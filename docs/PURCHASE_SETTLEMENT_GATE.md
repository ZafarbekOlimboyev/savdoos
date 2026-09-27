# FINAL DESIGN GATE — Xarid to'lovi / SEYF / split settlement

> **Tavsiya: NO-GO (Phase 0–4).** 7 mustaqil gate tekshiruvining **7 tasi ham FAIL**;
> **28 bloklovchi** nuqson ochiq. Ularning oltitasini **o'zim repoda tasdiqladim**.
> Implementatsiya boshlanmagan; kod yozilmagan; deploy yo'q; Fayzan SEYFi YO'Q;
> production tegilmagan.

| Maydon | Qiymat |
|---|---|
| **Ko'rikdan o'tgan commit SHA** | **`2f0c163`** («Write the nine decisions into the design, and correct what they exposed»); ish daraxti toza |
| **O'zgargan hujjatlar** | `docs/PURCHASE_SETTLEMENT_DESIGN.md` (2-tahrir, 9 qaror kiritilgan), `docs/PURCHASE_SETTLEMENT_REVIEW_TRACE.md` (yangi, 67 topilma traceability), `docs/PURCHASE_SETTLEMENT_GATE.md` (shu hisobot) |
| **Hal qilinmagan BLOKLOVCHI** | **28** |
| **Hal qilinmagan JIDDIY** | 41 |
| **Hal qilinmagan KICHIK** | 31 |
| **Kechiktirilgan (deferred)** | 1 — 1-tur `claim-accuracy#13` (havola siljishlari qismiy tuzatilgan) |
| **Ataylab doiradan tashqari** | 0 |
| **Ziddiyat skani** | **FAIL** — 15 topilma (8 bloklovchi) |
| **DDL moslik (fresh + mavjud)** | **FAIL** — 12 topilma (3 bloklovchi) |
| **SQLite / `run.bat`** | **FAIL** — 9 topilma (3 bloklovchi); asosiy PREMISSA xato edi |
| **Readiness / `check_canon`** | **FAIL** — 11 topilma (2 bloklovchi) |
| **Report parity dizayni** | **FAIL** — 12 topilma (4 bloklovchi) |
| **Determinizm / konkurrentlik** | **FAIL** — 15 topilma (3 bloklovchi) |
| **Havolalar / tuzilma** | **FAIL** — 26 topilma (5 bloklovchi) |
| **GO / NO-GO** | **NO-GO** |

---

## 1. Nega NO-GO

1-tur ko'rik 67 nuqson topdi va 2-tahrir ularning **66 tasini** hal qildi. Lekin 2-tur gate
tekshiruvi **yangi va qolgan 100 nuqson** topdi, shundan **28 tasi bloklovchi**. Ya'ni
`PURCHASE_SETTLEMENT_REVIEW_TRACE.md` dagi **«hal qilinmagan bloklovchi: 0»** da'vosi
**1-tur topilmalari uchun** to'g'ri, lekin **dizaynning implementatsiyaga tayyorligi uchun
YO'Q** — 2-tahrir tuzatishlari yangi ziddiyatlar kiritdi.

Eng og'ir ikkitasi mening o'z xatolarim:

