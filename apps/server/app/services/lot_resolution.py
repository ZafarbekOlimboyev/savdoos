# -*- coding: utf-8 -*-
"""QARZNI YOPISH (Phase 4A) — O'ZGARMAS BUXGALTERIYA HODISASI.

NIMA O'ZGARDI VA NEGA
=====================
Phase 3 da yopish ikki narsani JOYIDA o'zgartirardi: `lot_shortfalls`
hisoblagichlarini va `sale_item_lot_allocations` ni — ya'ni SOTUV SURATINI.
Og'ish esa faqat `resolved_cost − resolved_qty × unit_cost` ayirmasi edi:

  · QACHON tan olingani yo'q — hisobot og'ishni davrga yig'olmasdi;
  · qisman yopishlar orasida qanday taqsimlangani yo'q;
  · tarixiy sotuv qatori jimgina «to'ldirilardi».

Endi har yopish QATORI — `lot_shortfall_resolutions` dagi o'zgarmas hodisa.
Sotuv surati (`SaleItem`, `sale_item_lot_allocations`) TEGILMAYDI.

IKKI TUR
========
  real     — tovar HAQIQATAN X partiyadan ketgan edi. X kamayadi,
             og'ish = a·q − (kumulyativ taxmin ulushi).
  netting  — qarzning o'zi QAYTIB KELGAN (U partiya, `return_item_shortfall_
             allocations` orqali AYNAN shu qarzga bog'langan). U kamayadi,
             og'ish 0 — tovar hech qayerdan «topilmadi», u o'z qarzini yopdi.

CHEGARALAR (hammasi qarz qulfi ostida)
======================================
  Σq                        ≤ qty − resolved_qty
  netting (U bo'yicha)      ≤ U.remaining_qty
  real (Σ)                  ≤ (qty − resolved_qty) − o'z_U_qoldig'i
      ⚠️  Qaytib kelgan tovar javonda turgan ekan, uni «X dan ketgan» deb yopish
          uni IKKI MARTA sanardi: bir marta U partiyada, bir marta X ning
          kamayishida. Avval U netlanadi.

KUMULYATIV YAXLITLASH
=====================
    prov_k = round2(p·(oldin + q)) − round2(p·oldin)

Qarz to'liq yopilganda Σprov == round2(p·qty) == chekdagi taxmin (sotuv
`lot_fefo.shortfall_cost` AYNAN shunday yaxlitlaydi). Har qatorni alohida
yaxlitlash (round2(p·q)) 3 xonali miqdorda tiyinlar yig'ilib, taxmin hech
qachon AYNAN teskari qilinmasdi.

QULF TARTIBI (global, sotuv / qaytarish bilan bir xil)
=====================================================
    ota qatorlar FOR KEY SHARE -> Inventory FOR UPDATE -> qarz FOR UPDATE
    -> partiyalar FOR UPDATE (id tartibida) -> hodisa INSERT'lari

⚠️  Ota qatorlar NEGA OLDINDAN KEY SHARE. Hodisa INSERT'i FK orqali ota qatorga
    KEY SHARE oladi. Agar u Inventory qulfidan KEYIN birinchi marta olinsa,
    ota qatorni FOR UPDATE ushlab turgan boshqa tranzaksiya bilan qulf
    halqasi tug'ilishi mumkin (Phase 2.5 darsi). `create_sale` ham ota
    qatorlarni sotuv INSERT'ida — Inventory'dan OLDIN — oladi.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import (RESOLUTION_NETTING, RESOLUTION_REAL, Inventory,
                                  LotShortfall, LotShortfallResolution,
                                  LotShortfallResolutionRequest,
                                  ReturnItemResolutionAllocation,
                                  ReturnItemShortfallAllocation, StockBatch)
from app.services import stock_invariant as SI

Q = Decimal("0.001")
C = Decimal("0.01")
MAX_LINES = 50


class ResolutionError(Exception):
    """HTTP holati bilan rad etish — API qatlami `HTTPException` ga o'giradi."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def q3(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(Q, rounding=ROUND_HALF_UP)


