# CASH MIGRATION — Operator CLI Runbook

Thin, safe CLI drivers the operator runs from the **Railway terminal** (`railway run --service savdoos …`).
They wrap the already-tested Phase 0/1/2/3 tooling (`phase0` / `phase1` / `backfill` / `compare_engine`
/ `preflight` / `mode`). **They add no business logic** — only argument parsing, output, and exit codes.

## Safety invariants (every CLI, enforced in `app/tools/_common.py`)
- **No secrets printed.** `TARGET DB` shows only `current_database()` — never host/user/password/URL.
  `DATABASE_URL` is shown as `true`/`false` only; its value is never read into output.
- **LEDGER_PRIMARY is never enabled and the mode is never changed** (`set_mode` is not called; no
  `SAVDOOS_CASH_ALLOW_PRIMARY` write). Every CLI **refuses to run** if the environment is already
  `LEDGER_PRIMARY` (`guard_never_primary`).
- **No `DELETE` / `UPDATE` / `TRUNCATE` / `DROP`.** Ledger writes are **append-only** (`ON CONFLICT DO
  NOTHING`, deterministic uuid5 ids) and happen **only** with `--apply`. Default is always dry-run/read-only.
- Every write CLI prints a **`THIS WILL WRITE …`** banner before applying, and requires explicit flags
  (no interactive prompt).

## Exit codes (shared contract)
`0` = READY / clean / MATCH / PASS · `1` = usage error · `2` = REVIEW (non-blocking; operator inspects)
· `3` = BLOCK / REJECTED / FAIL (do not proceed).

## Modules
| CLI | Writes? | Purpose |
|---|---|---|
| `python -m app.tools.cash_preflight` | no (read-only) | PG readiness, inventory, TILL A/B/C finding, currency, BLOCK/REVIEW |
| `python -m app.tools.cash_provision` | cash_accounts only (with `--apply`) | Idempotent TILL/SAFE provisioning; **no ledger write** |
| `python -m app.tools.cash_backfill`  | ledger (with `--apply --approved-hash`) | Historical `< T0` RECONSTRUCTION legs |
| `python -m app.tools.cash_verify`    | no (read-only) | Dual-write gate #9 (verify + reconcile, all mandatory PASS) |
| `python -m app.tools.cash_compare`   | no (read-only) | Phase-3 compare + cutover readiness (evaluator only) |
| `python -m app.tools.cash_discover`  | no (read-only) | Physical-checkout discovery + operator mapping skeleton |
| `python -m app.tools.cash_t0_probe`  | **strictly** read-only | Pre-backfill ledger state + T0 boundary probe (see below) |
| `python -m app.tools.cash_reconcile_probe` | **strictly** read-only | Row-level audit of the `RECONCILE_*_SHADOW` reviews (see below) |
| `python -m app.tools.cash_runtime_readiness` | **strictly** read-only | Per-company pre-T0 runtime readiness — explicit blocker codes (see below) |

### Running the read-only probes from Windows — use `ssh`, NOT `run`
`railway run` executes locally with prod env vars injected, but the Railway **internal** Postgres hostname
(`Postgres-d29B`) does **not resolve from a Windows workstation**, so `railway run … python …` fails to
connect. Run read-only inspection **inside the container** over SSH instead:
```bat
railway.cmd ssh --service savdoos -- python -m app.tools.cash_t0_probe --json
```
`cash_t0_probe` opens a session, runs only `SELECT`s + `reconcile_shadows`, then **rolls back and closes** —
no INSERT/UPDATE/DELETE/DDL, no `cutover_at` SET, no mode change, no `LEDGER_PRIMARY`, no secrets printed.
Its JSON reports: cutover state, ledger inventory (rows, device/recorded min-max, posting_kind/source_type/
provenance counts, with/without shift, earliest NORMAL, RECONSTRUCTION rows, prior-backfill YES/NO), cash-
account inventory (ACTIVE/ARCHIVED TILL + SAFE per branch), open legacy shifts (HAS_TILL / LEGACY_UNKNOWN +
cash activity), reconciliation reviews, and a T0 candidate evaluation (`PROVABLE` only on a clean
`recon < T0 ≤ runtime` boundary; otherwise `NOT_PROVABLE_*` / `T0_NOT_DETERMINED` — it never SETs T0).

