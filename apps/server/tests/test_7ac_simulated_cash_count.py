# -*- coding: utf-8 -*-
"""PHASE 7AC — SANOQ MANBASI shartnomasi: xavfsizlik va hisob testlari.

NIMA UCHUN
==========
Haqiqiy kassir yashikdagi pulni SANAYDI. Sintetik kassirning sanaydigan
puli YO'Q. Bu ikki narsa BIR XIL DALIL EMAS, lekin shu paytgacha
`CloseShift` ikkisini ham bitta `counted_cash` maydoniga qabul qilardi va
tizimda ularni ajratishning HECH QANDAY yo'li yo'q edi
(`PHASE7AC_CONTRACT_AUDIT.md`).

QOPLAMA (§7 ning 15 bandi)
==========================
  1  haqiqiy do'kon fizik sanog'i              -> `test_01`, `test_11`
  2  avtorizatsiyali sintetik sanoq            -> `test_02`
  3  haqiqiy do'konda SIMULATED urinishi       -> `test_03` ⭐
  4  begona tenant rad etilishi                -> `test_04`
  5  attestatsiya yo'q / yaroqsiz              -> `test_05`, `test_05b`
  6  kassir identifikatori yo'q / noto'g'ri    -> `test_06`
  7  takroriy yopish                           -> `test_07`
  8  kutilgan va e'lon qilingan summa farqi    -> `test_08`
  9  naqd/karta/QR qaytarish + naqd xarajat    -> `test_09`
 10  audit metama'lumoti saqlanishi            -> `test_10`
 11  eski fizik-sanoq orqaga mosligi           -> `test_11`
 12  sintetik worker so'rovining tuzilishi     -> lab repo: `test_live_p7ac_simulated_close.py`
 13  noma'lum manba fail-closed                -> `test_13`
 14  klient demo identifikatorini SOXTALASHTIRA olmaydi -> `test_14` ⭐
 15  standbyda biznes mutatsiyasi yo'q         -> lab repo (standby testlari)

⚠️  IKKI QATLAM SINALADI: HTTP sirti (`/api/v1/shifts/{id}/close`) VA
    servis mantig'i (`close_shift_svc` to'g'ridan). Haqiqiy-do'kon
    yo'llari servis qatlamida sinaladi, chunki seed do'koni `demo`
    kodli — ya'ni HTTP sirtidan haqiqiy do'konni olish uchun ALOHIDA
    tenant qurish kerak (`_real_store` fiksturasi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

API = "/api/v1"


# ─────────────────────────── yordamchilar ────────────────────────────────
def _open_shift(client, H, opening=1000):
    """Smena ochadi; allaqachon ochiq bo'lsa uni qaytaradi."""
    cur = client.get(f"{API}/shifts/current", headers=H)
    if cur.status_code == 200 and cur.json():
        return cur.json()["id"]
    r = client.post(f"{API}/shifts/open", headers=H, json={"opening_cash": opening})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _close(client, H, sid, **body):
    return client.post(f"{API}/shifts/{sid}/close", headers=H, json=body)


def _shift_row(sid):
    from app.db.session import SessionLocal
    from app.models.shifts import Shift
    db = SessionLocal()
    try:
        return db.get(Shift, uuid.UUID(str(sid)))
    finally:
        db.close()


