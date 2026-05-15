"""
X (Twitter) otomatik haber: RSS + Playwright (API yok).
Panel: python dashboard.py  veya  uvicorn dashboard:app --reload

X girişi: Google Chrome (BROWSER_CHANNEL=chrome, varsayılan). Yedek: chromium
"""
from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

from engine import (
    effective_feeds,
    effective_poll_interval_minutes,
    login_interactive,
    run_once,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="RSS → X (tarayıcı, API yok)")
    parser.add_argument("--login", action="store_true", help="X'e bir kez tarayıcıdan giriş (profil kaydı)")
    parser.add_argument("--once", action="store_true", help="Tek kontrol yap ve çık")
    parser.add_argument("--dry-run", action="store_true", help="Gönderme; ilk yeni metni yazdırır")
    parser.add_argument("--feed", action="append", dest="feeds", help="Ek RSS URL (CLI; panel ayarını geçersiz kılar)")
    args = parser.parse_args()

    if args.login:
        login_interactive()
        raise SystemExit(0)

    feeds = effective_feeds(args.feeds)
    load_dotenv()

    if args.once or args.dry_run:
        raise SystemExit(run_once(feeds, args.dry_run))

    while True:
        code = run_once(feeds, False)
        if code != 0:
            raise SystemExit(code)
        interval = effective_poll_interval_minutes()
        print(f"{interval} dakika sonra tekrar kontrol…")
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
