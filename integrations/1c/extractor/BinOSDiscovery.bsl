// BinOS Discovery Collector — 1C tashqi qayta ishlash MODULI (ObjectModule).
//
// ⚠️⚠️  RUNTIME'DA SINALMAGAN.  Bu manba 1C:Enterprise platformasi BO'LMAGAN mashinada yozilgan.
//       U kompilyatsiya QILINMAGAN, sintaksis tekshiruvidan O'TMAGAN va hech qanday 1C bazasida
//       ISHLATILMAGAN. Ishlatishdan oldin mijozning 1C mutaxassisi Konfiguratorda ochib
//       sintaksisni tekshirishi SHART. «Ishlaydi» degan da'vo YO'Q.
//
// ⚠️⚠️  FAQAT AJRATILGAN NUSXADA.  Bu qayta ishlash HECH QACHON jonli bazada ochilmaydi.
//       Nusxa alohida (do'kon LAN'idagi zaxira) kompyuterga tiklanadi va u yerda ishlatiladi.
//
// ⚠️⚠️  DEFAULT REJIM: METADATA_ONLY.  Yig'uvchi argument berilmaganda birorta AKTIV zond
//       bajarmaydi. Ikkinchi rejim — `APPROVED_PROBES` — FAQAT operator bergan ANIQ allowlist
//       (`(tur, nishon, sabab)` uchliklari) bo'yicha ishlaydi. Noma'lum rejim kelsa yoki
//       allowlist bo'sh bo'lsa — fail-safe/fail-closed: yana `METADATA_ONLY`, birorta zond
//       bajarilmaydi, va bu `run_status.json` ning `mode_note` maydonida OCHIQ qayd etiladi.
//       ⚠️ `ВыполнитьЗонд` to'g'ridan-to'g'ri chaqirilganda HAM shu darvozadan o'tadi: rejim
//       o'rnatilmagan bo'lsa (`ВыполнитьРазведку` chaqirilmagan) zond RAD etiladi. Aks holda
//       rejim shartnomasi faqat bitta kirish nuqtasini qo'riqlardi.
//
// RUNTIME PAKETI — `ВыполнитьРазведку` operator ko'rsatgan papkaga YOZADIGAN fayllar:
//   | fayl                  | shartnoma              | majburiy | mazmuni                    |
//   | export.json           | `binos-1c-export-v1`   | HA       | Phase 2 shakli — O'ZGARMAGAN|
//   | metadata.json         | `binos-1c-metadata-v1` | HA       | Phase 3 shakli — O'ZGARMAGAN|
//   | run_status.json       | `binos-1c-run-v1`      | HA       | rejim, vaqtlar, bo'limlar,  |
//   |                       |                        |          | OILALAR, ARTEFAKTLAR, zondlar|
//   |                       |                        |          | kengaytirilgan platforma    |
//   | errors.json           | `binos-1c-errors-v1`   | HA       | strukturali xatolar (bo'sh  |
//   |                       |                        |          | bo'lishi MUMKIN)            |
//   | run_summary.md        | —                      | HA       | operator uchun: nima bo'ldi |
//   | manifest.json         | `binos-1c-manifest-v1` | HA       | har fayl uchun bayt + sha256|
//   | probes/NN_<tur>.json  | `binos-1c-probe-v1`    | YO'Q     | faqat APPROVED_PROBES       |
//
// ⚠️ NEGA `run_status.json` va `run_summary.md`, `status.json`/`summary.md` EMAS.
//    `binos-1c-discovery-v1` TO'PLAMINING besh a'zosidan ikkitasi AYNAN `status.json` va
//    `summary.md` deb ataladi va ularni BinOS tomonidagi ADAPTER quradi — yig'uvchi emas.
//    Bir xil nom ikki xil sxema: operator papkalarni aralashtirsa, kod ham, odam ham xato
//    faylni o'qiydi. Shu bois runtime paketi BOSHQA nom oladi.
//
// ⚠️ MANIFEST PROVENANS DA'VOSI EMAS. U faqat YOZILGAN BAYTLARNING sha256'si: fayl nomi,
//    bayt hajmi, sha256 — boshqa hech narsa. `source_copy`, `snapshot_at`, `plan_sha256` kabi
//    MANBA provenansi maydonlari ATAYLAB YO'Q: yig'uvchi o'zi nusxada ishlayotganini,
//    snapshot qachon olinganini yoki qanday reja bajarilganini BILA OLMAYDI. Ularni yozish
//    isbotlanmagan da'vo bo'lardi.
//
// ⚠️ `probes/` OSTKI PAPKASINI OPERATOR OLDIN YARATADI. Yig'uvchi katalog yaratmaydi —
//    `СоздатьКаталог` statik audit bilan TAQIQLANGAN (eksport MAVJUD bo'sh papkaga yoziladi).
//    Papka bo'lmasa zond fayllari yozilmaydi, sabab `errors.json` ga tushadi va umumiy holat
//    `SUCCESS` BO'LMAYDI. Bu QOBILIYAT CHEGARASI, yashirilmaydi.
//
// CHIQISH SHARTNOMASI — IKKI HUJJAT, IKKI FAYL:
//   1. `export.json`   — `binos-1c-export-v1`. Shakli O'ZGARMAGAN: TEKIS tuzilma, hamma sanoq
//                        MATN. To'plam shakliga (`binos-1c-discovery-v1`) aylantirishni BinOS
//                        tomonidagi adapter bajaradi (`app/services/discovery_1c/export_adapter.py`).
//   2. `metadata.json` — `binos-1c-metadata-v1`. UNIVERSAL inventarizatsiya: konfiguratsiyada
//                        UMUMAN NIMA BOR. Shakl `app/services/discovery_1c/metadata.py` da
//                        QAT'IY tekshiriladi (kalit oq ro'yxati, sanoq MATN, nomda nuqta yo'q).
// Sabab: to'plam qoidalari murakkab (besh a'zo, holat hisoblanishi), va ularni men sinay
// olmaydigan tilda qurish xatoni tekshirib bo'lmaydigan joyga qo'yish bo'lardi.
//
// NIMA QILADI:   konfiguratsiya METADATASINI o'qiydi, obyektlar sonini sanaydi, ikki hujjat yozadi.
// NIMA QILMAYDI: hech narsa yozmaydi, o'tkazmaydi, o'chirmaydi, monopol rejim olmaydi,
//                tranzaksiya ochmaydi, tarozi bilan almashmaydi, biznes ma'lumotini
//                (narx, mijoz, hujjat qatori, mahsulot nomi) chiqarmaydi.
//
// ⚠️ QATTIQ YOZILGAN KONFIGURATSIYA NOMI YO'Q. Ilgari bu yerda bitta konfiguratsiya oilasiga
//    moslangan nishon ro'yxati bor edi (kutilgan katalog va registr nomlari qidirilardi). U
//    OLIB TASHLANDI: `candidates` kaliti shartnoma shakli uchun QOLADI, lekin BO'SH massiv
//    bo'ladi. Nomzod aniqlash deterministik ekstraksiyadan KEYIN, BinOS tomonidagi analitik
//    qatlamda bajariladi.
// ⚠️ BU YIG'UVCHINING QOBILIYATINI KAMAYTIRADI va bu YASHIRILMAYDI: `export.json` o'zi bilan
//    birorta nishonni ko'rsatmaydi, adapter hamma nishonni UNKNOWN darajasi bilan yozadi.
//    Dalil `metadata.json` da, qaror BinOS tomonida. Sabab `notes` da ham ochiq yozilgan.
//
// TAQIQLANGAN CHAQIRUVLAR statik audit bilan MAJBURLANADI:
// `apps/server/app/services/discovery_1c/epf_audit.py` + `tests/test_discovery_1c_epf_source.py`.
//
// ⚠️ ISHONCH: bu yerda daraja UMUMAN berilmaydi. Yig'uvchi faqat KO'RGANINI yozadi; darajani
//    BinOS tomoni hisoblaydi va u odam tasdig'isiz CANDIDATE dan oshmaydi.
//
// ⚠️ AI DAN KELGAN MATN KOD SIFATIDA BAJARILMAYDI. Model 1C ga o'z so'rovini yubora olmaydi:
//    u faqat `ВыполнитьЗонд` biladigan ZOND TURINI tanlaydi (katalog
//    `app/services/discovery_1c/probe.py` da). Bu modulda dinamik kod bajarish YO'Q.

#Область ПеременныеМодуля

Перем ЖурналРазделов;       // Массив — `export.json` bo'limlari; yiqilgani JIMGINA tushirilmaydi
Перем ЖурналМетаданных;     // Массив — `metadata.json` bo'limlari (alohida hujjat, alohida jurnal)
Перем ВремяНачала;

// ── RUNTIME PAKETI holati ─────────────────────────────────────────────────────────────────
// ⚠️ NEGA UCHINCHI JURNAL. `ЖурналРазделов` va `ЖурналМетаданных` MAVJUD ikki hujjatning
//    shartnomasiga tegishli va ularning tartibi shu hujjatlar ichida qoladi. Runtime paketi
//    esa O'Z bo'limlar ro'yxatini quradi (`СобратьРазделыЗапуска`): u UCHALA jurnalni
//    birlashtiradi, shu bois `overall` ni ikki tomon BITTA ro'yxatdan hisoblaydi.
// ⚠️ BO'LIM LUG'ATI UCHALASIDA BIR XIL: "ok" | "failed" | "skipped" (BinOS tomonida
//    `bundle.SECTION_STATUSES`). ILGARI runtime jurnaliga "absent"/"unreadable" ham yozilardi
//    va aynan shu narsa ikki tomonni ZID qilib qo'ygan: validator bo'lim lug'atida bu ikki
//    qiymatni UMUMAN qabul qilmaydi, ya'ni HAR BIR haqiqiy paket rad etilardi. Endi ular
//    ALOHIDA `ЖурналСемейств` da yashaydi — «oila bormi/o'qildimi» degan savol bo'limning
//    bajarilishidan BOSHQA savol, va ikkisini bitta maydonga tiqish farqni yo'qotardi.
Перем ЖурналЗапуска;        // Массив — `run_status.json`.`sections` (lug'at: ok|failed|skipped)
Перем ЖурналСемейств;       // Массив — `run_status.json`.`families`: present|absent|unreadable
Перем ЖурналАртефактов;     // Массив — `run_status.json`.`artifacts`: YOZILGAN fayl nomlari
Перем ЖурналОшибок;         // Массив — `errors.json`
Перем ЖурналЗондов;         // Массив — bajarilgan zondlar: nomi, nishoni va SABABI
Перем ЖурналФайлов;         // Массив — `manifest.json`: nom, bayt, sha256
Перем РежимРазведки;        // "METADATA_ONLY" | "APPROVED_PROBES"; Неопределено = O'RNATILMAGAN
Перем ЗаметкаРежима;        // rejim QANDAY tanlangani — `run_status.json`.`mode_note`
Перем РежимОтклонен;        // Булево — operator NOMA'LUM rejim so'radi va u BAJARILMADI
Перем РазрешенныеЗондыМодуля;   // Массив — operator bergan allowlist (normallashtirilgan)

#КонецОбласти

#Область ПрограммныйИнтерфейс

// Asosiy kirish nuqtasi. `КаталогВыгрузки` — operator ko'rsatgan BO'SH, MAVJUD papka.
//
// `Режим` — "METADATA_ONLY" (DEFAULT) yoki "APPROVED_PROBES". Berilmasa yoki noma'lum bo'lsa —
// `METADATA_ONLY` (fail-safe) va sabab `run_status.json`.`mode_note` da.
// `РазрешенныеЗонды` — Массив: har elementi `(tur, nishon, sabab)` uchligi (Структура
// `probe_type`/`target_object`/`reason`, yoki 3 elementli Массив). Bo'sh/Неопределено bo'lsa
// birorta zond BAJARILMAYDI (fail-closed).
//
// Qaytaradi: Структура("export", "metadata", "run_status") — uch hujjat. Fayllar jadval
// bo'yicha yoziladi (modul boshidagi RUNTIME PAKETI jadvaliga qarang).
Функция ВыполнитьРазведку(КаталогВыгрузки, Режим = Неопределено, РазрешенныеЗонды = Неопределено) Экспорт

	ЖурналРазделов = Новый Массив;
	ЖурналМетаданных = Новый Массив;
	ЖурналЗапуска = Новый Массив;
	ЖурналСемейств = Новый Массив;
	ЖурналАртефактов = Новый Массив;
	ЖурналОшибок = Новый Массив;
	ЖурналЗондов = Новый Массив;
	ЖурналФайлов = Новый Массив;
	ВремяНачала = ТекущаяДата();

	// ⚠️ ENG BIRINCHI QADAM: rejim. Zond bajaradigan hamma yo'l shu qarordan KEYIN keladi.
	УстановитьРежимРазведки(Режим, РазрешенныеЗонды);
	// ⚠️ REJIM IZOHI `mode_note` DA YASHAYDI, bo'limda EMAS: `ok` bo'limda `error` bo'lishi
	//    BinOS tomonidagi validator bilan TAQIQLANGAN, ya'ni izohni bo'limga qo'yish paketni
	//    RAD ettirardi. Ilgari aynan shunday edi.
	// ⚠️ NOMA'LUM REJIM `ok` EMAS: fail-safe ishlagani bilan operator SO'RAGAN rejim
	//    BAJARILMAGAN. Uni `ok` deb yozish yurishni `SUCCESS` qilib qo'yardi — ya'ni bajarilmagan
	//    talab muvaffaqiyat bo'lib ko'rinardi.
	Если РежимОтклонен Тогда
		ОтметитьЗапуск("mode", "failed", ЗаметкаРежима);
	Иначе
		ОтметитьЗапуск("mode", "ok");
	КонецЕсли;

	Платформа = СобратьПлатформу();
	// ⚠️ Kengaytirilgan platforma AYNAN SHU YERDA yig'iladi, `run_status.json` ni yozish
	//    oldidan EMAS: uning xatolari `errors.json` ga TUSHISHI kerak, u esa keyin yoziladi.
	ПлатформаЗапуска = СобратьПлатформуЗапуска(Платформа);
	Объекты = СобратьОбъекты();
	Счетчики = СобратьСчетчики();
	Кандидаты = СобратьКандидатов();

	// Inventarizatsiya AVVAL yoziladi: uning yozilishi yiqilsa, bu `export.json` jurnalida
	// `write_metadata` bo'lib ko'rinadi. Aks holda ikkinchi hujjatning yo'qligi jimgina
	// «shunchaki bo'lmagan» ga o'xshab qolardi.
	Инвентаризация = СобратьИнвентаризацию();
	МетаданныеЗаписаны = ВыгрузитьИнвентаризацию(КаталогВыгрузки, Инвентаризация);

	Экспорт = Новый Структура;
	Экспорт.Вставить("export_version", "binos-1c-export-v1");
	Экспорт.Вставить("collector", ОписаниеСборщика());
	Экспорт.Вставить("platform", Платформа);
	Экспорт.Вставить("objects", Объекты);
	Экспорт.Вставить("counts", Счетчики);
	Экспорт.Вставить("candidates", Кандидаты);

	Экспорт.Вставить("started_at", ВСтрокуISO(ВремяНачала));
	Экспорт.Вставить("finished_at", ВСтрокуISO(ТекущаяДата()));
	Экспорт.Вставить("collected_at", ВСтрокуISO(ТекущаяДата()));
	Экспорт.Вставить("sections", ЖурналРазделов);
	Экспорт.Вставить("notes", ЗаметкиЭкспорта());

	ЭкспортЗаписан = ВыгрузитьВФайл(КаталогВыгрузки, Экспорт);

	// Aktiv zondlar — FAQAT `APPROVED_PROBES` rejimida va FAQAT allowlist bo'yicha.
	ВыполнитьРазрешенныеЗонды(КаталогВыгрузки);

	// ⚠️ YOZISH TARTIBI VA UNING CHEGARASI (ochiq yozilgan).
	//    export.json → metadata.json → probes/ → run_summary.md → errors.json →
	//    run_status.json → manifest.json.
	//    · `run_summary.md` `run_status.json` dan OLDIN yoziladi, shu bois uning yozilishi
	//      `run_status.json`.`overall` ga KIRADI.
	//    · `errors.json` ham `run_status.json` dan OLDIN yoziladi va uning yozilishi HAM
	//      `overall` ga KIRADI. ILGARI KIRMASDI — bu YOLG'ON SUCCESS yo'li edi: majburiy
	//      artefakt umuman yozilmasa ham yurish `SUCCESS` bo'lib qolardi, holbuki
	//      `errors.json` ning YO'QLIGI «xato bo'lmadi» degani emas, «yig'uvchi tugamadi» degani.
	//    · `errors.json` `manifest.json` dan OLDIN yoziladi, shu bois manifest bosqichida
	//      chiqqan xato (xesh hisoblanmasligi) `errors.json` ga TUSHMAYDI — u manifestning
	//      O'ZIDA `"sha256": null` bo'lib ko'rinadi. Ma'lumot yo'qolmaydi, lekin ikki fayl
	//      sanog'i farq qilishi MUMKIN va bu `run_status.json` izohida aytilgan.
	//    · ⚠️ MANTIQIY CHEGARA — O'ZINI QAYD ETISH. `run_status.json` O'Z ICHIDA `overall` va
	//      `artifacts` ni olib yuradi, ya'ni O'ZI yozilmaganini O'ZIDA aytib bo'lmaydi: fayl
	//      bo'lmasa o'qiladigan da'vo ham yo'q. Shu bois `run_status.json` va `manifest.json`
	//      `artifacts` ga ATAYLAB e'lon qilinadi (yurish shu ikkisini yozish nuqtasiga YETDI),
	//      HAQIQIY tekshiruv esa `manifest.json` orqali bo'ladi: u ENG OXIRGI fayl va o'zidan
	//      OLDINGI hamma faylni (shu bilan `run_status.json` ni ham) nomi, bayti va xeshi bilan
	//      sanaydi. Ya'ni `manifest.json` bor va ichida `run_status.json` bor bo'lsa — ikki
	//      yozish ham bajarilgan; `manifest.json` yo'q bo'lsa — paket TUGALLANMAGAN va buni
	//      papkani ko'rgan BinOS tomoni/operator ko'radi, yig'uvchining o'z da'vosidan EMAS.
	СводкаЗаписана = ЗаписатьСводку(КаталогВыгрузки,
		СводкаТекстом(ОбщееСостояние(ЭкспортЗаписан И МетаданныеЗаписаны)));
	Если СводкаЗаписана Тогда
		ОтметитьЗапуск("write_run_summary", "ok");
	Иначе
		ОтметитьЗапуск("write_run_summary", "failed",
			"`run_summary.md` yozilmadi — sabab `errors.json` da");
	КонецЕсли;

	// ⚠️ QAYTARGAN QIYMAT O'QILADI. Yozish yiqilsa sabab `ЖурналОшибок` ga tushadi, lekin u
	//    AYNAN shu faylga yozilayotgan edi — ya'ni sabab O'ZI bilan yo'qoladi. Shu bois
	//    bosqich ALOHIDA bo'lim bo'lib `run_status.json` da qoladi.
	ОшибкиЗаписаны = ЗаписатьJSONФайл(КаталогВыгрузки, "errors.json", СобратьОшибки(), Истина);
	Если ОшибкиЗаписаны Тогда
		ОтметитьЗапуск("write_errors", "ok");
	Иначе
		ОтметитьЗапуск("write_errors", "failed",
			"`errors.json` yozilmadi — MAJBURIY artefakt; sababning O'ZI shu faylga "
			+ "yozilayotgan edi, shu bois u faqat shu bo'limda qoldi");
	КонецЕсли;

	СостояниеЗапуска = СобратьСостояниеЗапуска(ПлатформаЗапуска,
		ЭкспортЗаписан И МетаданныеЗаписаны И СводкаЗаписана И ОшибкиЗаписаны);
	ЗаписатьJSONФайл(КаталогВыгрузки, "run_status.json", СостояниеЗапуска, Истина);

	// ⚠️ MANIFEST ENG OXIRIDA: u qolgan fayllarni XESHLAYDI, ya'ni ular allaqachon yozilgan
	//    bo'lishi kerak. O'zini xeshlay olmaydi va o'zini ro'yxatga ham qo'shmaydi.
	ЗаписатьJSONФайл(КаталогВыгрузки, "manifest.json", СобратьМанифест(), Ложь);

	Результат = Новый Структура;
	Результат.Вставить("export", Экспорт);
	Результат.Вставить("metadata", Инвентаризация);
	Результат.Вставить("run_status", СостояниеЗапуска);
	Возврат Результат;

