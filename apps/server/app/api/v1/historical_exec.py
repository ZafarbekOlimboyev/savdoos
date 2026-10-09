# -*- coding: utf-8 -*-
"""`POST /api/v1/historical/events` — IMTIYOZLI tarixiy bajarish sirti.

MAQSAD. Sintetik test labi BusinessDayPlan hodisalarini bazaga TO'G'RIDAN
yozmasdan, KANONIK biznes yozuvchilari orqali bajara olsin. Yozuvchilar H1–H3b
da `at=` ni kalit-so'zli SERVIS parametri sifatida oldi, lekin HTTP orqali
tarixiy lahzani uzatish yo'li YO'Q edi: `historical.enter(...)` ning birorta
production chaqiruvchisi bo'lmagan.

NIMA EMAS
=========
Bu — ixtiyoriy funksiya chaqiruvchisi EMAS. Ruxsat etilgan hodisa turlari
`Literal` teglari sifatida discriminated union'ga qadalgan: noma'lum teg
PARSER darajasida 422 `union_tag_invalid` oladi va birorta yozuvchiga YETIB
BORMAYDI. Payloadlar — mavjud DTO'larning strict (`extra="forbid"`) voris
sinflari, ya'ni maydon ro'yxati DUBLIKAT QILINMAYDI va drift imkonsiz.

⚠️  `extra="forbid"` YETARLI EMAS. U faqat NOMA'LUM kalitni to'sadi; `sold_at`
    (`schemas/sales.py:39`), `client_uuid`, `image_b64`, `ai_raw` esa E'LON
    QILINGAN maydonlar va strict voris ularni SAQLAB qolardi (o'lchangan). Shu
    bois `_Strict` mixin'i server EGALIK qiladigan maydonlarni ALOHIDA rad
    etadi. `client_uuid` ni FAQAT server qo'yadi — u `event_key`.

NORMAL POS/MOBIL YO'LIGA TA'SIR = 0
===================================
Birorta mavjud marshrut, sxema yoki yozuvchi semantikasi o'zgarmaydi. Strictlik
FAQAT shu modulning xususiy bazasida: global `extra` siyosati TEGILMAYDI, chunki
`api/v1/sync.py:48-54` `SaleCreate(**raw)` ni `except ValidationError -> ok:False`
ichida bajaradi — `SaleCreate` strict bo'lsa, outbox payloadida bitta ortiqcha
kalit bo'lgan offline klient sotuvi JIMGINA dead-letter bo'lardi va payload
localStorage'da qolib abadiy qayta urinardi. Bu pul yo'qotish yo'li.
`/sync/push` ning ≤60 kunlik offline replay kontrakti ham O'ZGARMAYDI.

DARVOZALAR TARTIBI (hammasi biznes jadvaliga YOZUVDAN OLDIN)
===========================================================
 1 `require_vendor`           — dependency; 503/429/403/401. Xodim token'i
                                UMUMAN o'qilmaydi (imzosida `authorization` yo'q).
 2 strict parse + union       — 422; noma'lum teg yozuvchiga yetmaydi.
 3 muhit allowlist'i          — 403. ⚠️  `environment_allows_apply()` TUPLE
                                qaytaradi: `if not environment_allows_apply()`
                                HECH QACHON ishlamasdi (bo'sh bo'lmagan tuple
                                har doim truthy). `catalog_v2.py:48` kabi
                                unpack qilinadi.
 4 do'kon + `assert_demo_tenant` — 404/400/409; H1 ning YAGONA predikati.
 5 filial fail-closed        — 400 (ayni do'kon, o'chirilmagan, faol).
 6 aktor fail-closed         — 400; mavjud `resolve_actor` gardi.
 7 `actor_branch` TENGLIGI   — 400. ⚠️  O'n yozuvchi filialni `emp` dan
                                `actor_branch` orqali OLADI, ya'ni envelopdagi
                                `branch_id` faqat shu funksiya AYNI filialni
                                qaytarsa hurmat qilinadi. `EmployeeBranch`
                                qatorining MAVJUDLIGI yetarli emas: `deps.py:65-81`
                                da uch bosqich bor va 2-3 bosqich FAIL-OPEN
                                (biriktirilmagan xodimga do'konning birinchi
                                filialini, hatto NOFAOL filialni beradi).
 8 `require_index` + rezervatsiya — 409; jurnal ALOHIDA sessiyada commit qilinadi.
 9 `historical.enter(...)`   — 400 (kelajak lahza, bo'sh plan_id).
10 `historical.assert_gate(...)` — TRIPWIRE, himoya EMAS. HALOL CHEKLOV:
                                bu quvurda u YIQILA OLMAYDI, chunki `enter()`
                                kontekstni AYNI `company.id` dan qo'yadi va shu
                                qiymat uzatiladi. U kelajakdagi refaktoring
                                (kontekstni boshqa do'kon bilan ochish, ichma-ich
                                kontekst) uchun arzon qo'riqchi.
                                ⚠️  `sale` hodisasi uchun HAQIQIY himoya —
                                4-darvoza (demo tenant) va 6-darvoza (aktor
                                do'koni). `services/sales.py` `historical` ni
                                UMUMAN import qilmaydi (`now = at or _now()`),
                                ya'ni u na lahzani, na do'konni tekshiradi:
                                o'sha ikki darvoza YAGONA himoya, «qo'shimcha
                                qatlam» EMAS.
11 kanonik yozuvchi          — `at=ctx.instant`.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api.v1.admin import require_vendor
from app.api.v1.cashops import CashOpIn, _cash_op_once
from app.api.v1.customers import _pay_credit_once
from app.api.v1.inventory import CountIn, WriteoffIn, _stock_count_once, _writeoff_once
from app.api.v1.purchases import (SupplierPaymentIn, _create_purchase_once,
                                  _pay_supplier_once)
from app.api.v1.receiving import CommitIn, _commit_once
from app.api.v1.sales import _create_return_once
from app.api.v1.shifts import CloseShift, OpenShift
from app.db.session import SessionLocal, get_db
from app.models.auth import Employee
from app.models.org import Branch, Company
from app.schemas.customer import CreditPayment
from app.schemas.purchase import PurchaseCreate
from app.schemas.sales import ReturnCreate, SaleCreate
from app.services import historical as _H
from app.services import historical_journal as _J
from app.services import historical_recovery as _R
from app.services.migrator_1c import actor as _actor_mod
from app.services.shifts import close_shift_svc, open_shift_svc

router = APIRouter(prefix="/historical", tags=["historical"])

#: Aktor ATRIBUTSIYASI uchun talab qilinadigan ruxsat kodlari. Bu AVTORIZATSIYA
#: EMAS (u vendor kalitida) — «kim bajardi» degan yozuv haqiqiy, faol va shu
#: yozuvlarni HTTP tomonda himoya qiladigan kodlarga ega xodim bo'lsin.
#: ⚠️  `effective_permissions` bilan tekshiriladi, `require()` bilan EMAS: u
#:     `FULL_ACCESS_ROLES` uchun qisqa tutashuv qiladi, ya'ni ega HAR qanday
#:     kodni «bor» deb ko'rsatardi (`core/deps.py:128-129`).
ACTOR_PERMISSIONS = ("kassa.sell",)

#: Server EGALIK qiladigan maydonlar — mijoz BERMAYDI. `extra="forbid"` bularni
#: TUTMAYDI, chunki ular e'lon qilingan maydonlar (o'lchangan).
SERVER_OWNED = ("client_uuid", "sold_at", "image_b64", "ai_raw")

_STRICT = ConfigDict(extra="forbid")


class _Strict(BaseModel):
    """Strict baza: noma'lum kalit RAD + server egalik maydonlari RAD."""
    model_config = _STRICT

    @model_validator(mode="before")
    @classmethod
    def _server_owned_rad(cls, data):
        #  ⚠️  `mode="before"` SHART: faqat shu yerda XOM kalitlar ko'rinadi.
        #      `mode="after"` bo'lsa standart qiymat bilan to'lgan maydonni
        #      berilgan maydondan ajratib bo'lmasdi.
        if isinstance(data, dict):
            bor = [k for k in SERVER_OWNED if k in data]
            if bor:
                #  ⚠️  `PydanticCustomError`, oddiy `ValueError` EMAS: u BARQAROR
                #      `type` beradi (test shuni qadaydi) va `ctx` ga faqat
                #      MATN qo'yadi. Oddiy `ValueError` esa `ctx` ga istisno
                #      OBYEKTINI qo'yardi — repo 422 ishlovchisi uni
                #      serializatsiya qila olmay 500 berardi (o'sha nuqson
                #      `main.py` da alohida tuzatildi, lekin bu yerda unga
                #      TAYANMAYMIZ).
                raise PydanticCustomError(
                    "server_owned_field",
                    "server EGALIK qiladigan maydon(lar) berilgan: {maydonlar}. "
                    "Idempotentlik kaliti va vaqt muhrini FAQAT server qo'yadi "
                    "(client_uuid = event_key, vaqt = occurred_at).",
                    {"maydonlar": ", ".join(bor)})
        return data


