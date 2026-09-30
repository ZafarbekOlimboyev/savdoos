# P9 KRITIK TUZATISH 1 — HISOBOT

**Sana:** 2026-09-30 · **Branch:** `p9-critical-repair-1` · **Worktree:** `.claude/worktrees/p9-repair-1`
**Boshlang'ich SHA:** `7381e21ea43f61cc4013d1251d52cc164752e296` · **Yakuniy SHA:** `779cb42a9f7e90cc1278deaa4166c85befed3bd6`

Merge YO'Q · push YO'Q · deploy YO'Q · migratsiya YO'Q.

---

## 1. Boshlang'ich holat

Brief `482b3f38` ni "P9 snapshot" deb atagan edi. Tekshirganda P9 branchi **oldinga
siljigan**: `7381e21` ("Credit a sale's cash to the shift that took it", bugun 03:47),
ya'ni **Phase 3A brief yozilgandan keyin tushgan**. Ish aynan shu so'nggi snapshot ustida
bajarildi.

| Nima | SHA |
|---|---|
| origin/main | `e60c213a` |
| p9-pos-offline-shift-safety (baza) | `7381e21e` |
| qa/binos-independent-security (dalil) | `ac6421e3` |

Izolyatsiya: yangi worktree/branch; begona worktree'larga tegilmagan, hech qanday
jarayon o'ldirilmagan.

## 2. Tuzatishdan oldingi reproduksiya (7381e21 da)

QA sinovlari (`tests/test_qa_p9_repro.py`) import qilindi va **o'zgartirilmasdan**
yurgizildi — to'rttalasi ham QIZIL:

| Sinov | Natija |
|---|---|
| qa01 (P9-01) | QIZIL — ikki push, `#1288`/`#1289`, 2 sotuv, stok 10 → 8 |
| qa02 (P9-02) | QIZIL — `sale.shift_id` == yopiq smena, `expected_cash` o'zgarmagan |
| qa03 (P9-03) | QIZIL — doiradan tashqari |
| qa04 (P9-04) | QIZIL — doiradan tashqari |

## 3. Ildiz sabab — P9-01

`/sync/push` ning **butun dublikat himoyasi** `client_uuid` ga tayanadi:

- `_create_sale_once` kalit bo'lmasa dedup so'rovini **umuman qilmaydi**;
- `ux_sales_company_client_uuid` — **qisman** indeks (`WHERE client_uuid IS NOT NULL`),
  ya'ni NULL kalitlarni qamramaydi.

Demak kalitsiz chek uchun na dastur, na baza to'sig'i bor. Javob yo'qolib qayta
yuborilsa — ikkinchi sotuv va ikkinchi stok chiqimi.

Haqiqiy klient buni yubormaydi: `submitSale` imzosi (`packages/shared/src/lib/sync.ts`)
`client_uuid: string` ni **talab qiladi**, outbox esa `payload` ni localStorage'da
saqlaydi — kalit qayta yuklash va qayta urinishdan omon qoladi (`saleUuidRef` bitta
checkout davomida barqaror). Teshik faqat eski/buzuq/yovuz klient uchun ochiq edi.

## 4. Ildiz sabab — P9-02, 3A kontrakti ichida qayta tahlil

**Asl P9-02 kutilmasi endi vakolatli EMAS** (ega qarori). U pre-3A snapshot
(`482b3f38`) ga qarshi yozilgan; 3A (`7381e21`) esa undan keyin yopilgan smenaga kech
chekni qabul qilishni **ataylab ratifikatsiya qildi** (leg sotuvning o'z smenasiga
`LATE_SYNC` bo'lib tushadi, muzlatilgan yarashtirish tegilmaydi —
`tests/cash/test_sale_shift_ownership.py`).

Shuning uchun savol qayta qo'yildi: **`sold_at` qonuniy LATE_SYNC kontrakti nazarda
tutmagan qanday atribusiyani yarata oladi?**

Replay izlashi (7381e21):

```python
db.query(Shift).filter(
    Shift.cashier_id == emp.id,          # ✓ KASSIR cheklangan
    Shift.opened_at <= now,              # ✓ VAQT oynasi cheklangan
    (Shift.closed_at.is_(None)) | (Shift.closed_at >= now))
```

Chekning filiali esa bu yerdan emas — `actor_branch(emp, db)` dan, ya'ni kassirning
**joriy biriktirilgan** filialidan keladi. **Filial hech qayerda solishtirilmaydi.**

| O'lcham | Holat |
|---|---|
| Boshqa **kassir**ning smenasi | ✅ Mumkin emas (`cashier_id` filtri) |
| Boshqa **tenant** | ✅ Mumkin emas (kompaniya doirasi) |
| Boshqa **FILIAL**ning smenasi | ❌ **MUMKIN** — tor nuqson |

**Natija:** kassir A filialida smena ochib-yopgach B ga o'tkazilsa (yoki ikkala
filialga biriktirilgan bo'lsa), B da yuborilgan chek `sold_at` orqali A ning smenasiga
bog'lanadi:

