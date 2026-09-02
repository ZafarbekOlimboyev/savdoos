"""Egа uchun kassa kirim/chiqim (mobil) + filiallararo transfer.

Kassa operatsiyasi do'kondagi OCHIQ smenaga yoziladi (pul kassada turadi) —
ochiq smena bo'lmasa 400. Transfer: ombordan omborga, ledger transfer_out/in bilan.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import CashMovementType, MovementType, ShiftStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.shifts import CashMovement, Shift

router = APIRouter(tags=["cashops"])


class CashOpIn(BaseModel):
    type: Literal["payin", "expense", "collection"] = "expense"
    amount: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)
    client_uuid: uuid.UUID | None = None   # offline idempotentlik (retry'да ikki marta emas)


@router.post("/cash/ops")
def cash_op(data: CashOpIn, emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Kassa kirim (payin) / xarajat (expense) / inkassatsiya (collection) — o'z filiali ochiq smenaga."""
    from app.core.deps import actor_branch
    _ab = actor_branch(emp, db)
    # Xodим FILIALIdagi ochiq smenaга yoziladi (ilgari kompaniyaning global oxirgi ochiq smenasига
    # tushardi — ko'p-filialда pul boshqa filial kassasига kirib ketardi).
    q = (db.query(Shift)
         .join(Branch, Branch.id == Shift.branch_id)
         .filter(Branch.company_id == emp.company_id, Shift.status == ShiftStatus.open))
    if _ab:
        q = q.filter(Shift.branch_id == _ab.id)
    shift = q.order_by(Shift.opened_at.desc()).first()
    if not shift:
        raise HTTPException(400, "Ochiq smena yo'q — avval kassada smena oching")
    # DEDUP: shu client_uuid bilan harakat allaqачон bo'lsa — qayta yozмаймиз (offline retry).
    if data.client_uuid:
        dup = db.query(CashMovement).filter(
            CashMovement.shift_id == shift.id, CashMovement.client_uuid == data.client_uuid).first()
        if dup:
            return {"ok": True, "shift_id": str(shift.id), "duplicate": True}
    db.add(CashMovement(
        shift_id=shift.id, type=CashMovementType(data.type), amount=Decimal(str(data.amount)),
        reason=data.reason, employee_id=emp.id, created_at=datetime.now(timezone.utc),
        client_uuid=data.client_uuid,
    ))
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:  # bir vaqtдаги dublikat — DB unique indeksi (ux_cashmov_client_uuid) ushlади
        db.rollback()
        return {"ok": True, "shift_id": str(shift.id), "duplicate": True}
    return {"ok": True, "shift_id": str(shift.id)}


