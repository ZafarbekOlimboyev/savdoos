// CH-17B — App Store relizi darvozalari: maxfiylik havolasi, iOS maxfiylik
// manifesti va reliz konfiguratsiyasi.
//
// ⚠️  BU RATCHET. Har bir tasdiq ATAYLAB qattiq: darvozani bo'shatish uchun shu
//     faylni O'ZGARTIRISH kerak, ya'ni ONGLI qadam bo'ladi. `android_manifest_test`
//     bilan AYNI falsafa.
//
// NEGA `Env` TOZA FUNKSIYA ORQALI SINALADI. `--dart-define` qiymatlari
// compile-time constant: test ichida ularni o'zgartirib bo'lmaydi. Shu bois
// `Env.buildBase`/`Env.releaseBlockers` toza funksiya sifatida e'lon qilingan
// va HAR kombinatsiya (reliz faqat bir marta kesiladigan holatlar ham) oddiy
// test bilan qoplanadi.
@TestOn('vm')
library;

import 'dart:io';

import 'package:savdoos_mobile/platform/env.dart';
import 'package:flutter_test/flutter_test.dart';

/// Loyiha ildizi (`apps/mobile`) — test `apps/mobile` dan ishga tushadi.
final Directory _root = Directory.current;

File _f(String rel) => File('${_root.path}/$rel');

