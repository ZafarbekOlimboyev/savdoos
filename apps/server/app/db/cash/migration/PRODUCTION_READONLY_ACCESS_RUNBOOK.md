# PRODUCTION READ-ONLY ACCESS — Operator Runbook

Purpose: create a **dedicated, role-enforced read-only** database login so the production read-only
preflight (`preflight.discovery`, `phase0.*`, `phase1.*`, `compare_engine.*`) can run **without** the
write-capable Railway app/admin role.

**This runbook does not create the role and does not connect** — it is the operator procedure. Every
dangerous step uses `PRECONDITION → SQL → EXPECTED RESULT → STOP CONDITION`. **No password or connection
string is written here, in git, or in chat** — secrets flow only through Railway's secret/environment store.

Repository facts this is grounded in (`app/db/cash/cash_ddl_v1.sql`):
- `cash_readonly` is a **NOLOGIN group role** (DDL line 515) with `USAGE` (519) + `SELECT ON ALL TABLES`
  (522) on the **`cash` schema only**, plus `ALTER DEFAULT PRIVILEGES … GRANT SELECT … TO cash_readonly`
  (565) so future cash tables auto-grant. It has **no grants on the public/legacy tables**.
- Application roles (`cash_app`, `cash_posting`, `cash_readonly`) get **no DDL powers**; `cash_admin` is an
  admin grant role; the migration owner owns objects. The read-only login must inherit **only** `cash_readonly`.

---

## STEP 0 — Prerequisite: run role DDL as the migration owner (NOT app/admin)

- **PRECONDITION:** the `CREATE ROLE cash_preflight_ro …` statements below are DDL — they must be run by a
  **superuser / DBA / migration-owner** login on the Railway Postgres, once, out of band. Do **not** run
  them from any application role. This is the only step that writes to the cluster (role catalog), and it
  creates **no business data** and touches **no ledger/legacy row**.
- **STOP CONDITION:** if you cannot run role DDL as owner/superuser on `Postgres-d29B`, STOP — request DBA.

## STEP 1 — Create the LOGIN wrapper role `cash_preflight_ro`

- **PRECONDITION:** Step 0 access; a strong password stored **only** in Railway (see STEP 6).
- **SQL** (owner/DBA session):
  ```sql
  -- LOGIN wrapper; INHERITs cash_readonly (cash-schema SELECT). Password comes from Railway secret,
  -- NOT written here. Not a member of cash_app/cash_posting/cash_admin and NOT the migration owner.
  DO $$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cash_preflight_ro') THEN
      CREATE ROLE cash_preflight_ro LOGIN INHERIT PASSWORD '<<SET_VIA_RAILWAY_SECRET>>';
    END IF;
  END $$;

  GRANT cash_readonly TO cash_preflight_ro;          -- cash schema USAGE + SELECT (present + future)
  GRANT USAGE ON SCHEMA public TO cash_preflight_ro; -- needed to reach legacy tables
  ```
- **EXPECTED RESULT:** role exists, `rolcanlogin=t`, `rolsuper=f`, `rolcreatedb=f`, `rolcreaterole=f`.
- **STOP CONDITION:** any error, or the role ends up a member of `cash_posting`/`cash_app`/`cash_admin` or
  owns any object → STOP and drop/fix before continuing.

## STEP 2 — Grant SELECT on ONLY the legacy tables the preflight reads (least privilege)

- **PRECONDITION:** STEP 1 done.
- **SQL:**
  ```sql
  GRANT SELECT ON
    public.companies, public.branches, public.employees, public.employee_branches,
    public.terminals, public.shifts, public.cash_movements,
    public.sales, public.sale_payments, public.returns,
    public.customers, public.customer_payments, public.credit_transactions,
    public.suppliers, public.supplier_payments, public.supplier_ledger,
    public.purchases, public.purchase_returns, public.receivings,
    public.settings
  TO cash_preflight_ro;
  ```
- **EXPECTED RESULT:** SELECT granted on exactly these tables; **no** INSERT/UPDATE/DELETE granted; no other
  public tables exposed. (1C historical import lives in `sales`+`sale_payments` — no separate table.)
