"""X (Twitter) hesap zaman çizelgesi: yeni gönderileri bul, Türkçe özetle, alıntı kuyruğuna ekle."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from engine import (
    TEXT_ONLY_TEMPLATE,
    TurkishContentRequired,
    _emit,
    already_in_queue,
    already_posted,
    cdp_is_available,
    db_session,
    normalize_url,
    prepare_x_quote_payload,
    read_panel_config,
    use_existing_chrome,
    x_post_skip_reason,
    x_browser_page,
)

DEFAULT_X_WATCH_ACCOUNTS: list[str] = [
    "tetherwallet",
    "qvac",
    "usat",
    "tethergold",
    "USDT0_to",
    "hadron_tether",
    "tether",
    "keet_io",
]

_STATUS_ID_RE = re.compile(r"/status/(\d+)")
_TWITTER_EPOCH_MS = 1288834974657


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).path or "").lower()
    except Exception:
        return ""


def parse_x_handle(raw: str) -> str:
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    m = re.search(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([^/?#]+)", s, re.I)
    if m:
        h = m.group(1).strip()
        if h.lower() not in ("home", "search", "explore", "i", "intent", "settings"):
            return h
    if s.startswith("@"):
        s = s[1:]
    return s.strip()


def effective_x_watch_accounts(cfg: dict[str, Any] | None = None) -> list[str]:
    c = cfg or read_panel_config()
    raw = c.get("x_watch_accounts", DEFAULT_X_WATCH_ACCOUNTS)
    if not isinstance(raw, list):
        raw = DEFAULT_X_WATCH_ACCOUNTS
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        h = parse_x_handle(str(item))
        if not h:
            continue
        key = h.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out or list(DEFAULT_X_WATCH_ACCOUNTS)


def x_watch_enabled(cfg: dict[str, Any] | None = None) -> bool:
    c = cfg or read_panel_config()
    v = c.get("x_watch_enabled", True)
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def x_watch_max_enqueue(cfg: dict[str, Any] | None = None) -> int:
    c = cfg or read_panel_config()
    try:
        return max(0, min(8, int(c.get("x_watch_max_per_poll", 3))))
    except (TypeError, ValueError):
        return 3


def x_watch_max_age_hours(cfg: dict[str, Any] | None = None) -> float:
    c = cfg or read_panel_config()
    try:
        return max(1.0, min(168.0, float(c.get("x_watch_max_age_hours", 168))))
    except (TypeError, ValueError):
        return 168.0


def _sort_posts_newest_first(posts: list[dict[str, str]]) -> list[dict[str, str]]:
    def _tid_key(p: dict[str, str]) -> int:
        try:
            return int((p.get("id") or "0").strip())
        except (TypeError, ValueError):
            return 0

    return sorted(posts, key=_tid_key, reverse=True)


def _tweet_age_hours(tweet_id: str) -> float | None:
    try:
        tid = int(str(tweet_id).strip())
    except (TypeError, ValueError):
        return None
    created_ms = (tid >> 22) + _TWITTER_EPOCH_MS
    return max(0.0, (time.time() * 1000 - created_ms) / 3_600_000)


def _handle_has_baseline(conn: sqlite3.Connection, handle: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM x_watch_baseline WHERE handle = ?",
        (parse_x_handle(handle).lower(),),
    )
    return cur.fetchone() is not None


def _set_handle_baseline(conn: sqlite3.Connection, handle: str) -> None:
    h = parse_x_handle(handle).lower()
    if not h:
        return
    conn.execute(
        "INSERT OR IGNORE INTO x_watch_baseline (handle, baseline_at) VALUES (?, datetime('now'))",
        (h,),
    )


def _baseline_mark_posts(
    conn: sqlite3.Connection,
    posts: list[dict[str, str]],
    *,
    log: Callable[[str], None] | None,
    handle: str,
    max_age_hours: float,
) -> None:
    """İlk kurulum: yalnızca sabitlenmiş ve yaş sınırını aşan gönderileri işaretle; yeniler kuyruğa gidebilir."""
    skipped = 0
    for post in posts:
        tid = (post.get("id") or "").strip()
        url = (post.get("url") or "").strip()
        if not tid:
            continue
        age_h = _tweet_age_hours(tid)
        if age_h is not None and age_h > max_age_hours:
            _mark_x_seen(conn, tid, handle, url)
            skipped += 1
            continue
        if post.get("pinned") and (_x_seen(conn, tid) or already_posted(conn, normalize_url(url))):
            _mark_x_seen(conn, tid, handle, url)
            skipped += 1
            continue
        # Yeni sabitlenmiş: baseline'da işaretleme — aynı turda kuyruğa gidebilir
    _set_handle_baseline(conn, handle)
    if skipped:
        _emit(
            log,
            f"@{handle}: ilk kurulum — {skipped} sabit/eski gönderi işaretlendi "
            f"(son {max_age_hours:.0f} saat içindekiler kuyruğa alınabilir).",
        )


def _x_seen(conn: sqlite3.Connection, tweet_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM x_seen_posts WHERE tweet_id = ?", (tweet_id,))
    return cur.fetchone() is not None


def _mark_x_seen(conn: sqlite3.Connection, tweet_id: str, handle: str, url: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO x_seen_posts (tweet_id, handle, url) VALUES (?, ?, ?)",
        (tweet_id, handle, url),
    )


def _is_pinned_article(article_locator: Any) -> bool:
    try:
        soc = article_locator.locator('[data-testid="socialContext"]').first
        if soc.count() == 0:
            return False
        txt = (soc.inner_text(timeout=1500) or "").lower()
        markers = (
            "pinned",
            "sabitlendi",
            "sabitlenmiş",
            "sabitlendiği",
            "pinned post",
            "sabit gönderi",
        )
        return any(m in txt for m in markers)
    except PlaywrightTimeout:
        return False
    except Exception:
        return False


def _is_repost_article(article_locator: Any) -> bool:
    try:
        soc = article_locator.locator('[data-testid="socialContext"]').first
        if soc.count() == 0:
            return False
        txt = (soc.inner_text(timeout=1500) or "").lower()
        markers = ("reposted", "retweeted", "yeniden gönder", "alıntıladı", "quoted")
        return any(m in txt for m in markers)
    except PlaywrightTimeout:
        return False
    except Exception:
        return False


def _tweet_url_for_handle(handle: str, href: str) -> tuple[str, str] | None:
    href = (href or "").strip()
    if not href:
        return None
    if href.startswith("/"):
        href = "https://x.com" + href
    m = _STATUS_ID_RE.search(href)
    if not m:
        return None
    tid = m.group(1)
    path = urlparse_path(href)
    if path and f"/{handle.lower()}/" not in path.lower():
        return None
    url = f"https://x.com/{handle}/status/{tid}"
    return tid, url


def fetch_profile_posts_playwright(page: Page, handle: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Giriş yapılmış Chrome sekmesinde profil zaman çizelgesinden son gönderiler."""
    handle = parse_x_handle(handle)
    if not handle:
        return []
    page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2500)
    try:
        page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=30_000)
    except PlaywrightTimeout:
        return []

    articles = page.locator('article[data-testid="tweet"]')
    count = min(articles.count(), limit + 6)
    seen_ids: set[str] = set()
    out: list[dict[str, str]] = []

    for i in range(count):
        if len(out) >= limit:
            break
        art = articles.nth(i)
        pinned = _is_pinned_article(art)
        if _is_repost_article(art):
            continue
        tweet_id = ""
        tweet_url = ""
        links = art.locator('a[href*="/status/"]')
        for j in range(min(links.count(), 12)):
            href = links.nth(j).get_attribute("href") or ""
            parsed = _tweet_url_for_handle(handle, href)
            if parsed:
                tweet_id, tweet_url = parsed
                break
        if not tweet_id or tweet_id in seen_ids:
            continue
        seen_ids.add(tweet_id)
        text = ""
        try:
            text = art.locator('[data-testid="tweetText"]').first.inner_text(timeout=4000)
        except PlaywrightTimeout:
            pass
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if len(text) < 4:
            continue
        out.append(
            {
                "id": tweet_id,
                "url": tweet_url,
                "text": text,
                "handle": handle,
                "pinned": pinned,
            }
        )
    return out


