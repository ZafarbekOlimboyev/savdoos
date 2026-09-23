// Paket M5 (qobiq, filial, ruxsatlar, sozlamalar) tarjimalari.
//
// SHAKL (yadro bilan kelishilgan, o'zgartirmang):
//   * kalit — `tr('...')` ga beriladigan O'ZBEK LOTIN manba matni (aynan o'sha satr);
//   * `ruShell` — ruscha, `kyShell` — qirg'izcha tarjima; uzc (kirill) avtomatik;
//   * har kalit IKKALA xaritada bo'lishi SHART, boshqa manbadagi ayni kalit bilan
//     tarjima bir xil bo'lsin — `test/core_l10n_test.dart` ikkalasini tekshiradi;
//   * o'rinbosar `{nom}` shaklida (`trArgs`), transliteratsiyada saqlanadi.
//
// `lib/l10n.dart` bu xaritalarni birlashtiradi — l10n.dart ga TEGMANG.
//
// Ikki qism: (1) M5 ekranlarining o'z matnlari; (2) SERVER matnlari (xodimlarni
// boshqarish va kirish cheklovlari) — `apps/server/app/api/v1/employees.py`,
// `core/ratelimit.py` dagi matnlar AYNAN (ASCII apostrof bilan): `userMessage`
// ularni `tr(matn)` orqali tarjima qiladi. Server matni o'zgarsa bu yerda ham
// yangilang (`test/shell_l10n_test.dart` asosiylarini tekshiradi).