# ── PAYLOADLAR: mavjud DTO'larning strict vorislari ────────────────────────
#  ⚠️  Maydon ro'yxati DUBLIKAT QILINMAYDI — voris hamma maydonni meros oladi va
#      faqat configni almashtiradi, ya'ni asl DTO o'zgarsa bu ham o'zgaradi
#      (drift imkonsiz). O'lchangan: `sorted(model_fields)` AYNI.

class _ShiftOpenP(_Strict, OpenShift):
    pass


class _ShiftCloseP(_Strict, CloseShift):
    #  ⚠️  `CloseShift` da `shift_id` YO'Q — yozuvchi uni POZITSIONAL oladi
    #      (`close_shift_svc(shift_id, data, emp, db, *, at=None)`). Shu bois
    #      maydon FAQAT shu yerda qo'shiladi; normal marshrut sxemasi
    #      TEGILMAYDI (`test_historical_dto_freeze.py` buni qadaydi).
    #      `counted_cash` MEROS olinadi — qo'lda qayta e'lon qilish drift
    #      xavfi bo'lardi (asl DTO'dagi `ge=0, le=1e9, allow_inf_nan=False`
    #      cheklovlari yo'qolardi).
    shift_id: _uuid.UUID


class _SaleP(_Strict, SaleCreate):
    pass


