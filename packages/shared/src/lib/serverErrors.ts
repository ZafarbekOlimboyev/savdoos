// AVTO-GENERATSIYA (scratchpad/gen_errors.mjs) — qo'lda tahrirlamang.
// Server (backend) xato xabarlari o'zbekcha (lotin) qaytadi. Bu modul ularni
// foydalanuvchi tiliga (ru/uzc) o'giradi. Backendga tegilmaydi — faqat ko'rsatishда tarjima.
// Til: ru->ruscha, uzc->kirill, ky->ruscha (Qirg'iziston uchun), uz->asl matn.
import { useLang } from "@/store/lang";

interface Tr { ru: string; uzc: string }

// Aniq (statik) xato matnlari
const STATIC: Record<string, Tr> = {
  "Sessiya tugadi — qayta kiring": { ru: "Сессия истекла — войдите снова", uzc: "Сессия тугади — қайта киринг" },
  "Server bilan aloqa yo'q": { ru: "Нет связи с сервером", uzc: "Сервер билан алоқа йўқ" },
  "Juda ko'p urinish — 5 daqiqadan keyin qayta urining": { ru: "Слишком много попыток — повторите через 5 минут", uzc: "Жуда кўп уриниш — 5 дақиқадан кейин қайта уриниб кўринг" },
  "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring": { ru: "Аккаунт временно заблокирован — попробуйте через 15 минут", uzc: "Ҳисоб вақтинча блокланди — 15 дақиқадан кейин уриниб кўринг" },
  "Juda ko'p urinish — 15 daqiqadan keyin urinib ko'ring": { ru: "Слишком много попыток — попробуйте через 15 минут", uzc: "Жуда кўп уриниш — 15 дақиқадан кейин уриниб кўринг" },
  "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.": { ru: "Магазин временно приостановлен. Свяжитесь с нами.", uzc: "Дўкон вақтинча тўхтатилган. Биз билан боғланинг." },
  "Do'kon kodi topilmadi": { ru: "Код магазина не найден", uzc: "Дўкон коди топилмади" },
  "Do'kon kodi kerak (company_code)": { ru: "Нужен код магазина", uzc: "Дўкон коди керак" },
  "Do'kon topilmadi": { ru: "Магазин не найден", uzc: "Дўкон топилмади" },
  "PIN noto'g'ri": { ru: "Неверный PIN", uzc: "PIN нотўғри" },
  "Telefon yoki parol noto'g'ri": { ru: "Неверный телефон или пароль", uzc: "Телефон ёки парол нотўғри" },
  "Yangi parol kamida 6 belgi bo'lishi kerak": { ru: "Новый пароль должен содержать не менее 6 символов", uzc: "Янги парол камида 6 та белги бўлиши керак" },
  "Joriy parol noto'g'ri": { ru: "Текущий пароль неверный", uzc: "Жорий парол нотўғри" },
  "Avtorizatsiya talab qilinadi": { ru: "Требуется авторизация", uzc: "Авторизация талаб қилинади" },
  "Xodim faol emas": { ru: "Сотрудник неактивен", uzc: "Ходим фаол эмас" },
  "Tarifni o'zgartirib bo'lmaydi — provayder bilan bog'laning": { ru: "Тариф изменить нельзя — свяжитесь с нами", uzc: "Тарифни ўзгартириб бўлмайди — биз билан боғланинг" },
  "Kassa band — qayta urinib ko'ring": { ru: "Касса занята — попробуйте ещё раз", uzc: "Касса банд — қайта уриниб кўринг" },
  "Savat bo'sh": { ru: "Корзина пуста", uzc: "Сават бўш" },
  "Mijoz topilmadi": { ru: "Клиент не найден", uzc: "Мижоз топилмади" },
  "Filial topilmadi": { ru: "Филиал не найден", uzc: "Филиал топилмади" },
  "Ochiq smena yo'q — avval smenani oching": { ru: "Нет открытой смены — сначала откройте смену", uzc: "Очиқ смена йўқ — аввал сменани очинг" },
  "Miqdor noto'g'ri": { ru: "Неверное количество", uzc: "Миқдор нотўғри" },
  "Chegirma mahsulot summasidan oshdi": { ru: "Скидка превысила сумму товара", uzc: "Чегирма маҳсулот суммасидан ошди" },
  "Chegirma jami summadan oshib ketdi": { ru: "Скидка превысила итоговую сумму", uzc: "Чегирма жами суммадан ошиб кетди" },
  "Bo'sh chek uchun to'lov bo'lmaydi": { ru: "Нельзя оплатить пустой чек", uzc: "Бўш чек учун тўлов бўлмайди" },
  "Berilgan summa yetarli emas": { ru: "Внесённая сумма недостаточна", uzc: "Берилган сумма етарли эмас" },
  "Nasiya uchun mijoz tanlanishi shart": { ru: "Для продажи в долг нужно выбрать клиента", uzc: "Насия учун мижоз танланиши шарт" },
  "Bo'sh so'rov": { ru: "Пустой запрос", uzc: "Бўш сўров" },
  "Chek topilmadi": { ru: "Чек не найден", uzc: "Чек топилмади" },
  "Qaytarish uchun mahsulot tanlanmagan": { ru: "Для возврата не выбран товар", uzc: "Қайтариш учун маҳсулот танланмаган" },
  "Qaytarish miqdori noto'g'ri": { ru: "Неверное количество возврата", uzc: "Қайтариш миқдори нотўғри" },
  "Asl chek topilmadi": { ru: "Исходный чек не найден", uzc: "Асл чек топилмади" },
  "Mahsulot bu chekda yo'q": { ru: "Товара нет в этом чеке", uzc: "Маҳсулот бу чекда йўқ" },
  "Ochiq smena yo'q — avval kassada smena oching": { ru: "Нет открытой смены — сначала откройте смену на кассе", uzc: "Очиқ смена йўқ — аввал кассада смена очинг" },
  "Bir xil filial tanlandi": { ru: "Выбран один и тот же филиал", uzc: "Бир хил филиал танланди" },
  "Kamida bitta mahsulot kerak": { ru: "Нужен хотя бы один товар", uzc: "Камида битта маҳсулот керак" },
  "PLU kodi band": { ru: "Код PLU занят", uzc: "PLU коди банд" },
  "Noto'g'ri o'lchov birligi": { ru: "Неверная единица измерения", uzc: "Нотўғри ўлчов бирлиги" },
  "Mahsulot topilmadi": { ru: "Товар не найден", uzc: "Маҳсулот топилмади" },
  "Kategoriya topilmadi": { ru: "Категория не найдена", uzc: "Категория топилмади" },
  "Yetkazib beruvchi topilmadi": { ru: "Поставщик не найден", uzc: "Етказиб берувчи топилмади" },
  "Mahsulot yoki yangi nom kerak": { ru: "Нужен товар или новое название", uzc: "Маҳсулот ёки янги ном керак" },
  "Kirim topilmadi": { ru: "Приход не найден", uzc: "Кирим топилмади" },
  "Qator topilmadi": { ru: "Строка не найдена", uzc: "Қатор топилмади" },
  "Bu yetkazib beruvchiga qarz yo'q": { ru: "У этого поставщика нет долга", uzc: "Бу етказиб берувчига қарз йўқ" },
  "Qarzi bor mijozni o'chirib bo'lmaydi": { ru: "Нельзя удалить клиента с долгом", uzc: "Қарзи бор мижозни ўчириб бўлмайди" },
  "Summa noto'g'ri": { ru: "Неверная сумма", uzc: "Сумма нотўғри" },
  "Qarz yo'q": { ru: "Нет долга", uzc: "Қарз йўқ" },
  "Filial nomi kerak": { ru: "Введите название филиала", uzc: "Филиал номи керак" },
  "Filial ID noto'g'ri": { ru: "Неверный ID филиала", uzc: "Филиал ID нотўғри" },
  "Rol topilmadi": { ru: "Роль не найдена", uzc: "Роль топилмади" },
  "Administrator akkauntini faqat administrator yarata oladi": { ru: "Аккаунт администратора может создать только администратор", uzc: "Администратор аккаунтини фақат администратор ярата олади" },
  "Parol kamida 6 belgi bo'lishi kerak": { ru: "Пароль должен содержать не менее 6 символов", uzc: "Парол камида 6 та белгидан иборат бўлиши керак" },
  "Parolli xodim uchun telefon (login) kerak": { ru: "Для сотрудника с паролем нужен телефон (логин)", uzc: "Паролли ходим учун телефон (логин) керак" },
  "Bu telefon allaqachon band": { ru: "Этот телефон уже занят", uzc: "Бу телефон аллақачон банд" },
  "Xodim topilmadi": { ru: "Сотрудник не найден", uzc: "Ходим топилмади" },
  "Administrator akkauntini faqat administrator tahrirlaydi": { ru: "Аккаунт администратора может редактировать только администратор", uzc: "Администратор аккаунтини фақат администратор таҳрирлайди" },
  "Administrator rolini faqat administrator biriktiradi": { ru: "Роль администратора может назначить только администратор", uzc: "Администратор ролини фақат администратор бириктиради" },
  "Status noto'g'ri": { ru: "Неверный статус", uzc: "Статус нотўғри" },
  "O'zingizni o'chira olmaysiz": { ru: "Вы не можете удалить самого себя", uzc: "Ўзингизни ўчира олмайсиз" },
  "Administrator akkauntini faqat administrator o'chira oladi": { ru: "Аккаунт администратора может удалить только администратор", uzc: "Администратор аккаунтини фақат администратор ўчира олади" },
  "Ruxsatlarni faqat administrator o'zgartira oladi": { ru: "Права может изменять только администратор", uzc: "Рухсатларни фақат администратор ўзгартира олади" },
  "Smena topilmadi": { ru: "Смена не найдена", uzc: "Смена топилмади" },
  "Ochiq smena topilmadi": { ru: "Открытая смена не найдена", uzc: "Очиқ смена топилмади" },
  "Noto'g'ri tur": { ru: "Неверный тип", uzc: "Нотўғри тур" },
  "Ochiq smena allaqachon mavjud": { ru: "Открытая смена уже существует", uzc: "Очиқ смена аллақачон мавжуд" },
  "Smena allaqachon yopilgan": { ru: "Смена уже закрыта", uzc: "Смена аллақачон ёпилган" },
  "Tarozi topilmadi": { ru: "Весы не найдены", uzc: "Тарози топилмади" },
  "Noto'g'ri holat": { ru: "Неверный статус", uzc: "Нотўғри ҳолат" },
};

