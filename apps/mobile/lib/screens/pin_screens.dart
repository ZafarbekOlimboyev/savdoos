import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../theme.dart';
import 'login_screen.dart';
import 'shell.dart';

// ─────────── Umumiy: PIN nuqtalari + raqamli klaviatura ───────────
class _PinBody extends StatelessWidget {
  final String title, subtitle;
  final int entered;
  final String? error;
  final void Function(int) onDigit;
  final VoidCallback onBackspace;
  final Widget? footer;
  const _PinBody({
    required this.title,
    required this.subtitle,
    required this.entered,
    required this.error,
    required this.onDigit,
    required this.onBackspace,
    this.footer,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 30),
          child: Column(children: [
            const Spacer(flex: 2),
            Container(
              width: 58, height: 58,
              decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(16)),
              child: const Icon(Icons.lock_rounded, color: Colors.white, size: 28),
            ),
            const SizedBox(height: 18),
            Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800), textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(subtitle, style: TextStyle(color: AppColors.muted, fontSize: 13.5), textAlign: TextAlign.center),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(4, (i) {
                final filled = i < entered;
                return AnimatedContainer(
                  duration: const Duration(milliseconds: 120),
                  margin: const EdgeInsets.symmetric(horizontal: 9),
                  width: 15, height: 15,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: filled ? AppColors.accentStrong : Colors.transparent,
                    border: Border.all(
                      color: error != null ? AppColors.danger : (filled ? AppColors.accentStrong : AppColors.border),
                      width: 2,
                    ),
                  ),
                );
              }),
            ),
            SizedBox(
              height: 22,
              child: error == null ? null : Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(error!, style: const TextStyle(color: AppColors.danger, fontSize: 13, fontWeight: FontWeight.w600)),
              ),
            ),
            const Spacer(flex: 1),
            _Keypad(onDigit: onDigit, onBackspace: onBackspace),
            SizedBox(height: 60, child: Center(child: footer ?? const SizedBox.shrink())),
            const Spacer(flex: 1),
          ]),
        ),
      ),
    );
  }
}

class _Keypad extends StatelessWidget {
  final void Function(int) onDigit;
  final VoidCallback onBackspace;
  const _Keypad({required this.onDigit, required this.onBackspace});

  Widget _key(String label, {VoidCallback? onTap, Widget? child}) {
    final empty = label.isEmpty && child == null;
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.all(7),
        child: AspectRatio(
          aspectRatio: 1.7,
          child: Material(
            color: empty ? Colors.transparent : AppColors.card,
            borderRadius: BorderRadius.circular(16),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: onTap,
              child: Center(child: child ?? Text(label, style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w700))),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Row(children: [for (final n in [1, 2, 3]) _key('$n', onTap: () => onDigit(n))]),
      Row(children: [for (final n in [4, 5, 6]) _key('$n', onTap: () => onDigit(n))]),
      Row(children: [for (final n in [7, 8, 9]) _key('$n', onTap: () => onDigit(n))]),
      Row(children: [
        _key(''),
        _key('0', onTap: () => onDigit(0)),
        _key('', onTap: onBackspace, child: Icon(Icons.backspace_outlined, size: 22, color: AppColors.text2)),
      ]),
    ]);
  }
}

// ─────────── PIN o'rnatish (login'dan keyin yoki sozlamalardan) ───────────
class PinSetupScreen extends StatefulWidget {
  final VoidCallback onDone;
  const PinSetupScreen({super.key, required this.onDone});
  @override
  State<PinSetupScreen> createState() => _PinSetupScreenState();
}

class _PinSetupScreenState extends State<PinSetupScreen> {
  String _first = '';
  String _entered = '';
  bool _confirming = false;
  String? _error;
  bool _busy = false;

  void _digit(int n) {
    if (_busy || _entered.length >= 4) return;
    setState(() {
      _error = null;
      _entered += '$n';
    });
    if (_entered.length == 4) _next();
  }

  void _back() {
    if (_entered.isEmpty) return;
    setState(() => _entered = _entered.substring(0, _entered.length - 1));
  }