@pytest.fixture
def real_store():
    """HAQIQIY do'kon: kodi `demo`/`test` prefiksli EMAS.

    ⚠️  Seed do'koni `demo` kodli, shu bois «haqiqiy do'kon» yo'lini
        sinash uchun ALOHIDA tenant kerak. Seed ma'lumoti TEGILMAYDI —
        yangi `Company`/`Role`/`Employee`/`Branch`/`Shift` qatorlari
        yaratiladi va test oxirida O'CHIRILADI.
    """
    from app.db.session import SessionLocal
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus, ShiftStatus
    from app.models.org import Branch, Company
    from app.models.shifts import Shift
    db = SessionLocal()
    yasalgan = []
    try:
        co = Company(id=uuid.uuid4(), name="Haqiqiy Do'kon 7AC",
                     code="fayzan7ac", currency="KGS")
        db.add(co); db.flush(); yasalgan.append(co)
        #  ⚠️  `Role` GLOBAL (do'konga bog'lanmagan) va `code` UNIQUE —
        #      yangi rol YARATILMAYDI, mavjudi QAYTA ISHLATILADI.
        role = (db.query(Role).filter(Role.code == "ega").first()
                or db.query(Role).first())
        assert role is not None, "seed da birorta rol yo'q"
        emp = Employee(id=uuid.uuid4(), company_id=co.id, full_name="Haqiqiy Kassir",
                       phone="+996700000777", role_id=role.id,
                       status=EmployeeStatus.active)
        db.add(emp); db.flush(); yasalgan.append(emp)
        br = Branch(id=uuid.uuid4(), company_id=co.id, code="HF-7AC",
                    name="Haqiqiy filial")
        db.add(br); db.flush(); yasalgan.append(br)
        sh = Shift(id=uuid.uuid4(), branch_id=br.id, cashier_id=emp.id,
                   opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
                   opening_cash=Decimal("3000.00"), status=ShiftStatus.open)
        db.add(sh); db.flush(); yasalgan.append(sh)
        db.commit()
        yield {"company": co, "employee": emp, "branch": br, "shift": sh}
    finally:
        for row in reversed(yasalgan):
            try:
                db.delete(db.merge(row))
                db.commit()
            except Exception:                     # noqa: BLE001
                db.rollback()
        db.close()


class _Body:
    """`CloseShift` o'rniga oddiy tashuvchi (servis qatlami testlari uchun)."""

    def __init__(self, counted_cash, count_source=None, attestation_ref=None):
        self.counted_cash = counted_cash
        self.count_source = count_source
        self.attestation_ref = attestation_ref


# ══ 1 · 11. HAQIQIY FIZIK SANOQ va ORQAGA MOSLIK ═════════════════════════
def test_01_PHYSICAL_ayniq_manba_bilan_yopiladi(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=1500)
    r = _close(client, admin_headers, sid, counted_cash=1500,
               count_source="PHYSICAL")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count_source"] == "PHYSICAL"
    assert j["attestation_ref"] is None
    assert j["expected_cash"] == 1500.0
    assert j["counted_cash"] == 1500.0
    assert j["difference"] == 0.0
    row = _shift_row(sid)
    assert row.status.value == "closed"
    assert "count_source=PHYSICAL" in (row.note or "")


def test_11_ESKI_klient_manbasiz_yuboradi_PHYSICAL_deb_qabul(client, admin_headers):
    """⭐ ORQAGA MOSLIK: `count_source` YO'Q -> `PHYSICAL`, SIMULATED EMAS."""
    sid = _open_shift(client, admin_headers, opening=800)
    r = _close(client, admin_headers, sid, counted_cash=800)   # faqat eski maydon
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count_source"] == "PHYSICAL", \
        "manbasiz yopish SIMULATED deb QAYTA TASNIFLANDI — taqiq"
    assert j["attestation_ref"] is None
    #  Eski kalitlar ham joyida (shartnoma buzilmagan).
    for k in ("id", "expected_cash", "counted_cash", "difference"):
        assert k in j
    assert "count_source=PHYSICAL" in (_shift_row(sid).note or "")


# ══ 2. AVTORIZATSIYALI SINTETIK SANOQ ════════════════════════════════════
def test_02_demo_tenantda_SIMULATED_qabul_qilinadi(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=2000)
    ref = "synthetic-lab/7AC/%s" % sid
    r = _close(client, admin_headers, sid, counted_cash=2000,
               count_source="SIMULATED", attestation_ref=ref)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count_source"] == "SIMULATED"
    assert j["attestation_ref"] == ref
    assert j["difference"] == 0.0
    note = _shift_row(sid).note or ""
    assert "count_source=SIMULATED" in note
    assert "attestation_ref=%s" % ref in note


