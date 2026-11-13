#!/usr/bin/env python3
"""Окно управления монитором Avito."""

import json
import os
import math
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "общий-лог.txt"
LIVE_FILE = BASE_DIR / "лог.html"
CHANGES_FILE = BASE_DIR / "изменения.txt"
PID_FILE = BASE_DIR / "app.pid"
PROFILE_DIR = BASE_DIR / "chrome-profile"
SHOTS_DIR = BASE_DIR / "shots"

APP_VERSION = "1.0.0"

BG = "#08080b"
CARD = "#101015"
CARD_2 = "#15151c"
WELL = "#0b0b10"
LINE = "#23232c"
LINE_SOFT = "#1a1a22"

TEXT = "#f2f2f7"
MUTED = "#9a9aa8"
FAINT = "#5d5d6b"

ACCENT = "#8b5cf6"
ACCENT_2 = "#ec4899"
ACCENT_SOFT = "#1d1533"
ACCENT_TEXT = "#cbb6ff"
OK = "#6ee7b7"
WARN = "#fbbf24"
ERR = "#fb7185"

F_H1 = ("Segoe UI", 20, "bold")
F_CAP = ("Segoe UI", 8)
F_BIG = ("Segoe UI", 30, "bold")
F_LABEL = ("Segoe UI", 10, "bold")
F_BODY = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_TINY = ("Segoe UI", 8)
F_NUM = ("Consolas", 12, "bold")
F_MONO = ("Consolas", 9)

DEFAULT_URL = (
    "https://www.avito.ru/all/tovary_dlya_kompyutera/komplektuyuschie/"
    "videokarty-ASgBAgICAkTGB~pm7gmmZw"
    "?f=ASgBAgECAkTGB~pm7gmmZwFFxpoMFXsiZnJvbSI6MCwidG8iOjI2MDAwfQ"
    "&q=rtx+3060+12gb&s=104"
)


def label_from_url(url):
    try:
        qs = parse_qs(urlparse(url).query)
        if qs.get("q"):
            return qs["q"][0][:40]
        return urlparse(url).path.strip("/").split("/")[-1][:40] or "ссылка"
    except Exception:
        return "ссылка"


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{secs} с"


def rub(value):
    try:
        value = int(value)
    except Exception:
        return "—"
    return f"{value:,}".replace(",", " ") + " ₽"


def blend(c1, c2, t):
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


_IMAGE_CACHE = {}
_IMAGE_KEEP = []


def _corner_image(size, bg, edge, colors, border, corner, ss=8):
    key = ("c", size, bg, edge, tuple(colors), border, corner)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    img = tk.PhotoImage(width=size, height=size)
    total = float(ss * ss)
    outer = (size - 0.5) ** 2
    inner = max(0.0, size - 0.5 - border) ** 2
    cx = float(size) if corner in ("nw", "sw") else 0.0
    cy = float(size) if corner in ("nw", "ne") else 0.0
    for j in range(size):
        fill_col = colors[min(j, len(colors) - 1)]
        row = []
        for i in range(size):
            hits = 0
            inside = 0
            for sy in range(ss):
                yy = j + (sy + 0.5) / ss
                dy2 = (yy - cy) ** 2
                for sx in range(ss):
                    xx = i + (sx + 0.5) / ss
                    d2 = (xx - cx) ** 2 + dy2
                    if d2 <= outer:
                        hits += 1
                        if d2 <= inner:
                            inside += 1
            o = hits / total
            inn = inside / total
            if edge is None:
                col = blend(bg, fill_col, o)
            else:
                col = blend(bg, edge, o)
                if inn > 0:
                    col = blend(col, fill_col, inn)
            row.append(col)
        img.put("{" + " ".join(row) + "}", to=(0, j))
    _IMAGE_CACHE[key] = img
    _IMAGE_KEEP.append(img)
    return img


def _circle_image(diameter, color, bg, ss=8):
    key = ("o", diameter, color, bg)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    img = tk.PhotoImage(width=diameter, height=diameter)
    r = diameter / 2.0
    total = float(ss * ss)
    for j in range(diameter):
        row = []
        for i in range(diameter):
            hits = 0
            for sy in range(ss):
                yy = j + (sy + 0.5) / ss - r
                for sx in range(ss):
                    xx = i + (sx + 0.5) / ss - r
                    if xx * xx + yy * yy <= r * r:
                        hits += 1
            row.append(blend(bg, color, hits / total))
        img.put("{" + " ".join(row) + "}", to=(0, j))
    _IMAGE_CACHE[key] = img
    _IMAGE_KEEP.append(img)
    return img


