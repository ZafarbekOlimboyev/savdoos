# -*- coding: utf-8 -*-
"""DEMO-TARIX YAKUNLASH — BAXTLI YO'L (FAQAT real PostgreSQL).

NEGA FAQAT SHU YERDA
====================
Ega buyurgan darvoza `shadow_compare.compare_tenant(..., t0=None) == MATCH`
ga tayanadi, ya'ni LEDGER tomoni MAVJUD bo'lishi kerak. Naqd quyi tizimi
(`cash` sxemasi) ATAYLAB faqat Postgres'da bor, shu bois SQLite to'plamida bu
yo'lni O'LCHAB BO'LMAYDI — u yerda marshrut fail-closed 503 beradi
(`tests/test_demo_history_routes.py::test_K_...`).

QURILISH REJASINING SHAKLI ATAYLAB TANLANGAN — o'lchangan uch tuzoqdan qochadi:
  1. `opening_cash = 0`. Legacy tomoni HAR BIR smenaning `opening_cash` ini
     qo'shadi, ledger esa ochilish legini FAQAT hisob qoldig'iga nisbatan
     MUSBAT delta uchun yozadi. Naqd qoldirib ketadigan ko'p-smenali reja
     har qo'shimcha smenada aynan `opening_cash` miqdorida delta berardi.
  2. Hodisalar AYNI aktor bilan `shift_open -> naqd amal -> shift_close`
     tartibida. Custody `actor_open_shift` orqali aniqlanadi va u VAQTNI
     BILMAYDI (faqat `status == open`) — smenalar yopilgandan keyin naqd
     hujjat yuborilsa, u ledger-only shoxga tushardi.
  3. Naqd AVVAL kiradi. Har OUT legi hisob qoldig'i yetmasa
     `INSUFFICIENT_CASH` bilan rad etiladi.

A  baxtli yo'l: qurilish -> hodisalar -> MATCH -> finalize -> T0
B  finalize IDEMPOTENT (ayni T0 -> duplicate, yon ta'sir YO'Q)
C  finalize'dan KEYIN tarixiy replay -> 409 (NC8), 12 turning HAMMASI
D  finalize'dan KEYIN enforcement YONADI (NC9)
E  TILL YO'Q bo'lsa paritet TASDIQLANMAYDI (jim no-op fail-closed ushlanadi)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.services.cash import tenant as _t

TZ = "Asia/Bishkek"
#: Tarixiy chuqurlik: `/sync/push` ning 60 kunlik oynasidan ham NARIDA.
DEPTH = 200


def _aw(dt):
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture()
def jdb_pg(cashenv, monkeypatch):
    """Jurnal ALOHIDA sessiya ishlatadi (`historical_exec.SessionLocal`).

    ⚠️  `tests/cash/conftest.py` O'Z engine'ini quradi va ilovaning
        `SessionLocal` ini QAYTA BOG'LAMAYDI. Patch qilinmasa jurnal qatorlari
        SQLite'ga, biznes qatorlari esa Postgres'ga tushardi — `finalize` esa
        jurnalni Postgres sessiyasida o'qib 0 qator ko'rardi.
    """
    SL = sessionmaker(bind=cashenv.engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.api.v1.historical_exec.SessionLocal", SL)
    return SL


#: Tarixiy aktor uchun SHART bo'lgan ruxsat (`historical_exec.ACTOR_PERMISSIONS`).
#  ⚠️  Gard `effective_permissions` bilan ishlaydi va FULL_ACCESS_ROLES uchun
#      qisqa tutashuv QILMAYDI — shu bois rolga ruxsat AYNAN berilishi kerak.
#      Bu fikstura ishi: `Base.metadata.create_all` `initdb` ning rol
#      urug'lantirishini ishlatmaydi, shu bois PG bazasida `ega` roli BO'SH.
def _ega_roli(db):
    from app.models.auth import Permission, Role, RolePermission
    r = db.query(Role).filter(Role.code == "ega").first()
    if r is None:
        r = Role(id=uuid.uuid4(), code="ega", name="Ega")
        db.add(r)
        db.flush()
    p = db.query(Permission).filter(Permission.code == "kassa.sell").first()
    if p is None:
        p = Permission(id=uuid.uuid4(), code="kassa.sell", module="kassa")
        db.add(p)
        db.flush()
    bogh = (db.query(RolePermission)
            .filter(RolePermission.role_id == r.id,
                    RolePermission.permission_id == p.id).first())
    if bogh is None:
        db.add(RolePermission(role_id=r.id, permission_id=p.id))
        db.flush()
    return r


def _qurilish_tenanti(db, *, till=True):
    """Tenant FAQAT kanonik marshrut funksiyasi orqali yaratiladi."""
    from app.api.v1.admin import DemoHistoryProvisionIn, demo_history_provision
    from app.models.cash import CashAccount
    from app.services.cash import till_identity as _ti
    _ega_roli(db)
    db.commit()
    kod = f"demo{uuid.uuid4().hex[:10]}"
    data = DemoHistoryProvisionIn(
        company_name="Demo tarix PG", company_code=kod, owner_name="Ega",
        owner_phone=f"+9967{uuid.uuid4().int % 10**8:08d}",
        owner_password="Zt7#mvQ2pLx9", currency="KGS", timezone=TZ,
        plan_id="plan-" + uuid.uuid4().hex[:6])
    out = demo_history_provision(data, True, db)
    assert out["historical_build"] is True
    cid = uuid.UUID(out["company_id"])
    brid = uuid.UUID(out["branch_id"])
    #  Darvozaning asosiy invarianti — ikkisi ham YO'Q.
    cfg = _t.cash_config(db, cid)
    assert "ledger_native" not in cfg and "cutover_at" not in cfg, cfg

    acc = None
    if till:
        #  AYNAN BITTA ACTIVE TILL: `resolve_till` >1 TILL uchun terminal
        #  mosligisiz None qaytaradi va naqd hook'lari JIM no-op bo'lardi.
        acc = CashAccount(id=uuid.uuid4(), tenant_id=cid, branch_id=brid, type="TILL",
                          currency="KGS", status="ACTIVE",
                          label=_ti.till_label(f"TILL-{uuid.uuid4().hex[:4]}", None),
                          created_at=datetime.now(timezone.utc) - timedelta(days=DEPTH + 10))
        db.add(acc)
    db.commit()
    return {"cid": cid, "brid": brid, "eid": uuid.UUID(out["owner_id"]),
            "kod": kod, "till": acc, "plan": "pl-" + uuid.uuid4().hex[:8]}


def _hodisa(db, s, *, event_type, payload, seq, at, plan_start=False):
    from app.api.v1.historical_exec import HistoricalEventIn, historical_event
    body = HistoricalEventIn(**{
        "company_id": str(s["cid"]), "branch_id": str(s["brid"]),
        "actor_employee_id": str(s["eid"]), "plan_id": s["plan"],
        "plan_start": plan_start, "occurred_at": at.isoformat(), "event_seq": seq,
        "event": {"event_type": event_type, "payload": payload}})
    return historical_event(body, True, db)


def _reja(db, s, *, payin=5000):
    """shift_open(0) -> cash_payin -> shift_close. Ikki tomon ham simmetrik."""
    kun = (datetime.now(timezone.utc) - timedelta(days=DEPTH)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    t_open = kun + timedelta(hours=9)
    t_pay = kun + timedelta(hours=12)
    t_close = kun + timedelta(hours=18)

    o = _hodisa(db, s, event_type="shift_open", payload={"opening_cash": 0},
                seq=["d1", "open"], at=t_open, plan_start=True)
    assert o["ok"] is True, o
    p = _hodisa(db, s, event_type="cash_payin",
                payload={"type": "payin", "amount": payin, "reason": "demo kirim"},
                seq=["d1", "payin"], at=t_pay)
    assert p["ok"] is True, p
    c = _hodisa(db, s, event_type="shift_close",
                payload={"shift_id": o["result_id"], "counted_cash": payin},
                seq=["d1", "close"], at=t_close)
    assert c["ok"] is True, c
    db.commit()
    return {"t_open": t_open, "t_pay": t_pay, "t_close": t_close,
            "oxirgi": t_close, "shift_id": o["result_id"]}


def _finalize(db, cid, ref="PG-ATTEST-1"):
    from app.api.v1.admin import DemoHistoryFinalizeIn, demo_history_finalize
    return demo_history_finalize(str(cid), DemoHistoryFinalizeIn(attestation_ref=ref),
                                 True, db)


def _dual(db):
    from app.services.cash import retrofit as _cr
    return _cr.dual_write_enabled(db)


# ═══ A) baxtli yo'l ════════════════════════════════════════════════════════
def test_A_baxtli_yol_MATCH_va_T0(db, cashenv, jdb_pg):
    from app.services.cash import cutover as _cut
    from app.services.cash import shadow_compare as _sc
    if not _dual(db):
        pytest.skip("dual-write o'chiq (cash sxemasi yo'q) — paritet o'lchanmaydi")

    s = _qurilish_tenanti(db)
    r = _reja(db, s)

    #  PARITET: ikki tomon ham HARAKATLANGAN va teng.
    rep = _sc.compare_tenant(db, s["cid"], t0=None)
    ok, sabab = _sc.finalize_parity_verdict(rep)
    assert ok is True, f"{sabab} | {rep}"
    assert float(rep["legacy_in"]) > 0 and float(rep["ledger_in"]) > 0, rep
    assert rep["status"] == "MATCH", rep

    out = _finalize(db, s["cid"])
    assert out["ok"] is True and out["finalized"] is True
    assert out["duplicate"] is False
    assert out["events"] == 3, out

    #  T0 = oxirgi tarixiy lahza + 1 mikrosekund, QAT'IY keyin va `<= now`.
    t0 = _cut.cutover_at(db, s["cid"])
    assert t0 is not None
    assert t0 == _aw(r["oxirgi"]) + timedelta(microseconds=1), (t0, r["oxirgi"])
    assert t0 > _aw(r["oxirgi"]), "T0 oxirgi tarixiy qatorni LIVE deb tasniflardi"
    assert t0 <= datetime.now(timezone.utc)

    #  HOLAT: uchinchi shakl -> fresh kontrakt.
    cfg = _t.cash_config(db, s["cid"])
    assert cfg["ledger_native"] is True
    assert "historical_build" not in cfg
    assert cfg["onboarded_at"] and cfg["historical_build_finalized_at"]
    assert _t.is_historical_build(db, s["cid"]) is False


# ═══ B) idempotentlik ══════════════════════════════════════════════════════
def test_B_finalize_IDEMPOTENT(db, cashenv, jdb_pg):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    s = _qurilish_tenanti(db)
    _reja(db, s)
    birinchi = _finalize(db, s["cid"])
    oldin = dict(_t.cash_config(db, s["cid"]))

    ikkinchi = _finalize(db, s["cid"])
    assert ikkinchi["duplicate"] is True, ikkinchi
    assert ikkinchi["cutover_at"] == birinchi["cutover_at"]
    #  YON TA'SIR YO'Q: `finalized_at` ham o'zgarmaydi.
    assert _t.cash_config(db, s["cid"]) == oldin


# ═══ C) NC8 — yuza O'ZI yopiladi ═══════════════════════════════════════════
def test_C_NC8_finalizedan_keyin_tarixiy_replay_409(db, cashenv, jdb_pg):
    from fastapi import HTTPException
    from app.api.v1.historical_exec import EVENT_TYPES
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    s = _qurilish_tenanti(db)
    r = _reja(db, s)
    _finalize(db, s["cid"])

    #  (1) ALLAQACHON BAJARILGAN kalitni replay — `duplicate: true` EMAS, 409:
    #      darvoza jurnal rezervatsiyasidan OLDIN turadi.
    with pytest.raises(HTTPException) as ei:
        _hodisa(db, s, event_type="shift_open", payload={"opening_cash": 0},
                seq=["d1", "open"], at=r["t_open"], plan_start=True)
    assert ei.value.status_code == 409
    assert "T0" in ei.value.detail

    #  (2) 12 TURNING HAMMASI — bitta ham yo'l topmasin.
    namuna = {
        "shift_open": {"opening_cash": 0},
        "shift_close": {"shift_id": r["shift_id"], "counted_cash": 0},
        "sale": {"items": [], "payments": []},
        "purchase": {},
        "receiving": {},
        "return": {},
        "inventory_count": {},
        "writeoff": {},
        "cash_payin": {"type": "payin", "amount": 1},
        "cash_expense": {"type": "expense", "amount": 1},
        "customer_debt_payment": {"customer_id": str(uuid.uuid4()), "amount": 1},
        "supplier_payment": {"supplier_id": str(uuid.uuid4()), "amount": 1},
    }
    assert set(namuna) == set(EVENT_TYPES), "hodisa turlari ro'yxati ajralib ketdi"
    for et in EVENT_TYPES:
        try:
            _hodisa(db, s, event_type=et, payload=namuna[et],
                    seq=["after", et], at=r["t_pay"])
        except HTTPException as e:
            #  409 = T0 darvozasi. 422 ham qabul (DTO tanani rad etdi) EMAS:
            #  darvoza DTO'dan KEYIN, lekin yozuvchidan OLDIN turishi kerak.
            assert e.status_code == 409, f"{et}: {e.status_code} {e.detail}"
            assert "T0" in str(e.detail), f"{et}: {e.detail}"
        except Exception as e:                                  # noqa: BLE001
            #  Pydantic validatsiyasi — darvozaga yetmasdan rad etilgan tana.
            #  Bu ham YOZUV YO'Q degani, lekin aniq ajratib qo'yamiz.
            assert "validation" in type(e).__name__.lower(), f"{et}: {type(e).__name__} {e}"
        else:
            pytest.fail(f"{et}: finalize'dan keyin hodisa O'TDI")


# ═══ D) NC9 — enforcement yonadi ═══════════════════════════════════════════
def test_D_NC9_finalizedan_keyin_enforcement_YONADI(db, cashenv, jdb_pg):
    from app.services.cash import cutover_guard as _cg
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    s = _qurilish_tenanti(db)

    assert _cg.enforcement_active(db, s["cid"]) is False
    assert _t.is_ledger_native(db, s["cid"]) is False
    assert _t.is_historical_build(db, s["cid"]) is True

    _reja(db, s)
    _finalize(db, s["cid"])

    assert _cg.enforcement_active(db, s["cid"]) is True
    assert _t.is_ledger_native(db, s["cid"]) is True
    assert _t.is_ledger_authoritative(db, s["cid"]) is True
    assert _t.is_historical_build(db, s["cid"]) is False


# ═══ E) TILL yo'q — jim no-op FAIL-CLOSED ushlanadi ════════════════════════
def test_E_TILL_YOQ_bolsa_paritet_TASDIQLANMAYDI(db, cashenv, jdb_pg):
    """`on_shift_open`/`_cash_op_once` TILL aniqlanmasa JIM `None` qaytaradi.

    Ya'ni legacy tomoni harakatlanadi, ledger tomoni BO'SH qoladi — va bu
    xato KO'TARMAYDI. Darvoza aynan shu jim holatni ushlashi SHART.
    """
    from fastapi import HTTPException
    from app.services.cash import shadow_compare as _sc
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    s = _qurilish_tenanti(db, till=False)
    _reja(db, s)

    rep = _sc.compare_tenant(db, s["cid"], t0=None)
    ok, sabab = _sc.finalize_parity_verdict(rep)
    assert ok is False, f"TILL'siz reja paritetdan O'TDI: {rep}"

    with pytest.raises(HTTPException) as ei:
        _finalize(db, s["cid"])
    assert ei.value.status_code == 409
    assert "paritet" in ei.value.detail.lower(), ei.value.detail
    #  Holat O'ZGARMADI.
    cfg = _t.cash_config(db, s["cid"])
    assert cfg.get("historical_build") is True
    assert "cutover_at" not in cfg
