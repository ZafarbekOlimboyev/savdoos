# -*- coding: utf-8 -*-
"""`redact.py` shartnomasi — ko'p tilli sir so'zlari va «redaksiya SIRNI OLIB TASHLAYDI» invarianti.

Bu fayl aynan XAVFLI holatlarni qulflaydi:
  · operator O'Z TILIDA (qirg'izcha / kirill-o'zbekcha) yozgan parol;
  · Word/1C avtomatik tuzatishi qo'ygan EN DASH ajratuvchi;
  · `redact()` yorliqni olib tashlab, QIYMATNI qoldirib, `scan()` ni jimgina «toza» qilishi;
  · masofaviy kirish identifikatori erkin matnda;
  · sir nomli kalit OSTIDAGI ichma-ich qiymat.

⚠️ Eng muhim tekshiruv — `test_invariant_redaksiyadan_keyin_sirning_ozi_yoq`: to'plamda sirning
O'ZI qolmasligi `scan()` ning jim turishidan MUHIMROQ.
"""
from __future__ import annotations

import json

import pytest

from app.services.discovery_1c import redact as R


def notes(text: str) -> dict:
    """Yig'uvchi to'plamidagi erkin matn maydonini taqlid qiladi."""
    return {"discovery": {"notes": [text]}}


# ── Ko'p tilli sir so'zlari ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "сырсөз: qwerty",
    "сыр сөз: qwerty",
    "купуя сөз: qwerty",
    "Сыр: qwerty",
    "Сыр — qwerty",
])
def test_qirgizcha_parol_sozlari_tutiladi(text):
    """`ky` tili loyihada bor — qirg'izcha yozilgan parol ham RAD etilishi shart."""
    assert R.scan(notes(text)), f"qirg'izcha sir so'zi o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "махфий: qwerty",
    "махфий сўз: qwerty",
    "махфий код — 1234",
    "Махфий сўзи = qwerty",
])
def test_kirill_ozbek_maxfiy_sozlari_tutiladi(text):
    """Fayzan tenantining UI/kontenti KIRILL — `махфий` lotin `maxfiy` bilan teng huquqli."""
    assert R.scan(notes(text)), f"kirill-o'zbek sir so'zi o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "Сыр Российский 50% 1кг",
    "Сыр «Голландский» брусок",
    "Сыр-косичка копчёная 100г",
    "Сыр плавленый 90г",
])
def test_ruscha_pishloq_nomi_sir_deb_belgilanmaydi(text):
    """⚠️ Yolg'on ijobiy narxi: ruscha `сыр` = PISHLOQ, tovar nomi to'plamni bloklamasin."""
    assert R.scan(notes(text)) == [], f"tovar nomi sir deb belgilandi: {text!r}"


@pytest.mark.parametrize("text", [
    "парол – 1234",
    "parol – 1234",
    "махфий сўз – 1234",
    "password – 1234",
])
def test_en_dash_ajratuvchi_ham_tutiladi(text):
    """Word va 1C avtomatik tuzatishi `-` ni EN DASH (U+2013) ga aylantiradi."""
    assert R.scan(notes(text)), f"en dash ajratuvchi o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "пароль — qwerty",
    "parol: qwerty",
    "parol=qwerty",
    "parol - qwerty",
    "maxfiy so'z: qwerty",
    "password: qwerty",
])
def test_eski_ajratuvchi_va_shakllar_regressiya(text):
    """Phase 2 da tutilgan shakllar KUCHAYTIRISHDAN keyin ham tutilishi shart."""
    assert R.scan(notes(text)), f"regressiya — ilgari tutilgan shakl o'tib ketdi: {text!r}"


# ── Masofaviy kirish identifikatori ERKIN MATNDA ───────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "AnyDesk: 123 456 789",
    "any desk 123 456 789",
    "TeamViewer ID: 1 234 567 890",
    "подключись через RustDesk 987654321",
    "Ammyy Admin: 12 345 678",
])
def test_masofaviy_kirish_identifikatori_erkin_matnda_tutiladi(text):
    """Ilgari faqat KALIT NOMIDA tutilardi — hisobot matnidagi ID jimgina chiqib ketardi."""
    assert R.scan(notes(text)), f"masofaviy kirish ID o'tib ketdi: {text!r}"


# ── `redact()` HAMMA naqshni qo'llashi kerak ───────────────────────────────────────────────
def test_redaksiya_birinchi_naqshda_toxtamaydi():
    """⚠️ `return rx.sub(...)` faqat BIRINCHI mos naqshni qo'llardi — qolgani qolib ketardi."""
    out = R.redact({"comment": "aloqa: admin@dokon.example.com yoki +996 555 123 456"})
    assert "admin@dokon.example.com" not in out["comment"]
    assert "555 123 456" not in out["comment"]


