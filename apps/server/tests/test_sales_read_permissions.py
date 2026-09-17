# -*- coding: utf-8 -*-
"""PHASE 5B.1 — SOTUV HUJJATINI O'QISH RUXSATI (`/sales/find`, `/sales/{id}`).

Ilgari ikkala endpoint faqat LOGIN tekshirardi. Chek raqami ketma-ket (`#N`), ya'ni
istalgan xodim (omborchi ham, `sotuvlar.view` i olib qo'yilgan kassir ham) raqamlarni
aylanib chiqib har chekning kassiri, narxlari va `sale_id` sini o'qiy olardi — partiya
ekranlari ATAYLAB yashirgan maydonlar shu yo'l bilan ochilardi.

QOIDA (yagona manba — `app.core.deps`):

  darvoza      — `require_any(*SALES_DOC_TIER)` = `sotuvlar.view` YOKI `hisobot.view`,
                 DEPENDENCY sifatida: bazadan OLDIN, ya'ni ruxsatsiz xodim mavjud va
                 yo'q chek uchun AYNAN bir xil 403 oladi (403 hatto 422 dan oldin);
  doira        — kompaniya + `visible_branches`; begona do'kon, begona filial, yo'q
                 va o'chirilgan chek — bir xil 404;
  kassir       — O'Z SOTUVI bilan cheklanmaydi: qaytarish filial bo'yicha;
  maydonlar    — `field_access` darvoza bilan AYNAN bir xil javob beradi.

⚠️  ALOHIDA DO'KON (business tarif). Seed do'koni tarifi 10 foydalanuvchi va u boshqa
    fayllar bilan bo'lingan: bu yerdagi ~25 xodim unga yozilsa, boshqa fayllardagi
    xodim yaratish 403 bilan yiqilardi.
"""
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.test_lot_fefo_sale import _enable, _lots, _product, _recv

_VK = {"X-Vendor-Key": "test-vendor-key"}
_PW = "Toshkent-Kuz-2026"
FIND = "/api/v1/sales/find"
RUXSAT_403 = {"detail": "Ruxsat yo'q: sotuvlar.view / hisobot.view"}
YOQ_404 = {"detail": "Chek topilmadi"}

# Rol standarti OLIB TASHLANIB, faqat `hisobot.view` qoldirilgan xodim.
FAQAT_HISOBOT = {"kassa.sell": False, "kassa.view": False, "sotuvlar.view": False,
                 "qaytarishlar.create": False, "mijozlar.view": False, "hisobot.view": True}


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _dokon(client, plan):
    phone = f"+99894{uuid.uuid4().int % 10000000:07d}"
    code = f"sr{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": "QA sotuv o'qish", "company_code": code, "owner_name": "QA Ega",
        "owner_phone": phone, "owner_password": "Toshkent-Bahor-2026", "plan": plan})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password",
                     json={"phone": phone, "password": "Toshkent-Bahor-2026"})
    assert lg.status_code == 200, lg.text
    return {"id": lg.json()["employee"]["id"],
            "h": {"Authorization": f"Bearer {lg.json()['access_token']}"}}


def _filial(client, h, name):
    r = client.post("/api/v1/branches", headers=h, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _xodim(client, ega_h, rol, *, ism=None, filial=None, override=None):
    phone = "+99890" + str(uuid.uuid4().int % 10_000_000).zfill(7)
    body = {"full_name": ism or f"5B sotuv {rol}", "phone": phone, "password": _PW,
            "role_code": rol}
    if filial:
        body["branch_id"] = filial
    r = client.post("/api/v1/employees", headers=ega_h, json=body)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    if override:
        p = client.patch(f"/api/v1/employees/{eid}/permissions", headers=ega_h,
                         json={"overrides": override})
        assert p.status_code == 200, p.text
        # Override HAQIQATAN qo'llangan — aks holda sinov rolni o'lchardi, override'ni emas.
        perms = set(p.json()["permissions"])
        for code, allowed in override.items():
            assert (code in perms) is allowed, (code, sorted(perms))
    lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": _PW})
    assert lg.status_code == 200, lg.text
    return {"id": eid, "h": {"Authorization": f"Bearer {lg.json()['access_token']}"}}


def _qoldiq(pid, bid, qty):
    """Filialdagi qoldiq qatorini to'g'ridan-to'g'ri o'rnatadi (kuzatuvsiz mahsulot)."""
    from app.models.inventory import Inventory
    with _db() as db:
        i = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid),
                                       Inventory.branch_id == uuid.UUID(bid)).first()
        if i is None:
            i = Inventory(product_id=uuid.UUID(pid), branch_id=uuid.UUID(bid), qty=Decimal("0"),
                          min_qty=0, updated_at=datetime.now(timezone.utc))
            db.add(i)
        i.qty = Decimal(str(qty))
        db.commit()


