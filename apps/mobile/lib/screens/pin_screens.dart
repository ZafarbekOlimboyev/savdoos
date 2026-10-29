import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../draft_vault.dart';
import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../secure_screen.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'app_lock.dart';
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
        // ⚠️  SCROLL SHART. Ilgari bu `Spacer` li `Column` edi va u:
        //       * LANDSCAPE da 352-456 px toshardi (`Info.plist` landscape'ga
        //         ruxsat beradi va Dart'da orientatsiya qulfi yo'q) — 667x375
        //         da faqat 1-6 tugmalar ko'rinardi, "0", backspace va
        //         "Chiqish" EKRANDAN TASHQARIDA qolardi;
        //       * katta tizim yozuvida portretda ham toshardi (320x568 da
        //         1.45x dan, 375x667 da 1.75x dan boshlab).
        //     Ya'ni PIN'ida "0" bo'lgan operator ilovani UMUMAN ocha olmasdi.
        //     `SliverFillRemaining(hasScrollBody: false)` joy bo'lsa markazda
        //     ushlab turadi, joy yetmasa scroll ochadi.
        child: CustomScrollView(
          slivers: [
            SliverFillRemaining(
              hasScrollBody: false,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 12),
                child: Column(children: [
                  const Spacer(flex: 2),
                  Container(
                    width: 58,
                    height: 58,
                    decoration:
                        BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(16)),
                    child: const Icon(Icons.lock_rounded, color: Colors.white, size: 28),
                  ),
                  const SizedBox(height: 18),
                  Text(title,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                      textAlign: TextAlign.center),
                  const SizedBox(height: 6),
                  Text(subtitle,
                      style: TextStyle(color: AppColors.muted, fontSize: 13.5), textAlign: TextAlign.center),
                  const SizedBox(height: 24),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: List.generate(4, (i) {
                      final filled = i < entered;
                      return AnimatedContainer(
                        duration: const Duration(milliseconds: 120),
                        margin: const EdgeInsets.symmetric(horizontal: 9),
                        width: 15,
                        height: 15,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: filled ? AppColors.accentStrong : Colors.transparent,
                          border: Border.all(
                            color: error != null
                                ? AppColors.danger
                                : (filled ? AppColors.accentStrong : AppColors.border),
                            width: 2,
                          ),
                        ),
                      );
                    }),
                  ),
                  SizedBox(
                    height: 22,
                    child: error == null
                        ? null
                        : Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(error!,
                                style: const TextStyle(
                                    color: AppColors.danger, fontSize: 13, fontWeight: FontWeight.w600)),
                          ),
                  ),
                  const Spacer(flex: 1),
                  const SizedBox(height: 12),
                  _Keypad(onDigit: onDigit, onBackspace: onBackspace),
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Center(child: footer ?? const SizedBox.shrink()),
                  ),
                  const Spacer(flex: 1),
                ]),
              ),
            ),
          ],
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
              child: Center(
                  child: child ??
                      Text(label, style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w700))),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Row(children: [
        for (final n in [1, 2, 3]) _key('$n', onTap: () => onDigit(n))
      ]),
      Row(children: [
        for (final n in [4, 5, 6]) _key('$n', onTap: () => onDigit(n))
      ]),
      Row(children: [
        for (final n in [7, 8, 9]) _key('$n', onTap: () => onDigit(n))
      ]),
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

class _PinSetupScreenState extends State<PinSetupScreen> with SecureScreenMixin<PinSetupScreen> {
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
    try {
      await Lock.setPin(_first);
    } catch (_) {
      //  ⚠️  PIN O'RNATILMADI (qisman yozuv `Lock.setPin` da ortga qaytarildi).
      //      Ilgari bu yerda xato tutilmagani uchun ekran `_busy` holatida
      //      QOTIB qolardi; foydalanuvchi ilovani majburan yopib, PIN'siz
      //      ochilgan ilovaga qaytardi. Endi xato aytiladi va qayta urinish
      //      mumkin — `onDone()` esa CHAQIRILMAYDI (qulf yo'q).
      if (!mounted) return;
      setState(() {
        _busy = false;
        _entered = '';
        _first = '';
        _confirming = false;
        _error = tr('PIN saqlanmadi — qaytadan urinib ko‘ring');
      });
      return;
    }
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
            content: Text(tr('Barmoq izi yoki Face ID bilan ham kirishni yoqasizmi?'),
                style: TextStyle(color: AppColors.text3)),
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
      subtitle:
          _confirming ? tr('Xuddi shu 4 raqamni qayta kiriting') : tr('Ilovani ochish uchun 4 xonali kod'),
      entered: _entered.length,
      error: _error,
      onDigit: _digit,
      onBackspace: _back,
    );
  }
}

// ─────────── Qulf ekrani (ilova ochilganda) ───────────
class LockScreen extends StatefulWidget {
  /// [onUnlocked] berilsa (ilova fondan qaytganda qayta qulflash) — ochilganda shu
  /// chaqiriladi (odatda `pop`: foydalanuvchi qayerda qolgan bo'lsa, o'sha ekranga
  /// qaytadi). Berilmasa (sovuq ishga tushish) — qobiq (Shell) ochiladi.
  final VoidCallback? onUnlocked;
  const LockScreen({super.key, this.onUnlocked});
  @override
  State<LockScreen> createState() => _LockScreenState();
}

