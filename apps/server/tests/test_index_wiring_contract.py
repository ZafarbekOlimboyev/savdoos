# -*- coding: utf-8 -*-
"""QAYSI YOZUVCHI QAYSI INDEKSNI TALAB QILADI — SIMLASH RO'YXATI (DB'siz).

⚠️  NEGA MANBA MATNIDAN. `require_index` chaqirig'i yozuvchining ICHIDA, ya'ni uni
    import vaqtida ko'rib bo'lmaydi va chaqirmasdan tekshirib ham bo'lmaydi
    (har biri baza, smena, hujjat talab qiladi). Shu bois ro'yxat MANBA matnidan
    o'qiladi: gard olib tashlansa yoki indeks nomi almashtirilsa bu test QIZIL
    bo'ladi. Yozuvchining HAQIQIY fail-closed xulqi alohida faylda, haqiqiy
    Postgres bilan: `tests/test_index_wiring_pg.py`.

⚠️  Bu ro'yxat QAMROV bayonoti ham: unda bo'lmagan idempotentlik indeksi ATAYLAB
    simlanmagan (sabablari hisobotda: qulf kalit bilan mos tushadi, dublikat boshqa
    cheklov bilan to'silgan, yoki jonli yozuvchisi yo'q).
"""
from __future__ import annotations

import io
import re

import pytest

from app.core import required_schema as rs

#  (fayl, funksiya, indeks, jadval, operation)
SIMLASH = [
    ("app/services/doc_seq.py", "allocate", "ux_doc_counter", "doc_counters", "doc_seq"),
    ("app/services/subscription/lifecycle.py", "enrol",
     "ux_subscriptions_company", "subscriptions", "subscription_enrol"),
    ("app/services/subscription/payments.py", "record_payment",
     "ux_subpay_client_uuid", "subscription_payments", "subscription_payment"),
    ("app/services/sales.py", "_create_sale_once",
     "ux_sales_company_client_uuid", "sales", "sale"),
    ("app/api/v1/sales.py", "_create_return_once",
     "ux_returns_client_uuid", "returns", "return"),
    ("app/api/v1/receiving.py", "_commit_once",
     "ux_receivings_client_uuid", "receivings", "receiving"),
    ("app/services/lot_correction.py", "correct",
     "ux_recv_corr_client", "receiving_corrections", "receiving_correction"),
    ("app/api/v1/purchases.py", "_create_purchase_once",
     "ux_purchases_client_uuid", "purchases", "purchase"),
    ("app/api/v1/inventory.py", "writeoff",
     "ux_stockmov_client_prod_type", "stock_movements", "writeoff"),
    ("app/api/v1/cashops.py", "cash_op",
     "ux_cashmov_client_uuid_all", "cash_movements", "cash_op"),
    ("app/api/v1/cashops.py", "_transfer_once",
     "ux_stockmov_client_prod_type", "stock_movements", "transfer"),
    ("app/api/v1/shifts.py", "open_shift",
     "ux_shifts_cashier_open", "shifts", "shift_open"),
]

#: Simlangan, LEKIN shakli ATAYLAB ro'yxatga olinmagan indekslar — sabab bilan.
#
#  ⚠️  Bu ro'yxat bo'sh bo'lishi KERAK EMAS, lekin har bir a'zo O'LCHANGAN sabab
#      bilan kirishi SHART. Shakl ro'yxatiga qo'shish hukmni `IX_DEF_WRONG` qilса,
#      gard SIMLANGAN yozuvni HAR so'rovda 409 qilardi — ya'ni «ro'yxat to'liq
#      bo'lsin» deb qo'shish uzilish keltirardi.
SHAKLSIZ = {
    "ux_shifts_cashier_open":
        "predikat ENUM solishtiruvini o'z ichiga oladi (`status = 'open'::shift_status`); "
        "`_same_predicate`/`check_canon` cast'ni faqat text/varchar ustunlar uchun "
        "normallashtiradi (`_INDEX_DEF_SQL` `txtcols` ni shunday yig'adi), shu bois "
        "e'lon qilingan shakl `IX_DEF_WRONG` beradi va gard har smena ochishni 409 "
        "qilardi. O'lchangan haqiqiy Postgres'da.",
}


def _tana(path: str, fn: str) -> str:
    """Funksiya tanasi — keyingi yuqori darajali `def`/`@`/`class` gacha."""
    s = io.open(path, encoding="utf-8").read().split("\n")
    bosh = next(i for i, l in enumerate(s)
                if re.match(rf"^(async )?def {re.escape(fn)}\(", l))
    for j in range(bosh + 1, len(s)):
        if re.match(r"^(@|def |async def |class )", s[j]):
            return "\n".join(s[bosh:j])
    return "\n".join(s[bosh:])


@pytest.mark.parametrize("path,fn,ix,tbl,op", SIMLASH,
                         ids=[f"{p.split('/')[-1]}::{f}" for p, f, *_ in SIMLASH])
