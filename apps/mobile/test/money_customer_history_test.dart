// IC (Phase 5G integration): the customer profile now reads the additive
// fields of `GET /customers/{id}/detail` — a purchase row carries `sale_id`
// and `receipt_no` (it opens the server receipt when the user may read one)
// and `items_qty`, the exact 3-decimal quantity, so a weighed purchase is no
// longer shown as a truncated whole count; a debt payment shows its stored
// `method`. An older server sends none of them and the rows stay as they were.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/customer_profile_screen.dart';
import 'package:savdoos_mobile/screens/sales_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

/// A weighed purchase (opens a receipt), a whole one, and a row from a server
/// before Phase 5G (no `sale_id` / `receipt_no` / `items_qty`).
const List<Map<String, dynamic>> kHistory = [
  {
    'date': '2026-09-18T10:00:00',
    'items': 3,
    'items_qty': '3.500',
    'amount': 45000.0,
    'method': 'card',
    'sale_id': 's1',
    'receipt_no': '#1042',
  },
  {
    'date': '2026-09-17T10:00:00',
    'items': 2,
    'items_qty': '2.000',
    'amount': 20000.0,
    'method': 'cash',
    'sale_id': 's2',
    'receipt_no': '#1041',
  },
  {'date': '2026-09-16T10:00:00', 'items': 5, 'amount': 5000.0, 'method': 'cash'},
];

/// One payment with the stored method, one from an older server.
const List<Map<String, dynamic>> kPayments = [
  {'date': '2026-09-17T09:00:00', 'amount': 50000.0, 'method': 'qr'},
  {'date': '2026-09-15T09:00:00', 'amount': 1000.0},
];

Map<String, dynamic> _detailJson({
  List<Map<String, dynamic>> history = kHistory,
  List<Map<String, dynamic>> payments = kPayments,
}) =>
    {
      ...customerDetailJson(balance: 0),
      'history': history,
      'payments': payments,
    };

FakeBackend _backend({
  String role = 'ega',
  List<String> perms = const [],
  List<Map<String, dynamic>> history = kHistory,
}) {
  final be = FakeBackend()
    ..get('/auth/context', (_) => contextJson(role: role, permissions: perms))
    ..get('/customers/{id}/detail', (_) => _detailJson(history: history))
    ..get('/sales/{id}/receipt', (_) => saleReceiptJson());
  signIn(role: role, permissions: perms);
  return be;
}

Future<void> _open(WidgetTester tester, FakeBackend be) async {
  await Session.instance.load(force: true);
  await pumpAt390(tester, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
  await tester.pumpAndSettle();
}

/// The texts of the payment row carrying [amount] (grouped with NBSP), joined.
String _rowTexts(WidgetTester tester, String amount) {
  final row = find.ancestor(of: find.textContaining(amount), matching: find.byType(Row)).first;
  return [
    for (final e in find.descendant(of: row, matching: find.byType(Text)).evaluate())
      (e.widget as Text).data ?? ''
  ].join(' | ');
}

void main() {
  setUp(() async => resetCore());
  tearDown(() {
    L.code = 'uz';
    Session.instance.debugReset();
  });

  group('purchase history', () {
    testWidgets('a row with sale_id opens the server receipt; the number is shown', (tester) async {
      final be = _backend();
      await be.run(() async {
        await _open(tester, be);
        expect(find.textContaining('№#1042'), findsOneWidget);
        expectMinTouchTarget(tester, find.byKey(const Key('customer-sale-s1')));
        await tester.tap(find.byKey(const Key('customer-sale-s1')));
        await tester.pumpAndSettle();
        expect(find.byType(SalesDetailScreen), findsOneWidget);
        expect(be.calls('GET', '/sales/s1/receipt'), hasLength(1));
        expect(be.calls('GET', '/sales/s2/receipt'), isEmpty);
      });
    });

    testWidgets('no sales.receipt: the row is not tappable', (tester) async {
      final be = _backend(role: 'omborchi', perms: ['mijozlar.view', 'ombor.view']);
      await be.run(() async {
        await _open(tester, be);
        // The row still renders (and still shows its receipt number).
        expect(find.byKey(const Key('customer-sale-s1')), findsOneWidget);
        expect(find.textContaining('№#1042'), findsOneWidget);
        await tester.tap(find.byKey(const Key('customer-sale-s1')));
        await tester.pumpAndSettle();
        expect(find.byType(SalesDetailScreen), findsNothing);
        expect(be.calls('GET', '/sales/s1/receipt'), isEmpty);
      });
    });

    testWidgets('older server (no sale_id): nothing to open, no id is guessed', (tester) async {
      final be = _backend(history: [kHistory.last]);
      await be.run(() async {
        await _open(tester, be);
        expect(find.byKey(const Key('customer-sale-s1')), findsNothing);
        expect(find.textContaining('№'), findsNothing);
        await tester.tap(find.text('5 ta tovar · Naqd'));
        await tester.pumpAndSettle();
        expect(find.byType(SalesDetailScreen), findsNothing);
        expect(be.calls('GET', '/sales/s1/receipt'), isEmpty);
      });
    });

    testWidgets('quantity: fractional keeps 3 decimals, whole reads as a count, older server falls back',
        (tester) async {
      final be = _backend();
      await be.run(() async {
        await _open(tester, be);
        // 3.500 kg is NOT "3 ta tovar".
        expect(find.text('Miqdor: 3,500 · Karta'), findsOneWidget);
        expect(find.text('3 ta tovar · Karta'), findsNothing);
        expect(find.text('2 ta tovar · Naqd'), findsOneWidget);
        // No `items_qty` -> the integer `items` of the old payload.
        expect(find.text('5 ta tovar · Naqd'), findsOneWidget);
      });
    });
  });

  group('debt payments', () {
    testWidgets('the stored method is localized; an older row shows only the date', (tester) async {
      final be = _backend();
      await be.run(() async {
        await _open(tester, be);
        // (The date itself is device-local, so only the method half is asserted.)
        expect(_rowTexts(tester, '+50 000'), contains(' · QR'));
        expect(_rowTexts(tester, '+1 000'), isNot(contains(' · ')),
            reason: 'older server: no method, no empty separator');
      });
    });
  });

  for (final lang in ['ru', 'ky']) {
    testWidgets('$lang at 390: history and payments fit', (tester) async {
      final be = _backend();
      L.code = lang;
      await be.run(() async {
        await _open(tester, be);
        expect(tester.takeException(), isNull);
        expect(find.byKey(const Key('customer-sale-s1')), findsOneWidget);
        await tester.tap(find.byKey(const Key('customer-sale-s1')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull, reason: 'receipt from the history row');
      });
    });
  }
}
