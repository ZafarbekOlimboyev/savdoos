"""Mobil "Tovar qabul qilish" — nakladnoy skani → AI o'qish → moslash → omborga kirim.

Xavfsizlik: AI natijasi FAQAT taklif; ombor faqat foydalanuvchi tasdig'idan keyin o'zgaradi.
Har qabul audit uchun saqlanadi (rasm + AI dastlabki + yakuniy tahrir)."""
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.core.deps import require
from app.db.session import get_db
from app.services import doc_seq as _DS
from app.services.currency import company_currency as _company_currency
from app.models.auth import Employee
from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import CreditTxnType, MovementType, PurchaseStatus
from app.models.inventory import Inventory, StockMovement
from app.models.org import Branch
from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierLedger
from app.models.receiving import Receiving
from app.services import lot_policy as LP
from app.services import lot_receiving as _LR
from app.services.receiving_ai import match_products, read_invoice

log = logging.getLogger(__name__)

router = APIRouter(tags=["receiving"])

_DEFAULT_SUPPLIER = "Qabul (mobil)"


class ScanIn(BaseModel):
    image_b64: str = Field(max_length=15_000_000)   # ~11MB rasm shifti — cheksiz yuklashга qarshi
    media_type: str = Field(default="image/jpeg", max_length=60)
    #  ⚠️  MIJOZ RASMNI QAYSI TALAB ostida yuborayotgani. DARVOZA EMAS:
    #      haqiqiy darvoza — `ai_consent.require_consent` (serverdagi yozuv).
    #      Bu maydon TOCTOU ni yopadi: operator A provayderi uchun rozilik
    #      ko'rsatilgan ekranda turib rasm yuborsa, konfiguratsiya esa shu
    #      orada B ga o'tgan bo'lsa — rasm B ga JIM ketmaydi, 409 qaytadi.
    #      IXTIYORIY: o'rnatilgan desktop mijozlar uni yubormaydi va
    #      ularning yo'li O'ZGARMAYDI (rozilik darvozasi mustaqil ishlaydi).
    revision: int | None = Field(default=None, ge=1, le=10_000)


class ConsentIn(BaseModel):
    """⚠️  MIJOZ FAQAT O'ZI KO'RSATGAN OSHKOR ETISH VERSIYASINI bildiradi.

    `provider`, `model`, `granted_at`, `employee_id`, `revision` — SERVER
    aniqlaydi (`services/ai_consent.py`). Mijozdan kelgan `consent: true` kabi
    bayroq rozilik DALILI emas va bu DTO'da bunday maydon YO'Q.

    ⚠️  PASTDAGI UCH MAYDON — MIJOZ KUTGANI, AVTORITET EMAS. Server ularni
        HECH QACHON yozmaydi; faqat O'Z holati bilan solishtiradi va mos
        kelmasa 409 (`AI_REQUIREMENT_CHANGED`) beradi. Ya'ni foydalanuvchi
        ekranda ko'rgan talab bilan yozilgan rozilik AYNAN bir xil bo'ladi.
        Ular IXTIYORIY: o'rnatilgan desktop mijoz faqat `disclosure_version`
        yuboradi va uning yo'li o'zgarmaydi."""
    disclosure_version: int = Field(ge=1, le=1000)
    revision: int | None = Field(default=None, ge=1, le=10_000)
    provider: str | None = Field(default=None, max_length=40)
    disclosure_id: str | None = Field(default=None, max_length=100)


@router.get("/receiving/ai-consent")
def ai_consent_status(emp: Employee = Depends(require("xaridlar.edit")),
                      db: Session = Depends(get_db)):
    """Dialog kerakmi va QAYSI provayder nomlanishi kerak. Skan qiluvchi xodim
    o'qiy olishi SHART — aks holda u rozilik oynasini ko'rsata olmasdi."""
    from app.services import ai_consent as _AC
    return _AC.status(db, emp.company_id)


@router.post("/receiving/ai-consent")
def ai_consent_grant(data: ConsentIn,
                     emp: Employee = Depends(require("sozlamalar.edit")),
                     db: Session = Depends(get_db)):
    """Rozilik berish — TASDIQLOVCHI AMAL. Ruxsat `sozlamalar.edit`: kompaniya
    ma'lumotini tashqi qayta ishlovchiga berish do'kon darajasidagi qaror
    (`PUT /settings` bilan AYNI ruxsat)."""
    from app.services import ai_consent as _AC
    qiymat = _AC.grant(db, emp, data.disclosure_version,
                       expect_revision=data.revision,
                       expect_provider=data.provider,
                       expect_disclosure_id=data.disclosure_id)
    db.commit()
    return {"ok": True, **_AC.status(db, emp.company_id), "granted_at": qiymat["granted_at"]}


@router.delete("/receiving/ai-consent")
def ai_consent_revoke(emp: Employee = Depends(require("sozlamalar.edit")),
                      db: Session = Depends(get_db)):
    """Rozilikni qaytarib olish. Shundan keyin skan FAIL-CLOSED bo'ladi va
    qo'lda kirim yo'li ishlashda davom etadi."""
    from app.services import ai_consent as _AC
    _AC.revoke(db, emp)
    db.commit()
    return {"ok": True, **_AC.status(db, emp.company_id)}


@router.post("/receiving/scan")
def scan(data: ScanIn, emp: Employee = Depends(require("xaridlar.edit")), db: Session = Depends(get_db)):
    """Rasmni AI bilan o'qib, mavjud mahsulotlar bilan moslashtiradi. OMBORNI O'ZGARTIRMAYDI.
    AI-vision xarajat qiladi va xaridlar oqimining bir qismi — 'xaridlar.edit' ruxsati kerak."""
    #  ⚠️  IKKI DARVOZA — TASHQI UZATISHDAN OLDIN (CH-16).
    #
    #  1) ROZILIK. Fail-closed: do'kon AYNAN hozirgi provayderga rozilik
    #     bermagan bo'lsa 403 + `AI_CONSENT_REQUIRED` va rasm UMUMAN chiqmaydi.
    #     Demo rejimda (kalit sozlanmagan) tashqi uzatish yo'q, shu bois darvoza
    #     o'tkazib yuboriladi. Mijozdan kelgan bayroqqa ISHONILMAYDI — dalil
    #     serverdagi `Setting(key="ai_consent")` yozuvi.
    #
    #  2) RASM DARVOZASI. Tur FAQAT BAYTLARDAN aniqlanadi: mobil e'lon qilingan
    #     `media_type` ni picker'dan o'zgartirmasdan uzatadi (`image_capture.dart:35`)
    #     va desktop brauzerning `f.type` ini yuboradi (`Purchases.tsx:1233`) —
    #     ikkisi ham baytlar bilan ZID bo'lishi mumkin. Shu yerda EXIF/GPS ham
    #     olib tashlanadi: galereyadan tanlangan rasm koordinatani O'ZI bilan
    #     olib keladi va u tashqi provayderga ketishi KERAK EMAS.
    #
    #  Tartib: rozilik BIRINCHI — yuborishga ruxsat bo'lmagan rasm ustida ish
    #  qilmaymiz. Tozalash esa demo rejimda HAM bajariladi (PDF/axlat rad etilsin).
    from app.services import ai_consent as _AC
    _AC.require_consent(db, emp.company_id)
    #  ⚠️  TARTIB. Rozilik BIRINCHI (yuqorida), keyin MIJOZ KUTGAN talab. Ikkisi
    #      ham rasm BAYTLARIGA tegishdan OLDIN: ruxsat yo'q rasm ustida ish
    #      qilmaymiz. Reviziya yuborilmasa (eski mijoz) tekshiruv o'tkazib
    #      yuboriladi — rozilik darvozasi esa HAMMA UCHUN ishlaydi.
    if data.revision is not None:
        _provider, _ = _AC.active_provider()
        if data.revision != _AC.requirement_revision(_provider):
            raise HTTPException(
                409, "AI shartlari o'zgardi — rasmni qayta tanlab, yangi "
                     "shartlarni ko'rib chiqing",
                headers=EC.headers(EC.AI_REQUIREMENT_CHANGED))

    import base64 as _b64
    from app.services import image_guard as _IG
    try:
        _xom = _b64.b64decode(data.image_b64, validate=True)
    except Exception:   # noqa: BLE001 — binascii.Error va boshqalar
        raise HTTPException(400, "Rasm ma'lumoti buzuq — qayta suratga oling",
                            headers=EC.headers(EC.AI_IMAGE_REJECTED)) from None
    try:
        _toza, _tur = _IG.sanitize(_xom, declared=data.media_type)
    except _IG.ImageRejected as e:
        #  `ImageRejected` — NOMLANGAN DOMEN istisnosi: matni shu repo kodida
        #  ATAYLAB operator uchun yozilgan va mijoz lug'atiga tushadi, ichki
        #  istisnodan kelmaydi. `CorrectionError`/`ResolutionError` bilan AYNI
        #  naqsh (`tests/test_lot_error_texts.py` `DOMAIN`).
        raise HTTPException(400, str(e),
                            headers=EC.headers(EC.AI_IMAGE_REJECTED)) from None
    _toza_b64 = _b64.b64encode(_toza).decode("ascii")

    units = {u.id: u.code for u in db.query(Unit).all()}
    prods = (
        db.query(Product)
        .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None))
        .all()
    )
    plist = [{"id": str(p.id), "name": p.name, "unit_code": units.get(p.unit_id, "dona"),
              "base_buy_price": float(p.base_buy_price)} for p in prods]
    names = [p["name"] for p in plist]
    #  TOZALANGAN baytlar va HAQIQIY tur uzatiladi — asl `data.image_b64` emas.
    rows, source = read_invoice(_toza_b64, _tur, names)
    if source.startswith("error:"):
        # ⚠️  Yuqori oqim (AI provayderi) matni operatorga UZATILMAYDI: unda kutubxona
        #     istisnosi, tarmoq tafsiloti, hatto stek bo'lagi bo'lishi mumkin. Tafsilot
        #     jurnalda; mijozga barqaror kod + o'zi bajara oladigan jumla (Phase 5G.1).
        log.warning("receiving/scan: AI o'qish xatosi (company=%s): %s", emp.company_id, source[6:])
        raise HTTPException(502, "Nakladnoy rasmini o'qib bo'lmadi — qayta urinib ko'ring yoki "
                                 "qatorlarni qo'lda kiriting.",
                            headers=EC.headers(EC.AI_SCAN_FAILED))
    items = match_products(rows, plist)
    return {"source": source, "items": items, "ai_raw": rows}


