# Fayzan 1C → BinOS cutover — runbook QORALAMASI

**Holat: QORALAMA.** Do'kondagi 1C konfiguratsiyasi (nomi, versiyasi, platforma versiyasi) hali NOMA'LUM.
Shu sababli bu hujjatda birorta ham `Регистр`, `Справочник` yoki so'rov matni yozilmagan — ular discovery
javobidan keyin qo'shiladi. Konfiguratsiyani taxmin qilish (Розница 2 / УТ 11 / УНФ / Розница 3) TAQIQLANGAN:
mavjud 2026-08 eksport fayllarining hisobot sarlavhalari Розница va УТ da bir xil, ya'ni ular konfiguratsiyani
ANIQLAMAYDI (`integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md:376`).

Bog'liq hujjatlar (TAKRORLANMAYDI, faqat ishora qilinadi):

| Hujjat | Nima uchun |
|---|---|
| `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` | 8 savollik so'rovnoma + skrinshot gigiyenasi + 1C ga tegmaslik qoidalari |
| `integrations/1c/BINOS_1C_BUNDLE_V1.md` | `binos-1c-v1` fayl shartnomasi |
| `integrations/1c/MIGRATOR_V1_RUNBOOK.md` | migrator CLI bosqichlari, himoyalar, siyosatlar |
| `docs/FAYZAN_1C_DISCOVERY.md` | discovery bajarish yo'riqnomasi |
| `docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md` | bo'sh natija shabloni |

---

## 0. Butun cutover uchun qat'iy qoidalar

1. **Yo'nalish faqat 1C → BinOS, bir martalik.** BinOS 1C'ga HECH QACHON yozmaydi
   (`apps/server/app/services/migrator_1c/__init__.py:2-4`). Bu doimiy sinxronizatsiya emas.
2. **1C ga yozadigan bosqich YO'Q.** Quyidagi 13 bosqichning hammasida 1C ustuni «yo'q». Bu — DA'VO emas,
   ikki joyda ISBOT talab qiladigan shart: 2-bosqichda `.dt` chiqarishning shartlari (monopol rejim, seans
   uzish) baza holatiga tegishi mumkin va ularni faqat do'kon administratori qiladi; 3-bosqichdagi `.epf`
   esa 5 shartli darvozadan o'tmaguncha do'kondagi 1C'da ochilmaydi. Shu ikki joydan tashqari 1C'ga hech
   kim, hech qachon tegmaydi.
3. **BinOS'ga yozadigan bosqich faqat 2 ta:** 11 (APPLY) va 13 (BinOS truth). 1–10 va 12-bosqichlar
   BinOS'ga ham hech narsa yozmaydi.
4. ⚠️ **1C'da hech qachon bosilmaydi:** «Выгрузить данные», «Загрузить», «Очистить», «Заполнить»,
   «Перенумеровать»; «Конфигуратор» da «Загрузить информационную базу…», «Обновить конфигурацию базы данных»,
   «Снять с поддержки», «Тестирование и исправление…». «Сохранить изменения?» savoliga har doim «Нет»
   (`FAYZAN_1C_DISCOVERY_CHECKLIST.md:63-77`).
5. ⚠️ **Ommaviy YOZADIGAN tugmalar — 2 va 9-bosqichlarda ham qat'iy taqiqlangan.** Discovery so'rovnomasi
   bularni sanamaydi, chunki u paytda baza admin huquqi bilan ochilmaydi; cutover kunlarida esa ochiladi.
   Menyu yo'li konfiguratsiyaga bog'liq, shuning uchun faqat TUGMA NOMLARI beriladi `(экранда tekshirilsin)`:
   «Удалить помеченные объекты», «Групповое изменение реквизитов», «Групповая обработка справочников и
   документов», «Синхронизация данных» / «Обмен данными» ichidagi «Выполнить», hujjat formasidagi «Провести»
   va «Отменить проведение», «Восстановление последовательности», «Закрытие месяца».
   Bular bitta tasdiq bilan minglab qatorni o'zgartiradi va **`.dt` nusxa bo'lsa ham qaytarib bo'lmaydi** —
   nusxani ishchi bazaga qaytarish «Загрузить информационную базу…» demakdir, u esa 4-qoida bilan taqiqlangan.
6. **Tasdiqlanmagan menyu yo'li** `(экранда tekshirilsin)` belgisi bilan yuriladi. Belgisiz yo'l — checklist'da
   tasdiqlangan yo'l.
7. **Ulanish satri faqat `DATABASE_URL` muhit o'zgaruvchisidan olinadi va hech qachon chop etilmaydi**
   (`apps/server/app/tools/migrate_1c.py:30-37`). Production `DATABASE_URL` chatga, logga, skrinshotga,
   hisobot fayliga yoki repoga TUSHMAYDI.
8. 🔒 **Maxfiy ma'lumot — BinOS tomoni ko'rmaydi va yozib olmaydi.** Bu qoida discovery'da ham, cutover
   kunida ham amal qiladi (manba: `FAYZAN_1C_DISCOVERY_CHECKLIST.md:84-90` — yashiriladigan/yashirilmaydigan
   ro'yxat; parol og'zaki qoidasi: `:94`).

   | Nima | Qoida |
   |---|---|
   | 1C foydalanuvchi/administrator paroli | Do'kon xodimi O'ZI kiritadi. Dasturchi parolni **so'ramaydi, eshitmaydi, yozmaydi**; parol aytilib yuborilsa — u zudlik bilan almashtiriladi |
   | Litsenziya raqami, ПИН, dasturiy himoya kaliti raqami | Skrinshotdan qora to'rtburchak bilan berkitiladi |
   | AnyDesk / masofadan kirish ID va paroli | Faqat telefon orqali, faqat egasining o'zi ishga tushiradi, sessiya oxirida yopiladi; ID hech qayerda saqlanmaydi |
   | Odamlarning telefoni, e-mail'i, bank rekvizitlari, karta raqami | Skrinshotga tushsa — berkitiladi yoki kadr qayta olinadi |
   | Xodim ismlari («Активные пользователи», `approved_by`) | Faqat cutover hujjatida, boshqa hech qayerda tarqatilmaydi |

   Berkitish usuli: Paint → to'ldirilgan qora to'rtburchak. **Marker va blur yaramaydi** — ular orqali o'qiladi
   (checklist:86-87). BERKITILMAYDI: tovar nomlari, narxlar, omborlar, 1C versiyasi, `File=`/`Srvr=`/`ws=` satri
   (checklist:90).
9. 🔒 **Nusxa va hosila fayllar — maxfiylik va yo'q qilish.** `.dt` nusxada do'konning BARCHA ma'lumoti bor
   (yetkazib beruvchilar, xodimlar, xaridorlar, kassa, bank rekvizitlari — checklist:199-200). Hosila fayllar
   (`report.json`, `plan.json`, `summary.txt`, `mapping.json`, astatka/sena/Список9 hisobotlari) do'konning
   to'liq katalogi, narxi va qoldig'i, ya'ni **tijorat siri**.

   - Faqat internetsiz kompyuterda ochiladi, hech kimga uzatilmaydi (checklist:207-208).
   - Telegram / e-mail / bulut orqali yuborilmaydi; topshirish — qo'ldan-qo'lga.
   - **Repoga commit qilinmaydi** va chatga/ticketga yopishtirilmaydi; `docs/` ga faqat SHU hujjatlar kiradi.
   - Ish tugagach nusxa ham, hosila fayllar ham o'chiriladi va o'chirilgani egasiga YOZMA tasdiqlanadi.
     Yo'q qilish sanasi yozma rozilikda oldindan ko'rsatiladi (checklist:202-204).
