# P9 KRITIK TUZATISH 4 — P9-05 ONLAYN SAVDO / YOPILISH POYGASI

**Boshlang'ich SHA:** `43152e62f66100a959a439d09bbaf3ebf1b7147e` (CR3, tasdiqlangan, tree toza)
**Branch:** `p9-critical-repair-4` · **Worktree:** `.claude/worktrees/p9-repair-4`
**Yakuniy SHA:** `0c53888934cf206ae479f29433e5706455bc7f88`
**`origin/main` (alohida tekshirildi):** `09a2eacb45f9936f96f3e4527d40579d4b78a635`

Merge YO'Q · push YO'Q · deploy YO'Q · migratsiya YO'Q · production/staging'ga kirilmadi.

---

## 1. ASL P9-05 TOPILMASI (aynan matn, `qa/binos-independent-security` dan)

> **BINOS-QA-P9-05 · P0 · CONFIRMED_STATIC · main+P9**
> **Smena yopilishi vs parallel savdo.** `close_shift` Shift'ni FOR UPDATE qulflaydi va
> SHIFT-1 izohi «hamma yo'l smenani qulflaydi» deydi — lekin **savdo yo'li
> (`_create_sale_once`) Shift qatorini QULFLAMAYDI va commitdan oldin statusni qayta
> tekshirmaydi**. READ COMMITTED'da: savdo tx smena=open o'qiydi → close tx qulf oladi,
> muzlatadi, commit → savdo tx keyin commit → savdo yopiq smenada, muzlatilgan
> expected'dan tashqarida. … **Minimal tuzatish:** savdo yo'lida smena qatorini
> `FOR NO KEY UPDATE` o'qish **yoki** commit oldidan status qayta-tekshiruv + retry.

Topilma joyida; taxmin bilan qayta talqin qilinmadi.

## 2. Reproduksiya (tuzatishdan OLDIN, haqiqiy PostgreSQL)

`tests/test_p9_repair4_online_race_pg.py`, tuzatishdan oldin: **1 yiqildi, 8 o'tdi**.

```
[1] muzlatilgan expected=0.00 != smenadagi naqd 100.00
```

Saqlangan holat: smena `status=closed`, `expected_cash=0.00` **muzlatilgan**, lekin
o'sha smenaga **100.00 naqd savdo bog'langan** (`Sale.shift_id` = yopiq smena,
`SalePayment` 100.00). Z-hisobot abadiy 100 so'mga xato.

6 poygadan **1 tasi** — ya'ni oyna tor, lekin haqiqiy. Keyin **deterministik** sinov
qo'shildi (`Shift` ustidagi `with_for_update()` dan oldin boshqa tranzaksiyada yopish),
u poygani timing'ga qoldirmaydi.

Boshqa 8 sinov (konkurrent idempotentlik, tenant izolyatsiyasi, 3A Case C) **o'tdi** —
ya'ni zaif yuza aynan yopilish poygasi.

## 3. Ildiz sabab va poyga oynasi

Qulf semantikasi: `sales.py` `SELECT … FOR NO KEY UPDATE` (key_share=True),
`shifts.py::close_shift` `SELECT … FOR UPDATE`. PostgreSQL matritsasida bu ikkisi
**to'qnashadi**, ya'ni tranzaksiyalar ketma-ketlashadi — lekin **ikkala tartib ham**
mumkin:

| Tartib | Natija |
|---|---|
| **A** — savdo qulfni birinchi oladi | yopish kutadi → `SalePayment` ni qulfdan KEYIN o'qiydi → savdo `expected_cash` ga KIRADI ✅ |
| **B** — yopish birinchi oladi | `expected_cash` muzlaydi, commit → savdo qulfni oladi, CLOSED ni **ko'radi** — va baribir bog'lanardi ❌ |
| **C** — yopish savdoning birinchi SELECT'idan oldin tugaydi | `status == open` filtri hech narsa topmaydi → shift-siz yo'l ✅ |
| **D** — yopish SELECT bilan qulf orasida | **B** bilan ayni ❌ |

