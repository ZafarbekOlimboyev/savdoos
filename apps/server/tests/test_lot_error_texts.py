# -*- coding: utf-8 -*-
"""PARTIYA XATOLARI TARJIMASIZ QOLMASIN.

Backend xatolari lotin-o'zbekcha qaytadi; frontend ularni foydalanuvchi tiliga
o'giradi. Lug'at MATN bo'yicha qidiradi, shu bois serverdagi bitta harf
o'zgarsa tarjima JIMGINA tushib qoladi va kirillcha ishlaydigan do'kon egasi
texnik lotin matn ko'radi — hech qayerda xato chiqmaydi.

Bu sinov shu jimlikni buzadi: partiya/inventarizatsiya yo'llaridagi HAR bir
foydalanuvchi xatosi ikkita lug'atdan birida (`serverErrors.ts` avto-generatsiya
yoki `serverErrorsLots.ts` qo'lda) qoplanganini tekshiradi.
"""
import ast
import io
import pathlib
import re
import types

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1] / "app"
SHARED = pathlib.Path(__file__).resolve().parents[3] / "packages" / "shared" / "src" / "lib"

SOURCES = ["api/v1/lots.py", "api/v1/lots_read.py", "api/v1/inventory.py",
           "api/v1/receiving.py",
           "services/lot_writeoff.py", "services/lot_resolution.py",
           "services/lot_receiving.py", "services/lot_return.py",
           "services/lot_policy.py", "services/stock_gate.py",
           # Phase 5D — tuzatish oqimi matnlari ham operator ko'radigan matn:
           # endpoint YUPQA, matnlar SERVISDA tug'iladi.
           "services/lot_correction.py"]
# ⚠️  XABAR ARGUMENTINING O'RNI HAR SINFDA BOSHQA: `HTTPException(409, "...")` va
#     `ResolutionError(409, "...")` da matn IKKINCHI argument, qolganlarida
#     BIRINCHI. Sinf nomini shunchaki to'plamga qo'shish sinovni JIMGINA
#     bo'shatardi: birinchi argument son bo'lgani uchun hech qanday matn
#     yig'ilmasdi va sinov YASHIL qolaverardi.
RAISERS = {"HTTPException": 1, "ResolutionError": 1,
           "LotSelectionError": 0, "LotPayloadError": 0,
           "TimezoneNotConfigured": 0, "LotActivationNotAllowed": 0,
           "TrackedProductNotSupported": 0,
           # `sales.py` qaytarish yo'lida `HTTPException(409, str(e))` bo'lib chiqadi.
           "ReturnAttributionError": 0,
           # Phase 5D: `CorrectionError(status, detail, code=...)` — matn IKKINCHI argument.
           "CorrectionError": 1,
           # Phase 5G.1: kassa gardining YAGONA kompozitori `_fail(code, msg, ...)` —
           # matn IKKINCHI argument. `raise` emas, chaqiruv: `_raises` uni alohida yig'adi.
           "_fail": 1}
MARK = "@@"          # format-o'rni belgisi


def _text(node):
    """Konstanta yoki f-string -> matn; almashadigan qism o'rniga MARK."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            else:
                out.append(MARK)
        return "".join(out)
    return None


def _messages():
    seen = {}
    for rel in SOURCES:
        p = SERVER / rel
        if not p.exists():
            continue
        tree = ast.parse(io.open(p, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name not in RAISERS:
                continue
            idx = RAISERS[name]
            arg = None
            for kw in node.keywords:        # HTTPException(status_code=.., detail="..")
                if kw.arg == "detail":
                    arg = kw.value
            if arg is None and len(node.args) > idx:
                arg = node.args[idx]
            if arg is None:
                continue
            txt = _text(arg)
            if txt:
                seen.setdefault(txt, rel)
    return seen


def _dicts():
    """Ikkala lug'atdan statik kalitlar va dinamik regexlar."""
    static, dyn = set(), []
    for f in ("serverErrors.ts", "serverErrorsLots.ts"):
        src = io.open(SHARED / f, encoding="utf-8").read()
        for line in src.splitlines():
            m = re.match(chr(32)*2 + chr(34) + "(.+?)" + chr(34) + ": [{]", line.rstrip())
            if m:
                static.add(m.group(1))
        for m in re.finditer(r"\{\s*re:\s*/\^(.*?)\$/\s*,", src):
            dyn.append(m.group(1))
    return static, dyn


