# -*- coding: utf-8 -*-
"""S1-F9F — rate-limit chelagida XOM MIJOZ IP saqlanmasin (P0).

NEGA BU FAYL BOR (S1-F9E da O'LCHANGAN, taxmin emas)
====================================================
TUZATISHDAN OLDIN ikki jadvalda xom IP ochiq matnda saqlanardi. Quyidagi
qator raqamlari TUZATISHDAN OLDINGI holatga tegishli (HEAD `8d5c4bcd`) —
joriy manbada ular boshqa joyda va boshqa kod:

  1. `public.auth_attempts.bucket`
         `auth.py:291` (oldin)  ipk = f"pin:{ip}"
         `auth.py:362` (oldin)  ipk = f"pw:{ip}"
         `ratelimit.py:179` (oldin)  db.add(AuthAttempt(..., bucket=bucket, ...))
     Qator `company_id=None` bilan yoziladi, ya'ni `tenant_purge` predikati
     (`"company_id" = :cid`) UNKNOWN qaytaradi -> do'kon o'chirilganda ham
     QOLADI va «nol qoldiq» tekshiruvi ham uni KO'RMAYDI.

  2. `public.vendor_auth_attempts.bucket`
         `admin.py:173` (oldin)  bucket_ip = f"ip:{ip}"
         `admin.py:149` (oldin)  db.add(VendorAuthAttempt(bucket=bucket, ...))
     Bu yerda TOZALASH KODI UMUMAN YO'Q (`VendorAuthAttempt` butun `app/` da
     faqat uch joyda: bitta `add`, bitta `count`) — ya'ni qator MUDDATSIZ
     qoladi.

S1-F9A FAQAT TELEFONNI kalitlagan (`account_bucket`), IP ga TEGMAGAN:
`tests/test_auth_bucket_privacy.py` ning ikki P0 testi ham faqat telefon
haqida. S1-F9E ikkalasini `pii` deb TO'G'RI tasnifladi, lekin YOZUV YO'LINI
o'zgartirmadi — reyestr tuzatishi SAQLASH nuqsonini tuzatmaydi.

YECHIM: uyda ALLAQACHON isbotlangan primitiv qayta ishlatiladi —
`ratelimit.account_bucket` / `candidate_bucket` ning HMAC naqshi (tuz
`SECRET_KEY` ustidan SHA-256). Yo'l (`pin` / `pw` / `ip`) HMAC KIRISHIGA
qo'shiladi, ya'ni namespace'lar AJRATILGAN holda qoladi.

XULQ O'ZGARMAYDI — NEGA (o'lchangan):
    `bucket` HECH QAYERDA qayta o'qilmaydi, faqat TENGLIK bilan
    solishtiriladi (joriy manba): `ratelimit.py:201` (`_count`), `:268`
    (`clear`), `admin.py:160` (vendor `count`). Chelak QIYMATINI almashtirish
    ekvivalentlik sinflarini saqlaydi -> chegara, oyna va 429 o'zgarmaydi.

⚠️  NEGA TEST-NET MANZILLARI ISHLATILMAYDI (o'lchangan, taxmin emas).
    `203.0.113.x` / `198.51.100.x` / `192.0.2.x` / `2001:db8::/32` —
    Python `ipaddress` da `is_private` TRUE, shu bois `core/net._is_infrastructure`
    ularni INFRATUZILMA deb rad etadi va `client_ip` BO'SH satr qaytaradi.
    Unda test IP qatlamini emas, ZAXIRA shoxini o'lchab qo'yardi. Shuning
    uchun bu yerda SINTETIK, lekin «global» shakldagi qiymatlar ishlatiladi.
"""
from __future__ import annotations

import ast
import io
import ipaddress
import pathlib
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH = ROOT / "app" / "api" / "v1" / "auth.py"
ADMIN = ROOT / "app" / "api" / "v1" / "admin.py"

_VK = {"X-Vendor-Key": "test-vendor-key"}
_VK_YOLGON = {"X-Vendor-Key": "butunlay-boshqa-vendor-kaliti"}

#  SINTETIK manzillar (yuqoridagi ogohlantirishga qarang).
IP4 = "84.54.70.21"
IP4_B = "84.54.70.22"
IP6 = "2a00:1450:4001:80e::200e"
IP6_B = "2a00:1450:4001:80e::200f"


# ── yordamchilar ──────────────────────────────────────────────────────────
def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _tozala(dimension=None):
    from app.models.security import AuthAttempt
    db = _db()
    try:
        q = db.query(AuthAttempt)
        if dimension:
            q = q.filter(AuthAttempt.dimension == dimension)
        q.delete()
        db.commit()
    finally:
        db.close()


def _tozala_vendor():
    from app.models.vendor import VendorAuthAttempt
    db = _db()
    try:
        db.query(VendorAuthAttempt).delete()
        db.commit()
    finally:
        db.close()


def _chelaklar(dimension=None) -> list[dict]:
    from app.models.security import AuthAttempt
    db = _db()
    try:
        q = db.query(AuthAttempt)
        if dimension:
            q = q.filter(AuthAttempt.dimension == dimension)
        return [{"dimension": r.dimension, "bucket": r.bucket,
                 "company_id": r.company_id} for r in q.all()]
    finally:
        db.close()


def _vendor_chelaklar() -> list[dict]:
    from app.models.vendor import VendorAuthAttempt
    db = _db()
    try:
        return [{"bucket": r.bucket, "reason": r.reason}
                for r in db.query(VendorAuthAttempt).all()]
    finally:
        db.close()


