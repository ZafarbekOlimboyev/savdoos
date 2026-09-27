# Xarid to'lovi: SEYF + split settlement — DIZAYN, **REVISION 3**

> **Holat:** dizayn. Phase 0 va Phase 2 **BAJARILGAN va qabul qilingan**; Phase 1, 3, 4 va
> 6a–7 **HOLD**. Fayzan SEYFi **YO'Q** va Phase 1 implement + verify bo'lmaguncha
> yaratilmaydi. Production tegilmagan.
>
> **Baza (repo holati):** `3493d39` — Phase 0 (`4b95e4b`) + Phase 2 (`af17ada` + `3493d39`)
> kiritilgan. Revision 2 hujjati bu o'zgarishlardan OLDINGI repoga qarardi; Revision 3 shu
> yerda qayta bazalandi.

## Havola siyosati (R8 ning ildizini butunlay yopadi)

⚠️ **Satr raqamlari faqat O'ZGARMAS DDL uchun.** Revision 2 da 135 `fayl:satr` havolasi bor
edi; Phase 0/2 dan keyin **24 tasi buzildi**, shundan **4 tasida da'voning O'ZI yolg'on**
bo'lib qoldi. Sababi tuzatilmasa bu har commit'da qaytadi.

**Revision 3 qoidasi:** kod havolalari **SIMVOL NOMI** bilan beriladi
(`fayl · funksiya/konstanta`), satr raqami bilan **emas**. Satr raqami faqat
`cash_ddl_v1.sql` dagi cheklov ta'riflari uchun ishlatiladi — u fayl versiyalangan va
o'zgarmas (mavjud bazaga qayta qo'llanmaydi, §6.6).

---

## Hujjat doirasi — Revision 3 nimani almashtiradi (MUHIM)

Revision 3 — **to'liq almashtirish emas**, ildiz sabablar hujjati. Aniq chegara:

| Mavzu | Kanonik manba |
|---|---|
| R1—R8 ildiz sabablari, yakuniy sxema, bosqich chegarasi, test rejasi | **SHU hujjat** (§2.1—§15) |
| Kreditor hayot davri/arxivlash, kreditor↔xodim ixtiyoriy bog'lanishi, ruxsat matritsasi, Manager UX, Mobil UX, Purchase Return forward-compat, migratsiya/back-compat rejasi | **Revision 2**, commit `3493d39` dagi ayni fayl — havola bilan **kuchda qoladi** |

**Ziddiyat qoidasi:** har qanday to'qnashuvda **Revision 3 g'olib**. Revision 3 olib tashlagan mexanizmlar Revision 2 matnida bo'lsa ham **BEKOR**:

- `revision` ustuni va party-noyoblik indekslari (`ux_ps_cash_party`/`ux_ps_cred_party`) → §2.3;
- Revision 2 ning reversal ledger xaritasi («ayni `source_id` + yangi `leg_index` + `PURCHASE_OUT`») → §3.3;
- `creditor_name_keys` jadvali → G qarori bilan bekor (§9.2-4);
- kreditorga qaytarishda majburiy `CashMovement(payout, reason=...)` → §8.3 (yangi tashuvchi jadval parity ro'yxatiga qo'shiladi, legacy soya yozuvi **emas**);
- `uq_*` noyobligini `REQUIRED_PG_CONSTRAINTS` ga kiritish → §5.2.

⚠️ **Meros bo'limlar hali Revision 2 satr-raqamli havolalarida.** Ular o'z bosqichlari (4, 6a, 7) boshlanishidan OLDIN yuqoridagi **havola siyosati** bo'yicha qayta bazalanishi SHART — bu Phase 6a/7/4 ning **kirish sharti** (§13).

---

## §0. Qabul qilingan qarorlar (A–L) — o'zgarmagan

| # | Qaror |
|---|---|
| **A** | `employees` ga additiv `(company_id, id)` noyobligi — **HA**; kreditor havolasi tenant bilan birga |
| **B** | `kreditor.settle`/`kreditor.repay` — **faqat ega** (V1); administrator avtomatik olmaydi; `kreditor.view` delegatlanadi |
| **F** | Phase 1 da mobil/PWA kreditor UI — **yo'q** |
| **G** | UI **joriy** display nomini ko'rsatadi; identitet `creditor_id`; surat **faqat audit** |
| **H** | Alohida 4 raqamli PIN darvozasi — **yo'q** |
| **I** | Ruxsat/bootstrap holati yo'q bo'lsa mutatsiya marshruti **503 fail-closed** |
| **J** | Legacy SEYF qoldig'i noma'lum bo'lsa migratsiya **BLOCK**; taxmin/nol/sintetik `CASH IN` taqiq |
| **K** | `public` da o'zgarmaslik triggeri Phase 1 da **yo'q**; xavfsizlik chegarasi deb ko'rsatilmaydi |
| **L** | Qaytarish allokatsiyasi — **FIFO**, deterministik |
| — | Manfiy kreditor balansi **taqiq**; kreditor **bir valyutali**; avans/qaytarish **butun som** |

**Ko'p sherik:** `OWNER_ADVANCE` anonim kompaniya qarzi emas — har oyoq
`company_id + creditor_id + amount` ni olib yuradi; bir xarid turli kreditorlardan bir
nechta avans oyog'ini ko'tara oladi.

---

## §1. Bajarilgan ish (Revision 2 dan farq)

| Bosqich | SHA | Nima bajarildi | Dizayndagi o'rni |
|---|---|---|---|
| **0** | `4b95e4b` | `pay_supplier` qulf inversiyasi tuzatildi: global tartib `purchases → suppliers`; FIFO so'rovi yagona manba + `id` tie-breaker; qarz to'plami qulf ostida o'zgarsa rollback+retry; `40P01` retry | §4.5 zanjiri endi **amalda** |
| **2** | `af17ada`, `3493d39` | Custody domeni (`SHIFT_BOUND`/`TREASURY`); SEYF ochiq smenadan mustaqil; TILL shartnomasi bit-ba-bit saqlangan; o'qish yo'li (`decide`) TREASURY uchun `options` beradi; `cash_purchase` preview amali; SEYF + zid `shift_id` → fail-closed | yuqoridagi **amaldagi custody shartnomasi**; §12 yo'li ochildi |

**Amaldagi custody shartnomasi** (`cutover_guard` · `DOMAIN_TREASURY` / `DOMAIN_SHIFT_BOUND`,
`custody_preview` · `OPERATION_DOMAIN`):

- `TREASURY` (`receiving_cash_purchase`, `cash_purchase`, `supplier_payment`): SEYF ochiq
  smenadan **mustaqil**; TILL — smena kassasi bo'lishi shart.
- `SHIFT_BOUND` (qolgan hammasi, e'lon qilinmagan amal ham): o'zgarmagan.
- SEYF oyog'i har doim `OFF_SHIFT`/`shift_id = NULL`; zid `shift_id` berilsa
  `SHIFT_NOT_BELONG_TO_ACCOUNT` (`posting` · `_resolve_shift`).

---

# R1 — `leg_no` allokatori

## §2.1 Hozirgi dalil

| Fakt | Manba |
|---|---|
| Butun repoda **yagona** leg allokatori — `max(leg_index)+1`, qulfsiz, `(tenant, source_type, source_id)` bo'yicha | `services/cash/repositories.py` · `next_leg_index` |
| Uning **yagona** chaqiruvchisi — naqd xarid summasini oshirish | `services/cash/retrofit.py` · `on_cash_purchase_increase` |
| Qolgan BARCHA yo'llarda `leg_index` **berilmaydi** → default `0` | `services/cash/commands.py` · `PostingCommand.leg_index = 0` |
| TRANSFER (inkassa) leg raqamlari **qattiq kodlangan**: OUT=0, IN=1 | `services/cash/posting.py` · `post_transfer` |
| Biznes kaliti | `cash_ddl_v1.sql:232` · `cle_uq_business (tenant_id, source_type, source_id, leg_index)` |
| `IntegrityError → DUPLICATE` o'girishi **faqat `commit=True`** shoxida; `commit=False` da faqat `flush()` | `services/cash/posting.py` · `post` |
| Barcha xarid/qabul hook'lari `commit=False` bilan chaqiriladi | `services/cash/retrofit.py` |
| `PATCH /purchases/{id}` `IntegrityError` ni **umuman tutmaydi** va retry o'rami yo'q | `api/v1/purchases.py` · `edit_purchase` |
| `POST /purchases` va `POST /receiving/commit` — 3 martalik retry → 409 | `api/v1/purchases.py` · `create_purchase` |
| **Leg ajratadigan ikkala yo'l ham `Purchase` qatorini `FOR UPDATE` qiladi** | `api/v1/purchases.py` · `edit_purchase`; `services/lot_correction.py` · `_correct_once` |

## §2.2 Buzilgan shartnoma

Revision 2 **ikki raqobatdosh allokator** e'lon qilgan edi (kanonik-tartib indeksi 0 dan +
`max+1`) va ularni **bitta** noyoblik fazosiga qo'ygan: `ux_ps_leg (purchase_id, leg_no)`
`revision` ni ko'rmaydi. Almashtiruvchi to'plam revizya 0 ning raqamlarini qayta so'raydi.

## §2.3 Tuzatilgan kanonik shartnoma — **BITTA qoida**

> **`leg_no` — hujjat doirasida MONOTON `max(leg_no) + 1`, HUJJAT QULFI ostida berilgan.**
> `revision` ustuni **YO'Q**. Raqam **hech qachon qayta ishlatilmaydi**: PAYMENT oyoqlari
> `0..n-1`, REVERSAL oyoqlari `n..`, almashtiruvchi PAYMENT oyoqlari `n+k..`.

**`max+1` nega XAVFSIZ (formal asos, boss talab qilgan).** Uchta shart birga:

1. **Serializatsiya:** leg ajratadigan har bir yo'l butun tranzaksiya davomida
   `purchases(id)` ni `FOR UPDATE` ushlaydi (dalil: §2.1 oxirgi qatori). Demak ayni
   `purchase_id` uchun RMW **ketma-ket** bajariladi. Bu allokatorning xossasi emas —
   **chaqiruvchining** xossasi, shu bois shartnomaga **yoziladi**: *leg ajratishdan oldin
   hujjat qulfi olinishi SHART.*
2. **Zaxira to'siq:** `ux_ps_leg` (settlement) va `cle_uq_business` (ledger) — qulf
   noto'g'ri olinsa yozuv **rad etiladi**, jimgina buzilmaydi.
3. **Idempotentlik `leg_no` ga TAYANMAYDI:** takror so'rov hujjat darajasida to'siladi
   (`ux_purchases_client_uuid`, `ux_receivings_client_uuid`, tuzatish uchun
   `ux_recv_corr_client (company_id, client_uuid)` + `request_hash` + saqlangan
   `response_json` — `models/receiving.py` · `ReceivingCorrection`).

**Natijada:** «retry ayni `leg_no` ni qaytaradi» degan talab **boshqacha** bajariladi —
muvaffaqiyatli commit'dan keyin retry **umuman yangi oyoq yozmaydi**, u saqlangan javobni
qaytaradi; commit bo'lmagan bo'lsa `max+1` ayni qiymatni beradi (hech narsa commit
qilinmagan).

**Party takrorlanishi:** bir so'rov tanasida ayni `party` (kassa hisobi yoki kreditor) ikki
marta kelsa — **`400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` (§9.4)**, INSERT'dan oldin. Deklarativ
party-noyobligi **YO'Q** (Revision 2 da bor edi): u almashtiruvchi oyoqni imkonsiz
qilardi. «Bir vaqtda bir party uchun bir tirik oyoq» — xizmat qatlami invarianti +
tranzaksiya oxiridagi tekshiruv.