10. 👤 **Javobgarlik BinOS tomonida.** Do'kon xodimi (kassir, administrator) — bajaruvchi emas, kuzatuvchi
    va ruxsat beruvchi. Xodim tasodifan biror tugmani bosib yuborsa **u aybdor emas**: sessiya to'xtatiladi,
    hech narsa o'zi tuzatilmaydi, hodisa yozib qo'yiladi va egasiga aytiladi. Har bir bosqichda «Kim» ustuni
    ishni KIM boshlashini ko'rsatadi; noaniq qolgan joyda ish BOSHLANMAYDI.

> Ruscha: Мы ничего не меняем в вашей 1С — только читаем данные и делаем скриншоты. Перенос идёт в одну
> сторону: из 1С в BinOS. Обратно BinOS в 1С не пишет никогда.

---

## 1. Bosqichlar — umumiy jadval

| # | Bosqich | Kim | Buyruq | Yozadimi (1C / BinOS) | Davomiylik |
|---|---|---|---|---|---|
| 1 | discovery | operator + do'kon admin | — | yo'q / yo'q | 24 daq (nusxa bor) – 32 daq (nusxa yo'q), sof ish vaqti |
| 2 | database copy | do'kon administratori | 1C Konfigurator | yo'q / yo'q | 30–60 daq (do'kon yopiq) |
| 3 | read-only extraction | dasturchi + do'kon admin | **HALI YO'Q** | yo'q / yo'q | o'lchanmagan |
| 4 | bundle validation | dasturchi | `verify-bundle` | yo'q / yo'q | < 1 daq |
| 5 | dry-run | dasturchi | `dry-run` | yo'q / yo'q | 1–5 daq |
| 6 | GUID mapping | dasturchi | `mapping-template` | yo'q / yo'q | < 1 daq |
| 7 | conflicts | operator (qaror) + dasturchi | `plan` | yo'q / yo'q | soatlar–kunlar |
| 8 | totals reconciliation | dasturchi + do'kon admin | `plan` + `apply --rehearse` | yo'q / yo'q (rollback) | 15–60 daq |
| 9 | final fresh snapshot | do'kon admin + dasturchi | 3–8 qayta | yo'q / yo'q | 30–90 daq |
| 10 | short freeze | do'kon egasi e'lon qiladi | — | yo'q / yo'q | 9+11+12 yig'indisi |
| 11 | APPLY | dasturchi (yozma ruxsat bilan) | `apply --commit` | yo'q / **HA** | 1–10 daq |
| 12 | post-apply verify | dasturchi | `verify-applied` | yo'q / yo'q | < 5 daq |
| 13 | BinOS truth | operator (`sozlamalar.edit`) | `/catalog/v2/cutover-complete` | yo'q / **HA** | < 5 daq |

Barcha CLI buyruqlari `apps/server` ichidan: `python -m app.tools.migrate_1c <buyruq> …`
(`apps/server/app/tools/migrate_1c.py:241-272` — jami 6 ta buyruq).

---

## Bosqich 1 — discovery

| Maydon | Qiymat |
|---|---|
| Maqsad | Do'kondagi 1C haqidagi 8 savolga hujjatli javob olish va konfiguratsiyani «О программе» dan ANIQLASH. |
| Kim | Operator (do'konda) + do'kon administratori (admin savollari) |
| Kirish | `docs/FAYZAN_1C_DISCOVERY.md`, bo'sh natija shabloni, 32 GB tashuvchi, qabul qiluvchining ismi/raqami |
| Chiqish | To'ldirilgan natija shabloni + raqamlangan skrinshotlar + 2–3 real tarozi etiketkasi fotosi |
| Buyruq | — (do'konda qo'lda) |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | **24 daq** (baza nusxasi beriladi) – **32 daq** (nusxa yo'q) sof ish vaqti; kutish va yo'l kirmaydi. Bandlar bo'yicha taqsimot va qisqartirish tartibi: `docs/FAYZAN_1C_DISCOVERY.md`, 2-bo'lim. 8-savol (tarozi + etiketka fotosi) eng uzun band va **hech qachon qisqartirilmaydi** |

⚖️ **Tarozi etiketkasi kontrakti — MA'LUM, shu bosqichda TASDIQLANADI.** Fayzan do'konidan olingan 4 ta real
etiketka formatni ANIQ ko'rsatdi: `27` + PLU(5) + GRAMM(5) + EAN-13 nazorat(1) = 13 raqam. Kod shu qoidaga
keltirildi (`packages/shared/src/lib/scaleBarcode.ts:87`, `apps/server/app/services/scale_barcode.py:98`;
real vektorlar: `tests/fixtures/scale_barcodes.json`). Shuning uchun 8-savoldagi etiketka fotosining maqsadi
endi formatni ANIQLASH emas — **do'kondagi AYNI tarozi AYNI shu kontraktda bosishini TASDIQLASH**: boshqa
tarozi (yoki boshqa sozlama) boshqacha bosishi mumkin, shuning uchun band saqlanadi.

**STOP shartlari**

- 1-savol («О программе»: platforma versiyasi, konfiguratsiya nomi va versiyasi) javobsiz — **butun quvur
  to'xtaydi**: bu uch maydon bundle'da MAJBURIY va bo'sh bo'lsa fayl butunlay rad etiladi
  (`apps/server/app/services/migrator_1c/bundle.py:160-162`).
- 8-savol etiketka fotosi yo'q — do'kon tarozisining yuqoridagi kontraktda bosishi TASDIQLANMAGAN bo'ladi;
  3-bosqichda `plu` ustuni yozilmaydi.
- ⚠️ Xodim taqiqlangan tugmalardan birini bosib yuborsa — sessiya to'xtatiladi, administratorga aytiladi,
  hech narsa o'zi tuzatilmaydi. **Xodim aybdor emas** (0-bo'lim, 10-qoida): hodisa natija shabloniga
  yoziladi, kim bosgani emas, NIMA bosilgani muhim.

**Rollback:** kerak emas — hech narsa o'zgarmagan. Javob to'liq bo'lmasa: ikkinchi tashrif rejalashtiriladi.

> Ruscha: Если вы не знаете ответ — так и напишите «не знаю» и укажите, кто может знать. Не угадывайте.

---

## Bosqich 2 — database copy

| Maydon | Qiymat |
|---|---|
| Maqsad | Ichki jadval/registr nomlarini TAXMINSIZ o'qish uchun bazaning nusxasini olish. |
| Kim | Do'kon administratori (yoki xizmat ko'rsatuvchi firma) — dasturchi faqat qabul qiladi |
| Kirish | Egasining YOZMA roziligi, 32 GB tashuvchi, do'kon yopilgan, kassa smenalari yopiq |
| Chiqish | `.dt` fayl (yoki `File=` bazasining papkasi) + 3 ta vaqt belgili nazorat hisoboti + papka skrinshoti |
| Buyruq | 1C «Конфигуратор» → «Администрирование» → «Выгрузить информационную базу…» (`FAYZAN_1C_DISCOVERY_CHECKLIST.md:170`) |
| Yozadimi | 1C: **«выгрузка» ning O'ZI** faqat o'qiydi (quyidagi izohga qarang) · BinOS: yo'q |
| Davomiylik | Do'kon yopilgandan keyin 30–60 daqiqa + nusxani qo'ldan-qo'lga topshirish |