### Interpreting the `RECONCILE_*_SHADOW` reviews — `cash_reconcile_probe`
The `reconcile_shadows` check compares the count of **shadow** `CashMovement`s (the extra `payin`/`payout`
the legacy runtime writes for cash debt-payments / refunds / supplier-payments, reason-prefixed, `client_uuid`
NULL) against the count of the **source** rows (`CustomerPayment` / `Return` / `SupplierPayment`). A shadow is
written **only inside an open shift** (`customers.pay_credit`, `purchases.pay_supplier`, `sales` refund are all
`if open_shift:`) and **only after** the shadow-writing code was deployed. So legacy cash payments made
off-shift or before that deploy have **no shadow** — this is **normal, not data loss**: backfill reconstructs
those legs from the **source table** (`CustomerPayment→DEBT_IN`, `Return→REFUND`, `SupplierPayment→SUPPLIER_OUT`),
and because there is no shadow there is nothing to double-count. `reconcile_shadows` therefore now classifies
`shadow < source` as **INFO / EXPECTED_LEGACY** (not REVIEW); it stays **REVIEW** only for `shadow > source`
(excess/orphan shadow with no matching source — a genuine inconsistency).

`cash_reconcile_probe` proves this **row by row** (no personal fields — no names/phones, no customer/supplier/
employee ids; only technical id, amount, timestamp, method, branch, shift):
```bat
railway.cmd ssh --service savdoos -- python -m app.tools.cash_reconcile_probe --json
```
Per source row it reports shadow presence, ledger presence, backfill **eligibility + which historical
evidence rule resolved it** (via the real `backfill.resolve_account`, **never a guessed TILL**), and a
classification: `EXPECTED_LEGACY_NO_SHADOW` (the false-positive case — historical drawer evidence exists),
`SHADOW_PRESENT`, `HISTORICAL_TILL_UNKNOWN`, or `DATA_INCONSISTENCY`. Verdict: `EXPECTED_LEGACY_CLEAN`
(exit 0); `HISTORICAL_TILL_UNKNOWN` (exit 2); `REVIEW_REQUIRED` (exit 2) = orphan shadow or ledger
mismatch. It rolls back and closes; no writes, no `cutover_at` SET, no mode change.

> **`HISTORICAL_TILL_UNKNOWN` is NOT fixed by provisioning a TILL.** Creating a drawer today is not
> evidence about the past — `CURRENT TILL PROVISIONING != HISTORICAL TILL EVIDENCE`. Those rows need
> deterministic historical evidence or an explicit operator attestation
> (`--historical-till-map`, a **different document** from `--mapping`); until then they stay outside the
> authoritative ledger, which does **not** block the T0-forward migration. The separate runtime concern
> ("this branch has no ACTIVE TILL today") is reported on its own as `current_till_provisioned`.
> Full rules: **HISTORICAL_TILL_RESOLUTION.md**.

All accept `--company-id <uuid>` (per-tenant; omit = all tenants) and `--json`. `cash_preflight`,
`cash_provision`, `cash_backfill`, and `cash_verify` also accept `--mapping <path>` (operator explicit
TILL mapping — see the physical-drawer model below).

## Physical drawer model (TILL / SAFE identity)
**A branch is NOT one TILL.** Each physical checkout / cash drawer is its own **TILL**; a cashier is not a
TILL (cashiers rotate, the drawer stays); each branch usually has one shared **SAFE** (shiftless). TILL
identity = **tenant + branch + physical checkout** (never branch-only). The TILL count is **dynamic**
(branch 0..N TILL, added/deactivated any time — see DYNAMIC_TILL_LIFECYCLE.md). Physical checkouts are
detected in priority order: **OPERATOR_MAPPING > EXISTING (already-provisioned TILLs) > TERMINAL (distinct
`shifts.terminal_id`) > (no current TILL)**. "Many cashiers = many TILLs" is **never** assumed — without
terminal evidence or an operator mapping a branch has **no current TILL**: it is **not** a migration
blocker (finding `CURRENT_BRANCH_NO_ACTIVE_TILL`, REVIEW); provisioning **skips** it and backfill routes its
historical legs to **REVIEW** (never a guessed TILL). Such a branch simply needs at least one ACTIVE TILL
before it transacts cash **after T0** (runtime-enforced). Provision a branch's drawers with `--mapping <path>`
(or `POST /tills`):
```json
{ "branches": { "<branch_uuid>": { "safe": true, "tills": [
  { "code": "TILL-01", "terminal_id": "<uuid-or-null>", "label": "Kassa 1" },
  { "code": "TILL-02", "terminal_id": "<uuid-or-null>", "label": "Kassa 2" } ] } } }
```
Physical identity is stored in `cash_accounts.label` (the ratified schema is unchanged): `TILL code=<checkout_code>
terminal=<uuid|NONE>` / `SAFE code=SAFE`. Provisioning is idempotent by that identity. The SAME operator
`--mapping` file MUST be passed to `cash_provision`, `cash_backfill`, and `cash_verify` (identical resolution).

