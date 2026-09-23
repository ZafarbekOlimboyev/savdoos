// Server xatolari tarjimalari — `lib/errors.dart` dagi o'zbekcha shablonlar.
// Kalit = errors.dart dagi matn AYNAN (o'rinbosarlar `{nom}` saqlanadi).

/// Xatolar: ruscha.
const Map<String, String> ruErrors = {
  // ── Umumiy ──
  'Server bilan aloqa yo‘q. Internetni tekshirib, qayta urinib ko‘ring.':
      'Нет связи с сервером. Проверьте интернет и попробуйте снова.',
  'Server o‘z vaqtida javob bermadi. Aloqani tekshirib, qayta urinib ko‘ring.':
      'Сервер не ответил вовремя. Проверьте связь и попробуйте снова.',
  'Sessiya tugadi — qayta kiring': 'Сессия истекла — войдите снова',
  'Ma’lumotlar noto‘g‘ri to‘ldirilgan — maydonlarni tekshirib, qayta urinib ko‘ring.':
      'Данные заполнены неверно — проверьте поля и попробуйте снова.',
  'Serverda vaqtincha nosozlik. Birozdan so‘ng qayta urinib ko‘ring.':
      'Временный сбой на сервере. Попробуйте немного позже.',
  'Serverdan kutilmagan javob keldi — internet ulanishini tekshiring.':
      'Сервер вернул неожиданный ответ — проверьте подключение к интернету.',
  'Bu amal uchun ruxsatingiz yo‘q.': 'У вас нет прав на это действие.',
  'Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.': 'Произошла непредвиденная ошибка. Попробуйте снова.',
  'Xatolik ({status}). Qayta urinib ko‘ring.': 'Ошибка ({status}). Попробуйте снова.',
  'Server bu so‘rovni tanimadi — server yangilanishi kerak bo‘lishi mumkin.':
      'Сервер не распознал запрос — возможно, сервер нужно обновить.',
  'Bu amal uchun ruxsat yo‘q: {perms}': 'Нет прав на это действие: {perms}',
  'Do‘kon vaqtincha to‘xtatilgan. Xizmat ko‘rsatuvchi bilan bog‘laning.':
      'Магазин временно приостановлен. Свяжитесь с обслуживающей компанией.',
  // ── Filial ──
  'Filial topilmadi': 'Филиал не найден',
  'Filial topilmadi ({name})': 'Филиал не найден ({name})',
  'Filial nofaol — amalni bajarib bo‘lmaydi': 'Филиал неактивен — операция невозможна',
  'Filial nofaol — ko‘chirib bo‘lmaydi ({name})': 'Филиал неактивен — перемещение невозможно ({name})',
  'Bu filial sizga biriktirilmagan': 'Этот филиал вам не назначен',
  'Manba filial sizga biriktirilmagan': 'Филиал-источник вам не назначен',
  'Bir xil filial tanlandi — boshqa filialni tanlang': 'Выбран тот же филиал — выберите другой',
  // ── Band / qayta urinish ──
  'Ombor band — sanoqni qayta yuboring': 'Склад занят — отправьте пересчёт ещё раз',
  'Ko‘chirish band — qayta urinib ko‘ring': 'Перемещение занято — попробуйте ещё раз',
  'Qabul hujjati band — qayta urinib ko‘ring': 'Документ приёмки занят — попробуйте ещё раз',
  'Xarid hujjati band — qayta urinib ko‘ring': 'Документ закупки занят — попробуйте ещё раз',
  'Kassa band — qayta urinib ko‘ring': 'Касса занята — попробуйте ещё раз',
  // ── Kassa amallari ──
  'Ochiq smena yo‘q — avval kassada smena oching': 'Нет открытой смены — сначала откройте смену на кассе',
  'Inkassatsiya: manba va manzil bir xil hisob bo‘lishi mumkin emas':
      'Инкассация: источник и получатель не могут быть одним счётом',
  'Kassada yetarli naqd yo‘q (mavjud: {amount})': 'В кассе недостаточно наличных (есть: {amount})',
  'Kassada yetarli naqd pul yo‘q.': 'В кассе недостаточно наличных.',
  // ── Mijozlar / yetkazib beruvchilar ──
  'Mijoz topilmadi': 'Клиент не найден',
  'Bu telefon raqami do‘konda allaqachon band': 'Этот номер телефона уже используется в магазине',
  'Mijoz yaratishda to‘qnashuv — qayta urinib ko‘ring': 'Конфликт при создании клиента — попробуйте ещё раз',
  'Hisob-kitobi ochiq (qarz yoki avans) mijozni o‘chirib bo‘lmaydi':
      'Нельзя удалить клиента с открытыми расчётами (долг или аванс)',
  'Summa noto‘g‘ri': 'Неверная сумма',
  'Qarz yo‘q': 'Долга нет',
  'Naqd qarz to‘lovi uchun ochiq smena kerak — avval smenani oching':
      'Для оплаты долга наличными нужна открытая смена — сначала откройте смену',
  'Noto‘g‘ri to‘lov usuli: {method}': 'Неверный способ оплаты: {method}',
  'Yetkazib beruvchi topilmadi': 'Поставщик не найден',
  'Balansi bor yetkazib beruvchini o‘chirib bo‘lmaydi — avval qarzni yoping':
      'Нельзя удалить поставщика с балансом — сначала закройте долг',
  'Bu yetkazib beruvchiga qarz yo‘q': 'У этого поставщика нет долга',
  'Kirim topilmadi': 'Приход не найден',
  // ── Qabul ──
  'Kamida bitta mahsulot kerak': 'Нужен хотя бы один товар',
  'Mahsulotni tanlang yoki yangi nom kiriting': 'Выберите товар или введите новое название',
  'PLU kodi 1–5 raqamdan iborat bo‘lsin': 'Код PLU должен состоять из 1–5 цифр',
  'PLU {plu} band ({other}) — «{name}» uchun boshqa PLU kiriting':
      'PLU {plu} занят ({other}) — укажите другой PLU для «{name}»',
  'Qabul topilmadi': 'Приёмка не найдена',
  'Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Партии и остаток не сходятся — приход ОТМЕНЁН. Обратитесь в поддержку.',
  'Rasmni o‘qib bo‘lmadi — qayta urinib ko‘ring yoki qo‘lda kiriting':
      'Не удалось распознать фото — попробуйте снова или введите вручную',
  'Ombor qoldig‘i yetarli emas: {name} (qoldiq {qty})': 'Недостаточно остатка на складе: {name} (остаток {qty})',
  'Yetarli qoldiq yo‘q: {name} (qoldiq: {qty})': 'Недостаточно остатка: {name} (остаток: {qty})',
  '«{name}»: qabul qiluvchi filial qoldig‘i juda katta — miqdorni tekshiring':
      '«{name}»: остаток в филиале-получателе слишком велик — проверьте количество',
  // ── Chek ──
  'Chek topilmadi': 'Чек не найден',
  'Qaytarish topilmadi': 'Возврат не найден',
  'Kompaniya chek shablonini faqat barcha filiallarga kirishi bor xodim o‘zgartiradi.':
      'Шаблон чека компании может менять только сотрудник с доступом ко всем филиалам.',
  'Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting.':
      'Оригинал чека по этому документу уже напечатан — печатайте копию.',
  'Chop etish holati yakunlangan — o‘zgartirib bo‘lmaydi.': 'Статус печати уже окончательный — изменить нельзя.',
  'Chop etish so‘rovi noto‘g‘ri.': 'Некорректный запрос печати.',
  'Bu chek hozir boshqa qurilmada chop etilmoqda — nusxa chop eting.':
      'Этот чек сейчас печатается на другом устройстве — печатайте копию.',
  // ── Partiyalar (kod bo'yicha) ──
  'Partiya bo‘yicha kuzatiladigan mahsulot uchun har qatorga partiyalarni kiriting.':
      'Для товара с учётом партий укажите партии в каждой строке.',
  'Bu mahsulot partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.':
      'Этот товар не учитывается по партиям — партии указать нельзя.',
  'Partiyalar yig‘indisi qator miqdoriga teng emas.': 'Сумма партий не равна количеству строки.',
  'Miqdor 0,001 aniqlikda kiritiladi — uchtadan ortiq kasr xona bo‘lmasin.':
      'Количество вводится с точностью 0,001 — не более трёх знаков после запятой.',
  'Bu mahsulot muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.':
      'Для этого товара учитывается срок годности — укажите срок для каждой партии.',
  'Bu mahsulot muddat bo‘yicha kuzatilmaydi — muddat kiritib bo‘lmaydi.':
      'Для этого товара срок годности не учитывается — срок указать нельзя.',
  'Muddati o‘tgan tovar qabul qilinmaydi — muddat bugungi ish kunidan oldin.':
      'Просроченный товар не принимается — срок раньше текущего рабочего дня.',
  'Filial vaqt zonasi tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.':
      'Часовой пояс филиала не подтверждён — партии со сроком записать нельзя. Администратор должен подтвердить пояс.',
  'Tanlangan partiya yaroqsiz (boshqa mahsulot yoki filialga tegishli yoki yopilgan). Ro‘yxatni yangilab, qayta tanlang.':
      'Выбранная партия недействительна (другой товар или филиал, либо закрыта). Обновите список и выберите снова.',
  'Partiyada yetarli qoldiq yo‘q — miqdorni kamaytiring yoki ro‘yxatni yangilang.':
      'В партии недостаточно остатка — уменьшите количество или обновите список.',
  'Partiyalar bo‘yicha sanoq yig‘indisi umumiy sanoqqa teng emas.':
      'Сумма пересчёта по партиям не равна общему пересчёту.',
  'Partiya bo‘yicha kuzatiladigan mahsulotni filiallararo ko‘chirib bo‘lmaydi.':
      'Товар с учётом партий нельзя перемещать между филиалами.',
  'Partiya va qoldiq mos kelmadi — amal BAJARILMADI. Qo‘llab-quvvatlashga murojaat qiling.':
      'Партии и остаток не сходятся — операция НЕ выполнена. Обратитесь в поддержку.',
  'Qaytarish partiya chegarasidan oshardi — amal bajarilmadi.':
      'Возврат превысил бы лимит партии — операция не выполнена.',
  'Partiya tannarxi mos kelmadi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Себестоимость партии не сходится — операция не выполнена. Обратитесь в поддержку.',
  'Bu tovar partiya hisobi yoqilishidan oldin sotilgan — omborga qaytarmasdan qaytaring.':
      'Этот товар продан до включения учёта партий — оформите возврат без возврата на склад.',
  'Qarzni yopib bo‘lmadi — partiya va qoldiq mos kelmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Не удалось закрыть долг — партии и остаток не сходятся. Обратитесь в поддержку.',
  'Server partiya hisobiga hali tayyor emas — administratorga xabar bering.':
      'Сервер ещё не готов к учёту партий — сообщите администратору.',
  // ── Partiyalar (matn bo'yicha) ──
  'Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko‘rsatib bo‘lmaydi':
      'Для этого товара учёт партий не включён — партию указать нельзя',
  'Partiyali mahsulot uchun partiyalarni aniq ko‘rsating — tizim qaysi partiya chiqarilayotganini taxmin qilmaydi.':
      'Для товара с учётом партий укажите партии точно — система не угадывает, какая партия списывается.',
  'Partiyali mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga taqsimlamaydi.':
      'У товара с учётом партий пересчитайте партии — общую разницу система по партиям не распределяет.',
  'Yangi partiya miqdori noldan katta bo‘lsin.': 'Количество новой партии должно быть больше нуля.',
  'Yangi partiya tannarxi manfiy bo‘lishi mumkin emas.': 'Себестоимость новой партии не может быть отрицательной.',
  'Bitta mahsulot bir sanoqda ikki marta bo‘lmasin': 'Один товар не может быть в пересчёте дважды',
  'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Списать не удалось — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.',
  'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Пересчёт не записан — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.',
  'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.':
      'Списать не удалось — партии и остаток перестали бы сходиться. Операция не выполнена.',
  'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.':
      'Пересчёт не записан — партии и остаток перестали бы сходиться. Операция не выполнена.',
  'Partiya topilmadi': 'Партия не найдена',
  'Filial vaqt zonasi o‘rnatilmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani sozlasin.':
      'Часовой пояс филиала не задан — партии со сроком записать нельзя. Администратор должен настроить пояс.',
  'Partiya ikki marta ko‘rsatilgan': 'Партия указана дважды',
  'Partiya ikki marta sanalgan': 'Партия пересчитана дважды',
  'Partiya miqdori noldan katta bo‘lsin': 'Количество партии должно быть больше нуля',
  'Sanoq manfiy bo‘lishi mumkin emas': 'Пересчёт не может быть отрицательным',
  'Partiya boshqa mahsulot yoki filialga tegishli — ro‘yxatni yangilang':
      'Партия относится к другому товару или филиалу — обновите список',
  'Partiya holati «{status}» — undan miqdor ayirib bo‘lmaydi': 'Статус партии «{status}» — списать с неё нельзя',
  'Partiya holati «{status}» — uni sanab bo‘lmaydi': 'Статус партии «{status}» — её нельзя пересчитать',
  'Partiyada yetarli qoldiq yo‘q ({have} < {need})': 'В партии недостаточно остатка ({have} < {need})',
  'Partiyalar yig‘indisi ({sum}) umumiy miqdorga ({total}) teng emas — qaysi partiya ekanini ko‘rsating.':
      'Сумма партий ({sum}) не равна общему количеству ({total}) — укажите, какая это партия.',
  'Partiyalar yig‘indisi ({sum}) umumiy sanoqqa ({total}) teng emas. Sanalmagan partiyalar o‘zgarmaydi ({untouched}).':
      'Сумма партий ({sum}) не равна общему пересчёту ({total}). Непересчитанные партии не меняются ({untouched}).',
  '«{name}» muddat bo‘yicha kuzatiladi — yangi partiyaga yaroqlilik muddatini kiriting.':
      '«{name}» учитывается по сроку годности — укажите срок для новой партии.',
  '«{name}» partiya bo‘yicha kuzatiladi — har kirim qatoriga partiyalarni kiriting.':
      '«{name}» учитывается по партиям — укажите партии в каждой строке прихода.',
  '«{name}» partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.':
      '«{name}» не учитывается по партиям — партии указать нельзя.',
  '«{name}» muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.':
      '«{name}» учитывается по сроку годности — укажите срок для каждой партии.',
  '«{name}» muddat bo‘yicha kuzatilmaydi — partiyaga muddat kiritib bo‘lmaydi.':
      '«{name}» не учитывается по сроку годности — срок партии указать нельзя.',
  '«{name}»: partiyalar yig‘indisi {sum} qator miqdori {total} ga teng emas.':
      '«{name}»: сумма партий {sum} не равна количеству строки {total}.',
  '«{name}»: partiya miqdori noldan katta bo‘lsin': '«{name}»: количество партии должно быть больше нуля',
  '«{name}»: miqdor {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.':
      '«{name}»: в количестве {qty} больше трёх знаков после запятой — количество вводится с точностью 0,001.',
  '«{name}»: partiya miqdori {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.':
      '«{name}»: в количестве партии {qty} больше трёх знаков после запятой — количество вводится с точностью 0,001.',
  '«{name}»: partiya tannarxi noma’lum — kirim narxini kiriting.':
      '«{name}»: себестоимость партии неизвестна — укажите цену прихода.',
  '«{name}»: muddat {date} bugungi ish kunidan ({today}) oldin — muddati o‘tgan tovar qabul qilinmaydi.':
      '«{name}»: срок {date} раньше текущего рабочего дня ({today}) — просроченный товар не принимается.',
  '«{name}» qatori summasi juda katta ({amount}) — miqdor yoki narxni tekshiring':
      'Сумма строки «{name}» слишком велика ({amount}) — проверьте количество или цену',
  '«{name}» partiya bo‘yicha kuzatiladi — kirim narxini tahrirlab bo‘lmaydi; tuzatish orqali o‘zgartiring.':
      '«{name}» учитывается по партиям — цену прихода редактировать нельзя; измените через исправление.',
  'Filial vaqt zonasi ({tz}) tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.':
      'Часовой пояс филиала ({tz}) не подтверждён — партии со сроком записать нельзя. Администратор должен подтвердить пояс.',
  'Vaqt zonasi «{tz}» tanilmagan — administratorga xabar bering.':
      'Часовой пояс «{tz}» не распознан — сообщите администратору.',
  'Bu amal partiya bo‘yicha kuzatiladigan mahsulotni qo‘llab-quvvatlamaydi ({n} ta mahsulot).':
      'Эта операция не поддерживает товары с учётом партий (товаров: {n}).',
  'Noma’lum filtr qiymati: {value}': 'Неизвестное значение фильтра: {value}',
  'Bir so‘rovda {n} ta partiya qatori — chegara {max}. Sanoqni bir necha qismga bo‘lib yuboring.':
      'В одном запросе {n} строк партий — предел {max}. Разбейте пересчёт на несколько частей.',
  // ── Qabulni tuzatish ──
  'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun.':
      'Эта приёмка не создала партий — исправление только для приёмок с партиями.',
  'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun. Hujjatni oddiy kirim tahriri bilan o‘zgartiring.':
      'Эта приёмка не создала партий — исправление только для приёмок с партиями. Измените документ обычным редактированием прихода.',
  'Partiyadan tovar allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.':
      'Товар из партии уже двигался — её номер, срок и цену исправить нельзя; можно только вернуть количество.',
  'Qaytarilayotgan miqdor partiya qoldig‘idan katta.': 'Возвращаемое количество больше остатка партии.',
  'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.':
      'У товара есть незакрытый долг по партиям — сначала привяжите долг к партии.',
  'Kassa yozuvini yozib bo‘lmadi — tuzatish BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Не удалось сделать запись в кассе — исправление ОТМЕНЕНО. Обратитесь в поддержку.',
  'Bu so‘rov avval boshqa mazmun bilan yuborilgan. Hujjatni yangilab, tuzatishni qayta yuboring.':
      'Этот запрос уже отправлялся с другим содержимым. Обновите документ и отправьте исправление заново.',
  'Hujjat tuzatilgan — uni faqat yangi tuzatish orqali o‘zgartirish mumkin.':
      'Документ исправлен — изменить его можно только новым исправлением.',
  'Tuzatish so‘rovi yakunlanmagan — qayta urinib ko‘ring': 'Запрос исправления не завершён — попробуйте ещё раз',
  'Tuzatishni yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Исправление не записано — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.',
  'Xarid filiali o‘chirilgan — tuzatib bo‘lmaydi': 'Филиал закупки удалён — исправить нельзя',
  'Tuzatish hujjat jamini manfiy qilardi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Исправление сделало бы итог документа отрицательным — операция не выполнена. Обратитесь в поддержку.',
  'Kamida bitta qator kerak': 'Нужна хотя бы одна строка',
  'Qator tannarxi manfiy bo‘lishi mumkin emas': 'Себестоимость строки не может быть отрицательной',
  'Qator topilmadi': 'Строка не найдена',
  'Bu hujjatga bog‘langan qabul yo‘q — tuzatish faqat qabul hujjati orqali bajariladi.':
      'К этому документу не привязана приёмка — исправление выполняется только через документ приёмки.',
  'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang, keyin bu qatorni tuzating.':
      'У товара есть незакрытый долг по партиям — сначала привяжите долг к партии, затем исправьте эту строку.',
  'Qaytarilgan summa juda katta — miqdor yoki narxni tekshiring':
      'Возвращаемая сумма слишком велика — проверьте количество или цену',
  'Almashtirilgan summa juda katta — miqdor yoki narxni tekshiring':
      'Сумма замены слишком велика — проверьте количество или цену',
  'Tuzatish summasi juda katta — miqdor yoki narxni tekshiring':
      'Сумма исправления слишком велика — проверьте количество или цену',
  'Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring':
      'Итоговая сумма документа слишком велика — проверьте количество или цену',
  'Summa juda katta — miqdor yoki narxni tekshiring': 'Сумма слишком велика — проверьте количество или цену',
  'Tuzatish sababi {min}–{max} belgidan iborat bo‘lsin.': 'Причина исправления — от {min} до {max} символов.',
  'Bir so‘rovda {n} ta qator — chegara {max}. Tuzatishni bir necha qismga bo‘lib yuboring.':
      'В одном запросе {n} строк — предел {max}. Разбейте исправление на несколько частей.',
  'Bitta qatorda {n} tadan ortiq partiya — tuzatishni bo‘lib yuboring.':
      'В одной строке больше {n} партий — разбейте исправление.',
  'Qator ikki marta ko‘rsatilgan': 'Строка указана дважды',
  'Qatorda na qaytarish, na almashtirish bor': 'В строке нет ни возврата, ни замены',
  'Almashtiriladigan partiya bor, lekin qator tannarxi kiritilmagan.':
      'Есть партия на замену, но себестоимость строки не указана.',
  'Tannarxni partiyasiz tuzatib bo‘lmaydi — eski partiyani qaytarib, yangisini kiriting.':
      'Себестоимость нельзя исправить без партий — верните старую партию и укажите новую.',
  'Partiya bu qabulga tegishli emas': 'Партия не относится к этой приёмке',
  '«{name}»: qoldiq qatori topilmadi — tuzatib bo‘lmaydi': '«{name}»: строка остатка не найдена — исправить нельзя',
  '«{name}»: partiyada {left} qoldi, {qty} qaytarilmoqda — partiya manfiyga tushmaydi.':
      '«{name}»: в партии осталось {left}, возвращается {qty} — партия не может уйти в минус.',
  '«{name}»: partiyadan {qty} allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.':
      '«{name}»: из партии уже ушло {qty} — её номер, срок и цену исправить нельзя; можно только вернуть количество.',
  '«{name}»: yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.':
      '«{name}»: есть незакрытый долг по партиям — сначала привяжите долг к партии.',
  // ── Naqd (kassa) ──
  'Naqd amal uchun pul manbaini (kassa yoki seyf) tanlang. Kassirda ochiq smena bo‘lsa, manba o‘sha smenaning kassasi bo‘ladi.':
      'Для наличной операции выберите источник денег (касса или сейф). Если у кассира открыта смена, источником будет касса этой смены.',
  'Naqd hisob bu amalga to‘g‘ri kelmaydi: u faol emas yoki boshqa filialga tegishli. Ochiq smenangiz boshqa filialda bo‘lsa — smenani yoping yoki hujjatni o‘sha filial xodimi rasmiylashtirsin.':
      'Денежный счёт не подходит для этой операции: он неактивен или относится к другому филиалу. Если ваша открытая смена в другом филиале — закройте смену или пусть документ оформит сотрудник того филиала.',
  'Naqd hisobi vaqtincha ishlamayapti — amal BAJARILMADI. Administratorga xabar bering.':
      'Учёт наличных временно недоступен — операция НЕ выполнена. Сообщите администратору.',
  'Kassa tanlanmagan. Smenani aniq kassa tanlab oching.': 'Касса не выбрана. Откройте смену, выбрав конкретную кассу.',
  'Kassa yaroqsiz (faol emas yoki boshqa filialga tegishli).':
      'Касса недействительна (неактивна или относится к другому филиалу).',
  'Bu amal ochiq smena kassasiga mos emas. Smena o‘rtasida kassa almashtirilmaydi.':
      'Операция не соответствует кассе открытой смены. Касса не меняется в середине смены.',
  'Smena eski usulda (kassasiz) ochilgan. Uni yopib, kassa tanlab yangi smena oching.':
      'Смена открыта по-старому (без кассы). Закройте её и откройте новую, выбрав кассу.',
  'Bu amal yopilgan smenaga tegishli — avtomatik qabul qilinmaydi. Administrator tekshirsin.':
      'Операция относится к закрытой смене — автоматически не принимается. Требуется проверка администратора.',
  'Naqd hisob holatini aniqlab bo‘lmadi — amal to‘xtatildi. Ilovani yangilang yoki administratorga xabar bering.':
      'Не удалось определить состояние денежного счёта — операция остановлена. Обновите приложение или сообщите администратору.',
  'Bu naqd amal uchun kassada ochiq smena kerak — avval smenani oching.':
      'Для этой наличной операции нужна открытая смена на кассе — сначала откройте смену.',
  'Kassa amali yozilmadi. Qayta urinib ko‘ring; takrorlansa administratorga xabar bering.':
      'Кассовая операция не записана. Попробуйте ещё раз; если повторится — сообщите администратору.',
  'Amal kassani manfiyga tushiradi — administrator tasdig‘i kerak.':
      'Операция уводит кассу в минус — нужно подтверждение администратора.',
  'Naqd hisob arxivlangan — boshqa hisobni tanlang.': 'Денежный счёт в архиве — выберите другой счёт.',
  'Naqd hisob topilmadi — ro‘yxatni yangilang.': 'Денежный счёт не найден — обновите список.',
  'Hisob valyutasi amal valyutasiga mos emas.': 'Валюта счёта не совпадает с валютой операции.',
  'Smena ochiq emas.': 'Смена не открыта.',
  'Bu naqd amal uchun ruxsatingiz yo‘q.': 'У вас нет прав на эту наличную операцию.',
  // ── Naqd posting (CashError, qo'shimcha) ──
  'Naqd hisob bu do‘konga tegishli emas — ro‘yxatni yangilang.':
      'Денежный счёт не относится к этому магазину — обновите список.',
  'Amal vaqti noto‘g‘ri — telefondagi sana va vaqtni tekshiring.':
      'Неверное время операции — проверьте дату и время на телефоне.',
  'Smena topilmadi — ma’lumotlarni yangilang.': 'Смена не найдена — обновите данные.',
  'Smena tanlangan kassaga tegishli emas.': 'Смена не относится к выбранной кассе.',
  'Bu naqd amal allaqachon bekor qilingan.': 'Эта наличная операция уже отменена.',
  'Bu naqd amalni bekor qilib bo‘lmaydi.': 'Эту наличную операцию нельзя отменить.',
  'Pul o‘tkazmasi noto‘g‘ri — manba va qabul qiluvchi hisobni tekshiring.':
      'Неверный перевод денег — проверьте счёт-источник и счёт-получатель.',
  'Bu amal uchun bunday turdagi naqd hisobni ishlatib bo‘lmaydi.':
      'Для этой операции нельзя использовать денежный счёт такого типа.',
  'Naqd amal ma’lumotlari noto‘g‘ri — summani tekshiring.': 'Неверные данные наличной операции — проверьте сумму.',
  'Bu naqd amal allaqachon yozilgan — ro‘yxatni yangilang.': 'Эта наличная операция уже записана — обновите список.',
  // ── Umumiy validatsiya ──
  'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456': 'Неверный номер телефона. Например: +996 700 123 456',
  'So‘rov bo‘sh — qidiruv matnini kiriting.': 'Пустой запрос — введите текст для поиска.',
  '{field} kiritilishi kerak': 'Необходимо заполнить: {field}',
  'Mijoz nomi': 'Имя клиента',
  'Ism': 'Имя',
  'Kategoriya nomi': 'Название категории',
  'Yetkazib beruvchi nomi': 'Название поставщика',
  // ── O'z paroli (POST /auth/password) va parol siyosati ──
  'Joriy parol (yoki PIN) noto‘g‘ri.': 'Неверный текущий пароль (или PIN).',
  'Parolni o‘zingiz o‘rnata olmaysiz — administratorga murojaat qiling.':
      'Вы не можете сами установить пароль — обратитесь к администратору.',
  'Parol o‘rnatish uchun avval telefon (login) qo‘shilishi kerak.':
      'Чтобы установить пароль, сначала нужно добавить телефон (логин).',
  'Bu telefon raqami boshqa akkauntda band.': 'Этот номер телефона занят другим аккаунтом.',
  'Parol juda qisqa — kamida {n} belgi kerak.': 'Пароль слишком короткий — нужно не менее {n} символов.',
  'Parol juda uzun.': 'Пароль слишком длинный.',
  'Parol juda oddiy — boshqa parol tanlang.': 'Пароль слишком простой — выберите другой.',
  'Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.':
      'В пароле слишком много повторяющихся символов — выберите другой.',
  'Yangi parolni kiriting.': 'Введите новый пароль.',
  'Parol qabul qilinmadi — boshqa parol tanlang.': 'Пароль не принят — выберите другой.',
};