⚠️ **«faqat o'qiydi» qaysi chegarada to'g'ri.** `.dt` chiqarishning o'zi bazadagi ma'lumotni o'zgartirmaydi.
Lekin uning SHARTLARI baza holatiga tegishi mumkin: monopol rejim, boshqa seanslarni uzish, `Srvr=` bazasida
ulanishni vaqtincha bloklash `(экранда tekshirilsin)`. **Bu amallarni faqat do'kon administratori qiladi va
ish tugagach O'ZI qaytaradi.** BinOS tomonidagi hech kim seans uzmaydi, blok qo'ymaydi va parol kiritmaydi
(0-bo'lim, 8-qoida). Chiqarish uzilib qolsa (joy yetmasa, seans uzilsa) — qayta urinishni ham administrator
qiladi; tashrif buyuruvchi hech narsani «tuzatmaydi».

**Nazorat hisobotlari (ayni kunga, vaqti yozilgan holda):** «Остатки на складах» (astatka),
«Цены по видам цен» (sena), shtrix-kodlar ro'yxati (Список9). Ular 8-bosqichda solishtirish uchun ishlatiladi.

**STOP shartlari**

- Yozma rozilik yo'q → STOP (`FAYZAN_1C_DISCOVERY_CHECKLIST.md:202-204`). Rozilikda yo'q qilish sanasi ham
  bo'lishi shart (0-bo'lim, 9-qoida).
- «Активные пользователи» ro'yxatida boshqa foydalanuvchi bor → nusxa olinmaydi.
- Nusxa Telegram / e-mail / bulut orqali so'ralsa yoki yuborilsa — STOP. **Qo'ldan-qo'lga topshirishni
  tashkil qilish BinOS tomonining vazifasi**, do'kon xodimidan talab qilinmaydi; xodim «tezroq bo'lsin» deb
  yuborib yuborsa ham ayb unda emas — fayl ishlatilmaydi, kanal yopiladi va nusxa qaytadan olinadi.
- Nusxa hech qachon kassirdan so'ralmaydi — faqat egasi yoki u tayinlagan administrator beradi.
- ⚠️ «Загрузить информационную базу…» bosilsa — ishchi baza o'chadi. Bu tugma HECH QACHON bosilmaydi
  (`FAYZAN_1C_DISCOVERY_CHECKLIST.md:175`).
- ⚠️ **AYNI MENYUDAGI qo'shni tugmalar ham taqiqlangan:** «Тестирование и исправление…» (bazani qayta
  quradi va YOZADI), «Загрузить конфигурацию из файла…», «Обновить конфигурацию базы данных»,
  «Вернуться к конфигурации БД». «Выгрузить информационную базу…» tasdig'idan boshqa har qanday savolga —
  «Нет» yoki «Отмена» (checklist:72-76).
- ⚠️ Baza admin huquqi bilan ochilgani uchun 0-bo'limdagi **5-qoida (ommaviy yozadigan tugmalar)** shu
  bosqichda kuchga kiradi: «Удалить помеченные объекты», «Групповое изменение реквизитов»,
  «Синхронизация данных» ichidagi «Выполнить» va h.k. bosilmaydi (menyu yo'li `(экранда tekshirilsin)` —
  5-qoidadagidek faqat TUGMA NOMLARI beriladi).

**Zaxira yo'l (nusxa berilmasa):** `.cf` (`(экранда tekshirilsin)`, checklist:183) va kengaytmalar uchun `.cfe`
(`(экранда tekshirilsin)`, checklist:185) + qo'shimcha rekvizitlar ro'yxati skrinshoti
(`(экранда tekshirilsin)`, checklist:188) + egasi kuzatuvida bir martalik masofadan ko'rish.
Bu yo'lda qo'shimcha rekvizitlar `.cf` ga KIRMAYDI — ular faqat skrinshotdan olinadi (checklist:328).

🔒 **Masofadan ko'rish qoidalari (checklist:192-195) — bittasi ham tushirib qoldirilmaydi:** ulanishni
**egasining o'zi** ishga tushiradi; ID va parol **faqat telefon orqali** aytiladi (chatda, xatda, skrinshotda
YOZILMAYDI va saqlanmaydi); egasi butun seansni kuzatib turadi; seans tugashi bilan AnyDesk **darhol yopiladi**;
seans davomida hech narsa o'zgartirilmaydi, faqat ko'riladi. Ekran yozib olinmaydi — kerak bo'lsa egasi
o'zi skrinshot qiladi va 0-bo'lim 8-qoidasi bo'yicha maxfiy joylarini berkitadi.
⚠️ `.cf`/`.cfe` ichiga dasturchi kassa yoki tarozi parolini yozib qo'ygan bo'lishi mumkin (checklist:187) —
fayl kelgach u 9-qoidadagi rejimda saqlanadi, parol topilsa egasiga aytiladi va u almashtiriladi.

**Rollback:** nusxa ishdan keyin o'chiriladi va o'chirilgani egasiga yozma tasdiqlanadi (checklist:207-208).

---

## Bosqich 3 — read-only extraction

