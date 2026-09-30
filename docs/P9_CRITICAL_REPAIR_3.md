# P9 KRITIK TUZATISH 3 — P9-04 KO'CHIRISH KALITINING IJARACHI DOIRASI

**Boshlang'ich SHA:** `115c85e6e6cf135822fbaf325ca61e73092062a2` (CR2, tasdiqlangan, tree toza)
**Branch:** `p9-critical-repair-3` · **Worktree:** `.claude/worktrees/p9-repair-3`
**Yakuniy SHA:** `f14755754fd3fa047ed0c8a821d733546e08579c`
**`origin/main` (alohida tekshirildi):** `09a2eacb45f9936f96f3e4527d40579d4b78a635` — siljigan (avval `e60c213a`)

Merge YO'Q · push YO'Q · deploy YO'Q · migratsiya YO'Q.

---

## 1. Reproduksiya (tuzatishdan OLDIN, saqlangan holat)

**Ijarachi A:** `uuid X`, A1→A2, pA ×2 · **Ijarachi B:** **ayni `X`**, B1→B2, pB ×5
(haqiqiy, mustaqil ko'chirish).

| O'lchov | Natija |
|---|---|
| B ning javobi | **200 OK, `{"ok": true, "duplicate": true}`** |
| B ning `stock_movements` qatorlari | **YO'Q** |
| B1 (manba) | **10.0 da qoldi** (kutilgan 5.0) |
| B2 (maqsad) | **qatori umuman yaratilmagan** |
| A ning ko'chirishi | to'g'ri bajarilgan (A1 8.0, A2 2.0) |

**Ikkinchi qirra** (ayni ijarachi, ayni kalit, `qty` 1 → 7):
javob **`{"ok": true, "duplicate": true}`**, A1 7.0 da qoldi — 7 donalik ko'chirish
umuman bo'lmadi, lekin muvaffaqiyat deb ko'rsatildi.

Audit izi: ko'chirishning yagona izi `stock_movements` (alohida audit jadvali yo'q).
`transfer_in` qatori `client_uuid=None` bilan yozilgan — ya'ni **maqsad filialni kalit
orqali tekshirib bo'lmasdi**.

## 2. Aniq ildiz sabab

`app/api/v1/cashops.py::_transfer_once`:

```python
ex = db.query(StockMovement).filter(
    StockMovement.client_uuid == data.client_uuid,
    StockMovement.type == MovementType.transfer_out).first()
if ex:
    return {"ok": True, "duplicate": True}
```

- **Qidiruv ustunlari:** `client_uuid` + `type`. Boshqa hech narsa.
- **`company_id`/`tenant_id` YO'Q** — va `stock_movements` jadvalida bunday ustun
  umuman mavjud emas. Filtr butun jadvalni ko'rardi.
- **Moddiy moslik yo'q** — manba, maqsad, tarkib, miqdor solishtirilmasdi.
- **Tranzaksiya chegarasi:** dedup `_transfer_once` boshida, `db.commit()` esa oxirida;
  tashqi `transfer()` o'rami `IntegrityError` da 3 marta qayta uradi.
- **Parallel takror:** SELECT hech narsa topmasa ikkala oqim ham INSERT ga boradi;
  ularni baza indeksi to'xtatadi → `IntegrityError` → retry → keyingi urinishda dedup
  commit bo'lgan qatorni topadi. Ya'ni ayni ijarachi uchun mexanizm **ishlagan**;
  buzilgani — **ijarachi chegarasi**.

### Baza noyobligi (muhim: migratsiya kerak emas)

```sql
ux_stockmov_client_prod_type
  ON stock_movements (client_uuid, product_id, type) WHERE client_uuid IS NOT NULL
```

`product_id` kaliti ichida — mahsulot esa **bitta kompaniyaga** tegishli. Demak indeks
ijarachilarni **tranzitiv ajratadi**: A va B ning mahsulotlari boshqa, to'qnashuv yo'q.
Reproduksiya buni tasdiqladi: baza B ning yozuvini to'smasdi — uni **ilova qidiruvi**
to'sdi. **Nuqson faqat ilovada edi; sxema o'zgartirilmadi.**

