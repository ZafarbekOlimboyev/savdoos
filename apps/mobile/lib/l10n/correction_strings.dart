// Paket M3 (qabulni tuzatish) tarjimalari.
//
// SHAKL (yadro bilan kelishilgan, o'zgartirmang):
//   * kalit — `tr('...')` ga beriladigan O'ZBEK LOTIN manba matni (aynan o'sha satr);
//   * `ruCorrection` — ruscha, `kyCorrection` — qirg'izcha tarjima; uzc (kirill) avtomatik;
//   * har kalit IKKALA xaritada bo'lishi SHART, boshqa manbadagi ayni kalit bilan
//     tarjima bir xil bo'lsin — `test/core_l10n_test.dart` ikkalasini tekshiradi;
//   * o'rinbosar `{nom}` shaklida (`trArgs`), transliteratsiyada saqlanadi.
//
// `lib/l10n.dart` bu xaritalarni birlashtiradi — l10n.dart ga TEGMANG.
//
// Umumiy so'zlar (Naqd, Qarzga, Filial, Hammasi, Chiqish, dona, Muddati o‘tgan,
// Yetkazib beruvchi, Filial: {name}) asosiy/yadro lug'atidan olinadi — bu yerda
// TAKRORLANMAYDI (ikki manbada ikki xil tarjima bo'lib qolmasin).

