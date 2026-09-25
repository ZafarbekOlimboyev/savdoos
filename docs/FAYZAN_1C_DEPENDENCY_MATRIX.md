# Fayzan 1C — BinOS Migrator ↔ Discovery: dependency matrix

BinOS tomonidagi 1C migratori bilan do'kondan keladigan discovery natijasi orasidagi **aniq bog'liqlik jadvali**.
Savol so'ramaydi — savollar allaqachon `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` da (8 ta savol),
do'kondagi ijro esa `docs/FAYZAN_1C_DISCOVERY.md` da (18 band).
Bu hujjat faqat shuni aytadi: **nima tayyor**, **nima bloklangan**, **nimani hozir yozsa bo'ladi**, **nimani
taxmin qilish taqiqlangan**.

| Manba hujjat | Nima uchun |
|---|---|
| `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` | 8 ta savol, skrinshot gigiyenasi, 1C ga tegmaslik qoidalari |
| `docs/FAYZAN_1C_DISCOVERY.md` | do'kondagi maydon kartasi (18 band: qayerdan topish, qanday skrinshot, nimani yashirish, nimaga tegmaslik) |
| `docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md` | bo'sh natija shabloni |
| `docs/FAYZAN_CUTOVER_RUNBOOK_DRAFT.md` | cutover ketma-ketligi (qoralama) |
| `integrations/1c/BINOS_1C_BUNDLE_V1.md` | `binos-1c-v1` fayl shartnomasi |
| `integrations/1c/MIGRATOR_V1_RUNBOOK.md` | operator quvuri (1–11 qadam) |

⚠️ **Bu hujjat MUHANDIS uchun. Do'konga OLIB BORILMAYDI.** Do'konda faqat `docs/FAYZAN_1C_DISCOVERY.md`
ishlatiladi. Quyidagi `D*` bandlari do'kon xodimiga beriladigan topshiriq EMAS — ular BinOS tomonidagi
bog'liqlikni tushuntiradi. Do'konda bajarish tartibi, kim bajarishi va xavfsizlik qoidalari faqat maydon
kartasida va ruscha so'rovnomada.

⚠️ **Raqamlash BOSHQA.** Bu hujjatdagi `D1…D32` — **bog'liqlik** raqamlari (dependency). Maydon kartasidagi
`Band 1…18` va natija shablonidagi `B01…B20` — **do'kondagi bajarish** raqamlari. Ular **bir xil EMAS**
va bitta raqam ikki joyda boshqa narsani anglatishi mumkin (masalan `D18` = «Код»/«Артикул», `B18` = tarozi
etiketkasi). O'tkazish jadvali — quyida «Bandlar o'tkazish jadvali» bo'limida. ⚠️ Hech qachon `D`-raqamini
`B`-raqami bilan almashtirib ishlatmang.

## Qanday o'qiladi

| Belgi | Ma'nosi |
|---|---|
| `(экранда tekshirilsin)` | Menyu yo'li yoki nom manbalarda TASDIQLANMAGAN — do'konda ekranda tekshiriladi |
| ⚠️ | Xavfli tugma / qaytarib bo'lmaydigan amal |
| `fayl:satr` | Repoda isbotlangan kod joyi |
| «Ruscha nom» | 1C interfeysidagi aynan nom |

**Konfiguratsiya NOMA'LUM.** Do'konda Розница 2 / УТ 11 / УНФ / Розница 3 dan qaysi biri turganini hozirgi
artefaktlarning HECH BIRI aniqlamaydi — hisobot sarlavhalari bu konfiguratsiyalarda bir xil
(`FAYZAN_1C_DISCOVERY_CHECKLIST.md:376`). Shu sababli bu hujjatda birorta registr, spravochnik yoki rekvizit
nomi yozilmagan.

**Discovery = FAQAT O'QISH.** Bu hujjatdagi birorta qadam 1C ga yozmaydi. Yo'nalish bir tomonlama: 1C → BinOS
(`apps/server/app/services/migrator_1c/__init__.py:2-4`).

---

## 0. Xavfsizlik minimumi (muhandis uchun — so'rov yozishdan OLDIN)

To'liq ro'yxat `FAYZAN_1C_DISCOVERY_CHECKLIST.md:63-94` va `docs/FAYZAN_1C_DISCOVERY.md` 1-bo'limida —
TAKRORLANMAYDI. Bu yerda faqat quyidagi `D*` bandlarini so'raganda buziladigan minimum.

**0.1 ⚠️ Bosilmaydigan tugmalar — so'ralgan oyna bilan birga keladi**

| Qayerda | ⚠️ Taqiqlangan | Qaysi bog'liqlik (D) shu oynaga olib boradi |
|---|---|---|
| Oddiy 1C | «Выгрузить данные», «Загрузить», «Очистить», «Заполнить», «Перенумеровать» | D28, D29, D30 (tarozi almashinuvi oynasi) |
| Tarozi dasturi | «Загрузить», «Выгрузить» — tarozi xotirasini o'chiradi | D27, D28, D29 |
| Konfigurator | ⚠️ **«Загрузить информационную базу…» — ishchi bazani O'CHIRADI.** So'ralgan «**Вы**грузить информационную базу…» bilan AYNAN bitta menyuda, yonma-yon turadi | D6 (`.dt`) |
| Konfigurator | «Загрузить конфигурацию из файла…», «Вернуться к конфигурации БД», «Обновить конфигурацию базы данных», «Снять с поддержки», «Включить возможность изменения», «Тестирование и исправление…» | D2, D3 (`.cf`/`.cfe`, standartmi) |
| Hisobot oynasi | «Сохранить вариант отчёта…», «Сохранить настройки» *(tugma nomi konfiguratsiyaga qarab farq qiladi — экранда tekshirilsin)* — saqlangan variant 1C ga **YOZILADI**. Sozlamalarni faqat ko'rish va suratga olish mumkin; yopishda «Сохранить?» → «Нет» | D10 (qoldiq hisoboti sozlamalari), D13 |
| Spravochnik ro'yxatlari | «Создать», «Изменить», «Пометить на удаление»; kartochka ochilmaydi, filtr/saralash o'zgartirilmaydi | D9, D13, D17–D24 |
| Har joyda | `.epf` faylini ochish — discovery kunida umuman yo'q (D7 faqat RUXSAT haqida savol) | D7 |

> Ruscha: Кнопки «Выгрузить данные», «Загрузить», «Очистить», «Заполнить», «Перенумеровать» не нажимайте.
> Если 1С спросит «Сохранить изменения?» — отвечайте «Нет».

**0.2 Kim bajaradi**

| Bog'liqlik (D) | Kim | Qachon |
|---|---|---|
| D2, D3, D6, D7 (Konfigurator, nusxa, `.epf`) | FAQAT 1C administratori yoki xizmat firmasi («для администратора» — checklist:59, 157, 179) | do'kon YOPILGAN, smenalar yopilgan kunda |
| Qolgan bandlar | operator + xodim, faqat ko'rish va skrinshot | ish vaqtida ham mumkin |

⚠️ **Kassirdan Konfigurator ishi, nusxa olish yoki `.epf` sinovi SO'RALMAYDI.** Noto'g'ri bosilgan tugma
uchun javobgarlik xodimga yuklanmaydi: tasodifan bosilsa — administratorga aytiladi, o'zi tuzatmaydi
(checklist:68).

