# -*- coding: utf-8 -*-
"""Cash Migration CLI · CURRENT TILL PROVISIONING PLAN (STRICTLY READ-ONLY, BRANCH-SCOPED).

Operator (Windows/Railway — `railway run` EMAS, chunki Windows Railway internal hostname'ini resolve
qilolmaydi; `ssh` ishlatiladi):
    railway.cmd ssh --service savdoos -- python -m app.tools.cash_till_plan ^
        --company-id <UUID> --branch-id <UUID> --code TILL-01

`cash_provision` dan FARQI (nega alohida tool kerak bo'ldi):
  · cash_provision KOMPANIYaning BARCHA filiallarini aylanadi — BITTA filialga cheklab bo'lmaydi;
  · cash_provision har filialga SAFE ham TAKLIF qiladi (mapping'да `"safe": false` bo'lmasa);
  · cash_provision dalil topilmasa TERMINAL tarixidan fizik kassa SONINI KELTIRIB CHIQARADI
    (`TERM-<uuid>` kodli kassalar) — bu "kassa sonini TARIXDAN taxmin qilma" qoidasini buzadi.
Bu tool esa: BITTA kompaniya + BITTA filial, SAFE YO'Q, kod OPERATOR tomonidan aytiladi, TARIXGA
umuman qaramaydi.

═══ NIMA QILMAYDI (qat'iy) ══════════════════════════════════════════════════
  · APPLY REJIMI YO'Q — bu CLI'да `--apply` degan bayroq UMUMAN mavjud emas.
  · TILL/SAFE YARATMAYDI · cutover_at (T0) O'RNATMAYDI · ledger'ga yozmaydi · backfill qilmaydi
  · smena ochmaydi/yopmaydi/biriktirmaydi · cash mode'ni o'zgartirmaydi
  · TARIXIY identity'ni HAL QILMAYDI (817 ta dalilsiz qator SHUNDAYLIGICHA qoladi)
  · sir (DATABASE_URL/host/user/parol) chiqarmaydi
Faqat SELECT; oxirida session ROLLBACK + close.

═══ JORIY vs TARIXIY (ARALASHTIRILMAYDI) ════════════════════════════════════
  BUGUN kassa yaratish  -> FAQAT T0'dan KEYINGI runtime'ni ishlatadi (NO_ACTIVE_TILL yo'qoladi).
  TARIXIY drawer identity -> BUGUNGI kassa bilan HAL BO'LMAYDI va bu tool uni HISOBLAMAYDI.

Exit: 0 = yaratiladigan kassa(lar) bor va nizo yo'q · 2 = hammasi allaqachon mavjud (NO-OP)
· 3 = NIZO (yaratmang) · 1 = usage.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from app.models.cash import CashAccount
from app.models.org import Branch, Company, Terminal
from app.services.cash import till_identity as _ti
from app.tools import _common as C

KIND = "CASH_TILL_PROVISION_PLAN"

# Reja harakatlari
A_CREATE = "CREATE"
A_EXISTS = "EXISTS_NOOP"
A_CONFLICT = "CONFLICT"

HISTORICAL_NOTE = ("BUGUN kassa yaratish TARIXIY drawer identity'ni HAL QILMAYDI: eski qatorlar "
                   "dalilsiz bo'lsa dalilsizligicha qoladi, backfill qilinmaydi, eski smenalar "
                   "biriktirilmaydi, T0 o'rnatilmaydi. Bu FAQAT joriy runtime provisioning.")


def _parse_code_spec(raw: str) -> tuple:
    """`TILL-01` yoki `TILL-01=<terminal-uuid>` -> (code, terminal_id|None). Fail loud."""
    code, _, term = str(raw).partition("=")
    code = code.strip()
    if not code or " " in code:
        raise ValueError(f"kassa kodi noto'g'ri (bo'sh joysiz bo'lsin): {raw!r}")
    tid = None
    if term.strip():
        try:
            tid = uuid.UUID(term.strip())
        except ValueError as e:
            raise ValueError(f"terminal UUID noto'g'ri: {term.strip()!r}") from e
    return code, tid


# ── Tekshiruvlar (hammasi READ-ONLY) ─────────────────────────────────────────
def _company_check(db, company_id) -> dict:
    co = db.get(Company, company_id)
    if co is None or co.deleted_at is not None:
        return {"ok": False, "reason": "COMPANY_NOT_FOUND", "company_id": str(company_id)}
    cur = (co.currency or "").strip().upper()
    return {"ok": True, "company_id": str(co.id), "code": co.code, "name": co.name,
            "currency": cur or None,
            "currency_ok": len(cur) == 3,
            "currency_note": ("kompaniya valyutasi noaniq — POST /tills 'UZS' ga tushadi; "
                              "operator valyutani ANIQ bersin" if len(cur) != 3 else "")}


def _branch_check(db, co_row, branch_id) -> dict:
    br = db.get(Branch, branch_id)
    if br is None:
        return {"ok": False, "reason": "BRANCH_NOT_FOUND", "branch_id": str(branch_id)}
    if str(br.company_id) != co_row["company_id"]:
        return {"ok": False, "reason": "BRANCH_WRONG_COMPANY", "branch_id": str(branch_id),
                "belongs_to": str(br.company_id)}
    if br.deleted_at is not None:
        return {"ok": False, "reason": "BRANCH_DELETED", "branch_id": str(branch_id)}
    return {"ok": True, "branch_id": str(br.id), "code": br.code, "name": br.name,
            "is_active": bool(br.is_active)}


def _existing_accounts(db, company_id, branch_id) -> list:
    """Shu filialdagi BARCHA cash hisoblar — ACTIVE ham, ARCHIVED ham (dublikat nizosi uchun SHART)."""
    rows = db.query(CashAccount).filter(CashAccount.tenant_id == company_id,
                                        CashAccount.branch_id == branch_id).all()
    out = []
    for a in rows:
        p = _ti.parse_label(a.label) or {}
        out.append({"id": str(a.id), "type": a.type, "status": a.status,
                    "code": p.get("checkout_code"), "label": a.label, "currency": a.currency,
                    "terminal_id": (str(p.get("terminal_id")) if p.get("terminal_id") else None)})
    return sorted(out, key=lambda r: (r["type"], str(r["code"])))


def _code_used_on_other_branches(db, company_id, branch_id, code) -> list:
    """Bir xil kod BOSHQA filialda — kod (tenant, branch) doirasida, shu bois bu QONUNIY.
    Baribir OCHIQ ko'rsatiladi (operator adashmasin)."""
    out = []
    for a in db.query(CashAccount).filter(CashAccount.tenant_id == company_id,
                                          CashAccount.type == "TILL",
                                          CashAccount.branch_id != branch_id).all():
        if _ti.account_checkout_code(a) == code:
            out.append({"id": str(a.id), "branch_id": str(a.branch_id), "status": a.status})
    return out