def _karta_sotuv(client, h, pid, qty=1, price=100):
    # ⚠️  KARTA: alohida do'kon cutover'dan keyin yaratiladi, naqd savdo esa aniq kassa
    #     (TILL) bilan smena talab qiladi. Bu sinov ruxsatni o'lchaydi, kassani emas.
    r = client.post("/api/v1/sales", headers=h, json={
        "items": [{"product_id": pid, "qty": qty, "unit_price": price}],
        "payment_method": "card", "given_amount": price * qty,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()


def _qaytar(client, h, sale_id, pid):
    return client.post("/api/v1/returns", headers=h, json={
        "original_sale_id": sale_id, "reason": "customer", "restock": True,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 1, "unit_price": 0}]})


@pytest.fixture(scope="module")
def muhit(client):
    """T do'koni (A1, A2 filiallari) + begona do'kon; kassir A1 ning karta sotuvi."""
    ega = _dokon(client, "business")
    H = ega["h"]
    a1, a2 = _filial(client, H, "A1 filial"), _filial(client, H, "A2 filial")
    x = {"ega": ega}
    x["administrator"] = _xodim(client, H, "administrator")
    x["administrator@A2"] = _xodim(client, H, "administrator", filial=a2)
    x["menejer"] = _xodim(client, H, "menejer")
    x["menejer@A2"] = _xodim(client, H, "menejer", filial=a2)
    x["omborchi"] = _xodim(client, H, "omborchi")
    x["kassir@A1"] = _xodim(client, H, "kassir", ism="Kassir Birinchi", filial=a1)
    x["kassir2@A1"] = _xodim(client, H, "kassir", ism="Kassir Ikkinchi", filial=a1)
    x["kassir@A2"] = _xodim(client, H, "kassir", ism="Kassir A2", filial=a2)
    x["kassir@A1-sotuvlar.view"] = _xodim(client, H, "kassir", filial=a1,
                                          override={"sotuvlar.view": False})
    x["kassir@A1-qaytarishlar.create"] = _xodim(client, H, "kassir", filial=a1,
                                                override={"qaytarishlar.create": False})
    x["faqat-hisobot.view"] = _xodim(client, H, "kassir", filial=a1, override=FAQAT_HISOBOT)
    begona = _dokon(client, "start")
    x["begona-ega"] = begona
    x["begona-kassir"] = _xodim(client, begona["h"], "kassir")
    x["begona-omborchi"] = _xodim(client, begona["h"], "omborchi")

    pid = _product(client, H)
    _qoldiq(pid, a1, 1000)
    sale = _karta_sotuv(client, x["kassir@A1"]["h"], pid, qty=5)
    # Sotuv HAQIQATAN A1 da va kassir A1 nomida — aks holda doira sinovlari bo'sh o'tardi.
    assert (sale["branch_id"], sale["cashier_id"]) == (a1, x["kassir@A1"]["id"]), sale
    return {"x": x, "a1": a1, "a2": a2, "pid": pid, "sale": sale}


# ══ 1 · MATRITSA ═════════════════════════════════════════════════════════════
RUXSATLI, TASHQARIDA, RAD, ANONIM = "ruxsatli", "doiradan-tashqari", "rad", "anonim"

AKTORLAR = [
    ("ega", RUXSATLI),
    ("administrator", RUXSATLI),
    ("administrator@A2", TASHQARIDA),
    ("menejer", RUXSATLI),
    ("menejer@A2", TASHQARIDA),
    ("omborchi", RAD),
    ("kassir@A1", RUXSATLI),
    ("kassir2@A1", RUXSATLI),
    ("kassir@A2", TASHQARIDA),
    ("kassir@A1-sotuvlar.view", RAD),
    # Daraja KO'RISH haqida: qaytarish huquqi olingan kassir chekni ko'radi.
    ("kassir@A1-qaytarishlar.create", RUXSATLI),
    ("faqat-hisobot.view", RUXSATLI),
    ("begona-ega", TASHQARIDA),
    ("begona-kassir", TASHQARIDA),
    ("begona-omborchi", RAD),
    ("tokensiz", ANONIM),
]

