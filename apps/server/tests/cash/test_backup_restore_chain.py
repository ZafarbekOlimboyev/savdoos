# -*- coding: utf-8 -*-
"""Backup -> shifrlash -> tiklash ZANJIRI — uchdan-uchgacha regressiya.

NEGA BU TEST BOR: "backup skripti bor" degani "falokat kunida tiklanadi" degani EMAS.
Bu zanjirni bir marta qo'lda sinaganda BESHTA haqiqiy nuqson chiqdi, ularning biri
falokat kunida tiklashni butunlay to'xtatardi:

  1. `pg_dump "$URL" -Fc` — bayroq ulanish satridan KEYIN. Linux'da getopt permutatsiyasi
     tufayli ishlaydi, Windows/macOS'da "too many command-line arguments" bilan yiqiladi.
  2. `psql "$URL" -tAc` — xuddi shu muammo OLTI joyda. Yiqilish JIM edi
     (`2>/dev/null || echo`): metadata sxemalar ro'yxatini BO'SH yozardi va mashqning
     "maqsad baza bo'shmi" tekshiruvi HAR DOIM rad etardi.
  3. checksum: GNU coreutils fayl nomida ajratuvchi bo'lsa satr boshiga qo'shimcha belgi
     qo'yadi -> metadata JSON'i BUZILARDI va saqlangan checksum NOTO'G'RI bo'lardi.
  4. **ROLLAR**: rollar KLASTER darajasida, dump ichida YO'Q. Toza bazaga tiklashda
     `role "cash_posting" does not exist` chiqib, `--exit-on-error` butun tiklashni
     TO'XTATARDI. Ya'ni nusxa bor edi, lekin u YANGI bazaga TUSHMASDI.
  5. `python` qattiq yozilgan — virtual muhitli mashinada barmoq izi olinmasdi.

Har biri "yashil" ko'rinardi, chunki hech kim zanjirni OXIRIGACHA yurgizmagan edi.
Shu bois test ANIQ shu yo'ldan boradi va HAQIQIY skriptlarni chaqiradi.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[2]
ROOT = SERVER.parent.parent
PGBIN = SERVER / ".venv" / "Lib" / "site-packages" / "pgserver" / "pginstall" / "bin"
PASSPHRASE = "test-only-not-a-real-secret"

pgserver = pytest.importorskip("pgserver")

pytestmark = pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("gpg"),
    reason="zanjir testi uchun bash va gpg kerak",
)


def _pgbin() -> pathlib.Path:
    """pgserver ichidagi bin katalogi (platformadan qat'i nazar)."""
    base = pathlib.Path(pgserver.__file__).parent
    for name in ("pg_dump.exe", "pg_dump"):
        hits = list(base.rglob(name))
        if hits:
            return hits[0].parent
    pytest.skip("pg_dump topilmadi")


def _run(cmd, extra_env=None, cwd=None):
    env = dict(os.environ, **(extra_env or {}))
    env["PATH"] = str(_pgbin()) + os.pathsep + env.get("PATH", "")
    # PG_BIN — skriptlar binarni ANIQ shu yerdan olsin. Bu resolver'ning ASOSIY yo'li
    # (production'da composite action aynan shu o'zgaruvchini o'rnatadi), PATH'ga tayanmaydi.
    env.setdefault("PG_BIN", str(_pgbin()))
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          cwd=str(cwd or ROOT), timeout=900)


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _norm(url: str) -> str:
    for pfx in ("postgres://", "postgresql://"):
        if url.startswith(pfx):
            return "postgresql+psycopg://" + url[len(pfx):]
    return url


