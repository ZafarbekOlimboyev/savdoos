# PLATFORMA MOSLIK JADVALI (§11)

Manba: `integrations/1c/extractor/BinOSDiscovery.bsl`
Statik audit: `apps/server/app/services/discovery_1c/runtime_audit.py`,
`apps/server/app/services/discovery_1c/epf_audit.py`
Paket validatori: `apps/server/app/services/discovery_1c/runtime_bundle.py`
Darvoza testi: `apps/server/tests/test_discovery_1c_runbook.py`

---

## BU HUJJAT NIMA BERADI va NIMA BERMAYDI

**BERADI.** Ikki ro'yxat: (1) 1C muhitining qaysi variantlari haqida **kod nimani
majburlaydi**, (2) real Fayzan kompyuterida **qaysi maydonlar yig'ilishi kerak** va ular
yig'uvchining chiqishida **hozir bor yoki yo'q**.

**BERMAYDI.** Birorta variant uchun moslik da'vosini. Bu mashinada 1C:Enterprise **YO'Q**:
modul Konfiguratorda ochilmagan, sintaksis tekshiruvidan o'tmagan va hech qanday bazada
bajarilmagan. Shu bois moslik ustuni deyarli butunlay `UNKNOWN`, va bu **kamchilik emas** —
bu holatning to'g'ri yozilishi.

### Holat lug'ati (ikkita, aralashtirilmaydi)

| holat | ma'nosi |
|---|---|
| `KNOWN` | **KOD MAJBURLAYDI.** Qatorning oxirgi ustunida aynan shu narsani majburlaydigan joy ko'rsatilgan: fayl, funksiya yoki qoida nomi. Kod o'zgarmaguncha natija AYNAN shunday. |
| `UNKNOWN` | Kod bilan hal qilinmaydi. Javob faqat real 1C mashinasida olinadi. Taxmin YOZILMAYDI. |

⚠️ `KNOWN` qator har doim **kodning O'Z qoidasi** haqida, platformaning xatti-harakati
haqida EMAS. Masalan «yig'uvchi papka YARATMAYDI» — `KNOWN` (statik audit taqiqlagan);
«papka yo'q bo'lsa 1C qanday xato beradi» — `UNKNOWN` (platformaning ishi).

---

## 1-JADVAL — MUHIT VARIANTLARI

