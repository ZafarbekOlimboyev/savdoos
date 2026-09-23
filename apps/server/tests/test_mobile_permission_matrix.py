# -*- coding: utf-8 -*-
"""PHASE 5G / M5 — MOBIL RUXSAT MATRITSASI ⇔ SERVER DARVOZALARI (o'zaro tekshiruv).

Mobil ilova (`apps/mobile`) tugma/tab/amalni `assets/permission_matrix.json` bo'yicha
ko'rsatadi yoki yashiradi: `action -> {method, path, any_of}`. Bu fayl matritsa
SERVERNING HAQIQIY darvozalari bilan AYNI ekanini isbotlaydi:

  1. STATIK — har `{method, path}` AYNAN bitta FastAPI marshrutiga tushadi va marshrut
     dependency daraxtidagi `require`/`require_any` ruxsatlari to'plami `any_of` ga
     TENG (`tests/test_sales_read_pg.py::_darvozalar` namunasi). `any_of: []` —
     «har qanday kirgan xodim»: darvoza YO'Q, lekin autentifikatsiya BOR.
     `gate: "handler"` (custody preview) — marshrut darvozasi amal ruxsatlarining
     BIRLASHMASI, amalning o'zi esa `PREVIEW_PERMISSIONS[operation]`.
  2. DINAMIK — har seed roli (ega/administrator/menejer/omborchi/kassir) uchun har
     amal HAQIQIY so'rov bilan yuboriladi (yozuvlar bo'sh tana bilan: validatsiya
     darvozadan KEYIN, hech narsa yozilmaydi). «Rad etildi» = 403 + `X-Error-Code:
     PERMISSION_DENIED`; kutilgan = rol FULL_ACCESS emas va `any_of` bilan kesishmasi
     bo'sh. Ya'ni matritsa ham, darvozaning SEMANTIKASI (ega/administrator chetlab
     o'tishi, require_any) ham tekshiriladi.
  3. Mobil widget testidagi rollar (`apps/mobile/test/shell_permission_matrix_test.dart`
     BEGIN/END_ROLE_PERMISSIONS bloki) — `app/seed.py` ROLES bilan AYNI.
  4. Mobil kodidagi har YOZUV chaqiruvi (POST/PATCH/PUT/DELETE literal yo'li)
     matritsada e'lon qilingan (auth o'z-o'ziga xizmat yo'llari bundan mustasno).

⚠️  Ega/administrator serverda `FULL_ACCESS_ROLES` orqali ruxsat tekshiruvisiz o'tadi
    (`core/deps.py`) — matritsadagi `full_access_roles` shu ro'yxat bilan AYNI bo'lishi shart.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.security import create_access_token

REPO = Path(__file__).resolve().parents[3]
MOBILE = REPO / "apps" / "mobile"
MATRIX = MOBILE / "assets" / "permission_matrix.json"
WIDGET_TEST = MOBILE / "test" / "shell_permission_matrix_test.dart"
PREFIX = "/api/v1"
NOW = datetime.now(timezone.utc)

# Mobil yozuvlari ichida matritsada BO'LMASLIGI to'g'ri bo'lganlar: o'z sessiyasiga xizmat
# (ruxsat talab qilmaydi, marshrutda darvoza yo'q).
AUTH_SELF_SERVICE = {("POST", "/auth/login/password"), ("POST", "/auth/logout"), ("POST", "/auth/password")}


def _matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def _actions() -> dict:
    return _matrix()["actions"]


def _walk(routes, prefix: str, inc_deps: list, out: dict) -> None:
    """Marshrutlarni to'liq yo'l bilan yig'adi. FastAPI 0.14x `include_router` ni
    DANGASA (`_IncludedRouter`) saqlaydi — ichma-ich prefiks va include darajasidagi
    `dependencies` ham hisobga olinadi (eski versiyada `app.routes` allaqachon tekis)."""
    from fastapi.routing import APIRoute
    for r in routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                out.setdefault((m, prefix + r.path), []).append((r, tuple(inc_deps)))
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            ctx = r.include_context
            _walk(r.original_router.routes, prefix + (ctx.prefix or ""),
                  inc_deps + list(ctx.dependencies or []), out)


def _routes() -> dict:
    """(METHOD, '/path/{param}') -> [(APIRoute, include-deps)], `/api/v1` siz."""
    from app.main import app
    full: dict = {}
    _walk(app.routes, "", [], full)
    return {(m, p[len(PREFIX):]): v for (m, p), v in full.items() if p.startswith(PREFIX + "/")}


def _checker_perms(fn):
    """`require`/`require_any` tekshiruvchisi bo'lsa — uning ruxsatlari (closure), aks holda None."""
    if (getattr(fn, "__module__", None) == "app.core.deps"
            and getattr(fn, "__qualname__", "").endswith(".checker")):
        cells = dict(zip(fn.__code__.co_freevars, (c.cell_contents for c in fn.__closure__)))
        return {cells["permission_code"]} if "permission_code" in cells else set(cells["permission_codes"])
    return None


