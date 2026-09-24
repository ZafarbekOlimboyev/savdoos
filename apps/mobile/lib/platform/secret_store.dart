import 'secret_store_stub.dart'
    if (dart.library.io) 'secret_store_io.dart'
    if (dart.library.js_interop) 'secret_store_web.dart';

export 'secret_store_stub.dart'
    if (dart.library.io) 'secret_store_io.dart'
    if (dart.library.js_interop) 'secret_store_web.dart' show createSecretStore;

/// The FROZEN key names of the secret store. Every installed pilot phone
/// already holds values under these literals; renaming one logs the phone
/// out (token) or strands the one-time plaintext -> secure migration in
/// `Api.load()`. `test/platform_secret_store_test.dart` pins the set.
abstract final class SecretKeys {
  static const String token = 'token';
  static const String employee = 'employee';
  static const String pinHash = 'pin_hash';
  static const String pinSalt = 'pin_salt';
  static const String biometricOn = 'biometric_on';
  static const String lockOn = 'lock_on';
  static const String failCount = 'fail_count';
  static const String lockUntil = 'lock_until';
}

/// Secret storage for the bearer token, the employee snapshot and the PIN
/// hash. Selected by conditional import: Android/iOS -> `flutter_secure_storage`
/// (Keystore / Keychain), web -> see `secret_store_web.dart`.
abstract class SecretStore {
  /// The active store (tests inject a fake).
  static SecretStore instance = createSecretStore();

  /// HONEST flag: true only when the medium is protected by the OS from other
  /// apps/scripts (Android Keystore-wrapped EncryptedSharedPreferences, iOS
  /// Keychain). On web it is FALSE: `flutter_secure_storage_web` keeps the AES
  /// key in `localStorage` next to the ciphertext, so any script in the origin
  /// can read the token — encryption there is not a security boundary.
  bool get isHardwareBacked;

  /// Reads a value (null when absent). May throw when the medium is broken.
  Future<String?> read(String key);

  /// Writes a value. May throw when the medium is broken.
  Future<void> write(String key, String value);

  /// Deletes a value (no error when absent). May throw when the medium is broken.
  Future<void> delete(String key);
}

/// Marker for a store whose contents do NOT survive the app being closed.
///
/// Only the web store is ephemeral today (`SessionSecretStore`, backed by the
/// browser's `sessionStorage`): closing the tab or the installed Home-Screen
/// app ends the session and the operator signs in again. That is a deliberate
/// policy — the threat model is in `secret_store_web_policy.dart` — and it is
/// a behaviour difference, so the UI must say so where the operator sees it
/// before relying on staying signed in.
///
/// It is a marker interface rather than a member on [SecretStore] because
/// every store in the app (and every test fake) uses `implements SecretStore`,
/// where a defaulted member would not be inherited.
abstract interface class EphemeralSecretStore {}

/// The honest persistence flag, for any store.
extension SecretStorePersistence on SecretStore {
  /// Whether a stored value is still there after the app is closed and
  /// reopened. True on every native target (Keystore / Keychain); false for an
  /// [EphemeralSecretStore].
  bool get survivesAppClose => this is! EphemeralSecretStore;
}
