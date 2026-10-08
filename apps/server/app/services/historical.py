# -*- coding: utf-8 -*-
"""H1 — TARIXIY BAJARISH KONTEKSTI (Demo Store Engine poydevori).

NIMA UCHUN
==========
Demo do'konga 90–120 kunlik real ko'rinishli tarix kerak: oylab sotuv, smena,
xarid, qaytarish, sanoq, hisobdan chiqarish, kassa va mijoz qarzi. Bu tarix
KANONIK BinOS servislari bilan yozilishi SHART — aks holda demo ma'lumoti
haqiqiy invariantlarga bo'ysunmaydi va «BinOS shunday ishlaydi» degan ko'rsatuv
yolg'on bo'ladi.

Lekin kanonik yozuvchilar «hozir» ni muhrlaydi. Shu bois tarixiy bajarish uchun
IKKI narsa kerak: (a) orqaga sanalgan vaqtni uzatish yo'li, (b) o'sha yo'lni
oddiy POS/mobil sirtidan YETIB BO'LMAYDIGAN qilish.

BU MODUL (a) NI EMAS, (b) NI VA UNING ATROFINI BERADI — H1 doirasi:
  · tarixiy bajarish KONTEKSTI (so'rov-doirali);
  · AVTORITET demo-tenant darvozasi;
  · tashqi effektlarni so'rov-doirali BO'G'ISH siyosati;
  · idempotentlik kalitlari (deterministik, tenant doirasida).

⚠️  BU MODUL BIRORTA YOZUVCHIGA `at=` QO'SHMAYDI. Yozuvchilarga vaqt uzatish —
    H2 ishi. H1 faqat poydevor: kontekst, darvoza, bo'g'ish, idempotentlik.

⚠️  NORMAL POS/MOBIL SIRTI TEGILMAYDI. Bu modul birorta mavjud so'rov sxemasiga
    maydon qo'shmaydi va birorta marshrut xulqini o'zgartirmaydi.
    `/sync/push` dagi 60-kunlik klamp ham TEGILMAYDI (`api/v1/sync.py:30-40`) —
    tarixiy bajarish u yo'ldan EMAS, privilegiyali kontekstdan yuradi.

NEGA ContextVar
===============
FastAPI sinxron endpoint'ni threadpool'da chaqiradi, ya'ni parallel so'rovlar
bir-birining bayrog'ini KO'RMASLIGI shart. Repoda bu naqsh allaqachon bor va
AYNI sabab bilan izohlangan: `services/cash/cutover_guard.py:91-94`
(`_PREVIEW` — `set()`/`reset(token)` juftligi `try/finally` ichida). Shu bois
bu yerda ikkinchi mexanizm O'YLAB TOPILMAYDI — o'sha naqsh takrorlanadi.

FAIL-CLOSED POLYARLIGI
======================
Kontekst YO'Q bo'lsa — hamma narsa ODDIY holatda: tashqi effektlar YONIQ,
tarixiy ruxsat YO'Q. Ya'ni kontekstning o'zi — ruxsat berishning YAGONA yo'li,
va unga kirish faqat `enter()` orqali, darvozadan o'tgandan KEYIN.
Bu loyiha konvensiyasiga mos: o'zgaruvchi/kontekst yo'qligi HECH QACHON ruxsat
bermasin (`core/security_config.py` fail-open standartlari).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

# ── DEMO TENANT KOD PREFIKSLARI — YAGONA TA'RIF ────────────────────────────
#  `api/v1/admin.py` dagi `seed-demo` darvozasi AYNI predikatni ishlatadi
#  (import qiladi, nusxalamaydi): ikki joyda ikki xil ro'yxat bo'lsa, biri
#  yangilanib ikkinchisi qolib ketardi va «himoyalangan» do'kon himoyasiz
#  bo'lardi.
DEMO_CODE_PREFIXES = ("test", "demo")

#  Kelajakka yozishga tolerantlik: tarixiy bajarish ATAYLAB o'tmishga yozadi.
#  Soat siljishi uchun kichik oyna (`api/v1/shifts.py:469` dagi
#  `CLOCK_FUTURE_TOLERANCE_S` bilan AYNI ruh).
FUTURE_TOLERANCE = timedelta(minutes=5)

#  Idempotentlik kalitlari uchun BARQAROR ildiz. O'ZGARTIRILMAYDI — o'zgarsa
#  avval yozilgan rejalarning kalitlari boshqa chiqib, qayta yurish DUBLIKAT
#  yozardi (uuid5 deterministik, ya'ni ildiz ham shartnomaning qismi).
_PLAN_NS = uuid.UUID("b1a05e3a-0000-5000-8000-62696e6f7348")   # oxirgi guruh = "binosH"


@dataclass(frozen=True)
class HistoricalContext:
    """Bitta tarixiy lahzani bajarish konteksti (o'zgarmas).

    `instant` — AYNAN shu hodisa sodir bo'lgan (deb e'lon qilinayotgan) UTC payt.
    `plan_id` — BusinessDayPlan identifikatori; idempotentlik kalitlari shundan
    keltirib chiqariladi, ya'ni AYNI reja qayta yurilsa AYNI kalitlar chiqadi.
    """
    company_id: uuid.UUID
    plan_id: str
    instant: datetime

    def key(self, *parts: str) -> uuid.UUID:
        """Shu kontekst uchun deterministik hodisa kaliti (qarang `event_key`)."""
        return event_key(self.company_id, self.plan_id, *parts)


# ⚠️  So'rov-doirali. Standart `None` — ya'ni ODDIY holat (qarang modul sarlavhasi).
_CTX: ContextVar[HistoricalContext | None] = ContextVar("binos_historical", default=None)


# ── O'QISH ──────────────────────────────────────────────────────────────────

def active() -> HistoricalContext | None:
    """Joriy so'rovda tarixiy kontekst bormi (bo'lmasa `None`)."""
    return _CTX.get()


def require_active() -> HistoricalContext:
    """Kontekst SHART bo'lgan joylar uchun. Bo'lmasa — dasturchi xatosi.

    ⚠️  `HTTPException` EMAS: bu holat mijoz kirishidan kelib chiqmaydi, u
        chaqiruvchi kodning xatosi (kontekstdan tashqarida tarixiy yozuvchini
        chaqirish). Mijozga 400 berish bu xatoni YASHIRARDI.
    """
    ctx = _CTX.get()
    if ctx is None:
        raise RuntimeError(
            "tarixiy bajarish konteksti YO'Q — bu funksiya faqat "
            "`historical.enter(...)` ichida chaqirilishi mumkin")
    return ctx


def instant() -> datetime | None:
    """Tarixiy lahza yoki `None` (kontekst yo'q)."""
    ctx = _CTX.get()
    return ctx.instant if ctx is not None else None


def suppress_external() -> bool:
    """Tashqi effektlar BO'G'ILSINmi.

    ⚠️  POLYARLIK: faqat tarixiy kontekst ICHIDA `True`. Kontekst yo'q — `False`,
        ya'ni oddiy ishlashda birorta bildirishnoma YO'QOLMAYDI. Bo'g'ish
        kontekstga ULANGAN va kontekstga kirish darvozadan o'tishni talab
        qiladi — shu bois bu bayroqni «tasodifan» yoqib bo'lmaydi.

    H1 doirasida yagona tashqi effekt — FCM kam-qoldiq push'i
    (`services/push.py:notify_low_stock`), replay yo'llaridagi ikki chaqiruv
    joyi: `services/sales.py:1010` va `api/v1/inventory.py:152`. Manbadagi
    qolgan ikki tashqi chaqiruv replay yozuv yo'llarida EMAS:
      · `services/xpay.py` — faqat `api/v1/payments.py` dan; sotuv yo'li
        `QrPayment` ni MAHALLIY o'qiydi va iste'mol qiladi, tashqariga
        chiqmaydi (`services/sales.py:846-856` izohi);
      · `services/receiving_ai.py` — faqat `api/v1/receiving.py:57,66`
        (AI-o'qish marshruti), `_commit_once` (188–539) ICHIDA EMAS.
    """
    return _CTX.get() is not None


def assert_gate(at: datetime | None, company_id) -> None:
    """`at` ni FAQAT DARVOZA bo'yicha tekshiradi — SOATNI O'QIMAYDI.

    ⚠️  NEGA `resolve_at` DAN AJRATILGAN (H3b topilmasi). Ba'zi yozuvchilarda
        soat NAMUNA OLISH nuqtasi ataylab KECH (qulflardan keyin, yozuv
        qurilishidan darhol oldin) — `cash_op` va `pay_credit` shunday. Agar
        darvoza ham o'sha kech nuqtada ishlasa, kontekstSIZ berilgan `at`
        jimgina QABUL qilinib, keyinroq BUTUNLAY BOSHQA sabab bilan rad
        etilardi (masalan «Ochiq smena yo'q») — ya'ni xato CHALG'ITUVCHI
        bo'lardi va rad etishdan oldin ish bajarilgan bo'lardi. O'LCHANGAN:
        `_cash_op_once` ga kontekstsiz `at` berilganda aynan shu bo'ldi.
        Endi yozuvchi DARVOZANI eng boshida, SOATNI esa o'z joyida chaqiradi.

    ⚠️  `at is None` bo'lsa HECH NARSA qilmaydi: normal yo'l bu funksiyadan
        ta'sir OLMAYDI.
    """
    if at is None:
        return
    ctx = _CTX.get()
    if ctx is None:
        raise RuntimeError(
            "tarixiy vaqt (`at`) berildi, lekin tarixiy kontekst YO'Q — tarixiy "
            "yozuv faqat `historical.enter(...)` ichida mumkin")
    if ctx.company_id != company_id:
        raise RuntimeError(
            f"tarixiy kontekst BOSHQA do'konga tegishli: kontekst={ctx.company_id} "
            f"yozuv={company_id}")


def resolve_at(at: datetime | None, company_id) -> datetime:
    """Yozuvchilar uchun YAGONA vaqt nuqtasi: `at` berilmasa HOZIR, berilsa — darvozali.

    Bu funksiya H2 ning butun xavfsizligi yotgan joyi. Qoida:

      · `at is None`  -> `datetime.now(timezone.utc)`. ODDIY yo'l. Normal POS
        marshruti AYNAN shu holatda ishlaydi va uning semantikasi O'ZGARMAYDI.
      · `at is not None` -> tarixiy kontekst FAOL bo'lishi SHART va u AYNI
        do'konga tegishli bo'lishi SHART. Aks holda — xato.

    ⚠️  NEGA KONTEKST TEKSHIRILADI, `at` ning O'ZI yetarli emas. Agar yozuvchi
        `at` ni shartsiz qabul qilsa, u yozuvchini chaqiradigan HAR QANDAY yo'l
        (bugun yoki ertaga qo'shiladigan marshrut, servis, skript) tarixiy yozuv
        qobiliyatini OLGAN bo'lardi. Kontekst esa faqat `enter()` orqali
        ochiladi, `enter()` esa demo-tenant darvozasidan o'tadi. Ya'ni tarixiy
        qobiliyat MARSHRUTGA emas, DARVOZAGA bog'langan.

    ⚠️  DO'KON MOSLIGI ham tekshiriladi: bitta do'kon kontekstida turib
        boshqa do'konga tarixiy yozuv qilib bo'lmaydi.

    ⚠️  `RuntimeError`, `HTTPException` EMAS: bu holat mijoz kirishidan kelib
        chiqmaydi (normal marshrut `at` ni UMUMAN uzatmaydi). Bu kod xatosi yoki
        darvozani chetlab o'tish urinishi — ikkisi ham 400 bilan yashirilmaydi.
    """
    if at is None:
        return datetime.now(timezone.utc)
    assert_gate(at, company_id)
    #  ⚠️  KANONIK UTC. Aware qiymat ham `astimezone(utc)` bilan keltiriladi,
    #      shunchaki qaytarilmaydi. SABABI O'LCHANGAN: SQLite
    #      `DateTime(timezone=True)` ni saqlaganda `tzinfo` ni JIMGINA tashlab,
    #      DEVOR-SOATINI matn qilib yozadi. Ya'ni `+05:00` payt saqlansa, keyin
    #      u UTC deb o'qilib, hamma solishtirish 5 soat xato bo'lardi —
    #      xronologiya gardi (`assert_chronological`) esa aynan shu
    #      solishtirishga tayanadi. Postgres `timestamptz` da bu NO-OP
    #      (instant bir xil), ya'ni mavjud xulq o'zgarmaydi.
    if at.tzinfo is None:
        return at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)


