// M4 cash operations: hisobot.view gating, "no open shift" made explicit,
// collection requires a SAFE chosen from the server's list
// (`destination_safe_id`), outflows confirmed, idempotent retry.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/cash_ops_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

FakeBackend _backend({
  String role = 'ega',
  List<String> perms = const [],
  Map<String, dynamic>? custody,
  List<Map<String, dynamic>>? branches,
}) {
  final be = FakeBackend()
    ..get('/auth/context', (_) => contextJson(role: role, permissions: perms, branches: branches))
    ..get('/cash/custody-preview', (_) => custody ?? custodyJson('OPERATOR_MUST_CHOOSE',
        reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kSafe, kSafe2]))
    ..get('/cash/ops', (_) => [
          {'type': 'expense', 'amount': 20000.0, 'reason': 'Ijara · iyun', 'employee': 'Ega', 'at': '2026-09-19T05:00:00'},
        ])
    ..post('/cash/ops', (_) => {'ok': true, 'shift_id': 'sh1'});
  signIn(role: role, permissions: perms);
  return be;
}

Future<void> _boot(WidgetTester tester) async {
  await Session.instance.load(force: true);
  await pumpAt390(tester, const CashOpsScreen());
  await tester.pumpAndSettle();
}

Future<void> _save(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('sticky-primary')));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() async => resetCore());

  testWidgets('without hisobot.view: no access and no request', (tester) async {
    final be = _backend(role: 'omborchi', perms: ['ombor.edit', 'xaridlar.edit']);
    await be.run(() async {
      await _boot(tester);
      expect(find.byKey(const Key('no-access')), findsOneWidget);
      expect(be.calls('GET', '/cash/custody-preview'), isEmpty);
      expect(be.calls('GET', '/cash/ops'), isEmpty);
    });
  });

  testWidgets('no open shift: explicit banner, save disabled with the reason, nothing posted', (tester) async {
    final be = _backend(custody: custodyJson('BLOCKED', reason: 'OPEN_SHIFT_REQUIRED'));
    await be.run(() async {
      await _boot(tester);
      expect(be.last('GET', '/cash/custody-preview').query, {'operation': 'collection_destination'});
      expect(find.byKey(const Key('cash-no-shift')), findsOneWidget);
      expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
      await tester.tap(find.byKey(const Key('cash-type-payin')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cash-amount')), '1000');
      await _save(tester);
      expect(be.calls('POST', '/cash/ops'), isEmpty);
    });
  });

  testWidgets('payin: no confirmation, no destination, success notice, history reloaded', (tester) async {
    final be = _backend();
    await be.run(() async {
      await _boot(tester);
      expect(find.byKey(const Key('cash-shift')), findsOneWidget);
      expect(find.textContaining('Markaz'), findsWidgets);
      await tester.tap(find.byKey(const Key('cash-type-payin')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cash-amount')), '150000');
      await _save(tester);
      final body = be.last('POST', '/cash/ops').body;
      expect(body['type'], 'payin');
      expect(body['amount'], 150000);
      expect(body.containsKey('destination_safe_id'), isFalse);
      expect(body['client_uuid'], isA<String>());
      expect(find.byKey(const Key('cash-notice')), findsOneWidget);
      expect(be.calls('GET', '/cash/ops').length, greaterThanOrEqualTo(2));
    });
  });

  testWidgets('expense: confirmed first; category stored as data; duplicate said explicitly', (tester) async {
    final be = _backend()..post('/cash/ops', (_) => {'ok': true, 'shift_id': 'sh1', 'duplicate': true});
    await be.run(() async {
      await _boot(tester);
      await tester.tap(find.byKey(const Key('cash-cat-Kommunal')));
      await tester.enterText(find.byKey(const Key('cash-amount')), '2500');
      await _save(tester);
      expect(find.byKey(const Key('confirm-yes')), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm-no')));
      await tester.pumpAndSettle();
      expect(be.calls('POST', '/cash/ops'), isEmpty, reason: 'cancelled confirmation writes nothing');

      await _save(tester);
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      final body = be.last('POST', '/cash/ops').body;
      expect(body['type'], 'expense');
      expect(body['reason'], 'Kommunal');
      expect(find.text('Bu amal avval saqlangan edi — qayta yozilmadi.'), findsOneWidget);
    });
  });

  testWidgets('collection: SAFE must be chosen (no default) and is sent as destination_safe_id', (tester) async {
    final be = _backend();
    await be.run(() async {
      await _boot(tester);
      await tester.tap(find.byKey(const Key('cash-type-collection')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cash-safe-block')), findsOneWidget);
      expect(find.byIcon(Icons.radio_button_checked), findsNothing);
      await tester.enterText(find.byKey(const Key('cash-amount')), '500000');
      await _save(tester);
      expect(find.byKey(const Key('custody-required')), findsOneWidget);
      expect(find.byKey(const Key('confirm-yes')), findsNothing);

      await tester.tap(find.byKey(const Key('custody-option-s2')));
      await tester.pumpAndSettle();
      await _save(tester);
      expect(find.textContaining('S-02'), findsWidgets, reason: 'the confirmation names the safe');
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      final body = be.last('POST', '/cash/ops').body;
      expect(body['type'], 'collection');
      expect(body['destination_safe_id'], 's2');
      expect(body['amount'], 500000);
    });
  });

  testWidgets('collection without a cash subsystem (NOT_REQUIRED): no destination needed', (tester) async {
    final be = _backend(custody: custodyJson('NOT_REQUIRED'));
    await be.run(() async {
      await _boot(tester);
      await tester.tap(find.byKey(const Key('cash-type-collection')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cash-amount')), '1000');
      await _save(tester);
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      final body = be.last('POST', '/cash/ops').body;
      expect(body.containsKey('destination_safe_id'), isFalse);
    });
  });

  testWidgets('lost answer: unknown state, inputs locked, retry reuses the uuid', (tester) async {
    var n = 0;
    final be = _backend()
      ..post('/cash/ops', (_) {
        n++;
        if (n == 1) throw Exception('reset');
        return {'ok': true, 'shift_id': 'sh1'};
      });
    await be.run(() async {
      await _boot(tester);
      await tester.tap(find.byKey(const Key('cash-type-payin')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cash-amount')), '7000');
      await _save(tester);
      expect(find.byKey(const Key('cash-unknown')), findsOneWidget);
      expect(find.byKey(const Key('cash-notice')), findsNothing, reason: 'never shown as success');
      final amount = tester.widget<TextField>(
          find.descendant(of: find.byKey(const Key('cash-amount')), matching: find.byType(TextField)));
      expect(amount.enabled, isFalse);
      await _save(tester);
      final calls = be.calls('POST', '/cash/ops');
      expect(calls, hasLength(2));
      expect(calls[1].body['client_uuid'], calls[0].body['client_uuid']);
      expect(find.byKey(const Key('cash-notice')), findsOneWidget);
    });
  });

  testWidgets('shift closed meanwhile: translated error and the shift state is re-read', (tester) async {
    L.code = 'ky';
    final be = _backend()
      ..post('/cash/ops', (_) => FakeResponse.error(400, "Ochiq smena yo'q — avval kassada smena oching",
          code: 'OPEN_SHIFT_REQUIRED'));
    await be.run(() async {
      await _boot(tester);
      await tester.tap(find.byKey(const Key('cash-type-payin')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cash-amount')), '100');
      await _save(tester);
      expect(find.byKey(const Key('cash-error')), findsOneWidget);
      expect(find.textContaining("smena yo'q"), findsNothing);
      expect(be.calls('GET', '/cash/custody-preview'), hasLength(2));
    });
  });

  testWidgets('viewing another branch: the screen says where the cash is written', (tester) async {
    final be = _backend(branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Bozor')]);
    await be.run(() async {
      await Session.instance.load(force: true);
      await Session.instance.selectBranch('b2');
      await pumpAt390(tester, const CashOpsScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cash-branch-warning')), findsOneWidget);
      expect(find.textContaining('Bozor'), findsWidgets);
      expectMinTouchTarget(tester, find.byKey(const Key('cash-type-payin')));
      expectMinTouchTarget(tester, find.byKey(const Key('cash-cat-Ijara')));
    });
  });
}
