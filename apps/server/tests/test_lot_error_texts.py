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
           "services/lot_policy.py", "services/stock_gate.py"]
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
           "ReturnAttributionError": 0}
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