def _branch_terminals(db, branch_id) -> list:
    """Shu filialning terminal yozuvlari (JORIY holat). Bu FAQAT ma'lumot uchun — terminaldan
    TARIXIY drawer identity KELTIRIB CHIQARILMAYDI (RC10 qoidasi: terminal binding o'zgaruvchan)."""
    rows = db.query(Terminal).filter(Terminal.branch_id == branch_id,
                                     Terminal.deleted_at.is_(None)).all()
    return [{"id": str(t.id), "name": t.name, "is_active": bool(t.is_active),
             "device_uuid": t.device_uuid} for t in rows]


def _terminal_check(db, branch_id, terminal_id, existing) -> dict:
    if terminal_id is None:
        return {"requested": None, "ok": True, "note": "terminal bog'lanmaydi (ixtiyoriy)"}
    t = db.get(Terminal, terminal_id)
    if t is None or t.deleted_at is not None:
        return {"requested": str(terminal_id), "ok": False, "reason": "TERMINAL_NOT_FOUND"}
    if str(t.branch_id) != str(branch_id):
        return {"requested": str(terminal_id), "ok": False, "reason": "TERMINAL_WRONG_BRANCH",
                "belongs_to_branch": str(t.branch_id)}
    if not t.is_active:
        return {"requested": str(terminal_id), "ok": False, "reason": "TERMINAL_INACTIVE",
                "name": t.name}
    taken = [r for r in existing
             if r["type"] == "TILL" and r["status"] == "ACTIVE" and r["terminal_id"] == str(terminal_id)]
    if taken:
        return {"requested": str(terminal_id), "ok": False, "reason": "TERMINAL_ALREADY_BOUND",
                "bound_to": [r["id"] for r in taken]}
    return {"requested": str(terminal_id), "ok": True, "name": getattr(t, "name", None)}


