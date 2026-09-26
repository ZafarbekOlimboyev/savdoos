# Xarid to'lovi: SEYF + split settlement — DIZAYN (qattiqlashtirilgan)

> Holat: **DIZAYN. IMPLEMENTATSIYA QILINMAGAN.** Kod o'zgartirilmagan, migratsiya yozilmagan.
> Production tegilmagan; Fayzan SEYFi ATAYLAB YO'Q holatda qoldirilgan.
> Asos: `PURCHASE_SETTLEMENT_AUDIT.md` (sabab tahlili) + 14 linzali kod auditi (2 tur).
>
> **Qabul qilingan qaror (2026-09-27):** kompaniyada **BIR NECHTA ega/sherik** bo'lishi
> mumkin. `OWNER_ADVANCE` anonim kompaniya-darajali qarz sifatida modellanmaydi; har oyoq
> `company_id + creditor_id + amount` ni ANIQ olib yuradi. Batafsil — §3.

**Mundarija.** §0 hal qiluvchi zanjir · §1 settlement sxemasi · §2 oyoq identiteti ·
**§3 kreditor identiteti** · §4 majburiyat daftari · §5 qaytarish · §6 TILL validatsiyasi ·
§7 SEYF validatsiyasi va custody domeni · §8 ledger xaritasi · §9 ta'minotchi qarzi ·
§10 atomiklik, qulf, idempotentlik · §11 reversal · §12 SEYF ochilish qoldig'i ·
§13 Manager UX · §14 mobil UX · §15 Purchase Return · §16 migratsiya · §17 testlar ·
§18 bosqichlar · **Ochiq qarorlar (A–G)**

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
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  purchase_id            uuid NOT NULL -> purchases.id
  leg_no                 smallint NOT NULL                    # DETERMINISTIK, §2.1
  kind                   varchar(8)  NOT NULL                 # PAYMENT | REVERSAL
  source                 varchar(16) NOT NULL                 # TILL_CASH | SAFE_CASH | OWNER_ADVANCE
  cash_account_id        uuid NULL                            # faqat *_CASH uchun
  creditor_id            uuid NULL                            # faqat OWNER_ADVANCE uchun, §3
  creditor_name_snapshot varchar(120) NULL                    # faqat OWNER_ADVANCE uchun, §3.5
  amount                 numeric(14,2) NOT NULL               # HAR DOIM > 0; ishora `kind`da
  currency               char(3) NOT NULL                     # §3.9
  ledger_entry_id        uuid NULL                            # naqd oyoq provenansi
  reverses_id            uuid NULL -> purchase_settlements.id
  client_uuid            uuid NULL
  created_at             timestamptz NOT NULL
  created_by             uuid NULL -> employees.id
```

Qator-lokal CHECK'lar (Postgres CHECK qatorlararo ishlamaydi — §10.1):

```
ck_ps_amount_pos      amount > 0
ck_ps_kind            kind   IN ('PAYMENT','REVERSAL')
ck_ps_source          source IN ('TILL_CASH','SAFE_CASH','OWNER_ADVANCE')
ck_ps_cash_iff        (source IN ('TILL_CASH','SAFE_CASH')) = (cash_account_id IS NOT NULL)
ck_ps_creditor_iff    (source = 'OWNER_ADVANCE')            = (creditor_id IS NOT NULL)
ck_ps_cred_name_iff   (source = 'OWNER_ADVANCE')            = (creditor_name_snapshot IS NOT NULL)
ck_ps_cred_name_nb    creditor_name_snapshot IS NULL OR btrim(creditor_name_snapshot) <> ''
ck_ps_ledger_iff      (source IN ('TILL_CASH','SAFE_CASH')) = (ledger_entry_id IS NOT NULL)
ck_ps_reversal_iff    (kind = 'REVERSAL')                   = (reverses_id IS NOT NULL)
ck_ps_no_self_rev     reverses_id IS NULL OR reverses_id <> id
ck_ps_leg_nonneg      leg_no >= 0
```

`ck_ps_ledger_iff` — ataylab qattiq: naqd oyoq **ledgerga yozilmasa settlement qatori ham
yozilmaydi**. Bu auditda topilgan «kassa tegilmagan holda bajarildi» teshigini
(`purchases.py:959-964` da fail-closed yo'qligi) settlementga ko'chishiga yo'l qo'ymaydi.

Indekslar (boot'da **`OPTIONAL_UNIQUE` / `PERFORMANCE`** sinfida — prod boot bog'lanmasin):

```
ux_ps_leg         UNIQUE (purchase_id, leg_no)
ux_ps_client_uuid UNIQUE (client_uuid) WHERE client_uuid IS NOT NULL
ux_ps_reverses    UNIQUE (reverses_id) WHERE reverses_id IS NOT NULL
ux_ps_cash_party  UNIQUE (purchase_id, cash_account_id) WHERE kind='PAYMENT' AND cash_account_id IS NOT NULL
ux_ps_cred_party  UNIQUE (purchase_id, creditor_id)     WHERE kind='PAYMENT' AND creditor_id IS NOT NULL
ix_ps_purchase    (purchase_id)
ix_ps_creditor    (creditor_id) WHERE creditor_id IS NOT NULL
```

Oxirgi ikki noyob indeks **§2.1 determinizmining sharti**: bir xaridda bir manba (bir kassa
hisobi yoki bir kreditor) **ko'pi bilan bitta PAYMENT oyog'i** beradi. Bir sherik ayni xarid
uchun ikki marta pul bergan bo'lsa, u **bitta** avans (summasi qo'shilgan) sifatida
yoziladi: ikki qator qo'shimcha buxgalteriya ma'nosi bermaydi, ammo kanonik tartibni
noaniqlashtiradi.

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

### 2.1 `leg_no` determinizmi — TUZATILDI (ko'p kreditorli qaror buni ochib berdi)

`repositories.py:179-190` (`next_leg_index`) mavjud oyoq ajratish `max(leg_index)+1`. Agar
settlement shu usulni olsa, **idempotentlik buziladi**: birinchi urinish leg 0/1 yozib commit
qilsa, takroriy so'rov 2/3 ni hisoblaydi — biznes kaliti mos kelmaydi, dublikat
oldi-tekshiruvi (`posting.py:90-105`) o'tib ketadi va **hujjat ikki marta to'lanadi**.

Shu bois `leg_no` **so'rov tanasidan deterministik** hisoblanadi. **Avvalgi tahrirda tartib
`(source_rank, cash_account_id)` edi — bu NUQSON:** `OWNER_ADVANCE` da `cash_account_id`
NULL, ya'ni ikki xil kreditordan kelgan ikki avans oyog'i **ayni saralash kalitiga** tushib,
`leg_no` noaniq bo'lardi. To'g'ri tartib:

```
party      = COALESCE(cash_account_id, creditor_id)      # ck_ps_cash_iff / ck_ps_creditor_iff
                                                         # bo'yicha AYNAN bittasi NOT NULL
source_rank: SAFE_CASH=0, TILL_CASH=1, OWNER_ADVANCE=2
kanonik tartib = sort by (source_rank, party::text)
leg_no = shu tartibdagi indeks (0,1,2,...)
```

`party` to'liq tartib beradi, chunki `ux_ps_cash_party` va `ux_ps_cred_party` bir xaridda
bir `party` ni takrorlanmas qiladi. `::text` — repo konvensiyasi (`sorted(..., key=str)`:
`receiving.py:270`, `purchases.py:352`, `posting.py:188`); shu sabab **PK turi uuid bo'lishi
SHART** (integer PK bilan `"10" < "9"` tartibni jimgina buzardi).

Xossalari: bir xil tana → bir xil kalitlar → takror **DB darajasida** to'siladi;
tahrir/oshirish yo'lining `max+1` ajratishi settlement oyoqlaridan **keyin** keladi, demak
to'qnashuv yo'q.

**REVERSAL oyoqlari** `max+1` ishlatishi XAVFSIZ: ularning idempotentlik kaliti `leg_no`
emas, `ux_ps_reverses` (bir aslga bitta reversal) + tuzatish hujjatining `client_uuid`si.

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

## 3. KREDITOR IDENTITETI — qaror va sakkiz talab

### 3.0 Qabul qilingan qaror

- Kompaniyada **bir nechta ega/sherik** bo'lishi mumkin.
- `OWNER_ADVANCE` **anonim kompaniya qarzi EMAS**. Har oyoq javob beradi: *«BinOS
  kompaniyasi QAYSI SHAXSGA qancha qarzdor?»* — «kompaniya egalarga 5 000 qarzdor»
  **yaramaydi**.
- Bitta xarid **turli kreditorlardan bir nechta** `OWNER_ADVANCE` oyog'ini ko'tara oladi
  (`ux_ps_cred_party` faqat AYNI kreditorning takror oyog'ini to'sadi).
- Qaytarish **ayni kreditorga** havola qiladi va **faqat shu kreditor** qoldig'ini
  kamaytiradi (§5.2 allokatsiya).
- Kreditor **joriy foydalanuvchidan XULOSA QILINMAYDI** — hech bir yo'l `current_employee`
  ni kreditor deb qabul qilmaydi.

Misol (brifdan, 30 000 KGS):

| Oyoq | `source` | `party` | `leg_no` (§2.1) | Summa |
|---|---|---|---|---|
| 1 | `SAFE_CASH` | Asosiy seyf | 0 | 10 000 |
| 2 | `TILL_CASH` | Kassa #1 | 1 | 5 000 |
| 3 | `OWNER_ADVANCE` | **Sherik A** | 2 | 5 000 |
| — | ta'minotchi qarzi (hosila, §9) | — | — | 10 000 |

### 3.1 Mavjud modellar auditi — xulosa

Brif talab qilganidek avval mavjud subyektlar tekshirildi. **Kanonik party/counterparty
modeli repoda YO'Q**; «kreditor/creditor/counterparty» so'zlari kodda 0 marta uchraydi.

| Nomzod | Mexanik mos? | Semantik mos? | Rad etish sababi (dalil) |
|---|---|---|---|
| `Role.code = "ega"` | — | **YO'Q** | Rol — subyekt emas; **GLOBAL** jadval, `company_id` yo'q (`auth.py:12-35`); bitta do'konga xos rol yaratib bo'lmaydi |
| `Employee` | ha | **YO'Q** | `delete_employee` moliyaviy tekshiruvsiz soft-delete qiladi (`employees.py:501-533`); `status` (`active/suspended/terminated`) va rol beqaror (`:449-479`); har bootda eng eski faol administrator jimgina `ega` ga ko'tariladi (`initdb.py:1354-1380`); xodim bo'lmagan qarz beruvchi umuman ifodalanmaydi |
| `Supplier` | ha | **YO'Q** | «tur» ustuni yo'q (`purchasing.py:13-21`) → sherik xarid tanlagichlari va ta'minotchi hisobotlarida oddiy yetkazuvchi bo'lib ko'rinadi; qaytarish ledgerda `SUPPLIER_PAYMENT/SUPPLIER_OUT` bo'lib tovar to'lovidan farqlanmaydi |
| `Customer` | qisman | **YO'Q** | Teskari qarz faqat manfiy `credit_balance` (`customers.py:189-192`); `code`/`group_id`/`loyalty_points` biriktirilgan, qarz hisobotini ifloslantiradi (`reports.py:1717-1736`) |

→ **Tor, kompaniya-doirasidagi yangi kanonik kreditor subyekti.** Umumiy «party»
abstraksiyasi ORTIQCHA (naqd ledger allaqachon `source_type` polimorfizmiga ega).

### 3.2 `creditors` sxemasi

```
creditors
  id           uuid PK                            # uuid SHART (§2.1 saralash konvensiyasi)
  company_id   uuid NOT NULL -> companies.id
  name         varchar(120) NOT NULL
  phone        varchar(32) NULL
  employee_id  uuid NULL -> employees(id)         # IXTIYORIY havola, §3.4
  status       varchar(8) NOT NULL DEFAULT 'ACTIVE'   # ACTIVE | ARCHIVED, §3.3
  archived_at  timestamptz NULL
  balance      numeric(14,2) NOT NULL DEFAULT 0   # > 0 = KOMPANIYA QARZDOR; KESH (§5.7)
  currency     char(3) NOT NULL                   # §3.9
  note         text NULL
  created_at   timestamptz NOT NULL
  created_by   uuid NULL -> employees.id

