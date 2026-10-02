// BinOS Discovery Collector — KO'PRIK QATLAMI. 1C tashqi qayta ishlash ObjectModule
// manbasining FRAGMENTI (mustaqil modul EMAS — pastdagi «QANDAY YIG'ILADI» ga qarang).
//
// ⚠️⚠️  RUNTIME'DA SINALMAGAN.  Bu manba 1C:Enterprise platformasi BO'LMAGAN mashinada
//       yozilgan. U kompilyatsiya QILINMAGAN, sintaksis tekshiruvidan O'TMAGAN va hech
//       qanday 1C bazasida ISHLATILMAGAN. `.epf` konteyneri YIG'ILMAGAN va repoda YO'Q.
//       Holat nomi AYNAN `EPF_SOURCE_READY` — «tayyor o'rnatma» EMAS.
//
// ⚠️⚠️  FAQAT AJRATILGAN NUSXADA.  Bu qayta ishlash HECH QACHON jonli bazada ochilmaydi.
//       Nusxa alohida (do'kon LAN'idagi zaxira) kompyuterga tiklanadi va u yerda ishlatiladi.
//
// ── NEGA BU QATLAM BOR (va nega u YIG'UVCHI EMAS) ─────────────────────────────────────────
// ⚠️ IKKINCHI DISCOVERY DVIGATELI QURILMAYDI. Strukturaviy metadatani o'qish, kardinallik
//    zondlari, `binos-1c-export-v1` va `binos-1c-metadata-v1` hujjatlari, xato paketi va
//    manifest — hammasi MAVJUD `integrations/1c/extractor/BinOSDiscovery.bsl` da (2531 satr,
//    38 qoidali statik audit bilan qulflangan). Bu fragment unga BIRORTA qobiliyat qo'shmaydi.
//
// ⚠️ U QO'SHADIGAN YAGONA NARSA — KO'PRIK: agent (BinOS tomonidagi Python jarayoni) bilan
//    yig'uvchi orasidagi FAYLGA ASOSLANGAN shartnoma. Agent ko'prikni ISHGA TUSHIRA olmaydi
//    (COM yo'q, o'ylab chiqarilgan buyruq satri parametri yo'q), lekin u SO'ROV qoldira oladi
//    va JAVOBNI ishonchli taniy oladi. Shu ikki fayl — butun qo'shimcha.
//
// ── BESH QADAM, BOSHQA HECH NARSA ─────────────────────────────────────────────────────────
//   1. `request.json` ni O'Z papkasidan o'qiydi (ARGUMENTSIZ kirish nuqtasi);
//   2. shartnoma versiyasini, yig'uvchi versiyasini va `nonce` shaklini TEKSHIRADI;
//   3. MAVJUD `ВыполнитьРазведку(<output_dir>, <mode>, <allowed_probes>)` ni CHAQIRADI;
//   4. `response.json` yozadi (kimlikni QAYTA AYTADI: run_id, nonce, collector, fingerprint);
//   5. ENG OXIRIDA `bridge_done.json` yozadi.
//
// ── SHARTNOMA FAYLLARI ────────────────────────────────────────────────────────────────────
//   | fayl              | shartnoma                  | kim yozadi | qachon              |
//   | request.json      | `binos-bridge-request-v1`  | AGENT      | ko'prikdan OLDIN    |
//   | response.json     | `binos-bridge-response-v1` | KO'PRIK    | yurishdan KEYIN     |
//   | bridge_done.json  | `binos-bridge-done-v1`     | KO'PRIK    | ENG OXIRIDA         |
//
// ⚠️ PHASE 4 PAKETINING `manifest.json` I O'ZGARMAYDI. U `output_dir` (ya'ni `bundle/`)
//    ICHIDA qoladi va o'z navbatida ENG OXIRGI fayl bo'lib yoziladi. `bridge_done.json` —
//    QO'SHIMCHA qatlam: u paket shartnomasini almashtirmaydi, uning USTIGA qo'yiladi.
//    Tekshirish tartibi ham shunday: avval `bundle/manifest.json` (paket to'liq mi), keyin
//    `bridge_done.json` (yurish tugadi mi).
//
// ── NIMA QILMAYDI ─────────────────────────────────────────────────────────────────────────
// ⚠️ FAQAT O'QISH. Bazaga yozish, hujjat o'tkazish, tranzaksiya, monopol rejim, dinamik kod,
//    tashqi jarayon, uskuna buyrug'i, fayl nusxalash/ko'chirish/o'chirish — YO'Q. Taqiq
//    `app/services/discovery_1c/epf_audit.py` ning 38 qoidasi bilan MAJBURLANADI va bu
//    fragment ham shu auditdan o'tadi (`tests/test_agent_collector_source.py`).
// ⚠️ KATALOG YARATMAYDI. Katalog yaratish statik audit bilan taqiqlangan, ya'ni `output_dir`
//    (va zond ruxsat etilgan bo'lsa `output_dir/probes`) AGENT tomonidan OLDIN yaratilgan,
//    MAVJUD va BO'SH bo'lishi SHART. Bo'lmasa paket to'liq chiqmaydi va sabab
//    `bundle/errors.json` ga tushadi. Bu QOBILIYAT CHEGARASI, yashirilmaydi.
// ⚠️ KREDENSIALGA TEGMAYDI. Ko'prik parolni O'QIMAYDI, YOZMAYDI va SO'RAMAYDI. Bazaga
//    ulanish 1C ning O'Z oynasi orqali bo'ladi; `request.json` da `locator` ham, parol ham
//    YO'Q — faqat nishon kimligining XESHI (`target_fingerprint`).
// ⚠️ `ПараметрЗапуска` NI O'QIMAYDI. Kirish nuqtasi ARGUMENTSIZ: so'rov FAYLDAN keladi.
//    Sabab — CP1 da aniqlangan bo'shliq AYNAN argumentli kirish nuqtasi edi: agent buyruq
//    satriga qiymat qo'shardi, modulda esa uni o'qiydigan joy yo'q edi va natija JIMGINA
//    bo'sh papka bo'lardi. Buyruq satri parametri O'YLAB CHIQARILMAYDI; agent qo'shadigan
//    `/C<...>` bo'lagi bu fragment tomonidan E'TIBORGA OLINMAYDI.
//
// ── DEFAULT REJIM: METADATA_ONLY ──────────────────────────────────────────────────────────
// ⚠️ Rejim qarori KO'PRIKDA TAKRORLANMAYDI. `mode` `request.json` dan OLINADI va
//    `ВыполнитьРазведку` ga O'ZGARTIRILMASDAN uzatiladi; noma'lum yoki bo'sh rejimda
//    yig'uvchining O'Z fail-safe darvozasi `METADATA_ONLY` ga tushiradi va sababni
//    `run_status.json`.`mode_note` ga yozadi. Ikkinchi normallashtirish ikki tomonni ZID
//    qilib qo'yardi — aynan Phase 4 ning darsi.
//
// ── QANDAY YIG'ILADI (fragment, mustaqil modul EMAS) ──────────────────────────────────────
// ⚠️ Tashqi qayta ishlashda BITTA ObjectModule bor, ya'ni bu matn MAVJUD yig'uvchi bilan
//    BIR modulda yashaydi: `BinOSDiscovery.bsl` to'liq qo'yiladi, so'ng bu fragment uning
//    OXIRIGA qo'shiladi. Batafsil — `BUILD.md`.
// ⚠️ SHU BOIS BU FRAGMENTDA MODUL O'ZGARUVCHISI (`Перем`) YO'Q: 1C modul o'zgaruvchilarini
//    BIRINCHI protseduradan OLDIN talab qiladi, oxiriga qo'shilgan e'lon kompilyatsiyani
//    yiqitardi. Butun holat MAHALLIY o'zgaruvchilarda va parametrlarda yuradi.
// ⚠️ VA SHU BOIS HAMMA NOM `Мост` BILAN BOSHLANADI: bir moduldagi ikki bir xil nom
//    kompilyatsiyani yiqitadi. Nomlar kesishmasligi test bilan QULFLANGAN.

