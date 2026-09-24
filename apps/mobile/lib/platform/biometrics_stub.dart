import 'biometrics.dart';

/// Unknown target: no biometrics.
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
