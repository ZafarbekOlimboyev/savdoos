# Historical TILL Resolution — `CURRENT TILL != HISTORICAL EVIDENCE`

> **The rule this document exists to enforce**
>
> **A TILL an operator creates today is not evidence that a past transaction physically happened in
> that drawer.**
>
> ```
> CURRENT TILL PROVISIONING   !=   HISTORICAL TILL EVIDENCE
> ```
>
> Never attach an evidence-less legacy row to a currently-active TILL. Provisioning a drawer today
> satisfies *runtime readiness*; it says nothing about which drawer held cash in 2024.

---

## 1. The two concepts, kept strictly apart

| | **A. CURRENT_RUNTIME_TILL** | **B. HISTORICAL_TILL_RESOLUTION** |
|---|---|---|
| Used for | new cash activity **after T0** | legacy **backfill** only |
| Question answered | "which drawer do we post to *now*?" | "which drawer did this past row *actually* use?" |
| Source of truth | `till_identity.resolve_till_exact` / `retrofit` | `historical_till.resolve` |
| Account status | must be `ACTIVE` | `ARCHIVED` is **valid** (a retired drawer is often the correct answer) |
| Satisfied by creating a TILL today? | **yes** | **no** |

Creating a TILL today satisfies **A**. It must **never** automatically satisfy **B**.

Implemented in [`historical_till.py`](historical_till.py); consumed by
[`backfill.resolve_account`](backfill.py). Runtime readiness is reported separately by
`backfill.current_till_readiness()` and never mixed into historical resolution.

## 2. Allowed evidence — the complete hierarchy (first match wins)

| # | Rule | What it is |
|---|---|---|
| 1 | `SOURCE_TILL` | the source row's own persisted `till_id` (`Sale.till_id`, `Return.till_id`) |
| 2 | `SHIFT_TILL` | `source.shift_id` → `Shift.till_id`, written at transaction time |
| 3 | — | **terminal evidence is NOT accepted** — see §2b |
| 4 | `SHADOW_SHIFT_TILL` | the row's own contemporaneous shadow `CashMovement` → its `Shift` → `Shift.till_id` |
| 5 | `OPERATOR_SOURCE_MAP` | operator attestation: `source_type:source_id` → `till_id` |
| 5 | `OPERATOR_SHIFT_MAP` | operator attestation: `shift_id` → `till_id` |

**There is no other fallback.** Rules 1, 2 and 4 are *intrinsic*: the fact was recorded **when the
transaction happened**. Rule 5 is an *attestation*: a named human takes responsibility.

Every candidate is validated before it is accepted: the account must exist, be of type `TILL`, belong to
the leg's tenant (a cross-tenant target is escalated to **BLOCK**, never quietly deferred), and — when the
leg's branch is known — belong to **that branch**.

**Rule 4 must prove identity, not similarity.** Matching only on tenant + type + reason-prefix + amount +
employee is not enough: a *later* payment's shadow — possibly in another branch, recorded after
provisioning — matches that fingerprint and would hand an old row today's drawer. Both shadow writers
create the source row and its `CashMovement` in one transaction from the same `now`, so
`CashMovement.created_at` must **equal** the leg's `device_occurred_at`, and the shadow's shift must be in
the leg's branch. A shadow whose shift has no `till_id` proves nothing.

## 3. Forbidden — never evidence

- "the branch has exactly one ACTIVE TILL today" — the `single-checkout` retroactive default
- branch-default TILL / first ACTIVE TILL / today's TILL count
- "the tenant has exactly one active branch today" — the branch is **not** guessed either
- cashier default, or cashier count — a cashier is not a drawer
- today's `EmployeeBranch` association — that table has **no temporal columns**, so it records where an
  employee works *now*; someone transferred in 2025 would drag their 2024 payments to the new branch
- a source `terminal_id` resolved through the current terminal→TILL binding (below)

### 3b. Why terminal evidence is forbidden

A source row's historical `terminal_id` is real, but the `terminal → TILL` relation it would be resolved
through is **mutable and unversioned**, so it describes *today*, not the past:

- the binding is serialized into the free-text `cash_accounts.label` (`till_identity.till_label`) — there
  is no terminal column, no `effective_at`/`effective_to`, and no history table;
- `PATCH /tills/{id}` rewrites that label in place, keeping no copy of the previous value;
- the DB guard `cash.fn_guard_cash_account` protects only `tenant_id / branch_id / type / currency / id`
  — `label` is explicitly left mutable, and `UPDATE` on it is granted to the posting role;
- `DELETE /tills/{id}` hard-deletes a drawer that nothing references yet — and **before backfill every
  provisioned drawer is unreferenced** (legacy shifts carry `till_id = NULL`), so a terminal can be
  re-bound to a brand-new TILL row id leaving no trace;
- nothing enforces one terminal ↔ one TILL.

So `terminal_id` alone can silently resolve a 2024 row onto a drawer created — or re-pointed — in 2026.
`TERMINAL_EVIDENCE_SUPPORTED = False`. If a versioned/immutable binding is ever introduced, this decision
should be revisited; until then the drawer must be proven by rules 1, 2, 4 or 5.

## 4. When there is no evidence → `HISTORICAL_TILL_UNKNOWN`

The leg is **skipped** and recorded as `REVIEW` with `evidence_class = HISTORICAL_TILL_UNKNOWN`.
No `cash_account_id` is ever invented.

**This is not a migration blocker.** It is `REVIEW`, never `BLOCK`:

- `plan_backfill._go_no_go` counts only `BLOCK` rows and duplicate business keys → **GO stays GO**
- the T0-forward migration proceeds normally
- the affected rows simply stay **outside the authoritative ledger** until evidence or an attestation
  exists; they can be backfilled later, idempotently, because the business key is deterministic
- the §9 pre-dual-write gate stays **PASS**: `reconcile_backfill` subtracts these deliberately deferred
  legs from the expected totals and reports them separately as `deferred_historical_identity_*`. They are
  *explained* exclusions, not an `unexplained_delta` — otherwise a single evidence-less row would
  hard-STOP the whole migration, which is exactly what this rule must not do

Do **not** tell an operator to "provision a TILL and re-run" for these rows — that does not resolve
them, and doing so would invite exactly the retroactive attribution this document forbids.

The separate, genuinely runtime concern — "this branch has no ACTIVE TILL today" — is reported on its
own as `CURRENT_TILL_NOT_PROVISIONED` (probe field `current_till_provisioned`). It matters for cash
activity **after** T0 and is unrelated to the identity of a past row.

## 5. The operator historical attestation file

A **separate document** from the ordinary `--mapping` file, with its own flag:

```bash
python -m app.tools.cash_backfill --t0 <ISO> --historical-till-map <path>
```

`--mapping` is *current provisioning intent* (which drawers exist now). Passing it here is **rejected
loudly** on the `kind` discriminator — there is no silent half-interpretation. Only **exact** identifiers
are accepted; there is deliberately no "branch + date range" form, because a range is an assertion about
rows the operator has not actually examined.

```json
{
  "kind": "HISTORICAL_TILL_EVIDENCE",
  "version": 1,
  "attested_by": "Z. Olimboyev",
  "attested_at": "2026-09-07T10:00:00+00:00",
  "note": "signed drawer count sheets, 2024-11",
  "sources": { "SUPPLIER_PAYMENT:<source uuid>": "<cash_account uuid>" },
  "shifts":  { "<shift uuid>": "<cash_account uuid>" }
}
```

`till_id` is a **cash_accounts UUID** — a `code` label can be reused across drawers, a UUID cannot.
`attested_by` is mandatory. Prefer `sources` (one row, one decision); `shifts` is acceptable when the
operator can vouch for a whole shift's drawer.

**Audit trail.** The attestation is fingerprinted into `_manifest_hash`, so changing which drawer a row is
attested to changes the approved hash — an altered attestation cannot slip through a previously approved
plan. The rule that resolved each leg is written into the ledger row's `reconstruction_reason` as
`· till_evidence=<RULE>`, so a reader can always tell a proven attribution from an attested one, and the
string `single-checkout` can never appear there again.

## 6. Per-source reality (what evidence each type can carry)

| Source | Intrinsic evidence available | Typical legacy outcome |
|---|---|---|
| `Sale` | `till_id`, `shift_id`→`Shift.till_id` | resolvable when RC7-era identity was written |
| `Return` | `till_id`, `shift_id` (RC6 identity) | resolvable for RC6-era rows; older ones unknown |
| `Shift` (opening) / `CashMovement` | `Shift.till_id` | resolvable once shifts carry `till_id` |
| `CustomerPayment` | **none** (no till/shift/terminal columns) — only a contemporaneous shadow | usually `HISTORICAL_TILL_UNKNOWN` |
| `SupplierPayment` | **none** — only a contemporaneous shadow | usually `HISTORICAL_TILL_UNKNOWN` |

`CustomerPayment` and `SupplierPayment` have no drawer columns at all. When no shadow links them to a
shift with a `till_id`, they are `HISTORICAL_TILL_UNKNOWN` by construction — and an explicit attestation
is the only correct way to place them.

## 7. Operator procedure for evidence-less rows

1. Run the read-only probe: `python -m app.tools.cash_reconcile_probe --json`.
2. Rows classified `HISTORICAL_TILL_UNKNOWN` need evidence — **not** a new TILL.
3. Decide, from real-world records (drawer count sheets, a single-drawer shop's history, terminal logs),
   which drawer held that cash.
4. Write it into a `HISTORICAL_TILL_EVIDENCE` file with a real `evidence` note per entry.
5. Re-run the dry-run to get a new `manifest_hash`, then apply with `--approved-hash` and
   `--historical-till-map`.
6. Rows you cannot attest honestly should stay unresolved. An unreconstructed row is recoverable;
   a wrongly attributed one silently corrupts a drawer's history.

## 8. Worked examples

**Example 1 — provisioning today proves nothing.**
A cash payment from 2026-01 carries no `till_id`, no `shift_id`, no shadow. The operator creates `TILL-01`
in 2026-09. That row **cannot** be assigned to `TILL-01`: the drawer did not exist in the record when the
cash moved, and nothing ties the two together. Classification: `HISTORICAL_TILL_UNKNOWN`. The fix is
evidence or an attestation — *not* provisioning.

**Example 2 — an ARCHIVED drawer is still the right answer.**
A historical shift has `till_id = TILL-02`. `TILL-02` is ARCHIVED today. The old payment still resolves to
`TILL-02` via `SHIFT_TILL`: deactivating a drawer today must not invalidate the history it holds. Historical
resolution therefore does **not** require `status = ACTIVE`; only the *runtime* path does.

**Example 3 — a terminal is not a drawer.**
A row carries `terminal_id = T-7`, and `T-7` currently points at `TILL-03`. Because that binding lives in a
mutable, unversioned label — and the drawer row itself can be deleted and recreated while unreferenced —
this is **not** historical proof. The row stays `HISTORICAL_TILL_UNKNOWN` unless a persisted `till_id`, its
shift, its own shadow, or an explicit attestation says otherwise.
