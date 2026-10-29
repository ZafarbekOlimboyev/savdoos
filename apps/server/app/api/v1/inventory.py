import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

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
def overview(
    # Phase 5G: ixtiyoriy BITTA filial (mobil "joriy filial"). Tekshiruv `GET /products?branch_id=`
    # bilan AYNAN bir yordamchi (`_stock_scope`): begona/o'chirilgan -> 400, ko'rish doirasidan
    # tashqari -> 403. BERILMASA javob AVVALGIDEK (desktop Dashboard/Manager).
    branch_id: uuid.UUID | None = None,
    emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db),
):
    from app.api.v1.products import _stock_scope
    # filialга bog'langan xodim — faqat o'z filiali qoldig'i; `branch_id` — faqat o'sha filial.
    # ⚠️  `total_products` — KATALOG hajmi (mahsulot kompaniya darajasida, filialga bog'lanmagan),
    #     shu bois filial berilganda ham o'zgarmaydi; qoldiq/harakat sonlari esa filialniki.
    bset = _stock_scope(db, emp, branch_id)
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


def _lot_headers(e) -> dict | None:
    """Partiya tanlovi xatosining barqaror kodi (Phase 5G) — `X-Error-Code` uchun."""
    code = getattr(e, "code", None)
    return EC.headers(code) if code else None


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


#  R6.8 P0-1 — «SO'NGGI O'XSHASH CHIQARISH» OYNASI (daqiqa).
#
#  ⚠️  NEGA 30. Token 12 soat yashaydi, ya'ni 401 har qanday paytda keladi;
#      operator qoralamasi yo'qolgach amalni qayta kiritishi — qayta kirish,
#      mahsulotni qidirish, partiyalarni to'ldirish — amalda bir necha daqiqa.
#      Oyna qanchalik uzun bo'lsa shuncha ko'p tasodifiy takror tutiladi, lekin
#      shuncha ko'p HAQIQIY takror ham tasdiq so'raydi. 30 daqiqa — do'kon
#      ritmida ikki alohida chiqarishning kamdan-kam uchraydigan oralig'i.
#  ⚠️  MUHITDAN O'ZGARTIRILADI, lekin O'CHIRIB bo'lmaydi: `0` berilsa darvoza
#      YOPILMAYDI, eng kichik qiymat 1 daqiqa. Moliyaviy himoyani muhit
#      o'zgaruvchisi bilan jimgina o'chirib qo'yish mumkin bo'lmasligi kerak.
WRITEOFF_DUP_WINDOW_MIN = max(1, int(os.getenv("SAVDOOS_WRITEOFF_DUP_WINDOW_MIN", "30")))


class WriteoffIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    reason: str | None = Field(default=None, max_length=200)  # brak | expired | inventory | ...
    client_uuid: uuid.UUID | None = None  # idempotentlik — timeout'да qayta yuborishда ikki marta kamaymasin
    branch_id: uuid.UUID | None = None    # QA WH-002: qaysi filialdan chiqarish (berilmasa actor)
    # ⚠️  KUZATUVLI mahsulotda MAJBURIY. Tizim qaysi jismoniy partiya
    #     tashlanayotganini TAXMIN QILMAYDI — batafsil: `services/lot_writeoff.py`.
    lots: list[WriteoffLot] | None = Field(default=None, max_length=200)
    #  R6.8 P0-1: operator «ha, bu HAQIQATAN ikkinchi, alohida chiqarish» dedi.
    #  FAQAT `WRITEOFF_DUPLICATE_SUSPECTED` darvozasini ochadi; `client_uuid`
    #  dedup'iga va boshqa hech qanday tekshiruvga TA'SIR QILMAYDI.
    confirm_duplicate: bool = False


