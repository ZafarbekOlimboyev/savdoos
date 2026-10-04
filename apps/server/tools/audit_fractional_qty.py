# -*- coding: utf-8 -*-
"""Bo'linmas birlikdagi KASR miqdorlar auditi — FAQAT O'QISH, YOZUV YO'Q.

NEGA KERAK
──────────
`units.allow_fraction` ustuni birinchi kundan beri bor (`db/schema.sql:170`), lekin
2026-10-04 gacha uni HECH BIR server yozuvchisi tekshirmasdi. Ya'ni `0.5 dona`,
`3.5 upak` kabi FIZIK MA'NOSIZ miqdorlar sotuv, kirim, sanoq, hisobdan chiqarish
va ko'chirish orqali bazaga tusha olardi.

Darvoza (`app/services/unit_gate.py`) YANGI yozuvlarni to'sadi. Bu skript esa
MAVJUD ma'lumotda nima borligini o'lchaydi — chunki:

  · mavjud kasr qoldiq darvozadan KEYIN ham joyida qoladi (yaxlitlash TAQIQ);
  · ba'zi tuzatish yo'llari shu holatda endi 400 beradi (ro'yxat pastda);
  · qancha qator borligini bilmasdan tuzatish rejasini tuzib bo'lmaydi.

⚠️  HECH NARSA O'ZGARTIRMAYDI. Tranzaksiya `SET TRANSACTION READ ONLY` bilan
    ochiladi, ya'ni yozuv FIZIK darajada imkonsiz. `--apply` kaliti ATAYLAB
    YO'Q: bu skriptning tuzatish rejimi umuman mavjud emas.

⚠️  MIJOZ MA'LUMOTI CHOP ETILMAYDI. Mahsulot NOMI, mijoz, telefon, chek raqami —
    chiqishda YO'Q. Faqat: tenant kodi, birlik kodi, jadval, qator SONI, miqdor
    qiymati va mahsulot UUID'i (ega o'zi qarab topadi).

ISHLATISH (apps/server da)
──────────────────────────
    # production
    railway run --service Postgres-d29B -- .venv/Scripts/python tools/audit_fractional_qty.py

    # staging
    railway run --service Postgres-d29B --environment staging -- \\
        .venv/Scripts/python tools/audit_fractional_qty.py

    # mahalliy SQLite (dev)
    DATABASE_URL=sqlite:///./savdoos.db .venv/Scripts/python tools/audit_fractional_qty.py

CHIQISH — KLASSIFIKATSIYA
─────────────────────────
  A  QOLDIQ (`inventory`, `stock_batches`) — JONLI holat. Tuzatish kerak, chunki
     kelgusi har amal shu holat ustida ishlaydi.
  B  TARIX (`sale_items`, `purchase_items`, `stock_movements`, `return_items`) —
     SODIR BO'LGAN hodisa yozuvi. Qayta yozish TAQIQ (Phase 2.5 qoidasi): tarix
     o'zgartirilmaydi, u shunday bo'lgan.
  C  QARZ (`lot_shortfalls`) — atributsiya qarzi; qoldiqqa ta'sir qilmaydi, lekin
     yopish yo'li kasr `k` bilan endi 400 beradi.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (jadval, ustun, sinf, izoh) — `products.unit_id -> units.allow_fraction = false` doirasida
TEKSHIRUV = [
    ("inventory",       "qty",           "A", "JONLI qoldiq (filial kesimi)"),
    ("stock_batches",   "remaining_qty", "A", "partiya OCHIQ qoldig'i"),
    ("stock_batches",   "received_qty",  "A", "partiya qabul miqdori (O'ZGARMAS)"),
    ("sale_items",      "qty",           "B", "sotuv qatori (TARIX)"),
    ("purchase_items",  "qty",           "B", "xarid qatori (TARIX)"),
    ("stock_movements", "qty",           "B", "ombor harakati (LEDGER)"),
    ("return_items",    "qty",           "B", "qaytarish qatori (TARIX)"),
    ("lot_shortfalls",  "qty",           "C", "atributsiya qarzi"),
    ("lot_shortfalls",  "resolved_qty",  "C", "yopilgan qarz"),
]

# ⚠️  `<> trunc(x)` — Postgres `numeric` da ANIQ taqqoslash (float xatosi yo'q).
#     `round()` yoki `::int` ISHLATILMAYDI: ular yaxlitlab, farqni YASHIRARDI.
SQL = """
SELECT c.code                AS tenant,
       u.code                AS birlik,
       t.product_id          AS pid,
       t.{col}               AS miqdor,
       count(*)              AS qatorlar
  FROM {tbl} t
  JOIN products p ON p.id = t.product_id
  JOIN units    u ON u.id = p.unit_id
  JOIN companies c ON c.id = p.company_id
 WHERE u.allow_fraction = false
   AND t.{col} IS NOT NULL
   AND t.{col} <> trunc(t.{col})
 GROUP BY 1, 2, 3, 4
 ORDER BY 1, 2, 3
 LIMIT %s