- **STOP CONDITION:** a preflight query later fails with `permission denied for table X` → add **SELECT only**
  on X (never a write grant) and re-verify; if X is outside the migration's data model, STOP and review.

## STEP 3 — Role-level read-only enforcement (primary guard)

- **SQL:**
  ```sql
  ALTER ROLE cash_preflight_ro SET default_transaction_read_only = on;
  ```
- **EXPECTED RESULT:** every session opened by this role starts with `transaction_read_only = on`; Postgres
  **rejects** any INSERT/UPDATE/DELETE/DDL at command level (`cannot execute … in a read-only transaction`).
- **STOP CONDITION:** if the setting cannot be pinned on the role, STOP (do not rely on per-query discipline).

## STEP 4 — Connection-level read-only (defense-in-depth, second guard)

- **PRECONDITION:** STEP 3 done.
- **PROCEDURE:** in the read-only connection string, also pass the libpq option so read-only holds even if
  the role default is ever changed:
  ```
  options=-c default_transaction_read_only=on
  ```
  (In a URL: append `?options=-c%20default_transaction_read_only%3Don`.)
- **EXPECTED RESULT:** two independent layers force read-only (role default + connection option).
- **STOP CONDITION:** none — this is additive.

## STEP 5 — Confirm the role has NO write/DDL/admin powers

- **SQL** (owner session, inspect the wrapper):
  ```sql
  SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin
    FROM pg_roles WHERE rolname='cash_preflight_ro';
  SELECT r.rolname AS member_of
    FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
    JOIN pg_roles u ON u.oid=m.member WHERE u.rolname='cash_preflight_ro';
  ```
- **EXPECTED RESULT:** `rolsuper=f, rolcreatedb=f, rolcreaterole=f, rolcanlogin=t`; `member_of` = only
  `cash_readonly` (NOT `cash_posting`/`cash_app`/`cash_admin`).
- **STOP CONDITION:** any elevated attribute or extra membership → STOP and correct.

## STEP 6 — Password / connection string handling (secrets discipline)

- Store the password **only** in Railway's environment/secret store (e.g. a `CASH_READONLY_URL` variable on
  the service): `railway variables set CASH_READONLY_URL=<value>` — run by the operator, value never echoed.
- **NEVER** write the password/connection string in chat, in git, in this runbook, or in any committed file.
- The preflight process reads it from the environment at runtime (like the app reads `DATABASE_URL`).
- **STOP CONDITION:** if a secret would have to be pasted into a file/chat/PR, STOP and use Railway secrets.

## STEP 7 — VERIFY read-only access (run AS `cash_preflight_ro`)

- **PRECONDITION:** connect using the new read-only login (via `railway run psql "$CASH_READONLY_URL"` or the
  Railway-provisioned connection).
- **SQL:**
  ```sql
  SELECT current_user, current_database(), current_setting('transaction_read_only') AS txn_ro;
  SELECT
    has_table_privilege('cash_preflight_ro','public.sales','SELECT')                 AS sales_select,
    has_table_privilege('cash_preflight_ro','public.sales','INSERT')                 AS sales_insert,
    has_table_privilege('cash_preflight_ro','public.sales','UPDATE')                 AS sales_update,
    has_table_privilege('cash_preflight_ro','public.sales','DELETE')                 AS sales_delete,
    has_table_privilege('cash_preflight_ro','cash.cash_ledger_entries','SELECT')     AS ledger_select,
    has_table_privilege('cash_preflight_ro','cash.cash_ledger_entries','INSERT')     AS ledger_insert,
    has_table_privilege('cash_preflight_ro','cash.cash_ledger_entries','UPDATE')     AS ledger_update,
    has_table_privilege('cash_preflight_ro','cash.cash_ledger_entries','DELETE')     AS ledger_delete,
    has_schema_privilege('cash_preflight_ro','cash','USAGE')                         AS cash_usage,
    has_schema_privilege('cash_preflight_ro','public','USAGE')                       AS public_usage,
    has_schema_privilege('cash_preflight_ro','cash','CREATE')                        AS cash_create;
  ```