/// M3 (qabulni tuzatish): ruscha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> ruCorrection = {
  // ── Birliklar (desktop `unit.*` bilan bir xil) ──
  'kg': 'кг',
  'litr': 'л',
  'upak': 'уп',
  // ── Hujjat ekrani ──
  'Kirim hujjati': 'Документ прихода',
  'Holat: qabul qilingan': 'Статус: принят',
  'Holat: to‘lanmagan': 'Статус: не оплачен',
  'Holat: qisman to‘langan': 'Статус: частично оплачен',
  'Holat: bekor qilingan': 'Статус: отменён',
  'Holat: {s}': 'Статус: {s}',
  'Hujjat sanasi': 'Дата документа',
  'Hujjat jami': 'Итог документа',
  'To‘langan summa': 'Оплаченная сумма',
  'Hujjat qatorlari': 'Строки документа',
  'Partiya hisobida': 'Учёт по партиям',
  'Muddat hisobida': 'Учёт сроков годности',
  'Raqamsiz partiya': 'Партия без номера',
  'Qabul: {r} · Qoldiq: {q} · Ketgan: {c}': 'Принято: {r} · Остаток: {q} · Ушло: {c}',
  'Bu partiyadan tovar ketgan — raqami, muddati va tannarxi tuzatilmaydi; faqat miqdorni teskari qilish mumkin':
      'Из этой партии уже ушёл товар — её номер, срок и себестоимость исправить нельзя; можно отменить только количество',
  'Bu hujjatdagi tuzatishlar': 'Исправления по этому документу',
  'Tuzatish yoki bekor qilish': 'Исправить или отменить',
  'Bu hujjatni tuzatib bo‘lmaydi': 'Этот документ нельзя исправить',
  'Tuzatish yozildi: hujjat jami {delta} ga o‘zgardi': 'Исправление записано: итог документа изменился на {delta}',
  'Bu tuzatish avval yozilgan — qayta qo‘llanmadi.': 'Это исправление уже было записано — повторно не применено.',
  'Bu tuzatish avval yozilgan — hujjat allaqachon bekor qilingan.':
      'Это исправление уже было записано — документ уже отменён.',
  'Hujjat bekor qilindi': 'Документ отменён',
  // ── Tuzatish ekrani ──
  'Qabulni tuzatish': 'Исправление прихода',
  'Qator tahrirlanmaydi: ortiqcha yozilgan miqdor partiyadan teskari qilinadi, kerak bo‘lsa o‘rniga yangi partiya yoziladi.':
      'Строка не редактируется: лишнее количество отменяется из партии, при необходимости вместо него записывается новая партия.',
  'Tuzatish sababi': 'Причина исправления',
  'Nima xato bo‘lgan?': 'Что было не так?',
  'Sababni yozing (3–300 belgi) — tuzatish izsiz qolmaydi':
      'Укажите причину (3–300 символов) — исправление не остаётся без следа',
  'Butun hujjatni teskari qilish': 'Отменить весь документ',
  'Teskari qilinadigan miqdor': 'Отменяемое количество',
  'Partiya qoldig‘i: {q}': 'Остаток партии: {q}',
  'Qoldiqdan ko‘p — partiyada {q} qolgan': 'Больше остатка — в партии осталось {q}',
  'Hujjat narxi: {s}': 'Цена в документе: {s}',
  'teskari qilinadi: {n}': 'отменяется: {n}',
  'Bu qatorni tuzatib bo‘lmaydi': 'Эту строку нельзя исправить',
  'O‘rniga yangi partiya yozish': 'Записать новую партию вместо неё',
  'O‘rniga qo‘yish yopiq: teskari qilinayotgan partiyadan tovar allaqachon ketgan':
      'Замена недоступна: из отменяемой партии товар уже ушёл',
  'O‘rniga qo‘yiladigan miqdor': 'Количество замены',
  'Yangi tannarx (birlik uchun)': 'Новая себестоимость (за единицу)',
  'Yangi tannarxni kiriting (0 dan katta)': 'Укажите новую себестоимость (больше 0)',
  'Yangi partiyalar': 'Новые партии',
  'Bu hujjatda tuzatiladigan partiya yo‘q': 'В этом документе нет партий для исправления',
  'Teskari': 'Отменено',
  'O‘rniga': 'Замена',
  'Yangi jami': 'Новый итог',
  'Bu tuzatish hujjatni to‘liq bekor qiladi': 'Это исправление полностью отменит документ',
  'Tuzatishni yozish': 'Записать исправление',
  'Hujjatni bekor qilish': 'Отменить документ',
  'Tuzatish yozilsinmi?': 'Записать исправление?',
  'Hujjat BEKOR qilinadi': 'Документ будет ОТМЕНЁН',
  'Tuzatish — o‘zgarmas hodisa: uni o‘chirib bo‘lmaydi, faqat yangi tuzatish bilan to‘g‘rilanadi.':
      'Исправление — неизменяемое событие: его нельзя удалить, только поправить новым исправлением.',
  'Butun qabul teskari qilinadi: qoldiq kamayadi va hujjat bekor bo‘ladi.':
      'Весь приход будет отменён: остаток уменьшится, документ станет отменённым.',
  'Hujjat jami: {old} → {next}': 'Итог документа: {old} → {next}',
  'Kassaga qaytadi: {s}': 'Вернётся в кассу: {s}',
  'Kassadan chiqadi: {s}': 'Выйдет из кассы: {s}',
  'Yetkazib beruvchi qarzi o‘zgaradi: {s}': 'Долг поставщику изменится на {s}',
  'Hisob: {code}': 'Счёт: {code}',
  'Qoldiq va partiyalar darhol o‘zgaradi.': 'Остаток и партии изменятся сразу.',
  'Tahrirga qaytish': 'Вернуться к редактированию',
  'Tuzatish yozilmadi': 'Исправление не записано',
  'Kiritilgan ma’lumotlar yo‘qoladi. Chiqasizmi?': 'Введённые данные будут потеряны. Выйти?',
  'Natija noma’lum: aynan shu tuzatishni qayta yuboring — server uni ikki marta yozmaydi.':
      'Результат неизвестен: отправьте это же исправление ещё раз — сервер не запишет его дважды.',
  // ── Kassa to'sig'i ──
  'Pul qaysi kassa yoki seyf orqali o‘tishini tanlang — server buni taxmin qilmaydi':
      'Выберите, через какую кассу или сейф проходят деньги — сервер этого не угадывает',
  'Bu tuzatish pulni siljitadi, lekin uni hozir yozib bo‘lmaydi: {reason}':
      'Это исправление двигает деньги, но записать его сейчас нельзя: {reason}',
  // ── Tekshiruv xabarlari ──
  'Hech narsa tanlanmagan — teskari qilinadigan miqdor kiriting yoki yangi partiya qo‘shing':
      'Ничего не выбрано — укажите отменяемое количество или добавьте новую партию',
  '«{name}»: teskari qilinadigan miqdor noto‘g‘ri': '«{name}»: неверное отменяемое количество',
  '«{name}»: miqdor partiya qoldig‘idan katta — partiya manfiyga tushmaydi':
      '«{name}»: количество больше остатка партии — партия не уходит в минус',
  '«{name}»: o‘rniga qo‘yish yopiq — teskari qilinayotgan partiyadan tovar allaqachon ketgan':
      '«{name}»: замена недоступна — из отменяемой партии товар уже ушёл',
  '«{name}»: o‘rniga qo‘yiladigan miqdorni kiriting': '«{name}»: укажите количество замены',
  '«{name}»: yangi partiyalar yig‘indisi o‘rniga qo‘yiladigan miqdorga teng emas':
      '«{name}»: сумма новых партий не равна количеству замены',
  '«{name}»: yangi partiyaga yaroqlilik muddatini kiriting': '«{name}»: укажите срок годности новой партии',
  '«{name}»: muddat ish kunidan ({d}) oldin bo‘lmasin': '«{name}»: срок не может быть раньше рабочего дня ({d})',
  '«{name}»: ko‘pi bilan {n} ta partiya': '«{name}»: не более {n} партий',
  '«{name}»: yangi partiya miqdorini tekshiring': '«{name}»: проверьте количество новой партии',
  '«{name}»: yangi partiya tannarxini kiriting — u taxmin qilinmaydi':
      '«{name}»: укажите себестоимость новой партии — она не угадывается',
};

