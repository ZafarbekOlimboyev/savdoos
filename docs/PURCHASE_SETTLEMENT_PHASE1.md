# Phase 1 — SEYF ONBOARDING / OCHILISH QOLDIG'I

> **Maqomi:** SHARTNOMA (implementatsiyadan OLDIN yozilgan). Ega tomonidan tasdiqlangan
> **B1–B7 mahsulot qarorlari** shu hujjatda kanonlashtirilgan.
>
> **Bu hujjat `PURCHASE_SETTLEMENT_DESIGN.md` §12 ni ALMASHTIRADI.** §12 dagi taklif
> (`provenance='RECONSTRUCTION'`, `source_type='CASH_OP'`, summa = `counted − balance`)
> **BEKOR** — sababi §0.1 da, dalili bilan.
>
> Manba hujjatlar: `PURCHASE_SETTLEMENT_DESIGN.md` (Revision 3, §10/§12/§13/§14),
> `PURCHASE_SETTLEMENT_REVIEW_TRACE.md`, `PURCHASE_SETTLEMENT_GATE.md`,
> `PURCHASE_SETTLEMENT_RFIX.md`, `PURCHASE_SETTLEMENT_RDDL.md`.

---

## §0. Nega §12 bekor qilindi (STOP ning dalili)

§12 ochilish legini `provenance='RECONSTRUCTION'` deb belgilashni taklif qilgan edi.
Kodda **RECONSTRUCTION** ning ma'nosi bitta va u boshqa: **T0 dan oldingi legacy tarixning
backfill nusxasi**. Darvoza —
`app/db/cash/migration/preflight.py · post_backfill_verification()`: u
`backfill.verify_backfill` + `backfill.reconcile_backfill` ni jamlab **10 ta majburiy**
tekshiruv beradi va bittasi ham yiqilsa dual-write **YOQILMAYDI**. `verify_backfill`
do'kondagi RECONSTRUCTION qatorlarining **FILTRLANMAGAN** to'plamini oladi.

Runtime ochilish legi o'sha 10 tadan **5 tasini** yiqitadi:

| Tekshiruv | Qayerdan | Runtime ochilish legi nima qiladi |
|---|---|---|
| `row_count_matches` | `verify_backfill` | manifestdagi sondan **ortiq** qator → **FAIL** |
| `in_total_matches` | `verify_backfill` | IN yig'indisi manifest `in_total` idan **oshadi** → **FAIL** |
| `deterministic_ids` | `verify_backfill` | id `uuid5(biznes kalit)` emas (runtime UUID) → **FAIL** |
| `no_ge_t0_backfilled` | **gate** (`preflight`) | ochilish T0 **dan KEYIN** yoziladi → **FAIL** |
| `unexplained_delta_zero` | **gate** (`reconcile_backfill`) | legacy tomonda mos hodisa YO'Q → **FAIL** |

Qolgan 5 tasi (`no_duplicate_business_keys`, `tenant_isolation`, `no_shadow_leg_leaked`,
`out_total_matches`, `all_reconstruction_metadata`) o'tardi — lekin darvoza **hammasini**
talab qiladi.

**Istisno mexanizmi YO'Q** — na `verify_backfill(db, manifest, *, company_id)`, na
`post_backfill_verification(db, executed_manifest, *, company_id, t0)` da kechiruvchi
parametr bor. Va `tests/cash/test_preflight.py::test_post_backfill_verification_pass_and_fail`
**aynan shu shakldagi qatorni** (`source_type="CASH_OP"`, `provenance="RECONSTRUCTION"`,
runtime UUID) sun'iy kiritib, `ok is False` ni **talab qiladi** — ya'ni §12 taklifi
mavjud testni buzardi.

Ya'ni §12 ni bajarish uchun `verify_backfill` ni **kuchsizlantirish** kerak bo'lardi —
ega buni ATAYLAB taqiqladi. Shu bois B1 = **OPTION A**: ochilish legi **NORMAL**, va
uning o'z manba turi bor.

⚠️ `REVIEW_TRACE` dagi `claim-accuracy#9` va `deadlock#7` satrlari («ochilish
`RECONSTRUCTION` bo'lgani uchun `EXTRA_LEDGER` shoxiga tushmaydi — kod o'zgarishi kerak
emas») shu qaror bilan **SUPERSEDED**: endi leg NORMAL, ya'ni u `EXTRA_LEDGER` shoxiga
**tushadi** va `compare_engine` uni **aniq manba shartnomasi** bo'yicha tanishi SHART (§6).

---

## §1. B1 — LEDGER LEGI (kanonik shakl)

Ochilish **bitta** ledger legi yozadi (faqat `COUNTED` holatida, §3):

