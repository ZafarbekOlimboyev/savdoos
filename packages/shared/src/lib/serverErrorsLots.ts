// Partiya / muddat / inventarizatsiya xatolari — QO'LDA yuritiladi.
//
// NEGA ALOHIDA FAYL: `serverErrors.ts` AVTO-GENERATSIYA qilinadi va uning generatori
// repoda YO'Q (`serverErrorsCash.ts` sarlavhasida ham shu yozilgan). Phase 4B ekranlari
// ishlatadigan ~30 ta xato o'sha lug'atga tushmagan — ularsiz kirill/rus tilidagi do'kon
// egasi lotin-o'zbekcha texnik matn ko'rardi. Qayta generatsiya bu faylga TEGMAYDI.
//
// ⚠️  MATNLAR SERVER MATNIGA AYNAN MOS BO'LISHI SHART. Backend xabari o'zgarsa bu yerda
//     ham o'zgartiring — aks holda tarjima jimgina tushib qoladi (xato ko'rinaveradi,
//     faqat asl tilda). Shu bois `apps/server/tests/test_lot_error_texts.py` matnlarni
//     manba kodi bilan solishtirib turadi.
import { useLang } from "@/store/lang";

interface Tr { ru: string; uzc: string }

// Aniq (statik) matnlar
const STATIC: Record<string, Tr> = {
  "Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko'rsatib bo'lmaydi": {
    ru: "Для этого товара учёт партий не включён — партию указать нельзя",
    uzc: "Бу маҳсулотда партия кузатуви ёқилмаган — партия кўрсатиб бўлмайди",
  },
  "Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim qaysi jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.": {
    ru: "Для товара с учётом партий укажите партии ТОЧНО — система не угадывает, какая физическая партия списывается.",
    uzc: "Кузатувли маҳсулот учун партияларни АНИҚ кўрсатинг — тизим қайси жисмоний партия чиқарилаётганини ТАХМИН ҚИЛМАЙДИ.",
  },
  "Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga TAQSIMLAMAYDI.": {
    ru: "У товара с учётом партий пересчитайте партии — общую разницу система по партиям НЕ РАСПРЕДЕЛЯЕТ.",
    uzc: "Кузатувли маҳсулотда партияларни сананг — умумий фарқни тизим партияларга ТАҚСИМЛАМАЙДИ.",
  },
  "Yangi partiya miqdori musbat bo'lishi kerak.": {
    ru: "Количество новой партии должно быть положительным.",
    uzc: "Янги партия миқдори мусбат бўлиши керак.",
  },
  "Yangi partiya tannarxi manfiy bo'lishi mumkin emas.": {
    ru: "Себестоимость новой партии не может быть отрицательной.",
    uzc: "Янги партия таннархи манфий бўлиши мумкин эмас.",
  },
  "Mavjud qoldiq bor: `opening_lots` bering yoki `legacy_unit_cost` ni ANIQ ko'rsating. Mahsulotning joriy olish narxi JIMGINA ishlatilmaydi.": {
    ru: "Есть текущий остаток: передайте начальные партии или ТОЧНО укажите себестоимость остатка. Текущая закупочная цена товара молча не используется.",
    uzc: "Мавжуд қолдиқ бор: бошланғич партияларни беринг ёки таннархни АНИҚ кўрсатинг. Маҳсулотнинг жорий олиш нархи ЖИМГИНА ишлатилмайди.",
  },
  "Qarz topilmadi": { ru: "Долг не найден", uzc: "Қарз топилмади" },
  "Bitta mahsulot bir so'rovda IKKI MARTA sanalmaydi": {
    ru: "Один товар нельзя пересчитать дважды в одном запросе",
    uzc: "Битта маҳсулот бир сўровда ИККИ МАРТА саналмайди",
  },
  "Hisobdan chiqarib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Списать не удалось — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Ҳисобдан чиқариб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Inventarizatsiyani yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Пересчёт не записан — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Инвентаризацияни ёзиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Kuzatuvni yoqib bo'lmadi — qoldiq va partiyalar mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Не удалось включить учёт — остаток и партии не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Кузатувни ёқиб бўлмади — қолдиқ ва партиялар мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Qaytarishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Возврат не записан — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Қайтаришни ёзиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. Qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Партии и остаток не сходятся — приход ОТМЕНЁН. Обратитесь в поддержку.",
    uzc: "Партия ва қолдиқ мос келмади — кирим БЕКОР қилинди. Қўллаб-қувватлашга мурожаат қилинг.",
  },
  // ── SOTUV VA QARZNI YOPISH DARVOZALARI (`services/sales.py`, `services/lot_resolution.py`) ──
  // ⚠️  Ilgari bu ikki darvoza xom istisno matnini (UUID, `≠`, `[SQL: …]`) uzatardi va
  //     lug'atda yo'q edi. Qaysi darvoza ekanini `X-Error-Code` aytadi — matn emas.
  "Savdoni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Продажа не записана — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Савдони ёзиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Qarzni yopib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.": {
    ru: "Долг не закрыт — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.",
    uzc: "Қарзни ёпиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.",
  },
  "Yuborilgan TILL ochiq smena kassasiga mos emas — kassani server aniqlaydi": {
    ru: "Переданная касса не совпадает с кассой открытой смены — кассу определяет сервер",
    uzc: "Юборилган касса очиқ смена кассасига мос эмас — кассани сервер аниқлайди",
  },
  "Qabul hujjati band — qayta urinib ko'ring": {
    ru: "Документ прихода занят — попробуйте ещё раз",
    uzc: "Қабул ҳужжати банд — қайта уриниб кўринг",
  },
  "Qabul topilmadi": { ru: "Приход не найден", uzc: "Қабул топилмади" },
  "filial topilmadi": { ru: "филиал не найден", uzc: "филиал топилмади" },
  "filial vaqt zonasi o'rnatilmagan. Muddat kuzatuvi BIZNES sanasiga tayanadi; zonasiz bir kunlik xato muddati o'tgan tovarni yaroqli ko'rsatishi mumkin.": {
    ru: "часовой пояс филиала не задан. Учёт срока опирается на бизнес-дату; без пояса ошибка в один день может показать просроченный товар годным.",
    uzc: "филиал вақт зонаси ўрнатилмаган. Муддат кузатуви БИЗНЕС санасига таянади; зонасиз бир кунлик хато муддати ўтган товарни яроқли кўрсатиши мумкин.",
  },

  "Partiya topilmadi": { ru: "Партия не найдена", uzc: "Партия топилмади" },

  // ── AKTIVATSIYADAN OLDINGI CHEKNI QAYTARISH (B3, `services/lot_return.py`) ──
  // ⚠️  Restock'siz qaytarish RUXSAT etiladi — bu matn FAQAT omborga qaytarishda
  //     chiqadi (`X-Error-Code: LOT_RETURN_PRE_ACTIVATION`).
  "Bu mahsulot partiya kuzatuvi yoqilishidan OLDIN sotilgan — tovar qaysi partiyadan chiqqani NOMA'LUM va tizim uni taxmin qilmaydi. Omborga qaytarmasdan (restock'siz) qaytaring.": {
    ru: "Этот товар продан ДО включения учёта партий — из какой партии он ушёл, НЕИЗВЕСТНО, и система это не угадывает. Оформите возврат без возврата на склад.",
    uzc: "Бу маҳсулот партия кузатуви ёқилишидан ОЛДИН сотилган — товар қайси партиядан чиққани НОМАЪЛУМ ва тизим уни тахмин қилмайди. Омборга қайтармасдан қайтаринг.",
  },

  // ── KUZATUVNI YOQISH DARVOZASI: BAZA TAYYOR EMAS (`X-Error-Code: LOT_SCHEMA_NOT_READY`) ──
  // ⚠️  Sxema YAXLITLIGI matni (FK/cheklov soni bilan) avto-generatsiya lug'atida
  //     (`serverErrors.ts`) — u o'zgarmadi. Bu esa idempotentlik indekslari va uuid
  //     ustun tipi uchun YANGI, sonsiz matn.
  "Partiya kuzatuvini yoqib bo'lmaydi — server sxemasi to'liq tayyor emas (idempotentlik yoki ustun tipi). Avval /health/ready yashil bo'lsin.": {
    ru: "Нельзя включить учёт партий — схема сервера готова не полностью (идемпотентность или тип столбца). Сначала /health/ready должен быть зелёным.",
    uzc: "Партия кузатувини ёқиб бўлмайди — сервер схемаси тўлиқ тайёр эмас (идемпотентлик ёки устун типи). Аввал /health/ready яшил бўлсин.",
  },
};

