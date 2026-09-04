# Cash Ledger · Migration Phase 1 — Execution Design (Resolution of the four execution-shaping decisions)

Design only. No production write, no commit. Derived from the ratified architecture, DDL v1.0,
CashPostingService contract, `retrofit.py`/`adapters.py`, and the legacy schema.

---

## 1. POSTING PATH — **Recommend B: migration-owner controlled append (as a defined migration capability)**

**A) CashPostingService with `provenance=RECONSTRUCTION`** — reuses the sole writer (`posting.py:369`) and the
business-key dedup. But its pipeline is built for **live** posting and mis-fits history:
- OUT **sufficiency** (step 9) re-evaluates against a running balance → forces a global posting order and
  **rejects legitimate historical negatives** unless `allow_negative` (which fabricates a manager
  `NEGATIVE_OVERRIDE` approval that never happened).
- **Shift resolution** with `origin_shift_id=None` → Case D → floods the ledger with `UNRESOLVED_OFF_SHIFT`
  exceptions; reconstructing a closed shift → `LATE_SYNC` + `LATE_SYNC_UNACK` exceptions (a live anomaly, not
  the historical truth).
- **Timestamp window** validation is live-oriented.

**B) Migration-owner controlled append** — a purpose-built, one-time, audited historical path:
- Writes `RECONSTRUCTION` rows directly, setting `provenance=RECONSTRUCTION` + `reconstruction_reason` +
  `reconstruction_source_ref` (satisfies `cle_recon_prov`), an explicit `posting_kind`/`shift_id` (§2), and the
  resolved `cash_account_id` (§3). Idempotency is **DB-enforced**: `INSERT … ON CONFLICT ON CONSTRAINT
  cle_uq_business DO NOTHING`. Entry `id` is deterministic `uuid5(business key)` (byte-identical reruns).
- **Privileges:** runs as the **migration owner** (the DDL executor / DBA login that owns `cash.*`, per CF-D6) —
  **not** `cash_posting`, `cash_app`, `cash_readonly`, or `cash_admin`. Define this as an explicit **migration
  capability** (e.g. a `cash_migration` login granted `INSERT` on `cash.cash_ledger_entries` for the migration
  window, or execute under the owner). The runtime `cash_posting` role is untouched.
- **Runtime guarantees preserved:** `CashPostingService` remains the **sole runtime writer**; the append is a
  migration-only, non-runtime-reachable module. Append-only immutability still holds for every role
  (`fn_block_mutation`/`fn_block_truncate` block UPDATE/DELETE/TRUNCATE); the migration only INSERTs.
- **Transaction boundaries:** batched, atomic per batch (per-tenant, ≤N rows), ordered by §4; a failed batch
  rolls back and rerun resumes idempotently (ON CONFLICT). Each run writes an immutable **run record** into
  `cash.audit_logs` (T0, scope, counts, checksum, operator) + the manifest (§13).
- **Direct-write audit:** update it to recognize the migration module as a **sanctioned owner-role, migration-time**
  writer (documented, distinct from runtime `posting.py:369`). This does not weaken the runtime single-writer
  property (which is about the runtime role/path).

Chosen because RECONSTRUCTION + the migration-owner role were designed for exactly this; it records history
**faithfully** rather than re-validating it under live rules; and it keeps the runtime writer/guarantees intact.

## 2. HISTORICAL SHIFT ATTRIBUTION (no invented/clamped timestamps)

Window = the runtime window applied to the legacy shift: `[opened_at − TOL, (closed_at or opened_at + MAX) + TOL]`
(TOL=`CASH_TS_TOLERANCE_MIN`, MAX=`CASH_MAX_SHIFT_HOURS`). `device_occurred_at` = the legacy timestamp
(`opened_at`/`sold_at`/`created_at`), never altered. `shift_expected_cash` counts **ON_SHIFT only**, so a
faithful reconstruction of a shift's expected cash requires its contemporaneous legs to be **ON_SHIFT**.

