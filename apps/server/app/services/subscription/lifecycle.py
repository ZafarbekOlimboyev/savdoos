# -*- coding: utf-8 -*-
"""Obuna hayot sikli — YAGONA yozuvchi (Phase 6A/2.5).

KOMPANIYAGA BITTA QATOR, UMRBOD
===============================
Bekor qilingan mijoz qayta obuna bo'lsa YANGI QATOR YOZILMAYDI: mavjud qator
authoritative bo'lib qoladi va `reactivate()` uni qulf ostida qaytaradi. Buni sxema
ham majburlaydi — `ck_sub_deleted_never` + `ux_subscriptions_company` birgalikda
«kompaniyaga bitta qator» degan TO'LIQ noyoblikni beradi.

RUXSAT ETILGAN O'TISHLAR — BOSHQASI YO'Q
========================================
    yozuv yo'q         -> ACTIVE       enrol()
    ACTIVE             -> RESTRICTED   restrict()
    RESTRICTED         -> ACTIVE       restore()      (restricted_at ham SHART)
    ACTIVE|RESTRICTED  -> CANCELLED    cancel()
    CANCELLED          -> ACTIVE       reactivate()   (YAGONA yo'l)

⚠️  `restore()` SAQLANGAN qiymatga qaraydi, KO'RINISHGA emas. `state.py` bekor
    qilingan obunani operatorga `RESTRICTED` ko'rinishida ko'rsatadi — agar
    `restore()` shunga tayansa, u `CANCELLED -> ACTIVE` ga IKKINCHI yo'l bo'lib
    qolardi. CHECK buni ushlay olmaydi: cheklov oldingi qatorni ko'rmaydi.
⚠️  `GRACE` HECH QACHON saqlanmaydi — u faqat `state.py` da hisoblanadi.
⚠️  Bu yerda UMUMIY «status yangilash» amali ATAYLAB YO'Q: har o'tishning o'z
    shartlari va o'z audit hodisasi bor.

TRANZAKSIYA EGALIGI — `commit` BAYROG'I
======================================
Loyiha naqshi: `services/cash/posting.py:73-76`.

  `commit=True`  (standart, mustaqil chaqiruv) — TRANZAKSIYA EGASI SHU XIZMAT.
                 Muvaffaqiyatda `commit()`, rad etishda `rollback()` qiladi.
                 Bunda sessiyada BEGONA kutilayotgan ish BO'LMASLIGI shart va
                 buni `_assert_owner()` TEKSHIRADI — taxmin qilinmaydi.
  `commit=False` (chaqiruvchining tranzaksiyasiga qo'shilish) — xizmat NA commit,
                 NA rollback qiladi; faqat `flush()`. Rad etish istisno bo'lib
                 chiqadi va chaqiruvchi o'z tranzaksiyasi bilan nima qilishni
                 O'ZI hal qiladi.

⚠️  NEGA SHARTSIZ `rollback()` NOTO'G'RI EDI. Rad etish yo'li chaqiruvchining
    begona ishini ham bekor qilardi; `_lock` dagi shartsiz `db.flush()` esa uni
    bazaga yuborardi. Ya'ni AYNI chaqiruvchi kodi muvaffaqiyatda begona ishini
    SAQLAB, rad etishda YO'QOTARDI. Endi `flush` faqat `commit=False` da (o'sha
    ish chaqiruvchining O'Z tranzaksiyasida, birga commit bo'ladi), `rollback`
    esa faqat egalik xizmatda bo'lganda.

QULF VA AYNAN-BIR-MARTA
=======================
Har amal: qatorni `FOR NO KEY UPDATE` bilan qulflaydi, qulfdan KEYIN qiymatlarni
BAZADAN qayta o'qiydi, qarorni shu holatdan chiqaradi, o'zgartiradi, AYNI
tranzaksiyada audit yozadi va BIR marta yakunlaydi.

⚠️  `populate_existing()` SHART. `SessionLocal(autoflush=False, expire_on_commit=False)`
    — sessiya qatorni oldinroq yuklagan bo'lsa, oddiy qayta so'rov identity map'dagi
    ESKI nusxani qaytaradi va qulf ostidagi qaror eskirgan qiymatda qabul qilinardi:
    ikki parallel `reactivate()` ning ikkalasi ham «CANCELLED» ko'rib, davrni ikki
    marta tiklardi. Uy qoidasi: `services/catalog_import_v2.py:69-75`.
⚠️  `key_share=True` (`FOR NO KEY UPDATE`), `FOR UPDATE` EMAS:
    `subscription_payments.subscription_id` FK'li INSERT ota qatorga KEY SHARE
    oladi va `FOR UPDATE` u bilan to'qnashib DEADLOCK berardi.

TARIX
=====
Qator JORIY holatni saqlaydi, TARIXNI emas: `reactivate()` `cancelled_at` ni
tozalaydi (buni `ck_sub_cancelled_iff` talab qiladi). Bekor qilish fakti
`admin_audit_log` da qoladi — har o'tish uchun AYNI tranzaksiyada bitta qator,
to'ldirilgan `before_summary`/`after_summary` bilan (`ck_audit_sub_fields`).

ZANJIR TARTIBI — `row_version`
==============================
⚠️  `created_at` bo'yicha tartiblash YETARLI EMAS: bir soniya ichidagi ikki o'tish
    teng chiqadi va zanjir tasodifiy tartibda o'qilardi. Har o'tish `row_version` ni
    BIR ga oshiradi, ya'ni `after_summary["row_version"]` obuna bo'yicha QAT'IY
    o'suvchi — zanjir aynan shu bo'yicha tiklanadi. Yangi ustun kerak emas.

⚠️  `admin_audit_log` append-only KONSTRUKSIYA bo'yicha: bu modulda ham, boshqa
    joyda ham unga `UPDATE`/`DELETE` yo'li yo'q. Bu BAZA darajasidagi kafolat EMAS —
    ilova roli sxema egasi (staging'da `postgres`), ya'ni har qanday trigger'ni
    o'zi o'chira olardi. Da'vo aynan shu kuchda yoziladi, kuchaytirilmaydi.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.models.enums import SubscriptionStatus
from app.models.subscription import AdminAuditLog, Plan, Subscription
from app.services.subscription.periods import grace_end, period_end

ACTIVE = SubscriptionStatus.ACTIVE.value
RESTRICTED = SubscriptionStatus.RESTRICTED.value
CANCELLED = SubscriptionStatus.CANCELLED.value

TARGET_TYPE = "subscription"

ACTION_ENROL = "SUBSCRIPTION_CREATE"
ACTION_RESTRICT = "SUBSCRIPTION_RESTRICT"
ACTION_RESTORE = "SUBSCRIPTION_RESTORE"
ACTION_CANCEL = "SUBSCRIPTION_CANCEL"
ACTION_REACTIVATE = "SUBSCRIPTION_REACTIVATE"
ACTION_PAYMENT = "SUBSCRIPTION_PAYMENT"

#: Snapshot'ga AYNAN shu maydonlar tushadi — umumiy filtr emas, ANIQ ro'yxat.
#  Umumiy filtr yangi maydon qo'shilganda uni JIMGINA tushirib qoldirardi va
#  audit zanjiri sababsiz uzilardi.
SNAPSHOT_FIELDS = ("status", "plan_id", "started_at", "current_period_start",
                   "current_period_end", "grace_until", "restricted_at",
                   "cancelled_at", "deleted_at", "row_version")


class LifecycleRefused(Exception):
    """O'tish rad etildi. `code` — chaqiruvchi 4xx `X-Error-Code` ga aylantiradi."""

    def __init__(self, code: str, message: str, *, current_status: str | None = None):
        super().__init__(message)
        self.code = code
        #  ⚠️  Javobda JORIY holat ham qaytariladi: yo'qolgan javobdan keyingi takror
        #      urinish «boshqa kimdir o'zgartirdi» dan farq qila olsin.
        self.current_status = current_status


