// IC (Phase 5G integration): the stock numbers follow the CURRENT branch now
// that the server scopes them — `GET /products/{id}`, `/inventory/overview`
// and `/inventory/low` carry `branch_id`; the "all your branches" label stays
// only on a number that really is the sum (the multi-branch total, or no
// branch chosen); a low-stock row opens the product card via `product_id`.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/notifications_screen.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

/// `GET /products/{id}` of [branch] (null = the caller's visible branches).
Map<String, dynamic> _detail(String id, String? branch) {
  final stock = switch (branch) { 'b1' => 5, 'b2' => 7, _ => 12 };
  return {
    ...prodJson(id, 'Sut 1L', stock: stock, min: branch == 'b2' ? 4 : 2),
    'profit_unit': 3000,
    'margin_pct': 20.0,
    'month_in': stock,
    'month_out': 1,
    'sales_7d': {'qty': 1, 'revenue': 15000, 'profit': 3000},
    'sales_30d': {'qty': 4, 'revenue': 60000, 'profit': 12000},
    'created_by_name': 'Ega',
  };
}

String _texts(Finder f) => [
      for (final e in find.descendant(of: f, matching: find.byType(Text), matchRoot: true).evaluate())
        (e.widget as Text).data ?? ''
    ].join(' | ');

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get('/products/{id}', (r) => _detail(r.params['id']!, r.query['branch_id']))
      ..get('/inventory/movements', (r) => [])
      ..get('/lots/alerts', (r) => {'expiry': {}, 'shortfalls': {'open_count': 0}, 'cost_quality': {'tracked_products': 0}})
      ..get('/inventory/overview', (r) => {
            'total_products': 40,
            'low_count': r.query['branch_id'] == 'b2' ? 9 : 1,
            'out_count': r.query['branch_id'] == null ? 5 : 2,
            'moves_today': 0,
          })
      ..get(
          '/inventory/low',
          (r) => [
                {'name': 'Tuz', 'qty': 1, 'min': 5, 'product_id': 'p7'},
                if (r.query['branch_id'] == null) {'name': 'Tuz', 'qty': 2, 'min': 5, 'product_id': 'p7'},
                {'name': 'Eski', 'qty': 0, 'min': 1},
              ]);
  });
  tearDown(() {
    L.code = 'uz';
    Session.instance.debugReset();
  });

  group('StockApi', () {
    test('overview / low / product detail send the branch; product_id is parsed', () async {
      await be.run(() async {
        await StockApi.overview(branchId: 'b2');
        final rows = await StockApi.low(branchId: 'b2');
        final d = await StockApi.productDetail('p1', branchId: 'b2');
        expect(d.branchId, 'b2');
        expect(d.stockMilli, 7000);
        expect(rows.first.productId, 'p7');
        expect(rows.last.productId, isNull, reason: 'older server: no product_id -> no guess');
        final all = await StockApi.productDetail('p1');
        expect(all.branchId, isNull);
        expect(all.stockMilli, 12000);
        await StockApi.overview();
      });
      expect(be.calls('GET', '/inventory/overview').map((c) => c.query), [
        {'branch_id': 'b2'},
        <String, String>{},
      ]);
      expect(be.last('GET', '/inventory/low').query, {'branch_id': 'b2'});
      expect(be.calls('GET', '/products/p1').map((c) => c.query), [
        {'branch_id': 'b2'},
        <String, String>{},
      ]);
    });
  });

  group('product card', () {
    testWidgets('multi-branch owner: branch stock labelled with the branch + the labelled total', (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products/p1').map((c) => c.query),
          unorderedEquals([{'branch_id': 'b1'}, <String, String>{}]));
      final card = _texts(find.byKey(const Key('pd-stock-branch')));
      expect(card, contains('Qoldiq (Markaz)'));
      expect(card, contains('5 dona'));
      expect(card, isNot(contains('barcha filiallaringiz')), reason: 'the branch number is not an aggregate');
      expect(_texts(find.byKey(const Key('pd-stock-all'))), 'Qoldiq (barcha filiallaringiz): 12 dona');
      // The E2E key wraps both numbers.
      expect(_texts(find.byKey(const Key('pd-stock'))), allOf(contains('5 dona'), contains('12 dona')));
      expect(tester.takeException(), isNull);
    });

    testWidgets('single-branch user: one branch request, plain label, no total', (tester) async {
      await signInAs(be, role: 'omborchi', branches: [branchJson('b2', 'Chilonzor')]);
      await be.run(() async {
        await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products/p1').map((c) => c.query), [
        {'branch_id': 'b2'}
      ]);
      final card = _texts(find.byKey(const Key('pd-stock-branch')));
      expect(card, allOf(startsWith('Qoldiq |'), contains('7 dona')));
      expect(find.byKey(const Key('pd-stock-all')), findsNothing);
      expect(find.textContaining('barcha filiallaringiz'), findsNothing);
    });

    testWidgets('branch switch: the card reloads from scratch — A numbers never shown under B', (tester) async {
      await signInAs(be);
      final gate = Completer<void>();
      be.get('/products/{id}', (r) async {
        if (r.query['branch_id'] == 'b2') await gate.future;
        return _detail(r.params['id']!, r.query['branch_id']);
      });
      await be.run(() async {
        await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
        await tester.pumpAndSettle();
        expect(_texts(find.byKey(const Key('pd-stock-branch'))), contains('5 dona'));
        await Session.instance.selectBranch('b2');
        await tester.pump();
        await tester.pump();
        expect(find.byKey(const Key('pd-stock-branch')), findsNothing, reason: 'B still loading: no A number');
        expect(find.textContaining('5 dona'), findsNothing);
        expect(find.byKey(const Key('pd-actions')), findsNothing, reason: 'no action on the old branch product');
        gate.complete();
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products/p1').where((c) => c.query['branch_id'] != null).map((c) => c.query['branch_id']),
          ['b1', 'b2']);
      final card = _texts(find.byKey(const Key('pd-stock-branch')));
      expect(card, allOf(contains('Qoldiq (Chilonzor)'), contains('7 dona')));
      expect(_texts(find.byKey(const Key('pd-stock-all'))), contains('12 dona'));
    });

    testWidgets('several branches, none chosen: no branch is guessed — the sum, labelled so', (tester) async {
      be.get(
          '/auth/context',
          (_) => {
                ...contextJson(role: 'menejer', permissions: kRolePerms['menejer']!, branches: twoBranches()),
                'actor_branch': null,
              });
      signIn(role: 'menejer', permissions: kRolePerms['menejer']!);
      await be.run(() => Session.instance.load(force: true));
      expect(Session.instance.currentBranchId, isNull);
      await be.run(() async {
        await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products/p1').map((c) => c.query), [<String, String>{}]);
      expect(_texts(find.byKey(const Key('pd-stock-branch'))),
          allOf(contains('Qoldiq (barcha filiallaringiz)'), contains('12 dona')));
      expect(find.byKey(const Key('pd-stock-all')), findsNothing);
    });
  });

  group('notifications', () {
    testWidgets('stock section is the current branch; a low row opens its product card', (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
        expect(find.text('Qoldiq'), findsOneWidget);
        expect(find.textContaining('barcha filiallaringiz'), findsNothing);
        expect(find.text('Tugagan: 2 ta'), findsOneWidget);
        expect(find.byKey(const Key('branch-chip')), findsOneWidget, reason: 'one chip for both sections');
        expectMinTouchTarget(tester, find.byKey(const Key('nt-low-p7')));
        // No product_id (older server): not tappable.
        await tester.tap(find.byKey(const Key('nt-low-Eski')));
        await tester.pumpAndSettle();
        expect(find.byType(ProductDetailScreen), findsNothing);
        await tester.tap(find.byKey(const Key('nt-low-p7')));
        await tester.pumpAndSettle();
      });
      expect(be.last('GET', '/inventory/overview').query, {'branch_id': 'b1'});
      expect(be.last('GET', '/inventory/low').query, {'branch_id': 'b1'});
      expect(find.byType(ProductDetailScreen), findsOneWidget);
      // (`contains` compares maps by identity — the card's two calls are matched whole.)
      expect(be.calls('GET', '/products/p7').map((c) => c.query),
          unorderedEquals([{'branch_id': 'b1'}, <String, String>{}]));
      expect(tester.takeException(), isNull);
    });

    testWidgets('branch switch reloads overview + low for the new branch', (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/inventory/overview').map((c) => c.query['branch_id']), ['b1', 'b2']);
      expect(be.calls('GET', '/inventory/low').map((c) => c.query['branch_id']), ['b1', 'b2']);
      expect(find.text('Kam qolgan: 9 ta'), findsOneWidget);
    });

    testWidgets('no branch chosen: the sum (labelled), one row per branch, unique keys', (tester) async {
      be.get(
          '/auth/context',
          (_) => {
                ...contextJson(role: 'menejer', permissions: kRolePerms['menejer']!, branches: twoBranches()),
                'actor_branch': null,
              });
      signIn(role: 'menejer', permissions: kRolePerms['menejer']!);
      await be.run(() => Session.instance.load(force: true));
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
      });
      expect(be.last('GET', '/inventory/overview').query, isEmpty);
      expect(be.last('GET', '/inventory/low').query, isEmpty);
      expect(find.text('Qoldiq (barcha filiallaringiz)'), findsOneWidget);
      expect(find.byKey(const Key('nt-low-p7')), findsOneWidget);
      expect(find.byKey(const Key('nt-low-p7#2')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    for (final lang in ['ru', 'ky']) {
      testWidgets('$lang at 390: product card with both numbers and notifications fit', (tester) async {
        await signInAs(be, branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor filiali (yangi bino)')]);
        await be.run(() => Session.instance.selectBranch('b2'));
        L.code = lang;
        await be.run(() async {
          await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull, reason: 'product card');
          expect(_texts(find.byKey(const Key('pd-stock-branch'))), contains('Chilonzor filiali (yangi bino)'));
          await pumpAt390(tester, const NotificationsScreen());
          await tester.pumpAndSettle();
        });
        expect(tester.takeException(), isNull, reason: 'notifications');
      });
    }
  });
}
