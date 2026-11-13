#!/usr/bin/env python3
"""Монитор выдачи Avito: обновляет страницу и сообщает о новых объявлениях и смене цен."""

import argparse
import asyncio
import html
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import webbrowser
import winsound
from collections import deque
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "общий-лог.txt"
LEGACY_LOG = BASE_DIR / "watch.log"
CHANGES_FILE = BASE_DIR / "изменения.txt"
LIVE_FILE = BASE_DIR / "лог.html"
SHOTS_DIR = BASE_DIR / "shots"
PROFILE_DIR = BASE_DIR / "chrome-profile"
CONFIG_FILE = BASE_DIR / "config.json"

APP_VERSION = "1.0.0"

URL = (
    "https://www.avito.ru/all/tovary_dlya_kompyutera/komplektuyuschie/"
    "videokarty-ASgBAgICAkTGB~pm7gmmZw"
    "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6IkxiQTEydHhZZWJObTlETDgiO32DDLbeJgAAAA"
    "&f=ASgBAgECAkTGB~pm7gmmZwFFxpoMFXsiZnJvbSI6MCwidG8iOjI2MDAwfQ"
    "&q=rtx+3060+12gb&s=104"
)

ITEM_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const cards = document.querySelectorAll('[data-marker="item"]');
  for (const el of cards) {
    const a = el.querySelector('a[data-marker="item-title"]')
           || el.querySelector('a[itemprop="url"]')
           || el.querySelector('h3 a');
    if (!a) continue;
    const href = a.href;
    const m = href.match(/_(\d{6,})(?:\?|$)/);
    const id = m ? m[1] : href;
    if (seen.has(id)) continue;
    seen.add(id);

    let title = (a.textContent || '').trim();
    if (!title) {
      const t = el.querySelector('[itemprop="name"]');
      if (t) title = (t.textContent || '').trim();
    }

    let price = null;
    const pEl = el.querySelector('[itemprop="price"]');
    if (pEl) {
      const c = pEl.getAttribute('content');
      if (c) price = parseInt(c.replace(/\D/g, ''), 10);
      if (!price) {
        const mm = (pEl.textContent || '').match(/(\d[\d\s\u00a0]*)/);
        if (mm) price = parseInt(mm[1].replace(/\D/g, ''), 10);
      }
    }
    out.push({id: id, title: title, price: price || null, url: href});
  }
  return out;
}
"""

BLOCK_JS = r"""
() => {
  const t = (document.body ? document.body.innerText : '').toLowerCase();
  const u = location.href.toLowerCase();
  if (u.includes('/blocked') || u.includes('captcha')) return true;
  return t.includes('подтвердите, что вы не робот')
      || t.includes('доступ ограничен')
      || t.includes('слишком много запросов')
      || t.includes('вы не робот');
}
"""

ALERT_QUEUE = queue.Queue()


def ts():
    return datetime.now().strftime("%H:%M:%S")


LOG_BUFFER = deque(maxlen=400)
_LIVE_LOCK = threading.Lock()

SESSION_START = time.time()
TOTAL_BASE = 0.0
TOTAL_CYCLES = 0
FIRST_RUN = 0.0


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} д {hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


def session_uptime():
    return time.time() - SESSION_START


def total_uptime():
    return TOTAL_BASE + session_uptime()


def since_first_run():
    if not FIRST_RUN:
        return 0.0
    return max(0.0, time.time() - FIRST_RUN)


def detect_first_run():
    """Когда программа впервые запускалась: по первой записи общего лога."""
    if LOG_FILE.exists():
        try:
            with LOG_FILE.open("r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline().strip()
            m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", first)
            if m:
                return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            return LOG_FILE.stat().st_ctime
        except Exception:
            pass
    return time.time()

LIVE_TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>Avito watch — живой лог</title>
<style>
  body {{ margin:0; background:#12161f; color:#dfe4ee;
         font:13px/1.5 Consolas,"Cascadia Mono",monospace; }}
  .top {{ position:sticky; top:0; background:#1a2030; padding:12px 16px;
          border-bottom:1px solid #2a3448; display:flex;
          justify-content:space-between; align-items:center; }}
  .top b {{ font-family:"Segoe UI",sans-serif; font-size:15px; color:#ffd479; }}
  .top span {{ color:#7c8598; font-size:12px; }}
  .list {{ padding:8px 16px 40px; }}
  .row {{ padding:3px 0; border-bottom:1px solid #1b2130;
          display:flex; gap:10px; }}
  .t {{ color:#5f6a80; flex:0 0 68px; }}
  .m {{ white-space:pre-wrap; word-break:break-word; }}
  .info .m {{ color:#aeb7c8; }}
  .ok .m {{ color:#6ee7a8; }}
  .change .m {{ color:#ffd479; }}
  .warn .m {{ color:#ffab5e; }}
  .error .m {{ color:#ff6b6b; }}
  .empty {{ color:#5f6a80; padding:20px 0; }}
</style></head>
<body>
<div class="top"><b>Avito watch — живой лог</b><span>с первого запуска {since} · наработано {total} · этот запуск {session} · проверок {cycles} · обновлено {now}</span></div>
<div class="list">
{rows}
</div>
</body></html>
"""


