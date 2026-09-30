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

#КонецОбласти

#Область ПрограммныйИнтерфейс

// Asosiy kirish nuqtasi. `КаталогВыгрузки` — operator ko'rsatgan BO'SH, MAVJUD papka.
//
// Qaytaradi: Структура("export", "metadata") — ikki hujjat. Fayllar ham yoziladi:
// `export.json` va `metadata.json`.
Функция ВыполнитьРазведку(КаталогВыгрузки) Экспорт

	ЖурналРазделов = Новый Массив;
	ЖурналМетаданных = Новый Массив;
	ВремяНачала = ТекущаяДата();

	Платформа = СобратьПлатформу();
	Объекты = СобратьОбъекты();
	Счетчики = СобратьСчетчики();
	Кандидаты = СобратьКандидатов();

	// Inventarizatsiya AVVAL yoziladi: uning yozilishi yiqilsa, bu `export.json` jurnalida
	// `write_metadata` bo'lib ko'rinadi. Aks holda ikkinchi hujjatning yo'qligi jimgina
	// «shunchaki bo'lmagan» ga o'xshab qolardi.
	Инвентаризация = СобратьИнвентаризацию();
	ВыгрузитьИнвентаризацию(КаталогВыгрузки, Инвентаризация);

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

	ВыгрузитьВФайл(КаталогВыгрузки, Экспорт);

	Результат = Новый Структура;
	Результат.Вставить("export", Экспорт);
	Результат.Вставить("metadata", Инвентаризация);
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
		Результат.result = ЗондСанокҚаторлар(ПолноеИмяОбъекта, Ошибки);
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
	КонецЕсли;

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
	Иначе
		ОтметитьРаздел("metadata_sweep", "failed", Ошибки);
	КонецЕсли;

	Возврат Объекты;

КонецФункции

Процедура ДобавитьКоллекцию(Объекты, Коллекция, Префикс, ВидИсточника)

	Для Каждого ОбъектМД Из Коллекция Цикл
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
	Иначе
		ОтметитьРаздел("counts", "failed", Ошибки);
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
		Возврат;
	КонецЕсли;

	Ошибки = "";
	Попытка
		Для Каждого ОбъектМД Из Коллекция Цикл
			Объекты.Добавить(ОписатьОбъект(ОбъектМД, Описание.prefix, Описание.kind));
		КонецЦикла;
	Исключение
		Ошибки = ОписаниеОшибки();
	КонецПопытки;

	Если ПустаяСтрока(Ошибки) Тогда
		ОтметитьРазделМетаданных(Описание.section, "ok");
	Иначе
		ОтметитьРазделМетаданных(Описание.section, "failed", Ошибки);
	КонецЕсли;

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
		Возврат;
	КонецЕсли;

	Попытка
		Сколько = Формат(Коллекция.Количество(), "ЧГ=0");
	Исключение
		ОтметитьРазделМетаданных("chart_of_accounts", "failed", ОписаниеОшибки());
		Возврат;
	КонецПопытки;

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
Функция ЗондСанокҚаторлар(ПолноеИмяОбъекта, Ошибки)

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

// ── YOZISH ────────────────────────────────────────────────────────────────────────────────
// ⚠️ FAYL YOZISH FAQAT SHU IKKI EKSPORT UCHUN. Boshqa fayl kanali (nusxa ko'chirish, o'chirish,
//    tashqi ilova) statik audit bilan TAQIQLANGAN.
Процедура ВыгрузитьВФайл(КаталогВыгрузки, Экспорт)

	Попытка
		ПараметрыJSON = Новый ПараметрыЗаписиJSON(ПереносСтрокJSON.Авто, "  ");
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(КаталогВыгрузки + "/export.json", "UTF-8", Ложь, ПараметрыJSON);
		ЗаписатьJSON(ПотокJSON, Экспорт);
		ПотокJSON.Закрыть();
	Исключение
		// Yozish yiqilsa ham bo'lim jurnalida qoladi — jimgina yo'qolmaydi.
		ОтметитьРаздел("write_export", "failed", ОписаниеОшибки());
	КонецПопытки;

КонецПроцедуры

// ⚠️ Inventarizatsiyaning yozilishi `export.json` JURNALIDA qayd etiladi: agar u faqat o'z
//    ichida qayd etilsa va yozish yiqilsa, xato bilan birga yo'qolardi.
Процедура ВыгрузитьИнвентаризацию(КаталогВыгрузки, Инвентаризация)

	Попытка
		ПараметрыJSON = Новый ПараметрыЗаписиJSON(ПереносСтрокJSON.Авто, "  ");
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(КаталогВыгрузки + "/metadata.json", "UTF-8", Ложь, ПараметрыJSON);
		ЗаписатьJSON(ПотокJSON, Инвентаризация);
		ПотокJSON.Закрыть();
		ОтметитьРаздел("write_metadata", "ok");
	Исключение
		ОтметитьРаздел("write_metadata", "failed", ОписаниеОшибки());
	КонецПопытки;

КонецПроцедуры

#КонецОбласти