def _xff(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


def _pin_xato(client, ip: str | None = None, employee_id: str | None = None):
    h = _xff(ip) if ip else {}
    return client.post("/api/v1/auth/login",
                       headers=h,
                       json={"employee_id": employee_id or str(uuid.uuid4()),
                             "pin": "9999"})


def _pw_xato(client, ip: str | None = None, phone: str = "+998900000001"):
    h = _xff(ip) if ip else {}
    return client.post("/api/v1/auth/login/password",
                       headers=h,
                       json={"phone": phone, "password": "butunlay-boshqa-parol"})


def _vendor_xato(client, ip: str | None = None):
    """Vendor login — YOLG'ON kalit bilan (urinish qayd etiladi)."""
    h = dict(_VK_YOLGON)
    if ip:
        h.update(_xff(ip))
    return client.post("/api/v1/admin/login", headers=h, json={"otp": None})


def _ip_shakllari(ip: str) -> list[str]:
    """Bitta manzilning BARCHA oqilona yozilish shakllari.

    ⚠️  NEGA FAQAT `ip in matn` YETMAYDI: manzil qisqartirilgan (`::`),
        to'liq yozilgan (`exploded`) yoki PAKETLANGAN hex shaklida ham
        saqlanishi mumkin. Paketlangan hex (IPv4 uchun 8, IPv6 uchun 32
        belgi) 32-hex digest ichida tasodifan uchrash ehtimoli ~1e-8 dan
        kichik, ya'ni yolg'on qizil bermaydi.
    """
    addr = ipaddress.ip_address(ip)
    shakllar = {ip, str(addr), addr.exploded}
    try:
        xom = (socket.inet_aton(ip) if addr.version == 4
               else socket.inet_pton(socket.AF_INET6, ip))
        shakllar.add(xom.hex())
    except OSError:                                        # pragma: no cover
        pass
    return [s for s in shakllar if s]


def _ip_izi_bormi(matn: str, ip: str) -> bool:
    kichik = (matn or "").lower()
    return any(s.lower() in kichik for s in _ip_shakllari(ip))


def _manba_izohsiz(yol: pathlib.Path) -> str:
    """Manba IZOHLARSIZ va DOCSTRINGSIZ.

    ⚠️  NEGA KERAK: bu repoda o'lchangan tuzoq — manba gardlari IZOH va
        DOCSTRING ni ham sanaydi. Tuzatish izohida `f"pin:{ip}"` naqshi
        TUSHUNTIRISH sifatida yozilishi mumkin (va shu faylning yuqorisida
        AYNAN shunday yozilgan), va u gardni JIM yashil/qizil qilardi.
    """
    daraxt = ast.parse(io.open(yol, encoding="utf-8").read())
    for n in ast.walk(daraxt):
        if not isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            continue
        if n.body and isinstance(n.body[0], ast.Expr) and \
                isinstance(n.body[0].value, ast.Constant) and \
                isinstance(n.body[0].value.value, str):
            n.body[0].value.value = "<DOCSTRING>"
    return ast.unparse(daraxt)


def _xom_ip_fsatrlari(yol: pathlib.Path, nomlar: tuple = ()) -> list:
    """XOM `ip` ni f-satrga qo'yadigan TAYINLASHLAR (AST, matn qidiruvi EMAS).

    ⚠️  `nomlar` ATAYLAB E'TIBORGA OLINMAYDI (mustaqil ko'rik topdi): gard
        ilgari FAQAT `ipk` / `bucket_ip` nomlariga qarardi, ya'ni o'zgaruvchi
        qayta nomlansa JIM yashil bo'lardi. Endi faylning HAR QANDAY
        tayinlanishi tekshiriladi.

    ⚠️  QOLGAN CHEKLOV, ochiq aytiladi: bu gard FAQAT f-satr shaklini ko'radi.
        `"pin:" + ip`, `"pin:%s" % ip`, `"pin:{}".format(ip)` yoki yordamchi
        funksiya orqali yozish undan O'TIB KETADI. BIRLAMCHI darvoza — shakldan
        MUSTAQIL ishlaydigan ijro testlari `test_F9F_1..4`: ular bazaga
        HAQIQATAN yozilgan qiymatni o'qiydi. Bu gard faqat IKKILAMCHI to'r va
        regressiyani chaqiruv joyida ko'rsatish uchun.
    """
    daraxt = ast.parse(io.open(yol, encoding="utf-8").read())
    topilgan = []
    for n in ast.walk(daraxt):
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1):
            continue
        t = n.targets[0]
        if not isinstance(t, ast.Name):
            continue
        shoxlar = []
        v = n.value
        if isinstance(v, ast.JoinedStr):
            shoxlar.append(v)
        if isinstance(v, ast.IfExp):
            for sh in (v.body, v.orelse):
                if isinstance(sh, ast.JoinedStr):
                    shoxlar.append(sh)
        for sh in shoxlar:
            for q in sh.values:
                if isinstance(q, ast.FormattedValue) and \
                        isinstance(q.value, ast.Name) and q.value.id == "ip":
                    topilgan.append("%s:%d" % (yol.name, n.lineno))
    return topilgan


# ══ 1) ASOSIY DARVOZA: yangi yozuvlarda XOM IP YO'Q ════════════════════════

def test_F9F_1_PIN_yolida_IPv4_chelakda_XOM_SAQLANMAYDI(client):
    """Kassir PIN login — `ip` chelagida xom IPv4 BO'LMASIN."""
    _tozala()
    r = _pin_xato(client, IP4)
    assert r.status_code == 401, r.text

    qatorlar = _chelaklar()
    assert qatorlar, "urinish UMUMAN qayd etilmadi — proba kuchsiz"
    assert [q for q in qatorlar if q["dimension"] == "ip"], (
        "`ip` o'lchovi yozilmadi — proba kuchsiz: %s" % qatorlar)
    for q in qatorlar:
        assert not _ip_izi_bormi(q["bucket"], IP4), (
            "XOM IP chelakda: dimension=%s company_id=%s bucket=%r. "
            "Bu qator purge'dan omon qoladi (company_id IS NULL). "
            "Yechim: `ratelimit.ip_bucket` (HMAC)." %
            (q["dimension"], q["company_id"], q["bucket"]))


def test_F9F_2_PIN_yolida_IPv6_chelakda_XOM_SAQLANMAYDI(client):
    """IPv6 ham — qisqartirilgan, to'liq va paketlangan shakllarda."""
    _tozala()
    r = _pin_xato(client, IP6)
    assert r.status_code == 401, r.text
    qatorlar = _chelaklar("ip")
    assert qatorlar, "`ip` o'lchovi yozilmadi — proba kuchsiz"
    for q in qatorlar:
        assert not _ip_izi_bormi(q["bucket"], IP6), q["bucket"]