```
sale.branch_id = B   →  stok B dan chiqadi
sale.shift_id  = A ning smenasi ;  sale.till_id = A ning kassasi
```

Bitta chek ikki filialga bo'linadi: tovar B dan, pul A ning kassa hisobiga. Z-hisobot,
custody va filial P&L bir vaqtda buziladi. 3A ning "leg sotuvning o'z smenasiga
tushsin" niyati bu holatni nazarda tutmagan — uning barcha sinovlari **bitta filialda**.

**(A) qonuniy kech replay** — o'z filialidagi o'z smenasiga → o'zgarishsiz qabul.
**(B) vaqt belgisi manipulyatsiyasi** — endi filial chegarasidan o'ta olmaydi.

## 5. O'zgargan fayllar

Ishlab chiqarish kodi — **3 ta mazmunli qator** (qolgani izoh):

| Fayl | O'zgarish |
|---|---|
| `apps/server/app/api/v1/sync.py` | kalit majburiy (yo'q / nol-UUID → doimiy rad) |
| `apps/server/app/core/error_codes.py` | `SYNC_IDEMPOTENCY_KEY_REQUIRED` |
| `apps/server/app/services/sales.py` | replay izlashiga `Shift.branch_id == branch.id` |

Sinovlar: `tests/test_p9_repair1_contract.py` (YANGI, 13 ta), `tests/test_qa_p9_repro.py`
(QA dalili, **tanalari o'zgarmagan**, uchtasiga maqom markeri qo'yilgan).

**Phase 3A fayllari — TEGILMAGAN.** Strict variantda qilingan tahrirlar
(`test_sale_shift_ownership.py`, `test_offline_shift_policy.py`,
`test_offline_shift_policy_pg.py`) `git checkout` bilan **to'liq tiklandi**.

## 6. Yangi idempotentlik kontrakti

- Har offline chek **bardoshli** `client_uuid` bilan kelishi shart.
- Yo'q / nol-UUID (`00000000-…`) / buzuq → `ok:false`, **`retry:false`** (doimiy),
  `code: SYNC_IDEMPOTENCY_KEY_REQUIRED`. Chek yozilmaydi, stok tegilmaydi.
- Server **yangi kalit yaratmaydi** — aks holda har urinish "boshqa chek" bo'lardi.
- Nol-UUID ayrim ahamiyatga ega: qabul qilinsa birinchi sotuvdan keyin **hamma** chek
  "takror" bo'lib o'sha sotuvni qaytarardi (butun smena savdosi jimgina yutilardi).
- Kalit doirasi — **kompaniya**: begona tenant kaliti bu do'kon savdosini bosmaydi.
- **Onlayn `/sales` semantikasi o'zgarmadi** (kalit u yerda ixtiyoriy).

## 7. Kech sinxronlash atribusiyasi kontrakti

- 3A saqlanadi: yopilgan **o'z** smenasiga kech chek qabul qilinadi, leg o'z smenasiga
  tushadi, muzlatilgan `expected_cash`/`counted_cash`/`difference`/`closed_at`
  **tegilmaydi**, 3A qulf/egalik kafolatlari butun.
- Qo'shilgan yagona shart: **smena chekning filialiga tegishli bo'lsin.**
- Mos smena topilmasa **yangi rad kodi kiritilmaydi** — `shift` `None` bo'lib qoladi va
  mavjud, sinalgan yo'llar hal qiladi: `force_shift` yoqiq bo'lsa `OPEN_SHIFT_REQUIRED`,
  post-T0 da custody gardlari TILL ni aniq talab qiladi.

## 8. Tranzaksiya kafolatlari

- P9-01 rad **yozuvdan oldin**, `create_sale` umuman chaqirilmaydi → qisman holat yo'q.
- P9-02 filtri — `SELECT` shartining o'zi; qo'shimcha qulf, commit yoki rollback yo'q.
  3A ning `FOR NO KEY UPDATE` + `populate_existing()` qulf shartnomasi va qulf tartibi
  (`public.shifts → inventory → customers → cash.cash_accounts → cash.shifts`)
  o'zgarmagan.
- Keng `db.rollback()` **qo'shilmadi**; `/sync/push` ning mavjud per-record
  rollback/triaj mantig'iga tegilmadi.
- Sinov bilan tasdiqlandi: rad etilgan chekda `SaleItem`, `SalePayment`, `StockMovement`
  qatorlari **nol** (`test_c12`).

## 9. Sinovlar

**SQLite (251 o'tdi, 3 xfail, 0 yiqilish)** — `test_offline_shift_policy`,
`test_p9_repair1_contract`, `test_qa_p9_repro`, `test_flows`, `test_lot_fefo_sale`,
`test_lot_safe_409`, `test_lot_enable_race`, `test_lot_return`, `test_lot_phase4a`,
`test_mobile_parity`. Qo'shimcha: `test_sales_read_permissions`,
`test_cash_custody_correction`, `test_hardening` — **94 o'tdi**.

**Yangi kontrakt sinovlari (13/13):** kalitsiz · nol-UUID · bo'sh/buzuq · aynan payload
takrori · faqat `sold_at` o'zgarishi · tenantlararo to'qnashuv · onlayn semantika ·
indeks majburiy ro'yxatda · **3A ochiq smena** · **3A yopilgan o'z smenasi** ·
filiallararo atribusiya · qisman holat yo'qligi.

**QA repro:** qa01 **QIZIL → YASHIL**. qa02/qa03/qa04 — `xfail(strict=True)`,
**tanalari o'zgarmagan**: qa02 kutilmasi ega qarori bilan bekor qilindi, qa03/qa04
haqiqiy ochiq nuqsonlar.

## 10. PostgreSQL dalili

Resurs holati tekshirildi: faol begona pytest **yo'q** (python: 0), 322 `postgres`
jarayoni — o'lik yurishlardan qolgan yetim klasterlar (ularga **tegilmadi**), RAM 3.1 GB.

- **`tests/cash/test_sale_shift_ownership.py` — 16/16 o'tdi (haqiqiy PG).**
  Phase 3A egalik va qulf kafolatlari butunligicha tasdiqlandi.
- `tests/cash/test_sale_cash_posting.py` va `test_offline_shift_policy_pg.py` — 15 o'tdi,
  **1 yiqildi**: `test_post_t0_ochiq_smena_replay_QABUL_va_ledgerga_YOZILADI`.

**Bu yiqilish bu ishga tegishli EMAS** — atribusiya uch nuqtada tekshirildi:

| Snapshot | Natija |
|---|---|
| `p9-critical-repair-1` (mening) | `assert 0 > 0` |
| toza `7381e21` (3A) | `assert 0 > 0` |
| toza `482b3f38` (3A dan oldin) | `assert 0 > 0` |

Ya'ni **oldindan mavjud**: post-T0 ochiq smenali naqd replay ledger legi yozmaydi.
Tekshirildi va rad etildi: filial nomuvofiqligi sabab emas —
`shift.branch_id == actor_branch == d["bid"]` (to'g'ridan-to'g'ri o'lchandi).
Sotuv yoziladi, leg yozilmaydi. Bu **alohida ochiq savol** (ehtimol fixture legacy
`Shift` qatorini `cash.shifts` juftisiz yaratgani bilan bog'liq) va bu bosqich
doirasiga kirmaydi.

## 11. Ochiq qolgan P9 qarzlari

| ID | Mohiyat | Maqom |
|---|---|---|
| **P9-03** | Boshqa kassirning `client_uuid`i bilan replay → 200 OK, yangi chek **yutiladi** | OCHIQ, sinov qizil (xfail) |
| **P9-04** | `_transfer_once` dedup'i tenant-skopsiz va material-matchsiz | OCHIQ, sinov qizil (xfail) |
| **P9-05** | Onlayn savdo vs `close_shift` poygasi (3A qulfi bilan **toraygan**, yopilmagan) | OCHIQ |
| p9[23] | Onlayn smena izlashi ham filialni solishtirmaydi (`else` shoxi) — ayni sinf, `sold_at` bilan boshqarilmaydi | OCHIQ, bir qatorlik davomi |
| p9[10] | `LATE_SYNC_UNACK` istisnosini o'qiydigan API yo'q | OCHIQ |
| — | `test_post_t0_ochiq_smena_replay…` oldindan qizil (yuqorida) | OCHIQ |

## 12. Kuzatuv: dead-letter matni tarjimasiz

`deadLetter()` server matnini **xom** saqlaydi, POSKassa esa uni `{f.error}` bilan
tarjimasiz chiqaradi. Bu **barcha** kodlarga tegishli (mening o'zgarishimdan oldin ham) —
Fayzan UI kirill bo'lgani uchun kassir lotin-o'zbekcha texnik matn ko'radi.
`FailedSale.code` saqlanadi, demak kod → tarjima bir joyda yechiladi. Bu bosqich
doirasidan tashqarida, shu bois o'qilmaydigan lug'at yozuvi qo'shilmadi.

## 13. Yakuniy hukm

| Element | Hukm |
|---|---|
| **P9-01** | ✅ **FIXED** — reproduksiya yashil, 13 kontrakt sinovi, 251+94 regressiya toza |
| **P9-02** | ✅ **NARROWLY FIXED** — filiallararo atribusiya yopildi; 3A kontrakti **butun** (PG 16/16) |

**Qoldiq xavf (ega qarori talab qilinadi, HOLD emas — qaror allaqachon berilgan):**
3A kontrakti bo'yicha `kassa.sell` li token o'z filialidagi o'z yopilgan smenasiga
`sold_at` bilan chek qo'sha oladi (`_clamp_sold_at`: 60 kungacha orqaga). Bu ataylab
qabul qilingan xulq; yagona qoldiq — anomaliya (`LATE_SYNC_UNACK`) ni **o'qiydigan API
yo'qligi** (p9[10]), ya'ni operator uni amalda ko'rmaydi. Shu API paydo bo'lgach
kontrakt to'liq ishlaydi.
