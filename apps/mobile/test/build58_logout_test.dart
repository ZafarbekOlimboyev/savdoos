import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'shell_settings_test.dart' as settings;
import 'support/support.dart';

class DelayedCache implements LocalCache {
  final started = Completer<void>();
  final release = Completer<void>();
  @override
  Future<void> purgeCatalogFiles() async {
    if (!started.isCompleted) started.complete();
    await release.future;
  }
}

class DelayedTokenDeletion extends FakeSecretStore {
  DelayedTokenDeletion(super.map);
  final started = Completer<void>();
  final release = Completer<void>();

  @override
  Future<void> delete(String key) async {
    if (key == SecretKeys.token) {
      started.complete();
      await release.future;
    }
    await super.delete(key);
  }
}

void main() {
  setUp(() async {
    await resetCore(
      prefs: {'token': 'legacy-token', 'employee': '{}', 'catalog_e1_rev': '7'},
      secureValues: {SecretKeys.token: 'test-token', SecretKeys.employee: '{}'},
    );
    await Lock.clear();
  });
  tearDown(() async {
    Session.instance.debugReset();
    await Lock.clear();
  });

  testWidgets(
      'parallel 401 cleanup must finish deleting stored credentials before logout completes',
      (t) async {
    final store = DelayedTokenDeletion(PlatformMocks.secure);
    SecretStore.instance = store;
    LocalCache.instance = DelayedCache()..release.complete();
    final reply = Completer<Object?>();
    final be = FakeBackend()
      ..post('/auth/logout', (_) => reply.future)
      ..get('/products', (_) => FakeResponse.error(401, 'Expired'));
    await be.run(() async {
      signIn();
      final epoch = Api.authEpoch.value;
      var done = false;
      final logout = Api.logout().then((_) => done = true);
      await t.pump();
      await expectLater(Api.getJson('/products'), throwsA(isA<ApiException>()));
      await t.pump();
      expect(store.started.isCompleted, isTrue);
      expect(Api.token, isNull);
      reply.complete({'ok': true});
      await t.pump();
      expect(done, isFalse,
          reason:
              'the 401 owns cleanup but its secure deletion is still pending');
      store.release.complete();
      await t.pump();
      await logout;
      expect(PlatformMocks.secure[SecretKeys.token], isNull);
      expect(PlatformMocks.secure[SecretKeys.employee], isNull);
      expect(Api.authEpoch.value, epoch + 1);
    });
  });

  for (final status in [200, 401]) {
    testWidgets('Shell logout navigates after cache yields, status $status',
        (t) async {
      final be = FakeBackend()
        ..get('/auth/context', (_) => contextJson(role: 'menejer'))
        ..post(
            '/auth/logout',
            (_) => status == 200
                ? {'ok': true}
                : FakeResponse.error(401, 'Expired'));
      final cache = DelayedCache();
      LocalCache.instance = cache;
      await be.run(() async {
        signIn(role: 'menejer');
        await Lock.setPin('1234');
        Session.instance.attach();
        await Session.instance.load();
        await pumpAt390(
            t,
            Shell(tabBuilders: {
              ShellTab.home: (_) => const SizedBox(),
              ShellTab.settings: (_) => const SettingsScreen(),
            }));
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key('tab-settings')));
        await t.pumpAndSettle();
        await settings.tapRow(t, 'settings-logout');
        final oldEpoch = Api.authEpoch.value;
        await t.tap(find.byKey(const Key('confirm-yes')));
        await t.pump();
        await t.pump(const Duration(milliseconds: 400));
        expect(cache.started.isCompleted, isTrue);
        expect(Api.token, isNull);
        expect(Api.employee, isNull);
        expect(Api.authEpoch.value, oldEpoch + 1);
        expect(PlatformMocks.secure[SecretKeys.token], isNull);
        expect(PlatformMocks.secure[SecretKeys.employee], isNull);
        final prefs = await SharedPreferences.getInstance();
        expect(prefs.containsKey('token'), isFalse);
        expect(prefs.containsKey('employee'), isFalse);
        expect(prefs.containsKey('catalog_e1_rev'), isFalse);
        // authEpoch removes SettingsScreen while its logout is awaiting IO.
        expect(find.byType(SettingsScreen), findsNothing);
        cache.release.complete();
        await t.pumpAndSettle();
        expect(Lock.hasPin, isFalse);
        expect(find.byType(LoginScreen), findsOneWidget);
        expect(find.byKey(const Key('shell-loading')), findsNothing);
        expect(be.last('POST', '/auth/logout').headers['authorization'],
            'Bearer test-token');
      });
    });
  }

  testWidgets(
      'delayed revocation still uses the old token and cleans up after its reply',
      (t) async {
    LocalCache.instance = DelayedCache()..release.complete();
    final reply = Completer<Object?>();
    final be = FakeBackend()..post('/auth/logout', (_) => reply.future);
    await be.run(() async {
      signIn();
      final oldEpoch = Api.authEpoch.value;
      var done = false;
      final logout = Api.logout().then((_) => done = true);
      await t.pump();
      await t.pump(const Duration(seconds: 2));
      expect(done, isFalse);
      expect(be.last('POST', '/auth/logout').headers['authorization'],
          'Bearer test-token');
      reply.complete({'ok': true});
      await t.pump();
      await logout;
      expect(Api.token, isNull);
      expect(Api.authEpoch.value, oldEpoch + 1);
    });
  });

  testWidgets(
      'logout times out promptly; late 401 polling cannot clear a new session',
      (t) async {
    final logoutReply = Completer<Object?>();
    final pollReply = Completer<Object?>();
    final cache = DelayedCache()..release.complete();
    LocalCache.instance = cache;
    final be = FakeBackend()
      ..post('/auth/logout', (_) => logoutReply.future)
      ..get('/products', (_) => pollReply.future);
    await be.run(() async {
      signIn();
      final oldEpoch = Api.authEpoch.value;
      final poll = Api.getJson('/products');
      final pollCheck = expectLater(
          poll,
          throwsA(isA<ApiException>()
              .having((e) => e.code, 'code', Api.kStaleSession)));
      var done = false;
      final logout = Api.logout().then((_) => done = true);
      await t.pump();
      expect(be.calls('POST', '/auth/logout'), hasLength(1));
      await t.pump(const Duration(seconds: 6));
      expect(done, isTrue,
          reason: 'local logout must not await the 60-second write timeout');
      await logout;
      expect(Api.authEpoch.value, oldEpoch + 1);
      expect(Api.token, isNull);
      expect(PlatformMocks.secure[SecretKeys.token], isNull);
      signIn(id: 'new-user');
      Api.authEpoch.value++;
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      logoutReply.complete(FakeResponse.error(401, 'Old logout'));
      pollReply.complete(FakeResponse.error(401, 'Old polling'));
      await t.pump();
      await pollCheck;
      expect(Api.employee?['id'], 'new-user');
      expect(expired, 0);
    });
  });

  testWidgets(
      'polling 401 during logout does not let its late reply clear a new session',
      (t) async {
    final logoutReply = Completer<Object?>();
    LocalCache.instance = DelayedCache()..release.complete();
    final be = FakeBackend()
      ..post('/auth/logout', (_) => logoutReply.future)
      ..get('/products', (_) => FakeResponse.error(401, 'Expired'));
    await be.run(() async {
      signIn();
      final logout = Api.logout();
      await t.pump();
      await expectLater(Api.getJson('/products'), throwsA(isA<ApiException>()));
      await t.pump();
      expect(Api.token, isNull);
      signIn(id: 'new-user');
      Api.authEpoch.value++;
      final newEpoch = Api.authEpoch.value;
      logoutReply.complete({'ok': true});
      await t.pump();
      await logout;
      expect(Api.employee?['id'], 'new-user');
      expect(Api.authEpoch.value, newEpoch);
    });
  });
}
