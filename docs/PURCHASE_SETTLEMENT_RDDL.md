# R-DDL — kompozit FK OTA-KALIT prerequisite

> Alohida, kichik sxema-bosqichi. **Phase 3 dan OLDIN** va tenant-doiralangan kompozit FK
> talab qiladigan **Phase 6a sxemasidan OLDIN** bajarilishi shart.
> Bola jadvallar (`purchase_settlements`, `creditors`, …) **BU YERDA YARATILMAYDI**.
>
> Dizayn manbasi: `docs/PURCHASE_SETTLEMENT_DESIGN.md` §4.3 (R3), §5.2 (R4), §13.

---

## 1. Nima qo'shildi (va NEGA aynan ikkitasi)

| Indeks | Jadval | Ustunlar | Talab qiluvchi **tasdiqlangan** kelgusi FK |
|---|---|---|---|
| `uq_purchases_company_id` | `purchases` | `(company_id, id)` | `purchase_settlements (company_id, purchase_id) → purchases (company_id, id)` — Phase 3 |
| `uq_employees_company_id` | `employees` | `(company_id, id)` | `creditors (company_id, employee_id) → employees (company_id, id)` — Phase 6a (**A qarori**) |

**Taxminiy ota-kalit QO'SHILMADI.** Revision 3 §4.3 da sanalgan qolgan uchtasi
(`uq_creditors_company_id`, `uq_ps_company_id`, `uq_ps_id_kind`) **yangi** jadvallarda —
ular jadval bilan birga tug'iladi, mavjud jadvalga prerequisite EMAS.

**Nega mavjud indekslar yaramaydi** (1-isbot bilan tekshirilgan):

| Mavjud | Nega yaramaydi |
|---|---|
| `purchases` PK `(id)` | ustunlar mos emas |
| `UNIQUE (company_id, doc_no)` | ustunlar mos emas |
| `ux_purchases_client_uuid` | **QISMAN** (`WHERE client_uuid IS NOT NULL AND deleted_at IS NULL`) |
| `ux_employees_phone_pw`, `ux_employees_client_uuid` | **QISMAN** |

Postgres FK ota tomonida **noyob va qisman bo'lmagan** indeks talab qiladi; aks holda
`ALTER TABLE … ADD FOREIGN KEY` **42830** bilan rad etiladi (6-isbot).

⚠️ **Ma'lumotga xavfsiz:** `id` allaqachon PK, ya'ni `(company_id, id)` **ta'rif bo'yicha**
noyob — indeks dublikat tufayli qurilmay qolishi MUMKIN EMAS. Operator aralashuvi kerak emas.

---

## 2. Mexanizm

