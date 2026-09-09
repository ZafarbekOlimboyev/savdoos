# Fresh Production Launch — day-one cash for a new merchant

> **Read this file alone.** You do not need RC1–RC13 history, the migration runbooks, or any
> backfill document to onboard a new merchant. Everything the fresh path needs is here.

There are exactly **two** paths through the cash system, and they never mix:

| | **FRESH (ledger-native)** | **LEGACY (migration)** |
|---|---|---|
| Who | a merchant created **after** the ledger architecture shipped | a tenant that already had cash history |
| Cash history | none, by definition | may exist, drawer identity may be unprovable |
| Backfill | **never** | required (`cash_backfill`) |
| Historical TILL reconstruction | **never** | evidence-based, may end `UNKNOWN` |
| T0 ceremony | **none** — T0 is the onboarding instant | a deliberate, planned cutover |
| Migration tooling | **irrelevant** | `cash_discover`, `cash_provision`, `cash_runtime_readiness`, `cash_till_plan`, `cash_backfill`, `cash_verify` |

Everything below is the **FRESH** path. If you are migrating an existing tenant, stop here and read
[migration/PRE_T0_RUNTIME_READINESS.md](migration/PRE_T0_RUNTIME_READINESS.md) instead.

---

## 1. What makes a tenant "fresh" — explicit state, never inference

At company creation, [`admin.provision`](../../api/v1/admin.py) calls
[`cash.tenant.mark_ledger_native`](../../services/cash/tenant.py), which writes one Setting row:

```json
Setting(company_id, branch_id=NULL, key="cash").value = {
  "ledger_native": true,
  "onboarded_at":  "2026-09-07T12:00:00+00:00",
  "cutover_at":    "2026-09-07T12:00:00+00:00"
}
```

- `ledger_native: true` is the **tenant type**. It is written once, by server code only — the
  settings API rejects the `cash` key, so a tenant cannot forge it.
- `cutover_at = onboarded_at` makes every post-T0 guard active **from the first minute**. For a
  fresh tenant this crosses no history, because there is none.

**Why not infer the type?** An empty legacy tenant also has zero rows, so transaction counts cannot
distinguish the two. `company.created_at` is a timestamp compared against a rollout date — brittle
across restores and re-provisioning. `CASH_MODE` is a process-global env var with no per-tenant
resolution at all. Only an explicit flag says the thing that matters: *this tenant has no legacy
cash history.*

`is_ledger_native(db, company_id)` is the single read point.

## 2. Onboarding states

Derived from observable data — no separate state machine to drift out of sync
(`cash.tenant.onboarding_state`, served by `GET /api/v1/cash-setup`):

| State | Meaning | POS can open a cash shift? |
|---|---|---|
| `COMPANY_CREATED` | company exists, no active branch | no |
| `CASH_SETUP_REQUIRED` | a branch has **0 ACTIVE TILL** | **no** — blocked cleanly |
| `POS_READY` | every branch has ≥1 ACTIVE TILL | yes |

No placeholder TILL is ever auto-created.

## 3. Cash setup (Manager → Kassalar)

The merchant answers exactly one question per branch:

> **How many REAL physical checkout drawers does this branch have TODAY?**

Create one TILL per real drawer — `TILL-01`, `TILL-02`, … A branch may have **0..N** TILLs. The
count is **never** inferred from terminals, cashiers, history, branch count, or a "one TILL"
fallback.

The Manager screen (`packages/shared/src/screens/Kassalar.tsx`) shows only merchant-facing concepts.
It deliberately never displays T0, cutover, backfill, `historical_till_unknown`, shadow comparison
or migration hashes — those belong to operator tooling.

**SAFE is optional.** The screen asks *"Do you take money from the till to a safe?"* If no, no SAFE
is created. If yes, `POST /api/v1/safes` creates one explicitly. A branch is **0..N TILL, 0..N SAFE**.
Without a SAFE, collection (TILL→SAFE) is unavailable — and the server refuses it rather than
posting a one-legged OUT that would make cash disappear.

## 4. Day one, in order

1. Vendor provisions the company → branch `F01`, owner, and the `cash` Setting above.
2. Owner opens **Manager → Kassalar**, creates the real drawers (and a SAFE only if used).
3. Cashier opens POS. With one drawer it is preselected; with several the cashier picks one.
   Either way the POS sends the **exact `till_id`** — the server never guesses.
4. `Shift` persists `company / branch / cashier / till_id / (optional) terminal_id / timestamps`.
5. Every shift-bound cash operation inherits `Shift.till_id`. Shift-less cash (purchase, receiving,
   supplier payment, purchase return/increase) requires an explicit `cash_account_id`.
