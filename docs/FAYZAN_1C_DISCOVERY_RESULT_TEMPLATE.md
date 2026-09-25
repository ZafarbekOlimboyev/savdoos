# Fayzan 1C discovery — NATIJA SHABLONI (bo'sh)

Bu fayl **bo'sh shablon**. Operator do'kondan qaytgach **faqat to'ldiradi** — hech narsa o'ylab topmaydi.

- **Savollarning MATNI bu yerda EMAS.** Savollar, menyu yo'llari, skrinshot qoidalari va 1C'ga tegmaslik
  qoidalari bitta joyda turadi: `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md`.
  Har band sarlavhasida shu hujjatdagi savol raqami ko'rsatilgan.
- **Bajarish yo'riqnomasi** (qayerdan topish / qanday skrinshot / nimani yashirish / nimaga tegmaslik):
  `docs/FAYZAN_1C_DISCOVERY.md`. Bandlar tartibi shu hujjat bilan bir xil (B01…B18).
  ⚠️ **B19 va B20 da alohida band YO'Q:** B19 — yo'riqnomaning **Band 4** ichidagi og'zaki savol (`:327-329, :361`),
  B20 esa checklist tomonidan cutover rejasi uchrashuviga qoldirilgan (`:361`).
- **Discovery = FAQAT O'QISH.** 1C'ga hech narsa yozilmaydi, hech narsa yuklanmaydi, hech narsa o'chirilmaydi.

## To'ldirish qoidalari

