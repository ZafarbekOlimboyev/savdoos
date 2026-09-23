// M5 — session lifecycle in the shell: refresh of /auth/context on resume
// (permissions and branches follow the server), re-lock after a long
// background stay, 401 handling, and the lock screen overlay.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

Map<ShellTab, WidgetBuilder> fakeTabs() => {
      ShellTab.home: (_) => const Center(child: Text('HOME-TAB')),
      ShellTab.stock: (_) => const Center(child: Text('STOCK-TAB')),
      ShellTab.analytics: (_) => const Center(child: Text('ANALYTICS-TAB')),
    };

/// Pumps frames for [total] (platform-channel futures + transitions) without
/// requiring every animation to stop (a spinner never settles).
Future<void> settleFrames(WidgetTester tester, {Duration total = const Duration(seconds: 1)}) async {
  const step = Duration(milliseconds: 50);
  for (var t = Duration.zero; t < total; t += step) {
    await tester.pump(step);
  }
}

Future<void> enterPin(WidgetTester tester, String pin) async {
  for (final d in pin.split('')) {
    await tester.tap(find.text(d).last);
    await tester.pump();
  }
  await tester.pumpAndSettle();
}

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()..get('/inventory/overview', (_) => {'low_count': 0, 'out_count': 0});
    await Lock.clear();
    Lock.relockAfter = const Duration(minutes: 3);
    Lock.debugResetBackground();
  });

  tearDown(() async {
    s.debugReset();
    Session.resumeRefreshAfter = const Duration(seconds: 20);
    Lock.relockAfter = const Duration(minutes: 3);
    await Lock.clear();
  });

  group('Lock: background re-lock rule', () {
    test('only after a long background stay and only when the lock is on', () async {
      final t0 = DateTime(2026, 9, 19, 10);
      expect(Lock.consumeResume(t0), isFalse, reason: 'never backgrounded');
      Lock.markBackground(t0);
      expect(Lock.consumeResume(t0.add(const Duration(minutes: 10))), isFalse, reason: 'no PIN set');

      await Lock.setPin('2468');
      Lock.markBackground(t0);
      expect(Lock.consumeResume(t0.add(const Duration(minutes: 2))), isFalse, reason: 'camera / share sheet: short');
      Lock.markBackground(t0);
      Lock.markBackground(t0.add(const Duration(minutes: 2))); // first mark wins
      expect(Lock.consumeResume(t0.add(const Duration(minutes: 3))), isTrue);
      expect(Lock.consumeResume(t0.add(const Duration(hours: 1))), isFalse, reason: 'the mark is consumed');

      await Lock.setLockEnabled(false);
      Lock.markBackground(t0);
      expect(Lock.consumeResume(t0.add(const Duration(hours: 1))), isFalse, reason: '"PIN on open" switched off');

      await Lock.setLockEnabled(true);
      Lock.markBackground(t0);
      await Lock.clear(); // logout / 401
      expect(Lock.consumeResume(t0.add(const Duration(hours: 1))), isFalse);
    });
  });

  testWidgets('long background stay -> PIN overlay; unlocking returns to the same screen', (tester) async {
    await be.run(() async {
      await Lock.setPin('2468');
      Lock.relockAfter = Duration.zero;
      signIn();
      be.get('/auth/context', (_) => contextJson());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-stock')));
      await tester.pumpAndSettle();
      expect(find.text('STOCK-TAB'), findsOneWidget);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(find.byType(LockScreen), findsOneWidget);
      await enterPin(tester, '1111');
      expect(find.byType(LockScreen), findsOneWidget, reason: 'wrong PIN keeps it locked');
      await enterPin(tester, '2468');
      expect(find.byType(LockScreen), findsNothing);
      expect(find.text('STOCK-TAB'), findsOneWidget, reason: 'back where the operator was');
    });
  });

  testWidgets('short background stay (camera, share) does not lock', (tester) async {
    await be.run(() async {
      await Lock.setPin('2468');
      Lock.relockAfter = const Duration(hours: 1);
      signIn();
      be.get('/auth/context', (_) => contextJson());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.byType(LockScreen), findsNothing);
      expect(find.text('HOME-TAB'), findsOneWidget);
    });
  });

  testWidgets('resume reloads /auth/context: a new permission shows its tab, a removed branch disappears',
      (tester) async {
    var perms = <String>['ombor.view'];
    var branches = [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')];
    var calls = 0;
    await be.run(() async {
      signIn(role: 'menejer');
      be.get('/auth/context', (_) {
        calls++;
        return contextJson(
            role: 'menejer', permissions: perms, branches: branches, actorBranch: branchJson('b1', 'Markaz'));
      });
      s.attach();
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tab-analytics')), findsNothing);
      await s.selectBranch('b2');
      await tester.pumpAndSettle();

      // The owner grants hisobot.view and unassigns branch B meanwhile.
      perms = ['ombor.view', 'hisobot.view'];
      branches = [branchJson('b1', 'Markaz')];
      Session.resumeRefreshAfter = Duration.zero;
      final before = calls;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(calls, greaterThan(before));
      expect(find.byKey(const Key('tab-analytics')), findsOneWidget);
      expect(s.currentBranchId, 'b1', reason: 'an invisible branch is never kept');
      expect(find.descendant(of: find.byKey(const Key('branch-chip')), matching: find.text('Markaz')), findsOneWidget);
    });
  });

  testWidgets('401 from any request signs the session out: the shell drops every tab', (tester) async {
    var expired = 0;
    Api.onSessionExpired = () => expired++;
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => contextJson());
      s.attach();
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      expect(find.text('HOME-TAB'), findsOneWidget);

      be.get('/reports/overview', (_) => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring'));
      // Api drops the token FIRST, then purges the catalog cache files (real
      // IO) and only then signs the UI out (`onSessionExpired`): this part runs
      // outside the fake-async test zone and waits for BOTH.
      await tester.runAsync(() => be.run(() async {
            await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
            for (var i = 0; i < 100 && (Api.token != null || expired == 0); i++) {
              await Future<void>.delayed(const Duration(milliseconds: 20));
            }
          }));
      await settleFrames(tester);
      expect(Api.token, isNull);
      expect(expired, 1);
      expect(s.status, SessionStatus.signedOut);
      expect(find.text('HOME-TAB'), findsNothing, reason: 'no data of the expired session stays on screen');
      expect(find.byKey(const Key('shell-loading')), findsOneWidget);
    });
  });

  testWidgets('cold-start lock screen shows the name from the session and unlocks into the shell', (tester) async {
    await be.run(() async {
      await Lock.setPin('1357');
      signIn(fullName: 'Snapshot Name');
      be.get('/auth/context', (_) => contextJson(fullName: 'Aziz Karimov'));
      await s.load(force: true);
      await pumpAt390(tester, const LockScreen());
      await tester.pumpAndSettle();
      expect(find.text('Aziz Karimov'), findsOneWidget);
      for (final d in '1357'.split('')) {
        await tester.tap(find.text(d).last);
        await tester.pump();
      }
      await settleFrames(tester); // route transition (real tabs may animate forever: no pumpAndSettle)
      expect(find.byType(Shell), findsOneWidget);
      expect(find.byType(LockScreen), findsNothing);
    });
  });
}