/// M3 (qabulni tuzatish): qirg'izcha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> kyCorrection = {
  // ── Birliklar ──
  'kg': 'кг',
  'litr': 'л',
  'upak': 'упак',
  // ── Hujjat ekrani ──
  'Kirim hujjati': 'Кириш документи',
  'Holat: qabul qilingan': 'Абалы: кабыл алынган',
  'Holat: to‘lanmagan': 'Абалы: төлөнгөн эмес',
  'Holat: qisman to‘langan': 'Абалы: жарым-жартылай төлөнгөн',
  'Holat: bekor qilingan': 'Абалы: жокко чыгарылган',
  'Holat: {s}': 'Абалы: {s}',
  'Hujjat sanasi': 'Документтин күнү',
  'Hujjat jami': 'Документтин жыйынтыгы',
  'To‘langan summa': 'Төлөнгөн сумма',
  'Hujjat qatorlari': 'Документтин саптары',
  'Partiya hisobida': 'Партия боюнча эсеп',
  'Muddat hisobida': 'Мөөнөт боюнча эсеп',
  'Raqamsiz partiya': 'Номерсиз партия',
  'Qabul: {r} · Qoldiq: {q} · Ketgan: {c}': 'Кабыл алынды: {r} · Калдык: {q} · Кеткени: {c}',
  'Bu partiyadan tovar ketgan — raqami, muddati va tannarxi tuzatilmaydi; faqat miqdorni teskari qilish mumkin':
      'Бул партиядан товар кеткен — анын номерин, мөөнөтүн жана өздүк наркын оңдоого болбойт; санын гана жокко чыгарууга болот',
  'Bu hujjatdagi tuzatishlar': 'Бул документтеги оңдоолор',
  'Tuzatish yoki bekor qilish': 'Оңдоо же жокко чыгаруу',
  'Bu hujjatni tuzatib bo‘lmaydi': 'Бул документти оңдоого болбойт',
  'Tuzatish yozildi: hujjat jami {delta} ga o‘zgardi': 'Оңдоо жазылды: документтин жыйынтыгы {delta} өзгөрдү',
  'Bu tuzatish avval yozilgan — qayta qo‘llanmadi.': 'Бул оңдоо мурун жазылган — кайра колдонулган жок.',
  'Bu tuzatish avval yozilgan — hujjat allaqachon bekor qilingan.':
      'Бул оңдоо мурун жазылган — документ мурунтан жокко чыгарылган.',
  'Hujjat bekor qilindi': 'Документ жокко чыгарылды',
  // ── Tuzatish ekrani ──
  'Qabulni tuzatish': 'Кабыл алууну оңдоо',
  'Qator tahrirlanmaydi: ortiqcha yozilgan miqdor partiyadan teskari qilinadi, kerak bo‘lsa o‘rniga yangi partiya yoziladi.':
      'Сап түзөтүлбөйт: ашык жазылган сан партиядан жокко чыгарылат, керек болсо анын ордуна жаңы партия жазылат.',
  'Tuzatish sababi': 'Оңдоонун себеби',
  'Nima xato bo‘lgan?': 'Эмне туура эмес болгон?',
  'Sababni yozing (3–300 belgi) — tuzatish izsiz qolmaydi':
      'Себебин жазыңыз (3–300 белги) — оңдоо изсиз калбайт',
  'Butun hujjatni teskari qilish': 'Бүт документти жокко чыгаруу',
  'Teskari qilinadigan miqdor': 'Жокко чыгарылуучу сан',
  'Partiya qoldig‘i: {q}': 'Партиянын калдыгы: {q}',
  'Qoldiqdan ko‘p — partiyada {q} qolgan': 'Калдыктан көп — партияда {q} калган',
  'Hujjat narxi: {s}': 'Документтеги баа: {s}',
  'teskari qilinadi: {n}': 'жокко чыгарылат: {n}',
  'Bu qatorni tuzatib bo‘lmaydi': 'Бул сапты оңдоого болбойт',
  'O‘rniga yangi partiya yozish': 'Ордуна жаңы партия жазуу',
  'O‘rniga qo‘yish yopiq: teskari qilinayotgan partiyadan tovar allaqachon ketgan':
      'Алмаштыруу жабык: жокко чыгарылып жаткан партиядан товар мурунтан кеткен',
  'O‘rniga qo‘yiladigan miqdor': 'Алмаштыруучу сан',
  'Yangi tannarx (birlik uchun)': 'Жаңы өздүк нарк (бирдик үчүн)',
  'Yangi tannarxni kiriting (0 dan katta)': 'Жаңы өздүк наркты киргизиңиз (0дөн чоң)',
  'Yangi partiyalar': 'Жаңы партиялар',
  'Bu hujjatda tuzatiladigan partiya yo‘q': 'Бул документте оңдолуучу партия жок',
  'Teskari': 'Жокко чыгарылды',
  'O‘rniga': 'Алмаштыруу',
  'Yangi jami': 'Жаңы жыйынтык',
  'Bu tuzatish hujjatni to‘liq bekor qiladi': 'Бул оңдоо документти толугу менен жокко чыгарат',
  'Tuzatishni yozish': 'Оңдоону жазуу',
  'Hujjatni bekor qilish': 'Документти жокко чыгаруу',
  'Tuzatish yozilsinmi?': 'Оңдоо жазылсынбы?',
  'Hujjat BEKOR qilinadi': 'Документ ЖОККО ЧЫГАРЫЛАТ',
  'Tuzatish — o‘zgarmas hodisa: uni o‘chirib bo‘lmaydi, faqat yangi tuzatish bilan to‘g‘rilanadi.':
      'Оңдоо — өзгөрбөс окуя: аны өчүрүүгө болбойт, жаңы оңдоо менен гана түзөтүлөт.',
  'Butun qabul teskari qilinadi: qoldiq kamayadi va hujjat bekor bo‘ladi.':
      'Бүт кабыл алуу жокко чыгарылат: калдык азаят жана документ жокко чыгарылат.',
  'Hujjat jami: {old} → {next}': 'Документтин жыйынтыгы: {old} → {next}',
  'Kassaga qaytadi: {s}': 'Кассага кайтат: {s}',
  'Kassadan chiqadi: {s}': 'Кассадан чыгат: {s}',
  'Yetkazib beruvchi qarzi o‘zgaradi: {s}': 'Жеткирүүчүгө карыз өзгөрөт: {s}',
  'Hisob: {code}': 'Эсеп: {code}',
  'Qoldiq va partiyalar darhol o‘zgaradi.': 'Калдык жана партиялар дароо өзгөрөт.',
  'Tahrirga qaytish': 'Түзөтүүгө кайтуу',
  'Tuzatish yozilmadi': 'Оңдоо жазылган жок',
  'Kiritilgan ma’lumotlar yo‘qoladi. Chiqasizmi?': 'Киргизилген маалыматтар жоголот. Чыгасызбы?',
  'Natija noma’lum: aynan shu tuzatishni qayta yuboring — server uni ikki marta yozmaydi.':
      'Натыйжа белгисиз: ушул эле оңдоону кайра жөнөтүңүз — сервер аны эки жолу жазбайт.',
  // ── Kassa to'sig'i ──
  'Pul qaysi kassa yoki seyf orqali o‘tishini tanlang — server buni taxmin qilmaydi':
      'Акча кайсы касса же сейф аркылуу өтөрүн тандаңыз — сервер муну божомолдобойт',
  'Bu tuzatish pulni siljitadi, lekin uni hozir yozib bo‘lmaydi: {reason}':
      'Бул оңдоо акчаны жылдырат, бирок аны азыр жазууга болбойт: {reason}',
  // ── Tekshiruv xabarlari ──
  'Hech narsa tanlanmagan — teskari qilinadigan miqdor kiriting yoki yangi partiya qo‘shing':
      'Эч нерсе тандалган жок — жокко чыгарылуучу санды киргизиңиз же жаңы партия кошуңуз',
  '«{name}»: teskari qilinadigan miqdor noto‘g‘ri': '«{name}»: жокко чыгарылуучу сан туура эмес',
  '«{name}»: miqdor partiya qoldig‘idan katta — partiya manfiyga tushmaydi':
      '«{name}»: сан партиянын калдыгынан чоң — партия терске түшпөйт',
  '«{name}»: o‘rniga qo‘yish yopiq — teskari qilinayotgan partiyadan tovar allaqachon ketgan':
      '«{name}»: алмаштыруу жабык — жокко чыгарылып жаткан партиядан товар мурунтан кеткен',
  '«{name}»: o‘rniga qo‘yiladigan miqdorni kiriting': '«{name}»: алмаштыруучу санды киргизиңиз',
  '«{name}»: yangi partiyalar yig‘indisi o‘rniga qo‘yiladigan miqdorga teng emas':
      '«{name}»: жаңы партиялардын суммасы алмаштыруучу санга барабар эмес',
  '«{name}»: yangi partiyaga yaroqlilik muddatini kiriting': '«{name}»: жаңы партияга жарактуулук мөөнөтүн киргизиңиз',
  '«{name}»: muddat ish kunidan ({d}) oldin bo‘lmasin': '«{name}»: мөөнөт иш күнүнөн ({d}) мурун болбошу керек',
  '«{name}»: ko‘pi bilan {n} ta partiya': '«{name}»: эң көп {n} партия',
  '«{name}»: yangi partiya miqdorini tekshiring': '«{name}»: жаңы партиянын санын текшериңиз',
  '«{name}»: yangi partiya tannarxini kiriting — u taxmin qilinmaydi':
      '«{name}»: жаңы партиянын өздүк наркын киргизиңиз — ал божомолдонбойт',
};
