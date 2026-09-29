### AREA p9  sha=482b3f38  findings=32
  [ 0] P0 conf=hig pg=Y [REFU,CONF] Concurrent sale vs shift close: sale cash lands in an already-closed shift and is excluded from the frozen expected_cash
        apps/server/app/api/v1/shifts.py::close_shift / services/sales.py::_create_sale_once  (finder=shift-concurrency)
  [ 1] P1 conf=hig pg=Y [CONF,CONF] posting._lock_candidate_shift returns a stale identity-mapped CashShift: the in-lock status re-check reads pre-lock 'OPEN', silently writing ON_SHIFT legs into CLOSED shifts instead of LATE_SYNC
        apps/server/app/services/cash/posting.py::CashPostingService._lock_candidate_shift / _resolve_shift  (finder=shift-concurrency)
  [ 2] P1 conf=hig pg=Y [CONF,CONF] Offline replay: ledger leg is posted to the till's CURRENTLY-open cash shift, not the historical shift the sale is attributed to - Sale.shift_id != ledger shift_id by construction, and Case C LATE_SYNC is unreachable from the sale path
        apps/server/app/services/cash/retrofit.py::on_cash_sale (with services/sales.py QA PAY-02 shift matching)  (finder=shift-concurrency)
  [ 3] P1 conf=hig pg=Y [CONF,CONF] Post-T0 'one open shift per TILL' guard is check-then-act: two concurrent opens create two open legacy shifts on one till; the second has no cash shift and on_shift_close later closes the WRONG cash shift
        apps/server/app/api/v1/shifts.py::open_shift (post-T0 till-busy check) / retrofit.on_shift_open / on_shift_close  (finder=shift-concurrency)
  [ 4] P2 conf=hig pg=n [CONF] P9 offline policy cache survives a shift close performed on another device of the same cashier: up to 8h of offline sales are captured and then permanently dead-lettered on replay
        packages/shared/src/lib/sync.ts::offlineSaleAllowed / OFFLINE_POLICY_TTL_MS (with Shift.tsx close handler)  (finder=shift-concurrency)
  [ 5] P1 conf=hig pg=Y [CONF,CONF] Post-T0 cash sale queued before shift close is permanently rejected (CLOSED_SHIFT_CASH_REPLAY 400 -> dead-letter), contradicting the P9 ALLOWED promise
        apps/server/app/services/cash/cutover_guard.py::reject_closed_shift_replay / api/v1/shifts.py::offline_sale_policy  (finder=sync-idempotency)
  [ 6] P1 conf=hig pg=Y [CONF,CONF] Late-replayed offline cash is silently posted ON_SHIFT into the NEXT shift's ledger (wrong custodian, no anomaly flag); LATE_SYNC is unreachable from /sync/push
        apps/server/app/services/cash/retrofit.py::on_cash_sale / posting.py::_resolve_shift  (finder=sync-idempotency)
  [ 7] P1 conf=hig pg=Y [PLAU,CONF] close_shift freezes expected_cash without any lock against the sale path — a sale that read status=open commits after close and is missing from the frozen Z-report forever
        apps/server/app/api/v1/shifts.py::close_shift (QA SHIFT-1 comment) vs services/sales.py::_create_sale_once  (finder=sync-idempotency)
  [ 8] P2 conf=hig pg=n [CONF] /sync/push accepts offline receipts with client_uuid=None — such records have no idempotency and duplicate on any retry after response loss
        apps/server/app/api/v1/sync.py::push / schemas/sales.py::SaleCreate.client_uuid  (finder=sync-idempotency)
  [ 9] P2 conf=hig pg=n [CONF] 409-classified failures retry forever with no backoff or attempt cap; a poisoned receipt re-executes the full sale transaction every 30s indefinitely
        packages/shared/src/lib/sync.ts::flushOutbox / apps/server/app/api/v1/sync.py::push (retry:true for 409)  (finder=sync-idempotency)
  [10] P2 conf=hig pg=n [CONF] Cash ledger exceptions (LATE_SYNC_UNACK, UNRESOLVED_OFF_SHIFT, TIMESTAMP_OUT_OF_WINDOW) are written but exposed by no API — the 'attestation' half of LATE_SYNC does not exist
        apps/server/app/services/cash/posting.py::CashLedgerException writers vs app/api (no readers)  (finder=sync-idempotency)
  [11] P2 conf=med pg=n [REFU] moneyCaptured bypass: with prefs.offlineCard set, the P9 gate is skipped for every card sale, guaranteeing permanent dead-letter in force_shift stores without an open shift
        packages/shared/src/screens/POSKassa.tsx::finish() moneyCaptured / deadLetter cap  (finder=sync-idempotency)
  [12] P1 conf=hig pg=Y [REFU,CONF] Offline cash sale replayed after its shift closed posts the ledger leg to the WRONG (currently open) shift; LATE_SYNC path is unreachable from sales
        apps/server/app/services/cash/retrofit.py::on_cash_sale (line 228); caller apps/server/app/services/sales.py:696  (finder=posting-atomicity)
  [13] P1 conf=med pg=Y [CONF,CONF] Legacy shift close computes/freezes ledger-expected cash and reconciliation snapshot WITHOUT locking the cash.shifts row — concurrent posting can slip an ON_SHIFT leg between the SUM and the CLOSE
        apps/server/app/services/cash/retrofit.py::on_shift_close (line 168); also apps/server/app/api/v1/shifts.py:563 (ledger_expected_shift_cash)  (finder=posting-atomicity)
  [14] P1 conf=med pg=Y [CONF,CONF] Online sale can commit into a just-closed legacy shift: shift SELECTed without lock and never re-checked after close's freeze
        apps/server/app/services/sales.py::_create_sale_once (shift query at line 105)  (finder=posting-atomicity)
  [15] P2 conf=hig pg=n [CONF] /sync/push accepts offline receipts with client_uuid=None — such records have zero idempotency and duplicate on a lost HTTP response (double inventory deduction + duplicate cash IN)
        apps/server/app/api/v1/sync.py::push (line 44); SaleCreate.client_uuid at apps/server/app/schemas/sales.py:36  (finder=posting-atomicity)
  [16] P2 conf=hig pg=n [CONF] retrofit.on_cash_op still maps kind='collection' to a single-legged manual_cash_out, contradicting the module's own contract that collection must be a TILL->SAFE paired transfer
        apps/server/app/services/cash/retrofit.py::on_cash_op (line 467, map at line 471)  (finder=posting-atomicity)
  [17] P2 conf=hig pg=Y [CONF] lifecycle.open_shift commits the CashShift and posts the opening float in a SECOND transaction with a random uuid4 source_id — non-atomic and non-idempotent on failure
        apps/server/app/services/cash/lifecycle.py::open_shift (lines 28-50)  (finder=posting-atomicity)
  [18] P1 conf=hig pg=Y [PLAU,CONF] P9 device-clock gate skipped when force_shift is off, but post-T0 cash replay still depends on client clock
        apps/server/app/api/v1/shifts.py::offline_sale_policy  (finder=time-and-t0)
  [19] P1 conf=hig pg=n [CONF,CONF] Pre-T0: forged/skewed sold_at injects sales into closed, reconciled shifts and past reporting days (up to 60 days back)
        apps/server/app/services/sales.py::_create_sale_once (historical shift lookup) / sync.push _clamp_sold_at  (finder=time-and-t0)
  [20] P1 conf=hig pg=Y [CONF,CONF] Ledger 24h shift window: cash sales in a shift open longer than ~25h silently post OFF_SHIFT, making ledger-native shift close expected_cash undercount
        apps/server/app/services/cash/posting.py::CashPostingService._in_window / _resolve_shift  (finder=time-and-t0)
  [21] P2 conf=med pg=n [REFU] Clock >5min ahead: _clamp_sold_at silently re-dates the offline sale to flush time and rebinds it to whatever shift is open at flush
        apps/server/app/api/v1/sync.py::_clamp_sold_at / _create_sale_once shift selection  (finder=time-and-t0)
  [22] P1 conf=hig pg=n [CONF,CONF] Inter-branch transfer idempotency dedup is neither tenant-scoped nor material-matched
        apps/server/app/api/v1/cashops.py::_transfer_once  (finder=tenant-isolation)
  [23] P2 conf=hig pg=n [CONF] Sale can bind branch B stock to a branch A shift/till after mid-shift branch reassignment
        apps/server/app/services/sales.py::_create_sale_once  (finder=tenant-isolation)
  [24] P2 conf=med pg=n [CONF] Owner-less outbox entries are flushed under whichever account is logged in on the device
        packages/shared/src/lib/sync.ts::flushOutbox  (finder=tenant-isolation)
  [25] P2 conf=med pg=n [CONF] POST /sales idempotent replay returns another cashier's full SaleOut (incl. cost_total) by client_uuid
        apps/server/app/services/sales.py::_create_sale_once  (finder=tenant-isolation)
  [26] P1 conf=hig pg=n [CONF,CONF] Server-URL namespace change silently strands the entire offline queue and dead-letter list
        packages/shared/src/lib/offline.ts::serverTag / nsKey  (finder=client-outbox)
  [27] P1 conf=hig pg=n [CONF,CONF] Owner-filtered flush strands another cashier's queued sales forever, hidden from the POS badge
        packages/shared/src/lib/sync.ts::flushOutbox / usePendingCount  (finder=client-outbox)
  [28] P2 conf=med pg=n [CONF] Late-flushed sales older than 60 days (or >5min future) are silently re-dated to flush time, landing in the wrong day and wrong shift's cash expectations
        apps/server/app/api/v1/sync.py::_clamp_sold_at  (finder=client-outbox)
  [29] P2 conf=hig pg=n [CONF] Dead-letter list is capped at 200: overflow silently discards the oldest rejected-sale evidence
        packages/shared/src/lib/sync.ts::deadLetter  (finder=client-outbox)
  [30] P2 conf=med pg=n [CONF] P9 offline-policy invariant breaks when the same cashier's shift is closed from another device: money-captured sales then dead-letter on replay
        packages/shared/src/lib/sync.ts::offlineSaleAllowed / OFFLINE_POLICY_TTL_MS  (finder=client-outbox)
  [31] P2 conf=med pg=Y [CONF] sync.push classifies non-OperationalError transient DB failures as permanent, so the client dead-letters a valid money-captured sale
        apps/server/app/api/v1/sync.py::push (exception triage)  (finder=client-outbox)

