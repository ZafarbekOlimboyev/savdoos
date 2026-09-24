import 'secret_store.dart';

/// Neither `dart:io` nor `dart:js_interop` (no such Flutter target today):
/// an in-memory store so the app still boots; nothing survives a restart.
SecretStore createSecretStore() => _MemorySecretStore();

class _MemorySecretStore implements SecretStore {
  final Map<String, String> _m = {};

  @override
  bool get isHardwareBacked => false;

  @override
  Future<String?> read(String key) async => _m[key];

  @override
  Future<void> write(String key, String value) async => _m[key] = value;

  @override
  Future<void> delete(String key) async => _m.remove(key);
}
