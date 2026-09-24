import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'secret_store.dart';

/// `flutter_secure_storage`-backed store shared by the io and web adapters.
///
/// ⚠️  The construction below is BYTE-IDENTICAL to what `Api` and `Lock` used
///     before Phase 5G.1 (`AndroidOptions(encryptedSharedPreferences: true)`,
///     default key prefix / preferences name). Changing any option changes the
///     Android backing file and logs every pilot phone out.
class PluginSecretStore implements SecretStore {
  /// Creates the store; [hardwareBacked] is decided by the platform file.
  const PluginSecretStore({required bool hardwareBacked}) : _hardwareBacked = hardwareBacked;

  /// The plugin instance (one for the whole app, as before).
  static const FlutterSecureStorage storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  final bool _hardwareBacked;

  @override
  bool get isHardwareBacked => _hardwareBacked;

  @override
  Future<String?> read(String key) => storage.read(key: key);

  @override
  Future<void> write(String key, String value) => storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => storage.delete(key: key);
}
