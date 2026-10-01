# P9 ZANJIRI — YAGONA TO'LIQ HISOBOT

**Sana:** 2026-10-01 · **Holat:** zanjir yakunlandi, ega qarorini kutmoqda
**Hech narsa push / merge / deploy qilinmagan.** Production backend hamon `05b43fe`.

---

## 1. Qisqacha xulosa

Mustaqil adversarial QA auditi **11 ta nuqsonni bajariladigan sinov bilan** isbotladi
(2 tasi P0). Shundan **P9 sinfiga kirgan 6 tasi** ketma-ket beshta bosqichda ko'rildi:

| Topilma | Natija | Bosqich |
|---|---|---|
| **P9-01** offline idempotentlik kaliti yo'q | ✅ **TUZATILDI** | CR1 |
| **P9-02** `sold_at` orqali noto'g'ri smena | ✅ **TOR DOIRADA TUZATILDI** (ega qaroriga ko'ra 3A kontrakti saqlandi) | CR1 |
| **P9-03** kalit egaligi (boshqa kassir) | ✅ **TUZATILDI** | CR2 |
| **P9-04** transfer dedup ijarachi-skopsiz | ✅ **TUZATILDI** | CR3 |
| **P9-05** onlayn savdo vs smena yopilishi | ✅ **TUZATILDI** | CR4 |
| **P9-06** `_lock_candidate_shift` eskirgan ORM | ⚖️ **MEXANIZM TASDIQLANDI, OQIBAT YETIB BORMAYDI → tuzatish qilinmadi** | CR5 |

Qo'shimcha: CR4 da **o'zim CR2 da kiritgan regressiyani** topdim va tuzatdim (tarozi cheki
o'z qonuniy takroridan rad etilardi — Fayzan biznesining o'zagi).

Ishlab chiqarish kodi o'zgarishi jami: **~360 qator** (asosan izoh), **5 fayl**, **migratsiya yo'q**.

---

## 2. Zanjir va SHA'lar

```
7381e21  p9-pos-offline-shift-safety   ← Phase 3A (baza)
   │
   ├─ e78319d  p9-critical-repair-1    P9-01 + P9-02(tor) + ledger-jadval tuzatishi
   ├─ 115c85e  p9-critical-repair-2    P9-03
   ├─ 43152e6  p9-critical-repair-3    P9-04
   ├─ e0eeefa  p9-critical-repair-4    P9-05 + CR2 regressiyasi
   └─ fd2d765  p9-critical-repair-5    P9-06 (tuzatish YO'Q, holat qayd etildi)

ac6421e  qa/binos-independent-security  ← asl audit dalili
09a2eac  origin/main                    ← faqat o'qildi, tegilmagan
```

Har bir worktree **toza**; har bir commit ota-si oldingi bosqichning yakuniy SHA'si.

| Bosqich | Ishlab chiqarish diff'i |
|---|---|
| CR1 | 3 fayl, +78 / −1 |
| CR2 | 2 fayl, +96 |
| CR3 | 2 fayl, +99 / −5 |
| CR4 | 1 fayl, +85 / −7 |
| **CR5** | **0 — kod tegilmagan** |

---

## 3. Har bir topilma: nima edi, nima qilindi

### P9-01 — offline chek idempotentlik kalitisiz qabul qilinardi · **P0**

`/sync/push` ning butun dublikat himoyasi `client_uuid` ga tayanadi, lekin kalitsiz chekda
na dastur dedup'i, na baza to'sig'i ishlardi (`ux_sales_company_client_uuid` — qisman indeks,
NULL'ni qamramaydi). **Reproduksiya:** ikki push → 2 sotuv, qoldiq 10 → 8.

**Tuzatish:** kalit majburiy (yo'q / nol-UUID → doimiy rad, `SYNC_IDEMPOTENCY_KEY_REQUIRED`).
Server yangi kalit **yaratmaydi**. Onlayn `/sales` semantikasi tegilmadi.

### P9-02 — `sold_at` smenani tanlaydi · **P0 → tor doirada**

Asl kutilma: yopilgan smenaga replay taqiqlanishi. **Ega qarori:** Phase 3A ning
ratifikatsiya qilingan Case C / LATE_SYNC kontrakti **saqlanadi** — strict variant bekor
qilindi, 3A testlari tiklandi.

**Qayta tahlildan keyin topilgan tor nuqson:** replay izlashi kassirni cheklaydi, **filialni
yo'q**; chekning filiali esa `actor_branch` dan keladi. Natijada bitta chek ikki filialga
bo'linardi — tovar B dan, pul A ning kassasiga.

**Tuzatish:** izlashga `Shift.branch_id == branch.id` (bitta shart). 3A tegilmadi.

### P9-03 — kalit boshqa kassirning natijasini qaytarardi · **P1**

Dedup faqat `(company_id, client_uuid)` bo'yicha borib, topilgan chekni **shartsiz**
qaytarardi. **Reproduksiya:** B kassirga 200 OK + A ning `receipt_no`/`id`; B ning cheki
umuman yozilmagan, B ning tovari qoldiqda qolgan, puli hech qayerda yo'q. Ikkala yo'lda ham
(`/sync/push` va onlayn `/sales`).

**Tuzatish:** topilgan chek faqat **ayni kassir + ayni savat + ayni to'lov usuli** (offline
yo'lda narx ham) bo'lsa takror; aks holda **400 `IDEMPOTENCY_KEY_REUSED`**, hech narsa
yozilmaydi. Naqsh — repodagi ratifikatsiya qilingan `cashops.replay_answer`.

### P9-04 — transfer dedup ijarachi doirasidan tashqarida · **P1**

`stock_movements` da `company_id` ustuni yo'q, dedup esa faqat `(client_uuid, type)` bo'yicha
borib **butun jadvalni** ko'rardi. **Reproduksiya:** B ijarachi `{"ok":true,"duplicate":true}`
oldi, B1 qoldig'i 10 da qoldi, B2 qatori yaratilmadi.

**Tuzatish:** qidiruv `Branch.company_id` bilan doiralandi + manba/tarkib/maqsad moddiy
mosligi; kirim oyog'i ham kalitni oladi (maqsadni tekshirish shunga tayanadi).
**Migratsiya kerak emas** — `ux_stockmov_client_prod_type` `product_id` orqali allaqachon
ijarachini ajratadi.

### P9-05 — onlayn savdo smena yopilishi bilan poygada · **P0**

3A qulfni qo'shib holat **o'qishini** izchil qildi, lekin **qaror** qo'shmadi. Yopish qulfni
birinchi olsa, savdo CLOSED ni ko'radi-yu baribir bog'lanardi.
**Reproduksiya (haqiqiy PG):** 6 poygadan 1 tasi — smena `expected_cash=0.00` muzlatilgan,
unga **100.00 naqd savdo bog'langan**.

**Tuzatish:** onlayn shoxda bunday smenaga bog'lanmaymiz; qarorni mavjud yo'llar beradi
(`OPEN_SHIFT_REQUIRED`, post-T0 custody, OFF_SHIFT anomaliyasi). Yangi qulf yo'q.

**Adversarial ko'rik mening tuzatishimda teshik topdi:** gard sharti selektor sharti bilan
mos emas edi (`sold_at` yo'q `/sync/push` cheki gardni chetlab o'tardi). Shart endi **bir
marta** hisoblanadi — ajralishi mumkin emas.

### P9-06 — `_lock_candidate_shift` da `populate_existing()` yo'q · **tuzatish qilinmadi**

**Mexanizm TASDIQLANDI** (SQLAlchemy 2.0.52, haqiqiy PG o'lchovi): qulflovchi `select`
identity-map'dagi eski obyektni qaytaradi (`OPEN`), `populate_existing` esa yangisini
(`CLOSED`).

**Lekin oqibat yetib bormaydi:** barcha yozuvchilar tekshirildi — har biri ORM obyektini
qulfdan oldin tashlaydi, identity-map esa **zaif** (`WeakInstanceDict`), shu bois qulf
DB'dan yangi qatorni o'qiydi. Sotuv yo'li bundan tashqari 3A qulfi bilan **ikki qavat**
himoyalangan. `lifecycle.open_shift` obyektni ushlaydi, lekin ishlab chiqarishda
chaqiruvchisi yo'q.

**Qaror:** brief bo'yicha («kuzatiladigan oqibat bo'lmasa kodga tegma») — kod o'zgartirilmadi.
Bir qatorlik tuzatish tayyor va **teskari mutatsiya bilan isbotlangan**: qo'shilsa mexanizm
sinovi XPASS bo'ladi, qolgan 70 test yashil qoladi.

**Zaiflik qaydi:** xavfsizlik axlat yig'ish timingiga tayanadi, kodda yozilgan invariantga
emas. Buni `xfail(strict=True)` sinovi qo'riqlaydi.

### Qo'shimcha — CR2 da o'zim kiritgan regressiya · tuzatildi (CR4)

Komparatorim jamini 0.01 ga, yozuvchi esa **butun som**'ga yaxlitlardi → **tarozida tortilgan
har qanday chek o'z aynan takroridan rad etilardi** (0.525 kg × 7929: saqlangan 4163.00 vs
hisoblangan 4162.73). Kassirga «yozilmadi» deyilardi, holbuki yozilgan edi.
**Tuzatish:** jami o'rniga **qator narxi/chegirmasi** solishtiriladi — yaxlitlash arifmetikasi
butunlay yo'qoladi, narx farqi esa ushlanadi.

---

## 4. Dalillar

### Yangi sinov fayllari (jami 6, barchasi zanjirda)

| Fayl | Nima |
|---|---|
| `tests/test_p9_repair1_contract.py` | 13 — idempotentlik kaliti + 3A qo'riqchilari + filial |
| `tests/test_p9_repair2_contract.py` | 15 — kalit egaligi + moddiy moslik + tarozi regressiyasi |
| `tests/test_p9_repair3_contract.py` | 11 — transfer ijarachi doirasi va konfliktlar |
| `tests/test_p9_repair3_concurrency_pg.py` | 4 — transfer konkurrentligi (haqiqiy PG) |
| `tests/test_p9_repair4_online_race_pg.py` | 11 — yopilish poygasi + 4-parallel + tenant matritsasi (PG) |
| `tests/cash/test_p9_06_stale_shift_lock.py` | 7 + 1 xfail — eskirgan ORM matritsasi (PG) |

### Asl QA sinovlari (dalil sifatida, tanalari o'zgartirilmagan)

| | Holat |
|---|---|
| `qa01` (P9-01) | **QIZIL → YASHIL** |
| `qa02` (P9-02) | `xfail(strict)` — kutilmasi **ega qarori bilan bekor qilindi** |
| `qa03` (P9-03) | **QIZIL → YASHIL** |
| `qa04` (P9-04) | **QIZIL → YASHIL** |

### Yurishlar

| To'plam | Natija |
|---|---|
| **PG: `tests/cash/` to'liq + barcha P9 PG fayllari** | **750 o'tdi, 1 xfail, 1 muhit yiqilishi** |
| PG: 3A egalik/qulf (`test_sale_shift_ownership`) | 16/16 |
| PG: posting + 3A + naqd posting + P9-06 | 79 o'tdi, 1 xfail |
| PG: offline Case C + P9-05 poyga + P9-04 konkurrentlik | 22/22 |
| SQLite: kontraktlar + QA repro + oqimlar | 298 o'tdi, 1 xfail |
| `tsc` (POS/Manager) · `vitest` lug'at | 0 xato · 24/24 |

**Yagona yiqilish — muhit nuqsoni:** `pg_target` fiksturasining `app.initdb` subprocess'i
ulanish uzilishi bilan o'lgan (RAM ~1.2 GB, 800+ yetim postgres). Ayni fayl resurs
bo'shagach **7/7 yashil** bo'ldi — atribusiya shu.

### Mutatsiya isbotlari (hech biri commit qilinmagan)

| Bosqich | Mutatsiya | Natija |
|---|---|---|
| CR2 | egalik/moddiy tekshiruv o'chirildi | 9 QIZIL (3 ijarachilararo + 6 moddiy + qa03), 11 yashil |
| CR3 | ijarachi doirasi o'chirildi | aynan 3 ta ijarachilararo QIZIL, 11 yashil |
| CR4 | P9-05 gardi o'chirildi | `r2`, `r2b` QIZIL, 8 yashil |
| CR4 | eski nomuvofiq shart | aynan `r2c` QIZIL, 10 yashil |
| CR5 | **teskari** — tuzatish qo'shildi | mexanizm sinovi XPASS, 70 yashil |

---

## 5. SIZNING QARORINGIZNI KUTAYOTGAN ISHLAR

### A. P9 doirasida

1. **P9-06 bir qatorlik tuzatishi** — qo'llanilsinmi?
   ```
   posting.py::_lock_candidate_shift (origin shoxi)
   ).with_for_update().execution_options(populate_existing=True))
   ```
   To'g'riligi va xavfsizligi isbotlangan. Hozir zarar yo'q, lekin himoya tasodifiy.

2. **P9 zanjirini main'ga integratsiya** — beshta branch ketma-ket turibdi, hech biri
   merge qilinmagan. `origin/main` `09a2eac` ga siljigan, ya'ni qayta integratsiya kerak.

### B. P9 dan tashqari (audit chiqargan, hali ochiq)

3. **⚠️ KOD REPO PUBLIC** — `gh repo view`: `isPrivate: false`, CLAUDE.md esa «yopiq» deydi.
   Ochiq repoda `savdoos-db-daily/weekly-*` **production DB dump artefaktlari** yotibdi
   (shifrlanmagan `meta.json`/`.sha256` bilan), himoya — staging bilan umumiy bitta parol.
   **Eng yuqori og'irlikdagi ochiq element.**

4. **B4 deploy-gate bypass `origin/main`da ochiq** — P8.1 tuzatgan, lekin merge qilinmagan.
   `vars.STAGING_DEPLOY_ENABLED` yoqilishidan **oldin** merge shart.

---

## 6. OCHIQ TOPILMALAR (kodga tegilmagan)

| ID | Mohiyat | Og'irlik |
|---|---|---|
| **N2** | `close_shift` `cash.shifts` ni qulflashdan OLDIN kutilgan naqdni suratga oladi — parallel leg ikkala yakuniy raqamdan tushib qoladi | P1 |
| **N4** | `cash_op` qulfdan keyin statusni qayta tekshirmaydi (`populate_existing` yo'q) | P1 |
| **N3** | Shift-siz onlayn naqd savdo 3A qulfini umuman olmaydi | P2 |
| **N6** | `create_return` dagi deadlock izohi 3A dan keyin eskirgan | hujjat |
| **N5** | `POST /sales` kalitsiz chekni qabul qiladi | **ataylab** (CR1 qarori) |
| p9[23] | Onlayn smena izlashi filialni solishtirmaydi | P2, bir qatorlik |
| p9[10] | `LATE_SYNC_UNACK` istisnosini o'qiydigan API yo'q | P1 — Case C ni amalda ko'rinmas qiladi |
| p9[9] | `/sync/push` 409 cheksiz retry (backoff/cap yo'q) | P2 |
| — | Dead-letter matni UI'da tarjimasiz (barcha kodlar) | P2, Fayzan kirill UI |
| — | `writeoff` dedup'ida moddiy moslik yo'q | P2, naqsh tayyor |
| — | P&L oy chegarasi: 6 test 2026-10-01 dan doim qizil (sentabr sanasi + `period=month`) — **main'da ham**, P9 bilan bog'liq emas | P2 |

---

## 7. Muhit holati

- **322 ta yetim `postgres` jarayoni**, jami ~1143 s CPU yegan. Bu disk va RAM ni yeb
  turgan asosiy manba (disk yurish davomida 30 GB → 5.7 GB gacha tushgan).
- Yurishlar davomida boshqa sessiya ham PG bilan ishlagan; begona jarayonlarga tegilmagan.
- Tozalashni so'ramasdan bajarmadim — **ruxsat bersangiz tozalayman**.

---

## 8. HUKM

| Element | Hukm |
|---|---|
| P9-01 · P9-02 · P9-03 · P9-04 · P9-05 | ✅ **PASS** |
| P9-06 | ✅ **PASS** (mexanizm tasdiqlangan, oqibat yo'q, tuzatish ega qaroriga) |
| Phase 3A kontrakti | **butun** (PG 16/16) |
| Yakuniy SHA | **`fd2d765`**, tree toza |
| Push / merge / deploy | **YO'Q** |
