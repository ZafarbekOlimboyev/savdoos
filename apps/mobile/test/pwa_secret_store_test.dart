// C1 (Phase 5G.1) — the web auth-token policy.
//
// Measured in the B4 audit: on web `flutter_secure_storage` exports its raw
// AES-GCM key into `localStorage` right next to the ciphertext, so a token was
// recovered from the JS console in six lines. "Encrypted" bought nothing
// against the only attacker a browser has (a script running in the origin) —
// and it bought something worse: PERSISTENCE. A Home-Screen PWA on a shared
// shop iPhone has no user separation, so a token in `localStorage` means the
// next person to tap the icon is signed in as the previous employee, for as
// long as the token lives.
//
// The policy this file pins:
//   1. web secrets live in SESSION storage — they die when the tab / the
//      installed app is closed. This does not defeat XSS (nothing in a browser
//      does, short of an HttpOnly cookie, which is a server change and out of
//      scope); it bounds the window and it kills the shared-phone case.
//   2. the store is honest: `isHardwareBacked == false`,
//      `survivesAppClose == false`. Android is untouched and still says true.
//   3. nothing is ever written to the PERSISTENT medium, and credentials an
//      older policy left in `localStorage` are evicted on start-up — without
//      touching the ordinary preferences (`flutter.base_url`, language, theme,
//      the last branch), which are not secrets.
//
// VM only: the policy is pure Dart on purpose, so it is testable here rather
// than only in a browser.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/platform/secret_store_io.dart' as io;
import 'package:savdoos_mobile/platform/secret_store_web_policy.dart';

/// Records everything, so the test can assert what was NOT done too.
class FakeMedium implements WebSecretMedium {
  final Map<String, String> session = {};
  final Map<String, String> persistent = {};
  final List<String> persistentWrites = [];
  final List<String> persistentDeletes = [];

  @override
  String? read(String key) => session[key];

  @override
  void write(String key, String value) => session[key] = value;

  @override
  void delete(String key) => session.remove(key);

  @override
  List<String> persistentKeys() => persistent.keys.toList();

  @override
  void deletePersistent(String key) {
    persistentDeletes.add(key);
    persistent.remove(key);
  }
}

void main() {
  group('the web store is session-scoped and says so', () {
    test('it is honest about its medium', () {
      final s = SessionSecretStore(FakeMedium());
      expect(s.isHardwareBacked, isFalse, reason: 'no browser storage is protected from a script in the origin');
      expect(s.survivesAppClose, isFalse, reason: 'closing the Home-Screen app must sign the operator out');
    });

    test('Android/iOS native storage is untouched and still persistent', () {
      final native = io.createSecretStore();
      expect(native.isHardwareBacked, isTrue);
      expect(native.survivesAppClose, isTrue, reason: 'the pilot phones must not start re-authenticating');
    });

    test('read/write/delete round-trip through the session medium only', () async {
      final m = FakeMedium();
      final s = SessionSecretStore(m);
      expect(await s.read(SecretKeys.token), isNull);
      await s.write(SecretKeys.token, 'TOK-1');
      expect(await s.read(SecretKeys.token), 'TOK-1');
      await s.delete(SecretKeys.token);
      expect(await s.read(SecretKeys.token), isNull);
      expect(m.persistentWrites, isEmpty);
    });

    test('keys are namespaced so a co-hosted app cannot collide with them', () async {
      final m = FakeMedium();
      await SessionSecretStore(m).write(SecretKeys.token, 'T');
      expect(m.session.keys.single, startsWith(SessionSecretStore.keyPrefix));
      expect(m.session.keys.single, endsWith(SecretKeys.token));
      expect(SessionSecretStore.keyPrefix, isNot('FlutterSecureStorage'),
          reason: 'the plugin used one fixed global slot for every Flutter app on the origin');
    });

    test('every frozen key still round-trips (Api and Lock keep working on web)', () async {
      final m = FakeMedium();
      final s = SessionSecretStore(m);
      const keys = [
        SecretKeys.token,
        SecretKeys.employee,
        SecretKeys.pinHash,
        SecretKeys.pinSalt,
        SecretKeys.biometricOn,
        SecretKeys.lockOn,
        SecretKeys.failCount,
        SecretKeys.lockUntil,
      ];
      for (final k in keys) {
        await s.write(k, 'v-$k');
      }
      for (final k in keys) {
        expect(await s.read(k), 'v-$k', reason: k);
      }
      expect(m.session.length, keys.length);
    });
  });

  group('credentials an older policy persisted are evicted; preferences are not', () {
    test('the eviction list is exactly the flutter_secure_storage_web slots and the legacy plaintext token', () {
      final all = [
        'FlutterSecureStorage', // the exported raw AES key
        'FlutterSecureStorage.token',
        'FlutterSecureStorage.pin_hash',
        'flutter.token', // pre-5G plaintext token, migrated by Api.load()
        'flutter.employee',
        'flutter.base_url',
        'flutter.savdoos_lang',
        'flutter.savdoos_theme',
        'flutter.session.branch.https://x|c1|e1',
        'something.else',
      ];
      expect(
        legacyPersistentSecretKeys(all).toSet(),
        {'FlutterSecureStorage', 'FlutterSecureStorage.token', 'FlutterSecureStorage.pin_hash', 'flutter.token', 'flutter.employee'},
      );
    });

    test('constructing the store evicts them from the persistent medium', () {
      final m = FakeMedium()
        ..persistent.addAll({
          'FlutterSecureStorage': 'raw-aes-key',
          'FlutterSecureStorage.token': 'iv.ciphertext',
          'flutter.base_url': 'https://staging',
          'flutter.savdoos_lang': 'uzc',
        });
      SessionSecretStore(m);
      expect(m.persistentDeletes.toSet(), {'FlutterSecureStorage', 'FlutterSecureStorage.token'});
      expect(m.persistent.keys.toSet(), {'flutter.base_url', 'flutter.savdoos_lang'},
          reason: 'server address, language, theme and branch are settings, not credentials');
    });

    test('the plugin deleteAll() hazard is gone: the whole origin is never wiped', () {
      final m = FakeMedium()..persistent.addAll({'flutter.savdoos_theme': 'dark'});
      SessionSecretStore(m);
      expect(m.persistent, isNotEmpty,
          reason: 'flutter_secure_storage_web.deleteAll() removed every localStorage entry, prefs included');
    });
  });

  group('the web adapter really uses that policy', () {
    late String src;

    setUp(() => src = File('lib/platform/secret_store_web.dart').readAsStringSync());

    test('it no longer goes through flutter_secure_storage', () {
      expect(src, isNot(contains('PluginSecretStore')));
      // The doc comment still NAMES the plugin (that is the history a reader
      // needs); what must be gone is the dependency on it.
      expect(src, isNot(contains("import 'package:flutter_secure_storage/")));
      expect(src, contains('SessionSecretStore'));
    });

    test('it binds the session medium, and touches localStorage only to evict', () {
      expect(src, contains('sessionStorage'));
      expect(RegExp(r'localStorage\.setItem').hasMatch(src), isFalse, reason: 'no secret may become persistent');
      expect(src, contains('localStorage.removeItem'), reason: 'the eviction path needs it');
    });

    test('the threat model is written down where the next reader will look', () {
      expect(src.toUpperCase(), contains('XSS'));
      expect(src, contains('sessionStorage'));
    });
  });
}