| Maydon | Qiymat |
|---|---|
| Maqsad | 1C ichida `binos-1c-v1` shartnomasiga mos `.json` + `.json.sha256` hosil qilish. |
| Kim | Dasturchi (ekstraktorni yozadi va JAVOB BERADI) + do'kon administratori (faqat ruxsat beradi va ishga tushirishni kuzatadi) |
| Kirish | 1-bosqich javoblari (konfiguratsiya), 2-bosqich nusxasi (registr nomlari), ombor va narx turi tanlovi |
| Qayerda ishlaydi | **Avval FAQAT nusxada** (yoki `.cf` dan qurilgan bo'sh bazada). Jonli bazaga faqat quyidagi darvoza to'liq ochilgach chiqadi (checklist:350) |
| Chiqish | `binos-export-<export_id>.json` + `binos-export-<export_id>.json.sha256` |
| Buyruq | **HALI YO'Q** — 1C tomonidagi `.epf` repoda mavjud emas (`integrations/1c/MIGRATOR_V1_RUNBOOK.md:13`) |
| Yozadimi | 1C: yo'q — **ammo bu KOD xossasi, menyu xossasi emas**: quyidagi darvoza uni isbotlaydi · BinOS: yo'q |
| Davomiylik | O'lchanmagan — birinchi yurishda o'lchanadi |

🚪 **`.epf` darvozasi — 5 shart, hammasi bajarilmaguncha fayl do'kondagi 1C'da OCHILMAYDI.**
Discovery davomida har qanday `.epf` ni ochish umuman taqiqlangan (checklist:71); bu bosqich o'sha taqiqni
BEKOR QILMAYDI, faqat nazorat ostida bitta istisno ochadi.

| # | Shart | Kim bajaradi |
|---|---|---|
| 1 | Ekstraktor manbasida YOZISH operatori yo'qligi yozma tasdiqlanadi: `Записать`, `Удалить`, `Провести`, `ОтменитьПроведение`, `УстановитьПривилегированныйРежим` bilan yozish, `НачатьТранзакцию`, tashqi `Выполнить()` — hech biri ishlatilmaydi; fayl faqat so'rov o'qiydi va diskka `.json` yozadi | Dasturchi (imzo bilan) |
| 2 | Ayni fayl nusxada (yoki `.cf` dan qurilgan bo'sh bazada) to'liq yuritiladi va natijasi 4-bosqichdan o'tadi | Dasturchi |
| 3 | Do'konga beriladigan faylning `sha256` i oldindan aytiladi; do'konda AYNI shu xesh tekshiriladi | Dasturchi + administrator |
| 4 | Jonli bazada birinchi yurish **savdo yopiq** paytda va egasi/administrator ko'z o'ngida bo'ladi; birinchi urinish zararsiz «sinov rejimi» (bir nechta qator) bilan qilinadi (checklist:350) | Administrator ruxsati bilan |
| 5 | «Xavfsiz rejim» (безопасный режим) savoliga javob **Band 4** javob formatidan olinadi (`docs/FAYZAN_1C_DISCOVERY.md:394`); taqiq bo'lsa — jonli bazada YURITILMAYDI, faqat nusxa yo'li qoladi | Administrator |

👤 **Javobgarlik:** ekstraktor mazmuni uchun **BinOS tomoni javob beradi** (0-bo'lim, 10-qoida). Do'kon
administratori faylni faqat ruxsat berib ochadi; u faylning ichini tekshirishga majbur emas va unga
«ishonib ochib qo'ying» deb aytilmaydi. Biror shart bajarilmasa — administrator «yo'q» deyishi kifoya,
bosqich to'xtaydi.

> Ruscha: Эту обработку писали мы, и отвечаем за неё тоже мы. Она только читает и сохраняет файл.
> Сначала запустим на копии, и только потом — при вас, при закрытом магазине. Если вы не хотите её
> открывать — скажите «нет», мы пойдём другим путём.

**Hozirdanoq qat'iy (konfiguratsiyaga bog'liq EMAS):**

- JSON sonlari TAQIQLANGAN — barcha miqdor, narx, sanoq va identifikator MATN (`bundle.py:88-101`).
- Noma'lum yoki takror kalit — butun fayl rad (`bundle.py:36-48, 79-85`).
- GUID manbai: `XMLСтрока(Ссылка)`, kanonik kichik harfli `8-4-4-4-12` (`normalize.py:44-54`).
- Ekstraktor BARCHA omborlar va BARCHA narx turlarini chiqaradi; tanlov faqat `selection` da bo'ladi
  (`bundle.py:226-234`, `normalize.py:286-292`).
- `manifest.stock_qty_by_warehouse` 1C ICHIDA hisoblanadi (Decimal, yuvarlashsiz) — etalon algoritm
  `apps/server/tests/migrator_1c_synth.py:127-146`.
- `plu` nomdan AJRATIB OLINMAYDI (checklist:337-338).
- `plu` — 1–5 xonali raqam satri; migrator AYNAN shu chegarada qabul qiladi (`normalize.py:211`) va bu
  1-bosqichda tasdiqlanadigan etiketka kontraktining 5 xonali PLU maydoniga AYNAN mos tushadi — backend
  6 xonagacha KENGAYTIRILMADI. Kanonik zanjir: etiketkada bosilgan KOD `000537` (6 xona, tarozi shunday
  chop etadi) → barkod ichidagi PLU `00537` (5 xona, parser shuni qaytaradi —
  `packages/shared/src/lib/scaleBarcode.ts:87`) → BinOS `products.plu_code` `537` (yetakchi nolsiz, QA PC-013
  — `apps/server/app/api/v1/products.py:35`); uchalasi BITTA tovar, solishtirish ikkala tomonni 5 xonaga
  to'ldirib bajariladi. ⚠️ 6 xonali KOD `plu` ga YOZILMAYDI — u chop etilgan ko'rinish, barkod maydoni emas.

**STOP shartlari**

- `.epf` ochish ruxsati yoki xavfsiz rejim savoli hal qilinmagan (checklist:350) — bu band discovery'ga
  qaytarilishi kerak, aks holda ekstraktorni do'konda yurgizish MEXANIZMI yo'q.
- Konfiguratsiya nomi noma'lum — birorta so'rov yozilmaydi.
- ⚠️ 1C'da `.epf` ochilganda ichida «Выгрузить»/«Загрузить» tugmasi bo'lgan boshqa ishlov ochilmaydi.

**Rollback:** chiqqan fayl o'chiriladi (0-bo'lim, 9-qoida); 1C o'zgarmagan — buni «ekstraktor shunday
yozilgan» degan gap emas, darvozaning 1- va 2-shartlari isbotlaydi. ⚠️ `.epf` ni jonli bazada yurgizib
bo'lgach, u do'kon kompyuterida QOLDIRILMAYDI — o'chiriladi, aks holda keyin kimdir uni qaytadan,
nazoratsiz ochishi mumkin.

---

## Bosqich 4 — bundle validation

| Maydon | Qiymat |
|---|---|
| Maqsad | Fayl imzosi va tuzilmasini fail-closed tekshirish. |
| Kim | Dasturchi |
| Kirish | `.json` + `.json.sha256` |
| Chiqish | `file_sha256`, `content_sha256`, `export_id`, `snapshot_at`, `infobase`, `manifest` |
| Buyruq | `python -m app.tools.migrate_1c verify-bundle --bundle <fayl>` |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | < 1 daqiqa |

**STOP shartlari** (har biri butun faylni rad etadi)

| Shart | Manba |
|---|---|
| `.sha256` yon fayli yo'q yoki mos emas; hajm > 256 MB | `bundle.py:28-29, 320-351` |
| `schema_version` ≠ `binos-1c-v1` yoki `source_system` ≠ `1c` | `bundle.py:149-151` |
| `infobase` ning 3 majburiy maydoni bo'sh | `bundle.py:160-162` |
| `exported_at` / `snapshot_at` da vaqt zonasi yo'q | `bundle.py:137-143` |
| `purchase_price_type_guid` == `retail_price_type_guid` | `bundle.py:182-185` |
| Manifest sanog'i fayl mazmuniga teng emas | `bundle.py:240-247` |
| JSON soni yoki takror kalit | `bundle.py:79-101` |
| Whitelist'dan tashqari (noma'lum) kalit | `bundle.py:36-48` (ruxsat etilgan kalitlar) · `112-114` (rad etish) |

`verify-bundle` doim 0 qaytaradi; xato bo'lsa istisno bilan yiqiladi (`migrate_1c.py:108`).

**Rollback:** yo'q — ekstraktor tuzatilib, 3-bosqich qaytariladi.

---

## Bosqich 5 — dry-run

| Maydon | Qiymat |
|---|---|
| Maqsad | Bazaga YOZMASDAN har qatorni tasniflash va rekonsiliatsiyani hisoblash. |
| Kim | Dasturchi |
| Kirish | Tekshirilgan bundle, `--company-code fayzan1`, ixtiyoriy `--unit-map` |
| Chiqish | `report.json` (`report_sha256` bilan) + `summary.txt` |
| Buyruq | `dry-run --bundle X --company-code fayzan1 --out report.json --summary-out summary.txt [--unit-map units.json]` |
| Yozadimi | 1C: yo'q · BinOS: yo'q (DB sessiyasi read-only) |
| Davomiylik | 1–5 daqiqa |

**Read-only isbot ikki qismli** (`guard.py:110-137`): ijobiy dalil (`transaction_read_only=on` /
`PRAGMA query_only=1`) VA negativ nazorat — `UPDATE companies SET code = code WHERE 1 = 0` AYNAN read-only
xatosi bilan rad etilishi (PG SQLSTATE `25006`). Boshqa sabab bilan yiqilsa isbot NOANIQ va quruq yurish to'xtaydi.

**STOP shartlari**

