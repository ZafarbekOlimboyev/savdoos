# -*- coding: utf-8 -*-
"""SINTETIK WORKER KONTRAKTI — CI DARVOZASI (Phase 9).

⚠️  NEGA. BinOS Demo Production worker'i har yangi production relizini
    24/7 sinaydi. Lekin 2026-11-07 da O'LCHANDI: worker `6ef666bb` da
    MAVJUD BO'LMAGAN maydonga tayangan edi — `POST /shifts/{id}/close`
    ga `count_source="SIMULATED"` yuborib javobda uni TEKSHIRARDI.
    `count_source` o'sha relizning BUTUN repo'sida 0 fayl, `CloseShift`
    sxemasida faqat `counted_cash` bor va Pydantic `extra="ignore"`
    maydonni JIM tashlaydi. Natija: worker har KUN OXIRIDA smenani yopa
    olmasdi va bu faqat deploydan keyin ma'lum bo'lardi.

    `release.py` ning qobiliyat darvozasi bu sinfni USHLAMAYDI:
    manifestda 8 nom bor, worker esa 11 POST marshrutiga yozadi.
    Shu fayl o'sha bo'shliqni CI'da yopadi.

TEKSHIRILADIGAN SHARTLAR
────────────────────────
 1. MARSHRUT BOR: har e'lon qilingan yo'l + metod OpenAPI'da mavjud.
 2. MAJBURIY MAYDON: server majburiy deb e'lon qilgan HAR maydon
    worker payloadida bor (aks holda worker 422 oladi).
 3. JIM TASHLANMAYDI: worker yuboradigan HAR maydon server sxemasida
    E'LON QILINGAN (aks holda Pydantic uni jimgina tashlaydi — AYNAN
    `count_source` nuqsoni). Ataylab e'tiborsiz qoldiriladigan maydon
    `IGNORED_OK` da SABAB bilan ro'yxatdan o'tadi.
 4. JAVOB MAYDONLARI: worker o'qiydigan maydonlar javob sxemasida bor.
 5. QOBILIYAT MANIFESTI worker talabini qoplaydi.

⚠️  BU TEST BAZAGA YOZMAYDI va tashqi tarmoqqa chiqmaydi — faqat
    OpenAPI sxemasi va `api_capabilities` e'loni bo'yicha ishlaydi.
"""
import pytest

from app.core import api_capabilities

from tests.worker_contract import (IGNORED_OK, REQUEST_SCHEMA_FREEFORM,
                                   REQUIRED_API_LEVEL, REQUIRED_FEATURES,
                                   RESPONSE_SCHEMA_UNDECLARED,
                                   RESPONSE_SCHEMA_UNDECLARED_MAX, WORKER_GETS,
                                   WORKER_POSTS)

PREFIX = "/api/v1"


@pytest.fixture(scope="module")
def spec(client):
    """OpenAPI sxemasi. `APP_ENV=dev` da `/openapi.json` ochiq."""
    r = client.get("/openapi.json")
    assert r.status_code == 200, (
        "OpenAPI yopiq — bu test `APP_ENV=dev` da ishlaydi "
        f"(status {r.status_code})")
    return r.json()


def _yechim(spec: dict, sxema: dict | None) -> dict:
    """`$ref` ni ochadi (bir pog'ona — FastAPI shunday yozadi)."""
    s = sxema or {}
    ref = s.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        nom = ref.split("/")[-1]
        return ((spec.get("components") or {}).get("schemas") or {}).get(nom, {})
    return s


def _mos(shablon: str, aniq: str) -> bool:
    """`/shifts/{shift}/cash` va `/shifts/{shift_id}/cash` MOS keladi."""
    a = shablon.strip("/").split("/")
    b = aniq.strip("/").split("/")
    if len(a) != len(b):
        return False
    return all(
        (x.startswith("{") and y.startswith("{")) or x == y
        for x, y in zip(a, b))


def _top(spec: dict, shablon: str, metod: str) -> tuple[str | None, dict | None]:
    for yol, amallar in (spec.get("paths") or {}).items():
        if not yol.startswith(PREFIX):
            continue
        if _mos(shablon, yol[len(PREFIX):]):
            return yol, (amallar or {}).get(metod)
    return None, None


