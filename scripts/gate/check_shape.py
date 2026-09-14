# -*- coding: utf-8 -*-
"""Assert the EXACT Phase 4A (+4A.1) migration shape from a compare_fp.py JSON.

Used for the production clone (pre-initdb vs post-initdb) AND for live production
(pre-deploy vs post-deploy). Connects to nothing.

    python check_shape.py compare.json

Allowed: the four Phase 4A tables with their own indexes/constraints, sale_items.provisional_qty,
ix_sale_items_sale_id + ux_ret_alloc_line on existing tables, the three production-missing
stock_batches FKs, ck_lot_shortfall_resolved_le_qty on lot_shortfalls, and the removal of the
legacy (return_item_id, stock_batch_id) uniqueness. Business rows: zero mismatch.
Anything else — extra, missing, altered or removed — fails.
"""
import json
import re
import sys

NEW_TABLES = {"public.lot_shortfall_resolution_requests", "public.lot_shortfall_resolutions",
              "public.return_item_shortfall_allocations", "public.return_item_resolution_allocations"}
NEW_TABLE_NAMES = {t.split(".", 1)[1] for t in NEW_TABLES}
COLUMNS = ["public.sale_items.provisional_qty"]
INDEXES_ON_EXISTING = {"public.ix_sale_items_sale_id": "sale_items", "public.ux_ret_alloc_line": "return_item_lot_allocations"}
REQUIRED_INDEXES = {"public.ix_sale_items_sale_id", "public.ux_ret_alloc_line", "public.ux_lsr_request_client",
                    "public.ux_lsr_request_lot", "public.ux_risa_item_shortfall", "public.ux_rira_item_resolution",
                    "public.ix_lsr_company_resolved", "public.ix_lsr_shortfall", "public.ix_lsr_sale_item",
                    "public.ix_rira_return", "public.ix_rira_resolution", "public.ix_risa_shortfall",
                    "public.ix_risa_created_batch"}
CONSTRAINTS_ON_EXISTING = {"stock_batches.stock_batches_company_id_fkey", "stock_batches.stock_batches_purchase_item_id_fkey",
                           "stock_batches.stock_batches_supplier_id_fkey", "lot_shortfalls.ck_lot_shortfall_resolved_le_qty"}
REQUIRED_CONSTRAINTS = CONSTRAINTS_ON_EXISTING | {
    "lot_shortfall_resolutions.ck_lsr_qty_pos", "lot_shortfall_resolutions.ck_lsr_variance_identity",
    "lot_shortfall_resolutions.ck_lsr_kind", "lot_shortfall_resolutions.ck_lsr_netting_zero",
    "return_item_shortfall_allocations.ck_risa_qty_pos", "return_item_resolution_allocations.ck_rira_qty_pos"}
ALLOWED_REMOVED = sorted(["public.ux_ret_alloc",
                          "public.return_item_lot_allocations_return_item_id_stock_batch_id_key",
                          "return_item_lot_allocations.return_item_lot_allocations_return_item_id_stock_batch_id_key"])


def main(path):
    c = json.load(open(path, encoding="utf-8"))
    bad = []
    if c.get("verdict") != "OK":
        bad.append(("compare verdict", c.get("verdict")))
    for k in ("business_row_mismatch", "tables_removed", "columns_removed", "columns_altered",
              "indexes_removed", "indexes_altered", "constraints_removed", "constraints_altered"):
        if c.get(k):
            bad.append((k, c[k]))
    if set(c.get("tables_added") or []) != NEW_TABLES:
        bad.append(("tables_added", c.get("tables_added")))
    cols = [x.split(" ")[0] for x in c.get("columns_added") or []]
    if cols != COLUMNS:
        bad.append(("columns_added", c.get("columns_added")))
    idx = {}
    for x in c.get("indexes_added") or []:
        name, ddl = x.split(":", 1)
        m = re.search(r" ON (?:ONLY )?(?:public\.)?(\w+)", ddl)
        idx[name] = m.group(1) if m else None
    for need in sorted(REQUIRED_INDEXES - set(idx)):
        bad.append(("missing index", need))
    for name, table in sorted(idx.items()):
        if table in NEW_TABLE_NAMES:
            continue
        if INDEXES_ON_EXISTING.get(name) != table:
            bad.append(("unexpected index on an existing table", name, table))
    cons = [x.split(":", 1)[0] for x in c.get("constraints_added") or []]
    for need in sorted(REQUIRED_CONSTRAINTS - set(cons)):
        bad.append(("missing constraint", need))
    for name in cons:
        if name.split(".", 1)[0] not in NEW_TABLE_NAMES and name not in CONSTRAINTS_ON_EXISTING:
            bad.append(("unexpected constraint on an existing table", name))
    if sorted(c.get("allowed_removed") or []) != ALLOWED_REMOVED:
        bad.append(("legacy return uniqueness not removed exactly", c.get("allowed_removed")))
    summary = {
        "tables_added": sorted(c.get("tables_added") or []),
        "columns_added": c.get("columns_added"),
        "indexes_added_on_existing_tables": {k: v for k, v in idx.items() if v not in NEW_TABLE_NAMES},
        "indexes_added_total": len(idx),
        "constraints_added_on_existing_tables": [n for n in cons if n.split(".", 1)[0] not in NEW_TABLE_NAMES],
        "constraints_added_total": len(cons),
        "removed_as_expected": c.get("allowed_removed"),
        "business_row_mismatch": c.get("business_row_mismatch"),
        "pg_stat_write_deltas": c.get("pg_stat_write_deltas"),
        "problems": bad,
        "verdict": "SHAPE OK" if not bad else "SHAPE MISMATCH",
    }
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
