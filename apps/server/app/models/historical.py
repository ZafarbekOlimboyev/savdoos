# -*- coding: utf-8 -*-
"""Tarixiy bajarish JURNALI — `POST /historical/events` rezervatsiyasi.

NEGA JURNAL KERAK (yozuvchilarning o'z dedup'i YETMAYDI)
=========================================================
12 kanonik yozuvchining idempotentlik semantikasi BIR XIL EMAS — o'lchangan:
· to'rtta (sotuv, qaytarish, kassa kirim/chiqim) DTO'da kaliti, simlangan
  qismiy noyob indeksi va to'liq mazmun solishtiruvi bor — jurnal ularga
  dedup QO'SHMAYDI;
· `shift_open` kaliti bor, lekin `ux_shifts_client_uuid` MAVJUD EMAS, ya'ni
  oldin-tekshiruv indeks kafolati emas (yozuvchining o'zi buni
  `services/shifts.py:62-68` da tan oladi);
· `shift_close` da kalit UMUMAN YO'Q — takror 400 "Smena allaqachon yopilgan"
  beradi;
· beshta hodisa natija id'sini QAYTARMAYDI, ya'ni javob shaklini
  o'zgartirmasdan natijani yozib qo'yadigan yagona joy — shu jurnal.

NEGA `status` USTUNI BOR (`receiving_corrections` dan FARQ)
===========================================================
`receiving_corrections` da `response_json` AYNI tranzaksiyada to'ldiriladi
(`models/receiving.py:50-53`), shu bois unda "boshlangan lekin tugamagan"
holati YO'Q. Bu yerda esa bor va bu O'LCHANGAN zaruriyat:

  11 yozuvchining HAMMASI o'z tanasida `db.commit()` qiladi, `get_db`
  (`db/session.py:75-80`) esa faqat `close` qiladi. Ya'ni jurnal qatori
  so'rov sessiyasiga yozilsa — uni YOZUVCHI commit qiladi. Bundan yomoni:
  yozuvchilar xato yo'lida `db.rollback()` qiladi, u esa flush qilingan
  qatorni SESSIYADAN CHIQARIB TASHLAYDI. `create_sale` ning retry halqasi
  (`services/sales.py:128-133`) aynan shunday: 1-urinish `receipt_no`
  poygasida yiqilib rollback qiladi (jurnal qatori YO'Q BO'LADI), 2-urinish
  esa `Sale` ni commit qiladi. Natijada biznes qatori bor, idempotentlik
  yozuvi yo'q va noyob indeks HECH QACHON hakamlik qilmagan.

Shu bois jurnal ALOHIDA sessiyada, dispatch'dan OLDIN commit qilinadi
(`status='started'`), yozuvchi tugagach esa `status='done'` ga o'tadi. Uy
pretsedenti bor va ayni sabab bilan yozilgan: `api/v1/catalog_v2.py:159-161`
("ishni egallaymiz va DARHOL commit qilamiz"), sababi
`services/catalog_commit_v2.py:390-397` — bir tranzaksiyada bo'lsa rollback
izni ham o'chirardi.

HALOKAT OYNASI VA TIKLANISH
===========================
`status='started'` qatori + commit bo'lgan biznes qatori = yozuvchi ulgurgan,
finalize ulgurmagan. Bu holat ABADIY 409 BERMAYDI (ega qarori): ayni
`event_key` kelganda kanonik holat O'QILADI va natija finalize qilinadi yoki
yozuvchi hech narsa yozmagani aniqlansa qayta yuboriladi. Tiklanish o'qishlari
`payload` ustunidan foydalanadi (masalan `shift_close` uchun `shift_id`), shu
bois payload SAQLANADI.

⚠️  `deleted_at` YO'Q va noyob indeks QISMAN EMAS — `receiving_corrections`
    bilan ayni sabab: `deleted_at IS NULL` sharti idempotentlik kalitiga
    «o'chirib qayta yuborish» teshigini ochardi.

⚠️  KALIT `(company_id, event_key)`, branch KALITDA EMAS. `event_key` allaqachon
    do'kon+reja nom maydonidan chiqadi (`services/historical.py:459-471`), ya'ni
    konstruksiya bo'yicha noyob. Branch'ni kalitga qo'shish kontraktni
    BO'SHATARDI — ayni reja hodisasini har filialda bir marta yozishga ruxsat
    berardi. Ega qarori: branch SAQLANADI va payload HASH'iga KIRADI, ya'ni
    ayni kalit boshqa filial bilan kelsa — KONFLIKT (409), takror emas.

⚠️  CHECK cheklovi QO'SHILMAYDI. `status` erkin matn: CHECK qo'shilsa jadval
    `CHECK_DEFINITIONS` / `test_check_canon` / `test_check_defs_pg` zanjiriga
    tushardi va har o'zgarish uchta registrni yangilashni talab qilardi.
    Qiymatlar `services/historical_journal.py` da yagona joyda ta'riflangan.

⚠️  `products` ga FK YO'Q — mahsulot id'lari `payload` ichida. FK bo'lsa jadval
    `catalog_reset.KNOWN_PRODUCT_REFERRERS` ro'yxatiga tushardi
    (`test_lot_phase4a.py:956-973` majburlaydi).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin
from app.db.types import JSONB, UUID


class HistoricalPlanEvent(Base, PKMixin):
    """Bitta rejalashtirilgan tarixiy hodisaning rezervatsiyasi va natijasi."""

    __tablename__ = "historical_plan_events"
    __table_args__ = (
        Index("ux_hist_plan_event", "company_id", "event_key", unique=True),
    )

    #  ── Doira. Uchtasi ham MAJBURIY: endpoint ularni fail-closed tekshiradi.
    #     ⚠️  FK'lar ATAYLAB bor (ijarachi chalkashligi bazada ham imkonsiz
    #         bo'lsin), lekin shu sababli INSERT `KEY SHARE` oladi — shu bois
    #         endpoint `companies` qatorini `FOR UPDATE` QILMAYDI. Aks holda
    #         bir so'rov ichida o'z-o'zini bloklardi: `FOR UPDATE` ushlab turgan
    #         sessiya jurnal sessiyasining commit'ini kutardi, jurnal sessiyasi
    #         esa `KEY SHARE` uchun bloklanardi.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    actor_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)

    #  ── Hodisa kimligi.
    plan_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)

    #  ── Holat mashinasi: started -> done | failed (failed -> started qayta).
    status: Mapped[str] = mapped_column(String, nullable=False)

    #  ── So'rov MAZMUNI. `payload_hash` — ayni kalit bilan BOSHQA mazmun
    #     kelsa bu takror EMAS (409). `hash_version` — kelajakdagi kanonik
    #     shakl o'zgarishi ESKI qatorga yolg'on konflikt bermasligi uchun:
    #     kutilgan hash SAQLANGAN versiya bo'yicha qayta hisoblanadi.
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_version: Mapped[int] = mapped_column(nullable=False)
    #  Tiklanish o'qishlari uchun kerak (masalan `shift_close` uchun `shift_id`).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #  ── Natija. `result_id` — kanonik biznes qatorining id'si; beshta
    #     yozuvchi uni javobida QAYTARMAYDI, shu bois yagona manba shu yer.
    result_type: Mapped[str | None] = mapped_column(String, nullable=True)
    result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    #  Birinchi javob; takrorda AYNAN o'zi qaytariladi.
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    finalised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
