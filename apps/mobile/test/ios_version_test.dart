// R5.2 — iOS uchun BITTA versiya manbasi.
//
// ⚠️  NEGA BU TEST BOR. R5.1 oxirida o'lchangan holat:
//       * `pubspec.yaml` -> `version: 1.0.0+56`
//       * `ios/Flutter/Generated.xcconfig` -> `FLUTTER_BUILD_NUMBER=63`
//     Ikkinchisi `.gitignore` da (`apps/mobile/ios/.gitignore:21`) va uni
//     `flutter build` qayta yozadi. Ya'ni 62 va 63 raqamli buildlar BUYRUQ
//     SATRIDAGI `--build-number` dan kelgan, repodan EMAS.
//
//     Oqibat: toza clone yoki CI `flutter build ipa` ni qo'shimcha bayroqsiz
//     bajarsa **56** chiqadi — va 56 App Store Connect'ga ALLAQACHON
//     yuklangan (2026-10-12), ya'ni Apple uni takroriy raqam deb rad etadi.
//
// Shu bois bu yerda qoida qotiriladi: raqam FAQAT pubspec'dan keladi, va u
// Apple ko'rgan eng katta raqamdan katta bo'lishi shart.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// App Store Connect'da mavjud eng katta build raqami.
///
/// 2026-10-29 da `GET /v1/apps/6822128456/builds` bilan FAQAT O'QISH orqali
/// o'lchangan: 56, 57, 58, 59, 60, 61, 62 va **65** — hammasi `VALID`.
/// v1.0.0 esa `REJECTED` holatida. Yangi reliz raqami bundan KATTA bo'lishi
/// shart, aks holda yuklash takroriy raqam sababli rad etiladi.
///
/// ⚠️  62 dan 65 ga OSHIRILDI (R6.6). 65 R6.2 da ASC'ga yuklandi va
///     `MISSING_EXPORT_COMPLIANCE` holatida turadi. Chegara 62 da qolganda
///     skript 65 ni QAYTA ishlatishga ruxsat berardi — Apple esa uni rad
///     etardi, ya'ni darvoza o'z vazifasini bajarmay qolardi.
const int kHighestBuildOnAppStoreConnect = 66;

/// ASC'da BO'SH, lekin MAHALLIY imzolangan IPA'lar uchun allaqachon
/// ishlatilgan raqamlar. Bitta raqam = bitta manba SHA, shuning uchun ular
/// qayta ishlatilmaydi:
///   63 — S3 tuzatishidan OLDINGI source (`BinOS-63.ipa`)
///   64 — R6 source'ning uch bosqichi (42dafff, 04f91d6, 152b06f)
const Set<int> kBurnedLocalBuilds = {63, 64, 67};

final RegExp _versionLine = RegExp(r'^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$', multiLine: true);

File _f(String p) => File(p);

