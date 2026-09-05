# Migration Phase 3 — Compare: Findings, Stability Window & Cutover Criteria

Read-only reconciliation tooling. **Legacy remains AUTHORITY; the Cash Ledger remains SHADOW.**
Phase 3 does **not** make the cutover decision, does **not** switch mode, does **not** write anything.

Implementation: `app/services/cash/compare_engine.py` (event matcher, run model, evaluator, findings)
on top of `app/services/cash/shadow_compare.py` (aggregate rollups) and `phase1.plan_backfill`
(expected-event business-key derivation).

---

## §9 — Stability window (configurable; operator policy is separate)

A cutover **candidate** requires `N` consecutive clean comparison / full shift-close cycles with:

- zero **unexplained** monetary delta (`compare_run.unexplained_delta_events == 0`, `absolute_delta ≈ 0`)
- zero **missing** ledger event, zero **extra** ledger event
- zero **duplicate** business key
- no **cross-tenant** mismatch (DB-prevented by FK `cle_acct_currency_fk`; still asserted)
- no hidden PostgreSQL legacy-only cash commit (strict no-fallback — Phase-2 invariant)
- all **critical exceptions** acknowledged/resolved (`exceptions.open_total == 0`)

`evaluate_cutover_readiness(...)` encodes these as machine-readable NOT_READY reasons. `N` is
`DEFAULT_READINESS_CRITERIA["required_clean_cycles"]` (default **14**) and is **configurable** via the
`criteria` argument — the actual production observation **duration** is an **operator policy decision**,
deliberately NOT invented here. Recommended operator policy: at least two full weeks (≈14 daily
shift-close cycles) across all active branches, plus a manual sign-off, before considering cutover.

`evaluate_cutover_readiness` is **READ-ONLY** and **never** sets `LEDGER_PRIMARY` or changes mode.
A non-MATCH `compare_run` always yields NOT_READY (`RUN_NOT_MATCH` catch-all).

---

## §10 — Multi-cashier / one-TILL architectural finding

**Fact.** Legacy allows multiple open shifts per branch (one per cashier: `ux_shifts_cashier_open`).
The cash schema allows **one open shift per TILL** (`sh_one_open_per_account`). Phase 2 handles this
non-destructively (savepoint; legacy never broken) and surfaces the resulting shadow anomaly as a
`compare_till` REVIEW — it is **not hidden**.

**`multi_cashier_till_finding(...)`** analyzes, per branch, whether **concurrent** (overlapping shift
window) different-cashier shifts exist, and whether `Shift.terminal_id` distinguishes drawers:

| Finding | Condition | Meaning | Cutover impact |
|---|---|---|---|
| **A** | no concurrent multi-cashier (single or **sequential**) | current `1 branch = 1 TILL` mapping is **VALID** | none |
| **B** | concurrent, **distinct** `terminal_id` per shift | each terminal is likely a separate physical drawer | **needs additional TILL provisioning** (`1 terminal = 1 TILL`) |
| **C** | concurrent, `terminal_id` null / shared | cannot tell if cashiers share one physical drawer | **production data required** to decide |

**Conclusion.** The decision is **data-dependent** and cannot be finalized without production shift/terminal
data. Findings **B** and **C** **BLOCK cutover readiness** (not Phase-3 tooling readiness — the tooling is
complete and correctly surfaces the condition). The ratified schema is **NOT** changed automatically.
Recommended remediation before cutover: for **B**, provision one TILL per terminal and re-map open shifts;
for **C**, obtain production terminal/drawer data and re-classify (likely → A or B).

---

## §11 — 1C historical sales import policy

`reports.py` bulk-imports historical 1C sales as `Sale` + cash `SalePayment` rows with a past `sold_at`
and **no** `shift_id`. It calls **no** dual-write hook, so it creates **no** `NORMAL` ledger leg
(regression-tested: `test_1c_import_policy_and_no_normal_leg`).

**Classification (`import_1c_policy()`): `HISTORICAL_BACKFILL_TERRITORY`, `live_dual_write = False`.**

- An imported sale with `sold_at < T0` → belongs to **Phase-1 backfill** (RECONSTRUCTION), not live cash.
- An imported sale with `sold_at >= T0` should **not** occur (imports are historical); if wiring is ever
  added, it **must** block `sold_at >= T0` so an operator cannot accidentally create live NORMAL cash
  during dual-write.
- The import path must **never** call `on_cash_sale` / any retrofit hook while in shadow/dual-write mode.

Reconciliation treats these as historical: with a proper T0, `reconcile_events` classifies them under
`< T0` (backfill-expected) and does **not** report them as `MISSING_LEDGER` live events.

---

## Production prerequisites (before cutover — out of scope for this task)

1. Phase-1 historical backfill **executed** in production (operator: verified backup + restore rehearsal,
   operator-selected T0, migration-owner access).
2. Production dual-write enabled (`DUAL_WRITE_SHADOW`) and observed for the stability window (§9).
3. Multi-cashier/TILL finding resolved to **A** for every active branch (§10).
4. All critical cash exceptions acknowledged/resolved.
5. `evaluate_cutover_readiness(...)` returns **READY** across the full tenant scope for `N` consecutive cycles.

Only then may an operator (not this tooling) perform cutover (`LEDGER_PRIMARY`) — a later phase.

---

## Performance note (§15)

`reconcile_events` is **tenant-scoped** (the natural production unit): one query for the tenant's ledger
legs, one for its accounts (no N+1), plus `phase1.plan_backfill`'s legacy-source enumeration. This is
`O(tenant history)`. For very large tenants, run per-tenant and bound the monetary comparison with the
aggregate `shadow_compare(t0=...)` window; a bounded event-window for `reconcile_events` is a documented
follow-up enhancement (not required for controlled observation). The `cle_uq_business` unique index backs
business-key lookups; no production index changes are made by this task.
