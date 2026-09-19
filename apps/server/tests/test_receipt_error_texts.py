# -*- coding: utf-8 -*-
"""PHASE 5F — CHEK XATO MATNLARI TARJIMA LUG'ATIDA (rus/kirill do'konda xom lotin matn chiqmasin).

`detail` — tarjima KALITI. Server matni bir harfga o'zgarsa, frontend lug'ati uni topmaydi va
operator xom lotin matnni ko'radi. Shu bois:
  · `errors.NEW_TEXTS` har biri `serverErrorsReceipt.ts` da AYNAN kalit sifatida bor;
  · dinamik matnlar (`Chek sozlamasi noto'g'ri: <maydon>`, `receipt: noma'lum maydon '<f>'`)
    lug'atdagi REGEX'larga mos;
  · qayta ishlatilgan eski matnlar (`Filial topilmadi`, `Chek topilmadi`) avto-lug'atda bor;
  · chek modullaridagi HAR `HTTPException` matni e'lon qilingan to'plamdan (AST bilan) —
    yangi xato qo'shilib lug'atga tushmay qolsa, shu sinov qizaradi.
Bazaga ulanmaydi.
"""
import ast
import pathlib
import re

from app.services.receipt import errors as E

SRV = pathlib.Path(__file__).resolve().parents[1]
ROOT = SRV.parents[1]
TS = ROOT / "packages" / "shared" / "src" / "lib" / "serverErrorsReceipt.ts"
TS_AUTO = ROOT / "packages" / "shared" / "src" / "lib" / "serverErrors.ts"
MODULES = sorted((SRV / "app" / "services" / "receipt").glob("*.py")) + [
    SRV / "app" / "api" / "v1" / "receipts.py"]


def _ts_keys(path: pathlib.Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    return {m.group(1).replace("\\'", "'") for m in re.finditer(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', src, re.M)}


def _ts_regexes(path: pathlib.Path) -> list[re.Pattern]:
    src = path.read_text(encoding="utf-8")
    return [re.compile(m.group(1)) for m in re.finditer(r"re:\s*/(.+?)/,", src)]


def test_YANGI_matnlar_lugatda_AYNAN_kalit():
    keys = _ts_keys(TS)
    missing = [t for t in E.NEW_TEXTS if t not in keys]
    assert not missing, missing
    assert len(set(E.NEW_TEXTS)) == len(E.NEW_TEXTS)


def test_DINAMIK_matnlar_REGEX_ga_mos():
    rx = _ts_regexes(TS)
    assert len(rx) >= 2, rx
    for msg in (E.INVALID_FIELD_TMPL.format("width_mm"), E.INVALID_FIELD_TMPL.format("qr_url"),
                E.INVALID_FIELD_TMPL.format("value"), E.UNKNOWN_FIELD_TMPL.format("font")):
        assert any(r.match(msg) for r in rx), msg
    assert E.invalid_field("copies").detail == "Chek sozlamasi noto'g'ri: copies"
    assert E.unknown_field("x").detail == "receipt: noma'lum maydon 'x'"


def test_ESKI_matnlar_avto_lugatda():
    keys = _ts_keys(TS_AUTO)
    missing = [t for t in E.EXISTING_TEXTS if t not in keys]
    assert not missing, missing


def _literal_details(path: pathlib.Path) -> list[tuple[int, str]]:
    """`HTTPException(<status>, "<matn>")` / `detail="..."` dagi SATR literallari."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "HTTPException":
            args = list(node.args[1:2]) + [k.value for k in node.keywords if k.arg == "detail"]
            for a in args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.append((node.lineno, a.value))
                elif isinstance(a, ast.JoinedStr):
                    out.append((node.lineno, "<f-string>"))
    return out


def test_CHEK_modullarida_elon_QILINMAGAN_xato_matni_YOQ():
    allowed = set(E.NEW_TEXTS) | set(E.EXISTING_TEXTS)
    bad = [(p.name, ln, t) for p in MODULES for ln, t in _literal_details(p) if t not in allowed]
    assert not bad, bad


def test_BARQAROR_kodlar():
    codes = [E.RECEIPT_SCOPE_COMPANY_FORBIDDEN, E.PRINT_ORIGINAL_EXISTS_CODE, E.PRINT_JOB_FINAL_CODE,
             E.PRINT_JOB_INVALID_CODE]
    assert codes == ["RECEIPT_SCOPE_COMPANY_FORBIDDEN", "PRINT_ORIGINAL_EXISTS", "PRINT_JOB_FINAL",
                     "PRINT_JOB_INVALID"]
    assert E.scope_company_forbidden().headers == {"X-Error-Code": "RECEIPT_SCOPE_COMPANY_FORBIDDEN"}
    assert E.print_job_invalid(404).status_code == 404
