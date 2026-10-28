import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'api.dart';
import 'l10n.dart';
import 'draft_vault.dart';
import 'lock.dart';
import 'permissions.dart';
import 'session.dart';
import 'session_notice.dart';
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
    // ⚠️  TARTIB. `Api.authEpoch` bu nuqtaga qadar ALLAQACHON oshgan
    //     (api.dart:381-396), ya'ni ochiq shakllardagi `DraftGuard`
    //     listener'lari qoralamani `DraftVault` ga topshirib bo'lgan. Shu
    //     bois `isNotEmpty` ni SHU YERDA o'qish to'g'ri natija beradi.
    //
    // ⚠️  Xabar bu yerda faqat KO'TARILADI. Uni login ekrani o'z
    //     `initState` ida ko'rsatadi: `pushAndRemoveUntil(..., (r) => false)`
    //     dan keyin login yakka route bo'lib qoladi va yo'q qilinayotgan
    //     `Scaffold` ning `ScaffoldMessenger` i xabarni ko'rsatmaydi.
    SessionNotice.raise(SessionEndReason.expired,
        draftLost: DraftVault.isNotEmpty);
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

/// Framework (Material/Cupertino) matnlari uchun til.
///
/// ⚠️  Ilova tilidan olinadi, QURILMA tilidan emas. Kirill o'zbek (`uzc`)
///     uchun Flutter'da alohida tarjima yo'q, shuning uchun u lotin `uz` ga
///     tushadi — bu eng yaqin va tushunarli variant; muqobili inglizcha
///     bo'lardi.
Locale _frameworkLocale() => switch (L.code) {
      'ru' => const Locale('ru'),
      'ky' => const Locale('ky'),
      _ => const Locale('uz'),
    };

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
        // ⚠️  Framework matnlari ILOVA tilida bo'lishi SHART. Bularsiz
        //     Material va Cupertino o'z matnlarini INGLIZCHA chiqaradi:
        //     `showDateRangePicker` («Select range», «Save»), matn tanlash
        //     menyusi («Paste», «Copy», «Select All»), `AppBar` ning
        //     «Back» e'loni va boshqalar. Build 62 AYNAN shunday aralash
        //     til holati uchun rad etilgan edi (tizim oynalari inglizcha,
        //     interfeys o'zbekcha) — bu uning ikkinchi ko'rinishi.
        //
        //     `locale` ATAYLAB ilova tilidan olinadi, qurilma tilidan emas:
        //     operator ilovada ruschani tanlasa, sana tanlagich ham ruscha
        //     bo'lishi kerak.
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [Locale('uz'), Locale('ru'), Locale('ky')],
        locale: _frameworkLocale(),
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
