# -*- coding: utf-8 -*-
"""H2 — SMENA SERVISI (marshrut tanasidan AJRATILGAN).

NIMA UCHUN AJRATILDI
====================
`api/v1/shifts.py` da smena ochish/yopish MARSHRUTNING O'ZIDA edi: `app/services/shifts.py`
umuman yo'q edi va `opened_at`/`closed_at` inline `datetime.now(timezone.utc)` bilan
muhrlanardi (`shifts.py:617`, `:684`). Shu sababli tarixiy smena yozishning HECH QANDAY
yo'li yo'q edi.

Bu modul o'sha IKKI tanani AYNAN ko'chirib oladi va ularga BITTA ixtiyoriy
`at` parametri qo'shadi. Marshrutlar endi yupqa o'ram.

⚠️  TANA BAYT-AYNAN KO'CHIRILDI. Qo'lda qayta yozilmadi — programmatik ajratildi va
    har tanada AYNAN IKKI o'rin almashtirildi:
      1. `opened_at=datetime.now(timezone.utc)` / `s.closed_at = datetime.now(...)`
         -> `_now_at` (quyida `resolve_at` dan olinadi);
      2. ledger egizagi hook'iga (`on_shift_open` / `on_shift_close`) `at=_now_at`.
    Boshqa birorta satr tegilmadi — qulf tartibi, indeks gardi, T0 custody
    qoidalari, IntegrityError yo'li, Z-hisobot formulasi AYNI.

⚠️  NORMAL SEMANTIKA O'ZGARMAYDI. Marshrut `at` ni UZATMAYDI, ya'ni
    `resolve_at(None, ...)` -> `datetime.now(timezone.utc)`. Oddiy smena ochish/yopish
    AVVALGIDEK hozirgi vaqtni muhrlaydi.

⚠️  TARIXIY `at` DARVOZALI. `resolve_at` (`services/historical.py`) `at` berilganda
    H1 tarixiy kontekstini VA do'kon mosligini TALAB qiladi. Ya'ni tarixiy qobiliyat
    bu funksiyani chaqirish huquqiga emas, H1 DEMO-TENANT DARVOZASIDAN o'tishga
    bog'langan: kontekstsiz `at` — `RuntimeError`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import Employee
from app.models.enums import CashMovementType, ShiftStatus
from app.models.sales import Sale, SalePayment
from app.models.shifts import CashMovement, Shift
from app.services import historical as _H


def open_shift_svc(data, emp: Employee, db: Session, *, at: datetime | None = None,
                   client_uuid: uuid.UUID | None = None) -> dict:
    """Smena ochish — marshrut tanasi AYNAN. `at` faqat tarixiy kontekstda.

    `client_uuid` — IDEMPOTENTLIK kaliti (H2). Marshrut uni UZATMAYDI va `OpenShift`
    sxemasida bunday maydon YO'Q, ya'ni normal sirt o'zgarmagan.

    ⚠️  NEGA KERAK. Tarixiy rejani QAYTA yurgizish smenani IKKI marta ochmasligi
        kerak. `ux_shifts_cashier_open` buni TO'SMAYDI: u faqat AYNI PAYTDA ochiq
        smenani cheklaydi, yopilgan smenadan keyin ikkinchisini ochishga yo'l
        beradi. `Shift.client_uuid` ustuni ALLAQACHON bor (`SyncMixin`), lekin
        2026-10-07 holatiga ko'ra uni HECH BIR yozuvchi yozmaydi — shu bois
        migratsiya KERAK EMAS.

    ⚠️  BU OLDIN-TEKSHIRUV, INDEKS KAFOLATI EMAS. `shifts.client_uuid` ustida
        noyob indeks YO'Q, ya'ni ikki KONKURRENT qayta-yurish ikkala
        tekshiruvdan o'tishi mumkin. Tarixiy bajaruvchi KETMA-KET ishlaydi
        (rejani kun-ba-kun yozadi), shu bois bu yetarli. Haqiqiy kafolat uchun
        qismiy noyob indeks kerak — u ATAYLAB bu yerda EMAS (ega qaroriga,
        H3/D3 doirasi), chunki indeks qo'shish migratsiya va `require_index`
        registriga yozuv talab qiladi.

    ⚠️  DOIRA: dedup `cashier_id` bo'yicha ham filtrlaydi. Xodim bitta do'konga
        tegishli, ya'ni kalit TENANT doirasida qoladi va bir do'konning kaliti
        boshqasida «allaqachon bor» bo'lib chiqmaydi.
    """
    _now_at = _H.resolve_at(at, emp.company_id)
    if client_uuid is not None:
        _ex = (db.query(Shift)
               .filter(Shift.client_uuid == client_uuid, Shift.cashier_id == emp.id)
               .first())
        if _ex is not None:
            return {"id": str(_ex.id), "opened_at": _ex.opened_at}
    #  ⚠️  INDEKS KAFOLATI — YOZUVDAN OLDIN (fail-closed).
    #      «Bir kassirga bir vaqtda BITTA ochiq smena» invariantini SHU yo'lda
    #      `ux_shifts_cashier_open` dan BOSHQA hech narsa kafolatlamaydi: quyidagi
    #      oldin-tekshiruv QULFSIZ `SELECT` (bu yo'lda `FOR UPDATE` umuman yo'q), ya'ni
    #      ikki konkurrent ochish ikkalasi ham undan o'tadi. Indeks esa IntegrityError
    #      beradi va u pastda tutilib mavjud smena qaytariladi — demak indeks
    #      KANONIK kafolat, qo'shimcha qatlam EMAS.
    #      O'lchangan (haqiqiy Postgres, barrier bilan): indeks bor -> ikki konkurrent
    #      ochish AYNI smenani qaytaradi (ochiq=1); indeks DROP qilinsa -> IKKI OCHIQ
    #      SMENA (ochiq=2). Keyin «kassirning ochiq smenasi» ni topadigan 6 ta joy
    #      `.first()` ni TARTIBSIZ ishlatadi (birortasida `order_by` yo'q), `close_shift`
    #      esa faqat berilgan `id` ni yopadi — ikkinchisi ABADIY ochiq qoladi.
    #  ⚠️  SHAKLI RO'YXATGA OLINMAGAN va bu O'LCHANGAN QAROR: predikat enum
    #      solishtiruvini o'z ichiga oladi (`status = 'open'::shift_status`), kanonizator
    #      esa cast'ni faqat text/varchar ustunlar uchun normallashtiradi. Shaklni
    #      `REQUIRED_INDEX_DEFINITIONS` ga qo'shish hukmni `IX_DEF_WRONG` qilardi va gard
    #      HAR smena ochishni 409 qilardi (o'lchangan). Shu bois bu yerda faqat NOYOBLIK
    #      tekshiriladi — yo'q indeks TUTILADI, boshqa ustunli bir xil nomli indeks esa
    #      YO'Q (qoldiq xavf hisobotda qayd etilgan).
    from app.core.index_guard import require_index
    require_index(db, "ux_shifts_cashier_open", "shifts", operation="shift_open")
    if db.query(Shift).filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open).first():
        raise HTTPException(400, "Ochiq smena allaqachon mavjud")
    # QA RET-6: filial tanlash actor_branch bilan IZCHIL (order_by(created_at) + is_active, 3-bosqichli
    # fallback) — ilgari order_by/is_active-siz .first() NODETERMINISTIK edi va smena filialini Return/
    # payout (actor_branch) filialidan farqlantirib, ko'p-filialда naqd qaytarish payout'i boshqa filialга
    # tushishi mumkin edi. Endi savdo/qaytarish YOZUV filiali bilan bir xil.
    #  ⚠️  XODIM QATORI QULFI — `actor_branch` O'QILISHIDAN OLDIN (R6.8 P0-2).
    #      `PATCH /employees/{id}` filialni almashtirishdan oldin AYNI qatorni
    #      qulflaydi (`api/v1/employees.py::_assert_branch_change_allowed`), ya'ni
    #      «smena ochish» va «filial almashtirish» KETMA-KET bajariladi.
    #
    #      Qulfsiz POYGA bor edi: almashtirish «ochiq smena bormi?» ni o'qiydi
    #      (yo'q), shu paytda bu yo'l ESKI filialni o'qib smena yaratadi, keyin
    #      ikkalasi ham commit qiladi -> ochiq smena A filialda, xodim esa B da.
    #      O'sha smenaning keyingi cheklari B ga tushardi.
    #
    #      QO'SHIMCHA RAQOBAT YO'Q: bir xodimda bir vaqtda bitta ochiq smena
    #      bo'ladi (`ux_shifts_cashier_open`), ya'ni bu qulf allaqachon amalda
    #      ketma-ket bo'lgan yo'lni serializatsiya qiladi. SQLite'da `FOR UPDATE`
    #      chiqarilmaydi; qulf xulqi `tests/test_r68_branch_shift_race_pg.py` da.
    #
    #      ⚠️  USTUN SO'ROVI + `of=Employee`: `db.query(Employee)` `role` ni EAGER
    #          yuklaydi (`LEFT OUTER JOIN roles`) va Postgres outer join'ning
    #          nullable tomoniga `FOR UPDATE` ni RAD etadi.
    from app.models.auth import Employee as _Emp
    db.query(_Emp.id).filter(_Emp.id == emp.id).with_for_update(of=_Emp).first()
    from app.core.deps import actor_branch as _ab
    branch = _ab(emp, db)
    if not branch:
        raise HTTPException(400, "Filial topilmadi — avval filial yarating")
    if data.terminal_id is not None:
        # §review: fizik checkout MAVJUD va SHU filialга tegishli bo'lishi SHART (aks holда FK xatosi
        # chalg'ituvchi "smena band" bo'lib chiqardi + boshqa-tenant terminal saqlanardi).
        from app.models.org import Terminal
        _term = db.get(Terminal, data.terminal_id)
        if _term is None or _term.branch_id != branch.id:
            raise HTTPException(400, "Terminal topilmadi yoki bu filialga tegishli emas")
    # AUDIT: smenани FIZIK TILL'ga bog'laymiz (server-authoritative). cash_enabled bo'lsa terminal'дан
    # resolve; aks holда (SQLite/cash-disabled/unresolved) None — kassir orqali TILL TAXMIN QILINMAYDI.
    from app.services.cash import cutover as _cut
    from app.services.cash import retrofit as _cr
    # §4 POST-T0 EXACT CUSTODY: T0'dan keyin "filialda bitta TILL bor" degan sababli tanlov
    # QILINMAYDI. Custody AYNAN ko'rsatilishi kerak: klient till_id yuboradi yoki terminal moslik
    # beradi. T0'gacha legacy xulq (single-checkout) SAQLANADI — mavjud klientlar sinmasin.
    _post_t0 = _cr.cash_enabled(db) and _cut.cutover_reached(db, emp.company_id)
    if data.till_id is not None and _cr.cash_enabled(db):
        # AYNAN klient deklaratsiyasi — to'liq validatsiya (tenant + type=TILL + ACTIVE + filial).
        from app.services.cash import till_identity as _ti2
        _acc, _err = _ti2.validate_till_for_branch(db, emp.company_id, branch.id, data.till_id)
        if _acc is None:
            raise HTTPException(400, f"Noto'g'ri kassa (TILL): {_err}")
        # §RC13: till_id VA terminal_id ikkalasi kelsa va ular BOSHQA-BOSHQA drawer'ni
        # ko'rsatsa -> RAD. Aks holda Shift ZID juftlikni saqlardi (till_id bir kassa,
        # terminal_id boshqasi) va keyingi o'quvchilar qaysi biriga ishonishiga qarab
        # ajralib ketardi. TAXMIN QILINMAYDI — operator ziddiyatni o'zi hal qilsin.
        if data.terminal_id is not None:
            _tmatch = _ti2.find_till_by_terminal(db, emp.company_id, branch.id, data.terminal_id)
            if _tmatch is not None and str(_tmatch.id) != str(_acc.id):
                raise HTTPException(409, "Yuborilgan kassa (till_id) va terminal BOSHQA-BOSHQA "
                                         "kassani ko'rsatmoqda — bittasini tanlang.")
        _till_id = _acc.id
    else:
        _till_id = _cr.resolve_till_id(db, emp.company_id, branch.id, terminal_id=data.terminal_id,
                                       allow_single_checkout=not _post_t0)
    # POST-T0 HARD GUARANTEE (dynamic TILL): cutover'дан keyin naqd smena AYNAN ACTIVE TILL'siz ochilmaydi.
    # Fizik kassa TAXMIN qilinmaydi — operator kassa (TILL) yaratgan/tanlagan bo'lishi SHART.
    if _till_id is None and _post_t0:
        raise HTTPException(400, "T0 (cutover)'дан keyin naqd smena AYNAN kassa (TILL) talab qiladi. "
                                 "So'rovda till_id yuboring yoki terminal orqali tanlang. "
                                 "'Filialda bitta kassa bor' degan sababli AVTOMATIK tanlanmaydi.")
    # DYNAMIC TILL concurrency (POST-T0): bir FIZIK kassa (TILL)да bir vaqtда BITTA cash-custody smena.
    # Turli TILL -> parallel OK. PRE-T0/legacy: umumiy-yashik (shared drawer) toleratsiya qilinadi
    # (dual-write cash.shift'ни sh_one_open_per_account bilan boshqaradi; legacy sindirilmaydi).
    if (_till_id is not None and _cr.cash_enabled(db) and _cut.cutover_reached(db, emp.company_id)
            and db.query(Shift).filter(Shift.till_id == _till_id, Shift.status == ShiftStatus.open,
                                       Shift.deleted_at.is_(None)).first() is not None):
        raise HTTPException(400, "Bu kassa (TILL) band — unda allaqачон ochiq smena bor "
                                 "(bir kassa = bir vaqtда bitta cash-custody smena)")
    s = Shift(
        branch_id=branch.id,
        cashier_id=emp.id,
        client_uuid=client_uuid,          # H2 idempotentlik kaliti (normal yo'lda None)
        terminal_id=data.terminal_id,        # fizik checkout -> ko'p-TILL branch'да dual-write exact TILL'ga
        till_id=_till_id,                    # smena bog'langan fizik TILL (savdolar MEROS oladi)
        opened_at=_now_at,
        opening_cash=data.opening_cash,
        status=ShiftStatus.open,
    )
    db.add(s)
    try:
        db.flush()
        # Phase 2b dual-write (guarded): cash.shift ochamiz (+ opening float). SQLite/xaritalanmagan
        # filialда no-op. IntegrityError shu try'да tutiladi (bir vaqtдаги ikkinchi ochish).
        from app.services.cash import retrofit as _cr
        _cr.on_shift_open(db, emp, branch_id=branch.id, legacy_shift_id=s.id, at=_now_at,
                          opening_cash=data.opening_cash, terminal_id=s.terminal_id,
                          till_id=s.till_id)      # §4: cash.shift AYNAN smena kassasida ochiladi
        db.commit()
    except IntegrityError:
        # Bir vaqtда ikkinchi oyna smena ochdi (ux_shifts_cashier_open) — mavjudini qaytaramiz.
        db.rollback()
        ex = db.query(Shift).filter(Shift.cashier_id == emp.id, Shift.status == ShiftStatus.open).first()
        if ex is None and client_uuid is not None:
            # Tarixiy qayta-yurishда smena allaqachon YOPILGAN bo'lishi mumkin —
            # unda yuqoridagi «ochiq» so'rov uni topmaydi; kalit bo'yicha qidiramiz.
            ex = (db.query(Shift)
                  .filter(Shift.client_uuid == client_uuid, Shift.cashier_id == emp.id)
                  .first())
        if ex:
            return {"id": str(ex.id), "opened_at": ex.opened_at}
        raise HTTPException(400, "Ochiq smena allaqachon mavjud")
    db.refresh(s)
    return {"id": str(s.id), "opened_at": s.opened_at}


def close_shift_svc(shift_id: uuid.UUID, data, emp: Employee, db: Session, *,
                    at: datetime | None = None) -> dict:
    """Smena yopish — marshrut tanasi AYNAN. `at` faqat tarixiy kontekstda."""
    _now_at = _H.resolve_at(at, emp.company_id)
    # QA SHIFT-1: smena qatorini FOR UPDATE bilan QULFLAYMIZ — add_cash_movement/cash_op/cash-refund
    # (hammasi smenani qulflaydi) bilan SERIALIZATSIYA. Ilgari db.get (qulfsiz) edi: yopish paytida
    # commit bo'lgan naqd harakati/savdo muzlatilgan expected_cash'dan tushib qolib (TOCTOU), Z-hisobot
    # soxta ortiqcha/kamomad berardi. Qulf FAQAT shift qatoriда (boshqa lock yo'q) — deadlock bermaydi.
    # Qulf + status qayta-tekshiruvi double-close'ni ham to'sadi (ikkinchisi 'closed' ko'radi).
    s = db.query(Shift).filter(Shift.id == shift_id).with_for_update().first()
    if not s or s.cashier_id != emp.id:
        raise HTTPException(404, "Smena topilmadi")
    if s.status != ShiftStatus.open:
        raise HTTPException(400, "Smena allaqachon yopilgan")
    # tizim kutgan naqd = ochilish + smenadagi naqd savdolar
    cash = (
        db.query(SalePayment)
        .join(Sale, Sale.id == SalePayment.sale_id)
        .filter(Sale.shift_id == s.id, SalePayment.method_code == "cash")
        .all()
    )
    expected = Decimal(str(s.opening_cash)) + sum(Decimal(str(p.amount)) for p in cash)
    for m in db.query(CashMovement).filter(CashMovement.shift_id == s.id).all():
        if m.type == CashMovementType.payin:
            expected += Decimal(str(m.amount))
        elif m.type in (CashMovementType.payout, CashMovementType.expense, CashMovementType.collection):
            expected -= Decimal(str(m.amount))
    # §16 O'QISH AVTORITETI (ledger-native do'kon): yuqoridagi legacy formula FAQAT SalePayment va
    # CashMovement ni sanaydi va NAQD XARIDNI o'tkazib yuboradi (u ledgerga OUT yozadi, CashMovement
    # yozmaydi) — natijada Z-hisobot xarid summasiga TENG SOXTA KAMOMAD berardi. Ledger ON_SHIFT
    # legilari barcha fizik harakatni qamraydi, shu bois ledger-native do'konda AYNAN shundan olamiz.
    from app.services.cash import tenant as _cash_tenant
    _led = _cash_tenant.ledger_expected_shift_cash(db, emp.company_id, s.id, s.till_id,
                                                  s.opening_cash)
    if _led is not None:
        expected = _led
    s.counted_cash = Decimal(str(data.counted_cash))
    s.expected_cash = expected
    s.difference = s.counted_cash - expected
    s.closed_at = _now_at
    s.status = ShiftStatus.closed
    # Phase 2b dual-write (guarded): cash.shift ni yopamiz + reconciliation snapshot. SQLite'da no-op.
    from app.services.cash import retrofit as _cr
    _cr.on_shift_close(db, emp, branch_id=s.branch_id, counted_cash=data.counted_cash, at=_now_at,
                       terminal_id=s.terminal_id,
                       till_id=s.till_id,         # §4: ochilishdagi bilan BIR XIL ankor
                       opening_cash=s.opening_cash)
    db.commit()
    return {
        "id": str(s.id),
        "expected_cash": float(expected),
        "counted_cash": float(s.counted_cash),
        "difference": float(s.difference),
    }
