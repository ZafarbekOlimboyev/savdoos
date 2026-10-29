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
    #  ⚠️  `session_replication_role=replica` REAL PRODUCTION uchun ISHLATILMAYDI:
    #      u audit va append-only kafolatlarini o'chiradi. Shu bois `cash` sxemasi
    #      qatorlari O'CHIRILMAYDI — ular KARANTIN qilinadi (tenant yetib bo'lmaydi).
    ap.add_argument("--quarantine", action="store_true",
                    help="KARANTIN: do'kon va xodimlarni soft-delete qiladi (cash qatorlari qoladi)")
    a = ap.parse_args()
    m = json.load(open(a.manifest, encoding="utf-8"))
    order = [t for t in reversed(m["order"]) if t in m["rows"]]
    dst = psycopg.connect(a.dst, autocommit=True)
    total = 0
    with dst.transaction():
        with dst.cursor() as dc:
            dc.execute("set local statement_timeout = '600s'")
            dc.execute("set constraints all deferred")
            if a.quarantine:
                cid = m["tenant"]["company_id"]
                dc.execute("update employees set status='terminated', deleted_at=now() "
                           "where company_id=%s and deleted_at is null", (cid,))
                n_emp = dc.rowcount
                dc.execute("update companies set deleted_at=now() where id=%s and deleted_at is null", (cid,))
                print(f"  KARANTIN: do'kon soft-delete, {n_emp} xodim o'chirildi -> login YO'Q")
                if not a.apply:
                    raise _DryRun()
                return 0
            #  ⚠️  MANIFESTDAN TASHQARI QATOR GARDI: DEMO hisobi (va boshqa keyin
            #      qo'shilganlar) manifestda YO'Q. Ularni qoldirib `companies` ni
            #      o'chirish YETIM qator qoldiradi (klonda o'lchandi). Bunda PK-rollback
            #      RAD etiladi — karantin ishlatiladi.
            cid = m["tenant"]["company_id"]
            known = {x[0] for x in (m["rows"].get("public.employees", {}).get("ids") or [])}
            dc.execute("select id::text, full_name from employees where company_id=%s", (cid,))
            extra = [(i, n) for i, n in dc.fetchall() if i not in known]
            if extra:
                raise SystemExit(
                    f"TO'XTADI: manifestda YO'Q {len(extra)} xodim bor ({extra[0][1]!r}...) — "
                    f"PK-rollback yetim qoldiradi. `--quarantine` ishlatilsin.")
            for t in order:
                if t.startswith("cash."):
                    print(f"  {t:42s} O'TKAZILDI (append-only — karantin bilan hal qilinadi)")
                    continue
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
