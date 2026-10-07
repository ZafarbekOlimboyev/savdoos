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
    ctx = _CTX.get()
    if ctx is None:
        raise RuntimeError(
            "tarixiy vaqt (`at`) berildi, lekin tarixiy kontekst YO'Q — tarixiy "
            "yozuv faqat `historical.enter(...)` ichida mumkin")
    if ctx.company_id != company_id:
        raise RuntimeError(
            f"tarixiy kontekst BOSHQA do'konga tegishli: kontekst={ctx.company_id} "
            f"yozuv={company_id}")
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


# ── DEMO TENANT DARVOZASI (AVTORITET) ──────────────────────────────────────

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
