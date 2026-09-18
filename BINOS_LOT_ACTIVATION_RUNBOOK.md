# BinOS — Fayzan partiya (lot) kuzatuvi aktivatsiyasi — operator runbook

> **Doira:** production'da **bitta do'kon (`fayzan1`), bitta filial**, tanlangan mahsulotlar uchun
> partiya/muddat kuzatuvini yoqish. Hujjat Phase 5B.1 kodiga (`phase5b/lot-prehardening`) tayanadi.
>
> **Asosiy qoida:** kuzatuvni yoqish **QAYTARIB BO'LMAYDI**. Mahsulotda `track_lots` o'chiradigan kod
> yo'q, `track_expiry` tanlovi yoqilgan paytda muzlaydi. Har bir yozadigan qadam **alohida yozma
> ruxsat** bilan bajariladi. Hujjatdagi buyruqlar faqat tavsif: ularni o'qish ruxsat EMAS.
>
> **Oldingi hujjat:** kodni chiqarish, `uuid` ustun tipi migratsiyasi, backup/restore va deploy
> rollback'i — **`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md`**. Shu hujjatning 1–3 qadamlari o'sha yerga
> ishora qiladi va tafsilotni TAKRORLAMAYDI. Deploy tugagani aktivatsiyaga ruxsat degani EMAS.

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
| B2 | ~~**Kirim UI partiya yubormaydi**~~ — Manager tomoni YOPILDI (Phase 5C) | Manager «Yangi kirim» (Xaridlar) va «Rasm orqali kirim» endi kuzatuvli qatorda partiya muharririni ochadi va `lots` yuboradi; kirim tafsilotida kuzatuvli qator qulflangan (server tannarx tahririni ham 409 bilan rad etadi). Kuzatuvsiz kirim payloadi O'ZGARMADI. **QOLGAN CHEKLOVLAR:** (a) **mobil ilova** (`apps/mobile`) hamon `lots` yubormaydi — kuzatuvli mahsulotli har qanday mobil kirim/hisobdan chiqarish/sanoq butun hujjat bilan 400 oladi va xato xom lotin matnida ko'rinadi; (b) `POST /purchases` (menejer xaridi) va filiallararo ko'chirish 409; (c) kirim filiali har doim `actor_branch` (§6). Barcha kanallar va ularning AYNIQ javoblari — §2.13.1. | Manager'dan kirim OCHIQ. **Pilot mahsulotlar MOBIL ilovadan kirim/hisobdan chiqarish/sanoq qilinmaydi**, xarid (`/purchases`) va ko'chirishdan ham o'tmaydi |
| B9 | ~~**Xato qabulni tuzatib/bekor qilib bo'lmaydi**~~ — YOPILDI (Phase 5D) | Ilgari kuzatuvli hujjatda xato topilsa yagona maslahat «qo'llab-quvvatlashga murojaat qiling» edi: `PATCH /purchases/{id}` `stock_gate` bilan 409 berardi va boshqa yo'l yo'q edi. Endi `POST /receiving/{id}/corrections` bor — o'zgarmas teskari yozuv + o'rniga qo'yish, to'liq teskari qilinsa hujjat bekor bo'ladi (§2.13.2). Tuzatilgan hujjatda eski tahrir yo'li `LOT_CORRECTION_DOC_LOCKED` bilan yopiladi. | **YOPILDI** — operator ko'rsatmasi va rad etishlar §2.13.2–2.13.3 |
| B3 | **Aktivatsiyadan oldingi chekni qaytarish** | Kuzatuv yoqilgunga qadar sotilgan qatorda orqaga o'raydigan taqsimot YO'Q. Siyosat (Phase 5C): `restock=false` — RUXSAT (partiya, qarz va taqsimot TEGILMAYDI; tannarx asl chekdan); `restock=true` — 409 `LOT_RETURN_PRE_ACTIVATION`. Tasnif TUZILISH bo'yicha (`sold_at` bo'yicha EMAS). | **YOPILDI** — §2.12; operator ko'rsatmasi shu yerda |
| B4 | **Yoqish UI yo'q** | `/lots/enable` va `/lots/timezone/confirm` faqat API (ega tokeni) orqali. | Operator qadami |
| B5 | **Kuzatuvli mahsulotda birlik/tarozi o'zgarishi himoyasiz** | `PATCH /products` kuzatuvli mahsulotda `unit_code`/`is_weighted` ni o'zgartirishga yo'l qo'yadi. | Pilot davomida bu maydonlar o'zgartirilmaydi |
| B6 | **Ko'p filial** | §6 ga qarang. Fayzan (1 filial) uchun bloker EMAS, lekin ko'p filialli har qanday tenant uchun bloker. | — |
| B7 | **Ommaviy yoqish yo'q** | Har mahsulot bitta `POST /lots/enable` chaqiruvi (schema introspection + qatorlarni qulflash). 7137 mahsulotni savdo vaqtida yoqish mumkin emas. | Faqat kichik pilot to'plami |
| B8 | **UUID ustun tipi migratsiyasi qo'llanmagan** | Deploy tipni O'ZI tuzatmaydi. Tuzatilmaguncha `/health/ready` 503 (`column_types=false`) — 3-qadam STOP; naqd kirim/chiqim va QR dedup 42883 beradi (bu nuqson **bugun ham tirik** — `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §1.1, A katak). | To'liq tartib, o'lchangan raqamlar va STOP'lar: **`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §D2, §D5–D6**. Aktivatsiya uchun shart: `verify: VERIFIED` va `column_types=true` |

### 0.1 Aktivatsiya tayyorligi: server vs jarayon

Qaytarib bo'lmaydigan amalning bir qismini **server o'zi** to'sadi, qolgani — **faqat shu runbook**
javobgarligida. Ikkalasini aralashtirmang: server yashil bo'lishi «yoqsa bo'ladi» degani EMAS.

**SERVER TEKSHIRADI (baza; `/lots/enable` 409 beradi, hech narsa yozmaydi):**

| Tekshiruv | Qayerda | Kod |
|---|---|---|
| Sxema yaxlitligi (majburiy ustun/indeks, halokatli CHECK, FK va CHECK holati) | `required_schema.missing` | `LOT_SCHEMA_NOT_READY` |
| Idempotentlik noyob indekslari (offline dedup, pul/ombor/auth takrori) | `required_schema.idempotency_missing` | `LOT_SCHEMA_NOT_READY` |
| `uuid` bo'lishi shart ustunlar haqiqatan `uuid` (Postgres) | `required_schema.column_type_problems` | `LOT_SCHEMA_NOT_READY` |
| Do'kon × filial darvozasi (hammasidan OLDIN) | `lot_policy.assert_activation_allowed` | 403 |
| `track_expiry=true` da filial zonasi tasdig'i | `lot_policy.assert_tz_confirmed` | 409 |

Bular `GET /lots/availability` da ham ko'rinadi: `activation_ready` va `readiness`
(`schema_integrity`/`idempotency`/`column_types`) — faqat ha/yo'q, nomlarsiz; `can_enable`
ayni shularga tayanadi. Yakuniy qaror esa har doim `/lots/enable` (keshsiz).

**FAQAT RUNBOOK/OPERATOR TEKSHIRADI (server BILA OLMAYDI):**

| Tekshiruv | Nega server tekshira olmaydi | Qayerda |
|---|---|---|
| 1C cutover tugagani (B1) | `catalog_import_v2.is_live` bor, lekin «bu tenant 1C'ga o'tishi shart» — BIZNES fakti; 1C'siz do'kon aks holda umuman yoqa olmasdi | §0 B1 |
| Fayzan mashinalaridagi Manager/POS yig'malarida partiyali kirim UI (B2) | `/fleet` dagi `app_version` qurilmaning O'ZI aytadi — ishonchli emas | §0 B2 |
| Backup + restore mashqi yangiligi | GitHub Actions, ilovadan tashqarida | `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §D1, §D8 |
| `config`, `tenancy_schema`, `cash_schema`, `database` yashilligi | Umumiy xizmat tayyorligi; aktivatsiya darvozasiga ATAYLAB kiritilmagan (dev/e2e ni to'sib qo'yardi) | §2.3 |
| Aktivatsiyadan oldingi qaytarish siyosati (B3), birlik/tarozi muzlatilishi (B5), pilot hajmi (B7) | Jarayon qarori | §0 |
| Sokin savdo oynasi (smena yopiq, offline navbat bo'sh) | Server so'rov paytidagi savdo faolligini shart qilmaydi | §2.8 |
| Fingerprint digest (aktivatsiyadan oldingi/keyingi farq) | Read-only tashqi sessiya | §2.4 |

---

## 1. Bosqichlar

| # | Qadam | Buyruq / tekshiruv | Yozadimi | STOP sharti |
|---|---|---|---|---|
| 1 | Production hardening deploy (exact SHA) | §2.1 → **DEPLOY §D0, §D3** | HA (kod + boot DDL; ustun TIPI emas) | health commit ≠ SHA; boot jurnalida `[FATAL]`; boot jurnalida `-> uuid` (boot tipni o'zgartirmasligi SHART) |
| 1a | UUID ustun tipi migratsiyasi (aniq qadam) | §2.1a → **DEPLOY §D2, §D5–D6** | preflight — yo'q; apply — HA (alohida yozma ruxsat) | preflight `BLOCKED`; `REJECTED_STATE_CHANGED`; verify FAIL |
| 2 | Backup + restore mashqi | §2.2 → **DEPLOY §D1, §D8, §5** | yo'q (production'ga) | artefakt bo'sh; restore mashqi qizil |
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

> **DEPLOY §…** — `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` dagi bo'lim. 1, 1a va 2-qadamlar
> **to'liq o'sha hujjatda**; bu yerdagi §2.1 faqat aktivatsiya uchun muhim natijani qoldiradi.

---

## 2. Qadamlar tafsiloti

### 2.1 Production hardening deploy  ·  §2.1a UUID migratsiyasi  ·  §2.2 Backup/restore

> **Bu uch qadam TO'LIQ `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` da** — o'sha yerda buyruqlar,
> kutilgan chiqish satrlari, o'lchangan raqamlar (kod × sxema matritsasi, qulf kutishi 219 ms,
> DDL 15.8 s, boot 7.43 s, restore mashqi run 35365182486) va rollback matritsasi bor.
> Bu yerda faqat **aktivatsiya uchun** muhim natija qoladi. Tafsilotni ikki joyda saqlamang.

| Qadam | Deploy runbook'dagi joyi | Aktivatsiya uchun TALAB |
|---|---|---|
| 1 · deploy (aniq SHA) | §D0 (sokin oyna, qulf tekshiruvi), §D3 | `/api/v1/health` → `build.commit == SHA`, `environment=production`; boot jurnalida `[boot] partiya faollashtirish: rejim=closed, ro'yxat yozuvlari=0` (7-qadamgacha `SAVDOOS_LOT_ACTIVATION_SCOPES` berilMAGAN bo'lishi SHART) |
| 1a · `uuid` migratsiyasi | §D2 (preflight), §D5 (`--rehearse` → `--commit`), §D6 (`verify`) | `verify: VERIFIED` va `/health/ready` da `column_types=true`. Shusiz `/lots/enable` baribir 409 `LOT_SCHEMA_NOT_READY` beradi |
| 2 · backup + restore mashqi | §D1 (deploydan oldin), §D8 (deploydan keyin), §5 (RPO/RTO) | Ikkala backup runi yashil, `capture_quiescent=true`, mashqda `RESTORE_REHEARSAL_OK` |

