# -*- coding: utf-8 -*-
"""APPLY — tasdiqlangan rejani BITTA tranzaksiyada qo'llaydi. Chaqiruvchi commit/rollback qiladi.

⚠️  PHASE 5A: production bazasida (system_identifier ro'yxati) va production muhitida
    HECH QACHON ishlamaydi — `guard.assert_apply_allowed` birinchi amal. Postgres'da kutilgan
    `system_identifier` MAJBURIY va u operator ko'rib chiqqan hisobotdagi baza bilan AYNAN teng.

TARTIB (har qadam yiqilsa hech narsa yozilmaydi — chaqiruvchi ROLLBACK qiladi):
  1. darvoza (muhit + baza identiteti + ko'rib chiqilgan hisobot bazasi)
  2. do'kon qatori FOR NO KEY UPDATE (lock_timeout 120s) — parallel apply navbatga turadi
  3. ayni eksport (fayl yoki mazmun xeshi) ALLAQACHON qo'llanganmi -> AlreadyApplied (yozuvsiz);
     yangiroq (yoki teng) snapshot allaqachon qo'llanganmi -> StaleSnapshotError
  4. do'konning BARCHA mahsulot va qoldiq qatorlari (product_id, branch_id) tartibida qulflanadi —
     shundan keyin katalog o'qiladi: ko'rilgan holat va yoziladigan holat orasida oyna yo'q
  5. hisobot QAYTA hisoblanadi, operator ko'rgan xesh bilan solishtiriladi -> DriftError
  6. reja qayta quriladi va import_jobs'ga da'vo (ux_import_jobs_snapshot)
  7. yozuvlar FAQAT rejadan: identitet, narx, nom, barkod, mahsulot yaratish, QOLDIQ, o'chirish
  8. tranzaksiya ICHIDA post-tekshiruv — reja bazadan isbotlanmasa istisno

QOLDIQ SEMANTIKASI (1C yakuniy qoldig'i = BinOS ochilish qoldig'i), har (mahsulot, filial):
  · eski qoldiq != 0:  StockMovement(adjustment, ref_type='1c_cutover', reason='CUTOVER_LEGACY_CLOSE …',
                                     qty = -eski, balance_after = 0)
  · 1C qoldig'i != 0:  StockMovement(adjustment, ref_type='1c_cutover', reason='CUTOVER_OPENING_BALANCE …',
                                     qty = 1C, balance_after = 1C, unit_cost = kelish narxi)   (vaqt: yopish + 1 µs)
  · Inventory.qty = 1C — FAQAT shu harakatlar bilan birga, qator qulfi ostida.
  Eski demo/import harakatlari o'chirilmaydi va ochilish qoldig'i bilan aralashmaydi.
  `client_uuid = uuid5(job, 'kind:mahsulot:filial')` + `ux_movements_cutover_key` — BITTA job ichida
  takroriy harakat DB darajasida imkonsiz. Joblar ARO takrorni fayl/mazmun xeshi va snapshot vaqti to'sadi.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, lazyload

from app.models.catalog import Product, ProductBarcode, Unit
from app.models.enums import ImportStatus, MovementType
from app.models.imports import ImportJob
from app.models.inventory import Inventory, StockMovement
from app.models.org import Company

from . import CONTENT_HASH_VERSION, MOVEMENT_REF_TYPE, SOURCE_SYSTEM
from .bundle import Bundle, parse_ts
from .catalog import barcode_keys, is_1c_source, load_snapshot, q2, q3
from .classify import classify, snapshot_id_for
from .guard import assert_apply_allowed
from .mapping import build_plan, deterministic_product_id, movements_of

REASON = {"open": "CUTOVER_OPENING_BALANCE", "close": "CUTOVER_LEGACY_CLOSE",
          "close_missing": "CUTOVER_LEGACY_CLOSE_NOT_IN_1C"}
PATH_NAME = "1C migrator"


class AlreadyApplied(RuntimeError):
    pass


class DriftError(RuntimeError):
    pass


class StaleSnapshotError(DriftError):
    pass


class ApplyInProgress(RuntimeError):
    """Do'kon qatori boshqa apply tomonidan lock_timeout'dan uzoq ushlab turilibdi — hech narsa yozilmadi."""


class PostVerifyError(RuntimeError):
    pass


def _chunks(seq, n=900):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def reason_text(kind: str, bundle_file_sha256: str) -> str:
    return f"{REASON[kind]} · 1C export {bundle_file_sha256[:12]}"


def _company_1c_jobs(db: Session, company_id) -> list[ImportJob]:
    return [j for j in db.query(ImportJob).filter(
        ImportJob.company_id == company_id,
        ImportJob.status.in_([ImportStatus.committing, ImportStatus.committed])).all() if is_1c_source(j.source)]


def apply_migration(db: Session, bundle: Bundle, report_reviewed: dict, mapping: dict,
                    expect_system_identifier: str | None = None, actor_id=None) -> dict:
    gate = assert_apply_allowed(db, expect_system_identifier, report_reviewed.get("database"))
    is_pg = db.get_bind().dialect.name == "postgresql"
    if is_pg:
        db.execute(text("SET LOCAL lock_timeout = '120s'"))
        db.execute(text("SET LOCAL statement_timeout = '1800s'"))

    company_code = mapping.get("company_code")
    comp_q = db.query(Company).filter(Company.code == company_code, Company.deleted_at.is_(None))
    # FOR NO KEY UPDATE: ikki apply o'zaro navbatga turadi, lekin do'konga FK bilan yozuvchi oddiy
    # INSERT'lar (KEY SHARE) BLOKLANMAYDI — FOR UPDATE ular bilan deadlock xavfini tug'dirardi.
    try:
        comp = (comp_q.with_for_update(key_share=True) if is_pg else comp_q).first()
    except OperationalError as e:
        if getattr(getattr(e, "orig", None), "sqlstate", None) == "55P03":      # lock_not_available
            raise ApplyInProgress("boshqa apply ushbu do'konda ishlayapti (120 s kutildi) — tugagach qayta "
                                  "urinib ko'ring: u tugasa, ayni eksport AlreadyApplied bilan rad etiladi") from e
        raise
    if comp is None:
        raise LookupError(f"do'kon topilmadi: {company_code}")
    if is_pg:
        db.execute(text("SET LOCAL lock_timeout = '30s'"))

    # 3) takroriy / eskirgan apply — HECH QANDAY yozuvdan OLDIN
    snapshot_id = snapshot_id_for(bundle)
    snap_at = parse_ts(bundle.data["snapshot_at"], "snapshot_at")
    for j in _company_1c_jobs(db, comp.id):
        if j.snapshot_id == snapshot_id or j.content_sha256 == bundle.content_sha256:
            raise AlreadyApplied(f"bu eksport ALLAQACHON qo'llangan (job {j.id}, holat {j.status.value})")
        js = (j.column_mapping or {}).get("snapshot_at")
        if js and parse_ts(js, "job.snapshot_at") >= snap_at:
            raise StaleSnapshotError(f"eskirgan eksport: job {j.id} snapshot {js} >= {bundle.data['snapshot_at']}")

    # 4) BARCHA mahsulot va qoldiq qatorlari — sotuvlar bilan AYNI tartibda
    if is_pg:
        db.execute(select(Product.id).where(Product.company_id == comp.id)
                   .order_by(Product.id).with_for_update(key_share=True)).all()
        db.execute(select(Inventory.id).join(Product, Product.id == Inventory.product_id)
                   .where(Product.company_id == comp.id)
                   .order_by(Inventory.product_id, Inventory.branch_id)
                   .with_for_update(of=Inventory, key_share=True)).all()
    now = datetime.now(timezone.utc)                    # vaqt QULFLARDAN KEYIN

    # 5) katalog va hisobot QAYTA — operator ko'rgan holat bilan AYNAN bir xil bo'lishi shart
    snap = load_snapshot(db, company_code)
    report_now = classify(bundle, snap, report_reviewed.get("unit_names_extra") or {})
    if report_now["report_sha256"] != report_reviewed.get("report_sha256") \
            or report_now["report_sha256"] != mapping.get("report_sha256"):
        raise DriftError("katalog yoki eksport ko'rib chiqilgan hisobotdan keyin o'zgargan: "
                         f"hozir {report_now['report_sha256'][:16]}…, tasdiqlangan {str(mapping.get('report_sha256'))[:16]}…")
    plan = build_plan(report_now, mapping)

    # 6) da'vo
    job = ImportJob(
        id=uuid.uuid4(), company_id=comp.id, source=SOURCE_SYSTEM, file_name=bundle.data["export_id"],
        status=ImportStatus.committing, snapshot_id=snapshot_id,
        content_sha256=bundle.content_sha256, hash_contract_version=CONTENT_HASH_VERSION,
        mode=plan["mode"], total_rows=len(bundle.products), created_by=actor_id, created_at=now,
        applied_rows=0,
        column_mapping={"migrator": "binos-1c-v1", "bundle_file_sha256": bundle.file_sha256,
                        "report_sha256": plan["report_sha256"], "mapping_sha256": plan["mapping_sha256"],
                        "plan_sha256": plan["plan_sha256"], "catalog_fingerprint": plan["catalog_fingerprint"],
                        "approved_by": plan["approved_by"], "approved_at": plan["approved_at"],
                        "export_id": bundle.data["export_id"], "snapshot_at": snap_at.isoformat(),
                        "gate": gate})
    db.add(job)
    try:
        db.flush()
    except IntegrityError as e:
        raise AlreadyApplied("parallel apply ayni eksportni egalladi") from e

    res = _execute(db, comp.id, job, plan, now, actor_id)
    post = verify_state(db, comp.id, job.id, plan)
    if not post["ok"]:
        raise PostVerifyError(f"post-tekshiruv yiqildi: {post['failures'][:10]}")

    job.status = ImportStatus.committed
    job.committed_at = datetime.now(timezone.utc)
    job.applied_rows = len(plan["ops"])
    job.new_rows = plan["expected"]["create"]
    job.existing_rows = plan["expected"]["link"] + plan["expected"]["reactivate"]
    job.error_rows = len(plan["skipped"])
    job.column_mapping = {**job.column_mapping, "result": res, "post_verify": post, "expected": plan["expected"],
                          "plan": plan}
    from app.services.catalog_import_v2 import set_catalog_settings
    set_catalog_settings(db, comp.id, source_system=SOURCE_SYSTEM, last_import_job_id=str(job.id))
    from app.services.audit import log as audit_log
    audit_log(db, actor_id, "import", "catalog_1c_migration", job.id,
              after={"plan_sha256": plan["plan_sha256"], "bundle_file_sha256": bundle.file_sha256,
                     "system_identifier": gate.get("system_identifier"), **res})
    db.flush()
    return {"job_id": str(job.id), "plan_sha256": plan["plan_sha256"], "result": res, "post_verify": post,
            "expected": plan["expected"], "skipped": len(plan["skipped"]), "gate": gate}


def _execute(db: Session, company_id, job: ImportJob, plan: dict, now: datetime, actor_id) -> dict:
    from app.services.stock_gate import assert_untracked

    ops, deact = plan["ops"], plan["deactivate"]
    units = {u.code: u.id for u in db.query(Unit).all()}
    pid_of = {o["guid"]: (o["product_id"] or str(deterministic_product_id(job.id, o["guid"]))) for o in ops}
    existing_ids = sorted({o["product_id"] for o in ops if o["product_id"]} | {x["product_id"] for x in deact})
    touched = sorted(set(pid_of.values()) | {x["product_id"] for x in deact})

    prods: dict[str, Product] = {}
    for ch in _chunks([uuid.UUID(x) for x in existing_ids]):
        for p in (db.query(Product).options(lazyload("*"))
                  .filter(Product.company_id == company_id, Product.id.in_(ch)).all()):
            prods[str(p.id)] = p
    missing = [x for x in existing_ids if x not in prods]
    if missing:
        raise DriftError(f"rejadagi mahsulotlar topilmadi: {missing[:5]}")
    # Partiya kuzatuvli mahsulotga qoldiq yozilmaydi — MAVJUD darvoza (stock_gate) orqali.
    assert_untracked(db, [uuid.UUID(x) for x in existing_ids], PATH_NAME)
    bad = [x for x in existing_ids if prods[x].track_expiry or prods[x].lots_activated_at is not None]
    if bad:
        raise DriftError(f"partiya kuzatuvli mahsulotlar: {bad[:5]}")

    # CREATE: GUID registrsiz ham band bo'lmasligi shart (case-sensitive unique indeks buni TUTMAYDI)
    create_guids = [o["guid"] for o in ops if o["action"] == "CREATE"]
    for ch in _chunks(create_guids):
        clash = db.query(Product.id, Product.external_id).filter(
            Product.company_id == company_id, func.lower(func.trim(Product.external_id)).in_(ch)).first()
        if clash is not None:
            raise DriftError(f"yaratiladigan GUID allaqachon mahsulotda: {clash[1]} ({clash[0]})")
    # Barkodlar: GTIN variantlari bilan bazadan QAYTA — rejadan keyin paydo bo'lgan egani tutadi
    want_keys: dict[str, str] = {}
    for o in ops:
        for bc in o["barcodes_add"]:
            for k in barcode_keys(bc):
                want_keys[k] = pid_of[o["guid"]]
    for ch in _chunks(sorted(want_keys)):
        for bc, owner in db.query(ProductBarcode.barcode, ProductBarcode.product_id).filter(
                ProductBarcode.company_id == company_id, ProductBarcode.barcode.in_(ch)).all():
            if str(owner) != want_keys[bc]:
                raise DriftError(f"barkod {bc} boshqa mahsulotda ({owner})")

    acc = Counter()
    for o in ops:
        pid = pid_of[o["guid"]]
        if o["action"] == "CREATE":
            c = o["create"]
            if c["unit_code"] not in units:
                raise DriftError(f"birlik '{c['unit_code']}' BinOS'da yo'q")
            p = Product(id=uuid.UUID(pid), company_id=company_id, article_code=c["article_code"], sku=c["sku"],
                        name=c["name"], unit_id=units[c["unit_code"]],
                        base_buy_price=Decimal(o["buy_price"]) if o["buy_price"] is not None else Decimal("0"),
                        base_sell_price=Decimal(o["sell_price"]), tax_rate=0, is_weighted=bool(c["is_weighted"]),
                        plu_code=c["plu"], is_active=True, source_system=SOURCE_SYSTEM, external_id=o["guid"],
                        created_by=actor_id)
            db.add(p)
            acc["created"] += 1
        else:
            p = prods[pid]
            if o["action"] == "REACTIVATE":
                if p.deleted_at is None:
                    raise DriftError(f"{pid} o'chirilmagan — REACTIVATE rejasi eskirgan")
                p.deleted_at = None
                p.is_active = True
                if o["clear_plu"]:
                    p.plu_code = None
                acc["reactivated"] += 1
            else:
                if p.deleted_at is not None:
                    raise DriftError(f"{pid} o'chirilgan — LINK rejasi eskirgan")
                if o["activate"]:
                    p.is_active = True
                    acc["activated"] += 1
                acc["linked"] += 1
            if p.external_id is None:
                if not o["set_identity"]:
                    raise DriftError(f"{pid} identitetsiz, lekin reja identitetni kutgan")
                p.source_system, p.external_id = SOURCE_SYSTEM, o["guid"]
                acc["identity_set"] += 1
            elif not (p.source_system == SOURCE_SYSTEM and p.external_id == o["guid"]):
                raise DriftError(f"{pid} boshqa identitetga ega ({p.source_system}:{p.external_id})")
            if o["sell_price"] is not None:
                p.base_sell_price = Decimal(o["sell_price"])
                acc["prices_set"] += 1
            if o["buy_price"] is not None:
                p.base_buy_price = Decimal(o["buy_price"])
            if o["update_name"]:
                p.name = o["update_name"]
                acc["names_set"] += 1
        primary = not o["target_had_barcodes"]
        for bc in o["barcodes_add"]:
            db.add(ProductBarcode(product_id=uuid.UUID(pid), company_id=company_id, barcode=bc, is_primary=primary))
            primary = False
            acc["barcodes_added"] += 1
        acc["barcodes_skipped"] += len(o["barcodes_skipped"])
    for x in deact:
        p = prods[x["product_id"]]
        if p.deleted_at is not None:
            raise DriftError(f"{x['product_id']} o'chirilgan — reja eskirgan")
        p.is_active = False
        acc["deactivated"] += 1
    db.flush()

    # ── QOLDIQ: joriy qiymat reja kutgan eski qoldiqqa AYNAN teng bo'lishi shart ─────
    inv: dict[tuple[str, str], Inventory] = {}
    for ch in _chunks([uuid.UUID(x) for x in touched]):
        for r in db.query(Inventory).filter(Inventory.product_id.in_(ch)).all():
            inv[(str(r.product_id), str(r.branch_id))] = r
    expect_before: dict[tuple[str, str], Decimal] = {}
    for o in ops:
        for b, q in o["inventory_before"].items():
            expect_before[(pid_of[o["guid"]], b)] = Decimal(q)
    for x in deact:
        for b, q in x["inventory_before"].items():
            expect_before[(x["product_id"], b)] = Decimal(q)            # xaritalanmagan "keep" filiallar ham
    actual_before = {k: q3(r.qty) for k, r in inv.items() if q3(r.qty) != 0}
    if actual_before != expect_before:
        diff = sorted(set(actual_before.items()) ^ set(expect_before.items()))[:5]
        raise DriftError(f"qoldiq reja kutganidan farq qiladi: {diff}")

    t_close, t_open = now, now + timedelta(microseconds=1)
    totals = {"open": Decimal("0"), "close": Decimal("0"), "close_missing": Decimal("0")}
    unit_cost = {pid_of[o["guid"]]: (Decimal(o["buy_price"]) if o["buy_price"] is not None else None) for o in ops}
    finals: dict[tuple[str, str], Decimal] = {}
    for o in ops:
        for b, q in o["stock_final"].items():
            finals[(pid_of[o["guid"]], b)] = Decimal(q)
    for x in deact:
        for b in x["close"]:
            finals[(x["product_id"], b)] = Decimal("0")
    for m in movements_of(ops, deact):
        pid = pid_of[m["guid"]] if m["guid"] else m["product_id"]
        bid = m["branch_id"]
        qty = Decimal(m["qty"])
        db.add(StockMovement(id=uuid.uuid4(), product_id=uuid.UUID(pid), branch_id=uuid.UUID(bid),
                             type=MovementType.adjustment, qty=qty, balance_after=Decimal(m["balance_after"]),
                             unit_cost=unit_cost.get(pid) if m["kind"] == "open" else None,
                             ref_type=MOVEMENT_REF_TYPE, ref_id=job.id, employee_id=actor_id,
                             reason=reason_text(m["kind"], plan["bundle_file_sha256"]),
                             client_uuid=uuid.uuid5(job.id, f"{m['kind']}:{pid}:{bid}"),
                             created_at=t_open if m["kind"] == "open" else t_close))
        acc[f"movements_{m['kind']}"] += 1
        totals[m["kind"]] += abs(qty)
    for (pid, bid), target in sorted(finals.items()):
        row = inv.get((pid, bid))
        if row is None:
            row = Inventory(product_id=uuid.UUID(pid), branch_id=uuid.UUID(bid), qty=Decimal("0"), min_qty=0,
                            updated_at=t_open)
            db.add(row)
            inv[(pid, bid)] = row
        row.qty = target
        row.updated_at = t_open
        row.row_version = (row.row_version or 1) + 1
    db.flush()
    out = {k: int(v) for k, v in sorted(acc.items())}
    out.update({f"{k}_qty_total": format(v, "f") for k, v in totals.items()})
    return out


def verify_state(db: Session, company_id, job_id, plan: dict) -> dict:
    """Rejaning kutilgan holati bazada BORMI — har qiymat BAZADAN o'qiladi. Faqat o'qiydi."""
    fails: list[str] = []
    ops, deact = plan["ops"], plan["deactivate"]
    job_id = uuid.UUID(str(job_id))
    pid_of = {o["guid"]: (o["product_id"] or str(deterministic_product_id(job_id, o["guid"]))) for o in ops}

    # a) identitet: har GUID AYNAN bitta mahsulotda (registrsiz), va u reja kutgan mahsulot
    by_lower: dict[str, list] = {}
    cols = (Product.id, Product.source_system, Product.external_id, Product.deleted_at, Product.is_active,
            Product.base_sell_price, Product.base_buy_price, Product.name, Product.article_code, Product.sku,
            Product.unit_id, Product.is_weighted, Product.plu_code, Product.track_lots, Product.track_expiry,
            Product.lots_activated_at)
    for ch in _chunks([o["guid"] for o in ops]):
        for row in db.query(*cols).filter(Product.company_id == company_id,
                                          func.lower(func.trim(Product.external_id)).in_(ch)).all():
            by_lower.setdefault(row.external_id.strip().lower(), []).append(row)
    units = {str(u.id): u.code for u in db.query(Unit).all()}
    identity_ok = 0
    for o in ops:
        rows = by_lower.get(o["guid"], [])
        if len(rows) != 1:
            fails.append(f"{o['guid']}: GUID {len(rows)} ta mahsulotda")
            continue
        p = rows[0]
        want = pid_of[o["guid"]]
        if str(p.id) != want or p.source_system != SOURCE_SYSTEM or p.external_id != o["guid"]:
            fails.append(f"{o['guid']}: identitet {p.source_system}:{p.external_id} / {p.id} != reja {want}")
            continue
        if p.deleted_at is not None or not p.is_active:
            fails.append(f"{o['guid']}: mahsulot faol emas")
        if o["sell_price"] is not None and q2(p.base_sell_price) != Decimal(o["sell_price"]):
            fails.append(f"{o['guid']}: sotuv narxi {p.base_sell_price} != {o['sell_price']}")
        if o["buy_price"] is not None and q2(p.base_buy_price) != Decimal(o["buy_price"]):
            fails.append(f"{o['guid']}: kelish narxi {p.base_buy_price} != {o['buy_price']}")
        if o["update_name"] and p.name != o["update_name"]:
            fails.append(f"{o['guid']}: nom yangilanmagan")
        if o["clear_plu"] and p.plu_code is not None:
            fails.append(f"{o['guid']}: PLU tozalanmagan")
        c = o["create"]
        if c and (p.name != c["name"] or p.article_code != c["article_code"] or p.sku != c["sku"]
                  or units.get(str(p.unit_id)) != c["unit_code"] or bool(p.is_weighted) != bool(c["is_weighted"])
                  or p.plu_code != c["plu"]):
            fails.append(f"{o['guid']}: yaratilgan mahsulot maydonlari rejaga mos emas")
        if p.track_lots or p.track_expiry or p.lots_activated_at is not None:
            fails.append(f"{o['guid']}: partiya kuzatuvi yoqilgan")
        identity_ok += 1

    # b) o'chirilganlar
    deact_ids = [x["product_id"] for x in deact]
    inactive = 0
    for ch in _chunks([uuid.UUID(x) for x in deact_ids]):
        inactive += db.query(func.count(Product.id)).filter(
            Product.id.in_(ch), Product.is_active.is_(False), Product.deleted_at.is_(None)).scalar() or 0
    if inactive != len(deact_ids):
        fails.append(f"o'chirilgan (is_active=false) {inactive} != reja {len(deact_ids)}")

    # c) qoldiq: har reja juftligi bazada AYNAN yakuniy qiymatga teng; saqlangan juftliklar tegilmagan
    want_inv: dict[tuple[str, str], Decimal] = {}
    for o in ops:
        pid = pid_of[o["guid"]]
        for b, q in o["inventory_before"].items():
            want_inv[(pid, b)] = Decimal(q)                  # saqlangan (keep) filiallar — o'zgarmagan
        for b, q in o["stock_final"].items():
            want_inv[(pid, b)] = Decimal(q)
    for x in deact:
        for b, q in x["inventory_before"].items():
            want_inv[(x["product_id"], b)] = Decimal(q)                  # "keep" filiallar — o'zgarmagan
        for b in x["close"]:
            want_inv[(x["product_id"], b)] = Decimal("0")
    got: dict[tuple[str, str], Decimal] = {}
    touched = sorted({k[0] for k in want_inv} | set(pid_of.values()) | set(deact_ids))
    for ch in _chunks([uuid.UUID(x) for x in touched]):
        for pid, bid, qty in db.query(Inventory.product_id, Inventory.branch_id, Inventory.qty).filter(
                Inventory.product_id.in_(ch)).all():
            got[(str(pid), str(bid))] = q3(qty)
    mism = [(k, str(v), str(got.get(k))) for k, v in sorted(want_inv.items())
            if got.get(k, Decimal("0")) != v.quantize(Decimal("0.001"))]
    extra = [(k, str(v)) for k, v in sorted(got.items()) if k not in want_inv and v != 0]
    if mism:
        fails.append(f"qoldiq mos emas: {len(mism)} (masalan {mism[:3]})")
    if extra:
        fails.append(f"reja bilmagan nol bo'lmagan qoldiq: {len(extra)} (masalan {extra[:3]})")
    by_branch: dict[str, Decimal] = {}
    mapped = set(plan["warehouse_branch"].values())
    op_pids = set(pid_of.values())
    for (pid, b), v in got.items():
        if b in mapped and pid in op_pids:
            by_branch[b] = by_branch.get(b, Decimal("0")) + v
    exp_after = {b: Decimal(v) for b, v in plan["expected"]["stock_after_by_mapped_branch"].items()}
    if {b: v for b, v in by_branch.items() if v != 0} != {b: v for b, v in exp_after.items() if v != 0}:
        fails.append(f"filial jami (bazadan) {by_branch} != reja {exp_after}")

    # d) harakatlar: job'ning HAR harakati reja bilan AYNAN (miqdor, balans, sabab, filial)
    want_mv = Counter()
    for m in movements_of(ops, deact):
        pid = pid_of[m["guid"]] if m["guid"] else m["product_id"]
        want_mv[(pid, m["branch_id"], reason_text(m["kind"], plan["bundle_file_sha256"]),
                 str(Decimal(m["qty"]).quantize(Decimal("0.001"))),
                 str(Decimal(m["balance_after"]).quantize(Decimal("0.001"))))] += 1
    got_mv = Counter()
    for pid, bid, qty, bal, reason, rt in db.query(StockMovement.product_id, StockMovement.branch_id,
                                                   StockMovement.qty, StockMovement.balance_after,
                                                   StockMovement.reason, StockMovement.ref_type).filter(
            StockMovement.ref_id == job_id).all():
        if rt != MOVEMENT_REF_TYPE:
            fails.append(f"job harakati boshqa ref_type bilan: {rt}")
        got_mv[(str(pid), str(bid), reason, str(q3(qty)), str(q3(bal)))] += 1
    if want_mv != got_mv:
        fails.append(f"harakatlar rejaga mos emas: ortiqcha {list((got_mv - want_mv).items())[:3]}, "
                     f"yetishmaydi {list((want_mv - got_mv).items())[:3]}")

    # e) barkodlar: qo'shilganlar AYNAN rejadagi mahsulotda; o'tkazib yuborilganlar unga yozilmagan
    want_pairs = {(bc, pid_of[o["guid"]]) for o in ops for bc in o["barcodes_add"]}
    skipped_pairs = {(s["value"], pid_of[o["guid"]]) for o in ops for s in o["barcodes_skipped"]
                     if s["value"] not in o["barcodes_existing"]}
    vals = sorted({bc for bc, _ in want_pairs | skipped_pairs})
    have_pairs = set()
    for ch in _chunks(vals):
        have_pairs |= {(bc, str(pid)) for bc, pid in db.query(ProductBarcode.barcode, ProductBarcode.product_id)
                       .filter(ProductBarcode.company_id == company_id, ProductBarcode.barcode.in_(ch)).all()}
    if want_pairs - have_pairs:
        fails.append(f"barkod rejadagi mahsulotda emas: {sorted(want_pairs - have_pairs)[:3]}")
    if skipped_pairs & have_pairs:
        fails.append(f"o'tkazib yuborilgan barkod yozilgan: {sorted(skipped_pairs & have_pairs)[:3]}")

    # f) partiya kuzatuvi — do'kon bo'yicha
    tracked = db.query(func.count(Product.id)).filter(
        Product.company_id == company_id,
        (Product.track_lots.is_(True)) | (Product.track_expiry.is_(True)) | (Product.lots_activated_at.isnot(None))
    ).scalar() or 0
    if tracked:
        fails.append(f"partiya kuzatuvli mahsulot bor: {tracked}")
    return {"ok": not fails, "failures": fails, "ops_verified": identity_ok, "deactivated": inactive,
            "movements": sum(got_mv.values()), "movements_expected": sum(want_mv.values()),
            "barcode_pairs": len(want_pairs), "stock_by_mapped_branch": {b: format(v, "f") for b, v in sorted(by_branch.items())},
            "tracked_products": tracked}
