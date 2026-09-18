# -*- coding: utf-8 -*-
"""ESKI QOLDIQ YOZUVCHILARI — KUZATUVLI MAHSULOTDA FAIL-CLOSED (Phase 5D, §7).

Pilotda kuzatuvli mahsulotning omboriga FAQAT partiyani BILADIGAN ikki yo'l tegadi:
Manager kirimi (`POST /receiving/commit` + `lots`) va uni tuzatish
(`POST /receiving/{id}/corrections`). Qolgan HAR BIR yozuvchi — menejer xaridi va
uning tahriri, MOBIL shakldagi (`lots` kalitisiz) kirim, filiallararo ko'chirish,
inventarizatsiya, hisobdan chiqarish, 1C cutover qoldiq moslashtiruvi va 1C
migratori — kuzatuvli mahsulotda TO'XTAYDI. Jimgina zaxira yo'l, avto-kuzatuvni
o'chirish yoki sun'iy partiya HECH QAYERDA yo'q.

⚠️  NEGA BITTA JADVAL, NEGA HAR YO'LGA ALOHIDA FAYL EMAS. Yo'llar bitta savolga
    javob beradi: «kuzatuvli mahsulot bilan nima bo'ladi?». Javoblar bir joyda
    tursa, ular ORASIDAGI nomuvofiqlik ko'rinadi (bir yo'l 409, boshqasi 400 —
    bu ONGLI farq va §7 da asoslangan). Muhimi: yangi yozuvchi qo'shilganda uni
    jadvalga kiritish ONGLI qadam bo'ladi — §8 dagi qorovul jadvalda YO'Q
    yozuvchini QIZIL qiladi.

Har yo'l uchun IKKI o'lchov:
  · KUZATUVLI mahsulot — AYNAN shu maqom, AYNAN shu matn, AYNAN shu xato kodi
    (matn taxminan emas: rad etish operatorga NIMA QILISHNI aytadi va shu bois
    lug'atga — `serverErrorsLots.ts` — kalit bo'lib tushadi);
  · KUZATUVSIZ mahsulot — MANFIY NAZORAT: o'sha yo'l bugungidek ISHLAYDI va
    qoldiqni KUTILGANDEK siljitadi. Busiz «hamma narsani rad et» ham testdan
    o'tardi.

⚠️  HAR YO'L O'Z DO'KONIDA quriladi. Umumiy seed do'koni bo'ylab bu fayldagi
    sakkiz yo'l bir-birining hujjat raqami, katalog holati va 1C ish tarixiga
    tegib ketardi — test kodni emas, fayllar tartibini o'lchardi.
"""
from __future__ import annotations

import re
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.models.auth import Employee, Role
from app.models.catalog import Product, Unit
from app.models.enums import EmployeeStatus
from app.models.inventory import Inventory, StockBatch
from app.models.org import Branch, Company
from app.models.purchasing import Supplier
from app.services import stock_invariant as SI
from tests.migrator_1c_synth import WH_MAIN as _WH

NOW = datetime.now(timezone.utc)
TZ = "Asia/Tashkent"
V2 = "/api/v1/catalog/v2"

# ── KUTILGAN MATNLAR — SERVER KODI BILAN AYNAN ──────────────────────────────
# ⚠️  NUSXA ATAYLAB. Matnni koddan import qilsak, test matn o'zgarganini
#     KO'RMASDI: o'zgargan matn o'zgargan kutilma bilan birga kelardi va
#     operator ko'radigan jumla jimgina almashardi. Bu yerdagi nusxa —
#     «bu matn shartnoma» degan yozma qaror.


def _darvoza(yol: str) -> str:
    """`stock_gate.assert_untracked` matni (bitta kuzatuvli mahsulot uchun)."""
    return (f"«{yol}» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin 1 ta "
            f"kuzatuvli mahsulot so'raldi. Partiya-darajasidagi amalni ishlating — "
            f"qoldiqni partiyalardan ayirmasdan o'zgartirish miqdor invariantini buzardi.")


LOTS_MAJBURIY = ("partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` "
                 "MAJBURIY. Miqdor taxmin qilinmaydi.")
SANOQ_PARTIYASIZ = ("Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim "
                    "partiyalarga TAQSIMLAMAYDI.")
CHIQARISH_PARTIYASIZ = ("Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim "
                        "qaysi jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.")

# Servis qatlamidagi (HTTP'siz) yo'l uchun «maqom» o'rniga istisno SINFI yoziladi:
# 1C migratori CLI vositasi (`app/tools/migrate_1c.py`), uning HTTP javobi YO'Q.
CLI_MAQOMLAR = ("MappingError", "DriftError", "TrackedProductNotSupported")
MIGRATOR_REJA = "partiya kuzatuvi yoqilgan mahsulotlar bor — Migrator V1 ularga tegmaydi"

