// Naqd (cash ledger) xatolari — QO'LDA yuritiladi.
//
// NEGA ALOHIDA FAYL: `serverErrors.ts` AVTO-GENERATSIYA qilinadi (sarlavhasida "qo'lda
// tahrirlamang" deb yozilgan) va uning generatori repoda yo'q. Naqd xatolari kod-prefiksli
// (`CASH_CUSTODY_...: matn`) bo'lgani uchun ular avto-lug'atdagi ANIQ MATN qidiruviga tushmaydi.
// Shu bois ular shu yerda, PREFIKS bo'yicha tarjima qilinadi va avto-generatsiya fayliga
// TEGILMAYDI (qayta generatsiya bu tarjimalarni o'chirmaydi).
//
// Tarjimasiz nima bo'lardi: kirill/rus tilidagi do'kon egasi lotin-o'zbekcha texnik matn
// ko'rardi — masalan "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: 'debt_payment': T0'dan
// keyin naqd manbai/manzili AYNAN ko'rsatilishi SHART". Bu do'kon egasi uchun tushunarsiz.

import { useLang } from "@/store/lang";

interface Tr { ru: string; uzc: string; uz: string }

// Kod -> odam tilida tushunarli xabar (SABABI + NIMA QILISH kerakligi).
const CASH: Record<string, Tr> = {
  // ⚠️  MATN OPERATOR QILA OLADIGAN ISHNI AYTSIN (Phase 5E). Ilgari bu yerda «smena
  //     ochilsin» deyilardi — menejer stol ortida smena ocha OLMAYDI va bu maslahat
  //     uni boshi berk ko'chaga olib borardi. Endi ekran naqd hisobni TANLASH
  //     imkonini beradi, matn esa aynan shuni aytadi.
  CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: {
    uz: "Naqd amal uchun pul manbaini (kassa yoki seyf) tanlang. Kassirda ochiq smena bo'lsa, manba o'sha smenaning kassasi bo'ladi.",
    ru: "Для наличной операции выберите источник денег (касса или сейф). Если у кассира открыта смена, источником будет касса этой смены.",
    uzc: "Нақд амал учун пул манбаини (касса ёки сейф) танланг. Кассирда очиқ смена бўлса, манба ўша сменанинг кассаси бўлади.",
  },
  // ⚠️  IKKI HOLATNI QOPLAYDI: operator TANLAGAN hisob yaroqsiz bo'lsa ham, ochiq
  //     smenaning kassasi hujjat FILIALIGA to'g'ri kelmasa ham shu kod keladi —
  //     matn ikkinchisini ham tushuntirsin, aks holda «men hech narsa tanlamadim-ku»
  //     degan savol javobsiz qolardi.
  CASH_CUSTODY_ACCOUNT_INVALID: {
    uz: "Naqd hisob bu amalga to'g'ri kelmaydi: u faol emas, boshqa filialga yoki boshqa do'konga tegishli. Ochiq smenangiz boshqa filialda bo'lsa — smenani yoping yoki hujjatni o'sha filial xodimi tuzatsin.",
    ru: "Денежный счёт не подходит для этой операции: он неактивен, относится к другому филиалу или магазину. Если ваша открытая смена в другом филиале — закройте смену или пусть документ исправит сотрудник того филиала.",
    uzc: "Нақд ҳисоб бу амалга тўғри келмайди: у фаол эмас, бошқа филиалга ёки бошқа дўконга тегишли. Очиқ сменангиз бошқа филиалда бўлса — сменани ёпинг ёки ҳужжатни ўша филиал ходими тузатсин.",
  },
  // ── Phase 1: SEYF ochilish qoldig'i ────────────────────────────────────────
  SAFE_OPENING_REQUIRED: {
    uz: "Seyf ishga tayyor emas: ochilish qoldig'i tasdiqlanmagan. Menejer jismoniy sanoqni kiritsin — noma'lum qoldiq NOL deb olinmaydi.",
    ru: "Сейф не готов к работе: начальный остаток не подтверждён. Пусть менеджер внесёт фактический пересчёт — неизвестный остаток не считается нулём.",
    uzc: "Сейф ишга тайёр эмас: очилиш қолдиғи тасдиқланмаган. Менежер жисмоний саноқни киритсин — номаълум қолдиқ НОЛ деб олинмайди.",
  },
  SAFE_OPENING_CONFLICT: {
    uz: "Bu seyf uchun ochilish qoldig'i allaqachon tasdiqlangan va mazmuni boshqa. Ochilishni tahrirlash mumkin emas.",
    ru: "Начальный остаток этого сейфа уже подтверждён, и данные отличаются. Изменить его нельзя.",
    uzc: "Бу сейф учун очилиш қолдиғи аллақачон тасдиқланган ва мазмуни бошқа. Уни таҳрирлаш мумкин эмас.",
  },
  SAFE_OPENING_BLOCKED_BY_HISTORY: {
    uz: "Seyfda kassa harakati bor, ochilish qoldig'i esa tasdiqlanmagan. Buni keyin kiritish mavjud tarixni buzardi — administratorga murojaat qiling.",
    ru: "По сейфу уже есть движения, а начальный остаток не подтверждён. Внести его задним числом нельзя — обратитесь к администратору.",
    uzc: "Сейфда касса ҳаракати бор, очилиш қолдиғи эса тасдиқланмаган. Буни кейин киритиш мавжуд тарихни бузарди — администраторга мурожаат қилинг.",
  },
  CASH_LEDGER_UNAVAILABLE: {
    uz: "Naqd hisobi vaqtincha ishlamayapti — amal BAJARILMADI (pul hisobsiz qolmasligi uchun). Administratorga xabar bering.",
    ru: "Учёт наличных временно недоступен — операция НЕ выполнена (чтобы деньги не остались без учёта). Сообщите администратору.",
    uzc: "Нақд ҳисоби вақтинча ишламаяпти — амал БАЖАРИЛМАДИ (пул ҳисобсиз қолмаслиги учун). Администраторга хабар беринг.",
  },
  TILL_REQUIRED_AFTER_CUTOVER: {
    uz: "Kassa (TILL) tanlanmagan. Smenani aynan kassa tanlab oching.",
    ru: "Касса (TILL) не выбрана. Откройте смену, выбрав конкретную кассу.",
    uzc: "Касса (TILL) танланмаган. Сменани айнан касса танлаб очинг.",
  },
  TILL_INVALID_AFTER_CUTOVER: {
    uz: "Kassa yaroqsiz (faol emas yoki boshqa filialga tegishli).",
    ru: "Касса недействительна (неактивна или относится к другому филиалу).",
    uzc: "Касса яроқсиз (фаол эмас ёки бошқа филиалга тегишли).",
  },
  TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER: {
    uz: "Bu amal ochiq smena kassasiga mos emas. Smena o'rtasida kassa almashtirilmaydi.",
    ru: "Операция не соответствует кассе открытой смены. Касса не меняется в середине смены.",
    uzc: "Бу амал очиқ смена кассасига мос эмас. Смена ўртасида касса алмаштирилмайди.",
  },
  LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER: {
    uz: "Bu smena eski (kassasiz) ochilgan. Uni yopib, kassa tanlab yangi smena oching.",
    ru: "Эта смена открыта по-старому (без кассы). Закройте её и откройте новую, выбрав кассу.",
    uzc: "Бу смена эски (кассасиз) очилган. Уни ёпиб, касса танлаб янги смена очинг.",
  },
  // P9/3A: savdo smenasi va so'rovdagi kassa ZID — naqd atribusiyasi aniqlanmadi, savdo
  // rad etildi (qisman yozuv YO'Q). Kassir buni o'zi tuzata olmaydi: smenani yopib,
  // to'g'ri kassa bilan yangi smena ochish kerak.
  SHIFT_NOT_BELONG_TO_ACCOUNT: {
    uz: "Smena va tanlangan kassa bir-biriga mos kelmadi — savdo yozilmadi. Smenani yopib, to'g'ri kassa bilan yangi smena oching.",
    ru: "Смена и выбранная касса не совпадают — продажа не записана. Закройте смену и откройте новую с правильной кассой.",
    uzc: "Смена ва танланган касса бир-бирига мос келмади — савдо ёзилмади. Сменани ёпиб, тўғри касса билан янги смена очинг.",
  },
  CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY: {
    uz: "Bu chek yopilgan smenaga tegishli — avtomatik qabul qilinmaydi. Administrator tekshirishi kerak.",
    ru: "Этот чек относится к закрытой смене — автоматически не принимается. Требуется проверка администратора.",
    uzc: "Бу чек ёпилган сменага тегишли — автоматик қабул қилинмайди. Администратор текшириши керак.",
  },
};

/** Naqd xato kodini foydalanuvchi tiliga o'giradi. Kod topilmasa `null` — chaqiruvchi
 *  odatiy (avto-generatsiya) lug'atga o'tadi. */
export function translateCashError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  // IKKI SHAKL keladi:
  //   1) `cutover_guard._fail` -> matn "KOD: batafsil texnik matn" (prefiksli);
  //   2) `CashPostingError` (posting qatlami) -> detail OBYEKT `{error, message}`, uni
  //      `api.ts` JSON.stringify qiladi. Ilgari FAQAT 1-shakl tushunilardi va posting
  //      qatlamining HAR xatosi kassirga XOM JSON bo'lib ko'rinardi.
  let code = msg.split(":", 1)[0].trim();
  if (msg.startsWith("{")) {
    try {
      const o = JSON.parse(msg) as { error?: unknown };
      if (typeof o?.error === "string") code = o.error;
    } catch { /* JSON emas — prefiks shakli bilan davom etamiz */ }
  }
  const tr = CASH[code];
  if (!tr) return null;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return tr.uz; }
  if (lang === "uzc") return tr.uzc;
  if (lang === "ru" || lang === "ky") return tr.ru;   // ky -> ru (Qirg'iziston)
  return tr.uz;
}
