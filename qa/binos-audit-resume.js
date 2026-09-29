export const meta = {
  name: 'binos-adversarial-audit',
  description: 'Independent adversarial audit: P9 offline/cash ledger, SAFE index-guard, release safety, 1C import',
  phases: [
    { title: 'Xarita', detail: 'one code mapper per audit area' },
    { title: 'Qidiruv', detail: 'adversarial finders per brief dimension' },
    { title: 'Triaj', detail: 'skeptic verification per finding' },
  ],
}

const REPO = 'C:/Users/Developer/Desktop/savdoOS'
const QA = REPO + '/.claude/worktrees/qa-binos-security'

const COMMON = [
  'CONTEXT: You are part of an INDEPENDENT adversarial QA audit of BinOS (SavdoOS), a retail POS/ERP.',
  'Backend: FastAPI + SQLAlchemy 2 + PostgreSQL (apps/server). Clients: Electron POS/Manager (packages/shared), Flutter PWA (apps/mobile).',
  'HARD ISOLATION RULES (other Claude sessions are active on this machine):',
  '- READ-ONLY. Never write/edit/create/delete any file. Never run pytest, npm, uvicorn, or any server. RAM is nearly exhausted (~1.5GB free) and ~300 foreign postgres processes are running - do not add load.',
  '- Never run git checkout/reset/merge/stash/branch -f or touch any worktree. Allowed git commands (read-only, run from the repo root ' + REPO + '): git show SHA:path, git ls-tree, git grep PATTERN SHA -- path, git log, git diff SHA1 SHA2 -- path.',
  '- To read a file at the audited SHA use: git -C "' + REPO + '" show <SHA>:<path> (paths are repo-relative, forward slashes). git grep syntax: git -C "' + REPO + '" grep -n "pattern" <SHA> -- apps/server',
  '- The QA worktree ' + QA + ' is checked out at e60c213a; files there may be read directly ONLY when your audited SHA is e60c213a.',
  'Your final structured output is machine-consumed. Keep every code excerpt under 10 lines. Cite exact repo-relative file paths and function names.',
].join('\n')

