// M3 — receiving correction draft: payload shape, money preview on the
// DOCUMENT basis (rounded once), full-cancel detection, cash custody gate,
// client checks (mirror of the server rules) and the idempotency key.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/correction_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

CorrLine line(CorrectionDraft d, String itemId) => d.lines.firstWhere((l) => l.itemId == itemId);

void main() {
  setUp(() async => resetCore());

  group('buildCorrLines', () {
    test('a lot is shown once (first line of its product); lines without lots are skipped', () {
      final j = purchaseJson(items: [
        itemJson('i1', 'p-sut', 'Sut 1L', qty: 4, lots: [lotJson('L1', received: 6), lotJson('L2', received: 4)]),
        // The same product on a second line: the server returns the SAME lots again.
        itemJson('i1b', 'p-sut', 'Sut 1L', qty: 6, unitCost: 9000, lots: [lotJson('L1', received: 6), lotJson('L2', received: 4)]),
        itemJson('i3', 'p-non', 'Non', trackLots: false),
      ]);
      final lines = buildCorrLines(doc(j));
      expect(lines.map((l) => l.itemId), ['i1']);
      expect(lines.single.lots.map((l) => l.id), ['L1', 'L2']);
    });

    test('a line the server blocks carries its reason', () {
      final j = purchaseJson(items: [
        itemJson('i1', 'p-sut', 'Sut 1L', correctable: false, blockedReason: 'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog\'lang, keyin bu qatorni tuzating.', lots: [lotJson('L1')]),
      ]);
      final l = buildCorrLines(doc(j)).single;
      expect(l.blocked, isNotNull);
      L.code = 'ru';
      expect(CorrectionDraft.blockedText(l), startsWith('У товара есть незакрытый долг'));
      L.code = 'uz';
    });
  });

  group('payload', () {
    test('reverse only: no replace, no unit_cost', () {
      final d = CorrectionDraft(doc(), uuid: 'u-1')
        ..setReason('  Nakladnoy xato  ')
        ..setRev('L1', '2');
      expect(d.payload(), [
        {
          'purchase_item_id': 'i1',
          'reverse': [
            {'stock_batch_id': 'L1', 'qty': 2}
          ]
        }
      ]);
      expect(d.body(), {
        'client_uuid': 'u-1',
        'reason': 'Nakladnoy xato',
        'lines': d.payload(),
      });
    });

    test('3-decimal quantities are sent exactly (comma input)', () {
      final d = CorrectionDraft(doc())..setRev('L1', '1,255');
      expect(jsonEncode(d.payload()), contains('"qty":1.255'));
      expect(d.revMilli('L1'), 1255);
    });

    test('replacement: unit_cost only with replace; expiry only for expiry-tracked products', () {
      final d = CorrectionDraft(doc())..setRev('L3', '5');
      final kefir = line(d, 'i2');
      d.setRepOn(kefir, true);
      expect(kefir.repOn, isTrue);
      expect(kefir.repQty, '5', reason: 'starts at what is being reversed');
      final row = kefir.rep!.rows.single;
      expect(row.qty, '5', reason: 'one automatic row follows the replacement quantity');
      kefir.rep!.update(row.key, expiry: '2026-12-10', batch: ' B-7 ');
      d.setRepCost(kefir, '9500,5');
      // Untracked-expiry line: an expiry typed into a row is NOT sent.
      d.setRev('L1', '1');
      final sut = line(d, 'i1');
      d.setRepOn(sut, true);
      sut.rep!.update(sut.rep!.rows.single.key, expiry: '2026-12-31');
      d.setRepCost(sut, '10000');
      expect(d.payload(), [
        {
          'purchase_item_id': 'i1',
          'reverse': [
            {'stock_batch_id': 'L1', 'qty': 1}
          ],
          'replace': [
            {'qty': 1}
          ],
          'unit_cost': 10000,
        },
        {
          'purchase_item_id': 'i2',
          'reverse': [
            {'stock_batch_id': 'L3', 'qty': 5}
          ],
          'replace': [
            {'qty': 5, 'batch_number': 'B-7', 'expiry_date': '2026-12-10'}
          ],
          'unit_cost': 9500.5,
        },
      ]);
    });

    test('replacement quantity edits move the single untouched row', () {
      final d = CorrectionDraft(doc())..setRev('L3', '2');
      final k = line(d, 'i2');
      d.setRepOn(k, true);
      d.setRepQty(k, '3,5');
      expect(k.rep!.rows.single.qty, '3,5');
      expect(k.rep!.targetMilli, 3500);
    });
  });

  group('money preview (document basis, rounded once)', () {
    test('reversal uses doc_unit_cost, not the lot\'s own cost', () {
      final d = CorrectionDraft(doc())..setRev('L1', '2');
      expect(d.reversedCents, 2000000, reason: '2 × 10 000 (doc), not 2 × 12 000 (lot)');
      expect(d.newTotalCents, 13000000);
      expect(d.retAmtCents, 2000000, reason: 'cash comes back');
      expect(d.moneyMoves, isTrue);
    });

    test('older server without doc_unit_cost falls back to unit_cost; a 0 doc cost is kept', () {
      final j = purchaseJson(items: [
        itemJson('i1', 'p1', 'A', lots: [lotJson('X', received: 2, unitCost: 700)]),
        itemJson('i2', 'p2', 'B', lots: [lotJson('Y', received: 2, unitCost: 700, docUnitCost: 0)]),
      ]);
      final d = CorrectionDraft(doc(j))
        ..setRev('X', '1')
        ..setRev('Y', '1');
      expect(d.reversedCents, 70000, reason: 'X at its own 700, Y at the document price 0');
    });

    test('the sum is rounded ONCE, not per lot', () {
      final j = purchaseJson(total: 0.02, items: [
        itemJson('i1', 'p1', 'Mayda', unitCost: 0.01, lots: [
          lotJson('A', received: 1, unitCost: 0.01, docUnitCost: 0.01),
          lotJson('B', received: 1, unitCost: 0.01, docUnitCost: 0.01),
        ]),
      ]);
      final d = CorrectionDraft(doc(j))
        ..setRev('A', '0,5')
        ..setRev('B', '0,5');
      expect(d.reversedCents, 1, reason: '0.005 + 0.005 = 0.01 (per-lot rounding would give 0.02)');
    });

    test('replacement value and delta', () {
      final d = CorrectionDraft(doc())..setRev('L1', '2');
      final s = line(d, 'i1');
      d.setRepOn(s, true);
      d.setRepCost(s, '11000');
      expect(d.replacedCents, 2200000);
      expect(d.deltaCents, 200000);
      expect(d.newTotalCents, 15200000);
      expect(d.retAmtCents, -200000, reason: 'more cash goes out');
    });

    test('an identity-only correction (same qty, same cost) moves no money', () {
      final d = CorrectionDraft(doc())..setRev('L1', '2');
      final s = line(d, 'i1');
      d.setRepOn(s, true);
      d.setRepCost(s, '10000');
      expect(d.deltaCents, 0);
      expect(d.moneyMoves, isFalse);
    });

    test('money moves when paid ≠ new total even if the delta is zero (writer rule)', () {
      final d = CorrectionDraft(doc(purchaseJson(total: 150000, paid: 140000)))..setRev('L1', '0');
      expect(d.deltaCents, 0);
      expect(d.moneyMoves, isTrue);
    });
  });

  group('full cancel', () {
    test('every lot reversed, no replacement, new total 0 -> cancel', () {
      final d = CorrectionDraft(doc(freshPurchaseJson()))..reverseAll();
      expect(d.rev, {'L1': '3', 'L3': '2'});
      expect(d.newTotalCents, 0);
      expect(d.fullCancel, isTrue);
    });

    test('a replacement or a partial reversal is not a cancel', () {
      final d = CorrectionDraft(doc(freshPurchaseJson()))..reverseAll();
      d.setRepOn(line(d, 'i1'), true);
      expect(d.fullCancel, isFalse);
      final p = CorrectionDraft(doc(freshPurchaseJson()))..setRev('L1', '3');
      expect(p.fullCancel, isFalse);
    });

    test('reverseAll skips a blocked line and switches replacements off', () {
      final j = purchaseJson(items: [
        itemJson('i1', 'p1', 'A', lots: [lotJson('X', received: 2)]),
        itemJson('i2', 'p2', 'B', correctable: false, blockedReason: 'SHORTFALL', lots: [lotJson('Y', received: 2)]),
      ]);
      final d = CorrectionDraft(doc(j));
      d.setRepOn(line(d, 'i1'), true);
      d.reverseAll();
      expect(d.rev, {'X': '2'});
      expect(line(d, 'i1').repOn, isFalse);
      expect(d.allReversed, isFalse, reason: 'the blocked line keeps its stock — no cancel');
    });
  });

  group('cash custody gate', () {
    CorrectionDraft withCustody(Map<String, dynamic> c) => CorrectionDraft(doc(purchaseJson(custody: c)));

    test('OPERATOR_MUST_CHOOSE: gate closed until an EXACT option is chosen; only then sent', () {
      final d = withCustody(custodyJson('OPERATOR_MUST_CHOOSE',
          reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kTill, kSafe]))
        ..setReason('xato')
        ..setRev('L1', '1');
      expect(d.cashShown, isTrue);
      expect(d.mustChoose, isTrue);
      expect(d.cashNeed, isTrue);
      expect(d.cashAccountId, isNull, reason: 'never preselected');
      expect(d.body().containsKey('cash_account_id'), isFalse);
      d.setCash('bogus');
      expect(d.cashNeed, isTrue);
      expect(d.body().containsKey('cash_account_id'), isFalse);
      d.setCash('s1');
      expect(d.cashNeed, isFalse);
      expect(d.body()['cash_account_id'], 's1');
    });

    test('OPERATOR_MUST_CHOOSE with no options is blocked with its own message', () {
      final d = withCustody(custodyJson('OPERATOR_MUST_CHOOSE'))..setRev('L1', '1');
      expect(d.cashEmpty, isTrue);
      expect(d.cashBlocked, isTrue);
      expect(d.cashGateReason(), contains('faol kassa yoki seyf yo‘q'));
    });

    test('SERVER_RESOLVED: shown, nothing sent', () {
      final d = withCustody(custodyJson('SERVER_RESOLVED', resolved: kTill))
        ..setCash('t1')
        ..setRev('L1', '1');
      expect(d.cashShown, isTrue);
      expect(d.cashNeed, isFalse);
      expect(d.cashBlocked, isFalse);
      expect(d.body().containsKey('cash_account_id'), isFalse);
    });

    test('BLOCKED closes the gate only when money moves', () {
      final d = withCustody(custodyJson('BLOCKED', reason: 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER'))..setRev('L1', '1');
      expect(d.cashBlocked, isTrue);
      L.code = 'ru';
      expect(d.cashGateReason(), startsWith('Это исправление двигает деньги, но записать его сейчас нельзя: '));
      L.code = 'uz';
      // Identity-only: same qty, same cost -> money does not move -> not gated.
      final s = line(d, 'i1');
      d.setRepOn(s, true);
      d.setRepCost(s, '10000');
      expect(d.moneyMoves, isFalse);
      expect(d.cashShown, isFalse);
      expect(d.cashBlocked, isFalse);
    });

    test('NOT_APPLICABLE / NOT_REQUIRED / older server: never shown, never sent', () {
      for (final c in [custodyJson('NOT_APPLICABLE'), custodyJson('NOT_REQUIRED')]) {
        final d = withCustody(c)
          ..setRev('L1', '1')
          ..setCash('t1');
        expect(d.cashShown, isFalse);
        expect(d.body().containsKey('cash_account_id'), isFalse);
      }
      final old = CorrectionDraft(doc(purchaseJson(withCustody: false)))..setRev('L1', '1');
      expect(old.custody, isNull);
      expect(old.cashShown, isFalse);
    });

    test('an unknown custody mode fails closed', () {
      final d = withCustody({'mode': 'NEW_MODE'})..setRev('L1', '1');
      expect(d.custody!.mode, CustodyMode.blocked);
      expect(d.cashBlocked, isTrue);
    });
  });

  group('check (mirror of the server rules)', () {
    CorrectionDraft ready() => CorrectionDraft(doc())
      ..setReason('Nakladnoyda 8 ta edi')
      ..setRev('L1', '2');

    test('valid draft passes', () => expect(ready().check(), isNull));

    test('reason 3..300', () {
      expect((ready()..setReason(' ab ')).check()!.kind, CorrIssueKind.reason);
      expect((ready()..setReason('x' * 301)).check()!.kind, CorrIssueKind.reason);
      expect((ready()..setReason('abc')).check(), isNull);
    });

    test('reversal above the remaining quantity / invalid number', () {
      final over = ready()..setRev('L2', '1,001');
      final i = over.check()!;
      expect(i.kind, CorrIssueKind.overRemaining);
      expect(i.lotId, 'L2');
      expect((ready()..setRev('L2', '1')).check(), isNull, reason: 'exactly the remaining is fine');
      expect((ready()..setRev('L1', '1,2345')).check()!.kind, CorrIssueKind.revInvalid);
      expect((ready()..setRev('L1', 'abc')).check()!.kind, CorrIssueKind.revInvalid);
    });

    test('replacement cannot be switched on once a moved lot is reversed; check reports it if it was on', () {
      final d = ready()..setRev('L2', '1');
      final s = line(d, 'i1');
      d.setRepOn(s, true);
      expect(s.repOn, isFalse, reason: 'touched lot: switching on is refused');
      final e = ready();
      final s2 = line(e, 'i1');
      e.setRepOn(s2, true);
      e.setRev('L2', '1');
      expect(e.check()!.kind, CorrIssueKind.replaceLocked);
      e.setRepOn(s2, false);
      expect(s2.repOn, isFalse, reason: 'switching off always works');
      expect(e.check(), isNull);
    });

    test('replacement quantity, lot sum, expiry, cost', () {
      final d = CorrectionDraft(doc())
        ..setReason('muddat xato')
        ..setRev('L3', '5');
      final k = line(d, 'i2');
      d.setRepOn(k, true);
      d.setRepCost(k, '10000');
      // expiry required for an expiry-tracked product
      var i = d.check()!;
      expect(i.kind, CorrIssueKind.repLots);
      expect(i.message, contains('yaroqlilik muddatini kiriting'));
      final row = k.rep!.rows.single;
      k.rep!.update(row.key, expiry: '2026-09-18');
      i = d.check()!;
      expect(i.message, contains('ish kunidan (19.09.2026)'), reason: 'before the DOCUMENT branch business date');
      k.rep!.update(row.key, expiry: '2026-09-19');
      expect(d.check(), isNull, reason: 'expiry == business date is allowed');
      // Σ lots ≠ replacement qty
      k.rep!.update(row.key, qty: '4');
      expect(d.check()!.message, contains('yig‘indisi'));
      k.rep!.update(row.key, qty: '5');
      // replacement qty missing
      d.setRepQty(k, '');
      expect(d.check()!.kind, CorrIssueKind.repQty);
      d.setRepQty(k, '5');
      k.rep!.update(row.key, qty: '5');
      // cost must be > 0
      d.setRepCost(k, '0');
      expect(d.check()!.kind, CorrIssueKind.repCost);
      d.setRepCost(k, '');
      expect(d.check()!.kind, CorrIssueKind.repCost);
      d.setRepCost(k, '1');
      expect(d.check(), isNull);
    });

    test('nothing to send', () {
      final d = CorrectionDraft(doc())..setReason('hech narsa');
      expect(d.check()!.kind, CorrIssueKind.nothing);
      d.setRev('L1', '0');
      expect(d.check()!.kind, CorrIssueKind.nothing);
    });

    test('messages are localized (ky)', () {
      L.code = 'ky';
      final d = CorrectionDraft(doc())..setReason('a');
      expect(d.check()!.message, 'Себебин жазыңыз (3–300 белги) — оңдоо изсиз калбайт');
      L.code = 'uz';
    });
  });

  group('idempotency (same uuid for the same draft)', () {
    test('a re-sent identical draft is a replay; any edit makes it a new request', () {
      final d = CorrectionDraft(doc(), uuid: 'u-1')
        ..setReason('xato')
        ..setRev('L1', '2');
      expect(d.isReplay, isFalse);
      d.markSent();
      expect(d.isReplay, isTrue);
      d.setReason('xato!');
      expect(d.isReplay, isFalse);
      d.setReason('xato');
      expect(d.isReplay, isTrue);
      expect(d.body()['client_uuid'], 'u-1', reason: 'the key never changes for a retry');
    });

    test('a reload after a lost answer keeps the typed draft and the replay', () {
      final d = CorrectionDraft(doc(), uuid: 'u-1')
        ..setReason('xato')
        ..setRev('L1', '6');
      d.markSent();
      // The request DID land: the reloaded lot has 0 left.
      final j = purchaseJson(total: 90000);
      (j['items'] as List).first['lots'][0]['remaining_qty'] = 0.0;
      d.setDoc(doc(j));
      expect(d.rev['L1'], '6');
      expect(d.isReplay, isTrue, reason: 'the draft itself did not change');
      expect(d.check()!.kind, CorrIssueKind.overRemaining, reason: 'a NEW request would be refused client-side');
      expect(d.body()['client_uuid'], 'u-1');
    });

    test('LOT_CORRECTION_REPLAY_CONFLICT rotates the key and forgets the sent draft', () {
      final d = CorrectionDraft(doc(), uuid: 'u-1')
        ..setReason('xato')
        ..setRev('L1', '2');
      d.markSent();
      d.onReplayConflict();
      expect(d.uuid, isNot('u-1'));
      expect(d.isReplay, isFalse);
    });

    test('setDoc keeps replacement drafts by line and drops entries of a line that became blocked', () {
      final d = CorrectionDraft(doc())
        ..setRev('L1', '1')
        ..setRev('L3', '2');
      final k = line(d, 'i2');
      d.setRepOn(k, true);
      final ctl = k.rep;
      final j = purchaseJson();
      final items = j['items'] as List;
      items[0]['correctable'] = false;
      items[0]['correction_blocked_reason'] = 'SHORTFALL';
      d.setDoc(doc(j));
      expect(d.rev, {'L3': '2'});
      expect(line(d, 'i2').repOn, isTrue);
      expect(identical(line(d, 'i2').rep, ctl), isTrue);
      d.dispose();
    });
  });

  test('outcomeUnknown: no answer / timeout / 5xx are unknown; decided 4xx are not', () {
    expect(outcomeUnknown(ApiException(0, 'x', kind: ApiErrorKind.network)), isTrue);
    expect(outcomeUnknown(ApiException(0, 'x', kind: ApiErrorKind.timeout)), isTrue);
    expect(outcomeUnknown(ApiException(504, 'Gateway Timeout')), isTrue);
    expect(outcomeUnknown(ApiException(200, 'html', kind: ApiErrorKind.server, code: 'BAD_RESPONSE')), isTrue);
    expect(outcomeUnknown(ApiException(409, 'x', code: 'LOT_CORRECTION_CONSUMED')), isFalse);
    expect(outcomeUnknown(ApiException(400, 'x')), isFalse);
    expect(outcomeUnknown(ApiException(422, 'x')), isFalse);
    expect(outcomeUnknown(ApiException(403, 'x')), isFalse);
  });

  test('PendingCorrectionKeys remembers an unresolved key per purchase', () {
    PendingCorrectionKeys.clear();
    expect(PendingCorrectionKeys.of('p1'), isNull);
    PendingCorrectionKeys.unknown('p1', 'u-9');
    expect(CorrectionDraft(doc(), uuid: PendingCorrectionKeys.of('p1')).uuid, 'u-9');
    expect(PendingCorrectionKeys.of('p2'), isNull);
    PendingCorrectionKeys.resolved('p1');
    expect(PendingCorrectionKeys.of('p1'), isNull);
  });

  test('dirty flag', () {
    final d = CorrectionDraft(doc());
    expect(d.dirty, isFalse);
    d.setRev('L1', '1');
    expect(d.dirty, isTrue);
  });

  test('CorrectionResult parses the writer reply', () {
    final r = CorrectionResult.fromJson({
      'ok': true,
      'correction_id': 'c1',
      'receiving_id': 'r1',
      'purchase_id': 'p1',
      'reversed_total': 20000.0,
      'replaced_total': 0.0,
      'delta_total': -20000.0,
      'purchase_status': 'received',
      'cancelled': false,
      'duplicate': true,
    });
    expect(r.deltaCents, -2000000);
    expect(r.duplicate, isTrue);
    expect(r.cancelled, isFalse);
    expect(signedCents(r.deltaCents), '−${formatCents(2000000)}');
    expect(signedCents(150), '+${formatCents(150)}');
    expect(signedCents(0), formatCents(0));
  });
}
