import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Yengil i18n: kalit = o'zbekcha matnning o'zi. uz -> matn o'zgarishsiz,
/// ru/ky -> lug'atdan (topilmasa uz'ga tushadi). Til almashganda butun app qayta quriladi.
class L {
  static String code = 'uz'; // uz | ru | ky
  static final ValueNotifier<int> version = ValueNotifier(0);

  static Future<void> load() async {
    try {
      final p = await SharedPreferences.getInstance();
      code = p.getString('savdoos_lang') ?? 'uz';
    } catch (_) {}
  }

  static Future<void> set(String c) async {
    code = c;
    version.value++;
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString('savdoos_lang', c);
    } catch (_) {}
  }

  static String get native => switch (code) { 'ru' => 'Русский', 'ky' => 'Кыргызча', 'uzc' => 'Ўзбекча', _ => 'O‘zbekcha' };
}

/// Tarjima: uz matn -> joriy tildagi matn.
String tr(String uz) {
  if (L.code == 'uz') return uz;
  if (L.code == 'uzc') return _toCyrillic(uz);
  final map = L.code == 'ru' ? _ru : _ky;
  return map[uz] ?? uz;
}

// O'zbek lotin -> kirill transliteratsiya (uzc). Akronim (QR/PIN/PLU...), {vars}, F-key,
// SavdoOS saqlanadi; so'z boshidagi e -> э. Barcha tr() matnlarini qamraydi.
const String _apo = "'ʻ‘’`";
const Map<String, String> _di = {
  'SH': 'Ш', 'Sh': 'Ш', 'sh': 'ш', 'CH': 'Ч', 'Ch': 'Ч', 'ch': 'ч',
  'YO': 'Ё', 'Yo': 'Ё', 'yo': 'ё', 'YU': 'Ю', 'Yu': 'Ю', 'yu': 'ю',
  'YA': 'Я', 'Ya': 'Я', 'ya': 'я', 'YE': 'Е', 'Ye': 'Е', 'ye': 'е',
  'TS': 'Ц', 'Ts': 'Ц', 'ts': 'ц',
};
const Map<String, String> _single = {
  'a': 'а', 'b': 'б', 'c': 'с', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г', 'h': 'ҳ',
  'i': 'и', 'j': 'ж', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п',
  'q': 'қ', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'v': 'в', 'w': 'в', 'x': 'х',
  'y': 'й', 'z': 'з',
  'A': 'А', 'B': 'Б', 'C': 'С', 'D': 'Д', 'E': 'Е', 'F': 'Ф', 'G': 'Г', 'H': 'Ҳ',
  'I': 'И', 'J': 'Ж', 'K': 'К', 'L': 'Л', 'M': 'М', 'N': 'Н', 'O': 'О', 'P': 'П',
  'Q': 'Қ', 'R': 'Р', 'S': 'С', 'T': 'Т', 'U': 'У', 'V': 'В', 'W': 'В', 'X': 'Х',
  'Y': 'Й', 'Z': 'З',
};
String _toCyrillic(String s) {
  final keep = RegExp(r'\{[^}]*\}|https?://\S+|\bF\d\b|\b(?:QR|PIN|PLU|POS|PDF|CSV|SMS|EAN|USB|XPAY|VAT|NDS|IMEI|ID|URL|SavdoOS)\b');
  final buf = StringBuffer();
  int last = 0;
  for (final m in keep.allMatches(s)) {
    buf.write(_seg(s.substring(last, m.start)));
    buf.write(m[0]);
    last = m.end;
  }
  buf.write(_seg(s.substring(last)));
  return buf.toString();
}

String _seg(String s) {
  s = s.replaceAllMapped(RegExp('O[$_apo]'), (_) => 'Ў').replaceAllMapped(RegExp('o[$_apo]'), (_) => 'ў');
  s = s.replaceAllMapped(RegExp('G[$_apo]'), (_) => 'Ғ').replaceAllMapped(RegExp('g[$_apo]'), (_) => 'ғ');
  _di.forEach((a, b) { s = s.replaceAll(a, b); });
  s = s.replaceAllMapped(RegExp(r'(^|[^0-9A-Za-zА-Яа-яЁёЎўҒғҲҳҚқ])E'), (m) => '${m[1]}Э');
  s = s.replaceAllMapped(RegExp(r'(^|[^0-9A-Za-zА-Яа-яЁёЎўҒғҲҳҚқ])e'), (m) => '${m[1]}э');
  final sb = StringBuffer();
  for (final ch in s.split('')) {
    sb.write(_single[ch] ?? ch);
  }
  return sb.toString();
}

