# -*- coding: utf-8 -*-
"""Cash Ledger · HISTORICAL TILL RESOLUTION — tarixiy fizik drawer'ni FAQAT DALIL bilan aniqlash.

ASOSIY ARXITEKTURA QOIDASI:

    BUGUN yaratilgan ACTIVE TILL — o'tmishdagi tranzaksiya AYNAN o'sha fizik drawer'da
    bo'lganini ISBOTLAMAYDI.

        CURRENT TILL PROVISIONING  !=  HISTORICAL TILL EVIDENCE

Ikki TUSHUNCHA qat'iy AJRATILADI:
  A. CURRENT_RUNTIME_TILL      — T0'dan KEYINGI yangi naqd faoliyat uchun (runtime readiness).
                                 `till_identity.resolve_till_exact` / retrofit — ACTIVE TILL talab qiladi.
  B. HISTORICAL_TILL_RESOLUTION — FAQAT legacy backfill uchun (shu modul). ACTIVE bo'lishi SHART EMAS
                                 (naflaqa: nafaqaga chiqqan/ARCHIVED drawer eski qator uchun TO'G'RI javob).

Bugun TILL yaratish A'ni qanoatlantiradi. U B'ni AVTOMATIK qanoatlantirMAYDI.

RUXSAT ETILGAN DALILLAR (§3 yakuniy ierarxiya; birinchi mos kelgani g'olib):
  1. SOURCE_TILL          — manba qatorining O'ZIDA saqlangan till_id (Sale.till_id / Return.till_id)
  2. SHIFT_TILL           — manba.shift_id -> Shift.till_id (tranzaksiya vaqtida yozilgan)
  3. (terminal)           — §4 TAQIQ: terminal->TILL bog'lanishi MUTABLE/versiyalanmagan -> DALIL EMAS
  4. SHADOW_SHIFT_TILL    — zamondosh soya CashMovement -> Shift -> Shift.till_id
                            (identity SHART: soya created_at == manba vaqti VA filial mos)
  5. OPERATOR_SOURCE_MAP  — explicit operator attestatsiyasi: source_type:source_id -> till_id
     OPERATOR_SHIFT_MAP   — explicit operator attestatsiyasi: shift_id -> till_id
  BOSHQA FALLBACK YO'Q.

TAQIQLANGAN (HECH QACHON dalil emas):
  * "branch'da bugun bitta ACTIVE TILL bor"      (single-checkout retroaktiv default)
  * branch default TILL / birinchi ACTIVE TILL
  * "tenant'da bugun bitta faol branch bor"      (branch ham TAXMIN qilinmaydi)
  * kassir default / kassirlar soni
  * bugungi EmployeeBranch bog'lanishi           (temporal ustun YO'Q — bugungi holat, o'tmish emas)
  * terminal_id YOLG'IZ O'ZI (binding mutable: PATCH /tills label'ni qayta yozadi, versiya yo'q)
  * BUGUNGI TILL soni / branch'dagi drawer'lar soni

Dalil topilmasa -> HISTORICAL_TILL_UNKNOWN: leg SKIP qilinadi + REVIEW; account_id HECH QACHON
O'YLAB TOPILMAYDI. Bu T0-oldinga migratsiyani GLOBAL TO'XTATMAYDI (REVIEW, BLOCK emas) — dalil yoki
explicit mapping paydo bo'lguncha o'sha qatorlar avtoritet ledger'dan TASHQARIDA qoladi.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.models.cash import CashAccount
from app.models.enums import CashMovementType
from app.models.org import Branch
from app.models.shifts import CashMovement, Shift
from app.services.cash import till_identity as _ti

# ── Dalil qoidalari (§3 yakuniy ierarxiya; audit metodi nomi ledger/manifestga tushadi) ────
RULE_SOURCE_TILL = "SOURCE_TILL"            # manba qatorida SAQLANGAN till_id
RULE_SHIFT_TILL = "SHIFT_TILL"              # manba.shift_id -> Shift.till_id
RULE_SHADOW_SHIFT = "SHADOW_SHIFT_TILL"     # zamondosh soya -> Shift -> till_id
RULE_OP_SOURCE_MAP = "OPERATOR_SOURCE_MAP"  # operator: source_type:source_id -> till_id
RULE_OP_SHIFT_MAP = "OPERATOR_SHIFT_MAP"    # operator: shift_id -> till_id
RULE_ORDER = (RULE_SOURCE_TILL, RULE_SHIFT_TILL, RULE_SHADOW_SHIFT,
              RULE_OP_SOURCE_MAP, RULE_OP_SHIFT_MAP)

# §4 TERMINAL TAQIQI — ATAYLAB QOIDA YO'Q.
# terminal -> TILL bog'lanishi `cash_accounts.label` MUTABLE satrida saqlanadi
# (till_identity.till_label), `PATCH /tills/{id}` uni QAYTA YOZADI (api/v1/tills.py), DB guard'i
# (cash.fn_guard_cash_account) FAQAT tenant/branch/type/currency/id ni himoya qiladi — label EMAS,
# va eski bog'lanishni saqlaydigan versiyalangan/timestamped yozuv YO'Q. Demak tarixiy terminal_id ->
# BUGUNGI TILL "dalil" emas, MUTABLE JORIY ASSOTSIATSIYA: terminal keyinchalik boshqa drawer'ga
# ko'chirilsa eski qator NOTO'G'RI drawer'ga biriktirilardi. Shu bois terminal_id YOLG'IZ O'ZI
# hech qachon tarixiy identity BERMAYDI. (Immutable/versiyalangan binding paydo bo'lsa qayta ko'riladi.)
TERMINAL_EVIDENCE_SUPPORTED = False

# Hal qilinmagan tarixiy identity (BLOCK EMAS — skip + REVIEW)
HISTORICAL_TILL_UNKNOWN = "HISTORICAL_TILL_UNKNOWN"
# Runtime (T0-keyin) uchun TILL yo'q — BOSHQA masala, tarixiy identity bilan ARALASHTIRILMAYDI
CURRENT_TILL_NOT_PROVISIONED = "CURRENT_TILL_NOT_PROVISIONED"

_MAP_KIND = "HISTORICAL_TILL_EVIDENCE"
_MAP_VERSION = 1

# Soya prefikslari (phase1 bilan izchil bo'lishi uchun shu yerda takrorlanmaydi — import qilinadi)
_SHADOW = {"CUSTOMER_PAYMENT": (CashMovementType.payin, "Qarz to'lovi · "),
           "SUPPLIER_PAYMENT": (CashMovementType.payout, "Ta'minotchi · ")}


def _u(x):
    if x is None or x == "":
        return None
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _ts(x):
    if x is None or x == "":
        return None
    return _aware(datetime.fromisoformat(x) if isinstance(x, str) else x)


# ═══ Operator TARIXIY mapping (oddiy --mapping'dan QAT'IY AJRALGAN) ══════════
def load_historical_map(src) -> dict:
    """Operator TARIXIY dalil faylini yuklaydi + QAT'IY validatsiya qiladi (§7).

    SHAKL (oddiy `--mapping`dan BUTUNLAY BOSHQA hujjat):
        {"kind": "HISTORICAL_TILL_EVIDENCE", "version": 1, "attested_by": "<kim>",
         "sources": {"<source_type>:<source_id>": "<till_id>"},
         "shifts":  {"<shift_id>": "<till_id>"}}

    Oddiy `--mapping` (current provisioning intent) berilsa `kind` mos kelmagani uchun BALAND OVOZDA
    rad etiladi. Vaqt-oynali ("branch + davr") attestatsiya ATAYLAB QO'LLANMAYDI — §3 ierarxiyasi
    faqat ANIQ source_id / shift_id ni tan oladi (kengroq oyna taxminga yaqinlashadi)."""
    if src is None:
        return {}
    # IDEMPOTENT: CLI faylni bir marta yuklaydi, keyin execute_backfill yana chaqiradi.
    if isinstance(src, dict) and src.get("kind") == _MAP_KIND and src.get("_normalized") is True:
        return src
    if isinstance(src, dict):
        raw = src
    elif isinstance(src, (str, bytes)) or hasattr(src, "__fspath__"):
        try:
            raw = json.loads(open(src, encoding="utf-8").read())
        except json.JSONDecodeError as e:
            raise ValueError(f"historical mapping JSON o'qib bo'lmadi: {e}") from e
    else:
        raise ValueError(
            f"historical mapping RAD ETILDI: yo'l yoki obyekt kutilgan, {type(src).__name__} keldi.")
    if not isinstance(raw, dict):
        raise ValueError("historical mapping RAD ETILDI: yuqori daraja JSON obyekt bo'lishi kerak.")
    if raw.get("kind") != _MAP_KIND:
        raise ValueError(
            f"historical mapping RAD ETILDI: kind={raw.get('kind')!r} != {_MAP_KIND!r}. "
            "Oddiy --mapping (current provisioning) fayli TARIXIY dalil sifatida ISHLATILMAYDI.")
    try:
        _ver = int(raw.get("version", 0))
    except (TypeError, ValueError):
        raise ValueError(f"historical mapping versiyasi noto'g'ri: {raw.get('version')!r}") from None
    if _ver != _MAP_VERSION:
        raise ValueError(f"historical mapping versiyasi qo'llab-quvvatlanmaydi: {raw.get('version')!r}")
    if not str(raw.get("attested_by") or "").strip():
        raise ValueError("historical mapping RAD ETILDI: `attested_by` SHART (kim tasdiqladi).")

    sources, shifts = {}, {}
    raw_src = raw.get("sources") or {}
    if not isinstance(raw_src, dict):
        raise ValueError("historical mapping: `sources` obyekt bo'lishi kerak "
                         "({\"<source_type>:<source_id>\": \"<till_id>\"}).")
    for k, v in raw_src.items():
        parts = str(k).split(":", 1)
        if len(parts) != 2 or not parts[0].strip():
            raise ValueError(f"historical mapping sources[{k!r}]: kalit '<source_type>:<source_id>' bo'lsin.")
        try:
            sid, tid = _u(parts[1]), _u(v)
        except (ValueError, AttributeError, TypeError) as ex:
            raise ValueError(f"historical mapping sources[{k!r}]: noto'g'ri UUID ({ex}).") from None
        if sid is None or tid is None:
            raise ValueError(f"historical mapping sources[{k!r}]: source_id va till_id SHART.")
        sources[(parts[0].strip(), str(sid))] = tid
    raw_sh = raw.get("shifts") or {}
    if not isinstance(raw_sh, dict):
        raise ValueError("historical mapping: `shifts` obyekt bo'lishi kerak "
                         "({\"<shift_id>\": \"<till_id>\"}).")
    for k, v in raw_sh.items():
        try:
            shid, tid = _u(k), _u(v)
        except (ValueError, AttributeError, TypeError) as ex:
            raise ValueError(f"historical mapping shifts[{k!r}]: noto'g'ri UUID ({ex}).") from None
        if shid is None or tid is None:
            raise ValueError(f"historical mapping shifts[{k!r}]: shift_id va till_id SHART.")
        shifts[str(shid)] = tid
    if not sources and not shifts:
        raise ValueError("historical mapping BO'SH: `sources` yoki `shifts` dan kamida bittasi SHART.")
    return {"kind": _MAP_KIND, "version": _MAP_VERSION, "_normalized": True,
            "attested_by": str(raw["attested_by"]).strip(), "attested_at": raw.get("attested_at"),
            "note": raw.get("note"), "sources": sources, "shifts": shifts}


def map_fingerprint(hist: dict | None) -> str:
    """Manifest hash'ga qo'shiladigan barqaror imzo — attestatsiya o'zgarsa hash ham o'zgaradi."""
    if not hist:
        return "none"
    src = sorted(f"{k[0]}:{k[1]}->{v}" for k, v in (hist.get("sources") or {}).items())
    sh = sorted(f"shift:{k}->{v}" for k, v in (hist.get("shifts") or {}).items())
    return f"{hist.get('attested_by')}|{'|'.join(src)}|{'|'.join(sh)}"


# ═══ TARIXIY TILL indeksi (STATUS bo'yicha FILTRLANMAYDI — ARCHIVED ham to'g'ri) ══
def build_index(db, company_id=None) -> dict:
    """Tarixiy resolution uchun TILL indeksi. MUHIM: `status` bo'yicha FILTRLAMAYDI — nafaqaga
    chiqqan (ARCHIVED) drawer eski qator uchun AYNAN to'g'ri javob. (Runtime readiness ALOHIDA
    ACTIVE-only ko'rinishni ishlatadi.)"""
    # by_id ATAYLAB TENANT BO'YICHA KESILMAYDI: aks holda boshqa tenant'ning till_id'si "topilmadi"
    # bo'lib REVIEW'ga tushardi va resolve_account'dagi CROSS-TENANT **BLOCK** guard'i HECH QACHON
    # ishlamasdi (buzilgan ma'lumot jimgina kechiktirilgan bo'lib ko'rinardi). Jadval kichik.
    # §4: terminal->TILL indeksi ATAYLAB QURILMAYDI — u mutable joriy assotsiatsiya, tarixiy dalil emas.
    by_id = {str(a.id): a for a in db.query(CashAccount).filter(CashAccount.type == "TILL").all()}
    return {"by_id": by_id}


def _acc(index, till_id, tenant=None):
    """till_id -> CashAccount (tenant bo'yicha FILTRLAMAYDI!).

    DIQQAT: bu yerda tenant bo'yicha jimgina None qaytarish XATO bo'lardi — cross-tenant dalil
    REVIEW'ga aylanib, chaqiruvchidagi BLOCK guard'iga YETIB BORMASDI. Cross-tenant ishora buzilgan
    ma'lumot/mapping belgisi -> u BALAND OVOZDA BLOCK bo'lishi kerak (resolve_account guard'i)."""
    return index["by_id"].get(str(till_id))


# ═══ Dalil qidiruvi ══════════════════════════════════════════════════════════
def _source_employee(db, leg):
    """Manba qatorining employee_id'si (soya moslikni NOYOB qilish uchun) — leg'da bo'lmasa DB'dan."""
    from app.models.customers import CustomerPayment
    from app.models.purchasing import SupplierPayment
    model = {"CUSTOMER_PAYMENT": CustomerPayment, "SUPPLIER_PAYMENT": SupplierPayment}.get(
        leg.get("source_type"))
    if model is None:
        return None
    row = db.get(model, _u(leg["source_id"]))
    return getattr(row, "employee_id", None) if row is not None else None


def _shadow_shift(db, leg):
    """Zamondosh SOYA CashMovement -> uning Shift'i (NOYOB moslik SHART). Soya tranzaksiya
    PAYTIDA yozilgan -> haqiqiy tarixiy dalil (bugungi holat emas)."""
    st = leg.get("source_type")
    if st not in _SHADOW:
        return None
    mtype, prefix = _SHADOW[st]
    emp = leg.get("employee_id") or _source_employee(db, leg)
    if emp is None:
        return None                       # employee'siz moslik NOYOB emas -> dalil emas
    # §HIST-REVIEW (CRITICAL tuzatish): faqat (tenant+tur+prefiks+summa+xodim) MOSLIGI YETARLI EMAS —
    # u BOSHQA to'lovning soyasiga (masalan keyinroq, boshqa filialda, provisioning'dan KEYIN qilingan)
    # tushib, uning BUGUNGI till_id'sini eski qatorga "dalil" sifatida biriktirardi. Bu aynan biz
    # yo'q qilayotgan retroaktiv taxminning qayta ochilishi edi. Endi soya AYNI SHU manba qatoriniki
    # bo'lishi SHART:
    #   * VAQT: soya manba bilan BIR TRANZAKSIYADA, BIR XIL `now` bilan yoziladi
    #     (customers.py: CustomerPayment(created_at=now) + CashMovement(created_at=now);
    #      purchases.py ayni naqsh) -> created_at AYNAN teng bo'lishi kerak.
    #   * FILIAL: leg filiali ma'lum bo'lsa, soya smenasi O'SHA filialda bo'lishi kerak.
    occ = _ts(leg.get("device_occurred_at"))
    if occ is None:
        return None                       # vaqt dalili yo'q -> identity isbotlanmaydi
    from decimal import Decimal
    q = (db.query(Shift).join(CashMovement, CashMovement.shift_id == Shift.id)
         .join(Branch, Branch.id == Shift.branch_id)
         .filter(Branch.company_id == _u(leg["tenant_id"]),
                 CashMovement.type == mtype, CashMovement.client_uuid.is_(None),
                 CashMovement.reason.like(prefix + "%"),
                 CashMovement.amount == Decimal(str(leg.get("amount") or 0)),
                 CashMovement.employee_id == _u(emp),
                 CashMovement.created_at == occ))
    if leg.get("branch_id"):
        q = q.filter(Shift.branch_id == _u(leg["branch_id"]))
    rows = q.distinct().all()
    return rows[0] if len(rows) == 1 else None


def _candidate(index, till_id, leg, rule, detail):
    """Nomzod TILL'ni VALIDATSIYA qiladi: mavjud + type=TILL + (tenant) + FILIAL mosligi.

    Tenant mos kelmasa nomzod ATAYLAB QAYTARILADI — chaqiruvchi (resolve_account) uni BALAND OVOZDA
    BLOCK qiladi; bu yerda jimgina None qaytarish cross-tenant buzilishni REVIEW'ga aylantirib
    yashirardi. Filial mosligi: leg filiali ma'lum bo'lsa, drawer AYNAN o'sha filialniki bo'lishi SHART."""
    a = _acc(index, till_id)
    if a is None:
        return None, None, f"{rule}: till_id={till_id} cash_accounts'da TOPILMADI — identity tasdiqlanmadi"
    if str(getattr(a, "type", "")) != "TILL":
        return None, None, f"{rule}: hisob turi TILL EMAS ({a.type}) — yaroqsiz"
    if str(a.tenant_id) != str(leg["tenant_id"]):
        return a, rule, detail            # cross-tenant -> chaqiruvchi BLOCK qiladi
    if leg.get("branch_id") and str(a.branch_id) != str(leg["branch_id"]):
        return None, None, (f"{rule}: till {till_id} branch={a.branch_id} != leg branch "
                            f"{leg['branch_id']} — YAROQSIZ (noto'g'ri filial)")
    return a, rule, detail


def resolve(db, leg: dict, index: dict, *, historical_map: dict | None = None):
    """(CashAccount|None, rule|None, reason) — TARIXIY fizik drawer FAQAT dalil bilan aniqlanadi (§3).

    Ierarxiya (birinchi mos kelgani g'olib):
      1. SOURCE_TILL         — manba qatorida saqlangan till_id
      2. SHIFT_TILL          — manba.shift_id -> Shift.till_id
      (3. terminal — §4 bo'yicha TAQIQLANGAN: binding mutable/versiyalanmagan, dalil emas)
      4. SHADOW_SHIFT_TILL   — zamondosh soya -> Shift.till_id (identity: ayni vaqt + filial)
      5. OPERATOR_SOURCE_MAP -> OPERATOR_SHIFT_MAP — explicit operator attestatsiyasi

    Dalil yo'q -> (None, None, sabab); chaqiruvchi HISTORICAL_TILL_UNKNOWN sifatida SKIP+REVIEW qiladi.
    BUGUNGI provisioning'dan (bitta ACTIVE TILL, branch default, kassir, terminal) HECH QACHON taxmin
    QILINMAYDI."""
    tried = []

    # 1) manba qatorida SAQLANGAN till_id (tranzaksiya PAYTIDA yozilgan — eng kuchli intrinsic dalil)
    if leg.get("till_id"):
        return _candidate(index, leg["till_id"], leg, RULE_SOURCE_TILL,
                          f"manba qatorida saqlangan till_id={leg['till_id']}")
    tried.append("source.till_id yo'q")

    # 2) manba smenasi -> Shift.till_id
    if leg.get("shift_id"):
        sh = db.get(Shift, _u(leg["shift_id"]))
        if sh is not None and sh.till_id:
            return _candidate(index, sh.till_id, leg, RULE_SHIFT_TILL,
                              f"smena {sh.id} till_id={sh.till_id}")
        tried.append("shift.till_id yo'q")
    else:
        tried.append("shift yo'q")

    # 3) TERMINAL — §4: ATAYLAB ISHLATILMAYDI (mutable joriy binding, tarixiy dalil emas)
    if leg.get("terminal_id"):
        tried.append(f"terminal {leg['terminal_id']} bor, LEKIN terminal->TILL bog'lanishi mutable/"
                     "versiyalanmagan (cash_accounts.label) -> tarixiy dalil sifatida QABUL QILINMAYDI")

    # 4) zamondosh soya -> smena -> till_id
    sh = _shadow_shift(db, leg)
    if sh is not None and sh.till_id:
        return _candidate(index, sh.till_id, leg, RULE_SHADOW_SHIFT,
                          f"soya -> smena {sh.id} till_id={sh.till_id}")
    tried.append("soya->smena till_id yo'q")

    # 5) explicit operator attestatsiyasi — avval ANIQ source, keyin ANIQ shift
    if historical_map:
        hit = (historical_map.get("sources") or {}).get(
            (str(leg.get("source_type")), str(leg.get("source_id"))))
        if hit is not None:
            return _candidate(index, hit, leg, RULE_OP_SOURCE_MAP,
                              f"operator source-map attestatsiyasi (attested_by="
                              f"{historical_map.get('attested_by')})")
        if leg.get("shift_id"):
            hit = (historical_map.get("shifts") or {}).get(str(_u(leg["shift_id"])))
            if hit is not None:
                return _candidate(index, hit, leg, RULE_OP_SHIFT_MAP,
                                  f"operator shift-map attestatsiyasi (attested_by="
                                  f"{historical_map.get('attested_by')})")
        tried.append("operator attestatsiyasida bu qator yo'q")

    return None, None, ("deterministic historical TILL evidence absent; current TILL provisioning is not "
                        "historical evidence (" + "; ".join(tried) + "). Hal qilish: manba/smena till_id "
                        "dalili yoki explicit historical mapping (sources/shifts).")
