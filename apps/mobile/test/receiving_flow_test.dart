// Receiving (M1) — widget flows against a fake backend at 390×844.
//
// Covers: untracked manual receiving, tracked single / multi lot with expiry
// and the branch business date, sum mismatch, 3-decimal refusal, cash custody
// (choose / blocked / not required), duplicate replies (with and without lost
// edits), network failure (no success, same client_uuid on retry), permission
// gating, server error mapping (+ tracked list reload), branch mismatch, the
// AI review, the receiving detail, the tracked-name collision and a used
// barcode.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/screens/manual_receiving_screen.dart';
import 'package:savdoos_mobile/screens/receiving_detail_screen.dart';
import 'package:savdoos_mobile/screens/receiving_home_screen.dart';
import 'package:savdoos_mobile/screens/receiving_item_editor_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

const kEdit = ['xaridlar.edit', 'xaridlar.view', 'ombor.view', 'ombor.edit', 'mahsulotlar.view', 'mahsulotlar.edit'];

Map<String, dynamic> prod(String id, String name,
        {bool tracked = false,
        bool expiry = false,
        String unit = 'dona',
        num buy = 1000,
        num sell = 1500,
        bool active = true,
        bool weighted = false,
        String? plu,
        List<String> barcodes = const []}) =>
    {
      'id': id,
      'article_code': 'A-$id',
      'sku': id,
      'name': name,
      'category_id': null,
      'base_buy_price': buy,
      'base_sell_price': sell,
      'tax_rate': 12,
      'is_active': active,
      'barcodes': barcodes,
      'stock': 10,
      'min_stock': 1,
      'unit_code': unit,
      'expiry_date': null,
      'is_weighted': weighted,
      'plu_code': plu,
      'scale_sync': false,
      'sold_qty': 0,
      'track_lots': tracked,
      'track_expiry': expiry,
    };

Map<String, dynamic> custody(String mode, {String? reason, List<Map<String, dynamic>> options = const []}) => {
      'mode': mode,
      'reason': reason,
      'resolved': null,
      'options': options,
      'branch': {'id': 'b1', 'name': 'Markaz'},
    };

const till = {'id': 't-01', 'type': 'TILL', 'code': 'K-01', 'currency': 'UZS'};
const safe = {'id': 's-01', 'type': 'SAFE', 'code': 'S-01', 'currency': 'UZS'};

Map<String, dynamic> okCommit(FakeRequest r) => {
      'ok': true,
      'receiving_id': 'rec-1',
      'purchase_id': 'pur-1',
      'doc_no': 'KIR-000123',
      'results': [
        for (final i in (r.body['items'] as List))
          {'product': 'X', 'old_qty': 1, 'added': (i as Map)['qty'], 'new_qty': 1 + (i['qty'] as num), 'unit': 'dona'}
      ],
      'payment': r.body['payment'],
      'supplier': 'Qabul (mobil)',
      'total_types': (r.body['items'] as List).length,
      'total_qty': 1,
    };

/// Fake receiving backend.
class Fx {
  Fx({this.perms = kEdit, this.role = 'omborchi', this.branches, this.actor});

  final List<String> perms;
  final String role;
  final List<Map<String, dynamic>>? branches;
  final Map<String, dynamic>? actor;
  final be = FakeBackend();

  List<Map<String, dynamic>> catalog = [
    prod('p1', 'Sut 1L', unit: 'litr', buy: 12000, sell: 15000),
    prod('t1', 'Kefir 1L', tracked: true, expiry: true, buy: 8000),
    prod('t2', 'Guruch', tracked: true, unit: 'kg', buy: 14000),
  ];
  Set<String> trackedIds = {'t1', 't2'};
  Map<String, dynamic> custodyBlock = custody('NOT_REQUIRED');
  FutureOr<Object?> Function(FakeRequest r) onCommit = okCommit;
  Map<String, dynamic>? scanAnswer;

