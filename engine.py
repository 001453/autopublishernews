"""RSS haber akışı: şablon + aralık; hedef olarak X (Playwright), dosya kuyruğu veya Discord."""
from __future__ import annotations

import calendar
import html as html_module
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Sunucu/Docker: kalıcı veri (DATA_DIR=/app/data)."""
    raw = (os.environ.get("DATA_DIR") or "").strip()
    if raw:
        p = Path(raw)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return BASE_DIR


def resolve_config_path() -> Path:
    raw = (os.environ.get("PANEL_CONFIG_PATH") or "").strip()
    if raw:
        return Path(raw)
    return BASE_DIR / "panel_config.json"


STATE_DB = app_data_dir() / "posted.sqlite3"
CONFIG_PATH = resolve_config_path()

# Varsayılan RSS: yalnızca kripto odaklı, test edilmiş çalışan akışlar.
DEFAULT_FEEDS: list[str] = [
    # Türkçe kripto
    "https://koinmedya.com/feed/",
    "https://www.coinkolik.com/feed/",
    "https://www.btchaber.com/feed/",
    "https://tr.investing.com/rss/news_301.rss",
    "https://www.bitcoinsistemi.com/feed/",
    "https://www.coinotag.com/feed/",
    "https://koinbulteni.com/feed",
    "https://coin-turk.com/feed/",
    # Uluslararası kripto (özet Türkçe: OPENAI_API_KEY)
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://www.theblock.co/rss.xml",
    "https://decrypt.co/feed",
    "https://u.today/rss",
    "https://cryptopotato.com/feed/",
    "https://ambcrypto.com/feed/",
    "https://news.bitcoin.com/feed/",
]

# Panelde kategori etiketi (bilinen URL'ler).
FEED_LABELS: dict[str, dict[str, str]] = {
    "https://koinmedya.com/feed/": {"category": "Kripto", "label": "Koinmedya"},
    "https://www.coinkolik.com/feed/": {"category": "Kripto", "label": "Coinkolik"},
    "https://www.btchaber.com/feed/": {"category": "Kripto", "label": "BTCHaber"},
    "https://tr.investing.com/rss/news_301.rss": {"category": "Kripto", "label": "Investing.com TR (kripto)"},
    "https://www.bitcoinsistemi.com/feed/": {"category": "Kripto", "label": "Bitcoin Sistemi"},
    "https://www.coinotag.com/feed/": {"category": "Kripto", "label": "CoinOtag"},
    "https://koinbulteni.com/feed": {"category": "Kripto", "label": "Koin Bülteni"},
    "https://coin-turk.com/feed/": {"category": "Kripto", "label": "Coin-Turk"},
    "https://cointelegraph.com/rss": {"category": "Kripto", "label": "Cointelegraph"},
    "https://www.coindesk.com/arc/outboundfeeds/rss/": {"category": "Kripto", "label": "CoinDesk"},
    "https://www.theblock.co/rss.xml": {"category": "Kripto", "label": "The Block"},
    "https://decrypt.co/feed": {"category": "Kripto", "label": "Decrypt"},
    "https://u.today/rss": {"category": "Kripto", "label": "U.Today"},
    "https://cryptopotato.com/feed/": {"category": "Kripto", "label": "CryptoPotato"},
    "https://ambcrypto.com/feed/": {"category": "Kripto", "label": "AMBCrypto"},
    "https://news.bitcoin.com/feed/": {"category": "Kripto", "label": "Bitcoin.com News"},
}


def feeds_with_meta(urls: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for u in urls:
        u = str(u).strip()
        if not u:
            continue
        meta = FEED_LABELS.get(u, {})
        out.append(
            {
                "url": u,
                "category": meta.get("category", "Diğer"),
                "label": meta.get("label", u),
            }
        )
    return out

MAX_TWEET_LEN = 280
# Linkli şablonda özet üst sınırı; sadece metin şablonunda summary_max_chars() ~278 kullanılır.
SUMMARY_BODY_MAX_CHARS = 260
TEXT_ONLY_TEMPLATE = "📌 {summary}\n\n{hashtags}"
HASHTAG_COUNT = 2
HASHTAG_LINE_RESERVE = 40

# X paylaşımı için Türkçe haber üslubu (OpenAI system metni)
EDITORIAL_SUMMARY_STYLE = (
    "Üslup: Türkçe haber / kripto editörü dili; kuru özet değil, okunur mini haber metni.\n"
    "ÖZET iki paragraf olsun (arada tek boş satır):\n"
    "— 1. paragraf: Ana gelişme; mümkünse kişi veya kurum adıyla başla "
    "(ör. «Paolo Ardoino», «Coinbase CEO'su Brian Armstrong»). "
    "Açıklama fiilleri: açıkladı, söyledi, duyurdu, bildirdi, görüldü, geride bıraktı.\n"
    "— 2. paragraf: Detay, rakam, yüzde, ortaklık veya bağlam; somut veri varsa yaz.\n"
    "Özel isim, şirket, protokol adlarını koru; X hesabı varsa @Handle yazılabilir.\n"
    "Söyleşi/alıntı varsa Türkçe tırnak içinde ver («…» veya \"…\").\n"
    "«Haberine göre», «kaynaklarına göre», emoji, 📌 ve hashtag yazma."
)

ALLOWED_DESTINATIONS = frozenset({"x_browser", "file", "discord_webhook"})
OUTBOX_PATH = app_data_dir() / "publish_queue.txt"
DISCORD_MAX = 1900


class ManualPostPending(Exception):
    """Chrome'da manuel gönderim sekmesi açıldı; kuyruk silinmemeli."""


class TurkishContentRequired(RuntimeError):
    """İngilizce kaynak için Türkçe özet üretilemedi (çoğunlukla OPENAI_API_KEY eksik)."""


_TURKISH_CHARS = frozenset("ğüşıöçĞÜŞİÖÇ")
_EN_MARKERS = (
    " the ",
    " and ",
    " with ",
    " for ",
    " from ",
    " that ",
    " this ",
    " will ",
    " has ",
    " have ",
    " are ",
    " was ",
    " were ",
    " after ",
    " says ",
    " report",
    " according",
    " exchange",
    " bitcoin",
    " crypto",
)
_TR_MARKERS = (
    " ve ",
    " bir ",
    " için ",
    " ile ",
    " olan ",
    " bu ",
    " de ",
    " da ",
    " gibi ",
    " kadar ",
    " göre ",
    " yıl ",
    " tl ",
    " dolar ",
    " enflasyon",
    " merkez",
    " bankası",
)


def looks_likely_turkish(text: str) -> bool:
    raw = (text or "").strip()
    if len(raw) < 8:
        return False
    t = f" {raw.lower()} "
    tr_char = sum(1 for c in raw if c in _TURKISH_CHARS)
    tr_m = sum(1 for m in _TR_MARKERS if m in t)
    en_m = sum(1 for m in _EN_MARKERS if m in t)
    if tr_char >= 2 or tr_m >= 2:
        return True
    if en_m >= 2 and tr_m == 0 and tr_char == 0:
        return False
    return tr_m > en_m


def looks_likely_english(text: str) -> bool:
    return not looks_likely_turkish(text) and len((text or "").strip()) >= 16


def default_config() -> dict[str, Any]:
    return {
        "feeds": list(DEFAULT_FEEDS),
        "poll_interval_minutes": 15,
        "publish_interval_minutes": 30,
        "use_post_queue": True,
        "destination": "x_browser",
        "post_template": TEXT_ONLY_TEMPLATE,
        "discord_webhook_url": "",
        "x_watch_enabled": True,
        "x_watch_accounts": [
            "tetherwallet",
            "qvac",
            "usat",
            "tethergold",
            "USDT0_to",
            "hadron_tether",
            "tether",
            "keet_io",
        ],
        "x_watch_max_per_poll": 1,
        "x_watch_max_age_hours": 36,
    }


def _normalize_config_dict(c: dict[str, Any]) -> dict[str, Any]:
    out = default_config()
    feeds = c.get("feeds", out["feeds"])
    if not isinstance(feeds, list) or not all(isinstance(x, str) for x in feeds):
        feeds = list(DEFAULT_FEEDS)
    out["feeds"] = [str(u).strip() for u in feeds if str(u).strip()]
    if not out["feeds"]:
        out["feeds"] = list(DEFAULT_FEEDS)

    interval = c.get("poll_interval_minutes", out["poll_interval_minutes"])
    try:
        out["poll_interval_minutes"] = max(1, int(interval))
    except (TypeError, ValueError):
        out["poll_interval_minutes"] = 15

    dest = str(c.get("destination", out["destination"])).strip()
    if dest not in ALLOWED_DESTINATIONS:
        dest = "x_browser"
    out["destination"] = dest

    tpl = str(c.get("post_template", out["post_template"])).strip()
    if not tpl:
        tpl = TEXT_ONLY_TEMPLATE
    elif "{link}" in tpl:
        tpl = re.sub(r"\s*\n?\s*\{link\}\s*", "", tpl).strip() or TEXT_ONLY_TEMPLATE
    if "{hashtags}" not in tpl:
        tpl = tpl.rstrip() + "\n\n{hashtags}"
    out["post_template"] = tpl

    pub_i = c.get("publish_interval_minutes", out["publish_interval_minutes"])
    try:
        out["publish_interval_minutes"] = max(1, int(pub_i))
    except (TypeError, ValueError):
        out["publish_interval_minutes"] = 15

    uq = c.get("use_post_queue", out["use_post_queue"])
    out["use_post_queue"] = uq if isinstance(uq, bool) else str(uq).strip().lower() in ("1", "true", "yes", "on")

    out["discord_webhook_url"] = str(c.get("discord_webhook_url", "")).strip()

    x_on = c.get("x_watch_enabled", out["x_watch_enabled"])
    out["x_watch_enabled"] = (
        x_on if isinstance(x_on, bool) else str(x_on).strip().lower() in ("1", "true", "yes", "on")
    )
    x_accts = c.get("x_watch_accounts", out["x_watch_accounts"])
    if isinstance(x_accts, list):
        out["x_watch_accounts"] = [str(x).strip() for x in x_accts if str(x).strip()]
    else:
        out["x_watch_accounts"] = list(out["x_watch_accounts"])
    try:
        out["x_watch_max_per_poll"] = max(0, min(5, int(c.get("x_watch_max_per_poll", 1))))
    except (TypeError, ValueError):
        out["x_watch_max_per_poll"] = 1
    try:
        out["x_watch_max_age_hours"] = max(1.0, min(168.0, float(c.get("x_watch_max_age_hours", 36))))
    except (TypeError, ValueError):
        out["x_watch_max_age_hours"] = 36.0

    return out