#Область ПрограммныйИнтерфейс

// KO'PRIKNING YAGONA KIRISH NUQTASI — ARGUMENTSIZ.
//
// Qaytaradi: Структура("status", "notes", "run_id", "output_dir") — operatorga ko'rsatish va
// yig'ib olish uchun. ⚠️ QAYTARILGAN QIYMAT DALIL EMAS: haqiqiy dalil — DISKDAGI
// `response.json` + `bridge_done.json` + `bundle/manifest.json` uchligi. Agent faqat
// fayllarga qaraydi, bu qiymatga EMAS.
//
// ⚠️ `status` lug'ati yig'uvchining O'Z lug'ati: "SUCCESS" | "PARTIAL" | "FAILED" — ustiga
//    faqat "BRIDGE_REJECTED" qo'shiladi (ko'prik yurishni BOSHLAMADI). Yangi lug'at yasash
//    ikki tomonni ZID qilardi.
// ⚠️ NEGA "REJECTED" EMAS, "BRIDGE_REJECTED" (TOPILGAN TO'QNASHUV). `REJECTED` MAVJUD
//    yig'uvchida ALLAQACHON ishlatiladi — lekin BOSHQA ma'noda: u `bundle/errors.json`
//    ning `code` lug'atidagi qiymat ("WRITE_FAILED | PROBE_FAILED | REJECTED | UNHASHABLE")
//    va REJIM rad etilganini bildiradi, YURISH rad etilganini emas. Bir xil so'z ikki
//    shartnomada — aynan `status.json` va `run_status.json` ni ajratishga majbur qilgan
//    naqsh: kod ham, odam ham qaysi lug'at ekanini chalkashtirardi. Shu bois ko'prikning
//    qiymati ATAYLAB o'z prefiksini oladi.
Функция ВыполнитьМостРазведки() Экспорт

	МостЗаметки = Новый Массив;
	МостНачало = МостВремяISO();

	// 1-QADAM: O'Z papkasini topish. Boshqa hamma qadam shundan keyin keladi.
	МостКаталог = МостСвойКаталог(МостЗаметки);
	Если ПустаяСтрока(МостКаталог) Тогда
		// ⚠️ Papka topilmasa SO'ROV ham, CHIQISH yo'li ham noma'lum: bu yerda birorta fayl
		//    yozib bo'lmaydi. Operatorga aytiladi, agent esa javob kelmaganini ko'radi.
		Возврат МостИтог("BRIDGE_REJECTED", МостЗаметки, "", "");
	КонецЕсли;

	// ⚠️ TUGALLANISH BELGISI ALLAQACHON BOR BO'LSA — HECH NARSA YOZILMAYDI. Ikkinchi yurish
	//    birinchisining javobini USTIGA yozardi, ya'ni dalilni YO'Q QILARDI. Ko'prik faylni
	//    o'chira olmaydi (taqiqlangan) va o'chirishga URINMAYDI: u RAD ETADI.
	Если МостФайлСуществует(МостКаталог, МостИмяМеткиЗавершения()) Тогда
		МостЗаметка(МостЗаметки, "RUN_DIR_NOT_EMPTY");
		Возврат МостИтог("BRIDGE_REJECTED", МостЗаметки, "", "");
	КонецЕсли;

	// 2-QADAM: so'rovni o'qish va TEKSHIRISH.
	МостЗапрос = МостПрочитатьЗапрос(МостКаталог, МостЗаметки);
	Если МостЗапрос = Неопределено Тогда
		Возврат МостИтог("BRIDGE_REJECTED", МостЗаметки, "", "");
	КонецЕсли;

	МостКлючЗапуска = МостКлючИзЗапроса(МостЗапрос);

	// ⚠️ KIMLIK SHAKLI — HAMMA YOZISHDAN OLDIN. Javob so'rovning `run_id`, `nonce` va
	//    `target_fingerprint` ini QAYTA AYTADI; agar ularning SHAKLI buzuq bo'lsa, yozilgan
	//    javobni agent UMUMAN ajratib o'qiy olmaydi va u `BRIDGE_SHAPE_INVALID` bo'lib
	//    qaytadi — ya'ni «rad etishni ANIQ aytish» maqsadi bajarilmaydi. Shunday holatda
	//    JIMLIK YAXSHIROQ: agent javob YO'Qligini aniq ko'radi, operator esa xabarni
	//    1C oynasida o'qiydi. Buzuq kimlik bilan javob yozish faqat chalkashlik qo'shardi.
	МостСабабКимлик = МостПроверитьКимлик(МостЗапрос);
	Если Не ПустаяСтрока(МостСабабКимлик) Тогда
		МостЗаметка(МостЗаметки, МостСабабКимлик);
		Возврат МостИтог("BRIDGE_REJECTED", МостЗаметки, "", "");
	КонецЕсли;

	МостПричина = МостПроверитьЗапрос(МостЗапрос, МостКаталог);
	Если Не ПустаяСтрока(МостПричина) Тогда
		МостЗаметка(МостЗаметки, МостПричина);
		// ⚠️ RAD ETISHDA HAM JAVOB VA BELGI YOZILADI. Aks holda agent FARQLAY OLMAYDI:
		//    «ko'prik rad etdi» va «1C umuman ochilmadi» ikkisi ham JIMLIK bo'lib ko'rinardi.
		//    Rad etish ANIQ javobdir, jimlik esa emas.
		Если МостЗаписатьОтвет(МостКаталог, МостКлючЗапуска, "BRIDGE_REJECTED",
				МостНачало, МостЗаметки) Тогда
			МостЗаписатьМеткуЗавершения(МостКаталог, МостКлючЗапуска);
		КонецЕсли;
		Возврат МостИтог("BRIDGE_REJECTED", МостЗаметки, МостКлючЗапуска.run_id, "");
	КонецЕсли;

	// 3-QADAM: MAVJUD yig'uvchini chaqirish. Bu yerda BIRORTA qaror qayta ko'rilmaydi.
	МостВыход = МостПоле(МостЗапрос, "output_dir", "");
	МостСостояние = "FAILED";
	Попытка
		ВыполнитьРазведку(МостВыход,
			МостПоле(МостЗапрос, "mode", Неопределено),
			МостПоле(МостЗапрос, "allowed_probes", Неопределено));
		// ⚠️ UMUMIY HOLAT YIG'UVCHINING O'Z HUJJATIDAN O'QILADI, qaytarilgan qiymatdan EMAS:
		//    `run_status.json` — DISKDAGI dalil, qaytarilgan tuzilma esa xotirada. Ikkisi
		//    ajralib ketsa, diskdagi fayl haqiqat bo'ladi, chunki agent faqat uni ko'radi.
		МостСостояние = МостОбщееСостояние(МостВыход, МостЗаметки);
	Исключение
		// ⚠️ XATO MATNINING O'ZI `notes` GA TUSHMAYDI — faqat KOD tushadi. Sabab aniq:
		//    `ОписаниеОшибки()` FAYL YO'LINI o'z ichiga olishi mumkin, agent tomonidagi
		//    `notes` darvozasi esa shubhali qiymatni ko'rsa BUTUN hujjatni rad etadi.
		//    Ya'ni xato matnini yozish paketni rad etilishiga olib kelardi — nuqson
		//    sababini yo'qotib, ustiga yana bitta nuqson qo'shardi.
		// ⚠️ MATN YO'QOLMAYDI, LEKIN PROTOKOLGA KIRMAYDI: u operatorga 1C oynasida
		//    ko'rsatiladi. CHEGARA ochiq: paketli (fonda) ishga tushirishda bu xabar
		//    KO'RINMAYDI va `ВыполнитьРазведку` birorta fayl yozishdan OLDIN yiqilsa,
		//    tafsilot faqat KOD bo'lib qoladi. Paket chiqqan holatda tafsilot baribir
		//    `bundle/errors.json` da.
		Сообщить(Лев(ОписаниеОшибки(), 500));
		МостЗаметка(МостЗаметки, "COLLECTOR_RAISED");
	КонецПопытки;

	// 4-QADAM: javob. 5-QADAM: tugallanish belgisi — AYNAN shu tartibda va SHARTLI:
	// javob yozilmagan bo'lsa belgi ham yozilmaydi.
	Если МостЗаписатьОтвет(МостКаталог, МостКлючЗапуска, МостСостояние,
			МостНачало, МостЗаметки) Тогда
		МостЗаписатьМеткуЗавершения(МостКаталог, МостКлючЗапуска);
	КонецЕсли;

	Возврат МостИтог(МостСостояние, МостЗаметки, МостКлючЗапуска.run_id, МостВыход);

