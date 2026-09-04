-- ============================================================================
-- SavdoOS · Cash Subsystem · PostgreSQL DDL v1.0 — Integrity Correction (CF-D1…CF-D6, M1, M2)
-- Target: PostgreSQL 16+
-- Faithful to: Target Architecture v1.1 (RATIFIED) + Relational Schema v1.1 (DDL READY).
-- Scope: DDL + enums + composite keys + partial indexes + deferred triggers + append-only guards + privileges.
-- NOT included (by design): ORM, API, service code, migration-framework code, frontend.
--
-- ── REPOSITORY BINDING (Implementation Phase 1) ─────────────────────────────
--   The spec's abstract tenant table `public.tenants` binds to SavdoOS's real tenant
--   table `public.companies` (in SavdoOS the tenant IS the company; PK id is UUID, matching
--   the spec). This is the ONLY change from the ratified DDL and it is a semantics-preserving
--   binding, NOT a redesign: the `tenant_id` columns keep their name and simply reference
--   `public.companies(id)`. `public.branches` and `public.employees` match by name (both UUID PK).
--   The 9 cash tables, every constraint, trigger, index and privilege are byte-identical to the
--   verified DDL (empirically proven 47/47 on PostgreSQL 16).
--
-- ENTITY COUNT (M1): 9 cash-domain tables — cash_accounts, cash_transfers, shifts,
--   reconciliation_records, cash_ledger_entries, reconciliation_assignments,
--   negative_cash_approvals, cash_ledger_exceptions, audit_logs.
--   PLUS 3 pre-existing tables that are REFERENCED, not created/altered:
--   public.companies (tenant), public.branches, public.employees (PK id UUID).
--
-- CORRECTIONS IN THIS REVISION:
--   CF-D1 transfer integrity is complete (orphan header + incomplete group rejected at COMMIT)
--   CF-D2 OFF_SHIFT assignment is pinned to the entry's own CashAccount (declarative composite FKs)
--   CF-D3 RECONSTRUCTION requires reason AND source_ref; NORMAL requires both NULL
--   CF-D4 ACCOUNT-target reconciliation must target a SAFE (declarative); SHIFT-target stays TILL-only
--   CF-D5 negative approval entry must be direction=OUT AND account_type=TILL, same account
--   CF-D6 role/ownership model made internally consistent (external migration owner; cash_admin = grant role)
--   M2    declarative biconditional: TRANSFER category <-> transfer_group_id present
--
-- COLLISION SAFETY: all cash-ledger objects live in a dedicated schema `cash`.
--   SavdoOS already has public.shifts, public.audit_logs, public.cash_movements, etc.
--   The `cash` schema keeps this subsystem separate and non-clobbering.
--
-- Cross-tenant enforcement to the pre-existing tables would require them to expose
--   UNIQUE(tenant_id, id). We are instructed NOT to alter them, so references to them are
--   single-column existence FKs and the "referenced branch/employee is in the same tenant"
--   check is SERVICE-LEVEL. All CASH-DOMAIN references are fully tenant-scoped composite FKs.
-- ============================================================================

-- ── A. Extensions / prerequisites ──────────────────────────────────────────
-- gen_random_uuid() is built into PostgreSQL 13+ core; no extension required.

CREATE SCHEMA IF NOT EXISTS cash;
SET search_path TO cash, public;

-- ── B. Enum types (controlled values) ──────────────────────────────────────
CREATE TYPE cash.cash_account_type   AS ENUM ('TILL','SAFE');
CREATE TYPE cash.cash_account_status AS ENUM ('ACTIVE','ARCHIVED');
CREATE TYPE cash.cash_shift_status   AS ENUM ('OPEN','CLOSING','CLOSED');
CREATE TYPE cash.cash_posting_kind   AS ENUM ('ON_SHIFT','OFF_SHIFT','LATE_SYNC');
CREATE TYPE cash.cash_direction      AS ENUM ('IN','OUT');
CREATE TYPE cash.cash_provenance     AS ENUM ('NORMAL','RECONSTRUCTION');
CREATE TYPE cash.cash_recon_target   AS ENUM ('SHIFT','ACCOUNT');
CREATE TYPE cash.cash_recon_state    AS ENUM ('PENDING','EXCEPTION','RECONCILED');
CREATE TYPE cash.cash_exception_kind AS ENUM ('TIMESTAMP_OUT_OF_WINDOW','UNRESOLVED_OFF_SHIFT','NEGATIVE_OVERRIDE','LATE_SYNC_UNACK');
CREATE TYPE cash.cash_exception_state AS ENUM ('OPEN','RESOLVED');
CREATE TYPE cash.cash_source_type    AS ENUM ('SALE','RETURN','CUSTOMER_PAYMENT','SUPPLIER_PAYMENT','PURCHASE','PURCHASE_RETURN','CASH_OP','TRANSFER','SHIFT_OPEN');
CREATE TYPE cash.cash_category       AS ENUM ('OPENING','SALE','REFUND','DEBT_IN','SUPPLIER_OUT','PURCHASE_OUT','PURCHASE_RETURN','EXPENSE','CASH_IN','CASH_OUT','TRANSFER','BANK_DEPOSIT','ADJUSTMENT');
-- NOTE: VOIDED is intentionally absent (ratified: corrections are reversing entries).

