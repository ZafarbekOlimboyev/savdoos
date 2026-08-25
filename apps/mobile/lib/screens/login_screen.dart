import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'shell.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
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
    if (phone.isEmpty || pass.isEmpty || _busy) return;
    setState(() { _busy = true; _err = null; });
    try {
      await Api.login(phone, pass);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Shell()));
    } catch (e) {
      setState(() => _err = tr('Telefon yoki parol noto‘g‘ri'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  InputDecoration _dec(String label, {Widget? suffix}) => InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: AppColors.muted, fontSize: 14),
        suffixIcon: suffix,
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 64, height: 64,
                  decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(18)),
                  child: const Icon(Icons.storefront, color: Colors.white, size: 32),
                ),
                const SizedBox(height: 18),
                const Text('SavdoOS', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                const SizedBox(height: 4),
                Text(tr('Hisobingizga kiring'), style: TextStyle(color: AppColors.muted)),
                const SizedBox(height: 28),
                TextField(
                  controller: _phone,
                  keyboardType: TextInputType.phone,
                  autocorrect: false,
                  textInputAction: TextInputAction.next,
                  decoration: _dec(tr('Telefon')),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _password,
                  obscureText: _obscure,
                  onSubmitted: (_) => _submit(),
                  decoration: _dec(tr('Parol'), suffix: IconButton(
                    icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility, color: AppColors.muted, size: 20),
                    onPressed: () => setState(() => _obscure = !_obscure),
                  )),
                ),
                SizedBox(
                  height: 24,
                  child: _err == null ? null : Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(_err!, style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
                  ),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : Text(tr('Kirish')),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