КонецФункции

#КонецОбласти

#Область МостСлужебныеПроцедуры

// ── SHARTNOMA DOIMIYLARI — BITTA JOYDA ────────────────────────────────────────────────────
// ⚠️ NEGA FUNKSIYA, ALOHIDA DOIMIY EMAS: bu fragmentda `Перем` yozib bo'lmaydi (modul
//    oxiriga qo'shiladi), demak doimiy ham faqat funksiya ko'rinishida yashaydi.

Функция МостИмяФайлаЗапроса()
	Возврат "request.json";
КонецФункции

Функция МостИмяФайлаОтвета()
	Возврат "response.json";
КонецФункции

Функция МостИмяМеткиЗавершения()
	Возврат "bridge_done.json";
КонецФункции

Функция МостВерсияЗапроса()
	Возврат "binos-bridge-request-v1";
КонецФункции

Функция МостВерсияОтвета()
	Возврат "binos-bridge-response-v1";
КонецФункции

Функция МостВерсияМетки()
	Возврат "binos-bridge-done-v1";
КонецФункции

// KO'PRIK QATLAMINING kimligi. ⚠️ Bu `VERSION.json` dagi qiymat bilan AYNAN bir xil bo'lishi
// SHART: agent `expected_collector` ni shu nom va versiya bilan solishtiradi va farq bo'lsa
// `WRONG_COLLECTOR_VERSION` bilan paketni RAD ETADI. Ikki joyda ikki xil qiymat — Phase 4 da
// har bir real paketni rad etgan naqshning aynan o'zi.
// ⚠️ Versiya oxiridagi `-source` ATAYLAB: qurilgan `.epf` YO'Q, holat `EPF_SOURCE_READY`.
Функция МостОписаниеСборщика()

	Сборщик = Новый Структура;
	Сборщик.Вставить("name", "BinOSDiscoveryCollector");
	Сборщик.Вставить("version", "0.1.0-source");
	Возврат Сборщик;

