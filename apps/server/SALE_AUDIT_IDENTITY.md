# Sale / Receipt Audit Identity

Every sale (and every refund) records **who, which shift, which physical cash drawer, and which POS
device** it happened on — authoritatively, at creation time, never inferred later.

Physical model (see `app/services/cash/till_identity.py`): **a branch is NOT one TILL**. Each physical
checkout / cash drawer is a **TILL** (`cash.cash_accounts`, `type=TILL`); a cashier is not a TILL
(cashiers rotate, the drawer stays); each branch usually has one shared **SAFE**.

## Canonical audit identity (persisted on `sales`)
| Field | Meaning | Authority |
|---|---|---|
| `company_id` | tenant | server (`emp.company_id`) |
| `branch_id` | branch the sale happened in | server (`actor_branch`) |
| `cashier_id` | user who performed the sale | server (`emp.id`) |
| `shift_id` | the cashier's work session | server (active open shift) |
| `till_id` | **physical** `CashAccount(type=TILL).id` (the drawer) | server (from the shift; never guessed) |
| `terminal_id` | POS device / checkout device | server (from the shift; request only when shift-less) |

IDs are authoritative. `till_id` has **no DB foreign key** (the `cash` schema is Postgres-only; the
offline SQLite POS has no `cash_accounts`) — it is **service-validated** (same tenant + branch, type
`TILL`, status `ACTIVE`).

## Resolution rules (server-authoritative)
- **Shift open** (`POST /shifts/open`): `terminal_id` from the request is validated (exists + belongs to
  the branch); the shift's `till_id` is resolved from that terminal via
  `retrofit.resolve_till_id` → `till_identity.resolve_till_exact` (exact, **no branch-default fallback**).
  When cash is disabled (SQLite / unprovisioned / multi-TILL with no terminal match), `till_id = NULL`
  (honest "unknown", never a guess).
- **Sale with an open shift**: `cashier_id / shift_id / branch_id / terminal_id / till_id` are all
  inherited from the active shift. A client-sent `till_id` that conflicts with the shift's till → **409**;
  a client-sent `till_id` of the wrong tenant / branch / type / status → **400**. The client can never
  change the physical identity.
- **Sale without a shift** (only if `force_shift` is off): `till_id` is resolved from the request
  `terminal_id`; if it can't be resolved, `till_id = NULL` — the cash ledger simply does not post
  (a cash sale is **never** written to a guessed TILL).

## Ledger relation (cash payments only)
`on_cash_sale(..., till_id=Sale.till_id)` posts the `IN·SALE` leg to **exactly `Sale.till_id`**
(`CashLedgerEntry.cash_account_id == Sale.till_id`). Card / QR / credit payments create **no** physical
cash-ledger movement. `cashier_id` is never used as a cash-custody account.

## Refund identity (`returns`)
A refund keeps the **original sale identity** (`original_sale_id`) and separately records the **refunding**
context — `shift_id`, `terminal_id`, `till_id` — of the cashier performing it, which **may differ** from
the original sale (e.g. sold on TILL-01 today, refunded on TILL-02 tomorrow). The cash `OUT·REFUND` leg is
posted from the **refund** TILL (`on_cash_refund(..., till_id=Return.till_id)`), not the original sale's.

## Snapshots (sale-time, presentation-only)
IDs are authoritative; these frozen strings keep old receipts reproducible after an entity is **renamed or
deleted** (same pattern as `sale_items.name_snapshot`):
`cashier_name_snapshot`, `branch_name_snapshot`, `till_code_snapshot`, `till_label_snapshot`,
`terminal_name_snapshot`. Justification — each is a **mutable display name** that appears on a receipt:
a renamed/deactivated cashier, a renamed TILL/drawer (the audit subject itself), a renamed terminal, a
renamed branch. Duplication is kept minimal (five nullable strings; no numeric/relational data is copied).

## Immutability
`sales` is append-only (model docstring: "Chek — append-only"); there is no endpoint that updates
`cashier_id / shift_id / till_id / terminal_id / branch_id` after creation. Corrections go through a
**return/refund** (or a future explicit audited reversal), never a silent `UPDATE` that would move an old
receipt to a different drawer.

## API contract (frontend)
`SaleOut` (POST `/sales`, GET `/sales/{id}`) now includes: `branch_id, cashier_id, shift_id, till_id,
terminal_id` + the five `*_snapshot` fields. `GET /sales` rows carry the same audit block and accept
audit filters: `cashier_id`, `shift_id`, `till_id`, `terminal_id`, `branch_id` (all tenant/branch-scoped).
Example history row:
```json
{
  "id": "…", "receipt_no": "#1300", "sold_at": "2026-09-06T10:00:00Z", "total": 10000.0,
  "cashier": "Ali", "method": "cash",
  "branch_id": "…", "cashier_id": "…", "shift_id": "…",
  "till_id": "…", "terminal_id": "…",
  "cashier_name": "Ali", "branch_name": "Markaz",
  "till_code": "TILL-02", "till_label": "TILL code=TILL-02 terminal=…", "terminal_name": "Kassa 2"
}
```
The nested `till { id, code, label }` / `terminal { id, name }` / `cashier { id, name }` shape can be
composed by the client from `*_id` + `*_snapshot`; the ids are the join keys, the snapshots the labels.
Consumers can list sales **by cashier / shift / till / terminal / branch** using the filters above.

## Indexes
`sales (company_id, sold_at)` (existing) + new: `(branch_id, sold_at)`, `(cashier_id, sold_at)`,
`(till_id, sold_at)`, `(terminal_id, sold_at)`, `(shift_id)`; `returns (till_id)`. Auto-created by
`initdb._ensure_indexes` (SQLite + Postgres). New columns are auto-added by `initdb._ensure_columns`
(dialect-aware: `UUID` on Postgres, `CHAR(32)` on SQLite).

## Legacy backfill (SAFE, deterministic-evidence-only — operator-run, NOT automatic)
Existing rows have `till_id = NULL`. Backfill **only** where deterministic evidence exists — the sale's
own shift already resolved a drawer — and **never** guess (`cashier = till` or `branch = default till`
are forbidden). Rows with no shift, or whose shift has `till_id = NULL`, stay **NULL / history-unknown**.

```sql
-- Sales: inherit the drawer from the sale's own shift, only where the shift knows it.
UPDATE sales
   SET till_id = s.till_id
  FROM shifts s
 WHERE sales.shift_id = s.id
   AND sales.till_id IS NULL
   AND s.till_id IS NOT NULL;
-- (terminal_id may be filled the same way where sales.terminal_id IS NULL AND s.terminal_id IS NOT NULL.)

-- Returns: inherit from the return's own shift, same guard.
UPDATE returns
   SET till_id = s.till_id
  FROM shifts s
 WHERE returns.shift_id = s.id
   AND returns.till_id IS NULL
   AND s.till_id IS NOT NULL;
```
Snapshots for historical rows are **not** backfilled (the entity names may already have changed — a
backfilled "current" name would be misleading); leave them NULL and render from the live entity for old
rows. This backfill is idempotent and read-safe; run it once per environment after deploy, out of band.
```
