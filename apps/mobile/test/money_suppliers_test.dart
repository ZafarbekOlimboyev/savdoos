// M4 suppliers: gating, list/filter, detail tabs (lazy ledger), create/edit
// (no blind retry of a non-idempotent create), payment with custody.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/screens/money_payment_sheet.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart' show PurchaseDetailScreen;
import 'package:savdoos_mobile/screens/supplier_detail_screen.dart';
import 'package:savdoos_mobile/screens/suppliers_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

FakeBackend _backend({String role = 'ega', List<String> perms = const []}) {
  final be = FakeBackend()
    ..get('/auth/context', (_) => contextJson(role: role, permissions: perms))
    ..get('/suppliers', (_) => [
          supplierJson(),
          supplierJson(id: 's2', name: 'Coca-Cola', balance: 0),
          supplierJson(id: 's3', name: 'Lactel', balance: 50000.5),
        ])
    ..get('/suppliers/{id}', (r) => supplierDetailJson(id: r.params['id']!))
    ..get('/suppliers/{id}/ledger', (_) => supplierLedgerJson());
  signIn(role: role, permissions: perms);
  return be;
}

Future<void> _boot(WidgetTester tester, Widget screen) async {
  await Session.instance.load(force: true);
  await pumpAt390(tester, screen);
  await tester.pumpAndSettle();
}

Finder _inSheet(Finder f) => find.descendant(of: find.byType(MoneyPaymentSheet), matching: f);

