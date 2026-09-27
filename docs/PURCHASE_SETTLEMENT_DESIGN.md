# Xarid to'lovi: SEYF + split settlement — DIZAYN (2-tahrir, adversarial ko'rikdan keyin)

> Holat: **DIZAYN. IMPLEMENTATSIYA QILINMAGAN.** Kod o'zgartirilmagan, migratsiya yozilmagan.
> Production tegilmagan; Fayzan SEYFi ATAYLAB YO'Q holatda qoldirilgan.
> Asos: `PURCHASE_SETTLEMENT_AUDIT.md` + 14 linzali kod auditi + **5 linzali adversarial
> ko'rik** (67 topilma: 14 bloklovchi, 40 jiddiy). 1-tahrirdagi bloklovchi nuqsonlar shu
> hujjatda tuzatildi va har biri «⚠️ 1-tahrirda» belgisi bilan ko'rsatildi.
>
> **Qabul qilingan qaror (2026-09-27):** kompaniyada **BIR NECHTA ega/sherik** bo'lishi
> mumkin. `OWNER_ADVANCE` anonim kompaniya-darajali qarz sifatida modellanmaydi; har oyoq
> `company_id + creditor_id + amount` ni ANIQ olib yuradi. Batafsil — §3.

**Mundarija.** §0 hal qiluvchi zanjir · §1 settlement sxemasi · §2 oyoq identiteti ·
**§3 kreditor identiteti** · §4 majburiyat daftari · §5 qaytarish · §6 TILL validatsiyasi ·
§7 SEYF validatsiyasi va custody domeni · §8 ledger xaritasi · §9 ta'minotchi qarzi ·
§10 atomiklik, qulf, idempotentlik · §11 reversal · §12 SEYF ochilish qoldig'i ·
§13 Manager UX · §14 mobil UX · §15 Purchase Return · §16 migratsiya · §17 testlar ·
§18 bosqichlar · **Ochiq qarorlar (A–L)**

---

## 0. Hal qiluvchi zanjir (eng muhim topilma)

Auditda «Fayzanda SEYF qatori yo'q» deb aytilgan edi. Kod auditi ko'rsatdi: **SEYF yaratish
o'zi kerakli oqimni BERMAYDI.** Zanjir uch bo'g'inli va hozir **uchtasi ham uzilgan**:

| # | Bo'g'in | Hozirgi holat | Dalil |
|---|---|---|---|
| 1 | SEYF qatori mavjud bo'lishi | Fayzanda YO'Q (`{"TILL": 1}`) | production read-only probe |
| 2 | SEYFda **ledger qoldig'i** bo'lishi | **Kiritish NUQTASI YO'Q** | §12 |
| 3 | Ochiq smena SEYFdan to'lovni to'smasligi | `ERR_TILL_SHIFT_MISMATCH` to'sadi | `cutover_guard.py:394-401` |

2-bo'g'in nega o'lim nuqtasi: manfiy naqd qo'riqchisi qoldiqni butun hisob umri bo'yicha
`Σ(IN) − Σ(OUT)` deb hisoblaydi (`repositories.py:77-88`) va **SEYF uchun override MUTLAQO
yo'q**. Ya'ni bo'sh SEYF yaratilsa, undan har qanday to'lov **`INSUFFICIENT_CASH` (409)**
bilan rad etiladi.

> **Faqat SEYF yaratilsa va ochilish qoldig'i kiritilmasa — do'kon egasi «seyf paydo bo'ldi,
> lekin hech narsa to'lay olmayapman» holatiga tushadi.** Tartib: **mexanizm → darvoza →
> ma'lumot** (§18).

**Ko'rik qo'shgan to'rtinchi bo'g'in.** Yozuvchi SEYFni qabul qilsa ham, **o'qish yo'li**
(`preview_cash_custody` → `custody_preview.decide`) domenni bilmasa, ochiq smenada
`SERVER_RESOLVED` + `options=[]` qaytaradi va **Manager ekrani seyfni tanlash imkonini
bermaydi** (§7.2). Ya'ni darvoza server tomonida ochilib, UI tomonida yopiq qolardi.

---

## 1. Sxema taklifi — `purchase_settlements`

Sxema: **`public`** (sabab §16.2). Jadval **append-only** (§11).

```
purchase_settlements
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  purchase_id            uuid NOT NULL
  revision               smallint NOT NULL DEFAULT 0     # ⚠️ YANGI, §2.2
  leg_no                 smallint NOT NULL               # DETERMINISTIK, §2.1
  kind                   varchar(8)  NOT NULL            # PAYMENT | REVERSAL
  source                 varchar(16) NOT NULL            # TILL_CASH | SAFE_CASH | OWNER_ADVANCE
  cash_account_id        uuid NULL                       # faqat *_CASH uchun
  creditor_id            uuid NULL                       # faqat OWNER_ADVANCE uchun, §3
  creditor_name_snapshot varchar(120) NULL               # faqat OWNER_ADVANCE uchun, §3.5
  amount                 numeric(14,2) NOT NULL          # HAR DOIM > 0; ishora `kind`da
  currency               char(3) NOT NULL                # §3.9
  ledger_entry_id        uuid NULL                       # naqd oyoq provenansi, §1.2
  reverses_id            uuid NULL
  created_at             timestamptz NOT NULL
  created_by             uuid NULL -> employees.id
```

⚠️ **1-tahrirda `client_uuid` ustuni bor edi — OLIB TASHLANDI.** Semantikasi ta'riflanmagan
edi va ikki o'qishning ikkisi ham buzilardi: server hujjat `client_uuid`sini har oyoqqa
bossa, ikkinchi oyoq noyob indeksni buzib **split umuman yozilmasdi**; oyoq-per-uuid
kutilsa, na Manager, na mobil shartnomasi bunday uuid bermaydi. Idempotentlik hujjat
darajasida (`ux_purchases_client_uuid`, `ux_receivings_client_uuid`) va §10.3 dagi tabiiy
kalitlar bilan ta'minlanadi.

### 1.1 Qator-lokal CHECK'lar — **FUNKSIYASIZ**

```
ck_ps_amount_pos      amount > 0
ck_ps_kind            kind   IN ('PAYMENT','REVERSAL')
ck_ps_source          source IN ('TILL_CASH','SAFE_CASH','OWNER_ADVANCE')
ck_ps_rev_nonneg      revision >= 0
ck_ps_leg_nonneg      leg_no >= 0
ck_ps_cash_iff        (source IN ('TILL_CASH','SAFE_CASH')) = (cash_account_id IS NOT NULL)
ck_ps_creditor_iff    (source = 'OWNER_ADVANCE')            = (creditor_id IS NOT NULL)
ck_ps_cred_name_iff   (source = 'OWNER_ADVANCE')            = (creditor_name_snapshot IS NOT NULL)
ck_ps_cred_name_nb    creditor_name_snapshot IS NULL OR creditor_name_snapshot <> ''
ck_ps_ledger_iff      (source IN ('TILL_CASH','SAFE_CASH')) = (ledger_entry_id IS NOT NULL)
ck_ps_reversal_iff    (kind = 'REVERSAL')                   = (reverses_id IS NOT NULL)
ck_ps_no_self_rev     reverses_id IS NULL OR reverses_id <> id
```

⚠️ **1-tahrirda `btrim(...) <> ''` ishlatilgan edi — BU BLOKLOVCHI NUQSON.** Ikki mustaqil
sabab:

1. **SQLite'da `btrim` YO'Q** (faqat `trim`). SQLite CHECK ifodasidagi funksiyani **jadval
   yaratish paytida** hal qiladi, ya'ni cheklov «majburlanmaydi» emas — **jadval umuman
   yaratilmaydi**, `_create_all` istisnoni qayta ko'taradi va **boot FATAL** bo'ladi. Natija:
   `run.bat` (mahalliy SQLite) va butun SQLite to'plami model qo'shilgan zahoti ishga
   tushmasdi. (Ko'rikda o'lchandi: `CHECK (btrim(name) <> '')` → `no such function: btrim`.)