def test_faqat_yorliq_naqsh_butun_satrni_niqoblaydi():
    """⚠️ Yorliq (`Usr=`) o'chib, PAROL VA LOGIN qolib ketardi — qiymat qayerda tugashini
    bilmaymiz, shu bois butun satr ketadi."""
    out = R.redact({"comment": r"File=C:\bazalar\fayzan;Usr=admin;Pwd=hunter2"})
    assert out["comment"] == R.MASK
    assert "hunter2" not in out["comment"] and "admin" not in out["comment"]


def test_pem_kalit_tanasi_qolmaydi():
    """Sarlavha o'chib, kalit TANASI qolishi — eng og'ir sizish turi."""
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0000\n-----END RSA PRIVATE KEY-----"
    out = R.redact({"comment": pem})
    assert out["comment"] == R.MASK
    assert "MIIEowIBAAKCAQEA0000" not in json.dumps(out)


#: (nom, erkin matn, matndan CHIQMASLIGI kerak bo'lgan sirning O'ZI)
SIRLAR = (
    ("email", "aloqa: admin@dokon.example.com", "admin@dokon.example.com"),
    ("ulanish_pwd", r"File=C:\bazalar\fayzan;Usr=admin;Pwd=hunter2", "hunter2"),
    ("ulanish_dbpwd", "Srvr=10.0.0.5;Ref=trade;DBUser=sa;DBPwd=Str0ngPass", "Str0ngPass"),
    ("url_credentials", "postgres://user:hunter2@host/db", "hunter2"),
    ("pem", "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1111\n-----END KEY-----",
     "MIIEowIBAAKCAQEA1111"),
    ("parol_em_dash", "пароль — qwerty", "qwerty"),
    ("parol_en_dash", "parol – qwerty", "qwerty"),
    ("qirgiz", "сырсөз: qwerty", "qwerty"),
    ("kirill_ozbek", "махфий сўз: qwerty", "qwerty"),
    ("telefon", "qo'ng'iroq: +996 555 123 456", "555 123 456"),
    ("anydesk", "AnyDesk: 123 456 789", "123 456 789"),
)


@pytest.mark.parametrize("nom,matn,sir", SIRLAR, ids=[s[0] for s in SIRLAR])
def test_invariant_redaksiyadan_keyin_scan_jim(nom, matn, sir):
    """Quvurning birinchi sharti: `scan(redact(x)) == []`."""
    assert R.scan(R.redact(notes(matn))) == []


@pytest.mark.parametrize("nom,matn,sir", SIRLAR, ids=[s[0] for s in SIRLAR])
def test_invariant_redaksiyadan_keyin_sirning_ozi_yoq(nom, matn, sir):
    """⚠️ MUHIMROQ shart: sirning O'ZI chiqishda QOLMASLIGI kerak. Ilgari `scan` jim, lekin
    parol/kalit joyida qolar edi — ya'ni «avval redact, keyin tekshir» quvuri sirni
    validatordan O'TKAZIB YUBORARDI."""
    dumped = json.dumps(R.redact(notes(matn)), ensure_ascii=False)
    assert sir not in dumped, f"{nom}: sir redaksiyadan keyin ham joyida"


# ── Ichma-ich sir kalitlari ────────────────────────────────────────────────────────────────
def test_sir_nomli_kalit_ostidagi_ichma_ich_qiymat_tutiladi():
    """⚠️ `scan()` faqat BARG kalitni qarardi: `password.value` sirga o'xshamay qolardi."""
    found = R.scan({"password": {"value": "hunter2"}})
    assert found, "sir nomli kalit ostidagi ichma-ich qiymat topilmadi"
    assert found[0].path == "password.value"


def test_sir_nomli_kalit_ostidagi_royxat_ham_tutiladi():
    assert R.scan({"credentials": [{"host": "srv1", "user": "sa"}]})


def test_oddiy_ichma_ich_qiymat_sir_deb_belgilanmaydi():
    """Yo'lda sir nomi bo'lmasa — ichma-ich qiymat tinch qolsin."""
    assert R.scan({"objects": [{"name": "Справочник.Номенклатура", "rows": 7137}]}) == []


def test_asl_obyekt_ozgarmaydi():
    src = {"discovery": {"notes": ["parol: qwerty"]}}
    R.redact(src)
    assert src["discovery"]["notes"][0] == "parol: qwerty"


