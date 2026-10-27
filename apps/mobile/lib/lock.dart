import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';

import 'platform/platform.dart';

/// Xavfsiz xotira ilova qulfi haqida NIMA deya oldi.
///
/// ⚠️  «PIN yo'q» va «PIN borligini bilib bo'lmadi» BIR XIL emas. Ilgari
///     ikkalasi ham `hasPin == false` ga aylanardi, ya'ni o'qish xatosi
///     himoyalangan qobiqni JIMGINA ochardi (fail-open). Shu sababli holat
///     endi to'rtga ajratiladi va qobiq faqat [absent]/[valid] da ochiladi.
enum LockStatus {
  /// O'qildi — saqlangan PIN yo'q (yangi o'rnatma yoki chiqishdan keyin).
  absent,

  /// O'qildi — xesh va tuz joyida, kiritilgan PIN tekshirila oladi.
  valid,

  /// O'qildi — lekin juftlik buzilgan: biri yo'q yoki shakli bizning
  /// yozuvimizga o'xshamaydi. Hech qanday PIN tasdiqlanmaydi.
  corrupt,

  /// O'qishning O'ZI yiqildi (iOS Keychain hali qulflangan, Keystore nosoz,
  /// tiklanishdan keyin access-group mos emas) — holat NOMA'LUM.
  unavailable,
}

/// `sha256` ning onaltilik ko'rinishi — [Lock._hashPin] shuni chiqaradi.
const int _kHashHexLen = 64;

/// 16 baytli tuz onaltilikda — [Lock._randSalt] shuni chiqaradi.
const int _kSaltHexLen = 32;

bool _isLowerHex(String s, int len) {
  if (s.length != len) return false;
  for (final c in s.codeUnits) {
    final digit = c >= 0x30 && c <= 0x39; // 0-9
    final lower = c >= 0x61 && c <= 0x66; // a-f
    if (!digit && !lower) return false;
  }
  return true;
}

