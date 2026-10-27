// R5 — QURILMA TILI -> INTERFEYS TILI MOSLIGI.
//
// ⚠️  NEGA BU TEST BOR. Build 62 Apple App Review'da ARALASH TIL uchun rad
//     etildi: tizim ruxsat oynasi bir tilda, interfeys boshqa tilda chiqdi.
//     Tuzatish ikki qismdan iborat va IKKISI HAM shart:
//       1) `ios/Runner/<til>.lproj/InfoPlist.strings` — tizim oynasi qurilma
//          tilida chiqsin (`test/ios_localization_test.dart` qadaydi);
//       2) birinchi ishga tushishda interfeys tili ham QURILMA tilidan olinsin
//          (shu fayl) — aks holda 1-qism oynani ruscha qilib, interfeysni
//          o'zbekcha qoldirardi, ya'ni nomuvofiqlik SAQLANIB QOLARDI.
@TestOn('vm')
library;

import 'dart:ui' show Locale;

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('langForLocales', () {
    test('qo‘llanadigan tillar o‘z kodiga tushadi', () {
      expect(langForLocales([const Locale('ru', 'RU')]), 'ru');
      expect(langForLocales([const Locale('ky', 'KG')]), 'ky');
      expect(
          langForLocales(
              [const Locale.fromSubtags(languageCode: 'uz', scriptCode: 'Latn', countryCode: 'UZ')]),
          'uz');
    });

    test('uz-Cyrl kirill interfeysga tushadi', () {
      // iOS "Oʻzbekcha (kirill)" ni `uz-Cyrl-UZ` deb beradi.
      expect(
          langForLocales(
              [const Locale.fromSubtags(languageCode: 'uz', scriptCode: 'Cyrl', countryCode: 'UZ')]),
          'uzc');
    });

    test('qo‘llanmaydigan til -> uz (Info.plist asosiy qiymati bilan AYNI)', () {
      //  Inglizcha `InfoPlist.strings` ATAYLAB yo'q: iOS o'zbekcha asosiy
      //  qiymatga tushadi, interfeys ham o'zbekcha — ikki tomon bir tilda.
      expect(langForLocales([const Locale('en', 'US')]), 'uz');
      expect(langForLocales([const Locale('tr', 'TR')]), 'uz');
      expect(langForLocales(const <Locale>[]), 'uz');
    });

    test('afzal tillar ro‘yxatidagi IKKINCHI mos til ham hisobga olinadi', () {
      //  iOS bir nechta afzal til beradi; birinchisi qo'llanmasa, keyingisi
      //  baribir foydalanuvchining O'Z tanlovi.
      expect(langForLocales([const Locale('en', 'US'), const Locale('ru', 'RU')]), 'ru');
    });

    test('katta harfli til kodi ham tanilaydi', () {
      expect(langForLocales([const Locale('RU', 'RU')]), 'ru');
    });
  });

  _brandGroup();

  group('L.load()', () {
    test('SAQLANGAN tanlov qurilma tilidan ustun', () async {
      SharedPreferences.setMockInitialValues({'savdoos_lang': 'ky'});
      await L.load();
      expect(L.code, 'ky', reason: 'foydalanuvchi tanlovi bosib ketilgan');
    });

    test('tanlov yo‘q bo‘lsa — qurilma tili, lekin HECH NARSA saqlanmaydi', () async {
      SharedPreferences.setMockInitialValues({});
      await L.load();
      expect(const {'uz', 'uzc', 'ru', 'ky'}.contains(L.code), isTrue,
          reason: 'qo‘llanmaydigan til tanlangan: ${L.code}');
      final p = await SharedPreferences.getInstance();
      expect(p.getString('savdoos_lang'), isNull,
          reason: 'aniqlangan til saqlanib qolsa, telefon tili keyin '
              'o‘zgarganda ilova ortda qoladi');
    });
  });
}

// ── Kirill transliteratsiyasi brend nomlarini saqlashi ────────────────────
//  ⚠️  Apple HIG: `Face ID` va `Touch ID` AYNAN shunday yozilishi shart.
//      `keep` regexida ular `ID` dan OLDIN turmasa, faqat `ID` saqlanib
//      `Face` transliteratsiya qilinardi -> "Фасе ID" (o'lchangan nuqson).
void _brandGroup() {
  group('uzc transliteratsiyasi brend nomlarini saqlaydi', () {
    setUp(() => L.code = 'uzc');
    tearDown(() => L.code = 'uz');

    test('Face ID o‘zgarmaydi', () {
      final out = tr('Barmoq izi yoki Face ID bilan ham kirishni yoqasizmi?');
      expect(out, contains('Face ID'));
      expect(out, isNot(contains('Фасе')));
      expect(out, contains('Бармоқ'), reason: 'qolgan matn transliteratsiya bo‘lsin');
    });

    test('Touch ID ham o‘zgarmaydi', () {
      expect(tr('Touch ID bilan kirish'), contains('Touch ID'));
    });

    test('yakka ID va boshqa akronimlar avvalgidek saqlanadi', () {
      expect(tr('ID raqami'), contains('ID'));
      expect(tr('PIN kodi'), contains('PIN'));
      expect(tr('BinOS ilovasi'), contains('BinOS'));
    });
  });
}