def test_F9F_3_PAROL_yolida_IPv4_va_IPv6_XOM_SAQLANMAYDI(client):
    """Ega/admin parol login — ayni kafolat."""
    for ip in (IP4, IP6):
        _tozala()
        r = _pw_xato(client, ip)
        assert r.status_code == 401, r.text
        qatorlar = _chelaklar("ip")
        assert qatorlar, ("`ip` o'lchovi yozilmadi (%s) — proba kuchsiz" % ip)
        for q in qatorlar:
            assert not _ip_izi_bormi(q["bucket"], ip), (ip, q["bucket"])


def test_F9F_4_VENDOR_yolida_IPv4_va_IPv6_XOM_SAQLANMAYDI(client):
    """`vendor_auth_attempts` — TTL kodi umuman yo'q, ya'ni eng og'ir holat."""
    for ip in (IP4, IP6):
        _tozala_vendor()
        r = _vendor_xato(client, ip)
        assert r.status_code in (401, 403), r.text
        qatorlar = _vendor_chelaklar()
        assert qatorlar, ("vendor urinishi qayd etilmadi (%s) — proba kuchsiz" % ip)
        for q in qatorlar:
            assert not _ip_izi_bormi(q["bucket"], ip), (ip, q["bucket"])


# ══ 2) DETERMINIZM, AJRATISH, NAMESPACE ════════════════════════════════════

def test_F9F_5_AYNI_IP_va_AYNI_YOL_AYNI_chelak_beradi(client):
    """Barqarorlik SHART: kalit har so'rovda o'zgarsa cheklov ishlamasdi."""
    _tozala()
    for _ in range(3):
        assert _pin_xato(client, IP4).status_code == 401
    ip_q = [q["bucket"] for q in _chelaklar("ip")]
    assert len(ip_q) == 3, ip_q
    assert len(set(ip_q)) == 1, ("kalit barqaror emas: %s" % set(ip_q))


def test_F9F_6_BOSHQA_IP_BOSHQA_chelak_beradi(client):
    """Ajratish: aks holda bitta mijozning bloki hammaga tarqalardi."""
    _tozala()
    assert _pin_xato(client, IP4).status_code == 401
    a = {q["bucket"] for q in _chelaklar("ip")}
    _tozala()
    assert _pin_xato(client, IP4_B).status_code == 401
    b = {q["bucket"] for q in _chelaklar("ip")}
    assert a and b and a != b, ("IP ajratilmadi: %s vs %s" % (a, b))

    _tozala()
    assert _pin_xato(client, IP6).status_code == 401
    c = {q["bucket"] for q in _chelaklar("ip")}
    _tozala()
    assert _pin_xato(client, IP6_B).status_code == 401
    d = {q["bucket"] for q in _chelaklar("ip")}
    assert c and d and c != d, ("IPv6 ajratilmadi: %s vs %s" % (c, d))


def test_F9F_7_PIN_PAROL_VENDOR_namespacelari_AJRATILGAN(client):
    """Ayni IP uchun uch yo'l UCH xil chelak bersin.

    ⚠️  NEGA MUHIM: namespace birlashsa bitta yo'ldagi urinishlar
        boshqasining hisoblagichini surardi — ya'ni kassir PIN hujumi
        vendor portalini (yoki teskarisi) bloklab qo'yardi.
    """
    _tozala()
    _tozala_vendor()
    assert _pin_xato(client, IP4).status_code == 401
    pin_q = {q["bucket"] for q in _chelaklar("ip")}
    _tozala()
    assert _pw_xato(client, IP4).status_code == 401
    pw_q = {q["bucket"] for q in _chelaklar("ip")}
    assert _vendor_xato(client, IP4).status_code in (401, 403)
    ven_q = {q["bucket"] for q in _vendor_chelaklar()
             if not q["bucket"].startswith("flow:")}

    assert len(pin_q) == 1 and len(pw_q) == 1 and len(ven_q) == 1, \
        (pin_q, pw_q, ven_q)
    assert len(pin_q | pw_q | ven_q) == 3, (
        "namespace'lar to'qnashdi: pin=%s pw=%s vendor=%s" %
        (pin_q, pw_q, ven_q))


# ══ 3) PRIMITIV: `ip_bucket` ═══════════════════════════════════════════════

def test_F9F_8_PRIMITIV_shakl_tuz_va_domen_ajratish():
    """`ip_bucket` — `account_bucket` bilan AYNI uslub va kafolatlar."""
    from app.core import ratelimit as RL

    b = RL.ip_bucket("pin", IP4)
    #  BARQAROR.
    assert b == RL.ip_bucket("pin", IP4)
    #  SHAKL: o'qiladigan yo'l prefiksi + 32 hex (operator uchun; sir emas).
    assert re.fullmatch(r"pin:[0-9a-f]{32}", b), b
    #  QAYTARIB BO'LMAYDIGAN.
    assert not _ip_izi_bormi(b, IP4), b
    #  DOMEN AJRATISH: yo'l HMAC KIRISHIGA kiradi, faqat prefiks emas.
    assert b.split(":", 1)[1] != RL.ip_bucket("pw", IP4).split(":", 1)[1], (
        "yo'l HMAC kirishiga qo'shilmagan — prefiksni kesib tashlash "
        "namespace'larni birlashtirardi")
    assert RL.ip_bucket("ip", IP4) != b
    #  Boshqa PRIMITIVLAR bilan ham to'qnashmaydi — DIGEST darajasida
    #  solishtiriladi. (Mustaqil ko'rik topdi: to'liq satrlarni solishtirish
    #  TAVTOLOGIYA edi — `account_bucket` prefikssiz qaytaradi, ya'ni
    #  qurilish AYNI bo'lganda ham ular teng chiqmasdi.)
    digest = b.split(":", 1)[1]
    assert digest != RL.account_bucket(IP4), (
        "`ip_bucket` va `account_bucket` AYNI digest berdi — domen ajratish yo'q")
    assert digest != RL.candidate_bucket(None, IP4), (
        "`ip_bucket` va `candidate_bucket` AYNI digest berdi")
    #  TUZSIZ SHA-256 EMAS (IP fazosi IPv4 da 2^32 — lug'at hujumi arzon).
    #  ⚠️  BU TEKSHIRUVNING O'LCHANGAN CHEKLOVI: u FAQAT `sha256(ip)`
    #      shaklini ushlaydi. `sha256("pin|" + ip)` — domen ajratilgan,
    #      lekin TUZSIZ xesh — bu yerdan O'TIB KETADI (mutatsiya bilan
    #      o'lchandi). Shu holatdagi yagona darvoza — pastdagi
    #      `test_F9F_9` (SECRET_KEY bog'lanishi). Ikkisi BIRGALIKDA kerak.
    import hashlib
    xom = hashlib.sha256(IP4.encode()).hexdigest()[:32]
    assert xom not in b, "tuzsiz SHA-256 ishlatilgan — IPv4 fazosi sanoqli"
    #  YOPIQ YO'L TO'PLAMI: noma'lum yo'l JIM yangi namespace ochmasin.
    assert "pin" in RL.IP_PATHS and "pw" in RL.IP_PATHS and "ip" in RL.IP_PATHS
    try:
        RL.ip_bucket("pwd", IP4)
    except ValueError:
        pass
    else:                                                  # pragma: no cover
        raise AssertionError(
            "noma'lum yo'l qabul qilindi — imlo xatosi JIM yangi namespace "
            "ochib, cheklovni nolga tushirardi")
    #  Uzunlik `String(128)` ga sig'adi (eng uzun yo'l bilan ham).
    for yol in sorted(RL.IP_PATHS):
        assert len(RL.ip_bucket(yol, IP6)) <= 128