-- ── D. cash_accounts ────────────────────────────────────────────────────────
CREATE TABLE cash.cash_accounts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES public.companies(id),
    branch_id   uuid NOT NULL REFERENCES public.branches(id),   -- existence FK; same-tenant is service-level (§I)
    type        cash.cash_account_type   NOT NULL,
    currency    char(3)                  NOT NULL,
    status      cash.cash_account_status NOT NULL DEFAULT 'ACTIVE',
    label       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- Tenant-scoped composite keys that back child composite FKs (not business duplicates):
    CONSTRAINT ca_uq_tenant_id          UNIQUE (tenant_id, id),
    CONSTRAINT ca_uq_tenant_id_currency UNIQUE (tenant_id, id, currency),
    CONSTRAINT ca_uq_tenant_id_branch   UNIQUE (tenant_id, id, branch_id),
    CONSTRAINT ca_uq_tenant_id_type     UNIQUE (tenant_id, id, type)
);
COMMENT ON TABLE cash.cash_accounts IS 'Physical cash container: TILL (drawer) or SAFE. One currency per account. Authority for branch_id.';

-- ── E. cash_transfers (header for intra-custody TILL/SAFE moves) ────────────
CREATE TABLE cash.cash_transfers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    from_account_id uuid NOT NULL,
    to_account_id   uuid NOT NULL,
    amount          numeric(14,2) NOT NULL,
    currency        char(3) NOT NULL,
    actor_id        uuid REFERENCES public.employees(id),
    occurred_at     timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ct_amount_pos CHECK (amount > 0),
    CONSTRAINT ct_no_self    CHECK (from_account_id <> to_account_id),
    -- from/to must be same-tenant accounts AND share this header's currency (declarative):
    CONSTRAINT ct_from_cur_fk FOREIGN KEY (tenant_id, from_account_id, currency)
        REFERENCES cash.cash_accounts (tenant_id, id, currency),
    CONSTRAINT ct_to_cur_fk   FOREIGN KEY (tenant_id, to_account_id, currency)
        REFERENCES cash.cash_accounts (tenant_id, id, currency),
    CONSTRAINT ct_uq_tenant_id UNIQUE (tenant_id, id)
);
COMMENT ON TABLE cash.cash_transfers IS 'Intra-custody transfer header (TILL<->SAFE). BANK_DEPOSIT is NOT represented here. Legs reference this via transfer_group_id.';

-- ── F. shifts (mutable lifecycle; belongs to exactly one TILL) ──────────────
CREATE TABLE cash.shifts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    cash_account_id uuid NOT NULL,
    branch_id       uuid NOT NULL,                       -- enforced derived copy of the account's branch
    account_type    cash.cash_account_type NOT NULL,     -- enforced derived copy; must be TILL
    status          cash.cash_shift_status NOT NULL DEFAULT 'OPEN',
    opened_at       timestamptz NOT NULL DEFAULT now(),
    closed_at       timestamptz,
    opened_by       uuid REFERENCES public.employees(id),
    closed_by       uuid REFERENCES public.employees(id),
    version         bigint NOT NULL DEFAULT 1,
    CONSTRAINT sh_type_till     CHECK (account_type = 'TILL'),
    CONSTRAINT sh_closed_iff    CHECK ((status = 'CLOSED') = (closed_at IS NOT NULL)),
    CONSTRAINT sh_window        CHECK (closed_at IS NULL OR closed_at > opened_at),  -- [opened_at, closed_at)
    -- only a TILL account, in the same tenant, may own a shift (declarative):
    CONSTRAINT sh_acct_type_fk  FOREIGN KEY (tenant_id, cash_account_id, account_type)
        REFERENCES cash.cash_accounts (tenant_id, id, type),
    CONSTRAINT sh_acct_branch_fk FOREIGN KEY (tenant_id, cash_account_id, branch_id)
        REFERENCES cash.cash_accounts (tenant_id, id, branch_id),
    CONSTRAINT sh_uq_tenant_id         UNIQUE (tenant_id, id),
    CONSTRAINT sh_uq_tenant_id_account UNIQUE (tenant_id, id, cash_account_id)   -- backs the entry's shift-account FK
);
-- At most one OPEN shift per CashAccount:
CREATE UNIQUE INDEX sh_one_open_per_account ON cash.shifts (cash_account_id) WHERE status = 'OPEN';
COMMENT ON TABLE cash.shifts IS 'Work session on one TILL. OPEN->CLOSING->CLOSED; audited reopen CLOSED->OPEN (service-controlled). SAFE never owns a shift.';