def _same_writeoff(mv: StockMovement, data: WriteoffIn, *, branch_hint) -> bool:
    """Saqlangan harakat qatori AYNI amalmi — kalit qayta ishlatilganini aniqlash.

    Kalit (`client_uuid`, `product_id`, `type`) tashqarisidagi MODDIY maydonlar
    solishtiriladi: miqdor, sabab va (so'rovда ANIQ berilgan bo'lsa) filial.

    ⚠️  FILIAL FAQAT ANIQ BERILGANDA solishtiriladi. Berilmasa yozuv filiali
        `actor_branch` dan kelib chiqadi; xodim biriktiruvi orada o'zgargan
        bo'lsa (R6.8 P0-2 ga qarang) «boshqa filial» degan YOLG'ON xulosa
        chiqib, haqiqiy takror 409 bo'lib ketardi.
    ⚠️  MIQDOR `Decimal` bilan: harakat qatorida u MANFIY (`qty=-qty`) va
        NUMERIC(14,3); `float` solishtiruvi 0.1+0.2 sinfidagi xato berardi.
    """
    if Decimal(str(mv.qty)) != -Decimal(str(data.qty)):
        return False
    if (mv.reason or "") != (data.reason or ""):
        return False
    if branch_hint is not None and mv.branch_id != branch_hint:
        return False
    return True


def _assert_no_recent_twin(db: Session, prod: Product, branch: Branch,
                           qty: Decimal, data: WriteoffIn) -> None:
    """Shu filialda JUDA YAQINDA yozilgan AYNI chiqarish bo'lsa — 409 (R6.8 P0-1).

    DOIRA: filial + mahsulot + miqdor + sabab, oyna
    [hozir - `WRITEOFF_DUP_WINDOW_MIN`, hozir], `client_uuid` esa BOSHQA
    (yoki yo'q). Ayni kalit bu yerga YETIB KELMAYDI — uni yuqoridagi dedup
    shoxi hal qiladi.

    ⚠️  NEGA FILIAL DOIRASIDA, XODIM DOIRASIDA EMAS. Zarar QOLDIQDA, qoldiq esa
        bitta: ikkinchi yozuvni kim qilishidan qat'iy nazar partiya va tannarx
        ikki marta chiqadi. Xodim bo'yicha cheklash himoyani sabab-siz
        toraytirardi.

    ⚠️  NEGA BU DEDUP EMAS. Hech narsa jimgina yutilmaydi va «ok» ham
        deyilmaydi: mijoz operatorga oldingi chiqarishni ko'rsatadi va u
        TASDIQLASA (`confirm_duplicate=true`) ikkinchi yozuv BAJARILADI.
        Spetsifikatsiya aynan shuni talab qiladi: bir xil mahsulot/miqdor/sabab
        bilan ikkita HAQIQIY, alohida chiqarish qonuniy bo'lishi mumkin.

    ⚠️  SANA `created_at` BO'YICHA, `at` (tarixiy payt) bo'yicha EMAS. Tarixiy
        qayta yurish (`_H`) o'z darvozalariga ega va u yerda oyna ma'nosiz
        bo'lardi — shu bois faqat JONLI yozuv vaqti.
    """
    chegara = datetime.now(timezone.utc) - timedelta(minutes=WRITEOFF_DUP_WINDOW_MIN)
    q = (db.query(StockMovement)
         .filter(StockMovement.product_id == prod.id,
                 StockMovement.branch_id == branch.id,
                 StockMovement.type == MovementType.writeoff,
                 StockMovement.qty == -qty,
                 StockMovement.created_at >= chegara))
    if data.client_uuid is not None:
        q = q.filter(StockMovement.client_uuid != data.client_uuid)
    for mv in q.order_by(StockMovement.created_at.desc()).limit(20).all():
        if (mv.reason or "") != (data.reason or ""):
            continue
        #  Vaqtni OPERATOR TILIDA bermaymiz: `detail` tarjima lug'atining kaliti
        #  (`test_lot_error_texts`), ya'ni matn BARQAROR bo'lishi kerak.
        #  Tafsilot sarlavhada va mijoz `GET /inventory/movements` bilan
        #  ko'rsatadi.
        raise HTTPException(409, "Bu hisobdan chiqarish shu filialda yaqinda allaqachon "
                                 "yozilgan. Agar bu HAQIQATAN ikkinchi, alohida amal "
                                 "bo'lsa — tasdiqlang; aks holda qoldiq ikki marta "
                                 "kamayadi.",
                            headers=EC.headers(EC.WRITEOFF_DUPLICATE_SUSPECTED))


