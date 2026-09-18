# -*- coding: utf-8 -*-
"""PHASE 5E — QABULNI TUZATISHDA KASSA CUSTODY'SI (§A.2 R0..R10 + §A.3 bloki).

⚠️  NEGA SQLite'DA EMAS. Butun qaror `cash.cash_accounts` qatorlariga qaraydi
    (TILL/SAFE, ACTIVE/ARCHIVED, tenant, filial), bu jadval esa ATAYLAB FAQAT
    Postgres'da mavjud (`app/models/cash.py`: alohida metadata, `cash` sxemasi).
    SQLite'da R2..R10 ning BIRORTASI ham TUG'ILMAYDI — u yerda sinov «yashil»
    bo'lardi va hech narsani o'lchamasdi. Shu bois bu fayl o'z pgserver'ini
    ko'taradi va HAQIQIY `app.initdb` (cash sxemasi bilan) ustida ishlaydi.

USHLANADIGAN NUQSONLAR SINFLARI
  1. TAXMIN — tizim kassani O'ZI o'ylab topishi (filial-default, birinchi TILL,
     yagona SAFE, kassir-default, begona filial hisobi, ARXIVLANGAN hisob).
  2. YARIM BAJARILGAN RAD ETISH — custody rad etganda hujjat/qoldiq/kassa
     qatorlari BAZADA qolib ketishi. Custody §13 da, ya'ni teskari yozuv
     ALLAQACHON yozilgandan KEYIN so'raladi: rad etish tranzaksiyani ROSTDAN
     qaytarishi SHART (har rad etishda `_izsiz`).
  3. EKRAN BILAN YOZUVCHINING AJRALISHI — `cash_custody` bloki operatorga
     «mumkin» deb ko'rsatib, server 400 berishi (yoki teskarisi). Blok
     yozuvchining O'Z funksiyasidan o'qiladi va har rejim AYNI holatda
     haqiqiy so'rov bilan tekshiriladi.
  4. ORTIQCHA OSHKORLIK — tanlov ro'yxatiga begona filial, begona do'kon,
     ARXIVLANGAN hisob yoki `label`/`terminal_id` kabi maydonlarning sizishi.
  5. PUL QIMIRLAMAYDIGAN TUZATISHNING BLOKLANISHI — muddat/partiya raqami
     xatosini smenasiz menejer ham tuzata olishi SHART (Phase 5D tuzatishi;
     R1 aynan shuni qo'riqlaydi).

⚠️  HAR RAD ETISH AYNAN BIR KOD BILAN. Kod MATN PREFIKSIDA keladi
    (`cutover_guard._fail`: `"<KOD>: matn"`) — mijoz ham aynan shu prefiks
    bo'yicha tarjima qiladi, shu bois sinov kodni MATNDAN qidiradi.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services import lot_correction as LC
from app.services.cash import cutover_guard as CG
from tests.test_check_defs_pg import _initdb, _psycopg_url
from tests.test_lot_tz_confirm_pg import _mk

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
QTY = Decimal("10")           # qabul qilingan miqdor
COST = Decimal("50")          # partiya tannarxi -> hujjat jami 500.00
KAM = Decimal("3")            # teskari qilinadigan miqdor -> qaytadigan naqd 150.00
QAYTIM = Decimal("150.00")    # KAM × COST
SABAB = "5E: nakladnoyda miqdor xato"
PUL = Decimal("100000")       # kassani to'ldirish (OUT oyog'i yetarlilik tekshiruvidan o'tsin)


# ══ BAZA ════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    """MODUL doirasida BITTA klaster + BITTA `initdb`.

    ⚠️  Har test uchun alohida klaster ko'tarish (`pg_target` naqshi) bu faylda
        20+ marta `app.initdb` ni qayta yugurtirardi. Buning o'rniga har sinov
        O'Z DO'KONINI yaratadi: izolyatsiya tenant darajasida, ya'ni sinovlar
        bir-birining qatorini KO'RMAYDI."""
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("custody5e") / "pgdata"))
    eng = S = None
    try:
        url = _psycopg_url(srv.get_uri())
        _initdb(url)
        eng, S = _mk(url)
        # Bu fayl SQLite'da HECH NARSANI o'lchamaydi (cash sxemasi u yerda YO'Q).
        assert eng.dialect.name == "postgresql", eng.dialect.name
        yield S
    finally:
        if eng is not None:
            eng.dispose()
        try:
            srv.cleanup()
        except Exception:       # noqa: BLE001
            pass


def _hex():
    return uuid.uuid4().hex[:8]