@dataclass(frozen=True)
class Actor:
    """Amalni bajargan platforma admini — auditga DENORMALIZATSIYA qilinadi."""
    admin_id: uuid.UUID
    login: str
    role: str


# ══ Yordamchilar ════════════════════════════════════════════════════════════

def _jsonable(v):
    """JSONB ga faqat JSON PRIMITIVLARI yoziladi.

    ⚠️  Engine `json_serializer`siz quriladi (`db/session.py`), ya'ni standart
        `json.dumps` ishlaydi va `datetime` ga `TypeError` beradi — snapshot'ga
        xom `datetime` qo'yilsa HAR cancel/reactivate 500 bo'lardi.
    """
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, datetime):
        #  ⚠️  IKKI xil siljish bor va ikkalasi ham audit ZANJIRINI uzadi:
        #      (a) SQLite naive qaytaradi, Postgres aware;
        #      (b) aware qiymat SERVER `TimeZone` GUC ofsetida keladi — AYNI lahza
        #          xotiradan `+00:00`, bazadan `+05:00` bo'lib yozilardi.
        #      Shu bois avval UTC deb o'qiladi, KEYIN UTC ga keltiriladi.
        v = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    return str(v)


def snapshot(sub: Subscription | None) -> dict:
    """Qatorning audit uchun suratini oladi (yo'q bo'lsa — bo'sh belgisi)."""
    if sub is None:
        return {"exists": False}
    out = {"exists": True}
    out.update({f: _jsonable(getattr(sub, f, None)) for f in SNAPSHOT_FIELDS})
    return out


