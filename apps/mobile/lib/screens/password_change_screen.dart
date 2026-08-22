import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../theme.dart';

class PasswordChangeScreen extends StatefulWidget {
  const PasswordChangeScreen({super.key});
  @override
  State<PasswordChangeScreen> createState() => _PasswordChangeScreenState();
}

class _PasswordChangeScreenState extends State<PasswordChangeScreen> {
  final _old = TextEditingController();
  final _new = TextEditingController();
  final _new2 = TextEditingController();
  bool _busy = false;
  String? _err;

  @override
  void dispose() {
    _old.dispose();
    _new.dispose();
    _new2.dispose();
    super.dispose();
  }

  bool get _match => _new.text.isNotEmpty && _new.text == _new2.text;

  Future<void> _save() async {
    if (_new.text.length < 6) return setState(() => _err = tr('Yangi parol kamida 6 belgi'));
    if (!_match) return setState(() => _err = tr('Parollar mos emas'));
    setState(() { _busy = true; _err = null; });
    try {
      await Api.changePassword(_old.text.isEmpty ? null : _old.text, _new.text);
      if (!mounted) return;
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Parol o‘zgartirildi ✓'))));
    } catch (e) {
      setState(() { _busy = false; _err = e.toString(); });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Parol o‘zgartirish'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _field(tr('Joriy parol'), _old),
          const SizedBox(height: 16),
          _field(tr('Yangi parol'), _new),
          const SizedBox(height: 16),
          _field(tr('Yangi parol (takror)'), _new2),
          if (_new2.text.isNotEmpty) ...[
            const SizedBox(height: 10),
            Row(children: [
              Icon(_match ? Icons.check_circle : Icons.cancel, size: 15, color: _match ? AppColors.ok : AppColors.danger),
              const SizedBox(width: 6),
              Text(_match ? tr('Parollar mos keladi') : tr('Parollar mos emas'), style: TextStyle(fontSize: 12, color: _match ? AppColors.ok : AppColors.danger)),
            ]),
          ],
          if (_err != null) ...[
            const SizedBox(height: 12),
            Text(_err!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
          ],
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: AppColors.ok),
              onPressed: _busy ? null : _save,
              icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.check, size: 20),
              label: Text(tr('Saqlash')),
            ),
          ),
        ],
      ),
    );
  }

  Widget _field(String label, TextEditingController c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        TextField(controller: c, obscureText: true, onChanged: (_) => setState(() {})),
      ]);
}
