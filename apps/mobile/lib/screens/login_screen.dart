import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../theme.dart';
import 'pin_screens.dart';
import 'shell.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController(text: '+996 '); // ilk login — kod avto turadi
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _err;

  @override
  void dispose() {
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final phone = _phone.text.trim();
    final pass = _password.text;
    if (phone.isEmpty || phone == '+996' || pass.isEmpty || _busy) return;
    setState(() { _busy = true; _err = null; });
    try {
      await Api.login(phone, pass);
      if (!mounted) return;
      // Bir marta login qilgach — 4 xonali PIN o'rnatiladi; keyingi ochishlarда PIN/biometrik.
      if (!Lock.hasPin) {
        // MUHIM: onDone ichida LOGIN context emas, PinSetup route'ining O'Z contextи (ctx)
        // ishlatiladi — pushReplacement Login State'ini dispose qiladi, uning contextи
        // bilan Navigator chaqirish "defunct" xatosi berib, ekran qotib qolardi.
        Navigator.of(context).pushReplacement(MaterialPageRoute(
            builder: (ctx) => PinSetupScreen(onDone: () {
                  Navigator.of(ctx).pushAndRemoveUntil(
                      MaterialPageRoute(builder: (_) => const Shell()), (r) => false);
                })));
      } else {
        Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Shell()));
      }
    } catch (e) {
      setState(() => _err = tr('Telefon yoki parol noto‘g‘ri'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  OutlineInputBorder _brd(Color c) =>
      OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c, width: 1.5));

  InputDecoration _dec(String hint, IconData icon, {Widget? suffix}) => InputDecoration(
        hintText: hint,
        hintStyle: TextStyle(color: AppColors.faint, fontSize: 15.5),
        prefixIcon: Icon(icon, size: 20, color: AppColors.muted),
        suffixIcon: suffix,
        filled: true,
        fillColor: AppColors.card,
        contentPadding: const EdgeInsets.symmetric(vertical: 17),
        border: _brd(AppColors.borderInput),
        enabledBorder: _brd(AppColors.borderInput),
        focusedBorder: _brd(AppColors.accent),
      );

  @override
  Widget build(BuildContext context) {
    final topPad = MediaQuery.of(context).padding.top;
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Column(
        children: [
          // ── HERO ──
          Container(
            width: double.infinity,
            padding: EdgeInsets.fromLTRB(28, topPad + 44, 28, 32),
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFF7060E0), Color(0xFF5A4BC4), Color(0xFF4A3EA8)],
              ),
              borderRadius: BorderRadius.only(
                  bottomLeft: Radius.circular(34), bottomRight: Radius.circular(34)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 60,
                  height: 60,
                  decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.16),
                      borderRadius: BorderRadius.circular(18)),
                  child: const Icon(Icons.storefront, color: Colors.white, size: 30),
                ),
                const SizedBox(height: 16),
                const Text('SavdoOS',
                    style: TextStyle(color: Colors.white, fontSize: 27, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
                const SizedBox(height: 5),
                Text(tr('Do‘koningiz cho‘ntagingizda'),
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.85), fontSize: 14.5)),
              ],
            ),
          ),

          // ── FORM ──
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(tr('Hisobingizga kiring'),
                      style: TextStyle(color: AppColors.text, fontSize: 18, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 18),
                  TextField(
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    autocorrect: false,
                    style: TextStyle(color: AppColors.text, fontSize: 15.5),
                    decoration: _dec(tr('Telefon'), Icons.phone_outlined),
                  ),
                  const SizedBox(height: 13),
                  TextField(
                    controller: _password,
                    obscureText: _obscure,
                    onSubmitted: (_) => _submit(),
                    style: TextStyle(color: AppColors.text, fontSize: 15.5),
                    decoration: _dec(tr('Parol'), Icons.lock_outline,
                        suffix: IconButton(
                          icon: Icon(_obscure ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                              color: AppColors.muted, size: 20),
                          onPressed: () => setState(() => _obscure = !_obscure),
                        )),
                  ),
                  SizedBox(
                    height: 24,
                    child: _err == null
                        ? null
                        : Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(_err!, style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
                          ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    height: 54,
                    child: ElevatedButton(
                      onPressed: _busy ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.accent,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                      ),
                      child: _busy
                          ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                          : Text(tr('Kirish'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