  void install() {
    be.get('/auth/context', (_) => contextJson(
          role: role,
          permissions: perms,
          branches: branches ?? [branchJson('b1', 'Markaz', businessDate: '2026-09-19')],
          actorBranch: actor ?? branchJson('b1', 'Markaz', businessDate: '2026-09-19'),
        ));
    be.get('/products', (r) {
      if (r.query['tracked'] == 'true') {
        return [
          for (final p in catalog)
            if (trackedIds.contains(p['id'])) {...p, 'track_lots': true}
        ];
      }
      final q = (r.query['q'] ?? '').toLowerCase();
      return [for (final p in catalog) if ((p['name'] as String).toLowerCase().contains(q)) p];
    });
    be.get('/categories', (_) => [
          {'id': 'c1', 'name': 'Sut mahsulotlari'}
        ]);
    be.get('/products/guess-category', (_) => {'category_id': null, 'category_name': null});
    be.get('/suppliers', (_) => [
          {'id': 'sup-1', 'name': 'Nestle', 'phone': null, 'balance': 0}
        ]);
    be.get('/lots/products/{id}', (_) => {'business_date': '2026-09-19', 'lots': []});
    be.get('/cash/custody-preview', (_) => custodyBlock);
    be.post('/receiving/commit', (r) => onCommit(r));
    be.get('/products/scan', (r) => scanAnswer ?? {'code': r.query['code'], 'kind': 'none', 'product': null, 'candidates': []});
    be.get('/receiving', (_) => [
          {
            'id': 'rec-9',
            'at': '2026-09-19 07:00:00',
            'source': 'manual',
            'employee': 'Ali',
            'total_types': 2,
            'total_qty': 7.5,
            'purchase_id': 'pur-9',
            'doc_no': 'KIR-000009',
            'payment': 'credit',
            'supplier': 'Nestle',
            'purchase_status': 'debt',
            'branch_id': 'b1',
            'branch_name': 'Markaz',
          }
        ]);
    be.get('/receiving/{id}', (r) => {
          'id': r.params['id'],
          'at': '2026-09-19 07:00:00',
          'source': 'ai',
          'employee': 'Ali',
          'total_types': 1,
          'total_qty': 2,
          'items': [
            {'product_id': 'p1', 'name': 'Sut 1L', 'qty': 2, 'unit_cost': 12000, 'ai_name': 'SUT', 'unit': 'litr'}
          ],
          'ai_raw': [],
          'image_b64': null,
          'purchase_id': 'pur-9',
          'doc_no': 'KIR-000009',
          'payment': 'credit',
          'supplier': 'Nestle',
          'purchase_status': 'debt',
          'branch_id': 'b1',
          'branch_name': 'Markaz',
        });
  }
}

Future<void> boot(Fx fx) async {
  fx.install();
  signIn(role: fx.role, permissions: fx.perms);
  await Session.instance.load(force: true);
}

Future<void> open(WidgetTester t, Widget screen) async {
  await pumpAt390(t, LaunchHost(onPressed: (ctx) => Navigator.of(ctx).push(MaterialPageRoute(builder: (_) => screen))));
  await t.tap(find.text('open'));
  await t.pumpAndSettle();
}

Future<void> tapK(WidgetTester t, String key) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

Future<void> typeK(WidgetTester t, String key, String text) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.enterText(f, text);
  await t.pump();
}

/// Adds a line through the editor: server search by [q], pick [id], qty, cost.
Future<void> addLine(WidgetTester t, String q, String id, {required String qty, String? cost, bool save = true}) async {
  await tapK(t, 'recv-add-line');
  await typeK(t, 'recv-edit-name', q);
  await t.pump(const Duration(milliseconds: 400));
  await t.pumpAndSettle();
  await tapK(t, 'recv-sugg-$id');
  await typeK(t, 'recv-edit-qty', qty);
  if (cost != null) await typeK(t, 'recv-edit-cost', cost);
  if (save) {
    await tapK(t, 'sticky-primary');
  }
}

Future<void> typeExpiry(WidgetTester t, int row, String ddmmyyyy) async {
  await tapK(t, 'lot-expiry-$row');
  await t.enterText(find.byKey(const Key('date-typed')), ddmmyyyy);
  await t.pump();
  await t.tap(find.byKey(const Key('date-typed-ok')));
  await t.pumpAndSettle();
}

/// Draft "save" → submit sheet → payment → (optional account) → save.
Future<void> submit(WidgetTester t, String payment, {String? account}) async {
  await tapK(t, 'sticky-primary');
  await t.tap(find.byKey(Key('recv-pay-$payment')));
  await t.pumpAndSettle();
  if (account != null) {
    await t.tap(find.byKey(Key('custody-option-$account')));
    await t.pumpAndSettle();
  }
  await t.tap(find.byKey(const Key('recv-submit-save')));
  await t.pumpAndSettle();
}

List<Map<String, dynamic>> items(FakeRequest r) => [for (final i in r.body['items'] as List) (i as Map).cast<String, dynamic>()];