def c2(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(C, rounding=ROUND_HALF_UP)


def cumulative_share(unit: Decimal, before: Decimal, q: Decimal) -> Decimal:
    """`round2(unit·(oldin+q)) − round2(unit·oldin)` — teleskopik ulush."""
    return c2(unit * (before + q)) - c2(unit * before)


# ══ QARZ BO'YICHA HOSILA HISOB ═════════════════════════════════════════════

@dataclass
class Book:
    """Bitta qarzning hodisalardan yig'ilgan holati (qarz qulfi ostida o'qiladi)."""
    events_qty: Decimal = Decimal("0")
    events_actual: Decimal = Decimal("0")
    resolved_real: Decimal = Decimal("0")
    resolved_net: Decimal = Decimal("0")
    returned_tail: Decimal = Decimal("0")        # Σ return_item_shortfall_allocations
    own_u_ids: set = field(default_factory=set)
    own_u_remaining: Decimal = Decimal("0")
    legacy: bool = False

    def tail_cap(self, sf) -> Decimal:
        """Qarz DUMIdan hali qaytarilishi mumkin bo'lgan miqdor.

        ⚠️  Phase 3.6 da bu `qty − resolved_qty` edi va `returned_qty` ni
            HISOBGA OLMASDI: dumdan qaytgan tovar qayta-qayta qaytarilishi
            mumkin edi (mahsulot chegarasi boshqa qatorlar hisobiga ruxsat
            bersa). Endi qaytgan dum AYIRILADI.

        LEGACY (Phase 4A dan oldingi, hodisasiz) qarzda yopilgan miqdor
        `sale_item_lot_allocations` ga QO'SHILGAN edi — ya'ni u qaytarishning
        1-bosqichida (asl taqsimot) qaytadi; dumdan esa `resolved_qty` ayiriladi.
        """
        if self.legacy:
            return q3(sf.qty) - q3(sf.resolved_qty) - q3(sf.returned_qty)
        return q3(sf.qty) - self.resolved_real - self.returned_tail


def book(db: Session, sf) -> Book:
    b = Book()
    for kind, qty, act in db.execute(
            select(LotShortfallResolution.kind,
                   func.coalesce(func.sum(LotShortfallResolution.qty), 0),
                   func.coalesce(func.sum(LotShortfallResolution.actual_cost), 0))
            .where(LotShortfallResolution.shortfall_id == sf.id)
            .group_by(LotShortfallResolution.kind)).all():
        if kind == RESOLUTION_REAL:
            b.resolved_real += q3(qty)
        else:
            b.resolved_net += q3(qty)
        b.events_actual += c2(act)
    b.events_qty = b.resolved_real + b.resolved_net
    b.returned_tail = q3(db.execute(
        select(func.coalesce(func.sum(ReturnItemShortfallAllocation.qty), 0))
        .where(ReturnItemShortfallAllocation.shortfall_id == sf.id)).scalar())
    for bid, rem, status in db.execute(
            select(StockBatch.id, StockBatch.remaining_qty, StockBatch.status)
            .join(ReturnItemShortfallAllocation,
                  ReturnItemShortfallAllocation.created_batch_id == StockBatch.id)
            .where(ReturnItemShortfallAllocation.shortfall_id == sf.id)).all():
        b.own_u_ids.add(bid)
        if status in SI.QUANTITY_BEARING:
            b.own_u_remaining += q3(rem)
    # ⚠️  LEGACY SHAKL. Hisoblagichlar hodisalar bilan MOS KELMASA, qarzning bir
    #     qismi Phase 4A dan oldin (hodisasiz) o'zgargan: yopish sotuv suratiga
    #     yozilgan yoki qaytgan dumning U partiyasi qarzga BOG'LANMAGAN. Bunday
    #     qarzda netting va real chegarasini ISBOTLAB bo'lmaydi.
    b.legacy = (q3(sf.resolved_qty) != b.events_qty
                or q3(sf.returned_qty) != b.returned_tail
                or c2(sf.resolved_cost) != b.events_actual)
    return b


def variance_totals(db: Session, shortfall_ids) -> dict:
    """{shortfall_id: (tan_olingan, qaytarilgan)} — faqat `real` hodisalar."""
    ids = list(shortfall_ids)
    if not ids:
        return {}
    out = {i: [Decimal("0"), Decimal("0")] for i in ids}
    for sid, v in db.execute(
            select(LotShortfallResolution.shortfall_id,
                   func.coalesce(func.sum(LotShortfallResolution.variance), 0))
            .where(LotShortfallResolution.shortfall_id.in_(ids),
                   LotShortfallResolution.kind == RESOLUTION_REAL)
            .group_by(LotShortfallResolution.shortfall_id)).all():
        out[sid][0] = c2(v)
    for sid, v in db.execute(
            select(LotShortfallResolution.shortfall_id,
                   func.coalesce(func.sum(ReturnItemResolutionAllocation.variance_reversed), 0))
            .join(LotShortfallResolution,
                  LotShortfallResolution.id == ReturnItemResolutionAllocation.resolution_id)
            .where(LotShortfallResolution.shortfall_id.in_(ids))
            .group_by(LotShortfallResolution.shortfall_id)).all():
        out[sid][1] = c2(v)
    return {k: (v[0], v[1]) for k, v in out.items()}


# ══ SO'ROV ═════════════════════════════════════════════════════════════════

def normalize_lines(lines) -> list[tuple[uuid.UUID, Decimal]]:
    """[(partiya, miqdor)] — 3 xonadan ortiq kasr va takroriy partiya RAD."""
    if not lines:
        raise ResolutionError(400, "Yopish qatorlari bo'sh")
    if len(lines) > MAX_LINES:
        raise ResolutionError(400, f"Bir so'rovda ko'pi bilan {MAX_LINES} ta qator")
    out, seen = [], set()
    for bid, qty in lines:
        d = Decimal(str(qty))
        if d <= 0:
            raise ResolutionError(400, "Yopish miqdori musbat bo'lishi shart")
        if d != d.quantize(Q):
            raise ResolutionError(400, "Miqdor ko'pi bilan 3 xona kasrli bo'lishi mumkin")
        if bid in seen:
            raise ResolutionError(400, "Bitta partiya bir so'rovda faqat bir marta keladi")
        seen.add(bid)
        out.append((bid, q3(d)))
    return out


def request_hash(shortfall_id, lines) -> str:
    canon = json.dumps({"shortfall_id": str(shortfall_id),
                        "lines": sorted([str(b), str(q)] for b, q in lines)},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def _visible(db: Session, emp, branch_id) -> bool:
    from app.core.deps import visible_branches
    vb = visible_branches(emp, db)
    return vb is None or branch_id in vb


def _current(db: Session, shortfall_id) -> dict:
    r = db.execute(select(LotShortfall.qty, LotShortfall.resolved_qty, LotShortfall.resolved_at)
                   .where(LotShortfall.id == shortfall_id)).first()
    if r is None:
        return {}
    return {"resolved_qty": float(q3(r[1])), "open_qty": float(q3(r[0]) - q3(r[1])),
            "closed": r[2] is not None}


def _replay(db: Session, emp, shortfall_id, client_uuid, h):
    hdr = db.execute(select(LotShortfallResolutionRequest).where(
        LotShortfallResolutionRequest.company_id == emp.company_id,
        LotShortfallResolutionRequest.client_uuid == client_uuid)).scalar_one_or_none()
    if hdr is None:
        return None
    if hdr.shortfall_id != shortfall_id or hdr.request_hash != h:
        raise ResolutionError(
            409, "Bu client_uuid BOSHQA yopish so'rovida ishlatilgan — takror emas. "
                 "Yangi so'rov uchun yangi client_uuid bering.")
    br = db.execute(select(LotShortfall.branch_id)
                    .where(LotShortfall.id == shortfall_id)).scalar()
    if br is None or not _visible(db, emp, br):
        raise ResolutionError(404, "Qarz topilmadi")
    try:
        stored = json.loads(hdr.response_json or "null")
    except ValueError:
        stored = None
    if not isinstance(stored, dict):
        raise ResolutionError(409, "Yopish so'rovi yakunlanmagan — qayta urinib ko'ring")
    return {**stored, "duplicate": True, "current": _current(db, shortfall_id)}


def _key_share(db: Session, model, pk) -> None:
    if pk is None:
        return
    db.execute(select(model.id).where(model.id == pk)
               .with_for_update(read=True, key_share=True))


def summary(db: Session, sf) -> dict:
    rec, rev = variance_totals(db, [sf.id]).get(sf.id, (Decimal("0"), Decimal("0")))
    return {
        "resolved_qty": float(q3(sf.resolved_qty)),
        "open_qty": float(q3(sf.qty) - q3(sf.resolved_qty)),
        "resolved_cost": float(c2(sf.resolved_cost)),
        "cogs_variance_recognised": float(rec),
        "cogs_variance_reversed": float(rev),
        "cogs_variance_net": float(rec - rev),
        # Ortga moslik: Phase 3 javobidagi kalit — endi hodisalardan (sof).
        "cogs_variance": float(rec - rev),
        "closed": sf.resolved_at is not None,
    }


def resolve(db: Session, emp, shortfall_id, lines, *, reason: str, client_uuid) -> dict:
    """Qarzni yopadi. Muvaffaqiyatda COMMIT qiladi; rad etishda `ResolutionError`."""
    from app.models.auth import Employee
    from app.models.catalog import Product
    from app.models.org import Branch, Company
    from app.models.sales import SaleItem
    from app.services.audit import log as audit_log
    from app.services.lot_fefo import is_provisional

    lines = normalize_lines(lines)
    h = request_hash(shortfall_id, lines)

    # 0) TAKROR — qulfsiz tez yo'l.
    dup = _replay(db, emp, shortfall_id, client_uuid, h)
    if dup is not None:
        return dup

    # 1) Qarz sarlavhasi — Core so'rov (ORM obyekti identity map'da ESKIRIB qolmasin).
    head = db.execute(select(LotShortfall.company_id, LotShortfall.branch_id,
                             LotShortfall.product_id, LotShortfall.sale_item_id)
                      .where(LotShortfall.id == shortfall_id)).first()
    if head is None or head.company_id != emp.company_id:
        raise ResolutionError(404, "Qarz topilmadi")
    # Filial izolyatsiyasi — boshqa filial qarzi mavjudligi ham bilinmasin (IDOR).
    if not _visible(db, emp, head.branch_id):
        raise ResolutionError(404, "Qarz topilmadi")

    # 2) Ota qatorlar KEY SHARE — Inventory qulfidan OLDIN (modul izohi).
    _key_share(db, Company, emp.company_id)
    _key_share(db, Branch, head.branch_id)
    _key_share(db, Product, head.product_id)
    _key_share(db, SaleItem, head.sale_item_id)
    _key_share(db, Employee, emp.id)

    # 3) Inventory — global tartibning BOSHI.
    inv = (db.query(Inventory)
           .filter(Inventory.product_id == head.product_id,
                   Inventory.branch_id == head.branch_id)
           .with_for_update().first())
    if inv is None:
        raise ResolutionError(409, "Qarzning qoldiq qatori topilmadi — yopib bo'lmaydi")

    # 4) Qarz — YANGI hisoblagichlar bilan (populate_existing).
    sf = (db.query(LotShortfall).filter(LotShortfall.id == shortfall_id)
          .with_for_update().populate_existing().one())

    # 4b) TAKROR — QULF OSTIDA QAYTA. Birinchi so'rov hali commit bo'lmagan
    #     paytda kelgan takror 0-qadamda sarlavhani ko'rmaydi va Inventory'da
    #     navbatga turadi. Qulfni olganida birinchisi COMMIT bo'lgan: hisoblagichlar
    #     yangi (ochiq qarz 0) va chegaralar uni 400 bilan RAD etardi — operatorga
    #     «yopilmadi» deyilardi, holbuki yopilgan. Shu bois chegaralardan OLDIN.
    dup = _replay(db, emp, shortfall_id, client_uuid, h)
    if dup is not None:
        db.rollback()
        return dup

    # 5) Hosila hisob va chegaralar.
    bk = book(db, sf)
    if bk.legacy:
        raise ResolutionError(
            409, "Bu qarz Phase 4A dan oldin hodisasiz o'zgargan (legacy shakl) — "
                 "avtomatik yopib bo'lmaydi. Operator ko'rib chiqishi kerak.")
    open_qty = q3(sf.qty) - q3(sf.resolved_qty)
    total = sum((q for _b, q in lines), Decimal("0"))
    if total > open_qty:
        raise ResolutionError(
            400, f"Yopilmagan qarz {open_qty}, so'ralgan {total} — ortiqcha yopib bo'lmaydi")

    # 6) Partiyalar — kompaniya/mahsulot/filial filtri bilan, id tartibida.
    ids = sorted({b for b, _q in lines}, key=str)
    locked = (db.query(StockBatch)
              .filter(StockBatch.id.in_(ids), StockBatch.company_id == emp.company_id,
                      StockBatch.product_id == sf.product_id,
                      StockBatch.branch_id == sf.branch_id)
              .order_by(StockBatch.id).with_for_update().populate_existing().all())
    batches = {b.id: b for b in locked}
    if len(batches) != len(ids):
        raise ResolutionError(
            400, "Partiya topilmadi yoki boshqa mahsulot/filialga tegishli")
    kinds: list[str] = []
    real_total = Decimal("0")
    for bid, q in lines:
        b = batches[bid]
        if b.status not in SI.QUANTITY_BEARING:
            raise ResolutionError(400, f"Partiya holati '{b.status}' — unga yopib bo'lmaydi")
        if q3(b.remaining_qty) < q:
            raise ResolutionError(
                400, f"Partiyada yetarli qoldiq yo'q ({q3(b.remaining_qty)} < {q}) — "
                     f"jismoniy partiya MANFIYGA tushmaydi")
        if b.id in bk.own_u_ids:
            kinds.append(RESOLUTION_NETTING)
        elif is_provisional(b):
            raise ResolutionError(
                400, "Taxminiy (atributsiyasiz) partiya BOSHQA qarzniki — unga yopib "
                     "bo'lmaydi: bu taxminni haqiqiy narx deb e'lon qilardi")
        else:
            kinds.append(RESOLUTION_REAL)
            real_total += q
    real_cap = max(Decimal("0"), open_qty - bk.own_u_remaining)
    if real_total > 0 and real_total > real_cap:
        raise ResolutionError(
            400, f"Bu qarzdan qaytib kelgan {bk.own_u_remaining} dona javonda turibdi — "
                 f"avval o'sha (atributsiyasiz) partiyani netlang. Haqiqiy partiyaga "
                 f"ko'pi bilan {real_cap} yopiladi")

    # 7) Sarlavha — idempotentlikning TRANZAKSION kafolati.
    now = datetime.now(timezone.utc)     # BARCHA qulflardan KEYIN
    req = LotShortfallResolutionRequest(
        id=uuid.uuid4(), company_id=emp.company_id, client_uuid=client_uuid,
        shortfall_id=sf.id, request_hash=h, employee_id=emp.id, created_at=now)
    db.add(req)
    try:
        # ⚠️  ANIQ flush: sarlavha hodisalardan OLDIN bazaga tushadi (SQLAlchemy
        #     aloqasi yo'q jadvallarni tasodifiy tartibda yozadi — Phase 2 darsi),
        #     va noyob indeks to'qnashuvi AYNAN shu qadamda chiqadi.
        db.flush()
    except IntegrityError:
        # ⚠️  Cheklov NOMIGA tayanilmaydi (SQLite'da `diag` yo'q; draft bazada
        #     ayni ustunlarda boshqa nomli indeks bo'lishi mumkin). Savol bitta:
        #     shu `client_uuid` sarlavhasi endi BORmi?
        db.rollback()
        dup = _replay(db, emp, shortfall_id, client_uuid, h)
        if dup is not None:
            return dup
        raise

    # 8) Hodisalar — so'rov tartibida, kumulyativ yaxlitlash bilan.
    p = c2(sf.unit_cost)
    before = q3(sf.resolved_qty)
    events: list[LotShortfallResolution] = []
    act_total = Decimal("0")
    for n, ((bid, q), kind) in enumerate(zip(lines, kinds)):
        b = batches[bid]
        prov = cumulative_share(p, before, q)
        a = c2(b.unit_cost)
        act = prov if kind == RESOLUTION_NETTING else c2(a * q)
        b.remaining_qty = q3(b.remaining_qty) - q
        b.updated_at = now
        if q3(b.remaining_qty) == 0:
            b.status = SI.DEPLETED
        ev = LotShortfallResolution(
            id=uuid.uuid4(), request_id=req.id, line_no=n, kind=kind,
            company_id=emp.company_id, branch_id=sf.branch_id, product_id=sf.product_id,
            shortfall_id=sf.id, sale_item_id=sf.sale_item_id, stock_batch_id=b.id,
            expiry_date=b.expiry_date, qty=q, provisional_unit_cost=p, actual_unit_cost=a,
            provisional_cost=prov, actual_cost=act, variance=act - prov,
            resolved_at=now, employee_id=emp.id, created_at=now)
        db.add(ev)
        events.append(ev)
        before += q
        act_total += act

    # 9) Hisoblagichlar (kesh). Invariant ta'rifi O'ZGARMAYDI: qarz = qty − resolved_qty.
    sf.resolved_qty = q3(sf.resolved_qty) + total
    sf.resolved_cost = c2(sf.resolved_cost) + act_total
    if q3(sf.qty) - q3(sf.resolved_qty) <= 0:
        sf.resolved_at = now
    db.flush()

    # 10) YAKUNIY DARVOZA — commit'dan OLDIN.
    try:
        SI.assert_ok(db, emp.company_id, [sf.product_id])
    except Exception as e:      # noqa: BLE001
        db.rollback()
        raise ResolutionError(409, f"Qarzni yopib bo'lmadi — invariant buzilardi: {e}") from e

    resp = {"ok": True, "shortfall_id": str(sf.id), "request_id": str(req.id),
            "resolution_ids": [str(e.id) for e in events],
            "kinds": [e.kind for e in events],
            "qty_now": float(total),
            "variance_now": float(sum((e.variance for e in events), Decimal("0"))),
            **summary(db, sf)}
    req.response_json = json.dumps(resp, sort_keys=True)
    first = events[0]
    audit_log(db, emp.id, "update", "lot_shortfall_resolve", sf.id,
              after={"request_id": str(req.id), "client_uuid": str(client_uuid),
                     "stock_batch_id": str(first.stock_batch_id), "qty": float(total),
                     "reason": reason,
                     "lines": [{"stock_batch_id": str(e.stock_batch_id), "kind": e.kind,
                                "qty": float(e.qty), "actual_cost": float(e.actual_cost),
                                "provisional_cost": float(e.provisional_cost),
                                "variance": float(e.variance)} for e in events],
                     "variance": resp["variance_now"],
                     "batch_unit_cost": float(first.actual_unit_cost),
                     "provisional_unit_cost": float(p)})
    db.commit()
    return {**resp, "duplicate": False}
