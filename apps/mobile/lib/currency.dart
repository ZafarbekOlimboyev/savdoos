/// VALYUTA KONTRAKTI — mobil tomondagi YAGONA jadval.
///
/// Valyuta va til — IKKI BOSHQA tushuncha:
///  * `company.currency` (ISO-4217) pul BIRLIGINI belgilaydi;
///  * UI tili ([L.code]) faqat MATNNI tarjima qiladi.
///
/// ⚠️  ILGARI NUQSON BOR EDI: pul yorlig'i faqat `tr('so‘m')` dan, ya'ni TILDAN
///     chiqarilardi — shu bois o'zbekcha interfeys KGS do'konda ham "so‘m"
///     ko'rsatardi. Pul birligini til hal qila OLMAYDI.
///
/// Bu jadval web tomondagi `packages/shared/src/receipt/format.ts`
/// (`currencyLabel`) bilan AYNI semantikada. Ikkisi ajralib ketmasin: yangi
/// valyuta qo'shilsa IKKI joyga ham qo'shiladi (test ikkisini ham qamraydi).
library;

import 'l10n.dart';

/// KGS — bitta KANONIK yozuv, barcha tillarda "сом" (mavjud qirg'iz UI konvensiyasi).
const String _kgs = 'сом';

/// Joriy do'konning valyutasi — ilova bo'ylab YAGONA manba.
///
/// [L] bilan bir xil naqsh: oddiy statik holat, ekranlarda nusxalanmaydi.
/// Qiymatni [Api] yozadi — login javobidagi `employee.company_currency` va
/// `GET /auth/context` dagi `company.currency` xodim suratiga tushadi, surat esa
/// qurilmaning xavfsiz xotirasida saqlanadi. Shu sabab OFFLINE ishga tushishda
/// ham valyuta ma'lum bo'ladi (do'konning asosiy ish rejimi).
class Cur {
  /// ISO-4217 kodi (`KGS`, `UZS`, ...) yoki `null` — hali ma'lum emas.
  static String? code;

  /// Joriy do'kon valyutasining yorlig'i.
  static String get label => currencyLabel(code);
}

/// Pul yorlig'i: AVVAL valyuta kodi, keyin til.
///
/// Fallback ATAYLAB va sinaladi:
///  * kod YO'Q/bo'sh (eski server, hali yuklanmagan surat) → eski tilga-asoslangan
///    yorliq, ya'ni mavjud UZS do'konlarida hech narsa o'zgarmaydi;
///  * kod NOMA'LUM (masalan `EUR`) → kodning O'ZI, yorliq O'YLAB TOPILMAYDI.
String currencyLabel(String? currency) {
  final code = (currency ?? '').trim().toUpperCase();
  if (code.isEmpty) return tr('so‘m'); // eski xulq — regressiya yo'q
  if (code == 'KGS') return _kgs;
  if (code == 'UZS') return tr('so‘m'); // bugungi tilga-bog'liq yozuv AYNAN saqlanadi
  return code;
}