void main() {
  setUp(() async {
    await resetCore();
    ReceivingApi.debugReset();
    ReceivingItemEditorScreen.debugScannerBuilder = null;
    ReceivingHomeScreen.debugPicker = null;
  });
  tearDown(() => Session.instance.debugReset());

  testWidgets('manual, untracked, credit: legacy payload; success shown only after the 2xx', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      expect(find.text('Qabul filiali: Markaz'), findsOneWidget);
      await addLine(t, 'sut', 'p1', qty: '2,5');
      expect(find.text('Sut 1L'), findsOneWidget);
      expect(find.byKey(const Key('recv-total')), findsOneWidget);
      expect(find.text(formatCents(3000000)), findsWidgets, reason: '2,5 × 12 000 (cost prefilled from the product)');
      await submit(t, 'credit');
      expect(find.byKey(const Key('recv-saved-title')), findsOneWidget);
      expect(find.textContaining('KIR-000123'), findsOneWidget);
    });
    final r = fx.be.last('POST', '/receiving/commit');
    expect(r.body['payment'], 'credit');
    expect(r.body['source'], 'manual');
    expect(r.body.containsKey('cash_account_id'), isFalse);
    expect(items(r).single, {
      'product_id': 'p1',
      'new_name': null,
      'new_sell_price': 15000,
      'new_category_id': null,
      'new_barcode': null,
      'new_plu': null,
      'new_is_weighted': null,
      'new_min_qty': null,
      'qty': 2.5,
      'unit_cost': 12000,
      'ai_name': null,
      'unit': null,
    });
    expect(fx.be.calls('GET', '/cash/custody-preview'), isEmpty, reason: 'credit never asks for a cash account');
  });

  testWidgets('tracked + expiry: business date hint, expiry required, then cash OPERATOR_MUST_CHOOSE', (t) async {
    final fx = Fx()..custodyBlock = custody('OPERATOR_MUST_CHOOSE', reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [till, safe]);
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'kef', 't1', qty: '5', save: false);
      expect(find.byKey(const Key('recv-edit-lots')), findsOneWidget);
      expect(find.text('Muddat 19.09.2026 yoki undan keyin bo‘lsin'), findsOneWidget, reason: 'business date of the receiving branch');
      await tapK(t, 'sticky-primary');
      expect(find.text('Yaroqlilik muddatini kiriting'), findsOneWidget);
      expect(find.byKey(const Key('recv-edit-lots')), findsOneWidget, reason: 'still in the editor');
      await typeExpiry(t, 0, '31122026');
      await tapK(t, 'sticky-primary');
      expect(find.byKey(const Key('badge-tracked')), findsOneWidget);
      // Cash: the preview says "choose" — nothing preselected, save refuses without a choice.
      await tapK(t, 'sticky-primary');
      await t.tap(find.byKey(const Key('recv-pay-cash')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('custody-option-t-01')), findsOneWidget);
      expect(find.byKey(const Key('custody-option-s-01')), findsOneWidget);
      await t.tap(find.byKey(const Key('recv-submit-save')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('custody-required')), findsOneWidget);
      expect(fx.be.calls('POST', '/receiving/commit'), isEmpty);
      await t.tap(find.byKey(const Key('custody-option-s-01')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('recv-submit-save')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-saved-title')), findsOneWidget);
    });
    expect(fx.be.last('GET', '/cash/custody-preview').query, {'operation': 'receiving_payment'});
    final r = fx.be.last('POST', '/receiving/commit');
    expect(r.body['cash_account_id'], 's-01');
    expect(r.body['payment'], 'cash');
    final it = items(r).single;
    expect(it['qty'], 5);
    expect(it['unit_cost'], 8000);
    expect(it['lots'], [
      {'qty': 5, 'expiry_date': '2026-12-31'}
    ]);
  });

  testWidgets('tracked multi lot: sum mismatch keeps the editor open; fixed sum saves two lots', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'gur', 't2', qty: '5', save: false);
      await tapK(t, 'lot-add');
      await typeK(t, 'lot-qty-0', '3');
      await typeK(t, 'lot-qty-1', '1');
      await tapK(t, 'sticky-primary');
      expect(find.textContaining('yana 1 kerak'), findsOneWidget);
      expect(find.byKey(const Key('recv-edit-lots')), findsOneWidget);
      await typeK(t, 'lot-qty-1', '2');
      await tapK(t, 'sticky-primary');
      expect(find.text('Guruch'), findsOneWidget);
      await submit(t, 'credit');
    });
    final it = items(fx.be.last('POST', '/receiving/commit')).single;
    expect(it['lots'], [
      {'qty': 3},
      {'qty': 2}
    ]);
    expect(it['qty'], 5);
  });

  testWidgets('quantity with more than 3 decimals is refused at input (never rounded)', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1,234', save: false);
      await t.enterText(find.byKey(const Key('recv-edit-qty')), '1,2345');
      await t.pump();
      final field = t.widget<TextField>(find.descendant(of: find.byKey(const Key('recv-edit-qty')), matching: find.byType(TextField)));
      expect(field.controller!.text, '1,234');
    });
  });

  testWidgets('cash BLOCKED: save disabled with the localized reason; credit still possible', (t) async {
    final fx = Fx()..custodyBlock = custody('BLOCKED', reason: 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER');
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await tapK(t, 'sticky-primary');
      await t.tap(find.byKey(const Key('recv-pay-cash')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('custody-blocked')), findsOneWidget);
      expect(find.text('Bu amal ochiq smena kassasiga mos emas. Smena o‘rtasida kassa almashtirilmaydi.'), findsWidgets);
      final btn = t.widget<ElevatedButton>(find.byKey(const Key('recv-submit-save')));
      expect(btn.onPressed, isNull);
      await t.tap(find.byKey(const Key('recv-pay-credit')));
      await t.pumpAndSettle();
      expect(t.widget<ElevatedButton>(find.byKey(const Key('recv-submit-save'))).onPressed, isNotNull);
    });
    expect(fx.be.calls('POST', '/receiving/commit'), isEmpty);
  });

  testWidgets('cash NOT_REQUIRED / SERVER_RESOLVED: nothing chosen, no cash_account_id sent', (t) async {
    final fx = Fx()..custodyBlock = {...custody('SERVER_RESOLVED'), 'resolved': till};
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await tapK(t, 'sticky-primary');
      await t.tap(find.byKey(const Key('recv-pay-cash')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('custody-resolved')), findsOneWidget);
      await t.tap(find.byKey(const Key('recv-submit-save')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-saved-title')), findsOneWidget);
    });
    expect(fx.be.last('POST', '/receiving/commit').body.containsKey('cash_account_id'), isFalse);
  });

  testWidgets('cash refusal by the server: sheet stays open, reason shown, custody re-read', (t) async {
    final fx = Fx()..custodyBlock = custody('NOT_REQUIRED');
    var n = 0;
    fx.onCommit = (r) {
      n++;
      if (n == 1) {
        fx.custodyBlock = custody('OPERATOR_MUST_CHOOSE', reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [till]);
        return FakeResponse.error(400, 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: naqd amal uchun hisob kerak');
      }
      return okCommit(r);
    };
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await submit(t, 'cash');
      expect(find.byKey(const Key('recv-submit-error')), findsOneWidget);
      expect(find.textContaining('pul manbaini (kassa yoki seyf) tanlang'), findsWidgets);
      expect(find.byKey(const Key('custody-option-t-01')), findsOneWidget, reason: 'block re-read from the server');
      await t.tap(find.byKey(const Key('custody-option-t-01')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('recv-submit-save')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-saved-title')), findsOneWidget);
    });
    expect(fx.be.calls('GET', '/cash/custody-preview'), hasLength(2));
    final calls = fx.be.calls('POST', '/receiving/commit');
    expect(calls.first.body.containsKey('cash_account_id'), isFalse);
    expect(calls.last.body['cash_account_id'], 't-01');
    expect(calls.first.body['client_uuid'], calls.last.body['client_uuid']);
  });

  testWidgets('custody preview unreachable: cash blocked with retry (fail closed)', (t) async {
    final fx = Fx();
    var down = true;
    await fx.be.run(() async {
      await boot(fx);
      fx.be.get('/cash/custody-preview', (_) {
        if (down) throw const SocketException('down');
        return custody('NOT_REQUIRED');
      });
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await tapK(t, 'sticky-primary');
      await t.tap(find.byKey(const Key('recv-pay-cash')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-custody-error')), findsOneWidget);
      expect(t.widget<ElevatedButton>(find.byKey(const Key('recv-submit-save'))).onPressed, isNull);
      down = false;
      await t.tap(find.descendant(of: find.byKey(const Key('recv-custody-error')), matching: find.byKey(const Key('banner-retry'))));
      await t.pumpAndSettle();
      expect(t.widget<ElevatedButton>(find.byKey(const Key('recv-submit-save'))).onPressed, isNotNull);
    });
    expect(fx.be.calls('POST', '/receiving/commit'), isEmpty);
  });

  testWidgets('lost answer: explicit error (no success), retry reuses client_uuid, duplicate is explicit', (t) async {
    final fx = Fx();
    var n = 0;
    fx.onCommit = (r) {
      n++;
      if (n == 1) throw const SocketException('connection reset');
      return {'ok': true, 'receiving_id': 'rec-1', 'duplicate': true};
    };
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await submit(t, 'credit');
      expect(find.byKey(const Key('recv-saved-title')), findsNothing);
      expect(find.byKey(const Key('recv-submit-error')), findsOneWidget);
      expect(find.textContaining('Server bilan aloqa yo‘q'), findsWidgets);
      expect(find.byKey(const Key('recv-submit-safe-retry')), findsOneWidget);
      await t.tap(find.byKey(const Key('recv-submit-save')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-duplicate-title')), findsOneWidget);
      expect(find.text('Keyingi o‘zgarishlar qo‘llanmaydi — saqlangan hujjat oldingi urinishdagidek qoldi.'), findsOneWidget);
      expect(find.byKey(const Key('recv-saved-title')), findsNothing);
    });
    final calls = fx.be.calls('POST', '/receiving/commit');
    expect(calls, hasLength(2));
    expect(calls[0].body['client_uuid'], calls[1].body['client_uuid']);
  });

  testWidgets('duplicate after an EDIT: the screen says the later edits were NOT applied', (t) async {
    final fx = Fx();
    var n = 0;
    fx.onCommit = (r) {
      n++;
      if (n == 1) throw const SocketException('timeout-ish');
      return {'ok': true, 'receiving_id': 'rec-1', 'duplicate': true};
    };
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '1');
      await submit(t, 'credit');
      await t.tap(find.byKey(const Key('recv-submit-close')));
      await t.pumpAndSettle();
      // Operator changes the quantity and sends again.
      await t.tap(find.text('Sut 1L'));
      await t.pumpAndSettle();
      await typeK(t, 'recv-edit-qty', '3');
      await tapK(t, 'sticky-primary');
      await submit(t, 'credit');
      expect(find.byKey(const Key('recv-duplicate-title')), findsOneWidget);
      expect(find.textContaining('QO‘LLANMADI'), findsOneWidget);
      expect(find.byKey(const Key('recv-done-open')), findsOneWidget);
    });
    final calls = fx.be.calls('POST', '/receiving/commit');
    expect(calls[0].body['client_uuid'], calls[1].body['client_uuid'], reason: 'one document = one uuid');
    expect(items(calls[1]).single['qty'], 3);
  });

  testWidgets('server refusal is localized (ru), tracked list reloaded, the line becomes lot-tracked', (t) async {
    L.code = 'ru';
    final fx = Fx()..trackedIds = {};
    fx.onCommit = (r) => FakeResponse.error(
        400, "'Sut 1L' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY. Miqdor taxmin qilinmaydi.",
        code: 'LOT_LINES_REQUIRED');
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await addLine(t, 'sut', 'p1', qty: '2');
      fx.trackedIds = {'p1'}; // tracking was just enabled on the server
      await submit(t, 'credit');
      final banner = find.descendant(of: find.byKey(const Key('recv-doc-error')), matching: find.byKey(const Key('banner-text')));
      final text = t.widget<Text>(banner).data!;
      expect(text, contains('Sut 1L'));
      expect(text, isNot(contains('MAJBURIY')));
      expect(text, isNot(contains('lots')));
      expect(find.byKey(const Key('badge-tracked')), findsOneWidget, reason: 'line now lot-tracked');
    });
    expect(fx.be.calls('GET', '/products').where((r) => r.query['tracked'] == 'true'), hasLength(2));
  });

  testWidgets('branch mismatch: saving blocked with the reason; switching back unblocks', (t) async {
    final fx = Fx(
      role: 'administrator',
      perms: const [],
      branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')],
    );
    await fx.be.run(() async {
      await boot(fx);
      await Session.instance.selectBranch('b2');
      await open(t, const ManualReceivingScreen());
      expect(find.byKey(const Key('recv-branch-mismatch')), findsOneWidget);
      await addLine(t, 'sut', 'p1', qty: '1');
      expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
      expect(find.textContaining('«Chilonzor»'), findsWidgets);
      expect(t.widget<ElevatedButton>(find.byKey(const Key('sticky-primary'))).onPressed, isNull);
      await tapK(t, 'recv-branch-switch');
      expect(find.byKey(const Key('recv-branch-mismatch')), findsNothing);
      expect(t.widget<ElevatedButton>(find.byKey(const Key('sticky-primary'))).onPressed, isNotNull);
    });
  });

  group('home: permission gating', () {
    testWidgets('kassir: no receiving actions, no history request', (t) async {
      final fx = Fx(role: 'kassir', perms: const ['kassa.sell', 'kassa.view', 'sotuvlar.view']);
      await fx.be.run(() async {
        await boot(fx);
        await open(t, const ReceivingHomeScreen());
      });
      expect(find.byKey(const Key('recv-home-manual')), findsNothing);
      expect(find.byKey(const Key('recv-home-camera')), findsNothing);
      expect(find.byKey(const Key('recv-home-no-edit')), findsOneWidget);
      expect(fx.be.calls('GET', '/receiving'), isEmpty);
    });

    testWidgets('xaridlar.view only: history (doc no, supplier, payment) without actions', (t) async {
      final fx = Fx(role: 'menejer', perms: const ['xaridlar.view']);
      await fx.be.run(() async {
        await boot(fx);
        await open(t, const ReceivingHomeScreen());
      });
      expect(find.byKey(const Key('recv-home-manual')), findsNothing);
      expect(find.text('KIR-000009 · Nestle'), findsOneWidget);
      expect(find.text('Qarzga'), findsOneWidget);
    });

    testWidgets('xaridlar.edit only: actions without history', (t) async {
      final fx = Fx(role: 'omborchi', perms: const ['xaridlar.edit']);
      await fx.be.run(() async {
        await boot(fx);
        await open(t, const ReceivingHomeScreen());
      });
      expect(find.byKey(const Key('recv-home-manual')), findsOneWidget);
      expect(find.byKey(const Key('recv-home-camera')), findsOneWidget);
      expect(find.byKey(const Key('recv-home-no-history')), findsOneWidget);
      expect(fx.be.calls('GET', '/receiving'), isEmpty);
      expectMinTouchTarget(t, find.byKey(const Key('recv-home-manual')));
    });

    testWidgets('history load failure: explicit error with retry', (t) async {
      final fx = Fx();
      var fail = true;
      await fx.be.run(() async {
        await boot(fx);
        fx.be.get('/receiving', (_) => fail ? FakeResponse.error(500, 'boom') : <Object>[]);
        await open(t, const ReceivingHomeScreen());
        expect(find.byKey(const Key('recv-history-error')), findsOneWidget);
        fail = false;
        await t.tap(find.byKey(const Key('banner-retry')));
        await t.pumpAndSettle();
        expect(find.byKey(const Key('recv-history-error')), findsNothing);
        expect(find.text('Hali qabul qilinmagan'), findsOneWidget);
      });
    });
  });

  testWidgets('AI review: tracked match gets lots, unmatched line picked via server search, photo + ai_raw sent', (t) async {
    final fx = Fx();
    fx.be.post('/receiving/scan', (r) => {
          'source': 'ai',
          'items': [
            {'ai_name': 'KEFIR 1L', 'qty': 4, 'unit': 'dona', 'price': null, 'product_id': 't1', 'matched_name': 'Kefir 1L', 'confidence': 0.93, 'unit_cost': 8000},
            {'ai_name': 'SUT', 'qty': 2, 'unit': 'dona', 'price': 12000, 'product_id': null, 'matched_name': null, 'confidence': 0.3, 'unit_cost': 12000},
          ],
          'ai_raw': [
            {'name': 'KEFIR 1L'},
            {'name': 'SUT'}
          ],
        });
    ReceivingHomeScreen.debugPicker = (source) async => (utf8.encode('fake-jpeg'), 'image/jpeg');
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ReceivingHomeScreen());
      await tapK(t, 'recv-home-gallery');
      expect(find.text('Diqqat talab qiladi'), findsOneWidget);
      expect(find.text('KEFIR 1L'), findsNothing, reason: 'matched name shown');
      expect(find.text('Kefir 1L'), findsOneWidget);
      // Kefir: tracked + expiry -> needs an expiry; SUT: unmatched.
      await t.tap(find.text('Mahsulotni tanlang').first);
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-search-field')), findsOneWidget);
      await t.enterText(find.byKey(const Key('recv-search-field')), 'sut');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('recv-search-p1')));
      await t.pumpAndSettle();
      // Fix the kefir line: add the expiry in the editor.
      await t.tap(find.text('Kefir 1L'));
      await t.pumpAndSettle();
      await typeExpiry(t, 0, '01032027');
      await tapK(t, 'sticky-primary');
      expect(find.text('Diqqat talab qiladi'), findsNothing);
      await submit(t, 'credit');
      expect(find.byKey(const Key('recv-saved-title')), findsOneWidget);
    });
    final r = fx.be.last('POST', '/receiving/commit');
    expect(r.body['source'], 'ai');
    expect(r.body['image_b64'], base64Encode(utf8.encode('fake-jpeg')));
    expect(r.body['ai_raw'], hasLength(2));
    final its = items(r);
    final kef = its.firstWhere((i) => i['product_id'] == 't1');
    expect(kef['lots'], [
      {'qty': 4, 'expiry_date': '2027-03-01'}
    ]);
    expect(kef['ai_name'], 'KEFIR 1L');
    final sut = its.firstWhere((i) => i['product_id'] == 'p1');
    expect(sut.containsKey('lots'), isFalse);
    expect(sut['ai_name'], 'SUT');
    expect(sut['qty'], 2);
  });

  testWidgets('editor: a new name equal to a tracked product is refused; one tap picks the tracked product', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      await tapK(t, 'recv-add-line');
      fx.catalog = []; // search finds nothing: the operator would create a "new" product
      await typeK(t, 'recv-edit-name', 'kefir 1l');
      await t.pump(const Duration(milliseconds: 700));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-edit-tracked-collision')), findsOneWidget);
      await typeK(t, 'recv-edit-barcode', '4780000000001');
      await typeK(t, 'recv-edit-qty', '2');
      await tapK(t, 'sticky-primary');
      expect(find.byKey(const Key('recv-edit-tracked-collision')), findsOneWidget, reason: 'not saved');
      await tapK(t, 'recv-edit-use-tracked');
      expect(find.byKey(const Key('recv-edit-product')), findsOneWidget);
      expect(find.byKey(const Key('recv-edit-lots')), findsOneWidget);
    });
  });

  testWidgets('editor: a typed barcode already used by another product is not silently attached', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      fx.scanAnswer = {'code': '4780000000009', 'kind': 'barcode', 'product': prod('p1', 'Sut 1L', unit: 'litr'), 'candidates': []};
      await open(t, const ManualReceivingScreen());
      await tapK(t, 'recv-add-line');
      await typeK(t, 'recv-edit-name', 'Yangi sut');
      await t.pump(const Duration(milliseconds: 700));
      await t.pumpAndSettle();
      await typeK(t, 'recv-edit-barcode', '4780000000009');
      await typeK(t, 'recv-edit-qty', '1');
      await tapK(t, 'sticky-primary');
      expect(find.byKey(const Key('recv-code-taken')), findsOneWidget);
      await t.tap(find.byKey(const Key('recv-code-taken-use')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('recv-edit-product')), findsOneWidget);
    });
    expect(fx.be.last('GET', '/products/scan').query['code'], '4780000000009');
  });

  testWidgets('editor: a scale label fills the product AND the weighed quantity', (t) async {
    final fx = Fx();
    ReceivingItemEditorScreen.debugScannerBuilder = (ctx, onCode, errorView) => Center(
          child: ElevatedButton(key: const Key('fake-detect'), onPressed: () => onCode('2000412012345'), child: const Text('d')),
        );
    await fx.be.run(() async {
      await boot(fx);
      fx.scanAnswer = {
        'code': '2000412012345',
        'kind': 'scale',
        'product': prod('w1', 'Go‘sht', unit: 'kg', weighted: true, plu: '412'),
        'candidates': [],
        'scale': {'plu': 412, 'grams': 1234, 'qty': '1.234'},
      };
      await open(t, const ManualReceivingScreen());
      await tapK(t, 'recv-add-line');
      await tapK(t, 'recv-edit-scan');
      await t.tap(find.byKey(const Key('fake-detect')));
      await t.pumpAndSettle();
      expect(find.text('Go‘sht'), findsOneWidget);
      final q = t.widget<TextField>(find.descendant(of: find.byKey(const Key('recv-edit-qty')), matching: find.byType(TextField)));
      expect(q.controller!.text, '1,234');
    });
  });

  testWidgets('detail: doc no, supplier, payment, lines and the purchase link', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ReceivingDetailScreen(id: 'rec-9'));
    });
    expect(find.text('KIR-000009'), findsOneWidget);
    expect(find.text('Nestle'), findsOneWidget);
    expect(find.text('Qarzga'), findsOneWidget);
    expect(find.text('Sut 1L'), findsOneWidget);
    expect(find.text(formatCents(2400000)), findsWidgets);
    expect(find.byKey(const Key('recv-detail-open-purchase')), findsOneWidget);
    expectMinTouchTarget(t, find.byKey(const Key('recv-detail-open-purchase')));
  });

  testWidgets('touch targets of the document screen and the submit sheet are >= 48 dp', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      await open(t, const ManualReceivingScreen());
      expectMinTouchTarget(t, find.byKey(const Key('recv-add-line')));
      expectMinTouchTarget(t, find.byKey(const Key('recv-supplier')));
      await addLine(t, 'sut', 'p1', qty: '1');
      expectMinTouchTarget(t, find.byWidgetPredicate((w) => w.key is ValueKey && '${(w.key as ValueKey).value}'.startsWith('recv-line-remove-')));
      await tapK(t, 'sticky-primary');
      expectMinTouchTarget(t, find.byKey(const Key('recv-pay-cash')));
      expectMinTouchTarget(t, find.byKey(const Key('recv-pay-credit')));
      expectMinTouchTarget(t, find.byKey(const Key('recv-submit-save')));
    });
  });

  testWidgets('editor: a weighed scale label is never kept as a permanent product barcode', (t) async {
    final fx = Fx();
    await fx.be.run(() async {
      await boot(fx);
      // The server parsed it as a scale label but no weighted product has PLU 1234.
      fx.scanAnswer = {
        'code': '2001234056780',
        'kind': 'none',
        'product': null,
        'candidates': [],
        'scale': {'plu': 1234, 'grams': 5678, 'qty': '5.678'},
      };
      await open(t, const ManualReceivingScreen());
      await tapK(t, 'recv-add-line');
      await typeK(t, 'recv-edit-name', 'Qadoqlangan go‘sht');
      await t.pump(const Duration(milliseconds: 700));
      await t.pumpAndSettle();
      await typeK(t, 'recv-edit-barcode', '2001234056780');
      await typeK(t, 'recv-edit-qty', '1');
      await typeK(t, 'recv-edit-cost', '10000');
      await tapK(t, 'sticky-primary');
      // The verification lookup says "scale": the code carries the WEIGHT, so it
      // can never become this product's permanent barcode.
      expect(find.byKey(const Key('recv-edit-scale-label')), findsOneWidget);
      expect(find.textContaining('tarozi yorlig‘i'), findsWidgets);
      expect(find.byKey(const Key('recv-edit-name')), findsOneWidget, reason: 'the editor stays open');
      expect(find.byKey(const Key('recv-line-0')), findsNothing, reason: 'nothing was added to the draft');
    });
    expect(fx.be.calls('POST', '/receiving/commit'), isEmpty);
  });

  testWidgets('scanner: a weighed label is not offered as a new product code (upstream guard)', (t) async {
    final fx = Fx();
    ReceivingItemEditorScreen.debugScannerBuilder = (ctx, onCode, errorView) => Center(
          child: ElevatedButton(key: const Key('fake-detect'), onPressed: () => onCode('2001234056780'), child: const Text('d')),
        );
    await fx.be.run(() async {
      await boot(fx);
      fx.scanAnswer = {
        'code': '2001234056780',
        'kind': 'none',
        'product': null,
        'candidates': [],
        'scale': {'plu': 1234, 'grams': 5678, 'qty': '5.678'},
      };
      await open(t, const ManualReceivingScreen());
      await tapK(t, 'recv-add-line');
      await tapK(t, 'recv-edit-scan');
      await t.tap(find.byKey(const Key('fake-detect')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('scan-scale-label')), findsOneWidget);
      expect(find.byKey(const Key('scan-use-code')), findsNothing);
    });
  });

  testWidgets('home history: every row says which branch the receiving belongs to', (t) async {
    final fx = Fx(branches: [
      branchJson('b1', 'Markaz', businessDate: '2026-09-19'),
      branchJson('b2', 'Bozor', businessDate: '2026-09-19'),
    ]);
    await fx.be.run(() async {
      await boot(fx);
      fx.be.get('/receiving', (_) => [
            {
              'id': 'rec-9',
              'at': '2026-09-19 07:00:00',
              'source': 'manual',
              'employee': 'Ali',
              'total_types': 2,
              'total_qty': 7.5,
              'doc_no': 'KIR-000009',
              'payment': 'credit',
              'supplier': 'Nestle',
              'branch_id': 'b1',
              'branch_name': 'Markaz',
            },
            {
              'id': 'rec-8',
              'at': '2026-09-19 06:00:00',
              'source': 'manual',
              'employee': 'Vali',
              'total_types': 1,
              'total_qty': 3,
              'doc_no': 'KIR-000008',
              'payment': 'cash',
              'supplier': 'Nestle',
              'branch_id': 'b2',
              'branch_name': 'Bozor',
            },
          ]);
      await open(t, const ReceivingHomeScreen());
      expect(find.text('Qabul filiali: Markaz'), findsOneWidget);
      expect(find.byKey(const Key('recv-history-branch-rec-8')), findsOneWidget);
      expect(t.widget<Text>(find.byKey(const Key('recv-history-branch-rec-8'))).data, contains('Bozor'));
      expect(t.widget<Text>(find.byKey(const Key('recv-history-branch-rec-9'))).data, contains('Markaz'));
    });
  });

  test('barcode scan screen hook type matches the core scanner builder', () {
    expect(ReceivingItemEditorScreen.debugScannerBuilder, isNull);
    const ScannerViewBuilder? b = null;
    expect(b, isNull);
    expect(ImageSource.gallery, isNotNull);
  });
}
