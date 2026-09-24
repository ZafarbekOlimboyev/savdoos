// C2 item 2 — staging and production are told apart at a glance.
//
// Production is the OLDER server SHA carrying the live Fayzan tenant. Until
// now a "staging APK" and a "production APK" were byte-identical, both pointed
// at production, and nothing on screen said which server was in use: a pilot
// tester was one tap away from writing into live merchant data with no cue.
//
// The contract: a build is cut with `--dart-define=BINOS_ENV=…` /
// `BINOS_API_BASE=…` (B4's `Env`); a non-production build wears an unmissable
// marker in the shell and names its environment and API host in Settings; a
// production build shows NEITHER — the production widget tree must be exactly
// what it was before this phase.
//
// Two layers on purpose:
//   * the widget behaviour is driven through `EnvBadge.debugStagingOverride`,
//     so both branches are covered in an ordinary `flutter test` run;
//   * the last test takes the override away and asserts the marker follows the
//     COMPILE-TIME `Env` — it passes in the plain run (production, no marker)
//     and in the `--dart-define=BINOS_ENV=staging` run (marker), which is what
//     proves the build flag is really wired to the UI.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/main.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/ui/ui.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get('/auth/context', (_) => contextJson(role: 'ega', permissions: const ['hisobot.view', 'ombor.view']))
      ..get('/inventory/overview', (_) => {'low_count': 0, 'out_count': 0});
    addTearDown(() {
      EnvBadge.debugStagingOverride = null;
      s.debugReset();
    });
  });

  Future<void> openShell(WidgetTester tester) async {
    signIn();
    await s.load(force: true);
    await pumpAt390(tester, Shell(tabBuilders: {ShellTab.home: (_) => const SizedBox.shrink()}));
    await tester.pumpAndSettle();
  }

  // The marker lives at the APP ROOT (`main.dart`), not in the shell: the
  // screen that asks for the password is exactly where a tester must see which
  // server is being addressed, and an upgraded phone can still carry a stored
  // server address from its previous install.
  group('root marker', () {
    testWidgets('the LOGIN screen of a staging build already names the server', (tester) async {
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      Api.token = null; // not signed in -> the app opens on the login screen
      setPhoneViewport(tester);
      await tester.pumpWidget(const SavdoApp());
      await tester.pump();

      final badge = find.byKey(const Key('env-badge'));
      expect(badge, findsOneWidget, reason: 'the marker must be there BEFORE the password is typed');
      expect(find.descendant(of: badge, matching: find.textContaining('STAGING')), findsOneWidget);
      expect(find.descendant(of: badge, matching: find.textContaining('staging.example.test')), findsOneWidget,
          reason: 'the marker must name the server, not just the word STAGING');
    });

    testWidgets('a production build shows nothing and its layout is untouched', (tester) async {
      EnvBadge.debugStagingOverride = false;
      Api.token = null;
      setPhoneViewport(tester);
      await tester.pumpWidget(const SavdoApp());
      await tester.pump();

      expect(find.byKey(const Key('env-badge')), findsNothing);
      expect(find.textContaining('STAGING'), findsNothing);
      expect(find.byType(EnvBadge), findsNothing,
          reason: 'production must not even build the marker widget — no layout change at all');
    });

    testWidgets('the shell draws no second marker of its own', (tester) async {
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      await be.run(() => openShell(tester));
      expect(find.byType(EnvBadge), findsNothing,
          reason: 'the shell pumped alone must carry no marker — one is drawn at the root, '
              'and two would mean two strips on a real phone');
    });
  });

  group('settings', () {
    Future<void> openSettings(WidgetTester tester) async {
      signIn();
      await s.load(force: true);
      await pumpAt390(tester, const SettingsScreen());
      await tester.pumpAndSettle();
    }

    testWidgets('a staging build names the environment and the API host', (tester) async {
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      await be.run(() => openSettings(tester));

      final row = find.byKey(const Key('settings-env'));
      expect(row, findsOneWidget);
      expect(find.descendant(of: row, matching: find.textContaining('STAGING')), findsOneWidget);
      expect(find.descendant(of: row, matching: find.textContaining('staging.example.test')), findsOneWidget);
      expectMinTouchTarget(tester, row);
    });

    testWidgets('a production build shows no environment row', (tester) async {
      EnvBadge.debugStagingOverride = false;
      await be.run(() => openSettings(tester));
      expect(find.byKey(const Key('settings-env')), findsNothing);
    });

    testWidgets('the version line carries the build number — the part that tells two builds apart', (tester) async {
      EnvBadge.debugStagingOverride = false;
      await be.run(() => openSettings(tester));
      // The fake package info reports 0.6.30 / build 55. The footer is the
      // last row of a lazy list, so scroll to it first.
      await tester.scrollUntilVisible(find.textContaining('0.6.30'), 300,
          scrollable: find.descendant(of: find.byType(SettingsScreen), matching: find.byType(Scrollable)).first);
      await tester.pumpAndSettle();
      expect(find.textContaining('0.6.30+55'), findsOneWidget,
          reason: 'versionName alone cannot distinguish two builds of the same version');
    });
  });

  testWidgets('the marker follows the COMPILE-TIME environment, not a runtime guess', (tester) async {
    EnvBadge.debugStagingOverride = null;
    expect(EnvBadge.visible, Env.isStaging);
    await be.run(() => openShell(tester));
    expect(find.byKey(const Key('env-badge')), Env.isStaging ? findsOneWidget : findsNothing);
  });
}