def _body_sxema(spec: dict, op: dict) -> dict:
    tana = ((op.get("requestBody") or {}).get("content") or {}) \
        .get("application/json") or {}
    return _yechim(spec, tana.get("schema"))


def _javob_sxema(spec: dict, op: dict) -> dict:
    for kod in ("200", "201"):
        javob = (op.get("responses") or {}).get(kod) or {}
        tana = (javob.get("content") or {}).get("application/json") or {}
        s = _yechim(spec, tana.get("schema"))
        if s:
            return s
    return {}


# ════════════════════════════════════════════════════════════════════════
#  1. MARSHRUTLAR MAVJUD
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("c", WORKER_POSTS, ids=lambda c: c["key"])
def test_POST_marshrut_MAVJUD(spec, c):
    yol, op = _top(spec, c["path"], "post")
    assert yol is not None, (
        f"MARSHRUT YO'Q: POST {c['path']} — worker shu yo'lga YOZADI, "
        f"server esa uni e'lon qilmaydi (404 bo'lardi)")
    assert op is not None, f"yo'l bor, POST metodi YO'Q: {yol}"


@pytest.mark.parametrize("c", WORKER_GETS, ids=lambda c: c["key"])
def test_GET_marshrut_MAVJUD(spec, c):
    yol, op = _top(spec, c["path"], "get")
    assert yol is not None, f"MARSHRUT YO'Q: GET {c['path']}"
    assert op is not None, f"yo'l bor, GET metodi YO'Q: {yol}"


# ════════════════════════════════════════════════════════════════════════
#  2. MAJBURIY MAYDONLAR WORKER PAYLOADIDA BOR
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("c", WORKER_POSTS, ids=lambda c: c["key"])
def test_majburiy_maydonlar_YUBORILADI(spec, c):
    _yol, op = _top(spec, c["path"], "post")
    assert op is not None, (
        f"{c['key']}: marshrut yo'q — `test_POST_marshrut_MAVJUD` ham "
        f"qizil bo'ladi; bu yerda SKIP qilmaymiz, chunki CI skip "
        f"darvozasi (`verify_pytest_run.py`) ro'yxatdan tashqari HAR "
        f"skipni qizil deb hisoblaydi va sabab CHALG'ITARDI")
    sxema = _body_sxema(spec, op)
    majburiy = set(sxema.get("required") or [])
    yuborilgan = set(c["sends"])
    yoq = sorted(majburiy - yuborilgan)
    assert not yoq, (
        f"{c['key']}: server MAJBURIY deb e'lon qilgan, worker YUBORMAYDI: "
        f"{yoq} -> worker 422 olardi")


# ════════════════════════════════════════════════════════════════════════
#  3. JIM TASHLANADIGAN MAYDON YO'Q  (`count_source` nuqsoni sinfi)
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("c", WORKER_POSTS, ids=lambda c: c["key"])
def test_yuborilgan_maydon_SXEMADA_ELON_QILINGAN(spec, c):
    """⚠️  ENG MUHIM TEKSHIRUV. Pydantic standarti `extra="ignore"`:
        e'lon qilinmagan maydon JIM TASHLANADI va server 200 qaytaradi.
        Worker esa «yubordim, qabul qilindi» deb O'YLAYDI. Aynan shu
        2026-11-07 da topilgan `count_source` nuqsoni edi.
    """
    _yol, op = _top(spec, c["path"], "post")
    assert op is not None, f"{c['key']}: marshrut yo'q"
    sxema = _body_sxema(spec, op)
    xossalar = set((sxema.get("properties") or {}).keys())
    if not xossalar:
        #  ⚠️  JIM SKIP YO'Q (javob tomonidagi bilan AYNI naqsh).
        assert c["key"] in REQUEST_SCHEMA_FREEFORM, (
            f"{c['key']}: so'rov sxemasi XOSSASIZ (erkin tana) va ro'yxatda "
            f"YO'Q. Erkin tanada worker yuborgan HAR maydon jimgina qabul "
            f"qilinadi, ya'ni `count_source` sinfi TEKSHIRILMAY qoladi. "
            f"Yo sxema e'lon qilinsin, yo `REQUEST_SCHEMA_FREEFORM` ga "
            f"SABAB bilan yozilsin.")
        return
    notanish = sorted(set(c["sends"]) - xossalar - set(IGNORED_OK))
    assert not notanish, (
        f"{c['key']}: worker yuboradi, server sxemasida E'LON QILINMAGAN: "
        f"{notanish}. Pydantic ularni JIM TASHLAYDI (200 qaytaradi), ya'ni "
        f"worker ta'sir bo'ldi deb o'ylaydi. Yo serverga maydon qo'shilsin, "
        f"yo worker uni yubormasin, yo `IGNORED_OK` ga SABAB bilan yozilsin.")


