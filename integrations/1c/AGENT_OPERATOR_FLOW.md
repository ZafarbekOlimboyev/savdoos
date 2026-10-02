# AGENT OPERATOR OQIMI — `BinOSDiscoveryAgent` ni kim, qanday va qaysi papkada yurgizadi

Bu hujjat OPERATOR uchun. U bitta savolga javob beradi: **agent nima qiladi, operator nima
qiladi va natija qanday ko'rinishi kerak.** Hujjatda birorta runtime da'vosi yo'q — faqat
kodda majburlangan narsalar yoziladi.

---

## 0. AVVAL O'QING: paketli yo'l (`batch_execute`) BUGUN ISHLATILMAYDI

Agentda ikki marshrut bor va ikkisining nomi kodda AYNAN shunday yoziladi:

| marshrut | kim 1C ni ishga tushiradi | bugungi holati |
|---|---|---|
| `batch_execute` | AGENT (`1cv8.exe` ni paketli rejimda) | **BUGUN FOYDALANIB BO'LMAYDI** — pastdagi uchta bo'shliq |
| `watch_folder` | **OPERATOR** (o'z 1C sessiyasida) | MVP da ishlatiladigan YAGONA marshrut |

### Nega `batch_execute` bugun foydalanib bo'lmaydi — UCHTA BO'SHLIQ

1. **Repoda `.epf` konteyneri YO'Q.** Yig'uvchi manba kodi bor
   (`integrations/1c/extractor/BinOSDiscovery.bsl`), lekin Konfiguratorda yig'ilgan `.epf`
   fayli repoda umuman mavjud emas. Paketli rejim esa aynan BAJARILADIGAN FAYLNI talab
   qiladi, manbani emas.
2. **BSL BO'SHLIG'I: paketli ishga tushirish parametrini o'qiydigan kirish nuqtasi yo'q.**
   Yig'uvchining eksport funksiyasi `ВыполнитьРазведку` chiqish papkasini **argument** bilan
   talab qiladi. Paketli rejim argument uzatmaydi — u faqat `/C` satrini qoldiradi, va uni
   BSL tomonida o'qish uchun `ПараметрЗапуска` ni ko'radigan argumentsiz kirish nuqtasi
   kerak. Manbada bunday kirish nuqtasi **YO'Q**.
3. **Aniqlovchi birorta bazani «tasdiq talab qilmaydi» deb isbotlay olmaydi.** Parolsiz
   kirishni ULANMASDAN isbotlab bo'lmaydi, shu bois `requires_auth` hech qachon `"false"`
   bo'lmaydi va paketli darvoza fail-closed tomonda yopiq turadi. (Agent parolni buyruq
   satriga HECH QACHON qo'ymaydi: u jarayon ro'yxatida ko'rinib qoladi.)

⚠️ Shu uchta bo'shliq **bugungi qobiliyat chegarasi**, vaqtinchalik nosozlik emas. Ularning
birortasi yopilgandan keyin ham `batch_execute` ning 1C dagi xulqi `RUNTIME-UNKNOWN` bo'lib
qoladi: bu mashinada 1C:Enterprise YO'Q (`1cv8.exe` yo'q, `V83.COMConnector` ro'yxatda yo'q,
`pywin32` yo'q), demak u yo'l birorta haqiqiy o'rnatmaga qarshi tekshirib bo'lmagan.

⚠️ **Bu hujjat avtomatlashtirilgan «bir bosish» oqimini TAKLIF QILMAYDI va agentda bunday
oqim yo'q.**
Agent bitta tugmani ko'rsatadi, lekin shu tugma ortida 1C ni OPERATOR ishga tushiradi.

### Agent buni YASHIRMAYDI

`watch_folder` yo'lida har yurishda quyidagilar yoziladi:

- `agent_status.json` → `route` = `watch_folder`;
- `agent_status.json` → `errors` ichida `BATCH_EXECUTE_NOT_ATTEMPTED` kodi va uchta
  bo'shliqni sanab o'tgan sabab;
- `agent_status.json` → `notes` ichida operatorning to'rtta qadami (shu hujjatdagi bilan AYNI
  matn);
- `discovery_report.md` → «Yo'l va operator aralashuvi» bo'limi: qaysi yo'l, operator
  aralashuvi bo'ldimi, `batch_execute` nega ishlatilmadi.

Hisobot `watch_folder` yo'lida odamning ishini agentga yozib qo'yadigan — ya'ni
«avtomatik» ma'nosini beradigan — iborani chiqara olmaydi: bunday ibora topilsa hisobot
UMUMAN yozilmaydi (fail-closed darvoza).

---

## 1. OQIM: kim nima qiladi

