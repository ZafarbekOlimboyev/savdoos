# -*- coding: utf-8 -*-
"""`POST /reports/history/seed` — KUCHAYTIRISH va KO'P-FILIAL VAQT NUQSONI.

NEGA BU MARSHRUT O'CHIRILMADI (o'lchangan)
==========================================
`Sale(` butun ilovada IKKI joyda quriladi: kanonik yozuvchi
(`services/sales.py:451`) va shu marshrut (`api/v1/reports.py`). Va
`cost_basis=` FAQAT shu marshrutda yoziladi. P&L provenans chelaklari esa uni
o'qiydi (`reports.py:284-293`), ya'ni marshrutni o'chirish
`COST_BASIS_ESTIMATED` ni NOL ishlab chiqaruvchi bilan qoldirardi va 162
qatorli regressiya harness'i ma'nosiz bo'lardi. Shu bois: o'chirish emas,
KUCHAYTIRISH.

NIMA O'ZGARDI
=============
Ilgari: `require("sozlamalar.edit")` — ya'ni shu ruxsat berilgan xodim JONLI
do'konda CHEKSIZ chuqurlikda orqaga sanalgan `Sale` + `SalePayment` yozardi:
tovar qatorlarisiz, inventar harakatisiz, naqd ledger oyog'isiz, audit izisiz.
Endi: vendor kaliti (avtorizatsiya) + `assert_demo_tenant` (doira) +
ANIQ ko'rsatilgan filial/aktor (determinizm) + audit izi.

⚠️  OQIBAT, OCHIQ AYTILADI: marshrut endi FAQAT demo/test kodli do'konda
    ishlaydi. Jonli 1C cutover uchun undan foydalanib bo'lmaydi. Hozirgi reja
    bunga qarshi emas (pilot YANGI toza tenantdan boshlanadi), lekin bu ongli
    qaror va jimgina sodir bo'lmagan.

⚠️  BU MARSHRUTNI YOPISH INVARIANTNI TO'LIQ O'RNATMAYDI. `POST /sync/push`
    `require("kassa.sell")` — ya'ni KASSIR ruxsati — bilan ochiq va
    `create_sale(at=_clamp_sold_at(sold_at))` chaqiradi; clamp oynasi
    `[hozir-60kun, +5daq]` (`api/v1/sync.py:30-40,89`). Ya'ni oddiy kassir
    hamon 60 kungacha orqaga sanalgan sotuv yozadi — bu ATAYLAB qurilgan
    offline-replay kontrakti va u O'ZGARTIRILMAYDI. Shu marshrutni yopish
    CHEKSIZ chuqurlikdagi yo'lni yo'qotadi, 60 kunlik oynani emas.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)
_VK = {"X-Vendor-Key": "test-vendor-key"}


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _sahna(*, code_prefix="test", tz_a="Asia/Bishkek", tz_b="Europe/Moscow"):
    """Ikki filialli demo do'kon + `ega` aktor.

    ⚠️  SEED DO'KONIGA TEGILMAYDI. Unda bitta filial bor va conftest'dagi
        `_seed_filiallari_ozgarmaydi` qo'riqchisi filiallar to'plamini
        o'zgartirgan testni teardown'da qizartiradi. Vaqt mintaqasi nuqsonini
        ko'rsatish uchun IKKI filial kerak, shu bois o'z do'konimizni quramiz.

    ⚠️  `created_at` ATAYLAB: A filiali ESKIROQ. `_store_tz` eng eski filialni
        tanlaydi (`order_by(Branch.created_at).first()`), ya'ni nuqson bo'lsa
        ofset A dan kelardi. B ga yozib A ning ofseti chiqsa — nuqson qaytgan.
    """
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    from app.models.org import Branch, Company
    with _db() as db:
        comp = Company(id=uuid.uuid4(), name="Tarixiy seed sahnasi",
                       code=f"{code_prefix}-hseed-{uuid.uuid4().hex[:6]}",
                       currency="KGS")
        db.add(comp)
        db.flush()
        a = Branch(id=uuid.uuid4(), company_id=comp.id, name="A (eski)", code="A01",
                   timezone=tz_a, is_active=True, created_at=NOW - timedelta(days=400))
        b = Branch(id=uuid.uuid4(), company_id=comp.id, name="B (yangi)", code="B01",
                   timezone=tz_b, is_active=True, created_at=NOW - timedelta(days=300))
        db.add_all([a, b])
        role_ega = db.query(Role).filter(Role.code == "ega").one()
        role_omb = db.query(Role).filter(Role.code == "omborchi").one()
        emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role_ega.id,
                       full_name="Seed aktori",
                       phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        omb = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role_omb.id,
                       full_name="Omborchi (ruxsatsiz)",
                       phone=f"+9985{uuid.uuid4().int % 10**7:07d}",
                       status=EmployeeStatus.active, sec_epoch=0)
        db.add_all([emp, omb])
        db.commit()
        return {"cid": str(comp.id), "a": str(a.id), "b": str(b.id),
                "eid": str(emp.id), "omb": str(omb.id), "code": comp.code}


def _body(s, *, branch=None, actor=None, no=None, date="12.01.2026 15:00:00",
          rev=500000.0, **kw):
    return {"company_id": s["cid"], "branch_id": branch or s["b"],
            "actor_employee_id": actor or s["eid"],
            "rows": [{"date": date, "revenue": rev, "no": no or uuid.uuid4().hex[:8]}],
            **kw}


def _post(client, body, headers=None):
    return client.post("/api/v1/reports/history/seed",
                       headers=_VK if headers is None else headers, json=body)


# ══ 1. KO'P-FILIAL VAQT MINTAQASI NUQSONI (asosiy tuzatish) ═════════════════

def test_VAQT_MINTAQASI_qator_yoziladigan_FILIALDAN_olinadi(client):
    """`sold_at` AYNAN maqsad filialining ofseti bilan hisoblanadi.

    ⚠️  NUQSON (shu commitgacha). Marshrut ikki MUSTAQIL filial tanlovi
        qilardi: qator `branch` ga yozilardi (tartibsiz `.first()`), ofset esa
        `_store_tz(db, company_id)` dan — u esa eng eski filialni oladi. Ko'p
        vaqt mintaqali do'konda `sold_at` ofsetlar FARQICHA xato bo'lardi va
        hech qayerda bu ko'rinmasdi: kun kesimlari siljib, "kechagi" savdo
        boshqa kunga tushardi.

        Bu yerda farq 3 soat: A=Asia/Bishkek(+6) eski, B=Europe/Moscow(+3)
        maqsad. 15:00 mahalliy -> to'g'ri 12:00Z, nuqsonli 09:00Z.
    """
    from app.models.sales import Sale
    s = _sahna()
    no = uuid.uuid4().hex[:8]
    r = _post(client, _body(s, branch=s["b"], no=no, date="12.01.2026 15:00:00"))
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1, r.json()

    with _db() as db:
        sale = db.query(Sale).filter(Sale.receipt_no == f"H{no}").one()
        got = sale.sold_at
        if got.tzinfo is None:                 # SQLite tzinfo'ni tashlab yuboradi
            got = got.replace(tzinfo=timezone.utc)
        kutilgan = datetime(2026, 1, 12, 12, 0, 0, tzinfo=timezone.utc)   # 15:00 - 3h
        nuqsonli = datetime(2026, 1, 12, 9, 0, 0, tzinfo=timezone.utc)    # 15:00 - 6h
        assert got == kutilgan, (
            f"sold_at={got}, kutilgan={kutilgan}. "
            f"{nuqsonli} bo'lsa — ofset ESKI filialdan olingan (nuqson qaytdi)")
        assert sale.branch_id == uuid.UUID(s["b"])


def test_VAQT_MINTAQASI_ikki_FILIAL_ikki_natija(client):
    """Ayni mahalliy vaqt, boshqa filial -> boshqa UTC. Proba haqiqiyligi.

    ⚠️  Bu yuqoridagi testning kuchaytiruvchisi: agar kimdir ofsetni yana
        do'kon bo'yicha qattiq kodlab qo'ysa, bitta filialli test o'tib
        ketardi. Ikki filialning natijasi FARQ qilishi shartnomaning o'zi.
    """
    from app.models.sales import Sale
    s = _sahna()
    na, nb = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]
    assert _post(client, _body(s, branch=s["a"], no=na)).status_code == 200
    assert _post(client, _body(s, branch=s["b"], no=nb)).status_code == 200
    with _db() as db:
        def _t(n):
            x = db.query(Sale).filter(Sale.receipt_no == f"H{n}").one().sold_at
            return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
        assert _t(na) - _t(nb) == timedelta(hours=-3), (
            f"A(+6)={_t(na)}, B(+3)={_t(nb)} — farq 3 soat bo'lishi kerak")


# ══ 2. AVTORIZATSIYA — VENDOR, XODIM EMAS ══════════════════════════════════

def test_XODIM_tokeni_RAD_etiladi(client, admin_headers):
    """Eng yuqori huquqli `ega` Bearer token'i ham 401.

    ⚠️  Marshrut `tests/test_vendor_auth_employee_token.py` ning YOPIQ-DUNYO
        ro'yxatiga ham avtomatik tushadi (u ilovaning dependency daraxtidan
        o'qiladi). Bu yerda esa kuchaytirishning O'ZI qayd etiladi.
    """
    s = _sahna()
    assert _post(client, _body(s), headers=admin_headers).status_code == 401


def test_VENDOR_kaliti_ISHLAYDI(client):
    """Nazorat: 401'lar marshrut buzilganidan emas."""
    s = _sahna()
    assert _post(client, _body(s)).status_code == 200