class TransactionMisuse(RuntimeError):
    """Xizmat tranzaksiya egasi, lekin sessiyada BEGONA kutilayotgan ish bor.

    Bu biznes rad etishi EMAS, dasturlash xatosi: `commit=True` bilan chaqirilgan
    xizmat muvaffaqiyatda `commit()`, rad etishda `rollback()` qiladi — ikkalasi
    ham chaqiruvchining begona ishiga TEGADI. Shu bois taxmin qilinmaydi, tekshiriladi.
    Chaqiruvchining ishi bir tranzaksiyada ketishi KERAK bo'lsa: `commit=False`.
    """


def _assert_owner(db, commit: bool) -> None:
    """`commit=True` da tranzaksiyani yakunlash HAQLI ekanini tekshiradi.

    NIMA TEKSHIRILADI VA NEGA AYNAN SHU
    ===================================
    ⚠️  «Tranzaksiya ochiq emas» TALAB QILINMAYDI va bu ataylab. Har so'rovda
        `get_current_employee` (`core/deps.py:12-46`) bir nechta SELECT bajaradi va
        `autobegin` standart `True` bo'lgani uchun endpoint tanasi ishlaganda
        tranzaksiya ALLAQACHON ochiq bo'ladi. Ya'ni virgin sessiya talab qilinsa,
        xizmat birorta marshrutdan chaqirilib bo'lmasdi.
        Repo chegarasi ham shunday: `app/api/v1` da 81 ta marshrut-darajasidagi
        `db.commit()` bor va HAMMASI aynan auth o'qishlari ochgan tranzaksiyani
        yakunlaydi. FAQAT O'QIGAN tranzaksiyani commit qilish esa hech nimani
        yo'qotmaydi — yo'qotadigan narsa YOZUV bo'lardi, u esa quyida to'siladi.
    ⚠️  ANIQLANADIGAN egalik signali — SAVEPOINT. Chaqiruvchi `begin_nested()`
        bilan o'z chegarasini ATAYLAB o'rnatgan bo'lsa, uni tashqaridan yakunlash
        noto'g'ri: shu holat fail-fast qilinadi.
    ⚠️  ANIQLAB BO'LMAYDIGAN holat: chaqiruvchi boshqa qatorda `FOR UPDATE` qulfini
        ushlab turib, uni chaqiruv oshib qolishini kutayotgan bo'lsa. SQLAlchemy
        buni ko'rsatmaydi. Shunday chaqiruvchi `commit=False` ishlatishi SHART —
        bu taxmin emas, hujjatlashtirilgan kontrakt.
    """
    if not commit:
        return
    pending = ([o for o in db.new] + [o for o in db.deleted]
               + [o for o in db.dirty if db.is_modified(o)])
    if pending:
        raise TransactionMisuse(
            "obuna xizmati `commit=True` bilan chaqirildi, lekin sessiyada "
            f"{len(pending)} ta yakunlanmagan YOZUV bor "
            f"({type(pending[0]).__name__}...). Avval commit qiling yoki "
            "`commit=False` bilan chaqiring.")
    if db.in_nested_transaction():
        raise TransactionMisuse(
            "sessiyada SAVEPOINT (`begin_nested`) ochiq — chegarani chaqiruvchi "
            "o'rnatgan, uni xizmat yakunlamaydi. `commit=False` ishlating.")


