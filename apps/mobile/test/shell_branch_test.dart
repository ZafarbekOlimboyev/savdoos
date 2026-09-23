// M5 — branch context in the shell: the current branch is always visible on
// branch-scoped tabs, switching rebuilds every branch-scoped tab (branch A data
// is never shown under branch B), analytics sends `branch_id`, the "Ombor"
// badge counts the CURRENT branch (`/inventory/overview?branch_id=`), and the
// session states (loading / error / old server) are explicit.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/analytics_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// A branch-scoped tab that remembers the branch it was BUILT for (like a
/// screen that loaded its data in initState).
class _Probe extends StatefulWidget {
  const _Probe(this.name);
  final String name;
  static final Map<String, int> inits = {};
  @override
  State<_Probe> createState() => _ProbeState();
}

class _ProbeState extends State<_Probe> {
  late final String loadedFor;
  @override
  void initState() {
    super.initState();
    _Probe.inits[widget.name] = (_Probe.inits[widget.name] ?? 0) + 1;
    loadedFor = Session.instance.currentBranchId ?? '-';
  }

  @override
  Widget build(BuildContext context) => Center(child: Text('${widget.name}:$loadedFor'));
}

Map<ShellTab, WidgetBuilder> probes() => {
      ShellTab.home: (_) => const _Probe('home'),
      ShellTab.stock: (_) => const _Probe('stock'),
    };