# ══ 3. DO'KON DOIRASI — DEMO/TEST ══════════════════════════════════════════

def test_JONLI_dokon_RAD_etiladi(client):
    """Demo/test prefiksi bo'lmagan do'kon 400 oladi."""
    s = _sahna(code_prefix="jonli")
    r = _post(client, _body(s))
    assert r.status_code == 400, r.text
    assert "demo" in r.text.lower() or "test" in r.text.lower(), r.text


def test_MAVJUD_BOLMAGAN_dokon_RAD(client):
    r = _post(client, {"company_id": str(uuid.uuid4()),
                       "branch_id": str(uuid.uuid4()),
                       "actor_employee_id": str(uuid.uuid4()), "rows": []})
    assert r.status_code == 404, r.text


# ══ 4. FILIAL — FAIL-CLOSED, DETERMINISTIK ═════════════════════════════════

def test_BOSHQA_dokon_filiali_RAD(client):
    """IDOR: boshqa ijarachi filiali — mavjudligi ham oshkor qilinmaydi."""
    s1, s2 = _sahna(), _sahna()
    r = _post(client, _body(s1, branch=s2["b"]))
    assert r.status_code == 400, r.text
    assert s2["b"] not in r.text and s2["code"] not in r.text, (
        "javob boshqa ijarachining ma'lumotini oshkor qildi")