def _refuse(db, exc, commit: bool):
    """Qulf ostidagi rad etish — egalik xizmatda bo'lsa tranzaksiyani yopadi.

    ⚠️  `commit=False` da HECH NARSA qilinmaydi: tranzaksiya chaqiruvchiniki,
        uni bekor qilish ham CHAQIRUVCHINING qarori. Xizmat begona ishni jimgina
        yo'q qilmaydi.
    """
    if commit:
        db.rollback()
    return exc


def _finish(db, commit: bool, objects) -> None:
    """Muvaffaqiyat yo'li: egalik xizmatda bo'lsa commit, aks holda NISHONLI flush.

    ⚠️  `commit=False` da `db.flush()` (parametrsiz) BUTUN sessiyani yuborardi va
        chaqiruvchining bog'liq bo'lmagan yozuvlari vaqtidan oldin bazaga chiqardi:
        cheklovlar kutilmagan joyda ishga tushardi va xato boshqa amalga
        «yopishardi». Shu bois faqat SHU amal yaratgan/tegilgan obyektlar
        yuboriladi — qolgani chaqiruvchining commit'iga qoladi.
    """
    if commit:
        db.commit()
    else:
        db.flush(objects)


def _lock(db, company_id, *, commit: bool) -> Subscription | None:
    """Qatorni qulflab, qiymatlarni BAZADAN qayta o'qiydi.

    ⚠️  FLUSH NISHONLI. `Session.flush()` BUTUN sessiyani yuboradi — `commit=False`
        da bu chaqiruvchining bog'liq bo'lmagan yozuvlarini ham vaqtidan oldin
        bazaga chiqarardi (cheklovlar kutilmagan joyda ishga tushardi). Shu bois
        faqat SHU kompaniyaning kutilayotgan obuna qatori yuboriladi: qulflangan
        SELECT uni ko'rishi kerak, boshqasi esa kerak emas.
    ⚠️  `commit=True` da umuman flush qilinmaydi: `_assert_owner()` kutilayotgan
        yozuv yo'qligini kafolatlagan.
    ⚠️  QULFLANGAN SELECT O'ZI ham flush QILMAYDI: `SessionLocal` `autoflush=False`
        (`db/session.py:72`), ya'ni so'rov yashirincha butun sessiyani yubormaydi.
        Test buni qadab turadi.
    """
    if not commit:
        kutilayotgan = [o for o in db.new
                        if isinstance(o, Subscription)
                        and getattr(o, "company_id", None) == company_id]
        if kutilayotgan:
            db.flush(kutilayotgan)
    return (db.query(Subscription)
            .filter(Subscription.company_id == company_id)
            .with_for_update(key_share=True)
            .populate_existing()
            .one_or_none())