# ── DEMO TENANT DARVOZASI (AVTORITET) ──────────────────────────────────────

def _as_utc(dt: datetime | None) -> datetime | None:
    """Naive datetime'ni UTC deb o'qiydi. SQLite `DateTime(timezone=True)` ni
    NAIVE qaytaradi — aware bilan solishtirish `TypeError` berardi."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def require_at(at: datetime | None, *, writer: str) -> None:
    """Tarixiy kontekst FAOL bo'lsa yozuvchiga `at` berilishi SHART.

    ⚠️  NEGA `at is not None` DARVOZASI YETARLI EMAS: kontekst ichida `at` ni
        UZATISHNI UNUTISH ham xato. U holda yozuvchi jimgina HOZIRGI vaqt
        bilan yozardi va xronologiya gardining o'zi ma'nosiz bo'lib qolardi
        (`MAX(stock_movements.created_at)` BUGUNGA sakrab, keyingi tarixiy
        yozuvlarni yolg'on rad etardi).

    ⚠️  NEGA BU TEKSHIRUV SHU MODULDA, YOZUVCHI ICHIDA EMAS:
        `tests/test_lot_error_texts.py` partiya/ombor yo'llaridagi HAR xato
        ko'taruvchini registrda bo'lishga majburlaydi va matnini frontend
        tarjima lug'atida talab qiladi — chunki o'sha yo'llardagi xatolar
        OPERATOR ko'radigan matn. Bu xato esa operatorga HECH QACHON yetib
        bormaydi (marshrut `at` uzatmaydi; u reja/bajaruvchi nuqsoni), shu
        bois uni o'sha registrga qo'shish lug'atdan hech kim ko'rmaydigan
        matn uchun tarjima talab qilardi. To'g'ri yechim — gardni bo'shatish
        emas, xatoni skanerlanmaydigan QATLAMGA, tarixiy kontrakt uyiga
        qo'yish.
    """
    if at is None:
        raise RuntimeError(
            f"tarixiy kontekst FAOL, lekin `{writer}` yozuvchisiga `at` "
            "berilmadi — tarixiy yozuvni HOZIRGI vaqt bilan muhrlab bo'lmaydi")


def assert_chronological(db: Session, *, branch_id, product_ids, at: datetime) -> None:
    """MUTLAQ (delta emas) tarixiy yozuv uchun XRONOLOGIYA gardi.

    NEGA FAQAT MUTLAQ YOZUVCHIGA KERAK
    ==================================
    `inventory.qty` ni DELTA bilan o'zgartiradigan yozuvchilar (sotuv, qabul,
    xarid, ko'chirish) KOMMUTATIV: qanday tartibda qo'llanilsa ham YAKUNIY
    qoldiq bir xil chiqadi. MUTLAQ yozuvchi esa joriy qiymatni BOSIB o'tadi
    (sanalgan qiymatni `inv.qty` ga BOSIB yozadi), shu bois u faqat O'Z
    PAYTIDA qo'llanilsa to'g'ri.

    ⚠️  IZOH USLUBI MAJBURIY: bu faylda qoldiq o'zlashtirishini SO'ZMA-SO'Z
        keltirib bo'lmaydi. `test_lot_receiving.py` va
        `test_legacy_receiving_gate.py` qoldiq yozuvchilarini MANBA MATNI
        bo'yicha (nuqta-`qty`-tenglik naqshi; izohlar ham qamraladi) topadi va
        ularni registrda bo'lishga majburlaydi. Bu fayl qoldiqni YOZMAYDI —
        faqat O'QIYDI — shu bois to'g'ri yechim registrni bo'shatish emas,
        izohni naqshga tushmaydigan qilib yozish.

    TARTIBSIZ QO'LLANILSA NIMA BO'LADI
    ==================================
    Inventarizatsiya `diff = counted - old` ni hisoblaydi, bunda `old` — YOZUV
    PAYTIDAGI qoldiq. Agar D kunidagi inventarizatsiya D+5 hodisasidan KEYIN
    yozilsa:
      · `inv.qty` D+5 ning ta'sirini YO'Q qiladi — qoldiq YOLG'ON bo'ladi;
      · `diff` eskirgan bazaga nisbatan hisoblanadi va ISHORASI almashishi
        mumkin — kamomad ledger'ga ORTIQCHA bo'lib yoziladi, ya'ni
        inventarizatsiya topish uchun mavjud bo'lgan farqning YAGONA yozuvi
        teskari bo'ladi.

    ⚠️  VA BUNI HECH NARSA KO'RSATMAYDI. `inventory.qty` yoki
        `stock_movements.balance_after` ustida CHECK yo'q; harakatlar
        yig'indisini qoldiq bilan solishtiradigan kod butun repo'da YO'Q;
        `stock_invariant` esa FAZOVIY tekshiruv (partiya yig'indisi == qoldiq)
        va u YOLG'ON qiymat USTIDA bir tranzaksiya ichida izchil ushlanadi,
        ustiga kuzatuvsiz mahsulotni UMUMAN ko'rmaydi. Ya'ni bu JIM buzilish.

    NIMANI SOLISHTIRADI
    ===================
    Har (mahsulot, filial) uchun `MAX(stock_movements.created_at)` — O'ZGARMAS
    fakt-ledger, ya'ni kanonik xronologiya — tarixiy paytga nisbatan. QAT'IY
    `>` da rad etiladi: TENGLIK ayni paytdagi qardosh hodisa va u
    idempotentlik kalitiga tegishli, xronologiyaga emas.

    ⚠️  `inventory.updated_at` ATAYLAB ishlatilmaydi: u "oxirgi tegilgan vaqt",
        ya'ni o'zgaruvchan va yozuvchilar intizomiga tayanadi. `stock_movements`
        esa immutable.

    ⚠️  BU PRE-CHECK, KONKURRENTLIK KAFOLATI EMAS. Qulflardan OLDIN chaqiriladi
        (fayl konvensiyasi: rad etish birorta qator qulflanmasdan bo'lsin), shu
        bois TOCTOU oynasi BOR. U faqat tarixiy kontekstda ishlaydi va tarixiy
        executor KETMA-KET — H2 `Shift.client_uuid` pre-check'i uchun aynan shu
        asosni yozgan. Konkurrent kafolat deb HUJJATLASHTIRILMASIN.

    ⚠️  `autoflush=False` (`db/session.py:72`). Ya'ni oldingi hodisa yozgan,
        lekin hali FLUSH qilinmagan harakatlarni SELECT KO'RMAYDI — bu loyihada
        aynan shu mexanizm `on_cash_sale` ni jim ishlamas qilgan. Shu bois
        kutilayotgan (`db.new`) harakatlar ham ALOHIDA tekshiriladi: gard SQL
        yubormasdan ham to'liq qaraydi (flush qilish gardni YOZUVCHI qilardi).
    """
    from sqlalchemy import func, select

    from app.models.inventory import StockMovement

    pids = [p for p in dict.fromkeys(product_ids) if p is not None]
    if not pids:
        return
    #  Solishtirish KANONIK UTC da. `resolve_at` buni allaqachon qiladi, lekin
    #  gard unga TAYANMAYDI: u to'g'ridan ham chaqirilishi mumkin.
    at_u = _as_utc(at)
    at_u = at_u.astimezone(timezone.utc)

    #  ⚠️  AVVAL FLUSH — `autoflush=False` (`db/session.py`). Oldingi hodisa
    #      `db.add` qilgan, lekin hali flush qilinmagan harakatlarni SELECT
    #      KO'RMAYDI va gard eskirgan `MAX` ni o'qib JIMGINA o'tib ketardi. Bu
    #      loyihada aynan shu mexanizm `on_cash_sale` ni ishlamas qilgan
    #      (Phase 2.5 darsi) va ayni sabab bilan flush qilinadigan uch joy bor:
    #      `api/v1/sales.py`, `services/lot_return.py`, `services/lot_correction.py`.
    #  ⚠️  HALOL CHEKLOV: demak gard SOF o'quvchi emas. Sanoqning O'ZIDAN hali
    #      hech narsa kutilmaydi (gard birinchi mutatsiyadan oldin turadi), shu
    #      bois bu yozuvchi uchun flush NO-OP; u faqat CHAQIRUVCHI uzatgan
    #      kutilayotgan qatorlarni yozadi — va aynan shu probani to'g'ri qiladi.
    db.flush()

    #  Bitta so'rov, `ix_stockmov_product_created` (`initdb.py`) bilan qoplangan.
    rows = db.execute(
        select(StockMovement.product_id, func.max(StockMovement.created_at))
        .where(StockMovement.product_id.in_(pids),
               StockMovement.branch_id == branch_id)
        .group_by(StockMovement.product_id)).all()
    latest: dict = {}
    for pid, mx in rows:
        latest[str(pid)] = _as_utc(mx)

    for pid in pids:
        mx = latest.get(str(pid))
        if mx is not None and mx > at_u:
            raise RuntimeError(
                "TARTIBSIZ tarixiy yozuv RAD etildi: mahsulot "
                f"{pid} uchun {mx.isoformat()} paytidagi zaxira harakati "
                f"ALLAQACHON yozilgan, yangi yozuv esa {at_u.isoformat()} "
                "paytiga tegishli. MUTLAQ yozuvchi (inventarizatsiya) faqat "
                "QAT'IY XRONOLOGIK tartibda to'g'ri ishlaydi — reja hodisalarini "
                "payt bo'yicha GLOBAL tartiblang.")


def is_demo_code(code: str | None) -> bool:
    """Do'kon kodi demo/test prefiksidami — YAGONA predikat (qarang yuqori).

    ⚠️  `strip()` ATAYLAB YO'Q. `api/v1/admin.py:731-732` dagi mavjud darvoza
        `(c.code or "").lower().startswith(...)` ni ishlatadi; bo'shliqni
        kesish predikatni BO'SHATARDI (`" test1"` asl darvozada RAD etiladi,
        kesilganda O'TARDI). Qayta ishlatish BAYT-AYNAN bo'lishi shart —
        darvozani «tozalash» niyatida bo'shatib qo'yish mumkin emas.
    """
    return (code or "").lower().startswith(DEMO_CODE_PREFIXES)


def assert_demo_tenant(db: Session, company, *, require_empty_history: bool) -> None:
    """Bu do'konga TARIXIY yozuv mumkinmi — AVTORITET darvoza. Mumkin bo'lmasa otadi.

    TO'RT shart, hammasi MAJBURIY:

      1. do'kon BOR va o'chirilmagan;
      2. kodi `test`/`demo` prefiksli — haqiqiy do'kon himoyalangan
         (`api/v1/admin.py:731-733` bilan AYNI predikat, AYNI manbadan);
      3. `require_empty_history` bo'lsa — do'konda BIRORTA haqiqiy savdo YO'Q.
         Kod prefiksi YOLG'IZ YETARLI EMAS: onboarding paytida do'konga
         `test-fayzan` kabi kod berish TABIIY va shundan keyin tarixiy yozuv
         jonli hisobotlarni buzardi (`admin.py:735-751` dagi AYNI dars);
      4. `cash` T0 (cutover_at) BELGILANMAGAN.

    ⚠️  4-SHART — EGA TALABI VA ARXITEKTURA SHARTI, kod o'zgarishi EMAS.
        `cash/cutover_guard.enforcement_active` → `cash/cutover.cutover_at(db,
        company_id)`: T0 `None` bo'lsa butun tenant LEGACY rejimda va
        `reject_closed_shift_replay` / `require_post_t0_till` UMUMAN yonmaydi.
        T0 belgilangan tenantda esa yopilgan tarixiy smenaga naqd yozish
        ATAYLAB rad etiladi (`services/sales.py:429-431`: klient `sold_at` i
        buxgalteriya vaqti bo'lib qoladi, lekin T0 darvozasini OCHMAYDI — aks
        holda POS eski sana yozib post-T0 naqdni TILL'siz kiritaverardi).
        O'sha anti-abuse qarori BUZILMAYDI: biz uni chetlab o'tmaymiz, balki
        T0 qo'yilmagan tenantni TALAB qilamiz.
    """
    if company is None or getattr(company, "deleted_at", None) is not None:
        raise HTTPException(404, "Do'kon topilmadi")
    if not is_demo_code(getattr(company, "code", None)):
        raise HTTPException(
            400, "Tarixiy yozuv FAQAT 'test'/'demo' kodli do'konga ruxsat "
                 "(haqiqiy do'kon himoyalangan)")
    if require_empty_history:
        from app.models.sales import Sale as _Sale
        if db.query(_Sale.id).filter(_Sale.company_id == company.id).first() is not None:
            raise HTTPException(
                409, "Bu do'konda ALLAQACHON savdo bor — tarixiy yozuv RAD ETILDI. "
                     "Tarix faqat BO'SH do'konga qo'shiladi (aks holda haqiqiy "
                     "hisobotlar soxta ma'lumot bilan aralashib ketardi).")
    from app.services.cash import cutover as _cut
    t0 = _cut.cutover_at(db, company.id)
    if t0 is not None:
        raise HTTPException(
            409, "Bu do'konda kassa T0 (cutover) belgilangan — tarixiy yozuv RAD "
                 "ETILDI. Yopilgan tarixiy smenaga naqd yozish ATAYLAB "
                 "taqiqlangan; tarixiy demo faqat T0 belgilanMAGAN do'konda "
                 f"quriladi (T0={t0.isoformat()}).")


# ── KONTEKSTGA KIRISH — YAGONA YO'L ────────────────────────────────────────

@contextmanager
def enter(db: Session, company, *, plan_id: str, instant: datetime,
          require_empty_history: bool = False):
    """Tarixiy bajarish kontekstini OCHADI (darvozadan o'tgandan keyin).

    Bu — kontekstga kirishning YAGONA yo'li. `_CTX` ni boshqa hech qayerda
    `set()` qilinmaydi, ya'ni oddiy POS so'rovida kontekst PAYDO BO'LA OLMAYDI.

    `try/finally` + `reset(token)` — `cutover_guard._PREVIEW` (satr 154/163)
    bilan AYNI naqsh: chaqiruv ichida xato chiqsa ham bayroq OQIB KETMAYDI.
    """
    assert_demo_tenant(db, company, require_empty_history=require_empty_history)

    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if instant > now + FUTURE_TOLERANCE:
        raise HTTPException(
            400, "Tarixiy lahza KELAJAKDA — tarixiy bajarish faqat o'tmishga "
                 "yozadi. Reja sanasini tekshiring.")
    pid = (plan_id or "").strip()
    if not pid:
        raise HTTPException(400, "plan_id MAJBURIY — idempotentlik kalitlari "
                                 "undan keltirib chiqariladi")

    prev = _CTX.get()
    if prev is not None and prev.company_id != company.id:
        # Ichma-ich kontekst BOSHQA do'konga — bu dasturchi xatosi va jim
        # qolsa bir do'konning hodisasi boshqasiga yozilardi.
        raise RuntimeError(
            f"tarixiy kontekst ichma-ich va BOSHQA do'kon: {prev.company_id} -> {company.id}")

    tok = _CTX.set(HistoricalContext(company_id=company.id, plan_id=pid, instant=instant))
    try:
        yield _CTX.get()
    finally:
        _CTX.reset(tok)


# ── IDEMPOTENTLIK KALITLARI ────────────────────────────────────────────────

def plan_namespace(company_id, plan_id: str) -> uuid.UUID:
    """Reja uchun nom maydoni — DO'KON va REJA bo'yicha ajratilgan.

    ⚠️  DO'KON KALITGA KIRADI. Yozuvchilarning noyoblik indekslari
        `(company_id, client_uuid)` juftligi bo'yicha (masalan
        `ux_sales_company_client_uuid`), ya'ni kalit allaqachon tenant
        doirasida. Shunga qaramay do'konni nom maydoniga KIRITAMIZ: shunda
        ikki do'konda AYNI reja yurgizilsa ham kalitlar ustma-ust tushmaydi
        va kalit birovning do'konida «allaqachon bor» bo'lib qolmaydi.
    """
    return uuid.uuid5(_PLAN_NS, f"{company_id}:{plan_id}")


def event_key(company_id, plan_id: str, *parts: str) -> uuid.UUID:
    """Bitta rejalashtirilgan hodisa uchun DETERMINISTIK `client_uuid`.

    `parts` — hodisani reja ichida YAGONA qiladigan bo'laklar, masalan
    `("d-087", "sale", "03")`. Ayni reja + ayni bo'laklar -> AYNI uuid, ya'ni
    rejani QAYTA yurgizish yozuvchilarning mavjud dedup yo'lidan o'tadi va
    DUBLIKAT yozilmaydi.

    ⚠️  NOL UUID QAYTARILMAYDI. `/sync/push` nol kalitni ataylab rad etadi
        (`api/v1/sync.py:80-85`), shu bois bu yerda ham nol chiqsa — xato.
        uuid5 amalda nol bermaydi; tekshiruv shartnomani YOZIB qo'yish uchun.
    """
    if not parts:
        raise RuntimeError("event_key: kamida bitta bo'lak kerak")
    out = uuid.uuid5(plan_namespace(company_id, plan_id), ":".join(str(p) for p in parts))
    if out.int == 0:
        raise RuntimeError("event_key: nol UUID — kalit sifatida yaroqsiz")
    return out
