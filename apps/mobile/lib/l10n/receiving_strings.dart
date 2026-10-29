// Paket M1 (qabul / kirim) tarjimalari.
//
// SHAKL (yadro bilan kelishilgan, o'zgartirmang):
//   * kalit — `tr('...')` ga beriladigan O'ZBEK LOTIN manba matni (aynan o'sha satr);
//   * `ruReceiving` — ruscha, `kyReceiving` — qirg'izcha tarjima; uzc (kirill) avtomatik;
//   * har kalit IKKALA xaritada bo'lishi SHART, boshqa manbadagi ayni kalit bilan
//     tarjima bir xil bo'lsin — `test/core_l10n_test.dart` ikkalasini tekshiradi;
//   * o'rinbosar `{nom}` shaklida (`trArgs`), transliteratsiyada saqlanadi.
//
// `lib/l10n.dart` bu xaritalarni birlashtiradi — l10n.dart ga TEGMANG.
// Asosiy lug'atda (`l10n.dart`) allaqachon bor kalitlar bu yerda TAKRORLANMAYDI.

/// M1 (qabul / kirim): ruscha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> ruReceiving = {
  'AI shartlari o‘zgardi. Rasmni qayta tanlang va yangilangan rozilik shartlarini tekshiring.':
      'Условия обработки ИИ изменились. Выберите фото снова и проверьте обновлённые условия согласия.',
  'AI uchun rozilik kerak. Rasmni qayta tanlang va rozilikni tasdiqlang yoki qatorlarni qo‘lda kiriting.':
      'Нужно согласие на обработку ИИ. Выберите фото снова и подтвердите согласие или введите строки вручную.',
  'Nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.':
      'Фото накладной будет отправлено в {name} для распознавания текста.',
  'Buni do‘kon egasi yoki administratori bir marta ruxsat berishi kerak.':
      'Это должен один раз разрешить владелец магазина или администратор.',
  'Hozir qatorlarni qo‘lda kiritishingiz mumkin.':
      'Сейчас вы можете ввести строки вручную.',
  // ── Qabul filiali ──
  'Bu tarozi yorlig‘i (og‘irlik kodlangan) — doimiy shtrix-kod qilib biriktirib bo‘lmaydi: har qadoqda kod boshqacha. Qadoqning o‘z EAN kodini skanerlang yoki mahsulotni kg birlikda PLU bilan kiriting.': 'Это весовая этикетка (в коде зашит вес) — её нельзя закрепить как постоянный штрихкод: у каждой упаковки код свой. Отсканируйте собственный EAN упаковки или заведите товар в кг с PLU.',
  'Qabul filiali: {name}': 'Филиал приёмки: {name}',
  'Filial ma’lumoti yuklanmoqda…': 'Загружаем данные филиала…',
  'Qabul filiali aniqlanmadi — aloqani tekshirib, qayta urinib ko‘ring.':
      'Не удалось определить филиал приёмки — проверьте связь и попробуйте снова.',
  'Siz «{current}» filialini ko‘ryapsiz, lekin kirim faqat «{actor}» filialiga yoziladi. Kirim qilish uchun «{actor}» filialiga o‘ting.':
      'Вы работаете в филиале «{current}», но приход записывается только в филиал «{actor}». Чтобы оформить приход, переключитесь на «{actor}».',
  '«{name}» filialiga o‘tish': 'Перейти в филиал «{name}»',
  // ── Bosh ekran / tarix ──
  'Kirim qilish uchun ruxsatingiz yo‘q.': 'У вас нет права оформлять приход.',
  'Qabullar tarixini ko‘rish uchun ruxsat yo‘q.': 'Нет права просматривать историю приёмок.',
  'Rasmni olib bo‘lmadi — kamera yoki galereyaga ruxsatni tekshiring.':
      'Не удалось получить фото — проверьте доступ к камере или галерее.',
  '{n} ta mahsulot': 'Товаров: {n}',
  // ── Hujjat (qo'lda / AI) ──
  'DEMO rejim: server AI’siz ishlayapti — qatorlar rasmdan O‘QILMAGAN. Har qatorni nakladnoy bilan solishtiring.':
      'ДЕМО-режим: сервер работает без ИИ — строки НЕ прочитаны с фото. Сверьте каждую строку с накладной.',
  'Partiyali mahsulotlar ro‘yxati yuklanmadi — qayta urinib ko‘ring.':
      'Не удалось загрузить список партионных товаров — попробуйте снова.',
  'Mahsulotlar tekshirilmoqda…': 'Проверяем товары…',
  'Ro‘yxat yuklanmadi — qayta urinish uchun bosing': 'Список не загружен — нажмите, чтобы повторить',
  'Omborga qo‘shish · tayyor {r}/{n}': 'Оприходовать · готово {r}/{n}',
  '{n} ta mahsulot · jami': 'Товаров: {n} · итого',
  '{n} ta qatorda xato bor — tuzating': 'Ошибки в строках: {n} — исправьте',
  '«{name}» olib tashlandi': '«{name}» удалён',
  'Kirim saqlanmadi': 'Приход не сохранён',
  'Hujjat saqlanmagan. Chiqsangiz kiritilgan qatorlar yo‘qoladi.':
      'Документ не сохранён. Если выйти, введённые строки пропадут.',
  'Qolish': 'Остаться',
  'Nomsiz': 'Без названия',
  'O‘chirish': 'Удалить',
  'AI o‘qidi: {name}': 'ИИ прочитал: {name}',
  'AI moslik {p}%': 'Совпадение ИИ {p}%',
  '{n} ta partiya': 'Партий: {n}',
  'Partiya': 'Партия',
  'Partiya · muddat': 'Партия · срок',
  'Mahsulotni tanlang yoki yangi mahsulot yarating': 'Выберите товар или создайте новый',
  'Kamida 2 ta harf yoki shtrix-kod raqamini yozing': 'Введите минимум 2 буквы или цифры штрих-кода',
  // ── Qator muharriri ──
  'Qatorni tahrirlash': 'Редактировать строку',
  'Topildi: {name}': 'Найдено: {name}',
  'Boshqa mahsulot': 'Другой товар',
  'Mahsulot arxivda — kirimdan keyin avtomatik faollashadi': 'Товар в архиве — после прихода станет активным автоматически',
  'Shu mahsulotni tanlash': 'Выбрать этот товар',
  '«{name}» nomli mahsulot bor va u partiya bo‘yicha kuzatiladi — uni ro‘yxatdan tanlang':
      'Товар «{name}» уже есть и учитывается по партиям — выберите его из списка',
  'Bu shtrix-kod band': 'Этот штрих-код занят',
  'Bu kod «{name}» mahsulotiga tegishli. Yangi mahsulotga biriktirib bo‘lmaydi.':
      'Этот код принадлежит товару «{name}». Привязать его к новому товару нельзя.',
  'Bu kod tarozi yorlig‘i sifatida mavjud mahsulotlarga mos keladi — boshqa kod bering.':
      'Этот код совпадает с весовой этикеткой существующих товаров — укажите другой код.',
  '6–14 raqam; skanerlash tavsiya etiladi': '6–14 цифр; лучше отсканировать',
  '1–5 raqam — tarozida shu kod bilan sotiladi': '1–5 цифр — на весах товар продаётся под этим кодом',
  'Litr': 'Литр',
  'Upak': 'Упак.',
  'Kelish narxi (birlik uchun)': 'Цена закупки (за единицу)',
  'Sotish narxi (ixtiyoriy)': 'Цена продажи (необязательно)',
  'Partiyali mahsulot uchun majburiy': 'Обязательно для партионного товара',
  'Qator summasi': 'Сумма строки',
  'O‘zgarishlar saqlanmaydi': 'Изменения не сохранятся',
  'Kiritilgan ma’lumotlar saqlanmaydi. Chiqasizmi?': 'Введённые данные не сохранятся. Выйти?',
  // ── Tekshiruv xabarlari ──
  'Shtrix-kod 6–14 raqamdan iborat bo‘lsin': 'Штрих-код должен содержать 6–14 цифр',
  'Partiyali mahsulot uchun kelish narxi noldan katta bo‘lsin':
      'Для партионного товара цена закупки должна быть больше нуля',
  'Partiyalarni kiriting': 'Укажите партии',
  'Avval qator miqdorini kiriting': 'Сначала укажите количество строки',
  'Har partiyaning miqdorini kiriting': 'Укажите количество каждой партии',
  'Partiyalar yig‘indisi qator miqdoridan {n} kam': 'Сумма партий меньше количества строки на {n}',
  'Partiyalar yig‘indisi qator miqdoridan {n} ortiq': 'Сумма партий больше количества строки на {n}',
  'Har partiyaga yaroqlilik muddatini kiriting': 'Укажите срок годности для каждой партии',
  'Muddati o‘tgan partiya qabul qilinmaydi': 'Партия с истёкшим сроком не принимается',
  // ── Saqlash oynasi ──
  'To‘lov turini tanlang': 'Выберите способ оплаты',
  '{supplier} · {n} ta mahsulot': '{supplier} · товаров: {n}',
  'Jami summa': 'Итого',
  'Qayta yuborish xavfsiz — bir kirim ikki marta yozilmaydi.':
      'Повторная отправка безопасна — приход не запишется дважды.',
  // ── Natija ──
  'Bu kirim avval saqlangan': 'Этот приход уже был сохранён',
  'Server bu hujjatni oldingi urinishda qabul qilgan (javobi sizga yetib kelmagan edi). Bu safargi yuborish qayta yozilmadi — ombor ikki marta o‘zgarmadi.':
      'Сервер принял этот документ при предыдущей попытке (ответ до вас не дошёл). Эта отправка повторно не записана — склад не изменился дважды.',
  'Oldingi urinishdan keyin kiritilgan o‘zgarishlar QO‘LLANMADI. Saqlangan hujjatni ochib tekshiring; farq bo‘lsa, hujjatni tuzating.':
      'Изменения, внесённые после предыдущей попытки, НЕ ПРИМЕНЕНЫ. Откройте сохранённый документ и проверьте; если есть расхождения — оформите корректировку.',
  'Keyingi o‘zgarishlar qo‘llanmaydi — saqlangan hujjat oldingi urinishdagidek qoldi.':
      'Последующие изменения не применяются — сохранённый документ остался таким, как при предыдущей попытке.',
  'Saqlangan hujjatni ochish': 'Открыть сохранённый документ',
  'Hujjatni ochish': 'Открыть документ',
  // ── Hujjat tafsiloti ──
  'AI (nakladnoy surati)': 'ИИ (фото накладной)',
  'Qo‘lda': 'Вручную',
  'Manba': 'Источник',
  'Holati': 'Статус',
  'Bu kirim tuzatish orqali to‘liq bekor qilingan — xarid hujjati yopilgan.':
      'Этот приход полностью отменён корректировкой — документ закупки закрыт.',
  'Xarid hujjati (partiyalar, tuzatish)': 'Документ закупки (партии, корректировка)',
  // ── CH-16: tashqi AI ga rasm yuborishga rozilik ──
  'Rasm tashqi xizmatga yuboriladi': 'Фото будет отправлено внешнему сервису',
  'AI xizmati o‘zgardi': 'AI-сервис изменился',
  'tashqi AI xizmati': 'внешний AI-сервис',
  'Siz tanlagan nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.':
      'Выбранное фото накладной будет отправлено в {name} для распознавания текста.',
  'Nakladnoy surati endi {name} ga yuboriladi.':
      'Фото накладной теперь будет отправляться в {name}.',
  'Surat faqat o‘qish uchun yuboriladi va qabul tasdiqlangandan keyin saqlanmaydi. Joylashuv kabi qo‘shimcha ma’lumotlar yuborishdan oldin olib tashlanadi.':
      'Фото отправляется только для распознавания и не сохраняется после подтверждения приёмки. Дополнительные данные, такие как геолокация, удаляются перед отправкой.',
  'Rozi bo‘lmasangiz, qatorlarni qo‘lda kiritish mumkin.':
      'Если вы не согласны, строки можно ввести вручную.',
  'Qo‘lda kiritaman': 'Введу вручную',
  'Roziman, yuborilsin': 'Согласен, отправить',
  'Rasm yuborilmadi. Qatorlarni qo‘lda kiritishingiz mumkin.':
      'Фото не отправлено. Вы можете ввести строки вручную.',
  // ── CH-17A: rasm darvozasi xatolari (server matni, `errors.dart:serverText`) ──
  // Format nomi PREFIKS bo'lib keladi (`"HEIC/HEIF: ..."`) — `_translateKnown`
  // `": "` dan keyingi qismni tarjima qilib, prefiksni JOYIDA qoldiradi.
  'bu rasm turi qo‘llab-quvvatlanmaydi — JPEG yoki PNG rasm tanlang':
      'этот тип изображения не поддерживается — выберите JPEG или PNG',
  "bu rasm turi qo'llab-quvvatlanmaydi — JPEG yoki PNG rasm tanlang":
      'этот тип изображения не поддерживается — выберите JPEG или PNG',
  'Fayl turi aniqlanmadi — JPEG yoki PNG rasm tanlang':
      'Тип файла не определён — выберите изображение JPEG или PNG',
  'Rasm bo‘sh — qayta suratga oling': 'Фото пустое — сфотографируйте снова',
  "Rasm bo'sh — qayta suratga oling": 'Фото пустое — сфотографируйте снова',
  'Rasm ma’lumoti buzuq — qayta suratga oling': 'Данные фото повреждены — сфотографируйте снова',
  "Rasm ma'lumoti buzuq — qayta suratga oling": 'Данные фото повреждены — сфотографируйте снова',
  'Rasm sarlavhasi buzuq — qayta suratga oling':
      'Заголовок изображения повреждён — сфотографируйте снова',
  'Rasm juda kichik — nakladnoy o‘qilmaydi': 'Изображение слишком маленькое — накладную не прочитать',
  "Rasm juda kichik — nakladnoy o'qilmaydi": 'Изображение слишком маленькое — накладную не прочитать',
  'Rasm juda katta — kichikroq rasm yuboring': 'Изображение слишком большое — отправьте изображение меньше',
  'Rasm hajmi juda katta — kichikroq rasm yuboring': 'Размер файла слишком большой — отправьте изображение меньше',
  'Tushunarli': 'Понятно',
  // ── R6.8 P1: idempotentlik kafolatining DOIRASI aytiladi ──
  'SHU oynadan qayta yuborish xavfsiz — bir kirim ikki marta yozilmaydi. Oynani yopsangiz kalit yo‘qoladi.':
      'ИЗ ЭТОГО окна повторная отправка безопасна — один приход не запишется дважды. Если закроете окно, ключ будет потерян.',
};