class _PurchaseP(_Strict, PurchaseCreate):
    pass


class _ReceivingP(_Strict, CommitIn):
    pass


class _ReturnP(_Strict, ReturnCreate):
    pass


class _CountP(_Strict, CountIn):
    pass


class _WriteoffP(_Strict, WriteoffIn):
    pass


class _CashPayinP(_Strict, CashOpIn):
    #  ⚠️  `Literal` ni QAYTA E'LON QILAMIZ: asl `CashOpIn.type`
    #      `Literal["payin","expense","collection"]`. Qayta e'lon qilmasak
    #      `collection` shu hodisa orqali YETIB BORARDI — uning tiklanish
    #      guvohi esa faqat Postgres'dagi cash sxemasida va «aniqlay olmadim»
    #      javobini beradi, ya'ni allowlist'dan ATAYLAB tashqarida.
    type: Literal["payin"] = "payin"


class _CashExpenseP(_Strict, CashOpIn):
    type: Literal["expense"] = "expense"


class _CustomerPayP(_Strict, CreditPayment):
    #  `_pay_credit_once` `customer_id` ni pozitsional oladi.
    customer_id: _uuid.UUID


class _SupplierPayP(_Strict, SupplierPaymentIn):
    #  `_pay_supplier_once` `supplier_id` ni pozitsional oladi.
    supplier_id: _uuid.UUID


# ── HODISA VARIANTLARI: allowlist = `Literal` teglar to'plami ──────────────
class _Ev(_Strict):
    pass