## §2.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | `purchase_settlements`: `leg_no smallint NOT NULL`, `ck_ps_leg_nonneg`, `ux_ps_leg (purchase_id, leg_no)`. `revision` ustuni **yo'q**; party noyoblik indekslari **yo'q** |
| **Xizmat** | Settlement yozuvchisi `purchases` ni `FOR UPDATE` qiladi (Phase 0 zanjiri), so'ng `max(leg_no)+1`; ledger tomoni ayni qulf ostida `next_leg_index` |
| **Migratsiya/boot** | Yangi ustun yo'q → T1 qoidasi qo'llanmaydi. `ux_ps_leg` → `REQUIRED_INDEXES` (§5.2) |
| **SQLite** | Ta'sir yo'q (oddiy indeks, funksiyasiz CHECK) |
| **Readiness/check_canon** | `ck_ps_leg_nonneg` grammatikadan o'tadi (repetitsiya P9) |
| **Reconciliation/report** | Split oyoqlar `leg_index` ni egallaydi → kutilgan tomon shundan qurilishi kerak (§8.3) |
| **Concurrency/idempotentlik** | Yuqoridagi uch shart; qulf olinmagan yo'l **kod ko'rigida rad etiladi** |
| **Rollback** | Oyoqlar commit qilinmagan bo'lsa raqamlar qaytadi; commit qilingan oyoq **hech qachon** qayta ishlatilmaydi (monoton) |

## §2.5 Testlar

1. Bir xil tana ikki marta → bitta hujjat, bitta oyoq to'plami.
2. Tuzatish hujjati `client_uuid` takrori → **saqlangan javob**, yangi oyoq yo'q.
3. Almashtiruvchi to'plam → `leg_no` PAYMENT/REVERSAL raqamlaridan **yuqori**,
   `ux_ps_leg` buzilmaydi.
4. Ayni party bir tanada ikki marta → `400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` (§9.4).
5. **Hujjat qulfisiz** ajratish urinishi → parallel ikki tranzaksiya `ux_ps_leg` da
   to'qnashadi (qulf shartining zarurligini isbotlaydi).
6. `commit=False` yo'lida `cle_uq_business` buzilsa xato **yutilmaydi** (§3.5).

---

# R2 — REVERSAL shartnomasi

## §3.1 Hozirgi dalil — **koddan o'qilgan, ixtiro qilinmagan**

`ReversalCommand` (`services/cash/commands.py`) — 8 maydon:
`reverses_id`, `source_id`, `cash_account_id`, `origin_shift_id`, `device_occurred_at`,
`idempotency_key`, `reason`, `tenant_id`.

