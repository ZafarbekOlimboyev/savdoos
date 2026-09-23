import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });

  tearDown(() => s.debugReset());

  Map<String, dynamic> twoBranches({String role = 'menejer', List<String> perms = const ['ombor.view']}) => contextJson(
        role: role,
        permissions: perms,
        branches: [
          branchJson('b1', 'Markaz', businessDate: '2026-09-19'),
          branchJson('b2', 'Chilonzor', businessDate: '2026-09-20'),
          branchJson('b3', 'Yopiq', active: false),
        ],
        actorBranch: branchJson('b1', 'Markaz', businessDate: '2026-09-19'),
      );

  test('loads /auth/context: identity, permissions, branches, business dates', () async {
    signIn(role: 'menejer');
    be.get('/auth/context', (_) => twoBranches());
    await be.run(() => s.load(force: true));
    expect(s.status, SessionStatus.ready);
    expect(s.context!.companyName, 'Fayzan');
    expect(s.can('ombor.view'), isTrue);
    expect(s.can('ombor.edit'), isFalse);
    expect(s.fullAccess, isFalse);
    expect(s.branches.map((b) => b.id), ['b1', 'b2', 'b3']);
    expect(s.selectableBranches.map((b) => b.id), ['b1', 'b2']);
    expect(s.currentBranch!.id, 'b1', reason: 'defaults to the actor branch');
    expect(s.currentIsActor, isTrue);
    expect(s.canSwitchBranch, isTrue);
    expect(s.businessDate(), '2026-09-19');
    expect(s.businessDate('b2'), '2026-09-20');
    expect(s.branchQuery(), {'branch_id': 'b1'});
    // Legacy Api.can sees the fresh permissions too.
    expect(Api.can('ombor.view'), isTrue);
  });

  test('full access roles pass every check (server bypass mirrored)', () async {
    signIn(role: 'administrator');
    be.get('/auth/context', (_) => contextJson(role: 'administrator', permissions: const []));
    await be.run(() => s.load(force: true));
    expect(s.can('xaridlar.edit'), isTrue);
    expect(s.canAny(['anything']), isTrue);
  });

  test('switching branch clears branch-scoped caches, persists per server+company+employee', () async {
    signIn(id: 'e1', role: 'menejer');
    be.get('/auth/context', (_) => twoBranches());
    await be.run(() => s.load(force: true));
    var cleared = 0;
    final unregister = s.registerBranchCache(() => cleared++);
    final keyA = s.cacheKey('products');
    final epoch = s.branchEpoch;
    await s.selectBranch('b2');
    expect(s.currentBranchId, 'b2');
    expect(s.currentIsActor, isFalse);
    expect(cleared, 1);
    expect(s.branchEpoch, epoch + 1);
    expect(s.cacheKey('products'), isNot(keyA), reason: 'A-branch cache never read under B');
    expect(s.branchQuery(), {'branch_id': 'b2'});
    unregister();

    // Invisible or inactive branch cannot be selected.
    expect(() => s.selectBranch('b3'), throwsArgumentError);
    expect(() => s.selectBranch('zzz'), throwsArgumentError);

    // Reload (e.g. app restart): the saved choice comes back for the same user.
    s.debugReset();
    await be.run(() async {
      s.attach(); // attach() starts the load itself
      await s.load();
    });
    expect(s.currentBranchId, 'b2');
    s.detach();

    // Another employee on the same device starts on their own actor branch.
    s.debugReset();
    signIn(id: 'e2', role: 'menejer');
    be.get('/auth/context', (_) => twoBranches()..['employee'] = {'id': 'e2', 'role_code': 'menejer'});
    await be.run(() => s.load(force: true));
    expect(s.currentBranchId, 'b1');
  });

  test('a saved branch that is no longer visible falls back to the actor branch', () async {
    signIn();
    final prefsKey = 'session.branch.${Api.serverKey()}|c1|e1';
    SharedPreferences.setMockInitialValues({prefsKey: 'gone'});
    be.get('/auth/context', (_) => twoBranches(role: 'ega'));
    await be.run(() => s.load(force: true));
    expect(s.currentBranchId, 'b1');
  });

  test('no actor branch and several branches -> no silent guess', () async {
    signIn();
    be.get('/auth/context', (_) => contextJson(branches: [
          branchJson('b1', 'A'),
          branchJson('b2', 'B'),
        ])..['actor_branch'] = null);
    await be.run(() => s.load(force: true));
    expect(s.currentBranch, isNull);
    expect(s.branchQuery(), isEmpty);
  });

  test('single visible branch cannot be switched', () async {
    signIn();
    be.get('/auth/context', (_) => contextJson());
    await be.run(() => s.load(force: true));
    expect(s.canSwitchBranch, isFalse);
    expect(s.currentBranch!.name, 'Markaz');
  });

  test('older server without /auth/context -> degraded mode from the login snapshot', () async {
    signIn(role: 'omborchi', permissions: ['ombor.edit']);
    await be.run(() => s.load(force: true)); // unrouted -> 404
    expect(s.status, SessionStatus.degraded);
    expect(s.can('ombor.edit'), isTrue);
    expect(s.can('hisobot.view'), isFalse);
    expect(s.branches, isEmpty);
    expect(s.currentBranch, isNull);
  });

  test('network error keeps the previous context', () async {
    signIn();
    be.get('/auth/context', (_) => twoBranches());
    await be.run(() => s.load(force: true));
    be.offline = true;
    await be.run(() => s.load(force: true));
    expect(s.status, SessionStatus.ready);
    expect(s.branches, hasLength(3));
    expect(s.lastError, isA<ApiException>());
  });

  test('login/logout through Api.authEpoch reloads / clears the session', () async {
    s.attach();
    be.get('/auth/context', (_) => twoBranches());
    be.post('/auth/login/password', (_) => {
          'access_token': 'T2',
          'employee': {'id': 'e1', 'role_code': 'menejer', 'permissions': []}
        });
    be.post('/auth/logout', (_) => {'ok': true});
    await be.run(() async {
      await Api.login('+996', 'pw');
      await pumpEventQueue();
    });
    expect(s.status, SessionStatus.ready);
    expect(s.currentBranchId, 'b1');
    var cleared = 0;
    s.registerBranchCache(() => cleared++);
    await be.run(() async {
      await Api.logout();
      await pumpEventQueue();
    });
    expect(s.status, SessionStatus.signedOut);
    expect(s.context, isNull);
    expect(s.can('ombor.view'), isFalse);
    expect(cleared, 1, reason: 'sign-out clears branch-scoped caches');
  });

  test('a malformed /auth/context never crashes and keeps the previous context', () async {
    signIn();
    be.get('/auth/context', (_) => twoBranches());
    await be.run(() => s.load(force: true));
    be.get('/auth/context', (_) => {
          'employee': [1, 2]
        });
    await be.run(() => s.load(force: true));
    expect(s.status, SessionStatus.ready);
    expect(s.currentBranchId, 'b1');
    expect(s.lastError, isNotNull);
  });

  test('401 on /auth/context signs out', () async {
    signIn();
    be.get('/auth/context', (_) => FakeResponse.error(401, 'Token yaroqsiz'));
    await be.run(() async {
      await s.load(force: true);
      await pumpEventQueue();
    });
    expect(s.status, SessionStatus.signedOut);
    expect(Api.token, isNull);
  });

  testWidgets('resume refreshes a stale context', (tester) async {
    signIn();
    var calls = 0;
    be.get('/auth/context', (_) {
      calls++;
      return twoBranches();
    });
    await be.run(() async {
      s.attach();
      await tester.pump();
      await s.load(force: true);
      final before = calls;
      Session.resumeRefreshAfter = Duration.zero;
      s.didChangeAppLifecycleState(AppLifecycleState.resumed);
      await tester.pump();
      await s.refreshIfStale(const Duration(hours: 1)); // fresh -> no call
      expect(calls, greaterThan(before));
    });
    Session.resumeRefreshAfter = const Duration(seconds: 20);
    s.detach();
  });

  test('can() is false when signed out even with a stale snapshot', () {
    Api.employee = {'role_code': 'ega', 'permissions': ['x']};
    expect(s.can('x'), isFalse);
  });
}
