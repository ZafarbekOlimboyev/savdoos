import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'shell.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  String _pin = '';
  bool _busy = false;
  String? _err;

  Future<void> _submit() async {
    if (_pin.length < 4 || _busy) return;
    setState(() { _busy = true; _err = null; });
    try {
      await Api.login(_pin);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Shell()));
    } catch (e) {
      setState(() { _err = 'PIN noto‘g‘ri yoki server bilan aloqa yo‘q'; _pin = ''; });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _tap(String d) {
    if (_pin.length >= 6) return;
    setState(() { _pin += d; _err = null; });
    if (_pin.length == 4) _submit();
  }

  void _back() => setState(() { if (_pin.isNotEmpty) _pin = _pin.substring(0, _pin.length - 1); });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 60, height: 60,
                decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(16)),
                child: const Icon(Icons.storefront, color: Colors.white, size: 30),
              ),
              const SizedBox(height: 18),
              const Text('SavdoOS', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              const Text('PIN-kodni kiriting', style: TextStyle(color: AppColors.muted)),
              const SizedBox(height: 28),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(4, (i) {
                  final on = i < _pin.length;
                  return Container(
                    margin: const EdgeInsets.symmetric(horizontal: 8),
                    width: 16, height: 16,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: on ? AppColors.accent : AppColors.borderInput,
                    ),
                  );
                }),
              ),
              const SizedBox(height: 14),
              SizedBox(height: 20, child: _busy
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(_err ?? '', style: const TextStyle(color: AppColors.danger, fontSize: 12.5))),
              const SizedBox(height: 14),
              _Pad(onTap: _tap, onBack: _back),
              const SizedBox(height: 12),
              const Text('Demo: Administrator — 1234 · Kassir — 1111',
                  style: TextStyle(color: AppColors.faint, fontSize: 11.5)),
            ],
          ),
        ),
      ),
    );
  }
}

class _Pad extends StatelessWidget {
  final void Function(String) onTap;
  final VoidCallback onBack;
  const _Pad({required this.onTap, required this.onBack});

  @override
  Widget build(BuildContext context) {
    final keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'back'];
    return GridView.count(
      shrinkWrap: true,
      crossAxisCount: 3,
      mainAxisSpacing: 12,
      crossAxisSpacing: 12,
      childAspectRatio: 1.5,
      physics: const NeverScrollableScrollPhysics(),
      children: keys.map((k) {
        if (k.isEmpty) return const SizedBox();
        final isBack = k == 'back';
        return Material(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(14),
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => isBack ? onBack() : onTap(k),
            child: Center(
              child: isBack
                  ? const Icon(Icons.backspace_outlined, color: AppColors.text3)
                  : Text(k, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600)),
            ),
          ),
        );
      }).toList(),
    );
  }
}