def _gate(entry) -> tuple[set[str], bool, int]:
    """Marshrut dependency daraxti: (require/require_any ruxsatlari, autentifikatsiya bormi,
    darvozalar soni) — closure'dan o'qiladi, ya'ni AYNAN marshrutga ulangan tekshiruvchi."""
    from app.core.deps import get_current_employee
    route, inc_deps = entry
    perms: set[str] = set()
    authed = False
    gates = 0
    for d in inc_deps:                      # include_router(..., dependencies=[...])
        got = _checker_perms(d.dependency)
        if got is not None:
            gates += 1
            perms |= got
            authed = True
        elif d.dependency is get_current_employee:
            authed = True
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is get_current_employee:
            authed = True
        got = _checker_perms(dep.call)
        if got is not None:
            gates += 1
            perms |= got
        stack.extend(dep.dependencies)
    return perms, authed, gates


def _route_of(action: str):
    a = _actions()[action]
    found = _routes().get((a["method"], a["path"]), [])
    assert len(found) == 1, f"{action}: {a['method']} {a['path']} -> {len(found)} ta marshrut (1 bo'lishi kerak)"
    return found[0]


# ══ 1. STATIK ═══════════════════════════════════════════════════════════════

def test_MATRITSA_shakli_va_toliq_huquqli_rollar():
    from app.core.deps import FULL_ACCESS_ROLES
    from app.seed import PERMISSIONS
    doc = _matrix()
    assert doc["full_access_roles"] == list(FULL_ACCESS_ROLES)
    known = {code for code, _ in PERMISSIONS}
    acts = doc["actions"]
    assert len(acts) >= 50
    for name, a in acts.items():
        assert a["method"] in {"GET", "POST", "PATCH", "PUT", "DELETE"}, name
        assert a["path"].startswith("/") and not a["path"].startswith(PREFIX), name
        assert isinstance(a["any_of"], list), name
        assert set(a["any_of"]) <= known, f"{name}: noma'lum ruxsat {set(a['any_of']) - known}"
        assert a.get("gate", "route") in {"route", "handler"}, name


@pytest.mark.parametrize("action", sorted(_actions()))
def test_HAR_AMAL_bitta_marshrutga_tushadi_va_darvozasi_any_of_ga_TENG(action):
    a = _actions()[action]
    route = _route_of(action)
    perms, authed, gates = _gate(route)
    assert authed, f"{action}: marshrut autentifikatsiyasiz — matritsa «kirgan xodim» deydi"
    if a.get("gate", "route") == "handler":
        return  # alohida test (custody preview)
    assert perms == set(a["any_of"]), (
        f"{action}: server darvozasi {sorted(perms)} != matritsa any_of {sorted(a['any_of'])}")
    if not a["any_of"]:
        assert gates == 0, f"{action}: matritsa «ruxsatsiz» deydi, marshrutda darvoza bor"


