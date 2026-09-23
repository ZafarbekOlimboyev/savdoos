// Shared fixtures of the M2 (stock) tests + a self-check of the fixtures.
// Other stock tests import this file: `import 'stock_fixtures_test.dart';`.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

export 'support/support.dart';

/// Seed permission sets of the roles (`apps/server/app/seed.py`).
const Map<String, List<String>> kRolePerms = {
  'ega': [],
  'administrator': [],
  'omborchi': ['mahsulotlar.view', 'mahsulotlar.edit', 'ombor.view', 'ombor.edit', 'xaridlar.view', 'xaridlar.edit'],
  'kassir': ['kassa.sell', 'kassa.view', 'sotuvlar.view', 'qaytarishlar.create', 'mijozlar.view'],
  'menejer': [
    'sotuvlar.view', 'qaytarishlar.create', 'qaytarishlar.view', 'mijozlar.view', 'mijozlar.edit', //
    'mahsulotlar.view', 'mahsulotlar.edit', 'ombor.view', 'hisobot.view', 'sozlamalar.view',
  ],
};

/// A `ProductOut`.
Map<String, dynamic> prodJson(
  String id,
  String name, {
  num stock = 10,
  num min = 0,
  bool tracked = false,
  bool expiry = false,
  String unit = 'dona',
  bool active = true,
  String? expiryDate,
  num sell = 15000,
  num buy = 12000,
}) =>
    {
      'id': id,
      'name': name,
      'unit_code': unit,
      'stock': stock,
      'min_stock': min,
      'base_sell_price': sell,
      'base_buy_price': buy,
      'track_lots': tracked,
      'track_expiry': expiry,
      'is_active': active,
      'is_weighted': unit == 'kg',
      'plu_code': null,
      'expiry_date': expiryDate,
      'barcodes': ['478${id.hashCode.abs() % 100000}'],
    };

/// A lot of `/lots/products/{id}`.
Map<String, dynamic> lotJson(
  String id, {
  String? batch,
  String? expiry,
  bool expired = false,
  num remaining = 1,
  num received = 10,
  num cost = 1000,
  String status = 'open',
}) =>
    {
      'id': id,
      'batch_number': batch,
      'expiry_date': expiry,
      'expired': expired,
      'received_qty': received,
      'remaining_qty': remaining,
      'unit_cost': cost,
      'status': status,
      'source_type': 'receiving',
      'received_at': '2026-09-01T08:00:00',
    };

/// `/lots/products/{id}` payload.
Map<String, dynamic> lotsJson(String pid, List<Map<String, dynamic>> lots,
        {bool tracked = true, bool expiry = false, String biz = '2026-09-19', num inv = 0, num shortfall = 0}) =>
    {
      'product_id': pid,
      'track_lots': tracked,
      'track_expiry': expiry,
      'business_date': biz,
      'inventory_qty': inv,
      'unresolved_shortfall_qty': shortfall,
      'lots': lots,
    };

/// Two visible branches (b1 = actor, b2).
List<Map<String, dynamic>> twoBranches() => [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')];

/// Signs in as [role] (seed permissions unless [perms] is given) and loads
/// `/auth/context` from [be].
Future<void> signInAs(FakeBackend be,
    {String role = 'ega', List<String>? perms, List<Map<String, dynamic>>? branches}) async {
  final p = perms ?? kRolePerms[role] ?? const [];
  be.get('/auth/context', (_) => contextJson(role: role, permissions: p, branches: branches ?? twoBranches()));
  signIn(role: role, permissions: p);
  await be.run(() => Session.instance.load(force: true));
}

/// A fake camera: every tap on `fake-detect` "detects" the next code.
ScannerViewBuilder fakeCamera(List<String> codes) => (ctx, onCode, errorView) => Center(
      child: ElevatedButton(
        key: const Key('fake-detect'),
        onPressed: () => onCode(codes.removeAt(0)),
        child: const Text('detect'),
      ),
    );

/// `/products/scan` reply for a barcode hit.
Map<String, dynamic> scanHit(Map<String, dynamic> product, {String code = '4780001'}) =>
    {'code': code, 'kind': 'barcode', 'product': product, 'candidates': [], 'scale': null};

void main() {
  setUp(() async => resetCore());
  tearDown(() => Session.instance.debugReset());

  test('fixtures parse into the stock models', () {
    final p = StockProduct.fromJson(prodJson('p1', 'Sut', stock: 2.5, tracked: true, expiryDate: '2020-01-01'));
    expect(p.stockMilli, 2500);
    expect(p.trackLots, isTrue);
    expect(p.productExpiry, isNull, reason: 'frozen product expiry is ignored for tracked products');
    final l = ProductLots.fromJson(lotsJson('p1', [lotJson('l1', remaining: 0.3)]), branchId: 'b1');
    expect(l.lots.single.remainingMilli, 300);
    expect(l.branchId, 'b1');
  });

  test('signInAs loads the context with two branches', () async {
    final be = FakeBackend();
    await signInAs(be, role: 'omborchi');
    expect(Session.instance.currentBranchId, 'b1');
    expect(Session.instance.can('ombor.edit'), isTrue);
    expect(Session.instance.can('hisobot.view'), isFalse);
  });
}