| Maydon | Qiymat | Majburlovchi |
|---|---|---|
| `provenance` | `NORMAL` | `posting._validate` (NORMAL ⇒ recon maydonlari NULL) + `cle_recon_prov` |
| `source_type` | **`ACCOUNT_OPENING`** — `cash.cash_source_type` ga YANGI label | enum |
| `category` | `ADJUSTMENT` | `_authorize` → **menejer+** (saqlanadi) |
| `direction` | `IN` (ochilish qoldig'i musbat) | `_validate` (`amount > 0`) |
| `posting_kind` | `OFF_SHIFT` | `_resolve_shift` (SAFE → OFF_SHIFT) |
| `shift_id` | `NULL` | `cle_posting_shift` CHECK |
| `account_type` | `SAFE` **faqat** | `cle_acct_type_fk` + xizmat tekshiruvi |
| `source_id` | `cash_account_openings.id` | §2 |
| `leg_index` | `0` | §2 |
| `amount` | `counted_amount` (`> 0`) | `cle_amount_pos` |
| `device_occurred_at` | **attestatsiya sanog'i vaqti** (`counted_at`) | §8 |
| `reconstruction_reason` / `_source_ref` | **NULL** (NORMAL majbur qiladi) | `cle_recon_prov` |

⚠️ **Attestatsiya havolasi ledger legiga YOZILMAYDI.** `cle_recon_prov` NORMAL leg uchun
ikkala rekonstruksiya ustunini NULL qilishni talab qiladi, shu bois `attestation_ref`
**manba yozuvida** turadi (§2). Bu ma'lumot yo'qotish EMAS: leg manbaga `source_id` orqali
bir qiymatli bog'langan.

**QILINMAYDI:** `RECONSTRUCTION` ishlatilmaydi · `CASH_OP` ishlatilmaydi · soxta CASH IN
yo'q · `verify_backfill` kuchsizlantirilmaydi · «ba'zi rekonstruksiya qatorlari kechiriladi»
degan oq ro'yxat yo'q.

**Yangi `ACCOUNT_OPENING` label O'TKAZILADIGAN joylar** (biror registr unutilsa —
testda yiqiladi, §11 T-19):
`cash.cash_source_type` enum · `app/models/cash.CashSourceType` · `posting`/`adapters`
yo'li · `compare_engine` (§6) · `shadow_compare` (§6) · `repositories` hisobotlari ·
cash sxema tayyorligi (§5) · `GET /safes/{id}/balance` (§7).

---

## §2. B2 — MANBA YOZUVI `cash.cash_account_openings`

```sql
CREATE TABLE cash.cash_account_openings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    cash_account_id uuid NOT NULL,
    account_type    cash.cash_account_type NOT NULL,   -- hosila nusxa; SAFE bo'lishi SHART
    kind            text NOT NULL,                     -- 'KNOWN_ZERO' | 'COUNTED'
    counted_amount  numeric(14,2) NOT NULL,            -- KNOWN_ZERO -> 0 ; COUNTED -> > 0
    currency        char(3) NOT NULL,
    counted_at      timestamptz NOT NULL,              -- ATTESTATSIYA sanog'i vaqti (§8)
    attested_by     uuid NOT NULL REFERENCES public.employees(id),
    attestation_ref text NOT NULL,                     -- hujjat/dalolatnoma havolasi
    ledger_entry_id uuid,                              -- COUNTED uchun NOT NULL, KNOWN_ZERO uchun NULL
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_cao_kind        CHECK (kind IN ('KNOWN_ZERO','COUNTED')),
    CONSTRAINT ck_cao_amount_nonneg CHECK (counted_amount >= 0),
    CONSTRAINT ck_cao_kind_amount CHECK ((kind = 'COUNTED') = (counted_amount > 0)),
    CONSTRAINT ck_cao_kind_ledger CHECK ((kind = 'COUNTED') = (ledger_entry_id IS NOT NULL)),
    CONSTRAINT ck_cao_ref_nb      CHECK (attestation_ref <> ''),
    CONSTRAINT ck_cao_type_safe   CHECK (account_type = 'SAFE'),
    -- ⚠️ Postgres buni `'SAFE'::cash.cash_account_type` deb SAQLAYDI va `check_canon`
    --    kvalifikatsiyalangan tip keltirishni ATAYLAB olib tashlamaydi (u domen bo'lishi
    --    mumkin) — tayyorlik kutilgan ta'rifni AYNI shu shaklda ushlab turadi.

    -- hisob AYNI tenantniki VA turi SAFE (deklarativ; `ca_uq_tenant_id_type` ga tayanadi):
    CONSTRAINT cao_acct_type_fk FOREIGN KEY (tenant_id, cash_account_id, account_type)
        REFERENCES cash.cash_accounts (tenant_id, id, type),
    -- valyuta hisobniki bilan bir xil (deklarativ; `ca_uq_tenant_id_currency`):
    CONSTRAINT cao_acct_cur_fk FOREIGN KEY (tenant_id, cash_account_id, currency)
        REFERENCES cash.cash_accounts (tenant_id, id, currency),
    CONSTRAINT cao_entry_fk FOREIGN KEY (tenant_id, ledger_entry_id)
        REFERENCES cash.cash_ledger_entries (tenant_id, id),

    CONSTRAINT cao_uq_account  UNIQUE (tenant_id, cash_account_id),   -- BITTA hisob = BITTA ochilish
    CONSTRAINT cao_uq_tenant_id UNIQUE (tenant_id, id)
);
CREATE UNIQUE INDEX cao_uq_entry ON cash.cash_account_openings (ledger_entry_id)
    WHERE ledger_entry_id IS NOT NULL;
```

**Tenancy FK strategiyasi — mavjud naqshga AYNAN mos:** `cash` sxemasidagi hamma bola
jadval ota tomonga **kompozit** `(tenant_id, …)` FK qo'yadi va `public.*` ga bitta ustunli
mavjudlik FK'i (`companies`, `employees`) qoladi — `cash_ddl_v1.sql` §I izohidagi qoida.
Yangi strategiya **ixtiro qilinmadi**; `ca_uq_tenant_id_type` allaqachon mavjud, shu bois
«SEYF bo'lishi» **bazada** majburlanadi, xizmat qatlamida emas.

**O'zgarmaslik:** jadval append-only — `trg_cao_immutable` (`BEFORE UPDATE OR DELETE` →
`cash.fn_block_mutation`) + `trg_cao_no_truncate` (`BEFORE TRUNCATE` →
`cash.fn_block_truncate`). Phase 1 da tuzatish/reversal yo'li **YO'Q** (§9).

### 2.1 Yozish tartibi (bitta tranzaksiya)

