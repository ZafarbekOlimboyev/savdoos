# SavdoOS — Production Operations Runbook

> Operator qo'llanmasi: **birinchi haqiqiy mijozdan OLDIN** va undan keyin har kuni kerak
> bo'ladigan amallar. Har bo'limda **aniq buyruq** va **nima kutilishi** yozilgan.
>
> Bu hujjat naqd arxitekturasini tushuntirmaydi — u uchun
> [`apps/server/app/db/cash/FRESH_PRODUCTION_LAUNCH.md`](apps/server/app/db/cash/FRESH_PRODUCTION_LAUNCH.md).

---

## 0. Eng muhim ogohlantirish (2026-09-09 holatiga)

**Bugungi kunga bazaning ZAXIRA NUSXASI YO'Q.**

`DB Backup` workflow'i 2026-08-30 dan beri **11 marta** ishga tushgan va **11 marta "success"**
deb belgilangan — lekin **birorta ham artefakt yaratmagan**. Sababi: `PROD_DATABASE_URL` siri
o'rnatilmagan, eski skript esa sir yo'qligida `exit 0` qilardi (ya'ni jimgina muvaffaqiyat).

Bu tuzatildi (endi sir yo'q bo'lsa workflow **yiqiladi**), lekin **sir hali ham o'rnatilmagan**.
Birinchi mijozni qabul qilishdan oldin [§3](#3-zaxira-nusxa-backup) ni bajaring.

---

## 1. Muhitlar topologiyasi

### Bugun (haqiqiy holat)

| | |
|---|---|
| Railway loyiha | `trustworthy-enchantment` |
| Servis | `savdoos` (backend) |
| Baza | `Postgres-d29B` |
| Ochiq manzil | `https://savdoos-production.up.railway.app` |
| Muhitlar soni | **bitta** |
| POS avto-yangilanish | `ZafarbekOlimboyev/savdoos-pos-releases` |
| Manager avto-yangilanish | `ZafarbekOlimboyev/savdoos-manager-releases` |

Ya'ni **dev, demo/test va kelajakdagi haqiqiy production BITTA bazada aralashgan**. Hozir
u yerda demo tenantlar bor: `fayzan`, `oltin`, `baraka`, `chinor`, `sinov`, `test879`, `normtest`.

### Maqsad (minimal, uchta muhit)

| Muhit | Ma'lumot | Baza | Backup |
|---|---|---|---|
| **DEV** | dasturchi mashinasi, tashlab yuboriladigan | lokal SQLite (`run.bat`) | shart emas |
| **STAGING** | FAQAT demo/test tenantlar, reliz sinovi, migratsiya mashqi | alohida Postgres | shart emas |
| **PRODUCTION** | FAQAT haqiqiy mijozlar | alohida Postgres | **majburiy** |

**Muhim topilma:** staging mijoz build'i uchun **kod o'zgartirish KERAK EMAS**.
[`packages/shared/src/lib/api.ts:6-9`](packages/shared/src/lib/api.ts#L6) allaqachon
`VITE_API_URL` bilan bekor qilishga ruxsat beradi:

```bash
VITE_API_URL=https://savdoos-staging.up.railway.app npm run dist:pos
```

> ⚠️ Staging POS'ni production API'ga ulab qo'ymaslik uchun staging build'ni **boshqa nom bilan**
> yig'ing va **boshqa mashinaga** o'rnating. Staging build'ni avto-yangilanish reliz repolariga
> **CHIQARMANG** — aks holda haqiqiy kassalar staging build'ga yangilanib ketadi.

### STAGING yaratish rejasi (hali bajarilmagan)

1. Railway'da yangi **environment**: `staging` (yoki alohida loyiha).
2. Yangi Postgres qo'shing (production bazasini **ULASHMANG**).
3. `savdoos` servisini staging'ga deploy qiling. Env: `DATABASE_URL` (staging), `SECRET_KEY`
   (**production'nikidan BOSHQA**), `APP_ENV=prod`, xohlasangiz `SEED_DEMO=1`.
4. Manager/POS build'lari `VITE_API_URL` bilan staging'ga qaratilsin.
5. Tekshiring: `curl https://<staging>/api/v1/health/ready` → `{"status":"ready"}`.

---

## 2. Production ma'lumot siyosati (PRODUCTION_DATA_POLICY)

> **Production'da faqat haqiqiy mijoz ma'lumoti bo'ladi.**

Yuqoridagi 7 ta tenant haqiqiy mijoz **emas**. Xavfsiz o'tish tartibi — **shu ketma-ketlikda**:

1. Staging muhitini yarating (§1).
2. Demo ma'lumotni staging'ga **ko'chiring/qayta yarating** va u yerda ishlashini tekshiring.
3. **Faqat shundan keyin** production'dan demo tenantlarni olib tashlang.
4. Olib tashlashdan **oldin** to'liq backup oling va uni **tiklab ko'ring** (§4).

> ❗ Bu runbook demo tenantlarni o'chirish buyrug'ini **ataylab bermaydi**. O'chirish — qaytarib
> bo'lmaydigan amal va u alohida, tasdiqlangan topshiriq bo'lishi kerak.

---

## 3. Zaxira nusxa (backup)

### 3.1 Yoqish — BIR MARTALIK, BIRINCHI MIJOZDAN OLDIN

**IKKITA sir kerak. Ikkalasisiz backup OLINMAYDI (workflow ataylab yiqiladi).**

1. Railway → loyiha → `Postgres-d29B` → **Connect** → `DATABASE_URL` ni nusxalang.
2. GitHub → repo → **Settings → Secrets and variables → Actions → New repository secret**
   - `PROD_DATABASE_URL` = yuqoridagi ulanish satri
   - `BACKUP_PASSPHRASE` = uzun tasodifiy parol (nusxa shu bilan AES256 shifrlanadi)

   > ⚠️ `BACKUP_PASSPHRASE` ni **parol menejerida** saqlang. U yo'qolsa **nusxalarni ochib
   > bo'lmaydi** — ya'ni parol ham backup'ning bir qismidir. GitHub sirini keyinchalik
   > **o'qib bo'lmaydi**, faqat almashtirish mumkin.

3. **Actions → DB Backup → Run workflow** (qo'lda bir marta).
4. **Tekshiring:** run tugagach **Artifacts** bo'limi bo'sh **BO'LMASLIGI** kerak.

```bash
gh run list --workflow=db-backup.yml --limit 1
gh api repos/ZafarbekOlimboyev/savdoos/actions/artifacts --jq '.total_count'
```

`total_count` **0** bo'lsa — backup hali ishlamayapti. Davom etmang.

### 3.2 Nima olinadi

Har tun 22:30 UTC (Toshkent ~03:30) — [`.github/workflows/db-backup.yml`](.github/workflows/db-backup.yml):

| Fayl | Mazmuni |
|---|---|
| `savdoos-<vaqt>.dump.gpg` | `pg_dump -Fc --no-owner`, **AES256 bilan shifrlangan** — public va cash sxemalari |
| `savdoos-<vaqt>.dump.sha256` | nazorat summasi |
| `savdoos-<vaqt>.meta.json` | vaqt, hajm, obyektlar soni, sha256, tiklash buyrug'i |
| `fingerprint.json` | jadval sanoqlari + ledger summalari (tiklashni tekshirish uchun) |

Ulanish satri artefakt **ichida saqlanmaydi**.

**Nega shifrlangan:** dump — barcha do'konlarning mijozlari, telefonlari, qarzlari va naqd
ledgeri. Loyihaning o'z qoidasi ([`apps/server/BACKUPS.md:49`](apps/server/BACKUPS.md))
ochiq dumpni GitHub artifact'ga qo'yishni **taqiqlaydi**: repo yopiqligi yetarli himoya emas
(`actions:read` huquqli har qanday token uni yuklab oladi). Shu bois artefaktga **faqat**
`.gpg` chiqadi; ochiq fayl ish jarayonida o'chiriladi.

### 3.3 Saqlash muddati

| Qachon | Muddat |
|---|---|
| har kuni | 14 kun |
| yakshanba | 56 kun (~8 hafta) |
| oyning 1-kuni | 180 kun (~6 oy) |

### 3.4 Qo'lda backup olish

```bash
DATABASE_URL='postgresql://...' ./scripts/backup_postgres.sh ./backups
```

### 3.5 Nosozlikni sezish

Backup **yiqilsa** workflow qizil bo'ladi va GitHub repo egasiga email yuboradi
(Settings → Notifications yoqilgan bo'lsin). **Jim muvaffaqiyat endi yo'q.**

> GitHub cron'i repo 60 kun harakatsiz qolsa avto-o'chadi. Oyda bir marta
> Actions sahifasida jadvallar yoqiqligini tekshiring.

---

## 4. Tiklash (restore) va mashq

### 4.1 Avtomatik mashq

[`.github/workflows/restore-rehearsal.yml`](.github/workflows/restore-rehearsal.yml) — har
yakshanba 03:00 UTC:

```
production (FAQAT O'QISH: pg_dump) → checksum → BIR MARTALIK postgres konteyneri
  → pg_restore --exit-on-error → FK/sxema butunligi
  → barmoq izi solishtiruvi → ilova readiness smoke testi
```

Mos kelmasa workflow **yiqiladi** (`RESTORE_REHEARSAL_FAILED`).

### 4.2 Qo'lda mashq

```bash
REHEARSAL_DATABASE_URL='postgresql://...bir_martalik_baza' \
BEFORE_FINGERPRINT=before.json \
  ./scripts/restore_rehearsal.sh backups/savdoos-<vaqt>.dump
```

Skript **production ustiga tiklashdan bosh tortadi**: maqsad `DATABASE_URL` bilan bir xil
bo'lsa yoki URL'da `prod` so'zi bo'lsa — to'xtaydi.

### 4.2a Shifrni ochish

```bash
gpg --batch --passphrase "<BACKUP_PASSPHRASE>" -o savdoos.dump -d savdoos-<vaqt>.dump.gpg
```

Haftalik mashq (§4.1) aynan shu qadamni ham sinaydi — parol noto'g'ri bo'lsa mashq yiqiladi,
ya'ni buni falokat kunida emas, oldindan bilib turasiz.

### 4.3 HAQIQIY falokatda tiklash

> Bu **qaytarib bo'lmaydigan** amal. Avval joriy holatdan backup oling — buzilgan baza ham
> keyinchalik tekshirish uchun kerak bo'lishi mumkin.

1. Railway'da servisni to'xtating (kassalar yozmasin).
2. Artefaktni yuklab oling, shifrni oching (§4.2a), checksum tekshiring:
   `sha256sum -c savdoos-<vaqt>.dump.sha256`
3. **Yangi bo'sh baza** yarating (eskisi ustiga yozmang — dalil yo'qolmasin).
4. `pg_restore --clean --if-exists --no-owner --exit-on-error -d "<YANGI_URL>" savdoos-<vaqt>.dump`
5. `DATABASE_URL` ni yangi bazaga qarating, servisni yoqing.
6. Tekshiring: `curl https://savdoos-production.up.railway.app/api/v1/health/ready`
7. `python -m app.tools.db_fingerprint --json` → `fingerprint.json` bilan solishtiring.

---

## 5. Tiklanish maqsadlari (RPO / RTO)

| | Maqsad | Nima uchun aynan shu |
|---|---|---|
| **RPO** (yo'qotiladigan ma'lumot) | **≤ 24 soat** | backup sutkada bir marta olinadi |
| **RTO** (tiklanish vaqti) | **≤ 4 soat** | artefaktni yuklab olish + `pg_restore` + tekshiruv |

**Halol baho:** bugun RPO **∞** (backup yo'q). §3.1 bajarilgach 24 soatga tushadi.

Yaxshilash yo'llari (kelajak): kuniga bir necha marta backup (RPO → soatlar); Railway'ning
PITR/replikatsiya tarifi (RPO → daqiqalar). Hozirgi bosqich uchun 24 soat/4 soat maqbul —
bitta do'kon, kunlik aylanma cheklangan.

---

## 6. Kuzatuv (monitoring)

### Bugun bor

| Signal | Qayerda | Chastota |
|---|---|---|
| Server tirikmi | [`uptime.yml`](.github/workflows/uptime.yml) → `/api/v1/health` | 15 daqiqa |
| Backup nosoz | `DB Backup` workflow yiqilishi | kunlik |
| Tiklash nosoz | `Restore Rehearsal` yiqilishi | haftalik |
| Test regressiyasi | `CI` workflow | har push |

> ⚠️ `uptime.yml` **tiriklikni** tekshiradi. Baza yiqilsa ham u 200 qaytarishi mumkin edi —
> shu bois `/api/v1/health/ready` qo'shildi (§7). Uptime monitorini **shunga** o'tkazish
> tavsiya etiladi.

### Minimal signallar ro'yxati

| # | Signal | Holat |
|---|---|---|
| A | Ilova javob bermayapti | ✅ `uptime.yml` |
| B | Baza javob bermayapti | ✅ `/health/ready` (503) |
| C | 5xx ko'payishi | ⚠️ Railway loglari — qo'lda |
| D | Ledger yozuvi nosozligi | ✅ 503 + `CASH_LEDGER_UNAVAILABLE` |
| E | `CASH_LEDGER_UNAVAILABLE` | ✅ mijozga baland xato |
| F | Custody nomuvofiqligi | ✅ `CASH_CUSTODY_ACCOUNT_INVALID` |
| G | Dublikat/idempotentlik | ⚠️ `sync_log.status='duplicate'` — qo'lda |
| H | Reconciliation anomaliyasi | ✅ `cash_reconcile_probe` (qo'lda) |
| H2 | Manba bor, ledger legi YO'Q | ✅ `cash_integrity_probe` (qo'lda) |
| I | Offline dead-letter > 0 | ✅ `/fleet/devices` → `queue_not_empty`; kassada bosiladigan ro'yxat |
| J | Smena yopilmadi | ⚠️ qo'lda |
| K | Backup nosozligi | ✅ workflow yiqiladi |
| L | Tiklash mashqi eskirgan | ✅ haftalik workflow |

C/G/J hozircha qo'lda. Birinchi mijoz uchun bu yetarli: bitta do'kon, kunlik ko'zdan kechirish.

---

## 7. Sog'liq endpointlari

| Endpoint | Nima isbotlaydi | Monitoring uchun |
|---|---|---|
| `GET /api/v1/health` | jarayon ko'tarilgan (**bazaga tegmaydi**) | konteyner restart |
| `GET /api/v1/health/ready` | baza + `cash` sxemasi + kritik konfiguratsiya | **xizmat tayyorligi** |

```bash
curl -s https://savdoos-production.up.railway.app/api/v1/health/ready
# {"status":"ready","checks":{"database":true,"cash_schema":true,"config":true}}
```

Tayyor bo'lmasa **503**. Javobda baza nomi/host/versiya **chiqmaydi**.

---

## 7a. Ishga tushish gardlari (fail-closed)

Ilova ATAYLAB **ishga tushmaydi**, agar:

| Shart | Sabab |
|---|---|
| production + `SECRET_KEY` standart | token soxtalashtirish mumkin bo'lardi |
| production + baza **SQLite** | `DATABASE_URL` yo'q/buzilgan — savdolar konteyner ichidagi vaqtinchalik faylga yozilib, har deploy'da **yo'qolardi** |

Ikkinchisi jiddiy tuzatish. Ilgari production FAQAT `DATABASE_URL` satridan aniqlanardi:
Railway'da o'sha o'zgaruvchi yo'qolsa (Postgres uzilsa, havola buzilsa) konteyner
**yiqilmasdan** ko'tarilib, bir vaqtning o'zida vaqtinchalik SQLite'ga yozardi, JWT'ni
manbadagi ochiq kalit bilan imzolardi, `/docs` ni ochardi va **demo do'konni (PIN 1234)**
seed qilardi. Endi Railway muhiti (`RAILWAY_*`) ham production signali hisoblanadi va bu
holat ishga tushishni to'xtatadi — yiqilgan servis jimgina yolg'on ishlaydiganidan afzal.

## 8. Konfiguratsiya auditi

```bash
railway.cmd ssh --service savdoos -- python -m app.tools.config_audit --json
```

Qiymatlar **hech qachon chop etilmaydi** — faqat `PRESENT` / `MISSING` / `UNSAFE_DEFAULT` /
`REVIEW` / `OFF`. Kritik muammo bo'lsa exit kodi **2**.

Kritik kalitlar: `DATABASE_URL`, `SECRET_KEY`, `APP_ENV`, `CORS_ORIGINS`, `SAVDOOS_CASH_MODE`,
`SEED_DEMO`, vendor portali kalitlari.

> `SECRET_KEY` production'da berilmasa ilova **umuman ishga tushmaydi**
> ([`app/main.py:20-27`](apps/server/app/main.py#L20)) — bu ataylab fail-closed.

---

## 9. Qurilma versiyasi va offline navbat

### Muammo

Ilgari server qaysi kassada qaysi build ishlayotganini **bilmasdi**. Buzuvchi naqd relizidan
oldin "hamma kerakli versiyadami?" degan savolga javob yo'q edi.

### Hozir

POS/Manager har 10 daqiqada `POST /api/v1/fleet/heartbeat` yuboradi: versiya, platforma,
**offline navbat** va **dead-letter** sonlari.

```bash
# Operator ko'rinishi (menejer tokeni bilan)
curl -s -H "Authorization: Bearer <token>" \
  https://savdoos-production.up.railway.app/api/v1/fleet/devices | jq .readiness
```

```json
{
  "release_ready": false,
  "active_cash_devices": 3,
  "below_minimum_version": ["dev-abc..."],
  "queue_state_unknown": [],
  "queue_not_empty": ["dev-xyz..."]
}
```

`MINIMUM_POS_VERSION` — [`app/api/v1/fleet.py`](apps/server/app/api/v1/fleet.py) da. Hozir
**0.7.0** (aynan `till_id` yuboradigan birinchi build).

> **Xolislik qoidasi:** server navbat holatini **o'ylab topmaydi**. Xabar bermagan qurilma
> `queue_state_unknown` da turadi va reliz **tayyor emas** deb belgilanadi. "Bilmayman" va
> "bo'sh" aralashtirilmaydi.

### Buzuvchi naqd relizidan oldin

1. `MINIMUM_POS_VERSION` ni yangi versiyaga oshiring.
2. `/fleet/devices` → `readiness.release_ready == true` bo'lguncha **kutig**.
3. `below_minimum_version` bo'sh, `queue_not_empty` bo'sh bo'lsin.

---

## 10. Deploy va rollback

### Deploy

```bash
cd apps/server
railway.cmd up --ci --service savdoos
```

Keyin **darhol**:

```bash
curl -s https://savdoos-production.up.railway.app/api/v1/health/ready
```

### Rollback

Railway → servis → **Deployments** → oldingi muvaffaqiyatli deploy → **Redeploy**.

> ⚠️ Rollback **kodni** qaytaradi, **bazani emas**. Deploy DB migratsiyasi
> (`initdb._ensure_columns`) qilgan bo'lsa — u ustunlar qoladi. Ular **additive + nullable**,
> shu bois eski kod ular bilan ishlaydi.

### Mijoz ilovasi relizi

`CLAUDE.md` dagi tartib. **Avval** §9 tayyorligini tekshiring.

---

## 11. Falokat stsenariylari

| Holat | Belgisi | Birinchi qadam | Keyin |
|---|---|---|---|
| **Backend yiqildi** | `uptime.yml` qizil | Railway → Deployments → loglar | Redeploy; tuzalmasa rollback |
| **Baza yiqildi** | `/health/ready` 503, `database:false` | Railway → Postgres holati | Railway statusi; kutish; oxirgi chora — backupdan yangi bazaga tiklash |
| **Deploy buzildi** | yangi deploy'dan keyin 5xx | **rollback** (§10) | Sababni staging'da qidiring |
| **Migratsiya buzildi** | `initdb` xatosi loglarda | Ustunlar additive — odatda zararsiz | Backupdan **yangi** bazaga tiklab tekshiring |
| **Ledger yozib bo'lmaydi** | `CASH_LEDGER_UNAVAILABLE` (503) | `config_audit` → `SAVDOOS_CASH_MODE`; `/health/ready` → `cash_schema` | Bu **ataylab** to'xtatish: naqd hisobsiz o'tmasin. Rejimni tuzating |
| **Dublikat replay** | `sync_log.status='duplicate'` | Normal — idempotentlik ishlayapti | Ko'p bo'lsa qurilma tarmog'ini tekshiring |
| **POS yo'qoldi/offline** | `/fleet/devices` da `last_seen_at` eski | `queue_not_empty` ga qarang | Qurilma tarmoqqa ulansin — navbat o'zi yuboriladi. **Qurilmani formatlash mumkin emas** — navbatdagi cheklar yo'qoladi |
| **Backup nosoz** | `DB Backup` qizil | Log: sir bormi? baza javob beryaptimi? | Tuzatib, **qo'lda** run qiling. Bir kun ham backupsiz qolmang |
| **Reconciliation anomaliyasi** | smena farqlari | `python -m app.tools.cash_reconcile_probe --json` | Faqat o'qiydi. Natijaga qarab menejer `ADJUSTMENT` qiladi |

> **Qoida:** hech bir stsenariyda avtomatik qaytarib bo'lmaydigan amal bajarilmaydi.
> O'chirish/tiklash — doim odam qarori.

---

## 12. Birinchi mijozni qabul qilish (staging mashqi)

**Avval staging'da to'liq mashq qiling.** Migratsiya vositalari (`cash_backfill`,
`cash_discover`, `cash_provision`) **ishlatilmaydi** — yangi mijoz uchun ular keraksiz.

1. Vendor: kompaniya + `F01` filiali + egasi
2. Egasi Manager'ga kiradi
3. **Kassalar** → `TILL-01`, `TILL-02` (haqiqiy yashiklar soni bo'yicha)
4. Seyf ishlatilsa → `SAFE-01`
5. Kassir xodim yaratiladi
6. POS'ga kirish → kassa tanlash → smena ochish
7. Naqd savdo · karta/QR savdo · qarz to'lovi (**smena ochiq holda**)
8. Xarid · qaytarish · xarajat · inkassa
9. Smenani yopish → farq **0**
10. Manager hisobotlari mantiqiy

**Qabul mezonlari:**

- [ ] Migratsiya buyrug'i ishlatilmadi
- [ ] Tarixiy xaritalash yo'q
- [ ] Kassa (TILL) **taxmin qilinmadi** — har amalda aniq
- [ ] Naqd matematikasi aniq; ledger qatorlari aniq
- [ ] Smena yopilishi mos keldi
- [ ] Offline qayta yuborish sinaldi
- [ ] Backup olindi
- [ ] Tiklash mashqi muvaffaqiyatli
- [ ] Kuzatuv yoqilgan
- [ ] Qurilma versiyasi ma'lum (`/fleet/devices`)

---

## 13. Xavfsizlik

| Nuqta | Holat |
|---|---|
| JWT siri | Production'da standart kalit bilan ilova **ishga tushmaydi** (fail-closed) |
| `/docs`, `/openapi.json` | Production'da **yopiq** |
| CORS | `*` — desktop ilova `file://` (Origin: null) uchun; `allow_credentials` **o'chiq**, auth Bearer header orqali |
| PIN brute-force | Uch qatlamli sliding-window: IP (10/5daq), hisob (12/15daq), do'kon (25/15daq) |
| Vendor portali | Kalit + ixtiyoriy IP-allowlist + ixtiyoriy TOTP 2FA — **ikkalasini ham yoqing** |
| Sirlar | `.env`, `*.db` `.gitignore` da; backup artefakti ulanish satrini **saqlamaydi** |
| Tenant izolyatsiyasi | Testlar bilan qoplangan (cross-tenant rad etiladi) |

**Tavsiya:** Railway jamoa kirishini kamaytiring; `PROD_DATABASE_URL` ni faqat GitHub Actions
sirida saqlang; vendor portali uchun 2FA + IP cheklovini yoqing.

---

## 14. Aloqa / eskalatsiya

| Rol | Kim | Aloqa |
|---|---|---|
| Texnik egasi | _to'ldiring_ | _to'ldiring_ |
| Zaxira | _to'ldiring_ | _to'ldiring_ |
| Railway hisobi | _to'ldiring_ | _to'ldiring_ |
| GitHub tashkiloti | `ZafarbekOlimboyev` | — |

---

## 15. Kunlik / haftalik / oylik ro'yxat

**Kunlik:** `DB Backup` yashilmi va artefakt bormi · `uptime.yml` yashilmi

**Haftalik:** `Restore Rehearsal` yashilmi · `/fleet/devices` — eski versiyali kassa bormi ·
`queue_not_empty` bo'shmi

**Oylik:** `config_audit` · `cash_integrity_probe` · GitHub cron jadvallari yoqiqmi ·
qo'lda tiklash mashqi · kontaktlar yangimi