def write_live():
    with _LIVE_LOCK:
        now = datetime.now().strftime("%H:%M:%S")
        if not LOG_BUFFER:
            rows = '<div class="empty">Пока пусто — запусти мониторинг.</div>'
        else:
            rows = "\n".join(
                f'<div class="row {kind}"><span class="t">{stamp}</span>'
                f'<span class="m">{html.escape(text)}</span></div>'
                for stamp, kind, text in reversed(LOG_BUFFER)
            )
        try:
            LIVE_FILE.write_text(
                LIVE_TEMPLATE.format(
                    now=now,
                    since=fmt_duration(since_first_run()),
                    total=fmt_duration(total_uptime()),
                    session=fmt_duration(session_uptime()),
                    cycles=TOTAL_CYCLES,
                    rows=rows,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass


def log(msg, kind="info"):
    now = datetime.now()
    short = now.strftime("%H:%M:%S")
    print(f"[{short}] {msg}", flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{now:%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass
    LOG_BUFFER.append((short, kind, msg))
    write_live()


def load_recent_log(limit=250):
    """Поднимает историю прошлых запусков в живой лог."""
    if not LOG_FILE.exists():
        return
    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as fh:
            tail = deque(fh, maxlen=limit)
    except Exception:
        return
    for line in tail:
        line = line.rstrip("\n")
        if not line:
            continue
        if line.startswith("[") and "] " in line:
            head, text = line[1:].split("] ", 1)
            stamp = head[-8:] if len(head) > 8 else head
        else:
            stamp, text = "", line
        kind = "info"
        if "ИЗМЕНЕНИЯ" in text or text.strip().startswith("[НОВОЕ") or "ЦЕНА" in text:
            kind = "change"
        elif "ошибк" in text.lower() or "не удалось" in text.lower():
            kind = "error"
        elif "запуск" in text.lower() or "срез" in text.lower():
            kind = "ok"
        LOG_BUFFER.append((stamp, kind, text))


def migrate_log():
    if not LOG_FILE.exists() and LEGACY_LOG.exists():
        try:
            LEGACY_LOG.replace(LOG_FILE)
        except Exception:
            pass


def money(value):
    if value is None:
        return "цена не видна"
    return f"{value:,}".replace(",", " ") + " ₽"


def gentle_beep():
    """Умеренный системный сигнал, не режущий слух."""
    try:
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass


def popup_worker(q):
    """Отдельный поток с tkinter: не мешает браузеру и не блокирует цикл."""
    try:
        import tkinter as tk
    except Exception:
        log("tkinter недоступен — оповещение только звуком и в консоли")
        return

    root = tk.Tk()
    root.withdraw()
    state = {"count": 0}

    def show(payload):
        state["count"] += 1
        win = tk.Toplevel(root)
        win.title("Avito: изменения")
        win.configure(bg="#1f2430")
        win.attributes("-topmost", True)
        win.resizable(False, False)

        head = tk.Label(
            win, text=f"Изменения в выдаче — {payload['time']}",
            bg="#1f2430", fg="#ffd479",
            font=("Segoe UI", 11, "bold"), anchor="w", justify="left",
        )
        head.pack(fill="x", padx=14, pady=(12, 6))

        body = tk.Label(
            win, text=payload["text"], bg="#1f2430", fg="#e8e8e8",
            font=("Segoe UI", 9), anchor="w", justify="left", wraplength=430,
        )
        body.pack(fill="both", padx=14)

        row = tk.Frame(win, bg="#1f2430")
        row.pack(fill="x", padx=14, pady=12)

        def open_first():
            if payload.get("url"):
                webbrowser.open(payload["url"])

        tk.Button(row, text="Открыть", command=open_first, width=12).pack(side="left")
        tk.Button(row, text="Закрыть", command=win.destroy, width=12).pack(side="left", padx=8)

        win.update_idletasks()
        w = max(win.winfo_reqwidth(), 460)
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = sw - w - 24
        y = sh - h - 70 - (state["count"] - 1) * 40
        win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 60)}")
        win.lift()

    def poll():
        try:
            while True:
                show(q.get_nowait())
        except queue.Empty:
            pass
        root.after(300, poll)

    root.after(300, poll)
    root.mainloop()


def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
            data.setdefault("watches", {})
            if data.get("items") and not data["watches"]:
                data["watches"]["default"] = {
                    "items": data.pop("items"),
                    "missing": data.pop("missing", {}),
                    "reported_removed": data.pop("reported_removed", []),
                }
            data.pop("items", None)
            data.pop("missing", None)
            data.pop("reported_removed", None)
            return data
        except Exception as exc:
            log(f"не смог прочитать state.json ({exc}), начинаю заново")
    return {"watches": {}}


def watch_section(state, wid):
    w = state.setdefault("watches", {}).setdefault(wid, {})
    w.setdefault("items", {})
    w.setdefault("missing", {})
    w.setdefault("reported_removed", [])
    return w


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def tick(state):
    """Считает выполненную проверку и накопленное время работы."""
    global TOTAL_CYCLES
    TOTAL_CYCLES += 1
    state["total_cycles"] = TOTAL_CYCLES
    state["total_seconds"] = round(TOTAL_BASE + session_uptime())
    save_state(state)


def collect_items(raw):
    items = {}
    for it in raw:
        iid = it.get("id")
        if not iid:
            continue
        items[iid] = {
            "title": (it.get("title") or "").strip(),
            "price": it.get("price"),
            "url": it.get("url"),
        }
    return items


def build_report(added, changed, removed):
    lines = []
    for it in added:
        lines.append(f"[НОВОЕ] {money(it['price'])}\n    {it['title'][:90]}")
    for old, new in changed:
        mark = "дешевле" if (new["price"] or 0) < (old["price"] or 0) else "дороже"
        lines.append(
            f"[ЦЕНА, {mark}] {money(old['price'])} -> {money(new['price'])}\n    {new['title'][:90]}"
        )
    for it in removed:
        lines.append(f"[СНЯТО] {money(it['price'])}\n    {it['title'][:90]}")
    return "\n\n".join(lines)


def write_changes(added, changed, removed, shot=None, note=None, watch=None):
    """Пишет каждое изменение отдельными строками в изменения.txt."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = [f"\n=== {stamp} =========="]

    if watch:
        out.append(f"[ССЫЛКА] {watch.get('name', '')} — {watch.get('url', '')}")

    if note:
        out.append(note)

    for it in added:
        out.append(f"[НОВОЕ ОБЪЯВЛЕНИЕ] {money(it.get('price'))}")
        out.append(f"    {it.get('title', '')}")
        out.append(f"    {it.get('url', '')}")

    for old, new in changed:
        po, pn = old.get("price"), new.get("price")
        if po and pn:
            if pn < po:
                kind = f"ЦЕНА СНИЖЕНА на {money(po - pn)}"
            elif pn > po:
                kind = f"ЦЕНА ВЫРОСЛА на {money(pn - po)}"
            else:
                kind = "ЦЕНА ИЗМЕНИЛАСЬ"
        else:
            kind = "ЦЕНА ИЗМЕНИЛАСЬ"
        out.append(f"[{kind}] {money(po)} -> {money(pn)}")
        out.append(f"    {new.get('title', '')}")
        out.append(f"    {new.get('url', '')}")

    for it in removed:
        out.append(f"[СНЯТО С ПРОДАЖИ] {money(it.get('price'))}")
        out.append(f"    {it.get('title', '')}")
        out.append(f"    {it.get('url', '')}")

    if shot:
        out.append(f"    скриншот: shots\\{shot.name}")

    try:
        with CHANGES_FILE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
    except Exception as exc:
        log(f"не смог записать изменения.txt: {exc}")


def diff(state, fresh, track_removed=True):
    old = state["items"]
    missing = state["missing"]
    reported = set(state["reported_removed"])

    added, changed, removed = [], [], []

    for iid, it in fresh.items():
        if iid not in old:
            added.append(it)
        else:
            po, pn = old[iid].get("price"), it.get("price")
            if po and pn and po != pn:
                changed.append((old[iid], it))
        missing.pop(iid, None)

    if not track_removed:
        state["missing"] = {}
        state["reported_removed"] = []
        return added, changed, removed

    for iid, it in old.items():
        if iid in fresh:
            continue
        missing[iid] = missing.get(iid, 0) + 1
        if missing[iid] >= 2 and iid not in reported:
            removed.append(it)
            reported.add(iid)

    state["reported_removed"] = sorted(reported)
    return added, changed, removed


def hide_chrome_from_taskbar(delay=4.0):
    """Убирает окно Chrome мониторинга из панели задач, оставляя его рабочим."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        import psutil
    except Exception:
        return

    time.sleep(delay)

    root = os.getpid()
    pids = set()
    try:
        for child in psutil.Process(root).children(recursive=True):
            try:
                if child.name().lower() == "chrome.exe":
                    pids.add(child.pid)
            except Exception:
                continue
    except Exception:
        return
    if not pids:
        return

    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                  (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
            found.append(hwnd)
        return True

    try:
        user32.EnumWindows(callback, 0)
    except Exception:
        return
    if found:
        log(f"окно Chrome убрано из панели задач ({len(found)})")


def free_profile():
    """Закрывает зависшие окна Chrome, которые держат профиль мониторинга."""
    if not sys.platform.startswith("win"):
        return 0
    profile = str(PROFILE_DIR)
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }}; "
        "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue }; "
        "($p | Measure-Object).Count"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True, text=True, timeout=25,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000 if sys.platform.startswith("win") else 0,
        )
        count = int((res.stdout or "0").strip().splitlines()[-1] or 0)
    except Exception:
        return 0
    if count:
        log(f"освободил профиль: закрыто зависших окон Chrome — {count}", "warn")
        time.sleep(2)
    return count


