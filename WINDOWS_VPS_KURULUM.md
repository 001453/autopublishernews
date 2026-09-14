# Windows VPS kurulumu (Turhost nCloud S-3) — adım adım

Bu rehber: **Windows Server 2025 + 4 GB RAM** sunucuda botu 7/24 çalıştırır.

---

## Bölüm 1 — Sunucu hazır olunca (Turhost paneli)

### Adım 1: RDP bilgilerini alın
1. Turhost müşteri panelinde **nCloud S-3** sunucunuza girin.
2. **IP adresi**, **kullanıcı adı** (genelde `Administrator`), **şifre** not edin.
3. Sunucu durumu **Aktif / Running** olana kadar bekleyin (5–30 dk).

### Adım 2: Bilgisayarınızdan bağlanın
1. Windows’ta **Başlat** → `Uzak Masaüstü Bağlantısı` (veya `mstsc`).
2. Bilgisayar: sunucu **IP**.
3. Kullanıcı / şifre ile giriş yapın.
4. İlk açılışta “Ağ profili” sorarsa → **Evet** (özel ağ).

---

## Bölüm 2 — Sunucuda yazılımlar

### Adım 3: Google Chrome
1. Sunucuda Edge açın → https://www.google.com/chrome/
2. Chrome’u kurun.

### Adım 4: Git
1. https://git-scm.com/download/win
2. Kurulumda varsayılanları kabul edin.

### Adım 5: Python 3.12 veya 3.11
1. https://www.python.org/downloads/windows/
2. Kurarken **“Add python.exe to PATH”** kutusunu işaretleyin.
3. PowerShell’de kontrol:
   ```powershell
   python --version
   git --version
   ```

### Adım 6 (isteğe bağlı): Otomatik kurulum scripti
Proje klasöründe (Adım 7’den sonra):
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\scripts\setup_windows_vps.ps1
```

---

## Bölüm 3 — Projeyi sunucuya alın

### Adım 7: Projeyi klonlayın
Sunucuda PowerShell (**Yönetici değil**, normal yeterli):

```powershell
cd C:\
git clone https://github.com/001453/autopublishernews.git
cd C:\autopublishernews
```

### Adım 8: Python sanal ortam + paketler
```powershell
cd C:\autopublishernews
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chrome
```

---

## Bölüm 4 — Ayar dosyaları (PC’nizden)

### Adım 9: `.env` dosyasını kopyalayın
**PC’nizde** (botun çalıştığı klasörde) `.env` var. Sunucuya **kopyalamayın, taşımayın** — kopyalayın:

**Yöntem A — RDP ile**
1. PC’de `.env` dosyasına sağ tık → Kopyala.
2. RDP penceresinde sunucuya yapıştırın: `C:\autopublishernews\.env`

**Yöntem B — Klasör paylaşımı (RDP)**
1. RDP bağlantısı → Yerel Kaynaklar → **Sürücüler** → PC diskinizi işaretleyin.
2. Sunucuda `\\tsclient\C\...` üzerinden `.env` kopyalayın.

`.env` örnek (sunucuda düzenleyin):
```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
AUTO_START_SCHEDULER=1
POLL_INTERVAL_MINUTES=15
PUBLISH_INTERVAL_MINUTES=115
USE_EXISTING_CHROME=0
BOT_CDP_PORT=9333
HEADLESS=0
BROWSER_CHANNEL=chrome
```

### Adım 10: `panel_config.json`
PC’deki `panel_config.json` dosyasını da aynı şekilde `C:\autopublishernews\` içine kopyalayın  
(feed listesi, X hesapları, 115 dk yayın ayarı burada da durur).

### Adım 11: X oturumu (`x_profile`) — iki yol

**Yol A — PC’den kopyala (kolay)**  
PC’de X’e giriş yapmış `x_profile` klasörünü sunucuya kopyalayın:
```
C:\autopublishernews\x_profile
```
Chrome **kapalı** olsun kopyalarken.

**Yol B — Sunucuda giriş**  
Adım 12–13’te Chrome açıp X’e sunucudan giriş yapın.

---

## Bölüm 5 — Botu çalıştırın

### Adım 12: Bot Chrome
```powershell
cd C:\autopublishernews
.\scripts\start_bot_chrome.ps1
```
“CDP port 9333 hazır” benzeri mesaj görmelisiniz.

Antivirüs uyarısı çıkarsa → `scripts\start_bot_chrome.ps1` ve proje klasörü için **istisna** ekleyin.

### Adım 13: X girişi (Yol B kullandıysanız)
Açılan Chrome’da https://x.com/login → hesabınızla giriş.

### Adım 14: Panel
Yeni bir PowerShell penceresi:
```powershell
cd C:\autopublishernews
.\.venv\Scripts\python.exe dashboard.py
```

Tarayıcıda (sunucunun içinde): **http://127.0.0.1:8765**

- Zamanlayıcı otomatik başlamalı (`AUTO_START_SCHEDULER=1`).
- Logda: `Otomatik başlatma: zamanlayıcı açıldı` ve `ilk otomatik yayın ~120 dk sonra`.

### Adım 15: Test
Panelden:
1. **RSS listesini yenile**
2. İstersen **tek haber kuyruğa al**
3. **Şimdi paylaş** ile bir deneme (Chrome açık ve X girişli olmalı)

---

## Bölüm 6 — Sunucu yeniden başlayınca otomatik açılsın

### Adım 16: Görev Zamanlayıcısı
1. `Win + R` → `taskschd.msc`
2. **Görev Oluştur**
   - Ad: `XNewsBot`
   - “Kullanıcı oturumu açıldığında” tetikleyici
   - Eylem: Program başlat  
     `powershell.exe`  
     Bağımsız değişken:
     ```
     -ExecutionPolicy Bypass -File "C:\autopublishernews\scripts\start_all_bot.ps1"
     ```
3. Ayarlar: “Görevi mümkün olan en kısa sürede yeniden başlat” işaretli olsun.

**Önemli:** Windows Server’da bot için **oturum açık kalmalı** (RDP ile giriş yapılı kalsın veya otomatik oturum açma). Kapalı oturumda Chrome çalışmayabilir.

---

## Bölüm 7 — PC’nizden panele bakmak (isteğe bağlı)

Sadece sizin IP’nizden erişim önerilir.

1. `.env` içine ekleyin: `PANEL_HOST=0.0.0.0`
2. Windows Güvenlik Duvarı → Gelen kural → TCP **8765** (sadece sizin IP).
3. Tarayıcı: `http://SUNUCU_IP:8765`

---

## Sık sorunlar

| Sorun | Çözüm |
|--------|--------|
| `python` tanınmıyor | PATH’e Python ekleyin veya tam yol: `C:\...\python.exe` |
| `dashboard.py` çalışmıyor | `.\.venv\Scripts\python.exe dashboard.py` kullanın |
| Port 8765 dolu | `Get-NetTCPConnection -LocalPort 8765` → ilgili süreci kapatın |
| X gönderemiyor | Bot Chrome açık mı, CDP 9333, X girişi var mı |
| 15 dk’da paylaşıyor | `.env` içinde `PUBLISH_INTERVAL_MINUTES=120` olmalı; paneli yeniden başlatın |
| Kaspersky / AV | Proje klasörü + `start_bot_chrome.ps1` istisna |

---

## Güncelleme (ileride)

```powershell
cd C:\autopublishernews
git pull
.\.venv\Scripts\pip install -r requirements.txt
# Panel ve Chrome’u yeniden başlatın
```

`.env`, `x_profile`, `posted.sqlite3` dosyalarını **silmeden** koruyun.