---

## STEP 1 — Release identity (out of band, no CLI)
- **PRECONDITION:** working tree clean; the commit deployed to Railway == the tested commit; remote synced.
- **EXPECTED RESULT:** you have written down the exact deployed git SHA (used in later gate evidence).
- **STOP CONDITION:** deployed SHA ≠ tested SHA, or tree dirty → redeploy the tested commit first.

## STEP 2 — Backup + restore rehearsal (out of band, no CLI)
- **PRECONDITION:** a verified DB snapshot exists **and** a restore has been rehearsed.
- **EXPECTED RESULT:** a backup manifest (`snapshot_ref`, `taken_at`, `operator`, `checksum`,
  `restore_rehearsed=true`, `verified=true`).
- **STOP CONDITION:** no verified/rehearsed backup → **STOP.** There is no rollback point; do not continue.

## STEP 3 — Read-only preflight discovery
```bash
railway run --service savdoos python -m app.tools.cash_preflight
# per-tenant: add  --company-id <uuid> ; with a draft mapping: add  --mapping <path>
```
- **EXPECTED RESULT:** `VERDICT: READY` (exit 0), or `VERDICT: REVIEW` (exit 2) when some branches have no
  provisioned TILL yet. The physical-drawer model lists each branch's resolved TILL count + SAFE; the
  physical-drawer finding is **informational** (never a global blocker — see DYNAMIC_TILL_LIFECYCLE.md).
- **STOP CONDITION:**
  - exit `3` / `VERDICT: BLOCK` → genuine blockers only: `TILL_CURRENCY_UNKNOWN` (company currency invalid)
    or readiness failure. **`CURRENT_BRANCH_NO_ACTIVE_TILL` and `OPEN_SHIFT_WITHOUT_TILL` are REVIEW, not
    BLOCK** — the TILL count is dynamic, so unknown/未-provisioned drawers do NOT stop the migration.
  - exit `2` / `VERDICT: REVIEW` → informational; a branch has cash history but no ACTIVE TILL yet. You do
    not need to resolve every branch to migrate — only branches that will transact cash **after T0** need
    at least one ACTIVE TILL (create it via `/tills` or STEP 5, any time — even after cutover).

## STEP 3b — Physical TILL readiness (per-branch, only for branches going live at T0)
- **DYNAMIC TILL:** the drawer count is **not** fixed and need **not** be discovered up front. There is no
  "all drawers must be known before migration" gate.
- **EXPECTED RESULT:** for each branch you intend to run cash on **from T0 onward**, at least one **ACTIVE
  TILL** exists — from terminal evidence, an already-provisioned TILL, or created explicitly (operator
  `--mapping` in STEP 5, or `POST /tills`). Branches with no current TILL simply cannot open a cash shift
  post-T0 until one is created (enforced at runtime) — they do not block the migration.
