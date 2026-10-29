import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../secure_screen.dart';
import '../theme.dart';
import '../ui/confirm_destructive.dart';
import 'app_lock.dart';
import 'login_screen.dart';
import 'pin_screens.dart';
import 'shell.dart';

/// Ilova ochilganda ko'rsatiladigan BIRINCHI ekran — YAKUNIY qulf darvozasi.
///
/// S3 ning saboqi: qarorni bo'laklarga bo'lish nuqsonni tug'dirgan edi, shu
/// bois butun qaror SHU funksiyada turadi va `main.dart` faqat uni chaqiradi.
///
/// ⚠️  Qaror [Lock.shouldLock] ga tayanib bo'lmaydi: PIN xeshini o'qib
///     bo'lmaganda (`unavailable`) yoki juftlik buzilganda (`corrupt`)
///     tekshiriladigan xesh yo'q, shu bois `shouldLock` yolg'on qaytadi va
///     ilgari shu yolg'on «qulf shart emas» deb o'qilib, savdo/kassa/qarz
///     ma'lumotlari PIN SO'RALMASDAN ochilardi.
///
/// ⚠️  `absent` + kirgan foydalanuvchi = PIN onboarding TUGALLANMAGAN. Token
///     login'da saqlanadi, PIN esa keyin qo'yiladi; foydalanuvchi PIN ekranida
///     ilovani yopsa (yoki yozuv yiqilsa) ilgari keyingi ishga tushishda qobiq
///     butunlay qulfsiz ochilardi. Chiqish/401 esa tokenni ham tozalaydi, ya'ni
///     bu holat FAQAT tugallanmagan onboarding'dan kelib chiqadi.
Widget lockGateHome() {
  if (!Api.loggedIn) return const LoginScreen();
  if (!Lock.statusKnown) return const LockRecoveryScreen();
  if (Lock.status == LockStatus.absent) return const MandatoryPinSetupScreen();
  return Lock.shouldLock ? const LockScreen() : const Shell();
}

/// Tugallanmagan PIN onboarding'ni oxiriga yetkazadi: PIN qo'yilmaguncha qobiq
/// ochilmaydi (`PinSetupScreen` muvaffaqiyatsiz `setPin` da `onDone` ni
/// CHAQIRMAYDI, ya'ni bu ekrandan chiqishning yagona yo'li — PIN o'rnatish).
class MandatoryPinSetupScreen extends StatelessWidget {
  /// Creates the mandatory onboarding step. [onDone] berilsa (qobiq USTIDA
  /// ko'rsatilganda) PIN qo'yilgach shu chaqiriladi; berilmasa qobiq ochiladi.
  const MandatoryPinSetupScreen({super.key, this.onDone});

  /// PIN muvaffaqiyatli o'rnatilgach nima bo'lishi.
  final VoidCallback? onDone;

  @override
  Widget build(BuildContext context) => PinSetupScreen(
        onDone: onDone ??
            () => Navigator.of(context)
                .pushReplacement(MaterialPageRoute(builder: (_) => const Shell())),
      );
}

/// Qaysi amal bajarilmoqda — tugmalar yozuvi shunga qarab o'zgaradi.
enum _Busy {
  /// Hech narsa; ikkala tugma ham faol.
  none,

  /// Xavfsiz xotira qayta o'qilmoqda.
  retry,

  /// Sessiya tozalanib login ekraniga o'tilmoqda.
  reauth,
}