def short_exc(exc):
    text = str(exc).strip()
    return text.splitlines()[0][:140] if text else type(exc).__name__


def label_from_url(url):
    try:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        if qs.get("q"):
            return qs["q"][0][:40]
        path = urlparse(url).path.strip("/").split("/")[-1]
        return path[:40] or "ссылка"
    except Exception:
        return "ссылка"


def load_watches(args):
    """Ссылки для наблюдения: из config.json, иначе из аргументов."""
    cfg = {}
    cfg_path = Path(args.config) if getattr(args, "config", None) else CONFIG_FILE
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            log(f"не смог прочитать {cfg_path.name}: {exc}", "error")
            cfg = {}

    if cfg.get("interval"):
        args.interval = int(cfg["interval"])
    if cfg.get("start_delay") is not None:
        args.start_delay = int(cfg["start_delay"])
    if cfg.get("limit") is not None and not getattr(args, "limit_explicit", False):
        args.limit = int(cfg["limit"])

    watches = []
    for i, w in enumerate(cfg.get("watches", []), 1):
        url = (w.get("url") or "").strip()
        if not url or not w.get("enabled", True):
            continue
        watches.append({
            "id": str(w.get("id") or f"w{i}"),
            "url": url,
            "limit": int(w.get("limit") or 0),
            "name": (w.get("name") or "").strip() or label_from_url(url),
        })

    if not watches:
        url = (getattr(args, "url", None) or URL).strip()
        watches.append({
            "id": "default",
            "url": url,
            "limit": 0,
            "name": label_from_url(url),
        })
    return watches