class ShiftOpenEv(_Ev):
    event_type: Literal["shift_open"]
    payload: _ShiftOpenP


class ShiftCloseEv(_Ev):
    event_type: Literal["shift_close"]
    payload: _ShiftCloseP


class SaleEv(_Ev):
    event_type: Literal["sale"]
    payload: _SaleP


class PurchaseEv(_Ev):
    event_type: Literal["purchase"]
    payload: _PurchaseP


class ReceivingEv(_Ev):
    event_type: Literal["receiving"]
    payload: _ReceivingP


class ReturnEv(_Ev):
    event_type: Literal["return"]
    payload: _ReturnP


class CountEv(_Ev):
    event_type: Literal["inventory_count"]
    payload: _CountP


class WriteoffEv(_Ev):
    event_type: Literal["writeoff"]
    payload: _WriteoffP


class CashPayinEv(_Ev):
    event_type: Literal["cash_payin"]
    payload: _CashPayinP


class CashExpenseEv(_Ev):
    event_type: Literal["cash_expense"]
    payload: _CashExpenseP


class CustomerPayEv(_Ev):
    event_type: Literal["customer_debt_payment"]
    payload: _CustomerPayP


class SupplierPayEv(_Ev):
    event_type: Literal["supplier_payment"]
    payload: _SupplierPayP


Event = Annotated[
    Union[ShiftOpenEv, ShiftCloseEv, SaleEv, PurchaseEv, ReceivingEv, ReturnEv,
          CountEv, WriteoffEv, CashPayinEv, CashExpenseEv, CustomerPayEv,
          SupplierPayEv],
    Field(discriminator="event_type"),
]

#: Ruxsat etilgan hodisa turlari — test bilan `_R.PROBES` ga tengligi qadalgan.
EVENT_TYPES = ("shift_open", "shift_close", "sale", "purchase", "receiving",
               "return", "inventory_count", "writeoff", "cash_payin",
               "cash_expense", "customer_debt_payment", "supplier_payment")


class HistoricalEventIn(_Strict):
    """Bitta tarixiy hodisa. Vaqtning YAGONA kirish nuqtasi — `occurred_at`."""
    company_id: _uuid.UUID
    branch_id: _uuid.UUID
    actor_employee_id: _uuid.UUID
    plan_id: str = Field(min_length=1, max_length=120)
    #: Rejaning BIRINCHI hodisasi: `assert_demo_tenant` bo'sh tarix talab qiladi.
    plan_start: bool = False
    occurred_at: datetime
    #: `event_key` shu bo'laklardan DETERMINISTIK chiqadi (`historical.event_key`).
    event_seq: list[str] = Field(min_length=1, max_length=8)
    event: Event


# ── DISPATCH: har hodisa -> kanonik yozuvchi ──────────────────────────────
def _with_key(payload, key: _uuid.UUID):
    """`client_uuid` ni SERVER qo'yadi. `model_copy` ataylab: qayta
    validatsiya qilmaydi, ya'ni mixin'ning «mijoz bermasin» qoidasi
    buzilmaydi."""
    if "client_uuid" in type(payload).model_fields:
        return payload.model_copy(update={"client_uuid": key})
    return payload


