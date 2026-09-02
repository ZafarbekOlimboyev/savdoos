import 'package:flutter/material.dart';
import 'api.dart';
import 'l10n.dart';
import 'lock.dart';
import 'theme.dart';
import 'screens/login_screen.dart';
import 'screens/pin_screens.dart';
import 'screens/shell.dart';

final GlobalKey<NavigatorState> rootNavKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  // Sessiya bekor bo'lsa (401: parol tiklandi / boshqa qurilmada chiqish / muddat tugadi) —
  // ilova o'lik tokenda "osilib" qolmasin: login ekraniga qaytaramiz.
  Api.onSessionExpired = () {
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