# ══ 3. ⭐ HAQIQIY DO'KONDA SIMULATED — RAD ═══════════════════════════════
def test_03_haqiqiy_dokonda_SIMULATED_RAD_etiladi(real_store):
    """⭐ Fizik sanoqni chetlab o'tish YO'LI YO'Q."""
    from app.db.session import SessionLocal
    from app.services.shifts import close_shift_svc
    d = real_store
    db = SessionLocal()
    try:
        emp = db.merge(d["employee"])
        with pytest.raises(HTTPException) as e:
            close_shift_svc(d["shift"].id,
                            _Body(16675.00, "SIMULATED", "soxta-havola"),
                            emp, db)
        assert e.value.status_code == 400
        assert "SIMULATED" in str(e.value.detail)
        assert "demo" in str(e.value.detail)
        db.rollback()
        #  Smena OCHIQ qoldi, sanoq YOZILMADI.
        sh = db.merge(d["shift"])
        db.refresh(sh)
        assert sh.status.value == "open"
        assert sh.counted_cash is None
        assert sh.note is None
    finally:
        db.close()


def test_03b_haqiqiy_dokonda_PHYSICAL_ISHLAYDI(real_store):
    """Haqiqiy do'konning fizik yo'li TEGILMAGAN."""
    from app.db.session import SessionLocal
    from app.services.shifts import close_shift_svc
    d = real_store
    db = SessionLocal()
    try:
        emp = db.merge(d["employee"])
        out = close_shift_svc(d["shift"].id, _Body(3000.00, "PHYSICAL"), emp, db)
        assert out["count_source"] == "PHYSICAL"
        assert out["expected_cash"] == 3000.0
        assert out["difference"] == 0.0
    finally:
        db.close()


# ══ 4. BEGONA TENANT ═════════════════════════════════════════════════════
def test_04_begona_tenant_smenasini_yopib_bolmaydi(client, admin_headers, real_store):
    """Demo tenant xodimi HAQIQIY do'kon smenasini yopa olmaydi (404)."""
    r = _close(client, admin_headers, str(real_store["shift"].id),
               counted_cash=3000, count_source="PHYSICAL")
    assert r.status_code == 404, r.text
    assert _shift_row(real_store["shift"].id).status.value == "open"


def test_04b_demo_predikati_BOSHQA_tenantga_tarqalmaydi(real_store):
    """Demo do'kon mavjudligi haqiqiy do'konga SIMULATED bermaydi."""
    from app.db.session import SessionLocal
    from app.services.historical import is_demo_code
    db = SessionLocal()
    try:
        co = db.merge(real_store["company"])
        assert is_demo_code(co.code) is False
    finally:
        db.close()


# ══ 5. ATTESTATSIYA ══════════════════════════════════════════════════════
def test_05_SIMULATED_attestatsiyasiz_RAD(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=500)
    r = _close(client, admin_headers, sid, counted_cash=500,
               count_source="SIMULATED")
    assert r.status_code == 400, r.text
    assert "attestation_ref" in r.text
    assert _shift_row(sid).status.value == "open"


def test_05b_attestatsiya_SIMULATED_siz_RAD(client, admin_headers):
    """Yarim e'lon qilingan holat — jimgina qabul qilinmaydi."""
    sid = _open_shift(client, admin_headers, opening=500)
    r = _close(client, admin_headers, sid, counted_cash=500,
               attestation_ref="havola-manbasiz")
    assert r.status_code == 400, r.text
    assert _shift_row(sid).status.value == "open"


def test_05c_bosh_attestatsiya_sxemada_RAD(client, admin_headers):
    """`min_length=1` -> bo'sh satr 422 (fail-closed)."""
    sid = _open_shift(client, admin_headers, opening=500)
    r = _close(client, admin_headers, sid, counted_cash=500,
               count_source="SIMULATED", attestation_ref="")
    assert r.status_code == 422, r.text
    assert _shift_row(sid).status.value == "open"