def _dokon(S, *, ikkinchi_filial=False):
    """Do'kon + filial(lar) + ega + KUZATUVLI mahsulot + ta'minotchi (qoldiq 0)."""
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="5E " + _hex(), code="c5e" + _hex(), currency="UZS")
        s.add(co)
        s.flush()
        # ⚠️  `created_at` ANIQ: `actor_branch()` eng ESKI faol filialni tanlaydi, ya'ni
        #     hujjat FILIALI shu tartibdan kelib chiqadi. Tartibsiz `first()` bilan
        #     «begona filial» sinovlari tasodifan to'g'ri filialga tushardi.
        b1 = Branch(id=uuid.uuid4(), company_id=co.id, code="F01", name="Markaz", timezone=TZ,
                    is_active=True, created_at=NOW - timedelta(days=10))
        s.add(b1)
        s.flush()
        b2 = None
        if ikkinchi_filial:
            b2 = Branch(id=uuid.uuid4(), company_id=co.id, code="F02", name="Ikkinchi",
                        timezone=TZ, is_active=True, created_at=NOW - timedelta(days=5))
            s.add(b2)
            s.flush()
        ega = s.query(Role).filter(Role.code == "ega").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name="5E ega",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
        s.add(e)
        s.flush()
        unit = s.query(Unit).filter(Unit.code == "dona").first() or s.query(Unit).first()
        nom = "5E " + _hex()
        p = Product(id=uuid.uuid4(), company_id=co.id, name=nom,
                    article_code="5E-" + _hex(), sku=_hex(), unit_id=unit.id,
                    base_buy_price=COST, base_sell_price=100, tax_rate=0, track_lots=True)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=b1.id, qty=Decimal("0"),
                        min_qty=0, updated_at=NOW))
        sup = Supplier(id=uuid.uuid4(), company_id=co.id, name="5E ta'minotchi")
        s.add(sup)
        s.commit()
        return {"cid": co.id, "bid": b1.id, "bid2": (b2.id if b2 else None), "emp": e.id,
                "pid": p.id, "sup": sup.id, "nom": nom}
    finally:
        s.close()


def _emp(s, d):
    from app.models.auth import Employee
    return s.get(Employee, d["emp"])


def _hisob(S, d, *, typ="TILL", branch=None, status="ACTIVE", tenant=None, code=None):
    """Bitta kassa hisobi (TILL yoki SAFE). `_ti` yorliq konvensiyasidan chetga chiqilmaydi."""
    from app.models.cash import CashAccount
    from app.services.cash import till_identity as _ti
    kod = code or ((("T-" if typ == "TILL" else "S-")) + _hex())
    s = S()
    try:
        a = CashAccount(id=uuid.uuid4(), tenant_id=(tenant or d["cid"]),
                        branch_id=(branch or d["bid"]), type=typ, currency="UZS", status=status,
                        label=(_ti.till_label(kod, None) if typ == "TILL" else _ti.safe_label(kod)),
                        created_at=NOW)
        s.add(a)
        s.commit()
        return {"id": a.id, "code": kod, "type": typ, "currency": "UZS"}
    finally:
        s.close()


def _pul(S, d, acc, amount=PUL):
    """Hisobni to'ldiradi — OUT oyog'i (naqd xarid) yetarlilik tekshiruvidan o'tsin."""
    from app.services.cash import adapters as _ad
    s = S()
    try:
        _ad.manual_cash_in(s, _emp(s, d), cash_account_id=acc["id"], source_id=uuid.uuid4(),
                           amount=Decimal(str(amount)), commit=True)
    finally:
        s.close()


def _t0(S, d, *, hours_ago=1):
    """T0 (cutover) ni O'TMISHGA qo'yadi — majburlash rejimi FAOL bo'ladi."""
    from app.models.settings import Setting
    s = S()
    try:
        row = (s.query(Setting).filter(Setting.company_id == d["cid"], Setting.key == "cash",
                                       Setting.branch_id.is_(None)).first())
        val = {"cutover_at": (NOW - timedelta(hours=hours_ago)).isoformat()}
        if row is None:
            s.add(Setting(company_id=d["cid"], branch_id=None, key="cash", value=val))
        else:
            row.value = val
        s.commit()
    finally:
        s.close()


def _smena(S, d, *, till=None, branch=None):
    """Aktyorning OCHIQ smenasi (`till=None` -> LEGACY smena: `till_id` YO'Q)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    s = S()
    try:
        sh = Shift(id=uuid.uuid4(), branch_id=(branch or d["bid"]), cashier_id=d["emp"],
                   opened_at=NOW - timedelta(hours=2), opening_cash=Decimal("0"),
                   status=ShiftStatus.open, till_id=(till["id"] if till else None))
        s.add(sh)
        s.commit()
        return sh.id
    finally:
        s.close()


def _qabul(S, d, *, payment="cash", account=None, partiyali=True):
    """HAQIQIY `POST /receiving/commit` — bitta qatorli qabul.

    `partiyali=False` — mahsulot kuzatuvdan chiqariladi va qabul PARTIYA
    YARATMAYDI: bu hujjat darajasidagi tuzatish to'sig'ini tug'diradigan
    YAGONA to'g'ri yo'l (partiyani keyin `DELETE` qilish o'z-o'zidan yasalgan,
    bazada hech qachon uchramaydigan holat bo'lardi)."""
    from app.api.v1.receiving import CommitIn, commit
    from app.models.catalog import Product
    from app.models.inventory import StockBatch
    from app.models.purchasing import PurchaseItem
    from app.models.receiving import Receiving
    if not partiyali:
        s = S()
        try:
            s.get(Product, d["pid"]).track_lots = False
            s.commit()
        finally:
            s.close()
    qator = {"product_id": str(d["pid"]), "qty": float(QTY), "unit_cost": float(COST),
             "unit": "dona"}
    if partiyali:
        qator["lots"] = [{"qty": float(QTY), "batch_number": "A-1"}]
    s = S()
    try:
        r = commit(CommitIn(
            items=[qator], supplier_id=d["sup"], payment=payment, source="manual",
            cash_account_id=(account["id"] if account else None),
            client_uuid=uuid.uuid4()), emp=_emp(s, d), db=s)
        assert r["ok"] is True, r
    finally:
        s.close()
    s = S()
    try:
        rec = s.get(Receiving, uuid.UUID(r["receiving_id"]))
        item = s.query(PurchaseItem).filter(PurchaseItem.purchase_id == rec.purchase_id).one()
        batch = (s.query(StockBatch).filter(StockBatch.receiving_id == rec.id).one()
                 if partiyali else None)
        d.update({"rec": rec.id, "pur": rec.purchase_id, "item": item.id,
                  "batch": (batch.id if batch else None)})
        return d
    finally:
        s.close()


