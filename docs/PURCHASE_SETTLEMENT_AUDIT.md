# Xarid to'lov manbalari + SEYF + split settlement — AUDIT/DIZAYN

**Holat: AUDIT (kod yozilmagan).** Worktree `.claude/worktrees/purchase-settlement`,
branch `p6c-purchase-settlement`, `a0ea7ae` dan. Production **faqat o'qildi**.

---

## 1. Hozirgi qabul (receiving) oqimi

| Mijoz | Qabul ekrani | Naqd manba tanlagichi |
|---|---|---|
| **Mobil / PWA** | bor | **bor** — `CustodyBlock` (`apps/mobile/lib/widgets/custody_block.dart`) |
| **Manager (desktop)** | bor (`Products.tsx` `FullReceiving`) | **YO'Q** — faqat «To'landi / Qarzga» |
| **POS** | yo'q | — |

Server tomoni: `POST /receiving/commit` (`receiving.py:106-117`) —
`payment: Literal["cash","credit"]` + **bitta** `cash_account_id`.
Manager xaridi: `POST /purchases` (`schemas/purchase.py:29-37`) — `status: received|debt` +
**bitta** `cash_account_id`.

`paid_amount` **so'rovdan olinmaydi**, hisoblanadi: `0` (qarz) yoki `total` (naqd)
(`receiving.py:245-249`, `purchases.py:330-340`).

---

## 2. SEYF nega chiqmadi — ANIQ SABAB

**Javob: A — Fayzanda SEYF qatori umuman yo'q.** Ro'yxat to'g'ri edi; unda mavjud
bo'lgan hamma narsa bor edi.

Production read-only probe (sysid `7674898282858840119`, read-only isbotlangan `25006`):

```
cash.cash_accounts  ->  {"TILL": 1}      <- bitta TILL, SAFE YO'Q
                        TILL / ACTIVE / branch_id to'ldirilgan
public.shifts       ->  0 qator          <- hech qachon smena ochilmagan
settings['cash']    ->  ledger_native, onboarded_at, cutover_at  (T0 o'tgan)
```

**B, C, D rad etiladi** (dalil bilan):

- **B emas** — API SEYFNI QAYTARADI: `custody_options()` = `list_tills(...) + list_safes(...)`
  (`custody_preview.py:96-97`). Filtrlash yo'q.
- **C emas** — UI FILTRLAMAYDI: mobil `for (final o in info.options) _option(o)` shartsiz
  (`custody_block.dart:314`), hatto SEYF uchun **atayin alohida yorliq va ikonka** bor
  (`custody_block.dart:69`).
- **D qisman** — backend SEYFNI QO'LLAYDI, lekin faqat **smenasiz** holatda
  (`cutover_guard.py:424-435`, `require_custody_account` `expect_type` bermasdan).
  Fayzanda smena 0 ta, ya'ni bu shox ishlagan va ro'yxat `OPERATOR_MUST_CHOOSE` bo'lgan —
  unda faqat 1 ta TILL ko'ringan.

⚠️ **Seyf qatorini yaratishning o'zi maqsadga yetkazmaydi.** Yana ikkita strukturaviy
to'siq bor (quyida): bitta hujjatga **bitta** manba, va **smena ochilsa seyf umuman rad etiladi**.

### 2.1 Yonma-yon turgan ikkinchi to'siq — ochiq smena

Kassirning ochiq smenasi `till_id` ga bog'langan bo'lsa:
- `custody_preview.decide` → `MODE_SERVER_RESOLVED`, `options` **bo'sh**
  (`custody_preview.py:157-159`) — UI tanlov ko'rsatmaydi;
- mijoz o'zi SEYF id yuborsa ham backend **rad etadi**: `ERR_TILL_SHIFT_MISMATCH`
  (`cutover_guard.py:394-401`).

Ya'ni kelajakda smena ochilsa, bugungi qoida bo'yicha seyfdan to'lash **prinsipial imkonsiz**.
Split settlement bu qoidani qayta ta'riflashni talab qiladi.

### 2.2 Uchinchi to'siq — Manager desktopda tanlagich yo'q

`Products.tsx:1053-1059` — faqat «To'landi/Qarzga»; commit tanasida `cash_account_id` yuborilmaydi
(`:855-875`).

---

## 3. Fayzanda SEYF holati

**`FAYZAN SAFE = MISSING`** — `cash.cash_accounts` da faqat 1 ta `TILL`.
Seyf **avtomatik yaratilmaydi** — bu ataylab: `POST /safes` izohi «FAQAT operator ATAYLAB
so'raganda. AVTOMATIK YARATILMAYDI» (`tills.py:214-219`), Manager UI ham shuni takrorlaydi
(`Kassalar.tsx:180-186`).

**Production'da o'zim yaratmadim.** Tavsiya etilgan ko'rsatiladigan nom: «Asosiy seyf».
Yaratish — alohida, aniq ruxsat bilan.

---

## 4. Backend cheklovlari

