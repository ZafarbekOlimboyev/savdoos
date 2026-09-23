// M3 — widget tests on a 390×844 phone against the FakeBackend:
// purchase document view, permission gating, the correction editor, cash
// custody per mode, full cancel, idempotent retry after a lost answer,
// replay conflict, duplicate reply, replacement with expiry, localisation.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

const _editor = ['xaridlar.view', 'xaridlar.edit'];

Map<String, dynamic> _result({num delta = -20000, bool cancelled = false, bool duplicate = false}) => {
      'ok': true,
      'correction_id': 'c-new',
      'receiving_id': 'r1',
      'purchase_id': 'p1',
      'reversed_total': (-delta).toDouble(),
      'replaced_total': 0.0,
      'delta_total': delta.toDouble(),
      'purchase_status': cancelled ? 'cancelled' : 'received',
      'cancelled': cancelled,
      'duplicate': duplicate,
    };

Finder _inBar(String barKey, String key) =>
    find.descendant(of: find.byKey(Key(barKey)), matching: find.byKey(Key(key)));

Future<void> _scrollTo(WidgetTester tester, Finder f, {String list = 'corr-list'}) async {
  await tester.scrollUntilVisible(f, 250,
      scrollable: find.descendant(of: find.byKey(Key(list)), matching: find.byType(Scrollable)).first);
  await tester.pumpAndSettle();
}