# ══════════════════════════════════════════════════════════════════════════════════════════
# NUQSON 1 — ERKIN MATN kalit NOMIDAN kuchsiz skanerlanmasin (ASIMMETRIYA)
# ⚠️ `SECRET_KEY_RE` 14 sir so'zini biladi (`token`, `secret`, `api_key`, `credential`,
#    `private_key`, `connection_string`, `rdp` …), erkin matn skaneri esa faqat PAROL
#    so'zlarini bilardi. Natijada AYNI BIR sir kalit NOMIDA rad etilib, xuddi o'zi erkin
#    matnda (obyekt izohi, `errors`, `notes`, hisobot matni) jimgina tashqariga chiqardi.
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("text", [
    "token: abc123XYZ",
    "Token = abc123XYZ",
    "tokeni: abc123XYZ",
    "api_key=sk-live-12345",
    "api-key: sk-live-12345",
    "apikey: 0123456789abcdef",
    "secret: hunter2hunter2",
    "secrets — hunter2hunter2",
    "credential = admin/hunter2",
    "credentials: sa/Str0ngPass",
    "private_key: MIIEowIBAAKCAQEA",
    "connection_string: Srv1;Ref=trade",
    "conn_str = Srv1;Ref=trade",
    "rdp: 10.0.0.5:3389",
])
def test_erkin_matndagi_sir_sozlari_ham_tutiladi(text):
    """⚠️ Kalit NOMIDA tutiladigan sir, erkin MATNDA ham tutilishi shart (simmetriya)."""
    assert R.scan(notes(text)), f"erkin matndagi sir so'zi o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "Пароль базы 12345",
    "Пароль от базы 12345",
    "parol bazaga 12345",
    "пароль администратора 1234",
])
def test_ajratuvchisiz_parol_va_raqamli_qiymat_tutiladi(text):
    """⚠️ Sir so'zi + BOSHQA so'z(lar) + raqamli qiymat, ajratuvchi belgi YO'Q.

    Bu shakl operator yozuvlarida eng tabiiy: `:` ham, `=` ham, tire ham qo'yilmaydi —
    shu bois ajratuvchiga tayangan naqshlarning HAMMASI bu shakldan o'tib ketardi."""
    assert R.scan(notes(text)), f"ajratuvchisiz parol o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "Токен обмена",
    "ТокенОбмена",
    "РегистрСведений.ТокенОбмена",
    "token exchange register",
    "credential store",
    "secret santa",
    "RDP orqali ulanish",
    "token:",
])
def test_sir_sozi_QIYMATSIZ_kelsa_metadata_deb_qoladi(text):
    """⚠️ MUVOZANAT QARORI: sir so'zi QIYMATSIZ kelsa — bu METADATA NOMI, sir emas.

    1C da `РегистрСведений.ТокенОбмена` kabi nomlar HAR QANDAY konfiguratsiyada bo'lishi
    mumkin va ular sir emas. Shu bois erkin matn naqshi QIYMAT borligini talab qiladi:
    `token: <qiymat>` — sir, yolg'iz `token exchange` — nom. Aks holda skaner deyarli har
    bir eksportni bloklab, o'zining ishonchini yo'qotardi."""
    assert R.scan(notes(text)) == [], f"metadata nomi sir deb belgilandi: {text!r}"


@pytest.mark.parametrize("text", [
    "4780000000017",
    "00537",
    "7137",
    "KOD 000537",
    "qatorlar soni 7137",
    "Сыр Российский 45%",
    "Сыр",
    "Сыр-косичка",
])
def test_sanoq_va_tovar_nomi_sir_deb_belgilanmaydi(text):
    """⚠️ Sanoqlar (barkod, PLU, qator soni) va tovar nomlari HAR BIR eksportda bor —
    ular sir deb belgilansa, darvoza hamma narsani rad etib, o'chirib qo'yilardi."""
    assert R.scan(notes(text)) == [], f"sanoq/tovar nomi sir deb belgilandi: {text!r}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# NUQSON 2 — FAYL YO'LI / UNC / IP:port
# ⚠️ REAL OQIM: yig'uvchi 1C ning `ОписаниеОшибки()` natijasini `errors` ga qo'yadi, SUBD
#    xatolari esa baza faylining YO'LINI va server NOMINI o'z ichiga oladi, `errors` esa
#    yukka kiradi. Ya'ni do'kon mashinasining ichki tuzilmasi hech kim so'ramasdan chiqardi.
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("text", [
    r"Baza: C:\Users\Kassa\1C\baza\1Cv8.1CD",
    r"D:\1C\baza ochilmadi",
    r"Xato: c:\program files\1cv8\bin\1cv8.exe",
])
def test_windows_fayl_yoli_tutiladi(text):
    assert R.scan(notes(text)), f"Windows fayl yo'li o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    r"Tarmoq: \\SRV-KASSA\baza",
    r"\\192.168.1.5\share\1Cv8.1CD ochilmadi",
])
def test_unc_tarmoq_yoli_tutiladi(text):
    assert R.scan(notes(text)), f"UNC yo'li o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "RDP 192.168.1.5:3389",
    "server 10.0.0.5:1541 javob bermadi",
])
def test_ip_va_port_tutiladi(text):
    assert R.scan(notes(text)), f"IP:port o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "8.3.24.1548",
    "1.0.0.1",
    "2.3.5.38",
    "0.1.0-UNVERIFIED",
    "platform_version 8.3.24.1548",
    "configuration_version 1.0.0.1",
    "1C:Enterprise 8.3.24.1548 platformasi",
    "Сервер 1С 8.3.24.1548",
])
def test_versiya_satri_ip_deb_belgilanmaydi_REGRESSIYA(text):
    """⚠️⚠️ ENG MUHIM YOLG'ON IJOBIY DARVOZASI: konfiguratsiya versiyasi SHAKLAN haqiqiy
    IP manzilga o'xshaydi (`1.0.0.1`) va u HAR BIR eksportda bor. Yolg'iz to'rt sonli
    guruhni IP deb hisoblash — butun quvurni bloklash bilan barobar. Shu bois IP faqat
    KONTEKST (bevosita `:port`) bilan tutiladi. Bu darvoza kelajakda buzilmasin."""
    assert R.scan(notes(text)) == [], f"versiya satri sir deb belgilandi: {text!r}"


