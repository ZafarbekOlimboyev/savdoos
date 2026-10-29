# -*- coding: utf-8 -*-
"""S1-F9A — rate-limit chelagida XOM TELEFON saqlanmasin (P0).

NEGA BU FAYL BOR (S1-F8 da o'lchangan, taxmin emas)
===================================================
`POST /api/v1/auth/login/password` muvaffaqiyatsiz urinishda ikki chelak yozadi:

    RL.record(db, [("ip", ipk, None), ("acct", f"pw:{phone}", None)])

Ikkala yozuvda ham `company_id=None`. Oqibatlari O'LCHANGAN:

  1. `acct` chelagi — IJARACHI EGASINING telefon raqami OCHIQ MATNDA
     (`norm_phone` dan keyin, xesh EMAS). Telefon `privacy.html:26` da
     «Hisob ma'lumotlari» deb ANIQ tan olingan shaxsiy ma'lumot.
  2. `company_id IS NULL` bo'lgani uchun `tenant_purge` ning predikati
     (`"company_id" = :cid`) UNKNOWN qaytaradi -> qator do'kon o'chirilganda
     ham QOLADI, va «nol qoldiq» tekshiruvi ham uni KO'RMAYDI (u AYNI
     predikatni qayta ishlatadi) -> purge «toza» deb hisobot beradi.
  3. `models/security.py` docstringi `company_id IS NULL` qatorlarni FAQAT
     «IP qatlami» deb ta'riflaydi va «bu qator biror do'konning ma'lumoti
     EMAS, shuning uchun purge uni o'chirmaydi — va bu to'g'ri» deydi.
     `acct` o'lchovi u yerda UMUMAN sanalmagan — ya'ni purge siyosatining
     YOZMA ASOSI shu o'lchov uchun YOLG'ON.
  4. IP aniqlanmaganda ZAXIRA kalit ham telefonga bog'lanadi:
     `ipk = f"pw:{ip}" if ip else f"pw:?:{phone or '-'}"` — ya'ni telefon
     `ip` o'lchoviga ham tushadi.

YECHIM: uyda ALLAQACHON bor xavfsiz primitiv qayta ishlatiladi —
`ratelimit.candidate_bucket` ning HMAC naqshi (`_pin_salt` = SHA-256 ustidan
`SECRET_KEY`). Telefon o'rniga BARQAROR, QAYTARIB BO'LMAYDIGAN kalitli
identifikator yoziladi. Tuzsiz SHA-256 ISHLATILMAYDI (qisqa fazo —
lug'at hujumi bir soniyada qaytaradi).

CHEKLOV (halol): bu tuzatish FAQAT yangi yozuvlarni qamraydi. Bazadagi ESKI
xom chelaklar `_prune` orqali `_MAX_WINDOW` (900 s) ichida o'z-o'zidan
tugaydi — ammo `_prune` DANGASA (faqat login yo'li chaqirilganda). Qarang:
hisobotdagi «Tarixiy ma'lumot tozalash» bo'limi.
"""
from __future__ import annotations

import io
import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH = ROOT / "app" / "api" / "v1" / "auth.py"

_VK = {"X-Vendor-Key": "test-vendor-key"}
PAROL = "Toshkent-Bahor-2026"


# ── yordamchilar ──────────────────────────────────────────────────────────
def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _tenant(client):
    """Ega + parol bilan do'kon ochadi; telefon SINTETIK."""
    phone = f"+99894{uuid.uuid4().int % 10000000:07d}"
    code = f"f9a{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": "F9A QA", "company_code": code, "owner_name": "F9A Ega",
        "owner_phone": phone, "owner_password": PAROL, "plan": "start"})
    assert r.status_code == 200, r.text
    return {"company_id": r.json()["company_id"], "phone": phone, "code": code}


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


def _xato_login(client, phone, parol="butunlay-boshqa-parol"):
    return client.post("/api/v1/auth/login/password",
                       json={"phone": phone, "password": parol})