const Map<String, String> _ru = {
  // Ilova qulfi (PIN + biometrik)
  'PIN kod o‘rnating': 'Установите PIN-код',
  'Ilovani ochish uchun 4 xonali kod': '4-значный код для входа',
  'PIN kodni tasdiqlang': 'Подтвердите PIN-код',
  'Xuddi shu 4 raqamni qayta kiriting': 'Введите те же 4 цифры ещё раз',
  'PIN kodlar mos kelmadi': 'PIN-коды не совпадают',
  'Biometrik kirish': 'Вход по биометрии',
  'Barmoq izi yoki Face ID bilan ham kirishni yoqasizmi?': 'Включить вход по отпечатку или Face ID?',
  'Keyinroq': 'Позже',
  'Yoqish': 'Включить',
  'Xush kelibsiz': 'Добро пожаловать',
  'PIN kodni kiriting': 'Введите PIN-код',
  'PIN kod noto‘g‘ri': 'Неверный PIN-код',
  'Ilovani ochish uchun tasdiqlang': 'Подтвердите для входа',
  'Biometrik': 'Биометрия',
  'Ilova qulfi': 'Блокировка приложения',
  'PIN kod': 'PIN-код',
  'O‘rnatilgan': 'Установлен',
  'O‘rnatilmagan': 'Не установлен',
  'Barmoq izi / Face ID': 'Отпечаток / Face ID',
  'Ochishda PIN so‘ralsin': 'Запрашивать PIN при открытии',
  // Umumiy
  'Bekor': 'Отмена', 'Saqlash': 'Сохранить', 'Qo‘shish': 'Добавить', 'Yopish': 'Закрыть',
  'Kirish': 'Войти', 'Chiqish': 'Выйти', 'Xato': 'Ошибка', 'Tayyor': 'Готово',
  'Barchasi': 'Все', 'Qidirish...': 'Поиск...', 'Topilmadi': 'Не найдено', 'Miqdor': 'Количество',
  'Saqlandi ✓': 'Сохранено ✓', 'so‘m': 'сом',
  // Nav
  'Bosh': 'Главная', 'Analitika': 'Аналитика', 'Amal': 'Действие', 'Ombor': 'Склад', 'Sozlama': 'Настройки',
  // Login
  'Hisobingizga kiring': 'Войдите в аккаунт', 'Telefon': 'Телефон', 'Parol': 'Пароль',
  'Telefon yoki parol noto‘g‘ri': 'Неверный телефон или пароль',
  // Bosh
  'Assalomu alaykum,': 'Здравствуйте,', 'Bugungi savdo': 'Продажи сегодня',
  'Yangi\nqabul': 'Новая\nприёмка', 'Sotuvlar': 'Продажи', 'Qarzdorlar': 'Должники',
  'Diqqat': 'Внимание', 'kam qolgan': 'мало на складе', 'tugagan': 'закончилось', 'muddati yaqin': 'скоро истекает',
  'So‘nggi sotuvlar': 'Последние продажи', 'Bugun sotuv yo‘q': 'Сегодня продаж нет',
  // Amal sheet
  'Yangi operatsiya': 'Новая операция',
  'Tovar qabul': 'Приёмка товара', 'Nakladnoyni skanerlash': 'Сканировать накладную',
  'Hisobdan chiqarish': 'Списание', 'Brak, muddati o‘tgan': 'Брак, просрочка',
  'Inventarizatsiya': 'Инвентаризация', 'Qoldiqni sanash': 'Пересчёт остатков',
  'Kassa kirim / chiqim': 'Касса приход / расход', 'Naqd pul harakati': 'Движение наличных',
  'Filiallararo transfer': 'Перемещение между филиалами', 'Do‘konlar orasida': 'Между магазинами',
  // Analitika
  'Bugun': 'Сегодня', 'Hafta': 'Неделя', 'Oy': 'Месяц',
  'Savdo': 'Выручка', 'Yalpi foyda': 'Валовая прибыль', 'Cheklar': 'Чеки', 'O‘rtacha chek': 'Средний чек',
  'yangi': 'новый', 'Savdo dinamikasi': 'Динамика продаж', 'To‘lov usullari': 'Способы оплаты',
  'Naqd': 'Наличные', 'Karta': 'Карта', 'Qarz': 'Долг', 'Qarz (to‘lanmagan)': 'Долг (не оплачен)',
  'Eng ko‘p sotilgan': 'Топ продаж', 'Kassirlar': 'Кассиры', 'chek': 'чек.',
  'Mijozlar qarzi': 'Долги клиентов', 'qarzdor': 'должн.', 'Umumiy qarz': 'Общий долг',
  'Bugun to‘landi': 'Оплачено сегодня', 'Bugun — soatlik savdo': 'Сегодня — по часам',
  'Kategoriyalar bo‘yicha savdo': 'Продажи по категориям', 'Qayta urinish': 'Повторить',
  'Mijozlar': 'Клиенты', 'Yetkazib beruvchilar': 'Поставщики', 'Batafsil · ABC': 'Подробно · ABC',
  // Ombor
  'Mahsulotlar': 'Товары', 'Ombor qiymati': 'Стоимость склада', 'Kam qolgan': 'Мало на складе',
  'Tugagan': 'Закончилось', 'Hammasi': 'Все', 'Muddati yaqin': 'Скоро истекает', 'Muddati o‘tgan': 'Просрочено',
  'Mahsulot qidirish...': 'Поиск товара...', 'Kam qoldi': 'Мало осталось',
  'Qoldiq': 'Остаток', 'Sotish narxi': 'Цена продажи', 'Tannarx': 'Себестоимость',
  'So‘nggi harakatlar': 'Последние движения', 'Harakat yo‘q': 'Нет движений',
  // Qabul
  'Tovar qabul qilish': 'Приёмка товара', 'Nakladnoyni suratga oling': 'Сфотографируйте накладную',
  'Mahsulot nomi va miqdorini avtomatik o‘qiymiz': 'Название и количество распознаются автоматически',
  'Suratga olish': 'Сфотографировать', 'Galereyadan tanlash': 'Выбрать из галереи',
  'So‘nggi qabullar': 'Последние приёмки', 'Hali qabul qilinmagan': 'Приёмок пока нет',
  'Hujjat o‘qilmoqda...': 'Читаем документ...', 'AI mahsulotlarni aniqlaydi': 'ИИ распознаёт товары',
  'Tekshirish': 'Проверка', 'Yetkazib beruvchi': 'Поставщик', 'mahsulot': 'товаров', 'birlik': 'единиц',
  'tekshirish': 'проверить', 'Diqqat talab qiladi': 'Требует внимания', 'Mahsulot topilmadi': 'Товар не найден',
  'AI o‘qidi:': 'ИИ прочитал:', 'Mahsulotni tanlang': 'Выберите товар',
  'yoki yangi mahsulot yaratish': 'или создать новый товар', 'Yangi mahsulot': 'Новый товар',
  'Nomi': 'Название', 'Kelish narxi': 'Цена закупки', 'yangi mahsulot': 'новый товар',
  'Omborga qo‘shilsinmi?': 'Добавить на склад?', 'Omborga qo‘shish': 'Добавить на склад',
  'Qo‘shilyapti...': 'Добавляем...', 'Tovar qanday olindi?': 'Как получен товар?',
  'Darrov to‘landi': 'Оплачено сразу', 'Qarzga': 'В долг',
  'Qo‘lda kirim': 'Приход вручную', 'Mahsulot qidiring yoki yangi nom yozing': 'Найдите товар или введите новое название',
  'Mahsulot qo‘shish': 'Добавить товар', 'To‘landi': 'Оплачено', 'Kirimni saqlash': 'Сохранить приход',
  'Kamida bitta mahsulot va miqdor kiriting': 'Введите хотя бы один товар и количество',
  'Qabul qilindi': 'Принято', 'Kategoriya (yangi mahsulot)': 'Категория (новый товар)', 'Kategoriyasiz': 'Без категории',
  'Tanlanmagan': 'Не выбрано', 'Yangi': 'Новый', 'Topildi': 'Найдено', 'OK': 'OK', 'Kod': 'Код',
  'Mahsulot nomi': 'Название товара', 'Kodni qo‘lda kiriting': 'Введите код вручную',
  'Shtrix-kodni skanerlang': 'Сканируйте штрих-код', 'Kodni ramka ichiga tuting': 'Наведите код в рамку',
  'Qo‘lda kiritish': 'Ввести вручную', 'Yangi kod — mahsulot nomini kiriting': 'Новый код — введите название товара',
  'Mahsulot nomini kiriting': 'Введите название товара', 'Miqdorni kiriting': 'Введите количество',
  'Shtrix-kodni skanerlash': 'Сканировать штрих-код', 'Qidirilmoqda…': 'Поиск…',
  'Yangi kod biriktiriladi': 'Новый код будет привязан', 'Qidiring yoki yangi nom yozing': 'Найдите или введите новое название',
  'Nechta keldi': 'Сколько пришло', 'Saqlash va ro‘yxatga qo‘shish': 'Сохранить и добавить в список',
  'Hali mahsulot qo‘shilmagan': 'Товары ещё не добавлены', 'Avval mahsulot qo‘shing': 'Сначала добавьте товар',
  'Tarozi': 'Весовой', 'Narxlar': 'Цены', 'Birlik foyda': 'Прибыль с единицы', 'Margin': 'Маржа',
  'Sotuv statistikasi': 'Статистика продаж', 'So‘nggi 30 kun': 'Последние 30 дней', 'So‘nggi 7 kun': 'Последние 7 дней',
  'Bu oy kirim': 'Приход за месяц', 'Bu oy chiqim': 'Расход за месяц', 'Oxirgi sotilgan': 'Последняя продажа',
  'Sotildi': 'Продано', 'Tushum': 'Выручка', 'Foyda': 'Прибыль', 'Qo‘shgan': 'Добавил',
  'Skanerlash': 'Сканировать', 'Bu kod bo‘yicha topilmadi': 'По этому коду не найдено',
  'Mavzu': 'Тема', 'Mavzu tanlang': 'Выберите тему',
  'Yetkazib beruvchiga qarz bo‘ldi': 'Долг поставщику',
  'Mahsulotlar omborga qo‘shildi': 'Товары добавлены на склад',
  'Yangi qabul qilish': 'Новая приёмка', 'Bosh sahifaga': 'На главную',
  'Qabul tafsiloti': 'Детали приёмки', 'Nakladnoy rasmi': 'Фото накладной',
  // Sotuvlar
  'So‘nggi sotuvlar ro‘yxati': 'Список продаж', 'Sotuvlar yo‘q': 'Продаж нет',
  'Oraliq': 'Промежуточный итог', 'Chegirma': 'Скидка', 'Jami': 'Итого', 'Qaytarish': 'Возврат',
  'dona': 'шт.',
  // CRM
  'Ism yoki telefon qidirish...': 'Поиск по имени или телефону...', 'Qarzdor': 'Должники',
  'Qarzni so‘ndirish': 'Погасить долг', 'joriy qarz': 'текущий долг', 'To‘lov summasi': 'Сумма оплаты',
  'To‘lovni tasdiqlash': 'Подтвердить оплату', 'Biz qarzmiz': 'Мы должны',
  'Yetkazib beruvchiga to‘lash': 'Оплата поставщику', 'Qarz yo‘q 👍': 'Долгов нет 👍',
  // Batafsil
  'Batafsil': 'Подробно', 'Qaytarish · bekor cheklar': 'Возвраты · отменённые чеки',
  'qaytarilgan': 'возвратов', 'summa': 'сумма', 'bekor chek': 'отменённых',
  'Tovarlar · ABC analiz': 'Товары · ABC-анализ', 'Bu klassda tovar yo‘q': 'В этом классе нет товаров',
  'ulush': 'доля',
  // Kassa
  'Kirim': 'Приход', 'Chiqim': 'Расход', 'Summa': 'Сумма', 'Xarajat turi': 'Тип расхода',
  'Ijara': 'Аренда', 'Kommunal': 'Коммунальные', 'Inkassatsiya': 'Инкассация', 'Boshqa': 'Прочее',
  'Izoh (ixtiyoriy)': 'Комментарий (необязательно)', 'Bugungi harakatlar': 'Операции за сегодня',
  'Bugun harakat yo‘q': 'Сегодня операций нет', 'Summani kiriting': 'Введите сумму',
  'Xarajat': 'Расход', 'Smena ochildi': 'Смена открыта',
  // Transfer
  'Qayerdan': 'Откуда', 'Qayerga': 'Куда', 'Tanlang': 'Выберите',
  'Mahsulot qo‘shilmagan': 'Товары не добавлены', 'Ko‘chirishni tasdiqlash': 'Подтвердить перемещение',
  'Ko‘chirildi ✓': 'Перемещено ✓',
  'Transfer uchun kamida 2 ta filial kerak.\nFilial qo‘shish — Manager ilovasida.':
      'Для перемещения нужно минимум 2 филиала.\nДобавить филиал — в приложении Manager.',
  // Sozlamalar
  'Sozlamalar': 'Настройки', 'Xavfsizlik': 'Безопасность', 'Bildirishnomalar': 'Уведомления',
  'Tarif': 'Тариф', 'Til': 'Язык', 'Server manzili': 'Адрес сервера', 'Hisobdan chiqish': 'Выйти из аккаунта',
  'Hisobdan chiqmoqchimisiz?': 'Выйти из аккаунта?', 'Til tanlang': 'Выберите язык',
  'Parol o‘zgartirish': 'Смена пароля', 'Joriy parol': 'Текущий пароль', 'Yangi parol': 'Новый пароль',
  'Yangi parol (takror)': 'Новый пароль (повтор)', 'Parollar mos emas': 'Пароли не совпадают',
  'Parol o‘zgartirildi ✓': 'Пароль изменён ✓', 'Administrator': 'Администратор',
  'Menejer': 'Менеджер', 'Omborchi': 'Кладовщик', 'Kassir': 'Кассир',
  // Qo'shimcha (ekran-agentlari topgan kalitlar)
  '+ Qo‘shish': '+ Добавить', 'Barcha': 'Все', 'Barchasi →': 'Все →', 'Ega': 'Владелец',
  'Bildirishnoma yo‘q 👍': 'Уведомлений нет 👍',
  'Hujjatdan mahsulot topilmadi. Aniqroq suratga oling.': 'Товары в документе не найдены. Сделайте фото чётче.',
  'Joriy': 'Текущий', 'Mahsulot': 'Товар', 'Mahsulot tanlang': 'Выберите товар',
  'Parollar mos keladi': 'Пароли совпадают', 'Qaytarish — tez orada': 'Возврат — скоро',
  'Sababi': 'Причина', 'Sanoq': 'Пересчёт', 'Sanoq (haqiqiy qoldiq)': 'Пересчёт (фактический остаток)',
  'Saqlanyapti...': 'Сохраняем...',
  'Tarifni o‘zgartirish uchun SavdoOS bilan bog‘laning': 'Для смены тарифа свяжитесь с SavdoOS',
  'Tizim': 'Система', 'Tovar': 'Товар', 'Yangi parol kamida 6 belgi': 'Новый пароль минимум 6 символов',
  'Jami xarid': 'Всего покупок', 'Tashriflar': 'Визиты', 'To‘lovlar': 'Платежи',
  'Xarid yo‘q': 'Покупок нет', 'Xaridlar tarixi': 'История покупок',
  'Naqd oqim': 'Движение наличных', 'Kassada naqd': 'Наличные в кассе', 'Naqd savdo': 'Наличные продажи',
  'Qarz qaytdi': 'Возврат долга', 'Qo‘shimcha': 'Дополнительно', 'Beruvchiga': 'Поставщику',
  'Oflayn — internet yo‘q': 'Офлайн — нет интернета',
  'Hisobotni yuklab olish': 'Скачать отчёт', 'Chiroyli hujjat': 'Красивый документ',
  'Jadval (CSV)': 'Таблица (CSV)', 'Matn — Telegram/WhatsApp': 'Текст — Telegram/WhatsApp',
  'Ulashish': 'Поделиться', 'Savdo hisoboti': 'Отчёт о продажах', 'Tayyorlandi': 'Подготовлено',
  'Ko‘rsatkich': 'Показатель',
};

