# -*- coding: utf-8 -*-
"""XODIM TOKEN'I VENDOR SIRTIGA YETIB BORMASIN — dalil bo'shlig'ini yopadi.

NEGA BU FAYL BOR (o'lchangan bo'shliq, taxmin emas)
===================================================
`require_vendor` (`app/api/v1/admin.py:251`) 10 ta cross-tenant marshrutni
qo'riqlaydi, lekin repoda uning xodim token'ini RAD ETISHINI tekshiradigan
birorta test YO'Q edi. Mavjud qamrov faqat KALIT bo'yicha
(`tests/test_security.py:58-60`: noto'g'ri kalit -> 401, to'g'ri kalit -> 200).
`docs/PHASE_6A_PLAN.md:81` bu qulfni va'da qilgan — kodda bor, testda yo'q edi.

Himoya MEXANIK, bahsli emas: `require_vendor` parametr ro'yxati
(`admin.py:252-255`) `Request`, `db`, `X-Vendor-Key`, `X-Vendor-Session` dan
iborat — unda `authorization` parametri ham, `Depends(get_current_employee)`
ham YO'Q. `get_current_employee` (`app/core/deps.py:12-45`) esa FAQAT
`authorization` ni o'qiydi. Ya'ni ikki dependency KIRISHI bo'yicha AJRALGAN va
Bearer token `admin.py:284` ga tushib 401 oladi.

⚠️  NEGA RUXSAT KODLARI BU YERDA YARAMAYDI. `require(...)` (`deps.py:121-135`)
    `FULL_ACCESS_ROLES = ("ega", "administrator")` uchun erta qaytadi, ya'ni
    do'kon egasi HAR QANDAY ruxsatdan o'tadi. Shu bois test ataylab eng yuqori
    huquqli token — `ega` — bilan ishlaydi: pastroq rol bilan o'tsa, test hech
    narsa isbotlamagan bo'lardi.

⚠️  YOPIQ DUNYO. Marshrutlar ro'yxati QO'LDA yozilmaydi — FastAPI ilovasining
    dependency daraxtidan O'QILADI. Shunda yangi vendor marshruti qo'shilsa u
    AVTOMATIK shu testga tushadi va qamrov bayonoti jimgina eskirmaydi.
"""
import uuid

import pytest

from app.api.v1.admin import require_vendor

#  Yo'l shablonidagi parametrlar o'rniga qo'yiladigan MAVJUD BO'LMAGAN id'lar.
#  ⚠️  NEGA mavjud bo'lmagan: agar kelajakda regressiya tufayli auth O'TIB
#      ketsa, `DELETE /admin/companies/{id}` seans bazasidagi haqiqiy do'konni
#      o'chirib yuborardi. Yo'q id bilan eng yomon holat ham 404.
_YOQ = {
    "company_id": "11111111-2222-3333-4444-555555555555",
}

#  Tana TALAB QILADIGAN marshrutlarga minimal tana beriladi.
#  ⚠️  O'LCHANGAN: bu ilovada dependency'lar tana validatsiyasidan OLDIN
#      ishlaydi — `POST /admin/companies` ga `{}` yuborilsa ham 422 emas, 401
#      qaytadi. Tanalar shunga qaramay beriladi: tartib o'zgarsa test
#      422 ni 401 deb o'tkazib yubormasligi uchun.
_TANA = {
    ("POST", "/api/v1/admin/companies"): {},
    ("POST", "/api/v1/admin/reset-password"): {},
    ("PATCH", "/api/v1/admin/companies/{company_id}/plan"): {"plan": "basic"},
    ("PATCH", "/api/v1/admin/companies/{company_id}/suspend"): {"suspended": True},
    ("POST", "/api/v1/admin/companies/{company_id}/seed-demo"): {},
    ("POST", "/api/v1/catalog/v2/reset/execute"): {},
}


def _vendor_qoriqlaydimi(dependant) -> bool:
    """`require_vendor` shu marshrutning dependency daraxtida bormi."""
    yigma = [dependant]
    while yigma:
        d = yigma.pop()
        if getattr(d, "call", None) is require_vendor:
            return True
        yigma.extend(getattr(d, "dependencies", []) or [])
    return False


def _yur(routes, prefix: str, out: list) -> None:
    """`app.routes` daraxtidan to'liq yo'llarni yig'adi.

    ⚠️  `app.routes` TEKIS EMAS — o'lchangan: to'liq import qilingan ilovada u
        7 element beradi, ulardan biri `_IncludedRouter`. FastAPI
        `include_router` ni DANGASA saqlaydi va marshrut obyektidagi `path`
        ichki, PREFIKSSIZ bo'ladi (`/api/v1/admin/overview` o'rniga
        `/overview`). Prefiks shu bois daraxtdan yig'iladi.

        Bu uyning tasdiqlangan naqshi: `app/core/subscription_gate.py:69-76`
        (`_walk`) va `tests/test_mobile_permission_matrix.py` ayni usulni
        ishlatadi. O'z introspeksiyasini yozish JIMGINA bo'sh ro'yxat berardi.
    """
    from fastapi.routing import APIRoute
    for r in routes:
        if isinstance(r, APIRoute):
            if not _vendor_qoriqlaydimi(r.dependant):
                continue
            for m in sorted(r.methods or []):
                if m in {"HEAD", "OPTIONS"}:
                    continue
                out.append((m, prefix + r.path))
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            _yur(r.original_router.routes,
                 prefix + (r.include_context.prefix or ""), out)


def _vendor_marshrutlari():
    """Ilovadan `require_vendor` bilan qo'riqlangan HAR bir marshrutni oladi."""
    from app.main import app
    out: list = []
    _yur(app.routes, "", out)
    return sorted(set(out))