/// Xatolar: qirg'izcha.
const Map<String, String> kyErrors = {
  // ── Umumiy ──
  'Server bilan aloqa yo‘q. Internetni tekshirib, qayta urinib ko‘ring.':
      'Сервер менен байланыш жок. Интернетти текшерип, кайра аракет кылыңыз.',
  'Server o‘z vaqtida javob bermadi. Aloqani tekshirib, qayta urinib ko‘ring.':
      'Сервер өз убагында жооп берген жок. Байланышты текшерип, кайра аракет кылыңыз.',
  'Sessiya tugadi — qayta kiring': 'Сессия бүттү — кайра кириңиз',
  'Ma’lumotlar noto‘g‘ri to‘ldirilgan — maydonlarni tekshirib, qayta urinib ko‘ring.':
      'Маалыматтар туура эмес толтурулган — талааларды текшерип, кайра аракет кылыңыз.',
  'Serverda vaqtincha nosozlik. Birozdan so‘ng qayta urinib ko‘ring.':
      'Серверде убактылуу бузулуу. Бир аздан кийин кайра аракет кылыңыз.',
  'Serverdan kutilmagan javob keldi — internet ulanishini tekshiring.':
      'Серверден күтүлбөгөн жооп келди — интернет туташуусун текшериңиз.',
  'Bu amal uchun ruxsatingiz yo‘q.': 'Бул аракетке уруксатыңыз жок.',
  'Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.': 'Күтүлбөгөн ката кетти. Кайра аракет кылыңыз.',
  'Xatolik ({status}). Qayta urinib ko‘ring.': 'Ката ({status}). Кайра аракет кылыңыз.',
  'Server bu so‘rovni tanimadi — server yangilanishi kerak bo‘lishi mumkin.':
      'Сервер бул сурамды тааныган жок — серверди жаңыртуу керек болушу мүмкүн.',
  'Bu amal uchun ruxsat yo‘q: {perms}': 'Бул аракетке уруксат жок: {perms}',
  'Do‘kon vaqtincha to‘xtatilgan. Xizmat ko‘rsatuvchi bilan bog‘laning.':
      'Дүкөн убактылуу токтотулган. Тейлөөчү компания менен байланышыңыз.',
  // ── Filial ──
  'Filial topilmadi': 'Филиал табылган жок',
  'Filial topilmadi ({name})': 'Филиал табылган жок ({name})',
  'Filial nofaol — amalni bajarib bo‘lmaydi': 'Филиал активдүү эмес — амалды аткарууга болбойт',
  'Filial nofaol — ko‘chirib bo‘lmaydi ({name})': 'Филиал активдүү эмес — которууга болбойт ({name})',
  'Bu filial sizga biriktirilmagan': 'Бул филиал сизге бекитилген эмес',
  'Manba filial sizga biriktirilmagan': 'Булак филиал сизге бекитилген эмес',
  'Bir xil filial tanlandi — boshqa filialni tanlang': 'Бир эле филиал тандалды — башка филиалды тандаңыз',
  // ── Band / qayta urinish ──
  'Ombor band — sanoqni qayta yuboring': 'Кампа бош эмес — эсепти кайра жөнөтүңүз',
  'Ko‘chirish band — qayta urinib ko‘ring': 'Которуу бош эмес — кайра аракет кылыңыз',
  'Qabul hujjati band — qayta urinib ko‘ring': 'Кабыл алуу документи бош эмес — кайра аракет кылыңыз',
  'Xarid hujjati band — qayta urinib ko‘ring': 'Сатып алуу документи бош эмес — кайра аракет кылыңыз',
  'Kassa band — qayta urinib ko‘ring': 'Касса бош эмес — кайра аракет кылыңыз',
  // ── Kassa amallari ──
  'Ochiq smena yo‘q — avval kassada smena oching': 'Ачык смена жок — адегенде кассада смена ачыңыз',
  'Inkassatsiya: manba va manzil bir xil hisob bo‘lishi mumkin emas':
      'Инкассация: булак жана алуучу бир эле эсеп боло албайт',
  'Kassada yetarli naqd yo‘q (mavjud: {amount})': 'Кассада накталай жетишсиз (бар: {amount})',
  'Kassada yetarli naqd pul yo‘q.': 'Кассада накталай акча жетишсиз.',
  // ── Mijozlar / yetkazib beruvchilar ──
  'Mijoz topilmadi': 'Кардар табылган жок',
  'Bu telefon raqami do‘konda allaqachon band': 'Бул телефон номери дүкөндө мурунтан колдонулууда',
  'Mijoz yaratishda to‘qnashuv — qayta urinib ko‘ring': 'Кардар түзүүдө кагылышуу — кайра аракет кылыңыз',
  'Hisob-kitobi ochiq (qarz yoki avans) mijozni o‘chirib bo‘lmaydi':
      'Эсептешүүсү ачык (карыз же аванс) кардарды өчүрүүгө болбойт',
  'Summa noto‘g‘ri': 'Сумма туура эмес',
  'Qarz yo‘q': 'Карыз жок',
  'Naqd qarz to‘lovi uchun ochiq smena kerak — avval smenani oching':
      'Карызды накталай төлөө үчүн ачык смена керек — адегенде сменаны ачыңыз',
  'Noto‘g‘ri to‘lov usuli: {method}': 'Туура эмес төлөм ыкмасы: {method}',
  'Yetkazib beruvchi topilmadi': 'Жеткирүүчү табылган жок',
  'Balansi bor yetkazib beruvchini o‘chirib bo‘lmaydi — avval qarzni yoping':
      'Балансы бар жеткирүүчүнү өчүрүүгө болбойт — адегенде карызды жабыңыз',
  'Bu yetkazib beruvchiga qarz yo‘q': 'Бул жеткирүүчүгө карыз жок',
  'Kirim topilmadi': 'Кириш табылган жок',
  // ── Qabul ──
  'Kamida bitta mahsulot kerak': 'Жок дегенде бир товар керек',
  'Mahsulotni tanlang yoki yangi nom kiriting': 'Товарды тандаңыз же жаңы аталыш киргизиңиз',
  'PLU kodi 1–5 raqamdan iborat bo‘lsin': 'PLU коду 1–5 сандан турушу керек',
  'PLU {plu} band ({other}) — «{name}» uchun boshqa PLU kiriting':
      'PLU {plu} бош эмес ({other}) — «{name}» үчүн башка PLU киргизиңиз',
  'Qabul topilmadi': 'Кабыл алуу табылган жок',
  'Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Партиялар жана калдык дал келген жок — кириш ЖОККО ЧЫГАРЫЛДЫ. Колдоо кызматына кайрылыңыз.',
  'Rasmni o‘qib bo‘lmadi — qayta urinib ko‘ring yoki qo‘lda kiriting':
      'Сүрөттү окуу мүмкүн болбоду — кайра аракет кылыңыз же кол менен киргизиңиз',
  'Ombor qoldig‘i yetarli emas: {name} (qoldiq {qty})': 'Кампада калдык жетишсиз: {name} (калдык {qty})',
  'Yetarli qoldiq yo‘q: {name} (qoldiq: {qty})': 'Калдык жетишсиз: {name} (калдык: {qty})',
  '«{name}»: qabul qiluvchi filial qoldig‘i juda katta — miqdorni tekshiring':
      '«{name}»: алуучу филиалдагы калдык өтө чоң — санын текшериңиз',
  // ── Chek ──
  'Chek topilmadi': 'Чек табылган жок',
  'Qaytarish topilmadi': 'Кайтарым табылган жок',
  'Kompaniya chek shablonini faqat barcha filiallarga kirishi bor xodim o‘zgartiradi.':
      'Компаниянын чек шаблонун бардык филиалдарга кирүү укугу бар кызматкер гана өзгөртөт.',
  'Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting.':
      'Бул документтин түп нуска чеги мурунтан басылган — көчүрмөсүн басыңыз.',
  'Chop etish holati yakunlangan — o‘zgartirib bo‘lmaydi.': 'Басып чыгаруу абалы аяктаган — өзгөртүүгө болбойт.',
  'Chop etish so‘rovi noto‘g‘ri.': 'Басып чыгаруу сурамы туура эмес.',
  'Bu chek hozir boshqa qurilmada chop etilmoqda — nusxa chop eting.':
      'Бул чек азыр башка түзмөктө басылып жатат — көчүрмөсүн басыңыз.',
  // ── Partiyalar (kod bo'yicha) ──
  'Partiya bo‘yicha kuzatiladigan mahsulot uchun har qatorga partiyalarni kiriting.':
      'Партия боюнча эсептелген товар үчүн ар бир сапка партияларды киргизиңиз.',
  'Bu mahsulot partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.':
      'Бул товар партия боюнча эсептелбейт — партия киргизүүгө болбойт.',
  'Partiyalar yig‘indisi qator miqdoriga teng emas.': 'Партиялардын суммасы саптын санына барабар эмес.',
  'Miqdor 0,001 aniqlikda kiritiladi — uchtadan ortiq kasr xona bo‘lmasin.':
      'Саны 0,001 тактык менен киргизилет — үтүрдөн кийин үчтөн ашык орун болбосун.',
  'Bu mahsulot muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.':
      'Бул товардын мөөнөтү көзөмөлдөнөт — ар бир партияга жарамдуулук мөөнөтүн киргизиңиз.',
  'Bu mahsulot muddat bo‘yicha kuzatilmaydi — muddat kiritib bo‘lmaydi.':
      'Бул товардын мөөнөтү көзөмөлдөнбөйт — мөөнөт киргизүүгө болбойт.',
  'Muddati o‘tgan tovar qabul qilinmaydi — muddat bugungi ish kunidan oldin.':
      'Мөөнөтү өткөн товар кабыл алынбайт — мөөнөт бүгүнкү иш күнүнөн мурун.',
  'Filial vaqt zonasi tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.':
      'Филиалдын убакыт алкагы ырасталган эмес — мөөнөттүү партияларды жазууга болбойт. Администратор алкакты ырастасын.',
  'Tanlangan partiya yaroqsiz (boshqa mahsulot yoki filialga tegishli yoki yopilgan). Ro‘yxatni yangilab, qayta tanlang.':
      'Тандалган партия жараксыз (башка товарга же филиалга тиешелүү же жабылган). Тизмени жаңыртып, кайра тандаңыз.',
  'Partiyada yetarli qoldiq yo‘q — miqdorni kamaytiring yoki ro‘yxatni yangilang.':
      'Партияда калдык жетишсиз — санын азайтыңыз же тизмени жаңыртыңыз.',
  'Partiyalar bo‘yicha sanoq yig‘indisi umumiy sanoqqa teng emas.':
      'Партиялар боюнча эсептин суммасы жалпы эсепке барабар эмес.',
  'Partiya bo‘yicha kuzatiladigan mahsulotni filiallararo ko‘chirib bo‘lmaydi.':
      'Партия боюнча эсептелген товарды филиалдар ортосунда которууга болбойт.',
  'Partiya va qoldiq mos kelmadi — amal BAJARILMADI. Qo‘llab-quvvatlashga murojaat qiling.':
      'Партиялар жана калдык дал келген жок — амал АТКАРЫЛГАН ЖОК. Колдоо кызматына кайрылыңыз.',
  'Qaytarish partiya chegarasidan oshardi — amal bajarilmadi.':
      'Кайтарым партиянын чегинен ашып кетмек — амал аткарылган жок.',
  'Partiya tannarxi mos kelmadi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Партиянын өздүк наркы дал келген жок — амал аткарылган жок. Колдоо кызматына кайрылыңыз.',
  'Bu tovar partiya hisobi yoqilishidan oldin sotilgan — omborga qaytarmasdan qaytaring.':
      'Бул товар партиялык эсеп күйгүзүлгөнгө чейин сатылган — кампага кайтарбай кайтарым жасаңыз.',
  'Qarzni yopib bo‘lmadi — partiya va qoldiq mos kelmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Карызды жабуу мүмкүн болбоду — партиялар жана калдык дал келген жок. Колдоо кызматына кайрылыңыз.',
  'Server partiya hisobiga hali tayyor emas — administratorga xabar bering.':
      'Сервер партиялык эсепке азырынча даяр эмес — администраторго кабарлаңыз.',
  // ── Partiyalar (matn bo'yicha) ──
  'Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko‘rsatib bo‘lmaydi':
      'Бул товарда партиялык эсеп күйгүзүлгөн эмес — партияны көрсөтүүгө болбойт',
  'Partiyali mahsulot uchun partiyalarni aniq ko‘rsating — tizim qaysi partiya chiqarilayotganini taxmin qilmaydi.':
      'Партиялык товар үчүн партияларды так көрсөтүңүз — система кайсы партия чыгарылып жатканын болжолдобойт.',
  'Partiyali mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga taqsimlamaydi.':
      'Партиялык товарда партияларды санаңыз — жалпы айырманы система партияларга бөлүштүрбөйт.',
  'Yangi partiya miqdori noldan katta bo‘lsin.': 'Жаңы партиянын саны нөлдөн чоң болсун.',
  'Yangi partiya tannarxi manfiy bo‘lishi mumkin emas.': 'Жаңы партиянын өздүк наркы терс боло албайт.',
  'Bitta mahsulot bir sanoqda ikki marta bo‘lmasin': 'Бир товар бир эсепте эки жолу болбосун',
  'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Эсептен чыгаруу мүмкүн болбоду — партиялар жана калдык дал келген жок. Амал АТКАРЫЛГАН ЖОК; колдоо кызматына кайрылыңыз.',
  'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Инвентаризацияны жазуу мүмкүн болбоду — партиялар жана калдык дал келген жок. Амал АТКАРЫЛГАН ЖОК; колдоо кызматына кайрылыңыз.',
  'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.':
      'Эсептен чыгаруу мүмкүн болбоду — партиялар жана калдык дал келбей калмак. Амал аткарылган жок.',
  'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.':
      'Инвентаризацияны жазуу мүмкүн болбоду — партиялар жана калдык дал келбей калмак. Амал аткарылган жок.',
  'Partiya topilmadi': 'Партия табылган жок',
  'Filial vaqt zonasi o‘rnatilmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani sozlasin.':
      'Филиалдын убакыт алкагы орнотулган эмес — мөөнөттүү партияларды жазууга болбойт. Администратор алкакты жөндөсүн.',
  'Partiya ikki marta ko‘rsatilgan': 'Партия эки жолу көрсөтүлгөн',
  'Partiya ikki marta sanalgan': 'Партия эки жолу саналган',
  'Partiya miqdori noldan katta bo‘lsin': 'Партиянын саны нөлдөн чоң болсун',
  'Sanoq manfiy bo‘lishi mumkin emas': 'Эсеп терс боло албайт',
  'Partiya boshqa mahsulot yoki filialga tegishli — ro‘yxatni yangilang':
      'Партия башка товарга же филиалга тиешелүү — тизмени жаңыртыңыз',
  'Partiya holati «{status}» — undan miqdor ayirib bo‘lmaydi': 'Партиянын абалы «{status}» — андан сан кемитүүгө болбойт',
  'Partiya holati «{status}» — uni sanab bo‘lmaydi': 'Партиянын абалы «{status}» — аны санаганга болбойт',
  'Partiyada yetarli qoldiq yo‘q ({have} < {need})': 'Партияда калдык жетишсиз ({have} < {need})',
  'Partiyalar yig‘indisi ({sum}) umumiy miqdorga ({total}) teng emas — qaysi partiya ekanini ko‘rsating.':
      'Партиялардын суммасы ({sum}) жалпы санга ({total}) барабар эмес — кайсы партия экенин көрсөтүңүз.',
  'Partiyalar yig‘indisi ({sum}) umumiy sanoqqa ({total}) teng emas. Sanalmagan partiyalar o‘zgarmaydi ({untouched}).':
      'Партиялардын суммасы ({sum}) жалпы эсепке ({total}) барабар эмес. Саналбаган партиялар өзгөрбөйт ({untouched}).',
  '«{name}» muddat bo‘yicha kuzatiladi — yangi partiyaga yaroqlilik muddatini kiriting.':
      '«{name}» мөөнөт боюнча көзөмөлдөнөт — жаңы партияга жарамдуулук мөөнөтүн киргизиңиз.',
  '«{name}» partiya bo‘yicha kuzatiladi — har kirim qatoriga partiyalarni kiriting.':
      '«{name}» партия боюнча эсептелет — ар бир кириш сабына партияларды киргизиңиз.',
  '«{name}» partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.':
      '«{name}» партия боюнча эсептелбейт — партия киргизүүгө болбойт.',
  '«{name}» muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.':
      '«{name}» мөөнөт боюнча көзөмөлдөнөт — ар бир партияга жарамдуулук мөөнөтүн киргизиңиз.',
  '«{name}» muddat bo‘yicha kuzatilmaydi — partiyaga muddat kiritib bo‘lmaydi.':
      '«{name}» мөөнөт боюнча көзөмөлдөнбөйт — партияга мөөнөт киргизүүгө болбойт.',
  '«{name}»: partiyalar yig‘indisi {sum} qator miqdori {total} ga teng emas.':
      '«{name}»: партиялардын суммасы {sum} саптын санына {total} барабар эмес.',
  '«{name}»: partiya miqdori noldan katta bo‘lsin': '«{name}»: партиянын саны нөлдөн чоң болсун',
  '«{name}»: miqdor {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.':
      '«{name}»: {qty} санында үтүрдөн кийин үчтөн ашык орун бар — саны 0,001 тактык менен киргизилет.',
  '«{name}»: partiya miqdori {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.':
      '«{name}»: партиянын {qty} санында үтүрдөн кийин үчтөн ашык орун бар — саны 0,001 тактык менен киргизилет.',
  '«{name}»: partiya tannarxi noma’lum — kirim narxini kiriting.':
      '«{name}»: партиянын өздүк наркы белгисиз — кириш баасын киргизиңиз.',
  '«{name}»: muddat {date} bugungi ish kunidan ({today}) oldin — muddati o‘tgan tovar qabul qilinmaydi.':
      '«{name}»: {date} мөөнөтү бүгүнкү иш күнүнөн ({today}) мурун — мөөнөтү өткөн товар кабыл алынбайт.',
  '«{name}» qatori summasi juda katta ({amount}) — miqdor yoki narxni tekshiring':
      '«{name}» сабынын суммасы өтө чоң ({amount}) — санын же баасын текшериңиз',
  '«{name}» partiya bo‘yicha kuzatiladi — kirim narxini tahrirlab bo‘lmaydi; tuzatish orqali o‘zgartiring.':
      '«{name}» партия боюнча эсептелет — кириш баасын түзөтүүгө болбойт; оңдоо аркылуу өзгөртүңүз.',
  'Filial vaqt zonasi ({tz}) tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.':
      'Филиалдын убакыт алкагы ({tz}) ырасталган эмес — мөөнөттүү партияларды жазууга болбойт. Администратор алкакты ырастасын.',
  'Vaqt zonasi «{tz}» tanilmagan — administratorga xabar bering.':
      '«{tz}» убакыт алкагы таанылган жок — администраторго кабарлаңыз.',
  'Bu amal partiya bo‘yicha kuzatiladigan mahsulotni qo‘llab-quvvatlamaydi ({n} ta mahsulot).':
      'Бул амал партия боюнча эсептелген товарды колдобойт ({n} товар).',
  'Noma’lum filtr qiymati: {value}': 'Белгисиз чыпка мааниси: {value}',
  'Bir so‘rovda {n} ta partiya qatori — chegara {max}. Sanoqni bir necha qismga bo‘lib yuboring.':
      'Бир сурамда {n} партия сабы — чеги {max}. Эсепти бир нече бөлүккө бөлүп жөнөтүңүз.',
  // ── Qabulni tuzatish ──
  'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun.':
      'Бул кабыл алуу партия түзгөн эмес — оңдоо партиялык кабыл алуу үчүн гана.',
  'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun. Hujjatni oddiy kirim tahriri bilan o‘zgartiring.':
      'Бул кабыл алуу партия түзгөн эмес — оңдоо партиялык кабыл алуу үчүн гана. Документти кадимки кириш түзөтүүсү менен өзгөртүңүз.',
  'Partiyadan tovar allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.':
      'Партиядан товар мурунтан кыймылдаган — анын номерин, мөөнөтүн жана баасын оңдоого болбойт; санын гана кайтарууга болот.',
  'Qaytarilayotgan miqdor partiya qoldig‘idan katta.': 'Кайтарылып жаткан сан партиянын калдыгынан чоң.',
  'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.':
      'Товарда жабыла элек партиялык карыз бар — адегенде карызды партияга байлаңыз.',
  'Kassa yozuvini yozib bo‘lmadi — tuzatish BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Кассага жазуу мүмкүн болбоду — оңдоо ЖОККО ЧЫГАРЫЛДЫ. Колдоо кызматына кайрылыңыз.',
  'Bu so‘rov avval boshqa mazmun bilan yuborilgan. Hujjatni yangilab, tuzatishni qayta yuboring.':
      'Бул сурам мурун башка мазмун менен жөнөтүлгөн. Документти жаңыртып, оңдоону кайра жөнөтүңүз.',
  'Hujjat tuzatilgan — uni faqat yangi tuzatish orqali o‘zgartirish mumkin.':
      'Документ оңдолгон — аны жаңы оңдоо аркылуу гана өзгөртүүгө болот.',
  'Tuzatish so‘rovi yakunlanmagan — qayta urinib ko‘ring': 'Оңдоо сурамы аяктаган жок — кайра аракет кылыңыз',
  'Tuzatishni yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.':
      'Оңдоону жазуу мүмкүн болбоду — партиялар жана калдык дал келген жок. Амал АТКАРЫЛГАН ЖОК; колдоо кызматына кайрылыңыз.',
  'Xarid filiali o‘chirilgan — tuzatib bo‘lmaydi': 'Сатып алуу филиалы өчүрүлгөн — оңдоого болбойт',
  'Tuzatish hujjat jamini manfiy qilardi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.':
      'Оңдоо документтин жыйынтыгын терс кылмак — амал аткарылган жок. Колдоо кызматына кайрылыңыз.',
  'Kamida bitta qator kerak': 'Жок дегенде бир сап керек',
  'Qator tannarxi manfiy bo‘lishi mumkin emas': 'Саптын өздүк наркы терс боло албайт',
  'Qator topilmadi': 'Сап табылган жок',
  'Bu hujjatga bog‘langan qabul yo‘q — tuzatish faqat qabul hujjati orqali bajariladi.':
      'Бул документке байланган кабыл алуу жок — оңдоо кабыл алуу документи аркылуу гана аткарылат.',
  'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang, keyin bu qatorni tuzating.':
      'Товарда жабыла элек партиялык карыз бар — адегенде карызды партияга байлап, анан бул сапты оңдоңуз.',
  'Qaytarilgan summa juda katta — miqdor yoki narxni tekshiring':
      'Кайтарылган сумма өтө чоң — санын же баасын текшериңиз',
  'Almashtirilgan summa juda katta — miqdor yoki narxni tekshiring':
      'Алмаштырылган сумма өтө чоң — санын же баасын текшериңиз',
  'Tuzatish summasi juda katta — miqdor yoki narxni tekshiring': 'Оңдоо суммасы өтө чоң — санын же баасын текшериңиз',
  'Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring':
      'Документтин жалпы суммасы өтө чоң — санын же баасын текшериңиз',
  'Summa juda katta — miqdor yoki narxni tekshiring': 'Сумма өтө чоң — санын же баасын текшериңиз',
  'Tuzatish sababi {min}–{max} belgidan iborat bo‘lsin.': 'Оңдоонун себеби {min}–{max} белгиден турушу керек.',
  'Bir so‘rovda {n} ta qator — chegara {max}. Tuzatishni bir necha qismga bo‘lib yuboring.':
      'Бир сурамда {n} сап — чеги {max}. Оңдоону бир нече бөлүккө бөлүп жөнөтүңүз.',
  'Bitta qatorda {n} tadan ortiq partiya — tuzatishni bo‘lib yuboring.':
      'Бир сапта {n} ашык партия — оңдоону бөлүп жөнөтүңүз.',
  'Qator ikki marta ko‘rsatilgan': 'Сап эки жолу көрсөтүлгөн',
  'Qatorda na qaytarish, na almashtirish bor': 'Сапта кайтаруу да, алмаштыруу да жок',
  'Almashtiriladigan partiya bor, lekin qator tannarxi kiritilmagan.':
      'Алмаштыруучу партия бар, бирок саптын өздүк наркы киргизилген жок.',
  'Tannarxni partiyasiz tuzatib bo‘lmaydi — eski partiyani qaytarib, yangisini kiriting.':
      'Өздүк наркты партиясыз оңдоого болбойт — эски партияны кайтарып, жаңысын киргизиңиз.',
  'Partiya bu qabulga tegishli emas': 'Партия бул кабыл алууга тиешелүү эмес',
  '«{name}»: qoldiq qatori topilmadi — tuzatib bo‘lmaydi': '«{name}»: калдык сабы табылган жок — оңдоого болбойт',
  '«{name}»: partiyada {left} qoldi, {qty} qaytarilmoqda — partiya manfiyga tushmaydi.':
      '«{name}»: партияда {left} калды, {qty} кайтарылып жатат — партия терске түшпөйт.',
  '«{name}»: partiyadan {qty} allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.':
      '«{name}»: партиядан {qty} мурунтан кыймылдаган — анын номерин, мөөнөтүн жана баасын оңдоого болбойт; санын гана кайтарууга болот.',
  '«{name}»: yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.':
      '«{name}»: жабыла элек партиялык карыз бар — адегенде карызды партияга байлаңыз.',
  // ── Naqd (kassa) ──
  'Naqd amal uchun pul manbaini (kassa yoki seyf) tanlang. Kassirda ochiq smena bo‘lsa, manba o‘sha smenaning kassasi bo‘ladi.':
      'Накталай амал үчүн акча булагын (касса же сейф) тандаңыз. Кассирде ачык смена болсо, булак ошол сменанын кассасы болот.',
  'Naqd hisob bu amalga to‘g‘ri kelmaydi: u faol emas yoki boshqa filialga tegishli. Ochiq smenangiz boshqa filialda bo‘lsa — smenani yoping yoki hujjatni o‘sha filial xodimi rasmiylashtirsin.':
      'Акча эсеби бул амалга туура келбейт: ал активдүү эмес же башка филиалга тиешелүү. Ачык сменаңыз башка филиалда болсо — сменаны жабыңыз же документти ошол филиалдын кызматкери тариздесин.',
  'Naqd hisobi vaqtincha ishlamayapti — amal BAJARILMADI. Administratorga xabar bering.':
      'Накталай эсеби убактылуу иштебей жатат — амал АТКАРЫЛГАН ЖОК. Администраторго кабарлаңыз.',
  'Kassa tanlanmagan. Smenani aniq kassa tanlab oching.': 'Касса тандалган жок. Сменаны так кассаны тандап ачыңыз.',
  'Kassa yaroqsiz (faol emas yoki boshqa filialga tegishli).':
      'Касса жараксыз (активдүү эмес же башка филиалга тиешелүү).',
  'Bu amal ochiq smena kassasiga mos emas. Smena o‘rtasida kassa almashtirilmaydi.':
      'Бул амал ачык сменанын кассасына туура келбейт. Сменанын ортосунда касса алмаштырылбайт.',
  'Smena eski usulda (kassasiz) ochilgan. Uni yopib, kassa tanlab yangi smena oching.':
      'Смена эски ыкма менен (кассасыз) ачылган. Аны жаап, кассаны тандап жаңы смена ачыңыз.',
  'Bu amal yopilgan smenaga tegishli — avtomatik qabul qilinmaydi. Administrator tekshirsin.':
      'Бул амал жабылган сменага тиешелүү — автоматтык түрдө кабыл алынбайт. Администратор текшерсин.',
  'Naqd hisob holatini aniqlab bo‘lmadi — amal to‘xtatildi. Ilovani yangilang yoki administratorga xabar bering.':
      'Акча эсебинин абалын аныктоо мүмкүн болбоду — амал токтотулду. Тиркемени жаңыртыңыз же администраторго кабарлаңыз.',
  'Bu naqd amal uchun kassada ochiq smena kerak — avval smenani oching.':
      'Бул накталай амал үчүн кассада ачык смена керек — адегенде сменаны ачыңыз.',
  'Kassa amali yozilmadi. Qayta urinib ko‘ring; takrorlansa administratorga xabar bering.':
      'Касса амалы жазылган жок. Кайра аракет кылыңыз; кайталанса администраторго кабарлаңыз.',
  'Amal kassani manfiyga tushiradi — administrator tasdig‘i kerak.':
      'Амал кассаны терске түшүрөт — администратордун ырастоосу керек.',
  'Naqd hisob arxivlangan — boshqa hisobni tanlang.': 'Акча эсеби архивде — башка эсепти тандаңыз.',
  'Naqd hisob topilmadi — ro‘yxatni yangilang.': 'Акча эсеби табылган жок — тизмени жаңыртыңыз.',
  'Hisob valyutasi amal valyutasiga mos emas.': 'Эсептин валютасы амалдын валютасына дал келбейт.',
  'Smena ochiq emas.': 'Смена ачык эмес.',
  'Bu naqd amal uchun ruxsatingiz yo‘q.': 'Бул накталай амалга уруксатыңыз жок.',
  // ── Naqd posting (CashError, qo'shimcha) ──
  'Naqd hisob bu do‘konga tegishli emas — ro‘yxatni yangilang.':
      'Акча эсеби бул дүкөнгө тиешелүү эмес — тизмени жаңыртыңыз.',
  'Amal vaqti noto‘g‘ri — telefondagi sana va vaqtni tekshiring.':
      'Амалдын убактысы туура эмес — телефондогу дата менен убакытты текшериңиз.',
  'Smena topilmadi — ma’lumotlarni yangilang.': 'Смена табылган жок — маалыматтарды жаңыртыңыз.',
  'Smena tanlangan kassaga tegishli emas.': 'Смена тандалган кассага тиешелүү эмес.',
  'Bu naqd amal allaqachon bekor qilingan.': 'Бул накталай амал мурунтан жокко чыгарылган.',
  'Bu naqd amalni bekor qilib bo‘lmaydi.': 'Бул накталай амалды жокко чыгарууга болбойт.',
  'Pul o‘tkazmasi noto‘g‘ri — manba va qabul qiluvchi hisobni tekshiring.':
      'Акча которуу туура эмес — булак жана алуучу эсепти текшериңиз.',
  'Bu amal uchun bunday turdagi naqd hisobni ishlatib bo‘lmaydi.':
      'Бул амал үчүн мындай түрдөгү акча эсебин колдонууга болбойт.',
  'Naqd amal ma’lumotlari noto‘g‘ri — summani tekshiring.': 'Накталай амалдын маалыматтары туура эмес — сумманы текшериңиз.',
  'Bu naqd amal allaqachon yozilgan — ro‘yxatni yangilang.': 'Бул накталай амал мурунтан жазылган — тизмени жаңыртыңыз.',
  // ── Umumiy validatsiya ──
  'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456': 'Телефон номери туура эмес. Мисалы: +996 700 123 456',
  'So‘rov bo‘sh — qidiruv matnini kiriting.': 'Суроо бош — издөө текстин киргизиңиз.',
  '{field} kiritilishi kerak': 'Толтуруу керек: {field}',
  'Mijoz nomi': 'Кардардын аты',
  'Ism': 'Аты',
  'Kategoriya nomi': 'Категориянын аталышы',
  'Yetkazib beruvchi nomi': 'Жеткирүүчүнүн аталышы',
  // ── O'z paroli (POST /auth/password) va parol siyosati ──
  'Joriy parol (yoki PIN) noto‘g‘ri.': 'Учурдагы сырсөз (же PIN) туура эмес.',
  'Parolni o‘zingiz o‘rnata olmaysiz — administratorga murojaat qiling.':
      'Сырсөздү өзүңүз орното албайсыз — администраторго кайрылыңыз.',
  'Parol o‘rnatish uchun avval telefon (login) qo‘shilishi kerak.':
      'Сырсөз орнотуу үчүн адегенде телефон (логин) кошулушу керек.',
  'Bu telefon raqami boshqa akkauntda band.': 'Бул телефон номери башка аккаунтта колдонулууда.',
  'Parol juda qisqa — kamida {n} belgi kerak.': 'Сырсөз өтө кыска — кеминде {n} белги керек.',
  'Parol juda uzun.': 'Сырсөз өтө узун.',
  'Parol juda oddiy — boshqa parol tanlang.': 'Сырсөз өтө жөнөкөй — башка сырсөз тандаңыз.',
  'Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.':
      'Сырсөздө кайталанган белгилер көп — башка сырсөз тандаңыз.',
  'Yangi parolni kiriting.': 'Жаңы сырсөздү киргизиңиз.',
  'Parol qabul qilinmadi — boshqa parol tanlang.': 'Сырсөз кабыл алынган жок — башка сырсөз тандаңыз.',
};