| Fakt | Manba |
|---|---|
| `source_id` izohi **so'zma-so'z**: «yangi manba identifikatori (original'niki EMAS)» | `commands.py` · `ReversalCommand.source_id` |
| **`leg_index` maydoni YO'Q** → `post_reversal` uni uzatmaydi → default `0` | `commands.py`; `posting.py` · `post_reversal` |
| `category` = **`ADJUSTMENT`, qattiq kodlangan** | `posting.py` · `post_reversal` |
| `direction` = aslining **teskarisi** (hisoblanadi); `amount`, `cash_account_id`, `source_type`, `currency` = **aslidan** | `posting.py` · `post_reversal` |
| `cash_account_id` va `reason` — **o'lik maydonlar** (o'qilmaydi; `reason` uchun ustun ham yo'q) | `posting.py`; `adapters.py` · `reversal` |
| `adapters.reversal` `source_id` berilmasa **`uuid4()`** quradi → biznes identiteti **barqaror emas** | `adapters.py` · `reversal` |
| Bir aslga **ko'pi bilan bitta** reversal | `cash_ddl_v1.sql:238` · `cle_uq_reverses` (qisman, `reverses_id` bo'yicha; **tenant ustuni yo'q**) |
| Reversal va asl leg **ayni tenantda** | `cash_ddl_v1.sql:227-228` · `cle_reverses_fk` |
| O'zini reversal qilish mumkin emas | `cash_ddl_v1.sql:204` · `cle_no_self_rev` |
| «faqat TO'LIQ reversal» | `cash_ddl_v1.sql:194` izohi: `-- full reversal only (never a partial refund)` |
| Summa tengligi va `ALREADY_REVERSED` — **xizmat** qatlamida | `posting.py` · `_validate_reversal` |
| **Reversal ishlab chiqarishda O'LIK KOD** — bitta ham chaqiruv joyi yo'q, faqat testlar | `adapters.py` · `reversal` (chaqiruvchilar: `tests/cash/test_posting_service.py`) |
| Qisman qaytarish reversal EMAS | `adapters.py` izohi; `db/cash/PURCHASE_RETURN_identity.md`; `api/v1/sales.py` izohi |

⚠️ **Jim no-op tuzog'i:** chaqiruvchi **band** `source_id` bersa, `post` ning erta
idempotentlik tekshiruvi mavjud qatorni `DUPLICATE` qilib qaytaradi — **xato yo'q va
reversal YOZILMAYDI** (`posting.py` · `post`). Shu bois `source_id` **deterministik va
noyob** bo'lishi shart.

## §3.2 Buzilgan shartnoma

Revision 2 §11 «reversal legi **ayni** `source_id` ostida **yangi** `leg_index` oladi,
`category = PURCHASE_OUT`» deb yozgan edi. Uchala band ham kod bilan **zid**, va
to'g'ridan-to'g'ri `INSERT` taqiqlangani uchun chetlab o'tish yo'li ham yo'q. **Revision 1
bu yerda TO'G'RI edi; Revision 2 uni buzdi.**

## §3.3 Tuzatilgan kanonik shartnoma

> Settlement reversali **`post_reversal` orqali** yoziladi (to'g'ridan-to'g'ri INSERT yo'q),
> quyidagi **aniq** xarita bilan:

```
reverses_id  = purchase_settlements(asl PAYMENT oyog'i).ledger_entry_id
source_id    = REVERSAL settlement qatorining O'Z `id` si     <-- deterministik, noyob
leg_index    = 0            (yangi source_id ostida to'qnashuv IMKONSIZ)
source_type  = aslidan      (PURCHASE)
category     = ADJUSTMENT   (servis qattiq kodlaydi — DIZAYN BUNI QABUL QILADI)
direction    = aslining teskarisi (servis hisoblaydi)
amount       = aslidan      (servis tengligini majburlaydi)
origin_shift_id = SEYF uchun NULL (majburiy, Phase 2); TILL uchun smena
```

**Nega `source_id` = reversal settlement qatorining id'si:** u (a) kod talab qilgan
«yangi» identifikator, (b) **deterministik** — replay ayni kalitni qayta hisoblaydi, ya'ni
`adapters.reversal` ning `uuid4()` tuzog'iga tushmaydi, (c) provenans: ledger legi
settlement qatoriga qaytib bog'lanadi.

**Tuzatish = reversal + almashtirish.** `cle_uq_reverses` **global** (tenant ustuni yo'q),
ya'ni **reversalni reversal qilish IMKONSIZ**. Shu bois tuzatish zanjiri: asl oyoqlarni
reversal qilish → **yangi** PAYMENT oyoqlari (`max(leg_no)+1`). Reversal zanjiri
**hech qachon** qurilmaydi.

⚠️ **Birinchi ishlab chiqarish ishlatilishi.** Reversal hozir o'lik kod. Phase 3 uni
**birinchi marta** jonli yo'lga qo'yadi — shu bois §3.5 dagi testlar shartnomaning har
bandini alohida qotiradi, va `ReversalCommand` ning ikki o'lik maydoni
(`cash_account_id`, `reason`) **ishlatilmaydi** deb yoziladi (ular o'zgartirilmaydi:
doira tashqarisi).

## §3.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | `purchase_settlements`: `kind`, `reverses_id` (o'ziga FK), `ck_ps_reversal_iff`, `ck_ps_no_self_rev`, `ux_ps_reverses`. **Summa tengligi uchun kompozit FK KERAK EMAS** — servis (`_validate_reversal`) ledger tomonida majburlaydi; settlement tomonida tranzaksiya-oxiri invarianti |
| **Xizmat** | Yozuvchi `post_reversal` ga `source_id = <reversal settlement id>` va SEYF uchun `origin_shift_id=None` uzatadi; `ALREADY_REVERSED` → `409` |
| **Migratsiya/boot** | Yangi cash DDL **kerak emas** (mavjud maydonlar) |
| **SQLite** | `cash` sxemasi SQLite'da yo'q → reversal yo'li mahalliy bazada **no-op**; settlement qatori esa yoziladi → mahalliy test faqat settlement tomonini ko'radi (aniq qayd etiladi) |
| **Readiness/check_canon** | Yangi CHECK'lar funksiyasiz (P9) |
| **Reconciliation/report** | Reversal legi `category = ADJUSTMENT` va **yangi `source_id`** bilan chiqadi → kutilgan tomon shuni **bilishi shart** (§8.3), aks holda `EXTRA_LEDGER` |
| **Concurrency/idempotentlik** | Deterministik `source_id` + `cle_uq_reverses` + `ALREADY_REVERSED`: takror reversal **rad**, jim no-op **emas** |
| **Rollback** | Reversal — yangi qator; asl oyoq **hech qachon** o'zgartirilmaydi (append-only) |

## §3.5 Testlar

1. Asl oyoq reversal qilinadi → ledger legi: `reverses_id` asl, `category=ADJUSTMENT`,
   `direction` teskari, `amount` teng, `source_id` = reversal settlement id.
2. Ayni oyoqni ikkinchi marta reversal → `ALREADY_REVERSED` (409), yangi leg yo'q.
3. **Jim no-op qo'riqchisi:** `source_id` band qiymat bilan berilsa → xizmat **rad etadi**
   (erta-idempotentlik `DUPLICATE` ni «bajarildi» deb qaytarmaydi).
4. Reversal + almashtirish: yangi PAYMENT oyoqlari `leg_no` bo'yicha yuqorida,
   `ux_ps_leg` buzilmaydi, `unpaid` qayta hisoblanadi.
5. Reversalni reversal qilish urinishi → `cle_uq_reverses` yoki xizmat rad etadi.
6. SEYF oyog'ining reversali: `origin_shift_id=None` → leg `OFF_SHIFT`; smena berilsa
   `SHIFT_NOT_BELONG_TO_ACCOUNT`.
7. Qisman summa bilan reversal urinishi → `_validate_reversal` rad etadi.

---

# R3 — Kompozit FK ota-kalitlari

## §4.1 Hozirgi dalil

| Jadval | Mavjud nomzod kalitlar | `(company_id, id)` |
|---|---|---|
| `purchases` | PK(`id`), UNIQUE(`company_id`,`doc_no`), qismiy `ux_purchases_client_uuid` | **YO'Q** |
| `employees` | PK(`id`), ikki qismiy indeks | **YO'Q** |
| `suppliers` | PK(`id`), qismiy `ux_suppliers_client_uuid` | **YO'Q** |
| `companies`, `branches` | PK(`id`) + qismiy indekslar | **YO'Q** |
| `customer_groups` | PK + `uq_cgroup_company_name` + **`uq_cgroup_company_id`** | **BOR** |
| `brands` | PK + **`uq_brand_company_id`** | **BOR** |
| `cash.cash_accounts` | PK + `ca_uq_tenant_id` + uch kompozit UNIQUE | **BOR** (`tenant_id`) |

**Presedent** (`models/customers.py` · `Customer` / `CustomerGroup`): ota jadvalda
`UniqueConstraint("company_id","id")`, bolada nullable kompozit FK, izohda «CROSS-TENANT
BOG'LANISH IMKONSIZ … MATCH SIMPLE: `group_id` NULL bo'lsa tekshiruv o'tkazib yuboriladi».

**Boot tartibi** (`initdb.py` · `main`): `_create_all` → `_ensure_columns` →
`_ensure_indexes` → `_ensure_tenant_scoped_catalogs` → `_ensure_lot_checks` →
`_ensure_foreign_keys` → … → `_verify_required_schema`.
Ya'ni **`_create_all` HAR DOIM barcha `_ensure_*` dan OLDIN.**

**Mavjud jadvalga UNIQUE CHEKLOV qo'shadigan yagona yo'l** —
`_ensure_tenant_scoped_catalogs` → `_migrate_one`, va u:
- faqat `_TENANCY_TABLES` dagi **ikki** juftlikka bog'langan (`customer_groups`, `brands`);
- jadval **tenantga bog'lanmagan** bo'lsa va qator bo'lsa **bootni to'xtatadi**
  (`company_id` egasini taxmin qilib bo'lmaydi);
- `ADD CONSTRAINT … UNIQUE` → **ACCESS EXCLUSIVE** qulf (o'lchangan jadval `initdb.py` da).

## §4.2 Buzilgan shartnoma

Revision 2 `fk_ps_purchase_same_company … → purchases(company_id, id)` ni talab qilgan, ota
kalit esa **yo'q** va uni qo'shadigan mexanizm ham yo'q. `_TENANCY_TABLES` yo'lini
«nusxalash» **ishlamaydi**: u tenantga bog'lanmagan jadval uchun mo'ljallangan va qatorli
jadvalda bootni to'xtatadi.

## §4.3 Tuzatilgan kanonik shartnoma

> **Ota-kalit — NOMLANGAN, QISMAN BO'LMAGAN UNIQUE INDEKS** (jadval cheklovi **emas**),
> ikki yo'l bilan yaratiladi va **ikki yo'lda ham AYNI nom** bilan:
>
> 1. **Modelda** — `Index("uq_purchases_company_id", "company_id", "id", unique=True)`
>    (ota jadval `__table_args__` ida) → yangi bazada `create_all` yaratadi.
> 2. **Bootda, `_create_all` dan OLDIN** — yangi qadam `_ensure_parent_uniques()`:
>    `CREATE UNIQUE INDEX IF NOT EXISTS uq_… ON t (company_id, id)`.

**Nega indeks, cheklov emas** (uch mustaqil sabab):
1. `(company_id, id)` da dublikat **mantiqan imkonsiz** (`id` — PK), ya'ni indeks qurilishi
   ma'lumot sababli **hech qachon yiqilmaydi** → `_TENANCY_TABLES` ning qator-rad etishi
   kerak emas.
2. PostgreSQL FK ota-kaliti uchun **noyob indeks yetarli** — cheklov talab qilinmaydi
   (repetitsiya **P3** isbotladi).
3. SQLite'da `UniqueConstraint` indeksining **nomi yo'qoladi** (`sqlite_autoindex_*`), ya'ni
   nom bo'yicha tayyorlik tekshiruvi mahalliy bazada **abadiy qizil** bo'lardi; nomlangan
   `CREATE UNIQUE INDEX` esa ikki dialektda ham nomini saqlaydi (repetitsiya **P10**).

**TARTIB QAT'IY SHART** (repetitsiya **P4** isbotladi): ota-kalit bo'lmasa kompozit FK'li
`CREATE TABLE` **42830** bilan rad etiladi. `create_all` birinchi DDL qadami bo'lgani uchun
yangi qadam **undan oldin** turishi shart:

```
0) _ensure_parent_uniques()   <-- YANGI: qadam, to_regclass bilan (jadval yo'q bo'lsa no-op)
1) _create_all()              <-- yangi bola jadvallar kompozit FK bilan
2) _ensure_columns() ... (o'zgarmagan)
```

**Kompozit FK'lar ro'yxati** (har biri uchun ota-kalit tasdiqlangan):

| Bola | FK | Ota-kalit |
|---|---|---|
| `purchase_settlements` | `(company_id, purchase_id) → purchases(company_id, id)` | `uq_purchases_company_id` (yangi) |
| `purchase_settlements` | `(company_id, creditor_id) → creditors(company_id, id)` | `uq_creditors_company_id` (yangi jadval) |
| `creditors` | `(company_id, employee_id) → employees(company_id, id)` | `uq_employees_company_id` (yangi) |
| `creditor_ledger`, `creditor_repayments`, `owner_advance_open`, `creditor_advance_allocations` | `(company_id, creditor_id) → creditors(company_id, id)` | `uq_creditors_company_id` |
| `owner_advance_open` | `(settlement_id, settlement_kind) → purchase_settlements(id, kind)` | `uq_ps_id_kind` (yangi jadval) |

`ledger_entry_id` — **FK'siz mantiqiy havola** (cross-schema; K qarori, `purchases.cash_account_id`
naqshi). Kafolat xizmat qatlamida: qiymat **shu tranzaksiyada yaratilgan** qatordan.

## §4.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | 2 ta mavjud jadvalga additiv **indeks** (ustun **yo'q**); yangi jadvallar ichida kompozit FK va `(company_id, id)` / `(id, kind)` noyobliklari |
| **Xizmat** | O'zgarish yo'q (DDL darajasi) |
| **Migratsiya/boot** | Yangi `_ensure_parent_uniques()` qadami `_create_all` dan **oldin**; `to_regclass` bilan qulfsiz prechek; `_lock_retry` naqshi; **FATAL emas** — indeks qurilmasa `_create_all` o'zi 42830 bilan to'xtaydi va xabar aniq bo'ladi |
| **SQLite** | Ikki dialektda ham ishlaydi (P5, P10); FK majburlanadi (P6) |
| **Readiness** | Yangi indekslar `REQUIRED_INDEXES` + kuchli tekshiruv (§5.2) |
| **Reconciliation/report** | Ta'sir yo'q |
| **Concurrency** | `CREATE UNIQUE INDEX` (CONCURRENTLY **emas**) ota jadvalga qisqa `ACCESS EXCLUSIVE` oladi; boot qulf byudjeti (`SAVDOOS_BOOT_LOCK_TIMEOUT`, standart `2s`) amal qiladi; jadval band bo'lsa retry |
| **Rollback** | Indeksni `DROP INDEX` bilan olib tashlash mumkin, lekin **FK unga bog'liq** → rollback tartibi: bola FK → indeks |

## §4.5 Testlar

1. **Fresh** baza: `initdb` → yangi jadvallar kompozit FK bilan quriladi.
2. **Mavjud** baza: qatorli `purchases`/`employees` ustida indeks qo'shiladi, boot
   yiqilmaydi, ikkinchi boot **no-op**.
3. **Tartib qo'riqchisi:** ota-kalit qo'lda `DROP` qilinsa `create_all` **42830** beradi
   (P4 ning testga aylangan shakli).
4. Cross-tenant INSERT → FK rad etadi (PG **23503**, SQLite `FOREIGN KEY constraint failed`).
5. `employee_id IS NULL` → MATCH SIMPLE bo'yicha **o'tadi**.
6. `tenant_purge`: B kompaniyani purge A ning kreditorini **o'chirmaydi**; yangi jadvallar
   FK grafida topiladi, `SEMANTIC_REGISTRY` ga **qo'shilmaydi**.

---

# R4 — Noyoblik registri va tayyorlik

## §5.1 Hozirgi dalil

| Ro'yxat | Nimani tekshiradi | Qattiqligi |
|---|---|---|
| `REQUIRED_COLUMNS` | (jadval, ustun) **mavjudligi** (tip **emas**) | boot-FATAL |
| `REQUIRED_PG_CONSTRAINTS` | **FAQAT CHECK** cheklovlari (`contype = 'c'`) | tayyorlik |
| `CHECK_DEFINITIONS` | CHECK **ifodasi** (`check_canon` bilan) | tayyorlik |
| `REQUIRED_INDEXES` | **FAQAT NOM** (inspector) | boot-FATAL |
| `IDEMPOTENCY_INDEXES`, `OPTIONAL_UNIQUE_INDEXES` | nom **+ `indisunique` + `indisvalid`** (`_UNIQUE_INDEX_SQL`) | jurnal / tayyorlik |
| `PERFORMANCE_INDEXES` | nom | jurnal |

⚠️ **Eng qattiq sinf eng zaif tekshiriladi:** `REQUIRED_INDEXES` nom bilan cheklanadi, ya'ni
yaroqsiz, noyob bo'lmagan yoki boshqa ustunlar ustidagi **ayni nomli** indeks «joyida» deb
o'tadi. Kuchli tekshiruv (`_UNIQUE_INDEX_SQL`) faqat IDEMPOTENCY/OPTIONAL sinflariga
qo'llangan. Faylning o'zi bu xavfni yozgan.

⚠️ **UNIQUE cheklov uchun registr YO'Q.** Uni `REQUIRED_PG_CONSTRAINTS` ga yozish →
har doim «yo'q» **va** `_ensure_lot_checks` da `CHECK_DEFINITIONS[name]` **KeyError**
(try'dan tashqarida) → **boot qulaydi**.

⚠️ **`cash` sxemasi registrdan tashqarida:** har so'rov `nspname = 'public'`;
`deploy_cash_schema` sxema mavjud bo'lsa DDL'ni **umuman** yurgizmaydi → `cash_ddl_v1.sql`
ga qo'shilgan yangi obyekt mavjud bazaga **hech qachon** tushmaydi.

⚠️ **Model → boot drifti qo'riqlanmagan:** modelga qo'shilgan, lekin boot ro'yxatiga
yozilmagan `Index`/`UniqueConstraint` ni tutadigan umumiy test **yo'q**.

## §5.2 Tuzatilgan kanonik shartnoma

| Obyekt turi | Registr | Qo'shimcha shart |
|---|---|---|
| Yangi **CHECK** | `CHECK_DEFINITIONS` **+** `REQUIRED_PG_CONSTRAINTS` **+** `check_renderings_pg.py` | `test_check_canon.py` dagi `len(RENDERINGS)` literali yangilanadi; rendering **haqiqiy PG dan olinadi** |
| Yangi **UNIQUE indeks** (FK ota-kaliti va idempotentlik kalitlari) | `REQUIRED_INDEXES` | ⚠️ **kuchli tekshiruv shart**: `_UNIQUE_INDEX_SQL` (nom + `indisunique` + `indisvalid`) `REQUIRED_INDEXES` ga ham yoyiladi — FK ota-kaliti uchun «nom bor» YETARLI EMAS |
| Tezlik indekslari | `PERFORMANCE_INDEXES` | — |
| UNIQUE **cheklov** | **HECH QAYERGA** | Cheklov umuman ishlatilmaydi (§4.3) |
| `cash` sxemasidagi yangi obyekt | — | **YO'Q**: Revision 3 `cash` sxemasiga hech narsa qo'shmaydi |

**Fresh ↔ yangilangan paritet:** yangi **drift qo'riqchisi testi** — model
`Base.metadata` dagi har bir `Index` nomi boot ro'yxatlaridan birida **bo'lishi shart** va
teskarisi. Bu Revision 2 da yo'q edi va aynan shu bo'shliq `(company_id, id)` ni ikki
joyda qo'lda saqlashni talab qilardi.

## §5.3 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | Yangi CHECK'lar **funksiyasiz** (P9 tasdiqlagan 27 ifoda) |
| **Xizmat** | O'zgarish yo'q |
| **Migratsiya/boot** | `_UNIQUE_INDEX_SQL` ni `REQUIRED_INDEXES` ga yoyish — **mavjud xatti-harakat o'zgarishi**: ilgari «nom bor» deb o'tgan yaroqsiz indeks endi ko'rinadi. Bu **ataylab**; regressiya ko'rigi kerak |
| **SQLite** | `REQUIRED_PG_CONSTRAINTS`/CHECK holati faqat PG'da; indeks nomlari ikki dialektda ham ko'rinadi (P10) |
| **Readiness** | Yangi obyektlar yo'q bo'lsa `/health/ready` qizil; FK ota-kaliti yo'q bo'lsa boot 42830 bilan to'xtaydi (tayyorlikni kutmaydi) |
| **Report** | Ta'sir yo'q |
| **Concurrency** | Ta'sir yo'q |
| **Rollback** | Ro'yxatdan chiqarish → tayyorlik yashil, obyekt qoladi (xavfsiz) |

## §5.4 Testlar

1. Har yangi CHECK `check_canon.canonical()` dan o'tadi (P9 ning testga aylangan shakli).
2. `len(RENDERINGS)` literali yangi songa teng.
3. **Kuchli indeks tekshiruvi:** `REQUIRED_INDEXES` dagi indeks noyob **bo'lmasa** yoki
   yaroqsiz bo'lsa tayyorlik **qizil** (hozir yashil bo'lardi).
4. Model ↔ boot drift qo'riqchisi: modelga indeks qo'shib ro'yxatga yozmaslik → test qizil.
5. UNIQUE cheklov nomini `REQUIRED_PG_CONSTRAINTS` ga qo'shish urinishi → test qizil
   (KeyError/boot qulashini oldini oladi).

---

# R5 — SQLite

## §6.1 Hozirgi dalil

| Fakt | Manba |
|---|---|
| **Kanonik:** SQLite URL bo'lsa har ulanishda `PRAGMA foreign_keys=ON`; izoh o'chirishni **taqiqlaydi** | `app/db/session.py` |
| Majburlash **engine** ga bog'langan, dialektga emas — boshqa joyda qurilgan SQLite engine FK'ni majburlamaydi | `app/db/session.py` (listener) |
| Repoda **uchta eskirgan, zid izoh** hali «pragma o'chiq» deydi | `services/sales.py`, `services/catalog_reset.py`, `tests/test_lot_phase4a_pg.py` |
| `_create_all` istisnoni **qayta ko'taradi** → boot FATAL (`start.sh` `set -e`) | `initdb.py` · `_create_all` |
| SQLite'da tushuntirish satri **chiqmaydi** (`sqlstate` yo'q) → yalang'och traceback | `initdb.py` · `_sqlstate` |
| Modelda **7 ta** CHECK, hammasi `models/inventory.py` da; bittasi `.ddl_if(dialect="postgresql")` bilan **PG-only** | `models/inventory.py` |
| PG-only CHECK `ck_track_expiry_implies_lots` **modelda umuman yo'q** → SQLite bazada ham yo'q, model izohi esa «initdb majburlaydi» deydi | `models/catalog.py`, `required_schema.py` |
| **`run.bat` `initdb` ni FAQAT venv yo'q bo'lganda yuritadi** → mavjud mahalliy `savdoos.db` yangi obyektlarni **olmaydi** | `run.bat` |

## §6.2 Buzilgan shartnoma

Revision 2 «SQLite FK'ni majburlamaydi» degan (eskirgan izohlarga tayanib) va shu sababli
kompozit FK'lar uchun ota-kalit talabini **umuman ko'rmagan**. Bu `run.bat` yo'lini
buzardi.

## §6.3 Tuzatilgan kanonik shartnoma

> **SQLite ham birinchi darajali maqsad.** Har bir kompozit FK, UNIQUE va CHECK ikki
> dialektda ham **haqiqatan quriladi va majburlanadi**. PG-only DDL faqat mavjud mexanizm
> bilan: `.ddl_if(dialect="postgresql")`.

**Repetitsiyada isbotlangan** (§11): fresh SQLite boot (P5), ikkinchi boot (P2), qonuniy
INSERT (P5), FK rad (P6), UNIQUE rad (P7), CHECK rad (P8), nomlangan indekslar (P10),
`foreign_keys=ON` (P6).

**Qismiy indekslar:** `postgresql_where` **va** `sqlite_where` **ikkisi ham** beriladi
(repetitsiyada `ux_ps_reverses` shunday qurilgan va ikki dialektda ham ishladi).

**Kashf etilgan tuzoq (implementatsiya uchun majburiy):** SQLite'da UUID ORM tipi bilan
saqlangan qiymat xom SQL'ga **string** sifatida bog'langanida **mos kelmaydi** — repetitsiyada
qonuniy INSERT FK xatosi bergan, sabab aynan shu. Demak **UUID ustunlariga tegadigan har
qanday xom SQL** ustun tipining bind-protsessori orqali (Core `insert()` yoki
`bindparam(type_=...)`) o'tishi shart.

**Naqd oyoq darvozasi (yangi, gate topgan).** `cash_enabled()` **har qanday** non-PostgreSQL dialektda `False` qaytaradi (`services/cash/retrofit.py` · `cash_enabled` — birinchi shart `bind.dialect.name != "postgresql"`). Demak SQLite'da ledger legi **hech qachon** yozilmaydi, `ck_ps_ledger_iff` esa naqd manbali settlement qatoriga `ledger_entry_id NOT NULL` ni majburlaydi — ya'ni **naqd settlement qatori SQLite'da yozilishi mumkin emas**.

> **Qaror: CHECK **saqlanadi**, yozuvchi **darvozalanadi**.** Split settlement yozuvchisi `cash_enabled(db)` bo'lmasa **yozmaydi** — mahalliy baza mavjud bitta-to'lov yo'lida (`Purchase.paid_amount` + `SupplierLedger`) qoladi, ya'ni bugungi xatti-harakat. Alternativa (`ledger_entry_id` ni nullable qilish) **rad etiladi**: u pul kafolatini PG'da ham bo'shatardi.
>
> Oqibat: **split** funksiyasi PG'da (Railway) ishlaydi; `run.bat` mahalliy demosida ko'rinmaydi. Bu qabul qilinadigan chegara — `cash` sxemasining o'zi ham mahalliy bazada yo'q.

**Xato diskriminatsiyasi (yangi, gate topgan).** «Qaysi noyoblik buzildi» ni **nom** bo'yicha ajratish faqat PG'da mumkin (`psycopg` `diag.constraint_name`); SQLite `IntegrityError` da bunday maydon yo'q. Shu bois xizmat qatlami **nomga tayanmaydi**: takrorlanish PG'da nom bilan, SQLite'da esa **oldindan tekshirish** (SELECT) bilan aniqlanadi. Ikki dialektda ham javob **ayni** bo'lishi test bilan qotiriladi (§6.5-6).

**`run.bat` oqibati (ochiq qayd):** mavjud mahalliy baza yangi jadval/indeks/CHECK'ni
olmaydi. Phase 3 ish hajmiga kiradi: `run.bat` ga `python -m app.initdb` ni **har ishga
tushirishda** qo'shish yoki README'da aniq ko'rsatma. Aks holda ishlab chiquvchi
tushunarsiz xato oladi.

## §6.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | Barcha CHECK'lar funksiyasiz; qismiy indekslar ikki dialektga e'lon qilinadi |
| **Xizmat** | `cash` sxemasi SQLite'da yo'q → `cash_enabled()` `False` → **naqd settlement qatori yozilmaydi** (yozuvchi darvozalanadi, §6.3); jadval/indeks/CHECK'lar esa **bor** va struktura darajasida sinaladi; kreditor (`OWNER_ADVANCE`) qatori ledgerga tegmaydi → SQLite'da **yoziladi** |
| **Migratsiya/boot** | `_ensure_parent_uniques()` ikki dialektda ham ishlaydi (xom DDL) |
| **Readiness** | SQLite'da CHECK/constraint holati tekshirilmaydi (faqat PG) |
| **Report** | Ta'sir yo'q |
| **Concurrency** | SQLite'da `_lock_retry` ishlamaydi (sqlstate yo'q) — mahalliy ish uchun ahamiyatsiz |
| **Rollback** | Mahalliy bazani o'chirib qayta yaratish — qabul qilinadigan yo'l |

## §6.5 Testlar

1. **SQLite boot testi:** yangi modellar bilan `python -m app.initdb` **yiqilmaydi**.
2. Ikkinchi boot — no-op.
3. Qonuniy INSERT o'tadi; FK/UNIQUE/CHECK buzilishlari **rad etiladi** (uchta alohida test).
4. Nomlangan indekslar `sqlite_master` da **nomi bilan** ko'rinadi.
5. UUID bind tuzog'i: xom SQL string bilan INSERT **yiqiladi**, Core `insert()` bilan
   **o'tadi** (tuzoqni hujjatlashtiruvchi test).
6. **Naqd darvozasi:** SQLite'da naqd manbali split urinishi — yozuvchi `cash_enabled()`
   bo'lmagani uchun settlement qatori yozmaydi va mavjud bitta-to'lov yo'li ishlaydi; ayni
   so'rov PG'da **yozadi**. `OWNER_ADVANCE` qatori SQLite'da ham yoziladi.
7. **Takrorlanish javobi dialektdan mustaqil:** ayni party ikki marta → ikki dialektda ham
   `400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` (§9.4), nom-diskriminatsiyasiga tayanmasdan.

## §6.6 Eskirgan izohlarni tuzatish

Uch joydagi «pragma o'chiq» izohi **yolg'on** va dizayn qaroriga ta'sir qiladi. Ular
Phase 3 ish hajmiga kiritiladi (kod xatti-harakati o'zgarmaydi — faqat izoh).

---

# R6 — Ochiq majburiyat / `ADJUST_UP`

## §7.1 Hozirgi dalil

| Fakt | Manba |
|---|---|
| Ochiq qoldiq + ortiqcha yopishni to'sish **naqshi** — qator-lokal CHECK: `resolved_qty <= qty` | `models/inventory.py` · `lot_shortfalls` · `ck_lot_shortfall_resolved_le_qty` |
| Allokatsiya qatorlari mavjud (`qty > 0` CHECK bilan) | `models/inventory.py` · `lot_shortfall_resolutions` · `ck_lsr_qty_pos` |
| Dastur qatlami: qulf → qulf ostida idempotentlik replay → ortiqcha yopishni **rad** | `services/lot_resolution.py` |
| Tranzaksiya oxirida invariant **assert** | `services/lot_resolution.py` · `stock_invariant` |
| ⚠️ **Pul domenida «qoldiq = Σ(hodisalar)» kafolati UMUMAN YO'Q**: `supplier_ledger` hech qachon yig'ilmaydi; `Supplier.balance` bilan ajralib ketsa **hech narsa sezmaydi** | `models/purchasing.py`, `api/v1/purchases.py` |
| `SupplierLedger` da **ishora `amount` da** (manfiy bo'ladi) → `amount > 0` kafolati yo'q; `company_id`, `currency`, `client_uuid`, tartib raqami ham yo'q | `models/purchasing.py` · `SupplierLedger` |

## §7.2 Buzilgan shartnoma

Revision 2 transfer maqsadida `ADJUST_UP` yozardi, lekin unga mos ochiq-qoldiq qatori
**tuzilishan imkonsiz** edi (`owner_advance_open` PK = `settlement_id`,
`ck_oao_kind_payment`), ayni paytda «har `ADJUST_DOWN`/`REPAYMENT` uchun
`Σ(allokatsiya) = amount`» invarianti talab qilinardi → transfer **bajarilmas**.

## §7.3 Tuzatilgan kanonik shartnoma

**Ikki daraja, aniq ajratilgan:**

| Daraja | Nima | Kafolat |
|---|---|---|
| **Kreditor qoldig'i** (haqiqat manbai) | `Σ creditor_ledger` ishorali: `+` (`ADVANCE`, `ADJUST_UP`), `−` (`REPAYMENT`, `ADJUST_DOWN`) | `creditors.balance` — **kesh**; tranzaksiya oxirida tengligi tekshiriladi, farq → **rollback** |
| **Har bir avansning ochiq qoldig'i** | `owner_advance_open(amount, repaid_amount, closed_amount)` | Qator-lokal `ck_oao_sum_le_amt`: `repaid_amount + closed_amount <= amount` |

**Savollarga aniq javob:**

| Savol | Javob |
|---|---|
| Qaysi qator ochiq qoldiq **yaratadi** | `creditor_ledger(ADVANCE)` — kreditor darajasida; `owner_advance_open` — avans darajasida (faqat `kind='PAYMENT'` settlement oyog'i uchun, kompozit FK bilan majburlangan) |
| Qaysi hodisa **kamaytiradi** | `REPAYMENT` (naqd chiqdi) va `ADJUST_DOWN` (naqd chiqmadi) |
| **Bevosita sherikka** qaytarish | `ADJUST_DOWN` + `advance_id` + allokatsiya + **sabab majburiy**; naqd **qimirlamaydi**. `REPAYMENT` deb yozish «kompaniya to'ladi» degan yolg'on ma'no berardi |
| Allokatsiya **nimaga FK qiladi** | `creditor_advance_allocations(ledger_id → creditor_ledger.id, advance_id → owner_advance_open.settlement_id)` — ya'ni `REPAYMENT` ham, `ADJUST_DOWN` ham **bir xil mexanizm** |
| FIFO **nimaga qarab** | `owner_advance_open` ning **o'z** ustunlari: `ORDER BY created_at, settlement_id` (JOIN yo'q) |
| `created_at` **teng** bo'lsa | `settlement_id` — majburiy ikkinchi kalit (ayni tranzaksiyada yozilgan ikki avans bir xil `created_at` oladi). **Dialekt-neytral yozilishi SHART:** `::text` PG-only sintaksis — ORM'da `order_by(OwnerAdvanceOpen.created_at, cast(OwnerAdvanceOpen.settlement_id, String))` (yoki tartib ikki dialektda ham barqaror bo'lsa, castsiz ustunning o'zi). Xom `::text` yozilsa SQLite to'plami yiqiladi |
| **Ortiqcha qaytarish** | `ck_oao_sum_le_amt` (baza) **+** dastur qatlami: qulf → replay → `409 CREDITOR_OVER_REPAYMENT` (§9.4). **Clamp YO'Q** |
| **Manfiy balans** | `ck_creditor_bal_nonneg (balance >= 0)` + `ck_cl_bal_nonneg (balance_after >= 0)` |
| `ADJUST_UP` (transfer maqsadi) | Ochiq-qoldiq qatori **YARATMAYDI** — unga mos avans hujjati yo'q. Shu bois allokatsiya invarianti **faqat `REPAYMENT` va `ADJUST_DOWN`** uchun amal qiladi. Kreditor darajasidagi himoya — `balance >= 0` |
| `OWNER_ADVANCE` uchun **soxta naqd oyoq** | **YO'Q.** `ck_ps_ledger_iff` uni majburlaydi: `ledger_entry_id` faqat `*_CASH` uchun |

⚠️ **Bu MEROS EMAS, YANGI shartnoma.** Zaxira domeni naqshi (CHECK + invariant assert)
**o'lchangan va ishlaydi**, lekin **pul domenida bunday kafolat umuman yo'q** —
`supplier_ledger` hech qachon yig'ilmaydi. Revision 2 buni «presedent» deb ko'rsatgan edi;
Revision 3 uni **yangi majburiyat** deb e'lon qiladi va shu bois invariant tekshiruvi
**majburiy ish hajmi**, ixtiyoriy yaxshilanish emas.

## §7.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | `creditors`, `creditor_ledger`, `owner_advance_open`, `creditor_repayments`, `creditor_advance_allocations` (§10) |
| **Xizmat** | Qulf zanjiri (§4.5 + `creditors` sloti), FIFO allokatsiya, invariant assert |
| **Migratsiya/boot** | Faqat yangi jadvallar (`create_all`) + ota-kalitlar (§4.3) |
| **SQLite** | To'liq ishlaydi (P5–P8) |
| **Readiness/check_canon** | 27 CHECK ifodasi o'tdi (P9) |
| **Report** | `OWNER_ADVANCE` naqd oyoq yozmaydi → parity ga **ta'sir qilmaydi** (muhim xossa) |
| **Concurrency** | `creditors` qatori `FOR NO KEY UPDATE` (FK KEY SHARE kuchaytirish tuzog'i); allokatsiya qulf ostida qayta o'qiladi |
| **Rollback** | Barcha qatorlar append-only; yagona o'zgaruvchan maydonlar ikki hisoblagich |

## §7.5 Testlar

1. `repaid_amount + closed_amount > amount` to'g'ridan-to'g'ri UPDATE → CHECK rad.
2. Ortiqcha qaytarish → `409 CREDITOR_OVER_REPAYMENT` (§9.4) (clamp **yo'q**).
3. FIFO deterministik; `created_at` teng bo'lganda `settlement_id` tartibni belgilaydi.
4. Parallel ikki qaytarish → ikkinchisi rad; hisoblagich oshmaydi.
5. `ADJUST_DOWN` (bevosita sherikka) → naqd **qimirlamaydi**, allokatsiya yozilgan.
6. Transfer: `ADJUST_DOWN` + `ADJUST_UP` juftligi; manba avanslari yopiladi; drift
   **rollback qilmaydi**; manba arxivlanadi.
7. Kesh ↔ daftar drifti → tranzaksiya oxirida **rollback**.
8. `OWNER_ADVANCE` oyog'i uchun `ledger_entry_id` NOT NULL bo'lsa → CHECK rad.

---

# R7 — Report parity / shadow compare / backfill

## §8.1 Hozirgi dalil — **IKKI buzilish ALLAQACHON jonli**

| # | Fakt | Manba |
|---|---|---|
| 1 | **Inkassa parity'si ALLAQACHON buzilgan.** Kutilgan tomon collection'ni **bitta** `CASH_OP·movement_id·0 OUT·CASH_OUT` oyoq deb kutadi; runtime esa **TRANSFER juftligi** yozadi (`·0` OUT TILL, `·1` IN SAFE) | `db/cash/migration/phase1.py` · `_cashop_legs_and_review`; `services/cash/posting.py` · `post_transfer` |
| | Natija (deterministik): har post-T0 inkassa uchun **1× MISSING_LEDGER + 2× EXTRA_LEDGER** → `compare_run` REVIEW → readiness NOT_READY. **Birorta test bilan qotirilmagan** | `services/cash/compare_engine.py` |
| 2 | **SEYF agregatda KO'RINMAYDI:** `compare_tenant`/`compare_branch` faqat `type == "TILL"` hisoblarini yig'adi; «SAFE» so'zi modulda **umuman yo'q** | `services/cash/shadow_compare.py` |
| | Phase 2 dan keyin SEYFdan xarid **mumkin** → legacy tomonda ayiriladi, ledger tomonda sanalmaydi → har shunday xarid uchun `compare_till` delta = **+total**, status REVIEW | `services/cash/shadow_compare.py` · `_cash_purchase_net` |
| 3 | `_purchase_out_legs` bir xaridga **aynan bitta** oyoq kutadi: `leg_index=0`, `amount = Purchase.total + Σ PurchaseReturn.amount`, `posting_kind="OFF_SHIFT"`, `provenance="RECONSTRUCTION"` | `phase1.py` · `_purchase_out_legs` |
| 4 | Tarixiy PURCHASE legi uchun hisobni aniqlash zanjirining **hamma shoxi bo'sh** → `HISTORICAL_TILL_UNKNOWN` → REVIEW + SKIP; amalda backfill PURCHASE_OUT legi **yozmaydi** | `db/cash/migration/historical_till.py`, `backfill.py` |
| 5 | `compare_leg` **9 maydonni** solishtiradi: amount (aniq Decimal, tolerantlik **yo'q**), direction, category, branch_id, cash_account_id, shift_id, posting_kind, provenance, device_occurred_at. **Solishtirmaydi:** currency, `leg_index` (u — moslash kalitining qismi), `reverses_id` | `services/cash/compare_engine.py` · `compare_leg` |
| 6 | 15 mismatch kodi; `compare_leg` faqat 9 tasini bera oladi, qolgan 6 tasi `reconcile_events` da tug'iladi | `compare_engine.py` |
| 7 | **Ko'p oyoqli PURCHASE ALLAQACHON jonli:** `edit_purchase` summani oshirsa `on_cash_purchase_increase` DELTA legini `leg_index = max+1` bilan yozadi (asl leg-0 o'zgarmaydi); kutilgan tomon esa **bitta** leg (`leg_index=0`, `amount = total + Σ qaytarish`) kutadi — ya'ni 100→130 oshirilgan naqd xarid **bugun** leg-0 da `WRONG_AMOUNT` (100 vs 130) + leg-1 da `EXTRA_LEDGER` beradi. **Birorta test bilan qotirilmagan** | `services/cash/retrofit.py` · `on_cash_purchase_increase` (`api/v1/purchases.py` · `edit_purchase` chaqiradi); `phase1.py` · `_purchase_out_legs` |
| 8 | Kutilgan tomon xaridni **ikki filtr** bilan chiqaradi: `_no_charge_exists()` (`SupplierLedger·charge` bo'lsa — ya'ni qarz qoldig'i bor bo'lsa) va `status IN (received, cancelled)`. To'liq qarz xarid uchun bu **to'g'ri** (create'da naqd chiqmaydi), lekin **split** xaridda naqd oyoq BOR va charge HAM bor → kutilgan tomon bo'sh qoladi | `phase1.py` · `_purchase_out_legs`, `_no_charge_exists` |

## §8.2 Buzilgan shartnoma

Revision 2 parity muammosini **faqat split xaridga** bog'lagan va uni «kutilgan oyoqlarni
`purchase_settlements` dan qurish» bilan yopamiz deb yozgan. Amalda:
- inkassa buzilishi **allaqachon bor** va split'ga aloqasi yo'q;
- **agregat yuza** (`shadow_compare`) umuman hisobga olinmagan — u SEYFni ko'rmaydi;
- reversal legining yangi shakli (yangi `source_id`, `ADJUSTMENT`) ham hisobga olinmagan;
- **ko'p oyoqli PURCHASE** (summa oshirish) buzilishi ham split'ga aloqasi yo'q — u bugun jonli;
- split xarid uchun `_no_charge_exists()` **kutilgan tomonni butunlay yo'qotadi** (§8.1-8) — Revision 2 buni sezmagan: u faqat «bitta oyoq → ko'p oyoq» muammosini ko'rgan.

⚠️ **Phase 2 ning oqibati (ochiq qayd).** Phase 2 SEYF yo'lini ochdi. **Birinchi haqiqiy
SEYFdan xarid** `compare_till` ni REVIEW ga suradi. Bu Phase 2 da **xatolik emas** (hozir
birorta SEYF yo'q va Fayzanda ham yo'q), lekin **do'kon SEYFdan amalda foydalanishi uchun
R7 yopilishi shart**. Bu Revision 3 ning eng muhim yangi topilmasi.

## §8.3 Tuzatilgan kanonik shartnoma

> **Parity qatlami BESH shaklni bilishi kerak**, va ularning **ikkitasi bugun jonli**
> (Revision 3 dan oldin ham buzilgan edi):

| # | Shakl | Kim o'rgatiladi |
|---|---|---|
| 1 | **Inkassa = TRANSFER juftligi** (`·0` OUT TILL, `·1` IN SAFE) | `phase1._cashop_legs_and_review` — kutilgan tomon juftlik qursin |
| 2 | **SEYF agregatda** | `shadow_compare.compare_tenant`/`compare_branch` — `type IN ('TILL','SAFE')`; `_cash_purchase_net` settlementdan hisoblasin |
| 3 | **Split xarid** = har naqd PAYMENT oyog'i uchun bitta kutilgan leg (`leg_index = leg_no`, `amount`, `cash_account_id`, `posting_kind`). **Filtrlar ham o'zgaradi:** settlement qatorlari bo'lsa `_no_charge_exists()` va `status IN (received, cancelled)` sharti shu xaridga **qo'llanmaydi** — aks holda qarz qoldig'i bor split xarid kutilgan tomondan butunlay tushib qoladi | `phase1._purchase_out_legs` — settlement qatorlari bo'lsa **shulardan** qursin |
| 4 | **Reversal legi** = yangi `source_id`, `category = ADJUSTMENT`, teskari `direction` | kutilgan oyoqlar ro'yxatiga qo'shilsin |
| 5 | **Summa oshirilgan naqd xarid** = leg-0 (asl summa) + leg-1.. (delta) — **bugungi** runtime shakli | `phase1._purchase_out_legs` — kutilgan leg `leg_span="AGGREGATE"` bilan belgilanadi: **yig'indi** shartnomasi (quyida) |

**YIG'INDI SHARTNOMASI (Revision 3 ning shakl 5 ko'rsatmasi TUZATILDI).** Revision 3 «ledgerdagi oyoqlar soni bo'yicha kutilsin» degan edi — bu **doiraviy**: kutilgan tomon haqiqiy tomondan olinsa, solishtirish tautologiyaga aylanadi. Legacy'da asl summa **saqlanmaydi** (`edit_purchase` oshirishda birorta qator yozmaydi, faqat `total`ni ko'taradi), shu bois tiklanadigan yagona haqiqat — **yig'indi**:

> `PURCHASE` manbasi ostidagi BARCHA naqd oyoqlar yig'indisi = `Purchase.total + Σ PurchaseReturn.amount`.

Bu «ko'p leg bo'lsa mayli» EMAS: (a) yig'indi **aynan** teng bo'lishi shart, (b) har oyoq yo'nalish/toifa/hisob bo'yicha **alohida** tekshiriladi, (c) davomiy oyoq (leg>=1) uchun smena/`posting_kind` **da'vo qilinmaydi** (legacy oshirish paytini saqlamaydi), (d) manbasiz qo'shimcha summa yig'indini buzadi → `WRONG_AMOUNT`.

**`RECONSTRUCTION` istisnosi saqlanadi:** SEYF ochilish legi (§12) ataylab
`provenance='RECONSTRUCTION'`, ya'ni `EXTRA_LEDGER` shoxiga **tushmaydi** (u
`provenance == "NORMAL"` ostida). Lekin **backfill verifikatsiya darvozasi** bilan
kesishishi alohida tekshirilishi shart — Revision 2 bu yerda «kod o'zgarishi kerak emas»
deb yozgan, Revision 3 uni **tekshirilmagan** deb belgilaydi va Phase 1 testiga qo'yadi.

**Kreditorga qaytarish** `CASH_OP` manbasi bilan yoziladi va `_is_shadow_movement`
`cash_movements` da qator topmaydi → `EXTRA_LEDGER`. Shu bois yangi tashuvchi jadval
**tanilishi** shart (Phase 7 ish hajmi).

## §8.4 Oqibatlar

| Aspekt | Oqibat |
|---|---|
| **Sxema** | Parity uchun sxema o'zgarishi **yo'q** |
| **Xizmat** | `phase1`, `shadow_compare`, `compare_engine` da kutilgan-tomon kodi o'zgaradi — bu **migratsiya/hisobot** kodi, biznes yo'li emas |
| **Migratsiya/boot** | Backfill darvozasi bilan kesishish Phase 1 da tekshiriladi |
| **SQLite** | `cash` sxemasi yo'q → parity mahalliy bazada ishlamaydi; testlar PG'da |
| **Readiness** | `compare_run` REVIEW → NOT_READY; ya'ni R7 yopilmasa SEYF yo'li **amalda ishlatilmaydi** |
| **Report** | Asosiy maqsad |
| **Concurrency** | Ta'sir yo'q (o'qish yo'li) |
| **Rollback** | Kutilgan-tomon kodini qaytarish parity'ni eski holatiga qaytaradi (ma'lumot buzilmaydi) |

## §8.5 Testlar (aniq shartnoma)

1. **Inkassa (regressiya, hozir qizil):** post-T0 collection → `reconcile_events` da
   `MISSING_LEDGER` va `EXTRA_LEDGER` **YO'Q**; kutilgan juftlik moslashadi.
2. **SEYFdan xarid:** `compare_till`/`compare_tenant` delta = **0**; status REVIEW emas.
3. **Split xarid:** 2 naqd oyoqli hujjat → `matched == 2`, `mismatches == []`.
4. **Reversal:** reversal legi `EXTRA_LEDGER` bermaydi.
5. **Ochilish legi:** `RECONSTRUCTION` legi `EXTRA_LEDGER` bermaydi **va** backfill
   verifikatsiya darvozasini **bloklamaydi**.
6. **Kreditorga qaytarish:** yangi `CASH_OP` tashuvchisi `EXTRA_LEDGER` bermaydi.
7. **Summa oshirilgan naqd xarid (regressiya, hozir QIZIL):** 100 da yaratilgan naqd xarid
   130 ga oshiriladi → `matched == 2`, `WRONG_AMOUNT` va `EXTRA_LEDGER` **yo'q**.
8. **Qisman qarzli split xarid:** bitta naqd oyoq + qarz qoldig'i → naqd oyoq kutilgan
   tomonda **bor** (`_no_charge_exists()` uni yutmaydi), `EXTRA_LEDGER` yo'q.
9. **Manfiy nazorat:** har bir yuqoridagi test kutilgan-tomon tuzatishisiz **QIZIL**.


## §8.6 R-fix implementatsiya shartnomasi (KODDA bajarilgan)

**Eng muhim yangi invariant: KUTILGAN SHAKL IKKI XIL.** `phase1.plan_backfill` ikki iste'molchiga xizmat qiladi va R-fix faqat BIRINI o'zgartiradi:

| Bo'lak | Iste'molchi | R-fix |
|---|---|---|
| `plan["legs"]` (< T0) | `backfill.py` (YOZADI) + `runtime_readiness.py` + manifest hash (`--approved-hash`) | **TEGILMAGAN** — bayt-bayt eski shakl |
| `plan["legs_after_t0"]` (>= T0) | `services/cash/compare_engine.py` (kutilgan tomon) | **runtime shakliga moslashtirildi** |

Shu bois `_leg` ning yangi maydonlari (`cash_account_id`, `account_type`, `leg_span`) **faqat qiymat bo'lganda** qo'shiladi (`_live_fields`) — tarixiy leg dict'i o'zgarmaydi.

**Kodda bajarilgan to'rt derivatsiya:**

1. **Inkassa juftligi** — `_cashop_legs_and_review`: live `collection` → `TRANSFER/mid/0 OUT` (TILL) + `TRANSFER/mid/1 IN` (**tip** `SAFE`). Manzil id'si legacy'da YO'Q (`cash_movements` da ustun yo'q), shu bois shartnoma **tip darajasida** — «tekshirmaymiz» emas (`compare_leg` yangi `account_type` tekshiruvi).
2. **Custody hisobi** — `Purchase.cash_account_id`, `PurchaseReturn.cash_account_id`, `SupplierPayment.cash_account_id`, `CustomerPayment.cash_account_id` (Phase 2 «audit identity») kutilgan tomonga uzatiladi; `_exp_account` uni filial-TILL taxminidan USTUN qo'yadi. Ilgari SEYFdan to'langan naqd xarid `WRONG_ACCOUNT` berardi.
3. **`posting_kind`/`shift_id`** — legacy smena oynasidan olinadi (`_Ctx.shift_at`). `cash.shifts.id` AYNAN legacy `shifts.id` (`retrofit.on_shift_open`), shu bois smena identifikatori ANIQ beriladi. Kesishgan oynalarda faqat ENG ERTA smena hisobga olinadi (`sh_one_open_per_account`: ikkinchi kassirga cash-smena OCHILMAYDI). Custody hisobi noma'lum bo'lsa **da'vo qilinmaydi** (`posting_kind=None`) — noto'g'ri `OFF_SHIFT` da'vosi aynan R-fix tuzatayotgan yolg'on mismatchni berardi.
4. **Yig'indi** — `leg_span="AGGREGATE"` (yuqoridagi shartnoma).

**Agregat yuza (`shadow_compare`) qayta tuzildi.** Ilgari `compare_till` legacy tomonni BUTUN FILIAL bo'yicha, ledger tomonni BITTA hisob bo'yicha hisoblardi — `_rollup` bolalarni qo'shgani uchun ko'p-TILL filialda legacy **hisoblar soniga ko'paytirilardi**. Endi:

- `compare_branch` — legacy kutilmasi **bir marta**, ledger tomon filialning **barcha** naqd hisoblari (**TILL va SEYF**) yig'indisi;
- `compare_tenant` — filiallar bo'yicha roll-up (hisoblar bo'yicha EMAS), filiallar `branches` jadvalidan — ya'ni hisobi provisionlanmagan filial ham solishtiriladi (ilgari bo'sh `parts` → jimgina «MATCH»);
- `compare_till` drill-down sifatida qoladi va ko'p hisobli filialda `scope_warning` beradi.