### AREA safe  sha=85be3991  findings=21
  [ 0] P1 conf=hig pg=Y [REFU,REFU] Guard fail-closed protection covers only 3 of ~15 REQUIRED unique-index write paths; degraded ux_lot_intake_key lets concurrent receiving replays double stock
        apps/server/app/services/lot_receiving.py::create_lots  (finder=guard-core)
  [ 1] P2 conf=med pg=n [REFU] index_guard cache keyed on id(bind): id reuse after GC can serve one database's cached verdict (including OK) to a different bind
        apps/server/app/core/index_guard.py::index_state  (finder=guard-core)
  [ 2] P2 conf=hig pg=Y [CONF] Index shape check compares full indkey and ignores indnkeyatts, so key-vs-INCLUDE split is unverified; guard certifies shapes it did not actually validate
        apps/server/app/core/required_schema.py::_INDEX_DEF_SQL / index_definition_states  (finder=guard-core)
  [ 3] P2 conf=hig pg=n [CONF] SQLite shape check accepts a partial index when no predicate is registered, and matches predicates by naive case-insensitive substring
        apps/server/app/core/required_schema.py::index_definition_states (SQLite branch)  (finder=guard-core)
  [ 4] P2 conf=med pg=Y [CONF] Guard's catalog probe checks out a second pool connection while the request already holds one; under pool saturation at TTL expiry the guard converts pool timeout into 409 SCHEMA_GUARANTEE_MISSING on healthy schemas
        apps/server/app/core/index_guard.py::index_state -> required_schema._con_of  (finder=guard-core)
  [ 5] P2 conf=hig pg=Y [CONF] index_state caches OK when the shape scan returns no row for the index (fail-open default in a fail-closed module)
        apps/server/app/core/index_guard.py::index_state  (finder=guard-caching)
  [ 6] P2 conf=med pg=Y [CONF] Shape check compares pg_index.indkey, which includes INCLUDE columns, so a unique index with a weaker key passes as correctly-shaped
        apps/server/app/core/required_schema.py::index_definition_states (_INDEX_DEF_SQL)  (finder=guard-caching)
  [ 7] P2 conf=hig pg=n [CONF] Stale in-code claim: required_schema comments say index_guard protects import commit and the 2026-09-29 index list, but Option A (docs §11.3) wired only 3 guards
        apps/server/app/core/required_schema.py::REQUIRED_INDEX_DEFINITIONS  (finder=guard-caching)
  [ 8] P2 conf=med pg=Y [CONF] Guard checks out extra pooled connections mid-transaction; pool exhaustion is misreported as SCHEMA_GUARANTEE_MISSING after a 30s stall while holding row locks
        apps/server/app/core/index_guard.py::index_state / require_index  (finder=guard-caching)
  [ 9] P2 conf=med pg=n [REFU] Guard cache keyed on id(bind): a garbage-collected Engine/Connection's id can be reused and its cached verdict inherited by a different database
        apps/server/app/core/index_guard.py::index_state (_cache key)  (finder=guard-caching)
  [10] P2 conf=hig pg=n [CONF] SAVDOOS_INDEX_GUARD_TTL parsed with float() at import time: an invalid value turns every guarded money write into a 500, and 'inf' makes both positive and negative verdicts permanent
        apps/server/app/core/index_guard.py::_TTL_SECONDS  (finder=guard-caching)
  [11] P1 conf=hig pg=Y [NO-VERDICT] index_guard protects the wrong writers: every concurrent-money idempotency path (sales sync, cash ops, receiving, returns, supplier/customer payments) has no write-side guard, and their indexes are in the non-boot-fatal IDEMPOTENCY class
        apps/server/app/services/sales.py::create_sale / _create_sale_once (also api/v1/shifts.py cash ops, api/v1/receiving.py, api/v1/sales.py returns)  (finder=write-coverage)
  [12] P2 conf=hig pg=Y [NO-VERDICT] All three wired require_index sites verify the index outside the writing transaction, with a 10s positive-verdict cache — a guard-pass admits writes after the guarantee is gone
        apps/server/app/core/index_guard.py::index_state / require_index  (finder=write-coverage)
  [13] P2 conf=hig pg=n [CONF] record_payment's guard gives false assurance for client_uuid=None: the partial index cannot cover NULL keys, and the SELECT-dedup returns None, so replayed NULL-key payments double-extend the subscription period
        apps/server/app/services/subscription/payments.py::record_payment / find_by_client_uuid  (finder=write-coverage)
  [14] P2 conf=med pg=n [NO-VERDICT] index_guard cache keyed on id(bind) can transfer a stale verdict between databases after engine disposal
        apps/server/app/core/index_guard.py::_cache / index_state  (finder=write-coverage)
  [15] P2 conf=hig pg=n [NO-VERDICT] Severity classes conflate correctness-bearing and currently-unused indexes: dropping an unused FK-candidate parent key crash-loops production boot, while a missing money-idempotency index does not even block boot
        apps/server/app/core/required_schema.py::REQUIRED_INDEXES vs IDEMPOTENCY_INDEXES  (finder=write-coverage)
  [16] P1 conf=med pg=Y [NO-VERDICT] Guard catalog probes take extra pooled connections with no single-flight; UNVERIFIABLE never cached, so pool pressure converts every sale into a 30s stall plus 409
        apps/server/app/core/index_guard.py::index_state / require_index (wired into doc_seq.allocate at apps/server/app/services/doc_seq.py:146)  (finder=guard-bypass)
  [17] P2 conf=med pg=n [NO-VERDICT] index_guard cache keyed on id(bind) — CPython id reuse after engine disposal can serve another database's cached verdict (stale OK bypasses the guard); cache is also unbounded
        apps/server/app/core/index_guard.py::_cache / index_state  (finder=guard-bypass)
  [18] P2 conf=hig pg=Y [NO-VERDICT] Stale safety claim: shape-check waiver for ux_import_jobs_snapshot still cites index_guard coverage that Option A removed — a degraded index leaves parallel import-commit claiming as pure SELECT-then-INSERT TOCTOU
        apps/server/app/core/required_schema.py::REQUIRED_INDEX_DEFINITIONS comment (:1013-1023) vs catalog_commit_v2.claim_commit_job  (finder=guard-bypass)
  [19] P2 conf=med pg=n [NO-VERDICT] record_payment has zero idempotency when client_uuid is None: guard passes, dedup lookup is skipped, and a retried call double-charges an append-only register
        apps/server/app/services/subscription/payments.py::record_payment / find_by_client_uuid  (finder=guard-bypass)
  [20] P2 conf=med pg=Y [NO-VERDICT] index_state treats a registered index that vanishes from the definition probe (defs.get returns None) as OK and caches OK for the full TTL
        apps/server/app/core/index_guard.py::index_state (lines 104-110)  (finder=guard-bypass)

