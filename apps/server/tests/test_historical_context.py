# -*- coding: utf-8 -*-
"""H1 — TARIXIY BAJARISH KONTEKSTI: darvoza, bo'g'ish, idempotentlik.

Isbotlanadi:
  1. POLYARLIK — kontekst YO'Q bo'lsa hech narsa o'zgarmaydi (bo'g'ish O'CHIQ,
     tarixiy ruxsat YO'Q). Oddiy POS so'rovida bu kod yo'li yonmaydi.
  2. DARVOZA — to'rt shart: do'kon bor · kod `test`/`demo` · (talab bo'lsa)
     savdo YO'Q · `cash` T0 BELGILANMAGAN.
  3. BAYT-AYNAN QAYTA ISHLATISH — `is_demo_code` mavjud `admin.py` darvozasining
     predikati bilan AYNI, ya'ni darvoza «tozalash» niyatida BO'SHATILMAGAN.
  4. BO'G'ISH — tarixiy kontekst ichida FCM push YUBORILMAYDI, tashqarisida
     YUBORILADI (negativ nazorat bilan).
  5. SO'ROV-DOIRALILIK — parallel oqimlar bir-birining kontekstini KO'RMAYDI.
  6. OQMASLIK — kontekst ichida xato chiqsa ham bayroq tiklanadi.
  7. IDEMPOTENTLIK — kalit deterministik, REJA va DO'KON bo'yicha ajralgan.

⚠️  H1 BIRORTA YOZUVCHIGA `at=` QO'SHMAYDI (bu H2 ishi). Shu bois bu fayl
    yozuvchilarni emas, POYDEVORNI o'lchaydi.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services import historical as H

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _company(code: str):
    """Do'kon (faqat kod muhim) — to'g'ridan bazada."""
    from app.models.org import Company
    with _db() as db:
        c = Company(id=uuid.uuid4(), name=f"H1 {code}", code=code, currency="UZS")
        db.add(c)
        db.commit()
        return c.id, code


def _get(cid):
    from app.models.org import Company
    with _db() as db:
        return db.get(Company, cid)


def _set_t0(cid, when: datetime | None):
    """`Setting(key='cash').cutover_at` ni o'rnatadi/olib tashlaydi."""
    from app.models.settings import Setting
    with _db() as db:
        row = (db.query(Setting)
               .filter(Setting.company_id == cid, Setting.key == "cash",
                       Setting.branch_id.is_(None)).first())
        if row is None:
            row = Setting(id=uuid.uuid4(), company_id=cid, branch_id=None, key="cash", value={})
            db.add(row)
        val = dict(row.value or {})
        if when is None:
            val.pop("cutover_at", None)
        else:
            val["cutover_at"] = when.isoformat()
        row.value = val
        db.commit()


# ══ 1) POLYARLIK ════════════════════════════════════════════════════════════
def test_kontekstsiz_HECH_NARSA_ozgarmaydi():
    """⚠️  FAIL-CLOSED: kontekst yo'qligi HECH QACHON ruxsat bermasin.

    Oddiy POS so'rovida `active()` None, `suppress_external()` False — ya'ni
    birorta bildirishnoma yo'qolmaydi va tarixiy ruxsat paydo bo'lmaydi.
    """
    assert H.active() is None
    assert H.instant() is None
    assert H.suppress_external() is False
    with pytest.raises(RuntimeError):
        H.require_active()