Javob = namedtuple("Javob", "status detail code")


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _javob(r) -> Javob:
    """HTTP javobini jadval bilan solishtiriladigan uchlikka aylantiradi."""
    try:
        detail = r.json().get("detail")
    except ValueError:                      # pragma: no cover — JSON'siz javob
        detail = r.text
    return Javob(r.status_code, detail, r.headers.get("X-Error-Code"))


# ══ DO'KON VA MAHSULOT ══════════════════════════════════════════════════════

def _dokon(filiallar: int = 1) -> dict:
    """Toza do'kon: filial(lar), `ega` xodim + token, ta'minotchi.

    Filiallar `created_at` bo'yicha ANIQ tartibda — birinchisi `deps.actor_branch`
    tanlaydigan filial, ya'ni xarid va kirim AYNAN unga yoziladi.
    """
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="5D darvoza",
                       code="d5" + uuid.uuid4().hex[:8], currency="UZS")
        db.add(comp)
        db.flush()
        bids = []
        for i in range(filiallar):
            br = Branch(id=uuid.uuid4(), company_id=comp.id, name=f"F0{i + 1}",
                        code=f"F0{i + 1}", timezone=TZ, is_active=True,
                        created_at=NOW - timedelta(days=10 - i))
            db.add(br)
            db.flush()
            bids.append(br.id)
        role = db.query(Role).filter(Role.code == "ega").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                       full_name="5D ega", phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add(emp)
        sup = Supplier(id=uuid.uuid4(), company_id=comp.id, name="5D ta'minotchi")
        db.add(sup)
        db.commit()
        tok = create_access_token(str(emp.id), {"role": "ega", "company_id": str(comp.id),
                                                "sv": 0})
        return {"cid": comp.id, "bids": bids, "eid": emp.id, "sup": sup.id,
                "H": {"Authorization": f"Bearer {tok}"}}


def _kuzatuvli_qil(db, *, cid, bid, pid, qty, unit_cost=Decimal("50.00")) -> None:
    """Mahsulotni KUZATUVLI qiladi — `/lots/enable` bilan AYNI natija.

    ⚠️  BAYROQ YOLG'IZ QO'YILMAYDI. Yoqish qoldiqqa TENG ochilish partiyasini ham
        yozadi; faqat bayroqni qo'ysak, `Inventory.qty == Σ remaining_qty`
        invarianti darhol buzilardi va keyingi rad etish DARVOZANI emas,
        buzilgan boshlang'ich holatni o'lchardi.
    """
    now = datetime.now(timezone.utc)
    q = Decimal(str(qty)).quantize(Decimal("0.001"))
    if q > 0:
        db.add(StockBatch(id=uuid.uuid4(), company_id=cid, branch_id=bid, product_id=pid,
                          qty=q, received_qty=q, remaining_qty=q, unit_cost=unit_cost,
                          status=SI.OPEN, source_type="legacy", client_uuid=uuid.uuid4(),
                          received_at=now, created_at=now, updated_at=now, row_version=1))
    p = db.get(Product, pid)
    p.track_lots = True
    p.track_expiry = False
    p.lots_activated_at = now


def _mahsulot(d: dict, *, tracked: bool, qty=0, bid=None):
    """Do'konga mahsulot qo'shadi; `tracked` bo'lsa ochilish partiyasi bilan."""
    bid = bid or d["bids"][0]
    with _db() as db:
        unit = db.query(Unit).first()
        p = Product(id=uuid.uuid4(), company_id=d["cid"],
                    name="Darvoza " + uuid.uuid4().hex[:6],
                    article_code="D-" + uuid.uuid4().hex[:10], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, branch_id=bid, qty=Decimal(str(qty)),
                         min_qty=0, updated_at=NOW))
        if tracked:
            _kuzatuvli_qil(db, cid=d["cid"], bid=bid, pid=p.id, qty=qty)
        db.commit()
        return p.id, p.name


def _qoldiq(pid, bid) -> Decimal:
    with _db() as db:
        r = (db.query(Inventory)
             .filter(Inventory.product_id == pid, Inventory.branch_id == bid).first())
        return Decimal(str(r.qty)) if r else Decimal("0")


# ══ YOZUVCHILAR ═════════════════════════════════════════════════════════════
#
# Har funksiya O'Z do'konini quradi, bitta yo'lni bir marta uradi va jadval bilan
# solishtiriladigan `Javob` qaytaradi. Kuzatuvsiz chaqiruvda u qo'shimcha ravishda
# qoldiq KUTILGANDEK siljiganini ham tekshiradi (manfiy nazorat).