| # | KIM | NIMA QILADI |
|---|---|---|
| 1 | OPERATOR | Natija papkasi uchun joy tanlaydi va yig'uvchi yozadigan **kuzatiladigan papkani** ko'rsatadi (`--headless <papka>` yoki oynadagi tanlov). |
| 2 | AGENT | Muhitni skanerlaydi (FAQAT O'QISH: reestr, fayl tizimi, `PATH`) va `environment.json` ni yozadi. 1C ga ULANMAYDI. |
| 3 | AGENT | Marshrutni tanlaydi. Yig'uvchi `.epf` berilmagan bo'lsa — `watch_folder`, va `batch_execute` nega urinilmagani yozuvga tushadi. |
| 4 | OPERATOR | 1C ni O'ZI ochadi va kerakli bazaga kiradi. Kirish oynasini 1C ning O'ZI ko'rsatadi; agent u oynani ko'rmaydi va parolni bilmaydi. |
| 5 | OPERATOR | Faqat-o'qish yig'uvchisini ishga tushiradi: `ВыполнитьРазведку(<chiqish papkasi>)`. Chiqish papkasi — 1-qadamda agentga ko'rsatilgan AYNI papka. |
| 6 | AGENT | Papkani kuzatadi: `manifest.json` paydo bo'lishini VA to'liq yozilishini kutadi. Kutish ekranda ko'rinadi. |
| 7 | AGENT | Paketni tekshiradi (Phase 4 validatori), grafni quradi, deterministik lokal tahlilni yurgizadi va natija papkasini yozadi. |
| 8 | OPERATOR | Natija papkasini ochib `discovery_report.md` ni o'qiydi. |

⚠️ 4- va 5-qadamlarni agent BAJARA OLMAYDI va bajarishga urinmaydi. Agent 1C ga ulanmaydi,
COM obyekti ochmaydi, o'zboshimcha BSL bajarmaydi va hech narsa yozmaydi.

⚠️ 6-QADAMNING ANIQ CHEGARASI: agent FAQAT tugallanish belgisini o'lchaydi — `manifest.json`
bor, JSON bo'lib o'qiladi va hajmi barqarorlashgan. Chiqishning MAZMUNI to'liqmi degan
savolga 7-qadamdagi validator javob beradi. Shu bois tugallangan, lekin to'liq bo'lmagan
chiqish «vaqt tugadi» deb emas, `FAILED_VALIDATION` deb nomlanadi va buzuq paket `bundle/`
ichida DALIL bo'lib saqlanadi — kutish uni tuzatmaydi.

---

## 2. QAYSI FAYL, QAYSI PAPKA

### Yig'uvchi (operator ishga tushiradigan narsa)

- **Manba:** `integrations/1c/extractor/BinOSDiscovery.bsl`
- **Chaqiriladigan eksport funksiya:** `ВыполнитьРазведку(КаталогВыгрузки)` —
  bitta argument: chiqish papkasi.
- **Rejim:** metadata-only. Bu DEFAULT va agent boshqa rejimni so'ramaydi: zond faqat
  operatorning ALOHIDA tasdig'idan keyin bo'ladi.
- ⚠️ Tayyor `.epf` repoda YO'Q — yig'uvchi Konfiguratorda yig'iladi. Uning sintaksisi
  Konfiguratorda tekshirilmagan.

### Kuzatiladigan papka (yig'uvchi YOZADIGAN joy)

Bu papkani OPERATOR tanlaydi va AYNI papkani ikki joyda ko'rsatadi: agentga (1-qadam) va
yig'uvchiga (5-qadam). **Har yurish uchun TOZA papka tanlang.**

⚠️ Nega toza papka: agent paketning AYNI SHU YURISH uchun yozilganini ISBOTLAY OLMAYDI —
jarayon uning qo'lida emas, chiqish kodi ham yo'q. Papkada oldingi yurishdan qolgan paket
turgan bo'lsa, agent uni shu yurishning natijasi deb o'qiydi va hisobotda shu ogohlantirish
yoziladi.

### Natija papkasi (AGENT yozadigan joy)

`binos-discovery-<vaqt>/` nomli papka, ichida:

| fayl | nima |
|---|---|
| `agent_status.json` | yurish yozuvi: holat, marshrut, o'tishlar, xatolar, izohlar |
| `environment.json` | muhit skaneri: 1C mavjudligi hukmi, o'rnatmalar, bazalar |
| `errors.json` | yurishning xatolari alohida hujjat sifatida |
| `agent_manifest.json` | butun papkaning sha256 manifesti |
| `discovery_ai_candidates.json` | tahlil nomzodlari (tahlil bajarilgan bo'lsa) |
| `discovery_report.md` | odam o'qiydigan hisobot — TAXMINLAR ro'yxati |
| `bundle/` | yig'uvchi chiqargan Phase 4 paketi, BAYT-BA-BAYT o'zgarmagan |

⚠️ `bundle/` ichidagi `manifest.json` va `errors.json` — Phase 4 ning O'Z hujjatlari.
Ildizdagi `errors.json` esa AGENTNING hujjati: ular IKKI XIL sxema va versiya satri bilan
ajraladi. Agentning manifesti ataylab `agent_manifest.json` deb ataladi, `manifest.json` emas.

---

## 3. NIMA KO'RINISHI KERAK

Agent ekranda (oyna yoki `--headless` chiqishi) quyidagilarni ko'rsatadi:

1. `READ ONLY` yorlig'i — agentning yagona rejimi;
2. aniqlangan 1C qatori va nishon baza qatori (mahalliy YO'L ko'rsatilmaydi — u sir);
3. **marshrut qatori:** `watch_folder` bo'lsa, u «yig'uvchini OPERATOR ishga tushiradi, agent
   1C ni ishga tushirmaydi» deb AYNAN aytadi;
4. operatorning to'rtta qadami;
5. progress: holat nomi (`ENVIRONMENT_SCAN` → `TARGET_SELECTION` → `SAFETY_CHECK` →
   `METADATA_DISCOVERY` → `VALIDATION` → `GRAPH_BUILD` → `ANALYSIS` → `REPORT` →
   `COMPLETE`);
6. **kutish qatori:** papka hali tayyor bo'lmasa, «kutilmoqda…» qatori yangilanadi va o'tgan
   vaqtni ko'rsatadi. Bu qator ko'rinib turgani — agent osilmagani.

Yurish muvaffaqiyatli tugaganda: holat `COMPLETE`, natija papkasi yozilgan va tekshiruvdan
o'tgan, `discovery_report.md` o'qishga tayyor.

---

## 4. NIMADIR BOSHQACHA BO'LSA

Har bir holat ANIQ nom oladi va hisobot «NIMA bo'ldi + KEYINGI QADAM» ni yozadi. Umumiy
«xato» holati YO'Q.

| ko'rganingiz | holat | nima qilish |
|---|---|---|
| kutish qatori uzoq turdi, so'ng yurish to'xtadi | `FAILED_TIMEOUT` | Yig'uvchi oxirigacha bajarilmagan. 1C band bo'lmagan paytda qayta yurgizing; `--wait-seconds` bilan chegarani oshirishingiz mumkin. Cheksiz kutish YO'Q. |
| «kuzatiladigan papka ko'rsatilmadi yoki topilmadi» | `FAILED_COLLECTOR_UNAVAILABLE` | Papka yo'lini tekshirib qayta ko'rsating. Bu 1C bor-yo'qligi haqida HECH NARSA demaydi. |
| «kuzatiladigan papka O'QILMADI» | `FAILED_COLLECTOR_UNAVAILABLE` | Papkaga kirish huquqini tekshiring. «O'qilmadi» «bo'sh» DEGANI EMAS. |
| «1C:Enterprise O'RNATILMAGAN (hamma manba o'qildi)» | `FAILED_NO_1C`, `presence_verdict` = `absent` | Bu JAVOB. 1C o'rnatilgan kompyuterda yurgizing. |
| «1C holatini ANIQLAB BO'LMADI» | `FAILED_NO_1C`, `presence_verdict` = `unknown` | Bu JAVOB EMAS: manbalardan biri o'qilmadi. Agentni 1C ni ko'ra oladigan hisobdan yurgizing. «O'rnatilmagan» degan xulosa CHIQARILMAYDI. |
| paket tekshiruvdan o'tmadi | `FAILED_VALIDATION` | Tahlil QILINMADI va bu ATAYLAB: noto'g'ri paketdan chiqarilgan xulosa noto'g'ri bo'ladi. Paketni qayta yig'ing, validator xabarini o'zgartirmasdan saqlang. |
| yurish `FAILED_INTERNAL` berdi | `FAILED_INTERNAL` | Bu agentning NUQSONI, muhit muammosi emas. Natija papkasini butunlay (hisoboti bilan) saqlab, ishlab chiquvchiga uzating — ichida sir yo'q. |
| hisobotda odamning ishi agentga yozilgan | — | Buni ishlab chiquvchiga xabar qiling: `watch_folder` yo'lida bu ibora chiqmasligi kerak va darvoza uni to'sadi. |

⚠️ Hech bir holatda agent hech narsani o'zgartirmaydi: yozish, o'tkazish, o'chirish va
o'zboshimcha kod bajarish yo'li bu quvurda umuman mavjud emas.

---

## 5. HISOBOTNI QANDAY O'QISH

`discovery_report.md` — **TAXMINLAR ro'yxati, xarita emas.** Uning boshidagi ogohlantirish
olib tashlanmaydi:

- hech bir qatori tasdiqlanmagan va ko'chirishga ruxsat bermaydi;
- eng yuqori avtomat daraja — `CANDIDATE`; `HUMAN_CONFIRMED` FAQAT operatorning alohida
  tasdiq hujjatidan keladi;
- tahlil deterministik va lokal: tarmoq chaqiruvi YO'Q va tashqi (bulutli) model chaqirilmaydi; do'konning ma'lumoti
  hech qayerga yuborilmadi;
- `UNKNOWN` konseptlar ro'yxati O'CHIRILMAYDI: «qaralmadi» va «yo'q» bir xil narsa emas.

⚠️ `watch_folder` yo'lida hisobot yana bitta narsani aytadi: AYNI SHU YURISH yig'uvchining
BIRINCHI HAQIQIY sinovi, chunki undan oldin u birorta haqiqiy 1C da bajarilmagan.
