// SecretStore adapter (B4 item 2) — the highest-risk change: it holds the
// bearer token, the employee snapshot and the PIN hash on every pilot phone.
// Key names and AndroidOptions are frozen; the plaintext->secure migration in
// Api.load() must still run; the hardware-backed flag must be honest.
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/platform/secret_store_io.dart' as io;
import 'package:shared_preferences/shared_preferences.dart';

import 'support/support.dart';

/// The exact key set every installed phone already holds. Renaming one logs
/// every pilot phone out (or strands the migration) — this list is the contract.
const frozenKeys = {'token', 'employee', 'pin_hash', 'pin_salt', 'biometric_on', 'lock_on', 'fail_count', 'lock_until'};

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    await Lock.clear();
    be = FakeBackend();
  });

  tearDown(() => Lock.clear());

  test('key names are frozen: the constants are the literal keys', () {
    expect(
      {
        SecretKeys.token,
        SecretKeys.employee,
        SecretKeys.pinHash,
        SecretKeys.pinSalt,
        SecretKeys.biometricOn,
        SecretKeys.lockOn,
        SecretKeys.failCount,
        SecretKeys.lockUntil,
      },
      frozenKeys,
    );
  });

  test('Api and Lock write exactly the frozen keys, nothing else', () async {
    be.post('/auth/login/password', (_) => {
          'access_token': 'T1',
          'employee': {'id': 'e1', 'role_code': 'ega'}
        });
    await be.run(() => Api.login('+996555', 'pw'));
    await Lock.setPin('2468');
    await Lock.setBiometric(true);
    await Lock.setLockEnabled(true);
    for (var i = 0; i < 5; i++) {
      await Lock.registerFail(); // 5th failure writes lock_until
    }
    expect(PlatformMocks.secure.keys.toSet(), frozenKeys);
    expect(PlatformMocks.secure['token'], 'T1');
    expect(jsonDecode(PlatformMocks.secure['employee']!)['id'], 'e1');
  });

  test('the io adapter keeps AndroidOptions(encryptedSharedPreferences: true) byte-for-byte', () {
    final store = io.createSecretStore();
    expect(store.isHardwareBacked, isTrue);
    expect(io.debugAndroidOptions(store), const AndroidOptions(encryptedSharedPreferences: true).toMap());
    expect(io.debugAndroidOptions(store)['encryptedSharedPreferences'], 'true');
  });

  test('the plaintext -> secure migration in Api.load() still runs through the adapter', () async {
    await resetCore(prefs: {'token': 'legacy-tok', 'employee': '{"id":"e9","role_code":"kassir"}'});
    await Api.load();
    expect(Api.token, 'legacy-tok');
    expect(Api.employee!['id'], 'e9');
    expect(PlatformMocks.secure['token'], 'legacy-tok', reason: 'moved into the secure store');
    expect(PlatformMocks.secure['employee'], '{"id":"e9","role_code":"kassir"}');
    final p = await SharedPreferences.getInstance();
    expect(p.getString('token'), isNull, reason: 'plaintext copy deleted');
    expect(p.getString('employee'), isNull);
  });

  test('a secure value wins over a stale plaintext one', () async {
    await resetCore(prefs: {'token': 'old-plain'});
    PlatformMocks.secure['token'] = 'secure-tok';
    await Api.load();
    expect(Api.token, 'secure-tok');
  });

  test('logout deletes token and employee from the store, and Lock.clear() the rest', () async {
    await resetCore(prefs: {}, secureValues: {for (final k in frozenKeys) k: 'x'});
    signIn();
    be.post('/auth/logout', (_) => {'ok': true});
    await be.run(Api.logout);
    expect(PlatformMocks.secure.containsKey('token'), isFalse);
    expect(PlatformMocks.secure.containsKey('employee'), isFalse);
    await Lock.clear();
    expect(PlatformMocks.secure, isEmpty);
  });

  test('a failing store never blocks start-up or logout (fail-soft, as before)', () async {
    SecretStore.instance = _BrokenStore();
    await resetCore(prefs: {'token': 'legacy'});
    SecretStore.instance = _BrokenStore();
    await Api.load();
    expect(Api.token, 'legacy', reason: 'kept in memory for this session when the store is broken');
    Api.token = 't';
    await Api.logout();
    expect(Api.token, isNull);
    await Lock.load();
    expect(Lock.hasPin, isFalse);
  });

  test('the fake used by the whole suite is honest about itself', () {
    expect(SecretStore.instance, isA<FakeSecretStore>());
    expect(SecretStore.instance.isHardwareBacked, isTrue, reason: 'tests model the Android phone by default');
    expect(FakeSecretStore({}, hardwareBacked: false).isHardwareBacked, isFalse);
  });
}

class _BrokenStore implements SecretStore {
  @override
  bool get isHardwareBacked => false;

  @override
  Future<void> delete(String key) => throw StateError('store down');

  @override
  Future<String?> read(String key) => throw StateError('store down');

  @override
  Future<void> write(String key, String value) => throw StateError('store down');
}
