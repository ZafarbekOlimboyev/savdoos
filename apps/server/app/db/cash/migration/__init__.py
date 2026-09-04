"""Cash Ledger — Migration toolkit.

Phase 0 (Prepare & Production Readiness): READ-ONLY inventory/mapping/audit + a
REPORT-ONLY backfill dry-run + idempotent CashAccount provisioning PLAN. Nothing here
writes to `cash.cash_ledger_entries` (only CashPostingService may). Historical backfill
and cutover are LATER phases and are NOT performed here.
"""
from app.db.cash.migration import phase0  # noqa: F401
