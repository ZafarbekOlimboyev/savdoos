// Own password change (`POST /auth/password`): the app mirrors only the length
// limits the server states (password_policy.py MIN_LEN=12, MAX_BYTES=72); every
// other rule is the server's, and its refusal is shown localized, never raw.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/password_change_screen.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore(lang: 'ru');
    be = FakeBackend();
    signIn();
  });

  group('passwordLengthProblem mirrors the server limits', () {
    test('12 characters minimum, counted like the server (code points)', () {
      expect(kPasswordMinLength, 12);
      expect(passwordLengthProblem('a' * 11), 'Пароль слишком короткий — нужно не менее 12 символов.');
      expect(passwordLengthProblem('olma anor 12'), isNull);
      // 12 emoji = 12 code points (24 UTF-16 units, 48 bytes) -> long enough.
      expect(passwordLengthProblem('😀' * 12), isNull);
      expect(passwordLengthProblem('😀' * 11), isNotNull);
    });

    test('72 UTF-8 bytes maximum (bcrypt), empty is refused', () {
      expect(passwordLengthProblem(''), 'Введите новый пароль.');
      expect(passwordLengthProblem('a' * 72), isNull);
      expect(passwordLengthProblem('a' * 73), 'Пароль слишком длинный.');
      // 37 Cyrillic letters = 74 bytes.
      expect(passwordLengthProblem('ж' * 37), 'Пароль слишком длинный.');
    });
  });

  Future<void> open(WidgetTester tester) async {
    await pumpAt390(tester, LaunchHost(onPressed: (ctx) {
      Navigator.of(ctx).push(MaterialPageRoute(builder: (_) => const PasswordChangeScreen()));
    }));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
  }

  Future<void> fill(WidgetTester tester, {String old = 'eski-parol-123', required String pw, String? pw2}) async {
    await tester.enterText(find.byKey(const Key('pw-old')), old);
    await tester.enterText(find.byKey(const Key('pw-new')), pw);
    await tester.enterText(find.byKey(const Key('pw-new2')), pw2 ?? pw);
    await tester.pump();
  }

  Future<void> save(WidgetTester tester) async {
    await tester.ensureVisible(find.byKey(const Key('pw-save')));
    await tester.tap(find.byKey(const Key('pw-save')));
    await tester.pumpAndSettle();
  }

  String errorText(WidgetTester tester) => tester.widget<Text>(find.byKey(const Key('pw-error'))).data!;

  testWidgets('the old "6 characters" rule is gone: 11 characters are refused locally, nothing is sent',
      (tester) async {
    await be.run(() async {
      await open(tester);
      expect(find.textContaining('6'), findsNothing);
      expect(find.textContaining('Не менее 12 символов'), findsOneWidget); // helper under the field
      await fill(tester, pw: 'qisqa-parol');
      await save(tester);
    });
    expect(errorText(tester), 'Пароль слишком короткий — нужно не менее 12 символов.');
    expect(be.log, isEmpty);
  });

  testWidgets('current password is required and the repeat must match (no request)', (tester) async {
    await be.run(() async {
      await open(tester);
      await fill(tester, old: '', pw: 'yangi uzun ibora');
      await save(tester);
      expect(errorText(tester), 'Введите текущий пароль или PIN-код.');
      await fill(tester, pw: 'yangi uzun ibora', pw2: 'boshqa uzun ibora');
      await save(tester);
      expect(errorText(tester), 'Пароли не совпадают');
    });
    expect(be.log, isEmpty);
  });

  testWidgets('success sends old+new, keeps the device signed in with the new token and closes', (tester) async {
    be.post('/auth/password', (_) => {'ok': true, 'access_token': 'NEW-TOKEN'});
    await be.run(() async {
      await open(tester);
      await fill(tester, pw: 'tog‘ ortida quyosh');
      await save(tester);
    });
    expect(be.last('POST', '/auth/password').body, {'old_password': 'eski-parol-123', 'new_password': 'tog‘ ortida quyosh'});
    expect(Api.token, 'NEW-TOKEN');
    expect(find.byType(PasswordChangeScreen), findsNothing);
    expect(find.text('Пароль изменён ✓'), findsOneWidget);
  });

  testWidgets('a server policy refusal is shown translated, not as the raw Uzbek text', (tester) async {
    be.post('/auth/password', (_) => FakeResponse.error(400, "Parol qabul qilinmadi: juda ko'p uchraydigan qiymat"));
    await be.run(() async {
      await open(tester);
      await fill(tester, pw: 'password1234');
      await save(tester);
    });
    expect(errorText(tester), 'Пароль слишком простой — выберите другой.');
    expect(find.textContaining('qabul qilinmadi'), findsNothing);
    expect(find.byType(PasswordChangeScreen), findsOneWidget);
  });

  testWidgets('wrong current password (401) says so and does NOT log the user out', (tester) async {
    var expired = 0;
    Api.onSessionExpired = () => expired++;
    be.post('/auth/password', (_) => FakeResponse.error(401, "Joriy kredensial noto'g'ri"));
    await be.run(() async {
      await open(tester);
      await fill(tester, pw: 'yangi uzun ibora 2026');
      await save(tester);
    });
    expect(errorText(tester), 'Неверный текущий пароль (или PIN).');
    expect(Api.token, 'test-token');
    expect(expired, 0);
    L.code = 'uz';
  });
}
