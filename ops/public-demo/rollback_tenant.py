"""DEMO TENANT importini QAYTARISH — manifest bo'yicha AYNAN yozilgan qatorlar.

python rollback_tenant.py --dst <dsn> --manifest out.json [--apply]

* O'chirish FAQAT manifest'dagi PK'lar bo'yicha — hech qanday `where company_id=...`
  keng filtri yo'q, demak boshqa tenant qatoriga tegish imkoniyati YO'Q.
* Tartib: import tartibining TESKARISI (bola birinchi).
* `--apply` berilmasa faqat sanab chiqadi.
* Bitta tranzaksiya: yoki hammasi, yoki hech narsa.
"""
from __future__ import annotations

import argparse
import json
import sys

import psycopg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dst", required=True); ap.add_argument("--manifest", required=True)
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--batch", type=int, default=5000)
    #  ⚠️  `cash` sxemasining bir qancha jadvallari DB darajasida APPEND-ONLY
    #      (`cash.fn_block_mutation` tutqichi). Import qaytarilishi uchun tutqichlar
    #      SESSIYA darajasida o'chiriladi — buning uchun superuser va OPERATOR ANIQ
    #      ruxsati kerak. Bayroqsiz rollback shu jadvallarda TO'XTAYDI (fail-closed).
    ap.add_argument("--allow-immutable", action="store_true",
                    help="cash append-only tutqichlarini sessiyada o'chirish (superuser)")
    a = ap.parse_args()
    m = json.load(open(a.manifest, encoding="utf-8"))
    order = [t for t in reversed(m["order"]) if t in m["rows"]]
    dst = psycopg.connect(a.dst, autocommit=True)
    total = 0
    with dst.transaction():
        with dst.cursor() as dc:
            dc.execute("set local statement_timeout = '600s'")
            dc.execute("set constraints all deferred")
            if a.allow_immutable:
                #  Faqat SHU sessiyada; manifest PK'laridan tashqari hech narsa o'chmaydi.
                dc.execute("set local session_replication_role = replica")
                print("  DIQQAT: cash append-only tutqichlari SESSIYADA o'chirildi")
            for t in order:
                info = m["rows"][t]
                keys, ids = info["pk"], info["ids"]
                if not keys or not ids:
                    continue
                n = 0
                for i in range(0, len(ids), a.batch):
                    chunk = ids[i:i + a.batch]
                    ph = ",".join(["(" + ",".join(["%s"] * len(keys)) + ")"] * len(chunk))
                    flat = [x for row in chunk for x in row]
                    dc.execute(f"delete from {t} where ({','.join(keys)}) in ({ph})", flat)
                    n += dc.rowcount
                total += n
                print(f"  {t:42s} o'chdi {n:>7d} / manifest {info['count']}")
            if not a.apply:
                raise _DryRun()
    print(f"ROLLBACK BAJARILDI: {total} qator")
    return 0


class _DryRun(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _DryRun:
        print("QURUQ YURISH (--apply yo'q): hech narsa o'chirilmadi")
        sys.exit(0)