def _xarid(client, tracked: bool) -> Javob:
    """`POST /purchases` — bu ham kirim, lekin `lots` maydonini BILMAYDI."""
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=tracked, qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("5.000"), "xarid qoldiqni oshirmadi"
    return _javob(r)


def _xarid_tahriri(client, tracked: bool) -> Javob:
    """`PATCH /purchases/{id}` — qoldiqni ISHORALI delta bilan siljitadi.

    ⚠️  HUJJAT KUZATUVSIZ PAYTDA yaratiladi: kuzatuvli mahsulotda `POST /purchases`
        ning o'zi 409 beradi, ya'ni tahrir yo'liga boshqacha YETIB BO'LMAYDI. Bu
        aynan real holat — kuzatuv ESKI hujjatlar ustiga yoqiladi.
    """
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=False, qty=0)
    r = client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    pur_id = r.json()["id"]
    it = client.get(f"/api/v1/purchases/{pur_id}", headers=d["H"]).json()["items"][0]
    if tracked:
        with _db() as db:
            _kuzatuvli_qil(db, cid=d["cid"], bid=d["bids"][0], pid=pid, qty=5)
            db.commit()
    # Tannarx O'ZGARMAYDI: faqat miqdor deltasi — ya'ni `_reconcile` darvozasi.
    r2 = client.patch(f"/api/v1/purchases/{pur_id}", headers=d["H"], json={
        "items": [{"id": it["id"], "qty": 2, "unit_cost": 700}]})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("2.000"), "tahrir qoldiqni tuzatmadi"
    return _javob(r2)


def _mobil_qabul(client, tracked: bool) -> Javob:
    """`POST /receiving/commit` MOBIL SHAKLDA — `lots` kaliti UMUMAN yo'q.

    ⚠️  MOBIL ILOVA (`apps/mobile`) AYNAN shu payloadni yuboradi: `lots` maydoni
        uning `api.dart` ida yo'q. Shu bois bu yerda `lots: null` emas, kalitning
        O'ZI berilmaydi — pydantic standarti `None` ni HAM qabul qiladi va ikki
        shakl ayni yo'lga tushishini ISBOTLAB qo'yish kerak.
    """
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=tracked, qty=0)
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 10, "unit_cost": 700, "unit": "dona"}],
        "supplier_id": None, "payment": "cash", "source": "manual",
        "client_uuid": str(uuid.uuid4())})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000"), "kirim qoldiqni oshirmadi"
    return _javob(r)


def _kochirish(client, tracked: bool) -> Javob:
    """`POST /inventory/transfer` — partiyani IKKI filialda ko'chirishi kerak edi."""
    d = _dokon(filiallar=2)
    pid, _nm = _mahsulot(d, tracked=tracked, qty=10, bid=d["bids"][0])
    r = client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(pid), "qty": 4}],
        "client_uuid": str(uuid.uuid4())})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("6.000")
        assert _qoldiq(pid, d["bids"][1]) == Decimal("4.000")
    return _javob(r)


def _sanoq(client, tracked: bool) -> Javob:
    """`POST /inventory/count` UMUMIY son bilan — qaysi partiya ekani aytilmagan."""
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=tracked, qty=10)
    r = client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(pid), "counted": 7}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("7.000"), "sanoq qoldiqni yozmadi"
    return _javob(r)


def _hisobdan_chiqarish(client, tracked: bool) -> Javob:
    """`POST /inventory/writeoff` partiyasiz — qaysi qadoq tashlangani NOMA'LUM."""
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=tracked, qty=10)
    r = client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
        "product_id": str(pid), "qty": 2, "reason": "brak",
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("8.000"), "chiqarish qoldiqni kamaytirmadi"
    return _javob(r)


def _cutover(client, tracked: bool) -> Javob:
    """`POST /catalog/v2/commit` (CUTOVER_REFRESH) — 1C qoldig'i MUTLAQ yoziladi.

    ⚠️  MAHSULOT 1C NING O'ZI orqali yaratiladi (INITIAL_CREATE), keyin kuzatuv
        yoqiladi: cutover moslashtiruvi FAQAT 1C bilan bog'langan mahsulotga
        tegadi, qo'lda yaratilgani bu yo'lga umuman tushmasdi.
    """
    d = _dokon()
    row = {"name": "1C tovar " + uuid.uuid4().hex[:6], "external_id": str(uuid.uuid4()),
           "sell_price": 100.0, "buy_price": 50.0, "stock": 10.0,
           "barcodes": [], "is_weighted": False}
    r0 = client.post(f"{V2}/commit", headers=d["H"], json={
        "mode": "INITIAL_CREATE", "source_system": "1c",
        "snapshot_id": "5d-" + uuid.uuid4().hex[:6], "rows": [row]})
    assert r0.status_code == 200, r0.text
    with _db() as db:
        p = db.query(Product).filter(Product.company_id == d["cid"],
                                     Product.external_id == row["external_id"]).one()
        pid = p.id
        if tracked:
            _kuzatuvli_qil(db, cid=d["cid"], bid=d["bids"][0], pid=pid, qty=10)
            db.commit()
    r = client.post(f"{V2}/commit", headers=d["H"], json={
        "mode": "CUTOVER_REFRESH", "source_system": "1c",
        "snapshot_id": "5d-" + uuid.uuid4().hex[:6], "rows": [{**row, "stock": 14.0}]})
    if not tracked:
        assert _qoldiq(pid, d["bids"][0]) == Decimal("14.000"), "cutover qoldiqni yozmadi"
    return _javob(r)