-- ── G. reconciliation_records (1:N per target; TILL close OR SAFE count) ─────
CREATE TABLE cash.reconciliation_records (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    target_type     cash.cash_recon_target NOT NULL,
    shift_id        uuid,
    cash_account_id uuid,
    account_type    cash.cash_account_type,               -- CF-D4: for ACCOUNT target only; must be SAFE
    seq             integer NOT NULL,
    is_current      boolean NOT NULL DEFAULT true,
    ledger_balance_snapshot numeric(14,2) NOT NULL,       -- immutable once written
    counted_cash    numeric(14,2),                         -- immutable once written
    difference      numeric(14,2),                         -- immutable once written
    state           cash.cash_recon_state NOT NULL DEFAULT 'PENDING',   -- mutable
    exception_reason text,                                 -- mutable
    resolved_by     uuid REFERENCES public.employees(id),  -- mutable
    resolved_at     timestamptz,                           -- mutable
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rr_seq_pos CHECK (seq >= 1),
    CONSTRAINT rr_target_exactly_one CHECK (
        (target_type = 'SHIFT'   AND shift_id IS NOT NULL AND cash_account_id IS NULL) OR
        (target_type = 'ACCOUNT' AND cash_account_id IS NOT NULL AND shift_id IS NULL)
    ),
    -- CF-D4: ACCOUNT-count reconciliation is a SAFE-only path; SHIFT target carries no account_type.
    CONSTRAINT rr_account_target_safe CHECK (
        (target_type = 'ACCOUNT' AND account_type = 'SAFE') OR
        (target_type = 'SHIFT'   AND account_type IS NULL)
    ),
    CONSTRAINT rr_shift_fk   FOREIGN KEY (tenant_id, shift_id)        REFERENCES cash.shifts (tenant_id, id),
    -- CF-D4: composite FK forces the ACCOUNT target's account to actually be of type SAFE.
    -- SHIFT target (both cash_account_id and account_type NULL) is skipped via MATCH SIMPLE.
    CONSTRAINT rr_account_type_fk FOREIGN KEY (tenant_id, cash_account_id, account_type)
        REFERENCES cash.cash_accounts (tenant_id, id, type),
    CONSTRAINT rr_uq_tenant_id UNIQUE (tenant_id, id)
);
-- seq unique per target; exactly one current per target:
CREATE UNIQUE INDEX rr_uq_shift_seq     ON cash.reconciliation_records (tenant_id, shift_id, seq)        WHERE shift_id IS NOT NULL;
CREATE UNIQUE INDEX rr_uq_account_seq   ON cash.reconciliation_records (tenant_id, cash_account_id, seq) WHERE cash_account_id IS NOT NULL;
CREATE UNIQUE INDEX rr_current_shift    ON cash.reconciliation_records (shift_id)        WHERE is_current AND shift_id IS NOT NULL;
CREATE UNIQUE INDEX rr_current_account  ON cash.reconciliation_records (cash_account_id) WHERE is_current AND cash_account_id IS NOT NULL;
COMMENT ON TABLE cash.reconciliation_records IS 'Reconciles a TILL shift-close OR a SAFE account-count. 1:N per target (seq/is_current). Snapshot columns immutable; state/is_current/resolved_* mutable.';

