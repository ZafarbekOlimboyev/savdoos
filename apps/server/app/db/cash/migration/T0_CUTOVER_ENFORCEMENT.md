# T0 Cutover Enforcement — post-T0 physical cash requires an exact TILL

> After a company's T0, **no physical cash mutation may be recorded without an exact current physical
> custody account**. The drawer is never guessed — not from the branch, not from the cashier, not from
> "the branch only has one TILL".

Guard: [`app/services/cash/cutover_guard.py`](../../../services/cash/cutover_guard.py).
Companion: [PRE_T0_RUNTIME_READINESS.md](PRE_T0_RUNTIME_READINESS.md) ·
[HISTORICAL_TILL_RESOLUTION.md](HISTORICAL_TILL_RESOLUTION.md).

---

## 1. Why a central guard

Enforcement used to be two scattered `cutover_reached` checks — shift-open and online cash sale. An audit
found **12 of 14** physical-cash entry points unguarded, and the one sale guard was **bypassable**: it was
skipped whenever `honor_price_snapshot` was true, and `/sync/push` (which any POS can call with the same
`kassa.sell` permission) always sets it. Scattered endpoint checks cannot hold this invariant; one central
guard can.

## 2. The guard

```python
require_post_t0_till(db, company_id=…, branch_id=…, operation=…, shift=…, till_id=…)
    -> (CashAccount | None, enforced: bool)          # shift-bound TILL custody

require_custody_account(db, company_id=…, branch_id=…, account_id=…, operation=…,
                        expect_type="TILL"|"SAFE", currency=…)   # shift-less explicit custody

cutover_open_shift_gate(db, company_id=…, shift=…, operation=…)   # shift-scoped wrapper
reject_closed_shift_replay(db, company_id=…, shift=…, operation=…)
```

`enforced=False` means pre-T0 — legacy behaviour continues and **no TILL is invented**.
`enforced=True` means the returned account passed every check:

- the company's cutover has been reached **by server acceptance time** (see §3);
- the TILL exists, is `type=TILL`, is `ACTIVE`, and belongs to this **tenant**;
- it belongs to the operation's **branch**;
- if a shift is supplied: post-T0 the shift must have a `till_id`, and an explicitly supplied
  `till_id` must equal it.

Stable error codes (clients and operators branch on these):

| Code | Meaning |
|---|---|
| `LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER` | a pre-T0 shift with `till_id = NULL` crossed T0 |
| `TILL_REQUIRED_AFTER_CUTOVER` | no drawer supplied and none may be inferred |
| `TILL_INVALID_AFTER_CUTOVER` | not found / not ACTIVE / wrong tenant / wrong branch |
| `TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER` | supplied drawer ≠ the shift's drawer |
| `CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER` | shift-less cash with no explicit TILL/SAFE |
| `CASH_CUSTODY_ACCOUNT_INVALID` | custody account wrong type / tenant / branch / currency / archived |
| `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY` | replay targeting a closed/reconciled shift |

## 3. Trusted enforcement time (offline replay)

Two clocks, deliberately separated:

| | Source | Used for |
|---|---|---|
| **Accounting time** | `device_occurred_at` / `sold_at` (client) | when the event happened; authoritative in the ledger, never rewritten |
| **Enforcement time** | server acceptance time | whether strict post-T0 custody applies |

**Only the server clock decides enforcement.** `sold_at` is client-supplied and unauthenticated; if it
could open the T0 gate, any POS could backdate a receipt and keep writing post-T0 cash with no drawer.
So: *if the server accepts a physical-cash event after the company's T0, exact custody identity is
required — whatever `sold_at` says.*

Genuine pre-T0 offline events are handled by the **sync barrier** (below), not by trusting device time.

### 3b. Offline cutover barrier (operator procedure)

Before setting T0, for the chosen company:

1. briefly pause new cash writes;
2. have every active POS flush its pending offline queue;
3. confirm the pending offline cash queue is **0**;
4. only then set `cutover_at`.

After T0 every physical-cash event the server accepts needs exact TILL/SAFE identity and cannot gain a
legacy exemption from an old `sold_at`. If delayed pre-T0 replay is ever needed after T0, that requires a
separate **server-attested batch** mechanism — deliberately not built here, because it would mean trusting
unsigned device time.