_BARCHASI = ("F #N", "F N", "F uid", "F yo'q", "F bo'sh", "F berilmagan",
             "G haqiqiy", "G tasodifiy", "G buzuq")
KUTILGAN = {
    RUXSATLI: {"F #N": 200, "F N": 200, "F uid": 200, "F yo'q": 404, "F bo'sh": 400,
               "F berilmagan": 422, "G haqiqiy": 200, "G tasodifiy": 404, "G buzuq": 422},
    TASHQARIDA: {"F #N": 404, "F N": 404, "F uid": 404, "F yo'q": 404, "F bo'sh": 400,
                 "F berilmagan": 422, "G haqiqiy": 404, "G tasodifiy": 404, "G buzuq": 422},
    RAD: {k: 403 for k in _BARCHASI},
    ANONIM: {k: 401 for k in _BARCHASI},
}


def _sorovlar(sale):
    n = sale["receipt_no"]
    return {
        "F #N": (FIND, {"q": n}),
        "F N": (FIND, {"q": n.lstrip("#")}),
        "F uid": (FIND, {"q": sale["uid"]}),
        "F yo'q": (FIND, {"q": "#987654321"}),
        "F bo'sh": (FIND, {"q": "   "}),
        "F berilmagan": (FIND, None),
        "G haqiqiy": (f"/api/v1/sales/{sale['id']}", None),
        "G tasodifiy": (f"/api/v1/sales/{uuid.uuid4()}", None),
        "G buzuq": ("/api/v1/sales/bu-uuid-emas", None),
    }


@pytest.mark.parametrize("nom,tur", AKTORLAR, ids=[a[0] for a in AKTORLAR])
def test_MATRITSA_find_va_detail_rol_filial_va_dokon_boyicha(client, muhit, nom, tur):
    s = muhit["sale"]
    assert s["receipt_no"].startswith("#") and s["uid"], s
    h = {} if tur == ANONIM else muhit["x"][nom]["h"]
    javob = {k: client.get(p, params=q, headers=h) for k, (p, q) in _sorovlar(s).items()}
    holat = {k: r.status_code for k, r in javob.items()}
    assert holat == KUTILGAN[tur], (nom, holat)

    for k, r in javob.items():
        if r.status_code == 200:
            assert r.json()["id"] == s["id"], (nom, k, r.json())
        elif r.status_code == 404:
            assert r.json() == YOQ_404, (nom, k, r.json())
        elif r.status_code == 403:
            assert r.json() == RUXSAT_403, (nom, k, r.json())
    if tur == RAD:
        # MAVJUDLIK ORACLE'I YO'Q: mavjud chek, yo'q chek, bo'sh/berilmagan so'rov va
        # buzuq UUID — BAYT-BAYT bir xil javob.
        assert len({r.content for r in javob.values()}) == 1, {k: r.content for k, r in javob.items()}
    if tur == TASHQARIDA:
        # Doiradan tashqaridagi HAQIQIY chek yo'q chekdan farqlanmaydi.
        assert javob["F #N"].content == javob["F uid"].content == javob["F yo'q"].content
        assert javob["G haqiqiy"].content == javob["G tasodifiy"].content


def test_CHEK_RAQAMLARINI_aylanish_ruxsatsizga_HECH_NARSA_bermaydi(client, muhit):
    """Omborchi `#N` larni ketma-ket so'raydi: faqat 403, 200/404 farqi YO'Q."""
    x, s = muhit["x"], muhit["sale"]
    n = int(s["receipt_no"].lstrip("#"))
    raqamlar = [f"#{k}" for k in range(n - 3, n + 4)]
    # NEGATIV NAZORAT: oraliqda HAQIQIY chek ham, yo'q chek ham bor — ruxsatli xodim
    # ularni ajrata oladi. Aks holda «hammasi 403» hech narsani isbotlamasdi.
    men = {q: client.get(FIND, params={"q": q}, headers=x["menejer"]["h"]).status_code
           for q in raqamlar}
    assert 200 in men.values() and 404 in men.values(), men

    omb = {q: client.get(FIND, params={"q": q}, headers=x["omborchi"]["h"]) for q in raqamlar}
    assert {r.status_code for r in omb.values()} == {403}, {q: r.status_code for q, r in omb.items()}
    assert len({r.content for r in omb.values()}) == 1


