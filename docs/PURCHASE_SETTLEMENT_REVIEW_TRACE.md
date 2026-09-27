# Adversarial ko'rik — TRACEABILITY, **REVISION 3** (167 topilma)

> Ikki ko'rik turi: **1-tur** (1-tahrir dizayni, 5 linza, **67** topilma) va **gate turi**
> (2-tahrir dizayni, 7 linza, **100** topilma). Bu hujjat har birining **Revision 3 dagi**
> holatini ko'rsatadi.
>
> - `RESOLVED` — yangi dizayn bo'limi **va** test shartnomasi BOR;
> - `SUPERSEDED` — nuqson yopiq, lekin 2-tahrir **mexanizmi almashtirildi**;
> - `DEFERRED` — bosqichga bog'landi, kirish sharti §13 da yozilgan;
> - `OUT-OF-SCOPE` — qaror bilan doiradan chiqarilgan.

| Ko'rsatkich | 1-tur | gate turi | Jami |
|---|---|---|---|
| Topilma | 67 | 100 | **167** |
| BLOKLOVCHI | 14 | 28 | **42** |
| RESOLVED | 62 | 94 | **156** |
| SUPERSEDED | 5 | 3 | **8** |
| DEFERRED | 0 | 3 | **3** |
| OUT-OF-SCOPE | 0 | 0 | **0** |
| **Hal qilinmagan BLOKLOVCHI** | **0** | **0** | **0** |

BLOKLOVCHI holatlari (gate turi): RESOLVED=28.

⚠️ **`SUPERSEDED` — «hal qilinmagan» degani EMAS.** Har biri uchun yangi kanonik
shartnoma va test shartnomasi bor; jadvalda aynan qaysi mexanizm almashtirilgani yozilgan.

⚠️ **`DEFERRED` — «e'tiborsiz» degani emas:** har biri §13 dagi bosqich
kirish shartiga bog'langan, ya'ni o'z bosqichi boshlanmasidan oldin yopilishi SHART.

---

## 1-tur (67) — Revision 3 dagi holati