# ⚠️  O'RIN-BELGI NAMUNALARI. Ko'p o'rin son yoki nom (har qanday matn), lekin
#     ba'zilari CHEKLANGAN ro'yxatdan keladi (`lot_return._check_restock_target`
#     ga «Asl partiya» / «Yopishda topilgan partiya» beriladi) va lug'at ularni
#     aniq sanab tarjima qiladi. Bitta «7» namunasi o'shalarni «tarjimasiz» deb
#     yolg'on qizartirardi.
PROBES = ("7", "Asl partiya", "Yopishda topilgan partiya")


def _covered(msg, static, dyn):
    if msg in static:
        return True
    for val in PROBES:
        probe = msg.replace(MARK, val)
        if probe in static:
            return True
        for src in dyn:
            try:
                rx = re.compile("^" + src + "$")
            except re.error:                 # JS-ga xos sintaksis — o'tkazamiz
                continue
            if rx.match(probe):
                return True
    return False


def _translatable():
    """Faqat o'rin-belgidan iborat o'rovchi xabar (`f"{nom}: {xato}"`) CHIQARILADI:
    ichki xato alohida qoplanadi, o'rovchining o'zida tarjima qilinadigan matn yo'q.

    ⚠️  SKIP EMAS, FILTR. CI `verify_pytest_run.py` kutilmagan skip'ni yiqitadi —
        doimiy skip esa «nimadir sinalmadi» signalini shovqinga aylantirardi.
    """
    return sorted(m for m in _messages() if m.replace(MARK, "").strip(": .-"))


@pytest.mark.parametrize("msg", _translatable())
def test_PARTIYA_xatosi_lugatda_BOR(msg):
    static, dyn = _dicts()
    assert _covered(msg, static, dyn), (
        f"TARJIMASIZ: {msg!r} — `serverErrorsLots.ts` ga qo'shing "
        f"(manba: {_messages()[msg]})")


