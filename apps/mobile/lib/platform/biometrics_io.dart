import 'package:local_auth/local_auth.dart';

import 'biometrics.dart';

/// Android/iOS (`local_auth`). Bodies moved verbatim from `Lock` (pre-5G.1).
Biometrics createBiometrics() => _NativeBiometrics();

class _NativeBiometrics implements Biometrics {
  final _auth = LocalAuthentication();

  @override
  bool get supported => true;

  @override
  Future<bool> available() async {
    try {
      final supported = await _auth.isDeviceSupported();
      final canCheck = await _auth.canCheckBiometrics;
      if (!supported && !canCheck) return false;
      final list = await _auth.getAvailableBiometrics();
      return list.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<bool> authenticate(String reason) async {
    try {
      return await _auth.authenticate(
        localizedReason: reason,
        options: const AuthenticationOptions(
          biometricOnly: true,
          stickyAuth: true,
          useErrorDialogs: true,
        ),
      );
    } catch (_) {
      return false;
    }
  }
}
