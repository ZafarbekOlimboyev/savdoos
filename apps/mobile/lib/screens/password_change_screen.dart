import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../theme.dart';

/// Server password policy (`apps/server/app/core/password_policy.py`).
///
/// The app mirrors ONLY the limits the server states in numbers, for instant
/// feedback. The server stays the authority: common, predictable or
/// repetitive passwords are refused there, and its reason is shown translated
/// ([userMessage]) — never raw.
const int kPasswordMinLength = 12; // MIN_LEN
const int kPasswordMaxBytes = 72; // MAX_BYTES (bcrypt ignores the rest)

/// Client-side check of a new password (same order as the server); `null`
/// when the length limits are met.
String? passwordLengthProblem(String pw) {
  if (pw.isEmpty) return tr('Yangi parolni kiriting.');
  if (utf8.encode(pw).length > kPasswordMaxBytes) return tr('Parol juda uzun.');
  // Python `len()` counts code points, not UTF-16 units.
  if (pw.runes.length < kPasswordMinLength) {
    return trArgs('Parol juda qisqa — kamida {n} belgi kerak.', {'n': kPasswordMinLength});
  }
  return null;
}

/// Changes the signed-in employee's own password (`POST /auth/password`).
/// The current credential is the password, or the PIN for a PIN-only account.
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

  String? _localProblem() {
    if (_old.text.isEmpty) return tr('Joriy parol yoki PIN kodni kiriting.');
    final p = passwordLengthProblem(_new.text);
    if (p != null) return p;
    if (!_match) return tr('Parollar mos emas');
    return null;
  }

  Future<void> _save() async {
    if (_busy) return;
    final problem = _localProblem();
    if (problem != null) return setState(() => _err = problem);
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      await Api.changePassword(_old.text, _new.text);
      if (!mounted) return;
      final messenger = ScaffoldMessenger.of(context);
      Navigator.pop(context);
      messenger.showSnackBar(SnackBar(content: Text(tr('Parol o‘zgartirildi ✓'))));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _err = userMessage(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Parol o‘zgartirish'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _field(tr('Joriy parol yoki PIN'), _old, const Key('pw-old'), AutofillHints.password),
          const SizedBox(height: 16),
          _field(tr('Yangi parol'), _new, const Key('pw-new'), AutofillHints.newPassword,
              helper: trArgs('Kamida {n} belgi. Bir necha so‘zdan iborat ibora ham bo‘ladi.',
                  {'n': kPasswordMinLength})),
          const SizedBox(height: 16),
          _field(tr('Yangi parol (takror)'), _new2, const Key('pw-new2'), AutofillHints.newPassword),
          if (_new2.text.isNotEmpty) ...[
            const SizedBox(height: 10),
            Row(children: [
              Icon(_match ? Icons.check_circle : Icons.cancel, size: 15, color: _match ? AppColors.ok : AppColors.danger),
              const SizedBox(width: 6),
              Flexible(
                child: Text(_match ? tr('Parollar mos keladi') : tr('Parollar mos emas'),
                    style: TextStyle(fontSize: 12, color: _match ? AppColors.ok : AppColors.danger)),
              ),
            ]),
          ],
          if (_err != null) ...[
            const SizedBox(height: 12),
            Text(_err!, key: const Key('pw-error'), style: const TextStyle(color: AppColors.danger, fontSize: 13)),
          ],
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              key: const Key('pw-save'),
              style: ElevatedButton.styleFrom(backgroundColor: AppColors.ok, minimumSize: const Size.fromHeight(48)),
              onPressed: _busy ? null : _save,
              icon: _busy
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.check, size: 20),
              label: Text(tr('Saqlash')),
            ),
          ),
        ],
      ),
    );
  }

  Widget _field(String label, TextEditingController c, Key key, String autofill, {String? helper}) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        TextField(
          key: key,
          controller: c,
          obscureText: true,
          enableSuggestions: false,
          autocorrect: false,
          autofillHints: [autofill],
          decoration: InputDecoration(helperText: helper, helperMaxLines: 3),
          onChanged: (_) => setState(() => _err = null),
        ),
      ]);
}
