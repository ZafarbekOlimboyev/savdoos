import 'package:flutter/foundation.dart';

import 'l10n.dart';

/// Sessiya nega tugaganini bildiradi.
enum SessionEndReason {
  /// Server 401 qaytardi: token muddati tugadi (`access_token_minutes = 720`),
  /// parol tiklandi yoki boshqa qurilmada chiqildi.
  expired,

  /// Sozlamalarda server manzili almashdi (`Api.setBaseUrl`) — eski token
  /// yangi serverga yuborilmaydi.
  serverChanged,

  /// Foydalanuvchi O'ZI chiqdi. Bu holatda xabar KERAK EMAS: u nima
  /// qilganini biladi.
  loggedOut,
}

/// Login ekranida BIR MARTA ko'rsatiladigan "sessiya tugadi" xabari.
///
/// ⚠️  NEGA ALOHIDA SINF. `main.dart` dagi 401 ishlovchisi
///     `pushAndRemoveUntil(..., (route) => false)` chaqiradi. Xabarni SHU
///     yerda ko'rsatish ishonchsiz: `(route) => false` stack'ni bo'shatgach
///     login YAKKA route bo'lib qoladi, ya'ni `nav.canPop()` shartiga
///     qurilgan xabar HECH QACHON chiqmaydi, va `ScaffoldMessenger` yo'q
///     qilinayotgan `Scaffold` ga tushadi. Shu bois xabar bu yerda
///     KO'TARILADI, login ekrani esa uni o'z `initState` ida ISTE'MOL qiladi
///     — ya'ni u allaqachon o'rnatilgan va ko'rinadigan bo'ladi.
///
/// ⚠️  BIR MARTALIK. `consume()` xabarni o'chiradi: til almashishi yoki
///     qayta qurilish uni takrorlamaydi.
abstract final class SessionNotice {
  static SessionEndNotice? _pending;

  /// Kutayotgan xabar (iste'mol qilmaydi) — testlar va diagnostika uchun.
  static SessionEndNotice? get pending => _pending;

  /// Xabarni ko'taradi. [draftLost] — ekranda SAQLANMAGAN qo'l kiritmasi
  /// bormi; faqat shunda yo'qotish haqida aytiladi (soxta ogohlantirish yo'q).
  static void raise(SessionEndReason reason, {required bool draftLost}) {
    if (reason == SessionEndReason.loggedOut) return;
    _pending = SessionEndNotice(reason, draftLost);
  }

  /// Xabarni oladi va o'chiradi.
  static SessionEndNotice? consume() {
    final n = _pending;
    _pending = null;
    return n;
  }

  /// Xabar MATNINI oladi va o'chiradi, yoki `null` — kutayotgan xabar yo'q.
  /// Login ekrani shu metodni `initState` da chaqiradi.
  static String? consumeText() {
    final n = consume();
    return n == null ? null : text(n);
  }

  /// Foydalanuvchiga ko'rsatiladigan matn.
  ///
  /// ⚠️  `saqlanmagan` so'zi ATAYLAB kichik harf bilan gap o'rtasida:
  ///     yo'qotish haqidagi qism matnning ajralmas bo'lagi va tarjimada ham
  ///     shunday qoladi.
  static String text(SessionEndNotice n) {
    final base = switch (n.reason) {
      SessionEndReason.expired => tr('Sessiya muddati tugadi'),
      SessionEndReason.serverChanged => tr('Server manzili o‘zgardi, sessiya tugadi'),
      SessionEndReason.loggedOut => tr('Sessiya tugadi'),
    };
    return n.draftLost
        ? '$base — ${tr('saqlanmagan ma‘lumot yo‘qoldi, qayta kiring')}'
        : '$base — ${tr('qayta kiring')}';
  }

  @visibleForTesting
  static void debugClear() => _pending = null;
}

/// Sessiya tugashi haqidagi bir martalik xabarning mazmuni.
class SessionEndNotice {
  const SessionEndNotice(this.reason, this.draftLost);
  final SessionEndReason reason;
  final bool draftLost;
}
