// M2 transfer: lot-tracked products are blocked up front (picker and scan),
// the destination is never pre-selected, the body carries the session branch
// as the source, duplicate is explicit, server 409 is mapped.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/transfer_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    be.get(
        '/branches',
        (r) => {
              'branches': [
                {'id': 'b1', 'name': 'Markaz', 'is_active': true, 'visible': true},
                {'id': 'b2', 'name': 'Chilonzor', 'is_active': true, 'visible': true},
                {'id': 'b3', 'name': 'Yopiq', 'is_active': false, 'visible': true},
              ],
            });
    be.get(
        '/products',
        (r) => FakeResponse.json([
              prodJson('t1', 'Partiyali qatiq', tracked: true, stock: 5),
              prodJson('u1', 'Non', stock: 10),
            ], headers: const {
              'x-total-count': '2'
            }));
  });
  tearDown(() => Session.instance.debugReset());

  Future<void> addNon(WidgetTester tester, String qty) async {
    await tester.tap(find.byKey(const Key('tr-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('picker-row-u1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('tr-qty')), qty);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tr-qty-save')));
    await tester.pumpAndSettle();
  }

  testWidgets('tracked product is listed but blocked with the reason; untracked can be chosen', (tester) async {
    await signInAs(be);
    await be.run(() async {
      await pumpAt390(tester, const TransferScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tr-tracked-note')), findsOneWidget);
      await tester.tap(find.byKey(const Key('tr-add')));
      await tester.pumpAndSettle();
      expect(find.text('Partiyali mahsulot — filiallararo ko‘chirib bo‘lmaydi'), findsOneWidget);
      await tester.tap(find.byKey(const Key('picker-row-t1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('picker-row-t1')), findsOneWidget, reason: 'tap on a blocked row does nothing');
    });
    expect(be.last('GET', '/products').query['branch_id'], 'b1', reason: 'source stock');
  });

  testWidgets('destination must be chosen; body = session branch -> chosen branch; result', (tester) async {
    await signInAs(be);
    be.post(
        '/inventory/transfer',
        (r) => {
              'ok': true,
              'from': 'Markaz',
              'to': 'Chilonzor',
              'moved': [
                {'product': 'Non', 'qty': 2.5, 'from_left': 7.5, 'to_now': 2.5},
              ],
            });
    await be.run(() async {
      await pumpAt390(tester, const TransferScreen());
      await tester.pumpAndSettle();
      await addNon(tester, '2,5');
      expect(tester.widget<ElevatedButton>(find.byKey(const Key('sticky-primary'))).onPressed, isNull);
      expect(find.text('Qaysi filialga ko‘chirilishini tanlang'), findsOneWidget);
      await tester.tap(find.byKey(const Key('tr-dest')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tr-dest-b1')), findsNothing, reason: 'source is not a destination');
      expect(find.byKey(const Key('tr-dest-b3')), findsNothing, reason: 'inactive branch');
      await tester.tap(find.byKey(const Key('tr-dest-b2')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
    });
    final body = be.last('POST', '/inventory/transfer').body;
    expect(body, {
      'from_branch_id': 'b1',
      'to_branch_id': 'b2',
      'items': [
        {'product_id': 'u1', 'qty': 2.5},
      ],
      'client_uuid': isA<String>(),
    });
    expect(find.byKey(const Key('tr-done')), findsOneWidget);
  });

  testWidgets('more than the source stock is refused in the quantity sheet', (tester) async {
    await signInAs(be);
    await be.run(() async {
      await pumpAt390(tester, const TransferScreen());
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-add')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('picker-row-u1')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('tr-qty')), '11');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-qty-save')));
      await tester.pumpAndSettle();
    });
    expect(find.text('Qoldiqdan ko‘p (qoldiq: 10 dona)'), findsOneWidget);
    expect(find.byKey(const Key('tr-item-u1')), findsNothing);
  });

  testWidgets('scanning a tracked product explains why it cannot be moved', (tester) async {
    await signInAs(be);
    be.get('/products/scan', (r) => scanHit(prodJson('t1', 'Partiyali qatiq', tracked: true)));
    await be.run(() async {
      await pumpAt390(tester, TransferScreen(scannerBuilder: fakeCamera(['4780001'])));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-scan')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('tr-notice')), findsOneWidget);
    expect(find.textContaining('Partiyali mahsulot — filiallararo ko‘chirib bo‘lmaydi'), findsOneWidget);
    expect(find.byKey(const Key('tr-item-t1')), findsNothing);
  });

  testWidgets('duplicate reply is explicit; server 409 tracked gate is translated', (tester) async {
    await signInAs(be);
    var dup = false;
    be.post('/inventory/transfer', (r) {
      if (dup) return {'ok': true, 'duplicate': true};
      return FakeResponse.error(
          409,
          "«filiallararo ko'chirish» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin 1 ta kuzatuvli mahsulot "
          "so'raldi. Bu yo'l qoldiqni partiyalarsiz siljitardi.",
          code: 'TRANSFER_TRACKED_UNSUPPORTED');
    });
    await be.run(() async {
      await pumpAt390(tester, const TransferScreen());
      await tester.pumpAndSettle();
      await addNon(tester, '1');
      await tester.tap(find.byKey(const Key('tr-dest')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-dest-b2')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('tr-error')), findsOneWidget);
      expect(find.textContaining('partiya bo‘yicha kuzatiladigan mahsulotni qo‘llab-quvvatlamaydi'), findsOneWidget);
      dup = true;
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('tr-duplicate')), findsOneWidget);
  });

  testWidgets('menejer (no ombor.edit): transfer not allowed', (tester) async {
    await signInAs(be, role: 'menejer');
    await be.run(() async {
      await pumpAt390(tester, const TransferScreen());
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('tr-denied')), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('tr-add'))).onPressed, isNull);
  });
}