def test_NOFAOL_filial_RAD(client):
    """⚠️  Ilgari filial tanlovida `is_active` filtri UMUMAN yo'q edi."""
    from app.models.org import Branch
    s = _sahna()
    with _db() as db:
        db.get(Branch, uuid.UUID(s["b"])).is_active = False
        db.commit()
    assert _post(client, _body(s, branch=s["b"])).status_code == 400


def test_OCHIRILGAN_filial_RAD(client):
    from app.models.org import Branch
    s = _sahna()
    with _db() as db:
        db.get(Branch, uuid.UUID(s["b"])).deleted_at = NOW
        db.commit()
    assert _post(client, _body(s, branch=s["b"])).status_code == 400


# ══ 5. AKTOR — DETERMINISTIK, MAVJUD GARD BILAN ════════════════════════════

def test_AKTOR_cashier_id_ga_AYNAN_yoziladi(client):
    """`cashier_id` — ko'rsatilgan aktor, "birinchi topilgan xodim" EMAS."""
    from app.models.sales import Sale
    s = _sahna()
    no = uuid.uuid4().hex[:8]
    assert _post(client, _body(s, no=no)).status_code == 200
    with _db() as db:
        assert db.query(Sale).filter(Sale.receipt_no == f"H{no}").one().cashier_id \
            == uuid.UUID(s["eid"])


