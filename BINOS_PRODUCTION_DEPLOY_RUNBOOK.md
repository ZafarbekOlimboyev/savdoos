# BinOS — production deploy runbook (Phase 5D/5E/5F kodi + `uuid` migratsiyasi)

> **Doira:** production'da ishlab turgan `99b1da7` ustiga YANGI kodni chiqarish (qabulni tuzatish
> oqimi + kassa custody bloki) va `uuid` ustun tipi migratsiyasini qo'llash.
> **Bu hujjat aktivatsiya EMAS.** Partiya kuzatuvini YOQISH — alohida, qaytarib bo'lmaydigan amal:
> `BINOS_LOT_ACTIVATION_RUNBOOK.md`. Deploy tugagani aktivatsiyaga ruxsat degani EMAS.
>
> **Asosiy qoida:** hujjatdagi buyruqlar faqat TAVSIF — ularni o'qish bajarish ruxsati EMAS.
> Yozadigan har qadam (deploy, `apply --commit`, Railway o'zgaruvchisi) **alohida yozma ruxsat**
> bilan bajariladi.
>
> **Ikkinchi qoida:** o'zgarmas biznes hodisasi — kassa ledgeri (`CashLedgerEntry`), yetkazib
> beruvchi daftari (`SupplierLedger`), ombor harakati (`StockMovement`), partiya identiteti —
> HECH QACHON `DELETE`/`UPDATE` bilan «qaytarilmaydi». Tuzatish har doim YANGI, qarama-qarshi
> hodisa bilan qilinadi (§4.3).

| Nima | Qiymat |
|---|---|
| Servis | Railway `savdoos` (loyiha `trustworthy-enchantment`, baza `Postgres-d29B`) |
| Bazaviy URL | `https://savdoos-production.up.railway.app/api/v1` |
| Production Postgres `system_identifier` | `7674898282858840119` |
| Bugungi production SHA | `99b1da7` (Phase 4B dormant, deploy `b74e20c4`, 2026-09-16) |
| Chiqariladigan SHA | `<40-belgili SHA>` — CI 6/6 yashil, PG18 bajarilish isboti, staging'da AYNI SHA smoke PASS |
| Migratsiya ID | `2026-09-17.uuid-client-columns-v1` |
| `fayzan1` kompaniya | `8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5` |
| Yagona filial (Asia/Bishkek) | `c311874f-4787-405a-94f2-af9347f999aa` |
| `gh` yo'li (Windows) | `C:\Program Files\GitHub CLI\gh.exe` |
| Railway CLI (Windows) | `railway.cmd` |

---

## 0. Hujjatlar taqsimoti — bu yerda NIMA bor, nima YO'Q

| Savol | Qaysi hujjat |
|---|---|
| Kodni qanday chiqaraman, `uuid` migratsiyasini qanday qo'llayman, nima qaytariladi | **Shu hujjat** |
| Partiya kuzatuvini qanday yoqaman, qaysi blokerlar ochiq, mahsulot bo'yicha smoke | `BINOS_LOT_ACTIVATION_RUNBOOK.md` |
| Backup/restore ni qanday YOQILGAN, sirlar, falokat stsenariylari, monitoring, tenant purge | `PRODUCTION_OPERATIONS_RUNBOOK.md` |
| Qabulni tuzatish oqimining biznes qarorlari (nima o'zgarmas, nega) | `apps/server/app/services/RECEIVING_CORRECTION.md` |
| Chek shabloni, printer ulash, chop etish holatlari, haqiqiy printer pilot tekshiruvi (5F) | `BINOS_RECEIPT_PRINTING.md` |

Aktivatsiya runbook'ining §2.1, §2.1a va §2.2 qadamlari endi **shu hujjatga** ishora qiladi —
tafsilot ikki joyda saqlanmaydi.

---

## 1. O'lchangan dalillar (taxmin EMAS)

Hammasi **bajarilgan** mashqdan: `binos_reh_5e` — staging PostgreSQL **18.6** klasteridagi
(`sysid 7683497876193431618`) ALOHIDA baza. U ESKI kod (`99b1da7`) sxemasidan qurilib, uchta
`uuid` ustuni VARCHAR ga qaytarilgan va `receiving_corrections` o'chirilgan — ya'ni
**production'ning bugungi shakli**. Production'ga UMUMAN tegilmagan.

### 1.1 Kod × sxema moslik matritsasi (o'lchangan)

| katak | boot | `/health/ready` | kassa dedup (`client_uuid == uuid`) | QR qidiruv | POS sotuv | offline replay | kuzatuvsiz kirim | tuzatish marshruti |
|---|---|---|---|---|---|---|---|---|
| **A** eski kod + eski sxema (**= bugungi production**) | — | **200** | **42883 bilan YIQILADI** | 42883 | 200 | ok | 200 | 404 |
| **B** yangi kod + eski sxema (deploy qilingan, migratsiya hali yo'q) | rc 0, jadvalni yaratadi | **503** (`column_types`) | 42883 bilan YIQILADI | 42883 | 200 | ok | 200 | 422 (marshrut BOR) |
| **C** eski kod + yangi sxema (migratsiyadan keyingi rollback) | rc 0, jadval qoladi | **200** | **ishlaydi** | ishlaydi | 200 | ok | 200 | 404 |
| **D** yangi kod + yangi sxema (maqsad) | — | **200** | ishlaydi | ishlaydi | 200 | ok | 200 | 422 |

Shu jadvaldan chiqadigan ikki xulosa — butun tartibning asosi:

1. **42883 nuqsoni ALLAQACHON production'da yashaydi** (A katak), eski readiness esa shunga
   qaramay 200 qaytaradi. Deploy uni KELTIRMAYDI — u faqat nuqsonni KO'RINADIGAN qiladi
   (B katak: halol 503).
2. **Migratsiyadan keyingi eski kod bugungidan SOG'LOMROQ** (C katak): 42883 yo'q, bo'sh yangi
   jadval unga inert. Ya'ni migratsiyadan KEYIN ham kod rollback'i xavfsiz.

### 1.2 `uuid` migratsiyasi — mashq raqamlari

`binos_reh_5e` ustida bajarilgan (chiqish satrlari AYNAN shu shaklda keladi):

| Bosqich | Natija |
|---|---|
| `preflight` | `hukm: READY` — 3 og'ish, 0 qator, 0 bloker (buyruq 6.7 s, ochiq proxy orqali ulanish bilan) |
| `apply --rehearse` | `apply: APPLIED · commit=False · DDL=2 · qulf kutishi=94ms · 5526 ms`, keyin katalog qayta o'qildi: tiplar hali `varchar` — ROLLBACK ishladi |
| `apply --commit` | `apply: APPLIED · commit=True · DDL=2 · qulf kutishi=219ms · 15758 ms` — **2 ta ALTER, qulf kutishi 219 ms, DDL 15.8 s** |
| `verify` | `verify: VERIFIED · tiplar: cash_movements.client_uuid=uuid, qr_payments.client_uuid=uuid, qr_payments.sale_id=uuid` |

**DDL 15.8 s** — bu vaqt ichida uchta ustunning jadvallari (`cash_movements`, `qr_payments`)
ACCESS EXCLUSIVE ostida qayta yoziladi: o'sha 15.8 soniya davomida bu ikki jadvalga **yozib ham,
o'qib ham bo'lmaydi**. Fayzan bazasida qator soni boshqa — vaqtni preflight hisobotidagi
`qator=` sonidan chamalang, lekin **sokin oyna** har holda shart.

### 1.3 Yangi jadval (`receiving_corrections`) boot narxi va qulf hikoyasi

Staging **konteynerining ICHIDA** o'lchangan (workstation'dagi ~200–300 s — TCP proxy kechikishi,
vakil emas):

| boot | soniya | natija |
|---|---|---|
| birinchi boot, `receiving_corrections` YO'Q | **7.43** | jadval + `ux_recv_corr_client` yaratildi, FATAL yo'q |
| barqaror boot, hammasi joyida | **6.85** | DDL umuman yo'q |

Yaratiladigan obyektlar: `receiving_corrections_pkey`, `ux_recv_corr_client` (noyob:
`company_id, client_uuid` — tuzatish idempotentligining YAGONA tranzaksion kafolati), hamda
`companies`, `receivings`, `purchases`, `branches`, `employees` ga FK va NOT NULL cheklovlari.

**Nega bo'sh yangi jadval Fayzan jadvallarini to'sib qo'ymaydi:**
- `create_all` faqat YO'Q jadvalni yaratadi; mavjud jadval **qayta yozilmaydi**, ustun
  qo'shilmaydi, ma'lumot skanerlanmaydi — ya'ni Fayzan jadvallarida ACCESS EXCLUSIVE YO'Q;
- `ux_recv_corr_client` **bo'sh, yangi** jadvalda quriladi — skanerlanadigan qator 0;
- mavjud jadvallarga yagona teginish — FK yaratish paytidagi qisqa SHARE ROW EXCLUSIVE, va u
  sessiya `lock_timeout=2s` bilan CHEGARALANGAN (boot jurnalidagi birinchi satr shuni aytadi).

**LEKIN teskarisi bo'lishi MUMKIN — va o'lchangan (§1.4).**

### 1.4 Deploy QULFSIZ EMAS — o'lchangan, fail-closed

Konteyner ichida `purchases` jadvalida 30 soniya `ROW EXCLUSIVE` ushlab turgan bitta tranzaksiya
bilan (oddiy INSERT/UPDATE aynan shu darajani oladi) yangi kod boot'i:

```
rc = 1  (konteyner nolga teng bo'lmagan kod bilan chiqadi)
[FATAL] yangi jadval yaratilmadi (create_all): receiving_corrections —
        companies, receivings, purchases, branches, employees qulfi 5 urinishda ham
        olinmadi (lock_timeout=2s; to'sayotgan seanslar: purchases...)
table_present = false
```

Ma'nosi:
- yangi jadvalning FK'lari **beshta** ota jadvalda qisqa qulf talab qiladi, shu bois
  `purchases`/`receivings` da ochiq YOZUVCHI tranzaksiya boot'ni to'sadi;
- boot **fail-closed**: 5 urinish × 2 s, keyin FATAL. Yarim yaratilgan sxema QOLMAYDI, lekin
  konteyner chiqib ketadi va Railway uni qayta uradi (`ON_FAILURE`; **servis instansiyasi
  `maxRetries=10` deb aytadi** — `railway.json` dagi `5` emas, ikkala muhitda ham API 10 beradi);
- **shuning uchun:** sokin oyna (§D0) va deploydan OLDIN `pg_stat_activity` dan uzoq
  tranzaksiyalarni tekshirish MAJBURIY. Crash-loop bo'lsa yechim — to'sayotgan seansni bo'shatib
  **AYNI SHA** ni qayta yuborish (§4, P2).

### 1.5 Backup / restore mashqi — o'lchangan

GitHub Actions run **35365182486** (artefakt rejimi), artefakt `savdoos-20260918T003850Z.dump`
(2026-09-18 00:38Z production nusxasi):

- shifrlangan fayl checksum'i — ochishdan OLDIN **MOS**; ochilgan dump checksum'i — **MOS**;
- yetishmayotgan rollar qayta yaratildi (`cash_admin`, `cash_app`, `cash_posting`, `cash_readonly`);
- `pg_restore` PostgreSQL 18 da; butunlik: `cash` sxemasi bor, **189 ta FOREIGN KEY**;
- capture-time barmoq izi bilan solishtiruv **MOS** → `RESTORE_REHEARSAL_OK`;
- so'ng TIKLANGAN production ma'lumoti ustida: `preflight` → `apply --commit` → `verify: VERIFIED`;
- ilova smoke: `/health/ready` **200**, sakkizta check ham `true`;
- yuklangan natija artefakti qayd etilgan (`SHA256 32ef232f…`).

Bu — production'ga tegmasdan olinadigan eng kuchli dalil: migratsiya ham, yangi readiness ham
**haqiqiy production ma'lumoti** ustida isbotlangan.

### 1.6 Railway semantikasi (manifest faktlari, GraphQL orqali o'qilgan)

```
staging    healthcheckPath=None timeout=None replicas=None restart=ON_FAILURE maxRetries=10
production healthcheckPath=None timeout=None replicas=None restart=ON_FAILURE maxRetries=10
```

- **`healthcheckPath` YO'Q** — Railway trafikni `/health/ready` ga qarab TO'SMAYDI. Demak 503
  qaytarayotgan konteyner ham so'rov qabul qiladi (B katak: POS sotuvi 200 bo'lib qolaveradi).
- **`replicas` ko'rsatilmagan** — bitta instansiya.
- `start.sh`: `python -m app.initdb` → `python -m app.seed` → `uvicorn`. Ya'ni **`initdb` yiqilsa
  uvicorn UMUMAN ishga tushmaydi** (shuning uchun §1.4 dagi FATAL — crash-loop, «yarim ishlaydigan
  server» emas).
- Production'da **avtomatik deploy trigger'i YO'Q**: deploy faqat ongli, aniq SHA bilan.

### 1.7 Phase 5F deltasi (chek, chop etish, kassa hisoblari ko'rinishi)

5F kodi shu runbook bo'yicha chiqariladigan SHA tarkibiga kirsa, qo'shimcha ravishda:

| Nima o'zgaradi | Deployga ta'siri |
|---|---|
| Ikki YANGI jadval: `receipt_logos`, `print_jobs` | Boot `create_all` bilan yaratadi. Har birida **FAQAT bitta FK — `companies`** (kamdan-kam yoziladigan jadval). 5D dagi besh jadvalli FK to'plamidan (§1.3) qulf yuzasi ancha kichik, lekin mexanizm AYNI: `companies` da uzoq ochiq YOZUVCHI tranzaksiya bo'lsa boot §1.4 dagidek FATAL bilan yiqiladi |
| `ux_print_jobs_original` (noyob, qisman: `copy='ORIGINAL'`) | `REQUIRED_INDEXES` da — Postgres'da yo'q bo'lsa boot FATAL, readiness qizil. YANGI, bo'sh jadvalda quriladi (skanerlanadigan qator 0) |
| `ix_print_jobs_doc` | `PERFORMANCE_INDEXES` (faqat jurnal) |
| Yangi production bog'liqliklari: `pillow`, `qrcode` | Docker image'ga kiradi (`pip install -e .`). CI `prod-install-boundary` job'i o'rnatilgan paketlarni tekshiradi |
| `GET /tills`, `GET /safes` endi ruxsat darvozasi bilan: `kassa.sell` / `kassa.view` / `sozlamalar.view` / `sozlamalar.edit` / `hisobot.view` dan biri | Bu ruxsatlardan hech biri yo'q xodim (standart `omborchi`) endi 403 oladi. Fayzan'da faqat `ega` + `kassir` — ta'sir YO'Q. Kerak bo'lsa xodimga `kassa.view` override beriladi |
| `/tills`, `/safes`, `/cash-setup` filial doirasiga bo'ysunadi | Filialga biriktirilgan xodim faqat o'z filiali hisoblarini ko'radi (ega va biriktirilmagan xodim — hammasini, avvalgidek) |
| `GET /settings` endi faqat KOMPANIYA darajasidagi qatorlarni qaytaradi | Filial qatorlari (`receipt_branch`) hech qachon `receipt` kalitini bosib ketmaydi |
| Filial chek override'i `settings` da **`key='receipt_branch'`** bilan saqlanadi | **Rollback xavfsizligi uchun ataylab:** `99b1da7` ning `GET /settings` i barcha qatorlarni `row_version` bo'yicha o'qib, kalit bo'yicha oxirgisini oladi — override `receipt` kalitida bo'lganida kod rollback'i filial B shablonini HAMMA filialga tarqatardi. Alohida kalitni eski kod umuman `receipt` deb o'qimaydi |

**Klient tartibi (MAJBURIY):** 5F dagi POS/Manager onlayn chekni serverdan (`GET /sales/{id}/receipt`)
oladi. Shuning uchun **avval server deploy qilinadi va kuzatuv oynasi (D9) tugaydi, keyin klient
release** (`CLAUDE.md` «Yangi versiya chiqarish» 0-qadam: production'da `GET /api/v1/receipt/profile`
404 bo'lsa release QILINMAYDI). Klientlar tarqalgach serverni 5F dan oldingi SHA ga qaytarish chekni
buzadi: POS faqat O'Z sotuvini eski usulda (mahalliy ma'lumotdan) chop eta oladi, Sotuvlarim/Manager
qayta chop etishi va qaytarish cheki ishlamaydi. Bunday holatda rollback nishoni — 5F SHA yoki undan
keyingisi.

**Haqiqiy printer:** 5F da ESC/POS baytlari golden testlar va virtual TCP printer bilan isbotlangan,
lekin **HAQIQIY printerda sinalmagan**. Pilot do'konda birinchi kuni `BINOS_RECEIPT_PRINTING.md` §8
dagi tekshiruv ro'yxati bajarilmaguncha chekka tayanilmaydi.

---

## 2. Tavsiya etilgan tartib va NEGA aynan shu

### 2.1 Tartib

```
backup → preflight (faqat o'qish) → deploy (aniq SHA) → migratsiya platformada
       (--rehearse, keyin --commit) → verify → readiness yashil → smoke
       → deploydan KEYINGI backup + restore mashqi
```

### 2.2 Asos (uchta o'lchangan fakt)

1. **Migratsiya vositasi ishlab turgan image'da YO'Q.** `99b1da7` da na
   `app/tools/schema_migrate.py`, na migratsiya moduli bor. Demak «avval migratsiya» faqat
   workstation'dan, ochiq proxy orqali, `--allow-production` +
   `--confirm-production-system-identifier` va **qo'lda e'lon qilingan production muhiti** bilan
   mumkin — ko'proq marosim va hech qachon mashq qilinmagan yo'l.
2. **Deploy yangi buzilish keltirmaydi.** A katak 42883 nuqsoni allaqachon tirikligini isbotlaydi;
   yangi kod xuddi shunday ishlaydi, faqat readiness halol 503 ga o'tadi va bo'sh jadval paydo
   bo'ladi.
3. **O'sha oynada rollback arzon.** `99b1da7` ni aniq SHA bilan qayta deploy qilish kifoya; bo'sh
   `receiving_corrections` eski kod uchun inert (C katak: eski kod jadval turgan bazada rc 0 bilan
   ko'tariladi).

### 2.3 Rad etilgan muqobil: AVVAL migratsiya (503 oynasisiz)

503 oynasini umuman istamagan operator uchun yo'l bor, lekin marosimi og'ir:

- workstation'da YANGI kod checkout qilinadi, `DATABASE_URL` — production'ning **ochiq**
  (`proxy.rlwy.net`) satri;
- `APP_ENV=production` **VA** `RAILWAY_ENVIRONMENT_NAME=production` qo'lda e'lon qilinadi (guard
  «production signali yo'qligi» ni production emas deb HISOBLAMAYDI — `app/db/migrations/guard.py`);
- `apply --commit` `--allow-production --confirm-production-system-identifier 7674898282858840119`
  bilan bajariladi;
- ALTER'lar ochiq proxy orqali yuboriladi — tarmoq uzilsa tranzaksiya to'liq qaytadi (qisman holat
  YO'Q), lekin 15.8 s DDL ustiga proxy kechikishi qo'shiladi;
- shundan KEYIN deploy qilinadi va `/health/ready` birinchi boot'dan 200 bo'ladi (C→D o'tishi).

**Nega tavsiya etilmaydi:** bu yo'l mashq qilinmagan; production DDL'i platformadan tashqarida,
workstation tarmog'iga bog'lab qo'yiladi; `--allow-production` niqobi bilan ishlash odat bo'lib
qolishi xavfli. 503 oynasi esa savdoni TO'XTATMAYDI (§D4).

---

## 3. Qadamlar

Har qadam: **BUYRUQ → KUTILADI → STOP**. STOP sharti yuz bersa keyingi qadamga O'TILMAYDI.

| # | Qadam | Yozadimi | STOP sharti |
|---|---|---|---|
| D0 | Oyna va prekondisiyalar | yo'q | uzoq tranzaksiya bor; CI qizil; staging smoke PASS emas |
| D1 | Deploy OLDIDAN backup | yo'q (production'ga) | run qizil; artefakt bo'sh; `capture_quiescent=false` |
| D2 | `preflight` — GO/NO-GO | yo'q | hukm `READY` emas |
| D3 | Deploy (aniq SHA) | HA | `[FATAL]`; `build.commit` ≠ SHA; jurnalda `-> uuid` |
| D4 | 503 oynasi — kuzatish | yo'q | POS sotuvi yiqildi; `/health` ham 200 emas |
| D5 | `uuid` migratsiyasi (platformada) | **HA — alohida yozma ruxsat** | preflight `BLOCKED`; `REJECTED_STATE_CHANGED`; qulf band |
| D6 | `verify` + readiness | yo'q | `verify` FAIL; biror check `false` |
| D7 | Smoke | yo'q | §D7 dagi birorta shart |
| D8 | Deploydan KEYINGI backup + restore mashqi | yo'q (production'ga) | mashq qizil |
| D9 | Kuzatuv oynasi (24 soat) | yo'q | §4 dagi rollback sharti |

### D0 — Oyna va prekondisiyalar

- **Sokin oyna:** kassa smenasi yopiq, POS offline navbati bo'sh (`/fleet/devices` →
  `queue_not_empty` yo'q), Manager'da ochiq kirim/tuzatish tahriri yo'q.
- **CI:** chiqariladigan SHA uchun 6/6 yashil, PG18 bajarilish isboti bor, staging'da AYNI SHA
  smoke PASS.
- **Uzoq tranzaksiyalar (§1.4 — deploy'ni to'sadigan yagona narsa):**

```sql
SELECT pid, state, application_name,
       EXTRACT(EPOCH FROM clock_timestamp() - xact_start)::int AS xact_s
FROM pg_stat_activity
WHERE xact_start IS NOT NULL AND state <> 'idle'
ORDER BY xact_start;
```

- **KUTILADI:** `xact_s` > 5 bo'lgan yozuvchi seans YO'Q.
- **STOP:** uzoq yozuvchi tranzaksiya bor — u tugaguncha (yoki egasi bilan kelishib bo'shatilguncha)
  deploy YUBORILMAYDI. Aks holda boot `[FATAL]` bilan yiqiladi va Railway 10 marta qayta uradi.

### D1 — Deploy OLDIDAN backup (MAJBURIY)

```bash
"C:\Program Files\GitHub CLI\gh.exe" workflow run db-backup.yml \
    --repo ZafarbekOlimboyev/savdoos --ref main
"C:\Program Files\GitHub CLI\gh.exe" run list --workflow db-backup.yml \
    --repo ZafarbekOlimboyev/savdoos --limit 1
```

- **KUTILADI:** run yashil. Jurnalda `ikkala sir ham mavjud`, `Saqlash: daily / 14 kun`
  (yakshanba — `weekly / 56`, oyning 1-kuni — `monthly / 180`), `dump davomida baza O'ZGARMADI —
  barmoq izi ANIQ`, `companies=… branches=… sales=…`, `shifrlandi: …dump.gpg (… bayt)`.
- Artefakt: `savdoos-db-<tier>-<run_id>` — ichida FAQAT `*.dump.gpg`, `*.sha256`, `*.meta.json`,
  `fingerprint.json`, `fingerprint-before.json`. **Ochiq dump artefaktga CHIQMAYDI.**
- **`<run_id>` ni yozib oling** — D8 va falokat holati uchun kerak.
- **STOP:** run qizil; artefakt bo'sh (`if-no-files-found: error` shuni ushlaydi);
  `meta.json` da `capture_quiescent=false` (dump davomida baza o'zgargan — barmoq izi taxminiy,
  demak tiklashni solishtirish zaif). Bu holatda sokinroq paytda qayta oling.

### D2 — `preflight` (faqat o'qish) — GO/NO-GO

Ishlab turgan image'da vosita YO'Q, shuning uchun bu qadam **workstation'dan**, YANGI kod
checkout'idan, production'ning **ochiq** (`proxy.rlwy.net`) ulanish satri bilan bajariladi.
Ulanish satrini olish — `PRODUCTION_OPERATIONS_RUNBOOK.md` §3.1, 1-qadam; qiymat terminal
tarixiga TUSHMASIN.

```bash
cd apps/server
DATABASE_URL="$PROD_DB_URL" .venv/Scripts/python.exe -m app.tools.schema_migrate preflight \
    --migration 2026-09-17.uuid-client-columns-v1 \
    --expect-system-identifier 7674898282858840119 \
    --out uuid-preflight-prod.json
```

(Buyruq Git Bash uchun. PowerShell'da: `$env:DATABASE_URL = $PROD_DB_URL` ni ALOHIDA satrda
bering — qiymatni buyruq satriga yozmang, u tarixga tushadi.)

Sessiya DB darajasida read-only (`default_transaction_read_only=on` + `REPEATABLE READ READ ONLY`)
va bu ISBOTLANADI: hisobotdagi `read_only_proof` da negativ zond `rejected: SQLSTATE 25006`.

- **KUTILADI** (maydonlar AYNAN shu va shu tartibda; `<…>` — o'zgaruvchi qiymat):

```
migratsiya:  2026-09-17.uuid-client-columns-v1
baza:        <baza nomi> · system_identifier 7674898282858840119 · server 180000
hukm:        READY
og'ishlar:   cash_movements.client_uuid, qr_payments.sale_id, qr_payments.client_uuid
  cash_movements.client_uuid: qator=<N> null=<N> kanonik_kichik=<N> kanonik_boshqa_registr=0 bo'sh=0 nokanonik=0
  qr_payments.sale_id: qator=<N> null=<N> kanonik_kichik=<N> kanonik_boshqa_registr=0 bo'sh=0 nokanonik=0
  qr_payments.client_uuid: qator=<N> null=<N> kanonik_kichik=<N> kanonik_boshqa_registr=0 bo'sh=0 nokanonik=0
plan_sha256:   <64 belgi>
report_sha256: <64 belgi>
hisobot saqlandi: uuid-preflight-prod.json
```

Har og'ishgan ustun uchun BITTA satr chiqadi va oltita maydon DOIM bo'ladi (`qator`, `null`,
`kanonik_kichik`, `kanonik_boshqa_registr`, `bo'sh`, `nokanonik`). Nimaga qarash kerak:
`bo'sh` yoki `nokanonik` noldan farq qilsa — hukm `BLOCKED` (pastdagi STOP ro'yxati).
`kanonik_boshqa_registr` (KATTA harfli, lekin kanonik UUID) o'z-o'zicha **to'smaydi** — `apply`
qiymatni `lower(…)::uuid` bilan o'tkazadi; u faqat NOYOB kalitda dublikat hosil qilsa
`UUID_CASE_DUPLICATE_IN_UNIQUE_KEY` bilan to'sadi. Topilmalar shu satrlardan keyin
`  [SEVERITY] KOD: tafsilot` shaklida chiqadi.

- Chiqish kodlari: `0` = READY/ALREADY_APPLIED, `1` = usage/darvoza rad etdi, `2` = REVIEW,
  `3` = BLOCKED. Chiqishda **qiymat, DSN, host YO'Q** — faqat sanoq, struktura va sha256.
- **STOP (`hukm: BLOCKED`, exit 3):** `UUID_NONCANONICAL`, `UUID_EMPTY_STRING`,
  `UUID_CASE_DUPLICATE_IN_UNIQUE_KEY` (uuid'ga o'tgach 23505 bo'lardi),
  `UUID_UNEXPECTED_INDEX/DEPENDENCY`, `UUID_EXPECTED_INDEX_MISSING`,
  `UUID_TABLE_MISSING/UUID_COLUMN_MISSING`. **Qiymatlar bo'yicha qaror operatorniki** — deploy
  ham TO'XTATILADI (aks holda 503 oynasi cho'ziladi).
- `UUID_NOT_TABLE_OWNER` — REVIEW (exit 2): hisobot tayyor, lekin `apply` jadval EGASI bilan
  bajarilishi shart. D5 ni shu login bilan rejalashtiring.
- Bu hisobot **dalil** sifatida saqlanadi. D5 dagi `apply` uni ISHLATA OLMAYDI (boshqa fayl
  tizimi), va kerak ham emas: `apply` rejani QULF OSTIDA qayta hisoblab, `plan_sha256` tengligini
  talab qiladi.

### D3 — Deploy (aniq SHA)

- **BUYRUQ:** Railway GraphQL
  `serviceInstanceDeployV2(serviceId, environmentId=<production>, commitSha=<40 belgili SHA>)`.
  `railway up` yuklashidan farqli o'laroq, bu usul `/health` dagi `build.commit` ni AYNAN shu
  SHA'ga bog'laydi. Tafsilot: `BINOS_LOT_ACTIVATION_RUNBOOK.md` §2.1.
- **BOOT JURNALIDA KUTILADI:**

```
[boot] initdb: jadvallar yaratilmoqda...
[boot] lock_timeout=2s — boot DDL'i qulfni shundan uzoq kutmaydi
[boot] partiya faollashtirish: rejim=closed, ro'yxat yozuvlari=0
[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: cash_movements.client_uuid
[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: qr_payments.sale_id
[schema] TAYYOR EMAS (boot davom etadi) — ustun tipi uuid emas: qr_payments.client_uuid
[schema] ustun tipi og'ishi — tuzatish (boot EMAS, operator): python -m app.tools.schema_migrate preflight --migration 2026-09-17.uuid-client-columns-v1
[boot] seed: boshlang'ich ma'lumot...
[boot] uvicorn ishga tushmoqda, port=8080
```

Uchta `TAYYOR EMAS` satri — **YIQILISH EMAS**, bu B katakning kutilgan holati.
`rejim=closed` SHART: aktivatsiya darvozasi hali ochilmagan.

```bash
curl -s https://savdoos-production.up.railway.app/api/v1/health
```

- **KUTILADI:** `build.commit == <SHA>`, `environment=production`,
  `platform_environment=production`.
- **STOP 1 — `[FATAL] yangi jadval yaratilmadi (create_all): receiving_corrections — …`:**
  qulf band edi (§1.4). Konteyner crash-loop'da. Yechim: to'sayotgan seansni (jurnalda pid
  ko'rsatilgan) bo'shatib, **AYNI SHA** ni qayta deploy qilish. Bu P2 nuqtasi (§4).
- **STOP 2 — jurnalda `[migrate] … -> uuid` satri:** boot ustun tipini o'zgartirgan bo'lardi; bu
  Phase 5C dan keyin bo'lishi MUMKIN EMAS. Chiqsa — noto'g'ri SHA deploy qilingan.
- **STOP 3 —** `build.commit` ≠ SHA.

### D3a — KONTEYNER ALMASHUVI: QISQA UZILISH BOR (O'LCHANGAN)

⚠️  BU 503 OYNASI EMAS, UNDAN OLDINGI BOSHQA HODISA. Railway eski konteynerni yangisi
    xizmatga tayyor bo'lguncha USHLAB TURMAYDI: `healthcheckPath` yo'q, replika bitta.
    Staging'da AYNI SHA bilan o'lchangan (2026-09-18, deploy 13859957, 403 ta 1 soniyalik
    zond):

```
…357.85  health 200  commit 1a4a46b  ready 200      ← eski konteyner xizmatda
…397.07  health 502              ready 502          ← UZILISH boshlandi
…412.85  health 200  commit 3799835 ready 200       ← yangi konteyner xizmatda
```

- **uzilish uzunligi:** ~15 soniya (12 ta ketma-ket 502). Production'da image kattaroq va
  boot uzunroq (`initdb` konteyner ichida 7.4 s o'lchangan, birinchi boot yangi jadvalni ham
  yaratadi) — **30–60 soniyaga mo'ljallang**.
- **shu oynada:** HAR QANDAY so'rov 502. POS offline navbatga yozadi va keyin replay qiladi
  (`/sync/push`), Manager esa xatoni DARHOL ko'radi.
- **shuning uchun:** deploy sokin oynada (§D0) qilinadi va kassirlarga oldindan aytiladi;
  «bir daqiqacha ishlamaydi» — kutilgan hodisa, avariya emas.
- **agar boot YIQILSA** (masalan `purchases` band — §1.5), 502 oynasi TUGAMAYDI: bu holda
  §4 P1 bo'yicha `99b1da7` ni aniq SHA bilan qayta deploy qiling va sababni bartaraf eting.

### D4 — 503 oynasi: nima ko'rinadi, nima ISHLAYDI

Bu oyna D3 tugagandan D6 gacha davom etadi. Uni oldindan biling, aks holda halol signalni
avariyaga chalkashtirasiz.

```bash
curl -s -w "\n%{http_code}\n" \
    https://savdoos-production.up.railway.app/api/v1/health/ready
```

- **KUTILADI:** HTTP **503**, tana: `{"status":"not_ready","checks":{…,"column_types":false}}`.
  Qolgan yettita check `true` bo'lishi SHART.
- **ISHLAYDI (B katak bilan o'lchangan):** POS sotuvi 200, offline replay ok, kuzatuvsiz kirim
  200. `healthcheckPath` yo'qligi sababli Railway TAYYORLIK bo'yicha trafikni to'smaydi (§1.6) —
  **yangi konteyner ko'tarilgach kassa savdo qilishda davom etadi**. (Konteyner ALMASHUVI
  paytidagi ~15–60 soniyalik 502 uzilishi alohida hodisa — §D3a.)
- **ISHLAMAYDI (bugun ham ishlamayapti):** kassa kirim/chiqim dedup va QR qidiruv — `42883`.
  Bu A katakda ham shunday; deploy buni O'ZGARTIRMAYDI.
- **Uptime workflow QIZARADI.** `.github/workflows/uptime.yml` har 15 daqiqada `/health/ready` ni
  so'raydi va 3 urinishdan keyin `::error::Server JAVOB BERYAPTI, lekin TAYYOR EMAS` bilan
  yiqiladi (email keladi). Oyna qancha uzun bo'lsa, shuncha qizil run. **Bu KUTILGAN** — yangi
  hodisa sifatida tekshirilmaydi, lekin D6 dan keyin yashilga qaytgani TASDIQLANADI.
- **STOP:** `/health` ham 200 emas (jarayon tirik emas) yoki POS sotuvi yiqila boshladi → darhol
  §4 P3.

### D5 — `uuid` migratsiyasi platformada (YOZADI — alohida yozma ruxsat)

Vosita endi ishlab turgan image'da BOR. Buyruqlar konteyner ichida bajariladi: Railway'ning
ICHKI Postgres hosti Windows workstation'dan RESOLVE BO'LMAYDI (shu sabab `railway run` emas,
`railway ssh`).

**1) Preflight — hisobot `apply` ishlaydigan joyda tug'ilsin:**

```bash
railway.cmd ssh --service savdoos -- python -m app.tools.schema_migrate preflight \
    --migration 2026-09-17.uuid-client-columns-v1 \
    --expect-system-identifier 7674898282858840119 \
    --out /tmp/uuid-preflight.json
```

- **KUTILADI:** `hukm: READY`, `plan_sha256` D2 dagiga TENG (oradan beri struktura o'zgarmagan).
- ⚠️ Hisobot fayli faqat SHU konteyner instansiyasida yashaydi. Konteyner qayta ishga tushsa
  fayl yo'qoladi — preflight qaytadan bajariladi (bu himoya, nuqson emas).
- **STOP:** hukm `READY` emas; `plan_sha256` D2 dagidan FARQ qiladi (kimdir sxemaga tegdi) —
  sababini aniqlamasdan davom etilmaydi.

**2) Mashq (hech narsa o'zgarmaydi — tranzaksiya DOIM qaytariladi):**

```bash
railway.cmd ssh --service savdoos -- python -m app.tools.schema_migrate apply \
    --migration 2026-09-17.uuid-client-columns-v1 \
    --report /tmp/uuid-preflight.json \
    --expect-system-identifier 7674898282858840119 \
    --rehearse --allow-production \
    --confirm-production-system-identifier 7674898282858840119
```

- ⚠️ **`--rehearse` ham production darvozasidan o'tadi:** `--allow-production` va
  `--confirm-production-system-identifier` mashqda ham MAJBURIY, aks holda
  `RAD ETILDI: …` (exit 1) keladi va hech narsa bajarilmaydi. Bu ataylab — darvoza yozuv
  sessiyasini ochish faktiga bog'langan, commit faktiga emas.
- **KUTILADI:**

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  PRODUCTION YO'LI: apply bazaga YOZADI (ACCESS EXCLUSIVE + ALTER TABLE).
  Alohida YOZMA ruxsatsiz bajarilmaydi (runbook §2.1).
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
apply: APPLIED · commit=False · DDL=2 · qulf kutishi=<N>ms · <M> ms
  ALTER TABLE public."cash_movements" ALTER COLUMN "client_uuid" TYPE uuid USING lower("client_uuid")::uuid
  ALTER TABLE public."qr_payments" ALTER COLUMN "sale_id" TYPE uuid USING …, ALTER COLUMN "client_uuid" TYPE uuid USING …
  tiplar: cash_movements.client_uuid=varchar, qr_payments.client_uuid=varchar, qr_payments.sale_id=varchar
```

  Oxirgi satr — ISBOT: mashqdan keyin tiplar hali `varchar`, ya'ni ROLLBACK ishladi.
  `<M>` — commit'dagi DDL vaqtining yaqin bahosi (mashqda 5.5 s, commit'da 15.8 s bo'lgan).
- **STOP:** `MASHQ QAYTARILMADI: …` (exit 3) — bu holatda katalog qo'lda tekshiriladi va
  `--commit` BAJARILMAYDI.

**3) APPLY (yozadi — ALOHIDA YOZMA RUXSAT):**

```bash
railway.cmd ssh --service savdoos -- python -m app.tools.schema_migrate apply \
    --migration 2026-09-17.uuid-client-columns-v1 \
    --report /tmp/uuid-preflight.json \
    --expect-system-identifier 7674898282858840119 \
    --commit --allow-production \
    --confirm-production-system-identifier 7674898282858840119 \
    --lock-timeout-ms 2000 --statement-timeout-ms 60000
```

Bitta tranzaksiya: `SET LOCAL lock_timeout`/`statement_timeout` → `LOCK TABLE … ACCESS EXCLUSIVE`
(nomlar bo'yicha tartiblangan — deadlock tartibi barqaror) → preflight QULF OSTIDA qayta
hisoblanadi va `plan_sha256` tengligi talab qilinadi → digest → har jadvalga BITTA `ALTER` →
tranzaksiya ICHIDA yakuniy tekshiruv (tip, indeks noyob/yaroqli/ayni ta'rif, digest). Har qanday
nomuvofiqlik → to'liq ROLLBACK. **Qisman holat bo'lishi MUMKIN EMAS.**

- **KUTILADI:**

```
COMMIT BAJARILDI · DDL=2
  ALTER TABLE public."cash_movements" ALTER COLUMN "client_uuid" TYPE uuid USING …
  ALTER TABLE public."qr_payments" ALTER COLUMN "sale_id" TYPE uuid USING …, ALTER COLUMN "client_uuid" TYPE uuid USING …
apply: APPLIED · commit=True · DDL=2 · qulf kutishi=<N>ms · <M> ms
  ALTER TABLE public."cash_movements" …
  ALTER TABLE public."qr_payments" …
  tiplar: cash_movements.client_uuid=uuid, qr_payments.client_uuid=uuid, qr_payments.sale_id=uuid
```

  (`…` — qisqartirilgan: to'liq `ALTER` satrlari yuqoridagi mashq chiqishida ko'rsatilgan.)
  ⚠️ DDL satrlari **ikki marta** chiqadi: avval `COMMIT BAJARILDI` blokida, keyin `apply:`
  satridan so'ng. Bu vositaning normal chiqishi — `ALTER` ikki marta BAJARILGANI emas
  (`DDL=2` bitta tranzaksiyadagi ikki bayonot: har jadvalga BITTA `ALTER`).
  Mashqda: `qulf kutishi=219ms`, DDL `15758 ms` (§1.2).
- **STOP — `QULF OLINMADI (lock_timeout=2000ms): … to'sayotgan seanslar: pid=…` (exit 2):**
  hech narsa o'zgarmadi. Seansni bo'shatib, sokin oynada QAYTA uriniladi.
- **STOP — `VAQT CHEGARASI (statement_timeout=60000ms)` (exit 2):** hech narsa o'zgarmadi.
  Jadval kutilganidan katta — sokinroq oyna va kattaroq `--statement-timeout-ms` bilan
  rejalashtiriladi.
- **STOP — `TO'XTATILDI (MigrationRejected): …REJECTED_STATE_CHANGED` (exit 3):** preflightdan
  keyin struktura o'zgargan. Preflight QAYTA bajariladi (1-punkt).
- ⚠️ **`VERIFY O'QILMADI (… ) — COMMIT BAJARILDI`** satri chiqsa: DDL **qo'llangan**, faqat
  keyingi o'qish uzilgan. `verify` ni alohida bajaring (D6), qayta `apply` QILMANG.
- ⚠️ Hovuzdagi tayyorlangan so'rovlar (`psycopg3 prepare_threshold`) uchun apply konteyner
  restart'i bilan yonma-yon bajariladi — D6 dan keyin `/health/ready` 200 bo'lmasa, servisni bir
  marta qayta ishga tushiring.

### D6 — `verify` + readiness

```bash
railway.cmd ssh --service savdoos -- python -m app.tools.schema_migrate verify \
    --migration 2026-09-17.uuid-client-columns-v1 \
    --expect-system-identifier 7674898282858840119
curl -s https://savdoos-production.up.railway.app/api/v1/health/ready
```

- **KUTILADI:**
  `verify: VERIFIED · tiplar: cash_movements.client_uuid=uuid, qr_payments.client_uuid=uuid, qr_payments.sale_id=uuid`
  va HTTP **200**, `status=ready`, **sakkizta** check `true`: `database`, `cash_schema`, `config`,
  `tenancy_schema`, `catalog_v2_schema`, `lot_schema_integrity`, `idempotency_schema`,
  `column_types`.
- **KUTILADI:** keyingi uptime run yashil (`Server TAYYOR ✅`).
- **STOP:** `verify: FAILED` + `[MUAMMO] …`; yoki biror check `false`. Aktivatsiyaga O'TILMAYDI —
  `/lots/enable` baribir 409 `LOT_SCHEMA_NOT_READY` beradi
  (`BINOS_LOT_ACTIVATION_RUNBOOK.md` §2.3).

### D7 — Smoke (deploydan keyin, aktivatsiyadan OLDIN)

| Tekshiruv | KUTILADI |
|---|---|
| `/api/v1/health` | `build.commit == <SHA>`, `environment=production` |
| `/api/v1/health/ready` | 200, sakkizta check `true` |
| Kassa kirim/chiqim (dedup) va QR qidiruv | **42883 YO'Q** — bugungi nuqson TUZATILDI (A→D) |
| POS sotuvi, offline replay | 200 / ok (D katak) |
| Kuzatuvsiz kirim (Manager «Yangi kirim») | 200, qoldiq kutilgandek siljidi |
| `GET /purchases/{id}` (kuzatuvsiz hujjat) | `cash_custody.mode` = `NOT_APPLICABLE` (qarz hujjati) yoki `NOT_REQUIRED` (naqd, T0 dan oldin — Fayzan BUGUN shu holatda) |
| Tuzatish marshruti mavjudligi | `POST /receiving/{id}/corrections` 404 EMAS (bo'sh tana — 422) |
| `GET /lots/availability` (Fayzan ega) | `activation_allowed=false` (darvoza hali YOPIQ), `tracked_products=0` |
| 5F: `GET /receipt/profile` (Fayzan ega) | 200, `effective.width_mm` ∈ {58, 80}; `print_jobs` va `receipt_logos` BO'SH (hech kim chop etmagan) |
| 5F: `GET /tills?mine=true` (Fayzan kassir) | 200 — kassir smena ochishda kassasini ko'radi (ruxsat darvozasidan o'tadi) |
| Railway jurnali | `[FATAL]` yo'q; REJALASHTIRILMAGAN qayta ishga tushish (crash-loop) yo'q |

- ⚠️ **Jurnal satrlari haqida — muhim.** D3 dagi boot satrlari (`[schema] TAYYOR EMAS (boot
  davom etadi) — ustun tipi uuid emas: …` va `[schema] ustun tipi og'ishi — tuzatish (boot
  EMAS, operator): …`) jurnalda **QOLADI**. Jurnal — tarix, va bu ketma-ketlikda konteyner
  qayta ishga tushirilmaydi (D5 dagi restart faqat `/health/ready` 200 bo'lmaganda bajariladi).
  Ularni "yo'qolgan" deb kutmang — bu yerda ular STOP sharti EMAS.
- **Holatni ISBOTLAYDIGAN narsa boshqa:** D6 dagi `verify: VERIFIED` va `/health/ready`
  javobidagi `column_types=true`. Jurnal emas, AYNAN shu ikkisi ustun tiplari o'zgarganini
  ko'rsatadi.
- Konteyner baribir qayta ishga tushirilsa (D5 dagi ixtiyoriy restart), **YANGI** boot bloki bu
  satrlarsiz chiqishi kerak. Yangi boot'da ular QAYTA chiqsa — §4 P4/P5.
- **STOP:** yuqoridagilardan birortasi bajarilmasa — §4 P4/P5.

### D8 — Deploydan KEYINGI backup va restore mashqi

Yangi sxemadagi nusxa ham TIKLANISHI isbotlanishi kerak — sxema o'zgargan, demak eski mashq
dalili avtomatik ko'chmaydi.

```bash
"C:\Program Files\GitHub CLI\gh.exe" workflow run db-backup.yml \
    --repo ZafarbekOlimboyev/savdoos --ref main
# run tugagach, uning <run_id> si bilan:
"C:\Program Files\GitHub CLI\gh.exe" workflow run restore-rehearsal.yml \
    --repo ZafarbekOlimboyev/savdoos --ref main -f backup_run_id=<run_id>
```

`backup_run_id` berilgani uchun **`artifact`** job ishlaydi: u production'ga UMUMAN ulanmaydi va
saqlangan artefaktning AYNAN o'zini tiklaydi (falokat kunida ishlatiladigan narsa shu).

- **KUTILADI** (jurnal ketma-ketligi): `shifrlangan checksum: MOS (ochishdan oldin tekshirildi)`
  → `ochiq dump checksum: MOS (…)` → rollar → `cash schema: … · foreign keys: <N>` →
  `RESTORE_REHEARSAL_OK — sanoqlar va summalar MOS` → `python -m app.initdb` →
  **`uuid` bosqichi bu safar `ALREADY_APPLIED`** → `verify: VERIFIED` → `readyz: 200 …` →
  `SMOKE OK`.
- `uuid` bosqichining AYNI chiqishi (nusxa allaqachon migratsiya qilingan sxemani olib keladi,
  shu bois jadval umuman QULFLANMAYDI; ikkala buyruq ham exit 0):

```
hukm:        ALREADY_APPLIED           <- preflight hisoboti (qolgan satrlari D2 dagidek)
COMMIT BAJARILDI · DDL=0
apply: ALREADY_APPLIED · commit=True · DDL=0 · qulf kutishi=0ms · <M> ms
  tiplar: cash_movements.client_uuid=uuid, qr_payments.client_uuid=uuid, qr_payments.sale_id=uuid
```

  ⚠️ `COMMIT BAJARILDI · DDL=0` — bu satr `--commit` yo'lida DDL BO'LMASA HAM chiqadi
  (tranzaksiya commit qilindi, ichida o'zgarish yo'q). «Migratsiya qayta bajarildi» degani EMAS:
  buni `DDL=0` va `qulf kutishi=0ms` isbotlaydi.
- **STOP:** `RESTORE_REHEARSAL_FAILED — barmoq izi MOS EMAS`; `CHECKSUM MOS EMAS`;
  `tiklangan bazada readiness YIQILDI`. Bu holatda backup «bor» deb hisoblanMAYDI.

### D9 — Kuzatuv oynasi (kamida 24 soat)

| Signal | Qayerda | Ma'nosi |
|---|---|---|
| `/health/ready` 200, uptime yashil | GitHub Actions, har 15 daqiqa | Norma |
| `42883 operator does not exist` | Railway jurnali | Migratsiya ta'sir qilmagan yo'l qolgan — tekshiring |
| `[FATAL]`, konteyner qayta ishga tushishi | Railway jurnali | §4 P3/P4 |
| `X-Error-Code: LOT_*` | javob sarlavhasi | Aktivatsiya hali yo'q — bo'lishi KUTILMAYDI |
| Kunlik backup runi | GitHub Actions, 22:30 UTC | Qizil bo'lsa — RPO buziladi (§5) |

---

## 4. Rollback matritsasi (P1..P6)

### 4.1 Nuqtalar

| Nuqta | Holat |
|---|---|
| **P1** | Backup olingan, `preflight READY`, deploy HALI qilinmagan |
| **P2** | Deploy yuborildi, boot `[FATAL]` (jadval qulf tufayli yaratilmadi), crash-loop |
| **P3** | Deploy muvaffaqiyatli: yangi kod + ESKI sxema (**B katak**), `/health/ready` 503 |
| **P4** | `apply --commit` bajarildi, `verify: VERIFIED` (**D katak**), biznes hodisasi hali yo'q |
| **P5** | Smoke/kuzatuvda yangi kodda nuqson topildi; yangi kod allaqachon savdo/naqd yozgan |
| **P6** | Pilot boshlandi: kuzatuvli qabul va/yoki tuzatish yozildi (`receiving_corrections`, `stock_batches`, kassa ledgeri) |

### 4.2 Matritsa

| Nuqta | Kod rollback (`99b1da7`) | Sxema revert (`revert --commit`) | Yagona to'g'ri yo'l |
|---|---|---|---|
| **P1** | kerak emas | kerak emas | Deploy qilinmaydi. Hech narsa o'zgarmagan |
| **P2** | XAVFSIZ, lekin odatda **kerak emas** | kerak emas (sxema tegilmagan) | To'sayotgan seansni bo'shatib **AYNI SHA** ni qayta deploy qilish (§1.4). Jadval yaratilmagan — baza D0 holatida |
| **P3** | **XAVFSIZ** — bo'sh `receiving_corrections` eski kod uchun inert (C katak: eski kod jadval turgan bazada rc 0 bilan ko'tariladi; `uuid` ustunlari esa hali A katak holatida) | kerak emas | Yo oldinga (D5), yo `99b1da7` ni aniq SHA bilan qayta deploy qilish. **Bo'sh jadval O'CHIRILMAYDI** — keyingi deploy uni baribir qayta yaratadi |
| **P4** | **XAVFSIZ va O'LCHANGAN** — C katak: eski kod yangi sxemada bugungidan SOG'LOMROQ (42883 yo'q) | **TAVSIYA ETILMAYDI** | Kod rollback'i yetarli. `revert --commit` faqat favqulodda: u 42883 nuqsonini QAYTARADI va asli KATTA harfli qiymatlar kichik harfda QOLADI (preflightdagi `canonical_other_case` — o'sha dalil) |
| **P5** | Mumkin (aktivatsiya boshlanmagan bo'lsa), **lekin yozilgan ma'lumot QAYTMAYDI** | yo'q | Kodni qaytaring; yangi kod yozgan savdo/naqd yozuvlari O'RNIDA QOLADI va DELETE/UPDATE bilan tozalanMAYDI (§4.3). Nuqson ma'lumotga ta'sir qilgan bo'lsa — oldinga tuzatish |
| **P6** | **TAQIQLANADI** | yo'q | `99b1da7` da do'kon × filial darvozasi, tz tasdiq darvozasi va partiya maydonlarini yashirish YO'Q (`BINOS_LOT_ACTIVATION_RUNBOOK.md` §3.3). Yagona yo'l — **oldinga tuzatish**: `POST /receiving/{id}/corrections` va/yoki darvozani yopish (o'sha §3.2) |

**Kod rollback'i qaysi SHA'ga:** aktivatsiyadan OLDIN (P2–P5, `track_lots=0`, darvoza yopiq)
`99b1da7` — bu shunchaki OLDINGI deploy. Aktivatsiyadan KEYIN (P6) `99b1da7` taqiqlanadi;
`89f647a` dan pastga esa partiya ma'lumoti bor bazada UMUMAN qaytilmaydi.

### 4.3 O'zgarmas biznes hodisasi HECH QACHON `DELETE`/`UPDATE` bilan qaytarilmaydi

Bu — butun rollback siyosatining o'zagi.

- **Tegilmaydi:** `cash.cash_ledger_entries`, `supplier_ledger`, `stock_movements`,
  `stock_batches` identiteti (raqam, muddat, `received_qty`, `unit_cost`), `purchase_items`
  qatorlari va `Receiving.final_items` surati.
- **Nima qilinadi:** YANGI, qarama-qarshi hodisa yoziladi — aynan shu uchun Phase 5D da tuzatish
  oqimi bor: teskari yozuv + o'rniga qo'yish, bitta tranzaksiyada, o'zgarmas yozuvlarga
  TEGMASDAN (`apps/server/app/services/RECEIVING_CORRECTION.md`).
- **Nega:** kassa ledgeri biznes kaliti (`cle_uq_business`) va replay himoyasi qatorlar
  O'ZGARMAS degan farazga tayanadi. Qo'lda `DELETE`/`UPDATE` idempotentlikni buzadi, tarixiy
  tannarxni YOLG'ON qiladi va buzilish kunlar keyin, hisobotda ko'rinadi.
- **Sxema ham shunday:** P3 da bo'sh `receiving_corrections` **o'chirilmaydi** (keyingi boot uni
  qayta yaratadi, faqat yana bir qulf oynasi ochiladi).

### 4.4 To'liq DB restore — faqat halokat

Restore backup'dan KEYINGI barcha savdo, qaytarish va to'lovni **yo'qotadi**. Bu rollback vositasi
EMAS; shartlari va tartibi: `PRODUCTION_OPERATIONS_RUNBOOK.md` §4.3 va §11.

---

## 5. Backup / restore: nima bor, qanday tekshiriladi, RPO/RTO

**Artefakt tarkibi** (`db-backup.yml`, har kuni 22:30 UTC + qo'lda):
`savdoos-<UTC>.dump.gpg` (AES256, `pg_dump -Fc`, `public` VA `cash`), `*.sha256`, `*.meta.json`
(ichida `sha256_encrypted`, `encrypted_size_bytes`, `capture_quiescent`, pg versiyasi, sxemalar
ro'yxati; **ulanish satri YO'Q**), `fingerprint.json` va `fingerprint-before.json`.
Ochiq dump ish jarayonida o'chiriladi va artefaktga CHIQMAYDI.

**Nega shifrlash majburiy:** dump — BUTUN production bazasi (barcha do'konlarning mijozlari,
telefonlari, qarzlari, naqd ledgeri). `actions:read` huquqiga ega har qanday token artefaktni
yuklab oladi. **Parol parol menejerida** — u yo'qolsa nusxa ochilmaydi.

**Barmoq izi ikki marta olinadi** (dumpdan oldin va keyin). Ikkalasi bir xil bo'lsa
`capture_quiescent=true` — barmoq izi shu dump uchun ANIQ; farq bo'lsa `false` deb belgilanadi
va JIM o'tkazilmaydi.

**Tekshirish zanjiri** (`restore_from_artifact.sh` → `restore_rehearsal.sh`):
tarkib → metadata → **shifrlangan** checksum (parolsiz, ochishdan OLDIN) → shifrni ochish →
ochiq checksum → rollar → `pg_restore` → `cash` sxemasi va FK soni → capture-time barmoq izi
bilan solishtirish → `RESTORE_REHEARSAL_OK`. So'ng ilova smoke'i HAQIQIY ishga tushish
ketma-ketligini takrorlaydi: `python -m app.initdb` → `uuid` migratsiyasi (aniq qadam) →
`/health/ready`.

**Saqlash muddati:** kunlik 14 kun · yakshanba 56 kun · oyning 1-kuni 180 kun.

| | Maqsad | Asos |
|---|---|---|
| **RPO** (yo'qotiladigan ma'lumot) | **≤ 24 soat** | backup sutkada bir marta olinadi (22:30 UTC) |
| **RTO** (tiklanish vaqti) | **≤ 4 soat** | artefaktni yuklab olish + `pg_restore` + tekshiruv |

Deploy oynasining RPO'ga ta'siri: D1 dagi backup **deploydan oldingi** holatni qat'iy qayd etadi,
D8 dagi backup esa yangi sxemani. Ikkalasi olinmagan bo'lsa deploy BOSHLANMAYDI/TUGALLANMAYDI.
Kengroq kontekst va yaxshilash yo'llari: `PRODUCTION_OPERATIONS_RUNBOOK.md` §5.

---

## 6. Pilot kanal siyosati (deploy shuni MUMKIN qiladi, YOQMAYDI)

Deploy tuzatish marshrutini va kassa custody blokini ochadi — lekin **partiya kuzatuvi hali
yoqilmagan** (`SAVDOOS_LOT_ACTIVATION_SCOPES` berilmagan, boot jurnali `rejim=closed`).
Aktivatsiyadan keyin amal qiladigan qoida — batafsil
`BINOS_LOT_ACTIVATION_RUNBOOK.md` §2.13, §2.13.1–2.13.3 va §6 da, bu yerda faqat sarlavhasi:

- kuzatuvli mahsulotning omboriga tovar **FAQAT** Manager'ning partiyani biladigan kirimi bilan
  kiradi (`POST /receiving/commit`, har qatorda `lots`); hujjatni keyin o'zgartirish **FAQAT**
  `POST /receiving/{id}/corrections` bilan;
- **mobil kirim** (`lots` yubormaydi) — 400; **menejer xaridi** `POST /purchases` va uning
  `PATCH` tahriri — 409; **filiallararo ko'chirish** — 409; partiyasiz sanoq/hisobdan chiqarish —
  400; 1C cutover qoldiq moslashtiruvi — 400;
- **ko'p filialli aktivatsiya** — server darajasida yopiq (do'konning BARCHA tirik filiallari
  ro'yxatda bo'lmasa darvoza yopiq);
- hammasi **fail-closed**: rad etilgan yo'l na qoldiq, na partiya, na hujjat qoldiradi. Jim
  zaxira yo'l, avto-«kuzatuvni o'chirish» yoki sun'iy partiya YO'Q.

Bu jadval `apps/server/tests/test_legacy_receiving_gate.py` da bajarilgan test bilan qadalgan.

---

## 7. Bir sahifada: STOP ro'yxati

| Qadam | STOP |
|---|---|
| D0 | 5 s dan uzoq ochiq YOZUVCHI tranzaksiya bor |
| D1 | Backup runi qizil; artefakt bo'sh; `capture_quiescent=false` |
| D2 | `hukm: BLOCKED` (qiymat sinflari) — deploy ham to'xtaydi |
| D3 | `[FATAL] … receiving_corrections` (yoki 5F: `receipt_logos` / `print_jobs`); `build.commit` ≠ SHA; jurnalda `-> uuid` |
| D4 | `/health` ham 200 emas; POS sotuvi yiqildi |
| D5 | `hukm` ≠ READY; `plan_sha256` farq qiladi; `QULF OLINMADI`; `REJECTED_STATE_CHANGED`; `MASHQ QAYTARILMADI` |
| D6 | `verify: FAILED`; biror readiness check `false` |
| D7 | Smoke jadvalidagi birorta qator bajarilmadi |
| D8 | `RESTORE_REHEARSAL_FAILED`; `CHECKSUM MOS EMAS`; tiklangan bazada readiness yiqildi |
| D9 | `[FATAL]`, takrorlanuvchi 42883, backup runi qizil |
