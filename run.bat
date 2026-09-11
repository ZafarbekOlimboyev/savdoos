@echo off
REM ============================================================
REM  SavdoOS — backend'ni bir tugmada ishga tushirish (Windows)
REM  Ilk marta: venv yaratadi, kutubxonalarni o'rnatadi, DB + seed.
REM  Keyingi safar: to'g'ridan-to'g'ri ishga tushadi.
REM ============================================================
setlocal
cd /d "%~dp0apps\server"

REM  Muhitni ANIQ e'lon qilamiz. Katalog reseti kabi xavfli amallar endi ANIQ
REM  ro'yxat bilan ishlaydi: belgi bo'lmasa — RAD (production'da `APP_ENV`
REM  umuman yo'qligi sababli reset ochiq qolgan edi). Mahalliy ish uchun `dev`.
if "%APP_ENV%"=="" set APP_ENV=dev

if not exist ".venv\Scripts\python.exe" (
  echo [SavdoOS] Ilk sozlash - iltimos kuting...
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip
  pip install -e .
  if not exist ".env" copy ".env.example" ".env" >nul
  python -m app.initdb
  python -m app.seed
) else (
  call ".venv\Scripts\activate.bat"
)

echo.
echo [SavdoOS] Backend: http://localhost:8000/docs
echo [SavdoOS] Login PIN: 1234 (Administrator) / 1111 (Kassir)
echo [SavdoOS] To'xtatish uchun: Ctrl+C
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
endlocal