class CommitItem(BaseModel):
    product_id: uuid.UUID | None = None       # mavjud mahsulot
    new_name: str | None = Field(default=None, max_length=200)  # yoki yangi mahsulot (bazada yo'q)
    new_sell_price: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    new_category_id: uuid.UUID | None = None  # yangi mahsulot uchun kategoriya (ixtiyoriy)
    new_barcode: str | None = Field(default=None, max_length=64)  # skanerlangan shtrix-kod (bazada yo'q bo'lsa mahsulotga biriktiriladi)
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    unit_cost: float = Field(default=0, ge=0, le=1e9, allow_inf_nan=False)
    ai_name: str | None = None
    unit: str | None = None
    # Yangi mahsulot uchun qo'shimcha (mobil kirim — Manager formasi bilan paritet):
    new_plu: str | None = Field(default=None, max_length=10)       # tarozi PLU (kg mahsulot)
    new_is_weighted: bool | None = None                             # kg/tarozi mahsulotimi
    new_min_qty: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)  # min qoldiq
    # ── PARTIYA KIRIMI (Phase 1) ──────────────────────────────────────────
    #  Kuzatuvsiz mahsulot uchun BERILMAYDI va bugungi oqim o'zgarmaydi.
    #  Kuzatuvli mahsulot uchun MAJBURIY va yig'indi `qty` ga ANIQ teng
    #  bo'lishi shart (NUMERIC(14,3), float solishtirish YO'Q).
    #
    #  ⚠️  CHEGARA (50) TASODIFIY EMAS. Bitta jismoniy qabul qatorida ellikdan
    #      ortiq alohida kogorta bo'lmaydi; chegarasiz ro'yxat esa bitta
    #      so'rovda 1000 qator × cheksiz partiya bilan bazaga yozuv yog'dirardi
    #      (har partiya — alohida INSERT + invariant tekshiruvi). UI ham AYNI
    #      chegarani qo'yadi, shu bois operator buni faqat qo'lda so'rov
    #      yuborganda ko'radi.
    lots: list["LotItem"] | None = Field(default=None, max_length=50)


class LotItem(BaseModel):
    """Bitta jismoniy partiya. Bir qator bir NECHTA partiya berishi mumkin."""
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    expiry_date: date | None = None
    batch_number: str | None = Field(default=None, max_length=64)
    unit_cost: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    external_lot_id: str | None = Field(default=None, max_length=120)


class CommitIn(BaseModel):
    items: list[CommitItem] = Field(max_length=1000)
    image_b64: str | None = Field(default=None, max_length=15_000_000)
    source: str = Field(default="ai", max_length=20)
    ai_raw: list = Field(default=[], max_length=2000)
    supplier_id: uuid.UUID | None = None
    payment: Literal["cash", "credit"] = "cash"   # qarzga olindi -> beruvchi balansi oshadi
    client_uuid: uuid.UUID | None = None
    # §1 EXPLICIT CUSTODY: smenasiz naqd amali uchun fizik hisob (TILL yoki SAFE) AYNAN
    # ko'rsatiladi. Ochiq smena bo'lsa server shift.till_id ni ishlatadi va bu maydon unga
    # TENG bo'lishi kerak (override QILIB BO'LMAYDI). Legacy/pre-T0 uchun nullable.
    cash_account_id: uuid.UUID | None = None


@router.post("/receiving/commit")
def commit(data: CommitIn, emp: Employee = Depends(require("xaridlar.edit")), db: Session = Depends(get_db)):
    # doc_no (KIR-...) count()+1 asosida beriladi — boshqa ta'minotchili ikki kirim/xarid AYNI PAYTDA
    # bir xil raqam olib UNIQUE(company_id, doc_no) buzardi (500). create_purchase kabi retry o'raymiz:
    # to'qnashuvda tranzaksiya bekor bo'lib, qayta urinishda count() yangi raqam beradi.
    # (client_uuid dedup ichki funksiyada "duplicate" qaytaradi — IntegrityError chiqarmaydi, retrysiz.)
    from sqlalchemy.exc import IntegrityError as _IEwrap
    from app.services.cash.errors import CashPostingError as _CPE
    _last: Exception | None = None
    for _try in range(3):
        try:
            return _commit_once(data, emp, db)
        except _IEwrap as e:
            db.rollback()
            _last = e
        except _CPE:
            # KONKURRENT DUBLIKAT IDEMPOTENTLIGI: naqd qabul endi OUT·PURCHASE_OUT post qiladi va
            # sufficiency tekshiradi. Bir xil client_uuid'li ikki konkurrent qabulда g'olib oqim
            # kassani kamaytirib commit qilса, YUTQAZGAN dublikat OUT-sufficiency'да CashPostingError
            # (INSUFFICIENT_CASH) olishi mumkin — commit-time client_uuid guard'gача yetmай. Bu XATO
            # EMAS: operatsiya g'olib orqali MUVAFFAQ bo'lган. client_uuid bilan Receiving mavjud bo'lса
            # idempotent dublikatni qaytaramiz; aks holда — HAQIQIY domain-error (yetarsiz naqd/arxiv
            # hisob/valyuta) -> qayta ko'taramiz.
            db.rollback()
            if data.client_uuid:
                ex = db.query(Receiving).filter(
                    Receiving.client_uuid == data.client_uuid,
                    Receiving.company_id == emp.company_id).first()
                if ex:
                    return {"ok": True, "receiving_id": str(ex.id), "duplicate": True}
            raise
    raise HTTPException(409, "Qabul hujjati band — qayta urinib ko'ring") from _last