| Case | Rule | posting_kind · shift_id |
|---|---|---|
| Source has a legacy shift link, `device_occurred_at` **in-window** | contemporaneous — belongs to the shift's expected cash | **ON_SHIFT** · reconstructed cash.shift id |
| Source has a legacy shift link, **out-of-window** | timestamp anomaly — don't clamp, don't attribute | **OFF_SHIFT** · NULL + `TIMESTAMP_OUT_OF_WINDOW` exception |
| Source has **no** shift link (refund/purchase/supplier/debt/purchase-return) | no shift period to attribute to | **OFF_SHIFT** · NULL |
| Reconstructed opening float (`Shift.opening_cash`) | definitionally in-window at `opened_at` | **ON_SHIFT** · reconstructed shift id |
| Shift is **closed** historically | reconstruct cash.shift as CLOSED; its in-window legs are ON_SHIFT; snapshot = Σ ON_SHIFT | — |
| Shift is **open at T0** (straddles T0) | pre-T0 legs ON_SHIFT; post-T0 deferred to live; but reconstruct-vs-live cash.shift ownership is ambiguous | **REVIEW** (operator closes/reopens at T0 per §G) |

**LATE_SYNC is NOT used during pure historical backfill.** LATE_SYNC means "arrived after the shift was already
reconciled" — a live/dual-write anomaly. In backfill all of a shift's legs are reconstructed together with no
prior reconciliation, so contemporaneous legs are ON_SHIFT and the shift's reconciliation snapshot is built from
them. LATE_SYNC is reserved for the live/dual-write phase.

Reconstructed `cash.shifts` use the **legacy shift id** as the cash.shift id (deterministic; a later live
dual-write for a still-open shift must reuse it — hence T0-straddling shifts are REVIEW, not auto-reconstructed).

## 3. SHIFT-LESS SOURCE ACCOUNT RESOLUTION (ranked; REVIEW/BLOCK, never guess)

Legacy branch linkage traced: `Return.branch_id` (NOT NULL), `Purchase.branch_id` (NOT NULL),
`PurchaseReturn.branch_id` (NOT NULL), `Sale.branch_id` (NOT NULL), `Shift.branch_id` → all **direct**.
Problem sources: **`SupplierPayment`** (no branch_id; has `employee_id`, `client_uuid`) and **`CustomerPayment`**
(nullable `branch_id`; has `employee_id`). Resolution ranking (highest reliability first; stop at first hit):

1. **Explicit `branch_id` on the source row** (CustomerPayment when set) → that branch's TILL. *Deterministic.*
2. **Single-active-branch tenant** → its sole TILL. *Deterministic & unambiguous* (covers single-store tenants,
   e.g. `fayzan`/F01).
3. **Shadow-movement linkage** — the payment's shadow `CashMovement` (payout `"Ta'minotchi · "` / payin
   `"Qarz to'lovi · "`, `client_uuid IS NULL`) matched by `(employee_id, amount, reason, created_at)` → its
   `shift.branch_id`. Accept **only a unique** match.
4. **Employee's sole `EmployeeBranch`** (exactly one active bound branch) → that TILL. *Deterministic when 1:1.*
5. **Otherwise → REVIEW** (multi-branch tenant, no explicit branch, no unique shadow, multi/zero-branch employee).
   Never use `actor_branch`'s "first active branch" fallback — that is a **guess** and is forbidden.

An unmapped/ambiguous TILL for the tenant (Phase-0 `TILL_AMBIGUOUS`/`TILL_CURRENCY_UNKNOWN`) → **BLOCK** for the
affected legs regardless of the above.

## 4. CHRONOLOGICAL CASH SUFFICIENCY & HISTORICAL NEGATIVES

**Deterministic total order** for reconstruction/reconciliation per `cash_account`:
`ORDER BY device_occurred_at ASC, source_type_rank ASC, source_id ASC, leg_index ASC`, where
`source_type_rank` puts `SHIFT_OPEN` first (opening float precedes same-instant events), then a fixed rank for
the rest. Same-timestamp events therefore have a **stable, deterministic** order; reruns are byte-identical.

- **Opening precedes later events:** `opened_at ≤ event times`, and the SHIFT_OPEN rank breaks exact-instant ties
  → opening float is always first for its shift.
- **OUT sufficiency:** under Path B, sufficiency is **not** a live guard — history is recorded faithfully. The
  deterministic order drives a **running-balance reconciliation** (§20). If the running TILL balance ever goes
  `< 0`, the legs are **still all posted** (no clamping, no dropped legs, no fabricated approval); the negative is
  surfaced as a **data-quality REVIEW** with the exact (account, timestamp, balance) trace.
- **Legitimate historical negative representation:** a genuine driven-negative TILL is represented under the
  ratified architecture either (a) as the faithful ledger sum (`balance = Σ IN − Σ OUT` may be negative — the
  ledger is a record, and only *live* posting forbids un-approved negatives), plus a reconciliation exception; or
  (b) if the operator wants it authorized, a `negative_cash_approvals` row (OUT+TILL, `nca_scope`) carrying a
  RECONSTRUCTION note. **Default = (a)** (faithful + REVIEW). Never silently fabricate the negative away.

