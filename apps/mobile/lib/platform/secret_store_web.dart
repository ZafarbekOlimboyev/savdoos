import 'dart:js_interop';

import 'secret_store.dart';
import 'secret_store_web_policy.dart';

/// Web: the token, the employee snapshot and the PIN hash live in the
/// browser's **sessionStorage**, so they die when the tab — or the installed
/// Home-Screen app — is closed.
///
/// This replaces `flutter_secure_storage_web`, which was not a security
/// boundary here: it exported its raw AES-GCM key into `localStorage` next to
/// the ciphertext (`flutter_secure_storage_web.dart:96-118`), so an XSS in the
/// origin recovered the token in six lines — the B-phase audit did exactly
/// that from the JS console. Encryption bought nothing against the only
/// attacker a browser has, and it bought persistence, which is the part that
/// actually hurt: a shop iPhone is shared, and a persisted token means the
/// next person to tap the icon is the previous employee.
///
/// The full threat model, including what this does NOT fix (XSS itself), is in
/// `secret_store_web_policy.dart`. The operator is told about the trade on
/// every launch (`web/index.html#binos-session-notice`).
SecretStore createSecretStore() => SessionSecretStore(const _BrowserMedium());

/// `window.sessionStorage` / `window.localStorage`.
extension type _Storage._(JSObject _) implements JSObject {
  external int get length;
  external String? key(int index);
  external String? getItem(String key);
  external void setItem(String key, String value);
  external void removeItem(String key);
}

@JS('sessionStorage')
external _Storage get _sessionStorage;

@JS('localStorage')
external _Storage get _localStorage;

/// The browser binding. Every call is guarded: Safari in private mode, a
/// blocked-storage setting or an evicted partition all throw on access, and a
/// broken medium must degrade to "not signed in", never to a crash at boot.
class _BrowserMedium implements WebSecretMedium {
  const _BrowserMedium();

  @override
  String? read(String key) {
    try {
      return _sessionStorage.getItem(key);
    } catch (_) {
      return null; /* storage blocked — treat as empty */
    }
  }

  @override
  void write(String key, String value) {
    try {
      _sessionStorage.setItem(key, value);
    } catch (_) {
      /* storage blocked or full — the session stays in memory only */
    }
  }

  @override
  void delete(String key) {
    try {
      _sessionStorage.removeItem(key);
    } catch (_) {
      /* nothing to delete when the medium is unavailable */
    }
  }

  @override
  List<String> persistentKeys() {
    final keys = <String>[];
    try {
      for (var i = 0; i < _localStorage.length; i++) {
        final k = _localStorage.key(i);
        if (k != null) keys.add(k);
      }
    } catch (_) {
      /* nothing to clean up when localStorage is unavailable */
    }
    return keys;
  }

  @override
  void deletePersistent(String key) {
    try {
      _localStorage.removeItem(key);
    } catch (_) {
      /* best-effort eviction */
    }
  }
}