def _make_lots_for_line(db, emp, branch, prod, qty, cost, raw_lots, now, *,
                        doc_key, line_index, supplier_id):
    """Bitta kirim qatori uchun partiyalarni tekshiradi va yaratadi.

    ⚠️  XATO TARJIMASI MAJBURIY. `LotPayloadError` — `ValueError`, lekin bu yo'lda
        `ValueError` ni ushlaydigan qatlam YO'Q: tarjimasiz u operatorga 500
        «server buzildi» bo'lib ko'rinardi, holbuki bu ANIQ va kutilgan rad
        etish (ma'lumot noto'g'ri -> 400). Vaqt zonasi tasdiqlanmagani esa
        holat ziddiyati -> 409.
    """
    try:
        lots = _LR.validate_line(
            db, emp.company_id, branch.id, prod, qty,
            [_LR.LotIn(qty=Decimal(str(x.qty)), expiry_date=x.expiry_date,
                       batch_number=x.batch_number,
                       unit_cost=(Decimal(str(x.unit_cost))
                                  if x.unit_cost is not None else None),
                       external_lot_id=x.external_lot_id)
             for x in (raw_lots or [])], now)
        return _LR.create_lots(
            db, company_id=emp.company_id, branch_id=branch.id, product=prod,
            lots=lots, doc_key=doc_key, line_index=line_index,
            source_type=_LR.SOURCE_RECEIVING, default_cost=cost, now=now,
            receiving_id=None,   # `rec` sikldan KEYIN yaratiladi -> pastda to'ldiriladi
            supplier_id=supplier_id)
    except _LR.LotPayloadError as e:
        # Phase 5G: barqaror kod `X-Error-Code` da (matn va 400 O'ZGARMAYDI).
        raise HTTPException(400, str(e),
                            headers=(EC.headers(e.code) if e.code else None)) from e
    except LP.TimezoneNotConfigured as e:
        raise HTTPException(409, str(e), headers=EC.headers(EC.LOT_TZ_NOT_CONFIRMED)) from e


