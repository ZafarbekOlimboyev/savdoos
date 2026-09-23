// M5 — permission gating of the shell per seeded role (ega / administrator /
// menejer / omborchi / kassir): which tabs, "+" actions, analytics links and
// settings rows each role SEES. The server stays authoritative; this checks
// the UX never offers what the server would refuse, and hides nothing it allows.
//
// The role permission sets below are the server seed. The backend test
// `apps/server/tests/test_mobile_permission_matrix.py` parses the JSON block
// between the markers and asserts it equals `app/seed.py` ROLES, so these
// widget tests always run against the real roles.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/screens/analytics_screen.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

// BEGIN_ROLE_PERMISSIONS
const _rolesJson = r'''
{
  "menejer": ["sotuvlar.view", "qaytarishlar.create", "qaytarishlar.view", "mijozlar.view", "mijozlar.edit",
              "mahsulotlar.view", "mahsulotlar.edit", "ombor.view", "hisobot.view", "sozlamalar.view"],
  "omborchi": ["mahsulotlar.view", "mahsulotlar.edit", "ombor.view", "ombor.edit", "xaridlar.view", "xaridlar.edit"],
  "kassir": ["kassa.sell", "kassa.view", "sotuvlar.view", "qaytarishlar.create", "mijozlar.view"]
}
''';
// END_ROLE_PERMISSIONS

/// Seeded permissions of a role (full-access roles need none: server bypass).
List<String> rolePerms(String role) {
  final m = (jsonDecode(_rolesJson) as Map).cast<String, dynamic>();
  return [for (final p in (m[role] as List? ?? const [])) '$p'];
}

/// What each role must see.
class Expect {
  const Expect(this.tabs, this.actions,
      {required this.employees, required this.navCards, required this.badge, required this.notifications});
  final List<ShellTab> tabs;
  final List<ShellAction> actions;
  final bool employees;
  final List<String> navCards; // analytics links (only when the tab exists)
  final bool badge; // "Ombor" badge: stock tab + stock.overview (hisobot.view)
  final bool notifications; // bell / settings row: stock.overview | stock.low | lots.alerts
}

const _all = [ShellTab.home, ShellTab.analytics, ShellTab.stock, ShellTab.settings];

const expected = <String, Expect>{
  'ega': Expect(_all, ShellAction.values,
      employees: true,
      navCards: ['nav-sales', 'nav-customers', 'nav-suppliers', 'nav-abc'],
      badge: true,
      notifications: true),
  'administrator': Expect(_all, ShellAction.values,
      employees: true,
      navCards: ['nav-sales', 'nav-customers', 'nav-suppliers', 'nav-abc'],
      badge: true,
      notifications: true),
  // hisobot.view + ombor.view; no xaridlar.*, no ombor.edit, no xodimlar.*
  'menejer': Expect(_all, [ShellAction.cash],
      employees: false, navCards: ['nav-sales', 'nav-customers', 'nav-abc'], badge: true, notifications: true),
  // ombor.* + xaridlar.*; no hisobot.view (no analytics, no cash ops, no stock badge)
  'omborchi': Expect([ShellTab.home, ShellTab.stock, ShellTab.settings],
      [ShellAction.receiving, ShellAction.writeoff, ShellAction.count, ShellAction.transfer],
      employees: false, navCards: [], badge: false, notifications: true),
  // POS only: nothing to manage from the phone
  'kassir': Expect([ShellTab.home, ShellTab.settings], [],
      employees: false, navCards: [], badge: false, notifications: false),
};

Map<ShellTab, WidgetBuilder> fakeTabs() => {
      ShellTab.home: (_) => const Center(child: Text('HOME-TAB')),
      ShellTab.stock: (_) => const Center(child: Text('STOCK-TAB')),
    };

