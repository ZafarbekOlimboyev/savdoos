// M5 — analytics tab renders a full report on a 390×844 phone in every UI
// language without layout overflow, and its links respect permissions.
// IB — links gated by their own matrix action (`sales.list`, `suppliers.list`),
// a recent sale opens the server receipt (`sales.receipt`), and the stock alert
// only links to the stock tab when that tab exists.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/analytics_screen.dart';
import 'package:savdoos_mobile/screens/detail_report_screen.dart';
import 'package:savdoos_mobile/screens/sales_detail_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

void routeFullReport(FakeBackend be) {
  be
    ..get(
        '/reports/overview',
        (_) => {
              'kpi': {'sales': 128450000, 'profit': 23990000, 'avg_check': 87650, 'tx': 1465},
              'delta': {'sales': 12.5, 'profit': -3.25},
              'series': [
                for (var d = 13; d <= 19; d++)
                  {'label': '2026-09-$d', 'sales': 15000000 + d * 100000, 'profit': 3000000}
              ],
              'top_products': [
                for (var i = 0; i < 5; i++)
                  {'name': 'Juda uzun nomli mahsulot $i — 1,5 litrli shisha idishda', 'revenue': 9000000 - i * 1000000}
              ],
              'cashiers': [
                {'name': 'Gulnora Abdurahmonova', 'sales': 64000000, 'tx': 700},
                {'name': 'Aziz Karimov', 'sales': 64450000, 'tx': 765},
              ],
              'payments': [
                {'method': 'cash', 'amount': 90000000},
                {'method': 'card', 'amount': 30000000},
                {'method': 'qr', 'amount': 8450000},
              ],
              'credit_total': 1250000,
            })
    ..get(
        '/reports/categories',
        (_) => [
              for (var i = 0; i < 6; i++)
                {
                  'name': 'Sut mahsulotlari va boshqalar $i',
                  'sales': 5000000 - i * 500000,
                  'profit': 900000,
                  'margin': 18
                }
            ])
    ..get(
        '/reports/dashboard',
        (_) => {
              'debt': {'total': 45600000, 'paid_today': 1250000, 'debtors': 37}
            })
    ..get(
        '/reports/hourly',
        (_) => [
              for (var h = 0; h < 24; h++) {'hour': h, 'sales': (h >= 8 && h <= 22) ? h * 100000 : 0}
            ])
    ..get(
        '/reports/cashflow',
        (_) => {
              'in': {'naqd_savdo': 90000000, 'qarz_qaytdi': 1250000, 'qoshimcha': 500000, 'jami': 91750000},
              'out': {
                'xarajat': 2000000,
                'inkassatsiya': 60000000,
                'qaytarish': 350000,
                'beruvchiga': 12000000,
                'jami': 74350000
              },
              'noncash': {'karta': 30000000, 'qr': 8450000, 'nasiya': 1250000},
              'opening': 500000,
              'kassada': 17900000,
            })
    ..get('/inventory/overview', (_) => {'low_count': 12, 'out_count': 3})
    ..get(
        '/sales',
        (_) => [
              for (var i = 0; i < 6; i++)
                {
                  'id': 's$i',
                  'receipt_no': '#10$i',
                  'cashier': 'Gulnora Abdurahmonova',
                  'method': i.isEven ? 'cash' : 'card',
                  'first_item': 'Coca-Cola 1,5 L shisha idishda (sovuq)',
                  'sold_at': '2026-09-19 10:0$i:00',
                  'item_count': 3,
                  'total': 125000 + i,
                }
            ]);
}

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    routeFullReport(be);
  });

  tearDown(() => Session.instance.debugReset());

  for (final lang in ['uz', 'uzc', 'ru', 'ky']) {
    testWidgets('full report, two branches, $lang: no overflow, every card rendered', (tester) async {
      L.code = lang;
      await be.run(() async {
        signIn();
        be.get(
            '/auth/context',
            (_) => contextJson(
                  branches: [
                    branchJson('b1', 'Markaz filiali (Bishkek, Chuy prospekti)'),
                    branchJson('b2', 'Osh bozori')
                  ],
                ));
        await Session.instance.load(force: true);
        await pumpAt390(tester, const AnalyticsScreen());
        await tester.pumpAndSettle();
        final list = find.descendant(of: find.byType(AnalyticsScreen), matching: find.byType(Scrollable)).first;
        // Scroll through the whole report: any RenderFlex overflow fails the test.
        for (var i = 0; i < 12; i++) {
          await tester.drag(list, const Offset(0, -400));
          await tester.pumpAndSettle();
        }
        expect(find.byKey(const Key('nav-abc')), findsOneWidget);
        // Phase 5G.1 / C4: the caption used to sit on FOUR cards, because four
        // reports were company-wide. Three of them are branch-filtered now, so
        // the assertion no longer counts labels in whatever happens to be on
        // screen — it scrolls to the ONE card that is still a company fact
        // (customer debt) and pins the label there.
        await tester.scrollUntilVisible(find.byKey(const Key('card-debt')), -200, scrollable: list);
        await tester.pumpAndSettle();
        expect(
            find.descendant(
                of: find.byKey(const Key('card-debt')), matching: find.byKey(const Key('agg-note'))),
            findsOneWidget,
            reason: 'the company-wide card is labelled');
      });
      expect(tester.takeException(), isNull);
    });
  }

  Future<void> openAs(WidgetTester tester, List<String> perms, {void Function(int)? onTab}) async {
    signIn(role: 'menejer', permissions: perms);
    be.get('/auth/context', (_) => contextJson(role: 'menejer', permissions: perms));
    await Session.instance.load(force: true);
    await pumpAt390(tester, AnalyticsScreen(onTab: onTab));
    await tester.pumpAndSettle();
  }

  Finder list() => find.descendant(of: find.byType(AnalyticsScreen), matching: find.byType(Scrollable)).first;

  testWidgets('links: Sales only with sales.list, Suppliers only with suppliers.list (and no /sales without it)',
      (tester) async {
    await be.run(() async {
      await openAs(tester, const ['hisobot.view']);
      await tester.scrollUntilVisible(find.byKey(const Key('nav-customers')), 300, scrollable: list());
    });
    expect(find.byKey(const Key('nav-sales')), findsNothing);
    expect(find.byKey(const Key('nav-suppliers')), findsNothing);
    expect(find.byKey(const Key('nav-abc')), findsOneWidget);
    expect(be.calls('GET', '/sales'), isEmpty, reason: 'recent sales need sotuvlar.view');
  });

  testWidgets('links: with sotuvlar.view + xaridlar.view both links are offered', (tester) async {
    await be.run(() async {
      await openAs(tester, const ['hisobot.view', 'sotuvlar.view', 'xaridlar.view']);
      await tester.scrollUntilVisible(find.byKey(const Key('nav-suppliers')), 300, scrollable: list());
    });
    expect(find.byKey(const Key('nav-sales')), findsOneWidget);
    expect(find.byKey(const Key('nav-suppliers')), findsOneWidget);
    expect(be.last('GET', '/sales').query, {'limit': '6', 'branch_id': 'b1'});
  });

  testWidgets('recent sale opens the server receipt (sales.receipt)', (tester) async {
    be.get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Not Found'));
    await be.run(() async {
      await openAs(tester, const ['hisobot.view', 'sotuvlar.view']);
      final tile = find.byKey(const Key('recent-sale-s2'));
      await tester.scrollUntilVisible(tile, 300, scrollable: list());
      expectMinTouchTarget(tester, tile);
      await tester.tap(tile);
      await tester.pumpAndSettle();
    });
    final d = tester.widget<SalesDetailScreen>(find.byType(SalesDetailScreen));
    expect(d.saleId, 's2');
    expect(d.receiptNo, '#102');
  });

  testWidgets('stock alert: branch-scoped request; opens the stock tab only when that tab is visible', (tester) async {
    final tabs = <int>[];
    await be.run(() async {
      // hisobot.view without ombor.view / mahsulotlar.view: no stock tab to open.
      await openAs(tester, const ['hisobot.view'], onTab: tabs.add);
      expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b1'});
      expect(find.byKey(const Key('analytics-stock-alert')), findsOneWidget);
      await tester.tap(find.byKey(const Key('analytics-stock-alert')));
      await tester.pump();
      expect(tabs, isEmpty, reason: 'no silent no-op navigation to a hidden tab');
    });
  });

  testWidgets('stock alert with the stock tab visible opens it', (tester) async {
    final tabs = <int>[];
    await be.run(() async {
      await openAs(tester, const ['hisobot.view', 'ombor.view'], onTab: tabs.add);
      await tester.tap(find.byKey(const Key('analytics-stock-alert')));
      await tester.pump();
    });
    expect(tabs, [ShellTab.stock.index]);
  });

  // ══ Phase 5G.1 / C4 — the server now filters the report endpoints by branch ══
  //
  // B1 gave `/reports/{categories,hourly,cashflow,detail}` the SAME `branch_id`
  // contract as `GET /products?branch_id=` (422 / 400 / 403, checked BEFORE the
  // aggregate). Until now the app sent nothing on those four, so a branch-scoped
  // operator read an every-visible-branch aggregate under their own branch name;
  // the "Barcha filiallar" caption was the honest patch over that hole. These
  // tests pin the new behaviour so the caption can never silently outlive it.

  /// Opens the screen as the owner of TWO branches (b1 current).
  Future<void> openTwoBranches(WidgetTester tester) async {
    signIn();
    be.get('/auth/context',
        (_) => contextJson(branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Osh bozori')]));
    await Session.instance.load(force: true);
    await pumpAt390(tester, const AnalyticsScreen());
    await tester.pumpAndSettle();
  }

  testWidgets('every branch-bound report carries the current branch_id', (tester) async {
    await be.run(() async {
      await openTwoBranches(tester);
      for (final p in ['/reports/overview', '/reports/categories', '/reports/hourly', '/reports/cashflow']) {
        expect(be.last('GET', p).query['branch_id'], 'b1', reason: '$p must follow the current branch');
      }
      // The period still travels with the branch (one query, not two contracts).
      expect(be.last('GET', '/reports/categories').query['period'], 'week');
      expect(be.last('GET', '/reports/cashflow').query['period'], 'week');
      // Company-wide BY SEMANTICS: customer credit has no branch column, so the
      // dashboard debt block must stay unscoped (and keep its caption).
      expect(be.last('GET', '/reports/dashboard').query.containsKey('branch_id'), isFalse,
          reason: 'customer debt is a company fact');
    });
  });

  testWidgets('"Barcha filiallar" scope drops branch_id from every branch-bound report', (tester) async {
    await be.run(() async {
      await openTwoBranches(tester);
      await tester.tap(find.byKey(const Key('scope-all')));
      await tester.pumpAndSettle();
      for (final p in ['/reports/overview', '/reports/categories', '/reports/hourly', '/reports/cashflow']) {
        expect(be.last('GET', p).query.containsKey('branch_id'), isFalse,
            reason: '$p must widen to every visible branch');
      }
    });
  });

  testWidgets('switching the period keeps the branch on the aux cards', (tester) async {
    await be.run(() async {
      await openTwoBranches(tester);
      await tester.tap(find.byKey(const Key('period-month')));
      await tester.pumpAndSettle();
      expect(be.last('GET', '/reports/categories').query, {'period': 'month', 'branch_id': 'b1'});
      expect(be.last('GET', '/reports/cashflow').query, {'period': 'month', 'branch_id': 'b1'});
    });
  });

  testWidgets('the all-branches caption stays ONLY on the company-wide debt card', (tester) async {
    await be.run(() async {
      await openTwoBranches(tester);
      Finder note(String card) => find.descendant(
          of: find.byKey(Key(card)), matching: find.byKey(const Key('agg-note')));
      for (final card in ['card-debt', 'card-cashflow', 'card-hourly', 'card-categories']) {
        await tester.scrollUntilVisible(find.byKey(Key(card)), 200, scrollable: list());
        await tester.pumpAndSettle();
        expect(note(card), card == 'card-debt' ? findsOneWidget : findsNothing,
            reason: '$card: only a company-wide number may claim "Barcha filiallar"');
      }
    });
  });

  testWidgets('one visible branch: no caption anywhere (nothing to disambiguate)', (tester) async {
    await be.run(() async {
      signIn();
      be.get('/auth/context', (_) => contextJson(branches: [branchJson('b1', 'Markaz')]));
      await Session.instance.load(force: true);
      await pumpAt390(tester, const AnalyticsScreen());
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.byKey(const Key('card-debt')), 200, scrollable: list());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('agg-note')), findsNothing);
      expect(find.byKey(const Key('scope-branch')), findsNothing, reason: 'no scope bar with one branch');
    });
  });

  // ── Batafsil · ABC (`/reports/detail`) — audit finding: all-branch numbers,
  //    no caption at all. B1 gave the endpoint a branch filter, so the screen
  //    now asks for ONE branch and says which one.
  group('detail report', () {
    void routeDetail(FakeBackend be) => be.get(
        '/reports/detail',
        (_) => {
              'returns': {'count': 4, 'sum': 320000, 'voided': 2},
              'a_share': 72.0,
              'abc': [
                {'name': 'Coca-Cola 1,5 L', 'cls': 'A', 'units': 120, 'share': 41.5, 'profit': 900000},
                {'name': 'Non', 'cls': 'B', 'units': 60, 'share': 12.0, 'profit': 120000},
              ],
            });

    testWidgets('asks for the current branch and names it', (tester) async {
      routeDetail(be);
      await be.run(() async {
        signIn();
        be.get('/auth/context',
            (_) => contextJson(branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Osh bozori')]));
        await Session.instance.load(force: true);
        await pumpAt390(tester, const DetailReportScreen());
        await tester.pumpAndSettle();
        expect(be.last('GET', '/reports/detail').query, {'period': 'month', 'branch_id': 'b1'});
        expect(find.byKey(const Key('detail-scope')), findsOneWidget,
            reason: 'a multi-branch operator must be told which branch these numbers are');
        expect(find.descendant(of: find.byKey(const Key('detail-scope')), matching: find.text('Markaz')),
            findsOneWidget);
      });
    });

    testWidgets('one visible branch: scoped request, no caption', (tester) async {
      routeDetail(be);
      await be.run(() async {
        signIn();
        be.get('/auth/context', (_) => contextJson(branches: [branchJson('b1', 'Markaz')]));
        await Session.instance.load(force: true);
        await pumpAt390(tester, const DetailReportScreen());
        await tester.pumpAndSettle();
        expect(be.last('GET', '/reports/detail').query['branch_id'], 'b1');
        expect(find.byKey(const Key('detail-scope')), findsNothing);
      });
    });
  });
}