```
1. require("kassa.attest")            — HTTP darvozasi (§4)
2. SAFE hisobini FOR UPDATE qulflash  — `_lock_account` bilan AYNI qator
3. mavjud ochilishni o'qish           — bor bo'lsa: bir xil payload -> 200 (idempotent),
                                        boshqa payload -> 409 SAFE_OPENING_CONFLICT
4. hisobda ledger legi bormi          — bor bo'lsa va ochilish yo'q -> 409
                                        SAFE_OPENING_BLOCKED_BY_HISTORY (§3.3)
5. opening_id = uuid4()               — id OLDIN generatsiya qilinadi
6. KNOWN_ZERO -> leg YO'Q
   COUNTED    -> cash_posting_service.post(..., commit=False):
                 source_type=ACCOUNT_OPENING, source_id=opening_id, leg_index=0
7. CashAccountOpening INSERT (ledger_entry_id to'ldirilgan holda, BITTA INSERT)
8. db.commit()                        — manba + leg AYNI tranzaksiyada
```

⚠️ **`CashPostingService` — ledger'ning YAGONA yozuvchisi.** Ochilish xizmati
`cash_ledger_entries` ga o'zi INSERT **qilmaydi**; u `post(..., commit=False)` ni
chaqiradi va o'z manba qatorini o'sha tranzaksiyaga qo'shadi. (DB darajasida ham:
`cash_posting` rolidan boshqa hech kim INSERT qila olmaydi.)

⚠️ **Nega `id` oldin generatsiya qilinadi:** `ledger_entry_id` COUNTED uchun NOT NULL va
jadval o'zgarmas (UPDATE bloklangan) — ya'ni «avval INSERT, keyin UPDATE» **mumkin emas**.
`source_id` esa DDL izohi bo'yicha **mantiqiy** havola (FK emas), shu bois legni manba
qatoridan OLDIN yozish qonuniy.

### 2.2 Idempotentlik va parallellik

- **Ayni payload qayta kelsa** — `200`, mavjud yozuv qaytariladi, **yangi leg yozilmaydi**.
  «Ayni payload» = `(kind, counted_amount, currency, attestation_ref, counted_at)` **to'liq**
  tengligi. Farq bo'lsa — **`409 SAFE_OPENING_CONFLICT`**, hech narsa yozilmaydi.
- **Parallel ikki so'rov** — hisob qatori `FOR UPDATE` bilan seriyalanadi; ikkinchisi
  qulfni olgach 3-qadamda mavjud yozuvni ko'radi. Qulf yetmagan holatda ham
  `cao_uq_account` **bazada** ikkinchi qatorni rad etadi, `cle_uq_business`
  `(tenant, ACCOUNT_OPENING, opening_id, 0)` esa ikkinchi legni rad etadi. **Aniq bittasi**
  muvaffaqiyat qiladi.
- `IntegrityError` → `409 SAFE_OPENING_CONFLICT` (jimgina «ok» EMAS).

---

## §3. B3 — UCH HOLAT va TAYYORLIK PREDIKATI

| Holat | Ta'rif | Ledger legi | SEYF ishlaydimi |
|---|---|---|---|
| **UNKNOWN** | ochilish yozuvi **YO'Q** | — | **YO'Q** (fail-closed) |
| **KNOWN_ZERO** | yozuv bor, `counted_amount = 0`, ega ANIQ «bo'sh» deb attestatsiya qilgan | **yo'q** (nol summali leg YOZILMAYDI) | HA |
| **COUNTED** | yozuv bor, `counted_amount > 0` | **aynan bitta** o'zgarmas `IN` legi | HA |

⚠️ **UNKNOWN ≠ nol.** Noma'lum qoldiq nol deb **taxmin qilinmaydi**; SEYF operatsion
emas. Bu ega qarori (J): legacy do'konda qoldiq noma'lum bo'lsa — **BLOCK**, REVIEW emas.

### 3.1 Markazlashgan predikat

`app/services/cash/safe_opening.py`:

```python
OPENING_UNKNOWN    = "UNKNOWN"
OPENING_KNOWN_ZERO = "KNOWN_ZERO"
OPENING_COUNTED    = "COUNTED"

def opening_state(db, *, company_id, cash_account_id) -> str
def is_operational(db, *, company_id, account) -> bool       # SAFE emas -> True (TILL tegilmaydi)
def require_operational(db, *, company_id, account) -> None  # aks holda SAFE_OPENING_REQUIRED
```

`is_operational` **yozuvning izchilligini ham** tekshiradi: `COUNTED` bo'lsa
`ledger_entry_id` mavjud VA o'sha leg bor, `ACCOUNT_OPENING`/`IN`/`ADJUSTMENT`/`SAFE`
shaklida va summasi `counted_amount` ga teng. Buzuq yozuv → **operatsion EMAS** (jimgina
«tayyor» deyilmaydi).

### 3.2 Majburlash nuqtalari (UI EMAS)

