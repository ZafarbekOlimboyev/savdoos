// M5 — employees list / card: permission gating (disabled with a reason, never
// silently missing), UX mirror of the server's role rules, idempotent create,
// self-edit without password fields, destructive delete confirmation and
// localized server refusals.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/employee_edit_screen.dart';
import 'package:savdoos_mobile/screens/employees_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

Map<String, dynamic> detail(String id, String role,
        {String name = 'Karim', String? branchId = 'b1', List<String>? perms}) =>
    {
      'id': id,
      'full_name': name,
      'phone': '+996700111222',
      'role': role,
      'role_name': role,
      'status': 'active',
      'branch_id': branchId,
      'branch': branchId == null ? null : 'Markaz',
      'permissions': perms ?? const ['kassa.sell', 'sotuvlar.view'],
    };

/// Scrolls the employee card's list until [f] is visible.
Future<void> scrollTo(WidgetTester tester, Finder f) async {
  if (f.evaluate().isEmpty) {
    // Not built yet (lazy list): scroll the card down to it.
    await tester.scrollUntilVisible(f, 300,
        scrollable: find.descendant(of: find.byType(EmployeeEditScreen), matching: find.byType(Scrollable)).first);
  }
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
}

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get(
          '/branches',
          (_) => {
                'branches': [
                  {'id': 'b1', 'name': 'Markaz', 'is_active': true, 'visible': true},
                  {'id': 'b2', 'name': 'Chilonzor', 'is_active': true, 'visible': true},
                  {'id': 'b3', 'name': 'Yopiq', 'is_active': false, 'visible': true},
                ]
              })
      ..get(
          '/permissions',
          (_) => [
                {'code': 'kassa.sell', 'module': 'kassa'},
                {'code': 'ombor.edit', 'module': 'ombor'},
                {'code': 'xodimlar.make_admin', 'module': 'xodimlar'},
              ])
      ..get('/employees/{id}/stats', (_) => {'month_sales': 0, 'tx': 0, 'chart': []})
      ..get(
          '/employees',
          (_) => [
                {
                  'id': 'k1',
                  'full_name': 'Karim',
                  'role': 'kassir',
                  'role_name': 'Kassir',
                  'status': 'active',
                  'branch': 'Markaz'
                },
                {'id': 'o1', 'full_name': 'Olim', 'role': 'omborchi', 'role_name': 'Omborchi', 'status': 'suspended'},
              ]);
  });

  tearDown(() => s.debugReset());

  Future<void> signInAs(String role, {List<String> perms = const [], String id = 'me'}) async {
    signIn(id: id, role: role, permissions: perms);
    be.get('/auth/context', (_) => contextJson(employeeId: id, role: role, permissions: perms));
    await s.load(force: true);
  }

  /// Pushes [screen] from a host so the pop result can be observed.
  Future<List<Object?>> open(WidgetTester tester, Widget screen) async {
    final results = <Object?>[];
    await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
      results.add(await Navigator.of(ctx).push<Object?>(MaterialPageRoute(builder: (_) => screen)));
    }));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    return results;
  }

  testWidgets('list with xodimlar.view only: rows shown, "add" disabled WITH the reason', (tester) async {
    await be.run(() async {
      await signInAs('menejer', perms: ['xodimlar.view', 'hisobot.view']);
      await pumpAt390(tester, const EmployeesScreen());
      await tester.pumpAndSettle();
      expect(find.text('Karim'), findsOneWidget);
      expect(find.text("To'xtatilgan"), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('employee-k1')));
      final add = find.descendant(
          of: find.byKey(const Key('employees-add')), matching: find.byKey(const Key('sticky-primary')));
      expect(tester.widget<ElevatedButton>(add).onPressed, isNull);
      expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
      expect(find.textContaining('Xodimlarni boshqarish'), findsOneWidget);
    });
  });

  testWidgets('owner creates an employee: role sheet, current branch preselected, client_uuid reused on retry',
      (tester) async {
    var fail = true;
    be.post('/employees', (r) => fail ? throw Exception('socket closed') : {'id': 'n1', 'full_name': 'Ali'});
    await be.run(() async {
      await signInAs('ega');
      final results = await open(tester, const EmployeeEditScreen());
      await tester.enterText(find.byKey(const Key('employee-name')), 'Ali Valiyev');
      await tester.tap(find.byKey(const Key('employee-role')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('role-ega')), findsOneWidget);
      await tester.tap(find.byKey(const Key('role-omborchi')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('employee-pin')), '4321');
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('employee-error')), findsOneWidget, reason: 'network failure is shown, not success');
      expect(results, isEmpty);
      final first = be.last('POST', '/employees').body;
      expect(first['full_name'], 'Ali Valiyev');
      expect(first['role_code'], 'omborchi');
      expect(first['branch_id'], 'b1', reason: 'the current branch is the default');
      expect(first['pin'], '4321');
      expect(first.containsKey('password'), isFalse);
      expect(first['client_uuid'], isA<String>());

      fail = false;
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(be.last('POST', '/employees').body['client_uuid'], first['client_uuid'],
          reason: 'same draft -> same uuid');
      expect(results, [true]);
    });
  });

  testWidgets('client validation: name required, PIN 4 digits, long password needs a phone — nothing is sent',
      (tester) async {
    be.post('/employees', (_) => {'id': 'x'});
    await be.run(() async {
      await signInAs('ega');
      await open(tester, const EmployeeEditScreen());
      await tester.enterText(find.byKey(const Key('employee-pin')), '12');
      await tester.enterText(find.byKey(const Key('employee-password')), 'short');
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(find.text('Ism kiriting'), findsOneWidget);
      expect(find.text('PIN aynan 4 raqam bo‘lsin'), findsOneWidget);
      expect(find.text(trArgs('Parol kamida {n} belgi bo‘lsin', {'n': kMinPasswordLength})), findsOneWidget);

      await tester.enterText(find.byKey(const Key('employee-name')), 'Ali');
      await tester.enterText(find.byKey(const Key('employee-pin')), '');
      await tester.enterText(find.byKey(const Key('employee-password')), 'uzun-va-yaxshi-parol');
      await tester.enterText(find.byKey(const Key('employee-phone')), '+996 ');
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(find.text('Parolli xodim uchun telefon (login) kerak'), findsOneWidget);
      expect(be.calls('POST', '/employees'), isEmpty);
    });
  });

  testWidgets('role sheet mirrors the server: admin without make_admin cannot pick administrator/ega', (tester) async {
    await be.run(() async {
      await signInAs('administrator');
      await open(tester, const EmployeeEditScreen());
      await tester.tap(find.byKey(const Key('employee-role')));
      await tester.pumpAndSettle();
      expect(tester.widget<InkWell>(find.byKey(const Key('role-ega'))).onTap, isNull);
      expect(tester.widget<InkWell>(find.byKey(const Key('role-administrator'))).onTap, isNull);
      expect(tester.widget<InkWell>(find.byKey(const Key('role-menejer'))).onTap, isNotNull);
      expect(find.text('Bu rolni tayinlash huquqingiz yo‘q'), findsNWidgets(2));
    });
  });

  test('assignable roles per signed-in role (UX mirror of employees.py)', () async {
    await be.run(() async {
      await signInAs('ega');
      expect(assignableRoles(s), kRoleOrder);
      await signInAs('administrator');
      expect(assignableRoles(s), ['kassir', 'omborchi', 'menejer']);
      await signInAs('administrator', perms: ['xodimlar.make_admin']);
      expect(assignableRoles(s), ['kassir', 'omborchi', 'menejer', 'administrator']);
      await signInAs('omborchi', perms: ['xodimlar.edit']); // override: never above own rank
      expect(assignableRoles(s), ['kassir', 'omborchi']);
    });
  });

  testWidgets(
      'own card: no password/PIN fields (server wants the current password), role locked, PATCH only the change',
      (tester) async {
    be.get('/employees/{id}', (r) => detail('me', 'administrator', name: 'Aziz'));
    be.patch('/employees/{id}', (_) => {'ok': true});
    await be.run(() async {
      await signInAs('administrator', id: 'me');
      final results = await open(tester, const EmployeeEditScreen(employeeId: 'me'));
      expect(find.text('Mening kartam'), findsOneWidget);
      expect(find.byKey(const Key('employee-password')), findsNothing);
      expect(find.byKey(const Key('employee-pin')), findsNothing);
      expect(find.byKey(const Key('employee-own-password')), findsOneWidget);
      expect(find.text('O‘z rolingizni o‘zgartira olmaysiz'), findsOneWidget);
      expect(find.byKey(const Key('employee-delete')), findsNothing, reason: 'nobody deletes themselves');
      await tester.enterText(find.byKey(const Key('employee-name')), 'Aziz Karimov');
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(be.last('PATCH', '/employees/me').body, {'full_name': 'Aziz Karimov'});
      expect(results, [true]);
    });
  });

  testWidgets('administrator opening an owner account: read-only with the reason; delete disabled with the reason',
      (tester) async {
    be.get('/employees/{id}', (r) => detail('o9', 'ega', name: 'Ega'));
    await be.run(() async {
      await signInAs('administrator');
      await open(tester, const EmployeeEditScreen(employeeId: 'o9'));
      expect(find.byKey(const Key('employee-readonly')), findsOneWidget);
      final save = find.descendant(
          of: find.byKey(const Key('employee-save')), matching: find.byKey(const Key('sticky-primary')));
      expect(tester.widget<ElevatedButton>(save).onPressed, isNull);
      expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('employee-delete')));
      expect(tester.widget<OutlinedButton>(find.byKey(const Key('employee-delete'))).onPressed, isNull);
      expect(find.byKey(const Key('employee-delete-reason')), findsOneWidget);
      expect(be.calls('PATCH', '/employees/o9'), isEmpty);
    });
  });

  testWidgets('owner deletes a cashier only after an explicit, acknowledged confirmation', (tester) async {
    be.get('/employees/{id}', (r) => detail('k1', 'kassir'));
    be.delete('/employees/{id}', (_) => {'ok': true});
    await be.run(() async {
      await signInAs('ega');
      final results = await open(tester, const EmployeeEditScreen(employeeId: 'k1'));
      await scrollTo(tester, find.byKey(const Key('employee-delete')));
      await tester.tap(find.byKey(const Key('employee-delete')));
      await tester.pumpAndSettle();
      expect(tester.widget<ElevatedButton>(find.byKey(const Key('confirm-yes'))).onPressed, isNull,
          reason: 'acknowledge first');
      await tester.tap(find.byKey(const Key('confirm-ack')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      expect(be.calls('DELETE', '/employees/k1'), hasLength(1));
      expect(results, [true]);
    });
  });

  testWidgets('server refusal is shown localized (ru), the form stays open', (tester) async {
    L.code = 'ru';
    be.get('/employees/{id}', (r) => detail('k1', 'kassir'));
    be.patch('/employees/{id}', (_) => FakeResponse.error(400, 'Xodimда ochiq smena bor — avval smenani yopish kerak'));
    await be.run(() async {
      await signInAs('ega');
      final results = await open(tester, const EmployeeEditScreen(employeeId: 'k1'));
      await scrollTo(tester, find.byKey(const Key('employee-active')));
      await tester.tap(find.byKey(const Key('employee-active')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      expect(be.last('PATCH', '/employees/k1').body, {'status': 'suspended'});
      expect(find.text('У сотрудника открыта смена — сначала закройте смену'), findsOneWidget);
      expect(results, isEmpty);
    });
  });

  testWidgets('permission toggles: owner changes a cashier override; a non-admin sees them locked with the reason',
      (tester) async {
    be.get('/employees/{id}', (r) => detail('k1', 'kassir'));
    be.patch(
        '/employees/{id}/permissions',
        (r) => {
              'ok': true,
              'permissions': ['kassa.sell', 'ombor.edit', 'sotuvlar.view'],
            });
    await be.run(() async {
      await signInAs('ega');
      await open(tester, const EmployeeEditScreen(employeeId: 'k1'));
      await scrollTo(tester, find.byKey(const Key('perm-ombor.edit')));
      await tester.tap(find.byKey(const Key('perm-ombor.edit')));
      await tester.pumpAndSettle();
      expect(be.last('PATCH', '/employees/k1/permissions').body, {
        'overrides': {'ombor.edit': true}
      });
      expect(tester.widget<SwitchListTile>(find.byKey(const Key('perm-ombor.edit'))).value, isTrue);
    });
  });

  testWidgets('menejer with an xodimlar.edit override: toggles locked (only ega/administrator change permissions)',
      (tester) async {
    be.get('/employees/{id}', (r) => detail('k1', 'kassir'));
    await be.run(() async {
      await signInAs('menejer', perms: ['xodimlar.view', 'xodimlar.edit']);
      await open(tester, const EmployeeEditScreen(employeeId: 'k1'));
      await scrollTo(tester, find.byKey(const Key('perms-locked')));
      expect(tester.widget<SwitchListTile>(find.byKey(const Key('perm-ombor.edit'))).onChanged, isNull);
      expect(find.text("Ruxsatlarni faqat Ega yoki administrator o'zgartiradi"), findsOneWidget);
    });
  });

  for (final lang in ['ru', 'ky']) {
    testWidgets('$lang: a full employee card (stats, permissions, danger zone) renders without overflow', (tester) async {
      L.code = lang;
      be.get('/employees/{id}', (r) => detail('k1', 'kassir', name: 'Gulnora Abdurahmonova Karimovna'));
      be.get('/employees/{id}/stats', (_) => {
            'month_sales': 123456789,
            'tx': 4321,
            'chart': [
              for (final m in ['Apr', 'May', 'Iyn', 'Iyl', 'Avg', 'Sen']) {'label': m, 'sales': 1000000}
            ],
          });
      await be.run(() async {
        await signInAs('ega');
        await open(tester, const EmployeeEditScreen(employeeId: 'k1'));
        await scrollTo(tester, find.byKey(const Key('employee-delete')));
      });
      expect(find.byKey(const Key('employee-delete')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
