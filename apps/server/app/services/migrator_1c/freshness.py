# -*- coding: utf-8 -*-
"""Cutover kesimining YANGILIGI — BIRINCHI apply uchun ham ishlaydigan darvoza.

NEGA KERAK. Mavjud eskirganlik darvozasi (`apply.py` — `StaleSnapshotError`) faqat OLDIN
qo'llangan job'lar bilan solishtiradi. Yangi ijarachida bunday job YO'Q, demak ixtiyoriy darajada
eski kesim ham bemalol o'tardi — va bu aynan CUTOVER, ya'ni yagona muhim yurish.

NIMANI TEKSHIRADI. `snapshot_at` (manba kesimi) bilan HOZIRGI vaqt orasidagi farq.
`exported_at` tekshirilmaydi: yosh faqat kesimdan hisoblanadi, fayl qachon yozilgani ahamiyatsiz.

⚠️ NIMANI ISBOTLAMAYDI. Bu darvoza E'LON QILINGAN yoshni o'lchaydi. Bugungi lahzani o'tgan
haftaning nusxasiga yozib qo'ygan ekstraktor undan bemalol o'tadi — kod buni tuta olmaydi.
Uchta himoya ALOHIDA va biri ikkinchisining o'rnini bosmaydi:
    1. yangilik darvozasi (shu modul) — e'lon qilingan yosh;
    2. `source_copy` provenansi — QAYSI nusxa ishlatilgani (lekin u QACHON olinganini emas);
    3. administratorning yozma qaydi — nusxa QACHON olingani.

CHEGARA QAYERDAN OLINGAN (24 soat). Bu bosqichlar yig'indisiga moslashtirilgan raqam EMAS,
balki YUQORI CHEGARA. Runbook freeze oynasining uzunligini ikki joyda «NOMA'LUM» deb yozadi, va
copy-first qo'shgan bosqichlar (nusxa ko'chirish, tiklash, yig'uvchi) uchun repoda birorta daqiqa
yo'q. Hujjatlangan qism: nusxa 30–60 daq + 4–8 qadamlar 30–90 daq. Shu bois pastroq har qanday
raqam — o'ylab topilgan bo'lardi, va uni past qo'yishning narxi qimmat: darvoza soat 03:00 da,
do'kon yopiq, egasi yonida turganda TO'G'RI cutover'ni rad etadi.
24 soat esa printsipial: savdo qiladigan do'konda 24 soatlik har qanday oraliq ALBATTA bitta
ochilishni o'z ichiga oladi, ya'ni bu qiymat «savdo bo'lib o'tgan» degan yagona haqiqiy shartni
hali ham ifodalaydi. Undan kattasi uni ifodalamay qo'yadi.

KELAJAKDAGI KESIM. Do'kon kassasi soati bir necha daqiqa oldinda yurishi — ODDIY hol, va u
`snapshot_at` ni serverning hozirgi vaqtidan kelajakka chiqarib qo'yadi. Shu bois kelajak
tomonga keng tolerantlik bor; undan ham oshsa — bu soat nosozligi, va u ham voz kechilishi mumkin,
chunki aks holda do'konning noto'g'ri soati cutover'ni chiqib bo'lmas holga solib qo'yardi.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: Cutover kesimining maksimal yoshi. Yuqori chegara (yuqoridagi izohga qarang).
MAX_SNAPSHOT_AGE = timedelta(hours=24)

#: Kesim serverning hozirgi vaqtidan shuncha oldinda bo'lishi ODDIY (do'kon soati oldinda yuradi).
FUTURE_TOLERANCE = timedelta(hours=2)

#: ⚠️ VOZ KECHISH O'CHIRILGAN (2026-09-28, egasining qarori).
#:
#: Ilgari bu yerda mapping faylidagi `freshness_override` bloki darvozani ochardi: `acknowledged`,
#: `reason`, `approved_by`, `approved_at`. Bu HIMOYA EMAS edi va shuni ochiq aytish kerak —
#: `migrate_1c` CLI'sida IDENTITY UMUMAN YO'Q: `cmd_apply` `apply_migration` ni `actor_id`siz
#: chaqiradi, ya'ni `job.created_by`, audit aktyori va harakatlarning `employee_id` si NULL bo'ladi.
#: `approved_by` — mapping faylini yozgan odamning O'ZI tergan matn. U hech kimni tasdiqlamaydi.
#:
#: Shu bois bloк endi darvozani OCHMAYDI: u bor bo'lsa reja umuman tuzilmaydi va sabab aytiladi.
#: Tekshiriladigan tasdiqlash mexanizmi yozilgunicha darvoza MUTLAQ.
#: TO'G'RI YO'L — yangi muzlatish va yangi nusxa.
OVERRIDE_KEY = "freshness_override"
OVERRIDE_DISABLED_MSG = (
    "mapping.freshness_override QABUL QILINMAYDI: bu avtorizatsiya emas. `migrate_1c` CLI'sida "
    "identity yo'q (apply `actor_id`siz chaqiriladi — `job.created_by` NULL), ya'ni `approved_by` "
    "faylni yozgan odamning o'zi tergan matn. Tekshiriladigan tasdiqlash mexanizmi yozilgunicha "
    "eskirgan kesimni qo'llashning yo'li YO'Q. TO'G'RI YO'L — yangi muzlatish va yangi nusxa.")


class SnapshotTooOld(Exception):
    """Kesim juda eski — do'kon oraliqda savdo qilgan bo'lishi mumkin."""


class SnapshotInFuture(Exception):
    """Kesim serverning vaqtidan sezilarli kelajakda — soatlardan biri noto'g'ri."""


@dataclass(frozen=True)
class FreshnessEvidence:
    """APPLY yozuviga tushadigan dalil — keyin buni qayta tiklab bo'lmaydi, shuning uchun saqlanadi."""
    now: str
    snapshot_at: str
    age_seconds: str
    max_age_seconds: str
    clock_source: str
    verdict: str          # hozircha faqat "fresh" — voz kechish yo'li yo'q

    def as_dict(self) -> dict:
        return {"now": self.now, "snapshot_at": self.snapshot_at, "age_seconds": self.age_seconds,
                "max_age_seconds": self.max_age_seconds, "clock_source": self.clock_source,
                "verdict": self.verdict}


