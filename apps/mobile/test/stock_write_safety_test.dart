// M2 write safety: a write whose OUTCOME IS UNKNOWN (network drop, timeout or
// a gateway 5xx) locks the draft. The screen promises «qayta yuborsangiz, ikki
// marta yozilmaydi», so until the server answers 2xx — or the operator
// explicitly abandons the attempt — nothing in the form may change and the
// retry MUST carry the same `client_uuid`.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/screens/transfer_screen.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/ui/ui.dart';

import 'stock_fixtures_test.dart';

/// A gateway failure: an HTTP answer arrived, but it decides NOTHING.
FakeResponse gateway502(FakeRequest _) => FakeResponse.error(502, 'Bad Gateway');

/// No answer at all within the write timeout.
Never timeoutFail(FakeRequest _) => throw TimeoutException('no answer');

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  Future<void> submit(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('sticky-primary')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-yes')));
    await tester.pumpAndSettle();
  }

  bool enabledOf(WidgetTester tester, Key k) {
    final w = tester.widget(find.byKey(k));
    if (w is QtyField) return w.enabled;
    if (w is TextField) return w.enabled ?? true;
    throw StateError('${w.runtimeType} has no enabled flag');
  }

  // ── Write-off ───────────────────────────────────────────────────────────

  group('write-off', () {
    void untracked() => be.get('/lots/products/{id}', (r) => lotsJson('p5', const [], tracked: false, inv: 20));

    Future<void> openAndFail(WidgetTester tester, FakeHandler fail) async {
      be.post('/inventory/writeoff', fail);
      await pumpAt390(tester, const WriteoffScreen(initialProduct: StockProduct(id: 'p5', name: 'Sut 1L')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('wo-qty')), '5');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('wo-reason-damaged')));
      await tester.pumpAndSettle();
      await submit(tester);
    }

    testWidgets('gateway 502 is an UNKNOWN outcome: retry hint, locked inputs, same client_uuid', (tester) async {
      await signInAs(be);
      untracked();
      await be.run(() async {
        await openAndFail(tester, gateway502);
        expect(find.byKey(const Key('wo-error')), findsOneWidget);
        expect(find.textContaining('ikki marta yozilmaydi'), findsOneWidget,
            reason: 'a 502 can hide a committed write — the outcome is unknown');
        expect(find.text('Qayta yuborish'), findsOneWidget);
        expect(find.byKey(const Key('wo-unknown')), findsOneWidget);

        // The draft is LOCKED: nothing the operator touches may change the body.
        expect(enabledOf(tester, const Key('wo-qty')), isFalse);
        expect(tester.widget<OutlinedButton>(find.byKey(const Key('wo-pick'))).onPressed, isNull);
        expect(tester.widget<OutlinedButton>(find.byKey(const Key('wo-scan'))).onPressed, isNull);
        await tester.enterText(find.byKey(const Key('wo-qty')), '6'); // ignored: disabled
        await tester.pumpAndSettle();

        final list = find.descendant(of: find.byKey(const Key('wo-list')), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(find.byKey(const Key('wo-note')), 150, scrollable: list);
        await tester.pumpAndSettle();
        expect(tester.widget<ChoiceChip>(find.byKey(const Key('wo-reason-lost'))).onSelected, isNull);
        expect(enabledOf(tester, const Key('wo-note')), isFalse);
        await tester.tap(find.byKey(const Key('wo-reason-lost')));
        await tester.enterText(find.byKey(const Key('wo-note')), 'sinib qoldi');
        await tester.pumpAndSettle();

        be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Sut 1L', 'new_qty': 15});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/writeoff');
      expect(posts, hasLength(2));
      expect(posts[1].body['qty'], 5, reason: 'the retry re-sends the SAME quantity');
      expect(posts[1].body['reason'], 'damaged');
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid'],
          reason: 'the same physical write-off keeps its idempotency key');
      expect(find.byKey(const Key('wo-done')), findsOneWidget);
    });

    testWidgets('timeout locks the draft the same way; an explicit discard rotates the key', (tester) async {
      await signInAs(be);
      untracked();
      await be.run(() async {
        await openAndFail(tester, timeoutFail);
        expect(enabledOf(tester, const Key('wo-qty')), isFalse);
        // «Bekor qilish» — the operator gives up on this attempt on purpose.
        await tester.tap(find.byKey(const Key('sticky-secondary')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pumpAndSettle();
        expect(enabledOf(tester, const Key('wo-qty')), isTrue, reason: 'the form is editable again');
        be.post('/inventory/writeoff', (r) => {'ok': true, 'product': 'Sut 1L', 'new_qty': 18});
        await tester.enterText(find.byKey(const Key('wo-qty')), '2');
        await tester.pumpAndSettle();
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/writeoff');
      expect(posts, hasLength(2));
      expect(posts[1].body['client_uuid'], isNot(posts[0].body['client_uuid']),
          reason: 'a DIFFERENT operation after an explicit discard');
    });

    // The freeze only starts when the answer (or the timeout) arrives. The
    // window BEFORE that is the dangerous one: the write may be committing on
    // the server while the operator walks away, and the State — with the only
    // `client_uuid` — dies with the route.
    testWidgets('leaving while the write is IN FLIGHT is blocked, and the answer lands on the screen that sent it',
        (tester) async {
      await signInAs(be);
      untracked();
      final gate = Completer<Object?>();
      be.post('/inventory/writeoff', (r) => gate.future);
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) {
          Navigator.of(ctx).push(MaterialPageRoute(
              builder: (_) => const WriteoffScreen(initialProduct: StockProduct(id: 'p5', name: 'Sut 1L'))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('wo-qty')), '5');
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('wo-reason-damaged')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        // NOT pumpAndSettle: the request must stay in flight.
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.byKey(const Key('wo-inflight')), findsOneWidget,
            reason: 'the operator must be told the request is out and the answer is pending');

        await tester.pageBack();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.byKey(const Key('wo-list')), findsOneWidget,
            reason: 'the screen may not be left while the outcome is still being decided');

        gate.complete({'ok': true, 'product': 'Sut 1L', 'new_qty': 15});
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('wo-done')), findsOneWidget);
      });
      expect(be.calls('POST', '/inventory/writeoff'), hasLength(1));
    });

    // The draft carries the branch it was LOADED for; the session's current
    // branch may move under a frozen draft (resume / owner edit). The retry
    // still writes off the old branch — so that is the branch to show.
    testWidgets('a frozen write-off names the branch it will write off, not the one now selected', (tester) async {
      await signInAs(be);
      untracked();
      await be.run(() async {
        await openAndFail(tester, gateway502);
        expect(find.byKey(const Key('wo-unknown')), findsOneWidget);
        expect(find.text('Markaz'), findsOneWidget);
        await Session.instance.selectBranch('b2'); // Chilonzor
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('wo-unknown')), findsOneWidget, reason: 'the lock survives a branch change');
        expect(tester.widget<Text>(find.byKey(const Key('wo-branch-locked'))).data, 'Markaz',
            reason: 'the frozen body still carries Markaz — showing Chilonzor mislabels an irreversible write');
        // The confirmation of the retry must name the same branch.
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        expect(find.textContaining('Filial: Markaz'), findsOneWidget);
        expect(find.textContaining('Filial: Chilonzor'), findsNothing);
        await tester.tap(find.byKey(const Key('confirm-no')));
        await tester.pumpAndSettle();
      });
      expect(be.last('POST', '/inventory/writeoff').body['branch_id'], 'b1');
    });
  });

  // ── Count ───────────────────────────────────────────────────────────────

  group('count', () {
    void catalog() {
      be.get('/products',
          (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10)], headers: const {'x-total-count': '1'}));
      be.get('/lots/products/{id}', (r) => lotsJson('p5', const [], tracked: false, inv: 10));
    }

    Future<void> addPlain(WidgetTester tester, String qty) async {
      await tester.tap(find.byKey(const Key('cnt-add')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('picker-row-p5')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('cnt-plain-qty')), qty);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-plain-save')));
      await tester.pumpAndSettle();
    }

    testWidgets('502: the session is frozen (no add / edit / remove) and the retry reuses client_uuid',
        (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/count', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await addPlain(tester, '7');
        await submit(tester);
        expect(find.byKey(const Key('cnt-unknown')), findsOneWidget);
        expect(find.text('Qayta yuborish'), findsOneWidget);
        expect(tester.widget<OutlinedButton>(find.byKey(const Key('cnt-add'))).onPressed, isNull);
        expect(tester.widget<OutlinedButton>(find.byKey(const Key('cnt-scan'))).onPressed, isNull);
        expect(tester.widget<IconButton>(find.byKey(const Key('cnt-edit-p5'))).onPressed, isNull);
        expect(tester.widget<IconButton>(find.byKey(const Key('cnt-remove-p5'))).onPressed, isNull);
        be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/count');
      expect(posts, hasLength(2));
      expect(posts[1].body['items'], posts[0].body['items']);
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
    });

    testWidgets('timeout: the same freeze', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/count', timeoutFail);
      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await addPlain(tester, '7');
        await submit(tester);
        expect(find.byKey(const Key('cnt-unknown')), findsOneWidget);
        expect(tester.widget<IconButton>(find.byKey(const Key('cnt-remove-p5'))).onPressed, isNull);
      });
    });

    // The freeze blocks «Qidirish»/«Skanerlash», but the open-error banner has
    // its own Retry that re-enters the very same code path — and an entry added
    // that way changes the body, so the retry would be sent under a NEW key
    // while the first send may already be committed.
    testWidgets('the open-error Retry cannot reopen the draft while the outcome is unknown', (tester) async {
      await signInAs(be);
      var lotsFail = true;
      be.get(
          '/products',
          (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10), prodJson('p6', 'Tuz', stock: 4)],
              headers: const {'x-total-count': '2'}));
      be.get('/lots/products/{id}', (r) {
        final id = r.params['id']!;
        if (id == 'p6' && lotsFail) return FakeResponse.error(500, 'ombor xizmati javob bermadi');
        return lotsJson(id, const [], tracked: false, inv: id == 'p5' ? 10 : 4);
      });
      be.post('/inventory/count', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await addPlain(tester, '7'); // p5 is counted

        // p6's lots fail -> the open-error banner offers a live Retry.
        await tester.tap(find.byKey(const Key('cnt-add')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('picker-row-p6')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('cnt-open-error')), findsOneWidget);

        await submit(tester); // 502 -> outcome unknown, the session freezes
        expect(find.byKey(const Key('cnt-unknown')), findsOneWidget);

        final retry = find.descendant(
            of: find.byKey(const Key('cnt-open-error')), matching: find.byKey(const Key('banner-retry')));
        expect(find.byKey(const Key('cnt-open-error')), findsOneWidget);
        expect(retry, findsNothing,
            reason: 'while frozen, nothing may reopen the draft — not even a retry of the lots fetch');

        lotsFail = false;
        expect(find.byKey(const Key('cnt-plain-qty')), findsNothing, reason: 'no editor may open while frozen');
        expect(find.byKey(const Key('cnt-item-p6')), findsNothing);

        be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/count');
      expect(posts, hasLength(2));
      expect(posts[1].body['items'], posts[0].body['items'], reason: 'EXACTLY the same operation is re-sent');
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
    });

    testWidgets('leaving while the count is IN FLIGHT does not claim it was never sent', (tester) async {
      await signInAs(be);
      catalog();
      final gate = Completer<Object?>();
      be.post('/inventory/count', (r) => gate.future);
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) {
          Navigator.of(ctx).push(MaterialPageRoute(builder: (_) => const InventarizatsiyaScreen()));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await addPlain(tester, '7');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.byKey(const Key('cnt-inflight')), findsOneWidget);

        await tester.pageBack();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.text('Sanoq yuborilmagan'), findsNothing,
            reason: 'the counts WERE sent — telling the operator the opposite invites a second count');
        expect(find.byKey(const Key('cnt-list')), findsOneWidget);

        gate.complete({'ok': true, 'changed': 1, 'results': const []});
        await tester.pumpAndSettle();
      });
      expect(be.calls('POST', '/inventory/count'), hasLength(1));
    });

    testWidgets('a branch change while FROZEN keeps the lock, the list and the key', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/count', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await addPlain(tester, '7');
        await submit(tester);
        expect(find.byKey(const Key('cnt-unknown')), findsOneWidget);

        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('cnt-unknown')), findsOneWidget,
            reason: 'a branch change is not proof that the pending count was refused');
        expect(find.byKey(const Key('cnt-branch-notice')), findsOneWidget);
        expect(find.textContaining('yozilgan bo‘lishi mumkin'), findsOneWidget,
            reason: 'the notice must say the frozen attempt may already be applied');
        final list = find.descendant(of: find.byKey(const Key('cnt-list')), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(find.byKey(const Key('cnt-item-p5')), 150, scrollable: list);
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('cnt-item-p5')), findsOneWidget);

        be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/count');
      expect(posts, hasLength(2));
      expect(posts[1].body['branch_id'], posts[0].body['branch_id'], reason: 'the frozen body is re-sent verbatim');
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
    });

    // Keeping the frozen branch must not outlive the frozen draft: after the
    // operator abandons the attempt, the NEXT count belongs to the branch they
    // are actually looking at.
    testWidgets('after an explicit discard the next count uses the CURRENT branch', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/count', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await addPlain(tester, '7');
        await submit(tester);
        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const Key('sticky-secondary'))); // «Bekor qilish»
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pumpAndSettle();

        be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});
        await addPlain(tester, '3');
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/count');
      expect(posts, hasLength(2));
      expect(posts[0].body['branch_id'], 'b1');
      expect(posts[1].body['branch_id'], 'b2', reason: 'the new count is Chilonzor’s, and it says so');
      expect(posts[1].body['client_uuid'], isNot(posts[0].body['client_uuid']));
    });
  });

  // ── Transfer ────────────────────────────────────────────────────────────

  group('transfer', () {
    void catalog() {
      be.get('/products',
          (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10)], headers: const {'x-total-count': '1'}));
      be.get(
          '/branches',
          (r) => {
                'branches': [
                  {'id': 'b1', 'name': 'Markaz', 'is_active': true, 'visible': true},
                  {'id': 'b2', 'name': 'Chilonzor', 'is_active': true, 'visible': true},
                ],
              });
    }

    Future<void> fill(WidgetTester tester) async {
      await tester.tap(find.byKey(const Key('tr-dest')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-dest-b2')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-add')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('picker-row-p5')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('tr-qty')), '3');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tr-qty-save')));
      await tester.pumpAndSettle();
    }

    testWidgets('502: destination and lines are frozen, retry reuses client_uuid', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/transfer', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await fill(tester);
        await submit(tester);
        expect(find.byKey(const Key('tr-unknown')), findsOneWidget);
        expect(find.text('Qayta yuborish'), findsOneWidget);
        final list = find.descendant(of: find.byKey(const Key('tr-list')), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(find.byKey(const Key('tr-item-p5')), 150, scrollable: list);
        await tester.pumpAndSettle();
        expect(tester.widget<IconButton>(find.byKey(const Key('tr-edit-p5'))).onPressed, isNull);
        expect(tester.widget<IconButton>(find.byKey(const Key('tr-remove-p5'))).onPressed, isNull);
        expect(tester.widget<OutlinedButton>(find.byKey(const Key('tr-add'))).onPressed, isNull);
        expect(tester.widget<InkWell>(find.byKey(const Key('tr-dest'))).onTap, isNull);
        be.post('/inventory/transfer', (r) => {'ok': true, 'from': 'Markaz', 'to': 'Chilonzor', 'moved': const []});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/transfer');
      expect(posts, hasLength(2));
      expect(posts[1].body['items'], posts[0].body['items']);
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
    });

    testWidgets('timeout: the same freeze', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/transfer', timeoutFail);
      await be.run(() async {
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await fill(tester);
        await submit(tester);
        expect(find.byKey(const Key('tr-unknown')), findsOneWidget);
        final list = find.descendant(of: find.byKey(const Key('tr-list')), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(find.byKey(const Key('tr-item-p5')), 150, scrollable: list);
        await tester.pumpAndSettle();
        expect(tester.widget<IconButton>(find.byKey(const Key('tr-remove-p5'))).onPressed, isNull);
      });
    });

    testWidgets('leaving while the transfer is IN FLIGHT is blocked', (tester) async {
      await signInAs(be);
      catalog();
      final gate = Completer<Object?>();
      be.post('/inventory/transfer', (r) => gate.future);
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) {
          Navigator.of(ctx).push(MaterialPageRoute(builder: (_) => const TransferScreen()));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await fill(tester);
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.byKey(const Key('tr-inflight')), findsOneWidget);

        await tester.pageBack();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.byKey(const Key('tr-list')), findsOneWidget,
            reason: 'the goods may be moving right now — the outcome may not be dropped');

        gate.complete({'ok': true, 'from': 'Markaz', 'to': 'Chilonzor', 'moved': const []});
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('tr-done')), findsOneWidget);
      });
      expect(be.calls('POST', '/inventory/transfer'), hasLength(1));
    });

    testWidgets('a source-branch change while FROZEN keeps the lock, the lines and the key', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/transfer', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await fill(tester);
        await submit(tester);
        expect(find.byKey(const Key('tr-unknown')), findsOneWidget);

        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('tr-unknown')), findsOneWidget,
            reason: 'the goods may already have moved — a branch change does not undo that');
        expect(find.byKey(const Key('tr-notice')), findsOneWidget);
        expect(find.textContaining('yozilgan bo‘lishi mumkin'), findsOneWidget);
        final list = find.descendant(of: find.byKey(const Key('tr-list')), matching: find.byType(Scrollable)).first;
        await tester.scrollUntilVisible(find.byKey(const Key('tr-from-locked')), 150, scrollable: list);
        await tester.pumpAndSettle();
        expect(tester.widget<Text>(find.byKey(const Key('tr-from-locked'))).data, 'Markaz',
            reason: 'the frozen transfer still leaves Markaz');

        be.post('/inventory/transfer', (r) => {'ok': true, 'from': 'Markaz', 'to': 'Chilonzor', 'moved': const []});
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/transfer');
      expect(posts, hasLength(2));
      expect(posts[1].body['from_branch_id'], posts[0].body['from_branch_id']);
      expect(posts[1].body['items'], posts[0].body['items']);
      expect(posts[1].body['client_uuid'], posts[0].body['client_uuid']);
    });

    testWidgets('after an explicit discard the next transfer leaves the CURRENT branch', (tester) async {
      await signInAs(be);
      catalog();
      be.post('/inventory/transfer', gateway502);
      await be.run(() async {
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await fill(tester); // Markaz (b1) -> Chilonzor (b2)
        await submit(tester);
        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const Key('sticky-secondary'))); // «Bekor qilish»
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await tester.pumpAndSettle();

        be.post('/inventory/transfer', (r) => {'ok': true, 'from': 'Chilonzor', 'to': 'Markaz', 'moved': const []});
        await tester.tap(find.byKey(const Key('tr-dest')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('tr-dest-b1')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('tr-add')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('picker-row-p5')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('tr-qty')), '2');
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('tr-qty-save')));
        await tester.pumpAndSettle();
        await submit(tester);
      });
      final posts = be.calls('POST', '/inventory/transfer');
      expect(posts, hasLength(2));
      expect(posts[0].body['from_branch_id'], 'b1');
      expect(posts[1].body['from_branch_id'], 'b2', reason: 'the abandoned draft must not pin the old source branch');
      expect(posts[1].body['to_branch_id'], 'b1');
      expect(posts[1].body['client_uuid'], isNot(posts[0].body['client_uuid']));
    });
  });
}