# ══ TUZATISH CHAQIRUVLARI ═══════════════════════════════════════════════════

def _amal(d, *, reverse=None, replace=None, account=None, cu=None, reason=SABAB,
          narx=COST):
    """HAQIQIY `POST /receiving/{id}/corrections` — SESSIYA OLADIGAN chaqiruv.

    Poyga sinovlari tranzaksiyani O'ZLARI boshqaradi (`_navbat`), shu bois
    chaqiruv sessiyadan AJRATILGAN."""
    from app.api.v1.receiving import (CorrectionIn, CorrectionLine, CorrectionLot,
                                      CorrectionReverse, correct_receiving)
    body = CorrectionIn(
        client_uuid=(cu or uuid.uuid4()), reason=reason,
        cash_account_id=(account["id"] if account else None),
        lines=[CorrectionLine(
            purchase_item_id=d["item"],
            reverse=[CorrectionReverse(stock_batch_id=b, qty=float(q))
                     for b, q in (reverse or [])],
            replace=[CorrectionLot(**x) for x in (replace or [])],
            unit_cost=(float(narx) if replace else None))])
    return lambda s: correct_receiving(d["rec"], body, emp=_emp(s, d), db=s)


def _tuzat(S, d, **kw):
    """`_amal` ni O'Z sessiyasida bajaradi — AYNAN `get_db` kabi yopiladi:
    muvaffaqiyatda servis commit qilgan, rad etishda `close()` qaytaradi."""
    s = S()
    try:
        return _amal(d, **kw)(s)
    finally:
        s.close()


def _kamaytir(S, d, **kw):
    """PUL QIMIRLAYDIGAN tuzatish: 3 dona teskari -> hujjat 500 -> 350, naqd 150 qaytadi."""
    return _tuzat(S, d, reverse=[(d["batch"], KAM)], **kw)


def _nol(S, d, **kw):
    """PUL QIMIRLAMAYDIGAN tuzatish: 3 dona AYNI narxda o'rniga qo'yiladi (delta 0)."""
    return _tuzat(S, d, reverse=[(d["batch"], KAM)],
                  replace=[{"qty": float(KAM), "batch_number": "A-2"}], **kw)


def _rad(fn, *a, **kw):
    """Rad etishni (status, matn) sifatida qaytaradi — boshqa istisno sinovni QIZIL qiladi."""
    with pytest.raises(HTTPException) as ei:
        fn(*a, **kw)
    return ei.value.status_code, str(ei.value.detail)


# ══ HOLAT VA IZ ═════════════════════════════════════════════════════════════

def _ledger(S, d, *, source_types=("PURCHASE", "PURCHASE_RETURN")):
    """Do'konning tuzatishga aloqador ledger qatorlari (to'ldirish CASH_OP chiqariladi)."""
    from app.models.cash import CashLedgerEntry as CLE
    s = S()
    try:
        return sorted(
            (r.source_type, str(r.source_id), r.leg_index, r.direction, r.category,
             str(r.cash_account_id), Decimal(str(r.amount)))
            for r in s.query(CLE).filter(CLE.tenant_id == d["cid"],
                                         CLE.source_type.in_(source_types)).all())
    finally:
        s.close()


