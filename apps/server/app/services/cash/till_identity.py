# -*- coding: utf-8 -*-
"""Cash Ledger — PHYSICAL TILL / SAFE identity (single source of truth).

REAL fizik model (operator tomonidan tasdiqlangan): BIR FILIAL != BIR TILL.

  Branch
  ├── Checkout/Kassa 1  -> alohida fizik cash drawer -> TILL
  ├── Checkout/Kassa 2  -> alohida fizik cash drawer -> TILL
  ├── Checkout/Kassa N  -> alohida fizik cash drawer -> TILL
  └── Admin seyfi        -> umumiy SAFE (odatda 1 branch = 1 SAFE)

Qoidalar:
  * TILL identity = tenant + branch + FIZIK CHECKOUT (terminal/checkout), branch-only EMAS.
  * Kassir TILL emas. Kassir almashadi; fizik drawer/TILL o'zgarmaydi. Cash custody TILL'da.
  * Fizik checkout aniqlash manbai (ustuvorlik): OPERATOR_MAPPING > TERMINAL > AMBIGUOUS.
  * "Ko'p kassir = ko'p TILL" HECH QACHON taxmin qilinmaydi. Faqat fizik checkout dalili
    (terminal_id) yoki explicit operator mapping. Dalil yo'q -> AMBIGUOUS (BLOCK; operator mapping shart).

Fizik-identity ratifikatsiya qilingan `cash.cash_accounts` SXEMASINI O'ZGARTIRMASDAN `label` ustunида
saqlanadi (schema deploy-safe; label ilgari ham "fizik-identity ref" edi). Konvensiya (deterministik,
auditable, parseable):
    TILL:  label = "TILL code=<checkout_code> terminal=<terminal_uuid|NONE>"
    SAFE:  label = "SAFE code=<checkout_code>"
`checkout_code` = (tenant, branch) doirasida BARQAROR yagona identity (idempotency kaliti); `terminal`
= ixtiyoriy legacy binding (runtime/backfill exact resolution uchun).
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash import CashAccount
from app.models.org import Branch, Terminal
from app.models.shifts import Shift

# ── Label konvensiyasi (yagona quruvchi/parser) ──────────────────────────────
_TILL_RE = re.compile(r"^TILL code=(?P<code>\S+)(?: terminal=(?P<term>\S+))?$")
_SAFE_RE = re.compile(r"^SAFE code=(?P<code>\S+)$")
_NONE = "NONE"


def till_label(checkout_code: str, terminal_id=None) -> str:
    return f"TILL code={checkout_code} terminal={terminal_id if terminal_id else _NONE}"


def safe_label(checkout_code: str = "SAFE") -> str:
    return f"SAFE code={checkout_code}"


def parse_label(label: str | None) -> dict | None:
    """label -> {"kind","checkout_code","terminal_id"} yoki None (parse bo'lmasa).

    Eski/label-siz TILL (label None yoki eski "BRANCH:*" konvensiyasi) -> LEGACY sifatida qaytadi
    (checkout_code=label|"LEGACY", terminal_id=None) — bitta-TILL filial uchun izchil ishlaydi."""
    if not label:
        return {"kind": "LEGACY", "checkout_code": "LEGACY", "terminal_id": None}
    m = _TILL_RE.match(label)
    if m:
        term = m.group("term")
        tid = None
        if term and term != _NONE:
            try:
                tid = uuid.UUID(term)
            except ValueError:
                tid = None
        return {"kind": "TILL", "checkout_code": m.group("code"), "terminal_id": tid}
    m = _SAFE_RE.match(label)
    if m:
        return {"kind": "SAFE", "checkout_code": m.group("code"), "terminal_id": None}
    return {"kind": "LEGACY", "checkout_code": label, "terminal_id": None}


def account_terminal_id(acc: CashAccount):
    p = parse_label(acc.label)
    return p["terminal_id"] if p else None


def account_checkout_code(acc: CashAccount) -> str:
    p = parse_label(acc.label)
    return p["checkout_code"] if p else "LEGACY"


# ── Account lookups (multi-TILL-safe) ────────────────────────────────────────
def list_tills(db: Session, tenant_id, branch_id) -> list[CashAccount]:
    """(tenant, branch) doirasidagi BARCHA ACTIVE TILL (deterministik: checkout_code bo'yicha)."""
    rows = db.scalars(select(CashAccount).where(
        CashAccount.tenant_id == tenant_id, CashAccount.branch_id == branch_id,
        CashAccount.type == "TILL", CashAccount.status == "ACTIVE")).all()
    return sorted(rows, key=lambda a: account_checkout_code(a))


def find_till_by_terminal(db: Session, tenant_id, branch_id, terminal_id) -> CashAccount | None:
    """terminal_id ga bog'langan ACTIVE TILL (NOYOB moslik) — aks holда None."""
    if terminal_id is None:
        return None
    tid = terminal_id if isinstance(terminal_id, uuid.UUID) else uuid.UUID(str(terminal_id))
    matches = [a for a in list_tills(db, tenant_id, branch_id) if account_terminal_id(a) == tid]
    return matches[0] if len(matches) == 1 else None


def find_till_by_checkout(db: Session, tenant_id, branch_id, checkout_code: str) -> CashAccount | None:
    for a in list_tills(db, tenant_id, branch_id):
        if account_checkout_code(a) == checkout_code:
            return a
    return None


def find_safe(db: Session, tenant_id, branch_id) -> CashAccount | None:
    return db.scalars(select(CashAccount).where(
        CashAccount.tenant_id == tenant_id, CashAccount.branch_id == branch_id,
        CashAccount.type == "SAFE", CashAccount.status == "ACTIVE")).first()


def resolve_till_exact(db: Session, tenant_id, branch_id, *, terminal_id=None):
    """GUARDED exact resolver (runtime + backfill). QAYTARADI: (CashAccount|None, reason).

      0 TILL             -> (None, "no-till")               # xaritalanmagan -> guarded no-op
      1 TILL             -> (till, "single-checkout")        # yagona fizik drawer -> aniq
      >1 TILL + terminal -> terminal moslik bo'lса (till, "terminal") aks holда (None, "unresolved-...")
      >1 TILL + terminal yo'q -> (None, "ambiguous-no-terminal")

    HECH QACHON ko'p-TILL filialда ixtiyoriy .first() TANLAMAYDI (jimgina branch-default fallback YO'Q)."""
    tills = list_tills(db, tenant_id, branch_id)
    if not tills:
        return None, "no-till"
    if len(tills) == 1:
        return tills[0], "single-checkout"
    if terminal_id is None:
        return None, "ambiguous-no-terminal"
    match = find_till_by_terminal(db, tenant_id, branch_id, terminal_id)
    if match is not None:
        return match, "terminal"
    return None, "unresolved-terminal-no-match"


# ── Operator mapping (explicit fizik drawer deklaratsiyasi) ──────────────────
@dataclass
class OperatorTill:
    checkout_code: str
    terminal_id: uuid.UUID | None
    label: str = ""


@dataclass
class OperatorBranchMapping:
    branch_id: uuid.UUID
    safe: bool = True
    tills: list[OperatorTill] = field(default_factory=list)


@dataclass
class OperatorMapping:
    branches: dict[uuid.UUID, OperatorBranchMapping] = field(default_factory=dict)
    source_path: str | None = None

    def for_branch(self, branch_id) -> OperatorBranchMapping | None:
        bid = branch_id if isinstance(branch_id, uuid.UUID) else uuid.UUID(str(branch_id))
        return self.branches.get(bid)


class MappingError(ValueError):
    """Operator mapping fayli yaroqsiz (deterministik, fail-loud)."""


def parse_operator_mapping(data: dict, *, source_path: str | None = None) -> OperatorMapping:
    """Operator mapping dict -> OperatorMapping. Qat'iy validatsiya (fail loud):
    branch UUID, till code (tenant/branch doirasida) NOYOB, terminal_id uuid|null."""
    if not isinstance(data, dict) or "branches" not in data or not isinstance(data["branches"], dict):
        raise MappingError("mapping: top-level 'branches' obyekti kerak")
    out = OperatorMapping(source_path=source_path)
    for braw, spec in data["branches"].items():
        try:
            bid = uuid.UUID(str(braw))
        except ValueError as e:
            raise MappingError(f"mapping: branch key noto'g'ri UUID: {braw!r}") from e
        if not isinstance(spec, dict):
            raise MappingError(f"mapping: branch {braw} qiymati obyekt bo'lishi kerak")
        safe = bool(spec.get("safe", True))
        tills_raw = spec.get("tills", [])
        if not isinstance(tills_raw, list) or not tills_raw:
            raise MappingError(f"mapping: branch {braw} kamida bitta 'tills' bandini talab qiladi")
        seen_codes: set[str] = set()
        tills: list[OperatorTill] = []
        for t in tills_raw:
            if not isinstance(t, dict) or not str(t.get("code", "")).strip():
                raise MappingError(f"mapping: branch {braw} till bandida 'code' majburiy")
            code = str(t["code"]).strip()
            if " " in code or "=" in code:
                raise MappingError(f"mapping: till code {code!r} bo'sh joy/'=' ni o'z ichiga ololmaydi")
            if code in seen_codes:
                raise MappingError(f"mapping: branch {braw} ichida till code takrorlangan: {code!r}")
            seen_codes.add(code)
            term_raw = t.get("terminal_id", None)
            tid = None
            if term_raw not in (None, "", "null"):
                try:
                    tid = uuid.UUID(str(term_raw))
                except ValueError as e:
                    raise MappingError(f"mapping: branch {braw} till {code} terminal_id noto'g'ri UUID: "
                                       f"{term_raw!r}") from e
            tills.append(OperatorTill(checkout_code=code, terminal_id=tid,
                                      label=str(t.get("label", "") or "")))
        # terminal_id lar (berilганlar) branch ichida NOYOB bo'lishi kerak (bir drawer = bir terminal)
        terms = [t.terminal_id for t in tills if t.terminal_id is not None]
        if len(terms) != len(set(terms)):
            raise MappingError(f"mapping: branch {braw} ichida terminal_id takrorlangan")
        out.branches[bid] = OperatorBranchMapping(branch_id=bid, safe=safe, tills=tills)
    return out


def load_operator_mapping(path: str) -> OperatorMapping:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return parse_operator_mapping(data, source_path=path)


def _identity_key(checkout_code: str, terminal_id) -> str:
    """Fizik drawer IDENTITY kaliti: terminal bog'langan bo'lса terminal (resolution shu orqali; code
    faqat label), aks holда code. Shu bois turli code + BIR XIL terminal MOS deb sanaladi."""
    return f"term:{terminal_id}" if terminal_id else f"code:{checkout_code}"


def mapping_db_mismatches(db: Session, tenant_id, mapping: "OperatorMapping | None") -> list[dict]:
    """Operator mapping bilan HAQIQATAN provisionланган DB TILL'lari MOS kelaяptimi (fizik identity).

    §review topilma: backfill/verify'ga berilган --mapping resolution'ни O'ZGARTIRMAYDI (resolve_account
    provisionланган cash_accounts'ni o'qiydi). Agar DB accounts mapping'дан FARQ qilса (masalan operator
    mapping'siz TERMINAL-provision qildi, keyin boshqa mapping bilan backfill) — jimgina divergensiya.
    Bu funksiya HAR mapped branch uchun DB checkout_code/terminal to'plamini mapping bilan solishtiradi;
    provisionланган (bo'sh bo'lmagan) branch mos kelmasa -> mismatch (backfill BLOCK qiladi). Provision
    hali qilinmagan branch (0 TILL) taqqoslanmaydi (plan-level AMBIGUOUS gate uni alohida ushlaydi)."""
    out: list[dict] = []
    if mapping is None:
        return out
    for bid, bm in mapping.branches.items():
        br = db.get(Branch, bid)
        if br is None:
            continue
        tenant = tenant_id if tenant_id is not None else br.company_id
        if br.company_id != tenant:
            continue
        tills = list_tills(db, tenant, bid)
        if not tills:
            continue   # provision qilinmagan -> AMBIGUOUS gate ushlaydi; bu yerда solishtirmaymiz
        # FIZIK IDENTITY bo'yicha solishtiramiz: TERMINAL-bog'langan TILL terminal bilan aniqlanadi
        # (code — faqat label; resolution terminal orqali boradi, shu bois TERM-<uuid> vs friendly "TILL-01"
        # BIR XIL terminalда MOS deb sanaladi — false-block yo'q). Terminal yo'q -> code identity.
        db_keys = {_identity_key(account_checkout_code(a), account_terminal_id(a)) for a in tills}
        map_keys = {_identity_key(t.checkout_code, t.terminal_id) for t in bm.tills}
        if db_keys != map_keys:
            out.append({"branch_id": str(bid),
                        "db_identity": sorted(db_keys), "mapping_identity": sorted(map_keys),
                        "db_count": len(tills), "mapping_count": len(bm.tills)})
    return out


# ── Fizik checkout aniqlash (phase0/provision/preflight/compare yagona manbai) ─
@dataclass
class Checkout:
    checkout_code: str
    terminal_id: uuid.UUID | None
    label_human: str
    source: str        # OPERATOR_MAPPING | TERMINAL
    confidence: str     # HIGH


# aniqlash natijasi kodlari
SRC_OPERATOR = "OPERATOR_MAPPING"
SRC_EXISTING = "EXISTING"          # allaqачон provisionланган ACTIVE TILL(lar) -> drawer(lar) hал qilingan
SRC_TERMINAL = "TERMINAL"
SRC_AMBIGUOUS = "AMBIGUOUS"
SRC_NO_ACTIVITY = "NO_ACTIVITY"


def _branch_terminals(db: Session, branch_id) -> dict:
    """Filialda TIRIK smenalarda ko'rinган distinct terminal_id -> Terminal (nom uchun)."""
    tids = [r[0] for r in db.execute(select(Shift.terminal_id).where(
        Shift.branch_id == branch_id, Shift.terminal_id.isnot(None),
        Shift.deleted_at.is_(None)).distinct()).all()]
    out = {}
    for tid in tids:
        term = db.get(Terminal, tid)
        out[tid] = (term.name if term is not None else str(tid))
    return out


def _has_shift_history(db: Session, branch_id) -> bool:
    return db.execute(select(Shift.id).where(
        Shift.branch_id == branch_id, Shift.deleted_at.is_(None)).limit(1)).first() is not None


def detect_physical_checkouts(db: Session, tenant_id, branch, *, mapping: OperatorMapping | None = None):
    """Filial uchun fizik checkout(lar)ni aniqlaydi. QAYTARADI: (checkouts, source, confidence, detail).

    Ustuvorlik: OPERATOR_MAPPING (operator avtoriteti) > TERMINAL (dalil) > AMBIGUOUS/NO_ACTIVITY.
    Currency/branch validatsiyasini CHAQIRUVCHI qiladi (bu funksiya faqat fizik checkout topadi)."""
    branch_id = branch.id
    # 1) OPERATOR_MAPPING — eng yuqori avtoritet.
    bm = mapping.for_branch(branch_id) if mapping is not None else None
    if bm is not None:
        checkouts = [Checkout(checkout_code=t.checkout_code, terminal_id=t.terminal_id,
                              label_human=(t.label or t.checkout_code), source=SRC_OPERATOR,
                              confidence="HIGH") for t in bm.tills]
        return checkouts, SRC_OPERATOR, "HIGH", f"operator mapping: {len(checkouts)} checkout"
    # 2) EXISTING — allaqачon provisionланган ACTIVE TILL(lar) fizik drawer'ni ANIQLAB BO'LGAN
    #    (idempotent-aware: qayta-provision/backfill AMBIGUOUS demasин). Fizik identity label'дан.
    existing = list_tills(db, tenant_id, branch_id)
    if existing:
        checkouts = [Checkout(checkout_code=account_checkout_code(a), terminal_id=account_terminal_id(a),
                              label_human=(a.label or account_checkout_code(a)), source=SRC_EXISTING,
                              confidence="HIGH") for a in existing]
        return checkouts, SRC_EXISTING, "HIGH", f"{len(checkouts)} existing provisioned TILL(s)"
    # 3) TERMINAL — legacy dalil (distinct terminal = alohida fizik drawer).
    terms = _branch_terminals(db, branch_id)
    if terms:
        checkouts = [Checkout(checkout_code=f"TERM-{tid}", terminal_id=tid, label_human=name,
                              source=SRC_TERMINAL, confidence="HIGH")
                     for tid, name in sorted(terms.items(), key=lambda kv: str(kv[0]))]
        return checkouts, SRC_TERMINAL, "HIGH", f"terminal evidence: {len(checkouts)} distinct terminal(s)"
    # 3) Dalil yo'q.
    if _has_shift_history(db, branch_id):
        # cash/shift tarixi BOR, lekin terminal_id NULL -> fizik drawer aniqlanmaydi -> AMBIGUOUS (BLOCK).
        return [], SRC_AMBIGUOUS, "AMBIGUOUS", ("shift history but terminal_id NULL and no operator "
                                                "mapping — physical drawer(s) undecidable")
    # cash tarixи yo'q -> migration blocker EMAS (backfill legasi yo'q); operator ishlashдан oldin map qiladi.
    return [], SRC_NO_ACTIVITY, "INFO", "no shift history — provide operator mapping before it transacts"