Ayni nuqson sinfi `POST /inventory/writeoff` da **allaqachon tuzatilgan** va izohi uni
so'zma-so'z tasvirlaydi («…BOSHQA do'konning ayni `client_uuid`'i bu amalni jimgina
«dublikat» qilib yutib yuborardi…»). Ko'chirish yo'li o'tkazib yuborilgan edi.

## 3. Kontrakt

| Holat | Natija |
|---|---|
| ayni ijarachi + ayni kalit + ayni mantiqiy ko'chirish | **TAKROR** (`duplicate: true`) |
| boshqa ijarachi + ayni kalit | **mutlaqo alohida ko'chirish** |
| ayni ijarachi + ayni kalit + moddiy boshqa | **409 `IDEMPOTENCY_KEY_REUSED`**, hech narsa yozilmaydi |
| manba / maqsad / tarkib / miqdor farqi | **konflikt** |

Moddiy o'lchamlar: **manba filial** (`transfer_out.branch_id`), **tarkib**
`(product_id → qty)`, **maqsad filial** (kirim oyog'i orqali).

409 — `cashops.replay_answer` pretsedenti bilan **aynan bir xil** (bu marshrut to'g'ridan-
to'g'ri API, sotuvdagi kabi outbox retry muammosi yo'q; shu bois P9-03 dagi 400 dan farqli).

## 4. Tanlangan tuzatish

1. **Qidiruv ijarachi doirasiga olindi** — `Branch.company_id == emp.company_id` join.
   (`product_id` orqali tranzitiv emas, **aniq** — ko'chirish ko'p mahsulotli bo'lishi
   mumkin, ya'ni bitta `product_id` kaliti yetarli emas.)
2. **`_transfer_replay_mismatch()`** — manba/tarkib/maqsad moslik tekshiruvi.
3. **Kirim oyog'i ham `client_uuid` oladi** — maqsadni kalit orqali tekshirish shunga
   tayanadi; qo'shimcha foyda: kirim oyog'i ham endi `ux_stockmov_client_prod_type`
   himoyasida (`type` kalit ichida, shu bois chiqim oyog'iga zid emas).
   ⚠️ Eski (tuzatishdan oldingi) ko'chirishlarda kirim oyog'ida kalit yo'q — u holda
   maqsad **solishtirilmaydi** (isbot yo'q, taxmin qilmaymiz); yangi ko'chirishlar uchun
   tekshiruv to'liq yopiq.
4. Klient tarjimasi (`serverErrors.ts`) — ko'chirish matni uchun alohida yozuv; aks holda
   umumiy naqsh uni «kassa amali» deb tarjima qilardi.

## 5. Konkurrentlik dalili (haqiqiy PostgreSQL)

`tests/test_p9_repair3_concurrency_pg.py` — **4/4 o'tdi**. Barrier bilan sinxron oqimlar,
production sessiya sozlamalari (`autoflush=False, expire_on_commit=False`).

| Sinov | Natija |
|---|---|
| **4 parallel, ayni ijarachi, ayni kalit** | qoldiq **aynan bir marta** (100→98 / 0→2); `transfer_out`=1, `transfer_in`=1; **aynan 1 ta** ASL javob, 3 tasi takror |
| **2 ijarachi parallel, ayni kalit** | **ikki mustaqil ta'sir** (A: 97/3, B: 93/7), har birida 1+1 harakat |
| **ayni kalit, boshqa miqdor** | **deterministik** 409 — ketma-ket ham, 3 parallel ham; qoldiq faqat birinchisidan |
| **aralash parallel** (2 ayni + 2 boshqa) | bitta ko'chirish bajariladi, qolganlari takror yoki 409; qoldiq bir marta siljiydi |

SELECT-ga yolg'iz tayanilmagan: yakuniy kafolat — `ux_stockmov_client_prod_type` +
`IntegrityError` retry o'rami; yuqoridagi sinovlar aynan shu birikmani o'lchaydi.

## 6. Sinovlar

| To'plam | Natija |
|---|---|
| `test_p9_repair3_contract.py` (YANGI, 11) | **11/11** |
| `test_p9_repair3_concurrency_pg.py` (YANGI, 4, haqiqiy PG) | **4/4** |
| QA repro — **`qa04` QIZIL → YASHIL** (xfail olib tashlandi) | qa01 ✅ qa03 ✅ qa04 ✅ · qa02 xfail |
| CR1+CR2+CR3 kontrakt + QA birga | **39 o'tdi, 1 xfail** |
| SQLite fokusli regressiya (11 fayl) | **255 o'tdi, 1 xfail** |
| `tests/cash/` PG + konkurrentlik fayli (bilvosita ta'sir) | **726/726** (20 daq 28 s) |
| `npx tsc --noEmit` (POS va Manager) | tegilgan faylga oid **0 xato** (15 ta xato — `electron/*.ts`, paket o'rnatilmagani sabab, o'zgarishga aloqasi yo'q) |
| `vitest server-errors-sanitize` | **24/24** |
| `package-lock.json` drift | **yo'q** (commit qilinmadi) |

## 7. Mutatsiya isboti

Ijarachiga ko'r qidiruv vaqtincha tiklandi — **commit QILINMADI**:

```
3 failed, 11 passed, 1 xfailed
```

**QIZIL bo'lganlar (aynan ijarachilararo):** `t3_boshqa_ijarachi_ayni_kalit_ALOHIDA_kochirish`,
`t4_ikkala_ijarachi_ham_OZ_audit_iziga_ega`, **`qa04`** (asl QA repro).
**YASHIL qolganlar (11):** qonuniy takror, bir-marta-ta'sir, moddiy konfliktlar
(miqdor/mahsulot/manba/maqsad), ko'p mahsulotli, kalitsiz ko'chirish.

Ya'ni sinovlar aynan ijarachi izolyatsiyasini nishonga oladi. Tiklangandan keyin:
**39 o'tdi, 1 xfail**.

## 8. O'zgargan fayllar

| Fayl | Nima |
|---|---|
| `apps/server/app/api/v1/cashops.py` | ijarachi doirasi + `_transfer_replay_mismatch()` + `TRANSFER_KEY_REUSED_TEXT` + kirim oyog'iga `client_uuid` |
| `packages/shared/src/lib/serverErrors.ts` | ko'chirish uchun ru/uzc tarjima |
| `apps/server/tests/test_p9_repair3_contract.py` | YANGI (11) |
| `apps/server/tests/test_p9_repair3_concurrency_pg.py` | YANGI (4, PG) |
| `apps/server/tests/test_qa_p9_repro.py` | `qa04` dan `xfail` olib tashlandi (tanasi o'zgarmagan) |

## 9. Saqlangan invariantlar

Phase 3A · P9-01 · P9-02 · P9-03 · Case C kech sinxronlash · smena qulfi va tartibi ·
qonuniy takror xulqi — **hammasi tegilmagan** (39 kontrakt sinovi va 255 regressiya
yashil; PG 3A to'plami CR2 da 23/23 edi va bu o'zgarish sotuv yo'liga tegmaydi).

## 10. Ochiq qolgan P9 topilmalari

| ID | Mohiyat | Maqom |
|---|---|---|
| **P9-05** | Onlayn savdo vs `close_shift` poygasi (3A qulfi bilan toraygan) | OCHIQ |
| p9[23] | Onlayn smena izlashi filialni solishtirmaydi | OCHIQ, bir qatorlik |
| p9[10] | `LATE_SYNC_UNACK` istisnosini o'qiydigan API yo'q | OCHIQ |
| p9[9] | `/sync/push` 409 cheksiz retry (backoff/cap yo'q) | OCHIQ |
| — | Dead-letter matni UI'da tarjimasiz | OCHIQ |
| — | `writeoff` dedup'ida moddiy moslik yo'q (ayni kalit, boshqa miqdor → jim «dublikat») | **YANGI kuzatuv**, doiradan tashqari |

## 11. HUKM

### **P9-04: PASS**

Reproduksiya qilindi (ikki qirra bilan), ildiz sabab aniq ko'rsatildi, baza noyobligi
tekshirilib **migratsiya kerak emasligi** isbotlandi, repodagi mavjud pretsedent bo'yicha
tuzatildi, haqiqiy PostgreSQL'da konkurrentlik o'lchandi, mutatsiya bilan isbotlandi.
