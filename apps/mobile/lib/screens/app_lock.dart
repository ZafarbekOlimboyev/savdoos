import 'package:flutter/material.dart';

import '../lock.dart';
import 'lock_recovery_screen.dart';
import 'login_screen.dart';
import 'pin_screens.dart';

/// Ilovaning ildiz navigatori (`MaterialApp.navigatorKey`).
///
/// Bu yerda turadi, `main.dart` da emas: qulf qatlami Navigator'dan YUQORIDA
/// joylashgani uchun unga kalit orqali murojaat qilish kerak bo'ladi, va
/// `main.dart` ga bog'lanish ekran fayllarida aylanma import yasardi.
///
/// ⚠️  `final` EMAS: test harness'i har `pumpWidget` uchun YANGI kalit beradi.
///     Bitta `GlobalKey` bir vaqtda ikki `MaterialApp` da bo'lsa Flutter
///     "Duplicate GlobalKey" deb assert qiladi — E2E'da `pumpApp` dan keyin
///     `pumpScreen` chaqirilganda aynan shunday bo'lgan.
GlobalKey<NavigatorState> rootNavKey = GlobalKey<NavigatorState>();

/// Sessiyadan chiqib login ekraniga qaytish — qulf qatlamini ham yopadi.
///
/// ⚠️  ILDIZ navigatoriga murojaat qiladi. Qulf qatlamining O'Z navigatori bor
///     (modal varaqlar ishlashi uchun), shuning uchun u yerdagi
///     `Navigator.of(context)` login ekranini QULF ICHIGA push qilardi — ya'ni
///     foydalanuvchi qulf ostida qolib ketardi. Testlarda ildiz kaliti bo'sh
///     bo'lishi mumkin, shu bois mahalliy navigatorga qaytish yo'li bor.
void leaveToLogin([BuildContext? context]) {
  Lock.engaged.value = false;
  // ⚠️  ILDIZ navigatori BIRINCHI va u widget `mounted` holatiga BOG'LIQ EMAS.
  //     Bu muhim: `Lock.clear()` boshida `engaged=false` qiladi va keyin
  //     Keychain o'chirishlarini kutadi. O'sha oraliqda kadr chiziladi, qulf
  //     qatlami unmount bo'ladi — ya'ni chaqiruvchi `State` endi `mounted`
  //     emas. Agar navigatsiya `mounted` ga bog'langan bo'lsa, "Chiqish",
  //     12-urinish tozalashi va "Parol bilan kirish" LOGIN EKRANIGA UMUMAN
  //     yetib bormasdi va oldingi xodimning ekrani qolib ketardi.
  final nav = rootNavKey.currentState ??
      (context != null ? Navigator.maybeOf(context, rootNavigator: true) : null);
  nav?.pushAndRemoveUntil(
    MaterialPageRoute<void>(builder: (_) => const LoginScreen()),
    (route) => false,
  );
}

/// Qulf yoqilganda tizimdan kelgan "orqaga" so'rovini YUTADIGAN qorovul.
class _LockPopGuard with WidgetsBindingObserver {
  @override
  Future<bool> didPopRoute() async => Lock.engaged.value;
}

_LockPopGuard? _popGuard;

/// Qulfning global qorovullarini o'rnatadi.
///
/// ⚠️  `runApp` (yoki testda `pumpWidget`) dan OLDIN chaqirilishi SHART.
///     Flutter `handlePopRoute` da observerlarni QO'SHILISH TARTIBIDA
///     so'raydi va birinchi `true` javobda to'xtaydi. `WidgetsApp` o'z
///     observer'ini qurilish paytida qo'shadi, ya'ni `MaterialApp.builder`
///     ichidagi har qanday widget undan KEYIN keladi va hech qachon
///     so'ralmaydi — shuning uchun qorovul widget daraxtida tura olmaydi.
///
///     VoiceOver'ning ikki barmoqli "Escape" ishorasi va har qanday `popRoute`
///     platforma xabari aynan shu yo'ldan keladi; `IgnorePointer`,
///     `ExcludeFocus` va `Offstage` uni to'smaydi. Qorovulsiz qulf ostidagi
///     ekran jimgina pop bo'lib ketardi.
///
///     Har chaqiruvda QAYTA ro'yxatdan o'tkaziladi, shunchaki "bir marta"
///     emas: test binding'i daraxtni almashtirganda eski `WidgetsApp` ning
///     observer'i chiqib, yangisi QO'SHILADI — agar biz qayta qo'shilmasak,
///     tartibda ularning ORTIDA qolib ketardik va hech qachon so'ralmasdik.
void installLockGuards() {
  final guard = _popGuard ??= _LockPopGuard();
  WidgetsBinding.instance
    ..removeObserver(guard)
    ..addObserver(guard);
}