void main() {
  final pubspec = _f('pubspec.yaml').readAsStringSync();
  final infoPlist = _f('ios/Runner/Info.plist').readAsStringSync();
  final pbxproj = _f('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();

  ({int major, int minor, int patch, int build}) version() {
    final m = _versionLine.firstMatch(pubspec)!;
    return (
      major: int.parse(m[1]!),
      minor: int.parse(m[2]!),
      patch: int.parse(m[3]!),
      build: int.parse(m[4]!),
    );
  }

  group('pubspec — yagona manba', () {
    test('aynan BITTA `x.y.z+build` satri bor', () {
      expect(_versionLine.allMatches(pubspec), hasLength(1),
          reason: 'ikkinchi satr ikkinchi haqiqat manbasi bo`ladi');
    });

    test('build raqami App Store Connect ko`rgan eng kattadan KATTA', () {
      final v = version();
      expect(v.build, greaterThan(kHighestBuildOnAppStoreConnect),
          reason: 'build ${v.build} App Store Connect`da allaqachon bor (56..'
              '$kHighestBuildOnAppStoreConnect) — Apple takroriy raqamni rad etadi');
    });

    test('mahalliy imzolangan raqamlar QAYTA ishlatilmaydi', () {
      final v = version();
      expect(kBurnedLocalBuilds, isNot(contains(v.build)),
          reason: 'build ${v.build} mahalliy imzolangan IPA uchun allaqachon '
              'ishlatilgan; bir raqam = bir manba SHA');
    });

    test('App Store relizi 1.0.0', () {
      final v = version();
      expect('${v.major}.${v.minor}.${v.patch}', '1.0.0',
          reason: 'ASC`da ochilgan versiya 1.0.0 (REJECTED) — nomi mos kelishi kerak');
    });
  });

  group('iOS raqamni TAKRORLAMAYDI', () {
    test('Info.plist Flutter o`zgaruvchilaridan oladi', () {
      expect(infoPlist, contains(r'<string>$(FLUTTER_BUILD_NAME)</string>'),
          reason: 'CFBundleShortVersionString pubspec`dan kelishi kerak');
      expect(infoPlist, contains(r'<string>$(FLUTTER_BUILD_NUMBER)</string>'),
          reason: 'CFBundleVersion pubspec`dan kelishi kerak');
    });

    test('Info.plist`da qotirilgan raqam YO`Q', () {
      // `1.0.0` yoki `64` kabi literal bo'lsa — ikkinchi manba.
      final shortVer = RegExp(
              r'<key>CFBundleShortVersionString</key>\s*<string>([^<]*)</string>')
          .firstMatch(infoPlist);
      final bundleVer =
          RegExp(r'<key>CFBundleVersion</key>\s*<string>([^<]*)</string>').firstMatch(infoPlist);
      expect(shortVer, isNotNull);
      expect(bundleVer, isNotNull);
      expect(shortVer!.group(1), r'$(FLUTTER_BUILD_NAME)');
      expect(bundleVer!.group(1), r'$(FLUTTER_BUILD_NUMBER)');
    });

    test('yuboriladigan target Flutter o`zgaruvchisini ishlatadi, literal EMAS', () {
      // ⚠️  Literal faqat YUBORILMAYDIGAN test target'ida bo'lishi mumkin
      //     (`com.binos.owner.RunnerTests`). Yuboriladigan `com.binos.owner`
      //     ning har bir konfiguratsiyasi Flutter o'zgaruvchisidan olishi shart.
      final shipped = <String, String>{};
      final block = RegExp(
          r'/\* (\w+) \*/ = \{\s*isa = XCBuildConfiguration;(.*?)\n\t\t\};',
          dotAll: true);
      for (final m in block.allMatches(pbxproj)) {
        final body = m.group(2)!;
        final bundle =
            RegExp(r'PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);').firstMatch(body)?.group(1);
        if (bundle != 'com.binos.owner') continue;
        final cpv =
            RegExp(r'CURRENT_PROJECT_VERSION = ([^;]+);').firstMatch(body)?.group(1);
        if (cpv != null) shipped[m.group(1)!] = cpv;
      }
      expect(shipped, isNotEmpty, reason: 'yuboriladigan target topilmadi');
      shipped.forEach((config, cpv) {
        expect(cpv, r'"$(FLUTTER_BUILD_NUMBER)"',
            reason: '$config konfiguratsiyasida qotirilgan raqam: $cpv');
      });
    });
  });

  group('Reliz skripti — build raqamini PUBSPEC`dan oladi', () {
    final script = _f('../../scripts/release_ios.sh');

    test('skript versiya nazoratida MAVJUD', () {
      expect(script.existsSync(), isTrue,
          reason: 'toza clone bir xil metadata hosil qilishi uchun skript tracked bo`lishi kerak');
    });

    test('skript raqamni pubspec`dan o`qiydi va qo`lda berilganini RAD etadi', () {
      final src = script.readAsStringSync();
      expect(src, contains('pubspec.yaml'),
          reason: 'raqam pubspec`dan olinishi kerak, buyruq satridan emas');
      expect(src, contains('BINOS_PRIVACY_URL'),
          reason: 'maxfiylik darvozasi skriptda bo`lishi kerak');
      expect(src, contains('set -euo pipefail'),
          reason: 'har qanday xato relizni TO`XTATISHI kerak');
      expect(src, contains('BINOS_BUILD_NUMBER'),
          reason: 'qo`lda berilgan raqam ANIQ rad etilishi kerak');
    });

    test('RATCHET: skript chegaralari shu testdagi konstantalar bilan AYNI', () {
      // ⚠️  Ikki joyda raqam bor (bu test va skript). Ular ayrilib ketmasligi
      //     uchun skript qiymatlari shu yerda O'QILADI va solishtiriladi:
      //     chegarani faqat bir joyda o'zgartirsa — test yiqiladi.
      final src = script.readAsStringSync();
      int declared(String name) {
        final m = RegExp('readonly $name=(\\d+)').firstMatch(src);
        expect(m, isNotNull, reason: 'skriptda `readonly $name=` topilmadi');
        return int.parse(m!.group(1)!);
      }

      expect(declared('MIN_BUILD_EXCLUSIVE'), kHighestBuildOnAppStoreConnect,
          reason: 'skript va test ASC chegarasi bo`yicha ayrilib ketdi');
      final burned = RegExp('readonly BURNED_BUILDS="([0-9 ]+)"').firstMatch(src);
      expect(burned, isNotNull, reason: 'skriptda `readonly BURNED_BUILDS=` topilmadi');
      final fromScript = burned!
          .group(1)!
          .trim()
          .split(' ')
          .where((e) => e.isNotEmpty)
          .map(int.parse)
          .toSet();
      expect(fromScript, kBurnedLocalBuilds,
          reason: 'skript va test kuygan raqamlar bo`yicha ayrilib ketdi');
    });

    test('skript bajariladigan (executable) bo`lishi kerak', () {
      final mode = script.statSync().mode;
      expect(mode & 0x40, isNot(0), reason: 'egasi uchun execute biti yo`q — CI ishga tushira olmaydi');
    });
  });
}