/// Xom o'qish natijasini holatga aylantiradi — toza funksiya, shuning uchun
/// har bir chegara holati alohida tekshirilishi mumkin.
///
/// [readOk] — PIN kalitlarining IKKALASI ham xatosiz o'qildimi. Yolg'on bo'lsa
/// qiymatlarga QARALMAYDI: yarim o'qishdan «PIN bor» yoki «PIN yo'q» degan
/// xulosa chiqarish mumkin emas.
LockStatus classifyLock({required bool readOk, required String? hash, required String? salt}) {
  if (!readOk) return LockStatus.unavailable;
  final h = hash ?? '';
  final s = salt ?? '';
  if (h.isEmpty && s.isEmpty) return LockStatus.absent;
  if (!_isLowerHex(h, _kHashHexLen) || !_isLowerHex(s, _kSaltHexLen)) return LockStatus.corrupt;
  return LockStatus.valid;
}

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

  /// ⚠️  Boshlang'ich qiymat YOPIQ. `main()` `runApp` dan oldin [load] ni
  ///     kutadi, lekin standart qiymat `absent` bo'lsa — ya'ni «PIN yo'q, qobiq
  ///     ochilsin» — har qanday kelgusi yo'l (test, boshqa kirish nuqtasi,
  ///     `load` dan oldingi kadr) jimgina fail-open bo'lardi.
  static LockStatus _status = LockStatus.unavailable;

  /// Har [clear] da oshadi — yozuv davomida chiqish bo'lganini aniqlash uchun.
  static int _epoch = 0;

  /// Xavfsiz xotira qulf haqida nima deya oldi (qarang: [LockStatus]).
  static LockStatus get status => _status;

  /// Qulf HOZIR ekranni egallab turganmi (fondan qaytgandan keyingi qulf).
  ///
  /// ⚠️  Bu faqat UI bayrog'i EMAS, balki BIZNES AMALLARI uchun ham darvoza.
  ///     `IgnorePointer` foydalanuvchi tegishini to'sadi, lekin kamera oqimi,
  ///     taymerlar va async davomlar tegishga BOG'LIQ EMAS — ular qulf ostida
  ///     ishlashda davom etadi. O'lchangan natija: qulflangan ilovadan
  ///     AUTHENTICATED `GET /products/scan` so'rovi ketardi
  ///     (`test/lock_bypass_test.dart`). Shu bois foydalanuvchi tegishidan
  ///     mustaqil har qanday manba shu bayroqni O'ZI tekshirishi SHART.
  static final ValueNotifier<bool> engaged = ValueNotifier<bool>(false);

  /// Holat ANIQ: xotira javob berdi va javobi mazmunli. Yolg'on bo'lsa
  /// himoyalangan qobiq OCHILMASLIGI kerak — PIN bor-yo'qligini bilmaymiz.
  ///
  /// ⚠️  Darvoza [shouldLock] ga EMAS, shu bayroqqa tayanadi: buzilgan yoki
  ///     o'qilmagan holatda `shouldLock` ham yolg'on bo'ladi (tekshiriladigan
  ///     xesh yo'q), ya'ni «qulf shart emas» degan XATO xulosa chiqadi.
  static bool get statusKnown => _status == LockStatus.absent || _status == LockStatus.valid;

  /// `true` — PIN holatini xavfsiz xotiradan O'QIB BO'LMADI. Bu "PIN yo'q"
  /// degani EMAS, shu bois UI buni "qulf o'chirilgan" deb ko'rsatmasligi kerak.
  static bool get loadFailed => _status == LockStatus.unavailable;

  /// Bitta kalitni o'qish: `(qiymat, muvaffaqiyatli_mi)`.
  static Future<(String?, bool)> _read(String key) async {
    try {
      return (await _store.read(key), true);
    } catch (_) {
      return (null, false);
    }
  }

  /// Har kalit ALOHIDA o'qiladi.
  ///
  /// ⚠️  Ilgari bitta `try` hammasini qamrab olgan edi: ikkinchi darajali
  ///     kalitning (`biometric_on`, `lock_on`, `fail_count`, `lock_until`)
  ///     xatosi MUVAFFAQIYATLI o'qilgan PIN xeshini ham `null` qilib,
  ///     ilovani JIMGINA qulfsiz ochardi. Endi faqat PIN kalitlarining
  ///     xatosi PIN holatiga ta'sir qiladi va u [status] bilan oshkor etiladi.
  static Future<void> load() async {
    final epoch = _epoch;
    final (hash, hashOk) = await _read(SecretKeys.pinHash);
    final (salt, saltOk) = await _read(SecretKeys.pinSalt);
    final (bio, _) = await _read(SecretKeys.biometricOn);
    final (lo, loOk) = await _read(SecretKeys.lockOn);
    final (fc, _) = await _read(SecretKeys.failCount);
    final (lu, _) = await _read(SecretKeys.lockUntil);
    if (epoch != _epoch) {
      // O'qish davomida [clear] ishladi (401 / chiqish). Diskdan kelgan
      // qiymatlar ESKI sessiyaga tegishli: ularni xotiraga qaytarsak, chiqqan
      // xodimning PIN'i keyingi xodimning sessiyasini qo'riqlardi.
      return;
    }
    _status = classifyLock(readOk: hashOk && saltOk, hash: hash, salt: salt);
    // Faqat TEKSHIRILA OLADIGAN juftlik xotirada qoladi: buzilgan juftlik
    // `hasPin` ni rost qilsa, foydalanuvchi hech qachon mos tushmaydigan
    // PIN'ni cheksiz kiritardi. Buzilgan holatda chiqish yo'li — parol.
    final usable = _status == LockStatus.valid;
    _hash = usable ? hash : null;
    _salt = usable ? salt : null;
    biometricOn = bio == '1';
    // ⚠️  `'0'` dan BOSHQA har qanday qiymat (bo'sh satr, buzilgan bayt) qulfni
    //     YOQILGAN deb hisoblanadi. Ilgari shart `lo == '1'` edi: diskdagi
    //     buzilgan qiymat qulfni JIMGINA o'chirardi, holbuki o'qish xatosi
    //     to'g'ri ravishda `true` berardi.
    lockOn = loOk ? (lo != '0') : true;
    _fails = int.tryParse(fc ?? '0') ?? 0;
    _lockUntil = int.tryParse(lu ?? '0') ?? 0;
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
  ///
  /// ⚠️  Sanoqni SAQLAY olmaslik (xotira yozuvi yiqilgan) qulf ekranini ishdan
  ///     chiqarmasligi kerak: ilgari bu yerdan otilgan xato `_check()` ni
  ///     to'xtatib, ekranni javobsiz qoldirardi. Xotiradagi eskalatsiya va
  ///     [_wipeAt] baribir ishlaydi; qolgan xavf — yozuv buzilgan qurilmada
  ///     sanoq ilova qayta ishga tushganda nolga qaytishi.
  static Future<bool> registerFail() async {
    _fails++;
    await _tryWrite(SecretKeys.failCount, '$_fails');
    if (_fails >= _wipeAt) return true;
    if (_fails >= 5) {
      final secs = (30 * (1 << (_fails - 5))).clamp(30, 900); // 30s,60,120,… max 15 daq
      _lockUntil = DateTime.now().millisecondsSinceEpoch + secs * 1000;
      await _tryWrite(SecretKeys.lockUntil, '$_lockUntil');
    }
    return false;
  }

  /// Qulfni KUCHSIZLANTIRMAYDIGAN yozuv: xatosi e'tiborsiz qoldiriladi.
  static Future<void> _tryWrite(String key, String value) async {
    try {
      await _store.write(key, value);
    } catch (_) {}
  }

  static Future<void> registerSuccess() async {
    _fails = 0;
    _lockUntil = 0;
    await _tryDelete(SecretKeys.failCount);
    await _tryDelete(SecretKeys.lockUntil);
  }

  /// Qulfni KUCHSIZLANTIRMAYDIGAN o'chirish: xatosi e'tiborsiz qoldiriladi,
  /// lekin KEYINGI kalitni to'xtatmaydi (qarang: [clear]).
  static Future<void> _tryDelete(String key) async {
    try {
      await _store.delete(key);
    } catch (_) {}
  }

  static bool get hasPin => _hash != null && _hash!.isNotEmpty;

  /// Kiritilgan PIN so'ralishi kerakmi (PIN bor va qulf yoqilgan).
  ///
  /// ⚠️  Bu YAKUNIY darvoza EMAS. Holat noma'lum bo'lganda (`corrupt`,
  ///     `unavailable`) tekshiriladigan xesh yo'q, shuning uchun bu yerda
  ///     yolg'on qaytadi — «qulf shart emas» degani EMAS. Qobiqni ochish
  ///     qaroriga [statusKnown] bilan birga keling (`lockGateHome()`).
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
    // Holat noma'lum — qancha vaqt o'tganidan qat'i nazar YOPIQ. Bu holatda
    // qobiqda bo'lishning o'zi mumkin emas (darvoza o'tkazmaydi), shu bois bu
    // ikkinchi qator himoya.
    if (!statusKnown) return true;
    if (at == null || !shouldLock) return false;
    final elapsed = (now ?? DateTime.now()).difference(at);
    // ⚠️  MANFIY davomiylik = soat ORQAGA surilgan. Ilgari bu `false` berardi,
    //     ya'ni telefon Sozlamalarida sanani orqaga surish qayta qulflashni
    //     BUTUNLAY chetlab o'tardi. Vaqtga ishonib bo'lmasa — QULFLAYMIZ.
    if (elapsed.isNegative) return true;
    return elapsed >= relockAfter;
  }

  /// Test uchun: fon belgisini tozalaydi.
  static void debugResetBackground() => _backgroundAt = null;

  static String _hashPin(String pin, String salt) =>
      sha256.convert(utf8.encode('$salt:$pin')).toString();

  /// PIN o'rnatish. Tuz va xesh BIRGA amal qiladi — biri yozilib ikkinchisi
  /// yozilmasa qulf ishlamaydi.
  ///
  /// ⚠️  Ilgari xotiradagi qiymatlar yozuvdan OLDIN o'rnatilardi va yozuv
  ///     ketma-ket, himoyasiz ketardi. Tuz yozilib xesh yozilmaganda:
  ///     joriy sessiyada `hasPin` true (qulf bor ko'rinadi), lekin keyingi
  ///     ishga tushishda xesh yo'q -> `shouldLock` false -> ilova QULFSIZ
  ///     ochilardi, foydalanuvchi esa PIN qo'yganiga ishonardi.
  ///     Endi: yozuv muvaffaqiyatli bo'lsa — xotira yangilanadi; xato bo'lsa —
  ///     qisman yozuv O'CHIRILADI va xato chaqiruvchiga uzatiladi (UI xabar
  ///     beradi, foydalanuvchi qayta uriniadi).
  ///
  /// ⚠️  Yozuv davomida [clear] chaqirilsa (401 kelib sessiya bekor bo'ldi)
  ///     bu PIN endi BOSHQA xodimning sessiyasiga tegishli bo'lardi: shu bois
  ///     u diskdan olib tashlanadi va xato otiladi.
  static Future<void> setPin(String pin) async {
    final epoch = _epoch;
    final prevHash = _hash;
    final prevSalt = _salt;
    final hadPin = _status == LockStatus.valid && prevHash != null && prevSalt != null;
    final salt = _randSalt();
    final hash = _hashPin(pin, salt);
    try {
      await _store.write(SecretKeys.pinSalt, salt);
      await _store.write(SecretKeys.pinHash, hash);
      await _store.write(SecretKeys.lockOn, '1');
    } catch (_) {
      await _rollbackPin(prevHash, prevSalt, hadPin: hadPin, epoch: epoch);
      rethrow;
    }
    if (epoch != _epoch) {
      // Sessiya tugadi: yangi PIN ham, ESKISI ham endi hech kimga tegishli
      // emas — ikkisi ham o'chiriladi (bu O'TKINCHI xato emas, chiqish).
      await _discardPin();
      throw StateError('qulf PIN yozuvi davomida tozalandi');
    }
    _salt = salt;
    _hash = hash;
    lockOn = true;
    _status = LockStatus.valid;
  }

  /// Yozuv yiqildi — holatni xavfsiz joyga qaytarish.
  ///
  /// ⚠️  ISHLAYOTGAN PIN'ni o'tkinchi xato sabab YO'Q QILIB BO'LMAYDI. Ilgari
  ///     bu yerda [_discardPin] shartsiz chaqirilardi: PIN'ni ALMASHTIRISH
  ///     yiqilsa (Keychain to'lgan/nosoz) eski, mukammal ishlayotgan juftlik
  ///     ham o'chib ketardi -> holat `absent` -> keyingi ishga tushishda ilova
  ///     QULFSIZ ochilardi. Endi avval eski juftlik tiklanadi; tiklash ham
  ///     yiqilsa holat YOPIQ ([LockStatus.unavailable]) bo'ladi — `absent`
  ///     EMAS, aks holda aynan shu nuqson qaytardi.
  /// ⚠️  [epoch] — yozuv BOSHLANGANDA olingan nav. Tiklash o'tkinchi xatoni
  ///     SESSIYA TUGASHIDAN ajrata olishi SHART: 401 kelib [clear] hamma
  ///     kalitni o'chirgach eski juftlikni qaytarish chiqib ketgan xodimning
  ///     PIN'ini TIRILTIRARDI va u keyingi xodimning sessiyasini qo'riqlardi.
  static Future<void> _rollbackPin(String? prevHash, String? prevSalt,
      {required bool hadPin, required int epoch}) async {
    if (!hadPin || epoch != _epoch) {
      // Yo birinchi marta o'rnatish edi (yo'qotadigan narsa yo'q), yo sessiya
      // tugadi (eski PIN ham endi hech kimga tegishli emas).
      await _discardPin();
      return;
    }
    // Uch yozuvning QAYSI biri o'tganini bilmaymiz, shu bois ikkisini ham
    // qayta yozamiz...
    await _tryWrite(SecretKeys.pinSalt, prevSalt!);
    await _tryWrite(SecretKeys.pinHash, prevHash!);
    // ...keyin DISKDAN O'QIB tasdiqlaymiz. Yozuv xatosi «eski PIN yo'qoldi»
    // degani EMAS: masalan xesh yozuvi yiqilgan bo'lsa, diskdagi ESKI xesh
    // umuman o'zgarmagan bo'ladi va juftlik butun qoladi. Taxmin qilish bu
    // yerda ishlayotgan qulfni bekorga yo'qotardi.
    final (hash, hashOk) = await _read(SecretKeys.pinHash);
    final (salt, saltOk) = await _read(SecretKeys.pinSalt);
    // Epoch QAYTA tekshiriladi: yuqoridagi `await`lar davomida ham chiqish
    // bo'lishi mumkin edi.
    if (epoch != _epoch) {
      await _discardPin();
      return;
    }
    if (hashOk && saltOk && hash == prevHash && salt == prevSalt) {
      _hash = prevHash;
      _salt = prevSalt;
      _status = LockStatus.valid; // eski PIN hanuz amalda
      return;
    }
    // Tiklanmadi. Holat YOPIQ bo'ladi — `absent` desak keyingi ishga tushishda
    // ilova QULFSIZ ochilardi, ya'ni aynan S3 nuqsoni qaytardi.
    _hash = null;
    _salt = null;
    _status = LockStatus.unavailable;
  }

  /// Qisman yozilgan PIN'ni xotiradan ham, xavfsiz xotiradan ham olib tashlash.
  static Future<void> _discardPin() async {
    _hash = null;
    _salt = null;
    _status = LockStatus.absent;
    await _tryDelete(SecretKeys.pinHash);
    await _tryDelete(SecretKeys.pinSalt);
  }

  static bool verify(String pin) =>
      hasPin && _salt != null && _hashPin(pin, _salt!) == _hash;

  /// ⚠️  Xotiraga YOZIB bo'lgach xotiradagi qiymat yangilanadi: aks holda
  ///     yozuv xatosi «yoqilgan» ko'rinib, qayta ishga tushishda o'chib
  ///     qolardi — ya'ni foydalanuvchi yoqqan himoya jimgina yo'qolardi.
  static Future<void> setBiometric(bool on) async {
    await _store.write(SecretKeys.biometricOn, on ? '1' : '0');
    biometricOn = on;
  }

  /// ⚠️  Yozuv BIRINCHI. `setBiometric` dagi sabab bu yerda yanada og'ir:
  ///     «Ochishda PIN so'ralsin» ni QAYTA YOQQANDA yozuv yiqilsa, xotira
  ///     «yoqilgan» deb turardi-yu, keyingi ishga tushishda diskdagi `'0'`
  ///     o'qilib ilova QULFSIZ ochilardi.
  static Future<void> setLockEnabled(bool on) async {
    await _store.write(SecretKeys.lockOn, on ? '1' : '0');
    lockOn = on;
  }

  /// Chiqishда qulf ma'lumotini tozalaymiz — boshqa foydalanuvchi kirsa yangi PIN qo'yiladi.
  static Future<void> clear() async {
    _epoch++;
    _hash = null;
    _salt = null;
    _status = LockStatus.absent;
    biometricOn = false;
    lockOn = true;
    _fails = 0;
    _lockUntil = 0;
    _backgroundAt = null;
    // Chiqish/401: qulf qatlami ham yopiladi — aks holda login ekrani uning
    // OSTIDA qolib ketardi.
    engaged.value = false;
    // ⚠️  Har kalit ALOHIDA o'chiriladi. Ilgari bitta `try` hammasini qamrab
    //     olgani uchun BIRINCHI xato qolgan beshta kalitni diskda qoldirardi:
    //     chiqqan xodimning `lock_on`, `biometric_on` va urinish sanog'i
    //     keyingi xodimga o'tib ketardi.
    for (final key in const [
      SecretKeys.pinHash,
      SecretKeys.pinSalt,
      SecretKeys.biometricOn,
      SecretKeys.lockOn,
      SecretKeys.failCount,
      SecretKeys.lockUntil,
    ]) {
      await _tryDelete(key);
    }
    // ⚠️  Epoch IKKI marta oshadi — boshida va oxirida. Boshidagisi yozuv
    //     o'rtasida kelgan chiqishni tutadi; oxirgisi esa o'chirishlar DAVOMIDA
    //     boshlangan [setPin] ni: u ham eskirgan epoch bilan qaytadi va PIN'ni
    //     o'rnatgan deb YOLG'ON hisobot bermaydi.
    _epoch++;
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