def _holat(S, d):
    """Tuzatishning BUTUN izi — rad etishdan keyin AYNAN o'zgarmagan bo'lishi shart."""
    from app.models.inventory import Inventory, StockBatch, StockMovement
    from app.models.purchasing import Purchase, PurchaseReturn, Supplier
    from app.models.receiving import ReceivingCorrection
    s = S()
    try:
        pur = s.get(Purchase, d["pur"])
        b = s.get(StockBatch, d["batch"]) if d.get("batch") else None
        return {
            "ledger": _ledger(S, d),
            "tuzatish": s.query(ReceivingCorrection).filter(
                ReceivingCorrection.company_id == d["cid"]).count(),
            "qaytarish": s.query(PurchaseReturn).filter(
                PurchaseReturn.company_id == d["cid"]).count(),
            "harakat": sorted((m.ref_type, Decimal(str(m.qty))) for m in
                              s.query(StockMovement).filter(
                                  StockMovement.product_id == d["pid"]).all()),
            "inv": Decimal(str(s.query(Inventory.qty).filter(
                Inventory.product_id == d["pid"], Inventory.branch_id == d["bid"]).scalar() or 0)),
            "partiya": ((b.status, Decimal(str(b.remaining_qty)), Decimal(str(b.received_qty)))
                        if b is not None else None),
            "hujjat": (pur.status.value, Decimal(str(pur.total)),
                       Decimal(str(pur.paid_amount or 0)), pur.deleted_at is not None),
            "balans": Decimal(str(s.get(Supplier, d["sup"]).balance or 0)),
        }
    finally:
        s.close()


def _izsiz(S, d, oldin, *, kod, javob):
    """RAD ETISH IZ QOLDIRMAYDI: kod aynan kutilgan, baza esa BIT-BA-BIT o'sha.

    ⚠️  «NOL LEDGER» YOLG'IZ YETMAYDI. Custody §13 da, ya'ni teskari yozuv,
        `ReceivingCorrection` sarlavhasi va hujjat summalari ALLAQACHON
        yozilgandan KEYIN so'raladi. Faqat ledgerni sanash bu qatorlarning
        qolib ketganini KO'RMASDI."""
    holat, matn = javob
    assert holat == 400, javob
    assert matn.startswith(kod + ":"), javob
    assert CG.code_of(matn) == kod, javob
    keyin = _holat(S, d)
    assert keyin == oldin, f"rad etilgan tuzatish IZ qoldirdi: {oldin} -> {keyin}"


def _detail(S, d):
    """HAQIQIY `GET /purchases/{id}` javobi."""
    from app.api.v1.purchases import purchase_detail
    s = S()
    try:
        return purchase_detail(d["pur"], emp=_emp(s, d), db=s)
    finally:
        s.close()


def _custody(S, d):
    return _detail(S, d)["cash_custody"]


# ═══════════════════════════════════════════════════════════════════════════
# §A.2 — QAROR JADVALI R0..R10
# ═══════════════════════════════════════════════════════════════════════════

def test_R0_QARZ_hujjatida_custody_UMUMAN_SORALMAYDI(pg):
    """R0 — hujjat `charged` (qarz): kassa oyog'i yo'q, hisob ham so'ralmaydi.

    ⚠️  T0 O'TGAN VA SMENA YO'Q. Custody `_charged` dan KEYIN kelsa, bu holat
        rad etilardi — holbuki qarz hujjatida kassa UMUMAN qatnashmaydi va
        rad etish menejerni sababsiz to'xtatardi."""
    S = pg
    d = _qabul(S, _dokon(S), payment="credit")
    _t0(S, d)
    r = _kamaytir(S, d)
    assert r["ok"] is True and r["delta_total"] == -150.0, r
    h = _holat(S, d)
    assert h["ledger"] == [], f"qarz hujjati KASSAGA tegdi: {h}"
    assert h["hujjat"] == ("debt", Decimal("350.00"), Decimal("0.00"), False), h
    assert h["balans"] == Decimal("350.00"), h
    assert _custody(S, d)["mode"] == LC.MODE_NOT_APPLICABLE


def test_R1_PUL_QIMIRLAMAYDIGAN_tuzatish_SMENASIZ_ham_otadi(pg):
    """R1 — `ret_amt == 0`: identifikatsiya tuzatishi (partiya raqami) uchun
    kassa hisobi SO'RALMAYDI, T0 o'tgan va smena yo'q bo'lsa ham.

    ⚠️  PHASE 5D TUZATISHINING QO'RIQCHISI. Ilgari custody HAR naqd hujjat
        uchun, `delta_total` MA'LUM BO'LISHIDAN OLDIN so'ralardi: muddat yoki
        partiya raqami xatosi ham smenasiz menejerga yopiq edi va Manager
        `cash_account_id` yubormagani uchun qayta urinishning YO'LI yo'q edi."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    oldin = _ledger(S, d)
    r = _nol(S, d)
    assert r["ok"] is True and r["delta_total"] == 0.0, r
    assert _ledger(S, d) == oldin, "pul qimirlamagan tuzatish KASSAGA tegdi"
    h = _holat(S, d)
    assert h["hujjat"] == ("received", Decimal("500.00"), Decimal("500.00"), False), h
    assert h["qaytarish"] == 0, h


def test_R2_OCHIQ_SMENA_kassasini_SERVER_hal_qiladi(pg):
    """R2 — smena bor, `till_id` bor, filial mos: custody = shift.till_id."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    _smena(S, d, till=till)
    r = _kamaytir(S, d)
    assert r["ok"] is True and r["delta_total"] == -150.0, r
    led = sorted((x[0], x[3], x[5], x[6]) for x in _ledger(S, d))
    assert led == sorted([("PURCHASE", "OUT", str(till["id"]), Decimal("500.00")),
                          ("PURCHASE_RETURN", "IN", str(till["id"]), QAYTIM)]), led