def _commit_once(data: CommitIn, emp: Employee, db: Session, *,
                 at: datetime | None = None):
    # ⚠️  TAKROR = BIRINCHI HUJJAT, TAHRIR EMAS. `client_uuid` allaqachon yozilgan
    #     bo'lsa qabul QAYTA ISHLANMAYDI: so'rovdagi miqdor/partiya/narx boshqa
    #     bo'lsa ham, javob AYNI birinchi hujjatga ishora qiladi
    #     (`duplicate: true`) va o'zgarishlar QO'LLANMAYDI. Bu ataylab: offline
    #     retry ikki marta stok/qarz yozmasligi kerak, tahrir esa alohida amal
    #     (`PATCH /purchases/{id}`). UI shu bois hujjat qoralamasi uchun BITTA
    #     barqaror `client_uuid` yuritadi va uni faqat MUVAFFAQIYATDAN keyin
    #     yangilaydi; `duplicate: true` javobi operatorga KO'RSATILADI.
    #  ⚠️  INDEKS KAFOLATI — YOZUVDAN VA QULFDAN OLDIN (fail-closed).
    #      Quyidagi dedup SELECT-keyin-INSERT: u KETMA-KET takrorni ushlaydi, lekin
    #      KONKURRENT takrorni faqat noyob indeks to'sadi. Indeks yo'q yoki shakli
    #      boshqa bo'lsa tayyorlik qizil bo'ladi, lekin u YOZUVNI TO'SMAYDI
    #      (`/health/ready` — monitoring signali). Shu bois darvoza SHU YERDA.
    #      Gard qulfdan OLDIN: yangi qulf tartibi YARATILMAYDI va rad etish
    #      birorta qator qulflanmasdan sodir bo'ladi.
    from app.core.index_guard import require_index
    require_index(db, "ux_receivings_client_uuid", "receivings", operation="receiving")
    if data.client_uuid:
        ex = db.query(Receiving).filter(
            Receiving.client_uuid == data.client_uuid, Receiving.company_id == emp.company_id
        ).first()
        if ex:
            return {"ok": True, "receiving_id": str(ex.id), "duplicate": True}
    if not data.items:
        raise HTTPException(400, "Kamida bitta mahsulot kerak")

    # Kirim xodim filialiga (ko'p-filial: sotuv bilan izchil). ⚠️  YAGONA YORDAMCHI:
    # `GET /cash/custody-preview?operation=receiving_payment` AYNI filialni ko'rsatadi.
    from app.services.cash import custody_preview as _CP
    branch = _CP.receiving_branch(db, emp)
    if not branch:
        raise HTTPException(400, "Filial topilmadi")

    # Yetkazib beruvchi — berilmasa "Qabul (mobil)" avto
    # QATOR QULFI: qarz-qabulda sup.balance RMW (quyida) bir vaqtdagi to'lov/kirim bilan yo'qolmasin
    # va SupplierLedger.balance_after haqiqiy balansga teng bo'lsin (create_purchase/edit_purchase/
    # pay_supplier bilan izchil — ilgari faqat receiving qulflamasdi).
    sup = None
    if data.supplier_id:
        sup = db.query(Supplier).filter(Supplier.id == data.supplier_id).with_for_update().first()
        # O'chirилган ta'minотchига qarз-qabul biriktирмаймиз — aks holда qarз yashirин qolарди
        # (create_purchase/pay_supplier ham deleted_at ni tekshiradi).
        if not sup or sup.company_id != emp.company_id or sup.deleted_at is not None:
            raise HTTPException(404, "Yetkazib beruvchi topilmadi")
    if sup is None:
        sup = db.query(Supplier).filter(
            Supplier.company_id == emp.company_id, Supplier.name == _DEFAULT_SUPPLIER,
            Supplier.deleted_at.is_(None)).with_for_update().first()
        if sup is None:
            sup = Supplier(company_id=emp.company_id, name=_DEFAULT_SUPPLIER)
            db.add(sup)
            db.flush()

    all_units = db.query(Unit).all()
    units = {u.id: u.code for u in all_units}
    unit_by_code = {u.code: u.id for u in all_units}   # tanlangan birlik (kg/litr/...) uchun
    default_unit_id = all_units[0].id if all_units else None
    #  Tarixiy payt FAQAT `resolve_at` orqali — kontekstsiz `at` RAD etiladi.
    from app.services import historical as _H
    now = _H.resolve_at(at, emp.company_id)
    # ⚠️  BIRLIK DARVOZASI — yig'indidan OLDIN, XOM qatorlar bo'yicha.
    #     Bu yo'lning o'ziga xosligi: qator MAVJUD mahsulotga ham, YANGI mahsulotga
    #     ham tegishli bo'lishi mumkin (`product_id=None`). Partiya qatorlari
    #     (`lots[].qty`) ham XOM holda tekshiriladi — ular yig'indisi `qty` ga teng
    #     bo'lishi quyida talab qilinadi, ya'ni kasr partiyalar butun jamiga
    #     yuvilishi mumkin edi.
    #
    # ⚠️  YANGI MAHSULOT BIRLIGI — KLIENT YORLIG'IDAN EMAS, YECHILGAN `unit_id` DAN.
    #     Ikki FAIL-OPEN teshigi aynan shu yerda bo'lgan: darvoza `i.unit` xom
    #     satrini (katta-kichik harfga SEZGIR, zaxirasiz) o'lchardi, mahsulot esa
    #     quyida `(i.unit or "").strip().lower() or default_unit_id` bilan
    #     yaratilardi. Natijada:
    #       · `"unit": "DONA"`  -> darvozada kod topilmaydi -> tekshirilmaydi ->
    #         mahsulot `dona` bo'lib yaratiladi (kasr `dona` TUG'ILADI);
    #       · `unit` BERILMAGAN (`str | None = None`, mobil kirim formasining
    #         oddiy holati) yoki noma'lum kod -> AYNI natija, zaxira `dona`.
    #     Shu bois darvoza AYNAN quyidagi yechim ifodasini ishlatadi — ikki joy
    #     bitta manbadan o'qiydi va ajralib ketolmaydi.
    from app.services import unit_gate as _UG
    _ug_fmap = _UG.fraction_map(db, [i.product_id for i in data.items if i.product_id])
    _ug_umap = _UG.unit_fraction_map(db, unit_by_code.values())

    def _ug_new_unit(i):
        """Yangi mahsulotga beriladigan birlik — yaratish joyi bilan AYNI (satr 343)."""
        return unit_by_code.get((i.unit or "").strip().lower()) or default_unit_id

    for _i in data.items:
        _allow = (_ug_fmap.get(_i.product_id) if _i.product_id
                  else _ug_umap.get(_ug_new_unit(_i)))
        _UG.validate_with_map({_i.product_id: _allow}, [(_i.product_id, _i.qty)],
                              db=db, label="kirim")
        for _lot in (_i.lots or []):
            _UG.validate_with_map({_i.product_id: _allow}, [(_i.product_id, _lot.qty)],
                                  db=db, label="kirim partiyasi")
    total = sum(Decimal(str(i.qty)) * Decimal(str(i.unit_cost)) for i in data.items)
    from app.core.validate import guard_amount
    guard_amount(total, "Hujjat jami summasi")  # Numeric(14,2) yig'indi overflow -> do'stona 400
    is_credit = data.payment == "credit"
    from app.api.v1.reports import _biz_date

    pur = Purchase(
        doc_no=_DS.next_no(db, emp.company_id, _DS.PURCHASE)[1],   # atomik hisoblagich
        #  ⚠️  `purchases.created_at` NI ANIQ YOZISH SHART. U `TimestampMixin`
        #      dan `server_default=func.now()` oladi, ya'ni tarixiy xarid DB
        #      soati bilan BUGUN muhrlanardi. Bu ustun YUK KO'TARADI:
        #      · `purchases.py` FIFO hisob-kitob tartibida teng `purchase_date`
        #        ichidagi AJRATUVCHI kalit (`order_by(purchase_date, created_at, id)`);
        #      · `cash/shadow_compare.py` da smena oynasi atributsiyasi shu
        #        ustunga tayanadi.
        #  ⚠️  NORMAL yo'lda ANIQ `None` -> SQLAlchemy ustunni INSERT'ga
        #      QO'SHMAYDI (o'lchandi, 2.0.52) va sanani hamon DB soati qo'yadi.
        created_at=(now if at is not None else None),
        currency=_company_currency(db, emp.company_id),   # VALYUTA SURATI (services/currency.py)
        company_id=emp.company_id, branch_id=branch.id,
        #  ⚠️  `_biz_date` IKKINCHI vaqt manbai — `at` uzatilmasa tarixiy
        #      qabul hujjati BUGUNGI sana bilan muhrlanardi.
        supplier_id=sup.id, employee_id=emp.id,
        purchase_date=_biz_date(db, emp.company_id, at=at),
        status=PurchaseStatus.debt if is_credit else PurchaseStatus.received,
        subtotal=total, total=total, paid_amount=Decimal("0") if is_credit else total,
    )
    db.add(pur)
    db.flush()

    results = []
    final_items = []
    total_qty = Decimal("0")
    # QATOR QULFI (deadlock oldini olish): tegiladigan mavjud mahsulotlar Inventory qatorlarini
    # DASTAVVAL bir xil GLOBAL tartibda (product_id) qulflaymiz — boshqa BARCHA yozuvchilar (sotuv/
    # qaytarish/xarid/writeoff/transfer) shu tartibda qulflaydi, aks holda AB-BA deadlock (500).
    # MUHIM: new_name item quyidagi DEDUP (lower(name)) orqali MAVJUD mahsulotga bog'lanishi mumkin —
    # uni ham oldindan qulflaymiz, aks holda loop ichida item-tartibda qulflab deadlock bo'lardi.
    # Haqiqatan yangi (dedup topmaydigan) nomlar tranzaksiya-ichi yaratiladi -> deadlock bermaydi.
    _lock_pids = {i.product_id for i in data.items if i.product_id}
    _new_names = [i.new_name.strip() for i in data.items
                  if not i.product_id and i.new_name and i.new_name.strip()]
    if _new_names:
        _ex = db.query(Product.id).filter(
            Product.company_id == emp.company_id, Product.deleted_at.is_(None),
            func.lower(Product.name).in_([n.lower() for n in _new_names])).all()
        _lock_pids |= {r[0] for r in _ex}
    for _pid in sorted(_lock_pids, key=str):
        db.query(Inventory).filter(
            Inventory.product_id == _pid, Inventory.branch_id == branch.id).with_for_update().first()
    # Partiya kaliti HUJJATDAN kelib chiqadi: mijoz `client_uuid` i retry'da
    # AYNI qoladi, shu bois qayta yuborilgan qabul AYNI partiyaga tushadi.
    _doc_key = str(data.client_uuid or pur.id)
    _line_no = -1
    # ⚠️  NOMI ANIQ: bu TEGILGAN mahsulotlar, faqat kuzatuvlilar EMAS. Invariant
    #     tekshiruvi kuzatuvlilarni O'ZI filtrlaydi (`stock_invariant.check`), va
    #     ro'yxatni tor qilish XAVFLI bo'lardi: qator qulflangandan keyin boshqa
    #     tranzaksiya kuzatuvni yoqib ulgursa, tor ro'yxat uni O'TKAZIB yuborardi.
    _touched_ids: list = []
    _made_lots: list = []

    for i in data.items:
        _is_new_prod = False   # shu itemda HAQIQATAN yangi mahsulot yaratildimi (mavjud/dedup emas)
        # Yangi mahsulot uchun kategoriya (berilsa — shu kompaniyaniki bo'lishi shart)
        cat_id = None
        if i.new_category_id:
            from app.models.catalog import Category as _Cat
            _c = db.get(_Cat, i.new_category_id)
            if _c and _c.company_id == emp.company_id and _c.deleted_at is None:
                cat_id = _c.id
        if i.product_id:
            prod = db.get(Product, i.product_id)
            if not prod or prod.company_id != emp.company_id or prod.deleted_at is not None:
                raise HTTPException(400, f"Mahsulot topilmadi: {i.product_id}")
        elif i.new_name and i.new_name.strip():
            nm = i.new_name.strip()
            # Dedup: shu nomli faol mahsulot bo'lsa — yangisini yaratmay, o'shanga kirim qilamiz
            existing = (
                db.query(Product)
                .filter(Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                        func.lower(Product.name) == nm.lower())
                .first()
            )
            if existing is not None:
                prod = existing
            else:
                # Bazada yo'q — yangi mahsulot (kelish narxi = unit_cost, sotish = new_sell yoki +20%)
                cost0 = Decimal(str(i.unit_cost))
                sell0 = Decimal(str(i.new_sell_price)) if i.new_sell_price is not None else (cost0 * Decimal("1.2"))
                pseq = db.query(Product).filter(Product.company_id == emp.company_id).count()
                # Birlik: kirimда tanlangani (i.unit — 'dona/kg/litr/upak') — ilgari e'tiborsiz edi
                _uid = unit_by_code.get((i.unit or "").strip().lower()) or default_unit_id
                # Tarozi (kg) mahsuloti: PLU noyob bo'lishi shart (kompaniya doirasida)
                _weighted = bool(i.new_is_weighted) or (i.unit or "").strip().lower() == "kg"
                from app.api.v1.products import _norm_plu as _nplu
                _plu = _nplu(i.new_plu)   # QA PC-013: kanonik shakl (yetakchi nolsiz), 1-5 raqam
                if _plu is not None:
                    _clash = db.query(Product).filter(
                        Product.company_id == emp.company_id, Product.deleted_at.is_(None),
                        Product.plu_code == _plu).first()
                    if _clash:
                        raise HTTPException(409, f"PLU {_plu} band ({_clash.name}) — boshqa PLU kiriting: {nm}")
                prod = Product(company_id=emp.company_id, name=nm, category_id=cat_id,
                               article_code=f"R-{1000 + pseq + 1}", sku=str(20000 + pseq + 1),
                               unit_id=_uid, base_buy_price=cost0, base_sell_price=sell0,
                               tax_rate=Decimal("12"),
                               is_weighted=_weighted, plu_code=_plu)
                db.add(prod)
                db.flush()
                _is_new_prod = True
        else:
            raise HTTPException(400, "Mahsulot yoki yangi nom kerak")
        # Narxlar yangilanishi: kelish narxi (unit_cost>0) va sotish narxi (new_sell_price berilsa)
        # bazadagidan farq qilsa — mahsulot kartochkasida ham yangilanadi (foydalanuvchi so'rovi).
        if i.unit_cost and Decimal(str(i.unit_cost)) != Decimal(str(prod.base_buy_price)):
            prod.base_buy_price = Decimal(str(i.unit_cost))
        if i.new_sell_price is not None and Decimal(str(i.new_sell_price)) > 0 \
                and Decimal(str(i.new_sell_price)) != Decimal(str(prod.base_sell_price)):
            prod.base_sell_price = Decimal(str(i.new_sell_price))
        if cat_id and prod.category_id is None:
            prod.category_id = cat_id
        # Kirim kelgan mahsulot arxivda bo'lsa — avtomatik faolga qaytadi (qoldiq endi bor)
        if not prod.is_active:
            prod.is_active = True
        # Skanerlangan shtrix-kod bazada yo'q bo'lsa — shu mahsulotga biriktiramiz
        # (yangi mahsulotga ham, mavjudga ham; band bo'lsa jimgina o'tkazamiz)
        if i.new_barcode:
            from app.api.v1.products import _norm_barcode as _nbc
            bc = _nbc(i.new_barcode)  # 6-14 raqam (butun tizimда bir xil); noto'g'ri -> None
            # QA PC-003: bandlik endi KOMPANIYA doirasida tekshiriladi (global emas)
            if bc and not db.query(ProductBarcode).filter(
                    ProductBarcode.company_id == emp.company_id, ProductBarcode.barcode == bc).first():
                db.add(ProductBarcode(product_id=prod.id, company_id=emp.company_id, barcode=bc, is_primary=False))
        _line_no += 1
        qty, cost = Decimal(str(i.qty)), Decimal(str(i.unit_cost))
        line_total = qty * cost
        # Numeric(14,2) sig'imidan oshsa Postgres "numeric field overflow" bilan qulaydi
        # (qty·cost 1e9·1e9=1e18 gacha bo'lishi mumkin) — do'st xabar bilan to'xtatamiz.
        if line_total > Decimal("999999999999.99"):
            raise HTTPException(400, f"'{prod.name}' qatori summasi juda katta (miqdor×narx {line_total:g}) — miqdor yoki narxni tekshiring")
        total_qty += qty
        db.add(PurchaseItem(purchase_id=pur.id, product_id=prod.id, qty=qty,
                            unit_cost=cost, line_total=line_total))
        # QATOR QULFI: qoldiq RMW bir vaqtдаги sotuv/kirim bilan STALE o'qib yo'qolмасин
        # (balance_after ham to'g'ri qatор qiymatини aks ettirsin).
        inv = db.query(Inventory).filter(
            Inventory.product_id == prod.id, Inventory.branch_id == branch.id).with_for_update().first()
        old_qty = float(inv.qty) if inv else 0.0
        if inv is None:
            inv = Inventory(product_id=prod.id, branch_id=branch.id, qty=Decimal("0"), updated_at=now)
            db.add(inv)
            db.flush()
        # Min qoldiq — FAQAT haqiqatan yangi yaratilgan mahsulotга (mavjud yoki dedup-mahsulotning
        # menejer sozlagan kam-qoldiq chegarasini kirim jarayonida jimgina almashtirmaslik uchun).
        if i.new_min_qty is not None and _is_new_prod:
            inv.min_qty = Decimal(str(i.new_min_qty))
        inv.qty = Decimal(str(inv.qty)) + qty
        inv.updated_at = now
        if inv.qty > Decimal(str(inv.min_qty or 0)):
            inv.low_alerted = False  # min ustiga chiqdi — keyingi tushishda yana ogohlantiriladi
        # ── PARTIYA (kuzatuvli mahsulot uchun) ────────────────────────────
        #  Bitta AGREGAT harakat qoladi (pastda), partiya tafsiloti esa
        #  `stock_batches` da.
        #
        #  ⚠️  `StockMovement.batch_id` YOZILMAYDI. Vasvasa bor edi: bitta
        #      partiyali qatorda unga ishora qilish "bepul foyda" ko'rinadi.
        #      Lekin u FAQAT shunday qatorlarda to'lardi va ko'p partiyali
        #      qatorda NULL qolardi — ya'ni "NULL = partiyasi yo'q" degan
        #      YOLG'ON o'qish tug'ilardi. Bundan tashqari uni hech kim
        #      o'qimaydi. Harakat -> partiya yo'nalishi Phase 2 da
        #      `sale_item_lot_allocations` orqali ANIQ modellanadi.
        if _LR.is_tracked(prod):
            _made = _make_lots_for_line(
                db, emp, branch, prod, qty, cost, i.lots, now,
                doc_key=_doc_key, line_index=_line_no,
                supplier_id=getattr(pur, "supplier_id", None))
            _made_lots.extend(_made)
        elif i.lots:
            raise HTTPException(400, f"'{prod.name}' partiya bo'yicha kuzatilmaydi — "
                                     f"`lots` berib bo'lmaydi",
                                headers=EC.headers(EC.LOT_LINES_FORBIDDEN))

        db.add(StockMovement(product_id=prod.id, branch_id=branch.id, type=MovementType.purchase_in,
                            qty=qty, unit_cost=cost, balance_after=inv.qty, ref_type="receiving",
                            ref_id=pur.id, employee_id=emp.id, created_at=now))
        _touched_ids.append(prod.id)
        _uc = units.get(prod.unit_id, "dona")
        results.append({"product": prod.name, "old_qty": old_qty, "added": float(qty),
                        "new_qty": float(inv.qty), "unit": _uc})
        #  ⚠️  `ai_name` ATAYLAB YOZILMAYDI (CH-15B Faza A, ega qarori). U AI ning
        #      nakladnoy qatorini SO'ZMA-SO'Z o'qishi edi (`services/receiving_ai.py:154`
        #      -> `CommitItem.ai_name`) va `final_items` JSONB ichida muddatsiz qolardi —
        #      ya'ni `image_b64`/`ai_raw` olib tashlangandan keyin ham xom AI matni
        #      saqlanib qolardi. Bu yerda FAQAT operator tasdiqlagan maydonlar yoziladi:
        #      `name` katalogdagi mahsulot nomi (`prod.name`), `qty`/`unit_cost` esa
        #      operator ko'rib chiqqan qiymatlar.
        #      `CommitItem.ai_name` (`:78`) E'LON QILINGAN holda QOLADI — eski mijozlar
        #      uni yuborishda davom etadi va muzlatilgan DTO ro'yxati buzilmaydi
        #      (`tests/test_historical_dto_freeze.py:56`). Server uni qabul qiladi va
        #      SAQLAMAYDI. `api/v1/purchases.py:970` allaqachon `None` yozadi.
        #  ⚠️  BIRLIK — MAHSULOTNING O'ZIDAN (`_uc`), MIJOZ YORLIG'IDAN EMAS (D5-b).
        #      Ilgari bu yerda `i.unit or _uc` edi: mijozning XOM satri afzal ko'rilardi.
        #      `CommitItem.unit` (`:79`) — bu DTO'dagi YAGONA saqlanadigan satr maydoni
        #      bo'lib, `Field()` chegarasi UMUMAN YO'Q (qardoshlari: `:72` 200, `:75` 64,
        #      `:81` 10), ya'ni istalgan uzunlikdagi matn `final_items` JSONB ichiga
        #      muddatsiz tushardi va `GET /receiving/{id}` (`:669`) uni qaytarardi.
        #      Qiymat manbasi — AI: `services/receiving_ai.py:156` `row.get("unit")`
        #      ni `units` jadvaliga SOLISHTIRMASDAN uzatadi (prompt `:17` faqat
        #      "dona|kg|litr" so'raydi, javob tekshirilmaydi); Desktop esa
        #      `Purchases.tsx:1190` da MAVJUD mahsulot uchun ham SHARTSIZ yuboradi.
        #
        #      `_uc` (`:470`) = `units[prod.unit_id]` — `products.unit_id` NOT NULL
        #      (`db/schema.sql:212`), shu bois u HAR DOIM yechiladi. Uchta shoxda ham
        #      to'g'ri: mavjud mahsulot (`:355`), YANGI mahsulot (`:375` birlikni
        #      `unit_id` ga ALLAQACHON yechadi) va NOM bo'yicha dedup (`:367` —
        #      mijoz yorlig'i mahsulotga umuman ta'sir qilmaydigan shox).
        #
        #  ⚠️  BU MODULNING O'Z QARORI, YANGI QOIDA EMAS. `services/unit_gate.py:110-118`
        #      ilgari mavjud `code_fraction_map` ni ATAYLAB olib tashlagan — u birlikni
        #      KLIENT satri bo'yicha yechardi va ikki fail-open teshigi ochardi
        #      (katta-kichik harf, noma'lum kod); o'sha modulning xulosasi —
        #      «Mijozga ishonilmaydi». Yuqoridagi `:472` (javobdagi `results[].unit`)
        #      ALLAQACHON yalang'och `_uc` ni ishlatadi va `purchases.py:971` ham
        #      `umap.get(p.unit_id, "dona")` yozadi — ya'ni AYNI so'rovda javob
        #      «kg» deb, saqlangan hujjat esa xom satrni deb turardi. Endi ikkisi MOS.
        #
        #      UZUNLIK CHEKLOVI QO'SHILMADI (ega qarori): `max_length` o'rnatilgan
        #      mijozlarga normalizatsiyadan OLDIN 422 berardi. Qiymat qabul qilinadi
        #      (200) va shunchaki SAQLANMAYDI — `ai_name` bilan AYNI naqsh.
        final_items.append({"product_id": str(prod.id), "name": prod.name, "qty": float(qty),
                            "unit_cost": float(cost), "unit": _uc})

    # Qarzga olindi — yetkazib beruvchi balansi oshadi (biz qarzmiz)
    if is_credit:
        sup.balance = Decimal(str(sup.balance or 0)) + total
        db.add(SupplierLedger(supplier_id=sup.id, type=CreditTxnType.charge, amount=total,
                              balance_after=sup.balance, ref_type="receiving", ref_id=pur.id, created_at=now))
    else:
        # Phase 2b — NAQD qabul (received) -> OUT·PURCHASE_OUT: create_purchase bilan IZCHIL; §07
        # off-ledger teshigini receiving tomonда HAM yopadi (ilgari receiving naqd xaridi kassani
        # jimgina kamaytirardi, ledgerда OUT yo'q edi -> keyingi qaytarish ham mumkin emasди).
        # source_type=PURCHASE, source_id=pur.id, leg_index=0 (asl xarid — PURCHASE_RETURN'дан farqli).
        # Summa = PERSISTED total (=paid_amount). Guarded/commit=False (SQLite/xaritalanmagan filialда
        # no-op) -> Purchase+ombor+ledger BIR tranzaksiyada (§05). Yetarsiz naqd/arxiv hisob/valyuta
        # -> CashPostingError -> butun qabul ROLLBACK.
        from app.services.cash import retrofit as _cr
        # §2 PURCHASE CUSTODY: post-T0 naqd xarid AYNAN fizik custody hisobini talab qiladi.
        # Smena bor -> manba = shift.till_id. Smenasiz bo'lsa -> HOZIRCHA FAIL-CLOSED: filial
        # bo'yicha TAXMIN QILINMAYDI (ilgari branch-guess qilinardi yoki JIMGINA ledger'siz
        # o'tib ketardi). Explicit cash_account_id so'rov shakli — keyingi qadam (docs).
        from app.services.cash import cutover_guard as _cg
        # ⚠️  SMENA — YAGONA YORDAMCHIDAN (`custody_preview.actor_open_shift`): o'qish
        #     ko'rinishi (`GET /cash/custody-preview?operation=receiving_payment`) AYNI
        #     smena va AYNI filial bilan AYNI `resolve_cash_custody` ni quruq yuritadi.
        _psh = _CP.actor_open_shift(db, emp)
        # §2: smena bor -> shift.till_id; smenasiz -> so'rovdagi EXPLICIT cash_account_id.
        _pacc, _ = _cg.resolve_cash_custody(db, company_id=emp.company_id, branch_id=branch.id,
                                            operation=_CP.OP_RECEIVING, shift=_psh,
                                            cash_account_id=data.cash_account_id,
                                            domain=_cg.DOMAIN_TREASURY)
        _cr.on_cash_purchase(db, emp, branch_id=branch.id, purchase_id=pur.id, cash_amount=total,
                             #  Tarixiy paytda naqd oyog'i AYNI paytni olishi SHART —
                             #  aks holda leg OFF_SHIFT bo'lib kun hisobidan tushardi.
                             cash_account_id=(_pacc.id if _pacc else None), at=(now if at is not None else None))
        if _pacc is not None:
            pur.cash_account_id = _pacc.id          # §5 audit identity
            db.add(pur)

    #  ⚠️  `image_b64` va `ai_raw` ATAYLAB BERILMAYDI (CH-15B Faza A, ega qarori):
    #      nakladnoy surati AI o'qishi uchun ishlatiladi va operator mahsulotlarni
    #      tasdiqlagandan keyin SAQLANMAYDI. Kwarg berilmagani uchun ustunlar o'z
    #      standart qiymatini oladi — `image_b64` nullable => NULL,
    #      `ai_raw` `Mapped[list], default=list` => `[]` (`models/receiving.py:22-23`).
    #      Ustunlar MODELDA QOLADI: `create_all` ustun tushirmaydi va `initdb.py` da
    #      `DROP COLUMN` yo'q, shuning uchun atributni olib tashlash eski baytlarni
    #      diskda ko'rinmas qilib qoldirardi — kelgusi tozalash ularni nishonga ola
    #      olmasdi. Sxema o'zgarishi KERAK EMAS.
    #      `CommitIn.image_b64` (`:109`) va `CommitIn.ai_raw` (`:111`) E'LON QILINGAN
    #      holda QOLADI: eski Flutter/Desktop mijozlari ularni yuborishda davom etadi,
    #      server qabul qiladi va TASHLAB YUBORADI. Ularni sxemadan olib tashlash
    #      muzlatilgan DTO ro'yxatini (`tests/test_historical_dto_freeze.py:54`) va
    #      CH-15A testini (`:68-77` — 422 aynan `image_b64` tur xatosidan keladi)
    #      buzardi.
    #      Nishon xulq allaqachon isbotlangan: `api/v1/historical_exec.py:117`
    #      `SERVER_OWNED` ikki maydonni rad etadi va `:346` shu `_commit_once` ni
    #      chaqiradi — ya'ni `image_b64=None` / `ai_raw=[]` bilan to'liq to'g'ri
    #      qabul hujjati yaratilishi test bilan qadalgan
    #      (`tests/test_historical_http_guards.py:131-132`).
    rec = Receiving(
        company_id=emp.company_id, branch_id=branch.id, employee_id=emp.id, purchase_id=pur.id,
        source=data.source, final_items=final_items,
        total_types=len(final_items), total_qty=total_qty, committed_at=now, client_uuid=data.client_uuid,
    )
    db.add(rec)
    # ── PARTIYALARNI HUJJATGA BOG'LASH + YAKUNIY DARVOZA — COMMIT'DAN OLDIN ──
    #  ⚠️  TARTIB HAL QILUVCHI. Bu blok ilgari `db.commit()` dan KEYIN turardi:
    #      o'shanda `db.rollback()` HECH NARSANI qaytarmasdi (tranzaksiya allaqachon
    #      yopilgan), ya'ni operator 409 «kirim bekor qilindi» ko'rardi, buzilgan
    #      qoldiq esa bazada QOLARDI — darvoza emas, darvoza SURATI edi.
    #      Endi tekshiruv AYNI ochiq tranzaksiyada bo'ladi va rad etish HAQIQIY.
    if _made_lots or _touched_ids:
        db.flush()                       # `rec.id` shu yerda paydo bo'ladi
        for _b in _made_lots:
            _b.receiving_id = rec.id
        db.flush()
        try:
            _LR.assert_invariant(db, emp.company_id, _touched_ids)
        except Exception as _e:      # noqa: BLE001
            db.rollback()
            # ⚠️  Istisno matni operatorga berilmaydi: ichida xom UUID va ichki
            #     nomlar bor (`stock_invariant.Mismatch.__str__`). Tafsilot jurnalda.
            log.exception("receiving invariant buzildi: products=%s", _touched_ids)
            raise HTTPException(409, "Partiya va qoldiq mos kelmadi — kirim BEKOR "
                                     "qilindi. Qo'llab-quvvatlashga murojaat qiling.",
                                headers=EC.headers(EC.LOT_INVARIANT_BROKEN)) from _e
    from sqlalchemy.exc import IntegrityError as _IE
    try:
        db.commit()
    except _IE:
        # Bir vaqtда bir xil client_uuid — DB unique indeksi (ux_receivings_client_uuid) ushlади:
        # butun tranzaksiya (ombor + xarid) bekor bo'ladi, birinchисининг natijasини qaytaramiz.
        db.rollback()
        if data.client_uuid:
            ex2 = db.query(Receiving).filter(
                Receiving.client_uuid == data.client_uuid, Receiving.company_id == emp.company_id).first()
            if ex2:
                return {"ok": True, "receiving_id": str(ex2.id), "duplicate": True}
        raise
    db.refresh(rec)
    return {"ok": True, "receiving_id": str(rec.id), "purchase_id": str(pur.id),
            "doc_no": pur.doc_no, "results": results, "payment": data.payment,
            "supplier": sup.name, "total_types": len(final_items), "total_qty": float(total_qty)}