// Dinamik (o'zgaruvchi qismli) xatolar — regex + $1,$2 shablon
const DYNAMIC: { re: RegExp; ru: string; uzc: string }[] = [
  { re: /^To'lovlar yig'indisi \((.+)\) jami summaga \((.+)\) teng emas$/, ru: "Сумма платежей ($1) не равна итоговой сумме ($2)", uzc: "Тўловлар йиғиндиси ($1) жами суммага ($2) тенг эмас" },
  { re: /^Qaytarish miqdori sotilganidan oshiq \(qoldi: (.+)\)$/, ru: "Количество возврата превышает проданное (осталось: $1)", uzc: "Қайтариш миқдори сотилганидан ошиқ (қолди: $1)" },
  { re: /^PLU (\S+) band \((.+)\) — boshqa PLU kiriting: (.+)$/, ru: "PLU $1 занят ($2) — введите другой PLU: $3", uzc: "PLU $1 банд ($2) — бошқа PLU киритинг: $3" },
  { re: /Ombor qoldig'i yetarli emas: (.+) \(qoldiq (.+)\)/, ru: "Недостаточно остатка на складе: $1 (остаток $2)", uzc: "Омбор қолдиғи етарли эмас: $1 (қолдиқ $2)" },
  { re: /^Yetarli qoldiq yo'q: (.+) \(qoldiq: (.+)\)$/, ru: "Недостаточно остатка: $1 (остаток: $2)", uzc: "Етарли қолдиқ йўқ: $1 (қолдиқ: $2)" },
  { re: /^PLU faqat raqam bo'lishi kerak: (.+)$/, ru: "PLU должен состоять только из цифр: $1", uzc: "PLU фақат рақамдан иборат бўлиши керак: $1" },
  { re: /^Noto'g'ri qaytarish sababi: (.+)$/, ru: "Неверная причина возврата: $1", uzc: "Нотўғри қайтариш сабаби: $1" },
  { re: /^Barcode allaqachon mavjud: (.+)$/, ru: "Штрих-код уже существует: $1", uzc: "Штрих-код аллақачон мавжуд: $1" },
  { re: /^PLU kodi band: (\S+) \((.+)\)$/, ru: "Код PLU занят: $1 ($2)", uzc: "PLU коди банд: $1 ($2)" },
  { re: /^Noto'g'ri to'lov usuli: (.+)$/, ru: "Неверный способ оплаты: $1", uzc: "Нотўғри тўлов усули: $1" },
  { re: /Noto'g'ri to'lov usuli: (.+)/, ru: "Неверный способ оплаты: $1", uzc: "Нотўғри тўлов усули: $1" },
  { re: /^Filial topilmadi \((.+)\)$/, ru: "Филиал не найден ($1)", uzc: "Филиал топилмади ($1)" },
  { re: /^Mahsulot topilmadi: (.+)$/, ru: "Товар не найден: $1", uzc: "Маҳсулот топилмади: $1" },
  { re: /Mahsulot topilmadi: (.+)/, ru: "Товар не найден: $1", uzc: "Маҳсулот топилмади: $1" },
  { re: /^PLU kodi band: (\S+)$/, ru: "Код PLU занят: $1", uzc: "PLU коди банд: $1" },
  { re: /^Artikul band: (.+)$/, ru: "Артикул занят: $1", uzc: "Артикул банд: $1" },
  { re: /^Ruxsat yo'q: (.+)$/, ru: "Нет доступа: $1", uzc: "Рухсат йўқ: $1" },
];

/** Server xato matnini joriy foydalanuvchi tiliga o'giradi. Topilmasa — asl matn. */
export function translateServerError(msg: string): string {
  if (!msg || typeof msg !== "string") return msg;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return msg; }
  // asl o'zbekcha — tarjima shart emas, faqat "provayder/vendor" -> "biz" (bosh harf saqlanadi)
  if (lang === "uz") return msg
    .replace(/(Provayder|Vendor) bilan bog'laning/g, "Biz bilan bog'laning")
    .replace(/(provayder|vendor) bilan bog'laning/g, "biz bilan bog'laning");
  const pick = (t: Tr) => (lang === "uzc" ? t.uzc : t.ru); // ky -> ru

  const s = STATIC[msg];
  if (s) return pick(s);

  for (const d of DYNAMIC) {
    const m = msg.match(d.re);
    if (m) {
      const tpl = lang === "uzc" ? d.uzc : d.ru;
      return tpl.replace(/\$(\d)/g, (_, i) => m[+i] ?? "");
    }
  }
  return msg; // lug'atda yo'q — asl matnni ko'rsatamiz
}
