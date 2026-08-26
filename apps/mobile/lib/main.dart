import 'package:flutter/material.dart';
import 'api.dart';
import 'l10n.dart';
import 'lock.dart';
import 'theme.dart';
import 'screens/login_screen.dart';
import 'screens/pin_screens.dart';
import 'screens/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
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