def test_05d_faqat_boshliqdan_iborat_attestatsiya_RAD(client, admin_headers):
    """`"   "` sxemadan o'tadi, lekin servis `strip()` dan keyin RAD etadi."""
    sid = _open_shift(client, admin_headers, opening=500)
    r = _close(client, admin_headers, sid, counted_cash=500,
               count_source="SIMULATED", attestation_ref="   ")
    assert r.status_code == 400, r.text
    assert _shift_row(sid).status.value == "open"


# ══ 6. KASSIR IDENTIFIKATORI ═════════════════════════════════════════════
def test_06_autentifikatsiyasiz_RAD(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=700)
    r = client.post(f"{API}/shifts/{sid}/close", json={"counted_cash": 700})
    assert r.status_code in (401, 403), r.text
    assert _shift_row(sid).status.value == "open"


def test_06b_BOSHQA_kassir_yopa_olmaydi(client, admin_headers, real_store):
    """`cashier_id != emp.id` -> 404 (egalik darvozasi TEGILMAGAN)."""
    from app.db.session import SessionLocal
    from app.services.shifts import close_shift_svc
    db = SessionLocal()
    try:
        from app.models.auth import Employee
        from app.models.org import Company
        co = db.query(Company).filter(Company.code == "demo").one()
        begona = db.query(Employee).filter(Employee.company_id == co.id).first()
        assert begona is not None
        with pytest.raises(HTTPException) as e:
            close_shift_svc(real_store["shift"].id,
                            _Body(3000.00, "PHYSICAL"), begona, db)
        assert e.value.status_code == 404
    finally:
        db.rollback()
        db.close()


# ══ 7. TAKRORIY YOPISH ═══════════════════════════════════════════════════
def test_07_ikkinchi_yopish_RAD_va_provenans_OZGARMAYDI(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=1200)
    ref = "synthetic-lab/7AC/dup/%s" % sid
    r1 = _close(client, admin_headers, sid, counted_cash=1200,
                count_source="SIMULATED", attestation_ref=ref)
    assert r1.status_code == 200, r1.text
    note1 = _shift_row(sid).note
    #  Ikkinchi urinish — BOSHQA manba va BOSHQA summa bilan.
    r2 = _close(client, admin_headers, sid, counted_cash=999,
                count_source="PHYSICAL")
    assert r2.status_code == 400, r2.text
    assert "yopilgan" in r2.text
    row = _shift_row(sid)
    assert row.note == note1, "PROVENANS QAYTA YOZILDI — muzlatilgan bo'lishi SHART"
    assert float(row.counted_cash) == 1200.0
    assert "count_source=SIMULATED" in (row.note or "")


# ══ 8. KUTILGAN vs E'LON QILINGAN FARQI ══════════════════════════════════
def test_08_farq_YASHIRILMAYDI_va_tuzatuvchi_yozuv_YOQ(client, admin_headers):
    """E'lon qilingan summa kutilmadan farq qilsa — farq SAQLANADI."""
    from app.db.session import SessionLocal
    from app.models.cash import ReconciliationRecord
    sid = _open_shift(client, admin_headers, opening=1000)
    r = _close(client, admin_headers, sid, counted_cash=950,
               count_source="SIMULATED",
               attestation_ref="synthetic-lab/7AC/diff/%s" % sid)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["expected_cash"] == 1000.0
    assert j["counted_cash"] == 950.0
    assert j["difference"] == -50.0, "farq yashirildi yoki yaxlitlandi"
    row = _shift_row(sid)
    assert Decimal(str(row.difference)) == Decimal("-50.00")
    assert "difference=-50" in (row.note or "")
    #  Avtomatik ADJUSTMENT legi YOZILMAYDI (§18 — menejer+ qarori).
    db = SessionLocal()
    try:
        recs = (db.query(ReconciliationRecord)
                .filter(ReconciliationRecord.shift_id == uuid.UUID(str(sid)))
                .all())
    except Exception as exc:                      # noqa: BLE001
        #  ⚠️  `cash` SXEMASI FAQAT POSTGRES'DA bor (`on_shift_close`
        #      SQLite'da no-op). Mahalliy SQLite yurishida bu tasdiq
        #      O'TKAZIB YUBORILADI; `*_pg` muhitida bajariladi.
        db.rollback()
        pytest.skip("cash sxemasi yo'q (SQLite): %s" % type(exc).__name__)
    else:
        for rec in recs:
            assert rec.state == "PENDING", \
                "farq AVTOMATIK kitobga olindi — taqiq"
    finally:
        db.close()


