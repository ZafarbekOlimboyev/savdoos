// R5.2 — reliz darvozasi SKRIPT darajasida ham to'sadi.
//
// ⚠️  NEGA BU TEST BOR. `Env.releaseBlockers` toza funksiya va u faqat
//     testdan chaqirilardi: arxivlashni HECH NARSA to'smasdi. Ya'ni
//     `BINOS_PRIVACY_URL` siz qurilgan IPA Sozlamalarida maxfiylik havolasi
//     BO'LMAGAN holda App Store'ga ketishi mumkin edi (Apple Guideline 5.1.1).
//
//     Endi darvoza `scripts/release_ios.sh` da va u arxivlashdan OLDIN
//     to'xtaydi. Bu test shu to'xtashni HAQIQIY exit code bilan tekshiradi.
//
//     Bu yerda FAQAT salbiy holatlar bor: hammasi qurilishdan OLDINGI
//     bosqichda yiqiladi, shuning uchun test tez. Pozitiv yo'l to'liq iOS
//     qurilishini talab qiladi va u relizda qo'lda/CI'da bajariladi.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Skriptni ishga tushiradi va `(exitCode, stdout+stderr)` qaytaradi.
///
/// `BINOS_PRIVACY_URL` muhit o'zgaruvchisi ATAYLAB o'chiriladi: test
/// mashinasida u o'rnatilgan bo'lsa, «URL yo'q» holati tekshirilmay qolardi.
({int code, String out}) _run(List<String> args, {Map<String, String> env = const {}}) {
  final r = Process.runSync(
    'bash',
    ['../../scripts/release_ios.sh', ...args],
    environment: {'BINOS_PRIVACY_URL': '', ...env},
    includeParentEnvironment: true,
    runInShell: false,
  );
  return (code: r.exitCode, out: '${r.stdout}${r.stderr}');
}

void main() {
  setUpAll(() {
    final f = File('../../scripts/release_ios.sh');
    expect(f.existsSync(), isTrue, reason: 'reliz skripti versiya nazoratida bo`lishi kerak');
  });

  group('Maxfiylik manzili — SALBIY holatlar relizni to`sadi', () {
    test('manzil BERILMAGAN -> exit != 0, qurilish BOSHLANMAYDI', () {
      final r = _run(const []);
      expect(r.code, isNot(0), reason: 'URL siz reliz davom etdi');
      expect(r.out, contains('BLOCKED'));
      expect(r.out, contains('BINOS_PRIVACY_URL'));
      expect(r.out, isNot(contains('flutter build')),
          reason: 'darvoza qurilishdan OLDIN to`xtashi kerak');
    });

    test('http:// RAD etiladi (ATS va App Review uchun yaroqsiz)', () {
      final r = _run(const ['--privacy-url', 'http://www.binos.uz/privacy']);
      expect(r.code, isNot(0));
      expect(r.out, contains('https'));
    });

    test('sxemasiz manzil RAD etiladi — sxema TAXMIN QILINMAYDI', () {
      final r = _run(const ['--privacy-url', 'www.binos.uz/privacy']);
      expect(r.code, isNot(0));
    });

    test('dasturchi mashinasi manzillari RAD etiladi', () {
      for (final u in const [
        'https://localhost/privacy',
        'https://127.0.0.1/privacy',
        'https://mac.local/privacy',
        'https://binos.invalid/privacy',
      ]) {
        final r = _run(['--privacy-url', u]);
        expect(r.code, isNot(0), reason: '$u qabul qilindi');
      }
    });

    test('ro`yxatga olinmaydigan host (nuqtasiz) RAD etiladi', () {
      final r = _run(const ['--privacy-url', 'https://binos/privacy']);
      expect(r.code, isNot(0));
    });

    test('manzilda login/parol bo`lsa RAD etiladi', () {
      final r = _run(const ['--privacy-url', 'https://u:p@www.binos.uz/privacy']);
      expect(r.code, isNot(0));
    });
  });

  group('Build raqami — faqat pubspec`dan', () {
    test('qo`lda berilgan BINOS_BUILD_NUMBER RAD etiladi', () {
      final r = _run(const ['--privacy-url', 'https://www.binos.uz/privacy'],
          env: const {'BINOS_BUILD_NUMBER': '99'});
      expect(r.code, isNot(0), reason: 'qo`lda berilgan raqam qabul qilindi');
      expect(r.out, contains('pubspec.yaml'));
    });

    test('skript pubspec`dagi raqamni O`QIYDI va ko`rsatadi', () {
      // Darvoza keyinroq (URL'da) yiqiladi, lekin 1-bosqich chiqishi raqamni
      // aytib bo'lgan bo'ladi — ya'ni manba AYNAN pubspec.
      final spec = File('pubspec.yaml').readAsStringSync();
      final m = RegExp(r'^version:\s*(\d+\.\d+\.\d+)\+(\d+)\s*$', multiLine: true).firstMatch(spec)!;
      final r = _run(const []);
      expect(r.out, contains('versiya ${m[1]}, build ${m[2]}'),
          reason: 'skript raqamni pubspec`dan olmadi');
    });
  });

  group('Skript o`zini himoyalaydi', () {
    test('noma`lum argument RAD etiladi (jim o`tkazib yuborilmaydi)', () {
      final r = _run(const ['--privacy-url', 'https://www.binos.uz/privacy', '--nonsense']);
      expect(r.code, isNot(0));
      expect(r.out, contains('noma`lum argument'.replaceAll('`', "'")));
    });

    test('--help exit 0 beradi va hech narsa qurmaydi', () {
      final r = _run(const ['--help']);
      expect(r.code, 0);
      expect(r.out, isNot(contains('BLOCKED')));
    });
  });
}