КонецФункции

// `nonce` uzunligi (hex belgilar soni). Shartnoma: kamida 32, ko'pi bilan 128.
// ⚠️ CHEGARALAR AGENT TOMONIDAGI SHAKL DARVOZASI BILAN AYNAN BIR XIL. Agar ko'prik agent
//    rad etadigan qiymatni QABUL QILSA, nuqson ko'prikda emas, undan KEYIN ko'rinardi va
//    operator «yig'ish tugadi, lekin BinOS qabul qilmadi» degan tushunarsiz holatga tushardi.
Функция МостМинимумNonce()
	Возврат 32;
КонецФункции

Функция МостМаксимумNonce()
	Возврат 128;
КонецФункции

// `target_fingerprint` — sha256, AYNAN 64 hex belgi.
Функция МостДлинаОтпечатка()
	Возврат 64;
КонецФункции

// ── O'Z PAPKASINI TOPISH ──────────────────────────────────────────────────────────────────
// ⚠️ RUNTIME-UNKNOWN. `ИспользуемоеИмяФайла` — tashqi qayta ishlash FAYLDAN ochilganda uning
//    yo'lini beradigan xossa. Bu mashinada 1C yo'q, demak uning HAR senariyda to'lishi
//    (masalan qayta ishlash bazaning qo'shimcha ishlovlar katalogidan yuklanganda) bu yerda
//    ISBOTLANMAGAN. Bo'sh bo'lsa ko'prik TO'XTAYDI va o'ylab chiqarilgan zaxira yo'lga
//    O'TMAYDI: taxmin qilingan papkaga yozish begona joyga yozish bo'lardi.
Функция МостСвойКаталог(МостЗаметки)

	ИмяФайлаМодуля = "";
	Попытка
		ИмяФайлаМодуля = ЭтотОбъект.ИспользуемоеИмяФайла;
	Исключение
		МостЗаметка(МостЗаметки, "SELF_PATH_UNAVAILABLE");
		Возврат "";
	КонецПопытки;

	Если ПустаяСтрока(ИмяФайлаМодуля) Тогда
		МостЗаметка(МостЗаметки, "SELF_PATH_EMPTY");
		Возврат "";
	КонецЕсли;

	Попытка
		ФайлМодуля = Новый Файл(ИмяФайлаМодуля);
		Возврат ФайлМодуля.Путь;
	Исключение
		МостЗаметка(МостЗаметки, "SELF_PATH_UNREADABLE");
		Возврат "";
	КонецПопытки;

КонецФункции

// ⚠️ FAIL-CLOSED: tekshirib bo'lmasa «BOR» deb hisoblanadi. Bu AYNAN tugallanish belgisi
//    uchun to'g'ri yo'nalish — «yo'q» deyish uning ustiga yozish yo'lini ochardi. Qolgan
//    chaqiruvlarda («bor» deb hisoblangan `request.json`/`run_status.json`) keyingi qadam
//    o'qishga urinadi va ANIQ `..._UNREADABLE` sababi bilan to'xtaydi, ya'ni bu yerda
//    «bor» deyish hech qachon jimgina muvaffaqiyat bermaydi.
Функция МостФайлСуществует(Каталог, Имя)

	Попытка
		Проверяемый = Новый Файл(ОбъединитьПути(Каталог, Имя));
		Возврат Проверяемый.Существует();
	Исключение
		Возврат Истина;
	КонецПопытки;

КонецФункции

// Papkaning O'ZI mavjud mi. ⚠️ Alohida funksiya: `ОбъединитьПути` ga bo'sh nom berish
//    platformada nima qilishi SINALMAGAN, shu bois yo'l bu yerda qo'shilmaydi.
Функция МостКаталогСуществует(Путь)

	Попытка
		Проверяемый = Новый Файл(Путь);
		Возврат Проверяемый.Существует() И Проверяемый.ЭтоКаталог();
	Исключение
		Возврат Ложь;
	КонецПопытки;

КонецФункции

