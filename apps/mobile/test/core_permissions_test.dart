// VM only: reads assets/permission_matrix.json from disk.
@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Role permissions as seeded by the server (`apps/server/app/seed.py`).
const roles = <String, List<String>>{
  'menejer': [
    'sotuvlar.view', 'qaytarishlar.create', 'qaytarishlar.view', 'mijozlar.view', 'mijozlar.edit',
    'mahsulotlar.view', 'mahsulotlar.edit', 'ombor.view', 'hisobot.view', 'sozlamalar.view',
  ],
  'omborchi': ['mahsulotlar.view', 'mahsulotlar.edit', 'ombor.view', 'ombor.edit', 'xaridlar.view', 'xaridlar.edit'],
  'kassir': ['kassa.sell', 'kassa.view', 'sotuvlar.view', 'qaytarishlar.create', 'mijozlar.view'],
};

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });

  tearDown(() => Session.instance.debugReset());

  Future<void> loginAs(String role, {List<String>? perms}) async {
    signIn(role: role);
    be.get('/auth/context', (_) => contextJson(role: role, permissions: perms ?? roles[role] ?? const []));
    await be.run(() => Session.instance.load(force: true));
  }

  test('the asset is well-formed and complete', () {
    final doc = jsonDecode(File('assets/permission_matrix.json').readAsStringSync()) as Map;
    final actions = (doc['actions'] as Map).cast<String, dynamic>();
    expect(actions.length, greaterThanOrEqualTo(50));
    expect(doc['full_access_roles'], ['ega', 'administrator']);
    const known = {
      'kassa.sell', 'kassa.view', 'sotuvlar.view', 'qaytarishlar.create', 'qaytarishlar.view', 'mijozlar.view',
      'mijozlar.edit', 'mahsulotlar.view', 'mahsulotlar.edit', 'ombor.view', 'ombor.edit', 'xaridlar.view',
      'xaridlar.edit', 'hisobot.view', 'xodimlar.view', 'xodimlar.edit', 'xodimlar.make_admin', 'sozlamalar.view',
      'sozlamalar.edit',
    };
    for (final e in actions.entries) {
      final v = (e.value as Map).cast<String, dynamic>();
      expect(['GET', 'POST', 'PATCH', 'PUT', 'DELETE'], contains(v['method']), reason: e.key);
      expect(v['path'], startsWith('/'), reason: e.key);
      expect(v['path'], isNot(startsWith('/api/')), reason: 'paths are relative to /api/v1: ${e.key}');
      for (final c in v['any_of'] as List) {
        expect(known, contains(c), reason: '${e.key}: unknown permission $c');
      }
    }
    // The actions the feature packages rely on (SPEC §2.6).
    for (final a in [
      'receiving.commit', 'receiving.scan', 'receiving.history', 'receiving.detail', 'receiving.correct',
      'purchases.detail', 'stock.count', 'stock.writeoff', 'stock.transfer', 'lots.product', 'lots.batches',
      'custody.preview.receiving_payment', 'custody.preview.debt_payment', 'custody.preview.supplier_payment',
      'custody.preview.collection_destination', 'customers.create', 'customers.edit', 'customers.pay',
      'suppliers.list', 'suppliers.create', 'suppliers.edit', 'suppliers.pay', 'suppliers.ledger', 'cash.ops.create',
      'cash.ops.list', 'sales.list', 'sales.detail', 'sales.receipt', 'reports.overview', 'employees.list',
    ]) {
      expect(Perm.isKnown(a), isTrue, reason: a);
    }
  });

  test('rules mirror the server gates', () {
    expect(Perm.rule('receiving.commit')!.anyOf, ['xaridlar.edit']);
    expect(Perm.rule('customers.create')!.anyOf, ['mijozlar.edit', 'kassa.sell']);
    expect(Perm.rule('sales.receipt')!.anyOf, ['sotuvlar.view', 'hisobot.view', 'kassa.sell']);
    expect(Perm.rule('receiving.correct')!.path, '/receiving/{receiving_id}/corrections');
    final c = Perm.rule('custody.preview.collection_destination')!;
    expect(c.query, {'operation': 'collection_destination'});
    expect(c.gate, 'handler');
    expect(c.anyOf, ['hisobot.view']);
  });

  test('ega / administrator may do everything', () async {
    for (final r in ['ega', 'administrator']) {
      await loginAs(r, perms: const []);
      for (final rule in Perm.all) {
        expect(Perm.allows(rule.action), isTrue, reason: '$r ${rule.action}');
      }
      Session.instance.debugReset();
    }
  });

  test('omborchi: stock + purchasing, no reports/cash/sales', () async {
    await loginAs('omborchi');
    for (final a in ['stock.count', 'stock.writeoff', 'stock.transfer', 'receiving.commit', 'receiving.correct',
      'lots.product', 'suppliers.pay', 'custody.preview.receiving_payment', 'custody.preview.supplier_payment']) {
      expect(Perm.allows(a), isTrue, reason: a);
    }
    for (final a in ['cash.ops.create', 'reports.overview', 'sales.list', 'customers.pay', 'employees.list',
      'custody.preview.collection_destination', 'stock.overview']) {
      expect(Perm.allows(a), isFalse, reason: a);
    }
  });

  test('menejer: reports + customers, no purchasing, no stock writes', () async {
    await loginAs('menejer');
    for (final a in ['reports.overview', 'sales.list', 'sales.receipt', 'customers.pay', 'customers.create',
      'lots.batches', 'cash.ops.create', 'custody.preview.collection_destination', 'custody.preview.debt_payment']) {
      expect(Perm.allows(a), isTrue, reason: a);
    }
    for (final a in ['receiving.commit', 'stock.writeoff', 'suppliers.list', 'employees.list']) {
      expect(Perm.allows(a), isFalse, reason: a);
    }
  });

  test('kassir: own receipts and new customers only', () async {
    await loginAs('kassir');
    expect(Perm.allows('sales.receipt'), isTrue);
    expect(Perm.allows('customers.create'), isTrue);
    expect(Perm.allows('sales.list'), isTrue);
    expect(Perm.allows('customers.pay'), isFalse);
    expect(Perm.allows('reports.overview'), isFalse);
    expect(Perm.allows('stock.count'), isFalse);
    expect(Perm.allows('products.list'), isTrue, reason: 'any signed-in employee');
  });

  test('fail closed: unknown action, signed out', () async {
    await loginAs('ega');
    expect(Perm.allows('no.such.action'), isFalse);
    Session.instance.debugReset();
    signIn(role: 'ega');
    expect(Perm.allows('stock.count'), isTrue, reason: 'snapshot fallback before context loads');
    await resetCore(); // signed out
    expect(Perm.allows('products.list'), isFalse);
  });

  test('reason() names the missing permission in the UI language', () async {
    await loginAs('kassir');
    L.code = 'ru';
    expect(Perm.reason('stock.writeoff'), 'Нужно право: Складские операции');
    expect(Perm.reason('sales.receipt'), '');
    L.code = 'ky';
    expect(Perm.reason('suppliers.pay'), 'Уруксат керек: Сатып алуу жана кабыл алуу');
    expect(permissionLabel('weird.code'), 'weird.code');
  });

  test('malformed matrix is rejected', () {
    expect(() => Perm.loadFromJson('{"actions": {"x": {"method": "GET"}}}'), throwsFormatException);
    expect(() => Perm.loadFromJson('[]'), throwsFormatException);
  });
}