#: Yangi sinflar uchun «sirning O'ZI qolmaydi» invarianti (yuqoridagi `SIRLAR` bilan bir xil
#: shartnoma; ALOHIDA ro'yxat, chunki yuqoridagisi Phase 2 regressiyasini hujjatlashtiradi).
YANGI_SIRLAR = (
    ("token", "token: abc123XYZ", "abc123XYZ"),
    ("api_key", "api_key=sk-live-12345", "sk-live-12345"),
    ("secret", "secret: hunter2hunter2", "hunter2hunter2"),
    ("credential", "credential = admin/hunter2", "admin/hunter2"),
    ("rdp", "rdp: 10.0.0.5:3389", "10.0.0.5:3389"),
    ("parol_ajratuvchisiz", "Пароль базы 12345", "12345"),
    ("win_path", r"Baza: C:\Users\Kassa\1C\baza\1Cv8.1CD", r"C:\Users\Kassa"),
    ("unc_path", r"Tarmoq: \\SRV-KASSA\baza", r"\\SRV-KASSA"),
    ("ip_port", "RDP 192.168.1.5:3389", "192.168.1.5:3389"),
)


@pytest.mark.parametrize("nom,matn,sir", YANGI_SIRLAR, ids=[s[0] for s in YANGI_SIRLAR])
def test_yangi_sinflar_redaksiyadan_keyin_scan_jim(nom, matn, sir):
    assert R.scan(R.redact(notes(matn))) == []


@pytest.mark.parametrize("nom,matn,sir", YANGI_SIRLAR, ids=[s[0] for s in YANGI_SIRLAR])
def test_yangi_sinflar_redaksiyadan_keyin_sirning_ozi_yoq(nom, matn, sir):
    """⚠️ `scan()` ning jim turishi YETMAYDI — sirning O'ZI chiqishda qolmasligi kerak.

    ⚠️ Matn IKKI marta tekshiriladi: xom satrda ham, JSON'ga yozilgandan keyin ham. Faqat
    `json.dumps` ni qarash YOLG'ON XOTIRJAMLIK berardi: `dumps` teskari chiziqni ikkilantiradi,
    shu bois fayl YO'LI xom holda joyida turgan bo'lsa ham tekshiruv YASHIL ko'rinardi."""
    out = R.redact(notes(matn))
    xom = out["discovery"]["notes"][0]
    assert sir not in xom, f"{nom}: sir xom satrda qoldi"
    assert sir not in json.dumps(out, ensure_ascii=False), f"{nom}: sir JSON'da qoldi"


def test_versiya_satri_redaksiyadan_keyin_ham_ozgarmaydi():
    """⚠️ Redaksiya versiyani YEB QO'YMASIN: yukdagi `platform_version` talqin uchun KERAK,
    u yo'qolsa model qaysi platforma haqida gapirayotganini bilmaydi."""
    src = {"platform_version": "8.3.24.1548", "configuration_version": "1.0.0.1"}
    assert R.redact(src) == src


def test_ip_port_bolagi_ham_qolmaydi_TARTIB_INVARIANTI():
    """⚠️ TARTIB NUQSONI (topilgan va tuzatilgan): so'z naqshi `RDP 192` ni yeb, `ip_with_port`
    ga `.168.1.5:3389` ni QOLDIRARDI. `scan()` jim bo'lardi va «192.168.1.5:3389» ham
    topilmasdi — lekin manzilning katta qismi va PORT to'plamda QOLARDI. Shu bois bu test
    BO'LAKLARNI qidiradi: to'liq satr yo'qolgani sirning ketganini BILDIRMAYDI."""
    out = R.redact(notes("RDP 192.168.1.5:3389"))["discovery"]["notes"][0]
    for bolak in ("192.168", "168.1.5", "3389"):
        assert bolak not in out, f"IP/port bo'lagi qoldi: {bolak!r} — {out!r}"


