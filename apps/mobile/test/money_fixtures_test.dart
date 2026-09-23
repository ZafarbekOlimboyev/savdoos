// Shared M4 fixtures (server payload shapes copied from apps/server) + a sanity
// test that the receipt fixtures obey the server invariant
// subtotal − line_discount − doc_discount + rounding == total.
//
// Other money_* tests import this file for the builders.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/qty.dart';

import 'support/support.dart';

/// `GET /customers/{id}/detail`.
Map<String, dynamic> customerDetailJson({String id = 'c1', num balance = 123456, String name = 'Ali Valiyev'}) => {
      'id': id,
      'code': 'M-1001',
      'full_name': name,
      'phone': '+996700111222',
      'credit_balance': balance,
      'total_spent': 999000,
      'visits': 7,
      'history': [
        {'date': '2026-09-18T10:00:00', 'items': 3, 'amount': 45000.0, 'method': 'card'},
      ],
      'payments': [
        {'date': '2026-09-17T09:00:00', 'amount': 50000.0},
      ],
    };

/// `SupplierOut`.
Map<String, dynamic> supplierJson({String id = 's1', String name = 'Nestle', num balance = 300000}) =>
    {'id': id, 'name': name, 'phone': '+996555000111', 'balance': balance};

/// `GET /suppliers/{id}`.
Map<String, dynamic> supplierDetailJson({String id = 's1', num balance = 300000}) => {
      'id': id,
      'name': 'Nestle',
      'phone': '+996555000111',
      'balance': balance,
      'purchase_count': 2,
      'total_purchased': 900000.0,
      'paid_total': 600000.0,
      'product_types': 2,
      'total_qty': 20.5,
      'avg_purchase': 450000.0,
      'expected_profit': 120000.0,
      'profit_margin': 13.3,
      'last_purchase': '2026-09-18',
      'top_qty_product': {'name': 'Sut', 'qty': 12.5},
      'top_profit_product': {'name': 'Sut', 'profit': 80000.0},
      'products': [
        {'name': 'Sut 1L', 'qty': 12.5, 'cost': 500000.0, 'profit': 80000.0},
        {'name': 'Qatiq', 'qty': 8, 'cost': 400000.0, 'profit': 40000.0},
      ],
      'recent_purchases': [
        {'id': 'p2', 'doc_no': 'K-0002', 'date': '2026-09-18', 'total': 400000.0, 'status': 'debt'},
        {'id': 'p1', 'doc_no': 'K-0001', 'date': '2026-09-10', 'total': 500000.0, 'status': 'received'},
      ],
    };

/// `GET /suppliers/{id}/ledger` (newest first).
List<Map<String, dynamic>> supplierLedgerJson() => [
      {'type': 'payment', 'amount': -100000.0, 'balance_after': 300000.0, 'ref_type': 'payment', 'at': '2026-09-19T07:00:00'},
      {'type': 'charge', 'amount': 400000.0, 'balance_after': 400000.0, 'ref_type': 'receiving', 'at': '2026-09-18T07:00:00'},
    ];

/// A `GET /sales` row.
Map<String, dynamic> saleRowJson({String id = 'x1', String no = '#1042'}) => {
      'id': id,
      'receipt_no': no,
      'sold_at': '2026-09-19T09:30:00',
      'cashier': 'Kassir 1',
      'method': 'cash',
      'item_count': 3.352,
      'first_item': 'Non',
      'total': 12500.5,
      'branch_id': 'b1',
      'cashier_id': 'e2',
      'shift_id': 'sh1',
      'till_id': 't1',
      'terminal_id': null,
      'cashier_name': 'Kassir 1',
      'branch_name': 'Markaz',
      'till_code': 'K-01',
      'till_label': null,
      'terminal_name': null,
    };

Map<String, dynamic> _template({bool showTill = true, bool showDiscount = true, String? footer}) => {
      'header': 'Xush kelibsiz',
      'footer': footer,
      'show_barcode': false,
      'store_display_name': null,
      'address': null,
      'phone': null,
      'width_mm': 80,
      'lang': null,
      'show_logo': false,
      'show_branch': true,
      'show_stir': true,
      'show_cashier': true,
      'show_till': showTill,
      'show_payment_breakdown': true,
      'show_discount': showDiscount,
      'show_customer': false,
      'qr_mode': 'none',
      'auto_cut': true,
      'copies': 1,
      'auto_print': false,
    };

