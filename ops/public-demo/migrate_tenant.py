"""DEMO TENANTNI asosiy bazaga KO'CHIRISH — FAQAT INSERT.

python migrate_tenant.py --src <dsn> --dst <dsn> --manifest out.json [--apply]

Dizayn qoidalari (P0 preflight):
  * MANBA bazada BITTA tenant bor (`companies` = 1), demak har qator demo tenantga tegishli —
    qator filtri kerak emas.
  * UMUMIY KATALOG (`permissions`, `roles`, `role_permissions`, `units`, `plans`,
    `platform_admins`) KO'CHIRILMAYDI: nishonda allaqachon bor (`initdb` har bootda
    idempotent ta'minlaydi). Ularning ID'lari bazaga xos, shu bois manbadagi FK'lar
    KOD bo'yicha nishon ID'siga qayta yoziladi.
  * FAQAT INSERT: hech qanday UPDATE/DELETE. Mavjud tenantlar qatorlariga TEGILMAYDI.
  * Jadval tartibi FK grafidan (topologik) hisoblanadi — qo'lda ro'yxat yo'q.
  * `--apply` berilmasa hech narsa yozilmaydi (reja + to'qnashuv tekshiruvi).
  * Yozilgan har PK manifest'ga tushadi -> `rollback_tenant.py` AYNAN shularni o'chiradi.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import psycopg
from psycopg.types.json import Json, Jsonb

#: Nishonda allaqachon mavjud, ko'chirilMAYDIGAN umumiy katalog.
CATALOG = {
    "public.permissions": "code",
    "public.roles": "code",
    "public.units": "code",
    "public.plans": "code",
}
#: Umuman ko'chirilmaydigan jadvallar (hosila yoki efemer).
SKIP = {
    "public.role_permissions",      # katalogdan hosila (nishonda rollar uchun bor)
    "public.platform_admins",       # platforma darajasi, tenantga tegishli emas
    "public.auth_sessions",         # efemer sessiyalar
    "public.vendor_sessions", "public.vendor_auth_attempts",
    "public.auth_attempts",
    "public.sync_log", "public.sync_cursors", "public.device_tokens",
    "public.import_jobs", "public.import_rows",
    "public.print_jobs",
    "public.audit_log", "public.audit_logs", "public.admin_audit_log",
    "public.activity_events",
}


def q(cur, sql, args=None):
    cur.execute(sql, args or ())
    return cur.fetchall()


def tables(cur) -> list[str]:
    return [f"{s}.{t}" for s, t in q(cur, """
        select table_schema, table_name from information_schema.tables
         where table_schema in ('public','cash') and table_type='BASE TABLE'
         order by table_schema, table_name""")]


def fks(cur) -> list[tuple[str, str, str, str]]:
    """(child, child_col, parent, parent_col) — barcha FK'lar."""
    return [(f"{r[0]}.{r[1]}", r[2], f"{r[3]}.{r[4]}", r[5]) for r in q(cur, """
        select ns.nspname, cl.relname, att.attname, fns.nspname, fcl.relname, fatt.attname
          from pg_constraint c
          join pg_class cl on cl.oid = c.conrelid
          join pg_namespace ns on ns.oid = cl.relnamespace
          join pg_class fcl on fcl.oid = c.confrelid
          join pg_namespace fns on fns.oid = fcl.relnamespace
          join unnest(c.conkey) with ordinality k(attnum, ord) on true
          join unnest(c.confkey) with ordinality fk(attnum, ord) on fk.ord = k.ord
          join pg_attribute att on att.attrelid = cl.oid and att.attnum = k.attnum
          join pg_attribute fatt on fatt.attrelid = fcl.oid and fatt.attnum = fk.attnum
         where c.contype = 'f' and ns.nspname in ('public','cash')""")]


def topo(names: list[str], edges: list[tuple[str, str, str, str]]) -> list[str]:
    """Ota jadval BIRINCHI. O'z-o'ziga va tsiklga chidamli (qolganlari oxirida)."""
    dep = defaultdict(set)
    for child, _cc, parent, _pc in edges:
        if child != parent and child in names and parent in names:
            dep[child].add(parent)
    out, seen = [], set()
    while len(out) < len(names):
        wave = [n for n in names if n not in seen and not (dep[n] - seen)]
        if not wave:                      # tsikl — qolganini tartibsiz qo'shamiz
            wave = [n for n in names if n not in seen]
        for n in wave:
            out.append(n); seen.add(n)
    return out


def cols(cur, t: str) -> list[str]:
    s, n = t.split(".")
    return [r[0] for r in q(cur, """
        select column_name from information_schema.columns
         where table_schema=%s and table_name=%s order by ordinal_position""", (s, n))]


def jsoncols(cur, t: str) -> dict[str, str]:
    """JSON/JSONB ustunlari — psycopg uchun aniq adapter kerak (dict xom holda ketmaydi)."""
    s, n = t.split(".")
    return {r[0]: r[1] for r in q(cur, """
        select column_name, data_type from information_schema.columns
         where table_schema=%s and table_name=%s and data_type in ('json','jsonb')""", (s, n))}


