# OMMAVIY DEMO — PRODUCTION CUTOVER RUNBOOK

> **Holat:** TAYYOR, lekin **BAJARILMAGAN**. Bu hujjat ijro qilinmadi — faqat
> tartib, tekshiruv va qaytish yo'li yozilgan. Production'ga yozuv, deploy,
> worker standby va repointing **ega ruxsatini kutadi**.

Maqsad: ommaviy DEMO do'konni **asosiy production PostgreSQL** ichida alohida
tenant sifatida ishga tushirish. Oddiy BinOS ilovasi, oddiy login — alohida
ilova, PWA yoki server almashtirish **YO'Q**.

---

## 0. DEPLOY TARTIBI (buzilsa — xavfsizlik teshigi)

**AVVAL SERVER KODI, KEYIN MA'LUMOT. Teskarisi — ochiq yozuv huquqi.**

| # | Qadam | Nega shu tartibda |
|---|-------|-------------------|
| 1 | `core/public_demo.py` + `core/deps.py` darvozasi production'ga deploy | Darvozasiz import qilinsa, demo hisobi **yozuv huquqli menejer** bo'lib qoladi |
| 2 | `api/v1/cashops.py` (`kassa.ops`) + `api/v1/shifts.py` (3 marshrut) darvozalari | Ilgari bu uchta yozuv marshruti **ruxsatsiz** edi |
| 3 | `seed.py` → `kassa.ops` ruxsati | `initdb.py:1361` har boot'da katalogni yangilaydi — **DB migratsiyasi KERAK EMAS** |
| 4 | Boot'dan keyin tekshir: `permissions` da `kassa.ops` **bor** | Import `catalog_map()` da shu kodga tayanadi; yo'q bo'lsa import o'zi to'xtaydi |
| 5 | Faqat shundan keyin — ma'lumot importi (§3) | — |
| 6 | Oxirida — ommaviy parolni e'lon qilish (§6) | Probe (§4) yashil bo'lmaguncha **hech kimga bermaslik** |

Tekshiruv (deploy'dan keyin, hali import yo'q):
```bash
curl -s -o /dev/null -w "%{http_code}" https://savdoos-production.up.railway.app/api/v1/health
```

---

## 1. PRODUCTION ZAXIRASI (import'dan OLDIN, majburiy)

1. Tungi avtomatik backup **yetarli emas** — importdan oldin **talab bo'yicha** nusxa olinadi.
2. `BACKUP_PASSPHRASE` amalda ekanini tasdiqlang (kod repo OCHIQ — `RELEASE_SAFETY_RUNBOOK.md` §6).
3. Nusxaning **tiklanishi** sinovdan o'tgan bo'lsin (hajm emas, `pg_restore --list` + bitta jadval sanog'i).
4. Nusxa identifikatorini (vaqt + hajm + SHA) shu runbook'ning ijro jurnaliga yozing.

> ⚠️  `session_replication_role=replica` **TAQIQ**. U FK va append-only tutqichlarini
> o'chiradi (klonda o'lchandi: yetim qatorlar qoldi). Qaytish yo'li — §5.

---

## 2. DEMO WORKER'NI QUIESCE QILISH VA CHECKPOINT (ijro ETILMADI)

Snapshot **izchil** bo'lishi uchun worker yarim tick holatida bo'lmasligi kerak.

```
# 2.1 STANDBY (ARM'ni olib tashlash) — yangi tick BOSHLANMAYDI
#     (demo-prod worker CLI: `_sm_to_standby`)
# 2.2 Joriy tick tugashini KUT + SETTLE_QUIESCE_SECONDS (1800 s) o'tsin
# 2.3 Tekshir:  pending intent YO'Q · sticky incident YO'Q · SAFE verdikt MOS
# 2.4 CHECKPOINT yozib ol:
#       epoch kaliti · oxirgi tick raqami · SAFE balansi · ochiq smena ID'lari
#       · oxirgi inkassa `client_uuid` · heartbeat vaqti (UTC)
```

**Checkpoint = snapshot bilan taqqoslash uchun yagona haqiqat.** Keyingi barcha
sanoq (§3.1 `--expect-*`) **ayni shu snapshotdan** olinadi, checkpointdan emas —
checkpoint faqat *farq bormi* degan savolga javob beradi.

> Worker standby, repointing va qayta ARM — **shu runbook'da BAJARILMAYDI**.
> Qaror variantlari §7 da.

---

## 3. IZCHIL SNAPSHOT VA IMPORT

### 3.1 Snapshot va kutilgan qiymatlar (ayni manbadan)
```bash
# Demo DB (Railway) -> bitta izchil tranzaksiyada
pg_dump --no-owner --no-privileges --serializable-deferrable -Fc \
        -f demo_snapshot.dump "$DEMO_DATABASE_URL"

# Kutilgan qiymatlar AYNI snapshotdan o'qiladi (tiklangan vaqtinchalik DB'dan):
#   sales soni · collection soni · SAFE balansi
```
Bu uchta qiymat `--expect-sales / --expect-collections / --expect-safe` ga beriladi.
**Eskirgan mahalliy nusxa ishlatilmaydi** — gard shuning uchun majburiy.

