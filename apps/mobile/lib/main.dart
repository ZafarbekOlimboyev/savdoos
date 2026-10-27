import 'dart:async';

import 'package:flutter/material.dart';
import 'api.dart';
import 'l10n.dart';
import 'lock.dart';
import 'permissions.dart';
import 'session.dart';
import 'theme.dart';
import 'ui/env_badge.dart';
import 'platform/scanner.dart' show scanDiagnosticsOn;
import 'screens/app_lock.dart';
import 'screens/lock_recovery_screen.dart';
import 'screens/login_screen.dart';
import 'screens/scan_diag_screen.dart';

// `rootNavKey` endi `screens/app_lock.dart` da: qulf qatlami Navigator'dan
// yuqorida turadi va unga kalit orqali murojaat qiladi, `main.dart` ga
// bog'lanish esa ekran fayllarida aylanma import yasardi.
export 'screens/app_lock.dart' show rootNavKey;

/// Diagnostika build'ida (`--dart-define=BINOS_SCAN_DIAG=1`) `?diag=scan` bilan
/// ochilsa — ilova TO'G'RIDAN-TO'G'RI skaner diagnostikasini ko'rsatadi: login,
/// qulf, sessiya va serverga murojaat YO'Q. Skaner nosozligini kamerada izlash
/// uchun boshqa hamma bo'g'in yo'ldan chiqarilishi kerak.
///
/// Production build'da `kScanDiagnostics` const `false`, ya'ni shart doim yolg'on
/// va dart2js bu shoxni butunlay olib tashlaydi — do'kon ilovasida bu yo'l YO'Q.
bool get _scanDiagRoute => scanDiagnosticsOn();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  // Sessiya bekor bo'lsa (401: parol tiklandi / boshqa qurilmada chiqish / muddat tugadi,
  // yoki server manzili almashdi) — ilova o'lik tokenda "osilib" qolmasin: login ekraniga
  // qaytaramiz. Qulf (PIN) ham tozalanadi: keyingi kirgan xodim OLDINGISINING PIN'i bilan
  // ochmasin — yangi login'dan keyin PIN qayta o'rnatiladi.
  Api.onSessionExpired = () {
    unawaited(Lock.clear());
    final nav = rootNavKey.currentState;
    if (nav != null) {
      nav.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
    }
  };
  await L.load();
  await AppTheme.load();
  await Lock.load();
  try {
    await Perm.load();
  } catch (e) {
    // Matritsa o'qilmasa ruxsatli tugmalar YASHIRIN qoladi (fail-closed) — ilova baribir ochiladi.
    debugPrint('permission matrix not loaded: $e');
  }
  // /auth/context: ishga tushganda, har login'dan keyin va ilova oldinga qaytganda.
  Session.instance.attach();
  installLockGuards(); // `runApp` dan OLDIN — qarang `screens/app_lock.dart`
  runApp(const SavdoApp());
}

class SavdoApp extends StatelessWidget {
  const SavdoApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Til yoki mavzu almashganda butun daraxt qayta quriladi.
    return AnimatedBuilder(
      animation: Listenable.merge([L.version, AppTheme.version]),
      builder: (context, _) => MaterialApp(
        navigatorKey: rootNavKey,
        title: 'BinOS',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        // The non-production marker sits at the ROOT, above every route and
        // dialog — including the login and PIN screens. Those are where a
        // pilot tester types credentials, and an upgraded phone can still
        // carry a stored server address from its previous (production)
        // install, so the screen that asks for the password must say which
        // server it is asking for. A production build is untouched
        // ([EnvBadge.wrap] returns its child).
        // ⚠️  `AppLockBarrier` ENG USTDA: u Navigator'dan yuqorida turgani
        //     uchun ostidagi hech qanday route qulfdan baland bo'la olmaydi
        //     va uni pop qila olmaydi (qarang `screens/app_lock.dart`).
        builder: (context, child) => ThemedBackground(
          child: EnvBadge.wrap(
            context,
            AppLockBarrier(child: child ?? const SizedBox.shrink()),
          ),
        ),
        // ⚠️  BUTUN qaror `lockGateHome()` da: login holati, qulf holati va
        //     tugallanmagan PIN onboarding'i bir joyda. Ilgari bu yerda
        //     `Lock.shouldLock ? LockScreen : Shell` turardi — PIN holatini
        //     o'qib bo'lmaganda u yolg'on qaytib, qobiq QULFSIZ ochilardi.
        home: _scanDiagRoute ? const ScanDiagScreen() : lockGateHome(),
      ),
    );
  }
}
