# PRODUCTION CASH MIGRATION RUNBOOK

Operator procedure for the real Cash Ledger migration. **Legacy stays AUTHORITY** through the whole
runbook. This document performs **no** production write itself; it drives the read-only preflight tooling
(`app/db/cash/migration/preflight.py`) and gates the two explicit operator write-steps (backfill execute,
mode enable). **`LEDGER_PRIMARY` / cutover is NOT part of this runbook** (later phase).

**Never put production credentials in this file.** Every dangerous step uses:
`PRECONDITION → COMMAND/PSEUDOCOMMAND → EXPECTED → STOP CONDITION`.

State machine (`preflight.RunbookState`, forward-only, no skipping):
`RELEASE_IDENTITY → BACKUP_VERIFIED → DISCOVERY_DONE → TILL_MAPPING_DECIDED → T0_SELECTED →
DRY_RUN_APPROVED → BACKFILL_EXECUTED → BACKFILL_VERIFIED → DUAL_WRITE_ENABLED → OBSERVING → CUTOVER_READY`.
`advance()` refuses to skip a stage or to enter a stage whose gate did not pass; `ABORTED` is reachable from
any stage. At **every** stage assert `preflight.assert_ledger_primary_prohibited()["ok"] is True`.

---

## §2 RELEASE IDENTITY / GIT SAFETY  → stage RELEASE_IDENTITY

- **PRECONDITION:** the production deployment is built from a known, tested commit.
- **COMMAND (local, read-only):**
  ```bash
  git status --porcelain        # must be empty (clean)
  git rev-parse HEAD            # record as tested_commit
  git rev-list --count @{u}..HEAD ; git rev-list --count HEAD..@{u}   # both 0 = synced
  ```
  Confirm the deployed image/commit SHA on the server equals `tested_commit`.
- **GATE:** `preflight.git_release_gate({working_tree_clean, tested_commit, deployed_commit, remote_synced})`
- **EXPECTED:** `ok == True`. **Recommendation:** create a release tag `cash-migration-<sha>` and bind the
  migration `run_id` to that SHA (record in the T0 record §6). *(Do not create the tag as part of THIS task.)*
- **STOP CONDITION:** dirty tree, `deployed_commit != tested_commit`, or not synced with remote.

## §3 PRODUCTION BACKUP GATE  → stage BACKUP_VERIFIED

- **PRECONDITION:** a fresh production DB backup/snapshot exists **and a restore rehearsal has run**.
- **PSEUDOCOMMAND:** take snapshot (e.g. managed DB snapshot / `pg_dump`), then **restore it into a scratch
  DB and run basic integrity checks** (row counts, `cash` schema present, a sample tenant balance sane).
  Record `{snapshot_ref, taken_at, operator, checksum, restore_rehearsed=true, verified=true}`.
- **GATE:** `preflight.backup_gate(backup_manifest)` (wraps `phase0.verify_backup`).
- **EXPECTED:** `ok == True`. Backup **existence is not enough — restore must be proven to work.**
- **STOP CONDITION:** any missing field, or `restore_rehearsed`/`verified` not `True` → **STOP** (no rollback point).

## §4 PRODUCTION READ-ONLY DISCOVERY  → stage DISCOVERY_DONE

- **PRECONDITION:** backup verified.
- **COMMAND (read-only):** `preflight.discovery(db, engine, company_id=None)` — runs `phase0.inventory`,
  `phase0.readiness_check` (PG ≥ 13, `cash` schema, roles `cash_posting/app/readonly/admin`, `cash_posting`
  cannot UPDATE/DELETE the ledger, `search_path` not cash-first), `propose_till_mapping`, shadow reconcile,
  and the multi-cashier finding. Review: tenant/branch/terminal/open-shift counts, currencies, cash volumes,
  ambiguous mappings, orphan/negative-historical anomalies, 1C imports.
- **EXPECTED:** `ok == True`; **no ledger write occurs** (assert row counts unchanged).
- **STOP CONDITION:** readiness FAIL, any BLOCK mapping finding, or multi-cashier finding **C**.

## §5 MULTI-CASHIER / TILL PRODUCTION DECISION  → stage TILL_MAPPING_DECIDED

- **COMMAND:** `preflight.till_mapping_decision(db, company_id, terminal_till_provisioned=…)`.
  - **A** (single / **sequential** cashiers — no concurrent overlap): current `1 branch = 1 TILL` mapping is
    **valid** → proceed.
  - **B** (concurrent, distinct `terminal_id`): each terminal is a separate physical drawer → provision
    **one TILL per terminal** (label = physical ref; runtime resolves the TILL by branch — provisioning is a
    migration step, schema unchanged) and re-map open shifts, then pass `terminal_till_provisioned=True`.
  - **C** (concurrent, null/shared terminal): drawer identity is not deterministic → **STOP**; obtain
    production terminal/drawer data and re-classify.