def test_F9F_9_KALIT_SECRET_KEY_ga_boglangan(monkeypatch):
    """Tuz `SECRET_KEY` dan olinadi — jarayonga xos EMAS (replikalar bir xil)."""
    from app.core import ratelimit as RL
    from app.core.config import settings

    asl = RL.ip_bucket("pin", IP4)
    monkeypatch.setattr(settings, "secret_key", "butunlay-boshqa-kalit-f9f",
                        raising=False)
    boshqa = RL.ip_bucket("pin", IP4)
    assert boshqa != asl, (
        "chelak `SECRET_KEY` ga bog'lanmagan — tuz qattiq kodlangan bo'lishi "
        "mumkin")
    assert re.fullmatch(r"pin:[0-9a-f]{32}", boshqa), boshqa


# ══ 4) XULQ SAQLANADI: chegara, oyna, 429, agregatsiya ═════════════════════

def test_F9F_10_IP_QATLAMI_chegarasi_va_429_xabari_OZGARMAYDI(client):
    """10 xato / 300 s — AVVALGIDEK bloklaydi va AYNI xabar qaytadi."""
    from app.core.ratelimit import ACCT_TIER, IP_TIER

    assert IP_TIER[0] == 10 and IP_TIER[1] == 300, ("qatlam o'zgardi: %s" %
                                                    (IP_TIER,))
    assert IP_TIER[0] < ACCT_TIER[0], (
        "proba noto'g'ri: IP qatlami hisob qatlamidan OLDIN bloklashi kerak")
    _tozala()
    #  Har urinishda BOSHQA xodim ID — hisob qatlami (`pin:{employee_id}`)
    #  aralashmasin, ya'ni AYNAN IP qatlami o'lchanadi.
    for i in range(IP_TIER[0]):
        r = _pin_xato(client, IP4)
        assert r.status_code == 401, (i, r.text)
    r = _pin_xato(client, IP4)
    assert r.status_code == 429, (
        "IP qatlami bloklamadi — cheklov xulqi BUZILDI: %s" % r.status_code)
    assert IP_TIER[2] in r.text, ("429 boshqa qatlamdan keldi: %s" % r.text[:200])


def test_F9F_11_OYNA_SAQLANADI_oynadan_tashqari_qator_sanalmaydi(client):
    """300 s oynasidan TASHQARIDAGI yangi-format qatorlar bloklamasin.

    ⚠️  POZITIV NAZORAT BILAN (mustaqil ko'rik talab qildi): agar ilova
        ishlatadigan chelak test hisoblagan `ip_bucket("pin", IP4)` dan
        FARQ QILSA, birinchi qism JIM yashil bo'lardi (hech narsa
        sanalmagani uchun). Shuning uchun AYNI chelak OYNA ICHIDA
        ekilganda 429 kelishi ham tekshiriladi.
    """
    from app.core import ratelimit as RL
    from app.models.security import AuthAttempt

    def _ek(nechta, yosh_s):
        db = _db()
        try:
            paytda = datetime.now(timezone.utc) - timedelta(seconds=yosh_s)
            for _ in range(nechta):
                db.add(AuthAttempt(dimension="ip", bucket=chelak,
                                   company_id=None, occurred_at=paytda))
            db.commit()
        finally:
            db.close()

    _tozala()
    chelak = RL.ip_bucket("pin", IP4)
    #  (a) OYNADAN TASHQARIDA — bloklamasligi SHART.
    _ek(RL.IP_TIER[0] + 5, RL.IP_TIER[1] + 120)
    r = _pin_xato(client, IP4)
    assert r.status_code == 401, (
        "oynadan tashqaridagi qatorlar sanaldi: %s" % r.status_code)

    #  (b) POZITIV NAZORAT: AYNI chelak OYNA ICHIDA -> 429 kelishi SHART.
    #      Bu test ekkan chelak ilova ishlatadigan chelak ekanini ISBOTLAYDI.
    _tozala()
    _ek(RL.IP_TIER[0], 10)
    r2 = _pin_xato(client, IP4)
    assert r2.status_code == 429, (
        "pozitiv nazorat yiqildi: test ekkan chelak ilova ishlatadigan "
        "chelak EMAS, ya'ni (a) qismi hech narsani isbotlamaydi (%s)"
        % r2.status_code)
    assert RL.IP_TIER[2] in r2.text, r2.text[:160]


def test_F9F_12_VENDOR_chegarasi_va_429_OZGARMAYDI(client):
    """Vendor IP qatlami: 5 xato / 900 s — AVVALGIDEK."""
    import app.api.v1.admin as A

    assert A._VENDOR_IP_TIER == (5, 900), ("vendor qatlami o'zgardi: %s" %
                                           (A._VENDOR_IP_TIER,))
    _tozala_vendor()
    for i in range(A._VENDOR_IP_TIER[0]):
        r = _vendor_xato(client, IP4)
        assert r.status_code in (401, 403), (i, r.text)
    r = _vendor_xato(client, IP4)
    assert r.status_code == 429, (
        "vendor IP qatlami bloklamadi: %s" % r.status_code)
    assert "15 daqiqadan keyin" in r.text, r.text[:200]
    #  BOSHQA IP esa bloklanmagan (ajratish saqlanadi).
    r2 = _vendor_xato(client, IP4_B)
    assert r2.status_code in (401, 403), (
        "boshqa IP ham bloklandi — vendor chelagi ajratilmagan: %s" %
        r2.status_code)


