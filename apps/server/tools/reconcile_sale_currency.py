# -*- coding: utf-8 -*-
"""Tarixiy `sales.currency` rekonsiliatsiyasi — DARVOZALI, IDEMPOTENT, standart holda FAQAT O'QISH.

NEGA KERAK
──────────
`sales.currency` ustunini uzoq vaqt HECH BIR yozuvchi o'rnatmasdi va qiymatni ORM ning
Python-tomon `default="UZS"` i berardi (tuzatish: `app/services/currency.py` + to'rtala
yozuvchi). Natijada KGS do'konda yozilgan sotuvlar `UZS` bo'lib qolgan. Ularning
`'UZS'` qiymati MA'LUMOT EMAS — standart artefakti.

2026-10-03 da production'da FAQAT O'QISH auditi:
    tenant `fayzan1`  company=KGS  sale=UZS  →  2 qator (sold_at 2026-09-26)
    staging                                  →  nomuvofiqlik 0
Klassifikatsiya: ikki qator ham **B (provably default artifact)**, dalillar:
  1. `companies.fayzan1`: `created_at == updated_at`, `row_version=1` — yaratilgandan
     beri YANGILANMAGAN (2026-09-10T22:21:15.623885Z);
  2. `companies.currency` ni FAQAT yaratilishda yozadigan kod bor (`api/v1/admin.py`,
     `app/seed.py`) — YANGILASH endpointi YO'Q;
  3. sotuvlar kompaniya KGS bo'lganidan 16 kun KEYIN (2026-09-26);
  4. `sales.currency` ni hech bir kod yo'li hech qachon yozmagan.
Ambigulik (C) qatori YO'Q.

TARTIB — MUHIM
──────────────
1. AVVAL tuzatilgan server deploy qilinadi. Aks holda yangi sotuvlar yana `UZS` kelib
   tushadi va rekonsiliatsiya cheksiz takrorlanadi.
2. KEYIN shu skript `--apply` bilan ishlatiladi.
Teskari tartib TAQIQ.

ISHLATISH (apps/server da)
──────────────────────────
    # 1) FAQAT O'QISH (standart) — hech narsa o'zgarmaydi
    railway run --service Postgres-d29B -- .venv/Scripts/python tools/reconcile_sale_currency.py

    # 2) YOZISH — faqat tekshirgandan keyin
    railway run --service Postgres-d29B -- .venv/Scripts/python tools/reconcile_sale_currency.py \\
        --apply --tenant fayzan1 --from-currency UZS --to-currency KGS --expect 2

DARVOZALAR (birortasi buzilsa — ABORT, yozuv YO'Q)
──────────────────────────────────────────────────
  · tenant kodi AYNAN `--tenant` (standart `fayzan1`);
  · `companies.currency` AYNAN `--to-currency` (standart `KGS`);
  · `sales.currency` AYNAN `--from-currency` (standart `UZS`);
  · qator kompaniya YARATILGANDAN KEYIN sotilgan (`sold_at >= companies.created_at`) —
    bu auditlangan artefakt to'plamini ta'riflaydi va kelajakda valyuta o'zgarsa
    himoya bo'ladi;
  · ta'sir qiladigan qator soni AYNAN `--expect` (standart 2); boshqa bo'lsa ABORT;
  · hammasi BITTA tranzaksiyada; `--apply` bo'lmasa ROLLBACK.

IDEMPOTENTLIK: ikkinchi yurishda mos qator 0 bo'ladi, `--expect 2` esa 0 ni qabul
qilmaydi → ABORT (xato EMAS, "allaqachon bajarilgan" degan ma'noda). Shu bois ikkinchi
yurish uchun `--expect 0 --apply` ishlatiladi: u ham hech narsa o'zgartirmaydi.

ROLLBACK
────────
Bu skript faqat `currency` ustunini o'zgartiradi, boshqa hech narsani. Qaytarish:
    UPDATE sales s SET currency = '<from-currency>'
      FROM companies c
     WHERE c.id = s.company_id AND c.code = '<tenant>'
       AND s.currency = '<to-currency>' AND s.id IN (<quyida chop etilgan id'lar>);
Skript `--apply` dan OLDIN ta'sir qiladigan qatorlarning `id` va `receipt_no` sini
chop etadi — ularni logda saqlang. Pul/mijoz maydonlari CHOP ETILMAYDI.

⚠️  Bu skript PRODUCTION ma'lumotiga yozadi. `--apply` ni faqat ega qarori bilan.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse


def _dsn() -> str:
    """`DATABASE_URL`; ichki Railway hosti tashqaridan yechilmasa — TCP proxy'ga ko'chiradi."""
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    if not url:
        print("[ABORT] DATABASE_URL env yo'q (railway run --service Postgres-... bilan ishlating)")
        sys.exit(2)
    dom, prt = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN"), os.environ.get("RAILWAY_TCP_PROXY_PORT")
    if dom and prt and ".railway.internal" in url:
        pr = urllib.parse.urlsplit(url)
        nl = pr.netloc.rsplit("@", 1)
        cred = nl[0] + "@" if len(nl) == 2 else ""
        url = urllib.parse.urlunsplit(pr._replace(netloc=f"{cred}{dom}:{prt}"))
    return url


# Mos qatorlarni TA'RIFLAYDIGAN yagona predikat — hisoblash ham, yozish ham SHUNI ishlatadi
# (ikki joyda ikki xil shart bo'lsa, hisoblangan son yozilganidan farq qilib ketardi).
_MATCH = """
  from sales s join companies c on c.id = s.company_id
 where c.code = %(tenant)s
   and upper(trim(c.currency)) = %(to_cur)s
   and upper(trim(s.currency)) = %(from_cur)s
   and s.sold_at >= c.created_at
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sales.currency rekonsiliatsiyasi (darvozali)")
    ap.add_argument("--tenant", default="fayzan1", help="do'kon kodi (AYNAN)")
    ap.add_argument("--from-currency", default="UZS", help="xato qiymat (AYNAN)")
    ap.add_argument("--to-currency", default="KGS", help="do'kon valyutasi (AYNAN)")
    ap.add_argument("--expect", type=int, default=2, help="kutilgan qator soni; mos kelmasa ABORT")
    ap.add_argument("--apply", action="store_true", help="YOZADI (bo'lmasa — rollback)")
    a = ap.parse_args(argv)

    try:
        import psycopg
    except ImportError:
        print("[ABORT] psycopg yo'q — apps/server/.venv ni ishlating")
        return 2

    p = {"tenant": a.tenant, "from_cur": a.from_currency.strip().upper(),
         "to_cur": a.to_currency.strip().upper()}
    print("[rejim] " + ("APPLY (YOZADI)" if a.apply else "FAQAT OQISH (rollback)"))
    print(f"[darvoza] tenant={p['tenant']} {p['from_cur']} -> {p['to_cur']} expect={a.expect}")

    with psycopg.connect(_dsn(), autocommit=False) as cn:
        with cn.cursor() as cur:
            if not a.apply:
                cur.execute("SET TRANSACTION READ ONLY")  # yozuvni FIZIK taqiqlaymiz

            # ── 0) Tenant va uning valyutasi ──
            cur.execute("select code, currency, created_at from companies where code = %(tenant)s", p)
            row = cur.fetchone()
            if row is None:
                print(f"[ABORT] tenant topilmadi: {p['tenant']}")
                return 1
            code, co_cur, co_created = row
            print(f"[tenant] code={code} currency={co_cur} created_at={co_created}")
            if (co_cur or "").strip().upper() != p["to_cur"]:
                print(f"[ABORT] company.currency {co_cur!r} != {p['to_cur']!r} — darvoza buzildi")
                return 1

            # ── 1) OLDINGI holat (butun tenant bo'yicha, kesim) ──
            cur.execute("""select upper(trim(s.currency)) as cur, count(*)
                             from sales s join companies c on c.id = s.company_id
                            where c.code = %(tenant)s group by 1 order by 1""", p)
            print("[oldin] tenant sotuvlari valyuta bo'yicha:",
                  {k: v for k, v in cur.fetchall()} or "yo'q")

            # ── 2) Mos qatorlar (pul/mijoz maydonlari CHOP ETILMAYDI) ──
            cur.execute(f"select s.id, s.receipt_no, s.sold_at {_MATCH} order by s.sold_at", p)
            matched = cur.fetchall()
            print(f"[mos] {len(matched)} qator:")
            for sid, no, sold in matched:
                print(f"   id={sid} receipt_no={no} sold_at={sold}")

            # ── 3) DARVOZA: soni AYNAN kutilgandek ──
            if len(matched) != a.expect:
                print(f"[ABORT] mos qator {len(matched)} != expect {a.expect} — HECH NARSA o'zgarmadi")
                cn.rollback()
                return 1
            if not matched:
                print("[OK] o'zgartirish kerak emas (idempotent: allaqachon bajarilgan)")
                cn.rollback()
                return 0

            if not a.apply:
                # DRY-RUN: UPDATE umuman YUBORILMAYDI (tranzaksiya READ ONLY — u xato berardi).
                print(f"[dry-run] {len(matched)} qator {p['from_cur']} -> {p['to_cur']} "
                      f"bo'lardi; yozish uchun --apply")
                cn.rollback()
                return 0

            # ── 4) Yozuv — AYNI predikat bilan, bitta tranzaksiyada ──
            cur.execute(f"""
                update sales set currency = %(to_cur)s
                 where id in (select s.id {_MATCH})
            """, p)
            changed = cur.rowcount
            print(f"[yozildi] {changed} qator")
            if changed != a.expect:
                print(f"[ABORT] yozilgan {changed} != expect {a.expect} — ROLLBACK")
                cn.rollback()
                return 1

            # ── 5) KEYINGI holat (ayni tranzaksiya ichida) ──
            cur.execute("""select upper(trim(s.currency)) as cur, count(*)
                             from sales s join companies c on c.id = s.company_id
                            where c.code = %(tenant)s group by 1 order by 1""", p)
            print("[keyin] tenant sotuvlari valyuta bo'yicha:", {k: v for k, v in cur.fetchall()})
            cur.execute(f"select count(*) {_MATCH}", p)
            left = cur.fetchone()[0]
            if left:
                print(f"[ABORT] {left} mos qator QOLDI — ROLLBACK")
                cn.rollback()
                return 1

        if a.apply:
            cn.commit()
            print("[COMMIT] rekonsiliatsiya bajarildi")
        else:
            cn.rollback()
            print("[ROLLBACK] faqat o'qish rejimi — hech narsa o'zgarmadi (--apply bilan yozadi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
