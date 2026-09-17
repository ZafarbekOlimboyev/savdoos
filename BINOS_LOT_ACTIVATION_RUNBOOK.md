# BinOS — Fayzan partiya (lot) kuzatuvi aktivatsiyasi — operator runbook

> **Doira:** production'da **bitta do'kon (`fayzan1`), bitta filial**, tanlangan mahsulotlar uchun
> partiya/muddat kuzatuvini yoqish. Hujjat Phase 5B.1 kodiga (`phase5b/lot-prehardening`) tayanadi.
>
> **Asosiy qoida:** kuzatuvni yoqish **QAYTARIB BO'LMAYDI**. Mahsulotda `track_lots` o'chiradigan kod
> yo'q, `track_expiry` tanlovi yoqilgan paytda muzlaydi. Har bir yozadigan qadam **alohida yozma
> ruxsat** bilan bajariladi. Hujjatdagi buyruqlar faqat tavsif: ularni o'qish ruxsat EMAS.

Production identifikatorlari (2026-09-17 read-only tekshiruvi):

| Nima | Qiymat |
|---|---|
| Kompaniya `fayzan1` | `8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5` |
| Yagona filial (Asia/Bishkek, faol) | `c311874f-4787-405a-94f2-af9347f999aa` |
| Production Postgres `system_identifier` | `7674898282858840119` |
| Xodimlar | 1 × `ega`, 1 × `kassir`; ruxsat override'lari 0 |
| Mahsulotlar / kuzatuvli | 7137 / 0 (`track_lots=0`, `track_expiry=0`) |
| `settings.catalog` | yo'q |

---

## 0. Aktivatsiyadan OLDIN yopilishi SHART bo'lgan blokerlar

Quyidagilardan birortasi ochiq bo'lsa, 8-qadamga (mahsulotni yoqish) O'TILMAYDI.

| # | Bloker | Nega | Holat |
|---|---|---|---|
| B1 | **1C cutover aktivatsiyadan OLDIN tugashi kerak** | `migrator_1c` apply kuzatuvli mahsulotni rad etadi, `verify-applied` esa do'konda BITTA kuzatuvli mahsulot bo'lsa ham yiqiladi. Aktivatsiya birinchi bo'lsa, 1C migratsiyasi umuman imkonsiz bo'ladi. | 1C discovery kutilmoqda |
| B2 | ~~**Kirim UI partiya yubormaydi**~~ — Manager tomoni YOPILDI (Phase 5C) | Manager «Yangi kirim» (Xaridlar) va «Rasm orqali kirim» endi kuzatuvli qatorda partiya muharririni ochadi va `lots` yuboradi; kirim tafsilotida kuzatuvli qator qulflangan (server tannarx tahririni ham 409 bilan rad etadi). Kuzatuvsiz kirim payloadi O'ZGARMADI. **QOLGAN CHEKLOVLAR:** (a) **mobil ilova** (`apps/mobile`) hamon `lots` yubormaydi — kuzatuvli mahsulotli har qanday mobil kirim/hisobdan chiqarish/sanoq butun hujjat bilan 400 oladi va xato xom lotin matnida ko'rinadi; (b) `POST /purchases` (menejer xaridi) va filiallararo ko'chirish 409; (c) kirim filiali har doim `actor_branch` (§6). | Manager'dan kirim OCHIQ. **Pilot mahsulotlar MOBIL ilovadan kirim/hisobdan chiqarish/sanoq qilinmaydi**, xarid (`/purchases`) va ko'chirishdan ham o'tmaydi |
| B3 | **Aktivatsiyadan oldingi chekni qaytarish** | Kuzatuv yoqilgunga qadar sotilgan qatorda orqaga o'raydigan taqsimot YO'Q. Siyosat (Phase 5C): `restock=false` — RUXSAT (partiya, qarz va taqsimot TEGILMAYDI; tannarx asl chekdan); `restock=true` — 409 `LOT_RETURN_PRE_ACTIVATION`. Tasnif TUZILISH bo'yicha (`sold_at` bo'yicha EMAS). | **YOPILDI** — §2.12; operator ko'rsatmasi shu yerda |
| B4 | **Yoqish UI yo'q** | `/lots/enable` va `/lots/timezone/confirm` faqat API (ega tokeni) orqali. | Operator qadami |
| B5 | **Kuzatuvli mahsulotda birlik/tarozi o'zgarishi himoyasiz** | `PATCH /products` kuzatuvli mahsulotda `unit_code`/`is_weighted` ni o'zgartirishga yo'l qo'yadi. | Pilot davomida bu maydonlar o'zgartirilmaydi |
| B6 | **Ko'p filial** | §6 ga qarang. Fayzan (1 filial) uchun bloker EMAS, lekin ko'p filialli har qanday tenant uchun bloker. | — |
| B7 | **Ommaviy yoqish yo'q** | Har mahsulot bitta `POST /lots/enable` chaqiruvi (schema introspection + qatorlarni qulflash). 7137 mahsulotni savdo vaqtida yoqish mumkin emas. | Faqat kichik pilot to'plami |
| B8 | **UUID ustun tipi migratsiyasi qo'llanmagan** | Deploy endi tipni O'ZI tuzatmaydi (§2.1, §2.1a). Tuzatilmaguncha `/health/ready` 503 (`column_types=false`) — 3-qadam STOP; naqd kirim/chiqim va QR dedup 42883 beradi. | Production'da faqat `preflight` (READY kutiladi); `apply --commit` ALOHIDA yozma ruxsat bilan, sokin oynada |

---

## 1. Bosqichlar