/// M5 (qobiq, filial, ruxsatlar, sozlamalar): ruscha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> ruShell = {
  // ── Qobiq / filial ──
  'Barcha filiallar': 'Все филиалы',
  'Asosiy filial': 'Основной филиал',
  'Filial haqida': 'О филиале',
  'Siz «{current}» filiali ma’lumotlarini ko‘ryapsiz. Tovar qabul va kassa amallari asosiy filialingizga — «{actor}» — yoziladi.':
      'Вы просматриваете данные филиала «{current}». Приёмка товара и кассовые операции записываются в ваш основной филиал — «{actor}».',
  '«{actor}» filialiga qaytish': 'Вернуться в филиал «{actor}»',
  'Tovar qabul va kassa amallari shu filialga yoziladi': 'Приёмка товара и кассовые операции записываются в этот филиал',
  // ── Sozlamalar ──
  'Ish joyi': 'Рабочее место',
  'Umumiy': 'Общие',
  'Biznes sanasi': 'Рабочая дата',
  'Mening ruxsatlarim': 'Мои права',
  '{role} — barcha ruxsatlarga ega.': '{role} — все права.',
  'Sizga hech qanday ruxsat berilmagan.': 'Вам не назначено ни одного права.',
  'Ruxsatlarni ega yoki administrator o‘zgartiradi. O‘zgarish kuchga kirishi uchun «Ma’lumotlarni yangilash» ni bosing.':
      'Права меняет владелец или администратор. Чтобы изменения вступили в силу, нажмите «Обновить данные».',
  'Ma’lumotlarni yangilash': 'Обновить данные',
  'Ma’lumotlar yangilandi': 'Данные обновлены',
  'Yangilanmoqda…': 'Обновляется…',
  'Server almashsa, hisobdan chiqasiz va qayta kirishingiz kerak bo‘ladi.':
      'При смене сервера вы выйдете из аккаунта и нужно будет войти заново.',
  'Server eski versiyada — filial va ruxsatlar kirishdagi holat bo‘yicha ko‘rsatilmoqda.':
      'Сервер старой версии — филиал и права показаны по состоянию на момент входа.',
  'Ilova qulfi (PIN) ham o‘chiriladi — keyingi kirishda yangidan o‘rnatiladi.':
      'Блокировка приложения (PIN) тоже будет удалена — при следующем входе её нужно будет установить заново.',
  'Xodim': 'Сотрудник',
  // ── Xodimlar ──
  'Hozircha xodim yo‘q': 'Сотрудников пока нет',
  'Xodim qo‘shish': 'Добавить сотрудника',
  'Mening kartam': 'Моя карточка',
  'Nofaol filial': 'Неактивный филиал',
  'Bu rolni tayinlash huquqingiz yo‘q': 'У вас нет права назначать эту роль',
  'O‘z rolingizni o‘zgartira olmaysiz': 'Нельзя изменить собственную роль',
  'O‘z holatingizni o‘zgartira olmaysiz': 'Нельзя изменить собственный статус',
  'Parolni o‘zgartirish': 'Сменить пароль',
  'O‘z parolingiz joriy parol bilan almashtiriladi': 'Свой пароль меняется с подтверждением текущего пароля',
  'Parolli xodim shu raqam bilan kiradi': 'Сотрудник с паролем входит по этому номеру',
  'Kamida {n} belgi': 'Не менее {n} символов',
  'Parol kamida {n} belgi bo‘lsin': 'Пароль — не менее {n} символов',
  'PIN (kassa uchun)': 'PIN (для кассы)',
  '4 ta raqam': '4 цифры',
  'PIN aynan 4 raqam bo‘lsin': 'PIN должен состоять ровно из 4 цифр',
  'Xodimni o‘chirish': 'Удалить сотрудника',
  'Xodim tizimga kira olmaydi; tarixdagi savdo va amallari saqlanadi.':
      'Сотрудник не сможет войти в систему; его продажи и операции в истории сохранятся.',
  'Administrator/Ega akkauntini faqat Ega boshqaradi': 'Аккаунтом администратора или владельца управляет только владелец',
  'Administrator/Ega akkauntini faqat Ega o‘chira oladi': 'Удалить аккаунт администратора или владельца может только владелец',
  'Tarif bo‘yicha xodimlar chegarasi: {n} ta. Ko‘proq xodim uchun tarifni oshiring.':
      'Лимит сотрудников по тарифу: {n}. Чтобы добавить больше, повысьте тариф.',
  'Parol juda qisqa — kamida {n} belgi kerak.': 'Пароль слишком короткий — нужно не менее {n} символов.',
  'Parol juda uzun.': 'Пароль слишком длинный.',
  'Parol juda oddiy — boshqa parol tanlang.': 'Пароль слишком простой — выберите другой.',
  'Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.':
      'В пароле слишком много повторяющихся символов — выберите другой.',

  // ── SERVER matnlari (AYNAN) ──
  'Parolli xodim uchun telefon (login) kerak': 'Для сотрудника с паролем нужен телефон (логин)',
  'Ega rolini faqat Ega tayinlaydi': 'Роль владельца назначает только владелец',
  "Administrator tayinlash huquqi yo'q — Ega bilan bog'laning": 'Нет права назначать администратора — обратитесь к владельцу',
  "O'z rolingizni yoki holatingizni o'zgartira olmaysiz": 'Нельзя изменить собственную роль или статус',
  "O'z darajangizdan yuqori rol tayinlay olmaysiz": 'Нельзя назначить роль выше вашей',
  "Oxirgi faol rahbarni (Ega/administrator) to'xtatib/o'zgartirib bo'lmaydi":
      'Нельзя остановить или понизить последнего активного руководителя (владельца или администратора)',
  "Oxirgi faol Egani pasaytirib/to'xtatib bo'lmaydi — avval boshqa Ega tayinlang":
      'Нельзя понизить или остановить последнего активного владельца — сначала назначьте другого владельца',
  "O'zingizni o'chira olmaysiz": 'Нельзя удалить самого себя',
  "Administrator/Ega akkauntini faqat Ega o'chira oladi": 'Удалить аккаунт администратора или владельца может только владелец',
  "Oxirgi faol rahbarni (Ega/administrator) o'chirib bo'lmaydi":
      'Нельзя удалить последнего активного руководителя (владельца или администратора)',
  "Oxirgi faol Egani o'chirib bo'lmaydi — avval boshqa Ega tayinlang":
      'Нельзя удалить последнего активного владельца — сначала назначьте другого владельца',
  'Bu telefon allaqachon band': 'Этот телефон уже занят',
  "Bu PIN do'konda allaqachon ishlatilgan": 'Этот PIN уже используется в магазине',
  "PIN aynan 4 ta raqamdan iborat bo'lishi kerak": 'PIN должен состоять ровно из 4 цифр',
  "Telefon raqami noto'g'ri. Masalan: +996 700 123 456": 'Неверный номер телефона. Например: +996 700 123 456',
  "Parolli akkauntdan telefonni olib tashlab bo'lmaydi (telefon — login)":
      'Нельзя удалить телефон у аккаунта с паролем (телефон — это логин)',
  'Rol topilmadi': 'Роль не найдена',
  'Xodim topilmadi': 'Сотрудник не найден',
  'Xodimда ochiq smena bor — avval smenani yopish kerak': 'У сотрудника открыта смена — сначала закройте смену',
  "Status noto'g'ri": 'Неверный статус',
  "Ruxsatlarni faqat Ega yoki administrator o'zgartira oladi": 'Права может менять только владелец или администратор',
  "Administrator/Ega ruxsatlarини faqat Ega o'zgartiradi": 'Права администратора или владельца меняет только владелец',
  '"Admin qilish" huquqini faqat Ega beradi': 'Право «назначать администратора» даёт только владелец',
  "Parol kamida 6 belgi bo'lishi kerak": 'Пароль должен быть не короче 6 символов',
  "Filial ID noto'g'ri": 'Неверный филиал',
  'Filial nofaol — avval faollashtiring': 'Филиал неактивен — сначала активируйте его',
  'Ism kiritilishi kerak': 'Введите имя',
  "Juda ko'p urinish — 5 daqiqadan keyin qayta urining": 'Слишком много попыток — повторите через 5 минут',
  "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring": 'Аккаунт временно заблокирован — попробуйте через 15 минут',
  "Juda ko'p urinish — birozdan keyin qayta urining": 'Слишком много попыток — повторите чуть позже',
};

