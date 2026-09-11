# -*- coding: utf-8 -*-
"""MIGRATSIYA — MAVJUD bazada (bo'sh emas).

⚠️  NEGA ALOHIDA FAYL: qolgan testlar har safar TOZA bazadan boshlanadi va u yerda
    `Base.metadata.create_all()` jadvalni MODELDAN yaratadi — ya'ni yangi ustunlar
    ALTER'siz paydo bo'ladi. Shu sabab "ustun migratsiyasi yo'q" degan nuqson
    butun to'plamda KO'RINMAYDI va faqat jonli bazada portlaydi. Aynan shunday
    bo'ldi: `ux_products_external_identity` staging'da "column source_system does
    not exist" bilan yiqildi, chunki `_ADDED_COLUMNS` ga ikki qator yozilmagan edi.

    Bu yerdagi testlar ESKI sxemani ataylab qayta tiklab (ustunni TASHLAB), keyin
    migratsiyani yurgizadi — ya'ni ular ALTER yo'lini HAQIQATAN o'lchaydi.
"""
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

RUNNER = textwrap.dedent(r"""
    import json, os, sys
    os.environ["DATABASE_URL"] = sys.argv[1]
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("VENDOR_ADMIN_KEY", "k")
    from sqlalchemy import text
    from app import initdb
    from app.db.session import engine

    step = sys.argv[2]
    if step == "create":
        initdb.main()
    elif step == "drop_cols":
        # INDEKS AVVAL: ustun indekslangan bo'lsa SQLite uni tashlashga yo'l qo'ymaydi.
        with engine.begin() as con:
            con.execute(text("DROP INDEX IF EXISTS ux_products_external_identity"))
            for c in ("source_system", "external_id"):
                con.execute(text(f"ALTER TABLE products DROP COLUMN {c}"))
    elif step == "migrate":
        initdb.main()
    elif step == "report":
        from sqlalchemy import inspect
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("products")}
        idx = {i["name"] for i in insp.get_indexes("products")}
        print("RESULT " + json.dumps({
            "source_system": "source_system" in cols,
            "external_id": "external_id" in cols,
            "index": "ux_products_external_identity" in idx,
        }))
""")


def _run(db_url: str, step: str, cwd: pathlib.Path) -> str:
    """Har qadam ALOHIDA jarayonda — SQLAlchemy metadata/inspector keshi
    qadamlar orasida olib o'tilmasin (aks holda test o'zini aldardi)."""
    r = subprocess.run([sys.executable, "-c", RUNNER, db_url, step],
                       capture_output=True, text=True, cwd=str(cwd),
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert r.returncode == 0, f"{step} yiqildi:\n{r.stdout}\n{r.stderr}"
    return r.stdout


@pytest.fixture
def legacy_db(tmp_path):
    """V2 ustunlarisiz — ya'ni migratsiyadan OLDINGI jonli baza nusxasi."""
    root = pathlib.Path(__file__).resolve().parents[1]
    db = tmp_path / "legacy.db"
    url = f"sqlite:///{db.as_posix()}"
    _run(url, "create", root)      # to'liq sxema
    _run(url, "drop_cols", root)   # V2 ustunlarini OLIB TASHLAYMIZ -> eski holat
    return url, root


def test_eski_bazada_V2_ustunlari_YO_Q(legacy_db):
    """Nazorat: fixture haqiqatan ESKI sxemani beradi (aks holda test bo'sh bo'lardi)."""
    url, root = legacy_db
    out = _run(url, "report", root)
    res = json.loads(out.split("RESULT ", 1)[1].strip())
    assert res == {"source_system": False, "external_id": False, "index": False}, res


def test_migratsiya_MAVJUD_bazaga_ustun_va_indeks_QOSHADI(legacy_db):
    """ASOSIY TALAB: `create_all` mavjud jadvalga ustun qo'shmaydi — ALTER shart."""
    url, root = legacy_db
    _run(url, "migrate", root)
    out = _run(url, "report", root)
    res = json.loads(out.split("RESULT ", 1)[1].strip())
    assert res["source_system"] is True, "source_system ustuni QO'SHILMADI"
    assert res["external_id"] is True, "external_id ustuni QO'SHILMADI"
    assert res["index"] is True, "ux_products_external_identity YARATILMADI"


def test_migratsiya_IDEMPOTENT(legacy_db):
    """Ikki marta yurgizish xatosiz o'tadi (har deploy'da qayta yuradi)."""
    url, root = legacy_db
    _run(url, "migrate", root)
    _run(url, "migrate", root)
    out = _run(url, "report", root)
    res = json.loads(out.split("RESULT ", 1)[1].strip())
    assert all(res.values()), res


def test_indeks_ustunlarsiz_YARATILMAYDI_degan_XATONI_takrorlaydi(legacy_db):
    """SALBIY NAZORAT — staging'da yuz bergan aynan shu nosozlik.

    `_ADDED_COLUMNS` dan V2 qatorlari olib tashlansa, indeks "column does not
    exist" bilan yiqiladi va migratsiya JIMGINA to'liqsiz qoladi.
    """
    url, root = legacy_db
    marker = "from app import initdb\n"
    patched = RUNNER.replace(
        marker,
        marker + "initdb._ADDED_COLUMNS = [c for c in initdb._ADDED_COLUMNS\n"
                 "                         if c[1] not in ('source_system', 'external_id')]\n", 1)
    # Yamoq HAQIQATAN qo'llanganini tekshiramiz. Avval u jimgina qo'llanmagan edi
    # (RUNNER `textwrap.dedent` dan o'tgani uchun qator chap chekkada turadi) va
    # salbiy nazorat oddiy migratsiyani o'lchab, o'zini aldagandi.
    assert patched != RUNNER, "salbiy nazorat yamog'i QO'LLANMADI"
    r = subprocess.run([sys.executable, "-c", patched, url, "migrate"],
                       capture_output=True, text=True, cwd=str(root),
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert r.returncode == 0, r.stderr
    out = _run(url, "report", root)
    res = json.loads(out.split("RESULT ", 1)[1].strip())
    assert res["source_system"] is False, "salbiy nazorat ma'nosiz — ustun baribir paydo bo'ldi"
    assert res["index"] is False, "salbiy nazorat ma'nosiz — indeks baribir yaratildi"
