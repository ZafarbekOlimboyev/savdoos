// Pumping helpers: a phone-sized viewport (390×844 logical, DPR 3 — the
// Fayzan pilot phones) and a MaterialApp wrapper with the real theme.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/theme.dart';

/// Logical phone size used by every widget test.
const Size kPhoneSize = Size(390, 844);

/// Wraps [home] in the app's MaterialApp shell (theme + themed background).
///
/// ⚠️  `AppLockBarrier` HAM shu yerda, `main.dart` dagi kabi `builder` ichida.
///     U qulf yoqilmaganda to'liq no-op, lekin tuzilishi bo'yicha production
///     bilan AYNI bo'lishi SHART: aks holda widget testlari qulf ostidagi
///     xulqni umuman ko'rmaydi va chetlab o'tish yo'llari sezilmay qolardi.
Widget testApp(Widget home, {List<NavigatorObserver> observers = const []}) {
  // Har pump uchun YANGI kalit: eski daraxt hali unmount bo'lmagan paytda
  // bitta `GlobalKey` ikki `MaterialApp` da bo'lsa Flutter duplicate deb
  // assert qiladi (E2E: `pumpApp` -> `pumpScreen`).
  rootNavKey = GlobalKey<NavigatorState>();
  return MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: buildTheme(),
    // ⚠️  `navigatorKey` HAM production bilan ayni: qulf qatlamidan chiqish
    //     (`leaveToLogin`) ILDIZ navigatorini kalit orqali topadi. Kalit
    //     bo'lmasa u qatlamning O'Z navigatoriga tushib, login ekranini
    //     qulf ICHIGA push qilardi — ya'ni test production'dan boshqacha
    //     yo'ldan yurib, aynan shu nuqsonni yashirardi.
    navigatorKey: rootNavKey,
    navigatorObservers: observers,
    builder: (context, child) => ThemedBackground(
      child: AppLockBarrier(child: child ?? const SizedBox.shrink()),
    ),
    home: home,
  );
}

/// Sets a 390×844 @3x viewport (reset after the test) and pumps [widget]
/// (wrapped in [testApp] unless [wrap] is false).
Future<void> pumpAt390(WidgetTester tester, Widget widget, {bool wrap = true}) async {
  setPhoneViewport(tester);
  await tester.pumpWidget(wrap ? testApp(widget) : widget);
}

/// Sets the 390×844 @3x viewport only.
void setPhoneViewport(WidgetTester tester) {
  tester.view.physicalSize = Size(kPhoneSize.width * 3, kPhoneSize.height * 3);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

/// A scaffold host with a button that runs [onPressed] with a context under
/// the Navigator (for sheets/dialogs/pushes).
class LaunchHost extends StatelessWidget {
  const LaunchHost({super.key, required this.onPressed, this.label = 'open'});
  final void Function(BuildContext context) onPressed;
  final String label;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: Builder(
            builder: (ctx) => ElevatedButton(onPressed: () => onPressed(ctx), child: Text(label)),
          ),
        ),
      );
}

/// Asserts that every hit-testable widget of [finder] is at least 48×48.
void expectMinTouchTarget(WidgetTester tester, Finder finder, {double min = 48}) {
  expect(finder, findsWidgets);
  for (final e in finder.evaluate()) {
    final size = (e.renderObject! as RenderBox).size;
    expect(size.height >= min - 0.01 && size.width >= min - 0.01, isTrue,
        reason: '${e.widget.runtimeType} is ${size.width}x${size.height}, below ${min}dp');
  }
}

/// Lets real IO complete, then pumps frames. Api purges the legacy catalog
/// cache files on logout / server change (a directory listing + deletes: SEVERAL
/// real-IO steps), and each step's continuation runs in the fake-async zone —
/// so real-IO turns and fake pumps are interleaved until nothing is left.
Future<void> flushIo(WidgetTester tester) async {
  for (var i = 0; i < 16; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
    await tester.pump(const Duration(milliseconds: 50));
  }
}
