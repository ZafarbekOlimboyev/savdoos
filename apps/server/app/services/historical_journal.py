# -*- coding: utf-8 -*-
"""Tarixiy hodisa JURNALI — rezervatsiya, takror, konflikt, TIKLANISH.

Bu modul `POST /historical/events` ning idempotentlik yadrosi. U uch savolga
javob beradi: bu hodisa boshlanganmi, tugaganmi, va tugamagan bo'lsa kanonik
holat nima deydi.

── NEGA ALOHIDA SESSIYA (eng muhim qaror, O'LCHANGAN) ───────────────────────
11 kanonik yozuvchining HAMMASI o'z tanasida `db.commit()` qiladi, `get_db`
(`db/session.py:75-80`) esa faqat `close` qiladi. Demak jurnal qatori so'rov
sessiyasiga yozilsa — uni YOZUVCHI commit qiladi. Bundan yomoni: yozuvchilar
xato yo'lida `db.rollback()` qiladi, u esa flush qilingan qatorni sessiyadan
CHIQARIB TASHLAYDI (o'lchangan: SQLAlchemy 2.0.52, `in session -> False`,
`identity -> None`).

`create_sale` ning retry halqasi (`services/sales.py:128-133`) aynan shu
yo'ldan yuradi va `at=` o'sha funksiyaning O'Z parametri, ya'ni tarixiy
chaqiruv uchun YETIB BORILADI: 1-urinish `receipt_no` poygasida IntegrityError
oladi, `db.rollback()` jurnal qatorini YO'Q QILADI, 2-urinish esa `Sale` ni
commit qiladi. Natija: biznes qatori bor, idempotentlik yozuvi YO'Q va noyob
indeks HECH QACHON hakamlik qilmagan — ya'ni «ayni kalit, boshqa filial»
konflikti ham aynan retry yo'lida jimgina ishlamasdi.

Shu bois rezervatsiya ALOHIDA sessiyada, dispatch'dan OLDIN commit qilinadi.
Uy pretsedenti bor va ayni sabab bilan yozilgan: `api/v1/catalog_v2.py:159-161`
(«1-BOSQICH: ishni egallaymiz va DARHOL commit qilamiz»), sababi
`services/catalog_commit_v2.py:390-397` — bir tranzaksiyada bo'lsa rollback
izni ham o'chirardi.

⚠️  `before_commit` SESSION LISTENER YARAMAYDI. Halokat ROLLBACK yo'lida, commit
    hook esa u yerda umuman ishlamaydi. Repoda ORM session listener YO'Q
    (yagona listener — `db/session.py:64` SQLite FK pragma'si), va uni shu yerda
    joriy qilish «atomik ko'rinadigan, lekin jim yo'qotadigan» dizayn bo'lardi.

── HALOKAT OYNALARI ─────────────────────────────────────────────────────────
W1  rezervatsiya commit'idan OLDIN       -> hech narsa yo'q; keyingi urinish YANGI.
W2  rezervatsiyadan keyin, yozuvchidan OLDIN -> `started`, biznes qatori YO'Q.
W3  yozuvchidan keyin, finalize'dan OLDIN    -> `started`, biznes qatori BOR.  <-- ega ko'rsatgan oyna
W4  finalize'dan keyin                   -> `done`; takror saqlangan javobni beradi.

W2 va W3 ni jurnalning O'ZI ajrata OLMAYDI — ajratuvchi faqat KANONIK HOLAT
o'qishi. Shu bois `payload` saqlanadi va har hodisa turi uchun tiklanish
o'qishi bor (`historical_recovery.py`). `started` holati HECH QACHON abadiy
409 bermaydi (ega qarori).

⚠️  `lot_correction._replay` (`:652-658`) BU YERDA NAMUNA EMAS. U
    «yakunlanmagan» holatda 409 beradi va tiklanish qilmaydi — bu uning uchun
    to'g'ri, chunki u BIR tranzaksiyali (`grep -c "db.commit()"` -> 1, `:1226`)
    va unda W3 oynasi UMUMAN mavjud emas. Bu yerda esa mavjud.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.index_guard import require_index
from app.models.historical import HistoricalPlanEvent

#: Holat mashinasi. CHECK cheklovi ATAYLAB yo'q (qarang model sarlavhasi) —
#: shu bois qiymatlar shu YAGONA joyda ta'riflanadi.
STARTED = "started"
DONE = "done"
FAILED = "failed"
STATUSES = (STARTED, DONE, FAILED)

#: Kanonik shakl versiyasi. Kutilgan hash SAQLANGAN versiya bo'yicha qayta
#: hisoblanadi, aks holda kelajakdagi v2 ESKI qatorlarga YOLG'ON konflikt
#: berardi (`services/catalog_commit_v2.py:184-192` naqshi).
HASH_VERSION = 1


def _num(v) -> str:
    """Sonning YO'QOTISHSIZ kanonik matni.

    ⚠️  NEGA `normalize()`. Ayni miqdor turli shaklda kelishi mumkin —
        `Decimal("2.000")`, `Decimal("2")`, `2.0` — va `model_dump(mode="json")`
        ularni turlicha yozib, AYNI so'rovga ikki xil hash berardi, ya'ni takror
        YOLG'ON KONFLIKT bo'lardi. `normalize()` ortiqcha nollarni olib tashlaydi
        va qiymatni O'ZGARTIRMAYDI, ya'ni aniqlik TANLASH kerak emas (qat'iy
        kvantlash esa chegaradan nariga tushgan farqni jimgina yutardi).

    ⚠️  `format(..., "f")` SHART: `normalize()` katta sonni `2E+2` qilib
        qo'yadi, ilmiy shakl esa kanonik matn sifatida beqaror.
    """
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return str(v)
    if not d.is_finite():            # NaN/Inf — DTO'lar buni rad etadi, baribir himoya
        return str(v)
    return format(d.normalize(), "f")


def _norm(x):
    """`model_dump(mode="json")` natijasini kanonik shaklga keltiradi.

    ⚠️  RO'YXAT TARTIBI SAQLANADI (saralanmaydi) — `lot_correction.py:195-197`
        bilan ayni sabab: tartib pastki oqimdagi kalitlarga kiradi, ya'ni
        tartib o'zgarishi BOSHQA so'rov demakdir. Lug'at kalitlari esa
        `json.dumps(sort_keys=True)` bilan saralanadi.
    """
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, (int, float, Decimal)):
        return _num(x)
    return str(x)


def canonical(*, event_type: str, occurred_at: datetime, branch_id,
              actor_employee_id, payload: dict) -> dict:
    """Hash va konflikt uchun YAGONA kanonik shakl.

    ⚠️  BRANCH HASH'GA KIRADI (ega qarori). Noyob kalit `(company_id,
        event_key)` — branch unda YO'Q, chunki `event_key` allaqachon
        do'kon+reja nom maydonidan chiqadi va branch'ni kalitga qo'shish ayni
        reja hodisasini HAR FILIALDA bir marta yozishga ruxsat berardi. Buning
        o'rniga branch hash'ga kiradi: ayni kalit boshqa filial bilan kelsa —
        KONFLIKT (409), takror emas.

    ⚠️  AKTOR HAM HASH'DA. Boshqa xodim bilan kelgan takror jimgina ikkinchi
        biznes qatori yaratmasin: u ham konflikt. Bu `create_sale` ning o'z
        xulqiga mos — `_replay_mismatch` (`services/sales.py:65-66`) kassirni
        solishtiradi va farq qilsa rad etadi.

    ⚠️  `company_id` va `plan_id` ATAYLAB YO'Q: ikkalasi ham `event_key` ichida
        (`services/historical.py:459-471`), ya'ni ayni kalit -> ayni do'kon va
        reja. Takrorlash hash'ni kuchaytirmaydi, faqat shaklni shishiradi.
    """
    return {
        "v": HASH_VERSION,
        "event_type": event_type,
        "occurred_at": _as_utc(occurred_at).isoformat(),
        "branch_id": str(branch_id),
        "actor_employee_id": str(actor_employee_id),
        "payload": _norm(payload),
    }


def payload_hash(canon: dict) -> str:
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find(db: Session, company_id, event_key) -> HistoricalPlanEvent | None:
    """`(company_id, event_key)` bo'yicha qator — noyob indeks kafolatlaydi."""
    return (db.query(HistoricalPlanEvent)
            .filter(HistoricalPlanEvent.company_id == company_id,
                    HistoricalPlanEvent.event_key == event_key)
            .one_or_none())


def claim(db: Session, *, company_id, branch_id, actor_employee_id, plan_id: str,
          event_type: str, event_key, occurred_at: datetime, canon: dict,
          ) -> tuple[HistoricalPlanEvent | None, HistoricalPlanEvent | None]:
    """Rezervatsiyani EGALLAYDI va DARHOL commit qiladi.

    Qaytaradi `(yangi, mavjud)`: biri `None`. `mavjud` qaytsa — kalit allaqachon
    band, qaror chaqiruvchida (takror / tiklanish / konflikt).

    ⚠️  INSERT-BIRINCHI, SELECT-BIRINCHI EMAS. Hakam `ux_hist_plan_event`
        bo'lsin: SELECT-keyin-INSERT klassik TOCTOU va uy allaqachon shundan
        kuygan (`services/lot_correction.py:700-706`, `models/receiving.py:42-46`).

    ⚠️  Bu sessiya FAQAT jurnalga tegadi. Biznes sessiyasi bilan ARALASHMAYDI —
        modul sarlavhasidagi rollback-expunge sababi.
    """
    #  ⚠️  INDEKS KAFOLATI — YOZUVDAN OLDIN (fail-closed). Gard aynan shu yerda,
    #      INSERT'ning YONIDA turadi: `ux_hist_plan_event` — `shift_open` va
    #      `shift_close` uchun YAGONA tranzaksion hakam (`ux_shifts_client_uuid`
    #      butun repoda MAVJUD EMAS, `close_shift_svc` esa kalit UMUMAN olmaydi).
    #      Indeks isbotlanmagan bo'lsa rezervatsiya BOSHLANMAYDI.
    require_index(db, "ux_hist_plan_event", "historical_plan_events",
                  operation="historical_event")
    row = HistoricalPlanEvent(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id,
        actor_employee_id=actor_employee_id, plan_id=plan_id,
        event_type=event_type, event_key=event_key,
        occurred_at=_as_utc(occurred_at), status=STARTED,
        payload_hash=payload_hash(canon), hash_version=HASH_VERSION,
        payload=canon["payload"],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        mavjud = find(db, company_id, event_key)
        if mavjud is None:
            #  Noyob indeks ishladi, lekin qator ko'rinmayapti — bu bizning
            #  kalitimiz EMAS (masalan FK buzilishi). Jim «takror» demaymiz.
            raise
        return None, mavjud
    return row, None


def finalise(db: Session, row: HistoricalPlanEvent, *, result_type: str | None,
             result_id, response: dict) -> None:
    """`started` -> `done`: natija va javob yoziladi, O'Z tranzaksiyasida."""
    row.status = DONE
    row.result_type = result_type
    row.result_id = result_id
    row.response_json = json.dumps(response, sort_keys=True, default=str)
    row.finalised_at = datetime.now(timezone.utc)
    row.error = None
    db.commit()


def mark_failed(db: Session, row: HistoricalPlanEvent, error: str) -> None:
    """`started` -> `failed`, ALOHIDA tranzaksiyada.

    ⚠️  Biznes tranzaksiyasi rollback bo'lgach ham iz QOLISHI SHART — aks holda
        muvaffaqiyatsiz urinish hech qanday iz qoldirmasdi
        (`services/catalog_commit_v2.py:390-397` ayni sabab). Shu bois o'z
        `try/except` i bor: iz yozilmasa ham ASOSIY xato yo'qolmasin.
    """
    try:
        row.status = FAILED
        row.error = (error or "")[:2000]
        db.commit()
    except Exception:                                        # noqa: BLE001
        db.rollback()


def resume(db: Session, row: HistoricalPlanEvent) -> None:
    """`failed` -> `started`: AYNI qator qayta ishlatiladi, yangi kalit emas.

    `catalog_commit_v2.py:199-203` (`ImportStatus.failed` -> qayta) naqshi.
    """
    row.status = STARTED
    row.error = None
    db.commit()


def stored_response(row: HistoricalPlanEvent) -> dict | None:
    """Saqlangan javob — lug'at bo'lmasa `None` (jim buzilmaydi)."""
    if not row.response_json:
        return None
    try:
        out = json.loads(row.response_json)
    except (ValueError, TypeError):
        return None
    return out if isinstance(out, dict) else None
