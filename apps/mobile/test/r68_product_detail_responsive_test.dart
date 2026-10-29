// R6.8 UI §4 — MAHSULOT TAFSILOTI EKRANINING RESPONSIVE AUDITI.
//
// ⚠️  NIMA O'LCHANADI. Ikki xil nuqson sinfi:
//
//       1. `RenderFlex overflow` — Flutter `FlutterError` otadi va test O'ZI
//          yiqiladi. `Row` ichidagi `Expanded`siz matnlar aynan shunday
//          buziladi (katta yozuvda ularning kengligi oshadi, Row esa
//          siqilmaydi).
//       2. EKRANDAN CHIQIB KETGAN MATN — toshish xatosi berilmasa ham matn
//          kesilib qolishi mumkin (`ClipRect` ostida, yoki `Expanded` ichida
//          `maxLines: 1` bilan). Shu bois har bir `Text` ning haqiqiy
//          to'rtburchagi viewport ichida ekani ALOHIDA tekshiriladi.
//
// ⚠️  SPETSIFIKATSIYA TALABI: «Kontentni majburan kichraytirish orqali
//     muammoni yashirma». Shu bois bu yerda `textScaleFactor` qisqartirilmaydi
//     va `FittedBox` ishlatilmaydi — o'lchov HAQIQIY foydalanuvchi
//     sozlamalarida olinadi.
@TestOn('vm')
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/theme.dart';

import 'stock_fixtures_test.dart';

/// Eng «og'ir» tafsilot javobi: barcha bo'limlar to'ldirilgan, raqamlar UZUN.
///
/// ⚠️  UZUN RAQAMLAR ATAYLAB. Do'kon ilovasida summalar so'mda bo'ladi, ya'ni
///     7-9 xonali. Qisqa raqam bilan o'lchash layoutni YENGIL ko'rsatardi.
Map<String, dynamic> _ogirDetail() => {
      ...prodJson('p1', 'Qatiq «Nasiba» 900 ml yarim yog`li', stock: 12),
      'buy_price': 1234567,
      'sell_price': 2345678,
      'profit_unit': 1111111,
      'margin_pct': 47.5,
      'month_in': 123456,
      'month_out': 98765,
      'min_qty': 54321,
      'sales_7d': {'qty': 12345, 'revenue': 123456789, 'profit': 23456789},
      'sales_30d': {'qty': 54321, 'revenue': 987654321, 'profit': 123456789},
      'created_by_name': 'Zafarbek Olimboyev',
    };

/// Harakatlar ro'yxati — `_move()` qatori eng siqilgan joy (ikkita `Text`
/// `Expanded`siz: miqdor va sana).
List<Map<String, dynamic>> _harakatlar() => [
      {
        'type': 'Inventarizatsiya tuzatishi',
        'direction': 'in',
        'name': 'Qatiq',
        'qty': 123456,
        'employee': 'Zafarbek Olimboyev',
        'at': '2026-09-18 10:00:00',
      },
      {
        'type': 'Hisobdan chiqarish',
        'direction': 'out',
        'name': 'Qatiq',
        'qty': 98765,
        'employee': 'Dilnoza Karimova',
        'at': '2026-10-29 23:59:00',
      },
    ];

/// Bitta yacheyka natijasi.
class _Olchov {
  _Olchov(this.xato, this.korilgan);

  /// Ekrandan chiqib ketgan matnlar tavsifi.
  final List<String> xato;

  /// Aylantirish davomida KO'RILGAN barcha matnlar — o'lchov haqiqatan
  /// bajarilganini tasdiqlash uchun (ijobiy nazorat).
  final Set<String> korilgan;
}