| # | Cheklov | Dalil |
|---|---|---|
| 1 | Hujjatga **bitta** naqd manba (`cash_account_id`) | `receiving.py:117`, `schemas/purchase.py:29-37` |
| 2 | To'lov **summasi** so'rovda yo'q — `paid_amount` hisoblanadi | `receiving.py:245-249` |
| 3 | «Qismi naqd + qismi qarz» ifodalanmaydi (yo `received`, yo `debt`) | `purchases.py:321` |
| 4 | Qarzga **to'liq** summa yoziladi, qoldiq emas | `receiving.py:415-419` |
| 5 | Qisman to'lov faqat keyingi **ta'minotchi** to'lovi orqali, FIFO taqsimot bilan | `purchases.py:1077-1101` |
| 6 | `SupplierPayment.purchase_id` ustuni bor, lekin **hech qachon yozilmaydi** | model `purchasing.py:84-86` · yagona konstruktor `purchases.py:1043` |
| 7 | Har to'lov — bitta usul + bitta hisob | `purchases.py:994-1002` |
| 8 | Ochiq smenada seyf **rad etiladi** | `cutover_guard.py:394-401` |
| 9 | Pre-T0 legacy yo'lda faqat TILL topiladi | `retrofit.py:345-356`, `:205-225` |
| 10 | Egasining shaxsiy puli uchun **model umuman yo'q** | qidirildi — topilmadi |

---

## 5. Frontend cheklovlari

- Manager qabulida naqd hisob tanlagichi **yo'q**.
- Mobil `CustodyBlock` **bitta** hisob tanlaydi (radio), summa kiritilmaydi.
- Ikkala mijozda ham «bir necha manba» tushunchasi yo'q.
- `packages/shared/src/lib/tills.ts:39` da `type === "TILL"` filtri **bor**, lekin uni faqat
  **smena ochish** ishlatadi (`Shift.tsx:73`) — qabul oqimiga aloqasi yo'q.

---

## 6. Taklif: settlement sxemasi

```
purchases / receivings (mavjud)
      │
      └── purchase_settlements   (YANGI, N ta qator)
            id
            company_id        -> companies.id (FK; yagona jonli FK)
            purchase_id       -> purchases.id
            source            TILL_CASH | SAFE_CASH | OWNER_ADVANCE
            cash_account_id   uuid | NULL   (faqat TILL_CASH/SAFE_CASH uchun)
            amount            Numeric(14,2)  > 0
            ledger_entry_id   uuid | NULL   (cash ledger oyog'i, provenance)
            client_uuid       uuid | NULL   (idempotentlik)
            created_at
```

Invariant (DB CHECK + xizmat):

```
purchase.total = Σ(settlements.amount) + supplier_unpaid_amount
```

- `amount <= 0` → **rad**; ma'nosiz 0 qator **saqlanmaydi**.
- Ortiqcha to'lov → **rad** (aniq biznes qoidasi bo'lmaguncha).
- `source IN ('TILL_CASH','SAFE_CASH')` ⇒ `cash_account_id IS NOT NULL`;
  `source='OWNER_ADVANCE'` ⇒ `cash_account_id IS NULL` (CHECK bilan).

**`SUPPLIER_DEBT` settlement oyog'i EMAS** — u qoldiq (`payable`), mavjud `SupplierLedger` da qoladi.

---

## 7. OWNER_ADVANCE modeli

Egasi o'z cho'ntagidan to'lasa — **kompaniya naqdi qimirlamaydi**. Shuning uchun:

- SEYFGA yoki KASSAGA **soxta CASH IN yozilmaydi**;
- `CashLedgerEntry` **yaratilmaydi**;
- o'rniga majburiyat yoziladi: kompaniya **egasiga** qarzdor.

```
owner_liabilities (YANGI)
  company_id, kind = ADVANCE | REPAYMENT,
  amount, source_settlement_id | NULL, cash_account_id | NULL (repayment uchun),
  created_at, client_uuid
```

Qaytarish: seyfdan 5 000 chiqsa → `CashLedgerEntry(OUT, SAFE)` **va**
`owner_liabilities(REPAYMENT, 5000)`; egasiga qarz 5000 → 0.