| Nuqta | Xulq |
|---|---|
| `CashPostingService.post` | SEYF hisobiga **har qanday** posting rad etiladi, **bitta istisno**: `source_type == ACCOUNT_OPENING` (ochilishning o'zi) |
| `CashPostingService.post_transfer` | inkassa manzili operatsion bo'lmagan SEYF bo'lsa — rad |
| `cutover_guard.resolve_cash_custody` / `require_custody_account` | operatsion bo'lmagan SEYF custody sifatida **tanlanmaydi** |
| `GET /cash/custody-preview` | o'sha gardni AYNAN chaqiradi (naqsh: `dry_run`) → `SAFE_OPENING_REQUIRED` |
| `POST /cash/ops` inkassa | yuqoridagi transfer gardiga tayanadi |

UI SEYFni ro'yxatdan yashirishi mumkin, lekin **kafolat serverda**.

### 3.3 Tarixi bor, ochilishi yo'q SEYF

Ledger legi(lari) bor, ochilish yozuvi yo'q hisob — **fail-closed**:
ochilish attestatsiyasi ham **rad etiladi** (`409 SAFE_OPENING_BLOCKED_BY_HISTORY`),
chunki retroaktiv «nol» yoki keyingi sanoq tarixni qayta talqin qilardi. Bunday hisob
**alohida migratsiya qarorini** talab qiladi — Phase 1 uni hal QILMAYDI.

Bu holat yangi do'konda **tug'ilmaydi**: §3.2 SEYFga ochilishdan oldin biror leg tushishiga
yo'l qo'ymaydi (inkassa ham, xarid to'lovi ham). Ya'ni qoida yopiq halqa.

### 3.4 O'zgaruvchan balans ustuni YO'Q

`cash_accounts` ga `balance` ustuni **qo'shilmaydi**; `cash_account_openings` da ham
«joriy balans» yo'q. Balans doim `repositories.account_balance` — Σ(IN) − Σ(OUT) —
bilan **hosil qilinadi**. `fn_guard_cash_account` allaqachon hisobning identity
ustunlarini muzlatadi; biz unga pul ustuni **qo'shmaymiz**.

---

## §4. B4 — RUXSAT `kassa.attest`

- **Yangi kod:** `kassa.attest` (modul `kassa`), `app/seed.PERMISSIONS` ga qo'shiladi.
- **Bootstrap:** `ega` va `administrator` — `ROLES` da `"ALL"` (avtomatik oladi);
  `menejer` — ro'yxatiga **ANIQ** qo'shiladi. `kassir` — **YO'Q**.
  `initdb._ensure_catalog()` har bootda yetishmayotgan ruxsatni yaratadi va mavjud
  rollarga bog'laydi → **mavjud do'konlar ham** oladi.
- **IKKALA shart birga:** marshrut `require("kassa.attest")` bilan yopiladi **va**
  xizmat qatlamida `category=ADJUSTMENT` (`reverses_id=None`) `posting._authorize` ning
  **menejer+** darvozasini saqlaydi. Ruxsat berilgan, lekin roli menejer+ bo'lmagan xodim
  — **rad**.
- **Ro'yxatdan o'tmagan bo'lsa fail-closed:** `deps.require` `FULL_ACCESS_ROLES`
  (`ega`, `administrator`) dan tashqari hamma uchun kod yo'q bo'lsa **rad etadi**.
- ⚠️ `hisobot.view` yoki `sozlamalar.edit` **o'rnini bosuvchi sifatida ishlatilmaydi**.

---

## §5. B5 — SXEMA va ADDITIV MIGRATSIYA

**Muammo:** `app/db/cash/deploy.py · deploy_cash_schema()` — **hammasi-yoki-hech narsa**: `cash` sxemasi
mavjud bo'lsa `'exists'` qaytaradi va DDL faylini **butunlay o'tkazib yuboradi**. Ya'ni
mavjud (production-like) bazalar yangi obyektni **hech qachon olmaydi**.

**Yechim:** `cash_ddl_v1.sql` **tegilmaydi** (versiyalangan, qayta qo'llanmaydi). Phase 1
obyektlari **yangi, idempotent boot qadamida** tug'iladi:

`app/initdb._ensure_cash_phase1()` — `_deploy_cash()` **dan KEYIN**, faqat PostgreSQL'da
va faqat `cash` sxemasi mavjud bo'lsa:

1. `ALTER TYPE cash.cash_source_type ADD VALUE IF NOT EXISTS 'ACCOUNT_OPENING'`
   — **alohida autocommit ulanishida** (yangi label o'sha tranzaksiyada ishlatilmaydi);
2. `CREATE TABLE IF NOT EXISTS cash.cash_account_openings (...)` — §2 dagi to'liq shakl;
3. `CREATE UNIQUE INDEX IF NOT EXISTS cao_uq_entry ...`;
4. append-only triggerlar — **FAQAT YO'Q BO'LSA** (`DO $$ IF NOT EXISTS (pg_trigger) …`).
   ⚠️ `DROP TRIGGER` **ataylab YO'Q**: `DROP`+`CREATE` juftligi mavjud triggerni jimgina
   almashtirardi, holbuki `cash_ddl_v1.sql` §CF-D6 append-only jadvalga haqiqiy tuzatishni
   «audit qilingan tranzaksiya ichida qo'riqchi triggerni **vaqtincha o'chirish**» deb
   ta'riflaydi — boot o'sha protsedurani o'rtasidan buzmasligi kerak;
5. grantlar: `GRANT SELECT, INSERT ON cash.cash_account_openings TO cash_posting;`
   `GRANT SELECT ... TO cash_app, cash_readonly;` `GRANT ALL ... TO cash_admin;`
   keyin `REVOKE UPDATE, DELETE, TRUNCATE ... FROM cash_posting, cash_admin;`

**Fresh baza ham AYNI qadamdan oladi** — Phase 1 obyekti bitta joyda ta'riflanadi
(`cash_ddl_v1.sql` ga nusxa ko'chirilmaydi), shu bois fresh va upgrade **ajralib keta
olmaydi**.

**Tayyorlik (readiness) — `CREATE TABLE IF NOT EXISTS` o'zi ISBOT EMAS.** Yangi
`app/services/cash/schema_readiness.opening_schema_problems(bind)` **aniq** tekshiradi:
enum labeli bor · jadval bor · har bir ustun (nom + tip + nullability) · oltita
`ck_cao_*` CHECK **ta'rifi bo'yicha** (`check_canon.canonical()`) · uchta FK · ikkita
UNIQUE (noyob, **qisman emas**, aynan shu ustunlar) · `cao_uq_entry` qisman indeksi ·
ikkita trigger · grantlar. Natija `/health/ready` da yangi **`cash_opening_schema`**
kaliti sifatida chiqadi.

**Qattiqlik darajasi (ataylab ikki xil, R-DDL naqshi):** buzuq/qisman obyekt →
**tayyorlik QIZIL** (`/health/ready` 503), boot **TO'XTAMAYDI**.

**YO'Q → YARAT, BOR-U NOTO'G'RI → TEGMA.** Bu R-DDL da qotirilgan ayni qoida:
- obyekt **yo'q** bo'lsa yaratiladi (indeks, trigger) — bu **himoyani qayta o'rnatish**,
  hech narsa yo'qotmaydi (test T-19d);
- obyekt **bor, lekin shakli boshqa** bo'lsa **tegilmaydi** va tayyorlik qizil bo'ladi
  (test T-19a) — `_ensure_cash_phase1` ichida `DROP TABLE`, `DROP TYPE`, `DROP TRIGGER`,
  `ALTER TABLE … DROP`, `REINDEX` **yo'q**.

⚠️ **Trigger uchun NOM YETMAYDI.** To'g'ri nomli, lekin boshqa (masalan bo'sh) funksiyani
chaqiradigan trigger jadvalni himoya qilmasdan «joyida» ko'rinardi — `check_canon` ning
CHECK uchun bergan darsining ayni o'zi. Shu bois tayyorlik trigger **funksiyasini** ham
tekshiradi (`fn_block_mutation` / `fn_block_truncate`).

**SQLite qamrovi:** `cash` quyi tizimi ATAYLAB faqat PostgreSQL'da (`cash_enabled`,
`require_ledger_writable`, `is_ledger_authoritative` — hammasi ayni qamrov). SQLite'da
`cash.cash_account_openings` **mavjud emas**, SEYF onboarding **mavjud emas**, va
`_ensure_cash_phase1` **no-op**. Isbot: SQLite boot yashil va yangi obyekt **yaratilmaydi**
(T-16). `CashAccountOpening` modeli `CashBase` metadata'sida (MAP-only) — `Base.create_all`
unga tegmaydi.

**PG18** — CI `prod-install`/PG18 jobi bilan.

---

## §6. B6 — HISOBOT va PARITY

### 6.1 Ochilish NIMA EMAS

Oddiy CASH IN emas · savdo tushumi emas · xarid to'lovi emas · ta'minotchiga to'lov emas ·
kassir smena ochilish float'i emas · tarixiy backfill emas. **Bu — hisobning ochilish
attestatsiyasi**, bir martalik.

### 6.2 TILL `kassada`

SEYF ochilishi TILL jamlariga **kirmaydi**: leg SEYF hisobida va `OFF_SHIFT`, TILL
ko'rsatkichlari esa TILL hisobidan/smenadan hisoblanadi. `/reports/cashflow` ning
`kassada` qismi ADJUSTMENT ni o'qimaydi — o'zgarish **kerak emas**, lekin T-13 buni
**isbot** sifatida qotiradi.

### 6.3 `compare_engine`

`ACCOUNT_OPENING` legi **NORMAL**, ya'ni `EXTRA_LEDGER` shoxiga tushadi. Uni «kutilgan»
qiladigan yagona narsa — **aniq manba shartnomasi**:

> `ACCOUNT_OPENING` legi KUTILGAN ⇔ `cash.cash_account_openings` da AYNI tenantda
> `id = leg.source_id`, `kind='COUNTED'`, `cash_account_id = leg.cash_account_id`,
> `counted_amount = leg.amount` bo'lgan qator MAVJUD.

Mos qator bo'lmasa → `EXTRA_LEDGER`; summasi boshqa bo'lsa → `WRONG_AMOUNT`; hisobi
boshqa bo'lsa → `EXTRA_LEDGER`. ⚠️ **`ADJUSTMENT` toifasi yoki NORMAL qatorlar
UMUMAN chiqarib tashlanmaydi** — faqat shu bitta manba turi, faqat mos manba qatori bilan.

⚠️ `compare_engine` **faqat o'qiydi** (`test_compare_engine_read_only_source` mutatsiya
fe'llarini taqiqlaydi) — yangi o'qish ham shu qoidaga bo'ysunadi.

### 6.4 `shadow_compare`

`_ledger_flows` NORMAL legilarni yig'adi, legacy tomonda esa ochilishning **hamkori YO'Q**
(ta'rif bo'yicha: bu legacy hodisa emas). Shu bois `_ledger_flows` **aynan
`source_type = 'ACCOUNT_OPENING'`** ni chiqarib tashlaydi — **ADJUSTMENT toifasini emas,
NORMAL qatorlarni emas**. Aks holda har bir ochilish do'konni soxta `CASH_OP` nomuvofiqligi
bilan qizil qilardi.

### 6.5 Backfill verifikatsiyasi — O'ZGARMAYDI

`backfill.verify_backfill` **tegilmaydi**: u hamon RECONSTRUCTION qatorlarining
filtrlanmagan to'plamini oladi va kutilmagan rekonstruksiyani **topadi**. `ACCOUNT_OPENING`
NORMAL bo'lgani uchun uning ko'rish maydoniga umuman kirmaydi. T-20 buni ikki tomondan
isbotlaydi: (a) ochilishdan keyin backfill verifikatsiyasi yashil qoladi;
(b) qo'lda qo'shilgan RECONSTRUCTION qatori hamon **yiqitadi**.

---

## §7. B7 — O'QISH MARSHRUTI `GET /safes/{safe_id}/balance`

Javob:

```jsonc
{
  "id": "…", "code": "…", "label": "…", "branch_id": "…", "currency": "UZS",
  "status": "ACTIVE",
  "operational": true,                      // §3.1 predikati
  "opening": {
    "state": "COUNTED",                     // UNKNOWN | KNOWN_ZERO | COUNTED
    "amount": "1250000.00",                 // FAQAT COUNTED da; aks holda null
    "counted_at": "2026-09-20T09:00:00Z",   // FAQAT COUNTED/KNOWN_ZERO da
    "attested_by": "…", "attestation_ref": "…"
  },
  "balance": "1418000.00",                  // UNKNOWN bo'lsa -> null
  "as_of": "2026-09-28T07:41:12Z"
}
```

⚠️ **UNKNOWN da `balance` — `null`, `0` EMAS.** Nol raqam «seyf bo'sh» degan **yolg'on**
ma'no berardi. `operational=false` va `opening.state="UNKNOWN"` sababni aytadi.

⚠️ **`POST /safes/{id}/opening` javobi `result` kalitini beradi** (`created` |
`duplicate`), `status` EMAS: `status` — HISOBNING holati (`ACTIVE`/`ARCHIVED`) va
ikkisi bir kalitga tushsa attestatsiya natijasi jimgina yo'qolardi (implementatsiyada
topilgan, test `T-22f` bilan qotirilgan).

**Ruxsat (audit qilingan):** mavjud `/safes` ro'yxati `TILL_READ_PERMS`
(`kassa.sell`, `kassa.view`, `sozlamalar.view`, `sozlamalar.edit`, `hisobot.view`) bilan
ochiladi. Balans — **pul ma'lumoti**, shu bois kassirga tegishli kodlar (`kassa.sell`,
`kassa.view`) **chiqarib tashlanadi**:
`require_any("hisobot.view", "sozlamalar.view", "sozlamalar.edit", "kassa.attest")`.
Doira `_readable_branch` orqali (filial ko'rinmasa **404**, mavjudlik oshkor qilinmaydi) —
`tills.py` ning mavjud naqshi.

**Obuna marshrut tasnifi — INTEGRATSIYA TALABI (tekshirildi 2026-09-28):** mexanizm
`p6a-admin-subscription` shoxida **MAVJUD** (`app/core/subscription_routes.py`) va u
**majburiy**: `tests/test_subscription_enforcement.py::test_QAMROV_TASNIFLANMAGAN_marshrut_darvozada_TOSILADI`
tasniflanmagan marshrutni QIZIL qiladi. Ikki shox **mustaqil** (biri ikkinchisining ajdodi
emas), shu bois **qo'shilganda** quyidagi ikki satr qo'shilishi SHART — aks holda qamrov
qo'riqchisi yiqiladi:

```python
("POST", "/safes/{safe_id}/opening"): BLOCK_BUSINESS_WRITE,   # `("POST", "/safes")` bilan izchil
("GET",  "/safes/{safe_id}/balance"): ALLOW_READ,             # `("GET", "/safes")` bilan izchil
```

Bu ega qaroridagi tasnif bilan AYNAN bir xil. Shu shoxning O'ZIDA mexanizm yo'q, shu bois
bu yerda hech narsa tasniflanmaydi.

~~**Obuna marshrut tasnifi:** bu shoxda (`p6c-purchase-settlement`) marshrutlarni
`BLOCK_BUSINESS_WRITE` / `ALLOW_READ` deb belgilaydigan mexanizm **MAVJUD EMAS**
(Phase 6A ishi, boshqa worktree'da). Shu bois Phase 1 hech narsa tasniflamaydi;
mexanizm kelganda: attestatsiya = **BLOCK_BUSINESS_WRITE**, balans o'qish = **ALLOW_READ**.~~
*(yuqoridagi blok bilan almashtirildi — mexanizm topildi va aniq talab yozildi)*

---

## §8. OCHILISH VAQTI

- `counted_at` — **majburiy** so'rov maydoni. Server vaqtiga **jimgina tushmaydi**:
  aniq sanoq vaqti ma'lum bo'lmasa, bu **noaniqlik** va u yashirilmaydi (400).
- `device_occurred_at = counted_at` — hisob hodisasining vaqti **jismoniy sanoq** vaqti.
- `recorded_at` / `server_received_at` — mavjud semantikasi bilan qoladi (server vaqti);
  `posting._new_entry` ularni o'zi qo'yadi.
- **Tekshiruv:** `counted_at` kelajakda bo'lmasin (soat qiyshiqligi uchun +5 daqiqa
  toleranti) **va** `cash_accounts.created_at` dan oldin bo'lmasin. Ikkinchisi sana
  **to'qib chiqarishni** to'sadi: jismoniy pul eskiroq bo'lishi mumkin, lekin **shu
  hisobni ochgan sanoq** hisob mavjud bo'lgandan keyin bajariladi. Bu, shuningdek,
  ochilishni T0 dan oldingi oynaga suqib qo'yishni ham to'sadi.

---

## §9. TUZATISH SIYOSATI (Phase 1)

- O'zgaruvchan tahrir **YO'Q** (jadval append-only, triggerlar bilan).
- Tuzatish/reversal ish oqimi Phase 1 da **YO'Q**.
- Zid qayta-attestatsiya → **`409 SAFE_OPENING_CONFLICT`**, fail-closed.
- Noto'g'ri ochilishni tuzatish — **kelgusi bosqich qarori** (alohida, attestatsiyalangan
  yo'l; jimgina UPDATE hech qachon).

---

## §10. XATO KODLARI (mavjud konvensiya, yangi mexanizm YO'Q)

`cutover_guard.ERROR_CODES` oilasiga qo'shiladi (`"<KOD>: matn"` prefiksi + 5G.1 dan
`X-Error-Code` sarlavhasi), `packages/shared/src/lib/serverErrorsCash.ts` ga tarjima:

| Kod | HTTP | Qachon |
|---|---|---|
| `SAFE_OPENING_REQUIRED` | 409 | SEYF operatsion emas (ochilish yozuvi yo'q yoki buzuq) |
| `SAFE_OPENING_CONFLICT` | 409 | boshqa payload bilan qayta attestatsiya / noyoblik to'qnashuvi |
| `SAFE_OPENING_BLOCKED_BY_HISTORY` | 409 | hisobda ledger tarixi bor, ochilish yozuvi yo'q |

Mavjud kodlar qayta ishlatiladi: `ACCOUNT_NOT_FOUND` (404), `UNAUTHORIZED_OPERATION`
(menejer+), `PERMISSION_DENIED` (403), `CASH_LEDGER_UNAVAILABLE` (ledger yozib bo'lmaydi).
**Dublikat kod ixtiro qilinmaydi.**

---

## §11. TESTLAR — 22 holat (RED/GREEN sezgirligi bilan)

| # | Holat | Kutilgan |
|---|---|---|
| T-1 | ochilish legi AYNAN: NORMAL·ACCOUNT_OPENING·ADJUSTMENT·IN·OFF_SHIFT·shift NULL·SAFE | yashil |
| T-2 | KNOWN_ZERO: yozuv bor, **ledger legi YO'Q**, `ledger_entry_id IS NULL` | yashil |
| T-3 | COUNTED: **aynan bitta** leg, summa = `counted_amount` | yashil |
| T-4 | UNKNOWN SEYF: `opening_state` = UNKNOWN, `is_operational` = False | yashil |
| T-5 | UNKNOWN SEYFdan xarid to'lovi / custody tanlovi → `SAFE_OPENING_REQUIRED` | rad |
| T-6 | UNKNOWN SEYFga inkassa (transfer manzili) → rad | rad |
| T-7 | ochilish postingi gardni **aylanib o'tadi** (o'zi uchun istisno) | yashil |
| T-8 | TILL hisobiga ochilish → rad (SAFE-only, DB CHECK + xizmat) | rad |
| T-9 | ayni payload qayta → `200`, **ikkinchi leg YO'Q**, ayni `opening.id` | idempotent |
| T-10 | boshqa payload qayta → `409 SAFE_OPENING_CONFLICT`, hech narsa yozilmaydi | rad |
| T-11 | parallel ikki attestatsiya → **aynan bittasi** yozadi (qulf + `cao_uq_account`) | 1 ta |
| T-12 | ledger tarixi bor + ochilish yo'q → `409 SAFE_OPENING_BLOCKED_BY_HISTORY` | rad |
| T-13 | SEYF ochilishi TILL `kassada` jamiga **kirmaydi** | isbot |
| T-14 | `compare_engine`: mos manba bor → **nomuvofiqlik YO'Q** | yashil |
| T-15 | `compare_engine`: (a) manbasiz **soxta** leg → `EXTRA_LEDGER`; (b) summa boshqa → `WRONG_AMOUNT`; (c) ikkinchi leg → `EXTRA_LEDGER` | rad |
| T-16 | `shadow_compare`: ochilish deltasi **YO'Q**; boshqa ADJUSTMENT/NORMAL qator hamon **ko'rinadi** | yashil |
| T-17 | `kassa.attest` yo'q → 403; bor, lekin **kassir** → menejer+ darvozasi rad; mavjud do'kon bootda ruxsatni **oladi** | rad/yashil |
| T-18 | sxema: fresh PG · mavjud PG upgrade · **ikkinchi boot no-op** (oid o'zgarmaydi) | yashil |
| T-19 | tayyorlik: buzuq/qisman obyekt (ustun yo'q, CHECK boshqa, indeks qisman) → `cash_opening_schema` **QIZIL**, boot to'xtamaydi, obyekt **almashtirilmaydi**; SQLite bootda obyekt **yaratilmaydi** | qizil/no-op |
| T-20 | `verify_backfill`: (a) ochilishdan keyin **yashil**; (b) qo'shilgan RECONSTRUCTION hamon **yiqitadi** | yashil/rad |
| T-21 | `counted_at`: majburiy (yo'q → 400) · kelajak → 400 · hisob `created_at` dan oldin → 400 · legning `device_occurred_at` = `counted_at` | rad/yashil |
| T-22 | `GET /safes/{id}/balance`: UNKNOWN → `balance = null` (**0 EMAS**) · COUNTED → hosil qilingan balans + ochilish summasi · kassir kodi bilan 403 · boshqa filial → 404 · boshqa tenant → 404 | yashil |

**Sezgirlik:** har bir test implementatsiyadan OLDIN **QIZIL** bo'lishi yozib olinadi
(T-14/T-16 uchun «RED» = mos manba shartnomasi yo'qligida soxta nomuvofiqlik/delta).

**Joylashuv va bajarilgan sonlar** (22 nomlangan holat parametrlash bilan 65 testga yoyildi):

| Fayl | Nima | Testlar |
|---|---|---|
| `tests/test_safe_opening_schema_pg.py` | T-18a–e, T-19a×4, T-19b–d — haqiqiy PG + haqiqiy boot | 12 |
| `tests/test_safe_opening_schema_sqlite.py` | SQLite qamrovi, ikkinchi boot, model metadata | 3 |
| `tests/cash/test_safe_opening.py` | T-1…T-12, T-17, T-21 + shakl/o'zgarmaslik | 27 |
| `tests/cash/test_safe_opening_parity.py` | T-13, T-13b, T-14, T-15a–c, T-16, T-20 | 9 |
| `tests/cash/test_safe_opening_api.py` | T-22a–f + balans darvozasi | 7 |
| `tests/test_safe_opening_permission.py` | `kassa.attest` simlari, boot yetkazishi | 7 |

**MAVJUD TESTLARNING QAYTA BAZALANISHI (32 ta).** Gard joriy qilingach cash to'plamida
32 test yiqildi — hammasi AYNI sababdan: ular SEYF yaratib, uni attestatsiyasiz
ishlatardi. Tasnif: 29 tasi to'g'ridan-to'g'ri `SAFE_OPENING_REQUIRED` (18 custody gardi +
11 posting servisi), 2 tasi tartib (quyida), 1 tasi `_check_db` mock arligi.

Yechim: `tests/cash/_factory.open_safe(...)` — HAQIQIY xizmat orqali, standart
`KNOWN_ZERO` (ledger legi YO'Q, ya'ni mavjud balans/parity sonlari O'ZGARMAYDI).
Birorta assert **kuchsizlantirilmadi, o'chirilmadi yoki skip qilinmadi**.

⚠️ **TARTIB NUQSONI (test topdi, KOD tuzatildi).** Gard dastlab `_resolve_account` dan
keyin turardi va SEYFga **zid smena** bergan chaqiruvchining
`SHIFT_NOT_BELONG_TO_ACCOUNT` xatosini **yopib qo'yardi**. Bu dasturchini noto'g'ri izga
solardi: seyfni attestatsiya qilgach ham so'rov hamon buzuq bo'lib qolardi. Endi gard
so'rov shakli tekshirilgandan (`_resolve_shift`) **KEYIN** va idempotentlikdan keyin
ishlaydi — replay rad etilmaydi. `post_transfer` da ham AYNI tartib.

**Sezgirlik (RED isboti):** parity tuzatishlari (`compare_engine._opening_expected` +
`shadow_compare` istisnosi) **qaytarilganda** T-14, T-15b, T-15c, T-16 **yiqiladi**
(4 failed / 4 passed); qolgan 4 tasi manfiy nazorat — ular ikkala holatda ham yashil
bo'lishi SHART. Sxema tomonida implementatsiyasiz butun fayl import xatosida yiqiladi.
⚠️ Ildiz `tests/*.py` va `tests/cash/*.py` **bitta pytest chaqiruvida aralashtirilmaydi**.
⚠️ `PYTHONIOENCODING=utf-8` bilan yurgizilmaydi.

---

## §11.1 DEPLOY OQIBATI — SEYF ENDI ATTESTATSIYASIZ ISHLAMAYDI

Bu **xulq o'zgarishi**, faqat yangi imkoniyat emas. Deploydan keyin:

| Holat | Oqibat | Yechim |
|---|---|---|
| **Yangi SEYF** (`POST /safes`) | yaratiladi, lekin **ISHLAMAYDI** — inkassa ham, undan to'lov ham rad (`SAFE_OPENING_REQUIRED`) | menejer+ attestatsiya qiladi: bo'sh seyf → `KNOWN_ZERO`, pul bor → `COUNTED` |
| **SEYF bor, ledger tarixi YO'Q** | ayni yuqoridagi | attestatsiya |
| **SEYF bor, ledger tarixi BOR, ochilish yozuvi yo'q** | **ISHLAMAYDI va ATTESTATSIYA HAM RAD** (`SAFE_OPENING_BLOCKED_BY_HISTORY`) | ⚠️ **alohida migratsiya qarori** — Phase 1 buni hal qilmaydi |

⚠️ **Nega `create_safe` avtomatik `KNOWN_ZERO` yozmaydi:** bu qoldiqni **taxmin qilish**
bo'lardi — yangi yaratilgan hisob yozuvi ichida ega pulining bor-yo'qligi haqida server
hech narsa bilmaydi. Ega ANIQ aytishi kerak; aynan shu Phase 1 ning mavjud sababi.

### §11.1.1 PRODUCTION DALILI (jonli, FAQAT O'QISH — 2026-09-28)

`railway ssh --service Postgres-d29B` orqali `BEGIN READ ONLY` + `statement_timeout`
tranzaksiyasida **faqat SELECT** (yozuv DB darajasida imkonsiz edi):

| O'lchov | Qiymat |
|---|---|
| `cash` sxemasi | BOR |
| kompaniyalar | **1** |
| TILL hisoblari | **1** |
| **SEYF hisoblari** | **0** |
| **ledger legi bor SEYFlar** | **0** |
| `cash.cash_account_openings` | YO'Q (Phase 1 deploy qilinmagan — kutilgani) |

**Xulosa:** Phase 1 tayyorlik qoidasi bugungi production'da **hech kimni to'smaydi** —
to'siladigan SEYF ham, «o'lik tugun» holati ham **NOL**. Yuqoridagi jadvalning uchinchi
qatori bugun **bo'sh**; qoida kelgusi holat uchun yopiq turadi.

⚠️ Zond `cash_preflight_ro` maxsus roli bilan EMAS, mavjud servis roli bilan bajarildi
(u rol DBA tomonidan alohida yaratilishi kerak — `PRODUCTION_READONLY_ACCESS_RUNBOOK.md`
STEP 0). Yozuvdan himoya **seans darajasida** `default_transaction_read_only=on` bilan
ta'minlandi.

⚠️ **Uchinchi qatorning bugungi xavfi:** production'da SEYF **YO'Q** (Phase 8 hali
boshlanmagan) va Phase 2 ning SEYF yo'li «kodda ochiq, amalda ishlatilmaydi» holatida
(DESIGN §13). Ya'ni bu qator **bugun bo'sh**; u kelgusi holatni yopiq qiladi.

---

## §12. Phase 1 NIMA QILMAYDI

- `purchase_settlements` (Phase 3) · Manager UI (Phase 4) · kreditor (6a/6b/7) — **yo'q**.
- **Fayzanda haqiqiy SEYF yaratilmaydi** (Phase 8; oldingi shart — shu bosqich
  implement **va** verify).
- `SAFE_CASH` settlement manbasi **yoqilmaydi** (Phase 3s).
- Ochilish tuzatish/reversal yo'li **yo'q** (§9).
- Production/staging **tegilmaydi**, deploy **yo'q**, `main` merge **yo'q**.
- `verify_backfill`, `cash_ddl_v1.sql`, `required_schema` ning public qamrovi
  **o'zgartirilmaydi**.

