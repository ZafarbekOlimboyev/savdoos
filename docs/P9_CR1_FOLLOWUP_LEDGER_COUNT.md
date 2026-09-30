# P9 KRITIK TUZATISH 1 — QO'SHIMCHA TEKSHIRUV

**Mavzu:** oldindan qizil PG sinovi
`test_post_t0_ochiq_smena_replay_QABUL_va_ledgerga_YOZILADI`
**Boshlang'ich:** HEAD `73e2fc0`, worktree toza (tasdiqlangan) · **Sana:** 2026-09-30

---

## 1. TASNIF

### **C — TEST/FIXTURE NUQSONI** (qat'iy isbotlangan)

**A (moliyaviy nuqson) RAD ETILDI.** Talab qilingan invariant **BUZILMAGAN**: post-T0
naqd savdo muvaffaqiyat qaytardi **va** kerakli moliyaviy yozuv bazada **MAVJUD**.
Ishlab chiqarish kodida hech qanday nuqson topilmadi va **hech narsa o'zgartirilmadi**.

## 2. Ildiz sabab

`tests/test_offline_shift_policy_pg.py::_sanoq` yordamchisi ledger qatorlarini
**mavjud bo'lmagan jadvaldan** sanaydi:

```python
leg = s.execute(text("SELECT count(*) FROM cash.ledger_entry WHERE tenant_id = :t"), …)
except Exception:          # ← xatoni YUTADI
    leg = 0
```

- Haqiqiy jadval — **`cash.cash_ledger_entries`** (`app/db/cash/cash_ddl_v1.sql:174`,
  repoda **47** joyda ishlatilgan).
- `cash.ledger_entry` butun repoda **faqat shu bitta qatorda** uchraydi.
- So'rov `UndefinedTable` beradi, `except Exception` uni yutadi → **`leg` DOIM 0**.

Natijada `assert keyin_leg > oldin_leg` har doim `0 > 0` bo'lib yiqilardi — **leg
yozilgan bo'lsa ham**.

### Yashirin, jiddiyroq oqibat

Ayni buzuq o'lchov **yana ikkita** sinovda ishlatiladi va ularning **ledger tasdiqlarini
BEKORGA** aylantirgan edi (yashil turib hech narsa isbotlamasdi):

| Sinov | Ledger tasdig'i | Ilgari |
|---|---|---|
| `…yopilgan_smenaga_naqd_replay_RAD_ETILADI` | rad etilgan replay leg yozmasin | `0 == 0` — bekorga |
| `…takror_client_uuid_ledgerga_IKKINCHI_leg_yozmaydi` | takror push ikkinchi leg yozmasin | `0 == 0` — bekorga |

Ya'ni bitta qizil sinov ortida **ikkita jim, ishlamayotgan moliyaviy tasdiq** turgan edi.

## 3. Bazadagi HAQIQIY qatorlar (73e2fc0, haqiqiy PostgreSQL)

Fikstura qayta qurildi va qatorlar bevosita o'qildi:

**1) Savdo commit bo'lgan**
```
sale: status='completed', total=100.00,
      shift_id=7f404fea…  till_id=d57384ce…  branch_id=a569ba98…
```

**2) To'lov** — `method_code='cash', amount=100.00`

**3) Qoldiq harakati** — `type='sale_out', qty=-1.000`, filial to'g'ri

**4) LEDGER LEGI — MAVJUD** (`cash.cash_ledger_entries`)
```
source_type='SALE'  direction='IN'  amount=100.00
posting_kind='OFF_SHIFT'  shift_id=NULL  cash_account_id=dbde7510…
```

**5) Anomaliya QAYD ETILGAN** (`cash.cash_ledger_exceptions`)
```
kind='UNRESOLVED_OFF_SHIFT'  state='OPEN'  entry_id=79984c41…
```