// Dinamik matnlar ($1, $2 — regex guruhlari)
const DYNAMIC: { re: RegExp; ru: string; uzc: string }[] = [
  { re: /^Partiya ikki marta ko'rsatilgan: (.+)$/, ru: "Партия указана дважды: $1", uzc: "Партия икки марта кўрсатилган: $1" },
  { re: /^Partiya ikki marta sanalgan: (.+)$/, ru: "Партия пересчитана дважды: $1", uzc: "Партия икки марта саналган: $1" },
  { re: /^Partiya miqdori musbat bo'lishi kerak: (.+)$/, ru: "Количество партии должно быть положительным: $1", uzc: "Партия миқдори мусбат бўлиши керак: $1" },
  { re: /^Sanoq manfiy bo'lishi mumkin emas: (.+)$/, ru: "Пересчёт не может быть отрицательным: $1", uzc: "Саноқ манфий бўлиши мумкин эмас: $1" },
  { re: /^Partiya topilmadi: (.+)$/, ru: "Партия не найдена: $1", uzc: "Партия топилмади: $1" },
  { re: /^Partiya boshqa mahsulot yoki filialga tegishli: (.+)$/, ru: "Партия относится к другому товару или филиалу: $1", uzc: "Партия бошқа маҳсулот ёки филиалга тегишли: $1" },
  { re: /^Partiya holati '(.+)' — undan miqdor ayirib bo'lmaydi: (.+)$/, ru: "Статус партии «$1» — списать с неё количество нельзя: $2", uzc: "Партия ҳолати «$1» — ундан миқдор айириб бўлмайди: $2" },
  { re: /^Partiya holati '(.+)' — uni sanab bo'lmaydi: (.+)$/, ru: "Статус партии «$1» — её нельзя пересчитать: $2", uzc: "Партия ҳолати «$1» — уни санаб бўлмайди: $2" },
  { re: /^Partiyada yetarli qoldiq yo'q \((.+) < (.+)\): (.+) — jismoniy partiya MANFIYGA tushmaydi$/, ru: "В партии недостаточно остатка ($1 < $2): $3 — физическая партия не уходит в минус", uzc: "Партияда етарли қолдиқ йўқ ($1 < $2): $3 — жисмоний партия МАНФИЙГА тушмайди" },
  { re: /^Partiyalar yig'indisi \((.+)\) umumiy miqdorga \((.+)\) mos emas\. Farqni tizim TAQSIMLAMAYDI — qaysi partiya ekanini operator aytishi shart\.$/, ru: "Сумма партий ($1) не совпадает с общим количеством ($2). Разницу система НЕ РАСПРЕДЕЛЯЕТ — какая это партия, должен указать оператор.", uzc: "Партиялар йиғиндиси ($1) умумий миқдорга ($2) мос эмас. Фарқни тизим ТАҚСИМЛАМАЙДИ — қайси партия эканини оператор айтиши шарт." },
  { re: /^Partiyalar yig'indisi \((.+)\) e'lon qilingan umumiy sanoqqa \((.+)\) mos emas\. Sanalmagan partiyalar TEGILMAYDI \((.+)\); farqni tizim TAQSIMLAMAYDI\.$/, ru: "Сумма партий ($1) не совпадает с заявленным итогом пересчёта ($2). Непересчитанные партии НЕ ТРОГАЮТСЯ ($3); разницу система НЕ РАСПРЕДЕЛЯЕТ.", uzc: "Партиялар йиғиндиси ($1) эълон қилинган умумий саноққа ($2) мос эмас. Саналмаган партиялар ТЕГИЛМАЙДИ ($3); фарқни тизим ТАҚСИМЛАМАЙДИ." },
  { re: /^'(.+)' muddat bo'yicha kuzatiladi — yangi partiyada `expiry_date` MAJBURIY\. Noma'lum muddat jimgina qabul qilinmaydi\.$/, ru: "«$1» отслеживается по сроку годности — у новой партии срок ОБЯЗАТЕЛЕН. Неизвестный срок молча не принимается.", uzc: "«$1» муддат бўйича кузатилади — янги партияда муддат МАЖБУРИЙ. Номаълум муддат жимгина қабул қилинмайди." },
  { re: /^Ochilish partiyalari yig'indisi (.+) joriy qoldiq (.+) ga TENG EMAS\. Miqdor taxmin qilinmaydi\.$/, ru: "Сумма начальных партий $1 НЕ РАВНА текущему остатку $2. Количество не угадывается.", uzc: "Бошланғич партиялар йиғиндиси $1 жорий қолдиқ $2 га ТЕНГ ЭМАС. Миқдор тахмин қилинмайди." },
  { re: /^'(.+)': ochilish partiyasi muddati sana EMAS — YYYY-MM-DD ko'rinishida bering\. Muddat taxmin qilinmaydi\.$/, ru: "«$1»: срок начальной партии — НЕ дата. Укажите в формате ГГГГ-ММ-ДД. Срок не угадывается.", uzc: "«$1»: бошланғич партия муддати сана ЭМАС — ЙЙЙЙ-ОО-КК кўринишида беринг. Муддат тахмин қилинмайди." },
  { re: /^Kuzatuvni yoqib bo'lmadi — miqdor invarianti buzilgan bo'lardi: (.+)$/, ru: "Не удалось включить учёт — был бы нарушен инвариант количества: $1", uzc: "Кузатувни ёқиб бўлмади — миқдор инварианти бузилган бўларди: $1" },
  { re: /^Hisobdan chiqarib bo'lmadi — invariant buzilardi: (.+)$/, ru: "Списать не удалось — был бы нарушен инвариант: $1", uzc: "Ҳисобдан чиқариб бўлмади — инвариант бузиларди: $1" },
  { re: /^Inventarizatsiyani yozib bo'lmadi — invariant buzilardi: (.+)$/, ru: "Пересчёт не записан — был бы нарушен инвариант: $1", uzc: "Инвентаризацияни ёзиб бўлмади — инвариант бузиларди: $1" },
  { re: /^'(.+)' allaqachon partiya bo'yicha kuzatiladi$/, ru: "«$1» уже отслеживается по партиям", uzc: "«$1» аллақачон партия бўйича кузатилади" },
  // ── ONLAYN SOTUV (`services/sales.py`) — mahsulot nomida «: » bo'lsa ham butun matn mos keladi ──
  { re: /^'(.+)': sotuvga yaroqli partiya yetarli emas \(kerak (.+), yaroqli (.+)\)\. Muddati o'tgan yoki hisobga olinmagan tovar bo'lishi mumkin — inventarizatsiya qiling\.$/, ru: "«$1»: годных к продаже партий недостаточно (нужно $2, годных $3). Возможно, товар просрочен или не учтён — проведите пересчёт.", uzc: "«$1»: сотувга яроқли партия етарли эмас (керак $2, яроқли $3). Муддати ўтган ёки ҳисобга олинмаган товар бўлиши мумкин — инвентаризация қилинг." },
  // ── KIRIM YO'LI (`services/lot_receiving.py`, `api/v1/receiving.py`) ───────
  { re: /^'(.+)' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY\. Miqdor taxmin qilinmaydi\.$/, ru: "«$1» отслеживается по партиям — для каждой строки прихода партии ОБЯЗАТЕЛЬНЫ. Количество не угадывается.", uzc: "«$1» партия бўйича кузатилади — ҳар кирим қатори учун партиялар МАЖБУРИЙ. Миқдор тахмин қилинмайди." },
  { re: /^'(.+)' partiya bo'yicha kuzatilmaydi — `lots` berib bo'lmaydi\. Avval partiya kuzatuvini yoqing\.$/, ru: "«$1» не отслеживается по партиям — партии передать нельзя. Сначала включите учёт партий.", uzc: "«$1» партия бўйича кузатилмайди — партия бериб бўлмайди. Аввал партия кузатувини ёқинг." },
  { re: /^'(.+)' partiya bo'yicha kuzatilmaydi — `lots` berib bo'lmaydi$/, ru: "«$1» не отслеживается по партиям — партии передать нельзя", uzc: "«$1» партия бўйича кузатилмайди — партия бериб бўлмайди" },
  { re: /^'(.+)' muddat bo'yicha kuzatiladi — har partiyada `expiry_date` MAJBURIY\. Noma'lum muddat jimgina qabul qilinmaydi\.$/, ru: "«$1» отслеживается по сроку годности — у каждой партии срок ОБЯЗАТЕЛЕН. Неизвестный срок молча не принимается.", uzc: "«$1» муддат бўйича кузатилади — ҳар партияда муддат МАЖБУРИЙ. Номаълум муддат жимгина қабул қилинмайди." },
  { re: /^'(.+)' muddat bo'yicha KUZATILMAYDI — yangi partiyaga `expiry_date` yozib bo'lmaydi\. Avval mahsulotda muddat kuzatuvini yoqing\.$/, ru: "«$1» НЕ отслеживается по сроку годности — у новой партии срок указать нельзя. Сначала включите учёт срока у товара.", uzc: "«$1» муддат бўйича КУЗАТИЛМАЙДИ — янги партияга муддат ёзиб бўлмайди. Аввал маҳсулотда муддат кузатувини ёқинг." },
  { re: /^'(.+)': partiyalar yig'indisi (.+) qator miqdori (.+) ga TENG EMAS\. Yetishmagan miqdor taxmin qilinmaydi\.$/, ru: "«$1»: сумма партий $2 НЕ РАВНА количеству строки $3. Недостающее количество не угадывается.", uzc: "«$1»: партиялар йиғиндиси $2 қатор миқдори $3 га ТЕНГ ЭМАС. Етишмаган миқдор тахмин қилинмайди." },
  { re: /^'(.+)': partiya miqdori musbat bo'lishi shart$/, ru: "«$1»: количество партии должно быть положительным", uzc: "«$1»: партия миқдори мусбат бўлиши шарт" },
  // ⚠️  ANIQLIK DARVOZASI (Phase 5C). Kasr xonasi uchtadan ortiq bo'lsa qoldiq va
  //     partiya har xil yaxlitlanib jimgina ajralardi — server AYTADI, yaxlitlamaydi.
  { re: /^'(.+)': qator miqdori (.+) da uchtadan ORTIQ kasr xonasi bor — miqdor 0\.001 aniqligida beriladi\. Miqdor jimgina yaxlitlanmaydi\.$/, ru: "«$1»: в количестве строки $2 больше трёх знаков после запятой — количество указывается с точностью 0.001. Количество молча не округляется.", uzc: "«$1»: қатор миқдори $2 да учтадан ОРТИҚ каср хонаси бор — миқдор 0.001 аниқлигида берилади. Миқдор жимгина яхлитланмайди." },
  { re: /^'(.+)': partiya miqdori (.+) da uchtadan ORTIQ kasr xonasi bor — miqdor 0\.001 aniqligida beriladi\. Miqdor jimgina yaxlitlanmaydi\.$/, ru: "«$1»: в количестве партии $2 больше трёх знаков после запятой — количество указывается с точностью 0.001. Количество молча не округляется.", uzc: "«$1»: партия миқдори $2 да учтадан ОРТИҚ каср хонаси бор — миқдор 0.001 аниқлигида берилади. Миқдор жимгина яхлитланмайди." },
  // Xarid tahriri (`api/v1/purchases.py`) — kuzatuvli qatorda FAQAT narx o'zgarishi.
  { re: /^'(.+)' partiya bo'yicha kuzatiladi — kirim narxini tahrirlab bo'lmaydi: partiya tannarxi qabul paytida yozilgan va hujjat bilan jimgina ajralib qolardi\. Kuzatuvli hujjat hozircha bekor ham qilinmaydi — tuzatish uchun qo'llab-quvvatlashga murojaat qiling\.$/, ru: "«$1» отслеживается по партиям — цену прихода изменить нельзя: себестоимость партии записана при приёмке и молча разошлась бы с документом. Приход по партиям пока и отменить нельзя — для исправления обратитесь в поддержку.", uzc: "«$1» партия бўйича кузатилади — кирим нархини таҳрирлаб бўлмайди: партия таннархи қабул пайтида ёзилган ва ҳужжат билан жимгина ажралиб қоларди. Кузатувли ҳужжат ҳозирча бекор ҳам қилинмайди — тузатиш учун қўллаб-қувватлашга мурожаат қилинг." },
  { re: /^'(.+)': partiya tannarxi noma'lum\. Kirim narxi yoki partiya narxi berilishi shart — mahsulotning joriy olish narxi JIMGINA ishlatilmaydi\.$/, ru: "«$1»: себестоимость партии неизвестна. Нужна цена прихода или цена партии — текущая закупочная цена товара молча не используется.", uzc: "«$1»: партия таннархи номаълум. Кирим нархи ёки партия нархи берилиши шарт — маҳсулотнинг жорий олиш нархи ЖИМГИНА ишлатилмайди." },
  { re: /^'(.+)': (.+) muddati bugungi biznes sanasi \((.+)\) dan OLDIN — muddati o'tgan tovar qabul qilinmaydi\.$/, ru: "«$1»: срок $2 РАНЬШЕ сегодняшней бизнес-даты ($3) — просроченный товар не принимается.", uzc: "«$1»: муддат $2 бугунги бизнес санасидан ($3) ОЛДИН — муддати ўтган товар қабул қилинмайди." },
  { re: /^'(.+)' qatori summasi juda katta \(miqdor×narx (.+)\) — miqdor yoki narxni tekshiring$/, ru: "Сумма строки «$1» слишком велика (количество×цена $2) — проверьте количество или цену", uzc: "«$1» қатори суммаси жуда катта (миқдор×нарх $2) — миқдор ёки нархни текширинг" },
  { re: /^AI o'qishda xato: (.+)$/, ru: "Ошибка распознавания: $1", uzc: "AI ўқишда хато: $1" },
  // ── DARVOZALAR (`services/lot_policy.py`, `services/stock_gate.py`) ────────
  { re: /^partiya kuzatuvi bu muhitda \('(.+)'\) YOQILMAYDI\. Phase 2 hali production uchun ko'rib chiqilmagan; kuzatuv yoqilgan mahsulotni ortga qaytarib bo'lmaydi\.$/, ru: "учёт партий в этой среде («$1») НЕ ВКЛЮЧАЕТСЯ. Он ещё не проверен для боевой среды; товар с включённым учётом назад не вернуть.", uzc: "партия кузатуви бу муҳитда («$1») ЁҚИЛМАЙДИ. У ҳали ишчи муҳит учун кўриб чиқилмаган; кузатув ёқилган маҳсулотни ортга қайтариб бўлмайди." },
  { re: /^filial vaqt zonasi \('(.+)'\) TASDIQLANMAGAN\. Muddat biznes sanasiga tayanadi va bir soatlik xato muddatni bir kunga suradi — shu bois zona operator tomonidan ANIQ tasdiqlanishi kerak\.$/, ru: "часовой пояс филиала («$1») НЕ ПОДТВЕРЖДЁН. Срок опирается на бизнес-дату, и ошибка в один час сдвигает срок на день — пояс должен подтвердить оператор.", uzc: "филиал вақт зонаси («$1») ТАСДИҚЛАНМАГАН. Муддат бизнес санасига таянади ва бир соатлик хато муддатни бир кунга суради — зонани оператор АНИҚ тасдиқлаши керак." },
  { re: /^vaqt zonasi '(.+)' tanilmagan\. Muddat kuzatuvi yoqilishidan oldin u qo'llab-quvvatlanadigan zonalar ro'yxatiga kiritilishi kerak\.$/, ru: "часовой пояс «$1» не распознан. До включения учёта срока его нужно добавить в список поддерживаемых.", uzc: "вақт зонаси «$1» танилмаган. Муддат кузатуви ёқилишидан олдин у қўллаб-қувватланадиган зоналар рўйхатига киритилиши керак." },
  { re: /^«(.+)» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin (\d+) ta kuzatuvli mahsulot so'raldi\. Partiya-darajasidagi amalni ishlating — qoldiqni partiyalardan ayirmasdan o'zgartirish miqdor invariantini buzardi\.$/, ru: "Путь «$1» не поддерживает учёт партий, а запрошено товаров с учётом: $2. Используйте операцию на уровне партий — изменение остатка без списания с партий нарушило бы инвариант количества.", uzc: "«$1» йўли партия кузатувини қўллаб-қувватламайди, лекин $2 та кузатувли маҳсулот сўралди. Партия даражасидаги амални ишлатинг — қолдиқни партиялардан айирмасдан ўзгартириш миқдор инвариантини бузарди." },
  { re: /^Noma'lum guruh: (.+)$/, ru: "Неизвестная группа: $1", uzc: "Номаълум гуруҳ: $1" },
  { re: /^Noma'lum tartib: (.+)$/, ru: "Неизвестная сортировка: $1", uzc: "Номаълум тартиб: $1" },
  { re: /^Noma'lum holat: (.+)$/, ru: "Неизвестный статус: $1", uzc: "Номаълум ҳолат: $1" },
  { re: /^Bitta so'rovda (\d+) ta partiya qatori — chegara (\d+)\. Sanoqni bir necha so'rovga bo'lib yuboring\.$/, ru: "В одном запросе $1 строк партий — предел $2. Разбейте пересчёт на несколько запросов.", uzc: "Битта сўровда $1 та партия қатори — чегара $2. Саноқни бир неча сўровга бўлиб юборинг." },
  // ── QAYTARISH: RESTOCK'SIZ so'rovda atributsiya topilmadi (`services/lot_return.py`) ──
  // ⚠️  Restock'li variant (`... omborga qaytarmasdan (restock'siz) qaytaring.`) — avto-
  //     generatsiya lug'atida (`serverErrors.ts`). Restock'siz so'rovda o'sha maslahat BOSHI
  //     BERK bo'lardi, shu bois matn ham, tarjimasi ham BOSHQA.
  { re: /^Qaytarilayotgan miqdorning (.+) donasini asl chek partiyalariga bog'lab bo'lmadi\. Tizim TAXMIN QILMAYDI — amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling\.$/, ru: "$1 шт. возвращаемого количества нельзя привязать к партиям исходного чека. Система не угадывает — операция НЕ выполнена; обратитесь в поддержку.", uzc: "Қайтарилаётган миқдорнинг $1 донасини асл чек партияларига боғлаб бўлмади. Тизим ТАХМИН ҚИЛМАЙДИ — амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг." },
];

function look(msg: string, lang: string): string | null {
  const s = STATIC[msg];
  if (s) return lang === "uzc" ? s.uzc : s.ru;
  for (const d of DYNAMIC) {
    const m = msg.match(d.re);
    if (m) {
      const tpl = lang === "uzc" ? d.uzc : d.ru;
      return tpl.replace(/\$(\d)/g, (_, i) => m[+i] ?? "");
    }
  }
  return null;
}

/** Partiya xatosini foydalanuvchi tiliga o'giradi; lug'atda bo'lmasa `null`
 *  (chaqiruvchi avto-generatsiya lug'atiga o'tadi).
 *
 *  ⚠️  Inventarizatsiya/hisobdan chiqarish xatolari serverda MAHSULOT NOMI bilan
 *      oldindan belgilanadi (`f"{prod.name}: {e}"`). Nom tarjima QILINMAYDI —
 *      shuning uchun prefiks ajratilib, qolgani tarjima qilinadi va nom
 *      o'z holicha qaytariladi. */
export function translateLotError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return null; }
  if (lang === "uz") return null;          // asl matn allaqachon o'zbekcha
  if (lang === "ky") lang = "ru";          // Qirg'iziston — ruscha
  const direct = look(msg, lang);
  if (direct) return direct;
  // ⚠️  BIRINCHI ": " YETARLI EMAS. Mahsulot nomining O'ZIDA ikki nuqta bo'lishi
  //     mumkin (1C'dan kelgan «Sok: olma»), o'shanda prefiks noto'g'ri kesilib
  //     tarjima JIMGINA tushib qolardi. Shu bois har bo'g'inda urinamiz.
  for (let from = 0; ;) {
    const i = msg.indexOf(": ", from);
    if (i < 0) break;
    const rest = look(msg.slice(i + 2), lang);
    if (rest) return msg.slice(0, i + 2) + rest;
    from = i + 2;
  }
  return null;
}

// ── 422 (PYDANTIC) ───────────────────────────────────────────────────────────
// ⚠️  BU MATNLAR SERVERDA EMAS, KUTUBXONADA tug'iladi va inglizcha bo'ladi.
//     Avto-generatsiya lug'ati ularni HECH QACHON ko'rmaydi. UI oldindan
//     tekshirsa ham, eski ilova yoki to'g'ridan-to'g'ri so'rov kirillcha do'kon
//     egasiga inglizcha matn ko'rsatardi.
const PYDANTIC: { re: RegExp; ru: string; uzc: string }[] = [
  { re: /^Field required$/, ru: "Поле обязательно", uzc: "Майдон мажбурий" },
  // ⚠️  UZUNROQ naqsh OLDIN: aks holda «greater than» «or equal to 0» ni
  //     ushlab, «больше or equal to 0» degan buzilgan va MA'NOSI TESKARI matn chiqardi.
  { re: /^Input should be greater than or equal to (.+)$/, ru: "Значение должно быть не меньше $1", uzc: "Қиймат $1 дан кичик бўлмаслиги керак" },
  { re: /^Input should be greater than (.+)$/, ru: "Значение должно быть больше $1", uzc: "Қиймат $1 дан катта бўлиши керак" },
  { re: /^Input should be less than or equal to (.+)$/, ru: "Значение должно быть не больше $1", uzc: "Қиймат $1 дан катта бўлмаслиги керак" },
  { re: /^String should have at least (\d+) characters?$/, ru: "Нужно не менее $1 символов", uzc: "Камида $1 та белги керак" },
  { re: /^String should have at most (\d+) characters?$/, ru: "Не более $1 символов", uzc: "Кўпи билан $1 та белги" },
  { re: /^List should have at least (\d+) items? after validation, not (\d+)$/, ru: "Нужно не менее $1 позиций (сейчас $2)", uzc: "Камида $1 та қатор керак (ҳозир $2)" },
  { re: /^List should have at most (\d+) items? after validation, not (\d+)$/, ru: "Не более $1 позиций (сейчас $2)", uzc: "Кўпи билан $1 та қатор (ҳозир $2)" },
  { re: /^Value error, (.+)$/, ru: "$1", uzc: "$1" },
  { re: /^Input should be a valid (.+)$/, ru: "Некорректное значение ($1)", uzc: "Нотўғри қиймат ($1)" },
];

/** FastAPI 422 tafsilotidagi BITTA `msg` ni tarjima qiladi (topilmasa `null`). */
export function translatePydanticError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return null; }
  if (lang === "uz") return null;
  if (lang === "ky") lang = "ru";
  for (const d of PYDANTIC) {
    const m = msg.match(d.re);
    if (m) {
      const tpl = lang === "uzc" ? d.uzc : d.ru;
      return tpl.replace(/\$(\d)/g, (_, i) => m[+i] ?? "");
    }
  }
  // Ichki xabar server qoidasi bo'lsa (`Value error, ...`) — lot lug'atida bo'lishi mumkin.
  return translateLotError(msg);
}
