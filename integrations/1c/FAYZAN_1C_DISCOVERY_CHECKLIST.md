# Fayzan 1C — discovery checklist (extractor yozishdan OLDIN)

Extractor (`.epf` tashqi ishlov berish) **taxmin bilan yozilmaydi**. Quyidagi savollarga 1C
administratori ANIQ javob bergandan keyin, aynan shu konfiguratsiya metadata nomlari bilan yoziladi.

## Hozir MA'LUM bo'lgan narsalar (manba: 2026-08 da yuborilgan eksport fayllari)

| Fakt | Manba |
|---|---|
| Hisobot `Цены по видам цен`: «Номенклатура, Упаковка», «Розничная цена», «Цена поставщика» (ikkalasi «Включает НДС») | sena.xls |
| Hisobot `Остатки на складах`: guruh «Магазин» → «Основной» va «Итого»; birliklar шт (6585), кг (454) | astatka.xls |
| Barkod ro'yxati: «Владелец / Упаковка / Штрихкод / Тип штрихкода»; EAN13 58158, EAN8 533, CODE39 458, CODE128 48, ITF14 12, EAN128 2 | Список9.xls |
| Eksportlarda Ссылка/GUID, Код, Артикул ustunlari YO'Q | 3 ta fayl tahlili |
| 214 ta takror nom guruhi (666 qator), 552 ta manfiy qoldiq qatori | fayzan_artefakt.out |
| Tarozi PLU'lari nom ichida («NNNКод»), 465 ta, 2 takror | tarozi.out |
| Til/valyuta: rus tilidagi 1C, сом, +996, filial vaqt zonasi Asia/Bishkek | fayllar, BinOS |

Hech biri konfiguratsiya nomini aniqlamaydi — hisobot sarlavhalari Розница va УТ da bir xil.

## 1C administratori javob berishi kerak

### A. Platforma va baza
1. 1C platforma versiyasi (Справка → О программе → «1С:Предприятие 8.3 (8.3.xx.xxxx)»).
2. Konfiguratsiya nomi, redaksiyasi va versiyasi (o'sha oyna: «Розница 2.3.x», «Управление торговлей 11.x», ERP yoki boshqa).
3. Konfiguratsiya **o'zgartirilganmi** (Конфигуратор → «Конфигурация на поддержке», o'zgarishlar bormi)?
4. Baza turi: fayl yoki klient-server? Nechta foydalanuvchi bir vaqtda ishlaydi?
5. Tashqi ishlov berish (`.epf`) ochishga ruxsat bormi (xavfsiz rejim, «Безопасный режим», huquqlar)?
6. 1C ga kirish usuli (RDP/lokal) va eksport faylini BinOS operatoriga uzatish yo'li.

### B. Nomenklatura identiteti
7. Mahsulot katalogi qaysi spravochnik (odatda `Справочник.Номенклатура`)? Guruh (papka) va xizmatlar qanday ajratilgan?
8. **Ссылка (GUID) barqarormi** — mahsulotlar hech qachon yangidan yaratilib/ko'chirilmaganmi (baza qayta tiklanmaganmi, boshqa bazadan yuklanmaganmi)?
9. `Код` noyobmi va nima uchun ishlatiladi? `Артикул` to'ldiriladimi, noyobmi?
10. 214 ta takror nom guruhi: ular ALOHIDA nomenklatura elementlarimi (turli GUID), xarakteristikalarmi, qadoqlarmi yoki xato dublikatlarmi?
11. **Характеристики номенклатуры** ishlatiladimi (o'lcham/rang/ta'm)? Qaysi mahsulotlarda?
12. **Серии** (partiya/yaroqlilik muddati) ishlatiladimi? (V1 da faqat hisobot uchun; lot faollashtirilmaydi.)
13. O'chirishga belgilangan (пометка удаления) elementlar bormi va ular migratsiyaga kirmasligi to'g'rimi?

### C. Birliklar va qadoqlar
14. Asosiy birliklar ro'yxati (шт, кг, л, упак, …) va OKEI kodlari.
15. **Упаковки / единицы измерения** (bir mahsulotda bir nechta birlik, koeffitsiyent) ishlatiladimi?
16. Tarozi mahsulotlari qanday belgilanadi (весовой флаг, «кг» birligi) va PLU qayerda saqlanadi (nomda «NNNКод» mi yoki alohida rekvizit / tarozi obmen sozlamalarida)?

### D. Qoldiq manbai
17. Nechta ombor bor? «Магазин Файзан» va «Основной» — qaysi biri ombor, qaysi biri guruh/tashkilot/magazin?
18. **Real joriy qoldiq qaysi omborda** (BinOS'ga ochilish qoldig'i sifatida shu olinadi)?
19. Qoldiq qaysi registrdan olinadi (Товары на складах / Товары в рознице / Товары организаций)? Hisobot qaysi registrga asoslangan?
20. Manfiy qoldiqlar (552 qator) sababi: sotuv kirimdan oldin yozilgan, «Товар Nсом» kabi xizmat tovarlari, yoki boshqa? Cutover'da ularni 0 qilish mumkinmi?
21. Qoldiq bo'yicha nazorat yoqilganmi (manfiy qoldiqqa ruxsat)?

### E. Narxlar
22. Barcha narx turlari ro'yxati. **Chakana narx** qaysi tur («Розничная цена»)?
23. Kelish narxi uchun qaysi tur («Цена поставщика») yoki tannarx registri?
24. Narxlar QQS (NDS) bilan kiritiladimi, stavka qancha?
25. Narxlar filial/ombor bo'yicha farq qiladimi?

### F. Barkodlar
26. Barkodlar qaysi registrda (`РегистрСведений.Штрихкоды` yoki boshqa)? Qadoq/xarakteristikaga bog'lanadimi?
27. Nega Список9 da 44 321 ta «Владелец» bor, narxli mahsulot esa ~8 285? (arxiv tovarlarmi?)
28. CODE39/CODE128 barkodlar (81 ta raqam bo'lmagan) nima uchun ishlatiladi — POS skanerida kerakmi?
29. Do'kon ichki barkodlari (2… bilan boshlanadigan 13 xonali) qanday generatsiya qilinadi?

### G. Cutover kuni
30. Oxirgi eksport vaqtida 1C savdosini to'xtatish mumkinmi (necha daqiqa)? Yoki aniq vaqt belgisi bilan qoldiq olinadimi?
31. POS/РМК smenalari: cutover oldidan barcha smenalar yopiladimi?
32. Eksport faylini kim ishga tushiradi va kim tasdiqlaydi (mapping `approved_by`)?

## Javoblardan keyin

1. Extractor aynan shu metadata nomlari bilan yoziladi (faqat O'QISH: `Запрос`, yozuv/hujjat/registr yozuvi YO'Q).
2. Sinov bazasida (1C nusxasi) eksport → `migrate_1c verify-bundle`.
3. Real Fayzan eksporti → `dry-run` (production'da faqat o'qish) → conflict review.
