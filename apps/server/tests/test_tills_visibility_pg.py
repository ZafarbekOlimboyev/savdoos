# -*- coding: utf-8 -*-
"""PHASE 5F (B2) — `/tills`, `/safes`, `/cash-setup` FILIAL DOIRASI haqiqiy PostgreSQL'da.

⚠️  NEGA. Kassa endpointlari ilgari faqat TENANT bo'yicha cheklangan edi:
    · A filial kassiri `GET /tills` bilan butun do'kon kassalarini (terminal UUID'lari bilan),
      `?branch_id=<B>` bilan esa B filialnikini o'qirdi;
    · B filialga biriktirilgan administrator A filial kassasini arxivlay / o'chira olardi
      (`_acc` faqat tenantni tekshirardi);
    · `/cash-setup` har xodimga do'konning HAMMA filialini ko'rsatardi;
    · o'qish uchun hech qanday ruxsat talab qilinmasdi (ombor xodimi ham ko'rardi).

Bu fayl isbotlaydi (rollar ega/administrator/menejer/omborchi/kassir × filial A/B/D ×
do'kon T/U, HAQIQIY seed rollari, marshrutdagi AYNAN ulangan darvozalar orqali):
  · ro'yxat JIMGINA `visible_branches` ga toraytiriladi; aniq `branch_id` ko'rinmasa yoki
    begona bo'lsa — begona tenant bilan AYNI 404; `mine=true` O'ZGARMAGAN (actor_branch);
  · PATCH/DELETE ko'rinmaydigan filial kassasiga — begona bilan AYNI 404, qator o'zgarmaydi;
  · POST ko'rinmaydigan filialga — 403 (idempotent qaytarish ham oshkor qilmaydi), begona
    tenant / o'chirilgan filial — avvalgidek 400;
  · `/cash-setup` faqat ko'rinadigan filiallar va holat shu filiallar bo'yicha;
  · arxiv semantikasi (`active_only` standartlari: tills False, safes True) O'ZGARMAGAN;
  · filialga biriktirilmagan xodim — butun do'kon (moslik tanlovi, `visible_branches`).

Kutilgan qiymatlar endpointdan EMAS, seed rejasidan (mustaqil oracle) hisoblanadi.
Maqsad-baza: `test_check_defs_pg.pg_target` (har test alohida baza; CI'da `-k external`).
Endpoint funksiyasi sessiya bilan TO'G'RIDAN chaqiriladi — `test_sales_read_pg` naqshi.
"""
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_products_tracked_scope import NOW, _dokon
from tests.test_sales_read_pg import _xodim

READ_PERMS = ("kassa.sell", "kassa.view", "sozlamalar.view", "sozlamalar.edit", "hisobot.view")
GATE_403 = "Ruxsat yo'q: " + " / ".join(READ_PERMS)
EDIT_403 = "Ruxsat yo'q: sozlamalar.edit"
FIL_404 = "Filial topilmadi"
FIL_400 = "Filial topilmadi"
FIL_403 = "Ruxsat yo'q: bu filial sizga biriktirilmagan"
TILL_404 = "Kassa (TILL) topilmadi"

# (rol, biriktirilgan filial) — kalit `rol@filial`. D — O'CHIRILGAN filial (`_dokon`).
XODIMLAR = (("ega", None), ("administrator", "A"), ("administrator", None), ("menejer", "A"),
            ("menejer", "B"), ("menejer", None), ("omborchi", "A"), ("kassir", "A"),
            ("kassir", "B"), ("kassir", None), ("kassir", "D"))
BEGONA = (("ega", None), ("administrator", "A"))
FILIALLAR = ("A", "B", "D")


# ══ YORDAMCHILAR ═══════════════════════════════════════════════════════════

def _baza(url):
    _initdb(url)
    eng = create_engine(url)
    return eng, sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def _doira(kalit):
    """Kutilgan KO'RISH doirasi — `visible_branches` ning mustaqil nusxasi: ega va filialga
    biriktirilmagan xodim — butun do'kon (None), aks holda biriktirilgan filial."""
    rol, f = kalit.split("@")
    return None if rol == "ega" or f == "-" else {f}


