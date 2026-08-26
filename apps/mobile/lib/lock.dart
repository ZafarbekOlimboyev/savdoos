import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

/// Ilova qulfi — bir marta login qilgach 4 xonali PIN o'rnatiladi. Keyin ilovani
/// ochganda PIN yoki biometrik (barmoq izi / Face ID) so'raladi. PIN xeshi (SHA-256 + tuz)
/// qurilmaning xavfsiz xotirasida (Android Keystore) saqlanadi — ochiq matnda emas.
class Lock {
  static const _store = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static final _auth = LocalAuthentication();

  static String? _hash;
  static String? _salt;
  static bool biometricOn = false;
  static bool lockOn = true;

  static Future<void> load() async {
    try {
      _hash = await _store.read(key: 'pin_hash');
      _salt = await _store.read(key: 'pin_salt');
      biometricOn = (await _store.read(key: 'biometric_on')) == '1';
      final lo = await _store.read(key: 'lock_on');
      lockOn = lo == null ? true : lo == '1';
    } catch (_) {
      _hash = null;
      _salt = null;
      biometricOn = false;
      lockOn = true;
    }
  }

  static bool get hasPin => _hash != null && _hash!.isNotEmpty;

  /// Ilova ochilganda qulf ko'rsatilsinmi (PIN bor va qulf yoqilgan).
  static bool get shouldLock => hasPin && lockOn;

  static String _hashPin(String pin, String salt) =>
      sha256.convert(utf8.encode('$salt:$pin')).toString();

  static Future<void> setPin(String pin) async {
    final salt = _randSalt();
    _salt = salt;
    _hash = _hashPin(pin, salt);
    lockOn = true;
    await _store.write(key: 'pin_salt', value: salt);
    await _store.write(key: 'pin_hash', value: _hash);
    await _store.write(key: 'lock_on', value: '1');
  }

  static bool verify(String pin) =>
      hasPin && _salt != null && _hashPin(pin, _salt!) == _hash;

  static Future<void> setBiometric(bool on) async {
    biometricOn = on;
    await _store.write(key: 'biometric_on', value: on ? '1' : '0');
  }

  static Future<void> setLockEnabled(bool on) async {
    lockOn = on;
    await _store.write(key: 'lock_on', value: on ? '1' : '0');
  }

  /// Chiqishда qulf ma'lumotini tozalaymiz — boshqa foydalanuvchi kirsa yangi PIN qo'yiladi.
  static Future<void> clear() async {
    _hash = null;
    _salt = null;
    biometricOn = false;
    lockOn = true;
    try {
      await _store.delete(key: 'pin_hash');
      await _store.delete(key: 'pin_salt');
      await _store.delete(key: 'biometric_on');
      await _store.delete(key: 'lock_on');
    } catch (_) {}
  }

  static String _randSalt() {
    final r = Random.secure();
    return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }

  /// Biometrik mavjudmi — qurilma qo'llab-quvvatlaydi va kamida bittasi ro'yxatga olingan.
  static Future<bool> biometricAvailable() async {
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

  static Future<bool> authenticate(String reason) async {
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
