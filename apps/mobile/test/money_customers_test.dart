// M4 customers & debt: server search, permission gating, create (idempotent
// retry), edit, debt payment with the cash-custody decision of the server.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/screens/customer_edit_screen.dart';
import 'package:savdoos_mobile/screens/customer_profile_screen.dart';
import 'package:savdoos_mobile/screens/customers_screen.dart';
import 'package:savdoos_mobile/screens/debtors_screen.dart';
import 'package:savdoos_mobile/screens/money_payment_sheet.dart';
import 'package:savdoos_mobile/session.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

Map<String, dynamic> _row(String id, String name, num balance) =>
    {'id': id, 'code': 'M-$id', 'full_name': name, 'phone': null, 'credit_balance': balance};

/// Backend with a signed-in [role] and customer routes.
FakeBackend _backend({String role = 'ega', List<String> perms = const [], num balance = 123456}) {
  final be = FakeBackend()
    ..get('/auth/context', (_) => contextJson(role: role, permissions: perms))
    ..get('/customers', (r) => r.query['only_debt'] == 'true'
        ? [_row('c1', 'Ali Valiyev', balance)]
        : [_row('c1', 'Ali Valiyev', balance), _row('c2', 'Bobur', 0), _row('c3', 'Vali', -5000)])
    ..get('/customers/{id}/detail', (r) => customerDetailJson(id: r.params['id']!, balance: balance));
  signIn(role: role, permissions: perms);
  return be;
}

Future<void> _boot(WidgetTester tester, FakeBackend be, Widget screen) async {
  await Session.instance.load(force: true);
  await pumpAt390(tester, screen);
  await tester.pumpAndSettle();
}

Finder _inSheet(Finder f) => find.descendant(of: find.byType(MoneyPaymentSheet), matching: f);

Future<void> _openPaySheet(WidgetTester tester) async {
  await tester.tap(find.descendant(of: find.byKey(const Key('customer-pay-bar')), matching: find.byKey(const Key('sticky-primary'))));
  await tester.pumpAndSettle();
  expect(find.byType(MoneyPaymentSheet), findsOneWidget);
}