def _audit(db, *, action, company_id, target_id, actor: Actor, reason: str,
           before: dict, after: dict, request_id: str | None) -> AdminAuditLog:
    row = AdminAuditLog(
        actor_admin_id=actor.admin_id, actor_login=actor.login, actor_role=actor.role,
        action=action, target_type=TARGET_TYPE, target_id=target_id,
        company_id=company_id, before_summary=before, after_summary=after,
        reason=reason, request_id=request_id)
    db.add(row)
    return row


def _require_reason(reason: str) -> str:
    #  `ck_audit_sub_fields` buni sxemada ham talab qiladi; bu yerda xato TUSHUNARLI
    #  bo'lsin (IntegrityError o'rniga).
    if not (reason or "").strip():
        raise LifecycleRefused("SUBSCRIPTION_REASON_REQUIRED",
                               "sabab ko'rsatilishi SHART")
    return reason


def plan_terms(db, plan_id) -> tuple[str, int]:
    """`(code, grace_days)` — davr hisobi uchun tarif SHARTLARI.

    ⚠️  `grace_days` TARIFDAN olinadi, kodda qotib qolmaydi. Ilgari hamma chaqiruv
        joyi `0` uzatardi: `grace_until` `current_period_end` ga TENG bo'lib qolar,
        `state.py` dagi GRACE tarmog'i esa HECH QACHON ishlamasdi — ijarachi davr
        chegarasida ogohlantirishsiz bloklanardi, holbuki `policy.py` grace haqida
        «to'lov kechikkan, lekin ish to'xtamaydi» deb turadi.
    """
    row = db.query(Plan.code, Plan.grace_days).filter(Plan.id == plan_id).first()
    if row is None:
        raise LifecycleRefused("PLAN_NOT_FOUND", f"tarif topilmadi: {plan_id}")
    return row[0], int(row[1] or 0)


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now timezone-aware bo'lishi SHART (UTC)")
    return now


# ══ O'tishlar ═══════════════════════════════════════════════════════════════

def enrol(db, *, company_id, plan_id, months: int, actor: Actor, reason: str,
          request_id: str | None = None, now: datetime | None = None,
          commit: bool = True) -> Subscription:
    """Kompaniyani obuna boshqaruviga OLADI (yozuv yo'q -> ACTIVE).

    ⚠️  Ro'yxatga olish ANIQ amal: yozuvi yo'q ijarachi grandfathered qoladi va
        HECH QACHON avtomatik cheklanmaydi (`state.py`).
    """
    _require_reason(reason)
    _assert_owner(db, commit)
    #  IDEMPOTENTLIK KAFOLATI BORMI — YOZUVDAN OLDIN (fail-closed).
    #  ⚠️  `ux_subscriptions_company` «kompaniyaga BITTA qator, umrbod» kontraktini
    #      beradi. U noyob bo'lmasa quyidagi `_lock()` pre-tekshiruvi TOCTOU bo'lib
    #      qoladi: ikki parallel ro'yxatga olish IKKI obuna qatorini yozadi, `state.py`
    #      esa BITTA qatorni kutgani uchun `one_or_none()` da butun do'kon uchun
    #      yiqilardi. Tayyorlik QIZIL bo'lishi bu yozuvni to'smaydi.
    from app.core.index_guard import require_index
    require_index(db, "ux_subscriptions_company", "subscriptions",
                  operation="subscription_enrol")
    at = _now(now)
    if _lock(db, company_id, commit=commit) is not None:
        raise _refuse(db, LifecycleRefused(
            "SUBSCRIPTION_ALREADY_EXISTS", "kompaniyada obuna yozuvi allaqachon bor"),
            commit)
    code, grace_days = plan_terms(db, plan_id)
    end = period_end(at, plan_code=code, months=months)
    sub = Subscription(
        company_id=company_id, plan_id=plan_id, started_at=at,
        current_period_start=at, current_period_end=end,
        grace_until=grace_end(end, grace_days), status=ACTIVE,
        restricted_at=None, cancelled_at=None)
    db.add(sub)
    try:
        #  ⚠️  `_lock` qator YO'Q bo'lganda hech narsani qulflamaydi (`FOR NO KEY
        #      UPDATE` bo'sh natijaga ta'sir qilmaydi), ya'ni ikki parallel `enrol`
        #      ikkalasi ham `None` ko'radi. Kontrakt buzilmaydi —
        #      `ux_subscriptions_company` ikkinchi qatorni to'sadi — lekin yutqazgan
        #      chaqiruv 500 emas, YUQORIDAGI AYNI rad etishni olishi kerak.
        db.flush([sub])
    except IntegrityError as e:
        raise _refuse(db, LifecycleRefused(
            "SUBSCRIPTION_ALREADY_EXISTS",
            "kompaniyada obuna yozuvi allaqachon bor"), commit) from e
    ev = _audit(db, action=ACTION_ENROL, company_id=company_id, target_id=sub.id,
                actor=actor, reason=reason, before=snapshot(None), after=snapshot(sub),
                request_id=request_id)
    _finish(db, commit, [sub, ev])
    return sub