ck_creditor_status       status IN ('ACTIVE','ARCHIVED')
ck_creditor_arch_iff     (status = 'ARCHIVED') = (archived_at IS NOT NULL)
ck_creditor_name_nb      btrim(name) <> ''
ck_creditor_bal_nonneg   balance >= 0                              # §5.6
ux_creditors_company_lower_name  UNIQUE (company_id, lower(name))  # QISMAN EMAS, §3.6
ux_creditors_company_employee    UNIQUE (company_id, employee_id) WHERE employee_id IS NOT NULL
```

**Ishora konvensiyasi:** `Supplier.balance` bilan bir xil (`> 0` = biz qarzdormiz).
`Customer.credit_balance` **teskari** ishorani ishlatadi — bu farq shu yerda qayd etiladi,
aks holda hisobotlarda jim xato beradi.

**Tenant doirasi:** `supplier_ledger`da `company_id` ham, `branch_id` ham YO'Q
(`db/schema.sql:433-442`) — yangi jadvallar bu kamchilikni **takrorlamaydi**.

**Majburiyat — KOMPANIYA fakti, filial fakti EMAS.** Presedent: mijoz qarzi ataylab
kompaniya fakti deb belgilangan (`reports.py:1717`). `creditors` da `branch_id` yo'q;
filialga biriktirilgan menejerning ko'rish huquqi §3.7 dagi ruxsat bilan boshqariladi,
ma'lumot doirasi bilan emas.

### 3.3 Hayot davri va arxivlash (talab 2)

Repoda **uchta zid mexanizm** bor: hard delete (faqat TILL — `tills.py:293-319`), soft
delete `deleted_at` (Supplier/Customer/Employee/Product), va arxiv `status` (naqd hisoblar —
`cash_ddl_v1.sql:50,70`). Kreditor uchun **BITTA o'q** tanlanadi: `status`.

Nega `deleted_at` EMAS:
- Product uchun soft-delete **nazoratsiz qaytariladi** (`catalog_commit_v2.py:291`,
  `migrator_1c/apply.py:253` — `p.deleted_at = None`, darvoza yo'q). Moliyaviy tarixli
  subyekt shu yo'l bilan jimgina tirilishi qabul qilinmaydi.
- Supplier telefon noyobligi `deleted_at IS NULL` bilan filtrlangan (`purchases.py:107-110`)
  → soft-delete'dan keyin **dublikat identitet ochiladi** va tarix ikki id'ga bo'linadi.
- `Supplier.is_active` / `Customer.is_active` — **o'lik ustunlar** (hech qayerda o'qilmaydi).
  Ikki o'qli hayot davri takrorlanmaydi: `is_active` YO'Q, `deleted_at` YO'Q.

**Holat mashinasi:**

| Amal | Shart | Natija |
|---|---|---|
| `create` | nom bo'sh emas, nom band emas | `ACTIVE` |
| `archive` | **ochiq qoldiq = 0** (daftardan hisoblangan, keshdan EMAS) | `ARCHIVED` + `archived_at` |
| `unarchive` | — | `ACTIVE`, `archived_at = NULL`, **audit majburiy** |
| `delete` (hard) | `creditor_referenced() = false` | qator o'chadi |
| `delete` (aks holda) | — | **400** + «arxivlang» (`tills.py:298-300` naqshi) |

⚠️ **Arxivlash darvozasi majburiy — TILL nuqsonini takrorlamaslik uchun.** `update_till`
arxivlashda qoldiqni tekshirmaydi (`tills.py:283-289`; `repo.account_balance` chaqirilmaydi),
natijada qoldiqli drawer arxivlansa `_resolve_account` `ACCOUNT_ARCHIVED` beradi
(`posting.py:281`) va **pul qamalib qoladi**. Kreditorda bu og'irroq: arxivlangan sherikka
qarz qolsa, uni **qaytarish yo'li yopilardi**. Shu bois ochiq qoldiq > 0 →
**409 `CREDITOR_HAS_BALANCE`**.

**O'qish qoidasi (muhim):** arxivlangan kreditorning **kartasi va daftari O'QILADIGAN
qoladi** (tarix bor), faqat **yangi avans tanlagichida chiqmaydi** (`active_only` filtri,
`tills.py:132-133` naqshi). Repoda bu ziddiyat allaqachon bor va takrorlanmasligi kerak:
`supplier_ledger` o'chirilgan ta'minotchini ko'rsatadi (`purchases.py:1131-1133`), lekin
`supplier_detail` **404** beradi (`:1155`).

### 3.4 Platforma foydalanuvchisiga IXTIYORIY havola (talab 3)

`creditors.employee_id` — **qulaylik va audit havolasi**, buxgalteriya identiteti EMAS.
Qat'iy shartlar:

1. Kreditor **hech qachon** `employee_id` bo'yicha aniqlanmaydi. Hisobot, qaytarish,
   settlement — hammasi `creditor_id` bilan ishlaydi.
2. Xodimdan kreditor **avtomatik yaratilmaydi**. Kreditor — ochiq operator qarori.
3. Xodim hayot davri hodisalari (`status` o'zgarishi, soft-delete, rol o'zgarishi, har
   bootdagi `ega` ko'tarilishi — `initdb.py:1354-1380`) kreditorga **hech qanday** ta'sir
   qilmaydi.
4. `UNIQUE (company_id, employee_id) WHERE employee_id IS NOT NULL` — bir shaxs ↔ ko'pi
   bilan bitta kreditor.
5. Havolani **uzish** (`unlink`) — audit hodisasi; birorta daftar/settlement qatoriga
   tegmaydi.
6. **FK bandi YO'Q** (`ON DELETE` yozilmaydi) — repo konvensiyasi (barcha moliyaviy
   havolalar `ON DELETE`siz: `db/schema.sql:585,624,807`, `cash_ddl_v1.sql:89,113,192`).
   `ON DELETE SET NULL` atributsiyani jimgina yo'qotardi; `CASCADE` esa qoldiqli kreditorni
   o'chirardi. Xodim API orqali hard delete BO'LMAYDI (`employees.py:528` — faqat
   `deleted_at`), demak band o'lik kod bo'lardi.
7. **Xodim bo'lmagan qarz beruvchi TO'LIQ QO'LLAB-QUVVATLANADI** (`employee_id IS NULL`):
   sherikning qarindoshi, investor, qo'shni do'kon.

> ⚠️ **BOSS QARORI TALAB QILINADI — `tenant_purge` kesishmasi (A-savol).**
> `tenant_purge.resolve()` bir jadvalning BARCHA egalik yo'llarini **OR** bilan
> birlashtiradi (`tenant_purge.py:404`: `ownership[node] = "(" + " OR ".join(preds) + ")"`
> — o'zim tasdiqladim). `creditors` da ikkita FK bo'lsa (`companies` va `employees`),
> B kompaniyani purge qilish egalik shartini
> `(company_id = B OR employee_id IN (SELECT id FROM employees WHERE company_id = B))`
> qiladi — ya'ni **A kompaniyaning kreditori** xato bilan B xodimiga havola qilsa, u
> B ni purge qilganda o'chib ketadi yoki purge'ni yiqitadi.
>
> Strukturaviy yechim: `employees` ga **additiv** `UNIQUE (company_id, id)` qo'shib,
> `creditors` da kompozit FK `(company_id, employee_id) -> employees(company_id, id)`
> ishlatish. `cash` sxemasi aynan shu naqshni ishlatadi (`cash_ddl_v1.sql:95-98,120-123`)
> va o'zi `employees` uchun «same-tenant check is SERVICE-LEVEL» deb tan oladi (`:36-39`),
> chunki hozir `employees` da bu UNIQUE **yo'q**.
>
> Muqobil (agar `employees` ga tegish rad etilsa): bir ustunli FK + xizmat qatlamida
> `employee.company_id == creditor.company_id` tekshiruvi + `creditors` ga DB trigger, VA
> `tenant_purge` OR-xavfi hujjatlashtiriladi. FK'siz «saqlanuvchi id» **tavsiya
> qilinmaydi** — u yolg'on id'larga yo'l ochadi.

### 3.5 O'zgarmas atributsiya va tarixiy nom (talab 4 va 8)

Repo nomni muzlatishni **faqat chek/sotuv yo'lida** qiladi: `Sale.cashier_name_snapshot`,
`branch_name_snapshot`, `till_code_snapshot`… (`models/sales.py:48-54`) va
`SaleItem.name_snapshot` (`:97-98`), qoida `services/receipt/dto.py:12-15` da
hujjatlashtirilgan: *ID'lar avtoritet, snapshotlar FAQAT tarixiy ko'rsatish uchun.*
Pul-kontragent tomonida snapshot **YO'Q** — `SupplierLedger` da na nom, na `company_id`
(`purchasing.py:123-131`), nom JOIN'dan olinadi, ya'ni rename qilinsa **tarix jimgina
qayta yoziladi**.

Kreditor uchun `SaleItem.name_snapshot` naqshi olinadi (`Sale.*_name_snapshot` naqshi EMAS
— u nullable + `or`-fallback, ya'ni fail-open):

1. `purchase_settlements.creditor_name_snapshot` — `ck_ps_cred_name_iff` bilan
   `creditor_id` bilan **ayni shartda majburiy** + bo'sh bo'lmaslik CHECK'i. Jadval YANGI
   va legacy qatorsiz, shu bois «additiv nullable» majburiyati bu yerda amal qilmaydi.
2. Ayni ustun `creditor_ledger` va `creditor_repayments` da ham **NOT NULL**.
3. **Snapshotni SERVER yozadi**, so'rov tanasidan OLINMAYDI — klient nomni to'qib
   yuborardi. Server `creditor_id` bo'yicha `creditors` qatorini **qulf ostida** (§10.2)
   o'qib nomni ko'chiradi; kreditor topilmasa yoki `ARCHIVED` bo'lsa **fail-closed** (409).
4. **O'qishda `or`-fallback YO'Q**: settlement/daftar/qaytarish ko'rinishlari nomni FAQAT
   snapshotdan oladi, `creditors.name` ga hech qachon qaytmaydi. Snapshot NOT NULL bo'lgani
   uchun fallback keraksiz va u rename sizishining yagona yo'li.
5. Uzunlik `creditors.name` bilan **aynan bir xil** (`varchar(120)`) — kesilish yo'q.
   Snapshot **original registrni** saqlaydi (`lower(name)` faqat noyoblik indeksida).
6. Rename **audit qilinadi**: `audit_log(..., before={"name": old}, after={"name": new})`.
   Repoda rename izi umuman yo'q (`delete_supplier` faqat o'chirishni yozadi,
   `purchases.py:243`) — bu darvoza shu yerda yopiladi.
7. **Shaxs kompaniyani tark etsa** — kreditor **arxivlanadi**, o'chirilmaydi (§3.3): nom
   `creditors` qatorida abadiy o'qiladi, hujjatlarda esa snapshotdan. Ikki qatlam birga
   8-talabni bajaradi.
8. Snapshot **hech qachon** `cash_ledger_entries.metadata` ga yozilmaydi (DDL: «non-
   authoritative») va `final_items[]` JSONB shakli takrorlanmaydi (sxema/CHECK yo'q).

### 3.6 Birlashtirish (merge) va o'chirish (talab 6)

**MERGE TAQIQLANADI.** Repoda subyekt birlashtirish mexanizmi umuman yo'q, va jim
birlashtirish **ataylab taqiqlangan**: `catalog_v2.py:38-49` («bu aynan taqiqlangan jim
birlashtirish bo'lardi»), `catalog_match.py:1-27` (identitet ziddiyati `AMBIGUOUS` bo'lib
operator qaroriga chiqadi).

- **Oldini olish:** `ux_creditors_company_lower_name` — **qisman EMAS**. Arxivlangan
  kreditor ham indeksda qoladi, aks holda nom bo'shab, ikki turli kreditor bitta tarixiy
  nomni ulashadi va snapshot noaniqlashadi. (`receiving_corrections` da noyob indeks aynan
  shu sababdan qismiy qilinmagan — `models/receiving.py:50-56`.)
- Band nomga urinish → **409 `CREDITOR_NAME_TAKEN`**; arxivlangan bo'lsa javob
  «qayta faollashtiring yoki boshqa nom» qarorini beradi — **jim unarchive YO'Q**.
- **Xato bilan ikki kreditor yaratilgan bo'lsa** yechim merge emas: biri arxivlanadi va
  qoldig'i **aniq juftlik** bilan ikkinchisiga o'tkaziladi —
  `creditor_ledger(type='ADJUSTMENT', ref_type='creditor_transfer')` manba tomonda (−) va
  maqsad tomonda (+), sabab majburiy. **Hech qanday qator qo'shilmaydi**, va
  `purchase_settlements` dagi tarixiy `creditor_id` **hech qachon qayta yozilmaydi** —
  o'zgarmas atributsiya (talab 4) shuni talab qiladi.
- **Hard delete** faqat `creditor_referenced() = false` (`purchase_settlements`,
  `creditor_ledger`, `creditor_repayments`, `creditor_repayment_allocations` da 0 havola) —
  ya'ni xato kiritilgan, hech qachon ishlatilmagan qator. `till_referenced()` naqshi
  (`tills.py:306-319`). Aks holda **400 + arxivlash**.
- Jadvalga **DELETE bloklovchi trigger** ham qo'yiladi (Postgres'da) — `cash_accounts` da
  bu trigger yo'q va bu kamchilik takrorlanmasin (faqat UPDATE guard bor,
  `cash_ddl_v1.sql:469`). §16.2 dagi egalik chegarasi bu yerda ham amal qiladi.

### 3.7 Ruxsatlar

Repoda **bitta kanonik naqsh** bor: `modul.amal` kodlari GLOBAL `permissions`/`roles`/
`role_permissions` jadvallarida (`auth.py:12-35`), yagona ro'yxat `seed.py:25-37`,
rol→ruxsat xaritasi `seed.py:42-58`, darvoza `core/deps.py:121-135`. Yangi kod qo'shish
**migratsiya EMAS** — `initdb._ensure_catalog` (`initdb.py:1294-1332`) har bootda
yetishmagan qatorlarni idempotent qo'shadi.

Yangi `kreditor` moduli, to'rt kod:

| Kod | Ma'nosi |
|---|---|
| `kreditor.view` | kreditorlar ro'yxati + qoldiq |
| `kreditor.edit` | yaratish / rename / arxivlash / havola |
| `kreditor.settle` | xaridda `OWNER_ADVANCE` legini yozish |
| `kreditor.repay` | qarzni qaytarish (pul SEYF/KASSAdan chiqadi) |

Mavjud kodni **qayta ishlatmaslik** sharti: `hisobot.view` menejerda bor (`seed.py:49`) —
uni ishlatish menejerga sherik qarzini yozish huquqini berardi.

⚠️ **Ikki qattiq mexanik haqiqat (o'zim tasdiqladim):**

1. `require()` **ega VA administrator** uchun tekshiruvni butunlay o'tkazib yuboradi
   (`deps.py:126-128`, `FULL_ACCESS_ROLES = ("ega","administrator")` `:49`). Ya'ni
   `require("kreditor.settle")` har qanday administratorda **avtomatik o'tadi**, va
   `ADMIN_EXCLUDE` (`seed.py:40`) buni **to'xtatmaydi** (u faqat grant qatorini to'xtatadi).
   Ega-only kerak bo'lsa — `make_admin` naqshi: handler ichida
   `emp.role.code == "ega" or "kreditor.settle" in effective_permissions(emp, db)`
   (`employees.py:34-37`), chunki `effective_permissions` FULL_ACCESS uchun chetlab
   o'tmaydi.
2. Rol ro'yxatidan chiqarib tashlash **«kassir hech qachon olmaydi»ni kafolatlamaydi**:
   `PATCH /employees/{id}/permissions` (`employees.py:637-679`) istalgan kodni istalgan
   rolga yoqadi va UI har kod uchun toggle chizadi (`Employees.tsx:163,219-233`). Kafolat
   uchun **yangi** `NON_OVERRIDABLE` deny-to'plami + `set_permissions` da 403 + UI filtri
   kerak — repoda bunday mexanizm **YO'Q**.

→ **B-savol:** ega-only mi, beriladigan (grantable) mi?

Qo'shimcha: kreditor kodlari `_PIN_FORBIDDEN_PERMS` (`auth.py:58-62`) ga kirsinmi (4 raqamli
PIN ortida sherik qarzi qolmasin); `reports.py` (~30 ta `require("hisobot.view")`) kreditor
qoldig'ini **qaytarmasligi** aniq yozilsin, aks holda `kreditor.view` darvozasi orqa
tomondan ochiladi; `initdb._ensure_catalog` try/except bilan **jim yiqiladi**
(`initdb.py:1328-1331`) — kreditor kodi yo'q bo'lsa marshrutlar fail-closed bo'lishi kerakmi.

### 3.8 Audit jurnali

Jadval nomi **`public.audit_log` (SINGULAR)** — `models/sync.py:66-82`: `actor_id`,
`action`, `entity`, `entity_id`, `before`, `after`, `terminal_id`, `created_at`.
**`company_id` YO'Q** (`api/v1/audit.py:28-30` buni ochiq tan oladi), **`reason` ustuni
ham YO'Q**, o'zgarmaslik faqat konvensiya. `cash.audit_logs` (`tenant_id` + `reason` +
DB-darajasida append-only) mavjud, lekin **birorta yozuvchisi yo'q** — «cash audit yozib
qo'yadi» deb hisoblab bo'lmaydi.

Yoziladigan hodisalar (barchasi `entity='creditor'`, **INSON QARORLARI**; pul faktlari
`creditor_ledger` da — `observability.py:26-27` qoidasi):
`create`, `update` (nom/telefon/havola, `before`/`after` bilan), `archive`, `unarchive`,
`delete`, `transfer_adjustment` (manba+maqsad id, summa, sabab), `repay` (kreditor id,
summa, `cash_account_id`, sabab), `link_user`, `unlink_user`.

Shartlar: `actor_id` **har doim majburiy** (NULL bo'lsa `api/v1/audit.py:31-36` INNER JOIN
uni ko'rsatmaydi — jim yo'qoladi); sabab `after.reason` ichiga yoziladi (`reason` ustuni
yo'q); `ENTITY_LABEL`/`ACTION_LABEL` (`api/v1/audit.py:11-18`) ga yangi kalitlar qo'shiladi,
aks holda Manager UI'da xom slug chiqadi.

> Pul faktlarining o'zgarmasligi `audit_log`ga **TAYANMAYDI** (u `public` sxemada
> trigger/REVOKE bilan himoyalanmagan) — §16.2.

### 3.9 Valyuta

`purchase_settlements`, `creditor_ledger` va `creditor_repayments` da **`currency`
majburiy**. Sabab: `Purchase.currency` bor (`purchasing.py:42`), naqd ledgerda valyuta
hisob bilan **kompozit FK** orqali majburlanadi (`cle_acct_currency_fk`,
`cash_ddl_v1.sql:220-226`), va turli valyutadagi avans/qaytarish §5.4 dagi
`repaid_amount <= amount` CHECK'ini ma'nosiz qilardi.

**Qoida:** bitta avans va uning barcha qaytarishlari **ayni valyutada**; kreditorning
`currency`si yaratilishda belgilanadi va o'zgarmaydi; boshqa valyutadagi avans →
**409 `CURRENCY_MISMATCH`** (mavjud kod). Ko'p valyutali sherik kerak bo'lsa — valyuta per
kreditor qator (**D-savol**).

---

## 4. Majburiyat daftari `creditor_ledger`

`SupplierLedger` naqshi (denormalizatsiyalangan balans + append-only daftar), tuzatilgan
tenant doirasi va snapshot bilan:

```
creditor_ledger
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  creditor_id            uuid NOT NULL -> creditors.id
  creditor_name_snapshot varchar(120) NOT NULL          # §3.5
  type                   varchar(12) NOT NULL           # ADVANCE | REPAYMENT | ADJUSTMENT
  amount                 numeric(14,2) NOT NULL         # > 0, ishora `type`da
  currency               char(3) NOT NULL
  balance_after          numeric(14,2) NOT NULL
  settlement_id          uuid NULL -> purchase_settlements.id   # ADVANCE uchun
  repayment_id           uuid NULL -> creditor_repayments.id    # REPAYMENT uchun
  ref_type               varchar(24) NULL               # ADJUSTMENT uchun
  reason                 text NULL
  created_at             timestamptz NOT NULL
  created_by             uuid NULL -> employees.id

