// Paket M4 (mijozlar, yetkazib beruvchilar, kassa, sotuvlar) tarjimalari.
//
// SHAKL (yadro bilan kelishilgan, o'zgartirmang):
//   * kalit — `tr('...')` ga beriladigan O'ZBEK LOTIN manba matni (aynan o'sha satr);
//   * `ruMoney` — ruscha, `kyMoney` — qirg'izcha tarjima; uzc (kirill) avtomatik;
//   * har kalit IKKALA xaritada bo'lishi SHART, boshqa manbadagi ayni kalit bilan
//     tarjima bir xil bo'lsin — `test/core_l10n_test.dart` ikkalasini tekshiradi;
//   * o'rinbosar `{nom}` shaklida (`trArgs`), transliteratsiyada saqlanadi.
//
// `lib/l10n.dart` bu xaritalarni birlashtiradi — l10n.dart ga TEGMANG.
//
// Umumiy so'zlar (Naqd, Karta, Qarz, Kirim, Xarajat, Inkassatsiya, Filial, Kassa,
// Kassir, Chegirma, Jami, Summa, Saqlash, Yopish, Ijara, Kommunal, Boshqa, ...)
// asosiy/yadro lug'atidan olinadi — bu yerda TAKRORLANMAYDI.
// Chek yorliqlari desktop `packages/shared/src/receipt/labels.ts` bilan bir xil.
// `test/money_l10n_test.dart` har M4 `tr()` matni tarjima qilinganini tekshiradi.