-- ── H. cash_ledger_entries (immutable, append-only; the cash authority) ─────
CREATE TABLE cash.cash_ledger_entries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    cash_account_id uuid NOT NULL,
    branch_id       uuid NOT NULL,                       -- enforced derived copy of account.branch
    account_type    cash.cash_account_type NOT NULL,     -- enforced derived copy (backs the TILL-only OFF_SHIFT queue)
    shift_id        uuid,                                 -- NULL only for OFF_SHIFT
    posting_kind    cash.cash_posting_kind NOT NULL,
    source_type     cash.cash_source_type  NOT NULL,
    source_id       uuid NOT NULL,                        -- LOGICAL reference (source_type qualifies it); NOT an FK
    leg_index       integer NOT NULL DEFAULT 0,
    direction       cash.cash_direction NOT NULL,
    category        cash.cash_category  NOT NULL,
    amount          numeric(14,2) NOT NULL,               -- always > 0; sign is in direction
    currency        char(3) NOT NULL,                     -- must equal account currency
    device_occurred_at timestamptz NOT NULL,              -- authoritative accounting time; never rewritten
    server_received_at timestamptz NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    actor_id        uuid REFERENCES public.employees(id),
    idempotency_key text NOT NULL,                        -- transport replay key
    reverses_id     uuid,                                 -- full reversal only (never a partial refund)
    transfer_group_id uuid,                               -- set for TRANSFER legs only
    origin_device_id text,
    provenance      cash.cash_provenance NOT NULL DEFAULT 'NORMAL',
    reconstruction_reason     text,                       -- required iff RECONSTRUCTION
    reconstruction_source_ref text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- non-authoritative

    CONSTRAINT cle_amount_pos   CHECK (amount > 0),
    CONSTRAINT cle_leg_nonneg   CHECK (leg_index >= 0),
    CONSTRAINT cle_no_self_rev  CHECK (reverses_id IS NULL OR reverses_id <> id),
    CONSTRAINT cle_posting_shift CHECK (
        (posting_kind IN ('ON_SHIFT','LATE_SYNC') AND shift_id IS NOT NULL) OR
        (posting_kind = 'OFF_SHIFT' AND shift_id IS NULL)
    ),
    -- CF-D3: RECONSTRUCTION requires BOTH reason and source_ref; NORMAL requires BOTH NULL.
    CONSTRAINT cle_recon_prov CHECK (
        (provenance = 'RECONSTRUCTION' AND reconstruction_reason IS NOT NULL AND reconstruction_source_ref IS NOT NULL) OR
        (provenance = 'NORMAL'         AND reconstruction_reason IS NULL     AND reconstruction_source_ref IS NULL)
    ),
    -- M2 / CF-D1: TRANSFER category <-> transfer_group_id present (biconditional; no documented exception).
    -- BANK_DEPOSIT (category BANK_DEPOSIT, group NULL) satisfies this and stays NOT a transfer.
    CONSTRAINT cle_transfer_group_iff CHECK ((category = 'TRANSFER') = (transfer_group_id IS NOT NULL)),
    -- Integrity composite FKs (tenant + branch + currency + type all forced to match the account):
    CONSTRAINT cle_acct_currency_fk FOREIGN KEY (tenant_id, cash_account_id, currency)
        REFERENCES cash.cash_accounts (tenant_id, id, currency),
    CONSTRAINT cle_acct_branch_fk   FOREIGN KEY (tenant_id, cash_account_id, branch_id)
        REFERENCES cash.cash_accounts (tenant_id, id, branch_id),
    CONSTRAINT cle_acct_type_fk     FOREIGN KEY (tenant_id, cash_account_id, account_type)
        REFERENCES cash.cash_accounts (tenant_id, id, type),
    -- shift (when present) must belong to the same tenant AND same account; NULL shift_id skips (MATCH SIMPLE) => OFF_SHIFT:
    CONSTRAINT cle_shift_fk FOREIGN KEY (tenant_id, shift_id, cash_account_id)
        REFERENCES cash.shifts (tenant_id, id, cash_account_id),
    CONSTRAINT cle_reverses_fk FOREIGN KEY (tenant_id, reverses_id)
        REFERENCES cash.cash_ledger_entries (tenant_id, id),
    CONSTRAINT cle_transfer_fk FOREIGN KEY (tenant_id, transfer_group_id)
        REFERENCES cash.cash_transfers (tenant_id, id),
    -- Business uniqueness / idempotency / replay key:
    CONSTRAINT cle_uq_business  UNIQUE (tenant_id, source_type, source_id, leg_index),
    CONSTRAINT cle_uq_tenant_id UNIQUE (tenant_id, id),
    CONSTRAINT cle_uq_tenant_id_account UNIQUE (tenant_id, id, cash_account_id),  -- backs approval's account-match FK
    CONSTRAINT cle_uq_id_dir_type       UNIQUE (tenant_id, id, direction, account_type)  -- CF-D5: backs approval's OUT/TILL FK
);
-- One original may have at most one FULL reversal:
CREATE UNIQUE INDEX cle_uq_reverses ON cash.cash_ledger_entries (reverses_id) WHERE reverses_id IS NOT NULL;
-- CF-D1: at most one OUT and one IN leg per transfer group (blocks a third/duplicate leg declaratively).
CREATE UNIQUE INDEX cle_uq_transfer_leg ON cash.cash_ledger_entries (transfer_group_id, direction) WHERE transfer_group_id IS NOT NULL;
COMMENT ON TABLE cash.cash_ledger_entries IS 'Append-only, immutable. One signed physical-cash leg. SAFE legs are always OFF_SHIFT (SAFE owns no shift). source_id is a logical reference.';

-- ── I. reconciliation_assignments (append-only; OFF_SHIFT -> shift) ──────────
CREATE TABLE cash.reconciliation_assignments (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES public.companies(id),
    entry_id          uuid NOT NULL,
    assigned_shift_id uuid NOT NULL,
    cash_account_id   uuid NOT NULL,               -- CF-D2: immutable copy tying entry & shift to ONE account
    actor_id          uuid REFERENCES public.employees(id),
    reason            text,
    assigned_at       timestamptz NOT NULL DEFAULT now(),
    -- CF-D2: the entry must belong to cash_account_id ...
    CONSTRAINT ra_entry_account_fk FOREIGN KEY (tenant_id, entry_id, cash_account_id)
        REFERENCES cash.cash_ledger_entries (tenant_id, id, cash_account_id),
    -- ... and the assigned shift must belong to the SAME account => entry.account = shift.account.
    CONSTRAINT ra_shift_account_fk FOREIGN KEY (tenant_id, assigned_shift_id, cash_account_id)
        REFERENCES cash.shifts (tenant_id, id, cash_account_id),
    CONSTRAINT ra_uq_tenant_id UNIQUE (tenant_id, id),
    CONSTRAINT ra_uq_entry     UNIQUE (tenant_id, entry_id)          -- one assignment per entry
);
COMMENT ON TABLE cash.reconciliation_assignments IS 'Logical OFF_SHIFT->shift attribution, pinned to the entry''s own CashAccount (CF-D2). Never mutates the entry; append-only. Target entry must be OFF_SHIFT (trigger).';

