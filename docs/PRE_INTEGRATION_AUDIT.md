# INTEGRATSIYADAN OLDINGI AUDIT — 5 MASALA

**Sana:** 2026-10-01 · **Rejim:** FAQAT O'QISH
Push / merge / deploy **YO'Q** · history rewrite **YO'Q** · secret/config mutatsiyasi **YO'Q**
Hech bir jarayon o'ldirilmadi, hech narsa o'chirilmadi.

---

## 1. P9 RUNTIME TIP SHA

**`0c53888934cf206ae479f29433e5706455bc7f88`**

Zanjirning har bir commiti tekshirildi (`apps/`, `packages/`, `infra/`, `scripts/`, `db/`,
`integrations/`, `.github/` — testlardan tashqari):

| Commit | Turi | Tegilgan runtime fayllari |
|---|---|---|
| `779cb42` | **RUNTIME** | `api/v1/sync.py`, `core/error_codes.py`, `services/sales.py` |
| `73e2fc0` | hujjat | — |
| `e78319d` | test | — |
| `9e5d037` | **RUNTIME** | `services/sales.py`, `lib/serverErrors.ts` |
| `115c85e` | hujjat | — |
| `f147557` | **RUNTIME** | `api/v1/cashops.py`, `lib/serverErrors.ts` |
| `9fe40d5` · `43152e6` | hujjat | — |
| **`0c53888`** | **RUNTIME (oxirgi)** | `services/sales.py` |
| `e0eeefa` · `fdd9fa7` · `00dd208` · `fd2d765` · `27a34c2` | hujjat / test | — |

**Tasdiq:** `git diff 0c53888 27a34c2 -- apps/server/app/ packages/shared/src/ …` → **bo'sh**.
Ya'ni `0c53888` dan keyin runtime mazmuni **aynan o'zgarmagan**.

`0c53888` dan keyin qo'shilgani: `tests/cash/test_p9_06_stale_shift_lock.py` (+366) va
uch hujjat (+720). Jami 4 fayl, 1086 qator — hammasi test/hujjat.

## 2. `27a34c2` — REPORT-ONLY

**HA, faqat hujjat.**

```
docs/P9_CHAIN_SUMMARY.md | 254 +++++
1 file changed, 254 insertions(+)
```

Runtime/production yo'llari diff'i: **bo'sh**. Boshqa fayl tegilmagan.

## 3. P9-06 — YAKUNIY DISPOZITSIYA

**Documented hardening backlog. Yangi kod o'zgarishi QILINMADI.**

