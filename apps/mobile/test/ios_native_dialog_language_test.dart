// R6 — TIZIM OYNASI va ILOVA INTERFEYSI BIR XIL TILDA bo'lishi.
//
// ⚠️  NEGA BU TEST BOR. Build 62 Apple tomonidan RAD ETILGAN edi: iOS'ning
//     o'z ruxsat oynalari (kamera, galereya, Face ID) INGLIZCHA chiqar, ilova
//     interfeysi esa O'ZBEKCHA edi. Foydalanuvchi "Allow"/"Don't Allow" ni
//     tushunmaydigan tilda ko'rardi.
//
//     Tuzatish ikki qismdan iborat:
//       1. Native: `ios/Runner/<til>.lproj/InfoPlist.strings` — tizim oynasi
//          matnini iOS O'ZI tanlaydi (biz nazorat qilmaydigan tugmalar ham
//          shu tanlovga qarab tarjima bo'ladi).
//       2. Dart: `langForLocales` — ilk ishga tushishda interfeys tili
//          qurilma tilidan olinadi.
//
//     Ikkisi AJRALIB KETSA rad etilish qaytadi: masalan native `ru` tanlab,
//     interfeys `uz` bo'lib qolsa. Shu bois bu test ikkisining MOSLIGINI
//     qotiradi.
//
// Quyidagi jadval Apple'ning O'Z algoritmi bilan o'lchangan (2026-10-28):
//
//     Bundle.preferredLocalizations(from: ["Base","uz","uz-Cyrl","ru","ky"],
//                                   forPreferences: [<qurilma tili>])
//
//     ru-RU      -> ru
//     uz-UZ      -> uz
//     uz-Latn-UZ -> uz
//     uz-Cyrl-UZ -> uz-Cyrl
//     ky-KG      -> ky
//     en-US      -> Base      (ya'ni Info.plist dagi asosiy, O'ZBEKCHA matn)
//     tr-TR      -> Base
//     ar-SA      -> Base
//     kk-KZ      -> Base
//
// `Base` — `ios/Runner/Info.plist` dagi asosiy qiymatlar, ular O'ZBEKCHA.
// Shuning uchun qo'llanmaydigan tilli qurilmada ham oyna va interfeys bir
// xil (o'zbekcha) bo'ladi.
@TestOn('vm')
library;

import 'dart:io';
import 'dart:ui' show Locale;

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';

/// Ilova bundle'ida bo'lishi SHART bo'lgan lokalizatsiyalar.
/// `en` ATAYLAB YO'Q: inglizcha oyna + o'zbekcha interfeys aynan rad etilgan
/// nomuvofiqlikni qaytarardi (qarang `test/ios_localization_test.dart`).
const Set<String> kExpectedLprojs = {'Base', 'uz', 'uz-Cyrl', 'ru', 'ky'};

/// Apple algoritmi bilan O'LCHANGAN jadval: qurilma tili -> tanlangan `.lproj`.
const Map<String, String> kAppleResolution = {
  'ru-RU': 'ru',
  'uz-UZ': 'uz',
  'uz-Latn-UZ': 'uz',
  'uz-Cyrl-UZ': 'uz-Cyrl',
  'ky-KG': 'ky',
  'en-US': 'Base',
  'tr-TR': 'Base',
  'ar-SA': 'Base',
  'kk-KZ': 'Base',
};

/// `.lproj` nomidan ilovaning ichki til kodiga.
/// `Base` -> `uz`, chunki Info.plist asosiy matnlari o'zbekcha.
String _uiCodeForLproj(String lproj) => switch (lproj) {
      'ru' => 'ru',
      'ky' => 'ky',
      'uz-Cyrl' => 'uzc',
      'uz' => 'uz',
      'Base' => 'uz',
      _ => throw StateError('kutilmagan .lproj: $lproj'),
    };

/// `ru-RU` kabi satrni `Locale` ga aylantiradi (script kodini ham hisobga oladi).
Locale _locale(String tag) {
  final p = tag.split('-');
  if (p.length == 3) return Locale.fromSubtags(languageCode: p[0], scriptCode: p[1], countryCode: p[2]);
  if (p.length == 2 && p[1].length == 4) return Locale.fromSubtags(languageCode: p[0], scriptCode: p[1]);
  if (p.length == 2) return Locale(p[0], p[1]);
  return Locale(p[0]);
}

