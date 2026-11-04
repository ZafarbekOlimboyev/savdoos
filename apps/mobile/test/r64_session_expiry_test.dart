// R6.4 — 12 soatlik token / 401 da LOKAL MA'LUMOT YO'QOLISHI reproduksiyasi.
//
// Bu testlar yangi xatti-harakat KIRITMAYDI: ular Build 65 dagi MAVJUD zanjirni
// o'lchaydi va hujjatlashtiradi. Zanjir (hammasi joriy kodda):
//
//   apps/server/app/core/config.py:15   access_token_minutes = 720  (12 soat)
//   apps/server/app/core/config.py:16   refresh_token_days — E'LON QILINGAN, LEKIN
//                                       hech qayerda ishlatilmaydi
//     => har qanday qurilma KAMIDA 12 soatda bir marta 401 oladi
//
//   lib/main.dart:39-48    Api.onSessionExpired = () { Lock.clear(); push(Login) }
//   lib/api.dart:832-845   token bilan ketgan HAR QANDAY 401 -> _clearLocal(...)
//   lib/api.dart:391-392   Keychain'dan `token` + `employee`
//   lib/lock.dart:404-413  Keychain'dan pin_hash, pin_salt, biometric_on,
//                          lock_on, fail_count, lock_until
//
// Testlar token muddatini CHETLAB O'TMAYDI — ular 401 javobining LOKAL
// oqibatini o'lchaydi, ya'ni muddati o'tgan token serverdan nima qaytarsa
// o'shani. Server tomonidagi `exp` tekshiruvi pytest bilan qoplangan.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

const _editor = ['xaridlar.view', 'xaridlar.edit'];

/// `lib/main.dart:39-48` dagi PRODUCTION ishlovchisini aynan takrorlaydi.
void _installProductionHandler() {
  Api.onSessionExpired = () {
    unawaited(Lock.clear());
    leaveToLogin();
  };
}