def paint_round(canvas, x1, y1, x2, y2, r, fill=None, grad=None,
                edge=None, border=1, tags=()):
    """Скруглённая фигура со сглаженными (антиалиасными) углами."""
    bg = canvas.cget("bg")
    left, top = int(round(x1)), int(round(y1))
    right, bottom = int(round(x2)), int(round(y2))
    if right - left < 2 or bottom - top < 2:
        return
    r = int(round(min(r, (right - left) / 2, (bottom - top) / 2)))
    span = max(bottom - top - 1, 1)

    def color_at(y):
        if grad is not None:
            return blend(grad[0], grad[1], max(0.0, min(1.0, (y - top) / span)))
        return fill

    if grad is not None:
        for yy in range(top, bottom):
            canvas.create_line(left, yy, right - 1, yy,
                               fill=color_at(yy), tags=tags)
    else:
        canvas.create_rectangle(left, top, right - 1, bottom - 1,
                                fill=fill, outline="", tags=tags)

    if r > 1:
        spots = (
            ("nw", left, top), ("ne", right - r, top),
            ("sw", left, bottom - r), ("se", right - r, bottom - r),
        )
        for corner, px, py in spots:
            colors = [color_at(py + j) for j in range(r)]
            img = _corner_image(r, bg, edge, colors, border, corner)
            canvas.create_image(px, py, image=img, anchor="nw", tags=tags)
        if edge:
            canvas.create_line(left + r, top, right - r - 1, top,
                               fill=edge, tags=tags)
            canvas.create_line(left + r, bottom - 1, right - r - 1, bottom - 1,
                               fill=edge, tags=tags)
            canvas.create_line(left, top + r, left, bottom - r - 1,
                               fill=edge, tags=tags)
            canvas.create_line(right - 1, top + r, right - 1, bottom - r - 1,
                               fill=edge, tags=tags)
    elif edge:
        canvas.create_rectangle(left, top, right - 1, bottom - 1,
                                fill=fill, outline=edge, tags=tags)


def round_rect(canvas, x1, y1, x2, y2, r, fill="", outline="", tags=()):
    paint_round(canvas, x1, y1, x2, y2, r, fill=fill or None, edge=outline or None,
                tags=tags)


def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    cfg.setdefault("interval", 45)
    cfg.setdefault("start_delay", 0)
    cfg.setdefault("limit", 7)
    if not cfg.get("watches"):
        cfg["watches"] = [{
            "id": "w1", "name": label_from_url(DEFAULT_URL),
            "url": DEFAULT_URL, "enabled": True, "limit": 7,
        }]
    return cfg


def save_config(cfg):
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def pid_alive(pid):
    if not pid:
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return False


def engine_pid():
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return None
    return pid if pid_alive(pid) else None


def kill_engine():
    pid = PID_FILE.exists() and PID_FILE.read_text().strip()
    if pid:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    profile = str(PROFILE_DIR)
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }}; "
        "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        PID_FILE.unlink()
    except Exception:
        pass


