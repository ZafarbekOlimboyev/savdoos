// M2 stock API: request shapes (write-off / count / transfer), response
// parsing (lots, results, duplicate) and the HTTP contract (paging, branch_id,
// client_uuid, cache bust) — through the fake backend.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/widgets/lot_editor.dart';

import 'stock_fixtures_test.dart';

void main() {
  setUp(() async => resetCore());
  tearDown(() => Session.instance.debugReset());

  group('request bodies', () {
    test('write-off, untracked: qty only, same branch_id, reason text', () {
      final b = writeoffBody(
          productId: 'p1', qtyMilli: 2500, reason: writeoffReasonText('damaged', ' singan '), branchId: 'b1');
      expect(b, {'product_id': 'p1', 'qty': 2.5, 'reason': 'damaged: singan', 'branch_id': 'b1'});
      expect(b.containsKey('lots'), isFalse);
    });

    test('write-off, tracked: lots[] with exact 3-decimal quantities', () {
      final b = writeoffBody(
        productId: 'p1',
        qtyMilli: 300,
        reason: 'expired',
        branchId: 'b2',
        lots: const [LotPick('l1', 100), LotPick('l2', 200)],
      );
      expect(b['qty'], 0.3);
      expect(b['lots'], [
        {'stock_batch_id': 'l1', 'qty': 0.1},
        {'stock_batch_id': 'l2', 'qty': 0.2},
      ]);
    });

    test('reason text: code only, code + note, cut to 200 characters', () {
      expect(writeoffReasonText('expired', ''), 'expired');
      expect(writeoffReasonText('other', 'x' * 300).length, kWriteoffReasonMax);
      expect(kWriteoffReasons, ['expired', 'damaged', 'lost', 'other']);
    });

    test('transfer body', () {
      expect(transferBody(fromBranchId: 'b1', toBranchId: 'b2', items: const [('p1', 1500), ('p2', 2000)]), {
        'from_branch_id': 'b1',
        'to_branch_id': 'b2',
        'items': [
          {'product_id': 'p1', 'qty': 1.5},
          {'product_id': 'p2', 'qty': 2},
        ],
      });
    });

    test('count: untracked entry is the absolute counted quantity', () {
      final e = PlainCountEntry(const StockProduct(id: 'p1', name: 'Sut'), systemMilli: 5000, countedMilli: 4250);
      expect(e.toJson(), {'product_id': 'p1', 'counted': 4.25});
      expect(e.lotLines, 0);
    });

    test('count: tracked total = untouched + counted + new; blank lots are NOT sent', () {
      final lots = ProductLots.fromJson(
        lotsJson(
            'p1',
            [
              lotJson('l1', remaining: 3),
              lotJson('l2', remaining: 5),
              lotJson('l3', remaining: 2),
              lotJson('v1', remaining: 4, status: 'void'), // miqdor tashimaydi — tegilmagan emas
            ],
            expiry: true,
            inv: 10),
        branchId: 'b1',
      );
      final ctl = LotEditorController(trackExpiry: true, hasTarget: false, withUnitCost: true, allowEmpty: true)..add();
      ctl.update(ctl.rows.first.key, qty: '1', unitCost: '1500', expiry: '2027-01-31', batch: 'N-7');
      final e = LotCountEntry(
        const StockProduct(id: 'p1', name: 'Sut', trackLots: true),
        lots: lots,
        counted: const {'l1': 2000, 'l3': 0},
        newLots: ctl.rows,
        newLotsPayload: ctl.newLotsPayload(),
        newMilli: ctl.state.sumMilli,
        newReason: ' javon ortidan ',
      );
      expect(e.untouchedMilli, 5000, reason: 'only l2 (void lot excluded)');
      expect(e.totalMilli, 5000 + 2000 + 0 + 1000);
      expect(e.toJson(), {
        'product_id': 'p1',
        'counted': 8,
        'lots': [
          {'stock_batch_id': 'l1', 'counted': 2},
          {'stock_batch_id': 'l3', 'counted': 0},
        ],
        'new_lots': [
          {'qty': 1, 'unit_cost': 1500, 'batch_no': 'N-7', 'expiry_date': '2027-01-31', 'reason': 'javon ortidan'},
        ],
      });
      expect(e.lotLines, 3);
      ctl.dispose();
    });

    test('count body carries the branch the lots were read from', () {
      expect(countBody(items: const [], branchId: 'b2'), {'items': [], 'branch_id': 'b2'});
    });
  });

  group('parsing', () {
    test('lots: FEFO rows, usable excludes void / empty lots, days left from the business date', () {
      final l = ProductLots.fromJson(
        lotsJson(
            'p1',
            [
              lotJson('a', expiry: '2026-09-18', expired: true, remaining: 1.5),
              lotJson('b', expiry: '2026-09-24', remaining: 0.001),
              lotJson('c', remaining: 0, status: 'depleted'),
              lotJson('d', remaining: 2, status: 'void'),
            ],
            expiry: true,
            shortfall: 0.5),
        branchId: 'b1',
      );
      expect(l.trackExpiry, isTrue);
      expect(l.shortfallMilli, 500);
      expect(l.usableLots.map((x) => x.id), ['a', 'b']);
      expect(l.lots.first.daysLeft(l.businessDate), -1);
      expect(l.lots[1].daysLeft(l.businessDate), 5);
      expect(l.lots[1].remainingMilli, 1);
    });

    test('write-off result: new stock, cost, duplicate', () {
      final r = WriteoffResult.fromJson({'ok': true, 'product': 'Sut', 'new_qty': 7.5, 'cost_total': 4500.5});
      expect(r.newQtyMilli, 7500);
      expect(r.costTotalCents, 450050);
      expect(WriteoffResult.fromJson({'ok': true, 'duplicate': true}).duplicate, isTrue);
    });

    test('count result: per-lot decrements / surpluses / created', () {
      final r = CountResult.fromJson({
        'ok': true,
        'changed': 1,
        'results': [
          {
            'product': 'Sut',
            'product_id': 'p1',
            'old': 10,
            'counted': 8,
            'diff': -2,
            'lots': {
              'decrements': [
                {'stock_batch_id': 'l1', 'qty': 1},
              ],
              'surpluses': [],
              'created': [
                {'stock_batch_id': 'n1', 'qty': 1, 'unit_cost': 1500, 'batch_no': 'N-7', 'expiry_date': '2027-01-31'},
              ],
            },
          },
          {'product': 'Non', 'product_id': 'p2', 'old': 5, 'counted': 5, 'diff': 0},
        ],
      });
      expect(r.changed, 1);
      expect(r.results.first.diffMilli, -2000);
      expect(r.results.first.decrements.single.lotId, 'l1');
      expect(r.results.first.created.single.unitCostCents, 150000);
      expect(r.results.first.hasLots, isTrue);
      expect(r.results.last.hasLots, isFalse);
      expect(CountResult.fromJson({'ok': true, 'duplicate': true, 'changed': 0, 'results': []}).duplicate, isTrue);
    });

    test('lot alerts: urgent = expired + today + 7 days', () {
      final a = LotAlerts.fromJson({
        'expiry': {
          'expired': {'lots': 2, 'qty': 3, 'value_at_risk': 100},
          'expires_today': {'lots': 1, 'qty': 1, 'value_at_risk': 10},
          'within_7_days': {'lots': 4, 'qty': 1, 'value_at_risk': 10},
          'within_30_days': {'lots': 9, 'qty': 1, 'value_at_risk': 10},
        },
        'shortfalls': {'open_count': 1, 'open_qty': 0.5},
        'cost_quality': {'tracked_products': 3},
      });
      expect(a.urgentLots, 7);
      expect(a.bucket(ExpiryKind.within30).lots, 9);
      expect(a.shortfallCount, 1);
      expect(a.trackedProducts, 3);
    });

    test('product: level and frozen expiry', () {
      expect(StockProduct.fromJson(prodJson('p', 'x', stock: 0)).level, StockLevel.out);
      expect(StockProduct.fromJson(prodJson('p', 'x', stock: 2, min: 3)).level, StockLevel.low);
      expect(StockProduct.fromJson(prodJson('p', 'x', stock: 2)).level, StockLevel.ok);
      expect(StockProduct.fromJson(prodJson('p', 'x', expiryDate: '2026-10-01')).productExpiry, '2026-10-01');
    });
  });

  group('HTTP', () {
    late FakeBackend be;
    setUp(() {
      be = FakeBackend();
      signIn();
    });

    test('products: server-side paging with branch_id, X-Total-Count, hasMore', () async {
      be.get('/products', (r) => FakeResponse.json([prodJson('p1', 'Sut')], headers: const {'x-total-count': '51'}));
      final page = await be.run(() => StockApi.products(q: '  sut ', branchId: 'b2', offset: 50));
      final q = be.last('GET', '/products').query;
      expect(q, {'q': 'sut', 'branch_id': 'b2', 'limit': '50', 'offset': '50'});
      expect(page.total, 51);
      expect(page.hasMore, isFalse);
      final first = await be.run(() => StockApi.products(tracked: true));
      expect(be.last('GET', '/products').query['tracked'], 'true');
      expect(first.hasMore, isTrue, reason: '0 + 1 < 51');
    });

    test('lots read sends the branch', () async {
      be.get('/lots/products/{id}', (r) => lotsJson(r.params['id']!, [lotJson('l1')]));
      final l = await be.run(() => StockApi.productLots('p1', branchId: 'b2'));
      expect(be.last('GET', '/lots/products/p1').query['branch_id'], 'b2');
      expect(l.branchId, 'b2');
    });

    test('write-off posts client_uuid and bumps stockRev only after a 2xx', () async {
      be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Sut', 'new_qty': 1});
      final rev = Api.stockRev.value;
      await be.run(() => StockApi.writeoff(
          writeoffBody(productId: 'p1', qtyMilli: 1000, reason: 'lost', branchId: 'b1'),
          clientUuid: 'u-1'));
      expect(be.last('POST', '/inventory/writeoff').body['client_uuid'], 'u-1');
      expect(Api.stockRev.value, rev + 1);

      be.post('/inventory/writeoff', (r) => FakeResponse.error(400, "Yetarli qoldiq yo'q: Sut (qoldiq: 1)"));
      await expectLater(
          be.run(() => StockApi.writeoff(writeoffBody(productId: 'p1', qtyMilli: 5000, reason: 'lost', branchId: 'b1'),
              clientUuid: 'u-2')),
          throwsA(isA<ApiException>()));
      expect(Api.stockRev.value, rev + 1, reason: 'a rejected write is not a stock change');
    });

    test('alerts / overview / low / expiring lots', () async {
      be.get('/lots/alerts', (r) => {'expiry': {}, 'shortfalls': {}, 'cost_quality': {}});
      be.get('/inventory/overview', (r) => {'total_products': 3, 'low_count': 1, 'out_count': 2});
      be.get(
          '/inventory/low',
          (r) => [
                {'name': 'Sut', 'qty': 1, 'min': 5},
              ]);
      be.get(
          '/lots/batches',
          (r) => {
                'total': 1,
                'lots': [
                  {
                    'id': 'l1',
                    'product_id': 'p1',
                    'product': 'Sut',
                    'unit_code': 'dona',
                    'expired': true,
                    'remaining_qty': 2
                  },
                ],
              });
      await be.run(() async {
        await StockApi.lotAlerts(branchId: 'b1');
        expect(be.last('GET', '/lots/alerts').query['branch_id'], 'b1');
        final o = await StockApi.overview();
        expect(o.outCount, 2);
        expect((await StockApi.low()).single.minMilli, 5000);
        final rows = await StockApi.expiringLots(branchId: 'b1', expiry: ExpiryKind.expired);
        expect(rows.single.expired, isTrue);
        expect(be.last('GET', '/lots/batches').query, {
          'branch_id': 'b1',
          'expiry': 'expired',
          'status': 'open',
          'sort': 'expiry',
          'order': 'asc',
          'limit': '50'
        });
      });
    });
  });
}
