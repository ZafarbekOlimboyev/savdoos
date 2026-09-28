# BinOS 1C eksport formati — `binos-1c-v1`

Bir martalik, **faqat o'qish** migratsiyasi uchun 1C → BinOS fayl shartnomasi.
BinOS 1C'ga hech narsa yozmaydi. Doimiy sinxronizatsiya emas.

Tekshiruvchi kod: `apps/server/app/services/migrator_1c/bundle.py` (qat'iy, fail-closed).
Sintetik namuna generatori: `apps/server/tests/migrator_1c_synth.py`.

## Fayllar

| Fayl | Mazmun |
|---|---|
| `binos-export-<export_id>.json` | UTF-8 JSON (BOM ruxsat etiladi) |
| `binos-export-<export_id>.json.sha256` | `<64 hex>  <fayl nomi>` — fayl BAYTLARINING SHA256'si (BOM'li yon fayl ham qabul qilinadi) |

BinOS yuklashda SHA256'ni **qayta hisoblaydi**; mos kelmasa fayl rad etiladi. Hajm chegarasi 256 MB.

## Qat'iy qoidalar (buzilsa — BUTUN fayl rad etiladi)

1. **JSON sonlari taqiqlangan** (int, float, NaN, Infinity). Barcha miqdor, narx va sanoqlar MATN: `"12.500"`, `"7137"`.
   Sabab: `0000123` son sifatida `123` bo'lib qoladi; float narx/miqdorni buzadi.
2. **Identifikatorlar matn:** `guid`, `code`, `article`, barkod `value`, `plu`. Oldingi nollar saqlanadi.
3. **Obyektda takror kalit** va **noma'lum kalit** (whitelist'da yo'q) — rad.
   **Yangi maydon faqat `schema_version` bilan** — bitta istisno bilan: `binos-1c-v1` hali
   **RELIZDAN OLDINGI** shartnoma, chunki uni ishlab chiqaradigan birorta narsa yo'q
   (`.epf` yozilmagan, diskda birorta bundle fayli yo'q, yagona o'quvchi — `bundle.py`).
   Shu holat tugagunicha shartnoma **joyida tuzatiladi**, versiya oshirilmaydi: aks holda
   hech qachon ishlatilmagan «v1» shakli abadiy qoladi va ikki shaklni qo'llab-quvvatlash
   kerak bo'lardi. **Birinchi haqiqiy ekstraktor paydo bo'lishi bilan bu istisno tugaydi.**
   *(2026-09-28: `source_copy` shu qoida bo'yicha qo'shildi.)*
4. **Vaqt:** `exported_at`, `snapshot_at` — ISO 8601, vaqt zonasi (offset) bilan, sanasi
   `2000..2100` oralig'ida (to'ldirilmagan 1C `Дата` si `0001-01-01` beradi va eskirganlik
   darvozasini jimgina ochib yuborardi). **`snapshot_at` `exported_at` dan KEYIN bo'lolmaydi** —
   holatni qo'lga olishdan oldin eksport qilib bo'lmaydi; tenglik ruxsat (1C `Дата` si soniya
   aniqligida).
5. **Tuzilma GUID'lari** (`warehouses[].guid`, `price_types[].guid`, `selection.*`, `stock[].warehouse_guid`,
   `prices[].price_type_guid`) — kichik harfli kanonik `8-4-4-4-12`.
