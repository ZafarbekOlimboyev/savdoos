# -*- coding: utf-8 -*-
"""KUZATUVNI YOQISH — BAZA TAYYORLIGI DARVOZASI (Phase 5C, G).

⚠️  NEGA (qaror TESKARISIGA o'zgardi). 5B.1 da idempotentlik noyob indekslari va uuid
    ustun tipi ATAYLAB aktivatsiyani to'smasdi: «aloqasiz indeks partiyani to'smasin».
    Lekin kuzatuvni yoqish QAYTARIB BO'LMAYDI va undan keyin ayni mahsulot offline
    sotuv, qaytarish, kassa harakati va QR to'lovini yozadi — takror yozuvni to'sadigan
    YAGONA baza to'sig'i esa o'sha indekslar, `client_uuid` ustuni varchar qolsa ORM
    taqqoslashi 42883 bilan yiqiladi. «Operator `/health/ready` dagi 8 booleanni o'qib
    ko'radi» qaytarib bo'lmaydigan amal uchun yetarli emas.

Bu fayl isbotlaydi (SQLite):
  · tayyorlik qizil -> `/lots/enable` 409 `LOT_SCHEMA_NOT_READY`, matn NOMSIZ va HECH
    NARSA yozilmaydi (bayroq, partiya, QOLDIQ qatori, audit, settings);
  · darvoza TARTIBI: ro'yxatda yo'q do'kon tayyorlik qizil bo'lsa ham 403 oladi —
    begona tenant sxema holatini zondlay olmaydi;
  · yoqish tekshiruvi KESHSIZ: `/lots/availability` ning 60 soniyalik keshi orqali
    o'tib bo'lmaydi;
  · `/lots/availability`: `activation_ready` + `readiness` bayroqlari va `can_enable`,
    `schema_ready`/`schema_problem_count` ma'nosi esa O'ZGARMAGAN;
  · `/lots/timezone/confirm` ATAYLAB darvozalanmagan (u partiya tarixini tug'dirmaydi).

Tasnif (`missing()`, `/health/ready` kalitlari) va haqiqiy Postgres tekshiruvlari —
`tests/test_runtime_columns.py` va `tests/test_runtime_columns_pg.py`.

⚠️  HAR SINOV O'Z DO'KONIDA (umumiy seed do'konining tarifi 10 foydalanuvchi).
"""
import uuid

import pytest

from app.core import required_schema as rs
from app.services import lot_policy as LP
from tests.test_lot_activation_scope import (_av, _darvoza_matni, _dokon, _enable, _iz,
                                             _mahsulot, _mahsulot_holati, _ochiq, _prod,
                                             _tasdiq)

# Server matni bilan AYNAN (lug'at kaliti ham shu — `test_lot_error_texts`).
TAYYOR_EMAS = ("Partiya kuzatuvini yoqib bo'lmaydi — server sxemasi to'liq tayyor emas "
               "(idempotentlik yoki ustun tipi). Avval /health/ready yashil bo'lsin.")
KOD = "LOT_SCHEMA_NOT_READY"
_IDEM = "idempotentlik indeksi yo'q: ux_sales_company_client_uuid (sales)"
_TIP = "ustun tipi uuid emas: cash_movements.client_uuid"
# Javobda CHIQMASLIGI shart: kod repo'si yopiq, jadval/ustun/indeks nomlari ommaviy emas.
SIRLAR = ("ux_", "cash_movements", "client_uuid", "idempotentlik indeksi", "uuid emas")


# ══ 1. ENABLE — TAYYOR EMAS BAZA ════════════════════════════════════════════