def pk(cur, t: str) -> list[str]:
    s, n = t.split(".")
    r = q(cur, """
        select att.attname from pg_constraint c
          join pg_class cl on cl.oid=c.conrelid join pg_namespace ns on ns.oid=cl.relnamespace
          join unnest(c.conkey) k(attnum) on true
          join pg_attribute att on att.attrelid=cl.oid and att.attnum=k.attnum
         where c.contype='p' and ns.nspname=%s and cl.relname=%s""", (s, n))
    return [x[0] for x in r]


def catalog_map(src, dst) -> dict[str, dict]:
    """Katalog jadvallari uchun {jadval: {manba_id: nishon_id}} — KOD bo'yicha."""
    out: dict[str, dict] = {}
    with src.cursor() as sc, dst.cursor() as dc:
        for t, key in CATALOG.items():
            s, n = t.split(".")
            if not q(sc, "select 1 from information_schema.tables where table_schema=%s and table_name=%s", (s, n)):
                continue
            a = dict((r[1], r[0]) for r in q(sc, f"select id, {key} from {t}"))     # kod -> manba id
            b = dict((r[1], r[0]) for r in q(dc, f"select id, {key} from {t}"))     # kod -> nishon id
            yoq = sorted(set(a) - set(b))
            if yoq:
                raise SystemExit(f"TO'XTADI: {t} da nishonda yo'q kodlar: {yoq} "
                                 f"(nishonni ayni commit bilan boot qiling)")
            out[t] = {a[k]: b[k] for k in a}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True)
    ap.add_argument("--manifest", required=True); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch", type=int, default=5000)
    #  ⚠️  ESKIRGAN MANBANI IMPORT QILMASLIK KAFOLATI: cutover suratida o'lchangan
    #      qiymatlar MAJBURIY beriladi; manba mos kelmasa import BOSHLANMAYDI.
    ap.add_argument("--expect-sales", type=int, help="manbadagi chek soni (surat)")
    ap.add_argument("--expect-collections", type=int, help="manbadagi inkassa soni (surat)")
    ap.add_argument("--expect-safe", help="manbadagi SAFE balansi (surat, masalan 77371.00)")
    a = ap.parse_args()

    src = psycopg.connect(a.src)
    #  ⚠️  AUTOCOMMIT: aks holda `catalog_map` dagi o'qish implicit tranzaksiya ochadi va
    #      keyingi `dst.transaction()` SAVEPOINT bo'lib qoladi -> commit bo'lmaydi (klonda o'lchandi).
    dst = psycopg.connect(a.dst, autocommit=True)
    src.read_only = True
    with src.cursor() as sc:
        n_comp = q(sc, "select count(*) from companies")[0][0]
        if n_comp != 1:
            raise SystemExit(f"TO'XTADI: manbada {n_comp} kompaniya (1 bo'lishi SHART)")
        comp = q(sc, "select id, code from companies")[0]
        names = [t for t in tables(sc)]
        edges = fks(sc)
    print(f"manba tenant: {comp[1]} ({comp[0]})")
    with src.cursor() as sc:
        got = {"sales": q(sc, "select count(*) from sales")[0][0],
               "collections": q(sc, "select count(*) from cash_movements where type='collection'")[0][0],
               "safe": str(q(sc, """select coalesce(sum(case when l.direction='IN' then l.amount
                                      else -l.amount end), 0) from cash.cash_ledger_entries l
                                      join cash.cash_accounts a on a.id = l.cash_account_id
                                     where a.type = 'SAFE'""")[0][0])}
    print("manba surati:", got)
    for k, want in (("sales", a.expect_sales), ("collections", a.expect_collections),
                    ("safe", a.expect_safe)):
        if want is None:
            raise SystemExit(f"TO'XTADI: --expect-{k} MAJBURIY (eskirgan manba gardi)")
        if str(got[k]) != str(want):
            raise SystemExit(f"TO'XTADI: manba {k}={got[k]} != kutilgan {want} — "
                             f"ESKIRGAN yoki noto'g'ri manba")

    cmap = catalog_map(src, dst)
    print("katalog xaritasi:", {k.split('.')[1]: len(v) for k, v in cmap.items()})

    #  Katalogga ishoraydigan FK ustunlari: (jadval, ustun) -> katalog jadvali
    ref: dict[tuple[str, str], str] = {}
    for child, cc, parent, _pc in edges:
        if parent in CATALOG:
            ref[(child, cc)] = parent

    order = [t for t in topo(names, edges) if t not in SKIP and t not in CATALOG]
    manifest: dict[str, list] = {"tenant": {"company_id": str(comp[0]), "code": comp[1]},
                                 "order": order, "rows": {}}
    total = 0
    with src.cursor(name="cur_src") as _probe:
        pass
    try:
        with dst.transaction():
            with dst.cursor() as dc:
                dc.execute("set local statement_timeout = '600s'")
                for t in order:
                    with src.cursor() as sc:
                        tc = cols(sc, t)
                        jc = jsoncols(sc, t)
                        n = q(sc, f"select count(*) from {t}")[0][0]
                    if not n:
                        continue
                    tpk = pk(dst.cursor(), t) if False else None
                    with dst.cursor() as pc:
                        tpk = pk(pc, t)
                    #  To'qnashuv tekshiruvi: PK bo'yicha mavjud qator BO'LMASIN.
                    if tpk:
                        with src.cursor() as sc:
                            ids = [r for r in q(sc, f"select {','.join(tpk)} from {t}")]
                        #  Postgres parametr chegarasi 65535 -> bo'laklab tekshiramiz.
                        step = max(1, 20000 // len(tpk))
                        dup = 0
                        for i in range(0, len(ids), step):
                            ch = ids[i:i + step]
                            ph = ",".join(["(" + ",".join(["%s"] * len(tpk)) + ")"] * len(ch))
                            flat = [x for row in ch for x in row]
                            dc.execute(f"select count(*) from {t} where ({','.join(tpk)}) in ({ph})", flat)
                            dup += dc.fetchone()[0]
                        if dup:
                            raise SystemExit(f"TO'XTADI: {t} da {dup} PK TO'QNASHUVI — import qilinmaydi")
                    remap = {c: ref[(t, c)] for c in tc if (t, c) in ref}
                    inserted = []
                    with src.cursor(name=f"c_{t.replace('.', '_')}") as sc:
                        sc.itersize = a.batch
                        sc.execute(f"select {','.join(tc)} from {t}")
                        ins = (f"insert into {t} ({','.join(tc)}) values ("
                               + ",".join(["%s"] * len(tc)) + ")")
                        buf = []
                        for row in sc:
                            r = list(row)
                            for c, cat in remap.items():
                                i = tc.index(c)
                                if r[i] is not None:
                                    r[i] = cmap[cat].get(r[i], r[i])
                            for c, dt in jc.items():
                                i = tc.index(c)
                                if isinstance(r[i], (dict, list)):
                                    r[i] = Jsonb(r[i]) if dt == "jsonb" else Json(r[i])
                            buf.append(r)
                            if tpk:
                                inserted.append([str(row[tc.index(k)]) for k in tpk])
                            if len(buf) >= a.batch:
                                dc.executemany(ins, buf); buf.clear()
                        if buf:
                            dc.executemany(ins, buf)
                    manifest["rows"][t] = {"pk": tpk, "ids": inserted, "count": n}
                    total += n
                    print(f"  {t:42s} {n:>7d}" + (f"  remap={list(remap)}" if remap else ""))
                dc.execute("set constraints all immediate")
                #  ⚠️  COMMIT'DAN OLDIN VALIDATSIYA (ayni tranzaksiyada): biror tekshiruv
                #      yiqilsa butun import ROLLBACK bo'ladi va hech narsa yozilmaydi.
                #      Bu append-only `cash` jadvallari uchun YAGONA toza qaytish nuqtasi.
                checks = [
                    ("cheklar", f"select count(*) from sales where company_id='{comp[0]}'", got["sales"]),
                    ("inkassa", "select count(*) from cash_movements m join shifts s on s.id=m.shift_id "
                                f"where m.type='collection' and s.branch_id in (select id from branches "
                                f"where company_id='{comp[0]}')", got["collections"]),
                    ("SAFE", """select coalesce(sum(case when l.direction='IN' then l.amount
                                  else -l.amount end), 0) from cash.cash_ledger_entries l
                                  join cash.cash_accounts a on a.id=l.cash_account_id
                                 where a.type='SAFE' and a.tenant_id=%(t)s""".replace("%(t)s", f"'{comp[0]}'"),
                     got["safe"]),
                    ("yetim_chek_qatori", "select count(*) from sale_items x left join sales p "
                                          "on p.id=x.sale_id where p.id is null", 0),
                    ("yetim_kassa", "select count(*) from cash_movements x left join shifts p "
                                    "on p.id=x.shift_id where p.id is null", 0),
                    ("yetim_rol", "select count(*) from employees x left join roles p "
                                  "on p.id=x.role_id where p.id is null", 0),
                    ("smena_farqi", f"select coalesce(sum(abs(difference)),0) from shifts "
                                    f"where status='closed' and branch_id in (select id from branches "
                                    f"where company_id='{comp[0]}')", "0.00"),
                ]
                bad = []
                for nm, sql, want in checks:
                    dc.execute(sql)
                    val = dc.fetchone()[0]
                    ok = str(val) == str(want)
                    print(f"  tekshiruv {nm:20s} {val} {'OK' if ok else 'XATO (kutilgan ' + str(want) + ')'}")
                    if not ok:
                        bad.append(nm)
                if bad:
                    raise SystemExit(f"TO'XTADI: commit'dan oldingi validatsiya yiqildi: {bad} — ROLLBACK")
                if not a.apply:
                    raise _DryRun()
    except _DryRun:
        print(f"\nQURUQ YURISH (--apply yo'q): {total} qator rejalashtirildi, HECH NARSA YOZILMADI")
    manifest["total"] = total
    with open(a.manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    print(f"manifest: {a.manifest} ({total} qator)")
    return 0


class _DryRun(Exception):
    pass


if __name__ == "__main__":
    sys.exit(main())