def _yozuv_filiali(kalit):
    """Kutilgan `actor_branch` — biriktirilgan FAOL filial, aks holda eng eski faol filial (A).
    D o'chirilgan: unga biriktirilgan kassir YOZUVNI A ga qiladi."""
    f = kalit.split("@")[1]
    return f if f in ("A", "B") else "A"


def _hisob(s, d, filial, tur, kod, holat, tartib):
    from app.models.cash import CashAccount
    from app.services.cash import till_identity as ti
    a = CashAccount(id=uuid.uuid4(), tenant_id=d["cid"], branch_id=d["fil"][filial], type=tur,
                    currency="UZS", status=holat,
                    label=(ti.till_label(kod, None) if tur == "TILL" else ti.safe_label(kod)),
                    created_at=NOW - timedelta(hours=1) + timedelta(seconds=tartib))
    s.add(a)
    s.flush()
    return str(a.id)


def _muhit(S, *, b_faol_kassa=True):
    """T (asosiy) va U (begona) do'konlar, kassa/seyflar va xodimlar. Qaytaradi (t, u, hisob)."""
    from app.models.org import Branch
    s = S()
    try:
        t = _dokon(s, "T", (), xodimlar=XODIMLAR)
        u = _dokon(s, "U", (), xodimlar=BEGONA)
        # Filial yoshi ANIQ: `actor_branch` eng eski FAOL filialni tanlaydi, `_dokon` filiallari
        # esa bitta tranzaksiyada (server now()) — teng created_at bilan tanlov tasodifiy bo'lardi.
        for d in (t, u):
            for i, k in enumerate(FILIALLAR):
                s.get(Branch, d["fil"][k]).created_at = NOW - timedelta(days=30 - i)
        s.flush()
        reja = [(t, "A", "TILL", "TA-1", "ACTIVE"), (t, "A", "TILL", "TA-OLD", "ARCHIVED"),
                (t, "A", "SAFE", "SA-1", "ACTIVE"), (t, "A", "SAFE", "SA-OLD", "ARCHIVED"),
                (t, "B", "TILL", "TB-1", "ACTIVE" if b_faol_kassa else "ARCHIVED"),
                (t, "B", "TILL", "TB-OLD", "ARCHIVED"), (t, "B", "SAFE", "SB-1", "ACTIVE"),
                (t, "D", "TILL", "TD-1", "ACTIVE"), (t, "D", "SAFE", "SD-1", "ACTIVE"),
                (u, "A", "TILL", "UA-1", "ACTIVE"), (u, "A", "SAFE", "USA-1", "ACTIVE")]
        hisob = {}
        # Kiritish tartibi created_at ga TESKARI: ro'yxat tartibi heap'dan emas, ORDER BY dan
        # kelishi ham shu bilan isbotlanadi.
        for i, (d, f, tur, kod, holat) in reversed(list(enumerate(reja))):
            hisob[kod] = {"id": _hisob(s, d, f, tur, kod, holat, i), "cid": d["cid"], "fil": f,
                          "tur": tur, "holat": holat, "tartib": i}
        s.commit()
    finally:
        s.close()
    return t, u, hisob


def _kutilgan(hisob, d, tur, filiallar, active_only):
    """Kutilgan ro'yxat (id'lar, created_at tartibida) — seed rejasidan, endpointsiz."""
    rows = [h for h in hisob.values() if h["cid"] == d["cid"] and h["tur"] == tur
            and (filiallar is None or h["fil"] in filiallar)
            and (not active_only or h["holat"] == "ACTIVE")]
    return [h["id"] for h in sorted(rows, key=lambda h: h["tartib"])]


def _ids(body):
    return [r["id"] for r in body]