**Aktivatsiya kontekstida eslab qolinadigan uchta fakt:**

- **Deploy ustun TIPINI tuzatmaydi.** Tuzatilmagan bazada boot jurnalida uchta
  `[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: <jadval>.<ustun>` satri va
  `[schema] ustun tipi og'ishi — tuzatish (boot EMAS, operator): …` maslahati KUTILADI — bu
  **YIQILISH EMAS**, lekin `/health/ready` 503 bo'ladi, ya'ni 3-qadam STOP.
- **`[FATAL]` va `[migrate] … -> uuid` satrlari CHIQMASLIGI SHART.** Birinchisi — qulf band
  bo'lgani (deploy runbook §1.4; Railway `ON_FAILURE`, servis instansiyasi `maxRetries=10`);
  ikkinchisi — boot DDL yuborgani, bu Phase 5C dan keyin bo'lishi mumkin emas.
- **Backup aktivatsiyani «qaytarmaydi».** Restore backup'dan keyingi BARCHA savdoni yo'qotadi
  (§3.3) va kuzatuv bayrog'ini o'chirmaydi.


### 2.3 health / ready

```bash
curl -s https://savdoos-production.up.railway.app/api/v1/health/ready
```
- **KUTILADI:** HTTP 200, `status=ready` va barcha check'lar `true`:
  - `database`, `cash_schema`, `config`, `tenancy_schema`, `catalog_v2_schema`, `lot_schema_integrity`;
  - `idempotency_schema` — offline dedup va pul/ombor noyobligi indekslari mavjud, yaroqli va noyob;
  - `column_types` — **ANIQ migratsiya qo'llanganidan keyin** `true`
    (`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §D5–D6; deploy uni o'zi tuzatmaydi, tuzatilmaguncha bu
    kalit `false` va butun javob 503).
- **STOP:** biror check `false`. **Server ham to'sadi:** `/lots/enable` sxema yaxlitligi, idempotentlik indekslari yoki uuid ustun tipi tayyor bo'lmasa 409 (`X-Error-Code: LOT_SCHEMA_NOT_READY`) qaytaradi va **hech narsa yozmaydi** — tekshiruv keshsiz, har so'rovda. Shunga qaramay readiness'siz davom etilMAYDI: `database`, `cash_schema`, `config`, `tenancy_schema` ni server aktivatsiya darvozasida tekshirmaydi.

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
2. Do'kon × filial darvozasi — bazadan OLDIN (ro'yxatda yo'q do'kon sxema holatini umuman bilmaydi: 403).
3. Sxema yaxlitligi (`missing()`): 409, matnda muammolar SONI.
4. Baza tayyorligi: idempotentlik indekslari + uuid ustun tiplari — 409 `LOT_SCHEMA_NOT_READY`,
   nomsiz matn (nomlar faqat Railway jurnalida). Keshsiz; qulf va qator yaratishdan OLDIN.
5. Mahsulot va filial.
6. Muddat bo'lsa, tz tasdig'i.
7. Mahsulotning HAR filialdagi qoldiq qatori qulflanadi (yo'g'i 0 bilan yaratiladi).
8. Mahsulot qayta o'qiladi. Parallel yoqish bo'lsa, ikkinchisi 409 oladi va audit bitta qoladi.
9. Ochilish partiyalari yoziladi.
10. Bayroqlar yoqiladi.
11. Yakuniy invariant tekshiruvi.
12. Audit (`product_lot_tracking`).

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

**Miqdor qoidalari (Phase 5C review):** ochilish partiyasi miqdorida uchtadan ORTIQ kasr
xona bo'lsa so'rov ANIQ 400 bilan rad etiladi (kirim bilan AYNI qoida) — ilgari u
darvozadan o'tib, QAYTARIB BO'LMAYDIGAN yoqishni yakuniy invariantda opaque 409 bilan
yiqitardi. Bir so'rovdagi ochilish partiyalari soni ko'pi bilan **50** ta.

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

### 2.13 Kuzatuvli qabul FAQAT Manager lot-aware oqimi orqali (Phase 5D)

**QOIDA (pilot davomida, istisnosiz):** kuzatuvli mahsulotning omboriga tovar FAQAT Manager'ning
partiyani biladigan kirimi bilan kiradi — `POST /api/v1/receiving/commit`, har qatorda `lots`.
Kiritilgan hujjatni keyin o'zgartirish ham FAQAT tuzatish oqimi bilan bo'ladi —
`POST /api/v1/receiving/{receiving_id}/corrections`.

Qolgan HAR BIR kanal kuzatuvli mahsulotda **to'xtaydi va hech narsa yozmaydi**. Jimgina zaxira
yo'l, avto-«kuzatuvni o'chirish» yoki sun'iy partiya **yo'q** — bu ataylab: qoldiqni partiyalardan
ayirmasdan siljitish `Inventory.qty == Σ remaining_qty` invariantini jimgina buzardi va buzilish
kunlar keyin, hisobotda ko'rinardi.

#### 2.13.1 Eski kanallar — operator nima ko'radi va nima qiladi

| Kanal | Javob | Operator ko'radigan matn (boshi) | Nima qilish kerak |
|---|---|---|---|
| Menejer xaridi `POST /purchases` | **409** | «`xarid (partiyasiz kirim)` yo'li partiya kuzatuvini qo'llab-quvvatlamaydi…» | Xaridni Manager **«Yangi kirim»** (partiya muharriri bilan) orqali kiriting |
| Kirim tahriri `PATCH /purchases/{id}` (miqdor/qator o'chirish) | **409** | «`xarid tahriri` yo'li partiya kuzatuvini qo'llab-quvvatlamaydi…» | Tahrir emas — **tuzatish** yarating (§2.13.2) |
| Kirim tahriri — faqat TANNARX | **409** | «…kirim narxini tahrirlab bo'lmaydi: partiya tannarxi qabul paytida yozilgan…» | Tannarx faqat tuzatishda, **o'rniga qo'yish** (`replace`) bilan o'zgaradi |
| Mobil kirim (`apps/mobile`, `lots` yubormaydi) | **400** | «'{mahsulot}' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY…» | **Pilot mahsulotlar mobil ilovadan qabul qilinmaydi** (B2). Manager'dan kiriting |
| Filiallararo ko'chirish `POST /inventory/transfer` | **409** | «`filiallararo ko'chirish` yo'li partiya kuzatuvini qo'llab-quvvatlamaydi…» | Pilotda ko'chirish yo'q (Fayzan — 1 filial) |
| Inventarizatsiya `POST /inventory/count` umumiy son bilan | **400** | «Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga TAQSIMLAMAYDI.» | Har partiyani ALOHIDA sanang (`lots`); javondan topilgan notanish qadoq — `new_lots` |
| Hisobdan chiqarish `POST /inventory/writeoff` partiyasiz | **400** | «Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating…» | Qaysi partiya tashlanayotganini ANIQ ko'rsating |
| 1C cutover qoldiq moslashtiruvi (`/catalog/v2/commit`) | **400** | «`1C cutover qoldiq moslashtiruvi` yo'li partiya kuzatuvini qo'llab-quvvatlamaydi…» | **B1:** 1C cutover aktivatsiyadan OLDIN tugashi shart |
| 1C migratori (CLI `migrate_1c.py`) | **apply BOSHLANMAYDI** | reja bosqichida: «partiya kuzatuvi yoqilgan mahsulotlar bor — Migrator V1 ularga tegmaydi» | **B1** bilan bir xil: migratsiya avval, aktivatsiya keyin |

> **Migratorda uch qavat darvoza bor.** (1) Reja qurishda (`mapping.build_plan`) — operator AYNAN
> shuni ko'radi, apply umuman boshlanmaydi. (2) Ko'rib chiqishdan KEYIN kuzatuv yoqilsa, apply
> katalogni qayta tasniflaydi va hisobot xeshi mos kelmagani uchun `DriftError` bilan to'xtaydi.
> (3) Tranzaksiya ichida `stock_gate.assert_untracked` — oxirgi chiziq, odatda yetib borilmaydi.
> Uchalasi ham hech narsa yozmasdan to'xtaydi.

Bu jadval `apps/server/tests/test_legacy_receiving_gate.py` da **bajarilgan test** bilan
qadalgan: har kanal kuzatuvli mahsulotda AYNAN shu javobni beradi, kuzatuvsizda esa bugungidek
ISHLAYDI (manfiy nazorat). O'sha fayldagi qorovul `Inventory.qty` ni yozadigan yangi modul
jadvalga ham, «partiyani biladi» ro'yxatiga ham kirmasa — to'plamni QIZIL qiladi.

#### 2.13.2 Tuzatish oqimi (`POST /receiving/{receiving_id}/corrections`)

**Nima qiladi.** Xato qabul qilingan hujjatni **o'zgarmas teskari yozuv + o'rniga qo'yish** bilan
tuzatadi, hammasi bitta tranzaksiyada:

- **teskari qilish** (`reverse`) — ko'rsatilgan kogortadan ANIQ miqdorni ayiradi; to'liq teskari
  qilingan va **tegilmagan** kogorta `void` bo'ladi, tegilgani `depleted` bo'lib qoladi;
- **o'rniga qo'yish** (`replace`) — to'g'ri partiya raqami, muddati va tannarxi bilan YANGI kogorta
  yaratadi (`source_type='correction'`, o'sha qabul hujjatiga bog'lanadi);
- qoldiq, yetkazib beruvchi qarzi (yoki naqd hujjatda kassa) va hujjat jami shu farqqa siljiydi;
- hammasi teskari qilinib jami **0** bo'lsa — hujjat `cancelled` bo'ladi va yopiladi.

**Nima QILMAYDI (va bu ataylab).** Mavjud partiyaning `received_qty`, `unit_cost`, raqami yoki
muddati **hech qachon qayta yozilmaydi**; `purchase_items` qatorlari va `Receiving.final_items`
surati **bayt-baytiga o'zgarmaydi**; kassa va yetkazib beruvchi daftariga faqat YANGI, qarama-qarshi
yozuv qo'shiladi. Sotilgan tovarning tarixiy tannarxi shu bois yolg'on bo'lib qolmaydi.

**Kirish nuqtasi.** Manager → **Xaridlar** → kirim tafsiloti. `GET /purchases/{id}` javobida
`correctable`, `correction_blocked_reason`, hujjatning oldingi `corrections` ro'yxati va har qator
uchun `lots` (qabul qilingan / qolgan / harakatlangan miqdor + `correctable`) bor — ya'ni operator
tugmani bosishdan OLDIN nima mumkinligini ko'radi. Ruxsat: **`xaridlar.edit`**.

**MAJBURIY maydonlar:** `client_uuid` (takror so'rovda ikki marta qo'llanmasligi uchun) va `reason`
(3–300 belgi, auditga tushadi).

#### 2.13.3 Tuzatishdagi rad etishlar — operator qo'llanmasi

`X-Error-Code` sarlavhasida barqaror kod keladi (matnda EMAS); Manager shu kod bo'yicha tarjima
ko'rsatadi.

| Kod / javob | Nega | Operator nima qiladi |
|---|---|---|
| **409** `LOT_CORRECTION_NOT_TRACKED` | bu qabul umuman partiya yaratmagan | Hujjatni oddiy kirim tahriri bilan o'zgartiring — tuzatish oqimi faqat partiyali qabul uchun |
| **409** `LOT_CORRECTION_EXCEEDS_REMAINING` | partiyada shuncha qolmagan | Qolgan miqdorni `GET /purchases/{id}` → `lots[].remaining_qty` dan oling; jismoniy partiya manfiyga tushmaydi |
| **409** `LOT_CORRECTION_CONSUMED` | kogortadan tovar allaqachon harakatlangan (sotilgan/chiqarilgan/sanalgan) | Tegilgan kogortada faqat **MIQDORNI** teskari qilish mumkin. Raqam/muddat/tannarxni tuzatish uchun kogorta tegilmagan bo'lishi shart. ⚠️ **Miqdorni teskari qilishning O'ZI ham kogortani «tegilgan» qiladi** — identifikatsiyani tuzatish shu kogortaga BIRINCHI teginish bo'lishi kerak |
| **409** `LOT_CORRECTION_SHORTFALL_OPEN` | mahsulotda yopilmagan partiya qarzi bor | Avval qarzni partiyaga bog'lang (`/lots/shortfalls`), keyin tuzating. Qarz ochiq ekan qaysi kogorta ketgani NOMA'LUM |
| **409** `LOT_CORRECTION_CASH_UNPOSTABLE` | naqd hujjat summasi o'zgardi, lekin kassa yozuvini yozib bo'lmadi | Tuzatish BEKOR qilindi (kassa tegilmagan). Qo'llab-quvvatlashga murojaat qiling — «bajarildi» deb aytilmaydi |
| **409** `LOT_CORRECTION_REPLAY_CONFLICT` | ayni `client_uuid` BOSHQA so'rov bilan ishlatilgan | Yangi so'rov uchun YANGI `client_uuid` bering (bu takror emas — boshqa so'rov) |
| **409** `LOT_CORRECTION_DOC_LOCKED` | hujjat allaqachon tuzatilgan, `PATCH /purchases/{id}` urinildi | Eski tahrir yo'li tuzatishni jimgina teskari qilardi — **yangi tuzatish** yarating |
| **409** `LOT_INVARIANT_BROKEN` | yozuvdan oldingi yakuniy tekshiruv mos kelmadi | Amal BAJARILMADI. Qo'llab-quvvatlashga murojaat qiling (§2.11 STOP sharti) |
| **404** «Qabul topilmadi» / «Kirim topilmadi» | qabul yoki unga bog'langan xarid yo'q, o'chirilgan yoki boshqa filialniki | Hujjatni Manager ro'yxatidan qayta oching; bekor qilingan hujjat qayta tuzatilmaydi |
| **400** partiya/qator shakli xatolari | qator ikki marta ko'rsatilgan, partiya bu qabulga tegishli emas, `replace` bor-u qator tannarxi yo'q va h.k. | Matn nimani to'g'rilash kerakligini AYNAN aytadi; tannarx **taxmin qilinmaydi** |
| **403** «Ruxsat yo'q: xaridlar.edit» | rol yetmaydi | Tuzatishni `xaridlar.edit` bo'lgan rol bajaradi: `ega`, `administrator` yoki `omborchi`. **`menejer` da bu ruxsat YO'Q** (`seed.py`) — u bilan qayta urinish ayni 403 ni beradi |

**Takror so'rov (idempotentlik).** Ayni `client_uuid` bilan AYNI tanani qayta yuborish yangi
tuzatish YARATMAYDI: birinchi javob `"duplicate": true` bilan qaytadi. Tarmoq uzilganda so'rovni
xotirjam takrorlang — qoldiq, qarz va kassa ikki marta siljimaydi.

**Tuzatishdan keyin tekshiring:** `GET /api/v1/lots/products/{id}` da
`inventory_qty == Σ lot.remaining_qty − unresolved_shortfall_qty` va hujjat jami kutilgan qiymatga
teng. Mos kelmasa — §3 rollback sharti.

### 2.10 Smoke (yoqilgan har mahsulot)

- `GET /api/v1/lots/products/{id}`: `inventory_qty == Σ lot.remaining_qty − unresolved_shortfall_qty`.
- `GET /api/v1/lots/batches?product_id={id}`: ochilish partiyalari to'g'ri (`source_type` `opening` yoki `legacy`).
- `GET /api/v1/audit?entity=product_lot_tracking`: sabab (`reason`) yozilgan.
- `GET /api/v1/lots/products/{id}`: `business_date` — XODIM YOZADIGAN filialning sanasi
  (`deps.actor_branch`); ko'p filialli do'konda Kirim UI muddat maslahati shu sanadan oladi.
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
- **Kod rollback'i (AKTIVATSIYADAN KEYIN):** faqat shu hardening liniyasidagi oldingi deploy'ga. `99b1da7` ga qaytish taqiqlanadi, chunki unda:
  - `/lots/timezone/confirm` darvozasiz;
  - 409 javoblari ichki matnni sizdiradi;
  - partiya maydonlarini yashirish va sotuv hujjati ruxsat darajasi yo'q;
  - do'kon × filial darvozasi yo'q.
  `89f647a` dan pastga esa partiya ma'lumoti bor bazada UMUMAN qaytilmaydi.
  ⚠️ **Aktivatsiyadan OLDIN bu taqiq amal qilmaydi:** darvoza yopiq va `track_lots=0` ekan,
  `99b1da7` shunchaki OLDINGI deploy bo'lib qoladi va unga qaytish deploy oynasida XAVFSIZ
  (o'lchangan: `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §1.1 C katak, rollback matritsasi §4.2
  P2–P5). Taqiq **P6 dan** — ya'ni birinchi kuzatuvli qabul yoki tuzatish yozilgandan — boshlanadi.
- **DB restore:** backup'dan keyingi BARCHA savdo, qaytarish va to'lovni yo'qotadi. Faqat halokat holati uchun (`PRODUCTION_OPERATIONS_RUNBOOK.md` §4, §11; RPO/RTO va artefakt tarkibi — `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §5).
- **O'zgarmas biznes hodisasi HECH QACHON `DELETE`/`UPDATE` bilan qaytarilmaydi** — kassa ledgeri, yetkazib beruvchi daftari, ombor harakati, partiya identiteti. Tuzatish faqat YANGI, qarama-qarshi hodisa bilan (§2.13.2; qoidaning to'liq bayoni — `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §4.3).
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
  Mahsulot va kuzatuv holatini o'qimaydi. **Sxema/tayyorlik tekshiruvi YO'Q va qo'shilmadi**
  (ataylab): tasdiq partiya tarixini tug'dirmaydi — `settings.catalog` dagi bitta kalit va bitta
  audit qatori, idempotent. Yoqish esa tayyorlikni qaytadan, keshsiz tekshiradi.
- `POST /lots/enable`:
  - ruxsat `ombor.edit`;
  - AYNI darvoza;
  - sxema yaxlitligi (`missing()`);
  - **baza tayyorligi: idempotentlik indekslari + uuid ustun tiplari** (Phase 5C; keshsiz,
    409 `LOT_SCHEMA_NOT_READY`). `/health/ready` dagi `idempotency_schema` va `column_types`
    kalitlari bilan AYNI manba;
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
- `tests/test_lot_enable_race.py` va `tests/test_lot_enable_race_pg.py`: yoqish va har bir ombor yozuvchisi poygasi; eski kodda qoldiq partiyalardan ajralgan, yangisida invariant butun;
- `tests/test_lot_activation_readiness.py` va `tests/test_runtime_columns.py`: idempotentlik indeksi yoki ustun tipi tayyor bo'lmasa yoqish 409 (`LOT_SCHEMA_NOT_READY`) va hech narsa yozilmaydi; darvoza tartibi (ro'yxatda yo'q do'kon 403 oladi, 409 EMAS); tasdiq esa tayyorlikka bog'lanMAGAN;
- `tests/test_legacy_receiving_gate.py` (Phase 5D, §2.13.1): `Inventory.qty` ni yozadigan HAR eski kanal — menejer xaridi va uning tahriri, mobil shakldagi (`lots` kalitisiz) kirim, filiallararo ko'chirish, inventarizatsiya, hisobdan chiqarish, 1C cutover va 1C migratori — kuzatuvli mahsulotda AYNAN qaysi maqom/matn/kod bilan to'xtashi; har biri uchun manfiy nazorat (kuzatuvsizda bugungidek ishlaydi va qoldiq kutilgandek siljiydi); rad etilgan yo'l na qoldiq, na partiya, na hujjat qoldiradi; va qamrov qorovuli — jadvalga ham, «partiyani biladi» ro'yxatiga ham kirmagan YANGI qoldiq yozuvchisi to'plamni QIZIL qiladi.

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
  qisqa ACCESS EXCLUSIVE endi ALOHIDA operator qadamida olinadi
  (`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §D5): preflight → ko'rib chiqish → `--rehearse` → yozma
  ruxsat bilan `--commit` → verify. Production apply uchun ikkita bayroq
  (`--allow-production` + `--confirm-production-system-identifier`) va muhitning o'z e'loni shart
  — `--rehearse` uchun ham. Bu qadam **deploy oynasida, aktivatsiyadan OLDIN** bajariladi va
  aktivatsiya uchun ochiq qoldirilmaydi. Jadvallar 0 qatorli, ya'ni yozish oynasi
  bir zumlik; qulf band bo'lsa vosita `exit 2` bilan chiqadi va HECH NARSA o'zgarmaydi (bitta
  tranzaksiya — qisman holat yo'q).
- **Identifikatsiyani tuzatish kogortaga BIRINCHI teginish bo'lishi shart (Phase 5D).** Miqdorni
  teskari qilish kogortaga taqsimot qatori yozadi va uni «tegilgan» qiladi; shundan keyin o'sha
  kogortaning raqami, muddati va tannarxini tuzatib bo'lmaydi (`LOT_CORRECTION_CONSUMED`).
  Ya'ni «avval 10 tasini teskari qilay, keyin qolganini to'g'ri partiya bilan almashtiray» ISHLAMAYDI —
  ikkalasini BITTA tuzatishda yuboring. Operator ko'rsatmasi §2.13.3 da.
- **Kirim narxi tahriridagi maslahat eskirgan.** `PATCH /purchases/{id}` da FAQAT tannarx
  o'zgartirilsa, 409 matni hamon «Kuzatuvli hujjat hozircha bekor ham qilinmaydi — tuzatish uchun
  qo'llab-quvvatlashga murojaat qiling» deydi, holbuki Phase 5D tuzatish oqimini ochdi. Xulq TO'G'RI
  (tahrir baribir rad etiladi), maslahat esa endi noto'g'ri manzilni ko'rsatadi. Operator §2.13.2 ga
  ko'ra tuzatish yaratadi. Matn va uning lug'at kaliti (`serverErrorsLots.ts`) keyingi bosqichda
  yangilanadi.

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