| # | Qoida |
|---|---|
| 1 | `____` — to'ldiriladigan joy. Hech bir `____` bo'sh qolmasin. |
| 2 | Javob bilinmasa — **`bilmayman`** yoziladi. Bu HAR maydonda ruxsat etilgan qiymat. |
| 3 | **Taxmin yozish TAQIQLANGAN.** «ehtimol», «odatda shunday», «menimcha» — javob emas. |
| 4 | `bilmayman` yozilsa, yoniga **kim bilishi mumkin** (kassir / buxgalter / xizmat firmasi) yoziladi. |
| 5 | Skrinshot fayl nomi maydon kartasidagi qoida bo'yicha **band raqami bilan** qo'yiladi: `B01-1.png`, `B09-2.png`, `B18-1.jpg` (`docs/FAYZAN_1C_DISCOVERY.md`, 0-bo'lim). Do'konda boshqacha nomlangan bo'lsa — fayl **qayta nomlanadi**, shablonga esa AYNAN yakuniy nom yoziladi. |
| 6 | Skrinshot kerak bo'lmagan maydonda `[skrinshot: yo'q]` yoziladi. |
| 7 | 1C interfeysidagi nom **ruscha, AYNAN ekrandagidek** ko'chiriladi: «Розничная цена», emas «roznichnaya». |
| 8 | Menyu yo'li tasdiqlanmagan bo'lsa — yoniga `(экранда tekshirilsin)` qoladi, o'chirilmaydi. |
| 9 | Konfiguratsiya turini (Розница 2 / УТ 11 / УНФ / Розница 3) **taxmin qilish taqiqlanadi** — faqat B01 javobi hal qiladi. |
| 9a | Jadval va oxiridagi YAML bir xil javobni ikki joyda saqlaydi. **Asosiysi — JADVAL**; YAML undan ko'chiriladi. Ziddiyat chiqsa jadval javobi to'g'ri deb olinadi va YAML tuzatiladi. |
| 10 | 🔒 **Sir bu faylga YOZILMAYDI.** Parol, login+parol juftligi, litsenziya raqami / PIN, AnyDesk yoki RDP **ID va paroli**, bank rekvizitlari, karta raqami — hech bir maydonga yozilmaydi. Kerak bo'lsa **faqat og'zaki telefonda** (so'rovnoma `:94`, yo'riqnoma `:80, :356`). |
| 11 | 🔒 **Odamlarning telefoni va e-mail'i yozilmaydi.** Ism va lavozim — mumkin (ular kerak); aloqa raqami — og'zaki. Agar maydon baribir raqam so'rasa, `og'zaki aytildi` deb yoziladi. |
| 12 | 🔒 **To'ldirilgan fayl — maxfiy hujjat.** Ichida do'konning ulanish satri, xodim ismlari va ombor/narx ma'lumoti bo'ladi. U **repoga commit qilinmaydi** va internetsiz ish kompyuteridan chiqmaydi (quyida «Fayllar qayerga qo'yiladi»). |

## ⚠️ Discovery paytida bosilmaydigan tugmalar (eslatma)

To'liq ro'yxat: `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md:69-77` (8 qoida bloki: `:61-95`).

| ⚠️ Ekran | Tegilmaydigan tugma |
|---|---|
| Oddiy 1C (tarozi/kassa bo'limlari) | «Выгрузить данные», «Загрузить», «Очистить», «Заполнить», «Перенумеровать». **Hech qanday `.epf` fayli ochilmaydi** |
| «Конфигуратор» | «Загрузить информационную базу…», «Загрузить конфигурацию из файла…», «Вернуться к конфигурации БД», «Обновить конфигурацию базы данных», «Обновить конфигурацию…», «Снять с поддержки», «Включить возможность изменения», «Тестирование и исправление…» |
| «Конфигуратор» — savollar | «Выгрузить информационную базу…» ning **o'zini** tasdiqlashdan boshqa har qanday savolga → «Нет» yoki «Отмена» |
| «Активные пользователи» | Boshqa foydalanuvchining sessiyasini uzadigan **hech qanday** tugma bosilmaydi (platformaga qarab «Завершить сеанс» / «Удалить» — `(экранда tekshirilsin)`, so'rovnomada bu tugmalar nomi YO'Q). Boshqalar 1C'dan **o'zlari** chiqadi (so'rovnoma `:167`) |
| «Расширения конфигурации» | «Загрузить из файла…», «Удалить» |
| Tarozi dasturi | «Загрузить», «Выгрузить» |
| Sozlamalar / «Администрирование» | Galochka va pereklyuchatellar (darhol saqlanadi) |
| Har qanday oyna yopilishi | «Сохранить изменения?» → har doim **«Нет»** |

> ⚠️ **Tasodifan bosilib ketsa** — darhol 1C administratoriga aytiladi, xodim **o'zi tuzatmaydi** va shu fayldagi
> tegishli bandga «tasodifan bosildi: ____ , administratorga aytildi» deb yoziladi (so'rovnoma `:66-68`).

## Do'kon xodimiga aytiladigan umumiy jumlalar

> Ruscha: «Мы ничего в вашей 1С не меняем — только смотрим и делаем скриншоты.»

> Ruscha: «Если не знаете — так и скажите, "не знаю". Угадывать не нужно.»

> Ruscha: «Кто может это точно знать — кассир, бухгалтер или обслуживающая фирма?»

---

## 0. Metadata

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Sana (discovery kuni) | `____` | `YYYY-MM-DD` | `[skrinshot: yo'q]` |
| Boshlangan / tugagan vaqt | `____` / `____` | `HH:MM` (mahalliy, Asia/Bishkek) | `[skrinshot: yo'q]` |
| Kim yig'di (operator) | `____` | ism | `[skrinshot: yo'q]` |
| Do'kon | `____` | do'kon nomi | `[skrinshot: yo'q]` |
| BinOS company code | `fayzan1` | tayyor qiymat, o'zgartirilmaydi | `[skrinshot: yo'q]` |
| Do'konda hozir bo'lgan xodim(lar) | `____` | ism + lavozim / `bilmayman` | `[skrinshot: yo'q]` |
| 1C administratori / xizmat firmasi | `____` | nom / `bilmayman` | `[skrinshot: yo'q]` |
| Platforma versiyasi (B01 dan ko'chiriladi) | `____` | aniq matn / `bilmayman` | `[skrinshot: ____]` |
| Konfiguratsiya nomi + versiyasi (B01 dan) | `____` | aniq matn / `bilmayman` | `[skrinshot: ____]` |
| **Baza nusxasi olindimi** | `____` | `ha (.dt)` / `ha (papka 1Cv8.1CD)` / `yo'q` / `keyinroq` / `bilmayman` | `[skrinshot: ____]` |
| Nusxa uchun egasining yozma roziligi | `____` | `bor` / `yo'q` / `kerak emas (nusxa olinmadi)` | `[skrinshot: ____]` |
| Skrinshotlar qabul qiluvchisi | `____` | **faqat ism** (telefon raqami bu faylga yozilmaydi — qoida 11) | `[skrinshot: yo'q]` |
| Jami skrinshot soni | `____` | son / `0` | `[skrinshot: yo'q]` |

> 🔒 **Rozilik darvozasi.** «Baza nusxasi olindi = `ha`» va «yozma rozilik = `yo'q`» birga bo'lishi **MUMKIN EMAS**.
> Bunday holatda nusxa **ochilmaydi, ko'chirilmaydi va olib ketilmaydi** — egasining yozma roziligi kelguncha
> fleshka do'konda qoladi yoki egasiga qaytariladi. Bu **STOP** (blokerlar jadvali, «B04-rozilik» qatori).

---

## B01 — «О программе»: platforma va konfiguratsiya

Savol: checklist **Вопрос 1** (`:98-107`) · Bundle: `infobase.platform_version`, `infobase.configuration_name`, `infobase.configuration_version` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Platforma versiyasi | `____` | «О программе» oynasidan AYNAN ko'chirilgan matn / `bilmayman` | `[skrinshot: ____]` |
| Konfiguratsiya NOMI | `____` | AYNAN ruscha nom / `bilmayman` | `[skrinshot: ____]` |
| Konfiguratsiya VERSIYASI | `____` | AYNAN raqam / `bilmayman` | `[skrinshot: ____]` |
| «О программе» oynasidagi baza satri | `____` | AYNAN satr / `bilmayman` | `[skrinshot: ____]` |
| «О программе» qaysi yo'l bilan ochildi | `____` | `☰ Сервис и настройки → О программе` / `Главное меню → Справка → О программе` / `bilmayman` | `[skrinshot: ____]` |

> Ruscha: «Покажите, пожалуйста, окно "О программе" целиком — версию платформы и название конфигурации.»

⚠️ Litsenziya raqami va internet-qo'llab-quvvatlash logini skrinshotda yopiladi.

**Bo'sh qolsa:** ekstraktor umuman yozilmaydi — registr/spravochnik nomlari konfiguratsiyaga bog'liq, va bundle bu uch maydonsiz rad etiladi.

---

## B02 — Konfiguratsiya standartmi yoki o'zgartirilganmi

Savol: checklist **Вопрос 1(а)** (`:110`) · Bundle: bevosita emas — `is_weighted` va `plu` manbasini belgilaydi · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Dasturchi/firma o'zgartirish kiritganmi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Qanday o'zgarish (aytilgan bo'lsa) | `____` | `qo'shimcha maydonlar` / `o'z hisobotlari` / `kassa bilan almashinuv` / `tarozi bilan almashinuv` / `boshqa: ____` / `bilmayman` | `[skrinshot: yo'q]` |
| Kengaytma (расширение) bormi | `____` | `bor` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| «Дополнительные реквизиты и сведения» ro'yxati olindimi | `____` | `ha` / `yo'q` / `yo'l topilmadi (экранда tekshirilsin)` / `bilmayman` | `[skrinshot: ____]` |
| «Дополнительные отчеты и обработки» ro'yxati olindimi | `____` | `ha` / `yo'q` / `yo'l topilmadi (экранда tekshirilsin)` / `bilmayman` | `[skrinshot: ____]` |
| Yaqin oylarda 1C yangilash/ko'chirish rejasi | `____` | `ha (qachon: ____)` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Программист или фирма что-нибудь дописывали в вашу 1С — свои поля, отчёты, обмен с кассой или весами?»

⚠️ «Дополнительные реквизиты и сведения» sahifasida faqat prokrutka — galochkaga tegilmaydi.

**Bo'sh qolsa:** qo'shimcha rekvizitlar (masalan «весовой», PLU) `.cf` ga kirmaydi — ularni qayerdan o'qish noma'lum qoladi.

---

## B03 — Infobase ulanishi: `File=` / `Srvr=` / `ws=`

Savol: checklist **Вопрос 2** (`:121-139`) · Bundle: bevosita emas — ekstraktor qayerda ishga tushishini belgilaydi · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Ishchi bazaning satri nima bilan boshlanadi | `____` | `File=` / `Srvr=` / `ws=` / `boshqa: ____` / `bilmayman` | `[skrinshot: ____]` |
| Satrning AYNAN nusxasi | `____` | to'liq satr / `bilmayman` | `[skrinshot: ____]` |
| Nechta 1C bazasi bor | `____` | son / `bilmayman` | `[skrinshot: ____]` |
| Har bazaning vazifasi | `____` | ro'yxat (`do'kon` / `buxgalteriya` / `markaziy` / `eski` / `boshqa: ____`) / `bilmayman` | `[skrinshot: ____]` |
| **Kassa qaysi bazada ishlaydi** | `____` | baza nomi / `bilmayman` | `[skrinshot: ____]` |
| Bazalar orasida avtomatik almashinuv | `____` | `bor` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| 2026-08 da yuborilgan 3 ta fayl shu bazadanmi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Bazaga qanday kiriladi | `____` | `shu kompyuterda` / `do'kondagi serverda` / `RDP` / `AnyDesk` / `brauzer` / `bilmayman` | `[skrinshot: yo'q]` |
| ⚠️ 1C turgan kompyuter/server soati (ekranning burchagidan) | `____` | `HH:MM` / `bilmayman` | `[skrinshot: ____]` |
| Shu soat operatorning telefonidagi vaqtga to'g'ri keladimi | `____` | `ha` / `yo'q (farq: ____ daqiqa)` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Щёлкните по рабочей базе один раз, не открывая её — внизу окна появится строка. Перепишите её, пожалуйста.»

⚠️ Baza tanlash oynasida «Изменить», «Добавить», «Удалить» bosilmaydi.
⚠️ 🔒 Ulanish satri **yashirilmaydi** (u kerak), lekin foydalanuvchi nomi / parol maydoni ko'rinsa — skrinshotda
yopiladi. «Bazaga qanday kiriladi» qatoriga faqat **usul** yoziladi (`RDP` / `AnyDesk` / …): masofaviy kirishning
**ID va paroli hech qayerda yozilmaydi** — na bu faylga, na chatga (qoida 10, yo'riqnoma `:356`).

⚠️ **Server soati nima uchun.** `snapshot_at` bundle'da ISO 8601 va **offset bilan** bo'lishi shart
(`bundle.py:137-143`) — offsetsiz vaqt rad etiladi. Do'konning fuqarolik zonasi ma'lum (Asia/Bishkek), lekin
1C turgan mashinaning **haqiqiy soati va zonasi** shu bilan bir xilligi tekshirilmagan. Noto'g'ri offset bilan
`AlreadyApplied` / `StaleSnapshotError` taqqoslashlari noto'g'ri ishlaydi (`apply.py:119-127`).
⚠️ Soat **o'zgartirilmaydi** va sana/vaqt sozlamalari oynasi ochilmaydi — faqat ekran burchagidagi qiymat
o'qiladi. Daraja: **REJA** (dependency matrix `D12`).

**Bo'sh qolsa:** ekstraktorni qayerda va qanday yurgizish hal qilinmaydi; noto'g'ri bazadan olingan eksport barcha tekshiruvlardan O'TADI, lekin jimgina eskirgan bo'ladi.

---

## B04 — `.dt` nusxa olish mumkinligi

Savol: checklist **Вопрос 3** (`:143-177`) · Bundle: bevosita emas — GUID, registr tuzilmasi va sinov imkoniyatini beradi · **BLOKER: HA (yo'lni tanlaydi)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Nusxa berish imkoni | `____` | `ha` / `yo'q` / `egasining roziligi kerak` / `bilmayman, kim qila oladi` | `[skrinshot: yo'q]` |
| Nusxani kim qiladi | `____` | **faqat** `1C administratori: ____` / `xizmat firmasi: ____` / `bilmayman` — Konfigurator'ga to'liq kirishi bor odam (so'rovnoma `:152`) | `[skrinshot: yo'q]` |
| Nusxa olishdan oldin: do'kon yopiq, smenalar yopilgan | `____` | `ha` / `yo'q` / `nusxa olinmadi` | `[skrinshot: yo'q]` |
| Nusxa turi | `____` | `.dt` / `papka (1Cv8.1CD)` / `olinmadi` | `[skrinshot: ____]` |
| Nusxa olingan sana/vaqt | `____` | `YYYY-MM-DD HH:MM` / `olinmadi` | `[skrinshot: yo'q]` |
| Nusxa hajmi | `____` | GB / `bilmayman` | `[skrinshot: ____]` |
| Topshirish usuli | `____` | `qo'ldan-qo'lga fleshka/disk` / `topshirilmadi` | `[skrinshot: yo'q]` |
| Egasining yozma roziligi | `____` | `bor` / `yo'q` | `[skrinshot: ____]` |
| Nazorat hisoboti 1 — «Остатки на складах» | `____` | fayl nomi + vaqt / `olinmadi` | `[skrinshot: yo'q]` |
| Nazorat hisoboti 2 — «Цены по видам цен» | `____` | fayl nomi + vaqt / `olinmadi` | `[skrinshot: yo'q]` |
| Nazorat hisoboti 3 — shtrix-kodlar ro'yxati | `____` | fayl nomi + vaqt / `olinmadi` | `[skrinshot: yo'q]` |
| «Активные пользователи» da faqat bitta foydalanuvchi bormi | `____` | `ha` / `yo'q` / `tekshirilmadi` | `[skrinshot: ____]` |

> Ruscha: «Копия нужна только для переноса каталога в BinOS. Она хранится на компьютере без интернета и удаляется по вашему письменному подтверждению.»

⚠️ «Загрузить информационную базу…» HECH QACHON bosilmaydi — u ishchi bazani o'chiradi.
⚠️ Nusxa Telegram / e-mail / bulut orqali yuborilmaydi (checklist `:197-208`).
⚠️ **Nusxani kassirdan so'ralmaydi.** Konfigurator'ga faqat 1C administratori yoki xizmat firmasi kiradi. Do'konda
bunday odam bo'lmasa — nusxa **kechiktiriladi** («keyinroq» deb yoziladi), xodim ko'ndirilmaydi.
⚠️ Nusxa **do'kon yopilgandan keyin** olinadi (so'rovnoma `:159`): ish vaqtida Konfigurator'ga kirish kassirlarni
bazadan uzib qo'yadi va savdoni to'xtatadi.
⚠️ «Активные пользователи» ro'yxatida boshqa odam ko'rinsa — ular 1C'dan **o'zlari chiqadi** (so'rovnoma `:167`).
«Завершить сеанс» / «Удалить» **bosilmaydi**. Ro'yxat bo'shamasa — nusxa o'sha kuni olinmaydi.

**Bo'sh qolsa:** ekstraktor ma'lumot bilan sinalmaydi; GUID (`products[].guid`) manbasi topilmaydi — 2026-08 fayllarida Ссылка/GUID ustuni YO'Q edi.

---

## B05 — `.cf` / `.cfe` mavjudligi (nusxa BO'LMASA)

Savol: checklist **Вопрос 3, «Если НЕТ»** (`:179-195`) · Bundle: bevosita emas — metadata nomlarini beradi · **BLOKER: shartli (B04 = `yo'q` bo'lsa STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| `.cf` fayli olindimi | `____` | `ha` / `yo'q` / `kerak emas (nusxa bor)` / `bilmayman` | `[skrinshot: ____]` |
| `.cf` saqlash yo'li ekranda tasdiqlandimi | `____` | `ha` / `yo'q (экранда tekshirilsin)` / `bilmayman` | `[skrinshot: ____]` |
| Kengaytma `.cfe` olindimi | `____` | `ha (nechta: ____)` / `kengaytma yo'q` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| `.cfe` saqlash yo'li ekranda tasdiqlandimi | `____` | `ha` / `yo'q (экранда tekshirilsin)` / `bilmayman` | `[skrinshot: ____]` |
| `.cf`/`.cfe` ichida kassa yoki tarozi paroli bormi (dasturchidan so'ralgan) | `____` | `yo'q` / `ha` / `so'ralmadi` / `bilmayman` | `[skrinshot: yo'q]` |
| Masofadan bir marta nazorat ostida ko'rish ruxsati | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Файл конфигурации — это структура программы, данных магазина в нём практически нет.»

⚠️ «Конфигуратор» da «Обновить конфигурацию базы данных», «Снять с поддержки», «Тестирование и исправление…» bosilmaydi.
⚠️ 🔒 **Parol javobi `ha` bo'lsa:** `.cf`/`.cfe` o'sha holicha olinmaydi. Avval dasturchi/xizmat firmasi parolni
fayldan olib tashlaydi yoki egasi yozma ravishda «shunday olinsin» deb tasdiqlaydi. Parolning **o'zi** bu faylga
ham, chatga ham yozilmaydi (qoida 10). Fayl olingan bo'lsa — nusxa qoidalari (`:197-208`) unga ham to'liq qo'llanadi.

**Bo'sh qolsa (B04 ham `yo'q` bo'lsa):** ekstraktor so'rovlarini kompilyatsiya qilib sinash imkoni umuman qolmaydi.

---

## B06 — Kassir savdosi qayerda bajariladi

Savol: checklist **Вопрос 4(а)** (`:217`) · Bundle: bevosita emas — freeze oynasini belgilaydi · **BLOKER: REJA**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Kassirlar qaysi dasturda sotadi | `____` | `1C ichida (РМК)` / `alohida dastur` / `bilmayman` | `[skrinshot: yo'q]` |
| Alohida dastur bo'lsa — nomi | `____` | `Frontol` / `Штрих-М` / `1С:Касса` / `boshqa: ____` / `kerak emas` / `bilmayman` | `[skrinshot: yo'q]` |
| Nechta kassa ishlaydi | `____` | son / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «В какой программе кассир пробивает товар — прямо в 1С или в отдельной кассовой программе?»

**Bo'sh qolsa:** cutover kunidagi «short freeze» qadamini kim va qayerda to'xtatishi noma'lum qoladi.

---

## B07 — Savdolar 1C'ga qachon tushadi

Savol: checklist **Вопрос 4(б)(в)** (`:218-220`) · Bundle: `snapshot_at` ishonchliligi · **BLOKER: REJA (STOP bo'lishi mumkin)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Savdo 1C qoldig'ini qachon kamaytiradi | `____` | `darhol` / `smena yopilganda` / `kechqurun` / `qo'lda yuklashda` / `bilmayman` | `[skrinshot: yo'q]` |
| Kechikish bo'ladimi (ertasi kun yoki keyin) | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Kechikish qancha (aytilgan bo'lsa) | `____` | vaqt / `kechikish yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Kim tasdiqladi | `____` | `katta kassir` / `administrator` / `egasi` / `bilmayman` | `[skrinshot: yo'q]` |
| Manfiy qoldiq sababi tushuntirildimi (552 qator) | `____` | `ochiq narx tugmalari` / `kassa kechikishi` / `noto'g'ri ombor` / `boshqa: ____` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Когда продажа уменьшает остаток в 1С — сразу, при закрытии смены или вечером?»

**Bo'sh qolsa:** «final fresh snapshot + short freeze» oynasining uzunligi hisoblanmaydi; noto'g'ri vaqtli snapshot `StaleSnapshotError` bilan ikkinchi urinishni ham bloklaydi.

---

## B08 — Real qoldiq ombori

Savol: checklist **Вопрос 5(а)** + omborlar ro'yxati skrinshoti (`:230, :236-239`) · Bundle: `warehouses[]`, `selection.warehouse_guids` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Zaldagi tovar qaysi omborda turadi | `____` | ombor nomi AYNAN ruscha / `bilmayman` | `[skrinshot: ____]` |
| 1C'da jami nechta ombor/magazin bor | `____` | son / `bilmayman` | `[skrinshot: ____]` |
| Omborlar ro'yxati (hammasi) | `____` | nomlar ro'yxati / `bilmayman` | `[skrinshot: ____]` |
| Omborlar ro'yxati menyu yo'li | `____` | ekranda ko'rilgan AYNAN yo'l + `(экранда tekshirilsin)` belgisi olib tashlandi / `topilmadi` / `bilmayman` | `[skrinshot: ____]` |
| Boshqa omborlarda ham savdo qoldig'i bormi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| BinOS'da nechta filial bo'ladi | `____` | son | `[skrinshot: yo'q]` |

> Ruscha: «На каком складе в 1С числится товар, который реально стоит в зале?»

⚠️ **1:1 qoida.** Ikki 1C ombori bitta BinOS filialiga xaritalanmaydi — reja RAD etiladi. Tanlangan ombor ro'yxati AYNAN filiallarga mos bo'lishi kerak.

**Bo'sh qolsa:** `selection.warehouse_guids` tanlanmaydi. Xato tanlov ISTISNO BERMAYDI — fayl barcha tekshiruvlardan
o'tadi. Uni faqat quruq yurish hisobotidagi sanoqlar ko'rsatadi: `missing_stock_rows`,
`stock_only_in_unselected_warehouse_rows`, `unselected_warehouse_stock_qty` (`classify.py:567-571`). Bu band
javobsiz qolsa, o'sha sanoqlar kutilganmi yoki xato tanlov belgisimi — hal qilib bo'lmaydi.

---

## B09 — Qoldiq hisoboti nomi va sozlamalari

Savol: checklist **Вопрос 5(б)** + 2- va 3-skrinshotlar (`:231, :240-249`) · Bundle: `manifest.stock_qty_by_warehouse` solishtiruvi · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Hisobot NOMI | `____` | AYNAN ruscha nom / `bilmayman` | `[skrinshot: ____]` |
| Hisobot varianti nomi (hisobot ustida ko'rinadi) | `____` | AYNAN nom / `variant ko'rinmadi` / `bilmayman` | `[skrinshot: ____]` |
| Hisobot menyu yo'li | `____` | ekranda ko'rilgan AYNAN yo'l / `topilmadi` / `bilmayman` | `[skrinshot: ____]` |
| **Qaysi qoldiq ko'rsatkichi olinadi** `(экранда tekshirilsin)` | `____` | ustun sarlavhasi AYNAN ekrandagidek. Uchrashi mumkin: «Конечный остаток» / «В наличии» / «Доступно» — ro'yxat TASDIQLANMAGAN, boshqa nom bo'lsa shunday yoziladi / `bilmayman` | `[skrinshot: ____]` |
| «Настройки…» oynasi skrinshoti olindimi (MAJBURIY) | `____` | `ha (nechta vkladka: ____)` / `yo'q` | `[skrinshot: ____]` |
| Hisobot sanasi va olingan vaqti | `____` | `YYYY-MM-DD HH:MM` / `olinmadi` | `[skrinshot: yo'q]` |
| «Итого» qatoridagi qiymat | `____` | AYNAN raqam / `olinmadi` / `bilmayman` | `[skrinshot: ____]` |
| Do'kon shu hisobotga ishonadimi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Поставьте сегодняшнюю дату, нажмите "Сформировать" и покажите верх отчёта и строку "Итого".»

⚠️ «Выбрать вариант» bosilmaydi. «Настройки…» oynasida faqat vkladkalar bosiladi, ko'rinish pereklyuchateli tegilmaydi.

**Bo'sh qolsa:** totals reconciliation qadami yozilmaydi — ekstraktor qaysi ko'rsatkichni o'qishi va nima bilan solishtirilishi noaniq qoladi.

---

## B10 — «Виды цен» ro'yxati

Savol: checklist **Вопрос 6, «Где посмотреть»** (`:264-269`) · Bundle: `price_types[]` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Jami nechta narx turi | `____` | son / `bilmayman` | `[skrinshot: ____]` |
| Narx turlari nomlari (hammasi) | `____` | AYNAN ruscha nomlar ro'yxati / `bilmayman` | `[skrinshot: ____]` |
| «Виды цен» menyu yo'li | `____` | ekranda ko'rilgan AYNAN yo'l / `topilmadi` / `bilmayman` | `[skrinshot: ____]` |
| «Розничная цена» kartochkasi olindimi | `____` | `ha` / `yo'q` / `bunday nom yo'q` | `[skrinshot: ____]` |
| «Цена поставщика» kartochkasi olindimi | `____` | `ha` / `yo'q` / `bunday nom yo'q` | `[skrinshot: ____]` |

> Ruscha: «Покажите, пожалуйста, список "Виды цен" полностью.»

⚠️ Kartochka krestik bilan yopiladi; «Сохранить?» so'ralsa — «Нет».

**Bo'sh qolsa:** `price_types[]` to'ldirilmaydi; ro'yxatda yo'q narx turi ishlatilsa bundle RAD etiladi.

---

## B11 — Kassada ishlatiladigan narx turi

Savol: checklist **Вопрос 6(а)(б)(в)** (`:258-260`) · Bundle: `selection.retail_price_type_guid`, `selection.purchase_price_type_guid` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Kassa QAYSI narx turi bilan sotadi | `____` | AYNAN narx turi nomi / `bilmayman` | `[skrinshot: ____]` |
| Chakana narx qanday kiritiladi | `____` | `qo'lda (hujjat bilan)` / `avtomatik hisoblanadi (наценка)` / `bilmayman` | `[skrinshot: yo'q]` |
| «Цена поставщика» yangilanishi | `____` | `har kirimda avtomatik` / `qo'lda` / `ancha yangilanmagan` / `bilmayman` | `[skrinshot: yo'q]` |
| Kelish narxi uchun ishlatiladigan tur | `____` | AYNAN nom / `ishlatilmaydi (null)` / `bilmayman` | `[skrinshot: yo'q]` |
| Tarozi tovarida narx 1 KG uchunmi | `____` | `ha, 1 kg` / `yo'q (nima uchun: ____)` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «По какой цене продаёт касса — "Розничная цена" или другой вид цены?»

> Ruscha: «Цена для весового товара указана за 1 килограмм?»

⚠️ Kelish narxi turi chakana narx turi bilan **bir xil bo'lsa bundle RAD etiladi** — ikkalasi boshqa-boshqa bo'lishi shart.

**Bo'sh qolsa:** eng xavfli bo'shliq — noto'g'ri narx turi butun katalogga noto'g'ri narx beradi va HECH QANDAY xato bermaydi.

---

## B12 — Oddiy (donali) tovar kartochkasi

Savol: checklist **Вопрос 7, skrinshot 1** (`:284-293`) · Bundle: `code`, `article`, `unit`, `name`, `kind` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| «Номенклатура» menyu yo'li | `____` | ekranda ko'rilgan AYNAN yo'l / `topilmadi` / `bilmayman` | `[skrinshot: ____]` |
| Kartochkada «Код» maydoni bormi, qayerda | `____` | `bor (joyi: ____)` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| «Код» qiymatining namunasi | `____` | AYNAN qiymat (oldingi nollar bilan) / `bilmayman` | `[skrinshot: ____]` |
| Kartochkada «Артикул» bormi, qayerda | `____` | `bor (joyi: ____)` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| «Артикул» qiymatining namunasi | `____` | AYNAN qiymat / `bo'sh` / `bilmayman` | `[skrinshot: ____]` |
| «Единица измерения» maydoni qayerda | `____` | joyi / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Ko'rilgan birlik nomlari (AYNAN) | `____` | ro'yxat (masalan «шт», «кг») / `bilmayman` | `[skrinshot: ____]` |
| «Штрихкоды» havolasi bormi | `____` | `bor` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| «Вид номенклатуры» maydonining qiymati `(экранда tekshirilsin)` | `____` | AYNAN ekrandagi qiymat (masalan «Товар» / «Услуга» / «Набор») / `maydon yo'q` / `bilmayman` | `[skrinshot: ____]` |

> Ruscha: «Откройте любой обычный штучный товар и прокрутите карточку до конца.»

⚠️ Guruhlarni faqat sarlavhasidan bosib ochiladi, galochkaga tegilmaydi.

⚠️ **Valyuta bu yerda SO'RALMAYDI** — u allaqachon yopilgan savol (so'rovnoma `:47-48`, yo'riqnoma
«do'konda SO'RALMAYDI» jadvali) va bundle'da valyuta maydoni umuman YO'Q (`bundle.py:42-46`).
Kartochka kadrida ko'rinib qolsa — hech narsa yozilmaydi, kadr qoladi.

**Bo'sh qolsa:** `sku` (1C «Код») va yangi mahsulot artikul zanjiri (`article → code → 1C-<guid>`) yozilmaydi
(`mapping.py:492-505`). «Вид номенклатуры» bo'sh qolsa — bundle'ning MAJBURIY `kind` maydoni
({goods, service, set, other}, `bundle.py:30, 201`) taxminga qoladi; `goods` dan boshqa qiymat qatorni
butunlay migratsiyadan chiqaradi (`classify.py:49-56`), ya'ni xato taxmin katalogning bir qismini jimgina yo'qotadi.

---

## B13 — Tarozi (vaznli) tovar kartochkasi

Savol: checklist **Вопрос 7, skrinshot 2** (`:291`) · Bundle: `is_weighted`, `unit`, `plu` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Ko'rilgan tovar nomi (AYNAN) | `____` | nom (masalan «148Код …») / `bilmayman` | `[skrinshot: ____]` |
| **«Весовой» belgisi qayerda** | `____` | `alohida rekvizit` / `вид номенклатуры darajasida` / `faqat birlik «кг»` / `umuman yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Rekvizit NOMI (agar bor bo'lsa) | `____` | AYNAN ruscha nom / `rekvizit yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Rekvizit qiymati shu tovarda | `____` | `Да` / `Нет` / `boshqa: ____` / `bilmayman` | `[skrinshot: ____]` |
| Birlik AYNAN qanday yozilgan | `____` | masalan «кг» / «кг.» / «килограмм» / `bilmayman` | `[skrinshot: ____]` |
| Kartochkada PLU/tarozi kodi maydoni bormi | `____` | `bor (nomi: ____)` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Kartochkadagi «Код» qiymati | `____` | AYNAN qiymat / `bilmayman` | `[skrinshot: ____]` |
| Nomdagi kod (masalan `148`) | `____` | AYNAN qiymat / `nomda kod yo'q` / `bilmayman` | `[skrinshot: ____]` |
| **Nomdagi kod kartochkadagi «Код» bilan bir xilmi** | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |

> Ruscha: «Откройте весовой товар, у которого в названии есть код весов, и прокрутите карточку до конца.»

⚠️ **«bilmayman» bu yerda xavfsiz emas.** `is_weighted` bo'sh qolsa, qiymat birlikdan kelib chiqadi: «кг» birlikdagi HAR BIR tovar avtomatik vaznli bo'lib qoladi.

**Bo'sh qolsa:** 454 ta «кг» tovarining vaznli belgisi taxminga qoladi — bu TAQIQLANGAN.

---

## B14 — Характеристики (variantlar)

Savol: checklist **Вопрос 7(а)** (`:279`) · Bundle: `has_characteristics` (MAJBURIY bool) · **BLOKER: HA (STOP — qamrovni belgilaydi)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Bitta tovar variantlarga bo'linadimi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Qanday belgilar bo'yicha | `____` | `o'lcham` / `rang` / `ta'm` / `boshqa: ____` / `ishlatilmaydi` / `bilmayman` | `[skrinshot: yo'q]` |
| Taxminan nechta tovarda (do'kon aytgan bo'lsa) | `____` | son / `bilmayman` | `[skrinshot: yo'q]` |
| 214 ta takror nom variantlar tufaylimi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Делите ли вы один товар на варианты — по размеру, цвету или вкусу?»

⚠️ Javob «ha» bo'lsa — bunday qatorlar V1 da **BLOKLANADI** (`CHARACTERISTICS_UNSUPPORTED`) va umuman ko'chmaydi. Bu pilot qamrovini o'zgartiradi.

**Bo'sh qolsa:** cutover qamrovi (nechta tovar ko'chadi) hisoblanmaydi.

---

## B15 — Серии (partiya / muddat)

Savol: checklist **Вопрос 7(б)** (`:280`) · Bundle: `has_series` (MAJBURIY bool) · **BLOKER: REJA**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| 1C'da partiya/seriya yuritiladimi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Yaroqlilik muddati yuritiladimi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Qaysi tovar guruhlarida | `____` | ro'yxat / `ishlatilmaydi` / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Ведёте ли вы в 1С партии или сроки годности?»

**Bo'sh qolsa:** `has_series` ni qator darajasida hisoblash qoidasi yozilmaydi (V1 da qatorni bloklamaydi, lekin hisobotga kiradi).

---

## B16 — Tarozilar soni va modellari

Savol: checklist **Вопрос 8(а)(в)** (`:304, :306`) · Bundle: bevosita emas — cutoverdan keyingi qayta yuklashni belgilaydi · **BLOKER: REJA**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Etiketka bosadigan tarozilar soni | `____` | son / `bilmayman` | `[skrinshot: yo'q]` |
| Har birining markasi va modeli | `____` | ro'yxat / `bilmayman` | `[skrinshot: ____]` |
| Hamma tarozida tovar kodlari bir xilmi | `____` | `ha` / `yo'q` / `bilmayman` | `[skrinshot: yo'q]` |
| Tovarlar taroziga qanday tushadi | `____` | `1C dan yuklash` / `tarozida qo'lda` / `tarozi dasturi orqali` / `bilmayman` | `[skrinshot: ____]` |
| Tarozi dasturi nomi (bo'lsa) | `____` | nom / `dastur yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Kim tarozilarni yuklaydi | `____` | ism/lavozim / `bilmayman` | `[skrinshot: yo'q]` |

> Ruscha: «Сколько у вас весов с печатью этикеток, какие марки, и у всех ли одинаковые коды товаров?»

⚠️ Tarozi dasturida «Загрузить» va «Выгрузить» bosilmaydi. 1C «Подключаемое оборудование» bo'limi faqat ko'rish uchun `(экранда tekshirilsin)`.

**Bo'sh qolsa:** cutoverdan keyin tarozilarni kim va qanday qayta yuklashi rejasiz qoladi; ikki tarozida bir xil PLU boshqa tovarga tegishli bo'lsa `plu_collision` siyosati kerak bo'ladi.

---

## B17 — PLU qayerda saqlanadi

Savol: checklist **Вопрос 8(б)** (`:305`) · Bundle: `products[].plu` · **BLOKER: HA (STOP)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| **Tarozi kodi qayerda beriladi** | `____` | `faqat tovar nomida` / `1C rekvizitida` / `tarozi dasturida (1C dan tashqarida)` / `bilmayman` | `[skrinshot: ____]` |
| 1C rekviziti bo'lsa — AYNAN nomi | `____` | ruscha nom / `rekvizit yo'q` / `bilmayman` | `[skrinshot: ____]` |
| Qiymat namunasi (AYNAN, nollar bilan) | `____` | masalan `0575` / `575` / `bilmayman` | `[skrinshot: ____]` |
| Nechta xonali | `____` | son / `har xil` / `bilmayman` | `[skrinshot: yo'q]` |
| Tarozi dasturida bo'lsa — ro'yxat eksporti mumkinmi | `____` | `ha` / `yo'q` / `kerak emas` / `bilmayman` | `[skrinshot: ____]` |
| Tarozi kodi tovar bilan qaysi maydon orqali bog'lanadi | `____` | maydon nomi / `bilmayman` | `[skrinshot: yo'q]` |
| Список9 fayli qaysi oyna/hisobotdan saqlangan (checklist **8(г)**, `:307`) | `____` | AYNAN oyna nomi / `esda yo'q` / `bilmayman` | `[skrinshot: ____]` |

> Ruscha: «Где задаётся код товара для весов — только в названии, в 1С или в программе самих весов?»

⚠️ **Nomdan PLU ajratib olish TAQIQLANGAN.** Nomdagi yozuv bir xil emas («148Код», «Код594», «476Корд» — 465 ta, 2 tasi takror) va u tarozi xotirasidagi kodga teng ekani hech qayerda isbotlanmagan.

**Bo'sh qolsa:** `plu` ustuni umuman chiqarilmaydi — BinOS'da tarozi etiketkalari tanilmaydi.

---

## B18 — Real tarozi etiketkasi / barkod namunasi

Savol: checklist **Вопрос 8, «Фото 1»** (`:310-311`) · Bundle: `plu` to'g'riligi + POS parseri · **BLOKER: HA (STOP — eng qattiq darvoza)**

Har etiketka uchun alohida qator. Kamida 2 ta, afzali 3 ta.

| # | Barkod ostidagi raqamlar (AYNAN nusxa) | Etiketkadagi vazn | Etiketkadagi summa | Tovar nomi (AYNAN) | Tarozi modeli | Foto |
|---|---|---|---|---|---|---|
| 1 | `____` | `____` | `____` | `____` | `____` | `[skrinshot: ____]` |
| 2 | `____` | `____` | `____` | `____` | `____` | `[skrinshot: ____]` |
| 3 | `____` | `____` | `____` | `____` | `____` | `[skrinshot: ____]` |

Har ustunda `bilmayman` / `o'qib bo'lmadi` yozish mumkin, lekin kamida BITTA to'liq o'qiladigan etiketka bo'lishi shart.

| Qo'shimcha maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Etiketka fotosi tushirildimi | `____` | `ha (nechta: ____)` / `yo'q` | `[skrinshot: ____]` |
| Shu tovarning 1 kg narxi 1C'da | `____` | qiymat / `bilmayman` | `[skrinshot: ____]` |

> Ruscha: «Сфотографируйте, пожалуйста, 2-3 настоящие этикетки с весов так, чтобы цифры под штрихкодом и название товара читались.»

**Dasturchi to'ldiradi (do'konda EMAS, fotolar bo'yicha):**

| Tekshiruv | Natija | Ruxsat etilgan qiymatlar |
|---|---|---|
| Barkod uzunligi | `____` | `13` / `boshqa: ____` / `aniqlanmadi` |
| Birinchi raqam (prefiks) | `____` | `2` / `boshqa: ____` / `aniqlanmadi` |
| 2–7-raqamlar PLU ga mos keladimi | `____` | `ha` / `yo'q` / `aniqlanmadi` |
| PLU maydonidagi qiymatning **ma'noli** xonalari (yetakchi nollarsiz) | `____` | `1-5` / `6` / `aniqlanmadi` |
| 8–12-raqamlar VAZN (gramm) mi yoki NARX mi | `____` | `vazn` / `narx` / `aniqlanmadi` |

⚠️ **STOP shartlari — IKKITASI, va ular BOSHQA-BOSHQA xavf:**

1. **Prefiks «2» emas yoki uzunlik 13 emas** → POS etiketkani vaznli deb **umuman qabul qilmaydi**
   (`scaleBarcode.ts:30`, `scale_barcode.py:44-46`) — tovar sotilmaydi, lekin xato **ko'rinadi**.
2. ⚠️ **8–12-raqamlar NARX bo'lsa** → POS etiketkani baribir O'QIYDI va o'sha raqamni **GRAMM** deb
   qabul qiladi (`scaleBarcode.ts:32-34`); bu holatni aniqlaydigan tekshiruv kodda **YO'Q**. Natijada
   savdo va ombor **jimgina** buziladi — bu 1-holatdan xavfliroq. Shuning uchun fotoda etiketkadagi vazn
   barkod raqamlariga teng ekani **ko'rinishi shart**.

Har ikki holatda avval POS/server parseri qayta ko'riladi, cutover keyin rejalashtiriladi; hozircha
454 ta «кг» tovar BinOS'da umuman yo'q va ularni faqat cutover yaratadi.

⚠️ **PLU xonasi.** Etiketkadagi PLU maydoni formatda **doim 6 xonali** (`scaleBarcode.ts:31`) — masala
maydonning kengligida emas, **qiymatida**: BinOS 5 xonadan uzun PLU ni saqlay olmaydi
(`products.py:33-46` — «PLU kodi 1-5 raqam bo'lishi kerak»), migrator esa 6 ma'noli xonani `INVALID_PLU`
deb belgilaydi (`normalize.py:209-216`). Ya'ni PLU qiymati **99999 dan katta** bo'lsa — avval BinOS
tomonida qaror kerak, extractor `plu` ni chiqara olmaydi.

**Bo'sh qolsa:** ekstraktorning `plu` chiqarishi ma'nosiz — format tasdiqlanmagan bo'ladi.

---

## Qo'shimcha bandlar (18 banddan tashqari — kechiktirilganidan qaytarilgan)

### B19 — `.epf` (tashqi ishlov) ochish ruxsati

Savol: checklist **4-bo'lim, eski 5-savol** (`:350` — u yerda bu savol «keyinroq» deb qoldirilgan) ·
Javob formati: yo'riqnoma **Band 4** ichida (`docs/FAYZAN_1C_DISCOVERY.md:342-345, :377`) — alohida band EMAS ·
**BLOKER: HA (ekstraktorni yurgizish mexanizmi)**

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Tashqi ishlov (`.epf`) ochishga ruxsat bormi | `____` | `ha` / `yo'q` / `xavfsiz rejim taqiqlaydi` / `administrator hal qiladi` / `bilmayman` | `[skrinshot: yo'q]` |
| Kim ruxsat bera oladi | `____` | ism/lavozim / `bilmayman` | `[skrinshot: yo'q]` |

⚠️ Discovery paytida HECH QANDAY `.epf` fayli ochilmaydi — faqat **og'zaki** imkoniyat so'raladi (yo'riqnoma `:345`:
«Сегодня мы ничего не открываем — это вопрос на будущее»).
⚠️ **Skrinshot so'ralmaydi va sozlamalar bo'limiga kirilmaydi.** «Xavfsiz rejim» / tashqi ishlovlarga ruxsat
bayrog'ining AYNAN nomi va joyi konfiguratsiyaga bog'liq va hech bir manbada tasdiqlanmagan
`(экранда tekshirilsin)`; «Администрирование» sahifalarida galochka **darhol saqlanadi** (so'rovnoma `:66-68`),
shuning uchun bu band faqat og'zaki javob bilan yopiladi.
⚠️ Agar administrator o'zi shunday bayroqni (masalan «Разрешить открывать внешние обработки»
`(экранда tekshirilsin)`) ko'rsatsa — u **galochka** va darhol saqlanadi: yoqilmaydi, o'chirilmaydi va
uni izlab «Администрирование» bo'limlari kezilmaydi. Javob og'zaki yoziladi. Ruxsatni keyinchalik
1C administratorining o'zi beradi (so'rovnoma `:66-68`).

**Bo'sh qolsa:** «read-only extraction» qadamining mexanizmi qolmaydi; yagona zaxira yo'l — `.dt` nusxa (B04).

### B20 — Cutover kuni mas'ullari

Savol: checklist **4-bo'lim, eski 30–32-savollar** (`:361`) · **BLOKER: REJA**

⚠️ Checklist bu uch savolni **cutover rejasi uchrashuviga** qoldirgan (`:361`) va yo'riqnomada ular uchun alohida
band yo'q. Discovery'da vaqt qolsa so'raladi; qolmasa — `kelishilmadi` deb yoziladi va bu **discovery'ni
to'liq emas qilmaydi** (daraja: REJA, STOP emas).

| Maydon | Javob | Ruxsat etilgan qiymatlar | Skrinshot |
|---|---|---|---|
| Cutover kuni savdoni kim to'xtatadi | `____` | ism/lavozim / `bilmayman` | `[skrinshot: yo'q]` |
| Smenalarni kim yopadi | `____` | ism/lavozim / `bilmayman` | `[skrinshot: yo'q]` |
| APPLY ni kim yozma tasdiqlaydi | `____` | ism / `bilmayman` | `[skrinshot: yo'q]` |
| Do'kon uchun qulay sana/vaqt | `____` | `YYYY-MM-DD HH:MM` / `kelishilmadi` | `[skrinshot: yo'q]` |

> Ruscha: «В какой день и час магазину удобнее всего остановить продажи на короткое время?»

---

## To'ldirish tugagach

### 1. Kim tekshiradi

| Bosqich | Kim | Nimani tekshiradi |
|---|---|---|
| 1 | Operator (do'konga borgan) | Bitta ham `____` qolmaganini; har `bilmayman` yoniga «kim bilishi mumkin» yozilganini |
| 2 | Dasturchi (migrator mas'uli) | Har skrinshot fayli mavjudligini va bandga mos kelishini; B18 «Dasturchi to'ldiradi» jadvalini |
| 3 | Dasturchi | Quyidagi bloker jadvalini — bitta ham STOP ochiq qolmasligini |
| 4 | Ikkalasi | YAML blokini: har kalit yo to'ldirilgan, yo ataylab `null` |
| 5 | Ikkalasi | 🔒 **Maxfiylik o'tishi:** faylda parol, litsenziya raqami / PIN, AnyDesk yoki RDP ID+paroli, telefon raqami, e-mail, karta/bank rekviziti **yo'qligi**; fayl repo ichida **emasligi** (qoida 10–12) |

Tekshiruv natijasi shu faylning oxiriga yoziladi: sana, tekshirgan kishi, `TAYYOR` yoki `TO'LIQ EMAS (qaysi bandlar: ____)`.

### 2. Fayllar qayerga qo'yiladi

| Nima | Qayerga | Qoida |
|---|---|---|
| **To'ldirilgan shu fayl** | Internetsiz ish kompyuteridagi `1c-discovery/<YYYY-MM-DD>/FAYZAN_1C_DISCOVERY_RESULT_<YYYY-MM-DD>.md` | ⚠️ 🔒 **Repoga commit QILINMAYDI.** Shablon o'zi (bu fayl) **o'zgarmaydi** — nusxasi to'ldiriladi |
| Skrinshotlar | O'sha papka | ⚠️ Repoga commit QILINMAYDI |
| Etiketka fotolari | O'sha papka | ⚠️ Repoga commit QILINMAYDI |
| `.dt` / `.cf` / `.cfe` | Checklist «Правила для копии базы» (`:197-208`) bo'yicha | ⚠️ Telegram / e-mail / bulut orqali yuborilmaydi; ish tugagach o'chiriladi va egasiga yozma xabar beriladi |
| Nazorat Excel hisobotlari (B04) | O'sha papka, fayl nomida sana bilan | Faqat rekonsiliatsiya uchun |
| Skrinshot / foto / to'ldirilgan fayl — **qachon o'chiriladi** | — | Bundle validatsiyasi tugagach o'chiriladi va **egasiga yozma xabar beriladi** (nusxa bilan bir xil qoida, yo'riqnoma `:88`) |

> ⚠️ 🔒 **Nega repoga emas.** To'ldirilgan fayl ichida do'konning ulanish satri (`Srvr=`/`File=`), xodim ismlari,
> ombor va narx ma'lumoti bo'ladi. Bu repoda `git add -A` bilan ishlaydigan «push qil» qoidasi bor (`CLAUDE.md`),
> ya'ni `docs/` ga qo'yilgan to'ldirilgan fayl **avtomatik commit bo'lib GitHub'ga chiqib ketadi**.
> Shuning uchun to'ldirilgan natija repo ichiga **umuman kiritilmaydi**.
>
> Agar baribir repoda saqlash kerak bo'lsa — avval `.gitignore` ga yo'l qo'shiladi va fayl
> **tozalangan** holatda (ulanish satri, ismlar, raqamlar olib tashlangan) saqlanadi; qaror egasi bilan kelishiladi.

### 3. Blokerlar — bo'sh qolsa ekstraktor BOSHLANMAYDI

| Band | Bundle / CLI maydoni | Bo'sh qolsa nima bo'ladi | Daraja |
|---|---|---|---|
| B01 | `infobase.platform_version` · `configuration_name` · `configuration_version` | Bundle bu uch maydonsiz RAD etiladi; bitta ham so'rov yozib bo'lmaydi | **STOP** |
| B02 | — (`is_weighted`, `plu` manbai) | Qo'shimcha rekvizitlar `.cf` ga kirmaydi — qayerdan o'qish noma'lum | **STOP** |
| B03 | — (ekstraktorni yurgizish joyi) | Noto'g'ri bazadan olingan eksport tekshiruvdan O'TADI, lekin eskirgan bo'ladi | **STOP** |
| B04 | `products[].guid` | 2026-08 fayllarida GUID ustuni yo'q edi; GUID'siz har qator `MISSING_GUID` | **STOP** |
| B04-rozilik | `access.owner_written_consent` | 🔒 Nusxa olingan, lekin yozma rozilik yo'q — nusxa ochilmaydi va olib ketilmaydi | **STOP** |
| B05 | — (metadata nomlari) | B04 `yo'q` bo'lsa: so'rovlarni kompilyatsiya qilib sinash imkoni yo'q | shartli **STOP** |
| B08 | `selection.warehouse_guids` | Xato tanlov istisno bermaydi; uni faqat hisobot sanoqlari ko'rsatadi (`missing_stock_rows`, `unselected_warehouse_stock_qty`) | **STOP** |
| B09 | `manifest.stock_qty_by_warehouse` | Totals reconciliation yozilmaydi | **STOP** |
| B10 | `price_types[]` | Ro'yxatda yo'q narx turi ishlatilsa bundle RAD | **STOP** |
| B11 | `selection.retail_price_type_guid` (+ `purchase_price_type_guid`) | Noto'g'ri narx turi butun katalogga noto'g'ri narx beradi, xatosiz | **STOP** |
| B12 | `code`, `article`, `unit`, `kind` | `sku` va artikul zanjiri yozilmaydi; noma'lum birlik `UNKNOWN_UNIT` (`decide`, block EMAS) beradi va `unknown_unit` siyosatini MAJBUR qiladi — `block` (butun reja rad) yoki `skip_row` (qator o'tkaziladi), standart qiymat YO'Q (`mapping.py:34, 363-371`) | **STOP** |
| B13 | `is_weighted` | Bo'sh qolsa «кг» birlikdagi HAR BIR tovar vaznli bo'lib qoladi | **STOP** |
| B14 | `has_characteristics` (MAJBURIY bool) | `true` qatorlar BLOKLANADI — pilot qamrovi hisoblanmaydi | **STOP** |
| B17 | `products[].plu` | `plu` umuman chiqarilmaydi; nomdan ajratish TAQIQLANGAN | **STOP** |
| B18 | `plu` formati + POS parseri | Prefiks/uzunlik tasdiqlanmasa 454 ta «кг» tovar sotilmaydi; 8–12-raqamlar narx bo'lsa POS uni GRAMM deb o'qiydi va savdo/ombor JIMGINA buziladi (`scaleBarcode.ts:30-34`) | **STOP** |
| B19 | — (`read-only extraction` mexanizmi) | `.epf` yurgizib bo'lmasa yagona yo'l — `.dt` nusxa (B04); og'zaki javob yetarli, skrinshot talab qilinmaydi | **STOP** |
| B03-soat | `snapshot_at` offseti (matritsa `D12`) | 1C mashinasining soati/zonasi tasdiqlanmasa offset noto'g'ri bo'lishi mumkin; `AlreadyApplied` / `StaleSnapshotError` taqqoslashlari xato ishlaydi (`apply.py:119-127`) | REJA |
| B07 | `snapshot_at` ishonchliligi | Freeze oynasi hisoblanmaydi; eski/teng snapshot apply'ni bloklaydi | REJA |
| B06 | — | Freeze qadamining mas'uli noma'lum | REJA |
| B15 | `has_series` | Qator darajasidagi hisoblash qoidasi yozilmaydi | REJA |
| B16 | — (tarozini qayta yuklash) | Cutoverdan keyingi qadam rejasiz qoladi | REJA |
| B20 | — (imzo/mas'ul) | Runbook «short freeze» va «APPLY» qadamlarida mas'ul satri bo'sh | REJA |

**Qoida:** bitta ham **STOP** ochiq bo'lsa — ekstraktor (`.epf`) yozish boshlanmaydi va cutover sanasi belgilanmaydi.

### 4. Discovery'dan keyin darhol

| # | Qadam |
|---|---|
| 1 | STOP blokerlarini yopish (yoki yopilmaganini yozma qayd etish) |
| 2 | B01 javobi bo'yicha barcha `(экранда tekshirilsin)` belgilarini olib tashlash yoki tasdiqlash |
| 3 | Quyidagi YAML blokini to'ldirish va `docs/FAYZAN_CUTOVER_RUNBOOK_DRAFT.md` bilan solishtirish |

---

## Mashina o'qiy oladigan qism (ekstraktor sozlamasi — HAMMASI BO'SH)

Bu blok keyinchalik ekstraktor sozlamasiga aylanadi. Hozir hamma qiymat `null` yoki bo'sh ro'yxat.
Bilinmagan qiymat `null` qoladi — **taxmin yozish taqiqlangan**.

```yaml
# BinOS 1C discovery natijasi — ekstraktor sozlamasi (qoralama)
# Manba savollar: integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md
# Fayl shartnomasi:  integrations/1c/BINOS_1C_BUNDLE_V1.md
#
# ⚠️ Bu blok — QORALAMA. `binos-1c-discovery-v1` nomli sxema BinOS kodida HOZIRCHA YO'Q va uni
#    hech bir buyruq o'qimaydi; u faqat ekstraktor yozilganda sozlama uchun asos bo'ladi.
#    Ziddiyat bo'lsa YUQORIDAGI JADVAL javobi asosiy — YAML jadvaldan ko'chiriladi, teskarisi emas.
#
# SIR YOZILMAYDI: parol, litsenziya/PIN, AnyDesk yoki RDP ID+paroli, telefon, e-mail,
# bank/karta rekviziti — hech bir kalitga. Kerak bo'lsa faqat og'zaki (qoida 10-11).
# Bu blok ham to'ldirilgan fayl bilan birga repodan TASHQARIDA qoladi.
schema: binos-1c-discovery-v1

meta:
  collected_at: null            # YYYY-MM-DD
  collected_by: null
  shop: null
  company_code: fayzan1
  db_copy_taken: null           # dt | folder | none | null
  screenshots_dir: null

infobase:                       # B01
  platform_version: null        # MAJBURIY (bundle)
  configuration_name: null      # MAJBURIY (bundle)
  configuration_version: null   # MAJBURIY (bundle)
  infobase_id: null             # ixtiyoriy

configuration:                  # B02
  modified: null                # true | false | null
  extensions_present: null      # true | false | null
  extra_attributes_listed: null # true | false | null
  extra_reports_listed: null    # true | false | null
  upgrade_planned: null

connection:                     # B03
  kind: null                    # file | server | web | other | null
  string_prefix: null           # "File=" | "Srvr=" | "ws=" | null
  base_count: null
  pos_base_name: null
  exports_2026_08_from_this_base: null
  access_method: null           # local | server | rdp | anydesk | browser | null

access:                         # B04, B05, B19
  dt_copy_available: null       # true | false | owner_consent_required | null
  dt_copy_taken_at: null
  dt_copy_made_by_role: null    # 1c_admin | service_firm | null  (kassir EMAS)
  shop_closed_during_copy: null # true | false | null
  owner_written_consent: null   # true | false | null
                                # dt_copy_taken_at bor + owner_written_consent != true  -> STOP
  cf_contains_password: null    # true | false | not_asked | null  (true -> fayl olinmaydi)
  cf_available: null
  cfe_available: null
  cfe_count: null
  remote_view_allowed: null
  epf_allowed: null             # true | false | safe_mode_forbids | null  (og'zaki javob, skrinshotsiz)

pos:                            # B06, B07
  cashier_software: null        # 1c_rmk | external | null
  cashier_software_name: null
  till_count: null
  sales_posted_to_1c: null      # immediate | shift_close | evening | manual | null
  sales_delay_observed: null    # true | false | null
  negative_stock_reason: null

warehouses:                     # B08, B09
  menu_path: null               # (экранда tekshirilsin) — tasdiqlanmaguncha null
  total_count: null
  all_names: []
  sales_floor_name: null        # -> selection.warehouse_guids
  binos_branch_count: null
  stock_report_name: null
  stock_report_variant: null
  stock_report_menu_path: null
  stock_measure: null           # konechny_ostatok | v_nalichii | dostupno | other | null
  stock_settings_screenshot: null
  stock_total_value: null
  stock_total_taken_at: null
  report_trusted: null

price_types:                    # B10, B11
  menu_path: null               # (экранда tekshirilsin)
  total_count: null
  all_names: []
  retail_name: null             # -> selection.retail_price_type_guid  (MAJBURIY)
  purchase_name: null           # -> selection.purchase_price_type_guid (retail'dan FARQLI)
  retail_entry_mode: null       # manual | computed | null
  purchase_update_mode: null    # auto | manual | stale | null
  price_is_per_kg: null         # true | false | null

product_card:                   # B12, B13
  nomenclature_menu_path: null  # (экранда tekshirilsin)
  code_field_present: null
  code_sample: null
  article_field_present: null
  article_sample: null
  unit_field_present: null
  unit_names_seen: []           # AYNAN: "шт", "кг", …  -> `--unit-map` mazmuni
  barcodes_link_present: null
  item_kind_value: null         # «Вид номенклатуры» ekrandagi qiymati -> bundle `kind` (MAJBURIY)
  name_code_equals_card_code: null   # true | false | null  (B13: nomdagi kod = «Код»?)
  weighted_flag_location: null  # attribute | item_kind | unit_only | none | null
  weighted_attribute_name: null
  weighted_sample_value: null
  plu_field_on_card: null

features:                       # B14, B15
  characteristics_used: null    # true | false | null  (true -> BLOCKED qatorlar)
  characteristics_scope: null
  characteristics_est_count: null
  duplicate_names_are_variants: null
  series_used: null             # true | false | null
  expiry_tracked: null

scales:                         # B16, B17, B18
  count: null
  models: []
  codes_identical_across_scales: null
  upload_method: null           # from_1c | manual | scale_software | null
  scale_software_name: null
  plu_source: null              # name_only | 1c_attribute | scale_software | null
  plu_attribute_name: null
  plu_sample_value: null        # AYNAN, oldingi nollar bilan
  plu_digits: null
  label_samples: []             # [{barcode: null, weight: null, sum: null, product: null, model: null}]
  label_length: null            # 13 | other | null   (dasturchi to'ldiradi)
  label_prefix: null            # "2" | other | null  (dasturchi to'ldiradi)
  label_plu_digits: null        # 1-5 | 6 | null      (MA'NOLI xona soni; dasturchi to'ldiradi)
  label_embeds: null            # weight | price | null (dasturchi to'ldiradi; price -> POS uni GRAMM deb o'qiydi)

barcodes:                       # B17 (checklist 8(г))
  spisok9_source_window: null

cutover:                        # B20
  stops_sales: null
  closes_shifts: null
  approves_apply: null
  preferred_datetime: null

status:
  blockers_open: []             # masalan: [B01, B11, B18]
  unknown_fields: []            # "bilmayman" javob berilgan maydonlar
  secrets_check_passed: null    # true = faylda parol/ID/telefon/karta yo'q (qoida 10-11)
  kept_outside_repo: null       # true = fayl repo ichida emas (qoida 12)
  ready_for_extractor: null     # true faqat STOP blokerlar yopilganda
                                #   VA secrets_check_passed = true
                                #   VA (dt_copy_taken_at = null YOKI owner_written_consent = true)
```

---

## Tekshiruv imzosi

| Maydon | Javob |
|---|---|
| To'ldirishni tugatgan sana | `____` |
| Operator | `____` |
| Dasturchi tekshiruvi sanasi | `____` |
| Dasturchi | `____` |
| Holat | `TAYYOR` / `TO'LIQ EMAS (bandlar: ____)` |
| Ochiq STOP blokerlar | `____` |
| 🔒 Maxfiylik o'tishi (qoida 10–12) | `o'tdi` / `o'tmadi (nima topildi: ____)` |
| 🔒 Fayl repodan tashqarida saqlanmoqda | `ha` / `yo'q` |
| 🔒 Nusxa/skrinshot o'chirilishi kerak bo'lgan sana | `____` / `nusxa olinmadi` |