@router.get("/inventory/writeoff/status")
def writeoff_status(client_uuid: uuid.UUID, product_id: uuid.UUID,
                    emp: Employee = Depends(require("ombor.view")),
                    db: Session = Depends(get_db)):
    """Shu `client_uuid` bilan chiqarish YOZILGANMI — NOMA'LUM urinishni hal qiladi.

    ⚠️  NEGA KERAK (R6.8 P0-1). Javob yo'qolganda mijoz amal bajarilgan-
        bajarilmaganini BILMAYDI va taxmin qilishi MUMKIN EMAS: taxmin ikki
        marta yozishga yoki butunlay yozilmay qolishiga olib borardi. Bu
        marshrut javobni ANIQ beradi — qayta yozuvsiz, faqat o'qish.

    ⚠️  MAHSULOT EGALIGI TEKSHIRILADI. `stock_movements` da `company_id` ustuni
        YO'Q (`_writeoff_once` izohi), ya'ni tekshiruvsiz so'rov BOSHQA
        do'konning kaliti bo'yicha javob berib, kalit mavjudligini oshkor
        qilardi.
    """
    prod = _get_product(db, product_id, emp.company_id)
    mv = (db.query(StockMovement)
          .filter(StockMovement.client_uuid == client_uuid,
                  StockMovement.product_id == prod.id,
                  StockMovement.type == MovementType.writeoff)
          .order_by(StockMovement.created_at.desc()).first())
    if mv is None:
        return {"recorded": False}
    return {"recorded": True, "movement_id": str(mv.id),
            "qty": float(-Decimal(str(mv.qty))), "reason": mv.reason,
            "branch_id": str(mv.branch_id),
            "at": mv.created_at.isoformat() if mv.created_at else None}


@router.post("/inventory/writeoff")
def writeoff(data: WriteoffIn, emp: Employee = Depends(require("ombor.edit")), db: Session = Depends(get_db)):
    """Hisobdan chiqarish (brak/muddati o'tgan/inventar) — qoldiqni kamaytiradi + ledger.

    ⚠️  NAQD PULGA TEGMAYDI. Tashlangan tovar — zaxira yo'qotishi, kassa amali
        EMAS. CashLedger'ga leg yozish kassada bo'lmagan pul harakatini
        ko'rsatardi va smena yopilishini buzardi.
    """
    #  ⚠️  YUPQA O'ROVCHI (H3b). Tana `_writeoff_once` ga ko'chdi, chunki tarixiy
    #      bajarish `at` ni talab qiladi, MARSHRUT imzosiga esa vaqt maydoni
    #      QO'SHILMAYDI — u FastAPI'da query parametri bo'lib qolardi va har
    #      qanday mijoz tarixiy yozuv so'rashga urinib ko'rardi.
    #  ⚠️  NOMI, PARAMETRLARI VA TARTIBI O'ZGARMAYDI: mavjud testlar yozuvchini
    #      TO'G'RIDAN import qiladi — `tests/cash/test_return_cash_posting.py`
    #      va `tests/test_lot_enable_race_pg.py` `writeoff(data, emp, db)` deb
    #      pozitsion chaqiradi.
    return _writeoff_once(data, emp, db)


