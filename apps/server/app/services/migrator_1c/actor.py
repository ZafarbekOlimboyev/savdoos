# -*- coding: utf-8 -*-
"""Cutover AKTYORI — kim bajarayotgani bazada hal bo'ladigan, faol va ruxsatli xodim.

NEGA KERAK. Ilgari cutover HECH KIMNI nomlamasdi: CLI `apply_migration` ni `actor_id`siz
chaqirardi, natijada to'rtta ustun NULL bo'lardi — `import_jobs.created_by`, `audit_log.actor_id`,
har bir harakatning `employee_id` va yaratilgan mahsulotlarning `created_by`. Ustiga-ustak
`/audit` yagona so'rovni `actor_id` bo'yicha INNER JOIN bilan quradi, ya'ni NULL aktyorli qator
BinOS foydalanuvchisiga hech qachon ko'rinmaydi. Do'kon tarixidagi eng katta yozuv hodisasi
egasiga ko'rinmasdi.

⚠️ BU AVTORIZATSIYA EMAS, ATRIBUTSIYA. Buni ochiq aytish shart: CLI hech kimni
autentifikatsiya qilmaydi va `DATABASE_URL` ni ushlab turgan odam har qanday uuid'ni tera oladi —
u allaqachon istalgan qatorni to'g'ridan-to'g'ri yoza oladi. Bu tekshiruv:

  ISBOTLAYDI   — HAQIQIY, shu do'konda ISHLAYOTGAN, RUXSATLI odam NOMLANGANINI, va bu nom
                 egasi kuzatib borishi mumkin bo'lgan tashqi kalit (FK) ekanini.
  ISBOTLAMAYDI — o'sha odam hozir shu yerda bo'lganini yoki roziligini. Bu — nazorat emas,
                 javobgarlik izi.

Nima uchun `employees.id` (uuid): u YAGONA global noyob identifikator (`db/schema.sql:118`).
`phone` faqat qisman noyob (parolli, o'chirilmagan qatorlar uchun — `initdb.py:663-666`),
`full_name` esa umuman noyob emas. Aniqmaslik bo'lgan joyda atributsiya ham aniq bo'lmaydi.

RUXSAT. Cutover katalogni ham, qoldiqni ham yozadi, shuning uchun aktyorda HTTP orqali ayni
o'sha yozuvlarni himoya qiladigan ikkita kod bo'lishi shart: `mahsulotlar.edit` va `ombor.edit`.
Tekshiruv `core.deps.effective_permissions` orqali: u rol standartini va xodim darajasidagi
`allowed=False` bekor qilishini hisobga oladi, va `require()` dan farqli o'laroq FULL_ACCESS_ROLES
uchun qisqa tutashuv QILMAYDI — ya'ni qat'iyroq.
"""
from __future__ import annotations

import uuid as _uuid

#: Cutover yozadigan narsalarni HTTP tomonda himoya qiladigan kodlar.
REQUIRED_PERMISSIONS = ("mahsulotlar.edit", "ombor.edit")


class ActorForbidden(Exception):
    """Aktyor berilmagan, topilmadi, faol emas, boshqa do'konniki yoki ruxsati yetmaydi."""


def resolve_actor(db, comp, actor_id, *,
                  required_permissions: tuple[str, ...] = REQUIRED_PERMISSIONS,
                  kontekst: str = "APPLY"):
    """Aktyorni hal qiladi yoki `ActorForbidden` ko'taradi. Hech narsa yozmaydi.

    `comp` — APPLY allaqachon QULFLAGAN maqsad kompaniya qatori, ya'ni do'kon identifikatori
    shu yerda vakolatli. Tekshiruv yozuvdan OLDIN, o'sha tranzaksiya ichida bajariladi.

    `required_permissions` / `kontekst` — D3: ayni gardni TARIXIY bajarish sirti ham
    ishlatadi (`POST /historical/events`, `POST /reports/history/seed`). U boshqa
    ruxsat kodlarini talab qiladi va xabarda «APPLY» deb ko'rinishi operatorni
    chalg'itardi. Standart qiymatlar cutover xulqini BAYT-AYNAN saqlaydi.
    ⚠️  IKKINCHI RESOLVER YOZILMAYDI: bir gardning ikki nusxasi — aynan
        `api/v1/admin.py:731-734` qayd etgan nuqson sinfi."""
    from app.core.deps import effective_permissions
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus

    if actor_id is None or (isinstance(actor_id, str) and not actor_id.strip()):
        raise ActorForbidden(
            f"{kontekst}: aktyor MAJBURIY — cutover'ni KIM bajarayotgani bazada mavjud, FAOL va ruxsatli "
            "xodim bo'lishi shart (`--actor-employee-id`). Bu avtorizatsiya emas, ATRIBUTSIYA: "
            "usiz cutover hech kimni nomlamaydi va audit jurnalida umuman ko'rinmaydi.")

    if isinstance(actor_id, str):
        try:
            actor_id = _uuid.UUID(actor_id.strip())
        except ValueError as e:
            raise ActorForbidden(
                f"{kontekst} taqiqlangan: aktyor identifikatori UUID emas — u `employees.id` bo'lishi "
                "shart. Ism yoki telefon bo'yicha qidirishga TUSHILMAYDI.") from e

    emp = db.get(Employee, actor_id)
    if emp is None:
        raise ActorForbidden(
            f"{kontekst} taqiqlangan: xodim topilmadi ({actor_id}) — bu bazada bunday `employees.id` yo'q")
    if getattr(emp, "deleted_at", None) is not None:
        raise ActorForbidden(
            f"{kontekst} taqiqlangan: xodim o'chirilgan (deleted_at={emp.deleted_at}) — "
            "o'chirilgan xodim nomidan cutover yozilmaydi")
    if emp.status != EmployeeStatus.active:
        raise ActorForbidden(
            f"{kontekst} taqiqlangan: xodim faol emas (status={emp.status.value}) — "
            "faqat `active` xodim cutover aktyori bo'la oladi")
    if emp.company_id != comp.id:
        # Boshqa do'kon nomi ATAYLAB aytilmaydi — bu boshqa ijarachining ma'lumoti.
        raise ActorForbidden(
            f"{kontekst} taqiqlangan: xodim BOSHQA do'konga tegishli — maqsad do'kon '{comp.code}'")

    missing = sorted(set(required_permissions) - effective_permissions(emp, db))
    if missing:
        raise ActorForbidden(
            f"{kontekst} taqiqlangan: xodimda ruxsat yetishmaydi: {missing} (rol '{emp.role.code}') — "
            "cutover katalogni ham, qoldiqni ham yozadi")
    return emp
