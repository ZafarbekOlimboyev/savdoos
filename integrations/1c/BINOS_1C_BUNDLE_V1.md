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
3. **Obyektda takror kalit** va **noma'lum kalit** (whitelist'da yo'q) — rad. Yangi maydon faqat `schema_version` bilan.
4. **Vaqt:** `exported_at`, `snapshot_at` — ISO 8601, vaqt zonasi (offset) bilan.
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
* **Birlik:** faqat ANIQ jadval (`шт/кг/л/упак…` + operator `--unit-map`); nom bo'lmasa OKEI kodi. Natija BinOS
  `units` jadvalida bo'lmasa — `UNKNOWN_UNIT`.

## Tuzilma

```jsonc
{
  "schema_version": "binos-1c-v1",
  "source_system": "1c",
  "export_id": "…",                         // extractor bergan noyob ID
  "exported_at": "2026-09-20T09:00:05+06:00",
  "snapshot_at": "2026-09-20T09:00:00+06:00", // qoldiq qaysi lahzaga olingan
  "infobase": {
    "platform_version": "8.3.24.1548",
    "configuration_name": "…",               // Метаданные.Синоним / Имя
    "configuration_version": "…",            // Метаданные.Версия
    "infobase_id": "…" | null                // ixtiyoriy
  },
  "extractor": { "name": "BinOS 1C Migrator", "version": "1.0.0" },
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
      "plu": "00575" | null,                 // kalit tushirib qoldirilishi mumkin (= null)
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
