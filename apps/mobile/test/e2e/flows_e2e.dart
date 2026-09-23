// Phase 5G — mobile E2E against a REAL backend (Postgres) at 390×844.
//
// Run: `python e2e/mobile/run_e2e.py` (starts the backend, seeds the scenario
// tenant, runs this file, stops everything). See `e2e/mobile/README.md`.
//
// Every flow drives the real screens with the real `Api`, then checks what
// the SERVER holds through an independent session ([Probe]) — a green run
// means the write really happened (or, for negative flows, really did not).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/screens/inventory_screen.dart';
import 'package:savdoos_mobile/screens/money_payment_sheet.dart';
import 'package:savdoos_mobile/screens/receiving_home_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';

import '../support/pump.dart';
import 'harness.dart';

void main() {
  setUpAll(() async {
    Scenario.I; // no backend configured = hard failure, never a skip
    await loadPhoneFonts();
  });
  setUp(e2eReset);

  group('0. sign-in', () {
    e2eTest('login screen -> PIN setup -> shell with the server context (owner, 2 branches)', (t) async {
      final s = Scenario.I;
      Session.instance.attach(); // as main(): /auth/context after login
      await pumpApp(t);
      await waitFor(t, k('login-phone'));
      // Wrong password: the server's single answer, no session.
      await type(t, k('login-phone'), '${s.user('owner')['phone']}');
      await type(t, k('login-password'), 'not-the-password-123');
      await tap(t, k('login-submit'));
      await waitFor(t, k('login-error'));
      expect(textOf(t, k('login-error')), 'Telefon yoki parol noto‘g‘ri');
      expect(Api.loggedIn, isFalse);
      // Right password.
      await type(t, k('login-password'), s.password);
      await tap(t, k('login-submit'));
      await waitFor(t, find.text('PIN kod o‘rnating'));
      for (final d in [1, 2, 3, 4, 1, 2, 3, 4]) {
        await t.tap(find.text('$d').last);
        await t.pump();
      }
      await waitFor(t, k('tab-home'));
      await waitFor(t, k('branch-chip'));
      expect(Session.instance.status, SessionStatus.ready);
      expect(Session.instance.branches.map((b) => b.id).toSet(), {s.branchId('A'), s.branchId('B')});
      expect(Session.instance.actorBranch?.id, s.branchId('A'));
      expect(Session.instance.currentBranchId, s.branchId('A'), reason: 'default = actor branch, no guess');
      expect(find.descendant(of: k('branch-chip'), matching: find.text(s.branchName('A'))), findsOneWidget);
      // Owner (ega): every tab and the "+" sheet.
      for (final tab in ['home', 'analytics', 'stock', 'settings']) {
        expect(k('tab-$tab'), findsOneWidget, reason: tab);
      }
      expect(k('shell-amal'), findsOneWidget);
    });
  });

  group('1. barcode -> product', () {
    e2eTest('camera code -> server lookup -> product detail with its stock; scale label; unknown code', (t) async {
      final s = Scenario.I;
      // The owner sees every branch: the detail card shows the stock of all his branches.
      final total = await serverStock(t, 'plain', 'A') + await serverStock(t, 'plain', 'B');
      await signInAs(t, 'owner');
      await t.pumpWidget(testApp(Shell(tabBuilders: {
        ShellTab.stock: (_) => const InventoryScreen(scannerBuilder: E2ECamera.view),
      })));
      await settle(t);
      await tap(t, k('tab-stock'));
      await waitFor(t, k('stock-total'));
      await scrollTo(t, k('stock-row-${s.pid('plain')}'), within: k('stock-list'));

      // 1a. EAN barcode -> the product, stock of the current branch.
      E2ECamera.next = '${s.product('plain')['barcode']}';
      await tap(t, k('stock-scan'));
      await tap(t, k('e2e-detect'));
      await waitFor(t, k('pd-name'));
      expect(textOf(t, k('pd-name')), s.pname('plain'));
      await waitFor(t, k('pd-stock'));
      expect(textsUnder(k('pd-stock')), contains(qtyUnit((total * 1000).round(), 'dona')));
      expect(textsUnder(k('pd-stock')), contains('barcha filiallaringiz'), reason: 'aggregate is labelled');
      final scan = E2EClient.calls('GET', '/products/scan').last;
      expect(scan.url.queryParameters['code'], s.product('plain')['barcode']);
      expect(scan.url.queryParameters['branch_id'], s.branchId('A'));
      expect(scan.status, 200);
      await t.pageBack();
      await settle(t);

      // 1b. Weighed (scale) label: the SERVER parses PLU + grams.
      final sc = s.section('scale');
      E2ECamera.next = '${sc['code']}';
      await tap(t, k('stock-scan'));
      await tap(t, k('e2e-detect'));
      await waitFor(t, k('pd-name'));
      expect(textOf(t, k('pd-name')), s.pname('scale'));
      final scaleAns = E2EClient.calls('GET', '/products/scan').last;
      expect(scaleAns.response, contains('"kind":"scale"'));
      expect(scaleAns.response, contains('"qty":"${sc['qty']}"'));
      await t.pageBack();
      await settle(t);

      // 1c. Unknown code: explicit "not found", nothing opened.
      E2ECamera.next = '${s.raw['unknown_barcode']}';
      await tap(t, k('stock-scan'));
      await tap(t, k('e2e-detect'));
      await waitFor(t, k('scan-notfound-code'));
      expect(textOf(t, k('scan-notfound-code')), contains('${s.raw['unknown_barcode']}'));
      expect(k('pd-name'), findsNothing);
    });
  });

  group('2-3-7. receiving (tracked lots, expiry, cash account)', () {
    Future<void> openManualReceiving(WidgetTester t) async {
      await pumpApp(t);
      await tap(t, k('shell-amal'));
      await tap(t, k('amal-receiving'));
      await tap(t, k('recv-home-manual'));
      await waitFor(t, k('recv-add-line'));
      await waitFor(t, k('recv-branch'), reason: 'receiving branch shown explicitly');
    }

    /// Adds [key] through the editor's server search; leaves the editor open.
    Future<void> pickProduct(WidgetTester t, String key, String query, String qty) async {
      final s = Scenario.I;
      await tap(t, k('recv-add-line'));
      await type(t, k('recv-edit-name'), query);
      await waitFor(t, k('recv-sugg-${s.pid(key)}'));
      await tap(t, k('recv-sugg-${s.pid(key)}'));
      await waitFor(t, k('recv-edit-product'));
      await type(t, k('recv-edit-qty'), qty);
      await settle(t);
    }

    Map<String, dynamic> lastCommit() {
      final c = E2EClient.calls('POST', '/receiving/commit');
      expect(c, isNotEmpty, reason: 'a commit was sent');
      return c.last.json;
    }

    e2eTest('2. tracked product, two lots, credit: lots born on the server with the batch numbers', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A');
      final before = await serverLots(t, s.pid('lot'), a);
      await signInAs(t, 'omborchi');
      await openManualReceiving(t);
      expect(textsUnder(k('recv-branch')), contains(s.branchName('A')));

      await pickProduct(t, 'lot', 'Guruch', '5');
      await waitFor(t, k('recv-edit-lots'), reason: 'tracked product gets the lot editor');
      await tap(t, k('lot-add'));
      await type(t, k('lot-qty-0'), '3');
      await type(t, k('lot-batch-0'), '$runTag-A');
      await type(t, k('lot-qty-1'), '1');
      await type(t, k('lot-batch-1'), '$runTag-B');
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      // Σ lots (4) != line qty (5): the editor refuses, nothing leaves the phone.
      await waitFor(t, find.textContaining('yana 1 kerak'));
      expect(k('recv-edit-lots'), findsOneWidget);
      await type(t, k('lot-qty-1'), '2');
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      await waitGone(t, k('recv-edit-lots'));
      await waitFor(t, k('badge-tracked'));

      await tap(t, k('sticky-primary'));
      await tap(t, k('recv-pay-credit'));
      await tap(t, k('recv-submit-save'));
      await waitFor(t, k('recv-saved-title'));

      final body = lastCommit();
      expect(body['payment'], 'credit');
      expect(body.containsKey('cash_account_id'), isFalse, reason: 'credit never sends a cash account');
      final item = (body['items'] as List).single as Map;
      expect(item['product_id'], s.pid('lot'));
      expect(item['qty'], 5);
      expect(item['lots'], [
        {'qty': 3, 'batch_number': '$runTag-A'},
        {'qty': 2, 'batch_number': '$runTag-B'},
      ]);
      expect(E2EClient.calls('POST', '/receiving/commit').last.status, 200);
      expect(textOf(t, k('recv-saved-meta')), contains('KIR-'), reason: 'doc number shown after the 2xx');

      // Server truth: the two lots exist in branch A with the typed batch numbers.
      final after = await serverLots(t, s.pid('lot'), a);
      final lots = (after['lots'] as List).cast<Map>();
      final mine = {for (final l in lots) if ('${l['batch_number']}'.startsWith(runTag)) l['batch_number']: l};
      expect(mine.keys.toSet(), {'$runTag-A', '$runTag-B'});
      expect(mine['$runTag-A']!['remaining_qty'], 3);
      expect(mine['$runTag-B']!['remaining_qty'], 2);
      expect(mine['$runTag-A']!['source_type'], 'receiving');
      expect(after['inventory_qty'], (before['inventory_qty'] as num) + 5);
    });

    e2eTest('3+7. expiry lot (required, past refused) paid in CASH: exact till/safe options, no default', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A');
      await signInAs(t, 'omborchi');
      final biz = DateTime.parse(Session.instance.businessDate(a)!);
      final good = biz.add(const Duration(days: 45));
      final goodIso = good.toIso8601String().substring(0, 10);
      String ddmmyyyy(DateTime d) =>
          '${d.day.toString().padLeft(2, '0')}${d.month.toString().padLeft(2, '0')}${d.year}';
      await openManualReceiving(t);

      await pickProduct(t, 'expiry', 'Qatiq', '4');
      await waitFor(t, k('recv-edit-lots'));
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      await waitFor(t, find.text('Yaroqlilik muddatini kiriting'));
      expect(k('recv-edit-lots'), findsOneWidget, reason: 'still in the editor');

      // A date before the branch business date is refused by the picker itself.
      await tap(t, k('lot-expiry-0'));
      await t.enterText(k('date-typed'), ddmmyyyy(biz.subtract(const Duration(days: 1))));
      await t.pump();
      await tap(t, k('date-typed-ok'));
      await waitFor(t, find.textContaining('dan oldin bo‘lmasin'));
      await t.enterText(k('date-typed'), ddmmyyyy(good));
      await t.pump();
      await tap(t, k('date-typed-ok'));
      await waitGone(t, k('date-typed'));
      await type(t, k('lot-batch-0'), '$runTag-E');
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      await waitGone(t, k('recv-edit-lots'));

      // Cash: the server says OPERATOR_MUST_CHOOSE -> the EXACT options, nothing preselected.
      await tap(t, k('sticky-primary'));
      await tap(t, k('recv-pay-cash'));
      final till = s.account('till_a')['id'], safe = s.account('safe_a')['id'];
      await waitFor(t, k('custody-option-$till'));
      expect(k('custody-option-$safe'), findsOneWidget);
      for (final other in ['till_a_archived', 'till_b', 'safe_b']) {
        expect(k('custody-option-${s.account(other)['id']}'), findsNothing, reason: '$other must not be offered');
      }
      final preview = E2EClient.calls('GET', '/cash/custody-preview').last;
      expect(preview.url.queryParameters['operation'], 'receiving_payment');
      expect(preview.response, contains('"mode":"OPERATOR_MUST_CHOOSE"'));
      await tap(t, k('recv-submit-save'));
      await waitFor(t, k('custody-required'));
      expect(E2EClient.calls('POST', '/receiving/commit'), isEmpty, reason: 'no silent default account');

      await tap(t, k('custody-option-$safe'));
      await tap(t, k('recv-submit-save'));
      await waitFor(t, k('recv-saved-title'));
      final body = lastCommit();
      expect(body['payment'], 'cash');
      expect(body['cash_account_id'], safe);
      expect(((body['items'] as List).single as Map)['lots'], [
        {'qty': 4, 'batch_number': '$runTag-E', 'expiry_date': goodIso}
      ]);

      // Server truth: the lot carries the expiry; the purchase is a CASH document of branch A.
      final lots = ((await serverLots(t, s.pid('expiry'), a))['lots'] as List).cast<Map>();
      final lot = lots.singleWhere((l) => l['batch_number'] == '$runTag-E');
      expect(lot['expiry_date'], goodIso);
      expect(lot['remaining_qty'], 4);
      expect(lot['expired'], isFalse);
      final res = E2EClient.calls('POST', '/receiving/commit').last.response!;
      final purchaseId = RegExp(r'"purchase_id":"([^"]+)"').firstMatch(res)!.group(1)!;
      final pur = await probe(t, () => Probe.get('/purchases/$purchaseId')) as Map;
      expect(pur['payment'], 'cash');
      expect(pur['branch_id'], a);
    });
  });

  /// Opens a "+" action of the shell (the app root must be pumped).
  Future<void> openAction(WidgetTester t, String action) async {
    await pumpApp(t);
    await tap(t, k('shell-amal'));
    await tap(t, k('amal-$action'));
  }

  /// Picks the scenario product [key] in the server-backed picker sheet.
  Future<void> pickInSheet(WidgetTester t, String key, String query) async {
    final s = Scenario.I;
    await waitFor(t, k('picker-search'));
    await type(t, k('picker-search'), query);
    await waitFor(t, k('picker-row-${s.pid(key)}'));
    await tap(t, k('picker-row-${s.pid(key)}'));
  }

  Map<String, Map> byBatch(Map<String, dynamic> lots) =>
      {for (final l in (lots['lots'] as List).cast<Map>()) '${l['batch_number']}': l};

  group('4. count (lot-aware, Phase 4B contract)', () {
    e2eTest('untracked absolute count + tracked per-lot count (blank lot untouched), same branch', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A');
      final plainBefore = await serverStock(t, 'count_plain', 'A');
      final lotsBefore = byBatch(await serverLots(t, s.pid('count_lot'), a));
      final y1 = lotsBefore['E2E-Y-1']!, y2 = lotsBefore['E2E-Y-2']!;
      final y1Counted = (y1['remaining_qty'] as num).toInt() - 1;
      final plainCounted = plainBefore.toInt() + 2;
      await signInAs(t, 'omborchi');
      await openAction(t, 'count');

      // Untracked: absolute counted quantity.
      await tap(t, k('cnt-add'));
      await pickInSheet(t, 'count_plain', 'Tuz');
      await type(t, k('cnt-plain-qty'), '$plainCounted');
      await tap(t, k('cnt-plain-save'));
      await waitFor(t, k('cnt-item-${s.pid('count_plain')}'));

      // Tracked: count ONE lot, leave the other blank (= untouched, not zero).
      await tap(t, k('cnt-add'));
      await pickInSheet(t, 'count_lot', 'Yog');
      await waitFor(t, k('lotcnt-qty-${y1['id']}'));
      expect(k('lotcnt-qty-${y2['id']}'), findsOneWidget);
      await type(t, k('lotcnt-qty-${y1['id']}'), '$y1Counted');
      await unfocus(t);
      await settle(t);
      await tap(t, k('sticky-primary'));
      await waitFor(t, k('cnt-item-${s.pid('count_lot')}'));

      await tap(t, k('sticky-primary'));
      await tap(t, k('confirm-yes'));
      await waitFor(t, k('cnt-changed'));
      expect(k('cnt-dec-${y1['id']}'), findsOneWidget, reason: 'server per-lot result shown');

      final post = E2EClient.calls('POST', '/inventory/count').single;
      expect(post.status, 200);
      final body = post.json;
      expect(body['branch_id'], a, reason: 'same branch as the lot read');
      final lotReads = E2EClient.calls('GET', '/lots/products/${s.pid('count_lot')}');
      expect(lotReads.map((c) => c.url.queryParameters['branch_id']).toSet(), {a});
      expect(body['items'], [
        {'product_id': s.pid('count_plain'), 'counted': plainCounted},
        {
          'product_id': s.pid('count_lot'),
          'counted': y1Counted + (y2['remaining_qty'] as num).toInt(),
          'lots': [
            {'stock_batch_id': y1['id'], 'counted': y1Counted}
          ],
          'new_lots': <Object>[],
        },
      ]);

      // Server truth.
      expect(await serverStock(t, 'count_plain', 'A'), plainCounted);
      final after = byBatch(await serverLots(t, s.pid('count_lot'), a));
      expect(after['E2E-Y-1']!['remaining_qty'], y1Counted);
      expect(after['E2E-Y-2']!['remaining_qty'], y2['remaining_qty'], reason: 'blank lot untouched');
    });
  });

  group('5. write-off (per lot, FEFO)', () {
    e2eTest('tracked: per-lot quantities, reason, cost shown; lots decremented on the server', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A');
      final before = byBatch(await serverLots(t, s.pid('wo_lot'), a));
      final k1 = before['E2E-K-1']!, k2 = before['E2E-K-2']!;
      await signInAs(t, 'omborchi');
      await openAction(t, 'writeoff');
      await tap(t, k('wo-pick'));
      await pickInSheet(t, 'wo_lot', 'Kefir');
      await waitFor(t, k('wo-lot-qty-${k1['id']}'));
      // FEFO: the lot expiring first is listed first.
      expect(t.getTopLeft(k('lot-card-${k1['id']}')).dy, lessThan(t.getTopLeft(k('lot-card-${k2['id']}')).dy));
      await type(t, k('wo-lot-qty-${k1['id']}'), '1');
      await type(t, k('wo-lot-qty-${k2['id']}'), '2');
      await unfocus(t);
      await tap(t, k('wo-reason-damaged'));
      await type(t, k('wo-note'), 'E2E $runTag');
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      await tap(t, k('confirm-yes'));
      await waitFor(t, k('wo-done'));
      await waitFor(t, k('wo-cost'));
      expect(textOf(t, k('wo-cost')), contains('24'), reason: '1×8 000 + 2×8 000 = 24 000');

      final post = E2EClient.calls('POST', '/inventory/writeoff').single;
      expect(post.status, 200);
      expect(post.json['branch_id'], a);
      expect(post.json['qty'], 3);
      expect(post.json['reason'], 'damaged: E2E $runTag');
      expect(post.json['lots'], [
        {'stock_batch_id': k1['id'], 'qty': 1},
        {'stock_batch_id': k2['id'], 'qty': 2},
      ]);
      final after = byBatch(await serverLots(t, s.pid('wo_lot'), a));
      expect(after['E2E-K-1']!['remaining_qty'], (k1['remaining_qty'] as num) - 1);
      expect(after['E2E-K-2']!['remaining_qty'], (k2['remaining_qty'] as num) - 2);
    });
  });

  group('6. correction of a receiving (cash document)', () {
    e2eTest('history -> detail -> purchase -> reverse 2 of the lot, cash back to a CHOSEN account', (t) async {
      final s = Scenario.I;
      final c = s.section('correction');
      final purchaseId = '${c['purchase_id']}';
      final lotId = '${c['lot_id']}';
      final purBefore = await probe(t, () => Probe.get('/purchases/$purchaseId')) as Map;
      final lotBefore = byBatch(await serverLots(t, s.pid('corr'), s.branchId('A')))['${c['batch']}']!;
      final nCorr = (purBefore['corrections'] as List).length;
      await signInAs(t, 'owner');
      await openAction(t, 'receiving');
      await scrollTo(t, k('recv-history-${c['receiving_id']}'), within: find.byType(ReceivingHomeScreen));
      await tap(t, k('recv-history-${c['receiving_id']}'));
      await waitFor(t, k('recv-detail-docno'));
      expect(textOf(t, k('recv-detail-docno')), '${c['doc_no']}');
      await tap(t, k('recv-detail-open-purchase'));
      await waitFor(t, k('pd-lot-$lotId'));
      await tap(t, find.descendant(of: k('pd-bar'), matching: k('sticky-primary')));

      // Editor: reason + reverse 2 of the lot.
      await waitFor(t, k('corr-rev-$lotId'));
      await type(t, k('corr-reason'), 'E2E $runTag: nakladnoyda 2 ta kam');
      await type(t, k('corr-rev-$lotId'), '2');
      await unfocus(t);
      await settle(t);
      final till = '${s.account('till_a')['id']}', safe = '${s.account('safe_a')['id']}';
      // Money goes back to the cash: the server's block says OPERATOR_MUST_CHOOSE.
      await scrollTo(t, k('custody-option-$till'), within: k('corr-list'));
      expect(k('custody-option-$safe'), findsOneWidget);
      expect(k('custody-option-${s.account('till_a_archived')['id']}'), findsNothing);
      final bar = find.descendant(of: k('corr-bar'), matching: k('sticky-primary'));
      expect(t.widget<ElevatedButton>(bar).onPressed, isNull, reason: 'no account chosen yet');
      await scrollTo(t, k('corr-money-line'), within: k('corr-list'));
      expect(textOf(t, k('corr-money-line')), startsWith('Kassaga qaytadi: 10'));
      await scrollTo(t, k('custody-option-$till'), within: k('corr-list'));
      await tap(t, k('custody-option-$till'));
      await tap(t, bar);
      await tap(t, k('confirm-ack'));
      await tap(t, k('confirm-yes'));
      await waitFor(t, k('pd-notice'));

      final post = E2EClient.calls('POST', '/receiving/${c['receiving_id']}/corrections').single;
      expect(post.status, 200, reason: post.response);
      expect(post.json['cash_account_id'], till);
      expect(post.json['lines'], [
        {
          'purchase_item_id': ((purBefore['items'] as List).single as Map)['id'],
          'reverse': [
            {'stock_batch_id': lotId, 'qty': 2}
          ]
        }
      ]);
      // Server truth: one more correction, the lot and the document total went down.
      final purAfter = await probe(t, () => Probe.get('/purchases/$purchaseId')) as Map;
      expect((purAfter['corrections'] as List).length, nCorr + 1);
      expect((purAfter['total'] as num), (purBefore['total'] as num) - 2 * (c['unit_cost'] as num));
      final lotAfter = byBatch(await serverLots(t, s.pid('corr'), s.branchId('A')))['${c['batch']}']!;
      expect(lotAfter['remaining_qty'], (lotBefore['remaining_qty'] as num) - 2);
    });
  });

  group('8. customer debt payment', () {
    e2eTest('debtors -> profile -> cash payment: account must be chosen; balance goes down on the server', (t) async {
      final s = Scenario.I;
      final d = s.section('customers')['debtor'] as Map;
      final before = await probe(t, () => Probe.get('/customers/${d['id']}')) as Map;
      final bal = (before['credit_balance'] as num).toInt();
      await signInAs(t, 'owner');
      await pumpApp(t);
      await tap(t, find.text('Qarzdorlar'));
      await waitFor(t, k('customer-${d['id']}'));
      await tap(t, k('customer-${d['id']}'));
      await waitFor(t, k('customer-balance'));
      await tap(t, find.descendant(of: k('customer-pay-bar'), matching: k('sticky-primary')));
      await waitFor(t, k('pay-amount'));
      await type(t, k('pay-amount'), '20000');
      await unfocus(t);
      final safe = '${s.account('safe_a')['id']}';
      await waitFor(t, k('custody-option-$safe'));
      expect(k('custody-option-${s.account('till_a')['id']}'), findsOneWidget);
      expect(E2EClient.calls('GET', '/cash/custody-preview').last.url.queryParameters['operation'], 'debt_payment');
      final confirm = find.descendant(of: find.byType(MoneyPaymentSheet), matching: k('sticky-primary'));
      await tap(t, confirm);
      await waitFor(t, k('custody-required'));
      expect(E2EClient.calls('POST', '/customers/${d['id']}/payments'), isEmpty, reason: 'no default account');
      await tap(t, k('custody-option-$safe'));
      await tap(t, confirm);
      await waitFor(t, k('customer-notice'));

      final post = E2EClient.calls('POST', '/customers/${d['id']}/payments').single;
      expect(post.status, 200);
      expect(post.json['method'], 'cash');
      expect(post.json['cash_account_id'], safe);
      expect(post.json['amount'], 20000);
      final after = await probe(t, () => Probe.get('/customers/${d['id']}')) as Map;
      expect((after['credit_balance'] as num).toInt(), bal - 20000);
    });
  });

  group('9. branch isolation', () {
    e2eTest('owner switches A -> B: list, stock and lots are B-only; A data never shown under B', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A'), b = s.branchId('B');
      final bLots = byBatch(await serverLots(t, s.pid('lot'), b));
      final aLots = byBatch(await serverLots(t, s.pid('lot'), a));
      expect(bLots.keys, contains('E2E-G-B1'));
      expect(bLots.keys.toSet().intersection(aLots.keys.toSet()), isEmpty, reason: 'lots are per branch on the server');
      await signInAs(t, 'owner');
      await pumpApp(t);
      await tap(t, k('tab-stock'));
      final bOnly = k('stock-row-${s.pid('b_only')}');
      await waitFor(t, bOnly);
      expect(textsUnder(bOnly), contains('Tugagan'), reason: 'A has none of it');
      expect(E2EClient.calls('GET', '/products').last.url.queryParameters['branch_id'], a);

      await tap(t, k('branch-chip'));
      await tap(t, k('branch-option-$b'));
      await waitFor(t, find.descendant(of: k('branch-chip'), matching: find.text(s.branchName('B'))));
      await waitFor(t, bOnly);
      expect(Session.instance.currentBranchId, b);
      expect(E2EClient.calls('GET', '/products').last.url.queryParameters['branch_id'], b);
      expect(textsUnder(bOnly), isNot(contains('Tugagan')));
      expect(textsUnder(bOnly), contains('7'));
      // The lot product under B: B's lot only, A's lots never shown.
      final b1 = bLots['E2E-G-B1']!;
      await tap(t, k('stock-row-${s.pid('lot')}'));
      await waitFor(t, k('lot-card-${b1['id']}'));
      for (final l in aLots.values) {
        expect(k('lot-card-${l['id']}'), findsNothing, reason: 'A lot ${l['batch_number']} under B');
      }
      expect(textOf(t, k('pd-branch-stock')),
          contains(qtyUnit(((b1['remaining_qty'] as num) * 1000).round(), 'dona')));
      expect(E2EClient.calls('GET', '/lots/products/${s.pid('lot')}').last.url.queryParameters['branch_id'], b);
    });

    e2eTest('a B-assigned employee sees only B; foreign-branch reads are refused by the server', (t) async {
      final s = Scenario.I;
      final a = s.branchId('A'), b = s.branchId('B');
      await signInAs(t, 'omborchi_b');
      expect(Session.instance.branches.map((x) => x.id), [b]);
      expect(Session.instance.actorBranch?.id, b);
      expect(Session.instance.currentBranchId, b);
      expect(Session.instance.selectableBranches.map((x) => x.id), [b], reason: 'nothing to switch to');
      await pumpApp(t);
      await tap(t, k('tab-stock'));
      await waitFor(t, k('stock-row-${s.pid('b_only')}'));
      expect(E2EClient.calls('GET', '/products').last.url.queryParameters['branch_id'], b);

      // Server: branch A is not this employee's — refused, not an empty 200.
      final e1 = await probeError(t, () => Probe.get('/products', who: 'omborchi_b', query: {'branch_id': a, 'limit': '5'}));
      expect(e1?.status, 403);
      final e2 = await probeError(
          t, () => Probe.get('/lots/products/${s.pid('lot')}', who: 'omborchi', query: {'branch_id': b}));
      expect(e2?.status, 404, reason: 'an A-assigned employee cannot read B lots (same answer as a foreign branch)');
    });
  });

  group('10. permission negative', () {
    e2eTest('kassir: no stock/analytics/actions; write-off screen explains; server says 403 PERMISSION_DENIED',
        (t) async {
      final s = Scenario.I;
      final stockBefore = await serverStock(t, 'plain', 'A');
      await signInAs(t, 'kassir');
      await pumpApp(t);
      await waitFor(t, k('tab-home'));
      expect(k('tab-settings'), findsOneWidget);
      expect(k('tab-stock'), findsNothing);
      expect(k('tab-analytics'), findsNothing);
      expect(k('shell-amal'), findsNothing, reason: 'no operation is allowed');

      await pumpScreen(t, const WriteoffScreen());
      await waitFor(t, k('wo-denied'));
      expect(t.widget<ElevatedButton>(k('sticky-primary')).onPressed, isNull);
      expect(E2EClient.calls('POST', '/inventory/writeoff'), isEmpty);

      // The server is the authority: a crafted request is refused with the stable code.
      final wo = await probeError(
          t,
          () => Probe.post('/inventory/writeoff', {
                'product_id': s.pid('plain'),
                'qty': 1,
                'reason': 'damaged',
                'branch_id': s.branchId('A'),
                'client_uuid': Api.newUuid(),
              }, who: 'kassir'));
      expect(wo?.status, 403);
      expect(wo?.code, 'PERMISSION_DENIED');
      final rc = await probeError(
          t,
          () => Probe.post('/receiving/commit', {
                'items': [
                  {'product_id': s.pid('plain'), 'qty': 1, 'unit_cost': 1}
                ],
                'payment': 'credit',
                'client_uuid': Api.newUuid(),
              }, who: 'kassir'));
      expect(rc?.status, 403);
      expect(rc?.code, 'PERMISSION_DENIED');
      expect(await serverStock(t, 'plain', 'A'), stockBefore, reason: 'nothing was written');
    });

    e2eTest('menejer: receiving hidden (no xaridlar.*); server refuses the commit', (t) async {
      final s = Scenario.I;
      await signInAs(t, 'menejer');
      await pumpScreen(t, const ReceivingHomeScreen());
      await waitFor(t, k('recv-home-no-edit'));
      expect(k('recv-home-manual'), findsNothing);
      expect(k('recv-home-camera'), findsNothing);
      expect(E2EClient.calls('GET', '/receiving'), isEmpty, reason: 'no history request without xaridlar.view');
      final rc = await probeError(
          t,
          () => Probe.post('/receiving/commit', {
                'items': [
                  {'product_id': s.pid('plain'), 'qty': 1, 'unit_cost': 1}
                ],
                'payment': 'credit',
                'client_uuid': Api.newUuid(),
              }, who: 'menejer'));
      expect(rc?.status, 403);
      expect(rc?.code, 'PERMISSION_DENIED');
    });
  });

  group('connectivity', () {
    e2eTest('server unreachable: explicit error, never "success"; retry reuses client_uuid; written ONCE', (t) async {
      final before = await serverStock(t, 'plain', 'A');
      await signInAs(t, 'omborchi');
      await openAction(t, 'writeoff');
      await tap(t, k('wo-pick'));
      await pickInSheet(t, 'plain', 'Shakar');
      await type(t, k('wo-qty'), '1');
      await unfocus(t);
      await tap(t, k('wo-reason-damaged'));

      Api.baseUrl = kDeadBase; // the server "disappears"
      await tap(t, k('sticky-primary'));
      await tap(t, k('confirm-yes'));
      await waitFor(t, k('wo-error'));
      expect(k('wo-done'), findsNothing, reason: 'a network failure is never shown as success');
      expect(find.textContaining('ikki marta yozilmaydi'), findsOneWidget);
      expect(Api.online.value, isFalse);
      final failed = E2EClient.calls('POST', '/inventory/writeoff');
      expect(failed.single.error, isNotNull);
      expect(failed.single.status, isNull);
      expect(await serverStock(t, 'plain', 'A'), before, reason: 'nothing reached the server');

      Api.baseUrl = kE2EBase; // back online
      await tap(t, k('sticky-primary'));
      await tap(t, k('confirm-yes'));
      await waitFor(t, k('wo-done'));
      final posts = E2EClient.calls('POST', '/inventory/writeoff');
      expect(posts, hasLength(2));
      expect(posts[1].status, 200);
      expect(posts[1].json['client_uuid'], posts[0].json['client_uuid'], reason: 'same draft, same idempotency key');
      expect(Api.online.value, isTrue);
      expect(await serverStock(t, 'plain', 'A'), before - 1, reason: 'written exactly once');
    });

    e2eTest('answer lost AFTER the server wrote the receiving: retry = same uuid -> "already saved", written ONCE',
        (t) async {
      final s = Scenario.I;
      final before = await serverStock(t, 'plain', 'A');
      await signInAs(t, 'omborchi');
      await pumpApp(t);
      await tap(t, k('shell-amal'));
      await tap(t, k('amal-receiving'));
      await tap(t, k('recv-home-manual'));
      await tap(t, k('recv-add-line'));
      await type(t, k('recv-edit-name'), 'Shakar');
      await tap(t, k('recv-sugg-${s.pid('plain')}'));
      await type(t, k('recv-edit-qty'), '2');
      await unfocus(t);
      await tap(t, k('sticky-primary'));
      await waitGone(t, k('recv-edit-product'));
      await tap(t, k('sticky-primary'));
      await tap(t, k('recv-pay-credit'));

      E2EClient.loseNextAnswer('POST', '/receiving/commit');
      await tap(t, k('recv-submit-save'));
      await waitFor(t, k('recv-submit-error'));
      expect(k('recv-saved-title'), findsNothing, reason: 'outcome unknown is not success');
      expect(k('recv-submit-safe-retry'), findsOneWidget, reason: 'the operator is told a retry is safe');
      final first = E2EClient.calls('POST', '/receiving/commit').single;
      expect(first.answerLost, isTrue);
      expect(first.status, 200, reason: 'the server DID write it');
      expect(await serverStock(t, 'plain', 'A'), before + 2);

      await tap(t, k('recv-submit-save'));
      await waitFor(t, k('recv-duplicate-title'));
      expect(k('recv-saved-title'), findsNothing);
      final posts = E2EClient.calls('POST', '/receiving/commit');
      expect(posts, hasLength(2));
      expect(posts[1].json['client_uuid'], posts[0].json['client_uuid']);
      expect(posts[1].response, contains('"duplicate":true'));
      expect(await serverStock(t, 'plain', 'A'), before + 2, reason: 'the retry did not receive a second time');
    });

    e2eTest('login while the server is unreachable: connectivity message, not "wrong password"', (t) async {
      final s = Scenario.I;
      Api.baseUrl = kDeadBase;
      await pumpApp(t);
      await type(t, k('login-phone'), '${s.user('owner')['phone']}');
      await type(t, k('login-password'), s.password);
      await tap(t, k('login-submit'));
      await waitFor(t, k('login-error'));
      expect(textOf(t, k('login-error')), isNot('Telefon yoki parol noto‘g‘ri'));
      expect(textOf(t, k('login-error')), contains('aloqa'));
      expect(Api.loggedIn, isFalse);
    });
  });
}