6. Each physical cash event writes its business row **and** its `CashLedgerEntry` in the **same
   transaction**. There is no shadow-only state and no source row without a ledger leg.

Card and QR sales write **no** `CashLedgerEntry` — ledger authority means *physical cash*, not
*every payment*.

## 4a. Shift carryover — one model

**Closing a shift does not move physical cash.** Money left in the drawer stays there and stays in
the ledger.

`opening_cash` is what the cashier **counts**, not cash deposited. Posting the count as an `IN` leg
would double-count carried-over money (100 000 left overnight, counted again next morning → ledger
says 200 000, drawer holds 100 000). So `on_shift_open` posts an opening leg only for the
**difference** between the count and the drawer's ledger balance:

- `delta > 0` → `IN·OPENING` for the delta — the cashier physically added money.
- `delta <= 0` → **no leg**. A negative delta is a counting discrepancy; it is not silently absorbed
  by an OUT, so it surfaces as a shortage at close, which is the correct behaviour.

### Expected cash is anchored to the opening count

```
expected = Shift.opening_cash + Σ(this shift's ON_SHIFT legs, excluding OPENING)
```

Two wrong anchors were considered and rejected:

- **Sum of this shift's legs alone** double-counts nothing but ignores carried-over money, so a
  drawer holding 100 000 overnight reports a 100 000 surplus every morning.
- **The TILL account balance** (the whole drawer) is correct only while the ledger and the physical
  drawer agree. After one *real* shortage they diverge permanently: the cashier counted 90 000 where
  the ledger said 100 000, and nothing wrote the 10 000 back. Anchoring to the balance re-charges
  that same 10 000 loss to **every later shift**, so tomorrow's cashier answers for yesterday's.

Anchoring to `opening_cash` — what *this* cashier counted when taking the drawer — makes each shift
answer for its own window only. The `OPENING` leg is excluded from the sum because it carries the
delta, which the anchor already contains; including it would count added money twice.

**The unresolved discrepancy is not erased.** It stays visible as `ledger balance ≠ opening count`
and in the reconciliation record (`ledger_balance_snapshot` / `counted_cash` / `difference`).
Writing it off is an `ADJUSTMENT`, which §18 deliberately restricts to **manager+** — a cashier must
not be able to under-declare and have the system silently retire the difference. Auto-posting that
leg at close was implemented and then reverted for exactly this reason: it would have handed every
cashier a self-service write-off. Closing the gap is a manager's explicit act, not a side effect.

The close-time reconciliation snapshot uses this same formula, so the Z-report and the stored
record can never disagree.

## 5. Read authority

For a ledger-native tenant, **shift expected cash is computed from the ledger**
(`cash.tenant.ledger_expected_shift_cash` → `repositories.shift_movement_total`, anchored per §4a),
not from the legacy formula.

This matters concretely. The legacy formula counts only `SalePayment` and `CashMovement`. A **cash
purchase** paid from the cashier's drawer writes a ledger `OUT·PURCHASE_OUT` leg but no
`CashMovement`, so the legacy Z-report showed a **false shortage equal to the purchase**. Reading the
ledger's `ON_SHIFT` legs covers every physical movement — opening float, sales, refunds,
payin/payout/expense, collection, and cash purchases. The **live** (open-shift) expected value uses
the same source, so the cashier does not see one number all shift and a different one at close.
Legacy tenants keep the old formula unchanged.

All three read paths — the cashier's live shift summary, the Z-report at close, and the manager's
`shifts_overview` — call the same function. A manager and a cashier looking at one open shift must
never see two different "expected cash" numbers; before this they did, because the overview still
used the legacy formula.

Remaining legacy read, classified: `GET /reports/cashflow` groups flows by category from legacy
rows. Cash purchases have no `CashMovement`, so they are absent from its outflow total. This is
**COMPATIBILITY_DISPLAY** — a reporting gap, not custody math; physical custody everywhere derives
from the ledger.

## 5a. Offline replay into a closed shift

Rejected server-side (`reject_closed_shift_replay`) and **never silently discarded**: the POS moves
the event to a durable dead-letter list (`savdoos_outbox_failed`) and shows the cashier a red badge
with the count. A full LATE_SYNC approval workflow remains post-launch work; the launch-safe bar —
rejected, preserved, visible, no reconciliation rewritten — is met.

## 6. The system must never degrade silently

Enforcement (`cutover_guard.enforcement_active`, which reads `cutover_at`) and ledger writing
(`retrofit.dual_write_enabled`, which needs Postgres + the `cash` schema **and** a non-`LEGACY_ONLY`
mode) are two *different* conditions. If they diverge, guards keep passing while ledger legs stop
being written — silently recreating the identity-less legacy state that migration exists to repair.

