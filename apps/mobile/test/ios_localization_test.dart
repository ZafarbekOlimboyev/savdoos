// R5 — iOS TIZIM RUXSAT OYNALARI LOKALIZATSIYASI.
//
// ⚠️  NEGA BU TEST BOR. Build 62 Apple App Review'da **Guideline 4 — Design**
//     bo'yicha RAD ETILDI: tizim ruxsat oynasi o'zbekcha chiqdi, ilova
//     interfeysi esa ruscha edi (Apple iPad Air 11" M3 da sinagan).
//     Sabab: `Info.plist` da uchta `NS*UsageDescription` FAQAT bitta tilda
//     qattiq kodlangan edi va ikkilikda BIRORTA `InfoPlist.strings` yo'q edi
//     (`.lproj` kataloglaridan faqat `Base.lproj`). Shu bois iOS qurilma tili
//     nima bo'lishidan qat'i nazar o'sha yagona matnni ko'rsatardi.
//
//     Bu test uchta narsani QADAYDI: har bir qo'llanadigan til uchun fayl
//     BOR, ichida uchta kalit HAM bor, va qiymatlar BO'SH EMAS hamda
//     tillar orasida TAKRORLANMAYDI (ya'ni kimdir faylni yaratib, ichini
//     nusxalab qo'ymagan).
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Ilova interfeysi qo'llaydigan TO'RT til. Boshqasi YO'Q — ayniqsa `en`:
/// pastdagi "inglizcha .lproj BO'LMASLIGI shart" testi sababini tushuntiradi.
const langs = ['uz', 'uz-Cyrl', 'ru', 'ky'];

/// Ilova so'raydigan ruxsatlar. Yangi ruxsat qo'shilsa, bu ro'yxat ham
/// o'sishi va HAR BIR tilda tarjimasi paydo bo'lishi shart.
const keys = [
  'NSCameraUsageDescription',
  'NSPhotoLibraryUsageDescription',
  'NSFaceIDUsageDescription',
];

String _dir(String lang) => 'ios/Runner/$lang.lproj';

Map<String, String> _parse(String path) {
  final out = <String, String>{};
  for (final line in File(path).readAsLinesSync()) {
    final m = RegExp(r'^\s*"([^"]+)"\s*=\s*"(.*)"\s*;\s*$').firstMatch(line);
    if (m != null) out[m.group(1)!] = m.group(2)!;
  }
  return out;
}

void main() {
  group('iOS ruxsat matnlari lokalizatsiyasi', () {
    test('har bir til uchun InfoPlist.strings BOR', () {
      for (final l in langs) {
        expect(File('${_dir(l)}/InfoPlist.strings').existsSync(), isTrue,
            reason: '$l uchun InfoPlist.strings yo‘q — o‘sha tildagi '
                'qurilmada tizim oynasi BOSHQA tilda chiqadi');
      }
    });

    test('har bir tilda UCHTA kalit ham bor va qiymati bo‘sh emas', () {
      for (final l in langs) {
        final m = _parse('${_dir(l)}/InfoPlist.strings');
        for (final k in keys) {
          expect(m.containsKey(k), isTrue, reason: '$l: $k yo‘q');
          expect(m[k]!.trim(), isNotEmpty, reason: '$l: $k bo‘sh');
        }
      }
    });

    test('Info.plist dagi kalitlar ro‘yxati test ro‘yxatiga TENG', () {
      //  ⚠️  Yangi ruxsat qo'shilib, tarjimasi unutilsa — shu yerda qizil.
      final plist = File('ios/Runner/Info.plist').readAsStringSync();
      final found = RegExp(r'<key>(NS[A-Za-z]+UsageDescription)</key>')
          .allMatches(plist)
          .map((m) => m.group(1)!)
          .toSet();
      expect(found, keys.toSet(),
          reason: 'Info.plist va lokalizatsiya ro‘yxati ajralib ketdi');
    });

    test('tarjimalar tillar orasida TAKRORLANMAYDI', () {
      //  Fayl yaratib ichini nusxalab qo'yish — Build 62 nuqsonining
      //  jimgina qaytishi bilan barobar.
      for (final k in keys) {
        final seen = <String, String>{};
        for (final l in langs) {
          final v = _parse('${_dir(l)}/InfoPlist.strings')[k]!;
          final dup = seen[v];
          expect(dup, isNull,
              reason: '$k: "$l" va "$dup" tillarida matn AYNI — tarjima '
                  'qilinmagan nusxa');
          seen[v] = l;
        }
      }
    });

    test('inglizcha InfoPlist.strings BO‘LMASLIGI shart', () {
      //  ⚠️  ATAYLAB YO'Q. Ilova interfeysida inglizcha tarjima YO'Q (egasining
      //      qarori). Agar `en.lproj/InfoPlist.strings` yuborilsa, tili
      //      inglizcha qurilmada tizim oynasi INGLIZCHA, interfeys esa
      //      O'ZBEKCHA chiqadi — ya'ni Build 62 rad etilgan AYNI nomuvofiqlik.
      //      Mos `.lproj` bo'lmasa iOS `Info.plist` ning ASOSIY (o'zbekcha)
      //      qiymatlariga tushadi — bu Build 62 ikkiligida O'LCHANGAN xulq
      //      (ikkilikda faqat `Base.lproj`, 0 ta `InfoPlist.strings` bo'lgan,
      //      va tizim oynasi o'zbekcha chiqqan). Shu bois zaxira = o'zbekcha,
      //      ilovaning standart interfeys tili bilan AYNI.
      expect(File('ios/Runner/en.lproj/InfoPlist.strings').existsSync(), isFalse,
          reason: 'en.lproj qaytib kelgan — inglizcha tizim oynasi + '
              'o‘zbekcha interfeys nomuvofiqligi tiklanadi');
    });

    test('Xcode knownRegions barcha tillarni biladi', () {
      final pbx = File('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();
      final block = RegExp(r'knownRegions = \((.*?)\);', dotAll: true)
          .firstMatch(pbx)!
          .group(1)!;
      for (final l in langs) {
        expect(block.contains(l), isTrue,
            reason: '$l knownRegions da yo‘q — Xcode .lproj ni ikkilikka '
                'solmaydi va tuzatish JIMGINA yo‘qoladi');
      }
    });
  });
}