async def check_watch(page, w, state, args):
    ws = watch_section(state, w["id"])
    limit = w.get("limit") or args.limit

    try:
        await page.goto(w["url"], wait_until="domcontentloaded", timeout=90000)
    except Exception as exc:
        if page.is_closed():
            raise
        log(f"[{w['name']}] страница не открылась: {short_exc(exc)}", "warn")
        return None

    await accept_cookies(page)

    if not await wait_items(page, 30000):
        if page.is_closed():
            raise
        try:
            blocked = await page.evaluate(BLOCK_JS)
        except Exception:
            blocked = False
        if blocked:
            log(f"[{w['name']}] капча/блокировка — реши вручную в окне Chrome", "warn")
            gentle_beep()
            await snapshot(page, w["id"])
        else:
            log(f"[{w['name']}] объявлений на странице не нашёл", "warn")
        return None

    raw = await page.evaluate(ITEM_JS)
    fresh = collect_items(raw)
    if limit and len(fresh) > limit:
        fresh = dict(list(fresh.items())[:limit])
    if not fresh:
        log(f"[{w['name']}] список объявлений пуст — пропускаю", "warn")
        return None

    if not ws["items"]:
        ws["items"] = fresh
        ws["missing"] = {}
        save_state(state)
        log(f"[{w['name']}] базовый срез: {len(fresh)} объявлений", "ok")
        return None

    added, changed, removed = diff(ws, fresh, track_removed=not limit)
    ws["items"] = fresh
    save_state(state)

    if not (added or changed or removed):
        return None

    shot = await snapshot(page, w["id"])
    write_changes(added, changed, removed, shot, watch=w)
    return added, changed, removed, shot