2. **`check_canon` grammatikasi HAR QANDAY funksiya chaqiruvini rad etadi**
   (`check_canon.py:422-425` — «funksiya yoki malakali nom qo'llab-quvvatlanmaydi»).
   Funksiyali CHECK `CHECK_DEFINITIONS` ga qo'shilsa `test_check_canon.py:36-38` darhol
   yiqiladi, ish vaqtida esa `CHECK_DEF_UNPARSED` → `/health/ready` **abadiy QIZIL**;
   qo'shilmasa — u §16.3 taqiqlagan «jimgina zaiflashtirilishi mumkin» CHECK bo'lib qoladi.

Shu bois **barcha CHECK ifodalari funksiyasiz**. Bo'sh joy normalizatsiyasi **xizmat
qatlamida** bajariladi, noyoblik esa saqlangan `name_key` ustuni bilan (§3.2) — ifoda
indeksi ham kerak emas. Mantiqiy-tenglik shaklidagi CHECK'lar
(`(a IN (...)) = (b IS NOT NULL)`) `check_canon` dan **o'tadi** (ko'rikda o'lchandi).

> **NULL semantikasi:** `source` va `kind` `NOT NULL`, shu bois tenglik shaklidagi CHECK'lar
> uchlik mantiqqa tushmaydi. Bu ataylab: nullable ustun ustida bunday CHECK **NULL →
> UNKNOWN → qabul** bo'lib fail-open bo'lardi.

### 1.2 Indekslar va kompozit kalitlar

```
ux_ps_leg         UNIQUE (purchase_id, leg_no)
ux_ps_cash_party  UNIQUE (purchase_id, revision, cash_account_id) WHERE kind='PAYMENT' AND cash_account_id IS NOT NULL
ux_ps_cred_party  UNIQUE (purchase_id, revision, creditor_id)     WHERE kind='PAYMENT' AND creditor_id IS NOT NULL
ux_ps_reverses    UNIQUE (reverses_id) WHERE reverses_id IS NOT NULL
ix_ps_purchase    (purchase_id)
ix_ps_creditor    (creditor_id) WHERE creditor_id IS NOT NULL

-- kompozit FK'larni qo'llab-quvvatlovchi noyobliklar (cash sxemasi naqshi):
uq_ps_company_id  UNIQUE (company_id, id)
uq_ps_id_kind     UNIQUE (id, kind)
uq_ps_id_amount   UNIQUE (id, amount)

-- tenant va o'zgarmaslik invariantlari FK bilan:
fk_ps_purchase_same_company  (company_id, purchase_id) -> purchases(company_id, id)
fk_ps_creditor_same_company  (company_id, creditor_id) -> creditors(company_id, id)   -- MATCH SIMPLE
fk_ps_reversal_same_amount   (reverses_id, amount)     -> purchase_settlements(id, amount)
```

⚠️ **Uch tuzatish 1-tahrirga nisbatan:**

- **Indeks sinfi.** 1-tahrir bu indekslarni `OPTIONAL_UNIQUE` sinfiga qo'ygan edi — lekin u
  **faqat jurnal** sinfi: indeks qurilmasa `/health/ready` yashil qoladi va hech qaysi
  darvoza yopilmaydi. Ayni paytda §10.3 ularni «ikkinchi to'lovni to'sadigan DB kafolati»
  deb sanaydi — ikki da'vo bir-birini yo'q qiladi. Jadvallar **yangi va bo'sh** bo'lgani
  uchun boot ularni xavfsiz qura oladi, shu bois pul kafolatini ko'taruvchi indekslar
  (`ux_ps_leg`, `ux_ps_cash_party`, `ux_ps_cred_party`, `ux_ps_reverses`,
  `ux_cr_client_uuid`, `ux_caa_pair`, `ux_creditors_name_key`, `ux_cl_advance`,
  `ux_cl_repayment`) **`REQUIRED_INDEXES`** sinfiga qo'yiladi. Faqat tezlik indekslari
  `PERFORMANCE` da qoladi.
- **Qismiy indeks ikki dialektda.** Modelda faqat `postgresql_where=` berilsa, SQLAlchemy
  SQLite uchun indeksni **shartsiz** chiqaradi — `ux_ps_cash_party` shartsiz
  `UNIQUE (purchase_id, revision, cash_account_id)` bo'lib, mahalliy to'plamda REVERSAL
  oyog'ini ham to'sib qo'yardi. Shart: har qismiy indeks yo modelda **`postgresql_where=`
  VA `sqlite_where=`** (ayni matn) bilan, yo `_ensure_indexes` da xom
  `CREATE UNIQUE INDEX ... WHERE ...` bilan (ikki dialektga ham) e'lon qilinadi.
- **`revision` o'lchovi** — §2.2.

**`ledger_entry_id` FK'mi?** 1-tahrirda u yolg'iz `uuid NULL` edi, ya'ni CHECK faqat
NOT NULL ni sinardi va **istalgan qiymat** o'tardi. Ikki yo'l bor, bu **K-savol**:
(a) haqiqiy cross-schema FK `-> cash.cash_ledger_entries(id)` — `cash` sxemasiga
`REFERENCES` granti kerak; (b) FK'siz mantiqiy havola — `purchases.cash_account_id` naqshi
(`purchasing.py:41-43`, cross-schema sababli ataylab FK'siz). Tavsiyam: **(b)**, lekin
xizmat qatlamida yozilgan `ledger_entry_id` **faqat shu tranzaksiyada yaratilgan** qatordan
olinadi va §17 C-25 shu invariantni sinaydi.

**`SUPPLIER_DEBT` settlement manbasi EMAS** — to'lanmagan qoldiq hosila (§9).

---

## 2. Settlement oyog'ining identiteti va idempotentligi

Naqd ledger biznes kaliti oyoq indeksini ko'taradi:
`cle_uq_business UNIQUE (tenant_id, source_type, source_id, leg_index)`
(`cash_ddl_v1.sql:232`). Split oyoqlar **mavjud identitetda** qoladi (yangi
`cash_source_type` label QO'SHILMAYDI — §16.1):

```
source_type = 'PURCHASE'   ·   source_id = purchase.id
leg_index   = purchase_settlements.leg_no
category    = 'PURCHASE_OUT'
```

Presedent: `on_cash_purchase_increase` ayni `source_id` ostida ikkinchi OUT legni **boshqa
hisobga** yozadi (`retrofit.py:400-427`).

### 2.1 `leg_no` determinizmi

```
party      = COALESCE(cash_account_id, creditor_id)   # AYNAN bittasi NOT NULL
source_rank: SAFE_CASH=0, TILL_CASH=1, OWNER_ADVANCE=2
kanonik tartib = sort by (revision, source_rank, party::text)
leg_no = shu tartibdagi indeks
```

⚠️ **1-tahrirda tartib `(source_rank, cash_account_id)` edi — NUQSON:** `OWNER_ADVANCE` da
`cash_account_id` NULL, ya'ni ikki xil sherikning avans oyoqlari ayni saralash kalitiga
tushib, `leg_no` noaniq bo'lardi. `party` to'liq tartib beradi, chunki `ux_ps_cash_party` /
`ux_ps_cred_party` bir revizyada bir `party` ni takrorlanmas qiladi. `::text` — repo
konvensiyasi (`sorted(..., key=str)`: `receiving.py:270`, `purchases.py:352`,
`posting.py:188`); shu sabab **PK turi uuid bo'lishi SHART**.

**E'lon qilingan shart (1-tahrirda yo'q edi):** PAYMENT oyoqlari **faqat hujjat
yaratilishida bitta atomik to'plam sifatida** yoziladi. Mavjud hujjatga keyin oyoq
**qo'shilmaydi** — aks holda `source_rank(SAFE)=0` yangi SAFE oyog'ini `leg_no=0` ga
majburlab, band kalitga urilardi. Keyingi har qanday o'zgarish — **REVERSAL + replacement
revizyasi** (§2.2).

### 2.2 `revision` — tuzatish yo'lini ISHLAYDIGAN qiladi

⚠️ **1-tahrirdagi bloklovchi nuqson:** `ux_ps_cred_party`/`ux_ps_cash_party` qisman
predikati faqat `kind='PAYMENT'` bo'yicha filtrlab, **bekor qilingan** PAYMENT qatorini
istisno qilmasdi. Demak `PAYMENT(A) → REVERSAL → yana PAYMENT(A)` ketma-ketligida asl
(bekor qilingan) qator kalitni egallab turardi va **almashtiruvchi oyoq unique buzilishi
bilan rad etilardi** — ya'ni hujjatning O'ZI tanlagan tuzatish mexanizmi (§9, §11)
strukturaviy ravishda bajarilmasdi. Yagona chiqish yo'li yangi kreditor/hisob yaratish
bo'lardi, bu esa §3.5 atributsiyasini buzardi.

Tuzatish: `revision smallint NOT NULL DEFAULT 0`.

- Hujjat yaratilishi → `revision = 0`.
- Tuzatish → `revision = 0` oyoqlari REVERSAL qilinadi, almashtiruvchi to'plam
  `revision = max(revision) + 1` bilan yoziladi — **hujjat qulfi ostida** (§10.2).
- Revizya raqami takrorda qayta hisoblanmaydi: **tuzatish hujjatining `client_uuid`si**
  idempotentlik kalitidir (`receiving_corrections` naqshi), `leg_no` emas.

### 2.3 REVERSAL oyog'ining `leg_no`si

⚠️ **1-tahrir `max+1` uchun `next_leg_index` ga havola qilgan edi — NUQSON:** u
`cash_ledger_entries` dan o'qiydi (`repositories.py:179-190`), `OWNER_ADVANCE` oyog'i esa
naqd yozuv **yaratmaydi**. §3 misolida (0=SAFE, 1=TILL, 2=OWNER_ADVANCE) ledger max = 1,
demak SAFE yoki TILL oyog'ini qaytarganda `leg_no = 2` chiqib **`ux_ps_leg` buzilardi**.
Yomonlashtiruvchi omil: oyoqlar `commit=False` bilan yoziladi, posting servisining
`IntegrityError→DUPLICATE` o'girishi esa faqat `commit=True` shoxida
(`posting.py:408-416`) — xom `IntegrityError` endpointga chiqib, §2.5 qoidasi bo'yicha
«duplicate» deb **yutilardi**: operator «allaqachon bajarilgan» javobini olardi, reversal
esa hech qachon yozilmasdi.

Tuzatish: `leg_no = max(purchase_settlements.leg_no) + 1` — **shu `purchase_id` doirasida**,
hujjat qulfi ostida. `next_leg_index` settlement uchun **umuman ishlatilmaydi**.

### 2.4 REVERSAL summasi asl summaga TENG

`ck_ps_amount_pos` faqat `amount > 0` ni, `ck_ps_reversal_iff` faqat `reverses_id` ni
tekshiradi — qator-lokal CHECK boshqa qatorni ko'rmaydi, ya'ni **qisman reversal** yozib
qo'yish mumkin edi (bu `unpaid` formulasini jimgina buzardi, §9). Deklarativ tuzatish:
`UNIQUE (id, amount)` + `FOREIGN KEY (reverses_id, amount) REFERENCES
purchase_settlements(id, amount)` — kompozit-FK-invariant naqshi.

### 2.5 Dublikat javobi TANANI solishtirishi SHART

`CashPostingService` dublikatni kalit bo'yicha aniqlaydi, **tanani solishtirmaydi**
(`posting.py:90-94, 424-431`) — boshqa summali so'rov «to'lov allaqachon amalga oshgan»
degan **yolg'on muvaffaqiyat** olishi mumkin. Settlement xizmati qaytgan DUPLICATE
natijaning `amount`/`cash_account_id`/`direction`ini kutilgan oyoq bilan solishtiradi, mos
kelmasa **`SETTLEMENT_CONFLICT` (409)**.

⚠️ **1-tahrirda bu faqat naqd oyoq uchun ta'riflangan edi.** `OWNER_ADVANCE` oyog'i posting
servisiga **umuman bormaydi**, shu bois takror `ux_ps_cred_party` da xom `IntegrityError`
beradi. Shart: **avans oyog'i uchun ham** majburiy tana-solishtirish — `IntegrityError` ni
**constraint NOMI bo'yicha** ajratib, mavjud qatorni o'qib (`amount`, `creditor_id`,
`currency`) solishtirish; mos kelmasa `SETTLEMENT_CONFLICT`.

Mavjud idempotentlik bloklari (`receiving.py:135`, `shifts.py:158`) xato **KODINI
tekshirmaydi** — settlement endpointi bu naqshni **ko'chirmaydi**: faqat nomi ma'lum
noyoblik buzilishlari yutiladi.

---

## 3. KREDITOR IDENTITETI — qaror va sakkiz talab

### 3.0 Qabul qilingan qaror

- Kompaniyada **bir nechta ega/sherik** bo'lishi mumkin.
- `OWNER_ADVANCE` **anonim kompaniya qarzi EMAS**: har oyoq *«BinOS kompaniyasi QAYSI
  SHAXSGA qancha qarzdor?»* savoliga javob beradi. «Kompaniya egalarga 5 000 qarzdor»
  **yaramaydi**.
- Bitta xarid **turli kreditorlardan bir nechta** `OWNER_ADVANCE` oyog'ini ko'tara oladi
  (`ux_ps_cred_party` faqat **ayni** kreditorning **ayni revizyada** takror oyog'ini
  to'sadi).
- Qaytarish **ayni kreditorga** havola qiladi va **faqat shu kreditor** qoldig'ini
  kamaytiradi (§5.2).
- Kreditor **joriy foydalanuvchidan XULOSA QILINMAYDI**.

Misol (brifdan, 30 000 KGS):

| Oyoq | `source` | `party` | `revision` | `leg_no` | Summa |
|---|---|---|---|---|---|
| 1 | `SAFE_CASH` | Asosiy seyf | 0 | 0 | 10 000 |
| 2 | `TILL_CASH` | Kassa #1 | 0 | 1 | 5 000 |
| 3 | `OWNER_ADVANCE` | **Sherik A** | 0 | 2 | 5 000 |
| — | ta'minotchi qarzi (hosila, §9) | — | — | — | 10 000 |

### 3.1 Mavjud modellar auditi — xulosa

**Kanonik party/counterparty modeli repoda YO'Q**; «kreditor/creditor/counterparty» so'zlari
kodda 0 marta uchraydi.

| Nomzod | Mexanik mos? | Semantik mos? | Rad etish sababi (dalil) |
|---|---|---|---|
| `Role.code = "ega"` | — | **YO'Q** | Rol — subyekt emas; **GLOBAL** jadval, `company_id` yo'q (`auth.py:12-35`) |
| `Employee` | ha | **YO'Q** | `delete_employee` moliyaviy tekshiruvsiz soft-delete qiladi (`employees.py:501-533`); rol/`status` beqaror (`:449-479`); har bootda eng eski faol administrator jimgina `ega` ga ko'tariladi (`initdb.py:1354-1380`); xodim bo'lmagan qarz beruvchi ifodalanmaydi |
| `Supplier` | ha | **YO'Q** | «tur» ustuni yo'q (`purchasing.py:13-21`) → sherik xarid tanlagichlarida oddiy yetkazuvchi bo'lib ko'rinadi; qaytarish ledgerda `SUPPLIER_OUT` bo'lib tovar to'lovidan farqlanmaydi |
| `Customer` | qisman | **YO'Q** | Teskari qarz faqat manfiy `credit_balance` (`customers.py:189-192`); `code`/`group_id`/`loyalty_points` biriktirilgan, qarz hisobotini ifloslantiradi (`reports.py:1717-1736`) |

→ **Tor, kompaniya-doirasidagi yangi kanonik kreditor subyekti.**

### 3.2 `creditors` sxemasi

```
creditors
  id           uuid PK
  company_id   uuid NOT NULL -> companies.id
  name         varchar(120) NOT NULL              # ko'rsatish uchun (xizmat qatlami strip qiladi)
  name_key     varchar(120) NOT NULL              # ⚠️ YANGI: normallashtirilgan noyoblik kaliti
  phone        varchar(32) NULL
  employee_id  uuid NULL                          # IXTIYORIY havola, §3.4
  status       varchar(8) NOT NULL DEFAULT 'ACTIVE'
  archived_at  timestamptz NULL
  balance      numeric(14,2) NOT NULL DEFAULT 0   # KESH; haqiqat manbai §5.7
  currency     char(3) NOT NULL
  note         text NULL
  created_at   timestamptz NOT NULL
  created_by   uuid NULL -> employees.id

ck_creditor_status      status IN ('ACTIVE','ARCHIVED')
ck_creditor_arch_iff    (status = 'ARCHIVED') = (archived_at IS NOT NULL)
ck_creditor_name_nb     name     <> ''
ck_creditor_key_nb      name_key <> ''
ck_creditor_bal_nonneg  balance >= 0                          # §5.6

uq_creditors_company_id  UNIQUE (company_id, id)              # bolalar kompozit FK uchun
uq_creditors_comp_cur    UNIQUE (company_id, id, currency)    # valyuta kompozit FK uchun (§3.9)
ux_creditors_name_key    UNIQUE (company_id, name_key)        # QISMAN EMAS, §3.6
ux_creditors_employee    UNIQUE (company_id, employee_id) WHERE employee_id IS NOT NULL
```

⚠️ **`name_key` nega kerak (1-tahrirda yo'q edi).** 1-tahrir `UNIQUE (company_id,
lower(name))` + `btrim` CHECK ishlatgan edi. Ikki nuqson: (a) funksiyalar §1.1 dagi
bloklovchi muammoga tushadi; (b) `btrim(name) <> ''` faqat **butunlay bo'sh** nomni rad
etadi — «Sherik A» va «Sherik A » (bitta orqa bo'shliq) indeksda **ikki xil kalit** bo'lib,
UI'da bir xil ko'rinadigan ikki kreditor paydo bo'lardi va nom surati noaniqlashardi.
`name_key` **xizmat qatlamida** hisoblanadi (bo'shliqlar siqiladi + `casefold()`), jadvalda
oddiy ustun sifatida saqlanadi — funksiya yo'q, ifoda indeksi yo'q, ikki dialekt ham
qo'llaydi.

**Ishora konvensiyasi:** `Supplier.balance` bilan bir xil (`> 0` = biz qarzdormiz).
`Customer.credit_balance` **teskari** ishorani ishlatadi — bu farq shu yerda qayd etiladi.

**Majburiyat — KOMPANIYA fakti** (presedent: mijoz qarzi, `reports.py:1717`); `branch_id`
yo'q.

### 3.3 Hayot davri va arxivlash (talab 2)

Repoda **uchta zid mexanizm** bor: hard delete (faqat TILL — `tills.py:293-319`), soft
delete `deleted_at`, va arxiv `status` (naqd hisoblar — `cash_ddl_v1.sql:50,70`). Kreditor
uchun **BITTA o'q**: `status`.

Nega `deleted_at` EMAS:
- Supplier telefon noyobligi `deleted_at IS NULL` bilan filtrlangan
  (`purchases.py:107-110`) → soft-delete'dan keyin **dublikat identitet ochiladi** va tarix
  ikki id'ga bo'linadi. Kreditor uchun bu bevosita moliyaviy zarar.
- `Supplier.is_active` / `Customer.is_active` — **o'lik ustunlar**. Ikki o'qli hayot davri
  takrorlanmaydi: `is_active` YO'Q, `deleted_at` YO'Q.
- Product soft-delete'i qaytarilishi mumkin (`catalog_commit_v2.py:291`,
  `migrator_1c/apply.py:253`).
  ⚠️ **1-tahrirda «darvoza yo'q» deb yozilgan edi — bu XATO.** Darvoza **bor**, lekin u
  operator so'rovidagi bayroq (`DeletedMatchAction.REACTIVATE_EXISTING`; standart —
  `KEEP_DELETED`), **moliyaviy holat emas**. Kreditor uchun `status` tanlashning haqiqiy
  sababi — yuqoridagi nom/telefon noyobligi teshigi.

**Holat mashinasi:**

| Amal | Shart | Natija |
|---|---|---|
| `create` | nom bo'sh emas, `name_key` band emas | `ACTIVE` |
| `archive` | **ochiq qoldiq = 0**, aynan §5.7 ifodasi bo'yicha | `ARCHIVED` + `archived_at` |
| `unarchive` | — | `ACTIVE`, `archived_at = NULL`, **audit majburiy** |
| `delete` (hard) | `creditor_referenced() = false` | qator o'chadi |
| `delete` (aks holda) | — | **400** + «arxivlang» |

⚠️ **Arxivlash darvozasi majburiy — TILL nuqsonini takrorlamaslik uchun.** `update_till`
arxivlashda qoldiqni tekshirmaydi (`tills.py:283-289`; `repo.account_balance`
chaqirilmaydi), natijada qoldiqli drawer arxivlansa `_resolve_account` `ACCOUNT_ARCHIVED`
beradi (`posting.py:281`) va **pul qamalib qoladi**. Kreditorda bu og'irroq: arxivlangan
sherikka qarz qolsa, uni **qaytarish yo'li yopilardi**. Ochiq qoldiq ≠ 0 →
**409 `CREDITOR_HAS_BALANCE`**.

⚠️ 1-tahrir «daftardan hisoblangan» deb noaniq yozgan edi va §5.7 haqiqat manbaini
butunlay boshqa jadval deb belgilagan edi — **ikki joy zid edi**. Endi normativ ifoda §5.7
da bir marta beriladi va bu darvoza **aynan shuni** ishlatadi.

**O'qish qoidasi:** arxivlangan kreditorning **kartasi va daftari O'QILADIGAN qoladi**
(tarix bor), faqat **yangi avans tanlagichida chiqmaydi** (`active_only`). Repoda bu
ziddiyat bor va takrorlanmasligi kerak: `supplier_ledger` o'chirilgan ta'minotchini
ko'rsatadi (`purchases.py:1131-1133`), `supplier_detail` esa **404** beradi (`:1155`).

### 3.4 Platforma foydalanuvchisiga IXTIYORIY havola (talab 3)

`creditors.employee_id` — **qulaylik va audit havolasi**, buxgalteriya identiteti EMAS:

1. Kreditor **hech qachon** `employee_id` bo'yicha aniqlanmaydi.
2. Xodimdan kreditor **avtomatik yaratilmaydi**.
3. Xodim hayot davri hodisalari kreditorga **hech qanday** ta'sir qilmaydi.
4. `UNIQUE (company_id, employee_id) WHERE employee_id IS NOT NULL` — bir shaxs ↔ ko'pi
   bilan bitta kreditor.
5. `unlink` — audit hodisasi; birorta daftar/settlement qatoriga tegmaydi.
6. **FK bandi YO'Q** (`ON DELETE` yozilmaydi) — repo konvensiyasi. Xodim API orqali hard
   delete BO'LMAYDI (`employees.py:528`), demak band o'lik kod bo'lardi; `SET NULL`
   atributsiyani jimgina yo'qotardi.
7. **Xodim bo'lmagan qarz beruvchi TO'LIQ QO'LLAB-QUVVATLANADI** (`employee_id IS NULL`).

**`tenant_purge` kesishmasi va uning `public` PRESEDENTI (A-savol).**
`tenant_purge.resolve()` bir jadvalning barcha egalik yo'llarini **OR** bilan birlashtiradi
(`tenant_purge.py:404`: `ownership[node] = "(" + " OR ".join(preds) + ")"` — o'zim
tasdiqladim). `creditors` da ikkita FK bo'lsa, B kompaniyani purge qilish shartni
`(company_id = B OR employee_id IN (SELECT id FROM employees WHERE company_id = B))`
qiladi — A kompaniyaning kreditori xato bilan B xodimiga havola qilsa, u o'chib ketadi
yoki purge'ni yiqitadi.

⚠️ **1-tahrir buni «yangi, presedentsiz talab» deb ko'rsatgan edi — bu XATO.** `public`
sxemada **aynan shu naqsh allaqachon bor va aynan shu cross-tenant nuqsonni tuzatish uchun
kiritilgan**: `customer_groups` ga additiv `UniqueConstraint("company_id","id",
name="uq_cgroup_company_id")`, `customers` da esa nullable kompozit FK
`(company_id, group_id) -> customer_groups(company_id, id)`, izohi bilan: *«CROSS-TENANT
BOG'LANISH IMKONSIZ … MATCH SIMPLE semantikasi: `group_id` NULL bo'lsa tekshiruv o'tkazib
yuboriladi»* (`models/customers.py:33-36, 44-53` — o'zim tasdiqladim).

Dizayn shu presedentni **aynan** ko'chiradi:
`fk_creditors_employee_same_company (company_id, employee_id) -> employees(company_id, id)`
MATCH SIMPLE bilan. Qoladigan yagona savol — **`employees` ga additiv
`UNIQUE (company_id, id)` qo'shishga ruxsatmi** (u hozir yo'q; `cash_ddl_v1.sql:36-39` bu
jadvallar uchun «same-tenant check is SERVICE-LEVEL» deb yozgan). Bu **A-savol**.

Muqobil (rad etilsa): bir ustunli FK + xizmat qatlami tekshiruvi + `tenant_purge` OR-xavfi
hujjatlashtiriladi. FK'siz «saqlanuvchi id» **tavsiya qilinmaydi**.

### 3.5 O'zgarmas atributsiya va tarixiy nom (talab 4 va 8)

Repo nomni muzlatishni **faqat chek/sotuv yo'lida** qiladi: `Sale.cashier_name_snapshot` …
(`models/sales.py:48-54`) va `SaleItem.name_snapshot` (`:97-98`); qoida
`services/receipt/dto.py:12-15`: *ID'lar avtoritet, snapshotlar FAQAT tarixiy ko'rsatish
uchun.* Pul-kontragent tomonida snapshot **YO'Q** (`SupplierLedger` da na nom, na
`company_id`) — rename qilinsa **tarix jimgina qayta yoziladi**.

Kreditor uchun `SaleItem.name_snapshot` naqshi (`Sale.*_name_snapshot` EMAS — u nullable +
`or`-fallback, ya'ni fail-open):

1. `purchase_settlements.creditor_name_snapshot` — `creditor_id` bilan **ayni shartda**
   majburiy (`ck_ps_cred_name_iff`) + bo'sh bo'lmaslik.
2. Ayni ustun `creditor_ledger` va `creditor_repayments` da ham **NOT NULL**.
3. **Snapshotni SERVER yozadi**, so'rov tanasidan OLINMAYDI; `creditors` qatori **qulf
   ostida** o'qiladi (§10.2). Kreditor topilmasa yoki `ARCHIVED` bo'lsa **fail-closed**
   (409).
4. **O'qishda `or`-fallback YO'Q**: nom FAQAT snapshotdan olinadi.
5. Uzunlik `creditors.name` bilan bir xil (`varchar(120)`); snapshot **original registrni**
   saqlaydi.
6. Rename **audit qilinadi** (`before`/`after`) — repoda rename izi umuman yo'q.
7. **Shaxs kompaniyani tark etsa** — kreditor **arxivlanadi**, o'chirilmaydi.
8. Snapshot **hech qachon** `cash_ledger_entries.metadata` ga yozilmaydi (DDL:
   «non-authoritative»).

⚠️ **Nomni qayta ishlatish teshigi (1-tahrirda yo'q edi).** Noyoblik faqat **joriy** nom
ustida. Rename nomni **bo'shatadi**: «Sherik Ali» → «Ali (eski)» dan keyin yangi kreditor
«Sherik Ali» nomini olishi mumkin va eski hujjatlardagi
`creditor_name_snapshot = 'Sherik Ali'` endi **boshqa, tirik shaxsga** ishora qilayotgandek
o'qiladi. Tuzatish — kichik append-only jadval:

```
creditor_name_keys
  company_id  uuid NOT NULL -> companies.id
  name_key    varchar(120) NOT NULL
  creditor_id uuid NOT NULL
  created_at  timestamptz NOT NULL
  PRIMARY KEY (company_id, name_key)          # kalit ABADIY band
  fk_cnk_creditor_same_company (company_id, creditor_id) -> creditors(company_id, id)
```

Qator **yaratishda va har rename'da** qo'shiladi, **hech qachon o'chirilmaydi**.
`ux_creditors_name_key` joriy nomni, `creditor_name_keys` esa **tarixiy** nomni band qiladi
— snapshot abadiy bir ma'noli.

### 3.6 Birlashtirish (merge) va o'chirish (talab 6)

**MERGE TAQIQLANADI.** Repoda subyekt birlashtirish mexanizmi yo'q va jim birlashtirish
**ataylab taqiqlangan**: `catalog_v2.py:38-49`, `catalog_match.py:1-27`.

- **Oldini olish:** `ux_creditors_name_key` — **qisman EMAS** (arxivlangan kreditor ham
  indeksda qoladi) + `creditor_name_keys` tarixi (§3.5).
- Band kalitga urinish → **409 `CREDITOR_NAME_TAKEN`**; arxivlangan bo'lsa javob «qayta
  faollashtiring yoki boshqa nom» qarorini beradi — **jim unarchive YO'Q**.
- **Xato bilan ikki kreditor yaratilgan bo'lsa** yechim merge emas, **aniq transfer**:
  manba tomonda `ADJUST_DOWN`, maqsad tomonda `ADJUST_UP` (§4), ikkisi ham
  `ref_type='creditor_transfer'` + bir xil `transfer_group_id` + sabab majburiy. Manba
  tomondagi `ADJUST_DOWN` **ochiq avans qatorlarini allokatsiya bilan YOPADI** (§5.2/§5.4)
  — aks holda §5.7 drifti transferni rollback qilardi (1-tahrirdagi bloklovchi nuqson).
  `purchase_settlements` dagi tarixiy `creditor_id` **hech qachon qayta yozilmaydi**.
- **Hard delete** faqat `creditor_referenced() = false` (`purchase_settlements`,
  `creditor_ledger`, `creditor_repayments`, `creditor_advance_allocations`,
  `creditor_name_keys` da 0 havola) — `till_referenced()` naqshi (`tills.py:306-319`).
  Aks holda **400 + arxivlash**.

⚠️ **1-tahrir bu yerda «DELETE bloklovchi trigger qo'yiladi» deb yozib, §16.2 da esa
`public` da trigger himoya emasligini tan olgan edi — ikki joy zid.** Bitta qaror:
**Phase 1 da trigger YO'Q.** Hard delete'ni **xizmat qatlami + `creditor_referenced()` +
kompozit FK'lar** to'sadi. Trigger va egalik — **K-savol**; §17 da trigger testlari
**shartli**.

### 3.7 Ruxsatlar

Kanonik naqsh: `modul.amal` kodlari GLOBAL jadvallarda (`auth.py:12-35`), ro'yxat
`seed.py:25-37`, xarita `seed.py:42-58`, darvoza `core/deps.py:121-135`. Yangi kod
**migratsiya EMAS** — `initdb._ensure_catalog` (`initdb.py:1294-1332`) har bootda
idempotent qo'shadi.

Yangi `kreditor` moduli: `kreditor.view`, `kreditor.edit`, `kreditor.settle`,
`kreditor.repay`. Mavjud kodni qayta ishlatmaslik sharti: `hisobot.view` menejerda bor
(`seed.py:49`).

**Ikki qattiq mexanik haqiqat (o'zim tasdiqladim):**

1. `require()` **ega VA administrator** uchun tekshiruvni butunlay o'tkazib yuboradi
   (`deps.py:126-128`, `FULL_ACCESS_ROLES` `:49`), va `ADMIN_EXCLUDE` buni **to'xtatmaydi**.
   Ega-only kerak bo'lsa — handler ichida `emp.role.code == "ega" or "kreditor.settle" in
   effective_permissions(emp, db)` (`employees.py:34-37`).
2. Rol ro'yxatidan chiqarish «kassir hech qachon olmaydi»ni kafolatlamaydi:
   `PATCH /employees/{id}/permissions` (`employees.py:637-679`) istalgan kodni yoqadi.

⚠️ **1-tahrir «repoda bunday mexanizm YO'Q» deb yozgan edi — bu XATO.** Ishlaydigan
presedent **bor**: `xodimlar.make_admin` override'i `set_permissions` ichida qattiq
kodlangan holda himoyalangan — *«"Admin qilish" huquqini faqat Ega beradi»*
(`employees.py:658-659`, o'zim tasdiqladim), UI ham bu kodni alohida shoxda chizadi. Kerakli
ish — shu naqshni **`NON_OVERRIDABLE` to'plamiga umumlashtirish**, noldan mexanizm yozish
emas. → **B-savol.**

**Orqa darvozalar (ikkisi ham yopilishi shart):**
- `reports.py` (~30 ta `require("hisobot.view")`) kreditor qoldig'ini **qaytarmaydi**;
- ⚠️ **`GET /audit`** ham `hisobot.view` bilan qo'riqlanadi va javobda `payload["name"]`ni
  qaytaradi, entity filtri esa mijozga ochiq. §3.8 kreditor hodisalarini `public.audit_log`
  ga yozgani uchun **sherik qarzining summasi va sababi shu yo'ldan sizadi**. Qaror:
  `entity='creditor'` qatorlari `kreditor.view` bo'lmasa **filtrlanadi** (yoki alohida
  `GET /creditors/{id}/audit`).

Qo'shimcha: `_PIN_FORBIDDEN_PERMS` (`auth.py:58-62`) — **H-savol**; `_ensure_catalog`
try/except bilan **jim yiqiladi** (`initdb.py:1328-1331`) → fail-closed kerakmi —
**I-savol**.

### 3.8 Audit jurnali

Jadval **`public.audit_log` (SINGULAR)** — `models/sync.py:66-82`: `actor_id`, `action`,
`entity`, `entity_id`, `before`, `after`, `terminal_id`, `created_at`. **`company_id` YO'Q**
(`api/v1/audit.py:28-30` tan oladi), **`reason` ustuni ham YO'Q**, o'zgarmaslik faqat
konvensiya. `cash.audit_logs` (DB-darajasida append-only) mavjud, lekin **birorta
yozuvchisi yo'q** — unga tayanib bo'lmaydi.

Hodisalar (`entity='creditor'`, **inson qarorlari**; pul faktlari `creditor_ledger` da —
`observability.py:26-27`): `create`, `update`, `archive`, `unarchive`, `delete`,
`transfer_adjustment`, `repay`, `link_user`, `unlink_user`.

Shartlar: `actor_id` **har doim majburiy** (NULL bo'lsa `api/v1/audit.py:31-36` INNER JOIN
uni ko'rsatmaydi); sabab `after.reason` ichiga; `ENTITY_LABEL`/`ACTION_LABEL`
(`api/v1/audit.py:11-18`) ga yangi kalitlar.

### 3.9 Valyuta (D-savol yopildi)

`purchase_settlements`, `creditor_ledger`, `creditor_repayments`, `owner_advance_open`,
`creditor_advance_allocations` da **`currency` majburiy** va **kreditor valyutasiga teng** —
kompozit FK bilan: `(company_id, creditor_id, currency) -> creditors(company_id, id,
currency)` (`cle_acct_currency_fk` naqshi). Bitta avans va uning barcha qaytarishlari **ayni
valyutada**; boshqa valyuta → **409 `CURRENCY_MISMATCH`**. Ko'p valyutali sherik — valyuta
per kreditor qator.

---

## 4. Majburiyat daftari `creditor_ledger`

```
creditor_ledger
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  creditor_id            uuid NOT NULL
  creditor_name_snapshot varchar(120) NOT NULL
  type                   varchar(12) NOT NULL   # ADVANCE | REPAYMENT | ADJUST_UP | ADJUST_DOWN
  amount                 numeric(14,2) NOT NULL # > 0; ishora TIPDA
  currency               char(3) NOT NULL
  balance_after          numeric(14,2) NOT NULL
  settlement_id          uuid NULL              # ADVANCE uchun
  repayment_id           uuid NULL              # REPAYMENT uchun
  advance_id             uuid NULL              # ⚠️ YANGI: ADJUST_* qaysi avansga tegdi
  transfer_group_id      uuid NULL              # ADJUST juftligi (§3.6)
  ref_type               varchar(24) NULL
  reason                 text NULL
  created_at             timestamptz NOT NULL
  created_by             uuid NULL -> employees.id

ck_cl_amount_pos   amount > 0
ck_cl_type         type IN ('ADVANCE','REPAYMENT','ADJUST_UP','ADJUST_DOWN')
ck_cl_bal_nonneg   balance_after >= 0
ck_cl_adv_iff      (type = 'ADVANCE')   = (settlement_id IS NOT NULL)
ck_cl_rep_iff      (type = 'REPAYMENT') = (repayment_id  IS NOT NULL)
ck_cl_adj_meta     type IN ('ADVANCE','REPAYMENT')
                     OR (ref_type IS NOT NULL AND reason IS NOT NULL AND reason <> '')

ux_cl_advance   UNIQUE (settlement_id) WHERE settlement_id IS NOT NULL
ux_cl_repayment UNIQUE (repayment_id)  WHERE repayment_id  IS NOT NULL
fk_cl_creditor_same_company (company_id, creditor_id) -> creditors(company_id, id)
```

⚠️ **Uch bloklovchi tuzatish 1-tahrirga nisbatan:**

1. **`ADJUSTMENT` da ISHORA YO'Q edi.** «Ishora tipda» qoidasi faqat ADVANCE/REPAYMENT
   uchun ishlardi; `ADJUSTMENT` esa ikki yo'nalishda ishlatilardi (kamaytirish: §5.3-b/c,
   transfer manbasi; oshirish: transfer maqsadi) va ishorani tashuvchi ustun yo'q edi.
   Daftar «majburiyat oshdimi yoki kamaydimi» savoliga javob bera olmasdi, hisobotlar
   ADJUSTMENT'larni **noto'g'ri belgida** yig'ardi.
   *(Mavjud `SupplierLedger` buni **ishorali `amount`** bilan hal qiladi —
   `purchases.py:887` da `amount=delta_out` manfiy bo'lishi mumkin. Bu naqsh **ataylab
   ko'chirilmadi**: u `amount > 0` kafolatini yo'q qiladi.)*
   Tuzatish: `ADJUST_UP` / `ADJUST_DOWN`.
2. **`ADJUSTMENT` avansga havola qila OLMASDI.** `ck_cl_adv_iff`/`ck_cl_rep_iff`
   bikonditsional edi, ya'ni ADJUSTMENT qatorida ikkisi ham **majburiy NULL**; allokatsiya
   jadvali esa `repayment_id NOT NULL` talab qilardi, `creditor_repayments` o'z navbatida
   `cash_account_id` va `ledger_entry_id` NOT NULL — (b)/(c) da esa **naqd qimirlamaydi**,
   demak qaytarish qatori ham, allokatsiya ham **imkonsiz**. Natijada
   `owner_advance_open.repaid_amount` ni oshirishning **hech qanday yo'li yo'q** edi va
   §5.7 drifti har (b)/(c) tranzaksiyasini **rollback** qilardi — dizaynning o'zi majburiy
   deb belgilagan ikki holat **yozib bo'lmas** edi.
   Tuzatish: `advance_id` ustuni + `ledger_id` bo'yicha allokatsiya (§5.2) +
   `closed_amount` hisoblagichi (§5.4).
3. **Idempotentlik kaliti YO'Q edi.** Bitta settlement ikkita ADVANCE qatori yozishi mumkin
   edi. Tuzatish: `ux_cl_advance`, `ux_cl_repayment`.

`creditors.balance` RMW — **`with_for_update(key_share=True)`** ostida (§10.2).

### OWNER_ADVANCE — naqd HARAKATLANMAYDI
Sherik o'z cho'ntagidan to'lasa: **`CashLedgerEntry` YARATILMAYDI**, soxta `CASH IN`
yozilmaydi. Faqat `purchase_settlements(source='OWNER_ADVANCE')` +
`creditor_ledger(ADVANCE)` + `owner_advance_open` (§5.4). Yangi cash enum label **kerak
emas**.

> **`OWNER_CONTRIBUTION` (kapital qo'yilma) bu dizaynga KIRMAYDI.**

---

## 5. Qaytarish va ortiqcha qaytarishni to'sish (talab 5)

```
creditor_repayments
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  creditor_id            uuid NOT NULL
  creditor_name_snapshot varchar(120) NOT NULL
  cash_account_id        uuid NOT NULL           # TILL yoki SAFE — §6/§7
  amount                 numeric(14,2) NOT NULL
  currency               char(3) NOT NULL
  ledger_entry_id        uuid NOT NULL           # FAIL-CLOSED
  client_uuid            uuid NOT NULL           # ⚠️ NOT NULL (1-tahrirda nullable edi)
  created_at, created_by

ck_cr_amount_pos  amount > 0                     # ⚠️ 1-tahrirda faqat IZOH edi
ux_cr_client_uuid UNIQUE (company_id, client_uuid)
fk_cr_creditor_same_company (company_id, creditor_id) -> creditors(company_id, id)
```

⚠️ **1-tahrirda `client_uuid` nullable va indeks qismiy edi** — klient uni yubormasa,
qaytarishning **birorta DB idempotentlik kaliti qolmasdi** (`purchase_id` yo'q, ledger
biznes kaliti esa `source_id = creditor_repayments.id`, ya'ni har urinishda yangi). Endi
majburiy: yuborilmasa **400**.

⚠️ **Barcha `client_uuid` noyobliklari `(company_id, client_uuid)`.** 1-tahrirda ular
**global** edi — A kompaniya yozgan uuid B kompaniya klientidan qaytsa (qayta ishlatilgan
fixture uuid), noyoblik buzilib **B ning to'lovi hech qachon yozilmasdi** va A qatorining
borligi sizardi. Repo konvensiyasi aynan shunday: `ux_sales_company_client_uuid`,
`ux_receivings_client_uuid`, `ux_purchases_client_uuid`, `ux_recv_corr_client`
(`initdb.py:668-713`); yagona global istisno `ux_cashmov_client_uuid_all` ATAYLAB
izohlangan («kompaniya ustuni bu jadvalda YO'Q», `initdb.py:723-726`).

Naqd oyoq:

```
direction='OUT', category='CASH_OUT', source_type='CASH_OP',
source_id = creditor_repayments.id, leg_index = 0
```

### 5.1 ⚠️ Parity — xavf 1-tahrirda NOTO'G'RI joylashtirilgan edi

`compare_engine` da `EXTRA_LEDGER` shoxi **`CASH_OP` ga xos EMAS** — u
`provenance == "NORMAL"` ostidagi oxirgi `else`: biznes kaliti kutilgan/tarixiy to'plamda
topilmasa leg «legacy manba yo'q» bo'ladi (`compare_engine.py:189-193`).

| Tashuvchi | Xavf | Sabab |
|---|---|---|
| `creditor_repayments` (`CASH_OP`, NORMAL) | **BOR** | `_is_shadow_movement` `cash_movements` da qator topmaydi (`compare_engine.py:76-81`) → `EXTRA_LEDGER` |
| **Split `PURCHASE` oyoqlari (`leg_index` ≥ 1)** | **BOR va ENG JIDDIY** | `phase1._purchase_out_legs` bir xaridga **aynan bitta** oyoq kutadi: `leg_index=0`, `amount = Purchase.total + Σ(PurchaseReturn.amount)` (`phase1.py:172-190`, o'zim tasdiqladim). Split hujjatda leg 0 → `WRONG_AMOUNT`, leg 1 → `EXTRA_LEDGER` |
| Reversal legi | **BOR** | kutilgan to'plamda yo'q |
| **SEYF ochilish legi** | **YO'Q** | ataylab `provenance='RECONSTRUCTION'` (§12.2), `EXTRA_LEDGER` esa NORMAL ostida |

⚠️ 1-tahrir xavfni faqat `CASH_OP` ga bog'lab, **SEYF ochilishiga** noto'g'ri yoyib, split
`PURCHASE` oyoqlarini esa **umuman e'tibordan chetda** qoldirgan edi — holbuki oxirgisi
har split xaridni parity'da doimiy QIZIL qilardi.

**Shart:** `phase1._purchase_out_legs` settlement qatorlari bor xarid uchun kutilgan
oyoqlarni **`purchase_settlements` dan** qursin (har PAYMENT naqd oyog'i uchun bitta,
`leg_index = leg_no`, `amount` mos), va `_is_shadow_movement` yonida yangi `CASH_OP`
tashuvchilari tanilsin. Bu **kod o'zgarishi** (§18, Bosqich 3 va 7).

Hisobot talabi: kreditor qaytarish oyoqlari umumiy `CASH_OUT` ichida ko'milmasin.

### 5.2 Allokatsiya: qaysi avans yopiladi

```
creditor_advance_allocations
  id          uuid PK
  company_id  uuid NOT NULL -> companies.id
  ledger_id   uuid NOT NULL -> creditor_ledger.id     # ⚠️ REPAYMENT va ADJUST_DOWN ikkisi ham
  advance_id  uuid NOT NULL -> owner_advance_open.settlement_id
  amount      numeric(14,2) NOT NULL
  currency    char(3) NOT NULL
ck_caa_amount_pos  amount > 0
ux_caa_pair        UNIQUE (ledger_id, advance_id)
```

⚠️ **1-tahrirda jadval `repayment_id` ga kalitlangan edi** — shu sababli `ADJUST_*`
allokatsiya qila olmasdi (§4, 2-tuzatish). `ledger_id` ga o'tish ikki holatni **bir xil
mexanizm** bilan qoplaydi.

Taqsimot **FIFO va deterministik**: ochiq avanslar `(created_at, settlement_id::text)`
bo'yicha saralanadi, har biriga `min(ochiq_qoldiq, qolgan)` beriladi.

**Tranzaksiya oxiridagi ikki invariant** (1-tahrirda yo'q edi):

```
har advance_id uchun:  Σ(allocations.amount) == repaid_amount + closed_amount
har ledger_id  uchun:  Σ(allocations.amount) == creditor_ledger.amount   (REPAYMENT/ADJUST_DOWN)
```

### 5.3 Uchta holat — ikkitasi `REPAYMENT` EMAS

| Holat | Kompaniya naqdi | Majburiyat | Yozuv |
|---|---|---|---|
| (a) pul SEYFGA/KASSAGA qaytdi, sherik hali qarzdor | `IN` | o'zgarmaydi | naqd ledger; majburiyat tegilmaydi |
| (b) pul bevosita SHERIKGA qaytdi | **qimirlamaydi** | kamayadi | `ADJUST_DOWN` + `advance_id` + allokatsiya + sabab |
| (c) xarid bekor, avans ishlatilmadi | qimirlamaydi | kamayadi | `ADJUST_DOWN`, `ref_type='settlement_reversal'` |

(b)/(c) ni `REPAYMENT` deb yozish **kompaniya pul to'lagan** degan yolg'on ma'no berardi.

### 5.4 Ochiq qoldiq qatori — o'zgarmas hujjat + o'zgaruvchan hisoblagich

`purchase_settlements` **append-only** (§11), shu bois unga o'zgaruvchan `repaid_amount`
qo'yilmaydi. Repo naqshi: o'zgarmas harakat qatorlari yonida **alohida kuzatuv qatori**,
ustida qator-lokal CHECK — `lot_shortfalls.resolved_qty` +
`CheckConstraint("resolved_qty <= qty", name="ck_lot_shortfall_resolved_le_qty")`
(`models/inventory.py:299-301`, o'zim tasdiqladim). Izohdagi sabab **so'zma-so'z** bu yerga
ko'chadi: ortiqcha yopilsa invariant yig'indisi jimgina nolga tushib, xatoni tushunarsiz
qilardi.

```
owner_advance_open
  settlement_id   uuid PK
  settlement_kind varchar(8) NOT NULL            # ⚠️ YANGI: kompozit FK uchun
  company_id      uuid NOT NULL -> companies.id
  creditor_id     uuid NOT NULL
  amount          numeric(14,2) NOT NULL         # settlementdan KO'CHIRILGAN, O'ZGARMAS
  repaid_amount   numeric(14,2) NOT NULL DEFAULT 0   # naqd qaytarish (REPAYMENT)
  closed_amount   numeric(14,2) NOT NULL DEFAULT 0   # ⚠️ YANGI: ADJUST_DOWN
  currency        char(3) NOT NULL

ck_oao_amount_pos   amount > 0
ck_oao_kind_payment settlement_kind = 'PAYMENT'
ck_oao_parts_nonneg repaid_amount >= 0 AND closed_amount >= 0
ck_oao_sum_le_amt   repaid_amount + closed_amount <= amount

fk_oao_settlement (settlement_id, settlement_kind) -> purchase_settlements(id, kind)
fk_oao_creditor_same_company (company_id, creditor_id) -> creditors(company_id, id)
```

⚠️ **Bloklovchi tuzatish: REVERSAL oyog'i kuzatuv qatori OLMAYDI.** 1-tahrir predikatni
«faqat `source='OWNER_ADVANCE'`» deb yozgan edi — lekin REVERSAL oyog'i **ham**
`source='OWNER_ADVANCE'` (`ck_ps_creditor_iff` shuni majburlaydi), ya'ni literal
implementatsiya **ikkinchi** `owner_advance_open` qatorini yozib, hisobni ikkilantirardi.
Qator-lokal CHECK boshqa jadvalning `kind`ini ko'rmaydi, shu bois himoya **deklarativ**:
`settlement_kind` ustuni + kompozit FK `(settlement_id, settlement_kind) ->
purchase_settlements(id, kind)` + `CHECK settlement_kind = 'PAYMENT'`. Bu aynan `cash`
sxemasining kompozit-FK naqshi (`cle_acct_type_fk`).

⚠️ **Atributsiya maydonlari o'zgarmas.** `creditor_id`, `amount`, `currency`,
`settlement_id`, `settlement_kind` **faqat INSERT'da**; UPDATE faqat
`repaid_amount`/`closed_amount` ga. 1-tahrirda bu jadval o'zgarmaslik perimetridan
tashqarida qolgan edi.

### 5.5 QISQARTIRISH (clamp) TAQIQLANADI — RAD ETILADI

Pul domeni ortiqcha to'lovni **jimgina qisqartiradi**: `purchases.py:1040`
(`amt = min(amount, bal)`), `customers.py:333` — ikkisi ham **200** qaytaradi.

⚠️ **1-tahrir «pul jimgina yo'qoladi» deb yozgan edi — bu MUBOLAG'A.** Balans darajasida
pul yo'qolmaydi: to'lovning to'liq summasi `SupplierPayment`ga,
`SupplierLedger(payment, −amt)` ga va `sup.balance` ga yoziladi. Yo'qoladigan narsa —
**hujjat darajasidagi taqsimot**: FIFO halqasidan keyin qolgan `remaining` birorta xaridga
yozilmaydi (`purchases.py:1088-1101`), ya'ni ta'minotchi balansi to'g'ri, lekin **qaysi
xarid to'langani noaniq**.

Clamp'ni rad etishning haqiqiy dalili boshqa: **ko'p sherikli dunyoda clamp operatorning
xatosini jimgina yutadi.** Sherik A ga 5 000 qaytarmoqchi operator 7 000 yuborsa, clamp
5 000 yozib **200 qaytaradi** — operator 7 000 chiqarilgan deb hisoblaydi, kassada esa
5 000 ketgan; ikki 2 000 nomuvofiqligi hech qayerda qayd etilmaydi.

**Qaror:** zaxira domeni naqshi (`lot_resolution.py:331-354`): qulf → qulf ostida
idempotentlik replay → `if total > open_total: raise 409 OVER_REPAYMENT`. **RAD, clamp
emas.** CHECK — faqat zaxira to'siq, chunki mavjud `IntegrityError` ushlash naqshi
constraint nomini o'qimaydi (`purchases.py:1113`).

### 5.6 Manfiy kreditor balansi TAQIQLANADI (C-savol yopildi)

`ck_creditor_bal_nonneg (balance >= 0)` va `ck_cl_bal_nonneg (balance_after >= 0)`.
Repoda ikki tomonga presedent bor (to'lov yo'lida manfiy yo'q; qaytarish/tahrir yo'lida
ataylab bor — `sales.py:1034-1036`, `purchases.py:868-885`), lekin kreditor uchun manfiy
**«endi sherik kompaniyaga qarzdor» degan yangi, hujjatsiz majburiyatni** jimgina
yaratardi. Yangi jadval — birorta legacy yo'lni buzmaydi.

### 5.7 Haqiqat manbai — YAGONA NORMATIV TA'RIF

⚠️ **1-tahrirda ayni qiymat uchun UCH vakillik bor edi** (kesh `creditors.balance`,
`creditor_ledger`, `owner_advance_open`), e'lon qilingan yagona invariant esa faqat
kesh ↔ `owner_advance_open` juftini tekshirardi; §3.3 darvozasi «daftardan» deb boshqa
jadvalni ko'rsatardi. Undan yomoni: §3.6 transferi `creditor_ledger` ga ikki qator yozib
`owner_advance_open` ga tegmagani uchun invariant **har transferni rollback** qilardi —
merge o'rniga taklif qilingan yagona yo'l ishlamasdi.

**Normativ ta'rif (bir marta; hamma joy shunga havola qiladi):**

```
kreditorning ochiq qoldig'i :=
    Σ creditor_ledger.amount · (+1 agar type IN ('ADVANCE','ADJUST_UP')
                                −1 agar type IN ('REPAYMENT','ADJUST_DOWN'))
```

- `creditors.balance` — shu yig'indining **keshi**; qulf ostida yangilanadi va tranzaksiya
  oxirida tekshiriladi (farq → **rollback**, `stock_invariant.assert_ok` uslubi,
  `lot_resolution.py:447-449`).
- `owner_advance_open` — **haqiqat manbai EMAS**. U **bitta avansdan ortiq yopishni**
  qator-lokal CHECK bilan imkonsiz qiladi (§5.4), boshqa hech narsa qilmaydi.
- §3.3 arxivlash darvozasi **shu ifodadan** hisoblaydi.
- Transfer (§3.6) daftarda `ADJUST_DOWN` + `ADJUST_UP` juftligi bo'lgani uchun yig'indi
  **avtomatik izchil**; manba tomondagi `ADJUST_DOWN` avans qatorlarini allokatsiya bilan
  yopadi, shu bois `owner_advance_open` ham ortda qolmaydi.

Ikkinchi darajali (majburiy) invariant: har kreditor uchun
`Σ(owner_advance_open.amount − repaid_amount − closed_amount)` **≤** ochiq qoldiq.

### 5.8 Yaxlitlash (E-savol yopildi)

Avans **va** qaytarish summalari **butun som** (`whole-som-payments`) — `ROUND_HALF_UP`,
klientda `Math.round`. Aks holda oxirgi qaytarishda 0.01 qoldiq qolib, avans
`repaid_amount + closed_amount <= amount` ostida **abadiy yopilmay** qolishi mumkin.

### 5.9 ⚠️ Z-hisobot xavfi — ochiq smenali TILL'dan qaytarish

Legacy (ledger-native **bo'lmagan**) do'konda `close_shift` kutilgan naqdni `SalePayment` +
`CashMovement` dan hisoblaydi. Kreditorga qaytarish faqat `cash_ledger_entries` ga yozilsa,
Z-hisobot **soxta ortiqcha** ko'rsatadi (kassadan pul ketgan, kutilgan naqd kamaymagan).
`pay_supplier` bu muammoni `CashMovement(payout, ...)` yozib hal qiladi.

**Qaror:** ochiq smenali TILL'dan qaytarishda `CashMovement(payout, reason="Kreditor · <nom
surati>")` **majburiy** — `pay_supplier` bilan bit-ba-bit izchil. SEYFdan yoki smenasiz
qaytarish bu qadamni talab qilmaydi.

---

## 6. TILL oyog'ining validatsiyasi — **bitta ham qoida yumshatilmaydi**

1. hisob mavjud, `type='TILL'`, `status='ACTIVE'`, ayni tenant, ayni filial, valyuta mos;
2. ochiq smena bo'lsa — TILL **aynan shu smenaning kassasi** bo'lishi SHART; boshqa
   kassirning yashigi **`ERR_TILL_SHIFT_MISMATCH`** bilan rad etiladi
   (`cutover_guard.py:394-401`);
3. post-T0 `till_id=NULL` legacy smena → `ERR_LEGACY_SHIFT_NEEDS_TILL`;
4. yopilgan smenaga replay → rad;
5. leg `ON_SHIFT` bo'lib `shift_id` oladi (aks holda `UNRESOLVED_OFF_SHIFT`,
   `posting.py:325-327`).

> **`ERR_TILL_SHIFT_MISMATCH` GLOBAL O'CHIRILMAYDI va kuchsizlantirilmaydi.**

---

## 7. SEYF oyog'ining validatsiyasi + custody domeni

### 7.1 Sxema SEYFni ALLAQACHON smenasiz deb modellaydi
- `cle_posting_shift CHECK`: `OFF_SHIFT ⟺ shift_id IS NULL` (`cash_ddl_v1.sql:204-207`);
- `cle_shift_fk`: smena **ayni hisobga** tegishli bo'lishi shart (`:225-226`) — SEYF esa
  smena ochmaydi (`:129`);
- jadval izohi (`:241`): *"SAFE legs are always OFF_SHIFT (SAFE owns no shift)"*.

### 7.2 Qaror: operatsiyaning **custody DOMENI** e'lon qilinadi

| Domen | Ma'nosi | Misollar |
|---|---|---|
| `SHIFT_BOUND` | kassirning yashik seansi qismi | sotuv, sotuv qaytarishi, smena kassa kirim/chiqimi |
| `TREASURY` | kompaniya pulining harakati; kassir navbatda bo'lishi ahamiyatsiz | **xarid/qabul to'lovi**, ta'minotchi to'lovi, **kreditorga qaytarish** |

`TREASURY`: **SAFE** → ochiq smena ahamiyatsiz, leg `OFF_SHIFT`/`shift_id=NULL`,
`TILL_SHIFT_MISMATCH` **qo'llanmaydi**; **TILL** → §6 to'liq, o'zgarishsiz; explicit hisob
berilmasa → `ERR_CUSTODY_REQUIRED` o'zgarishsiz. `SHIFT_BOUND` uchun **hech narsa
o'zgarmaydi**.

> Bu **«smena xavfsizligini yumshatish» EMAS.** TILL sharti o'zgarmaydi; faqat SEYFga TILL
> qoidasini qo'llash to'xtatiladi, chunki baza SEYFni smenasiz deb belgilagan. Amaldagi
> nuqson: tizim «seyfdan to'lash uchun kassir smenasini yoping» deb talab qiladi — bu
> jismoniy haqiqatga ham, sxemaga ham qarshi.

**Chaqiruv joylari — SAKKIZTA, sakkizinchisi O'QISH yo'li.** ⚠️ 1-tahrir yettita yozuvchini
sanab, **eng muhimini tushirib qoldirgan edi**:

| # | Joy | Tur |
|---|---|---|
| 1–7 | `customers.py:379`, `purchases.py:429/956/982/1070`, `receiving.py:439`, `lot_correction.py:676` | yozuvchi |
| — | `sales.py:183` (`require_post_t0_till`) | yozuvchi (`SHIFT_BOUND`) |
| **8** | **`preview_cash_custody` → `custody_preview.decide` / `preview()`** (`custody_preview.py:405-436`) | **O'QISH** |

Domen 8-chiga uzatilmasa (yoki fail-closed `SHIFT_BOUND` olsa), ochiq smenada `decide()`
`mode=SERVER_RESOLVED` va `options=[]` qaytaradi — **Manager ekrani seyfni tanlash imkonini
bermaydi**, server esa uni qabul qiladi. D-33 testi server tomonida yashil bo'lib, UI orqali
erishib bo'lmaydigan qolardi va §18 dagi «0–4 muammoni to'liq hal qiladi» va'dasi buzilardi.
**Shart:** `TREASURY` domenida ochiq smena bo'lsa ham `decide()` `options` (TILL + SAFE)
qaytaradi; D guruhiga **preview ↔ yozuvchi parity** testi qo'shiladi.

Domen e'loni **qo'shimcha** parametr; e'lon qilinmagan chaqiruv `SHIFT_BOUND` (eng qattiq)
deb qabul qilinadi — fail-closed default (`fail-open-defaults`).

### 7.3 SAFE uchun manfiy qoldiq — QAT'IY fail-closed
SEYF uchun `allow_negative` override **yo'q** (servis + DDL `CF-D5` ikkisi ham TILL'ga
bog'langan). **Ataylab shunday qoldiriladi.** Natija — §0 zanjiri: ochilish qoldig'i
bo'lmasa to'lov `INSUFFICIENT_CASH` bilan rad etiladi, va bu **to'g'ri**.

---

## 8. `CashPostingService` xaritasi

| Hodisa | Ledger oyog'i | Hisob | `posting_kind` / `shift_id` | Qo'shimcha |
|---|---|---|---|---|
| `TILL_CASH` settlement | `OUT · PURCHASE_OUT` (`PURCHASE`, `leg_no`) | tanlangan TILL | `ON_SHIFT` / smena id | — |
| `SAFE_CASH` settlement | `OUT · PURCHASE_OUT` (`PURCHASE`, `leg_no`) | tanlangan SAFE | `OFF_SHIFT` / `NULL` | — |
| `OWNER_ADVANCE` settlement | **yozuv yo'q** | — | — | `owner_advance_open` |
| kreditorga qaytarish | `OUT · CASH_OUT` (`CASH_OP`, 0) | TILL/SAFE | §6/§7 | ochiq smenali TILL → **`CashMovement(payout)`** (§5.9) |
| SEYF ochilish qoldig'i | `IN · ADJUSTMENT` (`CASH_OP`, 0) | SEYF | `OFF_SHIFT` / `NULL` | `provenance='RECONSTRUCTION'` |

`CashPostingService` **yagona yozuvchi**; to'g'ridan-to'g'ri `INSERT` **taqiqlanadi**.

---

## 9. Ta'minotchi qarzi xaritasi

```
unpaid = purchase.total − Σ(PAYMENT.amount) + Σ(REVERSAL.amount)
```

Ta'minotchi uchun **kim to'lagani ahamiyatsiz**, shu bois `OWNER_ADVANCE` ham `unpaid` ni
kamaytiradi va `purchases.paid_amount = Σ(PAYMENT − REVERSAL)`. `unpaid > 0` →
`sup.balance += unpaid` + `SupplierLedger(charge, ...)`, balans **qator qulfi ostida**
(`purchases.py:313`, `receiving.py:218`).

`paid_cash` / `paid_owner` — **saqlanmaydi, hisoblanadi**.

### ⚠️ `_charged` ikkilik predikati va tahrir darvozasi

`purchases.py:881-906` hujjatni ikkilik tasniflaydi, QA PR-004 esa naqd xaridda
`paid_amount`ni majburan `total`ga tenglaydi — gibrid hujjatda ikki qoida zid.

⚠️ **1-tahrirdagi darvoza TOR edi:** faqat «split yoki `OWNER_ADVANCE` bor» hujjatlarni
bloklardi, ya'ni **bitta oyoqli** (masalan faqat SEYF) settlement hujjati eski tahrir
yo'lidan o'tib ketardi — u yerda `pur.paid_amount = new_total` majburan o'rnatilib (QA
PR-004) §9 formulasi bilan zid bo'lardi va qaytarish `resolve_cash_custody` bo'yicha
**boshqa hisobga** tushardi.

**Qaror:** darvoza **settlement oyog'i bor HAR QANDAY hujjatga** qo'llanadi:
`PATCH /purchases/{id}` → **409 `SETTLEMENT_EDIT_UNSUPPORTED`**. Tuzatish yo'li —
REVERSAL + replacement revizyasi (§2.2, §11), Phase 5D naqshi.

---

## 10. Atomiklik, qulf, idempotentlik (talab 7)

### 10.1 Tranzaksiya chegarasi

Bitta DB tranzaksiyasi: hujjat + qatorlar + barcha settlement oyoqlari + barcha ledger
oyoqlari + ta'minotchi qarzi + kreditor daftari + kuzatuv/allokatsiya qatorlari. Har qanday
qisman xato → **butun ROLLBACK**.

- **`commit=False` da tiklanish:** `IntegrityError→DUPLICATE` o'girishi faqat `commit=True`
  shoxida (`posting.py:408-416`), shu bois har oyoq **`SAVEPOINT`** (`db.begin_nested()`)
  ichida yoziladi va noyoblik buzilishi **constraint nomi bo'yicha** ajratiladi (§2.5).
- **Qatorlararo invariantlar** (`total = Σ(legs) + unpaid`; §5.2 dagi ikki tenglik; §5.7
  kesh ↔ daftar) — Postgres CHECK qator-lokal bo'lgani uchun **xizmat qatlamida**
  tranzaksiya oxirida tekshiriladi.
- **Qator-lokal (baza kafolati):** ortiqcha yopish (§5.4), manfiy balans (§5.6), REVERSAL
  summasi tengligi (§2.4), REVERSAL kuzatuv qatori olmasligi (§5.4), tenant va valyuta
  izchilligi (kompozit FK'lar).

### 10.2 Qulf tartibi va darajasi

Repoda **yozilgan** shartnoma: `lot_correction.py:53-88`.

⚠️ **1-tahrirdagi zanjir ikki joyda YOLG'ON edi.**

1. **0/2-qadam tushib qolgan edi.** `FOR KEY SHARE` ota qatorlari (`Company`, `Branch`,
   `Employee`, va endi `Creditor`) **har qanday `FOR UPDATE`dan oldin** olinadi — sababi
   kodda yozilgan: hodisa INSERT'i FK orqali ota qatorga KEY SHARE oladi, uni keyinroq
   olish qulfni kuchaytirish bo'lardi.
2. **Zanjirning OXIRI o'z sxemasi bilan zid edi.** `ck_ps_ledger_iff` naqd oyoq uchun
   `ledger_entry_id` ni NOT NULL qiladi, §11 esa jadvalni append-only qiladi — demak
   settlement qatorini **ledger qatori yaratilgandan KEYIN** yozishdan boshqa yo'l yo'q.
   `CashPostingService` esa `cash_accounts` (va TILL bo'lsa `cash.shifts`) ni FOR UPDATE
   oladi (`posting.py:288-303`). Ya'ni **amalda** naqd qulflari settlement/daftar
   INSERT'laridan **oldin** olinadi.

**To'g'ri zanjir:**

```
0) FOR KEY SHARE:   companies -> branches -> employees -> creditors (sorted key=str)
1) purchases          FOR UPDATE
2) suppliers          FOR UPDATE
3) creditors          FOR NO KEY UPDATE   (sorted key=str)   <-- balans RMW
4) inventory          FOR UPDATE          (sorted key=str)
5) stock_batches      FOR UPDATE          (id tartibida)
6) custody rezolyutsiyasi — QULF YO'Q
7) cash.cash_accounts FOR UPDATE (sorted key=str) -> cash.shifts FOR UPDATE
8) INSERT: purchase_settlements, owner_advance_open, creditor_ledger,
           creditor_advance_allocations      (ledger_entry_id endi ma'lum)
9) qatorlararo invariantlar -> commit
```

3-qadamda `FOR NO KEY UPDATE` olinganidan keyin 8-qadamdagi INSERT'lar ayni qatorda KEY
SHARE so'raydi — **biz allaqachon kuchliroq qulfni ushlab turamiz**, demak kuchaytirish
yo'q.

⚠️ **QULF DARAJASI — 1-tahrirdagi xato.** Oldin «`Supplier.balance` naqshi» (oddiy
`with_for_update()`) deb yozilgan edi. Bu **FK KEY SHARE kuchaytirish tuzog'iga** tushadi:
`purchase_settlements.creditor_id`, `creditor_ledger.creditor_id`,
`owner_advance_open.creditor_id` FK'lari har INSERT'da kreditor qatorida `FOR KEY SHARE`
oladi. To'g'ri daraja — **`with_for_update(key_share=True)`** (FOR NO KEY UPDATE).
Presedent va sabab kodda: **`services/sales.py:612-638`** (izoh `:619-636`, kod `:637-638`)
va `cashops.py:102-108`.
⚠️ 1-tahrir havolani `sales.py:615-638` deb yozgan edi — repoda **ikki** `sales.py` bor va
`api/v1/sales.py:637-638` aynan **oddiy `FOR UPDATE`** ishlatadi, ya'ni havolani ochgan
implementator **noto'g'ri naqshni** ko'chirardi.

**Bir hujjatda bir necha kreditor:** `set` bilan dedup + `sorted(ids, key=str)`. Qulf
**doirasi hujjatniki**: tuzatish/reversal yo'lida so'rovdagi kreditorlar ∪
`SELECT DISTINCT creditor_id FROM purchase_settlements WHERE purchase_id = :id` **bitta
saralangan o'tishda**.

**Get-or-create** `ux_creditors_name_key` + `IntegrityError` retry'ga tayanadi,
`FOR UPDATE`ga **emas**: mavjud bo'lmagan qatorni qulflab bo'lmaydi
(`receiving.py:226-232` da aynan shu teshik bor).

**Deadlock o'rami:** `40P01` → 3 marta qayta urinish.
⚠️ Havolalar tuzatildi: naqsh **`lot_correction.py:691-716`** (`:712` da
`sqlstate != "40P01"`) — 1-tahrirdagi `:757-772` boshqa funksiyani ko'rsatardi;
`create_purchase` **allaqachon 3 marta qayta uradi**, faqat `IntegrityError` uchun —
**`purchases.py:283-291`** (1-tahrirda `:294-301`).

**MAJBURIY OLDINGI TUZATISH — `pay_supplier` tartib inversiyasi.** `pay_supplier` avval
`suppliers` ni FOR UPDATE qiladi (`purchases.py:1013`), so'ng FIFO taqsimotda `purchases`
qatorlarini **qulfsiz** o'qib UPDATE qiladi (`:1084-1101`) — commit'da implicit
`FOR NO KEY UPDATE` olinadi va u 1-qadamdagi `FOR UPDATE` bilan **to'qnashadi**. Yangi
zanjirga ergashadigan har yo'l (`edit_purchase` `:715 → :734`, qabul tuzatishi
`lot_correction.py:789 → :809`) `purchases` ni **birinchi** oladi. Shart: `pay_supplier` da
FIFO `debts` to'plami `suppliers` dan **oldin**, barqaror tartibda FOR UPDATE bilan
qulflansin, va `40P01` o'rami shu yo'lga ham qo'yilsin. **Bu Bosqich 3 ning oldingi sharti
(Bosqich 0).**

### 10.3 Idempotentlik kalitlari

| Hodisa | Kalit | Nima to'sadi |
|---|---|---|
| Hujjat | `ux_purchases_client_uuid` / `ux_receivings_client_uuid` (`(company_id, client_uuid)`) | ikkinchi hujjat |
| Settlement oyog'i | `ux_ps_leg` + `ux_ps_cash_party` / `ux_ps_cred_party` (deterministik `leg_no`) | ikkinchi oyoq |
| Naqd oyoq | `cle_uq_business` | ikkinchi ledger qatori |
| Daftar ADVANCE | `ux_cl_advance UNIQUE (settlement_id)` | ikkinchi ADVANCE |
| Daftar REPAYMENT | `ux_cl_repayment UNIQUE (repayment_id)` | ikkinchi REPAYMENT |
| Avans kuzatuvi | `owner_advance_open.settlement_id` PK | ikkinchi kuzatuv qatori |
| Qaytarish | `ux_cr_client_uuid`, `client_uuid` **NOT NULL** | ikkinchi qaytarish |
| Allokatsiya | `ux_caa_pair (ledger_id, advance_id)` + FIFO determinizmi | qo'shimcha allokatsiya |
| Tuzatish revizyasi | tuzatish hujjatining `client_uuid`si (§2.2) | ikkinchi revizya |

`OWNER_ADVANCE` oyog'ida **ledger yozuvi yo'q**, shu bois `CashPostingService` dublikat
tekshiruvi u yerda **ishlamaydi** — §2.5 dagi tana-solishtirish majburiy.

Bu indekslar pul kafolatini ko'taradi → **`REQUIRED_INDEXES`** (§1.2).

### 10.4 Offline takror — tekshirildi, xavf YO'Q

`/sync/push` **faqat `body.sales`** ni qabul qiladi (`sync.py:43-48`), shu bois
`sync.py:71` dagi `_transient = status >= 500 or status == 409` qoidasi settlementga
tegmaydi. Mobil qabul barqaror `client_uuid` + **qo'lda** qayta yuborish ishlatadi
(`api/receiving_api.dart:17`), fon navbati yo'q. Kelajakda xarid offline navbatga
qo'shilsa — `INSUFFICIENT_CASH` (doimiy 409) **cheksiz aylanardi**; shart o'sha paytda
qayta ko'riladi.

---

## 11. Tuzatish / reversal modeli

- `purchase_settlements` **append-only**. Yagona o'zgaruvchan moliyaviy maydonlar —
  `owner_advance_open.repaid_amount` / `closed_amount`, ikkisi ham qator-lokal CHECK bilan
  qamalgan.
- Teskari yo'nalish **`kind='REVERSAL'` + `reverses_id`** (manfiy summa emas);
  `ux_ps_reverses` → bir oyoqqa **ko'pi bilan bitta** reversal; summa tengligi kompozit FK
  bilan (§2.4).
- Almashtiruvchi to'plam — **yangi `revision`** (§2.2).
- ⚠️ **Ledger tomonida reversal legi «yangi `source_id`» OLMAYDI.** 1-tahrir shunday
  yozgan edi, lekin bu §2 bilan zid: `leg_index = leg_no` va reversal `leg_no` ni
  `purchase_settlements` dan oladi (§2.3), demak reversal legi **ayni**
  `source_id = purchase.id` ostida `leg_index = yangi leg_no` bilan yoziladi. Dublikat
  xavfi yo'q, chunki `leg_no` yangi.
- `OWNER_ADVANCE` legining reversali **naqd yozuvi yaratmaydi**; u
  `creditor_ledger(ADJUST_DOWN, ref_type='settlement_reversal', advance_id=...)` +
  allokatsiya bilan (§5.3-c).
- **Qisman qaytarish reversal EMAS** (`PURCHASE_RETURN_identity.md`, `adapters.py:70`).

> ⚠️ **Append-only'ni ustun yo'qligi ISBOTLAMAYDI.** Kafolat: (a) xizmat qatlamida yozuv
> yo'lining yagonaligi, (b) qator-lokal CHECK'lar, (c) `REQUIRED_INDEXES` sinfidagi unique
> indekslar, (d) kompozit FK'lar. DB trigger — **K-savol**, §16.2.

---

## 12. SEYF ochilish qoldig'i — **ANIQ DIZAYN BO'SHLIG'I**

### 12.1 Topilgan holat
- T0 da **hech qanday** ochilish yozuvi yozilmaydi (`T0_CUTOVER_ENFORCEMENT.md:96`);
  `cash_provision` faqat `cash_accounts` yaratadi. **Har qanday hisob qoldiq 0 bilan
  tug'iladi.**
- TILL uchun yo'l BOR: birinchi smena ochilishida `_delta = opening_cash − account_balance`,
  `_delta > 0` → `IN·OPENING` (`SHIFT_OPEN`, `ON_SHIFT`) (`retrofit.py:154-157`).
- SEYF uchun yo'l **YO'Q**: mexanizm smenaga bog'langan, SEYF smena ochmaydi.
  `POST /safes` (`tills.py:214`, `SafeCreate` — `:192-195`) summa qabul **QILMAYDI**.
- Sxema va adapterlar **tayyor**, lekin chaqiruvchi **API/CLI yo'q**.

> **XULOSA: T0 dan keyin yaratilgan SEYFga jismoniy qoldiqni kiritishning kanonik yo'li
> ARXITEKTURADA YO'Q.** Bosqich 1.

### 12.2 Taklif — `POST /cash/accounts/{id}/opening`

```
cash_account_openings
  id, company_id, cash_account_id UNIQUE, counted_amount, currency, counted_at,
  attestation_ref  NOT NULL, attested_by NOT NULL -> employees.id,
  ledger_entry_id  NOT NULL, created_at
ck_cao_amount_pos  counted_amount > 0
ck_cao_ref_nb      attestation_ref <> ''
```

```
direction='IN', category='ADJUSTMENT', source_type='CASH_OP',
source_id = cash_account_openings.id, leg_index = 0,
provenance='RECONSTRUCTION', reconstruction_reason=..., reconstruction_source_ref=attestation_ref
```

1. **`ADJUSTMENT`, `OPENING` emas** — `OPENING` faqat `SHIFT_OPEN` bilan juftlashgan;
   `ADJUSTMENT` mavjud **menejer+ darvozasini** beradi (`posting.py:254-260`).
2. **Miqdor semantikasi TILL bilan bir xil:** `amount = counted − balance`, hisob qulfi
   ostida; `<= 0` → aniq xato. `retrofit.py:150-163` izohi manfiy deltani ataylab
   yozmaslikni va uni kitobga olish `ADJUSTMENT` + menejer+ talab qilishini **allaqachon
   aytadi**.
3. **Bir martalik:** `UNIQUE(cash_account_id)` + `cle_uq_business`.
4. **Audit:** `attestation_ref` va `attested_by` **NOT NULL**;
   `provenance='RECONSTRUCTION'` reason+source_ref ikkisini majburlaydi (`cle_recon_prov`).
5. ⚠️ **Parity:** 1-tahrir bu yerda `compare_engine` o'zgarishini talab qilgan edi — **kerak
   emas**: `EXTRA_LEDGER` shoxi `provenance == "NORMAL"` ostida, ochilish legi esa ataylab
   `RECONSTRUCTION`. Shart faqat shu: holat **testda qotirilsin** (§17 E-47).

### 12.3 Qo'shimcha bo'shliqlar
- **TILL qoldig'ini pasaytirish yo'li ham yo'q** (`retrofit.py:159-163`).
- `reconcile_safe` (`lifecycle.py:118-131`) na endpoint, na CLI orqali chaqirilmaydi.
- **SEYF hayot davri umuman yo'q:** `/safes` uchun faqat `GET` va `POST`.
- **Legacy tenantda SEYF qoldig'i backfillda YO'Q**, migratsiyada faqat REVIEW
  (`MIGRATION_PHASE0.md:151`) → **J-savol**.

---

## 13. Manager UX

Hozir: `packages/shared/src/screens/Products.tsx:1053-1059` — ikkilik `naqd | nasiya`
tugmasi, **hisob tanlagichi yo'q**. Ekranni **faqat Manager** import qiladi
(`apps/manager/src/App.tsx:5`) — POS ta'sirlanmaydi.

```
┌ To'lov ──────────────────────────────────────────────────┐
│ Jami: 30 000                                             │
│  [Asosiy seyf    ▾]  [ 10 000 ]  (qoldiq: 2 100 000)    │
│  [Kassa #1       ▾]  [  5 000 ]  (qoldiq:   340 000)    │
│  [Sherik: A      ▾]  [  5 000 ]  (qarz: 5 000 → 10 000) │
│  [+ to'lov manbasi]                                      │
│  Qarzga qoladi:        10 000   (hosila)                 │
└──────────────────────────────────────────────────────────┘
```

- Naqd manbalar **serverdan**: `GET /cash/custody-preview?operation=receiving_payment` →
  `info.options` (§7.2 dagi 8-chaqiruv **shart**).
- Kreditorlar `GET /creditors?active_only=true` dan; anonim «ega» varianti **YO'Q**.
- «Qarzga qoladi» — hosila; manfiy bo'lsa saqlash bloklanadi.
- Eski ikkilik tugma **ko'chiriladi, qo'shilmaydi** (`ui-move-not-add`).
- Qoldiq/qarz **oldin** ko'rinadi, xatodan keyin emas.
- ⚠️ **Desktop xato ko'rsatishi buzilgan:** `api.ts:105` dict `detail`ni `JSON.stringify`
  qiladi → operator **xom JSON** ko'radi; `serverErrorsCash.ts:18-67` faqat 7 ta prefiksli
  gard kodini biladi (mobil 18 ta posting kodini biladi — `errors.dart:111-129`). Shart:
  `api.ts` `d.error`/`d.message`ni ajratsin va `INSUFFICIENT_CASH`,
  `UNAUTHORIZED_OPERATION`, `ACCOUNT_ARCHIVED`, `CURRENCY_MISMATCH`, `OVER_REPAYMENT`,
  `CREDITOR_HAS_BALANCE`, `CREDITOR_NAME_TAKEN`, `SETTLEMENT_CONFLICT`,
  `SETTLEMENT_EDIT_UNSUPPORTED` ru/uzc bilan qo'shilsin (`server-error-i18n`).
- Summalar **butun som**.

---

## 14. Mobil UX

`custody_block.dart:69` `info.options`ni shartsiz chizadi, `:314` da «Seyf» yorlig'i.
Mobil kodni `X-Error-Code`/`detail['error']` dan o'qiydi (`api.dart:1032-1053`).

- bitta tanlovdan **qatorlar** ro'yxatiga; `client_uuid` hujjat uchun barqaror, `leg_no`
  deterministik;
- server rad etsa UI hujjatni **yo'qotmasdan** qayta manba tanlashni taklif qiladi;
- ⚠️ `receiving_submit_sheet.dart:34-48` ro'yxatidan `NEGATIVE_APPROVAL_REQUIRED` olinadi
  (o'lik kod), o'rniga `UNAUTHORIZED_OPERATION`;
- kreditor yozuvi mobilda bo'ladimi — **F-savol**.

---

## 15. Purchase Return — kelajakka moslik

> Bu bosqichda **implementatsiya QILINMAYDI.**

Bugun qaytarish `PATCH /purchases/{id}` tahririning yon ta'siri, summa
`_ret_amt = paid − new_total` (`purchases.py:936`), pul **hozirgi kontekst** bo'yicha
hisobga tushadi.

Sxema saqlaydi: har oyoqning **o'z identiteti** (`purchase_id`, `revision`, `leg_no`,
`party`, `ledger_entry_id`); `kind`/`reverses_id` — «qaysi oyoqqa qaytdi» javobini saqlash
joyi; `creditor_id` + snapshot — sherik pulining qaytishi fantom naqd yaratmasligi (§9
darvozasi Phase 1 da kafolatlaydi).

**`purchases.cash_account_id` taqdiri.** Izohi «keyingi audit … SHU ustunga tayanadi»
(`purchasing.py:41-43`) — split bilan **buziladi**. Audit identiteti
`purchase_settlements` ga o'tadi; ustun **aynan bitta** naqd oyoqda avvalgidek yoziladi
(`test_mobile_parity_pg.py:1323` yashil qoladi), splitda **NULL** va izohi «ESKIRGAN:
avtoritet emas» deb belgilanadi.

Kelajakda: allokatsiya siyosati (**L-savol**); `custody_preview` uchun
`purchase_return_cash` operatsiyasi (hozir yo'q).

---

## 16. Migratsiya va orqaga moslik

### 16.1 Yangi enum label KERAK EMAS
`ALTER TYPE ... ADD VALUE` repoda **hech qayerda yo'q**; `deploy_cash_schema` sxema mavjud
bo'lsa DDL'ni qayta yuritmaydi (`deploy.py:43-45`). Dizayn faqat mavjud qiymatlarni
ishlatadi: `PURCHASE`, `PURCHASE_OUT`, `CASH_OP`, `CASH_OUT`, `ADJUSTMENT`.

### 16.2 Yangi jadvallar `public`da — va kafolat chegarasi
`cash` sxemasiga production'da jadval **qo'shib bo'lmaydi** (16.1), shu bois yangi jadvallar
`public`da: model + `models/__init__` + boot `create_all`. Yangi **jadvallar** uchun
`_ensure_columns` yozuvi kerak emas; T1 qoidasi faqat **mavjud** jadvalga ustun
qo'shilganda — bu dizaynda bunday ustun **yo'q**.

**Ochiq e'tirof:** `public`da o'zgarmaslik triggeri **naqshi yo'q**, `initdb`da SQL trigger
yaratadigan qadam **yo'q**, jadvalni ilova roli yaratgani uchun **ilova o'zi ega** —
triggerni `DISABLE` qila oladi. Phase 1 kafolati: xizmat qatlami + qator-lokal CHECK'lar +
`REQUIRED_INDEXES` + kompozit FK'lar. Trigger va egalik — **K-savol**.

### 16.3 Yangi CHECK'larni qotirish (majburiy qadam)
`tests/check_renderings_pg.py:12-88` har CHECK uchun Postgres'ning **aynan** `pg_get_expr`
yozuvini (oddiy va pretty) talab qiladi; `tests/test_check_canon.py:40-45` har majburiy
CHECK uchun rendering bo'lishini, **`:69`** esa `len(RENDERINGS)` **literal sonini** talab
qiladi. Bu yozuvlar **qo'lda yozilmaydi** — reja **haqiqiy Postgres'dan rendering olish**
qadamini o'z ichiga oladi va `len(RENDERINGS)` literali yangilanadi.

⚠️ **1-tahrir «12 ta yangi CHECK» degan edi — YARIM hisob.** Shu tahrirdagi nomlangan
CHECK'lar: `purchase_settlements` **12**, `creditors` **5**, `creditor_ledger` **6**,
`creditor_repayments` **1**, `creditor_advance_allocations` **1**, `owner_advance_open`
**4**, `cash_account_openings` **2** → **jami 31**. Noto'g'ri sanoq bilan reja tuzilsa
qotirish qadami yarim hajmda bajarilib, qolganlari §16.3 ning o'zi ogohlantirgan holatda
qolardi.

**Barcha CHECK ifodalari funksiyasiz** (§1.1) — bu **majburiy dizayn cheklovi**, uslub emas.

### 16.4 Eski klientlar
Eski Manager/mobil `payment: "cash"|"credit"` (`receiving.py:240`) yoki
`status: "received"|"debt"` (`schemas/purchase.py:31`) + `cash_account_id` yuboradi. Yangi
`settlements[]` **ixtiyoriy**: berilmasa server eski yo'lni yuritadi. Eski klient
buzilmaydi; mavjud hujjatlar tegilmaydi.

### 16.5 SQLite
`cash` jadvallari mahalliy bazada yo'q; `cash_enabled()` non-Postgres'da naqd yozuv yo'lini
yopadi; FK majburlanmaydi (`sqlite-fk-yoq`).
⚠️ **CHECK esa majburlanadi — va undan muhimi: CHECK ifodasidagi NOTANISH FUNKSIYA jadval
yaratishni YIQITADI** (§1.1). 1-tahrirning «CHECK holati tasdiqlanmagan» formulasi xavfni
kamaytirib ko'rsatgan edi. Qismiy indekslar ikki dialektga ham e'lon qilinishi shart
(§1.2).

---

## 17. Test matritsasi

**PG majburiy** (`pgserver`, `pg` fixture). Alohida **SQLite boot testi**: yangi modellar
bilan `python -m app.initdb` SQLite'da **yiqilmaydi** (§1.1 regressiyasi).

### A. Identitet va idempotentlik
1. Bir xil tana ikki marta → bitta hujjat, bitta oyoq to'plami, `leg_no` o'zgarmagan.
2. `SETTLEMENT_CONFLICT`: ayni hujjat `client_uuid` + boshqa summa.
3. `max+1` regressiya qo'riqchisi: takroriy split leg 2/3 yaratmaydi.
4. **Ikki xil kreditordan ikki `OWNER_ADVANCE`** → `leg_no` deterministik (§2.1).
5. Ayni kreditordan ikkinchi PAYMENT (ayni revizyada) → `ux_ps_cred_party` rad.
6. **`OWNER_ADVANCE` bor hujjatda naqd oyoqni REVERSAL qilish** → `leg_no` to'g'ri, xom
   `IntegrityError` «duplicate» deb **yutilmaydi** (§2.3).
7. REVERSAL summasi asl summadan farq qilsa → kompozit FK rad (§2.4).
8. `PAYMENT(A) → REVERSAL → PAYMENT(A)` yangi revizyada → **muvaffaqiyat** (§2.2).
9. Avans oyog'i takrori → tana solishtirilib `SETTLEMENT_CONFLICT` (§2.5).

### B. Konkurrentlik (`_concurrent`, `threading.Barrier`)
10. Ayni SEYFdan ikki parallel to'lov → biri `INSUFFICIENT_CASH`, manfiy qoldiq YO'Q.
11. Seyf+kassa juftini teskari tartibda → deadlock yo'q.
12. Ayni kreditorga parallel avans → `balance` yo'qotilgan yangilanishsiz.
13. Ayni kreditorga parallel qaytarish → ikkinchisi `OVER_REPAYMENT`.
14. **Qulf darajasi qo'riqchisi:** FK INSERT (KEY SHARE) + `FOR UPDATE` = deadlock,
    `FOR NO KEY UPDATE` = deadlock yo'q (§10.2).
15. Ikki kreditorli hujjat teskari tartibda → saralash konvensiyasi to'sadi.
16. `name_key` get-or-create poygasi → `IntegrityError` retry, ikkinchi qator YO'Q.
17. **`pay_supplier` bilan parallel settlement** → deadlock yo'q (Bosqich 0 dan keyin).

### C. Invariantlar (adversarial)
18. `total ≠ Σ(legs) + unpaid` → rad. 19. Ortiqcha to'lov → rad. 20. `amount = 0`/manfiy →
rad. 21. `SAFE_CASH` + `cash_account_id=NULL` → rad. 22. `OWNER_ADVANCE` +
`cash_account_id` → rad. 23. `OWNER_ADVANCE` + `creditor_id=NULL` → rad. 24. Snapshot
NULL/bo'sh → rad. 25. Naqd oyoq + `ledger_entry_id=NULL` → rad; qiymat **shu tranzaksiyada
yaratilmagan** bo'lsa → xizmat rad (§1.2). 26. `repaid_amount + closed_amount > amount`
to'g'ridan-to'g'ri UPDATE bilan → CHECK rad. 27. `balance < 0` / `balance_after < 0` → rad.
28. `ADJUST_*` sababsiz/`ref_type`siz → rad. 29. **REVERSAL oyog'iga `owner_advance_open`
qatori** → kompozit FK rad (§5.4). 30. Allokatsiya yig'indilari tengligi buzilsa →
tranzaksiya rad (§5.2). 31. Kesh ↔ daftar drifti → rollback (§5.7). 32. Cross-tenant va
cross-valyuta kompozit FK'lar → rad.

### D. Custody domeni
33. Ochiq smena + SEYFdan to'lov → MUVAFFAQIYAT, `OFF_SHIFT`, `shift_id=NULL`.
34. Ochiq smena + **boshqa kassirning TILLi** → `ERR_TILL_SHIFT_MISMATCH` (global
yumshatish YO'Q). 35. Ochiq smena + shu smenaning TILLi → `ON_SHIFT` + `shift_id`.
36. Smenasiz + post-T0 + hisobsiz → `ERR_CUSTODY_REQUIRED`. 37. `SHIFT_BOUND` (sotuv) —
o'zgarmagan. 38. Domeni e'lon qilinmagan chaqiruv → `SHIFT_BOUND`. 39. Arxivlangan/boshqa
filial/boshqa valyuta → rad. 40. Gibrid: TILL `ON_SHIFT` + SEYF `OFF_SHIFT` bitta hujjatda.
41. **preview ↔ yozuvchi PARITY:** `TREASURY` + ochiq smena → `decide()` SEYFni `options`da
qaytaradi va yozuvchi uni qabul qiladi (§7.2 dagi 8-chaqiruv).

### E. SEYF ochilishi
42. Ikki marta → rad. 43. `counted <= balance` → xato, `IN` yozilmaydi.
44. `attestation_ref`/`attested_by` yo'q → rad. 45. Menejer bo'lmagan xodim → rad.
46. Ochilishdan keyin SEYFdan to'lov → muvaffaqiyat (zanjirning uchdan-uchi).
47. **Parity:** `RECONSTRUCTION` ochilish legi `EXTRA_LEDGER` **bo'lmaydi** (kod
o'zgarishisiz — §12.2-5).

### F. Kreditor hayot davri va atributsiya
48. Ochiq qoldiqli kreditorni arxivlash → `CREDITOR_HAS_BALANCE`; qoldiq **§5.7
ifodasidan**. 49. Arxivlangan: tanlagichda YO'Q, kartasi/daftari O'QILADI. 50. Havolali
kreditor + xodim soft-delete/`terminated`/rol o'zgarishi → kreditor o'zgarmaydi.
51. Xodimsiz kreditor (investor) → ishlaydi. 52. Rename → eski hujjat eski nomni
ko'rsatadi; audit `before/after`. 53. **Orqa bo'shliqli nom ham BAND** (`name_key`).
54. **Rename'dan keyin eski nom BAND qoladi** (`creditor_name_keys` — §3.5).
55. Snapshot **so'rov tanasidan olinmaydi**. 56. `ARCHIVED` kreditorga avans → 409.
57. `UNIQUE (company_id, employee_id)` → ikkinchi kreditor rad. 58. `unlink` daftarga
tegmaydi. 59. `creditor_referenced()` true → hard delete rad. 60. **Cross-tenant:** A
kreditori B xodimiga havola → rad. 61. `tenant_purge`: B ni purge A kreditorini
o'chirmaydi. 62. Yangi jadvallar FK grafida yoki `SEMANTIC_REGISTRY`da — aks holda
`PURGE_BLOCKED`.

### G. Qaytarish va allokatsiya
63. Qarzdan ko'p qaytarish → **409 `OVER_REPAYMENT`**, clamp YO'Q. 64. FIFO allokatsiya
deterministik; takrorda ayni to'plam. 65. `ledger_entry_id` majburiy → naqd yozilmasa butun
hodisa rad. 66. `client_uuid` yubormaslik → **400**. 67. (b) «bevosita sherikga qaytdi» →
`ADJUST_DOWN` + allokatsiya, **naqd qimirlamaydi**. 68. (c) avans bekor → `ADJUST_DOWN` +
kuzatuv yopiladi. 69. **Transfer (§3.6):** `ADJUST_DOWN`+`ADJUST_UP` juftligi, manba
avanslari yopiladi, drift **rollback QILMAYDI**, manba arxivlanadi. 70. Butun-som: 0.01
qoldiq bilan avans yopiladi. 71. Boshqa valyuta → `CURRENCY_MISMATCH`. 72. **Z-hisobot:**
ochiq smenali TILL'dan qaytarish → `CashMovement(payout)` yozilgan, soxta ortiqcha YO'Q
(§5.9).

### H. Ruxsatlar
73. Kassir `kreditor.*` ni rol bo'yicha olmaydi. 74. `PATCH
/employees/{id}/permissions` bilan kassirga `kreditor.repay` → B-savol javobiga ko'ra
rad/ruxsat; **tanlangan xatti-harakat qotiriladi** (`employees.py:658-659` naqshi).
75. Administrator `require()` dan avtomatik o'tadi — ega-only tanlansa
`effective_permissions` darvozasi to'sadi. 76. `reports.py` kreditor qoldig'ini
qaytarmaydi. 77. **`GET /audit`** `hisobot.view` bilan `entity='creditor'` qatorlarini
**qaytarmaydi** (§3.7).

### I. Regressiya
78. Mavjud naqd qabul (bitta TILL) — bit-ba-bit o'zgarmagan. 79. Eski klient shakli →
bitta oyoq. 80. `purchases.cash_account_id`: bitta naqd oyoqda yoziladi, splitda NULL.
81. Settlement oyog'i bor hujjat `PATCH` → `409 SETTLEMENT_EDIT_UNSUPPORTED` (§9).
82. Schema guard T1–T4 yashil; yangi indekslar `REQUIRED_INDEXES` da, `OPTIONAL_UNIQUE` da
**emas**. 83. **31 ta CHECK** `check_renderings_pg.py` + `test_check_canon.py` da;
`len(RENDERINGS)` literali yangilangan. 84. `check_canon.canonical()` har yangi CHECK
ifodasini **tahlil qiladi** (funksiya yo'q). 85. Xato kodlari ru/uzc lug'atida; desktop
`api.ts` dict `detail`ni to'g'ri o'qiydi. 86. **Split xarid parity'si**: kutilgan oyoqlar
`purchase_settlements` dan qurilgan, `WRONG_AMOUNT`/`EXTRA_LEDGER` YO'Q (§5.1).

> ⚠️ Testlarni `PYTHONIOENCODING=utf-8` bilan yurgizmang — `test_check_defs_pg` cp1252
> subprocess sababli **yolg'on yiqiladi**.

---

## 18. Implementatsiya bosqichlari

| Bosqich | Mazmun | Oldingi shart |
|---|---|---|
| **0** | **`pay_supplier` qulf inversiyasini tuzatish** (§10.2) + `40P01` o'rami | — |
| **1** | SEYF ochilish qoldig'i mexanizmi (§12.2) + E guruhi | — |
| **2** | Custody domeni refaktori **+ 8-chi (o'qish) chaqiruv** (§7.2) + D guruhi, ayniqsa **#34** va **#41** | — |
| **3** | `purchase_settlements` + naqd manbalar + `revision` + A/B/C; tahrir darvozasi (§9); **`_purchase_out_legs` parity tuzatishi** (§5.1) | 0, 2 |
| **4** | Manager UX (§13) + `api.ts` dict-detail + i18n | 3 |
| **5** | Mobil UX (§14) | 4 |
| **6a** | `creditors` + `creditor_name_keys` + hayot davri + ruxsatlar + audit + `/audit` filtri — **pulsiz** | **A, B, H, I** |
| **6b** | `OWNER_ADVANCE` + `creditor_ledger` + `owner_advance_open` + F guruhi | 6a |
| **7** | `creditor_repayments` + allokatsiya + transfer + Z-hisobot qadami (§5.9) + G guruhi | 6b |
| **8** | Fayzanda **haqiqiy** «Asosiy seyf» + jismoniy sanoq + ochilish qoldig'i | 1–4 prod'da isbotlangan |

> **Bosqich 8 gacha Fayzan production'ida SEYF YARATILMAYDI.**

**Tavsiya:** 0–4 do'konning haqiqiy muammosini to'liq hal qiladi va **faqat K va J
savollariga** tegadi; 6a–7 (sherik qarzi) A, B, F, G, H, I ga bog'liq va 0–4 ni kutib
turishga majbur qilmasligi kerak.

---

## Ochiq qarorlar — SIZDAN javob kerak

| # | Savol | Nega men hal qila olmayman | Tavsiyam | Bloklaydi |
|---|---|---|---|---|
| **A** | `employees` ga **additiv** `UNIQUE (company_id, id)` qo'shishga ruxsatmi? | `tenant_purge` egalik yo'llarini **OR** bilan birlashtiradi (`tenant_purge.py:404`) → bir ustunli `employee_id` FK cross-tenant o'chirish xavfi beradi. Naqsh `public`da **allaqachon bor** (`customer_groups` + `customers`, `models/customers.py:33-36,44-53`), lekin `employees` ga DDL qo'shish — sizning qaroringiz | **Ha** — presedent bor va bu «xizmat qatlami tekshiradi»dan kuchli | 6a |
| **B** | Kreditor ruxsatlari **ega-only** mi yoki **beriladigan** mi? | `require()` administratorni avtomatik o'tkazadi (`deps.py:126-128`); override himoyasi naqshi **bor** (`employees.py:658-659`), uni kengaytirish siyosat qarori | **Ega-only** `kreditor.settle`/`kreditor.repay`; `kreditor.view` beriladigan | 6a |
| **F** | Kreditor yozuvi **mobilda** bo'ladimi? | Ha bo'lsa `permission_matrix.json` + Dart testi majburlanadi | **Yo'q** (Phase 1) | 5 / 6a |
| **G** | Rename'dan keyin UI **qaysi nomni** ko'rsatadi? | Karta jonli nomni, hujjat snapshotni ko'rsatadi → bitta shaxs ikki nom bilan chiqadi | Hujjatda **faqat snapshot**; kartada joriy nom + «hujjatlarda: …» | 4 / 6b |
| **H** | Kreditor kodlari `_PIN_FORBIDDEN_PERMS` ga kirsinmi? | 4 raqamli PIN ortida sherik qarzi qolishi — xavf siyosati | **Ha** (`settle`/`repay`) | 6a |
| **I** | Ruxsat kodi bootda yaratilmasa marshrutlar **fail-closed** bo'lsinmi? | `_ensure_catalog` try/except bilan **jim yiqiladi** (`initdb.py:1328-1331`) | **Ha** — 503, jim ruxsatsizlik emas | 6a |
| **J** | Legacy tenantda SEYF qoldig'i migratsiyada **REVIEW** emas **BLOCK** bo'lsinmi? | `MIGRATION_PHASE0.md:151` hozir REVIEW; Fayzanda zararsiz, boshqa do'konda emas | **BLOCK** | 1 |
| **K** | `public` dagi yangi jadvallarga **o'zgarmaslik triggeri** qo'yilsinmi, va **kim** DDL egasi? Shu bilan birga `ledger_entry_id` cross-schema FK bo'lsinmi? | Ilova o'zi ega bo'lsa triggerni `DISABLE` qila oladi → «himoya» yolg'on bo'ladi (§16.2) | **Phase 1 da trigger YO'Q**, FK'siz mantiqiy havola; alohida infra ishi | 3, 6b |
| **L** | Qaytarish **allokatsiya siyosati**: FIFO / proporsional / operator tanlaydi? | Purchase Return bu bosqichda yozilmaydi, lekin sxema javobni saqlaydi | **FIFO** (deterministik) | keyingi faza |

### Kod javob bergan yoki hujjat ichida YOPILGAN savollar

| Savol | Javob |
|---|---|
| Nechta ega/sherik? | **Sizning qaroringiz: bir nechta.** `creditor_id` majburiy (§3.0) |
| Xodim bo'lmagan qarz beruvchi? | **Qo'llab-quvvatlanadi** (`employee_id` nullable, §3.4-7) |
| Kompaniya yoki filial fakti? | **Kompaniya** (`reports.py:1717` presedenti) |
| **C** Manfiy kreditor balansi? | **YOPILDI: yo'q** — `CHECK (balance >= 0)` + `409 OVER_REPAYMENT` (§5.6) |
| **D** Ko'p valyutali kreditor? | **YOPILDI: yo'q** — bitta valyuta, kompozit FK bilan (§3.9) |
| **E** Butun som? | **YOPILDI: ha** — avans ham, qaytarish ham (§5.8) |
| 403 vs 409? | Server **403** beradi, mobil 409 kutadi va **mobil xato**. `sync.py:71` har 409 ni transient deb belgilaydi → statuslarni **o'zgartirmaymiz**, mobil ro'yxati tuzatiladi (§14) |
| Manfiy TILL override yuzasi? | `NEGATIVE_APPROVAL_REQUIRED` — **o'lik kod** (`posting.py:254-260` avvalroq 403 beradi; endpoint/DTO yo'q). **Tiriltirilmaydi** |
| `OPEN NEGATIVE_OVERRIDE` kim yopadi? | Override yuzasi yo'q ekan — **yuzaga kelmaydi** |

---

## Taqiqlarga rioya

- Kod **o'zgartirilmagan**, migratsiya **yozilmagan**, deploy **qilinmagan**.
- Fayzan production'i **read-only**; **SEYF ataylab YO'Q**; tartib o'zgarmagan: ochilish
  mexanizmi → hisob-turiga xos custody validatsiyasi → split infratuzilmasi →
  testlar/yarashtirish → **faqat shundan keyin** haqiqiy jismoniy sanoq bilan Fayzan SEYFi.
- **Soxta `CASH_IN` yo'q, yashirin balans mutatsiyasi yo'q** (§12.2).
- `OWNER_ADVANCE` **anonim kompaniya qarzi emas** — `creditor_id` majburiy (§3.0).
- Mavjud `Employee`/`Supplier`/`Customer` **noto'g'ri ishlatilmagan** (§3.1).
- `OWNER_CONTRIBUTION` **qo'shilmagan** (§4).
- Purchase Return semantikasi **implementatsiya qilinmagan** — faqat moslik (§15).
- Mavjud manfiy naqd himoyasi **chetlab o'tilmagan**; SEYF uchun fail-closed **ataylab**
  (§7.3).
- `ERR_TILL_SHIFT_MISMATCH` **global o'chirilmagan**; TILL shartnomasi bit-ba-bit saqlangan
  va D-34 testi bilan qotirilgan (§6, §7.2).