  Future<void> _next() async {
    if (!_confirming) {
      setState(() {
        _first = _entered;
        _entered = '';
        _confirming = true;
      });
      return;
    }
    if (_entered != _first) {
      HapticFeedback.heavyImpact();
      setState(() {
        _error = tr('PIN kodlar mos kelmadi');
        _entered = '';
        _first = '';
        _confirming = false;
      });
      return;
    }
    setState(() => _busy = true);
    await Lock.setPin(_first);
    // Biometrik mavjud bo'lsa — taklif qilamiz. DIQQAT: dialog/biometrik qatlamда xatolik
    // (masalan qurilma biometrikasi nosoz) bo'lса ham setup TUGASHi shart — aks holda ekran
    // qotib qolardi. Shuning uchun try/catch ичida, onDone() esa har doim chaqiriladi.
    try {
      if (await Lock.biometricAvailable() && mounted) {
        final on = await showDialog<bool>(
          context: context,
          builder: (_) => AlertDialog(
            backgroundColor: AppColors.card,
            title: Text(tr('Biometrik kirish')),
            content: Text(tr('Barmoq izi yoki Face ID bilan ham kirishni yoqasizmi?'), style: TextStyle(color: AppColors.text3)),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Keyinroq'))),
              ElevatedButton(onPressed: () => Navigator.pop(context, true), child: Text(tr('Yoqish'))),
            ],
          ),
        );
        if (on == true) await Lock.setBiometric(true);
      }
    } catch (_) {/* biometrik taklifда xatolik — e'tiborsiz, setup davom etadi */}
    if (mounted) widget.onDone();
  }

  @override
  Widget build(BuildContext context) {
    return _PinBody(
      title: _confirming ? tr('PIN kodni tasdiqlang') : tr('PIN kod o‘rnating'),
      subtitle: _confirming ? tr('Xuddi shu 4 raqamni qayta kiriting') : tr('Ilovani ochish uchun 4 xonali kod'),
      entered: _entered.length,
      error: _error,
      onDigit: _digit,
      onBackspace: _back,
    );
  }
}

// ─────────── Qulf ekrani (ilova ochilganda) ───────────
class LockScreen extends StatefulWidget {
  const LockScreen({super.key});
  @override
  State<LockScreen> createState() => _LockScreenState();
}

class _LockScreenState extends State<LockScreen> {
  String _entered = '';
  String? _error;
  bool _bioAvail = false;
  int _locked = 0;        // qulf tugashiga qolgan soniya (0 = ochiq)
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _locked = Lock.lockRemaining();
    if (_locked > 0) _startCountdown();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      _bioAvail = await Lock.biometricAvailable();
      if (mounted) setState(() {});
      if (_locked == 0 && Lock.biometricOn && _bioAvail) _tryBiometric();
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  void _startCountdown() {
    _tick?.cancel();
    _tick = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      final r = Lock.lockRemaining();
      setState(() => _locked = r);
      if (r == 0) t.cancel();
    });
  }

  void _unlock() {
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Shell()));
  }

  Future<void> _tryBiometric() async {
    if (_locked > 0) return;
    final ok = await Lock.authenticate(tr('Ilovani ochish uchun tasdiqlang'));
    if (ok && mounted) {
      await Lock.registerSuccess();
      _unlock();
    }
  }

  void _digit(int n) {
    if (_locked > 0 || _entered.length >= 4) return;
    setState(() {
      _error = null;
      _entered += '$n';
    });
    if (_entered.length == 4) _check();
  }

  Future<void> _check() async {
    if (Lock.verify(_entered)) {
      await Lock.registerSuccess();
      if (mounted) _unlock();
      return;
    }
    HapticFeedback.heavyImpact();
    final wipe = await Lock.registerFail();
    if (wipe) {
      await _logout();  // juda ko'p urinish — sessiya tozalanadi, parol bilan qayta kirish
      return;
    }
    if (!mounted) return;
    final rem = Lock.lockRemaining();
    setState(() {
      _entered = '';
      _locked = rem;
      _error = rem > 0 ? null : tr('PIN kod noto‘g‘ri');
    });
    if (rem > 0) _startCountdown();
  }

  void _back() {
    if (_locked > 0 || _entered.isEmpty) return;
    setState(() => _entered = _entered.substring(0, _entered.length - 1));
  }

  Future<void> _logout() async {
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  String _fmt(int s) {
    if (s >= 60) return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
    return '${s}s';
  }

  @override
  Widget build(BuildContext context) {
    final name = (Api.employee?['name'] ?? Api.employee?['full_name'] ?? '').toString();
    final subtitle = _locked > 0
        ? tr('Ko‘p urinish — {t} kuting').replaceFirst('{t}', _fmt(_locked))
        : (name.isEmpty ? tr('PIN kodni kiriting') : name);
    return PopScope(
      canPop: false,
      child: _PinBody(
        title: tr('Xush kelibsiz'),
        subtitle: subtitle,
        entered: _entered.length,
        error: _error,
        onDigit: _digit,
        onBackspace: _back,
        footer: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_locked == 0 && Lock.biometricOn && _bioAvail)
              TextButton.icon(
                onPressed: _tryBiometric,
                icon: const Icon(Icons.fingerprint, size: 22),
                label: Text(tr('Biometrik')),
              ),
            TextButton(
              onPressed: _logout,
              child: Text(tr('Chiqish'), style: TextStyle(color: AppColors.muted)),
            ),
          ],
        ),
      ),
    );
  }
}