### 3.2 Import (bitta tranzaksiya, INSERT-only)
```bash
export DEMO_PUBLIC_PASSWORD='<ommaviy parol>'      # CLI'da emas, muhitda
python ops/public-demo/migrate_tenant.py \
  --src "$SNAPSHOT_DSN" --dst "$PROD_DATABASE_URL" \
  --manifest demo_import_manifest.json \
  --expect-sales <N> --expect-collections <N> --expect-safe <X.XX> \
  --demo-phone '+998XXXXXXXXX' \
  --apply
```
Skript o'zi bajaradigan **majburiy** darvozalar:

| Darvoza | Mazmuni |
|---|---|
| manba 1 tenant | aks holda to'xtaydi (satr filtri kerak bo'lmasligi uchun) |
| `--expect-*` mosligi | eskirgan manba importi MUMKIN EMAS |
| katalog xaritasi | `permissions/roles/units/plans` **KOD** bo'yicha remap; nishonda yo'q kod bo'lsa to'xtaydi |
| **global noyob kalit auditi** | `unique_preflight()` — tenant doirasiz (`company_id`/`tenant_id` siz) har noyob indeks bo'yicha manba↔nishon to'qnashuvi; **tekshirilmagan kalitlar ro'yxati chop etiladi** (jim qoldirilmaydi) |
| PK to'qnashuvi | har jadval bo'yicha bo'laklab |
| DEMO hisobi **ayni tranzaksiyada** | xodim + filial + 5 RAD ruxsat + belgi qatori; manifestga tushadi |
| telefon global noyobligi | `ux_employees_phone_pw` — band bo'lsa butun import ROLLBACK |
| commit'dan oldingi 11 validatsiya | cheklar · inkassa · SAFE · 3 yetim tekshiruvi · smena farqi · 4 demo tekshiruvi |