- **EXPECTED:** `ok == True` for A, or B once provisioned. **Never force `1 branch = 1 TILL` without seeing
  production data.**
- **STOP CONDITION:** finding **C**, or **B** not yet provisioned.

## §6 T0 SELECTION PROCEDURE  → stage T0_SELECTED

- **The tooling does NOT choose T0.** The operator picks it. **Ideal T0:** low-traffic window; **all TILL
  shifts closed**; pending offline transactions checked; import jobs stopped; migration operators ready;
  backup verified.
- **COMMAND:** `preflight.t0_record(t0_utc, local_tz, approved_by, git_sha, backup_id, run_id)`.
- **EXPECTED:** `ok == True` (all fields recorded). **Boundary is strict:** `device_occurred_at < T0` →
  RECONSTRUCTION/backfill; `>= T0` → NORMAL/live dual-write.
- **STOP CONDITION:** any required field missing.

## §7 FINAL PRODUCTION DRY-RUN  → stage DRY_RUN_APPROVED

- **PRECONDITION:** T0 selected; backup verified.
- **COMMAND (READ-ONLY):** `preflight.final_dry_run(db, engine, company_id, t0, git_sha, backup_id, run_id,
  acknowledged_reviews=[…])` — runs `phase0.readiness_check` + `backfill.execute_backfill(apply=False)` and
  returns a manifest: `run_id, git_sha, backup_id, T0, tenant_scope, branch/TILL mapping, candidate_rows,
  in_total, out_total, reconstruction_rows, skipped_shadows, REVIEW, BLOCK, duplicates, unresolved account
  mappings, negative historical traces, manifest_hash`.
- **EXPECTED:** `go_no_go == "GO"` **only if `BLOCK == 0`** and readiness ok. **Every REVIEW must be either
  explicitly acknowledged by the operator (`acknowledged_reviews`) or excluded from scope.** **Record the
  `manifest_hash` — the real backfill must match it exactly.**
- **STOP CONDITION:** any BLOCK row, readiness FAIL, or any un-acknowledged REVIEW.

## §8 PHASE 1 REAL BACKFILL EXECUTION  → stage BACKFILL_EXECUTED

- **PRECONDITION:** dry-run approved; run as **migration-owner** role (not the runtime posting role).
- **PSEUDOCOMMAND (the only historical write; append-only, idempotent, resume-safe, batched):**
  `backfill.execute_backfill(db, company_id, t0=<T0>, apply=True, approved_hash=<manifest_hash from §7>)`.
  The `approved_hash` gate **rejects** execution if the recomputed manifest hash differs from the approved
  dry-run (`REJECTED_MANIFEST_MISMATCH`, nothing written). Per batch, record `expected/inserted/
  already_existing/failed/running IN/running OUT`.
- **EXPECTED:** `go_no_go == "GO"`, `failed_rows == 0`, business-key idempotent (rerun inserts 0). Rows are
  RECONSTRUCTION, `< T0` only.
- **STOP CONDITION:** manifest mismatch (rejected), any unexpected schema/data shape, or `failed_rows > 0` → **STOP**.

## §9 POST-BACKFILL VERIFICATION  → stage BACKFILL_VERIFIED

- **PRECONDITION:** backfill executed. **This gate must PASS before DUAL_WRITE_SHADOW is enabled.**
- **COMMAND (READ-ONLY):** `preflight.post_backfill_verification(db, executed_manifest, company_id, t0)`
  (wraps `backfill.verify_backfill` + `reconcile_backfill`). **Mandatory (all must hold):** no duplicate
  business key, tenant isolation, no shadow leg leaked, deterministic ids, row-count parity, IN/OUT parity,
  all-reconstruction metadata, no `>= T0` rows backfilled, `unexplained_delta == 0`.
- **EXPECTED:** `ok == True`.
- **STOP CONDITION:** any mandatory check false → **do NOT enable dual-write**.

## §10 ENABLE DUAL_WRITE_SHADOW  → stage DUAL_WRITE_ENABLED

- **PRECONDITION:** backfill verified (§9).
- **BEFORE (READ-ONLY):** `preflight.dual_write_enable_gate(db, backfill_verified=True, deployed_git_sha,
  expected_git_sha)` — asserts current mode ≠ `LEDGER_PRIMARY`, `ledger_is_authority() == False`, deployed
  SHA matches, and that the target is **`DUAL_WRITE_SHADOW`**.
- **ENABLE (operator config, not the tooling):** set `SAVDOOS_CASH_MODE=DUAL_WRITE_SHADOW` for the runtime.
- **AFTER (smoke):** perform one cash event → confirm the legacy mutation committed **and exactly one
  `NORMAL` ledger leg** exists → `preflight.observation_cycle(...)` / `compare_run` → **delta 0**.
