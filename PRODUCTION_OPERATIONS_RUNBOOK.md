# SavdoOS — Production Operations Runbook

> Operator qo'llanmasi: **birinchi haqiqiy mijozdan OLDIN** va undan keyin har kuni kerak
> bo'ladigan amallar. Har bo'limda **aniq buyruq** va **nima kutilishi** yozilgan.
>
> Bu hujjat naqd arxitekturasini tushuntirmaydi — u uchun
> [`apps/server/app/db/cash/FRESH_PRODUCTION_LAUNCH.md`](apps/server/app/db/cash/FRESH_PRODUCTION_LAUNCH.md).

---

## 0. Eng muhim ogohlantirish (2026-09-09 holatiga)

**Bugungi kunga bazaning ZAXIRA NUSXASI YO'Q.**

Uchta to'siq ketma-ket ochildi:

1. **Sir yo'q edi.** `DB Backup` 2026-08-30 dan beri 11 marta "success" deb belgilangan,
   lekin birorta artefakt yaratmagan: `PROD_DATABASE_URL` o'rnatilmagan, skript esa
   sir yo'qligida `exit 0` qilardi (jimgina muvaffaqiyat). **Tuzatildi** — endi yiqiladi.
2. **Sirlar o'rnatildi**, ulanish MUVAFFAQIYATLI bo'ldi (`target=railway · pg=18.6 ·
   schemas=cash,public`), lekin dump yiqildi:
   `pg_dump: aborting because of server version mismatch — server 18.6, pg_dump 16.15`.
   **Tuzatildi** — [§3.6](#36-postgresql-versiyasi) ga qarang.
3. **Endi navbat:** backup'ni qayta ishga tushirish va artefakt paydo bo'lganini tekshirish.

Birinchi mijozni qabul qilishdan oldin [§3](#3-zaxira-nusxa-backup) ni oxirigacha bajaring.

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

#### 1-qadam · TO'G'RI ulanish satrini oling

Railway → loyiha → `Postgres-d29B` → **Connect**.

> ⚠️ **Eng ko'p uchraydigan xato.** Railway ikki xil manzil beradi:
>
> | | Ko'rinishi | GitHub Actions uchun |
> |---|---|---|
> | **Ichki** (private network) | `postgres.railway.internal:5432` | ❌ **ISHLAMAYDI** — GitHub runner bu nomni resolve qila olmaydi |
> | **Ochiq** (public proxy) | `<...>.proxy.rlwy.net:<port>` | ✅ **SHU KERAK** |
>
> GitHub runner Railway tarmog'idan tashqarida. Ichki manzil berilsa backup har tun
> "could not translate host name" bilan yiqiladi. Railway'da **"Public Network"** /
> **TCP Proxy** bo'limidagi satrni oling (host `proxy.rlwy.net` bilan tugaydi).

#### 2-qadam · Sirlarni o'rnating (qiymat terminal tarixiga TUSHMASIN)

`gh` CLI so' raganda qiymatni **kiritasiz** — u buyruq satrida yozilmaydi, ya'ni shell
tarixida ham, jarayonlar ro'yxatida ham qolmaydi:

```bash
gh secret set PROD_DATABASE_URL --repo ZafarbekOlimboyev/savdoos
```

```bash
gh secret set BACKUP_PASSPHRASE --repo ZafarbekOlimboyev/savdoos
```

Fayldan o'qish kerak bo'lsa (masalan parol menejeri eksporti), keyin faylni **o'chiring**:

```bash
gh secret set BACKUP_PASSPHRASE --repo ZafarbekOlimboyev/savdoos < passphrase.txt && rm -P passphrase.txt
```

> ❌ `gh secret set NAME --body "<qiymat>"` **ISHLATMANG** — qiymat shell tarixiga tushadi.

`BACKUP_PASSPHRASE` uchun kuchli tasodifiy qiymat:

```bash
openssl rand -base64 48
```

> ⚠️ `BACKUP_PASSPHRASE` ni **parol menejerida** saqlang. U yo'qolsa **nusxalarni ochib
> bo'lmaydi** — ya'ni parol ham backup'ning bir qismidir. GitHub sirini keyinchalik
> **o'qib bo'lmaydi**, faqat almashtirish mumkin.

#### 3-qadam · Nomlar joyidami (qiymat O'QILMAYDI)

```bash
gh secret list --repo ZafarbekOlimboyev/savdoos
```

Ikkala nom ham chiqishi kerak.

#### 4-qadam · Qo'lda ishga tushiring va TEKSHIRING

```bash
gh workflow run db-backup.yml --repo ZafarbekOlimboyev/savdoos --ref main
```

Run tugagach **Artifacts** bo'limi bo'sh **BO'LMASLIGI** kerak.

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

### 3.6 PostgreSQL versiyasi

Production **PostgreSQL 18**. `pg_dump` serverdan **eski** bo'lsa ishlashdan **qat'iy bosh
tortadi** — nusxa umuman olinmaydi.

**Nima bo'lgan edi.** Workflow `postgresql-client-17` ni muvaffaqiyatli o'rnatdi (17.11),
lekin `pg_dump --version` baribir **16.15** berdi. Sababi: Debian/Ubuntu'da `/usr/bin/pg_dump`
haqiqiy binar emas — u `/usr/share/postgresql-common/pg_wrapper` ga symlink va qaysi versiyani
ishga tushirishni **o'zi** hal qiladi. GitHub runner obrazida PostgreSQL 16 oldindan
o'rnatilgani uchun wrapper doim 16 ni tanlardi.

**Xulosa:** mijozni o'rnatish yetarli emas — binar **aniq** ko'rsatilishi kerak.

Endi shunday ishlaydi:

| Qatlam | Nima qiladi |
|---|---|
| [`.github/actions/pg-client`](.github/actions/pg-client/action.yml) | `postgresql-client-18` o'rnatadi, `/usr/lib/postgresql/18/bin` ni PATH oldiga qo'yadi va `PG_BIN` ni beradi. Binar major'ini **tasdiqlaydi**; mos kelmasa yiqiladi. Ikkala workflow ham **shu bitta** qadamni ishlatadi — ular ajralib keta olmaydi. |
| [`scripts/lib/pg_client.sh`](scripts/lib/pg_client.sh) | `PG_BIN` → versiyali katalog → PATH tartibida binarni tanlaydi va `PG_DUMP`/`PG_RESTORE`/`PSQL` ni to'ldiradi. |
| Versiya gardi | Dumpdan **oldin** `server_major` va `pg_dump_major` chop etiladi. `pg_dump_major < server_major` bo'lsa **to'xtaydi** (mijoz yangi bo'lishi — ruxsat). |

Log'da har run boshida ko'rasiz:

```
PostgreSQL · server_major=18 · pg_dump_major=18 · binar=/usr/lib/postgresql/18/bin/pg_dump
```

Railway serverni 19 ga yangilasa: `.github/actions/pg-client` chaqiruvlaridagi `major: "18"`
ni `"19"` ga o'zgartiring. Gard buni aytib turadi — jim qolmaydi.

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

### 4.1a SAQLANGAN ARTEFAKTNI tiklash (eng muhim mashq)

> **Bu — falokat kunida ishlatiladigan yagona yo'l.** Haftalik mashq (§4.1) production'dan
> YANGI dump olib tiklaydi — u tiklash *mexanizmini* isbotlaydi, **artefaktni emas**.
> Artefakt yaroqli ekanini faqat AYNAN o'sha artefaktni tiklab bilish mumkin.

**Actions → Restore Rehearsal → Run workflow** va `backup_run_id` ga DB Backup run
raqamini kiriting. Yoki CLI orqali:

```bash
gh workflow run restore-rehearsal.yml --repo ZafarbekOlimboyev/savdoos --ref main -f backup_run_id=34338652056
```

Ish ketma-ketligi:

```
DB Backup run <id> artefakti
  -> yuklab olinadi (AYNAN o'sha run'dan)
  -> tarkib tekshiriladi (bitta .dump.gpg + .sha256 + .meta.json)
  -> metadata o'qiladi; sha256_encrypted bo'lsa SHIFR OCHILMASDAN tekshiriladi
  -> BACKUP_PASSPHRASE bilan ochiladi
  -> ochiq dump checksum'i solishtiriladi   <- TIKLASHDAN OLDIN
  -> yetishmayotgan rollar yaratiladi
  -> pg_restore --exit-on-error  (BIR MARTALIK postgres:18 konteyneri, localhost)
  -> FK / cash sxemasi tekshiriladi
  -> capture-time barmoq izi bilan solishtiriladi
  -> ilova /api/v1/health/ready -> 200
  -> ochiq dump o'chiriladi (xato bo'lsa ham)
```

**Kafolatlar** (testlar bilan mixlangan):

| Kafolat | Qanday ta'minlangan |
|---|---|
| Artefakt rejimi YANGI dump olmaydi | Alohida job; `backup_postgres.sh` u yerda umuman yo'q |
| Production satri ko'rilmaydi | `PROD_DATABASE_URL` artefakt job'iga BERILMAYDI |
| Maqsad — faqat bir martalik baza | URL qattiq yozilgan `localhost`; skript localhost bo'lmasa RAD etadi |
| Buzuq nusxa tiklanmaydi | checksum tiklashdan OLDIN tekshiriladi |
| Ochiq nusxa qolmaydi | skriptda `trap`, workflow'da `if: always()` tozalash |
| Ochiq dump yuklanmaydi | natija artefaktida faqat kichik JSON'lar |

### 4.1b Nima bilan solishtiriladi (va nima bilan EMAS)

Tiklangan baza **jonli production bilan solishtirilmaydi** — u nusxa olingandan keyin
o'zgargan bo'lishi mumkin va bu **yolg'on nomuvofiqlik** berardi. Solishtirish
artefakt ichidagi **capture-time barmoq izi** (`fingerprint.json`) bilan bo'ladi.

`db-backup.yml` endi barmoq izini dumpdan **oldin ham, keyin ham** oladi. Ikkalasi bir xil
bo'lsa — dump davomida baza o'zgarmagan va `capture_quiescent: true` yoziladi, ya'ni
solishtiruv **aniq**. Farq qilsa `false` bo'ladi va kichik farqlar kutilishi mumkin.

> ⚠️ **Birinchi artefakt (`34338652056`) uchun cheklov.** U eski tartibda olingan: barmoq izi
> dump tugagach ~25 soniya **keyin** yozilgan va `capture_quiescent` maydoni umuman yo'q.
> Demak solishtiruv mos chiqsa — bu **kuchli dalil**, lekin tuzilish bo'yicha **kafolat emas**.
> Keyingi artefaktlarda bu kafolat mavjud.

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

4. **ROLLARNI YARATING — bu qadamni O'TKAZIB YUBORMANG.**

   Rollar **klaster** darajasida yashaydi, baza ichida emas. `pg_dump` GRANT satrlarini
   oladi, lekin rollarning **o'zini olmaydi**. Toza klasterga tiklashda:

   ```
   pg_restore: error: role "cash_posting" does not exist
   ```

   va `--exit-on-error` butun tiklashni to'xtatadi. Ya'ni nusxa bor, lekin u yangi bazaga
   **tushmaydi**. Avval:

   ```bash
   psql -c "DO \$\$ BEGIN
     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cash_posting')  THEN CREATE ROLE cash_posting  NOLOGIN; END IF;
     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cash_app')      THEN CREATE ROLE cash_app      NOLOGIN; END IF;
     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cash_readonly') THEN CREATE ROLE cash_readonly NOLOGIN; END IF;
     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cash_admin')    THEN CREATE ROLE cash_admin    NOLOGIN; END IF;
   END \$\$;" "<YANGI_URL>"
   ```

   > `scripts/restore_rehearsal.sh` buni **avtomatik** qiladi (dump ichidagi GRANT
   > satrlaridan rollarni o'zi topadi). Qo'lda tiklashda esa siz bajarasiz.

5. `pg_restore --clean --if-exists --no-owner --exit-on-error -d "<YANGI_URL>" savdoos-<vaqt>.dump`
6. `DATABASE_URL` ni yangi bazaga qarating, servisni yoqing.
7. Tekshiring: `curl https://savdoos-production.up.railway.app/api/v1/health/ready`
8. `python -m app.tools.db_fingerprint --json` → artefaktdagi `fingerprint.json` bilan
   solishtiring (`--compare`). Farq bo'lsa tiklash **to'liq emas**.

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

## 11a. Demo tenantlarni o'chirish (tenant purge)

> ⚠️ **HAR BIR buyruqda `--environment production` bo'lishi SHART.** `railway.cmd` o'zi
> bog'langan muhitga tayanadi va u boshqa muhit bo'lishi mumkin. Muhitni HAR SAFAR aniq
> ko'rsating — "qaysi muhitga ulangan ekanman" degan taxminga tayanmang.

### Standart rejim — QURUQ SINOV (hech narsa o'chmaydi)

Quruq sinov **baza darajasida faqat-o'qish** tranzaksiyada ishlaydi
(`SET TRANSACTION READ ONLY`): DELETE/UPDATE/DDL urinishi PostgreSQL tomonidan rad
etiladi, trigger o'chirilmaydi, qulf olinmaydi. Bu kod o'qib chiqishga emas,
dvigatel kafolatiga tayanadi.

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code baraka --json
```

### Hisobot nimani ko'rsatadi

| Bo'lim | Ma'nosi |
|---|---|
| `COMPANY` | aniqlangan do'kon (id / code / name) |
| `COVERAGE` | jadvallar tasnifi — **`unclassified` BO'SH bo'lishi SHART** |
| `DEPENDENCIES` | o'chiriladigan qatorlar, jadval bo'yicha |
| `SEMANTIC REGISTRY` | FK bermagan jadvallar: `DEAD_SCHEMA` / `GLOBAL_SHARED` |
| `CONTEXT` | bloklamaydigan ma'lumot (ledger qatorlari, savdo hajmi) |
| `RISK SIGNALS` | haqiqiy mijoz dalillari — **bloklaydi** |
| `VERDICT` | `PURGE_READY` yoki `PURGE_BLOCKED` |

### Nol qoldiq kafolati

Muvaffaqiyatli o'chirishdan keyin **uch qatlam** tekshiriladi va biror qoldiq topilsa
BUTUN tranzaksiya qaytariladi (`TENANT_PURGE_FAILED`):

1. FK grafidan kelib chiqadigan har bir jadval — 0 qator
2. `companies` qatori — yo'q
3. Semantik reyestrdagi `DEAD_SCHEMA` jadvallari — 0 qator

`GLOBAL_SHARED` jadvallar (`roles`, `permissions`, `role_permissions`, `units`,
`brands`, `customer_groups`) **ataylab tegilmaydi**: ularda company ustuni umuman yo'q,
ya'ni ular tenant ma'lumoti emas.

### Texnik xizmat qulfi (faqat `--execute`)

`cash` sxemasidagi append-only triggerlar tranzaksiya ichida vaqtincha o'chiriladi.
Bundan oldin jadvallarga **ANIQ `ACCESS EXCLUSIVE` qulfi** olinadi va `lock_timeout`
qo'yiladi — tizim band bo'lsa purge **kutmaydi, darhol yiqiladi** (fail closed).

O'lchangan xatti-harakat (`test_U`): `ALTER TABLE ... DISABLE TRIGGER USER`
`ShareRowExclusiveLock` oladi; u `INSERT/UPDATE/DELETE` ning `RowExclusive` qulfi bilan
to'qnashadi, ya'ni **boshqa seans trigger o'chiq oynadan foydalana olmaydi** — u kutadi.
Rollback DDL'ni ham qaytaradi. Purge oxirida har bir triggerning holati o'chirishdan
OLDINGI suratga aynan solishtiriladi.

### Ettala eski demo tenant uchun quruq sinov

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code 6195fdba --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code baraka --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code chinor --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code fayzan --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code normtest --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code sinov --json
```

```bash
railway.cmd ssh --service savdoos --environment production -- python -m app.tools.tenant_purge --company-code test879 --json
```

> Ettalasi ham **demo/sinov** ma'lumoti — haqiqiy mijoz emas. Shunga qaramay xavfsizlik
> gardi ba'zilarini `PURGE_BLOCKED` deb belgilashi mumkin (masalan yaqinda savdo bo'lgan
> bo'lsa). Bu **nuqson emas** — gard shunday ishlashi kerak. Hisobotni o'qib, sababni
> ko'rib chiqing.

O'chirish buyruqlari bu hujjatda **ataylab yo'q**: avval ettala quruq sinov hisoboti
ko'rib chiqiladi.

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
