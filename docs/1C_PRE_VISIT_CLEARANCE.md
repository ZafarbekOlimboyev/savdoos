# Fayzan 1C — TASHRIFDAN OLDINGI DARVOZA (pre-visit clearance)

**Maqsad:** do'konga borishdan OLDIN 13 ta javobni olish. Javobsiz borish — kechani behuda sarflash.

**Bu hujjat nima EMAS.** Bu do'kondagi ijro yo'riqnomasi emas (u — `docs/FAYZAN_1C_DISCOVERY.md`,
18 band) va egaga yuboriladigan to'liq so'rovnoma ham emas (u — `integrations/1c/FAYZAN_1C_DISCOVERY_CHECKLIST.md`,
8 savol). **Nusxa olish tartibi** ham shu yerda takrorlanmaydi — u so'rovnomaning **Вопрос 3** bo'limida,
kun tartibi va «Правила для копии базы» bilan birga.

Bu — faqat **darvoza**: javoblar kelmaguncha tashrif sanasi belgilanmaydi.

---

## Qoidalar

1. **Parol so'ralmaydi.** Na 1C paroli, na Windows, na AnyDesk/RDP. Kerak bo'lsa — faqat telefonda
   og'zaki, nusxa ochiladigan kuni (so'rovnoma qoidasi).
2. **Javob bilinmasa — `bilmayman`.** Taxmin yozilmaydi.
3. **Skrinshot shart emas — telefon fotosi yetadi.** «Skrinshot qanday olinadi» degan to'siqni olib tashlaymiz.
4. **Litsenziya raqamini barmoq bilan yoping**, rasmni tahrirlamang.
5. Savollar **ikki manzilga** bo'linadi: egasiga va 1C xizmat firmasiga. Egadan texnik javob kutilmaydi.

---

## A. Egaga (4 ta javob — boshqasini u bilmaydi)

