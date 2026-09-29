# BinOS — MUSTAQIL ADVERSARIAL QA HISOBOTI
**Sana:** 2026-09-30 · **Auditor:** mustaqil QA sessiyasi (`qa/binos-independent-security`)
**Uslub:** 3 fazali adversarial workflow (4 mapper → 15 finder → 2-linzali skeptik triaj, 123 agent)
+ har tasdiqlangan nuqson uchun BAJARILADIGAN reproduksiya sinovi.

---

## 1. Audit qilingan branch/SHA'lar (fetch'dan keyin o'z ko'zim bilan tekshirilgan)

| Area | Branch | Aniq SHA |
|---|---|---|
| Stabil baza / QA | origin/main | `e60c213a446caf0c8e845bd9caa50113aad0e194` |
| POS OFFLINE (P9) | p9-pos-offline-shift-safety (lokal) | `482b3f38bd3b14ac315b71115352052bfa89818a` |
| SAFE (index_guard) | integration/p6c-phase1 (lokal) | `85be3991bf7f087759949ff1e2545a98accbaea7` |
| RELEASE SAFETY | p8.1-release-gate-fixes (lokal) | `38f1d750d1ea9d65a397d13b5c1648054a1d5312` |
| 1C | p5-1c-discovery-collector (lokal) | `40150b54660f9a9adea3ef68442dcbcf35ee3c67` |

Muhim topografiya: **origin'da faqat `main` bor** — qolgan audit branchlari faqat lokal.
Lokal `main` (d916b9b) origin/main'dan orqada. `index_guard` FAQAT p6c-phase1'da mavjud
(main'da yo'q). P9 brachi = d916b9b + P7 UI (4 commit) + bitta P9 commit — auditlangan
moliyaviy mashina asosan main merosidir, shu bois topilmalarning aksariyati **ikkala**
joyda ham bor (har topilmada belgilangan).

## 2. Muhit va cheklovlar