/// M4 (mijozlar, yetkazib beruvchilar, kassa, sotuvlar): ruscha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> ruMoney = {
  // ── To'lov usullari, hujjat holatlari ──
  'Nasiya': 'В долг',
  'Qabul qilingan': 'Принят',
  'To‘langan': 'Оплачено',
  'Qisman to‘langan': 'Частично оплачен',
  'Qoralama': 'Черновик',
  'Bekor qilingan': 'Отменён',
  'Yakunlangan': 'Завершён',
  'Qaytarilgan': 'Возвращён',
  'Qisman qaytarilgan': 'Частично возвращён',
  // ── Ta'minotchi hisob-kitobi ──
  'To‘lov': 'Оплата',
  'Xarid': 'Закупка',
  'Xarid tahriri': 'Изменение закупки',
  'Qabul tuzatildi': 'Исправление приёмки',
  'Qarz kamaydi': 'Долг уменьшен',
  'Qarz oshdi': 'Долг увеличен',
  'Naqd chiqim': 'Выдача наличных',
  // ── Umumiy ──
  'Bu bo‘limni ko‘rish uchun ruxsatingiz yo‘q.': 'У вас нет доступа к этому разделу.',
  'Hech narsa topilmadi': 'Ничего не найдено',
  'Tahrirlash': 'Редактировать',
  'Telefon (ixtiyoriy)': 'Телефон (необязательно)',
  'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456': 'Неверный номер телефона. Например: +996 700 123 456',
  'O‘zgarish yo‘q': 'Нет изменений',
  'Qayta saqlash': 'Сохранить повторно',
  'Server javobi kelmadi — o‘zgarish saqlangan-saqlanmagani noma’lum. Qayta saqlash xavfsiz.':
      'Ответ сервера не получен — неизвестно, сохранено ли изменение. Сохранить повторно безопасно.',
  'Qayta yuborish': 'Отправить повторно',
  // ── To'lov oynasi ──
  'To‘lov qarzdan oshmasin (ko‘pi bilan {max})': 'Оплата не может превышать долг (не более {max})',
  'Pul manbai tekshirilmoqda…': 'Проверяем источник денег…',
  'Pul manbaini aniqlab bo‘lmadi — qayta urinib ko‘ring.': 'Не удалось определить источник денег — попробуйте ещё раз.',
  'Butun so‘mda. Qarzdan ortig‘i qabul qilinmaydi.': 'Целыми сомами. Сумма сверх долга не принимается.',
  'To‘lov usuli': 'Способ оплаты',
  'Server javobi kelmadi — to‘lov yozilgan-yozilmagani noma’lum. «Qayta yuborish» xavfsiz: to‘lov ikki marta yozilmaydi.':
      'Ответ сервера не получен — неизвестно, записана ли оплата. «Отправить повторно» безопасно: оплата не запишется дважды.',
  'Oldingi urinish natijasi noma’lum — to‘lov yozilgan bo‘lishi mumkin. Shuning uchun forma bloklangan: AYNAN shu to‘lovni qayta yuboring yoki «Yopish» bilan chiqing.':
      'Результат предыдущей попытки неизвестен — оплата могла быть записана. Поэтому форма заблокирована: отправьте ИМЕННО эту оплату повторно или выйдите через «Закрыть».',
  // ── Mijozlar ──
  'Yangi mijoz': 'Новый клиент',
  'Ism yoki telefon bo‘yicha qidirish': 'Поиск по имени или телефону',
  'Qarzdor mijozlar yo‘q': 'Должников нет',
  'Hozircha mijoz yo‘q': 'Клиентов пока нет',
  '{n} ta qarzdor': 'Должников: {n}',
  'Avans': 'Аванс',
  'Mijoz ma’lumotlari saqlandi': 'Данные клиента сохранены',
  'To‘lov qabul qilindi. Qolgan qarz: {left}': 'Оплата принята. Остаток долга: {left}',
  'To‘landi: {paid}. Qolgan qarz: {left}': 'Оплачено: {paid}. Остаток долга: {left}',
  'Diqqat: siz {asked} kiritdingiz, lekin serverga {paid} yozildi. Qolgan qarz: {left}':
      'Внимание: вы ввели {asked}, но на сервере записано {paid}. Остаток долга: {left}',
  'Server javobi kelmadi — to‘lov yozilgan bo‘lishi mumkin. Quyidagi ro‘yxatni tekshiring.':
      'Ответ сервера не получен — оплата могла быть записана. Проверьте список ниже.',
  'Avans (do‘kon mijozga qarzdor)': 'Аванс (магазин должен клиенту)',
  'So‘nggi xaridlar': 'Последние покупки',
  'Qarz to‘lovlari': 'Погашения долга',
  'To‘lov yo‘q': 'Оплат нет',
  '{n} ta tovar': 'Товаров: {n}',
  'Miqdor: {q}': 'Количество: {q}',
  'Ismni kiriting': 'Введите имя',
  'Mijozni tahrirlash': 'Редактирование клиента',
  'Manzil (ixtiyoriy)': 'Адрес (необязательно)',
  'Server javobi kelmadi — mijoz yaratilgan-yaratilmagani noma’lum. Qayta saqlash xavfsiz: mijoz ikki marta yaratilmaydi.':
      'Ответ сервера не получен — неизвестно, создан ли клиент. Сохранить повторно безопасно: клиент не будет создан дважды.',
  // ── Yetkazib beruvchilar ──
  'Yangi yetkazib beruvchi': 'Новый поставщик',
  'Hozircha yetkazib beruvchi yo‘q': 'Поставщиков пока нет',
  '{n} ta yetkazib beruvchiga': 'поставщикам: {n}',
  'Nomi yoki telefon bo‘yicha qidirish': 'Поиск по названию или телефону',
  'Qarzimiz bor': 'Мы должны',
  'Hech kimga qarzimiz yo‘q': 'Мы никому не должны',
  'Yetkazib beruvchini tahrirlash': 'Редактирование поставщика',
  'Nomini kiriting': 'Введите название',
  'Server javobi kelmadi — yetkazib beruvchi yaratilgan bo‘lishi mumkin. Takror yaratmaslik uchun avval ro‘yxatni yangilab tekshiring.':
      'Ответ сервера не получен — поставщик мог быть создан. Чтобы не создать дубликат, сначала обновите и проверьте список.',
  'Avval ro‘yxatni tekshiring': 'Сначала проверьте список',
  'Yetkazib beruvchi ma’lumotlari saqlandi': 'Данные поставщика сохранены',
  'Bu to‘lov avval saqlangan edi — qayta yozilmadi.': 'Эта оплата уже была сохранена ранее — повторно не записана.',
  'To‘landi: {paid}. Qolgan qarzimiz: {left}': 'Оплачено: {paid}. Наш остаток долга: {left}',
  'To‘lash': 'Оплатить',
  'Yetkazib beruvchi bizga qarzdor': 'Поставщик должен нам',
  'Oxirgi xarid': 'Последняя закупка',
  'Mahsulot turlari': 'Видов товара',
  'Kutilayotgan foyda': 'Ожидаемая прибыль',
  'Hisob-kitob': 'Взаиморасчёты',
  'Hisob-kitob yozuvlari yo‘q': 'Записей взаиморасчётов нет',
  'Qoldiq: {sum}': 'Остаток: {sum}',
  'Mahsulot yo‘q': 'Товаров нет',
  'Miqdor: {qty}': 'Количество: {qty}',
  // ── Kassa kirim / chiqim ──
  'Maosh': 'Зарплата',
  'Kassa holatini aniqlab bo‘lmadi — qayta urinib ko‘ring.': 'Не удалось определить состояние кассы — попробуйте ещё раз.',
  // ── To'lov varag'i: yo'ldagi/muzlagan yozuv ──
  'So‘rov serverga yuborildi — javob kutilmoqda. Javob kelguncha bu oyna yopilmaydi.':
      'Запрос отправлен на сервер — ждём ответа. Пока ответ не придёт, это окно не закроется.',
  'Javob kelmaguncha chiqib bo‘lmaydi: to‘lov serverda yozilayotgan bo‘lishi mumkin.':
      'Выйти нельзя, пока нет ответа: платёж может записываться на сервере прямо сейчас.',
  'Chiqish uchun «Yopish» tugmasini bosing — natija noma’lumligi aytiladi va qarz qoldig‘i serverdan qayta o‘qiladi.':
      'Чтобы выйти, нажмите «Закрыть» — вам сообщат, что результат неизвестен, а остаток долга перечитается с сервера.',
  'Kassa holati tekshirilmoqda…': 'Проверяем состояние кассы…',
  'Ochiq smena yo‘q — kassa amallari faqat ochiq smenaga yoziladi.':
      'Нет открытой смены — кассовые операции записываются только в открытую смену.',
  'Inkassatsiyani tasdiqlang': 'Подтвердите инкассацию',
  'Xarajatni tasdiqlang': 'Подтвердите расход',
  'Kassadan {sum} chiqariladi.': 'Из кассы будет выдано {sum}.',
  'Smena filiali: {name}': 'Филиал смены: {name}',
  'Qabul qiluvchi seyf: {code}': 'Сейф-получатель: {code}',
  'Izoh: {text}': 'Комментарий: {text}',
  'Chiqarish': 'Выдать',
  'Bu amal avval saqlangan edi — qayta yozilmadi.': 'Эта операция уже была сохранена ранее — повторно не записана.',
  'Saqlandi: {type} {sum}': 'Сохранено: {type} {sum}',
  'Qabul qiluvchi seyf': 'Сейф-получатель',
  'Server javobi kelmadi — amal yozilgan-yozilmagani noma’lum. «Qayta yuborish» xavfsiz: amal ikki marta yozilmaydi.':
      'Ответ сервера не получен — неизвестно, записана ли операция. «Отправить повторно» безопасно: операция не запишется дважды.',
  'Oldingi urinish natijasi noma’lum — amal yozilgan bo‘lishi mumkin. Shuning uchun forma bloklangan: AYNAN shu amalni qayta yuboring yoki «Bekor qilish» bilan yangi amal boshlang.':
      'Результат предыдущей попытки неизвестен — операция могла быть записана. Поэтому форма заблокирована: отправьте ИМЕННО эту операцию повторно или начните новую через «Отмена».',
  'Kassa amali serverda yozilgan bo‘lishi mumkin. Bekor qilsangiz, «Qayta yuborish» kaliti o‘chadi — o‘sha summani qayta kiritsangiz, amal IKKI MARTA yozilishi mumkin. Avval «Bugungi harakatlar» ro‘yxatini tekshiring.':
      'Кассовая операция могла быть записана на сервере. Если отменить, ключ «Отправить повторно» пропадёт — при повторном вводе той же суммы операция может записаться ДВАЖДЫ. Сначала проверьте список «Движения за сегодня».',
  'Baribir bekor qilish': 'Всё равно отменить',
  'Kassa amali serverda yozilgan bo‘lishi mumkin. Chiqsangiz, «Qayta yuborish» tugmasi yo‘qoladi — «Bugungi harakatlar» ro‘yxatidan tekshiring.':
      'Кассовая операция могла быть записана на сервере. Если выйти, кнопка «Отправить повторно» исчезнет — проверьте в списке «Движения за сегодня».',
  'So‘rov yuborildi': 'Запрос отправлен',
  'Kassa amali serverga yuborildi, javob hali kelmadi. Hozir chiqsangiz, javob yo‘qoladi — amal yozilgan bo‘lishi mumkin va «Qayta yuborish» kaliti ham o‘chadi.':
      'Кассовая операция отправлена на сервер, ответ ещё не получен. Если выйти сейчас, ответ будет потерян — операция могла быть записана, а ключ «Отправить повторно» пропадёт.',
  'Ochiq smena yo‘q. Kassa kirim/chiqimi faqat filialning ochiq smenasiga yoziladi — avval POS’da smena oching, keyin qayta tekshiring.':
      'Нет открытой смены. Приход и расход кассы записываются только в открытую смену филиала — откройте смену на POS, затем проверьте ещё раз.',
  'Ochiq smenaga yoziladi': 'Записывается в открытую смену',
  'Ochiq smenaga yoziladi: {branch}': 'Записывается в открытую смену: {branch}',
  'Diqqat: siz «{current}» filialini ko‘ryapsiz, lekin kassa amali sizning filialingiz smenasiga yoziladi.':
      'Внимание: вы просматриваете филиал «{current}», но кассовая операция запишется в смену вашего филиала.',
  // ── Sotuvlar ──
  'Chek raqami bo‘yicha qidirish': 'Поиск по номеру чека',
  '7 kun': '7 дней',
  'Shu oy': 'Этот месяц',
  'Bu raqamli chek topilmadi': 'Чек с таким номером не найден',
  'Bugun hali sotuv yo‘q': 'Сегодня продаж ещё нет',
  'Bu davrda sotuv yo‘q': 'За этот период продаж нет',
  '{n} ta chek': 'Чеков: {n}',
  'Ko‘proq ko‘rsatish': 'Показать больше',
  'Sotuv': 'Продажа',
  'Chekni ko‘rish': 'Посмотреть чек',
  'Holati: {status}': 'Статус: {status}',
  'Terminal': 'Терминал',
  'Vaqt': 'Время',
  'Tovarlar ({n})': 'Товары ({n})',
  'Qatorlar saqlanmagan (tarixiy sotuv)': 'Строки не сохранены (историческая продажа)',
  'Ulashib bo‘lmadi': 'Не удалось поделиться',
  'Bu — serverdagi chek nusxasi. Mobil ilovadan chop etilmaydi.':
      'Это копия чека с сервера. Мобильное приложение не печатает чеки.',
  // ── Chek (desktop receipt/labels.ts bilan bir xil) ──
  'Chek': 'Чек',
  'STIR': 'ИНН',
  'Xaridor': 'Покупатель',
  'Oraliq jami': 'Подытог',
  'Chek chegirmasi': 'Скидка на чек',
  'Yaxlitlash': 'Округление',
  'Berildi': 'Внесено',
  'Qaytim': 'Сдача',
  'BEKOR QILINGAN CHEK': 'ЧЕК АННУЛИРОВАН',
  'QAYTARISH CHEKI': 'ЧЕК ВОЗВРАТА',
  'Asl chek': 'Исходный чек',
  'QAYTARISH JAMI': 'ИТОГО ВОЗВРАТ',
  'JAMI': 'ИТОГО',
  'Qaytarildi': 'Возвращено',
  'Xaridingiz uchun rahmat!': 'Спасибо за покупку!',
  // Javobsiz urinishdan keyingi muzlashni ochish (tasdiq bilan).
  'Ro‘yxatni tekshirdingizmi?': 'Вы проверили список?',
  'Avvalgi urinish serverda saqlangan bo‘lishi mumkin. Agar mijoz ro‘yxatda bo‘lsa, qaytadan saqlash uni IKKI MARTA yaratadi.':
      'Предыдущая попытка могла сохраниться на сервере. Если клиент есть в списке, повторное сохранение создаст его ДВАЖДЫ.',
  'Ro‘yxatda yo‘q — qaytadan saqlash': 'В списке нет — сохранить заново',
  'Ro‘yxatni tekshirdim': 'Я проверил список',
};

