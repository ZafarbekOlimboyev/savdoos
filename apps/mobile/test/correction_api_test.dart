// M3 — `GET /purchases/{id}` parsing (current and older server) and the
// `POST /receiving/{id}/corrections` transport (path, body, errors).
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/correction_api.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

void main() {
  setUp(() async => resetCore());

  test('PurchaseDoc: lines, lots, history, custody, document branch', () {
    final d = PurchaseDoc.fromJson(purchaseJson(
      custody: custodyJson('OPERATOR_MUST_CHOOSE', reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill, kSafe]),
      corrections: [
        {'id': 'c1', 'at': '2026-09-19T08:30:00', 'reason': 'Nakladnoy', 'delta_total': -20000.0, 'employee': 'Ali'}
      ],
    ));
    expect(d.id, 'p1');
    expect(d.receivingId, 'r1');
    expect(d.branchId, 'b1');
    expect(d.branchName, 'Markaz');
    expect(d.date, '2026-09-18');
    expect(d.supplier, 'Oq Sut MChJ');
    expect(d.isCredit, isFalse);
    final l1 = d.lines.first;
    expect(l1.qtyMilli, 10000);
    expect(l1.unitCostCents, 1000000);
    expect(l1.lineTotalCents, 10000000);
    expect(l1.trackLots, isTrue);
    expect(l1.correctable, isTrue);
    expect(l1.lots.last.consumedMilli, 3000);
    expect(d.lines.last.trackExpiry, isTrue);
    expect(d.lines.last.lots.single.expiryDate, '2026-12-01');
    expect(d.corrections.single.deltaCents, -2000000);
    expect(d.corrections.single.employee, 'Ali');
    expect(d.corrections.single.at, isNotNull);
    expect(d.cashCustody!.needsChoice, isTrue);
    expect(d.cashCustody!.options.map((o) => o.id), ['t1', 's1']);
  });

  test('older server (no Phase 5D/5E keys): no correction flow, no custody', () {
    final j = purchaseJson(withCustody: false)
      ..remove('receiving_id')
      ..remove('correctable')
      ..remove('correction_blocked_reason')
      ..remove('corrections')
      ..remove('business_date')
      ..remove('branch_id')
      ..remove('branch_name');
    for (final it in j['items'] as List) {
      (it as Map)
        ..remove('lots')
        ..remove('correctable')
        ..remove('correction_blocked_reason');
    }
    final d = PurchaseDoc.fromJson(j);
    expect(d.correctable, isNull);
    expect(d.receivingId, isNull);
    expect(d.correctionOpen, isFalse);
    expect(d.cashCustody, isNull);
    expect(d.lines.first.lots, isEmpty);
    expect(d.lines.first.correctable, isNull);
    expect(d.businessDate, isNull);
  });

  test('a lot without `correctable` is treated as NOT correctable (fail-closed)', () {
    final lot = ReceivedLot.fromJson({'id': 'x', 'received_qty': 1, 'remaining_qty': 1, 'consumed_qty': 0, 'unit_cost': 5});
    expect(lot.correctable, isFalse);
    expect(lot.docUnitCostCents, isNull);
    expect(lot.docCostCents, 500);
  });

  test('purchase() GETs the document; submit() POSTs to the receiving and bumps stock listeners', () async {
    signIn(role: 'menejer', permissions: ['xaridlar.view', 'xaridlar.edit']);
    final be = FakeBackend()
      ..get('/purchases/{id}', (r) => purchaseJson(id: r.params['id']!))
      ..post('/receiving/{rid}/corrections', (r) => {
            'ok': true,
            'correction_id': 'c9',
            'receiving_id': r.params['rid'],
            'purchase_id': 'p1',
            'reversed_total': 20000.0,
            'replaced_total': 0.0,
            'delta_total': -20000.0,
            'purchase_status': 'received',
            'cancelled': false,
            'duplicate': false,
          });
    await be.run(() async {
      final d = await CorrectionApi.purchase('p1');
      expect(d.docNo, 'KR-0042');
      expect(be.last('GET', '/purchases/p1').headers['authorization'], 'Bearer test-token');
      final rev0 = Api.stockRev.value;
      final res = await CorrectionApi.submit(receivingId: 'r1', body: {
        'client_uuid': 'u-1',
        'reason': 'xato',
        'lines': [
          {
            'purchase_item_id': 'i1',
            'reverse': [
              {'stock_batch_id': 'L1', 'qty': 2}
            ]
          }
        ],
      });
      expect(res.correctionId, 'c9');
      expect(res.deltaCents, -2000000);
      expect(be.last('POST', '/receiving/r1/corrections').body['client_uuid'], 'u-1');
      expect(Api.stockRev.value, greaterThan(rev0));
    });
  });

  test('submit(): a coded 409 keeps its X-Error-Code; a network failure is connectivity (outcome unknown)', () async {
    signIn(role: 'menejer', permissions: ['xaridlar.edit']);
    final be = FakeBackend()
      ..post('/receiving/{rid}/corrections', (r) => FakeResponse.error(
          409,
          "Bu client_uuid BOSHQA tuzatish so'rovida ishlatilgan — takror emas. Yangi so'rov uchun yangi client_uuid bering.",
          code: 'LOT_CORRECTION_REPLAY_CONFLICT'));
    await be.run(() async {
      final e = await CorrectionApi.submit(receivingId: 'r1', body: {}).then<Object?>((_) => null, onError: (Object e) => e);
      expect(e, isA<ApiException>());
      expect((e as ApiException).code, 'LOT_CORRECTION_REPLAY_CONFLICT');
      expect(e.isConflict, isTrue);
      be.offline = true;
      final n = await CorrectionApi.submit(receivingId: 'r1', body: {}).then<Object?>((_) => null, onError: (Object e) => e);
      expect((n as ApiException).isConnectivity, isTrue);
    });
  });

  test('cash custody block with an unknown shape fails closed', () {
    final j = purchaseJson()..['cash_custody'] = null;
    final d = PurchaseDoc.fromJson(j);
    expect(d.cashCustody!.mode, CustodyMode.blocked);
  });
}