def test_IGNORED_OK_har_biri_SABABLI(spec):
    """Ro'yxatga jim qo'shib qo'yilmasin: har maydonda izoh BO'LSIN."""
    for maydon, sabab in IGNORED_OK.items():
        assert str(sabab).strip(), f"{maydon}: SABAB yozilmagan"


# ════════════════════════════════════════════════════════════════════════
#  4. JAVOB MAYDONLARI
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("c", [c for c in WORKER_POSTS if c["reads"]],
                         ids=lambda c: c["key"])
def test_javob_maydonlari_ELON_QILINGAN(spec, c):
    """⚠️  JIM SKIP YO'Q. Javob sxemasi e'lon qilinmagan marshrut
        `RESPONSE_SCHEMA_UNDECLARED` da ANIQ ro'yxatdan o'tadi; aks holda
        test QIZIL. Ilgari bu yerda `pytest.skip` bor edi va u
        `shift_close` ni (eng kritik marshrutni) JIMGINA tekshiruvsiz
        qoldirardi — ya'ni «50 passed» yashil ko'rinib, javob tomonidagi
        `count_source` sinfi UMUMAN qamralmagan edi.
    """
    _yol, op = _top(spec, c["path"], "post")
    assert op is not None, f"{c['key']}: marshrut yo'q"
    sxema = _javob_sxema(spec, op)
    xossalar = set((sxema.get("properties") or {}).keys())
    if not xossalar:
        assert c["key"] in RESPONSE_SCHEMA_UNDECLARED, (
            f"{c['key']}: javob sxemasi E'LON QILINMAGAN va ro'yxatda ham "
            f"YO'Q. Yo `response_model` qo'shilsin, yo "
            f"`RESPONSE_SCHEMA_UNDECLARED` ga SABAB bilan yozilsin — "
            f"jim tekshiruvsiz qolmasin.")
        return
    yoq = sorted(set(c["reads"]) - xossalar)
    assert not yoq, (
        f"{c['key']}: worker javobdan O'QIYDI, server e'lon qilmaydi: {yoq}")


def test_javob_sxemasi_ELON_QILINMAGANLAR_ANIQ(spec):
    """Ro'yxat AYNAN haqiqatga mos — «abadiy istisno» bo'lib qolmaydi.

    ⚠️  IKKI YO'NALISH: sxemasiz yangi marshrut qo'shilsa ham, mavjud
        marshrutga sxema qo'shilsa ham test QIZIL bo'ladi. Ikkinchisi
        muhim: tuzatilgandan keyin ro'yxat eskirib, kelajakdagi
        regressiyani YASHIRIB qo'yardi.
    """
    haqiqat = set()
    for c in WORKER_POSTS:
        _yol, op = _top(spec, c["path"], "post")
        if op is None:
            continue
        if not (_javob_sxema(spec, op).get("properties") or {}):
            haqiqat.add(c["key"])
    elon = set(RESPONSE_SCHEMA_UNDECLARED)
    assert haqiqat == elon, (
        f"ro'yxat ESKIRGAN. Sxemasiz, lekin ro'yxatda YO'Q: "
        f"{sorted(haqiqat - elon)}. Ro'yxatda, lekin sxemasi BOR "
        f"(olib tashlash kerak): {sorted(elon - haqiqat)}")
    for k, sabab in RESPONSE_SCHEMA_UNDECLARED.items():
        assert str(sabab).strip(), f"{k}: SABAB yozilmagan"