def test_F9F_13_IP_ANIQLANMASA_XAVFSIZ_zaxira(client):
    """Zaxira kalit: XOM xodim UUID si `ip` O'LCHOVIGA tushmasin.

    ⚠️  DOIRA ANIQ (mustaqil ko'rik tuzatdi): bu FAQAT `ip` o'lchovi haqida.
        AYNI so'rov `acct` o'lchoviga `pin:{employee_id}` ni — ya'ni XOM
        xodim UUID sini — HAMON yozadi va u ham `company_id=None` bilan
        tushadi, ya'ni `tenant_purge` dan OMON QOLADI. S1-F9F buni
        O'ZGARTIRMAYDI; quyida u ATAYLAB qadalgan, jim o'zgarmasin.

    ⚠️  GLOBAL BO'LMASLIGI SHART: bitta umumiy zaxira kalit 10 xato bilan
        BUTUN tizimni kassadan uzardi (`_client_ip` izohi).
    """
    e1, e2 = str(uuid.uuid4()), str(uuid.uuid4())
    _tozala()
    #  IP ni ANIQLANMAYDIGAN qilamiz (ichki manzil -> `client_ip` bo'sh satr).
    assert _pin_xato(client, "10.0.0.7", employee_id=e1).status_code == 401
    birinchi = [q["bucket"] for q in _chelaklar("ip")]
    assert birinchi, "zaxira yo'lda `ip` o'lchovi yozilmadi — proba kuchsiz"
    for b in birinchi:
        assert e1 not in b, ("zaxira kalitida XOM xodim UUID si: %r" % b)
        assert e1.replace("-", "") not in b, b

    #  O'ZGARMAGAN HOLAT, ATAYLAB QADALADI: `acct` o'lchovi HAMON xom UUID.
    acct = [q for q in _chelaklar("acct") if e1 in q["bucket"]]
    assert acct, (
        "`acct` chelagi endi xom xodim UUID sini saqlamayapti — bu YAXSHI "
        "o'zgarish, lekin u S1-F9F doirasida EMAS: izohlarni va reyestrdagi "
        "`public.auth_attempts` yozuvini YANGILANG")
    assert all(q["company_id"] is None for q in acct), (
        "egalik semantikasi o'zgardi — S1-F8 D4 qarorini talab qiladi")

    #  DETERMINIZM.
    assert _pin_xato(client, "10.0.0.7", employee_id=e1).status_code == 401
    hammasi = [q["bucket"] for q in _chelaklar("ip")]
    assert len(set(hammasi)) == 1, ("zaxira kalit barqaror emas: %s" %
                                    set(hammasi))

    #  GLOBAL EMAS: boshqa xodim -> boshqa chelak.
    _tozala()
    assert _pin_xato(client, "10.0.0.7", employee_id=e2).status_code == 401
    ikkinchi = {q["bucket"] for q in _chelaklar("ip")}
    assert ikkinchi and ikkinchi != set(birinchi), (
        "zaxira kalit GLOBAL bo'lib qoldi — 10 xato butun tizimni bloklardi: "
        "%s vs %s" % (ikkinchi, set(birinchi)))


def test_F9F_14_IP_QATLAMI_DOKONLAR_BOYLAB_AGREGATSIYA_qiladi(client):
    """Ayni IP, BOSHQA xodim/do'kon -> AYNI `ip` chelagi.

    ⚠️  Bu ATAYLAB shunday (`models/security.py` docstringi): aks holda
        hujumchi har so'rovda boshqa identifikator yuborib, har safar
        yangi bo'sh hisoblagich ochib IP cheklovini CHETLAB O'TARDI.
    """
    from app.core.ratelimit import IP_TIER

    _tozala()
    chelaklar = set()
    for i in range(IP_TIER[0]):
        r = _pin_xato(client, IP4, employee_id=str(uuid.uuid4()))
        assert r.status_code == 401, (i, r.text)
        chelaklar |= {q["bucket"] for q in _chelaklar("ip")}
    assert len(chelaklar) == 1, (
        "ayni IP uchun bir nechta chelak ochildi — cheklov chetlab o'tiladi: "
        "%s" % chelaklar)
    #  Yangi identifikator ham bloklangan.
    r = _pin_xato(client, IP4, employee_id=str(uuid.uuid4()))
    assert r.status_code == 429, (
        "yangi identifikator bilan cheklov chetlab o'tildi: %s" % r.status_code)


# ══ 5) OSHKORLIK: javob, xato va vendor yo'lida IP oqmaydi ═════════════════

def test_F9F_15_JAVOBDA_va_XATODA_IP_OQMAYDI(client):
    """401, 429 va vendor javoblarida IP ham, chelak ham ko'rinmasin."""
    from app.core import ratelimit as RL
    from app.core.ratelimit import IP_TIER

    _tozala()
    _tozala_vendor()
    r = _pin_xato(client, IP4)
    assert r.status_code == 401
    assert not _ip_izi_bormi(r.text, IP4), r.text[:200]
    assert RL.ip_bucket("pin", IP4) not in r.text, "chelak javobda oshkor bo'ldi"

    for _ in range(IP_TIER[0]):
        _pin_xato(client, IP4)
    r429 = _pin_xato(client, IP4)
    assert r429.status_code == 429
    assert not _ip_izi_bormi(r429.text, IP4), r429.text[:200]

    rv = _vendor_xato(client, IP6)
    assert rv.status_code in (401, 403)
    assert not _ip_izi_bormi(rv.text, IP6), rv.text[:200]
    assert RL.ip_bucket("ip", IP6) not in rv.text


# ══ 6) ESKI MA'LUMOT: o'tish davri ANIQ TA'RIFLANADI ══════════════════════