⚠️ **`OWNER_CONTRIBUTION` (kapital qo'yilma) bu bosqichda QO'SHILMAYDI.** U boshqa narsa:
kontributsiyada kompaniya egasiga **qarzdor emas**. Buxgalteriya semantikasi auditsiz ikkalasini
bitta `OTHER` ga qo'shish taqiqlanadi.

---

## 8. Cash ledger xaritasi

| Manba | Ledger yozuvi | Hisob | Smena | Kutilayotgan kassa naqdi |
|---|---|---|---|---|
| `TILL_CASH` | `OUT`, summa = leg | aynan tanlangan TILL | **ochiq custody smenasi** | **−summa** |
| `SAFE_CASH` | `OUT`, summa = leg | aynan tanlangan SAFE | `NULL` | **ta'sir yo'q** |
| `OWNER_ADVANCE` | **yozuv yo'q** | — | — | ta'sir yo'q |

`CashPostingService` yagona yozuvchi bo'lib qoladi; parallel «purchase cash balance» tizimi
**yaratilmaydi**.

---

## 9. Ta'minotchi qarzi

To'lanmagan qoldiq = `total − Σ(legs)`. U > 0 bo'lsa: `sup.balance += qoldiq` va
`SupplierLedger(charge, qoldiq, ref_type='receiving'|'purchase', ref_id=...)`.

⚠️ Bugungi `_charged` ikkilik ta'rifi (`purchases.py:881-906`) gibrid hujjatni buzadi: u
«qarz bo'lsa butun delta qarzga, bo'lmasa butun delta kassaga» deydi. Tahrir yo'li
qayta ta'riflanishi shart.

---

## 10. Tranzaksiya chegarasi

Bitta DB tranzaksiyasida: xarid/qabul + qatorlar + **barcha** settlement leglari +
**barcha** ledger oyoqlari + ta'minotchi qarzi. Har qanday qisman xato → **butun ROLLBACK**.
Ta'minotchi qatori avvalgidek `with_for_update()` bilan qulflanadi.

---

## 11. Idempotentlik

- Hujjat darajasida: mavjud `client_uuid` (`ux_receivings_client_uuid`, `ux_purchases_client_uuid`).
- Leg darajasida: `purchase_settlements.client_uuid` noyob (qisman indeks).
- Takroriy so'rov → **bitta** hujjat, **bitta** to'plam leg; `IntegrityError` deterministik
  idempotent javobga aylantiriladi, 500 emas.
- Ayni `client_uuid` + **boshqa** tana → **konflikt**, jim qayta ishlatish emas.

---

## 12. Migratsiya ta'siri

- Yangi jadvallar → repo konvensiyasi: model + `models/__init__` + boot `create_all`
  (Alembic yo'q). Versiyalangan migratsiya **kerak emas**.
- Mavjud hujjatlar **tegilmaydi**: eski `cash_account_id` ustunlari audit sifatida qoladi.
- Yangi indekslar avval `OPTIONAL_UNIQUE`/`PERFORMANCE` sinfida — prod boot ularga bog'lanmasin.

---

## 13. Tegiladigan joylar

`api/v1/receiving.py` · `api/v1/purchases.py` · `schemas/purchase.py` ·
`services/cash/{custody_preview,cutover_guard,retrofit}.py` · `models/purchasing.py` ·
yangi `models/settlement.py` · `packages/shared/src/screens/Products.tsx` ·
`apps/mobile/lib/widgets/custody_block.dart`

---

## 14. Kerakli testlar

8-bo'limdagi matritsa to'liq: SAFE-only · TILL-only · OWNER-only · juftliklar · uchlik ·
uchlik + qarz · bir nechta TILL'dan aniq tanlov · begona filial hisobi → rad · arxiv → rad ·
SAFE + smena → rad · TILL smenasiz → rad · manfiy → rad · 0 leg → saqlanmaydi · ortiqcha → rad ·
idempotentlik (ketma-ket va **parallel**, haqiqiy PG) · ledger xatosida rollback ·
ega qarzini qaytarish · ikki marta qaytarish → rad · qoldiqdan ortiq → rad ·
kompaniyalararo → rad.

---

## 15. Moslik xavflari

1. **Ochiq smena qoidasi** — hozirgi `TILL_SHIFT_MISMATCH` qat'iy. Split uchun u
   «smena kassasidan boshqa TILL bo'lmasin, lekin SEYF/ega puli alohida leg sifatida mumkin»
   deb qayta ta'riflanishi kerak. Bu **mavjud xavfsizlik qoidasini yumshatish**, shuning uchun
   alohida qaror va test talab qiladi.
2. **`_charged` ikkilik ta'rifi** gibrid hujjatda noto'g'ri ishlaydi (9-bo'lim).
3. **Manager qabulida tanlagich yo'q** — UI ishi mobilnikidan katta.
4. **Pre-T0 do'konlar** (T0 o'rnatilmagan) legacy yo'lda qoladi; ularda split yoqilmasin.
5. **Purchase Return** semantikasi auditsiz — qaytarishda pul qaysi manbaga qaytishi
   hal qilinmagan. **Taxmin bilan yozilmaydi.**

---

## 16. Tavsiya etilgan bosqichlar

1. **P1** — `purchase_settlements` + `owner_liabilities` sxemasi, invariant CHECK'lari, sof testlar.
2. **P2** — server: qabul/xarid yo'lida N ta leg qabul qilish, atomik ledger, qarz qoldig'i.
3. **P3** — smena qoidasini qayta ta'riflash (alohida qaror + testlar).
4. **P4** — mobil UI (`CustodyBlock` → ko'p manbali).
5. **P5** — Manager UI (tanlagich noldan).
6. **P6** — ega qarzini qaytarish oqimi.
7. **P7** — Purchase Return semantikasi (alohida audit).

Fayzanda **SEYF yaratish** — P2 dan oldin, alohida ruxsat bilan operator amali.
