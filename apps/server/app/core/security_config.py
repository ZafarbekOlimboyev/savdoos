# -*- coding: utf-8 -*-
"""Production xavfsizlik konfiguratsiyasining YAGONA manbai.

⚠️  NEGA BITTA JOYDA. Ilgari xavfsizlik shartlari uch joyda alohida yozilgan edi:
    `main.py` boot qo'riqchisi, `/health/ready` va `app/tools/config_audit.py`.
    Uchtasi vaqt o'tib bir-biridan uzoqlashdi — audit `config_audit` ni "REVIEW"
    deb belgilagan shartlar boot'ni umuman to'xtatmasdi, `config_audit` ning o'zi
    esa runbook'dagi qo'l buyrug'idan boshqa hech qayerdan chaqirilmasdi. Ya'ni
    "xavfsizlik auditi yashil" degani ILOVA XAVFSIZ degani EMAS edi.

    Endi shartlar SHU YERDA baholanadi va uchala iste'molchi ham shu funksiyani
    chaqiradi. Yangi shart qo'shilsa — u avtomatik ravishda boot'ga, readiness'ga
    va CI'ga tarqaladi.

⚠️  SIR QIYMATLARI HECH QACHON QAYTARILMAYDI. Faqat kalit NOMI, holat va sabab.
"""
from __future__ import annotations

import os
import re

from app.core.config import DEFAULT_SECRET, settings

CRITICAL, WARNING, INFO = "CRITICAL", "WARNING", "INFO"

# ── SECRET_KEY siyosati ─────────────────────────────────────────────────────
# JWT HS256 imzosi uchun kalit. Ilgari tekshiruv `secret_key == DEFAULT_SECRET`
# edi — ya'ni AYNAN o'sha satr. `SECRET_KEY=x` bergan production YASHIL ko'tarilardi
# va tokenlarni bir belgili kalit bilan imzolardi.
SECRET_MIN_LEN = 32          # HS256 uchun >= 256 bit entropiya maqsad qilinadi
SECRET_MIN_UNIQUE = 8        # "xxxx...", "abababab..." kabi arzon kalitlarni to'sadi

# Ochiq manbalarda va shablonlarda uchraydigan qiymatlar — hech qachon qabul qilinmaydi.
_SECRET_PLACEHOLDERS = frozenset({
    DEFAULT_SECRET.lower(),
    "secret", "secretkey", "secret_key", "changeme", "change-me", "change_me",
    "please-change", "replace-me", "your-secret-key", "supersecret", "topsecret",
    "test", "testing", "dev", "development", "prod", "production",
    "password", "passw0rd", "admin", "example", "sample", "placeholder",
    "insecure", "notsecret", "todo", "xxx", "asdf", "qwerty", "123456",
})


def secret_key_problem(value: str | None) -> str | None:
    """SECRET_KEY siyosatini buzsa — SABABNI qaytaradi, aks holda None.

    Qiymatning O'ZI hech qachon qaytarilmaydi va loglanmaydi."""
    raw = (value or "").strip()
    if not raw:
        return "berilmagan yoki bo'sh"
    if raw.lower() in _SECRET_PLACEHOLDERS:
        return "ma'lum shablon/standart qiymat (ochiq manbalarda mavjud)"
    # "secret123", "changeme!" kabi shablon + qo'shimcha
    low = re.sub(r"[^a-z0-9]", "", raw.lower())
    for ph in _SECRET_PLACEHOLDERS:
        clean = re.sub(r"[^a-z0-9]", "", ph)
        if clean and len(clean) >= 5 and low.startswith(clean):
            return "ma'lum shablon qiymatidan boshlanadi"
    if len(raw) < SECRET_MIN_LEN:
        return f"juda qisqa ({len(raw)} belgi, kamida {SECRET_MIN_LEN} kerak)"
    if len(set(raw)) < SECRET_MIN_UNIQUE:
        return (f"entropiyasi past ({len(set(raw))} xil belgi, kamida "
                f"{SECRET_MIN_UNIQUE} kerak) — takrorlanuvchi naqsh")
    return None


def _env_set(name: str) -> bool:
    """Muhit o'zgaruvchisi berilganmi — QIYMAT O'QILMAYDI/CHOP ETILMAYDI."""
    return bool((os.getenv(name) or "").strip())