1. **2-tahrir 1-tahrirning TO'G'RI bayonotini «nuqson» deb belgilab, o'rniga bajarilmas
   shartnoma yozdi.** 1-tahrir «reversal legi yangi `source_id` oladi» degan edi — bu
   **to'g'ri**: `ReversalCommand.source_id` izohi so'zma-so'z *«yangi manba identifikatori
   (original'niki EMAS)»* (`commands.py:63`), `leg_index` maydoni umuman **yo'q**
   (`commands.py:60-68`), `post_reversal` esa `category=ADJUSTMENT` ni **qattiq kodlaydi**
   (`posting.py:156`). Men uni teskarisiga o'zgartirdim.
2. **SQLite FK premissasi xato edi.** §16.5 «FK majburlanmaydi» deb yozgan
   (xotiradagi eskirgan faktga tayanib), lekin `db/session.py:61-71`
   `PRAGMA foreign_keys=ON` ni **yoqadi** va izoh uni o'chirishni **taqiqlaydi**. Demak
   kompozit FK'lar mahalliy SQLite'da ham ota-kalit talab qiladi — va
   `fk_ps_purchase_same_company` uchun bunday kalit **yo'q**, ya'ni `run.bat` buzilardi.

---

## 2. 28 bloklovchi — 8 ta ildiz sabab

| # | Ildiz sabab | Bloklovchilar | Mohiyati | Nima o'zgarishi kerak |
|---|---|---|---|---|
| **R1** | `leg_no` allokatori | B01, B08, B21, B22 | Ikki raqobatdosh allokator bitta noyoblik fazosida: §2.1 «kanonik indeks (0 dan)» va §2.3 «max+1». `ux_ps_leg` da `revision` YO'Q, shu bois almashtiruvchi revizya rev0 ning `leg_no` larini qayta so'raydi. Xato `cle_uq_business` ga ham o'tadi | **Bitta** allokator: yo `ux_ps_leg (purchase_id, revision, leg_no)`, yo butun hujjat doirasida monoton `leg_no`. Kanonik tartib `kind` ni ham qamrasin |
| **R2** | Reversal ledger shartnomasi | B02 | `ReversalCommand` da `leg_index` yo'q, `source_id` YANGI bo'lishi shart, `category` qattiq kodlangan; §8 esa to'g'ridan-to'g'ri INSERT ni taqiqlaydi | Yo `ReversalCommand` ni kengaytirish (Bosqich 3 ish hajmiga kiritib), yo 1-tahrirning «yangi `source_id`» yechimiga qaytish |
| **R3** | Kompozit FK uchun ota-kalit | B03, B09, B10, B13, B16 | `purchases` da `UNIQUE (company_id, id)` YO'Q → `fk_ps_purchase_same_company` PG'da 42830 bilan yiqiladi, SQLite'da har INSERT xato beradi. Boot tartibi ham teskari: `_create_all` `_ensure_*` dan OLDIN | `purchases` uchun ham additiv UNIQUE; `_create_all` dan **OLDIN** ishlaydigan `_ensure_parent_uniques()` qadami |
| **R4** | UNIQUE noto'g'ri registrda | B04, B11, B14, B15 | `REQUIRED_PG_CONSTRAINTS` faqat CHECK uchun (`contype='c'`, `required_schema.py:860,891`) va `test_check_canon.py:36` uni `CHECK_DEFINITIONS` bilan **teng** bo'lishga majburlaydi → tayyorlik abadiy QIZIL, ikki test yiqiladi | UNIQUE ni `REQUIRED_INDEXES` yo'liga (`contype IN ('u','p')` — `required_schema.py:369`) o'tkazish |
| **R5** | SQLite FK premissasi | B12 (+ B13, B14 ga ta'siri) | SQLite FK'ni **majburlaydi** → butun §16.5 tahlili yolg'on poydevorda | §16.5 ni qayta yozish; har kompozit FK uchun ota-kalitni ikki dialektda ham ta'minlash |
| **R6** | `ADJUST_UP` ochiq-qoldiq qatorisiz | B05, B06, B23 | Transfer maqsadidagi `ADJUST_UP` ga mos `owner_advance_open` qatori **tuzilishan imkonsiz** (PK = `settlement_id`, `ck_oao_kind_payment`), lekin §5.2 har `ADJUST_DOWN`/`REPAYMENT` uchun `Σ(allocations) == amount` talab qiladi; `creditor_advance_allocations` da `creditor_id` yo'q, shu bois §3.9 valyuta FK'si ham yaratilmaydi | Allokatsiya invariantini «avans bilan qoplangan qism» bilan cheklash; `open_total` ni normativ ta'riflash; allokatsiya jadvaliga `creditor_id` |
| **R7** | Parity yuzasi to'liq emas | B17, B18, B19, B20 | `shadow_compare` (aggregate) yuzasi **umuman** hisobga olinmagan — har SEYF to'lovi doimiy delta beradi; `provenance='RECONSTRUCTION'` legi **backfill verifikatsiya darvozasini** buzadi; `compare_leg` `posting_kind`/`shift_id`/`branch_id` ni solishtiradi, settlementda ular **yo'q**; mismatch inventari yarim (`WRONG_ACCOUNT`, `WRONG_POSTING_KIND` yo'q) | §5.1 ni `shadow_compare` ga yoyish; ochilish legi provenance qarorini qayta ko'rish; sxemaga `branch_id` (+ naqd oyoq uchun `shift_id`/`posting_kind`) qo'shish |
| **R8** | Qoldiq ziddiyatlar | B07, B25, B26, B27, B28 | `creditor_name_keys` §3.5 da o'chirilgan, lekin §3.6 va §18 Bosqich 6a da **hamon bor**; §18.1 o'z ichida zid (FK 3-bosqichda*mi* yoki 6a da*mi*); **29 test (H, I, J guruhlari) birorta bosqichga biriktirilmagan**; H qarorining e'lon qilingan natijasi mexanik imkonsiz — ega **hech qachon** PIN bilan kira olmaydi (`api/v1/auth.py:71-72`) | Matn tozalash + §18 ga test-bosqich xaritasini to'ldirish + H bandini kuchliroq va to'g'ri shaklga keltirish |

**O'zim tasdiqlagan bloklovchilar (6):** B01 (o'z hujjatimda), B02 (`commands.py:60-68`,
`posting.py:156`), B03 (`purchasing.py:26`), B04 (`required_schema.py:860,891` +
`test_check_canon.py:36`), B12 (`db/session.py:61-71`), B28 (`api/v1/auth.py:71-72`).