def _seed(engine):
    """Ilova sxemasi (public + cash) + kichik, LEKIN haqiqiy shakldagi ma'lumot."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.cash.deploy import deploy_cash_schema
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.org import Branch, Company
    from app.models.sales import Sale, SaleItem, SalePayment

    Base.metadata.create_all(engine)
    assert deploy_cash_schema(engine) == "deployed"

    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        co = Company(name="Chain Co", code="chain", currency="UZS"); s.add(co); s.flush()
        role = Role(code="cashier_chain", name="Cashier"); s.add(role); s.flush()
        emp = Employee(company_id=co.id, full_name="Kassir", role_id=role.id); s.add(emp); s.flush()
        br = Branch(company_id=co.id, code="F01", name="Asosiy"); s.add(br); s.flush()
        unit = Unit(code="dona", name="dona"); s.add(unit); s.flush()
        p = Product(company_id=co.id, article_code="A1", name="Mahsulot", unit_id=unit.id,
                    base_buy_price=500, base_sell_price=1000, tax_rate=0)
        s.add(p); s.flush()
        for i in range(15):
            sale = Sale(company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                        receipt_no=f"R{i:05d}", total=2000, subtotal=2000,
                        sold_at=now - timedelta(hours=i))
            s.add(sale); s.flush()
            s.add(SaleItem(sale_id=sale.id, product_id=p.id, qty=2, unit_price=1000,
                           line_total=2000, name_snapshot="x", unit_cost=500))
            s.add(SalePayment(sale_id=sale.id, method_code="cash", amount=2000,
                              paid_at=now - timedelta(hours=i)))
        s.commit()

    with engine.begin() as con:
        cid = con.execute(text("SELECT id FROM companies LIMIT 1")).scalar()
        bid = con.execute(text("SELECT id FROM branches LIMIT 1")).scalar()
        acc = uuid.uuid4()
        con.execute(text(
            "INSERT INTO cash.cash_accounts (id, tenant_id, branch_id, type, currency, status,"
            " label, created_at) VALUES (:i,:t,:b,'TILL','UZS','ACTIVE','TILL-01', now())"),
            {"i": acc, "t": cid, "b": bid})
        for i in range(8):
            con.execute(text(
                "INSERT INTO cash.cash_ledger_entries (id, tenant_id, cash_account_id, branch_id,"
                " account_type, shift_id, posting_kind, source_type, source_id, leg_index,"
                " direction, category, amount, currency, device_occurred_at, server_received_at,"
                " recorded_at, idempotency_key, provenance, metadata)"
                " VALUES (:i,:t,:a,:b,'TILL',NULL,'OFF_SHIFT','SALE',:s,0,'IN','SALE',:amt,'UZS',"
                " now(), now(), now(), :k, 'NORMAL', '{}'::jsonb)"),
                {"i": uuid.uuid4(), "t": cid, "a": acc, "b": bid, "s": uuid.uuid4(),
                 "amt": 1000 + i, "k": f"chain-{i}"})


def test_backup_encrypt_restore_chain_end_to_end(tmp_path):
    from sqlalchemy import create_engine

    src = pgserver.get_server(str(tmp_path / "src_pg"))
    tgt = pgserver.get_server(str(tmp_path / "tgt_pg"))
    src_url, tgt_url = _norm(src.get_uri()), _norm(tgt.get_uri())

    eng = create_engine(src_url, future=True)
    _seed(eng)
    eng.dispose()

    py = sys.executable
    before = tmp_path / "before.json"
    r = _run([py, "-m", "app.tools.db_fingerprint", "--json"],
             {"DATABASE_URL": _plain(src_url)}, cwd=SERVER)
    assert r.returncode == 0, r.stderr[-500:]
    before.write_text(r.stdout, encoding="utf-8")

    # ── 1) HAQIQIY backup skripti ──────────────────────────────────────────
    out = tmp_path / "backups"
    r = _run(["bash", "scripts/backup_postgres.sh", str(out)], {"DATABASE_URL": _plain(src_url)})
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]

    dumps = sorted(out.glob("*.dump"))
    assert len(dumps) == 1
    dump = dumps[0]
    assert (out / (dump.name + ".sha256")).exists()

    # metadata YAROQLI JSON bo'lishi shart (checksum escape nuqsoni aynan shu yerda chiqqan edi)
    meta = json.loads(sorted(out.glob("*.meta.json"))[0].read_text(encoding="utf-8"))
    assert set("0123456789abcdef") >= set(meta["sha256"]), "checksum sof o'n oltilik emas"
    assert len(meta["sha256"]) == 64
    # `psql` chaqiruvi ishlagan bo'lsa IKKALA sxema ham ko'rinadi (jim yiqilish belgisi — bo'sh satr)
    assert "cash" in meta["schemas_present"] and "public" in meta["schemas_present"]
    assert meta["toc_objects"] > 0
    # Artefakt ULANISH SATRINI tashimasligi shart
    assert "postgresql://" not in json.dumps(meta)

    # ── 2) shifrlash + ochish (workflow bilan bir xil yo'l) ────────────────
    enc = dump.with_suffix(dump.suffix + ".gpg")
    r = _run(["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
              "--passphrase", PASSPHRASE, "-o", str(enc), str(dump)])
    assert r.returncode == 0 and enc.exists(), r.stderr[-400:]
    assert enc.read_bytes()[:16] != dump.read_bytes()[:16], "fayl shifrlanmagan"
    dump.unlink()
    r = _run(["gpg", "--batch", "--yes", "--passphrase", PASSPHRASE,
              "-o", str(dump), "-d", str(enc)])
    assert r.returncode == 0 and dump.exists(), r.stderr[-400:]

    # ── 3) PRODUCTION GARDI: maqsad == DATABASE_URL -> RAD ────────────────
    r = _run(["bash", "scripts/restore_rehearsal.sh", str(dump)],
             {"DATABASE_URL": _plain(src_url), "REHEARSAL_DATABASE_URL": _plain(src_url)})
    assert r.returncode != 0, "mashq production ustiga tiklashga ROZI BO'LDI"
    assert "RAD ETILDI" in (r.stdout + r.stderr)

    # ── 4) HAQIQIY tiklash (bir martalik ikkinchi baza) ───────────────────
    after = tmp_path / "after.json"
    r = _run(["bash", "scripts/restore_rehearsal.sh", str(dump)],
             {"DATABASE_URL": _plain(src_url),
              "REHEARSAL_DATABASE_URL": _plain(tgt_url),
              "PYTHON": py,
              "BEFORE_FINGERPRINT": str(before),
              "AFTER_FINGERPRINT": str(after)})
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined[-1500:]
    # Rollar dump ichida YO'Q — mashq ularni O'ZI yaratishi shart, aks holda pg_restore yiqiladi
    assert "role" not in combined.lower() or "does not exist" not in combined.lower(), combined[-800:]
    assert "RESTORE_REHEARSAL_OK" in combined, combined[-800:]

    # ── 5) tiklangan bazada ILOVA ko'tariladimi ───────────────────────────
    smoke = ("import json\n"
             "from fastapi.testclient import TestClient\n"
             "from app.main import app\n"
             "r = TestClient(app).get('/api/v1/health/ready')\n"
             "print(json.dumps({'s': r.status_code, 'b': r.json()}))\n")
    # ⚠️  `SECRET_KEY` xavfsizlik SIYOSATIGA mos bo'lishi SHART (>=32 belgi, >=8 xil
    #     belgi, shablon emas). Bu qadam `APP_ENV=prod` bilan HAQIQIY production
    #     boot'ini taqlid qiladi, ya'ni yangi gate zaif kalitni ataylab rad etadi —
    #     qisqa "test" kaliti bilan smoke test gate'ni sinamas, unga qoqilardi.
    # Vendor portali bu smoke testda ISHTIROK ETMAYDI — u tiklangan bazada ilova
    # ko'tariladimi, degan savolni sinaydi. Portal yoqiq bo'lsa production siyosati
    # undan 2FA va IP allowlist talab qiladi (to'g'ri), lekin bu shu testning mavzusi
    # emas; shuning uchun kalit BERILMAYDI va portal o'chiq qoladi.
    r = _run([py, "-c", smoke],
             {"DATABASE_URL": _plain(tgt_url), "APP_ENV": "prod",
              "VENDOR_ADMIN_KEY": "",
              "SECRET_KEY": "Rk7-Qz2mR9vT4wX8nL1pJ6hB3sD5gY0cW"}, cwd=SERVER)
    assert r.returncode == 0, r.stderr[-500:]
    body = json.loads(r.stdout.strip().splitlines()[-1])
    assert body["s"] == 200 and body["b"]["checks"]["cash_schema"] is True, body