ck_cl_amount_pos   amount > 0
ck_cl_type         type IN ('ADVANCE','REPAYMENT','ADJUSTMENT')
ck_cl_bal_nonneg   balance_after >= 0                   # §5.6
ck_cl_adv_iff      (type='ADVANCE')   = (settlement_id IS NOT NULL)
ck_cl_rep_iff      (type='REPAYMENT') = (repayment_id  IS NOT NULL)
ck_cl_adj_reason   type <> 'ADJUSTMENT' OR (ref_type IS NOT NULL AND btrim(coalesce(reason,'')) <> '')
```

`settlement_id` / `repayment_id` — **haqiqiy FK**, `SupplierLedger.ref_type`/`ref_id`
tipsiz polimorf ko'rsatkichi EMAS. Sabab: ular §5.2 dagi allokatsiyani va §10.2 dagi qulf
tartibini aniqlaydi.

`ADJUSTMENT` uchun `ref_type` va **sabab majburiy** — §5.3 dagi modellanmagan holatlar
shu orqali yoziladi.

### OWNER_ADVANCE — naqd HARAKATLANMAYDI
Sherik o'z cho'ntagidan to'lasa: **`CashLedgerEntry` YARATILMAYDI**, SEYFGA/KASSAGA soxta
`CASH IN` yozilmaydi. Faqat `purchase_settlements(source='OWNER_ADVANCE')` +
`creditor_ledger(ADVANCE)` + §5.4 dagi ochiq-qoldiq qatori. Shu bois avans uchun yangi
`cash_source_type`/`cash_category` label **kerak emas**.

> **`OWNER_CONTRIBUTION` (kapital qo'yilma) bu dizaynga KIRMAYDI.** Kontributsiyada
> kompaniya sherikka qarzdor emas; ikkalasini bitta qiymatga qo'shish buxgalteriya
> semantikasini buzadi.

---

## 5. Qaytarish (repayment) va ortiqcha qaytarishni to'sish (talab 5)

Avansni qaytarish — **alohida hodisa**, xariddan mustaqil.

```
creditor_repayments
  id                     uuid PK
  company_id             uuid NOT NULL -> companies.id
  creditor_id            uuid NOT NULL -> creditors.id
  creditor_name_snapshot varchar(120) NOT NULL
  cash_account_id        uuid NOT NULL           # TILL yoki SAFE — §6/§7 custody qoidasi
  amount                 numeric(14,2) NOT NULL  # > 0
  currency               char(3) NOT NULL
  ledger_entry_id        uuid NOT NULL           # FAIL-CLOSED
  client_uuid            uuid NULL
  created_at, created_by
