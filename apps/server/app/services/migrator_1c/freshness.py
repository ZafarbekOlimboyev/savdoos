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

KELAJAKDAGI KESIM — NOL TOLERANTLIK (egasining qarori, 2026-09-28). Manba kesimi hozirgi
vaqtdan KEYIN bo'lolmaydi: kelajakdagi lahzada jonli 1C holatini muzlatib bo'lmaydi. Ilgari bu
yerda 2 soatlik oyna bor edi — u eskirganlikdan HECH NARSANI himoya qilmasdi (kelajakka sanalgan
kesim ta'rifi bo'yicha 24 soatdan yosh, ya'ni yosh tekshiruvidan baribir o'tardi), faqat soat
anomaliyasini yashirardi. Endi yashirmaydi.

⚠️ Bu radni «yaxshiroq» vaqt yozib chetlab o'tish TAQIQLANGAN. Rad javobi soatlardan biri
noto'g'ri ekanini bildiradi: soat to'g'rilanadi va bundle QAYTA chiqariladi. Haqiqiy kesim
lahzasi nusxa qaydidan olinadi va u KEYINROQ vaqt bilan almashtirilmaydi.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: Cutover kesimining maksimal yoshi. Yuqori chegara (yuqoridagi izohga qarang).
MAX_SNAPSHOT_AGE = timedelta(hours=24)

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
    """Kesim hozirgi vaqtdan KEYIN — soatlardan biri noto'g'ri. Tolerantlik YO'Q."""


class ClockUnavailable(Exception):
    """Vaqtga ishonch yo'q — fail-closed. (Hozircha ishlatilmaydi; SQLite zaxirasi belgilanadi.)"""


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

    NEGA `clock_timestamp()`, `now()` EMAS: `now()` — `transaction_timestamp()` ning taxallusi,
    ya'ni u TRANZAKSIYA BOSHLANGAN lahzani qaytaradi va tranzaksiya davomida O'ZGARMAYDI. Apply
    uzoq tranzaksiya ichida ishlaydi (`lock_timeout = '120s'`, qator qulflari, katalog qayta
    tasniflanishi), shuning uchun `now()` yoshni KAM ko'rsatishi mumkin — bu esa aynan XAVFLI
    yo'nalish: eskirgan kesim yoshroq bo'lib ko'rinadi. `clock_timestamp()` har chaqiruvda
    haqiqiy devor soatini beradi.

    NEGA BAZANING soati: operator mashinasi (sandbox) ataylab NTP'siz qoldiriladi
    (`SANDBOX_RESTORE_RUNBOOK.md`), ya'ni uning soatiga ishonch yo'q.

    SQLite'da server YO'Q — jarayon soatiga tushamiz. Bu AYNAN o'sha ishonchsiz soat bo'lishi
    mumkin, shuning uchun dalilda `clock_source="process"` deb ochiq belgilanadi va uni
    avtoritetli o'qish deb hisoblash mumkin emas."""
    try:
        from sqlalchemy import text
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            ts = db.execute(text("SELECT clock_timestamp()")).scalar()
            if ts is not None:
                # `timestamptz` odatda tz-aware keladi; drayver naive bersa — solishtirish
                # TypeError bilan yiqilardi, shuning uchun UTC deb o'qiymiz (fail-closed emas,
                # lekin jim TypeError'dan yaxshiroq va manba dalilda ko'rinadi).
                if ts.tzinfo is None:
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

    Sof funksiya: soat TASHQARIDAN beriladi. Solishtirish tz-aware LAHZALAR bo'yicha, formatlangan
    satrlar bo'yicha EMAS — ofset farqi natijaga ta'sir qilmaydi.
    Voz kechish yo'li YO'Q va kelajakka tolerantlik YO'Q."""
    if snapshot_at.tzinfo is None or now.tzinfo is None:
        raise SnapshotInFuture("vaqt zonasiz (naive) lahzani solishtirib bo'lmaydi — "
                               "ikkala qiymat ham offset bilan bo'lishi SHART")
    age = now - snapshot_at
    ev = dict(now=now.isoformat(), snapshot_at=snapshot_raw,
              age_seconds=str(int(age.total_seconds())),
              max_age_seconds=str(int(MAX_SNAPSHOT_AGE.total_seconds())),
              clock_source=clock_source)

    if age < timedelta(0):
        raise SnapshotInFuture(
            f"snapshot_at ({snapshot_raw}) hozirgi vaqtdan ({now.isoformat()}, manba: "
            f"{clock_source}) {int(-age.total_seconds())} soniya KEYIN. Kelajakdagi lahzada 1C "
            "holatini muzlatib bo'lmaydi, shuning uchun tolerantlik YO'Q. Sabab — soatlardan biri "
            "noto'g'ri (do'kon kassasi yoki sandbox). SOATNI TO'G'RILANG va bundle'ni QAYTA "
            "chiqaring. ⚠️ Haqiqiy kesim lahzasini keyinroq vaqt bilan ALMASHTIRMANG — u nusxa "
            "qaydidan olinadi.")

    if age > MAX_SNAPSHOT_AGE:
        raise SnapshotTooOld(
            f"kesim juda eski: snapshot_at {snapshot_raw}, yoshi "
            f"{int(age.total_seconds()) // 3600} soat, ruxsat etilgani "
            f"{int(MAX_SNAPSHOT_AGE.total_seconds()) // 3600} soat (hozir {now.isoformat()}, "
            f"manba: {clock_source}). Do'kon shu oraliqda savdo qilgan bo'lishi mumkin, ya'ni "
            "ko'chadigan qoldiq haqiqatdan farq qiladi. YAGONA YO'L — yangi muzlatish va yangi "
            "nusxa; voz kechish mexanizmi ATAYLAB yo'q.")

    return FreshnessEvidence(**ev, verdict="fresh")