def _migrator_qur(db, tracked_oldin: bool):
    """1C migratori uchun do'kon + GUID bilan bog'langan mahsulot + eksport.

    Qaytaradi: (company_id, branch_id, product_id, bundle, report). `tracked_oldin` —
    kuzatuv KO'RIB CHIQISHDAN (classify) OLDIN yoqiladimi; bu ikki butunlay
    boshqa rad etish yo'li (§ pastdagi izohlar).

    ⚠️  ORM OBYEKTI EMAS, ID QAYTADI. `db.rollback()`/`db.commit()` obyektlarni
        eskirtiradi va sessiya yopilgach ular `DetachedInstanceError` beradi —
        test o'shanda kodni emas, o'z sessiya boshqaruvini o'lchardi.
    """
    from app.services.migrator_1c import classify as C
    from app.services.migrator_1c.catalog import load_snapshot
    from tests.migrator_1c_helpers import add_product, bundle_dict, g, load, seed_company

    comp, (br,) = seed_company(db)
    p = add_product(db, comp, br, "1C migrator tovar", guid=g(1), qty="5")
    cid, bid, pid, code = comp.id, br.id, p.id, comp.code
    if tracked_oldin:
        _kuzatuvli_qil(db, cid=cid, bid=bid, pid=pid, qty=5)
    db.commit()
    bundle = load(bundle_dict([{
        "guid": g(1), "code": None, "article": None, "name": "1C migrator tovar",
        "kind": "goods", "is_folder": False, "deletion_mark": False,
        "has_characteristics": False, "has_series": False,
        "unit": {"name": "шт", "code": "796"}, "is_weighted": None, "plu": None,
        "barcodes": [], "prices": [], "stock": [{"warehouse_guid": _WH, "qty": "9"}],
    }]))
    rep = C.classify(bundle, load_snapshot(db, code))
    db.rollback()
    return cid, bid, pid, bundle, rep


def _migrator(client, tracked: bool) -> Javob:
    """1C migratorining apply yo'li — CLI (`app/tools/migrate_1c.py`), HTTP emas.

    ⚠️  MAQOM O'RNIDA ISTISNO SINFI. Bu yo'lda operator HTTP javobi ko'rmaydi:
        vosita istisno bilan to'xtaydi va HECH NARSA yozilmaydi. Uni sun'iy
        ravishda «409» deb yozish jadvalni yolg'on qilardi.

    ⚠️  RAD ETISH `stock_gate` DAN OLDIN KELADI — VA BU TO'G'RI. Migratorda
        darvoza UCH qavat: (1) reja qurish (`mapping.build_plan`) katalog
        suratidagi `tracked_products` ni ko'rib `MappingError` beradi — operator
        AYNAN shuni ko'radi, ya'ni apply umuman boshlanmaydi; (2) ko'rib
        chiqishdan keyin kuzatuv yoqilsa hisobot xeshi o'zgaradi va apply
        `DriftError` bilan to'xtaydi (pastdagi alohida test); (3) tranzaksiya
        ichidagi `stock_gate.assert_untracked` — oxirgi chiziq. Jadvalda
        BIRINCHISI yoziladi: rad etish matni operator ko'radigan matn bo'lishi
        kerak, «kod qayerda to'xtatishni xohlaydi» degani emas.
    """
    from app.services.migrator_1c.apply import apply_migration
    from tests.migrator_1c_helpers import mapping_for

    with _db() as db:
        _cid, bid, pid, bundle, rep = _migrator_qur(db, tracked_oldin=tracked)
        m = mapping_for(rep, bid, policies={"missing_price": "keep_binos_price"})
        try:
            apply_migration(db, bundle, rep, m)
            db.commit()
        except Exception as e:                       # noqa: BLE001
            db.rollback()
            return Javob(type(e).__name__, str(e), None)
    if not tracked:
        assert _qoldiq(pid, bid) == Decimal("9.000"), "migrator qoldiqni yozmadi"
    return Javob(200, None, None)


