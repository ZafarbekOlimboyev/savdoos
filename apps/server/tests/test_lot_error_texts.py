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
           "CorrectionError": 1}
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
LEAK_RAISERS = ("HTTPException", "ResolutionError")


def _nom(node):
    return node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")


def _xabar(call):
    idx = RAISERS.get(_nom(call.func))
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