def _dispatch(ev, *, emp: Employee, db: Session, at: datetime,
              key: _uuid.UUID) -> tuple[str, _uuid.UUID | None, dict]:
    """Kanonik yozuvchini chaqiradi. Qaytaradi `(result_type, result_id, javob)`."""
    t, p = ev.event_type, _with_key(ev.payload, key)

    if t == "shift_open":
        out = open_shift_svc(p, emp, db, at=at, client_uuid=key)
        return "shift", _uuid.UUID(str(out["id"])), dict(out)

    if t == "shift_close":
        out = close_shift_svc(p.shift_id, p, emp, db, at=at)
        return "shift", _uuid.UUID(str(out["id"])), dict(out)

    if t == "sale":
        from app.services.sales import create_sale
        #  ⚠️  O'ROVCHI chaqiriladi (`_create_sale_once` EMAS): faqat u `at=` ni
        #      ham oladi, ham `receipt_no` to'qnashuvi uchun 3× retry'ni saqlaydi.
        sale = create_sale(db, emp, p, at=at)
        return "sale", sale.id, {"id": str(sale.id), "receipt_no": sale.receipt_no,
                                 "total": float(sale.total or 0)}

    if t == "purchase":
        pur = _create_purchase_once(p, emp, db, at=at)
        return "purchase", pur.id, {"id": str(pur.id)}

    if t == "receiving":
        out = _commit_once(p, emp, db, at=at)
        rid = out.get("receiving_id")
        return "receiving", (_uuid.UUID(str(rid)) if rid else None), dict(out)

    if t == "return":
        out = _create_return_once(p, emp, db, at=at)
        return "return", _uuid.UUID(str(out["id"])), dict(out)

    if t == "inventory_count":
        out = _stock_count_once(p, emp, db, at=at)
        #  Yagona natija qatori YO'Q (mahsulot bo'yicha 0..N harakat), shu bois
        #  natija havolasi jurnal qatorining O'ZI bo'ladi — chaqiruvchi qo'yadi.
        return "stock_count", None, dict(out)

    if t == "writeoff":
        out = _writeoff_once(p, emp, db, at=at)
        return "stock_movement", None, dict(out)

    if t in ("cash_payin", "cash_expense"):
        out = _cash_op_once(p, emp, db, at=at)
        return "cash_movement", None, dict(out)

    if t == "customer_debt_payment":
        out = _pay_credit_once(p.customer_id, p, emp, db, at=at)
        return "customer_payment", None, dict(out)

    if t == "supplier_payment":
        out = _pay_supplier_once(p.supplier_id, p, emp, db, at=at)
        return "supplier_payment", None, dict(out)

    #  Parser bu holatga yetib bormaydi (union tegi), lekin fail-closed.
    raise RuntimeError(f"dispatch yo'li YO'Q: {t!r}")


def _dispatch_retry(ev, *, emp: Employee, db: Session, at: datetime,
                    key: _uuid.UUID):
    """Marshrut o'ramlari qiladigan retry'ni TAKRORLAYDI.

    ⚠️  NEGA KERAK. HTTP marshrut o'ramlari `_once` tanasini `at=` siz,
        pozitsional chaqiradi — ya'ni tarixiy chaqiruvdan ULARGA YETIB
        BORILMAYDI va ular tutadigan ichki signallar bu yerda 500 bo'lib
        chiqardi: `_create_return_once` -> `_KuzatuvOzgardi`
        (`api/v1/sales.py:431`, faqat `:425` da tutiladi),
        `_pay_supplier_once` -> `_QulfQaytaUrinish` (`purchases.py:1056`,
        faqat `:1117` da tutiladi) va 40P01 deadlock.

    ⚠️  JURNAL TEGILMAYDI. `db.rollback()` faqat BIZNES sessiyasida; jurnal
        qatori ALOHIDA sessiyada allaqachon commit qilingan va shu sababli
        retry uni YO'Q QILMAYDI (modul `historical_journal` sarlavhasi).
    """
    from app.api.v1.purchases import _QulfQaytaUrinish
    from app.api.v1.sales import _KuzatuvOzgardi
    oxirgi: Exception | None = None
    for _ in range(3):
        try:
            return _dispatch(ev, emp=emp, db=db, at=at, key=key)
        except (_KuzatuvOzgardi, _QulfQaytaUrinish, IntegrityError) as e:
            db.rollback()
            oxirgi = e
        except OperationalError as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) != "40P01":
                raise
            db.rollback()
            oxirgi = e
    raise HTTPException(
        409, "Tarixiy hodisa band — qayta urinib ko'ring") from oxirgi


def _javob(row, *, result: dict, extra: dict | None = None) -> dict:
    out = {"ok": True, "event_key": str(row.event_key),
           "event_type": row.event_type, "status": row.status,
           "result_type": row.result_type,
           "result_id": (str(row.result_id) if row.result_id else None),
           "result": result}
    if extra:
        out.update(extra)
    return out