def test_BOSHQA_dokon_aktori_RAD(client):
    s1, s2 = _sahna(), _sahna()
    r = _post(client, _body(s1, actor=s2["eid"]))
    assert r.status_code == 400, r.text
    assert "BOSHQA do'kon" in r.text, r.text


def test_RUXSATSIZ_aktor_RAD(client):
    """Omborchi `kassa.sell` ruxsatiga ega emas.

    ⚠️  Gard `effective_permissions` bilan ishlaydi va `require()` dan farqli
        `FULL_ACCESS_ROLES` uchun qisqa tutashuv QILMAYDI — ya'ni qat'iyroq
        (qarang `services/migrator_1c/actor.py` sarlavhasi).
    """
    s = _sahna()
    r = _post(client, _body(s, actor=s["omb"]))
    assert r.status_code == 400, r.text
    assert "ruxsat yetishmaydi" in r.text and "kassa.sell" in r.text, r.text


def test_NOFAOL_aktor_RAD(client):
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    s = _sahna()
    with _db() as db:
        db.get(Employee, uuid.UUID(s["eid"])).status = EmployeeStatus.suspended
        db.commit()
    r = _post(client, _body(s))
    assert r.status_code == 400 and "faol emas" in r.text, r.text


def test_OCHIRILGAN_aktor_RAD(client):
    from app.models.auth import Employee
    s = _sahna()
    with _db() as db:
        db.get(Employee, uuid.UUID(s["eid"])).deleted_at = NOW
        db.commit()
    r = _post(client, _body(s))
    assert r.status_code == 400 and "o'chirilgan" in r.text, r.text


def test_MAVJUD_BOLMAGAN_aktor_RAD(client):
    s = _sahna()
    r = _post(client, _body(s, actor=str(uuid.uuid4())))
    assert r.status_code == 400 and "xodim topilmadi" in r.text, r.text


# ══ 6. AUDIT IZI ═══════════════════════════════════════════════════════════

def test_AUDIT_izi_YOZILADI(client):
    """Marshrut ilgari HECH QANDAY iz qoldirmasdi.

    ⚠️  `audit_log.actor_id` — `/audit` so'rovi INNER JOIN qiladigan ustun,
        ya'ni NULL aktyorli qator do'kon egasiga UMUMAN ko'rinmaydi. Shu bois
        aktor nomlangani kifoya emas — iz ham yozilishi shart.
    """
    from app.models.sync import AuditLog
    s = _sahna()
    assert _post(client, _body(s)).status_code == 200
    with _db() as db:
        rows = (db.query(AuditLog)
                .filter(AuditLog.entity == "history_seed",
                        AuditLog.actor_id == uuid.UUID(s["eid"])).all())
        assert len(rows) == 1, f"audit izi {len(rows)} ta (1 kutilgan)"
        after = rows[0].after or {}
        assert after.get("company_id") == s["cid"]
        assert after.get("branch_id") == s["b"]
        assert after.get("added") == 1


# ══ 7. MAVJUD KONTRAKT BUZILMAGANI ═════════════════════════════════════════

def test_IDEMPOTENTLIK_saqlanadi(client):
    """Ayni `no` + sana ikkinchi marta yozilmaydi (client_uuid bo'yicha)."""
    s = _sahna()
    b = _body(s)
    r1, r2 = _post(client, b), _post(client, b)
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert r1.json() == {"added": 1, "skipped": 0}, r1.json()
    assert r2.json() == {"added": 0, "skipped": 1}, r2.json()


def test_TAXMIN_OSHKORA_elon_qilinishi_SHART(client):
    """`cost_ratio` berilib `cost_basis` aytilmasa — 400. Kontrakt tegilmagan."""
    s = _sahna()
    r = _post(client, _body(s, cost_ratio=0.77))
    assert r.status_code == 400 and "cost_basis" in r.text, r.text