def _transition(db, company_id, *, allowed_from, action, actor, reason, request_id,
                apply, refuse_code, refuse_msg, commit: bool):
    """Umumiy skelet: qulf -> qayta o'qish -> shart -> o'zgartirish -> audit -> commit."""
    _require_reason(reason)
    _assert_owner(db, commit)
    sub = _lock(db, company_id, commit=commit)
    if sub is None:
        raise _refuse(db, LifecycleRefused(
            "SUBSCRIPTION_NOT_FOUND", "kompaniyada obuna yozuvi yo'q"), commit)
    before = snapshot(sub)
    #  ⚠️  Shart QULFDAN KEYINGI baza holatidan tekshiriladi: parallel ikkinchi
    #      chaqiruv shu yerda yutqazadi va AYNAN BIR MARTA bajarilishi ta'minlanadi.
    if sub.status not in allowed_from:
        raise _refuse(db, LifecycleRefused(
            refuse_code, refuse_msg.format(status=sub.status),
            current_status=sub.status), commit)
    try:
        apply(sub)
    except LifecycleRefused as e:
        raise _refuse(db, e, commit) from None
    sub.row_version = (sub.row_version or 0) + 1
    db.flush([sub])
    ev = _audit(db, action=action, company_id=company_id, target_id=sub.id, actor=actor,
                reason=reason, before=before, after=snapshot(sub), request_id=request_id)
    _finish(db, commit, [sub, ev])
    return sub


def restrict(db, *, company_id, actor: Actor, reason: str,
             request_id: str | None = None, now: datetime | None = None,
             commit: bool = True) -> Subscription:
    """ACTIVE -> RESTRICTED (qo'lda, intizomiy cheklov)."""
    at = _now(now)

    def apply(sub):
        sub.status, sub.restricted_at = RESTRICTED, at

    return _transition(db, company_id, allowed_from=(ACTIVE,), action=ACTION_RESTRICT,
                       actor=actor, reason=reason, request_id=request_id,
                       apply=apply, commit=commit,
                       refuse_code="SUBSCRIPTION_NOT_ACTIVE",
                       refuse_msg="cheklash uchun obuna ACTIVE bo'lishi kerak (hozir {status})")


