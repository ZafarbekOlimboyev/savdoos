import 'package:flutter/material.dart';
import 'api.dart';
import 'l10n.dart';
import 'theme.dart';
import 'screens/login_screen.dart';
import 'screens/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  await L.load();
  runApp(const SavdoApp());
}

class SavdoApp extends StatelessWidget {
  const SavdoApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Til almashganda butun daraxt qayta quriladi (L.version o'zgaradi).
    return ValueListenableBuilder<int>(
      valueListenable: L.version,
      builder: (context, _, __) => MaterialApp(
        title: 'SavdoOS',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: Api.loggedIn ? const Shell() : const LoginScreen(),
      ),
    );
  }
}
