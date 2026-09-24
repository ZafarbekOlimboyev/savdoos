import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';

import 'platform/platform.dart';

/// Ilova qulfi — bir marta login qilgach 4 xonali PIN o'rnatiladi. Keyin ilovani
/// ochganda PIN yoki biometrik (barmoq izi / Face ID) so'raladi. PIN xeshi (SHA-256 + tuz)
/// qurilmaning xavfsiz xotirasida (Android Keystore) saqlanadi — ochiq matnda emas.
///
/// Platforma: xotira — [SecretStore] (kalit nomlari MUZLATILGAN, [SecretKeys]),
/// biometrika — [Biometrics]. Web'da ikkalasi ham "haqiqiy" emas
/// (`isHardwareBacked == false`, `supported == false`) — UI shuni aytishi kerak.
class Lock {
  static SecretStore get _store => SecretStore.instance;
  static Biometrics get _auth => Biometrics.instance;

  static String? _hash;
  static String? _salt;
  static bool biometricOn = false;
  static bool lockOn = true;
  static int _fails = 0;          // ketma-ket noto'g'ri urinishlar
  static int _lockUntil = 0;      // qulf tugash vaqti (epoch ms)

  static Future<void> load() async {
    try {
      _hash = await _store.read(SecretKeys.pinHash);
      _salt = await _store.read(SecretKeys.pinSalt);
      biometricOn = (await _store.read(SecretKeys.biometricOn)) == '1';
      final lo = await _store.read(SecretKeys.lockOn);
      lockOn = lo == null ? true : lo == '1';
      _fails = int.tryParse(await _store.read(SecretKeys.failCount) ?? '0') ?? 0;
      _lockUntil = int.tryParse(await _store.read(SecretKeys.lockUntil) ?? '0') ?? 0;
    } catch (_) {
      _hash = null;
      _salt = null;
      biometricOn = false;
      lockOn = true;
      _fails = 0;
      _lockUntil = 0;
    }
  }

  // ── Brute-force lockout ──
  static const _wipeAt = 12;   // shundan ko'p urinishда sessiya tozalanadi (parol bilan qayta kirish)

  /// Qulf tugashiga qolgan soniya (0 = qulf yo'q). Ilova o'chib yonса ham saqlanadi.
  static int lockRemaining() {
    final now = DateTime.now().millisecondsSinceEpoch;
    return _lockUntil > now ? ((_lockUntil - now) / 1000).ceil() : 0;
  }

  static int get failCount => _fails;

  /// Noto'g'ri PIN — sanoqni oshiradi, 5+ da eskalatsiyali qulflaydi. Qaytaradi: sessiyани
  /// tozalash kerakmi (juda ko'p urinish → parol bilan qayta kirish).
  static Future<bool> registerFail() async {
    _fails++;
    await _store.write(SecretKeys.failCount, '$_fails');
    if (_fails >= _wipeAt) return true;
    if (_fails >= 5) {
      final secs = (30 * (1 << (_fails - 5))).clamp(30, 900); // 30s,60,120,… max 15 daq
      _lockUntil = DateTime.now().millisecondsSinceEpoch + secs * 1000;
      await _store.write(SecretKeys.lockUntil, '$_lockUntil');
    }
    return false;
  }

  static Future<void> registerSuccess() async {
    _fails = 0;
    _lockUntil = 0;
    try {
      await _store.delete(SecretKeys.failCount);
      await _store.delete(SecretKeys.lockUntil);
    } catch (_) {}
  }

  static bool get hasPin => _hash != null && _hash!.isNotEmpty;

  /// Ilova ochilganda qulf ko'rsatilsinmi (PIN bor va qulf yoqilgan).
  static bool get shouldLock => hasPin && lockOn;

  // ── Fonga ketib qaytganda qayta qulflash ──
  //
  // Ilgari qulf faqat SOVUQ ishga tushishda chiqardi: telefon ochiq qolib, ilova fonda
  // turgan bo'lsa, istalgan kishi uni PIN'siz qayta ochardi. Endi ilova [relockAfter]
  // dan uzoq fonda qolsa, qaytishda qulf ekrani ko'rsatiladi. Qisqa chiqishlar (kamera
  // bilan nakladnoyni suratga olish, ulashish oynasi, biometrik dialog) qulflamaydi.

  /// Fonda shundan uzoq qolsa qaytishda PIN so'raladi.
  static Duration relockAfter = const Duration(minutes: 3);

  static DateTime? _backgroundAt;

  /// Ilova fonga ketdi (`paused`/`hidden`). Birinchi belgi saqlanadi.
  static void markBackground([DateTime? now]) {
    _backgroundAt ??= now ?? DateTime.now();
  }

  /// Ilova qaytdi: qulf ekrani ko'rsatilishi kerakmi? Belgi har chaqiruvda tozalanadi.
  static bool consumeResume([DateTime? now]) {
    final at = _backgroundAt;
    _backgroundAt = null;
    if (at == null || !shouldLock) return false;
    return (now ?? DateTime.now()).difference(at) >= relockAfter;
  }

  /// Test uchun: fon belgisini tozalaydi.
  static void debugResetBackground() => _backgroundAt = null;

  static String _hashPin(String pin, String salt) =>
      sha256.convert(utf8.encode('$salt:$pin')).toString();

  static Future<void> setPin(String pin) async {
    final salt = _randSalt();
    _salt = salt;
    _hash = _hashPin(pin, salt);
    lockOn = true;
    await _store.write(SecretKeys.pinSalt, salt);
    await _store.write(SecretKeys.pinHash, _hash!);
    await _store.write(SecretKeys.lockOn, '1');
  }

  static bool verify(String pin) =>
      hasPin && _salt != null && _hashPin(pin, _salt!) == _hash;

  static Future<void> setBiometric(bool on) async {
    biometricOn = on;
    await _store.write(SecretKeys.biometricOn, on ? '1' : '0');
  }

  static Future<void> setLockEnabled(bool on) async {
    lockOn = on;
    await _store.write(SecretKeys.lockOn, on ? '1' : '0');
  }

  /// Chiqishда qulf ma'lumotini tozalaymiz — boshqa foydalanuvchi kirsa yangi PIN qo'yiladi.
  static Future<void> clear() async {
    _hash = null;
    _salt = null;
    biometricOn = false;
    lockOn = true;
    _fails = 0;
    _lockUntil = 0;
    _backgroundAt = null;
    try {
      await _store.delete(SecretKeys.pinHash);
      await _store.delete(SecretKeys.pinSalt);
      await _store.delete(SecretKeys.biometricOn);
      await _store.delete(SecretKeys.lockOn);
      await _store.delete(SecretKeys.failCount);
      await _store.delete(SecretKeys.lockUntil);
    } catch (_) {}
  }

  static String _randSalt() {
    final r = Random.secure();
    return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }

  /// Bu PLATFORMA biometrikani umuman qo'llaydimi (web: yo'q — Face ID deb
  /// yozish mumkin emas). Qurilmada ro'yxatga olinganmi — [biometricAvailable].
  static bool get biometricsSupported => _auth.supported;

  /// Biometrik mavjudmi — qurilma qo'llab-quvvatlaydi va kamida bittasi ro'yxatga olingan.
  static Future<bool> biometricAvailable() => _auth.available();

  static Future<bool> authenticate(String reason) => _auth.authenticate(reason);
}
