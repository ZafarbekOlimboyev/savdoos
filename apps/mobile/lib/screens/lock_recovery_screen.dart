import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../secure_screen.dart';
import '../theme.dart';
import 'login_screen.dart';
import 'pin_screens.dart';
import 'shell.dart';

/// Kirgan foydalanuvchiga ko'rsatiladigan BIRINCHI ekran — qulf darvozasi.
///
/// ⚠️  Qaror [Lock.shouldLock] ga tayanib bo'lmaydi: PIN xeshini o'qib
///     bo'lmaganda (`unavailable`) yoki juftlik buzilganda (`corrupt`)
///     tekshiriladigan xesh yo'q, shu bois `shouldLock` yolg'on qaytadi va
///     ilgari shu yolg'on «qulf shart emas» deb o'qilib, savdo/kassa/qarz
///     ma'lumotlari PIN SO'RALMASDAN ochilardi. Endi holat noma'lum bo'lsa
///     qobiq o'rniga [LockRecoveryScreen] chiqadi.
Widget lockGateHome() {
  if (!Lock.statusKnown) return const LockRecoveryScreen();
  return Lock.shouldLock ? const LockScreen() : const Shell();
}

/// Qulf holatini tasdiqlab bo'lmaganda chiqadigan ekran: himoyalangan qobiq
/// YOPIQ qoladi, foydalanuvchiga esa ikki xavfsiz yo'l beriladi — xotirani
/// qayta o'qish yoki parol bilan qaytadan kirish.
///
/// Bu ekran HECH NARSANI o'chirmaydi: o'tkinchi xotira xatosi sababli PIN yoki
/// tokenni avtomatik tozalash foydalanuvchini sababsiz chiqarib yuborardi.
/// Tozalash faqat foydalanuvchi «Parol bilan kirish» ni bosganda bo'ladi.
class LockRecoveryScreen extends StatefulWidget {
  /// [onResolved] berilsa (ilova fondan qaytganda qobiq ustiga qo'yilgan) —
  /// holat aniqlanib qulf shart emas bo'lsa shu chaqiriladi (odatda `pop`).
  /// Berilmasa (sovuq ishga tushish) — qobiq o'zi ochiladi.
  final VoidCallback? onResolved;
  const LockRecoveryScreen({super.key, this.onResolved});

  @override
  State<LockRecoveryScreen> createState() => _LockRecoveryScreenState();
}

class _LockRecoveryScreenState extends State<LockRecoveryScreen>
    with SecureScreenMixin<LockRecoveryScreen> {
  bool _busy = false;
  String? _error;

  Future<void> _retry() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    await Lock.load();
    if (!mounted) return;
    if (!Lock.statusKnown) {
      setState(() {
        _busy = false;
        _error = tr('Qulf holati hali tasdiqlanmadi');
      });
      return;
    }
    // Holat aniqlandi. PIN bor bo'lsa — `build` qulf ekranini qaytaradi;
    // shart bo'lmasa — qobiqqa o'tamiz.
    if (Lock.shouldLock) {
      setState(() => _busy = false);
      return;
    }
    _resolve();
  }

  void _resolve() {
    final done = widget.onResolved;
    if (done != null) {
      done();
      return;
    }
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const Shell()));
  }

  Future<void> _reauth() async {
    if (_busy) return;
    setState(() => _busy = true);
    // `Api.logout()` serverni ham xabardor qiladi, lekin oflayn bo'lsa lokal
    // chiqishga o'tadi — ya'ni internet yo'qligi bu yo'lni to'smaydi.
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true)
        .pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  @override
  Widget build(BuildContext context) {
    // Qayta o'qish holatni aniqlagan va PIN bor bo'lsa — darhol qulf ekrani.
    // Navigatsiya zanjiri o'rniga shu yerda almashtirish: oraliq kadrda qobiq
    // ko'rinib ketishi mumkin emas.
    if (Lock.statusKnown && Lock.shouldLock) {
      return LockScreen(onUnlocked: widget.onResolved);
    }
    return PopScope(
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 30),
            child: Column(children: [
              const Spacer(flex: 2),
              Container(
                width: 58,
                height: 58,
                decoration: BoxDecoration(
                  color: AppColors.warnSoft,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AppColors.warnBorder),
                ),
                child: const Icon(Icons.lock_person_outlined, color: AppColors.warn, size: 28),
              ),
              const SizedBox(height: 18),
              Text(
                tr('Qulf tasdiqlanmadi'),
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                tr('Qurilmaning xavfsiz xotirasi javob bermadi, shuning uchun PIN holatini tasdiqlab bo‘lmadi. Ma’lumotlaringiz yopiq qoldi.'),
                style: TextStyle(color: AppColors.text3, fontSize: 13.5, height: 1.45),
                textAlign: TextAlign.center,
              ),
              SizedBox(
                height: 30,
                child: _error == null
                    ? null
                    : Padding(
                        padding: const EdgeInsets.only(top: 10),
                        child: Text(
                          _error!,
                          style: const TextStyle(
                              color: AppColors.danger, fontSize: 13, fontWeight: FontWeight.w600),
                          textAlign: TextAlign.center,
                        ),
                      ),
              ),
              const Spacer(flex: 1),
              SizedBox(
                width: double.infinity,
                height: 52,
                child: ElevatedButton(
                  onPressed: _busy ? null : _retry,
                  child: Text(_busy ? tr('Tekshirilmoqda…') : tr('Qayta urinish')),
                ),
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                height: 52,
                child: TextButton(
                  onPressed: _busy ? null : _reauth,
                  child: Text(tr('Parol bilan kirish')),
                ),
              ),
              const Spacer(flex: 1),
            ]),
          ),
        ),
      ),
    );
  }
}