- Read-only isbot olinmadi → quruq yurish to'xtaydi.
- Chiqish kodi 3 — rekonsiliatsiya MOS EMAS (8-bosqichga qarang) (`migrate_1c.py:147`).
- `--unit-map` da to'qnashuv bo'lsa quruq yurish umuman boshlanmaydi (`migrate_1c.py:120-124`).
- ⚠️ Production'da `/catalog/v2/preview` ISHLATILMAYDI: u `validated` job yozadi va keyinroq
  `cutover-complete` ni abadiy bloklashi mumkin (`apps/server/app/api/v1/catalog_v2.py:66-70`).
  Production quruq yurishi FAQAT shu CLI orqali.

**Rollback:** kerak emas — sessiya rollback bilan yopiladi (`migrate_1c.py:132-134`).

---

## Bosqich 6 — GUID mapping

| Maydon | Qiymat |
|---|---|
| Maqsad | Identitet xaritasini (1C GUID → BinOS mahsuloti) va qaror shablonini tayyorlash. |
| Kim | Dasturchi (shablon), operator (qarorlar 7-bosqichda) |
| Kirish | `report.json` |
| Chiqish | `mapping.json` shabloni: `decisions`, `policies`, `warehouse_branch`, `approved_by/at` |
| Buyruq | `mapping-template --report report.json --out mapping.json` |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | < 1 daqiqa |

**Qat'iy fakt:** avtomatik (operatorsiz) bog'lanish FAQAT 1C GUID orqali bo'ladi — `EXACT_MATCH`
(`classify.py:335, 380-387`). `article`, `barcode`, `name`, `plu` — faqat NOMZOD dalili, ular orasida
ustuvorlik YO'Q va hech biri avtomatik bog'lamaydi (`classify.py:345-362, 397-402`).

**Fayzan uchun kutiladigan holat:** BinOS katalogida 1C GUID'li mahsulot 0 ta
(`integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md:352`), ya'ni `EXACT_MATCH` 0 bo'ladi va deyarli har qator
CANDIDATE / AMBIGUOUS / NEW ga tushadi. 214 ta takror nom guruhi (666 qator) tufayli `MANY_TO_ONE` xavfi
yuqori (checklist:371).

**STOP shartlari**

- Eksportda GUID ustuni yo'q → har qator `MISSING_GUID` bilan BLOKLANADI (`normalize.py:198-199`).
  2026-08 dagi 3 ta `.xls` faylida Ссылка/GUID ustuni YO'Q edi (checklist:370) — ular bilan cutover qilinmaydi.
- `warehouse_branch` `selection.warehouse_guids` ni AYNAN qoplamasa yoki ikki ombor bitta filialga
  xaritalansa — reja qurilmaydi (`mapping.py:217-229`).

**Rollback:** shablon qayta yaratiladi; hech narsa yozilmagan.

---

## Bosqich 7 — conflicts

| Maydon | Qiymat |
|---|---|
| Maqsad | Har bir qaror va har bir siyosatni ANIQ yozib, deterministik rejani qurish. |
| Kim | Operator (qarorlar, imzo) + dasturchi (reja) |
| Kirish | `report.json` + to'ldirilgan `mapping.json` |
| Chiqish | `plan.json` (`plan_sha256`, `expected`, `skipped`, `deactivate`, `kept_unlinked`) |
| Buyruq | `plan --report report.json --mapping mapping.json --out plan.json` |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | Soatlar–kunlar (qatorlar soniga bog'liq) |

**Qaror sinflari:** `EXCLUDED > BLOCKED > DELETED_MATCH > AMBIGUOUS > EXACT_MATCH > CANDIDATE > NEW`
(`classify.py:36`). Operator qarorlari: `LINK` / `CREATE` / `SKIP` / `REACTIVATE`.
`LINK` faqat hisobotda `linkable=true` bo'lgan nomzodga mumkin (`classify.py:263`, `mapping.py:313-322`).

**14 ta siyosat — STANDART QIYMAT YO'Q** (`mapping.py:29-46, 209-214`; ro'yxat: `MIGRATOR_V1_RUNBOOK.md:78-91`): `new_products`, `blocked_rows`,
`negative_stock`, `missing_price`, `unknown_unit`, `unit_differs`, `invalid_barcode`, `barcode_owned_by_other`,
`article_collision`, `plu_collision`, `names`, `unmapped_branch_stock`, `binos_missing_from_source`,
`skipped_row_products`. Siyosat yozilmasa reja umuman qurilmaydi.

**STOP shartlari**

- Chiqish kodi 2 — `MappingError` muammolar ro'yxati (`migrate_1c.py:163-164`).
- `has_characteristics = true` qatorlar V1 da BLOKLANADI (`CHARACTERISTICS_UNSUPPORTED`,
  `normalize.py:318-319`) — ularning hajmi 7(а) javobidan keyin ma'lum bo'ladi.
- BinOS'da partiya kuzatuvi yoqilgan mahsulot bo'lsa — reja umuman qurilmaydi (`mapping.py:190-191`).
- Katalog LIVE bo'lsa yoki `cutover_at` qo'yilgan bo'lsa — 1C snapshot'i endi qo'llanmaydi (`mapping.py:183-189`).
- `approved_by` / `approved_at` bo'sh bo'lsa — reja rad (`mapping.py:165-180`).

**Rollback:** `mapping.json` tuzatiladi va `plan` qayta yuritiladi; hech narsa yozilmagan.

---

## Bosqich 8 — totals reconciliation

| Maydon | Qiymat |
|---|---|
| Maqsad | Eksport TO'LIQ va reja BAJARILADIGAN ekanini raqam bilan isbotlash. |
| Kim | Dasturchi + do'kon administratori (1C «Итого» qatori) |
| Kirish | `report.json`, `plan.json`, 1C ning vaqt belgili nazorat hisobotlari |
| Chiqish | `reconciliation.ok = true` + rehearsal natijasi (rollback bilan) |
| Buyruq | `plan …` (chiqish kodi 0) va `apply --bundle X --report report.json --mapping mapping.json --expect-system-identifier <staging sysid> --rehearse` |
| Yozadimi | 1C: yo'q · BinOS: yo'q — rehearsal tranzaksiyasi HAR DOIM rollback qilinadi (`migrate_1c.py:176-195, 188-190`) |
| Davomiylik | 15–60 daqiqa |

**Uch qatlamli isbot**

| Qatlam | Nima solishtiriladi | Manba |
|---|---|---|
| Ayniyat | xom fayl = migratable + BLOCKED + EXCLUDED, har ko'rsatkich bo'yicha | `classify.py:187-222` |
| Manifest | fayldagi `stock_qty_by_warehouse` = BinOS mustaqil qayta hisobi | `classify.py:225-232` |
| Tashqi nazorat | BinOS jami = 1C hisobotining «Итого» qatori | `FAYZAN_1C_DISCOVERY_CHECKLIST.md:26, 227` — ⚠️ kodda darvoza YO'Q, bu QO'LDA solishtiriladi |

`raw_totals` normalizerni ISHLATMAYDI — o'z regexlari bilan xom fayldan o'qiydi (`classify.py:59-138`),
shuning uchun bu mustaqil nazorat.

**STOP shartlari**

- `dry-run` chiqish kodi 3 yoki `reconciliation.ok = false` → `build_plan` «rekonsiliatsiya MOS EMAS» deb rad
  etadi, apply mumkin emas (`classify.py:220`, `mapping.py:181-182`).
- Manifest `diffs` bo'sh emas.
- 1C «Итого» BinOS jamisiga teng emas — sabab topilmaguncha STOP.
- Rehearsal `PostVerifyError` bersa — STOP.