void main() {
  group('Maxfiylik siyosati manzili — YAGONA tasdiqlangan qiymat', () {
    test('ochiq https manzil qabul qilinadi va oxirgi slash olib tashlanadi', () {
      expect(Env.normalizePrivacyUrl('https://example.uz/privacy'),
          'https://example.uz/privacy');
      expect(Env.normalizePrivacyUrl('https://example.uz/privacy/'),
          'https://example.uz/privacy');
      expect(Env.normalizePrivacyUrl('  https://example.uz/p  '),
          'https://example.uz/p');
    });

    test('BERILMAGAN qiymat uchun TAXMIN QILINMAYDI — bo`sh qaytadi', () {
      // ⚠️  Eng muhim band: o'ylab topilgan manzil App Store'ga O'LIK havola
      //     jo'natardi. Shu bois zaxira qiymat UMUMAN yo'q.
      expect(Env.normalizePrivacyUrl(''), '');
      expect(Env.normalizePrivacyUrl('   '), '');
    });

    test('http, sxemasiz va ishonchsiz host RAD etiladi', () {
      for (final bad in <String>[
        'http://example.uz/privacy', // ATS/ko'rib chiqish uchun yaroqsiz
        'example.uz/privacy', // sxema TAXMIN QILINMAYDI
        'https://localhost/privacy',
        'https://127.0.0.1/privacy',
        'https://mac.local/privacy',
        'https://server-not-configured.invalid/p',
        'https://binos.localhost/p',
        'https://nodot/privacy', // registrga yaroqsiz host
        'https://user:pw@example.uz/p', // ichida kredensial
      ]) {
        expect(Env.normalizePrivacyUrl(bad), '',
            reason: 'qabul qilinmasligi kerak: $bad');
      }
    });
  });

  group('Reliz darvozasi — `Env.releaseBlockers`', () {
    List<String> gate({
      String api = 'https://api.example.uz',
      String env = 'production',
      String privacy = 'https://example.uz/privacy',
    }) =>
        Env.releaseBlockers(apiBase: api, envName: env, privacyUrl: privacy);

    test('hammasi to`g`ri bo`lsa — darvoza OCHIQ', () {
      expect(gate(), isEmpty);
    });

    test('maxfiylik manzili YO`Q bo`lsa — reliz TO`SILADI', () {
      expect(gate(privacy: ''), hasLength(1));
      expect(gate(privacy: '').single, contains('BINOS_PRIVACY_URL'));
    });

    test('staging qurilishi App Store uchun TO`SILADI', () {
      expect(gate(env: 'staging').any((b) => b.contains('BINOS_ENV')), isTrue);
    });

    test('localhost / staging / http API manzili TO`SILADI', () {
      expect(gate(api: 'http://localhost:8000').length, greaterThanOrEqualTo(1));
      expect(gate(api: 'https://127.0.0.1:8000')
          .any((b) => b.contains('developer machine')), isTrue);
      expect(gate(api: Env.kUnsetNonProductionBase)
          .any((b) => b.contains('sentinel')), isTrue);
      expect(gate(api: 'http://api.example.uz')
          .any((b) => b.contains('plain http')), isTrue);
      expect(gate(api: '').any((b) => b.contains('empty')), isTrue);
    });

    test('⚠️  HOZIRGI QURILISH: manzil berilmagani uchun darvoza YOPIQ', () {
      // Bu test HOZIR o'tadi, chunki `BINOS_PRIVACY_URL` hali berilmagan.
      // Ega manzilni bergandan keyin u YIQILADI va shu yerdagi kutilgan
      // natijani ONGLI ravishda yangilash kerak bo'ladi — bu ratchet.
      expect(Env.releaseBlockersForThisBuild, isNotEmpty,
          reason: 'manzil berilmagan qurilish relizga tayyor BO`LMASLIGI kerak');
      expect(Env.isPrivacyPolicyConfigured, isFalse);
    });
  });

  group('iOS maxfiylik manifesti — FAQAT tekshirilgan faktlar', () {
    final f = _f('ios/Runner/PrivacyInfo.xcprivacy');

    test('Runner manifesti MAVJUD', () {
      expect(f.existsSync(), isTrue,
          reason: 'ios/Runner/PrivacyInfo.xcprivacy topilmadi');
    });

    test('tracking FALSE va tracking domenlari BO`SH', () {
      final s = f.readAsStringSync();
      expect(s, contains('<key>NSPrivacyTracking</key>'));
      expect(RegExp(r'<key>NSPrivacyTracking</key>\s*<false/>').hasMatch(s), isTrue,
          reason: 'reklama/analitika SDK yo`q — tracking false bo`lishi SHART');
      expect(RegExp(r'<key>NSPrivacyTrackingDomains</key>\s*<array/>').hasMatch(s),
          isTrue);
    });

    test('Runner kodi required-reason API ishlatmasligi SAQLANADI', () {
      // Manifestda `NSPrivacyAccessedAPITypes` BO'SH — bu Runner'ning O'Z
      // kodida shunday API YO'Q degan FAKTGA tayanadi. Agar kimdir
      // AppDelegate/SceneDelegate ga UserDefaults yoki disk space qo'shsa, bu
      // test YIQILADI va manifestni yangilashga MAJBUR qiladi.
      final banned = RegExp(
          r'\b(UserDefaults|NSUserDefaults|systemUptime|mach_absolute_time|'
          r'statfs|volumeAvailableCapacity|activeInputModes|'
          r'contentModificationDate|creationDate)\b');
      for (final name in ['AppDelegate.swift', 'SceneDelegate.swift']) {
        final src = _f('ios/Runner/$name');
        if (!src.existsSync()) continue;
        expect(banned.hasMatch(src.readAsStringSync()), isFalse,
            reason: '$name required-reason API ishlatadi — manifestga '
                'TEKSHIRILGAN sabab kodi bilan yozilishi SHART');
      }
      final s = f.readAsStringSync();
      expect(RegExp(r'<key>NSPrivacyAccessedAPITypes</key>\s*<array/>').hasMatch(s),
          isTrue);
    });

    test('manifest Xcode RESURSLARIGA ulangan (bundle`ga kiradi)', () {
      // Fayl diskda bo'lishi YETARLI EMAS: Resources build phase'da bo'lmasa
      // u `.app` ichiga TUSHMAYDI va Apple uni ko'rmaydi.
      final pbx = _f('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();
      expect(pbx, contains('PrivacyInfo.xcprivacy in Resources'),
          reason: 'manifest Resources build phase`da yo`q — bundle`ga kirmaydi');
      expect(pbx, contains('path = PrivacyInfo.xcprivacy'));
    });
  });

  group('iOS reliz konfiguratsiyasi', () {
    test('Info.plist maqsad satrlari MAVJUD va bo`sh emas', () {
      final s = _f('ios/Runner/Info.plist').readAsStringSync();
      for (final k in [
        'NSCameraUsageDescription',
        'NSPhotoLibraryUsageDescription',
        'NSFaceIDUsageDescription',
      ]) {
        final m = RegExp('<key>$k</key>\\s*<string>([^<]*)</string>').firstMatch(s);
        expect(m, isNotNull, reason: '$k yo`q');
        expect(m!.group(1)!.trim().length, greaterThan(10),
            reason: '$k juda qisqa — Apple sababni tushuntirishni talab qiladi');
      }
    });

    test('⚠️  shifrlash deklaratsiyasi HALI YO`Q — ega faktik qaroriga bog`liq', () {
      // `ITSAppUsesNonExemptEncryption` — EKSPORT-HUQUQIY deklaratsiya, uni
      // taxmin qilib yozish mumkin EMAS. Bu test holatni QAYD etadi: kalit
      // qo'shilganda test yiqiladi va qaror ONGLI yozilganini tasdiqlaydi.
      final s = _f('ios/Runner/Info.plist').readAsStringSync();
      expect(s.contains('ITSAppUsesNonExemptEncryption'), isFalse,
          reason: 'kalit qo`shildi — ega qarori hujjatlashtirilganini '
              'tasdiqlab, shu testni yangilang');
    });

    test('url_launcher e`lon qilingan, bog`liq bo`lmagan paketlar TEGILMAGAN', () {
      final spec = _f('pubspec.yaml').readAsStringSync();
      expect(RegExp(r'^\s+url_launcher:\s').hasMatch(spec) ||
             spec.contains('\n  url_launcher:'), isTrue,
          reason: 'url_launcher pubspec`da yo`q');
      final lock = _f('pubspec.lock').readAsStringSync();
      for (final p in ['url_launcher:', 'url_launcher_ios:']) {
        expect(lock, contains('  $p'), reason: '$p lock`da yo`q');
      }
    });
  });
}