def _plan_one(db, company_id, branch_id, code, terminal_id, currency, existing) -> dict:
    """Bitta so'ralган kassa uchun reja. HECH NARSA yozmaydi."""
    row = {"code": code, "terminal_id": (str(terminal_id) if terminal_id else None),
           "currency": currency, "notes": []}
    same = [r for r in existing if r["type"] == "TILL" and r["code"] == code]
    active = [r for r in same if r["status"] == "ACTIVE"]
    archived = [r for r in same if r["status"] != "ACTIVE"]

    term = _terminal_check(db, branch_id, terminal_id, existing)
    row["terminal_check"] = term

    other = _code_used_on_other_branches(db, company_id, branch_id, code)
    if other:
        row["notes"].append(f"shu kod BOSHQA filial(lar)da ham bor ({len(other)} ta) — kod "
                            f"(tenant, filial) doirasida, shu bois bu QONUNIY, nizo EMAS.")
        row["same_code_other_branches"] = other

    if active:
        a = active[0]
        row["existing_id"] = a["id"]
        if terminal_id is not None and not term["ok"]:
            # Mavjud kassa bo'lsa ham, so'ralgan terminal yaroqsiz bo'lsa buni JIM O'TKAZMAYMIZ.
            row["notes"].append(f"so'ralgan terminal ishlatib bo'lmaydi: {term['reason']}")
        if a["currency"] != currency:
            row["action"] = A_CONFLICT
            row["reason"] = "CURRENCY_MISMATCH"
            row["detail"] = (f"'{code}' ACTIVE mavjud, lekin valyutasi {a['currency']} — so'ralган "
                             f"{currency} bilan MOS EMAS. Yaratmang; valyutani aniqlashtiring.")
            return row
        row["action"] = A_EXISTS
        row["detail"] = (f"'{code}' shu filialda ACTIVE holda ALLAQACHON bor (id={a['id']}). "
                         f"POST /tills IDEMPOTENT — o'shani qaytaradi, yangi qator yaratmaydi.")
        return row

    if archived:
        row["action"] = A_CONFLICT
        row["reason"] = "ARCHIVED_SAME_CODE"
        row["archived_ids"] = [r["id"] for r in archived]
        row["detail"] = (
            f"'{code}' shu filialda ARCHIVED holda bor ({', '.join(r['id'] for r in archived)}). "
            "DIQQAT: idempotentlik FAQAT ACTIVE hisoblar bo'yicha tekshiriladi (list_tills "
            "status='ACTIVE' filtri), (tenant, filial, kod) uchun BAZA darajasida unique constraint "
            "YO'Q — shu bois yangi yaratsangiz BIR XIL KODLI IKKI qator paydo bo'ladi (identity "
            "chalkashadi). To'g'ri yo'l: eski kassani QAYTA FAOLLASHTIRING "
            "(PATCH /tills/<id> {active:true}) yoki BOSHQA kod tanlang.")
        return row

    if not term["ok"]:
        row["action"] = A_CONFLICT
        row["reason"] = term["reason"]
        row["detail"] = f"terminal bog'lash mumkin emas: {term['reason']}"
        return row

    row["action"] = A_CREATE
    row["detail"] = (f"YANGI TILL yaratiladi: code={code}, currency={currency}, "
                     f"terminal={row['terminal_id'] or 'NONE'}, status=ACTIVE. "
                     f"Saqlanadigan label = {_ti.till_label(code, terminal_id)!r}")
    return row