-- ── J. negative_cash_approvals (append-only) ────────────────────────────────
CREATE TABLE cash.negative_cash_approvals (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES public.companies(id),
    entry_id            uuid NOT NULL,
    cash_account_id     uuid NOT NULL,
    direction           cash.cash_direction    NOT NULL,   -- CF-D5: must be OUT (enforced below)
    account_type        cash.cash_account_type NOT NULL,   -- CF-D5: must be TILL (enforced below)
    approver_id         uuid REFERENCES public.employees(id),
    reason              text NOT NULL,
    amount              numeric(14,2) NOT NULL,
    till_balance_before numeric(14,2) NOT NULL,
    till_balance_after  numeric(14,2) NOT NULL,
    authorized_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT nca_amount_pos CHECK (amount > 0),
    -- CF-D5: a negative-till override only applies to an OUT leg on a TILL.
    CONSTRAINT nca_scope CHECK (direction = 'OUT' AND account_type = 'TILL'),
    -- entry + account must match (declarative, via the entry's (tenant,id,account) key):
    CONSTRAINT nca_entry_account_fk FOREIGN KEY (tenant_id, entry_id, cash_account_id)
        REFERENCES cash.cash_ledger_entries (tenant_id, id, cash_account_id),
    -- CF-D5: the referenced entry must actually be OUT and on a TILL (composite FK to the entry's own columns):
    CONSTRAINT nca_entry_dirtype_fk FOREIGN KEY (tenant_id, entry_id, direction, account_type)
        REFERENCES cash.cash_ledger_entries (tenant_id, id, direction, account_type),
    CONSTRAINT nca_account_fk FOREIGN KEY (tenant_id, cash_account_id) REFERENCES cash.cash_accounts (tenant_id, id),
    CONSTRAINT nca_uq_tenant_id UNIQUE (tenant_id, id),
    CONSTRAINT nca_uq_entry     UNIQUE (tenant_id, entry_id)         -- one approval per entry
);
COMMENT ON TABLE cash.negative_cash_approvals IS 'Authorizes an OUT that drove a TILL negative (CF-D5: entry is OUT + TILL, same account). Complete before/after audit. One per entry. Authorization LEVEL stays service-level.';

-- ── K. cash_ledger_exceptions (entry-level anomalies; state mutable) ────────
CREATE TABLE cash.cash_ledger_exceptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES public.companies(id),
    entry_id    uuid NOT NULL,
    kind        cash.cash_exception_kind  NOT NULL,
    state       cash.cash_exception_state NOT NULL DEFAULT 'OPEN',
    reason      text,
    resolved_by uuid REFERENCES public.employees(id),
    resolved_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cx_resolved_iff CHECK ((state = 'RESOLVED') = (resolved_at IS NOT NULL)),
    CONSTRAINT cx_entry_fk FOREIGN KEY (tenant_id, entry_id) REFERENCES cash.cash_ledger_entries (tenant_id, id),
    CONSTRAINT cx_uq_tenant_id UNIQUE (tenant_id, id)
);
-- At most one OPEN exception of a given kind per entry (repeat lifecycle allowed after RESOLVED):
CREATE UNIQUE INDEX cx_one_open_per_kind ON cash.cash_ledger_exceptions (entry_id, kind) WHERE state = 'OPEN';
COMMENT ON TABLE cash.cash_ledger_exceptions IS 'Entry-level anomaly (Case-B timestamp, off-shift, negative override, late-sync unack) resolved WITHOUT mutating the entry.';

-- ── L. audit_logs (cash subsystem audit surface; append-only) ───────────────
-- NOTE: kept in schema `cash` to avoid colliding with SavdoOS's existing public.audit_logs
-- (which has a different shape and no tenant_id). If integrating, map fields to the existing surface.
CREATE TABLE cash.audit_logs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES public.companies(id),
    actor_id    uuid REFERENCES public.employees(id),           -- NULL for vendor/back-office
    action      text NOT NULL,
    entity_type text NOT NULL,                                   -- logical reference
    entity_id   uuid,                                            -- logical reference
    before      jsonb,
    after       jsonb,
    reason      text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE cash.audit_logs IS 'Append-only trail of human financial decisions (assignment, ack, adjustment, reversal, override, cross-branch, reopen). entity_type/entity_id are logical references.';

-- ── M. Functions ────────────────────────────────────────────────────────────

-- M1. Block all UPDATE/DELETE on fully append-only tables (defense-in-depth alongside privileges).
CREATE OR REPLACE FUNCTION cash.fn_block_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not permitted: append-only immutable table', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END $$;

-- M1b. Block TRUNCATE on append-only tables. Row triggers NEVER fire for TRUNCATE, so a separate
--      statement-level BEFORE TRUNCATE guard is required — without it, TRUNCATE bypasses fn_block_mutation
--      entirely and could erase an immutable table. Fires for every role (incl. owner) while enabled.
CREATE OR REPLACE FUNCTION cash.fn_block_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE on % is not permitted: append-only immutable table', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END $$;

-- M2. cash_accounts: forbid changing immutable ownership/type/currency (status/label remain mutable).
CREATE OR REPLACE FUNCTION cash.fn_guard_cash_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id <> OLD.tenant_id OR NEW.branch_id <> OLD.branch_id
       OR NEW.type <> OLD.type OR NEW.currency <> OLD.currency OR NEW.id <> OLD.id THEN
        RAISE EXCEPTION 'cash_accounts: tenant/branch/type/currency/id are immutable';
    END IF;
    RETURN NEW;
END $$;

-- M3. reconciliation_records: snapshot & target columns immutable; state/is_current/resolved_* mutable.
CREATE OR REPLACE FUNCTION cash.fn_guard_recon() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.target_type <> OLD.target_type
       OR NEW.shift_id IS DISTINCT FROM OLD.shift_id
       OR NEW.cash_account_id IS DISTINCT FROM OLD.cash_account_id
       OR NEW.account_type IS DISTINCT FROM OLD.account_type
       OR NEW.seq <> OLD.seq
       OR NEW.ledger_balance_snapshot <> OLD.ledger_balance_snapshot
       -- "immutable ONCE written": allow the first NULL -> value write; block any later change or erase.
       OR (OLD.counted_cash IS NOT NULL AND NEW.counted_cash IS DISTINCT FROM OLD.counted_cash)
       OR (OLD.difference   IS NOT NULL AND NEW.difference   IS DISTINCT FROM OLD.difference)
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'reconciliation_records: snapshot/target columns are immutable';
    END IF;
    RETURN NEW;
END $$;

-- M4. cash_ledger_exceptions: entry_id/kind/created_at immutable; state/resolved_* mutable.
CREATE OR REPLACE FUNCTION cash.fn_guard_exception() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.entry_id <> OLD.entry_id OR NEW.kind <> OLD.kind
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'cash_ledger_exceptions: entry_id/kind/tenant/created_at are immutable';
    END IF;
    RETURN NEW;
END $$;

-- M5. reconciliation_assignments: the target entry MUST be OFF_SHIFT (cross-table, not a simple constraint).
CREATE OR REPLACE FUNCTION cash.fn_assignment_off_shift() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_pk cash.cash_posting_kind;
BEGIN
    SELECT posting_kind INTO v_pk FROM cash.cash_ledger_entries
        WHERE id = NEW.entry_id AND tenant_id = NEW.tenant_id;
    IF v_pk IS NULL THEN
        RAISE EXCEPTION 'reconciliation_assignment: entry % not found for tenant', NEW.entry_id;
    ELSIF v_pk <> 'OFF_SHIFT' THEN
        RAISE EXCEPTION 'reconciliation_assignment: entry must be OFF_SHIFT (got %)', v_pk;
    END IF;
    RETURN NEW;
END $$;

-- M6 / CF-D1. Deferred transfer-group validation. Runs from BOTH the header (cash_transfers) and each
--   TRANSFER leg (cash_ledger_entries), so an orphan header with ZERO legs is caught at COMMIT just as an
--   incomplete or mismatched leg set is. A TRANSFER group must be exactly one OUT + one IN, equal amount &
--   currency, OUT.account = from_account_id, IN.account = to_account_id, both category = TRANSFER.
--   BANK_DEPOSIT (no group) is exempt. Read-only => cannot recurse.
CREATE OR REPLACE FUNCTION cash.fn_validate_transfer_group() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_gid uuid; v_tid uuid; v_out int; v_in int; v_matched int;
BEGIN
    IF TG_TABLE_NAME = 'cash_transfers' THEN
        v_gid := NEW.id;                 -- header path: validate the group this header owns
        v_tid := NEW.tenant_id;
    ELSE
        -- leg path: only TRANSFER legs are paired; everything else (incl. BANK_DEPOSIT) is exempt.
        IF NEW.transfer_group_id IS NULL OR NEW.category <> 'TRANSFER' THEN
            RETURN NULL;
        END IF;
        v_gid := NEW.transfer_group_id;
        v_tid := NEW.tenant_id;
    END IF;

    SELECT count(*) FILTER (WHERE direction = 'OUT'),
           count(*) FILTER (WHERE direction = 'IN')
      INTO v_out, v_in
      FROM cash.cash_ledger_entries
     WHERE transfer_group_id = v_gid;
    IF v_out <> 1 OR v_in <> 1 THEN
        RAISE EXCEPTION 'transfer group %: must have exactly one OUT and one IN leg (out=%, in=%)', v_gid, v_out, v_in;
    END IF;

    SELECT count(*) INTO v_matched
      FROM cash.cash_transfers t
      JOIN cash.cash_ledger_entries o ON o.transfer_group_id = t.id AND o.direction = 'OUT'
      JOIN cash.cash_ledger_entries i ON i.transfer_group_id = t.id AND i.direction = 'IN'
     WHERE t.id = v_gid AND t.tenant_id = v_tid
       AND o.tenant_id = t.tenant_id AND i.tenant_id = t.tenant_id
       AND o.cash_account_id = t.from_account_id AND i.cash_account_id = t.to_account_id
       AND o.amount = t.amount AND i.amount = t.amount
       AND o.currency = t.currency AND i.currency = t.currency
       AND o.category = 'TRANSFER' AND i.category = 'TRANSFER';
    IF v_matched <> 1 THEN
        RAISE EXCEPTION 'transfer group %: legs do not match header (accounts / amount / currency / category)', v_gid;
    END IF;
    RETURN NULL;
END $$;

-- ── N. Triggers ─────────────────────────────────────────────────────────────
-- Append-only: block UPDATE & DELETE on immutable tables.
CREATE TRIGGER trg_cle_immutable  BEFORE UPDATE OR DELETE ON cash.cash_ledger_entries        FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_ct_immutable   BEFORE UPDATE OR DELETE ON cash.cash_transfers             FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_ra_immutable   BEFORE UPDATE OR DELETE ON cash.reconciliation_assignments FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_nca_immutable  BEFORE UPDATE OR DELETE ON cash.negative_cash_approvals    FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_al_immutable   BEFORE UPDATE OR DELETE ON cash.audit_logs                 FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();

-- Append-only: block TRUNCATE too (statement-level; row triggers do NOT fire on TRUNCATE).
CREATE TRIGGER trg_cle_no_truncate BEFORE TRUNCATE ON cash.cash_ledger_entries        FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_ct_no_truncate  BEFORE TRUNCATE ON cash.cash_transfers             FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_ra_no_truncate  BEFORE TRUNCATE ON cash.reconciliation_assignments FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_nca_no_truncate BEFORE TRUNCATE ON cash.negative_cash_approvals    FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_al_no_truncate  BEFORE TRUNCATE ON cash.audit_logs                 FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_rr_no_truncate  BEFORE TRUNCATE ON cash.reconciliation_records     FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();
CREATE TRIGGER trg_cx_no_truncate  BEFORE TRUNCATE ON cash.cash_ledger_exceptions     FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate();

-- Partially-mutable tables: block DELETE, guard immutable columns on UPDATE.
CREATE TRIGGER trg_rr_no_delete   BEFORE DELETE ON cash.reconciliation_records FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_rr_guard       BEFORE UPDATE ON cash.reconciliation_records FOR EACH ROW EXECUTE FUNCTION cash.fn_guard_recon();
CREATE TRIGGER trg_cx_no_delete   BEFORE DELETE ON cash.cash_ledger_exceptions FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation();
CREATE TRIGGER trg_cx_guard       BEFORE UPDATE ON cash.cash_ledger_exceptions FOR EACH ROW EXECUTE FUNCTION cash.fn_guard_exception();

-- cash_accounts immutable-ownership guard (allow status/label changes).
CREATE TRIGGER trg_ca_guard BEFORE UPDATE ON cash.cash_accounts FOR EACH ROW EXECUTE FUNCTION cash.fn_guard_cash_account();

-- reconciliation_assignment target must be OFF_SHIFT.
CREATE TRIGGER trg_ra_off_shift BEFORE INSERT ON cash.reconciliation_assignments FOR EACH ROW EXECUTE FUNCTION cash.fn_assignment_off_shift();

-- Deferred transfer pairing — leg side (fires at COMMIT so both legs may be inserted first).
CREATE CONSTRAINT TRIGGER trg_transfer_pair
    AFTER INSERT ON cash.cash_ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION cash.fn_validate_transfer_group();

-- CF-D1: header side. Catches an ORPHAN header (inserted with zero legs) at COMMIT — the leg-side
-- trigger cannot fire when no leg exists, so this is required for complete transfer integrity.
CREATE CONSTRAINT TRIGGER trg_transfer_header_complete
    AFTER INSERT ON cash.cash_transfers
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION cash.fn_validate_transfer_group();

-- ── O. Indexes (access-pattern driven; no redundant indexes) ────────────────
-- Live expected cash / shift close: sum of a shift's ON_SHIFT legs (covering).
CREATE INDEX cle_ix_expected  ON cash.cash_ledger_entries (shift_id) INCLUDE (direction, amount) WHERE posting_kind = 'ON_SHIFT';
-- Cashflow + account balance (both TILL and SAFE), by tenant/account/time.
CREATE INDEX cle_ix_cashflow  ON cash.cash_ledger_entries (tenant_id, cash_account_id, device_occurred_at) INCLUDE (direction, category, amount);
-- Late-sync per shift (post-close adjustments).
CREATE INDEX cle_ix_late_sync ON cash.cash_ledger_entries (shift_id) WHERE posting_kind = 'LATE_SYNC';
-- OFF_SHIFT anomaly queue -- TILL only (SAFE OFF_SHIFT legs excluded via account_type).
CREATE INDEX cle_ix_off_shift ON cash.cash_ledger_entries (tenant_id, cash_account_id, device_occurred_at)
    WHERE posting_kind = 'OFF_SHIFT' AND account_type = 'TILL';
-- Transfer leg lookup.
CREATE INDEX cle_ix_transfer  ON cash.cash_ledger_entries (transfer_group_id) WHERE transfer_group_id IS NOT NULL;
-- (Business-uniqueness index cle_uq_business also serves source-prefix lookup; cle_uq_reverses serves reversal lookup.)

-- Exception queue (OPEN) + per-entry lookup.
CREATE INDEX cx_ix_open_queue ON cash.cash_ledger_exceptions (tenant_id, state, kind) WHERE state = 'OPEN';
CREATE INDEX cx_ix_entry      ON cash.cash_ledger_exceptions (entry_id);

-- Audit lookups.
CREATE INDEX al_ix_entity ON cash.audit_logs (tenant_id, entity_type, entity_id, occurred_at);
CREATE INDEX al_ix_actor  ON cash.audit_logs (tenant_id, actor_id, occurred_at);

-- ── P. Roles & privileges (least privilege; triggers are defense-in-depth) ──
-- Create roles only if absent (NOLOGIN group roles; grant to real login users separately).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_posting')  THEN CREATE ROLE cash_posting  NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_app')      THEN CREATE ROLE cash_app      NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_readonly') THEN CREATE ROLE cash_readonly NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_admin')    THEN CREATE ROLE cash_admin    NOLOGIN; END IF;
END $$;