def _darvozalar(endpoint):
    """Marshrut dependency daraxtidagi `require`/`require_any` tekshiruvchilari — AYNAN
    endpointga ulanganlari: darvoza marshrutdan olib tashlansa, bu fayl ham qizaradi."""
    from fastapi.routing import APIRoute

    from app.api.v1.tills import router
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
    tartibi): (status, javob yoki detail)."""
    from app.api.v1 import tills as TL
    from app.models.auth import Employee
    s = S()
    try:
        emp = s.get(Employee, emp_id)
        endpoint = getattr(TL, fn)
        try:
            for darvoza in _darvozalar(endpoint):
                darvoza(emp=emp, db=s)
            return 200, endpoint(**kw, emp=emp, db=s)
        except HTTPException as e:
            return e.status_code, e.detail
    finally:
        s.rollback()
        s.close()


def _qator(S, hid):
    """Hisob qatorining (status, label) holati yoki None — endpointdan mustaqil o'qish."""
    from app.models.cash import CashAccount
    s = S()
    try:
        a = s.get(CashAccount, uuid.UUID(hid))
        return None if a is None else (a.status, a.label)
    finally:
        s.close()


def _soni(S, cid, bid):
    from app.models.cash import CashAccount
    s = S()
    try:
        return s.scalar(select(func.count()).select_from(CashAccount).where(
            CashAccount.tenant_id == cid, CashAccount.branch_id == bid))
    finally:
        s.close()


# ══ TESTLAR ════════════════════════════════════════════════════════════════

def test_PG_ROYXAT_tills_safes_ROL_x_FILIAL_x_DOKON_doirasi(pg_target):
    """Ro'yxat, `active_only` standartlari, aniq `branch_id`, `mine` — har aktor uchun
    oracle bilan."""
    eng, S = _baza(pg_target)
    try:
        t, u, h = _muhit(S)
        aktorlar = [(t, k) for k in t["x"]] + [(u, k) for k in u["x"]]
        tekshirildi = 0
        for d, kalit in aktorlar:
            eid, doira = d["x"][kalit]["id"], _doira(kalit)
            for fn, tur, standart in (("list_tills", "TILL", False), ("list_safes", "SAFE", True)):
                if kalit.startswith("omborchi"):
                    # Darvoza BIRINCHI: aniq (hatto begona) filial so'ralsa ham javob farq qilmaydi.
                    for kw in ({}, {"mine": True}, {"branch_id": d["fil"]["A"]},
                               {"branch_id": u["fil"]["A"]}):
                        assert _chaqir(S, eid, fn, **kw) == (403, GATE_403), (kalit, fn, kw)
                    continue

                # 1) Doira bo'yicha ro'yxat; arxiv semantikasi O'ZGARMAGAN (standart active_only).
                for kw in ({}, {"active_only": True}, {"active_only": False}):
                    st, body = _chaqir(S, eid, fn, **kw)
                    ao = kw.get("active_only", standart)
                    assert st == 200, (kalit, fn, kw, body)
                    assert _ids(body) == _kutilgan(h, d, tur, doira, ao), (kalit, fn, kw)
                    assert {r["type"] for r in body} <= {tur}
                    assert all(r["active"] == (r["status"] == "ACTIVE") for r in body)
                    tekshirildi += 1

                # 2) Aniq branch_id: ko'rinadigan -> shu filial; ko'rinmaydigan / begona / yo'q ->
                #    AYNI 404 (javob farqi filial mavjudligini oshkor qilmaydi).
                for d2 in (t, u):
                    for fk in FILIALLAR:
                        korinadi = d2 is d and (doira is None or fk in doira)
                        # aniq branch_id `mine` dan USTUN (avvalgidek)
                        for mine in (False, True):
                            st, body = _chaqir(S, eid, fn, branch_id=d2["fil"][fk],
                                               active_only=False, mine=mine)
                            if korinadi:
                                assert st == 200, (kalit, fn, fk, body)
                                assert _ids(body) == _kutilgan(h, d, tur, {fk}, False), (kalit, fk)
                            else:
                                assert (st, body) == (404, FIL_404), (kalit, fn, d2 is d, fk)
                            tekshirildi += 1
                assert _chaqir(S, eid, fn, branch_id=uuid.uuid4()) == (404, FIL_404)

                # 3) mine=true O'ZGARMAGAN: AYNAN actor_branch (smena/savdo yozuv filiali).
                #    kassir@D: biriktirilgan filial o'chirilgan -> yozuv A ga tushadi, POS kassa
                #    ro'yxati ham A niki (aks holda smena ocholmasdi) — garchi `?branch_id=A`
                #    unga 404 bo'lsa ham (u A ni "ko'rmaydi", faqat unga yozadi).
                st, body = _chaqir(S, eid, fn, mine=True, active_only=True)
                assert st == 200, (kalit, fn, body)
                kut = _kutilgan(h, d, tur, {_yozuv_filiali(kalit)}, True)
                assert _ids(body) == kut, (kalit, fn)
                tekshirildi += 1
        assert tekshirildi == 12 * 2 * 16, tekshirildi   # 12 ruxsatli aktor x 2 tur x 16 so'rov

        # Aniq misollar (oracle'dan tashqari, o'qiladigan dalil):
        x = t["x"]
        st, body = _chaqir(S, x["kassir@A"]["id"], "list_tills")
        assert st == 200 and {r["code"] for r in body} == {"TA-1", "TA-OLD"}
        st, body = _chaqir(S, x["kassir@-"]["id"], "list_tills")         # biriktirilmagan — hammasi
        assert st == 200
        assert {r["code"] for r in body} == {"TA-1", "TA-OLD", "TB-1", "TB-OLD", "TD-1"}
        st, body = _chaqir(S, x["administrator@A"]["id"], "list_safes")
        assert st == 200 and [r["code"] for r in body] == ["SA-1"]   # safes: standart active_only
        st, body = _chaqir(S, x["kassir@D"]["id"], "list_tills")
        assert st == 200 and [r["code"] for r in body] == ["TD-1"]
        st, body = _chaqir(S, x["kassir@D"]["id"], "list_tills", mine=True, active_only=True)
        assert st == 200 and [r["code"] for r in body] == ["TA-1"]
        st, body = _chaqir(S, u["x"]["ega@-"]["id"], "list_tills")
        assert st == 200 and [r["code"] for r in body] == ["UA-1"]   # begona do'kon izolyatsiyasi
    finally:
        eng.dispose()