def test_sorov_sxemasi_XOSSASIZLAR_ANIQ(spec):
    """Erkin tanali marshrutlar ro'yxati AYNAN haqiqatga mos."""
    haqiqat = set()
    for c in WORKER_POSTS:
        _yol, op = _top(spec, c["path"], "post")
        if op is None:
            continue
        if not (_body_sxema(spec, op).get("properties") or {}):
            haqiqat.add(c["key"])
    elon = set(REQUEST_SCHEMA_FREEFORM)
    assert haqiqat == elon, (
        f"ro'yxat ESKIRGAN. Xossasiz, ro'yxatda YO'Q: "
        f"{sorted(haqiqat - elon)}. Ro'yxatda, lekin sxemasi BOR: "
        f"{sorted(elon - haqiqat)}")


def test_javob_modeli_qamrovi_YOMONLASHMAYDI():
    """Sxemasiz marshrutlar soni faqat KAMAYISHI mumkin.

    ⚠️  O'LCHANGAN 2026-11-07: 11 worker POST marshrutidan 8 tasida
        javob modeli yo'q. Chegara qo'yilmasa, keyingi marshrutlar ham
        sxemasiz qo'shilib, shartnoma asta-sekin BO'SHASHARDI —
        «qo'lda yuritiladigan ro'yxat» ildiz sababi (R16 auditi).
    """
    assert len(RESPONSE_SCHEMA_UNDECLARED) <= RESPONSE_SCHEMA_UNDECLARED_MAX, (
        f"sxemasiz marshrutlar KO'PAYDI: {len(RESPONSE_SCHEMA_UNDECLARED)} > "
        f"{RESPONSE_SCHEMA_UNDECLARED_MAX}. Yangi marshrutga "
        f"`response_model` e'lon qilinsin.")


# ════════════════════════════════════════════════════════════════════════
#  5. QOBILIYAT MANIFESTI WORKER TALABINI QOPLAYDI
# ════════════════════════════════════════════════════════════════════════
def test_qobiliyat_manifesti_worker_talabini_QOPLAYDI():
    elon = api_capabilities.declaration()
    assert elon["level"] >= REQUIRED_API_LEVEL, (
        f"API darajasi {elon['level']} < worker talabi {REQUIRED_API_LEVEL}")
    yoq = sorted(set(REQUIRED_FEATURES) - set(elon["features"]))
    assert not yoq, (
        f"worker tayanadigan qobiliyat manifestda YO'Q: {yoq} — "
        f"worker fail-closed to'xtardi")


def test_manifest_worker_marshrutlarini_QOPLAMAYDI_halol_cheklov():
    """⚠️  HALOL CHEKLOV YOZIB QO'YILADI, nuqson emas.

    Qobiliyat manifestida 8 nom bor, worker esa 11 POST + 11 GET
    marshrutiga tayanadi. Ya'ni manifest darvozasi ZARUR, lekin KIFOYA
    EMAS — shu fayl aynan shu bo'shliq uchun yozilgan. Kelajakda kimdir
    «manifest yetarli» deb o'ylamasin.
    """
    elon = api_capabilities.declaration()
    jami = len(WORKER_POSTS) + len(WORKER_GETS)
    assert len(elon["features"]) < jami, (
        "manifest endi hamma marshrutni qoplaydi — bu testni va "
        "`release.DEFAULT_REQUIRED_FEATURES` ni qayta ko'rib chiqing")


def test_kritik_marshrutlar_BELGILANGAN():
    """Kontraktda kamida smena/sotuv/naqd kritik deb belgilangan."""
    kritik = {c["key"] for c in WORKER_POSTS if c["critical"]}
    for kerak in ("sale", "shift_open", "shift_close", "shift_cash", "return"):
        assert kerak in kritik, f"{kerak} kritik deb belgilanmagan"
