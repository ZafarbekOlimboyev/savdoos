# Cash Ledger · Migration Phase 0 — Prepare & Production Readiness

**Scope:** preparation only. No historical backfill, no reader cutover, no legacy-table deletion.
All tooling here is READ-ONLY analysis + a REPORT-ONLY dry-run + idempotent provisioning **plan**.
Only `CashPostingService` ever writes `cash.cash_ledger_entries` (never this toolkit).

Toolkit: [`phase0.py`](phase0.py). Tests: `tests/cash/test_migration_phase0.py` (15, real PostgreSQL).

---

## A. Current-state (repository) findings
- **Tenant = company** (`public.companies`, UUID PK). **Branch** = `public.branches` (company_id, is_active).
- **No explicit physical-till entity in legacy.** Cash is tracked **per shift**: `shifts.opening_cash` +
  `cash_movements` (payin/payout/expense/collection). A shift binds `branch_id` + **nullable** `terminal_id`
  + `cashier_id`. `terminals` is a POS-device list, not a drawer.
- **Runtime already assumes one TILL per branch** — the Phase 2b retrofit resolves a branch's single TILL
  (`resolve_till(tenant, branch_id, "TILL")`). This settles the canonical mapping.
- **No app-level CashAccount provisioning** exists — the retrofit *resolves* an existing TILL and **no-ops**
  when a branch is unmapped. Provisioning is therefore a migration step (idempotent; `provision_accounts`).
- **cash schema** deploys via `deploy_cash_schema` (Postgres-only, idempotent, single txn) and **resets
  `search_path`** so `cash` never leaks into the pooled connection (the previously-found bug).
- Roles already separate concerns (DDL §P / CF-D6): `cash_posting` (sole ledger writer), `cash_app`
  (read), `cash_readonly` (reports), `cash_admin` (grant, **not** owner). **Migration owner** = the DDL
  executor; app roles get no DDL. `cash_posting` is REVOKEd UPDATE/DELETE on the immutable ledger.

## B. CashAccount mapping design (§03/§08)
- **TILL:** one per active branch. `cash_accounts.branch_id` **is** the mapping key (no runtime-schema
  change); `label` carries the physical identity ref (`BRANCH:<code>`). Currency = the company currency.
- **SAFE:** absent from legacy → optional, provisioned on operator request; no historical SAFE data.
- **Ambiguity — never guessed:** a branch whose shifts used **>1 distinct terminal** is `AMBIGUOUS`
  (shared drawer vs per-terminal — legacy cannot tell) → a `TILL_AMBIGUOUS` **BLOCK** and the branch is
  **skipped** by provisioning until an operator resolves it (usually one shared TILL).
- **Mapping artifact:** the JSON produced by `dry_run(...)["till_mappings"]` + the provisioned
  `cash_accounts` rows themselves. No new table, no runtime-schema mutation.
- **Provisioning is idempotent:** existing TILL → `exists` (never a duplicate); ambiguous → `skip`.
  `tenant_id` is always the branch's company (cross-tenant leak impossible).

## C. Open-shift mapping (§04)
`map_open_shifts` lists every `status=open` legacy shift → tenant, branch, cashier, legacy_shift_id,
inferred till (`BRANCH:<code>`), proposed CashAccount, opened_at, opening_cash, status. An open shift in
an **ambiguous** branch is **blocked** (`OPEN_SHIFT_UNMAPPABLE`, BLOCK) — the branch's migration halts;
**no fake shift is created**.

## D. Data-quality audit (§10) — classify, never repair
Categories (each BLOCK/REVIEW): `NEG_OPENING_CASH` (BLOCK), `NEG_COUNTED_CASH` (REVIEW),
`ORPHAN_CASH_MOVEMENT` (BLOCK), `SHIFT_NO_BRANCH` (BLOCK), `CLOSED_SHIFT_UNCOUNTED` (REVIEW),
`CURRENCY_INVALID` (BLOCK). Phase 0 **does not** mutate business data.

