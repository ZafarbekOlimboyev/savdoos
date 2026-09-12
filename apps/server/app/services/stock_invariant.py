"""MIQDOR INVARIANTI — partiyalar yig'indisi qoldiqqa TENG bo'lishi shart.

Kuzatuvli (`products.track_lots`) mahsulot uchun:

    Inventory.qty == SUM(remaining_qty)  [status != 'void']
                     ayni (company, branch, product) uchun

⚠️  MUDDAT MIQDORNI OLIB TASHLAMAYDI. Muddati o'tgan partiya JISMONAN javonda
    turibdi: 10 dona muddati kecha tugagan sut hamon 10 dona. U faqat ANIQ amal
    (hisobdan chiqarish / sotuv / tuzatish) bilan ketadi. Shu bois «muddati
    o'tgan» HOLAT EMAS — u `expiry_date < business_date` dan KELIB CHIQADI va
    yig'indiga ta'sir qilmaydi. Muddati o'tgan partiya hisobotда va hisobdan
    chiqarish oqimiда ko'rinadi, FEFO nomzodlaridan esa SIYOSAT bilan chiqariladi.

Ikkalasi DOIM ayni tranzaksiyada o'zgaradi — alohida yo'l YO'Q.

⚠️  BUZILGANDA NIMA BO'LADI. Jimgina tuzatilmaydi va taxmin qilinmaydi. Partiyaga
    oid amal (sotuv / qabul / hisobdan chiqarish) FAIL-CLOSED to'xtaydi va
    operator aniq xabar oladi. Avtomatik "moslashtirish" eng xavfli yo'l bo'lardi:
    u farqni yashiradi va uning SABABINI yo'qotadi. Auditlangan tiklash oqimi
    keyingi bosqichda qo'shiladi.

⚠️  KUZATUVSIZ mahsulot bu tekshiruvdan BUTUNLAY chetda: uning partiyasi yo'q va
    bo'lishi ham shart emas. Bugungi 7137 demo mahsulot aynan shunday.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.inventory import Inventory, StockBatch

# ── PARTIYA HAYOT SIKLI ──────────────────────────────────────────────────────
# OPEN     — miqdor tashiydi, yig'indiga KIRADI
# DEPLETED — remaining_qty = 0 (tugagan). Yig'indiga KIRADI, lekin 0 qo'shadi:
#            uni chiqarib tashlash shart emas va xavfli ham — `remaining_qty`
#            noldan farq qilib qolsa u JIMGINA yo'qolardi.
# VOID     — qabul BEKOR qilingan/xato kiritilgan. Miqdor tashimaydi
#            (`remaining_qty` 0 bo'lishi SHART) va yig'indiga KIRMAYDI.
#
# ⚠️  «EXPIRED» BU YERDA YO'Q va bo'lmasligi ham kerak — u hosila holat.
OPEN = "open"
DEPLETED = "depleted"
VOID = "void"
QUANTITY_BEARING = frozenset({OPEN, DEPLETED})
# Yig'indidan ATAYLAB chiqariladigan holatlar. Ro'yxatda yo'q holat —
# NOMA'LUM va FAIL-CLOSED (pastga qarang).
EXCLUDED = frozenset({VOID})
KNOWN_STATUSES = QUANTITY_BEARING | EXCLUDED


class UnknownLotStatus(RuntimeError):
    """Tasniflanmagan partiya holati — invariant hisoblanmaydi.

    ⚠️  FAIL-CLOSED. Yangi holat qo'shilib, uni bu yerda tasniflash unutilsa,
        generik `status != 'void'` qoidasi uni JIMGINA miqdor tashiydigan deb
        hisoblardi — ya'ni yangi holat invariantni bildirmasdan o'zgartirardi.
        Endi noma'lum holat hisobni TO'XTATADI.
    """


class InvariantBroken(RuntimeError):
    """Partiyalar yig'indisi qoldiqqa mos kelmadi — amal BAJARILMAYDI."""


@dataclass
class Mismatch:
    product_id: str
    branch_id: str
    inventory_qty: Decimal
    lot_sum: Decimal

    @property
    def delta(self) -> Decimal:
        return Decimal(str(self.inventory_qty)) - Decimal(str(self.lot_sum))

    def __str__(self) -> str:
        return (f"mahsulot {self.product_id} filial {self.branch_id}: "
                f"qoldiq {self.inventory_qty} ≠ partiyalar {self.lot_sum} "
                f"(farq {self.delta:+})")


