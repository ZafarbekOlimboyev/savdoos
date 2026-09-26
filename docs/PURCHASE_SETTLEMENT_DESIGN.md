# Xarid to'lovi: SEYF + split settlement — DIZAYN (qattiqlashtirilgan)

> Holat: **DIZAYN. IMPLEMENTATSIYA QILINMAGAN.** Kod o'zgartirilmagan, migratsiya yozilmagan.
> Production tegilmagan; Fayzan SEYFi ATAYLAB YO'Q holatda qoldirilgan.
> Asos: `PURCHASE_SETTLEMENT_AUDIT.md` (sabab tahlili) + 6 linzali kod auditi.

---

## 0. Hal qiluvchi zanjir (eng muhim topilma)

Auditda «Fayzanda SEYF qatori yo'q» deb aytilgan edi. Kod auditi ko'rsatdi: **SEYF yaratish
o'zi kerakli oqimni BERMAYDI.** To'liq zanjir uch bo'g'inli va hozir **uchtasi ham uzilgan**:

| # | Bo'g'in | Hozirgi holat | Dalil |
|---|---|---|---|
| 1 | SEYF qatori mavjud bo'lishi | Fayzanda YO'Q (`{"TILL": 1}`) | production read-only probe |
| 2 | SEYFda **ledger qoldig'i** bo'lishi | **Kiritish NUQTASI YO'Q** | §12 |
| 3 | Ochiq smena SEYFdan to'lovni to'smasligi | `ERR_TILL_SHIFT_MISMATCH` to'sadi | `cutover_guard.py:394-401` |

2-bo'g'in nega o'lim nuqtasi: manfiy naqd qo'riqchisi qoldiqni butun hisob umri bo'yicha
`Σ(IN) − Σ(OUT)` deb hisoblaydi (`repositories.py:77-88`) va **SEYF uchun override MUTLAQO
yo'q** (TILL uchungina menejer tasdig'i bor, u ham amalda yuzasiz — §7.3). Ya'ni bo'sh SEYF
yaratilsa, undan har qanday to'lov **`INSUFFICIENT_CASH` (409)** bilan rad etiladi.

> **Agar faqat SEYF yaratilsa va ochilish qoldig'i kiritilmasa — do'kon egasi «seyf paydo
> bo'ldi, lekin hech narsa to'lay olmayapman» holatiga tushadi.** Bu implementatsiya
> tartibining majburiy sharti: **mexanizm → darvoza → ma'lumot** (§18).

---

## 1. Sxema taklifi — `purchase_settlements`

Sxema: **`public`** (sabab §16.2). Jadval **append-only** (§11).

```
purchase_settlements
  id                  uuid PK
  company_id          uuid NOT NULL -> companies.id        # yagona jonli FK
  purchase_id         uuid NOT NULL -> purchases.id
  leg_no              smallint NOT NULL                    # DETERMINISTIK, §2.1
  kind                varchar(8)  NOT NULL                 # PAYMENT | REVERSAL
  source              varchar(16) NOT NULL                 # TILL_CASH | SAFE_CASH | OWNER_ADVANCE
  cash_account_id     uuid NULL                            # faqat *_CASH uchun
  creditor_id         uuid NULL                            # faqat OWNER_ADVANCE uchun, §3
  amount              numeric(14,2) NOT NULL               # HAR DOIM > 0; ishora `kind`da
  ledger_entry_id     uuid NULL                            # naqd oyoq provenansi
  reverses_id         uuid NULL -> purchase_settlements.id
  client_uuid         uuid NULL
  created_at          timestamptz NOT NULL
  created_by          uuid NULL -> employees.id
```

Qator-lokal CHECK'lar (Postgres CHECK qatorlararo ishlamaydi — §10):

```
ck_ps_amount_pos     amount > 0
ck_ps_kind           kind   IN ('PAYMENT','REVERSAL')
ck_ps_source         source IN ('TILL_CASH','SAFE_CASH','OWNER_ADVANCE')
ck_ps_cash_iff       (source IN ('TILL_CASH','SAFE_CASH')) = (cash_account_id IS NOT NULL)
ck_ps_creditor_iff   (source = 'OWNER_ADVANCE')            = (creditor_id IS NOT NULL)
ck_ps_ledger_iff     (source IN ('TILL_CASH','SAFE_CASH')) = (ledger_entry_id IS NOT NULL)
ck_ps_reversal_iff   (kind = 'REVERSAL')                   = (reverses_id IS NOT NULL)
ck_ps_no_self_rev    reverses_id IS NULL OR reverses_id <> id
ck_ps_leg_nonneg     leg_no >= 0
```

