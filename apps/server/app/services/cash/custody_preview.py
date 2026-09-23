# -*- coding: utf-8 -*-
"""KASSA CUSTODY — O'QISH KO'RINISHI (Phase 5E blok + Phase 5G `GET /cash/custody-preview`).

«Bu naqd amal qaysi kassa/seyf hisobidan o'tadi va operator nimani tanlashi kerak?»
degan savolga javob SERVERNIKI. Mijoz (Manager, mobil) uni HISOBLAMAYDI — faqat chizadi.

⚠️  YOZUVCHI BILAN AYNI FUNKSIYA. Blokdagi har qaror yozuvchining O'Z kodidan o'qiladi:
      · filial va smena — yozuvchi AYNAN chaqiradigan yordamchidan (`*_ctx` pastda;
        `receiving.commit`, `customers.pay_credit`, `purchases.pay_supplier`,
        `cashops.cash_op` ularni o'zi ham chaqiradi);
      · custody qarori — `cutover_guard.preview_cash_custody` (HAQIQIY
        `resolve_cash_custody`) yoki `cutover_guard.dry_run` (inkassa manbasi);
    ya'ni ekran «mumkin» deb ko'rsatib, server 400 beradigan holat prinsipial ravishda
    tug'ilmaydi. Bu yerda birorta custody qoidasi QAYTA YOZILMAYDI.

⚠️  BU DARVOZA EMAS. Blok hech narsani taqiqlamaydi va hech narsani ochmaydi —
    yozuvchi o'z tekshiruvini baribir o'zi bajaradi.

REJIMLAR (Phase 5E, `GET /purchases/{id}.cash_custody` bilan AYNI ma'no):
    NOT_APPLICABLE        kassa umuman qatnashmaydi (qarz hujjati)
    NOT_REQUIRED          yozuvchi hisobsiz ham qabul qiladi — mijoz HECH NARSA yubormaydi
    SERVER_RESOLVED       ochiq smena kassasi; mijoz HECH NARSA yubormaydi (`resolved` — ko'rsatish uchun)
    OPERATOR_MUST_CHOOSE  hisob AYNAN tanlanadi: `options` dan biri, oldindan TANLANMAYDI
    BLOCKED               bu aktyor hozir bu amalni bajara olmaydi; `reason` — barqaror kod
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MODE_NOT_APPLICABLE = "NOT_APPLICABLE"      # qarz hujjati — kassa UMUMAN qatnashmaydi
MODE_NOT_REQUIRED = "NOT_REQUIRED"          # pre-T0: server o'zi hal qiladi yoki legacy fallback
MODE_SERVER_RESOLVED = "SERVER_RESOLVED"    # ochiq smena kassasi — mijoz HECH NARSA yubormaydi
MODE_OPERATOR_MUST_CHOOSE = "OPERATOR_MUST_CHOOSE"   # smenasiz post-T0: hisob AYNAN tanlanadi
MODE_BLOCKED = "BLOCKED"                    # shu aktyor bu amalni bajara olmaydi

# ── Kuzatuv jurnalidagi amal nomlari — YOZUVCHI va KO'RINISH uchun BITTA qiymat ──
OP_RECEIVING = "receiving_cash_purchase"
OP_DEBT = "debt_payment"
OP_SUPPLIER = "supplier_payment"

# `GET /cash/custody-preview?operation=` qiymatlari -> yozuvchi RUXSATI.
# ⚠️  RUXSAT YOZUVCHINIKI: ko'rinish yozuvchidan KENG bo'lsa, amalni bajara olmaydigan
#     xodim kassa hisoblari ro'yxatini ko'rardi; TOR bo'lsa — bajara oladigan xodim
#     ko'ra olmasdi. Qiymatlar yozuvchi marshrutlaridagi `require(...)` bilan AYNAN
#     (`tests/test_mobile_parity.py` ularni marshrut dependency daraxtidan solishtiradi).
PREVIEW_PERMISSIONS = {
    "receiving_payment": "xaridlar.edit",        # POST /receiving/commit (payment=cash)
    "debt_payment": "mijozlar.edit",             # POST /customers/{id}/payments (method=cash)
    "supplier_payment": "xaridlar.edit",         # POST /suppliers/{id}/payments (method=cash)
    "collection_destination": "hisobot.view",    # POST /cash/ops (type=collection)
}


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def actor_open_shift(db: Session, emp):
    """Xodimning OCHIQ smenasi (yoki None) — custody rezolyutsiyasining kirish sharti.

    ⚠️  «XODIMNING» — filialning yoki kassaning EMAS. Custody qoidasi (§2) AYNI
        shu xodimning ochiq smenasiga qaraydi; boshqa kassirning smenasi bu yerga
        HECH QACHON kirmaydi (`cutover_guard` moduli izohi: «boshqa kassirning
        smenasi» — taqiqlangan taxminlar ro'yxatida)."""
    from app.models.enums import ShiftStatus as _ShSt
    from app.models.shifts import Shift as _Shift
    return (db.query(_Shift).filter(_Shift.cashier_id == emp.id,
                                    _Shift.status == _ShSt.open).first())


def account_out(acc) -> dict:
    """Kassa hisobining EKRANGA chiqadigan bo'lagi — id/type/code/currency, TAMOM.

    ⚠️  `label`, `terminal_id`, `branch_id`, `status` BERILMAYDI: bu blok
        `GET /tills` allaqachon har autentifikatsiyalangan xodimga ochib
        beradigan ma'lumotdan QAT'IY KAM bo'lishi shart (yangi oshkorlik yo'q)."""
    from app.services.cash import till_identity as _ti
    return {"id": str(acc.id), "type": str(acc.type),
            "code": _ti.account_checkout_code(acc), "currency": str(acc.currency)}


def custody_options(db: Session, company_id, branch_id) -> list:
    """Filialning FAOL (ACTIVE) TILL va SAFE hisoblari — tanlov ro'yxati.

    ⚠️  FAQAT O'SHA FILIAL. Boshqa filial hisobi ro'yxatga tushsa, operator uni
        tanlab, server esa `CASH_CUSTODY_ACCOUNT_INVALID` bilan rad etardi.
    ⚠️  ARXIVLANGAN hisob ham ro'yxatga tushmaydi — AYNI sababdan.
    ⚠️  Kassa quyi tizimi yo'q bo'lsa (SQLite/dev) ro'yxat BO'SH: `CashAccount`
        jadvali u yerda UMUMAN mavjud emas va so'rov xom xato berardi."""
    from app.services.cash import retrofit as _cr
    from app.services.cash import till_identity as _ti
    if not _cr.cash_enabled(db) or branch_id is None:
        return []
    return [account_out(a) for a in (list(_ti.list_tills(db, company_id, branch_id))
                                     + list(_ti.list_safes(db, company_id, branch_id)))]


def safe_options(db: Session, company_id, branch_id, currency=None) -> list:
    """Filialning FAOL SAFE hisoblari (inkassa MANZILI) — valyuta berilsa, faqat mosi.

    ⚠️  Yozuvchi manzilni `require_custody_account(expect_type="SAFE",
        currency=<manba valyutasi>)` bilan tekshiradi: ro'yxat AYNAN o'tadiganlari."""
    from app.services.cash import retrofit as _cr
    from app.services.cash import till_identity as _ti
    if not _cr.cash_enabled(db) or branch_id is None:
        return []
    return [account_out(a) for a in _ti.list_safes(db, company_id, branch_id)
            if currency is None or str(a.currency) == str(currency)]


def _branch_dict(branch) -> dict | None:
    return ({"id": str(branch.id), "name": branch.name} if branch is not None else None)


def empty_block(branch, mode: str = MODE_NOT_APPLICABLE) -> dict:
    return {"mode": mode, "reason": None, "resolved": None, "options": [],
            "branch": _branch_dict(branch)}


def decide(db: Session, emp, *, branch_id, shift, operation: str, options,
           pre_t0_drawer=None) -> dict:
    """Custody QARORI — `{mode, reason, resolved, options}` (filialsiz).

    `options`       — chaqiriladigan funksiya: OPERATOR_MUST_CHOOSE ro'yxati.
    `pre_t0_drawer` — `None` yoki chaqiriladigan funksiya. Yozuvchi T0 gacha
        hisobsiz yozganda DRAWER topishi SHART bo'lsa (tuzatish yo'li:
        `lot_correction.legacy_fallback_resolves`) — o'sha tekshiruv. Kirim, qarz
        va ta'minotchi to'lovi T0 gacha drawer topilmasa ham YOZILADI (legacy
        no-op), shu bois ular uchun `None`.

    Qaror YOZUVCHINING O'Z kodidan: `cash_account_id` ATAYLAB berilmaydi — bu
    «hech narsa yubormasam nima bo'ladi?» degan savol, ya'ni ekran ko'rsatishi
    kerak bo'lgan boshlang'ich holat."""
    from app.services.cash import cutover_guard as _cg
    out = {"mode": MODE_NOT_REQUIRED, "reason": None, "resolved": None, "options": []}
    acc, _enforced, code = _cg.preview_cash_custody(
        db, company_id=emp.company_id, branch_id=branch_id,
        operation=operation, shift=shift, cash_account_id=None)
    if not _cg.enforcement_active(db, emp.company_id):
        # R8/R9 — pre-T0. Server smenadan hal qilgan (acc) yoki yozuvchi hisobsiz
        # o'tadigan bo'lsa ekran HECH NARSA ko'rsatmaydi va yubormaydi.
        if code is None and (pre_t0_drawer is None or acc is not None or pre_t0_drawer()):
            return out
        # ⚠️  TANLOV FAQAT U HAQIQATAN QUTQARADIGAN HOLATDA. Aktyorning ochiq
        #     smenasi kassaga BOG'LANGAN bo'lsa (`shift.till_id` bor), lekin
        #     o'sha kassa yaroqsiz bo'lsa — `resolve_cash_custody` smena
        #     shoxida hisobni RAD etadi (TILL_SHIFT_MISMATCH), ya'ni aniq
        #     hisob ham yordam bermaydi: bu BLOKLANGAN holat, picker emas.
        if code is None and getattr(shift, "till_id", None) is None:
            out.update(mode=MODE_OPERATOR_MUST_CHOOSE, reason=_cg.ERR_CUSTODY_REQUIRED,
                       options=options())
            return out
        out.update(mode=MODE_BLOCKED, reason=code or _cg.ERR_CUSTODY_INVALID)
        return out
    if code is None and acc is not None:
        out.update(mode=MODE_SERVER_RESOLVED, resolved=account_out(acc))   # R2 — smena kassasi
        return out
    if code == _cg.ERR_CUSTODY_REQUIRED:
        out.update(mode=MODE_OPERATOR_MUST_CHOOSE, reason=code, options=options())   # R6
        return out
    # R4 (begona filial smenasi) / R5 (till'siz legacy smena) va boshqa kassa
    # rad etishlari: TANLOV KO'RSATILMAYDI — explicit hisob ham qutqarmaydi
    # (`resolve_cash_custody`: smena shoxi hisobdan OLDIN hal bo'ladi).
    out.update(mode=MODE_BLOCKED, reason=code or _cg.ERR_LEDGER_UNAVAILABLE)
    return out


def safe_block(db: Session, emp, branch, fn, *, what: str) -> dict:
    """`fn()` qarorini filial bilan o'raydi; kutilmagan xatoda FAIL-CLOSED `BLOCKED`.

    ⚠️  «hisob kerak emas» degan MA'NO xatodan HECH QACHON chiqmaydi. Ayni paytda
        blok QO'SHIMCHA maydon — u tufayli butun sahifa 500 bo'lib ketmaydi."""
    from app.services.cash import cutover_guard as _cg
    base = empty_block(branch)
    try:
        base.update(fn())
        return base
    except Exception:       # noqa: BLE001
        log.exception("cash_custody bloki hisoblanmadi: company=%s %s", emp.company_id, what)
        # Tranzaksiya buzilgan bo'lishi mumkin (masalan mavjud bo'lmagan jadval) —
        # uni tozalamasak, sahifaning QOLGAN o'qishlari ham yiqilardi. Bu yo'lda
        # YOZUV yo'q, shu bois qaytarishga hech narsa yo'q.
        db.rollback()
        return {"mode": MODE_BLOCKED, "reason": _cg.ERR_LEDGER_UNAVAILABLE,
                "resolved": None, "options": [], "branch": base["branch"]}


# ══ YOZUVCHILARNING FILIAL/SMENA KONTEKSTI — YOZUVCHI VA KO'RINISH UCHUN BITTA ═══

def receiving_branch(db: Session, emp):
    """`POST /receiving/commit` qabul FILIALI: xodim filiali (`actor_branch`), bo'lmasa
    do'konning birinchi o'chirilmagan filiali. Kirim, qoldiq va naqd oyoq — hammasi shu."""
    from app.core.deps import actor_branch
    from app.models.org import Branch
    return (actor_branch(emp, db)
            or db.query(Branch).filter(Branch.company_id == emp.company_id,
                                       Branch.deleted_at.is_(None)).first())


def receiving_payment_ctx(db: Session, emp):
    """(filial, smena) — naqd kirim custody'si. Smena — XODIMNING o'z ochiq smenasi."""
    return receiving_branch(db, emp), actor_open_shift(db, emp)


def shift_or_actor_branch_id(db: Session, emp, shift):
    """Smenasiz naqd to'lov custody FILIALI: smena bo'lsa uning filiali, aks holda
    `actor_branch`.

    ⚠️  `None` UZATILMAYDI. `branch_id=None` bilan `require_custody_account` filial
        tekshiruvini O'TKAZIB YUBORADI va butun do'kondagi ISTALGAN TILL/SAFE qabul
        bo'lardi — boshqa filial kassasiga naqd yozib yuborish mumkin edi
        (`customers.pay_credit` da yopilgan; Phase 5G da ta'minotchi to'loviga ham)."""
    from app.core.deps import actor_branch
    if shift is not None:
        return shift.branch_id
    ab = actor_branch(emp, db)
    return ab.id if ab is not None else None


def debt_payment_ctx(db: Session, emp):
    """(custody filiali id, smena) — naqd qarz to'lovi (`POST /customers/{id}/payments`)."""
    sh = actor_open_shift(db, emp)
    return shift_or_actor_branch_id(db, emp, sh), sh


def supplier_payment_ctx(db: Session, emp):
    """(custody filiali id, smena) — naqd ta'minotchi to'lovi (`POST /suppliers/{id}/payments`)."""
    sh = actor_open_shift(db, emp)
    return shift_or_actor_branch_id(db, emp, sh), sh


def force_shift_on(db: Session, company_id) -> bool:
    """Do'kon sozlamasi `security.force_shift` — naqd qarz to'lovi ochiq smenani TALAB qiladi."""
    from app.models.settings import Setting as _Set
    row = (db.query(_Set).filter(_Set.company_id == company_id, _Set.key == "security")
           .first())
    return bool(((row.value if row else {}) or {}).get("force_shift"))


def debt_payment_needs_shift(db: Session, emp, shift) -> bool:
    """Smenasiz naqd qarz to'lovi RAD etiladimi (`force_shift` yoqilgan va smena yo'q)."""
    return shift is None and force_shift_on(db, emp.company_id)


def cash_op_shift(db: Session, emp):
    """`POST /cash/ops` yozadigan smena: xodim FILIALIdagi (`actor_branch`) eng oxirgi
    ochiq smena. (Ilgari kompaniyaning global oxirgi ochiq smenasiga tushardi — ko'p
    filialda pul boshqa filial kassasiga kirib ketardi.)"""
    from app.core.deps import actor_branch
    from app.models.enums import ShiftStatus
    from app.models.org import Branch
    from app.models.shifts import Shift
    ab = actor_branch(emp, db)
    q = (db.query(Shift)
         .join(Branch, Branch.id == Shift.branch_id)
         .filter(Branch.company_id == emp.company_id, Shift.status == ShiftStatus.open))
    if ab:
        q = q.filter(Shift.branch_id == ab.id)
    return q.order_by(Shift.opened_at.desc()).first()


def cash_op_movement(db: Session, emp, client_uuid):
    """`POST /cash/ops` idempotentlik KALITI bo'yicha mavjud kassa harakati.

    ⚠️  DOIRA — KOMPANIYA, SMENA EMAS. Kalit `client_uuid`: amal KIMNING smenasiga
        tushgani serverning o'z qaroriga (`cash_op_shift`) bog'liq va u so'rovlar
        orasida O'ZGARADI (POS smenani yopib yangisini ochsa, yoki boshqa kassir
        smenasi eng yangisi bo'lib qolsa). Dedup smenaga bog'langanida javobi
        yo'qolgan amalning TAKRORI yangi smenaga IKKINCHI marta yozilardi —
        mobil ilova esa «qayta yuborish xavfsiz» deb va'da beradi.
        `shifts.add_cash_movement` (POS) smenani AYNAN ko'rsatadi, shu bois u
        yerda smena doirasi to'g'ri; bu yerda esa yagona barqaror kalit — uuid."""
    from app.models.org import Branch
    from app.models.shifts import CashMovement, Shift
    if client_uuid is None:
        return None
    return (db.query(CashMovement)
            .join(Shift, Shift.id == CashMovement.shift_id)
            .join(Branch, Branch.id == Shift.branch_id)
            .filter(Branch.company_id == emp.company_id,
                    CashMovement.client_uuid == client_uuid)
            .order_by(CashMovement.created_at, CashMovement.id)
            .first())


def recorded_collection_destination(db: Session, mv):
    """Saqlangan INKASSANING yozilgan manzili: `(aniqmi, hisob_id|None)`.

    Manzil `CashMovement` da SAQLANMAYDI (Fayzan production'idagi jadvalga ustun
    qo'shilmaydi) — u LEDGER'da: `on_cash_collection` TILL->SAFE transfer yozadi,
    uning IN oyog'i (`source_type=TRANSFER`, `source_id=<harakat id>`, `leg_index=1`)
    AYNAN manzil seyfga tegishli. Shu bois manzil o'sha oyoqdan TIKLANADI.

    `(True, None)` — manzil yozilmagan VA YOZILMAS edi: kassa quyi tizimi yo'q
    (SQLite/dev) yoki smena kassaga bog'lanmagan (pre-T0 legacy) — bunday o'rnatmada
    yozuvchi `destination_safe_id` ni UMUMAN ishlatmaydi, ya'ni u moddiy maydon emas.
    `(False, None)` — oyoq BO'LISHI KERAK edi, lekin yo'q: manzilni aniqlab
    bo'lmaydi. Chaqiruvchi bunda «dublikat» DEMAYDI (fail-closed)."""
    from app.models.org import Branch
    from app.models.shifts import Shift
    from app.services.cash import repositories as _repo
    from app.services.cash import retrofit as _cr
    try:
        if not _cr.cash_enabled(db):
            return True, None
        row = (db.query(Shift.till_id, Branch.company_id)
               .join(Branch, Branch.id == Shift.branch_id)
               .filter(Shift.id == mv.shift_id).first())
        if row is None:
            return False, None                 # smenasi yo'q harakat — aniqlab bo'lmaydi
        till_id, tenant_id = row
        leg = _repo.get_entry_by_business_key(db, tenant_id, "TRANSFER", mv.id, 1)
        if leg is not None:
            return True, str(leg.cash_account_id)
        if till_id is None:
            return True, None                  # legacy no-op: manzil ishlatilmagan
        return False, None
    except Exception:       # noqa: BLE001
        log.exception("inkassa manzilini tiklab bo'lmadi: movement=%s", getattr(mv, "id", None))
        return False, None


def collection_destination_matches(db, mv, destination_safe_id) -> bool:
    """So'rovdagi manzil saqlangan inkassaning YOZILGAN manzili bilan bir xilmi."""
    if db is None:
        return False                           # tekshira olmaymiz -> takror DEMAYMIZ
    aniq, yozilgan = recorded_collection_destination(db, mv)
    if not aniq:
        return False
    if yozilgan is None:
        return True                            # manzil bu o'rnatmada moddiy emas
    return destination_safe_id is not None and str(yozilgan) == str(destination_safe_id)


def cash_movement_matches(mv, *, kind: str, amount, reason, shift_id=None,
                          db: Session | None = None, destination_safe_id=None) -> bool:
    """Saqlangan kassa harakati AYNI amalning TAKRORIMI (moddiy maydonlar bo'yicha).

    ⚠️  Idempotentlik kaliti amalni IDENTIFIKATSIYA qiladi; u amalning MAZMUNINI
        o'zgartirish huquqini bermaydi. Kalit bir xil, tanasi boshqa bo'lsa — bu
        takror emas, YANGI amal: uni «dublikat» deb ok qaytarish pulni jimgina
        yo'qotardi (yozilmagan amal «yozildi» deb ko'rsatilardi). Shu bois
        farqlansa — 409 `IDEMPOTENCY_KEY_REUSED`.

        `shift_id` FAQAT POS yo'lida (`POST /shifts/{id}/cash`) beriladi: u smenani
        AYNAN ko'rsatadi, ya'ni boshqa smena = boshqa amal. `POST /cash/ops` da
        smenani SERVER hal qiladi va u so'rovlar orasida o'zgarishi mumkin, shu
        bois u yerda smena moddiy maydon EMAS.

    ⚠️  INKASSADA MANZIL HAM MODDIY (Phase 5G FX3-A). «Qancha» bir xil bo'lsa-yu
        «qaysi seyfga» boshqa bo'lsa, bu AYNI amal EMAS: takror deb ok qaytarilsa
        pul BIRINCHI seyfda qolar, kassir esa ikkinchisiga yozilgan deb bilardi
        (ikki seyf sanog'i butun boshli inkassaga ayro tushardi va buni ekranda
        hech narsa ko'rsatmasdi). Manzilni ANIQLAB bo'lmasa — TAKROR DEMAYMIZ.
    """
    from decimal import Decimal as _D
    if mv is None:
        return False
    if shift_id is not None and str(mv.shift_id) != str(shift_id):
        return False
    if getattr(mv.type, "value", mv.type) != kind:
        return False
    if _D(str(mv.amount)) != _D(str(amount)):
        return False
    if (mv.reason or "") != (reason or ""):
        return False
    if kind == "collection":
        return collection_destination_matches(db, mv, destination_safe_id)
    return True


def collection_source(db: Session, emp, shift):
    """Inkassa MANBASI — smena kassasi (ACTIVE TILL, smena filiali). Kassa quyi
    tizimi yo'q bo'lsa `None` (legacy: ledger oyog'i yozilmaydi, manzil so'ralmaydi)."""
    from app.services.cash import cutover_guard as _cg
    from app.services.cash import retrofit as _cr
    if not _cr.cash_enabled(db):
        return None
    return _cg.require_custody_account(
        db, company_id=emp.company_id, branch_id=shift.branch_id,
        account_id=shift.till_id, operation="collection_source", expect_type="TILL")


def collection_destination(db: Session, emp, shift, src, destination_safe_id):
    """Inkassa MANZILI — AYNAN ko'rsatilgan ACTIVE SAFE (smena filiali, manba valyutasi).

    Sukut bo'yicha seyf TANLANMAYDI (filialda 0..N SAFE). Bir xil hisob / boshqa tenant /
    boshqa filial / boshqa valyuta / arxivlangan / type != SAFE -> RAD."""
    from fastapi import HTTPException

    from app.services.cash import cutover_guard as _cg
    dst = _cg.require_custody_account(
        db, company_id=emp.company_id, branch_id=shift.branch_id,
        account_id=destination_safe_id, operation="collection_destination",
        expect_type="SAFE", currency=src.currency)
    if str(src.id) == str(dst.id):
        raise HTTPException(400, "Inkassa: manba va manzil bir xil hisob bo'lishi mumkin emas")
    return dst


# ══ `GET /cash/custody-preview` ══════════════════════════════════════════════

def preview(db: Session, emp, operation: str) -> dict:
    """Berilgan naqd amal uchun custody bloki — yozuvchi bilan AYNI kontekstda."""
    from app.models.org import Branch
    if operation == "receiving_payment":
        branch, shift = receiving_payment_ctx(db, emp)
        if branch is None:
            from fastapi import HTTPException
            raise HTTPException(400, "Filial topilmadi")      # yozuvchi bilan AYNI rad
        return safe_block(db, emp, branch, lambda: decide(
            db, emp, branch_id=branch.id, shift=shift, operation=OP_RECEIVING,
            options=lambda: custody_options(db, emp.company_id, branch.id)),
            what="receiving_payment")

    if operation in ("debt_payment", "supplier_payment"):
        ctx = debt_payment_ctx if operation == "debt_payment" else supplier_payment_ctx
        op = OP_DEBT if operation == "debt_payment" else OP_SUPPLIER
        branch_id, shift = ctx(db, emp)
        branch = db.get(Branch, branch_id) if branch_id is not None else None

        def _d():
            if operation == "debt_payment" and debt_payment_needs_shift(db, emp, shift):
                # `force_shift` yoqilgan do'kon: smenasiz naqd qarz to'lovi HISOB
                # tanlansa ham rad etiladi — tanlov ko'rsatish yolg'on bo'lardi.
                from app.core import error_codes as _EC
                return {"mode": MODE_BLOCKED, "reason": _EC.OPEN_SHIFT_REQUIRED}
            return decide(db, emp, branch_id=branch_id, shift=shift, operation=op,
                          options=lambda: custody_options(db, emp.company_id, branch_id))
        return safe_block(db, emp, branch, _d, what=operation)

    if operation == "collection_destination":
        return _collection_preview(db, emp)
    raise ValueError(operation)


def _collection_preview(db: Session, emp) -> dict:
    """Inkassa manzili. Manzil kassa quyi tizimi bor joyda HAR DOIM aniq tanlanadi
    (T0 dan qat'i nazar) — yozuvchi (`cash_op`) shunday ishlaydi."""
    from app.core import error_codes as _EC
    from app.core.deps import actor_branch
    from app.models.org import Branch
    from app.services.cash import cutover_guard as _cg
    shift = cash_op_shift(db, emp)
    if shift is None:
        blk = empty_block(actor_branch(emp, db), MODE_BLOCKED)
        blk["reason"] = _EC.OPEN_SHIFT_REQUIRED               # yozuvchi: «Ochiq smena yo'q»
        return blk
    branch = db.get(Branch, shift.branch_id)

    def _d():
        _r, code = _cg.dry_run(_cg.cutover_open_shift_gate, db, company_id=emp.company_id,
                               shift=shift, operation="cash_op:collection")
        if code is not None:
            return {"mode": MODE_BLOCKED, "reason": code}
        src, code = _cg.dry_run(collection_source, db, emp, shift)
        if code is not None:
            return {"mode": MODE_BLOCKED, "reason": code}
        if src is None:
            return {"mode": MODE_NOT_REQUIRED}                 # kassa quyi tizimi yo'q
        return {"mode": MODE_OPERATOR_MUST_CHOOSE, "reason": _cg.ERR_CUSTODY_REQUIRED,
                "options": safe_options(db, emp.company_id, shift.branch_id, src.currency)}
    return safe_block(db, emp, branch, _d, what="collection_destination")
