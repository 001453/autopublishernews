# Windows VPS: C surucuden D surucuye tasima (bos alan)

Bot kodu `BASE_DIR` ile calisir; sabit `C:\autopublishernews` zorunlu degil. Tasimadan sonra **Gorev Zamanlayicisi** yeni klasordeki scriptleri kullanmali.

## 1) Durdur

```powershell
Get-NetTCPConnection -LocalPort 8765,9333 -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
```

## 2) Kopyala (ornek: C -> D)

```powershell
robocopy C:\autopublishernews D:\autopublishernews /E /COPY:DAT /R:1 /W:1 /XD .venv __pycache__
```

`.venv` kopyalanmadiysa hedefte:

```powershell
cd D:\autopublishernews
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 3) Opsiyonel: agir veriyi D uzerinde tut

`D:\autopublishernews\.env` icine (tek satirlar, anahtar degistirme):

```env
DATA_DIR=D:\autopublishernews\data
X_PROFILE_DIR=D:\autopublishernews\x_profile
```

- `DATA_DIR`: `posted.sqlite3` ve ozel veri
- `X_PROFILE_DIR`: Chrome profili (yoksa `DATA_DIR\x_profile`)

C eski `x_profile` ve `posted.sqlite3` varsa `data` klasorune veya bu yollara el ile tasiyin.

## 4) Zamanlanmis gorevleri yeniden kur

**Yonetici** PowerShell, yeni klasorde:

```powershell
cd D:\autopublishernews
.\scripts\install_autostart.ps1
.\scripts\install_health_task.ps1
```

## 5) Baslat ve dogrula

```powershell
.\scripts\start_all_bot.ps1
Test-NetConnection 127.0.0.1 -Port 8765
Test-NetConnection 127.0.0.1 -Port 9333
```

## 6) Eski C klasorunu silmeden once

1-2 gun `D:\` ile sorunsuz calistigini dogrulayin; sonra `C:\autopublishernews` yedekleyip silebilirsiniz.
