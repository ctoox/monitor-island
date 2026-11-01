import sys
import paramiko
import re
import math
import warnings
warnings.filterwarnings("ignore")

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

C_BG_0 = QColor(14, 14, 20, 220)
C_BG_1 = QColor(18, 18, 26, 217)
C_TEXT = QColor(235, 237, 245)
C_LABEL = QColor(120, 125, 145)
C_DIM = QColor(80, 85, 100)
C_ACCENT = QColor(70, 140, 255)
C_GREEN = QColor(52, 199, 89)
C_ORANGE = QColor(255, 159, 10)
C_RED = QColor(255, 55, 95)
C_CYAN = QColor(100, 218, 255)
C_PURPLE = QColor(170, 100, 255)

def _font(mono=False, size=11, weight=QFont.Weight.Medium):
    f = QFont()
    if mono:
        f.setFamilies(["JetBrains Mono", "Cascadia Code", "Consolas", "SF Mono"])
    else:
        f.setFamilies(["Segoe UI Variable Display", "Microsoft YaHei UI", "SF Pro Display"])
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


class SSHWorker(QThread):
    data_ready = Signal(dict)

    def __init__(self):
        super().__init__()
        self.ssh = None
        self._running = True

    def connect_ssh(self):
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect('192.168.31.86', username='root', password='ctoo@ctoo@ctoo', timeout=5)
            return True
        except:
            self.ssh = None
            return False

    def cmd(self, c):
        try:
            if not self.ssh:
                if not self.connect_ssh():
                    return ""
            _, o, _ = self.ssh.exec_command(c, timeout=3)
            return o.read().decode('utf-8', errors='ignore').strip()
        except:
            self.connect_ssh()
            return ""

    def run(self):
        while self._running:
            try:
                d = {}

                # Check hermes-lite agent
                agent_running = bool(self.cmd("ps | grep hermes-lite.sh | grep agent | grep -v grep"))
                d["agent_running"] = agent_running

                # Check hermes-lite watchdog
                watchdog_running = bool(self.cmd("ps | grep hermes-lite.sh | grep watchdog | grep -v grep"))
                d["watchdog_running"] = watchdog_running

                d["running"] = agent_running

                # Get agent log info
                if agent_running:
                    log = self.cmd("tail -5 /var/log/hermes-lite.log 2>/dev/null")
                    if log:
                        # Check for recent activity
                        if "Initializing Feishu" in log:
                            d["status"] = "initializing"
                        elif "WebSocket-style polling" in log:
                            d["status"] = "connected"
                        elif "No chats found" in log:
                            d["status"] = "no_chat"
                        elif "restarted successfully" in log:
                            d["status"] = "restarted"
                        else:
                            d["status"] = "running"
                        
                        # Get last log time
                        m = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', log)
                        if m:
                            d["last_log_time"] = m.group(1)
                else:
                    d["status"] = "stopped"

                # Memory
                mem = self.cmd("cat /proc/meminfo | head -3")
                if mem:
                    total = avail = 0
                    for line in mem.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = int(parts[1])
                            if 'MemTotal' in line: total = kb
                            elif 'MemAvailable' in line: avail = kb
                    if total > 0:
                        used = total - avail
                        d["mem_total"] = round(total / 1024)
                        d["mem_used"] = round(used / 1024)
                        d["mem_pct"] = round(used / total * 100)

                # CPU via /proc/loadavg (lighter than top)
                loadavg = self.cmd("cat /proc/loadavg")
                if loadavg:
                    parts = loadavg.split()
                    if len(parts) >= 1:
                        try:
                            d["load"] = float(parts[0])
                        except:
                            pass

                # Uptime
                uptime = self.cmd("cat /proc/uptime")
                if uptime:
                    parts = uptime.split()
                    if len(parts) >= 1:
                        try:
                            d["uptime"] = int(float(parts[0]))
                        except:
                            pass

                # Feishu token status
                token_ok = bool(self.cmd("test -f /root/hermes-lite/conf/.token && echo ok"))
                d["token_ok"] = token_ok

                self.data_ready.emit(d)
            except Exception as e:
                pass

            self.msleep(10000)

    def stop(self):
        self._running = False
        self.wait()