/// M1 (qabul / kirim): qirg'izcha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> kyReceiving = {
  'AI shartlari o‘zgardi. Rasmni qayta tanlang va yangilangan rozilik shartlarini tekshiring.':
      'ЖИ шарттары өзгөрдү. Сүрөттү кайра тандап, жаңыртылган макулдук шарттарын текшериңиз.',
  'AI uchun rozilik kerak. Rasmni qayta tanlang va rozilikni tasdiqlang yoki qatorlarni qo‘lda kiriting.':
      'ЖИ үчүн макулдук керек. Сүрөттү кайра тандап, макулдукту ырастаңыз же саптарды кол менен киргизиңиз.',
  'Nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.':
      'Накладной сүрӀтү текстти окуу үчүн {name} га жӀнӀтүлӀт.',
  'Buni do‘kon egasi yoki administratori bir marta ruxsat berishi kerak.':
      'Буга дүкӀн ээси же администратор бир жолу уруксат бериши керек.',
  'Hozir qatorlarni qo‘lda kiritishingiz mumkin.':
      'Азыр саптарды кол менен киргизсеңиз болот.',
  // ── Qabul filiali ──
  'Bu tarozi yorlig‘i (og‘irlik kodlangan) — doimiy shtrix-kod qilib biriktirib bo‘lmaydi: har qadoqda kod boshqacha. Qadoqning o‘z EAN kodini skanerlang yoki mahsulotni kg birlikda PLU bilan kiriting.': 'Бул таразанын этикеткасы (кодго салмак жазылган) — аны туруктуу штрих-код кылып бекитүүгө болбойт: ар бир кутуда код башка. Кутунун өз EAN кодун сканерлеңиз же товарды кг менен PLU аркылуу киргизиңиз.',
  'Qabul filiali: {name}': 'Кабыл алуу филиалы: {name}',
  'Filial ma’lumoti yuklanmoqda…': 'Филиалдын маалыматы жүктөлүүдө…',
  'Qabul filiali aniqlanmadi — aloqani tekshirib, qayta urinib ko‘ring.':
      'Кабыл алуу филиалы аныкталган жок — байланышты текшерип, кайра аракет кылыңыз.',
  'Siz «{current}» filialini ko‘ryapsiz, lekin kirim faqat «{actor}» filialiga yoziladi. Kirim qilish uchun «{actor}» filialiga o‘ting.':
      'Сиз «{current}» филиалында турасыз, бирок кирим «{actor}» филиалына гана жазылат. Кирим кылуу үчүн «{actor}» филиалына өтүңүз.',
  '«{name}» filialiga o‘tish': '«{name}» филиалына өтүү',
  // ── Bosh ekran / tarix ──
  'Kirim qilish uchun ruxsatingiz yo‘q.': 'Кирим кылууга укугуңуз жок.',
  'Qabullar tarixini ko‘rish uchun ruxsat yo‘q.': 'Кабыл алуулардын тарыхын көрүүгө укук жок.',
  'Rasmni olib bo‘lmadi — kamera yoki galereyaga ruxsatni tekshiring.':
      'Сүрөттү алуу мүмкүн болгон жок — камерага же галереяга уруксатты текшериңиз.',
  '{n} ta mahsulot': '{n} товар',
  // ── Hujjat (qo'lda / AI) ──
  'DEMO rejim: server AI’siz ishlayapti — qatorlar rasmdan O‘QILMAGAN. Har qatorni nakladnoy bilan solishtiring.':
      'ДЕМО режим: сервер AI’сиз иштеп жатат — саптар сүрөттөн ОКУЛГАН ЖОК. Ар бир сапты накладной менен салыштырыңыз.',
  'Partiyali mahsulotlar ro‘yxati yuklanmadi — qayta urinib ko‘ring.':
      'Партиялуу товарлардын тизмеси жүктөлгөн жок — кайра аракет кылыңыз.',
  'Mahsulotlar tekshirilmoqda…': 'Товарлар текшерилүүдө…',
  'Ro‘yxat yuklanmadi — qayta urinish uchun bosing': 'Тизме жүктөлгөн жок — кайталоо үчүн басыңыз',
  'Omborga qo‘shish · tayyor {r}/{n}': 'Кампага кошуу · даяр {r}/{n}',
  '{n} ta mahsulot · jami': '{n} товар · жалпы',
  '{n} ta qatorda xato bor — tuzating': '{n} сапта ката бар — оңдоңуз',
  '«{name}» olib tashlandi': '«{name}» алынып салынды',
  'Kirim saqlanmadi': 'Кирим сакталган жок',
  'Hujjat saqlanmagan. Chiqsangiz kiritilgan qatorlar yo‘qoladi.':
      'Документ сакталган жок. Чыгып кетсеңиз, киргизилген саптар жоголот.',
  'Qolish': 'Калуу',
  'Nomsiz': 'Аталышы жок',
  'O‘chirish': 'Өчүрүү',
  'AI o‘qidi: {name}': 'AI окуду: {name}',
  'AI moslik {p}%': 'AI дал келүү {p}%',
  '{n} ta partiya': '{n} партия',
  'Partiya': 'Партия',
  'Partiya · muddat': 'Партия · мөөнөт',
  'Mahsulotni tanlang yoki yangi mahsulot yarating': 'Товарды тандаңыз же жаңы товар түзүңүз',
  'Kamida 2 ta harf yoki shtrix-kod raqamini yozing': 'Кеминде 2 тамга же штрих-коддун сандарын жазыңыз',
  // ── Qator muharriri ──
  'Qatorni tahrirlash': 'Сапты оңдоо',
  'Topildi: {name}': 'Табылды: {name}',
  'Boshqa mahsulot': 'Башка товар',
  'Mahsulot arxivda — kirimdan keyin avtomatik faollashadi': 'Товар архивде — киримден кийин автоматтык түрдө активдешет',
  'Shu mahsulotni tanlash': 'Ушул товарды тандоо',
  '«{name}» nomli mahsulot bor va u partiya bo‘yicha kuzatiladi — uni ro‘yxatdan tanlang':
      '«{name}» деген товар бар жана ал партия боюнча эсепке алынат — аны тизмеден тандаңыз',
  'Bu shtrix-kod band': 'Бул штрих-код бош эмес',
  'Bu kod «{name}» mahsulotiga tegishli. Yangi mahsulotga biriktirib bo‘lmaydi.':
      'Бул код «{name}» товарына таандык. Аны жаңы товарга байлаганга болбойт.',
  'Bu kod tarozi yorlig‘i sifatida mavjud mahsulotlarga mos keladi — boshqa kod bering.':
      'Бул код бар товарлардын тараза этикеткасына дал келет — башка код бериңиз.',
  '6–14 raqam; skanerlash tavsiya etiladi': '6–14 сан; сканерлөө сунушталат',
  '1–5 raqam — tarozida shu kod bilan sotiladi': '1–5 сан — таразада товар ушул код менен сатылат',
  'Litr': 'Литр',
  'Upak': 'Таңгак',
  'Kelish narxi (birlik uchun)': 'Алуу баасы (бирдик үчүн)',
  'Sotish narxi (ixtiyoriy)': 'Сатуу баасы (милдеттүү эмес)',
  'Partiyali mahsulot uchun majburiy': 'Партиялуу товар үчүн милдеттүү',
  'Qator summasi': 'Саптын суммасы',
  'O‘zgarishlar saqlanmaydi': 'Өзгөртүүлөр сакталбайт',
  'Kiritilgan ma’lumotlar saqlanmaydi. Chiqasizmi?': 'Киргизилген маалыматтар сакталбайт. Чыгасызбы?',
  // ── Tekshiruv xabarlari ──
  'Shtrix-kod 6–14 raqamdan iborat bo‘lsin': 'Штрих-код 6–14 сандан турушу керек',
  'Partiyali mahsulot uchun kelish narxi noldan katta bo‘lsin':
      'Партиялуу товар үчүн алуу баасы нөлдөн чоң болушу керек',
  'Partiyalarni kiriting': 'Партияларды киргизиңиз',
  'Avval qator miqdorini kiriting': 'Адегенде саптын санын киргизиңиз',
  'Har partiyaning miqdorini kiriting': 'Ар бир партиянын санын киргизиңиз',
  'Partiyalar yig‘indisi qator miqdoridan {n} kam': 'Партиялардын суммасы саптын санынан {n} аз',
  'Partiyalar yig‘indisi qator miqdoridan {n} ortiq': 'Партиялардын суммасы саптын санынан {n} ашык',
  'Har partiyaga yaroqlilik muddatini kiriting': 'Ар бир партияга жарамдуулук мөөнөтүн киргизиңиз',
  'Muddati o‘tgan partiya qabul qilinmaydi': 'Мөөнөтү өткөн партия кабыл алынбайт',
  // ── Saqlash oynasi ──
  'To‘lov turini tanlang': 'Төлөм түрүн тандаңыз',
  '{supplier} · {n} ta mahsulot': '{supplier} · {n} товар',
  'Jami summa': 'Жалпы сумма',
  'Qayta yuborish xavfsiz — bir kirim ikki marta yozilmaydi.':
      'Кайра жөнөтүү коопсуз — бир кирим эки жолу жазылбайт.',
  // ── Natija ──
  'Bu kirim avval saqlangan': 'Бул кирим мурун сакталган',
  'Server bu hujjatni oldingi urinishda qabul qilgan (javobi sizga yetib kelmagan edi). Bu safargi yuborish qayta yozilmadi — ombor ikki marta o‘zgarmadi.':
      'Сервер бул документти мурунку аракетте кабыл алган (жообу сизге жеткен эмес). Бул жолку жөнөтүү кайра жазылган жок — кампа эки жолу өзгөргөн жок.',
  'Oldingi urinishdan keyin kiritilgan o‘zgarishlar QO‘LLANMADI. Saqlangan hujjatni ochib tekshiring; farq bo‘lsa, hujjatni tuzating.':
      'Мурунку аракеттен кийин киргизилген өзгөртүүлөр КОЛДОНУЛГАН ЖОК. Сакталган документти ачып текшериңиз; айырма болсо, документке оңдоо киргизиңиз.',
  'Keyingi o‘zgarishlar qo‘llanmaydi — saqlangan hujjat oldingi urinishdagidek qoldi.':
      'Кийинки өзгөртүүлөр колдонулбайт — сакталган документ мурунку аракеттегидей калды.',
  'Saqlangan hujjatni ochish': 'Сакталган документти ачуу',
  'Hujjatni ochish': 'Документти ачуу',
  // ── Hujjat tafsiloti ──
  'AI (nakladnoy surati)': 'AI (накладной сүрөтү)',
  'Qo‘lda': 'Кол менен',
  'Manba': 'Булак',
  'Holati': 'Абалы',
  'Bu kirim tuzatish orqali to‘liq bekor qilingan — xarid hujjati yopilgan.':
      'Бул кирим оңдоо аркылуу толук жокко чыгарылган — сатып алуу документи жабылган.',
  'Xarid hujjati (partiyalar, tuzatish)': 'Сатып алуу документи (партиялар, оңдоо)',
  // ── CH-16: тышкы AI'га сүрөт жөнөтүүгө макулдук ──
  'Rasm tashqi xizmatga yuboriladi': 'Сүрөт тышкы кызматка жөнөтүлөт',
  'AI xizmati o‘zgardi': 'AI кызматы өзгөрдү',
  'tashqi AI xizmati': 'тышкы AI кызматы',
  'Siz tanlagan nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.':
      'Сиз тандаган накладной сүрөтү текстти окуу үчүн {name} га жөнөтүлөт.',
  'Nakladnoy surati endi {name} ga yuboriladi.':
      'Накладной сүрөтү мындан ары {name} га жөнөтүлөт.',
  'Surat faqat o‘qish uchun yuboriladi va qabul tasdiqlangandan keyin saqlanmaydi. Joylashuv kabi qo‘shimcha ma’lumotlar yuborishdan oldin olib tashlanadi.':
      'Сүрөт окуу үчүн гана жөнөтүлөт жана кирим тастыкталгандан кийин сакталбайт. Жайгашкан жер сыяктуу кошумча маалыматтар жөнөтүүдөн мурун өчүрүлөт.',
  'Rozi bo‘lmasangiz, qatorlarni qo‘lda kiritish mumkin.':
      'Макул болбосоңуз, саптарды кол менен киргизүүгө болот.',
  'Qo‘lda kiritaman': 'Кол менен киргизем',
  'Roziman, yuborilsin': 'Макулмун, жөнөтүлсүн',
  'Rasm yuborilmadi. Qatorlarni qo‘lda kiritishingiz mumkin.':
      'Сүрөт жөнөтүлгөн жок. Саптарды кол менен киргизсеңиз болот.',
  // ── CH-17A: сүрөт дарбазасынын каталары ──
  'bu rasm turi qo‘llab-quvvatlanmaydi — JPEG yoki PNG rasm tanlang':
      'бул сүрөт түрү колдоого алынбайт — JPEG же PNG сүрөт тандаңыз',
  "bu rasm turi qo'llab-quvvatlanmaydi — JPEG yoki PNG rasm tanlang":
      'бул сүрөт түрү колдоого алынбайт — JPEG же PNG сүрөт тандаңыз',
  'Fayl turi aniqlanmadi — JPEG yoki PNG rasm tanlang':
      'Файлдын түрү аныкталбады — JPEG же PNG сүрөт тандаңыз',
  'Rasm bo‘sh — qayta suratga oling': 'Сүрөт бош — кайра сүрөткө тартыңыз',
  "Rasm bo'sh — qayta suratga oling": 'Сүрөт бош — кайра сүрөткө тартыңыз',
  'Rasm ma’lumoti buzuq — qayta suratga oling': 'Сүрөт маалыматы бузук — кайра сүрөткө тартыңыз',
  "Rasm ma'lumoti buzuq — qayta suratga oling": 'Сүрөт маалыматы бузук — кайра сүрөткө тартыңыз',
  'Rasm sarlavhasi buzuq — qayta suratga oling': 'Сүрөт башы бузук — кайра сүрөткө тартыңыз',
  'Rasm juda kichik — nakladnoy o‘qilmaydi': 'Сүрөт өтө кичине — накладной окулбайт',
  "Rasm juda kichik — nakladnoy o'qilmaydi": 'Сүрөт өтө кичине — накладной окулбайт',
  'Rasm juda katta — kichikroq rasm yuboring': 'Сүрөт өтө чоң — кичирээк сүрөт жөнөтүңүз',
  'Rasm hajmi juda katta — kichikroq rasm yuboring': 'Сүрөт көлөмү өтө чоң — кичирээк сүрөт жөнөтүңүз',
  'Tushunarli': 'Түшүнүктүү',
  // ── R6.8 P1: idempotentlik kafolatining DOIRASI aytiladi ──
  'SHU oynadan qayta yuborish xavfsiz — bir kirim ikki marta yozilmaydi. Oynani yopsangiz kalit yo‘qoladi.':
      'УШУЛ терезеден кайра жөнөтүү коопсуз — бир кирим эки жолу жазылбайт. Терезени жапсаңыз ачкыч жоголот.',
};