def test_CUSTODY_PREVIEW_handler_darvozasi_YOZUVCHI_ruxsati_bilan_AYNI():
    from typing import get_args

    from app.api.v1.cashops import CustodyOperation
    from app.services.cash.custody_preview import PREVIEW_PERMISSIONS
    acts = {n: a for n, a in _actions().items() if a.get("gate") == "handler"}
    assert acts, "custody preview amallari matritsada yo'q"
    ops = {}
    for name, a in acts.items():
        assert (a["method"], a["path"]) == ("GET", "/cash/custody-preview"), name
        op = a["query"]["operation"]
        assert name == f"custody.preview.{op}", name
        assert a["any_of"] == [PREVIEW_PERMISSIONS[op]], (
            f"{name}: any_of {a['any_of']} != yozuvchi ruxsati {PREVIEW_PERMISSIONS[op]}")
        ops[op] = a
    assert set(ops) == set(PREVIEW_PERMISSIONS) == set(get_args(CustodyOperation))
    route_perms, _, _ = _gate(_route_of(next(iter(acts))))
    assert route_perms == set(PREVIEW_PERMISSIONS.values()), "marshrut darvozasi = amal ruxsatlarining birlashmasi"


def test_WIDGET_TEST_rollari_SEED_bilan_AYNI():
    from app.core.deps import FULL_ACCESS_ROLES
    from app.seed import ROLES
    src = WIDGET_TEST.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN_ROLE_PERMISSIONS\s*const _rolesJson = r'''(.*?)''';\s*// END_ROLE_PERMISSIONS", src, re.S)
    assert m, "BEGIN/END_ROLE_PERMISSIONS bloki topilmadi"
    dart_roles = {k: sorted(v) for k, v in json.loads(m.group(1)).items()}
    seed_roles = {code: sorted(perms) for code, (_, perms) in ROLES.items() if perms != "ALL"}
    assert dart_roles == seed_roles
    assert {code for code, (_, perms) in ROLES.items() if perms == "ALL"} == set(FULL_ACCESS_ROLES)


_WRITE_CALL = re.compile(
    r"""\b(?P<fn>postJson|patchJson|putJson|deleteJson|_post|_patch|_put|_delete)\(\s*(?P<q>['"])(?P<path>/[^'"]*)(?P=q)""")


def _norm(path: str) -> str:
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_]\w*", "{}", path)
    return re.sub(r"\{[A-Za-z_]\w*\}", "{}", path)


def test_MOBIL_kodidagi_har_YOZUV_matritsada_elon_qilingan():
    method = {"postJson": "POST", "_post": "POST", "patchJson": "PATCH", "_patch": "PATCH",
              "putJson": "PUT", "_put": "PUT", "deleteJson": "DELETE", "_delete": "DELETE"}
    declared = {(a["method"], _norm(a["path"])) for a in _actions().values()}
    allowed = declared | {(m, _norm(p)) for m, p in AUTH_SELF_SERVICE}
    found, missing = set(), []
    for f in sorted((MOBILE / "lib").rglob("*.dart")):
        for mm in _WRITE_CALL.finditer(f.read_text(encoding="utf-8")):
            key = (method[mm["fn"]], _norm(mm["path"]))
            found.add(key)
            if key not in allowed:
                missing.append(f"{f.relative_to(MOBILE)}: {key[0]} {mm['path']}")
    assert len(found) >= 10, "yozuv chaqiruvlari topilmadi — regex eskirgan"
    assert not missing, ("matritsada yo'q mobil yozuvlar (assets/permission_matrix.json ga qo'shing):\n"
                         + "\n".join(missing))


# ══ 2. DINAMIK — har rol, har amal, HAQIQIY so'rov ═════════════════════════

ROLES = ("ega", "administrator", "menejer", "omborchi", "kassir")


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


@pytest.fixture(scope="module")
def staff(client):
    """Alohida do'kon: bitta filial va har roldan bitta xodim (filialga biriktirilgan)."""
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="M5 " + uuid.uuid4().hex[:6], code="m5" + uuid.uuid4().hex[:8],
                       currency="UZS")
        db.add(comp)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=comp.id, name="M5-F01", code="F01", timezone="Asia/Bishkek",
                    is_active=True, created_at=NOW - timedelta(days=5))
        db.add(br)
        db.flush()
        out = {}
        for code in ROLES:
            role = db.query(Role).filter(Role.code == code).one()
            e = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id, full_name=f"M5 {code}",
                         phone=f"+9967{uuid.uuid4().int % 10**8:08d}", status=EmployeeStatus.active, sec_epoch=0)
            db.add(e)
            db.flush()
            if code != "ega":
                db.add(EmployeeBranch(employee_id=e.id, branch_id=br.id))
            tok = create_access_token(str(e.id), {"role": code, "company_id": str(comp.id), "sv": 0})
            out[code] = {"Authorization": f"Bearer {tok}"}
        db.commit()
    return out