def test_R3_SMENA_KASSASIDAN_BOSHQA_hisob_RAD_etiladi_T0_gacha_HAM(pg):
    """R3 — smenaga bog'langan naqdda kassani ALMASHTIRIB bo'lmaydi.

    Bu darvoza T0'dan OLDIN ham ishlaydi: `resolve_cash_custody` da smena shoxi
    `enforced` tekshiruvidan OLDIN turadi. Aks holda operator pre-T0 da pulni
    boshqa yashikka «qaytarib», smena hisob-kitobini jimgina buzardi."""
    S = pg
    for t0_bormi in (False, True):
        d = _dokon(S)
        till = _hisob(S, d)
        boshqa = _hisob(S, d)
        _pul(S, d, till)
        d = _qabul(S, d, account=till)
        if t0_bormi:
            _t0(S, d)
        _smena(S, d, till=till)
        oldin = _holat(S, d)
        _izsiz(S, d, oldin, kod=CG.ERR_TILL_SHIFT_MISMATCH,
               javob=_rad(_kamaytir, S, d, account=boshqa))


def test_R4_BEGONA_FILIAL_smenasi_OLIK_YOL_hisob_ham_QUTQARMAYDI(pg):
    """R4 — ochiq smena BOSHQA filialda: hujjat filialiga tegishli bo'lmagan
    kassa `CASH_CUSTODY_ACCOUNT_INVALID` bilan rad etiladi va TO'G'RI hisobni
    aniq ko'rsatish ham qutqarmaydi (R3 undan OLDIN chiqadi)."""
    S = pg
    d = _dokon(S, ikkinchi_filial=True)
    till = _hisob(S, d)                                   # hujjat filiali
    begona = _hisob(S, d, branch=d["bid2"])               # ikkinchi filial kassasi
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    _smena(S, d, till=begona, branch=d["bid2"])
    oldin = _holat(S, d)
    _izsiz(S, d, oldin, kod=CG.ERR_CUSTODY_INVALID, javob=_rad(_kamaytir, S, d))
    # ANIQ hisob ham OCHMAYDI — smena shoxi baribir birinchi javob beradi.
    _izsiz(S, d, oldin, kod=CG.ERR_TILL_SHIFT_MISMATCH,
           javob=_rad(_kamaytir, S, d, account=till))


def test_R5_LEGACY_SMENA_till_siz_RAD_hisob_ham_QUTQARMAYDI(pg):
    """R5 — T0'ni kesib o'tgan legacy smena (`till_id` NULL): aniq hisob berilsa
    ham rad etiladi. Kassa avtomatik biriktirilmaydi; smena YOPILISHI kerak."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    _smena(S, d, till=None)
    oldin = _holat(S, d)
    for hisob in (None, till):
        _izsiz(S, d, oldin, kod=CG.ERR_LEGACY_SHIFT_NEEDS_TILL,
               javob=_rad(_kamaytir, S, d, account=hisob))


def test_R6_SMENASIZ_post_T0_hisobsiz_RAD_etiladi(pg):
    """R6 — Phase 5D dagi bo'shliq: smenasiz menejer post-T0 da pul
    qaytaradigan tuzatishni AYNIQSA hisob ko'rsatmasdan bajara olmaydi."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    oldin = _holat(S, d)
    _izsiz(S, d, oldin, kod=CG.ERR_CUSTODY_REQUIRED, javob=_rad(_kamaytir, S, d))


@pytest.mark.parametrize("tur", ["TILL", "SAFE"])
def test_R7_SMENASIZ_post_T0_ANIQ_hisob_bilan_OTADI(pg, tur):
    """R7 — smenasiz post-T0: hujjat filialining FAOL TILL yoki SAFE hisobi
    ko'rsatilsa, naqd AYNAN o'sha hisobga qaytadi."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    manzil = till if tur == "TILL" else _hisob(S, d, typ="SAFE")
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    r = _kamaytir(S, d, account=manzil)
    assert r["ok"] is True and r["delta_total"] == -150.0, r
    led = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
    assert [(x[3], x[5], x[6]) for x in led] == [("IN", str(manzil["id"]), QAYTIM)], led


def test_R8_pre_T0_hisobsiz_LEGACY_yol_bilan_yoziladi(pg):
    """R8 — T0 belgilanmagan (BUGUNGI Fayzan): eski xatti-harakat saqlanadi,
    naqd filialning YAGONA kassasiga qaytadi va amal RAD ETILMAYDI."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    r = _kamaytir(S, d)
    assert r["ok"] is True and r["delta_total"] == -150.0, r
    led = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
    assert [(x[3], x[5], x[6]) for x in led] == [("IN", str(till["id"]), QAYTIM)], led


