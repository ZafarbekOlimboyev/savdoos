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
           "services/lot_writeoff.py", "services/lot_resolution.py",
           "services/lot_receiving.py", "services/lot_fefo.py"]
RAISERS = {"HTTPException", "LotSelectionError"}
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
            if name == "HTTPException":
                arg = node.args[1] if len(node.args) > 1 else None
            else:
                arg = node.args[0] if node.args else None
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


def _covered(msg, static, dyn):
    probe = msg.replace(MARK, "7")          # almashadigan qism o'rniga namuna
    if probe in static or msg in static:
        return True
    for src in dyn:
        try:
            rx = re.compile("^" + src + "$")
        except re.error:                     # JS-ga xos sintaksis — o'tkazamiz
            continue
        if rx.match(probe):
            return True
    return False


@pytest.mark.parametrize("msg", sorted(_messages()))
def test_PARTIYA_xatosi_lugatda_BOR(msg):
    static, dyn = _dicts()
    # Faqat o'rin-belgidan iborat o'rovchi xabar ("{nom}: {xato}") — ichki xato
    # alohida qoplanadi, o'rovchining o'zi tarjima qilinmaydi.
    if not msg.replace(MARK, "").strip(": .-"):
        pytest.skip("o'rovchi xabar")
    assert _covered(msg, static, dyn), (
        f"TARJIMASIZ: {msg!r} — `serverErrorsLots.ts` ga qo'shing "
        f"(manba: {_messages()[msg]})")