`ck_ps_ledger_iff` — ataylab qattiq: naqd oyoq **ledgerga yozilmasa settlement qatori ham
yozilmaydi**. Bu auditda topilgan «kassa tegilmagan holda bajarildi» teshigini
(`purchases.py:959-964` da fail-closed yo'qligi) settlementga ko'chishiga yo'l qo'ymaydi.

Indekslar (boot'da **`OPTIONAL_UNIQUE` / `PERFORMANCE`** sinfida — prod boot bog'lanmasin):

```
ux_ps_leg           UNIQUE (purchase_id, leg_no)
ux_ps_client_uuid   UNIQUE (client_uuid) WHERE client_uuid IS NOT NULL
ux_ps_reverses      UNIQUE (reverses_id) WHERE reverses_id IS NOT NULL
ix_ps_purchase      (purchase_id)
ix_ps_creditor      (creditor_id) WHERE creditor_id IS NOT NULL
```

**`SUPPLIER_DEBT` settlement manbasi EMAS** — to'lanmagan qoldiq hosila (§9).

---

## 2. Settlement oyog'ining identiteti va idempotentligi

Naqd ledger biznes kaliti allaqachon oyoq indeksini ko'taradi:
`cle_uq_business UNIQUE (tenant_id, source_type, source_id, leg_index)`
(`cash_ddl_v1.sql:232`).

**Qaror:** yangi `cash_source_type` label QO'SHILMAYDI (sabab §16.1). Split oyoqlar mavjud
identitetda qoladi:

```
source_type = 'PURCHASE'          (mavjud)
source_id   = purchase.id
leg_index   = purchase_settlements.leg_no
category    = 'PURCHASE_OUT'      (mavjud)
```

Presedent bor: `on_cash_purchase_increase` ayni `source_id` ostida ikkinchi OUT legni
**boshqa hisobga** yozadi (`retrofit.py:400-427`).

### 2.1 `leg_no` NEGA `max+1` BO'LMAYDI (nozik nuqta)

`repositories.py:179-190` da mavjud oyoq ajratish `max(leg_index)+1`. Agar settlement shu
usulni olsa, **idempotentlik buziladi**: birinchi urinish leg 0/1 yozib commit qilsa,
takroriy so'rov 2/3 ni hisoblaydi — biznes kaliti mos kelmaydi, dublikat oldi-tekshiruvi
(`posting.py:90-105`) o'tib ketadi va **hujjat ikki marta to'lanadi**.

Shu bois `leg_no` **so'rov tanasidan deterministik** hisoblanadi:

```
kanonik tartib = sort by (source_rank, cash_account_id)
   source_rank: SAFE_CASH=0, TILL_CASH=1, OWNER_ADVANCE=2
leg_no = shu tartibdagi indeks (0,1,2,...)
```

Xossalari: bir xil tana → bir xil kalitlar → takror **DB darajasida** to'siladi;
tahrir/oshirish yo'lining `max+1` ajratishi settlement oyoqlaridan **yuqorida** qoladi
(ular keyin yaratiladi), demak to'qnashuv yo'q.

### 2.2 Dublikat javobi TANANI solishtirishi SHART

`CashPostingService` dublikatni kalit bo'yicha aniqlaydi, lekin **tanani solishtirmaydi**
(`posting.py:90-94, 424-431`) — ya'ni boshqa summali so'rov «to'lov allaqachon amalga
oshgan» degan **yolg'on muvaffaqiyat** olishi mumkin. Settlement xizmati qaytgan DUPLICATE
natijaning `amount` / `cash_account_id` / `direction`ini kutilgan oyoq bilan solishtiradi,
mos kelmasa **`SETTLEMENT_CONFLICT` (409)**. Posting servisining o'zi o'zgartirilmaydi
(regressiya xavfi).

### 2.3 Hujjat darajasi

Mavjud `ux_receivings_client_uuid` / `ux_purchases_client_uuid` o'z kuchida. Ayni
`client_uuid` + **boshqa tana** → konflikt, jim qayta ishlatish emas.

⚠️ Mavjud idempotentlik bloklari (`receiving.py:135`, `shifts.py:158`) xato **KODINI
tekshirmaydi**. Settlement endpointi bu naqshni ko'chirmaydi: faqat `DUPLICATE_*` /
`IntegrityError` yutiladi, aks holda haqiqiy `INSUFFICIENT_CASH` jimgina
«duplicate: true» bo'lib ketardi.

---

## 3. Kreditor identiteti — MAVJUD MODELLAR AUDITI

Brif talab qilganidek avval mavjud subyektlar tekshirildi. **Kanonik party/counterparty
modeli repoda YO'Q**; tashqi tomon sifatida faqat `Customer` va `Supplier`, ichki shaxs
sifatida `Employee` bor. «kreditor/creditor/counterparty» so'zlari kodda 0 marta uchraydi.

| Nomzod | Mexanik mos? | Semantik mos? | Rad etish sababi (dalil) |
|---|---|---|---|
| `Role.code = "ega"` | — | **YO'Q** | Rol — subyekt emas; **GLOBAL** jadval, `company_id` yo'q (`auth.py:12-19`, `initdb.py:1334-1381`) |
| `Employee` | ha | **YO'Q** | `delete_employee`da moliyaviy balans tekshiruvi YO'Q (`employees.py:501-533`) → majburiyat yetim qoladi; rol/status o'zgaradi (`:449-460`); filial doirasiga bog'lanadi (`deps.py:84-94`); xodim bo'lmagan qarz beruvchi umuman ifodalanmaydi |
| `Supplier` | ha | **YO'Q** | «tur» ustuni yo'q (`purchasing.py:13-21`) → ega xarid tanlagichlarida va ta'minotchi hisobotlarida oddiy yetkazuvchi bo'lib ko'rinadi; qaytarish ledgerda `SUPPLIER_PAYMENT/SUPPLIER_OUT` bo'lib tovar to'lovidan farqlanmaydi |
| `Customer` | qisman | **YO'Q** | Teskari qarz faqat manfiy `credit_balance` sifatida (`customers.py:189-192`); `code`/`group_id`/`loyalty_points` biriktirilgan, qarz hisobotini ifloslantiradi (`reports.py:1717-1736`) |

**Qaror: TOR yangi identitet.** Umumiy «party» abstraksiyasi ORTIQCHA — naqd ledger
allaqachon `source_type` polimorfizmiga ega, va mavjud kanonik entity yo'q.

```
creditors
  id           uuid PK
  company_id   uuid NOT NULL -> companies.id      # tenant DDL darajasida
  name         varchar(120) NOT NULL
  employee_id  uuid NULL -> employees.id          # FAQAT audit havolasi; identitet undan MUSTAQIL
  balance      numeric(14,2) NOT NULL DEFAULT 0   # > 0 = KOMPANIYA QARZDOR (Supplier konvensiyasi)
  is_active    boolean NOT NULL DEFAULT true
  created_at   timestamptz NOT NULL
  ux_creditors_company_name  UNIQUE (company_id, lower(name))
```

- **Ishora konvensiyasi:** `Supplier.balance` bilan bir xil (`> 0` = biz qarzdormiz).
  `Customer.credit_balance` **teskari** ishorani ishlatadi — bu farq shu yerda qayd
  etiladi, aks holda hisobotlarda jim xato beradi.
- **O'chirish invarianti:** `balance != 0` → o'chirish **rad** (`delete_supplier` naqshi,
  `purchases.py:236-239`). `delete_employee`da bu invariant yo'q — kreditor nega
  `Employee` bo'lmasligining aniq sababi ham shu.
- **Tenant doirasi:** `supplier_ledger`da `company_id` ham, `branch_id` ham YO'Q
  (`db/schema.sql:433-442`) — yangi jadval bu kamchilikni **takrorlamaydi**.

### ⚠️ Ochiq mahsulot qarori (Bosqich 6 ni bloklaydi)
Bir do'konda **nechta ega** bo'lishi mumkin? Kod cheklamaydi — faqat oxirgi faol egani
o'chirishni to'sadi (`employees.py:433-437`), `admin.py:580-582` esa ko'plikni nazarda
tutadi. Shu bois sxemada `creditor_id` **MAJBURIY**: `company_id` bilangina «KIMGA
qarzdor» savoliga javob berilmaydi.

---

## 4. Kreditor majburiyati daftari

`SupplierLedger` naqshi (denormalizatsiyalangan balans + append-only daftar), tuzatilgan
tenant doirasi bilan:

```
creditor_ledger
  id            uuid PK
  company_id    uuid NOT NULL -> companies.id
  creditor_id   uuid NOT NULL -> creditors.id
  type          varchar(12) NOT NULL          # ADVANCE | REPAYMENT | ADJUSTMENT
  amount        numeric(14,2) NOT NULL        # > 0, ishora `type`da
  balance_after numeric(14,2) NOT NULL
  ref_type      varchar(24) NULL              # 'purchase_settlement' | 'creditor_repayment'
  ref_id        uuid NULL
  created_at    timestamptz NOT NULL
```

`creditors.balance` RMW **`with_for_update()` qator qulfi ostida** (mavjud
`purchases.py:312`, `receiving.py:213` naqshi).

### OWNER_ADVANCE — naqd HARAKATLANMAYDI
Ega o'z cho'ntagidan to'lasa: **`CashLedgerEntry` YARATILMAYDI**, SEYFGA/KASSAGA soxta
`CASH IN` yozilmaydi. Faqat `purchase_settlements(source='OWNER_ADVANCE')` +
`creditor_ledger(ADVANCE)`. Shu bois avans uchun yangi `cash_source_type`/`cash_category`
label **kerak emas**.

> **`OWNER_CONTRIBUTION` (kapital qo'yilma) bu dizaynga KIRMAYDI.** Kontributsiyada
> kompaniya egasiga qarzdor emas; ikkalasini bitta qiymatga qo'shish buxgalteriya
> semantikasini buzadi.

---

## 5. Qarzni qaytarish (repayment) modeli

Avansni qaytarish — **alohida hodisa**, xariddan mustaqil.

```
creditor_repayments
  id               uuid PK
  company_id       uuid NOT NULL
  creditor_id      uuid NOT NULL -> creditors.id
  cash_account_id  uuid NOT NULL           # TILL yoki SAFE — custody qoidasi §6/§7
  amount           numeric(14,2) NOT NULL  # > 0
  ledger_entry_id  uuid NOT NULL           # FAIL-CLOSED
  client_uuid      uuid NULL  (UNIQUE partial)
  created_at, created_by
```

Naqd oyoq xaritasi — **yangi enum label kerak emas**:

```
direction='OUT', category='CASH_OUT', source_type='CASH_OP',
source_id = creditor_repayments.id, leg_index = 0
```

### ⚠️ Haqiqiy integratsiya xavfi
`compare_engine`da `CASH_OP` legining `source_id`si `cash_movements`da izlanadi; qator
topilmasa leg **`EXTRA_LEDGER`** («legacy manba yo'q») deb belgilanadi
(`compare_engine.py:76-81, 189-193`). Ya'ni `CASH_OP` ni yangi tashuvchi jadval bilan
qayta ishlatish **report parity'da yolg'on nomuvofiqlik** beradi. Shart: `compare_engine`
yangi tashuvchilarni tanishi (kichik kod o'zgarishi) **va** shu holat testda qotirilishi
(§17 E-28). Bu §12 dagi SEYF ochilishiga ham AYNAN tegishli.

Hisobot talabi: bu oyoqlar umumiy `CASH_OUT` ichida ko'milmasligi kerak — hisobotlar
`creditor_repayments` bilan join qilib ajratadi.

### Uchta holat — ikkitasi hozir modellanmagan
Ta'minotchi pulni qaytargan sahnada uch xil haqiqat bor:

| Holat | Kompaniya naqdi | Kreditor majburiyati | Modellangan? |
|---|---|---|---|
| (a) pul SEYFGA qaytdi, ega hali qarzdor | `IN` | o'zgarmaydi | ha |
| (b) pul bevosita EGAGA qaytdi | **qimirlamaydi** | kamayadi | **YO'Q** — bu `REPAYMENT` emas, kompaniya to'lamadi |
| (c) xarid bekor, avans ishlatilmadi | qimirlamaydi | kamayadi | **YO'Q** — settlement bekor semantikasi |

(b) va (c) uchun `type='ADJUSTMENT'` + `ref_type` ishlatiladi va **sabab majburiy**;
ularni `REPAYMENT` deb yozish kompaniya pul to'lagan degan yolg'on ma'no berardi.

---

## 6. TILL oyog'ining validatsiyasi — **bitta ham qoida yumshatilmaydi**

TILL uchun hozirgi shartnoma **bit-ba-bit saqlanadi**:

1. hisob mavjud, `type='TILL'`, `status='ACTIVE'`, ayni tenant, ayni filial, valyuta mos
   (`require_custody_account`);
2. ochiq smena bo'lsa — TILL **aynan shu smenaning kassasi** bo'lishi SHART; boshqa
   kassirning yashigi **`ERR_TILL_SHIFT_MISMATCH`** bilan rad etiladi
   (`cutover_guard.py:394-401`);
3. post-T0 `till_id=NULL` legacy smena → `ERR_LEGACY_SHIFT_NEEDS_TILL`;
4. yopilgan smenaga replay → rad (`reject_closed_shift_replay`);
5. leg `ON_SHIFT` bo'lib `shift_id` oladi — aks holda `UNRESOLVED_OFF_SHIFT` anomaliyasi
   qolardi (`posting.py:325-327`).

> **`ERR_TILL_SHIFT_MISMATCH` GLOBAL O'CHIRILMAYDI va kuchsizlantirilmaydi.**

---

## 7. SAFE oyog'ining validatsiyasi + smena domeni

### 7.1 Sxema SEYFni ALLAQACHON smenasiz deb modellaydi
Bu xizmat qatlamining fikri emas, **bazaning invarianti**:

- `cle_posting_shift CHECK`: `OFF_SHIFT ⟺ shift_id IS NULL` (`cash_ddl_v1.sql:204-207`);
- `cle_shift_fk`: smena **ayni hisobga** tegishli bo'lishi shart (`:225-226`) — SEYF esa
  hech qachon smena ochmaydi (`:129`);
- jadval izohi (`:241`): *"SAFE legs are always OFF_SHIFT (SAFE owns no shift)"*.

### 7.2 Qaror: operatsiyaning **custody DOMENI** e'lon qilinadi
Bitta joyda (`custody_preview.OP_*` yonida) har operatsiya domeni belgilanadi:

| Domen | Ma'nosi | Misollar |
|---|---|---|
| `SHIFT_BOUND` | kassirning yashik seansi qismi | sotuv, sotuv qaytarishi, smena kassa kirim/chiqimi |
| `TREASURY` | kompaniya pulining harakati; kassir navbatda bo'lishi ahamiyatsiz | **xarid/qabul to'lovi**, ta'minotchi to'lovi, kreditorga qaytarish |

`TREASURY` uchun:

- hisob **SAFE** bo'lsa → ochiq smena **ahamiyatsiz**; leg `OFF_SHIFT`, `shift_id=NULL`
  (sxemaning o'z qoidasi). `TILL_SHIFT_MISMATCH` **qo'llanmaydi** — u boshqa turdagi
  hisob haqidagi qoida;
- hisob **TILL** bo'lsa → §6 dagi shartnoma **to'liq**, o'zgarishsiz;
- post-T0 explicit hisob berilmasa → `ERR_CUSTODY_REQUIRED`, o'zgarishsiz;
- `SHIFT_BOUND` operatsiyalar uchun **hech narsa o'zgarmaydi**.

> Bu **«smena xavfsizligini yumshatish» EMAS.** Yumshatish — bu bir xil hisob turi uchun
> shartni kamaytirish. Bu yerda TILL sharti o'zgarmaydi; faqat **SEYFga TILL qoidasini
> qo'llash to'xtatiladi**, chunki baza SEYFni smenasiz deb belgilagan. Amaldagi nuqson:
> hozir tizim «seyfdan to'lash uchun kassir smenasini yoping» deb talab qiladi — bu
> jismoniy haqiqatga ham, sxemaga ham qarshi.

Chaqiruv joylari: `resolve_cash_custody` 8 joyda ishlatiladi (`customers.py:379`,
`purchases.py:429/956/982/1070`, `receiving.py:439`, `lot_correction.py:676`) +
`require_post_t0_till` sotuvda (`sales.py:183`). Domen e'loni **qo'shimcha** parametr
bo'lib, e'lon qilinmagan chaqiruv `SHIFT_BOUND` (eng qattiq) deb qabul qilinadi —
fail-closed default (`fail-open-defaults` qoidasi).

### 7.3 SAFE uchun manfiy qoldiq — QAT'IY fail-closed
SEYF uchun `allow_negative` override **yo'q** (servis + DDL `CF-D5` ikkisi ham TILL'ga
bog'langan). Bu **ataylab shunday qoldiriladi**: mavjud manfiy naqd himoyasi chetlab
o'tilmaydi. Natija — §0 dagi zanjir: ochilish qoldig'i bo'lmasa to'lov
`INSUFFICIENT_CASH` bilan rad etiladi, va bu **to'g'ri** xatti-harakat.

---

## 8. `CashPostingService` xaritasi

| Settlement manbasi | Ledger oyog'i | Hisob | `posting_kind` / `shift_id` | Kutilayotgan naqd |
|---|---|---|---|---|
| `TILL_CASH` | `OUT · PURCHASE_OUT` | tanlangan TILL | `ON_SHIFT` / smena id | **−summa** |
| `SAFE_CASH` | `OUT · PURCHASE_OUT` | tanlangan SAFE | `OFF_SHIFT` / `NULL` | ta'sir yo'q |
| `OWNER_ADVANCE` | **yozuv yo'q** | — | — | ta'sir yo'q |

`CashPostingService` **yagona yozuvchi** bo'lib qoladi; parallel «purchase cash balance»
tizimi yaratilmaydi; to'g'ridan-to'g'ri `INSERT` (backfill naqshi) **taqiqlanadi** — u
manfiy qo'riqchini butunlay aylanib o'tadi (DB darajasida manfiy qoldiq invarianti YO'Q).

---

## 9. Ta'minotchi qarzi xaritasi

```
unpaid = purchase.total − Σ(PAYMENT.amount) + Σ(REVERSAL.amount)
```

`unpaid > 0` → `sup.balance += unpaid` + `SupplierLedger(charge, unpaid, ref_type=
'receiving'|'purchase', ref_id=...)`, balans **qator qulfi ostida** (mavjud naqsh).

### ⚠️ `_charged` ikkilik predikati gibrid hujjatni BUZADI
`purchases.py:881-906` hujjatni ikkilik tasniflaydi («ledgerga charge yozilganmi?»), QA
PR-004 esa naqd xaridda `paid_amount`ni **majburan `total`ga tenglaydi**. Gibrid hujjatda
(qismi naqd, qismi qarz) bu ikki qoida bir-biriga zid: `_charged` TRUE bo'lgani uchun
naqd ulush umuman qaytarilmaydi va butun delta `SupplierLedger`ga ketadi.

**Qaror (Phase 1 doirasi):** gibrid hujjat uchun `PATCH /purchases/{id}` **bloklanadi**
(`409 HYBRID_EDIT_UNSUPPORTED`); tuzatish Phase 5D da qotirilgan **reversal +
replacement** yo'li bilan boradi (§11). `_charged` ni qayta ta'riflash alohida ish, chunki
u sotuv/qaytarish/hisobot yo'llariga ham tegadi.

`paid_amount` **manbalar bo'yicha ajratiladi**: `paid_cash = Σ(*_CASH)`,
`paid_owner = Σ(OWNER_ADVANCE)`. Aks holda hujjat kamaytirilganda kod ega cho'ntagidan
kelgan pulni kassaga `IN` qilib **fantom naqd** yaratadi (ledgerda mos `OUT` yo'q).

---

## 10. Atomik tranzaksiya chegarasi

Bitta DB tranzaksiyasi: hujjat + qatorlar + **barcha** settlement oyoqlari + **barcha**
ledger oyoqlari + ta'minotchi qarzi + kreditor daftari. Har qanday qisman xato → **butun
ROLLBACK** (`CashPostingError` ham).

- **Qulf tartibi:** ikki hisobga yozilsa, `cash_accounts` qatorlari **`id` bo'yicha
  saralanib** qulflanadi (`post_transfer` naqshi, `posting.py:187-189`) — aks holda
  seyf+kassa juftida deadlock. Mavjud bir-hisobli `post()` bu tartibni majburlamaydi.
- **FK qulfi tuzog'i:** FK'li `INSERT` `KEY SHARE` oladi; keyin `FOR UPDATE` deadlock
  beradi — `FOR NO KEY UPDATE` ishlatiladi.
- **`commit=False` da tiklanish:** posting servisining `IntegrityError→DUPLICATE` o'girishi
  **faqat `commit=True`** shoxida (`posting.py:403-416`). Shu bois har oyoq **`SAVEPOINT`**
  (`db.begin_nested()`) ichida yoziladi; kalitlar deterministik bo'lgani uchun to'qnashuv
  aniq va qayta ishlanadigan.
- **Invariant DB CHECK bilan ushlanmaydi:** `total = Σ(legs) + unpaid` qatorlararo —
  Postgres CHECK qator-lokal. U xizmat qatlamida majburlanadi va §17 C guruhi bilan
  qotiriladi. `TRANSFER` dagi kabi deferred to'liqlik triggeri xarid oyoqlari uchun yo'q,
  `transfer_group_id` esa `cle_transfer_group_iff` sababli yaramaydi.

---

## 11. Tuzatish / reversal modeli

- `purchase_settlements` **append-only**: `UPDATE`/`DELETE` yo'q.
- `amount > 0` CHECK saqlanadi; teskari yo'nalish **`kind='REVERSAL'` + `reverses_id`**
  bilan ifodalanadi (manfiy summa emas). Bu auditda topilgan «immutability vs mutatsiya»
  to'qnashuvini hal qiladi: qaytarish `Purchase.total`ni o'zgartirsa ham settlement
  qatorlari **tahrirlanmaydi**.
- `ux_ps_reverses` → bir oyoqqa **ko'pi bilan bitta** reversal (ledgerdagi
  `cle_uq_reverses` naqshi, `cash_ddl_v1.sql:238`).
- Ledger tomonida reversal legi **yangi `source_id`** oladi — aks holda ikkinchi leg
  jimgina dublikat deb tashlanardi (`posting.py:90-94` + `leg_index=0` default).
- **Qisman qaytarish reversal EMAS** — u alohida hodisa (`PURCHASE_RETURN_identity.md`
  qarori o'z kuchida, `adapters.py:70`).

> ⚠️ **Append-only'ni ustun yo'qligi ISBOTLAMAYDI.** Kafolat: (a) xizmat qatlamida yozuv
> yo'lining yagonaligi, (b) qator-lokal CHECK'lar, (c) unique indekslar. DB trigger
> himoyasi **hozircha YO'Q** — §16.2.

---

## 12. SEYF ochilish qoldig'i — **ANIQ DIZAYN BO'SHLIG'I**

Brif shuni talab qildi: mavjud cutover/opening mexanizmi tekshirilsin va T0 dan keyingi
kanonik yo'l taklif qilinsin; yo'l bo'lmasa — bo'shliq deb aytilsin.

### 12.1 Topilgan holat
- T0 da **hech qanday** ochilish yozuvi yozilmaydi (`T0_CUTOVER_ENFORCEMENT.md:96` —
  *"Nothing is auto-mutated at T0"*); `cash_provision` faqat `cash_accounts` yaratadi,
  ledgerga yozmaydi. Demak **har qanday hisob T0 dan keyin qoldiq 0 bilan tug'iladi**.
- TILL uchun yo'l BOR: birinchi smena ochilishida `_delta = opening_cash − account_balance`,
  `_delta > 0` → `IN·OPENING` (`SHIFT_OPEN`, `ON_SHIFT`) (`retrofit.py:154-157`). Bu T0 dan
  keyin yaratilgan yangi TILL uchun ham ishlaydi (`tills.py:166`).
- SEYF uchun yo'l **YO'Q**: mexanizm smenaga bog'langan, SEYF esa smena ochmaydi.
  `POST /safes` (`tills.py:214`, `SafeCreate` — `tills.py:192-195`) summa qabul QILMAYDI; SEYFga pul faqat `TILL→SAFE`
  inkassa (`retrofit.py:443-455`) yoki smenasiz mijoz qarz to'lovi bilan kiradi.
- Sxema va adapterlar **tayyor** (`OPENING`/`ADJUSTMENT` kategoriyalari `cash_ddl_v1.sql:60`,
  `adapters.py:94-105`, SAFE → `OFF_SHIFT` `posting.py:320-323`), lekin ularni chaqiradigan
  **API/CLI yo'q**.

> **XULOSA: T0 dan keyin yaratilgan SEYFga jismoniy qoldiqni kiritishning kanonik yo'li
> ARXITEKTURADA YO'Q.** Bu implementatsiyadan oldin yopilishi shart — Bosqich 1.

### 12.2 Taklif — `POST /cash/accounts/{id}/opening`

Taqiqlarga to'liq rioya: yashirin balans o'rnatilmaydi, soxta sotuv/xarid yaratilmaydi,
jim `CASH IN` yozilmaydi. Buning o'rniga **ochiq, tasdiqlangan, bir martalik** yozuv.

Tashuvchi qator kerak, chunki mavjud `CASH_OP` manbasi — `public.cash_movements`, uning
`shift_id` esa **NOT NULL** (`shifts.py:37-40`), ya'ni smenasiz SEYF ochilishini ko'tara
olmaydi:

```
cash_account_openings
  id, company_id, cash_account_id UNIQUE, counted_amount, counted_at,
  attestation_ref  NOT NULL      # jismoniy sanoq dalili (akt/hujjat raqami)
  attested_by      NOT NULL -> employees.id
  ledger_entry_id  NOT NULL, created_at
```

Ledger oyog'i:

```
direction='IN', category='ADJUSTMENT', source_type='CASH_OP',
source_id = cash_account_openings.id, leg_index = 0,
provenance='RECONSTRUCTION', reconstruction_reason=..., reconstruction_source_ref=attestation_ref
```

Qarorlar va sabablari:

1. **`ADJUSTMENT`, `OPENING` emas.** `OPENING` hozir faqat `SHIFT_OPEN` bilan juftlashgan;
   yangi juftlik hisobot/parity kodidagi tekshirilmagan taxminlarni buzishi mumkin.
   `ADJUSTMENT` esa mavjud **menejer+ darvozasini** (`posting.py:253-258`) tayyor beradi.
2. **Miqdor semantikasi TILL bilan bir xil:** `amount = counted − balance`, hisob qatori
   qulfi ostida; `<= 0` → aniq xato. Ikki xil ochilish semantikasi paydo bo'lmaydi va
   inkassa kelgandan keyin qayta kiritish ikki marta hisoblanmaydi.
3. **Bir martalik:** `UNIQUE(cash_account_id)` tashuvchida + ledgerda `cle_uq_business`.
4. **Ruxsat va audit:** ega/menejer+ (`ADJUSTMENT` darvozasi) + `audit_logs` yozuvi.
   `attestation_ref` va `attested_by` **NOT NULL** — «pul yo'qdan paydo bo'ldi» holati
   hujjatsiz yozilmaydi. `provenance='RECONSTRUCTION'` reason+source_ref ikkisini
   majburlaydi (`cle_recon_prov`).
5. **`compare_engine`** yangi tashuvchini tanishi shart (§5 dagi ayni xavf).

### 12.3 Shu paketga kirishi kerak bo'lgan qo'shimcha bo'shliqlar
- **TILL qoldig'ini PASAYTIRISH yo'li ham yo'q:** manfiy delta ataylab yozilmaydi
  (`retrofit.py:159-163`) va uni kitobga oluvchi `ADJUSTMENT` endpointi mavjud emas. Agar
  ledger qoldig'i jismoniydan yuqori bo'lib qolsa (haqiqiy kamomad), tuzatish imkoni yo'q.
  Endpoint ikki yo'nalishni qoplasa — bu bo'shliq ham yopiladi.
- `reconcile_safe` (`lifecycle.py:118-131`) na endpoint, na CLI orqali chaqirilmaydi va
  farqni `PENDING` da qoldiradi — zanjir uzilgan.
- **Legacy tenantda SEYF qoldig'i backfillda YO'Q** va bu migratsiyada faqat REVIEW
  (`MIGRATION_PHASE0.md:151` — *"SAFE history without a physical count"*), BLOCK emas.
  Ya'ni T0 dan o'tgan do'konning seyfidagi pul ledgerda hech qachon ko'rinmaydi va bu
  migratsiyani to'xtatmaydi. Fayzan uchun bu hozir zararsiz (SEYF yo'q), lekin qoida
  sifatida tasdiqlanishi kerak.

---

## 13. Manager UX

Hozir: `packages/shared/src/screens/Products.tsx:1053-1059` da ikkilik `naqd | nasiya`
tugmasi; **naqd hisob tanlagichi umuman yo'q**, summa bo'linmaydi. Ekran `packages/shared`da,
lekin uni **faqat Manager** import qiladi (`apps/manager/src/App.tsx:5`) — POS ta'sirlanmaydi.

Taklif — **to'lov qatorlari** modeli:

```
┌ To'lov ────────────────────────────────────────────┐
│ Jami: 1 250 000                                    │
│                                                    │
│  [Asosiy seyf   ▾]  [   800 000 ]   (qoldiq: 2.1M) │
│  [Kassa #1      ▾]  [   200 000 ]   (qoldiq: 340k) │
│  [+ to'lov manbasi]                                │
│                                                    │
│  Qarzga qoladi:            250 000   (hosila)      │
└────────────────────────────────────────────────────┘
```

- Manbalar ro'yxati **serverdan**:
  `GET /cash/custody-preview?operation=receiving_payment` → `info.options` (bu yo'l
  allaqachon `list_tills + list_safes` qaytaradi — `custody_preview.py:96-97`).
- «Qarzga qoladi» — **hosila**, kiritilmaydi. `total − Σ(qatorlar)`; manfiy bo'lsa saqlash
  bloklanadi (ortiqcha to'lov rad).
- Eski ikkilik tugma **ko'chiriladi, qo'shilmaydi** (`ui-move-not-add`): `naqd` = bitta
  to'liq qator, `nasiya` = qatorsiz.
- Har qator yonida hisobning **mavjud qoldig'i** — `INSUFFICIENT_CASH` saqlashdan keyin
  emas, **oldin** ko'rinadi.
- `INSUFFICIENT_CASH` / `NEGATIVE_APPROVAL_REQUIRED` desktop lug'atida **yo'q**
  (`serverErrorsCash.ts`) — ru/uzc tarjimasi qo'shilmasa kirill do'kon egasi xom matn
  ko'radi. Fayzan uchun majburiy (`server-error-i18n`).
- Summalar **butun som** (`whole-som-payments`): kasr string yuborilmaydi.

---

## 14. Mobil UX

Asos **bor**: `custody_block.dart:69` `info.options`ni shartsiz chizadi, `:314` da alohida
«Seyf» yorlig'i/ikonkasi. Kerakli o'zgarishlar:

- bitta tanlovdan **qatorlar** ro'yxatiga o'tish (bitta qator = hozirgi xatti-harakat);
- offline navbatda `client_uuid` **hujjat uchun** saqlanadi, `leg_no` esa deterministik
  (§2.1) — takroriy sinxronizatsiya ikki marta to'lamasin;
- offline holatda qoldiq eskirgan bo'lishi mumkin: server rad etsa
  (`INSUFFICIENT_CASH`) UI hujjatni **yo'qotmasdan** qayta manba tanlashni taklif qiladi;
- mobil lug'atida `NEGATIVE_APPROVAL_REQUIRED` bor, desktopda yo'q — xato kodi
  shartnomasi ikki klientda birxillashtiriladi (§17 F).

---

## 15. Purchase Return — kelajakka moslik

> Bu bosqichda **Purchase Return semantikasi implementatsiya QILINMAYDI.** Bu yerda faqat
> sxemaning kelajakni bloklamasligi ta'minlanadi.

Bugungi holat: alohida «xarid qaytarish» amali yo'q — qaytarish `PATCH /purchases/{id}`
tahririning (yoki `POST /receiving/{id}/corrections`ning) yon ta'siri, summa
`_ret_amt = paid − new_total` (`purchases.py:936`), va pul **asl xarid emas, hozirgi
kontekst** bo'yicha hisobga tushadi: `Purchase.cash_account_id` ham, asl `OUT·PURCHASE_OUT`
oyog'ining hisobi ham hech qachon o'qilmaydi.

Sxema shu sababdan quyidagilarni **saqlaydi**:

- har oyoqning **o'z identiteti** (`purchase_id`, `leg_no`, `cash_account_id`,
  `ledger_entry_id`) — «qaysi pul qaysi hisobdan chiqqan» savoli javobsiz qolmaydi;
- `kind` / `reverses_id` — «qaysi oyoqqa qaytdi» javobini **saqlash joyi** mavjud;
- `paid_cash` va `paid_owner` ajratilgani — ega puli kassaga `IN` bo'lib fantom naqd
  yaratmasligi (§9).

Kelajakda hal qilinadi (hozir **ochiq**, lekin sxema bloklamaydi): allokatsiya siyosati
(FIFO / proporsional / operator tanlaydi); `Purchase.cash_account_id` taqdiri (deprecated
deb belgilanadimi); `custody_preview` uchun `purchase_return_cash` operatsiyasi (hozir
yo'q — `custody_preview.py:405-436`) va PATCH shakli; SEYFdan to'langan xarid qaytishi
(smena ochiq bo'lsa hozirgi kod jimgina smena TILLiga qaytaradi — bu §7.2 domeni bilan
birga hal qilinadi).

---

## 16. Migratsiya va orqaga moslik

### 16.1 Yangi enum label KERAK EMAS — bu ataylab
`ALTER TYPE ... ADD VALUE` repoda **hech qayerda yo'q**; `deploy_cash_schema` sxema mavjud
bo'lsa DDL'ni **qayta yuritmaydi** (`deploy.py:43-45`) va `force=True` hech qayerda
uzatilmaydi. Ya'ni **inkremental `cash` DDL migratsiya mexanizmi mavjud emas.** Shu bois
dizayn faqat mavjud qiymatlarni ishlatadi: `PURCHASE`, `PURCHASE_OUT`, `CASH_OP`,
`CASH_OUT`, `ADJUSTMENT`.

### 16.2 Yangi jadvallar `public`da — va kafolat chegarasi
`cash` sxemasi mos kelardi (`fn_block_mutation` + `fn_block_truncate` + 19 trigger +
privilege-twin + tashqi `migration owner`, `cash_ddl_v1.sql:540-552`), lekin production'da
unga jadval **qo'shib bo'lmaydi** (16.1). Shu bois yangi jadvallar `public`da: model +
`models/__init__` + boot `create_all` (Alembic yo'q).

**Ochiq e'tirof:** `public`da o'zgarmaslik triggeri **naqshi yo'q** (`receiving_corrections`
ham faqat docstring + unique indeks bilan himoyalangan), `initdb`da SQL trigger yaratadigan
qadam **yo'q**, va jadvalni ilova roli yaratgani uchun **ilova o'zi ega** bo'ladi — ya'ni
o'z triggerini `DISABLE` qila oladi. Bunday triggerni «himoya» deb atash yolg'on bo'lardi.
Phase 1 kafolati: xizmat qatlami + qator-lokal CHECK'lar + unique indekslar.

Alohida qaror talab qiladi (implementatsiyadan oldin): kim DDL bajaradi, kim ega;
trigger qo'shilsa `_ensure_lot_checks` naqshi (30 s qulf byudjeti, boot yiqilmaydi)
yangi bo'sh jadval uchun to'g'rimi yoki fail-closed kerakmi; `required_schema.py`
triggerlarni **umuman ko'rmaydi** (`/health/ready` yashil qolaveradi).

### 16.3 Eski klientlar
Eski Manager/mobil `cash_account_id` + `is_credit` yuboradi. Server ularni **bitta to'liq
settlement oyog'i** deb qabul qiladi (`is_credit=true` → oyoqsiz). Eski klient buzilmaydi.
Mavjud hujjatlar tegilmaydi; `purchases.cash_account_id` audit sifatida qoladi.

### 16.4 SQLite
`cash` jadvallari mahalliy bazada umuman yo'q; `cash_enabled()` non-Postgres'da naqd yozuv
yo'lini yopadi; SQLite FK'ni ham majburlamaydi (`sqlite-fk-yoq`). Demak mahalliy to'plam
split ledger oyoqlarini **ko'rmaydi** — kritik testlar haqiqiy PG'da (§17).

---

## 17. Test matritsasi (adversarial + PG konkurrentlik)

**PG majburiy** (`pgserver`, `pg` fixture).

### A. Identitet va idempotentlik
1. Bir xil tana ikki marta → **bitta** hujjat, **bitta** to'plam oyoq, `leg_no` o'zgarmagan.
2. Ayni `client_uuid` + **boshqa** summa → `SETTLEMENT_CONFLICT`, jim qabul emas.
3. `max+1` regressiya qo'riqchisi: ikki marta yuborilgan split **leg 2/3 yaratmaydi** (§2.1).
4. Dublikat tanasi mos kelmasa DUPLICATE **yolg'on muvaffaqiyat bo'lmaydi** (§2.2).
5. Haqiqiy `INSUFFICIENT_CASH` **`duplicate: true` bo'lib yutilmaydi** (§2.3).

### B. Konkurrentlik (`_concurrent`, `threading.Barrier`)
6. Ayni SEYFdan ikki parallel to'lov, qoldiq bittasiga yetadi → biri `INSUFFICIENT_CASH`,
   **manfiy qoldiq YO'Q**.
7. Seyf+kassa juftini teskari tartibda yozuvchi ikki tranzaksiya → **deadlock yo'q**.
8. Ayni ta'minotchiga parallel gibrid xarid → `sup.balance` yo'qotilgan yangilanishsiz.
9. Parallel kreditor avansi → `creditors.balance` izchil.

### C. Invariantlar (adversarial)
10. `total ≠ Σ(legs) + unpaid` holatini **yaratishga urinish** → har yo'lda rad.
11. Ortiqcha to'lov (`Σ > total`) → rad.
12. `amount = 0` yoki manfiy → CHECK rad.
13. `SAFE_CASH` + `cash_account_id=NULL` → CHECK rad.
14. `OWNER_ADVANCE` + `cash_account_id` berilgan → CHECK rad.
15. `OWNER_ADVANCE` + `creditor_id=NULL` → CHECK rad.
16. Naqd oyoq + `ledger_entry_id=NULL` → CHECK rad (fail-closed isboti).
17. `UPDATE`/`DELETE` — xizmat yo'li yo'q; trigger qo'shilsa `assert_rejects` naqshi.
18. Kreditor `balance != 0` → o'chirish rad.

### D. Custody domeni (eng nozik guruh)
19. **Ochiq smena + SEYFdan to'lov → MUVAFFAQIYAT**, leg `OFF_SHIFT`, `shift_id=NULL`.
20. **Ochiq smena + BOSHQA kassirning TILLi → `ERR_TILL_SHIFT_MISMATCH`** — global
    yumshatish sodir BO'LMAGANINI isbotlaydi.
21. Ochiq smena + **shu** smenaning TILLi → muvaffaqiyat, leg `ON_SHIFT` + `shift_id`.
22. Smenasiz + post-T0 + hisob berilmagan → `ERR_CUSTODY_REQUIRED`.
23. `SHIFT_BOUND` operatsiyalar (sotuv) — **hech narsa o'zgarmagan**, mavjud testlar yashil.
24. Domeni e'lon qilinmagan chaqiruv → `SHIFT_BOUND` (fail-closed default).
25. Arxivlangan / boshqa filial / boshqa valyuta hisob → rad (uch holat).
26. Gibrid: TILL oyog'i `ON_SHIFT`, SEYF oyog'i `OFF_SHIFT` — **bitta** hujjatda.

### E. SEYF ochilishi (§12)
27. Ochilish ikki marta → ikkinchisi rad (`UNIQUE` + biznes kaliti).
28. `counted <= balance` → aniq xato, `IN` yozilmaydi.
29. `attestation_ref` yoki `attested_by` yo'q → rad.
30. Menejer bo'lmagan xodim → rad.
31. Ochilishdan **keyin** SEYFdan to'lov → muvaffaqiyat (zanjirning uchdan-uchi, §0).
32. **`compare_engine` yangi tashuvchini `EXTRA_LEDGER` deb belgilamaydi** (report parity).

### F. Regressiya
33. Mavjud naqd qabul (bitta TILL) — xatti-harakat bit-ba-bit o'zgarmagan.
34. Eski klient shakli (`is_credit` + `cash_account_id`) → bitta oyoq (§16.3).
35. Gibrid hujjat `PATCH` → `409 HYBRID_EDIT_UNSUPPORTED` (§9).
36. `tenant_purge`: yangi jadvallar FK grafida yoki `SEMANTIC_REGISTRY`da — aks holda
    `PURGE_BLOCKED`.
37. Schema guard T1–T4 yashil; yangi indekslar `REQUIRED_*` da **emas**.
38. Xato kodlari ru/uzc lug'atida bor (`serverErrorsCash.ts`), desktop va mobil bir xil.

> ⚠️ Testlarni `PYTHONIOENCODING=utf-8` bilan yurgizmang — `test_check_defs_pg` cp1252
> subprocess sababli **yolg'on yiqiladi** (`local-pytest-utf8-pitfall`).

---

## 18. Implementatsiya bosqichlari

Tartib §0 dagi zanjirdan: **mexanizm → darvoza → ma'lumot.**

| Bosqich | Mazmun | Nega shu tartib |
|---|---|---|
| **1** | SEYF ochilish qoldig'i mexanizmi (§12.2) + `compare_engine` moslashuvi + E guruhi | Busiz SEYF yaratish foydasiz: har to'lov `INSUFFICIENT_CASH` |
| **2** | Custody domeni refaktori (§7.2) + D guruhi, ayniqsa **#20 regressiya qo'riqchisi** | Darvoza ochilmasa split'ning SEYF oyog'i ochiq smenada ishlamaydi |
| **3** | `purchase_settlements` + naqd manbalar + A/B/C; gibrid tahriri **bloklangan** (§9) | Naqd split — asosiy talab; egasiz ham to'liq qiymat beradi |
| **4** | Manager UX to'lov qatorlari (§13) + i18n | Fayzan kirill — xom matn qabul qilinmaydi |
| **5** | Mobil UX qatorlari (§14) | Desktop shartnomasi qotirilgandan keyin |
| **6** | `creditors` + `creditor_ledger` + `OWNER_ADVANCE` (§3, §4) | **Bloklovchi mahsulot qaroriga bog'liq** (pastda 1-savol) |
| **7** | `creditor_repayments` (§5) | 6 dan keyin ma'noga ega |
| **8** | Fayzanda **haqiqiy** «Asosiy seyf» + ochilish qoldig'ini kiritish | **ENG OXIRIDA**, 1–4 production'da isbotlangandan keyin |

> **Bosqich 8 gacha Fayzan production'ida SEYF YARATILMAYDI.** Hozir u ataylab YO'Q.

**Tavsiya:** Bosqich 3 gacha yetkazilgan qism do'konning haqiqiy muammosini (yetkazuvchiga
seyfdan to'lash) **to'liq hal qiladi**. Bosqich 6–7 (ega qarzi) mahsulot qaroriga
bog'liq va uni 3-ni kutib turishga majburlamaslik kerak.

---

## Ochiq qarorlar (mahsulot egasidan — taxmin qilinmaydi)

1. **Bir do'konda nechta «ega»/sherik bo'ladi?** — Bosqich 6 ni bloklaydi.
2. **Xodim bo'lmagan qarz beruvchi** (ega qarindoshi, investor) doiraga kiradimi?
3. **Kassir ega qarzini ko'rishi kerakmi?** — yangi ruxsat kodi kerak, hozir yo'q
   (`seed.py:42-58` da majburiyat ruxsati yo'q).
4. Majburiyat **kompaniya** faktimi yoki **filial** faktimi? (mijoz qarzi ataylab
   kompaniya fakti deb belgilangan — presedent bor, `reports.py:1717`)
5. Manfiy TILL override'iga **yuza** kerakmi? Hozir `allow_negative` uchun endpoint/DTO
   yo'q — menejer tasdig'i amalda yetib bo'lmaydi va `NEGATIVE_APPROVAL_REQUIRED` o'lik
   kod. Kerak bo'lmasa — o'lik yuza deb hujjatlashtiriladi.
6. Xato kodi shartnomasi: menejer emas + manfiy holatda server **403** beradi, mobil esa
   **409 `NEGATIVE_APPROVAL_REQUIRED`** kutadi. Qaysi biri to'g'ri?
7. `OPEN NEGATIVE_OVERRIDE` anomaliyasini kim va qanday yopadi? (yopish mexanizmi yo'q)

---

## Taqiqlarga rioya (shu hujjat doirasida)

- Kod **o'zgartirilmagan**, migratsiya **yozilmagan**, deploy **qilinmagan**.
- Fayzan production'i **read-only**; SEYF **ataylab YO'Q** holatda.
- `OWNER_CONTRIBUTION` **qo'shilmagan** (§4).
- Purchase Return semantikasi **implementatsiya qilinmagan** — faqat moslik (§15).
- Mavjud manfiy naqd himoyasi **chetlab o'tilmagan**; SEYF uchun fail-closed **ataylab**
  saqlangan (§7.3).
- Yashirin balans o'rnatish / soxta sotuv / soxta xarid / jim `CASH IN` — **yo'q**;
  ochilish qoldig'i faqat tasdiqlangan, bir martalik, menejer+ yozuvi (§12.2).
- `ERR_TILL_SHIFT_MISMATCH` **global o'chirilmagan**; TILL shartnomasi bit-ba-bit
  saqlangan va D-20 testi bilan qotirilgan (§6, §7.2).