- **STOP CONDITION:** none globally. Never let the tooling guess (no "branch = 1 TILL", no "many cashiers =
  many TILLs"). An **open** legacy shift without a TILL must be **closed or re-opened on an ACTIVE TILL**
  before it can continue past T0 (see DYNAMIC_TILL_LIFECYCLE.md → "Legacy open shifts at cutover").

## STEP 4 — Provision cash accounts (DRY-RUN)
```bash
railway run --service savdoos python -m app.tools.cash_provision --company-id <uuid> [--mapping <path>]
```
- **EXPECTED RESULT:** per branch, the detected physical checkouts (each TILL with its `checkout_code`,
  `terminal`, `source`, `confidence`) + the branch SAFE, then the provision plan (`tills` / `safes` /
  `existing` / `skip_ambiguous`); **nothing written** (`MODE: DRY-RUN`).
- **STOP CONDITION:** none. An `AMBIGUOUS` branch (no current TILL) is simply **skipped** (it does not block
  the others). Supply `--mapping` **only** if you want to provision that branch's drawers now — you can also
  add them later via `POST /tills`.

## STEP 5 — Provision cash accounts (APPLY)
```bash
railway run --service savdoos python -m app.tools.cash_provision --company-id <uuid> --apply [--mapping <path>]
```
- **EXPECTED RESULT:** `THIS WILL WRITE TO cash.cash_accounts …`, then
  `APPLIED: tills_created=… safes_created=… already_existing=…`. `VERDICT: OK`, or `VERDICT: REVIEW` (exit 2)
  when some branches still have no current TILL (skipped, informational). Resolvable branches are
  provisioned; **AMBIGUOUS branches are skipped, not refused** (dynamic TILL — add them any time). One TILL
  per physical checkout + one SAFE per branch. Re-running is idempotent. **Ledger is not touched.**
- **STOP CONDITION:** none from ambiguity. `--skip-ambiguous` is now a no-op (skipping is the default).

## STEP 6 — Select T0 (operator decision, no CLI)
- **PRECONDITION:** low-traffic instant; **all TILL shifts closed**; offline/pending synced; 1C import
  paused; backup verified (STEP 2); operators ready.
- **EXPECTED RESULT:** a single ISO-8601 UTC timestamp `T0`. Boundary is strict: `< T0` → RECONSTRUCTION
  backfill; `>= T0` → live dual-write.
- **STOP CONDITION:** any TILL shift still open at T0 → its legs go to REVIEW; close it first or re-pick T0.

## STEP 7 — Backfill DRY-RUN (capture the approved hash)
```bash
railway run --service savdoos python -m app.tools.cash_backfill --company-id <uuid> --t0 <T0-ISO> [--mapping <path>]
```
- **PRECONDITION:** STEP 3b passed — no AMBIGUOUS branch (else the plan is NO-GO). Pass the SAME
  `--mapping` used in STEP 5, if any.
- **EXPECTED RESULT:** candidate/IN/OUT/reconstructed/skipped counts, `GO/NO-GO: GO`, and a
  **`MANIFEST HASH: <hash>`**. Copy that hash. **Nothing written.**
- **STOP CONDITION:**
  - `VERDICT: BLOCK` (exit 3) = NO-GO: genuine BLOCK rows (e.g. duplicate business keys, structural
    anomalies) — resolve and re-run. A branch with **no current TILL is NOT a blocker** (dynamic TILL): its
    historical legs go to **REVIEW** and are skipped (never a guessed TILL), and `GO/NO-GO` stays GO.
  - `VERDICT: REVIEW` (exit 2) = GO but REVIEW items exist (e.g. a branch with no current TILL, or an
    off-shift/branch-level cash op in a multi-TILL branch that lacks a terminal → the exact drawer is
    undecidable, so that leg is skipped) — the operator must
    inspect/accept them before applying.

## STEP 8 — Backfill APPLY (hash-gated, idempotent)
```bash
railway run --service savdoos python -m app.tools.cash_backfill \
  --company-id <uuid> --t0 <T0-ISO> --apply --approved-hash <hash-from-STEP-7> [--mapping <path>]
```
- **EXPECTED RESULT:** `THIS WILL WRITE TO THE CASH MIGRATION TABLES`, then
  `inserted_rows=… already_existing=… failed=0`, `GO/NO-GO: GO` → `VERDICT: GO` (exit 0). Re-running with
  the same hash is idempotent (`inserted_rows: 0`).
- **STOP CONDITION:**
  - `REJECTED_MANIFEST_MISMATCH` (exit 3): the data/T0/scope changed since STEP 7 — **nothing was
    written.** Re-run STEP 7 to get a fresh hash, then re-apply.
  - `--apply` without `--approved-hash` → exit 1, nothing written (by design).
  - `failed_rows > 0` (exit 3) → inspect the failed rows before continuing.

## STEP 9 — Verify backfill (mandatory before dual-write)
```bash
railway run --service savdoos python -m app.tools.cash_verify --company-id <uuid> --t0 <T0-ISO> [--mapping <path>]
```
- **PRECONDITION:** pass the SAME `--mapping` used for the backfill (STEP 8) — the verify manifest is
  recomputed and must resolve to the identical physical TILLs.
- **EXPECTED RESULT:** every mandatory check `PASS` (no duplicate keys, tenant isolation, no shadow leg
  leaked, deterministic ids, row-count + IN/OUT parity, all-RECONSTRUCTION metadata, no `>= T0` backfilled,
  unexplained delta 0) → `VERDICT: PASS` (exit 0). Read-only.
- **STOP CONDITION:** exit `3` / `VERDICT: FAIL` → **do NOT enable dual-write.** Fix the failing check
  (from the backup, re-run backfill) and re-verify.

## STEP 10 — Enable DUAL_WRITE_SHADOW (operator config, no CLI here)
- **PRECONDITION:** STEP 9 PASS. Confirm the deployed git SHA still equals the tested SHA (STEP 1).
- **PROCEDURE:** ensure the service runs with `SAVDOOS_CASH_MODE=DUAL_WRITE_SHADOW` (this is the default;
  set it explicitly if it was ever `LEGACY_ONLY`) and redeploy. **Never** set `LEDGER_PRIMARY` or
  `SAVDOOS_CASH_ALLOW_PRIMARY`.
- **EXPECTED RESULT:** legacy remains the sole authority; each new cash event writes exactly one NORMAL
  ledger leg (shadow). A smoke event → legacy mutation + exactly 1 NORMAL leg → next compare delta 0.
- **STOP CONDITION:** smoke event produces ≠1 NORMAL leg, or `cash_compare` immediately shows mismatch →
  revert the mode config and investigate before continuing.

## STEP 11 — Observation cycles (one per shift close, read-only)
```bash
railway run --service savdoos python -m app.tools.cash_compare \
  --company-id <uuid> --t0 <T0-ISO> --report
```
- **EXPECTED RESULT:** `VERDICT: MATCH` (exit 0) each cycle — netting is disabled (absolute delta), so
  offsetting errors cannot hide. Record each clean cycle; run once per completed shift cycle across all
  active TILLs.
- **STOP CONDITION:**
  - `VERDICT: REVIEW` (exit 2) → a divergence/exception exists (`MISSING_LEDGER`, `EXTRA_LEDGER`,
    `WRONG_*`, open exceptions). Investigate; the clean-cycle counter resets.
  - `VERDICT: BLOCK` (exit 3) → unexplained/tenant mismatch or aggregate BLOCK — **STOP**, investigate.

## STEP 12 — Cutover readiness (evaluator only, read-only)
```bash
railway run --service savdoos python -m app.tools.cash_compare \
  --company-id <uuid> --t0 <T0-ISO> --clean-cycles <N>
```
- **EXPECTED RESULT:** `CUTOVER READINESS: READY` once `N` ≥ the policy's required clean cycles (default
  14, operator-configurable) **and** the run is MATCH with zero unexplained delta / open exceptions. This
  is an **evaluator** — it does **not** perform cutover and does **not** set `LEDGER_PRIMARY`.