void main() {
  setUp(() async => resetCore());

  testWidgets('menejer without xaridlar.view sees a no-access state and no request is made', (tester) async {
    final be = _backend(role: 'menejer', perms: ['sotuvlar.view', 'mijozlar.edit', 'hisobot.view']);
    await be.run(() async {
      await _boot(tester, const SuppliersScreen());
      expect(find.byKey(const Key('no-access')), findsOneWidget);
      expect(be.calls('GET', '/suppliers'), isEmpty);
    });
  });

  testWidgets('list: total we owe, owed filter, local search, open detail', (tester) async {
    final be = _backend(role: 'omborchi', perms: ['xaridlar.view', 'xaridlar.edit']);
    await be.run(() async {
      await _boot(tester, const SuppliersScreen());
      expect(find.text('Nestle'), findsOneWidget);
      expect(find.text('Coca-Cola'), findsOneWidget);
      expect(find.textContaining(formatCents(30000000 + 5000050)), findsOneWidget, reason: 'sum of server balances');
      expect(find.byKey(const Key('supplier-create')), findsOneWidget);

      await tester.tap(find.byKey(const Key('filter-owed')));
      await tester.pumpAndSettle();
      expect(find.text('Coca-Cola'), findsNothing);

      await tester.enterText(find.byKey(const Key('supplier-search')), 'lac');
      await tester.pumpAndSettle();
      expect(find.text('Nestle'), findsNothing);
      expect(find.text('Lactel'), findsOneWidget);

      await tester.tap(find.byKey(const Key('supplier-s3')));
      await tester.pumpAndSettle();
      expect(find.byType(SupplierDetailScreen), findsOneWidget);
      expect(be.last('GET', '/suppliers/s3'), isNotNull);
    });
  });

  testWidgets('detail: purchases, lazy ledger, products', (tester) async {
    final be = _backend();
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      expect(find.text('K-0002'), findsOneWidget);
      expect(find.text('Qarzga'), findsOneWidget, reason: 'purchase status translated');
      expect(be.calls('GET', '/suppliers/s1/ledger'), isEmpty, reason: 'ledger loads only when opened');

      await tester.tap(find.byKey(const Key('supplier-tab-ledger')));
      await tester.pumpAndSettle();
      expect(be.calls('GET', '/suppliers/s1/ledger'), hasLength(1));
      await tester.ensureVisible(find.byKey(const Key('supplier-ledger')));
      await tester.pumpAndSettle();
      expect(find.text('Tovar qabul'), findsOneWidget);
      expect(find.textContaining(formatCents(10000000)), findsWidgets);

      await tester.tap(find.byKey(const Key('supplier-tab-products')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Sut 1L'));
      await tester.pumpAndSettle();
      expect(find.text('Sut 1L'), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('supplier-tab-ledger')));
    });
  });

  testWidgets('a purchase row opens the purchase document (M3 screen)', (tester) async {
    final be = _backend(role: 'omborchi', perms: ['xaridlar.view']);
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      await tester.ensureVisible(find.byKey(const Key('purchase-p2')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('purchase-p2')));
      await tester.pumpAndSettle();
      expect(find.byType(PurchaseDetailScreen), findsOneWidget);
      expect(be.last('GET', '/purchases/p2'), isNotNull);
    });
  });

  testWidgets('payment, SERVER_RESOLVED: shows the till, sends no account, reports the paid amount', (tester) async {
    final be = _backend()
      ..get('/cash/custody-preview', (_) => custodyJson('SERVER_RESOLVED', resolved: kTill))
      ..post('/suppliers/{id}/payments', (r) => {'supplier_id': 's1', 'balance': 200000.0, 'paid': 100000.0});
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      await tester.tap(find.descendant(
          of: find.byKey(const Key('supplier-pay-bar')), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(be.last('GET', '/cash/custody-preview').query, {'operation': 'supplier_payment'});
      expect(find.byKey(const Key('custody-resolved')), findsOneWidget);
      expect(find.textContaining('K-01'), findsOneWidget);

      await tester.enterText(_inSheet(find.byKey(const Key('pay-amount'))), '100000');
      await tester.tap(_inSheet(find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      final body = be.last('POST', '/suppliers/s1/payments').body;
      expect(body['amount'], 100000);
      expect(body['method'], 'cash');
      expect(body.containsKey('cash_account_id'), isFalse);
      expect(find.byType(MoneyPaymentSheet), findsNothing);
      expect(find.byKey(const Key('supplier-notice')), findsOneWidget);
      expect(find.textContaining(formatCents(10000000)), findsWidgets);
    });
  });

  testWidgets('payment replay: duplicate is said explicitly', (tester) async {
    final be = _backend()
      ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
      ..post('/suppliers/{id}/payments',
          (r) => {'supplier_id': 's1', 'balance': 200000.0, 'paid': 100000.0, 'duplicate': true});
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      await tester.tap(find.descendant(
          of: find.byKey(const Key('supplier-pay-bar')), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      await tester.tap(_inSheet(find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(find.text('Bu to‘lov avval saqlangan edi — qayta yozilmadi.'), findsOneWidget);
    });
  });

  testWidgets('payment rejected for the custody account: translated, custody reloaded', (tester) async {
    L.code = 'ru';
    final be = _backend()
      ..get('/cash/custody-preview',
          (_) => custodyJson('OPERATOR_MUST_CHOOSE', reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill]))
      ..post('/suppliers/{id}/payments', (_) => FakeResponse.error(
          400, "CASH_CUSTODY_ACCOUNT_INVALID: 'supplier_payment': hisob boshqa filialga tegishli"));
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      await tester.tap(find.descendant(
          of: find.byKey(const Key('supplier-pay-bar')), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('custody-option-t1')));
      await tester.pumpAndSettle();
      await tester.tap(_inSheet(find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(be.last('POST', '/suppliers/s1/payments').body['cash_account_id'], 't1');
      expect(find.byKey(const Key('pay-error')), findsOneWidget);
      expect(find.textContaining('CASH_CUSTODY'), findsNothing, reason: 'no raw code on screen');
      expect(be.calls('GET', '/cash/custody-preview'), hasLength(2), reason: 'custody re-read after a custody rejection');
    });
  });

  testWidgets('xaridlar.view only: pay bar disabled with a reason, no edit', (tester) async {
    final be = _backend(role: 'menejer', perms: ['xaridlar.view']);
    await be.run(() async {
      await _boot(tester, const SupplierDetailScreen(supplierId: 's1', name: 'Nestle'));
      final bar = find.byKey(const Key('supplier-pay-bar'));
      expect(find.descendant(of: bar, matching: find.byKey(const Key('sticky-reason'))), findsOneWidget);
      expect(find.byKey(const Key('supplier-edit')), findsNothing);
    });
  });

  testWidgets('create: validation, then a lost answer is NOT blindly retried', (tester) async {
    final be = _backend()..post('/suppliers', (_) => throw Exception('timeout-ish reset'));
    await be.run(() async {
      await _boot(tester, const SuppliersScreen());
      await tester.tap(find.byKey(const Key('supplier-create')));
      await tester.pumpAndSettle();
      expect(find.byType(SupplierForm), findsOneWidget);
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(find.text('Nomini kiriting'), findsOneWidget);
      expect(be.calls('POST', '/suppliers'), isEmpty);

      await tester.enterText(find.byKey(const Key('supplier-name')), 'Pepsi');
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('supplier-unknown')), findsOneWidget);
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(be.calls('POST', '/suppliers'), hasLength(1), reason: 'no duplicate supplier from a blind retry');
      expect(find.text('Avval ro‘yxatni tekshiring'), findsOneWidget);
    });
  });

  testWidgets('a decided refusal after a lost create answer keeps the form blocked', (tester) async {
    // `POST /suppliers` da idempotentlik kaliti YO'Q: javobsiz urinishdan keyin
    // ko'r-ko'rona qayta saqlash ikkinchi ta'minotchi yaratishi mumkin. Keyingi
    // ANIQ rad javobi ham buni o'zgartirmaydi — muzlash YOPISHQOQ.
    var n = 0;
    final be = _backend()
      ..post('/suppliers', (_) {
        n++;
        if (n == 1) throw Exception('timeout-ish reset');
        return FakeResponse.error(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456");
      });
    await be.run(() async {
      await _boot(tester, const SuppliersScreen());
      await tester.tap(find.byKey(const Key('supplier-create')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('supplier-name')), 'Pepsi');
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('supplier-unknown')), findsOneWidget);
      expect(find.text('Avval ro‘yxatni tekshiring'), findsOneWidget,
          reason: 'a blind retry could create a second supplier');
    });
  });

  testWidgets('create ok opens the new supplier; edit sends only changes', (tester) async {
    final be = _backend()
      ..post('/suppliers', (r) => {'id': 's9', 'name': r.body['name'], 'phone': null, 'balance': 0})
      ..patch('/suppliers/{id}', (r) => {'id': 's1', 'name': r.body['name'] ?? 'Nestle', 'phone': '+996555000111', 'balance': 300000});
    await be.run(() async {
      await _boot(tester, const SuppliersScreen());
      await tester.tap(find.byKey(const Key('supplier-create')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('supplier-name')), 'Pepsi');
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(be.last('POST', '/suppliers').body, {'name': 'Pepsi'});
      expect(find.byType(SupplierDetailScreen), findsOneWidget);
      expect(be.last('GET', '/suppliers/s9'), isNotNull);

      await tester.tap(find.byKey(const Key('supplier-edit')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('supplier-name')), 'Nestle KG');
      await tester.pump();
      await tester.tap(find.descendant(of: find.byType(SupplierForm), matching: find.byKey(const Key('sticky-primary'))));
      await tester.pumpAndSettle();
      expect(be.last('PATCH', '/suppliers/s9').body, {'name': 'Nestle KG'});
      expect(find.byKey(const Key('supplier-notice')), findsOneWidget);
    });
  });
}