def test_R9_pre_T0_ANIQ_hisob_VALIDATSIYA_qilinadi_va_ISHLATILADI(pg):
    """R9 — pre-T0 da ham aniq hisob TEKSHIRILADI va AYNAN o'sha ishlatiladi
    («pre-T0» degan sabab bilan noto'g'ri hisob jimgina qabul qilinmaydi)."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    seyf = _hisob(S, d, typ="SAFE")
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    r = _kamaytir(S, d, account=seyf)
    assert r["ok"] is True, r
    led = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
    assert [(x[3], x[5], x[6]) for x in led] == [("IN", str(seyf["id"]), QAYTIM)], led


@pytest.mark.parametrize("nuqson", ["arxiv", "begona_filial", "begona_dokon", "notanish"])
def test_R10_YAROQSIZ_hisob_RAD_etiladi(pg, nuqson):
    """R10 — ARXIVLANGAN / begona filial / begona do'kon / umuman yo'q hisob:
    hammasi AYNI barqaror kod bilan rad etiladi va HECH NARSA yozilmaydi."""
    S = pg
    d = _dokon(S, ikkinchi_filial=True)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    if nuqson == "arxiv":
        yomon = _hisob(S, d, status="ARCHIVED")
    elif nuqson == "begona_filial":
        yomon = _hisob(S, d, branch=d["bid2"])
    elif nuqson == "begona_dokon":
        ikkinchi = _dokon(S)
        yomon = _hisob(S, ikkinchi)
    else:
        yomon = {"id": uuid.uuid4()}
    oldin = _holat(S, d)
    _izsiz(S, d, oldin, kod=CG.ERR_CUSTODY_INVALID,
           javob=_rad(_kamaytir, S, d, account=yomon))


# ═══════════════════════════════════════════════════════════════════════════
# §A.3 — `cash_custody` BLOKI (BESH REJIM)
# ═══════════════════════════════════════════════════════════════════════════

def test_BLOK_NOT_APPLICABLE_qarz_hujjatida_STATUSDAN_hosil_QILINMAYDI(pg):
    """Qarz hujjati — rejim `NOT_APPLICABLE`, hujjat TO'LIQ TO'LANGAN bo'lsa ham.

    ⚠️  MAVJUD `payment` MAYDONI YOLG'ON GAPIRADI: u `status` dan hosil bo'ladi
        va to'liq to'langan qarz hujjatini «cash» deb ko'rsatadi. Blok esa
        ledger predikatidan (`is_charged`) o'qiydi — aks holda ekran qarz
        hujjatida kassa hisobini so'rardi."""
    S = pg
    d = _qabul(S, _dokon(S), payment="credit")
    _t0(S, d)
    s = S()
    try:
        from app.models.enums import PurchaseStatus
        from app.models.purchasing import Purchase
        pur = s.get(Purchase, d["pur"])
        pur.paid_amount = pur.total
        pur.status = PurchaseStatus.received      # «to'liq to'langan qarz»
        s.commit()
    finally:
        s.close()
    det = _detail(S, d)
    assert det["payment"] == "cash", "sinov o'lchamaydi: eski maydon yolg'on gapirmadi"
    blok = det["cash_custody"]
    assert blok["mode"] == LC.MODE_NOT_APPLICABLE, blok
    assert blok["reason"] is None and blok["resolved"] is None and blok["options"] == [], blok
    assert blok["branch"]["id"] == str(d["bid"]), blok


def test_BLOK_NOT_REQUIRED_pre_T0_da(pg):
    """T0 belgilanmagan naqd hujjat — ekran HECH NARSA ko'rsatmaydi va yubormaydi."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_NOT_REQUIRED, blok
    assert blok["reason"] is None and blok["resolved"] is None and blok["options"] == [], blok
    assert blok["branch"] == {"id": str(d["bid"]), "name": "Markaz"}, blok


def test_BLOK_SERVER_RESOLVED_smena_kassasini_KORSATADI_tanlov_YOQ(pg):
    """R2 holati — blok kassani O'QISH uchun beradi, tanlov ro'yxatini EMAS."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _hisob(S, d, typ="SAFE")                      # seyf bor, lekin tanlov CHIQMAYDI
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    _smena(S, d, till=till)
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_SERVER_RESOLVED, blok
    assert blok["reason"] is None and blok["options"] == [], blok
    assert blok["resolved"] == {"id": str(till["id"]), "type": "TILL",
                                "code": till["code"], "currency": "UZS"}, blok
    # VA yozuvchi AYNI hisobga yozadi — blok bilan yozuvchi bir xil javob beradi.
    assert _kamaytir(S, d)["ok"] is True
    led = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
    assert [(x[5], x[6]) for x in led] == [(str(till["id"]), QAYTIM)], led