- **STOP CONDITION:** `NOT_READY` → the printed reason codes list what is missing (e.g.
  `INSUFFICIENT_OBSERVATION_CYCLES`, `RUN_NOT_MATCH`, `OPEN_EXCEPTIONS`). Continue observing.

## STEP 13 — Cutover to LEDGER_PRIMARY — **OUT OF SCOPE for these CLIs**
- Cutover (making the ledger authoritative) is a **later phase / operator decision**, gated by an explicit
  second flag (`SAVDOOS_CASH_ALLOW_PRIMARY=1`) and its own runbook. **None of these CLIs perform it**, and
  they **refuse** to run against a `LEDGER_PRIMARY` environment. Do not proceed here.

---

## Rollback
Backfill is append-only + idempotent (deterministic uuid5 business keys). If a step fails:
1. **Stay in DUAL_WRITE_SHADOW / LEGACY_ONLY** — legacy is still the source of truth; readers are unaffected.
2. Restore from the STEP 2 backup if ledger rows must be removed (these CLIs never delete).
3. Re-run STEP 3 (preflight) and STEP 7 (dry-run) to regenerate a clean plan + fresh approved hash.

### Per-company runtime readiness — `cash_runtime_readiness`
A reusable operator shell over [`runtime_readiness.py`](runtime_readiness.py). **There is no apply mode** —
the `--apply` flag does not exist in this CLI. It opens a session, runs only `SELECT`s, then rolls back and
closes; it never sets `cutover_at`, creates a TILL/SAFE, opens or closes a shift, changes the cash mode,
writes to the ledger, prints a secret, or prints customer personal data.

