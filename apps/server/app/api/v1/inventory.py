import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.core.deps import get_current_employee, require
from app.db.session import get_db
from app.models.auth import Employee
from app.models.catalog import Product
from app.models.enums import MovementType
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.services.audit import log as _audit_log

log = logging.getLogger(__name__)

router = APIRouter(tags=["inventory"])


def _first_branch(db: Session, company_id):
    b = db.query(Branch).filter(Branch.company_id == company_id, Branch.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(400, "Filial topilmadi")
    return b


def _get_product(db: Session, product_id, company_id):
    p = db.get(Product, product_id)
    if not p or p.company_id != company_id or p.deleted_at is not None:
        raise HTTPException(400, f"Mahsulot topilmadi: {product_id}")
    return p

MOVE_LABEL = {
    "purchase_in": ("Kirim", "in"),
    "return_in": ("Qaytdi", "in"),
    "sale_out": ("Sotildi", "out"),
    "writeoff": ("Hisobdan", "out"),
    "adjustment": ("Tuzatish", "in"),
    "transfer_in": ("Transfer keldi", "in"),
    "transfer_out": ("Transfer ketdi", "out"),
    "count_adjust": ("Inventarizatsiya", "in"),
}


@router.get("/inventory/overview")
def overview(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)  # filialга bog'langan xodim — faqat o'z filiali qoldig'i
    total = db.query(Product).filter(
        Product.company_id == emp.company_id, Product.deleted_at.is_(None)
    ).count()
    low = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    out = (
        db.query(Inventory)
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True), Inventory.qty <= 0)
    )
    # "Bugun" — do'kon MAHALLIY kuni (hisobotlar bilan izchil); UTC sana ofset tufayli noto'g'ri edi.
    from app.api.v1.reports import _store_tz
    LOCAL = _store_tz(db, emp.company_id)
    day0 = (datetime.now(timezone.utc).astimezone(LOCAL)
            .replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc))
    moves_today = (
        db.query(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .filter(Product.company_id == emp.company_id,  # tenant izolyatsiyasi
                StockMovement.created_at >= day0)
    )
    if bset is not None:
        low = low.filter(Inventory.branch_id.in_(bset))
        out = out.filter(Inventory.branch_id.in_(bset))
        moves_today = moves_today.filter(StockMovement.branch_id.in_(bset))
    return {"total_products": total, "low_count": low.count(), "out_count": out.count(), "moves_today": moves_today.count()}


@router.get("/inventory/movements")
def movements(limit: int = 20, offset: int = 0, product_id: uuid.UUID | None = None,
              emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    # QA WH-020: endi hisobot.view talab qilinadi (kassir ombor ledgerini ko'rmasin).
    from app.models.auth import Employee as Emp

    from app.core.deps import visible_branches
    bset = visible_branches(emp, db)
    query = (
        db.query(StockMovement, Product.name, Emp.full_name, Branch.name)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(Emp, Emp.id == StockMovement.employee_id)
        .outerjoin(Branch, Branch.id == StockMovement.branch_id)
        .filter(Product.company_id == emp.company_id)
    )
    if bset is not None:
        query = query.filter(StockMovement.branch_id.in_(bset))
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    # QA WH-013: manfiy limit Postgres'da 500 berardi (LIMIT -1) — endi 1..100 ga qisiladi.
    _lim = max(1, min(limit, 100))
    _off = max(0, min(offset, 100000))
    rows = query.order_by(StockMovement.created_at.desc()).offset(_off).limit(_lim).all()
    out = []
    for m, name, who, brname in rows:
        label, direction = MOVE_LABEL.get(m.type.value, (m.type.value, "in"))
        # Tuzatish/inventarizatsiya IKKI tomonlama — yo'nalish qty ishorasidan
        if m.type.value in ("adjustment", "count_adjust"):
            direction = "out" if float(m.qty) < 0 else "in"
        # QA WH-015: inventarizatsiya generik 'Tuzatish' emas — ref_type'dan aniqlanadi
        if m.type.value == "adjustment" and (m.ref_type or "") == "count":
            label = MOVE_LABEL["count_adjust"][0]
        out.append({
            "type": label,
            "direction": direction,
            "name": name,
            "qty": float(m.qty),
            "employee": who or "—",
            "branch": brname or "—",     # QA WH-014: ko'p-filial admin qaysi filialdaligini ko'rsin
            "reason": m.reason,
            "at": m.created_at,
        })
    return out


def _low_cross_check(inv, prod_name: str, crossed: list) -> None:
    """QA WH-009: min-chegara kesib o'tilishini HAR kamaytiruvchi amal belgilaydi (ilgari faqat
    sotuv). low_alerted dedup — bir kesishda bitta push."""
    if inv is not None and Decimal(str(inv.qty)) <= Decimal(str(inv.min_qty or 0)) and not bool(inv.low_alerted):
        inv.low_alerted = True
        crossed.append((prod_name, float(inv.qty)))


def _push_low(db, company_id, crossed: list, branch_name: str | None = None) -> None:
    if crossed:
        try:
            from app.services import push
            push.notify_low_stock(db, company_id, crossed, branch_name=branch_name)
        except Exception:  # noqa: BLE001
            pass


def _resolve_write_branch(db: Session, emp: Employee, branch_id: uuid.UUID | None):
    """QA WH-002: mobil endi filialni ANIQ tanlab yuboradi (ega/ko'p-filial). Berilmasa —
    eski xulq (actor_branch). Berilsa: o'z kompaniyasi + faol + ko'rish doirasida bo'lishi shart."""
    from app.core.deps import actor_branch, visible_branches
    if branch_id is None:
        return actor_branch(emp, db) or _first_branch(db, emp.company_id)
    b = db.get(Branch, branch_id)
    if not b or b.company_id != emp.company_id or b.deleted_at is not None:
        raise HTTPException(400, "Filial topilmadi")
    if not b.is_active:
        raise HTTPException(400, "Filial nofaol — amal bajarib bo'lmaydi")
    _vb = visible_branches(emp, db)
    if _vb is not None and b.id not in _vb:
        raise HTTPException(403, "Ruxsat yo'q: bu filial sizga biriktirilmagan")
    return b


class WriteoffLot(BaseModel):
    """Hisobdan chiqariladigan ANIQ partiya."""
    stock_batch_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)


class WriteoffIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)  # brak | expired | inventory | ...
    client_uuid: uuid.UUID | None = None  # idempotentlik — timeout'да qayta yuborishда ikki marta kamaymasin
    branch_id: uuid.UUID | None = None    # QA WH-002: qaysi filialdan chiqarish (berilmasa actor)
    # ⚠️  KUZATUVLI mahsulotda MAJBURIY. Tizim qaysi jismoniy partiya
    #     tashlanayotganini TAXMIN QILMAYDI — batafsil: `services/lot_writeoff.py`.
    lots: list[WriteoffLot] | None = Field(default=None, max_length=200)


