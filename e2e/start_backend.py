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

os.environ["DATABASE_URL"] = "sqlite:///./_e2e.db"
os.environ["APP_ENV"] = "dev"
os.environ["SEED_DEMO"] = "1"
os.environ.setdefault("VENDOR_ADMIN_KEY", "e2e-vendor-key")

db = SERVER_DIR / "_e2e.db"
if db.exists():
    db.unlink()

from app import initdb, seed  # noqa: E402

initdb.main()
seed.run()

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