| # | Qadam | Buyruq / tekshiruv | Yozadimi | STOP sharti |
|---|---|---|---|---|
| 1 | Production hardening deploy (exact SHA) | §2.1 | HA (kod + boot DDL; ustun TIPI emas) | health commit ≠ SHA; boot jurnalida `[FATAL]`; boot jurnalida `-> uuid` (boot tipni o'zgartirmasligi SHART) |
| 1a | UUID ustun tipi migratsiyasi (aniq qadam) | §2.1a | preflight — yo'q; apply — HA (alohida yozma ruxsat) | preflight `BLOCKED`; `REJECTED_STATE_CHANGED`; verify FAIL |
| 2 | Backup + restore mashqi | §2.2 | yo'q (production'ga) | artefakt bo'sh; restore mashqi qizil |
| 3 | health / ready | §2.3 | yo'q | biror check `false` |
| 4 | Fayzan fingerprint (read-only) | §2.4 | yo'q | `track_lots>0`, `settings.catalog` bor, biznes digest kutilmagan farq |
| 5 | Filial vaqt zonasi: tekshirish / tasdiqlash | §2.5 | tasdiq — HA (`settings.catalog` + audit) | zona `Asia/Bishkek` emas yoki `timezone_supported=false` |
| 6 | Aktivatsiya muhit siyosati | §2.6 | yo'q | `APP_ENV`/platforma `production` emas |
| 7 | Aniq do'kon × filial darvozasi | §2.7 | HA (Railway o'zgaruvchisi + restart) | boot jurnalida `rejim=scoped, ro'yxat yozuvlari=1` emas; boshqa do'kon uchun `activation_allowed=true` |
| 8 | Tanlangan mahsulotni yoqish | §2.8 | HA (qaytarilmaydi) | preflight qizil; javob ≠ 200; invariant tekshiruvi mos emas |
| 9 | Ochilish partiyasi strategiyasi | §2.9 | (8 ichida) | yig'indi qoldiqqa teng emas |
| 10 | Smoke | §2.10 | yo'q | §2.10 dagi birorta shart |
| 11 | Monitoring oynasi | §2.11 | yo'q | §3 dagi rollback sharti |
| 12 | Rollback shartlari va darvozani yopish | §3 | HA (o'zgaruvchini olib tashlash) | — |

---

## 2. Qadamlar tafsiloti

### 2.1 Production hardening deploy

- **PRECONDITION:** yakuniy SHA uchun CI 6/6 yashil, PG18 bajarilish isboti bor; staging'da AYNI SHA smoke PASS; 2-qadamdagi backup yangi.
- **BUYRUQ:** Railway GraphQL `serviceInstanceDeployV2(serviceId, environmentId=<production>, commitSha=<40 belgili SHA>)`.
  Production'da avtomatik deploy trigger'i YO'Q; deploy faqat ongli, aniq SHA bilan qilinadi.
  `railway up` yuklaganidan farqli o'laroq, bu usul `/health` dagi `build.commit` ni aynan shu SHA'ga bog'laydi.
- **BOOT'DA KUTILADI** (`python -m app.initdb`, `start.sh`):
  - `[boot] lock_timeout=2s — ...`
  - `[boot] partiya faollashtirish: rejim=closed, ro'yxat yozuvlari=0`. `SAVDOOS_LOT_ACTIVATION_SCOPES` hali berilMAGAN bo'lishi shart.
  - **DEPLOY USTUN TIPINI TUZATMAYDI (Phase 5C).** Production'da `cash_movements.client_uuid`,
    `qr_payments.sale_id` va `qr_payments.client_uuid` hozir VARCHAR, model esa UUID kutadi (shu sabab naqd
    kirim/chiqim va QR dedup so'rovlari `42883 operator does not exist` bilan yiqiladi). Ilgari buni birinchi
    boot o'zi `ALTER .. TYPE uuid` bilan tuzatardi — **endi yo'q**: mavjud ustun tipini almashtirish jadvalni
    qayta yozadi (ACCESS EXCLUSIVE, har indeks qayta quriladi) va qiymatlar bo'yicha operator qarorini talab
    qiladi; qulf band bo'lsa eski yo'l `[FATAL]` + Railway qayta urinishi = crash-loop bo'lardi.
  - Tuzatilmagan bazada boot jurnalida KUTILADI (bu **YIQILISH EMAS**):
    `[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: <jadval>.<ustun>` (3 satr) va
    `[schema] ustun tipi og'ishi — tuzatish (boot EMAS, operator): python -m app.tools.schema_migrate preflight --migration 2026-09-17.uuid-client-columns-v1`.
    Bu holatda `/health/ready` **503** (`column_types=false`) — ya'ni 3-qadam STOP. Tuzatish §2.1a da.
  - `[FATAL]` yo'q; `[migrate] ... -> uuid` satri ham **CHIQMASLIGI SHART** (boot DDL yubormaydi).
- **KUTILADI:** `/api/v1/health` → `build.commit == SHA`, `environment=production`, `platform_environment=production`.
- **STOP:** `[FATAL]` (Railway ON_FAILURE 5 marta qayta uradi). Bu holatda oldingi deploy'ga qaytiladi (§3.3) va sabab jurnaldan o'qiladi.

### 2.1a UUID ustun tipi migratsiyasi (ANIQ operator qadami)

> **Bu bosqichda production'da FAQAT `preflight` bajariladi.** `apply --commit` production'ga
> **ALOHIDA YOZMA ruxsat** bilan va sokin oynada (smena yopiq, POS offline navbati bo'sh)
> qilinadi; buyruqlarni o'qish ruxsat EMAS (§0 B8).

Vosita: `python -m app.tools.schema_migrate` (chiqish kodlari: 0 = OK/ALREADY_APPLIED,
1 = usage/darvoza rad etdi, 2 = REVIEW yoki qulf band, 3 = BLOCKED/REJECTED/verify FAIL).
Chiqishda **qiymat, DSN, host YO'Q** — faqat sanoq, struktura va sha256.

1. **PREFLIGHT (faqat o'qish, har muhitda ruxsat).** Sessiya `default_transaction_read_only=on`
   + `REPEATABLE READ READ ONLY`; read-only ISBOTI (negativ zond `25006`) hisobotga yoziladi.
   ```bash
   python -m app.tools.schema_migrate preflight --migration 2026-09-17.uuid-client-columns-v1 \
       --expect-system-identifier 7674898282858840119 --out uuid-preflight.json
   ```
   - **KUTILADI (production, 2026-09-17 holati):** `verdict=READY`, 3 ta og'ish, 0 qator, 0 bloker.
   - **BLOCKED sabablari** (apply RAD etiladi, qiymatlar operator qarori): `UUID_NONCANONICAL`,
     `UUID_EMPTY_STRING`, `UUID_CASE_DUPLICATE_IN_UNIQUE_KEY` (bir smenada faqat registri bilan farq
     qiladigan `client_uuid` — uuid'ga o'tgach 23505), `UUID_UNEXPECTED_INDEX/DEPENDENCY`,
     `UUID_EXPECTED_INDEX_MISSING`, `UUID_TABLE_MISSING/UUID_COLUMN_MISSING`.
   - `UUID_NOT_TABLE_OWNER` — REVIEW (exit 2): faqat o'qish login'i hisobot tayyorlay oladi,
     `apply` esa jadval EGASI bilan bajariladi.
2. **KO'RIB CHIQISH.** Hisobot saqlanadi (dalil): `plan_sha256` (struktura + baza identiteti),
   `report_sha256`, qiymat sinflari SANOG'I. `apply` shu faylni talab qiladi va uni bazaga
   bog'laydi: boshqa baza, buzilgan sha yoki **preflightdan keyin o'zgargan struktura** →
   `REJECTED_STATE_CHANGED` (exit 3), preflight QAYTA bajariladi.
3. **MASHQ (hech narsa o'zgarmaydi).**
   ```bash
   python -m app.tools.schema_migrate apply --migration 2026-09-17.uuid-client-columns-v1 \
       --report uuid-preflight.json --expect-system-identifier <sysid> --rehearse
   ```
   Tranzaksiya DOIM qaytariladi; keyin katalog qayta o'qilib, tip o'zgarmagani tasdiqlanadi.
4. **APPLY (yozadi — ALOHIDA YOZMA RUXSAT).** Bitta tranzaksiya: `SET LOCAL lock_timeout` +
   `statement_timeout` → `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE` (nomlar bo'yicha tartiblangan) →
   preflight QULF OSTIDA qayta hisoblanadi va `plan_sha256` tengligi talab qilinadi → digest →
   har jadvalga BITTA `ALTER ... TYPE uuid USING lower(col)::uuid` → tranzaksiya ichida yakuniy
   tekshiruv (tip, indeks noyob/yaroqli/ayni ta'rif, digest). Har qanday nomuvofiqlik → to'liq ROLLBACK.
   ```bash
   python -m app.tools.schema_migrate apply --migration 2026-09-17.uuid-client-columns-v1 \
       --report uuid-preflight.json --expect-system-identifier <sysid> --commit \
       --lock-timeout-ms 2000 --statement-timeout-ms 60000
   ```
   - **Production bazasi uchun qo'shimcha**: `--allow-production` **VA**
     `--confirm-production-system-identifier <ayni sysid>`, hamda muhit o'zini production deb
     e'lon qilgan bo'lishi (`APP_ENV`/`RAILWAY_ENVIRONMENT_NAME`) shart. Bu bosqichda bu buyruq
     **bajarilmaydi**.
   - **Qulf band** (`exit 2`): hech narsa o'zgarmaydi, to'sayotgan seans pid'i chop etiladi —
     sokin oynada qayta uriniladi. Qisman holat bo'lishi MUMKIN EMAS (bitta tranzaksiya).
   - Hovuzdagi tayyorlangan so'rovlar (`psycopg3 prepare_threshold`) uchun apply **deploy/restart
     bilan yonma-yon** bajariladi.
5. **VERIFY (faqat o'qish).**
   ```bash
   python -m app.tools.schema_migrate verify --migration 2026-09-17.uuid-client-columns-v1 \
       --expect-system-identifier <sysid>
   ```
   Katalog tiplari + `column_type_problems == []` + ORM zondlari (42883 yo'q). So'ng §2.3:
   `/health/ready` 200 va `column_types=true`.
6. **REVERT** (`revert --commit`) faqat mashq/favqulodda holat uchun: u 42883 nuqsonini QAYTARADI
   va asli KATTA harfli bo'lgan qiymatlar kichik harfda qoladi (preflightdagi
   `canonical_other_case` — o'sha dalil).

### 2.2 Backup va restore mashqi

```bash
gh workflow run db-backup.yml --repo ZafarbekOlimboyev/savdoos --ref main
```
- **KUTILADI:** run yashil; artefakt `savdoos-db-<tier>-<run_id>` bo'sh emas, `meta.json` ichida `capture_quiescent` bor.

```bash
gh workflow run restore-rehearsal.yml --repo ZafarbekOlimboyev/savdoos --ref main -f backup_run_id=<run_id>
```
- **KUTILADI:** vaqtinchalik PG18 ga tiklanadi, fingerprint mos keladi, `python -m app.initdb` ishlaydi, `/api/v1/health/ready` 200 qaytaradi.
- **ESLATMA:** backup aktivatsiyani «qaytarmaydi». Restore backup'dan keyingi BARCHA savdoni yo'qotadi (§3.3).

### 2.3 health / ready

```bash
curl -s https://savdoos-production.up.railway.app/api/v1/health/ready
```
- **KUTILADI:** HTTP 200, `status=ready` va barcha check'lar `true`:
  - `database`, `cash_schema`, `config`, `tenancy_schema`, `catalog_v2_schema`, `lot_schema_integrity`;
  - `idempotency_schema` — offline dedup va pul/ombor noyobligi indekslari mavjud, yaroqli va noyob;
  - `column_types` — **§2.1a dagi ANIQ migratsiya qo'llanganidan keyin** `true` (deploy uni o'zi
    tuzatmaydi; tuzatilmaguncha bu kalit `false` va butun javob 503).
- **STOP:** biror check `false`. `/lots/enable` sxema yaxlitligi to'liq bo'lmasa baribir 409 qaytaradi, lekin readiness'siz davom etilMAYDI.

### 2.4 Fayzan fingerprint (read-only)

Faqat o'qish sessiyasi ishlatiladi: `default_transaction_read_only=on`, `REPEATABLE READ, READ ONLY`, avval `system_identifier` tekshiriladi.

```sql
SELECT
  (SELECT count(*) FROM products  WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5')                 AS products,
  (SELECT count(*) FROM products  WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5' AND track_lots)  AS track_lots,
  (SELECT count(*) FROM products  WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5' AND track_expiry) AS track_expiry,
  (SELECT count(*) FROM settings  WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5' AND key = 'catalog') AS settings_catalog,
  (SELECT count(*) FROM stock_batches WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5')              AS stock_batches,
  (SELECT count(*) FROM lot_shortfalls WHERE company_id = '8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5')             AS lot_shortfalls;
```
- **KUTILADI (aktivatsiyadan oldin):** `track_lots=0`, `track_expiry=0`, `settings_catalog=0`, `stock_batches=0`, `lot_shortfalls=0`.
- **Qo'shimcha:** jadvallar kesimida mantiqiy digest (`row_to_json` ning md5, bitta snapshot). U aktivatsiyadan keyingi farqni «kutilgan yozuvlar» va «kutilmagan o'zgarishlar» ga ajratish uchun kerak.
- ⚠️ Repodagi `python -m app.tools.db_fingerprint` faqat qator SONLARINI oladi. Unda partiya jadvallari va `products.track_lots` digest'i yo'q, shuning uchun bu qadam uchun YETARLI EMAS.
- ⚠️ Operatorning haqiqiy faolligi (login, parol tiklash, savdo) digest'ni o'zgartiradi. Farq jadval bo'yicha ajratiladi va Claude/operator amali sifatida ALOHIDA yoziladi.

### 2.5 Filial vaqt zonasi: tekshirish va tasdiqlash

1. `GET /api/v1/lots/availability` (ega tokeni). `branches[]` ichida AYNAN bitta filial kutiladi:
   `timezone="Asia/Bishkek"`, `timezone_supported=true`.
2. **Tasdiq FAQAT `track_expiry=true` rejalashtirilsa kerak.** `track_lots`-only aktivatsiya tasdiqni o'qimaydi. Tasdiq `settings.catalog` qatorini yaratadi, shuning uchun unga kerak bo'lmasa tegilmaydi.
3. Tasdiq 7-qadamdan KEYIN (darvoza ochilgach) va filial ANIQ ko'rsatilgan holda yuboriladi:
   ```http
   POST /api/v1/lots/timezone/confirm
   {"branch_id": "c311874f-4787-405a-94f2-af9347f999aa"}
   ```
   - **KUTILADI:** 200 `{ok, branch_id, timezone:"Asia/Bishkek", confirmed:true, changed:true}`. Takroriy chaqiruv `changed:false` qaytaradi va hech narsa yozmaydi.
   - **Filial zonasi keyin o'zgartirilsa** tasdiq bekor bo'ladi: kirim va sanoqdagi yangi muddatli partiyalar 409 oladi. Qayta tasdiqlash uchun darvoza ochiq bo'lishi kerak.

### 2.6 Aktivatsiya muhit siyosati

- `APP_ENV=production` va `RAILWAY_ENVIRONMENT_NAME=production` o'zgarMAYDI.
- `lot_policy.activation_mode()`:
  - `SAVDOOS_LOT_ACTIVATION_SCOPES` yo'q → `closed`: hech bir do'kon yoqa olmaydi.
  - O'zgaruvchi bor → `scoped`: faqat ro'yxatdagi AYNI `(do'kon, filial)` juftligi.
  - Platforma production, ilova esa boshqa muhit deb aytsa → `closed`.
- Muhit bo'yicha ochish (`env` rejimi) production'da **mavjud EMAS**. `dev/test/staging` da o'zgaruvchi yo'q bo'lsa `env`, bor bo'lsa ular ham `scoped`: staging production konfiguratsiyasini oldindan sinashi mumkin.

### 2.7 Aniq do'kon × filial darvozasi

- **BUYRUQ** (Railway production, `savdoos` servisi, ruxsat bilan):
  ```
  SAVDOOS_LOT_ACTIVATION_SCOPES=8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5:c311874f-4787-405a-94f2-af9347f999aa
  ```
  So'ng AYNI SHA qayta ishga tushiriladi (o'zgaruvchi jarayon boshida o'qiladi).
- **KUTILADI:**
  - boot jurnali: `[boot] partiya faollashtirish: rejim=scoped, ro'yxat yozuvlari=1`. Qiymatlar hech qayerda chiqmaydi.
  - `python -m app.tools.config_audit`: `SAVDOOS_LOT_ACTIVATION_SCOPES` qatori `REVIEW`, 1 ta yozuv.
  - `GET /lots/availability` (Fayzan ega): `activation_allowed=true`, filial qatorida ham `activation_allowed=true`. Ro'yxat yoki rejim javobda ko'rinMAYDI.
- **FAIL-CLOSED xulqi** (kodda va testlarda isbotlangan):
  - bitta buzuq yozuv (bo'sh yozuv, ikki qismdan boshqa, UUID emas) hammani yopadi;
  - `branch_id` ko'rsatilmagan so'rov 403 oladi, jimgina «standart filial» tanlanmaydi;
  - boshqa do'kon, begona yoki tasodifiy filial 403 oladi (404 emas: mavjudlik oshkor bo'lmaydi) va bazaga tegilmaydi;
  - do'konning BARCHA tirik filiallari ro'yxatda bo'lmasa yopiq. Kuzatuv mahsulot bayrog'i va butun kompaniyaga ta'sir qiladi. Keyin qo'shilgan filial darvozani avtomatik yopadi;
  - xodimga ko'rinmaydigan filial 404 oladi.
- **STOP:** boshqa do'kon uchun `activation_allowed=true` (bo'lishi mumkin emas); boot jurnalida `BUZUQ`.

### 2.8 Tanlangan mahsulotni yoqish

**Preflight (har mahsulot, read-only):**
- `inventory.qty >= 0`. Manfiy qoldiq bo'lsa invariant 409 bilan rad etiladi (`LOT_INVARIANT_BROKEN`).
- Ochiq `lot_shortfalls` yo'q.
- Mahsulot pilot davomida MOBIL kirim, xarid (`/purchases`) yoki ko'chirishdan o'tmaydi (B2). Manager «Yangi kirim» / «Rasm orqali kirim» — RUXSAT (partiya muharriri bilan, Phase 5C).
- Aktivatsiyadan oldingi chek qaytarilsa — faqat `restock=false` (§2.12). Omborga qaytarish 409 beradi.
- `track_expiry` tanlovi ongli qilinadi, chunki keyin o'zgarmaydi.
- `legacy` strategiya uchun `legacy_unit_cost` aniq bilinadi. `0` «tannarx noma'lum» deb belgilanadi.

**So'rov:**
```http
POST /api/v1/lots/enable
{
  "product_id": "<uuid>",
  "branch_id": "c311874f-4787-405a-94f2-af9347f999aa",
  "track_expiry": false,
  "reason": "Fayzan pilot: <sabab>",
  "legacy_unit_cost": 12500
}
```
Muqobil — sanalgan ochilish partiyalari:
`"opening_lots": [{"qty": 6, "unit_cost": 12500, "batch_number": "A1", "expiry_date": "2026-12-31"}]`.

**Tekshiruvlar tartibi:**
1. Ruxsat (`ombor.edit`; ega va administrator doim o'tadi).
2. Do'kon × filial darvozasi — bazadan OLDIN.
3. Sxema yaxlitligi.
4. Mahsulot va filial.
5. Muddat bo'lsa, tz tasdig'i.
6. Mahsulotning HAR filialdagi qoldiq qatori qulflanadi (yo'g'i 0 bilan yaratiladi).
7. Mahsulot qayta o'qiladi. Parallel yoqish bo'lsa, ikkinchisi 409 oladi va audit bitta qoladi.
8. Ochilish partiyalari yoziladi.
9. Bayroqlar yoqiladi.
10. Yakuniy invariant tekshiruvi.
11. Audit (`product_lot_tracking`).

**Validatsiya:**
- yaroqsiz sana → 400 (500 emas), hech narsa yozilmaydi;
- `track_expiry=true` da muddatsiz yoki o'tgan muddatli ochilish partiyasi → 400;
- `track_expiry=false` (FIFO) da sanali ochilish partiyasi → 400. Sanoq bilan AYNI qoida:
  FEFO o'tgan sanali partiyani FIFO mahsulotda ham sotmaydi. `lots` bilan kirimda ham shunday;
- yig'indi joriy qoldiqqa teng emas → 400. Miqdor taxmin qilinmaydi.

**Parallel yozuvchilar:** sotuv, offline qayta yuborish, hisobdan chiqarish, sanoq, qaytarish, xarid va ko'chirish endi kuzatuv bayrog'ini qoldiq qatori QULFIDAN KEYIN qayta o'qiydi. Yoqish bilan poyga qoldiqni partiyalardan jimgina ajrata olmaydi (PG18 da isbotlangan, §4). Shunga qaramay yoqish **savdo sokin paytda** (smena yopiq, POS offline navbati bo'sh) qilinadi. Sababi: kamdan-kam deadlock ehtimoli bor. U ma'lumotni buzmaydi, lekin bitta so'rovga 500 beradi (§5).

**KUTILADI:** 200 `{ok, product_id, track_lots:true, track_expiry, opening_qty, lots_created, lot_ids}`.

### 2.9 Ochilish partiyasi strategiyasi

| Strategiya | Qachon | Afzallik | Xavf |
|---|---|---|---|
| **B) `legacy`** — bitta partiya, miqdor = joriy qoldiq, muddat/partiya raqami NULL | Muddati ahamiyatsiz yoki noma'lum tovar | Arzon; qoldiq aynan kitobdagi qoldiq | Kitobdagi xato partiyaga o'tadi. Muddat noma'lum: `/lots/expiring` va `/lots/alerts` bu partiyani ko'rmaydi. FEFO uni muddatlilardan KEYIN sotadi |
| **A) `opening_lots`** — sanalgan partiyalar | Muddatli tovar (`track_expiry=true`) | Muddat va partiya aniq | Jismoniy sanoq kerak. Yig'indi yoqish lahzasidagi qoldiqqa 0.001 aniqlikda teng bo'lishi SHART: oradagi sotuv 400 beradi |

Pilot uchun tavsiya: kam sonli, qaytarilishi kam, kirimi rejalashtirilgan mahsulotlar. Muddatli tovarda A, qolganlarida B.

### 2.12 Aktivatsiyadan OLDIN sotilgan chekni qaytarish (B3)

Kuzatuv yoqilgunga qadar sotilgan qatorda `sale_item_lot_allocations` ham, qarz ham yo'q —
tovar qaysi jismoniy partiyadan chiqqani NOMA'LUM. Tizim buni TAXMIN QILMAYDI.

| So'rov | Natija |
|---|---|
| `restock=false` (omborga qaytarmasdan) | **RUXSAT.** Partiya, qarz va taqsimot TEGILMAYDI; qoldiq +k keyin −k (NOL). Qaytarish tannarxi asl chek qatoridan (`qty × SaleItem.unit_cost`) — ochilish partiyasi narxidan EMAS. Audit: `return_pre_activation` |
| `restock=true` (omborga qaytarish) | **409** `X-Error-Code: LOT_RETURN_PRE_ACTIVATION`, hech narsa yozilmaydi. Ochilish partiyasiga qo'shish tovarni HECH QACHON tegishli bo'lmagan kogortaga yozib, tarixiy COGS'ni to'qib chiqarardi (ochilish partiyasi shu tovar KETGANDAN keyingi qoldiqdan o'lchangan) |

**Operator ko'rsatmasi:**
1. Bunday chekni **omborga qaytarmasdan** rasmiylashtiring — pul odatdagidek qaytadi (naqd/karta/QR/nasiya yo'li o'zgarmagan).
2. Qaytgan tovar **javonga o'z-o'zidan qaytmaydi**: tizimda u hisobdan chiqarilgan (`return_in` +k, `writeoff` −k). Tovar sog'lom bo'lsa va qayta sotilishi kerak bo'lsa, uni **partiya bilan sanoq** (`/inventory/count`, `new_lots`) orqali ANIQ tannarx va muddat bilan kiritish kerak. Aks holda keyingi sanoq ortiqcha ko'rsatadi.
3. Bitta chekda ham aktivatsiyadan oldingi, ham kuzatuvli mahsulot bo'lsa va kuzatuvlisi omborga qaytishi kerak bo'lsa — **ikkita alohida qaytarish** qiling: `restock` butun hujjatga tegishli.

**Hisobot (COGS) izohi:** `restock=false` qaytarish **tannarxni qaytarmaydi** — bu B3 uchun emas,
BARCHA restock'siz qaytarishlar uchun amal qiladigan qoida (`reports.py`: `_ret_cogs()` faqat
`Return.restock IS TRUE` da). Ya'ni tushum kamayadi, tannarx sotuvda qoladi va P&L shu qatorda
zarar ko'rsatadi. Bu ONGLI: javonga qaytmagan tovarning tannarxini tiklash yo'q tovarni
qaytargandek bo'lardi. Tovar 2-bandga ko'ra sanoq bilan qayta kiritilsa, qiymat ombor
qiymatiga QAYTADI.

### 2.10 Smoke (yoqilgan har mahsulot)

- `GET /api/v1/lots/products/{id}`: `inventory_qty == Σ lot.remaining_qty − unresolved_shortfall_qty`.
- `GET /api/v1/lots/batches?product_id={id}`: ochilish partiyalari to'g'ri (`source_type` `opening` yoki `legacy`).
- `GET /api/v1/audit?entity=product_lot_tracking`: sabab (`reason`) yozilgan.
- `GET /api/v1/lots/availability`: `tracked_products` kutilgan songa teng.
- Birinchi haqiqiy sotuvdan keyin:
  - sotuv qatorida partiya ulushi bor;
  - offline sotuv qayta yuborilganda `/lots/shortfalls` da kutilmagan qarz yo'q.
- **STOP:** invariant mos emas; har qanday `LOT_*` xato kodi (§2.11).

### 2.11 Monitoring oynasi (kamida birinchi 3 savdo kuni)

| Signal | Qayerda | Nimani anglatadi |
|---|---|---|
| `invariant buzildi`, `caps buzildi`, `cost-basis nomuvofiq`, `resolve invariant buzildi` | Railway jurnali | Ombor va partiyalar mos emas. Amal bajarilmagan, lekin tekshirish SHART |
| `X-Error-Code: LOT_INVARIANT_BROKEN`, `LOT_RETURN_CAPS_VIOLATED`, `LOT_COST_BASIS_INCONSISTENT`, `LOT_RESOLVE_INVARIANT_BROKEN` | javob sarlavhasi; `/sync/push` natijasidagi `code` | Yuqoridagining barqaror kodi |
| Onlayn sotuvda 409 `sotuvga yaroqli partiya yetarli emas` | POS xabari | Partiya kam yoki muddati o'tgan. Sanoq yoki kirim kerak |
| Qaytarishda 409 `X-Error-Code: LOT_RETURN_PRE_ACTIVATION` | javob sarlavhasi; POS xabari | Aktivatsiyadan OLDIN sotilgan chek OMBORGA qaytarilmoqchi. Xato EMAS — restock'siz rasmiylashtiriladi (§2.12) |
| `/lots/alerts` → `shortfalls.open_count`, `cost_quality.unknown_cost_lots` | API | Offline sotuvdan qarz; noma'lum tannarx |
| `/lots/shortfalls` | API | Yopilmagan qarzlar |
| `/fleet/devices` → `queue_not_empty` | API | 409 olgan offline chek outbox'da har 30 s qayta yuboriladi |
| `/health/ready` (uptime workflow, har 15 daqiqa) | GitHub Actions | Sxema yoki readiness buzildi |

---

## 3. Rollback shartlari va nima qaytadi / nima QAYTMAYDI

### 3.1 Darhol to'xtash (yangi mahsulot YOQILMAYDI)

- jurnalda `LOT_INVARIANT_BROKEN` yoki boshqa `LOT_*` kod;
- `/lots/products/{id}` invarianti mos emas;
- kutilmagan `lot_shortfalls` o'sishi yoki offline navbatda 409 lar to'planishi;
- `/health/ready` qizil;
- kassada kirim/xarid oqimi pilot mahsulotda to'xtab qolgani (B2) — jumladan MOBIL kirimda 400 (mobil hali partiya yubormaydi).

### 3.2 Darvozani yopish

- `SAVDOOS_LOT_ACTIVATION_SCOPES` olib tashlanadi, AYNI SHA qayta ishga tushiriladi.
- Boot jurnalida `rejim=closed` ko'rinadi; `/lots/enable` va `/lots/timezone/confirm` 403 beradi.
- **Allaqachon kuzatuvli mahsulotlar ishlashda davom etadi:** sotuv, `lots` bilan kirim, sanoq, hisobdan chiqarish, qarz yopish. Buni `test_DARVOZA_yopilgach_YOQISH_va_TASDIQ_403_kuzatuvli_mahsulot_SOTILADI_va_KIRIM_qilinadi` testi isbotlaydi.

### 3.3 Nima QAYTMAYDI

- **`track_lots` / `track_expiry` / `lots_activated_at`:** o'chiradigan API ham, vosita ham yo'q. Qo'lda SQL ham qilinmaydi: provenance yetim qoladi, `ck_track_expiry_implies_lots` va 1C migrator tekshiruvlari buziladi.
- **Kod rollback'i:** faqat shu hardening liniyasidagi oldingi deploy'ga. `99b1da7` ga qaytish taqiqlanadi, chunki unda:
  - `/lots/timezone/confirm` darvozasiz;
  - 409 javoblari ichki matnni sizdiradi;
  - partiya maydonlarini yashirish va sotuv hujjati ruxsat darajasi yo'q;
  - do'kon × filial darvozasi yo'q.
  `89f647a` dan pastga esa partiya ma'lumoti bor bazada UMUMAN qaytilmaydi.
- **DB restore:** backup'dan keyingi BARCHA savdo, qaytarish va to'lovni yo'qotadi. Faqat halokat holati uchun (`PRODUCTION_OPERATIONS_RUNBOOK.md` §4, §11).
- **Operatsion chora:**
  - yangi yoqishni to'xtatish;
  - qarzlarni yopish (`/lots/shortfalls/{id}/resolve`);
  - partiya darajasida sanoq yoki hisobdan chiqarish;
  - `lots` bilan API orqali kirim.

---

## 4. Vaqt zonasi ↔ aktivatsiya ketma-ketligi: aylanma bog'liqlik YO'Q

**Bog'liqliklar (kod):**
- `POST /lots/timezone/confirm` faqat quyidagiga bog'liq:
  - ruxsat `sozlamalar.edit`;
  - do'kon × filial darvozasi (bazadan oldin);
  - filial va qo'llab-quvvatlanadigan zona.
  Mahsulot va kuzatuv holatini o'qimaydi.
- `POST /lots/enable`:
  - ruxsat `ombor.edit`;
  - AYNI darvoza;
  - sxema;
  - FAQAT `track_expiry=true` bo'lsa, AYNI filialning tz tasdig'i.
  `track_lots`-only yoqish tasdiqqa bog'liq emas.
- Tasdiq yoqishga bog'liq, yoqish esa tasdiqni talab qilishi mumkin. Teskari bog'liqlik yo'q, shuning uchun halqa hosil bo'lmaydi.

**Ketma-ketlik:** `ro'yxatga (do'kon, filial) qo'shish` → `tasdiq(filial)` (faqat muddat kuzatuvi kerak bo'lsa) → `yoqish(mahsulot, filial)` → `ro'yxatdan olib tashlash`.

**Ortiqcha yozuv yuzasi ochilmaydi:**
- ochiq darvoza faqat AYNI juftlikka ta'sir qiladi; boshqa har qanday do'kon yoki filial bazaga tegmasdan 403 oladi;
- ro'yxatda yo'q do'kon uchun `availability` ham `activation_allowed=false` qaytaradi;
- ko'p filialli do'konda barcha filial ro'yxatda bo'lmasa yopiq;
- muhit bo'yicha ochish production'da yo'q.

**Isbotlovchi testlar:**
- `tests/test_lot_activation_scope.py`: truth table, `ROYXATDAGI_juftlik_TASDIQ_200_va_ENABLE_track_expiry_200`, `ROYXATDAGI_dokon_FILIALSIZ_sorov_403_va_HECH_NARSA_yozilmaydi`, `ROYXATDA_YOQ_dokon_BEGONA_yoki_TASODIFIY_filial_bilan_403_404_EMAS`, `IKKI_filialli_dokon_BITTASI_royxatda_403_IKKALASI_royxatda_200`, `AVAILABILITY_filial_bayroqlari_begona_dokon_YOPIQ_royxat_OSHKOR_EMAS`, `RUXSAT_matritsasi_SCOPED_rejimda_ruxsat_DARVOZADAN_OLDIN`;
- `tests/test_lot_activation_scope_pg.py`: PostgreSQL 18 da yozuvsizlik isboti bilan;
- `tests/test_lot_tz_confirm_gate.py`: tasdiq idempotent, katalog kalitlariga tegmaydi, tasdiqsiz `track_expiry` 409, tasdiqdan keyin 200;
- `tests/test_lot_enable_race.py` va `tests/test_lot_enable_race_pg.py`: yoqish va har bir ombor yozuvchisi poygasi; eski kodda qoldiq partiyalardan ajralgan, yangisida invariant butun.

---

## 5. Ma'lum cheklovlar (bloker emas, kuzatiladi)

- **Kamdan-kam deadlock (500).** Yoqish mahsulotning har filialdagi qoldiq qatorini qulflaydi. Buning ikki ehtimoli bor:
  - bir vaqtdagi filiallararo ko'chirish (`branches FOR UPDATE`);
  - qoldiq qatori yo'q mahsulotga `min_qty` yozish.
  Postgres ulardan birini to'xtatadi va ma'lumot buzilmaydi. Yoqish tomoni deadlock'da (40P01) o'zi qayta urinadi. Ko'chirish yoki `min_qty` tomoni esa 500 olib, qo'lda qayta uriladi. Oldini olish uchun yoqish savdo sokin paytda qilinadi.
- **0-qoldiqli qatorlar.** Yoqish qoldiq qatori yo'q filiallarda `qty=0` qator yaratadi. Ko'p filialli tenantda `inventory/overview` dagi «tugagan» soni oshishi mumkin. Fayzan'da 1 filial.
- **Deploy vaqtidagi DDL — ustun TIPI uchun YO'Q (Phase 5C).** Boot mavjud ustunning tipini hech qachon
  o'zgartirmaydi: u faqat yo'q ustunni to'g'ri tipda qo'shadi, og'ishni esa `TAYYOR EMAS` + o'zgarmas
  maslahat satri bilan ko'rsatadi va tayyorlikni QIZIL qiladi. `cash_movements` va `qr_payments` dagi
  qisqa ACCESS EXCLUSIVE endi ALOHIDA operator qadamida olinadi (§2.1a): preflight → ko'rib chiqish →
  `--rehearse` → yozma ruxsat bilan `--commit` → verify. Production apply uchun ikkita bayroq
  (`--allow-production` + `--confirm-production-system-identifier`) va muhitning o'z e'loni shart;
  bu bosqichda production'da faqat `preflight` bajariladi. Jadvallar 0 qatorli, ya'ni yozish oynasi
  bir zumlik; qulf band bo'lsa vosita `exit 2` bilan chiqadi va HECH NARSA o'zgarmaydi (bitta
  tranzaksiya — qisman holat yo'q).

---

## 6. Ko'p filial cheklovi — KO'P FILIALLI AKTIVATSIYA UCHUN BLOKER

Fayzan'da 1 filial bor, shuning uchun quyidagi standart qiymatlarning hammasi to'g'ri filialga tushadi va bu uning uchun bloker EMAS. **2+ filialli har qanday tenant esa quyidagilar qurilmaguncha aktivatsiya qilinMAYDI:**

1. **Inventarizatsiya va Hisobdan chiqarish ekranlarida filial konteksti yo'q.**
   - Ekranlar (`packages/shared/src/screens/Inventarizatsiya.tsx`, `Hisobdan.tsx`) partiyalarni BARCHA ko'rinadigan filiallar bo'yicha ro'yxatlaydi, yozuv esa `actor_branch` ga ketadi.
   - Server ko'pincha fail-closed: boshqa filial partiyasi yoki yig'indi farqi 400 beradi.
   - Lekin faqat `new_lots` bilan sanoq noto'g'ri filialga yozilishi mumkin.
   - **Kerak:** majburiy filial tanlash; `/lots/batches`, sanoq va hisobdan chiqarishga bitta `branch_id`.
2. **`ProductPicker`** (`packages/shared/src/components/lotui.tsx`) `/products?tracked=true` ni `branch_id` siz so'raydi, shuning uchun ko'rsatilgan qoldiq filiallar yig'indisi. **Kerak:** `branch_id` uzatish.
3. **`/lots/enable`.** Invariant mahsulotning BARCHA filiallarini qamraydi, shuning uchun 2+ filialda qoldig'i bor mahsulot 409 oladi. **Kerak:** filiallar bo'yicha ochilish partiyalari (bitta tranzaksiyada) yoki aniq xabar.
4. **Yangi filial standart zonasi `Asia/Tashkent`.** Tasdiq ko'rib chiqilmasdan berilishi mumkin. **Kerak:** filial zonasini aniq ko'rib chiqish.
5. **Partiyali filiallararo ko'chirish** hozir 409. **Kerak:** partiyali ko'chirish.
6. **Kirim filiali** har doim `actor_branch`. **Kerak:** kirimda filial tanlash. Manager kirim ekranidagi «filial ish kuni» maslahati esa `GET /lots/products/{id}` dan olinadi — u ENG ESKI filialni qaytaradi, ya'ni ko'p filialli do'konda maslahat boshqa filialnikini ko'rsatishi mumkin (server baribir hakam: muddat `actor_branch` biznes sanasi bo'yicha tekshiriladi).
8. **Mobil kirim partiyani bilmaydi** (`apps/mobile/lib/api.dart`): `lots` yuborilmaydi va `ProductLite` da `track_lots` yo'q, shuning uchun ilova kuzatuvli mahsulotni oldindan ajrata olmaydi. Butun hujjat 400 oladi. **Kerak:** mobil paritet yoki mobilda kuzatuvli mahsulotni ANIQ bloklash.
7. **Qurilma/terminal juftlash** (device pairing) — login filial kontekstini ishonchli olib kelmaydi.

Har biri uchun PG18 testlari (negativ nazorat bilan) talab qilinadi. Do'kon × filial darvozasi 2+ filialli do'konni, barcha filiallari ro'yxatda bo'lmaguncha, baribir yopiq ushlaydi.
