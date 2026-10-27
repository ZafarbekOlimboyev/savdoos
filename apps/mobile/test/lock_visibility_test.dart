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