| # | o'lcham | variant | holat | asos: kod MAJBURLAGAN joy · yoki NEGA `UNKNOWN` |
|---|---|---|---|---|
| 1 | platforma versiyasi | 8.2.x va undan past | `UNKNOWN` | Repoda versiya o'lchovi YO'Q. Inventarning 4-qatori (`platform_version_compatibility`) `RUNTIME-UNKNOWN` va uning dalil ro'yxati (`runtime_audit.INVENTORY_EVIDENCE`) ATAYLAB bo'sh. Manbadagi izohlar dalil emas. |
| 2 | platforma versiyasi | 8.3.0 – 8.3.5 | `UNKNOWN` | Ayni sabab. Manbada `СтрРазделить` (izohda 8.3.6 deb yozilgan), `ЗаписьJSON`, `СмещениеСтандартногоВремени`, `ХешированиеДанных` chaqiriladi — ularning shu relizlarda BORLIGI o'lchanmagan. |
| 3 | platforma versiyasi | 8.3.6 – 8.3.9 | `UNKNOWN` | 1-qator bilan ayni sabab: mijoz mashinasidagi versiya hali O'LCHANMAGAN va repoda uni majburlaydigan tekshiruv YO'Q. Bu oraliqda `СтрРазделить` bor deb TAXMIN qilinadi, isbotlanmaydi. |
| 4 | platforma versiyasi | 8.3.10 va yangi | `UNKNOWN` | 1-qator bilan ayni sabab. Yangi reliz «xavfsizroq» EMAS: `ЗаписьJSON` ning kalit tartibi va `Формат` ning lokalga bog'liqligi yangi relizda ham o'lchanmagan. |
| 5 | ilova rejimi | boshqariladigan (managed) | `UNKNOWN` | Manbada birorta kompilyatsiya direktivasi YO'Q (`runtime_audit.check_client_server_context` → `CONTEXT_NO_DIRECTIVE`). Direktiva yo'qligi tomonni ANIQLAMAYDI: fayl qaysi tomonning diskiga tushishi ham shundan kelib chiqmaydi. |
| 6 | ilova rejimi | oddiy (ordinary) | `UNKNOWN` | 5-qator bilan ayni sabab: direktiva yo'qligi ikki rejimning birortasini ham TASDIQLAMAYDI. Yig'uvchi rejimni faqat QAYD etadi (2-jadval, `application_mode`). |
| 7 | klient turi | qalin klient (`1CV8`) | `UNKNOWN` | Modul faqat klient nomini O'QIYDI va yozadi; qaysi klientda bajarilishi mumkinligi sinalmagan. `README.md` dagi «qalin klient» — TALAB, dalil emas. |
| 8 | klient turi | yupqa klient (`1CV8C`) | `UNKNOWN` | 7-qator bilan ayni sabab, ustiga: yupqa klientda `ОткрытьФайл` qaysi mashinaning diskiga yozishi rejimga bog'liq va u tekshirilmagan (inventarning 5 va 6-qatorlari). |
| 9 | klient turi | veb-klient | `UNKNOWN` | 7-qator bilan ayni sabab, ustiga: veb-klientda brauzer diskiga yozish umuman boshqa mexanizm bilan bo'ladi va manbada u YO'Q — faqat `ОткрытьФайл` bor. |
| 10 | klient turi | boshqa (COM / WS ulanish, fon topshirig'i) | `UNKNOWN` | 7-qator bilan ayni sabab. Yig'uvchi bu holatni `client_kind` = `other` deb BELGILAYDI (`unknown` EMAS), lekin bu talqin, bajarilish dalili emas. |
| 11 | infobase | fayl bazasi | `UNKNOWN` | Bazaning turi ANIQLANADI (2-jadval, `infobase_mode`), lekin yurishning natijasi sinalmagan. |
| 12 | infobase | klient-server bazasi | `UNKNOWN` | 11-qator bilan ayni sabab, ustiga: server tomonida `usr1cv8` xizmat hisobining fayl yozish huquqlari boshqa va u matndan KO'RINMAYDI (inventarning 6-qatori). |
| 13 | DB turi | fayl bazasi (`1Cv8.1CD`) | `UNKNOWN` | 11-qator bilan ayni sabab. Baza turi ANIQLANADI (`infobase_mode` = `file`), lekin `КОЛИЧЕСТВО(*)` so'rovlarining fayl bazasidagi vaqti va bloklashi o'lchanmagan. |
| 14 | DB turi | PostgreSQL | `UNKNOWN` | Yurish sinalmagan. SUBD nomining O'ZI esa umuman yig'ilmaydi — 24-qatorga qarang. |
| 15 | DB turi | MS SQL Server | `UNKNOWN` | 14-qator bilan ayni sabab: yurish sinalmagan va SUBD nomi umuman yig'ilmaydi (24-qator). Hisobot uni ko'rsatmaydi — bu qobiliyat chegarasi. |
| 16 | DB turi | Oracle / IBM Db2 | `UNKNOWN` | 14-qator bilan ayni sabab. Bu SUBD'lar Fayzanda kutilmaydi, lekin ular «qo'llab-quvvatlanmaydi» degan da'vo ham ISBOTLANMAGAN — shu bois `UNKNOWN`. |
| 17 | lokal | `ru_RU` | `UNKNOWN` | Lokal O'QILADI (2-jadval, `locale`), lekin lokalning natijaga ta'siri sinalmagan: sana `Формат(..., "ДФ=yyyy-MM-ddTHH:mm:ss")` bilan yoziladi va format satri platforma tiliga bog'liq bo'lishi mumkin (inventarning 13-qatori). |
| 18 | lokal | `uz` (lotin yoki kirill) | `UNKNOWN` | 17-qator bilan ayni sabab, ustiga: lotin va kirill yozuvi bir xil lokal kodida kelishi mumkin, ya'ni `locale` qiymati yozuvni AJRATMAYDI. |
| 19 | lokal | `ky_KG` | `UNKNOWN` | 17-qator bilan ayni sabab. Bu lokal Fayzanda kutilmaydi, lekin sanoq va sana formatiga ta'siri o'lchanmagani uchun holat baribir `UNKNOWN`. |
| 20 | muhit sharti | chiqish papkasi MAVJUD EMAS | `KNOWN` | **Yig'uvchi papkani YARATMAYDI:** `epf_audit.py` ning `CREATE_DIRECTORY` qoidasi `СоздатьКаталог` chaqiruvini TAQIQLAYDI va buni `tests/test_discovery_1c_epf_source.py` qulflaydi. Papka operator tomonidan oldin yaratiladi. (1C ning xato matni — `UNKNOWN`.) |
| 21 | muhit sharti | chiqish papkasi BO'SH EMAS | `KNOWN` | **Validator paketni RAD etadi:** `runtime_bundle.validate_runtime_members` shartnomada ta'riflanmagan har qanday faylni «shartnomada yo'q fayl» deb nuqson qiladi (ruxsat etilgani faqat `runtime_bundle.REQUIRED_FILES` va `runtime_bundle.PROBE_NAME_RE` ga mos nomlar). |
| 22 | muhit sharti | rejim argumenti berilmagan yoki noma'lum | `KNOWN` | **Natija `METADATA_ONLY`** (fail-safe) va sabab `mode_note` da qoladi: `runtime_bundle.resolve_mode` va `runtime_audit.normalize_mode` ikkisi ham `runtime_bundle.DEFAULT_MODE` ni qaytaradi. Aktiv zond bajarilmaydi. |
| 23 | muhit sharti | `APPROVED_PROBES`, `probes/` papkasi yo'q | `KNOWN` | **Yig'uvchi ostki papkani ham YARATMAYDI** (20-qator bilan ayni qoida, `epf_audit.py` `CREATE_DIRECTORY`). Zond fayli yozilmasa `runtime_bundle` ning `rejim_darvozasi` tekshiruvi qayd va fayllar mos kelmasligini nuqson qiladi. |
| 24 | muhit sharti | server bazasi — SUBD nomi (PostgreSQL / MS SQL / Oracle / Db2) | `KNOWN` | **Aniqlanmaydi va TAXMIN YOZILMAYDI:** BSL ning `СобратьПлатформуЗапуска` funksiyasida `db_type` faqat `FILE=` shoxida to'ldiriladi; server shoxida `unknown` bo'lib QOLADI va sabab `ДобавитьОшибку(... "unreadable")` bilan `errors.json` ga tushadi. 1C ning o'z tili SUBD turini bermaydi. |

**Taqsimot:** 24 qator — `UNKNOWN` **19**, `KNOWN` **5** (20, 21, 22, 23, 24).

⚠️ `KNOWN` qatorlarning birortasi ham «bu variant qo'llab-quvvatlanadi» degani EMAS. Ular
faqat kodning O'Z qoidasini qulflaydi.

---

## 2-JADVAL — REAL FAYZAN KOMPYUTERIDA YIG'ILADIGAN MAYDONLAR

«Yig'uvchi chiqishida» ustuni kodni **O'QIB** aniqlangan: har qator uchun maydonning JSON
kaliti `BinOSDiscovery.bsl` manbasida qidirilgan. `BOR` = kalit manbada YOZILADI;
`YO'Q` = kalit manbada UMUMAN yo'q. Buni darvoza testi grep bilan qayta tekshiradi.

| # | maydon (JSON kaliti) | §11 nomi | yig'uvchi chiqishida | artefakt · kalit yo'li | 1C manbasi / izoh |
|---|---|---|---|---|---|
| 1 | `platform_version` | platforma versiyasi | `BOR` | `export.json` → `platform.platform_version`; `run_status.json` → `platform.platform_version` | `Новый СистемнаяИнформация` → `ВерсияПриложения`. Shakl `export_adapter.PLATFORM_KEYS` bilan qulflangan. |
| 2 | `configuration_name` | konfiguratsiya nomi | `BOR` | `export.json` → `platform.configuration_name` | `Метаданные.Имя` |
| 3 | `configuration_version` | konfiguratsiya versiyasi | `BOR` | `export.json` → `platform.configuration_version` | `Метаданные.Версия` |
| 4 | `client_kind` | klient turi (talqin) | `BOR` | `run_status.json` → `platform.client_kind` | `ИмяКлиентскогоПриложения()` natijasidan: `1CV8` → `thick`, `1CV8C` → `thin`, `WEB` → `web`, aks holda `other`. |
| 5 | `client_application_name` | klient turi (XOM qiymat) | `BOR` | `run_status.json` → `platform.client_application_name` | Ayni chaqiruvning talqinsiz natijasi. Talqin xato bo'lsa xom qiymat bo'yicha tuzatiladi. |
| 6 | `locale` | lokal | `BOR` | `run_status.json` → `platform.locale` | `КодЛокализацииИнформационнойБазы()`. Ikkinchi «taxminiy» manba ATAYLAB yo'q. |
| 7 | `db_type` | DB turi | `BOR (QISMAN)` | `run_status.json` → `platform.db_type` | `СтрокаСоединенияИнформационнойБазы()` da `FILE=` bo'lsa `file`; **server bazasida `unknown` bo'lib qoladi** (1-jadval, 24-qator). Ulanish satrining O'ZI chiqishga tushmaydi. |
| 8 | `application_mode` | managed / ordinary | `BOR` | `run_status.json` → `platform.application_mode` | `Метаданные.ОсновнойРежимЗапуска` **enum QIYMATI** bilan solishtiriladi (`Строка(...)` lokalizatsiyalangan nom berardi). |
| 9 | `infobase_mode` | fayl / server bazasi | `BOR` | `export.json` → `platform.infobase_mode` | Ayni ulanish satri. Ruxsat etilgan qiymatlar: `export_adapter.INFOBASE_MODES_EXPORT`. |
| 10 | `configuration_modified` | konfiguratsiya o'zgartirilganmi | `BOR` | `export.json` → `platform.configuration_modified` | `КонфигурацияИзменена()` → uchlik MATN: `"true"` / `"false"` / `"unknown"`. |
| 11 | `os_version` | OS versiyasi | `BOR` | `run_status.json` → `platform.os_version` | `Новый СистемнаяИнформация` → `ВерсияОС`. |
| 12 | `infobase_id` | baza identifikatori | `BOR (BO'SH)` | `export.json` → `platform.infobase_id` | ⚠️ Kalit `binos-1c-export-v1` shaklida BOR, lekin manbada faqat `Неопределено` deb qo'yiladi va **hech qachon to'ldirilmaydi**: e'lon qilingan maydon, bajarilmagan qobiliyat. |
| 13 | `dbms_kind` | SUBD nomi (PostgreSQL / MS SQL / Oracle / Db2) | `YO'Q` | — | 1C ning o'z tili server bazasining SUBD turini BERMAYDI. Maydon ataylab yaratilmagan: bo'sh maydon «qarab ko'rmadim» degan yolg'on taassurot berardi (1-jadval, 24-qator). |
| 14 | `platform_bitness` | platforma razryadligi (x86 / x64) | `YO'Q` | — | `СистемнаяИнформация` dan olinmaydi. Kerak bo'lsa ALOHIDA qadam sifatida qo'shiladi. |
| 15 | `session_timezone` | seans vaqt zonasi (alohida maydon) | `YO'Q` | — | `ЧасовойПоясСеанса()` faqat vaqt siljishini hisoblash uchun chaqiriladi; zona maydon bo'lib YOZILMAYDI. Vaqt belgilari inventarning 13-qatorida `RUNTIME-UNKNOWN`. |
| 16 | `configuration_vendor` | konfiguratsiya yetkazuvchisi | `YO'Q` | — | Yig'ilmaydi. `Метаданные.Поставщик` manbada umuman chaqirilmaydi. |
| 17 | `server_name` | 1C server nomi | `YO'Q` | — | **ATAYLAB YO'Q.** Ulanish satri o'qiladi, lekin chiqishga tushmaydi: unda server nomi va foydalanuvchi bo'lishi mumkin. |
| 18 | `user_name` | 1C foydalanuvchisining nomi | `YO'Q` | — | **ATAYLAB YO'Q.** Ma'lumot minimallashtirish: razvedka kim bajarganini yozmaydi. |

**Taqsimot:** 18 qator — `BOR` **10**, `BOR (QISMAN)` **1**, `BOR (BO'SH)` **1**, `YO'Q` **6**.

---

## §11 MAYDONLARI — SHAKL YARASHTIRILDI

2-jadvaldagi §11 maydonlari (`client_kind`, `client_application_name`, `locale`,
`db_type`, `application_mode`, `os_version`) `run_status.json` ning **`platform`**
kalitiga tushadi. Ilgari bu yerda ochiq nuqson bor edi: `binos-1c-run-v1` ning ikki
tomoni bir-biriga ZID kalit yozardi va real paket 9-qadamdagi validatorda
`sxema_va_versiya` tekshiruvida yiqilardi.

**Yarashuv qarori** (`binos-1c-run-v1` — 14 kalit):
`run_version`, `collector`, `mode`, `mode_note`, `started_at`, `finished_at`,
`overall`, `platform`, `sections`, `families`, `probes`, `artifacts`,
`error_count`, `notes`.

Nima o'zgardi va NEGA:
- `probes_run` -> **`probes`** (yig'uvchi nomi olindi — u faylni yozadigan tomon);
- `export_sections` va `metadata_sections` bitta **`sections`** ga birlashdi
  (eksport jurnali `export:`, metadata jurnali `metadata:` prefiksi bilan);
- **`families`** va **`artifacts`** SAQLANDI — bular fail-closed darvozalar:
  `families[].state` `present|absent|unreadable` ajrimini tashiydi va `artifacts`
  yozilgan artefaktlarni sanaydi. Ikkisi ham `overall` ta'rifiga kiradi;
- `platform`, `error_count`, `notes` validator tomoniga QO'SHILDI.

⚠️ `absent` va `unreadable` FAQAT `families[].state` da yashaydi. `sections[].status`
lug'ati `ok|failed|skipped` bo'lib qoladi — «o'qiy olmadim» va «yo'q» bir xil narsa
emas, va bu ajrimni bo'lim holati ifodalay olmaydi.

⚠️ Bu yarashuv **manba matnida** bajarildi. Yig'uvchi hamon kompilyatsiya
QILINMAGAN: kalitlar mos ekani `test_discovery_1c_conformance.py` bilan statik
isbotlangan, real 1C da yozilishi esa `RUNTIME-UNKNOWN`.

---

## KEYINGI QADAM — FAQAT REAL MASHINADA YOPILADI

1-jadvaldagi 19 `UNKNOWN` qatorni statik audit YOPA OLMAYDI. Ular faqat 1C:Enterprise
o'rnatilgan mashinada, **FAQAT AJRATILGAN NUSXADA** yopiladi — tartib:
`integrations/1c/OPERATOR_RUNBOOK.md`.

Har yurishdan keyin 2-jadvalning to'ldirilgan qiymatlari shu hujjatga qaytariladi va
1-jadvalning mos qatori `UNKNOWN` dan o'zgartiriladi. **Sinalmaguncha holat
o'zgartirilmaydi.**