class Monitor(QWidget):
    COMPACT_W, COMPACT_H = 180, 48
    EXPANDED_W, EXPANDED_H = 320, 290

    glowOffset = Property(float, lambda self: self._glow_offset, lambda self, v: (setattr(self, '_glow_offset', v), self.update()))

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hermes-Lite")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._expanded = False
        self._hovered = False
        self._drag_pos = QPoint()
        self._drag_moved = False
        self._phase = 0.0
        self._glow_offset = 0.0

        self.data = {
            "agent_running": False,
            "watchdog_running": False,
            "running": False,
            "status": "stopped",
            "cpu": 0,
            "mem_pct": 0,
            "mem_used": 0,
            "mem_total": 0,
            "load": 0,
            "uptime": 0,
            "token_ok": False,
        }
        self._cpu = 0
        self._mem_pct = 0
        self._load = 0

        self.resize(self.COMPACT_W, self.COMPACT_H)
        self._center_top()

        self._frame = QTimer(self)
        self._frame.timeout.connect(self._tick)
        self._frame.start(16)

        self._glow_anim = QPropertyAnimation(self, b"glowOffset")
        self._glow_anim.setDuration(2800)
        self._glow_anim.setStartValue(0.0)
        self._glow_anim.setEndValue(1.0)
        self._glow_anim.setLoopCount(-1)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._glow_anim.start()

        self._worker = SSHWorker()
        self._worker.data_ready.connect(self._on_data)
        self._worker.start()

    def _center_top(self):
        s = QApplication.primaryScreen().availableGeometry()
        self.move((s.width() - self.width()) // 2, s.top() + 16)

    def _on_data(self, d):
        for k, v in d.items():
            self.data[k] = v

    def _tick(self):
        self._phase += 0.04
        self._cpu += (self.data.get("cpu", 0) - self._cpu) * 0.15
        self._mem_pct += (self.data["mem_pct"] - self._mem_pct) * 0.15
        self._load += (self.data.get("load", 0) - self._load) * 0.15
        self.update()

    def closeEvent(self, e):
        self._worker.stop()

    def enterEvent(self, e):
        self._hovered = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def leaveEvent(self, e):
        self._hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()
            self._drag_moved = False

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            np = e.globalPosition().toPoint() - self._drag_pos
            if (np - self.pos()).manhattanLength() > 3:
                self._drag_moved = True
                self.move(np)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._drag_moved:
            self.toggle()

    def toggle(self):
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self):
        self._expanded = True
        cur = self.geometry()
        nx = cur.center().x() - self.EXPANDED_W // 2
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(350)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        anim.setStartValue(cur)
        anim.setEndValue(QRect(nx, cur.top(), self.EXPANDED_W, self.EXPANDED_H))
        anim.start()
        self._expand_anim = anim

    def _collapse(self):
        self._expanded = False
        cur = self.geometry()
        nx = cur.center().x() - self.COMPACT_W // 2
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(350)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        anim.setStartValue(cur)
        anim.setEndValue(QRect(nx, cur.top(), self.COMPACT_W, self.COMPACT_H))
        anim.start()
        self._collapse_anim = anim

    def _draw_bar(self, p, x, y, w, h, pct, color_l, color_r):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        fw = w * min(pct / 100, 1.0)
        if fw > 1:
            fg = QLinearGradient(x, 0, x + fw, 0)
            fg.setColorAt(0, color_l)
            fg.setColorAt(1, color_r)
            p.setBrush(fg)
            p.drawRoundedRect(QRectF(x, y, fw, h), h / 2, h / 2)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        r = min(h / 2, 24) if not self._expanded else 16
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, C_BG_0)
        grad.setColorAt(1, C_BG_1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        glow_a = 0.15 + 0.08 * math.sin(self._phase)
        if self._hovered:
            glow_a += 0.1
        g = QColor(70, 140, 255, int(255 * glow_a))
        p.setPen(QPen(QBrush(g), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        offset = self._glow_offset
        cx = w * offset
        band_w = w * 0.35
        fl = QLinearGradient(cx - band_w, 0, cx + band_w, 0)
        fl.setColorAt(0.0, QColor(255, 255, 255, 0))
        fl.setColorAt(0.5, QColor(100, 200, 255, 12))
        fl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fl)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if not self._expanded:
            self._draw_compact(p, w, h)
        else:
            self._draw_expanded(p, w, h)

        p.end()

    def _draw_compact(self, p, w, h):
        cy = h / 2

        dot_x = 24
        dot_r = 5
        if self.data["agent_running"]:
            dot_g = QLinearGradient(dot_x - 5, cy - 5, dot_x + 5, cy + 5)
            dot_g.setColorAt(0, C_GREEN)
            dot_g.setColorAt(1, QColor(30, 200, 100))
        else:
            dot_g = QLinearGradient(dot_x - 5, cy - 5, dot_x + 5, cy + 5)
            dot_g.setColorAt(0, C_RED)
            dot_g.setColorAt(1, QColor(200, 50, 50))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_g)
        p.drawEllipse(int(dot_x - dot_r), int(cy - dot_r), dot_r * 2, dot_r * 2)

        p.setPen(C_TEXT)
        p.setFont(_font(mono=True, size=13, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(42, 0, 120, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "HERMES")

        p.setPen(C_DIM if not self.data["agent_running"] else C_GREEN)
        p.setFont(_font(size=9))
        status = "ON" if self.data["agent_running"] else "OFF"
        p.drawText(QRectF(128, 0, 40, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, status)

    def _draw_expanded(self, p, w, h):
        pad = 24

        p.setPen(C_TEXT)
        p.setFont(_font(size=14, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(pad, 20, 200, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "HERMES-LITE")

        # Status indicators
        agent_ok = self.data["agent_running"]
        wd_ok = self.data["watchdog_running"]
        token_ok = self.data["token_ok"]

        # Agent status
        if agent_ok:
            p.setPen(C_GREEN)
            txt = "AGENT OK"
        else:
            p.setPen(C_RED)
            txt = "AGENT DOWN"
        p.setFont(_font(size=9, weight=QFont.Weight.Bold))
        p.drawText(QRectF(w - 90, 18, 70, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)

        # Watchdog status
        if wd_ok:
            p.setPen(C_GREEN)
            wd_txt = "WD OK"
        else:
            p.setPen(C_ORANGE)
            wd_txt = "WD DOWN"
        p.setFont(_font(size=8))
        p.drawText(QRectF(w - 90, 32, 70, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, wd_txt)

        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawLine(int(pad), 48, int(w - pad), 48)

        # Uptime
        y0 = 60
        uptime = self.data.get("uptime", 0)
        h_t, r_t = divmod(uptime, 3600)
        m_t, s_t = divmod(r_t, 60)

        p.setPen(C_LABEL)
        p.setFont(_font(size=9, weight=QFont.Weight.Medium))
        p.drawText(QRectF(pad, y0, 60, 14), Qt.AlignmentFlag.AlignLeft, "UPTIME")
        p.setPen(C_ORANGE)
        p.setFont(_font(mono=True, size=22, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(pad, y0 + 14, 160, 28), Qt.AlignmentFlag.AlignLeft, f"{h_t:02d}:{m_t:02d}:{s_t:02d}")

        # Status
        status = self.data.get("status", "unknown")
        p.setPen(C_CYAN if agent_ok else C_DIM)
        p.setFont(_font(size=9))
        status_map = {
            "running": "Polling messages...",
            "connected": "Feishu connected",
            "initializing": "Connecting...",
            "no_chat": "No chat configured",
            "stopped": "Not running",
        }
        p.drawText(QRectF(pad + 165, y0 + 20, 120, 16), Qt.AlignmentFlag.AlignLeft, status_map.get(status, status))

        # CPU / Load
        y1 = y0 + 48
        col_w = (w - pad * 2) / 2

        p.setPen(C_LABEL)
        p.setFont(_font(size=9, weight=QFont.Weight.Medium))
        p.drawText(QRectF(pad, y1, 30, 14), Qt.AlignmentFlag.AlignLeft, "LOAD")
        load_val = round(self._load, 2)
        p.setPen(C_TEXT)
        p.setFont(_font(mono=True, size=18, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(pad, y1 + 14, col_w, 24), Qt.AlignmentFlag.AlignLeft, f"{load_val:.2f}")

        # Token status
        p.setPen(C_LABEL)
        p.setFont(_font(size=9, weight=QFont.Weight.Medium))
        p.drawText(QRectF(pad + col_w, y1, 60, 14), Qt.AlignmentFlag.AlignLeft, "TOKEN")
        p.setPen(C_GREEN if token_ok else C_RED)
        p.setFont(_font(size=10, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(pad + col_w, y1 + 14, col_w, 24), Qt.AlignmentFlag.AlignLeft, "VALID" if token_ok else "MISSING")

        # Memory
        y2 = y1 + 42
        mem_val = int(round(self._mem_pct))
        bar_h = 4.0

        p.setPen(C_LABEL)
        p.setFont(_font(size=9, weight=QFont.Weight.Medium))
        p.drawText(QRectF(pad, y2, 30, 14), Qt.AlignmentFlag.AlignLeft, "MEM")
        mem_color_l = QColor(52, 199, 89) if mem_val < 70 else QColor(255, 159, 10) if mem_val < 90 else QColor(255, 55, 95)
        mem_color_r = QColor(30, 200, 100) if mem_val < 70 else QColor(255, 200, 50) if mem_val < 90 else QColor(255, 80, 100)
        p.setPen(C_TEXT)
        p.setFont(_font(mono=True, size=10, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(w - pad - 40, y2, 40, 14), Qt.AlignmentFlag.AlignRight, f"{mem_val}%")
        bar_w = w - pad * 2
        self._draw_bar(p, pad, y2 + 16, bar_w, bar_h, self._mem_pct, mem_color_l, mem_color_r)

        # Target IP
        p.setPen(QColor(255, 255, 255, 25))
        p.setFont(_font(size=8))
        p.drawText(QRectF(pad, h - 18, w - pad * 2, 12), Qt.AlignmentFlag.AlignCenter, "192.168.31.86 / GL-MT1300")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = Monitor()
    w.show()
    sys.exit(app.exec())
