// M3 — a resend is a REPLAY only when the previous attempt's outcome was
// UNKNOWN (lost answer / timeout / 5xx). A DECIDED business rejection (4xx)
// wrote nothing, so the next submit is a NEW request: the client checks and
// the cash custody gate run again instead of looping on the same 400 while
// the operator is told the correction was already written.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

const _editor = ['xaridlar.view', 'xaridlar.edit'];

Finder _inBar(String barKey, String key) =>
    find.descendant(of: find.byKey(Key(barKey)), matching: find.byKey(Key(key)));

Future<void> _openEditor(WidgetTester tester) async {
  await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
  await tester.pumpAndSettle();
  await tester.tap(_inBar('pd-bar', 'sticky-primary'));
  await tester.pumpAndSettle();
  expect(find.byType(CorrectionScreen), findsOneWidget);
}

Future<void> _confirm(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('confirm-ack')));
  await tester.pump();
  await tester.tap(find.byKey(const Key('confirm-yes')));
  await tester.pumpAndSettle();
}

String? _barReason(WidgetTester tester) {
  final f = _inBar('corr-bar', 'sticky-reason');
  return f.evaluate().isEmpty ? null : tester.widget<Text>(f).data;
}

bool _submitEnabled(WidgetTester tester) =>
    tester.widget<ElevatedButton>(_inBar('corr-bar', 'sticky-primary')).onPressed != null;