### AREA release  sha=38f1d750  findings=17
  [ 0] P0 conf=hig pg=n [CONF,CONF] Dispatch path deploy-gate bypass: skipped freshness step + missing head_branch filter lets a green ci-proof/** SHA deploy (B4)
        .github/workflows/staging-deploy.yml::deploy job, steps 'Nishon hali ham main tepasimi' (id: fresh) and 'Bu SHA uchun CI HAQIQATAN yashilmi'  (finder=gate-logic)
  [ 1] P1 conf=med pg=n [CONF,CONF] workflow_dispatch executes the selected ref's copy of the gate; RAILWAY_TOKEN is repo-scoped with no environment protection, so all in-file checks are advisory (and the pre-P8.1 hole stays dispatchable from stale branch copies)
        .github/workflows/staging-deploy.yml::deploy job (no `environment:` key; secrets.RAILWAY_TOKEN referenced at job level)  (finder=gate-logic)
  [ 2] P2 conf=hig pg=n [CONF] TOCTOU between freshness/CI checks and the Railway mutation, and no post-mutation verification of the deployment
        .github/workflows/staging-deploy.yml::steps 'Nishon hali ham main tepasimi' -> 'Bu SHA uchun CI HAQIQATAN yashilmi' -> 'Railway'ga AYNAN shu SHA ni deploy qilish'  (finder=gate-logic)
  [ 3] P2 conf=hig pg=n [REFU] Dual-deploy-path race window is enforced only by runbook prose: the workflow never verifies Railway's push trigger is gone before mutating
        RELEASE_SAFETY_RUNBOOK.md::§2.5 activation table steps 4-6 vs staging-deploy.yml deploy job  (finder=gate-logic)
  [ 4] P0 conf=hig pg=n [CONF,CONF] B4 verified: dispatch path bypassed freshness gate, letting never-on-main ci-proof SHA deploy (exists-on-main, FIXED at 38f1d750)
        .github/workflows/staging-deploy.yml::deploy job, steps 'Nishon hali ham main tepasimi' (id: fresh) / 'Bu SHA uchun CI HAQIQATAN yashilmi'  (finder=concurrency-ordering)
  [ 5] P1 conf=hig pg=n [CONF,CONF] B1/B2 verified: runbook activation prose on main prescribed the dual-deployer-creating order and contradicted its own table (exists-on-main, FIXED at 38f1d750)
        RELEASE_SAFETY_RUNBOOK.md::§2.4 step 3 / §2.5 activation table  (finder=concurrency-ordering)
  [ 6] P2 conf=med pg=n [CONF] Concurrency group keeps only ONE pending run: a later-finishing CI event for an OLDER commit cancels the queued deploy of the NEWEST green tip, which is then never deployed (both SHAs)
        .github/workflows/staging-deploy.yml::concurrency: group staging-deploy, cancel-in-progress: false (lines 68-70)  (finder=concurrency-ordering)
  [ 7] P2 conf=hig pg=n [REFU] TOCTOU between freshness/CI-green reads and the Railway mutation: a push in the window deploys a no-longer-tip SHA; dispatch path violates its own 'main tip only' rule (both SHAs, partially acknowledged)
        .github/workflows/staging-deploy.yml::steps fresh (line 140) -> CI check (line 166) -> mutation (line 225)  (finder=concurrency-ordering)
  [ 8] P2 conf=hig pg=n [CONF] Fire-and-forget mutation: no post-mutation deployment verification; a transport failure or manual run cancellation after the curl leaves a live deploy behind a red/cancelled run (both SHAs)
        .github/workflows/staging-deploy.yml::step 'Railway'ga AYNAN shu SHA ni deploy qilish' (lines 225-262)  (finder=concurrency-ordering)
  [ 9] P2 conf=hig pg=n [CONF] Single-deployer invariant has no technical enforcement: the gate never asserts the Railway push trigger is gone, and runbook §2.7 shows the 'verify old path dead' step currently yields a false confirmation (both SHAs)
        .github/workflows/staging-deploy.yml::deploy job (mutation step) + RELEASE_SAFETY_RUNBOOK.md §2.5 step 5 / §2.7  (finder=concurrency-ordering)
  [10] P2 conf=med pg=n [REFU] Deploy gate and staging backup gate are independent variables with no ordering coupling: staging can auto-deploy (including boot-time DDL) nightly with staging backups still disabled (both SHAs)
        .github/workflows/staging-backup.yml::gate `vars.STAGING_BACKUP_ENABLED` (lines 72-74) vs staging-deploy.yml `vars.STAGING_DEPLOY_ENABLED`  (finder=concurrency-ordering)
  [11] P2 conf=hig pg=n [CONF] B3 verified: staging backup's prescribed manual validation run was silently skipped when the gate variable was unset (exists-on-main, FIXED at 38f1d750); residual: the dispatch exemption is permanent, not activation-scoped
        .github/workflows/staging-backup.yml::backup job if: (lines 60-74)  (finder=concurrency-ordering)
  [12] P1 conf=hig pg=n [CONF,CONF] Full production DB dump publicly downloadable, sole protection is one human passphrase shared with staging (violates repo's own BACKUPS.md policy)
        .github/workflows/_db-backup-core.yml::dump job / Upload artifact step (line 242) + staging-backup.yml:25  (finder=backup-secrets)
  [13] P2 conf=hig pg=n [CONF] Retention shortening only warns: documented 180-day monthly production RPO is silently 90 days and the run stays green
        .github/workflows/_db-backup-core.yml::Haqiqiy saqlash muddatini tekshirish step (line ~256-281)  (finder=backup-secrets)
  [14] P2 conf=hig pg=n [CONF] Connection-failure stderr leaks production DB host/port/user into public Actions logs (substring of secret, not masked by GitHub)
        scripts/backup_postgres.sh::pg_dump invocation (line 66) + _db-backup-core.yml fingerprint steps  (finder=backup-secrets)
  [15] P2 conf=hig pg=n [CONF] meta.json and plaintext-dump .sha256 remain unencrypted in the public artifact, leaking a daily business-size time series despite fingerprints being encrypted for exactly this threat
        .github/workflows/_db-backup-core.yml::Upload artifact path list (lines 244-249) + scripts/backup_postgres.sh meta heredoc  (finder=backup-secrets)
  [16] P2 conf=med pg=n [CONF] pg-client composite action interpolates its input directly into run: shell — latent workflow-input code-injection sink
        .github/actions/pg-client/action.yml::steps 'postgresql-client-${{ inputs.major }} o'rnatish' (line 44) and MAJOR="${{ inputs.major }}" (line 50)  (finder=backup-secrets)

### AREA onec  sha=40150b54  findings=8
  [ 0] P1 conf=hig pg=n [NO-VERDICT] Discovery content_sha256 covers sample file NAMES only, not their rows — evidence data can change under an unchanged hash
        apps/server/app/services/discovery_1c/bundle.py::canonical_projection  (finder=bundle-provenance)
  [ 1] P2 conf=hig pg=n [NO-VERDICT] load_members silently accepts unknown bundle member files — they bypass validation, the secret scan, and the content hash
        apps/server/app/services/discovery_1c/bundle.py::load_members  (finder=bundle-provenance)
  [ 2] P2 conf=hig pg=Y [NO-VERDICT] Apply's "report reviewed on THIS database" gate reads the one report field deliberately excluded from report_sha256
        apps/server/app/services/migrator_1c/guard.py::assert_apply_allowed  (finder=bundle-provenance)
  [ 3] P2 conf=hig pg=n [NO-VERDICT] Cutover ledger rows are timestamped with the operator machine's process clock that the same module declares untrusted
        apps/server/app/services/migrator_1c/apply.py::apply_migration / _execute  (finder=bundle-provenance)
  [ 4] P1 conf=hig pg=n [NO-VERDICT] LINK/EXACT_MATCH silently discards the 1C PLU (and is_weighted) of the linked product - no decide code, no policy gate
        apps/server/app/services/migrator_1c/classify.py::_classify (step 5, lines 423-438) / mapping.py _build_plan op construction  (finder=unit-and-identity)
  [ 5] P2 conf=hig pg=n [NO-VERDICT] Unit dimension deny-list misses common 1C spellings ('тн', 'литров', 'грамма', ...), so --unit-map can still silently remap a mass magnitude
        apps/server/app/services/migrator_1c/normalize.py::check_unit_mapping / KNOWN_UNIT_DIMENSION (lines 55-96, 98-145)  (finder=unit-and-identity)
  [ 6] P2 conf=hig pg=n [NO-VERDICT] Two CREATE ops can write duplicate SKUs - 1C code duplication is info-only and products.sku has no unique index
        apps/server/app/services/migrator_1c/mapping.py::_build_plan CREATE block (line 519: "sku": r["code"]) / classify.py:326 CODE_DUPLICATE_IN_BUNDLE  (finder=unit-and-identity)
  [ 7] P2 conf=med pg=n [NO-VERDICT] binos-1c-v1 contract does not pin which 1C unit denominates stock quantities and prices (base storage unit vs card unit vs price unit)
        integrations/1c/BINOS_1C_BUNDLE_V1.md::products[].unit / products[].stock[].qty / products[].prices[].value schema  (finder=unit-and-identity)