### 3c. Offline payload contract

A post-T0 offline-origin cash event must carry: `shift_id` when shift-bound, `till_id` (or a general
`cash_account_id`) for custody, `terminal_id` when available, `device_occurred_at`, and a stable
idempotency key. The server validates the account against **current** runtime identity.
`terminal_id` is **not** sufficient to recover a missing `till_id` — the terminal→TILL binding is mutable
and unversioned (see HISTORICAL_TILL_RESOLUTION.md §3b).

## 4. Legacy open shift crossing T0

A shift opened before T0 with `till_id = NULL` that is still open after T0 **must not accept new physical
cash**. Every guarded operation on such a shift fails with `LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER`.

Nothing is auto-mutated at T0: no shift is closed, no drawer is attached. The operator path is to **close
the legacy shift and open a fresh one on an explicit TILL** (preferred), or explicitly attach a real
current TILL if the physical drawer is genuinely known. Readiness reports such a shift as
`CURRENT_RUNTIME_NOT_READY` before T0 so it is dealt with in advance.

## 5. Covered surfaces

| Entry point | Guarded |
|---|---|
| shift open | yes (pre-existing) |
| online cash sale | yes — now via the central guard |
| offline / replayed cash sale (`/sync/push`) | **yes — bypass closed**, by server acceptance time |
| cash refund / Return | **yes (new)** |
| `/shifts/{id}/cash` — payin / payout / expense / collection | **yes (new)** |
| `/cash/ops` | **yes (new)** |
| customer debt payment (cash) | **yes (new)** |
| supplier payment (cash) | **yes (new)** |
| cash purchase (`/purchases`) | **yes** — explicit custody |
| receiving cash purchase | **yes** — explicit custody |
| purchase return (cash IN) | **yes** — explicit custody |
| purchase increase (cash OUT) | **yes** — explicit custody |
| shift close / reconciliation | no cash mutation of its own (records counted cash) |
| demo seed | vendor-gated, non-runtime |

### 5b. Custody contract

Every physical-cash mutation has an exact physical custody account.

**Shift-bound cash** — `account_id` must equal `shift.till_id`; the account must exist, be `TILL`,
`ACTIVE`, same tenant, same branch.

**Shift-less cash** — the caller must **explicitly** provide the custody account (`TILL` or `SAFE`
depending on where the money physically is). Forbidden: branch default, first TILL, the
exactly-one-active-TILL shortcut, cashier default, mutable terminal inference, implicit SAFE, null
account. Creating an account and assuming it was used is forbidden.

Purchase, receiving, purchase-return and purchase-increase now implement the contract fully. Their request
payloads (`PurchaseCreate`, `PurchaseEdit`, receiving `CommitIn`, `SupplierPaymentIn`) carry an optional
`cash_account_id`, resolved by the single rule in `cutover_guard.resolve_cash_custody`:

```
open shift  ->  custody = shift.till_id          (caller may pass the same id; it may NOT override)
no shift    ->  custody = request.cash_account_id (TILL or SAFE), required after T0
```

The chosen account is persisted on the business source — `purchases.cash_account_id`,
`supplier_payments.cash_account_id`, `purchase_returns.cash_account_id` (additive, nullable, legacy rows
left NULL) — so a later audit does not depend on the request body. Re-sending the same operation
(`client_uuid`) with a *different* account is rejected **409** rather than silently posting to the new
account or silently keeping the old one. Pre-T0 an explicit account is still validated and used; only when
no account is given does pre-T0 fall back to legacy behaviour, and even then nothing is guessed.

### 5c. SAFE runtime semantics

A SAFE is shift-less physical custody. Validation: `type == SAFE`, `ACTIVE`, same tenant, same branch,
same currency. A branch has **0..N** SAFEs just as it has 0..N TILLs — a SAFE is never auto-selected, even
when the branch has exactly one.

### 5d. Collection (inkassa) = TILL → SAFE transfer

Moving cash from a drawer to the safe does not remove it from company custody, so the old one-legged
`OUT·CASH_OUT` was financially wrong — it deleted cash from the ledger. Collection is now a **paired
internal transfer**: `TILL OUT` + `SAFE IN`, same tenant/branch/currency/amount, one `transfer_group_id`,
immutable and idempotent (`source_id = CashMovement.id`).