@router.get("/cash/ops")
def cash_ops_today(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    """Bugungi kassa harakatlari (kompaniya bo'yicha, oxirgi 50). "Bugun" — do'kon MAHALLIY kuni."""
    from app.api.v1.reports import _store_tz
    from app.core.deps import visible_branches
    LOCAL = _store_tz(db, emp.company_id)
    day0 = (datetime.now(timezone.utc).astimezone(LOCAL)
            .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим — faqat o'z filiali harakatlari
    q = (
        db.query(CashMovement, Employee.full_name)
        .join(Shift, Shift.id == CashMovement.shift_id)
        .join(Branch, Branch.id == Shift.branch_id)
        .outerjoin(Employee, Employee.id == CashMovement.employee_id)
        .filter(Branch.company_id == emp.company_id, CashMovement.created_at >= day0)
    )
    if _vb is not None:
        q = q.filter(Shift.branch_id.in_(_vb))
    rows = q.order_by(CashMovement.created_at.desc()).limit(50).all()
    return [{"type": m.type.value, "amount": float(m.amount), "reason": m.reason,
             "employee": who or "—", "at": m.created_at} for m, who in rows]


class TransferItem(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)


class TransferIn(BaseModel):
    from_branch_id: uuid.UUID
    to_branch_id: uuid.UUID
    items: list[TransferItem] = Field(max_length=1000)  # massiv-DoS oldini olish
    client_uuid: uuid.UUID | None = None


@router.post("/inventory/transfer")
def transfer(data: TransferIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    # Retry o'rami IKKI konkurrentlik race'ini yopadi: (1) bir xil client_uuid'li takror push
    # transfer_out unique indeksini (ux_stockmov_client_prod_type) buzsa -> keyingi urinishda
    # dedup SELECT committed yozuvni topib "duplicate" qaytaradi; (2) maqsad filialida (product_id,
    # branch_id) inventory qatori hali yo'q bo'lsa, ikki konkurrent INSERT UniqueConstraint'ni buzadi
    # -> keyingi urinishda qator mavjud, collision yo'q (create_sale'dagi kabi).
    from sqlalchemy.exc import IntegrityError as _IE
    _last: Exception | None = None
    for _try in range(3):
        try:
            return _transfer_once(data, emp, db)
        except _IE as e:
            db.rollback()
            _last = e
    raise HTTPException(409, "Ko'chirish band — qayta urinib ko'ring") from _last


def _transfer_once(data: TransferIn, emp: Employee, db: Session):
    """Filiallararo ko'chirish: from'dan kamayadi (transfer_out), to'ga qo'shiladi (transfer_in)."""
    if data.from_branch_id == data.to_branch_id:
        raise HTTPException(400, "Bir xil filial tanlandi")
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    if data.client_uuid:
        ex = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.type == MovementType.transfer_out).first()
        if ex:
            return {"ok": True, "duplicate": True}
    # QA WH-003 (TOCTOU): filial qatorlari FOR UPDATE — parallel delete_branch bilan serializatsiya
    # (o'chirilayotgan filialga commit'dan keyin stok tushib qamalib qolmasin).
    _bids = sorted({data.from_branch_id, data.to_branch_id}, key=str)
    _rows = {b.id: b for b in db.query(Branch).filter(Branch.id.in_(_bids)).with_for_update().all()}
    src = _rows.get(data.from_branch_id)
    dst = _rows.get(data.to_branch_id)
    for b, nm in ((src, "from"), (dst, "to")):
        if not b or b.company_id != emp.company_id or b.deleted_at is not None:
            raise HTTPException(404, f"Filial topilmadi ({nm})")
        # QA WH-006: NOFAOL filial bilan transfer yo'q (Modul-2 invarianti: nofaol filialga yangi yozuv 400)
        if not b.is_active:
            raise HTTPException(400, f"Filial nofaol — transfer qilib bo'lmaydi ({b.name})")
    # QA WH-005: manba filial xodimning ko'rish doirasida bo'lishi SHART (filialga bog'langan
    # xodim boshqa filial omborini bo'shata olmasin). Maqsad — istalgan faol filial (yuborish OK).
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)
    if _vb is not None and src.id not in _vb:
        raise HTTPException(403, "Ruxsat yo'q: manba filial sizga biriktirilmagan")
    # QA WH-004: bir mahsulot bir necha qatorda kelsa BIRLASHTIRAMIZ (qty yig'indisi) — ilgari
    # transfer_out'lar bir xil (client_uuid, product, type) kalit bilan o'z-o'zi bilan to'qnashib
    # DOIMIY 409 berardi (mobil ro'yxatga bir mahsulotni ikki marta qo'shish oddiy holat).
    _agg: dict = {}
    for i in data.items:
        _agg[i.product_id] = _agg.get(i.product_id, Decimal("0")) + Decimal(str(i.qty))
    now = datetime.now(timezone.utc)
    moved = []
    # DEADLOCK oldini olish: BARCHA tegiladigan (product_id, branch_id) qatorlarини DASTAVVAL bir
    # xil GLOBAL tartибда qulflaymiz (manba VA maqsad). QA WH-017: qator YO'Q bo'lsa shu yerda
    # 0-qoldiq bilan YARATIB qulflaymiz — keyingi INSERT poygalari sinfi butunlay yo'qoladi.
    _pairs = sorted({(p, src.id) for p in _agg} | {(p, dst.id) for p in _agg},
                    key=lambda t: (str(t[0]), str(t[1])))
    for _pid, _bid in _pairs:
        _r = db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == _bid).with_for_update().first()
        if _r is None:
            db.add(Inventory(product_id=_pid, branch_id=_bid, qty=Decimal("0"), updated_at=now))
            db.flush()   # to'qnashuv -> IntegrityError -> tashqi retry (keyingi urinishda mavjud)
            db.query(Inventory).filter(
                Inventory.product_id == _pid, Inventory.branch_id == _bid).with_for_update().first()
    _crossed: list = []
    for pid, qty in _agg.items():
        prod = db.get(Product, pid)
        if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
            raise HTTPException(400, f"Mahsulot topilmadi: {pid}")
        # Qatorlar yuqorида qulflangan (with_for_update) — quyидаги o'qishлар izchil.
        inv_from = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == src.id).with_for_update().first()
        avail = Decimal(str(inv_from.qty)) if inv_from else Decimal("0")
        if qty > avail:
            raise HTTPException(400, f"Yetarli qoldiq yo'q: {prod.name} (qoldiq: {avail})")
        inv_from.qty = avail - qty
        inv_from.updated_at = now
        from app.api.v1.inventory import _low_cross_check
        _low_cross_check(inv_from, prod.name, _crossed)   # QA WH-009: manba min ostiga tushsa ogohlantir
        inv_to = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == dst.id).with_for_update().first()
        inv_to.qty = Decimal(str(inv_to.qty)) + qty
        # QA WH-021: maqsad qoldig'i Numeric(14,3) sig'imidan oshsa xom DataError 500 emas — 400.
        if inv_to.qty > Decimal("99999999999"):
            raise HTTPException(400, f"'{prod.name}' maqsad filial qoldig'i juda katta — miqdorni tekshiring")
        inv_to.updated_at = now
        if inv_to.qty > Decimal(str(inv_to.min_qty or 0)):
            inv_to.low_alerted = False  # restok — kam-qoldiq ogohlantirishi qayta tiklanadi
        db.add(StockMovement(product_id=prod.id, branch_id=src.id, type=MovementType.transfer_out,
                             qty=-qty, balance_after=inv_from.qty, ref_type="transfer",
                             employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
        db.add(StockMovement(product_id=prod.id, branch_id=dst.id, type=MovementType.transfer_in,
                             qty=qty, balance_after=inv_to.qty, ref_type="transfer",
                             employee_id=emp.id, created_at=now))
        moved.append({"product": prod.name, "qty": float(qty),
                      "from_left": float(inv_from.qty), "to_now": float(inv_to.qty)})
    db.commit()
    from app.api.v1.inventory import _push_low
    _push_low(db, emp.company_id, _crossed, src.name)
    return {"ok": True, "from": src.name, "to": dst.name, "moved": moved}