const AREAS = [
  {
    key: 'p9', sha: '482b3f38bd3b14ac315b71115352052bfa89818a',
    title: 'POS OFFLINE & CASH LEDGER (P9 snapshot)',
    scope: 'Server: apps/server/app/api/v1/sales.py, shifts.py, sync.py, cashops.py; services (find posting.post, create_sale, _resolve_shift, _lock_candidate_shift, open_shift_for_account, close_shift via git grep); cash DDL and triggers: apps/server/app/db/cash/cash_ddl_v1.sql, T0_CUTOVER_ENFORCEMENT.md, migration/backfill.py; unique indexes ux_sales_company_client_uuid and cle_uq_business. Client offline queue: git grep for outbox/offline/queue/LATE_SYNC in packages/shared/src and apps/mobile/lib. NOTE: branch p9 = base d916b9b + P7 UI redesign + one P9 commit 482b3f3 "Refuse an offline sale the server is certain to reject" - audit the WHOLE snapshot, and separately note what the P9 tip commit changes (git diff 758739b 482b3f38).',
    finders: [
      { key: 'shift-concurrency', focus: 'Dimensions A,B,J: shift closure vs concurrent sale creation; a cash ledger entry assigned to the WRONG shift; multiple devices using the same cashier/shift. Walk _resolve_shift, _lock_candidate_shift, open_shift_for_account, close_shift and every caller. Central question: is there ANY interleaving (two DB sessions, FastAPI concurrent requests) where Sale.shift_id != the shift_id recorded on the SALE cash-ledger entry, or where a sale lands in a shift already closed? Check what row locks (FOR UPDATE / FOR NO KEY UPDATE) are taken, in which order, and whether the shift row is re-read after lock. Do not infer safety from an index existing.' },
      { key: 'sync-idempotency', focus: 'Dimensions C,D,E,H,P: /sync/push duplicate sale under concurrent sync of the same client_uuid (two devices, retries); original client_uuid reused or replaced; LATE_SYNC entry created without authorization or operator attestation; offline transaction queued before shift closure and pushed after; repeated HTTP 409/400 handling. Read the sync endpoint and its service end-to-end: what happens on unique-violation of ux_sales_company_client_uuid - is the response idempotent-success with the SAME sale, or can a retry create a divergent record? What exactly gates LATE_SYNC?' },
      { key: 'posting-atomicity', focus: 'Dimensions F,G,M: sale committed but inventory/cash posting failed; inventory deducted twice on retry; partial commit or rollback behavior. Trace create_sale and posting.post transaction boundaries: same session/transaction or separate commits? Any flush/commit between sale INSERT and ledger INSERT? What do the immutable-ledger triggers in cash_ddl_v1.sql actually forbid (UPDATE? DELETE? INSERT?) and can application code bypass them? Does cle_uq_business really dedupe every posting path?' },
      { key: 'time-and-t0', focus: 'Dimensions I,K: pre-T0 versus post-T0 behavior (read T0_CUTOVER_ENFORCEMENT.md and the code that enforces it); device clock manipulation - which timestamps are client-supplied and trusted (sale time, shift open/close time, LATE_SYNC attestation time), what breaks if a device clock is years off; does any invariant or window check rely on client time?' },
      { key: 'tenant-isolation', focus: 'Dimension L: tenant/store/cashier isolation across sales.py, shifts.py, sync.py, cashops.py at this SHA. For every query and INSERT: is company_id/branch scoping applied from the AUTH context or from client-supplied payload fields? Can a valid token of tenant A reference shift_id/product_id/sale client_uuid of tenant B? Check the idempotency indexes are company-scoped.' },
      { key: 'client-outbox', focus: 'Dimensions N,O and client half of H: the POS client offline queue (git grep -n "outbox\\|offline\\|queue" 482b3f38 -- packages/shared/src). Can a queued sale be LOST: on dead-letter, on server URL switch (orphaned queue keyed by URL?), on app update, on repeated 400? Is anything dropped silently after N retries? What happens to entries for a shift the server has since closed - client half of the LATE_SYNC flow. Note: only defects visible in committed code; do not speculate about un-committed Phase 3A work.' },
    ],
  },
  {
    key: 'safe', sha: '85be3991bf7f087759949ff1e2545a98accbaea7',
    title: 'SAFE FINANCIAL INTEGRITY (index_guard, Phase 1 integration snapshot)',
    scope: 'apps/server/app/core/required_schema.py (index_guard), app/services/doc_seq.py (ux_doc_counter), app/services/subscription/lifecycle.py and payments.py, plus git grep index_guard 85be3991 -- apps/server for every call site. Also stock movement cutover keys and LOT activation/write protection (git grep for lot activation guards). Tests exist at apps/server/tests/test_index_guarantee_guard.py - read them to learn intent, then attack beyond them.',
    finders: [
      { key: 'guard-core', focus: 'index_guard correctness itself: does the required-unique-index validation actually check uniqueness flag, column SET AND ORDER, partial-index predicate text, and index validity (indisvalid/indisready)? Can an INVALID index (failed CREATE INDEX CONCURRENTLY) satisfy the guard? Predicate comparison: text-normalized or naive string equal - can a semantically different predicate pass? Case/quoting pitfalls?' },
      { key: 'guard-caching', focus: 'Stale positive caches and negative caching: when is the guard result cached (process-global? per-connection? per-request), what invalidates it, and what happens if the index is dropped or becomes invalid AFTER a positive cache. Connection-specific catalog state (search_path, pg_stat vs pg_index visibility inside a transaction). Concurrent degradation: REINDEX/DROP INDEX CONCURRENTLY racing a guarded write. PostgreSQL pool exhaustion: does the guard consume/hold connections; can exhaustion fail-OPEN?' },
      { key: 'write-coverage', focus: 'Which financial writes DEPEND on which index for correctness vs performance: subscription payment idempotency, ux_doc_counter document numbering, stock movement cutover keys, LOT activation/write protection. For each guarded call site: is the guard checked in the SAME transaction as the write, or is there a TOCTOU window? Which write entry points (HTTP routes, background jobs, sync) touch these tables WITHOUT passing through index_guard at all? Differentiate actual financial-integrity dependencies from FK-candidate and performance-only indexes - does the guard conflate them?' },
      { key: 'guard-bypass', focus: 'Startup/readiness interplay: does app boot verify these indexes fail-closed, or only lazily on first write? If the guard raises, what does the caller do - abort the transaction, or catch-and-continue? Any except/fallback path that turns a guard failure into a warning? SQLite dev mode: does the guard no-op there (memory: local SQLite hides FK violations), and can code paths tested only on SQLite ship a guard that never ran? Propose the minimal safe fix per defect, do not weaken checks.' },
    ],
  },
  {
    key: 'release', sha: '38f1d750d1ea9d65a397d13b5c1648054a1d5312',
    title: 'RELEASE SAFETY (P8 on main e60c213a + P8.1 fixes 38f1d750)',
    scope: '.github/workflows/staging-deploy.yml, staging-backup.yml, _db-backup-core.yml, db-backup.yml, restore-rehearsal.yml, ci.yml at BOTH e60c213a and 38f1d750 (diff them). Known context: 6 audit defects were reported unfixed on main P8; P8.1 is the fix attempt. Classify each finding as exists-on-main / exists-on-p8.1 / both. Analysis only - never trigger workflows or touch Railway/GitHub config.',
    finders: [
      { key: 'gate-logic', focus: 'CI-gated staging deployment logic: workflow_dispatch authorization (who can dispatch, any actor check), exact-SHA validation (is the deployed SHA pinned and re-verified, or can the branch move between check and deploy), current-main-HEAD enforcement, ci-proof/** branch bypass (CI triggers on ci-proof branches - can a deploy gate accept a green run from a ci-proof branch instead of main?), missing/failed/cancelled/skipped CI job handling (a skipped job is not success - does the gate distinguish?), incorrect boolean conditions in if: expressions (string vs boolean, needs.X.result comparisons).' },
      { key: 'concurrency-ordering', focus: 'Workflow concurrency groups and stale deployments: two dispatches racing, cancel-in-progress semantics, deployment activation ordering (backup before deploy? gate before activation?), multiple active deployment triggers (push + dispatch + schedule), and whether a stale queued run can deploy an OLD sha after a newer one. Also: does any step continue-on-error mask a failed gate?' },
      { key: 'backup-secrets', focus: 'staging-backup.yml and _db-backup-core.yml: backup encryption (is the dump encrypted at rest, with what key, is the key logged), manual dispatch of backups, secret exposure in logs (set -x, echo of URLs with credentials), artifact retention/visibility, and injection via workflow inputs (untrusted input interpolated into run: shell). Do not call a P8.1 fix real based on a YAML substring - reason through the actual execution semantics.' },
    ],
  },
  {
    key: 'onec', sha: '40150b54660f9a9adea3ef68442dcbcf35ee3c67',
    title: '1C IMPORT INTEGRITY (discovery collector snapshot)',
    scope: 'integrations/1c/ at this SHA: extractor/BinOSDiscovery.bsl, DISCOVERY_BUNDLE_V1.md, MIGRATOR_V1_RUNBOOK.md, SANDBOX_RESTORE_RUNBOOK.md, FIRST_REAL_COPY_CHECKLIST.md, plus any python under integrations/1c or apps/server that validates/applies discovery bundles (git grep -ln "discovery\\|bundle" 40150b54 -- apps/server integrations). Known context: PLU source from product NAMES is FORBIDDEN (only 0.9% coverage proven); CHARACTERISTICS_UNSUPPORTED is a deliberate stop.',
    finders: [
      { key: 'bundle-provenance', focus: 'Bundle hash and provenance: how is the discovery JSON bundle hashed, is the hash verified before APPLY, can a stale import plan run against a CHANGED source copy (source-copy hash mismatch), migrator snapshot freshness checks, repeated APPLY requests (idempotent or duplicating?), and validation of the discovery JSON schema (missing fields, wrong types, hostile strings, huge payloads).' },
      { key: 'unit-and-identity', focus: 'Unit dimension and magnitude safety: can 12.5 kg become 12.5 dona, or 1200 gramm become 1200 kg - where are unit codes mapped, is there a dimension check, unknown-unit quarantine? Barcode collision handling: duplicate barcode assigned to different products - reject, quarantine, or last-write-wins? Product identity matching (GUID vs code vs name) - can two 1C items merge into one BinOS product or one item split? Synthetic metadata versus verified 1C evidence - does any doc/code claim runtime 1C compatibility without authorized testing?' },
    ],
  },
]