def build_plan(db, *, company_id, branch_id, code_specs, currency=None) -> dict:
    co = _company_check(db, company_id)
    rep = {"kind": KIND, "read_only": True, "apply_mode": "NONE",
           "scope": {"companies": 1, "branches": 1,
                     "company_id": str(company_id), "branch_id": str(branch_id),
                     "guarantee": ("REJA AYNAN bitta kompaniya + bitta filial uchun tuziladi va "
                                   "hech narsa YOZILMAYDI. DIQQAT: bir xil kod boshqa filialda ham "
                                   "borligini KO'RSATISH uchun shu tenant ichidagi boshqa "
                                   "filiallar O'QILADI (faqat SELECT); boshqa tenant UMUMAN "
                                   "o'qilmaydi.")},
           "company": co, "historical_separation": HISTORICAL_NOTE}
    if not co["ok"]:
        rep["verdict"] = "REFUSED"
        return rep
    br = _branch_check(db, co, branch_id)
    rep["branch"] = br
    if not br["ok"]:
        rep["verdict"] = "REFUSED"
        return rep

    cur = (currency or co["currency"] or "UZS").strip().upper()[:3]
    rep["currency_resolution"] = {
        "requested": currency, "company_currency": co["currency"], "effective": cur,
        "source": ("--currency" if currency else ("company" if co["currency"] else "UZS fallback"))}

    existing = _existing_accounts(db, company_id, branch_id)
    rep["existing_accounts"] = existing
    rep["terminals"] = _branch_terminals(db, branch_id)
    rep["terminal_policy"] = ("Terminal bog'lash IXTIYORIY va FAQAT joriy runtime uchun. Terminaldan "
                              "TARIXIY drawer identity KELTIRIB CHIQARILMAYDI. Filialda 2+ "
                              "bog'lanmagan ACTIVE TILL bo'lsa smena ochish noaniq bo'ladi.")
    rep["existing_active_tills"] = sum(1 for r in existing if r["type"] == "TILL" and r["status"] == "ACTIVE")
    rep["existing_active_safes"] = sum(1 for r in existing if r["type"] == "SAFE" and r["status"] == "ACTIVE")
    # SAFE hech qachon REJALASHTIRILMAYDI — faqat ko'rsatiladi (§SAFE avtomatik yaratilmaydi).
    rep["safe_policy"] = {"planned": 0, "auto_create": False,
                          "note": ("SAFE bu tool tomonidan HECH QACHON rejalashtirilmaydi/yaratilmaydi. "
                                   "SAFE faqat inkassa (TILL->SAFE) yoki SAFE custody ishlatilsa kerak.")}

    plan = []
    seen = set()
    for code, tid in code_specs:
        if code in seen:
            plan.append({"code": code, "action": A_CONFLICT, "reason": "DUPLICATE_IN_REQUEST",
                         "detail": "bir xil kod so'rovda ikki marta berilgan", "notes": []})
            continue
        seen.add(code)
        plan.append(_plan_one(db, company_id, branch_id, code, tid, cur, existing))
    rep["plan"] = plan
    rep["to_create"] = sum(1 for p in plan if p["action"] == A_CREATE)
    rep["already_exists"] = sum(1 for p in plan if p["action"] == A_EXISTS)
    rep["conflicts"] = sum(1 for p in plan if p["action"] == A_CONFLICT)

    if rep["conflicts"]:
        rep["verdict"] = "CONFLICT"
    elif rep["to_create"]:
        rep["verdict"] = "READY_TO_APPLY"
    else:
        rep["verdict"] = "NOTHING_TO_DO"
    # Ko'p-kassa ogohlantirishi (terminal bog'lanmasa smena ochish noaniq bo'lib qoladi)
    total_after = rep["existing_active_tills"] + rep["to_create"]
    unbound = [p for p in plan if p["action"] == A_CREATE and not p["terminal_id"]]
    unbound += [r for r in existing
                if r["type"] == "TILL" and r["status"] == "ACTIVE" and not r["terminal_id"]]
    rep["multi_till_warning"] = (
        {"active_tills_after": total_after, "unbound": len(unbound),
         "note": ("Filialda 2+ ACTIVE TILL bo'lib, ular terminalga BOG'LANMAGAN bo'lsa, terminal_id "
                  "yubormaydigan klientlar uchun smena ochish NOANIQ bo'ladi "
                  "(resolve_till_exact -> 'ambiguous-no-terminal'). 2 ta drawer ishlatishdan OLDIN "
                  "terminallarni bog'lang.")}
        if total_after > 1 and len(unbound) > 1 else
        {"active_tills_after": total_after, "unbound": len(unbound), "note": "ogohlantirish yo'q"})
    return rep