// ── SO'ROVNI O'QISH ───────────────────────────────────────────────────────────────────────
// ⚠️ `ПрочитатьJSON` ning ikkinchi argumenti `Ложь`: obyekt Структура bo'lib keladi, ya'ni
//    `allowed_probes` elementlari TO'G'RIDAN-TO'G'RI yig'uvchi kutgan shaklda bo'ladi
//    (`probe_type`/`target_object`/`reason`). Соответствие ga o'qib keyin qayta qurish
//    ikkinchi, sinalmagan tarjima qatlami bo'lardi.
// ⚠️ SHARTNOMA KALITLARI shu bois 1C identifikatori shaklida: lotin harf, raqam, pastki
//    chiziq. Begona kalit kelsa `ПрочитатьJSON` ISTISNO beradi va so'rov O'QILMADI deb
//    hisoblanadi — bu ochiq chegara, jimgina qisman o'qish emas.
Функция МостПрочитатьЗапрос(Каталог, МостЗаметки)

	Если Не МостФайлСуществует(Каталог, МостИмяФайлаЗапроса()) Тогда
		МостЗаметка(МостЗаметки, "REQUEST_NOT_FOUND");
		Возврат Неопределено;
	КонецЕсли;

	Попытка
		ПотокЧтения = Новый ЧтениеJSON;
		// ⚠️ KODLASH ANIQ BERILADI. Agent faylni UTF-8 da yozadi; platformaning standartiga
		//    tashlab qo'yish do'kon mashinasining mahalliy kod sahifasida o'qilish xavfini
		//    kiritardi va buzilgan kalit nomi JIMGINA «maydon yo'q» bo'lib ko'rinardi.
		ПотокЧтения.ОткрытьФайл(ОбъединитьПути(Каталог, МостИмяФайлаЗапроса()), "UTF-8");
		Прочитанное = ПрочитатьJSON(ПотокЧтения, Ложь);
		ПотокЧтения.Закрыть();
	Исключение
		// ⚠️ Xom xato matni `notes` ga TUSHMAYDI (yo'l sizib chiqishi mumkin) —
		//    faqat KOD. Tafsilot operatorga 1C oynasida ko'rsatiladi.
		Сообщить(Лев(ОписаниеОшибки(), 300));
		МостЗаметка(МостЗаметки, "REQUEST_UNREADABLE");
		Возврат Неопределено;
	КонецПопытки;

	Если ТипЗнч(Прочитанное) <> Тип("Структура") Тогда
		МостЗаметка(МостЗаметки, "REQUEST_NOT_AN_OBJECT");
		Возврат Неопределено;
	КонецЕсли;

	Возврат Прочитанное;

КонецФункции

// Структура maydonini XAVFSIZ o'qish (yo'q yoki `Неопределено` bo'lsa — standart qiymat).
Функция МостПоле(Данные, Имя, Стандарт)

	Значение = Стандарт;
	Если Данные.Свойство(Имя, Значение) Тогда
		Если Значение = Неопределено Тогда
			Возврат Стандарт;
		КонецЕсли;
		Возврат Значение;
	КонецЕсли;
	Возврат Стандарт;

КонецФункции

// ── TEKSHIRUV ─────────────────────────────────────────────────────────────────────────────
// Bo'sh matn = o'tdi. Aks holda RAD ETISH SABABI (kod).
// ⚠️ KO'PRIK O'Z TOMONIDAN NIMANI TEKSHIRADI: shartnoma versiyasi, majburiy maydonlarning
//    BORLIGI, `nonce` SHAKLI, yig'uvchi versiyasining MOSLIGI va chiqish papkasining O'Z
//    yurish papkasi ICHIDA bo'lishi.
// ⚠️ NIMANI TEKSHIRA OLMAYDI (ochiq chegara): `nonce` va `run_id` ning HAQIQIYLIGINI —
//    ularni agent yozgan va faqat agent biladi. Ko'prik ularni QAYTA AYTADI, TASDIQLAMAYDI.
//    Mosligini AGENT o'zi solishtiradi (`NONCE_MISMATCH`).
Функция МостПроверитьЗапрос(Запрос, Каталог)

	Если МостПоле(Запрос, "request_version", "") <> МостВерсияЗапроса() Тогда
		Возврат "REQUEST_VERSION_MISMATCH";
	КонецЕсли;

	Если ПустаяСтрока(МостПоле(Запрос, "requested_at", "")) Тогда
		Возврат "REQUEST_FIELD_MISSING";
	КонецЕсли;

	// ⚠️ YIG'UVCHI VERSIYASI. Agent KUTGAN nom va versiya shu fragmentdagi qiymatga MOS
	//    kelmasa, yurish BOSHLANMAYDI: noto'g'ri versiya yozgan paket keyin baribir rad
	//    etilardi, lekin undan OLDIN baza bo'ylab so'rov yuborilgan bo'lardi.
	Ожидаемый = МостПоле(Запрос, "expected_collector", Неопределено);
	Если ТипЗнч(Ожидаемый) <> Тип("Структура") Тогда
		Возврат "REQUEST_FIELD_MISSING";
	КонецЕсли;
	Наш = МостОписаниеСборщика();
	Если МостПоле(Ожидаемый, "name", "") <> Наш.name Тогда
		Возврат "WRONG_COLLECTOR_VERSION";
	КонецЕсли;
	Если МостПоле(Ожидаемый, "version", "") <> Наш.version Тогда
		Возврат "WRONG_COLLECTOR_VERSION";
	КонецЕсли;

	// ⚠️ CHIQISH PAPKASI O'Z YURISH PAPKASI ICHIDA bo'lishi SHART. Buzilgan yoki almashtirilgan
	//    `request.json` ko'prikni begona joyga yozishga yo'llardi; ko'prik esa WILDCARD
	//    O'CHIRISH ham, umumiy global natija fayli ham bilmaydi — har yurish O'Z papkasida.
	Выход = Строка(МостПоле(Запрос, "output_dir", ""));
	Если ПустаяСтрока(Выход) Тогда
		Возврат "REQUEST_FIELD_MISSING";
	КонецЕсли;
	Если Не МостВнутриКаталога(Выход, Каталог) Тогда
		Возврат "OUTPUT_DIR_OUTSIDE_RUN";
	КонецЕсли;
	Если Не МостКаталогСуществует(Выход) Тогда
		// ⚠️ Ko'prik katalog YARATMAYDI (statik audit bilan taqiqlangan): papkani AGENT
		//    oldin yaratadi. Yo'qligi QOBILIYAT CHEGARASI, jimgina o'tmaydi.
		Возврат "OUTPUT_DIR_MISSING";
	КонецЕсли;

	Возврат "";