@router.post("/events", include_in_schema=False)
def historical_event(body: HistoricalEventIn,
                     _vendor: bool = Depends(require_vendor),
                     db: Session = Depends(get_db)):
    #  ── 3. MUHIT ALLOWLIST'I ────────────────────────────────────────────────
    #  ⚠️  «Production'ga tegilmaydi» ni `require_vendor` BERMAYDI: vendor
    #      sessiyasi production'da ham amal qiladi. Buni AYNAN shu darvoza
    #      beradi va u `is_production` ga BOG'LIQ EMAS: `APP_ENV` yo'q bo'lsa
    #      `"unknown"` o'qiladi va RAD etiladi (fail-closed).
    from app.services.migrator_1c.guard import environment_allows_apply
    ok, why = environment_allows_apply()
    if not ok:
        raise HTTPException(403, f"Tarixiy bajarish bu muhitda yopiq: {why}")

    #  ── 4. DO'KON + DEMO DARVOZASI ──────────────────────────────────────────
    #  ⚠️  `with_for_update` ATAYLAB YO'Q. Jurnal sessiyasining INSERT'i
    #      `companies` ga FK sababli `KEY SHARE` oladi; bu sessiya `FOR UPDATE`
    #      ushlab turса, bir so'rov ichida o'z-o'zini bloklardi (jurnal commit
    #      kutardi, bu esa jurnalni kutardi). Qator MUTATSIYA QILINMAYDI.
    company = db.get(Company, body.company_id)
    _H.assert_demo_tenant(db, company, require_empty_history=body.plan_start)

    #  ── 5. FILIAL, FAIL-CLOSED ──────────────────────────────────────────────
    branch = db.get(Branch, body.branch_id)
    if (branch is None or branch.company_id != company.id
            or branch.deleted_at is not None or not branch.is_active):
        raise HTTPException(400, "Filial topilmadi yoki bu do'konga tegishli emas")

    #  ── 6. AKTOR, FAIL-CLOSED (mavjud gard) ─────────────────────────────────
    try:
        emp = _actor_mod.resolve_actor(db, company, body.actor_employee_id,
                                       required_permissions=ACTOR_PERMISSIONS,
                                       kontekst="TARIXIY BAJARISH")
    except _actor_mod.ActorForbidden as e:
        raise HTTPException(400, str(e)) from e

    #  ── 7. `actor_branch` TENGLIGI ──────────────────────────────────────────
    #  ⚠️  Mavjudlik YETARLI EMAS, TENGLIK kerak — qarang modul sarlavhasi
    #      (7-darvoza). O'n yozuvchi filialni `emp` dan oladi.
    from app.core.deps import actor_branch
    ab = actor_branch(emp, db)
    if ab is None or ab.id != branch.id:
        raise HTTPException(
            400, "Aktor shu filialga biriktirilmagan — tarixiy hodisa filiali "
                 "xodimning amaldagi filiali bilan AYNI bo'lishi shart")

    #  ── 8. REZERVATSIYA — ALOHIDA SESSIYADA ────────────────────────────────
    key = _H.event_key(company.id, body.plan_id, *body.event_seq)
    ev = body.event
    canon = _J.canonical(event_type=ev.event_type, occurred_at=body.occurred_at,
                         branch_id=branch.id, actor_employee_id=emp.id,
                         payload=ev.payload.model_dump(mode="json"))

    jdb: Session = SessionLocal()
    try:
        #  ⚠️  Indeks kafolati `_J.claim` ICHIDA, INSERT'ning YONIDA (fail-closed).
        #      U yerda sessiya `db` deb nomlanadi — registr gardi gard
        #      chaqiruvlarini `git grep` bilan sanaydi va shu nomni konvensiya
        #      sifatida talab qiladi; boshqa nom bilan chaqirilgan gard
        #      ro'yxatda KO'RINMASDAN qolardi.
        yangi, mavjud = _J.claim(
            jdb, company_id=company.id, branch_id=branch.id,
            actor_employee_id=emp.id, plan_id=body.plan_id,
            event_type=ev.event_type, event_key=key,
            occurred_at=body.occurred_at, canon=canon)

        if mavjud is not None:
            javob = _mavjud_kalit(jdb, db, mavjud, canon=canon, ev=ev,
                                  emp=emp, branch=branch, company=company,
                                  body=body, key=key)
            if javob is not None:
                return javob
            yangi = mavjud          # `failed` -> qayta ishlatiladi

        #  ── 9-11. KONTEKST, DARVOZA, YOZUVCHI ──────────────────────────────
        return _bajar(jdb, db, yangi, ev=ev, emp=emp, company=company,
                      body=body, key=key)
    finally:
        jdb.close()


