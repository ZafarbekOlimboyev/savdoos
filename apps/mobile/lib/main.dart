import 'package:flutter/material.dart';
import 'api.dart';
import 'theme.dart';
import 'screens/login_screen.dart';
import 'screens/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  runApp(const SavdoApp());
}

class SavdoApp extends StatelessWidget {
  const SavdoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SavdoOS',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: Api.loggedIn ? const Shell() : const LoginScreen(),
    );
  }
}