API contract: `shift_id` + `destination_safe_id` + `amount`. Source is always `shift.till_id`. Rejected:
`till = NULL`, same source and destination, wrong tenant, wrong branch, wrong currency, archived either
side, destination not a SAFE, missing `destination_safe_id`. **No default SAFE selection.**

A later bank deposit is separate: `SAFE OUT` with category `BANK_DEPOSIT`, a single leg with no transfer
group — that is when cash genuinely leaves company custody. No fake BANK cash account is created.

### 5e. Closed-shift replay

A closed/reconciled shift must not be silently changed by ordinary POS replay. Post-T0 any cash event
targeting a closed shift is rejected with `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY` **before** the
source mutation. The shift is not reopened, reconciliation is not updated, no other shift is auto-assigned,
and nothing is silently posted off-shift.

**Future LATE_SYNC recovery boundary.** `posting_kind=LATE_SYNC` exists in the architecture, but there is
deliberately **no automatic** path to it. A future explicit recovery workflow would verify operator
approval, use exact custody evidence, create a LATE_SYNC entry and a reconciliation *exception* — and
never rewrite the closed reconciliation.

## 6. Returns

`Return.till_id` is authoritative for the refund's cash account. The original sale's drawer is **not**
automatically the refund drawer — a cashier may legitimately refund from another valid current TILL — but
post-T0 that drawer must be explicit and must pass the guard. A legacy Return that occurred before T0 with
an unknown drawer keeps historical `HISTORICAL_TILL_UNKNOWN` semantics and stays non-blocking.

## 7. Per-company cutover

`cutover_at` lives in `Setting(company_id, branch_id=NULL, key='cash')`, so the guard is evaluated **per
company**. Tenants cut over independently; one company's readiness never gates another's.

## 8. Manifest parity (preflight → dry-run → apply → verify)

All four stages must plan from identical inputs or the approval is meaningless. `_manifest_hash` now
fingerprints **every** planning input: T0, tenant scope, the operator `--mapping`, the historical
attestation, the per-leg TILL evidence rule, and `PLANNER_SCHEMA_VERSION`. Change any one and the previous
approval is invalid.

- `preflight.final_dry_run(..., mapping=…, historical_map=…)` — previously passed **neither**, so its
  manifest drifted from the applied one.
- `cash_verify --historical-till-map … [--approved-hash …]` — uses the same parser and validation as
  backfill. With `--approved-hash`, a mismatch fails loudly as `INPUT_MISMATCH` (naming the map/mapping/
  planner fingerprints) instead of silently recomputing a different row set and reporting PASS.

## 9. Historical-unknown acknowledgement

Deliberately skipped historical rows are non-blocking but must not be invisible. Rather than forcing one
acknowledgement per row (28 rows = 28 acks), `final_dry_run(..., ack_historical_unknown=True)` records a
single explicit acknowledgement **pinned to a deterministic digest** of the skipped set
(`historical_unknown_ack_digest`, e.g. `28:<sha256 prefix>`). If a new evidence-less row appears the digest
changes and the old acknowledgement no longer covers it — so nothing can be silently ignored. Per-row acks
remain available.

## 10. Known remaining gaps

- **Explicit custody payload for purchases.** Purchase / receiving / purchase-return / purchase-increase
  are guarded and **fail closed** post-T0 when shift-less, but the request schemas do not yet carry an
  explicit `cash_account_id`, so a legitimately shift-less cash purchase cannot be completed after T0
  until that field is added.
- **`sold_at` remains unauthenticated.** Enforcement no longer trusts it, so this can no longer bypass
  T0; it still affects the *accounting* timestamp. Device-signed event times would close that.
- **Offline replay can still bind to a closed shift pre-T0.** Post-T0 it is rejected
  (`CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY`); before T0 legacy behaviour is unchanged.
- **Shift close does not verify the client queue.** The server cannot see a POS's pending local queue, so
  the POS must flush before closing ("Avval sinxronizatsiyani tugating, keyin smenani yoping"). That UX is
  not the guard — post-T0 the closed-shift rejection is the server-side protection.
- **Retrofit hooks still `return None` silently** when a drawer cannot be resolved pre-T0. Post-T0 the
  guard rejects first, so the silent path is unreachable after cutover.
