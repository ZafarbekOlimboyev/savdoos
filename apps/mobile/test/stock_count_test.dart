// M2 count (Phase 4B contract): untracked absolute count; tracked per-lot
// counts (blank = untouched), new lots via LotEditor, total = untouched +
// counted + new; same branch for the lot read and the write; remove items;
// server per-lot result; duplicate; error mapping + failing item.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

const trackedP = StockProduct(id: 'p1', name: 'Qatiq', trackLots: true, trackExpiry: true);

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  void catalog() {
    be.get(
        '/products',
        (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10), prodJson('p6', 'Tuz', stock: 4)],
            headers: const {'x-total-count': '2'}));
    be.get('/lots/products/{id}', (r) {
      final id = r.params['id']!;
      if (id == 'p1') {
        return lotsJson(
            'p1',
            [
              lotJson('l1', batch: 'A-1', expiry: '2026-09-25', remaining: 3),
              lotJson('l2', batch: 'B-2', expiry: '2026-10-10', remaining: 5),
              lotJson('l3', batch: 'C-3', expiry: '2026-09-10', expired: true, remaining: 2),
            ],
            expiry: true,
            inv: 10);
      }
      return lotsJson(id, const [], tracked: false, inv: id == 'p5' ? 10 : 4);
    });
  }

  Future<void> addPlain(WidgetTester tester, String id, String qty) async {
    await tester.tap(find.byKey(const Key('cnt-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(Key('picker-row-$id')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('cnt-plain-qty')), qty);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cnt-plain-save')));
    await tester.pumpAndSettle();
  }

  Finder lotList() =>
      find.descendant(of: find.byKey(const Key('lotcnt-list')), matching: find.byType(Scrollable)).first;

  /// Scrolls the lot page programmatically until [f] is built, then into view
  /// (a drag could start on a focused text field and select text instead).
  Future<void> reveal(WidgetTester tester, Finder f) async {
    final pos = tester.state<ScrollableState>(lotList()).position;
    for (var i = 0; i < 40 && f.evaluate().isEmpty; i++) {
      pos.jumpTo((pos.pixels + 200).clamp(0, pos.maxScrollExtent).toDouble());
      await tester.pump();
    }
    await tester.ensureVisible(f);
    await tester.pumpAndSettle();
  }

  Future<void> send(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('sticky-primary')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-yes')));
    await tester.pumpAndSettle();
  }

  testWidgets('untracked: absolute counted quantity, branch_id sent, result page', (tester) async {
    await signInAs(be);
    catalog();
    be.post(
        '/inventory/count',
        (r) => {
              'ok': true,
              'changed': 1,
              'results': [
                {'product': 'Non', 'product_id': 'p5', 'old': 10, 'counted': 7, 'diff': -3},
              ],
            });
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      expect(find.byKey(const Key('cnt-item-p5')), findsOneWidget);
      expect(find.text('−3 dona'), findsOneWidget);
      expect(find.byKey(const Key('cnt-branch-locked')), findsOneWidget, reason: 'branch locked while items exist');
      await send(tester);
    });
    final body = be.last('POST', '/inventory/count').body;
    expect(body['branch_id'], 'b1');
    expect(body['items'], [
      {'product_id': 'p5', 'counted': 7},
    ]);
    expect(body['client_uuid'], isA<String>());
    expect(find.byKey(const Key('cnt-changed')), findsOneWidget);
    expect(find.byKey(const Key('cnt-result-p5')), findsOneWidget);
  });

  testWidgets('tracked: blank lot untouched, 0 counted, new lot with cost+expiry; total and payload', (tester) async {
    await signInAs(be);
    catalog();
    be.post(
        '/inventory/count',
        (r) => {
              'ok': true,
              'changed': 1,
              'results': [
                {
                  'product': 'Qatiq',
                  'product_id': 'p1',
                  'old': 10,
                  'counted': 8,
                  'diff': -2,
                  'lots': {
                    'decrements': [
                      {'stock_batch_id': 'l1', 'qty': 1},
                      {'stock_batch_id': 'l3', 'qty': 2},
                    ],
                    'surpluses': [],
                    'created': [
                      {
                        'stock_batch_id': 'n1',
                        'qty': 1,
                        'unit_cost': 1500,
                        'batch_no': null,
                        'expiry_date': '2027-01-31'
                      },
                    ],
                  },
                },
              ],
            });
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      // Partiya sahifasi ochildi: l1 = 2, l2 bo'sh (tegilmaydi), l3 = 0.
      await tester.enterText(find.byKey(const Key('lotcnt-qty-l1')), '2');
      await reveal(tester, find.byKey(const Key('lotcnt-qty-l3')));
      await tester.enterText(find.byKey(const Key('lotcnt-qty-l3')), '0');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('lotcnt-diff-l2')), findsOneWidget);
      expect(find.text('tegilmaydi'), findsOneWidget);
      // Yangi partiya: 1 dona, tannarx 1500, muddat 31.01.2027.
      await reveal(tester, find.byKey(const Key('lot-add')));
      await tester.tap(find.byKey(const Key('lot-add')));
      await tester.pumpAndSettle();
      await reveal(tester, find.byKey(const Key('lot-qty-0')));
      await tester.enterText(find.byKey(const Key('lot-qty-0')), '1');
      await reveal(tester, find.byKey(const Key('lot-cost-0')));
      await tester.enterText(find.byKey(const Key('lot-cost-0')), '1500');
      await reveal(tester, find.byKey(const Key('lot-expiry-0')));
      await tester.tap(find.byKey(const Key('lot-expiry-0')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('date-typed')), '31012027');
      await tester.tap(find.byKey(const Key('date-typed-ok')));
      await tester.pumpAndSettle();
      expect(find.text('Jami sanoq: 8 dona'), findsOneWidget);
      expect(find.text('tegilmagan 5 + sanalgan 2 + yangi 1'), findsOneWidget);
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cnt-item-p1')), findsOneWidget);
      await send(tester);
    });
    expect(be.calls('GET', '/lots/products/p1').single.query['branch_id'], 'b1');
    final body = be.last('POST', '/inventory/count').body;
    expect(body['branch_id'], 'b1', reason: 'same branch as the lot read');
    expect(body['items'], [
      {
        'product_id': 'p1',
        'counted': 8,
        'lots': [
          {'stock_batch_id': 'l1', 'counted': 2},
          {'stock_batch_id': 'l3', 'counted': 0},
        ],
        'new_lots': [
          {'qty': 1, 'unit_cost': 1500, 'expiry_date': '2027-01-31'},
        ],
      },
    ]);
    expect(find.byKey(const Key('cnt-dec-l1')), findsOneWidget);
    expect(find.text('A-1 · 25.09.2026: −1'), findsOneWidget, reason: 'lot label from the lots that were counted');
    expect(find.byKey(const Key('cnt-created-n1')), findsOneWidget);
  });

  testWidgets('tracked: saving with nothing counted is refused (blank is not zero)', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen(initialProduct: trackedP));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('lotcnt-error')), findsOneWidget);
    expect(find.text('Kamida bitta partiyani sanang yoki topilgan yangi partiyani qo‘shing.'), findsOneWidget);
  });

  testWidgets('remove an item from the session before sending', (tester) async {
    await signInAs(be);
    catalog();
    be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': []});
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await addPlain(tester, 'p6', '4');
      await tester.tap(find.byKey(const Key('cnt-remove-p5')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cnt-item-p5')), findsNothing);
      await send(tester);
    });
    expect(be.last('POST', '/inventory/count').body['items'], [
      {'product_id': 'p6', 'counted': 4},
    ]);
  });

  testWidgets('duplicate reply is explicit', (tester) async {
    await signInAs(be);
    catalog();
    be.post('/inventory/count', (r) => {'ok': true, 'duplicate': true, 'changed': 0, 'results': []});
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await send(tester);
    });
    expect(find.byKey(const Key('cnt-duplicate')), findsOneWidget);
    expect(find.byKey(const Key('cnt-changed')), findsNothing);
  });

  testWidgets('sum mismatch: translated message and the failing product is marked', (tester) async {
    await signInAs(be);
    catalog();
    be.post(
        '/inventory/count',
        (r) => FakeResponse.error(
            400,
            "Non: Partiyalar yig'indisi (7.000) e'lon qilingan umumiy sanoqqa (8.000) mos emas. "
            "Sanalmagan partiyalar TEGILMAYDI (5.000); farqni tizim TAQSIMLAMAYDI.",
            code: 'LOT_COUNT_SUM_MISMATCH'));
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await send(tester);
    });
    expect(find.byKey(const Key('cnt-error')), findsOneWidget);
    expect(find.textContaining('Non: Partiyalar yig‘indisi (7.000) umumiy sanoqqa (8.000) teng emas'), findsOneWidget);
    expect(find.byKey(const Key('cnt-failed-p5')), findsOneWidget);
    expect(find.byKey(const Key('cnt-item-p5')), findsOneWidget, reason: 'nothing is lost after a rejection');
  });

  testWidgets('409 timezone not confirmed is mapped', (tester) async {
    await signInAs(be);
    catalog();
    be.post(
        '/inventory/count',
        (r) => FakeResponse.error(409, "filial vaqt zonasi ('Asia/Bishkek') TASDIQLANMAGAN. Administrator tasdiqlasin.",
            code: 'LOT_TZ_NOT_CONFIRMED'));
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await send(tester);
    });
    expect(find.textContaining('Filial vaqt zonasi (Asia/Bishkek) tasdiqlanmagan'), findsOneWidget);
  });

  testWidgets('leaving with unsent counts asks first', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) {
        Navigator.of(ctx).push(MaterialPageRoute(builder: (_) => const InventarizatsiyaScreen()));
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Sanoq yuborilmagan'), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm-no')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cnt-item-p5')), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
    });
    expect(find.byType(InventarizatsiyaScreen), findsNothing);
    expect(be.calls('POST', '/inventory/count'), isEmpty);
  });

  testWidgets('continuous scan: each scanned product is counted without leaving the scanner', (tester) async {
    await signInAs(be);
    catalog();
    be.get('/products/scan', (r) => scanHit(prodJson('p6', 'Tuz', stock: 4), code: r.query['code']!));
    await be.run(() async {
      await pumpAt390(tester, InventarizatsiyaScreen(scannerBuilder: fakeCamera(['111', '222'])));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-scan-continuous')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cnt-plain-system')), findsOneWidget, reason: 'count sheet over the scanner');
      await tester.enterText(find.byKey(const Key('cnt-plain-qty')), '3');
      await tester.tap(find.byKey(const Key('cnt-plain-save')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scan-last')), findsOneWidget, reason: 'still scanning');
      await tester.tap(find.byKey(const Key('scan-done')));
      await tester.pumpAndSettle();
    });
    expect(be.last('GET', '/products/scan').query['branch_id'], 'b1');
    expect(be.last('GET', '/lots/products/p6').query['branch_id'], 'b1');
    expect(find.byKey(const Key('cnt-item-p6')), findsOneWidget);
  });

  testWidgets('kassir: count not allowed', (tester) async {
    await signInAs(be, role: 'kassir');
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
    });
    expect(find.byKey(const Key('cnt-denied')), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('cnt-add'))).onPressed, isNull);
  });
}