"""

JAMI = """
SELECT count(*)
  FROM {tbl} t
  JOIN products p ON p.id = t.product_id
  JOIN units    u ON u.id = p.unit_id
 WHERE u.allow_fraction = false
   AND t.{col} IS NOT NULL
   AND t.{col} <> trunc(t.{col})
"""

# Darvozadan KEYIN kasr qoldiqda ISHLAMAYDIGAN yo'llar (ega bilishi SHART)
YOPILGAN_YOLLAR = """
  · POST /inventory/writeoff   kasr `qty` bilan            -> 400
  · POST /inventory/transfer   kasr `qty` bilan            -> 400
  · POST /returns              meros kasr sotuv qatori     -> 400
  · POST /lots/enable          kasr JORIY qoldiqda         -> 400 (meros shoxi ham)
  · PATCH /products/{id}       kasr qoldiqda birlik flip   -> 400
  · POST /receiving/{id}/corrections  kasr teskari miqdor  -> 400

  OCHIQ QOLGAN TUZATISH YO'LLARI:
  · POST /inventory/count      BUTUN `counted` bilan       -> 200  (asosiy yo'l)
  · PATCH /purchases/{id}      FAQAT narx (miqdor tegilmagan) -> 200
"""


def _dsn() -> str:
    """`DATABASE_URL`; ichki Railway hosti tashqaridan yechilmasa — TCP proxy'ga ko'chiradi.

    `tools/reconcile_sale_currency.py` dagi AYNI mantiq: `railway run` ichki
    `*.railway.internal` hostini beradi, u esa mahalliy mashinadan yechilmaydi.
    """
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    if not url:
        print("[ABORT] DATABASE_URL env yo'q "
              "(railway run --service Postgres-... bilan ishlating)")
        raise SystemExit(2)
    dom = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN")
    prt = os.environ.get("RAILWAY_TCP_PROXY_PORT")
    if dom and prt and ".railway.internal" in url:
        pr = urllib.parse.urlsplit(url)
        nl = pr.netloc.rsplit("@", 1)
        cred = nl[0] + "@" if len(nl) == 2 else ""
        url = urllib.parse.urlunsplit(pr._replace(netloc=f"{cred}{dom}:{prt}"))
    return url


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Bo'linmas birlikdagi kasr miqdorlar auditi (FAQAT O'QISH)")
    ap.add_argument("--limit", type=int, default=50,
                    help="har jadval uchun ko'rsatiladigan guruh soni (jami SONI to'liq)")
    a = ap.parse_args(argv)

    try:
        import psycopg
    except ImportError:
        print("[ABORT] psycopg yo'q — apps/server/.venv ni ishlating")
        return 2

    print("[rejim] FAQAT O'QISH — `SET TRANSACTION READ ONLY`, `--apply` kaliti YO'Q")
    jami_hammasi = {"A": 0, "B": 0, "C": 0}

    with psycopg.connect(_dsn(), autocommit=False) as cn:
        with cn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")

            cur.execute("SELECT code, allow_fraction FROM units ORDER BY code")
            birliklar = cur.fetchall()
            print("\n[birliklar] " + ", ".join(
                f"{k}={'KASR' if v else 'BUTUN'}" for k, v in birliklar))
            bolinmas = [k for k, v in birliklar if not v]
            if not bolinmas:
                print("[ABORT] bo'linmas birlik YO'Q — audit ma'nosiz")
                return 1

            for tbl, col, sinf, izoh in TEKSHIRUV:
                cur.execute("SELECT 1 FROM information_schema.columns "
                            "WHERE table_name = %s AND column_name = %s", (tbl, col))
                if cur.fetchone() is None:
                    print(f"\n[{sinf}] {tbl}.{col} — ustun YO'Q (o'tkazildi)")
                    continue
                cur.execute(JAMI.format(tbl=tbl, col=col))
                jami = cur.fetchone()[0]
                jami_hammasi[sinf] += jami
                belgi = "OK" if jami == 0 else "!!"
                print(f"\n[{sinf}] {belgi} {tbl}.{col}  ({izoh})  -> {jami} qator")
                if jami == 0:
                    continue
                cur.execute(SQL.format(tbl=tbl, col=col), (a.limit,))
                for tenant, birlik, pid, miqdor, n in cur.fetchall():
                    print(f"        tenant={tenant}  birlik={birlik}  "
                          f"miqdor={miqdor}  qatorlar={n}  product={pid}")

            # ── PROVENANS: kasr qoldiq QAYERDAN keldi ──────────────────────
            #  Ustun `ref_type`/`reason` ni o'qiydi: `product_create` | `import` |
            #  `1c_cutover` | `purchase` | ... — ya'ni QAYSI yozuvchi yozgani.
            #  Bu tuzatish rejasi uchun hal qiluvchi: manba yo'l darvozalanganmi?
            cur.execute("""
                SELECT c.code, m.ref_type, m.reason, count(*), min(m.created_at),
                       max(m.created_at)
                  FROM stock_movements m
                  JOIN products  p ON p.id = m.product_id
                  JOIN units     u ON u.id = p.unit_id
                  JOIN companies c ON c.id = p.company_id
                 WHERE u.allow_fraction = false
                   AND m.qty IS NOT NULL AND m.qty <> trunc(m.qty)
                 GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 20
            """)
            pr = cur.fetchall()
            if pr:
                print("\n[provenans] kasr harakatlar QAYSI yozuvchidan:")
                for code, rt, rsn, n, t0, t1 in pr:
                    print(f"        tenant={code}  ref_type={rt!r}  reason={rsn!r}  "
                          f"n={n}  {t0}..{t1}")

            # ── TUZATISH YO'LINI AJRATISH: tarozi mahsulotimi? ─────────────
            #  Qaror EGA qo'lida, lekin u SIGNALGA tayanishi kerak:
            #    · `is_weighted` yoki `plu_code` BOR  -> mahsulot aslida TAROZI
            #      mahsuloti, birligi XATO berilgan. Tuzatish: birlikni `kg` ga
            #      o'tkazish (kasr qoldiq SHU PAYT yaroqli bo'lib qoladi);
            #    · ikkisi ham YO'Q -> haqiqatan donali tovar, qoldiq buzilgan.
            #      Tuzatish: `/inventory/count` butun `counted` bilan.
            #  Mahsulot NOMI chop ETILMAYDI — faqat UUID va bayroqlar.
            cur.execute("""
                SELECT c.code, i.product_id, i.qty, p.is_weighted,
                       (p.plu_code IS NOT NULL AND p.plu_code <> '') AS plu_bor,
                       u.code
                  FROM inventory i
                  JOIN products  p ON p.id = i.product_id
                  JOIN units     u ON u.id = p.unit_id
                  JOIN companies c ON c.id = p.company_id
                 WHERE u.allow_fraction = false
                   AND i.qty IS NOT NULL AND i.qty <> trunc(i.qty)
                 ORDER BY 1, 3 DESC LIMIT 100
            """)
            rows = cur.fetchall()
            if rows:
                print("\n[tuzatish yo'li] har mahsulot uchun TAVSIYA "
                      "(qaror EGA qo'lida):")
                n_kg = n_count = 0
                for code, pid, qty, weighted, plu, ucode in rows:
                    tarozi = bool(weighted) or bool(plu)
                    if tarozi:
                        n_kg += 1
                        yol = "BIRLIKNI `kg` GA  (tarozi belgisi bor)"
                    else:
                        n_count += 1
                        yol = "`/inventory/count` BUTUN  (tarozi belgisi yo'q)"
                    print(f"        tenant={code}  birlik={ucode}  qty={qty}  "
                          f"is_weighted={bool(weighted)}  plu={bool(plu)}  "
                          f"product={pid}" + "\n            -> " + yol)
                print(f"\n        JAMI TAVSIYA:  birlikni `kg` ga = {n_kg}   "
                      f"sanoq bilan butunga = {n_count}")

        cn.rollback()          # ortiqcha, lekin ANIQ: hech narsa commit qilinmadi

    print("\n" + "=" * 72)
    print(f"JAMI:  A (jonli qoldiq) = {jami_hammasi['A']}   "
          f"B (tarix) = {jami_hammasi['B']}   C (qarz) = {jami_hammasi['C']}")
    if jami_hammasi["A"] == 0:
        print("\nHUKM: JONLI qoldiqda kasr miqdor YO'Q — darvoza hech bir mavjud")
        print("      do'konning tuzatish yo'lini yopmaydi. Tuzatish kerak EMAS.")
    else:
        print("\nHUKM: JONLI qoldiqda kasr miqdor BOR. Quyidagi yo'llar shu")
        print("      mahsulotlar uchun 400 beradi:")
        print(YOPILGAN_YOLLAR)
        print("      TAVSIYA: ega har bir mahsulot uchun QARORNI O'ZI qabul qiladi —")
        print("      (1) `/inventory/count` bilan butun miqdorga keltirish, YOKI")
        print("      (2) mahsulot birligini `kg`/`litr` ga o'tkazish (agar u")
        print("          haqiqatan tarozi mahsuloti bo'lsa — bu HAM tuzatish).")
        print("      AVTOMATIK YAXLITLASH TAQIQ: so'ralgan miqdorni server")
        print("      o'zboshimchalik bilan o'zgartirmaydi.")
    print("\nTARIX (B) QAYTA YOZILMAYDI: sodir bo'lgan hodisa yozuvi shunday qoladi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
