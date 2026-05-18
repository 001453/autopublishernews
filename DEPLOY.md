# Sunucuda 7/24 çalıştırma (PC'den bağımsız)

## GitHub'a push

```bash
git init
git add .
git commit -m "Kripto RSS + X bot"
git remote add origin https://github.com/KULLANICI/REPO.git
git push -u origin main
```

**Asla push etmeyin:** `.env`, `x_profile/`, `posted.sqlite3`, `data/`, `.venv/`

---

## Yöntem A — Docker (Linux VPS, önerilen deneme)

Sunucu: Ubuntu 22.04+, en az 2 GB RAM, 20 GB disk.

```bash
git clone https://github.com/KULLANICI/REPO.git
cd REPO
cp .env.production.example .env
# .env içinde OPENAI_API_KEY doldurun

mkdir -p data
docker compose up -d --build
docker compose logs -f
```

Panel: `http://SUNUCU_IP:8765`

### İlk X girişi (önemli)

Docker içinde X oturumu için:

1. Sunucuya **VNC** veya **RDP** (Windows VPS ise) ile bağlanın, **veya**
2. Geçici olarak `docker compose exec -it x-news-bot bash` → manuel giriş zordur.

**Pratik:** İlk kurulumda `x_profile` klasörünü PC'nizde giriş yaptıktan sonra `data/x_profile` olarak sunucuya kopyalayın:

```powershell
# PC'de (giriş yapılmış x_profile)
scp -r x_profile kullanici@SUNUCU:/path/to/REPO/data/
```

Sonra sunucuda `docker compose restart`.

---

## Yöntem B — Windows VPS (en az sorun)

**Ayrıntılı rehber:** [WINDOWS_VPS_KURULUM.md](WINDOWS_VPS_KURULUM.md)

Kısa özet:
1. RDP ile Windows Server’a bağlan.
2. Chrome, Git, Python kur → `git clone https://github.com/001453/autopublishernews.git`
3. `.\scripts\setup_windows_vps.ps1` → `.env` + `panel_config.json` kopyala.
4. `.\scripts\start_bot_chrome.ps1` → X giriş → `.\.venv\Scripts\python.exe dashboard.py`
5. Otomatik açılış: Görev Zamanlayıcı → `scripts\start_all_bot.ps1`

Uzak panel: `PANEL_HOST=0.0.0.0` (güvenlik duvarında 8765 açın).

---

## Ortam değişkenleri (sunucu)

| Değişken | Açıklama |
|----------|----------|
| `OPENAI_API_KEY` | Zorunlu (TR özet) |
| `DATA_DIR` | Kalıcı veri (`posted.sqlite3`, kuyruk) |
| `X_PROFILE_DIR` | X oturum çerezleri |
| `AUTO_START_SCHEDULER=1` | Panel açılınca zamanlayıcı otomatik |
| `PANEL_HOST=0.0.0.0` | Uzaktan panele erişim |
| `POLL_INTERVAL_MINUTES` | RSS + X tarama |
| `PUBLISH_INTERVAL_MINUTES` | Tweet aralığı |

---

## Sınırlar

- X, datacenter IP'lerinde ek doğrulama veya kısıt isteyebilir.
- Tam stabil çözüm uzun vadede **X API** (ücretli) ile tarayıcısız paylaşım.
- Bu proje şu an **Playwright + Chrome/Chromium** kullanır.

---

## Güncelleme

```bash
git pull
docker compose up -d --build
```

Veriler `data/` volume içinde kalır.
