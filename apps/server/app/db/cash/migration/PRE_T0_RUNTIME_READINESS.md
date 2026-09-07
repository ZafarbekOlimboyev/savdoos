# Pre-T0 Current Runtime Readiness

> Historical identity and current runtime readiness are **different questions**.
> A row whose past drawer cannot be proven does **not** stop the cutover.
> A branch with no drawer configured **today** does.

Evaluator: [`runtime_readiness.py`](runtime_readiness.py) — strictly read-only, **per company**.
Operator CLI: `python -m app.tools.cash_runtime_readiness [--json] [--company-id <UUID>]` — no apply mode;
see [CASH_MIGRATION_OPERATOR_CLI.md](CASH_MIGRATION_OPERATOR_CLI.md).
Companion rules: [HISTORICAL_TILL_RESOLUTION.md](HISTORICAL_TILL_RESOLUTION.md).

---

## 1. Three concepts, never mixed

| Concept | Means | Effect |
|---|---|---|
| `HISTORICAL_TILL_UNKNOWN` | which drawer a **past** row used cannot be proven | REVIEW · row stays outside the ledger · **never a blocker** |
| `NO_ACTIVE_TILL` | a **cash-transacting** branch has no drawer configured **today** | runtime readiness · blocks *that company's* cutover |
| post-T0 rejection | after T0, a cash operation without a valid TILL | runtime **rejects** the operation |

> Naming: the blocking code emitted here is `NO_ACTIVE_TILL`. Phase-0/preflight emits a similarly named
> but **different** finding, `CURRENT_BRANCH_NO_ACTIVE_TILL`, which is REVIEW and does **not** block.
> Post-T0 rejection codes live in `cutover_guard.py` (`TILL_REQUIRED_AFTER_CUTOVER`,
> `LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER`), not here.

## 2. Policy for the 28 `HISTORICAL_TILL_UNKNOWN` rows

For these rows no deterministic historical drawer evidence exists, and the operator will **not** supply a
guessed mapping. Therefore:

- they are **skipped** from the authoritative CashLedger — no fake `account_id`, no guessed TILL;
- the **source tables remain the authoritative historical record** for them (nothing is lost or deleted);
- **no attestation is required before T0** — an honest "unknown" is a valid end state;
- they are **not** a cutover blocker, for any company;
- if genuine evidence ever appears (a persisted `till_id`, a shift link, a signed drawer sheet), an exact
  `sources`/`shifts` attestation can be applied later and the rows post idempotently, because the business
  key is deterministic.

Backfill reports them explicitly — `skipped_historical_identity_rows` in the manifest, a
`skipped_hist_identity:` line in `cash_backfill`, and `deferred_historical_identity_*` in `cash_verify` —
so a deliberate skip can never be mistaken for silent success.

## 3. Current TILL provisioning contract

**Admin → Filial sozlamalari → Kassalar → + Yangi kassa** (`POST /tills`, permission `sozlamalar.edit`).

| Field | Required | Note |
|---|---|---|
| `branch_id` | yes | must belong to the company and not be deleted |
| `code` | yes | stable identity within (tenant, branch); no spaces; idempotent — re-posting returns the existing row |
| `currency` | no | falls back to the company currency, then `UZS` |
| `terminal_id` | no | optional binding to a physical checkout; must belong to the same branch |

Rules:

- **A branch has 0..N TILLs.** Zero is a legitimate state — it simply means the branch cannot transact
  physical cash after T0 until a drawer is created.
- Create **only the physical checkouts that actually exist and are in use today**. You do **not** need to
  know the eventual total.
- Adding `TILL-02` later is a plain row insert — **no migration, no DDL, no ledger write**, and it works
  after cutover too.
- Nothing auto-creates a TILL merely because a branch exists; provisioning skips branches whose physical
  drawers are undecidable rather than inventing one.
- ⚠️ Operational caveat: in a branch where clients do **not** send `terminal_id`, adding a **second**
  unbound TILL makes post-T0 shift-open ambiguous for those clients. Bind terminals before running two
  unbound drawers in one branch.

**Creating a TILL today does not resolve any historical row** — see HISTORICAL_TILL_RESOLUTION.md.

## 4. Legacy open shifts — pre-T0 policy

Open legacy shifts carry `till_id = NULL`. If such a shift crosses T0 it keeps accepting cash without a
drawer, so before cutover each one must be **one of**:

- **A. Closed as a legacy shift before T0** — *preferred*. Then open a fresh post-T0 shift on an explicit
  TILL. This is the safest path: it needs no judgement about the past.
- **B. Explicitly attached to a real current TILL** — only when the operator *knows* which physical drawer
  that shift is currently using.

Never infer the drawer from cashier, branch or terminal. An open shift without a usable drawer makes the
company `CURRENT_RUNTIME_NOT_READY`.

