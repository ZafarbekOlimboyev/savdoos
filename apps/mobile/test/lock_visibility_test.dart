// R6 — QULF YOQILGANDA HIMOYALANGAN KONTENT KO'RINMASLIGI (P0).
//
// ⚠️  NEGA BU TEST BOR. R5.2 da qulf `Navigator` route'idan butun ilova
//     ustidagi QATLAMGA (`AppLockBarrier`) ko'chirildi. Bu push/pop orqali
//     chetlab o'tishni tuzatdi, LEKIN ko'rinishni yo'qotdi:
//
//       * eski route `opaque: true` edi va AYNI Overlay'dagi ostki route'lar
//         umuman chizilmasdi;
//       * yangi qatlam esa qo'shni `Stack` bolasi — uning `opaque` bayrog'i
//         faqat O'Z Navigator'iga ta'sir qiladi, ilova daraxtiga emas;
//       * `theme.dart` da `scaffoldBackgroundColor` va `canvasColor` ataylab
//         `Colors.transparent` (fon `ThemedBackground` orqali chiziladi), ya'ni
//         qulf ekranining `Scaffold` i ham SHAFFOF.
//
//     Natija: PIN klaviaturasi ortidan savdo, kassa, qarz va mijoz
//     ma'lumotlari O'QILADI. `IgnorePointer` tegishni to'sadi, `ExcludeFocus`
//     klaviaturani to'sadi — lekin KO'RISH to'silmaydi.
//
//     Egasining talabi aynan shu: "Qulf faol bo'lsa, himoyalangan ma'lumot
//     KO'RINMASLIGI ... kerak. Vizual overlay mavjudligining o'zi PASS emas."
//
//     Shu bois bu test widget daraxtini emas, HAQIQIY PIKSELLARNI tekshiradi.
@TestOn('vm')
library;

import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';

import 'support/support.dart';

/// Mavzuda uchramaydigan, ataylab yorqin rang — "maxfiy kontent" belgisi.
const Color kSecretColor = Color(0xFF00FF00);

final GlobalKey _shotKey = GlobalKey();

/// Ekranning HAQIQIY piksellari ichida [c] rangi bormi.
Future<bool> _pixelsContain(WidgetTester tester, Color c) async {
  final boundary = _shotKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  late final ui.Image image;
  await tester.runAsync(() async => image = await boundary.toImage());
  final data = await tester.runAsync(
      () async => image.toByteData(format: ui.ImageByteFormat.rawRgba));
  final bytes = data!.buffer.asUint8List();
  final r = (c.r * 255).round(), g = (c.g * 255).round(), b = (c.b * 255).round();
  for (var i = 0; i + 3 < bytes.length; i += 4) {
    if (bytes[i] == r && bytes[i + 1] == g && bytes[i + 2] == b && bytes[i + 3] == 255) {
      return true;
    }
  }
  return false;
}

/// Qulf ostida turadigan "himoyalangan" ekran: butun maydonni maxfiy rang
/// bilan bo'yaydi. Haqiqiy qobiqdagi raqamlar o'rniga rang — tekshiruv
/// aniq va tez bo'lsin.
Widget _protectedScreen() => const ColoredBox(
      color: kSecretColor,
      child: Center(child: Text('MAXFIY')),
    );