MARSHRUTLAR = _vendor_marshrutlari()


def _aniq_yol(shablon: str) -> str:
    yol = shablon
    for nom, qiymat in _YOQ.items():
        yol = yol.replace("{" + nom + "}", qiymat)
    return yol


def _id(m, p):
    return f"{m} {p}"


def test_QAMROV_vendor_marshrutlari_TOPILDI():
    """Introspeksiya haqiqatan marshrut topgan bo'lsin — proba bo'sh bo'lmasin.

    ⚠️  Bu testsiz butun fayl JIMGINA bo'sh o'tardi: `_vendor_marshrutlari()`
        bo'sh ro'yxat qaytarsa, parametrlangan testlar umuman yig'ilmaydi va
        natija «hammasi yashil» bo'lardi.
    """
    assert len(MARSHRUTLAR) >= 10, (
        f"vendor marshrutlari kam topildi: {MARSHRUTLAR} — introspeksiya "
        f"buzilgan bo'lishi mumkin")
    #  Yo'l shablonlarida qoldiq parametr qolmasin (aks holda so'rov 404 bo'lib,
    #  test 401 ni ko'rmasdan o'tib ketardi).
    for _m, p in MARSHRUTLAR:
        qolgan = [s for s in p.split("/") if s.startswith("{")]
        for s in qolgan:
            assert s.strip("{}") in _YOQ, (
                f"{p}: `{s}` uchun _YOQ da qiymat yo'q — yangi parametrli "
                f"vendor marshruti qo'shilgan, ro'yxatni yangilang")


@pytest.mark.parametrize("m,p", MARSHRUTLAR, ids=[_id(*x) for x in MARSHRUTLAR])
def test_XODIM_tokeni_RAD_etiladi(client, admin_headers, m, p):
    """Haqiqiy `ega` Bearer token'i vendor marshrutiga 401 oladi."""
    r = client.request(m, _aniq_yol(p), headers=admin_headers,
                       json=_TANA.get((m, p)))
    assert r.status_code == 401, (
        f"{m} {p}: xodim token'i {r.status_code} oldi (401 kutilgan) — "
        f"vendor sirti tenant token'iga OCHILGAN: {r.text[:200]}")


@pytest.mark.parametrize("m,p", MARSHRUTLAR, ids=[_id(*x) for x in MARSHRUTLAR])
def test_XODIM_tokeni_va_SOXTA_sessiya_RAD_etiladi(client, admin_headers, m, p):
    """Bearer + o'ylab topilgan `X-Vendor-Session` ham 401.

    ⚠️  NEGA ALOHIDA HOLAT. Sessiya imzosi `vendor_admin_key + "|" +
        vendor_totp_secret` (`admin.py:185-191`) bilan qilinadi, ya'ni master
        kalitning O'ZI ham sessiya yasay olmaydi. Bu test o'ylab topilgan
        sessiya qiymati `_session_row` (`admin.py:226-249`) ni chalg'itmasligini
        qadaydi.
    """
    h = dict(admin_headers)
    h["X-Vendor-Session"] = f"{uuid.uuid4()}.{uuid.uuid4()}"
    r = client.request(m, _aniq_yol(p), headers=h, json=_TANA.get((m, p)))
    assert r.status_code == 401, (
        f"{m} {p}: soxta sessiya {r.status_code} oldi (401 kutilgan)")


def test_NAZORAT_xodim_tokeni_HAQIQIY(client, admin_headers):
    """Yuqoridagi 401'lar token YAROQSIZ bo'lgani uchun EMAS.

    ⚠️  BU TESTSIZ YUQORIDAGILAR BO'SH. Agar `admin_headers` buzilgan token
        bersa, hamma joyda 401 chiqib test «o'tardi», lekin hech narsa
        isbotlamagan bo'lardi.
    """
    me = client.get("/api/v1/auth/me", headers=admin_headers)
    assert me.status_code == 200, me.text
    #  Eng yuqori huquqli rol: ruxsat kodlari bilan qo'riqlash YARAMAGANINI
    #  ko'rsatadi (`FULL_ACCESS_ROLES` uni har ruxsatdan o'tkazadi).
    assert me.json().get("role_code") == "ega", me.json()
    assert client.get("/api/v1/products", headers=admin_headers).status_code == 200


def test_NAZORAT_vendor_kaliti_ISHLAYDI(client):
    """Marshrut umuman ishlaydi — 401 marshrut buzilganidan emas."""
    r = client.get("/api/v1/admin/overview",
                   headers={"X-Vendor-Key": "test-vendor-key"})
    assert r.status_code == 200, r.text


def test_require_vendor_AUTHORIZATION_ni_OQIMAYDI():
    """Mexanik isbot: `require_vendor` imzosida `authorization` YO'Q.

    Yuqoridagi HTTP testlari xulqni o'lchaydi; bu esa SABABNI qadaydi. Kimdir
    `require_vendor` ga xodim token'ini o'qiydigan zaxira yo'l qo'shsa (masalan
    «qulay bo'lsin» deb `Authorization` ni ham qabul qilsa), shu test qizil
    bo'ladi — HTTP testlari esa, agar zaxira yo'l ba'zi shartda ishlasa,
    qizil bo'lmasligi mumkin.
    """
    import inspect
    params = set(inspect.signature(require_vendor).parameters)
    assert params == {"request", "db", "x_vendor_key", "x_vendor_session"}, (
        f"require_vendor imzosi o'zgardi: {sorted(params)} — vendor "
        f"autentifikatsiyasiga yangi kirish manbasi qo'shilgan")