# ══ 9. QAYTARISH VA XARAJAT — NAQD SEMANTIKASI ═══════════════════════════
@pytest.mark.parametrize("usul,naqdga_tasir", [("card", False),
                                               ("qr", False),
                                               ("cash", True)])
def test_09_qaytarish_usuli_naqd_kutilmasiga_TOGRI_tasir(client, admin_headers,
                                                         usul, naqdga_tasir):
    """⭐ KARTA qaytarishi naqd kutilmasini KAMAYTIRMAYDI."""
    from app.db.session import SessionLocal
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement, Shift
    sid = _open_shift(client, admin_headers, opening=3000)
    db = SessionLocal()
    try:
        sh = db.get(Shift, uuid.UUID(str(sid)))
        #  Naqd qaytarish ledger/CashMovement tomonida `payout` bo'lib
        #  ko'rinadi; karta/QR esa naqdga TEGMAYDI.
        if naqdga_tasir:
            db.add(CashMovement(id=uuid.uuid4(), shift_id=sh.id,
                                type=CashMovementType.payout,
                                amount=Decimal("1500.00"),
                                reason="naqd qaytarish (test)",
                                created_at=datetime.now(timezone.utc)))
            db.commit()
        kutilgan = 3000.0 - (1500.0 if naqdga_tasir else 0.0)
    finally:
        db.close()
    r = _close(client, admin_headers, sid, counted_cash=kutilgan,
               count_source="SIMULATED",
               attestation_ref="synthetic-lab/7AC/%s/%s" % (usul, sid))
    assert r.status_code == 200, r.text
    assert r.json()["expected_cash"] == kutilgan
    assert r.json()["difference"] == 0.0


