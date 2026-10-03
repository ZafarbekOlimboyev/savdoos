"""BinOS promo: LOKAL, sintetik ma'lumotli backend — faqat reklama suratlari uchun.

    <venv python> capture/promo_backend.py            # o'zbekcha (asosiy)
    PROMO_LANG=ru <venv python> capture/promo_backend.py  # ru | ky — SOM narxlari

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

LANG = os.environ.get("PROMO_LANG", "uz")
if LANG not in promo_dataset.DATASETS:
    sys.exit(f"TO'XTADI: noma'lum PROMO_LANG={LANG}")
ds = promo_dataset.DATASETS[LANG]
if ds["categories"]:
    seed.CATEGORIES = ds["categories"]
seed.CATALOG = ds["catalog"]
seed.CUSTOMERS = ds["customers"]
seed.SUPPLIERS = ds["suppliers"]

initdb.main()
seed.run()

# Do'kon/filial nomi va valyuta seed ichida qat'iy yozilgan — tilga moslaymiz.
# ⚠️  Valyuta do'kon nomidan MUSTAQIL qo'llanadi: `uz` datasetida `store=None` (seed nomi
#     qoladi), lekin `currency="KGS"` — ilgari ikkisi bitta `if ds["store"]` ichida bo'lgani
#     uchun `uz` da valyuta bazaga UMUMAN yetib bormasdi.
if ds["store"] or ds["currency"]:
    from app.db.session import SessionLocal  # noqa: E402
    from app.models.org import Branch, Company  # noqa: E402
    from app.models.settings import Setting  # noqa: E402

    db = SessionLocal()
    try:
        company = db.query(Company).one()
        if ds["currency"]:
            company.currency = ds["currency"]
        if ds["store"]:
            company.name = ds["store"]
            branch = db.query(Branch).one()
            branch.name = ds["branch"]
            info = db.query(Setting).filter(Setting.key == "store_info").one()
            info.value = {"name": ds["store"], "branch": ds["branch"]}
        db.commit()
    finally:
        db.close()
print(f"[promo] toza sintetik baza ({LANG}): {DB}")

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
