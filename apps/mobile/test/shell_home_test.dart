// IB — Home (Bosh) gating per seeded role at 390×844 and its branch scope.
//
// * Every section / quick action / link is shown only with its matrix action
//   (hero `reports.overview`, recent sales `sales.list`, receipt `sales.receipt`,
//   "Tovar qabul" = the "+" sheet gate, "Ombor" = the stock tab gate, bell =
//   anything the notifications screen may read) — and a hidden section sends
//   no request, so no role ever gets a 403 from Home.
// * `/reports/overview`, `/sales`, `/inventory/overview` and `/lots/alerts`
//   carry the CURRENT branch; a branch switch re-reads everything and branch
//   A's numbers are never shown under branch B.
//
// The role permission sets are the server seed (`rolePerms`, checked against
// `app/seed.py` by `apps/server/tests/test_mobile_permission_matrix.py`).
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/screens/home_screen.dart';
import 'package:savdoos_mobile/screens/sales_detail_screen.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'shell_permission_matrix_test.dart' show rolePerms;
import 'support/support.dart';

/// What Home must show for a role.
class HomeExpect {
  const HomeExpect({
    required this.hero,
    required this.receiving,
    required this.sales,
    required this.stock,
    required this.bell,
    required this.stockOverview,
    required this.lotAlerts,
  });

  /// "Bugungi savdo" (reports.overview).
  final bool hero;

  /// "Yangi qabul" quick action (receiving.commit || receiving.history).
  final bool receiving;

  /// "Sotuvlar" quick action + recent sales section (sales.list).
  final bool sales;

  /// "Ombor" quick action (stock tab visible).
  final bool stock;

  /// Notifications bell.
  final bool bell;

  /// `/inventory/overview` requested (stock.overview).
  final bool stockOverview;

  /// `/lots/alerts` requested (lots.alerts).
  final bool lotAlerts;
}

const homeExpected = <String, HomeExpect>{
  'ega': HomeExpect(
      hero: true, receiving: true, sales: true, stock: true, bell: true, stockOverview: true, lotAlerts: true),
  // hisobot.view + sotuvlar.view + ombor.view; no xaridlar.*
  'menejer': HomeExpect(
      hero: true, receiving: false, sales: true, stock: true, bell: true, stockOverview: true, lotAlerts: true),
  // ombor.* + xaridlar.*; no hisobot.view, no sotuvlar.view
  'omborchi': HomeExpect(
      hero: false, receiving: true, sales: false, stock: true, bell: true, stockOverview: false, lotAlerts: true),
  // sotuvlar.view only (POS role)
  'kassir': HomeExpect(
      hero: false, receiving: false, sales: true, stock: false, bell: false, stockOverview: false, lotAlerts: false),
};

Map<String, dynamic> overviewJson(num sales) => {
      'kpi': {'sales': sales, 'profit': 0, 'avg_check': 0, 'tx': 1},
      'delta': {'sales': 4.5, 'profit': null},
      'series': [],
      'top_products': [],
      'cashiers': [],
      'payments': [],
      'credit_total': 0,
    };

Map<String, dynamic> saleJson(String id, String no, {num total = 125000}) => {
      'id': id,
      'receipt_no': no,
      'cashier': 'Gulnora Abdurahmonova',
      'method': 'cash',
      'first_item': 'Coca-Cola 1,5 L',
      'sold_at': '2026-09-19 10:05:00',
      'item_count': 3,
      'total': total,
    };

Map<String, dynamic> lotAlertsJson() => {
      'expiry': {
        'expired': {'lots': 1, 'qty': 1, 'value_at_risk': 10},
        'expires_today': {'lots': 0, 'qty': 0, 'value_at_risk': 0},
        'within_7_days': {'lots': 2, 'qty': 1, 'value_at_risk': 10},
        'within_30_days': {'lots': 0, 'qty': 0, 'value_at_risk': 0},
      },
      'shortfalls': {'open_count': 0, 'open_qty': 0},
      'cost_quality': {'tracked_products': 1},
    };