def test_YOZUVCHI_gardni_CHAQIRADI(path, fn, ix, tbl, op):
    tana = _tana(path, fn)
    assert "require_index(" in tana, f"{path}::{fn} gardni chaqirmaydi"
    assert f'"{ix}"' in tana, f"{path}::{fn} {ix} ni talab qilmaydi"
    assert f'"{tbl}"' in tana, f"{path}::{fn} {tbl} jadvalini ko'rsatmaydi"
    assert f'operation="{op}"' in tana, f"{path}::{fn} operation={op} emas"


def test_GARD_boshqa_joyda_SIMLANMAGAN():
    """Ro'yxat TO'LIQ: `app/` dagi har bir `require_index(db` chaqirig'i ro'yxatda bo'lsin.

    ⚠️  Bu ikki tomonlama qulf: yangi gard qo'shilsa ham ro'yxat yangilanishi SHART,
        aks holda qamrov bayonoti jimgina eskirardi.
    """
    import subprocess
    r = subprocess.run(["git", "grep", "-n", "require_index(db", "--", "app"],
                       capture_output=True, text=True, encoding="utf-8")
    #  ⚠️  Ta'rifning O'ZI chiqib qolmasin: `def require_index(db, index: str, ...)`
    #      ham shu naqshga mos keladi.
    topilgan = [l for l in r.stdout.splitlines()
                if l.strip() and "def require_index(" not in l]
    assert len(topilgan) == len(SIMLASH), (
        f"gard chaqiruvlari {len(topilgan)}, ro'yxatda {len(SIMLASH)}:\n"
        + "\n".join(topilgan))


def test_SIMLANGAN_indekslarning_SHAKLI_ROYXATGA_olingan():
    """Simlangan har bir indeks `REQUIRED_INDEX_DEFINITIONS` da bo'lishi SHART.

    ⚠️  NEGA. Shakl tekshiruvi FAQAT shu ro'yxatdagilarga tegishli
        (`index_guard.index_state`). Ro'yxatda bo'lmasa gard faqat NOYOBLIKni
        ko'rardi: ayni nomli, lekin boshqa ustunli yoki predikatsiz indeks
        «sog'lom» bo'lib o'tardi — bu esa indeks umuman yo'qligidan ham yomonroq,
        chunki operator uni sog'lom deb bilardi.
    """
    for _p, _f, ix, tbl, _op in SIMLASH:
        if ix in SHAKLSIZ:
            #  ⚠️  ATAYLAB ro'yxatda YO'Q. Sabab yozilgan bo'lishi va indeks shakl
            #      ro'yxatiga TUSHMAGAN bo'lishi SHART: aks holda kimdir uni
            #      «to'liqlik uchun» qo'shib, gardni har so'rovda 409 qilardi.
            assert SHAKLSIZ[ix].strip(), f"{ix}: sababsiz istisno"
            assert ix not in rs.REQUIRED_INDEX_DEFINITIONS, (
                f"{ix} SHAKLSIZ ro'yxatida, lekin DEFINITIONS ga qo'shilgan — "
                f"gard endi har yozuvni to'sadi. Sabab: {SHAKLSIZ[ix]}")
            continue
        assert ix in rs.REQUIRED_INDEX_DEFINITIONS, f"{ix} shakl ro'yxatida yo'q"
        assert rs.REQUIRED_INDEX_DEFINITIONS[ix][0] == tbl, (
            f"{ix}: ro'yxatdagi jadval {rs.REQUIRED_INDEX_DEFINITIONS[ix][0]}, "
            f"gard esa {tbl} deydi — SAFE-02 bo'yicha bu UNVERIFIABLE berib "
            f"yozuvni TO'SARDI")


def test_BOOT_xulqi_ozgarmagan():
    """Shakl ro'yxatiga qo'shish BOOT ni yiqitmaydi.

    ⚠️  `initdb._required_index` faqat `REQUIRED_INDEXES` ni o'qiydi. Yangi shakl
        yozuvlari u ro'yxatga TEGMAGAN, ya'ni birorta mavjud baza boot'da
        yiqilmaydi — ular faqat SHAKL hukmini yoqadi.
    """
    nomlar = {n for n, _t in rs.REQUIRED_INDEXES}
    #  Faqat idempotentlik indekslari: ular REQUIRED_INDEXES ga KIRMASLIGI kerak.
    for ix in ("ux_sales_company_client_uuid", "ux_returns_client_uuid",
               "ux_purchases_client_uuid", "ux_receivings_client_uuid",
               "ux_cashmov_client_uuid_all", "ux_stockmov_client_prod_type"):
        assert ix not in nomlar, (
            f"{ix} REQUIRED_INDEXES ga qo'shilgan — mavjud bazalarda boot YIQILARDI")
        assert ix in rs.REQUIRED_INDEX_DEFINITIONS
