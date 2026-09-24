import 'biometrics_stub.dart'
    if (dart.library.io) 'biometrics_io.dart'
    if (dart.library.js_interop) 'biometrics_web.dart';

export 'biometrics_stub.dart'
    if (dart.library.io) 'biometrics_io.dart'
    if (dart.library.js_interop) 'biometrics_web.dart' show createBiometrics;

/// Device biometrics (fingerprint / Face ID) for the app lock.
///
/// Two different truths the UI must be able to tell apart:
///  * [supported] — this PLATFORM can do biometrics at all (false on web:
///    there is no `local_auth` web implementation and no Face ID without a
///    WebAuthn path); a web UI must never say "Face ID";
///  * [available] — the device supports it AND at least one is enrolled.
abstract class Biometrics {
  /// The active adapter (tests inject a fake).
  static Biometrics instance = createBiometrics();

  /// The platform has a native biometric path.
  bool get supported;

  /// Device supported and at least one biometric enrolled. Never throws.
  Future<bool> available();

  /// Prompts the operator; true on success. Never throws.
  Future<bool> authenticate(String reason);
}