# ══ JADVAL ══════════════════════════════════════════════════════════════════
#
# `modul` — `Inventory.qty` ni AYNAN shu yo'lda yozadigan manba fayli
# (`app/` ga nisbatan). §8 qorovuli shu ustunni qoldiq yozuvchilari ro'yxati
# bilan solishtiradi.

YOZUVCHILAR = [
    # (kalit, modul, chaqiruv, kutilgan Javob)
    ("xarid", "api/v1/purchases.py", _xarid,
     Javob(409, _darvoza("xarid (partiyasiz kirim)"), None)),
    ("xarid_tahriri", "api/v1/purchases.py", _xarid_tahriri,
     Javob(409, _darvoza("xarid tahriri"), None)),
    ("mobil_qabul", "api/v1/receiving.py", _mobil_qabul,
     Javob(400, LOTS_MAJBURIY, None)),
    ("kochirish", "api/v1/cashops.py", _kochirish,
     Javob(409, _darvoza("filiallararo ko'chirish"), None)),
    ("sanoq", "api/v1/inventory.py", _sanoq,
     Javob(400, SANOQ_PARTIYASIZ, None)),
    ("hisobdan_chiqarish", "api/v1/inventory.py", _hisobdan_chiqarish,
     Javob(400, CHIQARISH_PARTIYASIZ, None)),
    ("cutover_1c", "services/catalog_commit_v2.py", _cutover,
     Javob(400, _darvoza("1C cutover qoldiq moslashtiruvi"), None)),
    ("migrator_1c", "services/migrator_1c/apply.py", _migrator,
     Javob("MappingError", MIGRATOR_REJA, None)),
]

_IDS = [w[0] for w in YOZUVCHILAR]


@pytest.mark.parametrize("kalit,modul,chaqir,kutilgan",
                         YOZUVCHILAR, ids=_IDS)
def test_ESKI_yozuvchi_KUZATUVLIDA_rad_etadi(client, kalit, modul, chaqir, kutilgan):
    """Kuzatuvli mahsulotda har eski yo'l AYNAN shu maqom/matn/kod bilan to'xtaydi."""
    got = chaqir(client, True)
    assert got.status == kutilgan.status, f"{kalit}: {got}"
    # Matn AYNAN: ba'zi yo'llar mahsulot nomini oldiga qo'shadi (`'{nom}': ...`),
    # shu bois «ichida» tekshiruvi — lekin kutilgan jumla TO'LIQ.
    assert kutilgan.detail in (got.detail or ""), f"{kalit}: {got.detail!r}"
    assert got.code == kutilgan.code, f"{kalit}: X-Error-Code {got.code!r}"


@pytest.mark.parametrize("kalit,modul,chaqir,kutilgan",
                         YOZUVCHILAR, ids=_IDS)
def test_ESKI_yozuvchi_KUZATUVSIZDA_ISHLAYDI(client, kalit, modul, chaqir, kutilgan):
    """MANFIY NAZORAT: darvoza kuzatuvsiz oqimni QIMIRLATMAYDI.

    Chaqiruv funksiyasining O'ZI qoldiq kutilgan qiymatga siljiganini ham
    tekshiradi — «200 qaytdi» yolg'iz yetarli emas edi.
    """
    got = chaqir(client, False)
    assert got.status == 200, f"{kalit}: {got}"
    assert got.code is None, f"{kalit}: kuzatuvsiz yo'lda xato kodi {got.code!r}"


def test_MOBIL_payloadida_lots_kaliti_UMUMAN_YOQ(client):
    """Mobil shakl `lots: null` emas, kalitsiz — ikkalasi ham AYNI rad javobini oladi.

    ⚠️  Bu farq muhim: `CommitItem.lots` standarti `None`, ya'ni kalitsiz payload
        pydantic darajasida O'TADI va rad etish faqat `lot_receiving.validate_line`
        da bo'ladi. Agar kimdir kalitni MAJBURIY qilsa, mobil ilova butun hujjat
        uchun 422 (validation) olardi — bu boshqa, tarjimasiz xato sinfi.
    """
    d = _dokon()
    pid, nm = _mahsulot(d, tracked=True, qty=0)
    base = {"supplier_id": None, "payment": "cash", "source": "manual"}
    kalitsiz = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        **base, "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(pid), "qty": 3, "unit_cost": 700, "unit": "dona"}]})
    null_bilan = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        **base, "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": str(pid), "qty": 3, "unit_cost": 700, "unit": "dona",
                   "lots": None}]})
    for r in (kalitsiz, null_bilan):
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == (f"'{nm}' partiya bo'yicha kuzatiladi — har kirim "
                                      f"qatori uchun `lots` MAJBURIY. Miqdor taxmin "
                                      f"qilinmaydi.")
    assert _qoldiq(pid, d["bids"][0]) == Decimal("0.000"), "rad etilgan kirim qoldiq qoldirdi"