/// `unawaited(Lock.clear())` tugashini kutadi (main.dart ham `unawaited` qiladi).
Future<void> _settleClear() async {
  for (var i = 0; i < 8; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

FakeResponse _expired() =>
    FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring');

void main() {
  setUp(() async {
    await resetCore();
    PendingCorrectionKeys.clear();
  });

  group('R6.4-1. 401 Keychain\'ni tozalaydi', () {
    test('muddati o\'tgan tokenning 401\'i PIN, tuz va biometrikani o\'chiradi', () async {
      // Arrange — xodim PIN va biometrika sozlab, ishlab turgan holat.
      await Lock.setPin('1234');
      await Lock.setBiometric(true);
      expect(Lock.status, LockStatus.valid, reason: 'PIN o\'rnatildi');
      expect(Lock.hasPin, isTrue);
      expect(Lock.biometricOn, isTrue);
      signIn();
      _installProductionHandler();

      // Act — serverda token muddati tugagan (12 soat o'tgan): har qanday
      // chaqiruv 401 qaytaradi.
      final be = FakeBackend()..get('/products', (_) => _expired());
      await be.run(() async {
        await expectLater(
          Api.getJson('/products'),
          throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.auth)),
        );
      });
      await _settleClear();

      // Assert — PIN YO'Q, biometrika o'chgan, sessiya tugagan.
      expect(Lock.status, LockStatus.absent, reason: 'PIN Keychain\'dan o\'chdi');
      expect(Lock.hasPin, isFalse);
      expect(Lock.biometricOn, isFalse, reason: 'biometrika sozlamasi ham ketdi');
      expect(Api.token, isNull);
      expect(Api.employee, isNull);
    });

    test('/auth/context 401: sessiya va qulf BIRGA tozalanadi', () async {
      await Lock.setPin('5678');
      signIn();
      _installProductionHandler();

      // Ilova har sovuq start'da shu chaqiruvni qiladi (session.dart:217 -> :304).
      final be = FakeBackend()..get('/auth/context', (_) => _expired());
      await be.run(() async {
        await Session.instance.load(force: true);
      });
      await _settleClear();

      expect(Api.token, isNull, reason: '/auth/context 401 ham sessiyani tugatadi');
      expect(Lock.hasPin, isFalse, reason: 'PIN birga ketadi');
    });

    test('401 dan OZOD yo\'llar: login va parol almashtirish tozalamaydi', () async {
      await Lock.setPin('1234');
      signIn();
      _installProductionHandler();

      final be = FakeBackend()
        ..post('/auth/login/password', (_) => _expired())
        ..post('/auth/password', (_) => _expired());
      await be.run(() async {
        await expectLater(Api.postJson('/auth/login/password', {}), throwsA(isA<ApiException>()));
        await expectLater(Api.postJson('/auth/password', {}), throwsA(isA<ApiException>()));
      });
      await _settleClear();

      expect(Lock.hasPin, isTrue, reason: 'noto\'g\'ri parol PIN\'ni o\'chirmasligi kerak');
      expect(Api.token, isNotNull);
    });
  });

  group('R6.4-2. SAQLANMAGAN QORALAMA', () {
    // 401 -> Lock.clear() zanjiri R6.4-1 da tasdiqlangan. Bu yerda AYNI
    // `main.dart:39-48` dagi NAVIGATSIYA qadamining qoralamaga ta'siri
    // o'lchanadi: `pushAndRemoveUntil(..., (route) => false)`.
    testWidgets('sessiya tugashi qoralamani OGOHLANTIRISHSIZ yo\'q qiladi', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}',
            (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)));

      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        await tester.tap(find.descendant(
            of: find.byKey(const Key('pd-bar')),
            matching: find.byKey(const Key('sticky-primary'))));
        await tester.pumpAndSettle();
        expect(find.byType(CorrectionScreen), findsOneWidget);

        // Arrange — menejer qo'lda qoralama kiritadi (hech qayerda saqlanmaydi).
        const reason = 'Nakladnoyda 4 ta kam keldi, yetkazuvchi tasdiqladi';
        await tester.enterText(find.byKey(const Key('corr-reason')), reason);
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        expect(find.text(reason), findsOneWidget, reason: 'qoralama ekranda turadi');

        // Act — main.dart:39-48 ning navigatsiya qadami, AYNI shaklda.
        // (Fayzan, 2026-09-17: ega xodim parolini tikladi.)
        Lock.engaged.value = false;
        rootNavKey.currentState!.pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (route) => false,
        );
        await tester.pumpAndSettle();

        // Assert — qoralama YO'Q, ogohlantirish YO'Q.
        expect(find.byType(CorrectionScreen), findsNothing,
            reason: 'tahrirlovchi butunlay yo\'q qilindi');
        expect(find.text(reason), findsNothing, reason: 'kiritilgan matn YO\'QOLDI');
        expect(find.byType(LoginScreen), findsOneWidget);
        expect(find.textContaining('saqlanmagan', findRichText: true), findsNothing,
            reason: 'HECH QANDAY ogohlantirish korsatilmaydi');
      });
    });

    test('faqat idempotentlik kaliti saqlanadi — qoralama MAZMUNI emas', () async {
      signIn(role: 'menejer', permissions: _editor);
      _installProductionHandler();
      PendingCorrectionKeys.unknown('r1', 'uuid-saqlanadi');

      final be = FakeBackend()..get('/reports/overview', (_) => _expired());
      await be.run(() async {
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
      });
      await _settleClear();

      expect(PendingCorrectionKeys.of('r1'), 'uuid-saqlanadi',
          reason: 'takroriy yozuvdan himoya qiladi, lekin qoralamani TIKLAMAYDI');
      expect(Api.token, isNull, reason: 'sessiya tugadi');
    });
  });

  group('R6.4-3. qayta kirish va xodim almashishi', () {
    test('parol bilan qayta kirish: sessiya tiklanadi, lekin PIN YO\'Q', () async {
      await Lock.setPin('1234');
      signIn();
      _installProductionHandler();

      final be = FakeBackend()
        ..get('/products', (_) => _expired())
        ..post('/auth/login/password', (_) => {
              'access_token': 'yangi-token',
              'employee': {'id': 'e1', 'role_code': 'ega', 'permissions': <String>[]},
            });
      await be.run(() async {
        await expectLater(Api.getJson('/products'), throwsA(isA<ApiException>()));
        await _settleClear();
        expect(Lock.hasPin, isFalse);

        await Api.login('+998901234567', 'parol');
      });

      expect(Api.token, 'yangi-token', reason: 'parol bilan qayta kirildi');
      expect(Lock.hasPin, isFalse,
          reason: 'PIN tiklanmaydi — foydalanuvchi YANGISINI o\'rnatishi shart');
      expect(Lock.status, LockStatus.absent);
    });

    // ⚠️  O'LCHANGAN HAQIQAT: `Api.logout()` O'ZI qulfni tozalamaydi — u faqat
    //     token/xodim/katalogni o'chiradi (api.dart:360-369). Qulfni HAR BIR
    //     chaqiruvchi ALOHIDA tozalaydi:
    //       shell.dart:380-381 · settings_screen.dart:124-125
    //       pin_screens.dart:384-385 · lock_recovery_screen.dart:153-154
    //     Bu test shu shartnomani QOTIRADI: yangi chiqish yo'li qo'shilib
    //     `Lock.clear()` esdan chiqsa, keyingi xodim OLDINGISINING PIN'i bilan
    //     ocholadi — test shu paytda yiqiladi.
    test('Api.logout() O\'ZI qulfni tozalamaydi — chaqiruvchi Lock.clear() qilishi SHART', () async {
      signIn(id: 'eA');
      await Lock.setPin('1111');
      final be = FakeBackend()..post('/auth/logout', (_) => {'ok': true});
      await be.run(() async => Api.logout());

      expect(Api.token, isNull, reason: 'sessiya tugadi');
      expect(Lock.hasPin, isTrue,
          reason: 'PIN DISKDA QOLADI — Api.logout() uni o\'chirmaydi');
    });

    test('PRODUCTION chiqish yo\'li: A xodimning PIN\'i B ga O\'TMAYDI', () async {
      signIn(id: 'eA');
      await Lock.setPin('1111');
      expect(Lock.hasPin, isTrue);

      final be = FakeBackend()
        ..post('/auth/logout', (_) => {'ok': true})
        ..post('/auth/login/password', (_) => {
              'access_token': 'token-B',
              'employee': {'id': 'eB', 'role_code': 'kassir', 'permissions': <String>[]},
            });
      await be.run(() async {
        // shell.dart:380-381 dagi AYNI ikki qadam.
        await Api.logout();
        await Lock.clear();
        expect(Lock.hasPin, isFalse, reason: 'chiqish qulfni ham tozalaydi');

        await Api.login('+998900000000', 'parol-B');
      });

      expect(Api.employee?['id'], 'eB');
      expect(Lock.hasPin, isFalse, reason: 'B A\'ning PIN\'i bilan ocholmaydi');
      expect(Lock.status, LockStatus.absent);
    });
  });
}