**Biror darvoza yiqilsa — butun import ROLLBACK, nishonda 0 qator** (klonda o'lchandi).

### 3.3 GLOBAL NOYOB KALITLAR — PRODUCTION'DA O'LCHANDI (2026-11-04)

Faqat o'qish tranzaksiyasida (`default_transaction_read_only=on`) production
katalogidan **tenant doirasiz** (`company_id`/`tenant_id` siz) barcha noyob
indekslar o'qildi. Natija — 34 indeks; import uchun ahamiyatlilari:

| Indeks | Ustunlar | Hukm |
|---|---|---|
| `product_barcodes` | **faqat** `pkey` + `ux_barcodes_company_bc` | ✅ **GLOBAL BARCODE INDEKSI YO'Q** — eski `uq_barcode`/`product_barcodes_barcode_key` production'da mavjud emas. Katalog ustma-ust tushsa ham to'qnashuv BO'LMAYDI (production'da allaqachon 12 604 barkod bor) |
| `public.cash_movements.ux_cashmov_client_uuid_all` | `client_uuid` | ⚠️ **GLOBAL** — demo 522 qatorining har biri tekshiriladi (`unique_preflight`) |
| `public.employees.ux_employees_phone_pw` | `phone` | ✅ o'lchandi: `phone_hits = 0` |
| `public.companies.ux_companies_code` | `code` | ✅ `demoprodsm` production'da YO'Q |
| `public.stock_movements` (2 indeks) | `client_uuid[+product_id+type]` | ⚠️ global — preflight tekshiradi (qiymatlar demo UUID'lari) |
| `public.shifts.ux_shifts_cashier_open` · `cash.shifts.sh_one_open_per_account` | `cashier_id` / `cash_account_id` | ✅ demo UUID'lari — to'qnashuv imkonsiz |
| `sync_devices.device_uuid` · `terminals.device_uuid` · `device_tokens.token` · `qr_payments.txn_id` | — | ✅ SKIP jadvallari yoki demo-lokal qiymat |
| `permissions/roles/units/plans.code` | `code` | ✅ CATALOG — ko'chirilmaydi, KOD bo'yicha remap |

**`sales.client_uuid` va `returns.client_uuid` global noyob indeksi production'da
YO'Q** (`db/schema.sql` dagi `UNIQUE` production katalogiga chiqmagan) — ya'ni
2 271 chek bo'yicha to'qnashuv xavfi ham yo'q.

Isbot: `evidence_prod_unique_keys.txt`.

### 3.4 Nega `uq_barcode` tekshirildi
`db/schema.sql:242` da barcode bir vaqtlar **GLOBAL** noyob edi; hozirgi boot uni
do'kon doirasiga ko'chiradi (`initdb.py:489 ux_barcodes_company_bc`) va eski
cheklovni (`product_barcodes_barcode_key`) olib tashlaydi. Demo katalogi **real
katalogdan** olingan (12 601 barkod), production'da esa jonli tenant bor — global
indeks qolgan bo'lsa import o'rtada yiqilardi. `unique_preflight()` buni
**taxmin qilmaydi, nishondagi amaldagi indekslardan o'qiydi.**

---

## 4. IMPORT'DAN KEYINGI ISBOT (probe)

```bash
python ops/public-demo/probe_demo_account.py \
  --base https://savdoos-production.up.railway.app \
  --phone '+998XXXXXXXXX' --password "$DEMO_PUBLIC_PASSWORD"
```
Kutilgan: **15 mutatsiya → 403**, **7 o'qish → 200**, izolyatsiya tekshiruvlari o'tadi.

Qo'shimcha qo'l tekshiruvi:
1. Qo'shni tenant (`fayzan1`) egasi kirib, o'z sanoqlari **O'ZGARMAGAN**ini ko'rsin.
2. Demo kontekstida 100 kunlik tarix, ikki kassa va SAFE balansi ko'rinadi.
3. `POST /auth/logout` demo tokeni bilan → `{"ok":true,"demo":true}`, **boshqa demo sessiyalari tirik**.

---

## 5. QAYTISH YO'LI (rollback)

| Vaziyat | Yo'l |
|---|---|
| Import tranzaksiyasi yiqildi | **Hech narsa kerak emas** — nishonda 0 qator (atomar) |
| Commit bo'ldi, lekin `cash.*` qatorlari hali bog'lanmagan | `rollback_tenant.py --manifest ... --apply` (manifestdagi AYNAN PK'lar) |
| Commit bo'ldi, `cash.*` bog'langan (amalda **shu holat**) | `rollback_tenant.py --quarantine --apply` — do'kon + xodimlar soft-delete, **login YO'Q**; append-only qatorlar joyida qoladi |
| Butun DB falokat | §1 zaxirasidan tiklash |

> PK-rollback `cash_account_openings_attested_by_fkey` tufayli **tuzilmaviy
> imkonsiz** bo'ladi (xodimni o'chirish bloklanadi) — shu bois karantin yagona
> commitdan keyingi yo'l. Manifestdan tashqari qator bo'lsa skript **o'zi to'xtaydi**.

---

## 6. OMMAVIY KREDENSIALNI FAOLLASHTIRISH (eng oxirgi qadam)

1. §4 probe **to'liq yashil** bo'lsin.
2. Parol **hisobotlarda, loglarda va Git'da YOZILMAYDI** — faqat ega kanalida.
3. E'londan keyin 24 soat kuzatuv: `auth_attempts` o'sishi, 429 soni, server CPU.

---

## 7. WORKER — EGA QARORI (bu runbook BAJARMAYDI)

| Variant | Mazmuni | Xavf |
|---|---|---|
| **A. STATIK demo** (tavsiya) | Worker butunlay to'xtatiladi; demo 100 kunlik tarix bilan qoladi | Vaqt o'tishi bilan "bugun" bo'sh ko'rinadi |
| **B. Demo tenantga repointing** | Worker production'dagi demo tenantga yozadi | **Production DB'ga doimiy yozuv**; yangi lock/epoch identifikatori SHART (staging identifikatorini qayta ishlatish TAQIQ); faqat demo tenantga yozishi isbotlanishi kerak |
| **C. Staging'da qoldirish** | Worker eski demo DB'da ishlaydi, production demo — statik nusxa | Ikki haqiqat manbasi; chalkashlik |

B tanlansa: worker **ommaviy demo hisobidan FOYDALANMAYDI** (u yozuv rad etilgan) —
o'zining importdan kelgan kassir/menejer hisobi bilan ishlaydi.

---

## 8. QOLGAN XAVFLAR (ochiq)

| # | Xavf | Holat |
|---|---|---|
| R1 | **Demo katalogi real mijoz (Fayzan) katalogidan olingan** — 7 155 mahsulot nomi va 12 601 barkod ommaga ochiladi; assortiment va narx siyosati ko'rinadi | **EGA QARORI**: katalogni anonimlashtirish yoki ochiq qoldirish. Mijoz **shaxsiy** ma'lumoti (ism/telefon) demoda YO'Q |
| R2 | DB hajmi ~29 MB → ~270 MB (~9×) | Railway disk va backup vaqti tekshirilsin |
| R3 | Umumiy hisobda IP qatlami (10/300) — bitta NAT ortidagi ko'p foydalanuvchi | Xato urinishda bloklanadi; faollashtirgandan keyin kuzatiladi |
| R4 | Demo sessiyalari 12 soat yashaydi; hamma bir xil hisob | Yozuv imkonsiz, lekin o'qish yuklamasi oshadi |
| R5 | Nishonda qo'shimcha jadval bor (`public.ai_requirement`) | Importga ta'siri YO'Q (manbada ham, SKIP'da ham emas — qator ko'chirilmaydi) |
| R6 | Obuna/suspend — `subscriptions` 0 qator, `_is_suspended` `Setting(key='suspended')` ga tayanadi | Obuna yozuvi **kerak emas** (production'da o'lchandi) |

---

## 9. IJRO JURNALI (bo'sh — hech narsa bajarilmagan)

| Vaqt (UTC) | Qadam | Natija | Kim |
|---|---|---|---|
| — | — | — | — |
