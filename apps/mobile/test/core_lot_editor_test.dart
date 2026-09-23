import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/widgets/lot_editor.dart';

import 'support/support.dart';

LotDraft d(String qty, {String? exp, String batch = '', String cost = ''}) =>
    LotDraft(qty: qty, expiry: exp, batch: batch, unitCost: cost);

void main() {
  group('lotLineState (mirror of desktop lotLineState)', () {
    test('valid single and multi lot', () {
      expect(lotLineState(targetMilli: 5000, lots: [d('5')]).ok, isTrue);
      final st = lotLineState(targetMilli: 5000, lots: [d('2,5'), d('1.5'), d('1')]);
      expect(st.ok, isTrue);
      expect(st.sumMilli, 5000);
      expect(st.diffMilli, 0);
    });

    test('float-free sum: 0.1 + 0.2 == 0.3', () {
      expect(lotLineState(targetMilli: 300, lots: [d('0,1'), d('0,2')]).ok, isTrue);
    });

    test('mismatch reports remaining / excess and focuses the last row', () {
      final lots = [d('2'), d('1')];
      final st = lotLineState(targetMilli: 5000, lots: lots);
      expect(st.has(LotIssueKind.mismatch), isTrue);
      expect(st.diffMilli, 2000);
      expect(st.firstBadKey, lots.last.key);
      expect(lotLineState(targetMilli: 1000, lots: [d('2')]).diffMilli, -1000);
    });

    test('>3 decimals is its own issue and hides the sum mismatch', () {
      final lots = [d('1,2345'), d('1')];
      final st = lotLineState(targetMilli: 5000, lots: lots);
      expect(st.has(LotIssueKind.decimals, lots.first.key), isTrue);
      expect(st.has(LotIssueKind.mismatch), isFalse);
      expect(st.diffMilli, isNull);
      expect(st.firstBadField, LotField.qty);
    });

    test('expiry required iff tracked; not before the business date', () {
      final a = d('1'), b = d('1', exp: '2026-09-18'), c = d('1', exp: '2026-09-19');
      final st = lotLineState(targetMilli: 3000, lots: [a, b, c], trackExpiry: true, businessDate: '2026-09-19');
      expect(st.has(LotIssueKind.expiryMissing, a.key), isTrue);
      expect(st.has(LotIssueKind.expiryPast, b.key), isTrue);
      expect(st.has(LotIssueKind.expiryPast, c.key), isFalse, reason: 'expiry == business date is allowed');
      expect(st.firstBadKey, a.key);
      expect(st.firstBadField, LotField.expiry);
      // Unknown business date -> the past check is left to the server.
      expect(lotLineState(targetMilli: 1000, lots: [b], trackExpiry: true).ok, isTrue);
      // Untracked expiry: no expiry issues at all.
      expect(lotLineState(targetMilli: 1000, lots: [a]).ok, isTrue);
    });

    test('line qty invalid, no rows, too many rows', () {
      expect(lotLineState(targetMilli: null, lots: [d('1')]).firstBadField, LotField.line);
      expect(lotLineState(targetMilli: 1000, lots: const []).has(LotIssueKind.qty), isTrue);
      final many = [for (var i = 0; i < kMaxLots + 1; i++) d('1')];
      expect(lotLineState(targetMilli: (kMaxLots + 1) * 1000, lots: many).has(LotIssueKind.tooMany), isTrue);
    });

    test('count new_lots: no target, empty allowed, cost required (0 ok)', () {
      expect(lotLineState(targetMilli: null, lots: const [], hasTarget: false, allowEmpty: true).ok, isTrue);
      final a = d('2', cost: ''), b = d('1', cost: '0'), c = d('1', cost: '-1');
      final st = lotLineState(
          targetMilli: null, lots: [a, b, c], hasTarget: false, withUnitCost: true, allowEmpty: true);
      expect(st.has(LotIssueKind.cost, a.key), isTrue);
      expect(st.has(LotIssueKind.cost, b.key), isFalse);
      expect(st.has(LotIssueKind.cost, c.key), isTrue);
      expect(st.has(LotIssueKind.mismatch), isFalse);
    });
  });

  group('payloads', () {
    test('lotsPayload has the desktop shape {qty, batch_number?, expiry_date?}', () {
      final p = lotsPayload([
        d('2,5', exp: '2027-01-01', batch: ' B-7 '),
        d('1', exp: '2027-02-01'),
      ], trackExpiry: true);
      expect(jsonEncode(p),
          '[{"qty":2.5,"batch_number":"B-7","expiry_date":"2027-01-01"},{"qty":1,"expiry_date":"2027-02-01"}]');
      // Untracked expiry: the date is never sent even if typed.
      expect(lotsPayload([d('1', exp: '2027-01-01')], trackExpiry: false), [
        {'qty': 1}
      ]);
    });

    test('newLotsPayload uses the count contract {qty, unit_cost, batch_no?, expiry_date?}', () {
      expect(newLotsPayload([d('0,5', cost: '12 500,5', batch: 'X', exp: '2027-01-01')], trackExpiry: true), [
        {'qty': 0.5, 'unit_cost': 12500.5, 'batch_no': 'X', 'expiry_date': '2027-01-01'}
      ]);
    });

    test('lotSummary', () {
      expect(lotSummary([d('2', exp: '2027-01-01'), d('1')]), '2 + 1 · 01.01.2027');
    });
  });

  group('LotEditorController', () {
    test('a single automatic row follows the target until edited', () {
      final c = LotEditorController(trackExpiry: false, targetMilli: 3000);
      expect(c.rows.single.qty, '3');
      expect(c.autoFollowing, isTrue);
      c.targetMilli = 4500;
      expect(c.rows.single.qty, '4,5');
      c.update(c.rows.single.key, qty: '4');
      expect(c.autoFollowing, isFalse);
      c.targetMilli = 6000;
      expect(c.rows.single.qty, '4', reason: 'operator edit is never overwritten');
      c.dispose();
    });

    test('add / remove / fill remaining; 50 rows max', () {
      final c = LotEditorController(trackExpiry: false, targetMilli: 5000);
      c.update(c.rows.first.key, qty: '2');
      c.add();
      c.update(c.rows.last.key, qty: '1');
      expect(c.state.diffMilli, 2000);
      c.fillRemaining();
      expect(c.rows.last.qty, '3');
      expect(c.state.ok, isTrue);
      c.remove(c.rows.last.key);
      expect(c.rows, hasLength(1));
      c.remove(c.rows.first.key);
      expect(c.rows, hasLength(1), reason: 'at least one row stays');
      for (var i = 0; i < 60; i++) {
        c.add();
      }
      expect(c.rows, hasLength(kMaxLots));
      expect(c.canAdd, isFalse);
      c.dispose();
    });

    test('payload helpers on the controller', () {
      final c = LotEditorController(trackExpiry: true, targetMilli: 2000, businessDate: '2026-09-19');
      c.update(c.rows.first.key, expiry: '2026-12-31', batch: 'L1');
      expect(c.lotsPayload(), [
        {'qty': 2, 'batch_number': 'L1', 'expiry_date': '2026-12-31'}
      ]);
      c.dispose();
    });
  });

  group('LotEditor widget', () {
    setUp(() async => resetCore());

    Widget host(LotEditorController c, {String unit = 'kg'}) => Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(children: [LotEditor(controller: c, unit: unit), const SizedBox(height: 600)]),
          ),
        );

    testWidgets('typing updates the running sum; fill button appears and works', (tester) async {
      final c = LotEditorController(trackExpiry: false, targetMilli: 5000);
      await pumpAt390(tester, host(c));
      await tester.enterText(find.byKey(const Key('lot-qty-0')), '2');
      await tester.pump();
      expect(find.text('Partiyalar: 2 / 5 kg · yana 3 kerak'), findsOneWidget);
      await tester.tap(find.byKey(const Key('lot-add')));
      await tester.pump();
      expect(find.byKey(const Key('lot-row-1')), findsOneWidget);
      await tester.tap(find.byKey(const Key('lot-fill')));
      await tester.pump();
      expect(c.state.ok, isTrue);
      expect(find.text('Partiyalar: 5 / 5 kg'), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('lot-remove-0')));
      expectMinTouchTarget(tester, find.byKey(const Key('lot-add')));
    });

    testWidgets('validate() reveals missing expiry and focuses the first bad field', (tester) async {
      final c = LotEditorController(trackExpiry: true, targetMilli: 2000, businessDate: '2026-09-19');
      await pumpAt390(tester, host(c));
      expect(find.text('Yaroqlilik muddatini kiriting'), findsNothing, reason: 'not before a submit attempt');
      expect(find.byKey(const Key('lot-bizdate')), findsOneWidget);
      late bool ok;
      await tester.runAsync(() async => ok = c.validate());
      await tester.pumpAndSettle();
      expect(ok, isFalse);
      expect(find.text('Yaroqlilik muddatini kiriting'), findsOneWidget);
      expect(c.focusNode(c.rows.first.key, LotField.expiry).hasFocus, isTrue);
    });

    testWidgets('expiry picker refuses dates before the business date', (tester) async {
      final c = LotEditorController(trackExpiry: true, targetMilli: 1000, businessDate: '2026-09-19');
      await pumpAt390(tester, host(c));
      await tester.tap(find.byKey(const Key('lot-expiry-0')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('date-day-2026-09-10')));
      await tester.pumpAndSettle();
      expect(c.rows.first.expiry, isNull);
      await tester.tap(find.byKey(const Key('date-day-2026-09-30')));
      await tester.pumpAndSettle();
      expect(c.rows.first.expiry, '2026-09-30');
      expect(c.state.ok, isTrue);
    });

    testWidgets('>3 decimals cannot be typed; inline error for a zero qty', (tester) async {
      final c = LotEditorController(trackExpiry: false, targetMilli: 1000);
      await pumpAt390(tester, host(c));
      await tester.enterText(find.byKey(const Key('lot-qty-0')), '0,0001');
      await tester.pump();
      expect(c.rows.first.qty, isNot('0,0001'));
      await tester.enterText(find.byKey(const Key('lot-qty-0')), '0');
      await tester.pump();
      expect(find.text('Miqdor noldan katta bo‘lsin'), findsOneWidget);
    });

    testWidgets('count mode: cost field, no target, localized ky', (tester) async {
      L.code = 'ky';
      final c = LotEditorController(trackExpiry: false, hasTarget: false, withUnitCost: true, allowEmpty: true);
      await pumpAt390(tester, host(c, unit: 'dona'));
      expect(c.rows, isEmpty);
      await tester.tap(find.byKey(const Key('lot-add')));
      await tester.pump();
      await tester.enterText(find.byKey(const Key('lot-qty-0')), '3');
      await tester.enterText(find.byKey(const Key('lot-cost-0')), '0');
      await tester.pump();
      expect(c.state.ok, isTrue);
      expect(find.text('Жалпы: 3 dona'), findsOneWidget);
      expect(c.newLotsPayload(), [
        {'qty': 3, 'unit_cost': 0}
      ]);
    });
  });
}