def test_PG_DARVOZA_oqish_ruxsatlari_override_va_yozuv_darvozasi(pg_target):
    """O'qish darvozasi AYNAN 5 ruxsat (har biri yetarli), override ham hisobga olinadi;
    FULL_ACCESS istisnosi; yozuv darvozasi (sozlamalar.edit) o'zgarmagan; /cash-setup ochiq."""
    from app.api.v1 import tills as TL
    assert TL.TILL_READ_PERMS == READ_PERMS
    for fn in ("list_tills", "list_safes"):
        assert len(_darvozalar(getattr(TL, fn))) == 1, fn
    for fn in ("create_till", "create_safe", "update_till", "delete_till"):
        assert len(_darvozalar(getattr(TL, fn))) == 1, fn
    assert _darvozalar(TL.cash_setup_state) == []           # o'zgarmagan: faqat autentifikatsiya

    eng, S = _baza(pg_target)
    try:
        t, u, h = _muhit(S)
        s = S()
        try:
            ov = {f"omborchi@A+{c}": _xodim(s, t, "omborchi", "A", {c: True}) for c in READ_PERMS}
            ov["kassir@A-kassa"] = _xodim(s, t, "kassir", "A", {"kassa.sell": False,
                                                                 "kassa.view": False})
            ov["kassir@--kassa"] = _xodim(s, t, "kassir", None, {"kassa.sell": False,
                                                                  "kassa.view": False})
            ov["menejer@--sozl-hisobot"] = _xodim(s, t, "menejer", None,
                                                  {"sozlamalar.view": False, "hisobot.view": False})
            ov["administrator@A-hammasi"] = _xodim(s, t, "administrator", "A",
                                                   {c: False for c in READ_PERMS})
            s.commit()
        finally:
            s.close()

        # (kalit, ruxsat bormi, doira)
        holatlar = [(k, True, {"A"}) for k in ov if k.startswith("omborchi@A+")] + [
            ("kassir@A-kassa", False, None), ("kassir@--kassa", False, None),
            ("menejer@--sozl-hisobot", False, None),
            # FULL_ACCESS: override darvozani yopmaydi (`has_any` istisnosi)
            ("administrator@A-hammasi", True, {"A"})]
        for kalit, ruxsat, doira in holatlar:
            for fn, tur, standart in (("list_tills", "TILL", False), ("list_safes", "SAFE", True)):
                st, body = _chaqir(S, ov[kalit], fn)
                if not ruxsat:
                    assert (st, body) == (403, GATE_403), (kalit, fn)
                    # Darvoza filial tekshiruvidan OLDIN: begona/yo'q filial ham AYNI 403.
                    assert _chaqir(S, ov[kalit], fn, branch_id=u["fil"]["A"]) == (403, GATE_403)
                    continue
                assert st == 200, (kalit, fn, body)
                assert _ids(body) == _kutilgan(h, t, tur, doira, standart), (kalit, fn)
                assert _chaqir(S, ov[kalit], fn, branch_id=t["fil"]["B"]) == (404, FIL_404)

        # Yozuv darvozasi O'ZGARMAGAN: o'qish ruxsati (hatto sozlamalar.view) yozishga yetmaydi.
        till_a = uuid.UUID(h["TA-1"]["id"])
        for eid in (t["x"]["menejer@A"]["id"], t["x"]["kassir@A"]["id"], t["x"]["omborchi@A"]["id"],
                    ov["omborchi@A+sozlamalar.view"]):
            yangi_kassa = TL.TillCreate(branch_id=t["fil"]["A"], code="X-1")
            yangi_seyf = TL.SafeCreate(branch_id=t["fil"]["A"], code="XS-1")
            assert _chaqir(S, eid, "create_till", data=yangi_kassa) == (403, EDIT_403)
            assert _chaqir(S, eid, "create_safe", data=yangi_seyf) == (403, EDIT_403)
            assert _chaqir(S, eid, "update_till", till_id=till_a,
                           data=TL.TillUpdate(active=False)) == (403, EDIT_403)
            assert _chaqir(S, eid, "delete_till", till_id=till_a) == (403, EDIT_403)
        assert _qator(S, h["TA-1"]["id"]) == ("ACTIVE", "TILL code=TA-1 terminal=NONE")
        assert _soni(S, t["cid"], t["fil"]["A"]) == 4

        # /cash-setup ruxsatsiz (avvalgidek), lekin DOIRALANGAN: omborchi@A faqat A ni ko'radi.
        st, body = _chaqir(S, t["x"]["omborchi@A"]["id"], "cash_setup_state")
        assert st == 200 and [b["branch_id"] for b in body["branches"]] == [str(t["fil"]["A"])]
    finally:
        eng.dispose()