@dataclass
class Report:
    checked: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _lot_sums(db: Session, company_id, product_ids=None) -> dict[tuple, Decimal]:
    q = (select(StockBatch.product_id, StockBatch.branch_id,
                func.coalesce(func.sum(StockBatch.remaining_qty), 0))
         # ANIQ RO'YXAT — generik "void'dan boshqa hammasi" EMAS.
         .where(StockBatch.status.in_(sorted(QUANTITY_BEARING))))
    if company_id is not None:
        q = q.where(StockBatch.company_id == company_id)
    if product_ids is not None:
        q = q.where(StockBatch.product_id.in_(list(product_ids)))
    q = q.group_by(StockBatch.product_id, StockBatch.branch_id)
    return {(str(p), str(b)): Decimal(str(t or 0)) for p, b, t in db.execute(q).all()}


def _assert_known_statuses(db: Session, company_id, product_ids) -> None:
    """Tasniflanmagan holat bo'lsa — hisob TO'XTAYDI (fail-closed)."""
    q = select(StockBatch.status).where(
        StockBatch.status.notin_(sorted(KNOWN_STATUSES))).distinct()
    if company_id is not None:
        q = q.where(StockBatch.company_id == company_id)
    if product_ids is not None:
        q = q.where(StockBatch.product_id.in_(list(product_ids)))
    bad = [r[0] for r in db.execute(q).all()]
    if bad:
        raise UnknownLotStatus(
            f"partiya holati TASNIFLANMAGAN: {sorted(bad)}. Miqdor tashiydimi yoki "
            f"yo'qmi — noma'lum, shu bois invariant hisoblanmaydi. Holatni "
            f"`stock_invariant.QUANTITY_BEARING` yoki `EXCLUDED` ga kiriting.")


def check(db: Session, company_id, product_ids=None) -> Report:
    """Invariantni TEKSHIRADI. Hech narsa o'zgartirmaydi.

    `product_ids` berilsa faqat o'shalar — sotuv yo'lida butun katalogni
    tekshirish qimmat bo'lardi, tegilayotgan qatorlar esa arzon.
    """
    rep = Report()
    pq = select(Product.id).where(Product.track_lots.is_(True))
    if company_id is not None:
        pq = pq.where(Product.company_id == company_id)
    if product_ids is not None:
        pq = pq.where(Product.id.in_(list(product_ids)))
    tracked = [r[0] for r in db.execute(pq).all()]
    if not tracked:
        return rep

    _assert_known_statuses(db, company_id, tracked)
    sums = _lot_sums(db, company_id, tracked)
    iq = (select(Inventory.product_id, Inventory.branch_id, Inventory.qty)
          .where(Inventory.product_id.in_(tracked)))
    for pid, bid, qty in db.execute(iq).all():
        rep.checked += 1
        inv_q = Decimal(str(qty or 0))
        lot_q = sums.get((str(pid), str(bid)), Decimal("0"))
        if inv_q != lot_q:
            rep.mismatches.append(Mismatch(str(pid), str(bid), inv_q, lot_q))

    # Qoldiq qatori UMUMAN yo'q, lekin ochiq partiya bor — bu ham nomuvofiqlik.
    seen = {(str(p), str(b)) for p, b, _ in db.execute(iq).all()}
    for key, lot_q in sums.items():
        if key not in seen and lot_q != 0:
            rep.checked += 1
            rep.mismatches.append(Mismatch(key[0], key[1], Decimal("0"), lot_q))
    return rep


def assert_ok(db: Session, company_id, product_ids=None) -> None:
    """Buzilgan bo'lsa `InvariantBroken` — chaqiruvchi tranzaksiyani QAYTARADI."""
    rep = check(db, company_id, product_ids)
    if not rep.ok:
        raise InvariantBroken(
            "Partiya miqdor invarianti BUZILGAN — amal bajarilmadi. "
            + "; ".join(str(m) for m in rep.mismatches[:5])
            + (f" (+{len(rep.mismatches) - 5} ta yana)" if len(rep.mismatches) > 5 else ""))