def read_panel_config() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
    merged = {**default_config(), **raw}
    return _normalize_config_dict(merged)


def write_panel_config(updates: dict[str, Any]) -> None:
    base = read_panel_config()
    base.update(updates)
    final = _normalize_config_dict(base)
    CONFIG_PATH.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")


def profile_dir() -> Path:
    load_dotenv()
    raw = os.environ.get("X_PROFILE_DIR", "").strip()
    p = Path(raw) if raw else app_data_dir() / "x_profile"
    p.mkdir(parents=True, exist_ok=True)
    return p


def headless_from_env() -> bool:
    load_dotenv()
    v = os.environ.get("HEADLESS", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def browser_channel() -> str | None:
    """Yüklü tarayıcı kanalı: chrome (varsayılan), msedge veya chromium (Playwright paketi)."""
    load_dotenv()
    raw = (os.environ.get("BROWSER_CHANNEL") or "chrome").strip().lower()
    if raw in ("", "chromium", "bundled", "playwright"):
        return None
    allowed = {
        "chrome",
        "chrome-beta",
        "chrome-dev",
        "chrome-canary",
        "msedge",
        "msedge-beta",
        "msedge-dev",
        "msedge-canary",
    }
    return raw if raw in allowed else "chrome"


def use_existing_chrome() -> bool:
    load_dotenv()
    return os.environ.get("USE_EXISTING_CHROME", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def browser_mode_label() -> str:
    """Panel durumu için kısa etiket."""
    if use_existing_chrome():
        return "existing_chrome_cdp" if cdp_is_available() else "existing_chrome_no_cdp"
    return "bot_profile"


def chrome_cdp_url() -> str:
    load_dotenv()
    return (os.environ.get("CHROME_CDP_URL") or "http://127.0.0.1:9222").strip()


def chrome_user_data_dir() -> Path | None:
    """Gerçek Chrome profili (Chrome tamamen kapalıyken)."""
    load_dotenv()
    raw = os.environ.get("CHROME_USER_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        p = Path(local) / "Google" / "Chrome" / "User Data"
        if p.is_dir():
            return p
    return None


def _launch_x_persistent_context(p: Any, *, headless: bool):
    """Ayrı bot profili (x_profile) veya .env CHROME_USER_DATA_DIR — Chrome kapalı olmalı."""
    load_dotenv()
    custom = os.environ.get("CHROME_USER_DATA_DIR", "").strip()
    prof = Path(custom) if custom else profile_dir()
    channel = browser_channel()
    cdp_port = (os.environ.get("BOT_CDP_PORT") or "9333").strip() or "9333"
    opts: dict[str, Any] = {
        "user_data_dir": str(prof),
        "headless": headless,
        "locale": "tr-TR",
        "args": [
            "--disable-blink-features=AutomationControlled",
            f"--remote-debugging-port={cdp_port}",
        ],
    }
    if channel:
        opts["channel"] = channel
    return p.chromium.launch_persistent_context(**opts)


def _chrome_executable() -> str | None:
    for base in (
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    ):
        if not base:
            continue
        p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if p.is_file():
            return str(p)
    return None


def cdp_is_available(endpoint: str | None = None) -> bool:
    url = (endpoint or chrome_cdp_url()).rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def bot_cdp_url() -> str:
    load_dotenv()
    return (os.environ.get("BOT_CDP_URL") or "http://127.0.0.1:9333").strip().rstrip("/")


def bot_cdp_is_available() -> bool:
    return cdp_is_available(bot_cdp_url())


def open_cdp_new_tab(url: str, *, endpoint: str | None = None) -> bool:
    """CDP açıksa mevcut Chrome oturumunda yeni sekme (ayrı profil/pencere açmaz)."""
    target = (url or "").strip()
    ep = (endpoint or chrome_cdp_url()).rstrip("/")
    if not target or not cdp_is_available(ep):
        return False
    base = ep
    q = urllib.parse.quote(target, safe="")
    for method in ("PUT", "GET"):
        try:
            req = urllib.request.Request(
                f"{base}/json/new?{q}",
                method=method,
                headers={"User-Agent": "rss-news-bot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status in (200, 201, 204):
                    return True
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            continue
    return False


def open_chrome_new_tab(url: str) -> bool:
    """Açık Chrome'da sekme: önce CDP, olmazsa chrome.exe ile URL (aynı oturum)."""
    if open_cdp_new_tab(url):
        return True
    target = (url or "").strip()
    if not target:
        return False
    exe = _chrome_executable()
    if not exe:
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [exe, target],
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) or 0,
            )
        else:
            subprocess.Popen([exe, target], close_fds=True, start_new_session=True)
        return True
    except OSError:
        return False


def _bot_chrome_start_script() -> Path:
    sh = BASE_DIR / "scripts" / "start_bot_chrome.sh"
    if sys.platform != "win32" and sh.is_file():
        return sh
    return BASE_DIR / "scripts" / "start_bot_chrome.ps1"


def _run_bot_chrome_script(
    login_url: str,
    *,
    force_restart: bool = False,
    log: Callable[[str], None] | None = None,
) -> bool:
    """start_bot_chrome.ps1 senkron çalıştırır; CDP hazır olunca True."""
    script = _bot_chrome_start_script()
    if not script.is_file():
        _emit(log, f"Eksik: {script.name}")
        return False
    if script.suffix == ".sh":
        cmd = ["bash", str(script), "-Url", login_url]
        if force_restart:
            cmd.append("-ForceRestart")
    else:
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Url",
            login_url,
        ]
        if force_restart:
            cmd.append("-ForceRestart")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        for line in combined.splitlines()[-8:]:
            s = line.strip()
            if s:
                _emit(log, s)
        if proc.returncode not in (0, None) and not bot_cdp_is_available():
            _emit(log, f"start_bot_chrome.ps1 çıkış kodu: {proc.returncode}")
    except subprocess.TimeoutExpired:
        _emit(log, "start_bot_chrome.ps1 zaman aşımı (120 sn).")
    except OSError as ex:
        _emit(log, "Bot Chrome başlatılamadı: " + str(ex))
        return False
    for _ in range(20):
        if bot_cdp_is_available():
            return True
        time.sleep(1.0)
    return False


def ensure_bot_chrome_cdp(
    *,
    login_url: str = "https://x.com/login",
    wait_sec: int = 35,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Tek bot Chrome (CDP 9333); CDP'siz eski pencere varsa yeniden başlatır."""
    _ = wait_sec  # script içi bekleme + _run_bot_chrome_script poll
    if bot_cdp_is_available():
        return True
    _emit(log, "Bot Chrome CDP kapalı — tek pencere başlatılıyor…")
    if _run_bot_chrome_script(login_url, force_restart=False, log=log):
        _emit(
            log,
            "Bot Chrome CDP hazır (port " + (os.environ.get("BOT_CDP_PORT") or "9333") + ").",
        )
        return True
    _emit(log, "CDP hâlâ kapalı — bot Chrome yeniden başlatılıyor (-ForceRestart)…")
    if _run_bot_chrome_script(login_url, force_restart=True, log=log):
        _emit(log, "Bot Chrome CDP hazır (yeniden başlatıldı).")
        return True
    _emit(
        log,
        "Bot Chrome CDP açılamadı. Terminalde: .\\scripts\\start_bot_chrome.ps1 -ForceRestart",
    )
    return False


# Bot Chrome'da aynı anda tek Playwright işlemi (yayın + X tarama çakışmasın).
_x_browser_lock = threading.Lock()


def _playwright_goto_soft(page: Any, url: str, *, timeout: int = 90_000) -> None:
    """X yönlendirmelerinde ERR_ABORTED sık görülür; sekme açıksa yeterli."""
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
    except Exception as ex:
        low = str(ex).lower()
        if "err_aborted" in low or "interrupted" in low or "target closed" in low:
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            return
        raise


def _bot_cdp_open_tab(url: str) -> bool:
    """Bot Chrome'da giriş/yayın sekmesi aç; kapatma."""
    target = (url or "").strip()
    if not target or not bot_cdp_is_available():
        return False
    if open_cdp_new_tab(target, endpoint=bot_cdp_url()):
        return True
    try:
        with _x_browser_lock:
            with sync_playwright() as p:
                browser = _connect_cdp_browser(p, bot_cdp_url())
                if not browser.contexts:
                    return False
                page = browser.contexts[0].new_page()
                _playwright_goto_soft(page, target)
        return True
    except Exception:
        return False


def open_bot_profile_new_tab(url: str) -> bool:
    """Açık bot Chrome (CDP) üzerinde yeni sekme — ikinci pencere açmaz."""
    return _bot_cdp_open_tab(url)


def _connect_cdp_browser(p: Any, endpoint: str) -> Any:
    return p.chromium.connect_over_cdp(endpoint)


@contextmanager
def x_browser_page(*, headless: bool, new_tab: bool = True) -> Iterator[tuple[Any, bool]]:
    """
    (page, close_context_on_exit)
    CDP: mevcut Chrome'da yeni sekme açar; iş bitince yalnızca o sekmeyi kapatır.
    """
    with _x_browser_lock:
        with sync_playwright() as p:
            if use_existing_chrome() and cdp_is_available():
                endpoint = chrome_cdp_url()
                browser = _connect_cdp_browser(p, endpoint)
                if not browser.contexts:
                    raise RuntimeError("Chrome CDP bağlamı yok.")
                context = browser.contexts[0]
                page = context.new_page() if new_tab else (
                    context.pages[0] if context.pages else context.new_page()
                )
                try:
                    yield page, False
                finally:
                    if new_tab:
                        try:
                            page.close()
                        except Exception:
                            pass
                return

            if use_existing_chrome():
                raise RuntimeError(
                    "Chrome CDP kapalı; otomatik sekme kontrolü yok. "
                    "Giriş için open_chrome_new_tab kullanılır."
                )

            if not bot_cdp_is_available():
                ensure_bot_chrome_cdp()
            if bot_cdp_is_available():
                browser = _connect_cdp_browser(p, bot_cdp_url())
                if not browser.contexts:
                    raise RuntimeError("Bot Chrome CDP bağlamı yok.")
                context = browser.contexts[0]
                page = context.new_page() if new_tab else (
                    context.pages[0] if context.pages else context.new_page()
                )
                try:
                    yield page, False
                finally:
                    if new_tab:
                        try:
                            page.close()
                        except Exception:
                            pass
                return

            context = _launch_x_persistent_context(p, headless=headless)
            try:
                if new_tab and context.pages:
                    page = context.new_page()
                else:
                    page = context.pages[0] if context.pages else context.new_page()
                yield page, True
            finally:
                context.close()


def open_x_login_tab(log: Callable[[str], None] | None = None) -> str:
    """X giriş: bot profili veya mevcut Chrome (CDP)."""
    login_url = "https://x.com/login"
    if use_existing_chrome():
        if cdp_is_available():
            if open_cdp_new_tab(login_url):
                return "CDP: Mevcut Chrome'da yeni X sekmesi açıldı."
            try:
                with _x_browser_lock:
                    with sync_playwright() as p:
                        browser = _connect_cdp_browser(p, chrome_cdp_url())
                        page = browser.contexts[0].new_page()
                        _playwright_goto_soft(page, login_url)
                return "CDP: Chrome'da yeni X giriş sekmesi açıldı."
            except Exception as ex:
                raise RuntimeError("X giriş sekmesi açılamadı: " + str(ex)) from ex
        if open_chrome_new_tab(login_url):
            return "Chrome'da yeni sekme açıldı — giriş yapın (CDP kapalı, tam otomasyon yok)."
        raise RuntimeError("Chrome bulunamadı veya sekme açılamadı.")
    prof = profile_dir()
    ensure_bot_chrome_cdp(login_url=login_url, log=log)
    if not bot_cdp_is_available():
        raise RuntimeError(
            "Bot Chrome CDP kapalı. Terminalde: .\\scripts\\start_bot_chrome.ps1 -ForceRestart"
        )
    if _bot_cdp_open_tab(login_url):
        return (
            f"Bot Chrome'da X giriş sekmesi açıldı ({prof}). "
            "Giriş yapın; oturum x_profile içinde kalır."
        )
    if open_chrome_new_tab(login_url):
        return (
            f"Chrome'da giriş sekmesi açıldı ({prof}). "
            "Bot CDP yoksa önce start_bot_chrome.ps1 çalıştırın."
        )
    raise RuntimeError(
        "X giriş sekmesi açılamadı. Bot Chrome açık mı? "
        ".\\scripts\\start_bot_chrome.ps1 -ForceRestart"
    )


_db_lock = threading.Lock()


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Panel + zamanlayıcı eşzamanlı erişimde database locked önlenir."""
    with _db_lock:
        conn = sqlite3.connect(str(STATE_DB), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS posted (url TEXT PRIMARY KEY, title TEXT, created_at TEXT DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS post_queue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "url TEXT NOT NULL UNIQUE, "
        "title TEXT, "
        "body TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS summary_cache ("
        "url TEXT PRIMARY KEY, "
        "title_tr TEXT NOT NULL, "
        "summary_tr TEXT NOT NULL, "
        "updated_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS x_seen_posts ("
        "tweet_id TEXT PRIMARY KEY, "
        "handle TEXT, "
        "url TEXT, "
        "seen_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS x_watch_baseline ("
        "handle TEXT PRIMARY KEY, "
        "baseline_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    qcols = {row[1] for row in conn.execute("PRAGMA table_info(post_queue)")}
    if "quote_url" not in qcols:
        conn.execute("ALTER TABLE post_queue ADD COLUMN quote_url TEXT")
    if "post_kind" not in qcols:
        conn.execute("ALTER TABLE post_queue ADD COLUMN post_kind TEXT DEFAULT 'rss'")
    scols = {row[1] for row in conn.execute("PRAGMA table_info(summary_cache)")}
    if "hashtags" not in scols:
        conn.execute("ALTER TABLE summary_cache ADD COLUMN hashtags TEXT DEFAULT ''")
    conn.commit()


def _summary_cache_get(conn: sqlite3.Connection, url: str) -> tuple[str, str] | None:
    cur = conn.execute(
        "SELECT title_tr, summary_tr FROM summary_cache WHERE url = ?",
        (url,),
    )
    row = cur.fetchone()
    if not row:
        return None
    t, s = str(row[0] or "").strip(), str(row[1] or "").strip()
    if t and s and not looks_likely_english(s):
        return t, s
    return None


def _summary_cache_get_hashtags(conn: sqlite3.Connection, url: str) -> str:
    try:
        cur = conn.execute(
            "SELECT hashtags FROM summary_cache WHERE url = ?",
            (url,),
        )
        row = cur.fetchone()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip()
    except sqlite3.OperationalError:
        pass
    return ""


def _summary_cache_set(conn: sqlite3.Connection, url: str, title_tr: str, summary_tr: str) -> None:
    conn.execute(
        "INSERT INTO summary_cache (url, title_tr, summary_tr, updated_at) "
        "VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT(url) DO UPDATE SET "
        "title_tr = excluded.title_tr, "
        "summary_tr = excluded.summary_tr, "
        "updated_at = excluded.updated_at",
        (url, title_tr, summary_tr),
    )


def _summary_cache_clear(conn: sqlite3.Connection, url: str) -> None:
    try:
        conn.execute("DELETE FROM summary_cache WHERE url = ?", (url,))
    except sqlite3.OperationalError:
        pass


def _summary_cache_set_hashtags(conn: sqlite3.Connection, url: str, hashtags: str) -> None:
    line = (hashtags or "").strip()
    if not line:
        return
    try:
        conn.execute(
            "UPDATE summary_cache SET hashtags = ?, updated_at = datetime('now') WHERE url = ?",
            (line, url),
        )
    except sqlite3.OperationalError:
        pass


def already_posted(conn: sqlite3.Connection, url: str) -> bool:
    cur = conn.execute("SELECT 1 FROM posted WHERE url = ?", (url,))
    return cur.fetchone() is not None


def mark_posted(conn: sqlite3.Connection, url: str, title: str) -> None:
    conn.execute("INSERT OR IGNORE INTO posted (url, title) VALUES (?, ?)", (url, title))
    conn.commit()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
        if not p.scheme:
            return url.strip()
        netloc = p.netloc.lower()
        path = p.path or ""
        return f"{p.scheme}://{netloc}{path}"
    except Exception:
        return url.strip()


def strip_html(s: str) -> str:
    if not s:
        return ""
    t = html_module.unescape(str(s))
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def entry_plain_excerpt(entry: Any) -> str:
    candidates: list[str] = []
    for attr in ("summary", "description"):
        s = getattr(entry, attr, None)
        if s:
            candidates.append(str(s))
    cont = getattr(entry, "content", None) or []
    if isinstance(cont, list):
        for c in cont:
            if isinstance(c, dict) and c.get("value"):
                candidates.append(str(c["value"]))
                break
    best = ""
    for ch in candidates:
        plain = strip_html(ch)
        if len(plain) > len(best):
            best = plain
    return best


def _normalize_summary_paragraphs(raw: str) -> str:
    """En fazla iki blok; bloklar arasında tek boş satır (tweet okunurluğu)."""
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    parts = [p.strip() for p in s.split("\n") if p.strip()]
    if len(parts) >= 2:
        return "\n\n".join(parts[:2])
    return parts[0] if parts else ""


def post_template_has_link(template: str) -> bool:
    return "{link}" in (template or "")


def template_has_hashtags(template: str) -> bool:
    return "{hashtags}" in (template or "")


def summary_max_chars(template: str | None = None) -> int:
    tpl = (template or "").strip() or TEXT_ONLY_TEMPLATE
    if post_template_has_link(tpl):
        return SUMMARY_BODY_MAX_CHARS
    overhead = len(format_post("", "", tpl, summary="", hashtags=""))
    if template_has_hashtags(tpl) and overhead < HASHTAG_LINE_RESERVE:
        overhead = max(overhead, HASHTAG_LINE_RESERVE)
    return max(100, MAX_TWEET_LEN - overhead)


def _clip_summary_body(text: str, max_len: int = SUMMARY_BODY_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    for sep in (". ", "? ", "! ", "… "):
        j = cut.rfind(sep)
        if j >= max_len // 4:
            return cut[: j + len(sep)].strip()
    j = cut.rfind("\n\n")
    if j >= 40:
        return cut[:j].strip()
    sp = cut.rfind(" ", max(12, max_len // 5), max_len)
    if sp > 12:
        return cut[:sp].rstrip() + "…"
    return cut[: max_len - 1].rstrip() + "…"


def heuristic_news_line(
    title: str,
    excerpt: str,
    *,
    max_chars: int | None = None,
) -> str:
    ti = (title or "").strip()
    t = strip_html(excerpt or "").strip()
    t = re.sub(r"\s+", " ", t)
    max_len = max_chars if max_chars is not None else SUMMARY_BODY_MAX_CHARS
    if len(t) < 40:
        short = ti[:max_len]
        if len(ti) > max_len:
            sp = short.rfind(" ", max_len // 2, max_len)
            short = (short[:sp].rstrip() + ".") if sp > 10 else short[: max_len - 1] + "."
        return short
    if ti:
        low = t.lower()
        ti_low = ti.lower()
        if low.startswith(ti_low):
            t = t[len(ti) :].lstrip(" :.-—")
    if len(t) <= max_len:
        return t
    best_i = -1
    best_sep = ""
    for sep in (". ", "? ", "! ", "… "):
        i = t.rfind(sep, 0, max_len + 1)
        if i > best_i:
            best_i = i
            best_sep = sep
    if best_i >= max(50, max_len // 4) and best_sep:
        return t[: best_i + len(best_sep)].strip()
    sp = t.rfind(" ", max(40, max_len // 4), max_len + 1)
    if sp > 30:
        return t[:sp].rstrip() + "."
    return t[: max_len - 1].rstrip() + "."


def _parse_turkish_bundle(raw: str, *, cap: int) -> tuple[str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    title_tr = ""
    summary_tr = ""
    m_title = re.search(r"(?im)^\s*BA[ŞS]LIK:\s*(.+?)\s*$", text)
    if m_title:
        title_tr = m_title.group(1).strip().split("\n")[0].strip()
    m_sum = re.search(r"(?is)Ö?ZET:\s*(.+)\s*$", text)
    if m_sum:
        summary_tr = m_sum.group(1).strip()
    if not summary_tr:
        for line in re.split(r"\r?\n", text):
            ln = line.strip()
            if not ln:
                continue
            up = ln.upper()
            if up.startswith("BAŞLIK:") or up.startswith("BASLIK:"):
                title_tr = ln.split(":", 1)[1].strip()
            elif up.startswith("ÖZET:") or up.startswith("OZET:"):
                summary_tr = ln.split(":", 1)[1].strip()
    if not summary_tr:
        return None
    if not title_tr:
        title_tr = summary_tr.split(".")[0][:110].strip()
    summary_tr = _normalize_summary_paragraphs(summary_tr)
    summary_tr = _clip_summary_body(summary_tr, cap)
    title_tr = _clip_summary_body(title_tr, 110)
    if len(summary_tr) < 14 or looks_likely_english(summary_tr):
        return None
    return title_tr, summary_tr


def openai_turkish_bundle(
    title: str,
    excerpt: str,
    log: Callable[[str], None] | None,
    *,
    max_chars: int | None = None,
    strict: bool = False,
) -> tuple[str, str] | None:
    load_dotenv()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    cap = max_chars if max_chars is not None else SUMMARY_BODY_MAX_CHARS
    body_text = strip_html(excerpt) if excerpt else ""
    if len(body_text) < 45:
        body_text = (title or "").strip()
    body_text = body_text[:4500]
    system = (
        "Sen Türkçe kripto/finans haber editörüsün. Girdi İngilizce veya başka dilde olsa bile "
        "çıktın tamamen Türkçe olmalı; İngilizce cümle yazma.\n"
        f"{EDITORIAL_SUMMARY_STYLE}\n"
        "Yanıtını KESİNLİKLE şu formatta ver (başka açıklama veya markdown yok):\n"
        "BAŞLIK: (tek satır, en fazla 110 karakter)\n"
        f"ÖZET: (iki paragraf; paragraflar arasında boş satır; toplam en fazla {cap} karakter; "
        "cümleleri nokta ile bitir)\n\n"
        "Örnek ÖZET üslubu:\n"
        "Paolo Ardoino, @Tether ekibinin açık kaynaklı eşler arası (P2P) bir arama motoru "
        "üzerinde çalıştığını açıkladı.\n\n"
        "Paylaşılan demoda, merkezi sunucular yerine kullanıcılar arasında çalışan bir P2P "
        "Wikipedia arama motorunun test edildiği görüldü."
    )
    if strict:
        system += (
            " Önceki deneme İngilizce veya çok kısa kaldı; bu kez tam Türkçe, iki paragraf "
            "haber üslubuyla yaz."
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Başlık: {title}\n\nMetin:\n{body_text}"},
        ],
        "max_tokens": 420,
        "temperature": 0.3 if strict else 0.4,
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": "rss-news-bot/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=70) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        out = (raw.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        parsed = _parse_turkish_bundle(out, cap=cap)
        if parsed:
            return parsed
        fallback = _normalize_summary_paragraphs(str(out))
        for _ in range(4):
            if fallback.startswith("📌"):
                fallback = fallback[1:].lstrip(" \t")
            else:
                break
        if len(fallback) >= 14 and not looks_likely_english(fallback):
            t = (title or "").strip()
            if looks_likely_english(t) or len(t) > 110:
                t = fallback.split(".")[0][:110].strip()
            return t, _clip_summary_body(fallback, cap)
        return None
    except Exception as ex:
        if log:
            log("OpenAI Türkçe özet atlandı: " + str(ex))
        return None


def _sanitize_hashtag_token(raw: str) -> str:
    s = (raw or "").strip().lstrip("#")
    s = re.sub(r"[^\w]", "", s, flags=re.UNICODE)
    if not s or not re.search(r"[A-Za-z0-9]", s):
        return ""
    if len(s) > 30:
        s = s[:30]
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()


def _ascii_fold(s: str) -> str:
    t = (s or "").lower()
    for a, b in (
        ("ı", "i"),
        ("ğ", "g"),
        ("ü", "u"),
        ("ş", "s"),
        ("ö", "o"),
        ("ç", "c"),
        ("â", "a"),
        ("î", "i"),
    ):
        t = t.replace(a, b)
    return t


_CANONICAL_TAG_ALIASES: dict[str, str] = {
    "kripto": "KriptoPara",
    "kriptopara": "KriptoPara",
    "crypto": "KriptoPara",
    "cryptocurrency": "KriptoPara",
    "blockchain": "Blockchain",
    "blokzincir": "Blockchain",
    "tether": "Tether",
    "usdt": "Tether",
    "usdc": "Tether",
    "bitcoin": "Bitcoin",
    "btc": "Bitcoin",
    "ethereum": "Ethereum",
    "eth": "Ethereum",
    "thorchain": "Thorchain",
    "thorchainhack": "Thorchain",
    "rune": "RUNE",
    "solana": "Solana",
    "sol": "Solana",
    "binance": "Binance",
    "bnb": "Binance",
    "xrp": "Ripple",
    "ripple": "Ripple",
    "defi": "DeFi",
    "nft": "NFT",
    "regulasyon": "Regulasyon",
    "regulation": "Regulasyon",
    "ekonomi": "Ekonomi",
    "borsa": "Borsa",
    "haber": "KriptoPara",
    "news": "KriptoPara",
}

_CRYPTO_CONTEXT_HINTS: tuple[str, ...] = (
    "kripto",
    "crypto",
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "blockchain",
    "defi",
    "nft",
    "token",
    "altcoin",
    "mica",
    "zondacrypto",
    "bithero",
    "upbit",
    "irys",
    "binance",
    "coinbase",
    "kraken",
    "ftx",
    "borsasi",
    "crypto exchange",
    "kripto borsa",
    "stablecoin",
    "thorchain",
    "tether",
    "usdt",
    "btc",
    "eth",
    "web3",
    "cuzdan",
    "wallet",
    "madencilik",
    "mining",
)

# Öncelik: önce marka/konu, sonra genel kategori.
_TOPIC_WORD_PATTERNS: frozenset[str] = frozenset(
    {"btc", "eth", "sol", "bnb", "bit", "coin", "rune", "ada", "xrp", "nft", "defi"}
)


def _topic_pattern_matches(blob: str, pattern: str) -> bool:
    """Kısa kalıplarda upbit→bit, bithero→thor gibi yanlış eşleşmeyi önle."""
    p = _ascii_fold(pattern).strip()
    if not p:
        return False
    if p in _TOPIC_WORD_PATTERNS or (len(p) <= 4 and " " not in p):
        return re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", blob) is not None
    if p.startswith(" ") or p.endswith(" "):
        return p in blob or p.strip() in blob.split()
    return p in blob


def _topic_rule_matches(blob: str, patterns: tuple[str, ...]) -> bool:
    return any(_topic_pattern_matches(blob, p) for p in patterns)


_TOPIC_PRIMARY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("mica", "markets in crypto-assets"), "KriptoPara"),
    (
        (
            "bithero",
            "upbit",
            "irys",
            "zondacrypto",
            "kripto para",
            "kripto borsa",
            "kripto borsasi",
            "crypto exchange",
            "faaliyetlerini sonlandir",
            "borsa kapat",
        ),
        "KriptoPara",
    ),
    (("tether", "usdt", "usdc", "usd tether"), "Tether"),
    (("thorchain", "thor chain"), "Thorchain"),
    (("binance", " bnb"), "Binance"),
    (("coinbase",), "Coinbase"),
    (("solana", " sol "), "Solana"),
    (("ripple", " xrp"), "Ripple"),
    (("cardano", " ada"), "Cardano"),
    (("bitcoin", " btc", "satoshi"), "Bitcoin"),
    (("ethereum", " eth ", "vitalik"), "Ethereum"),
    (("blockchain", "blokzincir", "blok zincir", "on-chain", "onchain"), "Blockchain"),
    (("defi", "decentralized finance", "likidite"), "DeFi"),
    (("nft", "non-fungible"), "NFT"),
    (("sec ", "cftc", "regulasyon", "regulation", "komisyon"), "Regulasyon"),
    (("fed ", "faiz orani", "faiz", "enflasyon", "merkez bank"), "Ekonomi"),
    (("nasdaq", "hisse senedi", "hisse", "wall street", "borsa istanbul"), "Borsa"),
    (("kripto", "crypto", "altcoin", "token", " coin"), "KriptoPara"),
]

_SKIP_IF_CRYPTO_PRIMARY = frozenset({"Ekonomi", "Borsa"})

_TOPIC_ASSET_RULES: list[tuple[tuple[str, ...], str]] = [
    (("bitcoin", " btc"), "Bitcoin"),
    (("ethereum", " eth"), "Ethereum"),
    (("rune",), "RUNE"),
    (("solana", " sol "), "Solana"),
    (("binance", " bnb"), "Binance"),
    (("tether", " usdt"), "Tether"),
]

_GENERIC_TOPIC_TAGS = frozenset({"KriptoPara", "Blockchain", "DeFi", "NFT", "Regulasyon", "Ekonomi", "Borsa"})


def _refine_hashtag_token(token: str, context: str) -> str:
    """Etiketi kısa standart forma getir (KriptoPara, Tether, Blockchain…)."""
    if not token:
        return ""
    low = _ascii_fold(token)
    if low in _CANONICAL_TAG_ALIASES:
        canon = _CANONICAL_TAG_ALIASES[low]
        if context.strip():
            fresh = _detect_topic_hashtags("", context)
            if fresh and canon not in fresh:
                return fresh[0]
        if canon == "Ekonomi" and _has_crypto_context(_ascii_fold(context)):
            return "KriptoPara"
        return canon

    if low == "ekonomi" and _has_crypto_context(_ascii_fold(context)):
        return "KriptoPara"

    if low.startswith("rune") and len(low) > 4:
        return "RUNE"

    m = re.match(r"^([A-Za-z]{2,10})(.+)$", token)
    if m:
        base, rest = m.group(1), _ascii_fold(m.group(2))
        base_low = base.lower()
        if base_low in _CANONICAL_TAG_ALIASES:
            base_tag = _CANONICAL_TAG_ALIASES[base_low]
        else:
            base_tag = base.upper() if base.upper() in ("RUNE", "BTC", "ETH", "SOL", "BNB", "XRP") else (
                base[0].upper() + base[1:] if len(base) > 1 else base.upper()
            )
        junk = ("degerkaybi", "degerkayb", "kaybi", "kayb", "yukseldi", "dustu", "haber", "hack")
        if rest and any(j in rest for j in junk):
            return base_tag

    detected = _detect_topic_hashtags("", context)
    if detected:
        return detected[0]
    return token


def _has_crypto_context(blob: str) -> bool:
    return any(_topic_pattern_matches(blob, h) for h in _CRYPTO_CONTEXT_HINTS)


def _detect_topic_hashtags(title: str, summary: str) -> list[str]:
    """Konuya uygun 1–2 kısa etiket: KriptoPara, Blockchain, Tether, Bitcoin…"""
    blob = _ascii_fold(f"{title} {summary}")
    tags: list[str] = []
    crypto_ctx = _has_crypto_context(blob)

    for patterns, tag in _TOPIC_PRIMARY_RULES:
        if crypto_ctx and tag in _SKIP_IF_CRYPTO_PRIMARY:
            continue
        if _topic_rule_matches(blob, patterns):
            tags.append(tag)
            break

    if crypto_ctx and not tags:
        tags.append("KriptoPara")

    if len(tags) < HASHTAG_COUNT:
        for patterns, tag in _TOPIC_ASSET_RULES:
            if tag in tags:
                continue
            if _topic_rule_matches(blob, patterns):
                tags.append(tag)
                break

    if len(tags) < HASHTAG_COUNT and tags and tags[0] in _GENERIC_TOPIC_TAGS:
        for patterns, tag in _TOPIC_ASSET_RULES:
            if tag not in tags and _topic_rule_matches(blob, patterns):
                tags.append(tag)
                break

    if crypto_ctx and tags == ["Regulasyon"] and len(tags) < HASHTAG_COUNT:
        tags.append("KriptoPara")

    if not tags:
        tags.append("KriptoPara")
    return tags[:HASHTAG_COUNT]


def _format_hashtags(tags: list[str], *, context: str = "") -> str:
    out: list[str] = []
    seen: set[str] = set()
    ctx = context or ""
    for t in tags:
        token = _sanitize_hashtag_token(t)
        if ctx:
            token = _refine_hashtag_token(token, ctx)
        key = token.lower()
        if token and key not in seen:
            seen.add(key)
            out.append("#" + token)
        if len(out) >= HASHTAG_COUNT:
            break
    return " ".join(out)


def heuristic_topic_hashtags(title: str, summary: str) -> str:
    ctx = f"{title} {summary}"
    return _format_hashtags(_detect_topic_hashtags(title, summary), context=ctx)


def _parse_hashtag_response(raw: str) -> list[str]:
    tags: list[str] = []
    for line in re.split(r"\r?\n", str(raw or "")):
        ln = line.strip()
        if not ln:
            continue
        up = ln.upper()
        if up.startswith("ETIKET") or up.startswith("HASHTAG") or up.startswith("TAG"):
            val = ln.split(":", 1)[-1].strip()
            if val:
                tags.append(val)
        elif ln.startswith("#"):
            tags.append(ln.lstrip("#").split()[0])
    if not tags:
        for m in re.finditer(r"#([\w\u0080-\uFFFF]{2,30})", str(raw or "")):
            tags.append(m.group(1))
    return tags


def openai_topic_hashtags(
    title: str,
    summary: str,
    log: Callable[[str], None] | None,
) -> str | None:
    load_dotenv()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    system = (
        f"Konuya uygun tam {HASHTAG_COUNT} X hashtag öner. Yanıt:\n"
        "ETIKET1: (tek kelime, # yok)\n"
        f"ETIKET2: (tek kelime)\n"
        "Sadece kısa konu etiketleri: KriptoPara, Blockchain, Tether, Bitcoin, Ethereum, "
        "Thorchain, DeFi, Regulasyon, Ekonomi, Borsa, RUNE. "
        "Türkçe birleşik veya olay cümlesi yazma (RUNEdeğerkaybı, THORChainHack yasak). "
        "Genel #Haber #News kullanma."
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Başlık: {(title or '').strip()}\n\nÖzet: {(summary or '').strip()[:800]}",
            },
        ],
        "max_tokens": 60,
        "temperature": 0.4,
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": "rss-news-bot/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        out = (raw.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        ctx = f"{(title or '').strip()} {(summary or '').strip()}"
        line = _format_hashtags(_parse_hashtag_response(out), context=ctx)
        return line if line.count("#") >= 1 else None
    except Exception as ex:
        if log:
            log("OpenAI hashtag atlandı: " + str(ex))
        return None


def resolve_topic_hashtags(
    title: str,
    summary: str,
    log: Callable[[str], None] | None,
    *,
    conn: sqlite3.Connection | None = None,
    cache_url: str | None = None,
    force_refresh: bool = False,
) -> str:
    if conn is None:
        with db_session() as c:
            return resolve_topic_hashtags(
                title,
                summary,
                log,
                conn=c,
                cache_url=cache_url,
                force_refresh=force_refresh,
            )
    key = normalize_url(cache_url or "")
    ctx = f"{(title or '').strip()} {(summary or '').strip()}"
    line = _format_hashtags(_detect_topic_hashtags(title, summary), context=ctx)
    if line.count("#") < 1:
        line = openai_topic_hashtags(title, summary, log)
    if not line:
        line = heuristic_topic_hashtags(title, summary)
    if key and line:
        _summary_cache_set_hashtags(conn, key, line)
        conn.commit()
    return line


def openai_summarize_news_line(
    title: str,
    excerpt: str,
    log: Callable[[str], None] | None,
    *,
    max_chars: int | None = None,
) -> str | None:
    bundle = openai_turkish_bundle(title, excerpt, log, max_chars=max_chars)
    return bundle[1] if bundle else None


def synthesize_summary(
    title: str,
    excerpt: str,
    log: Callable[[str], None] | None,
    *,
    template: str | None = None,
) -> str:
    cap = summary_max_chars(template)
    t = (title or "").strip()
    ex = strip_html(excerpt or "")
    if looks_likely_turkish(t) and (not ex or looks_likely_turkish(ex) or len(ex) < 40):
        ai = openai_summarize_news_line(title, excerpt, log, max_chars=cap)
        if ai and not looks_likely_english(ai):
            return ai
        line = heuristic_news_line(title, excerpt, max_chars=cap)
        if line and not looks_likely_english(line):
            return line
    bundle = openai_turkish_bundle(title, excerpt, log, max_chars=cap)
    if bundle and not looks_likely_english(bundle[1]):
        return bundle[1]
    bundle = openai_turkish_bundle(title, excerpt, log, max_chars=cap, strict=True)
    if bundle and not looks_likely_english(bundle[1]):
        return bundle[1]
    if looks_likely_turkish(t):
        line = heuristic_news_line(title, excerpt, max_chars=cap)
        if line and not looks_likely_english(line):
            return line
    return ""


def resolve_turkish_title_summary(
    title: str,
    excerpt: str,
    log: Callable[[str], None] | None,
    *,
    template: str | None = None,
    conn: sqlite3.Connection | None = None,
    cache_url: str | None = None,
    force_refresh: bool = False,
) -> tuple[str, str]:
    """Türkçe başlık + özet; uluslararası kaynaklarda OpenAI zorunlu."""
    if conn is None:
        with db_session() as c:
            return resolve_turkish_title_summary(
                title,
                excerpt,
                log,
                template=template,
                conn=c,
                cache_url=cache_url,
                force_refresh=force_refresh,
            )
    key = normalize_url(cache_url or "")
    if key and force_refresh:
        _summary_cache_clear(conn, key)
    elif key:
        hit = _summary_cache_get(conn, key)
        if hit:
            return hit
    t = (title or "").strip()
    ex = strip_html(excerpt or "")
    cap = summary_max_chars(template)
    if looks_likely_turkish(t) and (not ex or looks_likely_turkish(ex) or len(ex) < 40):
        summary = synthesize_summary(title, excerpt, log, template=template)
        if summary and not looks_likely_english(summary):
            out = (t, summary)
            if key:
                _summary_cache_set(conn, key, out[0], out[1])
                conn.commit()
            return out
    bundle = openai_turkish_bundle(title, excerpt, log, max_chars=cap)
    if not bundle or looks_likely_english(bundle[1]):
        bundle = openai_turkish_bundle(title, excerpt, log, max_chars=cap, strict=True)
    if bundle and not looks_likely_english(bundle[1]):
        if key:
            _summary_cache_set(conn, key, bundle[0], bundle[1])
            conn.commit()
        return bundle
    if looks_likely_turkish(t):
        summary = heuristic_news_line(title, excerpt, max_chars=cap)
        if summary and not looks_likely_english(summary):
            out = (t, summary)
            if key:
                _summary_cache_set(conn, key, out[0], out[1])
                conn.commit()
            return out
    load_dotenv()
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise TurkishContentRequired(
            "İngilizce kaynak için .env içinde OPENAI_API_KEY gerekli."
        )
    raise TurkishContentRequired("Türkçe özet üretilemedi; log kayıtlarına bakın.")


def prepare_post_payload(
    link: str,
    title: str,
    excerpt: str,
    template: str,
    log: Callable[[str], None] | None,
    *,
    conn: sqlite3.Connection | None = None,
    force_refresh: bool = False,
) -> tuple[str, str]:
    title_tr, summary = resolve_turkish_title_summary(
        title,
        excerpt,
        log,
        template=template,
        conn=conn,
        cache_url=link,
        force_refresh=force_refresh,
    )
    hashtags = resolve_topic_hashtags(
        title_tr,
        summary,
        log,
        conn=conn,
        cache_url=link,
        force_refresh=force_refresh,
    )
    excerpt_slot = strip_html(excerpt)[:400] if excerpt else ""
    raw = format_post(
        title_tr,
        link,
        template,
        summary=summary,
        excerpt=excerpt_slot,
        hashtags=hashtags,
    )
    return title_tr, clip_for_publish(raw)


def _split_hashtag_suffix(text: str) -> tuple[str, str]:
    lines = [ln for ln in (text or "").strip().split("\n") if ln.strip()]
    if not lines:
        return (text or "").strip(), ""
    last = lines[-1].strip()
    if last.startswith("#") and re.fullmatch(r"(?:#\w+\s*){1,4}", last):
        return "\n".join(lines[:-1]).strip(), last
    return (text or "").strip(), ""


def clip_for_publish(text: str, max_len: int = MAX_TWEET_LEN) -> str:
    """Tweet sınırı; link yoksa tam cümlede keser."""
    text = (text or "").strip()
    head, tag_suffix = _split_hashtag_suffix(text)
    if tag_suffix:
        reserve = len(tag_suffix) + 2
        if len(head) + reserve <= max_len:
            return head + "\n\n" + tag_suffix if head else tag_suffix
        clipped = clip_for_publish(head, max_len - reserve)
        return (clipped + "\n\n" + tag_suffix).strip()
    if len(text) <= max_len:
        return text
    lines = text.split("\n")
    last = lines[-1].strip() if lines else ""
    if len(lines) >= 2 and last.startswith("http"):
        return clip_preserving_link(text, max_len)
    cut = text[:max_len]
    for sep in (". ", "? ", "! ", "… "):
        j = cut.rfind(sep)
        if j >= max_len * 2 // 3:
            return cut[: j + len(sep)].strip()
    sp = cut.rfind(" ", max_len // 3, max_len)
    if sp > 20:
        return cut[:sp].rstrip() + "."
    return cut[: max_len - 1].rstrip() + "."


def clip_preserving_link(text: str, max_len: int = MAX_TWEET_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    lines = text.split("\n")
    last = lines[-1].strip() if lines else ""
    if len(lines) >= 2 and last.startswith("http"):
        link = last
        head = "\n".join(lines[:-1]).strip()
        budget = max_len - len(link) - 1
        if budget < 40:
            return text[: max_len - 1] + "…"
        if len(head) > budget:
            head = head[: budget - 1].rstrip() + "…"
        return head + "\n" + link
    return text[: max_len - 1].rstrip() + "…"


def format_post(
    title: str,
    link: str,
    template: str,
    *,
    summary: str = "",
    excerpt: str = "",
    hashtags: str = "",
) -> str:
    try:
        netloc = urlparse((link or "").strip()).netloc.lower()
    except Exception:
        netloc = ""
    src = netloc[4:] if netloc.startswith("www.") else netloc
    repl = {
        "title": (title or "").strip(),
        "link": (link or "").strip(),
        "source": src,
        "summary": (summary or "").strip(),
        "excerpt": (excerpt or "").strip(),
        "hashtags": (hashtags or "").strip(),
    }
    t = str(template or TEXT_ONLY_TEMPLATE)
    for k, v in repl.items():
        t = t.replace("{" + k + "}", v)
    t = re.sub(r"\n{3,}", "\n\n", t.strip())
    lines = [ln for ln in t.split("\n") if ln.strip()]
    return "\n".join(lines)


def append_outbox(text: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    sep = "\n" + ("─" * 40) + "\n"
    with OUTBOX_PATH.open("a", encoding="utf-8") as f:
        f.write(stamp + "\n")
        f.write(text + sep)


def post_discord_webhook(url: str, content: str) -> None:
    payload = json.dumps({"content": content[:DISCORD_MAX]}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            if resp.status not in (200, 201, 202, 204):
                raise RuntimeError(f"HTTP {resp.status}")
    except urllib.error.HTTPError as ex:
        detail = ex.read()[:400].decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord HTTP {ex.code}: {detail}") from ex


def _entry_published_ts(entry: Any) -> float:
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if t:
        try:
            return float(calendar.timegm(t))
        except (TypeError, ValueError, OverflowError):
            pass
    return 0.0


def fetch_entries(feed_urls: list[str]) -> list[tuple[str, str, str]]:
    """Tüm akışlardan öğeleri toplar; yayın zamanına göre yeniden eskiye sıralar."""
    rows: list[tuple[float, str, str, str]] = []
    for feed_url in feed_urls:
        parsed = feedparser.parse(feed_url)
        for e in getattr(parsed, "entries", []) or []:
            link = getattr(e, "link", None) or ""
            title = getattr(e, "title", None) or ""
            if not link:
                continue
            ex = entry_plain_excerpt(e)
            ts = _entry_published_ts(e)
            rows.append((ts, link.strip(), title.strip(), ex))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [(link, title, ex) for _, link, title, ex in rows]


def _active_tweet_editor(page: Any) -> Any:
    """Birden fazla tweetTextarea_0 olduğunda görünür / diyalog içindekini seç."""
    for sel in (
        '[role="dialog"] [data-testid="tweetTextarea_0"]',
        '[data-testid="tweetComposer"] [data-testid="tweetTextarea_0"]',
        '[data-testid="layers"] [data-testid="tweetTextarea_0"]',
    ):
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.first
    all_ed = page.locator('[data-testid="tweetTextarea_0"]')
    n = all_ed.count()
    for i in range(n):
        ed = all_ed.nth(i)
        try:
            if not ed.is_visible():
                continue
            box = ed.bounding_box()
            if box and float(box.get("width") or 0) > 80 and float(box.get("height") or 0) > 24:
                return ed
        except Exception:
            continue
    return page.get_by_test_id("tweetTextarea_0").first


def _strip_compose_pointer_blockers(page: Any) -> None:
    """Compose üstündeki görünmez katmanlar tıklamayı engelliyorsa devre dışı bırak."""
    try:
        page.evaluate(
            """() => {
              const roots = [
                ...document.querySelectorAll('[role="dialog"]'),
                ...document.querySelectorAll('[data-testid="tweetComposer"]'),
                ...document.querySelectorAll('[data-testid="layers"]'),
              ];
              for (const root of roots) {
                for (const el of root.querySelectorAll('[class*="r-ipm5af"]')) {
                  const r = el.getBoundingClientRect?.();
                  if (!r || r.width < 40 || r.height < 40) continue;
                  const style = window.getComputedStyle(el);
                  if (style.position === 'fixed' || style.position === 'absolute') {
                    el.style.pointerEvents = 'none';
                  }
                }
              }
            }"""
        )
    except Exception:
        pass


def _focus_tweet_editor(page: Any) -> Any:
    """Tıklama yerine focus — X overlay engelini aşar."""
    editor = _active_tweet_editor(page)
    editor.wait_for(state="visible", timeout=25_000)
    _strip_compose_pointer_blockers(page)
    for attempt in range(4):
        try:
            editor.focus(timeout=2_000)
            page.wait_for_timeout(150)
            return editor
        except Exception:
            pass
        try:
            editor.evaluate(
                """(el) => {
                  el.focus();
                  el.click?.();
                  const inner = el.querySelector('[contenteditable="true"]') || el;
                  inner.focus();
                }"""
            )
            page.wait_for_timeout(150)
            return editor
        except Exception:
            pass
        try:
            editor.click(timeout=1_500, force=True)
            page.wait_for_timeout(150)
            return editor
        except Exception:
            pass
        _dismiss_x_overlays(page)
        page.wait_for_timeout(300)
    return editor


def _fill_tweet_editor(page: Any, text: str) -> None:
    editor = _focus_tweet_editor(page)
    page.wait_for_timeout(200)
    try:
        editor.fill(text, timeout=8_000)
    except Exception:
        try:
            page.keyboard.press("Control+a")
            page.keyboard.insert_text(text)
        except Exception:
            editor.click(force=True, timeout=2_000)
            page.keyboard.press("Control+a")
            page.keyboard.type(text, delay=6)
    page.wait_for_timeout(400)


def _tweet_compose_done(page: Any) -> bool:
    try:
        url = (page.url or "").lower()
        if "intent/tweet" not in url and "/compose" not in url:
            return True
    except Exception:
        pass
    try:
        if page.locator('[role="dialog"] [data-testid="tweetTextarea_0"]').count() == 0:
            vis = page.locator('[data-testid="tweetTextarea_0"]')
            if vis.count() == 0:
                return True
            if not vis.first.is_visible():
                return True
    except Exception:
        pass
    return False


def _active_tweet_submit_button(page: Any) -> Any:
    """Gönder düğmesi — compose diyalogu içindeki."""
    for sel in (
        '[role="dialog"] [data-testid="tweetButton"]',
        '[role="dialog"] [data-testid="tweetButtonInline"]',
        '[data-testid="tweetComposer"] [data-testid="tweetButton"]',
        '[data-testid="tweetComposer"] [data-testid="tweetButtonInline"]',
    ):
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.first
    for testid in ("tweetButton", "tweetButtonInline"):
        loc = page.locator(f'[data-testid="{testid}"]')
        n = loc.count()
        for i in range(n):
            btn = loc.nth(i)
            try:
                if btn.is_visible() and not btn.is_disabled():
                    return btn
            except Exception:
                continue
    return page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first


def _dismiss_x_overlays(page: Any) -> None:
    for sel in ('[data-testid="app-bar-close"]', '[aria-label="Close"]', '[aria-label="Kapat"]'):
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=800, force=True)
                page.wait_for_timeout(250)
        except Exception:
            pass
    for _ in range(4):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(350)
        except Exception:
            break


def _prepare_x_compose_session(page: Any) -> None:
    """Açık compose / örtüleri kapat; tek gönderi penceresi."""
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(800)
    except Exception:
        pass
    _dismiss_x_overlays(page)


def _click_tweet_submit(page: Any) -> None:
    """Gönder: editöre tıklamadan Ctrl+Enter; sonra force Gönder."""
    _active_tweet_editor(page).wait_for(state="visible", timeout=25_000)
    _strip_compose_pointer_blockers(page)
    page.wait_for_timeout(300)

    for _ in range(2):
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(2000)
        if _tweet_compose_done(page):
            return

    _focus_tweet_editor(page)
    for _ in range(3):
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(2000)
        if _tweet_compose_done(page):
            return

    btn = _active_tweet_submit_button(page)
    try:
        if btn.is_disabled():
            raise RuntimeError("Gönder düğmesi kapalı (metin veya oturum sorunu).")
    except Exception:
        pass

    _strip_compose_pointer_blockers(page)
    for click_fn in (
        lambda: btn.dispatch_event("click"),
        lambda: btn.click(timeout=2_000, force=True),
        lambda: btn.evaluate(
            """(el) => {
              el.removeAttribute('disabled');
              el.click();
            }"""
        ),
    ):
        try:
            click_fn()
            page.wait_for_timeout(2500)
            if _tweet_compose_done(page):
                return
        except Exception:
            continue

    _dismiss_x_overlays(page)
    raise RuntimeError(
        "Gönder tamamlanamadı. Bot Chrome'da açık taslak pencerelerini kapatıp tekrar deneyin."
    )


def _post_via_intent(page: Any, text: str) -> None:
    q = urllib.parse.quote(text, safe="")
    page.goto(f"https://x.com/intent/tweet?text={q}", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2500)
    _strip_compose_pointer_blockers(page)
    _click_tweet_submit(page)


def _post_compose_fill(page, text: str) -> None:
    page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(1500)
    _fill_tweet_editor(page, text)
    _click_tweet_submit(page)


def post_tweet_browser(text: str, *, log: Callable[[str], None] | None = None) -> None:
    headless = headless_from_env()
    if use_existing_chrome() and headless:
        headless = False

    if use_existing_chrome() and not cdp_is_available():
        q = urllib.parse.quote(text, safe="")
        if open_chrome_new_tab(f"https://x.com/intent/tweet?text={q}"):
            _emit(
                log,
                "Mevcut Chrome'da yeni sekme açıldı — 'Gönder'e basın; kuyruk silinmedi. "
                "(Otomasyon: scripts\\chrome_debug.ps1)",
            )
            raise ManualPostPending("Manuel gönderim bekleniyor")
        raise RuntimeError("Chrome'da sekme açılamadı.")

    with x_browser_page(headless=headless, new_tab=True) as (page, _):
        _prepare_x_compose_session(page)
        try:
            _post_compose_fill(page, text)
        except Exception:
            _prepare_x_compose_session(page)
            _post_via_intent(page, text)


def _quote_tweet_on_page(page: Any, tweet_url: str, text: str) -> None:
    _prepare_x_compose_session(page)
    page.goto(tweet_url.strip(), wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2000)
    rt = page.locator('[data-testid="retweet"]').first
    rt.wait_for(state="visible", timeout=25_000)
    rt.click(timeout=15_000)
    page.wait_for_timeout(900)
    quoted = False
    for sel in ('[data-testid="quoteTweet"]', '[data-testid="app-bar-quote"]'):
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.first.click(timeout=12_000)
            quoted = True
            break
    if not quoted:
        try:
            page.get_by_role(
                "menuitem",
                name=re.compile(r"Alıntı|Quote", re.I),
            ).first.click(timeout=12_000)
            quoted = True
        except PlaywrightTimeout:
            pass
    if not quoted:
        raise RuntimeError("Alıntı tweet menüsü açılamadı.")
    page.wait_for_timeout(1200)
    _fill_tweet_editor(page, text)
    _click_tweet_submit(page)


def post_quote_tweet_browser(
    tweet_url: str,
    comment_text: str,
    *,
    log: Callable[[str], None] | None = None,
) -> None:
    """X'te bir gönderiyi Türkçe yorumla alıntılar."""
    headless = headless_from_env()
    if use_existing_chrome() and headless:
        headless = False
    text = (comment_text or "").strip()
    target = (tweet_url or "").strip()
    if not target or not text:
        raise RuntimeError("Alıntı URL veya metin eksik.")

    if use_existing_chrome() and not cdp_is_available():
        if open_chrome_new_tab(target):
            _emit(
                log,
                "Alıntı için gönderi sekmesi açıldı — yorumu yapıştırıp «Alıntı» ile paylaşın "
                "(otomasyon: scripts\\chrome_debug.ps1).",
            )
            raise ManualPostPending("Manuel alıntı bekleniyor")
        raise RuntimeError("Chrome'da sekme açılamadı.")

    with x_browser_page(headless=headless, new_tab=True) as (page, _):
        try:
            _quote_tweet_on_page(page, target, text)
        finally:
            _dismiss_x_overlays(page)


def login_interactive() -> None:
    if use_existing_chrome():
        print(open_x_login_tab())
        if cdp_is_available():
            print("CDP aktif — bot bu Chrome oturumunda otomatik gönderebilir.")
        else:
            print(
                "Giriş sekmesi açıldı. Otomatik paylaşım için (isteğe bağlı):\n"
                "  Chrome'u tamamen kapatın → scripts\\chrome_debug.ps1\n"
                "(Aksi halde her tweet yeni sekmede açılır, siz Gönder'e basarsınız.)"
            )
        try:
            input("X hazır olunca Enter…")
        except EOFError:
            time.sleep(90)
        return

    login_url = "https://x.com/login"
    prof = profile_dir()
    ch = browser_channel() or "chromium (Playwright)"
    print("Profil klasörü:", prof)
    print("Tarayıcı:", ch)
    try:
        ensure_bot_chrome_cdp(login_url=login_url)
        if open_bot_profile_new_tab(login_url):
            print(
                "Açık bot Chrome'da yeni sekme açıldı (x.com/login). "
                "Giriş yapın; bittiğinde Enter'a basın."
            )
            try:
                input()
            except EOFError:
                time.sleep(120)
            print("Oturum kaydedildi:", prof)
            return
        print(
            "Bot Chrome'a bağlanılıyor (tek pencere). "
            "Giriş yapın; bittiğinde Enter'a basın."
        )
        with x_browser_page(headless=False, new_tab=True) as (page, _):
            page.goto(login_url, wait_until="domcontentloaded", timeout=90_000)
            try:
                input()
            except EOFError:
                time.sleep(120)
    except Exception as ex:
        print("Chrome başlatılamadı:", ex, file=sys.stderr)
        raise SystemExit(1) from ex
    print("Oturum kaydedildi:", prof)


def _emit(log: Callable[[str], None] | None, msg: str) -> None:
    if log:
        log(msg)
    else:
        print(msg)


def already_in_queue(conn: sqlite3.Connection, url: str) -> bool:
    cur = conn.execute("SELECT 1 FROM post_queue WHERE url = ?", (url,))
    return cur.fetchone() is not None


def _url_pipeline_state() -> tuple[set[str], dict[str, int]]:
    """Paylaşılmış URL'ler ve kuyruktaki url -> queue id."""
    with db_session() as conn:
        posted = {str(r[0]) for r in conn.execute("SELECT url FROM posted")}
        queued: dict[str, int] = {}
        for r in conn.execute("SELECT url, id FROM post_queue"):
            queued[str(r[0])] = int(r[1])
        return posted, queued


def _queue_preview_by_url() -> dict[str, tuple[str, str]]:
    """Kuyruktaki url -> (başlık, gövde) — panel önizlemesi için."""
    with db_session() as conn:
        out: dict[str, tuple[str, str]] = {}
        for url, title, body in conn.execute("SELECT url, title, body FROM post_queue"):
            out[str(url)] = (str(title or ""), str(body or ""))
        return out


def _body_to_preview_excerpt(body: str, *, max_len: int = 220) -> str:
    s = (body or "").strip()
    if s.startswith("📌"):
        s = s[1:].lstrip(" \t")
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _source_label(url: str) -> str:
    try:
        netloc = urlparse(url.strip()).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "—"
    except Exception:
        return "—"


def build_rss_preview(
    feed_urls: list[str],
    limit: int = 50,
    *,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    posted_urls, queued_urls = _url_pipeline_state()
    queue_preview = _queue_preview_by_url()
    cfg = read_panel_config()
    template = str(cfg.get("post_template", TEXT_ONLY_TEMPLATE))

    items: list[dict[str, Any]] = []
    preview_ai_budget = 14
    with db_session() as conn:
        for link, title, excerpt in fetch_entries(feed_urls):
            if len(items) >= limit:
                break
            key = normalize_url(link)
            if key in posted_urls:
                status = "yayinlandi"
            elif key in queued_urls:
                status = "kuyrukta"
            else:
                status = "yeni"

            show_title = (title or "").strip()
            show_excerpt = strip_html(excerpt)
            needs_tr = looks_likely_english(show_title) or looks_likely_english(show_excerpt)

            if status == "kuyrukta":
                qt, qb = queue_preview.get(key, (show_title, ""))
                show_title = qt or show_title
                show_excerpt = _body_to_preview_excerpt(qb) or show_excerpt
            elif status == "yeni" and needs_tr and preview_ai_budget > 0:
                try:
                    show_title, show_excerpt = resolve_turkish_title_summary(
                        title,
                        excerpt,
                        log,
                        template=template,
                        conn=conn,
                        cache_url=link,
                    )
                    preview_ai_budget -= 1
                except TurkishContentRequired:
                    show_excerpt = "Kuyruğa alınca Türkçe özetlenir (OpenAI API gerekli)."
                except Exception as ex:
                    if log:
                        log("Önizleme özeti: " + str(ex))
            elif status == "yeni" and needs_tr:
                hit = _summary_cache_get(conn, key)
                if hit:
                    show_title, show_excerpt = hit
                else:
                    show_excerpt = "Türkçe özet için «Kuyruğa al» veya listeyi yenileyin."

            if len(show_excerpt) > 220:
                show_excerpt = show_excerpt[:219].rstrip() + "…"

            items.append(
                {
                    "url": link,
                    "title": show_title,
                    "excerpt": show_excerpt,
                    "source": _source_label(link),
                    "status": status,
                    "queue_id": queued_urls.get(key),
                    "can_enqueue": status == "yeni",
                }
            )
        conn.commit()
    return items


def _prepare_post_for_entry(
    link: str,
    title: str,
    excerpt: str,
    template: str,
    log: Callable[[str], None] | None,
    *,
    conn: sqlite3.Connection | None = None,
    force_refresh: bool = False,
) -> tuple[str, str]:
    return prepare_post_payload(
        link, title, excerpt, template, log, conn=conn, force_refresh=force_refresh
    )


def enqueue_article_by_url(
    article_url: str,
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    """Belirli haberi hazırlayıp kuyruğa ekler. 1=eklendi, 0=zaten var/yok, 2=hata."""
    raw = (article_url or "").strip()
    if not raw:
        return 0
    cfg = read_panel_config()
    template = str(cfg.get("post_template", "{title}\n{link}"))
    feeds = effective_feeds(None)
    target_key = normalize_url(raw)

    with db_session() as conn:
        if already_posted(conn, target_key):
            _emit(log, "Bu haber zaten yayınlanmış.")
            return 0
        if already_in_queue(conn, target_key):
            _emit(log, "Bu haber zaten kuyrukta.")
            return 0

        for link, title, excerpt in fetch_entries(feeds):
            if normalize_url(link) != target_key and link.strip() != raw:
                continue
            try:
                title_tr, text_raw = _prepare_post_for_entry(
                    link, title, excerpt, template, log, conn=conn
                )
            except TurkishContentRequired as ex:
                _emit(log, str(ex))
                return 2
            cur = conn.execute(
                "INSERT OR IGNORE INTO post_queue (url, title, body) VALUES (?, ?, ?)",
                (target_key, title_tr, text_raw),
            )
            conn.commit()
            if cur.rowcount == 1:
                _emit(
                    log,
                    "Seçilen haber kuyruğa alındı: "
                    + (title_tr[:70] + "…" if len(title_tr) > 70 else title_tr),
                )
                return 1
            return 0
        _emit(log, "Haber RSS listesinde bulunamadı; önce listeyi yenileyin.")
        return 0


def enqueue_next_unposted(
    feed_urls: list[str],
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    """Paylaşılmamış ve kuyrukta olmayan en güncel 1 haberi hazırlayıp post_queue tablosuna ekler. Dönüş: 1 veya 0."""
    cfg = read_panel_config()
    template = str(cfg.get("post_template", "{title}\n{link}"))
    with db_session() as conn:
        for link, title, excerpt in fetch_entries(feed_urls):
            if not link:
                continue
            key_url = normalize_url(link)
            if already_posted(conn, key_url):
                continue
            if already_in_queue(conn, key_url):
                continue
            try:
                title_tr, text_raw = _prepare_post_for_entry(
                    link, title, excerpt, template, log, conn=conn
                )
            except TurkishContentRequired as ex:
                _emit(log, str(ex))
                return 2
            cur = conn.execute(
                "INSERT OR IGNORE INTO post_queue (url, title, body) VALUES (?, ?, ?)",
                (key_url, title_tr, text_raw),
            )
            conn.commit()
            if cur.rowcount == 1:
                _emit(
                    log,
                    "Kuyruğa alındı: "
                    + (title_tr[:70] + "…" if len(title_tr) > 70 else title_tr),
                )
                return 1
        _emit(log, "Kuyruğa eklenecek yeni haber yok.")
        return 0


def preview_next_enqueue_post(feed_urls: list[str]) -> str | None:
    """Kuyruğa bir sonraki eklenecek haberin hazır metnini döndürür (eklemez)."""
    cfg = read_panel_config()
    template = str(cfg.get("post_template", "{title}\n{link}"))
    with db_session() as conn:
        for link, title, excerpt in fetch_entries(feed_urls):
            if not link:
                continue
            key_url = normalize_url(link)
            if already_posted(conn, key_url):
                continue
            if already_in_queue(conn, key_url):
                continue
            _title_tr, body = _prepare_post_for_entry(link, title, excerpt, template, None)
            return body
        return None


def rebuild_post_queue_bodies(
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    """Kuyruktaki metinleri güncel şablon ve özet kurallarıyla yeniden üretir."""
    cfg = read_panel_config()
    template = str(cfg.get("post_template", TEXT_ONLY_TEMPLATE))
    feeds = effective_feeds(None)
    url_meta: dict[str, tuple[str, str]] = {}
    for link, title, excerpt in fetch_entries(feeds):
        if link:
            url_meta[normalize_url(link)] = (title, excerpt)

    n = 0
    with db_session() as conn:
        cur = conn.execute("SELECT id, url, title FROM post_queue ORDER BY id ASC")
        for qid, url, title in cur.fetchall():
            key = normalize_url(str(url))
            t, ex = url_meta.get(key, (str(title or ""), ""))
            try:
                title_tr, body = _prepare_post_for_entry(
                    str(url), t, ex, template, log, conn=conn, force_refresh=True
                )
            except TurkishContentRequired as ex_err:
                _emit(log, f"Atlandı (id={qid}): {ex_err}")
                continue
            conn.execute(
                "UPDATE post_queue SET title = ?, body = ? WHERE id = ?",
                (title_tr, body, qid),
            )
            n += 1
        conn.commit()
        if n and log:
            _emit(log, f"Kuyruk haber üslubuyla yenilendi: {n} kayıt.")
    return n


def list_post_queue(*, limit: int = 100) -> list[dict[str, Any]]:
    with db_session() as conn:
        cur = conn.execute(
            "SELECT id, url, title, body, created_at, quote_url, post_kind "
            "FROM post_queue ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        rows: list[dict[str, Any]] = []
        pos = 0
        for r in cur.fetchall():
            pos += 1
            bid, url, title, body, created_at, quote_url, post_kind = r
            preview = body or ""
            rows.append(
                {
                    "id": bid,
                    "url": url,
                    "title": title or "",
                    "body": body or "",
                    "body_preview": preview,
                    "created_at": created_at or "",
                    "quote_url": quote_url or "",
                    "post_kind": post_kind or "rss",
                    "position": pos,
                    "is_next": pos == 1,
                }
            )
        return rows


def delete_post_queue_item(row_id: int) -> bool:
    with db_session() as conn:
        cur = conn.execute("DELETE FROM post_queue WHERE id = ?", (row_id,))
        conn.commit()
        return cur.rowcount > 0


def peek_queue_head() -> tuple[int, str, str, str, str] | None:
    with db_session() as conn:
        cur = conn.execute(
            "SELECT id, url, title, body, quote_url FROM post_queue ORDER BY id ASC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        return (
            int(row[0]),
            str(row[1]),
            str(row[2] or ""),
            str(row[3] or ""),
            str(row[4] or ""),
        )


def publish_one_from_queue(
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    """Kuyruğun başındaki 1 gönderiyi yayınlar. 0=kuyruk boş, 1=başarılı, 2=yayın hatası."""
    load_dotenv()
    head = peek_queue_head()
    if not head:
        _emit(log, "Gönderim kuyruğu boş.")
        return 0
    qid, key_url, title, body, quote_url = head
    cfg = read_panel_config()
    destination = cfg.get("destination", "x_browser")

    def _finalize_success() -> None:
        with db_session() as conn:
            mark_posted(conn, key_url, title)
            conn.execute("DELETE FROM post_queue WHERE id = ?", (qid,))
            conn.commit()

    if destination == "file":
        try:
            append_outbox(body)
        except OSError as ex:
            _emit(log, "Dosyaya yazılamadı: " + str(ex))
            return 2
        _finalize_success()
        _emit(log, "Dosya kuyruğuna yazıldı (gönderim kuyruğundan): " + str(OUTBOX_PATH))
        return 1

    if destination == "discord_webhook":
        wh = (cfg.get("discord_webhook_url") or os.environ.get("DISCORD_WEBHOOK_URL", "")).strip()
        if not wh:
            _emit(log, "Discord webhook URL yok.")
            return 2
        try:
            post_discord_webhook(wh, body)
        except Exception as ex:
            _emit(log, "Discord gönderimi başarısız: " + str(ex))
            return 2
        _finalize_success()
        _emit(log, "Discord'a gönderildi (kuyruk): " + key_url)
        return 1

    text_x = clip_for_publish(body)
    try:
        if (quote_url or "").strip():
            post_quote_tweet_browser(quote_url.strip(), text_x, log=log)
        else:
            post_tweet_browser(text_x, log=log)
    except ManualPostPending:
        _emit(log, "Kuyrukta kaldı (manuel gönderim): " + (title[:60] or key_url))
        return 3
    except PlaywrightTimeout as ex:
        _emit(log, "Tarayıcı zaman aşımı: " + str(ex))
        return 2
    except Exception as ex:
        _emit(log, "Gönderim hatası: " + str(ex))
        return 2

    _finalize_success()
    if (quote_url or "").strip():
        _emit(log, "Alıntı tweet yayınlandı: " + quote_url)
    else:
        _emit(log, "Tweet gönderildi (kuyruk): " + key_url)
    return 1


def run_once(
    feed_urls: list[str],
    dry_run: bool,
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    load_dotenv()
    cfg = read_panel_config()
    destination = cfg.get("destination", "x_browser")
    template = str(cfg.get("post_template", "{title}\n{link}"))

    entries = fetch_entries(feed_urls)
    posted_count = 0

    for link, title, excerpt in entries:
        if not link:
            continue
        key_url = normalize_url(link)
        with db_session() as conn:
            if already_posted(conn, key_url):
                continue

        try:
            title_tr, text_raw = prepare_post_payload(
                link, title, excerpt, template, log
            )
        except TurkishContentRequired as ex:
            _emit(log, str(ex))
            continue

        if dry_run:
            preview = text_raw if len(text_raw) <= 600 else text_raw[:600] + "…"
            _emit(log, f"[dry-run][{destination}] " + preview)
            posted_count += 1
            break

        if destination == "file":
            try:
                append_outbox(text_raw)
            except OSError as ex:
                _emit(log, "Dosyaya yazılamadı: " + str(ex))
                return 1
            with db_session() as conn:
                mark_posted(conn, key_url, title_tr)
            posted_count += 1
            _emit(log, "Kuyruğa yazıldı: " + str(OUTBOX_PATH))
            break

        if destination == "discord_webhook":
            wh = (cfg.get("discord_webhook_url") or os.environ.get("DISCORD_WEBHOOK_URL", "")).strip()
            if not wh:
                _emit(log, "Discord webhook URL yok (ayar veya DISCORD_WEBHOOK_URL).")
                return 1
            try:
                post_discord_webhook(wh, text_raw)
            except Exception as ex:
                _emit(log, "Discord gönderimi başarısız: " + str(ex))
                return 1
            with db_session() as conn:
                mark_posted(conn, key_url, title_tr)
            posted_count += 1
            _emit(log, "Discord'a gönderildi: " + key_url)
            break

        text_x = clip_for_publish(text_raw)
        try:
            post_tweet_browser(text_x, log=log)
        except PlaywrightTimeout as ex:
            _emit(log, "Tarayıcı zaman aşımı: " + str(ex))
            return 1
        except Exception as ex:
            _emit(log, "Gönderim hatası: " + str(ex))
            return 1

        with db_session() as conn:
            mark_posted(conn, key_url, title_tr)
        posted_count += 1
        _emit(log, "Tweet gönderildi (tarayıcı): " + key_url)
        break

    if posted_count == 0:
        _emit(log, "Yeni haber yok veya tümü daha önce paylaşılmış.")
    return 0


def effective_poll_interval_minutes() -> int:
    load_dotenv()
    env_raw = os.environ.get("POLL_INTERVAL_MINUTES", "").strip()
    if env_raw:
        try:
            return max(1, int(env_raw))
        except ValueError:
            pass
    return read_panel_config()["poll_interval_minutes"]


def effective_publish_interval_minutes() -> int:
    load_dotenv()
    env_raw = os.environ.get("PUBLISH_INTERVAL_MINUTES", "").strip()
    if env_raw:
        try:
            return max(1, int(env_raw))
        except ValueError:
            pass
    return read_panel_config()["publish_interval_minutes"]


def effective_feeds(cli_feeds: list[str] | None) -> list[str]:
    if cli_feeds:
        return cli_feeds
    return read_panel_config()["feeds"]