def test_PG_PATCH_DELETE_korinmas_filial_404_begona_bilan_AYNI(pg_target):
    from app.api.v1 import tills as TL
    eng, S = _baza(pg_target)
    try:
        t, u, h = _muhit(S)
        x = t["x"]
        adm_a = x["administrator@A"]["id"]

        # Ko'rinmaydigan filial (B, o'chirilgan D), begona do'kon va mavjud bo'lmagan id —
        # AYNI (404, matn); qator O'ZGARMAYDI va o'chirilmaydi.
        nishonlar = [h["TB-1"]["id"], h["TB-OLD"]["id"], h["TD-1"]["id"], h["UA-1"]["id"],
                     str(uuid.uuid4())]
        oldin = {n: _qator(S, n) for n in nishonlar}
        for n in nishonlar:
            tid = uuid.UUID(n)
            for data in (TL.TillUpdate(active=False), TL.TillUpdate(active=True),
                         TL.TillUpdate(code="HACK-1")):
                st, body = _chaqir(S, adm_a, "update_till", till_id=tid, data=data)
                assert (st, body) == (404, TILL_404), n
            assert _chaqir(S, adm_a, "delete_till", till_id=tid) == (404, TILL_404), n
            # Begona do'kon egasi T kassasiga ham AYNI javob (tenant izolyatsiyasi o'zgarmagan).
            if n != h["UA-1"]["id"]:
                st, body = _chaqir(S, u["x"]["ega@-"]["id"], "delete_till", till_id=tid)
                assert (st, body) == (404, TILL_404), n
        assert {n: _qator(S, n) for n in nishonlar} == oldin
        assert oldin[h["TB-1"]["id"]] == ("ACTIVE", "TILL code=TB-1 terminal=NONE")

        # Seyf PATCH/DELETE marshruti yo'q: SAFE id si /tills orqali — tur farqi 404 (o'zgarmagan).
        seyf = uuid.UUID(h["SA-1"]["id"])
        assert _chaqir(S, adm_a, "delete_till", till_id=seyf) == (404, TILL_404)

        # O'z filiali (A) — administrator@A uchun hammasi ishlaydi.
        ta = uuid.UUID(h["TA-1"]["id"])
        st, body = _chaqir(S, adm_a, "update_till", till_id=ta, data=TL.TillUpdate(code="TA-MAIN"))
        assert st == 200 and body["code"] == "TA-MAIN", body
        st, body = _chaqir(S, adm_a, "update_till", till_id=ta, data=TL.TillUpdate(active=False))
        assert st == 200 and body["status"] == "ARCHIVED" and body["active"] is False, body
        st, body = _chaqir(S, adm_a, "update_till", till_id=ta, data=TL.TillUpdate(active=True))
        assert st == 200 and body["status"] == "ACTIVE", body
        # Rename noyobligi FILIAL doirasida: B dagi "TB-1" kodi A da band emas.
        st, body = _chaqir(S, adm_a, "update_till", till_id=ta, data=TL.TillUpdate(code="TB-1"))
        assert st == 200 and body["code"] == "TB-1", body
        st, body = _chaqir(S, adm_a, "delete_till", till_id=uuid.UUID(h["TA-OLD"]["id"]))
        assert (st, body) == (200, {"ok": True, "deleted": h["TA-OLD"]["id"]})
        assert _qator(S, h["TA-OLD"]["id"]) is None

        # Cheklovsiz aktorlar (ega, biriktirilmagan administrator) boshqa filialda ham ishlaydi.
        st, body = _chaqir(S, x["ega@-"]["id"], "update_till", till_id=uuid.UUID(h["TB-1"]["id"]),
                           data=TL.TillUpdate(active=False))
        assert st == 200 and body["status"] == "ARCHIVED", body
        st, body = _chaqir(S, x["administrator@-"]["id"], "update_till",
                           till_id=uuid.UUID(h["TD-1"]["id"]), data=TL.TillUpdate(code="TD-X"))
        assert st == 200 and body["code"] == "TD-X", body
        st, body = _chaqir(S, x["administrator@-"]["id"], "delete_till",
                           till_id=uuid.UUID(h["TB-OLD"]["id"]))
        assert st == 200 and _qator(S, h["TB-OLD"]["id"]) is None, body
        # Begona do'kon administratori o'z kassasini boshqaradi, T nikini emas.
        assert _chaqir(S, u["x"]["administrator@A"]["id"], "update_till",
                       till_id=uuid.UUID(h["TB-1"]["id"]),
                       data=TL.TillUpdate(active=True)) == (404, TILL_404)
        st, body = _chaqir(S, u["x"]["administrator@A"]["id"], "update_till",
                           till_id=uuid.UUID(h["UA-1"]["id"]), data=TL.TillUpdate(active=False))
        assert st == 200 and body["status"] == "ARCHIVED", body
    finally:
        eng.dispose()


