# Fayzan 1C — do'kondagi discovery maydon kartasi

**Auditoriya:** do'konga boradigan operator (dasturchi emas).
**Maqsad:** bitta tashrifda 18 ta faktni **xavfsiz** yig'ish, keyin extractor (`.epf`) ni taxminsiz yozish.
**Vaqt:** **24 daqiqa** (baza nusxasi beriladigan bo'lsa) — **32 daqiqa** (nusxa yo'q). Tafsilot: 2-bo'lim.
⚠️ Bu **sof ish vaqti**: kutish, odam izlash va yo'lda yurish kirmaydi. 20–30 daqiqaga sig'dirish kerak bo'lsa —
2-bo'limdagi **qisqartirish tartibi** ishlatiladi; bandlarni o'z bilganicha tashlab ketish mumkin emas.

> **YANGILANDI:** Fayzan'dan **real tarozi etiketkalari** olindi (4 ta, hammasining EAN-13 nazorat raqami
> to'g'ri). Shu dalil bilan **ikki bloker YOPILDI**:
> 1. **PLU xonasi** — barkod ichidagi PLU maydoni **5 xonali** (6 emas). Ya'ni BinOS'ning 1–5 xonali
>    cheklovi (`apps/server/app/api/v1/products.py:35`) va migrator qoidasi
>    (`apps/server/app/services/migrator_1c/normalize.py:211`) kontraktga **aynan mos** — backend kengaytirilmadi.
> 2. **Vazn yoki narx** — 8–12-raqamlar **GRAMM**. Dalil etiketkaning o'zida bosilgan summa:
>    350 × 0.426 = **149.10** va 580 × 0.056 = **32.48**.
>
> Haqiqiy kontrakt: **`27` + PLU(5) + GRAMM(5) + EAN-13 nazorat(1) = 13 raqam.** Tafsilot va kanonik
> mapping — **band 18**.
> ⚠️ Lekin **discovery davom etadi**: **xarakteristikalar (band 14) hamon ochiq STOP-bloker**, va
> **PLU qiymati 1C da qayerdan olinishi (band 17) hali NOMA'LUM**. Band 16 va 18 ham tashlanmaydi —
> ularning maqsadi endi «formatni aniqlash» emas, **«do'kondagi AYNAN shu tarozi shu kontraktda
> chop etishini TASDIQLASH»** (boshqa marka/model boshqacha bosishi mumkin).

## Bu hujjat va mavjud so'rovnoma farqi

