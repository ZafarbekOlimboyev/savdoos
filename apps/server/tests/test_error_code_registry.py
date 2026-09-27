# -*- coding: utf-8 -*-
"""BARQAROR XATO KODI RO'YXATDAN O'TMAGAN HOLDA CHIQMASIN.

Repoda IKKI konvensiya bor:
  · «partiya/5G.1» oilasi — kod `X-Error-Code` sarlavhasida, `detail` toza operator matni
    (u i18n lug'atining KALITI);
  · «naqd» oilasi — `detail = "KOD: matn"` **va** sarlavha; kodni `cutover_guard.code_of`
    FAQAT `ERROR_CODES` ro'yxatidan taniydi.

Ikkovida ham kod REGISTRDA bo'lishi shart. Aks holda: `api.ts` matn bo'yicha qidiradi va
prefiksli satrni topa olmaydi, `code_of` esa `None` qaytaradi — natijada rus/kirill tilidagi
do'kon egasi ekranda XOM lotin mashina tokenini ko'radi (ustiga ba'zan `str(e)` ni ham).

Bu sinov shuni to'sadi: `HTTPException` `detail`ida `KOD:` shaklidagi prefiks bo'lsa, u kod
BIRORTA registrda bo'lishi shart.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
SHARED = pathlib.Path(__file__).resolve().parents[3] / "packages" / "shared" / "src" / "lib"

# `KOD: matn` prefiksi (kamida 2 bo'lak, katta harf + pastki chiziq)
_PREFIX = re.compile(r"^([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+):\s")


def _registered() -> set:
    """Barcha barqaror kod qiymatlari — uch registrdan."""
    from app.core import error_codes as EC
    from app.services.cash import cutover_guard as CG
    out = {v for k, v in vars(EC).items()
           if k.isupper() and isinstance(v, str) and k != "HEADER"}
    out |= set(CG.ERROR_CODES)
    try:
        from app.services.receipt import errors as RE
        out |= {v for k, v in vars(RE).items() if k.isupper() and isinstance(v, str)}
    except Exception:                                    # pragma: no cover
        pass
    return out


def _detail_strings(path: pathlib.Path) -> list:
    """`HTTPException(...)` ning MATN argumentlari (const va f-string sarlavhasi)."""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "HTTPException":
            continue
        for arg in node.args[1:2] or []:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append((arg.value, node.lineno))
            elif isinstance(arg, ast.JoinedStr):
                head = arg.values[0] if arg.values else None
                if isinstance(head, ast.Constant) and isinstance(head.value, str):
                    out.append((head.value, node.lineno))
    return out


def test_har_prefiksli_kod_registrda():
    known = _registered()
    bad = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        for text, line in _detail_strings(path):
            m = _PREFIX.match(text)
            if m and m.group(1) not in known:
                bad.append(f"{path.relative_to(APP)}:{line} -> {m.group(1)}")
    assert not bad, ("Registrdan o'tmagan kod prefiksi (mijoz lug'ati tarjima qila olmaydi):\n  "
                    + "\n  ".join(bad))


def test_katalog_kodlari_registrda_va_tarjimada():
    """R-fix: uchala katalog kodi registrda VA matni desktop lug'atida."""
    from app.core import error_codes as EC
    for code in ("CATALOG_SNAPSHOT_CONFLICT", "CATALOG_IMPORT_IN_PROGRESS",
                 "CATALOG_RESET_TOKEN_STALE"):
        assert getattr(EC, code, None) == code, code + " registrda yo'q"
    dicts = "\n".join(io.open(SHARED / n, encoding="utf-8").read()
                      for n in ("serverErrors.ts", "serverErrorsLots.ts",
                                "serverErrorsCash.ts", "serverErrorsReceipt.ts"))
    for sentence in ("Ko'rib chiqilgan ro'yxat eskirgan",
                     "Boshqa import hozir bajarilmoqda",
                     "Tozalash tasdig'i eskirgan",
                     # `force_shift` naqd qarz to'lovi — mobil'да bor edi, desktopда YO'Q edi
                     "Naqd qarz to'lovi uchun ochiq smena kerak"):
        assert sentence in dicts, "tarjimasiz operator matni: " + sentence


def test_katalog_yoli_xom_istisno_matnini_chiqarmaydi():
    """`str(e)` (SQL/ichki matn) operator ekraniga TUSHMASIN — faqat jurnalda."""
    src = io.open(APP / "api" / "v1" / "catalog_v2.py", encoding="utf-8").read()
    for token in ('f"SNAPSHOT_CONFLICT: {e}"', 'f"IMPORT_IN_PROGRESS: {e}"',
                  'f"RESET_TOKEN_STALE: {e}"'):
        assert token not in src, "xom istisno matni qaytdi: " + token