/// M4 (mijozlar, yetkazib beruvchilar, kassa, sotuvlar): qirg'izcha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> kyMoney = {
  // ── To'lov usullari, hujjat holatlari ──
  'Nasiya': 'Насыя',
  'Qabul qilingan': 'Кабыл алынды',
  'To‘langan': 'Төлөнгөн',
  'Qisman to‘langan': 'Жарым-жартылай төлөнгөн',
  'Qoralama': 'Долбоор',
  'Bekor qilingan': 'Жокко чыгарылган',
  'Yakunlangan': 'Аякталган',
  'Qaytarilgan': 'Кайтарылган',
  'Qisman qaytarilgan': 'Жарым-жартылай кайтарылган',
  // ── Ta'minotchi hisob-kitobi ──
  'To‘lov': 'Төлөм',
  'Xarid': 'Сатып алуу',
  'Xarid tahriri': 'Сатып алууну өзгөртүү',
  'Qabul tuzatildi': 'Кабыл алуу оңдолду',
  'Qarz kamaydi': 'Карыз азайды',
  'Qarz oshdi': 'Карыз көбөйдү',
  'Naqd chiqim': 'Накталай чыгым',
  // ── Umumiy ──
  'Bu bo‘limni ko‘rish uchun ruxsatingiz yo‘q.': 'Бул бөлүмдү көрүүгө уруксатыңыз жок.',
  'Hech narsa topilmadi': 'Эч нерсе табылган жок',
  'Tahrirlash': 'Түзөтүү',
  'Telefon (ixtiyoriy)': 'Телефон (милдеттүү эмес)',
  'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456': 'Телефон номери туура эмес. Мисалы: +996 700 123 456',
  'O‘zgarish yo‘q': 'Өзгөртүү жок',
  'Qayta saqlash': 'Кайра сактоо',
  'Server javobi kelmadi — o‘zgarish saqlangan-saqlanmagani noma’lum. Qayta saqlash xavfsiz.':
      'Сервердин жообу келген жок — өзгөртүү сакталганы белгисиз. Кайра сактоо коопсуз.',
  'Qayta yuborish': 'Кайра жөнөтүү',
  // ── To'lov oynasi ──
  'To‘lov qarzdan oshmasin (ko‘pi bilan {max})': 'Төлөм карыздан ашпасын (эң көп {max})',
  'Pul manbai tekshirilmoqda…': 'Акча булагы текшерилүүдө…',
  'Pul manbaini aniqlab bo‘lmadi — qayta urinib ko‘ring.': 'Акча булагын аныктоо мүмкүн болбоду — кайра аракет кылыңыз.',
  'Butun so‘mda. Qarzdan ortig‘i qabul qilinmaydi.': 'Бүтүн сом менен. Карыздан ашыгы кабыл алынбайт.',
  'To‘lov usuli': 'Төлөм ыкмасы',
  'Server javobi kelmadi — to‘lov yozilgan-yozilmagani noma’lum. «Qayta yuborish» xavfsiz: to‘lov ikki marta yozilmaydi.':
      'Сервердин жообу келген жок — төлөм жазылганы белгисиз. «Кайра жөнөтүү» коопсуз: төлөм эки жолу жазылбайт.',
  'Oldingi urinish natijasi noma’lum — to‘lov yozilgan bo‘lishi mumkin. Shuning uchun forma bloklangan: AYNAN shu to‘lovni qayta yuboring yoki «Yopish» bilan chiqing.':
      'Мурунку аракеттин жыйынтыгы белгисиз — төлөм жазылган болушу мүмкүн. Ошондуктан форма бөгөттөлгөн: ДАЛ ушул төлөмдү кайра жөнөтүңүз же «Жабуу» аркылуу чыгыңыз.',
  // ── Mijozlar ──
  'Yangi mijoz': 'Жаңы кардар',
  'Ism yoki telefon bo‘yicha qidirish': 'Аты же телефону боюнча издөө',
  'Qarzdor mijozlar yo‘q': 'Карыздар кардарлар жок',
  'Hozircha mijoz yo‘q': 'Азырынча кардар жок',
  '{n} ta qarzdor': 'Карыздарлар: {n}',
  'Avans': 'Аванс',
  'Mijoz ma’lumotlari saqlandi': 'Кардардын маалыматтары сакталды',
  'To‘lov qabul qilindi. Qolgan qarz: {left}': 'Төлөм кабыл алынды. Калган карыз: {left}',
  'To‘landi: {paid}. Qolgan qarz: {left}': 'Төлөндү: {paid}. Калган карыз: {left}',
  'Diqqat: siz {asked} kiritdingiz, lekin serverga {paid} yozildi. Qolgan qarz: {left}':
      'Көңүл буруңуз: сиз {asked} киргиздиңиз, бирок серверге {paid} жазылды. Калган карыз: {left}',
  'Server javobi kelmadi — to‘lov yozilgan bo‘lishi mumkin. Quyidagi ro‘yxatni tekshiring.':
      'Сервердин жообу келген жок — төлөм жазылган болушу мүмкүн. Төмөнкү тизмени текшериңиз.',
  'Avans (do‘kon mijozga qarzdor)': 'Аванс (дүкөн кардарга карыз)',
  'So‘nggi xaridlar': 'Акыркы сатып алуулар',
  'Qarz to‘lovlari': 'Карыз төлөмдөрү',
  'To‘lov yo‘q': 'Төлөм жок',
  '{n} ta tovar': 'Товар: {n}',
  'Miqdor: {q}': 'Саны: {q}',
  'Ismni kiriting': 'Атын жазыңыз',
  'Mijozni tahrirlash': 'Кардарды түзөтүү',
  'Manzil (ixtiyoriy)': 'Дарек (милдеттүү эмес)',
  'Server javobi kelmadi — mijoz yaratilgan-yaratilmagani noma’lum. Qayta saqlash xavfsiz: mijoz ikki marta yaratilmaydi.':
      'Сервердин жообу келген жок — кардар түзүлгөнү белгисиз. Кайра сактоо коопсуз: кардар эки жолу түзүлбөйт.',
  // ── Yetkazib beruvchilar ──
  'Yangi yetkazib beruvchi': 'Жаңы жеткирүүчү',
  'Hozircha yetkazib beruvchi yo‘q': 'Азырынча жеткирүүчү жок',
  '{n} ta yetkazib beruvchiga': 'жеткирүүчүлөргө: {n}',
  'Nomi yoki telefon bo‘yicha qidirish': 'Аталышы же телефону боюнча издөө',
  'Qarzimiz bor': 'Карызыбыз бар',
  'Hech kimga qarzimiz yo‘q': 'Эч кимге карызыбыз жок',
  'Yetkazib beruvchini tahrirlash': 'Жеткирүүчүнү түзөтүү',
  'Nomini kiriting': 'Аталышын жазыңыз',
  'Server javobi kelmadi — yetkazib beruvchi yaratilgan bo‘lishi mumkin. Takror yaratmaslik uchun avval ro‘yxatni yangilab tekshiring.':
      'Сервердин жообу келген жок — жеткирүүчү түзүлгөн болушу мүмкүн. Кайталап түзбөө үчүн адегенде тизмени жаңылап текшериңиз.',
  'Avval ro‘yxatni tekshiring': 'Адегенде тизмени текшериңиз',
  'Yetkazib beruvchi ma’lumotlari saqlandi': 'Жеткирүүчүнүн маалыматтары сакталды',
  'Bu to‘lov avval saqlangan edi — qayta yozilmadi.': 'Бул төлөм мурун сакталган — кайра жазылган жок.',
  'To‘landi: {paid}. Qolgan qarzimiz: {left}': 'Төлөндү: {paid}. Биздин калган карыз: {left}',
  'To‘lash': 'Төлөө',
  'Yetkazib beruvchi bizga qarzdor': 'Жеткирүүчү бизге карыз',
  'Oxirgi xarid': 'Акыркы сатып алуу',
  'Mahsulot turlari': 'Товар түрлөрү',
  'Kutilayotgan foyda': 'Күтүлгөн пайда',
  'Hisob-kitob': 'Эсептешүү',
  'Hisob-kitob yozuvlari yo‘q': 'Эсептешүү жазуулары жок',
  'Qoldiq: {sum}': 'Калдык: {sum}',
  'Mahsulot yo‘q': 'Товар жок',
  'Miqdor: {qty}': 'Саны: {qty}',
  // ── Kassa kirim / chiqim ──
  'Maosh': 'Айлык',
  'Kassa holatini aniqlab bo‘lmadi — qayta urinib ko‘ring.': 'Кассанын абалын аныктоо мүмкүн болбоду — кайра аракет кылыңыз.',
  // ── To'lov varag'i: yo'ldagi/muzlagan yozuv ──
  'So‘rov serverga yuborildi — javob kutilmoqda. Javob kelguncha bu oyna yopilmaydi.':
      'Суроо серверге жөнөтүлдү — жооп күтүлүүдө. Жооп келгенге чейин бул терезе жабылбайт.',
  'Javob kelmaguncha chiqib bo‘lmaydi: to‘lov serverda yozilayotgan bo‘lishi mumkin.':
      'Жооп келгенге чейин чыгууга болбойт: төлөм ушул учурда серверде жазылып жатышы мүмкүн.',
  'Chiqish uchun «Yopish» tugmasini bosing — natija noma’lumligi aytiladi va qarz qoldig‘i serverdan qayta o‘qiladi.':
      'Чыгуу үчүн «Жабуу» баскычын басыңыз — жыйынтык белгисиз экени айтылат жана карыз калдыгы серверден кайра окулат.',
  'Kassa holati tekshirilmoqda…': 'Кассанын абалы текшерилүүдө…',
  'Ochiq smena yo‘q — kassa amallari faqat ochiq smenaga yoziladi.':
      'Ачык смена жок — касса амалдары ачык сменага гана жазылат.',
  'Inkassatsiyani tasdiqlang': 'Инкассацияны ырастаңыз',
  'Xarajatni tasdiqlang': 'Чыгымды ырастаңыз',
  'Kassadan {sum} chiqariladi.': 'Кассадан {sum} чыгарылат.',
  'Smena filiali: {name}': 'Сменанын филиалы: {name}',
  'Qabul qiluvchi seyf: {code}': 'Кабыл алуучу сейф: {code}',
  'Izoh: {text}': 'Эскертүү: {text}',
  'Chiqarish': 'Чыгаруу',
  'Bu amal avval saqlangan edi — qayta yozilmadi.': 'Бул амал мурун сакталган — кайра жазылган жок.',
  'Saqlandi: {type} {sum}': 'Сакталды: {type} {sum}',
  'Qabul qiluvchi seyf': 'Кабыл алуучу сейф',
  'Server javobi kelmadi — amal yozilgan-yozilmagani noma’lum. «Qayta yuborish» xavfsiz: amal ikki marta yozilmaydi.':
      'Сервердин жообу келген жок — амал жазылганы белгисиз. «Кайра жөнөтүү» коопсуз: амал эки жолу жазылбайт.',
  'Oldingi urinish natijasi noma’lum — amal yozilgan bo‘lishi mumkin. Shuning uchun forma bloklangan: AYNAN shu amalni qayta yuboring yoki «Bekor qilish» bilan yangi amal boshlang.':
      'Мурунку аракеттин жыйынтыгы белгисиз — амал жазылган болушу мүмкүн. Ошондуктан форма бөгөттөлгөн: ДАЛ ушул амалды кайра жөнөтүңүз же «Жокко чыгаруу» аркылуу жаңы амал баштаңыз.',
  'Kassa amali serverda yozilgan bo‘lishi mumkin. Bekor qilsangiz, «Qayta yuborish» kaliti o‘chadi — o‘sha summani qayta kiritsangiz, amal IKKI MARTA yozilishi mumkin. Avval «Bugungi harakatlar» ro‘yxatini tekshiring.':
      'Касса операциясы серверде жазылган болушу мүмкүн. Жокко чыгарсаңыз, «Кайра жөнөтүү» ачкычы жоголот — ошол эле сумманы кайра киргизсеңиз, амал ЭКИ ЖОЛУ жазылышы мүмкүн. Адегенде «Бүгүнкү кыймылдар» тизмесин текшериңиз.',
  'Baribir bekor qilish': 'Баары бир жокко чыгаруу',
  'Kassa amali serverda yozilgan bo‘lishi mumkin. Chiqsangiz, «Qayta yuborish» tugmasi yo‘qoladi — «Bugungi harakatlar» ro‘yxatidan tekshiring.':
      'Касса операциясы серверде жазылган болушу мүмкүн. Чыксаңыз, «Кайра жөнөтүү» баскычы жоголот — «Бүгүнкү кыймылдар» тизмесинен текшериңиз.',
  'So‘rov yuborildi': 'Суроо жөнөтүлдү',
  'Kassa amali serverga yuborildi, javob hali kelmadi. Hozir chiqsangiz, javob yo‘qoladi — amal yozilgan bo‘lishi mumkin va «Qayta yuborish» kaliti ham o‘chadi.':
      'Касса операциясы серверге жөнөтүлдү, жооп али келе элек. Азыр чыксаңыз, жооп жоголот — амал жазылган болушу мүмкүн жана «Кайра жөнөтүү» ачкычы да өчөт.',
  'Ochiq smena yo‘q. Kassa kirim/chiqimi faqat filialning ochiq smenasiga yoziladi — avval POS’da smena oching, keyin qayta tekshiring.':
      'Ачык смена жок. Кассанын кириши жана чыгышы филиалдын ачык сменасына гана жазылат — адегенде POS’то смена ачып, анан кайра текшериңиз.',
  'Ochiq smenaga yoziladi': 'Ачык сменага жазылат',
  'Ochiq smenaga yoziladi: {branch}': 'Ачык сменага жазылат: {branch}',
  'Diqqat: siz «{current}» filialini ko‘ryapsiz, lekin kassa amali sizning filialingiz smenasiga yoziladi.':
      'Көңүл буруңуз: сиз «{current}» филиалын көрүп жатасыз, бирок касса амалы сиздин филиалдын сменасына жазылат.',
  // ── Sotuvlar ──
  'Chek raqami bo‘yicha qidirish': 'Чектин номери боюнча издөө',
  '7 kun': '7 күн',
  'Shu oy': 'Ушул ай',
  'Bu raqamli chek topilmadi': 'Мындай номердеги чек табылган жок',
  'Bugun hali sotuv yo‘q': 'Бүгүн азырынча сатуу жок',
  'Bu davrda sotuv yo‘q': 'Бул мезгилде сатуу жок',
  '{n} ta chek': 'Чек: {n}',
  'Ko‘proq ko‘rsatish': 'Көбүрөөк көрсөтүү',
  'Sotuv': 'Сатуу',
  'Chekni ko‘rish': 'Чекти көрүү',
  'Holati: {status}': 'Абалы: {status}',
  'Terminal': 'Терминал',
  'Vaqt': 'Убакыт',
  'Tovarlar ({n})': 'Товарлар ({n})',
  'Qatorlar saqlanmagan (tarixiy sotuv)': 'Саптар сакталган эмес (тарыхый сатуу)',
  'Ulashib bo‘lmadi': 'Бөлүшүү мүмкүн болбоду',
  'Bu — serverdagi chek nusxasi. Mobil ilovadan chop etilmaydi.':
      'Бул — сервердеги чектин көчүрмөсү. Мобилдик тиркемеден басылбайт.',
  // ── Chek (desktop receipt/labels.ts bilan bir xil) ──
  'Chek': 'Чек',
  'STIR': 'ИНН',
  'Xaridor': 'Кардар',
  'Oraliq jami': 'Аралык сумма',
  'Chek chegirmasi': 'Чекке арзандатуу',
  'Yaxlitlash': 'Тегеректөө',
  'Berildi': 'Берилди',
  'Qaytim': 'Кайтарым',
  'BEKOR QILINGAN CHEK': 'ЖОККО ЧЫГАРЫЛГАН ЧЕК',
  'QAYTARISH CHEKI': 'КАЙТАРУУ ЧЕГИ',
  'Asl chek': 'Баштапкы чек',
  'QAYTARISH JAMI': 'КАЙТАРУУ ЖЫЙЫНТЫГЫ',
  'JAMI': 'ЖЫЙЫНТЫК',
  'Qaytarildi': 'Кайтарылды',
  'Xaridingiz uchun rahmat!': 'Сатып алганыңыз үчүн рахмат!',
  // Javobsiz urinishdan keyingi muzlashni ochish (tasdiq bilan).
  'Ro‘yxatni tekshirdingizmi?': 'Тизмени текшердиңизби?',
  'Avvalgi urinish serverda saqlangan bo‘lishi mumkin. Agar mijoz ro‘yxatda bo‘lsa, qaytadan saqlash uni IKKI MARTA yaratadi.':
      'Мурдагы аракет серверде сакталган болушу мүмкүн. Эгер клиент тизмеде болсо, кайра сактоо аны ЭКИ ЖОЛУ түзүт.',
  'Ro‘yxatda yo‘q — qaytadan saqlash': 'Тизмеде жок — кайрадан сактоо',
  'Ro‘yxatni tekshirdim': 'Тизмени текшердим',
};
