import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });

  group('JSON helpers', () {
    test('getJson builds the URL + query, sends auth, returns data and headers', () async {
      signIn();
      be.get('/products', (r) => FakeResponse.json([
            {'id': 'p1'}
          ], headers: {'X-Total-Count': '7137'}));
      final res = await be.run(() => Api.getJson('/products', query: {
            'q': 'sut ichimlik',
            'limit': 50,
            'offset': 0,
            'branch_id': null, // skipped
            'tracked': true,
          }));
      expect(res.list, hasLength(1));
      expect(res.totalCount, 7137);
      expect(res.header('X-TOTAL-COUNT'), '7137');
      final r = be.last('GET', '/products');
      expect(r.query, {'q': 'sut ichimlik', 'limit': '50', 'offset': '0', 'tracked': 'true'});
      expect(r.headers['authorization'], 'Bearer test-token');
      expect(r.headers['accept'], 'application/json');
      expect(r.raw.url.toString(), startsWith('http://fake.test/api/v1/products?'));
    });

    test('post/patch/delete send JSON bodies; list query values repeat', () async {
      be.post('/inventory/count', (r) => {'ok': true, 'echo': r.body});
      be.patch('/suppliers/{id}', (r) => {'id': r.params['id'], 'name': r.body['name']});
      be.delete('/employees/{id}', (r) => {'ok': true});
      be.get('/lots/batches', (r) => {'q': r.queryAll['status']});
      await be.run(() async {
        final p = await Api.postJson('/inventory/count', {'items': [], 'client_uuid': 'u1'});
        expect(p.map['echo'], {'items': [], 'client_uuid': 'u1'});
        final pa = await Api.patchJson('/suppliers/${Api.seg('a b')}', {'name': 'X'});
        expect(pa.map, {'id': 'a b', 'name': 'X'});
        final d = await Api.deleteJson('/employees/e9');
        expect(d.map['ok'], true);
        final g = await Api.getJson('/lots/batches', query: {
          'status': ['open', 'depleted']
        });
        expect(g.map['q'], ['open', 'depleted']);
      });
      expect(be.last('POST', '/inventory/count').headers['content-type'], startsWith('application/json'));
    });

    test('a query already in the path is kept', () {
      final u = Api.uri('/sales?limit=3', {'branch_id': 'b1'});
      expect(u.queryParameters, {'limit': '3', 'branch_id': 'b1'});
      expect(Api.uri('/x').hasQuery, isFalse);
    });

    test('.map / .list on a wrong shape is a server error, not a crash', () async {
      be.get('/x', (_) => [1, 2]);
      final res = await be.run(() => Api.getJson('/x'));
      expect(() => res.map, throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.server)));
    });
  });

  group('ApiException', () {
    Future<ApiException> failWith(FakeResponse resp, {String method = 'GET'}) async {
      be.on(method, '/x', (_) => resp);
      try {
        await be.run(() => method == 'GET' ? Api.getJson('/x') : Api.postJson('/x', {}));
      } on ApiException catch (e) {
        return e;
      }
      fail('no exception');
    }

    test('X-Error-Code header is the code; text is kept raw in detail', () async {
      final e = await failWith(FakeResponse.error(409, 'Hisobdan chiqarib bo\'lmadi — ...', code: 'LOT_INVARIANT_BROKEN'),
          method: 'POST');
      expect(e.status, 409);
      expect(e.code, 'LOT_INVARIANT_BROKEN');
      expect(e.kind, ApiErrorKind.business);
      expect(e.detail, "Hisobdan chiqarib bo'lmadi — ...");
      expect(e.isConflict, isTrue);
      expect(e.isConnectivity, isFalse);
    });

    test('CASH_* prefix of the text is the code', () async {
      final e = await failWith(FakeResponse.error(400, "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: 'debt_payment': ..."));
      expect(e.code, 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER');
      final t = await failWith(FakeResponse.error(400, 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER: x'));
      expect(t.code, 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER');
      // An ordinary "Word: text" is not a code.
      final n = await failWith(FakeResponse.error(400, 'Mahsulot topilmadi: p1'));
      expect(n.code, isNull);
    });

    test('dict detail {error, message} (cash posting)', () async {
      final e = await failWith(FakeResponse.error(409, {'error': 'INSUFFICIENT_CASH', 'message': 'Kassada pul yetmaydi'}));
      expect(e.code, 'INSUFFICIENT_CASH');
      expect(e.message, 'Kassada pul yetmaydi');
      expect(e.detail, isA<Map>());
    });

    test('kinds per status', () async {
      final cases = {
        401: ApiErrorKind.auth,
        403: ApiErrorKind.permission,
        404: ApiErrorKind.business,
        409: ApiErrorKind.business,
        422: ApiErrorKind.validation,
        500: ApiErrorKind.server,
        503: ApiErrorKind.server,
      };
      for (final c in cases.entries) {
        final e = await failWith(FakeResponse.error(c.key, 'x'));
        expect(e.kind, c.value, reason: '${c.key}');
      }
    });

    test('422 list detail is flattened for logs, never shown raw', () async {
      final e = await failWith(FakeResponse.error(422, [
        {'loc': ['body', 'qty'], 'msg': 'Input should be greater than 0', 'type': 'greater_than'}
      ]));
      expect(e.message, 'Input should be greater than 0');
      expect(e.toString(), isNot(contains('{')));
      expect(e.toString(), 'Ma’lumotlar noto‘g‘ri to‘ldirilgan — maydonlarni tekshirib, qayta urinib ko‘ring.');
    });

    test('toString() is the localized user message', () async {
      L.code = 'ru';
      final e = await failWith(FakeResponse.error(400, "Qarz yo'q"));
      expect('$e', 'Долга нет');
    });

    test('2xx with a non-JSON body (captive portal) is NOT a success', () async {
      be.post('/cash/ops', (_) => FakeResponse.raw(200, '<html>Wi-Fi login</html>'));
      await expectLater(
        be.run(() => Api.postJson('/cash/ops', {'amount': 1})),
        throwsA(isA<ApiException>()
            .having((e) => e.kind, 'kind', ApiErrorKind.server)
            .having((e) => e.code, 'code', 'BAD_RESPONSE')),
      );
    });

    test('empty 204 body is a success with null data', () async {
      be.delete('/y', (_) => FakeResponse(204));
      final r = await be.run(() => Api.deleteJson('/y'));
      expect(r.status, 204);
      expect(r.data, isNull);
    });
  });

  group('online flag', () {
    test('network failure -> kind network, online=false; next HTTP response -> true', () async {
      be.offline = true;
      await expectLater(
        be.run(() => Api.getJson('/products')),
        throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.network).having((e) => e.status, 's', 0)),
      );
      expect(Api.online.value, isFalse);
      be.offline = false;
      be.get('/products', (_) => FakeResponse.error(500, 'boom'));
      await expectLater(be.run(() => Api.getJson('/products')), throwsA(isA<ApiException>()));
      expect(Api.online.value, isTrue, reason: 'a 500 is still a server answer');
    });

    test('HTTP errors never mark offline', () async {
      be.get('/x', (_) => FakeResponse.error(409, 'band'));
      await expectLater(be.run(() => Api.getJson('/x')), throwsA(isA<ApiException>()));
      expect(Api.online.value, isTrue);
    });

    test('timeout -> kind timeout, online unchanged', () async {
      final never = Completer<Object?>();
      be.get('/slow', (_) => never.future);
      await expectLater(
        be.run(() => Api.getJson('/slow', timeout: const Duration(milliseconds: 50))),
        throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.timeout)),
      );
      expect(Api.online.value, isTrue);
    });

    test('ping', () async {
      be.get('/health', (_) => {'ok': true});
      expect(await be.run(Api.ping), isTrue);
      be.offline = true;
      expect(await be.run(Api.ping), isFalse);
    });
  });

  group('session lifecycle in Api', () {
    test('401 on a normal call clears the session and calls onSessionExpired', () async {
      signIn();
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final epoch = Api.authEpoch.value;
      be.get('/products', (_) => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring'));
      await expectLater(be.run(() => Api.getJson('/products')),
          throwsA(isA<ApiException>().having((e) => e.kind, 'k', ApiErrorKind.auth)));
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(Api.token, isNull);
      expect(Api.employee, isNull);
      expect(expired, 1);
      expect(Api.authEpoch.value, greaterThan(epoch));
    });

    test('a late 401 of the PREVIOUS session does not sign out the user who just signed in', () async {
      signIn(); // employee A
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final gate = Completer<void>();
      be.get('/reports/overview', (_) async {
        await gate.future; // A's slow read (30 s read timeout on a bad line)
        return FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring');
      });
      be.post('/auth/logout', (_) => {'ok': true});
      be.post('/auth/login/password', (_) => {
            'access_token': 'OWNER',
            'employee': {'id': 'e2', 'role_code': 'ega', 'permissions': <String>[]}
          });
      await be.run(() async {
        Object? lateError;
        final slow = Api.getJson('/reports/overview').then<void>((_) {}, onError: (Object e) => lateError = e);
        await Api.logout(); // A hands the phone over (server bumps sec_epoch)
        await Api.login('+998900000001', 'owner-parol-2026'); // the owner signs in, sets a PIN
        gate.complete(); // ... and only now A's 401 arrives
        await slow;
        await Future<void>.delayed(Duration.zero);
        await Future<void>.delayed(Duration.zero);
        expect(lateError, isA<ApiException>(), reason: 'the stale answer never becomes data');
        expect(Api.token, 'OWNER', reason: 'the owner stays signed in');
        expect(Api.employee!['id'], 'e2');
        expect(expired, 0, reason: 'no login screen, no Lock.clear() for the owner');
      });
    });

    test('a late 200 of the PREVIOUS session never reaches the caller', () async {
      signIn();
      final gate = Completer<void>();
      be.get('/products', (_) async {
        await gate.future;
        return [
          {'id': 'p-of-employee-A'}
        ];
      });
      be.post('/auth/logout', (_) => {'ok': true});
      be.post('/auth/login/password', (_) => {
            'access_token': 'OWNER',
            'employee': {'id': 'e2', 'role_code': 'ega'}
          });
      await be.run(() async {
        Object? err;
        ApiResponse? got;
        final slow = Api.getJson('/products').then<void>((r) => got = r, onError: (Object e) => err = e);
        await Api.logout();
        await Api.login('+998900000001', 'owner-parol-2026');
        gate.complete();
        await slow;
        expect(got, isNull, reason: 'employee A\'s list must not render under the owner');
        expect(err, isA<ApiException>().having((e) => e.code, 'code', 'SESSION_CHANGED'));
        expect(Api.token, 'OWNER');
      });
    });

    test('401 on /auth/login* does not log out', () async {
      signIn();
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      be.post('/auth/login/password', (_) => FakeResponse.error(401, "Telefon yoki parol noto'g'ri"));
      await expectLater(be.run(() => Api.login('+996', 'x')), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(Api.token, 'test-token');
      expect(expired, 0);
    });

    test('login stores token/employee and bumps authEpoch', () async {
      be.post('/auth/login/password', (_) => {
            'access_token': 'NEW',
            'employee': {'id': 'e7', 'role_code': 'omborchi', 'permissions': ['ombor.edit']}
          });
      final epoch = Api.authEpoch.value;
      await be.run(() => Api.login('+996555', 'pw'));
      expect(Api.token, 'NEW');
      expect(Api.can('ombor.edit'), isTrue);
      expect(Api.authEpoch.value, epoch + 1);
      expect(PlatformMocks.secure['token'], 'NEW');
    });

    test('setBaseUrl to another server clears token/employee and expires the session', () async {
      signIn();
      Api.baseUrl = 'https://old.example.com';
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final changed = await Api.setBaseUrl('new.example.com/api/v1/');
      expect(changed, isTrue);
      expect(Api.baseUrl, 'https://new.example.com');
      expect(Api.token, isNull);
      expect(Api.employee, isNull);
      expect(expired, 1);
    });

    test('setBaseUrl to the same server keeps the session', () async {
      signIn();
      Api.baseUrl = 'https://same.example.com';
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final changed = await Api.setBaseUrl(' https://same.example.com/ ');
      expect(changed, isFalse);
      expect(Api.token, 'test-token');
      expect(expired, 0);
    });

    test('normalizeBaseUrl', () {
      expect(Api.normalizeBaseUrl(''), 'https://savdoos-production.up.railway.app');
      expect(Api.normalizeBaseUrl('http://10.0.2.2:8000/'), 'http://10.0.2.2:8000');
      expect(Api.normalizeBaseUrl('shop.uz'), 'https://shop.uz');
    });
  });

  group('legacy functions keep working', () {
    test('network errors from legacy calls are ApiException(kind network)', () async {
      be.offline = true;
      await expectLater(be.run(Api.cashOps), throwsA(isA<ApiException>().having((e) => e.kind, 'k', ApiErrorKind.network)));
    });

    test('setPermission goes through the shared transport', () async {
      be.patch('/employees/{id}/permissions', (r) => {'permissions': ['a', 'b']});
      final perms = await be.run(() => Api.setPermission('e1', 'ombor.edit', true));
      expect(perms, ['a', 'b']);
      expect(be.last('PATCH', '/employees/e1/permissions').body, {
        'overrides': {'ombor.edit': true}
      });
    });

    // The pre-5G money/stock writers (payCredit, paySupplier, cashOp, writeoff,
    // stockCount, transfer, commit, createEmployee, ...) sent no payment method,
    // cash account, destination safe or lots. They were removed; every business
    // write now lives in the feature API that carries its full contract. This
    // guard fails if one comes back into the core client.
    test('the core client writes only auth and permission endpoints', () {
      final src = File('lib/api.dart')
          .readAsLinesSync()
          .where((l) => !l.trimLeft().startsWith('//')) // doc examples are not calls
          .join('\n');
      final writes = {
        for (final m in RegExp(r"""\b(_post|postJson|patchJson|putJson|deleteJson)\(\s*'([^']*)'""").allMatches(src))
          '${m[1]} ${m[2]}',
      };
      expect(writes, {
        '_post /auth/logout',
        '_post /auth/login/password',
        '_post /auth/password',
        r'patchJson /employees/${seg(id)}/permissions',
      });
      for (final gone in ['payCredit', 'paySupplier', 'cashOp(', 'stockCount', 'createEmployee', 'editEmployee']) {
        expect(src.contains(gone), isFalse, reason: gone);
      }
    });
  });

  group('logout / 401 clean-up', () {
    test('logout deletes every old catalog cache (any employee/server) and keeps other data', () async {
      signIn();
      final dir = PlatformMocks.tempDir;
      final oldFiles = [
        File('${dir.path}/catalog_e1.json'), // pre-5G key
        File('${dir.path}/catalog_1a2b3c4d_fayzan1_e9.json'), // 5G key of another employee
      ];
      for (final f in oldFiles) {
        f.writeAsStringSync('[{"id":"p1","stock":5}]');
      }
      final keep = File('${dir.path}/other.json')..writeAsStringSync('{}');
      SharedPreferences.setMockInitialValues({'catalog_e1_rev': '7', 'savdoos_lang': 'ru'});
      be.post('/auth/logout', (_) => {'ok': true});
      await be.run(Api.logout);
      expect(be.last('POST', '/auth/logout').headers['authorization'], 'Bearer test-token');
      expect(Api.token, isNull);
      expect(Api.employee, isNull);
      for (final f in oldFiles) {
        expect(f.existsSync(), isFalse, reason: f.path);
      }
      expect(keep.existsSync(), isTrue);
      keep.deleteSync();
      final p = await SharedPreferences.getInstance();
      expect(p.getString('catalog_e1_rev'), isNull);
      expect(p.getString('savdoos_lang'), 'ru');
    });

    test('on 401 the token is gone before the error reaches the caller and before listeners run', () async {
      signIn();
      String? tokenSeenByListener = 'unset';
      void onEpoch() => tokenSeenByListener = Api.token;
      Api.authEpoch.addListener(onEpoch);
      be.get('/products', (_) => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring'));
      try {
        await expectLater(be.run(() => Api.getJson('/products')), throwsA(isA<ApiException>()));
        // No extra event-loop turn: the clean-up's synchronous part already ran.
        expect(Api.token, isNull);
        expect(Api.employee, isNull);
        expect(tokenSeenByListener, isNull);
      } finally {
        Api.authEpoch.removeListener(onEpoch);
      }
      await Future<void>.delayed(Duration.zero);
    });
  });

  group('DraftUuid', () {
    test('same draft -> same uuid; changed draft -> new; rotate -> new', () {
      final k = DraftUuid();
      final a = k.forDraft({'qty': 1});
      expect(k.forDraft({'qty': 1}), a);
      final b = k.forDraft({'qty': 2});
      expect(b, isNot(a));
      k.rotate();
      expect(k.forDraft({'qty': 2}), isNot(b));
      expect(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$').hasMatch(k.current), isTrue);
    });
  });
}