def evaluate() -> list[dict]:
    """Xavfsizlik shartlarini baholaydi. Har yozuv: key/severity/ok/note.

    `severity` FAQAT muammo bo'lganda ahamiyatli: `ok=True` bo'lsa u INFO."""
    prod = settings.is_production
    rows: list[dict] = []

    def add(key, ok, severity, note):
        rows.append({"key": key, "ok": bool(ok),
                     "severity": INFO if ok else severity, "note": note})

    # ── 1) Production'da SQLite ─────────────────────────────────────────────
    sqlite_prod = prod and settings.database_url.startswith("sqlite")
    add("DATABASE_URL", not sqlite_prod, CRITICAL,
        "production'da SQLite — konteyner qayta ishga tushganda savdolar YO'QOLADI"
        if sqlite_prod else "tashqi baza")

    # ── 2) JWT imzo kaliti ──────────────────────────────────────────────────
    problem = secret_key_problem(settings.secret_key)
    # Dev/test'da standart kalit NORMAL — u yerda bu faqat ogohlantirish.
    add("SECRET_KEY", problem is None, CRITICAL if prod else WARNING,
        f"siyosatni buzadi: {problem}" if problem else "siyosatga mos")

    # ── 3) Demo seed ────────────────────────────────────────────────────────
    seed_demo = _env_set("SEED_DEMO") and (os.getenv("SEED_DEMO") or "").strip() == "1"
    add("SEED_DEMO", not (prod and seed_demo), CRITICAL,
        "production'da demo seed YOQILGAN — real bazaga MA'LUM kredensialli soxta "
        "tenant tushadi" if (prod and seed_demo) else "o'chiq")

    # ── 4) Vendor portali ───────────────────────────────────────────────────
    # Vendor kaliti CROSS-TENANT: u bilan har do'konni yaratish, to'xtatish va
    # O'CHIRISH mumkin. Shu bois production'da u YOLG'IZ yetarli bo'lmasligi kerak.
    if settings.vendor_admin_key.strip():
        add("VENDOR_ADMIN_KEY", True, INFO, "vendor portali yoqilgan")
        add("VENDOR_TOTP_SECRET", not prod or settings.vendor_2fa_on, CRITICAL,
            "production'da vendor 2FA MAJBURIY — kalit yolg'iz cross-tenant "
            "kirishga yetmasligi kerak" if prod and not settings.vendor_2fa_on
            else ("2FA yoqilgan" if settings.vendor_2fa_on else "2FA o'chiq (dev)"))
        n_ip = len(settings.vendor_ip_list)
        add("VENDOR_ALLOWED_IPS", not prod or n_ip > 0, CRITICAL,
            "production'da vendor IP allowlist MAJBURIY — kalit sizsa istalgan "
            "joydan kirish mumkin bo'lardi" if prod and not n_ip else f"{n_ip} ta manba")
    else:
        add("VENDOR_ADMIN_KEY", True, INFO, "vendor portali o'chiq (kalit yo'q)")

    return rows


def critical_failures() -> list[dict]:
    """Ishga tushishni TO'XTATADIGAN buzilishlar (bo'sh bo'lsa — xavfsiz)."""
    return [r for r in evaluate() if not r["ok"] and r["severity"] == CRITICAL]


def security_config_ok() -> tuple[bool, dict]:
    """`/health/ready` uchun: (xavfsizmi, kalit -> holat).

    Sir qiymatlari ham, ortiqcha konfiguratsiya tafsiloti ham QAYTARILMAYDI —
    faqat kalit nomi va u siyosatga mos kelishi."""
    rows = evaluate()
    bad = [r for r in rows if not r["ok"] and r["severity"] == CRITICAL]
    return (not bad), {r["key"]: r["ok"] for r in rows}


class UnsafeConfigError(RuntimeError):
    """Production konfiguratsiyasi xavfsiz emas — ishga tushish TO'XTAYDI."""


def enforce_at_boot() -> None:
    """Boot qo'riqchisi. Kritik buzilish bo'lsa ishga tushishga YO'L QO'YMAYDI.

    `start.sh` `set -e` bilan ishlaydi, ya'ni bu xato konteynerni to'xtatadi.
    Bu ATAYLAB: xavfsiz bo'lmagan konfiguratsiyada "sog'lom" backend bo'lmasligi kerak."""
    bad = critical_failures()
    if not bad:
        return
    lines = "\n".join(f"  - {r['key']}: {r['note']}" for r in bad)
    raise UnsafeConfigError(
        "PRODUCTION KONFIGURATSIYASI XAVFSIZ EMAS — ishga tushish TO'XTATILDI.\n"
        f"{lines}\n"
        "  Sozlamalarni to'g'rilang (qiymatlar bu yerda hech qachon chop etilmaydi)."
    )
