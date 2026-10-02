# -*- coding: utf-8 -*-
"""Sirlarni topish va olib tashlash — FAIL-CLOSED.

Discovery to'plami do'kon kompyuteridan chiqadi va qo'ldan-qo'lga o'tadi. Shu bois unda
ulanish satri, parol, token yoki masofaviy kirish identifikatori BO'LMASLIGI kerak.

Ikki rejim:
  · `scan()`  — topilganlarni ro'yxatlaydi. Validator shuni chaqiradi va topilsa RAD etadi.
  · `redact()`— topilgan joyni niqob bilan almashtiradi. Yig'uvchi to'plamni YOZISHDAN OLDIN
                shuni ishlatadi; validator esa ishonmaydi va qayta tekshiradi.

Ataylab EHTIYOTKOR: shubhali narsa topilsa RAD etiladi. Yolg'on ijobiy — bir marta qo'lda
tekshirish; yolg'on salbiy — mijozning paroli GitHub'ga ketishi.

⚠️ QAMROV OCHIQ YOZILADI. Sirlardan tashqari do'kon mashinasining ICHKI TUZILMASI ham
olib tashlanadi: Windows fayl yo'li, UNC tarmoq yo'li va `IP:port`. Bu bezak emas — yig'uvchi
1C ning xato tavsifini `errors` ga qo'yadi, SUBD xatolari esa baza faylining to'liq yo'lini va
server nomini o'z ichiga oladi.
⚠️ QAMRALMAGAN, ATAYLAB: YALANG'OCH IP (portsiz va kontekstsiz, masalan `10.0.0.5`).
Sababi — konfiguratsiya versiyasi shaklan AYNAN shunday ko'rinadi (`1.0.0.1`) va u har bir
eksportda bor; kontekstsiz naqsh har bir to'plamni rad etib, darvozani o'chirishga olib
kelardi. Yolg'on kafolat yozishdan ko'ra qamramaslikni OCHIQ aytish yaxshi.

⚠️ `redact()` ning ASOSIY majburiyati — SIRNING O'ZINI olib tashlash, `scan()` ni jim
qilish EMAS. Bu ikkisi bir xil narsa emas: yorliqni (`Pwd=`) o'chirib qiymatni qoldirish
`scan()` ni «toza» qiladi, lekin parolni to'plamda qoldiradi. Shu bois pastda naqshlar ikki
sinfga bo'lingan: QIYMATNI QAMRAYDIGAN va FAQAT-YORLIQ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MASK = "[REDACTED]"

#: Kalit nomi shunga o'xshasa — qiymati HECH QACHON chiqmaydi (qiymatiga qaralmaydi).
SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|parol|secret|token|api[_-]?key|apikey|credential|"
    r"private[_-]?key|connection[_-]?string|conn[_-]?str|anydesk|teamviewer|rdp)"
)

#: Yorliq va qiymat orasidagi ajratuvchilar.
#: ⚠️ EN DASH (U+2013) ATAYLAB bor: Word va 1C avtomatik tuzatishi `парол - 1234` dagi oddiy
#:    tireni aynan `–` ga aylantiradi, natijada `парол – 1234` uchala darvozadan jimgina
#:    o'tib ketardi. EM DASH (U+2014) va oddiy tire ham qamrab olingan.
#: ⚠️ Tire belgilari naqshlarda ANIQ \uXXXX bilan yozilgan: em dash va en dash ni
#:    ko'z bilan farqlash mumkin emas, aynan shu tufayli EN DASH yetishmayotgani uzoq vaqt
#:    sezilmagan.
_SEP = r"[:=\u2014\u2013-]"

#: «Parol» ma'nosini beradigan yorliqlar — TO'RT TILDA.
#: ⚠️ NEGA ko'p tilli: ilova to'rt tilda ishlaydi, ba'zi ijarachilarning UI va kontenti esa
#:    KIRILL. Operator O'Z TILIDA yozgan parol aks holda jimgina tashqariga chiqadi — bu
#:    Phase 2 da tuzatilgan lotin `parol` teshigining boshqa alifbodagi aynan o'zi.
_SECRET_WORD = (
    r"парол\w*"                                            # ruscha/kirill: пароль, паролдон
    r"|parol\w*"                                           # lotin-o'zbek: parol, parolim
    r"|password|passwd|pwd"                                # inglizcha
    r"|махфий\w*(?:\s+(?:сўз\w*|соз\w*|суз\w*|код\w*))?"   # kirill-o'zbek: махфий (сўз|код)
    r"|maxfiy\w*(?:\s+(?:so\W?z\w*|kod\w*))?"              # lotin-o'zbek: maxfiy so'z|kod
    r"|сырсөз\w*"                                          # qirg'izcha: сырсөз
    r"|сыр\s+сөз\w*"                                       # qirg'izcha: сыр сөз
    r"|купуя\s+сөз\w*"                                     # qirg'izcha: купуя сөз
)

#: `SECRET_KEY_RE` biladigan QOLGAN sir so'zlari — ERKIN MATN uchun.
#: ⚠️ NEGA KERAK: ilgari kalit NOMI 14 so'zni bilardi, erkin matn esa faqat parol so'zlarini.
#:    Ya'ni AYNI BIR sir `{"token": "..."}` shaklida RAD etilib, `"izoh: token: ..."` shaklida
#:    jimgina o'tib ketardi. Bu asimmetriya — nuqsonning o'zi: yig'uvchi 1C xatolarini,
#:    operator izohlarini va hisobot matnini erkin MATN maydonlariga qo'yadi.
#: ⚠️ `anydesk`/`teamviewer` bu ro'yxatda YO'Q: ular `remote_access_id` da QIYMATSIZ ham
#:    tutiladi (masofaviy kirish dasturining nomi o'zi bilan xavf haqida gapiradi).
_SECRET_KEY_WORD = (
    r"token\w*"                        # token, tokeni, token_obmena
    r"|secret\w*"                      # secret, secrets
    r"|api[_\-\s]?key\w*"              # api_key, api-key, api key
    r"|apikey\w*"
    r"|credential\w*"                  # credential, credentials
    r"|private[_\-\s]?key\w*"
    r"|connection[_\-\s]?string\w*"
    r"|conn[_\-]?str\w*"
    r"|rdp"                            # masofaviy ish stoli
)

#: QAT'IY ajratuvchi: `:`/`=` yoki PROBEL BILAN AJRATILGAN tire.
#: ⚠️ NEGA `_SEP` dan qattiqroq: parol so'zlari uchun ajratuvchisiz tire (`parol-1234`) ham
#:    tutiladi, chunki `parol` so'zi matnda deyarli har doim SIRNI anglatadi. `token`/`rdp`
#:    kabi umumiy so'zlar esa QO'SHMA NOMLAR ichida uchraydi (`token-exchange`,
#:    `RDP-ulanish`) — ajratuvchisiz tireni sanasak, har bir shunday nom yolg'on ijobiy
#:    berib, darvozaning ishonchini yo'qotardi.
_STRICT_SEP = r"(?:\s*[:=]\s*|\s+[\u2014\u2013-]\s+)"

#: Ajratuvchi YO'Q shakl: sir so'zi + 0–3 ta oddiy so'z + RAQAMLI qiymat.
#: ⚠️ NEGA ALOHIDA: `Пароль базы 12345` da hech qanday ajratuvchi yo'q — operator shunchaki
#:    gap yozadi. Ajratuvchiga tayangan naqshlarning HAMMASI bu shakldan o'tib ketardi.
#: ⚠️ CHEKLOVLAR ataylab: (1) qiymat kamida UCH raqamli, (2) orada eng ko'pi bilan uch so'z,
#:    (3) oraliq so'zlarda raqam ham, ajratuvchi ham bo'lmaydi. Shunday qilinmasa naqsh
#:    butun gapdan o'tib, matnning oxiridagi tasodifiy sanoqni ham «parol» deb belgilardi.
_NO_SEP_NUMERIC_VALUE = r"(?:\s+[^\s\d:=]+){0,3}\s+\d{3,}\b"

#: Qiymat naqshlari. Har biri: (nom, regex, izoh).
VALUE_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    # 1C ulanish satri bo'laklari — `Usr=`/`Pwd=` eng xavflisi, lekin `File=`/`Srvr=` ham
    # do'kon mashinasining ichki tuzilmasini oshkor qiladi.
    ("1c_connection_string", re.compile(r"(?i)\b(File|Srvr|Ref|Usr|Pwd|DBUser|DBPwd)\s*="),
     "1C ulanish satri bo'lagi"),
    # `scheme://user:password@host`
    ("url_credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"),
     "URL ichidagi login:parol"),
    ("email", re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b"),
     "e-mail manzili"),
    # Xalqaro telefon: `+` va 9–15 raqam (orasida probel/tire/qavs bo'lishi mumkin).
    # Tovar nomidagi oddiy raqam bunga tushmaydi — `+` va raqam soni SHART.
    ("phone", re.compile(r"\+\d(?:[\s\-()]*\d){8,14}"), "telefon raqami"),
    # PEM kalit bloklari.
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "shaxsiy kalit bloki"),
    # Masofaviy kirish dasturlari ERKIN MATNDA: `AnyDesk: 123 456 789`, `TeamViewer ID ...`.
    # ⚠️ Ilgari bu faqat KALIT NOMIDA (`SECRET_KEY_RE`) tutilardi, ya'ni hisobot matnidagi
    #    yoki operator izohidagi ID hech kimga ko'rinmasdan to'plam bilan ketardi. Masofaviy
    #    kirish ID si — do'kon kompyuteriga to'g'ridan-to'g'ri yo'l.
    ("remote_access_id",
     re.compile(r"(?i)\b(any\s?desk|team\s?viewer|rust\s?desk|ammyy|radmin|радмин|"
                r"энидеск|тимвьювер)\b"),
     "masofaviy kirish identifikatori"),
    # ── Do'kon mashinasining ichki tuzilmasi: fayl yo'li, tarmoq yo'li, IP va port ─────────
    # ⚠️ REAL OQIM: yig'uvchi 1C ning xato tavsifini `errors` ga qo'yadi, SUBD xatolari esa
    #    baza faylining TO'LIQ YO'LINI va server NOMINI o'z ichiga oladi, `errors` esa yukka
    #    kiradi. Ya'ni yo'llar hech kim so'ramasdan to'plam bilan tashqariga chiqardi.
    ("windows_file_path", re.compile(r"(?i)\b[a-z]:\\[^\s\"';,]*"),
     "mahalliy fayl yo'li"),
    ("unc_path", re.compile(r"\\\\[\w.\-]+\\[^\s\"';,]*"),
     "tarmoq (UNC) yo'li"),
    # ⚠️⚠️ IP FAQAT PORT BILAN tutiladi. YOLG'IZ to'rt sonli guruhni IP deb hisoblash MUMKIN
    #    EMAS: konfiguratsiya versiyasi AYNAN shunday ko'rinadi (`1.0.0.1`) va versiya HAR BIR
    #    eksportda bor. Kontekstsiz naqsh har bir to'plamni rad etib, darvozani foydasiz
    #    qilardi; port esa kontekstni bir ma'noli qiladi — versiyadan keyin `:1541` kelmaydi.
    #    Port oldida PROBEL BO'LMASLIGI ham shart: aks holda `versiya 1.0.0.1: 2026` shakli
    #    yolg'on ijobiy berardi. Yalang'och IP (portsiz, kontekstsiz) ATAYLAB QAMRALMAGAN —
    #    uni konfiguratsiya versiyasidan ishonchli ajratib bo'lmaydi.
    ("ip_with_port", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}\b"),
     "IP manzil va port"),
    # ⚠️ TARTIB YUKLI: struktura naqshlari (yo'l, IP:port) SO'Z naqshlaridan OLDIN
    #    turadi. `_redact_text` naqshlarni AYNAN shu navbatda qo'llaydi, so'z naqshi esa
    #    o'z qiymatini `\S+` yoki raqam bilan yutadi: `RDP 192.168.1.5:3389` da
    #    ajratuvchisiz naqsh `RDP 192` ni olib, `ip_with_port` ga `.168.1.5:3389` ni
    #    QOLDIRARDI — manzilning katta qismi va PORT to'plamda qolardi. Struktura avval
    #    niqoblansa, so'z naqshi allaqachon niqoblangan matnni oladi va zarar yo'q.
    # `password: ...` / `пароль — ...` / `сырсөз: ...` / `махфий сўз – ...` ko'rinishidagi
    # erkin matn (yuqoridagi `_SECRET_WORD` ga qarang).
    ("inline_password", re.compile(rf"(?i)\b(?:{_SECRET_WORD})\b\s*{_SEP}\s*\S+"),
     "matn ichidagi parol"),
    # Yolg'iz qirg'izcha `сыр` («sir») — ALOHIDA, QATTIQROQ naqsh.
    # ⚠️ QAROR: ruscha `сыр` = PISHLOQ, tovar nomida «Сыр Российский», «Сыр-косичка» bo'lishi
    #    MUMKIN. Shu bois yolg'iz `сыр` ni ajratuvchisiz TUTMAYMIZ va oddiy tirega ham
    #    ishonmaymiz: faqat `сыр:` / `сыр=` yoki PROBEL BILAN AJRATILGAN tire (`сыр — 1234`)
    #    shaklida tutamiz. Shunda «Сыр-косичка» va «Сыр Российский» tinch o'tadi, ammo narx
    #    ro'yxatidagi «Сыр — 120» yolg'on ijobiy berishi mumkin — bu ataylab tanlangan
    #    narx: yolg'on ijobiy bir marta qo'lda tekshiriladi, yolg'on salbiy parolni chiqaradi.
    ("inline_password_ky_short",
     re.compile(r"(?i)\bсыр(?:\s*[:=]|\s+[\u2014\u2013-]\s+)\s*\S+"),
     "matn ichidagi parol (qirg'izcha «сыр»)"),
    # `token: ...` / `secret — ...` / `rdp: ...` va `api[_-]key` shakllari — ERKIN MATNDA.
    # ⚠️ QIYMAT BORLIGI SHART (`\S+`). QAROR: sir so'zi qiymatsiz kelsa — bu METADATA NOMI
    #    (`РегистрСведений.ТокенОбмена`, `token exchange register`), sir EMAS. 1C
    #    konfiguratsiyalarida bunday nomlar ko'p va ular deyarli har bir eksportda uchraydi;
    #    ularni sir deb sanash butun quvurni bloklab, darvozani o'chirishga olib kelardi. Sir
    #    esa QIYMATI bilan xavfli: qiymatsiz nom hech kimga kirish bermaydi.
    ("inline_secret_key_value",
     re.compile(rf"(?i)\b(?:{_SECRET_KEY_WORD})\b{_STRICT_SEP}\S+"),
     "matn ichidagi sir (kalit so'zi va qiymati)"),
    # `Пароль базы 12345` — ajratuvchi YO'Q, qiymat RAQAMLI.
    # ⚠️ Parol so'zlari ham, umumiy sir so'zlari ham qamraladi: shakl ikkisida bir xil xavfli.
    ("inline_secret_no_sep_numeric",
     re.compile(rf"(?i)\b(?:{_SECRET_WORD}|{_SECRET_KEY_WORD})\b{_NO_SEP_NUMERIC_VALUE}"),
     "matn ichidagi sir (ajratuvchisiz, raqamli qiymat)"),
)

#: ⚠️ FAQAT-YORLIQ sinfi: bu naqshlar sirning YORLIG'INI tutadi, QIYMATINI emas —
#: `Pwd=hunter2`, PEM kalit tanasi, probel bilan bo'lingan AnyDesk ID. Qiymat qayerda
#: tugashini bilmaymiz, shu bois bunday satr BUTUNLAY `MASK` bilan almashtiriladi.
#: Ilgari `rx.sub` faqat yorliqni o'chirib qiymatni joyida qoldirardi
#: (`Usr=admin;Pwd=hunter2` → `[REDACTED]admin;[REDACTED]hunter2`), `scan()` esa yorliq
#: yo'qolgani uchun «toza» deb aytardi — ya'ni «avval redact, keyin tekshir» quvuri sirni
#: OLIB TASHLAMASDAN validatordan o'tkazib yuborardi.
LABEL_ONLY_PATTERNS = frozenset({"1c_connection_string", "private_key_block",
                                 "remote_access_id"})


@dataclass(frozen=True)
class Finding:
    path: str
    pattern: str
    detail: str

    def __str__(self) -> str:  # xato matnida qiymatning O'ZI ko'rsatilmaydi
        return f"{self.path}: {self.detail} ({self.pattern})"


def _walk(node, path: str):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def _secret_path_segment(path: str) -> str | None:
    """Yo'lning sir nomiga o'xshaydigan BIRINCHI bo'lagi (bo'lmasa `None`).

    ⚠️ Ilgari faqat BARG kalit qaralardi, shu bois `{"password": {"value": "hunter2"}}`
    to'plamdan jimgina o'tib ketardi: sir nomi OTA kalitda turadi. Sir nomli kalit ostidagi
    HAMMA narsa — lug'at, ro'yxat, ichma-ich qiymat — shubhali.
    """
    for seg in path.split("."):
        seg = seg.split("[", 1)[0]
        if seg and SECRET_KEY_RE.search(seg):
            return seg
    return None


def scan(data) -> list[Finding]:
    """To'plamdagi (yoki uning bir qismidagi) barcha shubhali joylar."""
    out: list[Finding] = []
    for path, value in _walk(data, ""):
        seg = _secret_path_segment(path)
        if seg and value not in (None, "", MASK):
            out.append(Finding(path, "secret_key_name", f"kalit nomi sirga o'xshaydi ({seg!r})"))
            continue
        if not isinstance(value, str) or value == MASK:
            continue
        for name, rx, detail in VALUE_PATTERNS:
            if rx.search(value):
                out.append(Finding(path, name, detail))
                break
    return out


def _redact_text(text: str) -> str:
    """Bitta satrdan sirlarni olib tashlash.

    ⚠️ Ikki qoida: (1) faqat-yorliq naqsh mos kelsa — BUTUN satr ketadi; (2) qolgan naqshlar
    HAMMASI qo'llanadi. Ilgari birinchi mos naqshdan keyin darrov qaytilardi, shu bois
    `'Srvr=srv1 · aloqa: admin@dokon.example.com'` da e-mail joyida qolardi.
    """
    for name, rx, _detail in VALUE_PATTERNS:
        if name in LABEL_ONLY_PATTERNS and rx.search(text):
            return MASK
    out = text
    for name, rx, _detail in VALUE_PATTERNS:
        if name not in LABEL_ONLY_PATTERNS:
            out = rx.sub(MASK, out)
    return out


def redact(data):
    """Nusxasini qaytaradi: shubhali qiymatlar niqoblangan. Asl obyekt o'zgarmaydi."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if SECRET_KEY_RE.search(k):
                out[k] = MASK if v not in (None, "") else v
            else:
                out[k] = redact(v)
        return out
    if isinstance(data, list):
        return [redact(v) for v in data]
    if isinstance(data, str) and data != MASK:
        return _redact_text(data)
    return data