КонецФункции

// Yo'l ikkinchi yo'lning ICHIDA mi. ⚠️ FAQAT MATN SOLISHTIRISHI: `..` bo'laklari,
// simvolik havola va qisqa (8.3) nom bu yerda OCHILMAYDI, demak bu to'liq himoya EMAS —
// u BUZILGAN so'rovni tutadi, maqsadli hujumni emas. Chegara ochiq yozilgan.
Функция МостВнутриКаталога(Путь, Каталог)

	Основа = МостНормальныйПуть(Каталог);
	Проверяемая = МостНормальныйПуть(Путь);
	Если ПустаяСтрока(Основа) Или ПустаяСтрока(Проверяемая) Тогда
		Возврат Ложь;
	КонецЕсли;
	Если Проверяемая = Основа Тогда
		Возврат Истина;
	КонецЕсли;
	Возврат Лев(Проверяемая, СтрДлина(Основа) + 1) = Основа + "/";

КонецФункции

// Yo'lni solishtirishga keltiradi: ajratuvchi `/`, oxiridagi ajratuvchi olib tashlanadi,
// registr pasaytiriladi (Windows yo'llari registrga sezgir emas).
// ⚠️ TESKARI CHIZIQ `Символ(92)` BILAN YOZILADI, satr literali bilan EMAS. BSL da yolg'iz
//    teskari chiziqli literal QONUNIY, lekin statik o'quvchi uni ko'chirib yozilgan `\"`
//    qochirishidan AJRATA OLMAYDI va literalni shu yerda yopilgan deb hisoblaydi — natijada
//    faylning QOLGAN QISMI «literal» bo'lib, begona alifbo harfini tutadigan darvoza
//    (`CHARSET_FOREIGN_LETTER`) KO'R bo'lib qolardi. Ya'ni bu tanlov uslub emas: u auditning
//    o'qiy olishini saqlaydi.
Функция МостНормальныйПуть(Путь)

	Значение = СтрЗаменить(Строка(Путь), Символ(92), "/");
	Пока СтрДлина(Значение) > 1 И Прав(Значение, 1) = "/" Цикл
		Значение = Лев(Значение, СтрДлина(Значение) - 1);
	КонецЦикла;
	Возврат НРег(Значение);

КонецФункции

// ⚠️ FAQAT KICHIK HEX. Agent tomonidagi darvoza aynan `[0-9a-f]` ni kutadi, shu bois
//    bosh harfli hex bu yerda RAD etiladi: ko'prik qabul qilib, agent rad etsa, nuqson
//    yig'ish TUGAGANDAN keyin ko'rinardi.
Функция МостHexСтрока(Текст)

	Разрешенные = "0123456789abcdef";
	Если СтрДлина(Текст) = 0 Тогда
		Возврат Ложь;
	КонецЕсли;
	Для Номер = 1 По СтрДлина(Текст) Цикл
		Если СтрНайти(Разрешенные, Сред(Текст, Номер, 1)) = 0 Тогда
			Возврат Ложь;
		КонецЕсли;
	КонецЦикла;
	Возврат Истина;

КонецФункции

// ── KIMLIK SHAKLI ─────────────────────────────────────────────────────────────────────────
// Bo'sh matn = o'tdi. Aks holda SABAB KODI.
// ⚠️ BU TEKSHIRUV HAMMA YOZISHDAN OLDIN bajariladi (kirish nuqtasidagi izohga qarang):
//    buzuq kimlik bilan yozilgan javobni agent ajratib o'qiy olmaydi.
// ⚠️ KO'PRIK `run_id` va `nonce` ning HAQIQIYLIGINI tekshira olmaydi — faqat SHAKLINI.
//    Haqiqiyligini agent o'zi solishtiradi (`NONCE_MISMATCH`, `STALE_OUTPUT`).
Функция МостПроверитьКимлик(Запрос)

	ЗначениеИдЗапуска = Строка(МостПоле(Запрос, "run_id", ""));
	Если ПустаяСтрока(ЗначениеИдЗапуска) Тогда
		Возврат "RUN_ID_MALFORMED";
	КонецЕсли;

	ЗначениеNonce = Строка(МостПоле(Запрос, "nonce", ""));
	Если СтрДлина(ЗначениеNonce) < МостМинимумNonce()
		Или СтрДлина(ЗначениеNonce) > МостМаксимумNonce()
		Или Не МостHexСтрока(ЗначениеNonce) Тогда
		Возврат "NONCE_MALFORMED";
	КонецЕсли;

	ЗначениеОтпечатка = Строка(МостПоле(Запрос, "target_fingerprint", ""));
	Если СтрДлина(ЗначениеОтпечатка) <> МостДлинаОтпечатка()
		Или Не МостHexСтрока(ЗначениеОтпечатка) Тогда
		Возврат "FINGERPRINT_MALFORMED";
	КонецЕсли;

	Возврат "";

КонецФункции