def test_NOMALUM_raiser_JIMGINA_otkazib_yuborilmaydi():
    """SOURCES dagi HAR `raise X(...)` sinfi RAISERS da bo'lishi SHART.

    ⚠️  Aks holda yangi istisno sinfi qo'shilganda uning matnlari drift
        sinoviga UMUMAN tushmasdi va sinov YASHIL qolaverardi (aynan
        `ReturnAttributionError` bilan shunday bo'lgan edi).
    """
    unknown = set()
    for rel in SOURCES:
        tree = ast.parse(io.open(SERVER / rel, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                fn = node.exc.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name and name not in RAISERS:
                    unknown.add(f"{name} ({rel})")
    assert not unknown, f"RAISERS ga qo'shing (xabar argumenti indeksi bilan): {sorted(unknown)}"


def test_xabar_argumenti_MATN_bo_lishi_SHART():
    """Xabar o'zgaruvchi yoki `.format()` bo'lsa, lug'at bilan solishtirib bo'lmaydi."""
    opaque = []
    for rel in SOURCES:
        tree = ast.parse(io.open(SERVER / rel, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            fn = node.exc.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name not in RAISERS:
                continue
            idx = RAISERS[name]
            arg = next((kw.value for kw in node.exc.keywords if kw.arg == "detail"), None)
            if arg is None and len(node.exc.args) > idx:
                arg = node.exc.args[idx]
            if arg is None or _text(arg) is not None:
                continue
            # `str(e)` — ichki istisno matnini QAYTA uzatish; uning manbasi
            # (asl raiser) shu sinovda alohida yig'iladi, shuning uchun ruxsat.
            if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "str":
                continue
            # `e.detail` — `ResolutionError` matnini qayta uzatish (manbasi yig'iladi).
            if isinstance(arg, ast.Attribute) and arg.attr == "detail":
                continue
            opaque.append(f"{rel}:{node.lineno}")
    assert not opaque, f"xabar matn EMAS (lug'at bilan solishtirib bo'lmaydi): {opaque}"


# ══ 409 — SOTUV VA QAYTARISH YO'LI (Phase 5B) ═══════════════════════════════
# ⚠️  NEGA FAQAT 409. `services/sales.py` va `api/v1/sales.py` ni SOURCES ga
#     butunlay qo'shish partiyaga aloqasi yo'q ~17 ta mavjud 400 matnini (QR,
#     chegirma limiti ...) qizartirardi. 409 esa aynan partiya darvozalari va
#     `/sync/push` TRANZIENT deb biladigan holat: pul olingan offline chek shu
#     matn bilan outbox'da qayta-qayta aylanadi — u tarjimasiz qolmasin.
SALES = ["services/sales.py", "api/v1/sales.py"]

# Phase 5B darvoza matnlari — server kodi va lug'at bilan AYNAN mos.
SALE_409 = ("Savdoni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
            "qo'llab-quvvatlashga murojaat qiling.")
RETURN_409 = ("Qaytarishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
              "qo'llab-quvvatlashga murojaat qiling.")
RESOLVE_409 = ("Qarzni yopib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; "
               "qo'llab-quvvatlashga murojaat qiling.")

# ⚠️  NOMLANGAN DOMEN ISTISNOLARI. Ularning matni operatorga ATAYLAB yozilgan
#     ko'rsatma («restock'siz qaytaring») va manbasi o'zi alohida yig'iladi —
#     `str(e)` / `e.detail` bilan uzatish FAQAT shularga ruxsat. Keng
#     `except Exception` ichida esa istisno matni HECH QACHON javobga tushmaydi:
#     u yerda xom UUID, `≠`, modul nomlari va `[SQL: ...]` yotadi.
DOMAIN = frozenset({"ReturnAttributionError", "TimezoneNotConfigured", "LotSelectionError",
                    "LotPayloadError", "TrackedProductNotSupported",
                    "LotActivationNotAllowed", "ResolutionError",
                    # Phase 5D: qabulni tuzatish servisining tipli xatosi
                    # (`ResolutionError` bilan AYNI naqsh — matn SERVERDA
                    # yoziladi va lug'atga tushadi, ichki istisnodan kelmaydi).
                    "CorrectionError",
                    "CashTillUnresolved", "LedgerUnavailable"})
BROAD = frozenset({"Exception", "BaseException"})
LEAK_RAISERS = ("HTTPException", "ResolutionError", "_fail")


def _nom(node):
    return node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")


def _xabar(call):
    idx = RAISERS.get(_nom(call.func))
    # ⚠️  `_fail(code, msg, *, detail=...)` da `detail` — JURNALGA ketadigan ICHKI matn
    #     (operator ko'rmaydi); xabar FAQAT ikkinchi pozitsion argument.
    arg = None
    if _nom(call.func) != "_fail":
        arg = next((kw.value for kw in call.keywords if kw.arg == "detail"), None)
    if arg is None and idx is not None and len(call.args) > idx:
        arg = call.args[idx]
    return arg


def _holat(call):
    arg = next((kw.value for kw in call.keywords if kw.arg == "status_code"), None)
    if arg is None and call.args:
        arg = call.args[0]
    return arg.value if isinstance(arg, ast.Constant) else None


def _raises(tree):
    """(raise tuguni, uni o'rab turgan BARCHA except'lar) — ichkaridan tashqariga.

    ⚠️  Faqat eng yaqin except yetmaydi: `except Exception as e:` ichidagi
        `except ValueError:` dan `str(e)` uzatilsa, bog'langan nom TASHQI
        except'niki bo'ladi va u yerda ham sizib chiqadi.
    """
    out = []

    def visit(node, handlers):
        for child in ast.iter_child_nodes(node):
            hs = (child,) + handlers if isinstance(child, ast.ExceptHandler) else handlers
            if isinstance(child, ast.Raise) and isinstance(child.exc, ast.Call):
                out.append((child, hs))
            # Phase 5G.1: `_fail(code, msg, ...)` — kassa gardining `raise` o'rnidagi
            # chaqiruvi. Uni `raise` tuguni SHAKLIDA qaytaramiz (`.exc` = chaqiruv), shunda
            # sizish/409/id detektorlari uni HTTPException bilan bir xil ko'radi.
            if (isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                    and _nom(child.value.func) == "_fail"):
                out.append((types.SimpleNamespace(exc=child.value, lineno=child.lineno), hs))
            visit(child, hs)
    visit(tree, ())
    return out


def _turlar(h):
    if h.type is None:
        return {"BaseException"}           # yalang'och `except:`
    types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    return {_nom(t) for t in types}


def _ishlatadi(expr, name):
    return bool(name) and any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(expr))


def _domen_uzatishi(arg, handlers):
    """`str(e)` yoki `e.detail` — `e` NOMLANGAN domen istisnosiga bog'langan bo'lsa."""
    if isinstance(arg, ast.Call) and _nom(arg.func) == "str" and len(arg.args) == 1:
        inner = arg.args[0]
    elif isinstance(arg, ast.Attribute) and arg.attr == "detail":
        inner = arg.value
    else:
        return False
    if not isinstance(inner, ast.Name):
        return False
    for h in handlers:
        if h.name == inner.id:
            return _turlar(h) <= DOMAIN
    return False


def _scan_409(source, rel):
    """`HTTPException(409, ...)` xabarlari -> (matnlar {matn: joy}, shaffof EMASlar [joy])."""
    texts, opaque = {}, []
    for node, handlers in _raises(ast.parse(source)):
        call = node.exc
        if _nom(call.func) != "HTTPException" or _holat(call) != 409:
            continue
        arg = _xabar(call)
        txt = _text(arg) if arg is not None else None
        if txt is not None:
            texts.setdefault(txt, f"{rel}:{node.lineno}")
        elif not _domen_uzatishi(arg, handlers):
            opaque.append(f"{rel}:{node.lineno}")
    return texts, opaque


def _sales_409():
    texts, opaque = {}, []
    for rel in SALES:
        t, o = _scan_409(io.open(SERVER / rel, encoding="utf-8").read(), rel)
        for k, v in t.items():
            texts.setdefault(k, v)
        opaque += o
    return texts, opaque


def _sizishlar(source, rel="<manba>"):
    """Istisno matnini javobga uzatadigan `raise` lar ro'yxati.

    1) `.join(` BinOp/f-string ichida — ichki qatorlar ro'yxati (UUID, ustun
       nomlari) xabarga yopishtiriladi. Bu qoida except'dan TASHQARIDA ham
       ishlaydi: qaytarish chegarasi xabari aynan `if` ichida edi.
    2) Bog'langan istisno nomi xabarda — keng except'da HECH QACHON, boshqa
       except'da faqat nomlangan domen istisnosi bo'lsa.
    """
    bad = []
    for node, handlers in _raises(ast.parse(source)):
        call = node.exc
        if _nom(call.func) not in LEAK_RAISERS:
            continue
        arg = _xabar(call)
        if arg is None:
            continue
        if isinstance(arg, (ast.BinOp, ast.JoinedStr)) and any(
                isinstance(x, ast.Call) and _nom(x.func) == "join" for x in ast.walk(arg)):
            bad.append(f"{rel}:{node.lineno} .join(")
        for h in handlers:
            if not _ishlatadi(arg, h.name):
                continue
            turlar = _turlar(h)
            if turlar & BROAD or not turlar <= DOMAIN:
                bad.append(f"{rel}:{node.lineno} {h.name} ({', '.join(sorted(turlar))})")
    return bad


@pytest.mark.parametrize("msg", sorted(_sales_409()[0]))
def test_SOTUV_409_xatosi_lugatda_BOR(msg):
    static, dyn = _dicts()
    assert _covered(msg, static, dyn), (
        f"TARJIMASIZ 409: {msg!r} — `serverErrorsLots.ts` ga qo'shing "
        f"(manba: {_sales_409()[0][msg]})")


def test_SOTUV_409_xabari_MATN_yoki_DOMEN_uzatishi():
    """409 xabari lug'at bilan solishtiriladigan matn bo'lishi SHART.

    Yagona istisno — NOMLANGAN domen istisnosini `str(e)` bilan uzatish (uning
    manbasi alohida yig'iladi). Qatorlar yig'indisi (`"..." + "; ".join(...)`)
    yoki keng except'dagi `str(e)` bu yerda QIZIL.
    """
    _texts, opaque = _sales_409()
    assert not opaque, f"409 xabari matn EMAS va domen uzatishi ham emas: {opaque}"


def test_SOTUV_409_skaneri_BOSH_EMAS():
    """Skaner jimgina hech narsa yig'masa, yuqoridagi ikki sinov YOLG'ON yashil bo'lardi."""
    texts, _opaque = _sales_409()
    assert SALE_409 in texts, sorted(texts)
    assert RETURN_409 in texts, sorted(texts)
    assert any("sotuvga yaroqli partiya yetarli emas" in t for t in texts), sorted(texts)


def test_ICHKI_istisno_matni_JAVOBGA_SIZMAYDI():
    """Phase 4B.1 qoidasi endi TO'RTTALA qolgan darvozada ham qo'riqlanadi."""
    bad = []
    for rel in SOURCES + SALES:
        p = SERVER / rel
        if p.exists():
            bad += _sizishlar(io.open(p, encoding="utf-8").read(), rel)
    assert not bad, f"istisno matni operatorga sizib chiqadi: {bad}"


# ⚠️  MANFIY NAZORAT. Detektor ESKI naqshlarni ushlamasa, yuqoridagi sinovlar
#     hech narsani isbotlamaydi — shu bois ular sun'iy manbada QIZIL bo'lishi shart.
_ESKI = '''
def sotuv(db):
    try:
        tekshir(db)
    except Exception as _e:      # noqa: BLE001
        db.rollback()
        raise HTTPException(409, f"Partiya/qoldiq invarianti buzildi — savdo "
                                 f"bekor qilindi: {_e}") from _e


def qaytarish(db, _viol):
    if _viol:
        raise HTTPException(
            409, "chegarasi buzilardi: " + "; ".join(_viol[:3]))


def yopish(db):
    try:
        tekshir(db)
    except (ValueError, Exception) as e:
        raise ResolutionError(409, "yopib bo'lmadi: " + str(e)) from e


def ichma_ich(db):
    try:
        tekshir(db)
    except BaseException as e:
        try:
            tozala(db)
        except ReturnAttributionError:
            raise HTTPException(409, repr(e.args))


def nomlanmagan(db):
    try:
        tekshir(db)
    except ValueError as e:
        raise HTTPException(409, str(e))
'''

_TOZA = '''
def sotuv(db):
    try:
        tekshir(db)
    except Exception as e:      # noqa: BLE001
        log.exception("sotuv invariant buzildi: %s", e)
        db.rollback()
        raise HTTPException(409, "aniq matn", headers=EC.headers(EC.LOT_INVARIANT_BROKEN)) from e


def qaytarish(db):
    try:
        reja(db)
    except _LR.ReturnAttributionError as e:
        raise HTTPException(409, str(e)) from e


def yopish(db):
    try:
        yop(db)
    except LRes.ResolutionError as e:
        raise HTTPException(e.status, e.detail) from e
'''


def test_MANFIY_NAZORAT_eski_naqshlar_USHLANADI():
    bad = _sizishlar(_ESKI)
    joylar = {b.split(" ", 1)[0] for b in bad}
    assert len(joylar) == 5, bad
    assert any(".join(" in b for b in bad), bad
    assert any("_e (Exception)" in b for b in bad), bad
    texts, opaque = _scan_409(_ESKI, "<eski>")
    eski = "Partiya/qoldiq invarianti buzildi — savdo bekor qilindi: @@"
    assert eski in texts, sorted(texts)
    static, dyn = _dicts()
    assert not _covered(eski, static, dyn), "eski sotuv matni lug'atda — nazorat bo'sh"
    # `+ "; ".join(...)`, `repr(e.args)` va nomlanmagan `ValueError` ning `str(e)` si
    assert len(opaque) == 3, opaque


def test_MUSBAT_NAZORAT_ruxsat_etilgan_naqshlar_QIZARMAYDI():
    """Detektor HAMMA narsani ushlasa ham manfiy nazorat o'tardi — bu uni ushlaydi."""
    assert _sizishlar(_TOZA) == []
    _texts, opaque = _scan_409(_TOZA, "<toza>")
    assert opaque == [], opaque




def test_YANGI_matnlar_QOLDA_yuritiladigan_lugatda():
    """Avto-generatsiya lug'ati (`serverErrors.ts`) qo'lda tahrirlanmaydi — yangi
    matnlar FAQAT `serverErrorsLots.ts` STATIC da bo'lishi shart."""
    src = io.open(SHARED / "serverErrorsLots.ts", encoding="utf-8").read()
    for msg in (SALE_409, RETURN_409, RESOLVE_409):
        assert f'  "{msg}": {{' in src, msg


# ══ SON SIG'IMI RAD ETISHLARI — YARIM TARJIMA BO'LMASIN (Phase 5D) ══════════
#
# ⚠️  «QOPLANGAN» YETMAYDI, «TARJIMA QILINGAN» KERAK. Tuzatish moduli ilgari
#     `f"{yorliq} juda katta — ..."` deb yozardi va lug'atdagi dinamik qoida
#     `$1` o'rniga LOTIN yorlig'ini qo'yardi: rus tilidagi jumla ichida
#     o'zbekcha bo'lak qolardi («Teskari qilingan summa слишком велика ...»).
#     Yuqoridagi sinovlar bundan BEXABAR edi — shablon ularga «qoplangan» bo'lib
#     ko'rinardi. Shu bois to'rttala rad etish ALOHIDA to'liq jumla.
SIGIM = (
    "Teskari qilingan summa juda katta — miqdor yoki narxni tekshiring",
    "O'rniga qo'yilgan summa juda katta — miqdor yoki narxni tekshiring",
    "Tuzatish summasi juda katta — miqdor yoki narxni tekshiring",
    "Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring",
)


@pytest.mark.parametrize("msg", SIGIM)
def test_SIGIM_rad_etishi_TOLIQ_JUMLA_va_STATIK(msg):
    static, _dyn = _dicts()
    assert msg in _messages(), (
        f"server bu matnni TO'LIQ jumla sifatida ko'tarmaydi: {msg!r}")
    assert msg in static, f"`serverErrorsLots.ts` STATIC da yo'q: {msg!r}"


def test_SIGIM_xabari_YORLIQ_bilan_YOPISHTIRILMAYDI():
    """Tuzatish modulida «@@ juda katta ...» o'rin-belgili shablon QOLMASIN."""
    bad = [m for m, rel in _messages().items()
           if MARK in m and "juda katta" in m and rel == "services/lot_correction.py"]
    assert not bad, f"yorliq jumlaga yopishtirilgan (tarjima yarim qoladi): {bad}"


# ══ KASSA FAYLLARI — ICHKI ID VA ISTISNO MATNI JAVOBGA SIZMAYDI (Phase 5G.1, B3) ═
#
# ⚠️  NEGA ALOHIDA RO'YXAT. Kassa rad etishlari MATN bo'yicha emas, KOD prefiksi
#     bo'yicha tarjima qilinadi (`serverErrorsCash.ts`, `errors.dart`), shu bois
#     ular `SOURCES` ga (lug'at qoplami sinovi) QO'SHILMAYDI — faqat SIZISH
#     detektorlari ularga ham qaraydi. Audit (AU-2 §4.3): aynan shu fayllar
#     hech qanday detektorga tushmagani uchun oltita xabar bazadan olingan UUID
#     bilan chiqib ketgan edi.
CASH_SOURCES = ["services/cash/cutover_guard.py", "services/cash/errors.py",
                "api/v1/cashops.py", "api/v1/customers.py", "api/v1/purchases.py",
                "api/v1/shifts.py"]
# ID-shaklidagi interpolatsiya TAQIQLANADIGAN fayllar. Bu yerda mijoz yuborgan id'ni
# matnga qaytarish ham qonuniy emas: gard faqat SERVER holatini ko'radi (smena, hisob
# qatori), API fayllari esa saqlangan hisobni yoki smenani nomlaydi. Mijoz-yuborgan
# id'ni ataylab qaytaradigan fayllar (`purchases.py:242` «Mahsulot topilmadi: {id}»)
# bu ro'yxatga KIRMAYDI — ular uchun hakam jonli manfiy nazorat
# (`test_error_hygiene.py`: «so'rovda yuborilmagan UUID yo'q»).
ID_SOURCES = ["services/cash/cutover_guard.py", "services/cash/errors.py",
              "services/cash/observability.py",
              "api/v1/customers.py", "api/v1/shifts.py", "api/v1/cashops.py"]
ID_RE = re.compile(r"(^|_)(id|uuid)$")
# `_fail` uchun: har chaqiruv `operation=` VA kontekst id'laridan kamida bittasini bersin —
# aks holda jurnal `company_id:null,branch_id:null,...` bo'lib qoladi va xabardan
# chiqarilgan id hech qayerda qolmaydi (AU-2 §1.1, 3-fakt: 14 chaqiruvdan 13 tasi bo'sh edi).
FAIL_CONTEXT = ("company_id", "branch_id", "shift_id", "account_id", "till_id")


def _id_ifoda(expr) -> bool:
    """Interpolatsiya ifodasi id'ga ISHORA qiladimi: `x_id`, `id`, `acc.branch_id`,
    `shift.id`, `getattr(shift, "id", ...)`, `str(<...>)`."""
    if isinstance(expr, ast.Name):
        return bool(ID_RE.search(expr.id))
    if isinstance(expr, ast.Attribute):
        return bool(ID_RE.search(expr.attr))
    if isinstance(expr, ast.Call):
        nm = _nom(expr.func)
        if nm == "getattr" and len(expr.args) >= 2 and isinstance(expr.args[1], ast.Constant):
            return bool(ID_RE.search(str(expr.args[1].value)))
        if nm == "str" and expr.args:
            return _id_ifoda(expr.args[0])
    return False


def _xabar_idx(call, idx):
    arg = None
    if _nom(call.func) != "_fail":      # `_fail(..., detail=)` — jurnal matni, xabar emas
        arg = next((kw.value for kw in call.keywords if kw.arg == "detail"), None)
    if arg is None and len(call.args) > idx:
        arg = call.args[idx]
    return arg


def _id_sizishlari(source, rel="<manba>"):
    """Xabar f-string'ida ID-SHAKLIDAGI interpolatsiya — [`fayl:qator ifoda`]."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        idx = RAISERS.get(_nom(node.func))
        if idx is None:
            continue
        arg = _xabar_idx(node, idx)
        if arg is None:
            continue
        for x in ast.walk(arg):
            if isinstance(x, ast.FormattedValue) and _id_ifoda(x.value):
                bad.append(f"{rel}:{node.lineno} {ast.unparse(x.value)}")
    return bad


def _fail_chaqiruvlari(source):
    return [n for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and _nom(n.func) == "_fail"]


def _manba(rel):
    return io.open(SERVER / rel, encoding="utf-8").read()


def test_KASSA_ichki_istisno_matni_JAVOBGA_SIZMAYDI():
    """`_sizishlar` endi kassa fayllarini ham ko'radi (va `_fail` ni `raise` kabi)."""
    bad = []
    for rel in CASH_SOURCES:
        bad += _sizishlar(_manba(rel), rel)
    assert not bad, f"istisno matni operatorga sizib chiqadi: {bad}"


def test_KASSA_xabarida_BAZADAN_OLINGAN_ID_YOQ():
    """AU-2 T14: gard/kassa xabarida id-shaklidagi interpolatsiya bo'lmasin.

    Xabardan chiqarilgan id JURNALGA o'tadi (`_fail(..., account_id=, till_id=,
    shift_id=, branch_id=)`), operator esa id'siz, o'zi bajara oladigan jumla oladi."""
    bad = []
    for rel in ID_SOURCES:
        bad += _id_sizishlari(_manba(rel), rel)
    assert not bad, f"xabarda id interpolatsiyasi (jurnalga o'tkazing): {bad}"


def test_FAIL_har_chaqiruv_OPERATION_va_KONTEKST_beradi():
    """AU-2 T15 — tartib tuzog'i: id'ni matndan olib tashlashdan OLDIN u strukturali
    maydonga o'tgan bo'lishi shart; aks holda diagnostika o'chib ketardi."""
    bad = []
    for call in _fail_chaqiruvlari(_manba("services/cash/cutover_guard.py")):
        kws = {kw.arg for kw in call.keywords}
        if "operation" not in kws or not (kws & set(FAIL_CONTEXT)):
            bad.append(f"cutover_guard.py:{call.lineno} kwargs={sorted(k for k in kws if k)}")
    assert not bad, f"`_fail` chaqiruvi kontekstsiz (jurnal bo'sh qoladi): {bad}"


def test_FAIL_sarlavha_bilan_KOTARADI():
    """AU-2 T16: `_fail` `HTTPException(..., headers=EC.headers(code))` ko'tarsin — kod
    matn prefiksidan tashqari `X-Error-Code` da ham yursin (`main.py` CORS ochgan)."""
    tree = ast.parse(_manba("services/cash/cutover_guard.py"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fail")
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
              and _nom(n.exc.func) == "HTTPException"]
    assert raises, "`_fail` ichida HTTPException ko'tarilmaydi?"
    for r in raises:
        hdr = next((kw.value for kw in r.exc.keywords if kw.arg == "headers"), None)
        assert hdr is not None, f"cutover_guard.py:{r.lineno} headers= yo'q"
        assert (isinstance(hdr, ast.Call) and _nom(hdr.func) == "headers"
                and hdr.args and _nom(hdr.args[0]) == "code"), ast.unparse(hdr)


def _prefiksli(arg) -> bool:
    """Xabar `"<KOD>: ..."` shaklidami: doimiy matn, `*_TEXT` doimiysi yoki
    `f"{ERR_...}: ..."`."""
    txt = _text(arg) if arg is not None else None
    if txt:
        return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", txt.split(":", 1)[0].strip()))
    if isinstance(arg, ast.Name):
        return arg.id.endswith("_TEXT")
    if isinstance(arg, ast.Attribute):
        return arg.attr.endswith("_TEXT")
    return (isinstance(arg, ast.JoinedStr) and bool(arg.values)
            and isinstance(arg.values[0], ast.FormattedValue)
            and _nom(arg.values[0].value).startswith("ERR_"))


def test_KASSA_KOD_PREFIKSLI_rad_etishlar_SARLAVHALI():
    """`"<KOD>: matn"` prefiksi bilan ko'tarilgan HAR HTTPException `headers=` ham bersin
    (customers/cashops/shifts): yangi mijoz sarlavhani, eski mijoz prefiksni o'qiydi.
    `purchases.py` B2 paketiniki — u yerdagi ikki chaqiruv B2 da AYNI yordamchiga o'tadi."""
    bad = []
    for rel in ("api/v1/customers.py", "api/v1/cashops.py", "api/v1/shifts.py"):
        for node, _h in _raises(ast.parse(_manba(rel))):
            call = node.exc
            if _nom(call.func) != "HTTPException" or not _prefiksli(_xabar(call)):
                continue
            if not any(kw.arg == "headers" for kw in call.keywords):
                bad.append(f"{rel}:{node.lineno}")
    assert not bad, f"kod-prefiksli rad etish sarlavhasiz: {bad}"


# ⚠️  MANFIY NAZORAT (AU-2 N1): eski 225-226 qatorlar AYNAN — detektor QIZIL bo'lsin;
#     toza ko'rinish (id kwarg'da, matnda yo'q) — YASHIL qolsin.
_ESKI_ID = """
def require_custody_account(db, *, company_id, branch_id, account_id, operation):
    acc = db.get(CashAccount, account_id)
    if acc is None:
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob topilmadi ({account_id}).")
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': hisob boshqa filialga tegishli ({acc.branch_id} != {branch_id}).")
    if shift is not None:
        _fail(ERR_CLOSED_SHIFT_REPLAY,
              f"'{operation}': YOPILGAN smenaga naqd yozib bo'lmaydi (smena {getattr(shift, 'id', '?')} "
              "yopilgan).")
        raise HTTPException(409, f"{ERR}: bu amal boshqa hisob bilan yozilgan ({ex.cash_account_id}).")


def ledger(db, operation):
    try:
        tekshir(db)
    except Exception as e:
        _fail(ERR_LEDGER_UNAVAILABLE, f"'{operation}': {e}")
"""

_TOZA_ID = """
def require_custody_account(db, *, company_id, branch_id, account_id, operation):
    acc = db.get(CashAccount, account_id)
    if acc is None:
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob topilmadi. Hisobni qayta tanlang.",
              company_id=company_id, branch_id=branch_id, account_id=account_id,
              operation=operation)
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob boshqa filialga tegishli.",
              company_id=company_id, branch_id=acc.branch_id, account_id=acc.id,
              operation=operation, detail=f"requested branch={branch_id}")
    raise HTTPException(409, KEY_ACCOUNT_CONFLICT_TEXT, headers=EC.headers(ERR_CUSTODY_INVALID))


def ledger(db, operation):
    try:
        tekshir(db)
    except _tn.LedgerUnavailable as e:
        _fail(ERR_LEDGER_UNAVAILABLE, f"'{operation}': ledger yozilmaydi.", detail=str(e),
              company_id=company_id, operation=operation)
"""


def test_MANFIY_NAZORAT_id_detektori_ESKI_gard_qatorlarini_USHLAYDI():
    bad = _id_sizishlari(_ESKI_ID, "<eski>")
    ifodalar = {b.split(" ", 1)[1] for b in bad}
    assert {"account_id", "acc.branch_id", "getattr(shift, 'id', '?')",
            "ex.cash_account_id"} <= ifodalar, bad
    # `branch_id` (so'rov qiymati) ham id — gard uni ham matnga yozmasin.
    assert "branch_id" in ifodalar, bad
    # Keng except'dagi `{e}` — sizish detektori (`_fail` ni ham ko'radi).
    siz = _sizishlar(_ESKI_ID, "<eski>")
    assert any("e (Exception)" in s for s in siz), siz


def test_MUSBAT_NAZORAT_id_detektori_TOZA_gardni_QIZARTIRMAYDI():
    assert _id_sizishlari(_TOZA_ID, "<toza>") == []
    assert _sizishlar(_TOZA_ID, "<toza>") == []
