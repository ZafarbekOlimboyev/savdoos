import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import (FULL_ACCESS_ROLES, effective_permissions,
                          get_current_employee, visible_branches)
from app.core import ratelimit as RL
from app.core.net import client_ip
from app.core.password_policy import enforce_password_policy
from app.core.security import create_access_token, hash_password, norm_phone, verify_password
from app.db.session import get_db
from app.models.auth import Employee
from app.models.enums import EmployeeStatus
from app.models.org import Company
from app.schemas.auth import (ChangePassword, EmployeeOut, LoginPassword, LoginPin,
                             PinRosterItem, Token)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Brute-force himoya — UMUMIY holat (`app/core/ratelimit`, PostgreSQL) ──
#
# ⚠️  Ilgari hisoblagichlar JARAYON XOTIRASIDA (`_ATTEMPTS` lug'ati) edi. Ular
#     har deploy'da NOLGA tushardi va instanslar o'rtasida BO'LINMASDI, ya'ni
#     "10 xatodan keyin blok" degan kafolat amalda hech narsani kafolatlamasdi:
#     hujumchi deploy kutib yoki boshqa instansga urib chetlab o'tardi.
#     Vendor yo'lida Postgres asosidagi naqsh allaqachon isbotlangan.


def _client_ip(request) -> str:
    """Mijoz IP'si — ISHONCHLI PROXY modeliga muvofiq (`app/core/net`).

    ⚠️  Ilgari bu yerda `X-Forwarded-For` ning eng o'ng qismi olinardi va docstring
    "shunda IP kaliti global bo'lib qolmaydi" deb da'vo qilardi. Aslida eng o'ng
    qism CDN/ichki hop manzili, ya'ni BARCHA mijozlar uchun BIR XIL — oldini
    olmoqchi bo'lgan cross-tenant DoS aynan o'z kuchida qolgan edi.

    ⚠️  ANIQLANMASA BO'SH QAYTARADI, "?" EMAS. Ilgari bu funksiya "?" qaytarardi va
    o'sha "?" BITTA GLOBAL kalitga aylanardi: `client_ip` bo'sh qiymat qaytargan
    holatda (XFF bor, lekin birinchi hop ichki manzil) BARCHA do'konlarning barcha
    mijozlari bitta hisoblagichni baham ko'rardi — 10 ta xato butun tizimni 5
    daqiqaga kassadan uzardi. Ya'ni bu aynan P0-1 ning tizim miqyosidagi shakli edi.
    Chaqiruvchi bo'sh qiymatda GLOBAL bo'lmagan zaxira kalitga o'tadi."""
    return client_ip(request) or ""


# PIN bilan kirishga HAQLI EMAS bo'lgan ruxsatlar.
#
# ⚠️  PIN — do'kon ichidagi IKKILAMCHI kredensial: 4 raqam, kassa oynasida terilaydi,
#     smena davomida hamkasblar ko'z o'ngida. Do'konni BOSHQARADIGAN shaxs (ega,
#     administrator yoki shu huquqlar berilgan istalgan rol) bu yo'l bilan kira
#     olmasligi kerak — aks holda butun biznes 4 raqam ortida qolardi.
#
#     Rol NOMI bo'yicha emas, RUXSAT bo'yicha tekshiramiz: loyihaning kanonik modeli
#     `modul.harakat` ruxsatlari (app/seed.py PERMISSIONS/ROLES) va xodimga alohida
#     ruxsat ham berilishi mumkin.
_PIN_FORBIDDEN_PERMS = frozenset({
    "xodimlar.make_admin",   # boshqani admin qilish — imtiyoz shifti
    "xodimlar.edit",         # xodim/PIN/rol boshqaruvi
    "sozlamalar.edit",       # do'kon sozlamalari
})


def _pin_login_allowed(emp: Employee, db: Session) -> bool:
    """Bu xodim PIN bilan kira oladimi (imtiyozli boshqaruv huquqi yo'qmi).

    ⚠️  ROL ham qat'iy to'siq. `ega`/`administrator` ruxsatlari bazada "ALL" deb
        beriladi, lekin xodim-darajali override o'sha uchta ruxsatni OLIB TASHLASA,
        faqat ruxsat bo'yicha tekshiruv egani PIN yo'liga QO'YIB YUBORARDI. Rol
        nomi bo'yicha qo'shimcha tekshiruv shu teshikni yopadi."""
    if emp.role.code in FULL_ACCESS_ROLES:
        return False
    return not (_PIN_FORBIDDEN_PERMS & effective_permissions(emp, db))


def _is_suspended(db: Session, company_id) -> bool:
    """Vendor do'konni vaqtincha to'xtatganmi (Setting key='suspended')."""
    from app.models.settings import Setting
    s = db.query(Setting).filter(Setting.company_id == company_id, Setting.key == "suspended").first()
    return bool(s and (s.value or {}).get("on"))


# ⚠️  YAGONA xato matni — do'kon kodi, telefon va PIN/parol uchun BIR XIL.
#     Ilgari "Do'kon kodi topilmadi" va "PIN noto'g'ri" ALOHIDA matnlar edi:
#     bu autentifikatsiyasiz hujumchiga do'kon kodi MAVJUDLIGINI tasdiqlaydigan
#     oracle berardi (kodni topgach hujum aynan o'sha do'konga qaratilardi).
_LOGIN_FAILED = "Kirish ma'lumotlari noto'g'ri"

_SUSPENDED_MSG = "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning."


