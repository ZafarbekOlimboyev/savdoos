# -*- coding: utf-8 -*-
"""PHASE 5B.1 — `/sales/find` va `/sales/{id}` HAQIQIY POSTGRES'da.

SQLite nimani o'lchay olmaydi va bu fayl nimani isbotlaydi:
  · `find` ning `.first()` i ORDER BY'siz PG'da heap (yoki indeks) tartibidagi BIRINCHI
    qatorni qaytarardi — SQLite'dagi rowid tartibi emas, va UPDATE/VACUUM dan keyin
    o'zgaradi. `ORDER BY sold_at DESC` bilan to'qnashuvda (`#N` / import qilingan `N`,
    boshqa chekning `uid` i) kiritilish tartibidan QAT'I NAZAR eng yangi chek chiqadi;
    filial doirasi va `deleted_at` filtri tartibdan OLDIN ishlaydi;
  · darvoza (`require_any(*SALES_DOC_TIER)`), `has_any` va `field_access` PG'dagi rol va
    override qatorlari bilan AYNI javob beradi; ruxsatli xodim uchun find va detail
    doirasi, 404 matni va o'chirilgan chek pariteti bir xil.

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
Endpoint funksiyasi sessiya bilan TO'G'RIDAN chaqiriladi — PG testlaridagi odatiy naqsh
(`test_products_tracked_pg._royxat`), TestClient ilova engine'iga (SQLite) bog'langan.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_products_tracked_scope import NOW, _dokon

RUXSAT_403 = "Ruxsat yo'q: sotuvlar.view / hisobot.view"
YOQ_404 = "Chek topilmadi"
XODIMLAR = (("kassir", "A"), ("ega", None), ("administrator", "A"), ("menejer", None),
            ("menejer", "B"), ("omborchi", "A"))


def _baza(url):
    _initdb(url)
    eng = create_engine(url)
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def _xodim(db, d, rol, filial, override):
    """Override'li xodim (`_dokon` kalitlari `rol@filial` — bir xil juftdan ikkinchisi sig'maydi)."""
    from app.models.auth import Employee, EmployeeBranch, EmployeePermission, Permission, Role
    from app.models.enums import EmployeeStatus
    role = db.query(Role).filter(Role.code == rol).one()
    e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=role.id, full_name=f"5B.1 {rol}",
                 phone="+99893" + str(uuid.uuid4().int % 10_000_000).zfill(7),
                 status=EmployeeStatus.active, sec_epoch=0)
    db.add(e)
    db.flush()
    if filial:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=d["fil"][filial]))
    for code, allowed in override.items():
        pid = db.query(Permission.id).filter(Permission.code == code).scalar()
        assert pid is not None, code
        db.add(EmployeePermission(employee_id=e.id, permission_id=pid, allowed=allowed))
    db.flush()
    return e.id


def _chek(db, d, filial, receipt_no, sold_at, *, uid=None, deleted=False):
    from app.models.sales import Sale
    s = Sale(id=uuid.uuid4(), receipt_no=receipt_no, uid=uid, company_id=d["cid"],
             branch_id=d["fil"][filial], cashier_id=d["x"]["kassir@A"]["id"],
             subtotal=Decimal("100"), total=Decimal("100"), sold_at=sold_at,
             deleted_at=NOW if deleted else None)
    db.add(s)
    db.flush()         # har chek ALOHIDA flush — kiritilish (heap) tartibi aniq bo'lsin
    return s.id


def _darvozalar(endpoint):
    """Marshrut dependency daraxtidagi `require`/`require_any` tekshiruvchilari — AYNAN
    endpointga ulanganlari: darvoza marshrutdan olib tashlansa, bu fayl ham qizaradi."""
    from fastapi.routing import APIRoute

    from app.api.v1.sales import router
    route = next(r for r in router.routes if isinstance(r, APIRoute) and r.endpoint is endpoint)
    out, stack = [], list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        if (getattr(d.call, "__module__", None) == "app.core.deps"
                and getattr(d.call, "__qualname__", "").endswith(".checker")):
            out.append(d.call)
        stack.extend(d.dependencies)
    return out


def _chaqir(S, emp_id, fn, **kw):
    """Endpoint funksiyasi AYNI sessiyada, marshrutdagi ruxsat darvozasidan KEYIN (FastAPI
    tartibi: dependency — bazadagi chekdan oldin): (status, javob yoki detail)."""
    from app.api.v1 import sales as SA
    from app.models.auth import Employee
    from app.schemas.sales import SaleOut
    s = S()
    try:
        emp = s.get(Employee, emp_id)
        endpoint = getattr(SA, fn)
        try:
            for darvoza in _darvozalar(endpoint):
                darvoza(emp=emp, db=s)
            out = endpoint(**kw, emp=emp, db=s)
        except HTTPException as e:
            return e.status_code, e.detail
        if fn == "get_sale":
            out = SaleOut.model_validate(out).model_dump(mode="json")
        return 200, out
    finally:
        s.rollback()
        s.close()


def test_PG_FIND_toqnashuvda_ENG_YANGI_chek_KIRITILISH_tartibiga_bogliq_emas(pg_target):
    eng, S = _baza(pg_target)
    try:
        s = S()
        try:
            t = _dokon(s, "T", (), xodimlar=XODIMLAR)
            u = _dokon(s, "U", (), xodimlar=(("ega", None),))
            kutilgan, raqamlar = {}, iter(range(7001, 7100))
            # (to'qnashuv turi, eng yangi chek OLDIN kiritiladimi)
            for tur in ("chek", "uid"):
                for yangi_oldin in (True, False):
                    term = str(next(raqamlar))
                    yangi = dict(receipt_no=term) if tur == "chek" else \
                        dict(receipt_no=f"IMP-{term}", uid=term)
                    tartib = [("eski", dict(receipt_no="#" + term), NOW - timedelta(days=2)),
                              ("yangi", yangi, NOW - timedelta(hours=1))]
                    if yangi_oldin:
                        tartib.reverse()
                    ids = {k: _chek(s, t, "A", sold_at=v, **kw) for k, kw, v in tartib}
                    kutilgan[(tur, yangi_oldin)] = (term, ids["yangi"])

            # DOIRA va O'CHIRILGAN tartibdan OLDIN: eng yangisi o'chirilgan (A), undan keyingi
            # yangisi B da, eng eskisi A da — va ular aynan shu tartibda kiritiladi.
            d_term = str(next(raqamlar))
            d_ochirilgan = _chek(s, t, "A", f"DEL-{d_term}", NOW - timedelta(minutes=5),
                                 uid=d_term, deleted=True)
            d_b = _chek(s, t, "B", d_term, NOW - timedelta(hours=1))
            d_a = _chek(s, t, "A", "#" + d_term, NOW - timedelta(days=2))
            s.commit()
        finally:
            s.close()

        x = t["x"]
        for (tur, yangi_oldin), (term, yangi_id) in kutilgan.items():
            for q in (term, "#" + term):
                st, body = _chaqir(S, x["menejer@-"]["id"], "find_sale", q=q)
                assert st == 200, (tur, yangi_oldin, q, body)
                assert body["id"] == str(yangi_id), (tur, yangi_oldin, q, body["receipt_no"])

        for kalit, kut in (("ega@-", d_b), ("menejer@-", d_b), ("menejer@B", d_b),
                           ("kassir@A", d_a), ("administrator@A", d_a)):
            st, body = _chaqir(S, x[kalit]["id"], "find_sale", q=d_term)
            assert st == 200 and body["id"] == str(kut), (kalit, st, body)
            assert body["id"] != str(d_ochirilgan)
        # Begona do'kon: AYNI raqam bilan ham faqat 404.
        assert _chaqir(S, u["x"]["ega@-"]["id"], "find_sale", q=d_term) == (404, YOQ_404)
    finally:
        eng.dispose()


# (kalit, sotuv darajasi, A dagi chek doirada) — kalit `rol@filial[±override]`.
AKTORLAR = (
    ("ega@-", True, True),
    ("administrator@A", True, True),
    ("administrator@A-sotuvlar.view-hisobot.view", True, True),   # FULL_ACCESS istisnosi
    ("menejer@-", True, True),
    ("menejer@B", True, False),
    ("menejer@--sotuvlar.view-hisobot.view", False, None),
    ("omborchi@A", False, None),
    ("omborchi@A+hisobot.view", True, True),
    ("omborchi@A+qaytarishlar.create", False, None),
    ("kassir@A", True, True),
    ("kassir@A-sotuvlar.view", False, None),
    ("U:ega@-", True, False),
    ("U:omborchi@-", False, None),
)
OVERRIDE = {
    "administrator@A-sotuvlar.view-hisobot.view": ("administrator", "A",
                                                   {"sotuvlar.view": False, "hisobot.view": False}),
    "menejer@--sotuvlar.view-hisobot.view": ("menejer", None,
                                             {"sotuvlar.view": False, "hisobot.view": False}),
    "omborchi@A+hisobot.view": ("omborchi", "A", {"hisobot.view": True}),
    "omborchi@A+qaytarishlar.create": ("omborchi", "A", {"qaytarishlar.create": True}),
    "kassir@A-sotuvlar.view": ("kassir", "A", {"sotuvlar.view": False}),
}


def test_PG_DARAJA_field_access_va_FIND_DETAIL_doira_hamda_OCHIRILGAN_chek_pariteti(pg_target):
    from app.core.deps import FULL_ACCESS_ROLES, SALES_DOC_TIER, field_access, has_any
    from app.models.auth import Employee
    from app.models.sales import Sale

    eng, S = _baza(pg_target)
    try:
        s = S()
        try:
            t = _dokon(s, "T", (), xodimlar=XODIMLAR)
            u = _dokon(s, "U", (), xodimlar=(("ega", None), ("omborchi", None)))
            ids = {k: v["id"] for k, v in t["x"].items()}
            ids.update({f"U:{k}": v["id"] for k, v in u["x"].items()})
            for kalit, (rol, filial, ov) in OVERRIDE.items():
                ids[kalit] = _xodim(s, t, rol, filial, ov)
            chek = _chek(s, t, "A", "#5101", NOW - timedelta(hours=2), uid="260917005101")
            ochiriladi = _chek(s, t, "A", "#5102", NOW - timedelta(hours=1), uid="260917005102")
            s.commit()
        finally:
            s.close()

        for kalit, daraja, doirada in AKTORLAR:
            s = S()
            try:
                e = s.get(Employee, ids[kalit])
                fa = field_access(e, s)
                assert fa["sales"] is daraja and has_any(e, s, SALES_DOC_TIER) is daraja, (kalit, fa)
                # YOPIQ STANDART: noma'lum kod faqat FULL_ACCESS istisnosi bilan «bor».
                assert has_any(e, s, ("mavjud.bolmagan.kod",)) is (e.role.code in FULL_ACCESS_ROLES)
            finally:
                s.close()

            javob = {"F #N": _chaqir(S, ids[kalit], "find_sale", q="#5101"),
                     "F N": _chaqir(S, ids[kalit], "find_sale", q="5101"),
                     "F uid": _chaqir(S, ids[kalit], "find_sale", q="260917005101"),
                     "F yo'q": _chaqir(S, ids[kalit], "find_sale", q="#987654321"),
                     "G haqiqiy": _chaqir(S, ids[kalit], "get_sale", sale_id=chek),
                     "G tasodifiy": _chaqir(S, ids[kalit], "get_sale", sale_id=uuid.uuid4())}
            if not daraja:
                # PG'dagi rol/override qatorlaridan: mavjud va yo'q chek — AYNAN bir xil 403.
                assert list(javob.values()) == [(403, RUXSAT_403)] * len(javob), (kalit, javob)
                continue
            assert javob["F yo'q"] == javob["G tasodifiy"] == (404, YOQ_404), (kalit, javob)
            if not doirada:
                # Doiradan tashqaridagi HAQIQIY chek yo'q chekdan farqlanmaydi.
                assert list(javob.values()) == [(404, YOQ_404)] * len(javob), (kalit, javob)
                continue
            assert javob["G haqiqiy"][0] == 200 and javob["F #N"][0] == 200, (kalit, javob)
            assert javob["F #N"] == javob["F N"] == javob["F uid"], kalit
            f, g = javob["F #N"][1], javob["G haqiqiy"][1]
            assert (f["id"], f["receipt_no"], f["uid"]) == (g["id"], g["receipt_no"], g["uid"]) \
                == (str(chek), "#5101", "260917005101")
            assert float(f["total"]) == float(g["total"]) == 100.0

        # O'CHIRILGAN CHEK: find ham, detail ham 404. NEGATIV NAZORAT — o'chirishdan OLDIN ikkalasi 200.
        kassir = ids["kassir@A"]
        assert _chaqir(S, kassir, "find_sale", q="#5102")[0] == 200
        assert _chaqir(S, kassir, "get_sale", sale_id=ochiriladi)[0] == 200
        s = S()
        try:
            s.get(Sale, ochiriladi).deleted_at = NOW
            s.commit()
        finally:
            s.close()
        for kalit in ("ega@-", "administrator@A", "menejer@-", "kassir@A", "omborchi@A+hisobot.view"):
            for fn, kw in (("find_sale", {"q": "#5102"}), ("find_sale", {"q": "260917005102"}),
                           ("get_sale", {"sale_id": ochiriladi})):
                assert _chaqir(S, ids[kalit], fn, **kw) == (404, YOQ_404), (kalit, fn, kw)
    finally:
        eng.dispose()
