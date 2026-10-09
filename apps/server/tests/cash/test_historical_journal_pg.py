# -*- coding: utf-8 -*-
"""Tarixiy jurnal — ALOHIDA SESSIYANING haqiqiy qiymati (FAQAT Postgres).

NEGA BU FAYL BOR
================
`tests/test_historical_http_journal.py` jurnalning «dispatchdan OLDIN commit»
xossasini qadaydi, lekin ALOHIDA sessiya qarorini ISBOTLAMAYDI: `claim` darhol
commit qilgani uchun umumiy sessiyada ham qator durable bo'ladi. Buni mutatsiya
o'lchovi ko'rsatdi (jurnalni biznes sessiyasiga ko'chirish SQLite to'plamida
TUTILMADI).

Alohida sessiyaning jonli qiymati AYNAN SHU YERDA ko'rinadi: Postgres'da xatodan
keyin tranzaksiya ABORTED holatga o'tadi va o'sha sessiyada BIRORTA bayonot
bajarilmaydi (`InFailedSqlTransaction`). Ya'ni `mark_failed` o'sha sessiyada
IZNI YOZA OLMAYDI — muvaffaqiyatsiz urinish hech qanday iz qoldirmasdan
yo'qolardi, bu esa `services/catalog_commit_v2.py:390-397` aynan ogohlantirgan
holat.

⚠️  SQLite BUNGA TOQAT QILADI — xatodan keyin ham o'sha sessiyada yozish
    mumkin. Shu bois mahalliy to'plam bu nuqsonni KO'RSATMAYDI va tekshiruv
    faqat shu yerda bo'lishi mumkin.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.historical import HistoricalPlanEvent
from app.services import historical_journal as HJ

D0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


def _kalit():
    return uuid.uuid4()


def _claim(sess, cashenv, key, *, plan="pg-plan"):
    canon = HJ.canonical(event_type="shift_open", occurred_at=D0,
                         branch_id=cashenv.branch_id,
                         actor_employee_id=cashenv.employee_id,
                         payload={"opening_cash": 1000})
    yangi, mavjud = HJ.claim(
        sess, company_id=cashenv.company_id, branch_id=cashenv.branch_id,
        actor_employee_id=cashenv.employee_id, plan_id=plan,
        event_type="shift_open", event_key=key, occurred_at=D0, canon=canon)
    assert mavjud is None, "kalit band — test sahnasi iflos"
    return yangi


def _abort(sess):
    """Tranzaksiyani PG'da ABORTED holatga keltiradi."""
    with pytest.raises(DBAPIError):
        sess.execute(text("SELECT 1 FROM jadval_umuman_yoq_12345"))


def test_ABORTED_tranzaksiyada_AYNI_sessiya_IZ_yoza_OLMAYDI(cashenv):
    """NAZORAT: muammoning O'ZI shu yerda ko'rsatiladi.

    Bu test nuqsonni MAQTAMAYDI — u `mark_failed` ni umumiy sessiyada
    chaqirish NIMA UCHUN yaramasligini o'lchaydi. Shu testsiz keyingi test
    «alohida sessiya yaxshi» degan ASOSSIZ bayonot bo'lardi.
    """
    key = _kalit()
    #  Qator ALOHIDA sessiyada yaratiladi (durable bo'lsin).
    with Session(cashenv.engine) as j:
        row = _claim(j, cashenv, key)
        rid = row.id

    #  Biznes sessiyasi: qatorni o'qiymiz, keyin tranzaksiyani BUZAMIZ.
    with Session(cashenv.engine) as r:
        biznes_row = r.get(HistoricalPlanEvent, rid)
        assert biznes_row is not None
        _abort(r)
        #  ⚠️  ENDI shu sessiyada HECH NARSA bajarilmaydi.
        biznes_row.status = HJ.FAILED
        biznes_row.error = "IZ YOZILISHI KERAK EDI"
        with pytest.raises(DBAPIError):
            r.commit()

    #  Iz YOZILMAGAN — muammo shu.
    with Session(cashenv.engine) as k:
        hol = k.get(HistoricalPlanEvent, rid)
        assert hol.status == HJ.STARTED, (
            f"holat={hol.status} — aborted sessiyada yozuv O'TDI, ya'ni bu "
            f"testning asosi yo'qolgan")
        assert hol.error is None


def test_ALOHIDA_sessiyada_mark_failed_IZNI_yozadi(cashenv):
    """ASOSIY DA'VO: alohida sessiya aborted biznes tranzaksiyasidan mustaqil.

    Bu — `historical_exec` ning haqiqiy quvuri: jurnal `jdb`, biznes `db`.
    Biznes tomoni yiqilsa ham `mark_failed` izni YOZADI.
    """
    key = _kalit()
    with Session(cashenv.engine) as j, Session(cashenv.engine) as r:
        row = _claim(j, cashenv, key)
        rid = row.id
        #  Biznes tomoni yiqiladi va tranzaksiya ABORTED bo'ladi.
        _abort(r)
        #  Jurnal sessiyasi TEGILMAGAN — iz yoziladi.
        HJ.mark_failed(j, row, "ValueError: biznes yiqildi")

    with Session(cashenv.engine) as k:
        hol = k.get(HistoricalPlanEvent, rid)
        assert hol.status == HJ.FAILED, f"holat={hol.status} — iz yozilmadi"
        assert "biznes yiqildi" in (hol.error or ""), hol.error


