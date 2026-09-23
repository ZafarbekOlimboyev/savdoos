// M4 API layer: request shapes (query, bodies, idempotency key, custody
// account only when chosen), exact integer money parsing, receipt DTO parsing.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/money_api.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

void main() {
  setUp(() async {
    await resetCore();
    signIn();
  });

  group('customers', () {
    test('list sends q and only_debt; money is exact cents', () async {
      final be = FakeBackend()
        ..get('/customers', (r) => [
              {'id': 'c1', 'code': 'M-1001', 'full_name': 'Ali', 'phone': '+996700111222', 'credit_balance': 150000.5},
              {'id': 'c2', 'code': 'M-1002', 'full_name': 'Vali', 'phone': null, 'credit_balance': -2000},
            ]);
      final rows = await be.run(() => MoneyApi.customers(q: ' ali ', onlyDebt: true));
      expect(be.last('GET', '/customers').query, {'q': 'ali', 'only_debt': 'true'});
      expect(rows.first.balanceCents, 15000050);
      expect(rows.first.hasDebt, isTrue);
      expect(rows.last.balanceCents, -200000);
      expect(rows.last.phone, isNull);

      await be.run(() => MoneyApi.customers());
      expect(be.last('GET', '/customers').query, isEmpty, reason: 'no empty q / only_debt=false noise');
    });

    test('detail parses history, payments and totals', () async {
      final be = FakeBackend()..get('/customers/{id}/detail', (r) => customerDetailJson(id: r.params['id']!));
      final p = await be.run(() => MoneyApi.customerDetail('c1'));
      expect(p.balanceCents, 12345600);
      expect(p.totalSpentCents, 99900000);
      expect(p.visits, 7);
      expect(p.history.single.method, 'card');
      expect(p.history.single.items, 3);
      expect(p.payments.single.amountCents, 5000000);
    });

    test('create sends client_uuid and only non-empty optional fields', () async {
      final be = FakeBackend()
        ..post('/customers', (r) => {'id': 'c9', 'code': 'M-1009', 'full_name': r.body['full_name'], 'credit_balance': 0});
      final c = await be.run(() => MoneyApi.createCustomer(fullName: 'Aziz', phone: '  ', address: '', clientUuid: 'u-1'));
      expect(be.last('POST', '/customers').body, {'full_name': 'Aziz', 'client_uuid': 'u-1'});
      expect(c.id, 'c9');
    });

    test('edit sends only the changed fields; empty phone clears it', () async {
      final be = FakeBackend()
        ..patch('/customers/{id}', (r) => {'id': 'c1', 'code': 'M-1', 'full_name': 'X', 'credit_balance': 0});
      await be.run(() => MoneyApi.editCustomer('c1', phone: ''));
      expect(be.last('PATCH', '/customers/c1').body, {'phone': ''});
    });

    test('debt payment: whole-number JSON amount, method, uuid; account only when given', () async {
      final be = FakeBackend()
        ..post('/customers/{id}/payments', (r) => {'customer_id': 'c1', 'credit_balance': 2000.0});
      final r1 = await be.run(() => MoneyApi.payCustomerDebt('c1', amountCents: 5000000, method: 'card', clientUuid: 'u1'));
      final b1 = be.last('POST', '/customers/c1/payments').body;
      expect(b1, {'amount': 50000, 'method': 'card', 'client_uuid': 'u1'});
      expect(b1['amount'], isA<int>());
      expect(r1.balanceCents, 200000);

      await be.run(() =>
          MoneyApi.payCustomerDebt('c1', amountCents: 100, method: 'cash', cashAccountId: 't1', clientUuid: 'u2'));
      expect(be.last('POST', '/customers/c1/payments').body,
          {'amount': 1, 'method': 'cash', 'cash_account_id': 't1', 'client_uuid': 'u2'});
    });
  });

  group('suppliers', () {
    test('list, detail, ledger parse', () async {
      final be = FakeBackend()
        ..get('/suppliers', (r) => [supplierJson()])
        ..get('/suppliers/{id}', (r) => supplierDetailJson())
        ..get('/suppliers/{id}/ledger', (r) => supplierLedgerJson());
      final list = await be.run(MoneyApi.suppliers);
      expect(list.single.balanceCents, 30000000);
      expect(list.single.weOwe, isTrue);
      final d = await be.run(() => MoneyApi.supplierDetail('s1'));
      expect(d.purchaseCount, 2);
      expect(d.recentPurchases.first.status, 'debt');
      expect(d.products.first.qtyMilli, 12500);
      expect(d.lastPurchase, '2026-09-18');
      final l = await be.run(() => MoneyApi.supplierLedger('s1'));
      expect(l.first.amountCents, -10000000);
      expect(l.first.label, 'To‘lov');
      expect(l.last.label, 'Tovar qabul');
    });

    test('payment reports what the server recorded and replays', () async {
      final be = FakeBackend()
        ..post('/suppliers/{id}/payments',
            (r) => {'supplier_id': 's1', 'balance': 200000.0, 'paid': 100000.0, 'duplicate': true});
      final r = await be.run(() =>
          MoneyApi.paySupplier('s1', amountCents: 10000000, method: 'qr', clientUuid: 'u9'));
      expect(be.last('POST', '/suppliers/s1/payments').body, {'amount': 100000, 'method': 'qr', 'client_uuid': 'u9'});
      expect(r.paidCents, 10000000);
      expect(r.duplicate, isTrue);
    });

    test('create/edit bodies', () async {
      final be = FakeBackend()
        ..post('/suppliers', (r) => {'id': 's2', 'name': r.body['name'], 'phone': null, 'balance': 0})
        ..patch('/suppliers/{id}', (r) => {'id': 's2', 'name': 'N', 'phone': null, 'balance': 0});
      await be.run(() => MoneyApi.createSupplier(name: 'Nestle', phone: '+996 700 123 456'));
      expect(be.last('POST', '/suppliers').body, {'name': 'Nestle', 'phone': '+996 700 123 456'});
      await be.run(() => MoneyApi.editSupplier('s2', name: 'N'));
      expect(be.last('PATCH', '/suppliers/s2').body, {'name': 'N'});
    });
  });

  group('cash ops', () {
    test('destination_safe_id only for a collection', () {
      expect(MoneyApi.cashOpBody(type: 'payin', amountCents: 1000, destinationSafeId: 's1'),
          {'type': 'payin', 'amount': 10});
      expect(MoneyApi.cashOpBody(type: 'collection', amountCents: 1000, reason: ' x ', destinationSafeId: 's1'),
          {'type': 'collection', 'amount': 10, 'reason': 'x', 'destination_safe_id': 's1'});
    });

    test('post and history parse', () async {
      final be = FakeBackend()
        ..post('/cash/ops', (r) => {'ok': true, 'shift_id': 'sh1', 'duplicate': true})
        ..get('/cash/ops', (r) => [
              {'type': 'collection', 'amount': 5000.0, 'reason': null, 'employee': 'Ega', 'at': '2026-09-19T08:00:00'},
              {'type': 'payin', 'amount': 1.5, 'reason': 'x', 'employee': null, 'at': null},
            ]);
      final r = await be.run(() => MoneyApi.cashOp(type: 'expense', amountCents: 250000, reason: 'Ijara', clientUuid: 'u'));
      expect(r.duplicate, isTrue);
      expect(be.last('POST', '/cash/ops').body, {'type': 'expense', 'amount': 2500, 'reason': 'Ijara', 'client_uuid': 'u'});
      final h = await be.run(MoneyApi.cashOpsToday);
      expect(h.first.isIn, isFalse);
      expect(h.last.isIn, isTrue);
      expect(h.last.amountCents, 150);
    });
  });

  group('sales + receipt', () {
    test('list query: period, q, branch, limit', () async {
      final be = FakeBackend()..get('/sales', (r) => [saleRowJson()]);
      final rows = await be.run(() => MoneyApi.sales(period: SalesPeriod.week, branchId: 'b1'));
      expect(be.last('GET', '/sales').query, {'limit': '100', 'period': 'week', 'branch_id': 'b1'});
      expect(rows.single.totalCents, 1250050);
      expect(rows.single.branchName, 'Markaz');
      await be.run(() => MoneyApi.sales(period: SalesPeriod.all, q: '#12', limit: 300));
      expect(be.last('GET', '/sales').query, {'limit': '300', 'q': '#12'});
    });

    test('receipt DTO parses; amounts stay the server strings', () async {
      final be = FakeBackend()..get('/sales/{id}/receipt', (r) => saleReceiptJson());
      final r = await be.run(() => MoneyApi.saleReceipt('x1'));
      expect(r.schema, 'binos.receipt.v1');
      expect(r.kind, 'SALE');
      expect(r.number, '#1042');
      expect(r.lines, hasLength(2));
      expect(r.lines.last.weighted, isTrue);
      expect(r.total, '42240.00');
      expect(r.payments.map((p) => p.method), ['cash', 'card']);
      expect(r.payments.first.change, '760.00');
      expect(r.template.showTill, isTrue);
      expect(r.isReturn, isFalse);

      final ret = Receipt.fromJson(returnReceiptJson());
      expect(ret.isReturn, isTrue);
      expect(ret.refundMethod, 'cash');
      expect(ret.originalNumber, '#1042');
    });

    test('a failure is an ApiException (never a silent empty list)', () async {
      final be = FakeBackend()..get('/sales/{id}/receipt', (r) => FakeResponse.error(404, 'Chek topilmadi'));
      await expectLater(be.run(() => MoneyApi.saleReceipt('zz')), throwsA(isA<ApiException>()));
      be.offline = true;
      await expectLater(
          be.run(() => MoneyApi.sales()),
          throwsA(isA<ApiException>().having((e) => e.isConnectivity, 'connectivity', isTrue)));
    });
  });
}