void routeReports(FakeBackend be) {
  be.get(
      '/reports/overview',
      (_) => {
            'kpi': {'sales': 1500000, 'profit': 300000, 'avg_check': 50000, 'tx': 30},
            'delta': {'sales': 5.0, 'profit': -2.0},
            'series': [],
            'top_products': [],
            'cashiers': [],
            'payments': [],
            'credit_total': 0,
          });
  be.get('/reports/categories', (_) => []);
  be.get(
      '/reports/dashboard',
      (_) => {
            'debt': {'total': 0, 'paid_today': 0, 'debtors': 0}
          });
  be.get('/reports/hourly', (_) => []);
  be.get('/reports/cashflow', (_) => {'in': {}, 'out': {}, 'noncash': {}, 'opening': 0, 'kassada': 0});
  be.get('/inventory/overview', (_) => {'low_count': 2, 'out_count': 1});
  be.get('/sales', (_) => []);
}

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    routeReports(be);
  });

  tearDown(() => Session.instance.debugReset());

  Future<void> signInAs(String role) async {
    signIn(role: role, permissions: rolePerms(role));
    be.get('/auth/context', (_) => contextJson(role: role, permissions: rolePerms(role)));
    await Session.instance.load(force: true);
  }

  test('role gates are consistent with the permission matrix', () async {
    await be.run(() async {
      for (final role in expected.keys) {
        await signInAs(role);
        final e = expected[role]!;
        expect(ShellGates.visibleTabs(), e.tabs, reason: role);
        expect(ShellGates.actions(), e.actions, reason: role);
        // The shell never offers an action the matrix denies: each "+" entry is
        // exactly the matrix action of the write it leads to.
        expect(ShellGates.actionAllowed(ShellAction.writeoff), Perm.allows('stock.writeoff'), reason: role);
        expect(ShellGates.actionAllowed(ShellAction.count), Perm.allows('stock.count'), reason: role);
        expect(ShellGates.actionAllowed(ShellAction.transfer), Perm.allows('stock.transfer'), reason: role);
        expect(ShellGates.actionAllowed(ShellAction.cash), Perm.allows('cash.ops.create'), reason: role);
        expect(ShellGates.actionAllowed(ShellAction.receiving),
            Perm.allows('receiving.commit') || Perm.allows('receiving.history'),
            reason: role);
        expect(ShellGates.tabVisible(ShellTab.analytics), Perm.allows('reports.overview'), reason: role);
        expect(ShellGates.stockBadgeAllowed(), e.badge, reason: role);
        expect(ShellGates.stockBadgeAllowed(), Perm.allows('stock.overview') && e.tabs.contains(ShellTab.stock),
            reason: role);
        expect(ShellGates.notificationsVisible(), e.notifications, reason: role);
        Session.instance.debugReset();
      }
    });
  });

  for (final role in expected.keys) {
    testWidgets('$role: tabs, "+" sheet and settings rows', (tester) async {
      final e = expected[role]!;
      await be.run(() async {
        await signInAs(role);
        await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
        await tester.pumpAndSettle();

        expect(find.text('HOME-TAB'), findsOneWidget, reason: 'home is the landing tab');
        // "Ombor" badge: requested (with the current branch) only with stock.overview.
        expect(
            be.calls('GET', '/inventory/overview').map((c) => c.query).toList(),
            e.badge
                ? [
                    {'branch_id': 'b1'}
                  ]
                : isEmpty,
            reason: '$role: no /inventory/overview request that would 403');
        expect(find.byKey(const Key('stock-badge')), e.badge ? findsOneWidget : findsNothing, reason: role);
        for (final t in ShellTab.values) {
          expect(find.byKey(Key('tab-${t.name}')), e.tabs.contains(t) ? findsOneWidget : findsNothing,
              reason: '$role tab ${t.name}');
        }
        expectMinTouchTarget(tester, find.byKey(const Key('tab-home')));

        // "+" — hidden when the role has no action at all.
        final plus = find.byKey(const Key('shell-amal'));
        if (e.actions.isEmpty) {
          expect(plus, findsNothing, reason: role);
        } else {
          expectMinTouchTarget(tester, plus);
          await tester.tap(plus);
          await tester.pumpAndSettle();
          for (final a in ShellAction.values) {
            expect(find.byKey(Key('amal-${a.name}')), e.actions.contains(a) ? findsOneWidget : findsNothing,
                reason: '$role action ${a.name}');
          }
          await tester.tapAt(const Offset(195, 60)); // close the sheet (barrier)
          await tester.pumpAndSettle();
        }

        // Settings: role, company, current branch; employees row per xodimlar.view.
        await tester.tap(find.byKey(const Key('tab-settings')));
        await tester.pumpAndSettle();
        expect(find.byType(SettingsScreen), findsOneWidget);
        expect(find.byKey(const Key('settings-company')), findsOneWidget);
        expect(find.descendant(of: find.byKey(const Key('settings-branch')), matching: find.text('Markaz')),
            findsOneWidget);
        expect(find.byKey(const Key('settings-employees')), e.employees ? findsOneWidget : findsNothing, reason: role);
        expect(find.byKey(const Key('settings-notifications')), e.notifications ? findsOneWidget : findsNothing,
            reason: role);
        expect(find.byKey(const Key('branch-chip')), findsNothing, reason: 'settings is not branch-scoped');

        // Analytics links, each with its own permission.
        if (e.tabs.contains(ShellTab.analytics)) {
          await tester.tap(find.byKey(const Key('tab-analytics')));
          await tester.pumpAndSettle();
          expect(find.byType(AnalyticsScreen), findsOneWidget);
          await tester.scrollUntilVisible(find.byKey(const Key('nav-customers')), 300,
              scrollable: find.descendant(of: find.byType(AnalyticsScreen), matching: find.byType(Scrollable)).first);
          for (final k in ['nav-sales', 'nav-customers', 'nav-suppliers', 'nav-abc']) {
            expect(find.byKey(Key(k)), e.navCards.contains(k) ? findsOneWidget : findsNothing, reason: '$role $k');
          }
          expect(be.calls('GET', '/sales').isNotEmpty, e.navCards.contains('nav-sales'),
              reason: 'recent sales are only requested with sotuvlar.view');
        } else {
          expect(be.calls('GET', '/reports/overview'), isEmpty, reason: '$role never hits a hisobot.view report');
        }
      });
    });
  }

  testWidgets('role labels are localized (ru) in settings', (tester) async {
    L.code = 'ru';
    await be.run(() async {
      await signInAs('omborchi');
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-settings')));
      await tester.pumpAndSettle();
    });
    expect(tester.widget<Text>(find.byKey(const Key('settings-role'))).data, tr('Omborchi'));
    expect(tester.widget<Text>(find.byKey(const Key('settings-company'))).data, 'Fayzan');
    expect(tr('Omborchi'), isNot('Omborchi'));
  });

  testWidgets('a permission override is honoured (omborchi + hisobot.view sees analytics and cash ops)',
      (tester) async {
    await be.run(() async {
      signIn(role: 'omborchi');
      be.get('/auth/context',
          (_) => contextJson(role: 'omborchi', permissions: [...rolePerms('omborchi'), 'hisobot.view']));
      await Session.instance.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tab-analytics')), findsOneWidget);
      await tester.tap(find.byKey(const Key('shell-amal')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('amal-cash')), findsOneWidget);
    });
  });

  testWidgets('a revoked override removes the tab on the next context load', (tester) async {
    var perms = ['sotuvlar.view', 'hisobot.view', 'ombor.view'];
    await be.run(() async {
      signIn(role: 'menejer');
      be.get('/auth/context', (_) => contextJson(role: 'menejer', permissions: perms));
      await Session.instance.load(force: true);
      await pumpAt390(tester, Shell(tabBuilders: fakeTabs()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-analytics')));
      await tester.pumpAndSettle();
      expect(find.byType(AnalyticsScreen), findsOneWidget);

      perms = ['sotuvlar.view', 'ombor.view']; // hisobot.view revoked by the owner
      await Session.instance.load(force: true);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tab-analytics')), findsNothing);
      expect(find.byType(AnalyticsScreen), findsNothing);
      expect(find.text('HOME-TAB'), findsOneWidget, reason: 'falls back to the home tab');
      expect(find.byKey(const Key('shell-amal')), findsNothing, reason: 'cash ops needed hisobot.view');
    });
  });
}