def _doc_info(db: Session, company_id, receivings) -> dict:
    """{receiving_id: {purchase_id, doc_no, payment, supplier, purchase_status, branch_id,
    branch_name}} — ro'yxat uchun BITTA so'rovlar to'plamida (N+1 yo'q). Phase 5G.

    ⚠️  `payment` HUJJAT HOLATIDAN EMAS, LEDGERDAN (`lot_correction.is_charged` bilan
        AYNI ta'rif): to'liq to'langan qarz qabul `received` bo'lib qoladi, lekin u
        baribir QARZ hujjati. Holatdan chiqarilsa u «naqd» deb yolg'on ko'rinardi.
    ⚠️  Xarid BEKOR qilingan bo'lsa (`purchase_status="cancelled"`, tuzatish to'liq
        teskari qilgan) `purchase_id` baribir beriladi — bu tarixiy fakt; mijoz
        hujjatni ochishdan oldin holatga qaraydi (`GET /purchases/{id}` 404 beradi).
    ⚠️  Ruxsat: `/receiving` darvozasi `xaridlar.view` = `PURCHASING_TIER`, ya'ni
        hujjat raqami, ta'minotchi va to'lov turi shu o'quvchiga allaqachon ochiq."""
    pids = {r.purchase_id for r in receivings if r.purchase_id is not None}
    bids = {r.branch_id for r in receivings if r.branch_id is not None}
    purs, sups, charged = {}, {}, set()
    if pids:
        purs = {p.id: p for p in db.query(Purchase).filter(
            Purchase.id.in_(pids), Purchase.company_id == company_id).all()}
        sids = {p.supplier_id for p in purs.values() if p.supplier_id is not None}
        if sids:
            sups = dict(db.query(Supplier.id, Supplier.name).filter(Supplier.id.in_(sids)).all())
        charged = {rid for rid, sid in (
            db.query(SupplierLedger.ref_id, SupplierLedger.supplier_id)
            .filter(SupplierLedger.ref_id.in_(pids),
                    SupplierLedger.ref_type.in_(("purchase", "receiving")),
                    SupplierLedger.type == CreditTxnType.charge).all())
            if rid in purs and purs[rid].supplier_id == sid}
    bnames = (dict(db.query(Branch.id, Branch.name).filter(Branch.id.in_(bids)).all())
              if bids else {})
    out = {}
    for r in receivings:
        pur = purs.get(r.purchase_id) if r.purchase_id is not None else None
        out[r.id] = {
            "purchase_id": str(r.purchase_id) if r.purchase_id is not None else None,
            "doc_no": pur.doc_no if pur is not None else None,
            "payment": (None if pur is None
                        else ("credit" if pur.id in charged else "cash")),
            "supplier": (sups.get(pur.supplier_id) if pur is not None else None),
            "purchase_status": (pur.status.value if pur is not None else None),
            "branch_id": str(r.branch_id) if r.branch_id is not None else None,
            "branch_name": bnames.get(r.branch_id),
        }
    return out