void main() {
  setUp(() async {
    await resetCore();
    PendingCorrectionKeys.clear();
  });

  testWidgets('a DECIDED 400 re-opens the cash gate: the unchanged draft is not a replay', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    var shiftClosed = false;
    final be = FakeBackend()
      ..get(
          '/purchases/{id}',
          (r) => purchaseJson(
                custody: shiftClosed
                    ? custodyJson('OPERATOR_MUST_CHOOSE', options: const [kTill, kSafe])
                    : custodyJson('SERVER_RESOLVED', resolved: kTill),
              ))
      ..post('/receiving/{rid}/corrections', (r) {
        // The cashier closed the POS shift while the request was in flight.
        shiftClosed = true;
        return FakeResponse.error(400,
            'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: Pul qaysi kassa yoki seyf orqali o‘tishini tanlang');
      });
    await be.run(() async {
      await _openEditor(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
      await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
      await tester.pumpAndSettle();
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      await _confirm(tester);

      expect(find.byType(CorrectionScreen), findsOneWidget);
      expect(find.byKey(const Key('corr-error')), findsOneWidget);
      expect(find.textContaining('Natija noma’lum'), findsNothing, reason: 'a 400 is a decided answer');
      // The reload brought OPERATOR_MUST_CHOOSE: the gate must be visible and
      // closed, and the button must not re-send the same rejected body.
      expect(_barReason(tester), 'Pul qaysi kassa yoki seyf orqali o‘tishini tanlang — server buni taxmin qilmaydi');
      expect(_submitEnabled(tester), isFalse);
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      expect(be.calls('POST', '/receiving/r1/corrections'), hasLength(1),
          reason: 'nothing is sent until an account is chosen');
    });
  });

  testWidgets('an UNKNOWN outcome still allows the identical resend as a replay', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    final replies = <FakeResponse>[FakeResponse.error(504, 'Gateway Timeout')];
    final be = FakeBackend()
      ..get('/purchases/{id}', (r) => purchaseJson(custody: custodyJson('OPERATOR_MUST_CHOOSE', options: const [kTill])))
      ..post('/receiving/{rid}/corrections', (r) {
        if (replies.isNotEmpty) return replies.removeAt(0);
        return {
          'ok': true,
          'correction_id': 'c-new',
          'receiving_id': 'r1',
          'purchase_id': 'p1',
          'reversed_total': 10000.0,
          'replaced_total': 0.0,
          'delta_total': -10000.0,
          'purchase_status': 'received',
          'cancelled': false,
          'duplicate': true,
        };
      });
    await be.run(() async {
      await _openEditor(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
      await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.byKey(const Key('custody-option-t1')), 250,
          scrollable:
              find.descendant(of: find.byKey(const Key('corr-list')), matching: find.byType(Scrollable)).first);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('custody-option-t1')));
      await tester.pumpAndSettle();
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      await _confirm(tester);
      expect(find.textContaining('Natija noma’lum'), findsOneWidget);
      expect(_submitEnabled(tester), isTrue);
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      await _confirm(tester);
      final posts = be.calls('POST', '/receiving/r1/corrections');
      expect(posts, hasLength(2));
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
      expect(find.byType(CorrectionScreen), findsNothing);
    });
  });

  // The ONE key that survives the screen is `PendingCorrectionKeys`: the
  // correction editor is torn down for real when the session ends
  // (`onSessionExpired` -> pushAndRemoveUntil(LoginScreen)), which happened in
  // Fayzan production on 2026-09-17 when the owner reset an employee password
  // while that employee was working. A write that was authenticated BEFORE the
  // revocation still commits and answers 2xx; the core discards that answer as
  // `SESSION_CHANGED`. Treating it as a refusal — and deleting the key — makes
  // the manager re-enter the correction and write a SECOND immutable one.
  testWidgets('a 2xx discarded as a stale session keeps the pending key, even after the screen is gone',
      (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    final gate = Completer<Object?>();
    final be = FakeBackend()
      ..get('/purchases/{id}', (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)))
      ..post('/receiving/{rid}/corrections', (r) => gate.future);
    await be.run(() async {
      await _openEditor(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
      await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
      await tester.pumpAndSettle();
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-ack')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      // NE pumpAndSettle: so'rov yo'lda qolishi kerak.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(be.calls('POST', '/receiving/r1/corrections'), hasLength(1));

      // Boshqa so'rov 401 qaytardi: yadro sessiyani tozalaydi (epoch oshadi) va
      // UI login ekraniga o'tadi — tuzatish ekrani BUTUNLAY yo'q qilinadi.
      Api.authEpoch.value++;
      // Butun daraxt yo‘q qilinadi (LoginScreen ga pushAndRemoveUntil kabi).
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(find.byType(CorrectionScreen), findsNothing);

      // Server tuzatishni YOZDI va 200 qaytardi — yadro uni eskirgan deb rad etadi.
      gate.complete({
        'ok': true,
        'correction_id': 'c-new',
        'receiving_id': 'r1',
        'purchase_id': 'p1',
        'reversed_total': 10000.0,
        'replaced_total': 0.0,
        'delta_total': -10000.0,
        'purchase_status': 'received',
        'cancelled': false,
      });
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    });
    expect(PendingCorrectionKeys.of('p1'), be.last('POST', '/receiving/r1/corrections').body['client_uuid'],
        reason: 'the key must outlive the screen: re-entering the correction under a NEW key writes it twice');
  });

  // Kalit so'rov KETISHIDAN OLDIN eslab qolinadi: ekran javob kelgunча yo'q
  // qilinsa, `catch` hech qachon ishlamaydi va kalitni yozib qo'yadigan
  // birorta joy qolmaydi.
  testWidgets('the pending key is recorded BEFORE the request leaves', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    final gate = Completer<Object?>();
    final be = FakeBackend()
      ..get('/purchases/{id}', (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)))
      ..post('/receiving/{rid}/corrections', (r) => gate.future);
    await be.run(() async {
      await _openEditor(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
      await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
      await tester.pumpAndSettle();
      await tester.tap(_inBar('corr-bar', 'sticky-primary'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-ack')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(PendingCorrectionKeys.of('p1'), be.last('POST', '/receiving/r1/corrections').body['client_uuid'],
          reason: 'while the answer is out the outcome is unknown by definition');

      gate.complete(FakeResponse.error(400, 'Sabab (izoh) majburiy'));
      await tester.pumpAndSettle();
      expect(PendingCorrectionKeys.of('p1'), isNull, reason: 'a DECIDED 4xx wrote nothing — the key is spent');
    });
  });
}