**Rejim darvozasi.** `on_cash_collection`/`on_bank_deposit` `cash_enabled` (FAQAT infra) bilan darvozalangan edi — `LEGACY_ONLY` rejimda butun deploy ledgerga yozmasa ham inkassa ikki leg yozib ketardi. Endi barcha qardosh hook'lar kabi `dual_write_enabled`.

**Fail-loud.** `reconcile_events(company_id=None)` endi rad etiladi: kutilgan tomon HAMMA tenant uchun qurilib, haqiqiy tomon `tenant_id IS NULL` (ustun NOT NULL) tufayli bo'sh bo'lardi → bazadagi har live hodisa `MISSING_LEDGER`.

**Simmetriya.** `_purchase_return_legs` endi ota-xarid uchun `_purchase_out_legs` bilan AYNI status filtridan o'tadi (docstring buni allaqachon da'vo qilardi).

⚠️ **R-fix doirasidan TASHQARIDA (qayd etildi, bajarilmadi):** legacy soya `CashMovement` faqat `if _sh:` ichida yoziladi, ya'ni smenasiz naqd to'lovning legacy tomonida HECH QANDAY qator bo'lmaydi (bu **yozuvchi** asimmetriyasi, kutilgan tomon emas); transfer oyoqlari `CashLedgerException` qatori olmaydi (monitoring); dry-run manifestining `duplicate_conflicts` doim 0 va `MANUAL_PAYOUT_REVIEW` hech qachon chiqmaydi.