КонецФункции

// TASDIQLANGAN FAQAT-O'QISH ZONDLAR KATALOGI — `binos-1c-probe-v1` ning 1C tomoni.
//
// ⚠️ BU FUNKSIYA FAQAT KATALOGDAGI ZOND TURLARINI BILADI. Noma'lum tur kelsa — xato, hech
//    narsa bajarilmaydi. Ro'yxat QO'LDA yozilgan va o'zgarmas; model shu ro'yxatdan TANLAYDI.
// ⚠️ AI DAN KELGAN MATN KOD SIFATIDA BAJARILMAYDI. `ТипЗонда` — katalog kaliti,
//    `ЦелевойОбъект` — metadata manzili. Ikkisining biri ham so'rov matni sifatida
//    ishlatilmaydi: so'rov jadvali nomi metadata obyektining O'ZIDAN (`ПолноеИмя()`) olinadi,
//    kelgan matndan EMAS. Dinamik kod bajarish bu modulda YO'Q.
// ⚠️ ZOND HECH NARSA YOZMAYDI — na bazaga, na diskka. U natijani QAYTARADI; faylni operator
//    yozadi. Yozuvchi zond bu qatlamning butun ma'nosini yo'qotardi.
// ⚠️ NATIJA SHAKLI HALI SHARTNOMA EMAS: BinOS tomonida zond natijasini tekshiradigan
//    validator YO'Q (`probe.py` faqat SO'ROVni tekshiradi). Shuning uchun natija shakliga
//    tayanib kod yozilmasin.
Функция ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект) Экспорт

	Ошибки = Новый Массив;
	Результат = Новый Структура;
	Результат.Вставить("probe_version", "binos-1c-probe-v1");
	Результат.Вставить("probe_type", ТипЗонда);
	Результат.Вставить("target_object", ЦелевойОбъект);
	Результат.Вставить("read_only", "true");     // MATN: `Булево` JSON'da `true` bo'lib ketmasin
	Результат.Вставить("result", Неопределено);
	Результат.Вставить("errors", Ошибки);
	Результат.Вставить("mode", ТекущийРежим());

	// ⚠️ REJIM DARVOZASI — ENG BIRINCHI TEKSHIRUV (§5). Zond FAQAT `APPROVED_PROBES` rejimida
	//    va FAQAT operator bergan allowlistdagi `(tur, nishon)` juftligi uchun bajariladi.
	//    Rejim o'rnatilmagan bo'lsa — DEFAULT `METADATA_ONLY`, ya'ni RAD.
	// ⚠️ NEGA ALLOWLIST HAM TEKSHIRILADI, NEGA FAQAT REJIM EMAS: «rejim APPROVED_PROBES»
	//    o'zi bilan hech qanday zondni TASDIQLAMAYDI — tasdiq aynan `(tur, nishon, sabab)`
	//    uchligida. Faqat rejimni tekshirish «bir marta ruxsat berdim» ni «hamma zondga
	//    ruxsat» ga aylantirardi.
	// ⚠️ Metadata O'QISHI bu darvozadan O'TMAYDI: `ВыполнитьРазведку` ning metadata yo'li
	//    zond emas va `METADATA_ONLY` da to'liq ishlaydi.
	Если Не ЗондРазрешен(ТипЗонда, ЦелевойОбъект) Тогда
		Ошибки.Добавить("zond RAD etildi: rejim `" + ТекущийРежим() + "`, allowlistda "
			+ "(tur, nishon) juftligi yo'q. Aktiv zond FAQAT `APPROVED_PROBES` rejimida va "
			+ "FAQAT operator bergan allowlist bilan bajariladi. Keldi: "
			+ Строка(ТипЗонда) + " / " + Строка(ЦелевойОбъект));
		Возврат Результат;
	КонецЕсли;

	ПутьПоля = "";
	ОбъектМД = НайтиЦелевойОбъект(ЦелевойОбъект, ПутьПоля, Ошибки);
	Если ОбъектМД = Неопределено Тогда
		Возврат Результат;          // sabab `errors` da; jimgina bo'sh javob qaytmaydi
	КонецЕсли;

	ПолноеИмяОбъекта = ПолноеИмяБезопасно(ОбъектМД, Ошибки);

	// NISHON SHARTNOMASI (Python tomoni bilan AYNI):
	//   · `field_type_details` nishoni — MAYDON MANZILI: `<obyekt>.<maydon>` yoki
	//     `<obyekt>.<bo'lim>.<maydon>`;
	//   · QOLGAN hamma zond turining nishoni — OBYEKT: `<obyekt>`.
	// ⚠️ Ilgari maydon yo'li HAMMA tur uchun JIMGINA tashlanardi: `row_count` ga maydon
	//    manzili kelsa, yig'uvchi butun OBYEKTNI o'lchab, xatosiz natija qaytarardi — ya'ni
	//    jimgina BOSHQA nishon. Shu bois ikki tomonning shartnomasi zid edi va
	//    `field_type_details` zondi umuman bajarilmay qolardi. Endi FAIL-CLOSED.
	Если Не ПустаяСтрока(ПутьПоля) И ТипЗонда <> "field_type_details" Тогда
		Ошибки.Добавить("target_object maydon manzili emas, OBYEKT bo'lishi kerak "
			+ "(`<Kolleksiya>.<Nom>`): " + Строка(ТипЗонда) + " zondi maydon yo'lini qabul qilmaydi, "
			+ "keldi: " + Строка(ЦелевойОбъект));
		Возврат Результат;
	КонецЕсли;

	Если ТипЗонда = "object_attributes" Тогда
		Результат.result = ЗондПоляОбъекта(ОбъектМД, Ошибки);
	ИначеЕсли ТипЗонда = "tabular_sections" Тогда
		Результат.result = ТабличныеЧастиОбъекта(ОбъектМД, Ошибки);
	ИначеЕсли ТипЗонда = "referencing_objects" Тогда
		Результат.result = ЗондСсылающиеся(ПолноеИмяОбъекта, Ошибки);
	ИначеЕсли ТипЗонда = "referenced_objects" Тогда
		Результат.result = АдресаПолейОбъекта(ОбъектМД, ПолноеИмяОбъекта, Ошибки);
	ИначеЕсли ТипЗонда = "register_shape" Тогда
		Результат.result = ЗондФормаРегистра(ОбъектМД, Ошибки);
	ИначеЕсли ТипЗонда = "enum_values" Тогда
		Результат.result = ИменаКоллекцииОбъекта(ОбъектМД, "ЗначенияПеречисления", Ошибки);
	ИначеЕсли ТипЗонда = "predefined_names" Тогда
		Результат.result = ИменаКоллекцииОбъекта(ОбъектМД, "ПредопределенныеЭлементы", Ошибки);
	ИначеЕсли ТипЗонда = "row_count" Тогда
		Результат.result = ЗондКоличествоСтрок(ПолноеИмяОбъекта, Ошибки);
	ИначеЕсли ТипЗонда = "field_type_details" Тогда
		Результат.result = ЗондДеталиТипаПоля(ОбъектМД, ПутьПоля, Ошибки);
	ИначеЕсли ТипЗонда = "common_attributes" Тогда
		Результат.result = ЗондОбщиеРеквизиты(ПолноеИмяОбъекта, Ошибки);
	ИначеЕсли ТипЗонда = "characteristic_plans" Тогда
		Результат.result = ЗондПланыВидовХарактеристик(Ошибки);
	Иначе
		// ⚠️ FAIL-CLOSED: noma'lum tur BAJARILMAYDI. «Balki shunga o'xshash narsani qilaman»
		//    degan zaxira yo'l zond katalogining butun ma'nosini yo'qotardi.
		ВызватьИсключение "noma'lum zond turi: " + Строка(ТипЗонда)
			+ ". `ВыполнитьЗонд` faqat `binos-1c-probe-v1` katalogidagi turlarni biladi.";
	КонецЕсли;

	Возврат Результат;

КонецФункции

#КонецОбласти

#Область СлужебныеПроцедуры

Функция ОписаниеСборщика()

	Сборщик = Новый Структура;
	Сборщик.Вставить("name", "BinOSDiscovery");
	Сборщик.Вставить("version", "0.2.0-UNVERIFIED");
	Возврат Сборщик;

КонецФункции

// ── VAQT ──────────────────────────────────────────────────────────────────────────────────
// ⚠️ SINALMAGAN: `СмещениеСтандартногоВремени` yozgi vaqtni hisobga olmaydi. MDH zonalarida
//    yozgi vaqt yo'q, shuning uchun bu yetarli; boshqa zonada tekshirilishi kerak.
Функция ВСтрокуISO(Момент)

	Смещение = 0;
	Попытка
		Смещение = СмещениеСтандартногоВремени(ЧасовойПоясСеанса());
	Исключение
		// Eski platformada bu funksiya bo'lmasligi mumkin — UTC deb belgilaymiz.
	КонецПопытки;

	Знак = ?(Смещение < 0, "-", "+");
	Абсолютное = ?(Смещение < 0, -Смещение, Смещение);
	Часы = Цел(Абсолютное / 3600);
	Минуты = Цел((Абсолютное - Часы * 3600) / 60);

	Возврат Формат(Момент, "ДФ=yyyy-MM-ddTHH:mm:ss") + Знак
		+ Формат(Часы, "ЧЦ=2; ЧВН=; ЧГ=0") + ":" + Формат(Минуты, "ЧЦ=2; ЧВН=; ЧГ=0");

КонецФункции

Процедура ОтметитьРаздел(Имя, Состояние, Описание = Неопределено)

	ЖурналРазделов.Добавить(НовыйРаздел(Имя, Состояние, Описание));

КонецПроцедуры

Процедура ОтметитьРазделМетаданных(Имя, Состояние, Описание = Неопределено)

	ЖурналМетаданных.Добавить(НовыйРаздел(Имя, Состояние, Описание));

КонецПроцедуры

// ⚠️ `ok` bo'limda `error` BO'SH bo'lishi SHART, `failed`/`skipped` da esa TO'LDIRILGAN:
//    ikkalasini ham BinOS tomonidagi validator majburlaydi. Sababsiz yiqilgan bo'lim —
//    «nimadir bo'ldi» degan foydasiz yozuv.
Функция НовыйРаздел(Имя, Состояние, Описание)

	Раздел = Новый Структура;
	Раздел.Вставить("name", Имя);
	Раздел.Вставить("status", Состояние);          // "ok" | "failed" | "skipped"
	Раздел.Вставить("error", Описание);
	Возврат Раздел;

КонецФункции

// ── REJIMLAR (§5) ─────────────────────────────────────────────────────────────────────────
// ⚠️ DEFAULT REJIM: METADATA_ONLY. 1C da konstanta yo'q, shu bois rejim nomlari FUNKSIYA
//    bo'lib beriladi — nom bitta joyda yoziladi va matn xatosi ikki joyda ajralib ketmaydi.
Функция РежимТолькоМетаданные()

	Возврат "METADATA_ONLY";

КонецФункции

Функция РежимРазрешенныеЗонды()

	Возврат "APPROVED_PROBES";

КонецФункции

// Amaldagi rejim. ⚠️ O'RNATILMAGAN holat (`ВыполнитьЗонд` to'g'ridan-to'g'ri chaqirilgan)
// `METADATA_ONLY` ga TENG: o'zgaruvchining yo'qligi HECH QACHON ruxsat bermaydi.
Функция ТекущийРежим()

	Если РежимРазведки = Неопределено Тогда
		Возврат РежимТолькоМетаданные();
	КонецЕсли;
	Возврат РежимРазведки;

КонецФункции

// Zond bajarilishiga RUXSAT bormi. Fail-closed: shubha bo'lsa — YO'Q.
Функция ЗондРазрешен(ТипЗонда, ЦелевойОбъект)

	Если ТекущийРежим() <> РежимРазрешенныеЗонды() Тогда
		Возврат Ложь;
	КонецЕсли;
	Если РазрешенныеЗондыМодуля = Неопределено Тогда
		Возврат Ложь;
	КонецЕсли;
	Для Каждого Заявка Из РазрешенныеЗондыМодуля Цикл
		Если Заявка.probe_type = ТипЗонда И Заявка.target_object = ЦелевойОбъект Тогда
			Возврат Истина;
		КонецЕсли;
	КонецЦикла;
	Возврат Ложь;

КонецФункции

// Rejimni va allowlistni O'RNATADI. ⚠️ Bu YAGONA joy: boshqa hech qayerda rejim yozilmaydi,
// ya'ni «rejimni o'rnatib qo'yish» uchun alohida eksport funksiyasi YO'Q — aks holda u
// darvozani aylanib o'tish yo'li bo'lardi.
Процедура УстановитьРежимРазведки(Режим, РазрешенныеЗонды)

	РазрешенныеЗондыМодуля = Новый Массив;
	// ⚠️ FAIL-CLOSED DEFAULT: bayroq har yurishda ATAYLAB tozalanadi — o'zgaruvchining
	//    yo'qligi hech qachon «rad etilmagan» degani bo'lib qolmasin.
	РежимОтклонен = Ложь;

	Если Режим = Неопределено Тогда
		РежимРазведки = РежимТолькоМетаданные();
		ЗаметкаРежима = "rejim argumenti BERILMAGAN -> fail-safe: METADATA_ONLY, birorta "
			+ "aktiv zond bajarilmaydi";
	ИначеЕсли Строка(Режим) = РежимТолькоМетаданные() Тогда
		РежимРазведки = РежимТолькоМетаданные();
		ЗаметкаРежима = "rejim operator tomonidan METADATA_ONLY deb berildi";
	ИначеЕсли Строка(Режим) = РежимРазрешенныеЗонды() Тогда
		РежимРазведки = РежимРазрешенныеЗонды();
		ЗаметкаРежима = "rejim operator tomonidan APPROVED_PROBES deb berildi";
	Иначе
		// ⚠️ NOMA'LUM REJIM — «balki shunga o'xshash narsani so'ragan» degan talqin YO'Q.
		РежимРазведки = РежимТолькоМетаданные();
		ЗаметкаРежима = "NOMA'LUM rejim keldi (" + Строка(Режим)
			+ ") -> fail-safe: METADATA_ONLY, birorta aktiv zond bajarilmaydi";
		// ⚠️ BAYROQ: operator SO'RAGAN rejim BAJARILMADI. Fail-safe yurishni davom ettiradi,
		//    lekin `mode` bo'limi `failed` bo'ladi va yurish `SUCCESS` BO'LMAYDI — bajarilmagan
		//    talabni muvaffaqiyat deb yozish yolg'on bo'lardi.
		РежимОтклонен = Истина;
		ДобавитьОшибку("mode", Неопределено, Неопределено, "REJECTED", ЗаметкаРежима);
	КонецЕсли;

	Если РежимРазведки <> РежимРазрешенныеЗонды() Тогда
		Если РазрешенныеЗонды <> Неопределено Тогда
			// Allowlist berilgan, lekin rejim uni bajarishga ruxsat bermaydi — JIMGINA
			// bajarilmaydi ham, jimgina bajarilmaydi ham EMAS: sabab yozib qoldiriladi.
			ДобавитьОшибку("mode", Неопределено, Неопределено, "REJECTED",
				"allowlist berildi, lekin rejim " + РежимРазведки
				+ " — birorta zond bajarilmaydi");
		КонецЕсли;
		Возврат;
	КонецЕсли;

	Если РазрешенныеЗонды = Неопределено Тогда
		ЗаметкаРежима = ЗаметкаРежима + "; allowlist Неопределено -> fail-closed: "
			+ "allowlist bo'sh — fail-closed";
		Возврат;
	КонецЕсли;

	Попытка
		Для Каждого Элемент Из РазрешенныеЗонды Цикл
			Заявка = НормализоватьЗаявку(Элемент);
			Если Заявка = Неопределено Тогда
				ДобавитьОшибку("mode", Неопределено, Неопределено, "REJECTED",
					"allowlist elementi (tur, nishon, sabab) uchligi shaklida emas yoki "
					+ "SABABI bo'sh — element RAD etildi");
				Продолжить;
			КонецЕсли;
			РазрешенныеЗондыМодуля.Добавить(Заявка);
		КонецЦикла;
	Исключение
		// Allowlist umuman kezilmasa — birorta zond bajarilmaydi (allowlist bo'sh qoladi).
		ДобавитьОшибку("mode", Неопределено, Неопределено, "REJECTED",
			"allowlist o'qilmadi: " + ОписаниеОшибки());
	КонецПопытки;

	Если РазрешенныеЗондыМодуля.Количество() = 0 Тогда
		ЗаметкаРежима = ЗаметкаРежима + "; allowlist bo'sh — fail-closed";
	Иначе
		ЗаметкаРежима = ЗаметкаРежима + "; allowlistda "
			+ Формат(РазрешенныеЗондыМодуля.Количество(), "ЧГ=0") + " ta tasdiqlangan zond";
	КонецЕсли;

КонецПроцедуры

// Allowlist elementini `(probe_type, target_object, reason)` uchligiga keltiradi.
// ⚠️ SABAB MAJBURIY: sababsiz zond «tasdiqlangan zond» emas. Bo'sh sabab -> element RAD.
// ⚠️ Shakl noto'g'ri bo'lsa `Неопределено` qaytadi — «yaqin ma'noda tushunish» YO'Q.
Функция НормализоватьЗаявку(Элемент)

	ТипЗонда = "";
	Нишон = "";
	Сабаб = "";

	Попытка
		Если ТипЗнч(Элемент) = Тип("Массив") Тогда
			Если Элемент.Количество() <> 3 Тогда
				Возврат Неопределено;
			КонецЕсли;
			ТипЗонда = Строка(Элемент[0]);
			Нишон = Строка(Элемент[1]);
			Сабаб = Строка(Элемент[2]);
		Иначе
			ТипЗонда = Строка(Элемент.probe_type);
			Нишон = Строка(Элемент.target_object);
			Сабаб = Строка(Элемент.reason);
		КонецЕсли;
	Исключение
		Возврат Неопределено;
	КонецПопытки;

	Если ПустаяСтрока(ТипЗонда) Или ПустаяСтрока(Нишон) Или ПустаяСтрока(Сабаб) Тогда
		Возврат Неопределено;
	КонецЕсли;

	Заявка = Новый Структура;
	Заявка.Вставить("probe_type", ТипЗонда);
	Заявка.Вставить("target_object", Нишон);
	Заявка.Вставить("reason", Сабаб);
	Возврат Заявка;

