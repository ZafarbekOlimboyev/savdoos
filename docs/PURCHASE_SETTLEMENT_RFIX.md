# R-FIX — jonli report/reconciliation nuqsonlari (Revision 3 oldingi sharti)

> **Doira:** FAQAT Revision 3 ning R-fix deb belgilagan **mavjud** nuqsonlari. Yangi settlement
> modeli YO'Q: `purchase_settlements`, `creditor_ledger`, `OWNER_ADVANCE`, SEYF ochilish qoldig'i
> va split-xarid so'rov sxemasi **yozilmadi**. Sxema o'zgarishi **YO'Q**.
>
> **Baza:** `717e367` (Revision 3 dizayni) · **Dizayn manbasi:** `docs/PURCHASE_SETTLEMENT_DESIGN.md`
> §8.1–§8.6 (R7), §5.2/§5.4 (R4), §6.3 (R5), §13 (bosqich chegarasi).

---

## 1. Nima buzilgan edi (JONLI, bugungi kodda)

Kutilgan tomon (`db/cash/migration/phase1.py`) **tarixiy backfill** uchun yozilgan, lekin
`services/cash/compare_engine.py` AYNI derivatsiyani **post-T0 live** hodisalar uchun ham
ishlatadi. Runtime esa boshqa shakl yozadi — natijada yolg'on mismatch:

| # | Jonli nuqson | Bugungi natija (o'lchangan) |
|---|---|---|
| 1 | Inkassa: runtime `TRANSFER` JUFTLIGI (0 OUT TILL, 1 IN SEYF); kutilgan tomon bitta `CASH_OP` OUT·CASH_OUT | `{'MISSING_LEDGER': 1, 'EXTRA_LEDGER': 2}` har inkassa uchun |
| 2 | Naqd xarid summasi oshirilsa: leg-0 ASL summada muzlaydi, delta leg-1 bo'ladi; kutilgan tomon BITTA leg (`total + Σqaytarish`) | `{'WRONG_AMOUNT': 1, 'EXTRA_LEDGER': 1, 'WRONG_POSTING_KIND': 1}` |
| 3 | `posting_kind` qattiq `OFF_SHIFT` yozilgan (xarid, xarid-qaytarish, ta'minotchi to'lovi, mijoz qarz to'lovi), runtime esa ochiq smenada `ON_SHIFT` yozadi | `{'WRONG_POSTING_KIND': 1}` **har oddiy naqd xarid uchun** |
| 4 | Custody hisobi kutilgan tomonda filial TILL'i deb TAXMIN qilinadi; `Purchase.cash_account_id` o'qilmaydi | SEYFdan to'langan xarid → `WRONG_ACCOUNT` (aslida TO'G'RI) |
| 5 | Agregat (`shadow_compare`): legacy FILIAL bo'yicha, ledger BITTA hisob bo'yicha | ko'p-TILL filialda legacy **hisoblar soniga ko'paytiriladi** |
| 6 | Agregat: faqat `type == "TILL"` sanaladi | SEYF oyoqlari ledger tomonda YO'Q → doimiy delta |
| 6b | Ledger tomonga SEYF qo'shilgach inkassa juftligi nolga bekor bo'ladi, legacy tomon esa `collection`ni CHIQIM deb ayirardi | tenant agregatida **har inkassa uchun** soxta delta (yangi SEYF qo'shilishining oqibati) |
| 7 | Agregat: naqd hisobi yo'q tenant/filial legacy jadvallarni o'qimasdan «MATCH» | yolg'on toza natija → cutover READY bo'lib ketishi mumkin |
| 8 | `on_cash_collection`/`on_bank_deposit` `cash_enabled` (FAQAT infra) bilan darvozalangan | `LEGACY_ONLY` rejimda ham ledgerga yozadi |
| 9 | `reconcile_events(company_id=None)` | kutilgan tomon HAMMA tenant, haqiqiy tomon BO'SH → har hodisa `MISSING_LEDGER` |
| 10 | `catalog_v2` uch prefiksli kodni (`SNAPSHOT_CONFLICT`, `IMPORT_IN_PROGRESS`, `RESET_TOKEN_STALE`) **birorta registrsiz** va sarlavhasiz qaytaradi | mijoz kodni dasturiy taniy olmaydi (`code_of` `None`); matn esa **to'g'ri** — u qo'lda yozilgan vendor-admin tashxisi, shu bois SAQLANDI |
| 11 | `force_shift` naqd qarz to'lovi jumlasi desktop lug'atida YO'Q | rus/kirill operator xom lotin matn ko'radi |
| 12 | `REQUIRED_INDEXES` FAQAT NOM bo'yicha tekshirilardi | noyob BO'LMAGAN indeks jimgina o'tardi (kafolat yo'q, tayyorlik yashil) |

---

## 2. Eng muhim yangi invariant: KUTILGAN SHAKL IKKI XIL

`phase1.plan_backfill` ikki iste'molchiga xizmat qiladi. R-fix **faqat birini** o'zgartiradi:

| Bo'lak | Iste'molchi | R-fix |
|---|---|---|
| `plan["legs"]` (< T0) | `backfill.py` (**YOZADI**), `runtime_readiness.py`, manifest hash (`--approved-hash`) | **TEGILMAGAN** |
| `plan["legs_after_t0"]` (>= T0) | `compare_engine` (kutilgan tomon) | runtime shakliga moslashtirildi |

Shu bois `_leg` ning yangi maydonlari (`cash_account_id`, `account_type`, `leg_span`) **faqat
qiymat bo'lganda** qo'shiladi (`_live_fields`) — tarixiy leg dict'i bayt-bayt eski holida qoladi.
Simmetrik status filtri ham FAQAT live shoxda.

---

## 3. R-fix ro'yxati — DONE / NOT APPLICABLE / BLOCKED

### 3.1 BLOKLANGAN (sxema o'zgarishi — boss qarori kerak)

| Band | Manba | Holat | Sabab |
|---|---|---|---|
| Ota-kalit qadami: `_ensure_parent_uniques()` + `uq_purchases_company_id`, `uq_employees_company_id` | §4.3, §13 «R-fix» | **BLOCKED** | Bu **DDL** (mavjud jadvallarga additiv noyob indeks). R-fix ko'rsatmasi: «Prefer NO schema changes… STOP before implementing them and report why». Iste'molchisi (kompozit FK) FAQAT Phase 3/6a da tug'iladi, ya'ni hozir yozilsa foydasiz DDL bo'ladi. |
| §4.5 testlari 1–6 | §14 | **BLOCKED** | yangi jadvallarni (`purchase_settlements`, `creditors`) talab qiladi |

### 3.2 BAJARILDI

| Band | Manba | Dalil (test) |
|---|---|---|
| Inkassa = `TRANSFER` juftligi | §8.1-1, §8.3-1, §8.5-1 | `test_A_inkassa_juft_transfer_parity`, `test_A2_…seyf_tipi_tekshiriladi` |
| Manzil TIP darajasida tekshiriladi (id legacy'da YO'Q) | yangi, §8.6 | `test_A2` (TILL→TILL → `WRONG_ACCOUNT`) |
| SEYF agregatda sanaladi | §8.1-2, §8.3-2 | `compare_branch` (hisob tipi filtri olib tashlandi) |
| Ko'p oyoqli xarid = YIG'INDI shartnomasi | §8.1-7, §8.3-5, §8.5-7 | `test_C…`, `test_D_edit_purchase_oshirish_parity`, `test_G1` |
| `posting_kind`/`shift_id` legacy smena oynasidan | yangi (audit) | `test_B_oddiy_naqd_xarid_parity`, `test_D2` |
| Custody hisobi legacy qatordan (`*.cash_account_id`) | yangi (audit) | `_exp_account`; `test_B`, `test_D` |
| Ko'p-TILL legacy ko'paytirilishi | yangi (audit) | `compare_branch` + `scope_warning` |
| Hisobsiz filial/tenant yolg'on «MATCH» | yangi (audit) | `compare_tenant` filiallardan yig'adi |
| Rejim darvozasi (`dual_write_enabled`) | §6.3 (`cash_enabled` bandi) | `test_H1`, `test_H2`, `test_H3` |
| Tenantsiz reconcile fail-loud | yangi (audit) | `test_I_tenantsiz_reconcile_rad_etiladi` |
| Reversal shartnomasi drift qilmaydi | §3.3, §8.5-4 | `test_E_reversal_shartnomasi_drift_qilmaydi` |
| Xato-kodi registri: 3 katalog kodi ro'yxatga + sarlavhaga; 1 tushib qolgan jumla lug'atga | §9.4 | `tests/test_error_code_registry.py` (4 test, butun `app/` daraxti bo'yicha prefiks skani) |
| Majburiy indeks KUCHLI tekshiruvi | §5.2, §5.4-3/4/5 | `tests/cash/test_required_index_strength.py` (6 test + manfiy nazorat) |
| `_purchase_return_legs` status simmetriyasi (live shox) | §8.1-8 ning bir qismi | invariant sifatida; tarixiy reja tegilmagan |

### 3.3 QO'LLANMAYDI (o'z bosqichiga bog'langan — R-fix da bajarilmaydi)

| Band | Manba | Nega |
|---|---|---|
| Split xarid kutilgan tomoni + `_no_charge_exists` filtri | §8.3-3, §8.5-8 | `purchase_settlements` YO'Q. **Bugun filtr TO'G'RI**: charge'li xarid create'da naqd oyoq yozmaydi (`create_purchase` faqat `debt`/`received`), qarz keyin `SUPPLIER_PAYMENT` orqali to'lanadi va uning O'Z kutilgan legi bor. |
| Reversal legi kutilgan oyoqlar ro'yxatida | §8.3-4, §8.5-4 | repoda `post_reversal` ning **birorta jonli chaqiruvchisi yo'q** (grep: faqat `adapters.reversal`). Kutilgan tomon legacy jadvaldan quriladi — reversal uchun legacy tashuvchi Phase 3 da tug'iladi. |
| Ochilish legi ↔ backfill darvozasi | §8.5-5, §12 | Phase 1 |
| Kreditorga qaytarish tashuvchisi | §8.5-6 | Phase 7 |
| `len(RENDERINGS)` / yangi CHECK'lar | §5.4-1/2 | 27 CHECK Phase 3/6a jadvallarida |
| SQLite boot testlari (yangi modellar) + naqd darvozasi + dialekt-mustaqil takror javobi | §6.5-1..7 | yangi modellar/kodlar Phase 3/6a |
| `run.bat` ga `initdb`; §6.6 eskirgan izohlar | §6.3, §6.6 | dizaynning O'ZI bu ikkisini **Phase 3** ish hajmiga bergan |

### 3.4 QAYD ETILDI, BAJARILMADI (R-fix doirasidan tashqari)

| Topilma | Nega tashqarida |
|---|---|
| Legacy soya `CashMovement` faqat `if _sh:` ichida yoziladi → smenasiz naqd to'lovning legacy tomonida HECH QANDAY qator yo'q | Bu **yozuvchi** (biznes yo'li) asimmetriyasi, kutilgan tomon emas. Tuzatish legacy yozuvni o'zgartiradi. |
| Transfer oyoqlari `CashLedgerException` qatori olmaydi | monitoring qamrovi |
| Dry-run manifest: `duplicate_conflicts` doim 0; `MANUAL_PAYOUT_REVIEW` hech qachon chiqmaydi | backfill gate hisoboti |
| `report_cash`: ledger o'qishi yiqilsa naqd xarid chiqimi TUSHIB qoladi | **QISMAN**: ikki holat ajratildi, xato JURNALGA yoziladi va javobda `ledger_error` bayrog'i paydo bo'ldi (qo'shimcha maydon). «503 fail-closed qilinsinmi?» — **boss qarori** (jonli hisobot shartnomasi o'zgaradi) |

---

## 4. Sezgirlik isboti (RED → GREEN)

Yangi test fayli **tuzatishdan OLDINgi** kodga qarshi yurgizildi (to'rt fayl `git checkout` bilan
qaytarildi: `phase1.py`, `compare_engine.py`, `shadow_compare.py`, `retrofit.py`):

```
tuzatishsiz: 11 failed, 4 passed
tuzatish bilan: 15 passed
```

O'tib ketgan 4 ta — ATAYLAB nazorat testlari (bugungi to'g'ri xatti-harakatni qotiradi):
`test_E` (reversal shartnomasi), `test_F` (boshqa `CASH_OP`), `test_G2` (yo'qolgan leg tutiladi),
`test_G3` (manbasiz transfer juftligi HAMON `EXTRA_LEDGER`).

Reconciliation **bo'shatilmadi**: `test_G1` manbasiz qo'shimcha summani `WRONG_AMOUNT` bilan
tutadi, `test_G2` kam legni `MISSING_LEDGER` bilan, `test_G3` begona legni `EXTRA_LEDGER` bilan.
«Ko'p leg bo'lsa mayli» degan umumiy qoida YO'Q — har oyoq manba shartnomasi bo'yicha
atributlanadi (yig'indi aynan teng + har oyoq maydon-tekshiruvidan o'tadi).
