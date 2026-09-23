// Receiving (M1) — draft model, pre-validation and payload shape.
//
// The payload shape is the desktop `FullReceiving.save` / `LotReceivingEditor
// .lotsPayload` contract (`POST /receiving/commit`); untracked lines must stay
// byte-for-byte the legacy payload (no `lots` key).
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/widgets/lot_editor.dart';

import 'support/support.dart';

RecvProduct prod(String id, String name,
        {bool tracked = false, bool expiry = false, String? unit = 'dona', int? buyCents}) =>
    RecvProduct(id: id, name: name, trackLots: tracked, trackExpiry: expiry, unitCode: unit, buyCents: buyCents);

RecvLine existing(RecvProduct p, {String qty = '5', String cost = '1000'}) {
  final l = RecvLine(qtyText: qty, costText: cost);
  l.setProduct(p);
  return l;
}

void main() {
  setUp(() async {
    await resetCore();
    ReceivingApi.debugReset();
  });
  tearDown(() => Session.instance.debugReset());

  group('payload', () {
    test('untracked existing line: legacy keys only, no lots, server picks the unit', () {
      final l = existing(prod('p1', 'Sut'), qty: '2,5', cost: '12 500,5');
      final item = commitItem(l);
      expect(item.containsKey('lots'), isFalse);
      expect(item, {
        'product_id': 'p1',
        'new_name': null,
        'new_sell_price': null,
        'new_category_id': null,
        'new_barcode': null,
        'new_plu': null,
        'new_is_weighted': null,
        'new_min_qty': null,
        'qty': 2.5,
        'unit_cost': 12500.5,
        'ai_name': null,
        'unit': null,
      });
      expect(lineIssues(l), isEmpty);
    });

    test('new product: dona needs a 6..14 digit barcode, kg a 1..5 digit PLU', () {
      final d = RecvLine(newName: 'Yangi non', unit: 'dona', barcode: '4780001234567', qtyText: '10', costText: '3000',
          sellText: '4000', minText: '2', categoryId: 'c1');
      expect(lineIssues(d), isEmpty);
      final item = commitItem(d);
      expect(item['product_id'], isNull);
      expect(item['new_name'], 'Yangi non');
      expect(item['new_barcode'], '4780001234567');
      expect(item['new_plu'], isNull);
      expect(item['new_is_weighted'], false);
      expect(item['new_sell_price'], 4000);
      expect(item['new_min_qty'], 2);
      expect(item['new_category_id'], 'c1');
      expect(item['unit'], 'dona');

      final kg = RecvLine(newName: 'Go‘sht', unit: 'kg', plu: '0412', barcode: '999999', qtyText: '1,25', costText: '90000');
      expect(lineIssues(kg), isEmpty);
      final k = commitItem(kg);
      expect(k['new_plu'], '0412');
      expect(k['new_barcode'], isNull, reason: 'kg products are sold by PLU');
      expect(k['new_is_weighted'], true);
      expect(k['qty'], 1.25);

      expect(lineIssues(RecvLine(newName: 'X', barcode: '12345', qtyText: '1')).map((i) => i.kind),
          contains(RecvIssueKind.barcode));
      expect(lineIssues(RecvLine(newName: 'X', barcode: '', qtyText: '1')).map((i) => i.kind), contains(RecvIssueKind.barcode));
      expect(lineIssues(RecvLine(newName: 'X', unit: 'kg', plu: '123456', qtyText: '1')).map((i) => i.kind),
          contains(RecvIssueKind.plu));
      expect(isValidBarcode('000123'), isTrue, reason: 'leading zeros are kept');
      expect(isValidBarcode('123456789012345'), isFalse);
    });

    test('tracked single lot: one row follows the line qty; qty rebuilt from milli', () {
      final l = existing(prod('t1', 'Kefir', tracked: true), qty: '5', cost: '8000');
      expect(l.lots, isNotNull);
      expect(l.lots!.autoFollowing, isTrue);
      l.setQtyText('7,5');
      expect(l.lots!.rows.single.qty, '7,5');
      expect(lineIssues(l), isEmpty);
      final item = commitItem(l);
      expect(item['qty'], 7.5);
      expect(item['lots'], [
        {'qty': 7.5}
      ]);
    });

    test('tracked multi lot with expiry: desktop shape, sum == qty, expiry only when tracked', () {
      final l = existing(prod('t2', 'Yogurt', tracked: true, expiry: true), qty: '5', cost: '9000');
      final c = l.lots!;
      c.businessDate = '2026-09-19';
      c.update(c.rows.first.key, qty: '3', expiry: '2026-12-31', batch: 'A-1');
      c.add();
      c.update(c.rows.last.key, qty: '2', expiry: '2027-01-15');
      expect(lineIssues(l), isEmpty);
      expect(jsonEncode(commitItem(l)['lots']),
          '[{"qty":3,"batch_number":"A-1","expiry_date":"2026-12-31"},{"qty":2,"expiry_date":"2027-01-15"}]');
    });

    test('expiry required / past business date / sum mismatch / 3 decimals', () {
      final l = existing(prod('t3', 'Tvorog', tracked: true, expiry: true), qty: '4', cost: '5000');
      final c = l.lots!..businessDate = '2026-09-19';
      expect(lineIssues(l).single.kind, RecvIssueKind.lots);
      expect(lineIssues(l).single.message, 'Har partiyaga yaroqlilik muddatini kiriting');

      c.update(c.rows.first.key, expiry: '2026-09-18');
      expect(lineIssues(l).single.message, 'Muddat 19.09.2026 dan oldin bo‘lishi mumkin emas');
      c.update(c.rows.first.key, expiry: '2026-09-19');
      expect(lineIssues(l), isEmpty, reason: 'expiry == business date is allowed');

      c.update(c.rows.first.key, qty: '3');
      expect(lineIssues(l).single.message, 'Partiyalar yig‘indisi qator miqdoridan 1 kam');
      c.update(c.rows.first.key, qty: '4,5');
      expect(lineIssues(l).single.message, 'Partiyalar yig‘indisi qator miqdoridan 0,5 ortiq');

      c.update(c.rows.first.key, qty: '1,2345');
      expect(lineIssues(l).single.message, 'Ko‘pi bilan 3 ta kasr xona (0,001)');

      l.setQtyText('1,2345');
      expect(lineIssues(l).map((i) => i.kind), [RecvIssueKind.qty], reason: 'line qty >3 decimals is refused, not rounded');
    });

    test('float-free: 0,1 + 0,2 lots == 0,3 line', () {
      final l = existing(prod('t4', 'Ziravor', tracked: true), qty: '0,3', cost: '100');
      final c = l.lots!;
      c.update(c.rows.first.key, qty: '0,1');
      c.add();
      c.update(c.rows.last.key, qty: '0,2');
      expect(lineIssues(l), isEmpty);
      expect(commitItem(l)['qty'], 0.3);
    });

    test('tracked lines need cost > 0; untracked may be 0', () {
      final t = existing(prod('t5', 'Pishloq', tracked: true), cost: '0');
      expect(lineIssues(t).single.kind, RecvIssueKind.cost);
      final u = existing(prod('u5', 'Tuz'), cost: '');
      expect(lineIssues(u), isEmpty);
      expect(commitItem(u)['unit_cost'], 0);
    });

    test('a NEW product named like a tracked product is refused (server dedup would hit it)', () {
      final cat = TrackedCatalog([prod('t6', 'Sut 1L', tracked: true)]);
      final l = RecvLine(newName: '  sut 1l ', barcode: '4780000000001', qtyText: '1');
      final issues = lineIssues(l, tracked: cat);
      expect(issues.map((i) => i.kind), contains(RecvIssueKind.trackedName));
      expect(issues.first.message, contains('«Sut 1L»'));
      expect(lineIssues(RecvLine(newName: 'Sut 2L', barcode: '4780000000001', qtyText: '1'), tracked: cat), isEmpty);
    });

    test('document: two new products with the same barcode / PLU (leading zeros) are refused', () {
      final a = RecvLine(newName: 'A', barcode: '4780000000001', qtyText: '1');
      final b = RecvLine(newName: 'B', barcode: '4780000000001', qtyText: '1');
      expect(documentIssues([a, b]), hasLength(1));
      final c = RecvLine(newName: 'C', unit: 'kg', plu: '12', qtyText: '1');
      final d = RecvLine(newName: 'D', unit: 'kg', plu: '012', qtyText: '1');
      expect(documentIssues([c, d]).single, contains('PLU'));
      expect(documentIssues([a, c]), isEmpty);
    });

    test('commitBody: cash_account_id only when given, manual ai_raw is empty', () {
      final l = existing(prod('p1', 'Sut'));
      final manual = commitBody(lines: [l], clientUuid: 'u-1', payment: 'credit', source: 'manual', aiRaw: const ['x']);
      expect(manual['client_uuid'], 'u-1');
      expect(manual['payment'], 'credit');
      expect(manual['ai_raw'], isEmpty);
      expect(manual.containsKey('cash_account_id'), isFalse);
      final cash = commitBody(
          lines: [l], clientUuid: 'u-1', payment: 'cash', source: 'ai', supplierId: 's1', cashAccountId: 'acc', aiRaw: const ['x']);
      expect(cash['cash_account_id'], 'acc');
      expect(cash['supplier_id'], 's1');
      expect(cash['ai_raw'], ['x']);
    });
  });

  group('AI lines and cloning', () {
    test('AI line: matched product gets tracking from the catalog; quantities are never rounded', () {
      final cat = TrackedCatalog([prod('t1', 'Kefir 1L', tracked: true, expiry: true)]);
      final a = RecvLine.fromAi(
          const AiItem(aiName: 'KEFIR 1l', qty: 12.0, productId: 't1', matchedName: 'Kefir 1L', confidence: 0.7, unitCost: 8500),
          cat);
      expect(a.tracked, isTrue);
      expect(a.trackExpiry, isTrue);
      expect(a.qtyText, '12');
      expect(a.costText, '8500');
      expect(a.lots!.rows.single.qty, '12');
      expect(commitItem(a)['ai_name'], 'KEFIR 1l');
      expect(commitItem(a)['unit'], isNull, reason: 'the AI unit is not the product unit');

      final b = RecvLine.fromAi(const AiItem(aiName: 'Noma’lum', qty: 1.2345), cat);
      expect(b.unmatched, isTrue);
      expect(b.qtyText, '1,2345', reason: '4 decimals are shown, not rounded');
      expect(lineIssues(b).single.kind, RecvIssueKind.unmatched);
      expect(qtyTextFromServer(0.1 + 0.2), '0,30000000000000004');
      expect(qtyTextFromServer('2.500'), '2,5');
      expect(moneyTextFromServer(12500.5), '12500,50');
    });

    test('clone keeps the automatic lot row automatic and copies manual rows', () {
      final l = existing(prod('t1', 'Kefir', tracked: true, expiry: true), qty: '4');
      l.lots!.update(l.lots!.rows.first.key, expiry: '2027-01-01', batch: 'B1');
      final c = l.clone();
      expect(c.lots!.autoFollowing, isTrue);
      c.setQtyText('6');
      expect(c.lots!.rows.single.qty, '6');
      expect(c.lots!.rows.single.expiry, '2027-01-01');
      expect(l.lots!.rows.single.qty, '4', reason: 'the original is untouched');
      l.lots!.add();
      final c2 = l.clone();
      expect(c2.lots!.rows, hasLength(2));
      expect(c2.lots!.autoFollowing, isFalse);
      for (final x in [l, c, c2]) {
        x.dispose();
      }
    });

    test('setProduct(untracked) drops the lot editor', () {
      final l = existing(prod('t1', 'Kefir', tracked: true));
      expect(l.lots, isNotNull);
      l.setProduct(prod('u1', 'Tuz'));
      expect(l.lots, isNull);
      expect(commitItem(l).containsKey('lots'), isFalse);
    });
  });

  group('server answers', () {
    test('commit result: full answer and duplicate answer', () {
      final ok = CommitResult.fromJson(const {
        'ok': true,
        'receiving_id': 'r1',
        'purchase_id': 'p1',
        'doc_no': 'KIR-7',
        'results': [
          {'product': 'Sut', 'old_qty': 1.5, 'added': 2, 'new_qty': 3.5, 'unit': 'litr'}
        ],
        'payment': 'credit',
        'supplier': 'Nestle',
        'total_types': 1,
        'total_qty': 2,
      });
      expect(ok.duplicate, isFalse);
      expect(ok.docNo, 'KIR-7');
      expect(ok.results.single.newMilli, 3500);
      expect(ok.payment, RecvPayment.credit);
      final dup = CommitResult.fromJson(const {'ok': true, 'receiving_id': 'r1', 'duplicate': true});
      expect(dup.duplicate, isTrue);
      expect(dup.results, isEmpty);
      expect(() => CommitResult.fromJson(const {'ok': true}), throwsA(isA<ApiException>()));
    });

    test('history / detail parsing', () {
      final d = ReceivingDetail.fromJson(const {
        'id': 'r1',
        'at': '2026-09-19 08:00:00',
        'source': 'manual',
        'employee': 'Ali',
        'total_types': 2,
        'total_qty': 3.5,
        'items': [
          {'product_id': 'p1', 'name': 'Sut', 'qty': 2, 'unit_cost': 1000.5, 'unit': 'litr'},
          {'product_id': 'p2', 'name': 'Non', 'qty': 1.5, 'unit_cost': 3000, 'ai_name': 'NON'},
        ],
        'purchase_id': 'pu1',
        'doc_no': 'KIR-1',
        'payment': 'cash',
        'supplier': 'Qabul (mobil)',
        'purchase_status': 'received',
        'branch_id': 'b1',
        'branch_name': 'Markaz',
      });
      expect(d.doc.purchaseId, 'pu1');
      expect(d.doc.payment, RecvPayment.cash);
      expect(d.items.first.totalCents, 200100);
      expect(d.totalCents, 200100 + 450000);
      expect(d.doc.cancelled, isFalse);
      expect(ReceivingDoc.fromJson(const {'id': 'x', 'purchase_status': 'cancelled'}).cancelled, isTrue);
    });
  });

  group('receiving branch and business date', () {
    Map<String, dynamic> ctx({List<String> perms = const ['xaridlar.edit']}) => contextJson(
          role: 'omborchi',
          permissions: perms,
          branches: [branchJson('b1', 'Markaz', businessDate: '2026-09-19'), branchJson('b2', 'Chilonzor')],
          actorBranch: branchJson('b1', 'Markaz', businessDate: '2026-09-19'),
        );

    test('branch state: actor shown; switching to another branch blocks with a reason', () async {
      final be = FakeBackend()..get('/auth/context', (_) => ctx());
      signIn(role: 'omborchi', permissions: const ['xaridlar.edit']);
      expect(RecvBranchState.of().issue, RecvBranchIssue.unknown);
      await be.run(() => Session.instance.load(force: true));
      expect(RecvBranchState.of().ok, isTrue);
      expect(RecvBranchState.of().actor!.name, 'Markaz');
      await Session.instance.selectBranch('b2');
      final st = RecvBranchState.of();
      expect(st.issue, RecvBranchIssue.mismatch);
      L.code = 'ru';
      expect(st.reason(), contains('«Chilonzor»'));
      expect(st.reason(), contains('«Markaz»'));
    });

    test('business date: server probe with ombor.view, else the session date; cached', () async {
      final be = FakeBackend()
        ..get('/auth/context', (_) => ctx(perms: const ['xaridlar.edit', 'ombor.view']))
        ..get('/lots/products/{id}', (_) => {'business_date': '2026-09-20', 'lots': []});
      signIn(role: 'omborchi', permissions: const ['xaridlar.edit', 'ombor.view']);
      await be.run(() async {
        await Session.instance.load(force: true);
        expect(await ReceivingApi.businessDate('t1'), '2026-09-20');
        expect(await ReceivingApi.businessDate('t2'), '2026-09-20');
      });
      expect(be.calls('GET', '/lots/products/t1'), hasLength(1));
      expect(be.calls('GET', '/lots/products/t2'), isEmpty, reason: 'cached for 5 minutes');
    });

    test('business date without ombor.view: no probe, the /auth/context date is used', () async {
      final be = FakeBackend()..get('/auth/context', (_) => ctx());
      signIn(role: 'omborchi', permissions: const ['xaridlar.edit']);
      await be.run(() async {
        await Session.instance.load(force: true);
        expect(await ReceivingApi.businessDate('t1'), '2026-09-19');
      });
      expect(be.calls('GET', '/lots/products/t1'), isEmpty);
    });

    test('business date: a 403 probe falls back; nothing known -> null (server decides)', () async {
      final be = FakeBackend()
        ..get('/lots/products/{id}', (_) => FakeResponse.error(403, "Ruxsat yo'q: ombor.view", code: 'PERMISSION_DENIED'));
      signIn(role: 'omborchi', permissions: const ['xaridlar.edit', 'ombor.view']);
      final d = await be.run(() => ReceivingApi.businessDate('t1'));
      expect(d, isNull);
    });
  });

  test('LotEditorController clone helper keeps rows when not automatic', () {
    final c = LotEditorController(trackExpiry: false, targetMilli: 3000);
    c.update(c.rows.first.key, qty: '1');
    c.add();
    c.update(c.rows.last.key, qty: '2');
    final n = cloneLotController(c);
    expect(n.rows.map((r) => r.qty), ['1', '2']);
    expect(n.state.ok, isTrue);
    c.dispose();
    n.dispose();
  });
}
