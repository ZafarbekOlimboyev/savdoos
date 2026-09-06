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

All accept `--company-id <uuid>` (per-tenant; omit = all tenants) and `--json`. `cash_preflight`,
`cash_provision`, `cash_backfill`, and `cash_verify` also accept `--mapping <path>` (operator explicit
TILL mapping — see the physical-drawer model below).

## Physical drawer model (TILL / SAFE identity)
**A branch is NOT one TILL.** Each physical checkout / cash drawer is its own **TILL**; a cashier is not a
TILL (cashiers rotate, the drawer stays); each branch usually has one shared **SAFE** (shiftless). TILL
identity = **tenant + branch + physical checkout** (never branch-only). Physical checkouts are detected in
priority order: **OPERATOR_MAPPING > EXISTING (already-provisioned TILLs) > TERMINAL (distinct
`shifts.terminal_id`) > AMBIGUOUS**. "Many cashiers = many TILLs" is **never** assumed — without terminal
evidence or an operator mapping a branch is **AMBIGUOUS** and both provisioning-apply and Phase-1 backfill
**BLOCK** for it. Resolve an AMBIGUOUS branch by supplying `--mapping <path>`:
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
- **EXPECTED RESULT:** `VERDICT: READY` (exit 0). PG readiness ok; the physical-drawer model lists each
  branch's resolved TILL count + SAFE (source TERMINAL / OPERATOR_MAPPING / EXISTING); physical-drawer
  finding **RESOLVED**; no BLOCK.
- **STOP CONDITION:**
  - exit `3` / `VERDICT: BLOCK` → resolve the listed BLOCK findings first: `MULTI_PHYSICAL_DRAWER_UNRESOLVED`
    (a branch's physical drawers can't be determined — supply `--mapping`), `TILL_CURRENCY_UNKNOWN`,
    `OPEN_SHIFT_UNMAPPABLE`, or readiness failure.
  - exit `2` / `VERDICT: REVIEW` → inspect the review findings before proceeding.

## STEP 3b — Confirm the physical TILL mapping (MANDATORY gate before backfill)
- **PRECONDITION:** every active branch reads as **RESOLVED** in STEP 3 — via terminal evidence, an
  already-provisioned TILL, or an operator `--mapping`. No branch may be **AMBIGUOUS**.
- **EXPECTED RESULT:** the operator has explicitly confirmed, per branch, how many physical drawers exist
  and (where used) which `terminal_id` binds to which TILL. Freeze the `--mapping` file if one is used —
  the identical file is required in STEP 5, 8, and 9.
- **STOP CONDITION:** any AMBIGUOUS branch remains → **STOP.** Do not provision or backfill it; produce or
  fix the operator mapping and re-run STEP 3. Never let the tooling guess (no "branch = 1 TILL", no
  "many cashiers = many TILLs").

## STEP 4 — Provision cash accounts (DRY-RUN)
```bash
railway run --service savdoos python -m app.tools.cash_provision --company-id <uuid> [--mapping <path>]
```
- **EXPECTED RESULT:** per branch, the detected physical checkouts (each TILL with its `checkout_code`,
  `terminal`, `source`, `confidence`) + the branch SAFE, then the provision plan (`tills` / `safes` /
  `existing` / `skip_ambiguous`); **nothing written** (`MODE: DRY-RUN`).
- **STOP CONDITION:** any `AMBIGUOUS` branch listed → supply `--mapping` (STEP 3b) before applying.

## STEP 5 — Provision cash accounts (APPLY)
```bash
railway run --service savdoos python -m app.tools.cash_provision --company-id <uuid> --apply [--mapping <path>]
```
- **EXPECTED RESULT:** `THIS WILL WRITE TO cash.cash_accounts …`, then
  `APPLIED: tills_created=… safes_created=… already_existing=…`; `VERDICT: OK` (exit 0). One TILL per
  physical checkout + one SAFE per branch. Re-running is idempotent (`tills_created=0`). **Ledger is not touched.**
- **STOP CONDITION:** exit `3` = refused because AMBIGUOUS branches exist — supply `--mapping`, or (only if
  you deliberately intend to leave those branches unprovisioned) re-run with `--skip-ambiguous`.

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
  - `VERDICT: BLOCK` (exit 3) = NO-GO: BLOCK rows (incl. `MULTI_PHYSICAL_DRAWER_UNRESOLVED` — a branch's
    physical drawer is unresolved; supply `--mapping`) or duplicate business keys — resolve and re-run.
  - `VERDICT: REVIEW` (exit 2) = GO but REVIEW items exist (e.g. an off-shift/branch-level cash op in a
    multi-TILL branch that lacks a terminal → the exact drawer is undecidable) — the operator must
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
