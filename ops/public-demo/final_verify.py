"""CUTOVER'DAN KEYINGI INVARIANT TEKSHIRUVI — production bazasida, FAQAT O'QISH.

python final_verify.py            # konteyner ichida (DATABASE_URL muhitdan)

Tekshiradi:
  1. DEMO tenant importi to'liq (do'kon, filial, kassa hisoblari, xodimlar).
  2. SAFE balansi = IN - OUT (cash ledger), manba bilan solishtirish uchun chop etiladi.
  3. Yopilgan smenalarda farq (`difference`) yig'indisi 0.
  4. Yetim qator YO'Q (chek qatori, kassa harakati, rol).
  5. Qo'shni tenantlar TEGILMAGAN (sanoqlar ko'rsatiladi).
  6. Ommaviy DEMO hisobi: faqat-o'qish belgisi + RAD etilgan ruxsatlar.
  7. Stok invarianti: inventory.qty manfiy emas.
Parol, token yoki shaxsiy ma'lumot CHOP ETILMAYDI.
"""
from __future__ import annotations

import os
import sys

import psycopg

DEMO = "demoprodsm"


def main() -> int:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    c = psycopg.connect(url, options="-c default_transaction_read_only=on -c statement_timeout=120000")
    q = lambda s, a=None: c.execute(s, a).fetchone()          # noqa: E731
    ok = True

    cid = q("select id from companies where code=%s", (DEMO,))
    if not cid:
        print("FAIL: demo tenant YO'Q"); return 1
    cid = cid[0]
    print(f"demo company_id = {cid}")

    rows = {
        "branches": q("select count(*) from branches where company_id=%s", (cid,))[0],
        "employees": q("select count(*) from employees where company_id=%s", (cid,))[0],
        "products": q("select count(*) from products where company_id=%s", (cid,))[0],
        "sales": q("select count(*) from sales where company_id=%s", (cid,))[0],
        "sale_items": q("select count(*) from sale_items si join sales s on s.id=si.sale_id "
                        "where s.company_id=%s", (cid,))[0],
        "shifts": q("select count(*) from shifts where branch_id in "
                    "(select id from branches where company_id=%s)", (cid,))[0],
        "cash_movements": q("select count(*) from cash_movements m join shifts s on s.id=m.shift_id "
                            "where s.branch_id in (select id from branches where company_id=%s)", (cid,))[0],
        "ledger": q("select count(*) from cash.cash_ledger_entries where tenant_id=%s", (cid,))[0],
        "hist_events": q("select count(*) from historical_plan_events where company_id=%s", (cid,))[0],
    }
    print("DEMO qatorlari:", rows)

    safe = q("""select coalesce(sum(case when l.direction='IN' then l.amount else -l.amount end), 0)
                  from cash.cash_ledger_entries l join cash.cash_accounts a on a.id=l.cash_account_id
                 where a.type='SAFE' and a.tenant_id=%s""", (cid,))[0]
    print(f"SAFE balansi = {safe}")

    diff = q("""select coalesce(sum(abs(difference)), 0) from shifts
                 where status='closed' and branch_id in
                       (select id from branches where company_id=%s)""", (cid,))[0]
    print(f"yopilgan smena farqi yig'indisi = {diff}")
    ok &= str(diff) in ("0", "0.00")

    for nom, sql in (
        ("yetim_chek_qatori", "select count(*) from sale_items x left join sales p on p.id=x.sale_id "
                              "where p.id is null"),
        ("yetim_kassa", "select count(*) from cash_movements x left join shifts p on p.id=x.shift_id "
                        "where p.id is null"),
        ("yetim_rol", "select count(*) from employees x left join roles p on p.id=x.role_id "
                      "where p.id is null"),
        ("manfiy_qoldiq", "select count(*) from inventory where qty < 0"),
    ):
        v = q(sql)[0]
        print(f"  {nom:20s} {v}")
        ok &= (v == 0)

    print("qo'shni tenantlar (TEGILMAGAN bo'lishi kerak):")
    for code, n_sales, n_emp in c.execute(
            "select c.code, (select count(*) from sales s where s.company_id=c.id),"
            "       (select count(*) from employees e where e.company_id=c.id)"
            "  from companies c where c.code <> %s order by c.code", (DEMO,)).fetchall():
        print(f"  {code:16s} chek={n_sales:<8d} xodim={n_emp}")

    vid = q("select value->>'employee_id' from settings where company_id=%s and key='public_demo_viewer'",
            (cid,))
    if not vid or not vid[0]:
        print("FAIL: public_demo_viewer belgisi YO'Q"); ok = False
    else:
        n_deny = q("select count(*) from employee_permissions where employee_id=%s and allowed=false",
                   (vid[0],))[0]
        st = q("select status::text, password_hash is not null, deleted_at is null from employees where id=%s",
               (vid[0],))
        print(f"DEMO ko'ruvchi: id={vid[0]} holat={st[0]} parol={st[1]} tirik={st[2]} RAD_ruxsat={n_deny}")
        ok &= (n_deny == 5 and st[0] == "active" and st[1] and st[2])

    c.close()
    print("\nNATIJA:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
