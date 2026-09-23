// M5 — settings (who am I: role / company / branch, my permissions, manual
// session refresh, server change, logout) and the login screen's error UX.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Lets real IO complete, then pumps frames. Api purges the legacy catalog
/// cache files on logout / server change (a directory listing + deletes: SEVERAL
/// real-IO steps), and each step's continuation runs in the fake-async zone —
/// so real-IO turns and fake pumps are interleaved until nothing is left.
Future<void> flushIo(WidgetTester tester) async {
  for (var i = 0; i < 16; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Scrolls the settings list to [key] and taps it.
Future<void> tapRow(WidgetTester tester, String key) async {
  final f = find.byKey(Key(key));
  if (f.evaluate().isEmpty) {
    // Not built yet (lazy list): scroll the settings list down to it.
    await tester.scrollUntilVisible(f, 300,
        scrollable: find.descendant(of: find.byType(SettingsScreen), matching: find.byType(Scrollable)).first);
  }
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await tester.pumpAndSettle();
}

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    await Lock.clear();
    be = FakeBackend();
  });

  tearDown(() async {
    s.debugReset();
    await Lock.clear();
  });

  Future<void> signInAs(String role, {List<String> perms = const [], String name = 'Aziz Karimov'}) async {
    signIn(role: role, permissions: perms);
    be.get('/auth/context', (_) => contextJson(role: role, permissions: perms, fullName: name));
    await s.load(force: true);
  }

  group('settings', () {
    testWidgets('profile shows name, localized role and company; rows are 48dp+', (tester) async {
      L.code = 'ru';
      await be.run(() async {
        await signInAs('menejer', perms: ['hisobot.view']);
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
      });
      expect(find.text('Aziz Karimov'), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('settings-role'))).data, tr('Menejer'));
      expect(tr('Menejer'), isNot('Menejer'));
      expect(tester.widget<Text>(find.byKey(const Key('settings-company'))).data, 'Fayzan');
      for (final k in ['settings-branch', 'settings-perms', 'settings-refresh', 'settings-language', 'settings-server']) {
        expectMinTouchTarget(tester, find.byKey(Key(k)));
      }
    });

    testWidgets('"my permissions": labels for a limited role', (tester) async {
      await be.run(() async {
        await signInAs('omborchi', perms: ['ombor.edit', 'xaridlar.view']);
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        await tapRow(tester, 'settings-perms');
        expect(find.text('Ombor amallari'), findsOneWidget);
        expect(find.text('Xaridlarni ko‘rish'), findsOneWidget);
        expect(find.textContaining('ombor.edit'), findsNothing, reason: 'codes are never shown raw');
      });
    });

    testWidgets('"my permissions": a single line for full access', (tester) async {
      await be.run(() async {
        await signInAs('ega');
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        await tapRow(tester, 'settings-perms');
        expect(find.text('Ega — barcha ruxsatlarga ega.'), findsOneWidget);
      });
    });

    testWidgets('manual refresh reloads /auth/context; a failure is reported, the old context kept', (tester) async {
      var calls = 0;
      await be.run(() async {
        signIn(role: 'menejer');
        be.get('/auth/context', (_) {
          calls++;
          return contextJson(role: 'menejer', permissions: calls > 1 ? ['hisobot.view', 'xodimlar.view'] : ['hisobot.view']);
        });
        await s.load(force: true);
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('settings-employees')), findsNothing);

        await tapRow(tester, 'settings-refresh');
        expect(calls, 2);
        expect(find.text('Ma’lumotlar yangilandi'), findsOneWidget);
        expect(find.byKey(const Key('settings-employees')), findsOneWidget, reason: 'new permission visible at once');

        be.offline = true;
        await tapRow(tester, 'settings-refresh');
        expect(find.textContaining('Server bilan aloqa yo‘q'), findsWidgets);
        expect(s.status, SessionStatus.ready);
        expect(find.byKey(const Key('settings-employees')), findsOneWidget);
      });
    });

    testWidgets('changing the server warns first, then signs out (token and PIN of the old server dropped)',
        (tester) async {
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      await be.run(() async {
        await signInAs('ega');
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        await tapRow(tester, 'settings-server');
        expect(find.text('Server almashsa, hisobdan chiqasiz va qayta kirishingiz kerak bo‘ladi.'), findsOneWidget);
        await tester.enterText(find.byKey(const Key('server-url')), 'staging.example.test/api/v1/');
        await tester.tap(find.byKey(const Key('server-save')));
        await flushIo(tester);
      });
      expect(Api.baseUrl, 'https://staging.example.test');
      expect(Api.token, isNull);
      expect(expired, 1);
    });

    testWidgets('logout asks for confirmation, clears the PIN lock and opens the login screen', (tester) async {
      await Lock.setPin('1234');
      be.post('/auth/logout', (_) => {'ok': true});
      await be.run(() async {
        await signInAs('ega');
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        await tapRow(tester, 'settings-logout');
        expect(find.byKey(const Key('confirm-no')), findsOneWidget, reason: 'confirmation sheet opened');
        await tester.tap(find.byKey(const Key('confirm-no')));
        await tester.pumpAndSettle();
        expect(Api.token, isNotNull, reason: 'cancel keeps the session');

        await tapRow(tester, 'settings-logout');
        expect(find.byKey(const Key('confirm-yes')), findsOneWidget, reason: 'confirmation sheet opened again');
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await flushIo(tester);
        await flushIo(tester);
      });
      expect(be.calls('POST', '/auth/logout'), hasLength(1));
      expect(Api.token, isNull);
      expect(Lock.hasPin, isFalse);
      expect(find.byType(LoginScreen), findsOneWidget);
    });

    testWidgets('language switch from settings', (tester) async {
      await be.run(() async {
        await signInAs('ega');
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();
        await tapRow(tester, 'settings-language');
        expectMinTouchTarget(tester, find.byKey(const Key('lang-ky')));
        await tester.tap(find.byKey(const Key('lang-ky')));
        await tester.pumpAndSettle();
      });
      expect(L.code, 'ky');
    });
  });

  group('login', () {
    Future<void> submit(WidgetTester tester) async {
      await tester.enterText(find.byKey(const Key('login-phone')), '+996 700 123 456');
      await tester.enterText(find.byKey(const Key('login-password')), 'secret-password');
      await tester.tap(find.byKey(const Key('login-submit')));
      await tester.pumpAndSettle();
    }

    String errorText(WidgetTester tester) => tester.widget<Text>(find.byKey(const Key('login-error'))).data!;

    testWidgets('wrong credentials -> the single "wrong phone or password" message', (tester) async {
      be.post('/auth/login/password', (_) => FakeResponse.error(401, "Kirish ma'lumotlari noto'g'ri"));
      await be.run(() async {
        await pumpAt390(tester, const LoginScreen());
        await submit(tester);
      });
      expect(errorText(tester), 'Telefon yoki parol noto‘g‘ri');
      expect(Api.token, isNull);
    });

    testWidgets('server unreachable is NOT reported as a wrong password', (tester) async {
      be.offline = true;
      await be.run(() async {
        await pumpAt390(tester, const LoginScreen());
        await submit(tester);
      });
      expect(errorText(tester), isNot('Telefon yoki parol noto‘g‘ri'));
      expect(errorText(tester), contains('Server bilan aloqa yo‘q'));
    });

    testWidgets('rate limit (429) is explained in the UI language', (tester) async {
      L.code = 'ru';
      be.post('/auth/login/password',
          (_) => FakeResponse.error(429, "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring"));
      await be.run(() async {
        await pumpAt390(tester, const LoginScreen());
        await submit(tester);
      });
      expect(errorText(tester), 'Аккаунт временно заблокирован — попробуйте через 15 минут');
    });

    testWidgets('success without a PIN -> PIN setup (session token stored)', (tester) async {
      be.post('/auth/login/password', (_) => {
            'access_token': 'NEW',
            'employee': {'id': 'e1', 'full_name': 'Aziz', 'role_code': 'ega', 'permissions': []},
          });
      await be.run(() async {
        await pumpAt390(tester, const LoginScreen());
        await submit(tester);
      });
      expect(Api.token, 'NEW');
      expect(find.byType(PinSetupScreen), findsOneWidget);
    });
  });
}