**Rollback:** rehearsal tranzaksiyasi o'zi qaytariladi; hech qanday yozuv qolmaydi.

---

## Bosqich 9 — final fresh snapshot

| Maydon | Qiymat |
|---|---|
| Maqsad | APPLY'dan darhol oldin qoldiq va narxning ENG YANGI holatini olish. |
| Kim | Do'kon administratori (eksportga ruxsat va kuzatuv) + dasturchi (3–8 qayta) |
| Kirish | Savdo to'xtagan 1C bazasi, oldingi `mapping.json` qarorlari |
| Qayerda ishlaydi | **JONLI bazada** — eng yangi qoldiq faqat shu yerda. Ya'ni bu `.epf` ning eng xavfli yurishi |
| Chiqish | Yangi `report.json` + yangi `mapping.json` + yangi `plan.json` |
| Buyruq | 3 → 4 → 5 → 6 → 7 → 8 bosqichlari qaytadan |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | 30–90 daqiqa (freeze oynasi ichida) |

⚠️ **3-bosqichning `.epf` darvozasi bu yerda ham to'liq amal qiladi** va endi u JONLI bazada bajariladi:
faylning `sha256` i o'sha (3-shart), u nusxada allaqachon toza yurgan (2-shart), yurish egasi yoki
administrator ko'z o'ngida va savdo yopiq paytda bo'ladi (4-shart). Freeze ichida shoshilinch «tuzatilgan»
yangi `.epf` OLIB KIRILMAYDI — xesh boshqacha bo'lsa cutover boshqa kunga suriladi.
🔒 Bu yurishda 0-bo'limning 8- va 9-qoidalari amalda: yangi `report.json` ham tijorat siri, u ham ish
oxirida o'chiriladi.

Oldingi qarorlar yangi hisobotga KO'CHIRILADI, farqlar qayta ko'riladi
(`integrations/1c/MIGRATOR_V1_RUNBOOK.md:20`).

**STOP shartlari**

- Yangi `snapshot_at` allaqachon qo'llangan jobning snapshot vaqtidan eski yoki TENG bo'lsa —
  `StaleSnapshotError`, apply yozuvsiz rad etiladi (`apply.py:125-127`). Shuning uchun yangi eksport
  vaqti aniq oldinga surilishi shart.
- Yangi hisobotda kutilmagan yangi konflikt paydo bo'lsa — qaror qayta ko'riladi, APPLY kutadi.

**Rollback:** freeze bekor qilinadi, savdo ochiladi, cutover boshqa kunga suriladi. BinOS'da hech narsa
o'zgarmagan.

---

## Bosqich 10 — short freeze

| Maydon | Qiymat |
|---|---|
| Maqsad | 9–12 bosqichlar davomida 1C qoldig'i o'zgarmasligini kafolatlash. |
| Kim | Do'kon egasi e'lon qiladi; kassirlar bajaradi |
| Kirish | 9-bosqich boshlanishiga tayyorlik, yozma ruxsat |
| Chiqish | Savdo to'xtagan oyna + yopilgan smenalar |
| Buyruq | — (tashkiliy qadam) |
| Yozadimi | 1C: yo'q · BinOS: yo'q |
| Davomiylik | 9 + 11 + 12 bosqichlar yig'indisi (quyidagi bo'limga qarang) |

👤 **Qaror kassirniki EMAS.** Savdoni to'xtatish ham, qaytadan ochish ham **faqat egasi (yoki u YOZMA
tayinlagan mas'ul)** ning qarori; kassir buyruqni bajaradi, o'zi boshlamaydi va o'zi tugatmaydi.
BinOS tomonidagi hech kim kassirga to'g'ridan-to'g'ri «savdoni to'xtating» demaydi — bu so'rov egasi orqali
o'tadi. Boshlanish va tugash vaqti, kim aytgani va kim bajargani cutover hujjatiga yoziladi.
⚠️ Freeze cho'zilib ketsa — bu kassirning muammosi emas: dasturchi holatni egasiga aytadi, egasi
«davom etamiz / bugun to'xtatamiz» qarorini qabul qiladi. Har qanday to'xtatishda BinOS'da hech narsa
o'zgarmaydi (11-bosqich bajarilmagan bo'ladi).

Batafsil: «Muzlatish (freeze) oynasi» bo'limi.

---

## Bosqich 11 — APPLY

| Maydon | Qiymat |
|---|---|
| Maqsad | Tasdiqlangan rejani BinOS bazasiga bitta tranzaksiyada yozish. |
| Kim | Dasturchi — ALOHIDA yozma ruxsat bilan |
| Kirish | Yangi bundle + `report.json` + `mapping.json` + maqsad bazaning `system_identifier` qiymati |
| Chiqish | `import_jobs` qatori (`committed`) + `job_id` |
| Buyruq | `apply --bundle X --report report.json --mapping mapping.json --expect-system-identifier <sysid> --commit` |
| Yozadimi | 1C: yo'q · **BinOS: HA** |
| Davomiylik | 1–10 daqiqa |