ux_cr_client_uuid UNIQUE (client_uuid) WHERE client_uuid IS NOT NULL
```

Naqd oyoq xaritasi — **yangi enum label kerak emas**:

```
direction='OUT', category='CASH_OUT', source_type='CASH_OP',
source_id = creditor_repayments.id, leg_index = 0
```

### 5.1 ⚠️ Integratsiya xavfi — `compare_engine`
`compare_engine`da `CASH_OP` legining `source_id`si `cash_movements`da izlanadi; qator
topilmasa leg **`EXTRA_LEDGER`** («legacy manba yo'q») deb belgilanadi
(`compare_engine.py:76-81, 189-193`). `CASH_OP` ni yangi tashuvchi jadval bilan qayta
ishlatish **report parity'da yolg'on nomuvofiqlik** beradi. Shart: `compare_engine` yangi
tashuvchilarni tanishi (kichik kod o'zgarishi) **va** shu holat testda qotirilishi (§17 E-40).
Bu §12 dagi SEYF ochilishiga ham AYNAN tegishli.

Hisobot talabi: bu oyoqlar umumiy `CASH_OUT` ichida ko'milmasligi kerak — hisobotlar
`creditor_repayments` bilan join qilib ajratadi.

### 5.2 Allokatsiya: qaysi avans yopiladi

Qaytarish **aniq avans qatorlariga** taqsimlanadi — «qaysi avans yopildi» savoli javobsiz
qolmaydi:

```
creditor_repayment_allocations
  id             uuid PK
  company_id     uuid NOT NULL -> companies.id
  repayment_id   uuid NOT NULL -> creditor_repayments.id
  advance_id     uuid NOT NULL -> owner_advance_open.settlement_id
  amount         numeric(14,2) NOT NULL          # > 0
ck_cra_amount_pos  amount > 0
ux_cra_pair        UNIQUE (repayment_id, advance_id)
```

Taqsimot **FIFO va deterministik**: ochiq avanslar `(created_at, settlement_id::text)`
bo'yicha saralanadi, har biriga `min(ochiq_qoldiq, qolgan)` beriladi. Deterministik bo'lishi
idempotentlikning sharti (§10.3): takroriy so'rov **ayni** allokatsiya to'plamini beradi.

### 5.3 Uchta holat — ikkitasi `REPAYMENT` EMAS

| Holat | Kompaniya naqdi | Kreditor majburiyati | Yozuv |
|---|---|---|---|
| (a) pul SEYFGA/KASSAGA qaytdi, sherik hali qarzdor | `IN` | o'zgarmaydi | naqd ledger; majburiyat tegilmaydi |
| (b) pul bevosita SHERIKGA qaytdi | **qimirlamaydi** | kamayadi | `ADJUSTMENT` + sabab majburiy |
| (c) xarid bekor, avans ishlatilmadi | qimirlamaydi | kamayadi | `ADJUSTMENT` + `ref_type='settlement_reversal'` |

(b) va (c) ni `REPAYMENT` deb yozish **kompaniya pul to'lagan** degan yolg'on ma'no berardi.
Ikkalasi ham ayni `owner_advance_open` qatoriga bog'lanadi (§5.4) — aks holda qator-lokal
CHECK ularni ko'rmaydi.

### 5.4 Ochiq qoldiq qatori — o'zgarmas hujjat + o'zgaruvchan hisoblagich

`purchase_settlements` **append-only** (§11), shu bois unga o'zgaruvchan `repaid_amount`
ustuni **qo'yilmaydi**. Repo o'zining aniq naqshini beradi: o'zgarmas harakat qatorlari
yonida **alohida kuzatuv qatori**, ustida qator-lokal CHECK —
`lot_shortfalls.resolved_qty` + `CheckConstraint("resolved_qty <= qty",
name="ck_lot_shortfall_resolved_le_qty")` (`models/inventory.py:299-301`, o'zim
tasdiqladim). Izohdagi sabab **so'zma-so'z** bu yerga ko'chadi: ortiqcha yopilsa invariant
yig'indisi jimgina nolga tushib, xatoni tushunarsiz qilardi.

```
owner_advance_open
  settlement_id   uuid PK -> purchase_settlements.id     # 1:1, faqat source='OWNER_ADVANCE'
  company_id      uuid NOT NULL -> companies.id
  creditor_id     uuid NOT NULL -> creditors.id
  amount          numeric(14,2) NOT NULL                 # settlementdan KO'CHIRILGAN, O'ZGARMAS
  repaid_amount   numeric(14,2) NOT NULL DEFAULT 0       # YAGONA o'zgaruvchan maydon
  currency        char(3) NOT NULL