def _role_perms(code: str) -> set[str]:
    from app.seed import ROLES as SEED
    perms = SEED[code][1]
    return set() if perms == "ALL" else set(perms)


def _url(a: dict) -> str:
    def sub(m):
        return "x123" if m.group(1) == "code" else str(uuid.uuid4())
    return PREFIX + re.sub(r"\{(\w+)\}", sub, a["path"])


def test_DINAMIK_har_rol_har_amal_rad_etilishi_MATRITSA_bilan_AYNI(client, staff):
    from fastapi.testclient import TestClient

    from app.core.deps import FULL_ACCESS_ROLES
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)   # 500 — darvozadan O'TGANI (rad emas)
    wrong = []
    checked = 0
    tally = {True: 0, False: 0}
    for role in ROLES:
        perms = _role_perms(role)
        for name, a in sorted(_actions().items()):
            expected_denied = (role not in FULL_ACCESS_ROLES and bool(a["any_of"])
                               and not (set(a["any_of"]) & perms))
            kw = {"headers": staff[role], "params": a.get("query") or None}
            if a["method"] in {"POST", "PATCH", "PUT"}:
                kw["json"] = {}   # bo'sh tana: validatsiya darvozadan KEYIN, hech narsa yozilmaydi
            r = c.request(a["method"], _url(a), **kw)
            denied = r.status_code == 403 and r.headers.get("X-Error-Code") == "PERMISSION_DENIED"
            checked += 1
            tally[denied] += 1
            if denied != expected_denied:
                wrong.append(f"{role:13} {name:40} kutilgan={'RAD' if expected_denied else 'OCHIQ'} "
                             f"haqiqiy={r.status_code} {r.headers.get('X-Error-Code')}")
            assert r.status_code != 401, f"{role} {name}: token rad etildi — test sozlamasi xato"
    assert checked == len(ROLES) * len(_actions())
    # Vakuum emas: har ikki natija ham haqiqatan kuzatilgan (kassir/omborchi rad etiladi, ega o'tadi).
    assert tally[True] >= 40 and tally[False] >= 150, tally
    assert not wrong, "matritsa ⇔ server darvozasi mos emas:\n" + "\n".join(wrong)


def test_DINAMIK_override_ruxsati_ham_hisobga_olinadi(client, staff):
    """Override (Xodimlar sahifasidagi toggle) bilan berilgan/olingan ruxsat — matritsa
    semantikasi `effective_permissions` ga tayanadi (mobil `/auth/context.permissions`)."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.auth import Employee, EmployeePermission, Permission
    c = TestClient(app, raise_server_exceptions=False)
    hdr = staff["omborchi"]
    with _db() as db:
        tok = hdr["Authorization"].split(" ", 1)[1]
        from app.core.security import decode_token
        eid = uuid.UUID(decode_token(tok)["sub"])
        e = db.get(Employee, eid)
        perm = {p.code: p.id for p in db.query(Permission).all()}
        db.add(EmployeePermission(employee_id=e.id, permission_id=perm["hisobot.view"], allowed=True))
        db.add(EmployeePermission(employee_id=e.id, permission_id=perm["ombor.edit"], allowed=False))
        db.commit()
    try:
        ctx = c.get(PREFIX + "/auth/context", headers=hdr).json()
        assert "hisobot.view" in ctx["permissions"] and "ombor.edit" not in ctx["permissions"]
        acts = _actions()
        r = c.get(_url(acts["reports.overview"]), headers=hdr)
        assert r.status_code == 200, r.text
        r = c.post(_url(acts["stock.writeoff"]), headers=hdr, json={})
        assert r.status_code == 403 and r.headers.get("X-Error-Code") == "PERMISSION_DENIED"
    finally:
        with _db() as db:
            db.query(EmployeePermission).filter(EmployeePermission.employee_id == eid).delete()
            db.commit()