---

## A. Decision matrix
| Item | Options | Decision | Why |
|---|---|---|---|
| Posting path | A service-RECONSTRUCTION · B owner-append | **B** | faithful history; runtime writer/guarantees intact; DB-enforced idempotency |
| Shift attribution | ON/OFF/LATE_SYNC | in-window→**ON_SHIFT**, out/none→**OFF_SHIFT**, straddle-T0→**REVIEW**, LATE_SYNC→**not in backfill** | expected-cash faithfulness; no invented timestamps |
| Shift-less account | branch / single-branch / shadow / employee / — | ranked 1–4 then **REVIEW**; never `actor_branch` fallback | deterministic where possible, never guess |
| Sufficiency/negatives | reject vs faithful | **faithful + REVIEW** (no clamp), optional `nca` note | ledger is a record; anomalies surfaced not hidden |

## B. Exact algorithm
```
for tenant in scope:
  assert readiness_check.ok and backup verified and T0 recorded and TILLs provisioned (no ambiguous)
  legs = phase1.plan_backfill(tenant, t0).legs                     # historical (< T0) only
  reconstruct cash.shifts (legacy id) for every referenced shift fully < T0 (CLOSED);
      straddle-T0 shifts -> REVIEW, exclude
  for leg in legs:
    acct = resolve_account(leg)      # §3 ranking; REVIEW/BLOCK if unresolved -> exclude from insert
    kind, shift = attribute_shift(leg)   # §2
    provenance=RECONSTRUCTION; reason/source_ref from leg.reconstruction
    id = uuid5(tenant:source_type:source_id:leg_index)
  order legs by §4; run running-balance check -> negative -> REVIEW (still insert)
  batch INSERT ... ON CONFLICT (cle_uq_business) DO NOTHING   (owner role, atomic batches)
  record run (audit_logs) + verify (§19) + reconcile (§20)
BLOCK/REVIEW legs are NEVER inserted.
```

## C. Required code changes (specification — to implement at execution time, then review)
- `migration/backfill.py`: `resolve_account(leg)` (§3 ranking), `attribute_shift(leg)` (§2), `reconstruct_shifts()`
  (legacy-id cash.shifts, exclude straddle-T0), `execute(tenant, t0, *, apply)` (owner-role batched
  `ON CONFLICT DO NOTHING`, deterministic uuid5 id, run record), `verify()` (§19), `reconcile()` (§20).
- Plan legs must additionally carry `branch_id` (add to `_leg`) so `resolve_account` is row-local.
- DDL/roles: define the `cash_migration` capability (owner-scoped INSERT) OR document execution under the owner.
- Direct-write audit: whitelist `migration/backfill.py` as a sanctioned migration-time writer.

## D. Required tests (real PostgreSQL)
account resolution (each rank + REVIEW/BLOCK) · shift attribution (in/out-window, none, opening, straddle-T0
REVIEW) · deterministic ordering & same-timestamp stability · idempotent rerun (0 new, ON CONFLICT) · business-key
uniqueness · tenant isolation · historical negative → REVIEW + still-posted (no clamp) · no shadow double-count ·
purchase-return net (original OUT + return) · run record + manifest match · verify/reconcile pass · dry-run→execute
count parity · BLOCK/REVIEW legs never inserted.

## E. Production operator inputs required
approved **T0** (§G) · production DB connection as the **migration owner** · confirmation of ambiguous-mapping
resolutions (shared drawer, multi-branch shift-less payments) · sign-off on the §3 REVIEW resolutions and any
historical negatives · the verified backup manifest (§F).

## F. Backup / restore gate requirements (must PASS before any write)
`phase0.verify_backup(manifest).ok == True` — manifest with `snapshot_ref, taken_at, operator, checksum,
restore_rehearsed=True, verified=True`; a **rehearsed restore** into a scratch instance; readiness_check `all_ok`.
No write starts otherwise (Phase-0 runbook §14).

## G. T0 selection procedure (operator-chosen; not selected here)
Per Phase-0 §06: a low-traffic instant at which **all TILL shifts are closed** (or a coordinated freeze). Record
T0 in the manifest. `< T0` = backfilled; `≥ T0` = deferred to live dual-write. An open shift straddling T0 must be
closed/reopened at T0 by the operator (those shifts are REVIEW here). Offline events classify by
`device_occurred_at` vs T0.