def _mavjud_kalit(jdb, db, row, *, canon, ev, emp, branch, company, body, key):
    """Kalit band: takror / konflikt / tiklanish. `None` -> qayta bajariladi."""
    #  (a) FILIAL KONFLIKTI — BIRINCHI va ALOHIDA (ega qarori). Branch saqlangan
    #      ustun, ya'ni hech narsa qayta hisoblamasdan aniq diagnoz beriladi.
    #      Hash'ga qo'shib yuborish «payload boshqa» deb chalg'itardi.
    if row.branch_id != branch.id:
        raise HTTPException(
            409, "Bu event_key BOSHQA filial uchun yozilgan — takror emas. "
                 "Yangi hodisa uchun yangi kalit bering.")
    #  (b) HODISA TURI — aniq diagnoz (hash ham tutardi, lekin noaniq xabar bilan).
    if row.event_type != ev.event_type:
        raise HTTPException(
            409, "Bu event_key BOSHQA hodisa turi uchun ishlatilgan — takror "
                 "emas. Yangi hodisa uchun yangi kalit bering.")
    #  (c) MAZMUN KONFLIKTI. Kutilgan hash SAQLANGAN versiya bo'yicha
    #      hisoblanadi, aks holda kelajakdagi v2 ESKI qatorga YOLG'ON konflikt
    #      berardi (`catalog_commit_v2.py:184-192` naqshi).
    if row.hash_version != _J.HASH_VERSION:
        raise HTTPException(
            409, f"Bu event_key boshqa kanonik shakl versiyasida yozilgan "
                 f"(saqlangan v{row.hash_version}, hozirgi v{_J.HASH_VERSION}) — "
                 f"solishtirib bo'lmaydi.")
    if row.payload_hash != _J.payload_hash(canon):
        raise HTTPException(
            409, "Bu event_key BOSHQA mazmun bilan kelgan — takror emas. "
                 "Yangi hodisa uchun yangi kalit bering.")

    #  (d) TUGAGAN -> TAKROR: saqlangan javob AYNAN qaytariladi.
    if row.status == _J.DONE:
        saqlangan = _J.stored_response(row)
        if saqlangan is None:
            #  `done`, lekin javob o'qilmaydi — jim «muvaffaqiyat» demaymiz.
            raise HTTPException(
                409, "Tarixiy hodisa yakunlangan, lekin javobi o'qilmadi — "
                     "operator tekshiruvi kerak.")
        return _javob(row, result=saqlangan, extra={"duplicate": True})

    #  (e) BOSHLANGAN yoki MUVAFFAQIYATSIZ -> KANONIK HOLATNI O'QIYMIZ.
    #
    #  ⚠️  EGA SHARTI: `started` qatori halokatdan keyin ABADIY 409 BERMASIN.
    #      Shu bois bu yerda taxmin qilinmaydi — biznes jadvali O'QILADI.
    #
    #  ⚠️  `failed` HAM ZONDLANADI, va bu NOZIK NUQTA. `mark_failed` istisno
    #      bo'yicha qo'yiladi, istisno esa yozuvchi COMMIT QILGANDAN KEYIN ham
    #      yuzaga kelishi mumkin (masalan natija id'sini o'qishda). Agar `failed`
    #      ni zondsiz «qayta bajaramiz» deb olsak, `shift_close` uchun qayta
    #      dispatch 400 «Smena allaqachon yopilgan» berib hodisani ABADIY
    #      QOTIRIB qo'yardi — ya'ni ayni taqiqlangan holat, faqat boshqa nom
    #      ostida. Zond bir o'qish, qotib qolish esa tiklanmaydigan holat.
    if row.status in (_J.STARTED, _J.FAILED):
        zond = _R.probe(db, row)
        if zond.landed:
            #  W3: yozuvchi commit qilgan, finalize ulgurmagan -> FINALIZE.
            natija = dict(zond.detail)
            _J.finalise(jdb, row, result_type=zond.result_type,
                        result_id=zond.result_id, response=natija)
            return _javob(row, result=natija,
                          extra={"duplicate": True, "recovered": True})
        #  W2: yozuvchiga yetib bormagan -> AYNI qator qayta ishlatiladi
        #  (yangi kalit MINTILMAYDI — `catalog_commit_v2.py:199-203` naqshi).
        if row.status == _J.FAILED:
            _J.resume(jdb, row)
        return None

    raise HTTPException(409, f"Tarixiy hodisa holati noma'lum: {row.status!r}")


