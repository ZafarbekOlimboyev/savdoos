# 1C RUNTIME TAYYORLIGI — BLOKERLAR INVENTARI

Manba: `integrations/1c/extractor/BinOSDiscovery.bsl`
Audit: `apps/server/app/services/discovery_1c/runtime_audit.py`
Testlar: `apps/server/tests/test_discovery_1c_runtime_audit.py`

---

## BU HUJJAT NIMA ISBOTLAYDI va NIMA ISBOTLAMAYDI

**ISBOTLAYDI.** Ekstraktor manbasining MATNI ustida bajarilgan statik tekshiruvlar
natijasini: belgi to'plami, blok muvozanati, ishlatilgan global nomlar ro'yxati,
kompilyatsiya direktivalari, `Попытка` qamrovi, fayl va JSON yozish usuli, uchlik
mantiq va sanoqlarning MATN bo'lib chiqishi, ixtiyoriy metadata oilalarining
qo'riqlanishi. Bu tekshiruvlar KOD bilan bajariladi va CI da qayta ishlanadi, ya'ni
bu jadval qo'lda yozilgan da'vo emas — u koddan kelib chiqadi.

**ISBOTLAMAYDI.** Manba 1C:Enterprise da:

- kompilyatsiya bo'lishini,
- ishga tushishini,
- to'g'ri natija berishini,
- birorta faylni diskka yozishini.

Bu mashinada 1C:Enterprise platformasi **YO'Q**. Manba hech qachon Konfiguratorda
ochilmagan, sintaksis tekshiruvidan o'tmagan va hech qanday bazada ishlatilmagan.
Shu bois bu hujjatda «ishlaydi», «kompilyatsiya qilinadi», «runtime tasdiqlangan»
degan ibora **YO'Q**, va bo'lishi ham mumkin emas.

### Holat lug'ati (uchta, aralashtirilmaydi)

| holat | ma'nosi |
|---|---|
| `KNOWN` | MANBA MATNI shu xulosani MAJBURLAYDI. Matnni o'qib aynan shu natijaga kelish mumkin: tuzatilmasa runtime'da AYNAN shunday bo'ladi. |
| `SOURCE-VALIDATED` | Statik tekshiruv bajarildi va talab QONDIRILDI. Bu «runtime'da ishlaydi» degani EMAS — «matnda buzilmagan» degani. |
| `RUNTIME-UNKNOWN` | Matn bilan hal qilinmaydi. Javob faqat real 1C mashinasida olinadi. |

⚠️ Taxmin bilan `KNOWN` yozilmagan. Statik matn bilan isbotlanmagan hamma narsa
`RUNTIME-UNKNOWN`. Har `KNOWN` va `SOURCE-VALIDATED` qator KAMIDA BITTA topilma
kodiga tayanadi (`runtime_audit.INVENTORY_EVIDENCE`), va o'sha kodning rostdan
chiqarilishini test statik tekshiradi.

⚠️⚠️ **HOLATLAR — SNAPSHOT.** Jadval `BinOSDiscovery.bsl` ning SHU holati ustida
hisoblangan. Manba o'zgarsa holatlar QAYTA HISOBLANISHI SHART:

```
cd apps/server && python -c "from app.services.discovery_1c import runtime_audit as r;   import collections; print(collections.Counter(f.code for f in r.audit_file(r.EXTRACTOR_SOURCE)))"
```

Keyin `runtime_audit.INVENTORY_ITEMS` va bu jadval **birga** tahrirlanadi —
ikkisining mosligini `test_inventar_jadvali_kod_bilan_MOS` qulflaydi. Nuqson
tuzatilganda holatni **pasaytirish** esdan chiqmasin, aks holda hujjat mavjud
bo'lmagan nuqsonni ko'rsatib turadi.

---

## §2 — BLOKERLAR INVENTARI (15 qator)

Qator soni va identifikatorlari `runtime_audit.INVENTORY_ITEMS` ga QULFLANGAN
(`test_inventar_jadvali_kod_bilan_MOS`).

