/// The web auth-token policy — pure Dart on purpose, so it can be tested on
/// the VM (`test/pwa_secret_store_test.dart`) instead of only in a browser.
/// The browser bindings live in `secret_store_web.dart`.
///
/// ## Threat model (Phase 5G.1, package C1)
///
/// The store holds the bearer token, the employee snapshot and the PIN hash.
/// On Android those sit in Keystore-wrapped `EncryptedSharedPreferences`, so
/// another app cannot read them. **A browser has no equivalent.**
///
/// What the previous adapter did, measured in the B-phase audit:
/// `flutter_secure_storage_web 1.2.1` generates an AES-GCM-256 key, exports it
/// **raw**, and writes it to `localStorage` under the fixed global slot
/// `"FlutterSecureStorage"` — right next to the ciphertext it protects
/// (`flutter_secure_storage_web.dart:96-118`). The audit recovered a plaintext
/// token from the JS console in six lines. So on web the encryption is
/// decoration: it stops nobody, and it costs the one thing that actually
/// matters here — it makes the credential **persistent**.
///
/// Threats, and what this policy does about each:
///
/// * **Script injection (XSS) in the origin.** Not defeated. Nothing in a
///   browser defeats it while the app is open short of an `HttpOnly` cookie,
///   which is a server change (session issuance + CSRF) and out of scope for
///   5G.1. The mitigations that do apply are in `web/index.html`: a
///   `script-src 'self'` CSP, no inline script, no third-party script, and the
///   ZXing library vendored instead of pulled from unpkg at run time. This is
///   stated plainly rather than papered over.
/// * **A shared shop phone.** Defeated. An installed Home-Screen PWA has one
///   storage partition and no user separation: a token in `localStorage` means
///   whoever taps the icon next is signed in as the previous employee, for as
///   long as the token lives. Session storage dies with the tab / the
///   installed app, so closing it ends the session.
/// * **A token sitting on the device for days waiting to be scraped.** Bounded
///   to one app session, instead of the token's full 12-hour life plus
///   whatever `localStorage` retains afterwards.
/// * **Credentials an older policy already persisted.** Evicted on start-up —
///   see [legacyPersistentSecretKeys]. Preferences (server address, language,
///   theme, last branch) are not credentials and are left alone.
///
/// The cost is real and the operator is told about it on every launch
/// (`web/index.html#binos-session-notice`): closing the app means signing in
/// again. That is the trade this package chose, and it is visible rather than
/// silent.
///
/// The token is never put in a URL, never logged, and never reachable by the
/// service worker (`web/sw.js` refuses to intercept anything cross-origin,
/// non-GET, under an API path, or carrying an `Authorization` header).
library;

import 'secret_store.dart';

/// The browser storage this policy talks to, as two flat key/value media.
///
/// Split into "session" (what the app uses) and "persistent" (what it only
/// cleans up) so the policy can be exercised without a browser.
abstract class WebSecretMedium {
  /// Reads from the SESSION medium.
  String? read(String key);

  /// Writes to the SESSION medium.
  void write(String key, String value);

  /// Deletes from the SESSION medium.
  void delete(String key);

  /// Every key currently in the PERSISTENT medium (`localStorage`).
  List<String> persistentKeys();

  /// Deletes one key from the PERSISTENT medium.
  void deletePersistent(String key);
}

/// The `localStorage` keys that hold (or held) a credential and must be
/// evicted, given [all] keys currently present.
///
/// Exactly two families, and nothing else:
///
/// * `FlutterSecureStorage` and `FlutterSecureStorage.<key>` — the exported
///   AES key and every value the previous web adapter wrote;
/// * `flutter.token` / `flutter.employee` — the pre-5G plaintext pair that
///   `Api.load()` migrates out of `SharedPreferences`. On web there has never
///   been a released build that wrote them, but leaving a plaintext token in
///   `localStorage` forever is not a risk worth carrying for symmetry.
///
/// Everything else under the `flutter.` prefix is a SETTING — `base_url`,
/// `savdoos_lang`, `savdoos_theme`, `session.branch.<scope>` — and is left
/// untouched. (The old plugin's `deleteAll()` wiped the entire origin,
/// preferences included; that hazard disappears with the plugin.)
List<String> legacyPersistentSecretKeys(Iterable<String> all) => [
      for (final k in all)
        if (k == _pluginSlot || k.startsWith('$_pluginSlot.') || k == 'flutter.token' || k == 'flutter.employee') k,
    ];

const String _pluginSlot = 'FlutterSecureStorage';

/// A [SecretStore] over the browser's SESSION storage.
///
/// Honest by construction: [isHardwareBacked] is `false` (no browser medium is
/// protected from a script in the origin) and it is an [EphemeralSecretStore],
/// so `survivesAppClose` is `false` — that is the point. See the library
/// comment for the threat model.
class SessionSecretStore implements SecretStore, EphemeralSecretStore {
  /// Binds the store to [_medium] and evicts anything an older policy
  /// persisted.
  SessionSecretStore(this._medium) {
    purgeLegacyPersistentSecrets();
  }

  /// Namespace for this app's session keys.
  ///
  /// The old plugin used one fixed global slot (`FlutterSecureStorage`) with
  /// no app namespacing, so any other Flutter-web app on the same origin shared
  /// it. This prefix is ours.
  static const String keyPrefix = 'binos.session.';

  final WebSecretMedium _medium;

  @override
  bool get isHardwareBacked => false;

  @override
  Future<String?> read(String key) async => _medium.read('$keyPrefix$key');

  @override
  Future<void> write(String key, String value) async => _medium.write('$keyPrefix$key', value);

  @override
  Future<void> delete(String key) async => _medium.delete('$keyPrefix$key');

  /// Removes credentials an older policy left in the persistent medium.
  /// Returns how many keys were removed.
  int purgeLegacyPersistentSecrets() {
    var removed = 0;
    for (final k in legacyPersistentSecretKeys(_medium.persistentKeys())) {
      _medium.deletePersistent(k);
      removed++;
    }
    return removed;
  }

  /// Never prints a value.
  @override
  String toString() => 'SessionSecretStore(sessionStorage, $keyPrefix*)';
}