void main() {
  setUp(() async {
    await resetCore();
    await Lock.clear();
    Lock.engaged.value = false;
  });

  tearDown(() async {
    Lock.engaged.value = false;
    await Lock.clear();
  });

  Future<void> pumpApp(WidgetTester t) async {
    // ⚠️  `RepaintBoundary` BUTUN ilovadan YUQORIDA bo'lishi SHART.
    //     `AppLockBarrier` `MaterialApp.builder` ichida turadi, ya'ni `home`
    //     dan yuqorida — boundary'ni `home` ga qo'ysak, u qulf qatlamining
    //     ICHIDA qolib, biz o'lchayotgan narsa ekran emas, yopilgan daraxtning
    //     o'zi bo'lardi.
    setPhoneViewport(t);
    await t.pumpWidget(
      RepaintBoundary(key: _shotKey, child: testApp(_protectedScreen())),
    );
    await t.pumpAndSettle();
  }

// ───────────────────────────────────────────────────────────────────────────
// ───────────────────────────────────────────────────────────────────────────
  group('Ilova FAOL emasda kontent yopiladi (App Switcher surati)', () {
    // ⚠️  iOS ilova fonga chiqqanda ekranning SURATINI oladi va uni App
    //     Switcher'da ko'rsatadi. Telefonni qo'liga olgan kishi ilovani
    //     OCHMASDAN, PIN ham so'ralmasdan oxirgi ekranni o'qiy oladi.
    //     Native parda `ios/Runner/SceneDelegate.swift` da; bu yerda Flutter
    //     tomonidagi IKKINCHI parda tekshiriladi — u `inactive` dan boshlab
    //     ishlaydi va native parda olingan paytdagi oraliqni yopadi.
    /// ⚠️  Flutter lifecycle mashinasi TO'G'RIDAN-TO'G'RI o'tishga ruxsat
    ///     bermaydi: `resumed` dan `paused` ga borish uchun `inactive` va
    ///     `hidden` orqali o'tish SHART. Aks holda hodisa jimgina tashlanadi
    ///     va test "parda ishlamadi" deb yolg'on signal beradi.
    const chain = [
      AppLifecycleState.inactive,
      AppLifecycleState.hidden,
      AppLifecycleState.paused,
    ];

    Future<void> lifecycle(WidgetTester t, AppLifecycleState st) async {
      if (st == AppLifecycleState.resumed) {
        for (final s in chain.reversed.skip(1)) {
          t.binding.handleAppLifecycleStateChanged(s);
        }
        t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      } else {
        for (final s in chain) {
          t.binding.handleAppLifecycleStateChanged(s);
          if (s == st) break;
        }
      }
      await t.pumpAndSettle();
    }

    for (final st in const [
      AppLifecycleState.inactive,
      AppLifecycleState.hidden,
      AppLifecycleState.paused,
    ]) {
      testWidgets('${st.name}: himoyalangan kontent PIKSEL darajasida yo`q', (t) async {
        await pumpApp(t);
        expect(await _pixelsContain(t, kSecretColor), isTrue, reason: 'nazorat');

        await lifecycle(t, st);
        expect(await _pixelsContain(t, kSecretColor), isFalse,
            reason: '${st.name} holatida kontent ko`rinib turibdi — iOS aynan '
                'shu paytda App Switcher suratini oladi');
      });
    }

    testWidgets('resumed: kontent QAYTADI (qulf shart bo`lmasa)', (t) async {
      await pumpApp(t);
      await lifecycle(t, AppLifecycleState.paused);
      expect(await _pixelsContain(t, kSecretColor), isFalse);

      await lifecycle(t, AppLifecycleState.resumed);
      expect(await _pixelsContain(t, kSecretColor), isTrue,
          reason: 'qaytganda kontent ochilishi kerak');
    });

    testWidgets('qulf kerak bo`lsa resumed`da ham YOPIQ qoladi', (t) async {
      await Lock.setPin('2468');
      Lock.relockAfter = Duration.zero;
      Lock.debugResetBackground();
      await pumpApp(t);

      await lifecycle(t, AppLifecycleState.paused);
      expect(await _pixelsContain(t, kSecretColor), isFalse);

      // Qulf qarori: fonda bo'lgan, demak qaytganda qulflanadi.
      Lock.markBackground(DateTime(2026, 10, 28, 10));
      if (Lock.consumeResume(DateTime(2026, 10, 28, 11))) {
        Lock.engaged.value = true;
      }
      await lifecycle(t, AppLifecycleState.resumed);

      expect(Lock.engaged.value, isTrue, reason: 'test o`zini sozlay olmadi');
      expect(await _pixelsContain(t, kSecretColor), isFalse,
          reason: 'qulf yoqilgan bo`lsa kontent ochilmasligi SHART');
    });
  });

  group('PIN ekrani: landscape va katta yozuvda ham TO`LIQ ishlaydi', () {
    // ⚠️  `Info.plist` landscape'ga ruxsat beradi va Dart'da orientatsiya
    //     qulfi yo'q. Ilgari PIN ekrani `Spacer` li `Column` edi va 667x375
    //     landscape'da faqat 1-6 tugmalar ko'rinardi: "0", backspace va
    //     "Chiqish" EKRANDAN TASHQARIDA qolardi. Ya'ni PIN'ida "0" bo'lgan
    //     operator ilovani UMUMAN ocha olmasdi.
    for (final size in const [
      Size(320, 568), // eng kichik iOS 15 qurilma, portret
      Size(375, 667),
      Size(390, 844),
      Size(568, 320), // LANDSCAPE
      Size(667, 375), // LANDSCAPE
      Size(844, 390), // LANDSCAPE
    ]) {
      for (final scale in const [1.0, 2.0, 3.0]) {
        testWidgets('${size.width.toInt()}x${size.height.toInt()} @${scale}x — barcha raqamlar yetib boriladi',
            (t) async {
          L.code = 'ru'; // eng uzun tarjimalar
          await Lock.clear();
          await Lock.setPin('2468');

          t.view.physicalSize = Size(size.width * 3, size.height * 3);
          t.view.devicePixelRatio = 3.0;
          t.view.padding = const FakeViewPadding(top: 141, bottom: 102);
          t.platformDispatcher.textScaleFactorTestValue = scale;
          addTearDown(t.view.resetPhysicalSize);
          addTearDown(t.view.resetDevicePixelRatio);
          addTearDown(t.view.resetPadding);
          addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);

          // Overflow bo'lsa `FlutterError` otiladi va test O'ZI yiqiladi.
          await t.pumpWidget(testApp(const LockScreen()));
          await t.pump();

          // HAR BIR raqam va backspace YETIB BORILADIGAN bo'lishi SHART.
          for (final d in const ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']) {
            final f = find.text(d);
            expect(f, findsWidgets, reason: '«$d» tugmasi daraxtda yo`q');
            await t.ensureVisible(f.first);
          }
          await t.ensureVisible(find.byIcon(Icons.backspace_outlined));

          // ⚠️  Bu tasdiqlar IKKI narsani qoplaydi. Birinchisi: `Column`
          //     toshsa Flutter `RenderFlex overflow` xatosini otadi va test
          //     O'ZI yiqiladi — scroll qo'shilishidan oldin landscape'da
          //     aynan shunday bo'lardi (352-456 px). Ikkinchisi:
          //     `ensureVisible` tugma ekrandan tashqarida bo'lib, scroll ham
          //     bo'lmasa xato beradi — ya'ni "0" tugmasiga yetib borilmasligi
          //     ham ushlanadi.
        });
      }
    }
  });

  group('Qulf yoqilganda himoyalangan kontent KO`RINMAYDI', () {
    testWidgets('qulfsiz holatda kontent ko`rinadi (nazorat)', (t) async {
      await pumpApp(t);
      expect(await _pixelsContain(t, kSecretColor), isTrue,
          reason: 'nazorat yiqildi — test o`zini sozlay olmadi');
    });

    testWidgets('PIN qulfi yoqilganda kontent PIKSEL darajasida yo`q', (t) async {
      await Lock.setPin('2468');
      await pumpApp(t);
      expect(await _pixelsContain(t, kSecretColor), isTrue, reason: 'nazorat');

      Lock.engaged.value = true;
      await t.pumpAndSettle();

      expect(find.byType(LockScreen), findsOneWidget, reason: 'qulf ekrani chiqmadi');
      expect(await _pixelsContain(t, kSecretColor), isFalse,
          reason: 'HIMOYALANGAN KONTENT QULF ORTIDAN KO`RINADI — '
              'PIN klaviaturasi ustida savdo/kassa/qarz raqamlari o`qiladi');
    });

    testWidgets('qulf ochilgach kontent QAYTADI (holat yo`qolmaydi)', (t) async {
      await Lock.setPin('2468');
      await pumpApp(t);
      Lock.engaged.value = true;
      await t.pumpAndSettle();
      expect(await _pixelsContain(t, kSecretColor), isFalse);

      Lock.engaged.value = false;
      await t.pumpAndSettle();
      expect(await _pixelsContain(t, kSecretColor), isTrue,
          reason: 'qulf ochilgach operator qayerda qolgan bo`lsa — o`sha yerda '
              'bo`lishi kerak, ekran qayta qurilmasligi lozim');
    });

    testWidgets('tiklash ekrani (holat noma`lum) ham kontentni yopadi', (t) async {
      // PIN o'rnatmaymiz: holat `absent` bo'ladi, lekin qatlam baribir
      // ko'rinishni to'sishi SHART — qaysi ekran chiqishidan qat'i nazar.
      await pumpApp(t);
      Lock.engaged.value = true;
      await t.pumpAndSettle();
      expect(await _pixelsContain(t, kSecretColor), isFalse,
          reason: 'qatlam qaysi ekranni ko`rsatishidan qat`i nazar yopishi kerak');
    });
  });
}