- **EXPECTED:** smoke event mirrors 1:1, delta 0.
- **STOP CONDITION / rollback:** smoke fails → **revert config** to `SAVDOOS_CASH_MODE=LEGACY_ONLY`
  (ledger stops being written; legacy never lost authority). **`LEDGER_PRIMARY` remains absolutely off.**

## §11 PRODUCTION OBSERVATION WINDOW  → stage OBSERVING

- Per **shift-close cycle** (and/or a scheduled repeated run): `preflight.observation_cycle(db, company_id,
  t0, run_id)` → `compare_run` + `reconcile_events` + `operator_report` + `evaluate_cutover_readiness`.
  Persist/report results externally; **accounting data is never mutated**.
- **Track:** signed/absolute/unexplained delta, missing/extra ledger, wrong amount/account/shift, duplicate
  key, OFF_SHIFT, LATE_SYNC, open exceptions, multi-cashier anomalies (via `preflight.alerts_from_run`).

## §12 STABILITY POLICY  (configurable — operator approval required)

- `preflight.stability_policy(**overrides)` — NOT hard-coded. Fields: `minimum_clean_cycles`,
  `minimum_completed_shift_cycles`, `maximum_unexplained_delta = 0`, `maximum_missing_events = 0`,
  `maximum_extra_events = 0`, `maximum_duplicates = 0`, `require_operator_approval = True`.
- **Recommendation (conservative):** ≥ 14 full shift-close cycles across all active branches with zero
  unexplained delta, **plus an explicit operator sign-off**. The actual **duration is an operator policy
  decision** — not invented here.

## §13 ROLLBACK / ABORT MATRIX

`preflight.rollback_matrix()`:
- **A pre-backfill:** no ledger write → simply STOP.
- **B during backfill:** execution STOP (idempotent/resume-safe); written RECONSTRUCTION rows are **immutable**
  → not deleted; resume with the same manifest, or an approved reversal-migration.
- **C after backfill / before dual-write:** dual-write not enabled → legacy authority, ledger shadow; anomaly →
  identify manifest + separate **approved** reversal/corrective migration (**not** a destructive DELETE).
- **D dual-write observation:** revert `SAVDOOS_CASH_MODE=LEGACY_ONLY` → ledger writes stop; legacy never lost
  authority → POS unaffected.
- **E comparison anomaly:** BLOCK cutover; keep observing; **no auto-repair**; root-caused by operator.
- **Invariant:** backfill is append-only/immutable — **"DELETE migrated rows" is NOT a routine rollback**.

## §14 1C IMPORT PRODUCTION GUARD

- `preflight.import_1c_guard(sold_at, t0)`: `sold_at < T0` → historical migration territory (OK). `sold_at
  >= T0` → **must not be silently accepted** as an ordinary import (would create live NORMAL cash) → REVIEW /
  operator decision. The `reports.py` import path calls **no** dual-write hook (creates no NORMAL leg); if
  wiring is ever added it must block `sold_at >= T0` during dual-write.

## §15 OBSERVABILITY / ALERTS

`preflight.alerts_from_run(run)` emits, per condition, `{code, severity, scope, source_reference,
detected_at, operator_action}` for: unexplained delta ≠ 0, missing/extra ledger, duplicate business key,
cross-tenant, `UNEXPECTED_RECONSTRUCTION` (≥ T0), `UNEXPECTED_NORMAL_POST` (< T0), unresolved critical ledger
exception, comparison failure, backfill manifest mismatch. **No auto-repair.**

## §16 PRODUCTION COMMAND CHECKLIST (copy/paste; no credentials)

For each stage: `PRECONDITION → COMMAND/PSEUDOCOMMAND → EXPECTED → STOP CONDITION` as above. Connection
strings/passwords are supplied by the operator's environment, **never written here**. Run every read-only
step first; the only writes are §8 (backfill, migration-owner) and the §10 config change.

## Exact operator inputs still required (Q)

1. Verified **backup manifest** (`snapshot_ref, taken_at, operator, checksum, restore_rehearsed, verified`).
2. **Git/deploy evidence** (`working_tree_clean, tested_commit, deployed_commit, remote_synced`).
3. **Multi-cashier resolution** per branch (A, or B with per-terminal TILL provisioning; C blocks).
4. **T0** (`t0_utc, local_tz, approved_by, git_sha, backup_id, run_id`).
5. **REVIEW acknowledgements** for the dry-run manifest (or scope exclusions).
6. **Migration-owner DB credentials** (operator environment) for the §8 backfill.
7. **Stability policy** values + operator sign-off.
8. Production PostgreSQL access with the deployed SHA confirmed.
