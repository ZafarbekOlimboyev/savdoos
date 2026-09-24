import 'biometrics.dart';

/// Web: NO biometrics. `local_auth` has no web implementation and a browser
/// has no "unlock with Face ID" short of WebAuthn/passkeys (a separate,
/// server-registered feature). The web app lock is PIN / session-timeout based
/// and must never be labelled Face ID.
Biometrics createBiometrics() => const _NoBiometrics();

class _NoBiometrics implements Biometrics {
  const _NoBiometrics();

  @override
  bool get supported => false;

  @override
  Future<bool> available() async => false;

  @override
  Future<bool> authenticate(String reason) async => false;
}