// ── KIMLIK: QAYTA AYTISH, TASDIQLASH EMAS ─────────────────────────────────────────────────
// ⚠️ `target_fingerprint` — AGENT hisoblagan xesh (`kind` + `name` + `locator` ning sha256'si).
//    Ko'prik uni QAYTA AYTADI va TEKSHIRMAYDI: xom `locator` protokolga YOZILMAYDI (u sir
//    bo'lishi mumkin), demak ko'prikda xeshni qayta hisoblash uchun kirish ma'lumoti YO'Q.
// ⚠️ SHU BOIS JAVOBDAGI `target_fingerprint` NISHON TO'G'RILIGINING DALILI EMAS. U faqat
//    «agent qaysi nishonni so'ragan bo'lsa, javob SHU so'rovga tegishli» degan BOG'LANISH.
//    Mustaqil dalil `bundle/metadata.json` da: konfiguratsiya inventarizatsiyasi.
Функция МостКлючИзЗапроса(Запрос)

	Ключ = Новый Структура;
	Ключ.Вставить("run_id", Строка(МостПоле(Запрос, "run_id", "")));
	Ключ.Вставить("nonce", Строка(МостПоле(Запрос, "nonce", "")));
	Ключ.Вставить("target_fingerprint", Строка(МостПоле(Запрос, "target_fingerprint", "")));
	Возврат Ключ;

КонецФункции

// ── UMUMIY HOLATNI DISKDAN O'QISH ─────────────────────────────────────────────────────────
// ⚠️ NEGA DISKDAN: agent faqat fayllarni ko'radi. Ko'prik xotiradagi qiymatni javobga yozsa
//    va u diskdagi `run_status.json` dan farq qilsa, ikki tomon ikki xil haqiqat ko'rardi.
// ⚠️ O'qilmasa `FAILED` qaytadi (fail-closed): «o'qiy olmadim» HECH QACHON «muvaffaqiyat»
//    degani emas.
Функция МостОбщееСостояние(КаталогВыхода, МостЗаметки)

	Если Не МостФайлСуществует(КаталогВыхода, "run_status.json") Тогда
		МостЗаметка(МостЗаметки, "RUN_STATUS_MISSING");
		Возврат "FAILED";
	КонецЕсли;

	Попытка
		ПотокЧтения = Новый ЧтениеJSON;
		ПотокЧтения.ОткрытьФайл(ОбъединитьПути(КаталогВыхода, "run_status.json"), "UTF-8");
		Прочитанное = ПрочитатьJSON(ПотокЧтения, Ложь);
		ПотокЧтения.Закрыть();
	Исключение
		МостЗаметка(МостЗаметки, "RUN_STATUS_UNREADABLE");
		Возврат "FAILED";
	КонецПопытки;

	Если ТипЗнч(Прочитанное) <> Тип("Структура") Тогда
		МостЗаметка(МостЗаметки, "RUN_STATUS_NOT_AN_OBJECT");
		Возврат "FAILED";
	КонецЕсли;

	Состояние = Строка(МостПоле(Прочитанное, "overall", ""));
	Если Состояние <> "SUCCESS" И Состояние <> "PARTIAL" И Состояние <> "FAILED" Тогда
		МостЗаметка(МостЗаметки, "RUN_STATUS_UNKNOWN_OVERALL");
		Возврат "FAILED";
	КонецЕсли;
	Возврат Состояние;

КонецФункции

// ── YOZISH ────────────────────────────────────────────────────────────────────────────────
// ⚠️ FAYL YOZISH FAQAT SHU IKKI SHARTNOMA FAYLI UCHUN. Boshqa fayl kanali (nusxa ko'chirish,
//    o'chirish, tashqi ilova, boshqa yozuvchi obyekt) statik audit bilan TAQIQLANGAN.
// ⚠️ CHIQISH UTF-8, BOM'siz (`ОткрытьФайл` ning uchinchi argumenti `Ложь`).
// ⚠️ QAYTARGAN QIYMAT O'QILADI. Javob yozilmagan bo'lsa tugallanish belgisi HAM yozilmaydi:
//    belgi «javob diskda» degan MA'NONI bildiradi va belgisiz javob agentni jimgina
//    noto'g'ri xulosaga olib borardi.
Функция МостЗаписатьОтвет(Каталог, Ключ, Состояние, Начало, МостЗаметки)

	Ответ = Новый Структура;
	Ответ.Вставить("response_version", МостВерсияОтвета());
	Ответ.Вставить("run_id", Ключ.run_id);
	Ответ.Вставить("nonce", Ключ.nonce);
	Ответ.Вставить("collector", МостОписаниеСборщика());
	Ответ.Вставить("target_fingerprint", Ключ.target_fingerprint);
	Ответ.Вставить("status", Состояние);
	Ответ.Вставить("started_at", Начало);
	Ответ.Вставить("finished_at", МостВремяISO());
	// ⚠️ `notes` — MATNLAR MASSIVI, qo'shilgan bitta satr EMAS. Agent tomonidagi
	//    darvoza aynan ro'yxat kutadi; bitta satrga qo'shish kodlarni ajratib
	//    bo'lmaydigan qilardi va hujjat shakl bo'yicha rad etilardi.
	Ответ.Вставить("notes", МостЗаметки);

	Возврат МостЗаписатьJSONФайл(Каталог, МостИмяФайлаОтвета(), Ответ);

КонецФункции

// ⚠️ ENG OXIRGI YOZISH. Belgi BOR degani — javob allaqachon diskda. Teskarisi emas: javob
//    bo'lib belgi bo'lmasligi MUMKIN (yozish yarmida to'xtadi) va agent AYNAN shu holatni
//    `bridge_done.json` yo'qligi bilan tutadi.
// ⚠️ BELGIGA HOLAT YOZILMAYDI. U faqat TUGALLANISH faktini aytadi; holat `response.json` da.
//    Ikki joyda holat bo'lsa, ular ajralib ketgan kun kimga ishonish noma'lum bo'lardi.
Функция МостЗаписатьМеткуЗавершения(Каталог, Ключ)

	Метка = Новый Структура;
	Метка.Вставить("done_version", МостВерсияМетки());
	Метка.Вставить("run_id", Ключ.run_id);
	Метка.Вставить("nonce", Ключ.nonce);
	Метка.Вставить("written_at", МостВремяISO());

	Возврат МостЗаписатьJSONФайл(Каталог, МостИмяМеткиЗавершения(), Метка);