def _tarixiy_qatorlarni_tozalash(final_items):
    """Javob uchun TOZALANGAN NUSXA — ORM obyekti hech qachon o'zgartirilmaydi (D5-a).

    NEGA NUSXA MAJBURIY. `r.final_items` — identity-map'dagi AYNAN o'sha Python
    ro'yxati. Uni joyida tahrirlash ikki zarar berardi: (a) `JSONB` bu yerda
    `Mutable` TUR EMAS (`db/types.py`), ya'ni o'zgarish flush QILINMAYDI va
    sessiya ichida saqlangan qiymat bilan xotiradagi qiymat AJRALIB ketardi;
    (b) ayni sessiyada keyin o'qigan har kim (masalan `lot_correction`) tozalangan
    ro'yxatni ko'rib, hujjatni YO'Q ma'lumot bilan hisoblardi. Shu bois: yangi
    tashqi ro'yxat + har qator uchun yangi dict.

    SAYOZ NUSXA YETARLI, chunki biz FAQAT yuqori darajadagi `ai_name` kalitini
    qayta yozamiz — ichki obyektlarga TEGMAYMIZ, shuning uchun ularni ulashish
    xavfsiz (javob faqat serializatsiya qilinadi). `deepcopy` 1000 qatorli
    hujjatda behuda ish bo'lardi.

    `ai_name` KALITI SAQLANADI, faqat qiymati olib tashlanadi. Kalitni o'chirish
    ham, hamma qatorga qo'shish ham mijoz shartnomasini o'zgartirardi:
      · mobil `receiving_api.dart:308` uni `String?` deb o'qiydi -> `null` XAVFSIZ;
      · YANGI qatorlarda bu kalit UMUMAN yo'q (CH-15B Faza A) va shunday qoladi —
        aks holda `test_ch15b_qabul_saqlanmaydi.py` dagi shakl tasdig'i buzilardi.

    Operator TASDIQLAGAN maydonlar (`product_id`, `name`, `qty`, `unit_cost`,
    `unit`) TEGILMAYDI — tarixiy `unit` qiymatlari ham (D5-a doirasidan tashqari).
    """
    tozalangan = []
    for qator in (final_items or []):
        if not isinstance(qator, dict):
            tozalangan.append(qator)      # kutilmagan shakl — tegilmaydi
            continue
        nusxa = dict(qator)
        if "ai_name" in nusxa:
            nusxa["ai_name"] = None
        tozalangan.append(nusxa)
    return tozalangan