def test_fayl_yoli_bolagi_ham_qolmaydi():
    """⚠️ Yo'lning BIR BO'LAGI ham do'kon mashinasining tuzilmasini oshkor qiladi."""
    yol = "Baza: C:" + "\\" + "Users" + "\\" + "Kassa" + "\\" + "1C" + "\\" + "1Cv8.1CD"
    out = R.redact(notes(yol))["discovery"]["notes"][0]
    for bolak in ("Users", "Kassa", "1Cv8.1CD"):
        assert bolak not in out, f"yo'l bo'lagi qoldi: {bolak!r} — {out!r}"


def test_unc_yoli_bolagi_ham_qolmaydi():
    """⚠️ UNC yo'lidagi SERVER NOMI — tarmoqqa to'g'ridan-to'g'ri ishora."""
    yol = "Tarmoq: " + "\\\\" + "SRV-KASSA" + "\\" + "baza"
    out = R.redact(notes(yol))["discovery"]["notes"][0]
    for bolak in ("SRV-KASSA", "baza"):
        assert bolak not in out, f"UNC bo'lagi qoldi: {bolak!r} — {out!r}"


def test_redaksiya_idempotent():
    """⚠️ Ikkinchi o'tish natijani O'ZGARTIRMASIN: aks holda quvurdagi har bir qadam matnni
    yana kesib, `scan` va `redact` bir-biriga mos kelmay qolardi."""
    for matn in ("token: abc123XYZ", "RDP 192.168.1.5:3389", "Пароль базы 12345",
                 "aloqa: admin@dokon.example.com yoki +996 555 123 456"):
        bir = R.redact(matn)
        assert R.redact(bir) == bir, f"redaksiya idempotent emas: {matn!r} -> {bir!r}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# NUQSON 3 — POSIX ABSOLYUT YO'L OQIB CHIQADI (HOST SINTAKSISIGA BOG'LIQ DARVOZA)
# ⚠️ ILDIZ SABAB: `VALUE_PATTERNS` da `windows_file_path` (`C:\...`) va `unc_path`
#    (`\\srv\...`) BOR, lekin POSIX absolyut yo'l naqshi YO'Q EDI. Shu bois darvozaning
#    kuchi QURILGAN MASHINAGA bog'lanib qolgan: Windows'da ishlab turgan tekshiruvlar
#    Linux'da (CI, Docker, Railway) jimgina teshik bo'lib qolardi — `_safe()` dan o'tgan
#    validator nuqsoni ichidagi `/tmp/pytest-of-runner/.../umuman-yoq` NIQOBLANMASDAN
#    `agent_status.json` ga tushardi. Yo'l — do'kon/host mashinasining ichki tuzilmasi, va
#    bu yozuv qo'ldan-qo'lga o'tadi.
# ⚠️ SHARTNOMA: absolyut maxfiy fayl yo'li HOST SINTAKSISIDAN QAT'I NAZAR oqmaydi.
# ══════════════════════════════════════════════════════════════════════════════════════════

#: ⚠️ MANFIY NAZORAT uchun: AYNAN eski (tuzatishdan OLDINGI) qamrov — faqat-Windows ikkilik.
ESKI_FAQAT_WINDOWS_NAQSHLAR = ("windows_file_path", "unc_path")

#: Tuzatish qo'shadigan naqshlar. ⚠️ Nom bo'yicha qulflanadi: naqsh jimgina olib
#: tashlansa yoki qayta nomlansa, bu ro'yxat darrov qizil bo'ladi.
YANGI_POSIX_NAQSHLAR = ("posix_temp_path", "posix_file_path")


def _naqsh(nom: str):
    """Nomi bo'yicha qiymat naqshi (topilmasa — darhol yiqiladi, jim o'tmaydi)."""
    for n, rx, _d in R.VALUE_PATTERNS:
        if n == nom:
            return rx
    raise AssertionError(f"naqsh yo'q: {nom!r}")


def test_POSIX_naqshlari_VALUE_PATTERNS_da_BOR():
    """⚠️ Naqshlar nom bilan e'lon qilingan — jim yo'qolishi mumkin emas."""
    nomlar = [n for n, _rx, _d in R.VALUE_PATTERNS]
    for nom in YANGI_POSIX_NAQSHLAR + ESKI_FAQAT_WINDOWS_NAQSHLAR:
        assert nom in nomlar, f"naqsh yo'qoldi: {nom!r}"