**AYNAN 6 ta jadvalga yoziladi** (+ `audit_log`): `products`, `product_barcodes`, `inventory`,
`stock_movements`, `import_jobs`, `settings` (`key='catalog'`) — boshqa jadval yo'q (`apply.py:240-246, 282,
325-343, 149-161, 180-185`).

**Qoldiq semantikasi:** har (mahsulot, filial) uchun `CUTOVER_LEGACY_CLOSE` (−eski, balance_after=0, vaqt T)
va `CUTOVER_OPENING_BALANCE` (1C qoldig'i, vaqt T+1 µs), `ref_type='1c_cutover'`,
`client_uuid = uuid5(job, "kind:mahsulot:filial")` (`apply.py:311-333`).

**STOP shartlari** (hammasi YOZUVSIZ rad etadi)

| Xato | Sabab | Manba |
|---|---|---|
| `ApplyForbidden` | muhit yoki baza darvozasi | `guard.py:34, 47-54, 74-89`; `apply.py:97` |
| `AlreadyApplied` | ayni fayl yoki mazmun xeshi allaqachon qo'llangan | `apply.py:119-124` |
| `StaleSnapshotError` | snapshot eski yoki teng | `apply.py:125-127` |
| `ApplyInProgress` | do'kon qatori 120 s ichida qulflanmadi | `apply.py:107-113` |
| `DriftError` | katalog yoki hisobot ko'rilgandan keyin o'zgargan | `apply.py:140-146` |
| `PostVerifyError` | tranzaksiya ichidagi tekshiruv yiqildi | `apply.py:167-170, 350-486` |

**Rollback:** butun apply BITTA tranzaksiya. Post-tekshiruv yiqilsa hammasi qaytariladi. `--rehearse` va
`--commit` dan AYNAN bittasi berilishi shart, aks holda `SystemExit` (`migrate_1c.py:176-177`).

---

## Bosqich 12 — post-apply verify

| Maydon | Qiymat |
|---|---|
| Maqsad | Rejaning bazada BAJARILGANINI bazadan o'qib isbotlash. |
| Kim | Dasturchi |
| Kirish | `--company-code fayzan1`, `--job-id <id>` |
| Chiqish | `ok: true` + job holati `committed` |
| Buyruq | `verify-applied --company-code fayzan1 --job-id <id>` |
| Yozadimi | 1C: yo'q · BinOS: yo'q (read-only isbot bilan) |
| Davomiylik | < 5 daqiqa |

**STOP shartlari**

- Chiqish kodi 4 — post-holat farq qiladi yoki job `committed` emas (`migrate_1c.py:224`).
- Read-only isbot olinmasa — tekshiruv to'xtaydi.

**Rollback:** APPLY allaqachon commit qilingan. Farq topilsa 13-bosqich BOSHLANMAYDI; sabab aniqlanmaguncha
POS savdosi ochilmaydi.

---

## Bosqich 13 — BinOS truth

| Maydon | Qiymat |
|---|---|
| Maqsad | Katalogni LIVE qilish — BinOS haqiqat manbaiga aylanadi. |
| Kim | Operator (`sozlamalar.edit` ruxsati bilan) |
| Kirish | 12-bosqich `ok: true`, `import_job_id` |
| Chiqish | `settings.catalog`: `mode='LIVE'`, `cutover_at`, `last_import_job_id`, `last_snapshot_id`, `last_content_sha256` |
| Buyruq | `POST /catalog/v2/cutover-complete?import_job_id=<id>` |
| Yozadimi | 1C: yo'q · **BinOS: HA** |
| Davomiylik | < 5 daqiqa |

**MUHIM:** APPLY `settings.catalog` ga faqat `source_system='1c'` va `last_import_job_id` yozadi,
`mode` ni LIVE QILMAYDI (`apply.py:180-181`): `set_catalog_settings` faqat `None` bo'lmagan kalitlarni
qo'shadi, qolgani bazadagi joriy qiymatdan olinadi (`catalog_import_v2.py:134-136`).
`mode='LIVE'` va `cutover_at` ni FAQAT `cutover-complete` marshruti yozadi — ALOHIDA qadam
(`apps/server/app/api/v1/catalog_v2.py:312-315`).

**STOP shartlari** (`catalog_v2.py:256-310`)

- Production muhitida 403 (`catalog_v2.py:268` → `47-50`).
- `import_job_id` berilmagan; cutover allaqachon yopilgan (409); job `committed` emas;
  `mode` ∉ {CUTOVER_REFRESH, INITIAL_CREATE}; `source` katalog manbasiga mos emas;
  `snapshot_id` yoki `content_sha256` bo'sh.
- Kechroq yaratilgan boshqa `snapshot_id` li ish bor; tugallanmagan COMMITTING/FAILED ish bor;
  job qatorlarida SKIPPED_AMBIGUOUS/SKIPPED_INVALID yoki `confirmation_required` > 0.

**Rollback:** `cutover_at` qo'yilgandan keyin 1C snapshot'i endi qo'llanmaydi (`mapping.py:183-189`) —
bu qadam QAYTARILMAYDI. Shuning uchun u faqat 12-bosqich toza o'tgandan keyin bajariladi.

---

## Muzlatish (freeze) oynasi

**Nima uchun:** 9-bosqichdagi eksport lahzasi bilan 11-bosqichdagi APPLY orasida 1C'da savdo bo'lsa,
BinOS'ga ko'chgan qoldiq haqiqatdan farq qiladi. Kod buni O'ZI ANIQLAY OLMAYDI — migratorda faqat «eskirgan
snapshot» darvozasi bor (`apply.py:125-127`). Qoldiq haqiqiyligi butunlay shu oynaga bog'liq.

| Savol | Javob |
|---|---|
| Oyna nimadan iborat | 9-bosqich (yangi eksport + 4–8 qayta) + 11-bosqich (APPLY) + 12-bosqich (verify) |
| Uzunligi | **NOMA'LUM** — 4-savol javobisiz hisoblab bo'lmaydi (quyiga qarang) |
| Kim e'lon qiladi | Do'kon egasi (yoki u yozma ruxsat bergan mas'ul) — ism va imzo cutover kuni yoziladi |
| Kim bajaradi | Kassirlar: savdo to'xtatiladi, smenalar yopiladi |
| Qanday qaytariladi | Har qanday STOP shartida: APPLY bajarilmaydi, freeze bekor qilinadi, savdo ochiladi, cutover boshqa kunga suriladi. BinOS'da hech narsa o'zgarmagan |

**Uzunlik 4-savol javobiga bog'liq** (checklist:218-220):

| 4(б) javobi | Freeze uchun ma'nosi |
|---|---|
| Savdo 1C qoldig'ini DARHOL kamaytiradi | Oyna = 9+11+12 bosqichlar vaqti |
| Smena yopilganda kamaytiradi | Freeze BARCHA smenalar yopilgandan KEYIN boshlanadi |
| Kechqurun / qo'lda yuklanadi | Oyna oxirgi yuklash tugagunicha cho'ziladi; uzunlik cutover rejasi uchrashuvida hisoblanadi |

> Ruscha: В этот промежуток касса не продаёт. Начало и конец объявляет владелец магазина. Если что-то
> пойдёт не так, мы ничего не записываем и открываем продажу обратно — данные остаются как были.

**Oldindan tayyor bo'lishi kerak:** kim savdoni to'xtatadi, smenalar kim tomonidan yopiladi va APPLY'ni kim
YOZMA tasdiqlaydi — bu uchtasi checklist:361 da cutover rejasi uchrashuviga qoldirilgan va hozir BO'SH.

---

## APPLY ruxsati — mavjud kod production'ni QANDAY to'sadi

Bu to'siqlarni ochish — **ALOHIDA, ONGLI o'zgarish**. Runbook'ning o'zi ularni ochmaydi va bu hujjat
ularni ochish yo'riqnomasi EMAS.

| # | To'siq | Fayl:satr | Ochish mumkinmi |
|---|---|---|---|
| 1 | `APP_ENV` ∈ {dev, test, staging} bo'lishi shart | `apps/server/app/services/migrator_1c/guard.py:34, 50-51` | Muhit o'zgaruvchisi — ongli o'zgarish |
| 2 | Platforma muhiti 'prod'/'production' bo'lsa RAD | `guard.py:52-53` | Muhit o'zgaruvchisi — ongli o'zgarish |
| 3 | Production Postgres `system_identifier` **7674898282858840119** denylist'da | `guard.py:74-75` · `migrator_1c/__init__.py:34` | **Override YO'Q — faqat kod o'zgartirish** |
| 4 | Non-production allowlist (kodda staging **7683497876193431618**) | `guard.py:76-78` · `__init__.py:37` | `MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS`, lekin denylist undan AYIRILADI (`guard.py:44`) |
| 5 | `--expect-system-identifier` MAJBURIY va ulangan bazaga teng | `guard.py:79-82` | Yo'q — operator maqsadni aniq aytishi shart |
| 6 | Hisobotdagi `database` (sysid + baza nomi) AYNAN teng bo'lishi shart | `guard.py:83-87` | Yo'q |
| 7 | `assert_apply_allowed` apply'ning BIRINCHI amali — `import_jobs` qatori ham yaratilmaydi | `apply.py:97` | Yo'q |
| 8 | `/catalog/v2/preview`, `/commit`, `/initial-create`, `/cutover-complete` production'da 403 | `apps/server/app/api/v1/catalog_v2.py:47-50` (chaqiruvlar: `70`, `99`, `141`, `268`) | Ayni `environment_allows_apply()` darvozasi |

**Diqqat:** production bazasi dump/restore bilan qayta yaratilsa, uning `system_identifier` qiymati YANGI
bo'ladi va allowlist'da bo'lmaydi — apply baribir RAD etiladi (`guard.py:76-78`).

**13-bosqich uchun alohida qaror kerak:** production'da `cutover-complete` 403 bo'lgani uchun katalogni LIVE
qilish yo'li (darvozani ongli ochish yoki maxsus CLI qadami) hali TANLANMAGAN
(`integrations/1c/MIGRATOR_V1_RUNBOOK.md:23`).

---

## BinOS truth — cutover tugagach nima o'zgaradi

| Savol | Javob |
|---|---|
| Haqiqat manbai | **BinOS.** `settings.catalog.mode = 'LIVE'` qo'yilgan lahzadan boshlab (`catalog_v2.py:312-318`) |
| Mahsulot identiteti | `Product.external_id` = kanonik kichik harfli 1C GUID, `source_system = '1c'` (`apply.py:240-244`) |
| `sku` | 1C «Код» qiymati (`mapping.py:504-505`) |
| Artikul | Deterministik zanjir: 1C artikuli → 1C kodi → `1C-<guid>` (`mapping.py:492-501`) |
| Qoldiq | `CUTOVER_OPENING_BALANCE` harakatlari; eski tarix o'chirilmaydi, lekin aralashmaydi (`MIGRATOR_V1_RUNBOOK.md:68`) |
| 1C bilan nima qilinadi | **Hech narsa.** 1C o'zgartirilmaydi va o'chirilmaydi. BinOS unga hech qachon yozmaydi (`migrator_1c/__init__.py:3-5`) |
| Takroriy import | Ayni eksport qayta qo'llanmaydi (`AlreadyApplied`); katalog LIVE bo'lgach 1C snapshot'i umuman qo'llanmaydi (`mapping.py:183-189`) |

**Cutover'dan KEYIN ochiq qoladigan ish (ALOHIDA vazifa, bu runbook'da yopilmaydi):**

- `plu` bazaga FAQAT `CREATE` yo'lida yoziladi; `LINK` da 1C PLU'si mavjud BinOS mahsulotiga
  KO'CHIRILMAYDI (`mapping.py:456-477, 504-505`). Ya'ni bog'langan mahsulotlarning PLU'si BinOS'dagicha qoladi.
- Tarozilarga tovar yuklash oqimi BinOS tomonida hozircha stub (`apps/server/app/services/scales/generic.py:25-27`).

> Ruscha: После перехода товары, цены и остатки ведутся в BinOS. Ваша 1С остаётся у вас без изменений —
> мы в неё ничего не записываем.

---

## Ochiq savollar (discovery javob bermaguncha hal bo'lmaydi)

| # | Qaror | Nimaga bog'liq | Javobsiz oqibat |
|---|---|---|---|
| 1 | Ekstraktor so'rovlari (registr/spravochnik nomlari) | 1-savol «О программе» | Birorta so'rov yozilmaydi; bundle'ning 3 majburiy `infobase` maydoni ham bo'sh (`bundle.py:160-162`) |
| 2 | `.epf` ni do'konda yurgizish mexanizmi | Kechiktirilgan eski 5-savol (checklist:350) | 3-bosqichning bajarilish yo'li yo'q; zaxira — faqat `.dt` nusxa |
| 3 | `selection.warehouse_guids` | 5(а) — real zal ombori | Tanlanmagan ombor qoldig'i MIGRATSIYA QILINMAYDI (`normalize.py:286-292`) va xato nol qoldiq beradi. Hisobotda faqat `info` darajasida ko'rinadi (`STOCK_ONLY_IN_UNSELECTED_WAREHOUSE`, `normalize.py:308-312`) — u apply'ni TO'XTATMAYDI, shuning uchun noto'g'ri ombor tanlovi barcha darvozalardan o'tib ketadi |
| 4 | `manifest.stock_qty_by_warehouse` ma'nosi va «Итого» manbai | 5(б) — hisobot nomi va sozlamalari | 8-bosqichning tashqi nazorat qatlami yo'q |
| 5 | `selection.retail_price_type_guid` | 6(а) — kassa qaysi narx turida sotadi | Eng xavfli bo'shliq: noto'g'ri narx turi butun katalogga noto'g'ri narx beradi va bundle darajasida HECH QANDAY XATO BERMAYDI |
| 6 | `selection.purchase_price_type_guid` (yoki `null`) | 6(в) — «Цена поставщика» yangilanadimi | Eskirgan tur qo'yilsa tannarx va COGS buziladi; retail bilan bir xil bo'lsa bundle rad (`bundle.py:182-185`) |
| 7 | Narx avtomatik hisoblanadimi | 6(б) | Avtomatik bo'lsa registrni oddiy o'qish bo'sh/eskirgan narx beradi — ekstraktorning narx o'qish usuli boshqacha bo'ladi |
| 8 | `has_characteristics` / `has_series` hisoblash qoidasi | 7(а), 7(б) + registr tuzilmasi | Ikkalasi MAJBURIY bool (`bundle.py:202-203`); `has_characteristics=true` qatorni BLOKLAYDI |
| 9 | `is_weighted` manbai | 7 — kartochkada «Весовой» rekviziti | Null qoldirish XAVFSIZ EMAS: qiymat `unit_code == 'kg'` dan kelib chiqadi (`normalize.py:207`) — kg'dagi HAR BIR tovar vaznli bo'lib qoladi |
| 10 | `plu` QIYMATLARI 1C da qayerda saqlanadi (qaysi rekvizit) | 8(б) | Etiketka FORMATI endi ochiq savol emas — real etiketkalar bilan tasdiqlangan (`27`+PLU(5)+GRAMM(5)+nazorat; `scaleBarcode.ts:87`, `scale_barcode.py:98`) va migratorning 1–5 xonali chegarasiga mos (`normalize.py:211`). Ochiq qolgani faqat MANBA: PLU qiymati 1C ning qaysi maydonidan olinishi noma'lum, `plu` nomdan ajratib olinmaydi (checklist:337-338) — javobsiz ekstraktor `plu` ustunini bo'sh qoldiradi va tarozi tovarlari BinOS'ga PLU'siz tushadi |
| 11 | 454 ta «кг» tovarining taqdiri | 8-savol | Ular BinOS'da umuman yo'q; javobsiz cutover'da yaratilmaydi |
| 12 | Qadoq («Упаковка») filtri qoidasi | 3-savol nusxasi (registr tuzilmasi) | Qoida checklist:332-333 da REJA holatida; statistik dalil (qadoq deyarli ishlatilmaydi) qoidani yozishga yetmaydi |
| 13 | `--unit-map` mazmuni | 7 — kartochkadagi birlik nomlari | Jadvalda yo'q birlik `UNKNOWN_UNIT` va butun qatorni chiqarib tashlash siyosatini talab qiladi |
| 14 | `snapshot_at` vaqt zonasi | Do'kon serverining zonasi (checklist:339-340) | Offset MAJBURIY (`bundle.py:137-143`) |
| 15 | Freeze oynasining uzunligi | 4(б), 4(в) | 10-bosqich uzunligi hisoblanmaydi |
| 16 | Kim savdoni to'xtatadi va kim APPLY'ni yozma tasdiqlaydi | Eski 30–32-savollar (checklist:361) | 10- va 11-bosqichlarda imzo satri bo'sh qoladi |
| 17 | Production'da katalogni LIVE qilish yo'li | Alohida ongli qaror | 13-bosqich bajarilmaydi (403) |

**Menyu yo'llari — hali tasdiqlanmagan (`(экранда tekshirilsin)`):** `.cf` saqlash yo'li (checklist:183),
`.cfe` saqlash yo'li (:185), qo'shimcha rekvizitlar / qo'shimcha hisobotlar ro'yxatlari (:188), omborlar
ro'yxati (:236-239), «Виды цен» (:266), «Номенклатура» (:286), tarozi uchun «Подключаемое оборудование» (:313).