async def accept_cookies(page):
    for label in ("Принять", "Хорошо", "Согласен"):
        try:
            btn = page.get_by_role("button", name=label, exact=False).first
            if await btn.count():
                await btn.click(timeout=2500)
                log("принял куки-баннер")
                return
        except Exception:
            continue


async def wait_items(page, timeout=25000):
    try:
        await page.wait_for_selector('[data-marker="item"]', timeout=timeout)
        return True
    except Exception:
        return False


async def snapshot(page, wid="default"):
    safe = re.sub(r"[^0-9A-Za-z_-]+", "", str(wid)) or "watch"
    path = SHOTS_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{safe}.png"
    for full in (True, False):
        try:
            await page.screenshot(path=str(path), full_page=full)
            if path.exists() and path.stat().st_size > 3000:
                return path
        except Exception as exc:
            log(f"скриншот не снялся: {str(exc).splitlines()[0][:120]}", "warn")
    return path if path.exists() else None


async def start_browser(p, args):
    """Поднимает Chrome с профилем мониторинга. Возвращает (ctx, page) или (None, None)."""
    free_profile()
    log(f"запускаю Chrome, профиль: {PROFILE_DIR}")
    base_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-background-mode",
        "--start-maximized",
    ]
    if args.hide:
        base_args += ["--window-position=-3200,-3200", "--window-size=1280,900"]

    ctx = None
    attempts = [
        ("с включённой песочницей", True, base_args),
        ("без песочницы", False, base_args + ["--test-type"]),
    ]
    for label, sandbox, launch_args in attempts:
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                viewport=None,
                chromium_sandbox=sandbox,
                args=launch_args,
            )
            if not sandbox:
                log("Chrome запущен без песочницы — для этой задачи безопасно", "warn")
            break
        except Exception as exc:
            log(f"Chrome не открылся ({label}): {short_exc(exc)}", "warn")
            ctx = None

    if ctx is None:
        log("Chrome не открылся. Профиль занят или браузер не найден.", "error")
        return None, None

    await ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    page.set_default_timeout(30000)

    if args.hide:
        await asyncio.to_thread(hide_chrome_from_taskbar)

    return ctx, page