/// Qulf holatini tasdiqlab bo'lmaganda chiqadigan ekran: himoyalangan qobiq
/// YOPIQ qoladi, foydalanuvchiga esa ikki xavfsiz yo'l beriladi — xotirani
/// qayta o'qish yoki parol bilan qaytadan kirish.
///
/// Bu ekran HECH NARSANI o'chirmaydi: o'tkinchi xotira xatosi sababli PIN yoki
/// tokenni avtomatik tozalash foydalanuvchini sababsiz chiqarib yuborardi.
/// Tozalash faqat foydalanuvchi «Parol bilan kirish» ni bosib TASDIQLAGANDA
/// bo'ladi.
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
  _Busy _busy = _Busy.none;
  String? _error;

  bool get _idle => _busy == _Busy.none;

  Future<void> _retry() async {
    if (!_idle) return;
    setState(() {
      _busy = _Busy.retry;
      _error = null;
    });
    await Lock.load();
    if (!mounted) return;
    if (!Lock.statusKnown) {
      setState(() {
        _busy = _Busy.none;
        _error = tr('Qulf holati hali tasdiqlanmadi');
      });
      return;
    }
    // Holat aniqlandi. Qarorni O'ZIMIZ chiqarmaymiz — `build` darvozaning
    // qoidasiga mos ekranni qaytaradi (PIN bor -> qulf, PIN yo'q -> majburiy
    // onboarding). Faqat «qulf shart emas» holatida navigatsiya kerak.
    if (Lock.shouldLock || Lock.status == LockStatus.absent) {
      setState(() => _busy = _Busy.none);
      return;
    }
    _resolve();
  }

  /// Holat aniqlandi va qulf shart emas (operator «ochishda PIN so'ralsin» ni
  /// o'zi o'chirgan).
  ///
  /// ⚠️  Qaror bu yerda QAYTA chiqarilmaydi — darvozaning o'ziga murojaat
  ///     qilinadi. Ilgari to'g'ridan-to'g'ri `const Shell()` turardi va
  ///     darvozaning `absent -> MandatoryPinSetupScreen` qoidasi CHETLAB
  ///     O'TILARDI: PIN o'rnatilmagan sessiya bitta tugma bosishda qobiqni
  ///     ochardi. S3 ning saboqi aynan shu — bitta qaror, bitta joy.
  void _resolve() {
    final done = widget.onResolved;
    if (done != null) {
      done();
      return;
    }
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => lockGateHome()));
  }

  Future<void> _reauth() async {
    if (!_idle) return;
    // ⚠️  Tasdiq SO'RALADI: bu amal tokenni ham, PIN'ni ham o'chiradi va qaytish
    //     uchun parol hamda internet kerak bo'ladi. Sozlamalardagi chiqish ham
    //     ayni shu tasdiqni so'raydi (`settings_screen.dart`).
    final ok = await confirmDestructive(
      context,
      title: tr('Parol bilan kirish'),
      message: tr('Hisobdan chiqib, parol bilan qaytadan kirasizmi?'),
      details: [tr('Ilova qulfi (PIN) ham o‘chiriladi — keyingi kirishda yangidan o‘rnatiladi.')],
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Bekor'),
    );
    if (!ok || !mounted) return;
    setState(() => _busy = _Busy.reauth);
    // `Api.logout()` serverni ham xabardor qiladi, lekin oflayn bo'lsa lokal
    // chiqishga o'tadi — ya'ni internet yo'qligi bu yo'lni to'smaydi.
    await Api.logout();
    await Lock.clear();
    //  ⚠️  QORALAMA SAQLANADI — `evictAll()` ATAYLAB CHAQIRILMAYDI (R6.8 P1).
    //
    //      Foydalanuvchi bu ekranni TANLAMAGAN: u faqat xavfsiz xotira
    //      o'qilmagani yoki PIN hash/salt juftligi buzilgani uchun ko'rinadi
    //      (`Lock.statusKnown == false`), orqaga chiqish ham to'silgan. «Parol
    //      bilan kirish» — ishdan voz kechish emas, QURILMANI TUZATISH qadami,
    //      va u ilova ustida TURGAN forma bilan birga ham chiqishi mumkin.
    //
    //      Xavfsizlik O'ZGARMAYDI: `DraftVault` faqat RAM'da, `claim` esa
    //      server tasdiqlagan `server|company|employee|branch` doirasining
    //      TO'LIQ tengligini talab qiladi — uni faqat muvaffaqiyatli parol
    //      logini qayta tiklaydi. Boshqa xodim, boshqa do'kon yoki boshqa
    //      server qoralamani KO'RMAYDI, begona urinish esa uni o'chiradi.
    //      Haqiqiy 401 ham qoralamani RAM'da qoldiradi, ya'ni yangi yuza
    //      ochilmaydi.
    //
    //      Token, PIN, biometrika va urinishlar sanog'i avvalgidek
    //      tozalanadi — fail-closed qulf zaiflashmaydi.
    // `mounted` tekshirilmaydi — sababi `leaveToLogin` hujjatida.
    leaveToLogin(mounted ? context : null); // qulf qatlamini ham yopadi
  }

  /// Holatga mos TUSHUNTIRISH. `corrupt` da xotira javob berdi — ma'lumot
  /// buzilgan, ya'ni qayta o'qish yordam bermaydi; shuni aytmaslik
  /// foydalanuvchini behuda «Qayta urinish» bosishga majburlardi.
  String get _explanation => switch (Lock.status) {
        LockStatus.corrupt => tr(
            'Saqlangan PIN ma’lumoti buzilgan, shuning uchun uni tekshirib bo‘lmaydi. Ma’lumotlaringiz yopiq qoldi — parol bilan kirib, yangi PIN o‘rnating.'),
        _ => tr(
            'Qurilmaning xavfsiz xotirasi javob bermadi, shuning uchun PIN holatini tasdiqlab bo‘lmadi. Ma’lumotlaringiz yopiq qoldi.'),
      };

  @override
  Widget build(BuildContext context) {
    // Qayta o'qish holatni aniqlagan bo'lsa — darvozaning qoidasiga
    // BO'YSUNAMIZ. Navigatsiya zanjiri o'rniga shu yerda almashtirish: oraliq
    // kadrda qobiq ko'rinib ketishi mumkin emas.
    if (Lock.statusKnown) {
      if (Lock.shouldLock) return LockScreen(onUnlocked: widget.onResolved);
      // PIN yo'q: tugallanmagan onboarding. Qobiqqa qaytarish fail-open
      // bo'lardi — qobiq USTIDA bo'lsak ham PIN so'raladi.
      if (Lock.status == LockStatus.absent) {
        return MandatoryPinSetupScreen(onDone: widget.onResolved);
      }
    }
    return PopScope(
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          // ⚠️  SCROLL SHART. Bu ekranning yagona ikki chiqish yo'li — pastdagi
          //     tugmalar, orqaga qaytish esa `PopScope` bilan to'silgan. Katta
          //     tizim yozuv o'lchamida (Accessibility) matn tugmalarni ekrandan
          //     chiqarib yuborsa, foydalanuvchi BUTUNLAY tiqilib qolardi.
          //     `SliverFillRemaining(hasScrollBody: false)` joy bo'lsa markazda
          //     ushlab turadi, joy yetmasa scroll ochadi.
          child: CustomScrollView(
            slivers: [
              SliverFillRemaining(
                hasScrollBody: false,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 16),
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
                      _explanation,
                      style: TextStyle(color: AppColors.text3, fontSize: 13.5, height: 1.45),
                      textAlign: TextAlign.center,
                    ),
                    // Xato matni O'Z balandligini oladi: qat'iy balandlikdagi
                    // quti uni kesib tashlardi (ru/ky matnlari ikki qatorga
                    // chiqadi, katta yozuv o'lchamida esa undan ham ko'proq).
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 14),
                        child: Semantics(
                          liveRegion: true,
                          child: Text(
                            _error!,
                            style: const TextStyle(
                                color: AppColors.danger, fontSize: 13, fontWeight: FontWeight.w600),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                    const Spacer(flex: 1),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      height: 52,
                      child: ElevatedButton(
                        onPressed: _idle ? _retry : null,
                        child: Text(_busy == _Busy.retry ? tr('Tekshirilmoqda…') : tr('Qayta urinish')),
                      ),
                    ),
                    const SizedBox(height: 10),
                    SizedBox(
                      width: double.infinity,
                      height: 52,
                      child: TextButton(
                        onPressed: _idle ? _reauth : null,
                        child: Text(
                            _busy == _Busy.reauth ? tr('Chiqilmoqda…') : tr('Parol bilan kirish')),
                      ),
                    ),
                    const Spacer(flex: 1),
                  ]),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