@pytest.mark.parametrize("nom,muammo", [
    pytest.param("idempotency_missing", _IDEM, id="idempotentlik"),
    pytest.param("column_type_problems", _TIP, id="ustun_tipi"),
])
def test_BAZA_tayyor_emas_ENABLE_409_va_HECH_NARSA_yozilmaydi(client, monkeypatch, nom, muammo):
    """Eski kodda (537d20b) AYNI so'rov 200 qaytarib, kuzatuvni QAYTARIB BO'LMAYDIGAN
    qilib yoqardi."""
    t = _dokon(filiallar=2)
    b1, b2 = t["bids"]
    pid = _mahsulot(t, qty=3, bid=b1)
    _prod(monkeypatch, (t["cid"], b1), (t["cid"], b2))
    oldin = _iz(t["cid"])
    assert len(oldin["inventory"]) == 1, "sinov farazi: qoldiq qatori bitta filialda"

    with monkeypatch.context() as m:
        m.setattr(rs, nom, lambda bind: [muammo])
        r = _enable(client, t["H"], pid, b1, legacy_unit_cost=70)
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == TAYYOR_EMAS, r.text
        assert r.headers.get("X-Error-Code") == KOD, dict(r.headers)
        for sir in SIRLAR:
            assert sir not in r.text, sir
        # Darvoza MAHSULOT qidiruvidan ham OLDIN: yo'q mahsulot ham AYNI 409 (404 emas).
        r2 = _enable(client, t["H"], str(uuid.uuid4()), b1, legacy_unit_cost=70)
        assert r2.status_code == 409 and r2.json()["detail"] == TAYYOR_EMAS, r2.text

    assert _mahsulot_holati(pid) == (False, False, None, 0)
    assert _iz(t["cid"]) == oldin, "rad etilgan yoqish BAZAGA tegdi"

    # ── MANFIY NAZORAT: soxta muammo olingach AYNI so'rov 200 ────────────────
    r3 = _enable(client, t["H"], pid, b1, legacy_unit_cost=70)
    assert r3.status_code == 200, r3.text
    keyin = _iz(t["cid"])
    assert _mahsulot_holati(pid)[0] is True
    # Yoqish HAR filialda qoldiq qatorini yaratadi — 409 da u YARATILMAGANI ham isbotlandi.
    assert len(keyin["inventory"]) == 2, keyin["inventory"]


def test_DARVOZA_TARTIBI_royxatda_YOQ_dokon_tayyorlik_QIZIL_bolsa_ham_403(client, monkeypatch):
    """Tayyorlik tekshiruvi do'kon × filial darvozasidan KEYIN turishi shart.

    Aks holda begona tenant 403 va 409 farqi orqali server sxemasi holatini zondlar,
    `test_lot_activation_scope` dagi «matn AYNI» kafolati esa buzilardi. (Eski kodda
    ham yashil — ATAYLAB qo'riqchi sinov.)
    """
    a, b = _dokon(), _dokon()
    pa, pb = _mahsulot(a, qty=1), _mahsulot(b, qty=2)
    _prod(monkeypatch, (a["cid"], a["bid"]))            # `b` ro'yxatda YO'Q
    matn = _darvoza_matni()
    oldin = _iz(b["cid"])
    with monkeypatch.context() as m:
        m.setattr(rs, "idempotency_missing", lambda bind: [_IDEM])
        r = _enable(client, b["H"], pb, b["bid"], legacy_unit_cost=70)
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == matn
        assert r.headers.get("X-Error-Code") is None, dict(r.headers)
        assert TAYYOR_EMAS not in r.text and "sxema" not in r.text
        # NAZORAT: ro'yxatDAGI do'kon AYNI holatda 409 oladi — 403 aynan darvozadan.
        r2 = _enable(client, a["H"], pa, a["bid"], legacy_unit_cost=70)
        assert r2.status_code == 409 and r2.json()["detail"] == TAYYOR_EMAS, r2.text
    assert _iz(b["cid"]) == oldin
    assert _mahsulot_holati(pa) == (False, False, None, 0)


def test_ENABLE_tekshiruvi_KESHSIZ_availability_keshi_orqali_OTIB_bolmaydi(client, monkeypatch):
    """`lot_policy.schema_problems` 60 s keshlanadi (ekranlar uchun). Qaytarib bo'lmaydigan
    yoqish esa AYNI LAHZADAGI bazaga tayanishi shart."""
    t = _dokon()
    pid = _mahsulot(t, qty=2)
    _ochiq(monkeypatch)
    LP._SCHEMA_CACHE.clear()
    j = _av(client, t["H"]).json()                      # kesh endi [] bilan to'ldi
    assert (j["schema_ready"], j["activation_ready"], j["can_enable"]) == (True, True, True), j
    oldin = _iz(t["cid"])
    try:
        # (a) YAXLITLIK — eski kodda ham to'sardi (nazorat: kesh yoqishga ta'sir qilmaydi).
        with monkeypatch.context() as m:
            m.setattr(rs, "missing", lambda bind: ["FK tasdiqlanmagan: fk_x"])
            assert _av(client, t["H"]).json()["schema_ready"] is True, "kesh sinovga kerak edi"
            r = _enable(client, t["H"], pid, t["bid"], legacy_unit_cost=70)
            assert r.status_code == 409, r.text
            assert "FK/cheklov tayyor emas" in r.json()["detail"], r.text
            assert r.headers.get("X-Error-Code") == KOD, dict(r.headers)
        # (b) IDEMPOTENTLIK — yangi darvoza; kesh bu yerda umuman yo'q.
        with monkeypatch.context() as m:
            m.setattr(rs, "idempotency_missing", lambda bind: [_IDEM])
            assert _av(client, t["H"]).json()["schema_ready"] is True    # yaxlitlik KESHDA
            r = _enable(client, t["H"], pid, t["bid"], legacy_unit_cost=70)
            assert r.status_code == 409 and r.json()["detail"] == TAYYOR_EMAS, r.text
        assert _iz(t["cid"]) == oldin
        assert _enable(client, t["H"], pid, t["bid"], legacy_unit_cost=70).status_code == 200
    finally:
        LP._SCHEMA_CACHE.clear()