| Qatlam | Nima qilindi |
|---|---|
| Model | `Index("uq_…", "company_id", "id", unique=True)` — **fresh** bazada `create_all` quradi |
| Boot | yangi `initdb._ensure_parent_uniques()` — **`_create_all` dan OLDIN** (12-isbot). Jadval hali yo'q bo'lsa **no-op** (`inspect().has_table`); MAVJUD bazada indeksni qo'shadi (`create_all` mavjud jadvalga indeks qo'shmaydi) |
| Registr — nom + noyoblik | `required_schema.REQUIRED_INDEXES` + kuchli tekshiruv (`indisunique` + `indisvalid`) → **halokatli** sinf (pul kafolati) |
| Registr — **shakl** | `required_schema.PARENT_KEY_COLUMNS` + `parent_key_problems()` → ustunlar **va** qisman-emaslik; **`soft_missing`** (tayyorlik QIZIL, boot TO'XTAMAYDI) |
| CHECK registri | **TEGILMAGAN** — `REQUIRED_PG_CONSTRAINTS` faqat `contype='c'`, noyoblik u yerda abadiy «yo'q» bo'lardi (11-isbot) |

**Severity nega ikki xil (ataylab):** noyoblikning O'ZI — pul kafolati sinfi, shu bois
`REQUIRED_INDEXES` orqali **boot'ni to'xtatadi**. Shakl (ustunlar/predikat) esa hozir HECH
NARSA foydalanmaydigan kelgusi FK uchun, shu bois **tayyorlikni qizil qiladi**, ishlab turgan
do'konning boot'ini to'xtatmaydi.

⚠️ **JIMGINA ALMASHTIRISH YO'Q.** Nomi to'g'ri, lekin shakli noto'g'ri indeks **tegilmaydi**
(`IF NOT EXISTS` uni o'tkazib yuboradi) va tayyorlik qizil bo'ladi. `_ensure_parent_uniques`
ichida `DROP INDEX`/`REINDEX`/`ALTER INDEX` **yo'q** — bu 12-isbotda qotirilgan.

---

## 3. 12 ISBOT — natijalar

Fayllar: `apps/server/tests/test_parent_key_prereq_pg.py` (haqiqiy PostgreSQL, `initdb`
**subprocess** bilan real boot) · `apps/server/tests/test_parent_key_prereq_sqlite.py`.

| # | Isbot | Natija |
|---|---|---|
| 1 | joriy sxema inspeksiyasi (mavjud indekslar tegilmagan) | ✅ `test_1_2_3…` |
| 2 | indeks ta'rifi: **nom + ustunlar + noyoblik + predikat** (`pg_get_indexdef`, `indpred IS NULL`, `indkey` → `attname`) | ✅ `test_1_2_3…` |
| 3 | fresh PostgreSQL | ✅ `test_1_2_3…` |
| 4 | upgrade qilingan PostgreSQL (ota-kalitsiz MAVJUD baza → boot qo'shadi) | ✅ `test_4…` |
| 5 | ikkinchi boot idempotentligi (indeks **oid** o'zgarmadi → DROP/CREATE yo'q) | ✅ `test_5…` · SQLite: `test_7b…` |
| 6 | PostgreSQL FK ota-kalit isboti (FK quriladi; indeks olib tashlansa **42830**) | ✅ `test_6…` |
| 7 | fresh SQLite | ✅ `test_7…` |
| 8 | SQLite `foreign_keys=ON` (ILOVANING o'z dvigatelida) | ✅ `test_8…` |
| 9 | SQLite ota-kalit/FK isboti (`constraint failed`, **`mismatch` EMAS**) | ✅ `test_9…` |
| 10 | iflos/zid legacy sxema **jimgina almashtirilmaydi**, tayyorlik qizil | ✅ `test_10…` (qisman va teskari-ustun), SQLite: `test_sqlite_iflos…`; noyob bo'lmagani esa **halokatli**: `test_10b…` |
| 11 | registr INDEKS mexanizmi, `CHECK_DEFINITIONS` EMAS | ✅ `test_11…` |
| 12 | boot tartibi: ota UNIQUE kompozit FK dan OLDIN | ✅ `test_12…` |

**Sezgirlik (RED→GREEN):** implementatsiya `git checkout` bilan qaytarilganda
**10 failed, 2 passed**; implementatsiya bilan **PG 9/9 + SQLite 5/5 yashil**.
(O'tib ketgan 2 ta — `foreign_keys=ON` pragmasi va SQLite FK sinovi; 9-isbot keyin
KUCHAYTIRILDI: ota-kalitsiz SQLite `foreign key mismatch` beradi, ya'ni FK umuman
majburlanmaydi — test endi aynan shuni rad etadi.)

⚠️ **Mahalliy tuzoq:** har PG testi o'z `pgserver` klasterini ochadi; bu mashinada 9 ta
ketma-ket klaster ba'zan `pg_ctl`/`initdb` xatosi beradi (muhit, test mantig'i emas) —
alohida yurgizilganda o'tadi.

---

## 4. Nima QILINMADI

- `purchase_settlements`, `creditors` va boshqa Phase 3/6a jadvallari **yaratilmadi**;
- kompozit FK'lar **qo'shilmadi** (ota-kalit ular uchun TAYYOR, o'zi esa hech narsani majburlamaydi);
- taxminiy ota-kalitlar **qo'shilmadi**;
- deploy **yo'q**, `main` merge **yo'q**, Fayzan SEYFi **yo'q**.
