// M2 count guards:
//  * an entry counted in branch A may never end up in a branch-B request — the
//    branch may change while the lot/qty editor is open;
//  * a tracked product with an OPEN lot shortfall can never be counted (the
//    server's `Inventory.qty == Σ lots − Σ shortfall` invariant makes every
//    such count a 409 «qo'llab-quvvatlashga murojaat qiling»), so the screen
//    must refuse it up front instead of letting the operator type.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  void catalog({num shortfall = 0}) {
    be.get(
        '/products',
        (r) => FakeResponse.json([
              prodJson('p5', 'Non', stock: 10),
              prodJson('p6', 'Tuz', stock: 4),
              prodJson('p1', 'Qatiq', tracked: true, stock: 3),
            ], headers: const {
              'x-total-count': '3'
            }));
    be.get('/lots/products/{id}', (r) {
      final id = r.params['id']!;
      if (id == 'p1') {
        return lotsJson('p1', [lotJson('l1', batch: 'A-1', remaining: 3)], inv: 3, shortfall: shortfall);
      }
      return lotsJson(id, const [], tracked: false, inv: id == 'p5' ? 10 : 4);
    });
  }

  Future<void> openPlain(WidgetTester tester, String id) async {
    await tester.tap(find.byKey(const Key('cnt-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(Key('picker-row-$id')));
    await tester.pumpAndSettle();
  }

  testWidgets('a branch switch while the count sheet is open discards the entry (never re-pins the old branch)',
      (tester) async {
    await signInAs(be);
    catalog();
    be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});
    await be.run(() async {
      await Session.instance.selectBranch('b2');
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await openPlain(tester, 'p5'); // counted against Chilonzor (b2) stock
      expect(find.byKey(const Key('cnt-plain-qty')), findsOneWidget);
      await tester.enterText(find.byKey(const Key('cnt-plain-qty')), '7');
      await tester.pumpAndSettle();
      // The branch changes under the open sheet (deactivated / unassigned).
      await Session.instance.selectBranch('b1');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-plain-save')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('cnt-item-p5')), findsNothing,
          reason: 'the b2 count must not silently join a b1 session');
      expect(find.byKey(const Key('cnt-branch-notice')), findsOneWidget);

      // A second product, counted in the CURRENT branch, is the only thing sent.
      await openPlain(tester, 'p6');
      await tester.enterText(find.byKey(const Key('cnt-plain-qty')), '4');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-plain-save')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
    });
    final body = be.last('POST', '/inventory/count').body;
    expect(body['branch_id'], 'b1');
    expect(body['items'], [
      {'product_id': 'p6', 'counted': 4},
    ]);
  });

  testWidgets('a tracked product with an open lot shortfall is refused up front, with what to do', (tester) async {
    await signInAs(be);
    catalog(shortfall: 7);
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await openPlain(tester, 'p1');
      expect(find.byKey(const Key('lotcnt-list')), findsNothing,
          reason: 'the editor may not open: any count of this product is refused by the server');
      expect(find.byKey(const Key('cnt-open-error')), findsOneWidget);
      expect(find.textContaining('partiyasiz sotilgan'), findsOneWidget);
      // The operator is sent to a section that EXISTS in the desktop Manager
      // and is named the same way everywhere else in this app.
      expect(find.textContaining('Aniqlanmagan qoldiq'), findsOneWidget,
          reason: 'a refusal must name the section that clears it, not an invented "qarzni bog‘lash"');
      expect(find.byKey(const Key('cnt-item-p1')), findsNothing);
    });
    expect(be.calls('POST', '/inventory/count'), isEmpty);
  });

  // The continuous scanner is a full-screen route ON TOP of the count screen:
  // a refusal written onto the screen underneath is never read, and the next
  // scan wipes it. A product the screen refuses must therefore be refused
  // INSIDE the scanner — and must not be ticked off as counted.
  testWidgets('continuous scan: a shortfall-blocked product is refused in the scanner and never counted',
      (tester) async {
    await signInAs(be);
    catalog(shortfall: 7);
    be.get('/products/scan', (r) => scanHit(prodJson('p1', 'Qatiq', tracked: true, stock: 3), code: r.query['code']!));
    await be.run(() async {
      await pumpAt390(tester, InventarizatsiyaScreen(scannerBuilder: fakeCamera(['4780001'])));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-scan-continuous')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('scan-refused')), findsOneWidget,
          reason: 'the operator must see the refusal while still in the scanner');
      expect(find.textContaining('partiyasiz sotilgan'), findsOneWidget);
      expect(find.byKey(const Key('scan-last')), findsNothing,
          reason: 'a green check for an item that was NOT counted is a lie');
      expect(find.text('Tayyor (0)'), findsOneWidget, reason: 'the tally may not count a dropped item');
      await tester.tap(find.byKey(const Key('scan-done')));
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('cnt-item-p1')), findsNothing);
  });

  testWidgets('continuous scan: an accepted product still shows the green check and counts', (tester) async {
    await signInAs(be);
    catalog();
    be.get('/products/scan', (r) => scanHit(prodJson('p5', 'Non', stock: 10), code: r.query['code']!));
    await be.run(() async {
      await pumpAt390(tester, InventarizatsiyaScreen(scannerBuilder: fakeCamera(['4780001'])));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-scan-continuous')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();
      // The plain count sheet opens over the scanner; count 7.
      await tester.enterText(find.byKey(const Key('cnt-plain-qty')), '7');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-plain-save')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scan-refused')), findsNothing);
      expect(find.byKey(const Key('scan-last')), findsOneWidget);
      expect(find.text('Tayyor (1)'), findsOneWidget);
      await tester.tap(find.byKey(const Key('scan-done')));
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('cnt-item-p5')), findsOneWidget);
  });

  testWidgets('without a shortfall the same product still opens normally', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await openPlain(tester, 'p1');
      expect(find.byKey(const Key('lotcnt-list')), findsOneWidget);
    });
  });
}