def test_MANFIY_NAZORAT_eski_FAQAT_WINDOWS_mantigi_POSIX_yolini_TUTMAYDI():
    """⚠️⚠️ MANFIY NAZORAT — ildiz sababni AYNAN isbotlaydi.

    Eski ikki naqsh (`windows_file_path` + `unc_path`) POSIX yo'lini TUTMAYDI: ya'ni
    tuzatishdan oldin bu holat darvozadan jimgina o'tib ketardi. Yangi naqsh esa TOPADI.
    ⚠️ Tuzatish QAYTARILSA bu test qizil bo'ladi (oxirgi tasdiq yiqiladi)."""
    yol = "/tmp/pytest-of-runner/pytest-1/test_papka_yoq0/umuman-yoq"
    for nom in ESKI_FAQAT_WINDOWS_NAQSHLAR:
        assert _naqsh(nom).search(yol) is None, \
            f"{nom}: eski naqsh POSIX yo'lini tutib qoldi — manfiy nazorat ma'nosiz"
    assert R.scan(notes(yol)), "POSIX absolyut yo'l darvozadan o'tib ketdi"


@pytest.mark.parametrize("text", [
    "/opt/1c/baza/1Cv8.1CD",
    "Baza: /mnt/kassa/baza/1Cv8.1CD",
    "/home/kassir/.1cv8/1C/1cestart/ibases.v8i ochilmadi",
    "Xato: /usr/local/bin/1cv8",
    "/srv/баз/номенклатура.1CD",
    "/opt/1c/baza/",
])
def test_posix_absolyut_fayl_yoli_tutiladi(text):
    """Do'kon/host mashinasining POSIX yo'li ham ichki tuzilmani oshkor qiladi."""
    assert R.scan(notes(text)), f"POSIX fayl yo'li o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    "/tmp/pytest-of-runner/pytest-1/test_papka_yoq0/umuman-yoq",
    "/tmp/binos-run-0001",
    "/var/tmp/1c-export",
    "/var/folders/qz/abc123/T/binos",
    "/private/var/folders/qz/abc123/T/binos",
    "/dev/shm/export.json",
    "/run/user/1000/binos",
    "vaqtinchalik papka: /tmp",
])
def test_vaqtinchalik_papka_yoli_tutiladi(text):
    """⚠️ Vaqtinchalik ildizlar (`/tmp`, `/var/folders`, `/private/var`) YALANG'OCH holda
    ham tutiladi: do'kon ma'lumot yig'ish to'plamida ular HECH QACHON qonuniy mazmun emas
    — ular faqat host yo'li sizib chiqqanda paydo bo'ladi. Shu bois bitta segment YETARLI
    (umumiy POSIX naqshi esa kamida IKKI segment talab qiladi)."""
    assert R.scan(notes(text)), f"vaqtinchalik papka yo'li o'tib ketdi: {text!r}"


@pytest.mark.parametrize("text", [
    # versiya satrlari
    "8.3.24.1548", "1.0.0.1", "0.1.0-UNVERIFIED", "platform_version 8.3.24.1548",
    # sana / vaqt
    "2026-10-02", "2026-10-02T11:39:17Z", "02/10/2026", "01/02/2026 14:30",
    # oddiy matn — qiya chiziq AJRATUVCHI sifatida
    "ha/yo'q", "va/yoki", "kg/dona", "24/7", "obyekt/maydon", "50/50",
    # 1C nomlari
    "Справочник.Номенклатура", "ВЫБРАТЬ КОЛИЧЕСТВО(*)", "РегистрСведений.ЦеныНоменклатуры",
    # nisbiy yo'llar — XAVFSIZ, red etilmaydi
    "tests/conftest.py", "bundle/export.json", "probes/01_row_count.json",
    "../bundle/export.json", "./bundle/export.json", "bundle/probes/01_row_count.json",
    # artefakt nomlari
    "agent_status.json", "run_summary.md", "discovery_report.md",
    # barkod / PLU / sanoqlar
    "4780000000017", "00537", "7137", "KOD 000537",
])
def test_POSIX_naqshi_ODDIY_MATNNI_tutmaydi_YOLGON_IJOBIY_DARVOZASI(text):
    r"""⚠️⚠️ ENG KATTA XAVF — ORTIQCHA REDAKSIYA. Bu modul 3000+ testli to'plamning
    fail-closed darvozasi: oddiy matn red etilsa, HAR BIR eksport rad etilib darvoza
    o'chirishga majbur qilinardi.

    Naqsh ikki qoida bilan himoyalangan: (1) kamida IKKI segment, (2) boshlang'ich `/`
    so'z belgisidan yoki nuqtadan KEYIN kelmaydi (`(?<![\w.])`) — shu bois `kg/dona`,
    `24/7`, `02/10/2026`, `tests/conftest.py` va `../bundle/export.json` TUTILMAYDI."""
    assert R.scan(notes(text)) == [], f"oddiy matn sir deb belgilandi: {text!r}"


