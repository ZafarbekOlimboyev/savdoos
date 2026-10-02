# FINAL REVISION 3 DESIGN GATE

> Oldingi gate reporti (Revision 2 uchun **NO-GO**) `25d3803` commitida saqlangan.
> Bu hujjat Revision 3 uchun.

## 1. Aniq dizayn SHA

| | |
|---|---|
| Revision 3 commit | **`717e3675ed17964b9b0a8f6faaf01a1a2612399a`** |
| Baza (repo holati) | `3493d39` — Phase 0 (`4b95e4b`) + Phase 2 (`af17ada`, `3493d39`) |
| Shox | `p6c-purchase-settlement` (main merge **YO'Q**) |
| Kod o'zgarishi | **0 fayl** — `git diff --stat`: faqat `docs/` |

## 2. O'zgargan hujjatlar

| Fayl | Δ |
|---|---|
| `docs/PURCHASE_SETTLEMENT_DESIGN.md` | to'liq Revision 3 (−1641 / +1034 satr; 47 bo'lim) |
| `docs/PURCHASE_SETTLEMENT_REVIEW_TRACE.md` | 167 topilma uchun qayta yozildi |
| `docs/PURCHASE_SETTLEMENT_GATE.md` | shu hujjat |

## 3. R1–R8 hal qilish jadvali

Har bir ildiz sabab uchun boss talab qilgan **12 jihat** yozilgan (hozirgi dalil ·
buzilgan shartnoma · tuzatilgan kanonik shartnoma · sxema · xizmat · migratsiya/boot ·
SQLite · readiness/check_canon · reconciliation/report · concurrency/idempotentlik ·
aniq testlar · rollback).

| # | Ildiz | Tuzatilgan kanonik shartnoma (bir satrda) | Bo'lim |
|---|---|---|---|
| **R1** | `leg_no` allokatori | **Bitta** qoida: hujjat doirasida monoton `max(leg_no)+1`, **hujjat qulfi ostida**; `revision` ustuni YO'Q; party-noyoblik indekslari YO'Q; bir tanada takror party → `400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` | §2.1–2.5 |
| **R2** | REVERSAL shartnomasi | **Koddan o'qilgan**: `source_id` = reversal qatorining **o'z** id'si, `leg_index=0`, `category=ADJUSTMENT`; `cle_uq_reverses` global (tenant ustuni yo'q) → `ALREADY_REVERSED` | §3.1–3.5 |
| **R3** | Kompozit FK ota-kalitlari | Nomlangan, **qisman emas** UNIQUE **indeks** ota-kalit sifatida; yangi `_ensure_parent_uniques()` qadami `_create_all` dan **OLDIN** | §4.1–4.5 |
| **R4** | Noyoblik registri | UNIQUE → `REQUIRED_INDEXES` + **kuchli** tekshiruv (`indisunique`+`indisvalid`); `REQUIRED_PG_CONSTRAINTS` ga **hech qachon** (u `contype='c'`) | §5.1–5.4 |
| **R5** | SQLite | Ikki dialekt **birinchi darajali**; `foreign_keys=ON` kanonik fakt; `cash_enabled()` non-PG'da `False` → naqd settlement **yozuvchisi darvozalanadi**, CHECK bo'shatilmaydi; UUID bind tuzog'i | §6.1–6.6 |
| **R6** | Ochiq majburiyat / `ADJUST_UP` | Ikki darajali kafolat: **haqiqat** = `Σ(creditor_ledger)` ishorali; qator-lokal `ck_oao_sum_le_amt`; `ADJUST_UP` **ochiq qator yaratmaydi**; FIFO dialekt-neytral; ortiqcha qaytarish `409 CREDITOR_OVER_REPAYMENT`; **soxta naqd leg YO'Q** | §7.1–7.5 |
| **R7** | Report parity | Parity **besh** shaklni o'rganadi; **ikkitasi bugun jonli** (inkassa TRANSFER juftligi, summa oshirilgan naqd xaridning leg-1'i); split uchun `_no_charge_exists()` filtri ham o'zgaradi | §8.1–8.5 |
| **R8** | Havola/test/ziddiyat | Havola siyosati: **simvol nomi**, satr raqami faqat `cash_ddl_v1.sql`; hujjat doirasi bloki (Revision 2 dan meros + ziddiyat qoidasi); §9.4 xato-kodi registri | Havola siyosati, §9.1–9.4 |

## 4. Hal qilinmagan BLOKLOVCHI

**0.** 42 BLOKLOVCHI (1-tur 14 + gate turi 28) — hammasi `RESOLVED` yoki `SUPERSEDED`
(yangi kanonik shartnoma + test shartnomasi bilan). `DEFERRED` BLOKLOVCHI **yo'q**.