/// `GET /sales/{id}/receipt` — a mixed-payment sale with a line discount,
/// a document discount and rounding.
Map<String, dynamic> saleReceiptJson({String status = 'completed', bool showDiscount = true}) => {
      'schema': 'binos.receipt.v1',
      'kind': 'SALE',
      'test': false,
      'provisional': false,
      'doc': {
        'id': 'x1',
        'number': '#1042',
        'uid': 'R-7Q2K',
        'issued_at': '2026-09-19T04:30:00+00:00',
        'issued_at_local': '19.09.2026 10:30',
        'tz': 'Asia/Bishkek',
        'is_offline': false,
        'status': status,
      },
      'store': {'name': 'Fayzan', 'branch_name': 'Markaz', 'address': 'Toktogul 1', 'phone': '+996312000000', 'stir': '123456789'},
      'actor': {'cashier': 'Kassir 1', 'till_code': 'K-01', 'terminal': 'POS-1'},
      'customer': null,
      'lines': [
        {
          'name': 'Non',
          'qty': '2.000',
          'unit': 'dona',
          'weighted': false,
          'unit_price': '15000.00',
          'gross': '30000.00',
          'discount': '1000.00',
          'total': '29000.00'
        },
        {
          'name': 'Olma',
          'qty': '0.352',
          'unit': 'kg',
          'weighted': true,
          'unit_price': '36000.00',
          'gross': '12672.00',
          'discount': '0.00',
          'total': '12672.00'
        },
      ],
      'totals': {
        'currency': 'UZS',
        'subtotal': '42672.00',
        'line_discount': '1000.00',
        'doc_discount': '0.00',
        'rounding': '568.00',
        'total': '42240.00',
      },
      'payments': [
        {'method': 'cash', 'amount': '40000.00', 'given': '40760.00', 'change': '760.00'},
        {'method': 'card', 'amount': '2240.00', 'given': null, 'change': null},
      ],
      'refund': null,
      'original': null,
      'barcode': null,
      'qr': null,
      'logo': null,
      'template': _template(showDiscount: showDiscount),
    };

/// `GET /returns/{id}/receipt` — amounts are POSITIVE; the renderer adds "−".
Map<String, dynamic> returnReceiptJson() => {
      'schema': 'binos.receipt.v1',
      'kind': 'RETURN',
      'test': false,
      'provisional': false,
      'doc': {
        'id': 'r1',
        'number': 'Q-17',
        'uid': null,
        'issued_at': '2026-09-19T06:00:00+00:00',
        'issued_at_local': '19.09.2026 12:00',
        'tz': 'Asia/Bishkek',
        'is_offline': false,
        'status': 'completed',
      },
      'store': {'name': 'Fayzan', 'branch_name': 'Markaz', 'address': null, 'phone': null, 'stir': null},
      'actor': {'cashier': 'Kassir 1', 'till_code': null, 'terminal': null},
      'customer': null,
      'lines': [
        {
          'name': 'Non',
          'qty': '1.000',
          'unit': 'dona',
          'weighted': false,
          'unit_price': '14500.00',
          'gross': '14500.00',
          'discount': '0.00',
          'total': '14500.00'
        },
      ],
      'totals': {
        'currency': 'UZS',
        'subtotal': '14500.00',
        'line_discount': '0.00',
        'doc_discount': '0.00',
        'rounding': '0.00',
        'total': '14500.00',
      },
      'payments': [],
      'refund': {'method': 'cash', 'amount': '14500.00'},
      'original': {'id': 'x1', 'number': '#1042', 'uid': 'R-7Q2K', 'issued_at_local': '19.09.2026 10:30'},
      'barcode': null,
      'qr': null,
      'logo': null,
      'template': _template(showTill: false, footer: 'Rahmat'),
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
const Map<String, dynamic> kSafe2 = {'id': 's2', 'type': 'SAFE', 'code': 'S-02', 'currency': 'UZS'};

void main() {
  setUp(() async => resetCore());

  test('receipt fixtures obey the server totals invariant', () {
    for (final r in [saleReceiptJson(), returnReceiptJson()]) {
      final t = r['totals'] as Map<String, dynamic>;
      int c(String k) => centsFromNum(t[k]);
      expect(c('subtotal') - c('line_discount') - c('doc_discount') + c('rounding'), c('total'));
    }
    final pays = (saleReceiptJson()['payments'] as List).map((p) => centsFromNum((p as Map)['amount']));
    expect(pays.fold<int>(0, (a, b) => a + b), centsFromNum('42240.00'));
  });
}