@router.get("/receiving")
def history(limit: int = 50, emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    from app.core.deps import visible_branches
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    _vb = visible_branches(emp, db)  # filialга bog'langan xodим — faqat o'z filiali qabullari
    q = (
        db.query(Receiving)
        .filter(Receiving.company_id == emp.company_id, Receiving.committed_at.isnot(None))
    )
    if _vb is not None:
        q = q.filter(Receiving.branch_id.in_(_vb))
    rows = q.order_by(Receiving.committed_at.desc()).limit(max(1, min(limit, 200))).all()
    info = _doc_info(db, emp.company_id, rows)
    return [{
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
        **info[r.id],        # Phase 5G: purchase_id, doc_no, payment, supplier, ... (QO'SHIMCHA)
    } for r in rows]


@router.get("/receiving/{receiving_id}")
def detail(receiving_id: uuid.UUID, emp: Employee = Depends(require("xaridlar.view")), db: Session = Depends(get_db)):
    r = db.get(Receiving, receiving_id)
    if not r or r.company_id != emp.company_id:
        raise HTTPException(404, "Qabul topilmadi")
    from app.core.deps import visible_branches
    _vb = visible_branches(emp, db)  # boshqa filial qabulini ochib bo'lmaydi (IDOR)
    if _vb is not None and r.branch_id not in _vb:
        raise HTTPException(404, "Qabul topilmadi")
    names = dict(db.query(Employee.id, Employee.full_name).filter(Employee.company_id == emp.company_id).all())
    return {
        "id": str(r.id), "at": r.committed_at, "source": r.source,
        "employee": names.get(r.employee_id, "—"),
        "total_types": r.total_types, "total_qty": float(r.total_qty),
        #  ⚠️  TARIXIY MAXFIY YUK JAVOBDA QAYTARILMAYDI (D5-a, ega qarori).
        #      CH-15B Faza A faqat YANGI qatorlarni to'xtatdi; Faza A dan OLDIN
        #      yozilgan qatorlarda `image_b64` to'liq base64 surat (EXIF/GPS bilan),
        #      `ai_raw` AI ning xom javobi va `final_items[].ai_name` esa AI ning
        #      so'zma-so'z o'qishi bo'lib QOLGAN. Bu yo'l ularning YAGONA API
        #      chiqishi edi (butun repoda boshqa o'quvchi yo'q).
        #
        #      KALITLAR VA TURLAR SAQLANADI — o'rnatilgan mijozlar buzilmaydi:
        #        `image_b64` -> None   (mobil `receiving_api.dart:347` `is String`
        #                               tekshiradi -> surat ko'rsatilmaydi, xato YO'Q)
        #        `ai_raw`    -> []     (detail DTO'da bu maydon UMUMAN yo'q —
        #                               `aiRaw` faqat `AiScan` da, ya'ni no-op)
        #        `ai_name`   -> None   (`_tarixiy_qatorlarni_tozalash`, kalit joyida)
        #
        #      MA'LUMOT O'CHIRILMAYDI: diskdagi qatorlar TEGILMAGAN. Bu — chiqishni
        #      yopish, tozalash emas (legacy purge = Faza C, alohida ruxsat).
        "items": _tarixiy_qatorlarni_tozalash(r.final_items),
        "ai_raw": [], "image_b64": None,
        # Phase 5G: tuzatish ekrani (`GET /purchases/{id}`) shu havola orqali ochiladi.
        **_doc_info(db, emp.company_id, [r])[r.id],
    }


# ══ QABULNI TUZATISH (Phase 5D) ═════════════════════════════════════════════
#
# ⚠️  NEGA ALOHIDA ENDPOINT, NEGA `PATCH /purchases/{id}` EMAS. Eski tahrir yo'li
#     hujjat jamini `purchase_items` dan QAYTA hisoblaydi va qoldiqni ISHORALI
#     delta bilan siljitadi — u qaysi PARTIYA o'zgarayotganini bilmaydi va
#     kuzatuvli mahsulotda `stock_gate` bilan 409 oladi. Tuzatish esa partiya
#     darajasidagi amal: teskari yozuv + o'rniga qo'yish
#     (`services/lot_correction.py`, `services/RECEIVING_CORRECTION.md`).

class CorrectionReverse(BaseModel):
    """Mavjud kogortadan teskari qilinadigan ANIQ miqdor (tizim TAXMIN QILMAYDI)."""
    stock_batch_id: uuid.UUID
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)


