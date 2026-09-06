# Dynamic TILL Lifecycle & Migration Boundary

The number of physical cash drawers (TILLs) in a branch is **not fixed and not known in advance**. It is
**not** a migration/architecture invariant. A branch has **0..N** TILLs; new registers are added, old ones
are deactivated, some run only at peak times — anytime, **without a migration**.

## Core model
- **Branch → 0..N TILL.** A **TILL** is one physical cash drawer / checkout (`cash.cash_accounts`,
  `type=TILL`). A **cashier is never** a TILL — cashiers rotate; the drawer stays. Same cashier: TILL-01
  today, TILL-02 tomorrow — valid.
- **TILL lifecycle is dynamic:** new register → new TILL (`POST /tills`); unused register → **deactivate**
  (`status=ARCHIVED`, never hard-deleted); historical TILLs are kept forever. Adding a TILL later — even
  after cutover — needs **no migration**; existing Sale/Shift/Ledger rows keep their old `till_id`.
- **SAFE:** usually one per branch (shiftless, not a physical checkout, independent of the TILL count);
  the schema/business layer allows 0..N SAFE. Migration/provisioning default = 1 branch → 1 SAFE.
- **Terminal ≠ TILL.** A terminal is a POS device/endpoint; a TILL is a physical cash-custody account. A
  terminal may bind to a TILL (`till_identity` label `terminal=<uuid>`), a TILL may later change terminals,
  and a terminal replacement does **not** alter historical Sale/Shift identity (RC6 snapshots + stable ids).

## What was wrong (removed)
"Physical checkout count UNKNOWN → `MULTI_PHYSICAL_DRAWER_UNRESOLVED` → **global migration BLOCK**" was
wrong: it assumed the drawer count is knowable at migration time. **Removed.** Not knowing how many
registers a branch had historically is **not** a global blocker. It is now:
- `CURRENT_BRANCH_NO_ACTIVE_TILL` — **REVIEW** (a branch has cash history but no provisioned TILL yet;
  operator creates one before it transacts post-T0). Not a BLOCK.
- `OPEN_SHIFT_WITHOUT_TILL` — **REVIEW** at discovery; a **cutover-time** matter, not a global BLOCK.
- The Phase-3 physical-drawer finding is now **informational** (`blocker` is always `False`).
Never assumed: `cashier = till`, `branch = default till`, `#cashiers = #tills`.

## Migration boundary (T0)
- **Before T0** (legacy history): physical TILL identity may be incomplete — `till_id`/`terminal_id` can be
  `NULL` (**HISTORY_UNKNOWN**). This never forces the operator to invent a TILL.
- **After T0** (new authoritative cash runtime): every new physical cash event requires an **exact ACTIVE
  TILL**. T0 is a per-company setting: `Setting(key='cash').value['cutover_at']` (ISO8601); unset → no
  enforcement (backward-compat). Enforcement is runtime + cutover-gate, not a migration-discovery block.

### Post-T0 hard guarantee (runtime, `cash_enabled` only)
After T0, these are **rejected** without an exact resolvable TILL:
- **Open shift** (`/shifts/open`) — no resolvable TILL → 400 "avval kassani yarating/tanlang".
- **Cash sale** (online; offline replay is exempt so no data is lost) — cash payment with no TILL → 400.
- Same guarantee for cash refund / payin / payout / expense / collection (they run inside a shift whose
  `till_id` is required post-T0, so they inherit an exact TILL).

Invariants (tests): `ON_SHIFT` leg → `shift.till_id == ledger.cash_account_id`; cash sale →
`Sale.till_id == ledger.cash_account_id`; refund → `Return.till_id == ledger.cash_account_id`;
card/QR/credit → **no** cash-ledger movement. The ledger's physical-account invariant is never weakened —
a leg is never posted to a guessed or NULL account; an unresolved historical row becomes **REVIEW/skip**.

## Shift → TILL
`branch_id`, `cashier_id` required; `till_id` is the authoritative physical-drawer identity, resolved
server-side from the terminal at open (or None pre-T0/cash-disabled). Validated: TILL ACTIVE, `type=TILL`,
same tenant, same branch. One cashier may use different TILLs on different days/shifts.

## Concurrency
**Default: one active cash-custody shift per TILL at a time** — enforced **post-T0** at the service layer
(a second open shift on the same TILL → 400 "kassa band"). Different TILLs in the same branch → parallel
shifts allowed. **Pre-T0/legacy** keeps the tolerated shared-drawer behavior (dual-write never breaks
legacy; the cash-ledger side is already guarded by `sh_one_open_per_account`). A hard DB uniqueness index
was deliberately **not** added because it would break legacy multi-cashier branches.

## Legacy open shifts at cutover
An old OPEN shift without a TILL cannot continue into the authoritative post-T0 runtime. Safest handling
(no guessing): the operator **closes** the legacy shift before T0, or **assigns an ACTIVE TILL** (opens a
new shift on the chosen drawer). The discovery finding `OPEN_SHIFT_WITHOUT_TILL` (REVIEW) lists them; the
runtime post-T0 open-shift guard prevents an untilled cash shift from continuing.

## Backfill (historical)
Exact TILL evidence (shift/terminal) → post to that TILL. No deterministic evidence → the row is
**REVIEW/skipped** (documented) — never invented, never a global NO-GO. Preserves the ledger physical-
account invariant while never forcing a false TILL. Operator may later create the TILL and re-run.

## TILL admin API (`/tills`)
`GET /tills[?branch_id]` (list all, ACTIVE+ARCHIVED) · `POST /tills` (create: branch, code, terminal?; idempotent
by code) · `PATCH /tills/{id}` (rename `code` — terminal binding preserved, id stable; and/or
`active` true/false = activate/deactivate) · `DELETE /tills/{id}` (**refused** if referenced by any
Sale/Shift/Return/Ledger/CashShift — deactivate instead). Writes require `sozlamalar.edit`. Cash-enabled
(Postgres) only.

## Admin / UX contract
Branch Settings → **Kassalar**: `Kassa 1 ACTIVE / Kassa 2 ACTIVE / Kassa 3 INACTIVE`, button **+ Yangi
kassa**. Admin can create / rename / deactivate / reactivate; **cannot** permanently delete a historically
used TILL. Shift-open UI: **"Kassani tanlang"** — the cashier picks an available physical TILL (or the
device preselects it by terminal). Renaming/deactivating a TILL never changes past receipts (RC6 snapshots
`till_code`/`till_label` at sale time; `till_id` is immutable on the sale).