def test_F9F_16_OTISH_DAVRI_qaysi_qatlamlar_nolga_tushishini_OLCHAYDI(
        client, monkeypatch):
    """O'TISH DAVRI CHEKLOVI — yashirilmaydi, UCH QISMDA O'LCHANADI.

    ⚠️  TUZATILGAN DA'VO (mustaqil ko'rik topdi). Bu testning avvalgi
        matni «`acct` va `cand` qatlamlari TEGILMAGAN» der edi va buni
        HECH O'LCHAMASDI. Aslida:
          (a) `ip` o'lchovi eski formatli qatorlarni sanamaydi — deploy'da
              IP hisoblagichi bir marta nolga tushadi;
          (b) AYNI relizdagi S1-F9A parol yo'lining `acct` chelagini
              `f"pw:{phone}"` dan `account_bucket(phone)` ga o'tkazadi,
              ya'ni O'SHA qatlam ham bir marta nolga tushadi;
          (c) `SECRET_KEY` almashtirilsa `_pin_salt`/`_acct_salt`/`_ip_salt`
              AYNI kalitdan olingani uchun `cand` va parol yo'lidagi `acct`
              ham nolga tushadi.
        Faqat kalitga bog'lanmagan chelaklar (`pin:{employee_id}`,
        `chpw:{id}`, `store` dagi `str(company_id)`) omon qoladi.
    """
    from app.core import ratelimit as RL
    from app.core.config import settings
    from app.models.security import AuthAttempt

    def _ek(dimension, chelak, nechta):
        db = _db()
        try:
            hozir = datetime.now(timezone.utc)
            for _ in range(nechta):
                db.add(AuthAttempt(dimension=dimension, bucket=chelak,
                                   company_id=None, occurred_at=hozir))
            db.commit()
        finally:
            db.close()

    #  (a) `ip`: eski format sanalmaydi.
    _tozala()
    _ek("ip", "pin:%s" % IP4, RL.IP_TIER[0] + 5)
    r = _pin_xato(client, IP4)
    assert r.status_code == 401, (
        "eski formatli `ip` qatorlari yangi chelakka sanaldi: %s" % r.status_code)
    assert _chelaklar("acct"), "hisob qatlami yozilmadi — proba kuchsiz"

    #  (b) `acct` (parol yo'li): eski `pw:{phone}` chelagi ham sanalmaydi.
    telefon = "+998900000077"
    _tozala()
    _ek("acct", "pw:%s" % telefon, RL.ACCT_TIER[0] + 5)
    _tozala("ip")
    r2 = _pw_xato(client, IP4_B, phone=telefon)
    assert r2.status_code == 401, (
        "eski `pw:{phone}` chelagi yangi `account_bucket` ga sanaldi — "
        "o'tish davri ta'rifi noto'g'ri: %s" % r2.status_code)
    #  Va YANGI chelak HAQIQATAN ishlatilmoqda (pozitiv nazorat).
    yangi_chelak = RL.account_bucket(telefon)
    assert any(q["bucket"] == yangi_chelak for q in _chelaklar("acct")), (
        "parol yo'li `account_bucket` ni ishlatmadi — proba kuchsiz")

    #  (c) `SECRET_KEY` almashtirish `acct` va `cand` ni HAM nolga tushiradi.
    ip_asl = RL.ip_bucket("pw", IP4)
    acct_asl = RL.account_bucket(telefon)
    cand_asl = RL.candidate_bucket(None, "1234")
    monkeypatch.setattr(settings, "secret_key", "f9f-rotatsiya-kaliti",
                        raising=False)
    assert RL.ip_bucket("pw", IP4) != ip_asl
    assert RL.account_bucket(telefon) != acct_asl, (
        "`acct` kalit rotatsiyasidan ta'sirlanmadi — izohdagi ta'rif noto'g'ri")
    assert RL.candidate_bucket(None, "1234") != cand_asl, (
        "`cand` kalit rotatsiyasidan ta'sirlanmadi — izohdagi ta'rif noto'g'ri")
# ══ 7) MANBA GARDLARI: regressiyani chaqiruv joyida ushlash ════════════════

def test_F9F_17_auth_py_da_XOM_IP_fsatri_YOQ():
    """`ipk = f"...{ip}..."` naqshi MANBADA bo'lmasin (AST, matn emas)."""
    topilgan = _xom_ip_fsatrlari(AUTH, ("ipk",))
    kod = _manba_izohsiz(AUTH)
    #  Vakuumga qarshi: gard HAQIQATAN shu faylni ko'radi.
    assert "login_password" in kod and "login_pin" in kod, (
        "AST ajratgichi `auth.py` ni o'qimadi")
    assert "IP_TIER" in kod, "rate-limit chaqiruvlari topilmadi"
    assert "ip_bucket" in kod, (
        "`auth.py` `ip_bucket` ni ishlatmaydi — tuzatish qo'llanmagan")
    assert topilgan == [], (
        "manbada XOM IP li chelak naqshi bor: %s. IP `ratelimit.ip_bucket` "
        "bilan kalitlanishi SHART." % topilgan)


def test_F9F_18_admin_py_da_XOM_IP_fsatri_YOQ_va_YOLLAR_YOPIQ():
    """Vendor yo'li ham kalitlangan; `ip_bucket` yo'llari YOPIQ to'plamdan."""
    from app.core import ratelimit as RL

    topilgan = _xom_ip_fsatrlari(ADMIN, ("bucket_ip",))
    kod = _manba_izohsiz(ADMIN)
    assert "_vendor_rate_check" in kod, "AST ajratgichi `admin.py` ni o'qimadi"
    assert "ip_bucket" in kod, (
        "`admin.py` `ip_bucket` ni ishlatmaydi — tuzatish qo'llanmagan")
    assert topilgan == [], (
        "`admin.py` da XOM IP li chelak naqshi bor: %s" % topilgan)

    #  Chaqiruv joylaridagi HAR BIR yo'l literali YOPIQ to'plamda bo'lsin —
    #  aks holda imlo xatosi JIM yangi namespace ochib, cheklovni nolga
    #  tushirardi (ValueError faqat ishga tushganda ko'rinardi).
    yollar = []
    for yol in (AUTH, ADMIN):
        daraxt = ast.parse(io.open(yol, encoding="utf-8").read())
        for n in ast.walk(daraxt):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "ip_bucket" and n.args):
                continue
            a0 = n.args[0]
            assert isinstance(a0, ast.Constant) and isinstance(a0.value, str), (
                "%s:%d — `ip_bucket` yo'li LITERAL emas, ya'ni yopiq to'plam "
                "statik tekshirilmaydi" % (yol.name, n.lineno))
            yollar.append(a0.value)
    assert yollar, "`ip_bucket` chaqiruvlari topilmadi — proba kuchsiz"
    noma = sorted(set(yollar) - set(RL.IP_PATHS))
    assert noma == [], ("yopiq to'plamda yo'q yo'llar: %s" % noma)