## E. Reconstruction inventory (§11) — `provenance = RECONSTRUCTION`
- **Historical cash-at-creation purchases** — a purchase settled in cash **at creation** (drawer
  decreased, no ledger OUT — the §07 gap) → backfill `OUT·PURCHASE_OUT` (RECONSTRUCTION). Identified by
  `_cash_at_creation_filter()`: `status = received` **AND no `SupplierLedger` charge** — because
  `received` alone is not a cash signal (`pay_supplier` flips a fully-paid **debt** purchase to `received`
  regardless of method). This mirrors the runtime `not _charged` gate, so a debt/bank/credit purchase is
  **never** invented as a cash outflow, and a cash-settled debt purchase (its cash is `OUT·SUPPLIER_OUT`)
  is **not** double-counted. Amount from the row, never invented.
- **Open-shift opening floats** — reconstructed as `IN·OPENING` at T0.
Reconstruction is an **approved** mechanism; a non-zero count is **not** a blocker.

## F. Dry-run design (§12)
`dry_run(db, company_id=None)` → report only, `wrote_ledger: False` (proven by
`test_dry_run_writes_no_ledger`). Computes: inventory; till mappings + ambiguous set; open-shift mappings
+ blocked; reconstruction candidates; expected ledger projection; expected rows; expected IN/OUT/net;
invalid rows; findings; metrics; GO/NO-GO. **Deterministic** on repeat (`test_dry_run_deterministic`).
Per-tenant scoping via `company_id`.

**Projection mirrors the runtime — no double-count.** Legacy double-records: a cash refund /
supplier-payment / debt-payment writes its source row **and** a shadow `CashMovement`
(`payout`/`payin`). The runtime posts from the source rows and omits `payout` (and never re-posts the
debt-payment `payin`) via `_CASHOP_MAP`. So the projection counts: `IN·OPENING`, `IN·SALE` (cash
`sale_payments`), `OUT·REFUND` (cash `returns`), `OUT·PURCHASE_OUT` (cash-at-creation purchases, §E),
`OUT·SUPPLIER_OUT` (cash `supplier_payments`), `IN·DEBT_IN` (cash `customer_payments`), plus the
**unambiguous** manual movements `expense → EXPENSE` and `collection → CASH_OUT`. The `payin`/`payout`
movements — indistinguishable in aggregate from their source shadows — are **excluded from the headline
totals** and reported separately as `ambiguous_movements` with an `AMBIGUOUS_CASH_MOVEMENTS` (REVIEW)
finding; **Phase 1 backfill** row-source-traces them (by `client_uuid`/reason) to split genuine manual
cash-ops from payment/refund shadows before posting.

## G. Production runbook (operator sequence)
```
PREPARE
 1. Backup:  pg_dump (or provider snapshot) of production.
 2. Verify restore: restore into a scratch instance; record snapshot_ref, checksum, taken_at, operator.
                    -> phase0.verify_backup(manifest) MUST return ok=True (restore_rehearsed & verified).
 3. Deploy cash schema (idempotent):  python -c "from app.db.cash.deploy import deploy_cash_schema; ..."
                    -> or initdb (_deploy_cash). Requires the migration-owner role (CREATEROLE for §P).
 4. Readiness:  phase0.readiness_check(engine)  -> ok=True (pg>=13, cash schema, roles, ledger immutable,
                    search_path not cash-first).
 5. Inventory:  phase0.inventory(db)            -> per-tenant/branch counts (RUN AGAINST PROD; not fabricated).
 6. Map TILL/SAFE:  phase0.propose_till_mapping(db)  -> resolve every AMBIGUOUS branch with the operator.
 7. Map open shifts:  phase0.map_open_shifts(db) -> every open shift mapped OR its branch is blocked.
 8. Select T0 (see §06 procedure below) — do NOT invent it here.
 9. Dry-run:  phase0.dry_run(db)  (per-tenant)  -> archive the report (JSON).
GO / NO-GO  (phase0.evaluate_go_no_go — §13): GO only when blocking == [].
NEXT PHASE (only after PASS):  Phase 1 — Shadow / Backfill.
  Phase-1 pre-provisioning (once, on the clean prod DB, BEFORE apply=True):
    phase0.ensure_provisioning_unique_index(db)   # 1 ACTIVE account per (tenant,branch,type)
    phase0.provision_accounts(db, mappings, apply=True)   # idempotent; ambiguous branches skipped
```

