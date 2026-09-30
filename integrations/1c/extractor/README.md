# BinOS Discovery Extractor — qurish va ishlatish

> ## ⚠️ HOLAT: RUNTIME'DA SINALMAGAN
>
> `BinOSDiscovery.bsl` — **manba matni**. U:
> - **kompilyatsiya qilinmagan** (bu mashinada 1C:Enterprise platformasi yo'q),
> - **sintaksis tekshiruvidan o'tmagan**,
> - **hech qanday 1C bazasida ishlatilmagan**,
> - shuning uchun `.epf` **fayli repoda YO'Q va soxta ravishda yaratilmaydi**.
>
> Tekshirilgan yagona narsa — **manba matni** (pastga qarang). «Ishlaydi» degan da'vo yo'q.
>
> **Isbotlangani:** yig'uvchi **manbasida qattiq yozilgan konfiguratsiya nomi YO'Q** — buni
> statik test majburlaydi — va manba **ikki hujjat** yozishini e'lon qiladi: `export.json`
> (`binos-1c-export-v1`) va `metadata.json` (`binos-1c-metadata-v1`).
>
> **Isbotlanmagani:** modulning **har qanday konfiguratsiyada ISHLASHI**. U kompilyatsiya
> qilinmagan va birorta 1C bazasida ishlatilmagan, shu bois bu yerda «universal» so'zi
> QOBILIYATNI bildirmaydi — u faqat **manbada konfiguratsiya nomi yo'qligi**ni bildiradi.
> Turli konfiguratsiyada metadata kolleksiyalarining shakli farq qiladi; buni faqat
> haqiqiy baza ko'rsatadi.
>
> Nomzod aniqlash **BinOS tomonida** bajariladi; bu yig'uvchining qobiliyatini kamaytiradi
> va pastda ochiq yozilgan.

## Nima tekshirilgan (va nima yo'q)

| Tekshiruv | Holat | Qayerda |
|---|---|---|
| Manbada yozuv/o'tkazish/o'chirish chaqiruvi yo'qligi | ✅ **avtomatik, CI'da** | `app/services/discovery_1c/epf_audit.py` |
| Auditning o'zi ishlashi (**31 qoida** × buzuvchi namuna) | ✅ **avtomatik** | `tests/test_discovery_1c_epf_source.py` |
| Qonuniy chaqiruvlar yolg'on signal bermasligi | ✅ **avtomatik** | o'sha test |
| Manba o'zini «sinalmagan» deb belgilashi | ✅ **avtomatik** | o'sha test |
| Manbada **qattiq yozilgan konfiguratsiya nomi yo'qligi** | ✅ **avtomatik** | o'sha test |
| Ikkinchi hujjat (`metadata.json`) yozilishi e'lon qilinishi | ✅ **avtomatik** | o'sha test |
| Zond katalogining hamma turi yig'uvchida borligi | ✅ **avtomatik** | o'sha test |
| Zond **nishon shartnomasi** darvozasi manbada borligi | ✅ **avtomatik (faqat MANBA MATNI)** | o'sha test |
| `metadata.json` **shakli** (kalit oq ro'yxati, sanoq MATN) | ✅ **avtomatik** (BinOS tomonida) | `app/services/discovery_1c/metadata.py` |
| **1C sintaksisi** | ❌ **YO'Q** | 1C mutaxassisi, Konfigurator |
| **Kompilyatsiya** | ❌ **YO'Q** | 1C mutaxassisi |
| **Haqiqiy bazada ishlashi** | ❌ **YO'Q** | birinchi nusxa testi |
| **Natija to'plamining to'g'riligi** | ❌ **YO'Q** | birinchi nusxa testidan keyin |
| **`ВыполнитьЗонд` natijasining shakli** | ❌ **YO'Q — validator umuman yozilmagan** | — |

> ⚠️ Yuqoridagi «✅» lar faqat **MANBA MATNI** haqida. Ular modul kompilyatsiya bo'lishini,
> 1C'da yurishini yoki to'g'ri javob berishini **isbotlamaydi**.

Statik auditni mahalliy ishga tushirish:

```bash
cd apps/server && python -m pytest tests/test_discovery_1c_epf_source.py -q
```

## Runtime talablari

| Talab | Qiymat | Izoh |
|---|---|---|
| 1C:Enterprise platformasi | **8.3.x**, mijozdagi baza bilan bir xil yoki undan yangi | Aniq versiya discovery'da yoziladi |
| Rejim | **Qalin klient (толстый клиент)**, oddiy yoki boshqariladigan ilova | Fayl yozish kerak |
| **Xavfsiz rejim** | ❌ **O'CHIQ bo'lishi kerak** | Xavfsiz rejim (безопасный режим) fayl yozishni taqiqlaydi |
| Huquqlar | Metadata o'qish + `Справочник`/`Регистр` larga **o'qish** | Yozuv huquqi **KERAK EMAS** — bermang |
| Litsenziya | **ПРОФ** (Базовая emas) | Базовая tashqi qayta ishlashni ochmaydi |
| Baza | **Ajratilgan nusxa**, do'kon LAN'idagi zaxira kompyuterda | `SANDBOX_RESTORE_RUNBOOK.md` |
| Bo'sh joy | Chiqish uchun ~50 MB | Katalog hajmiga qarab |

> ⚠️ **Litsenziya chegarasi.** 1C FAQ **I.19-19**: bazani qabul qiluvchi tomonda *o'sha
> konfiguratsiyani o'z ichiga olgan* «основная поставка» litsenziyasi bo'lishi shart. Shu bois
> nusxa **do'kondan tashqariga chiqarilmaydi** — u do'konning O'Z LAN'idagi zaxira kompyuterda
> tiklanadi. Batafsil: `integrations/1c/1C_PRE_VISIT_CLEARANCE.md`.

## `.epf` ni qurish (1C mutaxassisi bajaradi)

1. **Konfigurator** ochiladi (ajratilgan nusxa bazasida).
2. `Файл → Новый → Внешняя обработка`.
3. Nom: `BinOSDiscovery`.
4. `Объект → Модуль объекта` ochiladi va `BinOSDiscovery.bsl` **to'liq** ko'chiriladi.
5. **Sintaksis tekshiruvi:** `Правка → Синтаксический контроль` (yoki `Ctrl+F7`).
   Xato chiqsa — **TO'XTANG** va xatoni bizga yuboring; o'zingiz «tuzatib» ishlatmang.
6. Forma **shart emas**: qayta ishlash `ВыполнитьРазведку()` funksiyasi orqali chaqiriladi.
   Qo'lda ishga tushirish uchun oddiy forma qo'shilsa ham bo'ladi (bitta tugma → `ВыполнитьРазведку`).
   Ikkinchi eksport funksiyasi — `ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект)`: u **ixtiyoriy** va
   faqat BinOS tomoni aniq zond so'raganda chaqiriladi (pastga qarang).
7. Saqlash: `BinOSDiscovery.epf`.

## Ishga tushirish

```
1C:Enterprise (ajratilgan NUSXA bazasi)
  → Файл → Открыть → BinOSDiscovery.epf
  → chiqish papkasini ko'rsating (BO'SH papka bo'lsin)
  → ishga tushiring
```

Yoki kod orqali:

```bsl
Обработка = ВнешниеОбработки.Создать("C:\binos\BinOSDiscovery.epf");
Результат = Обработка.ВыполнитьРазведку("C:\binos\out");
// Результат.export — `binos-1c-export-v1`, Результат.metadata — `binos-1c-metadata-v1`.
// Ikkovi ham fayl bo'lib yozilgan; qaytarilgan tuzilma faqat qulaylik uchun.
```

**Kutilayotgan davomiylik:** metadata inventarizatsiyasi soniyalar (u so'rov yubormaydi);
`КОЛИЧЕСТВО(*)` sanoqlari katalog hajmiga bog'liq — Fayzan o'lchamidagi bazada (~7k mahsulot,
~59k barkod) taxminan **1–5 daqiqa**.
⚠️ Bu **baholash**, o'lchov emas — hech qachon ishlatilmagan. Yangi kraulyer eskisiga
qaraganda **ko'proq metadata** o'qiydi (standart rekvizitlar, havola nishonlari, jadval
bo'limlari, sanab o'tilgan qiymatlar), ya'ni bu baholash ham yangilanmagan.

**Kutilayotgan chiqish — IKKI FAYL, ikkovi ham yuboriladi:**

| Fayl | Shartnoma | Nima bor |
|---|---|---|
| `out/export.json` | `binos-1c-export-v1` | platforma/konfiguratsiya versiyasi, tekis metadata sweep, `КОЛИЧЕСТВО(*)` sanoqlari, bo'lim jurnali. `candidates` — **ataylab bo'sh** (pastga qarang). |
| `out/metadata.json` | `binos-1c-metadata-v1` | konfiguratsiyada **umuman nima bor**: Справочники, Документы, РегистрыСведений, РегистрыНакопления, ПланыВидовХарактеристик, Перечисления, Константы, ОбщиеРеквизиты — har biri rekvizit/o'lchov/resurs/jadval bo'limlari, tip matni, havola nishonlari, sanab o'tilgan qiymat NOMLARI bilan. |

⚠️ **Ikkovi ham kerak.** `metadata.json` yo'q bo'lsa BinOS tomonida tahlil qiladigan narsa
qolmaydi (`export.json` o'zi bilan birorta nishonni ko'rsatmaydi). Ikkinchi faylning
yozilishi `export.json` ning bo'lim jurnalida `write_metadata` bo'lib ko'rinadi — u yerda
`failed` bo'lsa, fayl yozilmagan.

⚠️ Bu **to'plamning o'zi EMAS**. BinOS tomonidagi adapter `export.json` ni
`binos-1c-discovery-v1` to'plamiga aylantiradi (`app/services/discovery_1c/export_adapter.py`).
Vazifa ataylab bo'lingan: to'plam qoidalari murakkab (besh a'zo, kalit oq ro'yxati, holat
hisoblanishi), va ularni men sinay olmaydigan tilda qurish xatoni tekshirib bo'lmaydigan joyga
qo'yish bo'lardi.

### ⚠️ Nomzod aniqlash endi yig'uvchida EMAS

Ilgari yig'uvchi kutilgan katalog va registr **nomlarini o'zida saqlardi** va shu nomlarni
qidirardi. Ya'ni u bitta konfiguratsiya oilasiga moslangan edi: boshqa konfiguratsiyada
jimgina «hech narsa topilmadi» deb qaytarardi va bu **yolg'on xotirjamlik** bo'lardi.

U ro'yxat **olib tashlandi**. Endi:

- `export.json` da `candidates` kaliti **qoladi** (shartnoma shakli), lekin **bo'sh massiv**;
- sabab `export.json` ning `notes` bo'limida ochiq yozilgan;
- nomzod aniqlash **BinOS tomonida**, `metadata.json` ustidagi analitik qatlamda bajariladi.

⚠️ **Bu yig'uvchining qobiliyatini kamaytiradi va yashirilmaydi:** adapter hamma nishonni
`UNKNOWN` darajasi bilan yozadi, chunki yig'uvchi birorta nishon haqida hech narsa demaydi.
Dalil `metadata.json` da, qaror BinOS tomonida, tasdiq esa **odamda**.

### Zondlar (`ВыполнитьЗонд`) — ixtiyoriy, alohida qadam

Discovery tugagach aniqlanmagan joylar qolsa, BinOS tomoni **tasdiqlangan zond turini** so'raydi
(katalog: `app/services/discovery_1c/probe.py`). Operator uni qo'lda chaqiradi:

Nishon shartnomasi:

| Zond turi | `target_object` | Misol |
|---|---|---|
| `field_type_details` | **MAYDON MANZILI** | `Справочник.<Nom>.<maydon>` yoki `Справочник.<Nom>.<bo'lim>.<maydon>` |
| qolgan HAMMA turi | **OBYEKT** | `РегистрНакопления.<Nom>` |

> ⚠️ **Boshqa turga maydon manzili berilsa — XATO qaytadi.** Ilgari maydon yo'li jimgina
> tashlanardi va zond BOSHQA nishonni (butun obyektni) o'lchab, xatosiz natija qaytarardi.

> ⚠️ **QIYMATNI BSL KODI ORASIGA QO'LDA TERMANG — bu INYEKSIYA yo'li.** Ilgari bu yerdagi
> shablon zond chaqiruvini bitta satrda ko'rsatardi, ya'ni operator BinOS bergan matnni
> to'g'ridan-to'g'ri `"…"` orasiga yozardi. Matnda `"` bo'lsa u literalni **yopadi** va
> qolgan qismi KOD bo'lib qoladi. Qiymatlar endi modulning **eng boshida**, bitta joyda,
> o'zgaruvchiga olinadi va bajarishdan oldin tekshiriladi:

```bsl
// Ikki qiymat BinOS bergan zond so'rovidan AYNAN ko'chiriladi — TAHRIRLANMAYDI.
// Agar ko'chirishda Konfigurator sintaksis xatosi bersa: TO'XTANG, «tuzatmang» —
// bu qiymatda qo'shtirnoq borligini bildiradi, so'rovni bizga qaytaring.
ТипЗонда = "register_shape";                 // katalog kaliti
ЦелевойОбъект = "РегистрНакопления.<Nom>";   // metadata manzili

Если СтрНайти(ТипЗонда, """") > 0 Или СтрНайти(ЦелевойОбъект, """") > 0 Тогда
	ВызватьИсключение "Qiymatda qo'shtirnoq bor — zond bajarilmaydi, so'rovni qaytaring.";
КонецЕсли;

Результат = Обработка.ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект);
```

> ⚠️ **Bu tekshiruvning CHEGARASI (yolg'on kafolat yozilmaydi).** Qiymat baribir satr
> literaliga tushadi — qo'lda ishga tushirishning boshqa kanali yo'q. Shu bois himoya
> **ikki qatlamli va ikkovi ham to'liq emas**:
>
> 1. Qo'shtirnoq XOM ko'chirilsa — modul **kompilyatsiya bo'lmaydi** (fail-closed), lekin
>    xato Konfiguratorda chiqadi, shu bois operator uni «tuzatib» qo'ymasligi SHART.
> 2. Qo'shtirnoq `""` shaklida ekranlangan bo'lsa — kod kompilyatsiya bo'ladi, ammo
>    yuqoridagi `СтрНайти` tekshiruvi zondni bajarmaydi.
>
> Ikkovi ham operatorning qiymatni **tahrirlamasligiga** tayanadi. Modul ichida esa
> kelgan matn so'rovga TUSHMAYDI (pastga qarang) — asosiy himoya shu.

⚠️ **AI dan kelgan matn kod sifatida bajarilmaydi.** `ВыполнитьЗонд` faqat katalogdagi
turlarni biladi (`Если`/`ИначеЕсли`), noma'lum tur kelsa xato qaytaradi. So'rov jadvalining nomi
metadata obyektining **o'zidan** (`ПолноеИмя()`) olinadi, kelgan matndan emas. Dinamik kod
bajarish (`Выполнить`/`Вычислить`) modulda **yo'q** va statik audit buni majburlaydi.

⚠️ Zond **hech narsa yozmaydi** — na bazaga, na diskka: natijani qaytaradi, faylni operator
saqlaydi. Natijaning **shakli hali shartnoma emas** (BinOS tomonida uni tekshiradigan validator
yo'q), shuning uchun unga tayanib kod yozilmasin.

```bash
# BinOS tomonida (nusxa emas, ishchi mashinada):
cd apps/server && python -c "
import json, pathlib
from app.services.discovery_1c import export_adapter as A
from app.services.discovery_1c import bundle as B
exp = json.loads(pathlib.Path('export.json').read_text(encoding='utf-8'))
members = A.to_bundle_members(exp, source_kind='copy')   # 'copy' — OPERATOR e'loni
print(B.content_hash(B.load_members(members)))
"
```

⚠️ `source_kind='copy'` — buni **operator** aytadi, yig'uvchi emas: qayta ishlash o'zi nusxada
ishlayotganini bila olmaydi.

## Xavfsizlik shartnomasi

Yig'uvchi quyidagilarni **hech qachon** chaqirmaydi (statik audit majburlaydi):

`Записать()` · `ЗаписатьНаборЗаписей()` · `Провести()` · `ОтменитьПроведение()` · `Удалить()` ·
`УдалитьОбъекты()` · `УстановитьМонопольныйРежим()` · `УстановитьПривилегированныйРежим()` ·
`НачатьТранзакцию()` · `ЗафиксироватьТранзакцию()` · `ОтменитьТранзакцию()` ·
`ВыполнитьОбработкуЗаполнения()` · dinamik `Выполнить()` / `Вычислить()` ·
`ОбменСВесами` / `ВыгрузитьВВесы` / `ЗаписатьPLU` · `COMОбъект`.

⚠️ Bu ro'yxat **manba matni** haqida: audit shu chaqiruvlar manbada YO'Q ekanini tekshiradi.
U modul ishlaganda nima qilishini **isbotlamaydi**.

Yangi kraulyer va zond yuzasi bilan **15 yangi qoida** qo'shildi (yig'uvchining fayl, kod va
baza yuzasi kengaygani uchun):

`ПолучитьCOMОбъект()` · `ЗапуститьПриложение()` · `КопироватьФайл()` · `ПереместитьФайл()` ·
`УдалитьФайлы()` · `СоздатьКаталог()` · `ЗначениеВФайл()` ·
`ВычислитьВБезопасномРежиме` / `ВыполнитьВБезопасномРежиме` · `ВнешниеОбработки.` /
`ВнешниеОтчеты.` · **yozuvchi obyektlar sinfi** (`ЗаписьТекста`, `ЗаписьДанных`, `ЗаписьXML`,
`ЗаписатьXML`, `ЗаписьZipФайла`, `ЗаписьHTML`, `ЗаписьFastInfoset`) ·
`Константы.<Nom>.Установить()` / `.СоздатьМенеджерЗначения()` ·
`Хранилище…Настроек.Сохранить()` · `ЗарегистрироватьИзменения()` /
`УдалитьРегистрациюИзменений()` · `Запрос.Текст` ni **bo'sh bo'lmagan literal bilan
boshlamaslik** · `Запрос.Текст` ga **oq ro'yxatdan tashqari** o'zgaruvchi qo'shmaslik.

> ⚠️ `ЗаписьJSON` / `ЗаписатьJSON` **taqiqlanmagan** — eksport aynan ular bilan yoziladi.
> Qolgan yozuvchi obyektlar taqiqlangan: ikkinchi yozish kanali nazoratdan chiqqan chiqish
> yo'li bo'lardi. Ikki test qulflaydi: buzuq satr tutiladi, JSON yozuvchisi tutilmaydi.
>
> ⚠️ `Константы` qoidasi AYNAN shu bosqichda kerak bo'ldi: yig'uvchi konstantalar
> kolleksiyasini kezishni shu bosqichda **boshladi**, ya'ni teshik YANGI ochilgan yuzada edi.
> O'qish (`.Получить()`) va metadata kezish (`Метаданные.Константы`) tutilmaydi.
>
> ⚠️ **So'rov matni qoidalari eng nozigi — va ularning CHEGARASI bor.** Ikki qoida ishlaydi:
> (1) matn **bo'sh bo'lmagan literal** bilan boshlanishi shart (`= "" + X` o'tmaydi);
> (2) unga `+` bilan qo'shiladigan o'zgaruvchi `epf_audit.py` dagi `QUERY_CONCAT_ALLOWED`
> oq ro'yxatida bo'lishi shart. Ikkinchi qoida **o'zgaruvchi xavfsizligini tekshirmaydi**:
> `+ ПолноеИмя` va `+ ТекстОтМодели` statik matn sifatida **farq qilmaydi**. U faqat oq
> ro'yxatni QULFLAYDI — yangi konkatenatsiya manbasi qo'shish uchun `epf_audit.py` ni
> tahrirlash SHART, ya'ni u ko'riksiz kirib kelmaydi.
>
> ⚠️ **HAQIQIY himoya statik auditda EMAS:** jadval nomi
> `Метаданные.НайтиПоПолномуИмени(...)` topgan obyektning O'Z `ПолноеИмя()` sidan olinadi,
> kelgan matndan emas. Audit buni **isbotlamaydi** — u faqat manbada shunday yozilganini
> tekshiradi.
>
> ⚠️ Ko'p satrga bo'lingan tayinlash (`Запрос.Текст =` satr oxirida, matn keyingi satrda) va
> 1C dagi `=` ning **taqqoslash** ma'nosi (`Если Поле.Текст = ИмяПоля Тогда`) ilgari YOLG'ON
> tutilardi — ikkovi uchun ham test bor.
>
> ⚠️ `ВычислитьВБезопасномРежиме` alohida qoida bo'lishi kerak edi: eski `Вычислить(` qoidasi
> uni **tutmaydi** (nomdan keyin `(` emas, `В` keladi). Bu haqiqiy teshik edi.

> ⚠️ **«Выгрузить в весы» HECH QACHON bosilmaydi** — 1C birinchi yuklashda yangi PLU'larni o'z
> registriga **yozishi** mumkin. Bu o'qish emas, yozuv amali.

## Ma'lumotni minimallashtirish

Bu versiya **faqat metadata va sanoq** oladi:

| Olinadi | Olinmaydi |
|---|---|
| Obyekt/rekvizit **nomlari**, sinonimlari va izohlari | Mahsulot nomlari |
| Tip tavsifi (razryadlik, kasr xona, uzunlik) | Narxlar, qoldiqlar |
| Havola nishonlari (qaysi maydon kimga havola qiladi) | Mijoz, ta'minotchi, xodim ma'lumotlari |
| Sanab o'tilgan qiymatlarning **nomlari** (`Имя`) | Ularning `Наименование` va `Код` i |
| Oldindan belgilangan elementlarning **nomlari** (`Имя`) | Hujjat qatorlari, summalar |
| `КОЛИЧЕСТВО(*)` sanoqlari (faqat `export.json`) | Barkod va PLU **qiymatlari** |
| Platforma/konfiguratsiya versiyasi | Nishon nomzodlari — **yig'uvchi ularni umuman chiqarmaydi** |

⚠️ `metadata.json` **so'rov yubormaydi**: `row_count` u yerda ataylab bo'sh. Sanoqlar faqat
`export.json` da va (so'ralsa) `row_count` zondida.

⚠️ `ПланыСчетов` **olinmaydi**: `binos-1c-metadata-v1` lug'atida hisob rejasi uchun `kind`
qiymati yo'q, boshqa `kind` bilan yozish esa hujjatni o'qiganni chalg'itardi. Jimgina o'tib
ketilmaydi — bo'lim jurnalida `chart_of_accounts` sababi bilan `skipped` bo'lib qoladi.

⚠️ `ОбщийРеквизит` ning **Состав** (qaysi obyektlarga ulangani) `metadata.json` shaklida yo'q —
u `common_attributes` zondi bilan olinadi. Bu **qobiliyat chegarasi**, yashirilmaydi.

Biznes ma'lumotini ko'chirish — **alohida, keyingi qadam**, alohida ruxsat bilan.

## Chiqishni yuborishdan oldin

`export.json` va ayniqsa `metadata.json` **konfiguratsiya tuzilmasini to'liq** ochib beradi
(obyekt, rekvizit va jadval bo'limi nomlari, izohlar, havola zanjirlari). Yuborishdan oldin
mijoz ikkovini ham ko'rib chiqsin. BinOS tomonida `redact.py` sirlarni (ulanish satri, parol,
token, e-pochta, telefon) qidiradi va **topilsa hujjatni RAD etadi** (`metadata.json` uchun ham:
`validate_metadata` ichida) — lekin bu ikkinchi qator himoya, birinchisi odam ko'rigi.

⚠️ `Комментарий` maydonlari ham chiqadi. Konfiguratsiya izohida operator qoldirgan matn
(masalan kirish ma'lumotlari) bo'lishi mumkin — shuning uchun `redact.py` ni aylanib o'tmang va
mijoz ko'rigini o'tkazib yubormang.
