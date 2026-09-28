# -*- coding: utf-8 -*-
"""Cutover AKTYORI — atributsiya darvozasi.

NIMANI ISBOTLAYDI: cutover'ni bajaruvchi HAQIQIY, shu do'konda ISHLAYOTGAN, RUXSATLI odam
sifatida nomlanganini, va bu nom egasi kuzatib borishi mumkin bo'lgan tashqi kalit ekanini.

NIMANI ISBOTLAMAYDI: o'sha odam hozir shu yerda bo'lganini. CLI hech kimni autentifikatsiya
qilmaydi va `DATABASE_URL` ni ushlagan odam istalgan uuid'ni tera oladi. Bu — nazorat emas,
javobgarlik izi. Shu farq kodda ham, hujjatda ham ochiq yozilgan.
"""
import uuid

import pytest

from app.models.auth import Employee
from app.models.enums import EmployeeStatus
from app.models.imports import ImportJob
from app.services.migrator_1c import classify as C
from app.services.migrator_1c.actor import ActorForbidden, REQUIRED_PERMISSIONS
from app.services.migrator_1c.apply import apply_migration
from app.services.migrator_1c.catalog import load_snapshot
from tests.migrator_1c_helpers import (actor_of, bundle_dict, g, load, mapping_for, prod,
                                       seed_company)


@pytest.fixture
def db(client):
    from app.db.session import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _ready(db):
    comp, (br,) = seed_company(db)
    db.commit()
    b = load(bundle_dict([prod(g(1), "Tovar", stock=("25",))]))
    rep = C.classify(b, load_snapshot(db, comp.code))
    db.rollback()
    return comp, br, b, rep, mapping_for(rep, br.id, mode="INITIAL_CREATE")


def _jobs(db, comp):
    return db.query(ImportJob).filter(ImportJob.company_id == comp.id).count()


# ── RED: fail-closed holatlar ─────────────────────────────────────────────────────────────
def test_aktyorsiz_APPLY_boshlanmaydi(db):
    """Eng muhimi: aktyor YO'Q bo'lsa hech narsa yozilmaydi. Ilgari bu jimgina NULL bo'lardi."""
    comp, br, b, rep, m = _ready(db)
    with pytest.raises(ActorForbidden, match="MAJBURIY"):
        apply_migration(db, b, rep, m)
    db.rollback()
    assert _jobs(db, comp) == 0


def test_bosh_satr_ham_rad(db):
    comp, br, b, rep, m = _ready(db)
    with pytest.raises(ActorForbidden, match="MAJBURIY"):
        apply_migration(db, b, rep, m, actor_id="   ")
    db.rollback()


def test_UUID_bolmagan_qiymat_rad_va_ISMGA_tushmaydi(db):
    """Buzuq uuid ism/telefon bo'yicha qidirishga TUSHMAYDI — bu erkin matnli aktyorga qaytish bo'lardi."""
    comp, br, b, rep, m = _ready(db)
    with pytest.raises(ActorForbidden, match="UUID emas"):
        apply_migration(db, b, rep, m, actor_id="Cutover operatori")
    db.rollback()


def test_mavjud_bolmagan_xodim_rad(db):
    comp, br, b, rep, m = _ready(db)
    with pytest.raises(ActorForbidden, match="xodim topilmadi"):
        apply_migration(db, b, rep, m, actor_id=uuid.uuid4())
    db.rollback()
    assert _jobs(db, comp) == 0


def test_OCHIRILGAN_xodim_rad(db):
    from datetime import datetime, timezone
    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    db.get(Employee, aid).deleted_at = datetime.now(timezone.utc)
    db.flush()
    with pytest.raises(ActorForbidden, match="o'chirilgan"):
        apply_migration(db, b, rep, m, actor_id=aid)
    db.rollback()


@pytest.mark.parametrize("status", [EmployeeStatus.suspended, EmployeeStatus.terminated])
def test_FAOL_bolmagan_xodim_rad(db, status):
    """Jonli tizim tokenli xodimga qo'yadigan ayni chegara (`core/deps.py`)."""
    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    db.get(Employee, aid).status = status
    db.flush()
    with pytest.raises(ActorForbidden, match="faol emas"):
        apply_migration(db, b, rep, m, actor_id=aid)
    db.rollback()


def test_BOSHQA_dokon_xodimi_rad_va_ozga_dokon_nomi_AYTILMAYDI(db):
    """Xodim MAVJUD va FAOL, lekin boshqa ijarachida. Xato matni o'sha do'kon nomini oshkor qilmaydi."""
    comp, br, b, rep, m = _ready(db)
    other, _ = seed_company(db, code="boshqa-dokon-xyz")
    db.commit()
    alien = actor_of(db, other)
    with pytest.raises(ActorForbidden) as e:
        apply_migration(db, b, rep, m, actor_id=alien)
    db.rollback()
    msg = str(e.value)
    assert "BOSHQA do'konga" in msg
    assert "boshqa-dokon-xyz" not in msg          # o'zga ijarachining ma'lumoti chiqmaydi
    assert _jobs(db, comp) == 0


