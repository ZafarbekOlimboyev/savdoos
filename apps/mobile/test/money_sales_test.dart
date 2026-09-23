// M4 sales: gating, branch/period/search queries, detail and the server
// receipt (ReceiptDTO) view + text share. No returns, no printing on mobile.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/money_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/receipt_screen.dart';
import 'package:savdoos_mobile/screens/sales_detail_screen.dart';
import 'package:savdoos_mobile/screens/sales_list_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

FakeBackend _backend({String role = 'ega', List<String> perms = const [], List<Map<String, dynamic>>? branches}) {
  final be = FakeBackend()
    ..get('/auth/context', (_) => contextJson(role: role, permissions: perms, branches: branches))
    ..get('/sales', (r) => [saleRowJson(), saleRowJson(id: 'x2', no: '#1043')])
    ..get('/sales/{id}/receipt', (r) => saleReceiptJson());
  signIn(role: role, permissions: perms);
  return be;
}

Future<void> _boot(WidgetTester tester, Widget screen) async {
  await Session.instance.load(force: true);
  await pumpAt390(tester, screen);
  await tester.pumpAndSettle();
}

/// Captures shares instead of calling the platform.
final List<String> _shared = [];

void main() {
  setUp(() async {
    await resetCore();
    _shared.clear();
    receiptShare = (text, {subject}) async => _shared.add(text);
  });

  group('sales list', () {
    testWidgets('omborchi (no sotuvlar.view): no access, no request', (tester) async {
      final be = _backend(role: 'omborchi', perms: ['ombor.edit']);
      await be.run(() async {
        await _boot(tester, const SalesListScreen());
        expect(find.byKey(const Key('no-access')), findsOneWidget);
        expect(be.calls('GET', '/sales'), isEmpty);
      });
    });

    testWidgets('current branch + today by default; period chips; receipt search; open detail', (tester) async {
      final be = _backend(role: 'menejer', perms: ['sotuvlar.view', 'hisobot.view']);
      await be.run(() async {
        await _boot(tester, const SalesListScreen());
        expect(be.last('GET', '/sales').query, {'limit': '100', 'period': 'today', 'branch_id': 'b1'});
        expect(find.byKey(const Key('branch-chip')), findsOneWidget);
        expect(find.text('2 ta chek'), findsOneWidget);

        await tester.tap(find.byKey(const Key('period-week')));
        await tester.pumpAndSettle();
        expect(be.last('GET', '/sales').query['period'], 'week');

        await tester.enterText(find.byKey(const Key('sales-search')), '1043');
        await tester.pump(const Duration(milliseconds: 400));
        await tester.pumpAndSettle();
        expect(be.last('GET', '/sales').query, {'limit': '100', 'q': '1043', 'branch_id': 'b1'},
            reason: 'a receipt search spans all periods');

        await tester.tap(find.byKey(const Key('sale-x2')));
        await tester.pumpAndSettle();
        expect(find.byType(SalesDetailScreen), findsOneWidget);
        expect(be.last('GET', '/sales/x2/receipt'), isNotNull);
      });
    });

    testWidgets('switching the branch reloads with the new branch only', (tester) async {
      final be = _backend(branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Bozor')]);
      await be.run(() async {
        await _boot(tester, const SalesListScreen());
        expect(be.last('GET', '/sales').query['branch_id'], 'b1');
        await tester.tap(find.byKey(const Key('branch-chip')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('branch-option-b2')));
        await tester.pumpAndSettle();
        expect(be.last('GET', '/sales').query['branch_id'], 'b2');
      });
    });

    testWidgets('branch B never shows branch A receipts — not while loading, not after a failed reload',
        (tester) async {
      final gate = Completer<Object?>();
      final be = _backend(branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Bozor')])
        ..get('/sales', (r) async {
          if (r.query['branch_id'] == 'b2') return gate.future;
          return [saleRowJson(), saleRowJson(id: 'x2', no: '#1043')];
        });
      await be.run(() async {
        await _boot(tester, const SalesListScreen());
        expect(find.byKey(const Key('sale-x1')), findsOneWidget);

        await tester.tap(find.byKey(const Key('branch-chip')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('branch-option-b2')));
        await tester.pumpAndSettle();
        expect(be.last('GET', '/sales').query['branch_id'], 'b2');
        expect(find.byKey(const Key('sale-x1')), findsNothing,
            reason: "the old branch's receipts must go the moment the branch changes");
        expect(find.byKey(const Key('sales-count')), findsNothing);

        gate.complete(FakeResponse.error(500, 'boom'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('sale-x1')), findsNothing,
            reason: 'a failed branch-B reload must not leave Markaz takings under the Bozor chip');
        expect(find.byKey(const Key('sale-x2')), findsNothing);
        expect(find.byKey(const Key('sales-count')), findsNothing);
      });
    });

    testWidgets('legacy saleTile (analytics card) still renders', (tester) async {
      await pumpAt390(
          tester,
          Scaffold(
            body: saleTile(SaleRow(
                id: 'x', receiptNo: '#1', cashier: 'K', method: 'card', firstItem: 'Non', at: null, itemCount: 2, total: 1500)),
          ));
      expect(find.text('Non'), findsOneWidget);
      expect(find.text('Karta'), findsOneWidget);
    });
  });

  group('sale detail', () {
    testWidgets('built from the server receipt: branch, till, lines, totals, payment split; no return button',
        (tester) async {
      final be = _backend(role: 'menejer', perms: ['sotuvlar.view']);
      await be.run(() async {
        await _boot(tester, const SalesDetailScreen(saleId: 'x1', receiptNo: '#1042'));
        expect(find.text('Markaz'), findsOneWidget);
        expect(find.text('K-01'), findsOneWidget);
        expect(find.text('Kassir 1'), findsOneWidget);
        expect(find.text('Olma'), findsOneWidget);
        expect(find.textContaining('0,352 kg'), findsOneWidget, reason: 'weighed qty keeps 3 decimals');
        await tester.ensureVisible(find.byKey(const Key('sale-payments')));
        await tester.pumpAndSettle();
        expect(find.text('+568'), findsOneWidget, reason: 'rounding shown signed, from the server');
        expect(find.textContaining('42 240'), findsWidgets);
        expect(find.text('Qaytim'), findsOneWidget);
        expect(find.textContaining('Qaytarish'), findsNothing);
        expect(find.textContaining('tez orada'), findsNothing);

        await tester.tap(find.byKey(const Key('sale-share')));
        await tester.pumpAndSettle();
        expect(_shared.single, contains('#1042'));

        await tester.tap(find.descendant(of: find.byKey(const Key('sale-receipt-bar')), matching: find.byKey(const Key('sticky-primary'))));
        await tester.pumpAndSettle();
        expect(find.byType(ReceiptScreen), findsOneWidget);
        expect(be.calls('GET', '/sales/x1/receipt'), hasLength(1), reason: 'the receipt screen reuses the loaded DTO');
      });
    });

    testWidgets('voided sale is flagged', (tester) async {
      final be = _backend()..get('/sales/{id}/receipt', (_) => saleReceiptJson(status: 'voided'));
      await be.run(() async {
        await _boot(tester, const SalesDetailScreen(saleId: 'x1'));
        expect(find.byKey(const Key('sale-status')), findsOneWidget);
        expect(find.textContaining('Bekor qilingan'), findsOneWidget);
      });
    });

    testWidgets('older server without the receipt route: explicit message, no silent fallback', (tester) async {
      final be = _backend()..get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Not Found'));
      await be.run(() async {
        await _boot(tester, const SalesDetailScreen(saleId: 'x1'));
        expect(find.textContaining('server yangilanishi kerak'), findsOneWidget);
        expect(be.calls('GET', '/sales/x1'), isEmpty);
      });
    });
  });

  group('receipt', () {
    testWidgets('paper view: header, store, meta, lines, discounts, totals, payments, footer; share text',
        (tester) async {
      final be = _backend();
      await be.run(() async {
        await _boot(tester, const ReceiptScreen(saleId: 'x1'));
        final paper = find.byKey(const Key('receipt-paper'));
        expect(find.descendant(of: paper, matching: find.text('Xush kelibsiz')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Fayzan')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Filial: Markaz')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('STIR: 123456789')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Chek #1042')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('19.09.2026 10:30')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Kassa: K-01')), findsOneWidget, reason: 'show_till');
        expect(find.descendant(of: paper, matching: find.text('2 dona × 15 000')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('30 000')), findsOneWidget, reason: 'gross when the discount line shows');
        expect(find.descendant(of: paper, matching: find.text('-1 000')), findsWidgets);
        expect(find.descendant(of: paper, matching: find.text('0,352 kg × 36 000')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Yaxlitlash')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.textContaining('42 240')), findsOneWidget);
        expect(find.descendant(of: paper, matching: find.text('Xaridingiz uchun rahmat!')), findsOneWidget);
        expect(find.byIcon(Icons.print), findsNothing);

        await tester.tap(find.byKey(const Key('receipt-share')));
        await tester.pumpAndSettle();
        final text = _shared.single;
        expect(text, contains('Chek #1042'));
        expect(text, contains('JAMI'));
        expect(text, contains('Qaytim'));
        expect(text, isNot(contains('null')));
      });
    });

    testWidgets('RETURN receipt: minus signs, refund line, original receipt; ru labels', (tester) async {
      L.code = 'ru';
      await pumpAt390(tester, ReceiptScreen(receipt: Receipt.fromJson(returnReceiptJson())));
      await tester.pumpAndSettle();
      final paper = find.byKey(const Key('receipt-paper'));
      expect(find.descendant(of: paper, matching: find.text('ЧЕК ВОЗВРАТА')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.text('Исходный чек: #1042')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.text('-14 500')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.textContaining('ИТОГО ВОЗВРАТ')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.textContaining('-14 500 сом')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.text('Возвращено (Наличные)')), findsOneWidget);
      expect(find.descendant(of: paper, matching: find.text('Rahmat')), findsOneWidget, reason: 'template footer');
    });

    test('plain text keeps the server amounts, hides the discount when the template says so', () {
      final r = Receipt.fromJson(saleReceiptJson(showDiscount: false));
      final t = receiptPlainText(r);
      expect(t, isNot(contains('Chegirma')));
      expect(t, contains('29 000'), reason: 'net line total when discounts are hidden');
      expect(t, contains('Oraliq jami'));
      expect(t, contains('41 672'), reason: 'subtotal net of hidden line discounts (desktop renderer rule)');
      for (final line in t.split('\n')) {
        expect(line.length, lessThanOrEqualTo(40), reason: line);
      }
    });

    test('ApiException on a failed load (no fallback)', () async {
      signIn();
      final be = FakeBackend()..get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Chek topilmadi'));
      await expectLater(be.run(() => MoneyApi.saleReceipt('x')), throwsA(isA<ApiException>()));
    });
  });
}