def pythonw_exe():
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def chrome_exe_path():
    roots = [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for root in roots:
        if not root:
            continue
        candidate = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if candidate.exists():
            return str(candidate)
    return None


def monitor_chrome_pids():
    pids = set()
    profile = str(PROFILE_DIR).lower()
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if (proc.info.get("name") or "").lower() != "chrome.exe":
                    continue
                line = " ".join(proc.info.get("cmdline") or []).lower()
                if profile in line:
                    pids.add(int(proc.info["pid"]))
            except Exception:
                continue
    except Exception:
        pass
    return pids


def show_monitor_browser():
    """Показывает окно Chrome мониторинга как обычное окно с кнопкой в панели задач."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        pids = monitor_chrome_pids()
        found = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value.startswith("Chrome_WidgetWin"):
                    found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)

        if found:
            def area(hwnd):
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                return (rect.right - rect.left) * (rect.bottom - rect.top)

            hwnd = max(found, key=area)
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            width = min(1400, int(screen_w * 0.72))
            height = min(900, int(screen_h * 0.78))
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2 - 30)

            user32.ShowWindow(hwnd, 9)
            user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0040)
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass

    exe = chrome_exe_path()
    if exe:
        try:
            subprocess.Popen(
                [exe, f"--user-data-dir={PROFILE_DIR}", "--new-window",
                 "https://www.avito.ru/"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False
    return False


def dark_titlebar(window):
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class Panel(tk.Canvas):
    def __init__(self, parent, bg=BG, radius=16, pad=18, fill=CARD,
                 edge=LINE, stretch=False, min_height=0):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.radius = radius
        self.pad = pad
        self.fill = fill
        self.edge = edge
        self.stretch = stretch
        self.min_height = min_height
        self.body = tk.Frame(self, bg=fill)
        self._win = self.create_window(pad, pad, window=self.body,
                                       anchor="nw", tags="content")
        self.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._on_body)

    def _on_body(self, _e=None):
        if self.stretch:
            return
        want = max(self.body.winfo_reqheight() + self.pad * 2, self.min_height)
        if int(self.cget("height")) != want:
            self.configure(height=want)

    def _redraw(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        self.delete("deco")
        paint_round(self, 0.5, 0.5, w - 0.5, h - 0.5, self.radius,
                    fill=self.fill, edge=self.edge, tags="deco")
        if self.stretch:
            self.itemconfigure(self._win, width=max(10, w - self.pad * 2),
                               height=max(10, h - self.pad * 2))
        else:
            self.itemconfigure(self._win, width=max(10, w - self.pad * 2))
        self.tag_lower("deco")


class Btn(tk.Canvas):
    def __init__(self, parent, text, command, width=150, height=44, bg=CARD,
                 variant="ghost", font=F_BODY):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._pw, self._ph = width, height
        self._command = command
        self._variant = variant
        self._text = text
        self._font = font
        self._hover = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda _e: self._command())
        self._draw()

    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _draw(self):
        self.delete("all")
        r = min(16, self._ph / 2)
        if self._variant == "primary":
            top = blend(ACCENT, "#ffffff", 0.16 if self._hover else 0.0)
            bottom = blend(ACCENT_2, "#000000", 0.0 if self._hover else 0.1)
            paint_round(self, 0.5, 0.5, self._pw - 0.5, self._ph - 0.5, r,
                        grad=(top, bottom), tags="bg")
            fg = "#ffffff"
        elif self._variant == "danger":
            fill = "#3a1722" if self._hover else "#2a1119"
            paint_round(self, 0.5, 0.5, self._pw - 0.5, self._ph - 0.5, r,
                        fill=fill, edge="#5d2233")
            fg = ERR
        else:
            fill = "#1d1d26" if self._hover else CARD_2
            paint_round(self, 0.5, 0.5, self._pw - 0.5, self._ph - 0.5, r,
                        fill=fill, edge=LINE)
            fg = TEXT
        self.create_text(self._pw / 2, self._ph / 2, text=self._text,
                         fill=fg, font=self._font)


def _toggle_image(on, bg=CARD):
    key = ("toggle", bool(on), bg)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    w, h = 48, 30
    img = tk.PhotoImage(width=w, height=h)
    x1, y1, x2, y2, r = 1.0, 5.0, 47.0, 25.0, 10.0
    top = blend(ACCENT, "#ffffff", 0.18)
    bottom = ACCENT_2
    knob_cx = 35.0 if on else 13.0
    knob_cy = 15.0
    knob_r = 10.0
    ss = 4
    total = float(ss * ss)
    for y in range(h):
        if on:
            t = max(0.0, min(1.0, (y + 0.5 - y1) / (y2 - y1)))
            track = blend(top, bottom, t)
        else:
            track = "#262630"
        knob_col = "#ffffff" if on else "#8b8b99"
        row = []
        for x in range(w):
            inside_track = 0
            inside_knob = 0
            for sy in range(ss):
                py = y + (sy + 0.5) / ss
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    if x1 <= px <= x2 and y1 <= py <= y2:
                        cx = min(max(px, x1 + r), x2 - r)
                        cy = min(max(py, y1 + r), y2 - r)
                        if (px - cx) ** 2 + (py - cy) ** 2 <= r * r:
                            inside_track += 1
                    if (px - knob_cx) ** 2 + (py - knob_cy) ** 2 <= knob_r * knob_r:
                        inside_knob += 1
            col = bg
            if inside_track:
                col = blend(col, track, inside_track / total)
            if inside_knob:
                col = blend(col, knob_col, inside_knob / total)
            row.append(col)
        img.put("{" + " ".join(row) + "}", to=(0, y))
    _IMAGE_CACHE[key] = img
    _IMAGE_KEEP.append(img)
    return img


class Toggle(tk.Canvas):
    def __init__(self, parent, value=True, bg=CARD, command=None):
        super().__init__(parent, width=48, height=30, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.value = bool(value)
        self._command = command
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self):
        self.delete("all")
        image = _toggle_image(self.value, self.cget("bg"))
        self.create_image(0, 0, image=image, anchor="nw")

    def _toggle(self, _e):
        self.value = not self.value
        self._draw()
        if self._command:
            self._command()


class Spin(tk.Canvas):
    def __init__(self, parent, var, lo, hi, bg=CARD_2, width=96, height=34):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        self.lo, self.hi = lo, hi
        self._pw, self._ph = width, height
        self.bind("<Button-1>", self._click)
        self.bind("<MouseWheel>", self._wheel)
        self._draw()

    def _shift(self, step):
        try:
            value = int(self.var.get())
        except Exception:
            value = self.lo
        self.var.set(str(max(self.lo, min(self.hi, value + step))))
        self._draw()

    def _click(self, event):
        self._shift(-1 if event.x < 30 else 1)

    def _wheel(self, event):
        self._shift(1 if event.delta > 0 else -1)

    def _draw(self):
        self.delete("all")
        paint_round(self, 0.5, 0.5, self._pw - 0.5, self._ph - 0.5, 12,
                    fill=WELL, edge=LINE)
        self.create_text(15, self._ph / 2, text="−", fill=MUTED,
                         font=("Segoe UI", 12))
        self.create_text(self._pw - 15, self._ph / 2, text="+", fill=TEXT,
                         font=("Segoe UI", 12))
        self.create_text(self._pw / 2, self._ph / 2, text=self.var.get(),
                         fill=TEXT, font=("Consolas", 11, "bold"))


class ScrollColumn(tk.Frame):
    """Прокручиваемая колонка с тонким ползунком справа."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self._active = False
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar = tk.Canvas(self, width=9, bg=bg, highlightthickness=0, bd=0)
        self.bar.pack(side="right", fill="y", padx=(6, 0))
        self.bar.bind("<Button-1>", self._bar_jump)
        self.bar.bind("<B1-Motion>", self._bar_jump)
        self.bar.bind("<Configure>", lambda _e: self._draw_bar())

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self._sync())
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda _e: setattr(self, "_active", True))
        self.canvas.bind("<Leave>", lambda _e: setattr(self, "_active", False))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.bar.bind("<MouseWheel>", self._wheel)
        self.winfo_toplevel().bind_all("<MouseWheel>", self._wheel, add="+")

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync()

    def _sync(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._draw_bar()

    def _wheel(self, event):
        try:
            x0 = self.canvas.winfo_rootx()
            y0 = self.canvas.winfo_rooty()
            x1 = x0 + self.canvas.winfo_width()
            y1 = y0 + self.canvas.winfo_height()
        except tk.TclError:
            return
        if not (x0 <= event.x_root <= x1 and y0 <= event.y_root <= y1):
            return
        top, bottom = self.canvas.yview()
        if bottom - top >= 0.999:
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        self._draw_bar()

    def _bar_jump(self, event):
        height = max(self.bar.winfo_height(), 1)
        self.canvas.yview_moveto(max(0.0, min(1.0, event.y / height - 0.05)))
        self._draw_bar()

    def _draw_bar(self):
        c = self.bar
        c.delete("all")
        height = c.winfo_height()
        if height < 24:
            return
        first, last = self.canvas.yview()
        if last - first > 0.995:
            return
        y1 = first * height
        y2 = max(y1 + 26, last * height)
        round_rect(c, 1, y1 + 1, 8, min(y2, height) - 1, 3.5,
                   fill="#2b2b37")


class LinkRow(tk.Frame):
    def __init__(self, parent, app, watch):
        super().__init__(parent, bg=CARD)
        self.app = app
        self.watch = watch

        self.toggle = Toggle(self, value=watch.get("enabled", True), bg=CARD)
        self.toggle.pack(side="left", padx=(0, 16))

        self.name_var = tk.StringVar(value=watch.get("name", ""))
        self.url_var = tk.StringVar(value=watch.get("url", ""))

        self.name_entry = tk.Entry(
            self, textvariable=self.name_var, bg=CARD, fg=TEXT,
            insertbackground=ACCENT, relief="flat", font=F_LABEL, width=14,
            highlightthickness=0, bd=0,
        )
        self.name_entry.pack(side="left", padx=(0, 14))

        well = tk.Frame(self, bg=WELL, highlightthickness=1,
                        highlightbackground=LINE, highlightcolor=ACCENT)
        well.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.url_entry = tk.Entry(
            well, textvariable=self.url_var, bg=WELL, fg=MUTED,
            insertbackground=TEXT, relief="flat", font=F_TINY,
            highlightthickness=0, bd=0,
        )
        self.url_entry.pack(fill="x", padx=8, pady=6)

        Btn(self, "×", self.remove, width=32, height=32, bg=CARD,
            font=("Segoe UI", 11)).pack(side="left")

    def remove(self):
        self.app.delete_row(self)


class ListingRow(tk.Frame):
    def __init__(self, parent, title, price, url):
        super().__init__(parent, bg=CARD)
        self._url = url
        self._bg = CARD

        self.price = tk.Label(self, text=rub(price), bg=CARD, fg=TEXT,
                              font=F_NUM)
        self.price.pack(side="right", padx=(12, 0))

        self.title = tk.Label(self, text=title, bg=CARD, fg=MUTED,
                              font=F_SMALL, anchor="w")
        self.title.pack(side="left", fill="x", expand=True)

        for widget in (self, self.title, self.price):
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
            widget.bind("<Button-1>", self._open)
        self.configure(cursor="hand2")

    def _paint(self, color):
        self.configure(bg=color)
        self.title.configure(bg=color)
        self.price.configure(bg=color)

    def _enter(self, _e):
        self._paint(CARD_2)

    def _leave(self, _e):
        self._paint(CARD)

    def _open(self, _e):
        if self._url:
            webbrowser.open(self._url)


class LogWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._snapshot = None
        self._alive = True

        self.title("журнал — Avito Watch")
        self.configure(bg=BG)
        self.geometry("880x540")
        self.minsize(600, 340)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=20, pady=(16, 12))
        tk.Label(top, text="журнал", bg=BG, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        Btn(top, "в браузере", app.open_live, width=126, height=34, bg=BG,
            font=F_SMALL).pack(side="right")
        Btn(top, "скрыть", self.close, width=96, height=34, bg=BG,
            font=F_SMALL).pack(side="right", padx=8)

        panel = Panel(self, bg=BG, radius=14, pad=2, fill=WELL,
                      edge=LINE, stretch=True)
        panel.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.text = tk.Text(panel.body, bg=WELL, fg="#c3c3d0",
                            insertbackground=ACCENT, relief="flat",
                            font=F_MONO, wrap="word",
                            padx=14, pady=12, bd=0, highlightthickness=0,
                            spacing1=1, spacing3=1)
        self.text.pack(side="left", fill="both", expand=True)
        self.bar = SlimScroll(panel.body)
        self.bar.pack(side="right", fill="y", padx=(0, 6), pady=8)
        self.bar.attach(self.text)
        self.text.tag_configure("change", foreground=ACCENT_TEXT)
        self.text.tag_configure("warn", foreground=WARN)
        self.text.tag_configure("error", foreground=ERR)
        self.text.tag_configure("ok", foreground=OK)
        self.text.configure(state="disabled")

        dark_titlebar(self)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._tick()

    def _tick(self):
        if not self._alive:
            return
        try:
            self._refresh()
        except tk.TclError:
            return
        self.after(1500, self._tick)

    def _refresh(self):
        lines = []
        if LOG_FILE.exists():
            try:
                with LOG_FILE.open("r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-200:]
            except Exception:
                lines = []
        snapshot = tuple(lines)
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        at_end = self.text.yview()[1] > 0.98
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if not lines:
            self.text.insert("end", "Пока пусто.", "warn")
        for line in lines:
            low = line.lower()
            tag = ""
            if "изменения" in low or "новое" in low or "цена" in low:
                tag = "change"
            elif "ошибк" in low or "не удалось" in low:
                tag = "error"
            elif "капча" in low or "не нашёл" in low:
                tag = "warn"
            elif "запуск" in low or "срез" in low or "остановка" in low:
                tag = "ok"
            self.text.insert("end", line if line.endswith("\n") else line + "\n", tag)
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def close(self):
        self._alive = False
        self.destroy()


class SlimScroll(tk.Canvas):
    def __init__(self, parent, bg=WELL):
        super().__init__(parent, width=8, bg=bg, highlightthickness=0, bd=0)
        self._first, self._last = 0.0, 1.0
        self._target = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._jump)
        self.bind("<B1-Motion>", self._jump)
        self._redraw()

    def attach(self, text):
        self._target = text
        text.configure(yscrollcommand=self.set_view)

    def set_view(self, first, last):
        self._first, self._last = float(first), float(last)
        self._redraw()

    def _jump(self, event):
        if self._target is None:
            return
        height = max(self.winfo_height(), 1)
        self._target.yview_moveto(max(0.0, min(1.0, event.y / height - 0.05)))

    def _redraw(self):
        self.delete("all")
        h = self.winfo_height()
        if h < 12:
            return
        y1 = self._first * h
        y2 = max(y1 + 20, self._last * h)
        round_rect(self, 1, y1 + 1, 7, min(y2, h) - 1, 3,
                   fill="#2e2e3a")


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        import ctypes

        self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\AvitoWatchApp")
        if ctypes.windll.kernel32.GetLastError() == 183:
            self.destroy()
            sys.exit(0)

        self.cfg = load_config()
        self.rows = []
        self.log_window = None
        self._status = None
        

        self.title(f"Avito Watch {APP_VERSION}")
        self.configure(bg=BG)
        self.geometry("1180x740")
        self.minsize(1040, 660)

        self._build()
        self.update_idletasks()
        dark_titlebar(self)
        self._refresh()
        self._paint_dot()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=26, pady=(22, 16))

        mark = tk.Canvas(top, width=38, height=38, bg=BG, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        paint_round(mark, 1, 1, 37, 37, 11, grad=(ACCENT, ACCENT_2))
        mark.create_text(19, 20, text="A", fill="#ffffff",
                         font=("Segoe UI", 15, "bold"))

        titles = tk.Frame(top, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="Avito Watch", bg=BG, fg=TEXT,
                 font=F_H1).pack(anchor="w")
        tk.Label(titles, text=f"следит за выдачей и сообщает об изменениях · v{APP_VERSION}",
                 bg=BG, fg=FAINT, font=F_TINY).pack(anchor="w")

        right = tk.Frame(top, bg=BG)
        right.pack(side="right")
        self.badge = tk.Canvas(right, width=200, height=40, bg=BG,
                               highlightthickness=0, bd=0)
        self.badge.pack(side="right")
        self.clock = tk.Label(right, text="", bg=BG, fg=FAINT, font=F_MONO)
        self.clock.pack(side="right", padx=14)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=26)

        left = tk.Frame(body, bg=BG, width=372)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        right_col = ScrollColumn(body, bg=BG)
        right_col.pack(side="left", fill="both", expand=True, padx=(18, 0))
        self.column = right_col

        self._hero(left)
        self._links(right_col.inner)
        self._listings(right_col.inner)
        self._log_teaser(right_col.inner)

        for watch in self.cfg["watches"]:
            self._add_row(watch)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _hero(self, parent):
        panel = Panel(parent, bg=BG, radius=22, pad=22, fill=CARD, edge=LINE,
                      stretch=True)
        panel.pack(fill="both", expand=True)
        body = panel.body

        tk.Label(body, text="СОСТОЯНИЕ", bg=CARD, fg=FAINT,
                 font=F_TINY).pack(anchor="w")

        self.status_row = tk.Frame(body, bg=CARD)
        self.status_row.pack(anchor="w", pady=(10, 0))
        self.dot = tk.Canvas(self.status_row, width=18, height=18, bg=CARD,
                             highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(0, 8))
        self.status_label = tk.Label(self.status_row, text="на паузе", bg=CARD,
                                     fg=MUTED, font=F_BODY)
        self.status_label.pack(side="left")

        self.big_value = tk.Label(body, text="0", bg=CARD, fg=TEXT,
                                  font=F_BIG)
        self.big_value.pack(anchor="w", pady=(22, 0))
        tk.Label(body, text="проверок всего", bg=CARD, fg=FAINT,
                 font=F_TINY).pack(anchor="w")

        meta = tk.Frame(body, bg=CARD)
        meta.pack(fill="x", pady=(22, 0))
        self.meta_uptime = self._meta(meta, "наработка")
        self.meta_links = self._meta(meta, "ссылок")
        self.meta_interval = self._meta(meta, "интервал")

        tk.Frame(body, bg=LINE_SOFT, height=1).pack(fill="x", pady=(20, 18))

        Btn(body, "ЗАПУСТИТЬ", self.start_engine, width=320, height=48,
            bg=CARD, variant="primary",
            font=("Segoe UI", 10, "bold")).pack(fill="x")
        Btn(body, "ОСТАНОВИТЬ", self.stop_engine, width=320, height=42,
            bg=CARD, variant="danger").pack(fill="x", pady=(8, 0))

        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x", pady=(14, 0))
        Btn(row, "журнал", self.open_log_window, width=150, height=36,
            bg=CARD, variant="ghost", font=F_SMALL).pack(side="left")
        Btn(row, "изменения", self.open_changes, width=150, height=36,
            bg=CARD, variant="ghost", font=F_SMALL).pack(side="right")

        Btn(body, "показать Chrome", self.show_browser, width=320, height=36,
            bg=CARD, variant="ghost", font=F_SMALL).pack(fill="x", pady=(10, 0))

        tk.Frame(body, bg=LINE_SOFT, height=1).pack(side="bottom", fill="x",
                                                    pady=(0, 12))
        self._signature(body, CARD, side="bottom")

    def _signature(self, parent, bg=BG, side=None):
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x", side=side or "top", pady=(10, 2))
        tk.Label(box, text="ГЛАВНЫЙ АВТОР", bg=bg, fg=FAINT,
                 font=F_TINY).pack(anchor="w")
        tk.Label(box, text="tatar4173", bg=bg, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(1, 0))
        line = tk.Frame(box, bg=bg)
        line.pack(anchor="w", pady=(3, 0))
        tk.Label(line, text="нейросеть ", bg=bg, fg=FAINT,
                 font=F_TINY).pack(side="left")
        tk.Label(line, text="MultiTool", bg=bg, fg=ACCENT_TEXT,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(line, text=" отвечает за всё", bg=bg, fg=FAINT,
                 font=F_TINY).pack(side="left")

    def _meta(self, parent, caption):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        value = tk.Label(row, text="—", bg=CARD, fg=TEXT, font=F_SMALL)
        value.pack(side="right")
        tk.Label(row, text=caption, bg=CARD, fg=FAINT,
                 font=F_TINY).pack(side="left")
        return value

    def _links(self, parent):
        panel = Panel(parent, bg=BG, radius=22, pad=20, fill=CARD, edge=LINE)
        panel.pack(fill="x")
        body = panel.body

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", pady=(0, 12))
        tk.Label(head, text="Ссылки на выдачу", bg=CARD, fg=TEXT,
                 font=F_LABEL).pack(side="left")
        self.limit_label = tk.Label(head, text="", bg=CARD, fg=FAINT,
                                    font=F_TINY)
        self.limit_label.pack(side="right")

        self.link_box = tk.Frame(body, bg=CARD)
        self.link_box.pack(fill="x")

        foot = tk.Frame(body, bg=CARD)
        foot.pack(fill="x", pady=(12, 0))
        Btn(foot, "+ добавить", self.add_row, width=130, height=34, bg=CARD,
            font=F_SMALL).pack(side="left")

        params = tk.Frame(foot, bg=CARD)
        params.pack(side="right")
        self.interval_var = tk.StringVar(value=str(self.cfg.get("interval", 45)))
        tk.Label(params, text="каждые", bg=CARD, fg=FAINT,
                 font=F_TINY).pack(side="left", padx=(0, 6))
        Spin(params, self.interval_var, 10, 600, bg=CARD).pack(side="left")
        tk.Label(params, text="сек", bg=CARD, fg=FAINT,
                 font=F_TINY).pack(side="left", padx=(6, 16))

        self.limit_var = tk.StringVar(value=str(self.cfg.get("limit", 7)))
        tk.Label(params, text="первые", bg=CARD, fg=FAINT,
                 font=F_TINY).pack(side="left", padx=(0, 6))
        Spin(params, self.limit_var, 1, 50, bg=CARD).pack(side="left")

    def _listings(self, parent):
        panel = Panel(parent, bg=BG, radius=22, pad=20, fill=CARD, edge=LINE)
        panel.pack(fill="x", pady=(18, 0))
        body = panel.body

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Объявления", bg=CARD, fg=TEXT,
                 font=F_LABEL).pack(side="left")
        self.count_label = tk.Label(head, text="", bg=CARD, fg=FAINT,
                                    font=F_TINY)
        self.count_label.pack(side="right")

        tk.Frame(body, bg=LINE_SOFT, height=1).pack(fill="x", pady=(0, 6))

        self.list_box = tk.Frame(body, bg=CARD)
        self.list_box.pack(fill="x")

        self.empty_label = tk.Label(
            body, text="запусти мониторинг — здесь появятся объявления с ценами",
            bg=CARD, fg=FAINT, font=F_SMALL)
        self.empty_label.pack(pady=20)

    def _log_teaser(self, parent):
        panel = Panel(parent, bg=BG, radius=22, pad=20, fill=CARD, edge=LINE)
        panel.pack(fill="x", pady=(18, 12))
        body = panel.body

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Журнал", bg=CARD, fg=TEXT,
                 font=F_LABEL).pack(side="left")
        Btn(head, "открыть", self.open_log_window, width=104, height=32,
            bg=CARD, font=F_SMALL).pack(side="right")
        Btn(head, "в браузере", self.open_live, width=118, height=32,
            bg=CARD, font=F_SMALL).pack(side="right", padx=8)

        tk.Frame(body, bg=LINE_SOFT, height=1).pack(fill="x", pady=(0, 8))

        wrap = tk.Frame(body, bg=WELL, highlightthickness=1,
                        highlightbackground=LINE_SOFT)
        wrap.pack(fill="x")
        self.preview = tk.Text(wrap, bg=WELL, fg="#b9b9c6", relief="flat",
                               font=F_MONO, wrap="word", height=9,
                               padx=12, pady=10, bd=0, highlightthickness=0,
                               spacing1=1, spacing3=1)
        self.preview.pack(fill="x")
        self.preview.tag_configure("change", foreground=ACCENT_TEXT)
        self.preview.tag_configure("warn", foreground=WARN)
        self.preview.tag_configure("error", foreground=ERR)
        self.preview.tag_configure("ok", foreground=OK)
        self.preview.configure(state="disabled")
        self._preview_sig = None

    def _add_row(self, watch):
        row = LinkRow(self.link_box, self, watch)
        row.pack(fill="x", pady=3)
        self.rows.append(row)
        return row

    def add_row(self):
        n = len(self.rows) + 1
        watch = {"id": f"w{int(time.time())}{n}", "name": "", "url": "",
                 "enabled": True, "limit": int(self.limit_var.get() or 7)}
        self.cfg.setdefault("watches", []).append(watch)
        self._add_row(watch)

    def delete_row(self, row):
        if row not in self.rows:
            return
        self.rows.remove(row)
        try:
            self.cfg["watches"].remove(row.watch)
        except ValueError:
            pass
        row.destroy()
        self.after(10, self.column._sync)

    def collect(self):
        watches = []
        for row in self.rows:
            url = row.url_var.get().strip()
            if not url:
                continue
            name = row.name_var.get().strip() or label_from_url(url)
            w = dict(row.watch)
            w.update({
                "url": url,
                "name": name,
                "enabled": bool(row.toggle.value),
                "limit": int(self.limit_var.get() or 7),
            })
            watches.append(w)
        try:
            interval = max(10, int(self.interval_var.get()))
        except Exception:
            interval = 45
        self.cfg.update({
            "interval": interval,
            "start_delay": 0,
            "limit": int(self.limit_var.get() or 7),
            "watches": watches,
        })
        return self.cfg

    def start_engine(self):
        cfg = self.collect()
        if not [w for w in cfg["watches"] if w.get("enabled")]:
            messagebox.showwarning("Avito Watch", "Нет включённых ссылок — нечего проверять.")
            return
        save_config(cfg)
        if engine_pid():
            kill_engine()
            time.sleep(1)
        proc = subprocess.Popen(
            [pythonw_exe(), str(BASE_DIR / "avito_watch.py"),
             "--config", str(CONFIG_FILE), "--hide"],
            cwd=str(BASE_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        self._refresh()

    def stop_engine(self):
        kill_engine()
        time.sleep(0.5)
        self._refresh()

    def open_log_window(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return
        self.log_window = LogWindow(self)

    def open_live(self):
        if LIVE_FILE.exists():
            os.startfile(str(LIVE_FILE))
        else:
            messagebox.showinfo("Avito Watch", "Живой лог появится после первого запуска.")

    def open_changes(self):
        if CHANGES_FILE.exists():
            os.startfile(str(CHANGES_FILE))
        else:
            messagebox.showinfo("Avito Watch", "Изменений пока не было.")

    def open_shots(self):
        SHOTS_DIR.mkdir(exist_ok=True)
        os.startfile(str(SHOTS_DIR))

    def show_browser(self):
        if show_monitor_browser():
            return
        messagebox.showinfo(
            "Avito Watch",
            "Не нашёл Chrome. Установи Google Chrome или запусти мониторинг.",
        )

    def _paint_dot(self):
        color = OK if self._status else MUTED
        self.dot.delete("all")
        ring = _circle_image(16, blend(CARD, color, 0.35), CARD)
        core = _circle_image(8, color, CARD)
        self.dot.create_image(1, 1, image=ring, anchor="nw")
        self.dot.create_image(5, 5, image=core, anchor="nw")

    def _draw_badge(self, running):
        c = self.badge
        c.delete("all")
        paint_round(c, 0.5, 2.5, 199.5, 37.5, 18,
                    fill="#0f1218" if not running else "#0d1714",
                    edge=LINE if not running else "#244a3d")
        color = OK if running else MUTED
        dot = _circle_image(8, color, "#0f1218" if not running else "#0d1714")
        c.create_image(17, 16, image=dot, anchor="nw")
        c.create_text(32, 20, text="работает" if running else "на паузе",
                      anchor="w", fill=color, font=F_SMALL)
        if running:
            c.create_text(182, 20, text="live", anchor="e",
                          fill=blend(OK, BG, 0.35), font=F_TINY)

    def _refresh(self):
        running = bool(engine_pid())
        if running != self._status:
            self._status = running
            self._draw_badge(running)
            self.status_label.configure(
                text="мониторинг идёт" if running else "на паузе",
                fg=OK if running else MUTED,
            )
            self._paint_dot()
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        total = data.get("total_seconds", 0) or 0
        cycles = data.get("total_cycles", 0) or 0
        self.big_value.configure(text=str(cycles))
        self.meta_uptime.configure(text=fmt_duration(total))
        self.meta_links.configure(text=str(len(self.rows)))
        self.meta_interval.configure(text=f"{self.interval_var.get()} с")
        self.limit_label.configure(
            text=f"следим за первыми {self.limit_var.get()} объявлениями"
        )
        self.clock.configure(text=time.strftime("%H:%M"))
        self._load_listings(data)
        self._refresh_preview()
        self.after(2000, self._refresh)

    def _refresh_preview(self):
        lines = []
        if LOG_FILE.exists():
            try:
                with LOG_FILE.open("r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-9:]
            except Exception:
                lines = []
        signature = tuple(lines)
        if signature == self._preview_sig:
            return
        self._preview_sig = signature
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if not lines:
            self.preview.insert("end", "пока пусто", "warn")
        for line in lines:
            low = line.lower()
            tag = ""
            if "изменения" in low or "новое" in low or "цена" in low:
                tag = "change"
            elif "ошибк" in low or "не удалось" in low:
                tag = "error"
            elif "капча" in low or "не нашёл" in low:
                tag = "warn"
            elif "запуск" in low or "срез" in low or "остановка" in low:
                tag = "ok"
            self.preview.insert("end", line if line.endswith("\n") else line + "\n", tag)
        self.preview.configure(state="disabled")

    def _load_listings(self, data):
        items = {}
        for watch in (data.get("watches") or {}).values():
            for item_id, info in (watch.get("items") or {}).items():
                items[item_id] = info
        ordered = list(items.values())[:14]
        self.count_label.configure(
            text=f"в срезе {len(items)}" if items else "пока пусто"
        )
        if not ordered:
            self.empty_label.pack(pady=20)
        else:
            self.empty_label.pack_forget()
        signature = tuple((i.get("title"), i.get("price")) for i in ordered)
        if signature == getattr(self, "_list_sig", None):
            return
        self._list_sig = signature
        for child in self.list_box.winfo_children():
            child.destroy()
        for info in ordered:
            ListingRow(self.list_box, str(info.get("title", "—"))[:90],
                       info.get("price"), info.get("url", "")).pack(fill="x", pady=5)
        self.after(10, self.column._sync)

    def on_close(self):
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
