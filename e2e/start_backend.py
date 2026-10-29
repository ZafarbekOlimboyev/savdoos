"""E2E backend: HAR SAFAR toza SQLite + demo seed, so'ng uvicorn (port 8000).

Playwright webServer sifatida ishga tushadi — testlar deterministik boshlang'ich
holatdan boshlanadi (demo do'kon: admin +998901234567/demo1234, kassir PIN 1111,
19 mahsulot qoldig'i bilan).
"""
import os
import pathlib
import sys

SERVER_DIR = pathlib.Path(__file__).resolve().parent.parent / "apps" / "server"
os.chdir(SERVER_DIR)
sys.path.insert(0, str(SERVER_DIR))

#  ⚠️  PORT va BAZA env orqali sozlanadi (ADMIN-1.0/RC). STANDART
#      QIYMATLAR O'ZGARMAYDI — `playwright.config.ts` va CI avvalgidek
#      8000/_e2e.db ni oladi. Sozlanuvchanlik FAQAT parallel sessiya bilan
#      port to'qnashuvisiz izolyatsiyalangan yurish uchun kerak.
E2E_PORT = int(os.environ.get("E2E_PORT", "8000"))
E2E_DB = os.environ.get("E2E_DB", "_e2e.db")

os.environ["DATABASE_URL"] = "sqlite:///./" + E2E_DB
os.environ["APP_ENV"] = "dev"
os.environ["SEED_DEMO"] = "1"
os.environ.setdefault("VENDOR_ADMIN_KEY", "e2e-vendor-key")
#  ADMIN-1.0 / P0-H: vendor konsoli brauzer E2E si PRODUCTION yo'lidan o'tsin.
#
#  Production'da 2FA MAJBURIY (`api/v1/admin.py`: sir sozlanmagan bo'lsa 503) va
#  `require_vendor` xom master kalitni avtorizatsiya sifatida QABUL QILMAYDI.
#  Sir berilmasa E2E boshqa kod yo'lini (2FA o'chiq) sinab, aynan buzuq bo'lgan
#  oqimni tekshirmagan bo'lardi. Sir — RFC 4648 base32, FAQAT shu toza bazada.
os.environ.setdefault("VENDOR_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

db = SERVER_DIR / E2E_DB
if db.exists():
    db.unlink()

from app import initdb, seed  # noqa: E402

initdb.main()
seed.run()

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=E2E_PORT, log_level="warning")