Future<void> _confirmPay(WidgetTester tester) async {
  await tester.tap(_inSheet(find.byKey(const Key('sticky-primary'))));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() async => resetCore());

  group('customers list', () {
    testWidgets('server search (debounced) and debtors filter with total', (tester) async {
      final be = _backend();
      await be.run(() async {
        await _boot(tester, be, const CustomersScreen());
        expect(find.text('Ali Valiyev'), findsOneWidget);
        expect(find.text('Bobur'), findsOneWidget);
        expect(find.text('Avans'), findsOneWidget, reason: 'negative balance = advance');

        await tester.enterText(find.byKey(const Key('customer-search')), 'ali');
        await tester.pump(const Duration(milliseconds: 100));
        expect(be.calls('GET', '/customers').where((r) => r.query['q'] == 'ali'), isEmpty, reason: 'debounced');
        await tester.pump(kSearchDebounce);
        await tester.pumpAndSettle();
        expect(be.last('GET', '/customers').query['q'], 'ali');

        await tester.tap(find.byKey(const Key('filter-debt')));
        await tester.pumpAndSettle();
        expect(be.last('GET', '/customers').query, {'q': 'ali', 'only_debt': 'true'});
        expect(find.byKey(const Key('debt-summary')), findsOneWidget);
        expect(find.textContaining(formatCents(12345600)), findsWidgets);
      });
    });

    testWidgets('DebtorsScreen opens the list on the debtors filter', (tester) async {
      final be = _backend();
      await be.run(() async {
        await _boot(tester, be, const DebtorsScreen());
        expect(be.last('GET', '/customers').query['only_debt'], 'true');
        expect(find.text('Qarzdorlar'), findsWidgets);
      });
    });

    testWidgets('create is hidden without mijozlar.edit / kassa.sell', (tester) async {
      final be = _backend(role: 'omborchi', perms: ['ombor.view', 'ombor.edit']);
      await be.run(() async {
        await _boot(tester, be, const CustomersScreen());
        expect(find.byKey(const Key('customer-create')), findsNothing);
      });
    });

    testWidgets('a kassir (kassa.sell) may create a customer', (tester) async {
      final be = _backend(role: 'kassir', perms: ['kassa.sell', 'mijozlar.view']);
      await be.run(() async {
        await _boot(tester, be, const CustomersScreen());
        expect(find.byKey(const Key('customer-create')), findsOneWidget);
        expectMinTouchTarget(tester, find.byKey(const Key('customer-create')));
      });
    });

    testWidgets('list failure shows a localized error with retry', (tester) async {
      L.code = 'ru';
      final be = _backend()..get('/customers', (_) => FakeResponse.error(500, 'Traceback: boom'));
      await be.run(() async {
        await _boot(tester, be, const CustomersScreen());
        expect(find.textContaining('Traceback'), findsNothing);
        expect(find.text('Повторить'), findsWidgets);
      });
    });
  });

  group('create / edit', () {
    testWidgets('validation, idempotent retry after a lost answer, then the profile opens', (tester) async {
      final be = _backend(role: 'menejer', perms: ['mijozlar.edit', 'mijozlar.view']);
      var fail = true;
      be.post('/customers', (r) {
        if (fail) {
          fail = false;
          throw Exception('connection reset');
        }
        return {'id': 'c9', 'code': 'M-1009', 'full_name': r.body['full_name'], 'phone': r.body['phone'], 'credit_balance': 0};
      });
      await be.run(() async {
        await _boot(tester, be, const CustomersScreen());
        await tester.tap(find.byKey(const Key('customer-create')));
        await tester.pumpAndSettle();
        expect(find.byType(CustomerEditScreen), findsOneWidget);

        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.text('Ismni kiriting'), findsOneWidget);
        expect(be.calls('POST', '/customers'), isEmpty);

        await tester.enterText(find.byKey(const Key('customer-name')), 'Aziz Karimov');
        await tester.enterText(find.byKey(const Key('customer-phone')), '+996 700 12');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.text('Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456'), findsOneWidget);
        expect(be.calls('POST', '/customers'), isEmpty);

        await tester.enterText(find.byKey(const Key('customer-phone')), '+996 700 123 456');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('customer-unknown')), findsOneWidget, reason: 'network failure is not success');
        expect(tester.widget<TextField>(find.byKey(const Key('customer-name'))).enabled, isFalse,
            reason: 'the retry must send the same draft');
        final first = be.last('POST', '/customers').body['client_uuid'];

        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        final calls = be.calls('POST', '/customers');
        expect(calls, hasLength(2));
        expect(calls.last.body['client_uuid'], first, reason: 'retry reuses the idempotency key');
        expect(calls.last.body['full_name'], 'Aziz Karimov');
        expect(find.byType(CustomerProfileScreen), findsOneWidget);
        expect(be.last('GET', '/customers/c9/detail'), isNotNull);
      });
    });

    testWidgets('create answered 502: draft frozen, retry reuses the client_uuid', (tester) async {
      var n = 0;
      final be = _backend(role: 'menejer', perms: ['mijozlar.edit', 'mijozlar.view'])
        ..post('/customers', (r) {
          n++;
          if (n == 1) return FakeResponse.error(502, 'Bad Gateway');
          return {'id': 'c9', 'code': 'M-1009', 'full_name': r.body['full_name'], 'phone': r.body['phone'], 'credit_balance': 0};
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerEditScreen());
        await tester.enterText(find.byKey(const Key('customer-name')), 'Aziz Karimov');
        await tester.enterText(find.byKey(const Key('customer-phone')), '+996 700 123 456');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('customer-unknown')), findsOneWidget,
            reason: 'a 502 can land after the customer was created');
        expect(tester.widget<TextField>(find.byKey(const Key('customer-name'))).enabled, isFalse);

        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        final calls = be.calls('POST', '/customers');
        expect(calls, hasLength(2));
        expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
      });
    });

    testWidgets('server phone conflict is shown on the phone field', (tester) async {
      final be = _backend()..post('/customers', (_) => FakeResponse.error(409, "Bu telefon do'konda allaqachon band"));
      await be.run(() async {
        await _boot(tester, be, const CustomerEditScreen());
        await tester.enterText(find.byKey(const Key('customer-name')), 'X');
        await tester.enterText(find.byKey(const Key('customer-phone')), '+996700123456');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.text('Bu telefon raqami do‘konda allaqachon band'), findsOneWidget);
        expect(find.byKey(const Key('customer-error')), findsNothing);
      });
    });

    testWidgets('edit sends only the changed field', (tester) async {
      final be = _backend()
        ..patch('/customers/{id}',
            (r) => {'id': 'c1', 'code': 'M-1001', 'full_name': 'Ali Valiyev', 'phone': r.body['phone'], 'credit_balance': 1234.56});
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await tester.tap(find.byKey(const Key('customer-edit')));
        await tester.pumpAndSettle();
        // unchanged -> disabled with a reason
        expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
        await tester.enterText(find.byKey(const Key('customer-phone')), '+996555000999');
        await tester.pump();
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(be.last('PATCH', '/customers/c1').body, {'phone': '+996555000999'});
        expect(find.byKey(const Key('customer-notice')), findsOneWidget);
      });
    });
  });

  group('debt payment', () {
    testWidgets('cash + OPERATOR_MUST_CHOOSE: no default, must choose, sends the chosen account', (tester) async {
      final be = _backend(balance: 1234.56)
        ..get('/cash/custody-preview', (_) => custodyJson('OPERATOR_MUST_CHOOSE',
            reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill, kSafe]))
        ..post('/customers/{id}/payments', (r) => {'customer_id': 'c1', 'credit_balance': 0});
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        expect(be.last('GET', '/cash/custody-preview').query, {'operation': 'debt_payment'});
        // Prefilled with the debt rounded UP to whole som (server clamps to the balance).
        expect(find.text('1 235'), findsOneWidget);
        expect(find.byIcon(Icons.radio_button_checked), findsNothing, reason: 'no preselection');

        await _confirmPay(tester);
        expect(find.byKey(const Key('custody-required')), findsOneWidget);
        expect(be.calls('POST', '/customers/c1/payments'), isEmpty);

        await tester.tap(find.byKey(const Key('custody-option-s1')));
        await tester.pumpAndSettle();
        await _confirmPay(tester);
        final body = be.last('POST', '/customers/c1/payments').body;
        expect(body['cash_account_id'], 's1');
        expect(body['method'], 'cash');
        expect(body['amount'], 1235);
        expect(body['client_uuid'], isA<String>());
        expect(find.byType(MoneyPaymentSheet), findsNothing);
        expect(find.byKey(const Key('customer-notice')), findsOneWidget);
        expect(find.textContaining('Qolgan qarz'), findsOneWidget,
            reason: 'an older server sends no paid/duplicate — report the balance the server returned');
        expect(be.calls('GET', '/customers/c1/detail').length, greaterThanOrEqualTo(2), reason: 'reloaded after a 2xx');
      });
    });

    testWidgets('gateway 502: outcome UNKNOWN too — sheet locked, same uuid on retry', (tester) async {
      var n = 0;
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('OPERATOR_MUST_CHOOSE',
            reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill, kSafe]))
        ..post('/customers/{id}/payments', (_) {
          n++;
          if (n == 1) return FakeResponse.error(502, 'Bad Gateway');
          return {'customer_id': 'c1', 'credit_balance': 0};
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await tester.tap(find.byKey(const Key('custody-option-t1')));
        await tester.pumpAndSettle();
        await _confirmPay(tester);

        expect(find.byKey(const Key('pay-unknown')), findsOneWidget,
            reason: 'a 502 can land AFTER the server committed the payment');
        expect(find.byKey(const Key('pay-error')), findsNothing, reason: 'never reported as a decided failure');
        expect(find.textContaining('nosozlik'), findsNothing, reason: 'a 502 is not a decided server failure here');
        final amount = tester.widget<TextField>(
            find.descendant(of: _inSheet(find.byKey(const Key('pay-amount'))), matching: find.byType(TextField)));
        expect(amount.enabled, isFalse, reason: 'editing the draft would mint a NEW client_uuid');

        await _confirmPay(tester);
        final calls = be.calls('POST', '/customers/c1/payments');
        expect(calls, hasLength(2));
        expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
        expect(calls[1].body['cash_account_id'], calls[0].body['cash_account_id']);
        expect(find.byType(MoneyPaymentSheet), findsNothing);
      });
    });

    testWidgets('Android back cannot abort an in-flight payment', (tester) async {
      final gate = Completer<Object?>();
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) => gate.future);
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await tester.tap(_inSheet(find.byKey(const Key('sticky-primary'))));
        await tester.pump();
        expect(be.calls('POST', '/customers/c1/payments'), hasLength(1));

        await tester.binding.handlePopRoute();
        // Ne pumpAndSettle: bu yerda virtual soat yozuv taymautidan oshib ketadi.
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 500)); // varaq chiqish animatsiyasidan uzunroq
        expect(find.byType(MoneyPaymentSheet), findsOneWidget,
            reason: 'the POST may still commit — the sheet must not vanish behind it');

        gate.complete({'customer_id': 'c1', 'credit_balance': 0});
        await tester.pumpAndSettle();
        expect(find.byType(MoneyPaymentSheet), findsNothing);
        expect(be.calls('POST', '/customers/c1/payments'), hasLength(1));
        expect(find.byKey(const Key('customer-notice')), findsOneWidget,
            reason: 'the caller learns the outcome instead of showing the pre-payment balance');
      });
    });

    testWidgets('closing after a lost answer warns the caller instead of showing the old balance', (tester) async {
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) {
          throw Exception('socket closed');
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await _confirmPay(tester);
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget);

        await tester.tap(_inSheet(find.byKey(const Key('sticky-secondary'))));
        await tester.pumpAndSettle();
        expect(find.byType(MoneyPaymentSheet), findsNothing);
        expect(find.byKey(const Key('customer-notice')), findsOneWidget);
        expect(find.textContaining('yozilgan bo‘lishi mumkin'), findsOneWidget,
            reason: 'the balance below may still be the pre-payment one');
        expect(find.textContaining('To‘lov qabul qilindi'), findsNothing);
        expect(be.calls('GET', '/customers/c1/detail').length, greaterThanOrEqualTo(2), reason: 'caller refreshed');
      });
    });

    testWidgets('replay answered with duplicate: reported as a replay, not as a new payment', (tester) async {
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) => {'customer_id': 'c1', 'credit_balance': 0, 'duplicate': true});
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await _confirmPay(tester);
        expect(find.text('Bu to‘lov avval saqlangan edi — qayta yozilmadi.'), findsOneWidget);
        expect(find.textContaining('To‘lov qabul qilindi'), findsNothing);
      });
    });

    testWidgets('server recorded less than typed (clamped): the notice names what was recorded', (tester) async {
      final be = _backend(balance: 500)
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) => {'customer_id': 'c1', 'credit_balance': 0, 'paid': 200.0});
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await _confirmPay(tester);
        expect(be.last('POST', '/customers/c1/payments').body['amount'], 500);
        final notice = find.byKey(const Key('customer-notice'));
        expect(notice, findsOneWidget);
        expect(find.descendant(of: notice, matching: find.textContaining('200')), findsOneWidget,
            reason: 'the operator took 500 in cash — the screen must show the 200 the server booked');
        expect(find.textContaining('To‘lov qabul qilindi'), findsNothing);
      });
    });

    testWidgets('BLOCKED (no open shift with force_shift): submit disabled with the reason', (tester) async {
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('BLOCKED', reason: 'OPEN_SHIFT_REQUIRED'));
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        expect(find.byKey(const Key('custody-blocked')), findsOneWidget);
        expect(_inSheet(find.byKey(const Key('sticky-reason'))), findsOneWidget);
        await _confirmPay(tester);
        expect(be.calls('POST', '/customers/c1/payments'), isEmpty);
        // Card does not touch a cash account -> allowed.
        await tester.tap(find.byKey(const Key('pay-method-card')));
        await tester.pumpAndSettle();
        await _confirmPay(tester);
        final body = be.last('POST', '/customers/c1/payments').body;
        expect(body['method'], 'card');
        expect(body.containsKey('cash_account_id'), isFalse);
      });
    });

    testWidgets('NOT_REQUIRED: nothing to choose, no account sent; amount capped', (tester) async {
      final be = _backend(balance: 1234.56)
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (r) => {'customer_id': 'c1', 'credit_balance': 734.56});
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await tester.enterText(_inSheet(find.byKey(const Key('pay-amount'))), '2000');
        await _confirmPay(tester);
        expect(find.textContaining('To‘lov qarzdan oshmasin'), findsOneWidget);
        expect(be.calls('POST', '/customers/c1/payments'), isEmpty);

        await tester.enterText(_inSheet(find.byKey(const Key('pay-amount'))), '500');
        await _confirmPay(tester);
        final body = be.last('POST', '/customers/c1/payments').body;
        expect(body, containsPair('amount', 500));
        expect(body.containsKey('cash_account_id'), isFalse);
      });
    });

    testWidgets('lost answer -> "unknown" state, retry reuses the uuid; business error is translated', (tester) async {
      var n = 0;
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('SERVER_RESOLVED', resolved: kTill))
        ..post('/customers/{id}/payments', (r) {
          n++;
          if (n == 1) throw Exception('socket closed');
          return FakeResponse.error(400, "Qarz yo'q");
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        expect(find.byKey(const Key('custody-resolved')), findsOneWidget);
        await _confirmPay(tester);
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget);
        expect(find.byType(MoneyPaymentSheet), findsOneWidget, reason: 'never shown as success');
        await _confirmPay(tester);
        final calls = be.calls('POST', '/customers/c1/payments');
        expect(calls, hasLength(2));
        expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
        expect(calls[1].body.containsKey('cash_account_id'), isFalse, reason: 'SERVER_RESOLVED sends nothing');
        expect(find.byKey(const Key('pay-error')), findsOneWidget);
        expect(find.text('Qarz yo‘q'), findsOneWidget);
      });
    });

    testWidgets('a decided refusal after an undecided attempt keeps the sheet frozen and the key', (tester) async {
      var n = 0;
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) {
          n++;
          if (n == 1) return FakeResponse.error(502, 'Bad Gateway');
          if (n == 2) return FakeResponse.error(400, "Qarz yo'q");
          return {'customer_id': 'c1', 'credit_balance': 0};
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await _confirmPay(tester);
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget);

        await _confirmPay(tester); // decided 400 — attempt 1 may still commit
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget,
            reason: 'a later refusal does not prove the earlier undecided attempt was not written');
        expect(find.byKey(const Key('pay-error')), findsOneWidget, reason: 'the refusal is still shown');
        final amount = tester.widget<TextField>(
            find.descendant(of: _inSheet(find.byKey(const Key('pay-amount'))), matching: find.byType(TextField)));
        expect(amount.enabled, isFalse, reason: 'editing would mint a NEW client_uuid');

        await _confirmPay(tester);
        final calls = be.calls('POST', '/customers/c1/payments');
        expect(calls, hasLength(3));
        expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
        expect(calls[2].body['client_uuid'], calls[0].body['client_uuid']);
      });
    });

    testWidgets('session changed mid-payment: a stale 2xx is UNKNOWN, never a decided failure', (tester) async {
      var n = 0;
      final be = _backend()
        ..get('/cash/custody-preview', (_) => custodyJson('NOT_REQUIRED'))
        ..post('/customers/{id}/payments', (_) {
          n++;
          if (n == 1) Api.authEpoch.value++; // parallel 401: ega parolni tikladi
          return {'customer_id': 'c1', 'credit_balance': 0};
        });
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        await _openPaySheet(tester);
        await _confirmPay(tester);
        expect(find.byType(MoneyPaymentSheet), findsOneWidget, reason: 'never closed as a success');
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget,
            reason: 'the server committed the 200 — the outcome is unknown, not refused');
        expect(find.byKey(const Key('pay-error')), findsNothing);

        await _confirmPay(tester);
        final calls = be.calls('POST', '/customers/c1/payments');
        expect(calls, hasLength(2));
        expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
      });
    });

    testWidgets('without mijozlar.edit the pay button is disabled with the reason', (tester) async {
      final be = _backend(role: 'kassir', perms: ['kassa.sell', 'mijozlar.view']);
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        final bar = find.byKey(const Key('customer-pay-bar'));
        expect(bar, findsOneWidget);
        expect(find.descendant(of: bar, matching: find.byKey(const Key('sticky-reason'))), findsOneWidget);
        expect(find.byKey(const Key('customer-edit')), findsNothing);
        await tester.tap(find.descendant(of: bar, matching: find.byKey(const Key('sticky-primary'))));
        await tester.pumpAndSettle();
        expect(find.byType(MoneyPaymentSheet), findsNothing);
      });
    });

    testWidgets('no debt -> no pay bar; touch targets >= 48', (tester) async {
      final be = _backend(balance: 0);
      await be.run(() async {
        await _boot(tester, be, const CustomerProfileScreen(customerId: 'c1', name: 'Ali'));
        expect(find.byKey(const Key('customer-pay-bar')), findsNothing);
        expectMinTouchTarget(tester, find.byKey(const Key('customer-edit')));
      });
    });
  });
}

/// The list's search debounce (+ a margin).
const Duration kSearchDebounce = Duration(milliseconds: 400);