def _writeoff_once(data: WriteoffIn, emp: Employee, db: Session, *,
                   at: datetime | None = None):
    """Hisobdan chiqarishning KANONIK tanasi (`at` = tarixiy payt, H3b).

    ⚠️  TANA SHU FAYLDA QOLDI — yangi servis moduliga KO'CHIRILMADI, va bu
        ATAYLAB. `tests/test_lot_error_texts.py` da UCHTA manba ro'yxati
        (`SOURCES`, `CASH_SOURCES`, `ID_SOURCES`) aynan `api/v1/*.py`
        fayllarini skanerlab, operator ko'radigan xato matnlarini frontend
        tarjima lug'atida va id-oqmasligida tekshiradi. Tanani boshqa modulga
        ko'chirish bu xabarlarni uch detektordan JIMGINA chiqarib tashlardi —
        gard QIZIL BO'LMASDAN, chunki u endi boshqa faylni skanerlaydi. Audit
        AU-2 §4.3 aynan shu teshik sababli bu fayllarni ro'yxatga qo'shgan
        (oltita xabar bazadan olingan UUID bilan chiqib ketgan edi).
    """
    from app.services import historical as _H
    #  ⚠️  DARVOZA ENG BOSHIDA, SOAT esa o'z joyida. Kontekstsiz `at` DARHOL rad
    #      etilishi SHART: aks holda u jimgina qabul qilinib, keyinroq BUTUNLAY
    #      BOSHQA sabab bilan rad etilardi (o'lchangan: «Ochiq smena yo'q») —
    #      xato chalg'ituvchi bo'lardi va rad etishdan OLDIN ish bajarilgan
    #      bo'lardi. Batafsil: `historical.assert_gate`.
    _H.assert_gate(at, emp.company_id)
    #  Kontekst FAOL bo'lsa `at` berilishi SHART.
    if _H.active() is not None:
        _H.require_at(at, writer="hisobdan chiqarish")
    #  ⚠️  INDEKS KAFOLATI — YOZUVDAN VA QULFDAN OLDIN (fail-closed).
    #      Quyidagi dedup SELECT-keyin-INSERT: u KETMA-KET takrorni ushlaydi, lekin
    #      KONKURRENT takrorni faqat noyob indeks to'sadi. Indeks yo'q yoki shakli
    #      boshqa bo'lsa tayyorlik qizil bo'ladi, lekin u YOZUVNI TO'SMAYDI
    #      (`/health/ready` — monitoring signali). Shu bois darvoza SHU YERDA.
    #      Gard qulfdan OLDIN: yangi qulf tartibi YARATILMAYDI va rad etish
    #      birorta qator qulflanmasdan sodir bo'ladi.
    from app.core.index_guard import require_index
    require_index(db, "ux_stockmov_client_prod_type", "stock_movements",
                  operation="writeoff")
    # ⚠️  BIRLIK DARVOZASI — QULFDAN va YOZUVDAN oldin. Bo'linmas birlikda
    #     `0.25 dona` hisobdan chiqarish RAD etiladi. Partiya qatorlari ALOHIDA,
    #     XOM holda tekshiriladi: `lot_writeoff.validate` faqat `Σ lots[].qty == qty`
    #     ni talab qiladi, ya'ni `0.5 + 0.5` yig'indisi `qty=1` bilan MOS kelib,
    #     yaroqsiz partiya miqdorlari butun jamiga YUVILARDI.
    from app.services import unit_gate as _UG
    _UG.validate_one(db, data.product_id, data.qty, label="hisobdan chiqarish")
    for _lot in (data.lots or []):
        _UG.validate_one(db, data.product_id, _lot.qty, label="hisobdan chiqarish partiyasi")
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
            #  ⚠️  R6.8: KALIT QAYTA ISHLATILGANINI ANIQLASH. Ilgari bu shox
            #      MAZMUNNI solishtirmasdan `duplicate: true` qaytarardi: ayni
            #      kalit bilan BOSHQA miqdor/sabab/filial kelsa operator
            #      «bajarildi» degan javob olardi, holbuki HECH NARSA
            #      yozilmagan va serverda BOSHQA amal turadi. Bu TAKROR emas —
            #      mijoz xatosi; repo konvensiyasi `IDEMPOTENCY_KEY_REUSED`
            #      (`core/error_codes.py`, naqd yo'lida AYNI semantika).
            if not _same_writeoff(dup, data, branch_hint=data.branch_id):
                raise HTTPException(409, "Bu idempotentlik kaliti BOSHQA hisobdan chiqarish "
                                         "uchun ishlatilgan — amal YOZILMADI. Yangi kalit "
                                         "bilan qaytadan yuboring.",
                                    headers=EC.headers(EC.IDEMPOTENCY_KEY_REUSED))
            return {"ok": True, "duplicate": True}
    from app.services import lot_writeoff as _LW
    from app.services import stock_gate as _SG
    from app.services import stock_invariant as _SI
    _tracked = bool(_SG.tracked_ids(db, [data.product_id]))
    _lots_in = [(l.stock_batch_id, l.qty) for l in (data.lots or [])]
    if not _tracked and _lots_in:
        raise HTTPException(400, "Bu mahsulotda partiya kuzatuvi yoqilmagan — "
                                 "partiya ko'rsatib bo'lmaydi",
                            headers=EC.headers(EC.LOT_LINES_FORBIDDEN))
    branch = _resolve_write_branch(db, emp, data.branch_id)
    prod = _get_product(db, data.product_id, emp.company_id)
    qty = Decimal(str(data.qty))
    #  ⚠️  R6.8 P0-1 DARVOZASI — QULFDAN va YOZUVDAN OLDIN (repo konvensiyasi:
    #      rad etish birorta qator qulflanmasdan sodir bo'lsin). Filial va
    #      mahsulot ANIQLANGANDAN keyin, chunki doira aynan shu juftlikda.
    #
    #  ⚠️  TARIXIY QAYTA YURISH (`at is not None`) DARVOZADAN CHIQARILADI.
    #      Oyna — JONLI operator evristikasi («operator hozir ikkinchi marta
    #      kiritdi»); o'tmishdagi hodisalarni qayta ijro etishda uning ma'nosi
    #      YO'Q. Tarixiy yozuv `created_at` ni O'TMISHGA qo'yadi, ya'ni oyna
    #      uni amalda ko'rmaydi ham — lekin tasodifga tayanmaymiz: yaqinda
    #      bo'lgan JONLI chiqarish tarixiy replay'ni to'sib qo'yishi mumkin
    #      edi. Tarixiy yo'lning O'Z darvozalari bor
    #      (`services/historical_recovery.py` kalit bo'yicha probe,
    #      `_H.assert_gate`, vendor-only `POST /events`) va `client_uuid`
    #      dedup'i bu yerda ham ishlaydi.
    if at is None and not data.confirm_duplicate:
        _assert_no_recent_twin(db, prod, branch, qty, data)
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
    now = _H.resolve_at(at, emp.company_id)
    _plan = None
    if _tracked:
        _batches = _LW.lock_batches(db, [b for b, _ in _lots_in])
        try:
            _plan = _LW.validate(_batches, _lots_in, company_id=emp.company_id,
                                 product_id=prod.id, branch_id=branch.id, total_qty=qty)
        except _LW.LotSelectionError as e:
            # Phase 5G: barqaror kod `X-Error-Code` da (matn va 400 O'ZGARMAYDI).
            raise HTTPException(400, str(e), headers=_lot_headers(e)) from e
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
    from sqlalchemy.exc import IntegrityError as _IE
    if _plan is not None:
        # Harakat qatori allokatsiya FK'sidan OLDIN mavjud bo'lishi shart.
        #
        # ⚠️  BU `flush` HARAKAT QATORINI INSERT QILADI, ya'ni noyob indeks
        #     (`ux_stockmov_client_prod_type`) to'qnashuvi AYNAN SHU YERDA
        #     otiladi — pastdagi `commit` ning `try` bloki esa unga YETIB
        #     BORMAYDI. Kuzatuvsiz yo'lda INSERT faqat `commit` da bo'ladi, shu
        #     bois nuqson FAQAT kuzatuvli mahsulotda ko'rinardi: bir vaqtda
        #     kelgan AYNI kalitli ikkinchi so'rov `duplicate: true` emas,
        #     tutilmagan `IntegrityError` -> 500 olardi. R6.8 P0-1 da topildi;
        #     qo'shni yozuvchilar (`/inventory/transfer`, `/inventory/count`)
        #     allaqachon qayta urinish o'ramiga ega.
        try:
            db.flush()
        except _IE:
            db.rollback()
            if data.client_uuid:
                return {"ok": True, "duplicate": True}
            raise
        # `apply` ANIQ (yaxlitlanmagan) yig'indini qaytaradi — pul maydoniga
        # chiqishdan oldin ATAYIN HALF_UP bilan yaxlitlanadi (butun repo shunday;
        # ilgari `apply` ichida Decimal sukut rejimi HALF_EVEN bilan kesilardi).
        _cost = _LW.apply(db, _plan, movement_id=_mv_id, company_id=emp.company_id,
                          product_id=prod.id, now=now).quantize(
                              Decimal("0.01"), rounding=ROUND_HALF_UP)
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
        #  ⚠️  `at` BU YERDA ham SHART (H3b topilmasi). H3a sanoq auditiga uni
        #      uzatgan, chiqarish auditiga esa UZATMAGAN edi — tarixiy chiqarish
        #      audit izi BUGUNGI payt bilan yozilib, hujjatning O'ZI bilan
        #      ziddiyatga tushardi. Bu shox FAQAT kuzatuvli mahsulotda ishlaydi
        #      (`if _plan is not None`), shu bois kuzatuvsiz chiqarish audit
        #      qatori UMUMAN yozmaydi — testda aynan kuzatuvli yo'l o'lchanadi.
        _audit_log(db, emp.id, "delete", "stock_writeoff", _mv_id,
                   at=(now if at is not None else None),
                   after={"product_id": str(prod.id), "branch_id": str(branch.id),
                          "qty": float(qty), "reason": data.reason,
                          "cost_total": float(_cost),
                          "lots": [{"stock_batch_id": str(b.id), "qty": float(q),
                                    "unit_cost": float(b.unit_cost or 0)}
                                   for b, q in _plan]})
    # SELECT-dedup (yuqorida) race'ga chidamli emas — ikki konkurrent takror qoldiqni 2x kamaytirardi.
    # DB unique indeksi (ux_stockmov_client_prod_type) ikkinchisini ushlaydi -> tranzaksiya bekor, dublikat javob.
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