def _fetch_syndication(handle: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Yedek: herkese açık syndication (sık 429 verir)."""
    handle = parse_x_handle(handle)
    if not handle:
        return []
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; rss-news-bot/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return []
    except OSError:
        return []

    body = raw.strip()
    if body.startswith("{"):
        data = json.loads(body)
    else:
        m = re.search(r"\{.*\}", body, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))

    out: list[dict[str, str]] = []
    for item in (data.get("timeline") or data.get("entries") or [])[: limit + 5]:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("tweet_id") or item.get("id_str") or item.get("id") or "")
        text = str(item.get("text") or item.get("full_text") or "").strip()
        if not tid.isdigit() or len(text) < 4:
            continue
        tweet_url = f"https://x.com/{handle}/status/{tid}"
        out.append({"id": tid, "url": tweet_url, "text": text, "handle": handle})
        if len(out) >= limit:
            break
    return out


def enqueue_x_quote_post(
    tweet: dict[str, str],
    *,
    log: Callable[[str], None] | None = None,
    conn: sqlite3.Connection | None = None,
    max_age_hours: float | None = None,
) -> int:
    """1 = kuyruğa eklendi, 0 = atlandı."""
    tweet_url = (tweet.get("url") or "").strip()
    tweet_id = (tweet.get("id") or "").strip()
    handle = (tweet.get("handle") or "").strip()
    text = (tweet.get("text") or "").strip()
    if not tweet_url or not tweet_id:
        return 0

    cfg = read_panel_config()
    template = str(cfg.get("post_template", TEXT_ONLY_TEMPLATE))
    key = normalize_url(tweet_url)
    age_limit = max_age_hours if max_age_hours is not None else x_watch_max_age_hours(cfg)

    if conn is None:
        with db_session() as c:
            return enqueue_x_quote_post(
                tweet, log=log, conn=c, max_age_hours=max_age_hours
            )

    pinned = bool(tweet.get("pinned"))
    age_h = _tweet_age_hours(tweet_id)

    if age_h is not None and age_h > age_limit:
        _mark_x_seen(conn, tweet_id, handle, tweet_url)
        tag = "sabitlenmiş " if pinned else ""
        _emit(
            log,
            f"@{handle}: {tag}eski gönderi atlandı ({age_h:.0f} saat, sınır {age_limit:.0f} saat).",
        )
        return 0

    if _x_seen(conn, tweet_id) or already_posted(conn, key) or already_in_queue(conn, key):
        if pinned:
            _emit(log, f"@{handle}: sabitlenmiş gönderi zaten işlendi / kuyrukta.")
        return 0

    skip = x_post_skip_reason(text, cfg=cfg, for_x_watch=True)
    if skip:
        _mark_x_seen(conn, tweet_id, handle, tweet_url)
        label = "USDC" if skip == "USDC" else "fiyat"
        _emit(log, f"@{handle}: {label} gönderisi atlandı.")
        return 0

    if pinned:
        _emit(
            log,
            f"@{handle}: yeni sabitlenmiş gönderi (~{age_h:.0f} saat) — kuyruğa alınıyor."
            if age_h is not None
            else f"@{handle}: yeni sabitlenmiş gönderi — kuyruğa alınıyor.",
        )
    try:
        title_tr, body = prepare_x_quote_payload(
            tweet_url,
            handle,
            text,
            template,
            log,
            conn=conn,
        )
    except TurkishContentRequired as ex:
        _emit(log, f"@{handle} alıntı bekliyor: {ex}")
        return 0

    cur = conn.execute(
        "INSERT OR IGNORE INTO post_queue (url, title, body, quote_url, post_kind) "
        "VALUES (?, ?, ?, ?, 'x_quote')",
        (key, f"@{handle} · {title_tr}", body, tweet_url),
    )
    conn.commit()
    if cur.rowcount == 1:
        _mark_x_seen(conn, tweet_id, handle, tweet_url)
        conn.commit()
        _emit(log, f"X alıntı kuyruğa: @{handle} — {title_tr[:55]}")
        return 1
    return 0


def poll_x_watch_accounts(*, log: Callable[[str], None] | None = None) -> int:
    """Yapılandırılmış X hesaplarını tarar; yeni gönderilerden en fazla N tanesini kuyruğa alır."""
    cfg = read_panel_config()
    if not x_watch_enabled(cfg):
        return 0
    accounts = effective_x_watch_accounts(cfg)
    cap = x_watch_max_enqueue(cfg)
    if cap <= 0:
        return 0

    if use_existing_chrome() and not cdp_is_available():
        _emit(
            log,
            "X hesap takibi: USE_EXISTING_CHROME=1 ama CDP kapalı. "
            "scripts\\chrome_debug.ps1 veya .env içinde USE_EXISTING_CHROME=0 yapın.",
        )
        return 0

    mode = "CDP" if use_existing_chrome() else "bot profili (x_profile)"
    _emit(log, f"X hesap taraması başlıyor ({mode})…")

    enqueued = 0
    max_age = x_watch_max_age_hours(cfg)
    try:
        with x_browser_page(headless=False, new_tab=True) as (page, _):
            for handle in accounts:
                if enqueued >= cap:
                    break
                posts: list[dict[str, str]] = []
                try:
                    posts = fetch_profile_posts_playwright(page, handle, limit=8)
                except Exception as ex:
                    _emit(log, f"@{handle} zaman çizelgesi: {ex}")
                if not posts:
                    posts = _fetch_syndication(handle, limit=5)
                if not posts:
                    continue
                posts = _sort_posts_newest_first(posts)
                with db_session() as conn:
                    if not _handle_has_baseline(conn, handle):
                        _baseline_mark_posts(
                            conn, posts, log=log, handle=handle, max_age_hours=max_age
                        )
                        conn.commit()
                for post in posts:
                    if enqueued >= cap:
                        break
                    n = enqueue_x_quote_post(post, log=log, max_age_hours=max_age)
                    if n:
                        enqueued += n
                        break
    except Exception as ex:
        _emit(log, f"X hesap tarama hatası: {ex}")
    if enqueued:
        _emit(log, f"X takip: {enqueued} yeni alıntı kuyruğa eklendi.")
    return enqueued