GRANT USAGE ON SCHEMA cash TO cash_posting, cash_app, cash_readonly, cash_admin;

-- Reporting: read-only.
GRANT SELECT ON ALL TABLES IN SCHEMA cash TO cash_readonly;

-- General application: read everything (writes go through the posting service).
GRANT SELECT ON ALL TABLES IN SCHEMA cash TO cash_app;

-- Posting service: the ONLY writer of the ledger. INSERT everywhere; UPDATE only where the model
-- permits process mutation (shift lifecycle, reconciliation state/is_current, exception state).
-- It is NOT granted UPDATE/DELETE on the immutable ledger/transfer/approval/audit tables.
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA cash TO cash_posting;
GRANT UPDATE ON cash.shifts                 TO cash_posting;   -- OPEN->CLOSING->CLOSED, reopen
GRANT UPDATE ON cash.reconciliation_records TO cash_posting;   -- state/is_current/resolved_* (guard trigger blocks snapshot changes)
GRANT UPDATE ON cash.cash_ledger_exceptions TO cash_posting;   -- state/resolved_* (guard trigger blocks entry_id/kind)
GRANT UPDATE ON cash.cash_accounts          TO cash_posting;   -- status/label (guard trigger blocks ownership/type/currency)
-- Explicitly ensure no UPDATE/DELETE on the immutable ledger reaches the posting service:
REVOKE UPDATE, DELETE ON cash.cash_ledger_entries, cash.cash_transfers,
                          cash.negative_cash_approvals, cash.reconciliation_assignments,
                          cash.audit_logs FROM cash_posting;