def _stock_count_once(data: CountIn, emp: Employee, db: Session, *,
                      at: datetime | None = None):
    # ⚠️  KUZATUVSIZ mahsulotda bu yo'l qoldiqni MUTLAQ qilib yozadi (delta emas).
    #     KUZATUVLIDA esa sanoq PARTIYA DARAJASIDA bo'ladi va umumiy son
    #     partiyalar yig'indisi bilan SOLISHTIRILADI (jimgina taqsimlanmaydi).
    from app.models.inventory import StockBatch as _SB
    from app.services import historical as _H
    from app.services import lot_policy as _LP
    from app.services import lot_writeoff as _LW
    from app.services import stock_gate as _SG
    from app.services import stock_invariant as _SI
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")
    # ⚠️  BIRLIK DARVOZASI — FARQ hisoblanishidan, agregatsiyadan va qoldiqni
    #     MUTLAQ yozishdan OLDIN. Bu yo'l qoldiqni to'g'ridan-to'g'ri o'rnatadi,
    #     ya'ni `counted=0.25 dona` qoldiqni fizik ma'nosiz holatga keltirardi.
    #     UCH manba ham XOM holda tekshiriladi: `counted`, `lots[].counted`,
    #     `new_lots[].qty` — aks holda kasr partiyalar butun jamiga yuvilardi.
    from app.services import unit_gate as _UG
    _ug_fmap = _UG.fraction_map(db, [i.product_id for i in data.items])
    for _i in data.items:
        _rows = [(_i.product_id, _i.counted)]
        _rows += [(_i.product_id, _l.counted) for _l in (_i.lots or [])]
        _rows += [(_i.product_id, _l.qty) for _l in (_i.new_lots or [])]
        _UG.validate_with_map(_ug_fmap, _rows, db=db, label="sanoq")
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
                                     "partiya ko'rsatib bo'lmaydi",
                                headers=EC.headers(EC.LOT_LINES_FORBIDDEN))
    branch = _resolve_write_branch(db, emp, data.branch_id)
    now = _H.resolve_at(at, emp.company_id)
    #  ⚠️  XRONOLOGIYA GARDI — FAQAT tarixiy kontekstda, QULFLARDAN OLDIN.
    #      Inventarizatsiya MUTLAQ yozuvchi (`inv.qty = counted`), ya'ni faqat
    #      o'z paytida qo'llanilsa to'g'ri. Keyinroq sanalgan harakat allaqachon
    #      yozilgan bo'lsa, bu yozuv uning ta'sirini YO'Q qiladi va farq
    #      ishorasini ham teskari qilishi mumkin — buni hech narsa ko'rsatmaydi.
    #      Qulfdan OLDIN: rad etish birorta qator qulflanmasdan sodir bo'ladi va
    #      yangi qulf tartibi YARATILMAYDI (yuqoridagi `writeoff` konvensiyasi).
    #      Batafsil: `services/historical.assert_chronological`.
    #  ⚠️  Darvoza `_H.active()` da, `at is not None` da EMAS: kontekst ichida
    #      `at` berishni UNUTISH ham xato — sanoq jimgina BUGUNGI sana bilan
    #      yozilib, gardning o'zini ma'nosiz qilardi.
    if _H.active() is not None:
        _H.require_at(at, writer="inventarizatsiya")
        _H.assert_chronological(db, branch_id=branch.id,
                                product_ids=[i.product_id for i in data.items],
                                at=now)
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
                        raise HTTPException(409, str(e),
                                            headers=EC.headers(EC.LOT_TZ_NOT_CONFIRMED)) from e
                # ⚠️  MUDDAT KUZATUVIDA YANGI PARTIYA MUDDATSIZ BO'LMAYDI — qabul
                #     yo'lidagi qoida bilan AYNI. «Noma'lum muddat» jimgina qabul
                #     qilinsa, muddat hisoboti shu partiyani umuman ko'rmasdi.
                if prod.track_expiry:
                    for _n in (it.new_lots or []):
                        if _n.expiry_date is None:
                            raise HTTPException(
                                400, f"'{prod.name}' muddat bo'yicha kuzatiladi — yangi "
                                     f"partiyada `expiry_date` MAJBURIY. Noma'lum muddat "
                                     f"jimgina qabul qilinmaydi.",
                                headers=EC.headers(EC.LOT_EXPIRY_REQUIRED))
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
                                     f"mahsulotda muddat kuzatuvini yoqing.",
                                headers=EC.headers(EC.LOT_EXPIRY_FORBIDDEN))
                _plan = _LW.plan_count(
                    _lock, [(l.stock_batch_id, l.counted) for l in (it.lots or [])],
                    open_lots=[_lock.get(str(b.id), b) for b in _open],
                    company_id=emp.company_id, product_id=prod.id,
                    branch_id=branch.id, declared_total=counted,
                    new_lots=[{"qty": n.qty, "unit_cost": n.unit_cost, "batch_no": n.batch_no,
                               "expiry_date": n.expiry_date, "reason": n.reason}
                              for n in (it.new_lots or [])])
            except _LW.LotSelectionError as e:
                raise HTTPException(400, f"{prod.name}: {e}", headers=_lot_headers(e)) from e
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
                _audit_log(db, emp.id, "update", "stock_count", _mv_id, at=(now if at is not None else None),
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
def low_stock(
    # Phase 5G: ixtiyoriy BITTA filial — tekshiruv `overview` / `GET /products?branch_id=` bilan AYNI.
    branch_id: uuid.UUID | None = None,
    emp: Employee = Depends(require("hisobot.view")), db: Session = Depends(get_db),
):
    # QA WH-020: hisobot.view darvozasi. QA WH-010: min_qty>0 sharti — aks holda katta katalogda
    # (Fayzan: import min=0) har qty=0 mahsulot '0<=0' bilan ro'yxatni bosardi; limit ham qo'shildi.
    from app.api.v1.products import _stock_scope
    _bset = _stock_scope(db, emp, branch_id)
    q = (
        db.query(Product.name, Inventory.qty, Inventory.min_qty, Product.id)
        .join(Inventory, Inventory.product_id == Product.id)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None), Product.is_active.is_(True),
                Inventory.min_qty > 0, Inventory.qty <= Inventory.min_qty)
    )
    if _bset is not None:
        q = q.filter(Inventory.branch_id.in_(_bset))
    rows = q.order_by(Inventory.qty).limit(200).all()
    # Phase 5G: `product_id` — QO'SHIMCHA maydon (mobil qatordan mahsulot kartasini ochadi);
    # mavjud kalitlar va ularning tartibi O'ZGARMAGAN.
    return [{"name": n, "qty": float(q), "min": float(mn), "product_id": str(pid)}
            for n, q, mn, pid in rows]