def employee_out(e: Employee, db: Session) -> EmployeeOut:
    comp = db.get(Company, e.company_id)
    # QA SB-014: chekda kompaniya-darajali bitta store_info.branch chiqardi — endi xodimning
    # HAQIQIY filiali nomi ham beriladi (POS chek shu nomni ishlatadi; biriktirilmagan -> None).
    from app.models.auth import EmployeeBranch as _EB
    from app.models.org import Branch as _Br
    _brow = (db.query(_Br.name).join(_EB, _EB.branch_id == _Br.id)
             .filter(_EB.employee_id == e.id, _Br.deleted_at.is_(None))
             .order_by(_Br.created_at).first())
    return EmployeeOut(
        id=e.id,
        full_name=e.full_name,
        phone=e.phone,
        role_code=e.role.code,
        role_name=e.role.name,
        status=e.status.value,
        company_name=comp.name if comp else None,
        company_code=comp.code if comp else None,   # qurilma sozlamasini o'zini-o'zi tuzatish uchun
        # Valyuta kontrakti: pul birligi TILdan emas, do'kon sozlamasidan keladi (ISO-4217).
        company_currency=comp.currency if comp else None,
        permissions=sorted(effective_permissions(e, db)),
        branch_name=(_brow[0] if _brow else None),
    )


def _token(e: Employee, db: Session) -> Token:
    token = create_access_token(str(e.id), {
        "role": e.role.code,
        "company_id": str(e.company_id),
        "sv": int(e.sec_epoch or 0),  # token bekor qilish davri (parol/chiqishда oshadi)
    })
    return Token(access_token=token, employee=employee_out(e, db))


# Telefon MAVJUD emasligини javob vaqtidan bilib olishга yo'l qo'ymaslik uchun (timing enumeration),
# nomzod topilmasa ham bir marta soxta bcrypt qiyoslash bajaramiz — ikkala yo'l bir xil vaqt oladi.
_DUMMY_HASH = hash_password("savdoos-timing-guard")


