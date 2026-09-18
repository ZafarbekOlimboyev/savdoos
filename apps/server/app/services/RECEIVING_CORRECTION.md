# Qabulni tuzatish — model qarori (Phase 5D)

Holat: **kod yozilgan** (model / sxema / servis / API / hujjat o'qish). Manager UI va
to'liq test to'plami — keyingi bosqich.

Tanlangan model: **C — o'zgarmas teskari yozuv + o'rniga qo'yish**, bitta qabul hujjati doirasida.
Servis: `app/services/lot_correction.py`. Endpoint: `POST /api/v1/receiving/{receiving_id}/corrections`.

## Muammo

Nakladnoy xato kiritilgan: 100 o'rniga 10 keldi, muddat boshqa, tannarx boshqa. Kuzatuvli
(`track_lots`) hujjatda buni tuzatadigan yo'l YO'Q edi: `PATCH /purchases/{id}` qoldiqni
ISHORALI delta bilan siljitadi va qaysi partiya o'zgarayotganini bilmaydi, shu bois
`stock_gate` uni 409 bilan to'sadi. Operatorga «qo'llab-quvvatlashga murojaat qiling»
deyilardi — ya'ni jonli do'konda hujjat ABADIY xato qolardi.

## Nega A/B/D rad etildi

**A — partiyani JOYIDA tahrirlash.** Tuzilmaviy jihatdan imkonsiz:

- `StockBatch.received_qty` butun repoda hech qayerda qayta yozilmaydi, va
  `stock_invariant._lot_sums` faqat `remaining_qty` ni yig'adi — partiya ATRIBUTLARINI
  tahrirlash xavfsizlik to'riga UMUMAN ko'rinmaydi;
- `sale_item_lot_allocations.unit_cost` — SOTUV LAHZASINING muzlatilgan surati. Tovar
  ketganidan keyin kogorta narxini qayta yozish tarixiy COGS'ni yolg'on qilardi
  (Phase 2.5 qoidasi: tarixiy sotuv QAYTA YOZILMAYDI).

**B — bekor qilib qayta qabul qilish.** Jimgina hech narsa qilmaydi yoki ikkilantiradi:

- partiya kaliti `uuid5(company:doc_key:line_index:lot_index)` va `ux_lot_intake_key`
  (`company_id`, `client_uuid`) bilan qulflangan; `lot_receiving.create_lots` takroriy
  kalitda MAVJUD partiyani QAYTARADI;
- `/receiving/commit` `client_uuid` bo'yicha dedup qilib, hech narsa qo'llamasdan
  `duplicate: true` beradi;
- yangi `client_uuid` bilan qayta yuborish eski kogortani JONLI qoldirib, yoniga
  ikkinchisini qo'shardi.

**D — tuzatish hujjati (inventarizatsiya yo'li).** Allaqachon mavjud va ATAYLAB
kuchsizroq: sanoq ortiqchasi `source_type='adjustment'` bilan provenansi NOMA'LUM
kogorta tug'diradi va yetkazib beruvchi / kassa bog'lanishini butunlay yo'qotadi. Hujjat
tuzatishi uchun ishlatilsa, «bu tovar kimdan, qaysi hujjat bilan keldi» degan savol
javobsiz qolardi.

## C — nima bo'ladi

```
teskari yozuv:   mavjud kogorta remaining_qty -= q     (lot_writeoff.lock_batches/validate/apply)
o'rniga qo'yish: YANGI kogorta                          (lot_receiving.create_lots,
                                                         doc_key=f"corr:{correction.id}",
                                                         source_type="correction")
```

`received_qty`, `unit_cost`, `batch_no`, `expiry_date`, `client_uuid`, `source_type` —
mavjud kogortada HECH QACHON tegilmaydi. `Receiving.final_items` ham qayta yozilmaydi: u
qabul lahzasining surati, tuzatish esa alohida hodisa.

## Holat mashinasi

**Partiya (`stock_batches.status`)** — yangi qiymat KIRITILMAYDI:

```
open ──(qisman teskari, qoldiq > 0)──▶ open
open ──(nolgacha teskari, ilgari tegilgan)──▶ depleted   [lot_writeoff.apply]
open ──(nolgacha teskari, TEGILMAGANI ISBOTLANGAN)──▶ void  [tuzatish ANIQ yozadi]
void ──▶ terminal (lot_writeoff.validate QUANTITY_BEARING bo'lmagan partiyani rad etadi)
```

`void` `remaining_qty == 0` ni TALAB qiladi (`stock_invariant` da hujjatlashtirilgan, baza
majburlamaydi) — shart kodda, `apply` dan KEYIN tekshiriladi. Bu `void` ning birinchi ish
vaqti yozuvchisi; ikkinchisi — `initdb` dagi boot ta'miri.

To'rtinchi holat QO'SHILMAYDI: `stock_invariant._assert_known_statuses` fail-closed va
tasniflanmagan holat o'sha tenantning HAR keyingi sotuvi/qabuli/sanog'ini 500 qilardi.

**Hujjat (`purchases.status`)** — yangi qiymat yo'q:

```
received/debt/partial ──(sof > 0)──▶ ayni holat, summalar sof qiymatga siljiydi
received/debt/partial ──(hammasi teskari, sof == 0)──▶ cancelled + deleted_at
cancelled ──▶ terminal (har keyingi tuzatishga 404; QULF OSTIDA qayta tekshiriladi)
```

**Tuzatish hujjati** — bir marta yaratiladi, hech qachon tahrirlanmaydi va o'chirilmaydi.
Takror `response_json` ni AYNAN qaytaradi; ayni `client_uuid` bilan boshqa mazmun — 409.

## Rad etishlar (har biri sinov talab qiladi)

| Kod (`X-Error-Code`) | Qachon |
|---|---|
| `LOT_CORRECTION_NOT_TRACKED` | qabul umuman partiya tug'dirmagan (409) |
| `LOT_CORRECTION_CONSUMED` | IDENTIFIKATSIYA tuzatilmoqda, lekin kogorta tegilgan (409) |
| `LOT_CORRECTION_EXCEEDS_REMAINING` | teskari miqdor qoldiqdan katta (409) |
| `LOT_CORRECTION_SHORTFALL_OPEN` | (mahsulot, filial) da yopilmagan qarz bor (409) |
| `LOT_CORRECTION_CASH_UNPOSTABLE` | naqd oyog'i yozilmadi, kassa tegilmadi (409) |
| `LOT_CORRECTION_REPLAY_CONFLICT` | ayni `client_uuid`, boshqa `request_hash` (409) |
| `LOT_CORRECTION_DOC_LOCKED` | tuzatilgan hujjatga `PATCH /purchases/{id}` (409) |
| `LOT_INVARIANT_BROKEN` | yakuniy `stock_invariant.assert_ok` darvozasi (409) |

Kodsiz rad etishlar: ruxsat (403), topilmadi (404), shakl xatolari va partiya tanlovi
(400, matni `lot_writeoff` / `lot_receiving` dan AYNAN uzatiladi).

**Nega `remaining_qty == received_qty` yolg'iz yetmaydi.** Sotuv + mijoz qaytarishi
qoldiqni AYNAN tiklaydi (`lot_return._restock` hatto `depleted` kogortani qayta ochadi).
Shu bois «tegilmagan» dalili uchun BESHALA kanal ham ALOHIDA tekshiriladi
(`lot_correction.alloc_sums` / `untouched`): `sale_item_lot_allocations`,
`stock_movement_lot_allocations`, `return_item_lot_allocations`,
`lot_shortfall_resolutions` va `return_item_resolution_allocations`.

⚠️  Oxirgi ikkisi UZOQ VAQT TUSHIB QOLGAN EDI. Partiya qarzini yopish kogortadan
miqdor OLADI va AYNAN uning narxida COGS og'ishini TAN OLADI; tovar keyin qaytsa
(`return_item_resolution_allocations`) qoldiq tiklanadi va birinchi uchta jadvalda
BIRORTA qator qolmaydi — ya'ni og'ishi allaqachon hisobga olingan kogorta
«tegilmagan» ko'rinib, `void` qilinishi mumkin edi.

**«Qancha ketgan» — GROSS.** Rad etish xabari va `GET /purchases/{id}` dagi
`consumed_qty` chiqishlar yig'indisini beradi (`lot_correction.moved`), qaytishlarni
AYIRMAYDI: 15 sotilib 15 qaytgan kogorta uchun «0 dona harakatlangan» degan xabar
o'zi aytayotgan sababni inkor qilardi.

**Miqdor-only teskari yozuv qisman sotilgan kogortada RUXSAT etiladi** (100 keldi deb
yozilgan, 30 sotilgan, aslida 90 kelgan → qolgan 70 dan 10 teskari). Tarixda hech narsa
yolg'on bo'lmaydi; faqat qoldiq chegarasi amal qiladi.

## Pul tomoni

- **Yetkazib beruvchi.** Faqat `charge` yozilgan (qarz) hujjatda: `sup.balance += delta`
  + `SupplierLedger(type=adjustment, ref_type='receiving_correction')`.
  `ref_type IN ('purchase','receiving') AND type='charge'` predikatiga HECH QACHON
  tegilmaydi — uchta kassa migratsiyasi quyi tizimi «bu hujjat kassadan pul chiqarganmi»
  qarorini AYNAN o'sha predikatdan o'qiydi.
- **Kassa.** Faqat naqd hujjatda: kamayish → yangi `PurchaseReturn`
  (`reason='receiving_correction'`) + `retrofit.on_purchase_return`; oshish →
  `retrofit.on_cash_purchase_increase`. Custody
  `cutover_guard.resolve_cash_custody(operation="receiving_correction_cash")` orqali va
  FAQAT naqd oyoq haqiqatan yoziladigan bo'lsa (`paid != new_total`) — `purchases.py`
  bilan AYNI naqsh. Pul qimirlamaydigan tuzatish (muddat/partiya raqami) smenasiz
  menejerda ham o'tadi; ilgari u `CUSTODY_REQUIRED` bilan yopilardi va Manager
  `cash_account_id` yubormagani uchun qayta urinishning yo'li yo'q edi.
  Kassa ledgeri append-only (DB trigger) — kamayish QARAMA-QARSHI oyoq bilan yoziladi,
  mutatsiya bilan emas.
- **Hujjat summalari.** `purchase_items` qatorlari BAYT-BA-BAYT o'zgarmaydi (ular aslida
  nima yozilganining yozuvi); faqat hosila `subtotal`/`total`/`paid_amount` siljiydi.

### Ikki xil pul asosi (ADASHTIRILMAYDI)

| Asos | Formula | Qayerda |
|---|---|---|
| COGS (zaxira) | Σ miqdor × **partiya** narxi (`StockBatch.unit_cost`) | harakat `unit_cost`, `stock_movement_lot_allocations` |
| HUJJAT | Σ miqdor × **qator** narxi (`PurchaseItem.unit_cost`, o'rniga qo'yishda qatorning tuzatilgan narxi) | `reversed_total`/`replaced_total`/`delta_total`, `Purchase.total`, `SupplierLedger`, kassa |

`Purchase.total` ning O'ZI hujjat asosida tug'iladi (`receiving.commit`: xom Σ qty × unit_cost,
`Numeric(14,2)` ga BIR MARTA yaxlitlanadi) — shu bois teskari yozuv ham xom yig'iladi va BIR
MARTA yaxlitlanadi. Aks holda: partiyaning o'z narxi qator narxidan farq qilsa to'liq teskari
qilish ta'minotchida FANTOM qarz qoldirardi; ikki tiyindan kichik qatorlar esa hujjat jamini
0.01 ga surib, tuzatishni «manfiy jami» deb rad etardi. `lot_writeoff.apply` endi
YAXLITLANMAGAN aniq yig'indi qaytaradi (yaxlitlash chaqiruv joyida, HALF_UP).

**Hisobotlar.** `purchase_items` tuzatilmagani uchun ta'minotchi hisoboti ikki xil raqam
ko'rsatardi (hujjat jami tuzatilgan, mahsulot ustuni tuzatilmagan). Endi ikkala tomon ham
mahsulot agregati + `lot_correction.deltas_by_product` (AYNI hisob) dan tug'iladi.

**FIFO o'rni.** Qator AYNAN bitta kogortani teskari qilsa, o'rniga qo'yilgan partiya o'sha
kogortaning `received_at` ini oladi (`lot_receiving.create_lots(received_at=...)`):
sof identifikatsiya tuzatishi tovarni FIFO/FEFO navbatining oxiriga surmasin. `created_at`
HAR DOIM yozuv vaqti.

## Qulf tartibi

`lot_correction` modul izohida (1–9). Yangi tartib o'ylab topilmaydi: FK ota qatorlari
avval `FOR KEY SHARE`, so'ng `Purchase` → `Supplier` → `Inventory` → `StockBatch`. Teskari
tartib (`FOR KEY SHARE` dan keyin `FOR UPDATE` ga ko'tarilish) Phase 2.5 da o'lchangan
deadlock'ni qaytarardi.

**Qulf doirasi — HUJJATNIKI, so'rovniki emas.** «Hujjat to'liq teskari qilindimi» qarori shu
qabulning HAMMA kogortasiga qaraydi, shu bois ularning `Inventory` qatorlari va partiyalari ham
(so'rovda bo'lmasa ham) AYNI global tartibda qulflanadi. Qulfsiz o'qishda parallel yozuvchi
hujjatni jimgina `cancelled` qilib qo'yardi yoki haqli bekor qilishga to'sqinlik qilardi
(`test_receiving_correction_pg.test_PG_bekor_qarori_QULFLANMAGAN_kogortaga_TAYANMAYDI`).

`resolve_cash_custody` esa QULFLARDAN KEYIN chaqiriladi: u `Setting`/`Shift`/`CashAccount` ni
faqat O'QIYDI, birorta qator qulfi olmaydi — tartib buzilmaydi.

## Idempotentlik

`receiving_corrections (company_id, client_uuid)` — `ux_recv_corr_client`, MAJBURIY
indeks (`required_schema.REQUIRED_INDEXES`): yo'q bo'lsa `/health/ready` QIZIL va
`/lots/enable` aktivatsiyani to'sadi. `request_hash` — so'rovning kanonik sha256'si;
`response_json` — birinchi javob. Poygada `IntegrityError` ushlanadi va G'OLIB
tranzaksiyaning javobi qaytariladi (`duplicate: true`).