# ── Chop etish ───────────────────────────────────────────────────────────────
def _print_human(rep: dict) -> None:
    co, br = rep["company"], rep.get("branch") or {}
    C.out("")
    C.out(f"KOMPANIYA: {co.get('code')}  {co.get('name', '')}  ok={str(co['ok']).lower()}"
          + ("" if co["ok"] else f"  ({co.get('reason')})"))
    if co["ok"]:
        C.out(f"   valyuta: {co.get('currency') or 'NOANIQ'}   ok={str(co['currency_ok']).lower()}"
              + (f"  — {co['currency_note']}" if co.get("currency_note") else ""))
    C.out(f"FILIAL:    {br.get('code')}  ok={str(br.get('ok')).lower()}"
          + ("" if br.get("ok") else f"  ({br.get('reason')})"))
    if not (co["ok"] and br.get("ok")):
        return
    C.out(f"   is_active={str(br['is_active']).lower()}   branch_id={br['branch_id']}")
    cr = rep["currency_resolution"]
    C.out(f"   ISHLATILADIGAN VALYUTA: {cr['effective']}  (manba: {cr['source']})")
    C.out("")
    C.out(f"MAVJUD HISOBLAR (shu filial, ACTIVE + ARCHIVED): {len(rep['existing_accounts'])}")
    for a in rep["existing_accounts"]:
        C.out(f"   {a['type']:<4} {str(a['code']):<14} {a['status']:<9} {a['currency']}  "
              f"terminal={a['terminal_id'] or 'NONE'}  id={a['id']}")
    if not rep["existing_accounts"]:
        C.out("   (bitta ham yo'q)")
    C.out(f"   ACTIVE TILL={rep['existing_active_tills']}   ACTIVE SAFE={rep['existing_active_safes']}")
    C.out(f"   SAFE: {rep['safe_policy']['note']}")
    C.out("")
    C.out(f"TERMINALLAR (shu filial, o'chirilmagan): {len(rep['terminals'])}")
    for t in rep["terminals"]:
        C.out(f"   id={t['id']}  name={t['name']}  active={str(t['is_active']).lower()}  "
              f"device={t['device_uuid'] or '-'}")
    if not rep["terminals"]:
        C.out("   (terminal yozuvi yo'q — bog'lash mumkin emas; bitta kassa uchun SHART EMAS)")
    C.out(f"   {rep['terminal_policy']}")
    C.out("")
    C.out("REJA (hech narsa yozilmaydi):")
    for p in rep["plan"]:
        C.out(f"   [{p['action']}] {p['code']}")
        C.out(f"       {p.get('detail', '')}")
        tc = p.get("terminal_check") or {}
        if tc.get("requested"):
            C.out(f"       terminal: {tc['requested']}  ok={str(tc.get('ok')).lower()}"
                  + (f"  ({tc.get('reason')})" if not tc.get("ok") else ""))
        for n in p.get("notes", []):
            C.out(f"       INFO: {n}")
    C.out("")
    C.out(f"JAMI: yaratiladi={rep['to_create']}  mavjud(NO-OP)={rep['already_exists']}  "
          f"nizo={rep['conflicts']}")
    mw = rep["multi_till_warning"]
    if mw["note"] != "ogohlantirish yo'q":
        C.out(f"OGOHLANTIRISH: {mw['note']}")
    C.out("")
    C.out(f"TARIX: {rep['historical_separation']}")