**6) `cash.shifts` — BO'SH.** Fikstura (`_smena`) faqat legacy `public.shifts` qatorini
yaratadi, `cash.shifts` juftini emas. Shu bois leg `cash.shifts` ga havola qila olmaydi
(`cle_shift_fk`) va **ratifikatsiya qilingan xulq bo'yicha** `OFF_SHIFT` + anomaliya
bo'lib yoziladi — bu aynan 3A ning
`test_7_cash_smenasi_YOQ_bolsa_OFF_SHIFT_anomaliyasi` sinovi qulflagan holat.

**7) Testning so'rovi**
```
SELECT count(*) FROM cash.ledger_entry
→ ProgrammingError (psycopg.errors.UndefinedTable):
  relation "cash.ledger_entry" does not exist
```

**8) `cash` sxemasidagi jadvallar:** `audit_logs`, `cash_accounts`,
**`cash_ledger_entries`**, `cash_ledger_exceptions`, `cash_transfers`,
`negative_cash_approvals`, `reconciliation_assignments`, `reconciliation_records`,
`shifts` — `ledger_entry` **yo'q**.

### Oqim bo'yicha xulosa

```
/sync/push → validatsiya OK → smena tanlandi (legacy, ochiq)
→ create_sale OK → qoldiq chiqimi OK
→ retrofit.on_cash_sale → posting → leg YOZILDI (OFF_SHIFT + anomaliya)
→ post-T0 majburlash: TILL mavjud, o'tdi → COMMIT
```
Hech qayerda jim yo'qotish yo'q.

## 4. Kiritilgan o'zgarish

**Ishlab chiqarish kodi: NOL.** (`git diff -- apps/server/app/` → bo'sh.)

Faqat test yordamchisi (`_sanoq`):
- jadval nomi → `cash.cash_ledger_entries`;
- **`try/except` olib tashlandi** — bu fayl PG-ga bog'langan (`pg_target`) va butun
  maqsadi ledger tasdiqlari, shu bois jadval o'qilmasa sinov jim o'tmasin, baland
  yiqilsin.

## 5. PG natijalari

| To'plam | Natija |
|---|---|
| `test_offline_shift_policy_pg.py` (aniq qizil sinov shu yerda) | **7/7 o'tdi** |
| `tests/cash/test_sale_shift_ownership.py` (3A egalik/qulf) | **16/16 o'tdi** |
| `tests/cash/test_sale_cash_posting.py` + `test_posting_service.py` bilan birga | **72/72 o'tdi** |
| `tests/cash/` (butun papka) | **722/722 o'tdi** (11 daq 28 s) |

SQLite: `test_p9_repair1_contract` + `test_qa_p9_repro` + `test_offline_shift_policy`
+ `test_flows` → **50 o'tdi, 3 xfail** (xfail'lar: qa02 bekor qilingan kutilma,
qa03/qa04 ochiq nuqsonlar).

**Muhimi:** tuzatilgan o'lchov bilan ikkita ilgari bekorga ishlagan tasdiq endi
HAQIQATAN tekshiradi va **yashil** — ya'ni rad etilgan replay ledger legi yozmasligi
va takror `client_uuid` ikkinchi leg yozmasligi jonli isbotlandi. Yashirin moliyaviy
nuqson **chiqmadi**.

## 6. Saqlangan invariantlar

- Phase 3A egalik va qulf kafolatlari — **tegilmagan** (16/16).
- P9-01 (bardoshli idempotentlik kaliti) — **tegilmagan**.
- P9-02 tor tuzatishi (filial) — **tegilmagan**.
- Qonuniy `LATE_SYNC` semantikasi — **tegilmagan**.
- Muzlatilgan yarashtirish semantikasi — **tegilmagan**.

## 7. Tegilmagan mavzular

P9-03 · P9-04 · kengroq P9-05 · p9[10] · SAFE · Release Safety · 1C — **hech biriga
tegilmadi**.

## 8. Metodologik qayd

Bu aynan audit hisobotidagi «bajarilishni isbotlamaydigan sinov» sinfi: yashil (yoki
tushunarsiz qizil) sinov ortida ishlamayotgan tasdiq. Tavsiya: PG-ga bog'langan
moliyaviy sinovlarda `except Exception -> 0` naqshidan voz kechish — u xatoni
o'lchovga aylantiradi.
