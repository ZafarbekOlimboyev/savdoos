# Cash Ledger · PURCHASE_RETURN Source Identity Correction

Status: **applied** (contract/schema/DDL/posting/adapter/call-site). Migration NOT started.

## Problem (discovered in Phase 2b-Finalization)
The `purchase_return` adapter reused the cash-purchase business identity:

| Operation | source_type | source_id | leg_index | → ledger |
|-----------|-------------|-----------|-----------|----------|
| Cash purchase (create) | `PURCHASE` | `purchase_id` | 0 | `OUT · PURCHASE_OUT` |
| Purchase return (OLD, wrong) | `PURCHASE` | `purchase_id` | 0 | `IN · PURCHASE_RETURN` |

Both produced the identical `cle_uq_business (tenant_id, source_type, source_id, leg_index)`
key → posting a return for a purchase that already had a cash-purchase leg raised
`IntegrityError`, and multiple returns against one purchase could not coexist. The cash
`OUT·PURCHASE_OUT` posted at create was therefore never reversible.

## Correction — distinct business source type
A new **source type** `PURCHASE_RETURN` is introduced. It is a *source type*, NOT a posting
kind, category, or reversal. `category = PURCHASE_RETURN`, `direction = IN`, `reverses_id = NULL`
(a return is an independent business event, never a reversal of the original purchase leg).

| Operation | source_type | source_id | leg_index | → ledger |
|-----------|-------------|-----------|-----------|----------|
| Cash purchase (create) | `PURCHASE` | `purchase_id` | 0 | `OUT · PURCHASE_OUT` |
| Purchase return | `PURCHASE_RETURN` | `purchase_return_id` | 0 | `IN · PURCHASE_RETURN` |

Approved source-type list (9): SALE, RETURN, CUSTOMER_PAYMENT, SUPPLIER_PAYMENT, PURCHASE,
**PURCHASE_RETURN**, CASH_OP, TRANSFER, SHIFT_OPEN. Business-uniqueness principle unchanged:
`(tenant_id, source_type, source_id, leg_index)`.

## Source identity — the return business event
SavdoOS had **no persistent purchase-return / cancellation entity**. The de-facto
return-to-supplier flow is `edit_purchase` (`PATCH /purchases/{id}`) reducing or cancelling a
**received (cash)** purchase — that is the moment cash is returned by the supplier. So a minimal
persistent event entity is introduced:

**`public.purchase_returns`** (`PurchaseReturn` model): `id` (PK, the ledger `source_id`),
`company_id`, `purchase_id`, `branch_id`, `amount` (cash returned), `reason`, `employee_id`,
`client_uuid`, `created_at`. One row per reducing/cancelling edit of a received purchase, for the
returned delta (`paid_before − new_total`, and `= paid_before` on full cancel).

Why this identity is correct:
- **Not the original purchase id** — a distinct entity, so no collision with `PURCHASE + purchase_id`.
- **Not a random-on-retry UUID / not a timestamp** — the id is the persistent `PurchaseReturn.id`.
- **Idempotent** — `edit_purchase` locks the purchase `FOR UPDATE` and recomputes the delta from
  the persisted `paid_amount` (PR-002 convergence): a replayed/duplicated edit computes delta 0 →
  no `PurchaseReturn` row and no ledger leg. `cle_uq_business` is the structural guarantee that any
  single `PurchaseReturn` row posts exactly once. A full cancel sets `deleted_at`, so it is one-shot.
- **Multiple returns** — return #1 and #2 are separate `PurchaseReturn` rows with distinct ids →
  `PURCHASE_RETURN + return_1_id + 0` and `PURCHASE_RETURN + return_2_id + 0` never collide.
- **Independent audit trail** — each return is its own auditable row.

## Scope / non-goals
- `PURCHASE + purchase_id + 0 → OUT·PURCHASE_OUT` (create) is unchanged.
- Only **received (cash)** purchases post a cash return; debt purchases adjust `SupplierLedger`
  (no drawer movement), so they are gated out (`not _charged`).
- INCREASING a received purchase on edit (more cash out) is **out of scope** here and remains
  unposted — a separate, pre-existing symmetric gap to the create side, for the migration phase.
- Guarded like every Phase 2b hook: no-op on SQLite / unmapped branch; posts `commit=False` so the
  return leg joins the caller transaction (source + ledger atomic).
