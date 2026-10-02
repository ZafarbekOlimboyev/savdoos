# BinOS 1C Discovery to'plami — `binos-1c-discovery-v1`

**Bu nima.** 1C ichida ishlaydigan yig'uvchi chiqaradigan **faqat o'qish** hisoboti: konfiguratsiyada
nima borligi, BinOS migratoriga kerak maydonlar qayerdan olinishi va har bir javobga qanchalik
ishonish mumkinligi.

**Bu nima EMAS.** Bu migratsiya fayli EMAS. Migratsiya fayli — `binos-1c-v1`
([BINOS_1C_BUNDLE_V1.md](BINOS_1C_BUNDLE_V1.md)), uni `migrator_1c` o'qiydi. Ikkalasi alohida
artefakt va **hech qachon aralashtirilmaydi**: discovery to'plami do'kon ma'lumotini ko'chirmaydi,
u faqat tuzilma va sanoqlarni tashiydi.

Tekshiruvchi kod: `apps/server/app/services/discovery_1c/bundle.py` (qat'iy, fail-closed).
Sintetik generator: `apps/server/tests/discovery_1c_synth.py`.
CLI: `python -m app.tools.discovery_1c validate <papka>`.

---

## Fayllar

| Fayl | Mazmun |
|---|---|
| `discovery.json` | manba metadatasi + **nishonlar bo'yicha bog'lanishlar** (asosiy mazmun) |
| `metadata_sweep.json` | xom metadata sanog'i: obyektlar, bolalari, qator sanoqlari |
| `counts.json` | rekonsiliatsiya sanoqlari |
| `status.json` | yurish yozuvi: umumiy holat, bo'limlar, vaqtlar |
| `summary.md` | odam o'qiydigan hisobot |
| `samples/*.json` | namunalar (ixtiyoriy) |

Beshta birinchi fayl **MAJBURIY** — bittasi yo'q bo'lsa to'plam rad etiladi.

## Qat'iy qoidalar (buzilsa — BUTUN to'plam rad etiladi)

1. **JSON sonlari taqiqlangan.** Har qanday sanoq — ASCII raqamli **MATN**: `"7137"`.
   Sabab `binos-1c-v1` dagi bilan bir xil: `000537` son bo'lsa `537` ga aylanadi va PLU yo'qoladi.
   Namunadagi qiymatlar ham MATN yoki `null`.
2. **Takror kalit** va **noma'lum kalit** — rad. Kalit **yetishmasa** ham rad: `null` yozish va
   kalitni tushirib qoldirish bir xil narsa emas.
3. **Har bir nishon `mappings` da AYNAN BIR MARTA.** Aniqlanmagan nishon tashlab ketilmaydi —
   u `UNKNOWN` darajasi va `errors` dagi sababi bilan yoziladi.
   *Nega:* jim tushib qolish eng xavfli nosozlik — hisobot to'liq ko'rinadi, aslida savol berilmagan.
4. **`status` bo'limlardan hisoblanadi** va e'lon qilingani bilan mos kelishi shart.
   Yiqilgan bo'lim sababsiz qolmaydi.
5. **Vaqt:** `collected_at`, `started_at`, `finished_at` — ISO 8601, **offset bilan**.
6. **`VERIFIED` ni nom mosligi bera olmaydi** (pastga qarang).
7. **Sir topilsa — rad:** ulanish satri (`File=`/`Srvr=`/`Usr=`/`Pwd=`), parol, token, e-mail,
   telefon, PEM kalit bloki, `AnyDesk`/`RDP` identifikatori. Namunaning **ustun nomi** ham
   tekshiriladi.
8. **Manba `copy` bo'lishi kerak.** `live` — ataylab ruxsat talab qiladi (`allow_live_source=True`).

## Ishonch darajasi — sxemaning yuragi

```
evidence[].kind:
  KUCHSIZ (o'zi bilan faqat CANDIDATE):
    name_match · synonym_match · type_shape · cardinality · fill_ratio ·
    value_domain · structural_link
  KUCHLI (faqat shular VERIFIED beradi):
    human_confirmed · arithmetic_proof · contract_match ·
    cross_source_agreement · absence_proven
```

* `UNKNOWN` — dalil **bo'lmasligi** kerak, sabab `errors` da.
* `CANDIDATE` — kamida bitta dalil.
* `VERIFIED` — kamida bitta **kuchli** dalil. **Yuzta `name_match` ham bittasining o'rnini bosmaydi.**
* `source_kind = "absent"` (ya'ni «bu konfiguratsiyada YO'Q») `VERIFIED` bo'lishi uchun
  `absence_proven` SHART — «topa olmadim» bilan «yo'qligini isbotladim» boshqa-boshqa narsa.

## Nishonlar

19 tasi `binos-1c-v1` maydonlari (15 mahsulot maydoni + 4 tuzilma bloki), 4 tasi faqat discovery:

```
warehouses · price_types · selection.retail_price_type · selection.purchase_price_type
products.{guid, code, article, name, kind, is_folder, deletion_mark, has_characteristics,
          has_series, unit, is_weighted, plu, barcodes, prices, stock}
scale.{plu_source, barcode_prefix, exchange_rule} · equipment.connected
```

`products.*` ro'yxati `binos-1c-v1` bilan **bir xil bo'lishi test bilan qulflangan**
(`test_discovery_1c_universal.py`) — shartnoma o'zgarsa, ikkalasi birga o'zgaradi.

## Tuzilma

```jsonc
// discovery.json
{
  "schema_version": "binos-1c-discovery-v1",
  "collector": { "name": "…", "version": "…" },
  "collected_at": "2026-09-28T09:21:40+06:00",
  "source": {
    "kind": "copy",                    // "live" — ataylab ruxsat bilan
    "platform_version": "…"  | null,
    "configuration_name": "…" | null,
    "configuration_version": "…" | null,
    "configuration_modified": true | false | null,
    "infobase_mode": "file" | "server" | "ws" | null,
    "infobase_id": "…" | null
  },
  "mappings": [
    {
      "target": "products.barcodes",
      "source_object": "…",            // metadata to'liq nomi (to'plam ICHIDAN kelgan ma'lumot)
      "source_field": "…",
      "source_kind": "information_register",
      "confidence": "CANDIDATE",
      "evidence": [ { "kind": "structural_link", "detail": "o'lchovi katalogga havola" } ],
      "row_count": "59211" | null,
      "non_null_count": "58888" | null,
      "sample_count": "5" | null,
      "errors": []
    }
  ],
  "notes": [ "…" ]
}
```

```jsonc
// status.json
{ "schema_version": "…", "status": "COMPLETE" | "PARTIAL" | "BLOCKED",
  "started_at": "…", "finished_at": "…",
  "sections": [ { "name": "metadata_sweep", "status": "ok" | "failed" | "skipped", "error": null } ],
  "blocked_reason": null }
```

Holat qoidasi: hech bir bo'lim `ok` emas → **BLOCKED** (`blocked_reason` shart); hammasi `ok` →
**COMPLETE**; aralash → **PARTIAL**.

```jsonc
// metadata_sweep.json — xom sanoq
{ "schema_version": "…", "objects": [
  { "full_name": "…", "kind": "catalog", "name": "…", "synonym": "…" | null,
    "row_count": "7137" | null, "errors": [],
    "children": [ { "name": "…", "kind": "attribute", "type": "…" | null, "synonym": null } ] } ] }

// counts.json — rekonsiliatsiya
{ "schema_version": "…", "counts": [
  { "name": "catalog_rows", "value": "7137" | null, "scope": "…", "errors": [] } ] }
//  `value` null bo'lsa — `errors` SHART.

// samples/<nom>.json
{ "schema_version": "…", "source_object": "…", "fields": ["…"],
  "rows": [["…", null]], "row_count": "7137" | null, "sample_count": "2" }
```

## Manba turlari (`source_kind`)

1C **platformasining** umumiy tushunchalari — konfiguratsiyadan mustaqil:

```
catalog · document · information_register · accumulation_register ·
chart_of_characteristic_types · enum · constant · common_attribute ·
attribute · dimension · resource · tabular_section · standard_attribute ·
virtual_table · computed · absent
```

## Mazmun xeshi

`binos-1c-discovery-content-v1` — kanonik proyeksiyadan. **Kirmaydi:** vaqt belgilari, `summary.md`,
fayl formatlanishi, qator tartibi. **Kiradi:** bog'lanishlar, dalillar, sanoqlar, metadata sanog'i,
bo'lim holatlari va **xatolar** — chunki «xato bor» ham javobning bir qismi.

Ya'ni bitta nusxani ikki marta skanerlash bir xil xesh beradi, agar javoblar o'zgarmagan bo'lsa.

## Yadro konfiguratsiyadan MUSTAQIL

`app/services/discovery_1c/` da biror konfiguratsiya yoki ijarachi nomi **yo'q**, va bu
statik test bilan qulflangan (`test_discovery_1c_universal.py`): ijarachi nomi, konfiguratsiya
oilasi, amaliy metadata nomlari va mamlakat/valyuta taxminlari taqiqlangan. 1C **platformasining**
atamalari (`Справочник`, `РегистрСведений`, `ПланВидовХарактеристик` …) ruxsat etiladi — yadroning
vazifasi aynan shularni modellashtirish.

Konfiguratsiyaga xos bilim faqat ixtiyoriy **adapter**ga tushadi (`adapters/`, hozircha bo'sh).
Adapter faqat **taklif** qiladi — u hech qachon `VERIFIED` bera olmaydi, chunki daraja dalil
turi bilan chegaralangan.