# ══ 2 · KASSIR SEMANTIKASI — FILIAL BO'YICHA, O'Z SOTUVI BILAN EMAS ═══════════
def test_KASSIR_filialdagi_BOSHQA_kassir_chekini_topadi_va_QAYTARADI(client, muhit):
    """Qaytarish filial bo'yicha (`POST /returns` ko'rinadigan filialdagi istalgan chekni
    qabul qiladi) — o'qish darvozasi kassirni o'z sotuvi bilan CHEKLAMAYDI."""
    x, s, pid = muhit["x"], muhit["sale"], muhit["pid"]
    k2 = x["kassir2@A1"]
    assert s["cashier_id"] == x["kassir@A1"]["id"] != k2["id"]
    f = client.get(FIND, params={"q": s["receipt_no"]}, headers=k2["h"])
    assert f.status_code == 200, f.text
    assert f.json()["id"] == s["id"] and f.json()["cashier"] == "Kassir Birinchi", f.json()
    r = _qaytar(client, k2["h"], f.json()["id"], pid)
    assert r.status_code == 200, r.text

    # Boshqa filial kassiri: na topadi, na qaytaradi.
    ka2 = x["kassir@A2"]["h"]
    f2 = client.get(FIND, params={"q": s["receipt_no"]}, headers=ka2)
    assert f2.status_code == 404 and f2.json() == YOQ_404, f2.text
    assert _qaytar(client, ka2, s["id"], pid).status_code == 404


def test_DARAJA_KORISH_haqida_qaytarish_huquqiga_TEGMAYDI(client, muhit):
    x, s, pid = muhit["x"], muhit["sale"], muhit["pid"]
    g = f"/api/v1/sales/{s['id']}"
    # `sotuvlar.view` olingan kassir: chekni KO'RA OLMAYDI (ro'yxat ham 403 edi) ...
    h = x["kassir@A1-sotuvlar.view"]["h"]
    assert client.get(FIND, params={"q": s["receipt_no"]}, headers=h).status_code == 403
    assert client.get(g, headers=h).status_code == 403
    assert client.get("/api/v1/sales", headers=h).status_code == 403
    # ... qaytarish huquqi esa bu o'zgarishda O'ZGARMAGAN.
    assert _qaytar(client, h, s["id"], pid).status_code == 200

    # `qaytarishlar.create` olingan kassir: KO'RADI, lekin qaytara olmaydi.
    h = x["kassir@A1-qaytarishlar.create"]["h"]
    assert client.get(FIND, params={"q": s["receipt_no"]}, headers=h).status_code == 200
    assert client.get(g, headers=h).status_code == 200
    assert _qaytar(client, h, s["id"], pid).status_code == 403


