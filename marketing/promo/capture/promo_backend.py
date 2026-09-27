"""BinOS promo: LOKAL, sintetik ma'lumotli backend — faqat reklama suratlari uchun.

    <venv python> capture/promo_backend.py

Har ishga tushishda TOZA SQLite (`.cache/promo.db`) yaratiladi, standart demo
seed `promo_dataset.py` ro'yxatlari bilan yurgiziladi va 127.0.0.1:8000 da
ochiladi (POS/Manager brauzer-preview'i dev rejimda aynan shu manzilga ulanadi).

XAVFSIZLIK (qasddan qat'iy):
  * `DATABASE_URL` shu skript ichida LOKAL faylga qat'iy o'rnatiladi — muhitdan
    kelgan har qanday qiymat (masalan production) USTIDAN yoziladi;
  * 8000-port band bo'lsa TO'XTAYDI: noma'lum backend'ga surat olish (va
    undagi ma'lumotni reklamaga tushirish) mumkin emas;
  * production seed qo'riqchisi (`seed.run` ichida) o'zgartirilmaydi.
"""
import os
import pathlib
import socket
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROMO = HERE.parent
REPO = PROMO.parent.parent
SERVER_DIR = REPO / "apps" / "server"
CACHE = PROMO / ".cache"
CACHE.mkdir(exist_ok=True)
DB = CACHE / "promo.db"

with socket.socket() as s:
    if s.connect_ex(("127.0.0.1", 8000)) == 0:
        sys.exit("TO'XTADI: 127.0.0.1:8000 band — boshqa backend ishlayapti. Uni to'xtating.")

os.environ["DATABASE_URL"] = "sqlite:///" + DB.as_posix()
os.environ["APP_ENV"] = "dev"
os.environ["SEED_DEMO"] = "1"
for leak in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "PGHOST", "PGPASSWORD"):
    os.environ.pop(leak, None)

if DB.exists():
    DB.unlink()

sys.path.insert(0, str(HERE))
os.chdir(SERVER_DIR)
sys.path.insert(0, str(SERVER_DIR))

import promo_dataset  # noqa: E402
from app import initdb, seed  # noqa: E402

seed.CATALOG = promo_dataset.CATALOG
seed.CUSTOMERS = promo_dataset.CUSTOMERS
seed.SUPPLIERS = promo_dataset.SUPPLIERS

initdb.main()
seed.run()
print(f"[promo] toza sintetik baza: {DB}")

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