/// Opens the purchase detail, then the correction editor.
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

  group('purchase document screen', () {
    testWidgets('shows the document, lots once, history and the correct action (xaridlar.edit)', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson(corrections: [
              {'id': 'c1', 'at': '2026-09-19T08:30:00', 'reason': 'Nakladnoy xato', 'delta_total': -20000.0, 'employee': 'Ali'}
            ]));
      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        expect(find.text('KR-0042'), findsOneWidget);
        expect(find.byKey(const Key('pd-supplier')), findsOneWidget);
        expect(find.text('Oq Sut MChJ'), findsOneWidget);
        expect(tester.widget<Text>(find.byKey(const Key('pd-total'))).data, contains('150'));
        expect(find.byKey(const Key('pd-branch')), findsOneWidget);
        expect(find.byKey(const Key('pd-lot-L1')), findsOneWidget);
        expect(find.byKey(const Key('pd-lot-L2')), findsOneWidget);
        await tester.scrollUntilVisible(find.byKey(const Key('pd-corr-c1')), 250,
            scrollable: find.descendant(of: find.byKey(const Key('pd-list')), matching: find.byType(Scrollable)).first);
        expect(find.text('Nakladnoy xato'), findsOneWidget);
        expect(find.textContaining('−20'), findsOneWidget);
        final btn = _inBar('pd-bar', 'sticky-primary');
        expect(tester.widget<ElevatedButton>(btn).onPressed, isNotNull);
        expectMinTouchTarget(tester, btn);
        expect(be.calls('GET', '/purchases/p1'), hasLength(1));
      });
    });

    testWidgets('view-only (xaridlar.view): no correction action', (tester) async {
      signIn(role: 'omborchi', permissions: ['xaridlar.view']);
      final be = FakeBackend()..get('/purchases/{id}', (r) => purchaseJson());
      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        expect(find.text('KR-0042'), findsOneWidget);
        expect(find.byKey(const Key('pd-bar')), findsNothing);
      });
    });

    testWidgets('without xaridlar.view: explained, nothing requested', (tester) async {
      signIn(role: 'kassir', permissions: ['kassa.sell']);
      final be = FakeBackend()..get('/purchases/{id}', (r) => purchaseJson());
      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Xaridlarni ko‘rish'), findsOneWidget);
        expect(be.log, isEmpty);
      });
    });

    testWidgets('a blocked document: action disabled with the translated server reason (ru)', (tester) async {
      L.code = 'ru';
      signIn(role: 'administrator');
      final be = FakeBackend()
        ..get('/purchases/{id}',
            (r) => purchaseJson(correctable: false, blockedReason: "Xarid filiali o'chirilgan — tuzatib bo'lmaydi."));
      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        expect(tester.widget<ElevatedButton>(_inBar('pd-bar', 'sticky-primary')).onPressed, isNull);
        expect(find.text('Филиал закупки удалён — исправить нельзя'), findsOneWidget);
        expect(find.text('Исправить или отменить'), findsOneWidget);
      });
    });

    testWidgets('a 404 (cancelled / other branch) is an explained error with retry', (tester) async {
      signIn(role: 'ega');
      final be = FakeBackend()..get('/purchases/{id}', (r) => FakeResponse.error(404, 'Kirim topilmadi'));
      await be.run(() async {
        await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
        await tester.pumpAndSettle();
        expect(find.text('Kirim topilmadi'), findsOneWidget);
        expect(find.text('Qayta urinish'), findsOneWidget);
      });
    });
  });

  group('correction editor', () {
    testWidgets('reverse a quantity: exact body, confirm, back on the document with a notice', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      var current = purchaseJson();
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => current)
        ..post('/receiving/{rid}/corrections', (r) {
          current = purchaseJson(total: 130000, corrections: [
            {'id': 'c-new', 'at': '2026-09-19T09:00:00', 'reason': 'Nakladnoyda 4 ta', 'delta_total': -20000.0, 'employee': 'Test'}
          ]);
          return _result();
        });
      await be.run(() async {
        await _openEditor(tester);
        // Nothing typed: the reason is required.
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('corr-check')), findsOneWidget);
        expect(be.calls('POST', '/receiving/r1/corrections'), isEmpty);

        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoyda 4 ta');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('corr-check')), findsNothing, reason: 'the banner follows the current draft');
        expect(tester.widget<Text>(find.byKey(const Key('corr-sum-reversed'))).data, contains('20'));
        expect(find.byKey(const Key('corr-line-0-rev')), findsOneWidget);
        await _scrollTo(tester, find.byKey(const Key('corr-money-line')));
        expect(find.byKey(const Key('corr-cash')), findsNothing, reason: 'NOT_REQUIRED: nothing to choose');
        expect(tester.widget<Text>(find.byKey(const Key('corr-money-line'))).data, startsWith('Kassaga qaytadi: 20'));

        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.text('Tuzatish yozilsinmi?'), findsOneWidget);
        await _confirm(tester);

        final post = be.last('POST', '/receiving/r1/corrections').body;
        expect(post.keys.toSet(), {'client_uuid', 'reason', 'lines'});
        expect(post['reason'], 'Nakladnoyda 4 ta');
        expect(post['lines'], [
          {
            'purchase_item_id': 'i1',
            'reverse': [
              {'stock_batch_id': 'L1', 'qty': 2}
            ]
          }
        ]);
        expect(find.byType(CorrectionScreen), findsNothing);
        expect(find.byKey(const Key('pd-notice')), findsOneWidget);
        expect(find.textContaining('Tuzatish yozildi'), findsOneWidget);
        expect(be.calls('GET', '/purchases/p1'), hasLength(2), reason: 'reloaded after the write');
      });
    });

    testWidgets('over the remaining quantity: inline error, focus, nothing sent', (tester) async {
      signIn(role: 'ega');
      final be = FakeBackend()..get('/purchases/{id}', (r) => purchaseJson());
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await _scrollTo(tester, find.byKey(const Key('corr-rev-L2')));
        await tester.enterText(find.byKey(const Key('corr-rev-L2')), '2');
        await tester.pumpAndSettle();
        expect(find.textContaining('Qoldiqdan ko‘p'), findsOneWidget);
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.textContaining('partiya qoldig‘idan katta'), findsWidgets);
        expect(be.calls('POST', '/receiving/r1/corrections'), isEmpty);
        // The moved lot is flagged, and a replacement cannot be switched on for it.
        expect(find.byKey(const Key('corr-lot-L2-touched')), findsOneWidget);
        await tester.enterText(find.byKey(const Key('corr-rev-L2')), '1');
        await tester.pumpAndSettle();
        await _scrollTo(tester, find.byKey(const Key('corr-replace-0')));
        expect(find.byKey(const Key('corr-line-0-rep-locked')), findsOneWidget);
        await tester.tap(find.byKey(const Key('corr-replace-0')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('corr-rep-qty-0')), findsNothing);
      });
    });

    testWidgets('OPERATOR_MUST_CHOOSE: submit closed until an exact option is tapped; chosen id is sent', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}',
            (r) => purchaseJson(custody: custodyJson('OPERATOR_MUST_CHOOSE',
                reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill, kSafe])))
        ..post('/receiving/{rid}/corrections', (r) => _result());
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        expect(_submitEnabled(tester), isFalse);
        expect(_barReason(tester), contains('kassa yoki seyf'));
        await _scrollTo(tester, find.byKey(const Key('custody-option-s1')));
        expect(find.byKey(const Key('custody-option-t1')), findsOneWidget);
        await tester.tap(find.byKey(const Key('custody-option-s1')));
        await tester.pumpAndSettle();
        expect(_submitEnabled(tester), isTrue);
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Hisob: S-01'), findsOneWidget);
        await _confirm(tester);
        expect(be.last('POST', '/receiving/r1/corrections').body['cash_account_id'], 's1');
      });
    });

    testWidgets('SERVER_RESOLVED: read-only till, no cash_account_id sent', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)))
        ..post('/receiving/{rid}/corrections', (r) => _result());
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
        await tester.pumpAndSettle();
        await _scrollTo(tester, find.byKey(const Key('custody-resolved')));
        expect(find.text('Pul manbai: K-01 (Kassa)'), findsOneWidget);
        expect(_submitEnabled(tester), isTrue);
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        expect(be.last('POST', '/receiving/r1/corrections').body.containsKey('cash_account_id'), isFalse);
      });
    });

    testWidgets('BLOCKED: a money-moving draft is closed with the reason; an identity-only one is allowed', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}',
            (r) => purchaseJson(custody: custodyJson('BLOCKED', reason: 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER')))
        ..post('/receiving/{rid}/corrections', (r) => _result(delta: 0));
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Partiya raqami xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        expect(_submitEnabled(tester), isFalse);
        expect(_barReason(tester), contains('pulni siljitadi'));
        expect(_barReason(tester), contains('ochiq smena kassasiga mos emas'));
        // Same quantity back as a new lot at the same cost: no money moves.
        await _scrollTo(tester, find.byKey(const Key('corr-replace-0')));
        await tester.tap(find.byKey(const Key('corr-replace-0')));
        await tester.pumpAndSettle();
        await _scrollTo(tester, find.byKey(const Key('corr-rep-cost-0')));
        await tester.enterText(find.byKey(const Key('corr-rep-cost-0')), '10000');
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('corr-cash')), findsNothing);
        expect(_submitEnabled(tester), isTrue);
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        final line = (be.last('POST', '/receiving/r1/corrections').body['lines'] as List).single as Map;
        expect(line['replace'], [
          {'qty': 2}
        ]);
        expect(line['unit_cost'], 10000);
      });
    });

    testWidgets('full cancel: reverse everything, cancel label, document route pops true', (tester) async {
      signIn(role: 'ega');
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => freshPurchaseJson())
        ..post('/receiving/{rid}/corrections', (r) => _result(delta: -70001, cancelled: true));
      bool? changed;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async => changed = await PurchaseDetailScreen.open(ctx, 'p1')));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(_inBar('pd-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Tovar qaytarib yuborildi');
        await tester.tap(find.byKey(const Key('corr-reverse-all')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('corr-full-cancel')), findsOneWidget);
        expect(find.descendant(of: find.byKey(const Key('corr-bar')), matching: find.text('Hujjatni bekor qilish')),
            findsOneWidget);
        expect(tester.widget<Text>(find.byKey(const Key('corr-sum-total'))).data, startsWith('0'));
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.text('Hujjat BEKOR qilinadi'), findsOneWidget);
        expect(find.textContaining('Butun qabul teskari qilinadi'), findsWidgets);
        await _confirm(tester);
        final lines = be.last('POST', '/receiving/r1/corrections').body['lines'] as List;
        expect(lines, [
          {
            'purchase_item_id': 'i1',
            'reverse': [
              {'stock_batch_id': 'L1', 'qty': 3}
            ]
          },
          {
            'purchase_item_id': 'i2',
            'reverse': [
              {'stock_batch_id': 'L3', 'qty': 2}
            ]
          },
        ]);
        expect(changed, isTrue);
        expect(find.byType(PurchaseDetailScreen), findsNothing);
        expect(find.text('Hujjat bekor qilindi'), findsOneWidget);
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
      });
    });

    testWidgets('lost answer: explained, document reloaded, the SAME draft is re-sent with the SAME key -> duplicate',
        (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      var landed = false;
      var failNext = true;
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) {
          final j = purchaseJson(total: landed ? 90000 : 150000);
          if (landed) ((j['items'] as List).first['lots'] as List).first['remaining_qty'] = 0.0;
          return j;
        })
        ..post('/receiving/{rid}/corrections', (r) {
          if (failNext) {
            failNext = false;
            landed = true; // the server wrote it, the answer never arrived
            throw const SocketExceptionForTest();
          }
          return _result(delta: -60000, duplicate: true);
        });
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '6');
        await tester.pumpAndSettle();
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        expect(find.byType(CorrectionScreen), findsOneWidget, reason: 'no success without a 2xx');
        expect(find.byKey(const Key('corr-error')), findsOneWidget);
        expect(find.textContaining('Natija noma’lum'), findsOneWidget);
        expect(be.calls('GET', '/purchases/p1'), hasLength(2), reason: 'reloaded after the failure');
        expect(find.textContaining('Qoldiqdan ko‘p'), findsOneWidget, reason: 'the reloaded lot has nothing left');
        // Re-send the untouched draft: client checks are skipped, same key.
        expect(_submitEnabled(tester), isTrue);
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        final posts = be.calls('POST', '/receiving/r1/corrections');
        expect(posts, hasLength(2));
        expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
        expect(posts[1].body['lines'], posts[0].body['lines']);
        expect(find.byType(CorrectionScreen), findsNothing);
        expect(find.text('Bu tuzatish avval yozilgan — qayta qo‘llanmadi.'), findsOneWidget);
      });
    });

    testWidgets('a gateway 504 is an UNKNOWN outcome: the key survives closing the editor; a decided rejection does not',
        (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final replies = <FakeResponse>[
        FakeResponse.error(504, 'Gateway Timeout'),
        FakeResponse.error(409, 'Partiya topilmadi: L1'),
      ];
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson())
        ..post('/receiving/{rid}/corrections', (r) => replies.isEmpty ? _result() : replies.removeAt(0));
      Future<void> sendOnce(String qty) async {
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), qty);
        await tester.pumpAndSettle();
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
      }

      Future<void> leaveEditor() async {
        await tester.pageBack();
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pumpAndSettle();
        expect(find.byType(CorrectionScreen), findsNothing);
      }

      await be.run(() async {
        await _openEditor(tester);
        await sendOnce('1');
        expect(find.textContaining('Natija noma’lum'), findsOneWidget, reason: '5xx: the write may have happened');
        await leaveEditor();
        // Reopen and type a (different) draft: the unresolved key is reused.
        await tester.tap(_inBar('pd-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await sendOnce('2');
        var posts = be.calls('POST', '/receiving/r1/corrections');
        expect(posts, hasLength(2));
        expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
        expect(find.textContaining('Natija noma’lum'), findsNothing, reason: 'a decided 409 is not "unknown"');
        await leaveEditor();
        await tester.tap(_inBar('pd-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await sendOnce('1');
        posts = be.calls('POST', '/receiving/r1/corrections');
        expect(posts, hasLength(3));
        expect(posts[2].body['client_uuid'], isNot(posts[0].body['client_uuid']),
            reason: 'after a decided answer a new editor starts a new request');
        expect(find.textContaining('Tuzatish yozildi'), findsOneWidget);
      });
    });

    testWidgets('LOT_CORRECTION_REPLAY_CONFLICT: translated, reloaded, the next send uses a NEW key', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      var first = true;
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson())
        ..post('/receiving/{rid}/corrections', (r) {
          if (first) {
            first = false;
            return FakeResponse.error(
                409,
                "Bu client_uuid BOSHQA tuzatish so'rovida ishlatilgan — takror emas. Yangi so'rov uchun yangi client_uuid bering.",
                code: 'LOT_CORRECTION_REPLAY_CONFLICT');
          }
          return _result();
        });
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Nakladnoy xato');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
        await tester.pumpAndSettle();
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        expect(find.textContaining('boshqa mazmun bilan yuborilgan'), findsOneWidget);
        expect(be.calls('GET', '/purchases/p1'), hasLength(2));
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        final posts = be.calls('POST', '/receiving/r1/corrections');
        expect(posts, hasLength(2));
        expect(posts[1].body['client_uuid'], isNot(posts[0].body['client_uuid']));
      });
    });

    testWidgets('a business rejection keeps the editor open with the translated message (ru)', (tester) async {
      L.code = 'ru';
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson())
        ..post('/receiving/{rid}/corrections', (r) => FakeResponse.error(
            409, "'Sut 1L': yopilmagan partiya qarzi bor — avval qarzni partiyaga bog'lang.",
            code: 'LOT_CORRECTION_SHORTFALL_OPEN'));
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Накладная');
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
        await tester.pumpAndSettle();
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.text('Записать исправление?'), findsOneWidget);
        await _confirm(tester);
        expect(find.byType(CorrectionScreen), findsOneWidget);
        expect(find.textContaining('незакрытый долг'), findsOneWidget);
      });
    });

    testWidgets('replacement of an expiry-tracked line: expiry required, picked, sent with the line cost', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()
        ..get('/purchases/{id}', (r) => purchaseJson())
        ..post('/receiving/{rid}/corrections', (r) => _result(delta: 0));
      await be.run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), 'Muddat xato yozilgan');
        await _scrollTo(tester, find.byKey(const Key('corr-rev-L3')));
        await tester.enterText(find.byKey(const Key('corr-rev-L3')), '5');
        await tester.pumpAndSettle();
        await _scrollTo(tester, find.byKey(const Key('corr-replace-1')));
        await tester.tap(find.byKey(const Key('corr-replace-1')));
        await tester.pumpAndSettle();
        await _scrollTo(tester, find.byKey(const Key('corr-rep-cost-1')));
        expect(tester.widget<TextField>(find.descendant(of: find.byKey(const Key('corr-rep-qty-1')), matching: find.byType(TextField))).controller!.text, '5');
        await tester.enterText(find.byKey(const Key('corr-rep-cost-1')), '10000');
        await tester.pumpAndSettle();
        // Submit without an expiry: refused client-side, focus on the row.
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        expect(find.textContaining('yaroqlilik muddatini kiriting'), findsWidgets);
        expect(be.calls('POST', '/receiving/r1/corrections'), isEmpty);
        await _scrollTo(tester, find.byKey(const Key('lot-expiry-0')));
        await tester.tap(find.byKey(const Key('lot-expiry-0')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('date-typed')), '10122026');
        await tester.tap(find.byKey(const Key('date-typed-ok')));
        await tester.pumpAndSettle();
        await tester.tap(_inBar('corr-bar', 'sticky-primary'));
        await tester.pumpAndSettle();
        await _confirm(tester);
        final line = (be.last('POST', '/receiving/r1/corrections').body['lines'] as List).single;
        expect(line, {
          'purchase_item_id': 'i2',
          'reverse': [
            {'stock_batch_id': 'L3', 'qty': 5}
          ],
          'replace': [
            {'qty': 5, 'expiry_date': '2026-12-10'}
          ],
          'unit_cost': 10000,
        });
      });
    });

    testWidgets('leaving with typed data asks first; controls are at least 48 dp', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      final be = FakeBackend()..get('/purchases/{id}', (r) => purchaseJson());
      await be.run(() async {
        await _openEditor(tester);
        expectMinTouchTarget(tester, find.byKey(const Key('corr-reverse-all')));
        expectMinTouchTarget(tester, find.byKey(const Key('corr-rev-all-L1')));
        expectMinTouchTarget(tester, _inBar('corr-bar', 'sticky-primary'));
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
        await tester.pumpAndSettle();
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(find.text('Tuzatish yozilmadi'), findsOneWidget);
        await tester.tap(find.byKey(const Key('confirm-no')));
        await tester.pumpAndSettle();
        expect(find.byType(CorrectionScreen), findsOneWidget);
        await tester.pageBack();
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pumpAndSettle();
        expect(find.byType(CorrectionScreen), findsNothing);
        expect(find.byType(PurchaseDetailScreen), findsOneWidget);
        expect(be.calls('GET', '/purchases/p1'), hasLength(2), reason: 'the document is re-read after leaving');
      });
    });

    testWidgets('the editor renders in Kyrgyz without overflow', (tester) async {
      L.code = 'ky';
      signIn(role: 'ega');
      final be = FakeBackend()
        ..get('/purchases/{id}',
            (r) => purchaseJson(custody: custodyJson('OPERATOR_MUST_CHOOSE', options: [kTill, kSafe])));
      await be.run(() async {
        await _openEditor(tester);
        expect(find.text('Кабыл алууну оңдоо'), findsOneWidget);
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '1');
        await tester.pumpAndSettle();
        expect(_barReason(tester), 'Акча кайсы касса же сейф аркылуу өтөрүн тандаңыз — сервер муну божомолдобойт');
        expect(tester.takeException(), isNull);
      });
    });
  });
}

/// A transport failure raised by a FakeBackend handler.
class SocketExceptionForTest implements Exception {
  const SocketExceptionForTest();
}