## 5. Hal qilinmagan JIDDIY

**0.** `DEFERRED` JIDDIY — **1**: gate #84 (uch yozuvchi uchun preview yo'li yo'q) →
F qarori bo'yicha Phase 1 da UI yo'q, Phase 4 **kirish sharti** (§13).
Qolgan `DEFERRED` ikkitasi KICHIK: #26 (o'qish yo'li tezlik indekslari → Phase 6b),
#99 (`creditor_referenced()` ro'yxati → Phase 6a meros bo'limi).

## 6. Ziddiyat skani

| Skan | Natija |
|---|---|
| Bir-biriga zid bayonot | **0** |
| Shu skanda **yangi** topilgan va TUZATILGAN | **4**: §8.1-7 (ko'p oyoqli PURCHASE jonli), §8.1-8 (`_no_charge_exists` filtri), §9.4 (xato kodlari registrsiz edi), §6.3 (`cash_enabled()` darvozasi) |
| `revision` ustuni qoldig'i | **0** (faqat §9.1/doira blokida «BEKOR» deb) |
| `creditor_name_keys` **talab** sifatida | **0** |
| «kod o'zgartirilmagan» da'vosi | **0** (§1 bajarilgan ishni SHA bilan sanaydi) |
| CHECK sanog'i ↔ nomlar | **27 = 27** (`ck_ps_*` 11, `ck_creditor_*` 5, `ck_oao_*` 4, `ck_cl_*` 3, `ck_cao_*` 2, `ck_cr_*` 1, `ck_caa_*` 1) |
| UNIQUE indeks sanog'i ↔ nomlar | **14 = 14** (ota-kalit 5 + biznes/idempotentlik 9) |

## 7. Buzilgan havola skani

| Skan | Natija |
|---|---|
| Uzilgan `§N` havolasi | **0** (skript bilan: 47 bo'lim, hamma havola mos) |
| Satr-raqamli kod havolasi | **faqat `cash_ddl_v1.sql`** — 5 ta (`:194`, `:204`, `:227-228`, `:232`, `:238`) |
| Boshqa fayl uchun `fayl:satr` | **0** |
| Kirill matn (hujjat lotincha) | **0** |

## 8. Fresh PG mosligi

Repetitsiya (jonli PG 18, `pgserver`): **P1** ilova sxemasi quriladi; **P4** ota-kalitsiz
kompozit FK **`42830`** bilan RAD etiladi (boot tartibi majburiy ekanini isbotlaydi);
**P3** ikki nomlangan UNIQUE indeks `indisunique`+`indisvalid`; **P1** bolalar jadvallari
kompozit FK bilan quriladi; **P8** `ck_ps_creditor_iff` `23514` bilan rad etadi;
**P7** `ux_ps_leg` `23505` bilan rad etadi; **P6** cross-tenant FK `23503`.

## 9. Upgrade PG mosligi

**P2**: ikkinchi yurish — o'zgarishsiz (idempotent). `_ensure_parent_uniques()`
`to_regclass` bilan qulfsiz prechek qiladi; jadval yo'q bo'lsa no-op; indeks qurilmasa
`_create_all` o'zi `42830` bilan to'xtaydi (fail-closed, xabari aniq). Mavjud bazada
`ACCESS EXCLUSIVE` emas, `CREATE UNIQUE INDEX` **SHARE** oladi (§5.3 da tuzatilgan).

## 10. SQLite mosligi

**P5** fresh boot + bolalar jadvallari (kompozit FK + CHECK + qismiy indeks);
**P2** ikkinchi yurish no-op; **P10** 73 nomlangan indeks `sqlite_master` da nomi bilan;
**P6** `PRAGMA foreign_keys=ON` va cross-tenant FK **rad etiladi**; **P7/P8** UNIQUE va
CHECK rad etiladi. Ikki ochiq qayd yozilgan: (a) `cash_enabled()` non-PG'da `False` →
**naqd settlement qatori mahalliy bazada yozilmaydi** (yozuvchi darvozalanadi, CHECK
saqlanadi); (b) `run.bat` mavjud venv bilan `initdb` ni chaqirmaydi → Phase 3 ish hajmi.
UUID bind tuzog'i (xom SQL string ≠ ORM ko'rinishi) repetitsiyada topilgan va majburiy
qoida sifatida yozilgan.

## 11. Readiness / `check_canon` mosligi

**P9**: **27** ta taklif qilingan CHECK ifodasi `check_canon.canonical()` dan **o'tdi**
(funksiya chaqiruvi yo'q — `btrim` o'rniga `<> ''`). Registr qoidasi §5.2 da:
CHECK → `CHECK_DEFINITIONS` + `REQUIRED_PG_CONSTRAINTS` + `check_renderings_pg.py`
(+`len(RENDERINGS)` literali); UNIQUE → **faqat** `REQUIRED_INDEXES` kuchli tekshiruv
bilan. UNIQUE nomini CHECK registriga qo'shish urinishi **test bilan qizil** (§5.4-5).

## 12. Reversal shartnomasi verdikti

**PASS.** Shartnoma `services/cash/commands.py · ReversalCommand` va
`services/cash/posting.py · post_reversal` **manba kodidan** o'qildi: `source_id` —
yangi (izoh: «original'niki EMAS»), `leg_index` maydoni **yo'q** → default `0`,
`category=ADJUSTMENT` **qattiq kodlangan**. Revision 2 aynan bu uchtasiga zid yozgan edi;
Revision 3 Revision 1 ning to'g'ri bayonotini qaytardi. Tuzatish = **reversal +
almashtirish**; `cle_uq_reverses` global, shu bois takror reversal rad etiladi
(jim no-op emas).

## 13. `leg_no` / determinizm verdikti

**PASS, formal asos bilan.** `max+1` uchta shart birga bo'lgani uchun xavfsiz:
(1) **serializatsiya** — leg ajratadigan har yo'l `purchases(id)` ni `FOR UPDATE`
ushlaydi (repoda **ikkala** mavjud yo'l shunday qiladi: `edit_purchase`,
`lot_correction._correct_once`), shu bois shart **shartnomaga yozildi**;
(2) **zaxira to'siq** — `ux_ps_leg` + `cle_uq_business` (qulf noto'g'ri olinsa yozuv
rad etiladi, jimgina buzilmaydi); (3) **idempotentlik `leg_no` ga tayanmaydi** — hujjat
darajasidagi `client_uuid` indekslari + `ReceivingCorrection.response_json`.
`revision` ustuni **olib tashlandi** (u almashtiruvchi oyoqni imkonsiz qilardi).

## 14. Kompozit FK verdikti

**PASS.** Har ota jadvalda **aniq** nomzod kalit tekshirildi: `purchases` da
`(company_id, id)` **yo'q edi** → `uq_purchases_company_id` qo'shiladi; `employees` →
`uq_employees_company_id`; yangi jadvallar → `uq_creditors_company_id`,
`uq_ps_company_id`, `uq_ps_id_kind`. Presedent repoda bor (`uq_cgroup_company_id`,
`uq_brand_company_id`, MATCH SIMPLE). Boot tartibi: `_ensure_parent_uniques()` →
`_create_all` → … → `_ensure_foreign_keys` → `_verify_required_schema`.
PG **va** SQLite majburlashi repetitsiyada isbotlandi.

## 15. Report parity verdikti

**PASS (dizayn darajasida), lekin operatsion shart bilan.** Parity qatlami **besh**
shaklni o'rganishi kerak va **ikkitasi Revision 3 dan oldin ham buzilgan**:
inkassa TRANSFER juftligi va summa oshirilgan naqd xaridning leg-1'i — ikkisi ham
**birorta test bilan qotirilmagan**. Yana ikki shakl split va reversal bilan keladi,
beshinchisi SEYFni agregatga qo'shish. Ochiq qayd: **Phase 2 SEYF yo'lini kodda ochdi,
lekin R7 yopilmaguncha SEYFdan amalda foydalanish `compare_till` ni REVIEW ga suradi** —
bu Phase 2 nuqsoni emas, Phase 3s/8 ning kirish sharti (§13).

## 16. Concurrency / idempotentlik verdikti

**PASS.** Global qulf tartibi: FK ota qatorlari `FOR KEY SHARE` → `purchases`
`FOR UPDATE` → `suppliers` → `inventory` → `stock_batches` → event INSERT'lari →
custody (qulfsiz) → `cash.cash_accounts` → `cash.shifts`. Phase 0 da `pay_supplier`
inversiyasi **tuzatildi va deadlock testi bilan qotirildi** (test `pg_stat_database.
deadlocks` ni o'qiydi — eski tartibda **qizil**). Idempotentlik hujjat darajasida
(`client_uuid` + saqlangan javob), `leg_no` ga **tayanmaydi**. FIFO allokatsiyasi
deterministik (`created_at`, keyin `settlement_id`) va **dialekt-neytral** yozilishi
shart (`::text` PG-only — taqiqlandi). Ortiqcha qaytarish va manfiy balans qator-lokal
CHECK + xizmat invarianti bilan bloklanadi.

## 17. Traceability sanoqlari

| | 1-tur | gate turi | Jami |
|---|---|---|---|
| Topilma | 67 | 100 | **167** |
| BLOKLOVCHI | 14 | 28 | **42** |
| RESOLVED | 62 | 94 | **156** |
| SUPERSEDED | 5 | 3 | **8** |
| DEFERRED | 0 | 3 | **3** |
| OUT-OF-SCOPE | 0 | 0 | **0** |
| **Hal qilinmagan BLOKLOVCHI** | 0 | 0 | **0** |

`SUPERSEDED` = nuqson yopiq, lekin Revision 2 **mexanizmi almashtirildi** (masalan
`revision` ustuni, party-noyoblik indekslari, Revision 2 ning reversal xaritasi,
majburiy `CashMovement`). Har biri uchun yangi bo'lim **va** test shartnomasi bor.

## 18. Phase 1/3/4/6a–7 dependency matritsasi

| Ildiz | Phase 1 | Phase 3 | Phase 4 | Phase 6a | Phase 6b | Phase 7 |
|---|---|---|---|---|---|---|
| **R1** `leg_no` | — | **BLOK** | — | — | — | — |
| **R2** reversal | — | **BLOK** | — | — | — | — |
| **R3** ota-kalitlar | — | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R4** registr | **BLOK** | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R5** SQLite | **BLOK** | **BLOK** | — | **BLOK** | **BLOK** | **BLOK** |
| **R6** ochiq qoldiq | — | — | — | — | **BLOK** | **BLOK** |
| **R7** parity | **BLOK** | **BLOK** | — | — | — | **BLOK** |
| **R8** havola/test | — | — | — | — | — | — |

Bosqich tartibi: **0** ✅ → **2** ✅ → **R-fix** (kod tuzatishlari) → **1** → **3**
(`TILL_CASH`, `OWNER_ADVANCE`) → **3s** (`SAFE_CASH`, Phase 1+8 talab qiladi) → **4** →
**5** → **6a** → **6b** → **7** → **8** (Fayzanda haqiqiy SEYF).
Meros bo'limlar (kreditor hayot davri, ruxsat, Manager/Mobil UX, Purchase Return
forward-compat, migratsiya) **o'z bosqichi oldidan qayta bazalanishi** — kirish sharti.

## 19. Bosqich bo'yicha aniq test rejasi

| Bosqich | Testlar | Soni |
|---|---|---|
| **R-fix** | §4.5 (1–6), §5.4 (1–5), §6.5 (1–7), §8.5 (1–9) | 27 |
| **1** | ochilish: ikki marta rad, `counted<=balance`, attestatsiya, menejer+ darvozasi, ochilishdan keyin to'lov, backfill darvozasi, J BLOCK | 7 |
| **3** | §2.5 (1–6), §3.5 (1–7), split invariantlari, append-only rad, §9.4 kod registri+i18n | 20 |
| **4** | To'lov qatorlari UX, `api.ts` dict-detail, i18n | 3 |
| **5** | Mobil qatorlar; `permission_matrix.json` tegilmagan (F) | 2 |
| **6a** | §4.5 kreditor uchun, hayot davri, ruxsat (B/H/I), audit | 18 |
| **6b** | §7.5 (1–8) | 8 |
| **7** | §7.5 (2–6), §8.5 (6), Z-hisobot qadami | 7 |
| **8** | Fayzan: jismoniy sanoq, attestatsiya, ochilishdan keyin to'lov | 3 |
| | **JAMI** | **95** |

⚠️ Testlarni `PYTHONIOENCODING=utf-8` bilan yurgizmang (`test_check_defs_pg` cp1252
subprocess sababli yolg'on yiqiladi).

## 20. YAKUNIY VERDIKT

# ✅ REVISION 3 DESIGN GATE PASS

**Asos:** R1–R8 ning har biri 12 jihat bilan yopildi va shartnomalar **manba kodidan**
o'qildi; 20 repetitsiya **PASS, 0 FAIL** (jonli PG 18 + jonli SQLite) sxema da'volarini
isbotladi; buzilgan havola **0**, ziddiyat **0**, hal qilinmagan BLOKLOVCHI **0**;
27 CHECK va 14 UNIQUE indeks sanog'i nomlari bilan **mos**.

**Doira chegarasi (ochiq va ataylab):** bu PASS **dizayn** uchun. Kod tuzatishlari
(**R-fix**) hali yozilmadi va Phase 1/3/4/6a–7 ning BLOK shartlari aynan shunga bog'liq.

**Rioya:** business implementation **yo'q** · deploy **yo'q** · main merge **yo'q** ·
Fayzan SEYFi **yo'q** (va Phase 1 implement + verify bo'lmaguncha yaratilmaydi) ·
production/staging **tegilmagan** (repetitsiyalar vaqtinchalik mahalliy klasterlarda).