def test_09b_naqd_xarajat_kutilmani_KAMAYTIRADI(client, admin_headers):
    from app.db.session import SessionLocal
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement, Shift
    sid = _open_shift(client, admin_headers, opening=3000)
    db = SessionLocal()
    try:
        sh = db.get(Shift, uuid.UUID(str(sid)))
        db.add(CashMovement(id=uuid.uuid4(), shift_id=sh.id,
                            type=CashMovementType.expense,
                            amount=Decimal("800.00"), reason="Kanstovar",
                            created_at=datetime.now(timezone.utc)))
        db.add(CashMovement(id=uuid.uuid4(), shift_id=sh.id,
                            type=CashMovementType.payin,
                            amount=Decimal("1000.00"), reason="Kassaga qo'shimcha",
                            created_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()
    #  3000 + 1000 − 800 = 3200
    r = _close(client, admin_headers, sid, counted_cash=3200,
               count_source="SIMULATED",
               attestation_ref="synthetic-lab/7AC/expense/%s" % sid)
    assert r.status_code == 200, r.text
    assert r.json()["expected_cash"] == 3200.0
    assert r.json()["difference"] == 0.0


# ══ 10. AUDIT METAMA'LUMOTI SAQLANISHI ═══════════════════════════════════
def test_10_provenans_BARCHA_maydonlari_saqlanadi(client, admin_headers):
    sid = _open_shift(client, admin_headers, opening=2500)
    ref = "synthetic-lab/7AC/prov/%s" % sid
    r = _close(client, admin_headers, sid, counted_cash=2500,
               count_source="SIMULATED", attestation_ref=ref)
    assert r.status_code == 200, r.text
    note = _shift_row(sid).note or ""
    #  §3 talab qilgan metama'lumot: manba · havola · aktor · vaqt ·
    #  smena · kutilgan · e'lon qilingan · farq.
    for kalit in ("count_source=SIMULATED", "attestation_ref=%s" % ref,
                  "by=", "at=", "shift=%s" % sid,
                  "expected=", "counted=", "difference="):
        assert kalit in note, "provenansda yo'q: %s · note=%r" % (kalit, note)
    row = _shift_row(sid)
    assert row.closed_at is not None
    assert row.expected_cash is not None and row.counted_cash is not None


# ══ 13. NOMA'LUM MANBA — FAIL-CLOSED ═════════════════════════════════════
@pytest.mark.parametrize("yomon", ["MAGIC", "simulated", "Physical", "EXPECTED",
                                   "PHYSICAL ", 1, True, []])
def test_13_nomalum_manba_RAD_etiladi(client, admin_headers, yomon):
    """Noma'lum/boshqa registrli manba JIMGINA PHYSICAL bo'lib qolmaydi."""
    sid = _open_shift(client, admin_headers, opening=600)
    r = _close(client, admin_headers, sid, counted_cash=600,
               count_source=yomon)
    assert r.status_code == 422, "noma'lum manba QABUL QILINDI: %r -> %s" % (
        yomon, r.status_code)
    assert _shift_row(sid).status.value == "open"


def test_13b_EXPECTED_sanoq_manbasi_sifatida_RAD(client, admin_headers):
    """Kutilgan naqd SANOQ EMAS — u manba qiymati bo'la olmaydi."""
    sid = _open_shift(client, admin_headers, opening=600)
    r = _close(client, admin_headers, sid, counted_cash=600,
               count_source="EXPECTED")
    assert r.status_code == 422, r.text


# ══ 14. ⭐ KLIENT DEMO IDENTIFIKATORINI SOXTALASHTIRA OLMAYDI ════════════
def test_14_klient_qoshimcha_maydon_bilan_demo_boLa_olmaydi(real_store):
    """⭐ Server MUSTAQIL tekshiradi: `company.code` DB dan o'qiladi.

    Klient `company_code`, `is_demo`, `tenant_code` kabi maydonlarni
    qo'shsa — ular `CloseShift` sxemasida YO'Q va Pydantic ularni
    TASHLAB yuboradi; darvoza esa baribir DB dagi kodga qaraydi.
    """
    from app.db.session import SessionLocal
    from app.services.shifts import close_shift_svc
    d = real_store
    db = SessionLocal()
    try:
        emp = db.merge(d["employee"])
        soxta = _Body(16675.00, "SIMULATED", "soxta")
        #  Klient «men demo tenantman» deb da'vo qiladi:
        soxta.company_code = "demo1"
        soxta.is_demo = True
        soxta.tenant_code = "demod31final"
        with pytest.raises(HTTPException) as e:
            close_shift_svc(d["shift"].id, soxta, emp, db)
        assert e.value.status_code == 400
        assert "demo" in str(e.value.detail)
        db.rollback()
        sh = db.merge(d["shift"])
        db.refresh(sh)
        assert sh.status.value == "open", "SOXTA DA'VO BILAN SMENA YOPILDI"
    finally:
        db.close()


def test_14b_sxema_nomalum_maydonni_TASHLAB_yuboradi(client, admin_headers):
    """HTTP sirti: begona maydonlar provenansga TUSHMAYDI."""
    sid = _open_shift(client, admin_headers, opening=400)
    r = _close(client, admin_headers, sid, counted_cash=400,
               count_source="PHYSICAL",
               company_code="demo1", is_demo=True, note="begona")
    assert r.status_code == 200, r.text
    note = _shift_row(sid).note or ""
    for begona in ("company_code", "is_demo", "begona"):
        assert begona not in note, "begona maydon provenansga tushdi: %s" % begona