@router.get("/pin-roster", response_model=list[PinRosterItem])
def pin_roster(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """PIN bilan kira oladigan xodimlar — POS'dagi "kassirni tanlang" ekrani uchun.

    ⚠️  BU ANONIM ENDPOINT EMAS va hech qachon bo'lmasligi kerak. Ro'yxatni faqat
        SHU do'konga ALLAQACHON kirgan xodim oladi: qurilmani ega/menejer bir marta
        parol bilan sozlaydi, POS ro'yxatni lokal keshlaydi va keyin kassirlar shu
        keshdan tanlaydi. Anonim foydalanuvchi `company_code` bilan xodimlar
        ro'yxatini OLA OLMAYDI — aks holda bu ochiq employee-enumeration bo'lardi
        (ism o'g'irlash + maqsadli PIN hujumi uchun tayyor ro'yxat).

    ⚠️  Ataylab kam ma'lumot: telefon ham, rol ham qaytarilmaydi. Ro'yxat do'kon
        zalidagi qurilmada keshda yotadi — u yerda ortiqcha ma'lumot saqlanmasin.

    Filial ko'rinishi mavjud modelga BO'YSUNADI (`visible_branches`): filialga
    biriktirilgan xodim faqat o'z filialini, ega esa butun do'konni ko'radi."""
    from app.models.auth import EmployeeBranch

    rows = (db.query(Employee)
            .filter(Employee.company_id == emp.company_id,
                    Employee.deleted_at.is_(None),
                    Employee.pin_hash.isnot(None),
                    Employee.status == EmployeeStatus.active)
            .all())

    allowed = visible_branches(emp, db)          # None = cheklovsiz
    bmap = _branch_names(db, emp.company_id)
    bset: dict = {}
    if allowed is not None:
        # Faqat SHU do'kon xodimlari bo'yicha — boshqa tenant qatorlari umuman o'qilmasin.
        ids = [e.id for e in rows]
        if ids:
            for eid, bid in (db.query(EmployeeBranch.employee_id, EmployeeBranch.branch_id)
                             .filter(EmployeeBranch.employee_id.in_(ids)).all()):
                bset.setdefault(eid, set()).add(bid)

    eligible = _pin_eligible_ids(db, rows)
    out: list[PinRosterItem] = []
    for e in rows:
        if e.id not in eligible:
            continue                              # ega/admin bu ro'yxatda KO'RINMAYDI
        if allowed is not None:
            own = bset.get(e.id)
            # Filialga biriktirilmagan xodim kompaniya bo'ylab ko'rinadi — bu
            # `visible_branches` ning O'Z semantikasi, shu bois izchil saqlanadi.
            if own and not (own & allowed):
                continue
        out.append(PinRosterItem(id=e.id, full_name=e.full_name, branch_name=bmap.get(e.id)))
    return out


def _pin_eligible_ids(db: Session, rows) -> set:
    """PIN bilan kira oladigan xodimlar to'plami — XODIM BOSHIGA SO'ROVSIZ.

    ⚠️  Ilgari bu yerda har bir xodim uchun `effective_permissions` chaqirilardi va
        u xodim boshiga bitta `employee_permissions` so'rovi berardi: 108 xodimli
        do'konda 108 ta ortiqcha so'rov (o'lchangan, taxmin emas). 'business'
        tarifida shift 999 xodim — ya'ni bitta autentifikatsiyalangan so'rov
        bazani ko'mib tashlashi mumkin edi. Endi hammasi ikkita so'rov."""
    from app.models.auth import EmployeePermission, Permission
    ids = [e.id for e in rows]
    if not ids:
        return set()
    pcode = {pid: code for pid, code in db.query(Permission.id, Permission.code).all()}
    ov: dict = {}
    for eid, pid, allowed in (db.query(EmployeePermission.employee_id,
                                       EmployeePermission.permission_id,
                                       EmployeePermission.allowed)
                              .filter(EmployeePermission.employee_id.in_(ids)).all()):
        ov.setdefault(eid, []).append((pcode.get(pid), allowed))

    out = set()
    for e in rows:
        if e.role.code in FULL_ACCESS_ROLES:
            continue
        perms = {p.code for p in e.role.permissions}      # Role.permissions — lazy="selectin"
        for code, allowed in ov.get(e.id, ()):
            if code is None:
                continue
            if allowed:
                perms.add(code)
            else:
                perms.discard(code)
        if not (_PIN_FORBIDDEN_PERMS & perms):
            out.add(e.id)
    return out


def _branch_names(db: Session, company_id) -> dict:
    """{employee_id: 'Filial nomi'} — bitta so'rovda."""
    from app.models.auth import EmployeeBranch as _EB
    from app.models.org import Branch as _Br
    out: dict = {}
    for eid, bname in (db.query(_EB.employee_id, _Br.name)
                       .join(_Br, _Br.id == _EB.branch_id)
                       .filter(_Br.company_id == company_id, _Br.deleted_at.is_(None)).all()):
        out.setdefault(eid, []).append(bname)
    return {k: ", ".join(v) for k, v in out.items()}


def _pin_lookup(db: Session, data: LoginPin):
    """(xodim_qatori, do'kon_id, haqlimi) — bcrypt BAJARILMAYDI.

    ⚠️  DO'KON QATORDAN OLINADI, HAQLILIKDAN QAT'IY NAZAR. Ilgari bu funksiya
        haqsiz xodim uchun ham `None` qaytarardi va chaqiruvchi do'konni umuman
        bilmasdi — natijada `cand`/`store` qatlamlari FAQAT haqli xodimlar uchun
        ishlardi. Bu esa "429 keldi = bu ID haqiqiy, faol va PIN-haqli" degan
        oracle berardi (o'lchangan: 5 ta xatodan keyin haqli ID 429, boshqasi 401).
        Endi qatlamlar har qanday HAQIQIY qator uchun bir xil ishlaydi.

    Rad etish sabablari (yo'q / o'chirilgan / faol emas / boshqa do'kon / imtiyozli)
    tashqaridan FARQLANMAYDI: hammasi `haqli=False` va chaqiruvchi baribir aynan
    bitta bcrypt bajaradi."""
    emp = db.get(Employee, data.employee_id)
    if emp is None:
        return None, None, False
    comp = db.get(Company, emp.company_id)
    # Do'kon QATORI umuman yo'q bo'lsa `company_id` QAYTARILMAYDI: `cand`/`store`
    # yozuvlari `companies.id` ga FK bilan bog'langan, ya'ni mavjud bo'lmagan
    # do'kon bilan yozish FK buzilishiga va 500 ga olib kelardi. (Postgres FK'lari
    # buni deyarli imkonsiz qiladi, lekin bu yo'l autentifikatsiyasiz.)
    company_id = comp.id if comp is not None else None
    if emp.deleted_at is not None or emp.pin_hash is None:
        return emp, company_id, False
    if emp.status != EmployeeStatus.active:
        return emp, company_id, False
    if comp is None or comp.deleted_at is not None:
        return emp, company_id, False
    if data.company_code and comp.code != data.company_code.strip().lower():
        return emp, company_id, False   # boshqa do'kon — mavjudligi OSHKOR QILINMAYDI
    if not _pin_login_allowed(emp, db):
        return emp, company_id, False   # imtiyozli identifikator PIN yo'lidan KIRMAYDI
    return emp, company_id, True


@router.post("/login", response_model=Token)
def login_pin(data: LoginPin, request: Request, db: Session = Depends(get_db)):
    """Kassir PIN login — AVVAL xodim tanlanadi, keyin PIN.

    ⚠️  NEGA XODIM AVVAL TANLANADI. Ilgari bu endpoint PIN'ni do'kondagi HAR BIR
        xodim hash'i bilan qiyoslardi. bcrypt (cost 12) ≈ 220 ms, ya'ni bitta
        AUTENTIFIKATSIYASIZ so'rov 25 xodimli do'konda ~5.6, 100 xodimda ~22
        CPU-soniya yeyardi (o'lchangan, taxmin emas). Bir necha parallel so'rov
        butun serverni to'xtatishi mumkin edi.

        Endi POS `employee_id` yuboradi va server AYNAN BITTA hash'ni tekshiradi.
        Nomzod topilmasa ham AYNAN BITTA soxta bcrypt bajariladi — javob matni ham,
        vaqti ham bir xil.

    ⚠️  ESKI YO'L ATAYLAB QOLDIRILMADI. `employee_id` MAJBURIY: "eski mijozlar
        uchun" fallback qoldirilsa, DoS yo'li ochiq qolardi va tuzatish tuzatish
        bo'lmasdi. POS/Manager AYNI relizda yangilanadi.

    ⚠️  `employee_id` MAXFIY EMAS — u shunchaki 122-bitli identifikator. Xavfsizlik
        PIN'ning o'zida va cheklovlarda; ro'yxat esa faqat autentifikatsiyalangan
        `/auth/pin-roster` orqali beriladi."""
    ip = _client_ip(request)
    # IP qatlami GLOBAL (company_id=None) — do'kon aniqlanishidan OLDIN tekshiriladi.
    # IP aniqlanmasa kalit XODIMGA bog'lanadi: "bitta umumiy kalit" butun tizimni
    # bloklaydigan holatga aylanmasin (izoh: `_client_ip`).
    ipk = f"pin:{ip}" if ip else f"pin:?:{data.employee_id}"
    RL.guard(db, "ip", ipk, RL.IP_TIER)

    # XODIM qatlami. Ataylab xodim MAVJUDLIGIDAN QAT'IY NAZAR ishlaydi: aks holda
    # "429 keldi = bu employee_id haqiqiy" degan oracle paydo bo'lardi.
    acctk = f"pin:{data.employee_id}"
    RL.guard(db, "acct", acctk, RL.ACCT_TIER)

    emp, company_id, haqli = _pin_lookup(db, data)   # arzon PK o'qish — bcrypt YO'Q

    candk = None
    throttled = False
    if company_id is not None:
        # NOMZOD qatlami — endi ham KERAK. Xodim qatlami (`acct`) bitta xodimga
        # qaratilgan hujumni to'sadi, lekin BITTA PIN'ni KO'P xodimga sepish
        # (spray) har safar boshqa `acct` kaliti bo'lgani uchun undan o'tib
        # ketardi. `cand` aynan (do'kon, PIN qiymati) juftini sanaydi.
        #
        # ⚠️  BU QATLAM 429 BERMAYDI. Ilgari u `HTTPException(429)` otardi va
        #     shu 429 "bu employee_id haqiqiy" degan oracle bo'lib xizmat qilardi.
        #     Endi chegara oshsa AYNAN O'SHA 401 qaytariladi — ya'ni javob
        #     noto'g'ri PIN'dan farq qilmaydi. Bloklash kuchida qoladi: bu holatda
        #     TO'G'RI PIN ham qabul qilinmaydi.
        candk = RL.candidate_bucket(company_id, data.pin)
        throttled = RL.over_limit(db, "cand", candk, RL.CAND_TIER, company_id)
        # DO'KON qatlami — SEKINLASHTIRISH, rad etish EMAS.
        delay = RL.store_backoff(db, company_id)
        if delay:
            time.sleep(delay)

    # AYNAN BITTA bcrypt — BARCHA tarmoqlarda, `throttled` holatida ham. Soxta hash
    # o'zgarmas sinov qiymatidan olinadi (haqiqiy PIN yoki sirdan EMAS) va hech
    # qayerga yozilmaydi; u faqat javob vaqtini tenglashtirish uchun. Cheklovda ham
    # bcrypt bajariladi, aks holda "tez 401" yana oracle bo'lardi.
    ok = verify_password(data.pin, emp.pin_hash if haqli else _DUMMY_HASH)
    if throttled:
        ok = False          # cheklovda TO'G'RI PIN ham o'tmaydi

    if ok and haqli:
        # Suspend tekshiruvi PIN TASDIQLANGACH (parol oqimi bilan izchil) — aks holda
        # kredensialsiz har kim suspend holatini bilib olardi.
        if _is_suspended(db, company_id):
            RL.clear(db, [("ip", ipk, None), ("acct", acctk, None)])
            raise HTTPException(403, _SUSPENDED_MSG)
        # MUHIM: do'kon-darajali hisoblagich SAQLANADI — aks holda insider
        # "9 xato + o'z PIN'i bilan 1 kirish" sikli bilan uni nolga tushirib,
        # hamkasb PIN'ini cheksiz taxmin qilardi.
        RL.clear(db, [("ip", ipk, None), ("acct", acctk, None)])
        return _token(emp, db)

    fails = [("ip", ipk, None), ("acct", acctk, None)]
    if company_id is not None:
        fails += [("cand", candk, company_id), ("store", str(company_id), company_id)]
    RL.record(db, fails)
    raise HTTPException(401, _LOGIN_FAILED)


@router.post("/login/password", response_model=Token)
def login_password(data: LoginPassword, request: Request, db: Session = Depends(get_db)):
    """Egа/admin login — telefon + parol. Telefon global noyob (parolli akkaunt uchun)."""
    phone = norm_phone(data.phone)
    ip = _client_ip(request)
    # IP aniqlanmasa kalit telefonga bog'lanadi (global kalit bo'lmasin — `_client_ip`).
    ipk = f"pw:{ip}" if ip else f"pw:?:{phone or '-'}"
    if not phone:
        # ⚠️  YAGONA xato matni. Ilgari bu yerda BOSHQA matn qaytarardi va cheklov
        #     ham, bcrypt ham umuman ishlamasdi — ya'ni "raqamsiz telefon" javobi
        #     boshqa har qanday xatodan farq qilardi (kichik, lekin haqiqiy oracle).
        raise HTTPException(401, _LOGIN_FAILED)
    # Hisob qatlami IP'dan MUSTAQIL — bitta telefonga tarqoq hujum ham bloklanadi.
    RL.guard(db, "ip", ipk, RL.IP_TIER)
    RL.guard(db, "acct", f"pw:{phone}", RL.ACCT_TIER)
    candidates = (
        db.query(Employee)
        .filter(
            Employee.phone == phone,
            Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None),
        )
        .all()
    )
    for e in candidates:
        if verify_password(data.password, e.password_hash):
            if e.status != EmployeeStatus.active:
                break  # faol emas — parol to'g'ri ekanini OSHKOR QILMAYMIZ (umumiy xato)
            comp = db.get(Company, e.company_id)
            if not comp or comp.deleted_at is not None:
                break  # o'chirilgan do'kon — umumiy xato bilan yashiramiz
            if _is_suspended(db, e.company_id):
                # to'g'ri parol tasdiqlandi — bloklashni tozalab, aniq sabab beramiz
                RL.clear(db, [("ip", ipk, None), ("acct", f"pw:{phone}", None)])
                raise HTTPException(403, _SUSPENDED_MSG)
            RL.clear(db, [("ip", ipk, None), ("acct", f"pw:{phone}", None)])
            return _token(e, db)
    if not candidates:
        # Telefon ro'yxatda yo'q — bcrypt ishga tushmagan bo'lardi; javob vaqti ochib
        # qo'ymasligi uchun soxta qiyoslash qilamiz (timing enumeration'га qarshi).
        verify_password(data.password, _DUMMY_HASH)
    RL.record(db, [("ip", ipk, None), ("acct", f"pw:{phone}", None)])
    raise HTTPException(401, _LOGIN_FAILED)