def run(db, *, company_id, branch_id, code_specs, currency, as_json: bool) -> int:
    C.set_stdout_json_only(as_json)   # --json: stdout FAQAT JSON (`| jq` uchun); qolgani stderr'ga
    C.guard_never_primary()
    C.require_postgres_cash(db)
    C.print_header("CURRENT TILL PROVISION PLAN (read-only)", mode_label="READ-ONLY",
                   company_id=company_id, db=db,
                   extra={"APPLY MODE": "NONE (mavjud emas)", "BRANCH": str(branch_id)})
    rep = build_plan(db, company_id=company_id, branch_id=branch_id,
                     code_specs=code_specs, currency=currency)
    if as_json:
        C.emit_json(rep)
    else:
        _print_human(rep)
    C.out("")
    v = rep["verdict"]
    if v == "REFUSED":
        C.err(f"VERDICT: REFUSED — {rep['company'].get('reason') or rep.get('branch', {}).get('reason')}")
        return C.EXIT_USAGE
    if v == "CONFLICT":
        C.out(f"VERDICT: CONFLICT — {rep['conflicts']} ta nizo. YARATMANG; avval nizoni hal qiling.")
        return C.EXIT_BLOCK
    if v == "NOTHING_TO_DO":
        C.out("VERDICT: NOTHING_TO_DO — so'ralgan kassa(lar) allaqachon ACTIVE. Apply SHART EMAS.")
        return C.EXIT_REVIEW
    C.out(f"VERDICT: READY_TO_APPLY — {rep['to_create']} ta yangi kassa yaratiladi. "
          f"Apply ALOHIDA qadam (bu tool yozmaydi).")
    return C.EXIT_OK


def main(argv=None, *, session_factory=None, engine=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m app.tools.cash_till_plan",
        description="STRICTLY READ-ONLY, BITTA FILIALGA cheklangan joriy TILL provisioning rejasi. "
                    "Apply rejimi YO'Q.")
    p.add_argument("--company-id", required=True, help="Tenant (UUID) — MAJBURIY.")
    p.add_argument("--branch-id", required=True, help="Filial (UUID) — MAJBURIY (faqat shu filial).")
    p.add_argument("--code", action="append", default=[], metavar="CODE[=TERMINAL_UUID]",
                   help="BUGUN REAL mavjud fizik kassa kodi (masalan TILL-01). Har kassa uchun "
                        "takrorlang. Terminalga bog'lash: TILL-01=<terminal-uuid>.")
    p.add_argument("--currency", default=None, help="Valyuta (3 harf). Berilmasa — kompaniya valyutasi.")
    p.add_argument("--json", action="store_true", help="Rejani JSON sifatida chiqarish.")
    args = p.parse_args(argv)

    try:
        company_id = C.parse_company_id(args.company_id)
        branch_id = C.parse_company_id(args.branch_id)
    except ValueError:
        C.err("USAGE: --company-id va --branch-id to'g'ri UUID bo'lishi kerak.")
        return C.EXIT_USAGE
    if company_id is None or branch_id is None:
        C.err("USAGE: --company-id va --branch-id bo'sh bo'lmasin.")
        return C.EXIT_USAGE
    if not args.code:
        C.err("USAGE: kamida bitta --code kerak. FAQAT bugun REAL mavjud fizik kassalarni bering; "
              "kelajakdagi/zaxira kassa YARATMANG. Kassa soni TARIXDAN taxmin QILINMAYDI.")
        return C.EXIT_USAGE
    try:
        specs = [_parse_code_spec(c) for c in args.code]
    except ValueError as e:
        C.err(f"USAGE: {e}")
        return C.EXIT_USAGE

    eng, db = C.get_engine_and_session(session_factory, engine)
    try:
        return run(db, company_id=company_id, branch_id=branch_id, code_specs=specs,
                   currency=args.currency, as_json=args.json)
    finally:
        db.rollback()   # STRICTLY READ-ONLY: hech qanday yozuv saqlanmaydi
        db.close()
        C.set_stdout_json_only(False)   # global bayroqni TIKLA (boshqa CLI'ga sizib ketmasin)


if __name__ == "__main__":
    sys.exit(main())