@pytest.mark.parametrize("text", ["/api/v1/reports", "GET /api/v1/receipt/profile",
                                  "marshrut /sales/42/receipt"])
def test_API_marshruti_MATN_sifatida_HAM_red_etiladi_ASOSLANGAN_QAROR(text):
    """⚠️ ATAYLAB TANLANGAN QAROR (jim qoldirilmagan): API marshruti HAM red etiladi.

    SABAB: `/api/v1/reports` va `/opt/1c/baza` o'rtasida SINTAKTIK farq YO'Q — ikkisi ham
    «absolyut yo'l». «Xavfsiz ildizlar» ro'yxati (`/api`, `/sales` …) darvozada teshik
    qoldirardi: ildizni `/api` bilan boshlanadigan PAPKA nomi bilan taqlid qilish mumkin,
    va ro'yxatni kim yangilab turishini hech kim kafolatlamaydi.
    NARXI esa NOL (o'lchandi): bu quvur o'z HTTP marshrutlarini yukka HECH QACHON
    yozmaydi — `discovery_1c` va `discovery_agent` da birorta `/api/` satri YO'Q,
    marshrutlar repoda hujjatlashtirilgan, to'plamda emas. Modulning e'lon qilingan
    siyosati shu: yolg'on ijobiy — bir marta qo'lda tekshirish, yolg'on salbiy — mijoz
    yo'li/paroli GitHub'da."""
    assert R.scan(notes(text)), f"API marshruti red etilmadi: {text!r}"


@pytest.mark.parametrize("text", ["marshrut /sales/{id}/receipt",
                                  "GET /sales/{sale_id}/receipt"])
def test_CHEKLOV_OCHIQ_qavsli_marshrut_SHABLONI_tutilmaydi(text):
    """⚠️ CHEKLOV OCHIQ YOZILADI (yashirilmaydi): QAVSLI marshrut SHABLONI tutilmaydi.

    SABAB: `{` va `}` yo'l segmentining belgisi EMAS, shu bois `/sales/{id}/receipt` da
    naqsh uchun faqat BITTA segment qoladi (`/sales`) va ikki-segment qoidasi ishlamaydi.
    Bu QABUL QILINGAN: qavsli o'rin egasi — hujjat matni, mashinada mavjud yo'l EMAS; unda
    na host nomi, na operator papkasi bor. Haqiqiy, QIYMATLANGAN marshrut
    (`/sales/42/receipt`) esa yuqoridagi testda RED ETILADI.
    ⚠️ Yolg'on xotirjamlik bermaslik uchun bu chegara AYNAN shu yerda qulflangan: kimdir
    `{`/`}` ni segment sinfiga qo'shsa, qarorni OCHIQ o'zgartirishga majbur bo'ladi."""
    assert R.scan(notes(text)) == [], f"qavsli shablon kutilmaganda red etildi: {text!r}"


POSIX_SIRLAR = (
    ("posix_baza", "Baza: /opt/1c/baza/1Cv8.1CD", "/opt/1c/baza"),
    ("posix_tmp", "papka topilmadi: '/tmp/pytest-of-runner/pytest-1/t0/umuman-yoq'",
     "umuman-yoq"),
    ("posix_home", "Xato: /home/kassir/.1cv8/1C/1cestart/ibases.v8i", "kassir"),
    ("posix_var_folders", "/var/folders/qz/abc123/T/binos", "abc123"),
)


@pytest.mark.parametrize("nom,matn,sir", POSIX_SIRLAR, ids=[s[0] for s in POSIX_SIRLAR])
def test_posix_yoli_redaksiyadan_keyin_ham_qolmaydi(nom, matn, sir):
    """⚠️ `scan()` ning jim turishi YETMAYDI — yo'lning O'ZI (va BO'LAKLARI) ketishi kerak."""
    out = R.redact(notes(matn))
    xom = out["discovery"]["notes"][0]
    assert sir not in xom, f"{nom}: yo'l bo'lagi xom satrda qoldi — {xom!r}"
    assert sir not in json.dumps(out, ensure_ascii=False), f"{nom}: yo'l JSON'da qoldi"
    assert R.MASK in xom, f"{nom}: yo'l NIQOBLANGAN bo'lishi kerak, jim o'chirilgan emas"
    assert R.scan(out) == [], f"{nom}: redaksiyadan keyin ham skaner gapiradi"


def test_posix_yoli_redaksiyasi_idempotent():
    """⚠️ Ikkinchi o'tish natijani O'ZGARTIRMASIN (quvurda matn bir necha qadamdan o'tadi)."""
    for matn in ("/opt/1c/baza/1Cv8.1CD", "/tmp/binos-run-0001",
                 "papka topilmadi: '/tmp/pytest-of-runner/pytest-1/t0/umuman-yoq'"):
        bir = R.redact(matn)
        assert R.redact(bir) == bir, f"idempotent emas: {matn!r} -> {bir!r}"