Map<String, dynamic> overviewJson(num sales) => {
      'kpi': {'sales': sales, 'profit': 0, 'avg_check': 0, 'tx': 1},
      'delta': {'sales': null, 'profit': null},
      'series': [],
      'top_products': [],
      'cashiers': [],
      'payments': [],
      'credit_total': 0,
    };

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    _Probe.inits.clear();
    be = FakeBackend()
      // Stock counts per branch: A=4+1, B=1+1, all visible branches=5+2.
      ..get(
          '/inventory/overview',
          (r) => switch (r.query['branch_id']) {
                'b1' => {'low_count': 4, 'out_count': 1},
                'b2' => {'low_count': 1, 'out_count': 1},
                _ => {'low_count': 5, 'out_count': 2},
              })
      ..get('/reports/categories', (_) => [])
      ..get(
          '/reports/dashboard',
          (_) => {
                'debt': {'total': 120000, 'paid_today': 0, 'debtors': 2}
              })
      ..get('/reports/hourly', (_) => [])
      ..get(
          '/reports/cashflow',
          (_) => {
                'in': {'jami': 10},
                'out': {},
                'noncash': {},
                'opening': 0,
                'kassada': 10
              })
      ..get('/sales', (_) => [])
      // Each branch has its own numbers: A=1 111 111, B=2 222 222, all=3 333 333.
      ..get(
          '/reports/overview',
          (r) => overviewJson(switch (r.query['branch_id']) {
                'b1' => 1111111,
                'b2' => 2222222,
                _ => 3333333,
              }));
  });

  tearDown(() => s.debugReset());

  Map<String, dynamic> twoBranches({String role = 'ega', String actor = 'b1'}) => contextJson(
        role: role,
        permissions: const ['hisobot.view', 'ombor.view', 'sotuvlar.view'],
        branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor', businessDate: '2026-09-20')],
        actorBranch: branchJson(actor, actor == 'b1' ? 'Markaz' : 'Chilonzor'),
      );

  Future<void> pickBranch(WidgetTester tester, String id) async {
    await tester.tap(find.byKey(const Key('branch-chip')).first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(Key('branch-option-$id')));
    await tester.pumpAndSettle();
  }

  testWidgets('current branch is shown on branch-scoped tabs; switching rebuilds them for the new branch',
      (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();

      expect(find.text('home:b1'), findsOneWidget);
      final chip = find.byKey(const Key('branch-chip'));
      expect(find.descendant(of: chip, matching: find.text('Markaz')), findsOneWidget);
      expectMinTouchTarget(tester, chip);

      // Visit the stock tab so it is alive, then switch the branch.
      await tester.tap(find.byKey(const Key('tab-stock')));
      await tester.pumpAndSettle();
      expect(find.text('stock:b1'), findsOneWidget);
      await pickBranch(tester, 'b2');

      expect(find.text('stock:b2'), findsOneWidget, reason: 'the visible tab is rebuilt for B');
      expect(find.text('stock:b1'), findsNothing, reason: 'branch A data never stays under B');
      expect(find.descendant(of: chip, matching: find.text('Chilonzor')), findsOneWidget);
      await tester.tap(find.byKey(const Key('tab-home')));
      await tester.pumpAndSettle();
      expect(find.text('home:b2'), findsOneWidget, reason: 'hidden tabs are rebuilt too');
      expect(find.text('home:b1'), findsNothing);
      expect(_Probe.inits, {'home': 2, 'stock': 2});
    });
  });

  testWidgets('settings tab has no branch header; the branch is switched there as well', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-settings')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('branch-chip')), findsNothing);
      expect(find.descendant(of: find.byKey(const Key('settings-business-date')), matching: find.textContaining('19')),
          findsOneWidget);
      await tester.tap(find.byKey(const Key('settings-branch')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('branch-option-b2')));
      await tester.pumpAndSettle();
      expect(s.currentBranchId, 'b2');
      expect(find.descendant(of: find.byKey(const Key('settings-branch')), matching: find.text('Chilonzor')),
          findsOneWidget);
      expect(find.byKey(const Key('settings-actor-branch')), findsOneWidget, reason: 'writes still go to Markaz');
      await tester.tap(find.byKey(const Key('tab-home')));
      await tester.pumpAndSettle();
      expect(find.text('home:b2'), findsOneWidget);
    });
  });

  testWidgets('a branch other than the actor branch explains where receiving/cash writes go', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('branch-actor-hint')), findsNothing);
      await pickBranch(tester, 'b2');
      final hint = find.byKey(const Key('branch-actor-hint'));
      expect(hint, findsOneWidget);
      expectMinTouchTarget(tester, hint);
      await tester.tap(hint);
      await tester.pumpAndSettle();
      expect(find.textContaining('«Chilonzor»'), findsOneWidget);
      expect(find.textContaining('«Markaz»'), findsWidgets);
      await tester.tap(find.byKey(const Key('branch-back-to-actor')));
      await tester.pumpAndSettle();
      expect(s.currentBranchId, 'b1');
      expect(find.text('home:b1'), findsOneWidget);
    });
  });

  testWidgets('analytics: overview and sales carry branch_id; "all branches" drops it; aggregated cards are labelled',
      (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-analytics')));
      await tester.pumpAndSettle();

      expect(be.last('GET', '/reports/overview').query, {'period': 'week', 'branch_id': 'b1'});
      expect(be.last('GET', '/sales').query, {'limit': '6', 'branch_id': 'b1'});
      expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b1'});
      expect(find.byKey(const Key('analytics-stock-alert')), findsOneWidget, reason: 'branch-scoped stock alert');
      expect(find.textContaining('1 111 111'), findsOneWidget);
      expect(find.text('Barcha filiallar'), findsWidgets, reason: 'scope toggle + labelled company-wide cards');

      // Switch branch -> analytics rebuilt, B numbers only.
      await pickBranch(tester, 'b2');
      expect(be.last('GET', '/reports/overview').query['branch_id'], 'b2');
      expect(find.textContaining('2 222 222'), findsOneWidget);
      expect(find.textContaining('1 111 111'), findsNothing);

      // All visible branches.
      await tester.tap(find.byKey(const Key('scope-all')));
      await tester.pumpAndSettle();
      expect(be.last('GET', '/reports/overview').query, {'period': 'week'});
      expect(be.last('GET', '/inventory/overview').query, isEmpty, reason: 'all visible branches: no branch_id');
      expect(find.textContaining('3 333 333'), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('scope-all')), min: 42);

      // Period change keeps the scope.
      await tester.tap(find.byKey(const Key('period-day')));
      await tester.pumpAndSettle();
      expect(be.last('GET', '/reports/overview').query, {'period': 'day'});
      await tester.tap(find.byKey(const Key('scope-branch')));
      await tester.pumpAndSettle();
      expect(be.last('GET', '/reports/overview').query, {'period': 'day', 'branch_id': 'b2'});
      expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b2'});
    });
  });

  testWidgets('analytics with one branch: no scope toggle, no "all branches" labels', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => contextJson());
      await s.load(force: true);
      await pumpAt390(tester, const AnalyticsScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scope-all')), findsNothing);
      expect(find.text('Barcha filiallar'), findsNothing);
      expect(be.last('GET', '/reports/overview').query, {'period': 'week', 'branch_id': 'b1'});
      expectMinTouchTarget(tester, find.byKey(const Key('analytics-export')));
    });
  });

  testWidgets('analytics: server error -> localized error with retry (no raw text)', (tester) async {
    var fail = true;
    be.get('/reports/overview',
        (_) => fail ? FakeResponse.error(500, 'Traceback (most recent call last) psycopg') : overviewJson(5));
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => contextJson());
      await s.load(force: true);
      await pumpAt390(tester, const AnalyticsScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('analytics-error')), findsOneWidget);
      expect(find.textContaining('Traceback'), findsNothing);
      fail = false;
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('analytics-error')), findsNothing);
      expect(find.textContaining('5'), findsWidgets);
    });
  });

  testWidgets('Ombor badge: shown for one visible branch, hidden when branches would be mixed', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => contextJson());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('stock-badge')), findsOneWidget);
      expect(find.text('5'), findsOneWidget);
    });
  });

  testWidgets('Ombor badge with several visible branches: counts the current branch, re-read on switch',
      (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      final badge = find.byKey(const Key('stock-badge'));
      expect(be.calls('GET', '/inventory/overview').map((c) => c.query), [
        {'branch_id': 'b1'}
      ]);
      expect(find.descendant(of: badge, matching: find.text('5')), findsOneWidget, reason: 'A: 4 low + 1 out');

      await pickBranch(tester, 'b2');
      expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b2'});
      expect(find.descendant(of: badge, matching: find.text('2')), findsOneWidget, reason: 'B: 1 low + 1 out');
      expect(find.descendant(of: badge, matching: find.text('5')), findsNothing, reason: 'A count never under B');
      expect(find.descendant(of: badge, matching: find.text('7')), findsNothing, reason: 'never the mixed sum');
    });
  });

  testWidgets('Ombor badge after a switch: the old count is cleared before the new one arrives', (tester) async {
    final gate = Completer<Object?>();
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => twoBranches());
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('stock-badge')), findsOneWidget);
      be.get('/inventory/overview', (_) => gate.future);
      await pickBranch(tester, 'b2');
      expect(find.byKey(const Key('stock-badge')), findsNothing, reason: 'B is loading: no A number meanwhile');
      gate.complete({'low_count': 0, 'out_count': 3});
      await tester.pumpAndSettle();
      expect(find.descendant(of: find.byKey(const Key('stock-badge')), matching: find.text('3')), findsOneWidget);
    });
  });

  testWidgets('single visible branch: chip is informative only (no switcher)', (tester) async {
    await be.run(() async {
      signIn(role: 'omborchi');
      be.get('/auth/context', (_) => contextJson(role: 'omborchi', permissions: const ['ombor.view']));
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.descendant(of: find.byKey(const Key('branch-chip')), matching: find.text('Markaz')), findsOneWidget);
      await tester.tap(find.byKey(const Key('branch-chip')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('branch-option-b1')), findsNothing);
    });
  });

  testWidgets('no branch can be determined among several: explicit prompt, no silent guess', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context',
          (_) => contextJson(branches: [branchJson('b1', 'A'), branchJson('b2', 'B')])..['actor_branch'] = null);
      await s.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('branch-pick-hint')), findsOneWidget);
      expect(find.text('home:-'), findsOneWidget);
      await pickBranch(tester, 'b2');
      expect(find.byKey(const Key('branch-pick-hint')), findsNothing);
      expect(find.text('home:b2'), findsOneWidget);
    });
  });

  testWidgets('the shell waits for /auth/context: no tab (no branch-scoped request) before it', (tester) async {
    final gate = Completer<Object?>();
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => gate.future);
      unawaited(s.load(force: true));
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pump();
      expect(find.byKey(const Key('shell-loading')), findsOneWidget);
      expect(_Probe.inits, isEmpty);
      expect(be.calls('GET', '/inventory/overview'), isEmpty);
      gate.complete(contextJson());
      await tester.pumpAndSettle();
      expect(find.text('home:b1'), findsOneWidget);
      expect(_Probe.inits, {'home': 1});
    });
  });

  testWidgets('context cannot be loaded: explicit error, retry, logout — no guessed permissions', (tester) async {
    var up = false;
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => up ? contextJson() : FakeResponse.error(503, 'Service Unavailable'));
      await s.load(force: true);
      expect(s.status, SessionStatus.error);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('shell-error')), findsOneWidget);
      expect(find.byKey(const Key('tab-home')), findsNothing);
      expectMinTouchTarget(tester, find.byKey(const Key('shell-error-logout')));
      up = true;
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();
      expect(find.text('home:b1'), findsOneWidget);
    });
  });

  testWidgets('older server without /auth/context: legacy branch label from the login snapshot', (tester) async {
    await be.run(() async {
      signIn(role: 'omborchi', permissions: const ['ombor.view', 'ombor.edit']);
      Api.employee!['branch_name'] = 'Eski filial';
      await s.load(force: true); // 404
      expect(s.status, SessionStatus.degraded);
      await pumpAt390(tester, Shell(tabBuilders: probes()));
      await tester.pumpAndSettle();
      expect(find.descendant(of: find.byKey(const Key('branch-legacy')), matching: find.text('Eski filial')),
          findsOneWidget);
      expect(find.byKey(const Key('tab-stock')), findsOneWidget, reason: 'permissions from the login snapshot');
      expect(find.byKey(const Key('tab-analytics')), findsNothing);
    });
  });

  for (final lang in ['ru', 'ky', 'uzc']) {
    testWidgets('$lang: long branch names, actor hint and the full tab bar fit a 390dp phone', (tester) async {
      L.code = lang;
      await be.run(() async {
        signIn();
        be.get(
            '/auth/context',
            (_) => contextJson(
                  branches: [
                    branchJson('b1', 'Markaziy filial — Bishkek, Chuy prospekti 150/1'),
                    branchJson('b2', 'Osh shahar bozori yonidagi katta ombor filiali'),
                  ],
                  actorBranch: branchJson('b1', 'Markaziy filial — Bishkek, Chuy prospekti 150/1'),
                ));
        await s.load(force: true);
        await pumpAt390(tester, Shell(tabBuilders: probes()));
        await tester.pumpAndSettle();
        await pickBranch(tester, 'b2');
        expect(find.byKey(const Key('branch-actor-hint')), findsOneWidget);
        for (final t in ['home', 'analytics', 'stock', 'settings']) {
          expectMinTouchTarget(tester, find.byKey(Key('tab-$t')));
        }
        await tester.tap(find.byKey(const Key('shell-amal')));
        await tester.pumpAndSettle();
      });
      expect(tester.takeException(), isNull);
    });
  }
}