`cash.tenant.require_ledger_writable` closes this: for a **ledger-native** tenant, if the ledger
cannot be written, the physical cash operation **fails loudly (503)** instead of degrading. Legacy
tenants are untouched — for them that state is legitimate.

Scope: the guard applies **only on PostgreSQL**, where the cash subsystem is expected to exist. On
SQLite the cash subsystem is architecturally absent by design (dev and e2e), so there is nothing to
degrade from and the guard stays silent. Production is PostgreSQL, so the two real risks — a missing
`cash` schema, and a global `SAVDOOS_CASH_MODE=LEGACY_ONLY` — are both covered.

## 7. What is NOT needed for a fresh tenant

`cash_discover` · `cash_provision` · `historical_till_map` · `cash_backfill` · `cash_verify` ·
historical acknowledgements · migration manifests · approved hashes · T0 planning.

This is enforced by test `test_J_no_migration_dependency`, which traps those functions and fails if
the fresh path calls any of them.

## 8. Tests that hold this contract

`tests/cash/test_fresh_tenant_launch.py`:

| Test | Proves |
|---|---|
| A | new company is ledger-native, `cutover_at == onboarded_at`, idempotent |
| B | `CASH_SETUP_REQUIRED` → `POS_READY` |
| C | full day-one smoke: 0 + 100 000 cash − 20 000 refund − 10 000 expense = **70 000**; card 50 000 excluded |
| D | card/QR writes no cash ledger row |
| E | collection without a SAFE writes **neither** a legacy row nor a one-legged ledger OUT |
| F | SAFE is explicit; then collection is a paired transfer and cash is conserved |
| G | rejects: no TILL, wrong branch, archived, missing `till_id` |
| H | duplicate replay is idempotent |
| I | cross-tenant TILL rejected; listings and setup state are tenant-scoped |
| J | no migration dependency |
| K | cash purchase produces **no false shortage** in the Z-report |
| L | ledger-native never degrades silently; legacy behaviour unchanged |
| M | carried-over cash is not double-counted at open |
| N | off-shift debt payment demands an explicit custody account |
| O | a purchase return posts even when the original had no ledger leg |
| P | collection is a paired transfer and conserves cash |
| Q | extended first-day arithmetic across every cash operation |
| R | a real shortage is **not** re-charged to the next shift (opening anchor) |
| S | the reconciliation snapshot equals the Z-report, on a carried-over drawer |
| T | manager overview and cashier screen show the **same** expected cash |
| U | off-shift debt payment custody is scoped to the actor's branch |

## 9. Before the first real merchant

These are **not** code gaps in the fresh path — they are operational prerequisites.

- **Demo data.** The production database currently holds demo/test tenants (`fayzan`, `oltin`,
  `baraka`, `chinor`, `sinov`, `test879`, `normtest`). They are not real customers and must not
  drive migration strategy. Recommended: move demo/test data to a non-production environment, so
  production contains real merchant data only. Second-best: delete them before launch. Keeping them
  "marked DEMO" is weakest — the marker has to be respected by every future query.
- **Environments.** Dev, staging and production should not share one database. Production should
  hold real merchant data only.
- **Backups.** Do not assume the platform provides them. Required before launch: automated backup,
  a **tested** restore, a stated retention window, and a rehearsal.
- **Observability.** Minimum signals, each mapped to a real failure mode: ledger posting failure ·
  source row committed without its required ledger leg · cash account mismatch · reconciliation
  anomaly · duplicate/idempotency conflict · offline replay rejection · shift close discrepancy.
- **POS build.** Every cash device must run a build that sends an exact `till_id` (v0.7.0+).

### Known boundary: off-shift cash debt payment has no UI

`POST /customers/{id}/payments` resolves custody two ways: with an open shift it uses
`Shift.till_id` (server-authoritative); **without** one it requires an explicit `cash_account_id`,
validated against the actor's own branch. No client sends that field — `Customers.tsx` posts only
`{amount, method, client_uuid}`.

Consequence on a fresh tenant (post-T0 from minute one): a cashier **on shift** records cash debt
payments normally, but an admin **not on shift** is refused with `CASH_CUSTODY_REQUIRED`.

This fails **closed** — no cash can enter without a custody account, which is the safe direction —
so it is a capability gap, not a money-safety hole. The day-one workaround is the normal flow: the
cashier records the payment during their shift. Adding a custody picker for off-shift payments is
tracked as post-checkpoint UI work.