---

# R8 — Havolalar, testlar, qolgan ziddiyatlar

## §9.1 Hozirgi dalil

- Revision 2 da **135** `fayl:satr` havolasi; **111 to'g'ri, 24 noto'g'ri**, shundan
  **4 tasida da'voning O'ZI yolg'on** (Phase 0/2 ularni tuzatgan).
- Hujjat sarlavhasi va «Taqiqlar» bo'limi «kod o'zgartirilmagan» deb yozardi, holbuki
  ~1200 satr kod+test commit qilingan; *Revision 2 ning* bosqich jadvali Bosqich 0 va 2 ni
  **kelajak ish** deb ko'rsatardi.
- `creditor_name_keys` *Revision 2 ning* kreditor bo'limida **ataylab olib tashlangan**,
  lekin ayni hujjatning merge va bosqich bo'limlarida hamon talab qilinardi.
- F qarorining qotiruvchi testi «F-guruhi» deb ko'rsatilgan, aslida **J-96**.

## §9.2 Tuzatilgan kanonik shartnoma

1. **Havola siyosati** (hujjat boshida): satr raqami **faqat** `cash_ddl_v1.sql` uchun;
   qolganlari **simvol nomi** bilan. Bu 24 ta buzilgan havola sinfini **butunlay**
   yo'q qiladi.