/// Routes with a distinct answer per `branch_id` (A = b1, B = b2).
void routeHome(FakeBackend be) {
  be
    ..get(
        '/reports/overview',
        (r) => overviewJson(switch (r.query['branch_id']) {
              'b1' => 1111111,
              'b2' => 2222222,
              _ => 3333333,
            }))
    ..get(
        '/sales',
        (r) => switch (r.query['branch_id']) {
              'b2' => [saleJson('sb2', '#B-2001')],
              _ => [saleJson('sa1', '#A-1001'), saleJson('sa2', '#A-1002', total: 99000)],
            })
    ..get(
        '/inventory/overview',
        (r) => switch (r.query['branch_id']) {
              'b1' => {'total_products': 10, 'low_count': 4, 'out_count': 1},
              'b2' => {'total_products': 10, 'low_count': 6, 'out_count': 8},
              _ => {'total_products': 20, 'low_count': 10, 'out_count': 9},
            })
    ..get('/lots/alerts', (r) => lotAlertsJson());
}

/// Every request Home sent is one the matrix allows for the signed-in role:
/// a hidden section must never probe the server (no 403 by design).
void expectNoForbiddenRequest(FakeBackend be, String role) {
  bool templ(String t, String p) {
    final a = t.split('/'), b = p.split('/');
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!(a[i].startsWith('{') && a[i].endsWith('}')) && a[i] != b[i]) return false;
    }
    return true;
  }

  for (final r in be.log) {
    final rules = [
      for (final rule in Perm.all)
        if (rule.method == r.method &&
            templ(rule.path, r.path) &&
            rule.query.entries.every((q) => r.query[q.key] == q.value))
          rule
    ];
    // Literal segments win over `{param}` ones (e.g. /products/scan).
    rules.sort((x, y) => x.path.split('{').length.compareTo(y.path.split('{').length));
    if (rules.isEmpty) continue;
    expect(Perm.allows(rules.first.action), isTrue, reason: '$role sent ${r.method} ${r.path} (${rules.first.action})');
  }
}

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    routeHome(be);
  });

  tearDown(() => Session.instance.debugReset());

  Future<void> signInAs(String role, {List<Map<String, dynamic>>? branches}) async {
    signIn(role: role, permissions: rolePerms(role));
    be.get('/auth/context', (_) => contextJson(role: role, permissions: rolePerms(role), branches: branches));
    await Session.instance.load(force: true);
  }

  Finder k(String key) => find.byKey(Key(key));

  for (final role in homeExpected.keys) {
    testWidgets('$role: Home shows only what the matrix allows, and requests only that (branch A)', (tester) async {
      final e = homeExpected[role]!;
      final tabs = <int>[];
      await be.run(() async {
        await signInAs(role);
        await pumpAt390(tester, HomeScreen(onTab: tabs.add));
        await tester.pumpAndSettle();
      });

      // Sections and entries.
      expect(k('home-hero'), e.hero ? findsOneWidget : findsNothing, reason: '$role hero');
      expect(k('home-quick-receiving'), e.receiving ? findsOneWidget : findsNothing, reason: '$role receiving');
      expect(k('home-quick-sales'), e.sales ? findsOneWidget : findsNothing, reason: '$role sales');
      expect(k('home-sales-all'), e.sales ? findsOneWidget : findsNothing, reason: '$role sales list link');
      expect(k('home-quick-stock'), e.stock ? findsOneWidget : findsNothing, reason: '$role stock');
      expect(k('home-quick-debtors'), findsOneWidget, reason: 'customers.list: any signed-in employee');
      expect(k('home-bell'), e.bell ? findsOneWidget : findsNothing, reason: '$role bell');
      expect(find.text('So‘nggi sotuvlar'), e.sales ? findsOneWidget : findsNothing);

      // The gates ARE the shell/matrix gates (one source of truth).
      expect(e.receiving, ShellGates.actionAllowed(ShellAction.receiving), reason: role);
      expect(e.stock, ShellGates.tabVisible(ShellTab.stock), reason: role);
      expect(e.sales, Perm.allows('sales.list'), reason: role);
      expect(e.hero, Perm.allows('reports.overview'), reason: role);
      expect(e.bell, ShellGates.notificationsVisible(), reason: role);

      // Requests: only the allowed ones, each with the current branch.
      expect(
          be.calls('GET', '/reports/overview').map((c) => c.query).toList(),
          e.hero
              ? [
                  {'period': 'day', 'branch_id': 'b1'}
                ]
              : isEmpty,
          reason: '$role overview');
      expect(
          be.calls('GET', '/sales').map((c) => c.query).toList(),
          e.sales
              ? [
                  {'limit': '3', 'branch_id': 'b1'}
                ]
              : isEmpty,
          reason: '$role sales');
      expect(
          be.calls('GET', '/inventory/overview').map((c) => c.query).toList(),
          e.stockOverview
              ? [
                  {'branch_id': 'b1'}
                ]
              : isEmpty,
          reason: '$role stock overview');
      expect(be.calls('GET', '/lots/alerts').map((c) => c.query['branch_id']).toList(), e.lotAlerts ? ['b1'] : isEmpty,
          reason: '$role lot alerts');
      expect(be.calls('GET', '/products'), isEmpty, reason: 'Home never loads the catalog');
      expectNoForbiddenRequest(be, role);

      // Content of the allowed sections.
      if (e.hero) expect(find.textContaining('1 111 111'), findsOneWidget);
      if (e.sales) {
        expect(find.text('#A-1001'), findsOneWidget);
        expectMinTouchTarget(tester, k('home-sales-all'));
      }
      if (e.stockOverview) expect(find.text('kam qolgan'), findsOneWidget);
      if (e.bell) expectMinTouchTarget(tester, k('home-bell'));
      expectMinTouchTarget(tester, k('home-quick-debtors'));

      // "Ombor" goes to the logical stock tab.
      if (e.stock) {
        await tester.tap(k('home-quick-stock'));
        await tester.pump();
        expect(tabs, [ShellTab.stock.index]);
      }
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('recent sale opens the server receipt (sales.receipt) — kassir', (tester) async {
    be.get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Not Found'));
    await be.run(() async {
      await signInAs('kassir');
      expect(Perm.allows('sales.receipt'), isTrue);
      await pumpAt390(tester, const HomeScreen());
      await tester.pumpAndSettle();
      final tile = k('home-sale-sa1');
      expect(tile, findsOneWidget);
      expectMinTouchTarget(tester, tile);
      await tester.tap(tile);
      await tester.pumpAndSettle();
    });
    final detail = tester.widget<SalesDetailScreen>(find.byType(SalesDetailScreen));
    expect(detail.saleId, 'sa1');
    expect(detail.receiptNo, '#A-1001');
    expect(be.calls('GET', '/sales/sa1/receipt'), isNotEmpty);
  });

  testWidgets('recent sales failure is an explicit error with retry, never "no sales today"', (tester) async {
    var fail = true;
    be.get('/sales', (_) => fail ? FakeResponse.error(500, 'Traceback psycopg') : [saleJson('sa1', '#A-1001')]);
    await be.run(() async {
      await signInAs('kassir');
      await pumpAt390(tester, const HomeScreen());
      await tester.pumpAndSettle();
      expect(k('home-sales-error'), findsOneWidget);
      expect(k('home-sales-empty'), findsNothing);
      expect(find.textContaining('Traceback'), findsNothing);
      fail = false;
      await tester.tap(find.descendant(of: k('home-sales-error'), matching: find.text('Qayta urinish')));
      await tester.pumpAndSettle();
    });
    expect(k('home-sales-error'), findsNothing);
    expect(find.text('#A-1001'), findsOneWidget);
  });

  testWidgets('branch switch: every Home number is re-read for B; A numbers never shown under B', (tester) async {
    final gate = Completer<Object?>();
    await be.run(() async {
      await signInAs('ega', branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')]);
      await pumpAt390(tester, const HomeScreen());
      await tester.pumpAndSettle();
      expect(find.textContaining('1 111 111'), findsOneWidget);
      expect(find.text('#A-1001'), findsOneWidget);
      expect(find.text('4'), findsOneWidget, reason: 'A: 4 low');

      // B's overview is slow: A's figure must disappear at once.
      be.get('/reports/overview', (_) => gate.future);
      await Session.instance.selectBranch('b2');
      await tester.pump();
      expect(find.textContaining('1 111 111'), findsNothing, reason: 'no A figure while B loads');
      expect(find.text('#A-1001'), findsNothing);
      await tester.pumpAndSettle();
      gate.complete(overviewJson(2222222));
      await tester.pumpAndSettle();
    });
    expect(find.textContaining('2 222 222'), findsOneWidget);
    expect(find.text('#B-2001'), findsOneWidget);
    expect(find.text('#A-1001'), findsNothing);
    expect(find.text('6'), findsOneWidget, reason: 'B: 6 low');
    expect(be.last('GET', '/reports/overview').query, {'period': 'day', 'branch_id': 'b2'});
    expect(be.last('GET', '/sales').query, {'limit': '3', 'branch_id': 'b2'});
    expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b2'});
    expect(be.last('GET', '/lots/alerts').query['branch_id'], 'b2');
    expect(be.calls('GET', '/reports/overview'), hasLength(2), reason: 'one read per branch, no duplicate');
  });

  testWidgets('a revoked permission hides its Home section on the next context load', (tester) async {
    var perms = rolePerms('menejer');
    await be.run(() async {
      signIn(role: 'menejer', permissions: perms);
      be.get('/auth/context', (_) => contextJson(role: 'menejer', permissions: perms));
      await Session.instance.load(force: true);
      await pumpAt390(tester, const HomeScreen());
      await tester.pumpAndSettle();
      expect(k('home-hero'), findsOneWidget);
      expect(k('home-quick-sales'), findsOneWidget);

      perms = [
        for (final p in perms)
          if (p != 'hisobot.view' && p != 'sotuvlar.view') p
      ];
      await Session.instance.load(force: true);
      await tester.pumpAndSettle();
    });
    expect(k('home-hero'), findsNothing);
    expect(k('home-quick-sales'), findsNothing);
    expect(k('home-sales-all'), findsNothing);
    expect(be.calls('GET', '/reports/overview'), hasLength(1), reason: 'no request after the revocation');
    expect(be.calls('GET', '/sales'), hasLength(1));
  });

  for (final lang in ['ru', 'ky']) {
    testWidgets('owner Home at 390×844 in $lang: no overflow', (tester) async {
      L.code = lang;
      await be.run(() async {
        await signInAs('ega');
        await pumpAt390(tester, HomeScreen(onTab: (_) {}));
        await tester.pumpAndSettle();
      });
      expect(k('home-quick-receiving'), findsOneWidget);
      expect(k('home-quick-stock'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  group('in the shell', () {
    Map<ShellTab, WidgetBuilder> stockProbe() => {ShellTab.stock: (_) => const Center(child: Text('STOCK-TAB'))};

    testWidgets('omborchi: Home "Ombor" opens the stock tab; no overview/sales request', (tester) async {
      await be.run(() async {
        await signInAs('omborchi');
        await pumpAt390(tester, Shell(tabBuilders: stockProbe()));
        await tester.pumpAndSettle();
        await tester.tap(k('home-quick-stock'));
        await tester.pumpAndSettle();
      });
      expect(find.text('STOCK-TAB'), findsOneWidget);
      expect(be.calls('GET', '/reports/overview'), isEmpty);
      expect(be.calls('GET', '/sales'), isEmpty);
      expect(be.calls('GET', '/inventory/overview'), isEmpty, reason: 'no hisobot.view: no badge, no tile');
      expect(find.byKey(const Key('stock-badge')), findsNothing);
      expectNoForbiddenRequest(be, 'omborchi');
    });

    testWidgets('kassir: no "Ombor" entry anywhere (the tab is hidden); settings hides notifications', (tester) async {
      await be.run(() async {
        await signInAs('kassir');
        await pumpAt390(tester, Shell(tabBuilders: stockProbe()));
        await tester.pumpAndSettle();
        expect(k('home-quick-stock'), findsNothing);
        expect(k('tab-stock'), findsNothing);
        expect(k('home-bell'), findsNothing);
        await tester.tap(k('tab-settings'));
        await tester.pumpAndSettle();
        expect(find.byType(SettingsScreen), findsOneWidget);
        expect(k('settings-notifications'), findsNothing);
      });
      expectNoForbiddenRequest(be, 'kassir');
    });

    testWidgets('menejer: a branch switch in the shell reads Home once for B (no stale-State duplicate)',
        (tester) async {
      await be.run(() async {
        await signInAs('menejer', branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')]);
        await pumpAt390(tester, Shell(tabBuilders: stockProbe()));
        await tester.pumpAndSettle();
        expect(find.textContaining('1 111 111'), findsOneWidget);
        await tester.tap(find.byKey(const Key('branch-chip')).first);
        await tester.pumpAndSettle();
        await tester.tap(k('branch-option-b2'));
        await tester.pumpAndSettle();
      });
      expect(find.textContaining('2 222 222'), findsOneWidget);
      expect(find.textContaining('1 111 111'), findsNothing);
      expect(be.calls('GET', '/reports/overview').map((c) => c.query['branch_id']), ['b1', 'b2']);
      expect(be.calls('GET', '/sales').map((c) => c.query['branch_id']), ['b1', 'b2']);
      expectNoForbiddenRequest(be, 'menejer');
    });
  });
}