def test_RAD_etilgan_yol_HECH_NARSA_yozmaydi(client):
    """Rad etish COMMIT'dan OLDIN: partiya, qoldiq va hujjat IZSIZ qoladi.

    ⚠️  Ilgari boshqa yo'lda topilgan xato aynan shu edi — tekshiruv commit'dan
        KEYIN turganda operator 409 ko'rardi, buzilgan qoldiq esa bazada QOLARDI.
    """
    from app.models.purchasing import Purchase
    d = _dokon(filiallar=2)
    pid, _nm = _mahsulot(d, tracked=True, qty=10)
    oldin = _qoldiq(pid, d["bids"][0])
    with _db() as db:
        partiyalar = db.query(StockBatch).filter(StockBatch.product_id == pid).count()

    client.post("/api/v1/purchases", headers=d["H"], json={
        "supplier_id": str(d["sup"]), "status": "received",
        "items": [{"product_id": str(pid), "qty": 5, "unit_cost": 700}],
        "client_uuid": str(uuid.uuid4())})
    client.post("/api/v1/inventory/transfer", headers=d["H"], json={
        "from_branch_id": str(d["bids"][0]), "to_branch_id": str(d["bids"][1]),
        "items": [{"product_id": str(pid), "qty": 4}], "client_uuid": str(uuid.uuid4())})
    client.post("/api/v1/inventory/count", headers=d["H"], json={
        "items": [{"product_id": str(pid), "counted": 7}],
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})
    client.post("/api/v1/inventory/writeoff", headers=d["H"], json={
        "product_id": str(pid), "qty": 2, "reason": "brak",
        "branch_id": str(d["bids"][0]), "client_uuid": str(uuid.uuid4())})

    assert _qoldiq(pid, d["bids"][0]) == oldin, "rad etilgan yo'l qoldiqni siljitdi"
    assert _qoldiq(pid, d["bids"][1]) == Decimal("0"), "rad etilgan ko'chirish maqsadga yozdi"
    with _db() as db:
        assert db.query(StockBatch).filter(
            StockBatch.product_id == pid).count() == partiyalar, "partiya qo'shildi"
        assert db.query(Purchase).filter(
            Purchase.company_id == d["cid"]).count() == 0, "rad etilgan xarid hujjat qoldirdi"
        assert SI.check(db, d["cid"], [pid]).ok


def test_MIGRATOR_korib_chiqishdan_KEYIN_yoqilsa_APPLY_toxtaydi(client):
    """Ikkinchi qavat: reja toza edi, kuzatuv apply'gacha bo'lgan oynada yoqildi.

    ⚠️  AYNAN SHU OYNA XAVFLI. Operator hisobotni ko'rib chiqadi (kuzatuvli
        mahsulot YO'Q), so'ng kimdir `/lots/enable` ni bosadi, keyin apply
        yuguradi. Reja darvozasi bu holatni KO'RMAGAN. Apply katalogni QAYTA
        tasniflaydi va hisobot xeshi mos kelmagani uchun to'xtaydi — ya'ni
        qoldiq MUTLAQ yozilmaydi va tovar partiyalardan ajralmaydi.
    """
    from app.services.migrator_1c.apply import DriftError, apply_migration
    from tests.migrator_1c_helpers import mapping_for

    with _db() as db:
        cid, bid, pid, bundle, rep = _migrator_qur(db, tracked_oldin=False)
        m = mapping_for(rep, bid, policies={"missing_price": "keep_binos_price"})
        # KO'RIB CHIQISHDAN KEYIN yoqiladi — reja allaqachon tasdiqlangan.
        _kuzatuvli_qil(db, cid=cid, bid=bid, pid=pid, qty=5)
        db.commit()
        with pytest.raises(DriftError) as e:
            apply_migration(db, bundle, rep, m)
        db.rollback()
    assert "ko'rib chiqilgan hisobotdan keyin o'zgargan" in str(e.value)
    assert _qoldiq(pid, bid) == Decimal("5.000"), "to'xtagan apply qoldiqni yozdi"