const MAP_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    entry_points: { type: 'array', items: { type: 'string' } },
    transaction_boundaries: { type: 'array', items: { type: 'string' } },
    protective_constraints: { type: 'array', items: { type: 'string' } },
    suspects: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary', 'entry_points', 'protective_constraints', 'suspects'],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['P0', 'P1', 'P2'] },
          file: { type: 'string' },
          symbol: { type: 'string' },
          claim: { type: 'string' },
          invariant: { type: 'string' },
          attack_scenario: { type: 'string' },
          evidence: { type: 'string' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          needs_pg: { type: 'boolean' },
          suggested_repro: { type: 'string' },
        },
        required: ['title', 'severity', 'file', 'claim', 'invariant', 'attack_scenario', 'evidence', 'confidence', 'needs_pg'],
      },
    },
    not_vulnerable_notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['REFUTED', 'PLAUSIBLE', 'CONFIRMED_STATIC'] },
    reasoning: { type: 'string' },
    protective_constraint_found: { type: 'string' },
    repro_hint: { type: 'string' },
  },
  required: ['verdict', 'reasoning'],
}

function mapperPrompt(a) {
  return COMMON + '\n\nROLE: senior code mapper. AREA: ' + a.title + '\nAUDITED SHA: ' + a.sha + '\nSCOPE HINTS: ' + a.scope + '\n\nTASK: build a compact factual map of this area AT THIS SHA for adversarial reviewers who come after you. List: (1) entry_points - every write/deploy/import entry point as "symbol @ file" with one-line role; (2) transaction_boundaries - where commits/flushes/locks happen in the financial paths (or job/step boundaries for workflows); (3) protective_constraints - every unique index, DB trigger, row lock, guard check, gate condition that protects integrity, with file:line; (4) suspects - up to 12 specific spots that look fragile, each one line with WHY. Facts only, no speculation dressed as fact. Keep total under 120 lines.'
}

