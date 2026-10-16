# -*- coding: utf-8 -*-
"""HISOBNI O'CHIRISH — shaxsiy ma'lumot QAYTARILMAS tarzda olib tashlanadi (CH-18A).

Apple Guideline 5.1.1(v): hisob yaratishni qo'llab-quvvatlagan ilova foydalanuvchiga
ILOVA ICHIDAN hisobni o'chirishni boshlash imkonini berishi SHART.

⚠️  BU «YUMSHOQ O'CHIRISH» EMAS. Mavjud `deleted_at` yorlig'i xodimni ro'yxatdan
    OLIB TASHLAYDI, lekin ism va telefon bazada QOLAVERADI — Apple uchun bu
    yetarli emas. Bu modul PII ustunlarini QAYTA YOZADI: tiklash uchun manba
    qolmaydi.

⚠️  O'CHIRILADIGAN NARSA — ODAMNING BITTA DO'KONDAGI A'ZOLIGI, global hisob EMAS.
    `employees` qatori `company_id` bilan bog'langan. Parolli telefon GLOBAL
    noyob (`ux_employees_phone_pw`: `UNIQUE(phone) WHERE phone IS NOT NULL AND
    password_hash IS NOT NULL AND deleted_at IS NULL`), ya'ni parolli hisob
    faqat BITTA do'konda bo'ladi. PIN'li xodim esa AYNI telefon bilan boshqa
    do'konda ALOHIDA qator sifatida yashashi mumkin — u TEGILMAYDI, chunki har
    so'rov `company_id` bo'yicha chegaralanadi.

⚠️  BIZNES TARIXI O'CHIRILMAYDI. Savdo, kassa, xarid, ombor harakati va audit izi
    QOLADI: ular soliq/buxgalteriya majburiyati va `employee_id` ularda FK. Shu
    bois QATOR O'CHIRILMAYDI — faqat PII ustunlari tozalanadi, ya'ni FK butun
    qoladi va hisob-kitob invariantlari buzilmaydi.

NEGA `sec_epoch` OSHIRILADI. Tokenda `sv` claim'i bor (`api/v1/auth.py:121`) va
`core/deps.py:32` uni `employees.sec_epoch` bilan solishtiradi. Bittaga oshirish —
o'sha xodimning BARCHA mavjud tokenlarini DARHOL kuchsiz qiladi. Bu yagona
haqiqiy sessiya bekor qilish levereji (`auth_sessions` jadvali ishlatilmaydi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.auth import Employee, EmployeeBranch, EmployeePermission, Role
from app.models.enums import EmployeeStatus

#: PII ustunlari — tozalangandan keyin shaxsni tiklash uchun manba QOLMAYDI.
PII_COLUMNS = ("full_name", "phone", "pin_hash", "password_hash", "avatar_url")

#: Tasdiqlash so'zi — mijoz AYNAN shu matnni yuborishi kerak (tasodifiy
#: bosishdan himoya; `tenant_purge` dagi TTL-token falsafasi bilan bir xil).
CONFIRM_WORD = "O'CHIRISH"


def anonymized_name(employee_id) -> str:
    """O'chirilgan xodim uchun barqaror, shaxssiz yorliq.

    Hisobotlarda va cheklarda bo'sh nom ko'rinmasligi uchun nom BERILADI, lekin
    unda shaxsiy ma'lumot YO'Q: faqat `id` ning qisqa bo'lagi, u allaqachon
    biznes yozuvlarida FK sifatida turadi va yangi ma'lumot oshkor qilmaydi.
    """
    return f"O'chirilgan xodim #{str(employee_id).replace('-', '')[:8]}"


def is_deleted(emp: Employee) -> bool:
    """Hisob allaqachon ANONIMLASHTIRILGANMI (takroriy so'rovni aniqlash uchun).

    ⚠️  ANONIMLASHTIRISH BELGISI bo'yicha, MA'LUMOT YO'QLIGI bo'yicha EMAS
        (CH-18D). Ilgari shart `deleted_at bor AND parol yo'q AND telefon
        yo'q` edi. Lekin PIN'li xodimning telefoni NULL bo'lishi MUMKIN —
        telefon faqat PAROLLI xodim uchun majburiy
        (`api/v1/employees.py:335`). Shunda ISHDAN BO'SHATILGAN (lekin PII si
        TURGAN) PIN'li xodim uchta shartni ham qondirardi va:
          · `POST /employees/{id}/account-deletion` «repeated: true» deb
            qaytarardi — anonimlashtirish BAJARILMASDI, ism va PIN hash
            BAZADA QOLARDI, ya'ni javob YOLG'ON bo'lardi;
          · `close_store` ham, yopish preview'i ham uni chetlab o'tardi.

        `anonymized_name()` deterministik va uni FAQAT `anonymize()` yozadi,
        shu bois u ishonchli belgi: «ishdan bo'shatilgan» (PII joyida) va
        «o'chirilgan» (PII yo'q) holatlari endi ARALASHMAYDI.
    """
    return emp.deleted_at is not None and emp.full_name == anonymized_name(emp.id)


def pii_retained(emp: Employee) -> bool:
    """Bu qatorda HAMON shaxsiy ma'lumot turadimi.

    ⚠️  «FAOL» EMAS. Ishdan bo'shatilgan xodim (`deleted_at` bor) ham ism va
        telefonini saqlaydi, shu bois yopish preview'i va hisobotlar uni
        SANASHI kerak — aks holda ega bazadagidan KICHIK son ko'radi.
    """
    return not is_deleted(emp)


def anonymize(db: Session, emp: Employee, *, now: datetime | None = None) -> dict:
    """PII ni QAYTARILMAS tarzda olib tashlaydi va sessiyalarni bekor qiladi.

    Qaytaradi: o'chirilgan maydonlar ro'yxati (audit uchun, QIYMATLARSIZ).
    """
    ts = now or datetime.now(timezone.utc)
    tozalangan = []
    for col in PII_COLUMNS:
        if getattr(emp, col, None):
            tozalangan.append(col)
    emp.full_name = anonymized_name(emp.id)
    emp.phone = None
    emp.pin_hash = None
    emp.password_hash = None
    emp.avatar_url = None
    emp.status = EmployeeStatus.terminated
    emp.deleted_at = ts
    #  Sessiya bekor qilish: mavjud BARCHA tokenlar darhol kuchsiz bo'ladi.
    emp.sec_epoch = int(emp.sec_epoch or 0) + 1
    #  Kirish grantlari — biznes tarixi EMAS, shu bois o'chiriladi (qator
    #  o'chirilmagani uchun CASCADE ishlamaydi: ularni QO'LDA olib tashlaymiz).
    db.query(EmployeePermission).filter(
        EmployeePermission.employee_id == emp.id).delete(synchronize_session=False)
    db.query(EmployeeBranch).filter(
        EmployeeBranch.employee_id == emp.id).delete(synchronize_session=False)
    #  ⚠️  PUSH QURILMA TOKENI ham AYNI TOIFA (CH-18C). U do'konga shu odamning
    #      TELEFONIGA bildirishnoma yuborish imkonini beradi — yetkazish
    #      granti, fiskal yozuv EMAS. CH-18B da men buni o'tkazib yuborgandim:
    #      sinov xodimi hech qachon qurilma ro'yxatdan o'tkazmagan edi, shu
    #      bois marker sweep uni KO'RMADI. Qolsa, «o'chirilgan» odamning
    #      telefoniga xabar yuborish mumkin bo'lardi.
    from app.models.devices import DeviceToken
    qurilma = db.query(DeviceToken).filter(
        DeviceToken.employee_id == emp.id).delete(synchronize_session=False)
    audit = _redact_audit_pii(db, emp.id)
    return {"cleared": tozalangan, "audit_rows_redacted": audit,
            "device_tokens_removed": int(qurilma or 0)}


#: Audit yuklamalaridagi SHAXSIY maydonlar. Qolgan kalitlar (rol, holat, ruxsat)
#: shaxsiy emas va audit ma'nosi uchun KERAK, shu bois tegilmaydi.
_AUDIT_PII_KEYS = ("name", "full_name", "phone")


def _redact_audit_pii(db: Session, employee_id) -> int:
    """SHU xodimning O'Z audit yozuvlaridagi ism/telefonni olib tashlaydi.

    ⚠️  NEGA KERAK (o'lchangan, taxmin emas). O'chirishdan keyin butun bazani
        marker bilan skanerlash `audit_log.before` va `audit_log.after` da ism
        va telefonning QOLGANINI ko'rsatdi: `api/v1/employees.py` ning beshta
        audit chaqiruvi (`unlock`, `create`, `update`, legacy `delete`,
        `permissions`) yuklamaga `full_name`/`phone` ni yozadi. Ya'ni
        `employees` qatorini tozalash O'ZI YETARLI EMAS edi.

    ⚠️  BU AUDIT IZINI O'CHIRISH EMAS. Qator O'CHIRILMAYDI; `actor_id`,
        `action`, `entity`, `entity_id` va `created_at` TEGILMAYDI — ya'ni
        «kim qachon nima qildi» savoli to'liq javobsiz qolmaydi. Faqat
        yuklamadagi SHAXSIY matn olib tashlanadi, chunki shaxsni aniqlash uchun
        `entity_id` allaqachon bor va u o'chirilgan hisobga ishora qiladi.

    ⚠️  DOIRA QAT'IY: faqat `entity == "employee"` VA `entity_id == <shu xodim>`
        qatorlari. Boshqa odamlarning yoki boshqa obyektlarning yozuvlariga
        TEGILMAYDI, hisob-kitob daftarlari esa umuman bu jadvalda emas.
    """
    from app.models.sync import AuditLog

    rows = (db.query(AuditLog)
            .filter(AuditLog.entity == "employee",
                    AuditLog.entity_id == employee_id)
            .all())
    n = 0
    for r in rows:
        ozgardi = False
        for maydon in ("before", "after"):
            qiymat = getattr(r, maydon, None)
            if not isinstance(qiymat, dict):
                continue
            yangi = {k: v for k, v in qiymat.items() if k not in _AUDIT_PII_KEYS}
            if len(yangi) != len(qiymat):
                #  JSONB `Mutable` tur EMAS — YANGI dict tayinlanadi, aks holda
                #  o'zgarish flush qilinmasdi (CH-15B/A.2 dagi ayni tuzoq).
                setattr(r, maydon, yangi)
                ozgardi = True
        if ozgardi:
            n += 1
    return n


# ══ DARVOZALAR ══════════════════════════════════════════════════════════════

def _role_code(db: Session, emp: Employee) -> str:
    r = emp.role if getattr(emp, "role", None) is not None else db.get(Role, emp.role_id)
    return (r.code if r is not None else "") or ""


def _active_peers(db: Session, company_id, codes, exclude_id=None,
                  *, lock: bool = False) -> list[Employee]:
    """Shu do'kondagi FAOL, berilgan rollardagi xodimlar (o'zidan boshqa).

    ⚠️  `lock=True` — «OXIRGI RAHBAR» TEKSHIRUVI UCHUN MAJBURIY (CH-18B).
        Bu check-then-act: ikki rahbar AYNI PAYTDA o'z hisobini o'chirsa,
        ikkalasi ham «yana bitta rahbar bor» deb o'qib o'tib ketardi va do'kon
        0 rahbarli qolardi. `employees` qatorlarini `FOR UPDATE` bilan qulflab,
        bu amallar KETMA-KET bajariladi: ikkinchisi birinchisi commit qilgach
        kamaygan sonni ko'radi va to'g'ri rad etiladi. Naqsh
        `api/v1/employees.py:_active_admin_count_locked` bilan AYNI — faqat
        `Employee` qatorlari qulflanadi.

    ⚠️  `exclude_id` QULF SO'ROVIGA KIRMAYDI — bu ATAYLAB (CH-18C). Ilgari u
        SQL filtriga qo'shilardi va men izohda «barqaror tartib deadlock'ga
        qarshi» deb yozgandim. Bu NOTO'G'RI edi: `order_by` faqat AYNI
        to'plam ichida yordam beradi, `exclude_id` esa to'plamni har
        chaqiruvda BOSHQA qiladi. Ega ikki administratorni PARALLEL
        o'chirganda T1 {ega, A2} ni, T2 {ega, A1} ni qulflardi va keyin har
        biri boshqasining maqsadini so'rardi — PostgreSQL buni
        `DeadlockDetected` bilan uzdi (CH-18C `test_PG_2...`: «deadlock
        detected ... while locking tuple in relation "employees"»). Ma'lumot
        buzilmasdi (PG bittasini qaytaradi), lekin operator toza 409 emas,
        500 olardi.

        Yechim: QULF butun rol to'plamiga, AYNI `id` tartibida qo'yiladi va
        `exclude_id` Python darajasida chiqariladi. Shunda har bir raqib
        AYNI qatorlarni AYNI tartibda oladi -> ikkinchisi KUTADI, deadlock
        yo'q. Qaytariladigan ro'yxat o'zgarmaydi.
    """
    q = (db.query(Employee)
         .join(Role, Employee.role_id == Role.id)
         .filter(Employee.company_id == company_id,
                 Employee.deleted_at.is_(None),
                 Employee.status == EmployeeStatus.active,
                 Role.code.in_(tuple(codes))))
    if lock:
        #  `exclude_id` BU YERDA QO'LLANMAYDI — yuqoridagi izohga qara.
        q = q.order_by(Employee.id).with_for_update(of=Employee)
    elif exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    qatorlar = q.all()
    if lock and exclude_id is not None:
        return [e for e in qatorlar if e.id != exclude_id]
    return qatorlar


def self_deletion_state(db: Session, emp: Employee) -> dict:
    """O'z hisobini o'chirish MUMKINMI — va mumkin bo'lmasa, QANDAY yo'l bor.

    ⚠️  «Oxirgi rahbar» holati UCHUN TANLOV BERILADI, shunchaki rad etilmaydi
        (ega talabi): boshqa administratorga boshqaruvni O'TKAZISH yoki do'konni
        YOPISH. Aks holda yagona ega qulflanib qolardi va Apple talabini
        bajarish uchun hech qanday yo'l bo'lmasdi.
    """
    from app.api.v1.employees import _has_open_shift

    kod = _role_code(db, emp)
    bloklar: list[str] = []
    #  ⚠️  PAROLSIZ (PIN'li) XODIM BU YO'LDAN O'CHIRA OLMAYDI (CH-18D).
    #      Marshrut (`api/v1/auth.py:delete_own_account`) 400 beradi, chunki
    #      tasdiqlash uchun parol YO'Q. Holat esa `can_delete: true` deb
    #      qaytarardi — ya'ni API O'ZIGA ZID javob berardi: «mumkin» deydi,
    #      keyin rad etadi. Mobil ekran `needs_password` bo'yicha shoxlanadi,
    #      shu bois ko'rinmas edi, lekin boshqa iste'molchi uchun bu
    #      chalg'ituvchi. `needs_password` AYNI ma'lumotni beradi, `blockers`
    #      esa SABABNI aytadi.
    if not emp.password_hash:
        bloklar.append("no_password")
    if _has_open_shift(db, emp.id):
        bloklar.append("open_shift")

    #  Oxirgi FAOL ega yoki oxirgi FAOL rahbar bo'lsa — do'kon boshsiz qolardi.
    #  QULF ostida: poyga ikki rahbarni bir vaqtda o'chirib yubormasin.
    rahbarlar = _active_peers(db, emp.company_id, ("ega", "administrator"), emp.id, lock=True)
    egalar = _active_peers(db, emp.company_id, ("ega",), emp.id, lock=True)
    oxirgi_rahbar = kod in ("ega", "administrator") and not rahbarlar
    oxirgi_ega = kod == "ega" and not egalar
    if oxirgi_rahbar:
        bloklar.append("sole_manager")
    elif oxirgi_ega:
        bloklar.append("sole_owner")

    #  O'TKAZISH NOMZODLARI: do'kondagi boshqa FAOL xodimlar, ularni ega/admin
    #  qilish mumkin. Ro'yxat PII bermaydi — faqat id va rol.
    nomzodlar = [] if not (oxirgi_rahbar or oxirgi_ega) else [
        {"id": str(p.id), "role": _role_code(db, p)}
        for p in _active_peers(db, emp.company_id,
                               ("ega", "administrator", "menejer", "omborchi", "kassir"),
                               emp.id)
    ]
    return {
        "role": kod,
        "can_delete": not bloklar,
        "blockers": bloklar,
        "already_deleted": is_deleted(emp),
        # Rad etilgan holatda OPERATOR BAJARA OLADIGAN ikki yo'l:
        "transfer_candidates": nomzodlar,
        #  ⚠️  CH-18B: YOPISH ENDI MAVJUD va MAVJUD PRIMITIVDAN foydalanadi.
        #      CH-18A da men buni «kutish muddati va vendor tasdig'i kerak» deb
        #      bloklagandim — bu SIYOSATNI O'YLAB TOPISH edi, repoda bunday
        #      talab YO'Q. Haqiqat: `Company.deleted_at` ALLAQACHON majburlanadi
        #      (`core/deps.py:38-39` -> 401) va vendor yo'li uni «yumshoq,
        #      tarix saqlanadi, login yopiladi» deb ishlatadi. Shu bois yopish
        #      FAQAT egaga ochiladi — sxema o'zgarmaydi, yangi majburlash
        #      manbai qo'shilmaydi.
        "store_closure_available": kod == "ega",
    }


def other_deletion_blockers(db: Session, actor: Employee, target: Employee) -> list[str]:
    """Ega BOSHQA xodimni o'chirishi mumkinmi.

    ⚠️  ROL TOKENDAN EMAS, BAZADAN olinadi. `core/deps.py` tokendagi `role`
        claim'ini ishlatadi, lekin bu yerda qaror AKTYORNING BAZADAGI roli
        bo'yicha chiqariladi — soxta token rolini qabul qilmaslik uchun.
    """
    bloklar: list[str] = []
    if target.company_id != actor.company_id:
        bloklar.append("other_tenant")          # chaqiruvchi buni 404 qiladi
        return bloklar
    if target.id == actor.id:
        bloklar.append("self")                  # o'zini bu yo'l bilan emas
    if _role_code(db, actor) != "ega":
        bloklar.append("not_owner")
    from app.api.v1.employees import _has_open_shift
    if _has_open_shift(db, target.id):
        bloklar.append("open_shift")
    kod = _role_code(db, target)
    if kod in ("ega", "administrator"):
        qolgan = _active_peers(db, actor.company_id, ("ega", "administrator"), target.id, lock=True)
        if not qolgan:
            bloklar.append("sole_manager")
    if kod == "ega":
        qolgan_ega = _active_peers(db, actor.company_id, ("ega",), target.id, lock=True)
        if not qolgan_ega:
            bloklar.append("sole_owner")
    return bloklar


# ══ DO'KONNI OPERATSION YOPISH (CH-18B) ═════════════════════════════════════
#
#  ⚠️  YOPISH ≠ TENANT PURGE. Hisob-kitob daftarlari (savdo, kassa, xarid,
#      ombor harakatlari) TEGILMAYDI va `tools/tenant_purge.py` CHAQIRILMAYDI.
#      Yopish — OPERATSION holat: kirish yopiladi, tarix joyida qoladi.
#      `enums.CompanyStatus.CLOseD` izohi aynan shuni aytadi: «tarixiy ma'lumot
#      SAQLANADI, hard-delete YO'Q».

def close_store(db: Session, owner: Employee, *, delete_self: bool = False,
                now: datetime | None = None) -> dict:
    """Do'konni OPERATSION yopadi. Xodimlar PII sini O'ZI O'CHIRMAYDI.

    ⚠️  CH-18C TUZATISHI — MENING OLDINGI IMPLEMENTATSIYAM OSHIB KETGAN EDI.
        CH-18B da bu funksiya do'kondagi BARCHA xodimlar hisobini
        anonimlashtirardi. Ega YOPISHNI chiqish yo'li sifatida tasdiqlagan,
        lekin BARCHA xodimlar PII sini ommaviy, qaytarilmas o'chirishni ALOHIDA
        tasdiqlamagan. Qaytarilmas amalni «mantiqan kelib chiqadi» deb o'zim
        kiritishim xato edi — endi u AJRATILDI.

    TO'RT NARSA ENDI ALOHIDA:
      1. OPERATSION YOPISH — shu funksiya: `deleted_at` + `status=CLOSED`.
         Kirish to'xtaydi (`core/deps.py:38-39` -> 401), tarix TEGILMAYDI.
      2. SHAXSIY HISOBNI O'CHIRISH — har kim O'ZI so'raydi/bajaradi.
      3. MAJBURIY HISOB-KITOB SAQLASH — daftarlar HECH QACHON tegilmaydi.
      4. OMMAVIY PII ANONIMLASHTIRISH — **BAJARILMAYDI**, biznes qarorini
         kutadi (javobda `pii_retained_employees` sifatida OCHIQ aytiladi).

    ⚠️  ANONIMLASHTIRILADIGAN YAGONA HISOBLAR — ROZILIK BERILGANLAR:
          · O'CHIRISHNI SO'RAGAN xodimlar (`account_deletion_requests`) — bu
            ularning O'Z iltimosi, ya'ni yangi vakolat EMAS. Agar ular yopishda
            bajarilmasa, xodim `pending` holatida ABADIY QOLARDI: do'kon
            yopilgach u kira olmaydi va ega ham harakat qila olmaydi.
          · AKTYORNING O'ZI — faqat `delete_self=True` bo'lsa. Bu uning o'z
            hisobini o'chirish huquqi; standart qiymat `False`, ya'ni jim
            o'chirish YO'Q.

    ⚠️  `Company.status` SEMANTIK yorliq: majburlash `deleted_at` orqali, chunki
        repo (`models/org.py`) `status` ni «hali majburlanmaydi» deb
        ogohlantiradi — YANGI majburlash manbai qo'shilmaydi.
    """
    from app.models.enums import CompanyStatus
    from app.models.org import Company

    ts = now or datetime.now(timezone.utc)
    comp = db.get(Company, owner.company_id)
    if comp is None or comp.deleted_at is not None:
        raise ValueError("company_already_closed")

    #  Ijarachining BARCHA xodimlari — QULF ostida (yopish bilan parallel
    #  o'chirish poygasi).
    #
    #  ⚠️  `deleted_at IS NULL` FILTRI OLIB TASHLANDI (CH-18D). U ISHDAN
    #      BO'SHATILGAN xodimni chetlab o'tardi — holbuki uning ism va
    #      telefoni BAZADA TURADI. Natijada o'chirishni O'ZI so'ragan, keyin
    #      ishdan bo'shatilgan xodim yopishda ham UNUTILARDI: so'rovi abadiy
    #      «kutilmoqda», PII si esa joyida qolardi. Haqiqatan
    #      anonimlashtirilganlar pastda `is_deleted()` bilan chiqarib
    #      tashlanadi, ya'ni ikki marta ishlanmaydi.
    hammasi = (db.query(Employee)
               .filter(Employee.company_id == owner.company_id)
               .order_by(Employee.id)
               .with_for_update(of=Employee)
               .all())

    #  ROZILIK BERGANLAR: o'chirishni O'ZI so'ragan xodimlar.
    #  ⚠️  RO'YXAT BITTA MARTA, QULF OSTIDA o'qiladi va OXIRIDA BITTA marta
    #      yoziladi. Ilgari har bir xodim uchun alohida `clear_request`
    #      chaqirilardi — bu N ta read-modify-write edi, ya'ni shu payt
    #      so'rov yuborayotgan xodim oraga tushib qolishi mumkin edi. Qulfni
    #      BOSHIDA olish yopish qaroriga asos bo'lgan ro'yxat bilan
    #      BAJARILADIGAN ro'yxatni bir xil qiladi.
    sorov_qatori = _requests_row_locked(db, owner.company_id)
    sosalgan = {str(it.get("employee_id")) for it in _items(sorov_qatori)}
    bajarildi, qoldi = [], 0
    for e in hammasi:
        if is_deleted(e):
            continue
        rozi = str(e.id) in sosalgan or (delete_self and e.id == owner.id)
        if rozi:
            anonymize(db, e, now=ts)
            bajarildi.append(str(e.id))
        else:
            qoldi += 1

    #  Bajarilgan so'rovlar ro'yxatdan BIR MARTA olib tashlanadi — osilib
    #  qolgan `pending` qolmaydi.
    if bajarildi:
        tugallangan = set(bajarildi)
        sorov_qatori.value = {
            "items": [it for it in _items(sorov_qatori)
                      if str(it.get("employee_id")) not in tugallangan]}
        sorov_qatori.row_version += 1

    comp.deleted_at = ts
    comp.status = CompanyStatus.CLOSED.value
    return {
        "closed": True,
        #  Rozilik bergan hisoblar (so'rov + ixtiyoriy aktyor).
        "anonymized_employees": len(bajarildi),
        #  ⚠️  OCHIQ AYTILADI: bu hisoblarda ism/telefon HAMON BOR. Jim
        #      qoldirish ega qoidasi 5 ga zid bo'lardi; jim o'chirish esa
        #      tasdiqlanmagan qaytarilmas amal bo'lardi. Shu bois — HISOBOT.
        "pii_retained_employees": qoldi,
        #  Ommaviy anonimlashtirish BAJARILMAYDI; qaror kutilmoqda.
        "bulk_anonymization": "not_performed_pending_owner_decision",
    }


# ══ O'CHIRISH SO'ROVI — PAROLSIZ (PIN'li) XODIM UCHUN (CH-18B) ══════════════
#
#  ⚠️  PIN O'ZI QAYTARILMAS O'CHIRISHGA YETARLI EMAS (ega qoidasi). PIN qisqa,
#      do'konda ko'pincha ulashilgan va yonidagi odam ko'rib qolishi mumkin.
#      Shu bois PIN'li xodim o'chirishni BOSHLAYDI (so'rov qoldiradi), bajarish
#      esa EGANING parol bilan qayta autentifikatsiyasini talab qiladi.
#      Natijada: boshlash OSON va ilova ichida, bajarish esa KUCHLI tasdiq
#      ostida — Apple 5.1.1(v) «ilova ichidan boshlash» talabi bajariladi.
#
#  ⚠️  SXEMA O'ZGARMAYDI: so'rovlar mavjud `Setting` kalit->JSONB do'konida
#      (`UNIQUE(company_id, branch_id, key)`) RO'YXAT sifatida yashaydi.
#      `_validate_value` (`api/v1/settings.py`) bu kalitni BILMAYDI, ya'ni
#      umumiy `PUT /settings` orqali SOXTALASHTIRIB bo'lmaydi.

REQUESTS_KEY = "account_deletion_requests"


def _requests_row(db: Session, company_id, *, lock: bool = False):
    """So'rovlar ro'yxati turgan `Setting` qatori.

    ⚠️  `lock=True` — YOZISHDAN OLDIN MAJBURIY (CH-18D). Ro'yxatga yozish
        read-modify-write: butun ro'yxat o'qiladi, element qo'shiladi/olinadi
        va butun ro'yxat QAYTA YOZILADI. Qulfsiz ikki yozuvchi bir-birini
        BOSIB KETADI va xodim «so'rovim yuborildi» deb ko'rsa-da, ega uni
        hech qachon ko'rmaydi; teskari tomonda esa bajarilgan so'rov QAYTA
        TIRILADI (`test_PG_8_...` buni aynan shunday tutgan).

        `order_by(row_version.desc())` legacy-dublikat qator uchun (naqsh
        `api/v1/settings.py:176` bilan AYNI).
    """
    from app.models.settings import Setting
    q = (db.query(Setting)
         .filter(Setting.company_id == company_id,
                 Setting.branch_id.is_(None),
                 Setting.key == REQUESTS_KEY)
         .order_by(Setting.row_version.desc()))
    if lock:
        #  ⚠️  FLUSH `populate_existing()` DAN OLDIN. `populate_existing()`
        #      obyektni BAZADAN qayta yuklaydi va hali flush qilinmagan
        #      o'zgarishni JIM YO'Q QILADI. Ayni tranzaksiyada ikki marta
        #      yozilsa (yopish paytida har bir rozilik bergan xodim uchun),
        #      ikkinchi o'qish birinchisining natijasini bosib ketardi va
        #      BITTA so'rov ro'yxatda QOLIB KETARDI —
        #      `test_A_YOPISHDA_ROZILIK_berganlar_va_EGA_BIRGA_ochiriladi`
        #      buni aynan shunday tutgan. Flush o'zgarishni bazaga yuboradi,
        #      shu bois qayta yuklash AYNI qiymatni o'qiydi.
        db.flush()
        q = q.with_for_update().populate_existing()
    return q.first()


def _requests_row_locked(db: Session, company_id):
    """Qulflangan qatorni QAYTARADI, kerak bo'lsa YARATADI.

    ⚠️  PARALLEL BIRINCHI-INSERT POYGASI. Qator hali yo'q bo'lsa, ikki
        yozuvchi ham uni yaratishga urinadi va
        `UNIQUE(company_id, branch_id, key)` bittasini rad etadi. Naqsh
        `api/v1/settings.py:199-208` dagi bilan AYNI: xatoni ushlab, raqib
        yozgan qatorni QULF bilan qayta o'qiymiz. Farqi — bu yerda SAVEPOINT
        ishlatiladi, chunki bu servis chaqiruvchining tranzaksiyasi ichida
        ishlaydi va uni butunlay qaytarib bo'lmaydi.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.settings import Setting
    row = _requests_row(db, company_id, lock=True)
    if row is not None:
        return row
    try:
        with db.begin_nested():
            db.add(Setting(company_id=company_id, key=REQUESTS_KEY,
                           value={"items": []}))
    except IntegrityError:
        pass          # raqib ulgurdi — pastda uning qatorini o'qiymiz
    row = _requests_row(db, company_id, lock=True)
    if row is None:   # nazariy: qator ham yo'q, xato ham yo'q
        raise RuntimeError("so'rovlar qatori yaratilmadi")
    return row