-- CF-D6 — OWNERSHIP MODEL (made internally consistent):
--   Object OWNERSHIP belongs to the external "migration owner" — the role that EXECUTES this file
--   (a dedicated deployment/DBA login or a CI migration role), NOT to any application role and NOT to
--   cash_admin. Only an object's owner (or a superuser) may ALTER/DROP it, so schema evolution is confined
--   to that migration owner. To pin ownership to a named role explicitly, run it AS that role, or:
--       ALTER SCHEMA cash OWNER TO <migration_owner>;
--       -- then ALTER TABLE/FUNCTION/TYPE ... OWNER TO <migration_owner>; for each object (or deploy under it).
--
--   cash_admin is an ADMINISTRATIVE GRANT ROLE ONLY — broad runtime privileges for maintenance/inspection,
--   but NOT the owner: it cannot ALTER/DROP objects. It is NOT a superuser and is NOT used by the app at
--   runtime. A genuine correction to an append-only table (temporarily disabling an immutable guard trigger
--   inside an audited transaction) requires OWNERSHIP, i.e. the migration owner — never cash_admin, never
--   an application role. Application roles (cash_app / cash_posting / cash_readonly) receive NO DDL powers.
GRANT ALL ON ALL TABLES IN SCHEMA cash TO cash_admin;
-- Immutability is not weakened for cash_admin. GRANT ALL confers UPDATE/DELETE *and TRUNCATE*; all three
-- would let a role empty or edit an append-only table, so all three are revoked on every append-only /
-- immutable-history table. (Defense-in-depth: fn_block_mutation blocks UPDATE/DELETE and fn_block_truncate
-- blocks TRUNCATE for EVERY role while the triggers are enabled, so this REVOKE is the privilege-layer twin.)
REVOKE UPDATE, DELETE, TRUNCATE ON
    cash.cash_ledger_entries, cash.cash_transfers, cash.negative_cash_approvals,
    cash.reconciliation_assignments, cash.audit_logs
    FROM cash_admin;
REVOKE TRUNCATE ON cash.reconciliation_records, cash.cash_ledger_exceptions FROM cash_admin;

-- Future tables in the schema inherit read grants for reporting/app (writers stay explicit).
ALTER DEFAULT PRIVILEGES IN SCHEMA cash GRANT SELECT ON TABLES TO cash_readonly, cash_app;

-- ============================================================================
-- END OF DDL.  See the accompanying notes document for: constraint map, trigger map,
-- index map, permission model, invariant traceability, acceptance-test mapping,
-- self-review, known service-level rules, and final verdict.
-- ============================================================================