Saqlanadigan xulosa (o'zgarmaydi):
- eskirgan ORM mexanizmi **isbotlangan** (SQLAlchemy 2.0.52, haqiqiy PG o'lchovi);
- kuzatiladigan writer oqibati **yetib bormaydi** (barcha yozuvchilar ORM obyektini qulfdan
  oldin tashlaydi, identity-map zaif; sotuv yo'li bundan tashqari 3A qulfi bilan himoyalangan);
- kod o'zgarishi **asoslanmaydi**.

Kodda qayd: `tests/cash/test_p9_06_stale_shift_lock.py::test_g…` — `xfail(strict=True)`.
Tuzatish kelajakda qo'shilsa u **XPASS** berib markerni olib tashlashni o'zi aytadi.

## 4. HOZIRGI `origin/main`

**`030258d2c1f817fb9180514e3a416e80a1dfc120`**
`030258d  2026-10-01 15:25:19 +0600  Put the secret boundary where GitHub will accept it`

## 5. P8.1 DEPENDENCY — **BAJARILGAN**

Brief nomlagan P8.1 integratsiya nomzodi `030258d…` — **`origin/main`ning AYNAN O'ZI**.

| Tekshiruv | Natija |
|---|---|
| `030258d` `origin/main` ajdodimi | **HA** — va u main'ning **tepasi** |
| `030258d` qaysi ref'larda | `origin/main`, `origin/HEAD`, `integration/p8.1-with-calendar-fix`, `merge/p81-to-main`, `ci-proof/p81-calendar-030258d` |
| Eski baza `09a2eac` | endi main tarixida (ajdod) — **P9 unga qayta merge qilinmaydi** |

**→ `BLOCKED ON NEW MAIN BASE` holati YUZAGA KELMADI.** P8.1 main'ga kirgan.

## 6. P9 INTEGRATSIYASI — **HOLD**

Sabab: **ega ko'rsatmasi** («hozircha main'ga merge QILMA»), dependency emas.

Texnik holat (integratsiya boshlanganda kerak bo'ladi):

| | |
|---|---|
| P9 zanjiri va main merge-base | `d916b9b` (2026-09-28, Phase 6A preflight) |
| main'da P9 da yo'q commitlar | **17** |
| P9 da main'da yo'q commitlar | **20** |
| main'ning 17 commiti **runtime** ga tegganmi | **YO'Q** — `apps/server/app/` + `packages/shared/src/` diff'i **bo'sh** |

Ya'ni main'ning qo'shgani — workflow / release-safety / hujjat / test (P8 + P8.1 + kalendar
tuzatishi). **Runtime yo'llarida konflikt kutilmaydi**; qayta integratsiya yangi baza
**`030258d`** ustiga qilinishi kerak, `09a2eac` ustiga EMAS.

---

## 7. OCHIQ REPO TA'SIRI — FAKTLAR

### 7.1 Repo

| | |
|---|---|
| Repo | `ZafarbekOlimboyev/savdoos` |
| Ko'rinish | **PUBLIC** (`isPrivate: false`) |
| Yaratilgan | 2026-08-17 |

CLAUDE.md esa «kod repo yopiq qoladi» deb yozilgan — **hujjat va haqiqat ziddiyatda**.

### 7.2 Production dump artefaktlari (git'da emas — GitHub Actions artefaktlari)

`db-backup.yml` → `_db-backup-core.yml`:

| | |
|---|---|
| Manba | `secrets.PROD_DATABASE_URL`, GitHub Environment **`production`** |
| Jadval | `cron: 30 22 * * *` (har kuni 22:30 UTC) |
| Mazmuni | `pg_dump -Fc` — **sxema + ma'lumot**, `public` + `cash` sxemalari |
| Artefakt nomi | `savdoos-db-<tier>-<run_id>` |
| **Muddati o'tmagan artefaktlar** | **20+ ta**, har biri ~2.17 MB |
| Eng yangisi | **2026-10-01** (bugun) |
| Eng uzoq muddati | **2026-12-30** |

**Artefakt ichida nima SHIFRLANGAN:**
- `*.dump.gpg` — AES256, `secrets.BACKUP_PASSPHRASE`
- `fingerprint.json.gpg`, `fingerprint-before.json.gpg` — **mening auditimdan KEYIN shifrlangan**
  (workflow sarlavhasi bu tuzatishni ochiq qayd etadi)

**Artefakt ichida nima OCHIQ qoladi:**
- `*.meta.json` — ulanish satri **YO'Q** (skript sarlavhasida talab sifatida yozilgan va
  tekshirildi); bor: hajm, checksum'lar, PG versiyasi, sxemalar ro'yxati,
  `environment: production`, `capture_quiescent`
- `*.sha256` — **ochiq (shifrlanmagan) dump'ning** nazorat summasi

### 7.3 Eng o'tkir texnik nuqta

Shifrlangan dump yonida **ochiq dump'ning sha256'i** yotadi. Bu — parolga offline hujum
uchun **tekshiruv orakuli**: hujumchi parol variantini sinab, ochilgan faylning sha256'ini
shu qiymat bilan solishtiradi va muvaffaqiyatni **aniq biladi**. Yagona umumiy parol
(`BACKUP_PASSPHRASE`, audit bo'yicha staging bilan bo'lishilgan) bunda sezilarli
kuchsizlanadi. Bir marta yuklab olingan shifrmatn **qaytarib olinmaydi**.

### 7.4 Credential / token / secret

| Qayerda | Natija |
|---|---|
| Artefakt `meta.json` | ulanish satri **YO'Q** (tasdiqlandi) |
| HEAD (`origin/main`) — DSN+parol naqshi | **0 moslik** |
| HEAD — `ghp_` / `github_pat_` / `AKIA…` / PRIVATE KEY | **0 / 0 / 0 / 0** |
| HEAD — `railway.app` | 46 moslik / 26 fayl — bu **ommaviy** backend hostnomi (CLAUDE.md'da ham), sir emas |
| Dump ichida | butun production DB → `employees.password_hash`, sozlamalar; **shifrlangan** |

### 7.5 PII / mijoz ma'lumoti

| Qayerda | Natija |
|---|---|
| Dump ichida | **HA** — mijozlar (ism/telefon), sotuvlar, xodimlar. **Shifrlangan**, lekin ochiq yuklab olinadi |
| HEAD — `+998…` raqamlar | 42 moslik / 22 fayl — **hammasi test/seed/demo**, ikkitasi hujjat namunasi (`tools/import_1c.py`, `README_import_1c.md`) |
| Hujjat namunalari | `--phone +998… --password savdo1234` — **credential shaklidagi satr ommaviy hujjatda** (haqiqiyligi tasdiqlanmagan, lekin tekshirilishi kerak) |

### 7.6 Git TARIXI

| Fakt | Holat |
|---|---|
| Production DB **host:port** (`…proxy.rlwy.net:11729`) | 2026-08-29 dan 2026-09-29 gacha tracked; `73bba68` bilan HEAD'dan olindi, **tarixda O'QILADI** |
| O'sha qatorlardagi parol | **PLACEHOLDER** (`u:p`, `user:p`) — ya'ni **manzil oshkor, parol oshkor emas** |
| `apps/server/qa_auth_results.json` | `73bba68` da o'chirildi; blob tarixda qoldi — 10 789 bayt, **0** DSN, **1** telefon, **0** parol/token kaliti |
| HEAD'da o'sha fayl | **YO'Q** ✓ |
| Tarixda `ghp_` / `github_pat_` | **0** |
| Tarixdagi boshqa DSN'lar | placeholder/lokal: `host`, `srv`, `db.example.com`, `somehost.example`, `127.0.0.1`, `localhost`, `10.0.0.5` |
| History rewrite | **qilinmagan** (va men ham qilmadim) |

---

## 8. DARHOL CONTAINMENT TAVSIYASI (bajarilmagan — qaroringiz uchun)

Og'irlik tartibida:

1. **Repo ko'rinishi bo'yicha qaror.** Bu yagona eng kuchli dastak: repo private bo'lsa
   barcha Actions artefaktlari ham o'sha zahoti ommaviy bo'lmaydi. CLAUDE.md allaqachon
   «yopiq» deb yozadi — ya'ni bu niyatni tiklash.
2. **Ochiq `.sha256` ni artefaktdan olib tashlash** (orakulni yopish). `meta.json` dagi
   `sha256_encrypted` tiklash uchun yetarli — ochiq dump checksum'i kerak emas.
3. **`BACKUP_PASSPHRASE` ni rotatsiya qilish** va staging bilan **ajratish**. Eski
   artefaktlar eski parol bilan shifrlangan bo'lib qoladi — shu bois 4-band.
4. **Mavjud muddati o'tmagan artefaktlarni o'chirish** (GitHub API). ⚠️ Allaqachon yuklab
   olingan nusxalar qaytarib olinmaydi — bu xavfni **kamaytiradi, yo'q qilmaydi**.
5. **Backup'ni Actions artefaktidan yopiq saqlashga ko'chirish** (R2/S3/Railway volume) —
   ildiz yechim; artefakt yo'li ommaviy repoda printsipial xavfli.
6. **Production DB manzilini ommaviy deb hisoblash**: himoya manzil sirligiga tayanmasin —
   DB credential rotatsiyasi va Railway TCP proxy cheklovini ko'rib chiqish.
7. **Hujjatdagi namuna parolini tekshirish** (`savdo1234`) — agar biror tenantda haqiqiy
   bo'lsa, almashtirish.
8. **History rewrite — BIRINCHI chora EMAS.** Oshkor bo'lgan narsa *manzil*, credential emas;
   rewrite esa barcha klonlarni buzadi va 322 ta mavjud fork/klonga ta'sir qilmaydi.
   Avval 1–5 bandlar.

---

## 9. POSTGRES YETIMLARI — INVENTARIZATSIYA

⚠️ **Hech biri o'ldirilmadi.** Sanoqlar harakatda (boshqa sessiyalar klaster ochib-yopmoqda);
quyidagi suratga olish vaqti — 2026-10-01 ~21:07.

| | |
|---|---|
| Jami `postgres.exe` | **322** |
| Shundan **postmaster** (`-D` bor) | **52 klaster** |
| Bolalar (`-D` yo'q) | 270 |
| Har bir postmaster'ning ota-si | `cmd.exe` (52/52) |
| O'sha `cmd.exe`larning ota-si | **O'LGAN** → klasterlar **yetim** |

**Klasterlar manbasi bo'yicha:**

| Data directory ildizi | Klaster | Eng eski | Eng yangi | Tasnif |
|---|---|---|---|---|
| `Temp/pytest-of-Developer/pytest-104/legacy_pgNN` | **48** | 2026-09-30 01:41 | 2026-09-30 02:01 | **tasdiqlangan yetim** |
| `Temp/claude/…` | 2 | 2026-09-28 20:17 | 2026-09-28 20:31 | **tasdiqlangan yetim** |
| `Temp/cashpg_test_*` (`tests/cash` `cashenv`) | 2 | 2026-09-29 14:58 | 2026-09-30 01:43 | **tasdiqlangan yetim** |

**Disk izi:**

| | |
|---|---|
| `pytest-104` katalogi | **8 128 MB (8.1 GB)** ← eng katta iste'molchi |
| `cashpg_test_*` (24 katalog) | **1 035 MB** |
| `Temp` umumiy | **24.4 GB** |
| Disk bo'sh | 25.0 GB |

### ⚠️ HOZIR TIRIK YURISHLAR BOR

**3 ta `python -m pytest` jarayoni ishlayapdi** (PID 41732, 38652, 35260 — `-p no:randomly`
flagi bilan, ya'ni **mening yurishlarim emas**, boshqa sessiya). Ular `pytest-524…528`
kataloglariga yozmoqda (oxirgi yozuv 21:05–21:07).

**Shu bois hozir hech qanday tozalash BAJARILMADI.**

### XAVFSIZ TOZALASH REJASI (bajarilmagan)

```
0-qadam  Tirik pytest/python jarayonlari sonini tekshir — NOL bo'lishi SHART.
         (Get-Process python) → bo'sh bo'lmasa TO'XTA.

1-qadam  Har bir yetim postmaster uchun GRACEFUL to'xtatish (taskkill EMAS):
           pg_ctl stop -D "<data_dir>" -m fast
         Faqat quyidagi ildizlar:
           Temp/pytest-of-Developer/pytest-104/legacy_pg*
           Temp/cashpg_test_*   (oxirgi 2 soatda tegilmaganlar)
           Temp/claude/...      (2026-09-28 dagilar)

2-qadam  To'xtaganini tasdiqla: shu data_dir ga tegishli postgres.exe qolmasin.

3-qadam  Faqat shundan KEYIN eskirgan kataloglarni o'chir:
           Temp/pytest-of-Developer/pytest-104        (~8.1 GB)
           Temp/cashpg_test_*  (faqat to'xtatilganlar) (~1 GB)

TAQIQ    pytest-52x (tirik yurishlar) — TEGILMAYDI
TAQIQ    taskkill /F — klaster buzilishi va boshqa sessiya yurishini sindirishi mumkin
KUTILGAN NATIJA  ~9 GB disk bo'shaydi, 52 yetim klaster yopiladi
```

---

## 10. KEYINGI ANIQ AMAL

**Men hech narsa qilmayman — to'xtadim.** Sizdan bitta qaror kerak, qolganlari undan keladi:

> **Repo ko'rinishi: PUBLIC qoladimi yoki PRIVATE ga o'tadimi?**

Bu javob 8-bo'limdagi 1–5 bandlarning tartibini belgilaydi. Qolgan ikki navbatdagi ish
mustaqil va kutishi mumkin:

- **P9 integratsiyasi** — HOLD (sizning ko'rsatmangiz). Boshlanganda: yangi baza
  **`030258d`**, runtime tip **`0c53888`**, runtime konflikti kutilmaydi.
- **Postgres tozalash** — tirik yurishlar tugashini kutadi; reja 9-bo'limda, ruxsat bersangiz
  bajaraman.
