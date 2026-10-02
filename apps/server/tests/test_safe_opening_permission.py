# -*- coding: utf-8 -*-
"""Phase 1 — `kassa.attest` RUXSAT SIMLARI (`PHASE1.md` §4, test T-17 ning HTTP yarmi).

Bu yerda BAZA kerak emas darajadagi tekshiruvlar + `initdb._ensure_catalog` orqali
MAVJUD do'kon ham ruxsatni olishi (SQLite bootda ham ishlaydi).

⚠️  Xizmat qatlamidagi MENEJER+ darvozasi alohida: `tests/cash/test_safe_opening.py`.
    IKKALASI BIRGA talab qilinadi — ruxsat berilgan, lekin roli menejer+ bo'lmagan
    xodim HAM rad etiladi.
"""
from __future__ import annotations

import subprocess
import sys
import os

from sqlalchemy import create_engine, text

from app import seed as S
from app.api.v1 import tills as tills_api

SRV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = "kassa.attest"


def test_ruxsat_royxatda_va_modulida():
    assert (CODE, "kassa") in S.PERMISSIONS, "kassa.attest PERMISSIONS da YO'Q"
    assert CODE not in S.ADMIN_EXCLUDE, "administrator uni OLISHI kerak"


def test_rollar_kimga_beriladi():
    # ega / administrator — "ALL" (ADMIN_EXCLUDE dan tashqari hammasi)
    assert S.ROLES["ega"][1] == "ALL"
    assert S.ROLES["administrator"][1] == "ALL"
    # menejer — ANIQ ro'yxatda
    assert CODE in S.ROLES["menejer"][1]
    # kassir / omborchi — YO'Q
    assert CODE not in S.ROLES["kassir"][1]
    assert CODE not in S.ROLES["omborchi"][1]


def test_marshrut_darvozasi_aynan_shu_kod():
    """`POST /safes/{id}/opening` AYNAN `kassa.attest` bilan yopilgan."""
    import inspect
    assert 'require("kassa.attest")' in inspect.getsource(tills_api)
    # marshrut ro'yxatda
    paths = {r.path for r in tills_api.router.routes}
    assert "/safes/{safe_id}/opening" in paths
    assert "/safes/{safe_id}/balance" in paths


def test_balans_darvozasi_kassir_kodlarini_olmaydi():
    perms = set(tills_api.SAFE_BALANCE_READ_PERMS)
    assert not ({"kassa.sell", "kassa.view"} & perms)
    # ⚠️  `hisobot.view` ALMASHTIRUVCHI EMAS: u faqat O'QISH uchun. Attestatsiya
    #     (yozish) AYNAN `kassa.attest` talab qiladi — quyidagi test buni qotiradi.
    assert "hisobot.view" in perms


def test_yozish_uchun_hisobot_view_yetmaydi():
    """Yozuv marshrutida `hisobot.view` yoki `sozlamalar.edit` O'RNINI BOSMAYDI."""
    import inspect
    src = inspect.getsource(tills_api.attest_safe_opening)
    assert "hisobot.view" not in src
    assert 'require("sozlamalar.edit")' not in src


def test_mavjud_dokon_bootda_ruxsatni_oladi(tmp_path):
    """`_ensure_catalog` HAR bootda yetishmayotgan ruxsatni qo'shadi va rollarga bog'laydi.

    ⚠️  Bu Phase 1 ning MAVJUD do'konlar uchun yagona yetkazish yo'li: migratsiya
        freymvorki yo'q, ruxsat esa yangi."""
    url = "sqlite:///" + str(tmp_path / "perm.db").replace("\\", "/")
    env = dict(os.environ, DATABASE_URL=url, APP_ENV="test")
    r = subprocess.run([sys.executable, "-m", "app.initdb"], cwd=SRV, capture_output=True,
                       text=True, timeout=900, env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    eng = create_engine(url, future=True)
    try:
        with eng.connect() as con:
            assert con.execute(text("SELECT 1 FROM permissions WHERE code = :c"),
                               {"c": CODE}).first() is not None, "ruxsat yaratilmadi"
            # menejer roli uni OLGAN
            got = con.execute(text(
                "SELECT 1 FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE r.code = 'menejer' AND p.code = :c"), {"c": CODE}).first()
            assert got is not None, "menejer rolига bog'lanmadi"
            # kassir OLMAGAN
            bad = con.execute(text(
                "SELECT 1 FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE r.code = 'kassir' AND p.code = :c"), {"c": CODE}).first()
            assert bad is None, "kassir ruxsatni OLDI"
    finally:
        eng.dispose()


def test_require_yopiq_royxatdan_tashqari_kodga():
    """`deps.require` — fail-closed: ro'yxatda bo'lmagan kod HECH KIMGA ochilmaydi
    (FULL_ACCESS_ROLES dan tashqari)."""
    from app.core.deps import FULL_ACCESS_ROLES
    assert FULL_ACCESS_ROLES == ("ega", "administrator")