def restore(db, *, company_id, actor: Actor, reason: str,
            request_id: str | None = None, now: datetime | None = None,
            commit: bool = True) -> Subscription:
    """RESTRICTED -> ACTIVE (qo'ldagi cheklovni yechish).

    ⚠️  SAQLANGAN `status` tekshiriladi. `CANCELLED` qator `state.py` da
        `RESTRICTED` ko'rinishida chiqadi — bu yerda u RAD ETILADI, aks holda
        `restore()` bekor qilingan obunani tiriltiradigan ikkinchi yo'l bo'lardi.
    """
    _ = _now(now)

    def apply(sub):
        if sub.restricted_at is None:
            #  Zid qator: `state.py` uni baribir cheklangan deb hisoblaydi, lekin
            #  `restore` uni JIMGINA «tuzatib» yubormasin — operator ko'rib chiqsin.
            raise LifecycleRefused(
                "SUBSCRIPTION_RESTRICTION_INCONSISTENT",
                "status RESTRICTED, lekin restricted_at bo'sh — qo'lda ko'rib chiqing",
                current_status=sub.status)
        sub.status, sub.restricted_at = ACTIVE, None

    return _transition(db, company_id, allowed_from=(RESTRICTED,), action=ACTION_RESTORE,
                       actor=actor, reason=reason, request_id=request_id,
                       apply=apply, commit=commit,
                       refuse_code="SUBSCRIPTION_NOT_RESTRICTED",
                       refuse_msg="tiklash uchun obuna RESTRICTED bo'lishi kerak (hozir {status})")


def cancel(db, *, company_id, actor: Actor, reason: str,
           request_id: str | None = None, now: datetime | None = None,
           commit: bool = True) -> Subscription:
    """ACTIVE|RESTRICTED -> CANCELLED."""
    at = _now(now)

    def apply(sub):
        #  `ck_sub_restricted_iff` talabi: CANCELLED da `restricted_at` bo'sh bo'lsin.
        sub.status, sub.cancelled_at, sub.restricted_at = CANCELLED, at, None

    return _transition(db, company_id, allowed_from=(ACTIVE, RESTRICTED),
                       action=ACTION_CANCEL, actor=actor, reason=reason,
                       request_id=request_id, apply=apply, commit=commit,
                       refuse_code="SUBSCRIPTION_ALREADY_CANCELLED",
                       refuse_msg="obuna bekor qilib bo'lmaydi (hozir {status})")


def reactivate(db, *, company_id, plan_id, months: int, actor: Actor, reason: str,
               request_id: str | None = None, now: datetime | None = None,
               commit: bool = True) -> Subscription:
    """CANCELLED -> ACTIVE — bekor qilingan obunani QAYTA ishga tushirishning YAGONA yo'li.

    ⚠️  Yangi davr `now` dan BOSHLANADI. Eski `current_period_end` baza sifatida
        ISHLATILMAYDI: bekor qilingan davrni «uzaytirish» mijozga to'lanmagan
        oylarni sovg'a qilardi.
    ⚠️  `started_at` O'ZGARMAYDI — u «mijoz qachondan beri bizda» degan javob.
        Davr boshi uchun `current_period_start` bor.
    ⚠️  `plan_id` va `months` ANIQ beriladi, eski qatordan meros olinmaydi.
    """
    _require_reason(reason)
    _assert_owner(db, commit)
    at = _now(now)
    code, grace_days = plan_terms(db, plan_id)

    def apply(sub):
        end = period_end(at, plan_code=code, months=months)
        sub.plan_id = plan_id
        sub.current_period_start = at
        sub.current_period_end = end
        sub.grace_until = grace_end(end, grace_days)
        sub.status = ACTIVE
        #  `ck_sub_cancelled_iff` talabi: ACTIVE da `cancelled_at` bo'sh. Bekor
        #  qilish FAKTI `admin_audit_log` da qoladi — qator joriy holatni saqlaydi.
        sub.cancelled_at = None
        sub.restricted_at = None

    return _transition(db, company_id, allowed_from=(CANCELLED,),
                       action=ACTION_REACTIVATE, actor=actor, reason=reason,
                       request_id=request_id, apply=apply, commit=commit,
                       refuse_code="SUBSCRIPTION_NOT_CANCELLED",
                       refuse_msg="qayta faollashtirish uchun obuna CANCELLED "
                                  "bo'lishi kerak (hozir {status})")