# ══ 2) DARVOZA ══════════════════════════════════════════════════════════════
def test_darvoza_HAQIQIY_dokonni_RAD_etadi(client):
    cid, _ = _company("fayzan-h1-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            H.assert_demo_tenant(db, _get(cid), require_empty_history=False)
    assert e.value.status_code == 400
    assert "test" in e.value.detail and "demo" in e.value.detail


def test_darvoza_DEMO_dokonni_OTKAZADI(client):
    cid, _ = _company("demo-h1-" + uuid.uuid4().hex[:6])
    with _db() as db:
        H.assert_demo_tenant(db, _get(cid), require_empty_history=True)   # otmaydi


def test_darvoza_T0_BELGILANGAN_dokonni_RAD_etadi(client):
    """⚠️  EGA TALABI: `cutover_at IS NULL` — boshlang'ich shart.

    T0 belgilangan tenantda yopilgan tarixiy smenaga naqd yozish ATAYLAB
    taqiqlangan (`services/sales.py:429-431`). Biz o'sha qarorni CHETLAB
    O'TMAYMIZ — T0 qo'yilmagan tenantni TALAB qilamiz.
    """
    cid, _ = _company("demo-t0-" + uuid.uuid4().hex[:6])
    _set_t0(cid, NOW - timedelta(days=30))
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            H.assert_demo_tenant(db, _get(cid), require_empty_history=False)
    assert e.value.status_code == 409
    assert "T0" in e.value.detail
    # T0 olib tashlansa — o'tadi (shart AYNAN T0 ga bog'liq, boshqa narsaga emas)
    _set_t0(cid, None)
    with _db() as db:
        H.assert_demo_tenant(db, _get(cid), require_empty_history=False)


def test_darvoza_ochirilgan_dokon_404(client):
    from app.models.org import Company
    cid, _ = _company("demo-del-" + uuid.uuid4().hex[:6])
    with _db() as db:
        db.get(Company, cid).deleted_at = NOW
        db.commit()
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            H.assert_demo_tenant(db, _get(cid), require_empty_history=False)
    assert e.value.status_code == 404


# ══ 3) BAYT-AYNAN QAYTA ISHLATISH ═══════════════════════════════════════════
@pytest.mark.parametrize("code, kutilgan", [
    ("test", True), ("test1", True), ("testing", True),
    ("demo", True), ("demo-x", True), ("DEMO-X", True), ("Test-A", True),
    ("fayzan1", False), ("", False), (None, False),
    (" test1", False),      # ⚠️  BO'SHLIQ KESILMAYDI — qarang pastdagi test
    ("atest", False), ("xdemo", False),
])
def test_is_demo_code_predikati(code, kutilgan):
    assert H.is_demo_code(code) is kutilgan


def test_is_demo_code_MAVJUD_darvoza_bilan_AYNI():
    """⚠️  DARVOZA BO'SHATILMAGANINI qadaydi.

    `api/v1/admin.py` ilgari INLINE qilardi:
        `code = (c.code or "").lower()`
        `if not (code.startswith("test") or code.startswith("demo")): 400`
    Predikatni umumiylashtirganda `strip()` qo'shish TABIIY ko'rinadi — lekin u
    darvozani BO'SHATARDI: `" test1"` asl darvozada RAD etiladi. Shu bois bu
    yerda ASL ifoda qayta hisoblanadi va ikkisi SOLISHTIRILADI.
    """
    def asl(code):                                   # asl inline predikat, AYNAN
        c = (code or "").lower()
        return c.startswith("test") or c.startswith("demo")

    for code in ["test", "test1", "demo", "demo-x", "DEMO", "Test-A", "fayzan1",
                 "", None, " test1", "  demo", "atest", "xdemo", "tes", "dem"]:
        assert H.is_demo_code(code) is asl(code), f"predikat AJRALDI: {code!r}"


# ══ 4) TASHQI EFFEKTLARNI BO'G'ISH (negativ nazorat bilan) ══════════════════
def _fcm_sahna(cid, monkeypatch):
    """FCM yuborishni KUZATADIGAN sahna: token bor, kalit bor, `send_ex` sanaladi."""
    from app.models.devices import DeviceToken
    from app.services import push
    with _db() as db:
        db.add(DeviceToken(id=uuid.uuid4(), company_id=cid,
                           token="tok-" + uuid.uuid4().hex, platform="android"))
        db.commit()

    yuborildi: list = []

    def _fake_send_ex(tokens, title, body, data=None):
        yuborildi.append((tuple(tokens), title, body))
        return len(tokens), []

    monkeypatch.setattr(push, "send_ex", _fake_send_ex)

    class _S:                                   # `fcm_enabled` YONIQ bo'lsin
        fcm_enabled = True
    monkeypatch.setattr(push, "settings", _S())
    return yuborildi


def test_FCM_kontekst_TASHQARISIDA_YUBORILADI(client, monkeypatch):
    """NEGATIV NAZORAT: bo'g'ish bo'lmasa push HAQIQATAN ketadi.

    Bu test bo'lmasa, keyingi test «bo'g'ildi» deb YOLG'ON ishontirardi —
    push umuman ketmaydigan sahnada ham yashil bo'lardi.
    """
    cid, _ = _company("demo-fcm1-" + uuid.uuid4().hex[:6])
    yuborildi = _fcm_sahna(cid, monkeypatch)
    from app.services import push
    with _db() as db:
        push.notify_low_stock(db, cid, [("Non", 2)], branch_name="F01")
    assert len(yuborildi) == 1, "nazorat sahnasi push yubormadi — test o'lchamaydi"


def test_FCM_kontekst_ICHIDA_BO_GILADI(client, monkeypatch):
    """Tarixiy kontekst ichida AYNI chaqiruv push YUBORMAYDI."""
    cid, _ = _company("demo-fcm2-" + uuid.uuid4().hex[:6])
    yuborildi = _fcm_sahna(cid, monkeypatch)
    from app.services import push
    with _db() as db:
        with H.enter(db, _get(cid), plan_id="p1", instant=NOW - timedelta(days=90)):
            assert H.suppress_external() is True
            push.notify_low_stock(db, cid, [("Non", 2)], branch_name="F01")
    assert yuborildi == [], "tarixiy bajarishda push KETDI"
    # Kontekstdan chiqqach — yana YUBORILADI (bo'g'ish OQIB KETMAGAN)
    with _db() as db:
        push.notify_low_stock(db, cid, [("Non", 2)], branch_name="F01")
    assert len(yuborildi) == 1, "kontekstdan keyin push tiklanmadi"


# ══ 5) SO'ROV-DOIRALILIK ════════════════════════════════════════════════════
def test_kontekst_OQIMLAR_boyicha_AJRATILGAN(client):
    """⚠️  FastAPI sinxron endpoint'ni THREADPOOL'da chaqiradi.

    Parallel so'rovlar bir-birining bayrog'ini ko'rsa, bitta demo replay'i
    AYNI paytdagi haqiqiy do'konning push'ini ham bo'g'ib qo'yardi.
    `ContextVar` aynan shuni to'sadi (`cash/cutover_guard.py:91-94` dagi AYNI
    sabab).
    """
    cid, _ = _company("demo-thr-" + uuid.uuid4().hex[:6])
    natija: dict = {}

    def boshqa_oqim():
        natija["tashqi"] = (H.active(), H.suppress_external())

    with _db() as db:
        with H.enter(db, _get(cid), plan_id="p1", instant=NOW - timedelta(days=10)):
            assert H.suppress_external() is True
            t = threading.Thread(target=boshqa_oqim)
            t.start()
            t.join()

    assert natija["tashqi"] == (None, False), \
        f"boshqa oqim kontekstni KO'RDI: {natija['tashqi']}"


# ══ 6) OQMASLIK ═════════════════════════════════════════════════════════════
def test_kontekst_XATODA_ham_TIKLANADI(client):
    cid, _ = _company("demo-exc-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with pytest.raises(ValueError):
            with H.enter(db, _get(cid), plan_id="p1", instant=NOW - timedelta(days=5)):
                assert H.active() is not None
                raise ValueError("sun'iy xato")
    assert H.active() is None, "kontekst OQIB KETDI"
    assert H.suppress_external() is False


def test_KELAJAK_lahza_RAD_etiladi(client):
    cid, _ = _company("demo-fut-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            with H.enter(db, _get(cid), plan_id="p1", instant=NOW + timedelta(days=1)):
                pass
    assert e.value.status_code == 400
    assert H.active() is None


def test_plan_id_MAJBURIY(client):
    cid, _ = _company("demo-pid-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with pytest.raises(HTTPException) as e:
            with H.enter(db, _get(cid), plan_id="   ", instant=NOW - timedelta(days=1)):
                pass
    assert e.value.status_code == 400


def test_ICHMA_ICH_boshqa_dokon_RAD(client):
    cid1, _ = _company("demo-n1-" + uuid.uuid4().hex[:6])
    cid2, _ = _company("demo-n2-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with H.enter(db, _get(cid1), plan_id="p1", instant=NOW - timedelta(days=2)):
            with pytest.raises(RuntimeError):
                with H.enter(db, _get(cid2), plan_id="p1", instant=NOW - timedelta(days=2)):
                    pass
    assert H.active() is None


def test_darvoza_OTMASA_kontekst_OCHILMAYDI(client):
    """⚠️  Kontekstga kirishning YAGONA yo'li darvozadan o'tadi."""
    cid, _ = _company("fayzan-h1b-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with pytest.raises(HTTPException):
            with H.enter(db, _get(cid), plan_id="p1", instant=NOW - timedelta(days=3)):
                pytest.fail("darvoza o'tkazmasligi kerak edi")
    assert H.active() is None


# ══ 7) IDEMPOTENTLIK KALITLARI ══════════════════════════════════════════════
def test_event_key_DETERMINISTIK_va_AJRATILGAN():
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    a = H.event_key(c1, "plan-A", "d-087", "sale", "03")
    b = H.event_key(c1, "plan-A", "d-087", "sale", "03")
    assert a == b, "kalit deterministik EMAS — qayta yurish dublikat yozardi"
    assert a != H.event_key(c1, "plan-A", "d-087", "sale", "04"), "bo'lak ajratmaydi"
    assert a != H.event_key(c1, "plan-B", "d-087", "sale", "03"), "REJA ajratmaydi"
    assert a != H.event_key(c2, "plan-A", "d-087", "sale", "03"), "DO'KON ajratmaydi"
    assert a.int != 0


def test_event_key_bolaksiz_XATO():
    with pytest.raises(RuntimeError):
        H.event_key(uuid.uuid4(), "plan-A")


def test_kontekst_kaliti_event_key_bilan_AYNI(client):
    cid, _ = _company("demo-key-" + uuid.uuid4().hex[:6])
    with _db() as db:
        with H.enter(db, _get(cid), plan_id="plan-A",
                     instant=NOW - timedelta(days=7)) as ctx:
            assert ctx.key("d-007", "sale", "01") == \
                H.event_key(cid, "plan-A", "d-007", "sale", "01")
            assert ctx.company_id == cid and ctx.plan_id == "plan-A"
            assert H.instant() == ctx.instant