/// Viewport'dan CHIQIB ketgan matnlar.
List<String> _chiqibKetganMatnlar(WidgetTester t, Size ekran) {
  const chek = 0.5; // anti-aliasing uchun
  final xato = <String>[];
  for (final e in t.elementList(find.byType(Text))) {
    final ro = e.renderObject;
    if (ro is! RenderBox || !ro.hasSize || ro.size.isEmpty) continue;
    final r = ro.localToGlobal(Offset.zero) & ro.size;
    if (r.right > ekran.width + chek || r.left < -chek) {
      final w = e.widget as Text;
      xato.add('«${w.data ?? ''}» x=[${r.left.toStringAsFixed(1)}..'
          '${r.right.toStringAsFixed(1)}] (ekran ${ekran.width.toInt()})');
    }
  }
  return xato;
}

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
    be.get('/products/{id}', (r) => _ogirDetail());
    be.get('/inventory/movements', (r) => _harakatlar());
  });
  tearDown(() async {
    Session.instance.debugReset();
    L.code = 'uz';
    await AppTheme.set('tungi');
  });

  /// Bitta o'lchov yacheykasi: ekranni sozlaydi, tafsilotni ochadi va
  /// ro'yxatni OXIRIGACHA aylantirib, HAR bosqichda matnlarni o'lchaydi.
  ///
  /// ⚠️  AYLANTIRISH SHART — bu birinchi variantning NUQSONI edi (o'lchangan).
  ///     `ListView` DANGASA quradi: «So'nggi harakatlar» bo'limi ekran ostida
  ///     bo'lsa, uning `_move()` qatorlari UMUMAN qurilmaydi. Natijada test
  ///     faqat yuqori qismni o'lchab, YASHIL berardi — mutatsiya nazorati
  ///     buni fosh qildi: sana matnini qat'iy 300 px ga qo'yish ham testni
  ///     qizil qilmadi, chunki o'sha qator hech qachon chizilmagan edi.
  Future<_Olchov> olcha(
    WidgetTester t, {
    required Size ekran,
    required double yozuv,
    required String til,
    required String mavzu,
  }) async {
    L.code = til;
    await AppTheme.set(mavzu);
    t.view.physicalSize = Size(ekran.width * 3, ekran.height * 3);
    t.view.devicePixelRatio = 3.0;
    // Haqiqiy iPhone chetlari: notch va home indicator.
    t.view.padding = const FakeViewPadding(top: 141, bottom: 102);
    t.platformDispatcher.textScaleFactorTestValue = yozuv;
    addTearDown(t.view.resetPhysicalSize);
    addTearDown(t.view.resetDevicePixelRatio);
    addTearDown(t.view.resetPadding);
    addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);

    await signInAs(be);
    return be.run(() async {
      // ⚠️  Toshish bo'lsa Flutter `FlutterError` otadi va test O'ZI yiqiladi.
      await t.pumpWidget(testApp(const ProductDetailScreen(
          productId: 'p1', initialName: 'Qatiq')));
      await t.pumpAndSettle();

      final xato = <String>{};
      final korilgan = <String>{};
      void yoz() {
        xato.addAll(_chiqibKetganMatnlar(t, ekran));
        korilgan.addAll(t
            .widgetList<Text>(find.byType(Text))
            .map((w) => w.data ?? '')
            .where((x) => x.isNotEmpty));
      }

      yoz();
      final sc = find.byType(Scrollable).first;
      var oldingi = -1.0;
      // 60 qadam — eng kichik ekranda ham (320x568, 3.0x yozuv) ro'yxat
      // oxiriga yetishga yetarli; holat o'zgarmasa oldin to'xtaydi.
      for (var i = 0; i < 60; i++) {
        final pos = t.state<ScrollableState>(sc).position;
        if (pos.pixels == oldingi) break;
        oldingi = pos.pixels;
        await t.drag(sc, Offset(0, -ekran.height / 3));
        await t.pumpAndSettle();
        yoz();
      }
      return _Olchov(xato.toList(), korilgan);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 1. KENGLIK x YOZUV O'LCHAMI x ORIENTATSIYA
  // ═══════════════════════════════════════════════════════════════════════════

  // ⚠️  `Map<double, ...>` const bo'la olmaydi (`double` da primitive equality
  //     yo'q) — ro'yxat ishlatiladi.
  const tikOlchamlar = <Size>[
    Size(320, 568), // iPhone SE 1 — eng kichik qo'llanadigan iOS qurilma
    Size(375, 667), // iPhone SE 2/3, 8
    Size(390, 844), // iPhone 12-16 (pilot telefonlar)
    Size(430, 932), // iPhone 15/16 Pro Max
  ];
  const yozuvlar = [1.0, 1.5, 2.0, 3.0];

  for (final tik in tikOlchamlar) {
    for (final yozuv in yozuvlar) {
      for (final yotiq in const [false, true]) {
        final ekran = yotiq ? Size(tik.height, tik.width) : tik;
        testWidgets(
            '${ekran.width.toInt()}x${ekran.height.toInt()} '
            '@${yozuv}x ${yotiq ? "yotiq" : "tik"}', (t) async {
          final o = await olcha(t,
              ekran: ekran, yozuv: yozuv, til: 'uz', mavzu: 'tungi');
          // IJOBIY NAZORAT: ro'yxat oxirigacha aylantirilgan va eng siqilgan
          // bo'lim (`_move` qatorlari) HAQIQATAN o'lchangan.
          expect(o.korilgan, contains('So‘nggi harakatlar'),
              reason: 'harakatlar bo`limiga yetib borilmadi — o`lchov '
                  'ekranning faqat yuqori qismini qamragan');
          expect(o.xato, isEmpty,
              reason: 'MATN EKRANDAN CHIQIB KETDI (${o.xato.length} ta):\n'
                  '${o.xato.join("\n")}');
        });
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 2. TIL x YOZUV — eng tor kenglikda
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  Ruscha tarjimalar ENG UZUN (`lock_visibility_test` da ham shu qayd
  //     etilgan), ya'ni til almashuvi mustaqil xavf.

  for (final til in const ['uz', 'ru', 'ky']) {
    for (final yozuv in const [1.0, 2.0, 3.0]) {
      testWidgets('til=$til @${yozuv}x 320px', (t) async {
        final o = await olcha(t,
            ekran: const Size(320, 568), yozuv: yozuv, til: til, mavzu: 'tungi');
        expect(o.xato, isEmpty,
            reason: 'MATN EKRANDAN CHIQIB KETDI ($til, ${yozuv}x):\n'
                '${o.xato.join("\n")}');
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 3. TO'Q VA OCH MAVZU
  // ═══════════════════════════════════════════════════════════════════════════

  for (final mavzu in const ['tungi', 'oq', 'kosmos', 'yalpiz']) {
    testWidgets('mavzu=$mavzu 320px @2x', (t) async {
      final o = await olcha(t,
          ekran: const Size(320, 568), yozuv: 2.0, til: 'ru', mavzu: mavzu);
      expect(o.xato, isEmpty, reason: '$mavzu:\n${o.xato.join("\n")}');
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 4. iPad MOSLIGI
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  `Info.plist` iPad'ni ham qo'llaydi (universal ilova), ya'ni App Review
  //     uni iPad'da ham ochadi. Keng ekranda layout buzilmasligi SHART.

  for (final ekran in const [Size(768, 1024), Size(1024, 768), Size(1366, 1024)]) {
    testWidgets('iPad ${ekran.width.toInt()}x${ekran.height.toInt()} @2x', (t) async {
      final o = await olcha(t,
          ekran: ekran, yozuv: 2.0, til: 'ru', mavzu: 'tungi');
      expect(o.xato, isEmpty, reason: 'iPad:\n${o.xato.join("\n")}');
    });
  }
}
