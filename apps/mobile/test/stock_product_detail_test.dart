// M2 product card: lots of the CURRENT branch for tracked products (expired
// highlighted, frozen product expiry NOT used), permission gating of lots,
// movements and actions, branch switch reloads the lots.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/theme.dart';

import 'stock_fixtures_test.dart';

Map<String, dynamic> detailJson(String id, String name,
        {bool tracked = false, bool expiry = false, String? expiryDate}) =>
    {
      ...prodJson(id, name, tracked: tracked, expiry: expiry, expiryDate: expiryDate, stock: 12),
      'profit_unit': 3000,
      'margin_pct': 20.0,
      'month_in': 5,
      'month_out': 2,
      'sales_7d': {'qty': 1, 'revenue': 15000, 'profit': 3000},
      'sales_30d': {'qty': 4, 'revenue': 60000, 'profit': 12000},
      'created_by_name': 'Ega',
    };

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    be.get(
        '/inventory/movements',
        (r) => [
              {
                'type': 'Kirim',
                'direction': 'in',
                'name': 'Sut',
                'qty': 5,
                'employee': 'Ega',
                'at': '2026-09-18 10:00:00'
              },
            ]);
  });
  tearDown(() => Session.instance.debugReset());

  testWidgets('tracked: lots of the current branch, expired highlighted, frozen expiry hidden', (tester) async {
    await signInAs(be);
    be.get('/products/{id}', (r) => detailJson('p1', 'Qatiq', tracked: true, expiry: true, expiryDate: '2020-01-01'));
    be.get(
        '/lots/products/{id}',
        (r) => lotsJson(
            'p1',
            [
              lotJson('l1', batch: 'A-1', expiry: '2026-09-10', expired: true, remaining: 2),
              lotJson('l2', batch: 'B-2', expiry: '2026-09-22', remaining: 5),
            ],
            expiry: true,
            inv: 7,
            shortfall: 1));
    await be.run(() async {
      await pumpAt390(tester, const ProductDetailScreen(productId: 'p1', initialName: 'Qatiq'));
      await tester.pumpAndSettle();
    });
    expect(be.last('GET', '/lots/products/p1').query['branch_id'], 'b1');
    expect(find.byKey(const Key('pd-product-expiry')), findsNothing, reason: 'frozen column of a tracked product');
    await tester.scrollUntilVisible(find.byKey(const Key('lot-card-l2')), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('lot-card-l1')), findsOneWidget);
    final box = tester.widget<Container>(find.byKey(const Key('lot-card-l1')));
    expect((box.decoration! as BoxDecoration).color, AppColors.dangerSoft, reason: 'expired lot highlighted');
    expect(find.descendant(of: find.byKey(const Key('lot-card-l1')), matching: find.text('Muddati o‘tgan')),
        findsOneWidget);
    expect(
        find.descendant(of: find.byKey(const Key('lot-card-l2')), matching: find.text('3 kun qoldi')), findsOneWidget);
    expect(find.textContaining('Filial qoldig‘i: 7'), findsOneWidget);
    expect(find.byKey(const Key('pd-shortfall')), findsOneWidget);
    expect(find.byKey(const Key('pd-actions')), findsOneWidget, reason: 'owner may count and write off');
  });

  testWidgets('branch switch reloads the lots for the new branch (old lots dropped)', (tester) async {
    await signInAs(be);
    be.get('/products/{id}', (r) => detailJson('p1', 'Qatiq', tracked: true));
    be.get(
        '/lots/products/{id}',
        (r) => lotsJson('p1', [
              lotJson(r.query['branch_id'] == 'b2' ? 'lb2' : 'lb1', batch: r.query['branch_id'], remaining: 1),
            ]));
    await be.run(() async {
      await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
      await tester.pumpAndSettle();
      await Session.instance.selectBranch('b2');
      await tester.pumpAndSettle();
    });
    expect(be.calls('GET', '/lots/products/p1').map((c) => c.query['branch_id']), ['b1', 'b2']);
    await tester.scrollUntilVisible(find.byKey(const Key('lot-card-lb2')), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('lot-card-lb1')), findsNothing);
  });

  testWidgets('untracked: no lots request; product expiry is shown', (tester) async {
    await signInAs(be);
    be.get('/products/{id}', (r) => detailJson('p2', 'Non', expiryDate: '2026-09-21'));
    await be.run(() async {
      await pumpAt390(tester, const ProductDetailScreen(productId: 'p2'));
      await tester.pumpAndSettle();
    });
    expect(be.calls('GET', '/lots/products/p2'), isEmpty);
    expect(find.byKey(const Key('pd-product-expiry')), findsOneWidget);
    expect(find.text('2 kun qoldi'), findsOneWidget);
  });

  testWidgets('kassir: no lots / movements requests, no write actions', (tester) async {
    await signInAs(be, role: 'kassir');
    be.get('/products/{id}', (r) => detailJson('p1', 'Qatiq', tracked: true));
    await be.run(() async {
      await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
      await tester.pumpAndSettle();
    });
    expect(be.calls('GET', '/lots/products/p1'), isEmpty);
    expect(be.calls('GET', '/inventory/movements'), isEmpty, reason: 'needs hisobot.view');
    expect(find.byKey(const Key('pd-actions')), findsNothing);
    await tester.scrollUntilVisible(find.byKey(const Key('pd-lots-denied')), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.byKey(const Key('pd-lots-denied')), findsOneWidget);
  });

  testWidgets('omborchi: lots yes, movements no (hisobot.view), actions yes', (tester) async {
    await signInAs(be, role: 'omborchi');
    be.get('/products/{id}', (r) => detailJson('p1', 'Qatiq', tracked: true));
    be.get('/lots/products/{id}', (r) => lotsJson('p1', [lotJson('l1')]));
    await be.run(() async {
      await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
      await tester.pumpAndSettle();
    });
    expect(be.calls('GET', '/lots/products/p1'), hasLength(1));
    expect(be.calls('GET', '/inventory/movements'), isEmpty);
    expect(find.byKey(const Key('pd-actions')), findsOneWidget);
  });
}
