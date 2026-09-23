// M2 layout: the stock screens render at 390×844 in Russian and Kyrgyz (the
// longest translations) without overflow, and their primary controls are
// 48 dp touch targets.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/screens/inventory_screen.dart';
import 'package:savdoos_mobile/screens/notifications_screen.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/screens/transfer_screen.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

const tracked = StockProduct(id: 'p1', name: 'Qatiq 3,2% «Musaffo» 450 g', trackLots: true, trackExpiry: true);

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get(
          '/products',
          (r) => FakeResponse.json([
                prodJson('p1', 'Qatiq 3,2% «Musaffo» 450 g juda uzun nomli mahsulot',
                    tracked: true, expiry: true, stock: 0),
                prodJson('p2', 'Non', stock: 2, min: 5, expiryDate: '2026-09-20'),
              ], headers: const {
                'x-total-count': '2'
              }))
      ..get(
          '/products/{id}',
          (r) => {
                ...prodJson('p1', 'Qatiq', tracked: true, expiry: true, stock: 12),
                'sales_7d': {'qty': 1, 'revenue': 1500000, 'profit': 300000},
                'sales_30d': {'qty': 4, 'revenue': 6000000, 'profit': 1200000},
              })
      ..get(
          '/lots/products/{id}',
          (r) => lotsJson(
              'p1',
              [
                lotJson('l1', batch: 'PARTIYA-2026-000123', expiry: '2026-09-10', expired: true, remaining: 1234.567),
                lotJson('l2', expiry: '2026-09-21', remaining: 5, cost: 1234567.5),
              ],
              expiry: true,
              inv: 1239.567,
              shortfall: 1.5))
      ..get(
          '/lots/alerts',
          (r) => {
                'expiry': {
                  'expired': {'lots': 12, 'qty': 1234.5, 'value_at_risk': 12345678},
                  'expires_today': {'lots': 1, 'qty': 1, 'value_at_risk': 10},
                  'within_7_days': {'lots': 4, 'qty': 1, 'value_at_risk': 10},
                  'within_30_days': {'lots': 9, 'qty': 1, 'value_at_risk': 10},
                },
                'shortfalls': {'open_count': 3, 'open_qty': 2},
                'cost_quality': {'tracked_products': 5},
              })
      ..get('/inventory/overview', (r) => {'low_count': 31, 'out_count': 12})
      ..get(
          '/inventory/low',
          (r) => [
                {'name': 'Tuz yodlangan 1 kg juda uzun nom bilan', 'qty': 1, 'min': 5},
              ])
      ..get(
          '/branches',
          (r) => {
                'branches': [
                  {'id': 'b1', 'name': 'Markaz', 'is_active': true},
                  {'id': 'b2', 'name': 'Chilonzor filiali (yangi bino)', 'is_active': true},
                ],
              });
  });
  tearDown(() {
    L.code = 'uz';
    Session.instance.debugReset();
  });

  for (final lang in ['ru', 'ky']) {
    testWidgets('$lang: Ombor list, product card, notifications', (tester) async {
      await signInAs(be);
      L.code = lang;
      await be.run(() async {
        await pumpAt390(tester, const InventoryScreen());
        await tester.pumpAndSettle();
        expectMinTouchTarget(tester, find.byKey(const Key('stock-scan')));
        expect(tester.takeException(), isNull, reason: 'Ombor list');
        await pumpAt390(tester, const ProductDetailScreen(productId: 'p1'));
        await tester.pumpAndSettle();
        await tester.drag(find.byType(Scrollable).first, const Offset(0, -900));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull, reason: 'product card');
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
      });
      expect(tester.takeException(), isNull);
    });

    testWidgets('$lang: write-off (tracked), count lot page, transfer', (tester) async {
      await signInAs(be);
      L.code = lang;
      await be.run(() async {
        await pumpAt390(tester, const WriteoffScreen(initialProduct: tracked));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('wo-lot-qty-l1')), '9999');
        await tester.pumpAndSettle();
        expectMinTouchTarget(tester, find.byKey(const Key('sticky-primary')));
        expect(tester.takeException(), isNull, reason: 'write-off');
        await pumpAt390(tester, const InventarizatsiyaScreen(initialProduct: tracked));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('lotcnt-qty-l1')), '1,5');
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull, reason: 'count lot page');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('cnt-item-p1')), findsOneWidget);
        expectMinTouchTarget(tester, find.byKey(const Key('cnt-remove-p1')));
        expect(tester.takeException(), isNull, reason: 'count session');
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
      });
      expect(tester.takeException(), isNull);
    });
  }
}