class CorrectionLot(BaseModel):
    """O'rniga qo'yiladigan YANGI kogorta — kirim partiyasi bilan AYNI shakl."""
    qty: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    batch_number: str | None = Field(default=None, max_length=64)
    expiry_date: date | None = None
    unit_cost: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)


class CorrectionLine(BaseModel):
    purchase_item_id: uuid.UUID
    # ⚠️  CHEGARA (50) — `CommitItem.lots` bilan AYNI sabab: chegarasiz ro'yxat
    #     bitta tranzaksiyada cheksiz INSERT va invariant tekshiruvi demakdir.
    reverse: list[CorrectionReverse] = Field(default_factory=list, max_length=50)
    replace: list[CorrectionLot] = Field(default_factory=list, max_length=50)
    # `replace` bo'sh bo'lmasa MAJBURIY; bo'sh bo'lsa BERILMASLIGI shart
    # (tannarxni partiyasiz tuzatib bo'lmaydi — `lot_correction._check_shape`).
    unit_cost: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)


class CorrectionIn(BaseModel):
    """⚠️  `client_uuid` MAJBURIY (Phase 4A namunasi). Tuzatish qoldiqni, yetkazib
        beruvchi qarzini VA kassani siljitadi: tarmoq uzilishida takror so'rov
        buni IKKI marta qilmasligi kerak va buning yagona tranzaksion kafolati —
        `(company_id, client_uuid)` noyob indeksi."""
    client_uuid: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)     # AUDIT uchun MAJBURIY
    # §1 EXPLICIT CUSTODY: smenasiz naqd amali uchun fizik hisob (TILL yoki SAFE)
    # AYNAN ko'rsatiladi; ochiq smena bo'lsa server shift.till_id ni ishlatadi.
    cash_account_id: uuid.UUID | None = None
    lines: list[CorrectionLine] = Field(min_length=1, max_length=200)


@router.post("/receiving/{receiving_id}/corrections")
def correct_receiving(receiving_id: uuid.UUID, data: CorrectionIn,
                      emp: Employee = Depends(require("xaridlar.edit")),
                      db: Session = Depends(get_db)):
    """Qabul hujjatini TUZATADI — teskari yozuv + o'rniga qo'yish, bitta tranzaksiyada.

    ⚠️  BU YERDA FAQAT TARJIMA. Butun qaror, qulf tartibi va rad etishlar
        `services/lot_correction.py` da: servis HTTP ni BILMAYDI va tipli xato
        ko'taradi (`lot_receiving` / `lot_writeoff` / `lot_return` bilan AYNI
        naqsh). Barqaror kod MATNGA qo'shilmaydi — u `X-Error-Code`
        sarlavhasiga ketadi (`app/core/error_codes.py` izohi).
    """
    from app.services import lot_correction as _LC
    # ⚠️  BIRLIK DARVOZASI — servis chaqiruvidan va qulflardan OLDIN. Tuzatish IKKI
    #     xil FIZIK miqdor yozadi: `reverse[].qty` (kogortani teskari qilish) va
    #     `replace[].qty` (yangi kogorta). So'rov tanasida `product_id` YO'Q —
    #     mahsulot `purchase_item_id` orqali yechiladi.
    #     HAR QATOR XOM holda: `lot_correction` qator yig'indilari bilan ishlaydi,
    #     ya'ni `0.5 + 0.5` butun jamiga YUVILARDI.
    from sqlalchemy import select as _sa_select
    from app.models.purchasing import PurchaseItem as _PI
    from app.services import unit_gate as _UG
    _ug_pi = dict(db.execute(_sa_select(_PI.id, _PI.product_id).where(
        _PI.id.in_([ln.purchase_item_id for ln in data.lines]))).all())
    _ug_rows = []
    for _ln in data.lines:
        _pid = _ug_pi.get(_ln.purchase_item_id)
        _ug_rows += [(_pid, _rv.qty) for _rv in _ln.reverse]
        _ug_rows += [(_pid, _rp.qty) for _rp in _ln.replace]
    _UG.validate_lines(db, _ug_rows, label="qabul tuzatishi")
    req = _LC.CorrectionIn(
        client_uuid=data.client_uuid, reason=data.reason,
        cash_account_id=data.cash_account_id,
        lines=[_LC.LineIn(
            purchase_item_id=ln.purchase_item_id,
            reverse=[_LC.ReverseIn(stock_batch_id=r.stock_batch_id,
                                   qty=Decimal(str(r.qty))) for r in ln.reverse],
            replace=[_LC.ReplaceIn(
                qty=Decimal(str(x.qty)), batch_number=x.batch_number,
                expiry_date=x.expiry_date,
                unit_cost=(Decimal(str(x.unit_cost)) if x.unit_cost is not None else None))
                for x in ln.replace],
            unit_cost=(Decimal(str(ln.unit_cost)) if ln.unit_cost is not None else None))
            for ln in data.lines])
    try:
        return _LC.correct(db, emp, receiving_id, req)
    except _LC.CorrectionError as e:
        db.rollback()
        raise HTTPException(e.status, e.detail,
                            headers=EC.headers(e.code) if e.code else None) from e