| Hujjat | Kim uchun | Qachon |
|---|---|---|
| `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` (2-bo'lim, ruscha) | do'kon egasi / 1C administratori | uchrashuvdan **OLDIN** yuboriladi — bu so'rovnoma |
| **Bu hujjat** | do'konga boradigan operator | uchrashuv paytida, **joyida ijro** uchun — qayerdan topish, qanday skrinshot, nimani yashirish, nimaga tegmaslik, javob formati |

Bu yerda **yangi savol yo'q**. Har band so'rovnomaning tegishli satriga ishora qiladi
(masalan: «batafsil ruscha yo'riqnoma: `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md`, 2-bo'lim, Вопрос 6»).

---

## 0. Boshlanishdagi 60 soniya

**Olib borish:**

| Narsa | Nega |
|---|---|
| 32 GB+ fleshka yoki tashqi disk | `.dt` nusxa uchun (band 4) |
| Telefon (kamera) | tarozi etiketkasi fotosi (band 18) — **majburiy** (kontrakt ma'lum; foto — shu tarozi uchun **TASDIQ**) |
| Bu hujjat + `docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md` (bosilgan yoki ekranda) | javoblarni joyida to'ldirish |
| Egasining **yozma roziligi** matni (nusxa uchun) | so'rovnoma: «Правила для копии базы», 197–208-satrlar |

**Kim bilan gaplashish:**

| Band | Kim javob beradi |
|---|---|
| 1–5 | 1C administratori yoki xizmat ko'rsatuvchi firma |
| 6, 7 | do'kon egasi + **katta kassir** |
| 8–15 | buxgalter yoki 1C administratori |
| 16–18 | tarozida ishlaydigan xodim (etiketka bosadigan) |

**Birinchi jumla (do'kon egasiga):**

> Ruscha: «Мы только смотрим и фотографируем экран. В вашей 1С мы ничего не меняем, не создаём и не удаляем. Ни одной кнопки записи мы не нажмём.»

### ⚠️ Kim sichqonchani ushlaydi — 4 ta qoida

Yuqoridagi va'da («biz hech narsa bosmaymiz») **butun hujjat bo'ylab amal qiladi**. Shuning uchun:

1. **Klaviatura va sichqoncha — do'kon odamida.** Har bir ochish/aylantirish/«Сформировать» ni **do'konning o'z
   xodimi** (administrator, egasi yoki katta kassir) bajaradi. Operator faqat **ko'rsatadi, qaraydi va suratga oladi**.
2. **Agar do'kon «o'zingiz qiling» desa** — faqat o'sha odam **yoningizda turgan holda**, va **har bosishdan oldin
   ovoz chiqarib aytib**: «сейчас я открою вот это, ничего не сохраняю». Yolg'iz qolgan kompyuterda ishlamang.
3. **Xodimdan uning vakolatidan yuqori ishni so'ramang.** Konfigurator, `.dt`, `.cf`/`.cfe`, baza sozlamalari —
   **faqat administrator**, va **faqat egasining ruxsati bilan**. Kassirdan yoki sotuvchidan baza nusxasi so'ralmaydi.
4. **Javobgarlik operatorda.** Biror narsa noto'g'ri ketsa — ayb xodimga yuklanmaydi: darhol administratorga
   aytiladi, natija shablonida qayd etiladi va o'zingiz tuzatmaysiz (1-bo'limga qarang).

> Ruscha (boshida aytiladi): «Нажимать будете вы — я только показываю, куда смотреть, и фотографирую. Если я о чём-то попрошу, а вам это делать нельзя — просто скажите "нет", это нормально.»

**Discovery qachon boshlanadi:** egasi (yoki egasi nomini aytgan mas'ul odam) **roziligini bergandan keyin**.
Egasi yo'q bo'lsa va bog'lanib bo'lmasa — 6, 7, 14, 15, 16, 18 bandlari (og'zaki savol va zaldagi fotolar)
bajariladi, 1C ekranidagi bandlar **keyingi safarga qoldiriladi**.

**Yozma ruxsat:** nusxa (`.dt`) yoki `.cf`/`.cfe` so'rashdan oldin egasidan qisqa yozma tasdiq oling
(kim beradi, nima beradi, sana, maqsad = faqat BinOS'ga katalog ko'chirish, internetsiz kompyuterda saqlanadi,
qaysi sanagacha o'chiriladi, o'chirish yozma tasdiqlanadi). Batafsil: so'rovnoma 197–208-satrlar.

**Skrinshot nomi:** band raqami bilan — `B01-1.png`, `B09-2.png`, `B18-1.jpg`.

---

## 0.1 ⚠️ Skrinshot va fotolar — maxfiylik qoidasi

⚠️ **Bu kadrlar do'konning butun narx ro'yxati, qoldig'i va aylanmasi.** Bu tijorat siri — `.dt` nusxa kabi
himoyalanadi. Ruscha so'rovnomadagi 6, 7, 8-qoidalar (84–95-satrlar) va «Правила для копии базы» (197–208)
shu kadrlarga ham tegishli.

| Qoida | Aniq nima qilinadi |
|---|---|
| **Yopiladi** | parol, litsenziya raqami / PIN, AnyDesk yoki masofaviy kirish ID+paroli, odamlarning telefoni va e-mail'i, bank rekvizitlari va karta raqamlari — Paint'da **qora to'rtburchak** bilan (marker/blur emas: ular orqali o'qiladi) |
| **Parollar hech qayerda yozilmaydi** | shablonga ham, chatga ham, skrinshotga ham. Kerak bo'lsa — **faqat og'zaki telefonda** (so'rovnoma 8-qoida) |
| **Odamlar** | kadrga mijoz yoki xodimning yuzi tushsa — o'sha qism **kesiladi**; odamni suratga olishdan oldin **so'rang** |
| **Qayerga yuboriladi** | **bitta shaxsiy chatga**, qabul qiluvchining ismi oldindan kelishiladi. ⚠️ Guruh chat, kanal, umumiy bulut papkasi — **YO'Q** |
| **Qanday yuboriladi** | Telegram'da **«Файл»** (telefonda «Фото» emas), kompyuterda «Сжать изображение» galochkasi **olinadi** — aks holda raqamlar o'qilmaydi |
| **Telefon avtomatik bulutga yuklashi** | etiketka fotolari olishdan oldin telefonda **avtomatik bulut zaxirasini o'chiring** (Google Photos / iCloud), aks holda do'kon ma'lumoti sizning shaxsiy bulutingizga chiqadi |
| **Do'kon kompyuterida qoldirilmaydi** | skrinshot yoki Excel do'kon mashinasida saqlangan bo'lsa — ish oxirida fleshkaga ko'chiriladi va **xodim ko'z o'ngida o'chiriladi** (Korzina ham tozalanadi) |
| **Qayerda saqlanadi** | internetsiz ish kompyuteridagi `1c-discovery/<YYYY-MM-DD>/` papkasi. ⚠️ **Repoga commit QILINMAYDI** |
| **Qachon o'chiriladi** | bundle validatsiyasi tugagach o'chiriladi va **egasiga yozma xabar beriladi** (nusxa qoidasi bilan bir xil) |

⚠️ **Skrinshot olish do'kon kompyuterida qiyin bo'lsa yoki ruxsat berilmasa** — ekranni **telefon kamerasi bilan**
suratga oling. Bu har doim ruxsat etilgan zaxira usul; do'kon mashinasiga hech narsa o'rnatilmaydi va saqlanmaydi.

---

## 1. ⚠️ HECH QACHON BOSILMAYDIGAN tugmalar

Bitta joyda, qisqa. Batafsil: so'rovnoma 2-bo'lim, «Перед началом», 3-qoida (63–77-satrlar).

| Qayerda | ⚠️ Taqiqlangan |
|---|---|
| Oddiy 1C | «Выгрузить данные», «Загрузить», «Очистить», «Заполнить», «Перенумеровать» |
| Oddiy 1C | hech qanday `.epf` faylini ochish |
| Har qanday kartochka / hujjat | «Записать», «Записать и закрыть», «Провести», «Провести и закрыть», «Отмена проведения» |
| Har qanday ro'yxat | «Создать», «Изменить», «Скопировать», «Пометить на удаление», klaviaturada **Del**, **Enter**, **F2**, **Ctrl+S** |
| Narxlar | «Установить цены», «Пересчитать», «Рассчитать» — narx hujjatlari umuman ochilmaydi |
| Kassa bilan almashinuv | «Загрузить из кассы», «Обмен с кассой», «Закрыть смену», «X-отчёт», «Z-отчёт» |
| «Подключаемое оборудование» | «Тест устройства», «Функции», «Настроить…» — ular tarozi/printerga **buyruq yuboradi** |
| «Администрирование» | «Завершение работы пользователей», «Блокировка установки соединений» — kassirni smena o'rtasida uzib qo'yadi |
| Konfigurator | «Загрузить информационную базу…» — **ishchi bazani o'chiradi** |
| Konfigurator | «Загрузить конфигурацию из файла…», «Вернуться к конфигурации БД», «Обновить конфигурацию базы данных», «Обновить конфигурацию…» |
| Konfigurator | «Снять с поддержки», «Включить возможность изменения», «Тестирование и исправление…» |
| Konfigurator → kengaytmalar | «Загрузить из файла…», «Удалить» |
| Tarozi dasturi | «Загрузить», «Выгрузить» |
| Baza tanlash oynasi | «Изменить», «Добавить», «Удалить» |
| Hisobot varianti | «Выбрать вариант» (variant NOMINI faqat o'qing) |

⚠️ **«Администрирование» va «Настройки» bo'limlarida galochkalar DARHOL ishlaydi** — «Сохранить?» so'ramaydi.
U sahifalarda faqat aylantiring va yo'riqnomada ko'rsatilgan havolani bosing.

⚠️ Oyna yopilayotganda «Сохранить изменения?» chiqsa — **har doim «Нет»**.

⚠️ Tasodifan bosib yuborsangiz — **o'zingiz tuzatmang**, darhol administratorga ayting va natija shabloniga yozing.

> Ruscha (xodimga): «Если я случайно что-то нажму — скажите сразу, я ничего исправлять не буду.»

---

## 2. Vaqt byudjeti

Vaqt **3-band javobiga** bog'liq: baza nusxasi berilsa, 8–15-bandlarda skrinshot kerak emas
(so'rovnoma 31–32-satrlar: nusxa bo'lsa 5-, 6-, 7-savollarga faqat javob yetarli).

| # | Band | Nusxa YO'Q | Nusxa BOR |
|---|---|---|---|
| — | Tayyorgarlik (0-bo'lim) | 1 | 1 |
| 1 | «О программе» | 2 | 2 |
| 2 | O'zgartirilganmi yoki standart | 1 | 1 |
| 3 | Infobase ulanishi (File/Srvr/ws) | 2 | 2 |
| 4 | `.dt` nusxa olish mumkinmi | 2 | 2 |
| 5 | `.cf` / `.cfe` bormi | 1 | 0 |
| 6 | Kassir savdosi qayerda bajariladi | 1 | 1 |
| 7 | Savdo 1C'ga qachon tushadi | 1 | 1 |
| 8 | Haqiqiy qoldiq qaysi omborda | 2 | 1 |
| 9 | Qoldiq hisoboti nomi | 2 | 1 |
| 10 | «Виды цен» | 2 | 1 |
| 11 | Kassada ishlatiladigan narx turi | 1 | 1 |
| 12 | Oddiy tovar kartochkasi | 2 | 0 |
| 13 | Vaznli/tarozi tovar kartochkasi | 2 | 0 |
| 14 | Xarakteristikalar (variantlar) | 1 | 1 |
| 15 | Seriyalar (partiyalar) | 1 | 1 |
| 16 | Tarozi modeli va soni | 1 | 1 |
| 17 | PLU qayerda saqlanadi | 2 | 2 |
| 18 | **Real etiketka / barkod namunasi** (kontraktni TASDIQLASH) | 3 | 3 |
| — | Chiqish tartibi (eski sana qaytarish, fayllarni do'kon mashinasidan o'chirish — 3-bo'lim) | 2 | 2 |
| | **JAMI (daqiqa)** | **32** | **24** |

⚠️ **18-band har doim to'liq bajariladi** — etiketka baza nusxasida KO'RINMAYDI (so'rovnoma 32-satr).
Kontrakt ma'lum bo'lgani bu bandni qisqartirmaydi: foto endi **do'kondagi tarozi shu kontraktda bosishini
tasdiqlash** uchun olinadi.
Vaqt qisqarsa, qisqartirish tartibi: 12 → 13 → 10 → 9 (shu bilan 30 daqiqadan pastga tushadi).
**1, 3, 8, 11, 17, 18 bandlari hech qachon tashlanmaydi.**
⚠️ **Chiqish tartibi hech qachon qisqartirilmaydi** — do'kon kompyuteri o'z holiga qaytarilmasdan chiqilmaydi.

---

# BANDLAR

Har bandda: **Qayerdan topish · Qanday skrinshot · Nimani yashirish · Nimaga tegmaslik · Javob formati · Nega kerak (BinOS tomoni)**.

⚠️ **Konfiguratsiya NOMA'LUM.** 1-band javobigacha do'konda Розница 2 / УТ 11 / УНФ / Розница 3 dan qaysi biri
turgani bilinmaydi. Shuning uchun **quyidagi HAR BIR menyu yo'li `(экранда tekshirilsin)` belgisi bilan** — ular
manbalarda tasdiqlanmagan. Mavjud 3 ta eksport fayli (sena / astatka / Список9) konfiguratsiyani aniqlamaydi:
hisobot sarlavhalari Розница va УТ da bir xil (so'rovnoma 376-satr).

**Nimani yashirish** bandlarida umumiy qoida (so'rovnoma 84–90-satrlar):
**YASHIRISH** — parol, litsenziya raqami / PIN, AnyDesk yoki masofaviy kirish ID+paroli, odamlarning telefoni va e-mail'i, bank rekvizitlari va karta raqamlari.
**YASHIRMASLIK** — tovar nomi, narx, ombor nomi, 1C versiyasi, baza nomi va `File=` / `Srvr=` / `ws=` bilan boshlanadigan satr.

---

## Band 1. «О программе» — platforma versiyasi, konfiguratsiya nomi va versiyasi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 1** (98–108-satrlar).

**Qayerdan topish**

| Konfiguratsiya | Yo'l |
|---|---|
| Har qanday (o'ng yuqorida ☰ tugmasi bor) | ☰ «Сервис и настройки» → «О программе» *(экранда tekshirilsin)* |
| Har qanday (☰ yo'q) | chap yuqorida «Главное меню» (yoki menyu satri) → «Справка» → «О программе» *(экранда tekshirilsin)* |

> Ruscha: «Откройте, пожалуйста, "О программе" — мне нужны только три строки: версия платформы, название и версия конфигурации.»

**Qanday skrinshot**

- **1 kadr:** «О программе» oynasi **to'liq** — platforma versiyasi, konfiguratsiya nomi, konfiguratsiya versiyasi va informatsion baza satri bitta kadrda.
- Oyna uzun bo'lsa — 2-kadr pastki qismi.
- Fayl: `B01-1.png` (`B01-2.png`).

**Nimani yashirish**

- litsenziya raqami;
- internet-qo'llab-quvvatlash logini (интернет-поддержка).

**Nimaga tegmaslik**

- ⚠️ oynadagi hech qanday havola bosilmaydi («Обновить», «Проверить обновления», «Настройки»);
- oyna faqat krestik bilan yopiladi;
- ⚠️ konfiguratsiya nomini **yozib olish shart**, yoddan yoki taxmin bilan yozilmaydi.

**Javob formati**

```
platforma:             8.3.__.____
konfiguratsiya nomi:   ____________________   (ekrandan AYNAN ko'chiring)
konfiguratsiya vers.:  __.__.__.__
infobase satri:        ____________________   (band 3 bilan bir xil bo'lishi mumkin)
skrinshot:             B01-1.png
```

**Nega kerak (BinOS tomoni):** `infobase.platform_version`, `configuration_name`, `configuration_version` —
bundle'da **UCHALASI MAJBURIY, bo'sh bo'lmagan matn** (`bundle.py:160-161`); ularsiz yaroqli fayl umuman
tug'ilmaydi. Bundan tashqari qoldiq / narx / shtrix-kod registrlarining nomlari har konfiguratsiyada boshqacha —
shu javobsiz extractor'da **bitta ham so'rov yozilmaydi**.

---

## Band 2. Konfiguratsiya o'zgartirilganmi yoki standart

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 1(а)** (110-satr).

**Qayerdan topish**

- Asosan **og'zaki savol** administratorga yoki xizmat ko'rsatuvchi firmaga.
- Qo'shimcha (agar administrator o'zi ko'rsatsa, faqat ko'rish uchun) *(экранда tekshirilsin)*:
  - «Администрирование» → «Общие настройки» → «Дополнительные реквизиты и сведения»;
  - «Администрирование» → «Печатные формы, отчеты и обработки» → «Дополнительные отчеты и обработки».

> Ruscha: «Программист или обслуживающая фирма вносили изменения в вашу 1С — дополнительные поля, свои отчёты, обмен с кассой или весами? Да / нет / не знаю.»

**Qanday skrinshot**

- Ixtiyoriy, faqat administrator o'zi ochsa: qo'shimcha rekvizitlar ro'yxati — **1 kadr**, `B02-1.png`.
- Ro'yxat uzun bo'lsa: faqat «Номенклатура» guruhi ko'rinadigan qism.

**Nimani yashirish**

- ro'yxatda parol yoki kassa/tarozi kirish ma'lumoti ko'rinsa — o'sha qator qora to'rtburchak bilan yopiladi (Paint → «Фигуры» → «Прямоугольник» → «Заливка: сплошной цвет» → «Цвет 2: чёрный»).

**Nimaga tegmaslik**

- ⚠️ «Администрирование» bo'limida galochkalar **darhol** ishlaydi — hech qaysi galochkaga tegmang;
- ⚠️ ro'yxatdagi element **ochilmaydi va tahrirlanmaydi**, faqat ro'yxat ko'rinishi;
- ⚠️ «Добавить», «Изменить», «Удалить» bosilmaydi.

**Javob formati**

```
o'zgartirilganmi:      ha / yo'q / bilmayman
kim xizmat ko'rsatadi: ____________________   (firma nomi yoki ism; telefon — faqat og'zaki)
yaqin oyda 1C yangilash rejasi: ha (qachon: ______) / yo'q / bilmayman
qo'shimcha rekvizitlar ro'yxati ko'rildimi: ha (B02-1.png) / yo'q
```

**Nega kerak (BinOS tomoni):** o'zgartirilgan bo'lsa «Весовой» va PLU kabi rekvizitlar **tipik joyda turmaydi**,
va qo'shimcha rekvizitlar `.cf` ga **KIRMAYDI** (so'rovnoma 328-satr). Bu javob band 4/5 dan qaysi biri
majburiy ekanini belgilaydi.

---

## Band 3. Infobase ulanishi — `File=` / `Srvr=` / `ws=`

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 2** (116–139-satrlar).

**Qayerdan topish**

- 1C ishga tushirilganda ochiladigan «Запуск 1С:Предприятия» oynasi (baza ro'yxati).
- Ishchi baza ustiga **bir marta bosiladi** — ochilmaydi. Oyna pastida ulanish satri chiqadi.
- Masofaviy ish stoli orqali ishlansa — **shu ish stolining ichida** bajariladi.
- Agar 1C bu oynasiz darhol ochilsa — bu bandning skrinshoti tashlanadi, satr band 1 dagi «О программе» oynasida ko'rinadi.

> Ruscha: «Щёлкните один раз по рабочей базе, не открывая её. Внизу окна появится строка — она мне и нужна.»

**Qanday skrinshot**

- **1 kadr:** «Запуск 1С:Предприятия» oynasi to'liq — baza ro'yxati **va** pastdagi satr bitta kadrda.
- Fayl: `B03-1.png`.

**Nimani yashirish**

- ro'yxatdagi baza nomida odam ismi bo'lsa ham **yashirilmaydi** (baza nomi kerak);
- ⚠️ ulanish satri **yashirilmaydi** — `File=` / `Srvr=` / `ws=` to'liq ko'rinishi shart (so'rovnoma 90-satr);
- foydalanuvchi nomi / parol maydoni ko'rinsa — yashiriladi;
- ⚠️ satr yashirilmasa ham, u **do'kon serverining manzili** — `B03-1.png` faqat **bitta shaxsiy chatga**
  yuboriladi (0.1-bo'lim), guruhga, kanalga yoki umumiy bulutga **hech qachon**.

**Nimaga tegmaslik**

- ⚠️ «Изменить», «Добавить», «Удалить» — **hech qachon**;
- baza **ochilmaydi** (bir marta bosish yetarli);
- ⚠️ «1С:Предприятие» va «Конфигуратор» tugmalari bu bandda bosilmaydi.

**Javob formati**

```
ulanish turi:          File= / Srvr= / ws= / boshqa: ______
satr (birinchi 1–2 so'z): ____________________
nechta baza bor:       __  (nomlari va vazifasi: ______________________)
kassa QAYSI bazada ishlaydi: ____________________ / bilmayman
bazalar orasida avtomatik almashinuv: ha / yo'q / bilmayman
astatka + sena + Список9 shu bazadanmi: ha / yo'q / bilmayman
kirish usuli: shu kompyuterda / do'kondagi serverda / RDP / AnyDesk / brauzer / bilmayman
1C turgan mashinaning soati (ekran burchagidan): __:__ / bilmayman
  telefondagi vaqtga to'g'ri keladimi: ha / yo'q (farq __ daqiqa) / bilmayman
skrinshot:             B03-1.png
```

⚠️ **Soat nima uchun so'raladi.** Bundle'dagi `snapshot_at` **offset bilan** bo'lishi shart
(`bundle.py:137-143`). Do'konning fuqarolik zonasi ma'lum (Asia/Bishkek), lekin 1C turgan mashinaning
soati shu bilan bir xilligi tekshirilmagan — bu alohida fakt (dependency matrix `D12`).
⚠️ Soat **o'zgartirilmaydi**, sana/vaqt sozlamalari oynasi **ochilmaydi** — faqat ekran burchagidagi qiymat
o'qiladi (bu band uchun qo'shimcha vaqt kerak emas).

**Nega kerak (BinOS tomoni):** extractor **qayerda ishga tushirilishi** va `.dt` nusxa olish mumkinmi —
shu javobdan kelib chiqadi. ⚠️ Eng jim xavf: **noto'g'ri bazadan** olingan eksport BinOS'ning barcha
tekshiruvlaridan **O'TADI**, lekin eskirgan bo'ladi — kod buni tuta olmaydi.

---

## Band 4. `.dt` nusxa olish mumkinmi (eng muhim band)

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 3** (143–177-satrlar) va «Правила для копии базы» (197–208).

**Qayerdan topish**

- **Do'konda nusxa OLINMAYDI.** Bu bandda faqat **rozilik va reja** kelishiladi.
- Nusxa keyin, **do'kon yopilganda** va smenalar yopilgandan keyin, administrator tomonidan olinadi.
- Nusxa yo'li (administrator uchun, kelajakdagi kun) *(экранда tekshirilsin)*:
  - har qanday baza: Konfigurator → «Администрирование» → «Выгрузить информационную базу…» → `.dt`;
  - faqat `File=` bazasi: 1C va Konfigurator yopilgandan keyin butun papka nusxasi (ichida `1Cv8.1CD`).

> Ruscha: «Копию делаем не сегодня. Сегодня мне нужно только ваше решение и имя администратора, который её сделает.»

⚠️ **Kechiktirilgan savolni oldinga surish** (so'rovnoma 350-satr, eski 5-savol — **yangi savol emas**):
extractor `.epf` faylini do'konda umuman ishga tushirish mumkinmi. Nusxa bo'lmasa, bu yagona yo'l bo'lib qoladi.

> Ruscha: «Можно ли у вас вообще открывать внешние обработки (.epf)? Есть ли запрет безопасного режима? Сегодня мы ничего не открываем — это вопрос на будущее.»

**Qanday skrinshot**

- Bugun: **skrinshot yo'q**.
- Nusxa keyinroq olingach (administrator yuboradi): `.dt` yoki `1Cv8.1CD` turgan papka — nom, sana, hajm ko'rinadigan **1 kadr**, `B04-1.png`.

**Nimani yashirish**

- papka yo'lida odam ismi bo'lsa — faqat shu qism kesiladi;
- fayl nomi, sanasi va hajmi **yashirilmaydi**;
- ⚠️ **masofaviy kirish (AnyDesk/RDP) ID va paroli — hech qayerda yozilmaydi**: na shablonga, na chatga.
  So'rovnomaning oxirgi savolidagi shart aynan takrorlanadi (192–195-satrlar): **ulanishni egasi o'zi boshlaydi**,
  ID va parol **faqat telefonda og'zaki** aytiladi, egasi butun seansni **kuzatib turadi** va tugashi bilan
  dasturni **o'zi yopadi**. Kuzatuvsiz («unattended») kirish so'ralmaydi va qabul qilinmaydi.

**Nimaga tegmaslik**

- ⚠️ **«Загрузить информационную базу…» — HECH QACHON.** Bu ishchi bazani o'chiradi;
- ⚠️ bugun Konfigurator **umuman ochilmaydi**;
- ⚠️ hech qanday `.epf` ochilmaydi va sinalmaydi;
- XML «Выгрузка», «Конвертация данных» va Excel **nusxa o'rniga yaramaydi** — ularda ma'lumotning faqat bir qismi bo'ladi.

**Javob formati**

```
nusxa bera oladimi:    ha / yo'q / egasining roziligi kerak / bilmayman
kim qiladi:            ____________________   (Konfiguratorga to'liq kirish bor odam)
qachon:                ____________  (do'kon yopilgan kun)
tashuvchi:             fleshka __ GB / tashqi disk  (Telegram / e-mail / bulut — YO'Q)
egasining yozma roziligi olindimi: ha / yo'q
nusxa kuni 3 ta nazorat hisoboti kelishildimi (astatka / sena / Список9 + vaqt): ha / yo'q
.epf ochish mumkinmi (kelajak uchun): ha / yo'q / bilmayman / xavfsiz rejim taqiqlaydi
masofadan bir marta kuzatuv ostida ko'rish mumkinmi: ha / yo'q
```

**Nega kerak (BinOS tomoni):** 2026-08 dagi 3 ta eksport faylida **Ссылка/GUID, Код va Артикул ustunlari YO'Q**
(so'rovnoma 370-satr). GUID'siz **har bir qator `MISSING_GUID` bilan bloklanadi** (`normalize.py:198-199`) va
avtomatik moslashtirish umuman ishlamaydi — EXACT_MATCH faqat GUID orqali bo'ladi (`classify.py:335`).
Ya'ni **mavjud fayllar bilan cutover qilib bo'lmaydi**; GUID faqat nusxa yoki 1C ichidagi `.epf` orqali olinadi.

---

## Band 5. `.cf` / `.cfe` bormi (faqat nusxa YO'Q bo'lsa)

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 3, «Если НЕТ»** (179–191-satrlar).

**Qayerdan topish**

- Bu ham **bugun bajarilmaydi** — administrator bilan kelishiladi.
- Yo'l (administrator uchun, kelajakdagi kun) *(экранда tekshirilsin)*:
  - Konfigurator → «Конфигурация» → «Конфигурация базы данных» → «Сохранить конфигурацию БД в файл…» → `.cf`;
  - kengaytmalar bo'lsa: «Конфигурация» → «Расширения конфигурации» → kengaytmani tanlash → «Конфигурация» → «Сохранить в файл…» → `.cfe`.

⚠️ **`.cf`/`.cfe` ham «nusxa qoidalari» ostida** (so'rovnoma 197–200-satrlar: 1 va 2-qoida bu fayllarga ham tegishli):

- **egasining yozma roziligi** — `.dt` bilan bir xil shart, «bu shunchaki struktura» deb o'tkazib yuborilmaydi;
- ⚠️ **konfiguratsiya o'zgartirilgan bo'lsa, u xizmat ko'rsatuvchi firmaning mehnati** bo'lishi mumkin —
  uni berish egasi bilan firma orasidagi shartnomaga taalluqli. So'rovni **egasi** firmaga qo'yadi;
  operator firmani chetlab o'tib xodimdan fayl so'ramaydi;
- **qo'ldan-qo'lga fleshkada**, Telegram / e-mail / bulut orqali **YO'Q**; ish tugagach o'chiriladi va
  egasiga yozma xabar beriladi.

> Ruscha: «В этих файлах данных магазина в основном нет — это только структура программы. Но программист мог вписать туда пароли от кассы или весов, спросите его, пожалуйста.»

**Qanday skrinshot**

- Bugun: **skrinshot yo'q**. Fayl kelgach: papka ko'rinishi, `B05-1.png`.

**Nimani yashirish**

- fayl yo'lidagi odam ismi.

**Nimaga tegmaslik**

- ⚠️ Konfiguratorda **«Снять с поддержки», «Включить возможность изменения», «Обновить конфигурацию базы данных»** — hech qachon;
- ⚠️ kengaytmalar oynasida **«Загрузить из файла…» va «Удалить»** — hech qachon;
- ⚠️ Konfigurator har qanday savolga — «Нет» yoki «Отмена» (faqat eksportning o'zini tasdiqlashdan boshqa).

**Javob formati**

```
.cf bera oladimi:      ha / yo'q / bilmayman
kengaytma (.cfe) bormi: ha (nechta: __) / yo'q / bilmayman
.cf/.cfe ichida kassa yoki tarozi paroli bormi (dasturchidan so'ralgan): ha / yo'q / bilmayman
```

**Nega kerak (BinOS tomoni):** `.cf` bo'sh mahalliy bazaga yuklanib, extractor so'rovlari **ma'lumotsiz
kompilyatsiya qilinadi va tekshiriladi**. ⚠️ Lekin qo'shimcha rekvizitlar (band 2) `.cf` ga kirmaydi —
demak `.cf` yolg'iz o'zi `is_weighted` va `plu` manbasini ochmaydi.

---

## Band 6. Kassir savdosi qayerda bajariladi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 4(а)** (217-satr).

**Qayerdan topish**

- **Og'zaki savol** — katta kassirga. Ekran kerak emas.
- Aniqlash uchun: kassa kompyuteridagi oynaning sarlavhasiga qarash mumkin (ochilgan bo'lsa), lekin **hech narsa bosilmaydi**.

> Ruscha: «В какой программе вы пробиваете чеки: в самой 1С (рабочее место кассира, "РМК"), или в отдельной программе — Frontol, Штрих-М, 1С:Касса, другая?»

**Qanday skrinshot**

- Skrinshot **kerak emas**. Alohida dastur bo'lsa — nomi va versiyasi ko'rinadigan sarlavha fotosi ixtiyoriy: `B06-1.jpg`.

**Nimani yashirish**

- kassir ismi va login'i ekranda ko'rinsa — yashiriladi;
- chek raqami, summa — yashirilmaydi.

**Nimaga tegmaslik**

- ⚠️ ochiq smenali kassa dasturida **hech narsa bosilmaydi** — chek ochilib qolishi mumkin;
- ⚠️ «Закрыть смену», «Отчёт», «X-отчёт», «Z-отчёт» — **hech qachon**.

**Javob formati**

```
kassir dasturi:        1C ichida (РМК) / Frontol / Штрих-М / 1С:Касса / boshqa: ______ / bilmayman
versiyasi (bilsa):     ____________
nechta kassa ishlaydi: __
```

**Nega kerak (BinOS tomoni):** savdo 1C'dan tashqarida bo'lsa, 1C qoldig'i **haqiqatdan katta** bo'ladi.
Buni kod aniqlay olmaydi — migratorda faqat «eskirgan snapshot» darvozasi bor (`apply.py:125-127`).
Ya'ni qoldiqning haqiqiyligi butunlay cutover kunidagi **«final fresh snapshot + freeze»** qadamiga tayanadi.

---

## Band 7. Savdo 1C'ga qachon tushadi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 4(б)(в)** (218–220-satrlar).

**Qayerdan topish**

- **Og'zaki savol** — katta kassirga va buxgalterga. Ikkalasining javobi farq qilsa — **ikkalasini ham yozing**.

> Ruscha: «Когда продажа уменьшает остаток в 1С: сразу, при закрытии смены, вечером, или при ручной загрузке? Бывает, что продажи попадают в 1С на следующий день или позже?»

**Qanday skrinshot**

- Skrinshot **kerak emas**.

**Nimani yashirish**

- —

**Nimaga tegmaslik**

- ⚠️ tekshirish uchun **hech qanday hujjat ochilmaydi va «Провести» bosilmaydi**;
- ⚠️ «Загрузить из кассы», «Обмен с кассой» — hech qachon.

**Javob formati**

```
qachon kamaytiradi:    darhol / smena yopilganda / kechqurun / qo'lda yuklanganda / bilmayman
kechikish bo'ladimi:   ha (necha kun: __) / yo'q / bilmayman
kim aytdi:             katta kassir / buxgalter / egasi
javoblar farq qildimi: yo'q / ha — ikkinchi javob: ______________________
oxirgi yuklanish vaqti (bilsa): __:__
```

**Nega kerak (BinOS tomoni):** bu javob **«short freeze» oynasining uzunligini** belgilaydi. Apply eski yoki
**TENG** `snapshot_at` ni `StaleSnapshotError` bilan rad etadi (`apply.py:125-127`) — ya'ni final snapshot vaqti
noto'g'ri bo'lsa, **ikkinchi urinish ham bloklanadi**.

---

## Band 8. Haqiqiy qoldiq qaysi omborda

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 5(а)** (230-satr) va omborlar ro'yxati (236–239).

**Qayerdan topish**

Omborlar/magazinlar ro'yxati — **hammasi `(экранда tekshirilsin)`**:

| Konfiguratsiya | Yo'l |
|---|---|
| Розница 2 | «НСИ» → «Склады» yoki «НСИ» → «Магазины» *(экранда tekshirilsin)* |
| Управление торговлей 11 | «НСИ и администрирование» → «НСИ» → «Склады и магазины» *(экранда tekshirilsin)* |
| Розница 3 / УНФ | «Компания» → «Склады и магазины» *(экранда tekshirilsin)* |

⚠️ Qaysi konfiguratsiya ekani band 1 dan bilinadi. Band 1 dan oldin bu bandga o'tmang.

> Ruscha: «На каком складе в 1С числится товар, который реально стоит в зале?»

**Qanday skrinshot**

- **1–2 kadr:** omborlar/magazinlar ro'yxati, **BARCHA qatorlar**. Ro'yxat uzun bo'lsa aylantirib 2-kadr.
- Fayl: `B08-1.png`, `B08-2.png`.
- Mavjud `astatka.xls` da «Магазин» → «Основной» guruhi ko'rilgan (so'rovnoma 368-satr) — ⚠️ lekin «Основной»
  **haqiqiy zal ombori ekani TASDIQLANMAGAN**, shuni og'zaki aniqlang.

**Nimani yashirish**

- ombor nomlari **yashirilmaydi**;
- ro'yxatda mas'ul shaxs telefoni ko'rinsa — yashiriladi.

**Nimaga tegmaslik**

- ⚠️ ombor kartochkasi **ochilmaydi va o'zgartirilmaydi**;
- ⚠️ «Создать», «Пометить на удаление» — hech qachon;
- ro'yxatdagi filtr/saralash **o'zgartirilmaydi**.

**Javob formati**

```
omborlar ro'yxati (ekrandan AYNAN):
  1. ______________________
  2. ______________________
  3. ______________________
haqiqiy ZAL qoldig'i qaysi omborda: ______________________ / bilmayman
«Основной» — bu zal omborimi:  ha / yo'q / boshqa nom: ______
boshqa omborlar nima uchun:    ______________________
BinOS filiallari soni:         __   (ombor → filial 1:1 bo'lishi SHART)
skrinshot:                     B08-1.png
```

**Nega kerak (BinOS tomoni):** `selection.warehouse_guids` **bo'sh bo'la olmaydi** (`bundle.py:176-177`) va
`warehouse_branch` xaritasi uni **AYNAN qoplashi** shart; ⚠️ **ikki ombor bitta BinOS filialiga xaritalanmaydi**
(`mapping.py:227-228`). ⚠️ Eng jim xato: tanlanmagan ombor qoldig'i faylda bo'ladi, lekin **migratsiya qilinmaydi**
(`normalize.py:286-292`) — natijada **jimgina nol qoldiq** chiqadi.

---

## Band 9. Qoldiq hisoboti nomi (va uning sozlamalari)

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 5(б)** (231, 240–249-satrlar).

**Qayerdan topish**

| Konfiguratsiya | Yo'l |
|---|---|
| Розница 2 | «Склад» → «Отчеты по складу» → «Остатки на складах» *(экранда tekshirilsin)* |
| Управление торговлей 11 | «Склад и доставка» → «Отчеты по складу» → «Ведомость по товарам на складах» *(экранда tekshirilsin)* |
| Розница 3 / УНФ | — *(экранда tekshirilsin — yo'l manbalarda yo'q, administrator ko'rsatadi)* |

Bugungi sanani qo'ying → «Сформировать». **Sana o'zgartirish va «Сформировать» — ruxsat etilgan amallar**
(so'rovnoma 1-qoida, 64-satr), lekin uch shart bilan:

1. ⚠️ **Avval eski sanani yozib oling** (yoki o'zgartirishdan oldin bitta kadr oling). Ba'zi 1C hisobotlari
   foydalanuvchi sozlamasini **yopilganda o'zi eslab qoladi** — ish tugagach **eski sana/davr qaytariladi**,
   shunda ertaga egasi odatdagi ko'rinishni ko'radi.
2. ⚠️ **Sanani do'konning o'z xodimi qo'yadi** (0-bo'lim, «Kim sichqonchani ushlaydi»).
3. ⚠️ **Ish vaqtida og'ir hisobot** serverni sekinlashtirishi mumkin. Avval so'rang: «сейчас можно, не помешает
   кассе?». Faqat **bugungi sana** uchun shakllantiring, uzoq davr olinmaydi. Hisobot osilib qolsa —
   **1C ni majburan yopmang**, xodimga ayting.

> Ruscha: «Каким отчётом вы сами проверяете остатки и доверяете ли ему? Поставьте, пожалуйста, сегодняшнюю дату и нажмите "Сформировать".»

**Qanday skrinshot — 3 kadr, uchalasi ham MAJBURIY**

1. `B09-1.png` — hisobot **yuqorisi**: nomi, sanasi, ombor, hamda **variant nomi** (hisobot ustida ko'rinadi).
2. `B09-2.png` — hisobot **pasti**: **«Итого» qatori to'liq ko'rinishi shart**.
3. `B09-3.png` — «Настройки…» (yoki «Ещё» → «Настройки…») oynasi *(экранда tekshirilsin)*. ⚠️ Bu oynada **faqat vkladkalarni** bosing va
   har vkladkani alohida suratga oling. Vkladka bo'lmasa — oynani borligicha oling.
   Oynani **krestik** bilan yoping.

**Nimani yashirish**

- tovar nomlari, miqdorlar, «Итого» — **yashirilmaydi** (bular kerak);
- hisobot pastida foydalanuvchi ismi chiqsa — yashiriladi.

**Nimaga tegmaslik**

- ⚠️ **«Выбрать вариант» bosilmaydi** — variant nomini faqat o'qing;
- ⚠️ «Настройки…» oynasida **ko'rinish turi pereklyuchateli (вид отчёта) o'zgartirilmaydi**, galochka qo'yilmaydi/olinmaydi;
- ⚠️ «Сохранить настройки», «Сохранить вариант отчёта» — hech qachon;
- ⚠️ hisobot oynasi yopilayotganda «Сохранить изменения?» / «Сохранить настройки?» chiqsa — **«Нет»**;
- hisobotni Excel'ga saqlash ruxsat etiladi (agar so'ralsa), lekin bugun shart emas —
  ⚠️ saqlangan fayl **do'kon kompyuterida qoldirilmaydi** (0.1-bo'lim).

**Javob formati**

```
hisobot nomi (ekrandan AYNAN): ______________________
variant nomi:                  ______________________
sana qo'yildi:                 2026-__-__   vaqt: __:__
«Итого» qiymati:               ______________   (AYNAN ko'chiring, yuvarlamang)
qaysi ko'rsatkich (sozlamalar oynasidan): Конечный остаток / В наличии / Доступно / boshqa: ______ / ko'rinmadi
egasi shu hisobotga ishonadimi: ha / yo'q / bilmayman
skrinshotlar:                  B09-1.png · B09-2.png · B09-3.png
```

**Nega kerak (BinOS tomoni):** `manifest.stock_qty_by_warehouse` 1C **ichida** hisoblanadi va BinOS uni fayldan
**mustaqil qayta hisoblab** solishtiradi — bu **yagona «eksport to'liq» isboti**
(`BINOS_1C_BUNDLE_V1.md:95-97`, `classify.py:225-232`). ⚠️ Qaysi qoldiq ko'rsatkichi (Конечный остаток / В наличии /
Доступно) olinishi **faqat `B09-3.png` dan** aniqlanadi — u bo'lmasa extractor qaysi resursni o'qishi yozilmaydi.
`reconciliation.ok = false` bo'lsa dry-run **3** qaytaradi (`app/tools/migrate_1c.py:147`) va reja **umuman
qurilmaydi** — ya'ni apply bosqichiga yetib ham bo'lmaydi (`mapping.py:181`).

---

## Band 10. «Виды цен» — narx turlari ro'yxati

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 6** (264–269-satrlar).

**Qayerdan topish**

| Konfiguratsiya | Yo'l |
|---|---|
| Розница 2 | «Маркетинг» → «Ценообразование» → «Виды цен» *(экранда tekshirilsin)* |
| Управление торговлей 11 | «CRM и маркетинг» → «Настройки и справочники» → «Виды цен» *(экранда tekshirilsin)* |
| Розница 3 / УНФ | «Продажи» → «Цены и скидки» → «Виды цен» *(экранда tekshirilsin)* |

> Ruscha: «Покажите, пожалуйста, список "Виды цен" целиком — мне нужны только названия, ничего открывать и менять не будем.»

**Qanday skrinshot**

- **1–2 kadr:** «Виды цен» ro'yxati **to'liq**, barcha qatorlar. Fayl: `B10-1.png`.
- Agar egasi kartochkalarni ko'rsatsa: «Розничная цена» va «Цена поставщика» kartochkalari, **oxirigacha aylantirib**,
  yuqoridan pastga bir necha kadr: `B10-2.png`, `B10-3.png`.
- Mavjud `sena.xls` da aynan ikkita tur ko'rilgan: «Розничная цена» va «Цена поставщика», ikkalasi «Включает НДС»
  (so'rovnoma 367-satr). ⚠️ Bu ro'yxatning **to'liqligini isbotlamaydi** — ekrandagi ro'yxat kerak.

**Nimani yashirish**

- narx turlari nomlari va narxlar **yashirilmaydi**;
- kartochkada mas'ul shaxs yoki kontragent telefoni ko'rinsa — yashiriladi.

**Nimaga tegmaslik**

- ⚠️ kartochka **faqat krestik** bilan yopiladi, «Сохранить изменения?» ga — **«Нет»**;
- ⚠️ «Записать», «Записать и закрыть», «Установить цены», «Создать» — hech qachon;
- formula yoki naценка maydoniga **kursor qo'yilmaydi**.

**Javob formati**

```
narx turlari (ekrandan AYNAN, hammasi):
  1. ______________________
  2. ______________________
  3. ______________________
kartochka skrinshotlari:      B10-2.png · B10-3.png / olinmadi
skrinshot:                    B10-1.png
```

**Nega kerak (BinOS tomoni):** `price_types[]` fayl ichida ishlatilgan **har bir** narx turini e'lon qilishi shart:
`prices[].price_type_guid` shu ro'yxatda bo'lmasa fayl **rad etiladi** (`bundle.py:222-223`), `selection` dagi
chakana/kelish turi ham ro'yxatda bo'lishi kerak (`bundle.py:191-193`). Ekrandagi to'liq ro'yxat esa **tanlash
uchun** kerak: band 11 da qaysi tur kassaniki ekani ro'yxatdan ko'rsatiladi. Ro'yxat to'liq bo'lmasa,
extractor'ning chiqishi bundle validatsiyasidan o'tmaydi.

---

## Band 11. Kassada ishlatiladigan narx turi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 6(а)(б)(в)** (258–260-satrlar).

**Qayerdan topish**

- **Og'zaki savol** — egasiga yoki buxgalterga. Band 10 ning ro'yxati oldida turib so'ralsa aniqroq bo'ladi.

> Ruscha: «По какой именно цене продаёт касса — "Розничная цена" или другой вид цены? Розничная цена вводится вручную документом или считается автоматически из "Цены поставщика" с наценкой? "Цена поставщика" обновляется при каждом поступлении, вручную, или давно не обновлялась?»

**Qanday skrinshot**

- Skrinshot **kerak emas** (band 10 kadrlari yetarli).

**Nimani yashirish**

- —

**Nimaga tegmaslik**

- ⚠️ tekshirish uchun **«Установка цен номенклатуры» hujjati ochilmaydi va «Провести» bosilmaydi**;
- ⚠️ «Пересчитать», «Заполнить», «Рассчитать» — hech qachon.

**Javob formati**

```
kassa qaysi narx turi bilan sotadi: ______________________ / bilmayman
chakana narx: qo'lda (hujjat bilan) / avtomatik (наценка bilan «Цена поставщика» dan) / bilmayman
«Цена поставщика» yangilanadimi: har kirimda avtomatik / qo'lda / uzoq vaqt yangilanmagan / bilmayman
chakana va kelish narxi turlari BIR XIL emasmi: tasdiqlandi / bir xil / bilmayman
```

**Nega kerak (BinOS tomoni):** ⚠️ **Eng xavfli bo'shliq.** `selection.retail_price_type_guid` MAJBURIY
(`bundle.py:181-185`), va **noto'g'ri narx turi butun katalogga noto'g'ri narx beradi — bundle darajasida
HECH QANDAY XATO BERMAYDI.** Shuningdek `purchase_price_type_guid` chakanadan **farq qilishi shart**, aks holda
fayl rad etiladi (tannarx chakana narxga teng bo'lib qolardi). ⚠️ Narx **avtomatik** hisoblansa, registrdan
oddiy o'qish **bo'sh yoki eskirgan** narx beradi — extractor boshqa manbadan o'qishi kerak bo'ladi.

---

## Band 12. Oddiy tovar kartochkasi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 7** (274–293-satrlar).

**Qayerdan topish**

| Konfiguratsiya | Yo'l |
|---|---|
| Розница 2 | «НСИ» → «Номенклатура» *(экранда tekshirilsin)* |
| Управление торговлей 11 | «НСИ и администрирование» → «Номенклатура» *(экранда tekshirilsin)* |
| Розница 3 / УНФ | «Продажи» → «Номенклатура» *(экранда tekshirilsin)* |

Qidiruv satriga nomning **bir qismini** kiriting va oddiy **donali** tovarni (masalan ichimlik) **ikki marta bosib** oching.

> Ruscha: «Откройте, пожалуйста, любой обычный штучный товар — например напиток. Мне нужно увидеть, где у вас код, артикул и единица измерения.»

**Qanday skrinshot — 2–4 kadr**

- Kartochkani **oxirigacha aylantirib**, yuqoridan pastga ketma-ket kadrlar: `B12-1.png` … `B12-4.png`.
- Yig'ilgan guruhlar **guruh sarlavhasini bosib** ochiladi (⚠️ galochkani emas).
- «Штрихкоды» havolasi bo'lsa — ochib, alohida kadr: `B12-5.png`.
- Kadrda ko'rinishi **shart**: «Код», «Артикул», «Единица измерения», «Вид номенклатуры», «Весовой» (bo'lsa).

**Nimani yashirish**

- tovar nomi, kodi, artikuli, narxi, birligi — **yashirilmaydi**;
- kartochkada yetkazib beruvchining telefoni yoki shartnoma raqami ko'rinsa — yashiriladi.

**Nimaga tegmaslik**

- ⚠️ **«Записать», «Записать и закрыть», «Провести»** — hech qachon;
- ⚠️ hech qanday maydonga yozilmaydi, galochka qo'yilmaydi/olinmaydi;
- kartochka **krestik** bilan yopiladi, «Сохранить изменения?» ga — **«Нет»**;
- ⚠️ kartochka **uzoq ochiq qoldirilmaydi** — suratga olib bo'lgach darhol yoping: ochiq kartochka 1C'da o'sha
  tovarni boshqa foydalanuvchi (kassa almashinuvi, narx yangilash) uchun **band qilib qo'yishi mumkin**;
- ⚠️ «Объект заблокирован…» kabi xabar chiqsa — bu tovar bilan **boshqa odam ishlayapti**: hech narsa
  «majburan» qilinmaydi, oyna yopiladi va boshqa tovar tanlanadi;
- ⚠️ «Штрихкоды» oynasida «Создать», «Печать этикеток» bosilmaydi.

**Javob formati**

```
«Код» maydoni bormi:      ha (qiymat namunasi: ________) / yo'q
  oldingi nollar bilanmi: ha / yo'q
«Артикул» maydoni bormi:  ha (namunasi: ________) / yo'q / bo'sh
«Единица измерения»:      ekrandagi nom AYNAN: ________
«Вид номенклатуры»:       ________________  (товар / услуга / набор / boshqa)
«Весовой» rekviziti bormi: ha (qayerda: ____________) / yo'q / ko'rinmadi
«Штрихкоды» havolasi bormi: ha / yo'q
skrinshotlar:             B12-1.png … B12-_.png
```

**Nega kerak (BinOS tomoni):** 1C «Код» BinOS `sku` ga yoziladi, yangi mahsulot artikuli esa
**deterministik zanjir** bo'yicha tanlanadi: `article → code → 1C-<guid>` (`mapping.py:492-505`;
`fallback_article` = `1C-<guid>`, `classify.py:521`). ⚠️ **Ikkalasi ham faqat CREATE yo'lida** — LINK
qilingan mavjud BinOS mahsulotining `sku` va `article_code` i **o'zgarmaydi** (LINK operatsiyasida bu
maydonlar umuman yo'q: `mapping.py:512-523`). Band 17 dagi `plu` bilan ayni cheklov. ⚠️ Mavjud 3 ta
eksport faylida **Код va Артикул ustunlari YO'Q** edi (so'rovnoma 370-satr) — shuning uchun ular kartochkada
qayerda turishini ko'rish shart. `kind` MAJBURIY va faqat {goods, service, set, other} dan biri bo'ladi
(`bundle.py:201`).

---

## Band 13. Vaznli / tarozi tovar kartochkasi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 7** (291-satr — ikkinchi kartochka).

**Qayerdan topish**

- Band 12 bilan ayni ro'yxat («Номенклатура»).
- Qidiruv satriga **nomida tarozi kodi bor** tovarni kiriting. Mavjud dalil bo'yicha nomlar shunday yozilgan:
  `148Код`, `Код594`, `476Корд` (so'rovnoma 372-satr — 465 ta topilgan, 2 tasi takror).
- Qidiruvga `Код` yoki `Корд` so'zini kiritish yetarli.

> Ruscha: «А теперь откройте, пожалуйста, весовой товар — тот, у которого в названии есть код, например "148Код". Мне нужно то же самое: код, единица, и есть ли признак "весовой".»

**Qanday skrinshot — 2–4 kadr**

- Xuddi band 12 kabi, oxirigacha: `B13-1.png` … `B13-4.png`.
- ⚠️ **Alohida diqqat:** «Весовой» rekviziti bor-yo'qligi ko'rinadigan qism **albatta** kadrga tushsin.
- Nomdagi kod (`148`) va kartochkadagi «Код» maydoni **bir xilmi yoki boshqami** — ikkalasi bitta kadrda ko'rinsa yaxshi.

**Nimani yashirish**

- nomi, kodi, narxi, birligi — **yashirilmaydi**.

**Nimaga tegmaslik**

- band 12 dagi barcha ⚠️ taqiqlar shu yerda ham amal qiladi;
- ⚠️ **«Печать этикеток» bosilmaydi** — printerga ish yuborilib qolishi mumkin.

**Javob formati**

```
tovar nomi (AYNAN):        ______________________
nomdagi kod:               ______
kartochkadagi «Код»:       ______   (nomdagi kod bilan bir xilmi: ha / yo'q)
birlik (AYNAN):            ______   (кг / кг. / килограмм / boshqa)
«Весовой» rekviziti:       ha, nomi «____________» / yo'q / ko'rinmadi
«Весовой» qayerda turadi:  kartochkada / «Вид номенклатуры» darajasida / faqat birlik кг / bilmayman
skrinshotlar:              B13-1.png … B13-_.png
```

**Nega kerak (BinOS tomoni):** ⚠️ **XAVFLI DEFAULT.** `is_weighted` null bo'lsa, qiymat **birlikdan** kelib chiqadi:
`unit_code == 'kg'` → weighted (`normalize.py:207`). Ya'ni «bilmayman» **xavfsiz emas** — kg birlikdagi **har bir**
tovar avtomatik vaznli bo'lib qoladi. Teskarisi ham xavfli: BinOS POS mahsulotni topishi uchun
**`is_weighted === true` VA PLU mosligi** birga kerak (`POSKassa.tsx:502`) — `is_weighted` noto'g'ri bo'lsa
etiketka **hech qachon ishlamaydi**. Birlik esa ANIQ jadval orqali aniqlanadi (`шт/кг/л/упак` + OKEI 796/166/112/778),
jadvalda yo'q nom → `UNKNOWN_UNIT` va butun qator siyosat talab qiladi (`normalize.py:176-184`).

---

## Band 14. Xarakteristikalar (variantlar)

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 7(а)** (279-satr).

**Qayerdan topish**

- **Og'zaki savol** + band 12/13 kartochkalarida «Характеристики» havolasi yoki vkladkasi bor-yo'qligiga qarash.

> Ruscha: «Делите ли вы один товар на варианты — по размеру, цвету или вкусу? В 1С это называется "Характеристики". Да / нет / не знаю.»

**Qanday skrinshot**

- Kartochkada «Характеристики» havolasi bo'lsa — **1 kadr**, `B14-1.png` (havola **ochilmaydi**, faqat borligi ko'rinsin).

**Nimani yashirish**

- —

**Nimaga tegmaslik**

- ⚠️ «Характеристики» ro'yxatida «Создать» bosilmaydi;
- ⚠️ «Использовать характеристики» galochkasiga **tegilmaydi** — u darhol ishlaydi.

**Javob formati**

```
xarakteristikalar ishlatiladimi: ha / yo'q / bilmayman
ha bo'lsa — taxminan nechta tovarda: __________ / bilmayman
kartochkada «Характеристики» ko'rindimi: ha / yo'q
214 ta takror nom guruhi variant bo'lishi mumkinmi (egasi fikri): ha / yo'q / bilmayman
```

**Nega kerak (BinOS tomoni):** ⚠️ **STOP-darvoza.** `has_characteristics = true` bo'lgan **har bir qator V1 da
BLOKLANADI** (`CHARACTERISTICS_UNSUPPORTED`, `normalize.py:318-319`) — migratsiya qilinmaydi. Javob «ha» bo'lsa,
pilot qamrovi qayta rejalashtiriladi. Bundan tashqari bu maydon bundle'da **MAJBURIY bool**, null bo'la olmaydi
(`bundle.py:202-203`) — ya'ni extractor uni haqiqatan hisoblashi shart.

---

## Band 15. Seriyalar (partiyalar)

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 7(б)** (280-satr).

**Qayerdan topish**

- **Og'zaki savol** + kartochkada «Серии» havolasi yoki «Срок годности» maydoni bor-yo'qligiga qarash.

> Ruscha: «Ведёте ли вы в 1С партии или сроки годности? В 1С это называется "Серии". Да / нет / не знаю.»

**Qanday skrinshot**

- «Серии» yoki «Срок годности» ko'rinsa — **1 kadr**, `B15-1.png`.

**Nimani yashirish**

- —

**Nimaga tegmaslik**

- ⚠️ «Использовать серии» galochkasiga **tegilmaydi**;
- «Серии» ro'yxati ochilsa ham hech narsa yaratilmaydi.

**Javob formati**

```
seriyalar/partiyalar ishlatiladimi: ha / yo'q / bilmayman
srok godnosti kuzatiladimi:         ha / yo'q / bilmayman
ha bo'lsa — qaysi tovarlarda:       ______________________
kartochkada «Серии» ko'rindimi:     ha / yo'q
```

**Nega kerak (BinOS tomoni):** `has_series = true` qatorni **bloklamaydi** — faqat `LOT_DATA_PRESENT` info
(`normalize.py:320-321`), va BinOS partiya kuzatuvi **yoqilmaydi**. ⚠️ Lekin BinOS tomonida allaqachon partiya
kuzatuvi yoqilgan mahsulot bo'lsa — **reja umuman qurilmaydi** (`mapping.py:190-191`). Bu maydon ham bundle'da
**MAJBURIY bool** (`bundle.py:202-203`).

---

## Band 16. Tarozi modeli va soni

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 8(а)(в)** (304, 306-satrlar).

**Qayerdan topish**

- **Zalga chiqing.** Tarozining **o'zida** — korpusdagi yorliqda marka va model yozilgan.
- Tarozi dasturi bo'lsa — kompyuterdagi dastur nomi (⚠️ faqat sarlavha, hech narsa bosilmaydi).

> Ruscha: «Сколько у вас весов с печатью этикеток? Покажите, пожалуйста, наклейку на корпусе — мне нужны марка и модель. У всех весов коды товаров одинаковые?»

**Qanday skrinshot**

- **Foto:** har bir tarozining korpusidagi marka/model yorlig'i — `B16-1.jpg`, `B16-2.jpg`.
- Tarozi dasturi bo'lsa: dastur oynasining sarlavhasi — `B16-3.png`.

**Nimani yashirish**

- tarozi seriya raqami — yashirish shart emas, lekin kerak ham emas;
- dastur oynasida login/parol ko'rinsa — yashiriladi;
- ⚠️ zalda suratga olayotganda **mijoz yoki xodimning yuzi** kadrga tushmasin; tushsa — o'sha qism kesiladi,
  odamni suratga olishdan oldin **so'raladi** (0.1-bo'lim).

**Nimaga tegmaslik**

- ⚠️ tarozining **hech qanday tugmasi bosilmaydi**;
- ⚠️ tarozi dasturida **«Загрузить» va «Выгрузить» — hech qachon** (tovar bazasini buzadi);
- ⚠️ 1C dagi «Подключаемое оборудование» bo'limida *(экранда tekshirilsin)* faqat **ko'rish**:
  «Выгрузить данные», «Загрузить», «Очистить», «Заполнить», «Перенумеровать» — hech qachon, galochkalarga tegilmaydi;
- ⚠️ o'sha bo'limdagi **«Тест устройства», «Функции», «Настроить…»** ham bosilmaydi — ular tarozi yoki
  printerga **haqiqiy buyruq yuboradi** (etiketka chiqib ketishi yoki qurilma uzilib qolishi mumkin).

**Javob formati**

```
etiketka bosadigan tarozilar soni: __
  1. marka/model: ______________________
  2. marka/model: ______________________
barcha tarozilarda tovar kodlari BIR XILmi: ha / yo'q / bilmayman
tovarlar taroziga qanday tushadi: 1C dan eksport / qo'lda tarozida / tarozi dasturi orqali / bilmayman
tarozi dasturi nomi (bo'lsa):     ______________________
fotolar:                          B16-1.jpg …
```

**Nega kerak (BinOS tomoni):** BinOS'da PLU noyobligi **kompaniya doirasida** (filial emas):
`ux_products_company_plu` — UNIQUE (company_id, plu_code) (`initdb.py:504-506`). ⚠️ Ikki tarozida **bir xil PLU
boshqa tovarga** tegishli bo'lsa, bitta `plu_code` maydoni yetmaydi va bu BinOS tomonida **yangi qaror** talab
qiladi. Cutover'dan keyin tarozilarni kim qayta yuklashi ham shu javobga bog'liq — hozircha BinOS tomonida
bu qadam **umuman yo'q** (tarozi drayveri stub: `services/scales/generic.py:25-27`).

---

## Band 17. PLU qayerda saqlanadi

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 8(б)(г)** (305, 307-satrlar).

⚠️ **Bu band HAMON ochiq — kontrakt ma'lum bo'lgani uni yopmaydi.** Real etiketkalardan biz PLU maydoni
**5 xonali** ekanini bildik (band 18), lekin **o'sha 5 xonali qiymat 1C da qayerda turishi** —
nomdami, alohida rekvizitdami, yoki faqat tarozi dasturidami — **hali NOMA'LUM**. Extractor `plu` ni
qayerdan olishi shu javobga bog'liq.

**Qayerdan topish**

Uchta ehtimoliy manbani **ketma-ket tekshiring** (qaysi biri ekani NOMA'LUM):

| Manba | Qayerdan | Belgi |
|---|---|---|
| Faqat tovar nomida | band 13 kartochkasi | nomda `148Код` ko'rinadi, alohida maydon yo'q |
| 1C rekvizitida | band 13 kartochkasi, oxirigacha aylantirib | «Код весов», «PLU», «Код для весов» kabi maydon *(экранда tekshirilsin)* |
| Tarozi dasturida (1C dan tashqarida) | band 16 dagi dastur | tovar ro'yxatida «Код» ustuni bor |

Qo'shimcha: `Список9.xls` (shtrix-kodlar) **qaysi oynadan** saqlangani so'raladi.

> Ruscha: «Где задаётся код товара для весов — например 148: только в названии товара, в отдельном поле 1С, или в программе самих весов? И из какого окна вы сохраняли файл штрихкодов Список9?»

**Qanday skrinshot**

- 1C'da alohida maydon bo'lsa: **1 kadr** — maydon nomi va qiymati ko'rinadigan qism, `B17-1.png`.
- Tarozi dasturida bo'lsa: tovar ro'yxati — nom va kod ustunlari, **1 kadr**, `B17-2.png`.
- `Список9` manbasi: o'sha oyna/hisobot sarlavhasi va ustun nomlari, bir necha qator — **1 kadr**, `B17-3.png`.

**Nimani yashirish**

- —

**Nimaga tegmaslik**

- ⚠️ tarozi dasturida **«Загрузить», «Выгрузить» — hech qachon**;
- ⚠️ 1C kartochkasida maydonga kursor qo'yilmaydi, «Записать» bosilmaydi;
- `Список9` oynasida qayta saqlash **bugun shart emas** — faqat ko'rsating.

**Javob formati**

```
PLU manbai:  faqat tovar nomida / 1C rekvizitida / tarozi dasturida / bilmayman
1C rekviziti bo'lsa — maydon nomi AYNAN: ______________________
  namunaviy qiymat:                      ______   (oldingi nollar bilanmi: ha / yo'q)
tarozi dasturida bo'lsa — dastur nomi:   ______________________
  ro'yxat eksporti olinadimi:            ha / yo'q / bilmayman
Список9 qaysi oynadan saqlangan:         ______________________ / eslay olmaydi
skrinshotlar:                            B17-1.png · B17-2.png · B17-3.png
```

**Nega kerak (BinOS tomoni):** ⚠️ **Nomdan PLU ajratib olish TAQIQLANGAN** (so'rovnoma 337-338-satrlar) —
dalil: nom ichidagi yozuv bir xil emas (`148Код`, `Код594`, `476Корд`), 465 ta, 2 tasi takror; bu satrlar tarozi
xotirasidagi PLU ga teng ekani **hech qayerda isbotlanmagan**. 1C'da alohida maydon bo'lmasa, extractor `plu` ni
**umuman chiqarmaydi** (null) — bu qonuniy, lekin PLU alohida bosqichda yopiladi. ⚠️ Yana bir tuzoq: **`plu`
bazaga faqat CREATE yo'lida yoziladi** (`mapping.py:504-505`) — LINK qilingan mavjud BinOS mahsulotiga 1C PLU'si
**KO'CHIRILMAYDI**, ya'ni cutover rejasiga alohida qadam qo'shiladi.

⚠️ **Yetakchi nollar — shuning uchun «oldingi nollar bilanmi» savoli.** BinOS `products.plu_code` ni
**yetakchi nolsiz** saqlaydi (`products.py:38-47` — QA PC-013), migrator ham `str(int(s))` qiladi va
`PLU_LEADING_ZEROS` belgisini qo'yadi (`normalize.py:211-214`). Barkod ichidagi PLU esa **5 xonali,
yetakchi nollar bilan** («00537»). Ikkalasi **bir xil tovar** — solishtirish ikkala tomonni 5 xonaga
to'ldirib bajariladi (`scaleBarcode.ts:94-98`, `scale_barcode.py:101`). Ya'ni 1C dagi qiymat «537» bo'lsa
ham, «00537» bo'lsa ham mos keladi; operator faqat **AYNAN qanday yozilganini** ko'chiradi, o'zi tahrirlamaydi.
⚠️ Lekin **6 xonali qiymat** (masalan `000537`) rekvizitda tursa — buni shunday yozib keling: bu
etiketkada bosilgan KOD ko'rinishi, **barkod maydoni emas**, va u BinOS'ga o'sha holida kiritilmaydi
(`normalizePlu` 6 xonani ataylab rad etadi, `scaleBarcode.ts:72-76`).

---

## Band 18. Real tarozi etiketkasi / barkod namunasi ⚠️ MAJBURIY

Ruscha yo'riqnoma: so'rovnoma 2-bo'lim, **Вопрос 8, «Фото и скриншоты», 1-band** (310–311-satrlar).

⚠️ **Bu band har doim to'liq bajariladi**, hatto baza nusxasi berilgan bo'lsa ham — etiketka nusxada ko'rinmaydi.

⚠️ **Bandning maqsadi O'ZGARDI (lekin band qolmoqda).** Fayzan'dan olingan 4 ta real etiketka bilan
kontrakt **aniqlandi** — `27` + PLU(5) + GRAMM(5) + EAN-13 nazorat(1) («Nega kerak» bo'limiga qarang).
Shuning uchun bu band endi «formatni ochish» emas, **«do'kondagi AYNAN shu tarozi(lar) shu kontraktda
bosishini TASDIQLASH»**: band 16 da bir nechta tarozi yoki boshqa marka chiqishi mumkin, va boshqa
model boshqacha prefiks (21/22/23/28) yoki boshqa maydon taqsimoti bilan bosishi mumkin.
⚠️ Shu sababli quyidagi **«javob formati» ataylab KO'R qoldirilgan**: operatorga kutilgan qiymat
**AYTILMAYDI** va u raqamlarni faqat ko'chiradi. Kutilgan javobni aytish tasdiqni yo'q qiladi.

**Qayerdan topish**

- Zalga chiqing, tarozi etiketkasi yopishtirilgan **haqiqiy tovarlarni** toping (nomida `Код` bo'lgani ma'qul).
- Etiketka tugagan bo'lsa: ⚠️ **o'zingiz bosmang va bostirmang** — ⚠️ mavjud tovarlardan toping yoki xodim
  odatdagi ishi davomida bosgan etiketkani kuting.

> Ruscha: «Дайте, пожалуйста, 2–3 товара с этикеткой от весов — я только сфотографирую этикетку. Ничего печатать не нужно.»

**Qanday foto — 2–3 kadr, har biri alohida tovar**

Har kadrda **to'rttasi ham o'qilishi shart**:

1. shtrix-kod **ostidagi raqamlar** (hammasi, to'liq);
2. etiketkadagi **VAZN** (kg yoki g);
3. etiketkadagi **SUMMA**;
4. **tovar nomi**.

- Telefonni yaqin tuting, yorug'lik yetarli bo'lsin, raqamlar xiralashmasin.
- Fayl: `B18-1.jpg`, `B18-2.jpg`, `B18-3.jpg`.
- ⚠️ Telegram orqali yuborilsa — **«Файл»**, «Фото» emas (aks holda matn o'qilmaydi).

**Nimani yashirish**

- **Hech narsa.** Etiketkada shaxsiy ma'lumot bo'lmaydi;
- kadrga kassa ekrani yoki mijoz tushib qolsa — o'sha qism kesiladi.

**Nimaga tegmaslik**

- ⚠️ **tarozida hech narsa bosilmaydi** — etiketka bostirilmaydi;
- ⚠️ tovarni tarozida qayta tortmang;
- etiketka tovardan **ko'chirilmaydi** (kerak bo'lsa tovarni qo'lda ushlab suratga oling).

**Javob formati**

Har namunaga alohida:

```
NAMUNA 1
  barkod raqamlari (AYNAN ko'chiring, probelsiz): _____________
  raqamlar soni:                                  __   (sanab yozing — kutilgan qiymat AYTILMAYDI)
  birinchi IKKI raqam:                            __   (ko'chiring — kutilgan qiymat AYTILMAYDI)
  etiketkadagi vazn:                              ____ kg / ____ g
  etiketkadagi summa:                             __________
  tovar nomi:                                     ______________________
  1 kg narxi (etiketkada bo'lsa):                 __________   ⚠️ bo'lsa ALBATTA ko'chiring —
                                                  narx × vazn = summa tekshiruvi shunga bog'liq
  foto:                                           B18-1.jpg

NAMUNA 2 … (xuddi shunday)
NAMUNA 3 … (xuddi shunday)

⚠️ **Quyidagini operator do'konda TO'LDIRMAYDI.** Bu yakuniy tahlilni **dasturchi** fotolardan qiladi
(natija shablonining B18 bandidagi «Dasturchi to'ldiradi» jadvali). Operator do'konda faqat shuni tekshiradi:
**fotolar o'qiladimi** — barkod raqamlari, vazn, summa va nom xiralashmaganmi. Xira bo'lsa — do'konda turib
qayta oling.

Dasturchi keyin hisoblaydi (natija shablonida) — **kutilgan kontrakt bo'yicha**
`27` + PLU(5) + GRAMM(5) + nazorat(1):
  1–2-raqamlar (prefiks):        __      → "27" mi: ha / yo'q  (yo'q bo'lsa → STOP, boshqa tarozi layouti)
  3–7-raqamlar (PLU maydoni):    _____   → nomdagi / rekvizitdagi kod bilan mos: ha / yo'q
  8–12-raqamlar (gramm maydoni): _____   → etiketkadagi vaznga teng: ha / yo'q
  agar TENG EMAS — bu maydon NARXmi: ha / yo'q / aniqlanmadi   (→ STOP, band qayta ochiladi)
  13-raqam (EAN-13 nazorat):     __      → hisoblangan bilan mos: ha / yo'q
  nazorat: 1 kg narxi × (gramm ÷ 1000) = etiketkadagi SUMMA mi: ha / yo'q
```

**Kanonik mapping — uch shakl, BITTA tovar** (chalkashmasin; natija shablonida ham shu zanjir yoziladi):

| Shakl | Namuna | Kim ishlatadi |
|---|---|---|
| Etiketkada bosilgan **KOD** | `000537` (**6 xona**) | tarozi shunday chop etadi (odam o'qishi uchun) |
| Barkod ichidagi **PLU maydoni** | `00537` (**5 xona**, yetakchi nollar bilan) | **kanonik shakl** — parser shuni SATR qilib qaytaradi (`scaleBarcode.ts:87`, `scale_barcode.py:98`) |
| BinOS `products.plu_code` | `537` (yetakchi **nolsiz**) | DB da shunday saqlanadi (QA PC-013, `products.py:38-47`) |

Solishtirish **ikkala tomonni 5 xonaga to'ldirib** bajariladi (`scaleBarcode.ts:94-98`, `scale_barcode.py:101`) —
DB dagi `537` etiketkadagi `00537` ga **mos keladi**.
⚠️ **6 xonali KOD ni PLU sifatida kiritish RAD etiladi** — u etiketkada bosilgan ko'rinish, barkod maydoni emas
(`normalizePlu`, `scaleBarcode.ts:72-76`).

**Nega kerak (BinOS tomoni):** ⚠️ **Cutover'ning eng qattiq STOP-darvozasi** — lekin darvoza endi
«format qanday?» emas, «**shu tarozi ham shu formatda bosadimi?**».

**Haqiqiy kontrakt (Fayzan'dan olingan 4 ta REAL etiketka bilan tasdiqlangan):**

```
27 + PLU(5) + GRAMM(5) + EAN-13 nazorat(1)   = 13 raqam

2700345032787 = 27 | 00345 | 03278 | 7   → 3.278 kg
2700565020205 = 27 | 00565 | 02020 | 5   → 2.020 kg
2700537004264 = 27 | 00537 | 00426 | 4   → 0.426 kg · 350 so'm/kg · summa 149.10
2700349000560 = 27 | 00349 | 00056 | 0   → 0.056 kg · 580 so'm/kg · summa 32.48
```

To'rtalasining **EAN-13 nazorat raqami to'g'ri** (4/4). BinOS POS va server etiketkani AYNAN shunday
o'qiydi: faqat raqamlar olinadi, uzunlik **aynan 13**, prefiks **aynan «27»** (`scaleBarcode.ts:81-82`,
`scale_barcode.py:90`; prefiks konstantasi — `scaleBarcode.ts:34`, `scale_barcode.py:40`),
**nazorat raqami TEKSHIRILADI** (`scaleBarcode.ts:84`, `scale_barcode.py:93`),
PLU = 3–7-raqamlar — **5 xonali SATR**, yetakchi nollar saqlanadi (`scaleBarcode.ts:87`,
`scale_barcode.py:98`), gramm = 8–12-raqamlar va **> 0** bo'lishi shart. POS va server bitta vektor fayli
bilan tekshiriladi: `tests/fixtures/scale_barcodes.json` (10 musbat — shu 4 ta real etiketka + chegara
holatlari, 11 manfiy). `GET /products/scan` javobida kanonik shakl `scale.plu_code` = «00537»
(`products.py:540`, `schemas/catalog.py:53-54`); eski `scale.plu` SON bo'lib qoladi (mobil mijozlar uchun).

⚠️ **Ikki qizil chiziq — ikkalasi ham YOPILDI:**

1. ✅ **Vazn yoki narx — YOPILDI: bu GRAMM.** Dalil etiketkaning o'zida bosilgan summa:
   350 × **0.426** = **149.10** va 580 × **0.056** = **32.48**. Agar 8–12-raqamlar narx bo'lganida bu
   ko'paytmalar to'g'ri kelmasdi. ⚠️ Kodda bu holatni aniqlaydigan tekshiruv baribir **YO'Q** — boshqa
   marka tarozi narx bossa, POS narxni **miqdor** deb o'qiydi. Shuning uchun fotoda **vazn, 1 kg narxi va
   summa birga ko'rinishi** hamon shart: bu uchtasi shu tarozi uchun ko'paytmani qayta tekshirish imkonini beradi.
2. ✅ **PLU xonasi ziddiyati — YOPILDI: ziddiyat yo'q edi.** Barkod ichidagi PLU maydoni **5 xonali**
   (6 emas) — eski `2 + PLU(6) + gramm(5)` taxmini noto'g'ri bo'lgan: u prefiksning ikkinchi raqami «7» ni
   PLU maydoniga qo'shib yuborar va `2700537004264` ni PLU **700537** deb o'qir edi. Demak BinOS API'ning
   **1–5 xonali** cheklovi (`products.py:35`, xato matni `products.py:46`) va migrator qoidasi
   (`normalize.py:211-216`) real kontraktga **aynan mos** — backend 6 xonaga **kengaytirilmadi** va
   kengaytirilmaydi. Etiketkada bosilgan 6 xonali **KOD** (`000537`) bu maydon emas (yuqoridagi mapping jadvali).

Fayzan'da hozir **454 ta tarozi tovari BinOS'da UMUMAN YO'Q** — Phase 1/2 da ular **ataylab yaratilmagan**
(`scripts/fayzan_verify_phase2.out:42-43` — «454 tarozi … ular hech qachon yaratilmagan»); mavjud 7137 tovarning
**hammasi `dona`** birligida va `is_weighted`/`plu_code` **0 ta** (o'sha fayl, 23-27-satrlar). Demak bu 454 tovar
cutover'da **CREATE yo'lidan** o'tadi — ya'ni `plu` ular uchun haqiqatan yoziladi (band 17 dagi LINK cheklovi
bularga tegishli emas). Bu band javobsiz o'sha 454 tovar **sotilmaydi**.
⚠️ Kontrakt ma'lum bo'lgani bu 454 tovarni sotiladigan qilmaydi: hamon **band 17** kerak — `plu`
**qiymatlari** 1C da qayerdan olinishi, va **band 16** — bir nechta tarozida PLU takrorlanmasligi.

---

# 3. Do'kondan chiqishdan oldin — 14 bandli nazorat ro'yxati

Har bandni **belgilang**. Belgilanmagan band qolsa — hali chiqmang.

⚠️ Bu ro'yxatdagi har bir satr natija shablonining **STOP** blokeri bilan bog'langan (`docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md`, «Blokerlar» jadvali). Ro'yxat to'liq belgilanmasa — ekstraktor yozish BOSHLANMAYDI, ya'ni ikkinchi tashrif kerak bo'ladi.

| # | Tekshiruv | ✓ |
|---|---|---|
| 1 | **Konfiguratsiya nomi + versiyasi + platforma versiyasi** yozib olindi va `B01-1.png` bor (band 1) | ☐ |
| 2 | **`File=` / `Srvr=` / `ws=`** satri yozildi va kassa QAYSI bazada ishlashi aniqlandi (band 3) | ☐ |
| 3 | **Nusxa (`.dt`) bo'yicha aniq javob** olindi; «ha» bo'lsa — kim, qachon, qaysi tashuvchida, **yozma rozilik** bor (band 4) | ☐ |
| 4 | **Haqiqiy zal ombori** nomi aytildi va omborlar ro'yxati suratga olindi (band 8) | ☐ |
| 5 | **Qoldiq hisoboti** nomi + varianti + **«Итого» qiymati** yozildi, **3 kadr** (`B09-1/2/3`) bor — ayniqsa **sozlamalar oynasi** (band 9) | ☐ |
| 6 | **«Виды цен» to'liq ro'yxati** suratga olindi va **kassa qaysi narx turi bilan sotishi** aytildi (band 10, 11) | ☐ |
| 7 | **«Весовой» belgisi qayerda** ekani aniqlandi (yoki «yo'q, faqat кг» deb yozildi) va birlik nomi AYNAN ko'chirildi (band 13) | ☐ |
| 8 | **Характеристики** va **Серии** bo'yicha «ha / yo'q / bilmayman» javobi yozildi (band 14, 15) | ☐ |
| 9 | **PLU manbai** aniqlandi (nom / 1C rekviziti / tarozi dasturi) va `Список9` manbasi so'raldi (band 17) | ☐ |
| 10 | **2–3 ta real etiketka fotosi** olindi; har birida **barkod raqamlari + vazn + summa + nom** (va bo'lsa **1 kg narxi**) o'qiladi — do'kondagi tarozi `27+PLU(5)+GRAMM(5)+nazorat` kontraktida bosishini TASDIQLASH uchun (band 18) | ☐ |
| 11 | **1C standartmi yoki o'zgartirilganmi** so'raldi (`ha`/`yo'q`/`bilmayman` + kim xizmat ko'rsatadi) — STOP blokeri B02 (band 2) | ☐ |
| 12 | **«Kод» va «Артикул»** kartochkada qayerda turishi ko'rildi va birlik nomi AYNAN ko'chirildi — STOP blokeri B12 (band 12) | ☐ |
| 13 | **`.epf` (tashqi ishlov) ochish mumkinmi** — og'zaki javob olindi (hech narsa ochilmagan holda) — STOP blokeri B19 (band 4 ichidagi savol) | ☐ |
| 14 | Nusxa **berilmaydigan** bo'lsa: **`.cf` / `.cfe`** bo'yicha aniq javob olindi — shartli STOP blokeri B05 (band 5). Nusxa beriladigan bo'lsa: `kerak emas` deb belgilanadi | ☐ |

**Chiqishdan oldin oxirgi 4 ta ish:**

1. Fotolarni **darhol** ko'zdan kechiring: barkod raqamlari o'qilyaptimi? Xira bo'lsa — qayta oling, do'konda turib.
2. ⚠️ **Do'kon kompyuterini o'z holiga qaytaring:** hisobotdagi **eski sana/davr** qaytarildi (band 9);
   saqlangan skrinshot/Excel fayllar fleshkaga ko'chirildi va **xodim ko'z o'ngida o'chirildi** (Korzina ham);
   1C'da ochiq qolgan kartochka yoki hisobot oynasi **yopildi**; biror narsa tasodifan bosilgan bo'lsa —
   administratorga **aytildi** va shablonga **yozildi**.
3. `docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md` ni to'ldiring. **Bilinmagan har band «bilmayman» deb yoziladi** —
   bo'sh qoldirilmaydi va **taxmin qilinmaydi**.
   ⚠️ Shablonda **birorta parol, PIN, AnyDesk ID yoki shaxsiy telefon raqami bo'lmasligi** yana bir bor tekshiriladi.
4. Xodimga rahmat ayting va tasdiqlang:

> Ruscha: «Спасибо. Мы в вашей 1С ничего не меняли, не создавали и не удаляли — только смотрели и фотографировали.»

---

## Qo'shimcha: do'konda SO'RALMAYDI (allaqachon hal qilingan)

Vaqtni tejash uchun — bular so'rovnomaning 1-bo'limida (40–48-satrlar) yopilgan:

| Mavzu | Nega so'ralmaydi |
|---|---|
| Qadoq (Упаковка) koeffitsiyenti | do'konda so'rab foyda yo'q: dalil statistik (Список9 da 59 211 qatordan 1 tasida, sena da 0 ta, astatka da «Упак.» = «Количество»). ⚠️ Lekin bu **qoida emas** — filtr qoidasi faqat baza nusxasidagi registr tuzilmasidan yoziladi (matritsa `D24`, `T8`) |
| Barkodlar noyobmi | 58 888 bo'sh bo'lmagan barkodning **hammasi** noyob |
| QQS (НДС), valyuta, boshqa narx turlari | eksport **barcha** narx turlarini chiqaradi; chakana va kelish turini operator `selection` da tanlaydi |
| Til / valyuta / fuqarolik vaqt zonasi | ma'lum: ruscha 1C, сом, +996, Asia/Bishkek. ⚠️ **1C mashinasining o'z soati** bundan alohida — u band 3 da o'qiladi (matritsa `D12`) |

---

## Manbalar

| Hujjat | Nima uchun |
|---|---|
| `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md` | egaga oldindan yuboriladigan ruscha so'rovnoma (8 savol) |
| `integrations/1c/BINOS_1C_BUNDLE_V1.md` | `binos-1c-v1` fayl shartnomasi |
| `integrations/1c/MIGRATOR_V1_RUNBOOK.md` | migratorning 11 qadami va himoyalari |
| `docs/FAYZAN_1C_DISCOVERY_RESULT_TEMPLATE.md` | bo'sh natija shabloni (do'kondan kelgach to'ldiriladi) |
| `docs/FAYZAN_CUTOVER_RUNBOOK_DRAFT.md` | cutover ketma-ketligi qoralamasi |