# ══ 8) ORIGIN/MAIN YANGI YO'LLARI: `del` va `close` (ADMIN-1.0 / P0-A) ═════
#
# ⚠️  NEGA BU BO'LIM QO'SHILDI (o'lchangan, taxmin emas). S1-F9F `8d5c4bcd`
#     ustida yozilgan va o'sha SHA da `auth.py` da FAQAT IKKI IP chelagi bor
#     edi (`pin`, `pw`). `origin/main` (`2457b98a`) hisob o'chirish va do'kon
#     yopish yo'llarini qo'shdi, va ularda IKKI YANGI XOM IP yozuvchisi
#     paydo bo'ldi (tuzatishdan OLDINGI qatorlar):
#
#         auth.py:568   ipk = f"del:{ip}"   if ip else f"del:?:{emp.id}"
#         auth.py:764   ipk = f"close:{ip}" if ip else f"close:?:{emp.id}"
#
#     Ya'ni F9F ni bu tarixga ko'chirish `IP_PATHS` ni KENGAYTIRISHNI talab
#     qiladi. `test_F9F_17` (manba gardi) bu ikki joyni AVTOMATIK ko'radi —
#     u o'zgaruvchi NOMIGA qaramaydi — lekin u faqat f-satr SHAKLINI ushlaydi.
#     Quyidagi testlar esa BAZAGA yozilgan qiymatni o'qib, shakldan MUSTAQIL
#     o'lchaydi; ya'ni birlamchi darvoza ular.
#
# ⚠️  BU YO'LLAR NEGA ALOHIDA NAMESPACE (parol yo'liga qo'shilmaydi): hisob
#     o'chirish va do'kon yopish — QAYTARIB BO'LMAYDIGAN amallar, ularning
#     chegarasi login bilan BIRLASHTIRILSA, oddiy login xatolari o'chirish
#     oynasini yeb qo'yardi (va teskarisi). `origin/main` ularni ataylab
#     ajratgan; F9F ko'chirishi SHU ajratishni SAQLASHI shart.

_PAROL_DC = "Toshkent-Bahor-2026"


def _tasdiq_sozi() -> str:
    """Tasdiq so'zi MANBADAN olinadi (qattiq kodlanmaydi — apostrof tuzog'i)."""
    from app.services.account_deletion import CONFIRM_WORD
    return CONFIRM_WORD


def _ega_tokeni(client):
    """Konsol orqali do'kon ochadi va EGA (`ega`) tokenini qaytaradi."""
    tel = "+99893%07d" % (uuid.uuid4().int % 10000000)
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": "F9F DC", "company_code": "f9fdc" + uuid.uuid4().hex[:8],
        "owner_name": "F9F Ega", "owner_phone": tel,
        "owner_password": _PAROL_DC, "plan": "start"})
    assert r.status_code == 200, r.text
    lr = client.post("/api/v1/auth/login/password",
                     json={"phone": tel, "password": _PAROL_DC})
    assert lr.status_code == 200, lr.text
    h = {"Authorization": "Bearer %s" % lr.json()["access_token"]}
    me = client.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200, me.text
    _tozala()          # login yo'li qoldirgan qatorlarni olib tashlaymiz
    return h, str(me.json()["id"])


def _dc_xato(client, h, yol, ip=None, parol="butunlay-boshqa-parol"):
    """`/account-deletion` yoki `/store-closure` — PAROL NOTO'G'RI (403).

    Parol ataylab noto'g'ri: shunda `RL.record` ishga tushadi va hech narsa
    o'chirilmaydi/yopilmaydi (ya'ni proba IZSIZ).
    """
    hh = dict(h)
    if ip:
        hh.update(_xff(ip))
    return client.post("/api/v1/auth/" + yol, headers=hh,
                       json={"password": parol, "confirm": _tasdiq_sozi()})


def test_F9F_19_HISOB_OCHIRISH_yolida_XOM_IP_SAQLANMAYDI(client):
    """`POST /auth/account-deletion` — IPv4 va IPv6 chelakda XOM qolmasin."""
    h, _ = _ega_tokeni(client)
    for ip in (IP4, IP6):
        _tozala()
        r = _dc_xato(client, h, "account-deletion", ip)
        assert r.status_code == 403, (ip, r.status_code, r.text[:160])
        qatorlar = _chelaklar("ip")
        assert qatorlar, "`ip` o'lchovi yozilmadi — proba kuchsiz (%s)" % ip
        for q in qatorlar:
            assert not _ip_izi_bormi(q["bucket"], ip), (
                "XOM IP hisob-o'chirish chelagida: %r (%s)" % (q["bucket"], ip))


def test_F9F_20_DOKON_YOPISH_yolida_XOM_IP_SAQLANMAYDI(client):
    """`POST /auth/store-closure` — IPv4 va IPv6 chelakda XOM qolmasin."""
    h, _ = _ega_tokeni(client)
    for ip in (IP4, IP6):
        _tozala()
        r = _dc_xato(client, h, "store-closure", ip)
        assert r.status_code == 403, (ip, r.status_code, r.text[:160])
        qatorlar = _chelaklar("ip")
        assert qatorlar, "`ip` o'lchovi yozilmadi — proba kuchsiz (%s)" % ip
        for q in qatorlar:
            assert not _ip_izi_bormi(q["bucket"], ip), (
                "XOM IP do'kon-yopish chelagida: %r (%s)" % (q["bucket"], ip))