def test_PG_POST_korinmas_filial_403_begona_va_ochirilgan_400(pg_target):
    from app.api.v1 import tills as TL
    eng, S = _baza(pg_target)
    try:
        t, u, h = _muhit(S)
        x = t["x"]
        adm_a = x["administrator@A"]["id"]
        fa, fb, fd = t["fil"]["A"], t["fil"]["B"], t["fil"]["D"]
        b_oldin = _soni(S, t["cid"], fb)

        # Ko'rinmaydigan (lekin o'z do'konidagi) filial -> 403, qator YARATILMAYDI.
        # "TB-1" — B da MAVJUD: idempotent yo'l ham (mavjud kassani qaytarib) oshkor qilmaydi.
        for code in ("NEW-B", "TB-1"):
            assert _chaqir(S, adm_a, "create_till",
                           data=TL.TillCreate(branch_id=fb, code=code)) == (403, FIL_403), code
        for code in ("SAFE-B2", "SB-1"):
            assert _chaqir(S, adm_a, "create_safe",
                           data=TL.SafeCreate(branch_id=fb, code=code)) == (403, FIL_403), code
        assert _soni(S, t["cid"], fb) == b_oldin

        # Begona do'kon filiali, o'chirilgan filial, mavjud bo'lmagan id -> avvalgidek 400.
        # Tenant tekshiruvi doiradan OLDIN: begona filialga 403 berilsa, u mavjudligini tasdiqlardi.
        for eid in (adm_a, x["ega@-"]["id"], x["administrator@-"]["id"]):
            for bid in (u["fil"]["A"], fd, uuid.uuid4()):
                assert _chaqir(S, eid, "create_till",
                               data=TL.TillCreate(branch_id=bid, code="Z-1")) == (400, FIL_400)
                assert _chaqir(S, eid, "create_safe",
                               data=TL.SafeCreate(branch_id=bid, code="ZS-1")) == (400, FIL_400)
        assert _soni(S, u["cid"], u["fil"]["A"]) == 2 and _soni(S, t["cid"], fd) == 2

        # O'z filiali: yaratiladi va IDEMPOTENT (avvalgidek).
        st, a1 = _chaqir(S, adm_a, "create_till", data=TL.TillCreate(branch_id=fa, code="TA-2"))
        assert st == 200 and a1["branch_id"] == str(fa) and a1["code"] == "TA-2", a1
        st, a2 = _chaqir(S, adm_a, "create_till", data=TL.TillCreate(branch_id=fa, code="TA-2"))
        assert st == 200 and a2["id"] == a1["id"]
        st, s1 = _chaqir(S, adm_a, "create_safe", data=TL.SafeCreate(branch_id=fa, code="SA-2"))
        assert st == 200 and s1["branch_id"] == str(fa) and s1["type"] == "SAFE", s1
        st, body = _chaqir(S, adm_a, "list_tills", branch_id=fa, active_only=True)
        assert st == 200 and a1["id"] in _ids(body)

        # Cheklovsiz aktorlar istalgan (o'z do'koni) filialiga yaratadi.
        st, b1 = _chaqir(S, x["ega@-"]["id"], "create_till",
                         data=TL.TillCreate(branch_id=fb, code="NEW-B"))
        assert st == 200 and b1["branch_id"] == str(fb), b1
        st, b2 = _chaqir(S, x["administrator@-"]["id"], "create_safe",
                         data=TL.SafeCreate(branch_id=fb, code="SAFE-B2"))
        assert st == 200 and b2["branch_id"] == str(fb), b2
        assert _soni(S, t["cid"], fb) == b_oldin + 2
        # Endi mavjud bo'lsa ham administrator@A uchun B hamon 403 (idempotent qaytarish emas).
        assert _chaqir(S, adm_a, "create_till",
                       data=TL.TillCreate(branch_id=fb, code="NEW-B")) == (403, FIL_403)
    finally:
        eng.dispose()