def authoritative_now(db) -> tuple[datetime, str]:
    """Hozirgi vaqt — imkon bo'lsa YOZILAYOTGAN BAZANING soatidan.

    Nega bazaning: operator mashinasi (sandbox) ataylab NTP'siz qoldiriladi, ya'ni uning soatiga
    ishonch yo'q. Postgres'da `now()` — tranzaksiya boshlanish vaqti, ya'ni qulf kutishi uni
    ko'pi bilan bir necha daqiqaga konservativ qiladi (24 soatlik byudjetga ta'sirsiz).
    SQLite'da server yo'q — jarayon soatiga tushamiz va buni dalilda OCHIQ belgilaymiz."""
    try:
        from sqlalchemy import text
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            ts = db.execute(text("SELECT now()")).scalar()
            if ts is not None:
                if ts.tzinfo is None:                       # ehtiyot chorasi: naive kelsa UTC deb o'qiymiz
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts, "database"
    except Exception:                                       # noqa: BLE001 — soat uchun yiqilmaymiz
        pass
    return datetime.now(timezone.utc), "process"


def refuse_override(mapping: dict) -> list[str]:
    """Mapping'da voz kechish bloki bo'lsa — MUAMMO. Shakl tekshirilmaydi, chunki hech qanday
    shakl uni haqiqiy tasdiqlashga aylantirmaydi.

    Nega kalit hamon whitelist'da: aks holda operator «noma'lum kalit» degan umumiy xato olardi va
    NEGA ishlamasligini bilmasdan qolardi."""
    return [OVERRIDE_DISABLED_MSG] if OVERRIDE_KEY in mapping else []


def assert_fresh(now: datetime, clock_source: str, snapshot_at: datetime,
                 snapshot_raw: str) -> FreshnessEvidence:
    """Kesim yangimi? Dalilni qaytaradi yoki `SnapshotTooOld` / `SnapshotInFuture` ko'taradi.

    Sof funksiya: soat TASHQARIDAN beriladi — shu bois test qilish oson va yashirin holat yo'q.
    Voz kechish yo'li YO'Q: darvoza mutlaq (yuqoridagi izohga qarang)."""
    age = now - snapshot_at
    ev = dict(now=now.isoformat(), snapshot_at=snapshot_raw,
              age_seconds=str(int(age.total_seconds())),
              max_age_seconds=str(int(MAX_SNAPSHOT_AGE.total_seconds())),
              clock_source=clock_source)

    if age < -FUTURE_TOLERANCE:
        raise SnapshotInFuture(
            f"snapshot_at ({snapshot_raw}) hozirgi vaqtdan ({now.isoformat()}, manba: "
            f"{clock_source}) {int(-age.total_seconds())} soniya KELAJAKDA. Eng ehtimolli sabab — "
            "soatlardan biri noto'g'ri (do'kon kassasi yoki sandbox). Soatni to'g'rilab, bundle'ni "
            "qayta chiqaring.")

    if age > MAX_SNAPSHOT_AGE:
        raise SnapshotTooOld(
            f"kesim juda eski: snapshot_at {snapshot_raw}, yoshi "
            f"{int(age.total_seconds()) // 3600} soat, ruxsat etilgani "
            f"{int(MAX_SNAPSHOT_AGE.total_seconds()) // 3600} soat (hozir {now.isoformat()}, "
            f"manba: {clock_source}). Do'kon shu oraliqda savdo qilgan bo'lishi mumkin, ya'ni "
            "ko'chadigan qoldiq haqiqatdan farq qiladi. YAGONA YO'L — yangi muzlatish va yangi "
            "nusxa; voz kechish mexanizmi ATAYLAB yo'q.")

    return FreshnessEvidence(**ev, verdict="fresh")