@router.post("/inventory/writeoff")
def writeoff(data: WriteoffIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Hisobdan chiqarish (brak/muddati o'tgan/inventar) — qoldiqni kamaytiradi + ledger.

    ⚠️  NAQD PULGA TEGMAYDI. Tashlangan tovar — zaxira yo'qotishi, kassa amali
        EMAS. CashLedger'ga leg yozish kassada bo'lmagan pul harakatini
        ko'rsatardi va smena yopilishini buzardi.
    """
    # DEDUP: shu client_uuid bilan writeoff allaqachon bo'lgan bo'lsa — qayta kamaytirmaymiz.
    # ⚠️  KALIT DB INDEKSI BILAN AYNAN BIR XIL: `ux_stockmov_client_prod_type`
    #     (client_uuid + product_id + type). `stock_movements` da `company_id`
    #     ustuni YO'Q, shu bois mahsulotsiz so'rov BUTUN jadvalni ko'rardi va
    #     BOSHQA do'konning ayni client_uuid'i bu amalni jimgina «dublikat»
    #     qilib yutib yuborardi — javob esa muvaffaqiyatdek ko'rinardi.
    if data.client_uuid:
        dup = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.product_id == data.product_id,
            StockMovement.type == MovementType.writeoff).first()
        if dup:
            return {"ok": True, "duplicate": True}
    from app.services import lot_writeoff as _LW
    from app.services import stock_gate as _SG
    from app.services import stock_invariant as _SI
    _tracked = bool(_SG.tracked_ids(db, [data.product_id]))
    _lots_in = [(l.stock_batch_id, l.qty) for l in (data.lots or [])]
    if not _tracked and _lots_in:
        raise HTTPException(400, "Bu mahsulotda partiya kuzatuvi yoqilmagan — "
                                 "partiya ko'rsatib bo'lmaydi")
    branch = _resolve_write_branch(db, emp, data.branch_id)
    prod = _get_product(db, data.product_id, emp.company_id)
    qty = Decimal(str(data.qty))
    # QATOR QULFI: sotuv (services/sales.py) qatorni with_for_update bilan qulflaydi;
    # writeoff qulflamasa Postgres'да bir vaqtдаги sotuv/writeoff STALE qoldiqni o'qib
    # tekshiruvдан o'tib qoldiqни yo'qotardi (lost update / oversell). Endi qulflanadi.
    #
    # ⚠️  QULF TARTIBI: Inventory -> tartiblangan partiyalar. Sotuv yo'li ham
    #     AYNAN shunday qiladi; teskari tartib AB/BA deadlock tug'dirardi.
    inv = (db.query(Inventory)
           .filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id)
           .with_for_update().first())
    # ⚠️  KUZATUV BAYROG'I QULFDAN KEYIN QAYTA O'QILADI (Phase 5B, W). Yuqoridagi
    #     `_tracked` qulfdan OLDIN o'qilgan: `/lots/enable` shu qatorni ushlab commit
    #     qilsa, chiqarish ESKI «kuzatuvsiz» qaror bilan partiyaga tegmay qoldiqni
    #     kamaytirardi. Endi yangi qiymat — partiyasiz so'rov 400 oladi.
    _tracked = str(prod.id) in _SG.refresh_tracking(db, [prod])
    # ⚠️  KUZATUVLI YO'LDA miqdor NUMERIC(14,3) ga keltiriladi — aks holda qoldiq,
    #     harakat qatori va partiya allokatsiyalari brauzer floatining TURLI
    #     yaxlitlanishini olardi. Kuzatuvsiz yo'l AVVALGIDEK qoladi.
    if _tracked:
        qty = _LW._d(qty)
    have = Decimal(str(inv.qty)) if inv else Decimal("0")
    if qty > have:
        raise HTTPException(400, f"Yetarli qoldiq yo'q: {prod.name} (qoldiq: {have:g})")
    now = datetime.now(timezone.utc)
    _plan = None
    if _tracked:
        _batches = _LW.lock_batches(db, [b for b, _ in _lots_in])
        try:
            _plan = _LW.validate(_batches, _lots_in, company_id=emp.company_id,
                                 product_id=prod.id, branch_id=branch.id, total_qty=qty)
        except _LW.LotSelectionError as e:
            raise HTTPException(400, str(e)) from e
    inv.qty = have - qty
    inv.updated_at = now
    _crossed: list = []
    _low_cross_check(inv, prod.name, _crossed)   # QA WH-009: writeoff kesishi ham push beradi
    _mv_id = uuid.uuid4()
    db.add(StockMovement(id=_mv_id, product_id=prod.id, branch_id=branch.id,
                         type=MovementType.writeoff,
                         qty=-qty, balance_after=inv.qty, ref_type="writeoff", reason=data.reason,
                         employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
    _cost = None
    if _plan is not None:
        # Harakat qatori allokatsiya FK'sidan OLDIN mavjud bo'lishi shart.
        db.flush()
        _cost = _LW.apply(db, _plan, movement_id=_mv_id, company_id=emp.company_id,
                          product_id=prod.id, now=now)
        db.flush()
        # ── YAKUNIY DARVOZA: qoldiq va partiyalar BARAVAR kamayganini isbotlaymiz ──
        try:
            _SI.assert_ok(db, emp.company_id, [prod.id])
        except Exception as e:      # noqa: BLE001
            db.rollback()
            # ⚠️  ISTISNO MATNI OPERATORGA BERILMAYDI. `InvariantBroken` ichida xom
            #     UUID'lar, `≠` belgisi va modul/konstanta nomlari bor — ular do'kon
            #     egasiga hech narsa aytmaydi, tarjima ham qilinmaydi va ichki
            #     tuzilmani ochadi. Tafsilot JURNALGA yoziladi.
            log.exception("writeoff invariant buzildi: product=%s branch=%s", prod.id, branch.id)
            raise HTTPException(409, "Hisobdan chiqarib bo'lmadi — partiya va qoldiq mos "
                                     "kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga "
                                     "murojaat qiling.",
                                headers=EC.headers(EC.LOT_INVARIANT_BROKEN)) from e
        _audit_log(db, emp.id, "delete", "stock_writeoff", _mv_id,
                   after={"product_id": str(prod.id), "branch_id": str(branch.id),
                          "qty": float(qty), "reason": data.reason,
                          "cost_total": float(_cost),
                          "lots": [{"stock_batch_id": str(b.id), "qty": float(q),
                                    "unit_cost": float(b.unit_cost or 0)}
                                   for b, q in _plan]})
    # SELECT-dedup (yuqorida) race'ga chidamli emas — ikki konkurrent takror qoldiqni 2x kamaytirardi.
    # DB unique indeksi (ux_stockmov_client_prod_type) ikkinchisini ushlaydi -> tranzaksiya bekor, dublikat javob.
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        db.rollback()
        if data.client_uuid:
            return {"ok": True, "duplicate": True}
        raise
    _push_low(db, emp.company_id, _crossed, branch.name)
    out = {"ok": True, "product": prod.name, "new_qty": float(inv.qty)}
    if _cost is not None:
        out["cost_total"] = float(_cost)
    return out


class CountLot(BaseModel):
    """SANALGAN partiya va undagi HAQIQIY miqdor."""
    stock_batch_id: uuid.UUID
    counted: float = Field(ge=0, le=1e9, allow_inf_nan=False)


class CountNewLot(BaseModel):
    """SANOQDA TOPILGAN, tizimda YO'Q partiya — operator uni ANIQ e'lon qiladi.

    ⚠️  NEGA ALOHIDA. Ortiqcha miqdorni mavjud partiyaga yozish narx va muddatni
        O'SHA partiyadan NUSXALAYDI. Javonda boshqa muddatli qadoq topilgan bo'lsa,
        bu muddat hisobotini YOLG'ON qilardi. Shu bois yangi partiya o'z muddati,
        o'z raqami va OPERATOR aytgan tannarx bilan tug'iladi (`adjustment`).
    """
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    batch_no: str | None = Field(default=None, max_length=64)
    expiry_date: date | None = None
    reason: str | None = Field(default=None, max_length=200)


class CountItem(BaseModel):
    product_id: uuid.UUID
    counted: float = Field(ge=0, le=1e9, allow_inf_nan=False)  # absurd katta sanoq qoldiqni buzmasin
    # ⚠️  KUZATUVLI mahsulotda MAJBURIY (LOT_LEVEL_COUNT). Umumiy farqni tizim
    #     partiyalarga TAQSIMLAMAYDI — batafsil: `services/lot_writeoff.py`.
    #     Sanalmagan partiya TEGILMAYDI, «nol» deb tushunilmaydi.
    lots: list[CountLot] | None = Field(default=None, max_length=200)
    #  Phase 4B: javondan topilgan, tizimda YO'Q partiyalar (ixtiyoriy).
    new_lots: list[CountNewLot] | None = Field(default=None, max_length=50)


# ⚠️  JAMI PARTIYA QATORLARI CHEGARASI. Alohida chegaralar KO'PAYTIRILADI:
#     20 000 mahsulot x (200 sanalgan + 50 yangi) partiya — bitta tranzaksiyada
#     yuz minglab qator, har yangi partiya o'z `flush()` i bilan, hammasi ombor
#     qulflari ostida (do'kon sotuvi shuncha kutadi). Manager sanoqni
#     mahsulot-ba-mahsulot yuboradi, mobil ilova partiya yubormaydi — chegara
#     faqat g'ayritabiiy so'rovni to'xtatadi.
MAX_COUNT_LOT_LINES = 2000


class CountIn(BaseModel):
    items: list[CountItem] = Field(max_length=20000)  # massiv-DoS oldini olish
    client_uuid: uuid.UUID | None = None  # QA WH-023: offline retry idempotentligi (writeoff bilan izchil)
    branch_id: uuid.UUID | None = None    # QA WH-002: qaysi filial sanalmoqda (berilmasa actor)


@router.post("/inventory/count")
def stock_count(data: CountIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Inventarizatsiya — sanoq bilan tizim qoldig'ini solishtiradi; farqqa tuzatish yozadi.
    QA WH-001: yangi (qator yo'q) mahsulotga parallel yozuvchi bilan INSERT poygasi xom 500
    berardi (real-Postgres isbot) — endi boshqa ombor-yozuvchilardagi 3x retry-o'ram."""
    from sqlalchemy.exc import IntegrityError as _IE
    for _try in range(3):
        try:
            return _stock_count_once(data, emp, db)
        except _IE:
            db.rollback()   # parallel INSERT to'qnashuvi — keyingi urinishda qator mavjud
    raise HTTPException(409, "Ombor band — sanoqni qayta yuboring")


def _stock_count_once(data: CountIn, emp: Employee, db: Session):
    # ⚠️  KUZATUVSIZ mahsulotda bu yo'l qoldiqni MUTLAQ qilib yozadi (delta emas).
    #     KUZATUVLIDA esa sanoq PARTIYA DARAJASIDA bo'ladi va umumiy son
    #     partiyalar yig'indisi bilan SOLISHTIRILADI (jimgina taqsimlanmaydi).
    from app.models.inventory import StockBatch as _SB
    from app.services import lot_policy as _LP
    from app.services import lot_writeoff as _LW
    from app.services import stock_gate as _SG
    from app.services import stock_invariant as _SI
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    # ⚠️  BITTA MAHSULOT — BITTA QATOR. Har qator o'z `StockMovement` qatorini AYNI
    #     `client_uuid` bilan yozadi, DB indeksi esa (client_uuid, product_id, type)
    #     ni NOYOB qiladi: ikkinchi qator IntegrityError berib, yuqoridagi 3x
    #     retry-o'ramiga tushardi va operator «Ombor band — qayta yuboring» degan
    #     YOLG'ON maslahatni ko'rardi. Xato so'rovning O'ZIDA, shu bois aniq 400.
    _seen_pid: set = set()
    for it in data.items:
        if it.product_id in _seen_pid:
            raise HTTPException(400, "Bitta mahsulot bir so'rovda IKKI MARTA sanalmaydi")
        _seen_pid.add(it.product_id)
    _jami_partiya = sum(len(it.lots or ()) + len(it.new_lots or ()) for it in data.items)
    if _jami_partiya > MAX_COUNT_LOT_LINES:
        raise HTTPException(400, f"Bitta so'rovda {_jami_partiya} ta partiya qatori — chegara "
                                 f"{MAX_COUNT_LOT_LINES}. Sanoqni bir necha so'rovga bo'lib yuboring.")
    # DEDUP (QA WH-023): shu client_uuid bilan sanoq allaqachon qo'llangan bo'lsa — qayta emas.
    # ⚠️  MAHSULOT BO'YICHA CHEGARALANADI (DB indeksi bilan bir xil kalit).
    #     Aks holda begona do'konning ayni client_uuid'i butun sanoqni jimgina
    #     «dublikat» deb yutib yuborardi va operator qoldiq yangilandi deb o'ylardi.
    if data.client_uuid:
        dup = db.query(StockMovement).filter(
            StockMovement.client_uuid == data.client_uuid,
            StockMovement.product_id.in_([it.product_id for it in data.items]),
            StockMovement.type == MovementType.adjustment).first()
        if dup:
            return {"ok": True, "duplicate": True, "changed": 0, "results": []}
    # ⚠️  EGALIK — TAKROR KALITIDAN KEYIN, KUZATUV VA QULFDAN OLDIN.
    #     Pastdagi qulf halqasi `Inventory` qatorini YARATADI: mavjud bo'lmagan
    #     `product_id` Postgres'da FK'ni buzib IntegrityError berardi va retry-o'rami
    #     uni tranzient deb «Ombor band» qilib ko'rsatardi (to'g'ri javob —
    #     «Mahsulot topilmadi»); begona tenant mahsuloti esa tekshiruvdan OLDIN shu
    #     filialda qator yozib ulgurardi. Kuzatuv tekshiruvi ham egalikdan KEYIN:
    #     aks holda yo'q mahsulot «kuzatuv yoqilmagan» degan noto'g'ri javob olardi.
    #     Takror kaliti esa BIRINCHI: allaqachon qo'llangan sanoqning qayta
    #     yuborilishi mahsulot keyin o'chirilgan yoki kuzatuvi o'zgargan bo'lsa ham
    #     «dublikat» bo'lib qoladi — operatorga bajarilgan amal xato bo'lib qaytmaydi.
    _prods = {it.product_id: _get_product(db, it.product_id, emp.company_id)
              for it in data.items}
    _tracked = {str(i) for i in _SG.tracked_ids(db, [it.product_id for it in data.items])}
    for it in data.items:
        if str(it.product_id) not in _tracked and (it.lots or it.new_lots):
            raise HTTPException(400, "Bu mahsulotda partiya kuzatuvi yoqilmagan — "
                                     "partiya ko'rsatib bo'lmaydi")
    branch = _resolve_write_branch(db, emp, data.branch_id)
    now = datetime.now(timezone.utc)
    results = []
    changed = 0
    _crossed: list = []
    # QATOR QULFI: sanoq inv.qty ni counted'ga MUTLAQ o'rnatadi — bir vaqtдаги sotuv o'rtада bo'lса
    # (qulfsiz) yo'qolардi. Qatorlarni DASTAVVAL bir xil tartibda (product_id) qulflaymiz.
    # QA WH-001: qator YO'Q bo'lsa shu yerda 0-qoldiq bilan YARATIB qulflaymiz — pre-lock'dan
    # keyin paydo bo'lgan qatorni qulfsiz o'qish (lost-update oynasi) yopiladi; parallel INSERT
    # to'qnashuvi flush'da otilib retry-o'ramga tushadi.
    for _pid in sorted({it.product_id for it in data.items}, key=str):
        _row = db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
        if _row is None:
            db.add(Inventory(product_id=_pid, branch_id=branch.id, qty=Decimal("0"), updated_at=now))
            db.flush()
            db.query(Inventory).filter(
                Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    # ⚠️  KUZATUV BAYROG'I QULFLARDAN KEYIN QAYTA O'QILADI (Phase 5B, W). Yuqoridagi
    #     `_tracked` qulfdan OLDIN o'qilgan: `/lots/enable` qatorni ushlab commit qilsa,
    #     sanoq ESKI «kuzatuvsiz» qaror bilan qoldiqni partiyalarsiz MUTLAQ yozardi.
    #     Mahsulot obyekti ham yangilanadi — `track_expiry` quyida o'qiladi.
    _tracked = _SG.refresh_tracking(db, list(_prods.values()))
    _touched_tracked: list = []
    for it in data.items:
        prod = _prods[it.product_id]
        counted = Decimal(str(it.counted))
        if str(it.product_id) in _tracked:
            counted = _LW._d(counted)   # kuzatuvli yo'l — ayni aniqlik (yuqoridagi izoh)
        _applied: list = []
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == prod.id, Inventory.branch_id == branch.id)
               .with_for_update().first())   # QA WH-001: o'qish ham qulf ostida
        old = Decimal(str(inv.qty))
        diff = counted - old
        _plan = None
        if str(prod.id) in _tracked:
            # QULF TARTIBI: Inventory (yuqorida) -> tartiblangan partiyalar.
            _open = (db.query(_SB)
                     .filter(_SB.product_id == prod.id, _SB.branch_id == branch.id,
                             _SB.status.in_(sorted(_SI.QUANTITY_BEARING)))
                     .order_by(_SB.id).all())
            _lock = _LW.lock_batches(db, [b.id for b in _open]
                                     + [l.stock_batch_id for l in (it.lots or [])])
            try:
                # ⚠️  ZONA TASDIG'I — QABUL YO'LI BILAN AYNI TALAB. Yangi partiya
                #     muddati filial BIZNES sanasiga tayanadi; tasdiq zona NOMI bilan
                #     saqlanadi va zona o'zgarsa kuchini yo'qotadi. Qabul bunday
                #     holatda to'xtaydi — sanoq to'xtamasa, ayni muddat ikkinchi
                #     eshikdan yozilardi. Mavjud partiyalarni sanash sana YOZMAYDI,
                #     shu bois u bu darvozadan o'tmaydi.
                #     O'TGAN muddat bu yerda RAD ETILMAYDI (qabuldan farqli): javondan
                #     topilgan muddati o'tgan qadoq JISMONAN bor — uni rad etish
                #     tovarni tizimdan yashirib, hisobdan chiqarishni imkonsiz qilardi.
                if prod.track_expiry and it.new_lots:
                    try:
                        _LP.assert_tz_confirmed(db, emp.company_id, branch.id)
                    except _LP.TimezoneNotConfigured as e:
                        raise HTTPException(409, str(e)) from e
                # ⚠️  MUDDAT KUZATUVIDA YANGI PARTIYA MUDDATSIZ BO'LMAYDI — qabul
                #     yo'lidagi qoida bilan AYNI. «Noma'lum muddat» jimgina qabul
                #     qilinsa, muddat hisoboti shu partiyani umuman ko'rmasdi.
                if prod.track_expiry:
                    for _n in (it.new_lots or []):
                        if _n.expiry_date is None:
                            raise HTTPException(
                                400, f"'{prod.name}' muddat bo'yicha kuzatiladi — yangi "
                                     f"partiyada `expiry_date` MAJBURIY. Noma'lum muddat "
                                     f"jimgina qabul qilinmaydi.")
                # ⚠️  MUDDAT KUZATUVI YO'Q MAHSULOTDA SANA QABUL QILINMAYDI. FEFO
                #     saralashi «track_expiry=False -> expiry_date IS NULL» ga
                #     tayanadi; bitta sanali partiya kogortani jimgina muddat
                #     bo'yicha saralashga o'tkazardi, o'tgan sana esa uni sotuvdan
                #     butunlay chiqarib, tovarni javonda qoldirardi. Sanani
                #     JIMGINA tashlab yuborish ham yaramaydi: operator uni ANIQ
                #     kiritdi — biz uning qarorini o'zboshimchalik bilan o'zgartira
                #     olmaymiz, faqat AYTAMIZ.
                else:
                    for _n in (it.new_lots or []):
                        if _n.expiry_date is not None:
                            raise HTTPException(
                                400, f"'{prod.name}' muddat bo'yicha KUZATILMAYDI — yangi "
                                     f"partiyaga `expiry_date` yozib bo'lmaydi. Avval "
                                     f"mahsulotda muddat kuzatuvini yoqing.")
                _plan = _LW.plan_count(
                    _lock, [(l.stock_batch_id, l.counted) for l in (it.lots or [])],
                    open_lots=[_lock.get(str(b.id), b) for b in _open],
                    company_id=emp.company_id, product_id=prod.id,
                    branch_id=branch.id, declared_total=counted,
                    new_lots=[{"qty": n.qty, "unit_cost": n.unit_cost, "batch_no": n.batch_no,
                               "expiry_date": n.expiry_date, "reason": n.reason}
                              for n in (it.new_lots or [])])
            except _LW.LotSelectionError as e:
                raise HTTPException(400, f"{prod.name}: {e}") from e
            _touched_tracked.append(prod.id)
        # ⚠️  `diff == 0` BO'LSA HAM HARAKAT YOZILISHI MUMKIN. Operator bir partiyani
        #     kamaytirib, ayni miqdorda YANGI partiya e'lon qilsa, mahsulot jami
        #     o'zgarmaydi — PARTIYA tarkibi esa o'zgaradi. `qty = 0` harakat
        #     ATAYLAB qonuniy: allokatsiya qatorlari unga bog'lanadi va «qaysi
        #     kogorta qayerga ketdi» savoliga javob shu yerda qoladi.
        if diff != 0 or (_plan is not None and (_plan.decrements or _plan.surpluses or _plan.new_lots)):
            changed += 1
            inv.qty = counted
            inv.updated_at = now
            if counted > Decimal(str(inv.min_qty or 0)):
                inv.low_alerted = False
            else:
                _low_cross_check(inv, prod.name, _crossed)   # QA WH-009: pastga tuzatish ham ogohlantiradi
            _mv_id = uuid.uuid4()
            db.add(StockMovement(id=_mv_id, product_id=prod.id, branch_id=branch.id,
                                 type=MovementType.adjustment,
                                 qty=diff, balance_after=counted, ref_type="count", reason="inventarizatsiya",
                                 employee_id=emp.id, client_uuid=data.client_uuid, created_at=now))
            if _plan is not None:
                db.flush()      # allokatsiya FK'si uchun harakat qatori MAVJUD bo'lsin
                _yangi = _LW.apply_count(db, _plan, movement_id=_mv_id,
                                         company_id=emp.company_id, product_id=prod.id,
                                         branch_id=branch.id, now=now)
                _applied = list(_yangi)
                _audit_log(db, emp.id, "update", "stock_count", _mv_id,
                           after={"product_id": str(prod.id), "branch_id": str(branch.id),
                                  "old": float(old), "counted": float(counted),
                                  "kamaygan": [{"stock_batch_id": str(b.id), "qty": float(q)}
                                               for b, q in _plan.decrements],
                                  "ortiqcha": [{"manba_batch_id": str(b.id), "qty": float(q),
                                                "yangi_batch_id": str(nb.id)}
                                               for (b, q), nb in zip(_plan.surpluses, _yangi)],
                                  # Phase 4B: operator E'LON QILGAN partiyalar (manbasiz).
                                  # ⚠️  SABAB ham yoziladi: «javon ortidan chiqdi» degan
                                  #     izoh keyin qaralganda yagona tushuntirish bo'ladi
                                  #     — partiyaning o'zida hujjat YO'Q.
                                  "yangi_partiyalar": [
                                      {"stock_batch_id": str(nb.id), "qty": float(nb.remaining_qty),
                                       "unit_cost": float(nb.unit_cost), "batch_no": nb.batch_no,
                                       "expiry_date": nb.expiry_date.isoformat() if nb.expiry_date else None,
                                       "reason": (nl or {}).get("reason")}
                                      for nb, nl in zip(_yangi[len(_plan.surpluses):], _plan.new_lots)]})
        # ⚠️  UI PARTIYA DARAJASIDA KO'RSATADI. Ilgari javob faqat mahsulot
        #     jamini qaytarardi va operator «qaysi partiya qancha o'zgardi» ni
        #     ko'rmasdi — bu sanoqni tekshirib bo'lmaydigan qilardi.
        _row = {"product": prod.name, "product_id": str(prod.id),
                "old": float(old), "counted": float(counted), "diff": float(diff)}
        if _plan is not None:
            _row["lots"] = {
                "decrements": [{"stock_batch_id": str(b.id), "qty": float(q)}
                               for b, q in _plan.decrements],
                "surpluses": [{"stock_batch_id": str(b.id), "qty": float(q)}
                              for b, q in _plan.surpluses],
                "created": [{"stock_batch_id": str(nb.id), "qty": float(nb.remaining_qty),
                             "unit_cost": float(nb.unit_cost), "batch_no": nb.batch_no,
                             "expiry_date": nb.expiry_date.isoformat() if nb.expiry_date else None,
                             "source_type": nb.source_type} for nb in _applied]}
        results.append(_row)
    if _touched_tracked:
        db.flush()
        # ── YAKUNIY DARVOZA: qoldiq va partiyalar MOS ekanini isbotlaymiz ──
        try:
            _SI.assert_ok(db, emp.company_id, _touched_tracked)
        except Exception as e:      # noqa: BLE001
            db.rollback()
            # ⚠️  ISTISNO MATNI OPERATORGA BERILMAYDI. `InvariantBroken` ichida xom
            #     UUID'lar, `≠` belgisi va modul/konstanta nomlari bor — ular do'kon
            #     egasiga hech narsa aytmaydi, tarjima ham qilinmaydi va ichki
            #     tuzilmani ochadi. Tafsilot JURNALGA yoziladi.
            log.exception("count invariant buzildi: products=%s", _touched_tracked)
            raise HTTPException(409, "Inventarizatsiyani yozib bo'lmadi — partiya va qoldiq "
                                     "mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga "
                                     "murojaat qiling.",
                                headers=EC.headers(EC.LOT_INVARIANT_BROKEN)) from e
    db.commit()
    _push_low(db, emp.company_id, _crossed, branch.name)
    return {"ok": True, "changed": changed, "results": results}


@router.get("/inventory/low")
def low_stock(emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db)):
    # QA WH-020: hisobot.view darvozasi. QA WH-010: min_qty>0 sharti — aks holda katta katalogda
    # (Fayzan: import min=0) har qty=0 mahsulot '0<=0' bilan ro'yxatni bosardi; limit ham qo'shildi.
    from app.core.deps import visible_branches
    _bset = visible_branches(emp, db)
    q = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True),
                Inventory.min_qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    if _bset is not None:
        q = q.filter(Inventory.branch_id.in_(_bset))
    rows = q.order_by(Inventory.qty).limit(200).all()
    return [{"name": n, "qty": float(q), "min": float(mn)} for n, q, mn in rows]
