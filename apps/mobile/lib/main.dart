import 'dart:async';

import 'package:flutter/material.dart';
import 'api.dart';
import 'l10n.dart';
import 'lock.dart';
import 'permissions.dart';
import 'session.dart';
import 'theme.dart';
import 'screens/login_screen.dart';
import 'screens/pin_screens.dart';
import 'screens/shell.dart';

final GlobalKey<NavigatorState> rootNavKey = GlobalKey<NavigatorState>();

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
        title: 'SavdoOS',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        builder: (context, child) => ThemedBackground(child: child ?? const SizedBox.shrink()),
        home: !Api.loggedIn
            ? const LoginScreen()
            : (Lock.shouldLock ? const LockScreen() : const Shell()),
      ),
    );
  }
}