class _LockScreenState extends State<LockScreen> with SecureScreenMixin<LockScreen> {
  String _entered = '';
  String? _error;
  bool _bioAvail = false;
  int _locked = 0; // qulf tugashiga qolgan soniya (0 = ochiq)
  bool _wiping = false; // juda ko'p urinish: sessiya tozalanmoqda
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
    final done = widget.onUnlocked;
    if (done != null) {
      done();
      return;
    }
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
    if (_wiping || _locked > 0 || _entered.length >= 4) return;
    setState(() {
      _error = null;
      _entered += '$n';
    });
    if (_entered.length == 4) _check();
  }

  Future<void> _check() async {
    if (_wiping) return;
    if (Lock.verify(_entered)) {
      await Lock.registerSuccess();
      if (mounted) _unlock();
      return;
    }
    HapticFeedback.heavyImpact();
    final wipe = await Lock.registerFail();
    if (wipe) {
      // ⚠️  Klaviatura DARHOL o'chiriladi. `_logout()` serverga murojaat qiladi
      //     (5 soniyagacha kutadi) va ilgari AYNAN o'sha oynada yana PIN
      //     kiritish mumkin edi — ya'ni 12 urinish chegarasidan oshib ketardi.
      if (mounted) setState(() => _wiping = true);
      //  ⚠️  `userChose: false` — bu MAJBURIY tozalash. Foydalanuvchi ishdan
      //      voz kechishni TANLAMAGAN, u shunchaki PIN'ni chalkashtirgan;
      //      qoralamani (va u bilan birga yagona `client_uuid` ni) o'chirish
      //      operatorni ayni amalni ikkinchi marta yozishga yo'llardi.
      await _logout(userChose: false);
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

  /// Confirms the explicit sign-out before discarding anything.
  ///
  /// ⚠️  WHY A CONFIRMATION (R6.8 P1). This was the only sign-out in the app
  ///     without one (`settings_screen` and `lock_recovery_screen` both
  ///     confirm), and it is also the only remaining path that still throws
  ///     unsaved work away — one stray tap on a locked screen destroyed it.
  Future<void> _confirmLogout() async {
    if (_wiping) return;
    final ok = await confirmDestructive(
      context,
      title: tr('Chiqish'),
      message: tr('Hisobdan chiqmoqchimisiz?'),
      details: [
        tr('Ilova qulfi (PIN) ham o‘chiriladi — keyingi kirishda yangidan o‘rnatiladi.'),
        if (DraftVault.isNotEmpty) tr('Saqlanmagan kiritmalar ham o‘chiriladi.'),
      ],
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Bekor'),
    );
    if (!ok) return;
    await _logout(userChose: true);
  }

  void _back() {
    if (_wiping || _locked > 0 || _entered.isEmpty) return;
    setState(() => _entered = _entered.substring(0, _entered.length - 1));
  }

  /// Signs out of the lock screen.
  ///
  /// [userChose] separates the two flows that reach this one function:
  ///
  /// * `true`  — the operator tapped «Chiqish». Abandoning the work is the
  ///             point, so the drafts go.
  /// * `false` — twelve wrong PINs forced the wipe ([Lock] `_wipeAt`). The
  ///             operator did NOT choose this, so the drafts are KEPT.
  ///
  /// ⚠️  WHY KEEPING IS SAFE (R6.8 P1). [DraftVault] is RAM-only and
  ///     [DraftVault.claim] demands FULL equality of the server-attested scope
  ///     `server|company|employee|branch`, which only a successful password
  ///     login can reproduce — so a different employee, company or server can
  ///     never see the draft, and a foreign touch destroys it. A real 401
  ///     already leaves drafts in RAM (`api.dart` has no `evictAll`), so this
  ///     opens NO new surface; it only stops the forced path from being
  ///     stricter than an expired session.
  ///
  /// ⚠️  FAIL-CLOSED IS UNTOUCHED. The PIN, the biometric flag, the token and
  ///     the failure counter are all still cleared by `Lock.clear()` /
  ///     `Api.logout()`; the escalating lockout and the wipe itself are
  ///     unchanged. Nothing about the lock is keyed on [DraftVault].
  Future<void> _logout({required bool userChose}) async {
    await Api.logout();
    await Lock.clear();
    if (userChose) {
      // ⚠️  ANIQ CHIQISH qoralamani ATAYLAB tashlab ketadi: keyingi xodim
      //     oldingisining kiritmasini ko'rmasligi kerak. (`DraftVault.claim`
      //     doirani ham tekshiradi — bu ikkinchi qatlam.)
      DraftVault.evictAll();
    }
    // ⚠️  `mounted` TEKSHIRILMAYDI. `Lock.clear()` qulf qatlamini yopadi va
    //     Keychain o'chirishlarini kutadi — o'sha oraliqda bu `State` unmount
    //     bo'ladi. `if (!mounted) return` qo'ysak, chiqish login ekraniga
    //     YETIB BORMASDI. `leaveToLogin` ildiz navigatorini kalit orqali
    //     topadi, ya'ni widget holatiga bog'liq emas.
    leaveToLogin(mounted ? context : null);
  }

  String _fmt(int s) {
    if (s >= 60) return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
    return '${s}s';
  }

  @override
  Widget build(BuildContext context) {
    final ctxName = Session.instance.context?.fullName ?? '';
    final name =
        ctxName.isNotEmpty ? ctxName : (Api.employee?['name'] ?? Api.employee?['full_name'] ?? '').toString();
    final subtitle = _locked > 0
        ? trArgs('Ko‘p urinish — {t} kuting', {'t': _fmt(_locked)})
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
              key: const Key('lock-logout'),
              onPressed: _confirmLogout,
              child: Text(tr('Chiqish'), style: TextStyle(color: AppColors.muted)),
            ),
          ],
        ),
      ),
    );
  }
}
