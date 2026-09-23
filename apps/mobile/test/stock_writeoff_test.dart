// M2 write-off: untracked single qty; tracked per-lot qty (Σ == qty, each ≤
// remaining) with the SAME branch_id for the lot read and the write; desktop
// reason codes; cost_total; duplicate; network retry reuses client_uuid;
// server error mapping; permission gating.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

const trackedP = StockProduct(id: 'p1', name: 'Qatiq', unit: 'dona', stockMilli: 8000, trackLots: true);

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  void trackedLots() => be.get(
      '/lots/products/{id}',
      (r) => lotsJson(
          'p1',
          [
            lotJson('l1', batch: 'A-1', expiry: '2026-09-10', expired: true, remaining: 3, cost: 1000),
            lotJson('l2', batch: 'B-2', expiry: '2026-10-01', remaining: 5, cost: 2000),
          ],
          expiry: true,
          inv: 8));

  Future<void> submit(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('sticky-primary')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-yes')));
    await tester.pumpAndSettle();
  }

  testWidgets('untracked: pick -> qty -> reason -> confirm -> POST (qty, reason, branch_id), result shown',
      (tester) async {
    await signInAs(be);
    be.get('/products',
        (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10)], headers: const {'x-total-count': '1'}));
    be.get('/lots/products/{id}', (r) => lotsJson('p5', const [], tracked: false, inv: 10));
    be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Non', 'new_qty': 7.5});
    final rev = Api.stockRev.value;
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen());
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('wo-pick')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('picker-row-p5')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-qty')), '2,5');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('wo-reason-damaged')));
      await tester.enterText(find.byKey(const Key('wo-note')), 'singan');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('wo-summary')), findsOneWidget);
      await submit(tester);
    });
    expect(be.last('GET', '/products').query['branch_id'], 'b1');
    expect(be.last('GET', '/lots/products/p5').query['branch_id'], 'b1');
    final body = be.last('POST', '/inventory/writeoff').body;
    expect(body, {
      'product_id': 'p5',
      'qty': 2.5,
      'reason': 'damaged: singan',
      'branch_id': 'b1',
      'client_uuid': isA<String>(),
    });
    expect(find.byKey(const Key('wo-done')), findsOneWidget);
    expect(find.text('Yangi qoldiq: 7,5 dona'), findsOneWidget);
    expect(Api.stockRev.value, greaterThan(rev));
  });

  testWidgets('untracked: more than the branch stock is blocked before sending', (tester) async {
    await signInAs(be);
    be.get('/lots/products/{id}', (r) => lotsJson('p5', const [], tracked: false, inv: 10));
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: StockProduct(id: 'p5', name: 'Non')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-qty')), '12');
      await tester.pumpAndSettle();
    });
    expect(find.text('Qoldiqdan ko‘p (qoldiq: 10 dona)'), findsWidgets);
    final btn = tester.widget<ElevatedButton>(find.byKey(const Key('sticky-primary')));
    expect(btn.onPressed, isNull);
    expect(be.calls('POST', '/inventory/writeoff'), isEmpty);
  });

  testWidgets('tracked: per-lot quantities, Σ = qty, same branch for lots and write, cost_total', (tester) async {
    await signInAs(be);
    trackedLots();
    be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Qatiq', 'new_qty': 3.5, 'cost_total': 6000});
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('lot-card-l1')), findsOneWidget, reason: 'expired lots stay visible');
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l1')), '3');
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l2')), '1,5');
      await tester.pumpAndSettle();
      expect(find.text('Jami: 4,5 dona · tannarx 6\u00a0000 so‘m'), findsOneWidget);
      await submit(tester);
    });
    final lotsRead = be.last('GET', '/lots/products/p1').query['branch_id'];
    final body = be.last('POST', '/inventory/writeoff').body;
    expect(body['branch_id'], lotsRead, reason: 'the lots were read from the branch the write goes to');
    expect(body['qty'], 4.5);
    expect(body['reason'], 'expired');
    expect(body['lots'], [
      {'stock_batch_id': 'l1', 'qty': 3},
      {'stock_batch_id': 'l2', 'qty': 1.5},
    ]);
    expect(find.byKey(const Key('wo-cost')), findsOneWidget);
    expect(find.text('Hisobdan chiqarilgan tannarx: 6\u00a0000 so‘m'), findsOneWidget);
  });

  testWidgets('tracked: a lot above its remaining is an inline error and blocks submit', (tester) async {
    await signInAs(be);
    trackedLots();
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l1')), '3,001');
      await tester.pumpAndSettle();
    });
    expect(find.text('Partiya qoldig‘idan ko‘p (3 dona)'), findsOneWidget);
    expect(tester.widget<ElevatedButton>(find.byKey(const Key('sticky-primary'))).onPressed, isNull);
  });

  testWidgets('duplicate reply is shown as "already saved", not as a new write-off', (tester) async {
    await signInAs(be);
    trackedLots();
    be.post('/inventory/writeoff', (r) => {'ok': true, 'duplicate': true});
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l2')), '1');
      await tester.pumpAndSettle();
      await submit(tester);
    });
    expect(find.byKey(const Key('wo-duplicate')), findsOneWidget);
    expect(find.byKey(const Key('wo-done')), findsNothing);
  });

  testWidgets('network failure: no success, retry hint, the retry reuses the same client_uuid', (tester) async {
    await signInAs(be);
    trackedLots();
    be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Qatiq', 'new_qty': 7});
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l2')), '1');
      await tester.pumpAndSettle();
      be.offline = true;
      await submit(tester);
      expect(find.byKey(const Key('wo-done')), findsNothing);
      expect(find.byKey(const Key('wo-error')), findsOneWidget);
      expect(find.textContaining('ikki marta yozilmaydi'), findsOneWidget);
      expect(find.text('Qayta yuborish'), findsOneWidget);
      be.offline = false;
      await submit(tester);
    });
    final posts = be.calls('POST', '/inventory/writeoff');
    expect(posts, hasLength(2));
    expect(posts[0].body['client_uuid'], posts[1].body['client_uuid']);
    expect(find.byKey(const Key('wo-done')), findsOneWidget);
  });

  testWidgets('LOT_SELECTION_INVALID: localized message and the lots are reloaded', (tester) async {
    await signInAs(be);
    trackedLots();
    be.post(
        '/inventory/writeoff',
        (r) => FakeResponse.error(
            400, "Partiya boshqa mahsulot yoki filialga tegishli: 3fa85f64-5717-4562-b3fc-2c963f66afa6",
            code: 'LOT_SELECTION_INVALID'));
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-lot-qty-l2')), '1');
      await tester.pumpAndSettle();
      await submit(tester);
    });
    expect(find.textContaining('Partiya boshqa mahsulot yoki filialga tegishli — ro‘yxatni yangilang'), findsOneWidget);
    expect(find.textContaining('3fa85f64'), findsNothing, reason: 'no raw UUIDs');
    expect(be.calls('GET', '/lots/products/p1'), hasLength(2), reason: 'lots reloaded after the rejection');
  });

  testWidgets('kassir: write-off is not allowed (reason shown, nothing sent)', (tester) async {
    await signInAs(be, role: 'kassir');
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen());
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('wo-denied')), findsOneWidget);
    expect(tester.widget<ElevatedButton>(find.byKey(const Key('sticky-primary'))).onPressed, isNull);
    expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
  });

  testWidgets('branch switch drops the selected product (no cross-branch write-off)', (tester) async {
    await signInAs(be);
    trackedLots();
    await be.run(() async {
      await pumpAt390(tester, const WriteoffScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await Session.instance.selectBranch('b2');
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('wo-product')), findsNothing);
    expect(find.text('Filial almashtirildi — mahsulotni qayta tanlang.'), findsOneWidget);
  });
}