def test_BLOK_OPERATOR_MUST_CHOOSE_TILL_va_SAFE_ni_beradi(pg):
    """R6 holati — tanlov ro'yxati: hujjat filialining FAOL TILL va SAFE lari."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    seyf = _hisob(S, d, typ="SAFE")
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_OPERATOR_MUST_CHOOSE, blok
    assert blok["reason"] == CG.ERR_CUSTODY_REQUIRED, blok
    assert blok["resolved"] is None, blok
    assert sorted(o["id"] for o in blok["options"]) == sorted(
        [str(till["id"]), str(seyf["id"])]), blok
    # Ro'yxatdagi hisob HAQIQATAN ishlaydi: ko'rsatilgan tanlov «yolg'on» emas.
    assert _kamaytir(S, d, account=seyf)["ok"] is True


def test_BLOK_OPERATOR_MUST_CHOOSE_filialda_hisob_YOQ_bosh_royxat(pg):
    """Filialda birorta faol hisob bo'lmasa — ro'yxat BO'SH (ekran buni ANIQ
    xabar bilan ko'rsatadi; bo'sh «select» emas)."""
    S = pg
    d = _dokon(S, ikkinchi_filial=True)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    s = S()
    try:                                          # yagona kassani ARXIVLAYMIZ
        from app.models.cash import CashAccount
        s.get(CashAccount, till["id"]).status = "ARCHIVED"
        s.commit()
    finally:
        s.close()
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_OPERATOR_MUST_CHOOSE, blok
    assert blok["options"] == [], blok


@pytest.mark.parametrize("holat,kod", [("legacy_smena", CG.ERR_LEGACY_SHIFT_NEEDS_TILL),
                                       ("begona_filial", CG.ERR_CUSTODY_INVALID)])
def test_BLOK_BLOCKED_sababni_beradi_TANLOV_bermaydi(pg, holat, kod):
    """R4/R5 — blok sababni beradi va TANLOV KO'RSATMAYDI: bu holatlarda aniq
    hisob ham qutqarmaydi, ya'ni picker operatorni ALDAB qo'yardi."""
    S = pg
    d = _dokon(S, ikkinchi_filial=True)
    till = _hisob(S, d)
    _hisob(S, d, typ="SAFE")
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    if holat == "legacy_smena":
        _smena(S, d, till=None)
    else:
        _smena(S, d, till=_hisob(S, d, branch=d["bid2"]), branch=d["bid2"])
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_BLOCKED, blok
    assert blok["reason"] == kod, blok
    assert blok["options"] == [] and blok["resolved"] is None, blok
    # Blok bilan yozuvchi AYNI kodni beradi — ekran boshqa sabab ko'rsatmaydi.
    assert _rad(_kamaytir, S, d)[1].startswith(kod + ":")


def test_BLOK_har_YOLDA_bor_partiyasiz_qabulda_ham(pg):
    """Hujjat darajasidagi to'siqda ham blok BOR: mijoz `undefined` ni «hech
    narsa kerak emas» deb o'qimasin (`items` kalitlari bilan AYNI qoida)."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till, partiyali=False)
    _t0(S, d)
    det = _detail(S, d)
    assert det["correctable"] is False and det["correction_blocked_reason"], det
    assert det["cash_custody"]["mode"] == LC.MODE_OPERATOR_MUST_CHOOSE, det["cash_custody"]


# ═══════════════════════════════════════════════════════════════════════════
# §A.3 — OSHKORLIK CHEGARASI
# ═══════════════════════════════════════════════════════════════════════════

def test_OSHKORLIK_faqat_id_type_code_currency_ACTIVE_va_BITTA_filial(pg):
    """Tanlov ro'yxati `GET /tills` dan QAT'IY KAM oshkor qiladi.

    Ro'yxatga TUSHMAYDI: arxivlangan hisob, begona filial hisobi, begona do'kon
    hisobi. Har element AYNAN to'rt kalitdan iborat — `label`, `terminal_id`,
    `branch_id`, `status` sizib chiqmaydi."""
    S = pg
    d = _dokon(S, ikkinchi_filial=True)
    till = _hisob(S, d)
    seyf = _hisob(S, d, typ="SAFE")
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    arxiv = _hisob(S, d, status="ARCHIVED")
    begona_filial = _hisob(S, d, branch=d["bid2"])
    begona_dokon = _hisob(S, _dokon(S))
    blok = _custody(S, d)
    assert blok["mode"] == LC.MODE_OPERATOR_MUST_CHOOSE, blok
    ids = {o["id"] for o in blok["options"]}
    assert ids == {str(till["id"]), str(seyf["id"])}, blok
    for yashirin in (arxiv, begona_filial, begona_dokon):
        assert str(yashirin["id"]) not in ids, (yashirin, blok)
    for o in blok["options"]:
        assert set(o) == {"id", "type", "code", "currency"}, o
        assert o["type"] in ("TILL", "SAFE") and o["currency"] == "UZS", o
    assert {o["code"] for o in blok["options"]} == {till["code"], seyf["code"]}, blok


def test_KUZATUV_ekran_ochilishi_cash_failure_YOZMAYDI_haqiqiy_rad_YOZADI(pg, monkeypatch):
    """Ekranni ochish `cash_failure` yozmaydi — aks holda bir hujjatni o'n marta
    ochish jurnalda o'nta SOXTA «naqd o'tmadi» qoldirib, «qaysi do'konda naqd
    o'tmadi?» degan savolning javobini bo'g'ib qo'yardi. HAQIQIY rad etish esa
    avvalgidek YOZILADI (kuzatuv butunlay o'chib qolmasin)."""
    from app.services.cash import observability as _obs
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    _t0(S, d)
    yozilgan: list = []
    monkeypatch.setattr(_obs, "log_cash_failure",
                        lambda code, **kw: yozilgan.append(code))
    _custody(S, d)
    _custody(S, d)
    assert yozilgan == [], f"o'qish yo'li kuzatuv jurnalini IFLOSLADI: {yozilgan}"
    _rad(_kamaytir, S, d)
    assert yozilgan == [CG.ERR_CUSTODY_REQUIRED], \
        f"haqiqiy rad etish yozilmay qoldi — kuzatuv butunlay o'chdi: {yozilgan}"