function finderPrompt(a, f, map) {
  const m = JSON.stringify(map).slice(0, 7000)
  return COMMON + '\n\nROLE: adversarial defect finder. Your goal is NOT to confirm the code works - it is to find real defects existing tests missed.\nAREA: ' + a.title + '\nAUDITED SHA: ' + a.sha + '\nSCOPE HINTS: ' + a.scope + '\nAREA MAP (from a prior mapper, verify before relying on it): ' + m + '\n\nYOUR DIMENSIONS: ' + f.focus + '\n\nMETHOD: for every suspected defect identify the exact code path (read the real code via git show), define the invariant that must hold, and construct the smallest concrete attack scenario (exact interleaving / input). Check for protective constraints BEFORE reporting - a finding that a unique index already prevents is a false positive, but do not infer safety merely because an idempotency index exists: check the error handling AROUND the constraint. Report at most 8 findings; only ones you can argue at code level. severity: P0 = money loss, duplicate accounting, inventory corruption, lost transactions, cross-tenant access, unrecoverable ledger, or a deploy-gate bypass; P1 = serious but recoverable; P2 = hardening. needs_pg=true when proof requires real PostgreSQL transactions/catalog. Put verified-safe areas into not_vulnerable_notes (one line each). If you find nothing real in a dimension, say so there - do not invent findings.'
}