# ══ 2. AVAILABILITY — UI DARVOZASI ══════════════════════════════════════════

@pytest.mark.parametrize("rejim", ["env", "scoped"])
def test_AVAILABILITY_tayyorlik_bayroqlari_can_enable_YOPIQ_nom_CHIQMAYDI(client, monkeypatch,
                                                                         rejim):
    """UI «yoqish mumkin» deb ko'rsatib, so'rov 409 olishi — eng yomon variant."""
    t = _dokon()
    if rejim == "scoped":
        _prod(monkeypatch, (t["cid"], t["bid"]))
    else:
        _ochiq(monkeypatch)
    LP._SCHEMA_CACHE.clear()
    try:
        j = _av(client, t["H"]).json()                  # nazorat: hammasi yashil
        assert j["readiness"] == {"schema_integrity": True, "idempotency": True,
                                  "column_types": True}, j
        assert (j["activation_ready"], j["can_enable"], j["activation_allowed"]) == (
            True, True, True), j

        with monkeypatch.context() as m:
            m.setattr(rs, "idempotency_missing", lambda bind: [_IDEM])
            r = _av(client, t["H"])
            j = r.json()
            assert j["readiness"] == {"schema_integrity": True, "idempotency": False,
                                      "column_types": True}, j
            assert j["activation_ready"] is False and j["can_enable"] is False, j
            # ⚠️  `schema_ready` MA'NOSI O'ZGARMADI — u FAQAT `missing()`.
            assert j["schema_ready"] is True and j["schema_problem_count"] == 0, j
            # Ruxsat va (do'kon, filial) darvozasi ham o'zgarmaydi.
            assert j["can_write"] is True and j["activation_allowed"] is True, j
            for sir in SIRLAR:
                assert sir not in r.text, sir
    finally:
        LP._SCHEMA_CACHE.clear()


# ══ 3. TASDIQ — ATAYLAB DARVOZALANMAGAN ═════════════════════════════════════

def test_TASDIQ_baza_tayyorligiga_BOGLANMAGAN_yoqish_esa_TOSILADI(client, monkeypatch):
    """QAROR (Phase 5C): `/lots/timezone/confirm` DB tayyorligini TEKSHIRMAYDI.

    U partiya tarixini tug'dirmaydi — qulf ostida `settings.catalog` ning bitta kaliti
    va bitta audit qatori, idempotent. Yoqish esa tayyorlikni keshsiz qayta tekshiradi,
    ya'ni «tasdiq berildi» hech qachon «yoqsa bo'ladi» degani emas. Bu sinov qarorni
    MIXLAYDI: tasdiqqa darvoza qo'shilsa — QIZIL.
    """
    t = _dokon()
    pid = _mahsulot(t, qty=1)
    _ochiq(monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(rs, "idempotency_missing", lambda bind: [_IDEM])
        m.setattr(rs, "column_type_problems", lambda bind: [_TIP])
        c = _tasdiq(client, t["H"], t["bid"])
        assert c.status_code == 200, c.text
        assert (c.json()["confirmed"], c.json()["changed"]) == (True, True), c.text
        # AYNI holatda yoqish TO'SILADI — farq ATAYLAB.
        r = _enable(client, t["H"], pid, t["bid"], track_expiry=True, legacy_unit_cost=70)
        assert r.status_code == 409 and r.json()["detail"] == TAYYOR_EMAS, r.text
    assert _mahsulot_holati(pid) == (False, False, None, 0)
    # NAZORAT: tasdiq haqiqatan yozilgan — yoqish tayyorlik tiklangach 200.
    r = _enable(client, t["H"], pid, t["bid"], track_expiry=True, legacy_unit_cost=70)
    assert r.status_code == 200, r.text
    assert r.json()["track_expiry"] is True