def test_MIGRATOR_ICHKI_darvozasi_OXIRGI_chiziq(client):
    """Uchinchi qavat: tranzaksiya ichidagi `stock_gate` — matn va yo'l nomi.

    ⚠️  BU QAVAT ODATDA YETIB BORILMAYDI (yuqoridagi ikki darvoza oldinroq
        to'xtatadi) va aynan shuning uchun test bilan bog'lanadi: yetib
        borilmaydigan kod jimgina o'chib ketishi oson, u esa migratorning
        `Inventory.qty = target` yozuvi bilan kuzatuvli mahsulot orasidagi
        OXIRGI to'siq. Yo'l nomi moduldan OLINADI — matnni ikki joyda qo'lda
        saqlash uni jimgina ajratib yuborardi.
    """
    from app.services.migrator_1c.apply import PATH_NAME
    from app.services.stock_gate import TrackedProductNotSupported, assert_untracked
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=True, qty=5)
    with _db() as db:
        with pytest.raises(TrackedProductNotSupported) as e:
            assert_untracked(db, [pid], PATH_NAME)
    assert str(e.value) == _darvoza("1C migrator")
    assert PATH_NAME == "1C migrator"


def test_KUZATUVLI_kirim_FAQAT_partiya_bilan_otadi(client):
    """IJOBIY qutb: yagona ochiq yo'l — `lots` bilan kirim. Qolgani yopiq ekan,
    shu yo'l ROSTDAN ochiqligini ham isbotlash SHART (aks holda pilot umuman
    tovar qabul qila olmasdi va jadval buni ko'rmasdi)."""
    d = _dokon()
    pid, _nm = _mahsulot(d, tracked=True, qty=0)
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(pid), "qty": 10, "unit_cost": 700, "unit": "dona",
                   "lots": [{"qty": 10, "batch_number": "5D-1"}]}],
        "supplier_id": None, "payment": "cash", "source": "manual",
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert _qoldiq(pid, d["bids"][0]) == Decimal("10.000")
    with _db() as db:
        lots = db.query(StockBatch).filter(StockBatch.product_id == pid).all()
        assert len(lots) == 1 and lots[0].batch_no == "5D-1"
        assert SI.check(db, d["cid"], [pid]).ok


# ══ QAMROV QOROVULI — JADVALDA YO'Q YOZUVCHI QOLMASIN ═══════════════════════