/// Qulfni butun ilova USTIGA qo'yadigan to'siq — YAKUNIY darvoza.
///
/// ⚠️  NEGA ROUTE EMAS. Ilgari fondan qaytgandagi qulf oddiy `Navigator` route
///     sifatida push qilinardi. O'lchangan (va `test/lock_bypass_test.dart` da
///     qotirilgan) uchta chetlab o'tish yo'li:
///
///       1. Qulf ostidagi kod YANGI route'ni qulf USTIGA push qila olardi
///          (uzluksiz skaner natijasi aynan shunday chiqardi).
///       2. `Navigator.pop()` qulfni BUTUNLAY yo'q qilardi — `PopScope(canPop:
///          false)` faqat tizim "orqaga" ishorasini to'sadi, programmali
///          pop'ni EMAS. Ilova qulfsiz qobiqqa qaytardi.
///       3. Qulf ostidagi kamera oqimi ishlashda davom etib, qulflangan
///          ilovadan AUTHENTICATED `GET /products/scan` so'rovi ketardi.
///
///     Qatlam Navigator'dan YUQORIDA turgani uchun (1) va (2) endi tuzilish
///     bo'yicha mumkin emas: ostidagi hech qanday route undan baland bo'la
///     olmaydi va uni pop qila olmaydi.
///
///     (3) ni esa faqat vizual to'siq hal qilmaydi — [IgnorePointer] tegishni
///     to'sadi, lekin kamera oqimi tegishga bog'liq EMAS. Shu bois
///     foydalanuvchi tegishidan mustaqil manbalar [Lock.engaged] ni o'zi
///     tekshiradi (qarang `barcode_scan_screen.dart` `_onCode`).
class AppLockBarrier extends StatefulWidget {
  /// Ilovaning qolgan qismi (Navigator).
  const AppLockBarrier({super.key, required this.child});

  /// `MaterialApp.builder` bergan daraxt.
  final Widget child;

  @override
  State<AppLockBarrier> createState() => _AppLockBarrierState();
}

class _AppLockBarrierState extends State<AppLockBarrier> {
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<bool>(
        valueListenable: Lock.engaged,
        builder: (context, engaged, _) => Stack(
          children: [
            // ⚠️  `Offstage` — ENG MUHIM QATLAM. Qulf endi route emas, qo'shni
            //     `Stack` bolasi: uning `opaque` bayrog'i faqat O'Z
            //     Navigator'iga ta'sir qiladi, ilova daraxtiga EMAS. Mavzuda
            //     esa `scaffoldBackgroundColor` va `canvasColor` ataylab
            //     `Colors.transparent` (fon `ThemedBackground` orqali
            //     chiziladi), ya'ni qulf ekranining `Scaffold` i ham shaffof.
            //     Natijada PIN klaviaturasi ORTIDAN savdo, kassa va qarz
            //     raqamlari O'QILARDI — buni `test/lock_visibility_test.dart`
            //     piksel darajasida o'lchaydi.
            //
            //     `Offstage` ostidagi daraxtni UMUMAN chizmaydi, lekin element
            //     va `State` larni saqlaydi — operator qulfni ochgach qayerda
            //     qolgan bo'lsa, o'sha yerda qoladi. `TickerMode` esa qulf
            //     ostidagi animatsiyalarni to'xtatadi.
            //
            //     `IgnorePointer`/`ExcludeFocus` ATAYLAB qoldirilgan: ular
            //     tegish va klaviatura uchun mustaqil ikkinchi qator himoya.
            Offstage(
              offstage: engaged,
              child: TickerMode(
                enabled: !engaged,
                child: ExcludeFocus(
                  excluding: engaged,
                  child: IgnorePointer(ignoring: engaged, child: widget.child),
                ),
              ),
            ),
            if (engaged) const Positioned.fill(child: _LockLayer()),
          ],
        ),
      );
}

/// Qulf qatlamining mazmuni. O'Z `Navigator` i bor: qulf ekranidagi tasdiq
/// varaqasi (`confirmDestructive` -> `showModalBottomSheet`) Navigator talab
/// qiladi, qatlam esa ilova Navigator'idan yuqorida.
class _LockLayer extends StatelessWidget {
  const _LockLayer();

  @override
  Widget build(BuildContext context) =>
      // ⚠️  `HeroControllerScope.none` SHART: aks holda bu Navigator
      //     `MaterialApp` ning HeroController'ini ilova Navigator'i bilan
      //     BAHAM ko'radi va Flutter "A HeroController can not be shared by
      //     multiple Navigators" deb assert qiladi. Qulf qatlamida Hero
      //     animatsiyasi kerak emas.
      // ⚠️  O'Z `ScaffoldMessenger` i: qulf ekranlarining `Scaffold` lari aks
      //     holda ILOVA darajasidagi messenger'ga ro'yxatdan o'tadi va qulf
      //     ostidagi ekranlardan chiqqan SnackBar qulf USTIDA ko'rinadi —
      //     ular `userMessage(e)` orqali server matnini (mahsulot nomi,
      //     miqdor) olib chiqishi mumkin.
      ScaffoldMessenger(
        child: HeroControllerScope.none(
          child: Navigator(
            onGenerateRoute: (_) => PageRouteBuilder<void>(
              opaque: true,
              transitionDuration: Duration.zero,
              reverseTransitionDuration: Duration.zero,
              pageBuilder: (_, __, ___) => const _LockLayerContent(),
            ),
          ),
        ),
      );
}

class _LockLayerContent extends StatelessWidget {
  const _LockLayerContent();

  /// Qulf ochildi (yoki endi shart emas) — qatlam yopiladi.
  static void _disengage() => Lock.engaged.value = false;

  @override
  Widget build(BuildContext context) {
    // Holat noma'lum bo'lsa tekshiriladigan xesh yo'q: PIN so'rash boshi berk
    // ko'cha bo'lardi. Qaror `lockGateHome()` bilan AYNI qoidaga tayanadi.
    if (!Lock.statusKnown) {
      return const LockRecoveryScreen(onResolved: _disengage);
    }
    return const LockScreen(onUnlocked: _disengage);
  }
}