async def run(args):
    global TOTAL_BASE, TOTAL_CYCLES

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    migrate_log()
    state = load_state()
    baseline = True

    TOTAL_BASE = float(state.get("total_seconds", 0) or 0)
    TOTAL_CYCLES = int(state.get("total_cycles", 0) or 0)
    state["sessions"] = int(state.get("sessions", 0) or 0) + 1

    load_recent_log()
    log(
        f"=== Avito Watch {APP_VERSION} · запуск №{state['sessions']}. Всего наработано: {fmt_duration(TOTAL_BASE)}, "
        f"проверок за всё время: {TOTAL_CYCLES} ===",
        "ok",
    )
    save_state(state)

    write_live()
    if args.live:
        webbrowser.open(LIVE_FILE.as_uri())

    threading.Thread(target=popup_worker, args=(ALERT_QUEUE,), daemon=True).start()

    if args.test:
        demo_added = [{
            "title": "Тестовая видеокарта RTX 3060 12 гб",
            "price": 20000,
            "url": "https://www.avito.ru/",
        }]
        demo_changed = [(
            {"title": "Тестовая карта", "price": 23000, "url": "https://www.avito.ru/"},
            {"title": "Тестовая карта", "price": 19500, "url": "https://www.avito.ru/"},
        )]
        write_changes(demo_added, demo_changed, [], note="[ТЕСТ] проверка записи в лог")
        ALERT_QUEUE.put({
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": build_report(demo_added, demo_changed, []) + "\n\nЭто тест, в выдаче ничего не менялось.",
            "url": "https://www.avito.ru/",
        })
        gentle_beep()
        log("тестовое оповещение: окно и запись в изменения.txt")
        await asyncio.sleep(20)
        return

    async with async_playwright() as p:
        ctx, page = await start_browser(p, args)
        if ctx is None:
            return

        if args.login:
            log("открываю avito.ru — войди в аккаунт в этом окне")
            await page.goto("https://www.avito.ru/", wait_until="domcontentloaded", timeout=90000)
            await accept_cookies(page)
            print("\n>>> Войди в свой аккаунт Avito в открывшемся окне Chrome.")
            print(">>> Когда закончишь, вернись сюда и нажми Enter.\n", flush=True)
            await asyncio.to_thread(input, "")
            log("вход сохранён в профиле, окно закрываю")
            await ctx.close()
            return

        watches = load_watches(args)
        log(
            f"под наблюдением ссылок: {len(watches)} — "
            + "; ".join(w["name"] for w in watches)
        )

        if args.start_delay > 0:
            log(f"стартовая пауза {args.start_delay} с — всё, что уже висит, изменениями не считаю")
            await asyncio.sleep(args.start_delay)

        warned = False
        cycle = 0
        while True:
            cycle += 1
            started = time.time()
            found = []
            closed = False

            for num, w in enumerate(watches, 1):
                if page.is_closed() or not ctx.pages:
                    closed = True
                    break
                try:
                    res = await check_watch(page, w, state, args)
                except Exception as exc:
                    if page.is_closed():
                        closed = True
                        break
                    log(f"[{w['name']}] ошибка проверки: {short_exc(exc)}", "warn")
                    continue
                if res:
                    found.append((num, w, res))

            if closed:
                log("окно Chrome закрыто — поднимаю браузер заново", "warn")
                try:
                    await ctx.close()
                except Exception:
                    pass
                ctx = page = None
                for attempt in range(1, 21):
                    await asyncio.sleep(6)
                    try:
                        ctx, page = await start_browser(p, args)
                    except Exception as exc:
                        log(f"перезапуск не удался: {short_exc(exc)}", "warn")
                        ctx = None
                    if ctx is not None:
                        log("Chrome поднят, продолжаю проверки", "ok")
                        break
                    if attempt == 20:
                        log("браузер так и не поднялся — остановлено", "error")
                        break
                if ctx is None:
                    break
                continue

            tick(state)

            if found:
                parts = []
                for num, w, (added, changed, removed, _shot) in found:
                    parts.append(f"{num}) {w['name']}\n{build_report(added, changed, removed)}")
                    log(
                        f"[{w['name']}] ИЗМЕНЕНИЯ: новых {len(added)}, цен {len(changed)}, "
                        f"снятых {len(removed)}",
                        "change",
                    )
                first = found[0][2]
                first_url = (first[0] or [n for _, n in first[1]] or first[2])[0].get("url")
                ALERT_QUEUE.put({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "text": "\n\n".join(parts),
                    "url": first_url,
                })
                log("оповещение: звук и окно показаны", "change")
                gentle_beep()
            else:
                log(
                    f"проверка №{cycle}: {len(watches)} ссылок, изменений нет "
                    f"({time.time() - started:.1f} с)"
                )

            if args.cycles and cycle >= args.cycles:
                break

            elapsed = time.time() - started
            pause = max(5.0, args.interval + random.uniform(-args.jitter, args.jitter) - elapsed)
            try:
                await page.wait_for_timeout(int(pause * 1000))
            except Exception:
                continue
            if not warned and not args.once:
                log(f"интервал проверки: ~{args.interval} с (±{args.jitter})")
                warned = True

        state["total_seconds"] = round(TOTAL_BASE + session_uptime())
        state["total_cycles"] = TOTAL_CYCLES
        save_state(state)
        log(
            f"=== остановка. Этот запуск: {fmt_duration(session_uptime())}, "
            f"всего наработано: {fmt_duration(total_uptime())}, "
            f"проверок за всё время: {TOTAL_CYCLES} ===",
            "ok",
        )

        try:
            await ctx.close()
        except Exception as exc:
            log(f"не удалось закрыть Chrome: {exc}", "warn")
        await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Монитор выдачи Avito")
    parser.add_argument("--interval", type=int, default=45, help="секунд между проверками")
    parser.add_argument("--jitter", type=int, default=10, help="случайный разброс, секунд")
    parser.add_argument("--once", action="store_true", help="один проход и выход")
    parser.add_argument("--start-delay", type=int, default=60,
                        help="пауза после открытия страницы, секунд (по умолчанию 60)")
    parser.add_argument("--login", action="store_true", help="войти в аккаунт Avito и сохранить вход")
    parser.add_argument("--test", action="store_true", help="проверить оповещение и запись в лог")
    parser.add_argument("--live", action="store_true", help="открыть живой лог в браузере")
    parser.add_argument("--cycles", type=int, default=0, help="сколько проверок сделать (0 — без ограничения)")
    parser.add_argument("--limit", type=int, default=7,
                        help="следить только за первыми N объявлениями (0 — за всей страницей)")
    parser.add_argument("--hide", action="store_true",
                        help="держать окно Chrome за краем экрана, ничего не перекрывать")
    parser.add_argument("--url", default=None, help="ссылка на выдачу (одна)")
    parser.add_argument("--config", default=None, help="файл config.json со списком ссылок")
    args = parser.parse_args()
    args.limit_explicit = any(a == "--limit" or a.startswith("--limit=") for a in sys.argv)
    if args.once:
        args.cycles = 1

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log("остановлено пользователем", "warn")
    except Exception as exc:
        first = str(exc).splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
        log(f"работа остановлена из-за ошибки: {first}", "error")


if __name__ == "__main__":
    main()