6. `selection.purchase_price_type_guid` chakana narx turidan FARQ qilishi shart (aks holda tannarx = chakana).
7. **Manifest sanoqlari** — ASCII raqamli matn, fayl mazmuniga AYNAN teng. `stock_qty_by_warehouse` kalitlari
   AYNAN `selection.warehouse_guids`; qiymatlari Decimal matn (jami bo'lgani uchun 40 butun xonagacha).
8. Bitta mahsulotda bitta narx turi / bitta ombor ikki marta bo'lmaydi.

## Qator darajasidagi qiymatlar (buzilsa — faqat SHU qator kodlanadi)

* **Decimal:** faqat ASCII `-?[0-9]{1,20}(\.[0-9]{1,12})?` (to'liq moslik). Vergul, eksponenta, `+`, probel,
  oxirgi `\n`, to'liq kenglikdagi yoki arab raqamlari — `INVALID_NUMBER` (narxda `INVALID_PRICE`, qoldiqda `INVALID_QTY`).
  Ustun aniqligidan ortiq nol bo'lmagan xona (qoldiq > 3, narx > 2) — `PRECISION_LOSS_*`, yuvarlanmaydi.
* **Mahsulot GUID'i:** 1C `XMLСтрока(Ссылка)`. Katta harf kichikka keltiriladi; qavs, tiresiz, atrofida probel,
  nol-GUID — `INVALID_GUID`; bo'sh — `MISSING_GUID`.
* **Barkod:** faqat chekka probel olinadi; raqamdan boshqa belgi yoki 6–14 dan tashqari uzunlik — `INVALID_BARCODE`
  (belgilar O'CHIRILMAYDI). 12 xonali UPC-A va `0`+12 xonali EAN-13 BITTA GTIN deb qidiriladi (egalik, to'qnashuv).
* **Kelish narxi `"0"`:** 1C'da to'ldirilmagan deb hisoblanadi — `ZERO_PURCHASE_PRICE` (info), BinOS tannarxi
  USTIGA YOZILMAYDI (yangi mahsulotda 0). Hisobotda `purchase_price_*` hisoblagichlari bor.
* **Birlik:** faqat ANIQ jadval (`шт/кг/л/упак…` + operator `--unit-map`); nom bo'lmasa OKEI kodi.
  ⚠️ `--unit-map` O'LCHAM va MIQYOS bo'yicha tekshiriladi: tanilgan nom faqat ayni o'lchamdagi va ayni
  miqyosdagi BinOS kodiga tusha oladi (`кг -> dona`, `г -> kg` RAD). Aylantirish shartnomada YO'Q. Natija BinOS
  `units` jadvalida bo'lmasa — `UNKNOWN_UNIT`.

## Tuzilma

```jsonc
{
  "schema_version": "binos-1c-v1",
  "source_system": "1c",
  "export_id": "…",                         // extractor bergan noyob ID
  "exported_at": "2026-09-20T09:00:05+06:00", // shu FAYL yaratilgan lahza
  "snapshot_at": "2026-09-20T09:00:00+06:00", // MANBA KESIMI — pastga qarang
  "infobase": {
    "platform_version": "8.3.24.1548",
    "configuration_name": "…",               // Метаданные.Синоним / Имя
    "configuration_version": "…",            // Метаданные.Версия
    "infobase_id": "…" | null                // ixtiyoriy
  },
  "extractor": { "name": "BinOS 1C Migrator", "version": "1.0.0" },
  "source_copy": {                             // QAYSI nusxadan chiqarilgan — MAJBURIY
    "sha256": "…64 KICHIK harfli hex…",        // BITTA artefakt FAYLI: .dt yoki 1Cv8.1CD
    "byte_size": "3221225472",                 // MATN, yetakchi nolsiz, musbat
    "source_snapshot_at": "2026-09-20T09:00:00+06:00",   // snapshot_at bilan AYNI LAHZA
    "copy_method": "DT_EXPORT",                // DT_EXPORT | FILEBASE_COPY | OTHER_APPROVED_COPY
    "original_artifact_type": "dt"             // kichik harfli qisqa token
  },
  "warehouses":  [ { "guid": "…", "code": "…", "name": "…" } ],   // BARCHA omborlar
  "price_types": [ { "guid": "…", "code": "…", "name": "…" } ],   // BARCHA narx turlari
  "selection": {
    "warehouse_guids": ["…"],                // real joriy qoldiq manbai (operator tanlovi)
    "retail_price_type_guid": "…",           // chakana narx
    "purchase_price_type_guid": "…" | null   // kelish narxi (ixtiyoriy, chakanadan farqli)
  },
  "products": [
    {
      "guid": "…" | null,
      "code": "0000123" | null,              // 1C Код
      "article": "00000456" | null,          // Артикул
      "name": "…" | null,
      "kind": "goods" | "service" | "set" | "other",
      "is_folder": false,
      "deletion_mark": false,
      "has_characteristics": false,          // V1: true bo'lsa BLOCKED
      "has_series": false,                   // V1: faqat ma'lumot (lot faollashtirilmaydi)
      "unit": { "name": "шт", "code": "796" } | null,   // nom + OKEI kodi
      "is_weighted": true | false | null,    // kalit tushirib qoldirilishi mumkin (= null)
      "plu": "00537" | null,                 // BARKOD ichidagi 5 xonali PLU maydoni (pastga qarang);
                                             // kalit tushirib qoldirilishi mumkin (= null)
      "barcodes": [ { "value": "4600000000017", "type": "EAN13" } ],
      "prices":   [ { "price_type_guid": "…", "value": "12500.00" | null } ],
      "stock":    [ { "warehouse_guid": "…", "qty": "12.500" } ]      // BARCHA omborlar bo'yicha
    }
  ],
  "manifest": {
    "product_count": "…", "barcode_count": "…", "price_count": "…", "stock_row_count": "…",
    "stock_qty_by_warehouse": { "<tanlangan ombor guid>": "…" }   // AYNAN selection.warehouse_guids
  }
}
```

`manifest.stock_qty_by_warehouse` extractor tomonidan **1C ichida** hisoblanadi; BinOS uni fayldan
mustaqil qayta hisoblab solishtiradi. Tanlanmagan omborlardagi qoldiq ham `stock` ga yoziladi — hisobotda
ko'rinadi (`unselected_warehouse_stock_qty`), lekin migratsiya qilinmaydi.

### `snapshot_at` — MANBA KESIMI, yig'uvchi ishlagan vaqt EMAS

| Maydon | Ma'nosi |
|---|---|
| **`snapshot_at`** | **Jonli 1C holati MUZLATILGAN / NUSXA OLINGAN lahza.** Yig'uvchi ishlagan vaqt EMAS, nusxa tiklangan vaqt EMAS, bundle yozilgan vaqt EMAS. |
| `exported_at` | Shu **fayl yaratilgan** lahza. |

Copy-first arxitekturada (nusxa alohida mashinada tiklanadi) bu farq hal qiluvchi bo'ladi:
muzlatish do'konda kechasi bo'ladi, bundle esa soatlar keyin yoziladi. **Ekstraktor `snapshot_at`
ga NUSXA OLINGAN lahzani yozishi SHART** — o'zi ishlagan lahzani emas.

⚠️ **`snapshot_at` MASHINA SOATIDAN OLINMAYDI — u OPERATOR beradigan parametr.** Tiklangan
nusxada ishlayotgan ekstraktor nusxa qachon olinganini **bila olmaydi**: sessiya soati
(`ТекущаяУниверсальнаяДата()` va shunga o'xshashlar) unga o'zining ishga tushish vaqtini beradi,
ya'ni aynan taqiqlangan ma'noni. Qiymat administratorning yozma qaydidan keladi
([`SANDBOX_RESTORE_RUNBOOK.md`](SANDBOX_RESTORE_RUNBOOK.md), 1-bo'lim). `exported_at` esa,
aksincha, mashina soatidan olinadi — u fayl yozilgan lahza.

Eskirganlik darvozasi AYNAN `snapshot_at` ni baholaydi (`apply.py` — `StaleSnapshotError`,
`>=` bo'lsa rad). `exported_at` ni hech kim solishtirmaydi. Shu bois:

* `snapshot_at` **mazmun xeshiga KIRADI** (UTC ga keltirib), `exported_at` esa **kirmaydi** —
  kesim HOLATNING bir qismi, fayl yozilgan vaqt esa emas;
* o'zgarmagan holatni o'sha kesim bilan qayta chiqarish — boshqa fayl bo'lsa ham — `AlreadyApplied`;
* yangi muzlatish — yangi kesim, ya'ni bu boshqa eksport.

⚠️ **Qat'iyan taqiqlangan:** eski nusxaga yangi `snapshot_at` yozib, uni yangidek ko'rsatish.

⚠️ **Kod buni TUTA OLMAYDI.** Invariantlar (`snapshot_at <= exported_at`, kalendar oynasi)
da'vo qilingan TARTIBNI isbotlaydi, ROSTLIKNI emas: ikkala vaqtni birga surib qo'ygan ekstraktor
hamma tekshiruvdan o'tadi. Yagona haqiqiy himoya — nusxaning yozma qaydi
([`SANDBOX_RESTORE_RUNBOOK.md`](SANDBOX_RESTORE_RUNBOOK.md), 1-bo'lim: `copy_sha256`,
`source_snapshot_at`, `taken_by`, `freeze_declared_at`).

Chegaralar `apps/server/tests/test_migrator_1c_snapshot_time.py` da qulflangan.

### `source_copy` — QAYSI nusxa, va yoshlik darvozasi

**Uchta himoya ALOHIDA va biri ikkinchisining o'rnini bosmaydi:**

| Himoya | Nimani isbotlaydi | Qayerda |
|---|---|---|
| Yangilik darvozasi | kesim **e'lon qilingan** yoshi 24 soatdan oshmaydi | `freshness.py`, APPLY vaqtida |
| `source_copy` | **QAYSI** nusxa artefakti ishlatilgani | shu blok |
| Yozma qayd | nusxa **QACHON** olingani | `SANDBOX_RESTORE_RUNBOOK.md`, 1-bo'lim |

⚠️ **SHA-256 qaysi nusxa ishlatilganini isbotlaydi. U o'sha nusxa QACHON olinganini
ISBOTLAMAYDI.** Kesim vaqti operator boshqaradigan yozma qayddan keladi, kodning
tekshiruvidan emas.

⚠️ **BinOS `.dt` / `1Cv8.1CD` faylini hech qachon ko'rmaydi** — `sha256` va `byte_size` ni server
tekshira olmaydi. Ular **da'vo**: odam ularni administratorning qaydidagi `copy_sha256` /
`copy_size_bytes` bilan solishtiradi. Kod bu yerda faqat **shaklni** va **kesim bilan moslikni**
kafolatlaydi.

Qoidalar: `sha256` — 64 ta **kichik** harfli hex (PowerShell `Get-FileHash` KATTA harfda
chiqaradi — kichiklashtiring); `byte_size` — musbat butun son **matni**; `source_snapshot_at` —
`snapshot_at` bilan **ayni lahza** (ofset boshqa bo'lishi mumkin, mikrosekund farqi esa RAD);
fayl bazasida ham **bitta fayl** (`1Cv8.1CD`) xeshlanadi, papkaning yagona xeshi bo'lmaydi.

`source_copy` **mazmun xeshiga kirmaydi** — u artefakt haqidagi ma'lumot, holat haqida emas
(`infobase` va `extractor` kabi). Bir xil holatning ikki nusxasidan chiqarilgan bundle bir xil
mazmun xeshiga ega bo'ladi, ya'ni takroriy apply darvozasi nusxa almashgani uchun ochilib ketmaydi.

### Yangilik darvozasi — 24 soat

APPLY kesimni **hozirgi vaqt** bilan solishtiradi. Soat manbai — imkon bo'lsa yozilayotgan
**bazaning** `clock_timestamp()` i. `now()` ATAYLAB ishlatilmaydi: u `transaction_timestamp()`
taxallusi, ya'ni tranzaksiya boshlangan lahzani qaytaradi va uzoq apply tranzaksiyasida yoshni
**kam** ko'rsatadi — bu esa xavfli yo'nalish. SQLite'da server yo'q ⇒ jarayon soati, va dalilda
`clock_source: "process"` deb ochiq belgilanadi (u avtoritetli o'qish emas).

**Kelajakka NOL tolerantlik.** Kesim hozirgi vaqtdan keyin bo'lolmaydi — kelajakdagi lahzada 1C
holatini muzlatib bo'lmaydi. Yosh 0 bo'lishi mumkin; bir mikrosekund kelajak ham rad etiladi.
⚠️ Radni «yaxshiroq» vaqt yozib chetlab o'tish **taqiqlangan**: soat to'g'rilanadi va bundle
qayta chiqariladi. Haqiqiy kesim lahzasi nusxa qaydidan olinadi.

Solishtirish **tz-aware lahzalar** bo'yicha, formatlangan satrlar bo'yicha emas — `+06:00` va
`+00:00` da yozilgan bir xil lahza bir xil natija beradi.
Eskirganlik halqasi faqat oldin qo'llangan job'lar bilan solishtiradi va birinchi apply'da —
ya'ni **cutover'da** — bo'sh bo'ladi; bu darvoza aynan shu bo'shliqni yopadi.

⚠️ **24 soat — faqat TEXNIK yuqori chegara.** U kesimdan keyin savdo bo'lmaganini
**ISBOTLAMAYDI**. Savdoning to'xtaganini faqat hujjatlashtirilgan operatsion tasdiq ko'rsatadi
(smenalar yopilgani, «Активные пользователи» bo'sh, uchta nazorat hisoboti) —
[`SANDBOX_RESTORE_RUNBOOK.md`](SANDBOX_RESTORE_RUNBOOK.md).

24 soat — bosqichlar yig'indisiga moslashtirilgan raqam emas, **yuqori chegara**: savdo qiladigan
do'konda 24 soatlik har qanday oraliq albatta bitta ochilishni o'z ichiga oladi. Runbook freeze
oynasining uzunligini «NOMA'LUM» deb yozadi, shu bois pastroq raqam o'ylab topilgan bo'lardi.

⚠️ **VOZ KECHISH YO'Q — darvoza MUTLAQ** (2026-09-28).

Ilgari mapping ildizidagi `freshness_override` bloki (`acknowledged` / `reason` / `approved_by` /
`approved_at`) darvozani ochardi. **Bu himoya emas edi**, va buni ochiq aytish kerak:
`migrate_1c` CLI'sida **identity umuman yo'q** — `cmd_apply` `apply_migration` ni `actor_id`siz
chaqiradi, ya'ni `job.created_by`, audit aktyori va harakatlarning `employee_id` si **NULL**
bo'ladi. `approved_by` esa mapping faylini yozgan odamning **o'zi tergan matn**: u hech kimni
tasdiqlamaydi va hech narsani isbotlamaydi.

Shu bois blok endi **rad etiladi** (reja umuman tuzilmaydi) va sabab aniq aytiladi — kalit
whitelist'da qoldirildi, aks holda operator umumiy «noma'lum kalit» xatosini olib, nega
ishlamasligini bilmasdan qolardi.

**Yagona yo'l — yangi muzlatish va yangi nusxa.** Tekshiriladigan tasdiqlash mexanizmi
(autentifikatsiyalangan tasdiqlovchi, hisobot/mapping/kesim/kompaniyaga bog'langan, o'zgarmas
yozuv bilan) alohida ish sifatida loyihalanmoqda.

`import_jobs.column_mapping.freshness` da har yurish uchun dalil qoladi: `now`, `snapshot_at`,
`age_seconds`, `max_age_seconds`, `clock_source`, `verdict`.

### `products[].plu` — barkod PLU maydoni, etiketkadagi KOD EMAS

Ekstraktor `plu` ga **tarozi barkodi ichidagi 5 xonali PLU maydonini** chiqarishi SHART.
Fayzanning real tarozi etiketkalari bilan tasdiqlangan kontrakt:
`27` + PLU(5) + GRAMM(5) + EAN-13 nazorat(1) = 13 raqam
(`apps/server/app/services/scale_barcode.py:12`, misol `2700537004264`).

Tarozi etiketkasida **6 xonali KOD** bosiladi — bu ko'rinish, barkod maydoni emas. Uni `plu` ga
yozish MUMKIN EMAS: 6 xonali qiymat `INVALID_PLU` (decide) beradi — chegara 1–5 xona
(`apps/server/app/services/migrator_1c/normalize.py:211`). BinOS API'da ham AYNI cheklov
(`apps/server/app/api/v1/products.py:35`), ya'ni backend kengaytirilmagan.

Kanonik mapping — uchala shakl BITTA tarozi tovarini bildiradi:

| Shakl | Namuna | Izoh |
|---|---|---|
| Etiketkada bosilgan KOD | `000537` | 6 xona — tarozi shunday chop etadi. `plu` ga YOZILMAYDI |
| Barkod ichidagi PLU maydoni | `00537` | 5 xona, SATR — `plu` ga AYNAN shu yoziladi |
| BinOS `products.plu_code` | `537` | yetakchi nolsiz (QA PC-013) — DB'da shunday saqlanadi |

* `plu` — MATN (qat'iy qoida 2): `"00537"`. Songa aylantirilmasin, yetakchi nollar yo'qolmasin.
* `"00537"` qabul qilinadi va `537` ga keltiriladi — `PLU_LEADING_ZEROS` (info, xato emas).
  Yetakchi nolsiz `"537"` ham to'g'ri; solishtirish ikkala tomonni 5 xonaga to'ldirib bajariladi
  (`apps/server/app/services/scale_barcode.py:101`).
* 6+ xona, bo'sh joydan boshqa begona belgi yoki raqam bo'lmagan matn — `INVALID_PLU`.
* Mahsulot tarozi tovari bo'lmasa — kalit tushirib qoldiriladi (= `null`).

## Mazmun xeshi (idempotentlik) — `binos-1c-content-v2`

`content_sha256` kanonik PROYEKSIYADAN hisoblanadi (`bundle.canonical_projection`):

* faqat ma'lum maydonlar; yo'q kalit = `null`;
* mahsulot GUID'i kanonik (kichik harf), barkod chekka probelsiz;
* son qiymati bo'yicha: `"12.5"` = `"12.500"`, `"7"` = `"7.00"`, `"0.000"` = `"0"` (buzuq matn o'zicha qoladi);
* `snapshot_at` UTC lahzasiga keltiriladi (`+06:00` va `Z` bir xil lahza — bir xil xesh);
* qator tartibi, JSON formati, BOM, `exported_at`, `export_id`, `infobase`, `extractor` xeshga KIRMAYDI;
* ko'plik saqlanadi: `[X]` va `[X, X]` turli xesh.

Apply fayl xeshi YOKI mazmun xeshi allaqachon qo'llangan bo'lsa rad etadi (`AlreadyApplied`), va
snapshot vaqti allaqachon qo'llangan 1C snapshot'idan eski yoki teng bo'lsa ham rad etadi (`StaleSnapshotError`).

## Qator kodlari (dry-run hisobotida)

| Guruh | Kodlar |
|---|---|
| block | MISSING_GUID, INVALID_GUID, DUPLICATE_GUID, MISSING_NAME, IDENTITY_FORMAT_MISMATCH, IDENTITY_DUPLICATE_IN_BINOS, GUID_OWNED_BY_OTHER_SOURCE, BARCODE_COLLISION_IN_BUNDLE, INVALID_PRICE, NEGATIVE_PRICE, INVALID_PURCHASE_PRICE, NEGATIVE_PURCHASE_PRICE, PRICE_OUT_OF_RANGE, PRECISION_LOSS_PRICE, INVALID_QTY, QTY_OUT_OF_RANGE, PRECISION_LOSS_QTY, CHARACTERISTICS_UNSUPPORTED, TARGET_LOT_TRACKED |
| decide | MISSING_PRICE, ZERO_PRICE, NEGATIVE_STOCK, UNKNOWN_UNIT, UNIT_DIFFERS, INVALID_BARCODE, BARCODE_OWNED_BY_OTHER_PRODUCT, ARTICLE_COLLISION_IN_BUNDLE, PLU_COLLISION, INVALID_PLU, REACTIVATE_PLU_CONFLICT, IDENTITY_CONFLICT, MANY_TO_ONE |
| info | MISSING_STOCK, STOCK_ONLY_IN_UNSELECTED_WAREHOUSE, STOCK_IN_UNSELECTED_WAREHOUSE, INVALID_QTY_UNSELECTED_WAREHOUSE, ZERO_STOCK, NAME_DIFFERS, PRICE_CHANGES, PURCHASE_PRICE_CHANGES, ZERO_PURCHASE_PRICE, EXTRA_BINOS_BARCODES, LOT_DATA_PRESENT, WHITESPACE_TRIMMED, PLU_LEADING_ZEROS, DUPLICATE_BARCODE_IN_ROW, PRICE_FOR_UNSELECTED_TYPE, MISSING_PURCHASE_PRICE, NAME_DUPLICATE_IN_BUNDLE, CODE_DUPLICATE_IN_BUNDLE |

Asosiy toifa: `EXCLUDED > BLOCKED > DELETED_MATCH > AMBIGUOUS > EXACT_MATCH > CANDIDATE > NEW`.

* `EXCLUDED` — papka, o'chirish belgisi, `kind != goods`; sifat hisoblagichlariga kirmaydi (alohida `excluded_by_reason`).
* `AMBIGUOUS` — bir nechta nomzod; nomzod BOSHQA identitetga ega (`IDENTITY_CONFLICT`, LINK imkonsiz);
  bir nechta 1C qatori GUID'siz dalil bilan bitta mahsulotni ko'rsatadi (`MANY_TO_ONE`).
* Nomzod dalillari: `article`, `barcode` (GTIN variantlari bilan), `name` (NFKC+casefold), `plu`. Hech biri
  avtomatik bog'lanish EMAS.