КонецФункции

// Allowlist bo'yicha zondlarni bajaradi va har birini `probes/NN_<tur>.json` ga yozadi.
// ⚠️ `METADATA_ONLY` da bu protsedura BIRORTA zond bajarmaydi va buni `skipped` deb qayd etadi.
Процедура ВыполнитьРазрешенныеЗонды(КаталогВыгрузки)

	Если ТекущийРежим() <> РежимРазрешенныеЗонды() Тогда
		ОтметитьЗапуск("probes", "skipped", "rejim " + ТекущийРежим()
			+ " — birorta aktiv zond bajarilmaydi");
		Возврат;
	КонецЕсли;

	Если РазрешенныеЗондыМодуля.Количество() = 0 Тогда
		ОтметитьЗапуск("probes", "skipped", "allowlist bo'sh — fail-closed");
		Возврат;
	КонецЕсли;

	Номер = 0;
	ТекстОшибок = "";
	Для Каждого Заявка Из РазрешенныеЗондыМодуля Цикл
		Номер = Номер + 1;
		ОтносительныйПуть = "probes/" + Формат(Номер, "ЧЦ=2; ЧВН=; ЧГ=0") + "_"
			+ Заявка.probe_type + ".json";

		// ⚠️ HAR ZOND ALOHIDA `Попытка` ichida: noma'lum tur `ВызватьИсключение` beradi
		//    (fail-closed) va u BUTUN yurishni buzmasligi kerak.
		Результат = Неопределено;
		Попытка
			Результат = ВыполнитьЗонд(Заявка.probe_type, Заявка.target_object);
		Исключение
			ДобавитьОшибку("probe", Неопределено, Заявка.target_object, "PROBE_FAILED",
				"`" + Заявка.probe_type + "` zondi ISTISNO berdi: " + ОписаниеОшибки());
		КонецПопытки;

		Запись = Новый Структура;
		Запись.Вставить("no", Формат(Номер, "ЧЦ=2; ЧВН=; ЧГ=0"));
		Запись.Вставить("probe_type", Заявка.probe_type);
		Запись.Вставить("target_object", Заявка.target_object);
		// ⚠️ SABAB `run_status.json` da KO'RINADI: nima uchun aktiv zond bajarilgani
		//    keyin o'qiladigan yagona javob shu.
		Запись.Вставить("reason", Заявка.reason);
		Запись.Вставить("file", ОтносительныйПуть);
		// ⚠️ TUZATILGAN YOLG'ON `ok`: ilgari bu yerda FAQAT istisno `failed` deb sanalardi.
		//    Nishon topilmagan yoki REJIM DARVOZASI RAD etgan zond istisno BERMAYDI — u
		//    Структура qaytaradi (`result` = Неопределено, `errors` to'ldirilgan), ya'ni
		//    qayd `ok` bo'lib qolardi va `probes/NN.json` da `result: null` turardi.
		СостояниеЗаписи = СостояниеЗонда(Результат);
		Запись.Вставить("status", СостояниеЗаписи);
		ЖурналЗондов.Добавить(Запись);

		// ⚠️ BO'LIM ZOND QAYDI BILAN ZID BO'LMAYDI: qayd `failed` bo'lsa, `probes` bo'limi ham
		//    `failed` bo'lishi SHART. Ilgari bo'lim faqat ISTISNO va YOZISH xatosini sanardi,
		//    ya'ni `result: null` bo'lgan zond bilan yurish `SUCCESS` bo'lib chiqardi.
		Если СостояниеЗаписи = "failed" Тогда
			ТекстОшибок = ТекстОшибок + ОтносительныйПуть + "; ";
		КонецЕсли;

		Если Результат = Неопределено Тогда
			Продолжить;
		КонецЕсли;

		Для Каждого Текст Из Результат.errors Цикл
			ДобавитьОшибку("probe", Неопределено, Заявка.target_object, "PROBE_FAILED",
				"`" + Заявка.probe_type + "` zondi: " + Текст);
		КонецЦикла;

		Если Не ЗаписатьJSONФайл(КаталогВыгрузки, ОтносительныйПуть, Результат, Истина) Тогда
			ТекстОшибок = ТекстОшибок + ОтносительныйПуть + "; ";
		КонецЕсли;
	КонецЦикла;

	Если ПустаяСтрока(ТекстОшибок) Тогда
		ОтметитьЗапуск("probes", "ok");
	Иначе
		ОтметитьЗапуск("probes", "failed", "zond bajarilmadi yoki fayli yozilmadi: "
			+ ТекстОшибок + "— `probes` ostki papkasini OPERATOR oldin yaratishi kerak: "
			+ "yig'uvchi katalog yaratmaydi (statik audit `СоздатьКаталог` ni taqiqlagan)");
	КонецЕсли;

КонецПроцедуры

// ── RUNTIME JURNALLARI (§6) ───────────────────────────────────────────────────────────────
// `run_status.json`.`sections` yozuvi. ⚠️ LUG'AT UCHALA JURNALDA BIR XIL: "ok" | "failed" |
// "skipped". Ilgari bu jurnalga "absent"/"unreadable" ham yozilardi — bu ikki tomonni ZID
// qilib qo'ygan nuqson edi: BinOS tomonidagi validator bo'lim lug'atida bu qiymatlarni UMUMAN
// qabul qilmaydi. Oila holati endi `ОтметитьСемейство` ga tushadi.
Процедура ОтметитьЗапуск(Имя, Состояние, Описание = Неопределено)

	ЖурналЗапуска.Добавить(НовыйРаздел(Имя, Состояние, Описание));

КонецПроцедуры

// `run_status.json`.`families` yozuvi — «bu turdagi obyektlar oilasi BORMI va O'QILDIMI».
// ⚠️ LUG'AT: "present" | "absent" | "unreadable". ENG MUHIM AJRIM SHU YERDA:
//    · "present"    — o'qildi va obyekt BOR.
//    · "absent"     — O'QILDI va BO'SH. Bu TO'LIQ javob, XATO EMAS — shu bois u
//                     `errors.json` ga TUSHMAYDI va umumiy holatni BUZMAYDI.
//    · "unreadable" — O'QIY OLMADIM (huquq, platforma, xato). Bu YO'QLIK EMAS, javobning
//                     O'ZI yo'q — shu bois u `errors.json` da HAM bo'ladi va umumiy holatni
//                     BUZADI.
// ⚠️ `UNKNOWN` ni `NOT_FOUND` deb TALQIN QILISH razvedkaning eng katta yolg'oni bo'lardi:
//    o'qilmagan oila «bu konfiguratsiyada yo'q» bo'lib ko'rinardi va BinOS tomoni uni
//    «absence_proven» darajasiga yaqin deb o'qishi mumkin edi.
// ⚠️ OILA VA BO'LIM BOG'LIQ, LEKIN BITTA NARSA EMAS: oila `unreadable` bo'lsa tegishli bo'lim
//    `failed` bo'ladi; oila `absent` bo'lsa bo'lim `ok` bo'ladi (bo'lim BAJARILDI, javobi —
//    «yo'q»). Shu bog'lanish har chaqiruv joyida ALOHIDA yozilgan.
Процедура ОтметитьСемейство(Имя, Состояние, Описание = Неопределено)

	Запись = Новый Структура;
	Запись.Вставить("name", Имя);
	Запись.Вставить("state", Состояние);       // "present" | "absent" | "unreadable"
	Запись.Вставить("detail", Описание);
	ЖурналСемейств.Добавить(Запись);

КонецПроцедуры

// `run_status.json`.`artifacts` — YOZILGAN fayl nomlari.
// ⚠️ NEGA KERAK: `overall` ning ta'rifi «HAMMA majburiy artefakt yozilgan» dan boshlanadi va
//    BinOS tomoni shu ro'yxatga qarab hukm chiqaradi. Ro'yxat bo'lmasa, «yozildi» degan da'vo
//    hech qanday dalilga bog'lanmagan bo'lardi.
// ⚠️ NOM TAKRORLANMAYDI: `artifacts` da takroriy fayl nomi BinOS tomonida RAD etiladi.
//    `run_status.json` ikki joyda belgilanadi — e'lon qilinganda va haqiqatan yozilganda —
//    shu bois tekshiruv shu yerda, chaqiruv joyida EMAS.
Процедура ОтметитьАртефакт(Имя)

	Для Каждого Мавжуд Из ЖурналАртефактов Цикл
		Если Мавжуд = Имя Тогда
			Возврат;
		КонецЕсли;
	КонецЦикла;
	ЖурналАртефактов.Добавить(Имя);

КонецПроцедуры

// `errors.json` yozuvi — `binos-1c-errors-v1`.
// ⚠️ `Доира` (`scope`) LUG'ATI: "platform" | "family" | "object" | "probe" | "write" | "mode".
// ⚠️ `Код` — BARQAROR KOD, `[A-Z][A-Z0-9_]*`: "UNREADABLE", "OBJECT_FAILED", "WRITE_FAILED",
//    "PROBE_FAILED", "REJECTED", "UNHASHABLE". Ilgari bu maydon `kind` deb atalgan va
//    KICHIK harfda yozilardi — validator kodning shaklini QAT'IY tekshiradi, ya'ni har bir
//    haqiqiy paket shu farq tufayli rad etilardi. Odam o'qiydigan matn `detail` da.
// ⚠️ "absent" BU FAYLDA BO'LMAYDI: «o'qildi va yo'q» XATO emas, u `families` da turadi.
// ⚠️ `Семейство` — METADATA oilasining nomi. Bir nechta oila bitta matnga birlashgan bo'lsa
//    (`metadata_sweep`, `counts`) u `Неопределено` bo'ladi va oila nomlari `detail` ichida
//    qoladi: bitta maydonga ro'yxat tiqish uni mashina o'qiydigan maydon bo'lishdan chiqarardi.
Процедура ДобавитьОшибку(Доира, Семейство, ИмяОбъекта, Код, Матн)

	Запись = Новый Структура;
	Запись.Вставить("scope", Доира);
	Запись.Вставить("family", Семейство);
	Запись.Вставить("object", ИмяОбъекта);
	Запись.Вставить("code", Код);
	Запись.Вставить("detail", Матн);
	ЖурналОшибок.Добавить(Запись);

КонецПроцедуры

// Umumiy holat: "SUCCESS" | "PARTIAL" | "FAILED" — YAGONA TA'RIF (BinOS tomoni AYNAN shunga
// yozadi, ikki tomonning hisobi bir xil chiqishi SHART).
// ⚠️ `SUCCESS` ⇔ hamma MAJBURIY artefakt yozilgan VA birorta bo'lim `failed` emas VA birorta
//    oila `unreadable` emas. Yozish yiqilsa — `FAILED`. Qolgan hamma holda — `PARTIAL`.
// ⚠️ `skipped` bo'lim va `absent` oila SUCCESS ni BUZMAYDI: `METADATA_ONLY` da `probes`
//    bo'limi HAR DOIM `skipped` (bu HALOL default yurish), `absent` esa TO'LIQ javob.
// ⚠️ BO'LIMLAR UCHALA JURNALDAN olinadi (`СобратьРазделыЗапуска`): `platform` bo'limining
//    yiqilishi FAQAT eksport jurnalida qayd etiladi va u hisobga olinmasa, yig'uvchi
//    `SUCCESS`, BinOS tomoni esa `PARTIAL` deb hisoblab paketni RAD etardi.
// ⚠️ CHEGARA: bu funksiya `run_status.json` ning O'ZI va `manifest.json` yozilganini BILA
//    OLMAYDI (ular keyin yoziladi). `ВыполнитьРазведку` izohida yozilgan: ularning haqiqiy
//    mavjudligi `manifest.json` orqali tekshiriladi, yig'uvchining da'vosidan EMAS.
Функция ОбщееСостояние(ОбязательныеЗаписаны)

	Если Не ОбязательныеЗаписаны Тогда
		Возврат "FAILED";
	КонецЕсли;

	Если ЕстьНеудача(СобратьРазделыЗапуска()) Или ЕстьНечитаемоеСемейство() Тогда
		Возврат "PARTIAL";
	КонецЕсли;

	Возврат "SUCCESS";

КонецФункции

Функция ЕстьНеудача(Журнал)

	Для Каждого Раздел Из Журнал Цикл
		Если Раздел.status = "failed" Тогда
			Возврат Истина;
		КонецЕсли;
	КонецЦикла;
	Возврат Ложь;

КонецФункции

// ⚠️ FAQAT `unreadable` tekshiriladi: `absent` — TO'LIQ javob va u yurishni buzmaydi.
Функция ЕстьНечитаемоеСемейство()

	Для Каждого Семейство Из ЖурналСемейств Цикл
		Если Семейство.state = "unreadable" Тогда
			Возврат Истина;
		КонецЕсли;
	КонецЦикла;
	Возврат Ложь;

КонецФункции

// Zond qaydining holati. ⚠️ `ok` FAQAT: natija BOR va zond birorta xato QAYTARMAGAN.
// ⚠️ NEGA IKKI SHART: nishon topilmagan yoki rejim darvozasi RAD etgan zond ISTISNO
//    BERMAYDI — u Структура qaytaradi (`result` = Неопределено, `errors` to'ldirilgan).
//    Faqat istisnoni sanash shu zondlarni `ok` qilib qo'yardi, ya'ni `probes/NN.json` da
//    `result: null` turgan yurish `SUCCESS` bo'lib ko'rinardi.
Функция СостояниеЗонда(Результат)

	Если Результат = Неопределено Тогда
		Возврат "failed";
	КонецЕсли;
	Если Результат.result = Неопределено Тогда
		Возврат "failed";
	КонецЕсли;
	Если Результат.errors.Количество() > 0 Тогда
		Возврат "failed";
	КонецЕсли;
	Возврат "ok";

КонецФункции

// ── PLATFORMA VA KONFIGURATSIYA ───────────────────────────────────────────────────────────
// ⚠️ Uchlik mantiq MATN bilan beriladi ("true"/"false"/"unknown"): `Булево` JSON'da `true`
//    bo'lib ketardi va «bilmayman» ni «yo'q» dan ajratib bo'lmasdi.
Функция СобратьПлатформу()

	Сведения = Новый Структура;
	Сведения.Вставить("platform_version", Неопределено);
	Сведения.Вставить("configuration_name", Неопределено);
	Сведения.Вставить("configuration_version", Неопределено);
	Сведения.Вставить("configuration_modified", "unknown");
	Сведения.Вставить("infobase_mode", "unknown");
	Сведения.Вставить("infobase_id", Неопределено);

	Ошибки = "";
	Попытка
		СистемнаяИнфо = Новый СистемнаяИнформация;
		Сведения.platform_version = СистемнаяИнфо.ВерсияПриложения;
	Исключение
		Ошибки = Ошибки + "platform_version: " + ОписаниеОшибки() + "; ";
	КонецПопытки;

	Попытка
		Сведения.configuration_name = Метаданные.Имя;
		Сведения.configuration_version = Метаданные.Версия;
	Исключение
		Ошибки = Ошибки + "configuration: " + ОписаниеОшибки() + "; ";
	КонецПопытки;

	// ⚠️ §11: «konfiguratsiya o'zgarganmi». Bu maydon ilgari HAMMA VAQT "unknown" edi — ya'ni
	//    e'lon qilingan qobiliyat hech qachon bajarilmagan. Endi to'ldiriladi.
	//    SHAKL O'ZGARMAYDI: kalit allaqachon bor va "true"/"false"/"unknown" uchligi
	//    `binos-1c-export-v1` da RUXSAT ETILGAN, ya'ni bu QIYMAT o'zgarishi, shartnoma emas.
	// ⚠️ Uchlik mantiq MATN: `Булево` JSON'da `true` bo'lib ketardi va «bilmayman» ni «yo'q»
	//    dan ajratib bo'lmasdi.
	Попытка
		Сведения.configuration_modified = ?(КонфигурацияИзменена(), "true", "false");
	Исключение
		Ошибки = Ошибки + "configuration_modified: " + ОписаниеОшибки() + "; ";
	КонецПопытки;

	// Fayl yoki server bazasi — ulanish satridan ANIQLANADI, lekin satrning O'ZI CHIQMAYDI
	// (unda server nomi va foydalanuvchi bo'lishi mumkin).
	Попытка
		СтрокаСоединения = СтрокаСоединенияИнформационнойБазы();
		Если СтрНайти(ВРег(СтрокаСоединения), "FILE=") > 0 Тогда
			Сведения.infobase_mode = "file";
		ИначеЕсли СтрНайти(ВРег(СтрокаСоединения), "SRVR=") > 0 Тогда
			Сведения.infobase_mode = "server";
		КонецЕсли;
	Исключение
		Ошибки = Ошибки + "infobase_mode: " + ОписаниеОшибки() + "; ";
	КонецПопытки;

	Если ПустаяСтрока(Ошибки) Тогда
		ОтметитьРаздел("platform", "ok");
	Иначе
		ОтметитьРаздел("platform", "failed", Ошибки);
		ДобавитьОшибку("platform", Неопределено, Неопределено, "UNREADABLE", Ошибки);
	КонецЕсли;

	Возврат Сведения;

КонецФункции