- **EXPECTED RESULT:** `txn_ro = on`; every `*_select = true` and `cash_usage/public_usage = true`; every
  `*_insert / *_update / *_delete = false`; `cash_create = false`.
- **STOP CONDITION:** `txn_ro` not `on`, any write privilege `true`, `cash_create = true`, or a needed
  `*_select = false` → STOP and fix grants; do **not** run the preflight until this passes.

## STEP 8 — Write-DENIAL proof (safe; never modifies a business row)

- **PRECONDITION:** connected AS `cash_preflight_ro`.
- **SQL** (each write is triple-safe: rejected by read-only; `WHERE false` matches 0 rows even if read-only
  were off; wrapped in `ROLLBACK`):
  ```sql
  BEGIN;
    UPDATE public.companies SET name = name WHERE false;   -- EXPECT: ERROR cannot execute UPDATE in a read-only transaction
  ROLLBACK;

  BEGIN;
    CREATE TEMP TABLE _ro_probe (x int);                    -- EXPECT: ERROR cannot execute CREATE TABLE in a read-only transaction
  ROLLBACK;
  ```
- **EXPECTED RESULT:** BOTH statements raise `ERROR: cannot execute … in a read-only transaction`. No row is
  updated, no object created (also guaranteed by `WHERE false` + `ROLLBACK`).
- **STOP CONDITION:** if any write **succeeds**, the access is NOT read-only → STOP immediately, revoke the
  login, and re-do STEP 3.

## STEP 9 — Re-run the production READ-ONLY preflight under the new access

- **PRECONDITION:** STEPs 7 & 8 PASSED; `CASH_READONLY_URL` in Railway.
- **PROCEDURE:** run the ready, tested preflight tooling against production with the read-only connection
  (no writes, `apply=False` everywhere):
  ```bash
  # operator, read-only connection (writes are impossible for this role):
  railway run --service savdoos python -c "IMPORT AND CALL: \
    preflight.discovery(db, engine, company_id=None); \
    phase0.readiness_check(engine); phase0.inventory(db); \
    compare_engine.multi_cashier_till_finding(db); \
    phase1.reconcile_shadows(db); \
    phase1.plan_backfill(db, t0=None)  # apply=False planner only"
  ```
  (Use a small driver script that opens a Session on `CASH_READONLY_URL` and dumps the JSON reports.) Nothing
  provisions, deploys, backfills, or changes mode; `provision_accounts`/`execute_backfill` are **not** called.
- **EXPECTED RESULT:** the preflight report (Sections A–N of `PRODUCTION_CASH_MIGRATION_RUNBOOK.md` §4) is
  produced; the read-only role makes any accidental write impossible.
- **STOP CONDITION:** any `permission denied` → add SELECT-only on that table (STEP 2); any write attempt is
  rejected (expected, proves safety).

## STEP 10 — Decommission after preflight (optional hygiene)

- After the migration observation window, the operator may drop the login:
  `DROP ROLE cash_preflight_ro;` (run as owner). It owns no objects, so drop is clean.

---

## Guarantees this design provides

1. **Role-enforced read-only** (`ALTER ROLE … SET default_transaction_read_only = on`) — Postgres rejects
   all writes at command level; not discipline-based. Plus a connection-level second guard (STEP 4).
2. **Least privilege** — SELECT only, on exactly the cash-schema (via `cash_readonly`) + the enumerated
   legacy tables; **no** INSERT/UPDATE/DELETE, **no** DDL, **not** a member of any writer/admin role, **not**
   the migration owner.
3. **No secrets in code/chat/git** — password/connection string live only in Railway.
4. **Verifiable** — STEP 7 (privilege matrix) + STEP 8 (write-denial) prove read-only before any preflight query.

## Exact next operator actions
1. As owner/DBA on `Postgres-d29B`: run STEPs 1–3 (create role, grant SELECT, pin read-only).
2. Store the read-only connection string in Railway (STEP 6).
3. Connect AS the role; run STEP 7 + STEP 8 — confirm `txn_ro=on`, SELECT=true, writes=false, write-denial errors.
4. Run STEP 9 — the production read-only preflight — and return the reports.