def _bajar(jdb, db, row, *, ev, emp, company, body, key):
    """Kontekst ochadi, darvozani aniq tekshiradi, yozuvchini chaqiradi."""
    try:
        with _H.enter(db, company, plan_id=body.plan_id,
                      instant=body.occurred_at,
                      require_empty_history=body.plan_start) as ctx:
            #  ⚠️  TRIPWIRE, himoya EMAS — halol cheklov. Bu quvurda yiqila
            #      olmaydi: `enter()` kontekstni AYNI `company.id` dan qo'ydi.
            #      Saqlanadi, chunki arzon va kelajakdagi refaktoring (boshqa
            #      do'kon bilan kontekst, ichma-ich kontekst) uni ishga
            #      tushiradi. Yiqilsa — SERVER NUQSONI, shu bois 500 bo'lib
            #      chiqadi va 409 ga aylantirilMAYDI.
            #  ⚠️  `sale` uchun HAQIQIY himoya 4- va 6-darvozalar (demo tenant +
            #      aktor do'koni): `services/sales.py` `historical` ni umuman
            #      import qilmaydi va na lahzani, na do'konni tekshiradi.
            _H.assert_gate(ctx.instant, company.id)
            try:
                rtype, rid, natija = _dispatch_retry(ev, emp=emp, db=db,
                                                     at=ctx.instant, key=key)
            except RuntimeError as e:
                #  ⚠️  TARIXIY QATLAM `RuntimeError` KO'TARADI, `HTTPException`
                #      EMAS — ataylab: `assert_chronological` va `require_at`
                #      xabarlari OPERATORGA emas BAJARUVCHIGA qaratilgan va shu
                #      sababli frontend tarjima lug'atiga kirmaydi (H3a qarori).
                #      Lekin bajaruvchi — HTTP mijozi, va 500 unga diagnoz
                #      BERMAYDI. Shu bois 409 ga aylantiramiz va xabarni AYNAN
                #      saqlaymiz (unda nima qilish kerakligi yozilgan: «reja
                #      hodisalarini payt bo'yicha GLOBAL tartiblang»).
                raise HTTPException(409, str(e)) from e
    except HTTPException:
        _J.mark_failed(jdb, row, "biznes qoidasi rad etdi")
        raise
    except Exception as e:                                   # noqa: BLE001
        _J.mark_failed(jdb, row, f"{type(e).__name__}: {e}")
        raise

    #  Yagona natija qatori bo'lmagan hodisalar uchun havola — jurnal qatori.
    if rid is None:
        zond = _R.probe(db, row)
        rid = zond.result_id if zond.landed else row.id
        if zond.landed and zond.detail:
            natija = {**natija, **zond.detail}
    _J.finalise(jdb, row, result_type=rtype, result_id=rid, response=natija)
    return _javob(row, result=natija, extra={"duplicate": False})