const Map<String, String> _ky = {
  // Ilova qulfi (PIN + biometrik)
  'PIN kod o‘rnating': 'PIN код коюңуз',
  'Ilovani ochish uchun 4 xonali kod': 'Кирүү үчүн 4 орундуу код',
  'PIN kodni tasdiqlang': 'PIN кодду ырастаңыз',
  'Xuddi shu 4 raqamni qayta kiriting': 'Ошол эле 4 санды кайра киргизиңиз',
  'PIN kodlar mos kelmadi': 'PIN коддор дал келген жок',
  'Biometrik kirish': 'Биометрия менен кирүү',
  'Barmoq izi yoki Face ID bilan ham kirishni yoqasizmi?': 'Манжа изи же Face ID менен кирүүнү жандырасызбы?',
  'Keyinroq': 'Кийинчерээк',
  'Yoqish': 'Жандыруу',
  'Xush kelibsiz': 'Кош келиңиз',
  'PIN kodni kiriting': 'PIN кодду киргизиңиз',
  'PIN kod noto‘g‘ri': 'PIN код туура эмес',
  'Ilovani ochish uchun tasdiqlang': 'Кирүү үчүн ырастаңыз',
  'Biometrik': 'Биометрия',
  'Ilova qulfi': 'Колдонмо кулпусу',
  'PIN kod': 'PIN код',
  'O‘rnatilgan': 'Коюлган',
  'O‘rnatilmagan': 'Коюлган эмес',
  'Barmoq izi / Face ID': 'Манжа изи / Face ID',
  'Ochishda PIN so‘ralsin': 'Ачканда PIN суралсын',
  // Umumiy
  'Bekor': 'Жокко чыгаруу', 'Saqlash': 'Сактоо', 'Qo‘shish': 'Кошуу', 'Yopish': 'Жабуу',
  'Kirish': 'Кирүү', 'Chiqish': 'Чыгуу', 'Xato': 'Ката', 'Tayyor': 'Даяр',
  'Barchasi': 'Баары', 'Qidirish...': 'Издөө...', 'Topilmadi': 'Табылган жок', 'Miqdor': 'Саны',
  'Saqlandi ✓': 'Сакталды ✓', 'so‘m': 'сом',
  // Nav
  'Bosh': 'Башкы', 'Analitika': 'Аналитика', 'Amal': 'Аракет', 'Ombor': 'Кампа', 'Sozlama': 'Жөндөө',
  // Login
  'Hisobingizga kiring': 'Аккаунтуңузга кириңиз', 'Telefon': 'Телефон', 'Parol': 'Сырсөз',
  'Telefon yoki parol noto‘g‘ri': 'Телефон же сырсөз туура эмес',
  // Bosh
  'Assalomu alaykum,': 'Саламатсызбы,', 'Bugungi savdo': 'Бүгүнкү соода',
  'Yangi\nqabul': 'Жаңы\nкабыл алуу', 'Sotuvlar': 'Сатуулар', 'Qarzdorlar': 'Карыздарлар',
  'Diqqat': 'Көңүл буруңуз', 'kam qolgan': 'аз калды', 'tugagan': 'түгөндү', 'muddati yaqin': 'мөөнөтү жакын',
  'So‘nggi sotuvlar': 'Акыркы сатуулар', 'Bugun sotuv yo‘q': 'Бүгүн сатуу жок',
  // Amal sheet
  'Yangi operatsiya': 'Жаңы операция',
  'Tovar qabul': 'Товар кабыл алуу', 'Nakladnoyni skanerlash': 'Накладнойду сканерлөө',
  'Hisobdan chiqarish': 'Эсептен чыгаруу', 'Brak, muddati o‘tgan': 'Брак, мөөнөтү өткөн',
  'Inventarizatsiya': 'Инвентаризация', 'Qoldiqni sanash': 'Калдыкты саноо',
  'Kassa kirim / chiqim': 'Касса кириш / чыгыш', 'Naqd pul harakati': 'Накталай акча кыймылы',
  'Filiallararo transfer': 'Филиалдар аралык которуу', 'Do‘konlar orasida': 'Дүкөндөр ортосунда',
  // Analitika
  'Bugun': 'Бүгүн', 'Hafta': 'Апта', 'Oy': 'Ай',
  'Savdo': 'Соода', 'Yalpi foyda': 'Дүң киреше', 'Cheklar': 'Чектер', 'O‘rtacha chek': 'Орточо чек',
  'yangi': 'жаңы', 'Savdo dinamikasi': 'Соода динамикасы', 'To‘lov usullari': 'Төлөм ыкмалары',
  'Naqd': 'Накталай', 'Karta': 'Карта', 'Qarz': 'Карыз', 'Qarz (to‘lanmagan)': 'Карыз (төлөнбөгөн)',
  'Eng ko‘p sotilgan': 'Эң көп сатылган', 'Kassirlar': 'Кассирлер', 'chek': 'чек',
  'Mijozlar qarzi': 'Кардарлардын карызы', 'qarzdor': 'карыздар', 'Umumiy qarz': 'Жалпы карыз',
  'Bugun to‘landi': 'Бүгүн төлөндү', 'Bugun — soatlik savdo': 'Бүгүн — сааттык соода',
  'Kategoriyalar bo‘yicha savdo': 'Категориялар боюнча соода', 'Qayta urinish': 'Кайра аракет',
  'Mijozlar': 'Кардарлар', 'Yetkazib beruvchilar': 'Жеткирүүчүлөр', 'Batafsil · ABC': 'Кеңири · ABC',
  // Ombor
  'Mahsulotlar': 'Товарлар', 'Ombor qiymati': 'Кампа наркы', 'Kam qolgan': 'Аз калган',
  'Tugagan': 'Түгөнгөн', 'Hammasi': 'Баары', 'Muddati yaqin': 'Мөөнөтү жакын', 'Muddati o‘tgan': 'Мөөнөтү өткөн',
  'Mahsulot qidirish...': 'Товар издөө...', 'Kam qoldi': 'Аз калды',
  'Qoldiq': 'Калдык', 'Sotish narxi': 'Сатуу баасы', 'Tannarx': 'Өздүк нарк',
  'So‘nggi harakatlar': 'Акыркы кыймылдар', 'Harakat yo‘q': 'Кыймыл жок',
  // Qabul
  'Tovar qabul qilish': 'Товар кабыл алуу', 'Nakladnoyni suratga oling': 'Накладнойду сүрөткө тартыңыз',
  'Mahsulot nomi va miqdorini avtomatik o‘qiymiz': 'Аталышы жана саны автоматтык таанылат',
  'Suratga olish': 'Сүрөткө тартуу', 'Galereyadan tanlash': 'Галереядан тандоо',
  'So‘nggi qabullar': 'Акыркы кабыл алуулар', 'Hali qabul qilinmagan': 'Азырынча кабыл алуу жок',
  'Hujjat o‘qilmoqda...': 'Документ окулууда...', 'AI mahsulotlarni aniqlaydi': 'AI товарларды аныктайт',
  'Tekshirish': 'Текшерүү', 'Yetkazib beruvchi': 'Жеткирүүчү', 'mahsulot': 'товар', 'birlik': 'бирдик',
  'tekshirish': 'текшерүү', 'Diqqat talab qiladi': 'Көңүл талап кылат', 'Mahsulot topilmadi': 'Товар табылган жок',
  'AI o‘qidi:': 'AI окуду:', 'Mahsulotni tanlang': 'Товарды тандаңыз',
  'yoki yangi mahsulot yaratish': 'же жаңы товар түзүү', 'Yangi mahsulot': 'Жаңы товар',
  'Nomi': 'Аталышы', 'Kelish narxi': 'Алуу баасы', 'yangi mahsulot': 'жаңы товар',
  'Omborga qo‘shilsinmi?': 'Кампага кошулсунбу?', 'Omborga qo‘shish': 'Кампага кошуу',
  'Qo‘shilyapti...': 'Кошулууда...', 'Tovar qanday olindi?': 'Товар кандай алынды?',
  'Darrov to‘landi': 'Дароо төлөндү', 'Qarzga': 'Карызга',
  'Qo‘lda kirim': 'Кол менен кирим', 'Mahsulot qidiring yoki yangi nom yozing': 'Товар издеңиз же жаңы ат жазыңыз',
  'Mahsulot qo‘shish': 'Товар кошуу', 'To‘landi': 'Төлөндү', 'Kirimni saqlash': 'Киримди сактоо',
  'Kamida bitta mahsulot va miqdor kiriting': 'Эң аз бир товар жана санын киргизиңиз',
  'Qabul qilindi': 'Кабыл алынды', 'Kategoriya (yangi mahsulot)': 'Категория (жаңы товар)', 'Kategoriyasiz': 'Категориясыз',
  'Tanlanmagan': 'Тандалган жок', 'Yangi': 'Жаңы', 'Topildi': 'Табылды', 'OK': 'OK', 'Kod': 'Код',
  'Mahsulot nomi': 'Товардын аты', 'Kodni qo‘lda kiriting': 'Кодду кол менен киргизиңиз',
  'Shtrix-kodni skanerlang': 'Штрих-кодду скандаңыз', 'Kodni ramka ichiga tuting': 'Кодду рамкага караткыла',
  'Qo‘lda kiritish': 'Кол менен киргизүү', 'Yangi kod — mahsulot nomini kiriting': 'Жаңы код — товардын атын киргизиңиз',
  'Mahsulot nomini kiriting': 'Товардын атын киргизиңиз', 'Miqdorni kiriting': 'Санын киргизиңиз',
  'Shtrix-kodni skanerlash': 'Штрих-кодду скандоо', 'Qidirilmoqda…': 'Изделүүдө…',
  'Yangi kod biriktiriladi': 'Жаңы код байланат', 'Qidiring yoki yangi nom yozing': 'Издеңиз же жаңы ат жазыңыз',
  'Nechta keldi': 'Канча келди', 'Saqlash va ro‘yxatga qo‘shish': 'Сактап тизмеге кошуу',
  'Hali mahsulot qo‘shilmagan': 'Товарлар кошула элек', 'Avval mahsulot qo‘shing': 'Адегенде товар кошуңуз',
  'Tarozi': 'Тартылма', 'Narxlar': 'Баалар', 'Birlik foyda': 'Бирдиктен пайда', 'Margin': 'Маржа',
  'Sotuv statistikasi': 'Сатуу статистикасы', 'So‘nggi 30 kun': 'Акыркы 30 күн', 'So‘nggi 7 kun': 'Акыркы 7 күн',
  'Bu oy kirim': 'Бул айда кирим', 'Bu oy chiqim': 'Бул айда чыгым', 'Oxirgi sotilgan': 'Акыркы сатуу',
  'Sotildi': 'Сатылды', 'Tushum': 'Түшүм', 'Foyda': 'Пайда', 'Qo‘shgan': 'Кошкон',
  'Skanerlash': 'Скандоо', 'Bu kod bo‘yicha topilmadi': 'Бул код боюнча табылган жок',
  'Mavzu': 'Тема', 'Mavzu tanlang': 'Теманы тандаңыз',
  'Yetkazib beruvchiga qarz bo‘ldi': 'Жеткирүүчүгө карыз болду',
  'Mahsulotlar omborga qo‘shildi': 'Товарлар кампага кошулду',
  'Yangi qabul qilish': 'Жаңы кабыл алуу', 'Bosh sahifaga': 'Башкы бетке',
  'Qabul tafsiloti': 'Кабыл алуу чоо-жайы', 'Nakladnoy rasmi': 'Накладной сүрөтү',
  // Sotuvlar
  'So‘nggi sotuvlar ro‘yxati': 'Сатуулар тизмеси', 'Sotuvlar yo‘q': 'Сатуу жок',
  'Oraliq': 'Аралык', 'Chegirma': 'Арзандатуу', 'Jami': 'Жалпы', 'Qaytarish': 'Кайтаруу',
  'dona': 'даана',
  // CRM
  'Ism yoki telefon qidirish...': 'Аты же телефон боюнча издөө...', 'Qarzdor': 'Карыздар',
  'Qarzni so‘ndirish': 'Карызды жабуу', 'joriy qarz': 'учурдагы карыз', 'To‘lov summasi': 'Төлөм суммасы',
  'To‘lovni tasdiqlash': 'Төлөмдү ырастоо', 'Biz qarzmiz': 'Биз карызбыз',
  'Yetkazib beruvchiga to‘lash': 'Жеткирүүчүгө төлөө', 'Qarz yo‘q 👍': 'Карыз жок 👍',
  // Batafsil
  'Batafsil': 'Кеңири', 'Qaytarish · bekor cheklar': 'Кайтаруу · жокко чыгарылган чектер',
  'qaytarilgan': 'кайтарылган', 'summa': 'сумма', 'bekor chek': 'жокко чыгарылган',
  'Tovarlar · ABC analiz': 'Товарлар · ABC анализ', 'Bu klassda tovar yo‘q': 'Бул класста товар жок',
  'ulush': 'үлүш',
  // Kassa
  'Kirim': 'Кириш', 'Chiqim': 'Чыгыш', 'Summa': 'Сумма', 'Xarajat turi': 'Чыгым түрү',
  'Ijara': 'Ижара', 'Kommunal': 'Коммуналдык', 'Inkassatsiya': 'Инкассация', 'Boshqa': 'Башка',
  'Izoh (ixtiyoriy)': 'Комментарий (милдеттүү эмес)', 'Bugungi harakatlar': 'Бүгүнкү операциялар',
  'Bugun harakat yo‘q': 'Бүгүн операция жок', 'Summani kiriting': 'Сумманы киргизиңиз',
  'Xarajat': 'Чыгым', 'Smena ochildi': 'Смена ачылды',
  // Transfer
  'Qayerdan': 'Кайдан', 'Qayerga': 'Кайда', 'Tanlang': 'Тандаңыз',
  'Mahsulot qo‘shilmagan': 'Товар кошулган жок', 'Ko‘chirishni tasdiqlash': 'Которууну ырастоо',
  'Ko‘chirildi ✓': 'Которулду ✓',
  'Transfer uchun kamida 2 ta filial kerak.\nFilial qo‘shish — Manager ilovasida.':
      'Которуу үчүн кеминде 2 филиал керек.\nФилиал кошуу — Manager колдонмосунда.',
  // Sozlamalar
  'Sozlamalar': 'Жөндөөлөр', 'Xavfsizlik': 'Коопсуздук', 'Bildirishnomalar': 'Билдирмелер',
  'Tarif': 'Тариф', 'Til': 'Тил', 'Server manzili': 'Сервер дареги', 'Hisobdan chiqish': 'Аккаунттан чыгуу',
  'Hisobdan chiqmoqchimisiz?': 'Аккаунттан чыгасызбы?', 'Til tanlang': 'Тил тандаңыз',
  'Parol o‘zgartirish': 'Сырсөздү өзгөртүү', 'Joriy parol': 'Учурдагы сырсөз', 'Yangi parol': 'Жаңы сырсөз',
  'Yangi parol (takror)': 'Жаңы сырсөз (кайталоо)', 'Parollar mos emas': 'Сырсөздөр дал келбейт',
  'Parol o‘zgartirildi ✓': 'Сырсөз өзгөртүлдү ✓', 'Administrator': 'Администратор',
  'Menejer': 'Менеджер', 'Omborchi': 'Кампачы', 'Kassir': 'Кассир',
  // Qo'shimcha (ekran-agentlari topgan kalitlar)
  '+ Qo‘shish': '+ Кошуу', 'Barcha': 'Баары', 'Barchasi →': 'Баары →', 'Ega': 'Ээси',
  'Bildirishnoma yo‘q 👍': 'Билдирме жок 👍',
  'Hujjatdan mahsulot topilmadi. Aniqroq suratga oling.': 'Документтен товар табылган жок. Тагыраак сүрөткө тартыңыз.',
  'Joriy': 'Учурдагы', 'Mahsulot': 'Товар', 'Mahsulot tanlang': 'Товарды тандаңыз',
  'Parollar mos keladi': 'Сырсөздөр дал келет', 'Qaytarish — tez orada': 'Кайтаруу — жакында',
  'Sababi': 'Себеби', 'Sanoq': 'Саноо', 'Sanoq (haqiqiy qoldiq)': 'Саноо (чыныгы калдык)',
  'Saqlanyapti...': 'Сакталууда...',
  'Tarifni o‘zgartirish uchun SavdoOS bilan bog‘laning': 'Тарифти өзгөртүү үчүн SavdoOS менен байланышыңыз',
  'Tizim': 'Система', 'Tovar': 'Товар', 'Yangi parol kamida 6 belgi': 'Жаңы сырсөз кеминде 6 белги',
  'Jami xarid': 'Жалпы сатып алуу', 'Tashriflar': 'Келүүлөр', 'To‘lovlar': 'Төлөмдөр',
  'Xarid yo‘q': 'Сатып алуу жок', 'Xaridlar tarixi': 'Сатып алуу тарыхы',
  'Naqd oqim': 'Накталай кыймылы', 'Kassada naqd': 'Кассадагы накталай', 'Naqd savdo': 'Накталай сатуу',
  'Qarz qaytdi': 'Карыз кайтты', 'Qo‘shimcha': 'Кошумча', 'Beruvchiga': 'Жеткирүүчүгө',
  'Oflayn — internet yo‘q': 'Оффлайн — интернет жок',
  'Hisobotni yuklab olish': 'Отчётту жүктөө', 'Chiroyli hujjat': 'Кооз документ',
  'Jadval (CSV)': 'Таблица (CSV)', 'Matn — Telegram/WhatsApp': 'Текст — Telegram/WhatsApp',
  'Ulashish': 'Бөлүшүү', 'Savdo hisoboti': 'Сатуу отчёту', 'Tayyorlandi': 'Даярдалды',
  'Ko‘rsatkich': 'Көрсөткүч',
};