def test_PG_CASH_SETUP_faqat_korinadigan_filiallar_va_holat(pg_target):
    """`/cash-setup` qatorlari va umumiy holat ko'rish doirasi bo'yicha; Kassalar ekrani oqimi
    (har qator uchun `/tills?branch_id=` va `/safes?branch_id=&active_only=false`) 404 bermaydi."""
    from app.models.cash import CashAccount
    from app.models.org import Branch
    from app.services.cash import till_identity as ti
    eng, S = _baza(pg_target)
    try:
        t, u, h = _muhit(S, b_faol_kassa=False)          # B: faol kassa YO'Q, faqat seyf
        s = S()
        try:
            # Nofaol C filial (ACTIVE kassasi bilan): cash-setup'da avvalgidek ko'rinmaydi.
            c = Branch(id=uuid.uuid4(), company_id=t["cid"], code="F-C", name="Filial C",
                       timezone="Asia/Tashkent", is_active=False,
                       created_at=NOW - timedelta(days=5))
            s.add(c)
            s.flush()
            s.add(CashAccount(id=uuid.uuid4(), tenant_id=t["cid"], branch_id=c.id, type="TILL",
                              currency="UZS", status="ACTIVE", label=ti.till_label("TC-1", None),
                              created_at=NOW))
            s.commit()
        finally:
            s.close()

        fa, fb = str(t["fil"]["A"]), str(t["fil"]["B"])
        # kalit -> (kutilgan filiallar tartibda, umumiy holat, tugallanganmi)
        kutilgan = {
            "ega@-": ([fa, fb], "CASH_SETUP_REQUIRED", False),
            "administrator@-": ([fa, fb], "CASH_SETUP_REQUIRED", False),
            "menejer@-": ([fa, fb], "CASH_SETUP_REQUIRED", False),
            "kassir@-": ([fa, fb], "CASH_SETUP_REQUIRED", False),
            "administrator@A": ([fa], "POS_READY", True),
            "menejer@A": ([fa], "POS_READY", True),
            "kassir@A": ([fa], "POS_READY", True),
            "omborchi@A": ([fa], "POS_READY", True),
            "menejer@B": ([fb], "CASH_SETUP_REQUIRED", False),
            "kassir@B": ([fb], "CASH_SETUP_REQUIRED", False),
            # Faqat o'chirilgan filialga biriktirilgan: ko'rinadigan FAOL filial yo'q.
            "kassir@D": ([], "COMPANY_CREATED", False),
        }
        assert set(kutilgan) == set(t["x"])
        sonlar = {fa: (1, 1), fb: (0, 1)}                  # (faol kassa, faol seyf)
        for kalit, (fil, holat, tayyor) in kutilgan.items():
            eid = t["x"][kalit]["id"]
            st, body = _chaqir(S, eid, "cash_setup_state")
            assert st == 200, (kalit, body)
            assert [b["branch_id"] for b in body["branches"]] == fil, (kalit, body["branches"])
            assert (body["state"], body["cash_setup_complete"]) == (holat, tayyor), kalit
            assert body["ledger_native"] is False
            for b in body["branches"]:
                assert (b["active_tills"], b["active_safes"]) == sonlar[b["branch_id"]], (kalit, b)
                assert b["can_open_cash_shift"] is (b["active_tills"] > 0)
                assert b["collection_available"] is True
                if kalit.startswith("omborchi"):
                    continue                              # o'qish darvozasi (alohida testda)
                # Kassalar.tsx oqimi: cash-setup qatori -> filial so'rovi HECH QACHON 404 emas.
                for fn, kw in (("list_tills", {}), ("list_safes", {"active_only": False})):
                    st2, rows = _chaqir(S, eid, fn, branch_id=uuid.UUID(b["branch_id"]), **kw)
                    assert st2 == 200 and {r["branch_id"] for r in rows} <= {b["branch_id"]}, \
                        (kalit, fn, rows)

        # Begona do'kon: faqat o'z filiallari (U.B da kassa yo'q -> ega uchun sozlash kerak,
        # A ga biriktirilgan administrator uchun esa tayyor).
        st, body = _chaqir(S, u["x"]["ega@-"]["id"], "cash_setup_state")
        assert st == 200 and [b["branch_id"] for b in body["branches"]] == \
            [str(u["fil"]["A"]), str(u["fil"]["B"])]
        assert (body["state"], body["cash_setup_complete"]) == ("CASH_SETUP_REQUIRED", False)
        st, body = _chaqir(S, u["x"]["administrator@A"]["id"], "cash_setup_state")
        assert st == 200 and [b["branch_id"] for b in body["branches"]] == [str(u["fil"]["A"])]
        assert (body["state"], body["cash_setup_complete"]) == ("POS_READY", True)

        # Nofaol C ning kassasi ro'yxatda avvalgidek (faqat cash-setup nofaolni yashiradi).
        st, body = _chaqir(S, t["x"]["ega@-"]["id"], "list_tills", active_only=True)
        assert st == 200 and "TC-1" in {r["code"] for r in body}
    finally:
        eng.dispose()