| # | Savol | Nima hal qiladi |
|---|---|---|
| 7 | Baza nusxasini berishga rozimisiz? (yozma rozilik) | Rozilik yo'q = butun yo'l yopiq |
| — | 1C administratoringiz yoki xizmat firmasi kim? **Ism + telefon** | Shusiz nusxa kuni bajarilmaydi (shablonda bu maydon hali bo'sh) |
| 8 | Nusxa qaysi kuni olinadi? (do'kon yopilgan, smenalar yopilgan) | Kechani rejalashtirish |
| 9 | Nechta etiketka bosadigan tarozi bor, markasi/modeli qanday? | Tarozi yo'lining butun tarmog'i shunga bog'liq |

## B. 1C xizmat firmasiga (egasi shu xabarni forward qiladi)

| # | Savol | Nima hal qiladi |
|---|---|---|
| 1 | Platforma versiyasi (8.3.x.yyyy) | Uyda QAYSI platforma o'rnatilishi; `.dt` faqat teng yoki yangiroqda ochiladi |
| 2 | Konfiguratsiya nomi va versiyasi | Metadata nomlari; hozir NOMA'LUM |
| 3 | Litsenziya: **Базовая / ПРОФ** | Базовая'da bir qancha yo'l umuman yo'q |
| 4 | Baza turi: **File= / Srvr= / ws=** | `ws=` bo'lsa bu reja butunlay boshqa |
| 5/6 | Nusxa kim va qanday oladi (`.dt` yoki papka) | Ijrochi |
| ★ | **Bu bazaning zaxira nusxasi bormi? Kechagi `.dt` bormi?** | **Bor bo'lsa — do'konni yopish KERAK EMAS** |
| ★ | Konfiguratsiya o'zgartirilganmi? Kengaytmalar bormi? | Nusxa uydan ochilmasligi mumkin |

★ — bu ikkitasi mening qo'shimcham, 13 talikda yo'q edi. Birinchisi butun kechani bekor qilishi mumkin.

## C. Bitta foto bilan yopiladigan 3 ta javob

1C ishga tushirish oynasi — **ochmasdan**, ishchi bazani **bir marta** bosib, butun oynani suratga olish:

- **4-savol** — pastki qatordagi `File=` / `Srvr=` / `ws=`
- ★ **«Конфигуратор» tugmasi bormi** — yo'q bo'lsa (faqat thin client) `.dt` yo'li shu kompyuterda yo'q
- baza ro'yxati — nechta baza bor, kassa qaysi birida

Yana ikkita foto:

- **1/2-savol** — ☰ «Сервис и настройки» → «О программе» oynasi (litsenziya raqami yopilgan)
- ★ **baza fayli hajmi** — `File=` papkasini ochib, «Таблица»/«Details» ko'rinishida `1Cv8.1CD` qatorini
  suratga olish (nom, sana, **hajm**). `Srvr=` bo'lsa — firmadan GB'da so'rang.
  **Nega:** hajm fleshka turini, nusxa vaqtini va «60 daqiqa» degan raqam haqiqatmi-yo'qmi — hammasini hal qiladi.
  Hozir repo bu suratni nusxa olingandan KEYIN so'raydi, ya'ni qaytarib bo'lmaydigan qarordan keyin.

## D. Tarozi (do'konda, 1C'ga tegmasdan)

| # | Savol | Izoh |
|---|---|---|
| 9 | Har bir tarozi korpusidagi **yorliq fotosi** — marka + model | Klaviaturaga tegilmaydi |
| 10 | Kompyuterdagi tarozi dasturining **nomi va versiyasi** | Yorliq xossalari yoki «Programs and Features» dan; dasturni ochish shart emas |
| 11 | **Bitta real etiketka fotosi** — barkod, kg narxi va SUMMA ko'rinsin | Summa bo'lmasa kontrakt isbotlanmaydi |

⚠️ **Hech qachon bosilmaydi:** tarozi dasturida «Выгрузить»/«Загрузить»/«Отправить» — bular tarozi
xotirasiga YOZADI. 1C'da «Выгрузить в весы» ham — 1C yangi PLU'larni o'z registriga yozishi mumkin.

## E. Og'zaki javob (egasi yoki katta kassir)

| # | Savol | Nima hal qiladi |
|---|---|---|
| 12 | Kassa qaysi narx turi bilan sotadi? | Noto'g'ri tanlov butun katalogni noto'g'ri narxda ochadi va **hech qanday xato bermaydi** |
| 13 | Haqiqiy javon qaysi omborda? («Основной» — tasdiqlanmagan) | Noto'g'ri ombor = jim nol qoldiq |
| ★ | Savdo 1C'ga qachon tushadi — darhol yoki kechikib? | Kechiksa, nusxadagi qoldiq do'kon qoldig'i EMAS |

---

## Ruscha matn — yuborish uchun

> **Владельцу**
>
> Здравствуйте! Перед визитом нужно несколько ответов — так мы не потратим ваш вечер впустую.
> Пароли не нужны ни один. Не знаете ответ — пишите «не знаю», не угадывайте.
>
> 1. Готовы ли вы дать копию базы? Нужно короткое письменное согласие.
> 2. Кто ваш администратор 1С или обслуживающая фирма — имя и телефон?
> 3. В какой день можно сделать копию (магазин закрыт, смены на кассах закрыты)?
> 4. Сколько у вас весов с печатью этикеток и какой они марки/модели?
> 5. Сфотографируйте телефоном наклейку на корпусе каждых весов (марка и модель).
> 6. Сфотографируйте ОДНУ настоящую этикетку с весов — чтобы были видны штрихкод,
>    цена за кг и СУММА.
> 7. Как называется программа для весов на компьютере? Посмотрите в «Пуск» или
>    «Программы и компоненты» — **открывать её не нужно**.
> 8. Запустите 1С. Появится список баз. Щёлкните по рабочей базе ОДИН раз и **не открывайте её**.
>    Сфотографируйте телефоном ВСЁ окно целиком, включая нижнюю строку.
> 9. Откройте 1С, ☰ «Сервис и настройки» → «О программе». Сфотографируйте окно.
>    Номер лицензии закройте пальцем.
> 10. Какой ценой продаёт касса? По какому складу лежит товар на полках?
>     Продажа попадает в 1С сразу или с задержкой? (если не знаете — спросите старшего кассира)
>
> ⚠️ В программе для весов **никогда** не нажимайте «Выгрузить», «Загрузить» или «Отправить» —
> это записывает в память весов.

> **Обслуживающей фирме** (перешлите это сообщение)
>
> Добрый день! Несколько вопросов по базе магазина «Файзан», ничего менять не нужно:
>
> 1. Версия платформы (8.3.x.yyyy) и точное название + версия конфигурации?
> 2. Лицензия базовая или ПРОФ?
> 3. База файловая (`File=`) или клиент-серверная (`Srvr=` / `ws=`)?
> 4. **Делаются ли резервные копии этой базы? Есть ли готовый файл `.dt` за вчера,
>    и может ли владелец его получить?**
> 5. Конфигурация на поддержке или изменена? Есть ли расширения конфигурации?
> 6. Размер базы в ГБ?
> 7. Кто и когда сможет сделать копию?
>
> Пароли присылать не нужно.

---

## Darvoza qoidasi

Tashrif sanasi **faqat** quyidagilar kelganda belgilanadi:

- [ ] 1, 2, 3, 4 — javob bor (platforma, konfiguratsiya, litsenziya, baza turi)
- [ ] ★ zaxira nusxa savoliga javob bor
- [ ] ★ baza hajmi ma'lum
- [ ] 7 — yozma rozilik bor
- [ ] administrator ismi va telefoni bor, sana kelishilgan
- [ ] 9, 10 — tarozi markasi va dasturi ma'lum
- [ ] **uyda 1C runtime hal qilingan** — litsenziya sotib olingan yoki rasmiylashtirilgan VA bir marta
      sinov `.dt` yuklab ko'rilgan. Bu hal bo'lmaguncha nusxa olishning ma'nosi yo'q:
      nusxani ochadigan hech narsa bo'lmaydi.

Bittasi ham bo'sh bo'lsa — **tashrif ko'chiriladi**, chunki bu ro'yxatdagi har bir bo'shliq
do'konni behuda yopish demakdir.
