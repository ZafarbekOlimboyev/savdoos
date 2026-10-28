import 'package:flutter/foundation.dart';

/// Sessiya tugaganda ekran bilan birga yo'qolib ketadigan SAQLANMAGAN
/// qoralamalarning qisqa muddatli saqlagichi.
///
/// ⚠️  NEGA KERAK. 401 (12 soatlik token muddati — `access_token_minutes = 720`,
///     parol tiklanishi, boshqa qurilmada chiqish) `main.dart` da
///     `pushAndRemoveUntil(..., (route) => false)` ni ishga soladi: BUTUN route
///     stack yo'q qilinadi va ochiq shakllardagi qo'l kiritmasi OGOHLANTIRISHSIZ
///     ketadi. Fayzan, 2026-09-17: menejer tuzatish yozayotganda ega xodim
///     parolini tikladi va kiritilgan hammasi jimgina yo'qoldi.
///
/// ⚠️  DISKKA YOZILMAYDI — ATAYLAB. Qoralamalar maxfiy biznes ma'lumoti
///     (narx, miqdor, mijoz, yetkazuvchi). Ularni sandbox'ga yozish 401
///     tozalashi YETIB BORMAYDIGAN yangi maxfiylik yuzasi ochadi: `_clearLocal`
///     faqat Keychain va `catalog_*.json` ni oladi. Diskda saqlash — alohida
///     mahsulot/xavfsizlik qarori, bu sinf uni QILMAYDI.
///
/// ⚠️  EGALIK QAT'IY. Har yozuv o'z DOIRASI bilan saqlanadi
///     (`Session.cacheKey` — server|kompaniya|xodim|filial). [claim] faqat
///     AYNI doira uchun qaytaradi; begona urinish yozuvni O'CHIRADI. Shu
///     sababli boshqa xodim, boshqa kompaniya yoki boshqa filial oldingisining
///     kiritmasini hech qachon ko'rmaydi.
///
/// ⚠️  AUTH HIMOYASINI CHETLAB O'TMAYDI. Bu sinf na token tekshiradi, na
///     sessiyani uzaytiradi, na 401 ni to'sadi. U faqat ekran matnini eslab
///     qoladi. Qulf (PIN/Face ID) va server 401 o'z yo'lida ishlaydi:
///     qoralamani qaytarish uchun foydalanuvchi QAYTA AUTENTIFIKATSIYA
///     qilishi SHART.
abstract final class DraftVault {
  /// Bir vaqtda saqlanadigan eng ko'p yozuv. Chegaradan oshsa ENG ESKISI
  /// tushib qoladi — xotira cheksiz o'smaydi.
  static const int maxEntries = 8;

  /// Kiritilish tartibini saqlaydi (Dart `Map` — `LinkedHashMap`), shu bois
  /// `keys.first` eng eski yozuv.
  static final Map<String, _Entry> _byKey = {};

  /// [draft] ni [name] ostida eslab qoladi.
  ///
  /// [scope] — yozuvning egasi. U qoralama kiritilayotgan paytda (ekran
  /// `initState`) olinishi SHART: 401 ishlovchisi `Api.employee` ni
  /// `authEpoch` oshishidan OLDIN null qiladi, ya'ni tozalash paytida
  /// egalikni aniqlab bo'lmaydi.
  ///
  /// Doira noma'lum xodimni ko'rsatsa — yozuv SAQLANMAYDI (fail-closed).
  static void stash(String name, Object draft, {required String scope}) {
    if (!_knownOwner(scope)) return;
    // Qayta yozish tartibni ham yangilaydi: eng yangi yozuv oxirida turadi.
    _byKey.remove(name);
    _byKey[name] = _Entry(scope, draft);
    while (_byKey.length > maxEntries) {
      _byKey.remove(_byKey.keys.first);
    }
  }

  /// [name] qoralamasini QAYTARADI va o'chiradi — bir martalik.
  ///
  /// Doira mos kelmasa `null` qaytaradi va yozuvni HAM o'chiradi: begona
  /// sessiya tegingan qoralama endi hech kimga ochilmaydi.
  static Object? claim(String name, {required String scope}) {
    final e = _byKey.remove(name);
    if (e == null) return null;
    return e.scope == scope ? e.draft : null;
  }

  /// [name] uchun AYNI doirada qoralama bor-yo'qligi. O'chirmaydi.
  static bool has(String name, {required String scope}) {
    final e = _byKey[name];
    return e != null && e.scope == scope;
  }

  /// Hammasini o'chiradi — chiqish, hisob almashishi va qulf tozalanishida.
  static void evictAll() => _byKey.clear();

  /// Saqlangan qoralama bormi. 401 ishlovchisi xabar matnini shunga qarab
  /// tanlaydi: yo'qotish bo'lmasa SOXTA ogohlantirish berilmaydi.
  static bool get isNotEmpty => _byKey.isNotEmpty;

  /// Doira xodimni aniq ko'rsatadimi.
  ///
  /// `Session.cacheKey` formati: `<nom>@<serverKey>|<kompaniya>|<xodim>|<filial>`.
  /// Kirilmagan holatda kompaniya va xodim `-` bo'ladi.
  static bool _knownOwner(String scope) {
    final parts = scope.split('|');
    if (parts.length < 3) return false;
    final employee = parts[2].trim();
    return employee.isNotEmpty && employee != '-';
  }

  @visibleForTesting
  static void debugClear() => _byKey.clear();

  @visibleForTesting
  static int get debugCount => _byKey.length;
}

class _Entry {
  _Entry(this.scope, this.draft);
  final String scope;
  final Object draft;
}
