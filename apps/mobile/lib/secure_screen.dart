import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Ekran himoyasi (Android FLAG_SECURE): maxfiy ekranlarда skrinshot va so'nggi-ilovalar
/// ko'rinishini bloklaydi. Faqat login/PIN ekranlarида yoqamiz — hisobot/cheklarni
/// foydalanuvchi baribir skrinshot qilib ulasha olsin.
class SecureScreen {
  static const _ch = MethodChannel('savdoos/secure');

  static Future<void> on() async {
    if (kIsWeb) return;
    try {
      await _ch.invokeMethod('on');
    } catch (_) {/* iOS / kanal yo'q — jimgina o'tkazamiz */}
  }

  static Future<void> off() async {
    if (kIsWeb) return;
    try {
      await _ch.invokeMethod('off');
    } catch (_) {}
  }
}

/// State mixin — sahifa ochilganда FLAG_SECURE yoqadi, yopilganда o'chiradi.
/// Foydalanish: `class _XState extends State<X> with SecureScreenMixin<X> { ... }`
/// (initState/dispose'да `super`ни chaqirish shart — Flutter'да odatdagidek.)
mixin SecureScreenMixin<T extends StatefulWidget> on State<T> {
  @override
  void initState() {
    super.initState();
    SecureScreen.on();
  }

  @override
  void dispose() {
    SecureScreen.off();
    super.dispose();
  }
}