function skepticPrompt(a, fnd, lens) {
  const lensText = lens === 'protective-constraint'
    ? 'LENS: protective constraints. Hunt for ANY existing mechanism that already prevents this: unique index + correct conflict handling, trigger, row lock, serializable retry, gate condition, validation. Read the actual code/DDL at the SHA - do not trust the finding text.'
    : 'LENS: runtime reality. Walk the ACTUAL execution: FastAPI dependency/session lifecycle, SQLAlchemy autoflush/commit points, GitHub Actions expression semantics, real interleaving feasibility. Does the claimed scenario survive contact with how this code actually runs?'
  return COMMON + '\n\nROLE: independent skeptic. Try to REFUTE this finding. Default to REFUTED if the attack cannot be made concrete.\nAREA: ' + a.title + '\nAUDITED SHA: ' + a.sha + '\n' + lensText + '\n\nFINDING UNDER TEST:\n' + JSON.stringify(fnd).slice(0, 5000) + '\n\nReturn verdict REFUTED (with the concrete protective mechanism or reasoning), PLAUSIBLE (cannot refute, but proof needs a test - give repro_hint), or CONFIRMED_STATIC (the defect is provable by reading code alone - explain the exact broken path). Be precise; your verdict feeds a financial-safety report.'
}

const results = await pipeline(
  AREAS,
  (a) => agent(mapperPrompt(a), { label: 'map:' + a.key, phase: 'Xarita', schema: MAP_SCHEMA }),
  (map, a) =>
    parallel(a.finders.map((f) => () =>
      agent(finderPrompt(a, f, map || {}), { label: 'find:' + a.key + ':' + f.key, phase: 'Qidiruv', effort: 'high', schema: FINDINGS_SCHEMA })
    )).then((rs) => {
      const findings = rs.filter(Boolean).flatMap((r, fi) => (r.findings || []).map((x) => ({ ...x, area: a.key, finder: a.finders[fi] ? a.finders[fi].key : '?' })))
      const notes = rs.filter(Boolean).flatMap((r) => r.not_vulnerable_notes || [])
      log('[' + a.key + '] finders done: ' + findings.length + ' finding, ' + notes.length + ' safe-note')
      return { map, findings, notes }
    }),
  (res, a) => {
    const seen = new Set()
    const uniq = []
    for (const f of res.findings) {
      const k = (f.file + '|' + (f.symbol || '') + '|' + f.title.slice(0, 50)).toLowerCase()
      if (!seen.has(k)) { seen.add(k); uniq.push(f) }
    }
    log('[' + a.key + '] triage: ' + uniq.length + ' unique (dropped ' + (res.findings.length - uniq.length) + ' dup)')
    return parallel(uniq.map((f, i) => () => {
      const lenses = f.severity === 'P2' ? ['protective-constraint'] : ['protective-constraint', 'runtime-reality']
      return parallel(lenses.map((l) => () =>
        agent(skepticPrompt(a, f, l), { label: 'triage:' + a.key + ':' + i + ':' + l.slice(0, 7), phase: 'Triaj', effort: 'high', schema: VERDICT_SCHEMA })
      )).then((vs) => ({ ...f, verdicts: vs.filter(Boolean) }))
    })).then((withV) => ({ area: a.key, sha: a.sha, map: res.map, notes: res.notes, findings: withV.filter(Boolean) }))
  }
)

const flat = results.filter(Boolean)
const summary = flat.map((r) => {
  const alive = r.findings.filter((f) => f.verdicts.some((v) => v.verdict !== 'REFUTED'))
  const killed = r.findings.length - alive.length
  return r.area + ': ' + alive.length + ' tirik / ' + killed + ' rad etildi'
})
log('YAKUN: ' + summary.join(' | '))
return { areas: flat, summary }