// ── KENGAYTIRILGAN PLATFORMA TAVSIFI (§11) — FAQAT `run_status.json` UCHUN ─────────────────
// ⚠️ NEGA `export.json` GA EMAS. `binos-1c-export-v1` ning `platform` kalitlari QAT'IY oq
//    ro'yxatda (`export_adapter.PLATFORM_KEYS`) va adapter NOMA'LUM kalitni ham, TUSHIB
//    QOLGAN kalitni ham RAD etadi. Yangi maydon qo'shsak, Phase 2 shartnomasi va uning ustida
//    turgan hamma narsa buzilardi — bu bosqichda REGRESSIYA TAQIQLANGAN.
// ⚠️ NEGA `metadata.json` GA HAM EMAS. `binos-1c-metadata-v1` ning yuqori darajadagi kalitlari
//    ham oq ro'yxatda (`metadata.METADATA_KEYS`) va u yerda `platform` bo'limi UMUMAN YO'Q:
//    qo'shish uchun `metadata.py` ni tahrirlash kerak, u esa BOSHQA agentning fayli. So'rov
//    yig'uvchining `notes` ida qoldirildi (`ЗаметкиЗапуска`).
// ⚠️ NATIJA: §11 maydonlari `run_status.json` ga tushdi — u YANGI shartnoma
//    (`binos-1c-run-v1`) va birorta mavjud validatorga tegmaydi.
// ⚠️ TOPILMAGAN MAYDON `Неопределено` yoki "unknown" bo'lib QOLADI va SABABI `errors.json` ga
//    tushadi. Jimgina tashlanmaydi: «qaramadim» va «yo'q» bir xil narsa emas.
// ⚠️ RUNTIME-UNKNOWN: quyidagi platforma chaqiruvlari SINALMAGAN. Har biri O'Z `Попытка` si
//    ichida — eski relizda funksiya bo'lmasa maydon bo'sh qoladi, butun yig'uvchi yiqilmaydi.
Функция СобратьПлатформуЗапуска(Базовая)

	Сведения = Новый Структура;
	Для Каждого КлючЗначение Из Базовая Цикл
		Сведения.Вставить(КлючЗначение.Ключ, КлючЗначение.Значение);
	КонецЦикла;

	Сведения.Вставить("client_application_name", Неопределено);   // XOM qiymat, talqinsiz
	Сведения.Вставить("client_kind", "unknown");                  // thick|thin|web|other|unknown
	Сведения.Вставить("locale", Неопределено);
	Сведения.Вставить("db_type", "unknown");                      // file|unknown
	Сведения.Вставить("application_mode", "unknown");             // managed|ordinary|unknown
	Сведения.Вставить("os_version", Неопределено);

	// KLIENT TURI. ⚠️ XOM qiymat HAM saqlanadi: talqin (`client_kind`) xato bo'lsa, xom nom
	//    bo'yicha uni keyin tuzatish mumkin. Faqat talqinni yozish ma'lumot yo'qotish bo'lardi.
	Попытка
		Имя = ИмяКлиентскогоПриложения();
		Сведения.client_application_name = Имя;
		Если Имя = "1CV8" Тогда
			Сведения.client_kind = "thick";
		ИначеЕсли Имя = "1CV8C" Тогда
			Сведения.client_kind = "thin";
		ИначеЕсли СтрНайти(ВРег(Имя), "WEB") > 0 Тогда
			Сведения.client_kind = "web";
		ИначеЕсли Не ПустаяСтрока(Имя) Тогда
			// COMConnection, WSConnection, BackgroundJob va boshqalar — «boshqa», «noma'lum» EMAS.
			Сведения.client_kind = "other";
		КонецЕсли;
	Исключение
		ДобавитьОшибку("platform", Неопределено, "client_kind", "UNREADABLE", ОписаниеОшибки());
	КонецПопытки;

	// LOKAL. ⚠️ Faqat BITTA ishonchli manba ishlatiladi; ikkinchi «taxminiy» yo'l YO'Q —
	//    o'ylab chiqarilgan lokal noto'g'ri sanoq formatiga olib kelardi.
	Попытка
		Сведения.locale = КодЛокализацииИнформационнойБазы();
	Исключение
		ДобавитьОшибку("platform", Неопределено, "locale", "UNREADABLE", ОписаниеОшибки());
	КонецПопытки;

	// DB TURI. ⚠️ QOBILIYAT CHEGARASI, OCHIQ YOZILGAN: 1C ning o'z tili SERVER bazasining
	//    SUBD turini (PostgreSQL / MS SQL / Oracle / IBM Db2) BERMAYDI. Fayl bazasi ulanish
	//    satridan aniqlanadi; server bazasida `db_type` "unknown" bo'lib QOLADI va sabab
	//    `errors.json` ga tushadi. Taxmin yozish YOLG'ON dalil bo'lardi.
	// ⚠️ Ulanish satrining O'ZI CHIQMAYDI: unda server nomi va foydalanuvchi bo'lishi mumkin.
	Попытка
		СтрокаСоединения = СтрокаСоединенияИнформационнойБазы();
		Если СтрНайти(ВРег(СтрокаСоединения), "FILE=") > 0 Тогда
			Сведения.db_type = "file";
		Иначе
			ДобавитьОшибку("platform", Неопределено, "db_type", "UNREADABLE",
				"server bazasining SUBD turini 1C tili bermaydi — `unknown` bo'lib qoldi; "
				+ "taxmin yozilmadi");
		КонецЕсли;
	Исключение
		ДобавитьОшибку("platform", Неопределено, "db_type", "UNREADABLE", ОписаниеОшибки());
	КонецПопытки;

	// MANAGED / ORDINARY. ⚠️ Enum QIYMATI bilan solishtiriladi, MATNI bilan emas: `Строка(...)`
	//    lokalizatsiyalangan nom qaytaradi va boshqa tilda taqqoslash jimgina yolg'on bo'lardi.
	Попытка
		Если Метаданные.ОсновнойРежимЗапуска
			= РежимЗапускаКлиентскогоПриложения.УправляемоеПриложение Тогда
			Сведения.application_mode = "managed";
		ИначеЕсли Метаданные.ОсновнойРежимЗапуска
			= РежимЗапускаКлиентскогоПриложения.ОбычноеПриложение Тогда
			Сведения.application_mode = "ordinary";
		КонецЕсли;
	Исключение
		ДобавитьОшибку("platform", Неопределено, "application_mode", "UNREADABLE",
			ОписаниеОшибки());
	КонецПопытки;

	Попытка
		СистемнаяИнфо = Новый СистемнаяИнформация;
		Сведения.os_version = СистемнаяИнфо.ВерсияОС;
	Исключение
		ДобавитьОшибку("platform", Неопределено, "os_version", "UNREADABLE", ОписаниеОшибки());
	КонецПопытки;

	ОтметитьЗапуск("platform_extended", "ok");
	Возврат Сведения;

КонецФункции

// ── KOLLEKSIYA TAVSIFLARI ─────────────────────────────────────────────────────────────────
// ⚠️ BU RO'YXATDA KONFIGURATSIYA NOMI YO'Q — faqat 1C PLATFORMASINING kolleksiya nomlari.
//    Ular har qanday konfiguratsiyada bir xil, ya'ni bu universal bilim.
// `kind` qiymatlari `app/services/discovery_1c/schema.py` dagi SOURCE_KINDS lug'atidan.
Функция ОписаниеКоллекции(ИмяКоллекции, Префикс, ВидИсточника, ИмяРаздела)

	Описание = Новый Структура;
	Описание.Вставить("collection", ИмяКоллекции);
	Описание.Вставить("prefix", Префикс);
	Описание.Вставить("kind", ВидИсточника);
	Описание.Вставить("section", ИмяРаздела);
	Возврат Описание;

КонецФункции

Функция ОписанияКоллекций()

	Список = Новый Массив;
	Список.Добавить(ОписаниеКоллекции("Справочники", "Справочник", "catalog", "catalogs"));
	Список.Добавить(ОписаниеКоллекции("Документы", "Документ", "document", "documents"));
	Список.Добавить(ОписаниеКоллекции("РегистрыСведений", "РегистрСведений",
		"information_register", "information_registers"));
	Список.Добавить(ОписаниеКоллекции("РегистрыНакопления", "РегистрНакопления",
		"accumulation_register", "accumulation_registers"));
	Список.Добавить(ОписаниеКоллекции("ПланыВидовХарактеристик", "ПланВидовХарактеристик",
		"chart_of_characteristic_types", "characteristic_type_plans"));
	Список.Добавить(ОписаниеКоллекции("Перечисления", "Перечисление", "enum", "enums"));
	Список.Добавить(ОписаниеКоллекции("Константы", "Константа", "constant", "constants"));
	Список.Добавить(ОписаниеКоллекции("ОбщиеРеквизиты", "ОбщийРеквизит", "common_attribute",
		"common_attributes"));
	Возврат Список;

КонецФункции

// Kolleksiyani nomi bilan olish. YO'Q bo'lsa — JIMGINA o'tib ketilmaydi: sabab qaytariladi va
// chaqiruvchi uni bo'lim jurnaliga yozadi.
Функция КоллекцияМетаданных(ИмяКоллекции, Причина)

	Попытка
		Возврат Метаданные[ИмяКоллекции];
	Исключение
		Причина = ОписаниеОшибки();
		Возврат Неопределено;
	КонецПопытки;

КонецФункции

// ── METADATA SWEEP — `export.json` uchun TEKIS ro'yxat (SHAKLI O'ZGARMAGAN) ────────────────
Функция СобратьОбъекты()

	Объекты = Новый Массив;
	Ошибки = "";

	Попытка
		Для Каждого Описание Из ОписанияКоллекций() Цикл
			Причина = "";
			Коллекция = КоллекцияМетаданных(Описание.collection, Причина);
			Если Коллекция = Неопределено Тогда
				Ошибки = Ошибки + Описание.collection + ": " + Причина + "; ";
				Продолжить;
			КонецЕсли;
			ДобавитьКоллекцию(Объекты, Коллекция, Описание.prefix, Описание.kind);
		КонецЦикла;
	Исключение
		Ошибки = Ошибки + ОписаниеОшибки();
	КонецПопытки;

	Если ПустаяСтрока(Ошибки) Тогда
		ОтметитьРаздел("metadata_sweep", "ok");
		ОтметитьЗапуск("metadata_sweep", "ok");
	Иначе
		ОтметитьРаздел("metadata_sweep", "failed", Ошибки);
		ОтметитьЗапуск("metadata_sweep", "failed", Ошибки);
		ДобавитьОшибку("family", "metadata_sweep", Неопределено, "UNREADABLE",
			"metadata_sweep: " + Ошибки);
	КонецЕсли;

	Возврат Объекты;

КонецФункции