def test_nisbiy_yol_va_versiya_redaksiyadan_keyin_ham_OZGARMAYDI():
    """⚠️ Redaksiya qonuniy maydonlarni YEB QO'YMASIN: `bundle_dir` NISBIY nom bo'lishi
    SHART (`status.py` shartnomasi), artefakt nomlari esa hisobotda KERAK."""
    src = {"bundle_dir": "bundle",
           "artifacts": ["bundle/export.json", "agent_status.json",
                         "probes/01_row_count.json"],
           "platform_version": "8.3.24.1548", "finished_at": "2026-10-02T11:39:17Z"}
    assert R.redact(src) == src


# ── OLD_CHIZIQLI_WINDOWS yo'li: `windows_file_path` ikki ajratuvchini ham biladi ─────────
# ⚠️ Mustaqil ko'rik topdi: naqsh ilgari FAQAT teskari chiziqli shaklni bilardi, shu bois
#    `C:/Users/...` unga UMUMAN tushmasdi. POSIX naqshi qo'shilgandan keyin u tasodifan
#    tutilardi, lekin `posix_file_path` deb NOTO'G'RI nomlanardi. Bu yerda ikki narsa
#    qulflanadi: (1) yo'l TUTILADI, (2) YORLIG'I to'g'ri — operator diagnostikasi
#    Windows yo'lini POSIX deb ko'rsatmaydi.
_OLD_CHIZIQLI_WINDOWS = (
    "C:/Users/Developer/binos-agent-build/dist/BinOSDiscoveryAgent.exe",
    "D:/bazalar/dokon/1Cv8.1CD",
    "c:/program files/1cv8/bin/1cv8.exe",
)


@pytest.mark.parametrize("yol", _OLD_CHIZIQLI_WINDOWS)
def test_OLD_CHIZIQLI_WINDOWS_yoli_TUTILADI_va_WINDOWS_deb_nomlanadi(yol):
    topilmalar = R.scan(yol)
    assert topilmalar, f"old-chiziqli Windows yo'li TUTILMADI: {yol}"
    nomlar = [t.pattern for t in topilmalar]
    assert "windows_file_path" in nomlar, (
        "old-chiziqli Windows yo'li WINDOWS naqshi bilan nomlanishi SHART "
        f"(POSIX emas) — hozir: {nomlar}")


def test_OLD_CHIZIQLI_WINDOWS_naqshi_IKKI_ajratuvchini_ham_qabul_qiladi():
    """Tuzatish qaytarilsa (faqat teskari chiziq) shu test QIZIL bo'ladi."""
    naqsh = _naqsh("windows_file_path")
    bs = chr(92)
    assert naqsh.search("C:" + bs + "baza" + bs + "x"), "teskari chiziqli shakl yo'qolgan"
    assert naqsh.search("C:/baza/x"), "old-chiziqli shakl QAMRALMAGAN — tuzatish qaytarilgan"


def test_OLD_CHIZIQLI_WINDOWS_tuzatishi_ORTIQCHA_redaksiya_KELTIRMAYDI():
    """`[a-z]:` dan keyin ajratuvchi SHART — aks holda oddiy ikki nuqtali matn oqardi."""
    for xavfsiz in ("1C:Enterprise 8.3", "izoh: baza", "vaqt 9:30", "Nomenklatura:Kod"):
        assert not R.scan(xavfsiz), f"ORTIQCHA REDAKSIYA: {xavfsiz!r}"


def test_CHEGARA_URL_ning_YOL_bolagi_HAM_red_etiladi_OCHIQ_QAROR():
    """⚠️ CHEGARA, JIM QOLDIRILMAGAN: `https://host/a/b` ning yo'l bo'lagi RED ETILADI.

    Sabab: `//` dan keyin ikki segment qolsa `posix_file_path` moslashadi. Bu AYNI
    ratifikatsiya qilingan qaror bilan bir xil sinf — API marshruti matn sifatida ham
    red etiladi, chunki `/api/v1/reports` va `/opt/1c/baza` o'rtasida sintaktik farq
    YO'Q. Narxi bu quvurda NOL: yukda URL ham, `/api/` satri ham yozilmaydi.
    Bu testning maqsadi — xulqni KO'RINARLI qilish, kelajakda kim «nega URL
    niqoblandi?» deb so'rasa javob kodda tursin.
    """
    topilmalar = R.scan("https://binos.kg/a/b")
    assert [t.pattern for t in topilmalar] == ["posix_file_path"], topilmalar
    # ⚠️ Lekin SXEMA + HOST yolg'iz (yo'l bo'lagi YO'Q) tutilmaydi — ikki segment SHART.
    assert not R.scan("https://binos.kg")