ck_oao_amount_pos     amount > 0
ck_oao_repaid_le_amt  repaid_amount >= 0 AND repaid_amount <= amount
```

Natija: **bitta avansdan ortiq qaytarish BAZA darajasida imkonsiz**, hosila `SUM`ga
tayanmasdan. `amount` o'zgarmas; `repaid_amount` faqat `with_for_update(key_share=True)`
ostida oshiriladi (§10.2).

### 5.5 QISQARTIRISH (clamp) TAQIQLANADI — RAD ETILADI

Reponing pul domeni ortiqcha to'lovni **jimgina qisqartiradi**: `purchases.py:1040`
(`amt = min(amount, bal)`), `customers.py:333` (`amt = min(amt, bal)`) — ikkisi ham **200**
qaytaradi. Undan yomoni: `pay_supplier` FIFO halqasidan keyin qolgan `remaining` **hech
qayerga yozilmaydi** (`purchases.py:1088-1101`) — pul jimgina yo'qoladi.

Bir kreditorli dunyoda bu «deyarli bezarar» edi. **Ko'p sherikli dunyoda clamp pulni
sheriklar o'rtasida jimgina qayta taqsimlaydi:** Sherik A ga 5 000 qaytarmoqchi operator
7 000 yuborsa, clamp 5 000 yozadi va 2 000 **hech kimga tegishli bo'lmay yo'qoladi**.

**Qaror:** kreditor qaytarishida clamp YO'Q. Zaxira domeni naqshi olinadi
(`lot_resolution.py:331-354`): qulf → qulf ostida idempotentlik replay →
`if total > open_total: raise 409 OVER_REPAYMENT`. **RAD, qisqartirish emas.** CHECK faqat
zaxira to'siq (backstop), asosiy darvoza dastur qatlamida — chunki mavjud `IntegrityError`
ushlash naqshi constraint nomini o'qimaydi (`purchases.py:1113`) va xom CHECK buzilishi 500
yoki yolg'on «duplicate» berardi.

### 5.6 Manfiy kreditor balansi TAQIQLANADI

`ck_creditor_bal_nonneg (balance >= 0)` va `ck_cl_bal_nonneg (balance_after >= 0)`.

Repoda ikki tomonga ham presedent bor: to'lov yo'lida manfiy YO'Q (`purchases.py:1040`,
`customers.py:345`), qaytarish/tahrir yo'lida manfiy **ataylab BOR**
(`sales.py:1034-1036`, `purchases.py:868-885`). Kreditor uchun **manfiy rad etiladi**,
chunki manfiy balans «endi sherik kompaniyaga qarzdor» degan **yangi, hujjatsiz**
majburiyatni jimgina yaratardi. Bu yangi jadval — birorta legacy yo'lni buzmaydi (shu
CHECK'ni `suppliers`/`customers` ga qo'yib bo'lmaydi, chunki ular uchun manfiy ataylab
ruxsat etilgan). → **C-savol** bilan tasdiqlanadi.

### 5.7 Drift invarianti

`creditors.balance` — **kesh**. Haqiqat manbai: `Σ(owner_advance_open.amount −
repaid_amount)`. Arxivlash darvozasi (§3.3) va hisobotlar **haqiqat manbaidan** hisoblaydi,
keshdan emas. Kesh bilan haqiqat orasida farq paydo bo'lsa — `stock_invariant.assert_ok`
uslubidagi tekshiruv (`lot_resolution.py:447-449`) tranzaksiya oxirida ishlaydi va
**rollback** qiladi. Ta'minotchi FIFO'si bu holda qoldiqni jimgina yo'qotadi
(`purchases.py:1088-1101`) — kreditor uchun bu **qabul qilinmaydi**.

### 5.8 Yaxlitlash

Qaytarish summasi **butun som** (`whole-som-payments`) — `ROUND_HALF_UP`, klientda
`Math.round`. Sabab: aks holda oxirgi qaytarishda 0.01 qoldiq qolib, avans
`repaid_amount <= amount` CHECK'i ostida **abadiy yopilmay** qolishi mumkin. Avans summasi
ham butun som bo'lsinmi — **E-savol**.

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

## 7. SEYF oyog'ining validatsiyasi + custody domeni

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
| `TREASURY` | kompaniya pulining harakati; kassir navbatda bo'lishi ahamiyatsiz | **xarid/qabul to'lovi**, ta'minotchi to'lovi, **kreditorga qaytarish** |

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
fail-closed default (`fail-open-defaults`).

### 7.3 SAFE uchun manfiy qoldiq — QAT'IY fail-closed
SEYF uchun `allow_negative` override **yo'q** (servis + DDL `CF-D5` ikkisi ham TILL'ga
bog'langan). Bu **ataylab shunday qoldiriladi**: mavjud manfiy naqd himoyasi chetlab
o'tilmaydi. Natija — §0 dagi zanjir: ochilish qoldig'i bo'lmasa to'lov `INSUFFICIENT_CASH`
bilan rad etiladi, va bu **to'g'ri** xatti-harakat.

---

## 8. `CashPostingService` xaritasi

| Hodisa | Ledger oyog'i | Hisob | `posting_kind` / `shift_id` | Kutilayotgan naqd |
|---|---|---|---|---|
| `TILL_CASH` settlement | `OUT · PURCHASE_OUT` | tanlangan TILL | `ON_SHIFT` / smena id | **−summa** |
| `SAFE_CASH` settlement | `OUT · PURCHASE_OUT` | tanlangan SAFE | `OFF_SHIFT` / `NULL` | ta'sir yo'q |
| `OWNER_ADVANCE` settlement | **yozuv yo'q** | — | — | ta'sir yo'q |
| kreditorga qaytarish | `OUT · CASH_OUT` (`CASH_OP`) | tanlangan TILL/SAFE | §6/§7 qoidasi | **−summa** |
| SEYF ochilish qoldig'i | `IN · ADJUSTMENT` (`CASH_OP`) | SEYF | `OFF_SHIFT` / `NULL` | **+summa** |

`CashPostingService` **yagona yozuvchi** bo'lib qoladi; parallel «purchase cash balance»
tizimi yaratilmaydi; to'g'ridan-to'g'ri `INSERT` (backfill naqshi) **taqiqlanadi** — u
manfiy qo'riqchini butunlay aylanib o'tadi (DB darajasida manfiy qoldiq invarianti YO'Q).

---

## 9. Ta'minotchi qarzi xaritasi

```
unpaid = purchase.total − Σ(PAYMENT.amount) + Σ(REVERSAL.amount)
```

Ta'minotchi nuqtai nazaridan **kim to'lagani ahamiyatsiz** — sherik cho'ntagidan kelgan pul
ham unga yetib boradi. Shu bois `OWNER_ADVANCE` ham `unpaid` ni kamaytiradi va
`purchases.paid_amount = Σ(barcha PAYMENT oyoqlari)`.

`unpaid > 0` → `sup.balance += unpaid` + `SupplierLedger(charge, unpaid, ref_type=
'receiving'|'purchase', ref_id=...)`, balans **qator qulfi ostida** (`purchases.py:313`,
`receiving.py:218`).

`paid_cash` va `paid_owner` — **saqlanmaydi, hisoblanadi** (`purchase_settlements` dan).
Saqlangan ustun `purchases` ga T1 sxema majburiyatini qo'shardi va denormalizatsiya drifti
berardi.

### ⚠️ `_charged` ikkilik predikati gibrid hujjatni BUZADI
`purchases.py:881-906` hujjatni ikkilik tasniflaydi («ledgerga charge yozilganmi?»), QA
PR-004 esa naqd xaridda `paid_amount`ni **majburan `total`ga tenglaydi**. Gibrid hujjatda
bu ikki qoida zid: `_charged` TRUE bo'lgani uchun naqd ulush umuman qaytarilmaydi va butun
delta `SupplierLedger`ga ketadi.

**Qaror (Phase 1 doirasi):** quyidagi hujjatlar uchun `PATCH /purchases/{id}`
**bloklanadi** (`409 HYBRID_EDIT_UNSUPPORTED`):
- bir nechta PAYMENT oyog'i bor (split), **yoki**
- kamida bitta `OWNER_ADVANCE` oyog'i bor.

Sabab: mavjud qaytarish formulasi (`_ret_amt = paid − new_total`, `purchases.py:936`)
sherik pulini **kassaga `IN`** qilib **fantom naqd** yaratardi (ledgerda mos `OUT` yo'q).
Tuzatish Phase 5D da qotirilgan **reversal + replacement** yo'li bilan boradi (§11).
`_charged` ni qayta ta'riflash alohida ish — u sotuv/qaytarish/hisobot yo'llariga ham tegadi.

---

## 10. Atomiklik, qulf tartibi, idempotentlik (talab 7)

### 10.1 Tranzaksiya chegarasi

Bitta DB tranzaksiyasi: hujjat + qatorlar + **barcha** settlement oyoqlari + **barcha**
ledger oyoqlari + ta'minotchi qarzi + kreditor daftari + ochiq-qoldiq qatorlari. Har qanday
qisman xato → **butun ROLLBACK** (`CashPostingError` ham).

- **`commit=False` da tiklanish:** posting servisining `IntegrityError→DUPLICATE` o'girishi
  **faqat `commit=True`** shoxida (`posting.py:403-416`). Shu bois har oyoq **`SAVEPOINT`**
  (`db.begin_nested()`) ichida yoziladi; kalitlar deterministik bo'lgani uchun to'qnashuv
  aniq va qayta ishlanadigan.
- **Qatorlararo invariant DB CHECK bilan ushlanmaydi:** `total = Σ(legs) + unpaid` —
  Postgres CHECK qator-lokal. U xizmat qatlamida majburlanadi va §17 C guruhi bilan
  qotiriladi. `TRANSFER` dagi deferred to'liqlik triggeri xarid oyoqlari uchun yo'q,
  `transfer_group_id` esa `cle_transfer_group_iff` sababli yaramaydi.
- **Nima QATOR-LOKAL (ya'ni baza kafolati):** ortiqcha qaytarish (§5.4) va manfiy balans
  (§5.6).

### 10.2 Qulf tartibi va DARAJASI — TUZATILDI

Repoda **yozilgan** global qulf shartnomasi bor: `lot_correction.py:53-88` (9 qadam).
Amaldagi ketma-ketlik: dedup (qulfsiz) → FK ota qatorlari `FOR KEY SHARE` → `purchases`
`FOR UPDATE` → `suppliers` `FOR UPDATE` → `inventory` (`sorted(key=str)`) → `stock_batches`
→ hodisa INSERT'lari → **custody rezolyutsiyasi (qulf OLMAYDI**, ataylab) →
`cash.cash_accounts` → `cash.shifts` (**har doim eng oxiri**, faqat `CashPostingService`
ichida).

**`creditors` sloti:** `suppliers` dan **KEYIN**, `inventory` dan **OLDIN**:

```
purchases -> suppliers -> creditors -> inventory -> stock_batches -> cash_accounts -> cash.shifts
```

Sabab: naqd hisoblar har doim eng oxirida qulflanadi, shu bois kreditorni ulardan oldin
qo'yish **gibrid xarid** (supplier + creditor + inventar + hisob) va **kreditor qaytarishi**
(creditor + SAFE, inventarsiz) yo'llarini bitta yo'nalishga soladi. Aks holda qaytarish
avval hisobni qulflab, xarid yo'liga nisbatan AB/BA beradi.

⚠️ **QULF DARAJASI — avvalgi tahrirdagi XATO tuzatildi.** Oldin «`Supplier.balance` naqshi»
(oddiy `with_for_update()`) deb yozilgan edi. Bu **FK KEY SHARE kuchaytirish tuzog'iga**
tushadi: `purchase_settlements.creditor_id`, `creditor_ledger.creditor_id` va
`owner_advance_open.creditor_id` FK'lari har INSERT'da kreditor qatorida `FOR KEY SHARE`
oladi; shundan keyin `FOR UPDATE` = qulfni kuchaytirish = **deadlock**. To'g'ri daraja:

```
with_for_update(key_share=True)     # FOR NO KEY UPDATE
```

Presedent va sabab kodda yozilgan: `sales.py:615-638` (mijoz qatori) va
`cashops.py:102-108` (`CashMovement` FK'si). `balance` kalit ustun emas, shu bois
`UPDATE creditors SET balance=...` allaqachon ayni darajani oladi — kuchaytirish yo'q.
(`fk-qulf-kuchaytirish`.)

**Bir hujjatda bir necha kreditor:** `set` bilan dedup + `for cid in sorted(ids, key=str)`
— `receiving.py:270`, `purchases.py:352`, `posting.py:188` bilan ayni konvensiya.
Qulf **doirasi hujjatniki** (`lot_correction.py:78-83`): tuzatish/reversal yo'lida
so'rovdagi kreditorlar ∪ `SELECT DISTINCT creditor_id FROM purchase_settlements WHERE
purchase_id=:id` **bitta saralangan o'tishda** qulflanadi. Barcha kreditorlar **birinchi
`purchase_settlements` INSERT'idan OLDIN** qulflanadi, so'ng naqd oyoqlar uchun
`cash_account_id`lar **chaqiruvchi tomonidan** `sorted(key=str)` bilan saralanib ketma-ket
`post(commit=False)` qilinadi (bir-hisobli `post()` bu tartibni majburlamaydi —
`posting.py:97`).

**Kreditorni nom bo'yicha get-or-create** `ux_creditors_company_lower_name` +
`IntegrityError` retry'ga tayanadi, `FOR UPDATE`ga **emas**: mavjud bo'lmagan qatorni
qulflab bo'lmaydi (`receiving.py:226-232` da aynan shu teshik bor).

**Deadlock o'rami:** endpoint `lot_correction.py:757-772` naqshi bilan o'raladi —
`40P01` → 3 marta qayta urinish, 500 emas. `create_purchase` (`purchases.py:294-301`) faqat
`IntegrityError`ni tutadi, bu yetarli emas.

### 10.3 Idempotentlik kalitlari

| Hodisa | Kalit | Nima to'sadi |
|---|---|---|
| Hujjat | `ux_purchases_client_uuid` / `ux_receivings_client_uuid` | ikkinchi hujjat |
| Settlement oyog'i | `ux_ps_leg` + `ux_ps_cash_party` / `ux_ps_cred_party` | ikkinchi oyoq (deterministik `leg_no`, §2.1) |
| Naqd oyoq | `cle_uq_business` | ikkinchi ledger qatori |
| Avans ochiq qoldig'i | `owner_advance_open.settlement_id` PK | ikkinchi kuzatuv qatori |
| Qaytarish | `ux_cr_client_uuid` | ikkinchi qaytarish |
| Allokatsiya | `ux_cra_pair` + FIFO determinizmi (§5.2) | qo'shimcha allokatsiya |

`OWNER_ADVANCE` oyog'ida **ledger yozuvi yo'q** (`ck_ps_ledger_iff`), shu bois uning
idempotentligi butunlay yuqoridagi kalitlarga tayanadi — `CashPostingService` dublikat
tekshiruvi bu yerda **ishlamaydi**. Bu ataylab qayd etiladi.

### 10.4 Offline takror — tekshirildi, xavf YO'Q

`/sync/push` **faqat `body.sales`** ni qabul qiladi (`sync.py:43-48`) — xarid/qabul
hujjatlari u orqali o'tmaydi. Shu bois `sync.py:71` dagi
`_transient = status >= 500 or status == 409` qoidasi (**har qanday 409 transient**)
settlementga **tegmaydi**. Mobil qabul har hujjat uchun barqaror `client_uuid` + qo'lda
qayta yuborish ishlatadi (`api/receiving_api.dart:17`), fon navbati yo'q. Agar kelajakda
xarid offline navbatga qo'shilsa — `INSUFFICIENT_CASH` (doimiy 409) **cheksiz aylanardi**;
shart o'sha paytda qayta ko'riladi.

---

## 11. Tuzatish / reversal modeli

- `purchase_settlements` **append-only**: `UPDATE`/`DELETE` yo'q. Yagona o'zgaruvchan
  moliyaviy maydon — `owner_advance_open.repaid_amount` (§5.4), va u qator-lokal CHECK
  bilan qamalgan.
- `amount > 0` CHECK saqlanadi; teskari yo'nalish **`kind='REVERSAL'` + `reverses_id`**
  bilan ifodalanadi (manfiy summa emas). Bu «immutability vs mutatsiya» to'qnashuvini hal
  qiladi: qaytarish `Purchase.total`ni o'zgartirsa ham settlement qatorlari
  **tahrirlanmaydi**.
- `ux_ps_reverses` → bir oyoqqa **ko'pi bilan bitta** reversal (`cle_uq_reverses` naqshi,
  `cash_ddl_v1.sql:238`).
- Ledger tomonida reversal legi **yangi `source_id`** oladi — aks holda ikkinchi leg
  jimgina dublikat deb tashlanardi (`posting.py:90-94` + `leg_index=0` default).
- `OWNER_ADVANCE` legining reversali **naqd yozuvi yaratmaydi**; u
  `creditor_ledger(ADJUSTMENT, ref_type='settlement_reversal')` va `owner_advance_open`
  qatorining yopilishi bilan ifodalanadi (§5.3-c).
- **Qisman qaytarish reversal EMAS** — alohida hodisa (`PURCHASE_RETURN_identity.md`
  qarori o'z kuchida, `adapters.py:70`).

> ⚠️ **Append-only'ni ustun yo'qligi ISBOTLAMAYDI.** Kafolat: (a) xizmat qatlamida yozuv
> yo'lining yagonaligi, (b) qator-lokal CHECK'lar, (c) unique indekslar. DB trigger
> himoyasi **hozircha YO'Q** — §16.2.

---

## 12. SEYF ochilish qoldig'i — **ANIQ DIZAYN BO'SHLIG'I**

### 12.1 Topilgan holat
- T0 da **hech qanday** ochilish yozuvi yozilmaydi (`T0_CUTOVER_ENFORCEMENT.md:96` —
  *"Nothing is auto-mutated at T0"*); `cash_provision` faqat `cash_accounts` yaratadi,
  ledgerga yozmaydi. Demak **har qanday hisob T0 dan keyin qoldiq 0 bilan tug'iladi**.
- TILL uchun yo'l BOR: birinchi smena ochilishida `_delta = opening_cash − account_balance`,
  `_delta > 0` → `IN·OPENING` (`SHIFT_OPEN`, `ON_SHIFT`) (`retrofit.py:154-157`). Bu T0 dan
  keyin yaratilgan yangi TILL uchun ham ishlaydi (`tills.py:166`).
- SEYF uchun yo'l **YO'Q**: mexanizm smenaga bog'langan, SEYF esa smena ochmaydi.
  `POST /safes` (`tills.py:214`, `SafeCreate` — `tills.py:192-195`) summa qabul QILMAYDI;
  SEYFga pul faqat `TILL→SAFE` inkassa (`retrofit.py:443-455`) yoki smenasiz mijoz qarz
  to'lovi bilan kiradi.
- Sxema va adapterlar **tayyor** (`OPENING`/`ADJUSTMENT` `cash_ddl_v1.sql:60`,
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
  id, company_id, cash_account_id UNIQUE, counted_amount, currency, counted_at,
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

1. **`ADJUSTMENT`, `OPENING` emas.** `OPENING` hozir faqat `SHIFT_OPEN` bilan juftlashgan;
   yangi juftlik hisobot/parity kodidagi tekshirilmagan taxminlarni buzishi mumkin.
   `ADJUSTMENT` esa mavjud **menejer+ darvozasini** tayyor beradi (`posting.py:254-260`:
   `category=ADJUSTMENT and reverses_id is None and not _is_manager_plus` → rad).
2. **Miqdor semantikasi TILL bilan bir xil:** `amount = counted − balance`, hisob qatori
   qulfi ostida; `<= 0` → aniq xato. `retrofit.py:150-163` dagi izoh manfiy deltani
   ataylab yozmaslikni va uni kitobga olish `ADJUSTMENT` + menejer+ talab qilishini
   **allaqachon aytadi** — bu taklif shu izohni bajaradi.
3. **Bir martalik:** `UNIQUE(cash_account_id)` tashuvchida + ledgerda `cle_uq_business`.
4. **Ruxsat va audit:** ega/menejer+ + `audit_log`. `attestation_ref` va `attested_by`
   **NOT NULL** — «pul yo'qdan paydo bo'ldi» holati hujjatsiz yozilmaydi;
   `provenance='RECONSTRUCTION'` reason+source_ref ikkisini majburlaydi (`cle_recon_prov`).
5. **`compare_engine`** yangi tashuvchini tanishi shart (§5.1 dagi ayni xavf).

### 12.3 Shu paketga kirishi kerak bo'lgan qo'shimcha bo'shliqlar
- **TILL qoldig'ini PASAYTIRISH yo'li ham yo'q:** manfiy delta ataylab yozilmaydi
  (`retrofit.py:159-163`) va uni kitobga oluvchi `ADJUSTMENT` endpointi mavjud emas.
- `reconcile_safe` (`lifecycle.py:118-131`) na endpoint, na CLI orqali chaqirilmaydi va
  farqni `PENDING` da qoldiradi — zanjir uzilgan.
- **SEYF hayot davri umuman yo'q:** `/safes` uchun faqat `GET` va `POST` bor — `PATCH` ham,
  `DELETE` ham YO'Q. Seyfni yaratish mumkin, arxivlash mumkin emas. Ogohlantirish: «keyin
  qo'shamiz» deb qoldirilgan hayot davri umuman yozilmay ketadi (shu sababdan `creditors`
  uchun §3.3 boshidan to'liq).
- **Legacy tenantda SEYF qoldig'i backfillda YO'Q** va bu migratsiyada faqat REVIEW
  (`MIGRATION_PHASE0.md:151`), BLOCK emas. Fayzan uchun hozir zararsiz (SEYF yo'q), lekin
  qoida sifatida tasdiqlanishi kerak.

---

## 13. Manager UX

Hozir: `packages/shared/src/screens/Products.tsx:1053-1059` da ikkilik `naqd | nasiya`
tugmasi; **naqd hisob tanlagichi umuman yo'q**, summa bo'linmaydi. Ekran `packages/shared`da,
lekin uni **faqat Manager** import qiladi (`apps/manager/src/App.tsx:5`) — POS ta'sirlanmaydi.

Taklif — **to'lov qatorlari** modeli:

```
┌ To'lov ──────────────────────────────────────────────────┐
│ Jami: 30 000                                             │
│                                                          │
│  [Asosiy seyf    ▾]  [ 10 000 ]  (qoldiq: 2 100 000)    │
│  [Kassa #1       ▾]  [  5 000 ]  (qoldiq:   340 000)    │
│  [Sherik: A      ▾]  [  5 000 ]  (qarz: 5 000 → 10 000) │
│  [+ to'lov manbasi]                                      │
│                                                          │
│  Qarzga qoladi:        10 000   (hosila)                 │
└──────────────────────────────────────────────────────────┘
```

- Naqd manbalar **serverdan**: `GET /cash/custody-preview?operation=receiving_payment` →
  `info.options` (`custody_preview.py:96-97` — `list_tills + list_safes`).
- Kreditorlar **alohida ro'yxatdan** (`GET /creditors?active_only=true`) — arxivlangan
  kreditor chiqmaydi (§3.3).
- Qator tanlagichi kreditorni **ism bilan** ko'rsatadi; anonim «ega» varianti **YO'Q**.
- «Qarzga qoladi» — **hosila**, kiritilmaydi; manfiy bo'lsa saqlash bloklanadi.
- Eski ikkilik tugma **ko'chiriladi, qo'shilmaydi** (`ui-move-not-add`).
- Har qator yonida qoldiq/qarz **oldin** ko'rinadi, xatodan keyin emas.
- ⚠️ **Desktop xato ko'rsatishi buzilgan:** `api.ts:105` dict `detail`ni `JSON.stringify`
  qiladi → operator **xom JSON** ko'radi; `serverErrorsCash.ts:18-67` esa faqat 7 ta
  prefiksli gard kodini biladi (mobil 18 ta posting kodini biladi —
  `errors.dart:111-129`). Implementatsiyadan oldin: `api.ts` `d.error`/`d.message`ni
  ajratsin, va `INSUFFICIENT_CASH`, `UNAUTHORIZED_OPERATION`, `ACCOUNT_ARCHIVED`,
  `CURRENCY_MISMATCH`, `OVER_REPAYMENT`, `CREDITOR_HAS_BALANCE`, `CREDITOR_NAME_TAKEN`,
  `SETTLEMENT_CONFLICT`, `HYBRID_EDIT_UNSUPPORTED` ru/uzc bilan qo'shilsin
  (`server-error-i18n`). Fayzan `til=ru` — xom matn qabul qilinmaydi.
- Summalar **butun som** (`whole-som-payments`).

---

## 14. Mobil UX

Asos **bor**: `custody_block.dart:69` `info.options`ni shartsiz chizadi, `:314` da alohida
«Seyf» yorlig'i/ikonkasi. Mobil lug'ati kodni `X-Error-Code`/`detail['error']` dan o'qiydi
(`api.dart:1032-1053`) — desktopdan yaxshiroq holatda.

- bitta tanlovdan **qatorlar** ro'yxatiga o'tish (bitta qator = hozirgi xatti-harakat);
- `client_uuid` **hujjat uchun** barqaror, `leg_no` deterministik (§2.1);
- server rad etsa (`INSUFFICIENT_CASH`) UI hujjatni **yo'qotmasdan** qayta manba tanlashni
  taklif qiladi;
- ⚠️ `receiving_submit_sheet.dart:34-48` ro'yxatida `NEGATIVE_APPROVAL_REQUIRED` bor —
  lekin u **o'lik kod** (pastdagi jadval). Uni ro'yxatdan olib, o'rniga haqiqatda keladigan
  `UNAUTHORIZED_OPERATION` qo'yilsin;
- kreditor yozuvi mobilda bo'ladimi — **F-savol**; ha bo'lsa
  `apps/mobile/assets/permission_matrix.json` + `shell_permission_matrix_test.dart`
  yangilanadi (`test_mobile_permission_matrix.py:130-190` majburlaydi).

---

## 15. Purchase Return — kelajakka moslik

> Bu bosqichda **Purchase Return semantikasi implementatsiya QILINMAYDI.** Faqat sxemaning
> kelajakni bloklamasligi ta'minlanadi.

Bugungi holat: alohida «xarid qaytarish» amali yo'q — qaytarish `PATCH /purchases/{id}`
tahririning (yoki `POST /receiving/{id}/corrections`ning) yon ta'siri, summa
`_ret_amt = paid − new_total` (`purchases.py:936`), va pul **asl xarid emas, hozirgi
kontekst** bo'yicha hisobga tushadi.

Sxema quyidagilarni **saqlaydi**:
- har oyoqning **o'z identiteti** (`purchase_id`, `leg_no`, `party`, `ledger_entry_id`) —
  «qaysi pul qaysi hisobdan yoki KIMDAN chiqqan» savoli javobsiz qolmaydi;
- `kind` / `reverses_id` — «qaysi oyoqqa qaytdi» javobini **saqlash joyi** mavjud;
- `creditor_id` + `creditor_name_snapshot` — sherik pulining qaytishi **hech qachon**
  kassaga `IN` bo'lib fantom naqd yaratmaydi (§9 dagi edit bloki Phase 1 da kafolatlaydi).

**`purchases.cash_account_id` taqdiri.** Ustun izohi hozir «keyingi audit so'rov tanasiga
emas, SHU ustunga tayanadi» deydi (`purchasing.py:41-43`) — split bilan bu **buziladi**.
Qaror: audit identiteti **`purchase_settlements` ga o'tadi**; ustun esa
- **aynan bitta** naqd oyoq bo'lsa — avvalgidek yoziladi (orqaga moslik va
  `test_mobile_parity_pg.py:1323` assertioni yashil qoladi),
- split bo'lsa — **NULL**, va izohi «ESKIRGAN: avtoritet emas» deb belgilanadi
  (`PurchaseItem` dagi DEPRECATED izoh konvensiyasi).

Kelajakda hal qilinadi (sxema bloklamaydi): allokatsiya siyosati (FIFO / proporsional /
operator tanlaydi); `custody_preview` uchun `purchase_return_cash` operatsiyasi (hozir
yo'q — `custody_preview.py:405-436`); SEYFdan to'langan xaridning qaytishi (§7.2 domeni
bilan birga).

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
`models/__init__` + boot `create_all` (Alembic yo'q). Yangi **jadvallar** uchun
`_ensure_columns` yozuvi kerak emas (`create_all` hammasini yaratadi); T1 qoidasi faqat
**mavjud** jadvalga ustun qo'shilganda qo'llanadi — bu dizaynda bunday ustun **yo'q**
(`paid_cash`/`paid_owner` ataylab hisoblanadigan, §9).

**Ochiq e'tirof:** `public`da o'zgarmaslik triggeri **naqshi yo'q**
(`receiving_corrections` ham faqat docstring + unique indeks bilan himoyalangan),
`initdb`da SQL trigger yaratadigan qadam **yo'q**, va jadvalni ilova roli yaratgani uchun
**ilova o'zi ega** bo'ladi — ya'ni o'z triggerini `DISABLE` qila oladi. Bunday triggerni
«himoya» deb atash yolg'on bo'lardi. Phase 1 kafolati: xizmat qatlami + qator-lokal
CHECK'lar + unique indekslar.

Alohida qaror talab qiladi: kim DDL bajaradi, kim ega; trigger qo'shilsa
`_ensure_lot_checks` naqshi (30 s qulf byudjeti, boot yiqilmaydi) yangi bo'sh jadval uchun
to'g'rimi yoki fail-closed kerakmi; `required_schema.py` triggerlarni **umuman ko'rmaydi**.

### 16.3 Yangi CHECK'larni qotirish (majburiy qadam)
`tests/check_renderings_pg.py:12-88` har CHECK uchun Postgres'ning **aynan** `pg_get_expr`
yozuvini (oddiy VA pretty) talab qiladi, `tests/test_check_canon.py:98,121-124` esa
mutatsiya ro'yxatini. Bu yozuvlar **qo'lda yozilmaydi** (fayl sarlavhasi: «faqat o'qiydigan
katalog so'rovi bilan olingan»). Implementatsiya rejasi **haqiqiy Postgres'dan rendering
olish** qadamini o'z ichiga oladi, aks holda keyingi migratsiya CHECK'ni jimgina
zaiflashtira oladi. Bu dizaynda **12 ta yangi CHECK** bor.

### 16.4 Eski klientlar
Eski Manager/mobil `payment: "cash"|"credit"` (`receiving.py:240`) yoki
`status: "received"|"debt"` (`schemas/purchase.py:31`) + `cash_account_id` yuboradi.
Yangi `settlements[]` maydoni **ixtiyoriy**: berilmasa server eski yo'lni yuritadi
(`cash` → bitta to'liq oyoq, `credit` → oyoqsiz). Eski klient buzilmaydi. Mavjud hujjatlar
tegilmaydi.

### 16.5 SQLite
`cash` jadvallari mahalliy bazada umuman yo'q; `cash_enabled()` non-Postgres'da naqd yozuv
yo'lini yopadi; SQLite FK'ni ham majburlamaydi (`sqlite-fk-yoq`); CHECK holati
**tasdiqlanmagan**. Demak kritik testlar haqiqiy PG'da (§17).

---

## 17. Test matritsasi (adversarial + PG konkurrentlik)

**PG majburiy** (`pgserver`, `pg` fixture).

### A. Identitet va idempotentlik
1. Bir xil tana ikki marta → **bitta** hujjat, **bitta** to'plam oyoq, `leg_no` o'zgarmagan.
2. Ayni `client_uuid` + **boshqa** summa → `SETTLEMENT_CONFLICT`.
3. `max+1` regressiya qo'riqchisi: takroriy split **leg 2/3 yaratmaydi** (§2.1).
4. **Ikki xil kreditordan ikki `OWNER_ADVANCE`** → `leg_no` deterministik va takrorda
   o'zgarmaydi (`cash_account_id` NULL tartibni buzmaydi — §2.1 nuqsoni).
5. Ayni kreditordan ikkinchi PAYMENT oyog'i → `ux_ps_cred_party` rad.
6. Dublikat tanasi mos kelmasa DUPLICATE **yolg'on muvaffaqiyat bo'lmaydi** (§2.2).
7. Haqiqiy `INSUFFICIENT_CASH` **`duplicate: true` bo'lib yutilmaydi** (§2.3).

### B. Konkurrentlik (`_concurrent`, `threading.Barrier`)
8. Ayni SEYFdan ikki parallel to'lov, qoldiq bittasiga yetadi → biri `INSUFFICIENT_CASH`,
   **manfiy qoldiq YO'Q**.
9. Seyf+kassa juftini teskari tartibda yozuvchi ikki tranzaksiya → **deadlock yo'q**.
10. Ayni kreditorga parallel avans → `creditors.balance` yo'qotilgan yangilanishsiz.
11. Ayni kreditorga parallel qaytarish → ikkinchisi `OVER_REPAYMENT`; `repaid_amount`
    hech qachon `amount`dan oshmaydi.
12. **Qulf darajasi qo'riqchisi:** FK INSERT (KEY SHARE) + `FOR UPDATE` = deadlock,
    `FOR NO KEY UPDATE` = deadlock yo'q (`test_lot_phase4a.py:949-953` uslubi, §10.2).
13. Ikki kreditorli hujjatni teskari tartibda yozuvchi ikki tranzaksiya → saralash
    konvensiyasi deadlockni to'sadi.
14. Nom bo'yicha get-or-create poygasi → `IntegrityError` retry, ikkinchi kreditor qatori
    YO'Q.

### C. Invariantlar (adversarial)
15. `total ≠ Σ(legs) + unpaid` holatini **yaratishga urinish** → har yo'lda rad.
16. Ortiqcha to'lov (`Σ > total`) → rad.
17. `amount = 0` yoki manfiy → CHECK rad.
18. `SAFE_CASH` + `cash_account_id=NULL` → CHECK rad.
19. `OWNER_ADVANCE` + `cash_account_id` berilgan → CHECK rad.
20. `OWNER_ADVANCE` + `creditor_id=NULL` → CHECK rad.
21. `OWNER_ADVANCE` + `creditor_name_snapshot=NULL` yoki bo'sh → CHECK rad.
22. Naqd oyoq + `ledger_entry_id=NULL` → CHECK rad (fail-closed isboti).
23. `repaid_amount > amount` **to'g'ridan-to'g'ri UPDATE** bilan → CHECK rad (§5.4).
24. `creditors.balance < 0` / `balance_after < 0` → CHECK rad (§5.6).
25. `ADJUSTMENT` sababsiz yoki `ref_type`siz → CHECK rad.
26. `UPDATE`/`DELETE` — xizmat yo'li yo'q; trigger qo'shilsa `assert_rejects` naqshi.

### D. Custody domeni (eng nozik guruh)
27. **Ochiq smena + SEYFdan to'lov → MUVAFFAQIYAT**, leg `OFF_SHIFT`, `shift_id=NULL`.
28. **Ochiq smena + BOSHQA kassirning TILLi → `ERR_TILL_SHIFT_MISMATCH`** — global
    yumshatish sodir BO'LMAGANINI isbotlaydi.
29. Ochiq smena + **shu** smenaning TILLi → muvaffaqiyat, leg `ON_SHIFT` + `shift_id`.
30. Smenasiz + post-T0 + hisob berilmagan → `ERR_CUSTODY_REQUIRED`.
31. `SHIFT_BOUND` operatsiyalar (sotuv) — **hech narsa o'zgarmagan**, mavjud testlar yashil.
32. Domeni e'lon qilinmagan chaqiruv → `SHIFT_BOUND` (fail-closed default).
33. Arxivlangan / boshqa filial / boshqa valyuta hisob → rad (uch holat).
34. Gibrid: TILL oyog'i `ON_SHIFT`, SEYF oyog'i `OFF_SHIFT` — **bitta** hujjatda.

### E. SEYF ochilishi (§12)
35. Ochilish ikki marta → ikkinchisi rad.
36. `counted <= balance` → aniq xato, `IN` yozilmaydi.
37. `attestation_ref` yoki `attested_by` yo'q → rad.
38. Menejer bo'lmagan xodim → rad.
39. Ochilishdan **keyin** SEYFdan to'lov → muvaffaqiyat (zanjirning uchdan-uchi, §0).
40. **`compare_engine` yangi tashuvchini `EXTRA_LEDGER` deb belgilamaydi** (report parity).

### F. Kreditor hayot davri va atributsiya
41. Ochiq qoldiqli kreditorni arxivlash → `409 CREDITOR_HAS_BALANCE`; qoldiq **daftardan**
    hisoblanadi, keshdan emas (TILL nuqsoni takrorlanmaydi — §3.3).
42. Arxivlangan kreditor: tanlagichda **YO'Q**, kartasi/daftari **O'QILADI**.
43. Havolali kreditor → xodimni soft-delete / `status=terminated` / rol o'zgarishi →
    kreditor va qoldiq **o'zgarmaydi**.
44. Xodimsiz kreditor (investor) → to'liq ishlaydi.
45. Kreditor rename → eski hujjat **eski nomni** ko'rsatadi (snapshot); audit
    `before/after` yozilgan.
46. Nom snapshoti **so'rov tanasidan olinmaydi**: klient boshqa nom yuborsa ham server
    `creditors` dan o'qiganini yozadi.
47. `ARCHIVED` kreditorga yangi avans → **fail-closed** (409).
48. Band nomga urinish → `409 CREDITOR_NAME_TAKEN`; **arxivlangan nom ham band**.
49. `UNIQUE (company_id, employee_id)` → ayni xodimga ikkinchi kreditor rad.
50. Havolasi bor kreditorni `unlink` → daftarga **tegmaydi**.
51. `creditor_referenced()` true → hard delete rad, arxivlash taklif qilinadi.
52. **Cross-tenant:** A kompaniya kreditori B xodimiga havola qilishga urinish → rad
    (kompozit FK yoki xizmat tekshiruvi — A-savol javobiga qarab).
53. `tenant_purge`: B ni purge qilish A ning kreditorini **o'chirmaydi** (OR-egalik,
    §3.4).
54. Yangi jadvallar FK grafida yoki `SEMANTIC_REGISTRY`da — aks holda `PURGE_BLOCKED`.

### G. Qaytarish va allokatsiya
55. Qarzdan ko'p qaytarish → **409 `OVER_REPAYMENT`**, **qisqartirish YO'Q** (§5.5).
56. Aniq FIFO allokatsiya: uch avansga bo'lingan qaytarish → deterministik to'plam,
    takrorda **ayni** allokatsiya.
57. `creditor_repayments.ledger_entry_id` majburiy → naqd yozilmasa butun hodisa rad.
58. (b) «pul bevosita sherikga qaytdi» → `ADJUSTMENT`, **naqd qimirlamaydi**.
59. (c) avans bekor → `ADJUSTMENT` + `owner_advance_open` yopiladi, naqd qimirlamaydi.
60. Qoldiq drifti (`balance` kesh ≠ Σ ochiq avans) → tranzaksiya oxirida **rollback**.
61. Butun-som yaxlitlash: 0.01 qoldiq bilan avans **yopiladi** (§5.8).
62. Boshqa valyutadagi avans/qaytarish → `409 CURRENCY_MISMATCH`.

### H. Ruxsatlar
63. Kassir `kreditor.*` kodlarini rol bo'yicha **olmaydi**.
64. `PATCH /employees/{id}/permissions` bilan kassirga `kreditor.repay` berishga urinish →
    B-savol javobiga ko'ra rad yoki ruxsat; **tanlangan xatti-harakat testda qotiriladi**.
65. Administrator `require("kreditor.settle")` dan **avtomatik o'tadi** (`deps.py:128`) —
    ega-only tanlansa, `effective_permissions` darvozasi buni **to'sadi**.
66. `reports.py` (`hisobot.view`) kreditor qoldig'ini **qaytarmaydi**.

### I. Regressiya
67. Mavjud naqd qabul (bitta TILL) — xatti-harakat bit-ba-bit o'zgarmagan.
68. Eski klient shakli (`payment`/`status` + `cash_account_id`) → bitta oyoq (§16.4).
69. `purchases.cash_account_id`: bitta naqd oyoqda **yoziladi**
    (`test_mobile_parity_pg.py:1323` yashil), splitda **NULL** (§15).
70. Split yoki `OWNER_ADVANCE` bor hujjat `PATCH` → `409 HYBRID_EDIT_UNSUPPORTED` (§9).
71. Schema guard T1–T4 yashil; yangi indekslar `REQUIRED_*` da **emas**.
72. Yangi CHECK'lar `check_renderings_pg.py` + `test_check_canon.py` da (§16.3).
73. Xato kodlari ru/uzc lug'atida bor; desktop `api.ts` dict `detail`ni to'g'ri o'qiydi
    (§13).

> ⚠️ Testlarni `PYTHONIOENCODING=utf-8` bilan yurgizmang — `test_check_defs_pg` cp1252
> subprocess sababli **yolg'on yiqiladi** (`local-pytest-utf8-pitfall`).

---

## 18. Implementatsiya bosqichlari

Tartib §0 dagi zanjirdan: **mexanizm → darvoza → ma'lumot.**

| Bosqich | Mazmun | Nega shu tartib |
|---|---|---|
| **1** | SEYF ochilish qoldig'i mexanizmi (§12.2) + `compare_engine` moslashuvi + E guruhi | Busiz SEYF yaratish foydasiz: har to'lov `INSUFFICIENT_CASH` |
| **2** | Custody domeni refaktori (§7.2) + D guruhi, ayniqsa **#28 regressiya qo'riqchisi** | Darvoza ochilmasa split'ning SEYF oyog'i ochiq smenada ishlamaydi |
| **3** | `purchase_settlements` + naqd manbalar + A/B/C; gibrid tahriri **bloklangan** (§9) | Naqd split — do'konning haqiqiy muammosi; kreditorsiz ham to'liq qiymat beradi |
| **4** | Manager UX to'lov qatorlari (§13) + `api.ts` dict-detail tuzatishi + i18n | Fayzan kirill — xom JSON qabul qilinmaydi |
| **5** | Mobil UX qatorlari (§14) | Desktop shartnomasi qotirilgandan keyin |
| **6a** | `creditors` + hayot davri + ruxsatlar + audit (§3) — **pulsiz** | **A va B savollariga javob kerak** |
| **6b** | `OWNER_ADVANCE` oyog'i + `creditor_ledger` + `owner_advance_open` (§4, §5.4) + F guruhi | 6a dan keyin; C, D, E savollari |
| **7** | `creditor_repayments` + allokatsiya (§5) + G guruhi | 6b dan keyin ma'noga ega |
| **8** | Fayzanda **haqiqiy** «Asosiy seyf» + jismoniy sanoq + ochilish qoldig'i | **ENG OXIRIDA**, 1–4 production'da isbotlangandan keyin |

> **Bosqich 8 gacha Fayzan production'ida SEYF YARATILMAYDI.** Hozir u ataylab YO'Q.

**Tavsiya:** 1–4 do'konning haqiqiy muammosini (yetkazuvchiga seyfdan to'lash) **to'liq hal
qiladi** va A–G savollaridan **mustaqil**. 6a–7 (sherik qarzi) mahsulot qarorlariga bog'liq
va 1–4 ni kutib turishga majbur qilmasligi kerak.

---

## Ochiq qarorlar — SIZDAN javob kerak

| # | Savol | Nega men hal qila olmayman | Tavsiyam | Bloklaydi |
|---|---|---|---|---|
| **A** | `employees` jadvaliga **additiv** `UNIQUE (company_id, id)` qo'shishga ruxsatmi? | `tenant_purge.resolve()` egalik yo'llarini **OR** bilan birlashtiradi (`tenant_purge.py:404`) → `employee_id` FK bo'lsa B kompaniyani purge qilish A ning kreditorini o'chirishi mumkin. Strukturaviy yechim kompozit FK, u esa `employees` ga UNIQUE talab qiladi; `cash` DDL bu jadvallarga tegmaslikni yozgan (`cash_ddl_v1.sql:36-39`) | **Ha, qo'shilsin** — `cash` sxemasi allaqachon shu naqshni ishlatadi va bu «xizmat qatlami tekshiradi»dan kuchli | 6a |
| **B** | Kreditor ruxsatlari **ega-only** mi yoki **beriladigan** (grantable) mi? | `require()` administratorni avtomatik o'tkazadi (`deps.py:126-128`) va har qanday admin kassirga istalgan kodni yoqishi mumkin (`employees.py:637-679`). «Kassir hech qachon olmasin» uchun repoda mexanizm **YO'Q** — yangi `NON_OVERRIDABLE` to'plami yozilishi kerak | **Ega-only** `kreditor.settle`/`kreditor.repay`; `kreditor.view` beriladigan | 6a |
| **C** | **Manfiy** kreditor balansi qonuniymi (qarzdan ko'p qaytarish)? | Repoda ikki tomonga presedent bor: to'lov yo'lida manfiy yo'q, qaytarish yo'lida ataylab bor | **Yo'q** — `CHECK (balance >= 0)` + `409 OVER_REPAYMENT`. Manfiy balans hujjatsiz teskari majburiyat yaratardi | 6b |
| **D** | Kreditor **ko'p valyutali** bo'ladimi? | `repaid_amount <= amount` CHECK'i bitta valyutani talab qiladi | **Bitta valyuta** kreditor bo'yicha; kerak bo'lsa valyuta per kreditor qator | 6b |
| **E** | Avans summasi ham **butun som** bo'lsinmi (qaytarish albatta butun som)? | Yaxlitlash qoidasi sotuv/tarozi uchun yozilgan, xarid uchun emas | **Ha** — aks holda 0.01 qoldiq avansni abadiy yopilmas qilishi mumkin | 6b |
| **F** | Kreditor yozuvi **mobilda** bo'ladimi? | Ha bo'lsa `permission_matrix.json` + Dart testi majburlanadi | **Yo'q** (Phase 1) — Manager yetarli; mobil faqat naqd split | 5 / 6a |
| **G** | Rename'dan keyin UI **qaysi nomni** ko'rsatadi? | Joriy balans ekrani jonli nomni, hujjat esa snapshotni ko'rsatadi → bitta shaxs ikki nom bilan chiqadi. Repoda bu ziddiyat allaqachon bor va hal qilinmagan | Hujjatda **faqat snapshot**; kartada joriy nom + «hujjatlarda: …» qatori | 4 / 6b |

### Kod javob bergan savollar (endi OCHIQ EMAS)

| Avvalgi savol | Javob va dalil |
|---|---|
| Nechta ega/sherik? | **Sizning qaroringiz: bir nechta.** Sxema `creditor_id` ni majburiy qildi (§3.0) |
| Xodim bo'lmagan qarz beruvchi? | **Qo'llab-quvvatlanadi** — `employee_id` nullable (§3.4-7) |
| Majburiyat kompaniya yoki filial fakti? | **Kompaniya** — mijoz qarzi presedenti (`reports.py:1717`); `branch_id` yo'q (§3.2) |
| 403 vs 409 shartnomasi? | **Server 403 beradi, mobil 409 kutadi va mobil XATO.** Statuslar `errors.py:39-46` da; `sync.py:71` har 409 ni transient deb belgilaydi, shu bois statuslarni **o'zgartirmaymiz** — mobil ro'yxati tuzatiladi (§14) |
| Manfiy TILL override yuzasi? | **`NEGATIVE_APPROVAL_REQUIRED` — O'LIK KOD:** `_authorize` (`posting.py:254-260`) `allow_negative` + menejer emas kombinatsiyasini **403 bilan avvalroq** rad etadi, va `allow_negative` uchun endpoint/DTO yo'q. Tavsiya: **hozir tiriltirilmaydi**, o'lik yuza deb hujjatlashtiriladi. Tiriltirish `_authorize`ni balansga bog'liq qilishni talab qiladi — fail-open yo'nalishidagi o'zgarish |
| `OPEN NEGATIVE_OVERRIDE` anomaliyasini kim yopadi? | Override yuzasi yo'q ekan — **amalda yuzaga kelmaydi**; yuza qo'shilsa savol qayta ochiladi |

---

## Taqiqlarga rioya (shu hujjat doirasida)

- Kod **o'zgartirilmagan**, migratsiya **yozilmagan**, deploy **qilinmagan**.
- Fayzan production'i **read-only**; **SEYF ataylab YO'Q**; tartib o'zgarmagan: ochilish
  mexanizmi → hisob-turiga xos custody validatsiyasi → split infratuzilmasi →
  testlar/yarashtirish → **faqat shundan keyin** haqiqiy jismoniy sanoq va haqiqiy ochilish
  qoldig'i bilan Fayzan SEYFi.
- **Soxta `CASH_IN` yo'q, yashirin balans mutatsiyasi yo'q** (§12.2).
- `OWNER_ADVANCE` **anonim kompaniya qarzi emas** — `creditor_id` majburiy (§3.0).
- Mavjud `Employee`/`Supplier`/`Customer` **noto'g'ri ishlatilmagan** (§3.1).
- `OWNER_CONTRIBUTION` **qo'shilmagan** (§4).
- Purchase Return semantikasi **implementatsiya qilinmagan** — faqat moslik (§15).
- Mavjud manfiy naqd himoyasi **chetlab o'tilmagan**; SEYF uchun fail-closed **ataylab**
  saqlangan (§7.3).
- `ERR_TILL_SHIFT_MISMATCH` **global o'chirilmagan**; TILL shartnomasi bit-ba-bit
  saqlangan va D-28 testi bilan qotirilgan (§6, §7.2).
