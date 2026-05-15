# Kripto RSS → X Bot

Kripto RSS kaynaklarını ve seçili X hesaplarını tarar; Türkçe haber üslubunda özet + hashtag ile X'e paylaşır.

## Yerel çalıştırma (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chrome
copy .env.example .env
# .env → OPENAI_API_KEY

.\scripts\start_bot_chrome.ps1 -ForceRestart
# Bot Chrome'da X'e girin

python dashboard.py
# http://127.0.0.1:8765 → Zamanlayıcıyı başlat
```

## Sunucu (PC kapalıyken)

Bkz. **[DEPLOY.md](DEPLOY.md)** — Docker veya Windows VPS.

## Özellikler

- 16 kripto RSS (TR + uluslararası)
- X hesap takibi + alıntı tweet
- Kuyruk, tekrar paylaşım engeli, sabitlenmiş/eski tweet filtresi
- Panel: RSS önizleme, günlük, ayarlar