- Windows 11, 15.4 GB RAM (bo'sh ~1.5–2.6 GB), boshqa Claude sessiyalari faol.
- **Butun audit davomida 300–389 ta begona `postgres` jarayoni ishladi** (boshqa
  sessiyalarning to'plamlari). §7 qoidasiga ko'ra og'ir PG sinovlari **PENDING** —
  PG darajasidagi poyga isbotlari statik tasdiq bilan chegaralandi.
- Reproduksiyalar: SQLite + TestClient (mantiq nuqsonlari uchun yetarli — dedup doirasi,
  idempotentlik kaliti, smena bog'lash qoidasi, sof funksiyalar), venv python 3.12.
- Izolyatsiya: yangi worktree `qa-binos-security` (branch `qa/binos-independent-security`,
  baza e60c213a) + faqat o'qish uchun detached snapshot worktree'lar `qa-snap-p9/-safe/-1c`.
  Boshqa sessiyalarning worktree'lariga, jarayonlariga, bazalariga TEGILMADI.

## 3. Ijro xulosasi (Executive summary)

**14 ta nuqson BAJARILADIGAN sinov bilan REPRODUKSIYA QILINDI** (barchasi qizil =
invariant buziladi), yana bir P0 (smena yopilishi vs parallel savdo) ikki bosqichli
statik tasdiqdan o'tdi (PG reproduksiyasi kutilmoqda). Eng og'irlari:

1. **Offline chekda `client_uuid` yo'q bo'lsa idempotentlik YO'Q** — retry pul va stokni
   IKKI marta yozadi (P0-ta'sir; main + P9).
2. **Soxta `sold_at` YOPIQ, rekonsilatsiya qilingan smenaga savdo kiritadi** (60 kungача
   orqaga) — Z-hisobot orqadan buziladi (main + P9).
3. **Deploy darvozasi joriy origin/main'da chetlab o'tiladi** (B4): yashil `ci-proof/**`
   SHA'ni dispatch orqali staging'ga chiqarish mumkin — HAQIQIY darvoza kodi sintetik
   fixture'da rc=0 berdi. P8.1'da TUZATILGAN, lekin **P8.1 hali merge qilinmagan**.
4. **`record_payment(client_uuid=None)`** — append-only obuna reyestriga retry'da IKKI
   to'lov, davr IKKI oy uzayadi; storno yozuvchisi yo'q (SAFE).
5. **1C discovery `content_sha256` namuna QATORLARINI qamramaydi** — «tasdiqlangan»
   to'plam ostida dalilni almashtirish mumkin.
6. **⚠️ KOD REPO OCHIQ (PUBLIC)** — `ZafarbekOlimboyev/savdoos` `visibility: PUBLIC`
   (gh api bilan tekshirildi), CLAUDE.md esa «kod repo yopiq qoladi» deydi. Ochiq repoda
   **production DB backup artefaktlari yotibdi** (`savdoos-db-daily-*`, `savdoos-db-weekly-*`:
   `*.dump.gpg` + SHIFRLANMAGAN `*.meta.json`/`*.sha256`) — istalgan GitHub foydalanuvchisi
   yuklab oladi; yagona himoya — staging bilan bo'lishilgan bitta parol. Workflow izohlari
   («jurnal ochiq repoda loginsiz o'qiladi») muallif buni bilganini ko'rsatadi — lekin
   CLAUDE.md'dagi asos bilan zid. EGA QARORI SHART: repoi yopish yoki backup'ni artefaktdan
   tashqariga ko'chirish.

Umumiy triaj statistikasi (1-yurish): P9 32 topilma (30 tirik / 2 rad), SAFE 21 (triaj
qisman — sessiya limiti, qayta yuritildi), RELEASE 17 (14/3), 1C 8 (triaj qayta yuritildi).

## 4. TASDIQLANGAN topilmalar — reproduksiya dalili bilan

Har sinov INVARIANTNI tasdiqlaydi: nuqsonli kodda QIZIL. Sinov fayllari:
`apps/server/tests/test_qa_p9_repro.py` (QA branchida ham), snapshot'larda
`test_qa_safe_repro.py`, `test_qa_1c_repro.py` (nusxalari `qa/audit-2026-09-30/synthetic/`),
`qa/audit-2026-09-30/synthetic/test_release_gate_sim.py`. Dalillar: `qa/audit-2026-09-30/evidence/`.

### BINOS-QA-P9-01 · P0 · REPRODUCED · main+P9
**Joy:** `apps/server/app/api/v1/sync.py::push` + `services/sales.py::_create_sale_once` (idempotentlik bloki)
**Invariant:** bitta offline chek retry'da bir marta yoziladi, yoki kalitisiz chek rad etiladi.
**Repro:** ayni chek `client_uuid`siz ikki marta push → **ikkalasi ok:true (#1288, #1289),
2 sotuv, stok 10→8**. Moliyaviy ta'sir: dublikat tushum + ikki karra stok chiqimi.
**Minimal tuzatish:** push'da `s.client_uuid is None` → `ok:false, error:"validation"`
(doimiy); yoki `SaleCreate`da sync yo'li uchun majburiy qilish.
**Regressiya testi:** `test_qa01_push_without_client_uuid_duplicates_on_retry` (tayyor).

### BINOS-QA-P9-02 · P0 · REPRODUCED · main+P9
**Joy:** `services/sales.py::_create_sale_once` (QA PAY-02 tarixiy smena tanlovi) + `sync.py::_clamp_sold_at`
**Invariant:** yopilgan (expected_cash muzlatilgan) smenaga savdo JIMGINA biriktirilmaydi.
**Repro:** smena ochildi→yopildi; `sold_at` = yopiq oyna o'rtasi bilan push → **sale.shift_id
== yopiq smena**, muzlatilgan expected_cash=0.00 o'zgarmagan, smenada endi 100 naqd savdo.
`_clamp_sold_at` 60 kungача orqaga ruxsat beradi — istalgan `kassa.sell` tokeni o'tgan
hisobot kunlarini o'zgartira oladi. K o'lchovi (soat manipulyatsiyasi) ham shu yo'ldan.
**Minimal tuzatish:** tanlangan smena `status=closed` bo'lsa — barqaror kod bilan 400
(post-T0 `CLOSED_SHIFT_CASH_REPLAY` bilan uyg'un) YOKI anomaliya belgisi + yopiq smena
hisobotini qayta hisoblash. Dizayn qarori egada; jim biriktirish esa har holda taqiq.
**Regressiya testi:** `test_qa02_forged_sold_at_binds_into_closed_shift`.

### BINOS-QA-P9-03 · P1 · REPRODUCED · main+P9
**Joy:** `services/sales.py::_create_sale_once` (company-doirali dedup, material tekshiruvsiz)
**Invariant:** boshqa kassirning `client_uuid`iga to'qnashgan YANGI chek yo yoziladi, yo aniq rad.
**Repro:** B-kassir boshqa mahsulot/summa bilan A'ning uuid'ini yubordi → **200 OK, A'ning
sale id'si qaytdi**, B'ning 600 so'mlik cheki yozilmadi (stok o'zgarmagan). B pul olgan,
serverda savdo yo'q; qo'shimcha — B A'ning chekini (cost bilan) ko'radi.
**Minimal tuzatish:** dedup topilganda `cashier_id` va material (summa/pozitsiyalar xeshi)
solishtirish; mos kelmasa 409 barqaror kod.
**Regressiya testi:** `test_qa03_cross_cashier_uuid_replay_swallows_new_sale`.

### BINOS-QA-P9-04 · P1 · REPRODUCED · main+P9
**Joy:** `apps/server/app/api/v1/cashops.py::_transfer_once` (dedup: faqat `client_uuid+type`)
**Invariant:** idempotentlik kaliti KOMPANIYA doirasida; material mos kelmasa rad.
**Repro:** B-kompaniya A'ning uuid'i bilan HAQIQIY transfer yubordi → **{"ok":true,
"duplicate":true}**, stok siljimagan (from=10, to=yo'q). Tenantlararo interferensiya +
yo'qolgan inventar harakati.
**Minimal tuzatish:** filtrga kompaniya doirasi (branch orqali join yoki company ustuni)
+ material-match (cash_movements yo'lidagi kabi).
**Regressiya testi:** `test_qa04_transfer_dedup_not_tenant_scoped`.

### BINOS-QA-REL-01 (B4) · P0 · REPRODUCED (sintetik, haqiqiy darvoza kodi) · faqat main
**Joy:** `.github/workflows/staging-deploy.yml` (e60c213a): `fresh` qadamida
`if: github.event_name != 'workflow_dispatch'`; CI tekshiruvida `head_branch` filtri yo'q.
**Repro (bajarildi):** ikkala nusxaning python darvoza bloki YAML'dan sug'urib olinib
sintetik `workflow_runs` bilan bajarildi: **main nusxasi yashil `ci-proof/**` run bilan
rc=0** (vakolat berdi); skip semantikasi tufayli `steps.fresh.outputs.stale` bo'sh →
`'' != 'true'` → deploy davom etadi. **38f1d750: 12/12 yashil** (ci-proof rad, pending/
failure/cancelled/skipped rad, dispatch'da freshness qattiq).
**Xulosa:** B4 **joriy origin/main'da OCHIQ** (faqat `vars.STAGING_DEPLOY_ENABLED` o'chiq
turgani himoya), P8.1'da tuzatilgan lekin MERGE QILINMAGAN. 1-yurishdagi "[0] bypass
38f1d750'da bor" topilmasi RAD ETILDI (noto'g'ri SHA'ga yozilgan) — o'z o'qishim bilan.
**Minimal tuzatish:** P8.1'ni main'ga merge; qo'shimcha (release[1], P1): `RAILWAY_TOKEN`ni
`environment:` himoyasiga o'tkazish — aks holda eski branch nusxalari dispatch orqali
eski darvozani ishlatadi (GitHub semantikasi: dispatch tanlangan ref nusxasini bajaradi).

### BINOS-QA-REL-02 · P1 · CONFIRMED (jonli dalil) · joriy holat
**Joy:** repo ko'rinishi + `_db-backup-core.yml` Upload artifact (qatorlar 241–255)
**Dalil (2026-09-30):** `gh repo view` → `visibility: PUBLIC, isPrivate: false`;
`gh api .../actions/artifacts` → jami 238 artefakt, ular ichida `savdoos-db-daily-*` (6+)
va `savdoos-db-weekly-*` (5+) — tarkibi `*.dump.gpg`, `*.sha256`, `*.meta.json`
(oxirgi ikkisi SHIFRLANMAGAN: plaintext-dump xeshi + hajm/metadata = kunlik biznes-hajm
qatori oshkor). Ochiq repoda artefaktni istalgan GitHub akkaunti yuklab oladi; himoya —
bitta GPG parol (staging bilan umumiy, BACKUPS.md siyosatiga zid — finder [12]).
Qo'shimcha eskalatsiya: [14] ulanish-xato stderr'i prod DB host/port/user'ni OCHIQ
loglarga chiqaradi. **Minimal tuzatish:** repoi PRIVATE qilish (CLAUDE.md asli) YOKI
backup'ni Actions artefaktidan shaxsiy saqlashga ko'chirish + meta/sha256'ni ham
shifrlash + parolni stagingdan ajratish.

### BINOS-QA-SAFE-01 · P1 (latent) · REPRODUCED · 85be3991
**Joy:** `app/services/subscription/payments.py::record_payment` (+`find_by_client_uuid` None→None)
**Repro:** ayni to'lov `client_uuid=None` bilan ikki marta → **new2=True, 2 qator,
davr 2026-04-10 → 2026-06-10 (IKKI oy)**. `ux_subpay_client_uuid` qisman indeksi NULL'ni
qoplamaydi; jadval append-only, keyin tuzatib bo'lmaydi. HTTP chaqiruvchisi bu snapshotda
hali yo'q — shuning uchun "latent", lekin servis ochiq seam.
**Minimal tuzatish:** `client_uuid is None` → `LifecycleRefused("IDEMPOTENCY_KEY_REQUIRED")`.
**Regressiya:** `test_qaS1_record_payment_none_uuid_double_extends`.

### BINOS-QA-SAFE-02 · P2 · REPRODUCED (mantiq) · 85be3991
**Joy:** `app/core/index_guard.py::index_state` — `d = defs.get(index); if d is not None...`
**Repro:** ta'rif zondida qator yo'q → **state='ok' KESHLANADI** (fail-closed modulda
fail-open shox). **Minimal tuzatish:** `if d is None: return UNVERIFIABLE`.

### BINOS-QA-SAFE-03 · P2 · REPRODUCED · 85be3991
**Joy:** `index_guard.py` import vaqti: `float(os.getenv("SAVDOOS_INDEX_GUARD_TTL","10") or 10)`
**Repro:** `SAVDOOS_INDEX_GUARD_TTL='10s'` → **import ValueError, butun boot yiqiladi**.
`'inf'` esa keshni abadiy qiladi. **Minimal tuzatish:** try/except → default 10 + jurnal.

### BINOS-QA-1C-01 · P1 · REPRODUCED · 40150b54
**Joy:** `app/services/discovery_1c/bundle.py::canonical_projection` — `"samples": sorted(b.samples)`
**Repro:** qatorlari BUTUNLAY boshqa ikki to'plam → **content_sha256 AYNI**
(`f134f7f0c9f7b5c7…`): dict ustidagi `sorted()` faqat KALITLARNI oladi.
**Minimal tuzatish:** `sorted((k, dumps(v)) for k, v in b.samples.items())`.

### BINOS-QA-1C-02 · P2 · REPRODUCED · 40150b54
**Joy:** `app/services/migrator_1c/normalize.py::KNOWN_UNIT_DIMENSION`
**Repro:** `check_unit_mapping('тн'|'литров'|'грамма', 'dona')` — **hech biri
ValueError bermadi** (3/3): «yangi nom» sifatida o'tadi → massa miqdori jimgina sanoqqa
aylanadi (12.5 тн → 12.5 dona). **Minimal tuzatish:** imlolarni lug'atga qo'shish va/yoki
`norm_unit_key`da kelishik qo'shimchalarini yig'ish.

## 5. STATIK TASDIQ (PG reproduksiyasi PENDING)

### BINOS-QA-P9-05 · P0 · CONFIRMED_STATIC (o'z o'qishim + 1 skeptik CONF) · main+P9
**Smena yopilishi vs parallel savdo.** `close_shift` Shift'ni FOR UPDATE qulflaydi va
SHIFT-1 izohi «hamma yo'l smenani qulflaydi» deydi — lekin **savdo yo'li
(`_create_sale_once`) Shift qatorini QULFLAMAYDI va commitdan oldin statusni qayta
tekshirmaydi**. READ COMMITTED'da: savdo tx smena=open o'qiydi → close tx qulf oladi,
muzlatadi, commit → savdo tx keyin commit → savdo yopiq smenада, muzlatilgan expected'дан
tashqarida. SHIFT-1 himoyasi faqat CashMovement yo'llarini qamraydi. SQLite'da poyga
serializatsiya bo'lgani uchun repro faqat PG'da mumkin — **PENDING** (begona PG band).
**Minimal tuzatish:** savdo yo'lida smena qatorini `FOR NO KEY UPDATE` (FK-deadlock
naqshiga mos) o'qish yoki commit oldidan status qayta-tekshiruv + retry.

Quyidagilar ham ikki mustaqil skeptik CONF oldi, PG talab qiladi (PENDING):
- **P9-06** (`posting.py::_lock_candidate_shift`) — qulfdan keyin status QAYTA O'QILMAYDI
  (identity-map eski qiymat) → ON_SHIFT leg YOPIQ cash-smenaga; LATE_SYNC aylanib o'tiladi.
- **P9-07** (`retrofit.on_cash_sale` / `_resolve_shift`) — kech replay legi JORIY ochiq
  smenaga tushadi: **Sale.shift_id != ledger shift_id KONSTRUKTSIYA BO'YICHA** (brief'ning
  markaziy savoliga javob: HA, bunday yo'l bor) — Case C LATE_SYNC savdo yo'lidan yetib
  bo'lmaydi.
- **P9-08** (post-T0 «bitta ochiq smena / till») — check-then-act: ikki parallel open →
  bitta till'da ikkita legacy smena, keyin on_shift_close NOTO'G'RI cash-smenani yopadi.
- **P9-09** — `cutover_guard.reject_closed_shift_replay`: post-T0 yopiq smena naqd replay
  DOIMIY 400 → dead-letter (P9 va'dasi bilan zid: pul olingan, savdo yo'qoladi).
- **P9-10** — ledger 24h oynasi: 25 soatdan uzun smenada naqd legi jim OFF_SHIFT.

## 6. Rad etilgan gipotezalar (tanlab)

- P9 finder "moneyCaptured bypass" [11] — REFUTED (skeptik: oqim faqat pul allaqachon
  olingan holatni qamraydi, bu ataylab).
- release[3] «dual-deploy runbook prose» / [7] TOCTOU / [10] backup-deploy bog'lami —
  REFUTED yoki P2-hujjat darajasida.
- release[0] «bypass p8.1'da» — RAD (yuqorida, o'z o'qishim bilan; to'g'risi: main'da).
- 1-yurishda safe[0] «guard 3/15 yo'lni qoplaydi» P1 [REFU,REFU] — ikkala skeptik ham
  rad etdi (qamrov Option A bo'yicha ataylab qisqartirilgan, hujjatlashtirilgan).

## 7. Triaj yakuni (qayta yuritilgan qism)

_(sessiya limiti tufayli 21 triaj agenti qayta yuritildi — natijalar quyida)_
<!-- RESUME-TRIAGE-PLACEHOLDER -->

## 8. Sinovlar jadvali

| Sinov | SHA | Natija | Ma'no |
|---|---|---|---|
| test_qa_p9_repro.py (4) | 482b3f38 | 4 QIZIL | 4 nuqson isboti |
| test_qa_p9_repro.py (4) | e60c213a | 4 QIZIL | main'da ham bor |
| test_release_gate_sim.py (14) | e60c213a/38f1d750 | main: 2 QIZIL · p8.1: 12 YASHIL | B4 main'da, p8.1 tuzatgan |
| test_qa_safe_repro.py (3) | 85be3991 | 3 QIZIL | 3 nuqson isboti |
| test_qa_1c_repro.py (4) | 40150b54 | 4 QIZIL | 2 nuqson isboti (3 parametr birlikda) |

Barcha QIZIL — ataylab (invariant sinovlari). Yashil to'plam da'vosi YO'Q: to'liq
regressiya bu auditning vazifasi emas edi va yuritilmadi (begona PG yuki ostida
resurs qoidasi §7).

## 9. Tavsiya etilgan tuzatish tartibi

1. **P8.1 → main merge** (B4 joriy main'da ochiq; gate var yoqilishidan OLDIN shart) +
   `RAILWAY_TOKEN`ni environment himoyasiga.
2. **P9-01** (client_uuid=None rad) — kichik, xavfsiz, darhol.
3. **P9-03/P9-04** (dedup: aktor/material/kompaniya doirasi) — kichik.
4. **P9-02 + P9-05..09 birga** — smena-bog'lash va yopilish semantikasi bitta dizayn
   qarori: yopiq smenaga jim yozuv taqiqi + savdo yo'lida smena qulfi + LATE_SYNC'ni
   savdo yo'lidan yetadigan qilish. P9 Phase 3A ayni shu hududda — bu topilmalar Phase 3A
   spetsifikatsiyasiga kirsin, alohida yamoq emas.
5. **SAFE-01/02/03** — uch kichik yamoq (None-kalit rad; UNVERIFIABLE; TTL try/except).
6. **1C-01/02** — hash proyeksiyasi + birlik lug'ati (APPLY'dan oldin shart).

## 10. Qolgan integratsiya blokerlari / keyingi qadam

- PG-poyga reproduksiyalari (P9-05..08): begona PG jarayonlari tugagach `pgserver` bilan
  fokusli 2-sessiyali sinovlar (tayyor stsenariylar §5'da).
- P9 Phase 3A commit bo'lgach: P9-02/05..09 topilmalari YANGI kod ostida qayta baholansin.
- Vitest (klient outbox N/O topilmalari) — node muhiti bu mashinada og'ir; statik tasdiq
  bilan qoldi (P9 triajida CONF).

## YAKUNIY HUKM (area bo'yicha)

| Area | Hukm | Sabab |
|---|---|---|
| **POS OFFLINE** | **HOLD** | 2 REPRODUCED P0 (idempotentlik, yopiq smena) + statik P0 poyga; LATE_SYNC savdo yo'lidan yetib bo'lmaydi |
| **SAFE** | **HOLD** | append-only reyestrga None-kalit dubl to'lov + guard'da fail-open shox (kichik yamoqlar bilan tez yechiladi) |
| **RELEASE SAFETY** | **HOLD** | B4 joriy origin/main'da OCHIQ (p8.1 merge qilinmagan); **kod repo PUBLIC** (CLAUDE.md'ga zid) va unda prod DB dump artefaktlari — bitta parol himoyasida |
| **1C** | **HOLD** | content_sha256 dalilga ko'r + birlik o'lchov teshigi — APPLY'dan oldin shart |

Global PASS berilmaydi. Hech qanday production kod o'zgartirilmadi; barcha tuzatishlar
developer-handoff sifatida yuqorida.