| # | Linza | Nuqson (qisqa) | Revision 3 holati | Havola | Izoh |
|---|---|---|---|---|---|
| `claim-accuracy#1` | claim-accuracy | Ro'yxatda 7 ta chaqiruv bor (grep ham 7 ta topadi), 8-chi va eng muhim — O'QISH yo'li — tushib qolgan: preview_cash_custody -> res | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: 8-chi (O'QISH) chaqiruv qo'shildi — domen `preview_cash_custody`/`decide()` ga ham uzatiladi; §0 ga «to'rtinchi bo'g'in» kiritildi; §17 D- |
| `claim-accuracy#2` | claim-accuracy | Taklif qilingan sxemada ADJUSTMENT qatorini owner_advance_open ga bog'lashning BIRORTA yo'li yo'q: (1) ck_cl_adv_iff settlement_id | RESOLVED | Revision 2 (`3493d39`) — kuchda | state-consistency#2 bilan bir xil BLOKLOVCHI tuzatish |
| `deadlock#1` | deadlock | `purchases` va `suppliers` orasida repoda ALLAQACHON tartib inversiyasi bor va yangi slot uni AYNAN MEROS qilib oladi. `pay_suppli | RESOLVED | Revision 2 (`3493d39`) — kuchda | `pay_supplier` tartib inversiyasi ALOHIDA BOSQICH (0) qilib ajratildi va Bosqich 3 ning oldingi sharti deb belgilandi |
| `deadlock#2` | deadlock | Bu ketma-ketlik o'z sxemasi bilan ZID va shu sababli e'lon qilingan chain'ning oxiri YOLG'ON. `ck_ps_ledger_iff` naqd oyoq uchun ` | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: zanjir HAQIQIY tartibda qayta yozildi — INSERT'lar 8-qadamda, naqd qulflari 7-qadamda; `FOR NO KEY UPDATE` avval olinganidan keyin KEY SHA |
| `pg-semantics#1` | pg-semantics | SQLite'da `btrim` funksiyasi YO'Q (faqat `trim`). SQLite CHECK ifodasidagi funksiyani JADVAL YARATISH paytida hal qiladi — ya'ni c | RESOLVED | Revision 2 (`3493d39`) — kuchda | Barcha CHECK ifodalari FUNKSIYASIZ; bo'sh joy xizmat qatlamida trim qilinadi; §16.5 da «notanish funksiya jadval yaratishni YIQITADI» deb aniq yozildi |
| `pg-semantics#2` | pg-semantics | Funksiyali CHECK'ni bu mexanizmga QO'SHIB BO'LMAYDI: `check_canon` grammatikasi HAR QANDAY funksiya chaqiruvini rad etadi. Ikki yo | RESOLVED | Revision 2 (`3493d39`) — kuchda | Funksiya ishlatilmagani uchun `check_canon` grammatikasi barcha yangi CHECK'ni tahlil qiladi; §17 I-84 buni qotiradi |
| `requirement-coverage#1` | requirement-coverage | Ikki qoida bir-birini yo'q qiladi. Agar server hujjat `client_uuid`sini har settlement oyog'iga bossa — IKKINCHI oyoq global noyob | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: `purchase_settlements.client_uuid` OLIB TASHLANDI; idempotentlik hujjat darajasi + tabiiy kalitlar |
| `requirement-coverage#2` | requirement-coverage | Sxema buni IMKONSIZ qiladi: `ck_cl_adv_iff (type='ADVANCE') = (settlement_id IS NOT NULL)` biuslovli, ya'ni `ADJUSTMENT` qatorida  | RESOLVED | Revision 2 (`3493d39`) — kuchda | state-consistency#2 bilan bir xil BLOKLOVCHI tuzatish |
| `requirement-coverage#3` | requirement-coverage | `ADJUSTMENT` IKKI yo'nalishda ishlatiladi (kamaytirish: §5.3-b, §5.3-c, transfer manbasi; oshirish: transfer maqsadi), lekin «isho | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: `ADJUST_UP`/`ADJUST_DOWN` — ishora TIPDA; `SupplierLedger` ning ishorali `amount` naqshi ATAYLAB ko'chirilmadi |
| `requirement-coverage#4` | requirement-coverage | Talab 1 QOPLANMADI. Ochiq savollar RO'YXATI ham to'liq emas: A–G ga kirmagan kamida 5 qaror bor — (i) kreditor kodlari `_PIN_FORBI | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: ochiq savollar ro'yxati to'ldirildi (H, I, J, K, L qo'shildi) va BARCHASI javob oldi; C/D/E hujjat ichida yopildi |
| `state-consistency#1` | state-consistency | SAVOL (1) GA JAVOB: hujjat bo'yicha YARATILADI, va hujjat buni AYTMAYDI — teshik. REVERSAL oyog'i ham `source='OWNER_ADVANCE'` (§1 | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: `settlement_kind` ustuni + kompozit FK `(settlement_id, settlement_kind) -> purchase_settlements(id, kind)` + `CHECK settlement_kind='PAYM |
| `state-consistency#2` | state-consistency | SAVOL (2) GA JAVOB: bu TESHIK, va u ikki qatlamli. (i) `creditor_repayment_allocations.repayment_id uuid NOT NULL -> creditor_repa | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: `creditor_ledger.advance_id` qo'shildi; allokatsiya `ledger_id` ga kalitlandi; `closed_amount` hisoblagichi + `ck_oao_sum_le_amt` |
| `state-consistency#3` | state-consistency | SAVOL (3) va (5) GA JAVOB: HA — doimiy farq paydo bo'ladi, ochiq avanslar HALI ham manba kreditorda ochiq qoladi, va bu §3.5 atrib | RESOLVED | Revision 2 (`3493d39`) — kuchda | BLOKLOVCHI: haqiqat manbai `Σ(creditor_ledger ishorali)` deb NORMATIV belgilandi; transfer `ADJUST_DOWN`+`ADJUST_UP` juftligi bo'lgani uchun avtomatik |
| `state-consistency#5` | state-consistency | SAVOL (6) GA JAVOB: indekslar RUXSAT BERMAYDI, va qochish yo'li determinizmni buzadi. PAYMENT(A) → REVERSAL(PAYMENT(A)) → yana PAY | **SUPERSEDED** | §2.3 + §2.5-3/5 | R1 — `revision` ustuni va party-noyoblik indekslari BEKOR; o'rniga hujjat qulfi ostida monoton `max(leg_no)+1`, almashtiruvchi to'plam `n+k` raqamlarini oladi |
| `claim-accuracy#3` | claim-accuracy | apps/server/app/api/v1/sales.py:615-638 da mijoz qatori AYNAN TESKARI naqsh bilan qulflanadi — oddiy with_for_update() (FOR UPDATE | RESOLVED | Revision 2 (`3493d39`) — kuchda | Havola `services/sales.py:612-638` ga tuzatildi; `api/v1/sales.py:637-638` ning oddiy `FOR UPDATE` ishlatishi ALOHIDA ogohlantirish sifatida yozildi |
| `claim-accuracy#4` | claim-accuracy | 757-772 satrlar retry naqshi EMAS — ular _correct_once ichidagi partiya/mahsulot validatsiyasi (StockBatch bor-yo'qligi, PurchaseI | RESOLVED | Revision 2 (`3493d39`) — kuchda | `lot_correction.py:691-716` (`:712` da `sqlstate != '40P01'`) — o'zim tekshirdim |
| `claim-accuracy#5` | claim-accuracy | 294-301 satrlar `_create_purchase_once` ning boshi (client_uuid dedup), retry halqasi emas. Da'vo MAZMUNI to'g'ri, havola boshqa f | RESOLVED | Revision 2 (`3493d39`) — kuchda | `purchases.py:283-291` — o'zim tekshirdim: 3 marta qayta urinish halqasi bor |
| `claim-accuracy#6` | claim-accuracy | Hujjatning O'ZIDA 24 ta nomlangan CHECK bor (11 ck_ps_*, 4 ck_creditor_*, 6 ck_cl_*, 1 ck_cra_*, 2 ck_oao_*). «12» bilan reja tuzi | RESOLVED | Revision 2 (`3493d39`) — kuchda | pg-semantics#3 bilan bir xil: 31 ta (ko'rikchi 24 degan edi — 2-tahrirda jadvallar o'zgargani uchun qayta sanaldi) |
| `claim-accuracy#7` | claim-accuracy | Ikkala joyda ham DARVOZA BOR va u ataylab operator qaroriga bog'langan: catalog_commit_v2 da reaktivatsiya faqat DeletedMatchActio | RESOLVED | Revision 2 (`3493d39`) — kuchda | «darvoza yo'q» → «darvoza BOR, lekin u operator bayrog'i (`REACTIVATE_EXISTING`), moliyaviy holat emas»; `status` tanlashning haqiqiy sababi nom/telef |
| `claim-accuracy#8` | claim-accuracy | Dalil TO'LIQ EMAS: public sxemada AYNI naqsh ALLAQACHON qo'llanilgan va u xuddi shu cross-tenant nuqsonni tuzatish uchun kiritilga | RESOLVED | Revision 2 (`3493d39`) — kuchda | `customer_groups` + `customers` presedenti (`models/customers.py:33-36,44-53`) qo'shildi — o'zim tekshirdim; A endi «presedentsiz talab» emas |
| `claim-accuracy#9` | claim-accuracy | SEYF ochilishiga AYNAN tegishli EMAS: EXTRA_LEDGER shoxi `provenance == "NORMAL"` sharti ostida, §12.2 esa ochilish legini ATAYLAB | RESOLVED | Revision 2 (`3493d39`) — kuchda | SEYF ochilishi `RECONSTRUCTION` bo'lgani uchun `EXTRA_LEDGER` shoxiga TUSHMAYDI — kod o'zgarishi kerak emas, faqat test (E-47) |
| `claim-accuracy#10` | claim-accuracy | Repoda aynan shunday mexanizmning ishlaydigan presedenti BOR: set_permissions ichida `xodimlar.make_admin` kodi qattiq kodlangan h | RESOLVED | Revision 2 (`3493d39`) — kuchda | `make_admin` presedenti (`employees.py:658-659`) qo'shildi — «mexanizm YO'Q» da'voim XATO edi; kerakli ish — umumlashtirish |
| `claim-accuracy#11` | claim-accuracy | Ro'yxat TO'LIQ EMAS: §3.8 kreditor hodisalarini public.audit_log ga yozishni talab qiladi, `GET /audit` esa AYNI hisobot.view bila | RESOLVED | Revision 2 (`3493d39`) — kuchda | requirement-coverage#15 bilan bir xil tuzatish |
| `claim-accuracy#12` | claim-accuracy | Pul yo'qolmaydi: to'lovning TO'LIQ summasi (amt) SupplierPayment qatoriga, SupplierLedger(payment, −amt) ga va sup.balance = bal − | RESOLVED | Revision 2 (`3493d39`) — kuchda | «pul jimgina yo'qoladi» → «hujjat darajasidagi taqsimot yo'qoladi»; clamp'ni rad etish dalili operator xatosini jim yutishga almashtirildi |
| `deadlock#3` | deadlock | Chain o'zi meros qilib olayotgan shartnomaning 2-QADAMINI (`FK ota qatorlari FOR KEY SHARE`) tashlab ketadi — va aynan shu qadamni | RESOLVED | Revision 2 (`3493d39`) — kuchda | 0-qadam sifatida `FOR KEY SHARE` ota qatorlari (companies/branches/employees/creditors) tiklandi |
| `deadlock#4` | deadlock | `ledger_entry_id` uchun FK E'LON QILINMAGAN — sxema ro'yxatida u yolg'iz `uuid NULL` (keyingi qatordagi `reverses_id uuid NULL ->  | RESOLVED | Revision 2 (`3493d39`) — kuchda | K qarori: FK'siz mantiqiy havola (cross-schema), kafolat xizmat qatlamida — `ledger_entry_id` faqat shu tranzaksiyada yaratilgan qatordan; §17 C-25 |
| `deadlock#5` | deadlock | Ochiq smenali TILL'dan qaytarish legacy (ledger-native BO'LMAGAN) do'konda Z-hisobotga SOXTA ORTIQCHA beradi. `close_shift` kutilg | RESOLVED | Revision 2 (`3493d39`) — kuchda | Ochiq smenali TILL'dan qaytarishda `CashMovement(payout)` MAJBURIY — `pay_supplier` bilan bit-ba-bit; §17 G-72 |
| `deadlock#6` | deadlock | Bu yo'l §5.7 ning o'z invariantida HAR DOIM rollback bo'ladi. §5.7: haqiqat manbai `Σ(owner_advance_open.amount − repaid_amount)`, | RESOLVED | Revision 2 (`3493d39`) — kuchda | state-consistency#3 bilan bir xil tuzatish — transfer endi rollback bo'lmaydi |
| `deadlock#7` | deadlock | `EXTRA_LEDGER` shoxi `CASH_OP` ga xos EMAS — u har qanday NORMAL leg uchun oxirgi `else`: biznes kaliti kutilgan/live to'plamda to | RESOLVED | Revision 2 (`3493d39`) — kuchda | Xavf uch tashuvchiga yoyildi (CASH_OP, split PURCHASE, reversal) va `RECONSTRUCTION` ochilishi istisno qilindi |
| `pg-semantics#3` | pg-semantics | Haqiqatda 24 ta nomlangan CHECK bor — ikki baravar. Sanoq: purchase_settlements 11 (69-79), creditors 4 (236-239), creditor_ledger | RESOLVED | Revision 2 (`3493d39`) — kuchda | Qayta sanaldi: **31** ta nomlangan CHECK (jadval bo'yicha taqsimot bilan); `creditor_repayments` uchun `ck_cr_amount_pos` ANIQ nomlandi; `len(RENDERIN |
| `pg-semantics#4` | pg-semantics | `max+1` manbasi sifatida keltirilgan `next_leg_index` `cash_ledger_entries` dan o'qiydi, OWNER_ADVANCE oyog'i esa naqd yozuv YARAT | RESOLVED | Revision 2 (`3493d39`) — kuchda | REVERSAL `leg_no` = `max(purchase_settlements.leg_no)+1` (shu `purchase_id` doirasida); `next_leg_index` settlement uchun UMUMAN ishlatilmaydi |
| `pg-semantics#5` | pg-semantics | Ikkisi ham GLOBAL — tenantlararo. Ikki jadvalda `company_id` BOR, shu bois doirani kompaniyaga cheklamaslik uchun sabab yo'q. Hola | RESOLVED | Revision 2 (`3493d39`) — kuchda | `purchase_settlements.client_uuid` ustuni OLIB TASHLANDI; `creditor_repayments` da `UNIQUE (company_id, client_uuid)` |
| `pg-semantics#6` | pg-semantics | `OPTIONAL_UNIQUE_INDEXES` — FAQAT JURNAL sinfi: indeks qurilmasa `/health/ready` yashil qoladi va hech qaysi darvoza yopilmaydi. Y | RESOLVED | Revision 2 (`3493d39`) — kuchda | Pul kafolatini ko'taruvchi indekslar `REQUIRED_INDEXES` sinfiga o'tdi; faqat tezlik indekslari `PERFORMANCE` da |
| `pg-semantics#7` | pg-semantics | Repoda modeldagi qismiy indeks IKKI dialekt shartini ham talab qiladi. Faqat `postgresql_where` berilsa, SQLAlchemy SQLite uchun i | RESOLVED | Revision 2 (`3493d39`) — kuchda | Har qismiy indeks `postgresql_where=` VA `sqlite_where=` (ayni matn) bilan, yoki `_ensure_indexes` da xom DDL bilan — ikki dialektga ham |
| `pg-semantics#8` | pg-semantics | `company_id` ustunini qo'shish tenant doirasini MAJBURLAMAYDI — yangi jadvallar ota-qatordan ko'chirilgan `company_id`/`creditor_i | RESOLVED | Revision 2 (`3493d39`) — kuchda | Har bola jadval kompozit FK oladi (`(company_id, <parent_id>) -> parent(company_id, id)`); ota jadvallarga `UNIQUE (company_id, id)` qo'shildi |
| `pg-semantics#9` | pg-semantics | Noyoblik kaliti BO'SH JOYNI normallashtirmaydi. `ck_creditor_name_nb btrim(name) <> ''` faqat BUTUNLAY bo'sh nomni rad etadi; «She | RESOLVED | Revision 2 (`3493d39`) — kuchda | Saqlanadigan `name_key` ustuni (bo'shliq siqiladi + `casefold()`); noyoblik shu ustunda — funksiya ham, ifoda indeksi ham yo'q |
| `requirement-coverage#5` | requirement-coverage | `OPTIONAL_UNIQUE_INDEXES` repoda ataylab «FAQAT JURNAL … Yo'qligida pul/qoldiq ikkilanmaydi» sinfi va `optional_unique_missing()`  | RESOLVED | Revision 2 (`3493d39`) — kuchda | pg-semantics#6 bilan bir xil tuzatish |
| `requirement-coverage#6` | requirement-coverage | §2.2 dagi tana-solishtirish MEXANIZMI faqat `CashPostingService` qaytargan DUPLICATE natija uchun ta'riflangan. `OWNER_ADVANCE` oy | RESOLVED | Revision 2 (`3493d39`) — kuchda | Avans oyog'i uchun ham majburiy tana-solishtirish: `IntegrityError` constraint NOMI bo'yicha ajratiladi, qator o'qib solishtiriladi |
| `requirement-coverage#7` | requirement-coverage | `creditor_ledger` da BIRORTA noyob/idempotentlik kaliti YO'Q: na `client_uuid`, na `UNIQUE(settlement_id) WHERE type='ADVANCE'`, n | RESOLVED | Revision 2 (`3493d39`) — kuchda | `ux_cl_advance UNIQUE (settlement_id)` va `ux_cl_repayment UNIQUE (repayment_id)` qo'shildi; §10.3 jadvaliga kiritildi |
| `requirement-coverage#8` | requirement-coverage | Da'vo haddan ortiq. `ck_oao_repaid_le_amt` faqat HISOBLAGICHNI cheklaydi; `Σ(creditor_repayment_allocations.amount)` ning `repaid_ | RESOLVED | Revision 2 (`3493d39`) — kuchda | Tranzaksiya oxirida ikki tenglik invarianti e'lon qilindi (advance bo'yicha va ledger bo'yicha) |
| `requirement-coverage#9` | requirement-coverage | `client_uuid` NULLABLE va indeks QISMIY. Klient uni yubormasa (hujjat shakli buni majburlamaydi), qaytarishning birorta DB idempot | RESOLVED | Revision 2 (`3493d39`) — kuchda | `creditor_repayments.client_uuid` **NOT NULL**; yuborilmasa 400; indeks to'liq `(company_id, client_uuid)` |
| `requirement-coverage#10` | requirement-coverage | Yechim faqat BITTA so'rov ichida ishlaydi. Append-only (UPDATE yo'q) + `ux_ps_cred_party`/`ux_ps_cash_party` ning REVERSAL'ni hiso | **SUPERSEDED** | §2.3 + §2.5-4 | R1 — `revision` yo'q; qo'shimcha avans — YANGI oyoq (UPDATE emas); bir tanada ayni party ikki marta kelsa `400 PURCHASE_SETTLEMENT_DUPLICATE_PARTY` |
| `requirement-coverage#11` | requirement-coverage | Tartib SO'ROV TANASI ustida hisoblanadi, hujjatning TO'LIQ oyoq to'plami ustida emas — e'lon qilinmagan shart, ikki joyda buziladi | RESOLVED | Revision 2 (`3493d39`) — kuchda | E'lon qilingan shart: PAYMENT oyoqlari FAQAT hujjat yaratilishida bitta atomik to'plam; keyingi o'zgarish faqat REVERSAL + replacement revizyasi |
| `requirement-coverage#12` | requirement-coverage | `OWNER_ADVANCE` oyog'i `leg_no` ni EGALLAYDI, lekin ledgerga qator yozmaydi (`ck_ps_ledger_iff`). `next_leg_index()` esa max'ni FA | RESOLVED | Revision 2 (`3493d39`) — kuchda | pg-semantics#4 bilan bir xil tuzatish |
| `requirement-coverage#13` | requirement-coverage | Darvoza TOR: BITTA oyoqli (masalan faqat SAFE) settlement hujjati bloklanmaydi va eski tahrir yo'lidan o'tadi. Shu yo'lda: (i) `pu | RESOLVED | Revision 2 (`3493d39`) — kuchda | Darvoza kengaytirildi: settlement oyog'i bor HAR QANDAY hujjat → `409 SETTLEMENT_EDIT_UNSUPPORTED` |
| `requirement-coverage#14` | requirement-coverage | Ayni qiymat uchun UCH vakillik bor (kesh `creditors.balance`, `creditor_ledger`, `owner_advance_open`), lekin e'lon qilingan yagon | RESOLVED | Revision 2 (`3493d39`) — kuchda | Yagona normativ haqiqat manbai; `owner_advance_open` — faqat per-avans qo'riqchi, manba EMAS |
| `requirement-coverage#15` | requirement-coverage | Orqa darvoza `reports.py` da emas, `GET /audit` da qoladi: u ham `require("hisobot.view")` bilan qo'riqlanadi va javobda `payload. | RESOLVED | Revision 2 (`3493d39`) — kuchda | `GET /audit` orqa darvozasi qo'shildi: `entity='creditor'` qatorlari `kreditor.view` bo'lmasa filtrlanadi; §17 H-77 |
| `requirement-coverage#16` | requirement-coverage | §16.2 ayni hujjatda buni rad etadi: `public` da o'zgarmaslik triggeri naqshi yo'q, `initdb` da SQL trigger yaratadigan qadam YO'Q, | RESOLVED | Revision 2 (`3493d39`) — kuchda | K qarori bilan ziddiyat yo'q qilindi: Phase 1 da trigger YO'Q va u xavfsizlik chegarasi deb ko'rsatilmaydi |
| `requirement-coverage#17` | requirement-coverage | Noyoblik faqat JORIY nom ustida. Rename nomni BO'SHATADI: «Sherik Ali» → «Ali (eski)» dan keyin yangi kreditor «Sherik Ali» nomini | RESOLVED | Revision 2 (`3493d39`) — kuchda | G qarori bilan hal qilindi: surat identitet EMAS, UI joriy nomni ko'rsatadi — shu bois tarixiy kalitni band qilish KERAK EMAS va `creditor_name_keys`  |
| `requirement-coverage#18` | requirement-coverage | `owner_advance_open` ATRIBUTSIYA maydonlarini (`creditor_id`, `amount`, `currency`) o'zgarmaslik perimetridan tashqarida ushlaydi: | RESOLVED | Revision 2 (`3493d39`) — kuchda | Atributsiya maydonlari (`creditor_id`, `amount`, `currency`, `settlement_id`, `settlement_kind`, `created_at`) faqat INSERT'da; UPDATE faqat ikki hiso |
| `state-consistency#4` | state-consistency | SAVOL (4) GA JAVOB: hujjat qaysi manba hukm qilishini AYTMAYDI — «daftar» hujjatda §4 sarlavhasi bo'yicha `creditor_ledger` («Majb | RESOLVED | Revision 2 (`3493d39`) — kuchda | Yagona normativ ifoda bir joyda; §3.3 arxivlash darvozasi AYNAN shundan hisoblaydi |
| `state-consistency#6` | state-consistency | Ayni xavf `PURCHASE` uchun ham bor va hujjatda umuman qayd etilmagan — har bir split xarid parity'ni doimiy QIZIL qiladi. Kutilgan | RESOLVED | Revision 2 (`3493d39`) — kuchda | Split `PURCHASE` oyoqlari parity xavfi jadvalga kiritildi; `phase1._purchase_out_legs` ni settlement'dan qurish SHART deb yozildi |
| `state-consistency#7` | state-consistency | `REVERSAL.amount` ASL oyoq summasiga TENG bo'lishini birorta narsa majburlamaydi: `ck_ps_amount_pos` faqat `amount > 0` (:69), `ck | RESOLVED | Revision 2 (`3493d39`) — kuchda | `UNIQUE (id, amount)` + `FK (reverses_id, amount) -> purchase_settlements(id, amount)` — qisman reversal DEKLARATIV imkonsiz |
| `state-consistency#8` | state-consistency | Bu sabab O'ZINING dizayni bilan zid va yangi nuqson kiritadi. §2:121 `leg_index = purchase_settlements.leg_no`, §2.1:156 REVERSAL  | **SUPERSEDED** | §3.3 | R2 — Revision 2 «yangi `source_id`» ni olib tashlagan edi — Revision 3 uni KODDAN o'qib QAYTARDI: `source_id` = reversal qatorining o'z id'si, `leg_index=0`, `category=ADJUSTMENT` |
| `claim-accuracy#13` | claim-accuracy | To'qqiztasi ham 1-5 satr siljigan; ayrimlari boshqa funksiya/cheklovga tushadi: repositories.py:77-88 account_balance'dan chiqib s | **RESOLVED** (ilgari QISMAN) | Havola siyosati (hujjat boshi) | R8 — Satr-havola SINFI butunlay yo'q qilindi: kod havolalari simvol nomi bilan, satr raqami faqat `cash_ddl_v1.sql` uchun — QISMAN qoldiq HAM yopildi |
| `claim-accuracy#14` | claim-accuracy | Aksincha: :69 — typeLabel («Seyf»/«Kassa» yorlig'i), :314 — `for (final o in info.options) _option(o)` (ro'yxatni chizish). Ikki h | RESOLVED | Revision 2 (`3493d39`) — kuchda | `custody_block.dart:314` ro'yxatni chizadi, `:69` yorliq (`typeLabel`) — almashtirildi |
| `claim-accuracy#15` | claim-accuracy | serverErrorsCash.ts da 8 ta kod bor; resolve_cash_custody 7 ta to'g'ridan-to'g'ri chaqiruv (8-chisi preview — yuqoridagi BLOKLOVCH | RESOLVED | Revision 2 (`3493d39`) — kuchda | `serverErrorsCash` 8 ta; «8 joyda» → «7 yozuvchi + 1 o'qish»; trigger sanog'i da'vosi olib tashlandi |
| `claim-accuracy#16` | claim-accuracy | Bu ayniy jumla models/sales.py:48-49 da. dto.py:13-15 esa boshqa narsani aytadi — «Surat bo'lmasa (eski qator) — JORIY nomga qayti | RESOLVED | Revision 2 (`3493d39`) — kuchda | Sitata `models/sales.py:48-49` ga bog'landi; `dto.py:12-15` ning `or`-fallback naqshi ALOHIDA va biz undan voz kechganimiz qayd etildi |
| `claim-accuracy#17` | claim-accuracy | (a) shifts.py:158 bloki kodni tekshirmasa ham MODDIY MAYDONLARNI solishtiradi (cash_movement_matches), ya'ni «jim duplicate» xavfi | RESOLVED | Revision 2 (`3493d39`) — kuchda | `shifts.py:158` misoldan chiqarildi (u moddiy maydonlarni SOLISHTIRADI — to'g'ri naqsh); clamp dalili qayta yozildi |
| `claim-accuracy#18` | claim-accuracy | reports.py:1717-1736 da code/group_id/loyalty_points UMUMAN qatnashmaydi — so'rov faqat id/full_name/phone/credit_balance ni oladi | RESOLVED | Revision 2 (`3493d39`) — kuchda | Customer ustunlari uchun dalil `models/customers.py` ga; `reports.py:1717` faqat «kompaniya fakti» presedenti sifatida qoldi |
| `claim-accuracy#19` | claim-accuracy | Shu bo'limda auth.py:12-35 deganda app/models/auth.py nazarda tutilgan, lekin _PIN_FORBIDDEN_PERMS boshqa faylda — app/api/v1/auth | RESOLVED | Revision 2 (`3493d39`) — kuchda | `api/v1/auth.py:57-61` (`_PIN_FORBIDDEN_PERMS`) va `models/auth.py:12-35` aniq ajratildi — repoda ikkita `auth.py` bor |
| `pg-semantics#10` | pg-semantics | Repodagi HAR BIR ORM valyuta ustuni `String(3)` = varchar(3); `char(3)` faqat xom `cash` SQL DDL'da (u ORM bilan yaratilmaydi). PG | RESOLVED | Revision 2 (`3493d39`) — kuchda | Barcha yangi jadvallarda `varchar(3)` (ORM `String(3)`); `char(3)` ning bo'sh joy bilan to'ldirishi tushuntirildi |
| `pg-semantics#11` | pg-semantics | §2 (119) `source_id = purchase.id` deb qotirgan, §2.1 esa `leg_index = leg_no` deb belgilagan — ya'ni `leg_index=0` default HECH Q | **SUPERSEDED** | §3.3 | R2 — ayni tuzatish (koddan o'qilgan shartnoma) |
| `requirement-coverage#19` | requirement-coverage | Bitta so'rov tanasida AYNI party (ayni kassa hisobi yoki ayni kreditor) uchun ikki qator kelsa nima bo'lishi ta'riflanmagan. Mavju | RESOLVED | Revision 2 (`3493d39`) — kuchda | Bitta tanada AYNI party ikki qator → `400 DUPLICATE_PAYMENT_ROW`, INSERT'dan OLDIN; jim jamlash YO'Q |
| `requirement-coverage#20` | requirement-coverage | Yangi `source_id` qaysi tashuvchi qatordan va qaysi `source_type`/`category` bilan olinishi ta'riflanmagan (§16.1 yangi enum label | **SUPERSEDED** | §3.3 + §8.3-4 | R2 — reversal ledger xaritasi qayta yozildi va parity kutilgan-tomoniga qo'shildi |
| `requirement-coverage#21` | requirement-coverage | Indeks qismiy faqat NULL bo'yicha, STATUS bo'yicha emas → arxivlangan kreditor ham xodim havolasini abadiy band qiladi. Ya'ni plat | RESOLVED | Revision 2 (`3493d39`) — kuchda | `ux_creditors_employee` ga `AND status='ACTIVE'` qo'shildi — arxivlangan kreditor xodim havolasini abadiy band qilmaydi |
| `state-consistency#9` | state-consistency | `owner_advance_open` da `created_at` ustuni YO'Q — jadvalda faqat settlement_id, company_id, creditor_id, amount, repaid_amount, c | RESOLVED | Revision 2 (`3493d39`) — kuchda | `owner_advance_open` ga `created_at` qo'shildi (settlementdan ko'chirilgan, o'zgarmas); FIFO JOIN'siz va o'z-o'zidan to'liq |

> 1-turdagi `RESOLVED` qatorlarning ko'pchiligi 2-tahrir bo'limlarida yopilgan. Revision 3
> ularni **almashtirmaydi** — hujjat doirasi bloki bo'yicha ular `3493d39` dan
> havola bilan kuchda qoladi va o'z bosqichi oldidan qayta bazalanadi (§13).

---

## gate turi (100) — linza bo'yicha

### contradiction-scan (15)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 1 | BLOKLOVCHI | **R1** | §2.1 va §2.2 bir-birini yo'q qiladi: §2.1 «PAYMENT oyoqlari FAQAT hujjat yaratilishida yoziladi; mavjud hujjatga keyin o | RESOLVED | §2.3/§2.5 |  |
| 2 | BLOKLOVCHI | **R2** | §11 dagi reversal ledger xaritasi mavjud `CashPostingService` shartnomasi bilan bajarilmas, §8 esa to'g'ridan-to'g'ri IN | RESOLVED | §3.3/§3.5 |  |
| 3 | BLOKLOVCHI | **R3** | `fk_ps_purchase_same_company (company_id, purchase_id) -> purchases(company_id, id)` yaratilishi mumkin emas: `purchases | RESOLVED | §4.3/§4.5 |  |
| 4 | BLOKLOVCHI | **R4** | §3.4 `uq_employees_company_id` ni `REQUIRED_PG_CONSTRAINTS` ga kiritishni buyuradi, lekin bu registr FAQAT CHECK cheklov | RESOLVED | §5.2/§5.4 |  |
| 5 | BLOKLOVCHI | **R6** | Transfer maqsadidagi `ADJUST_UP` balansni oshiradi, lekin unga birorta `owner_advance_open` qatori mos kelmaydi; allokat | RESOLVED | §7.3/§7.5 |  |
| 6 | BLOKLOVCHI | **R6** | §3.9 `creditor_advance_allocations` da `currency` ni kompozit FK `(company_id, creditor_id, currency) -> creditors(compa | RESOLVED | §7.3/§7.5 |  |
| 7 | BLOKLOVCHI | **R8** | §3.5 `creditor_name_keys` jadvalini ATAYLAB olib tashlagan, lekin §3.6 merge'ni oldini olish mexanizmini hali ham shu ja | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 8 | BLOKLOVCHI | **R1** | §2.1 ning determinizm isboti REVERSAL qatorlari mavjud bo'lganda YOLG'ON: `party` ning noyobligi `ux_ps_cash_party`/`ux_ | RESOLVED | §2.3/§2.5 |  |
| 9 | JIDDIY | **R1** | §1.2 «pul kafolatini ko'taruvchi» indekslarni `REQUIRED_INDEXES` ga qo'yadi, lekin ro'yxatda `ux_creditors_employee` YO' | RESOLVED | §2.3/§2.5 |  |
| 10 | JIDDIY | **R7** | §5.9 majburiy `CashMovement(payout, reason="Kreditor · <nom surati>")` yozuvini talab qiladi — ya'ni nom SURATI audit bo | **SUPERSEDED** | §8.3 + Hujjat doirasi | Majburiy `CashMovement(payout, ...)` talabi BEKOR — kreditorga qaytarish yangi tashuvchi jadval bilan yoziladi va parity ro'yxatiga qo'shiladi |
| 11 | JIDDIY | **R7** | §5.1 split parity tashxisi noto'liq: `_purchase_out_legs` `_no_charge_exists()` bilan filtrlaydi, ya'ni SupplierLedger c | RESOLVED | §8.3/§8.5 |  |
| 12 | JIDDIY | **R4** | «31 ta CHECK» va «`len(RENDERINGS)` literali yangilangan» yakuniy holat uchun to'g'ri, lekin §18 jadvallarni Bosqich 1 / | RESOLVED | §5.2/§5.4 |  |
| 13 | JIDDIY | **R8** | «7 YOZUVCHI + 1 O'QISH» sarlavhasi jadvalning o'zi bilan zid: jadvalda «yozuvchi» deb belgilangan 8 qator bor (1–7 raqam | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 14 | KICHIK | **R6** | K qarori kafolatlarining 1-bandi va J-99 testi o'zgarmaslikni shartsiz «UPDATE/DELETE yo'q» deb ta'riflaydi, holbuki diz | RESOLVED | §7.3/§7.5 |  |
| 15 | KICHIK | **R8** | Indeks sinfi nomi hujjatda `OPTIONAL_UNIQUE` deb yozilgan; repodagi haqiqiy simvol — `OPTIONAL_UNIQUE_INDEXES`. Grep bil | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |

### ddl-compat (12)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 16 | BLOKLOVCHI | **R3** | `fk_ps_purchase_same_company (company_id, purchase_id) -> purchases(company_id, id)` uchun OTA noyoblik mavjud emas va h | RESOLVED | §4.3/§4.5 |  |
| 17 | BLOKLOVCHI | **R3** | Boot qadamlari TARTIBI hisobga olinmagan: mavjud jadvalga (`employees`, va 1-nuqson bo'yicha `purchases`) noyoblik qo'sh | RESOLVED | §4.3/§4.5 |  |
| 18 | BLOKLOVCHI | **R4** | `uq_employees_company_id` (UNIQUE cheklov) `REQUIRED_PG_CONSTRAINTS` ga kiritiladi deyilgan — lekin bu ro'yxat SEMANTIK  | RESOLVED | §5.2/§5.4 |  |
| 19 | JIDDIY | **R5** | Qismiy indekslarni e'lon qilishning IKKI yo'li «yo/yo» sifatida beriladi; «faqat modelda» yo'li sinflangan indekslar uch | RESOLVED | §6.3/§6.5 |  |
| 20 | JIDDIY | **R1** | Hujjatdagi indeks/noyoblik obyektlarining bir qismi HECH QAYSI sinfga biriktirilmagan — eng muhimi `ux_creditors_employe | RESOLVED | §2.3/§2.5 |  |
| 21 | JIDDIY | **R4** | 31 yangi CHECK uchun reja FAQAT `check_renderings_pg.py` yozuvlari + `len(RENDERINGS)` literalini o'z ichiga oladi; ular | RESOLVED | §5.2/§5.4 |  |
| 22 | JIDDIY | **R5** | «SQLite'da FK majburlanmaydi» da'vosi shu commitda YOLG'ON. Kodda har SQLite ulanishida `PRAGMA foreign_keys=ON` o'rnati | RESOLVED | §6.3/§6.5 |  |
| 23 | JIDDIY | **R3** | A qarorining cross-tenant kafolati TO'LIQ EMAS: `tenant_purge` barcha egalik yo'llarini OR bilan qo'shadi va BIR USTUNLI | RESOLVED | §4.3/§4.5 |  |
| 24 | KICHIK | **R8** | Qulf darajasi haqidagi da'vo noto'g'ri va ko'rsatilgan cross-reference mavjud emas: «`CREATE UNIQUE INDEX` mavjud jadval | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 25 | KICHIK | **R5** | Test matritsasida FRESH bo'sh Postgres'da boot testi YO'Q — faqat «Alohida SQLite boot testi» bor. Aynan 1-nuqson (42830 | RESOLVED | §6.3/§6.5 |  |
| 26 | KICHIK | **R4** | Hujjat majburiy qilib qo'ygan o'qish yo'llari uchun tezlik indekslari e'lon qilinmagan: §5.7 har tranzaksiya oxirida `cr | **DEFERRED** | §13 (Phase 6b/7) | O'qish yo'li tezlik indekslari e'lon qilinmagan — `PERFORMANCE_INDEXES` ro'yxati kreditor daftari tug'ilganda (6b) belgilanadi |
| 27 | KICHIK | **R3** | `db/schema.sql` — CLAUDE.md da kanonik DB hujjati deb ko'rsatilgan fayl — hujjatda BIR MARTA ham eslanmagan. Olti yangi  | RESOLVED | §4.3/§4.5 |  |

### sqlite-runbat (9)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 28 | BLOKLOVCHI | **R5** | §16.5 ning asosiy shartnomasi — «FK majburlanmaydi (`sqlite-fk-yoq`)» — FAKTIK XATO. Repo mahalliy SQLite'da chet kalitl | RESOLVED | §6.3/§6.5 |  |
| 29 | BLOKLOVCHI | **R3** | `fk_ps_purchase_same_company (company_id, purchase_id) -> purchases(company_id, id)` talab qilinadi, lekin `purchases` d | RESOLVED | §4.3/§4.5 |  |
| 30 | BLOKLOVCHI | **R3** | `uq_employees_company_id` ni yaratish uchun tanlangan mexanizm — «`REQUIRED_PG_CONSTRAINTS` ro'yxatiga kiritiladi va boo | RESOLVED | §4.3/§4.5 |  |
| 31 | JIDDIY | **R5** | Hujjat mahalliy xavfni FAQAT «boot FATAL» sifatida tasvirlaydi, lekin `run.bat`ning ODATIY yo'li (venv allaqachon bor) ` | RESOLVED | §6.3/§6.5 |  |
| 32 | JIDDIY | **R5** | `ck_ps_ledger_iff` naqd oyoq uchun `ledger_entry_id` ni majburiy qiladi, `cash_enabled()` esa non-Postgres'da HAR DOIM F | RESOLVED | §6.3/§6.5 |  |
| 33 | JIDDIY | **R5** | FIFO tartibi normativ ravishda `ORDER BY created_at, settlement_id::text` deb SQL shaklida beriladi. `::` — faqat Postgr | RESOLVED | §6.3/§6.5 |  |
| 34 | KICHIK | **R5** | «Natija: `run.bat` (mahalliy SQLite) va butun SQLite to'plami model qo'shilgan zahoti ishga tushmasdi» — noaniq. `run.ba | RESOLVED | §6.3/§6.5 |  |
| 35 | KICHIK | **R1** | Hujjat ustun tiplarini FAQAT SQL shaklida beradi (`smallint`, `numeric(14,2)`, `timestamptz`, `varchar(120)`, `text`) va | RESOLVED | §2.3/§2.5 |  |
| 36 | KICHIK | **R2** | `amount` ustunini kompozit FK KALITI sifatida ishlatish SQLite'da suzuvchi nuqta solishtiruvi bo'lib qoladi: repoda `asd | RESOLVED | §3.3/§3.5 |  |

### readiness-canon (11)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 37 | BLOKLOVCHI | **R4** | `uq_employees_company_id` (UNIQUE cheklov) `REQUIRED_PG_CONSTRAINTS` ga kiritib bo'lmaydi — bu ro'yxat FAQAT CHECK chekl | RESOLVED | §5.2/§5.4 |  |
| 38 | BLOKLOVCHI | **R3** | Boot tartibi `create_all` ni BIRINCHI bajaradi, `_ensure_*` qadamlari KEYIN. MAVJUD Postgres bazada (staging/production) | RESOLVED | §4.3/§4.5 |  |
| 39 | JIDDIY | **R4** | «Majburiy qotirish qadami» chala: `test_check_canon.py` dagi qattiq kodlangan `_TEXT` (`{cheklov_nomi: {matn_ustunlari}} | RESOLVED | §5.2/§5.4 |  |
| 40 | JIDDIY | **R5** | Bu «erkin tanlov» EMAS: tayyorlik sinfiga (REQUIRED_INDEXES / PERFORMANCE_INDEXES) kiritilgan HAR indeks `initdb.py` da  | RESOLVED | §6.3/§6.5 |  |
| 41 | JIDDIY | **R6** | To'qqizta indeks REQUIRED_INDEXES ga BITTA to'plam sifatida yoziladi, lekin ularning jadvallari turli bosqichlarda tug'i | RESOLVED | §7.3/§7.5 |  |
| 42 | JIDDIY | **R1** | «Pul kafolatini ko'taruvchi indekslar REQUIRED_INDEXES ga qo'yiladi» deyilgan, lekin hujjatning O'ZI pul/identitet kafol | RESOLVED | §2.3/§2.5 |  |
| 43 | JIDDIY | **R4** | Qulf darajasi NOTO'G'RI ko'rsatilgan: `CREATE [UNIQUE] INDEX` (CONCURRENTLY'siz) SHARE oladi, ACCESS EXCLUSIVE esa `ADD  | RESOLVED | §5.2/§5.4 |  |
| 44 | KICHIK | **R4** | `len(RENDERINGS)` literalining HOZIRGI qiymati (25) ham, maqsad qiymati (25+31=56) ham hujjatda yo'q. «Literali yangilan | RESOLVED | §5.2/§5.4 |  |
| 45 | KICHIK | **R4** | Satr havolasi noto'g'ri: «har majburiy CHECK uchun rendering bo'lishi» testi 42-46 satrlarda; 40-41 bo'sh satrlar. | RESOLVED | §5.2/§5.4 |  |
| 46 | KICHIK | **R4** | REQUIRED_PG_CONSTRAINTS ga tushgan har CHECK uchun ORM modelida AYNI matnli `CheckConstraint` bo'lishi SHART (bo'shliqla | RESOLVED | §5.2/§5.4 |  |
| 47 | KICHIK | **R4** | `_ensure_lot_checks` BARCHA REQUIRED_PG_CONSTRAINTS uchun BITTA 30 sekundlik byudjetni bo'lishadi va har cheklov uchun a | RESOLVED | §5.2/§5.4 |  |

### parity-contract (12)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 48 | BLOKLOVCHI | **R7** | Aggregate parity yuzasi (`shadow_compare.compare_till`/`compare_tenant`) dizaynda MUTLAQO yo'q. `compare_tenant` ledger  | RESOLVED | §8.3/§8.5 |  |
| 49 | BLOKLOVCHI | **R7** | Runtime tomonidan yoziladigan `provenance='RECONSTRUCTION'` legi backfill verifikatsiyasini va `post_backfill_verificati | RESOLVED | §8.3/§8.5 |  |
| 50 | BLOKLOVCHI | **R7** | §5.1 ning normativ sharti BAJARILMAYDI: `compare_leg` `posting_kind`, `shift_id` va `branch_id` ni solishtiradi, lekin ` | RESOLVED | §8.3/§8.5 |  |
| 51 | BLOKLOVCHI | **R7** | Mismatch inventari yarim: hujjat faqat `WRONG_AMOUNT` va `EXTRA_LEDGER` ni sanaydi. Amalda SEYF legi KAFOLATLI `WRONG_AC | RESOLVED | §8.3/§8.5 |  |
| 52 | JIDDIY | **R7** | `_no_charge_exists()` filtri hech qayerda muhokama qilinmagan. §9 bo'yicha `unpaid > 0` bo'lsa `SupplierLedger(charge)`  | RESOLVED | §8.3/§8.5 |  |
| 53 | JIDDIY | **R2** | Ikki bo'lim ayni funksiyaga ZID ko'rsatma beradi. §5.1: «har PAYMENT naqd oyog'i uchun bitta» — ya'ni REVERSAL qatorlari | RESOLVED | §3.3/§3.5 |  |
| 54 | JIDDIY | **R7** | §5.9 ochiq smenali TILL'dan qaytarishda `CashMovement(payout, reason="Kreditor · …")` ni MAJBURIY qiladi, lekin §5.1 bu  | **SUPERSEDED** | §8.3 + Hujjat doirasi | 10-topilma bilan ayni |
| 55 | JIDDIY | **R7** | Xavf «split» ga bog'langan, lekin KO'P OYOQLI `PURCHASE` BUGUN HAM bor: `edit_purchase` summani oshirganda leg >=1 yozil | RESOLVED | §8.3/§8.5 |  |
| 56 | JIDDIY | **R7** | I-86 test SHARTNOMASI emas, bir jumlali niyat: fayl nomi yo'q, fixture yo'q, summalar yo'q, kutilgan `matched` soni yo'q | RESOLVED | §8.3/§8.5 |  |
| 57 | JIDDIY | **R8** | Bosqich 3 ning oldingi sharti «0, 2» deb yozilgan — Bosqich 1 (SEYF ochilish qoldig'i) KIRMAGAN. Lekin §0/§7.3 ga ko'ra  | RESOLVED | §13 (`3s` qatori) | Phase 3 `SAFE_CASH` manbasi Phase 1 + 8 ga bog'landi — ochilish qoldig'isiz SEYF manbasi YOZILMAYDI |
| 58 | KICHIK | **R7** | SEYF oyog'i uchun filial cheklovi belgilanmagan. Boshqa filialdagi (masalan markaziy) SEYFdan to'lov `WRONG_BRANCH` bera | RESOLVED | §8.3/§8.5 |  |
| 59 | KICHIK | **R7** | Havola noto'g'ri: da'vo qilingan `leg_index=0` 172-190 oralig'ida YO'Q. Funksiya 172-198 satrlarda, `_leg(...)` chaqiruv | RESOLVED | §8.3/§8.5 |  |

### determinism-adversarial (15)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 60 | BLOKLOVCHI | **R1** | `leg_no` uchun IKKI xil allokator bitta noyoblik fazosida: §2.1 «kanonik tartibdagi indeks» (0 dan boshlanadi), §2.3 «ma | RESOLVED | §2.3/§2.5 |  |
| 61 | BLOKLOVCHI | **R1** | Yuqoridagi leg_no to'qnashuvi naqd ledgerga ham o'tadi: `cle_uq_business` da revizya o'lchovi yo'q va `leg_index = leg_n | RESOLVED | §2.3/§2.5 |  |
| 62 | BLOKLOVCHI | **R6** | §3.6 transferi maqsad kreditorda `ADJUST_UP` yozadi, lekin unga mos `owner_advance_open` qatori TUZILISHAN imkonsiz (PK  | RESOLVED | §7.3/§7.5 |  |
| 63 | JIDDIY | **R1** | `revision = max(revision)+1` ning takror-idempotentligi «tuzatish hujjatining client_uuid»siga bog'langan, lekin bu hujj | RESOLVED | §2.3/§2.5 |  |
| 64 | JIDDIY | **R6** | §3.9 besh jadval uchun UCH USTUNLI valyuta kompozit FK sini majburlaydi, lekin har bir jadvalning FK ro'yxatida faqat IK | RESOLVED | §7.3/§7.5 |  |
| 65 | JIDDIY | **R6** | §10.2 zanjiri o'z qoidasini buzadi: 1112-1115 «FOR KEY SHARE ota qatorlari HAR QANDAY FOR UPDATE dan OLDIN olinadi, chun | RESOLVED | §7.3/§7.5 |  |
| 66 | JIDDIY | **R6** | `repaid_amount`/`closed_amount` hisoblagichlari: (a) `owner_advance_open` qatori HECH QAYERDA qulflanmaydi; (b) UPDATE n | RESOLVED | §7.3/§7.5 |  |
| 67 | JIDDIY | **R6** | `creditor_repayments` da `request_hash`/`response_json` YO'Q, shu bois §5.2:829-830 dagi «retry → ux_cr_client_uuid biri | RESOLVED | §7.3/§7.5 |  |
| 68 | JIDDIY | **R6** | 2-tahrir uchta YANGI deterministik allokator kiritdi — REVERSAL `leg_no = max+1` (§2.3), `revision = max+1` (§2.2), FIFO | RESOLVED | §7.3/§7.5 |  |
| 69 | JIDDIY | **R5** | «Constraint NOMI bo'yicha ajratish» faqat Postgres'da mumkin (`psycopg` `diag.constraint_name`). SQLite'da `sqlite3.Inte | RESOLVED | §6.3/§6.5 |  |
| 70 | KICHIK | **R8** | `creditor_name_keys` jadvali §3.5 da ANIQ olib tashlangan, lekin §3.6 uni hali ham amaldagi oldini-olish mexanizmi deb s | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 71 | KICHIK | **R1** | `party::text` bo'yicha saralash determinizmi saralanadigan QIYMAT shakliga bog'liq, lekin hujjat uni belgilamaydi. Klien | RESOLVED | §2.3/§2.5 |  |
| 72 | KICHIK | **R2** | Har oyoq uchun SAVEPOINT kiritilgan, lekin savepoint rollback'idan KEYIN xizmat nima qilishi aytilmagan (abort qilish yo | RESOLVED | §3.3/§3.5 |  |
| 73 | KICHIK | **R8** | «Get-or-create `IntegrityError` retry'ga tayanadi» — lekin PG da noyoblik buzilishi tranzaksiyani abort qiladi (25P02) v | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 74 | KICHIK | **R1** | Settlement identiteti to'liq `purchase_id NOT NULL` ga bog'langan, hujjat esa asosiy UI oqimi sifatida QABUL (receiving) | RESOLVED | §10 (qabul izohi) | `receivings.purchase_id` modelda nullable, lekin yagona yozuvchi uni HAR DOIM Purchase bilan yozadi — koddan tasdiqlangan |

### refs-and-structure (26)

| # | Jiddiylik | Ildiz | Nuqson (qisqa) | Holat | Havola | Izoh |
|---|---|---|---|---|---|---|
| 75 | BLOKLOVCHI | **R8** | Ko'rilayotgan hujjat COMMIT QILINMAGAN. FINAL DESIGN GATE reportida talab qilingan «exact commit SHA» shu kontentga mos  | RESOLVED | Revision 3 commit | Hujjat commit qilindi; gate report SHA ni nomlaydi |
| 76 | BLOKLOVCHI | **R8** | ZIDDIYAT: §3.5 `creditor_name_keys` jadvalini ATAYLAB O'CHIRADI, §3.6 esa uni hamon himoya mexanizmi deb sanaydi va §18  | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 77 | BLOKLOVCHI | **R8** | §18.1 O'Z ICHIDA ZID: 1-band `fk_ps_creditor_same_company` ni «**3-bosqichda** yoziladi» deb e'lon qiladi, 2-band esa «n | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 78 | BLOKLOVCHI | **R8** | §18 bosqich jadvali test guruhlaridan FAQAT A/B/C, D, E, F, G ni biriktiradi. **H (73-77), I (78-86), J (87-100) — jami  | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 79 | BLOKLOVCHI | **R8** | H qarorining e'lon qilingan natijasi MEXANIK JIHATDAN IMKONSIZ: «PIN bilan kirgan **ega**» degan holat repoda mavjud ema | RESOLVED | §0 (H qatori) | H natijasi tuzatildi: ega PIN bilan KIRA OLMAYDI (`_pin_login_allowed` `FULL_ACCESS_ROLES` uchun False) — «PIN bilan kirgan ega» holati yo'q |
| 80 | JIDDIY | **R8** | NOTO'G'RI file:line — oldingi ko'rikning 1-BLOKLOVCHISI (`claim-accuracy#1`) uchun tuzatish havolasi boshqa funksiyani k | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 81 | JIDDIY | **R8** | TUZATILMAGAN QOLDIQ: H-74 hamon OCHIQ SAVOL shaklida yozilgan («B-savol javobiga ko'ra rad/ruxsat»), holbuki B qarori YO | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 82 | JIDDIY | **R8** | K qarorining almashtiruvchi kafolati YO'Q. J-99 «C-26 to'g'ridan-to'g'ri urinishni hujjatlashtiradi» deydi, lekin C-26 O | **SUPERSEDED** | §14 (Phase 3) | Revision 2 test raqamlari bekor; K ning almashtiruvchi kafolati = xizmat qatlamida append-only testi (trigger YO'Q, shu bois test YAGONA kafolat) |
| 83 | JIDDIY | **R8** | NOTO'G'RI CROSS-REFERENCE: «§17 **F-guruhida** shu qotiriladi» — F qarorining qotiruvchi testi J-96 da, F test guruhida  | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 84 | JIDDIY | **R8** | 7 yozuvchidan 3 tasi uchun O'QISH (preview) yo'li UMUMAN mavjud emas, shu bois D-41 «preview ↔ yozuvchi parity» ular uch | **DEFERRED** | §13 (Phase 4) | Uch yozuvchi uchun preview yo'li yo'q — F qarori bo'yicha Phase 1 da UI yo'q; preview/yozuvchi parity Phase 4 ish hajmida |
| 85 | JIDDIY | **R8** | TUZATILMAGAN QOLDIQ, aynan hujjatning o'zi 1-tahrirda qoralagan sinf: `sales.py` malakasiz yozilgan, repoda ikki xil `sa | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 86 | JIDDIY | **R1** | Ikki YANGI xato kodi yetim: hujjatda bir marta paydo bo'ladi, §13 ning i18n ro'yxatida (:1336-1339) YO'Q va §17 da biror | RESOLVED | §2.3/§2.5 |  |
| 87 | JIDDIY | **R8** | NOTO'G'RI file:line — sanab o'tilgan to'rt indeksdan biri (`ux_recv_corr_client`) berilgan diapazonda YO'Q. | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 88 | JIDDIY | **R8** | §18.1 chegara jadvali Bosqich 5 ni HECH QAYSI yo'lakka kiritmaydi, ayni paytda Yo'lak 1 ustuni «mobil naqd split» ni o'z | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 89 | JIDDIY | **R8** | (d) MOSLIK BUZILGAN: §18 Bosqich 6a ning qaror-bog'liqligi «A, B, H, I», §18.1 esa Yo'lak 2 uchun «A, B, F, G, H, I (+ K | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 90 | KICHIK | **R8** | SILJIGAN file:line: keltirilgan izoh («Keyingi audit … SHU ustunga tayanadi», «FK YO'Q (cash.* cross-schema)») berilgan  | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 91 | KICHIK | **R8** | NOTO'G'RI satr: «T0 da hech qanday ochilish yozuvi yozilmaydi» da'vosini tasdiqlovchi matn 96-satrda emas. | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 92 | KICHIK | **R8** | SILJIGAN file:line: `require()` ning FULL_ACCESS chetlab o'tishi 126-128 da emas — diapazon `return emp` ni kesib tashla | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 93 | KICHIK | **R4** | SILJIGAN file:line: ikki havola ham o'zi tasvirlagan assert/chaqiruvni diapazondan tashqarida qoldiradi. | RESOLVED | §5.2/§5.4 |  |
| 94 | KICHIK | **R8** | NOTO'G'RI SON: «`reports.py` (~30 ta `require("hisobot.view")`)» — haqiqiy son 2 barobar kam. | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 95 | KICHIK | **R4** | MAVJUD BO'LMAGAN IDENTIFIKATORLAR: hujjat `OPTIONAL_UNIQUE` va `PERFORMANCE` deb yozadi; repoda bunday nomlar yo'q. | RESOLVED | §5.2/§5.4 |  |
| 96 | KICHIK | **R2** | DIAPAZON TO'G'RI, DA'VO KENGAYTIRILGAN: «ikkinchi OUT legni **boshqa hisobga** yozadi» — keltirilgan kod buni isbotlamay | RESOLVED | §3.3/§3.5 |  |
| 97 | KICHIK | **R8** | Presedent sifatida keltirilgan kod boshqa HTTP holatini beradi: hujjat «→ `raise 409 OVER_REPAYMENT`» deb naqsh sifatida | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 98 | KICHIK | **R8** | MUNDARIJA UZILGAN: mavjud bo'lmagan sarlavhani nomlaydi va mavjud bir bo'limni tushirib qoldiradi. Nomi hujjatning o'z h | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |
| 99 | KICHIK | **R6** | `creditor_referenced()` ro'yxati `owner_advance_open` ni tushirib qoldirgan, holbuki u `creditor_id NOT NULL` + kompozit | **DEFERRED** | §13 (Phase 6a meros) | `creditor_referenced()` ro'yxati kreditor hayot davri bo'limida — u Revision 2 dan havola bilan meros va Phase 6a dan OLDIN qayta bazalanadi |
| 100 | KICHIK | **R8** | Test havolasi qismi noto'g'ri: `tenant_purge` da'vosi uchun F-60 keltirilgan, lekin F-60 DDL darajasidagi cross-tenant r | RESOLVED | Havola siyosati + §9.2/§9.3/§9.4 |  |

---

## Ildiz sabab bo'yicha yig'ma (gate turi)

| Ildiz | Topilma | BLOKLOVCHI | Dizayn bo'limi |
|---|---|---|---|
| **R1** | 12 | 4 | §2.3/§2.5 |
| **R2** | 5 | 1 | §3.3/§3.5 |
| **R3** | 8 | 6 | §4.3/§4.5 |
| **R4** | 14 | 3 | §5.2/§5.4 |
| **R5** | 10 | 1 | §6.3/§6.5 |
| **R6** | 11 | 3 | §7.3/§7.5 |
| **R7** | 12 | 4 | §8.3/§8.5 |
| **R8** | 28 | 6 | Havola siyosati + §9.2/§9.3/§9.4 |
