# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · PRODUCTION CONFIG AUDIT (STRICTLY READ-ONLY).

Kritik konfiguratsiya joyidami — ishga tushirishdan OLDIN tekshiradi.

⚠️  QIYMAT HECH QACHON CHOP ETILMAYDI. Faqat holat:
      PRESENT         — o'rnatilgan (qiymat ko'rsatilmaydi)
      MISSING         — yo'q
      UNSAFE_DEFAULT  — o'rnatilmagan va standart qiymat production uchun XAVFLI
      REVIEW          — o'rnatilgan, lekin operator ko'zdan kechirishi kerak
      OFF             — ixtiyoriy imkoniyat o'chiq (bu normal)

Operator:
    railway.cmd ssh --service savdoos -- python -m app.tools.config_audit --json

Exit: 0 = kritik muammo yo'q, 2 = kamida bitta UNSAFE_DEFAULT/MISSING (kritik), 1 = usage.
"""
from __future__ import annotations

import argparse
import os

from app.core.config import settings
from app.core.security_config import CRITICAL as _SEC_CRITICAL
from app.core.security_config import evaluate as _sec_evaluate
from app.tools import _common as C

PRESENT, MISSING, UNSAFE, REVIEW, OFF = "PRESENT", "MISSING", "UNSAFE_DEFAULT", "REVIEW", "OFF"


def _env_set(name: str) -> bool:
    """Muhit o'zgaruvchisi berilganmi — QIYMAT O'QILMAYDI/CHOP ETILMAYDI."""
    return bool((os.getenv(name) or "").strip())


def audit() -> list[dict]:
    prod = settings.is_production
    rows: list[dict] = []

    def add(key, status, critical, note):
        rows.append({"key": key, "status": status, "critical": bool(critical), "note": note})

    # ── XAVFSIZLIK SHARTLARI — KANONIK manbadan ─────────────────────────────
    # ⚠️  Bu yerda shartlar QAYTA YOZILMAYDI. Ilgari SECRET_KEY, SEED_DEMO va vendor
    #     shartlari shu faylda alohida baholanar, `main.py` va `/health/ready` esa
    #     o'zicha tekshirardi — uchtasi vaqt o'tib bir-biridan uzoqlashdi. Endi
    #     yagona `security_config.evaluate()` ishlatiladi, ya'ni bu hisobot boot
    #     to'xtatadigan narsa bilan AYNAN bir xil narsani ko'rsatadi.
    for r in _sec_evaluate():
        add(r["key"], PRESENT if r["ok"] else UNSAFE,
            (not r["ok"]) and r["severity"] == _SEC_CRITICAL, r["note"])

    # ── Muhit nomi ──────────────────────────────────────────────────────────
    if _env_set("APP_ENV"):
        add("APP_ENV", PRESENT, False, f"aniq berilgan (is_production={prod})")
    else:
        add("APP_ENV", REVIEW if prod else OFF, False,
            "berilmagan. Postgres aniqlangani uchun is_production fail-safe yoqildi, "
            "lekin aniq APP_ENV=prod berish afzal (niyat yashirin qolmasin).")

    # ── CORS ────────────────────────────────────────────────────────────────
    if "*" in settings.cors_list:
        add("CORS_ORIGINS", REVIEW, False,
            "'*' — paketlangan desktop ilova file:// (Origin: null) orqali ulanadi. "
            "allow_credentials ATAYLAB o'chirilgan (CORS spetsifikatsiyasi), auth Bearer header orqali. "
            "Brauzer-mijoz qo'shilsa qayta ko'rib chiqilsin.")
    else:
        add("CORS_ORIGINS", PRESENT, False, f"{len(settings.cors_list)} ta manba ro'yxatlangan")

    # ── Naqd rejimi (global, env-only) ──────────────────────────────────────
    from app.services.cash import mode as _mode_mod
    mode = C.current_cash_mode()
    if _env_set(_mode_mod.MODE_ENV):
        add(_mode_mod.MODE_ENV, REVIEW if mode == "LEGACY_ONLY" else PRESENT, mode == "LEGACY_ONLY",
            f"joriy: {mode}. LEGACY_ONLY bo'lsa ledger-native tenantlar 503 beradi "
            "(require_ledger_writable) — bu ATAYLAB, jim degradatsiya o'rniga.")
    else:
        add(_mode_mod.MODE_ENV, OFF, False, f"berilmagan -> standart {mode}")
    # DIQQAT: bu kalit nomi shu yerda QATTIQ YOZILMAYDI (yuqoridagi izohga qarang) —
    # faqat O'QILADI, hech qachon o'rnatilmaydi.
    add(_mode_mod.ALLOW_PRIMARY_ENV, PRESENT if _env_set(_mode_mod.ALLOW_PRIMARY_ENV) else OFF,
        False, "LEDGER_PRIMARY uchun qo'shimcha ochqich; cutover qilinmaguncha berilmasin")

    # ── Backup siri (ilova o'qimaydi, LEKIN launch uchun SHART) ────────────
    # Bu qiymat GitHub Actions secret'i — server muhitida bo'lmasligi NORMAL. Shu bois bu yerda
    # faqat ESLATMA: haqiqiy tekshiruv `DB Backup` workflow'ining artefakt chiqarishi bilan bo'ladi.
    add("PROD_DATABASE_URL (GitHub secret)", REVIEW, False,
        "ilova o'qimaydi — bu GitHub Actions siri. Yo'q bo'lsa TUNGI BACKUP UMUMAN OLINMAYDI. "
        "Tekshirish: Actions > DB Backup > oxirgi run > Artifacts BO'SH EMASmi.")

    # ── Tashqi integratsiyalar (ixtiyoriy) ──────────────────────────────────
    add("XPAY (QR to'lov)", PRESENT if settings.xpay_enabled else OFF, False,
        "kalitlar to'liq" if settings.xpay_enabled else "o'chiq — QR to'lov ishlamaydi")
    add("FCM (push)", PRESENT if settings.fcm_enabled else OFF, False,
        "yoqilgan" if settings.fcm_enabled else "o'chiq — kam-qoldiq bildirishnomasi yo'q")
    add("AI (hujjat o'qish)", PRESENT if settings.ai_any else OFF, False,
        "yoqilgan" if settings.ai_any else "o'chiq — demo rejim")

    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SavdoOS production konfiguratsiya auditi (read-only, sirsiz).")
    p.add_argument("--json", action="store_true", help="stdout FAQAT JSON")
    args = p.parse_args(argv)

    C.set_stdout_json_only(bool(args.json))
    try:
        rows = audit()
        bad = [r for r in rows if r["critical"]]
        payload = {
            "is_production": settings.is_production,
            "evaluated_env": "production" if settings.is_production else "non-production",
            "verdict": "CONFIG_OK" if not bad else "CONFIG_UNSAFE",
            "critical_count": len(bad),
            "rows": rows,
        }
        if args.json:
            C.emit_json(payload)
        else:
            C.out("=" * 74)
            C.out(" SavdoOS · PRODUCTION CONFIG AUDIT   (qiymatlar HECH QACHON chop etilmaydi)")
            C.out(f"   is_production: {settings.is_production}")
            C.out("=" * 74)
            for r in rows:
                mark = "!!" if r["critical"] else "  "
                C.out(f" {mark} {r['key']:34s} {r['status']:15s} {r['note']}")
            C.out("=" * 74)
            if not settings.is_production:
                C.out(" DIQQAT: bu NON-PRODUCTION muhit. Haqiqiy tekshiruv uchun production'da ishga tushiring:")
                C.out("   railway.cmd ssh --service savdoos -- python -m app.tools.config_audit --json")
            C.out(payload["verdict"])
        return 0 if not bad else 2
    finally:
        C.set_stdout_json_only(False)


if __name__ == "__main__":
    raise SystemExit(main())