def test_RUXSATSIZ_xodim_rad(db):
    """Xodim shu do'konda va faol, lekin katalog/qoldiq yozish ruxsati yo'q."""
    from app.models.auth import Role
    comp, br, b, rep, m = _ready(db)
    bare = Role(id=uuid.uuid4(), code="m1c_ruxsatsiz", name="Ruxsatsiz")
    db.add(bare)
    db.flush()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, full_name="Ruxsatsiz xodim",
                   role_id=bare.id, status=EmployeeStatus.active)
    db.add(emp)
    db.flush()
    with pytest.raises(ActorForbidden) as e:
        apply_migration(db, b, rep, m, actor_id=emp.id)
    db.rollback()
    assert "ruxsat yetishmaydi" in str(e.value)
    for code in REQUIRED_PERMISSIONS:
        assert code in str(e.value)


# ── GREEN: atributsiya HAQIQATAN yoziladi ─────────────────────────────────────────────────
def test_TORTTA_maydon_ham_aktyor_bilan_toladi(db):
    """Ilgari to'rttasi ham NULL edi — shu sababli cutover audit jurnalida ko'rinmasdi."""
    from app.models.catalog import Product
    from app.models.inventory import StockMovement
    from app.models.sync import AuditLog

    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    apply_migration(db, b, rep, m, actor_id=aid)
    db.commit()

    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    assert job.created_by == aid, "import_jobs.created_by"

    audit = (db.query(AuditLog)
             .filter(AuditLog.entity == "catalog_1c_migration",
                     AuditLog.entity_id == job.id).one())
    assert audit.actor_id == aid, "audit_log.actor_id"
    assert audit.entity_id == job.id

    prods = db.query(Product).filter(Product.company_id == comp.id).all()
    assert prods and all(p.created_by == aid for p in prods), "products.created_by"

    movs = (db.query(StockMovement).join(Product, Product.id == StockMovement.product_id)
            .filter(Product.company_id == comp.id).all())
    assert movs and all(mv.employee_id == aid for mv in movs), "stock_movements.employee_id"


def test_aktyor_XODIMGA_hal_boladi_nafaqat_saqlanadi(db):
    """Yozilgan qiymat — `employees.id` ga tashqi kalit, ya'ni egasi kimligini SO'RASHI mumkin."""
    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    apply_migration(db, b, rep, m, actor_id=aid)
    db.commit()
    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    emp = db.get(Employee, job.created_by)
    assert emp is not None and emp.company_id == comp.id
    assert emp.full_name == "Cutover operatori"


def test_MATN_shaklidagi_uuid_ham_qabul(db):
    """CLI argumenti matn bo'lib keladi."""
    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    apply_migration(db, b, rep, m, actor_id=str(aid))
    db.commit()
    assert _jobs(db, comp) == 1


# ── AUDIT JURNALIDA KO'RINISH — API javobi bo'yicha, jadvaldagi qator bo'yicha EMAS ────────
def test_cutover_AUDIT_JURNALIDA_korinadi(client, db):
    """⚠️ Bu darvozaning butun ma'nosi. Ilgari cutover `actor_id=NULL` bilan yozilar edi va
    `/audit` INNER JOIN tufayli uni HECH QACHON ko'rsatmasdi.

    Tekshiruv AYNAN API javobi bo'yicha: jadvalda qator borligi yetarli emas, egasi uni
    ekranda ko'rishi kerak."""
    from app.core.security import create_access_token
    from app.models.auth import Employee, Permission, Role, RolePermission

    comp, br, b, rep, m = _ready(db)
    aid = actor_of(db, comp)
    apply_migration(db, b, rep, m, actor_id=aid)

    # Jurnalni o'qiydigan xodim: `hisobot.view` ruxsati bilan.
    perm = db.query(Permission).filter(Permission.code == "hisobot.view").first()
    if perm is None:
        perm = Permission(id=uuid.uuid4(), code="hisobot.view", module="hisobot", description="x")
        db.add(perm); db.flush()
    role = db.query(Role).filter(Role.code == "m1c_kuzatuvchi").first()
    if role is None:
        role = Role(id=uuid.uuid4(), code="m1c_kuzatuvchi", name="Kuzatuvchi")
        db.add(role); db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    viewer = Employee(id=uuid.uuid4(), company_id=comp.id, full_name="Ega",
                      role_id=role.id, status=EmployeeStatus.active)
    db.add(viewer)
    db.commit()

    tok = create_access_token(str(viewer.id), {"role": role.code,
                                               "company_id": str(comp.id),
                                               "sv": getattr(viewer, "sec_epoch", 0) or 0})
    r = client.get("/api/v1/audit?limit=50", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["entity"] == "catalog_1c_migration"]
    assert rows, f"cutover jurnalda YO'Q: {[x['entity'] for x in r.json()]}"
    row = rows[0]
    assert row["actor"] == "Cutover operatori"          # kim qilgani KO'RINADI
    assert row["entity_label"] == "1C migratsiyasi"     # xom slug emas
    assert row["action_label"] == "ko'chirdi"
    job = db.query(ImportJob).filter(ImportJob.company_id == comp.id).one()
    assert row["entity_id"] == str(job.id)              # jobga bog'lanish kaliti