def _raqamlar(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _telefon_izi_bormi(matn: str, phone: str) -> bool:
    """Telefon raqami matnda HAR QANDAY shaklda ko'rinadimi."""
    raqam = _raqamlar(phone)
    return (phone in matn) or (raqam in matn) or (raqam[-7:] in matn)


def _manba_izohsiz() -> str:
    """`auth.py` manbasi IZOHLARSIZ.

    ⚠️  NEGA KERAK: bu repoda o'lchangan tuzoq — manba gardlari IZOH va
        DOCSTRING ni ham sanaydi. Tuzatish izohida `pw:{phone}` naqshi
        tushuntirish sifatida yozilishi mumkin, va u gardni JIM yashil
        qilardi.
    """
    import ast
    src = io.open(AUTH, encoding="utf-8").read()
    daraxt = ast.parse(src)
    #  Docstringlarni placeholder bilan almashtiramiz.
    for n in ast.walk(daraxt):
        if not isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            continue
        if n.body and isinstance(n.body[0], ast.Expr) and \
                isinstance(n.body[0].value, ast.Constant) and \
                isinstance(n.body[0].value.value, str):
            n.body[0].value.value = "<DOCSTRING>"
    #  `ast.unparse` izohlarni UMUMAN tashlaydi — ayni kerakli xossa.
    return ast.unparse(daraxt)


# ══ 1) ASOSIY DARVOZA: egasiz `acct` chelagida telefon YO'Q ════════════════

def test_P0_1_EGASIZ_acct_chelakda_XOM_TELEFON_YOQ(client):
    """Muvaffaqiyatsiz login egasiz chelakka telefon YOZMASIN.

    Bu qator `company_id IS NULL` bilan yoziladi, ya'ni `tenant_purge` dan
    OMON QOLADI — shu bois unda ijarachi egasining telefoni BO'LISHI MUMKIN EMAS.
    """
    t = _tenant(client)
    _tozala()
    r = _xato_login(client, t["phone"])
    assert r.status_code == 401, r.text

    qatorlar = _chelaklar()
    assert qatorlar, "urinish UMUMAN qayd etilmadi — proba kuchsiz"
    for q in qatorlar:
        assert not _telefon_izi_bormi(q["bucket"], t["phone"]), (
            f"XOM TELEFON chelakda: dimension={q['dimension']} "
            f"company_id={q['company_id']} bucket={q['bucket']!r}. "
            f"Bu qator purge'dan omon qoladi (company_id IS NULL), ya'ni "
            f"telefon o'chirilgan do'kondan keyin ham bazada qoladi. "
            f"Yechim: `ratelimit.account_bucket` (HMAC) ishlatilsin.")


def test_P0_2_IP_ZAXIRA_yolida_ham_TELEFON_YOZILMAYDI(client, monkeypatch):
    """IP aniqlanmaganda `ip` chelagi ham telefonga bog'lanmasin.

    `ipk = f"pw:{ip}" if ip else f"pw:?:{phone or '-'}"` — ikkinchi shox
    telefonni `ip` o'lchoviga olib kiradi.
    """
    import app.api.v1.auth as A

    t = _tenant(client)
    _tozala()
    monkeypatch.setattr(A, "_client_ip", lambda request: None)
    r = _xato_login(client, t["phone"])
    assert r.status_code == 401, r.text

    qatorlar = _chelaklar()
    assert qatorlar, "urinish qayd etilmadi — proba kuchsiz"
    ip_qatorlar = [q for q in qatorlar if q["dimension"] == "ip"]
    assert ip_qatorlar, f"`ip` o'lchovi yozilmadi: {qatorlar}"
    for q in ip_qatorlar:
        assert not _telefon_izi_bormi(q["bucket"], t["phone"]), (
            f"IP ZAXIRA kalitida XOM TELEFON: {q['bucket']!r}")


def test_P0_3_statik_gard_manbada_XOM_telefon_chelagi_YOQ():
    """Chaqiruv joyi darajasidagi to'siq — kelgusi regressiyani ushlaydi."""
    kod = _manba_izohsiz()
    #  Vakuumga qarshi: gard HAQIQATAN shu faylni ko'radi.
    assert "login_password" in kod, "AST ajratgichi `auth.py` ni o'qimadi"
    assert "ACCT_TIER" in kod, "rate-limit chaqiruvlari topilmadi"

    buzilgan = [naqsh for naqsh in ("pw:{phone}", "pw:?:{phone")
                if naqsh in kod]
    assert buzilgan == [], (
        f"manbada XOM telefonli chelak naqshi bor: {buzilgan}. "
        f"Telefon `account_bucket` bilan kalitlanishi SHART.")


# ══ 2) PRIMITIV: barqaror, qaytarib bo'lmaydigan, domen-ajratilgan ═════════

def test_P0_4_BARQAROR_va_QAYTARIB_BOLMAYDIGAN_kalit():
    """`account_bucket` — HMAC naqshi, `candidate_bucket` bilan AYNI uslub."""
    from app.core import ratelimit as RL

    telefon = "+998941234567"
    b1 = RL.account_bucket(telefon)
    b2 = RL.account_bucket(telefon)

    #  BARQAROR: ayni kirish -> ayni kalit (replikalar va restartlar bo'ylab).
    assert b1 == b2, "kalit barqaror emas — hisoblagich har safar nolga tushardi"
    #  SHAKL: `candidate_bucket` bilan ayni (32 hex belgi).
    assert re.fullmatch(r"[0-9a-f]{32}", b1), b1
    #  QAYTARIB BO'LMAYDIGAN: telefon izi YO'Q.
    assert not _telefon_izi_bormi(b1, telefon), b1
    #  AJRATISH: boshqa telefon -> boshqa kalit.
    assert RL.account_bucket("+998941234568") != b1
    #  DOMEN AJRATISH: `acct` kaliti `cand` kaliti bilan TO'QNASHMAYDI.
    assert RL.candidate_bucket(None, telefon) != b1, (
        "domen ajratilmagan — `acct` va `cand` chelaklari to'qnashishi mumkin")
    #  TUZ: tuzsiz SHA-256 EMAS.
    import hashlib
    assert hashlib.sha256(telefon.encode()).hexdigest()[:32] != b1, (
        "tuzsiz SHA-256 ishlatilgan — qisqa fazoda lug'at hujumi bilan qaytariladi")


def test_P0_9_KALIT_konfiguratsiyasi_tuzga_BOGLANGAN(monkeypatch):
    """Tuz `SECRET_KEY` dan olinadi; kalit o'zgarsa chelak ham o'zgaradi."""
    from app.core import ratelimit as RL
    from app.core.config import settings

    telefon = "+998949998877"
    asl = RL.account_bucket(telefon)
    monkeypatch.setattr(settings, "secret_key", "butunlay-boshqa-kalit-f9a", raising=False)
    boshqa = RL.account_bucket(telefon)
    assert boshqa != asl, (
        "chelak `SECRET_KEY` ga bog'lanmagan — tuz qattiq kodlangan bo'lishi mumkin")
    assert re.fullmatch(r"[0-9a-f]{32}", boshqa), boshqa


def test_P0_9b_ZAIF_kalit_PRODUCTIONDA_bootni_TOSADI(monkeypatch):
    """Zaif/standart `SECRET_KEY` production'da fail-closed darvozada to'siladi.

    ⚠️  Bu tuzatish YANGI darvoza qo'shmaydi — mavjud kanonik darvozaga
        tayanadi (`app/main.py` -> `security_config`). Shu test o'sha
        tayanchning HAQIQATAN mavjudligini qadaydi, aks holda «kalit kuchli»
        degan taxmin isbotsiz qolardi.
    """
    from app.core import security_config
    from app.core.config import DEFAULT_SECRET, settings

    #  Siyosat standart kalitni ANIQLAYDI.
    assert security_config.secret_key_problem(DEFAULT_SECRET) is not None

    monkeypatch.setattr(settings, "secret_key", DEFAULT_SECRET)

    #  (a) DEV/TEST muhitida bu faqat OGOHLANTIRISH — ataylab (o'lchangan:
    #      `evaluate()` da `CRITICAL if prod else WARNING`).
    monkeypatch.setattr(settings, "app_env", "dev")
    qatorlar = {r["key"]: r for r in security_config.evaluate()}
    assert qatorlar["SECRET_KEY"]["ok"] is False
    assert qatorlar["SECRET_KEY"]["severity"] == security_config.WARNING

    #  (b) PRODUCTION'da esa KRITIK — ya'ni `main.py` boot'ni TO'XTATADI.
    monkeypatch.setattr(settings, "app_env", "production")
    qatorlar = {r["key"]: r for r in security_config.evaluate()}
    assert qatorlar["SECRET_KEY"]["ok"] is False
    assert qatorlar["SECRET_KEY"]["severity"] == security_config.CRITICAL
    assert any(r["key"] == "SECRET_KEY"
               for r in security_config.critical_failures()), (
        "standart `SECRET_KEY` production'da kritik deb belgilanmadi")


# ══ 3) XULQ SAQLANADI: cheklov, izolyatsiya, oyna, prune ═══════════════════

def test_P0_5_AYNI_telefon_uchun_CHEKLOV_ishlaydi(client):
    """Hisob qatlami AVVALGIDEK bloklaydi (xulq o'zgarmaydi)."""
    from app.core.ratelimit import ACCT_TIER

    t = _tenant(client)
    _tozala()
    chegara = ACCT_TIER[0]
    #  ⚠️  IP QATLAMINI AJRATAMIZ. TestClient BARCHA so'rovlarni ayni manbadan
    #      yuboradi, IP qatlami esa qattiqroq (10/300 s) — ya'ni u hisob
    #      qatlamidan (12/900 s) OLDIN bloklaydi va test «hisob cheklovi»
    #      o'rniga IP cheklovini o'lchab qo'yadi (o'lchangan: 11-urinishda
    #      429 «5 daqiqadan keyin» = IP_TIER xabari).
    for i in range(chegara):
        _tozala("ip")
        r = _xato_login(client, t["phone"])
        assert r.status_code == 401, (i, r.text)
    _tozala("ip")
    r = _xato_login(client, t["phone"])
    assert r.status_code == 429, (
        f"hisob qatlami bloklamadi — cheklov xulqi BUZILDI: {r.status_code}")
    #  VA bu AYNAN hisob qatlami (IP emas) — xabar bilan isbotlanadi.
    assert ACCT_TIER[2] in r.text, (
        f"429 boshqa qatlamdan keldi: {r.text[:160]}")


def test_P0_6_BOSHQA_telefon_IZOLYATSIYA_qilinadi(client):
    """Bitta telefonning bloklanishi BOSHQASIGA ta'sir qilmasin."""
    from app.core.ratelimit import ACCT_TIER

    a = _tenant(client)
    b = _tenant(client)
    _tozala()
    #  `ip` o'lchovi HAR urinishdan keyin tozalanadi — bu test AYNAN hisob
    #  qatlamining ajratilishini o'lchaydi (P0_5 dagi ayni sabab).
    for _ in range(ACCT_TIER[0] + 1):
        _tozala("ip")
        _xato_login(client, a["phone"])
    #  A bloklangan — va AYNAN hisob qatlami bilan.
    _tozala("ip")
    bloklangan = _xato_login(client, a["phone"])
    assert bloklangan.status_code == 429, bloklangan.text[:160]
    assert ACCT_TIER[2] in bloklangan.text, bloklangan.text[:160]
    #  B esa YO'Q — faqat oddiy 401.
    _tozala("ip")
    r = _xato_login(client, b["phone"])
    assert r.status_code == 401, (
        f"boshqa telefon ham bloklandi — chelak ajratilmagan: {r.status_code}")


def test_P0_7_15_DAQIQALIK_oyna_SAQLANADI(client):
    """Oyna 900 s bo'lib qoladi va oynadan TASHQARIDAGI qator sanalmaydi."""
    from app.core.ratelimit import ACCT_TIER, account_bucket
    from app.models.security import AuthAttempt

    assert ACCT_TIER[1] == 900, f"oyna o'zgardi: {ACCT_TIER}"

    t = _tenant(client)
    _tozala()
    chelak = account_bucket(t["phone"])
    eski = datetime.now(timezone.utc) - timedelta(seconds=ACCT_TIER[1] + 120)
    db = _db()
    try:
        for _ in range(ACCT_TIER[0] + 5):
            db.add(AuthAttempt(dimension="acct", bucket=chelak,
                               company_id=None, occurred_at=eski))
        db.commit()
    finally:
        db.close()
    #  Hammasi oynadan TASHQARIDA — bloklanmasligi SHART.
    r = _xato_login(client, t["phone"])
    assert r.status_code == 401, (
        f"oynadan tashqaridagi qatorlar sanaldi: {r.status_code}")


def test_P0_8_DANGASA_PRUNE_eski_qatorni_OCHIRADI(client):
    """`_prune` oynadan eski qatorlarni o'chiradi (dangasa, login yo'lida)."""
    from app.core import ratelimit as RL
    from app.models.security import AuthAttempt

    t = _tenant(client)
    _tozala()
    eski = datetime.now(timezone.utc) - timedelta(seconds=RL._MAX_WINDOW + 600)
    db = _db()
    try:
        db.add(AuthAttempt(dimension="acct", bucket="f9a-eski-chelak",
                           company_id=None, occurred_at=eski))
        db.commit()
    finally:
        db.close()
    assert any(q["bucket"] == "f9a-eski-chelak" for q in _chelaklar())

    #  Dangasa bo'g'ishni nolga tushiramiz, so'ng login yo'lini chaqiramiz.
    RL._last_prune[0] = 0.0
    _xato_login(client, t["phone"])
    assert not any(q["bucket"] == "f9a-eski-chelak" for q in _chelaklar()), (
        "`_prune` eski qatorni o'chirmadi — saqlash oynasi cheksizlashadi")


def test_P0_10_PARALLEL_urinishlar_SANOQNI_buzmaydi(client):
    """Ketma-ket (parallel) urinishlar sanoqni to'g'ri yig'adi."""
    from app.core.ratelimit import ACCT_TIER, account_bucket

    t = _tenant(client)
    _tozala()
    n = 4
    for _ in range(n):
        assert _xato_login(client, t["phone"]).status_code == 401
    chelak = account_bucket(t["phone"])
    acct = [q for q in _chelaklar("acct") if q["bucket"] == chelak]
    assert len(acct) == n, (
        f"sanoq mos emas: kutilgan {n}, topilgan {len(acct)} -> {acct}")
    #  Hammasi AYNI chelakda (ya'ni kalit urinishlar bo'ylab barqaror).
    assert len({q["bucket"] for q in acct}) == 1
    assert ACCT_TIER[0] > n, "proba chegaradan oshib ketdi"


# ══ 4) OSHKORLIK VA DOIRA ══════════════════════════════════════════════════

def test_P0_11_JAVOB_va_XATODA_telefon_OQMAYDI(client):
    """HTTP javobida (va xato matnida) telefon ham, chelak ham ko'rinmasin."""
    t = _tenant(client)
    _tozala()
    r = _xato_login(client, t["phone"])
    assert r.status_code == 401
    assert not _telefon_izi_bormi(r.text, t["phone"]), (
        f"telefon JAVOBDA qaytdi: {r.text[:200]}")

    from app.core.ratelimit import account_bucket
    assert account_bucket(t["phone"]) not in r.text, "chelak javobda oshkor bo'ldi"

    #  429 yo'lida ham.
    from app.core.ratelimit import ACCT_TIER
    for _ in range(ACCT_TIER[0] + 1):
        _tozala("ip")
        _xato_login(client, t["phone"])
    _tozala("ip")
    r429 = _xato_login(client, t["phone"])
    assert r429.status_code == 429
    assert not _telefon_izi_bormi(r429.text, t["phone"]), r429.text[:200]


def test_P0_12_EGALIK_DOIRASI_ozgarmaydi(client):
    """Bu tuzatish EGALIK (`company_id`) semantikasiga TEGMAYDI.

    ⚠️  ATAYLAB: `acct`/`ip` o'lchovlari do'kon ANIQLANISHIDAN OLDIN
        tekshiriladi, shu bois ular `company_id=None` bilan qolaveradi.
        Tuzatish FAQAT chelak QIYMATINI kalitlaydi. `company_id` ni bu yerda
        to'ldirish ALOHIDA siyosat qarori (S1-F8 D4) va u bu bosqichda
        BAJARILMAYDI — shu test buni qayd etib, jim o'zgarishni to'sadi.
    """
    t = _tenant(client)
    _tozala()
    _xato_login(client, t["phone"])
    for q in _chelaklar():
        if q["dimension"] in ("acct", "ip"):
            assert q["company_id"] is None, (
                f"egalik semantikasi o'zgardi: {q} — bu S1-F8 D4 qarorini "
                f"talab qiladi, S1-F9A doirasida EMAS")

    #  Ikki ijarachi AYNI chelakni BO'LISHMAYDI (kalit telefonga xos).
    b = _tenant(client)
    from app.core.ratelimit import account_bucket
    assert account_bucket(t["phone"]) != account_bucket(b["phone"])