# ══ 3 · F VA G PARITETI ══════════════════════════════════════════════════════
def _vaqt(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


@pytest.mark.parametrize("nom", ["ega", "menejer"])
def test_F_va_G_BIR_XIL_chekni_beradi_ochirilganida_IKKALASI_404(client, muhit, nom):
    from app.models.sales import Sale
    x = muhit["x"]
    h = x[nom]["h"]
    d = _karta_sotuv(client, x["kassir@A1"]["h"], muhit["pid"])
    g_url = f"/api/v1/sales/{d['id']}"

    f = client.get(FIND, params={"q": d["receipt_no"]}, headers=h)
    g = client.get(g_url, headers=h)
    # NEGATIV NAZORAT: o'chirishdan OLDIN ikkalasi ham ochiladi.
    assert f.status_code == 200, f.text
    assert g.status_code == 200, g.text
    fj, gj = f.json(), g.json()
    assert (fj["id"], fj["receipt_no"], fj["uid"]) == (gj["id"], gj["receipt_no"], gj["uid"] or "")
    assert (fj["id"], fj["receipt_no"]) == (d["id"], d["receipt_no"])
    assert float(fj["total"]) == float(gj["total"]) == float(d["total"])
    assert _vaqt(fj["sold_at"]) == _vaqt(gj["sold_at"])

    with _db() as db:
        db.get(Sale, uuid.UUID(d["id"])).deleted_at = datetime.now(timezone.utc)
        db.commit()
    for r in (client.get(FIND, params={"q": d["receipt_no"]}, headers=h),
              client.get(FIND, params={"q": d["uid"]}, headers=h),
              client.get(g_url, headers=h)):
        assert r.status_code == 404, r.text
        assert r.json() == YOQ_404


def test_FIND_toqnashuvda_ENG_YANGI_chekni_beradi(client, muhit):
    """`N` so'rovi `#N` chekka ham, import qilingan `N` (belgisiz) chekka ham mos keladi.

    ⚠️  ORDER BY siz `.first()` bazaning ichki tartibini qaytarardi — qaysi chek
        chiqishi indeks rejasiga bog'liq edi. Ikkala tartibda ham tekshiriladi:
        natija `sold_at` ga ergashadi, qator kiritilish tartibiga emas."""
    from app.models.sales import Sale
    x, pid = muhit["x"], muhit["pid"]
    a = _karta_sotuv(client, x["kassir@A1"]["h"], pid)
    b = _karta_sotuv(client, x["kassir@A1"]["h"], pid)
    term = a["receipt_no"].lstrip("#")
    now = datetime.now(timezone.utc)
    for b_vaqti, kutilgan in ((now - timedelta(days=1), a["id"]),
                              (now + timedelta(minutes=1), b["id"])):
        with _db() as db:
            sb = db.get(Sale, uuid.UUID(b["id"]))
            sb.receipt_no = term           # import qilingan tarix: '#' siz — UNIQUE buzilmaydi
            sb.sold_at = b_vaqti
            db.get(Sale, uuid.UUID(a["id"])).sold_at = now
            db.commit()
        r = client.get(FIND, params={"q": term}, headers=x["menejer"]["h"])
        assert r.status_code == 200, r.text
        assert r.json()["id"] == kutilgan, (b_vaqti, r.json()["receipt_no"])


# ══ 4 · STATIK QO'RIQCHI — LOGIN-ONLY SOTUV O'QISHI QAYTMASIN ════════════════
_CHECKERS = {"require.<locals>.checker", "require_any.<locals>.checker"}


def _yollar(routes, prefix=""):
    """(to'liq yo'l, APIRoute). FastAPI 0.14x ichki routerlarni DANGASA qo'shadi
    (`_IncludedRouter.original_router`); eski versiyada yo'llar allaqachon tekis."""
    from fastapi.routing import APIRoute
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif getattr(r, "original_router", None) is not None:
            ctx = getattr(r, "include_context", None)
            yield from _yollar(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))


def _ruxsat_kodlari(dep) -> set:
    """Dependency daraxtidagi `require`/`require_any` tekshiruvchilarining ruxsat kodlari."""
    kod: set = set()
    call = dep.call
    if (inspect.isfunction(call) and call.__module__ == "app.core.deps"
            and call.__qualname__ in _CHECKERS):
        nl = inspect.getclosurevars(call).nonlocals
        if "permission_code" in nl:
            kod.add(nl["permission_code"])
        kod.update(nl.get("permission_codes", ()))
    for d in dep.dependencies:
        kod |= _ruxsat_kodlari(d)
    return kod


def test_SOTUV_va_QAYTARISH_GET_yollarining_HAR_BIRIDA_ruxsat_darvozasi_bor(client):
    from fastapi import APIRouter, Depends

    from app.core.deps import get_current_employee, require
    from app.main import app

    # NEGATIV NAZORAT: detektor login-only yo'lni HAQIQATAN ushlaydi.
    r = APIRouter()

    @r.get("/sales/login-only")
    def _faqat_login(emp=Depends(get_current_employee)):
        return None

    @r.get("/sales/ruxsatli")
    def _ruxsatli(emp=Depends(require("sotuvlar.view"))):
        return None

    sinov = dict(_yollar(r.routes))
    assert _ruxsat_kodlari(sinov["/sales/login-only"].dependant) == set()
    assert _ruxsat_kodlari(sinov["/sales/ruxsatli"].dependant) == {"sotuvlar.view"}

    yollar = {p: rt for p, rt in _yollar(app.routes)
              if "GET" in rt.methods and p.startswith(("/api/v1/sales", "/api/v1/returns"))}
    assert {"/api/v1/sales", "/api/v1/sales/find", "/api/v1/sales/{sale_id}",
            "/api/v1/returns"} <= set(yollar), sorted(yollar)
    ochiq = sorted(p for p, rt in yollar.items() if not _ruxsat_kodlari(rt.dependant))
    assert ochiq == [], f"faqat login bilan ochiq sotuv/qaytarish o'qishi: {ochiq}"

    from app.core.deps import SALES_DOC_TIER
    for p in ("/api/v1/sales/find", "/api/v1/sales/{sale_id}"):
        assert _ruxsat_kodlari(yollar[p].dependant) == set(SALES_DOC_TIER), p


