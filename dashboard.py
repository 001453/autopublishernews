"""
Web kontrol paneli: RSS önizleme, gönderim kuyruğu, zamanlayıcı.
Çalıştırma:  python dashboard.py
Tarayıcı:   http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from engine import (
    BASE_DIR,
    OUTBOX_PATH,
    build_rss_preview,
    delete_post_queue_item,
    queue_word_completions,
    update_post_queue_item,
    effective_feeds,
    effective_poll_interval_minutes,
    effective_publish_interval_minutes,
    browser_channel,
    browser_mode_label,
    bot_cdp_is_available,
    bot_cdp_url,
    chrome_cdp_url,
    cdp_is_available,
    open_x_login_tab,
    profile_dir,
    use_existing_chrome,
    feeds_with_meta,
    enqueue_article_by_url,
    enqueue_next_unposted,
    list_post_queue,
    peek_queue_head,
    preview_next_enqueue_post,
    publish_one_from_queue,
    publish_rss_per_rt,
    next_publish_kind,
    read_panel_config,
    rebuild_post_queue_bodies,
    run_once,
    write_panel_config,
)
from x_watch import DEFAULT_X_WATCH_ACCOUNTS, effective_x_watch_accounts, poll_x_watch_accounts, x_watch_enabled

app = FastAPI(title="X Haber Panel", version="1.0")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


@app.on_event("startup")
async def _on_startup() -> None:
    """Sunucu/Docker: AUTO_START_SCHEDULER=1 ile zamanlayıcı otomatik başlar."""
    if not _env_truthy("AUTO_START_SCHEDULER"):
        return
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        _stop_scheduler.clear()
        _scheduler_thread = threading.Thread(target=_scheduler_worker, daemon=True)
        _scheduler_thread.start()
    append_log("Otomatik başlatma: zamanlayıcı açıldı (AUTO_START_SCHEDULER).")

_log_lock = threading.Lock()
_logs: deque[str] = deque(maxlen=500)
_stop_scheduler = threading.Event()
_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()

_preview_lock = threading.Lock()
_rss_preview: list[dict[str, Any]] = []
_rss_preview_updated: str = ""

_sched_times_lock = threading.Lock()
_next_rss_at: str = ""
_next_publish_at: str = ""


def append_log(msg: str) -> None:
    line = datetime.now().strftime("%H:%M:%S") + " | " + msg
    with _log_lock:
        _logs.append(line)


def _set_rss_preview(items: list[dict[str, Any]]) -> None:
    global _rss_preview_updated
    with _preview_lock:
        _rss_preview.clear()
        _rss_preview.extend(items)
        _rss_preview_updated = datetime.now().isoformat(timespec="seconds")


def _set_sched_times(*, rss_in_sec: float, pub_in_sec: float | None) -> None:
    global _next_rss_at, _next_publish_at
    now = datetime.now()
    with _sched_times_lock:
        _next_rss_at = (now + timedelta(seconds=max(0, rss_in_sec))).strftime("%Y-%m-%d %H:%M:%S")
        if pub_in_sec is not None:
            _next_publish_at = (now + timedelta(seconds=max(0, pub_in_sec))).strftime(
                "%Y-%m-%d %H:%M:%S"
            )


def _scheduler_worker() -> None:
    append_log("Zamanlayıcı başladı (RSS listesi + kuyruk / yayın).")
    next_enq = 0.0
    next_pub = 0.0
    try:
        while not _stop_scheduler.is_set():
            now = time.monotonic()
            cfg = read_panel_config()
            use_q = bool(cfg.get("use_post_queue", True))
            poll_s = effective_poll_interval_minutes() * 60
            pub_s = effective_publish_interval_minutes() * 60

            if next_enq == 0.0 and next_pub == 0.0:
                next_enq = now
                next_pub = now + pub_s
                append_log(
                    f"Kuyruk: hemen RSS/haber eklenir; ilk otomatik yayın ~{effective_publish_interval_minutes()} dk sonra."
                )

            if now >= next_enq:
                feeds = effective_feeds(None)
                try:
                    _set_rss_preview(build_rss_preview(feeds, 60, log=append_log))
                except Exception as ex:
                    append_log(f"RSS listesi hatası: {ex}")
                if use_q:
                    try:
                        enqueue_next_unposted(feeds, log=append_log)
                    except Exception as ex:
                        append_log(f"Kuyruk ekleme hatası: {ex}")
                    try:
                        poll_x_watch_accounts(log=append_log)
                    except Exception as ex:
                        append_log(f"X hesap tarama: {ex}")
                else:
                    try:
                        run_once(feeds, dry_run=False, log=append_log)
                    except Exception as ex:
                        append_log(f"Döngü hatası: {ex}")
                next_enq = now + poll_s

            if use_q and now >= next_pub:
                qlen = len(list_post_queue(limit=500))
                if qlen > 0:
                    try:
                        code = publish_one_from_queue(log=append_log)
                        if code == 0:
                            append_log("Yayın atlandı (kuyruk boş).")
                    except Exception as ex:
                        append_log(f"Yayın hatası: {ex}")
                else:
                    append_log("Yayın bekliyor: kuyruk boş.")
                next_pub = now + pub_s

            now2 = time.monotonic()
            wait_enq = next_enq - now2
            wait_pub = (next_pub - now2) if use_q else wait_enq
            _set_sched_times(
                rss_in_sec=wait_enq,
                pub_in_sec=wait_pub if use_q else None,
            )
            sleep_s = min(wait_enq, wait_pub)
            sleep_s = max(0.5, min(120.0, sleep_s))
            if _stop_scheduler.wait(timeout=sleep_s):
                break
    finally:
        with _sched_times_lock:
            _next_rss_at = ""
            _next_publish_at = ""
        append_log("Zamanlayıcı durdu.")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "title": "X Haber Paneli"},
    )


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    thr = _scheduler_thread
    running = thr is not None and thr.is_alive() and not _stop_scheduler.is_set()
    cfg = read_panel_config()
    qlen = len(list_post_queue(limit=300))
    with _preview_lock:
        pc = len(_rss_preview)
    with _sched_times_lock:
        nra = _next_rss_at
        npa = _next_publish_at
    head = peek_queue_head()
    return {
        "scheduler_running": running,
        "poll_interval_minutes": effective_poll_interval_minutes(),
        "publish_interval_minutes": effective_publish_interval_minutes(),
        "feeds": list(cfg.get("feeds", [])),
        "feeds_meta": feeds_with_meta(list(cfg.get("feeds", []))),
        "feeds_count": len(cfg.get("feeds", [])),
        "profile_dir": str(profile_dir()),
        "browser_channel": browser_channel() or "chromium",
        "use_existing_chrome": use_existing_chrome(),
        "browser_mode": browser_mode_label(),
        "chrome_cdp_url": chrome_cdp_url() if use_existing_chrome() else bot_cdp_url(),
        "cdp_available": cdp_is_available() if use_existing_chrome() else bot_cdp_is_available(),
        "destination": cfg.get("destination", "x_browser"),
        "outbox_path": str(OUTBOX_PATH),
        "use_post_queue": bool(cfg.get("use_post_queue", True)),
        "queue_length": qlen,
        "rss_preview_count": pc,
        "next_rss_at": nra if running else "",
        "next_publish_at": npa if running and cfg.get("use_post_queue", True) else "",
        "next_queue_title": (head[2][:80] if head else ""),
        "next_publish_kind": next_publish_kind(),
        "publish_rss_per_rt": publish_rss_per_rt(cfg),
        "x_watch_enabled": x_watch_enabled(cfg),
        "x_watch_accounts": effective_x_watch_accounts(cfg),
        "x_watch_count": len(effective_x_watch_accounts(cfg)),
    }


@app.get("/api/feeds")
async def api_feeds() -> dict[str, Any]:
    cfg = read_panel_config()
    urls = list(cfg.get("feeds", []))
    return {"feeds": urls, "items": feeds_with_meta(urls)}


@app.get("/api/rss-preview")
async def api_rss_preview() -> dict[str, Any]:
    with _preview_lock:
        return {
            "updated_at": _rss_preview_updated,
            "items": list(_rss_preview),
        }


@app.post("/api/rss-preview/refresh")
async def api_rss_preview_refresh() -> dict[str, Any]:
    def job() -> None:
        feeds = effective_feeds(None)
        _set_rss_preview(build_rss_preview(feeds, 60, log=append_log))

    await asyncio.to_thread(job)
    with _preview_lock:
        return {"ok": True, "count": len(_rss_preview), "updated_at": _rss_preview_updated}


@app.get("/api/post-queue")
async def api_post_queue() -> dict[str, Any]:
    return {"items": list_post_queue(limit=100)}


@app.delete("/api/post-queue/{row_id}")
async def api_post_queue_delete(row_id: int) -> dict[str, Any]:
    ok = delete_post_queue_item(row_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Kayıt yok.")
    append_log(f"Kuyruktan silindi: id={row_id}")
    return {"ok": True}


class PostQueueBodyUpdate(BaseModel):
    body: str


@app.patch("/api/post-queue/{row_id}")
async def api_post_queue_patch(row_id: int, body: PostQueueBodyUpdate) -> dict[str, Any]:
    def job() -> bool:
        return update_post_queue_item(row_id, body.body)

    try:
        ok = await asyncio.to_thread(job)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    if not ok:
        raise HTTPException(status_code=404, detail="Kayıt yok veya metin boş.")
    append_log(f"Kuyruk metni güncellendi: id={row_id}")
    return {"ok": True}


@app.get("/api/post-queue/completions")
async def api_post_queue_completions(q: str = "", limit: int = 20) -> dict[str, Any]:
    lim = max(1, min(50, limit))
    words = queue_word_completions(prefix=q, limit=lim)
    return {"words": words, "max_tweet_len": 280}


class EnqueueUrlBody(BaseModel):
    url: str


@app.post("/api/post-queue/enqueue-url")
async def api_enqueue_url(body: EnqueueUrlBody) -> dict[str, Any]:
    def job() -> int:
        append_log("Haber seçildi → kuyruğa hazırlanıyor…")
        return enqueue_article_by_url(body.url.strip(), log=append_log)

    n = await asyncio.to_thread(job)
    if n == 2:
        return {"ok": False, "enqueued": 0, "error": "turkish_required"}
    return {"ok": n == 1, "enqueued": n}


@app.post("/api/post-queue/rebuild-turkish")
async def api_post_queue_rebuild_turkish() -> dict[str, Any]:
    def job() -> int:
        append_log("Kuyruk Türkçe metinlerle yeniden hazırlanıyor…")
        return rebuild_post_queue_bodies(log=append_log)

    n = await asyncio.to_thread(job)
    return {"ok": True, "updated": n}


@app.get("/api/config")
async def api_config_get() -> dict[str, Any]:
    return read_panel_config()


class ConfigBody(BaseModel):
    feeds: list[str] | None = None
    poll_interval_minutes: int | None = None
    publish_interval_minutes: int | None = None
    use_post_queue: bool | None = None
    destination: str | None = None
    post_template: str | None = None
    discord_webhook_url: str | None = None
    x_watch_enabled: bool | None = None
    x_watch_accounts: list[str] | None = None
    x_watch_max_per_poll: int | None = None
    x_watch_max_age_hours: float | None = None
    rss_max_age_hours: float | None = None
    queue_max_age_hours: float | None = None
    queue_max_items: int | None = None
    publish_rss_per_rt: int | None = None


@app.post("/api/x-watch/poll")
async def api_x_watch_poll() -> dict[str, Any]:
    def job() -> int:
        append_log("Manuel: X hesapları taranıyor…")
        return poll_x_watch_accounts(log=append_log)

    n = await asyncio.to_thread(job)
    return {"ok": True, "enqueued": n}


@app.post("/api/config")
async def api_config_post(body: ConfigBody) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if "feeds" in updates and updates["feeds"] is not None:
        updates["feeds"] = [str(u).strip() for u in updates["feeds"] if str(u).strip()]
    write_panel_config(updates)
    append_log("Ayarlar kaydedildi.")
    return read_panel_config()


@app.get("/api/logs")
async def api_logs() -> dict[str, Any]:
    with _log_lock:
        return {"lines": list(_logs)}


@app.post("/api/logs/clear")
async def api_logs_clear() -> dict[str, bool]:
    with _log_lock:
        _logs.clear()
    return {"ok": True}


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    thr = _scheduler_thread
    running = thr is not None and thr.is_alive() and not _stop_scheduler.is_set()
    return {"ok": True, "scheduler_running": running}


@app.post("/api/start")
async def api_start() -> dict[str, Any]:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            raise HTTPException(status_code=400, detail="Zamanlayıcı zaten çalışıyor.")
        _stop_scheduler.clear()
        _scheduler_thread = threading.Thread(target=_scheduler_worker, daemon=True)
        _scheduler_thread.start()
    return {"ok": True}


@app.post("/api/stop")
async def api_stop() -> dict[str, Any]:
    _stop_scheduler.set()
    append_log("Durdurma istendi; döngü tamamlanınca kapanacak.")
    return {"ok": True}


@app.post("/api/enqueue-once")
async def api_enqueue_once() -> dict[str, Any]:
    def job() -> int:
        feeds = effective_feeds(None)
        append_log("Manuel: RSS'ten kuyruğa ekleme.")
        try:
            _set_rss_preview(build_rss_preview(feeds, 60, log=append_log))
        except Exception as ex:
            append_log(f"RSS listesi: {ex}")
        return enqueue_next_unposted(feeds, log=append_log)

    n = await asyncio.to_thread(job)
    if n == 2:
        return {"ok": False, "enqueued": 0, "error": "turkish_required"}
    return {"ok": n == 1, "enqueued": n}


@app.post("/api/run-once")
async def api_run_once() -> dict[str, Any]:
    def job() -> int:
        cfg = read_panel_config()
        if cfg.get("use_post_queue", True):
            append_log("Tek sefer: kuyruğun başından yayın.")
            return publish_one_from_queue(log=append_log)
        feeds = effective_feeds(None)
        append_log("Tek sefer: doğrudan RSS (kuyruk kapalı).")
        return run_once(feeds, dry_run=False, log=append_log)

    code = await asyncio.to_thread(job)
    return {"ok": code in (0, 1), "code": code}


@app.post("/api/dry-run")
async def api_dry_run() -> dict[str, Any]:
    def job() -> None:
        cfg = read_panel_config()
        if cfg.get("use_post_queue", True):
            append_log("[dry-run] Kuyruk modu")
            head = peek_queue_head()
            if head:
                preview = head[3] if len(head[3]) <= 700 else head[3][:700] + "…"
                append_log("[dry-run] Sıradaki yayın:\n" + preview)
            else:
                append_log("[dry-run] Gönderim kuyruğu boş.")
            feeds = effective_feeds(None)
            nxt = preview_next_enqueue_post(feeds)
            if nxt:
                pv = nxt if len(nxt) <= 700 else nxt[:700] + "…"
                append_log("[dry-run] Bir sonraki kuyruğa eklenecek haber:\n" + pv)
            else:
                append_log("[dry-run] Kuyruğa eklenecek yeni haber yok.")
            return
        feeds = effective_feeds(None)
        append_log("Dry-run (doğrudan RSS).")
        run_once(feeds, dry_run=True, log=append_log)

    await asyncio.to_thread(job)
    return {"ok": True}


@app.post("/api/login-window")
async def api_login_window() -> dict[str, Any]:
    """Mevcut Chrome'da yeni X giriş sekmesi (ayrı pencere açmaz)."""

    def job() -> str:
        return open_x_login_tab(log=append_log)

    try:
        msg = await asyncio.to_thread(job)
    except RuntimeError as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
    except Exception as ex:
        append_log("X giriş sekmesi: " + str(ex))
        raise HTTPException(
            status_code=500,
            detail="X giriş sekmesi açılamadı. Bot Chrome: .\\scripts\\start_bot_chrome.ps1 -ForceRestart",
        ) from ex
    append_log(msg)
    return {"ok": True, "message": msg}


if __name__ == "__main__":
    import uvicorn

    from engine import _configure_stdio_utf8

    _configure_stdio_utf8()
    host = (os.environ.get("PANEL_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int((os.environ.get("PANEL_PORT") or "8765").strip())
    except ValueError:
        port = 8765
    uvicorn.run(app, host=host, port=port, log_level="info")
