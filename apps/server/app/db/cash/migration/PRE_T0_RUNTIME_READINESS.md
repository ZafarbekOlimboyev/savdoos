# Pre-T0 Current Runtime Readiness

> Historical identity and current runtime readiness are **different questions**.
> A row whose past drawer cannot be proven does **not** stop the cutover.
> A branch with no drawer configured **today** does.

Evaluator: [`runtime_readiness.py`](runtime_readiness.py) — strictly read-only, **per company**.
Companion rules: [HISTORICAL_TILL_RESOLUTION.md](HISTORICAL_TILL_RESOLUTION.md).

---

## 1. Three concepts, never mixed

| Concept | Means | Effect |
|---|---|---|
| `HISTORICAL_TILL_UNKNOWN` | which drawer a **past** row used cannot be proven | REVIEW · row stays outside the ledger · **never a blocker** |
| `CURRENT_BRANCH_NO_ACTIVE_TILL` | the branch has no drawer configured **today** | runtime readiness · blocks *that company's* cutover |
| `POST_T0_NO_ACTIVE_TILL` | after T0, a cash operation without a TILL | runtime **rejects** the operation |

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

Never infer the drawer from cashier, branch or terminal. An untilled open shift makes the company
`CURRENT_RUNTIME_NOT_READY`.

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
4. offline/pending POS writes are synced;
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