def test_LOTS_READ_ozining_ruxsat_predikatini_YOZMAYDI():
    """Maydon darajalari FAQAT `deps` da: nusxa predikat darvoza bilan jimgina ajralardi."""
    import app.api.v1.lots_read as LR
    from app.core import deps

    assert not hasattr(LR, "_field_access") and not hasattr(LR, "_can")
    assert LR.field_access is deps.field_access
    assert "FULL_ACCESS_ROLES" not in inspect.getsource(LR)


# ══ 5 · field_access == ENDPOINTLAR — RUXSAT TO'PLAMLARI TO'RI ═══════════════
@pytest.fixture(scope="module")
def partiya(client, muhit):
    """T do'konida: sotuv + hisobdan chiqarishli partiya va chekka bog'langan qarz."""
    H = muhit["x"]["ega"]["h"]
    sp = client.post("/api/v1/suppliers", headers=H, json={"name": "5B sotuv o'qish ta'minotchi"})
    assert sp.status_code == 200, sp.text
    sup = sp.json()["id"]

    pid = _product(client, H)
    assert _enable(client, H, pid, expiry=False).status_code == 200
    assert _recv(client, H, sup, pid, 10, 12, batch="SOTUV-DARAJA-1").status_code == 200
    lot = str(_lots(pid)[0].id)
    sale = _karta_sotuv(client, H, pid, qty=3)
    w = client.post("/api/v1/inventory/writeoff", headers=H, json={
        "product_id": pid, "qty": 2, "reason": "expired",
        "lots": [{"stock_batch_id": lot, "qty": 2}], "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 200, w.text

    pid2 = _product(client, H)
    assert _enable(client, H, pid2, expiry=False).status_code == 200
    assert _recv(client, H, sup, pid2, 1, 10).status_code == 200
    p = client.post("/api/v1/sync/push", headers=H, json={"sales": [{
        "client_uuid": str(uuid.uuid4()), "payment_method": "card", "given_amount": 300,
        "items": [{"product_id": pid2, "qty": 3, "unit_price": 100}]}]})
    assert p.status_code == 200 and p.json()["accepted"] == 1, p.text
    sfs = client.get("/api/v1/lots/shortfalls", headers=H).json()["shortfalls"]
    sf = [s for s in sfs if s["product_id"] == pid2]
    assert len(sf) == 1 and sf[0]["sale_item_id"], sfs
    return {"lot": lot, "sale": sale, "sf": sf[0]["id"]}


# (nom, rol, override, xarid, sotuv, xodim) — rol None: do'kon egasi.
TOR = [
    ("ega", None, None, True, True, True),
    ("administrator", "administrator", None, True, True, True),
    # FULL_ACCESS istisnosi override'dan USTUN (darvoza ham, maydon ham).
    ("administrator-sotuvlar.view-hisobot.view", "administrator",
     {"sotuvlar.view": False, "hisobot.view": False}, True, True, True),
    ("menejer", "menejer", None, False, True, True),
    ("menejer-sotuvlar.view", "menejer", {"sotuvlar.view": False}, False, True, True),
    ("menejer-hisobot.view", "menejer", {"hisobot.view": False}, False, True, False),
    ("menejer-sotuvlar.view-hisobot.view", "menejer",
     {"sotuvlar.view": False, "hisobot.view": False}, False, False, False),
    ("omborchi", "omborchi", None, True, False, False),
    ("omborchi+sotuvlar.view", "omborchi", {"sotuvlar.view": True}, True, True, False),
    ("omborchi+hisobot.view", "omborchi", {"hisobot.view": True}, True, True, True),
    # Qaytarish huquqlari sotuv hujjatini KO'RISH darajasi EMAS.
    ("omborchi+qaytarishlar", "omborchi",
     {"qaytarishlar.create": True, "qaytarishlar.view": True}, True, False, False),
    ("kassir+ombor.view", "kassir", {"ombor.view": True}, False, True, False),
]


@pytest.mark.parametrize("nom,rol,override,xarid,sotuv,xodim", TOR, ids=[t[0] for t in TOR])
def test_FIELD_ACCESS_darvoza_va_maydon_yashirish_BIR_XIL_javob_beradi(
        client, muhit, partiya, nom, rol, override, xarid, sotuv, xodim):
    from app.core.deps import FULL_ACCESS_ROLES, SALES_DOC_TIER, field_access, has_any
    from app.models.auth import Employee

    ega = muhit["x"]["ega"]
    a = ega if rol is None else _xodim(client, ega["h"], rol, override=override)
    with _db() as db:
        e = db.get(Employee, uuid.UUID(a["id"]))
        fa = field_access(e, db)
        tier = has_any(e, db, SALES_DOC_TIER)
        nomalum = has_any(e, db, ("mavjud.bolmagan.kod",))
        full = e.role.code in FULL_ACCESS_ROLES
    assert fa == {"purchasing": xarid, "sales": sotuv, "staff": xodim}, (nom, fa)
    assert tier is sotuv
    # YOPIQ STANDART: noma'lum kod faqat FULL_ACCESS istisnosi bilan «bor».
    assert nomalum is full

    h, s = a["h"], partiya["sale"]
    g = client.get(f"/api/v1/sales/{s['id']}", headers=h)
    f = client.get(FIND, params={"q": s["receipt_no"]}, headers=h)
    mv = client.get("/api/v1/inventory/movements", headers=h)
    bd = client.get(f"/api/v1/lots/batches/{partiya['lot']}", headers=h)
    sd = client.get(f"/api/v1/lots/shortfalls/{partiya['sf']}", headers=h)
    sl = client.get("/api/v1/lots/shortfalls", headers=h)
    for r in (bd, sd, sl):
        assert r.status_code == 200, r.text
    # «Yopiq» faqat RUXSAT sababli bo'lsin — 404/500 bilan tasodifan mos kelmasin.
    for r in (g, f, mv):
        assert r.status_code in (200, 403), r.text
    bdj, sdj, slj = bd.json(), sd.json(), sl.json()
    row = [x for x in slj["shortfalls"] if x["id"] == partiya["sf"]]
    assert len(row) == 1, slj

    sotuv_kuzatuv = {
        "G 200": g.status_code == 200,
        "F 200": f.status_code == 200,
        "partiya sale_id": bdj["sales"][0]["sale_id"] is not None,
        "partiya receipt_no": bdj["sales"][0]["receipt_no"] is not None,
        "qarz sale_id": sdj["sale"]["sale_id"] is not None,
        "qarz receipt_no": sdj["sale"]["receipt_no"] is not None,
        "qarz sale_item_id": sdj["sale"]["sale_item_id"] is not None,
        "qarz cashier": sdj["sale"]["cashier"] is not None,
        "qarz unit_price": sdj["sale"]["unit_price"] is not None,
        "qarzlar ro'yxati sale_item_id": row[0]["sale_item_id"] is not None,
    }
    assert sotuv_kuzatuv == {k: fa["sales"] for k in sotuv_kuzatuv}, (nom, sotuv_kuzatuv)
    assert (bdj["redacted"]["sales"], sdj["redacted"]["sales"], slj["redacted"]["sales"]) \
        == (not fa["sales"],) * 3

    xodim_kuzatuv = {
        "movements 200": mv.status_code == 200,
        "partiya employee": bdj["movements"][0]["employee"] is not None,
    }
    assert xodim_kuzatuv == {k: fa["staff"] for k in xodim_kuzatuv}, (nom, xodim_kuzatuv)
    assert bdj["redacted"]["staff"] is (not fa["staff"])

    assert (bdj["supplier"] is not None) is fa["purchasing"]
    assert bdj["redacted"]["purchasing"] is (not fa["purchasing"])

    # Ombor ma'lumoti ruxsatga qarab O'ZGARMAYDI: qator, sana, miqdor, sanoq.
    assert len(bdj["sales"]) == 1 and bdj["sales"][0]["qty"] == 3.0 and bdj["sales"][0]["sold_at"]
    assert sdj["sale"]["qty"] == 3.0 and sdj["open_qty"] == 2.0
    assert slj["count"] == len(slj["shortfalls"])