КонецФункции

// Qaytaradi: `Истина` — fayl yozildi va oqim yopildi.
// ⚠️ OQIM `Исключение` SHOXIDA HAM YOPILADI. `ЗаписатьJSON` yarmida yiqilsa, yopilmagan oqim
//    fayl deskriptorini ochiq qoldirardi va diskda YARIM JSON qolardi — keyin kimdir uni
//    to'liq fayl deb o'qishi mumkin. Yopishning O'ZI ham yiqilishi mumkin, shu bois u ichki
//    `Попытка` ga olingan: ikkinchi istisno birinchisining sababini yo'q qilmasin.
Функция МостЗаписатьJSONФайл(Каталог, Имя, Данные)

	ПотокJSON = Неопределено;
	Попытка
		ПараметрыJSON = Новый ПараметрыЗаписиJSON(ПереносСтрокJSON.Авто, "  ");
		ПотокJSON = Новый ЗаписьJSON;
		ПотокJSON.ОткрытьФайл(ОбъединитьПути(Каталог, Имя), "UTF-8", Ложь, ПараметрыJSON);
		ЗаписатьJSON(ПотокJSON, Данные);
		ПотокJSON.Закрыть();
		Возврат Истина;
	Исключение
		// ⚠️ YOZISH YIQILSA JIMGINA O'TMAYDI. Sabab bu yerda FAYLGA yozilmaydi (yozish
		//    kanalining O'ZI yiqildi) — u operatorga ko'rsatiladi va fayl YO'Q yoki YARIM
		//    bo'lib qoladi. Agent `bridge_done.json` yo'qligidan buni ANIQ ko'radi.
		Если ПотокJSON <> Неопределено Тогда
			Попытка
				ПотокJSON.Закрыть();
			Исключение
				// Yopish ham yiqildi — qo'shimcha qilinadigan narsa yo'q.
			КонецПопытки;
		КонецЕсли;
		Сообщить(МостТекстОператору("BRIDGE_WRITE_FAILED"));
		Возврат Ложь;
	КонецПопытки;

КонецФункции

// ── VAQT ──────────────────────────────────────────────────────────────────────────────────
// ⚠️ UTC, ATAYLAB. Agent `written_at` ni `requested_at` bilan SOLISHTIRADI
//    (`OUTPUT_PREDATES_REQUEST`), ya'ni bu TARTIB taqqoslashi. Mahalliy vaqt zonasi noto'g'ri
//    sozlangan 1C seansi solishtirishni JIMGINA teskari qilib qo'yardi, shu bois ko'prik
//    universal (UTC) vaqtni yozadi va siljishni `+00:00` bilan OCHIQ ko'rsatadi.
// ⚠️ CHEGARA: bu SOAT SIYRILISHINI (clock skew) yo'q qilmaydi. E'lon qilingan oqimda agent
//    va 1C BIR mashinada ishlaydi, demak soat bitta; yig'uvchi BOSHQA mashinada ishlatilsa
//    `OUTPUT_PREDATES_REQUEST` YOLG'ON ishlashi mumkin. Bu `REAL_1C_HANDOFF.md` da yozilgan.
Функция МостВремяISO()

	Возврат Формат(ТекущаяУниверсальнаяДата(), "ДФ=yyyy-MM-ddTHH:mm:ss") + "+00:00";

КонецФункции

// ── OPERATOR MATNI ────────────────────────────────────────────────────────────────────────
// ⚠️ ICHKI ATAMA YO'Q. Operator `nonce`, `fingerprint`, `overall` so'zlarini ko'rmaydi: u
//    NIMA BO'LGANINI va NIMA QILISHINI o'qiydi. Kod esa `notes` da qoladi — u BinOS tomoni
//    uchun. Fazalarning operator matni AGENT tomonida (`bridge_phase.py`); bu yerda faqat
//    1C oynasida ko'rinadigan uchta holat bor.
Функция МостТекстОператору(Код)

	Если Код = "BRIDGE_WRITE_FAILED" Тогда
		Возврат "Natija fayli yozilmadi. Papkaga yozish huquqini tekshirib, qaytadan "
			+ "urinib ko'ring.";
	КонецЕсли;
	Если Код = "RUN_DIR_NOT_EMPTY" Тогда
		Возврат "Bu papkada tugagan yurish bor. BinOS dan YANGI yurish boshlang.";
	КонецЕсли;
	Если Код = "REQUEST_NOT_FOUND" Тогда
		Возврат "So'rov fayli topilmadi. Qayta ishlashni BinOS yaratgan papkadan oching.";
	КонецЕсли;
	Возврат "Yurish tugamadi. BinOS dagi izohga qarang.";

КонецФункции

Процедура МостЗаметка(МостЗаметки, Текст)

	МостЗаметки.Добавить(Текст);
	// ⚠️ OPERATORGA HAM AYTILADI. Jimgina rad etish operatorni «nega hech narsa bo'lmadi»
	//    degan savol bilan qoldirardi. Paketli (fonda) ishga tushirishda bu xabar KO'RINMAYDI
	//    — bu ochiq chegara, shu bois ASOSIY dalil baribir fayllarda.
	Сообщить(МостТекстОператору(Текст));

КонецПроцедуры

Функция МостИтог(Состояние, МостЗаметки, ИдЗапуска, Выход)

	Итог = Новый Структура;
	Итог.Вставить("status", Состояние);
	Итог.Вставить("notes", МостЗаметки);
	Итог.Вставить("run_id", ИдЗапуска);
	Итог.Вставить("output_dir", Выход);
	Возврат Итог;

КонецФункции

#КонецОбласти
