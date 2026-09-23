// Shared fixtures of the M3 (receiving correction) tests — server-shaped
// `GET /purchases/{id}` payloads (apps/server/app/api/v1/purchases.py
// `purchase_detail` + `_correction_view`). Imported by the other
// `correction_*_test.dart` files; its own `main` checks the fixtures parse.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/correction_api.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

/// A lot of `items[].lots[]`.
Map<String, dynamic> lotJson(
  String id, {
  String? batch,
  String? expiry,
  num received = 1,
  num? remaining,
  num consumed = 0,
  num unitCost = 10000,
  Object? docUnitCost = _unset,
  bool correctable = true,
  String status = 'open',
  String? blockedReason,
}) =>
    {
      'id': id,
      'batch_no': batch,
      'expiry_date': expiry,
      'received_qty': received.toDouble(),
      'remaining_qty': (remaining ?? received).toDouble(),
      'consumed_qty': consumed.toDouble(),
      'unit_cost': unitCost.toDouble(),
      'status': status,
      'correctable': correctable,
      if (!identical(docUnitCost, _unset)) 'doc_unit_cost': docUnitCost,
      if (blockedReason != null) 'blocked_reason': blockedReason,
    };

const Object _unset = Object();

/// A line of `items[]`.
Map<String, dynamic> itemJson(
  String id,
  String productId,
  String name, {
  num qty = 1,
  num unitCost = 10000,
  String unit = 'dona',
  bool trackLots = true,
  bool trackExpiry = false,
  bool correctable = true,
  String? blockedReason,
  List<Map<String, dynamic>> lots = const [],
}) =>
    {
      'id': id,
      'product_id': productId,
      'name': name,
      'qty': qty.toDouble(),
      'unit_cost': unitCost.toDouble(),
      'line_total': (qty * unitCost).toDouble(),
      'sell_price': 0.0,
      'unit': unit,
      'stock': 0.0,
      'track_lots': trackLots,
      'track_expiry': trackExpiry,
      'correctable': correctable,
      'correction_blocked_reason': blockedReason,
      'lots': lots,
    };

/// A custody block.
Map<String, dynamic> custodyJson(String mode,
        {String? reason, Map<String, dynamic>? resolved, List<Map<String, dynamic>> options = const []}) =>
    {
      'mode': mode,
      'reason': reason,
      'resolved': resolved,
      'options': options,
      'branch': {'id': 'b1', 'name': 'Markaz'},
    };

const Map<String, dynamic> kTill = {'id': 't1', 'type': 'TILL', 'code': 'K-01', 'currency': 'UZS'};
const Map<String, dynamic> kSafe = {'id': 's1', 'type': 'SAFE', 'code': 'S-01', 'currency': 'UZS'};

/// The standard document:
///  * i1 «Sut 1L» 10 × 10 000 (lot-tracked): L1 6/6 (doc 10 000, own 12 000),
///    L2 received 4, remaining 1, 3 moved (identity frozen);
///  * i2 «Kefir» 5 × 10 000 (lot + expiry): L3 5/5 expiring 2026-12-01;
///  * total = paid = 150 000 (cash), custody NOT_REQUIRED by default.
Map<String, dynamic> purchaseJson({
  String id = 'p1',
  String? receivingId = 'r1',
  num total = 150000,
  num? paid,
  String payment = 'cash',
  String status = 'received',
  bool correctable = true,
  String? blockedReason,
  Map<String, dynamic>? custody,
  bool withCustody = true,
  List<Map<String, dynamic>>? items,
  List<Map<String, dynamic>> corrections = const [],
  String? businessDate = '2026-09-19',
}) =>
    {
      'id': id,
      'doc_no': 'KR-0042',
      'branch_id': 'b1',
      'branch_name': 'Markaz',
      'business_date': businessDate,
      'supplier': 'Oq Sut MChJ',
      'supplier_id': 'sup1',
      'date': '2026-09-18',
      'status': status,
      'payment': payment,
      'subtotal': total.toDouble(),
      'total': total.toDouble(),
      'paid_amount': (paid ?? total).toDouble(),
      'items': items ??
          [
            itemJson('i1', 'p-sut', 'Sut 1L', qty: 10, lots: [
              lotJson('L1', batch: 'A-1', received: 6, unitCost: 12000, docUnitCost: 10000.0),
              lotJson('L2', batch: 'A-2', received: 4, remaining: 1, consumed: 3, correctable: false, docUnitCost: 10000.0),
            ]),
            itemJson('i2', 'p-kefir', 'Kefir', qty: 5, trackExpiry: true, lots: [
              lotJson('L3', expiry: '2026-12-01', received: 5, docUnitCost: 10000.0),
            ]),
          ],
      'receiving_id': receivingId,
      'correctable': correctable,
      'correction_blocked_reason': blockedReason,
      'corrections': corrections,
      if (withCustody) 'cash_custody': custody ?? custodyJson('NOT_REQUIRED'),
    };

/// A document whose every lot is untouched (a full cancel is possible):
/// i1 3 × 20 000 (L1 3/3) + i2 2 × 5 000,5 (L3 2/2); total = paid = 70 001.
Map<String, dynamic> freshPurchaseJson({Map<String, dynamic>? custody, num? paid, String payment = 'cash'}) =>
    purchaseJson(
      total: 70001,
      paid: paid,
      payment: payment,
      custody: custody,
      items: [
        itemJson('i1', 'p-sut', 'Sut 1L', qty: 3, unitCost: 20000, lots: [
          lotJson('L1', received: 3, unitCost: 20000, docUnitCost: 20000.0),
        ]),
        itemJson('i2', 'p-kefir', 'Kefir', qty: 2, unitCost: 5000.5, trackExpiry: true, lots: [
          lotJson('L3', expiry: '2026-12-01', received: 2, unitCost: 5000.5, docUnitCost: 5000.5),
        ]),
      ],
    );

PurchaseDoc doc([Map<String, dynamic>? j]) => PurchaseDoc.fromJson(j ?? purchaseJson());

void main() {
  test('fixtures parse into the server-shaped model', () {
    final d = doc();
    expect(d.docNo, 'KR-0042');
    expect(d.totalCents, 15000000);
    expect(d.paidCents, 15000000);
    expect(d.lines, hasLength(2));
    expect(d.lines.first.lots.map((l) => l.id), ['L1', 'L2']);
    expect(d.lines.first.lots.first.docCostCents, 1000000);
    expect(d.lines.first.lots.first.unitCostCents, 1200000);
    expect(d.lines.first.lots.last.remainingMilli, 1000);
    expect(d.lines.first.lots.last.correctable, isFalse);
    expect(d.cashCustody!.mode, CustodyMode.notRequired);
    expect(d.correctionOpen, isTrue);
    expect(d.businessDate, '2026-09-19');
    final f = doc(freshPurchaseJson());
    expect(f.totalCents, 7000100);
  });
}