Процедура ДобавитьКоллекцию(Объекты, Коллекция, Префикс, ВидИсточника)

	// ⚠️ HAR OBYEKT ALOHIDA `Попытка` ICHIDA (§6). Ilgari butun sikl chaqiruvchining bitta
	//    `Попытка` si ichida edi: bitta obyektda `ОбъектМД.Имя` yiqilsa, kolleksiyaning
	//    QOLGAN yuzlab obyekti JIMGINA tushib qolardi va bo'lim shunchaki `failed` bo'lardi —
	//    ya'ni «nimadir bo'ldi» degan foydasiz yozuv. Endi yiqilgan obyekt SANOQLI: qaysi
	//    kolleksiya, qanday xato — `errors.json` da.
	Для Каждого ОбъектМД Из Коллекция Цикл
		Попытка
			ДобавитьОдинОбъектЭкспорта(Объекты, ОбъектМД, Префикс, ВидИсточника);
		Исключение
			ДобавитьОшибку("object", Префикс, Неопределено, "OBJECT_FAILED", ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;

КонецПроцедуры

Процедура ДобавитьОдинОбъектЭкспорта(Объекты, ОбъектМД, Префикс, ВидИсточника)

	ОшибкиОбъекта = Новый Массив;
	Элемент = Новый Структура;
	Элемент.Вставить("full_name", Префикс + "." + ОбъектМД.Имя);
	Элемент.Вставить("kind", ВидИсточника);
	Элемент.Вставить("name", ОбъектМД.Имя);
	Элемент.Вставить("synonym", Неопределено);
	Элемент.Вставить("row_count", Неопределено);
	Элемент.Вставить("children", Новый Массив);

	Попытка
		Элемент.synonym = ОбъектМД.Синоним;
	Исключение
		ОшибкиОбъекта.Добавить("synonym: " + ОписаниеОшибки());
	КонецПопытки;

	ДобавитьПоля(Элемент.children, ОбъектМД, "Реквизиты", "attribute", ОшибкиОбъекта);
	ДобавитьПоля(Элемент.children, ОбъектМД, "Измерения", "dimension", ОшибкиОбъекта);
	ДобавитьПоля(Элемент.children, ОбъектМД, "Ресурсы", "resource", ОшибкиОбъекта);
	ДобавитьТабличныеЧасти(Элемент.children, ОбъектМД, ОшибкиОбъекта);

	Элемент.Вставить("errors", ОшибкиОбъекта);
	Объекты.Добавить(Элемент);

	// ⚠️ Obyekt darajasidagi xato `export.json` ning O'ZIDA ham qoladi (`errors` kaliti —
	//    shakl O'ZGARMAGAN), lekin u `errors.json` ga HAM tushadi: operator bitta faylda
	//    butun yurishning xatolarini ko'rishi kerak.
	Для Каждого Текст Из ОшибкиОбъекта Цикл
		ДобавитьОшибку("object", Префикс, Элемент.full_name, "OBJECT_FAILED", Текст);
	КонецЦикла;

КонецПроцедуры

Процедура ДобавитьПоля(Дети, ОбъектМД, ИмяКоллекции, ВидПоля, ОшибкиОбъекта)

	Попытка
		Коллекция = ОбъектМД[ИмяКоллекции];
	Исключение
		Возврат;      // Bu obyekt turida bunday kolleksiya yo'q — xato emas, shakl farqi.
	КонецПопытки;

	Для Каждого Поле Из Коллекция Цикл
		Попытка
			Ребенок = Новый Структура;
			Ребенок.Вставить("name", Поле.Имя);
			Ребенок.Вставить("kind", ВидПоля);
			Ребенок.Вставить("type", ОписаниеТипаСтрокой(Поле.Тип));
			Ребенок.Вставить("synonym", Поле.Синоним);
			Дети.Добавить(Ребенок);
		Исключение
			ОшибкиОбъекта.Добавить(ИмяКоллекции + "." + Поле.Имя + ": " + ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;

КонецПроцедуры

Процедура ДобавитьТабличныеЧасти(Дети, ОбъектМД, ОшибкиОбъекта)

	Попытка
		Коллекция = ОбъектМД.ТабличныеЧасти;
	Исключение
		Возврат;
	КонецПопытки;

	Для Каждого ТабличнаяЧасть Из Коллекция Цикл
		Попытка
			Для Каждого Реквизит Из ТабличнаяЧасть.Реквизиты Цикл
				Ребенок = Новый Структура;
				Ребенок.Вставить("name", ТабличнаяЧасть.Имя + "." + Реквизит.Имя);
				Ребенок.Вставить("kind", "tabular_section");
				Ребенок.Вставить("type", ОписаниеТипаСтрокой(Реквизит.Тип));
				Ребенок.Вставить("synonym", Реквизит.Синоним);
				Дети.Добавить(Ребенок);
			КонецЦикла;
		Исключение
			ОшибкиОбъекта.Добавить("ТЧ." + ТабличнаяЧасть.Имя + ": " + ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;

КонецПроцедуры

// Tip — MATN sifatida. Razryadlik muhim: qoldiq 3 kasr xonalimi, narx 2 mi?
// ⚠️ BO'SH MATN QAYTMAYDI: BinOS tomonidagi validator bo'sh `type` ni RAD etadi, ya'ni bo'sh
//    matn butun hujjatni o'qilmas qilardi. Bilmaganda "unknown" yoziladi.
Функция ОписаниеТипаСтрокой(ОписаниеТипаЗначения)

	Части = Новый Массив;
	Попытка
		Для Каждого Тип Из ОписаниеТипаЗначения.Типы() Цикл
			Части.Добавить(Строка(Тип));
		КонецЦикла;
		Результат = СтрСоединить(Части, "|");

		КвалификаторыЧисла = ОписаниеТипаЗначения.КвалификаторыЧисла;
		Если КвалификаторыЧисла <> Неопределено Тогда
			Результат = Результат + "(" + Формат(КвалификаторыЧисла.Разрядность, "ЧГ=0")
				+ "," + Формат(КвалификаторыЧисла.РазрядностьДробнойЧасти, "ЧГ=0") + ")";
		КонецЕсли;

		КвалификаторыСтроки = ОписаниеТипаЗначения.КвалификаторыСтроки;
		Если КвалификаторыСтроки <> Неопределено Тогда
			Результат = Результат + "(" + Формат(КвалификаторыСтроки.Длина, "ЧГ=0") + ")";
		КонецЕсли;
		Если ПустаяСтрока(Результат) Тогда
			Возврат "unknown";
		КонецЕсли;
		Возврат Результат;
	Исключение
		Возврат "unknown";
	КонецПопытки;

КонецФункции

// ── SANOQLAR — FAQAT КОЛИЧЕСТВО(*) ────────────────────────────────────────────────────────
// ⚠️ Birorta QATOR chiqmaydi. Qiymat MATN — JSON soni TAQIQLANGAN.
// ⚠️ Sanoq FAQAT `export.json` da. `metadata.json` so'rov YUBORMAYDI: inventarizatsiya
//    metadata o'qishdan iborat, ya'ni u katta bazada ham tez tugaydi.
Функция СобратьСчетчики()

	Счетчики = Новый Массив;
	Ошибки = "";

	Попытка
		Для Каждого Описание Из ОписанияКоллекций() Цикл
			Если Не СчитаемаяКоллекция(Описание.kind) Тогда
				Продолжить;
			КонецЕсли;
			Причина = "";
			Коллекция = КоллекцияМетаданных(Описание.collection, Причина);
			Если Коллекция = Неопределено Тогда
				Ошибки = Ошибки + Описание.collection + ": " + Причина + "; ";
				Продолжить;
			КонецЕсли;
			ДобавитьСчетчики(Счетчики, Коллекция, Описание.prefix);
		КонецЦикла;
	Исключение
		Ошибки = Ошибки + ОписаниеОшибки();
	КонецПопытки;

	Если ПустаяСтрока(Ошибки) Тогда
		ОтметитьРаздел("counts", "ok");
		ОтметитьЗапуск("counts", "ok");
	Иначе
		ОтметитьРаздел("counts", "failed", Ошибки);
		ОтметитьЗапуск("counts", "failed", Ошибки);
		ДобавитьОшибку("family", "counts", Неопределено, "UNREADABLE",
			"counts: " + Ошибки);
	КонецЕсли;

	Возврат Счетчики;

КонецФункции

// Qaysi kolleksiyalarda `КОЛИЧЕСТВО(*)` ma'noga ega. Konfiguratsiya nomi emas — PLATFORMA
// tushunchasi: Перечисление va Константа da jadval yo'q, ОбщийРеквизит esa o'z jadvalisiz.
Функция СчитаемаяКоллекция(ВидИсточника)

	Возврат ВидИсточника = "catalog"
		Или ВидИсточника = "document"
		Или ВидИсточника = "information_register"
		Или ВидИсточника = "accumulation_register"
		Или ВидИсточника = "chart_of_characteristic_types";

КонецФункции

Процедура ДобавитьСчетчики(Счетчики, Коллекция, Префикс)

	Для Каждого ОбъектМД Из Коллекция Цикл
		ПолноеИмя = Префикс + "." + ОбъектМД.Имя;
		Запись = Новый Структура;
		Запись.Вставить("name", ПолноеИмя);
		Запись.Вставить("scope", "table");
		Запись.Вставить("value", Неопределено);
		ОшибкиСчетчика = Новый Массив;

		Попытка
			Запрос = Новый Запрос;
			// ⚠️ Jadval nomi METADATA dan keladi (kolleksiyani kezib chiqqanimizda), tashqi
			//    matndan EMAS. Bu yerda tashqaridan kelgan birorta belgi so'rovga tushmaydi.
			Запрос.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмя;
			Выборка = Запрос.Выполнить().Выбрать();
			Если Выборка.Следующий() Тогда
				Запись.value = Формат(Выборка.Кол, "ЧГ=0");
			Иначе
				Запись.value = "0";
			КонецЕсли;
		Исключение
			ОшибкиСчетчика.Добавить(ОписаниеОшибки());
		КонецПопытки;

		Запись.Вставить("errors", ОшибкиСчетчика);
		Счетчики.Добавить(Запись);
	КонецЦикла;

КонецПроцедуры

// ── NOMZODLAR — ATAYLAB BO'SH ─────────────────────────────────────────────────────────────
// ⚠️ `candidates` kaliti SHARTNOMA SHAKLI uchun qoladi (adapter uni qat'iy tekshiradi), lekin
//    BO'SH massiv qaytariladi. Ilgari bu yerda kutilgan katalog va registr NOMLARI QATTIQ
//    YOZILGAN edi — ya'ni yig'uvchi bitta konfiguratsiya oilasiga moslangan edi va boshqa
//    konfiguratsiyada jimgina «hech narsa topilmadi» deb qaytarardi.
// ⚠️ NOMZOD ANIQLASH ENDI BINOS TOMONIDA: deterministik ekstraksiyadan KEYIN, `metadata.json`
//    ustidagi analitik qatlamda. Sabab: nom mosligi O'ZI BILAN hech qachon tasdiqlangan
//    xarita bermaydi, ya'ni uni 1C ichida — sinab bo'lmaydigan joyda — hisoblashdan foyda yo'q.
// ⚠️ BU QOBILIYATNI KAMAYTIRADI va yashirilmaydi: sabab `notes` da ham yozilgan. Bo'lim
//    jurnalida `candidates` `ok` holatida qoladi (bo'lim BAJARILDI: qarori — bo'sh ro'yxat),
//    chunki `ok` bo'limda `error` bo'lishi validator tomonidan taqiqlangan.
Функция СобратьКандидатов()

	Кандидаты = Новый Массив;
	ОтметитьРаздел("candidates", "ok");
	Возврат Кандидаты;

КонецФункции

// ── INVENTARIZATSIYA — `binos-1c-metadata-v1` ─────────────────────────────────────────────
// ⚠️ BU HUJJATDA TALQIN YO'Q: nishon, ishonch darajasi, xarita — hech biri yo'q. U «nima bor»
//    ni yozadi, «nima ma'nosi» ni EMAS.
// ⚠️ BIZNES QATORI CHIQMAYDI. Faqat metadata: nomlar, sinonimlar, izohlar, tip MATNI, havola
//    nishonlari, sanab o'tilgan qiymat NOMLARI.
Функция СобратьИнвентаризацию()

	Объекты = Новый Массив;

	Для Каждого Описание Из ОписанияКоллекций() Цикл
		СобратьКоллекциюИнвентаризации(Объекты, Описание);
	КонецЦикла;

	// ⚠️ ПланыСчетов ATAYLAB alohida: shakl lug'atida hisob rejasi uchun `kind` YO'Q.
	ОтметитьПланыСчетов();

	Документ = Новый Структура;
	Документ.Вставить("metadata_version", "binos-1c-metadata-v1");
	Документ.Вставить("collector", ОписаниеСборщика());
	Документ.Вставить("collected_at", ВСтрокуISO(ТекущаяДата()));
	Документ.Вставить("objects", Объекты);
	Документ.Вставить("sections", ЖурналМетаданных);
	Документ.Вставить("notes", ЗаметкиИнвентаризации());
	Возврат Документ;

КонецФункции

Процедура СобратьКоллекциюИнвентаризации(Объекты, Описание)

	Причина = "";
	Коллекция = КоллекцияМетаданных(Описание.collection, Причина);
	Если Коллекция = Неопределено Тогда
		// ⚠️ «Qaralmadi» va «yo'q» bir xil narsa emas: kolleksiyaning o'zi yo'qligi ham JAVOB
		//    va u sababi bilan jurnalda qoladi.
		ОтметитьРазделМетаданных(Описание.section, "skipped",
			"`" + Описание.collection + "` kolleksiyasi bu platformada/konfiguratsiyada "
			+ "o'qilmadi: " + Причина);
		// ⚠️ `unreadable` — «O'QIY OLMADIM», `absent` EMAS. U OILA holati: bo'lim lug'atida
		//    (`ok|failed|skipped`) bunday qiymat YO'Q va uni bo'limga yozish paketni RAD
		//    ettirardi. OILA o'qilmasa — tegishli BO'LIM `failed`.
		ОтметитьСемейство(Описание.collection, "unreadable",
			"`" + Описание.collection + "` O'QILMADI: " + Причина
			+ " — bu «bu konfiguratsiyada YO'Q» degani EMAS");
		ОтметитьЗапуск(Описание.section, "failed",
			"`" + Описание.collection + "` O'QILMADI: " + Причина);
		ДобавитьОшибку("family", Описание.collection, Неопределено, "UNREADABLE", Причина);
		Возврат;
	КонецЕсли;

	// ⚠️ SANOQ XATOSI va OBYEKT XATOSI ALOHIDA yig'iladi: birinchisi oilani O'QIB
	//    BO'LMAGANINI (`unreadable`), ikkinchisi esa oila O'QILGANINI lekin ayrim obyektlar
	//    tushib qolganini bildiradi (`present` + bo'lim `failed`). Ilgari ikkisi bitta matnda
	//    edi, ya'ni ajrimni keyin tiklab bo'lmasdi.
	ОшибкаСчета = "";
	Сколько = -1;
	Попытка
		Сколько = Коллекция.Количество();
	Исключение
		ОшибкаСчета = "Количество(): " + ОписаниеОшибки() + "; ";
		ДобавитьОшибку("family", Описание.collection, Неопределено, "UNREADABLE", ОшибкаСчета);
	КонецПопытки;

	// ⚠️ HAR OBYEKT ALOHIDA `Попытка` ICHIDA (§6): ilgari butun sikl BITTA `Попытка` da edi,
	//    ya'ni bitta obyektning inspeksiyasi yiqilsa KOLLEKSIYANING QOLGANI ham tashlanib
	//    ketardi. Endi yiqilgan obyekt sanoqli va qolganlari yoziladi.
	ОшибкиОбъектов = "";
	Для Каждого ОбъектМД Из Коллекция Цикл
		Попытка
			Элемент = ОписатьОбъект(ОбъектМД, Описание.prefix, Описание.kind);
		Исключение
			ОшибкиОбъектов = ОшибкиОбъектов + ОписаниеОшибки() + "; ";
			ДобавитьОшибку("object", Описание.collection, Неопределено, "OBJECT_FAILED",
				ОписаниеОшибки());
			Продолжить;
		КонецПопытки;
		Объекты.Добавить(Элемент);
		// ⚠️ Obyekt ICHIDAGI xato bo'limni `failed` QILMAYDI (Phase 3 shakli shunday edi va
		//    unga tegilmaydi) — lekin u `errors.json` da KO'RINADI.
		Для Каждого Текст Из Элемент.errors Цикл
			ДобавитьОшибку("object", Описание.collection, Элемент.full_name, "OBJECT_FAILED", Текст);
		КонецЦикла;
	КонецЦикла;

	Если Не ПустаяСтрока(ОшибкаСчета) Тогда
		ОтметитьСемейство(Описание.collection, "unreadable", ОшибкаСчета
			+ "— kolleksiyaga murojaat qilindi, lekin javobning O'ZI olinmadi");
		ОтметитьРазделМетаданных(Описание.section, "failed", ОшибкаСчета + ОшибкиОбъектов);
		ОтметитьЗапуск(Описание.section, "failed", ОшибкаСчета + ОшибкиОбъектов);
		Возврат;
	КонецЕсли;

	// ⚠️ OILA HOLATI SANOQ bilan aniqlanadi, BO'LIM holati esa bajarilish bilan — ikkisi
	//    BOSHQA savol va shu bois ALOHIDA yoziladi.
	Если Сколько = 0 Тогда
		// ⚠️ `absent` — kolleksiya O'QILDI va BO'SH. Bu TO'LIQ javob, XATO EMAS: shu bois u
		//    `errors.json` ga TUSHMAYDI va umumiy holatni BUZMAYDI. `unreadable` bilan
		//    aralashtirish razvedkaning eng katta yolg'oni bo'lardi — «qaramadim» «yo'q» ga
		//    aylanib qolardi.
		ОтметитьСемейство(Описание.collection, "absent",
			"`" + Описание.collection + "` O'QILDI va BO'SH: bu konfiguratsiyada bu turdagi "
			+ "obyekt YO'Q. Bu TO'LIQ javob, «o'qilmadi» EMAS.");
	Иначе
		ОтметитьСемейство(Описание.collection, "present",
			"o'qildi, " + Формат(Сколько, "ЧГ=0") + " ta obyekt");
	КонецЕсли;

	Если Не ПустаяСтрока(ОшибкиОбъектов) Тогда
		ОтметитьРазделМетаданных(Описание.section, "failed", ОшибкиОбъектов);
		ОтметитьЗапуск(Описание.section, "failed", ОшибкиОбъектов);
		Возврат;
	КонецЕсли;

	ОтметитьРазделМетаданных(Описание.section, "ok");
	// ⚠️ `absent` OILA bo'limni BUZMAYDI: bo'lim BAJARILDI, javobi — «yo'q».
	ОтметитьЗапуск(Описание.section, "ok");

КонецПроцедуры

// ⚠️ Hisob rejasi: `binos-1c-metadata-v1` ning `kind` lug'atida hisob rejasi uchun qiymat YO'Q,
//    boshqa `kind` bilan yozish esa YOLG'ON bo'lardi (hujjat o'qiganda hisob rejasi katalogga
//    o'xshab ko'rinardi). Shu bois faqat MAVJUDLIGI qayd etiladi. JIMGINA o'tib ketilmaydi:
//    bo'lim jurnalida sababi bilan `skipped` bo'lib qoladi.
Процедура ОтметитьПланыСчетов()

	Причина = "";
	Коллекция = КоллекцияМетаданных("ПланыСчетов", Причина);
	Если Коллекция = Неопределено Тогда
		ОтметитьРазделМетаданных("chart_of_accounts", "skipped",
			"`ПланыСчетов` kolleksiyasi o'qilmadi (bu konfiguratsiyada bo'lmasligi mumkin): "
			+ Причина);
		// ⚠️ IXTIYORIY TUR bo'lsa ham «o'qilmadi» «yo'q» EMAS: bu yerda kolleksiyaga
		//    MUROJAAT yiqildi, ya'ni `unreadable` — va u OILA holati, bo'lim holati emas.
		ОтметитьСемейство("ПланыСчетов", "unreadable", Причина);
		ОтметитьЗапуск("chart_of_accounts", "failed",
			"`ПланыСчетов` O'QILMADI: " + Причина);
		ДобавитьОшибку("family", "ПланыСчетов", Неопределено, "UNREADABLE", Причина);
		Возврат;
	КонецЕсли;

	Попытка
		Сколько = Формат(Коллекция.Количество(), "ЧГ=0");
	Исключение
		ОтметитьСемейство("ПланыСчетов", "unreadable", ОписаниеОшибки());
		ОтметитьРазделМетаданных("chart_of_accounts", "failed", ОписаниеОшибки());
		ОтметитьЗапуск("chart_of_accounts", "failed", ОписаниеОшибки());
		ДобавитьОшибку("family", "ПланыСчетов", Неопределено, "UNREADABLE", ОписаниеОшибки());
		Возврат;
	КонецПопытки;

	Если Сколько = "0" Тогда
		ОтметитьСемейство("ПланыСчетов", "absent",
			"`ПланыСчетов` O'QILDI va BO'SH — bu konfiguratsiyada hisob rejasi YO'Q");
		// ⚠️ `absent` OILA bo'limni BUZMAYDI: bo'lim BAJARILDI va javob berdi.
		ОтметитьЗапуск("chart_of_accounts", "ok");
	Иначе
		// Kolleksiya bor, lekin tarkibi ATAYLAB olinmaydi (shakl lug'atida `kind` yo'q).
		ОтметитьСемейство("ПланыСчетов", "present",
			"kolleksiya topildi (" + Сколько + " ta obyekt); tarkibi ATAYLAB olinmadi");
		ОтметитьЗапуск("chart_of_accounts", "skipped",
			"kolleksiya topildi (" + Сколько + " ta obyekt), tarkibi ATAYLAB olinmadi: "
			+ "`binos-1c-metadata-v1` lug'atida hisob rejasi uchun `kind` yo'q");
	КонецЕсли;

	ОтметитьРазделМетаданных("chart_of_accounts", "skipped",
		"kolleksiya topildi (" + Сколько + " ta obyekt), lekin `binos-1c-metadata-v1` ning "
		+ "`kind` lug'atida hisob rejasi uchun qiymat yo'q — boshqa `kind` bilan yozish "
		+ "hujjatni o'qiganni chalg'itardi. Tarkibi OLINMADI; kerak bo'lsa shakl versiyasi "
		+ "oshirilib qo'shiladi.");

КонецПроцедуры

// ── OBYEKT TAVSIFI (ObjectDoc) ────────────────────────────────────────────────────────────
// Kalitlar AYNAN `metadata.py` dagi OBJECT_KEYS: noma'lum ham, tushib qolgan ham — RAD.
Функция ОписатьОбъект(ОбъектМД, Префикс, ВидИсточника)

	Ошибки = Новый Массив;
	// Obyekt darajasidagi maydonlar (Реквизиты/Измерения/Ресурсы va standart rekvizitlar) BITTA
	// nom maydonini bo'lishadi: grafda ularning manzili `<obyekt>.<nom>` bo'ladi. Takror nom
	// hujjatni RAD qilardi, shuning uchun takror TASHLANADI va sababi `errors` ga yoziladi.
	Занятые = Новый Соответствие;

	Элемент = Новый Структура;
	Элемент.Вставить("full_name", Префикс + "." + ОбъектМД.Имя);
	Элемент.Вставить("kind", ВидИсточника);
	Элемент.Вставить("name", ОбъектМД.Имя);
	Элемент.Вставить("synonym", ТекстСвойства(ОбъектМД, "Синоним", Ошибки));
	Элемент.Вставить("comment", ТекстСвойства(ОбъектМД, "Комментарий", Ошибки));
	Элемент.Вставить("hierarchical", Иерархичность(ОбъектМД, ВидИсточника, Ошибки));
	// ⚠️ `row_count` bu hujjatda ATAYLAB bo'sh: inventarizatsiya so'rov yubormaydi. Sanoqlar
	//    `export.json` ning `counts` bo'limida va `row_count` zondida.
	Элемент.Вставить("row_count", Неопределено);

	Реквизиты = ПоляКоллекции(ОбъектМД, "Реквизиты", "attribute", Занятые, Ошибки);
	ДобавитьСтандартныеРеквизиты(Реквизиты, ОбъектМД, Занятые, Ошибки);
	ДобавитьСобственныйТип(Реквизиты, ОбъектМД, ВидИсточника, Занятые, Ошибки);
	Элемент.Вставить("attributes", Реквизиты);
	Элемент.Вставить("dimensions", ПоляКоллекции(ОбъектМД, "Измерения", "dimension",
		Занятые, Ошибки));
	Элемент.Вставить("resources", ПоляКоллекции(ОбъектМД, "Ресурсы", "resource",
		Занятые, Ошибки));
	Элемент.Вставить("tabular_sections", ТабличныеЧастиОбъекта(ОбъектМД, Ошибки));
	Элемент.Вставить("enum_values", ИменаКоллекцииОбъекта(ОбъектМД, "ЗначенияПеречисления",
		Ошибки));
	Элемент.Вставить("predefined", ИменаКоллекцииОбъекта(ОбъектМД, "ПредопределенныеЭлементы",
		Ошибки));
	Элемент.Вставить("register_kind", ВидРегистраТекстом(ОбъектМД, ВидИсточника, Ошибки));
	Элемент.Вставить("periodicity", ПериодичностьТекстом(ОбъектМД, ВидИсточника, Ошибки));
	Элемент.Вставить("errors", Ошибки);
	Возврат Элемент;

КонецФункции

Функция ТекстСвойства(ОбъектМД, ИмяСвойства, Ошибки)

	Попытка
		Значение = ОбъектМД[ИмяСвойства];
	Исключение
		Ошибки.Добавить(ИмяСвойства + ": " + ОписаниеОшибки());
		Возврат Неопределено;
	КонецПопытки;

	Если Значение = Неопределено Тогда
		Возврат Неопределено;
	КонецЕсли;
	Возврат Строка(Значение);

КонецФункции

// Uchlik mantiq MATN bilan: "true" / "false" / "unknown".
// ⚠️ "unknown" = «yig'uvchi qaramadi yoki qaray olmadi», "false" = «qaradi va yo'q». Ikkisi
//    bir xil emas, shuning uchun ierarxiya tushunchasi BO'LMAGAN turlarda "false" yoziladi
//    (bu HAQIQAT: hujjat ierarxik emas), o'qish yiqilganda esa "unknown".
Функция Иерархичность(ОбъектМД, ВидИсточника, Ошибки)

	Если ВидИсточника <> "catalog" И ВидИсточника <> "chart_of_characteristic_types" Тогда
		Возврат "false";
	КонецЕсли;

	Попытка
		Возврат ?(ОбъектМД.Иерархический, "true", "false");
	Исключение
		Ошибки.Добавить("hierarchical: " + ОписаниеОшибки());
		Возврат "unknown";
	КонецПопытки;

КонецФункции

// Registr turi: Остатки -> balance, Обороты -> turnover.
// ⚠️ `null` = «bu obyektda qoldiq/aylanma tushunchasi YO'Q» (masalan РегистрСведений yoki
//    katalog), "unknown" = «registr, lekin turini o'qiy olmadim». Ikkisini qo'shib yuborish
//    «ma'lumot yo'q» ni «tushuncha yo'q» ga aylantirardi.
Функция ВидРегистраТекстом(ОбъектМД, ВидИсточника, Ошибки)

	Если ВидИсточника <> "accumulation_register" Тогда
		Возврат Неопределено;
	КонецЕсли;

	Попытка
		Если ОбъектМД.ВидРегистра = Метаданные.СвойстваОбъектов.ВидРегистраНакопления.Остатки Тогда
			Возврат "balance";
		ИначеЕсли ОбъектМД.ВидРегистра
			= Метаданные.СвойстваОбъектов.ВидРегистраНакопления.Обороты Тогда
			Возврат "turnover";
		КонецЕсли;
		Ошибки.Добавить("register_kind: platforma tanimagan registr turi berdi");
		Возврат "unknown";
	Исключение
		Ошибки.Добавить("register_kind: " + ОписаниеОшибки());
		Возврат "unknown";
	КонецПопытки;

КонецФункции

// Davriylik — XOM MATN. Uni lug'atga solish TALQIN bo'lardi: platforma versiyalari qiymat
// nomlarini boshqacha yozadi va noto'g'ri moslash jimgina xato beradi.
Функция ПериодичностьТекстом(ОбъектМД, ВидИсточника, Ошибки)

	Если ВидИсточника <> "information_register" Тогда
		Возврат Неопределено;
	КонецЕсли;

	Попытка
		Возврат Строка(ОбъектМД.ПериодичностьРегистраСведений);
	Исключение
		Ошибки.Добавить("periodicity: " + ОписаниеОшибки());
		Возврат Неопределено;
	КонецПопытки;

КонецФункции

// ── MAYDONLAR (FieldDoc) ──────────────────────────────────────────────────────────────────
Функция ПоляКоллекции(ОбъектМД, ИмяКоллекции, ВидПоля, Занятые, Ошибки)

	Поля = Новый Массив;
	Попытка
		Коллекция = ОбъектМД[ИмяКоллекции];
	Исключение
		Возврат Поля;      // Bu obyekt turida bunday kolleksiya yo'q — xato emas, shakl farqi.
	КонецПопытки;

	Для Каждого Поле Из Коллекция Цикл
		Попытка
			ДобавитьПолеОдин(Поля, Поле.Имя, Поле.Тип, ВидПоля,
				ТекстСвойства(Поле, "Синоним", Ошибки), Занятые, Ошибки);
		Исключение
			Ошибки.Добавить(ИмяКоллекции + ": " + ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;
	Возврат Поля;

КонецФункции

// Standart rekvizitlar (Ссылка, Код, Наименование, ПометкаУдаления, ЭтоГруппа, Период …) —
// obyektning HAQIQIY maydonlari, lekin `Реквизиты` ro'yxatida ko'rinmaydi. Ular bo'lmasa
// BinOS tomonidagi tahlil eng asosiy maydonlarni umuman ko'rmay qolardi.
Процедура ДобавитьСтандартныеРеквизиты(Поля, ОбъектМД, Занятые, Ошибки)

	Попытка
		Коллекция = ОбъектМД.СтандартныеРеквизиты;
	Исключение
		// Eski platformada bu kolleksiya bo'lmasligi mumkin — sababi bilan qayd etiladi.
		Ошибки.Добавить("СтандартныеРеквизиты: " + ОписаниеОшибки());
		Возврат;
	КонецПопытки;

	Для Каждого Поле Из Коллекция Цикл
		Попытка
			ДобавитьПолеОдин(Поля, Поле.Имя, Поле.Тип, "standard_attribute",
				ТекстСвойства(Поле, "Синоним", Ошибки), Занятые, Ошибки);
		Исключение
			Ошибки.Добавить("СтандартныеРеквизиты: " + ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;

КонецПроцедуры

// `Константа` va `ОбщийРеквизит` ning O'Z tipi — obyekt darajasidagi ma'lumot, lekin
// `binos-1c-metadata-v1` da obyekt darajasidagi tip maydoni YO'Q. Shu bois u `attributes`
// ichida shu obyekt NOMI bilan BITTA maydon bo'lib yoziladi; shakl `notes` da tushuntirilgan.
// ⚠️ Bu KODLASH QARORI, talqin emas: tip matni o'zgartirilmaydi, faqat joyi shu.
Процедура ДобавитьСобственныйТип(Поля, ОбъектМД, ВидИсточника, Занятые, Ошибки)

	Если ВидИсточника <> "constant" И ВидИсточника <> "common_attribute" Тогда
		Возврат;
	КонецЕсли;

	Попытка
		ДобавитьПолеОдин(Поля, ОбъектМД.Имя, ОбъектМД.Тип, "attribute",
			ТекстСвойства(ОбъектМД, "Синоним", Ошибки), Занятые, Ошибки);
	Исключение
		Ошибки.Добавить("own_type: " + ОписаниеОшибки());
	КонецПопытки;

КонецПроцедуры

Процедура ДобавитьПолеОдин(Поля, ИмяПоля, ТипПоля, ВидПоля, Синоним, Занятые, Ошибки)

	Если Занятые <> Неопределено Тогда
		Если Занятые[ИмяПоля] <> Неопределено Тогда
			Ошибки.Добавить("maydon nomi takrorlandi va TASHLANDI: " + ИмяПоля
				+ " (avval `" + Занятые[ИмяПоля] + "` sifatida yozilgan; "
				+ "obyekt darajasidagi maydonlar bitta manzil maydonini bo'lishadi)");
			Возврат;
		КонецЕсли;
		Занятые.Вставить(ИмяПоля, ВидПоля);
	КонецЕсли;

	Поле = Новый Структура;
	Поле.Вставить("name", ИмяПоля);
	Поле.Вставить("synonym", Синоним);
	Поле.Вставить("kind", ВидПоля);
	Поле.Вставить("type", ОписаниеТипаСтрокой(ТипПоля));
	Поле.Вставить("reference_targets", ЦелиСсылокТипа(ТипПоля, Ошибки));

	Квалификаторы = КвалификаторыПоля(ТипПоля, Ошибки);
	Поле.Вставить("numeric_digits", Квалификаторы.numeric_digits);
	Поле.Вставить("numeric_scale", Квалификаторы.numeric_scale);
	Поле.Вставить("string_length", Квалификаторы.string_length);
	Поля.Добавить(Поле);

КонецПроцедуры

// Havola nishonlari: `Тип.Типы()` dagi har bir tip uchun METADATA obyektini topib, uning
// to'liq nomini yozamiz. Ibtidoiy tiplar (Строка, Число, Дата, Булево) nishon bermaydi.
// ⚠️ TARTIBLANADI: tip to'plamining tartibi ma'no tashimaydi, lekin tartibsiz ro'yxat bir xil
//    bazada ikki xil bayt berishi mumkin edi.
Функция ЦелиСсылокТипа(ОписаниеТипаЗначения, Ошибки)

	Список = Новый СписокЗначений;
	Попытка
		Для Каждого Тип Из ОписаниеТипаЗначения.Типы() Цикл
			ОбъектТипа = Метаданные.НайтиПоТипу(Тип);
			Если ОбъектТипа = Неопределено Тогда
				Продолжить;              // ibtidoiy tip yoki metadata obyekti bo'lmagan tur
			КонецЕсли;
			ПолноеИмя = ОбъектТипа.ПолноеИмя();
			Если Список.НайтиПоЗначению(ПолноеИмя) = Неопределено Тогда
				Список.Добавить(ПолноеИмя);
			КонецЕсли;
		КонецЦикла;
		Список.СортироватьПоЗначению();
	Исключение
		Ошибки.Добавить("reference_targets: " + ОписаниеОшибки());
	КонецПопытки;

	ЦелиСсылок = Новый Массив;
	Для Каждого Элемент Из Список Цикл
		ЦелиСсылок.Добавить(Элемент.Значение);
	КонецЦикла;
	Возврат ЦелиСсылок;

КонецФункции

// Razryadlik va uzunlik — MATN. JSON soni TAQIQLANGAN: `0000123` soni `123` bo'lib qoladi.
// ⚠️ Kvalifikatorlar FAQAT tegishli tip mavjud bo'lganda yoziladi. Platforma satr tipida ham
//    `КвалификаторыЧисла` obyektini qaytarishi mumkin (razryadligi nol), va o'sha nolni
//    yozish «bu maydon 0 razryadli son» degan YOLG'ON dalil bo'lardi.
Функция КвалификаторыПоля(ОписаниеТипаЗначения, Ошибки)

	Результат = Новый Структура("numeric_digits, numeric_scale, string_length",
		Неопределено, Неопределено, Неопределено);

	Попытка
		Если ОписаниеТипаЗначения.СодержитТип(Тип("Число")) Тогда
			Квалификаторы = ОписаниеТипаЗначения.КвалификаторыЧисла;
			Если Квалификаторы <> Неопределено Тогда
				Результат.numeric_digits = Формат(Квалификаторы.Разрядность, "ЧГ=0");
				Результат.numeric_scale = Формат(Квалификаторы.РазрядностьДробнойЧасти, "ЧГ=0");
			КонецЕсли;
		КонецЕсли;
		Если ОписаниеТипаЗначения.СодержитТип(Тип("Строка")) Тогда
			Квалификаторы = ОписаниеТипаЗначения.КвалификаторыСтроки;
			Если Квалификаторы <> Неопределено Тогда
				Результат.string_length = Формат(Квалификаторы.Длина, "ЧГ=0");
			КонецЕсли;
		КонецЕсли;
	Исключение
		Ошибки.Добавить("qualifiers: " + ОписаниеОшибки());
	КонецПопытки;

	Возврат Результат;

КонецФункции

// ── JADVAL BO'LIMLARI ─────────────────────────────────────────────────────────────────────
// ⚠️ Bo'lim maydoni nomi TOZA nom bo'ladi ("F1"), `TC.F1` shaklida EMAS: nomda nuqta bo'lsa
//    grafdagi manzil (`<obyekt>.<bo'lim>.<maydon>`) ikki xil o'qilib qolardi.
Функция ТабличныеЧастиОбъекта(ОбъектМД, Ошибки)

	Разделы = Новый Массив;
	Попытка
		Коллекция = ОбъектМД.ТабличныеЧасти;
	Исключение
		Возврат Разделы;
	КонецПопытки;

	Для Каждого ТабличнаяЧасть Из Коллекция Цикл
		Попытка
			Раздел = Новый Структура;
			Раздел.Вставить("name", ТабличнаяЧасть.Имя);
			Раздел.Вставить("synonym", ТекстСвойства(ТабличнаяЧасть, "Синоним", Ошибки));
			// Har bo'limning O'Z nom maydoni bor: bo'lim ichidagi takror alohida tekshiriladi.
			ЗанятыеВРазделе = Новый Соответствие;
			Раздел.Вставить("attributes", ПоляКоллекции(ТабличнаяЧасть, "Реквизиты",
				"attribute", ЗанятыеВРазделе, Ошибки));
			Разделы.Добавить(Раздел);
		Исключение
			Ошибки.Добавить("ТЧ: " + ОписаниеОшибки());
		КонецПопытки;
	КонецЦикла;
	Возврат Разделы;

КонецФункции

// ── NOMLAR RO'YXATI (sanab o'tilgan qiymatlar, oldindan belgilangan elementlar) ────────────
// ⚠️ FAQAT `Имя` olinadi. `Наименование` va `Код` OLINMAYDI: ular mijoz ekranda ko'radigan
//    matn, ya'ni biznes ma'lumotiga yaqin. `Имя` esa konfiguratsiya identifikatori — metadata.
// ⚠️ Takror nom TASHLANADI (validator takrorni RAD etadi), lekin JIMGINA emas: sababi
//    obyektning `errors` ro'yxatiga yoziladi.
// ⚠️ TARTIB O'ZGARTIRILMAYDI: sanab o'tilgan qiymatlarning tartibi metadata MA'LUMOTI
//    (platforma indeksi shu tartibda), shuning uchun bu ro'yxat tartiblanmaydi.
Функция ИменаКоллекцииОбъекта(ОбъектМД, ИмяКоллекции, Ошибки)

	Имена = Новый Массив;
	Виденные = Новый Соответствие;
	Попытка
		Коллекция = ОбъектМД[ИмяКоллекции];
	Исключение
		Возврат Имена;      // bu obyekt turida bunday kolleksiya yo'q — shakl farqi
	КонецПопытки;

	Если Коллекция = Неопределено Тогда
		Возврат Имена;
	КонецЕсли;

	Попытка
		Для Каждого Элемент Из Коллекция Цикл
			Имя = Строка(Элемент.Имя);
			Если ПустаяСтрока(Имя) Тогда
				Ошибки.Добавить(ИмяКоллекции + ": bo'sh nom tashlandi");
				Продолжить;
			КонецЕсли;
			Если Виденные[Имя] <> Неопределено Тогда
				Ошибки.Добавить(ИмяКоллекции + ": nom takrorlandi va tashlandi: " + Имя);
				Продолжить;
			КонецЕсли;
			Виденные.Вставить(Имя, Истина);
			Имена.Добавить(Имя);
		КонецЦикла;
	Исключение
		Ошибки.Добавить(ИмяКоллекции + ": " + ОписаниеОшибки());
	КонецПопытки;

	Возврат Имена;

КонецФункции

// ── ZONDLAR (FAQAT O'QISH) ────────────────────────────────────────────────────────────────
// NISHON SHARTNOMASI (Python tomonidagi `probe.py` bilan AYNI):
//   · `field_type_details` nishoni — MAYDON MANZILI: `<Префикс>.<Имя>.<maydon>` yoki
//     `<Префикс>.<Имя>.<bo'lim>.<maydon>`;
//   · QOLGAN hamma zond turining nishoni — OBYEKT: `<Префикс>.<Имя>`.
// Bu funksiya nishonni OBYEKT nomi va MAYDON YO'LIga ajratadi; yo'lni FAQAT
// `field_type_details` ishlatishi mumkin — buni `ВыполнитьЗонд` tekshiradi.
// ⚠️ Kelgan matn SO'ROVGA TUSHMAYDI: undan faqat metadata obyekti IZLANADI, so'rovda esa
//    topilgan obyektning O'Z `ПолноеИмя()` si ishlatiladi.
Функция НайтиЦелевойОбъект(ЦелевойОбъект, ПутьПоля, Ошибки)

	ПутьПоля = "";
	Если Не ЗначениеЗаполнено(ЦелевойОбъект) Тогда
		Ошибки.Добавить("target_object bo'sh — zond nishonsiz bajarilmaydi");
		Возврат Неопределено;
	КонецЕсли;

	// ⚠️ `СтрРазделить` 8.3.6 dan bor. Eski platformada bu satr yiqiladi va zond bajarilmaydi —
	//    bu MAQBUL: fail-closed, chunki nishonni noto'g'ri ajratgandan ko'ra bajarmaslik xavfsiz.
	Части = СтрРазделить(Строка(ЦелевойОбъект), ".", Ложь);
	Если Части.Количество() < 2 Тогда
		Ошибки.Добавить("target_object `<Kolleksiya>.<Nom>` ko'rinishida bo'lishi kerak: "
			+ Строка(ЦелевойОбъект));
		Возврат Неопределено;
	КонецЕсли;

	ИмяОбъекта = Части[0] + "." + Части[1];
	Для Сч = 2 По Части.Количество() - 1 Цикл
		Если ПустаяСтрока(ПутьПоля) Тогда
			ПутьПоля = Части[Сч];
		Иначе
			ПутьПоля = ПутьПоля + "." + Части[Сч];
		КонецЕсли;
	КонецЦикла;

	Попытка
		ОбъектМД = Метаданные.НайтиПоПолномуИмени(ИмяОбъекта);
	Исключение
		Ошибки.Добавить("target_object izlanmadi: " + ОписаниеОшибки());
		Возврат Неопределено;
	КонецПопытки;

	Если ОбъектМД = Неопределено Тогда
		// ⚠️ Nom O'YLAB CHIQARILGAN bo'lishi mumkin — fail-closed: hech narsa bajarilmaydi.
		Ошибки.Добавить("target_object metadatada topilmadi: " + ИмяОбъекта);
	КонецЕсли;
	Возврат ОбъектМД;

КонецФункции

Функция ПолноеИмяБезопасно(ОбъектМД, Ошибки)

	Попытка
		Возврат ОбъектМД.ПолноеИмя();
	Исключение
		Ошибки.Добавить("full_name: " + ОписаниеОшибки());
		Возврат "";
	КонецПопытки;

КонецФункции

Функция ЗондПоляОбъекта(ОбъектМД, Ошибки)

	Занятые = Новый Соответствие;
	Поля = ПоляКоллекции(ОбъектМД, "Реквизиты", "attribute", Занятые, Ошибки);
	ДобавитьСтандартныеРеквизиты(Поля, ОбъектМД, Занятые, Ошибки);
	Для Каждого Поле Из ПоляКоллекции(ОбъектМД, "Измерения", "dimension", Занятые, Ошибки) Цикл
		Поля.Добавить(Поле);
	КонецЦикла;
	Для Каждого Поле Из ПоляКоллекции(ОбъектМД, "Ресурсы", "resource", Занятые, Ошибки) Цикл
		Поля.Добавить(Поле);
	КонецЦикла;
	Возврат Поля;

КонецФункции

// Obyekt KIMGA havola qiladi: maydon manzili -> havola nishonlari.
Функция АдресаПолейОбъекта(ОбъектМД, ПолноеИмяОбъекта, Ошибки)

	Адреса = Новый Массив;
	Для Каждого Поле Из ЗондПоляОбъекта(ОбъектМД, Ошибки) Цикл
		Если Поле.reference_targets.Количество() = 0 Тогда
			Продолжить;
		КонецЕсли;
		Запись = Новый Структура;
		Запись.Вставить("address", ПолноеИмяОбъекта + "." + Поле.name);
		Запись.Вставить("targets", Поле.reference_targets);
		Адреса.Добавить(Запись);
	КонецЦикла;

	Для Каждого Раздел Из ТабличныеЧастиОбъекта(ОбъектМД, Ошибки) Цикл
		Для Каждого Поле Из Раздел.attributes Цикл
			Если Поле.reference_targets.Количество() = 0 Тогда
				Продолжить;
			КонецЕсли;
			Запись = Новый Структура;
			Запись.Вставить("address",
				ПолноеИмяОбъекта + "." + Раздел.name + "." + Поле.name);
			Запись.Вставить("targets", Поле.reference_targets);
			Адреса.Добавить(Запись);
		КонецЦикла;
	КонецЦикла;
	Возврат Адреса;

КонецФункции

// KIM shu obyektga havola qiladi. Butun konfiguratsiya kezib chiqiladi — bu qimmat, lekin
// «kim havola qiladi» savoliga boshqa yo'l bilan javob berib bo'lmaydi.
Функция ЗондСсылающиеся(ПолноеИмяЦели, Ошибки)

	Найденные = Новый Массив;
	Для Каждого Описание Из ОписанияКоллекций() Цикл
		Причина = "";
		Коллекция = КоллекцияМетаданных(Описание.collection, Причина);
		Если Коллекция = Неопределено Тогда
			Ошибки.Добавить(Описание.collection + ": " + Причина);
			Продолжить;
		КонецЕсли;

		Для Каждого ОбъектМД Из Коллекция Цикл
			ПолноеИмя = Описание.prefix + "." + ОбъектМД.Имя;
			Для Каждого Запись Из АдресаПолейОбъекта(ОбъектМД, ПолноеИмя, Ошибки) Цикл
				Для Каждого ЦельСсылки Из Запись.targets Цикл
					Если ЦельСсылки = ПолноеИмяЦели Тогда
						Найденные.Добавить(Запись.address);
						Прервать;
					КонецЕсли;
				КонецЦикла;
			КонецЦикла;
		КонецЦикла;
	КонецЦикла;
	Возврат Найденные;

КонецФункции

Функция ЗондФормаРегистра(ОбъектМД, Ошибки)

	Форма = Новый Структура;
	Занятые = Новый Соответствие;
	Форма.Вставить("dimensions", ПоляКоллекции(ОбъектМД, "Измерения", "dimension",
		Занятые, Ошибки));
	Форма.Вставить("resources", ПоляКоллекции(ОбъектМД, "Ресурсы", "resource",
		Занятые, Ошибки));
	Форма.Вставить("attributes", ПоляКоллекции(ОбъектМД, "Реквизиты", "attribute",
		Занятые, Ошибки));
	// ⚠️ Zond obyekt TURINI bilmaydi, shuning uchun ikkala xossa ham urinib ko'riladi va
	//    tegishli bo'lmagani `null` bo'lib qoladi.
	Форма.Вставить("register_kind", ВидРегистраТекстом(ОбъектМД, "accumulation_register",
		Ошибки));
	Форма.Вставить("periodicity", ПериодичностьТекстом(ОбъектМД, "information_register",
		Ошибки));
	Возврат Форма;

КонецФункции

// ⚠️ Faqat SANOQ qaytadi, MATN sifatida. Qatorlarning O'ZI qaytmaydi.
// ⚠️ NOMI O'ZGARTIRILDI (TOPILGAN NUQSON). Bu funksiya ilgari `ЗондСанокҚаторлар` deb atalgan
//    edi: nomdagi `Қ` — U+049A (CYRILLIC CAPITAL LETTER KA WITH DESCENDER), ya'ni
//    QOZOQ/O'ZBEK kirill harfi. Rus alifbosida bunday harf YO'Q va 1C identifikatori rus
//    kirilli, lotin, raqam va pastki chiziqdan iborat — demak `row_count` zondi (11 zonddan
//    biri) kompilyatsiyani yiqitishi KUCHLI EHTIMOL edi. Endi audit qoidasi
//    (`NONSTANDARD_IDENT_CHAR`) buni qaytib kirishiga yo'l qo'ymaydi.
Функция ЗондКоличествоСтрок(ПолноеИмяОбъекта, Ошибки)

	Если ПустаяСтрока(ПолноеИмяОбъекта) Тогда
		Ошибки.Добавить("row_count: obyektning to'liq nomi olinmadi");
		Возврат Неопределено;
	КонецЕсли;

	Попытка
		Запрос = Новый Запрос;
		// ⚠️ Jadval nomi METADATA obyektidan (`ПолноеИмя()`) keldi, kelgan matndan EMAS.
		Запрос.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Кол ИЗ " + ПолноеИмяОбъекта;
		Выборка = Запрос.Выполнить().Выбрать();
		Если Выборка.Следующий() Тогда
			Возврат Формат(Выборка.Кол, "ЧГ=0");
		КонецЕсли;
		Возврат "0";
	Исключение
		Ошибки.Добавить("row_count: " + ОписаниеОшибки());
		Возврат Неопределено;
	КонецПопытки;

КонецФункции

// Bitta maydonning tip tafsilotlari. Manzil `<obyekt>.<maydon>` yoki
// `<obyekt>.<bo'lim>.<maydon>` bo'lishi mumkin.
Функция ЗондДеталиТипаПоля(ОбъектМД, ПутьПоля, Ошибки)

	Если ПустаяСтрока(ПутьПоля) Тогда
		Ошибки.Добавить("field_type_details: maydon yo'li ko'rsatilmagan — "
			+ "target_object `<Kolleksiya>.<Nom>.<maydon>` bo'lishi kerak");
		Возврат Неопределено;
	КонецЕсли;

	Части = СтрРазделить(ПутьПоля, ".", Ложь);
	// ⚠️ Shartnomada maydon yo'li BIR yoki IKKI bo'lakdan iborat (`<maydon>` yoki
	//    `<bo'lim>.<maydon>`). Chuqurroq yo'lni «yaqin ma'noda» tushunish JIMGINA BOSHQA
	//    maydonni o'lchash bo'lardi: ilgari o'rtadagi bo'laklar tashlanib ketardi.
	Если Части.Количество() > 2 Тогда
		Ошибки.Добавить("field_type_details: maydon yo'li juda chuqur, shartnomada "
			+ "`<maydon>` yoki `<bo'lim>.<maydon>` kutiladi: " + ПутьПоля);
		Возврат Неопределено;
	КонецЕсли;

	ИмяРаздела = "";
	ИмяПоля = Части[Части.Количество() - 1];
	Если Части.Количество() > 1 Тогда
		ИмяРаздела = Части[0];
	КонецЕсли;

	Владелец = ОбъектМД;
	Если Не ПустаяСтрока(ИмяРаздела) Тогда
		Попытка
			Владелец = ОбъектМД.ТабличныеЧасти.Найти(ИмяРаздела);
		Исключение
			Ошибки.Добавить("field_type_details: " + ОписаниеОшибки());
			Возврат Неопределено;
		КонецПопытки;
		Если Владелец = Неопределено Тогда
			Ошибки.Добавить("field_type_details: jadval bo'limi topilmadi: " + ИмяРаздела);
			Возврат Неопределено;
		КонецЕсли;
	КонецЕсли;

	Для Каждого ИмяКоллекции Из КоллекцииПолей() Цикл
		Поле = ПолеПоИмени(Владелец, ИмяКоллекции, ИмяПоля);
		Если Поле = Неопределено Тогда
			Продолжить;
		КонецЕсли;
		Найденные = Новый Массив;
		ДобавитьПолеОдин(Найденные, Поле.Имя, Поле.Тип, ВидПоляПоКоллекции(ИмяКоллекции),
			ТекстСвойства(Поле, "Синоним", Ошибки), Неопределено, Ошибки);
		Возврат Найденные[0];
	КонецЦикла;

	Ошибки.Добавить("field_type_details: maydon topilmadi: " + ПутьПоля);
	Возврат Неопределено;

КонецФункции

Функция КоллекцииПолей()

	Список = Новый Массив;
	Список.Добавить("Реквизиты");
	Список.Добавить("Измерения");
	Список.Добавить("Ресурсы");
	Список.Добавить("СтандартныеРеквизиты");
	Возврат Список;

КонецФункции

Функция ВидПоляПоКоллекции(ИмяКоллекции)

	Если ИмяКоллекции = "Измерения" Тогда
		Возврат "dimension";
	ИначеЕсли ИмяКоллекции = "Ресурсы" Тогда
		Возврат "resource";
	ИначеЕсли ИмяКоллекции = "СтандартныеРеквизиты" Тогда
		Возврат "standard_attribute";
	КонецЕсли;
	Возврат "attribute";

КонецФункции

Функция ПолеПоИмени(Владелец, ИмяКоллекции, ИмяПоля)

	Попытка
		Коллекция = Владелец[ИмяКоллекции];
	Исключение
		Возврат Неопределено;
	КонецПопытки;

	Для Каждого Поле Из Коллекция Цикл
		Если Поле.Имя = ИмяПоля Тогда
			Возврат Поле;
		КонецЕсли;
	КонецЦикла;
	Возврат Неопределено;

КонецФункции

// Umumiy rekvizitlar: obyektning o'z ro'yxatida ko'rinmaydi, lekin uning maydoni bo'lib
// ishlaydi. `ЦелевойОбъект` berilgan bo'lsa — faqat shu obyektga ULANGANLARI.
Функция ЗондОбщиеРеквизиты(ПолноеИмяЦели, Ошибки)

	Найденные = Новый Массив;
	Причина = "";
	Коллекция = КоллекцияМетаданных("ОбщиеРеквизиты", Причина);
	Если Коллекция = Неопределено Тогда
		Ошибки.Добавить("ОбщиеРеквизиты: " + Причина);
		Возврат Найденные;
	КонецЕсли;

	Для Каждого ОбъектМД Из Коллекция Цикл
		Попытка
			// ⚠️ SINALMAGAN JOY: `Состав.Найти` metadata obyektini qabul qilishi platforma
			//    versiyasiga bog'liq. Yiqilsa — `used_by_target` "unknown" bo'ladi va sabab
			//    `errors` ga tushadi; JIMGINA "false" YOZILMAYDI («bilmayman» ≠ «yo'q»).
			Включен = "unknown";
			Состав = ОбъектМД.Состав.Найти(Метаданные.НайтиПоПолномуИмени(ПолноеИмяЦели));
			Если Состав <> Неопределено Тогда
				Включен = ?(Состав.Использование
					= Метаданные.СвойстваОбъектов.ИспользованиеОбщегоРеквизита.Использовать,
					"true", "false");
			Иначе
				Включен = "false";
			КонецЕсли;
		Исключение
			Ошибки.Добавить("ОбщийРеквизит." + ОбъектМД.Имя + ": " + ОписаниеОшибки());
			Включен = "unknown";
		КонецПопытки;

		Запись = Новый Структура;
		Запись.Вставить("name", ОбъектМД.Имя);
		Запись.Вставить("synonym", ТекстСвойства(ОбъектМД, "Синоним", Ошибки));
		Запись.Вставить("type", ОписаниеТипаСтрокой(ОбъектМД.Тип));
		Запись.Вставить("used_by_target", Включен);   // MATN: "true"/"false"/"unknown"
		Найденные.Добавить(Запись);
	КонецЦикла;
	Возврат Найденные;

КонецФункции

// Xarakteristika turlari rejalari — kengaytirilgan konfiguratsiyada qo'shimcha maydonlar
// shu yerdan keladi va oddiy rekvizit ro'yxatida ko'rinmaydi.
Функция ЗондПланыВидовХарактеристик(Ошибки)

	Найденные = Новый Массив;
	Причина = "";
	Коллекция = КоллекцияМетаданных("ПланыВидовХарактеристик", Причина);
	Если Коллекция = Неопределено Тогда
		Ошибки.Добавить("ПланыВидовХарактеристик: " + Причина);
		Возврат Найденные;
	КонецЕсли;

	Для Каждого ОбъектМД Из Коллекция Цикл
		Найденные.Добавить(ОписатьОбъект(ОбъектМД, "ПланВидовХарактеристик",
			"chart_of_characteristic_types"));
	КонецЦикла;
	Возврат Найденные;

КонецФункции

// ── IZOHLAR ───────────────────────────────────────────────────────────────────────────────
Функция ЗаметкиЭкспорта()

	Заметки = Новый Массив;
	Заметки.Добавить("Metadata-only: qiymatlar o'qilmadi, faqat metadata va КОЛИЧЕСТВО(*).");
	Заметки.Добавить("`candidates` ATAYLAB BO'SH. Nomzod aniqlash deterministik ekstraksiyadan "
		+ "KEYIN, BinOS tomonidagi analitik qatlamda bajariladi: ilgari bu yerda kutilgan "
		+ "katalog va registr nomlari QATTIQ YOZILGAN edi, ya'ni yig'uvchi bitta "
		+ "konfiguratsiya oilasiga moslangan edi.");
	Заметки.Добавить("⚠️ Bu yig'uvchining QOBILIYATINI KAMAYTIRADI: `export.json` o'zi bilan "
		+ "birorta nishonni ko'rsatmaydi, adapter hamma nishonni UNKNOWN darajasi bilan "
		+ "yozadi. Yashirilmaydi: dalil `metadata.json` da, qaror BinOS tomonida.");
	Заметки.Добавить("Ikkinchi hujjat: `metadata.json` (`binos-1c-metadata-v1`) — "
		+ "konfiguratsiyada UMUMAN nima borligi. Bu ikki fayl birga yuboriladi.");
	Возврат Заметки;

КонецФункции

Функция ЗаметкиИнвентаризации()

	Заметки = Новый Массив;
	Заметки.Добавить("FAQAT metadata: birorta biznes qatori, narx, mijoz yoki barkod QIYMATI "
		+ "chiqmaydi. Bu hujjatda TALQIN ham yo'q — nishon, ishonch darajasi va xarita "
		+ "boshqa qadamning ishi.");
	Заметки.Добавить("`row_count` ATAYLAB bo'sh: inventarizatsiya so'rov yubormaydi. Sanoqlar "
		+ "`export.json` ning `counts` bo'limida va `row_count` zondida.");
	Заметки.Добавить("`Константа` va `ОбщийРеквизит` ning O'Z tipi `attributes` ichida shu "
		+ "obyekt nomi bilan BITTA maydon bo'lib yoziladi: shakl lug'atida obyekt "
		+ "darajasidagi tip maydoni yo'q.");
	Заметки.Добавить("⚠️ `ОбщийРеквизит` ning Состав (qaysi obyektlarga ulangani) bu shaklda "
		+ "YO'Q — u `common_attributes` zondi bilan olinadi. Bu QOBILIYAT CHEGARASI.");
	Заметки.Добавить("`predefined` va `enum_values` da FAQAT `Имя` bor; `Наименование` va `Код` "
		+ "OLINMAYDI, chunki ular mijoz ekranda ko'radigan matn.");
	Заметки.Добавить("`enum_values` platforma bergan TARTIBDA yoziladi (tartib metadata "
		+ "ma'lumoti), `reference_targets` esa tartiblanadi (tip to'plamining tartibi ma'no "
		+ "tashimaydi).");
	Заметки.Добавить("`register_kind` faqat РегистрНакопления uchun to'ldiriladi; boshqa "
		+ "turlarda `null` — «bu obyektda qoldiq/aylanma tushunchasi YO'Q», «qaralmadi» EMAS.");
	Заметки.Добавить("Bo'lim jurnalidagi `skipped` — «qaralmadi/olinmadi», `failed` — "
		+ "«urinildi va yiqildi». Ikkisi ham sababi bilan qoladi: qaralmagan narsa "
		+ "TASHLANMAYDI.");
	Возврат Заметки;

КонецФункции

Функция ЗаметкиЗапуска()

	Заметки = Новый Массив;
	Заметки.Добавить("DEFAULT REJIM: METADATA_ONLY. Aktiv zond FAQAT `APPROVED_PROBES` "
		+ "rejimida va FAQAT operator bergan `(tur, nishon, sabab)` allowlisti bo'yicha "
		+ "bajariladi. Rejim berilmasa yoki noma'lum bo'lsa — fail-safe METADATA_ONLY; "
		+ "allowlist bo'sh bo'lsa — fail-closed, birorta zond bajarilmaydi.");
	Заметки.Добавить("⚠️ `status.json` va `summary.md` — BinOS tomonidagi TO'PLAMNING "
		+ "(`binos-1c-discovery-v1`) a'zolari va ularni ADAPTER quradi. Shu bois bu paket "
		+ "`run_status.json` va `run_summary.md` nomlarini oladi: bir xil nom ikki xil sxema "
		+ "operator uchun ham, kod uchun ham tuzoq bo'lardi.");
	Заметки.Добавить("⚠️ `manifest.json` PROVENANS DA'VOSI EMAS — u faqat YOZILGAN "
		+ "BAYTLARNING sha256'si. `source_copy`, `snapshot_at`, `plan_sha256` kabi maydonlar "
		+ "ATAYLAB yo'q: yig'uvchi nusxada ishlayotganini yoki snapshot qachon olinganini "
		+ "BILA OLMAYDI.");
	Заметки.Добавить("⚠️ `absent` va `unreadable` IKKI XIL holat va ikkisi ham `families` da "
		+ "yashaydi, `sections` da EMAS: `absent` = o'qildi va yo'q (TO'LIQ javob), "
		+ "`unreadable` = o'qiy olmadim. Ikkinchisi `errors.json` da ham bo'ladi va tegishli "
		+ "bo'limni `failed` qiladi; birinchisi XATO emas va umumiy holatni BUZMAYDI.");
	Заметки.Добавить("⚠️ `overall` YAGONA TA'RIF: `SUCCESS` ⇔ hamma majburiy artefakt "
		+ "yozilgan VA birorta bo'lim `failed` emas VA birorta oila `unreadable` emas. "
		+ "Yozish yiqilsa `FAILED`, qolgan hamma holda `PARTIAL`. `skipped` bo'lim SUCCESS ni "
		+ "BUZMAYDI: `METADATA_ONLY` da `probes` bo'limi HAR DOIM `skipped`.");
	Заметки.Добавить("⚠️ `sections` UCH jurnalning BIRLASHMASI: runtime bo'limlari prefikssiz, "
		+ "`export.json` va `metadata.json` jurnallari esa `export:` va `metadata:` prefiksi "
		+ "bilan. Sabab ikkita: bo'lim nomi TAKRORLANMASLIGI kerak, va `platform` bo'limining "
		+ "yiqilishi FAQAT eksport jurnalida qayd etiladi — u tashlansa umumiy holat ikki "
		+ "tomonda boshqacha hisoblanardi.");
	Заметки.Добавить("⚠️ `artifacts` da `run_status.json` va `manifest.json` ATAYLAB bor, "
		+ "lekin ular shu fayl yozilgandan KEYIN yoziladi: fayl O'ZI yozilmaganini O'ZIDA "
		+ "aytib bo'lmaydi. HAQIQIY tekshiruv `manifest.json` da — u ENG OXIRGI fayl va "
		+ "o'zidan oldingi hamma faylni nomi, bayti va xeshi bilan sanaydi. `manifest.json` "
		+ "yo'q bo'lsa paket TUGALLANMAGAN, bu yig'uvchining da'vosidan emas, PAPKADAN ko'rinadi.");
	// ⚠️ BSL da teskari chiziq EKRANLASH BELGISI EMAS: satr literalidagi qo'shtirnoq faqat
	//    IKKILANTIRISH bilan yoziladi. Shu bois quyidagi matnda JSON maydon nomi qo'shtirnoq
	//    ichida emas, teskari apostrof ichida beriladi — ilgari bu yerda ekranlashga urinish
	//    bor edi va u literalni AYNAN shu joyda yopib, qolgan qismini KOD qilib qo'yardi.
	Заметки.Добавить("⚠️ `errors.json` `manifest.json` dan OLDIN yoziladi, shu bois manifest "
		+ "bosqichidagi xato (`UNHASHABLE`) u faylga TUSHMAYDI — u manifestda `sha256` "
		+ "maydoni `null` bo'lib ko'rinadi. `error_count` shu bois `errors.json` dagi "
		+ "sanoqdan KO'P bo'lishi mumkin.");
	Заметки.Добавить("⚠️ SO'ROV `metadata.py` GA (BinOS tomoni): §11 ning kengaytirilgan "
		+ "platforma maydonlari — `client_kind`, `client_application_name`, `locale`, "
		+ "`db_type`, `application_mode`, `os_version` — HOZIR `run_status.json` da. Ularni "
		+ "`metadata.json` ga ko'chirish uchun `binos-1c-metadata-v1` ga `platform` bo'limi "
		+ "kerak: `METADATA_KEYS` oq ro'yxati yangi kalitni RAD etadi. `export.json` ga "
		+ "qo'shish MUMKIN EMAS — `binos-1c-export-v1` ning `platform` kalitlari qulflangan.");
	Заметки.Добавить("⚠️ `probes` ostki papkasini OPERATOR oldin yaratadi: yig'uvchi katalog "
		+ "yaratmaydi (`СоздатьКаталог` statik audit bilan taqiqlangan). Papka bo'lmasa zond "
		+ "fayllari yozilmaydi va umumiy holat SUCCESS bo'lmaydi.");
	Заметки.Добавить("⚠️ RUNTIME'DA SINALMAGAN: `ХешированиеДанных`, "
		+ "`ИмяКлиентскогоПриложения`, `КодЛокализацииИнформационнойБазы`, "
		+ "`КонфигурацияИзменена`, `Метаданные.ОсновнойРежимЗапуска` va markdown yozish yo'li "
		+ "birorta 1C bazasida ishlatilmagan. Har biri O'Z `Попытка` si ichida: yo'q bo'lsa "
		+ "maydon bo'sh qoladi, sabab qayd etiladi, yurish davom etadi.");
	Возврат Заметки;

КонецФункции

Функция ЗаметкиОшибок()

	Заметки = Новый Массив;
	Заметки.Добавить("`code` lug'ati (BARQAROR KOD, katta harf): UNREADABLE | OBJECT_FAILED | "
		+ "WRITE_FAILED | PROBE_FAILED | REJECTED | UNHASHABLE. Odam o'qiydigan matn "
		+ "`detail` da: kod MASHINA uchun, matn ODAM uchun va ikkisi aralashtirilmaydi.");
	Заметки.Добавить("`scope` lug'ati: platform | family | object | probe | write | mode — "
		+ "xato YURISHNING QAYSI qatlamida chiqqani. `family` bitta oilaga tegishli bo'lsa "
		+ "`family` maydoni to'ldiriladi; bir nechta oila bitta matnga birlashgan bo'lsa "
		+ "(`metadata_sweep`, `counts`) u `null` va nomlar `detail` ichida qoladi.");
	Заметки.Добавить("⚠️ `absent` bu faylda BO'LMAYDI: «o'qildi va yo'q» XATO emas, u "
		+ "`run_status.json` ning `families` ro'yxatida turadi. `unreadable` esa XATO va u "
		+ "shu yerda — bundan tashqari u tegishli BO'LIMNI ham `failed` qiladi.");
	Заметки.Добавить("Bo'sh `errors` — hech qanday xato chiqmagani. Fayl BARIBIR yoziladi: "
		+ "faylning yo'qligi «xato bo'lmadi» degani emas, «yig'uvchi tugamadi» degani.");
	Возврат Заметки;

КонецФункции

Функция ЗаметкиМанифеста()

	Заметки = Новый Массив;
	Заметки.Добавить("Bu manifest FAQAT yozilgan baytlarni tavsiflaydi: fayl nomi, bayt "
		+ "hajmi, sha256. Boshqa hech narsa.");
	Заметки.Добавить("⚠️ PROVENANS DA'VOSI YO'Q: manba nusxasi, snapshot vaqti yoki reja "
		+ "xeshi kabi maydonlar ATAYLAB qo'shilmagan — ular metadata razvedkasidan kelib "
		+ "chiqmaydi va yig'uvchi ularni bila olmaydi.");
	Заметки.Добавить("⚠️ `sha256` `null` bo'lsa — xesh HISOBLANMADI (masalan platformada "
		+ "`ХешированиеДанных` yo'q). Sabab `errors.json` dagi `UNHASHABLE` kodli xatoda. "
		+ "YOLG'ON xesh yozilmaydi.");
	Заметки.Добавить("⚠️ `manifest.json` O'ZI ro'yxatda YO'Q: u o'zini xeshlay olmaydi.");
	Возврат Заметки;

КонецФункции

// ── RUNTIME ARTEFAKTLARI (§7) ─────────────────────────────────────────────────────────────
// `run_status.json`.`sections` — UCHALA jurnalning BITTA ro'yxati.
// ⚠️ NEGA BIRLASHTIRILADI. Shakl `sections` ni talab qiladi va `export_sections` /
//    `metadata_sections` kabi qo'shimcha kalitlar RAD etiladi (yuqori darajadagi kalitlar
//    QAT'IY oq ro'yxatda). Lekin ikki jurnalni shunchaki TASHLAB YUBORISH ham mumkin emas:
//    `platform` bo'limining yiqilishi FAQAT eksport jurnalida qayd etiladi, ya'ni u
//    tashlansa yig'uvchi `SUCCESS`, BinOS tomoni `PARTIAL` deb hisoblab paketni rad etardi.
// ⚠️ NEGA PREFIKS. `sections` da bo'lim nomi TAKRORLANMASLIGI SHART (validator takroriy nomni
//    rad etadi), `write_metadata` esa ikki jurnalda ham bor. Prefiks nomlarni ajratadi va shu
//    bilan HAR BIR yozuvning QAYSI hujjatga tegishli ekani ham ko'rinib turadi.
// ⚠️ RUNTIME jurnalining bo'limlari PREFIKSSIZ qoladi: BinOS tomonidagi oila->bo'lim
//    bog'lanishi aynan shu nomlarga (`catalogs`, `chart_of_accounts`, ...) suyanadi.
Функция СобратьРазделыЗапуска()

	Разделы = Новый Массив;
	Для Каждого Раздел Из ЖурналЗапуска Цикл
		Разделы.Добавить(Раздел);
	КонецЦикла;
	Для Каждого Раздел Из ЖурналРазделов Цикл
		Разделы.Добавить(НовыйРаздел("export:" + Раздел.name, Раздел.status, Раздел.error));
	КонецЦикла;
	Для Каждого Раздел Из ЖурналМетаданных Цикл
		Разделы.Добавить(НовыйРаздел("metadata:" + Раздел.name, Раздел.status, Раздел.error));
	КонецЦикла;
	Возврат Разделы;

КонецФункции

Функция СобратьСостояниеЗапуска(Платформа, ОбязательныеЗаписаны)

	// ⚠️ SHU IKKI ARTEFAKT `artifacts` GA ATAYLAB E'LON QILINADI va sabab `ВыполнитьРазведку`
	//    izohida ochiq yozilgan: `run_status.json` O'ZI yozilmaganini O'ZIDA aytib bo'lmaydi
	//    (fayl bo'lmasa o'qiladigan da'vo ham yo'q), `manifest.json` esa undan KEYIN yoziladi.
	//    HAQIQIY tekshiruv — `manifest.json`: u eng oxirgi fayl va o'zidan oldingi hamma
	//    faylni nomi, bayti va xeshi bilan sanaydi.
	ОтметитьАртефакт("run_status.json");
	ОтметитьАртефакт("manifest.json");

	Документ = Новый Структура;
	Документ.Вставить("run_version", "binos-1c-run-v1");
	Документ.Вставить("collector", ОписаниеСборщика());
	Документ.Вставить("mode", ТекущийРежим());
	// ⚠️ `mode_note` — rejim QANDAY tanlangani. Fail-safe qarori JIMGINA qabul qilinmaydi:
	//    «argument berilmadi» yoki «noma'lum rejim keldi» shu yerda OCHIQ yoziladi. Bu izoh
	//    FAQAT shu maydonda yashaydi: `ok` bo'limda `error` bo'lishi taqiqlangan.
	Документ.Вставить("mode_note", ЗаметкаРежима);
	Документ.Вставить("started_at", ВСтрокуISO(ВремяНачала));
	Документ.Вставить("finished_at", ВСтрокуISO(ТекущаяДата()));
	Документ.Вставить("overall", ОбщееСостояние(ОбязательныеЗаписаны));
	Документ.Вставить("platform", Платформа);
	Документ.Вставить("sections", СобратьРазделыЗапуска());
	Документ.Вставить("families", ЖурналСемейств);
	Документ.Вставить("probes", ЖурналЗондов);
	Документ.Вставить("artifacts", ЖурналАртефактов);
	Документ.Вставить("error_count", Формат(ЖурналОшибок.Количество(), "ЧГ=0"));
	Документ.Вставить("notes", ЗаметкиЗапуска());
	Возврат Документ;

КонецФункции

Функция СобратьОшибки()

	Документ = Новый Структура;
	Документ.Вставить("errors_version", "binos-1c-errors-v1");
	Документ.Вставить("collected_at", ВСтрокуISO(ТекущаяДата()));
	Документ.Вставить("errors", ЖурналОшибок);
	Документ.Вставить("notes", ЗаметкиОшибок());
	Возврат Документ;

КонецФункции

Функция СобратьМанифест()

	Документ = Новый Структура;
	Документ.Вставить("manifest_version", "binos-1c-manifest-v1");
	Документ.Вставить("files", ЖурналФайлов);
	Документ.Вставить("notes", ЗаметкиМанифеста());
	Возврат Документ;

КонецФункции

// Operator uchun markdown xulosa. ⚠️ Bu MATN, shartnoma EMAS: uni kod o'qimaydi.
Функция СводкаТекстом(ПредварительноеСостояние)

	Сводка = "# BinOS Discovery — yurish xulosasi" + Символы.ПС + Символы.ПС;
	Сводка = Сводка + "- Rejim: **" + ТекущийРежим() + "**" + Символы.ПС;
	Сводка = Сводка + "- Rejim izohi: " + Строка(ЗаметкаРежима) + Символы.ПС;
	Сводка = Сводка + "- Boshlandi: " + ВСтрокуISO(ВремяНачала) + Символы.ПС;
	Сводка = Сводка + "- Tugadi: " + ВСтрокуISO(ТекущаяДата()) + Символы.ПС;
	Сводка = Сводка + "- Holat (oldindan): **" + ПредварительноеСостояние + "**" + Символы.ПС;
	Сводка = Сводка + "- Xato soni: " + Формат(ЖурналОшибок.Количество(), "ЧГ=0") + Символы.ПС;
	Сводка = Сводка + Символы.ПС;
	Сводка = Сводка + "> ⚠️ Yuqoridagi holat `run_summary.md` va `manifest.json` YOZILISHIDAN"
		+ " OLDIN hisoblangan. QAT'IY holat — `run_status.json` ning `overall` maydonida."
		+ Символы.ПС + Символы.ПС;
	Сводка = Сводка + "> ⚠️ Bu yig'uvchi RUNTIME'DA SINALMAGAN. «Ishlaydi» degan da'vo yo'q."
		+ Символы.ПС + Символы.ПС;

	Сводка = Сводка + "## Bo'limlar" + Символы.ПС + Символы.ПС;
	Сводка = Сводка + "| bo'lim | holat | izoh |" + Символы.ПС;
	Сводка = Сводка + "|---|---|---|" + Символы.ПС;
	Для Каждого Раздел Из СобратьРазделыЗапуска() Цикл
		Сводка = Сводка + "| " + Раздел.name + " | " + Раздел.status + " | "
			+ ?(Раздел.error = Неопределено, "", Строка(Раздел.error)) + " |" + Символы.ПС;
	КонецЦикла;

	Сводка = Сводка + Символы.ПС + "## Oilalar" + Символы.ПС + Символы.ПС;
	Сводка = Сводка + "| oila | holat | izoh |" + Символы.ПС;
	Сводка = Сводка + "|---|---|---|" + Символы.ПС;
	Для Каждого Семейство Из ЖурналСемейств Цикл
		Сводка = Сводка + "| " + Семейство.name + " | " + Семейство.state + " | "
			+ ?(Семейство.detail = Неопределено, "", Строка(Семейство.detail)) + " |"
			+ Символы.ПС;
	КонецЦикла;

	Сводка = Сводка + Символы.ПС + "`absent` = o'qildi va YO'Q (to'liq javob). "
		+ "`unreadable` = O'QIY OLMADIM. Ikkisi bir xil narsa EMAS va ikkisi ham OILA "
		+ "holati: bo'lim holati faqat `ok`/`failed`/`skipped` bo'ladi." + Символы.ПС;

	Если ЖурналЗондов.Количество() > 0 Тогда
		Сводка = Сводка + Символы.ПС + "## Bajarilgan zondlar" + Символы.ПС + Символы.ПС;
		Для Каждого Запись Из ЖурналЗондов Цикл
			Сводка = Сводка + "- `" + Запись.probe_type + "` -> `" + Запись.target_object
				+ "` (" + Запись.status + ") — SABAB: " + Запись.reason + Символы.ПС;
		КонецЦикла;
	Иначе
		Сводка = Сводка + Символы.ПС + "## Zondlar" + Символы.ПС + Символы.ПС
			+ "Birorta aktiv zond bajarilmadi." + Символы.ПС;
	КонецЕсли;

	Сводка = Сводка + Символы.ПС + "## Yuborish" + Символы.ПС + Символы.ПС
		+ "Papkadagi HAMMA faylni birga yuboring. Yuborishdan OLDIN mijoz `export.json` va "
		+ "`metadata.json` ni ko'rib chiqsin: ular konfiguratsiya tuzilmasini ochib beradi."
		+ Символы.ПС;
	Возврат Сводка;

КонецФункции

// ── YOZISH ────────────────────────────────────────────────────────────────────────────────
// ⚠️ FAYL YOZISH FAQAT RUNTIME PAKETI ARTEFAKTLARI UCHUN. Boshqa fayl kanali (nusxa ko'chirish,
//    o'chirish, tashqi ilova, boshqa yozuvchi obyekt) statik audit bilan TAQIQLANGAN.
// ⚠️ MANIFESTGA RO'YXATGA OLISH shu yerda bo'ladi: har yozilgan fayl DARHOL o'lchanadi va
//    xeshlanadi. Keyin o'lchash fayl allaqachon o'zgargan bo'lishi xavfini kiritardi.
Функция ЗаписатьJSONФайл(КаталогВыгрузки, ОтносительныйПуть, Данные, Регистрировать)

	Путь = КаталогВыгрузки + "/" + ОтносительныйПуть;
	Попытка
		ПараметрыJSON = Новый ПараметрыЗаписиJSON(ПереносСтрокJSON.Авто, "  ");
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(Путь, "UTF-8", Ложь, ПараметрыJSON);
		ЗаписатьJSON(ПотокJSON, Данные);
		ПотокJSON.Закрыть();
	Исключение
		ДобавитьОшибку("write", Неопределено, ОтносительныйПуть, "WRITE_FAILED",
			ОписаниеОшибки());
		Возврат Ложь;
	КонецПопытки;

	// ⚠️ ARTEFAKT FAQAT YOZILGANDAN KEYIN BELGILANADI: «yozaman» degan niyat dalil emas.
	ОтметитьАртефакт(ОтносительныйПуть);
	Если Регистрировать Тогда
		ЗарегистрироватьФайл(ОтносительныйПуть, Путь);
	КонецЕсли;
	Возврат Истина;

КонецФункции

// Markdown xulosani yozadi.
// ⚠️ NEGA `ЗаписьJSON` BILAN MATN YOZILADI. Matn faylini yozadigan odatiy vositalar —
//    matn/ma'lumot yozuvchi obyektlar sinfi va matnli hujjatni faylga tushiruvchi usul —
//    statik audit bilan TAQIQLANGAN (`FOREIGN_WRITER_OBJECT` va `WRITE_OBJECT` qoidalari):
//    ular ikkinchi, nazoratsiz chiqish kanali bo'lardi. Audit qoidasini YUMSHATISH o'rniga
//    MAVJUD ruxsat etilgan kanal ishlatiladi: `ЗаписьJSON` ning `ЗаписатьБезОбработки`
//    metodi xom matn yozadi.
// ⚠️ ATAYLAB: bu izohda taqiqlangan nomlarning O'ZI yozilmagan. Audit IZOHNI HAM tekshiradi
//    (kimdir uni izohdan chiqarib qo'yishi mumkin), shu bois taqiq sabablari faqat QOIDA
//    KODI bilan atalgan.
// ⚠️ RUNTIME-UNKNOWN: bu yo'l birorta 1C bazasida SINALMAGAN. `Закрыть()` JSON hujjati
//    tugallanmaganini aytib xato berishi MUMKIN. Shunda fayl yozilmaydi, sabab `errors.json`
//    ga tushadi va umumiy holat `FAILED` bo'ladi (`run_summary.md` MAJBURIY artefakt).
//    Ya'ni nuqson JIMGINA o'tmaydi — lekin bu yo'lning ishlashi ISBOTLANMAGAN.
Функция ЗаписатьСводку(КаталогВыгрузки, Текст)

	ОтносительныйПуть = "run_summary.md";
	Путь = КаталогВыгрузки + "/" + ОтносительныйПуть;

	Попытка
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(Путь, "UTF-8", Ложь);
		ПотокJSON.ЗаписатьБезОбработки(Текст);
		ПотокJSON.Закрыть();
	Исключение
		ДобавитьОшибку("write", Неопределено, ОтносительныйПуть, "WRITE_FAILED",
			ОписаниеОшибки());
		Возврат Ложь;
	КонецПопытки;

	ОтметитьАртефакт(ОтносительныйПуть);
	ЗарегистрироватьФайл(ОтносительныйПуть, Путь);
	Возврат Истина;

КонецФункции

// Faylni manifest ro'yxatiga oladi: nomi, bayt hajmi, sha256.
// ⚠️ YOLG'ON XESH YOZILMAYDI. `ХешированиеДанных` platformada bo'lmasa (eski relizlar) yoki
//    fayl o'qilmasa — `sha256` `Неопределено` bo'lib QOLADI va sabab `UNHASHABLE` kodli xato
//    bo'lib qayd etiladi. «Xesh yo'q» deyish soxta xeshdan YAXSHI: soxta xesh butun
//    manifestni ma'nosiz qiladi, chunki unga suyanib solishtirish mumkin bo'lib ko'rinadi.
Процедура ЗарегистрироватьФайл(ОтносительныйПуть, Путь)

	Запись = Новый Структура;
	// ⚠️ Kalit `name` (ilgari `file` edi): manifest fayl yozuvining kalitlari BinOS tomonida
	//    QAT'IY tekshiriladi va `file` nomi bilan HAR BIR manifest rad etilardi.
	Запись.Вставить("name", ОтносительныйПуть);
	Запись.Вставить("bytes", Неопределено);      // MATN: JSON soni `0000123` ni buzardi
	Запись.Вставить("sha256", Неопределено);

	Попытка
		ОписаниеФайла = Новый Файл(Путь);
		Запись.bytes = Формат(ОписаниеФайла.Размер(), "ЧГ=0");
	Исключение
		ДобавитьОшибку("write", Неопределено, ОтносительныйПуть, "UNHASHABLE",
			"bayt hajmi o'lchanmadi: " + ОписаниеОшибки());
	КонецПопытки;

	Попытка
		Хеш = Новый ХешированиеДанных(ХешФункция.SHA256);
		ДвоичныеДанныеФайла = Новый ДвоичныеДанные(Путь);
		Хеш.Добавить(ДвоичныеДанныеФайла);
		Запись.sha256 = НРег(ПолучитьHexСтрокуИзДвоичныхДанных(Хеш.ХешСумма));
	Исключение
		ДобавитьОшибку("write", Неопределено, ОтносительныйПуть, "UNHASHABLE",
			"sha256 hisoblanmadi: " + ОписаниеОшибки());
	КонецПопытки;

	ЖурналФайлов.Добавить(Запись);

КонецПроцедуры

Функция ВыгрузитьВФайл(КаталогВыгрузки, Экспорт)

	Если ЗаписатьJSONФайл(КаталогВыгрузки, "export.json", Экспорт, Истина) Тогда
		ОтметитьЗапуск("write_export", "ok");
		Возврат Истина;
	КонецЕсли;

	// Yozish yiqilsa ham bo'lim jurnalida qoladi — jimgina yo'qolmaydi.
	ОтметитьРаздел("write_export", "failed", "`export.json` yozilmadi — sabab `errors.json` da");
	ОтметитьЗапуск("write_export", "failed", "`export.json` yozilmadi");
	Возврат Ложь;

КонецФункции

// ⚠️ Inventarizatsiyaning yozilishi `export.json` JURNALIDA qayd etiladi: agar u faqat o'z
//    ichida qayd etilsa va yozish yiqilsa, xato bilan birga yo'qolardi.
Функция ВыгрузитьИнвентаризацию(КаталогВыгрузки, Инвентаризация)

	Если ЗаписатьJSONФайл(КаталогВыгрузки, "metadata.json", Инвентаризация, Истина) Тогда
		ОтметитьРаздел("write_metadata", "ok");
		ОтметитьЗапуск("write_metadata", "ok");
		Возврат Истина;
	КонецЕсли;

	ОтметитьРаздел("write_metadata", "failed",
		"`metadata.json` yozilmadi — sabab `errors.json` da");
	ОтметитьЗапуск("write_metadata", "failed", "`metadata.json` yozilmadi");
	Возврат Ложь;

КонецФункции

#КонецОбласти
