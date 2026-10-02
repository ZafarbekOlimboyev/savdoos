# P9 KRITIK TUZATISH 2 — P9-03 IDEMPOTENTLIK KALITINING EGALIGI

**Boshlang'ich SHA:** `e78319de0ba98e468f38fffb995046e614653508` (CR1, tasdiqlangan, tree toza)
**Branch:** `p9-critical-repair-2` · **Worktree:** `.claude/worktrees/p9-repair-2`
**Yakuniy SHA:** `9e5d037ca589829fd564c234c803444e5a1516a1`

Merge YO'Q · push YO'Q · deploy YO'Q.

---

## 1. Reproduksiya (tuzatishdan OLDIN, saqlangan holat)

A va B — **bitta do'konning ikki kassiri**. A `uuid X` bilan 1×100 sotadi; B **ayni
`X`** bilan 3×200 (boshqa tovar, boshqa summa) yuboradi.

| O'lchov | Natija |
|---|---|
| B ning HTTP javobi | **200 OK**, `receipt_no='#1288'`, `id=cdd8a0a2…` — **A NING CHEKI** |
| Bazadagi sotuvlar | **1 ta** (`cashier_id` = A) |
| A ning tovari (p1) | 10 → **9** |
| **B ning tovari (p2)** | **10 da qoldi** — mol ketdi, hisobda yo'q |
| To'lovlar | faqat A ning `cash 100.00`; B ning 600 hech qayerda |
| Onlayn `/sales` yo'li | **ayni xulq** (B ga A ning `id`/`receipt_no`) |
| Boshqa tenant, ayni `X` | **to'qnashuv YO'Q** (o'z cheki, qoldiq 10→9) |

Ya'ni B pulni oldi, tizim «yozildi» dedi, lekin **hech narsa yozilmadi**.

## 2. Aniq ildiz sabab

`app/services/sales.py::_create_sale_once`, 1-qadam:

```python
existing = db.query(Sale).filter(
    Sale.client_uuid == data.client_uuid, Sale.company_id == emp.company_id).first()
if existing:
    return existing          # ← SHARTSIZ
```

**Ishlatilgan identity o'lchamlari — ikkita:** `company_id` + `client_uuid`.
Baza kaliti ham shunday: `ux_sales_company_client_uuid ON sales (company_id, client_uuid)`.

**Tekshirilmagan:** egalik (`cashier_id`) va amalning MAZMUNI. Shu bois kalitni bilgan
har qanday xodim boshqa birovning natijasini «takror» sifatida olardi.

Tenantlararo himoya ishlagan — `company_id` filtri va indeksning kompaniya doirasi
tufayli (reproduksiyada tasdiqlandi).

## 3. Kontrakt

> Idempotentlik kaliti amalni **IDENTIFIKATSIYA** qiladi; u amalning **MAZMUNINI
> o'zgartirish** yoki **boshqa kassirning natijasini olish** huquqini bermaydi.

Bu — o'ylab topilgan yangi model emas: repoda allaqachon ratifikatsiya qilingan
`cashops.replay_answer` + `custody_preview.cash_movement_matches` naqshi (kassa
amallari uchun), ayni kod bilan — `IDEMPOTENCY_KEY_REUSED`.

| Holat | Natija |
|---|---|
| ayni tenant + ayni kassir + ayni mantiqiy chek + ayni kalit | **TAKROR** — mavjud chek |
| boshqa kassir + ayni kalit | **RAD** — A ning cheki BERILMAYDI |
| boshqa tenant + ayni kalit | **to'qnashuv yo'q** (o'zgarishsiz) |
| ayni kassir + ayni kalit, moddiy boshqa payload | **RAD** (jimgina qabul EMAS) |
| kassir boshqa filialga o'tgach ayni chekni qayta yuborsa | **TAKROR** — yangi filialda hech narsa yozilmaydi |

**Moddiy o'lchamlar va NEGA aynan shular:**

| O'lcham | Asos |
|---|---|
| `cashier_id` | Egalik. Autentifikatsiyadan keladi va ayni chekning qayta yuborilishida **o'zgarmaydi** |
| savat `(product_id, qty)` | To'g'ridan-to'g'ri payload'dan → urinishlar orasida siljimaydi |
| to'lov usullari to'plami | Payload'dan |
| **jami** — faqat offline replay'da | U yerda narx payload'dan, jami deterministik. Onlaynda narx **katalogdan** keladi va urinishlar orasida o'zgarishi mumkin → solishtirsak qonuniy qayta urinish **yolg'on rad** bo'lardi |

**Moddiy EMAS:** `sold_at` (klient uni flush paytida qo'yadi), smena (server qayta hal
qiladi — `cash_op_movement` dagi ayni mulohaza), filial (offline chek soatlab navbatda
turib, kassir ko'chirilgandan keyin flush bo'lishi mumkin — rad etsak qonuniy chek
yo'qolardi; takrorda yangi filialda hech narsa **yozilmaydi**, shu bois custody chegarasi
kesilmaydi).

**Holat 400, 409 EMAS** — pretsedentdan ataylab farq. `/sync/push` 409 ni **tranzient**
deb biladi (`retry=True`), bu holat esa qayta urinishda hech qachon o'tmaydi (kalit
abadiy band). 409 bersak chek har 30 soniyada abadiy qayta urinardi va kassir uni
«kutilmoqda» deb ko'rardi. 400 → dead-letter: **ko'rinadigan** rad.

## 4. Kiritilgan o'zgarish

| Fayl | Nima |
|---|---|
| `apps/server/app/services/sales.py` | `_replay_mismatch()` yordamchisi + `KEY_REUSED_TEXT`; dedup shoxida chaqiruv |
| `packages/shared/src/lib/serverErrors.ts` | savdo matni uchun tarjima (ru/uzc) — umumiy naqshdan **oldin**, aks holda «kassa amali» deb tarjima qilinardi |
| `apps/server/tests/test_p9_repair2_contract.py` | YANGI — 13 kontrakt sinovi |
| `apps/server/tests/test_qa_p9_repro.py` | `qa03` dan `xfail` **olib tashlandi** (nuqson tuzatildi) — sinov tanasi o'zgarmagan |

## 5. Sinov dalili

| To'plam | Natija |
|---|---|
| `test_p9_repair2_contract.py` (yangi, 13) | **13/13** |
| `test_qa_p9_repro.py` | `qa01` ✅ · **`qa03` ✅ (QIZIL → YASHIL)** · qa02/qa04 xfail |
| CR1 + CR2 kontrakt + QA birga | **27 o'tdi, 2 xfail** |
| **PG:** 3A egalik/qulf + offline policy PG | **23/23** |
| **PG:** `tests/cash/` butun papka | **722/722** (12 daq 42 s) |
| SQLite fokusli regressiya (13 fayl) | **316 o'tdi, 2 xfail** |
| `npx tsc --noEmit` (POS) | **0 xato** |
| `vitest tests/server-errors-sanitize.test.ts` | **24/24** |

## 6. Mutatsiya isboti

Egalik/moddiy tekshiruv vaqtincha o'chirildi (`_why = None`) — **commit QILINMADI**:

```
9 failed, 6 passed, 2 xfailed
```

**QIZIL bo'lganlar (9):** r3, r4, r5 (boshqa kassir: push/onlayn), r7, r8, r9, r10
(moddiy farq: savat/miqdor/usul/narx), r13 (bitta tanada), **qa03** (asl QA repro).

**YASHIL qolganlar:** r1, r2 (qonuniy takror), r6 (tenantlararo), r11 (filial),
r12 (bitta tanada ayni chek), qa01 — ya'ni sinovlar aynan nuqsonni nishonga oladi,
tasodifiy xulqni emas.

Tiklangandan keyin: **27 o'tdi, 2 xfail** (mutatsiya izsiz olib tashlandi).

## 7. Saqlangan invariantlar

- **P9-01** (bardoshli idempotentlik kaliti) — tegilmagan, sinovi yashil.
- **P9-02** tor filial tuzatishi — tegilmagan, sinovi yashil.
- **Phase 3A** Case C / kech sinxronlash semantikasi, smena qulfi va tartibi —
  tegilmagan (PG 23/23, cash 722/722).
- **Qonuniy takror** — kuchsizlantirilmadi: ayni kassir + ayni savat + ayni usul
  avvalgidek mavjud chekni qaytaradi (r1, r2, r12).
- Yopiq smenaga blanket rad **qo'shilmadi**.

## 8. Ochiq qolgan P9 topilmalari

| ID | Mohiyat | Maqom |
|---|---|---|
| **P9-04** | `_transfer_once` dedup'i tenant-skopsiz va material-matchsiz | OCHIQ (qa04 xfail) |
| **P9-05** | Onlayn savdo vs `close_shift` poygasi (3A qulfi bilan toraygan) | OCHIQ |
| p9[23] | Onlayn smena izlashi filialni solishtirmaydi (`else` shoxi) | OCHIQ, bir qatorlik |
| p9[10] | `LATE_SYNC_UNACK` istisnosini o'qiydigan API yo'q | OCHIQ |
| p9[9] | `/sync/push` 409 cheksiz retry (backoff/cap yo'q) | OCHIQ — bu tuzatish 400 bilan chetlab o'tdi, umumiy muammo qoladi |
| — | Dead-letter matni UI'da tarjimasiz (barcha kodlar) | OCHIQ |

## 9. HUKM

### **P9-03: PASS**

Nuqson reproduksiya qilindi, ildiz sababi aniq ko'rsatildi, ratifikatsiya qilingan
mavjud naqsh bo'yicha tuzatildi, mutatsiya bilan isbotlandi, PG va SQLite regressiyasi
toza.