def _items(row) -> list[dict]:
    """Qatordagi ro'yxatning YANGI nusxasi (JSONB `Mutable` EMAS — joyida
    o'zgartirish SQLAlchemy uchun ko'rinmas bo'lardi)."""
    items = (row.value or {}).get("items") if row is not None else None
    return list(items) if isinstance(items, list) else []


def list_requests(db: Session, company_id) -> list[dict]:
    return _items(_requests_row(db, company_id))


def request_deletion(db: Session, emp: Employee, *, now: datetime | None = None) -> dict:
    """Xodim o'z hisobini o'chirishni SO'RAYDI (bajarilmaydi).

    Takroriy so'rov IDEMPOTENT: ro'yxatda allaqachon bo'lsa yangi yozuv
    qo'shilmaydi va ayni holat qaytariladi (mijoz «kutilmoqda» deb ko'rsatadi).
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    #  QULF ostida o'qiymiz — raqib yozuvchi bizni bosib ketmasin (CH-18D).
    row = _requests_row_locked(db, emp.company_id)
    items = _items(row)
    for it in items:
        if str(it.get("employee_id")) == str(emp.id):
            return {"requested": True, "repeated": True, "requested_at": it.get("at")}
    items.append({"employee_id": str(emp.id), "at": ts})
    row.value = {"items": items}        # YANGI dict — JSONB `Mutable` emas
    row.row_version += 1
    return {"requested": True, "repeated": False, "requested_at": ts}


def clear_request(db: Session, company_id, employee_id) -> None:
    """Hisob o'chirilgach so'rovni ro'yxatdan olib tashlaydi.

    ⚠️  Qator YO'Q bo'lsa YARATILMAYDI: o'chiradigan narsa yo'q, bo'sh qator
        esa keraksiz yozuv bo'lardi."""
    row = _requests_row(db, company_id, lock=True)
    if row is None:
        return
    row.value = {"items": [it for it in _items(row)
                           if str(it.get("employee_id")) != str(employee_id)]}
    row.row_version += 1


def request_state(db: Session, emp: Employee) -> dict:
    """Mijoz uchun SHAFFOF holat: so'rov yuborilganmi va qachon."""
    for it in list_requests(db, emp.company_id):
        if str(it.get("employee_id")) == str(emp.id):
            return {"pending": True, "requested_at": it.get("at")}
    return {"pending": False, "requested_at": None}