**0.3 ⚠️ Skrinshotda YASHIRILADIGAN (bu jadval so'raydigan oynalarda bor)**

| Bog'liqlik (D) | Oyna | Yashiriladi | Yashirilmaydi |
|---|---|---|---|
| D1 | «О программе» | litsenziya raqami, internet-qo'llab-quvvatlash logini (checklist:107) | platforma/konfiguratsiya versiyasi |
| D4, D5 | «Запуск 1С:Предприятия» ulanish satri | `Usr=` / `Pwd=` qismi, parol maydoni, foydalanuvchi nomi | `File=` / `Srvr=` / `ws=` ning o'zi (checklist:90 — bu maxfiy EMAS) |
| D28, D29 | tarozi dasturi | qurilma litsenziyasi/kaliti, masofaviy kirish ID va paroli | tovar nomi va kodi |
| Hammasi | har qanday kadr | parol, PIN, AnyDesk ID/parol, odam telefoni va e-mail'i, bank rekvizitlari (checklist:88) | tovar, narx, ombor, baza nomi |

⚠️ **Parol hech qayerda YOZILMAYDI** — na javob shablonida, na chatda, na commit'da (checklist:94: faqat
og'zaki). BinOS repozitoriysiga 1C skrinshoti, eksport fayli yoki nusxa **commit qilinmaydi**.

**0.4 ⚠️ Nusxa bilan muomala (D6, D3 uchun MAJBURIY)**

`.dt` nusxada do'konning BARCHA ma'lumoti bor: yetkazib beruvchilar, xodimlar, xaridorlar va chegirma
kartalari, kassa va pul, bank rekvizitlari (checklist:199-200). `.cf`/`.cfe` ham beg'ubor emas — dasturchi
u yerga kassa yoki tarozi parolini yozib qo'ygan bo'lishi mumkin (checklist:187).

| Qoida | Manba |
|---|---|
| Egasining YOZMA roziligi: kim beradi, nima, sana, maqsad, qachon o'chiriladi, o'chirish yozma tasdiqlanadi | checklist:202-204 |
| Uzatish qo'ldan qo'lga — fleshka/disk. ⚠️ Telegram, e-mail, bulut disk — YO'Q | checklist:205-206 |
| Saqlash: internetsiz kompyuterda, hech kimga berilmaydi, ish tugagach o'chiriladi va egasiga xabar qilinadi | checklist:207-208 |
| ⚠️ Nusxa/eksport hech qanday bulut, CI, tashqi xizmat yoki AI xizmatiga yuklanmaydi; repo va artefaktlarga tushmaydi | shu hujjat qoidasi |

---

## 1. HOZIR TAYYOR

BinOS tomoni ishlaydi va fail-closed. Yagona yetishmayotgan bo'lak — 1C ICHIDAGI ekstraktor (`.epf`):
`MIGRATOR_V1_RUNBOOK.md:13` da «discovery'dan keyin yoziladi» deb belgilangan. Quvurning 2–11 qadamlari tayyor.

### 1.1 Fayl shartnomasi (`binos-1c-v1`)

| Nima ishlaydi | Fayl:satr |
|---|---|
| Ildizda AYNAN 12 kalit, whitelist'da yo'q kalit butun faylni rad etadi | `apps/server/app/services/migrator_1c/bundle.py:36-37, 148` |
| 12 kalitning HAMMASI majburiy — ixtiyoriy top-level kalit yo'q | `bundle.py:149-166` |
| `schema_version` = `binos-1c-v1`, `source_system` = `1c` qat'iy | `bundle.py:149-151` · `migrator_1c/__init__.py:26,29` |
| JSON SONI (int/float/NaN/Infinity) butun faylda taqiqlangan | `bundle.py:88-101, 332` |
| Har qanday darajada takror JSON kaliti — fayl rad | `bundle.py:79-85` |
| `.json.sha256` yon fayli MAJBURIY, 256 MB chegara, UTF-8 (BOM ruxsat), yolg'iz surrogate rad | `bundle.py:28-29, 320-351` |
| `exported_at` / `snapshot_at` — ISO 8601 va offset bilan; tzinfo yo'q bo'lsa rad | `bundle.py:137-143, 152-155` |
| `warehouses[]` / `price_types[]` = {guid, code, name}; takror GUID rad | `bundle.py:31, 40, 167-173` |
| Har `stock[].warehouse_guid` va `prices[].price_type_guid` ro'yxatlarda bo'lishi shart | `bundle.py:186-193, 222, 231` |
| `selection` = 3 kalit; `warehouse_guids` kamida bitta, takrorsiz | `bundle.py:41, 175-181` |
| `purchase_price_type_guid` = `retail_price_type_guid` bo'lsa fayl RAD | `bundle.py:182-185` |
| `products[]` da AYNAN 15 maydon ruxsat etiladi | `bundle.py:42-43, 198` |
| `kind` majburiy va {goods, service, set, other} dan biri | `bundle.py:30, 201` |
| `is_folder`, `deletion_mark`, `has_characteristics`, `has_series` — TO'RTALASI majburiy bool, null rad | `bundle.py:202-203` |
| `guid`, `code`, `article`, `name`, `plu` — tuzilma darajasida ixtiyoriy matn | `bundle.py:199-200` |
| `is_weighted` ixtiyoriy bool; `unit` ixtiyoriy obyekt {name, code} | `bundle.py:44, 204, 206-210` |
| `barcodes` / `prices` / `stock` — majburiy ro'yxat; qator ichida takror narx turi yoki ombor rad | `bundle.py:45-47, 211-234` |
| `manifest` = 5 kalit; sanoqlar fayl mazmuniga AYNAN teng bo'lishi shart | `bundle.py:48, 236-247` |
| `manifest.stock_qty_by_warehouse` kalitlari AYNAN `selection.warehouse_guids` | `bundle.py:34, 248-253` |
| Mazmun xeshi `binos-1c-content-v2` (kanonik proyeksiya; `infobase`/`extractor`/`export_id`/`exported_at` xeshga kirmaydi) | `bundle.py:274-317` · `__init__.py:31` |
| Manifest yig'indisining ETALON algoritmi (Decimal prec=60, yuvarlashsiz) | `apps/server/tests/migrator_1c_synth.py:127-146` |

### 1.2 Normalizatsiya

| Nima ishlaydi | Fayl:satr |
|---|---|
| Kanonik GUID 8-4-4-4-12 kichik harf; nol-GUID `INVALID_GUID`, bo'sh `MISSING_GUID` (qator BLOK) | `normalize.py:19-20, 44-54, 198-199` |
| Decimal regexi `-?[0-9]{1,20}(\.[0-9]{1,12})?` to'liq moslik; vergul/eksponenta/probel `INVALID_NUMBER` | `normalize.py:21, 40-41, 57-63` |
| Qty ≤ 3 kasr, narx ≤ 2 kasr, YUVARLASH YO'Q; `QTY_MAX` / `PRICE_MAX` chegaralari | `normalize.py:22-27, 66-71, 250-253, 296-301` |
| Barkod: faqat chekka probel, 6–14 ASCII raqam, belgilar o'chirilmaydi; UPC-A(12) ↔ EAN-13 bitta GTIN | `normalize.py:138-156` |
| Birlik ANIQ jadval (шт/кг/л/упак…) + OKEI 796/166/112/778 + operator `--unit-map` | `normalize.py:30-37, 159-184` · `app/tools/migrate_1c.py:120-124` |
| PLU: faqat 1–5 ASCII raqam, yetakchi nol olinadi (`PLU_LEADING_ZEROS`), aks holda `INVALID_PLU`. ⚠️ Bu 1–5 chegarasi Fayzan REAL etiketka kontrakti bilan AYNAN MOS (barkod maydoni 5 xonali — 1.6) — ziddiyat YO'Q, kengaytirish KERAK EMAS | `normalize.py:209-216` |
| Narx holatlari: MISSING / INVALID / NEGATIVE / ZERO / `PRECISION_LOSS_PRICE` | `normalize.py:232-253` |
| Kelish narxi `"0"` = to'ldirilmagan → BinOS tannarxi USTIGA YOZILMAYDI | `normalize.py:264-278` |
| Tanlanmagan ombor qoldig'i `stock_unselected` ga ajraladi — hisobotda bor, migratsiya qilinmaydi | `normalize.py:282-312` |
| `has_characteristics=true` → `CHARACTERISTICS_UNSUPPORTED` (BLOK); `has_series=true` → `LOT_DATA_PRESENT` (info) | `normalize.py:318-321` |

### 1.3 Moslashtirish (dry-run)

| Nima ishlaydi | Fayl:satr |
|---|---|
| Avtomatik bog'lanish FAQAT 1C GUID orqali (`EXACT_MATCH`, `via_guid`) | `classify.py:335, 380-387` |
| Toifalar ustuvorligi: EXCLUDED > BLOCKED > DELETED_MATCH > AMBIGUOUS > EXACT_MATCH > CANDIDATE > NEW | `classify.py:36` |
| GUID'siz dalil kalitlari AYNAN 4 ta (article, barcode, name, plu) — ular orasida ustuvorlik YO'Q | `classify.py:345-362` |
| CANDIDATE — bog'lanish EMAS; operator `LINK` yozmaguncha hech narsa birlashmaydi | `classify.py:12-14, 397-402` |
| AMBIGUOUS 3 sabab: ko'p nomzod / `IDENTITY_CONFLICT` / `MANY_TO_ONE` | `classify.py:388-416` |
| Rekonsiliatsiya XOM fayldan MUSTAQIL hisoblanadi (`raw_totals` o'z regexlari bilan) | `classify.py:59-138, 187-212` |
| Ayniyat: xom 1C = migratable + BLOCKED + EXCLUDED, har ko'rsatkich bo'yicha + manifest qayta hisobi | `classify.py:187-233` (`reconcile` + `manifest_check`) |
| `report_sha256` deterministik; muhit maydonlari (generated_at, duration_ms, database) xeshga kirmaydi | `classify.py:651-658` (`NON_CONTENT_KEYS` + `report_hash`) |
| BinOS katalog snapshot'i: identitet formati, `plu_key` (`'0575' == '575'`, raqamsiz `raw:12A`), GTIN egaligi | `catalog.py:48-64, 106-119, 153-197` |

### 1.4 Reja va siyosatlar

| Nima ishlaydi | Fayl:satr |
|---|---|
| **14** siyosat kaliti va ruxsat etilgan qiymatlari; **STANDART QIYMAT YO'Q** | `mapping.py:29-46, 209-214` |
| Mapping AYNAN bitta hisobot + eksportga bog'langan (`report_sha256`, `bundle_file_sha256`, `company_code`, `approved_by/at`) | `mapping.py:165-180` |
| `warehouse_branch` tanlangan omborlarni AYNAN qoplaydi; ikki ombor bitta filialga MUMKIN EMAS | `mapping.py:217-229` |
| Yangi mahsulot artikuli deterministik zanjir: `article` → `code` → `1C-<guid>` | `mapping.py:487-503` · `classify.py:521-522` |
| `plu` va `is_weighted` FAQAT CREATE yo'lida yoziladi; LINK'da PLU ko'chirilmaydi | `mapping.py:456-477, 504-505` · `apply.py:243-244` |
| Reja to'siqlari: katalog LIVE, allaqachon qo'llangan eksport, eskirgan snapshot, kuzatuvli mahsulot | `mapping.py:183-191` |
| Bitta BinOS mahsuloti faqat BITTA 1C qatoriga bog'lanadi | `mapping.py:507-511` |

### 1.5 CLI, darvozalar va apply

| Nima ishlaydi | Fayl:satr |
|---|---|
| 6 buyruq: verify-bundle, dry-run, mapping-template, plan, apply, verify-applied | `app/tools/migrate_1c.py:241-272` |
| Chiqish kodlari: dry-run 0/3, plan 0/2, verify-applied 0/4 | `migrate_1c.py:108, 147, 163-170, 224` |
| Ulanish faqat `DATABASE_URL` dan, hech qachon chop etilmaydi | `migrate_1c.py:30-37` |
| dry-run DB darajasida read-only (PG `default_transaction_read_only=on` + REPEATABLE READ; SQLite `mode=ro`) | `migrate_1c.py:40-80` |
| Read-only ISBOTI: ijobiy dalil + negativ nazorat (`UPDATE … WHERE 1=0`, SQLSTATE 25006); boshqa xato = isbot EMAS | `guard.py:110-137` |
| Apply darvozalari — AYNAN 7 ta ketma-ket tekshiruv: (1) `APP_ENV` allowlist `guard.py:50-51`, (2) platforma production emas `52-53`, (3) production sysid denylist `74-75`, (4) non-prod allowlist `76-78`, (5) `--expect-system-identifier` MAJBURIY va ulangan bazaga teng `79-82`, (6) hisobotdagi `database` ulangan bazaga AYNAN teng `83-87`, (7) sessiya read-only emas `88-89`. ⚠️ (1)–(2) har qanday bazada; (3)–(7) FAQAT Postgres'da (`guard.py:73`) — SQLite yo'li boshqa shoxda (`90-94`) | `guard.py:34-95` · `__init__.py:34,37` |
| Production'da apply BIRINCHI amalda `ApplyForbidden` — bitta ham qator yozilmaydi | `apply.py:97` |
| Faqat `apply --commit` yozadi; `--rehearse` doim rollback; ikkalasi ham/hech biri berilmasa SystemExit | `migrate_1c.py:176-195` |
| Apply AYNAN 6 jadvalga yozadi (+ audit_log) | `apply.py:149-161, 180-185, 240-246, 282, 325-343` |
| Qoldiq semantikasi: `CUTOVER_LEGACY_CLOSE` (T) → `CUTOVER_OPENING_BALANCE` (T+1 µs), `client_uuid = uuid5(...)` | `apply.py:311-333` |
| Do'kon qatori `FOR NO KEY UPDATE` (lock_timeout 120 s), hisobot qayta hisoblanadi → `DriftError` | `apply.py:100-146` |
| Takroriy apply: `AlreadyApplied` / `StaleSnapshotError` — yozuvsiz | `apply.py:119-127` |
| Tranzaksiya ichida post-verify bazadan o'qib isbotlaydi; yiqilsa hammasi rollback | `apply.py:167-170, 350-486` |
| Apply `settings.catalog` ni LIVE QILMAYDI — LIVE alohida `/catalog/v2/cutover-complete` qadami | `apply.py:180-181` · `app/services/catalog_import_v2.py:127-138` |
| `/catalog/v2/preview\|commit\|initial-create\|cutover-complete` production'da 403 | `app/api/v1/catalog_v2.py:47-50, 70, 99, 141, 268` |
| cutover-complete darvozalari va eskirish himoyasi | `catalog_v2.py:256-310` |
| `import_jobs` idempotentligi: `snapshot_id = 1c-bundle:<sha256>` + `ux_import_jobs_snapshot` + `content_sha256` + `hash_contract_version` | `classify.py:643-644` · `app/models/imports.py:31-49` |

### 1.6 Tarozi tomoni (BinOS)

**Etiketka shartnomasi Fayzan do'konidan olingan REAL etiketkalar bilan TASDIQLANDI** (taxmin emas):

```
27 + PLU(5) + GRAMM(5) + EAN-13 nazorat(1)   = 13 raqam
```

| Real etiketka | Bo'linishi | Natija |
|---|---|---|
| `2700345032787` | `27` · `00345` · `03278` · `7` | 3.278 kg |
| `2700565020205` | `27` · `00565` · `02020` · `5` | 2.020 kg |
| `2700537004264` | `27` · `00537` · `00426` · `4` | 0.426 kg · 350 so'm/kg · summa **149.10** |
| `2700349000560` | `27` · `00349` · `00056` · `0` | 0.056 kg · 580 so'm/kg · summa **32.48** |

To'rtalasining EAN-13 nazorat raqami qo'lda va kod bilan tekshirildi — 4/4 to'g'ri. 8–12-raqamlar
**GRAMM** ekanini etiketkaning O'ZIDAGI summa isbotlaydi: 350 × 0.426 = 149.10 va 580 × 0.056 = 32.48.

**Kanonik mapping (chalkashmasin — uchala shakl BITTA tovar):**

| Shakl | Qiymat | Qayerda |
|---|---|---|
| Etiketkada bosilgan KOD | `000537` (6 xona) | tarozi shunday chop etadi — bu **ko'rinish**, barkod maydoni EMAS |
| Barkod ichidagi PLU | `00537` (5 xona, SATR, yetakchi nollar saqlanadi) | parser AYNAN shuni qaytaradi (`scaleBarcode.ts:87`) |
| BinOS `products.plu_code` | `537` (yetakchi nolsiz) | QA PC-013 qarori, DB da shunday (`app/api/v1/products.py:38-47`) |

Solishtirish ikkala tomonni 5 xonaga to'ldirib bajariladi (`pluMatches('537','00537') = true`).
⚠️ 6 xonali KODni PLU sifatida kiritish ATAYLAB rad etiladi (`normalizePlu` → `null`) — aks holda
etiketkadagi ko'rinish barkod maydoni bilan aralashib ketadi.

| Nima ishlaydi | Fayl:satr |
|---|---|
| POS etiketka parseri: 13 raqam, prefiks AYNAN «27», PLU = 3–7-raqamlar (5 xona, SATR), gramm = 8–12-raqamlar (5 xona), gramm > 0, **EAN-13 nazorat raqami TEKSHIRILADI** (mos kelmasa — etiketka emas) | `packages/shared/src/lib/scaleBarcode.ts:79-88` |
| PLU kanonizatsiyasi: faqat raqam, 5 xonaga to'ldiriladi, 6+ xona `null` — yetakchi nol SON konversiyasida yo'qolmaydi | `scaleBarcode.ts:72-76` · `app/services/scale_barcode.py:74-84` |
| POS mahsulotni topishi uchun `is_weighted === true` VA PLU mosligi birga kerak; offline ishlaydi | `packages/shared/src/screens/POSKassa.tsx:498-509` |
| Server `GET /products/scan` ayni qoidani qo'llaydi (scale / ambiguous / none); javobda `scale.plu_code` = kanonik 5 xonali SATR («00537»), `scale.plu` esa SON bo'lib qoladi (mijoz kontrakti buzilmasin) | `apps/server/app/api/v1/products.py:487-557`, javob maydonlari `539-541` |
| Mobil BARKODNI O'ZI PARSE QILMAYDI — qarorni server beradi, shuning uchun POS/mobil/server bitta etiketkani har xil o'qiy olmaydi | `products.py:507-508` · `apps/mobile/test/core_scan_test.dart` |
| TS ↔ Python ↔ vektor fayli bitta shartnoma bilan bog'langan | `scaleBarcode.ts:28-30` · `app/services/scale_barcode.py:4-8` · `<repo ildizi>/tests/fixtures/scale_barcodes.json:2` (⚠️ `apps/server/tests/fixtures/` YO'Q — vektor fayli repo ILDIZIDA) |
| **Umumiy vektor fayli:** 4 ta REAL Fayzan etiketkasi + chegara vektorlari (10 ijobiy) va **11 manfiy** (noto'g'ri nazorat raqami, prefiks 26, ESKI `2+PLU(6)+gramm(5)` layouti, 4 xonali PLU layouti, gramm 0, 12/14 raqam, raqamsiz, bo'sh); mapping zanjiri ham shu faylda yozilgan | `tests/fixtures/scale_barcodes.json:2` (kontrakt izohi), `:3-8` (mapping zanjiri), `:9` (labels) · vitest `tests/scale-barcode.test.ts` · pytest `apps/server/tests/test_scale_barcodes.py` |
| PLU noyobligi: `ux_products_company_plu` (company doirasida, o'chirilganlar chiqarilgan) | `app/initdb.py:504-506` · `app/core/required_schema.py:517` |
| API `_norm_plu`: faqat 1–5 raqam, yetakchi nolsiz, aks holda 400 — ⚠️ bu cheklov real kontraktga AYNAN MOS (maydon 5 xonali), shuning uchun backend 6 xonaga KENGAYTIRILMADI | `app/api/v1/products.py:33-47` |
| Taroziga yuborish marshrutlari bor, lekin drayver STUB — qurilma protokoli yozilmagan | `app/api/v1/scales.py:158-192` · `app/services/scales/generic.py:25-27` |

---

## 2. BLOKLANGAN — Fayzan fakti kelmaguncha ekstraktor yozib bo'lmaydi

«So'rovnoma savoli» ustuni `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` dagi **savol raqamiga va satriga**
ishora qiladi — maydon kartasidagi `Band` raqamiga EMAS. Maydon kartasi / natija shabloni raqamlarini
quyidagi «Bandlar o'tkazish jadvali» bo'limidan oling.

### 2.1 Konfiguratsiya va kirish

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D1 | «О программе»: platforma versiyasi, konfiguratsiya nomi va versiyasi (⚠️ kadrda litsenziya raqami va internet-qo'llab-quvvatlash logini yopiladi — 0.3) | 1-savol · checklist:98-108 | `infobase.platform_version/configuration_name/configuration_version` (`bundle.py:160-162`) va BARCHA ekstraktor so'rovlari | Bundle umuman tug'ilmaydi (uchala maydon majburiy matn). Birorta registr/spravochnik nomini yozib bo'lmaydi — ular Розница 2 / УТ 11 / УНФ / Розница 3 da har xil |
| D2 | 1C standartmi yoki o'zgartirilganmi | 1(a) · checklist:110 | «Весовой», PLU kabi доп. реквизиты qayerda saqlanishi | O'zgartirilgan bo'lsa rekvizitlar tipik joyda emas; so'rov bo'sh qaytadi va buni hech qanday tekshiruv tutmaydi |
| D3 | `.cf` / `.cfe` bera oladimi | 3-savol · checklist:179-187 `(экранда tekshirilsin)` | So'rovlarni bo'sh bazada kompilyatsiya qilib sinash | Ekstraktor birinchi marta JONLI bazada ishga tushadi — sinovsiz |
| D4 | Infobase ulanish turi: `File=` / `Srvr=` / `ws=` (⚠️ satrning `Usr=` / `Pwd=` qismi va parol maydoni yopiladi — 0.3) | 2-savol · checklist:121-132 | Ekstraktor qayerda va qanday yuritilishi, `.dt` nusxa olish mumkinmi | `ws=` bo'lsa `.epf` yo'li umuman yopiq bo'lishi mumkin — quvurning 1-qadami mexanizmsiz qoladi |
| D5 | Kassa QAYSI bazada ishlaydi | 2(v) · checklist:121-132 | Eksport manbai | Noto'g'ri bazadan olingan eksport BARCHA tekshiruvlardan O'TADI, lekin jimgina eskirgan bo'ladi. Kod buni tuta olmaydi |
| D6 | `.dt` nusxa (yoki baza papkasi) berilishi | 3-savol · checklist:143-177 **+ nusxa qoidalari checklist:197-208 → 0.4-bo'lim (rozilik, uzatish, saqlash, o'chirish)** | Registr tuzilmasi: qadoq qoidasi, `has_characteristics`/`has_series` hisoblash qoidasi, birlik ro'yxati | Nusxasiz ichki nomlar taxmin qilinadi — bu TAQIQLANGAN (4-bo'limga qarang) |
| D7 | `.epf` (tashqi ishlov) ochish ruxsati / xavfsiz rejim — ⚠️ SAVOL, sinov emas: discovery kunida hech qanday `.epf` ochilmaydi | **HOZIRCHA KECHIKTIRILGAN** · checklist:350 | «read-only extraction» qadamining MEXANIZMI | Javobsiz runbook'ning 1-qadami bajarilmaydi: zaxira yo'l faqat `.dt` nusxa. **Bu band discovery'ga QAYTARILISHI kerak** (yangi savol emas — kechiktirilganini oldinga surish) |

⚠️ **D2/D3/D6/D7 bo'yicha qat'iy shartlar** (0.2 va 0.4 ga qo'shimcha):

- `.cf`/`.cfe` «xavfsiz fayl» EMAS — dasturchi u yerga kassa yoki tarozi parolini yozib qo'ygan bo'lishi mumkin
  (checklist:187). Shuning uchun u ham 0.4 dagi nusxa qoidalari bo'yicha uzatiladi va saqlanadi.
- D3 dagi «bo'sh bazada sinash» — `.cf` dan qurilgan **ALOHIDA** baza. Ishchi bazada sinov YO'Q.
- D3 ustunidagi «jonli bazada sinovsiz ishga tushadi» — bu qabul qilingan yo'l emas, **xavf ta'rifi**.
  Ekstraktor jonli bazaga faqat quyidagi shartlar bilan yaqinlashadi: kod faqat o'qishga ekani tasdiqlangan
  (5-bo'lim, DoD 6), avval nusxada ishlatilgan, do'kon yopilgan, administrator yonida, egasining roziligi bor.

### 2.2 Ombor va qoldiq

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D8 | Haqiqiy zal ombori(lari) va ularning GUID'i | 5(a) · checklist:230 | `selection.warehouse_guids` (`bundle.py:176-177`), `warehouse_branch` (`mapping.py:221-223`) | Noto'g'ri ombor tanlansa qoldiq faylda BO'LADI, lekin migratsiya QILINMAYDI (`normalize.py:286-292`) — natija JIM nol qoldiq |
| D9 | Omborlar/magazinlar ro'yxati qaysi spravochnikda | 5-savol · checklist:236-239 `(экранда tekshirilsin)` | `warehouses[]` to'liq ro'yxati | Ro'yxat to'liq bo'lmasa har `stock[].warehouse_guid` rad etiladi (`bundle.py:186-193`) |
| D10 | Ishonchli qoldiq hisoboti nomi + uning sozlamalari (qaysi ko'rsatkich: «Конечный остаток» / «В наличии» / «Доступно») | 5(b) · checklist:231, 240-249, 329 | `manifest.stock_qty_by_warehouse` ning MA'NOSI va rekonsiliatsiya «Итого» manbai | Eksport «to'liq» ekanini isbotlaydigan YAGONA mexanizm yo'qoladi (`BINOS_1C_BUNDLE_V1.md:95-97`) |
| D11 | Savdo 1C qoldig'ini QACHON kamaytiradi (darhol / smena yopilganda / kechqurun) | 4(b)(v) · checklist:218-220 | «short freeze» oynasining uzunligi, `snapshot_at` ishonchliligi | Kechikish bo'lsa 1C qoldig'i haqiqatdan ko'p. Noto'g'ri snapshot vaqti bilan ikkinchi urinish ham `StaleSnapshotError` bilan bloklanadi (`apply.py:119-127`) |
| D12 | `snapshot_at` uchun do'kon serverining vaqt zonasi | checklist:339-340 | ISO 8601 offset (MAJBURIY — `bundle.py:137-143`) | Offset noto'g'ri bo'lsa snapshot taqqoslash (`AlreadyApplied` / `StaleSnapshotError`) noto'g'ri ishlaydi |
| D32 | Kassir savdosi QAYERDA bajariladi: 1C ichidagi «РМК» / Frontol / Штрих-М / 1С:Касса / boshqa dastur ⚠️ raqam ro'yxat oxiriga qo'shilgan (mavjud D-raqamlari surilmasligi uchun), ma'no jihatdan bu qator **D11 dan OLDIN** o'qiladi | 4(a) · checklist:217 | 1C qoldig'i umuman ishonchlimi; freeze qadamining egasi | Savdo 1C dan TASHQARIDA bo'lsa 1C qoldig'i haqiqatdan doim katta, va kod buni aniqlay olmaydi — faqat «eskirgan snapshot» darvozasi bor (`apply.py:125-127`). Ya'ni butun qoldiq haqiqiyligi 9/10-bosqichdagi «final fresh snapshot + freeze» ga tayanadi |

> Ruscha (checklist:230 dan): На каком складе в 1С числится товар, который реально стоит в зале?

### 2.3 Narx

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D13 | «Виды цен» to'liq ro'yxati va u qaysi spravochnikda | 6-savol · checklist:264-267 `(экранда tekshirilsin)` | `price_types[]` | Ro'yxatda yo'q narx turiga havola butun faylni rad etadi (`bundle.py:222`) |
| D14 | Kassa QAYSI narx turi bilan sotadi | 6(a) · checklist:258 | `selection.retail_price_type_guid` (MAJBURIY) | **Eng xavfli bo'shliq:** noto'g'ri narx turi BUTUN katalogga noto'g'ri narx beradi va bundle darajasida HECH QANDAY XATO BERMAYDI |
| D15 | Chakana narx qo'lda kiritiladimi yoki naceнка bilan avtomatik hisoblanadimi | 6(b) · checklist:259 | Ekstraktorning narx o'qish USULI | Avtomatik hisoblansa registrni oddiy o'qish bo'sh yoki eskirgan narx beradi → ommaviy `MISSING_PRICE` yoki jim eskirgan narx |
| D16 | «Цена поставщика» yangilanadimi | 6(v) · checklist:260 | `selection.purchase_price_type_guid` berilishi yoki `null` qoldirilishi | Eskirgan tur berilsa tannarx va COGS buziladi. Chakana bilan bir xil qo'yilsa fayl RAD (`bundle.py:182-185`) |

> Ruscha (checklist:258 dan): По какой цене продаёт касса — «Розничная цена» или другой вид цены?

### 2.4 Tovar kartochkasi

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D17 | `Ссылка` (GUID) ni o'qish imkoni | 3 / 7-savol · checklist:370 | `products[].guid` — `XMLСтрока(Ссылка)` (shartnoma: `BINOS_1C_BUNDLE_V1.md:37`; qabul qilinadigan shakl: `normalize.py:19-20`) | 2026-08 dagi 3 ta eksportda bu ustun YO'Q edi. GUID'siz har qator `MISSING_GUID` bilan BLOKLANADI (`normalize.py:198-199`) va avtomatik moslashtirish umuman yo'q — 7137 mahsulot qo'lda qarorga qoladi |
| D18 | «Код» va «Артикул» kartochkada qayerda, formati (yetakchi nollar) va noyobligi | 7-savol · checklist:291 | `products[].code` → BinOS `sku` (`mapping.py:504-505`); artikul zanjiri (`mapping.py:487-503`) | O'sha 3 faylda bu ustunlar ham YO'Q (checklist:370). Zanjir jimgina `1C-<guid>` ga tushadi va LINK dalillari kamayadi |
| D19 | «Весовой» belgisi: alohida rekvizitmi, tovar turi darajasidami, yoki faqat birlik «кг» mi | 7 / 8-savol · checklist:291 | `products[].is_weighted` | **`null` qoldirish XAVFSIZ EMAS:** qiymat `unit_code == 'kg'` dan kelib chiqadi (`normalize.py:207`) — «кг» birlikdagi HAR bir tovar avtomatik vaznli bo'lib qoladi |
| D20 | 1C da uchraydigan BARCHA birlik nomlari | 7-savol · checklist:291 | `--unit-map` jadvalini oldindan to'ldirish (`normalize.py:159-173`) | Jadvalda yo'q birlik `UNKNOWN_UNIT` beradi va siyosat `block`/`skip_row` — noma'lum birlik BUTUN qatorni chiqarib tashlaydi |
| D21 | «Характеристики» ishlatiladimi va nechta tovarda | 7(a) · checklist:279 | `products[].has_characteristics` (MAJBURIY bool) | `true` qator BLOCKED bo'ladi (`normalize.py:318-319`) — V1 bu tovarlarni umuman ko'chira olmaydi. Hajmi bilinmasa pilot qamrovini aytib bo'lmaydi (214 takror nom guruhi shu javobga bog'liq) |
| D22 | «Серии» (partiya / muddat) ishlatiladimi | 7(b) · checklist:280 | `products[].has_series` (MAJBURIY bool) | Faqat info (`LOT_DATA_PRESENT`), lekin BinOS'da kuzatuvli mahsulot bo'lsa reja RAD etiladi (`mapping.py:190-191`) |
| D23 | `has_characteristics` / `has_series` ni QATOR darajasida qanday hisoblash | checklist:334-336 + nusxa | Ikkala majburiy boolning manbai | Registr tuzilmasini ko'rmasdan qoida yozib bo'lmaydi; `null` yuborilsa fayl butunlay rad (`bundle.py:202-203`) |
| D24 | «Упаковка» filtri qoidasi (koeffitsiyent bo'yicha barkod/narx) | checklist:332-333 | Barkod va narx qatorlarini tashlash/`null` qilish qoidasi | Hozir faqat statistik dalil bor (qadoq deyarli ishlatilmaydi — checklist:42-45). Dalil qoidani yozishga YETMAYDI: koeffitsiyenti ≠ 1 qator jimgina ko'chib ketadi |

### 2.5 Tarozi va PLU

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D25 | **REAL etiketka fotosi (2–3 dona)** — prefiks, uzunlik va 8–12-raqamlar mazmuni ✅ ANIQ (`27`+PLU(5)+GRAMM(5)+nazorat, 1.6); kerakli fakt endi — do'kondagi QOLGAN tarozilar ham AYNAN shu kontraktda bosadimi | 8-savol · checklist:310-311 | `scaleBarcode.ts:79-88` parserining Fayzan uchun to'g'riligi | ✅ **YOPILDI — vazn/narx savoli real dalil bilan hal bo'ldi.** 4 ta etiketka olindi: prefiks `27`, 8–12-raqamlar GRAMM. Isbot — etiketkadagi summaning O'ZI: 350 × 0.426 = 149.10 va 580 × 0.056 = 32.48 (1.6 ga qarang). Parser shu kontraktga keltirildi va nazorat raqamini tekshiradi. ⚠️ **Band BEKOR QILINMAYDI**, lekin maqsadi o'zgardi: endi «formatni aniqlash» emas, «do'kondagi HAR BIR tarozi AYNAN shu kontraktda bosishini TASDIQLASH» (boshqa tarozi boshqacha bosishi mumkin — D28) |
| D26 | Etiketkadagi PLU maydonining HAQIQIY xonasi | 8-savol · checklist:310 | `products[].plu` ni chiqarish mumkinmi | ✅ **YOPILDI — ziddiyat YO'Q edi.** Real maydon **5 xonali** (`27` dan keyingi 5 raqam: `00345`, `00565`, `00537`, `00349`). BinOS API cheklovi (`products.py:33-35`) va migrator qoidasi (`normalize.py:211`) shu kontraktga AYNAN mos — backend 6 xonaga **kengaytirilmadi**. Kanonik shakl 5 xonali SATR, yetakchi nollar saqlanadi (`scaleBarcode.ts:72-76`); etiketkada bosilgan 6 xonali KOD (`000537`) PLU sifatida ATAYLAB rad etiladi. Mapping zanjiri 1.6 da |
| D27 | PLU ning HAQIQIY manbai: 1C rekviziti / tarozi dasturi (1C dan tashqarida) / faqat tovar nomi | 8(b) · checklist:305 | `products[].plu` ustuni | ⚠️ **HAMON OCHIQ va endi bu 2.5 dagi ASOSIY blokerdir.** D25/D26 etiketka SHAKLINI yopdi, lekin PLU QIYMATLARI 1C dan qayerdan olinishini YOPMADI. 1C da maydon bo'lmasa `plu` null qoladi va PLU ikkinchi manbadan alohida bosqichda keladi. Nomdan ajratish TAQIQLANGAN (checklist:337-338) |
| D28 | Tarozilar soni, marka/modeli, kodlar bir xilmi | 8(a) · checklist:304 | `plu_collision` siyosati va cutover'dan keyingi tarozi qayta yuklash qadami | Har tarozida boshqa kod bo'lsa bitta `plu_code` maydoni (kompaniya doirasida noyob) yetmaydi — BinOS tomonida yangi qaror kerak |
| D29 | Tovarlar taroziga QANDAY tushadi (1C eksporti / qo'lda / tarozi dasturi) | 8(v) · checklist:304 | Cutover'dan keyingi qadam egasi | BinOS drayveri STUB (`scales/generic.py:25-27`) — bu qadam hozir umuman yo'q |
| D30 | Список9 QAYSI oyna/hisobotdan saqlangan | 8(g) · checklist:307 | Shtrix-kod registrini o'qish yo'li + qadoq qoidasi | Список9 dagi 59 211 qator / 58 888 noyob barkodning (checklist:369) QAYSI registrdan kelgani isbotlanmaydi; ekstraktor to'g'ri oynadan o'qiyotganini ko'rsatib bo'lmaydi. ⚠️ BinOS'dagi 12603 barkod (`BINOS_MOBILE_PILOT_CHECKLIST.md:226`) BOSHQA sanoq — uni 1C manbasining dalili sifatida ishlatmang |

> Ruscha (checklist:310 dan): Сфотографируйте, пожалуйста, 2–3 настоящие этикетки с весов — цифры под штрихкодом,
> вес и название товара должны читаться.

### 2.6 Cutover tashkiliy tomoni

| # | Kerakli fakt | So'rovnoma savoli | Nimani ochadi | Fakt bo'lmasa — aniq zarar |
|---|---|---|---|---|
| D31 | Cutover kuni savdoni kim to'xtatadi, smenalar, APPLY ni kim YOZMA tasdiqlaydi | eski 30–32 · checklist:361 | Runbook'ning «short freeze» va «APPLY» qadamlaridagi mas'ul/imzo satri | Qadam egasiz qoladi; `approved_by` / `approved_at` bo'sh bo'lsa reja umuman qurilmaydi (`mapping.py:176-180`) |

⚠️ **D31 — javobgarlik va shaxsiy ma'lumot chegarasi:**

- APPLY ni **do'kon egasi yoki u yozma vakolat bergan mas'ul** tasdiqlaydi. Kassirdan yoki tarozi xodimidan
  qaytarib bo'lmaydigan ma'lumot amaliyotiga rozilik SO'RALMAYDI — ular faqat o'z ishi (smena yopish, savdoni
  to'xtatish) bo'yicha xabardor qilinadi.
- Tasdiq matnida APPLY ning ma'nosi ochiq yozilgan bo'lishi shart: katalog va qoldiq BinOS'ga ko'chiriladi,
  qaytarish faqat zaxiradan tiklash orqali.
- `approved_by` mapping fayliga va rejaga tushadi (`mapping.py:142-143, 178, 599`) — u yerga **lavozim + ism**
  yoziladi, egasi bilan kelishilgan holda. ⚠️ Telefon, pasport, shaxsiy manzil yoki boshqa shaxsiy ma'lumot
  yozilmaydi; bu fayl artefakt sifatida saqlanadi.

### 2.7 Bandlar o'tkazish jadvali (D ↔ maydon kartasi ↔ natija shabloni)

⚠️ Raqamlar **bir xil emas**. Bu jadval yagona to'g'ri o'tkazish yo'li.

| D (bu hujjat) | Maydon kartasi `docs/FAYZAN_1C_DISCOVERY.md` | Natija shabloni `..._RESULT_TEMPLATE.md` | Shablondagi daraja |
|---|---|---|---|
| D1 | Band 1 — «О программе» | B01 | STOP |
| D2 | Band 2 — o'zgartirilganmi | B02 | STOP |
| D3 | Band 5 — `.cf` / `.cfe` | B05 | shartli STOP |
| D4, D5 | Band 3 — infobase ulanishi (`File=`/`Srvr=`/`ws=`, kassa qaysi bazada) | B03 | STOP |
| D6, D17 | Band 4 — `.dt` nusxa (GUID manbai) | B04 (+ `B04-rozilik`) | STOP |
| D7 | Band 4 ichidagi og'zaki savol — `.epf` ruxsati | B19 | STOP |
| D8, D9 | Band 8 — haqiqiy zal ombori va omborlar ro'yxati | B08 | STOP |
| D10 | Band 9 — qoldiq hisoboti nomi va sozlamalari | B09 | STOP |
| D11 | Band 7 — savdo 1C'ga qachon tushadi | B07 | REJA |
| D12 | ⚠️ Band 3 ichidagi «server soati/zonasi» maydoni | B03 (vaqt zonasi qatori) | REJA |
| D13 | Band 10 — «Виды цен» | B10 | STOP |
| D14, D15, D16 | Band 11 — kassadagi narx turi | B11 | STOP |
| D18, D20 | Band 12 — oddiy tovar kartochkasi («Код», «Артикул», birlik). ⚠️ **D20 (1C dagi BARCHA birlik nomlari) do'konda YOPILMAYDI** — ikki kartochka to'liq ro'yxatni bermaydi; ro'yxat nusxadan chiqadi, do'kondan faqat namuna keladi | B12 | STOP |
| D19 | Band 13 — vaznli tovar kartochkasi («Весовой») | B13 | STOP |
| D21, D23 | Band 14 — Характеристики. ⚠️ **D23 (qator darajasidagi hisoblash qoidasi) do'konda YOPILMAYDI** — u registr tuzilmasini, ya'ni nusxani talab qiladi | B14 | STOP |
| D22, D23 | Band 15 — Серии (D23 bo'yicha yuqoridagi izoh shu yerda ham amal qiladi) | B15 | REJA |
| D24 | ⚠️ do'konda SO'RALMAYDI — qoida faqat nusxadan (`.dt`) yoziladi | — | — |
| D25, D26 | Band 18 — real etiketka fotosi va PLU xonasi. ✅ kontrakt TASDIQLANDI (1.6); band QOLADI, maqsadi endi — shu do'kondagi HAR BIR tarozi AYNAN shu kontraktda bosishini tasdiqlash | B18 | STOP (tasdiqlash) |
| D27, D30 | Band 17 — PLU manbai va `Список9` oynasi | B17 | STOP |
| D28, D29 | Band 16 — tarozilar soni/modeli va tovar qanday tushadi | B16 | REJA |
| D31 | ⚠️ maydon kartasida band YO'Q — cutover rejasi uchrashuvi | B20 | REJA |
| D32 | Band 6 — kassir savdosi qayerda bajariladi | B06 | REJA |

**Teskari o'qish uchun izoh:** maydon kartasining 18 bandi shu jadvalda **to'liq** qatnashadi (Band 1–18),
shablonning qo'shimcha ikki bandi (B19, B20) D7 va D31 ga ketadi. Shablonda **bandi yo'q** yagona bog'liqlik —
**D24** («Упаковка» filtri): u do'konda so'ralmaydi, javobi faqat baza nusxasidan chiqadi (4-bo'lim, T8).

---

## 3. HOZIRDANOQ UNIVERSAL QILINADIGAN

Konfiguratsiya nomini bilmasdan ham qat'iy yozilishi mumkin bo'lgan ish. «Nega xavfsiz» ustuni — buning asosi.

| # | Ish | Nega xavfsiz |
|---|---|---|
| U1 | Fayl qatlami spetsifikatsiyasi: `.json` + majburiy `.json.sha256`, 256 MB, UTF-8 (BOM ruxsat) | Tekshiruv kodda qat'iy va 1C turiga umuman qaramaydi — `bundle.py:28-29, 320-351` |
| U2 | JSON qat'iyligi: son taqiqi, takror kalit taqiqi, whitelist'dan tashqari kalit taqiqi | `bundle.py:36-48, 79-101` — fayl darajasidagi qoida, ma'lumot manbaiga bog'liq emas |
| U3 | Barcha identifikatorlar MATN va yetakchi nollar saqlanadi | 1C turidan qat'i nazar `0000123` son sifatida `123` bo'lib qolardi — `bundle.py:199-200`, `BINOS_1C_BUNDLE_V1.md:22` |
| U4 | Kanonik GUID shakli (kichik harf 8-4-4-4-12; nol-GUID `normalize` da rad — `bundle.py:31` regexi uni O'TKAZADI) | `bundle.py:31`, `normalize.py:44-54`, shartnoma `BINOS_1C_BUNDLE_V1.md:37` — `XMLСтрока(Ссылка)` platforma funksiyasi, konfiguratsiya obyektlari emas |
| U5 | Decimal matn regexi va aniqlik siyosati (qty ≤ 3, narx ≤ 2, YUVARLASH YO'Q, MAX chegaralari) | `normalize.py:21-27, 66-71` — matn qiymatiga qo'llanadi, metadata nomiga emas |
| U6 | Barkod normallashtirish: faqat trim, 6–14 ASCII raqam, UPC-A ↔ EAN-13 bitta GTIN | `normalize.py:138-156` — barkod standarti 1C ga bog'liq emas |
| U7 | PLU kanonizatsiyasi va BinOS `plu_key` solishtiruvi | `normalize.py:209-216`, `catalog.py:58-64` — BinOS tomonidagi invariant. ✅ Real etiketka kontrakti (5 xonali maydon) bu invariantni **tasdiqladi**, o'zgartirmadi: `'0575' == '575'` qoidasi etiketkadagi `00537` ↔ DB dagi `537` mosligi bilan bir xil mantiq (1.6) |
| U8 | Birlik jadvali (шт/штука/кг/л/литр/упак + OKEI 796/166/112/778) va `--unit-map` kengaytmasi | Jadval MATN qiymatlariga bog'langan, konfiguratsiyaga emas; to'qnashuv bo'lsa xato beradi, jimgina ustiga yozilmaydi — `normalize.py:30-37, 159-184` |
| U9 | Kelish narxi `"0"` = to'ldirilmagan → BinOS tannarxi ustiga yozilmaydi | `normalize.py:264-278` — qiymat semantikasi, manba semantikasi emas |
| U10 | EXCLUDED mantig'i: papka, o'chirish belgisi, `kind != goods` | `bundle.py:201-203`, `classify.py:49-56` — `kind` enum'i shartnomada qat'iy |
| U11 | **Ekstraktor BARCHA omborlar va BARCHA narx turlarini chiqaradi; tanlovni OPERATOR `selection` da qiladi** | Shu sababli D8/D14 javobi ekstraktor KODINI emas, faqat `selection` ni o'zgartiradi — `bundle.py:226-234`, `normalize.py:286-292` |
| U12 | Manifest hisoblash algoritmi (4 sanoq + tanlangan omborlar bo'yicha Decimal yig'indi, prec=60, yuvarlashsiz) | Etalon implementatsiya tayyor — `tests/migrator_1c_synth.py:127-146` |
| U13 | Mazmun xeshi v2 proyeksiyasi va `snapshot_id = 1c-bundle:<file_sha256>` idempotentligi | `bundle.py:274-317`, `classify.py:643-644` — xesh 1C metadatasini o'z ichiga OLMAYDI |
| U14 | BinOS identitet shartnomasi: `external_id` = kanonik GUID, `source_system = '1c'`, `sku` = 1C «Код», artikul zanjiri | `apply.py:240-244`, `mapping.py:492-505` — BinOS tomonidagi qaror |
| U15 | Read-only isbot mexanizmi (ijobiy dalil + negativ nazorat, SQLSTATE 25006) | `guard.py:110-137` — DB darajasida, 1C ga aloqasi yo'q |
| U16 | Apply darvozalari (APP_ENV, platforma, sysid deny/allow, `--expect-system-identifier`, hisobot bazasi aynanligi) | `guard.py:34-95` — muhit darvozalari |
| U17 | Rekonsiliatsiya ayniyati va manifest qayta hisobi | `classify.py:187-233` — hisob-kitob mantiqi o'zgarmaydi; faqat «Итого» MANBASI discovery'ga bog'liq (D10) |
| U18 | **14** siyosat kaliti va «standart qiymat YO'Q» qoidasi | `mapping.py:29-46` — `POLICY_CHOICES` da AYNAN 14 ta kalit bor (sanab chiqilgan); discovery faqat QAYSI siyosat kerak bo'lishini o'zgartiradi, ro'yxatni emas |
| U19 | Qoldiq semantikasi (LEGACY_CLOSE → OPENING_BALANCE, `client_uuid = uuid5(...)`, `inventory_before` aynanligi) | `apply.py:294-343` — BinOS tomonidagi yozuv modeli |
| U20 | Cutover ketma-ketligi (discovery → nusxa → read-only extraction → bundle validation → dry-run → GUID mapping → conflicts → totals reconciliation → final fresh snapshot → short freeze → APPLY → post-apply verify → BinOS truth) | ⚠️ **1:1 EMAS.** 13 band mavjud runbook'ning 11 qadamiga shunday tushadi (`MIGRATOR_V1_RUNBOOK.md:9-26`): discovery va nusxa — runbook'dan OLDIN (runbook 1-qadami eksportdan boshlanadi, `RUNBOOK:13`); read-only extraction = 1; bundle validation = 2; dry-run = 3; **totals reconciliation — alohida qadam emas, dry-run ichida** (`classify.py:187-233`, chiqish kodi 3); GUID mapping = 4; conflicts = 5 (+ reja 6, rehearsal 7); final fresh snapshot = 8; **short freeze — alohida qadam emas, 8-qadam ichida** («1C savdosini to'xtatish», `RUNBOOK:20`); APPLY = 9; post-apply verify = 10; BinOS truth = 11 |
| U21 | **Ekstraktor SHABLONI**: JSON yozuvchi, manifest hisoblovchi, SHA256 yozuvchi qism | Bu qismlar chiqish formatiga bog'langan, ma'lumot o'qish so'rovlariga emas. Faqat so'rovlar konfiguratsiyaga bog'liq qoladi |
| U22 | `plu` va `is_weighted` ni `null` qoldirish YO'LI qonuniy — PLU'siz migratsiya rejasi | `bundle.py:204`, `normalize.py:207-216`. ⚠️ Lekin `is_weighted = null` zararsiz EMAS (D19 ga qarang) |
| U23 | Etiketka fotosidan yoziladigan javob formati: 13 raqamning aynan nusxasi + etiketkadagi vazn + summa + tovar nomi + tarozi modeli | ✅ **Format ISHLADI:** aynan shu to'plam (13 raqam + vazn + summa) prefiks (D25), PLU xonasi (D26) va vazn/narx savolini bir vaqtda yopdi — summa bo'lmasa gramm/narx farqini isbotlab bo'lmasdi (1.6). Tarozi modeli D28 ga ketadi va HALI kelmagan. 1C turiga bog'liq emas. ⚠️ Etiketkadagi SUMMA va tarozi modeli checklist:310-311 dagi foto talabida YO'Q — ular 8(a) javobi va foto bilan birga alohida so'raladi; **qolgan tarozilar uchun shu format qayta ishlatiladi** |
| U24 | Nom bilan ishlash: nom AYNAN xom holida eksport qilinadi, ulash kaliti NFKC + casefold + probel siqish | `app/services/catalog_match.py:50-52`; 1C nomlarida 532 qo'sh probel bor (`apps/server/tools/import_1c.py:122`) |
| U25 | Skrinshot gigiyenasi, 1C ga tegmaslik va nusxa qoidalari | checklist:63-94 va 197-208 da tayyor + maydon kartasining 1-bo'limi — TAKRORLANMAYDI, ishora qilinadi. Bu hujjatning 0-bo'limi faqat SHU jadval so'raydigan oynalar uchun minimumni beradi |

---

## 4. TAXMIN QILISH TAQIQLANGAN

Bu ro'yxatdagi birorta narsa «odatda shunday bo'ladi» deb yozilmaydi. Har biri uchun: nega jozibador ko'rinadi,
noto'g'ri taxmin qanday JIM buzilishga olib keladi, va to'g'ri yo'l.

| # | TAQIQLANGAN taxmin | Nega jozibador (dalil) | Jim buzilish | To'g'ri yo'l |
|---|---|---|---|---|
| T1 | «Bu Розница 2» (yoki УТ 11 / УНФ / Розница 3) | Mavjud hisobotlar shu ko'rinishda | Hisobot sarlavhalari Розница va УТ da BIR XIL (checklist:376). Noto'g'ri registr nomi bilan yozilgan so'rov ma'lumot beradi — lekin BOSHQA o'lchovni | D1: «О программе» |
| T2 | «Haqiqiy qoldiq «Основной» omborda» | astatka.xls da «Магазин» → «Основной» guruhi ko'rindi (checklist:368) | Tanlanmagan ombor qoldig'i faylda bo'ladi, lekin migratsiya QILINMAYDI — natija jim NOL qoldiq (`normalize.py:286-292`) | D8: 5(a) javobi + ombor GUID'i |
| T3 | «Kassa «Розничная цена» bilan sotadi» | sena.xls da aynan shu tur bor (checklist:367) | Butun katalog noto'g'ri narxda ochiladi va bundle darajasida HECH QANDAY xato bermaydi | D14: 6(a) javobi |
| T4 | «Birlik «кг» bo'lsa — vaznli» | Kodda zaxira shunday (`normalize.py:207`) va astatka da 454 ta кг bor | Ikki tomonlama zarar: donali tovar vaznli bo'lib qoladi, YOKI vaznli tovar donali bo'lib POS etiketkani hech qachon o'qimaydi (`POSKassa.tsx:502`) | D19: «Весовой» rekviziti qayerda |
| T5 | «PLU ni tovar nomidan ajratib olamiz» | Nomlarda kod bor, shablon ham yozilgan (`scripts/fayzan_held_report.py:89`), 465 ta topilgan | Yozilishi bir xil emas («148Код», «Код594», «476Корд»), 2 tasi takror. Bu satrlar tarozi xotirasidagi PLU ga TENG ekani hech qayerda isbotlanmagan → `PLU_COLLISION` yoki BUTUNLAY BOSHQA tovar sotiladi | D27 + D25. Kontraktda qat'iy taqiq: checklist:337-338 |
| T6 | ~~«Etiketka «2» + 6 + 5 formatda»~~ → endi: «BARCHA tarozilar `27`+5+5 bosadi» | Eski parser aynan `2`+6+5 deb o'qirdi va bu **NOTO'G'RI** edi: prefiksning ikkinchi raqami PLU maydoniga oqib kirardi (`2700537004264` → PLU `700537`). Kontrakt endi real etiketka bilan tasdiqlangan (1.6) | **Taxmin qismi HAMON taqiqlangan:** dalil 4 ta etiketkadan va (ehtimol) BITTA tarozidan. Boshqa marka/model boshqa prefiks yoki boshqa maydon tartibida bosishi mumkin — u etiketka vaznli deb qabul qilinmaydi va o'sha tovarlar sotilmaydi | D25 + D28: qolgan tarozilardan ham etiketka olinadi, modeli/soni bilan |
| T7 | «PLU 1–5 xonali» — ✅ endi TAXMIN emas, TASDIQLANGAN fakt | BinOS API shunday cheklaydi (`products.py:33-35`) **va real etiketka maydoni ham AYNAN 5 xonali** (`00345`/`00565`/`00537`/`00349`) | Eski da'vo («etiketka maydoni 6 xonali») parser nuqsonidan kelib chiqqandi — u prefiksning `7` ini PLU ga qo'shib o'qirdi (`digits.slice(1, 7)`, tuzatishdan OLDINGI `scaleBarcode.ts:31` — commit `e8109b2`; joriy faylda bu satr YO'Q, kanonik uzunlik `scaleBarcode.ts:37` da **5**). Chegara ziddiyati YO'Q; backend kengaytirilmaydi. ⚠️ Qolgan xavf: etiketkada bosilgan 6 xonali KOD (`000537`) ni PLU deb kiritish — bu ATAYLAB rad etiladi (`scaleBarcode.ts:72-76`) | D26 YOPILDI. Ochiq qolgani — D27 (PLU qiymatlari manbai) |
| T8 | «Qadoq ishlatilmaydi, filtr shart emas» | Dalil kuchli: 59 211 qatordan 1 tasi, sena da 0, astatka da «Упак.» = «Количество» (checklist:42-45) | Dalil STATISTIK, qoida emas. Koeffitsiyenti ≠ 1 bo'lgan barkod/narx qatori jimgina ko'chib ketadi | D24: registr tuzilmasi (nusxa) |
| T9 | «Tovarda Код va Артикул bor» | Kartochkada bo'lishi kutiladi | 2026-08 dagi 3 ta eksportda bu ustunlar YO'Q (checklist:370). Artikul zanjiri jim `1C-<guid>` ga tushadi va LINK dalillari kamayadi | D18: kartochka skrinshoti |
| T10 | «GUID ni boshqa ustundan olamiz» | Eksport fayllari bor-ku | Shartnoma GUID manbaini AYNAN `XMLСтрока(Ссылка)` deb belgilaydi (`BINOS_1C_BUNDLE_V1.md:37`); eksport ustunlaridan tiklab bo'lmaydi. GUID'siz har qator `MISSING_GUID` | D17: nusxa yoki `.epf` |
| T11 | «`has_characteristics = false` deb qo'ya qolamiz» | Majburiy bool, tezroq to'ldiriladi | Xarakteristikali tovar BLOCKED bo'lmay, noto'g'ri narx/qoldiq bilan KO'CHIB KETADI (`normalize.py:318-319` chetlab o'tiladi) | D21 + D23: qator darajasidagi hisoblash qoidasi |
| T12 | «`has_series = false` deb qo'ya qolamiz» | Xuddi shunday | `LOT_DATA_PRESENT` info yo'qoladi — partiya siyosati bo'yicha qaror noto'g'ri asosda qabul qilinadi | D22 |
| T13 | «Savdo 1C ga darhol tushadi» | Oddiy holat | Freeze oynasi qisqa yoziladi; 1C qoldig'i haqiqatdan ko'p bo'ladi va buni HECH QANDAY tekshiruv tutmaydi (kod savdo kechikishini aniqlay olmaydi) | D11: 4(b)(v) javobi |
| T14 | «Ikki omborni bitta filialga yig'amiz» | Fayzan'da bitta filial | `mapping.py:227-228` buni RAD etadi — qoldiqni yig'ish taxmin bo'lardi | D8: 1:1 xarita |
| T15 | «Nusxa bo'lmasa `.cf` yetadi» | `.cf` da butun tuzilma bor | Qo'shimcha rekvizitlar (доп. реквизиты) va qo'shimcha ishlovlar `.cf` ga KIRMAYDI (checklist:326-328) — aynan PLU va «Весовой» o'sha yerda bo'lishi mumkin | D2 + D6: rekvizitlar ro'yxati skrinshoti |
| T16 | «`.epf` ni do'konda ocha olamiz» | Ekstraktor shunday ishlaydi | Xavfsiz rejim yoki siyosat taqiqlagan bo'lishi mumkin — do'kondagi ish o'sha yerda to'xtaydi | D7: bandni discovery'ga qaytarish |
| T17 | «Eksport fayllari o'sha ishchi bazadan» | Do'kon shunday yuborgan | Noto'g'ri bazadan olingan eksport BARCHA tekshiruvlardan o'tadi va jimgina eskirgan bo'ladi | D5: 2(v)/2(g) javobi |
| T18 | «Menyu yo'li shunday» (omborlar, «Виды цен», «Номенклатура», «Подключаемое оборудование») | Checklist'da yo'llar berilgan | Checklist'ning O'ZI bir qism yo'llarni `(проверить на экране)` deb belgilaydi: checklist:183, 185, 188, 236, 266, 286, 313. ⚠️ **LEKIN belgisiz qolgan, konfiguratsiyaga bog'liq yo'llar ham bor:** qoldiq hisoboti (checklist:241-242), «Виды цен» Розница 2 va Розница 3/УНФ (checklist:265, 267), «Номенклатура» Розница 2 va Розница 3/УНФ (checklist:285, 287). Belgi yo'qligi TASDIQ degani EMAS | Har yo'l — belgilanganmi yoki yo'qmi — `(экранда tekshirilsin)` sifatida olib o'tiladi; D1 javobi kelgach faqat bitta konfiguratsiya qatori qoldiriladi |

⚠️ **Umumiy qoida:** bu jadvaldagi har bir taxminning zarari JIM — na `verify-bundle`, na `dry-run`, na
post-verify uni tutadi, chunki fayl SINTAKTIK jihatdan to'g'ri bo'ladi. Tekshiruvlar faylning shaklini
isbotlaydi, MA'NOSINI emas.

---

## 5. Discovery'dan keyingi BIRINCHI engineering task

**Bitta vazifa:** aniqlangan konfiguratsiya va nusxa (`.dt` / `.cf`) asosida
`integrations/1c/EXTRACTOR_FIELD_BINDING.md` ni yozish — bundle'ning **15 ta mahsulot maydoni + 4 ta tuzilma
bloki** uchun ANIQ metadata bog'lanishi jadvali.

Nega aynan shu: `.epf` ning chiqish qatlami (JSON, manifest, SHA256) konfiguratsiyaga bog'liq emas va U21
bo'yicha hozir ham yozilaveradi. Konfiguratsiyaga bog'liq YAGONA qism — ma'lumot o'qish so'rovlari. Ularni
yozishdan oldin har maydon uchun metadata nomi TASDIQLANGAN bo'lishi kerak, aks holda 4-bo'limdagi jim
buzilishlar kodga kiradi.

✅ **`products[].plu` maydoni endi BLOKLANMAGAN** (task boshlanishiga to'siq emas): uning FORMATI real
etiketka bilan tasdiqlandi — 5 xonali raqam satri, yetakchi nollar saqlanadi, BinOS 1–5 chegarasi AYNAN mos
(1.6, D26). Shu satrni yozishga endi hech narsa halaqit bermaydi. ⚠️ Lekin uning **MANBASI** hamon ochiq
(D27): 1C da PLU rekviziti bormi, yo'qmi — buni nusxa/kartochka ko'rsatadi. Ya'ni bu satr «metadata nomi +
sanoq» yoki «1C da YO'Q» deb yopiladi; qiymatni tovar nomidan ajratish HAMON TAQIQLANGAN (T5).
⚠️ `has_characteristics` (D21/D23) — `CHARACTERISTICS_UNSUPPORTED` hamon discovery blokeri, DoD 2 o'zgarmaydi.

**Har satrda:**

| Ustun | Mazmun |
|---|---|
| Bundle maydoni | masalan `products[].is_weighted` |
| 1C metadata to'liq nomi | nusxadan o'qilgan aniq nom (taxmin YO'Q) |
| O'qish usuli | rekvizit / registr o'lchovi / hisoblanadigan qiymat |
| Nusxadagi sanoq | nechta tovarda to'ldirilgan (bo'sh bo'lsa — shunday yoziladi) |
| Tekshirish so'rovi | nusxada qayta ishga tushiriladigan so'rov |
| `null` qonuniymi | shartnoma bo'yicha (`bundle.py` ga havola) va operatsion oqibati |

**Bajarildi hisoblanadi (DoD):**

1. 15 maydonning HAR BIRI uchun yo metadata nomi + sanoq bor, yo «1C da YO'Q» deb yozilgan.
2. To'rtta majburiy bool (`is_folder`, `deletion_mark`, `has_characteristics`, `has_series`) uchun qator
   darajasidagi hisoblash qoidasi yozilgan — `null` yo'li yo'q (`bundle.py:202-203`).
3. `warehouses` / `price_types` / `selection` / `manifest` bloklari uchun manba spravochniklar tasdiqlangan.
4. Har satr nusxada qayta ishga tushirilgan so'rov bilan isbotlangan.
5. `(экранда tekshirilsin)` belgisi qolmagan — yoki tasdiqlangan, yoki «YO'Q» deb yopilgan.
6. ⚠️ Ekstraktorning o'qish qatlami uchun qat'iy shart yozilgan: `.epf` da birorta yozuv chaqirig'i
   bo'lmaydi (`Записать()`, `Удалить()`, `Провести()`, `УстановитьМонопольныйРежим()`), faqat so'rov tili
   bilan o'qish. Bu shart kod ko'rigining darvozasi — ko'rikdan o'tmagan `.epf` jonli bazaga umuman
   yaqinlashtirilmaydi (avval nusxa, so'ng `.cf` dan qurilgan bo'sh baza).
7. Ish tugagach nusxa (`.dt` / `.cf` / `.cfe`) 0.4 bo'yicha o'chiriladi va egasiga yozma tasdiq beriladi.
   Hujjatga na skrinshot, na eksport fragmenti, na baza mazmuni ko'chirilmaydi — faqat metadata nomlari
   va sanoqlar.

**Bu task NIMA EMAS:** `.epf` kodi yozilmaydi, bundle chiqarilmaydi, `apply` qilinmaydi, Fayzan
aktivatsiya qilinmaydi, production'ga tegilmaydi. Keyingi task (ekstraktorning o'qish qatlami) faqat shu
hujjat to'lgandan keyin boshlanadi.