### §06 T0 (historical cutoff) — selection procedure (not a value)
T0 is chosen by production, not invented here. Procedure: pick a low-traffic instant at which **all TILL
shifts are closed** (or a coordinated freeze). Data with `device_occurred_at < T0` = historical (Phase 1
backfill, RECONSTRUCTION where cash evidence is inferred); `>= T0` = live dual-write. An open shift
spanning T0 → close-and-reopen at T0, opening float reconstructed at T0. Offline events sync-classified by
`device_occurred_at` vs T0 (a `< T0` event synced later = LATE_SYNC / RECONSTRUCTION per the contract's
Case C). Dual-write is already active (Phase 2b); T0 only bounds where *backfill* stops and *live* begins.

## H. Tests (§16) — 15, real PostgreSQL
`tests/cash/test_migration_phase0.py`: mapping idempotency; duplicate-mapping detection; missing till
identity; multiple tills (ambiguous); shared-drawer resolution; open-shift mapping; ambiguous-shift
blocked; currency mismatch; tenant isolation (no cross-tenant leak); reconstruction detection; backup
verification; PostgreSQL compatibility; search_path reset; dry-run writes no ledger; dry-run deterministic.
Run: `pytest tests/cash/test_migration_phase0.py`.

## I. §15 Rollback (preparation is non-destructive)
Phase 0 changes no business data. On any failure: **stop**, do not mutate business data, fix
mapping/configuration, re-run preparation. The only writes Phase 0 can make are idempotent CashAccount
rows via `provision_accounts(apply=True)` — and provisioning is deferred to Phase 1; in Phase 0 it runs
as a **plan** (`apply=False`). If provisioning was applied early and must be undone before any ledger
exists, the migration owner may delete the un-referenced `cash_accounts` rows (no ledger references them
yet). The verified backup (step 2) is the ultimate rollback point.

## §17 Security
- **Migration owner ≠ runtime posting role** (CF-D6): DDL objects are owned by the executor; `cash_posting`
  is the sole *runtime* writer and is REVOKEd UPDATE/DELETE on the immutable ledger (verified by
  `readiness_check.posting_cannot_mutate_ledger`). App roles receive no DDL.
- **Least privilege:** reporting = `cash_readonly` (SELECT only); app = `cash_app` (SELECT).
- **No runtime mutation of immutable history:** privilege REVOKEs + `fn_block_mutation`/`fn_block_truncate`
  triggers (defense in depth).
- **Artifacts:** dry-run/inventory JSON carry ids + counts + amounts only — no credentials, no PII beyond
  existing identifiers. `.env` is never read by the toolkit.

## §18 Observability (metrics, no arbitrary thresholds)
`observability_metrics(report)` → `mapped_accounts`, `unmapped_accounts`, `ambiguous_mappings`,
`open_shift_mapping_failures`, `reconstruction_candidates`, `blocking_anomalies`, `dry_run_duration_ms`,
`dry_run_failures`. Thresholds are policy set by the operator against real dry-run output — none baked in.

## §13 GO / NO-GO
- **BLOCK (NO-GO):** ambiguous TILL, tenant mismatch, currency mismatch/invalid, impossible source ref,
  unexplained duplicate, unmappable open shift, orphan cash movement, branch-less shift, negative opening.
- **REVIEW (not blocking):** reconstruction candidates, timestamp uncertainty, missing legacy cash
  movement, SAFE history without a physical count.
- Reconstruction is approved — **zero reconstruction is not required**.