@router.post("/password")
def change_password(
    data: ChangePassword,
    emp: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """Foydalanuvchi o'z parolini o'zgartiradi — JORIY KREDENSIAL bilan tasdiqlab.

    ⚠️  STEP-UP MAJBURIY. Ilgari paroli YO'Q akkaunt (PIN bilan kirgan kassir yoki
        endi provision qilingan ega) `old_password` SIZ parol o'rnata olardi. Ya'ni
        O'G'IRLANGAN 12 soatlik token — masalan umumiy kassa terminalidan qolgan
        sessiya — DOIMIY kredensialga aylantirilardi: hujumchi o'ziga parol
        qo'yib, token muddati tugagach ham kira olaverardi.

        Endi joriy kredensialni isbotlash SHART:
          · paroli BOR bo'lsa  -> joriy PAROL,
          · paroli YO'Q bo'lsa -> joriy PIN (u shu akkauntga kirish uchun
            ishlatilgan kredensial).
        Ikkalasi ham yo'q bo'lsa — parolni O'ZI o'rnatib bo'lmaydi; uni imtiyozli
        xodim `xodimlar.edit` orqali beradi (provisioning yo'li o'z holicha qoladi)."""
    new = data.new_password or ""
    enforce_password_policy(new)

    rk = f"chpw:{emp.id}"           # joriy kredensialni cheksiz taxmin qilishga yo'l qo'ymaymiz
    RL.guard(db, "acct", rk, RL.ACCT_TIER, emp.company_id)
    if emp.password_hash:
        if not data.old_password or not verify_password(data.old_password, emp.password_hash):
            RL.record(db, [("acct", rk, emp.company_id)])
            raise HTTPException(401, "Joriy kredensial noto'g'ri")
    elif emp.pin_hash:
        # Paroli yo'q akkaunt: joriy PIN step-up sifatida talab qilinadi.
        if not data.old_password or not verify_password(data.old_password, emp.pin_hash):
            RL.record(db, [("acct", rk, emp.company_id)])
            raise HTTPException(401, "Joriy kredensial noto'g'ri")
    else:
        raise HTTPException(403, "Parolni o'zingiz o'rnata olmaysiz — administratorga murojaat qiling")
    RL.clear(db, [("acct", rk, emp.company_id)])
    # PIN-only akkaunt parolli akkauntga aylanayotgan bo'lsa — telefon GLOBAL noyob bo'lishi shart
    # (aks holda ux_employees_phone_pw partial-unique indeksi xom 500 berardi; edit_employee bilan izchil).
    if not emp.password_hash:
        if not emp.phone:
            raise HTTPException(400, "Parol o'rnatish uchun avval telefon (login) qo'shilishi kerak")
        _clash = db.query(Employee).filter(
            Employee.phone == emp.phone, Employee.password_hash.isnot(None),
            Employee.deleted_at.is_(None), Employee.id != emp.id).first()
        if _clash:
            raise HTTPException(409, "Bu telefon boshqa akkauntda band")
    emp.password_hash = hash_password(new)
    # Parol o'zgardi — barcha ESKI tokenlar bekor bo'lsin (o'g'irlangan/boshqa qurilma sessiyalari).
    emp.sec_epoch = int(emp.sec_epoch or 0) + 1
    db.commit()
    db.refresh(emp)
    # Joriy qurilma chiqib qolmasligi uchun yangi (amaldagi) token qaytaramiz — mijoz uni almashtiradi.
    return {"ok": True, "access_token": create_access_token(str(emp.id), {
        "role": emp.role.code, "company_id": str(emp.company_id), "sv": int(emp.sec_epoch or 0),
    })}


@router.post("/logout")
def logout(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """Server tomonda chiqish — sec_epoch oshadi, shu xodimning HAMMA tokeni bekor bo'ladi.
    (O'g'irlangan token endi mahalliy 'chiqish' bilan ham amalda bekor qilinadi.)"""
    emp.sec_epoch = int(emp.sec_epoch or 0) + 1
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=EmployeeOut)
def me(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    return employee_out(emp, db)


@router.get("/context")
def context(emp: Employee = Depends(get_current_employee), db: Session = Depends(get_db)):
    """MIJOZ KONTEKSTI (Phase 5G, mobil ilova) — kim, qaysi do'kon, qaysi ruxsatlar, qaysi filial.

    `{employee, company, permissions, full_access, actor_branch, branch_scope, branches}`

    ⚠️  HECH NARSA YANGI OCHILMAYDI — faqat server allaqachon QO'LLAYOTGAN qoidalar aytiladi:
        · `permissions` — `effective_permissions` (rol + override), `/auth/me` bilan AYNI;
        · `full_access` — `ega`/`administrator` (`require` ularni shartsiz o'tkazadi);
        · `actor_branch` — yozuvlar (kirim, sotuv, sanoq) TUSHADIGAN filial (`deps.actor_branch`);
        · `branches` — xodim KO'RA oladigan filiallar (`deps.visible_branches`; cheklovsiz
          bo'lsa — do'konning barcha o'chirilmagan filiallari), `created_at, id` tartibida;
        · `business_date` — filial vaqt zonasidagi BIZNES sanasi (`lot_policy.business_date`),
          muddat tekshiruvlari aynan shu sanaga tayanadi.
    ⚠️  MIJOZ BU YERDAN QAROR CHIQARMAYDI — faqat UX (tugmani yashirish, ogohlantirish).
        Har yozuvchi o'z ruxsati va filial doirasini baribir o'zi tekshiradi."""
    from app.core.deps import actor_branch
    from app.models.org import Branch
    from app.services import lot_policy as LP

    def _br(b) -> dict:
        return {"id": str(b.id), "name": b.name, "is_active": bool(b.is_active),
                "timezone": b.timezone,
                "business_date": LP.business_date(db, b.id).isoformat()}

    comp = db.get(Company, emp.company_id)
    vb = visible_branches(emp, db)
    q = db.query(Branch).filter(Branch.company_id == emp.company_id,
                                Branch.deleted_at.is_(None))
    if vb is not None:
        q = q.filter(Branch.id.in_(vb))
    branches = q.order_by(Branch.created_at, Branch.id).all()
    ab = actor_branch(emp, db)
    return {
        "employee": {"id": str(emp.id), "full_name": emp.full_name,
                     "role_code": emp.role.code, "role_name": emp.role.name},
        "company": ({"id": str(comp.id), "name": comp.name, "code": comp.code,
                     # Valyuta kontrakti: klient pul birligini shu yerdan oladi, UI tilidan EMAS.
                     "currency": comp.currency}
                    if comp is not None else None),
        "permissions": sorted(effective_permissions(emp, db)),
        "full_access": emp.role.code in FULL_ACCESS_ROLES,
        "actor_branch": ({"id": str(ab.id), "name": ab.name, "timezone": ab.timezone,
                          "business_date": LP.business_date(db, ab.id).isoformat()}
                         if ab is not None else None),
        "branch_scope": "all" if vb is None else "assigned",
        "branches": [_br(b) for b in branches],
    }


# ══ HISOBNI O'ZI O'CHIRISH (Apple 5.1.1(v), CH-18A) ═════════════════════════

class AccountDeletionIn(BaseModel):
    """⚠️  FAQAT O'Z hisobi uchun. Maqsad xodim `id` si bu DTO'da UMUMAN YO'Q —
    kim o'chirilayotgani TOKENDAN olinadi, so'rovdan emas, shu bois soxta
    so'rov bilan boshqa odamni o'chirib bo'lmaydi."""

    password: str = Field(min_length=1, max_length=200)
    #  Tasodifiy bosishdan himoya: mijoz AYNAN `CONFIRM_WORD` ni yuboradi.
    confirm: str = Field(min_length=1, max_length=40)


@router.get("/account-deletion")
def account_deletion_state(emp: Employee = Depends(get_current_employee),
                           db: Session = Depends(get_db)):
    """O'z hisobini o'chirish mumkinmi; mumkin bo'lmasa — QANDAY yo'l bor.

    Mijoz shu javob bo'yicha ekranni quradi: tugma faolmi, qanday ogohlantirish
    ko'rsatiladi va «oxirgi rahbar» holatida qanday tanlov taklif qilinadi."""
    from app.services import account_deletion as _AD
    st = _AD.self_deletion_state(db, emp)
    return {
        **st,
        "confirm_word": _AD.CONFIRM_WORD,
        #  Parolsiz (PIN'li) xodim parol bilan tasdiqlay olmaydi — u o'chirishni
        #  SO'RAYDI, ega esa bajaradi. Mijoz shu bayroq bo'yicha «o'chirish» yoki
        #  «so'rov yuborish» tugmasini ko'rsatadi.
        "needs_password": bool(emp.password_hash),
        "request": _AD.request_state(db, emp),
    }


@router.post("/account-deletion")
def delete_own_account(data: AccountDeletionIn,
                       request: Request,
                       emp: Employee = Depends(get_current_employee),
                       db: Session = Depends(get_db)):
    """O'z hisobini QAYTARILMAS o'chirish: parol qayta kiritiladi, PII tozalanadi.

    ⚠️  PAROL QAYTA SO'RALADI. Token o'g'irlangan bo'lsa ham hisob o'chirilmasin:
        bu qaytarib bo'lmaydigan amal, shu bois `POST /auth/password` bilan
        AYNI qoida — joriy parol majburiy.

    ⚠️  TEZLIK CHEKLOVI parol yo'li bilan AYNI (`RL.guard`): parolni taxmin
        qilib hisob o'chirishga urinishni ham to'xtatadi.

    ⚠️  BIZNES TARIXI TEGILMAYDI — savdo, kassa va ombor yozuvlari qoladi
        (`services/account_deletion` izohiga qara).
    """
    from app.services import account_deletion as _AD

    ip = _client_ip(request)
    ipk = f"del:{ip}" if ip else f"del:?:{emp.id}"
    RL.guard(db, "ip", ipk, RL.IP_TIER)
    RL.guard(db, "acct", f"del:{emp.id}", RL.ACCT_TIER)

    if data.confirm.strip() != _AD.CONFIRM_WORD:
        raise HTTPException(400, f"Tasdiqlash uchun «{_AD.CONFIRM_WORD}» so'zini kiriting")

    #  ⚠️  PAROLSIZ (faqat PIN'li) xodim bu yo'ldan o'cha olmaydi: tasdiqlash
    #      uchun parol YO'Q. Uning hisobini do'kon egasi o'chiradi — shu holat
    #      javobda AYNIQ aytiladi, jim 401 bermaydi.
    if not emp.password_hash:
        raise HTTPException(
            400, "Bu hisobda parol yo'q — o'chirishni do'kon egasidan so'rang")
    if not verify_password(data.password, emp.password_hash):
        RL.record(db, [("ip", ipk, None), ("acct", f"del:{emp.id}", None)])
        db.commit()
        raise HTTPException(403, "Parol noto'g'ri")

    st = _AD.self_deletion_state(db, emp)
    if st["already_deleted"]:
        #  Takroriy so'rov — IDEMPOTENT: ikkinchi marta hech narsa o'zgarmaydi.
        return {"ok": True, "deleted": True, "repeated": True}
    if not st["can_delete"]:
        #  409: HOLAT ziddiyati (ochiq smena / oxirgi rahbar), shakl xatosi emas.
        raise HTTPException(409, _AD_BLOCK_TEXT.get(
            st["blockers"][0], "Hisobni hozir o'chirib bo'lmaydi"))

    RL.clear(db, [("ip", ipk, None), ("acct", f"del:{emp.id}", None)])
    natija = _AD.anonymize(db, emp)
    from app.services.audit import log as audit_log
    #  Audit izi QOLADI, lekin unda PII YO'Q — faqat qaysi ustunlar tozalangani.
    audit_log(db, emp.id, "delete", "employee_account", emp.id,
              after={"cleared": natija["cleared"], "self": True})
    db.commit()
    return {"ok": True, "deleted": True, "repeated": False}


#: Blok sabablari -> operator ko'radigan jumla. Har biri BAJARA OLADIGAN amalni aytadi.
_AD_BLOCK_TEXT = {
    #  ⚠️  Bu blok 409 ga EMAS, 400 ga tushadi: marshrut parolsiz hisobni
    #      yuqorida, holat tekshiruvidan OLDIN rad etadi. Matn shu bois AYNI
    #      jumlani takrorlaydi — iste'molchi `blockers` ni o'qisa ham, 400
    #      javobini o'qisa ham BIR XIL narsani ko'radi.
    "no_password": "Bu hisobda parol yo'q — o'chirishni do'kon egasidan so'rang",
    "open_shift": "Avval smenani yoping — ochiq smena bilan hisob o'chirilmaydi",
    "sole_manager": "Siz do'kondagi yagona rahbarsiz — avval boshqa xodimni "
                    "administrator qilib tayinlang yoki do'konni yopish uchun "
                    "qo'llab-quvvatlashga murojaat qiling",
    "sole_owner": "Siz yagona Egasiz — avval boshqa Ega tayinlang",
}


# ══ PAROLSIZ XODIM: O'CHIRISHNI SO'RASH (CH-18B) ════════════════════════════

@router.post("/account-deletion/request")
def request_own_deletion(emp: Employee = Depends(get_current_employee),
                         db: Session = Depends(get_db)):
    """PIN'li (parolsiz) xodim o'z hisobini o'chirishni SO'RAYDI.

    ⚠️  PIN O'ZI QAYTARILMAS O'CHIRISHGA YETARLI EMAS (ega qoidasi): PIN qisqa,
        ko'pincha ulashilgan va yonidagi odam ko'rib qolishi mumkin. Shu bois bu
        yo'l HECH NARSANI O'CHIRMAYDI — faqat so'rov qoldiradi, bajarish esa
        EGANING paroli bilan qayta autentifikatsiyasini talab qiladi
        (`POST /employees/{id}/account-deletion`).

    ⚠️  PAROLLI xodim bu yo'ldan foydalanmaydi: u o'zi darhol o'chira oladi.
        Shunda ham so'rov yozish ZARARSIZ, lekin chalg'ituvchi bo'lardi — shu
        bois 400 bilan to'g'ri yo'lga yo'naltiriladi.
    """
    from app.services import account_deletion as _AD

    if emp.password_hash:
        raise HTTPException(
            400, "Sizda parol bor — hisobni o'zingiz darhol o'chira olasiz")
    natija = _AD.request_deletion(db, emp)
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "create", "employee_account_deletion_request", emp.id,
              after={"requested": True})
    db.commit()
    return {"ok": True, **natija, **_AD.request_state(db, emp)}


# ══ DO'KONNI YOPISH — YAGONA EGA UCHUN CHIQISH YO'LI (CH-18B) ═══════════════

class StoreClosureIn(BaseModel):
    """Eganing O'Z paroli + tasdiq so'zi. Ijarachi id'si so'rovda YO'Q — u
    tokendan olinadi, shu bois boshqa do'konni yopib bo'lmaydi.

    ⚠️  `delete_my_account` ALOHIDA va STANDART `False` (CH-18C). Yopish —
        OPERATSION amal; eganing shaxsiy hisobini o'chirish esa BOSHQA, qaytarib
        bo'lmaydigan amal. Ikkisini bitta tugmaga bog'lab jim bajarish
        tasdiqlanmagan xulq bo'lardi, shu bois ega buni AYNIQ so'raydi."""

    password: str = Field(min_length=1, max_length=200)
    confirm: str = Field(min_length=1, max_length=40)
    delete_my_account: bool = False


@router.get("/store-closure")
def store_closure_preview(emp: Employee = Depends(get_current_employee),
                          db: Session = Depends(get_db)):
    """Yopish NIMA QILADI — tasdiqlash ekrani uchun ANIQ oqibatlar.

    ⚠️  NEGA ALOHIDA ENDPOINT. Tasdiqlash ekrani «nima bo'ladi» deb TAXMIN
        qilmasligi kerak: qancha hisob anonimlashtiriladi, qanchasida ism
        QOLADI va qaysi yozuvlar saqlanadi — hammasi SERVERDAN keladi. Aks
        holda mijoz matni server xulqidan ajralib ketardi.
    """
    from app.services import account_deletion as _AD

    if emp.role.code != "ega":
        raise HTTPException(403, "Do'konni faqat Ega yopadi")
    from app.models.auth import Employee as _E
    #  ⚠️  «PII SAQLAYDIGAN» — na «faol», na «deleted_at IS NULL» (CH-18D).
    #      Ilgari bu yerda `deleted_at IS NULL` filtri turardi va izoh
    #      «status=terminated xodim ham sanaladi» deb da'vo qilardi. Da'vo
    #      YARIM TO'G'RI edi: `status` bo'yicha bo'shatilgan xodim chindan
    #      sanalardi, lekin `DELETE /employees/{id}` orqali bo'shatilgan
    #      (`deleted_at` o'rnatilgan, PII si TURGAN) xodim SANALMASDI. Ega
    #      shu sababli bazadagidan KICHIK son ko'rardi — qaytarilmas amal
    #      oldidagi tasdiqlash ekrani uchun qabul qilinmas.
    #
    #      Mezon endi BITTA manbadan: `account_deletion.pii_retained()`.
    pii_li = [e for e in db.query(_E).filter(_E.company_id == emp.company_id).all()
              if _AD.pii_retained(e)]
    sosalgan = {str(it.get("employee_id")) for it in _AD.list_requests(db, emp.company_id)}
    rozi = [e for e in pii_li if str(e.id) in sosalgan]
    return {
        "confirm_word": _AD.CONFIRM_WORD,
        "employees_with_pii": len(pii_li),
        #  O'chirishni O'ZI so'ragan hisoblar — yopishda BAJARILADI.
        "pending_requests": len(rozi),
        #  Qolganlarida ism/telefon SAQLANIB QOLADI — ochiq aytiladi.
        "pii_retained_after_closure": max(0, len(pii_li) - len(rozi)),
        #  Hisob-kitob daftarlari HAR HOLDA saqlanadi.
        "accounting_retained": True,
        "bulk_anonymization_available": False,
    }


@router.post("/store-closure")
def close_own_store(data: StoreClosureIn,
                    request: Request,
                    emp: Employee = Depends(get_current_employee),
                    db: Session = Depends(get_db)):
    """Do'konni OPERATSION yopadi: kirish yopiladi, TARIX SAQLANADI.

    ⚠️  OMMAVIY ANONIMLASHTIRISH BAJARILMAYDI (CH-18C). Faqat ROZILIK bergan
        hisoblar tozalanadi: o'chirishni O'ZI so'ragan xodimlar va — agar ega
        `delete_my_account: true` deb so'ragan bo'lsa — eganing o'zi. Qolgan
        hisoblarda ism/telefon SAQLANIB QOLADI va javob buni `pii_retained_employees`
        bilan OCHIQ aytadi.

    ⚠️  BU TENANT PURGE EMAS. Savdo, kassa, xarid va ombor daftarlari
        TEGILMAYDI; `tools/tenant_purge.py` CHAQIRILMAYDI. Yopish
        `Company.deleted_at` orqali bajariladi — u ALLAQACHON majburlanadigan
        darvoza (`core/deps.py:38-39` -> 401) va vendor yo'li uni aynan
        «yumshoq, tiklanadigan, tarix qoladi» deb ishlatadi.

    ⚠️  NEGA BU YAGONA EGANING CHIQISH YO'LI. Oxirgi rahbar o'z hisobini
        o'chira olmaydi (do'kon boshsiz qolardi). Vorisi bo'lmasa, u ABADIY
        QULFLANIB qolardi — shu bois do'konni yopish ochiq: yopilgandan keyin
        boshqaruv umuman talab qilinmaydi.
        (Ilgari bu izohда «va barcha xodim hisoblari anonimlashtiriladi» deb
        yozilgandi — CH-18C dan keyin bu YOLG'ON: faqat rozilik berganlar
        tozalanadi. Izoh tuzatildi.)

    ⚠️  `delete_my_account` NEGA AYNAN SHU SO'ROVDA. Yopish `Company.deleted_at`
        ni o'rnatadi va autentifikatsiya yopilgan ijarachini RAD etadi
        (`core/deps.py` -> 401) — EGA uchun ham. Ya'ni yopilgandan KEYIN
        ichkariga kirib o'z ma'lumotini o'chirishning autentifikatsiyalangan
        yo'li YO'Q. Shu bois ikkisi BITTA tranzaksiyada bajariladi: ega
        «yopdim, endi o'zimni ham o'chiraman» deb qaytib kela olmaydi, va bu
        qulflanib qolishning yagona qolgan shakli edi (CH-18D/A).
    """
    from app.services import account_deletion as _AD

    ip = _client_ip(request)
    ipk = f"close:{ip}" if ip else f"close:?:{emp.id}"
    RL.guard(db, "ip", ipk, RL.IP_TIER)
    RL.guard(db, "acct", f"close:{emp.id}", RL.ACCT_TIER)

    if emp.role.code != "ega":
        raise HTTPException(403, "Do'konni faqat Ega yopadi")
    if data.confirm.strip() != _AD.CONFIRM_WORD:
        raise HTTPException(400, f"Tasdiqlash uchun «{_AD.CONFIRM_WORD}» so'zini kiriting")
    if not emp.password_hash or not verify_password(data.password, emp.password_hash):
        RL.record(db, [("ip", ipk, None), ("acct", f"close:{emp.id}", None)])
        db.commit()
        raise HTTPException(403, "Parol noto'g'ri")

    RL.clear(db, [("ip", ipk, None), ("acct", f"close:{emp.id}", None)])
    try:
        natija = _AD.close_store(db, emp, delete_self=data.delete_my_account)
    except ValueError:
        raise HTTPException(409, "Do'kon allaqachon yopilgan") from None
    from app.services.audit import log as audit_log
    audit_log(db, emp.id, "delete", "company_closure", emp.company_id,
              after={"anonymized_employees": natija["anonymized_employees"],
                     "pii_retained_employees": natija["pii_retained_employees"],
                     "self_deleted": bool(data.delete_my_account)})
    db.commit()
    return {"ok": True, **natija}