def test_F9F_21_del_close_NAMESPACELARI_AJRATILGAN_va_BARQAROR(client):
    """Beshta yo'l AYNI IP uchun BESHTA boshqa chelak berishi SHART."""
    from app.core import ratelimit as RL

    #  (a) PRIMITIV darajasi: yo'llar yopiq to'plamda VA to'qnashmaydi.
    for yol in ("del", "del:?", "close", "close:?"):
        assert yol in RL.IP_PATHS, (
            "`%s` yo'li `IP_PATHS` da YO'Q — `origin/main` ning hisob "
            "o'chirish / do'kon yopish yo'llari qamrab olinmagan" % yol)
    digestlar = {y: RL.ip_bucket(y, IP4).split(":", 1)[1]
                 for y in ("pin", "pw", "ip", "del", "close")}
    assert len(set(digestlar.values())) == 5, (
        "namespace'lar to'qnashdi: %s" % digestlar)
    #  BARQAROR: ayni (yo'l, IP) -> ayni chelak.
    assert RL.ip_bucket("del", IP4) == RL.ip_bucket("del", IP4)
    assert RL.ip_bucket("close", IP6) == RL.ip_bucket("close", IP6)
    #  Boshqa IP -> boshqa chelak.
    assert RL.ip_bucket("del", IP4) != RL.ip_bucket("del", IP4_B)

    #  (b) IJRO darajasi: `del` urinishi `close` hisoblagichini SURMAYDI.
    h, _ = _ega_tokeni(client)
    _tozala()
    assert _dc_xato(client, h, "account-deletion", IP4).status_code == 403
    del_chelaklar = {q["bucket"] for q in _chelaklar("ip")}
    assert _dc_xato(client, h, "store-closure", IP4).status_code == 403
    hammasi = {q["bucket"] for q in _chelaklar("ip")}
    yangi = hammasi - del_chelaklar
    assert yangi, "do'kon-yopish urinishi YANGI chelak yozmadi — namespace birlashgan"
    assert len(hammasi) == 2, (
        "AYNI IP uchun ikki yo'l ikki chelak berishi SHART: %s" % hammasi)


def test_F9F_22_del_close_ZAXIRA_yolida_XOM_UUID_ip_olchoviga_TUSHMAYDI(client):
    """IP aniqlanmasa: `ip` o'lchovida XOM xodim UUID si bo'lmasin.

    ⚠️  DOIRA ANIQ: bu FAQAT `ip` o'lchovi haqida. AYNI so'rov `acct`
        o'lchoviga `del:{emp.id}` / `close:{emp.id}` — ya'ni XOM xodim UUID
        sini — HAMON yozadi (`origin/main` xulqi). Bu ADMIN-1.0 P0-A
        doirasida EMAS va quyida ATAYLAB qadalgan, jim o'zgarmasin.

    ⚠️  GLOBAL BO'LMASLIGI SHART: bitta umumiy zaxira kalit 10 xato bilan
        BUTUN tizimda hisob o'chirishni bloklardi.
    """
    h1, e1 = _ega_tokeni(client)
    h2, e2 = _ega_tokeni(client)
    assert e1 != e2

    for yol, acct_prefiks in (("account-deletion", "del:"),
                              ("store-closure", "close:")):
        _tozala()
        #  `10.0.0.7` — ichki manzil, `core/net.client_ip` BO'SH satr qaytaradi.
        r = _dc_xato(client, h1, yol, "10.0.0.7")
        assert r.status_code == 403, (yol, r.status_code, r.text[:160])
        birinchi = [q["bucket"] for q in _chelaklar("ip")]
        assert birinchi, "zaxira yo'lda `ip` o'lchovi yozilmadi (%s)" % yol
        for b in birinchi:
            assert e1 not in b, ("zaxira kalitida XOM UUID: %r (%s)" % (b, yol))
            assert e1.replace("-", "") not in b, (b, yol)

        #  O'ZGARMAGAN HOLAT, ATAYLAB QADALADI: `acct` HAMON xom UUID.
        acct = [q for q in _chelaklar("acct")
                if q["bucket"].startswith(acct_prefiks)]
        assert acct and any(e1 in q["bucket"] for q in acct), (
            "`acct` chelagi endi xom UUID saqlamayapti — YAXSHI o'zgarish, "
            "lekin P0-A doirasida EMAS: izohlarni va reyestrni YANGILANG (%s)"
            % yol)

        #  DETERMINIZM.
        assert _dc_xato(client, h1, yol, "10.0.0.7").status_code == 403
        assert len({q["bucket"] for q in _chelaklar("ip")}) == 1, (
            "zaxira kalit barqaror emas (%s)" % yol)

        #  GLOBAL EMAS: boshqa xodim -> boshqa chelak.
        _tozala()
        assert _dc_xato(client, h2, yol, "10.0.0.7").status_code == 403
        ikkinchi = {q["bucket"] for q in _chelaklar("ip")}
        assert ikkinchi and ikkinchi != set(birinchi), (
            "zaxira kalit GLOBAL bo'lib qoldi (%s): %s vs %s"
            % (yol, ikkinchi, set(birinchi)))


def test_F9F_23_del_close_CHEGARASI_va_429_XABARI_OZGARMAYDI(client):
    """`IP_TIER` (10 / 300 s) va 429 matni AVVALGIDEK — xulq o'zgarmadi."""
    from app.core.ratelimit import IP_TIER

    assert IP_TIER[0] == 10 and IP_TIER[1] == 300, ("IP_TIER o'zgardi: %s" % (IP_TIER,))

    h, _ = _ega_tokeni(client)
    for yol in ("account-deletion", "store-closure"):
        _tozala()
        for i in range(IP_TIER[0]):
            #  `acct` qatlami (12 / 900 s) IP dan OLDIN bloklamasin.
            _tozala("acct")
            r = _dc_xato(client, h, yol, IP4)
            assert r.status_code == 403, (yol, i, r.status_code, r.text[:120])
        _tozala("acct")
        r = _dc_xato(client, h, yol, IP4)
        assert r.status_code == 429, (
            "IP qatlami bloklamadi — cheklov xulqi BUZILDI (%s): %s"
            % (yol, r.status_code))
        assert IP_TIER[2] in r.text, (
            "429 boshqa qatlamdan keldi (%s): %s" % (yol, r.text[:160]))

        #  POZITIV NAZORAT: boshqa IP HAMON o'tadi (chelak IP ga bog'langan).
        r = _dc_xato(client, h, yol, IP4_B)
        assert r.status_code == 403, (
            "boshqa IP ham bloklandi — chelak IP ga bog'lanmagan (%s): %s"
            % (yol, r.status_code))