| # | slug | band | holat | nima TEKSHIRILGAN | nima tekshirilMAGAN | real 1C da QANDAY tekshiriladi |
|---|---|---|---|---|---|---|
| 1 | `bsl_syntax` | BSL sintaksisi | `RUNTIME-UNKNOWN` | Uch MAJBURIY matn sharti kod bilan tekshiriladi va HOZIR hammasi qondirilgan: blok juftlari muvozanati (`BLOCKS_BALANCED`), identifikator belgi to'plami (`CHARSET_CLEAN` — avvalgi `Қ` U+049A tuzatilgan) va satr literallarining yopilishi (`literal_defects`: `LITERAL_BACKSLASH_QUOTE` / `LITERAL_UNTERMINATED` topilmadi). | Sintaksisning O'ZI. Audit BSL parseri EMAS: tushib qolgan `Тогда`, noto'g'ri joydagi `Иначе`, yopilmagan qavs, xato argument soni yoki turi — hech biri tutilmaydi. Uch shartning qondirilishi ZARURIY, YETARLI EMAS, shu bois qator `SOURCE-VALIDATED` ham emas: savol («sintaksis to'g'rimi?») OCHIQ qoladi. | Konfigurator → tashqi qayta ishlashni ochish → **Konfiguratsiya · Modullarni sintaktik tekshirish** (`Ctrl+F7`). Chiqqan xatolar ro'yxati to'liq ko'chirib olinadi. |
| 2 | `processor_module_compile` | Tashqi qayta ishlash moduli kompilyatsiyasi | `RUNTIME-UNKNOWN` | Manba o'zining modul turini (`ObjectModule`) izohda e'lon qiladi va `Экспорт` kirish nuqtalari bor (`ВыполнитьРазведку`, `ВыполнитьЗонд`). | Modul kompilyatsiya bo'lishi. `.epf` konteyneri UMUMAN YO'Q: repoda faqat `.bsl` matni turadi, ya'ni tashqi qayta ishlash obyekti hali yig'ilmagan. | Konfiguratorda `Внешняя обработка` yaratish → ObjectModule ga matnni qo'yish → saqlash (`.epf`). Kompilyatsiya saqlashda bajariladi. |
| 3 | `metadata_api_compatibility` | Metadata API mosligi | `RUNTIME-UNKNOWN` | Ishlatilgan global nomlar SANAB chiqilgan (`api_surface`): tanish ro'yxatda 40 nom, tanilmagan 4 ta: `Метаданные.СвойстваОбъектов.*` uchligi (platforma versiyalari orasida eng ko'p o'zgargan shox) va `Метаданные.ОсновнойРежимЗапуска`. | Nomlarning platformada BORLIGI ham, TO'G'RI ishlatilgani ham. «Tanish» ro'yxati QO'LDA yozilgan bilim (`KNOWN_GLOBAL_API`), platformadan olinmagan. `ОбъектМД[ИмяКоллекции]` shaklidagi DINAMIK a'zo murojaatlari umuman tekshirilmaydi. | Sintaksis yordamchisi bilan har nom tekshiriladi; keyin `ВыполнитьРазведку` haqiqiy bazada ishlatilib `errors` ro'yxati o'qiladi — noma'lum a'zo aynan u yerda ko'rinadi. |
| 4 | `platform_version_compatibility` | Platforma versiyasi mosligi | `RUNTIME-UNKNOWN` | Manbada eng yosh talab qiluvchi chaqiruvlar BELGILANGAN: `СтрРазделить` (izohda 8.3.6 deb yozilgan), `ЗаписьJSON`/`ЗаписатьJSON`, `СмещениеСтандартногоВремени`. | Mijoz mashinasidagi platforma versiyasi. U hali O'LCHANMAGAN. `СмещениеСтандартногоВремени` yo'q bo'lsa `Попытка` uni tutadi, `СтрРазделить` yo'q bo'lsa zond BAJARILMAYDI (fail-closed). | `Новый СистемнаяИнформация.ВерсияПриложения` (audit uni `platform_version` ga yozadi) → talab qilingan minimal versiya bilan solishtirish. |
| 5 | `managed_or_ordinary` | Boshqariladigan yoki oddiy ilova | `RUNTIME-UNKNOWN` | Manbada birorta kompilyatsiya direktivasi YO'Q (`CONTEXT_NO_DIRECTIVE`) — tashqi qayta ishlashning ObjectModule i uchun bu normal. | Modul QAYSI tomonda bajarilishi. Direktiva yo'qligi «server» degani EMAS: bu ilova rejimiga va bazaning fayl/klient-server ekaniga bog'liq. Fayl aynan shu tomonning diskiga yoziladi (6-qatorga bog'liq). | Ikki rejimda ham ishga tushirish; `КаталогВыгрузки` ni operator mashinasining papkasi qilib berish va fayl QAYERDA paydo bo'lganini ko'rish. |
| 6 | `file_write_permissions` | Fayl yozish huquqlari | `RUNTIME-UNKNOWN` | Fayl yozish YAGONA kanal orqali (`ОткрытьФайл` + `ЗаписьJSON`); boshqa yozuvchi obyektlar `epf_audit.py` bilan TAQIQLANGAN; `СоздатьКаталог` ham taqiqlangan, ya'ni papka MAVJUD bo'lishi shart. | OS huquqlari. Xavfsiz rejimda (`безопасный режим`) fayl yozish umuman taqiqlangan; server tomonida `usr1cv8` xizmat hisobining huquqlari boshqa. Bularning birortasi matndan ko'rinmaydi. | Qayta ishlashni ishga tushirish va `run_status.json` dagi yozuv bo'limini o'qish; huquq yo'q bo'lsa `ОписаниеОшибки()` matni aynan shuni aytadi. |
| 7 | `encoding` | Kodlash | `SOURCE-VALIDATED` | Ikki `ОткрытьФайл` chaqiruvining ikkisida ham kodlash ANIQ `"UTF-8"` (`JSON_ENCODING_UTF8` ×2) va BOM argumenti `Ложь` (`JSON_BOM_DISABLED` ×2) — standartga tashlab qo'yilmagan. | Faylga TUSHGAN baytlar. Platforma so'ralgan kodlashni bajarishi, BOM rostdan yozilmasligi va rus/o'zbek matni buzilmasligi — hammasi runtime'da ko'rinadi. | Chiqqan `export.json` ni `python -c "open(p,'rb').read(3)"` bilan tekshirish (BOM yo'qligi) va `json.load(open(p, encoding='utf-8'))` bilan o'qish. |
| 8 | `json_serialization` | JSON serializatsiyasi | `KNOWN` | `Новый ЗаписьJSON` + `ЗаписатьJSON(` juftligi ishlatilgan. **NUQSON (matn majburlaydi):** `Закрыть()` FAQAT muvaffaqiyat shoxida — `Исключение` shoxida yo'q (`JSON_CLOSE_NOT_GUARANTEED` ×2), ya'ni `ЗаписатьJSON` yiqilsa oqim OCHIQ qoladi va diskda YARIM yozilgan JSON qoladi. Yozuvchi protseduralar muvaffaqiyatni chaqiruvchiga `Возврат Истина` bilan bildiradi — `WRITE_SUCCESS_UNRECORDED` tutilmaydi. | Yarim fayl aynan qanday ko'rinishi, platforma oqimni o'zi yopishi yoki yopmasligi. `Структура`/`Массив` ning JSON'ga aynan qanday tushishi (kalit tartibi, chuqurlik) ham sinalmagan. | `ЗаписатьJSON` ni ataylab yiqitib (masalan serializatsiya qilinmaydigan qiymat berib) diskdagi faylni ko'rish; keyin `manifest.json` dagi sha256 bilan solishtirish. |
| 9 | `large_configuration_performance` | Katta konfiguratsiyada unumdorlik | `RUNTIME-UNKNOWN` | Eng qimmat joylar MATNDA ko'rinadi: `СобратьСчетчики` har hisoblanadigan obyekt uchun BITTA `КОЛИЧЕСТВО(*)` so'rovi yuboradi; `ЗондСсылающиеся` butun konfiguratsiyani kezib chiqadi va har obyekt uchun `АдресаПолейОбъекта` ni qayta hisoblaydi (kvadratik shakl). | Vaqt va xotira. Fayzan bazasida 7137 mahsulot / 12603 barkod bor, lekin OBYEKT soni (kolleksiyalar kattaligi) o'lchanmagan; `КОЛИЧЕСТВО(*)` ning katta registrda qancha turishi ham noma'lum. Timeout, bloklash va xotira chegarasi — hammasi runtime'da. | Ajratilgan nusxada `ВыполнитьРазведку` ni o'lchash: `started_at`/`finished_at` farqi, keyin `counts` bo'limidagi eng sekin obyektlar. Zondni `row_count` dan boshlab bittalab sinash. |
| 10 | `optional_metadata_families_absence` | Ixtiyoriy metadata oilalarining yo'qligi | `KNOWN` | `ПланыСчетов`, `ПланыВидовХарактеристик`, `ОбщиеРеквизиты` — uchtasi ham qo'riqlangan (`OPTIONAL_FAMILY_GUARDED`): yo'q bo'lsa bo'lim jurnalida sababi bilan `skipped` qoladi. **NUQSON (matn majburlaydi):** `ПланыОбмена` manbada UMUMAN eslanmagan (`OPTIONAL_FAMILY_UNMENTIONED`) — u bor bo'lsa ham, yo'q bo'lsa ham hujjatda hech qanday iz qolmaydi. Bu muhim: almashinuv rejasi mijozning BOSHQA integratsiyalari borligini ko'rsatadigan yagona metadata belgisi. | Mijoz konfiguratsiyasida bu oilalar bor yoki yo'qligi. Jurnal real 1C da rostdan to'ldirilishi. | Chiqqan `metadata.json` ning `sections` ro'yxatini o'qish: har oila uchun `ok`/`skipped`/`failed` bo'lishi shart. `ПланыОбмена` uchun qator BO'LMAYDI — bu shu nuqsonning jonli isboti. |
| 11 | `permissions_read_access_failures` | Huquq va o'qish xatolari | `RUNTIME-UNKNOWN` | Metadata o'qishning KO'P joyi `Попытка` bilan o'ralgan va sabab `errors` ga yoziladi; kolleksiya yo'qligi jimgina tashlanmaydi (`КоллекцияМетаданных` sababni qaytaradi). | Huquq yetmaganda 1C AYNAN nima qilishi: istisno beradimi, bo'sh kolleksiya beradimi, yoki obyektni kolleksiyadan yashiradimi. Uchinchi holat eng xavfli — u xatosiz, JIMGINA to'liqsiz hujjat beradi va statik matn bunday yo'qotishni KO'RA OLMAYDI. | To'liq huquqli va cheklangan foydalanuvchi bilan ikki marta ishlatib, ikki `metadata.json` ning `objects` sonini solishtirish. Farq bo'lsa — yashirilgan obyektlar bor. |
| 12 | `probe_execution_contract` | Zond bajarilish shartnomasi | `KNOWN` | `ВыполнитьЗонд` noma'lum tur uchun FAIL-CLOSED: `ВызватьИсключение` beradi, «o'xshash narsa qilaman» zaxira yo'li YO'Q. Nishon shakli ikki tomonda BITTA joyda yozilgan (`probe.FIELD_TARGET_PROBE_TYPES`): maydon yo'li faqat `field_type_details` uchun. **NUQSON (matn majburlaydi):** `ВыполнитьЗонд` tanasida birorta `Попытка` YO'Q (`ENTRY_WITHOUT_TRY`) — ichkaridan chiqqan istisno chaqiruvchiga ketadi, ya'ni na natija, na `errors.json` qoladi. | Zond natijasining SHAKLI. BinOS tomonida zond NATIJASINI tekshiradigan validator YO'Q (`probe.py` faqat SO'ROVni tekshiradi), shu bois natija shakliga tayanib kod yozilmaydi. Katalogdagi 11 zondning birortasi ham bajarilib ko'rilmagan. | `APPROVED_PROBES` rejimida, operator bergan ANIQ allowlist bilan, bittalab: har zond uchun `probes/NN_<tur>.json` chiqishini va `errors` bo'sh yoki to'ldirilganini ko'rish. |
| 13 | `timestamps` | Vaqt belgilari | `RUNTIME-UNKNOWN` | Matndan QO'LDA o'qilgan, lekin KOD BILAN tekshirilMAGAN (shu bois `KNOWN` emas): `started_at`, `finished_at`, `collected_at` uchun `ТекущаяДата()` UCH MARTA ALOHIDA chaqiriladi, ya'ni ular bir-biridan farq qilishi MUMKIN va `collected_at` `finished_at` dan keyin bo'lishi mumkin. Zona siljishi `СмещениеСтандартногоВремени(ЧасовойПоясСеанса())` bilan olinadi va manbaning O'ZIDA «yozgi vaqtni hisobga olmaydi, SINALMAGAN» deb yozilgan. `ВСтрокуISO` siljishni `+HH:MM` bo'lib yozadi. ⚠️ Bu kuzatuvlar uchun tekshiruv YOZILMAGAN, shu bois ular holatni `KNOWN` ga ko'tarmaydi. | Chiqqan matnning BinOS tomonidagi `parse_ts` bilan o'qilishi. `Формат(Момент, "ДФ=yyyy-MM-ddTHH:mm:ss")` aynan shu matnni berishi ham sinalmagan (mahalliylashtirilgan format satri platforma tiliga bog'liq bo'lishi mumkin). `ТекущаяДата()` server soatini beradi — u do'kon soati bilan mos kelishi tekshirilmagan. | Chiqqan `export.json` dagi uch vaqtni o'qib `parse_ts` ga berish; keyin mashinaning soati va zonasi bilan solishtirish. |
| 14 | `output_directory_behavior` | Chiqish papkasining xatti-harakati | `RUNTIME-UNKNOWN` | Matn fakti (kod bilan tekshirilgan, lekin NUQSON ekani runtime'da hal bo'ladi): yo'l MATN QO'SHISH bilan quriladi (`PATH_BUILT_BY_CONCAT` ×2) va ajratuvchi `/` (`PATH_FORWARD_SLASH` ×2); `ОбъединитьПути` ishlatilmagan (`PATH_NO_JOIN_HELPER`); `СоздатьКаталог` `epf_audit.py` bilan TAQIQLANGAN, ya'ni papka MAVJUD bo'lishi SHART; papka mavjudligi yozishdan OLDIN tekshirilmaydi. Operator papkani oxirida ajratuvchi bilan bersa yo'lda IKKI ajratuvchi qoladi. | `/` ning Windows'da ishlashi, ikki ajratuvchili yo'lning taqdiri, papka yo'q bo'lganda `ОткрытьФайл` ning xato matni. Bo'sh bo'lmagan papkada eski fayl ustiga yozilishi ham sinalmagan. | Uch xil papka bilan sinash: (a) mavjud bo'sh, (b) oxirida `\` bilan, (c) mavjud emas. Har holat uchun `run_status.json` dagi yozuv bo'limi va diskdagi natija solishtiriladi. |
| 15 | `exception_handling` | Istisnolarni ishlash | `KNOWN` | **Matn majburlagan narsalar:** ikki `Экспорт` kirish nuqtasining IKKISIDA ham birorta `Попытка` YO'Q (`ENTRY_WITHOUT_TRY` ×2) — ichkaridan chiqqan istisno chaqiruvchiga ketadi va operator BO'SH papka ko'radi; metadata kolleksiyasi 10 joyda `Попытка` TASHQARISIDA kezilyapti (`LOOP_WITHOUT_TRY` ×10), holbuki kezishning O'ZI istisno berishi mumkin. | Istisnolar rostdan yuz berishi, `ОписаниеОшибки()` ning mazmuni, va `Попытка` ichidagi tiklanish to'g'ri ishlashi. Audit PARAMETR bo'lib kelgan kolleksiyani KO'RMAYDI (`ДобавитьКоллекцию(…, Коллекция, …)`) — bu ochiq chegara, yolg'on kafolat emas. | Huquqi cheklangan foydalanuvchi bilan ishlatish va `run_status.json` + `errors.json` ning to'ldirilishini ko'rish. Manba bu ikki faylni YOZADI (`ВыполнитьРазведку` ularni `ЗаписатьJSONФайл` bilan yozadi va `ДобавитьОшибку` sabablarni `errors.json` ga yig'adi) — sinalmagani ularning diskka ROSTDAN tushishi va istisno tutilganda mazmuni to'g'ri to'lishi. |

---

## RUNTIME PAKETI SHARTNOMASI

Real 1C mashinasidan chiqadigan papkaning majburiy tarkibi
(`runtime_audit.RUNTIME_PACKAGE_REQUIRED`):

| fayl | versiya | majburiy | mazmuni |
|---|---|---|---|
| `export.json` | `binos-1c-export-v1` | HA | O'ZGARMAGAN Phase 2 shakli |
| `metadata.json` | `binos-1c-metadata-v1` | HA | O'ZGARMAGAN Phase 3 shakli |
| `run_status.json` | `binos-1c-run-v1` | HA | rejim, vaqtlar, bo'limlar, umumiy holat |
| `errors.json` | `binos-1c-errors-v1` | HA (bo'sh bo'lishi mumkin) | strukturali xatolar |
| `run_summary.md` | — | HA | operator uchun: nima bo'ldi |
| `manifest.json` | `binos-1c-manifest-v1` | HA | har fayl uchun SHA-256 |
| `probes/NN_<tur>.json` | `binos-1c-probe-v1` | YO'Q | faqat `APPROVED_PROBES` rejimida |

⚠️ **NEGA `run_status.json` va `run_summary.md`, `status.json`/`summary.md` EMAS.**
Discovery to'plamining (`binos-1c-discovery-v1`) besh a'zosidan ikkitasi AYNAN
`status.json` va `summary.md` deb ataladi
(`app/services/discovery_1c/__init__.REQUIRED_MEMBERS`) va ularni **ADAPTER** quradi
(`export_adapter.py`), 1C emas. Bir xil nom ikki xil sxema — operator uchun ham,
kod uchun ham tuzoq: papkani to'plam deb o'qishga urinish jimgina BOSHQA hujjatni
validatorga berardi. Shu bois runtime paketi boshqa nom oladi.

⚠️ **MANIFEST — PROVENANS DA'VOSI EMAS.** U faqat YOZILGAN BAYTLARNING sha256'si.
Ruxsat etilgan maydonlar: `name`, `bytes`, `sha256` — boshqa hech narsa.
`source_copy`, `snapshot_at`, `plan_sha256` kabi MANBA provenansi maydonlari
**QO'SHILMAYDI**: ular metadata razvedkasidan kelib chiqmaydi, ya'ni yozilsa
YOLG'ON kafolat bo'lardi (Phase 2 qoidasi ularni ataylab taqiqlagan).

⚠️ **HOZIRGI HOLAT:** manba OLTI majburiy artefaktning HAMMASINI yozadi va yozish
TARTIBI `ВыполнитьРазведку` da ochiq yozilgan: `export.json` → `metadata.json` →
`probes/` → `run_summary.md` → `errors.json` → `run_status.json` → `manifest.json`.
Birinchi beshtasi `ЗаписатьJSONФайл` / `ЗаписатьСводку` orqali chiqadi,
`manifest.json` esa ENG OXIRIDA — u o'zidan oldingi hamma faylni nomi, bayti va
sha256'si bilan sanaydi va O'ZINI ro'yxatga qo'shmaydi. `probes/NN_<tur>.json` faqat
`APPROVED_PROBES` rejimida va faqat allowlistdagi zondlar uchun yoziladi.
Ikki tomonning shakl TENGLIGI — kalit nomlari, lug'atlar, majburiy artefakt nomlari
va `overall` ning ta'rifi — `apps/server/tests/test_discovery_1c_conformance.py`
darvozasi bilan majburlanadi: manbadagi `Вставить("<kalit>", …)` literallari
`runtime_bundle.py` ning oq ro'yxatlari bilan solishtiriladi.

⚠️ **BU NIMANI ISBOTLAMAYDI:** yozish KODI borligi fayllarning diskka ROSTDAN
tushishini isbotlamaydi. Yozish yo'li birorta 1C bazasida bajarilmagan
(`file_write_permissions`, `json_serialization`, `output_directory_behavior`
qatorlari `RUNTIME-UNKNOWN`), `run_summary.md` esa `ЗаписьJSON` ning xom matn
yozadigan metodi bilan chiqadi va bu yo'l ham sinalmagan. Shu bois shartnoma
hamon TALAB: haqiqiy paket kelgach u validatordan o'tishi kerak.

---

## REJIMLAR (§5)

| rejim | ma'nosi |
|---|---|
| `METADATA_ONLY` | **DEFAULT.** Hech qanday aktiv zond YO'Q: faqat metadata o'qish va `КОЛИЧЕСТВО(*)`. |
| `APPROVED_PROBES` | Faqat operator bergan ANIQ allowlist. Har zond nomi va SABABI ko'rsatiladi. O'zboshimcha kod YO'Q. |

⚠️ Default **HAR DOIM** `METADATA_ONLY`: argument berilmasa ham, noma'lum rejim
kelsa ham (`runtime_audit.normalize_mode`). Fail-safe sababi oddiy — «balki zond ham
kerak edi» degan taxmin mijoz bazasida amal bajarishga olib kelardi. Tanlov va
sababi `run_status.json` da QAYD ETILADI, ya'ni noma'lum rejim JIMGINA metadata-only
ga aylanmaydi.

⚠️ `normalize_mode` PYTHON tomonidagi qoidani majburlaydi. **BSL tomonida rejim
tushunchasi BOR va u AYNI fail-safe qoidasiga yozilgan:** rejim nomlari funksiya
bo'lib beriladi (`РежимТолькоМетаданные` / `РежимРазрешенныеЗонды`), `ТекущийРежим`
o'rnatilmagan rejimni `METADATA_ONLY` ga tushiradi, `УстановитьРежимРазведки`
argument berilmagan ham, noma'lum rejim kelgan ham holatni `METADATA_ONLY` ga
tushiradi va sababini `ЗаметкаРежима` da (`run_status.json`.`mode_note`) qoldiradi.
Noma'lum rejim JIMGINA qabul qilinmaydi: `РежимОтклонен` bayrog'i qo'yiladi, `mode`
bo'limi `failed` bo'ladi va `errors.json` ga `REJECTED` kodli xato tushadi, ya'ni
yurish `SUCCESS` BO'LMAYDI. Allowlist `НормализоватьЗаявку` bilan
`(probe_type, target_object, reason)` uchligiga keltiriladi — SABABI bo'sh element
RAD etiladi — va zond darvozasi `ЗондРазрешен` da fail-closed: rejim
`APPROVED_PROBES` bo'lmasa yoki juftlik allowlistda bo'lmasa zond BAJARILMAYDI.
Rejim nomlari, default va `overall` ta'rifining ikki tomonda tengligi
`test_discovery_1c_conformance.py` bilan qulflangan.

⚠️ `RUNTIME-UNKNOWN` bo'lib qolgani — bu mantiqning 1C da BAJARILISHI: kod o'qildi,
lekin birorta bazada ishlatilmadi.

---

## KEYINGI QADAM — ODAM BAJARADIGAN ISH

Bu inventardagi `RUNTIME-UNKNOWN` qatorlarni statik audit YOPA OLMAYDI. Ular faqat
1C:Enterprise o'rnatilgan mashinada, **FAQAT AJRATILGAN NUSXADA** yopiladi:

1. Nusxani ajratilgan mashinaga tiklash (jonli baza EMAS).
2. Konfiguratorda modulni sintaktik tekshirish (`Ctrl+F7`) — 1 va 2-qatorlar.
3. `METADATA_ONLY` rejimida ishlatish — 3–9, 11, 13, 14-qatorlar.
4. Chiqqan fayllarni BinOS tomonidagi validatorga berish — 7, 8, 10-qatorlar.
5. Faqat shundan keyin, operator ANIQ allowlist bilan `APPROVED_PROBES` —
   12-qator.

Har bosqichda natija shu hujjatga qaytariladi va holat `RUNTIME-UNKNOWN` dan
o'zgartiriladi. Sinalmaguncha holat o'zgartirilmaydi.
