// M2 Ombor list: server-side search + infinite scroll, scoped to the current
// branch; never the full catalog; a branch switch never shows the old
// branch's rows; scan -> product card.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/inventory_screen.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

List<Map<String, dynamic>> page(int from, int n, {String prefix = 'Mahsulot'}) => [
      for (var i = from; i < from + n; i++) prodJson('p$i', '$prefix ${i.toString().padLeft(3, '0')}', stock: i),
    ];

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  void productsRoute({int total = 120}) {
    be.get('/products', (r) {
      final off = int.parse(r.query['offset'] ?? '0');
      final lim = int.parse(r.query['limit'] ?? '999999');
      final n = (total - off).clamp(0, lim);
      final pre = r.query['branch_id'] == 'b2' ? 'B2' : 'Mahsulot';
      return FakeResponse.json(page(off, n, prefix: pre), headers: {'x-total-count': '$total'});
    });
  }

  testWidgets('first page: limit=50, offset=0, branch_id of the session; never the whole catalog', (tester) async {
    await signInAs(be);
    productsRoute();
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
    });
    final calls = be.calls('GET', '/products');
    expect(calls, isNotEmpty);
    expect(calls.first.query, {'branch_id': 'b1', 'limit': '50', 'offset': '0'});
    expect(calls.every((c) => c.query.containsKey('limit')), isTrue, reason: 'no unpaged /products');
    expect(find.text('Mahsulot 000'), findsOneWidget);
    expect(find.text('120 ta mahsulot'), findsOneWidget);
  });

  testWidgets('infinite scroll loads the next pages until the end', (tester) async {
    await signInAs(be);
    productsRoute(total: 70);
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Mahsulot 069'), 600, scrollable: find.byType(Scrollable).last);
      await tester.pumpAndSettle();
    });
    final offsets = be.calls('GET', '/products').map((c) => c.query['offset']).toList();
    expect(offsets, ['0', '50']);
    expect(find.text('Mahsulot 069'), findsOneWidget);
    expect(find.text('Ro‘yxat oxiri'), findsOneWidget);
  });

  testWidgets('search is sent to the server (debounced) and the tracked filter too', (tester) async {
    await signInAs(be);
    productsRoute(total: 3);
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('stock-search')), 's');
      await tester.enterText(find.byKey(const Key('stock-search')), 'sut');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('stock-filter-tracked')));
      await tester.pumpAndSettle();
    });
    final qs = be.calls('GET', '/products').map((c) => c.query).toList();
    expect(qs.where((q) => q['q'] == 's'), isEmpty, reason: 'debounced: only the final text is searched');
    expect(qs[1], {'q': 'sut', 'branch_id': 'b1', 'limit': '50', 'offset': '0'});
    expect(qs.last['tracked'], 'true');
    expect(qs.last['q'], 'sut');
  });

  testWidgets('branch switch: old rows disappear BEFORE the new branch answers', (tester) async {
    await signInAs(be);
    final gate = Completer<void>();
    be.get('/products', (r) async {
      if (r.query['branch_id'] == 'b2') await gate.future;
      final pre = r.query['branch_id'] == 'b2' ? 'B2' : 'Mahsulot';
      return FakeResponse.json(page(0, 2, prefix: pre), headers: const {'x-total-count': '2'});
    });
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
      expect(find.text('Mahsulot 000'), findsOneWidget);
      await Session.instance.selectBranch('b2');
      await tester.pump();
      expect(find.text('Mahsulot 000'), findsNothing, reason: 'branch A data must not be shown under branch B');
      gate.complete();
      await tester.pumpAndSettle();
    });
    expect(be.last('GET', '/products').query['branch_id'], 'b2');
    expect(find.text('B2 000'), findsOneWidget);
  });

  testWidgets('error state with retry; a later success shows rows', (tester) async {
    await signInAs(be);
    var fail = true;
    be.get('/products', (r) {
      if (fail) return FakeResponse.error(500, 'boom');
      return FakeResponse.json(page(0, 1), headers: const {'x-total-count': '1'});
    });
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
      expect(find.text('Serverda vaqtincha nosozlik. Birozdan so‘ng qayta urinib ko‘ring.'), findsOneWidget);
      fail = false;
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();
    });
    expect(find.text('Mahsulot 000'), findsOneWidget);
  });

  testWidgets('scan -> server lookup with the branch -> product card', (tester) async {
    await signInAs(be);
    productsRoute(total: 1);
    be.get('/products/{id}', (r) => {...prodJson(r.params['id']!, 'Qatiq'), 'sales_7d': {}, 'sales_30d': {}});
    be.get('/products/scan', (r) => scanHit(prodJson('p9', 'Qatiq'))); // keyin — '{id}' dan ustun
    await be.run(() async {
      await pumpAt390(tester, InventoryScreen(scannerBuilder: fakeCamera(['4780001'])));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('stock-scan')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();
    });
    expect(be.last('GET', '/products/scan').query, {'code': '4780001', 'branch_id': 'b1'});
    expect(find.byType(ProductDetailScreen), findsOneWidget);
    // The card is the CURRENT branch's (+ the total of the visible branches: 2 of them here).
    expect(be.calls('GET', '/products/p9').map((c) => c.query),
        unorderedEquals([
          {'branch_id': 'b1'},
          <String, String>{},
        ]));
  });

  testWidgets('rows are 48 dp+ touch targets and show tracked / level badges', (tester) async {
    await signInAs(be);
    be.get(
        '/products',
        (r) => FakeResponse.json([
              prodJson('a', 'Partiyali sut', tracked: true, expiry: true, stock: 0),
              prodJson('b', 'Non', stock: 2, min: 5),
            ], headers: const {
              'x-total-count': '2'
            }));
    await be.run(() async {
      await pumpAt390(tester, const InventoryScreen());
      await tester.pumpAndSettle();
    });
    expect(find.text('Partiyali'), findsWidgets);
    expect(find.text('Tugagan'), findsOneWidget);
    expect(find.text('Kam qoldi'), findsOneWidget);
    expectMinTouchTarget(tester, find.byKey(const Key('stock-row-a')));
    expectMinTouchTarget(tester, find.byKey(const Key('stock-scan')));
  });
}