/// M5 (qobiq, filial, ruxsatlar, sozlamalar): qirg'izcha tarjimalar (kalit = o'zbek lotin matn).
const Map<String, String> kyShell = {
  // ── Qobiq / filial ──
  'Barcha filiallar': 'Бардык филиалдар',
  'Asosiy filial': 'Негизги филиал',
  'Filial haqida': 'Филиал жөнүндө',
  'Siz «{current}» filiali ma’lumotlarini ko‘ryapsiz. Tovar qabul va kassa amallari asosiy filialingizga — «{actor}» — yoziladi.':
      'Сиз «{current}» филиалынын маалыматтарын көрүп жатасыз. Товар кабыл алуу жана касса операциялары негизги филиалыңызга — «{actor}» — жазылат.',
  '«{actor}» filialiga qaytish': '«{actor}» филиалына кайтуу',
  'Tovar qabul va kassa amallari shu filialga yoziladi': 'Товар кабыл алуу жана касса операциялары ушул филиалга жазылат',
  // ── Sozlamalar ──
  'Ish joyi': 'Иш орду',
  'Umumiy': 'Жалпы',
  'Biznes sanasi': 'Иш күнү',
  'Mening ruxsatlarim': 'Менин уруксаттарым',
  '{role} — barcha ruxsatlarga ega.': '{role} — бардык уруксаттарга ээ.',
  'Sizga hech qanday ruxsat berilmagan.': 'Сизге эч кандай уруксат берилген эмес.',
  'Ruxsatlarni ega yoki administrator o‘zgartiradi. O‘zgarish kuchga kirishi uchun «Ma’lumotlarni yangilash» ni bosing.':
      'Уруксаттарды ээси же администратор өзгөртөт. Өзгөрүү күчүнө кириши үчүн «Маалыматтарды жаңыртуу» баскычын басыңыз.',
  'Ma’lumotlarni yangilash': 'Маалыматтарды жаңыртуу',
  'Ma’lumotlar yangilandi': 'Маалыматтар жаңыртылды',
  'Yangilanmoqda…': 'Жаңыртылууда…',
  'Server almashsa, hisobdan chiqasiz va qayta kirishingiz kerak bo‘ladi.':
      'Сервер алмашса, аккаунттан чыгасыз жана кайра кирүүгө туура келет.',
  'Server eski versiyada — filial va ruxsatlar kirishdagi holat bo‘yicha ko‘rsatilmoqda.':
      'Сервер эски версияда — филиал жана уруксаттар кирген кездеги абал боюнча көрсөтүлүүдө.',
  'Ilova qulfi (PIN) ham o‘chiriladi — keyingi kirishda yangidan o‘rnatiladi.':
      'Колдонмо кулпусу (PIN) да өчүрүлөт — кийинки киргенде кайра орнотулат.',
  'Xodim': 'Кызматкер',
  // ── Xodimlar ──
  'Hozircha xodim yo‘q': 'Азырынча кызматкер жок',
  'Xodim qo‘shish': 'Кызматкер кошуу',
  'Mening kartam': 'Менин картам',
  'Nofaol filial': 'Активдүү эмес филиал',
  'Bu rolni tayinlash huquqingiz yo‘q': 'Бул ролду дайындоого укугуңуз жок',
  'O‘z rolingizni o‘zgartira olmaysiz': 'Өз ролуңузду өзгөртө албайсыз',
  'O‘z holatingizni o‘zgartira olmaysiz': 'Өз абалыңызды өзгөртө албайсыз',
  'Parolni o‘zgartirish': 'Сырсөздү өзгөртүү',
  'O‘z parolingiz joriy parol bilan almashtiriladi': 'Өз сырсөзүңүз учурдагы сырсөз менен алмаштырылат',
  'Parolli xodim shu raqam bilan kiradi': 'Сырсөзү бар кызматкер ушул номер менен кирет',
  'Kamida {n} belgi': 'Кеминде {n} белги',
  'Parol kamida {n} belgi bo‘lsin': 'Сырсөз кеминде {n} белги болсун',
  'PIN (kassa uchun)': 'PIN (касса үчүн)',
  '4 ta raqam': '4 сан',
  'PIN aynan 4 raqam bo‘lsin': 'PIN так 4 сандан турушу керек',
  'Xodimni o‘chirish': 'Кызматкерди өчүрүү',
  'Xodim tizimga kira olmaydi; tarixdagi savdo va amallari saqlanadi.':
      'Кызматкер системага кире албайт; тарыхтагы сатуулары жана операциялары сакталат.',
  'Administrator/Ega akkauntini faqat Ega boshqaradi': 'Администратордун же ээнин аккаунтун ээси гана башкарат',
  'Administrator/Ega akkauntini faqat Ega o‘chira oladi': 'Администратордун же ээнин аккаунтун ээси гана өчүрө алат',
  'Tarif bo‘yicha xodimlar chegarasi: {n} ta. Ko‘proq xodim uchun tarifni oshiring.':
      'Тариф боюнча кызматкерлердин чеги: {n}. Көбүрөөк кызматкер үчүн тарифти жогорулатыңыз.',
  'Parol juda qisqa — kamida {n} belgi kerak.': 'Сырсөз өтө кыска — кеминде {n} белги керек.',
  'Parol juda uzun.': 'Сырсөз өтө узун.',
  'Parol juda oddiy — boshqa parol tanlang.': 'Сырсөз өтө жөнөкөй — башка сырсөз тандаңыз.',
  'Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.':
      'Сырсөздө кайталанган белгилер көп — башка сырсөз тандаңыз.',

  // ── SERVER matnlari (AYNAN) ──
  'Parolli xodim uchun telefon (login) kerak': 'Сырсөзү бар кызматкер үчүн телефон (логин) керек',
  'Ega rolini faqat Ega tayinlaydi': 'Ээ ролун ээси гана дайындайт',
  "Administrator tayinlash huquqi yo'q — Ega bilan bog'laning": 'Администратор дайындоого укук жок — ээси менен байланышыңыз',
  "O'z rolingizni yoki holatingizni o'zgartira olmaysiz": 'Өз ролуңузду же абалыңызды өзгөртө албайсыз',
  "O'z darajangizdan yuqori rol tayinlay olmaysiz": 'Өз деңгээлиңизден жогору ролду дайындай албайсыз',
  "Oxirgi faol rahbarni (Ega/administrator) to'xtatib/o'zgartirib bo'lmaydi":
      'Акыркы активдүү жетекчини (ээ же администратор) токтотууга же өзгөртүүгө болбойт',
  "Oxirgi faol Egani pasaytirib/to'xtatib bo'lmaydi — avval boshqa Ega tayinlang":
      'Акыркы активдүү ээни төмөндөтүүгө же токтотууга болбойт — адегенде башка ээни дайындаңыз',
  "O'zingizni o'chira olmaysiz": 'Өзүңүздү өчүрө албайсыз',
  "Administrator/Ega akkauntini faqat Ega o'chira oladi": 'Администратордун же ээнин аккаунтун ээси гана өчүрө алат',
  "Oxirgi faol rahbarni (Ega/administrator) o'chirib bo'lmaydi":
      'Акыркы активдүү жетекчини (ээ же администратор) өчүрүүгө болбойт',
  "Oxirgi faol Egani o'chirib bo'lmaydi — avval boshqa Ega tayinlang":
      'Акыркы активдүү ээни өчүрүүгө болбойт — адегенде башка ээни дайындаңыз',
  'Bu telefon allaqachon band': 'Бул телефон мурунтан эле колдонулууда',
  "Bu PIN do'konda allaqachon ishlatilgan": 'Бул PIN дүкөндө мурунтан эле колдонулууда',
  "PIN aynan 4 ta raqamdan iborat bo'lishi kerak": 'PIN так 4 сандан турушу керек',
  "Telefon raqami noto'g'ri. Masalan: +996 700 123 456": 'Телефон номери туура эмес. Мисалы: +996 700 123 456',
  "Parolli akkauntdan telefonni olib tashlab bo'lmaydi (telefon — login)":
      'Сырсөзү бар аккаунттан телефонду алып салууга болбойт (телефон — логин)',
  'Rol topilmadi': 'Роль табылган жок',
  'Xodim topilmadi': 'Кызматкер табылган жок',
  'Xodimда ochiq smena bor — avval smenani yopish kerak': 'Кызматкердин ачык сменасы бар — адегенде сменаны жабуу керек',
  "Status noto'g'ri": 'Абал туура эмес',
  "Ruxsatlarni faqat Ega yoki administrator o'zgartira oladi": 'Уруксаттарды ээси же администратор гана өзгөртө алат',
  "Administrator/Ega ruxsatlarини faqat Ega o'zgartiradi": 'Администратордун же ээнин уруксаттарын ээси гана өзгөртөт',
  '"Admin qilish" huquqini faqat Ega beradi': '«Администратор кылуу» укугун ээси гана берет',
  "Parol kamida 6 belgi bo'lishi kerak": 'Сырсөз кеминде 6 белгиден турушу керек',
  "Filial ID noto'g'ri": 'Филиал туура эмес',
  'Filial nofaol — avval faollashtiring': 'Филиал активдүү эмес — адегенде активдештириңиз',
  'Ism kiritilishi kerak': 'Атын киргизиңиз',
  "Juda ko'p urinish — 5 daqiqadan keyin qayta urining": 'Өтө көп аракет — 5 мүнөттөн кийин кайра аракет кылыңыз',
  "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring": 'Аккаунт убактылуу бөгөттөлдү — 15 мүнөттөн кийин аракет кылыңыз',
  "Juda ko'p urinish — birozdan keyin qayta urining": 'Өтө көп аракет — бир аздан кийин кайра аракет кылыңыз',
};