**A non-null `till_id` is not enough.** Readiness validates the shift's drawer exactly as
`cutover_guard.require_post_t0_till` does at runtime — it must exist, be `type=TILL`, be `ACTIVE`, and
belong to this tenant *and* this branch. `PATCH /tills` can archive a drawer while a shift is still open on
it, so a shift bound to an `ARCHIVED` (or wrong-branch) drawer would otherwise pass readiness and then be
rejected mid-shift after T0. Each shift reports a `till_state`:
`VALID` · `MISSING` · `NOT_FOUND` · `WRONG_TENANT` · `NOT_A_TILL` · `ARCHIVED` · `WRONG_BRANCH`;
anything but `VALID` counts toward `OPEN_LEGACY_SHIFT_WITHOUT_TILL`.

## 4a. Which branches must have a drawer

Only branches that **actually transact cash** require an ACTIVE TILL. "Transacts cash" is decided by
evidence on that branch, never by assumption. The evidence set covers every physical-cash source that
requires **branch-scoped** custody after T0:

| Source | How it is detected |
|---|---|
| shift open/close, and every cash movement | a `Shift` on the branch (`CashMovement.shift_id` is NOT NULL, so cash ops are covered through it) |
| cash sale | a `Sale` on the branch |
| refund | a `Return` on the branch |
| cash debt payment | a branch-scoped cash `CustomerPayment` |
| **cash purchase / receiving** | a `Purchase` on the branch with no supplier `charge` — the same `_no_charge_exists()` predicate the backfill planner uses, so readiness and the ledger cannot drift apart |
| **purchase return** | a `PurchaseReturn` on the branch whose parent purchase was cash |

Supplier payments are deliberately absent: outside a shift they are recorded with `branch_id = None`, so
they impose no branch-scoped drawer requirement.

⚠️ **A warehouse is not automatically idle.** A branch that receives goods and pays cash for them needs
explicit TILL/SAFE custody after T0 (`resolve_cash_custody` → `require_custody_account` checks the branch
matches), so it is a cash-transacting branch. Only a branch with **none** of the evidence above is reported
as advisory (`idle_branches_without_till`) and does **not** block the cutover.

**SAFE is never required per branch.** ACTIVE SAFE counts are reported (`safe_configuration`) so the operator
can see them, but a missing SAFE is not a blocker — a SAFE is only needed where collection (TILL→SAFE) or
SAFE custody is actually used.

## 4b. Blocker codes

`NO_ACTIVE_TILL` · `OPEN_LEGACY_SHIFT_WITHOUT_TILL` · `REAL_RECONCILIATION_ANOMALY` (INFO /
EXPECTED_LEGACY is not counted) · `SCHEMA_NOT_READY` · `GUARD_NOT_READY`. Reported but **never
auto-blocking and never auto-satisfied**: `OFFLINE_SYNC_CONFIRMATION_REQUIRED` — the system cannot see the
POS devices' pending queues, so it never claims the queue is empty.

## 5. Readiness verdict

`status` is decided **only** by current runtime state; the historical dimension is reported separately in
`historical_identity_status` (`CLEAN` | `HISTORICAL_REVIEW`) and never blocks.

| Situation | `status` |
|---|---|
| historical unknown only, current TILL present, no untilled open shift | `CUTOVER_READY` |
| historical unknown + no current ACTIVE TILL | `CURRENT_RUNTIME_NOT_READY` |
| historical unknown + untilled legacy open shift | `CURRENT_RUNTIME_NOT_READY` |

## 6. Per-company cutover

`cutover_at` lives in `Setting(company_id, branch_id=NULL, key='cash')` and both runtime enforcement sites
read it per company — so **tenants cut over independently**. One company being unready never holds another
back. `runtime_readiness.evaluate()` reports each company separately with its own historical reviews,
active TILLs, legacy open shifts, reconciliation anomalies, ledger state and cutover state.

## 7. Clean-cutover prerequisites (T0 stays UNSET here)

This tooling never sets T0. Before an operator selects one, for the chosen company:

1. the company is explicitly identified (cutover is per-company);
2. its current physical TILL(s) are configured;
3. legacy open shifts are closed, or explicitly resolved to a real TILL;
4. offline/pending POS writes are synced — **operator-confirmed**; no tool can prove the device queues are
   empty, so this stays `OPERATOR_CONFIRMATION_REQUIRED`;
5. cash operations are paused for the cutover instant;
6. backup is taken **and a restore rehearsal verified**;
7. preflight shows no true `BLOCK` (historical REVIEW is not a BLOCK);
8. the cutover timestamp is chosen deliberately, at a quiet instant.

## 8. Post-T0 enforcement (now complete)

All 14 physical-cash entry points are either centrally enforced or explicitly justified as non-cash /
non-runtime — see [T0_CUTOVER_ENFORCEMENT.md](T0_CUTOVER_ENFORCEMENT.md) §5. `cutover_open_shift_gate`
exists and is wired. Shift-less cash (purchase, receiving, purchase-return, purchase-increase, supplier
payment) requires an explicit `cash_account_id` (TILL or SAFE) after T0; nothing is inferred from branch,
cashier or terminal. Closing untilled legacy open shifts before T0 remains the recommended operator path,
which is why such a shift still reports `CURRENT_RUNTIME_NOT_READY` here.