**Phase 3A nimani yopgan:** qulfni qo'shdi va `populate_existing()` bilan holatni qulf
ostida **qayta o'qishni** ta'minladi — ya'ni eskirgan ORM nusxasi yo'q va o'zaro istisno
bor. **Nima ochiq qolgan:** qulfdan keyin **holat bo'yicha qaror** yo'q edi (3A izohi
buni ochiq aytadi: «HOLAT TALABI QO'SHILMAYDI»).

**Nega boshqa gardlar yetmaydi:** `cutover_guard.reject_closed_shift_replay` faqat
**post-T0** (`enforcement_active`) va faqat **naqd** yo'lidan chaqiriladi. Bugungi
do'kon pre-T0; karta/nasiya cheki post-T0 da ham o'tib ketadi.

## 4. Tuzatish

**Onlayn shoxda**, mavjud qulfdan keyin: agar smena endi ochiq bo'lmasa — unga
bog'lanmaymiz (`shift = None`) va qarorni **mavjud, sinalgan yo'llar** beradi:
`force_shift` yoqiq bo'lsa `OPEN_SHIFT_REQUIRED`, post-T0 da custody gardlari TILL ni
aniq talab qiladi, ledger legi esa **OFF_SHIFT anomaliyasi** bo'lib qayd etiladi.
Jimgina noto'g'ri biriktirish o'rniga ko'rinadigan qaror.

**Yangi qulf qo'shilmadi** — bu allaqachon olingan qulf ostidagi qaror.
**Offline replay shoxiga tegilmadi** — u ataylab yopilgan smenaga bog'lanadi
(3A Case C / LATE_SYNC, ega tomonidan ratifikatsiya qilingan; `test_r9` buni qo'riqlaydi).

### 4b. Adversarial ko'rikda topilgan TESHIK (mening birinchi tuzatishimda)

Fonda yuritilgan mustaqil tahlil (22 agent) ildiz sababni tasdiqladi **va** birinchi
tuzatishimdagi kamchilikni topdi:

- selektor sharti: `honor_price_snapshot and at is not None`
- gard sharti: `not honor_price_snapshot`

`/sync/push` chekining `sold_at` i yo'q yoki oynadan tashqarida bo'lsa `_clamp_sold_at`
**`None`** qaytaradi → `honor_price_snapshot=True` bo'lsa-da **ONLAYN** selektor
tanlanadi, gard esa **chetlab o'tiladi** → poyga aynan shu kirishda ochiq qolardi.

**Tuzatildi:** shart **bir marta** hisoblanadi (`_offline_replay`) va ikkala joyda ayni
o'zgaruvchidan o'qiladi — endi hech qachon ajralmaydi. Sinov: `test_r2c`.

### 4c. O'ZIM KIRITGAN REGRESSIYA (CR2/P9-03) — TUZATILDI

Ayni tahlil CR2 da men kiritgan nuqsonni ham topdi va men uni sinov bilan tasdiqladim:

> yozuvchi jamini **butun som**'ga yaxlitlaydi (`quantize(Decimal("1"))` — naqd som'da
> tiyin yo'q), mening komparatorim esa **0.01** ga yaxlitlardi va qator chegirmalarini
> hisobga olmasdi.

Oqibati: **tarozida tortilgan har qanday chek o'z AYNAN o'sha takroridan rad etilardi**.
O'lchangan: 0.525 kg × 7929 → saqlangan `4163.00`, komparator `4162.73` →
`400 IDEMPOTENCY_KEY_REUSED`. Ya'ni javobi yo'qolgan tarozi cheki qayta yuborilganda
kassirga «yozilmadi» deyilardi, holbuki u **yozilgan** edi — bu aynan P9-01/P9-03
himoya qilmoqchi bo'lgan oqim, va Fayzan biznesining o'zagi (452 tarozi PLU).

**Tuzatildi:** jami qayta hisoblanmaydi; narx **qator darajasida** solishtiriladi
(`SaleItem.unit_price` va `.discount` offline yo'lda payload'dan **aynan** snapshot
qilinadi), ya'ni yaxlitlash arifmetikasi butunlay yo'qoladi, narx farqi esa hamon
ushlanadi. Sinovlar: `test_r10b` (qonuniy takror qabul), `test_r10c` (boshqa narx rad).

## 5. Qulf tartibi tahlili

Global tartib: `public.shifts` → `inventory` (product_id bo'yicha saralangan) →
`customers` → `cash.cash_accounts` → `cash.shifts`. `close_shift` va
`add_cash_movement` ham `public.shifts` dan boshlaydi; teskari yo'nalish topilmadi.

`key_share=True` **kuchsizlantirish emas**: `sales.shift_id` — `shifts(id)` ga FK, ya'ni
`INSERT INTO sales` o'sha qatorga `FOR KEY SHARE` oladi; `FOR UPDATE` bo'lsa savdo
o'zini bloklardi. `FOR NO KEY UPDATE` esa `FOR KEY SHARE` bilan to'qnashmaydi.

**Bu tuzatish yangi qulf qo'shmaydi** → deadlock tavakkali o'zgarmaydi.

## 6. PG konkurrentlik dalili

`tests/test_p9_repair4_online_race_pg.py` — **11/11 o'tdi** (haqiqiy PostgreSQL,
barrier bilan sinxron oqimlar, production sessiya sozlamalari):

| Sinov | Nima tekshiriladi |
|---|---|
| r1 | yopilish poygasi — invariant (A yoki B holati) |
| r2 | ayni poyga **6 marta** (timing har safar boshqa) |
| **r2b** | **deterministik** case B (yopish qulfni majburan birinchi oladi) |
| **r2c** | **`sold_at` yo'q offline chek** ham himoyalangan (shart mosligi) |
| r3 | yopilgandan keyin onlayn savdo yopiq smenani tanlamaydi |
| r4 | **4 parallel ayni UUID/payload** → 1 chek, 1 to'lov, 1 chiqim |
| r5 | 4 parallel ayni UUID, **moddiy boshqa** → deterministik 400 |
| r6 | turli UUID parallel → 4 chek, keraksiz birlashtirish yo'q |
| r7 | ayni tenant, **boshqa kassir**, ayni UUID → 1 yoziladi, 1 rad |
| r8 | **turli tenant**, ayni UUID → ikkalasi yoziladi |
| r9 | **3A Case C qo'riqchisi** — offline replay yopiq smenasiga bog'lanadi |

Deadlock, timeout yoki yutilgan `IntegrityError` kuzatilmadi.

## 7. Regressiya

| To'plam | Natija |
|---|---|
| P9-05 poyga fayli (PG) | **11/11** |
| CR1+CR2+CR3 kontrakt + QA repro + SQLite batareya (12 fayl) | **298 o'tdi, 1 xfail** |
| PG: 3A egalik/qulf + offline policy + naqd posting + CR3 konkurrentlik | **93/93** |
| PG: `tests/cash/` to'liq + barcha P9 PG fayllari | **744/744** (20 daq 53 s) |
| `tsc`/`vitest` | **kerak emas** — bu bosqichda frontend mapping'ga TEGILMADI |

**Oldindan mavjud yiqilish (meniki emas):** `test_cost_provenance.py` da 4 ta test.
Atribusiya: **toza `43152e6` da ham aynan o'sha 4 tasi yiqiladi** → mening
o'zgarishimga aloqasi yo'q. Bu hujjatlangan «yarim tun tuzog'i» sinfi (hisobot testlari
vaqt/mintaqaga bog'liq).

## 8. Mutatsiya isboti

**Mutatsiya 1** — P9-05 holat qarori butunlay o'chirildi:
`2 failed, 8 passed` — **r2** (probabilistik) va **r2b** (deterministik) QIZIL,
qolgan 8 tasi yashil.
Deterministik xabar: *«MUZLATILGAN SMENAGA BOG'LANDI: 1 ta savdo, naqdi 100.00,
muzlatilgan expected_cash=0.00»*.

**Mutatsiya 2** — shart eski, nomuvofiq holiga qaytarildi (`not honor_price_snapshot`):
`1 failed, 10 passed` — aynan **r2c** QIZIL, ya'ni sinov teshikni **aniq** nishonga oladi.

Ikkala mutatsiya ham **commit QILINMADI**; tiklangandan keyin **11/11**.

## 9. O'zgargan fayllar

| Fayl | Nima |
|---|---|
| `apps/server/app/services/sales.py` | P9-05 holat qarori (onlayn shox) · `_offline_replay` yagona shart · `_replay_mismatch` da jami o'rniga qator narxi/chegirmasi |
| `apps/server/tests/test_p9_repair4_online_race_pg.py` | YANGI (11, PG) |
| `apps/server/tests/test_p9_repair2_contract.py` | +2 regressiya sinovi (tarozi takrori) |

## 10. Saqlangan invariantlar

Phase 3A Case C kech sinxronlash · `public.shifts` qulf tartibi · P9-01 · P9-02 · P9-03
· P9-04 · qonuniy takror xulqi · tenant izolyatsiyasi — **hammasi yashil**
(298 SQLite + 93 PG + 11 poyga).

## 11. Ochiq qolgan P9 topilmalari

| ID | Mohiyat | Maqom |
|---|---|---|
| p9[23] | Onlayn smena izlashi filialni solishtirmaydi | OCHIQ (doiradan tashqari) |
| p9[10] | `LATE_SYNC_UNACK` istisnosini o'qiydigan API yo'q | OCHIQ (doiradan tashqari) |
| p9[9] | `/sync/push` 409 cheksiz retry | OCHIQ (doiradan tashqari) |
| — | Dead-letter matni UI'da tarjimasiz | OCHIQ (doiradan tashqari) |

### YANGI topilmalar (bu ko'rikda chiqdi, KODIGA TEGILMADI)

| # | Mohiyat | Dalil |
|---|---|---|
| N1 | **`posting._lock_candidate_shift` da `populate_existing()` yo'q** — qulfdan keyin eskirgan identity-map nusxasi o'qiladi va ON_SHIFT leg yopilgan cash-smenaga tushadi | CONFIRMED_STATIC (bu — asl **P9-06**) |
| N2 | **`close_shift` `cash.shifts` ni qulflashdan OLDIN kutilgan naqdni suratga oladi** — parallel till-doirasidagi leg ikkala yakuniy raqamdan ham tushib qoladi | CONFIRMED_STATIC |
| N3 | **Shift-siz onlayn naqd savdo 3A qulfini umuman olmaydi** — ledger smenani o'zi hal qiladi va yopilish bilan poygaga kiradi | CONFIRMED_STATIC (P2) |
| N4 | **`cash_op` qulfdan keyin statusni qayta tekshirmaydi** (`populate_existing()` yo'q) — yopilgan smenaga naqd harakat yozilishi mumkin | CONFIRMED_STATIC |
| N5 | **`POST /sales` `client_uuid` siz chekni qabul qiladi** — onlayn savdoda idempotentlik kaliti ham, DB to'sig'i ham yo'q | CONFIRMED_STATIC; **ataylab** (CR1 brifi: «onlayn semantikani o'zgartirma») |
| N6 | `create_return` dagi deadlock-xavfsizlik izohi 3A dan keyin **eskirgan** | CONFIRMED_STATIC (hujjat nuqsoni) |

## 12. WRITE-OFF TOPILMASI (backlog, kodiga tegilmadi)

**`POST /inventory/writeoff` dedup'ida MODDIY MOSLIK YO'Q.**

Dedup kaliti `(client_uuid, product_id, type=writeoff)` — ijarachi doirasi to'g'ri
(`product_id` orqali), lekin **miqdor solishtirilmaydi**. Ayni kalit boshqa `qty` bilan
kelsa, javob jimgina `{"ok": true, "duplicate": true}` bo'ladi va **yangi hisobdan
chiqarish bajarilmaydi** — xuddi P9-03/P9-04 dagi sinf, faqat tor.

P9-04 davomida topildi, P9-05 doirasiga kirmaydi. **Kodiga tegilmadi.**
Tuzatish naqshi tayyor: `cashops._transfer_replay_mismatch` bilan ayni.

## 13. HUKM

### **P9-05: PASS**

Asl topilma topildi va aynan o'qildi; haqiqiy PostgreSQL'da reproduksiya qilindi
(probabilistik va deterministik); ildiz sabab hamda 3A nimani yopgani aniq ajratildi;
eng kichik tuzatish qo'llandi (yangi qulf yo'q, migratsiya yo'q); mustaqil adversarial
ko'rik tuzatishning o'zidagi teshikni topdi va u ham yopildi; ikki mutatsiya bilan
isbotlandi.

**Qo'shimcha:** shu ko'rik davomida o'zim CR2 da kiritgan regressiya (tarozi chekining
qonuniy takrori rad etilishi) topildi, sinov bilan tasdiqlandi va tuzatildi. Bu P9-05
doirasidan tashqarida edi, lekin bu sessiyada men kiritgan nuqson bo'lgani uchun uni
ochiq qoldirish to'g'ri bo'lmasdi.