def test_NOYOB_INDEKS_ikkinchi_rezervatsiyani_TOSADI(cashenv):
    """`ux_hist_plan_event` — haqiqiy Postgres noyoblik kafolati.

    ⚠️  NEGA PG'DA. SQLite ham noyoblikni majburlaydi, lekin bu yerda
        QO'SHIMCHA narsa o'lchanadi: ikkinchi `claim` IntegrityError oladi va
        `claim` uni MAVJUD qatorga aylantiradi (jim «muvaffaqiyat» emas,
        «takror» qarorini chaqiruvchiga qaytaradi).
    """
    key = _kalit()
    with Session(cashenv.engine) as j1:
        _claim(j1, cashenv, key)
    with Session(cashenv.engine) as j2:
        canon = HJ.canonical(event_type="shift_open", occurred_at=D0,
                             branch_id=cashenv.branch_id,
                             actor_employee_id=cashenv.employee_id,
                             payload={"opening_cash": 1000})
        yangi, mavjud = HJ.claim(
            j2, company_id=cashenv.company_id, branch_id=cashenv.branch_id,
            actor_employee_id=cashenv.employee_id, plan_id="pg-plan",
            event_type="shift_open", event_key=key, occurred_at=D0, canon=canon)
        assert yangi is None and mavjud is not None, (yangi, mavjud)
        assert mavjud.event_key == key


def test_INDEKS_SHAKLI_registrga_MOS(cashenv):
    """Shakl registri jonli `pg_indexes` ta'rifiga mos kelsin.

    ⚠️  NEGA MUHIM. `index_guard` shakl tekshiruvini FAQAT registrdagi
        indekslarga qo'llaydi. Shakl XATO yozilgan bo'lsa hukm `BAD` bo'lib
        HAR yozuvni to'sardi (`services/shifts.py:93-99` aynan shu tuzoqni
        qayd etgan: enum predikatli indeks shakli). Shu bois registr
        yozuvi jonli bazada TEKSHIRILADI.
    """
    from app.core import index_guard as IG
    from app.core import required_schema as rs
    assert ("ux_hist_plan_event", "historical_plan_events") in rs.REQUIRED_INDEXES
    assert rs.REQUIRED_INDEX_DEFINITIONS["ux_hist_plan_event"] == (
        "historical_plan_events", ("company_id", "event_key"), None)
    hol = IG.index_state(cashenv.engine, "ux_hist_plan_event",
                         "historical_plan_events")
    #  ⚠️  Hukm KICHIK harfda qaytadi (`index_guard` docstringida `OK` deb
    #      yozilgan, amalda `"ok"`). Gard `!= "ok"` ni rad etadi, shu bois
    #      aynan shu qiymat talab qilinadi.
    assert hol == "ok", (
        f"indeks hukmi {hol!r} — registr yozuvi jonli ta'rifga MOS KELMAYDI; "
        f"bu holatda gard HAR yozuvni to'sardi")


def test_FK_lar_YETIM_qatorni_RAD_etadi(cashenv):
    """⚠️  SQLite bu loyihada FK buzilishini KO'RMAYDI — shu bois PG'da.

    Jurnal uchta FK tashiydi (`company_id`, `branch_id`, `actor_employee_id`).
    Ular ataylab bor: ijarachi chalkashligi BAZADA ham imkonsiz bo'lsin.
    """
    from sqlalchemy.exc import IntegrityError
    with Session(cashenv.engine) as j:
        canon = HJ.canonical(event_type="shift_open", occurred_at=D0,
                             branch_id=cashenv.branch_id,
                             actor_employee_id=cashenv.employee_id,
                             payload={})
        with pytest.raises(IntegrityError):
            HJ.claim(j, company_id=uuid.uuid4(),        # YO'Q do'kon
                     branch_id=cashenv.branch_id,
                     actor_employee_id=cashenv.employee_id, plan_id="pg-plan",
                     event_type="shift_open", event_key=_kalit(),
                     occurred_at=D0, canon=canon)


def test_OCCURRED_AT_timestamptz_sifatida_saqlanadi(cashenv):
    """Tarixiy lahza mintaqa bilan saqlansin — UTC siljimasin.

    ⚠️  SQLite `DateTime(timezone=True)` da `tzinfo` ni JIMGINA tashlab
        yuboradi, shu bois bu kafolat faqat PG'da o'lchanadi.
    """
    key = _kalit()
    t = datetime(2026, 3, 1, 8, 0, tzinfo=timezone(timedelta(hours=6)))
    with Session(cashenv.engine) as j:
        canon = HJ.canonical(event_type="shift_open", occurred_at=t,
                             branch_id=cashenv.branch_id,
                             actor_employee_id=cashenv.employee_id, payload={})
        row = HJ.claim(j, company_id=cashenv.company_id,
                       branch_id=cashenv.branch_id,
                       actor_employee_id=cashenv.employee_id, plan_id="pg-plan",
                       event_type="shift_open", event_key=key,
                       occurred_at=t, canon=canon)[0]
        rid = row.id
    with Session(cashenv.engine) as k:
        got = k.get(HistoricalPlanEvent, rid).occurred_at
        assert got.tzinfo is not None, "mintaqa yo'qoldi"
        assert got == t.astimezone(timezone.utc), (got, t)