---

## 3. Phase 0–4 implementatsiya tartibi (o'zgarmagan, lekin BLOKLANGAN)

| Bosqich | Mazmun | Holat |
|---|---|---|
| **0** | `pay_supplier` qulf inversiyasini tuzatish + `40P01` o'rami | **R1–R8 dan mustaqil** — yagona bosqich, dizayni toza |
| **1** | SEYF ochilish qoldig'i mexanizmi (§12.2) | **BLOKLANGAN: R7** (provenance ↔ backfill darvozasi) |
| **2** | Custody domeni + 8-chi (o'qish) chaqiruv | **R1–R8 dan mustaqil** |
| **3** | `purchase_settlements` + naqd manbalar + `revision` | **BLOKLANGAN: R1, R2, R3, R4, R5, R7** |
| **4** | Manager UX + `api.ts` dict-detail + i18n | 3 ga bog'liq |

Ya'ni **Bosqich 0 va 2 ni hoziroq boshlash mumkin**; **1, 3, 4 bloklangan**.

---

## 4. Bosqich bo'yicha rejalashtirilgan testlar

⚠️ **B27:** §17 dagi 100 testning **29 tasi (H 73-77, I 78-86, J 87-100) birorta bosqichga
biriktirilmagan** — bu o'zi bloklovchi. Quyida tuzatilgan xarita (hujjatga kiritilishi
kerak):

| Bosqich | Test guruhlari | Soni |
|---|---|---|
| **0** | B-17 (`pay_supplier` bilan parallel settlement) | 1 |
| **1** | E-42..47 | 6 |
| **2** | D-33..41 (ayniqsa **D-34** global-yumshatish qo'riqchisi va **D-41** preview↔yozuvchi parity) | 9 |
| **3** | A-1..9, B-10..17, C-18..32, I-78..86 | 41 |
| **4** | I-85 (i18n/dict-detail), J-96 (mobil shartnoma tegilmagan) | 2 |
| **5** | J-96 (mobil no-op tasdiqi) | 1 |
| **6a** | F-48..62, H-73..77, J-87..92, J-94, J-95, J-97 | 27 |
| **6b** | F-guruh qoldig'i + C-26, C-29 | — |
| **7** | G-63..72, J-100 | 11 |
| **Migratsiya darvozasi** | **J-98** (J qarori: legacy SEYF noma'lum → BLOCK) — **yangi bosqich kerak** | 1 |
| **K tasdiqi** | J-99 (trigger YO'Q, xizmat qatlami to'sadi) | 1 |

---

## 5. Kechiktirilgan topilmalar

| Topilma | Holat | Sabab |
|---|---|---|
| 1-tur `claim-accuracy#13` (havola siljishlari) | **QISMAN** | 6 tasi tekshirib tuzatildi; qolganlari navigatsiya havolalari (invariant emas) va implementatsiya paytida ochilganda tasdiqlanadi |
| 2-tur 41 JIDDIY + 31 KICHIK | **OCHIQ** | 28 bloklovchi tuzatilgandan keyin qayta triaj qilinadi — ba'zilari bloklovchi tuzatishlari bilan birga yopiladi |

---

## 6. GO shartlari

Phase 0–4 uchun **GO** berilishi uchun quyidagilar bajarilishi kerak:

1. **R1** — bitta `leg_no` allokatori tanlanib, `ux_ps_leg` va `cle_uq_business` bilan
   izchil qilinsin; A-guruhga revizya-2 sikli testi qo'shilsin.
2. **R2** — reversal ledger yo'li mavjud `CashPostingService` shartnomasiga moslanshin
   (yoki shartnoma o'zgarishi Bosqich 3 hajmiga kiritilsin).
3. **R3 + R4 + R5** — ota-kalitlar, boot qadam tartibi va registr tanlovi tuzatilsin;
   SQLite premissasi qayta yozilsin.
4. **R7** — parity yuzasi (`shadow_compare` + backfill verifikatsiyasi) qamralsin;
   ochilish legi provenance qarori qayta ko'rilsin (bu **Bosqich 1** ni bloklaydi).
5. **R8** — matn ziddiyatlari tozalanib, test↔bosqich xaritasi to'ldirilsin, H bandi
   to'g'rilansin.
6. **R6** — 6b/7 uchun (Phase 0–4 ni bloklamaydi, lekin 6b dan oldin hal qilinsin).

**Bosqich 0 va 2** yuqoridagilarning hech biriga bog'liq emas va alohida GO olishi mumkin.

---

## 7. Taqiqlarga rioya

- Kod **yozilmagan**, migratsiya **yozilmagan**, deploy **qilinmagan**.
- **Fayzan SEYFi YARATILMAGAN**; production **tegilmagan** (faqat avvalgi read-only probe).
- Implementatsiya **boshlanmagan** — brif talab qilganidek avval shu gate hisoboti.