# ═══════════════════════════════════════════════════════════════════════════
# §A.3 — PRE-T0 DA HAM DRAWER TOPILISHI SHART
#
# ⚠️  USHLANADIGAN NUQSON: blok `enforcement_active` yolg'on bo'lsa darhol
#     NOT_REQUIRED qaytarardi. Lekin T0'gacha ham naqd oyoq uchun DRAWER kerak:
#     yozuvchi hisobsiz yozganda `retrofit._shift_ctx` uni O'ZI qidiradi va
#     filialda BIR NECHTA faol TILL bo'lsa ATAYLAB hech nimani tanlamaydi
#     (branch-default YO'Q). Natijada ekran «hech narsa kerak emas» deb turar,
#     tugma bosilgach esa `LOT_CORRECTION_CASH_UNPOSTABLE` chiqardi — va
#     Manager `cash_account_id` yuborishni SO'RAMAGANI uchun qayta urinishning
#     yo'li ham yo'q edi.
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("kassalar,rejim", [(1, LC.MODE_NOT_REQUIRED),
                                            (2, LC.MODE_OPERATOR_MUST_CHOOSE)])
def test_BLOK_pre_T0_LEGACY_FALLBACK_drawer_TOPMASA_TANLOV_soraydi(pg, kassalar, rejim):
    """Ikkala FILIAL SHAKLI: yagona kassa — jim (NOT_REQUIRED); ikki kassa —
    TANLOV (OPERATOR_MUST_CHOOSE) va ko'rsatilgan tanlov HAQIQATAN ishlaydi."""
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    qoshimcha = [_hisob(S, d) for _ in range(kassalar - 1)]
    _pul(S, d, till)
    d = _qabul(S, d, account=till)          # T0 O'RNATILMAYDI — pre-cutover
    blok = _custody(S, d)
    assert blok["mode"] == rejim, blok
    assert blok["resolved"] is None, blok
    if rejim == LC.MODE_NOT_REQUIRED:
        # Legacy fallback drawer'ni ANIQ topadi — ekran hech narsa so'ramaydi
        # va hisobsiz so'rov ham o'tadi (R8 bilan AYNI holat).
        assert blok["reason"] is None and blok["options"] == [], blok
        assert _kamaytir(S, d)["ok"] is True
        return
    assert blok["reason"] == CG.ERR_CUSTODY_REQUIRED, blok
    assert sorted(o["id"] for o in blok["options"]) == sorted(
        [str(till["id"])] + [str(x["id"]) for x in qoshimcha]), blok
    # ⚠️  TANLOV «YOLG'ON» EMAS: yozuvchi pre-T0 da ham ANIQ hisobni qabul
    #     qiladi va validatsiya qiladi (R9) — ya'ni ekran ko'rsatgan yo'l bor.
    r = _kamaytir(S, d, account=till)
    assert r["ok"] is True, r
    led = [x for x in _ledger(S, d) if x[0] == "PURCHASE_RETURN"]
    assert [(x[3], x[5], x[6]) for x in led] == [("IN", str(till["id"]), QAYTIM)], led


def test_pre_T0_KOP_KASSALI_filialda_HISOBSIZ_yozuvchi_RAD_etadi(pg):
    """MANFIY NAZORAT — blok paranoyak emas: AYNI holatda yozuvchi HAQIQATAN
    rad etadi, ya'ni NOT_REQUIRED ko'rsatish EKRANNING YOLG'ONI bo'lardi.

    ⚠️  Rad etish 409 va `X-Error-Code` sarlavhasi bilan keladi (kassa gardining
        400 + prefiks konvensiyasi EMAS): bu tuzatish oqimining O'Z darvozasi —
        «kassa tegilmagan holda bajarildi deyilmaydi»."""
    from app.core import error_codes as EC
    S = pg
    d = _dokon(S)
    till = _hisob(S, d)
    _hisob(S, d)                                   # IKKINCHI faol TILL — drawer NOANIQ
    _pul(S, d, till)
    d = _qabul(S, d, account=till)
    oldin = _holat(S, d)
    with pytest.raises(HTTPException) as ei:
        _kamaytir(S, d)
    assert ei.value.status_code == 409, (ei.value.status_code, ei.value.detail)
    assert (ei.value.headers or {}).get(EC.HEADER) == EC.LOT_CORRECTION_CASH_UNPOSTABLE, (
        ei.value.headers)
    keyin = _holat(S, d)
    assert keyin == oldin, f"rad etilgan tuzatish IZ qoldirdi: {oldin} -> {keyin}"
