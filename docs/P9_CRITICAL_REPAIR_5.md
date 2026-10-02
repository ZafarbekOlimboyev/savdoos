# P9 KRITIK TUZATISH 5 — P9-06 `_lock_candidate_shift` ESKIRGAN IDENTITY-MAP

**Boshlang'ich SHA:** `e0eeefa7b2bfcf0dd43da9c1715cce068c7ad44d` (CR4, P9-05 PASS)
**`origin/main` (faqat o'qildi):** `09a2eacb45f9936f96f3e4527d40579d4b78a635`
**Worktree / branch:** `.claude/worktrees/p9-repair-5` · `p9-critical-repair-5`
**Yakuniy SHA:** `ed3dceafd52350ab235f6ecafe9d12fdc8d3379f` · tree toza · birinchi commit ota-si AYNAN `e0eeefa` (tasdiqlangan)

Push YO'Q · merge YO'Q · deploy YO'Q · config/secret o'zgarishi YO'Q · force push YO'Q.

---

## 1. Asl P9-06 topilmasi (aynan matn)

QA hisobotidan (`qa/binos-independent-security`):

> **P9-06** (`posting.py::_lock_candidate_shift`) — qulfdan keyin status QAYTA O'QILMAYDI
> (identity-map eski qiymat) → ON_SHIFT leg YOPIQ cash-smenaga; LATE_SYNC aylanib o'tiladi.

Xom topilma yozuvidan (hujum stsenariysi va dalil):

> «`posting.py:294-298` (origin shoxi): `select(CashShift)...with_for_update()` — `populate_existing`
> yo'q, `db.refresh` yo'q… Natija: yopilgan smenada o'zining muzlatilgan yarashtirish
> snapshotiga KIRMAYDIGAN `ON_SHIFT` legi, istisno qatori YO'Q, yozuv o'zgarmas…
> Izoh: origin'siz shox (`posting.py:300-305`) TASODIFAN xavfsiz, chunki `status` WHERE
> ichida va EvalPlanQual uni qayta baholaydi; faqat `origin_shift_id` shoxi zarar ko'radi.»

P9-05 xulosasi ko'chirilmadi — reachability 3A va P9-05 dan keyin **qaytadan** o'rganildi.

## 2. Runtime kontrakti (o'lchangan, taxmin emas)

Qaror maydoni — `_resolve_shift` dagi **`cand.status`**:

| `cand.status` | Natija |
|---|---|
| `OPEN` + oynada | `ON_SHIFT`, anomaliyasiz (Case A) |
| `CLOSED` + oynada | `LATE_SYNC` + **`LATE_SYNC_UNACK`** (Case C) |

Qolgan ta'sir qiluvchi maydonlar: `cand.cash_account_id` (egalik — `SHIFT_NOT_BELONG_TO_ACCOUNT`),
`cand.opened_at` (oyna), `tenant_id` (qulf so'rovining o'zida).

**SQLAlchemy xulqi — ajratib o'lchandi (SQLAlchemy 2.0.52, haqiqiy PG):**

```
1) A sessiyasi yukladi      : OPEN     | identity-map'da: True
2) B sessiyasi yopdi+commit : DB'da -> CLOSED
3) A qulfdan keyin o'qidi   : OPEN     | AYNI obyekt: True     ← ESKIRGAN
4) populate_existing bilan  : CLOSED                            ← yangi
```

Ya'ni **SQL qulfi to'g'ri olinadi, lekin ORM atributlari yangilanmaydi**. Mexanizm
TASDIQLANDI.

## 3. Tuzatishdan OLDIN deterministik reproduksiya (haqiqiy PostgreSQL)

`tests/cash/test_p9_06_stale_shift_lock.py` — hook bilan deterministik (timing lotereyasi yo'q):
`_lock_candidate_shift` chaqirilishidan AYNAN oldin boshqa tranzaksiya smenani yopib commit qiladi.

Brief talab qilgan matritsa:

| | Stsenariy | Natija |
|---|---|---|
| **A** | eskirgan status — naqd qarz to'lovi (`public.shifts` QULFSIZ yo'l) | **LATE_SYNC + LATE_SYNC_UNACK** — ya'ni nuqson YUZ BERMADI |
| **B** | egalik — begona kassaning smenasi | RAD (fail-closed) ✓ |
| **C** | normal ochiq smena | `ON_SHIFT` ✓ |
| **C2** | oldindan yopilgan smena | `OFF_SHIFT` + `UNRESOLVED_OFF_SHIFT` ✓ |
| **D** | origin'siz shox + konkurrent yopilish | `OFF_SHIFT` (EvalPlanQual) ✓ |
| **E** | ijarachi izolyatsiyasi | begona tenant smenasi qulflanmaydi ✓ |
| **F** | P9-05/3A bilan o'zaro ta'sir — sotuv yo'li | `ON_SHIFT`, o'z smenasiga ✓ |

**7/7 o'tdi.** Ya'ni **nuqson hech bir yo'lda reproduksiya BO'LMADI.**

### Nega reproduksiya bo'lmadi — o'lchangan sabab

Identity-map'ni har qadamda kuzatdim:

```
[1] open_shift_for_account dan KEYIN map: [('b000d401', 'OPEN')]
[2] _lock_account dan OLDIN       map: []          ← obyekt YO'QOLGAN
    _lock_candidate_shift -> cand.status: CLOSED   ← to'g'ri o'qildi
```

**Sabab:** SQLAlchemy identity-map — **`WeakInstanceDict`**. `_open_cash_shift_id` faqat
`sh.id` ni qaytaradi (`return sh.id if sh is not None else None`), ORM obyektiga **kuchli
havola qolmaydi** va u darhol yig'ib yuboriladi. Qulf so'rovi bo'sh map'ga tushadi va
DB'dan **yangi** qatorni o'qiydi.

## 4. Reachability — barcha yozuvchilar bo'yicha

`origin_shift_id` beradigan HAR BIR ishlab chiqarish yo'li tekshirildi:

| Yozuvchi | `public.shifts` qulfi | ORM obyekti ushlanadimi | Xulosa |
|---|---|---|---|
| `on_cash_sale` (sales.py) | **HA** (3A, `FOR NO KEY UPDATE`) | yo'q | **IKKI qavat himoya** |
| `on_cash_op` (cashops/shifts) | HA | yo'q | himoyalangan |
| `on_cash_refund` (create_return) | HA | yo'q | himoyalangan |
| `on_debt_payment` (customers.py) | **YO'Q** | yo'q (GC) | nuqson yuz bermaydi |
| `on_supplier_payment` / `on_cash_purchase` / `on_purchase_return` / `on_cash_purchase_increase` | **YO'Q** | yo'q (GC) | nuqson yuz bermaydi |
| `on_shift_open` | — | **HA** (yangi yaratilgan) | xavf yo'q: smena shu tranzaksiyada tug'ilgan, boshqa hech kim yopa olmaydi |
| `lifecycle.open_shift` (obyektni USHLAB post qiladi) | — | **HA** | **ishlab chiqarishda chaqiruvchisi YO'Q** (faqat testlar) |

**3A qulfi haqida muhim aniqlik:** asl topilma `on_cash_sale` ni nishon qilgan edi, lekin
Phase 3A dan beri sotuv yo'li `public.shifts` ni `FOR NO KEY UPDATE` bilan qulflaydi va
`close_shift` ayni qatorni `FOR UPDATE` bilan oladi — ular to'qnashadi, ya'ni yopish sotuv
qulfni ushlab turganda **commit qila olmaydi** va eskirish oynasi umuman ochilmaydi.

## 5. Biznes oqibati

**Bugungi holatda — YO'Q.** Kuzatiladigan yaxlitlik oqibati topilmadi.

Agar mexanizm yuz bersa (quyidagi zaiflik bo'limiga qarang), oqibat shunday bo'lardi:
yopilgan va yarashtirilgan smenaga **anomaliyasiz `ON_SHIFT`** legi tushadi, `trg_cle_immutable`
uni abadiy muzlatadi, `LATE_SYNC_UNACK` istisnosi yozilmaydi — ya'ni avtoritet kutilgan-naqd
manbai yarashtirish yozuvidan doimiy farq qiladi va buni **hech narsa bayroqlamaydi**.

## 6. Ildiz sabab

`populate_existing()` yo'qligi — mexanizm, **ildiz sabab emas**. To'liq shakli:

> `_lock_candidate_shift` SQL qulfini oladi, lekin ORM holatini yangilamaydi; qaror esa
> `cand.status` ga tayanadi. Bugun bu zarar keltirmaydi, chunki **hech bir chaqiruvchi
> yuklangan `CashShift` obyektiga havola saqlamaydi** va identity-map ZAIF — ya'ni
> xavfsizlik **axlat yig'ish (GC) timingiga** tayanadi, kodda yozilgan invariantga emas.

Moliyaviy kod uchun bu xususiyat emas, **tasodif**.

## 7. Qaror: TUZATISH QILINMADI

Brief: «Agar bug real writerga yetib bormasa — kodni o'zgartirma va sababini isbotla» va
«observable integrity consequence ko'rsat». Kuzatiladigan oqibat **yo'q**, shu bois
**ishlab chiqarish kodi o'zgartirilmadi** (`git diff -- apps/server/app/` → bo'sh).

### Tayyor bir qatorlik tuzatish (ega qaroriga)

```python
# apps/server/app/services/cash/posting.py::_lock_candidate_shift  (origin shoxi)
).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
```

U P9-3A/P9-05 naqshiga aynan mos (qulflangan qatorni DB'dagi yangi holat bilan o'qish),
yangi qulf tartibi yaratmaydi, tranzaksiya chegarasini kengaytirmaydi.

## 8. Mutatsiya isboti (TESKARI — tuzatish yo'qligi uchun)

Tuzatish bo'lmagani uchun klassik mutatsiya o'rniga teskarisi bajarildi: yuqoridagi bir
qatorlik tuzatish **vaqtincha** qo'shildi.

```
1 failed, 70 passed
FAILED ...::test_g_MEXANIZM...  [XPASS(strict)]
```

Ya'ni: (a) mexanizm sinovi **aynan** shu o'zgarishga sezgir (XPASS bo'ldi), (b) tuzatish
`test_posting_service` va `test_sale_shift_ownership` ning **70 ta sinovini buzmaydi**.
Mutatsiya **commit qilinmadi**; tiklangandan keyin ishlab chiqarish kodi o'zgarmagan.

## 9. Doimiy qayd — mexanizm sinovi

`test_g_MEXANIZM_kuchli_havola_bolsa_qulf_ESKIRGAN_obyekt_qaytaradi` —
**`xfail(strict=True)`**. U kuchli havola saqlanganda qulf eskirgan obyekt qaytarishini
ko'rsatadi. `populate_existing` qo'shilsa **XPASS** bo'ladi va marker olib tashlanishi
kerakligini o'zi aytadi. Ya'ni holat kodda qayd etilgan, suite esa yashil.

## 10. ZAIFLIK (yangi topilma, kodga tegilmadi)

Himoya **ikki tasodifga** tayanadi:
1. hech bir chaqiruvchi yuklangan `CashShift` ga havola saqlamasligi;
2. identity-map zaifligi + CPython ning darhol yig'ishi.

Bitta kelajakdagi o'zgarish buni jimgina buzadi — masalan `sh.id` o'rniga `sh` ni uzatish,
obyektni jurnalga yozish, yoki `lifecycle.open_shift` ga API chaqiruvchi qo'shilishi (u
allaqachon obyektni ushlab `origin_shift_id=sh.id` bilan post qiladi). Hech qanday sinov
yoki izoh bu invariantni hozir qo'riqlamaydi — `test_g` dan tashqari.

## 11. Regressiya

| To'plam | Natija |
|---|---|
| `tests/cash/test_p9_06_stale_shift_lock.py` (YANGI, 8) | **7 o'tdi, 1 xfail** |
| PG: `test_posting_service` + `test_sale_shift_ownership` (3A) + `test_sale_cash_posting` + P9-06 | **79 o'tdi, 1 xfail** |
| PG: offline policy (Case C) + P9-05 poyga + P9-04 konkurrentlik | **22/22** |
| SQLite: CR1/CR2/CR3 kontraktlari + QA repro + offline policy + custody | **92 o'tdi, 1 xfail** |
| Ishlab chiqarish kodi diff (`e0eeefa`..HEAD) | **bo'sh** |

**`tests/cash/` TO'LIQ to'plami — YURITILDI va natijasi tiklandi.**

Yurish 14:13 da ishga tushirilgan, 26 daq 34 s da tugagan, lekin sessiya natija qaydidan
OLDIN uzilgan (fon vazifasi «ishlayapdi» holatida qolib ketgan). Chiqish fayli saqlanib
qolgan va o'qildi:

```
1 failed, 750 passed, 1 xfailed in 1594.42s (0:26:34)
FAILED tests/test_offline_shift_policy_pg.py::test_pre_t0_smenasiz_ALLOWED[pgserver]
```

**Yagona yiqilish — MUHIT nuqsoni, kod nuqsoni EMAS.** U `pg_target` fiksturasida
(`tests/test_check_defs_pg.py:81`): fikstura `python -m app.initdb` ni subprocess sifatida
yuritadi va `returncode == 0` ni talab qiladi; subprocess esa SQLAlchemy `e3q8` xatosi bilan
yiqilgan — *«terminated abnormally before or while processing the request»*, ya'ni pgserver
backend'i ulanishni uzib yuborgan. O'sha paytda mashinada **RAM ~1.2 GB bo'sh va 800+ yetim
`postgres` jarayoni** bor edi.

**Atribusiya isboti:** AYNI fayl keyinroq (resurs bo'shagach) qayta yuritildi va
**7/7 yashil** bo'ldi — yuqoridagi «offline Case C + P9-05 + P9-04» qatoridagi 22/22 ning
ichida. Ya'ni yiqilish takrorlanmaydi va kodga aloqasi yo'q.

## 12. Aloqasiz yiqilishlar atribusiyasi

Bu yurishda `test_cost_provenance` **ishga tushirilmadi**. Uning baseline yiqilishi
(CR4 da o'lchangan, toza `43152e6` da ham aynan takrorlangan) **P9 bilan bog'liq emas** va
bu branchda tuzatilmaydi. Kanonik atribusiya: **qattiq kodlangan sentabr sanalari +
`period=month` joriy-oy kalendar chegarasi nuqsoni**.

Shuningdek, o'z sinov fiksturamda ayni sinfdagi xatoni topdim va tuzatdim: qattiq kodlangan
`NOW` sababli `device_occurred_at` smena oynasidan tashqarida qolib, har post Case B
(`TIMESTAMP_OUT_OF_WINDOW`) bo'lib ketardi va sinov tekshirmoqchi bo'lgan shoxga yetib
bormasdi. Nazorat sinovi (`test_c`) buni ushladi.

## 13. O'zgargan fayllar

| Fayl | Nima |
|---|---|
| `apps/server/tests/cash/test_p9_06_stale_shift_lock.py` | **YANGI** — 7 xulq sinovi + 1 mexanizm xfail |
| `apps/server/app/**` | **O'ZGARMAGAN** |

## 14. HUKM

### **P9-06: PASS (mexanizm tasdiqlandi, oqibat yetib bormaydi — tuzatish qilinmadi)**

- Mexanizm **TASDIQLANDI** (runtime o'lchovi bilan).
- Kuzatiladigan yaxlitlik oqibati **YO'Q** — barcha yozuvchilar tekshirildi.
- Sotuv yo'li 3A qulfi bilan **ikki qavat** himoyalangan.
- Himoya **tasodifiy** — bu zaiflik sifatida qayd etildi va `xfail` sinovi bilan qo'riqlanadi.
- Bir qatorlik tuzatish tayyor, to'g'riligi va xavfsizligi isbotlangan — **ega qaroriga**.