2. **Hujjat holati** har Revision boshida repo SHA bilan bazalanadi.
3. **Bajarilgan ish** alohida bo'limda (§1), «kelajak ish» ro'yxatida **emas**.
4. `creditor_name_keys` — hujjatda **yo'q** (G qarori bilan bekor qilingan).
5. Test havolalari guruh **harfi + raqami** bilan va §13 da yagona jadval.

## §9.3 Ziddiyat va havola skani (Revision 3)

| Skan | Natija |
|---|---|
| Uzilgan `§N` havolasi | **0** (skript bilan sanaldi: 46 bo'lim, 100% mos) |
| Satr-raqamli kod havolasi | **faqat `cash_ddl_v1.sql`** (**5 ta**: `:194`, `:204`, `:227-228`, `:232`, `:238`) |
| `creditor_name_keys` **talab** sifatida | **0** (faqat §9.1 da tarixiy izoh) |
| «kod o'zgartirilmagan» da'vosi | **0** — §1 bajarilgan ishni sanaydi |
| Bir-biriga zid bayonot | **0** (§9.4 va §8.1-7/8 shu skanda topilgan — tuzatildi) |
| Traceability (167 topilma) | `PURCHASE_SETTLEMENT_REVIEW_TRACE.md` — RESOLVED 156, SUPERSEDED 8, DEFERRED 3, hal qilinmagan BLOKLOVCHI **0** |
| Shu skanda **yangi** topilgan va tuzatilgan | 4: §8.1-7 (ko'p oyoqli PURCHASE jonli), §8.1-8 (charge filtri), §9.4 (xato kodi registri), §6.3 (`cash_enabled` darvozasi) |

## §9.4 Yangi xato kodlari — **repo konvensiyasi** (yangi, gate topgan)

Gate ikki nuqson topdi: (a) hujjat `400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` (§9.4) / `409 CREDITOR_OVER_REPAYMENT` (§9.4) deb
kod yozdi, lekin ularni **birorta registrga** bog'lamadi va i18n lug'atiga kiritmadi;
(b) `409` presedenti tekshirilmagan edi. Koddan o'qilgan haqiqiy konvensiya:

| Fakt | Manba |
|---|---|
| **Partiya** oilasi: kod FAQAT `X-Error-Code` sarlavhasida; `detail` — toza matn (u i18n lug'atining KALITI) | `core/error_codes.py` (modul izohi) |
| **Naqd** oilasi: `detail = f"{KOD}: matn"` **va** `headers=EC.headers(KOD)`; `ERROR_CODES` — yagona registr, `code_of` faqat shundan taniydi | `services/cash/cutover_guard.py` · `ERROR_CODES`, `_fail` |
| Tarjima **qo'lda**, kod prefiksi bo'yicha, uch til (`ru`/`uzc`/`uz`) | `packages/shared/src/lib/serverErrorsCash.ts` |
| HTTP holati koddan **kelib chiqmaydi**; shakl xatosi = 400 va **barqaror kodsiz**, holat ziddiyati = 409 | `core/error_codes.py` (Phase 5D izohi) |

**Kanonik qaror.** Xarid to'lovi naqd oilasiga kiradi:

| Kod | HTTP | Nima uchun shu holat | Registr |
|---|---|---|---|
| `PURCHASE_SETTLEMENT_DUPLICATE_PARTY` | **400** | so'rov **shakli** buzilgan (bir tanada ayni party ikki marta) — qayta yuborish ayni javobni beradi, holat ziddiyati emas | `ERROR_CODES` + `serverErrorsCash.ts` |
| `CREDITOR_OVER_REPAYMENT` | **409** | **holat** ziddiyati: qoldiq o'zgargan; operator summani kamaytirsa o'tadi | `ERROR_CODES` + `serverErrorsCash.ts` |
| `SETTLEMENT_EDIT_UNSUPPORTED` | **409** | **holat** ziddiyati: hujjatda settlement qatorlari bor, tahrir yo'li reversal talab qiladi | `ERROR_CODES` + `serverErrorsCash.ts` |

⚠️ 5D izohi «shakl xatolarining barqaror kodi YO'Q» deydi. Biz `DUPLICATE_PARTY` uchun kodni **saqlaymiz**, chunki naqd oilasida kod `detail` prefiksi orqali i18n **kaliti** bo'lib xizmat qiladi — kodsiz matn tarjima qilinmasdi. Bu 5D qoidasiga zid emas: u partiya oilasi (kodsiz toza matn) haqida.

**Testlar:** (1) uch kodning har biri `ERROR_CODES` da va `code_of(detail)` uni taniydi; (2) `serverErrorsCash.ts` da uchta kalit uchun `ru`/`uzc`/`uz` mavjud (mavjud `test_lot_error_texts.py` naqshi); (3) HTTP holati yuqoridagi jadvalga **aynan** mos.

---

## §10. Yakuniy sxema (R1–R8 dan keyin)

**Ota-kalitlar (mavjud jadvallarga additiv indeks):**
```
uq_purchases_company_id  UNIQUE INDEX ON purchases (company_id, id)     -- nomlangan, qisman EMAS
uq_employees_company_id  UNIQUE INDEX ON employees (company_id, id)
```

**`purchase_settlements`** (Phase 3)
```
id, company_id -> companies.id, purchase_id, leg_no smallint,
kind varchar(8), source varchar(16), cash_account_id, creditor_id,
creditor_name_snapshot varchar(120), amount numeric(14,2), currency varchar(3),
ledger_entry_id (FK'siz, §4.3), reverses_id -> purchase_settlements.id,
created_at, created_by
-- QABUL yo'li: `receivings.purchase_id` modelda nullable, lekin YAGONA yozuvchi
-- (`api/v1/receiving.py` commit yo'li) uni HAR DOIM Purchase bilan yozadi —
-- settlement identiteti `purchase_id NOT NULL` qabul oqimida ham bajariladi.

ck_ps_amount_pos      amount > 0
ck_ps_kind            kind   IN ('PAYMENT','REVERSAL')
ck_ps_source          source IN ('TILL_CASH','SAFE_CASH','OWNER_ADVANCE')
ck_ps_leg_nonneg      leg_no >= 0
ck_ps_cash_iff        (source IN ('TILL_CASH','SAFE_CASH')) = (cash_account_id IS NOT NULL)
ck_ps_creditor_iff    (source = 'OWNER_ADVANCE') = (creditor_id IS NOT NULL)
ck_ps_cred_name_iff   (source = 'OWNER_ADVANCE') = (creditor_name_snapshot IS NOT NULL)
ck_ps_cred_name_nb    creditor_name_snapshot IS NULL OR creditor_name_snapshot <> ''
ck_ps_ledger_iff      (source IN ('TILL_CASH','SAFE_CASH')) = (ledger_entry_id IS NOT NULL)
ck_ps_reversal_iff    (kind = 'REVERSAL') = (reverses_id IS NOT NULL)
ck_ps_no_self_rev     reverses_id IS NULL OR reverses_id <> id

ux_ps_leg        UNIQUE (purchase_id, leg_no)
ux_ps_reverses   UNIQUE (reverses_id) WHERE reverses_id IS NOT NULL   [pg + sqlite]
uq_ps_company_id UNIQUE (company_id, id)
uq_ps_id_kind    UNIQUE (id, kind)          -- owner_advance_open kompozit FK uchun
fk_ps_purchase_same_company  (company_id, purchase_id) -> purchases(company_id, id)
fk_ps_creditor_same_company  (company_id, creditor_id) -> creditors(company_id, id)
```

**`creditors`** (Phase 6a) — `name_key` (xizmat qatlami normallashtiradi), `status`
(`ACTIVE|ARCHIVED`), `balance` (kesh), `currency`, ixtiyoriy `employee_id`.
CHECK: `ck_creditor_status`, `ck_creditor_arch_iff`, `ck_creditor_name_nb`,
`ck_creditor_key_nb`, `ck_creditor_bal_nonneg`.
Indeks: `uq_creditors_company_id`, `ux_creditors_name_key (company_id, name_key)`,
`ux_creditors_employee (company_id, employee_id) WHERE employee_id IS NOT NULL AND status='ACTIVE'`.
FK: `fk_creditors_employee_same_company`.

**`creditor_ledger`** (Phase 6b) — `settlement_id`, `repayment_id`, `advance_id`,
`transfer_group_id`, `ref_type`, `reason`, `creditor_name_snapshot`.
CHECK: `ck_cl_amount_pos` (`amount > 0` — ishora **tipda**),
`ck_cl_type` (`type IN ('ADVANCE','REPAYMENT','ADJUST_UP','ADJUST_DOWN')`),
`ck_cl_bal_nonneg` (`balance_after >= 0`).
Indeks: `ux_cl_advance UNIQUE (settlement_id)`, `ux_cl_repayment UNIQUE (repayment_id)`.

**`owner_advance_open`** (Phase 6b) — `settlement_id` PK, `settlement_kind`,
`amount` (o'zgarmas), `repaid_amount`, `closed_amount`, `currency`, `created_at`
(settlementdan ko'chirilgan, FIFO kaliti).
CHECK: `ck_oao_amount_pos`, `ck_oao_kind_payment`, `ck_oao_parts_nonneg`,
`ck_oao_sum_le_amt`.
FK: `fk_oao_settlement (settlement_id, settlement_kind) -> purchase_settlements(id, kind)`.

**`creditor_repayments`** (Phase 7) — `cash_account_id`, `currency`,
`ledger_entry_id` NOT NULL, `client_uuid` **NOT NULL**.
CHECK: `ck_cr_amount_pos` (`amount > 0`).
Indeks: `ux_cr_client_uuid UNIQUE (company_id, client_uuid)`.

**`creditor_advance_allocations`** (Phase 7) — `ledger_id -> creditor_ledger.id`,
`advance_id -> owner_advance_open.settlement_id`.
CHECK: `ck_caa_amount_pos` (`amount > 0`).
Indeks: `ux_caa_pair UNIQUE (ledger_id, advance_id)`.

**`cash_account_openings`** (Phase 1) — `attested_by` NOT NULL, `ledger_entry_id` NOT NULL,
`attestation_ref` NOT NULL.
CHECK: `ck_cao_amount_pos` (`counted_amount > 0`),
`ck_cao_ref_nb` (`attestation_ref <> ''` — funksiyasiz, §5.2 grammatikasi).
Indeks: `ux_cao_account UNIQUE (cash_account_id)` — hisob uchun BITTA ochilish.

**Jami yangi CHECK: 27** — `ck_ps_*` 11, `ck_creditor_*` 5, `ck_oao_*` 4, `ck_cl_*` 3,
`ck_cao_*` 2, `ck_cr_*` 1, `ck_caa_*` 1. Repetitsiya **P9** hammasini `check_canon` da
sinadi; §5.2 bo'yicha har biri `CHECK_DEFINITIONS` + `REQUIRED_PG_CONSTRAINTS` +
`check_renderings_pg.py` ga kiritiladi va `len(RENDERINGS)` literali yangilanadi.
**Jami yangi UNIQUE indeks: 14** — ota-kalitlar 5 (`uq_purchases_company_id`,
`uq_employees_company_id`, `uq_creditors_company_id`, `uq_ps_company_id`, `uq_ps_id_kind`)
+ biznes/idempotentlik 9 (`ux_ps_leg`, `ux_ps_reverses`, `ux_creditors_name_key`,
`ux_creditors_employee`, `ux_cl_advance`, `ux_cl_repayment`, `ux_cr_client_uuid`,
`ux_caa_pair`, `ux_cao_account`). Hammasi §5.2 bo‘yicha `REQUIRED_INDEXES` ga
**kuchli tekshiruv** bilan boradi — `REQUIRED_PG_CONSTRAINTS` ga **hech qachon**.

**Yangi cash enum label: 0.** **`cash` sxemasiga yangi obyekt: 0.**

---

## §11. Dizayn repetitsiyalari — **20 PASS, 0 FAIL**

Haqiqatan yurgizilgan (mahalliy `pgserver` + vaqtinchalik SQLite fayli; production
tegilmagan; repoga hech narsa yozilmagan):

| # | Isbot | Natija |
|---|---|---|
| **P9** | 27 ta taklif qilingan CHECK ifodasi `check_canon.canonical()` dan o'tadi | PASS |
| **P1** | Fresh PG: haqiqiy `app.initdb` sxemasi + yangi jadvallar kompozit FK bilan | PASS |
| **P4** | **Ota-kalit YO'Q bo'lsa kompozit FK'li `CREATE TABLE` → `42830`** | PASS |
| **P3** | Nomlangan UNIQUE **indeks** (cheklov emas) FK ota-kaliti bo'ladi; `indisunique`+`indisvalid` | PASS |
| **P2** | Ikkinchi yurish (PG va SQLite) — idempotent | PASS |
| **P6** | Cross-tenant INSERT rad: PG `23503`, SQLite `FOREIGN KEY constraint failed`; SQLite'da `foreign_keys=ON` | PASS |
| **P7** | Takroriy `leg_no` rad: PG `23505`, SQLite `ux_ps_leg` | PASS |
| **P8** | `ck_ps_creditor_iff` rad: PG `23514`, SQLite CHECK | PASS |
| **P5** | Fresh SQLite: ayni sxema (kompozit FK + CHECK + qismiy indeks) quriladi va qonuniy INSERT o'tadi | PASS |
| **P10** | Indeks nomlari **ikki dialektda ham** ko'rinadi (SQLite'da `sqlite_autoindex_*` emas) | PASS |

**Repetitsiyada topilgan yangi tuzoq** (§6.3 ga kiritilgan): SQLite'da UUID ustunlariga xom
SQL'da **string** bog'lash ota qator bilan mos kelmaydi → Core `insert()` yoki tipli
`bindparam` shart.

---

## §12. SEYF ochilish qoldig'i — dizayn bo'shlig'i (o'zgarmagan)

T0 da hech qanday ochilish yozuvi yozilmaydi; TILL uchun yo'l smena ochilishiga bog'langan,
SEYF esa smena ochmaydi; `POST /safes` summa qabul qilmaydi. **T0 dan keyin yaratilgan
SEYFga jismoniy qoldiqni kiritishning kanonik yo'li arxitekturada YO'Q.**

Taklif: `POST /cash/accounts/{id}/opening` + tashuvchi jadval `cash_account_openings`,
ledger legi `IN·ADJUSTMENT` (`CASH_OP`, `provenance='RECONSTRUCTION'`,
`reconstruction_reason`/`source_ref` = attestatsiya). `ADJUSTMENT` tanlangani menejer+
darvozasini tayyor beradi; miqdor `counted − balance` (hisob qulfi ostida); bir martalik
(`ux_cao_account UNIQUE (cash_account_id)` + `cle_uq_business`).

⚠️ **J qarori:** legacy do'konda SEYF qoldig'i noma'lum bo'lsa migratsiya **BLOCK**.
Bu **Fayzanda SEYF yaratishga ruxsat EMAS.**
⚠️ **R7 kesishmasi:** ochilish legining backfill verifikatsiya darvozasi bilan munosabati
**tekshirilmagan** → Phase 1 testiga kiritilgan (§8.5-5).

---

## §13. Bosqich chegaralari va **dependency matritsasi**

| Ildiz sabab | Phase 1 (SEYF ochilishi) | Phase 3 (split settlement) | Phase 4 (Manager UI) | Phase 6a (kreditor) | Phase 6b (avans) | Phase 7 (qaytarish) |
|---|---|---|---|---|---|---|
| **R1** `leg_no` | — | **BLOK** | — | — | — | — |
| **R2** reversal | — | **BLOK** | — | — | — | — |
| **R3** ota-kalitlar | — | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R4** registr | **BLOK** | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R5** SQLite | **BLOK** | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R6** ochiq qoldiq | — | — | — | — | **BLOK** | **BLOK** |
| **R7** parity | **BLOK** | **BLOK** | — | — | — | **BLOK** |
| **R8** havola/test | — | — | — | — | — | — |

**Bosqich tartibi va oldingi shartlari:**

| Bosqich | Mazmun | Oldingi shart |
|---|---|---|
| **0** ✅ | `pay_supplier` qulf inversiyasi | — (bajarilgan, `4b95e4b`) |
| **2** ✅ | Custody domeni + o'qish yo'li | — (bajarilgan, `af17ada`+`3493d39`) |
| **R-fix** | R1–R8 **kod** tuzatishlari: ota-kalit qadami, registr kuchli tekshiruvi, SQLite qadamlari, parity kutilgan-tomoni | Revision 3 GATE PASS |
| **1** | SEYF ochilish mexanizmi | R4, R5, R7 |
| **3** | `purchase_settlements` + split (`TILL_CASH`, `OWNER_ADVANCE`) | R1, R2, R3, R4, R5, R7 |
| **3s** | `SAFE_CASH` **manbasini yoqish** | **1** (ochilish qoldig'i) + **8** (haqiqiy SEYF) — ochilish qoldig'isiz SEYF balansi yolg'on, shu bois manba Phase 3 da **yozilmaydi** |
| **4** | Manager UX + i18n | 3 **+ meros UX bo'limi qayta bazalangan** |
| **5** | Mobil naqd split (kreditor **yo'q**, F qarori) | 4 **+ meros mobil bo'limi qayta bazalangan** |
| **6a** | `creditors` + hayot davri + ruxsat + audit (pulsiz) | R3, R4, R5 **+ meros kreditor hayot davri/ruxsat bo'limlari qayta bazalangan** |
| **6b** | `OWNER_ADVANCE` + daftar + ochiq qoldiq | 6a, R6 |
| **7** | Qaytarish + allokatsiya + transfer | 6b, R6, R7 |
| **8** | **Fayzanda haqiqiy SEYF** + jismoniy sanoq + ochilish qoldig'i | 1 implement **va** verify; R7 yopilgan |

⚠️ **Meros bo'limlarning kirish sharti** (hujjat doirasi bloki): Revision 2 dan havola bilan kuchda qolgan bo'limlar (kreditor hayot davri/arxivlash, ruxsat matritsasi, Manager UX, Mobil UX, Purchase Return forward-compat, migratsiya/back-compat) tegishli bosqich **boshlanishidan oldin** Revision 4 sifatida qayta bazalanadi — ular hamon Revision 2 satr-raqamli havolalarini ko'taradi. Bu R8 ning ildizi shu bo'limlarda **hali ochiq** degani; R1—R8 doirasida esa yopilgan.

⚠️ **Phase 2 ning operatsion sharti:** SEYF yo'li **kodda ochiq**, lekin **R7 yopilmaguncha
amalda ishlatilmaydi** — birinchi SEYFdan xarid report parity'ni REVIEW ga suradi (§8.2).

---

## §14. Bosqich bo'yicha test rejasi

| Bosqich | Testlar | Soni |
|---|---|---|
| **R-fix** | §4.5 (1–6), §5.4 (1–5), §6.5 (1–7), §8.5 (1–9) | 27 |
| **1** | §12 ochilish: ikki marta rad, `counted<=balance`, attestatsiya majburiy, menejer+ darvozasi, ochilishdan keyin SEYFdan to'lov, backfill darvozasi, J qarori BLOCK | 7 |
| **3** | §2.5 (1–6), §3.5 (1–7), split invariantlari (`total = Σ + unpaid`, ortiqcha to'lov, tahrir darvozasi `409 SETTLEMENT_EDIT_UNSUPPORTED` (§9.4)), `purchases.cash_account_id` qoidasi, **append-only**: `purchase_settlements` ga `UPDATE`/`DELETE` urinishi xizmat qatlamida rad (K qarori — trigger YO'Q, shu bois test **yagona** kafolat), §9.4 uch kod registri + i18n | 20 |
| **4** | To'lov qatorlari UX, `api.ts` dict-detail, i18n (ru/uzc) | 3 |
| **5** | Mobil qatorlar; `permission_matrix.json` **tegilmagan** (F) | 2 |
| **6a** | §4.5 (1–6 kreditor uchun), hayot davri (arxivlash darvozasi, nom band, `unlink`), ruxsat (B/H/I), audit, `/audit` filtri | 18 |
| **6b** | §7.5 (1–8) | 8 |
| **7** | §7.5 (2–6), §8.5 (6), Z-hisobot qadami | 7 |
| **8** | Fayzan: jismoniy sanoq, attestatsiya, ochilishdan keyin to'lov | 3 |

> ⚠️ Testlarni `PYTHONIOENCODING=utf-8` bilan yurgizmang — `test_check_defs_pg` cp1252
> subprocess sababli **yolg'on yiqiladi**.

---

## §15. Taqiqlarga rioya

- Phase 1/3/4/6a–7 **implementatsiya boshlanmagan**; R1–R8 **dizayn darajasida** yopilgan.
- Production/staging **tegilmagan**; repetitsiyalar mahalliy vaqtinchalik bazalarda.
- **Fayzan SEYFi YO'Q** va Phase 1 implement + verify bo'lmaguncha yaratilmaydi.
- main'ga merge **yo'q**, deploy **yo'q**.
- `OWNER_ADVANCE` uchun **soxta naqd oyoq yo'q** (`ck_ps_ledger_iff`).
- Mavjud `Employee`/`Supplier`/`Customer` **noto'g'ri ishlatilmagan**.
- `OWNER_CONTRIBUTION` **qo'shilmagan**.
- Mavjud manfiy naqd himoyasi **chetlab o'tilmagan**; SEYF uchun fail-closed **ataylab**.
- `ERR_TILL_SHIFT_MISMATCH` **global o'chirilmagan** (Phase 2, hisob-turiga xos).