void main() {
  final runnerDir = Directory('ios/Runner');

  group('Native bundle lokalizatsiyalari', () {
    test('aynan kutilgan .lproj to`plami mavjud', () {
      final found = runnerDir
          .listSync()
          .whereType<Directory>()
          .map((d) => d.path.split('/').last)
          .where((n) => n.endsWith('.lproj'))
          .map((n) => n.substring(0, n.length - '.lproj'.length))
          .toSet();
      expect(found, kExpectedLprojs,
          reason: 'bundle lokalizatsiyalari o`zgargan — Apple tanlovi jadvali '
              'qayta o`lchanishi kerak (swift Bundle.preferredLocalizations)');
    });

    test('en.lproj YO`Q — inglizcha oyna + o`zbekcha interfeys qaytmasin', () {
      expect(Directory('ios/Runner/en.lproj').existsSync(), isFalse);
    });

    test('har bir tilda UCHALA ruxsat matni bor va bo`sh emas', () {
      for (final l in kExpectedLprojs.where((e) => e != 'Base')) {
        final f = File('ios/Runner/$l.lproj/InfoPlist.strings');
        expect(f.existsSync(), isTrue, reason: '$l.lproj/InfoPlist.strings yo`q');
        final src = f.readAsStringSync();
        for (final key in const [
          'NSCameraUsageDescription',
          'NSPhotoLibraryUsageDescription',
          'NSFaceIDUsageDescription',
        ]) {
          final m = RegExp('"$key"\\s*=\\s*"([^"]+)"').firstMatch(src);
          expect(m, isNotNull, reason: '$l: $key yo`q');
          expect(m!.group(1)!.trim().length, greaterThan(10), reason: '$l: $key juda qisqa');
        }
      }
    });

    test('Info.plist asosiy matnlari O`ZBEKCHA (Base fallback shu bo`ladi)', () {
      // Qo'llanmaydigan tilli qurilma `Base` ni oladi, ya'ni shu matnlarni.
      // Agar ular inglizcha bo'lsa — rad etilish aynan qaytadi.
      final plist = File('ios/Runner/Info.plist').readAsStringSync();
      final cam = RegExp(r'<key>NSCameraUsageDescription</key>\s*<string>([^<]+)</string>')
          .firstMatch(plist);
      expect(cam, isNotNull);
      final text = cam!.group(1)!;
      expect(text, contains('kamera'),
          reason: 'asosiy kamera matni o`zbekcha bo`lishi shart, topildi: $text');
      expect(text.toLowerCase(), isNot(contains('camera is')),
          reason: 'inglizcha matn asosiy qiymatda qolgan');
    });
  });

  group('Tizim oynasi tili == interfeys tili', () {
    // ⚠️  ASOSIY INVARIANT. Har bir qurilma tili uchun: Apple qaysi `.lproj`
    //     ni tanlasa, ilova interfeysi ham AYNI tilda bo'lishi kerak.
    for (final entry in kAppleResolution.entries) {
      test('${entry.key}: oyna=${entry.value} va interfeys MOS', () {
        final expectedUi = _uiCodeForLproj(entry.value);
        final actualUi = langForLocales([_locale(entry.key)]);
        expect(actualUi, expectedUi,
            reason: '${entry.key} qurilmasida tizim oynasi "${entry.value}" tilida '
                'chiqadi, interfeys esa "$actualUi" — Apple Guideline 4 radi '
                'AYNAN shu nomuvofiqlik uchun berilgan edi');
      });
    }

    test('jadval bundle lokalizatsiyalari bilan izchil', () {
      // Jadvaldagi har bir natija haqiqatan mavjud `.lproj` bo'lishi kerak.
      for (final v in kAppleResolution.values) {
        expect(kExpectedLprojs, contains(v), reason: 'jadvalda yo`q lokalizatsiya: $v');
      }
    });
  });

  group('Qo`lda tanlangan til tizim oynasidan MUSTAQIL', () {
    // Egasining 7 va 8-holatlari: qurilma tili bir xil, ilovada boshqa til
    // tanlangan. Bu Apple uchun MUAMMO EMAS — tizim oynasi tilini iOS
    // boshqaradi va uni norasmiy yo'l bilan o'zgartirish TAQIQLANADI
    // (`AppleLanguages` ga yozish). Shu bois bu yerda tekshiriladigan narsa:
    // qo'lda tanlov SAQLANADI va qurilma tili uni BOSMAYDI.
    test('qo`lda tanlov qurilma tilidan ustun turadi', () {
      // `L.load()` xulqi `test/device_language_test.dart` da o'lchangan;
      // bu yerda faqat qoida qayd etiladi, takrorlanmaydi.
      expect(langForLocales([const Locale('ru', 'RU')]), 'ru',
          reason: 'qurilma tili faqat ILK ishga tushishda standart beradi');
    });
  });
}