def test_BARCHA_qoldiq_yozuvchilari_JADVALDA_yoki_PARTIYANI_BILADI():
    """`Inventory.qty` ni yozadigan HAR modul uchta javobdan BIRINI beradi.

    ⚠️  BU QOROVUL `test_lot_receiving.py` dagisidan KUCHLIROQ. U yerdagi sinov
        manbadan darvoza NAQSHINI izlaydi — ya'ni «kod shunday yozilgan» deydi.
        Bu yerdagi ro'yxat esa BAJARILGAN testga bog'langan: jadvaldagi modul
        yuqoridagi parametrlashda ROSTDAN chaqirilgan va rad javobi o'lchangan.
        Naqsh qolib, xulq o'zgarsa — u yerda yashil, bu yerda qizil.

    Uch javob:
      A) JADVAL       — yuqoridagi `YOZUVCHILAR` da bor, ya'ni rad etishi
                        o'lchangan;
      B) PARTIYANI BILADI — kuzatuvli mahsulot bilan ISHLAYDI va commit'dan oldin
                        `stock_invariant.assert_ok(...)` bilan qoldiq ≡ partiyalar
                        ekanini ISBOTLAYDI (yoki isbotlaydigan xizmatga topshiradi);
      C) OQLANGAN     — yangi mahsulot yaratayotganda qator ochadi (`track_lots`
                        qurilish bo'yicha `False`) yoki dev urug'i.
    Boshqa har qanday modul — QIZIL.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"

    # (C) ANIQ OQLANGAN — `test_lot_receiving.py` dagi ro'yxat bilan AYNI sabab.
    OQLANGAN = {
        "api/v1/products.py",              # faqat YANGI mahsulot + min_qty (qty=0)
        "services/catalog_import_v2.py",   # INITIAL_CREATE — yangi mahsulot
        "seed.py", "services/demo_seed.py",        # dev urug'i
    }
    # (B) PARTIYANI BILADIGAN yozuvchilar — kuzatuvli mahsulot bilan ISHLAYDI.
    #     Ro'yxatda bo'lish YETARLI EMAS: quyida har biri invariantni
    #     ISBOTLAGANI (yoki isbotlovchiga topshirgani) tekshiriladi.
    BILADI = {
        "api/v1/lots.py",                  # yoqish: ochilish partiyasi + invariant
        "api/v1/sales.py", "services/sales.py",    # FEFO taqsimoti
        "services/lot_correction.py",      # Phase 5D: teskari yozuv + o'rniga qo'yish
    }
    ISBOT = ("assert_ok(", "assert_invariant(")
    # Topshiruvchi modul: invariantni O'ZI isbotlamaydi, lekin ISBOTLAYDIGAN
    # xizmatga beradi. «Import qildim» degan so'z isbot emas — topshirilgan
    # modul quyida ALOHIDA tekshiriladi.
    TOPSHIRADI = {
        "services.lot_receiving": "services/lot_receiving.py",
        "services.lot_return": "services/lot_return.py",
        "services.lot_writeoff": "services/lot_writeoff.py",
        "services.lot_correction": "services/lot_correction.py",
    }
    # ⚠️  NAQSH `test_lot_receiving.py` dagisi bilan AYNI — ikki qorovul bir xil
    #     yozuvchilar to'plamini ko'rsin, aks holda biri ko'rgan modul ikkinchisi
    #     uchun ko'rinmas bo'lardi.
    yozuvchi = re.compile(r"\.qty\s*=\s|\.qty\s*\+=|Inventory\(")

    jadval = {w[1] for w in YOZUVCHILAR}
    topildi, qoplanmagan = set(), []
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith("models/") or rel in OQLANGAN:
            continue
        src = f.read_text(encoding="utf-8")
        if not yozuvchi.search(src):
            continue
        topildi.add(rel)
        if rel in jadval or rel in BILADI:
            continue
        # Oxirgi imkoniyat: invariantni O'ZI isbotlaydi yoki isbotlovchiga topshiradi.
        if any(g in src for g in ISBOT):
            continue
        if any(mod in src for mod in TOPSHIRADI):
            continue
        qoplanmagan.append(rel)

    assert not qoplanmagan, (
        f"qoldiq yozuvchisi jadvalda ham, partiyani biladiganlar ro'yxatida ham YO'Q: "
        f"{qoplanmagan}. Yangi yozuvchi qo'shgan bo'lsangiz — `YOZUVCHILAR` ga rad "
        f"etish satrini qo'shing (kuzatuvlida nima bo'ladi?) yoki uni partiyani "
        f"biladigan qilib yozing va `assert_ok(...)` bilan isbotlang.")

    # ESKIRGAN SATR HAM QIZIL: jadvalda nomi bor, lekin fayl endi qoldiq
    # yozmaydi (yoki umuman yo'q) — bunday satr «qoplangan» degan YOLG'ON beradi.
    eskirgan = sorted(jadval - topildi)
    assert not eskirgan, f"jadvaldagi modul endi qoldiq yozmaydi: {eskirgan}"
    eskirgan_b = sorted(BILADI - topildi)
    assert not eskirgan_b, f"«partiyani biladi» ro'yxatidagi modul qoldiq yozmaydi: {eskirgan_b}"

    # (B) ISBOT TALABI: «biladi» deb e'lon qilingan modul ROSTDAN isbotlasin.
    for rel in sorted(BILADI):
        src = (root / rel).read_text(encoding="utf-8")
        assert any(g in src for g in ISBOT) or any(m in src for m in TOPSHIRADI), \
            f"{rel} partiyani biladi deyilgan, lekin invariantni ISBOTLAMAYDI"
    # Topshirilgan modul ham isbotlasin — «topshirdim» degan so'z isbot emas.
    for mod, hedef in TOPSHIRADI.items():
        tsrc = (root / hedef).read_text(encoding="utf-8")
        assert any(g in tsrc for g in ISBOT) or "LotSelectionError" in tsrc \
            or "ReturnAttributionError" in tsrc, \
            f"{hedef} ga topshiriladi, lekin u invariantni ISBOTLAMAYDI"

    # JADVAL VA «BILADI» KESISHMASIN: bitta modul ikkalasida bo'lsa, «qoplangan»
    # degan javob qaysi biridan kelgani noaniq bo'lardi — qorovul zaiflashardi.
    # (Jadvaldagi modul kuzatuvlida ROSTDAN rad etishi o'lchangan.)
    assert not (jadval & BILADI), f"modul ikki ro'yxatda: {sorted(jadval & BILADI)}"


def test_JADVAL_har_yolni_BIR_MARTA_va_HAQIQIY_modul_bilan_yozadi():
    """Jadvalning o'zi ham nazorat ostida: takror kalit yo'q, modul MAVJUD."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    kalitlar = [w[0] for w in YOZUVCHILAR]
    assert len(set(kalitlar)) == len(kalitlar), f"jadvalda takror kalit: {kalitlar}"
    for kalit, modul, _chaqir, kutilgan in YOZUVCHILAR:
        assert (root / modul).exists(), f"{kalit}: modul yo'q — {modul}"
        assert kutilgan.status in (400, 409) or kutilgan.status in CLI_MAQOMLAR, \
            f"{kalit}: kutilmagan maqom {kutilgan.status!r}"
        assert kutilgan.detail, f"{kalit}: rad etish matni bo'sh"