```bat
railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness
railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness --json
railway.cmd ssh --service savdoos -- python -m app.tools.cash_runtime_readiness --company-id <UUID> --json
```

**Per company it reports:** final status (only `CUTOVER_READY` or `CURRENT_RUNTIME_NOT_READY`), per branch
the ACTIVE **TILL** and ACTIVE **SAFE** counts plus whether the branch actually transacts cash, the
cash-transacting branch list, open legacy shifts (total / with TILL / without TILL, each listed by
`shift_id`, `branch_id`, `opened_at`, `till_id` — technical identifiers only), the historical-identity
review count, the offline-sync barrier, `schema_ready`, and post-T0 guard availability.

**Blocker codes (§3) — never a vague "REVIEW":**

| Code | Meaning |
|---|---|
| `NO_ACTIVE_TILL` | a **cash-transacting** branch has no ACTIVE TILL today |
| `OPEN_LEGACY_SHIFT_WITHOUT_TILL` | an open legacy shift would cross T0 without a usable drawer — `till_id = NULL`, or a `till_id` that is `ARCHIVED` / wrong-branch / wrong-tenant / missing (each shift reports its `till_state`) |
| `REAL_RECONCILIATION_ANOMALY` | a genuine mismatch (excess/orphan shadow) — `INFO / EXPECTED_LEGACY` is not counted |
| `SCHEMA_NOT_READY` | the `cash` schema is not deployed (Postgres) |
| `GUARD_NOT_READY` | the central post-T0 guard is missing/unimportable |
| `OFFLINE_SYNC_CONFIRMATION_REQUIRED` | operator confirmation — **reported, never auto-satisfied** |

**A branch with no cash activity does not block.** "Cash-transacting" is evidence-based: a shift (which also
covers every cash movement), a sale, a return, a branch-scoped cash customer payment, a **cash purchase /
receiving**, or a **purchase return**. A branch with none of those is reported as advisory
(`idle_branches_without_till`), not as a blocker. Note that a warehouse that pays cash for goods it receives
**is** cash-transacting and does need a drawer — see PRE_T0_RUNTIME_READINESS.md §4a.

**SAFE is never required per branch.** `safe_configuration` reports ACTIVE SAFE counts so the operator can
see them, but a missing SAFE is not a blocker — a SAFE is needed only where collection (TILL→SAFE) or SAFE
custody is actually used.

**Historical identity is never mixed with TILL provisioning.** `historical_identity_status` is reported
separately with `blocking: false`, and the tool never suggests creating a TILL "to fix history" — creating a
drawer today only enables post-T0 runtime. See [HISTORICAL_TILL_RESOLUTION.md](HISTORICAL_TILL_RESOLUTION.md).

**The offline device queue is never claimed to be empty.** `cutover_decision.device_queue` stays
`NOT_VERIFIABLE_BY_TOOL` / `OPERATOR_CONFIRMATION_REQUIRED`, alongside the other operator confirmations
(cash paused, backup + restore rehearsal, deliberate T0 instant). `cutover_decision.tool_verified` lists each
tool-checkable condition as `PASS`/`FAIL` with the failing companies — it never claims a failed check passed.

Exit: `0` = every evaluated company is `CUTOVER_READY` · `2` = at least one is `CURRENT_RUNTIME_NOT_READY`
· `1` = usage (bad `--company-id`, or no such company). **T0 remains an operator decision — this tool never
sets it.**
