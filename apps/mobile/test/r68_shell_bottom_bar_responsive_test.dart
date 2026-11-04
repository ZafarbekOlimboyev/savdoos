// R6.8 UI — PASTKI NAVIGATSIYA KATTA YOZUVDA TOSHADI.
//
// ⚠️  QAYERDAN TOPILDI. Bu nuqson mahsulot tafsiloti responsive auditini
//     SIMULYATORDA tasdiqlash paytida ko'rindi: iPhone 17 Pro'da iOS yozuv
//     o'lchami `accessibility-extra-extra-extra-large` ga qo'yilganda ekranning
//     pastida Flutter'ning qizil chizig'i chiqdi —
//     «BOTTOM OVERFLOWED BY 12 PIXELS», har bir yorliq uchun bittadan.
//
// ⚠️  SABAB. `shell.dart` dagi `_BottomBar` pufagi QAT'IY balandlikda
//     (`height: 62`), uning ichidagi har yacheyka esa `Column`:
//       ikonka 22 + oraliq 3 + yorliq (fontSize 10.5)
//     Yozuv 3.1× bo'lganda yorliq ~33-44 px ga chiqadi va ustun 62 px ga
//     SIG'MAYDI. Release build'da qizil chiziq ko'rinmaydi — matn jimgina
//     KESILADI, ya'ni nuqson yashirin bo'lib qoladi.
//
// ⚠️  NEGA MUHIM. Apple App Review Dynamic Type'ni sinaydi, va do'kon
//     egalarining katta qismi yoshi kattaroq odamlar — ular tizim yozuvini
//     ataylab kattalashtiradi.
@TestOn('vm')
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    // Bosh ekran so'rovlari — javob bo'lmasa `InlineAsync` xato ko'rsatadi,
    // lekin PASTKI PANEL baribir chiziladi (biz o'lchayotgan narsa shu).
    be.get('/reports/overview', (r) => {'total': 0, 'count': 0});
    be.get('/sales', (r) => []);
    //  ⚠️  KALITLAR `shell.dart:243` BILAN AYNAN MOS BO'LISHI SHART:
    //      `_attention = n(m['low_count']) + n(m['out_count'])`.
    //      Ilgari bu yerda `{'low': 0, 'out': 0, 'expiring': 0}` turardi —
    //      noto'g'ri kalitlar, ya'ni `_attention` HAR DOIM 0 va `Badge`
    //      HECH QACHON qurilmasdi. Natijada 320/375/390/430 px x
    //      1.0..3.5x matritsasi badgeli tartibni UMUMAN qamramasdi, lekin
    //      «23/23 yashil» deb hisobot berardi. Raqib tekshiruvi topdi.
    be.get('/inventory/overview', (r) => {'low_count': 7, 'out_count': 2});
    be.get('/lots/alerts', (r) => {'expiring': 0, 'expired': 0});
  });
  tearDown(() {
    Session.instance.debugReset();
    L.code = 'uz';
  });

  /// Ekranni sozlab `Shell` ni chizadi.
  Future<void> pumpShell(WidgetTester t, Size ekran, double yozuv, String til) async {
    L.code = til;
    t.view.physicalSize = Size(ekran.width * 3, ekran.height * 3);
    t.view.devicePixelRatio = 3.0;
    t.view.padding = const FakeViewPadding(top: 141, bottom: 102);
    t.platformDispatcher.textScaleFactorTestValue = yozuv;
    addTearDown(t.view.resetPhysicalSize);
    addTearDown(t.view.resetDevicePixelRatio);
    addTearDown(t.view.resetPadding);
    addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);

    await signInAs(be);
    await be.run(() async {
      // ⚠️  Toshish bo'lsa Flutter `FlutterError` otadi va test O'ZI yiqiladi.
      await t.pumpWidget(testApp(const Shell()));
      await t.pumpAndSettle();
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 1. TOSHISH YO'Q — barcha kenglik va yozuv o'lchamlarida
  // ═══════════════════════════════════════════════════════════════════════════

  for (final ekran in const [Size(320, 568), Size(375, 667), Size(390, 844), Size(430, 932)]) {
    for (final yozuv in const [1.0, 1.5, 2.0, 3.0, 3.5]) {
      testWidgets('${ekran.width.toInt()}px @${yozuv}x — pastki panel toshmaydi', (t) async {
        await pumpShell(t, ekran, yozuv, 'uz');
        expect(find.byKey(const Key('tab-home')), findsOneWidget,
            reason: 'pastki panel umuman chizilmadi — test o`lchamadi');
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 2. YORLIQLAR KESILMAYDI — panel yozuv bilan BIRGA o'sadi
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('katta yozuvda yorliqlar panel ICHIDA qoladi', (t) async {
    await pumpShell(t, const Size(390, 844), 3.0, 'ru'); // eng uzun tarjimalar
    final panel = t.getRect(find.byKey(const Key('shell-bottom-pill')));
    final xato = <String>[];
    for (final k in const ['home', 'analytics', 'stock', 'settings']) {
      final f = find.descendant(
          of: find.byKey(Key('tab-$k')), matching: find.byType(Text));
      if (f.evaluate().isEmpty) continue;
      final r = t.getRect(f.first);
      if (r.bottom > panel.bottom + 0.5 || r.top < panel.top - 0.5) {
        xato.add('«$k» y=[${r.top.toStringAsFixed(1)}..${r.bottom.toStringAsFixed(1)}] '
            'panel=[${panel.top.toStringAsFixed(1)}..${panel.bottom.toStringAsFixed(1)}]');
      }
    }
    expect(xato, isEmpty, reason: 'YORLIQ PANELDAN CHIQIB KETDI:\n${xato.join("\n")}');
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 1c. NISHON (Badge) PUFAK ICHIDA QOLADI
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  NEGA ALOHIDA TASDIQ. `Badge` o'z bolasining (22 px ikonka)
  //     TASHQARISIGA chiziladi: Material standarti `alignment: topEnd`,
  //     `largeSize: 16`, yorliq shrifti `labelSmall` (11 px) va u YOZUV
  //     O'LCHAMI bilan o'sadi. `_pufakH` hisobida esa faqat ikonka (22) bor.
  //     Ya'ni toshish `RenderFlex overflow` bermaydi — nishon jimgina
  //     pufakdan TASHQARIDA chiziladi.
  //
  //     Boshqa tasdiqlar buni ko'rmaydi: toshish xatosi yo'q, yorliq matni
  //     esa joyida. Shu bois nishon to'rtburchagi ALOHIDA o'lchanadi.

  for (final yozuv in const [1.0, 1.5, 2.0, 3.0, 3.5]) {
    testWidgets('nishon pufak ichida qoladi @${yozuv}x', (t) async {
      await pumpShell(t, const Size(390, 844), yozuv, 'uz');
      final bf = find.byKey(const Key('stock-badge'));
      expect(bf, findsOneWidget,
          reason: 'NISHON CHIZILMADI — fikstura kalitlari `shell.dart:243` '
              'bilan mos emas, ya`ni bu matritsa badgeli tartibni qamramaydi');

      final pufak = t.getRect(find.byKey(const Key('shell-bottom-pill')));
      // Nishon pufagi — `Badge` ichidagi MATN (raqam) joylashgan joy.
      final lbl = find.descendant(of: bf, matching: find.byType(Text));
      expect(lbl, findsWidgets, reason: 'nishon yorlig`i topilmadi');
      final r = t.getRect(lbl.first);

      final chiqdi = <String>[];
      if (r.top < pufak.top - 0.5) {
        chiqdi.add('tepadan ${(pufak.top - r.top).toStringAsFixed(1)} dp');
      }
      if (r.bottom > pufak.bottom + 0.5) {
        chiqdi.add('pastdan ${(r.bottom - pufak.bottom).toStringAsFixed(1)} dp');
      }
      if (r.right > pufak.right + 0.5) {
        chiqdi.add('o`ngdan ${(r.right - pufak.right).toStringAsFixed(1)} dp');
      }
      expect(chiqdi, isEmpty,
          reason: 'NISHON PUFAKDAN TASHQARIDA CHIZILDI (${chiqdi.join(", ")}) — '
              'nishon=[${r.top.toStringAsFixed(1)}..${r.bottom.toStringAsFixed(1)}] '
              'pufak=[${pufak.top.toStringAsFixed(1)}..${pufak.bottom.toStringAsFixed(1)}]');
    });
  }

  testWidgets('yorliq tugmalari 48 dp tegish maydonidan PAST tushmaydi', (t) async {
    //  ⚠️  BU TASDIQ REGRESSIYADAN KEYIN QO'SHILDI. Tuzatishning birinchi
    //      variantida yacheyka ustuniga `MainAxisSize.min` qo'yilgan edi —
    //      ustun mazmuniga qarab qisqarib, `GestureDetector` 62 dp o'rniga
    //      40 dp bo'lib qoldi, ya'ni Material talab qiladigan 48 dp dan PAST.
    //      `shell_branch_test.dart` buni ushladi; bu yerda esa KATTA yozuvda
    //      ham qadab qo'yiladi, chunki panel balandligi endi yozuvga bog'liq.
    for (final yozuv in const [1.0, 2.0, 3.0, 3.5]) {
      await pumpShell(t, const Size(390, 844), yozuv, 'uz');
      for (final k in const ['home', 'analytics', 'stock', 'settings']) {
        expectMinTouchTarget(t, find.byKey(Key('tab-$k')));
      }
    }
  });

  testWidgets('odatiy yozuvda panel balandligi O`ZGARMAYDI (62)', (t) async {
    // ⚠️  Tuzatish ko'rinishni o'zgartirmasligi SHART: 1.0x da panel AYNI
    //     62 px bo'lib qolishi kerak.
    await pumpShell(t, const Size(390, 844), 1.0, 'uz');
    final panel = t.getRect(find.byKey(const Key('shell-bottom-pill')));
    expect(panel.height, 62.0,
        reason: 'odatiy yozuvda panel balandligi o`zgargan — dizayn buzildi');
  });
}
