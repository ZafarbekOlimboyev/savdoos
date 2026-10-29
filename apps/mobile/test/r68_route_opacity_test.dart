// R6.8 UI — TO'LIQ EKRAN ROUTE'LARI SHAFFOF: O'TISH PAYTIDA ESKI SAHIFA
// YANGISINING ICHIDAN KO'RINADI (egasining iPhone suratidagi nuqson).
//
// ⚠️  NEGA BU NUQSON BOR. `theme.dart` da fon ataylab bitta joyda chiziladi:
//
//       scaffoldBackgroundColor: Colors.transparent   // theme.dart:186
//       canvasColor:             Colors.transparent   // theme.dart:194
//
//     va `ThemedBackground` `MaterialApp.builder` ichida, ya'ni Navigator'dan
//     TASHQARIDA turadi (`main.dart:142`). Natijada fon BUTUN ILOVA ortida BIR
//     MARTA chiziladi va har bir `MaterialPageRoute` ning o'z sahifasi
//     SHAFFOF bo'lib qoladi.
//
//     Tinch holatda bu ko'rinmaydi: `TransitionRoute._handleStatusChanged`
//     animatsiya TUGAGANDA `overlayEntries.first.opaque = opaque` qiladi va
//     ostki route'lar umuman chizilmaydi. LEKIN `forward`/`reverse` paytida
//     AYNI joyda `opaque = false` qo'yiladi — ya'ni o'tish davomida ostki
//     route CHIZILADI va shaffof yangi sahifa ortidan O'QILADI.
//
//     Oqibat ikki joyda ko'rinadi:
//       * push animatsiyasi (300 ms) — tez, lekin sekin qurilmada seziladi;
//       * iOS ORQAGA SURISH imo-ishorasi — davomiyligi FOYDALANUVCHI
//         barmog'iga bog'liq, ya'ni cheksiz uzun bo'lishi mumkin. Egasining
//         suratidagi holat aynan shunga to'g'ri keladi.
//
//     Shu bois bu test widget daraxtini emas, HAQIQIY PIKSELLARNI o'lchaydi va
//     `pumpAndSettle` bilan cheklanmaydi — animatsiyaning O'RTASI majburiy.
@TestOn('vm')
library;

import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/theme.dart';

import 'support/support.dart';

/// Mavzularda uchramaydigan rang — «eski sahifa» belgisi. Barcha mavzu fonlari
/// (`theme.dart:37-95`) to'q ko'k/yashil yoki och kulrang: hech birida qizil VA
/// ko'k bir vaqtda baland, yashil esa past emas.
const Color kOldPageSentinel = Color(0xFFFF00FF);

/// Belgi rangini TUS bo'yicha aniqlash — aniq RGB tengligi emas.
///
/// ⚠️  NEGA TUS. Belgi rangi ustiga ikki xil qatlam tushishi mumkin:
///     Cupertino o'tishining chap qirra soyasi
///     (`_CupertinoEdgeShadowDecoration`) va dialog/varaq PARDASI
///     (`Colors.black54`). Ikkisi ham siyohrangni xiralashtiradi: masalan
///     `FF00FF` parda ostida ≈ `750075` bo'ladi. Qat'iy `r > 200` shartida
///     test «ko'rinmayapti» deb YOLG'ON yashil berardi — aynan shu holat
///     birinchi yurishda dialog testini noto'g'ri yiqitdi.
///
/// ⚠️  XATO TOPISH XAVFI YO'Q: `theme.dart` dagi BARCHA ranglar (fonlar,
///     kartalar, chegara, aksent va aurora/yulduz nurlari `6366F1`, `6D5DD3`,
///     `8B5CF6`, `14B8A6`) bu shartga tushmaydi — mashina bilan tekshirilgan.
bool _isSentinel(int r, int g, int b, int a) =>
    a == 255 &&
    r >= 60 &&
    b >= 60 &&
    g * 3 < r &&
    g * 3 < b &&
    (r - b).abs() <= (r > b ? r : b) * 0.35;

const Key kNewPageKey = Key('r68-new-page');
const Key kOldPageKey = Key('r68-old-page');
final GlobalKey _shotKey = GlobalKey();

/// Ekranning haqiqiy piksellari. `toImage()` standart `pixelRatio: 1.0` bilan
/// MANTIQIY o'lchamda rasm beradi, ya'ni `tester.getRect` koordinatalari rasm
/// piksellariga 1:1 to'g'ri keladi.
class _Shot {
  _Shot(this.w, this.h, this.bytes);
  final int w;
  final int h;
  final Uint8List bytes;

  /// [rect] ichidagi «eski sahifa» piksellari soni.
  int sentinelsIn(Rect rect) {
    final x0 = rect.left.ceil().clamp(0, w);
    final x1 = rect.right.floor().clamp(0, w);
    final y0 = rect.top.ceil().clamp(0, h);
    final y1 = rect.bottom.floor().clamp(0, h);
    var n = 0;
    for (var y = y0; y < y1; y++) {
      for (var x = x0; x < x1; x++) {
        final i = (y * w + x) * 4;
        if (_isSentinel(bytes[i], bytes[i + 1], bytes[i + 2], bytes[i + 3])) n++;
      }
    }
    return n;
  }

  int get total => w * h;
}

Future<_Shot> _shoot(WidgetTester t) async {
  final boundary = _shotKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  late final ui.Image img;
  await t.runAsync(() async => img = await boundary.toImage());
  final data =
      await t.runAsync(() async => img.toByteData(format: ui.ImageByteFormat.rawRgba));
  return _Shot(img.width, img.height, data!.buffer.asUint8List());
}

/// Yangi sahifaning EKRANDA KO'RINADIGAN qismi, chekkalardan ichkariga surilgan.
///
/// ⚠️  Chekka qoldirish ATAYLAB: o'tish boshida yangi sahifa ekranning o'ng
///     qirrasida bo'lib, uning qirra soyasi va anti-aliasing pikselleri
///     aralash rang beradi. Spetsifikatsiya ham shuni aytadi: «yangi sahifa
///     hali qoplab olmagan chekka sohalar tabiiy». Biz FAQAT yangi sahifa
///     ALLAQACHON egallagan ichki sohani o'lchaymiz.
Rect _probeOf(WidgetTester t) {
  final r = t.getRect(find.byKey(kNewPageKey));
  final screen = Rect.fromLTWH(0, 0, kPhoneSize.width, kPhoneSize.height);
  return r.intersect(screen).deflate(12);
}

/// Eski sahifa: butun maydonni belgi rangi bilan bo'yaydi.
class _OldPage extends StatelessWidget {
  const _OldPage({required this.onOpen});
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) => Scaffold(
        key: kOldPageKey,
        body: ColoredBox(
          color: kOldPageSentinel,
          child: Center(
            child: ElevatedButton(
              onPressed: onOpen,
              child: const Text('OCHISH'),
            ),
          ),
        ),
      );
}

/// Yangi sahifa: `product_detail_screen.dart` bilan AYNI tuzilish — ustunli
/// `Scaffold` + `AppBar` + ro'yxat. Hech qanday o'z foni YO'Q, ya'ni mavzudagi
/// `scaffoldBackgroundColor: transparent` qanday bo'lsa shunday ishlaydi.
class _NewPage extends StatelessWidget {
  const _NewPage();

  @override
  Widget build(BuildContext context) => Scaffold(
        key: kNewPageKey,
        appBar: AppBar(title: const Text('Mahsulot')),
        body: ListView(
          children: [for (var i = 0; i < 20; i++) ListTile(title: Text('qator $i'))],
        ),
      );
}

Widget _host() => Builder(
      builder: (context) => _OldPage(
        onOpen: () => Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => const _NewPage()),
        ),
      ),
    );

void main() {
  setUp(resetCore);
  // ⚠️  `AppTheme.current` GLOBAL: `resetCore` uni tiklamaydi. Tiklanmasa
  //     matritsaning oxirgi mavzusi keyingi testlarga oqib ketadi.
  tearDown(() => AppTheme.set('tungi'));

  // ⚠️  Platformani `debugDefaultTargetPlatformOverride` bilan QO'LDA qo'yish
  //     yaramaydi: `flutter_test` har test oxirida
  //     `debugAssertAllFoundationVarsUnset` ni tekshiradi va u `tearDown` dan
  //     OLDIN ishlaydi. `TargetPlatformVariant` o'rnatish va tiklashni
  //     tekshiruvning TO'G'RI tomonida bajaradi.
  //
  //     Egasining qurilmasi iPhone: o'tish `CupertinoPageTransitionsBuilder`
  //     (o'ngdan suriladi, YARIM SHAFFOF EMAS) — ya'ni bu platformada
  //     o'tishning HAR bosqichida yangi sahifa ortidan hech narsa
  //     ko'rinmasligi SHART.
  final iOS = TargetPlatformVariant.only(TargetPlatform.iOS);

  Future<void> pumpApp(WidgetTester t) async {
    // ⚠️  `RepaintBoundary` BUTUN ilovadan yuqorida — `lock_visibility_test`
    //     dagi kabi: `ThemedBackground` va Navigator ikkisi ham ICHIDA qolishi
    //     kerak, aks holda biz ekranni emas, daraxtning bir qismini o'lchaymiz.
    setPhoneViewport(t);
    await t.pumpWidget(RepaintBoundary(key: _shotKey, child: testApp(_host())));
    await t.pumpAndSettle();
  }

  /// Bosqichni o'lchab, topilgan belgi piksellari sonini qaytaradi.
  /// `-1` — o'lchov maydoni hali juda kichik (yangi sahifa ekranga kirmagan).
  Future<int> measure(WidgetTester t, String bosqich) async {
    final probe = _probeOf(t);
    if (probe.width < 40 || probe.height < 40) return -1;
    final shot = await _shoot(t);
    final n = shot.sentinelsIn(probe);
    debugPrint('  [$bosqich] maydon=${probe.width.toInt()}x${probe.height.toInt()} '
        'belgi_piksel=$n');
    return n;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 1. PUSH ANIMATSIYASI — har bosqichda
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('nazorat: eski sahifa O`ZI belgi rangida (test o`zini sozlay oldi)',
      (t) async {
    await pumpApp(t);
    final shot = await _shoot(t);
    final hammasi = Rect.fromLTWH(0, 0, kPhoneSize.width, kPhoneSize.height);
    expect(shot.sentinelsIn(hammasi), greaterThan(shot.total ~/ 2),
        reason: 'nazorat yiqildi — eski sahifa belgi rangida chizilmagan');
  }, variant: iOS);

  testWidgets('PUSH: o`tishning HAR bosqichida eski sahifa yangisining ichida KO`RINMAYDI',
      (t) async {
    await pumpApp(t);
    await t.tap(find.text('OCHISH'));

    // Route animatsiyasini boshlaymiz (kadr jadvalga tushadi).
    await t.pump();

    final natijalar = <String, int>{};
    // ⚠️  Bosqichlar MUTLAQ vaqtda: `MaterialPageRoute` o'tishi 300 ms.
    const bosqichlar = <String, int>{
      'boshlanish (1 ms)': 1,
      '60-100 ms (80 ms)': 79,
      '120-180 ms (150 ms)': 70,
    };
    for (final e in bosqichlar.entries) {
      await t.pump(Duration(milliseconds: e.value));
      natijalar[e.key] = await measure(t, e.key);
    }
    await t.pumpAndSettle();
    natijalar['pumpAndSettle'] = await measure(t, 'pumpAndSettle');

    // Kamida bitta bosqich HAQIQATAN o'lchandi — aks holda test hech narsa
    // tekshirmagan bo'lardi va «yashil» yolg'on bo'lardi.
    expect(natijalar.values.where((v) => v >= 0), isNotEmpty,
        reason: 'hech bir bosqichda o`lchov maydoni yetarli bo`lmadi');

    final buzilgan = natijalar.entries.where((e) => e.value > 0).toList();
    expect(buzilgan, isEmpty,
        reason: 'ESKI SAHIFA YANGISINING ICHIDAN KO`RINADI: '
            '${buzilgan.map((e) => "${e.key} -> ${e.value} piksel").join(", ")}. '
            'Sabab: `scaffoldBackgroundColor: transparent` + `ThemedBackground` '
            'Navigator TASHQARISIDA, ya`ni route`ning o`z fonsiz sahifasi shaffof.');
  }, variant: iOS);

  // ═══════════════════════════════════════════════════════════════════════════
  // 2. ORQAGA QAYTISH — eng uzun oyna (iOS surish imo-ishorasi)
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('POP: orqaga qaytish animatsiyasida ham ichidan KO`RINMAYDI', (t) async {
    await pumpApp(t);
    await t.tap(find.text('OCHISH'));
    await t.pumpAndSettle();
    expect(find.byKey(kNewPageKey), findsOneWidget, reason: 'yangi sahifa ochilmadi');

    // Orqaga: `reverse` holatida `overlayEntries.first.opaque` QAYTA `false`
    // bo'ladi — ya'ni ostki route yana chiziladi.
    // ⚠️  `byType(Navigator)` ishlamaydi: qulf qatlamining O'Z Navigator'i bor
    //     (`app_lock.dart:209`). `testApp` ildiz navigatorini KALIT bilan beradi.
    rootNavKey.currentState!.pop();
    await t.pump();

    final natijalar = <String, int>{};
    for (final ms in const [1, 40, 80]) {
      await t.pump(Duration(milliseconds: ms));
      natijalar['pop +${ms}ms'] = await measure(t, 'pop +${ms}ms');
    }
    await t.pumpAndSettle();

    final buzilgan = natijalar.entries.where((e) => e.value > 0).toList();
    expect(buzilgan, isEmpty,
        reason: 'ORQAGA QAYTISHDA eski sahifa yangisining ichidan ko`rinadi: '
            '${buzilgan.map((e) => "${e.key} -> ${e.value} piksel").join(", ")}. '
            'Bu oyna foydalanuvchi barmog`iga bog`liq va cheksiz uzun bo`lishi mumkin.');
  }, variant: iOS);

  // ═══════════════════════════════════════════════════════════════════════════
  // 3. TINCH HOLAT — nuqsonning chegarasini aniq qayd etish
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('TINCH HOLAT: o`tish tugagach ostki route umuman chizilmaydi', (t) async {
    await pumpApp(t);
    await t.tap(find.text('OCHISH'));
    await t.pumpAndSettle();

    // ⚠️  Bu tasdiq TUZATISHDAN OLDIN HAM yashil bo'lishi kutiladi:
    //     `TransitionRoute._handleStatusChanged` animatsiya tugaganda
    //     `opaque = true` qiladi. Shu bois nuqson «doim ko'rinadi» emas,
    //     balki «o'tish davomida ko'rinadi» — hisobotda shu aniqlik muhim.
    final n = await measure(t, 'tinch holat');
    expect(n, 0,
        reason: 'tinch holatda ham ko`rinadi — bu BOSHQA, OG`IRROQ nuqson: '
            'route `opaque` bo`lmagan yoki Overlay qatlamlari buzilgan');
  }, variant: iOS);

  // ═══════════════════════════════════════════════════════════════════════════
  // 4. MAVZU MATRITSASI — Flat / Gradient / Aurora / Yulduzlar, to'q va och
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  Spetsifikatsiya aynan shuni talab qiladi: «Barcha Scaffold fonlarini
  //     ko'r-ko'rona bitta oq rangga o'tkazma». Shu bois tuzatish MAVZU fonini
  //     sahifaga ko'chiradi — demak HAR BIR mavzu alohida o'lchanishi kerak:
  //     gradient va aurora/yulduzlar `Stack` quradi, tekis fon esa `ColoredBox`.

  group('mavzu matritsasi: har bir fon turi o`tish paytida OPAQUE', () {
    for (final t in kThemes) {
      testWidgets('${t.id} (${t.dark ? "to`q" : "och"}, ${t.bgKind.name})', (tester) async {
        await AppTheme.set(t.id);
        await pumpApp(tester);
        await tester.tap(find.text('OCHISH'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 80));

        final n = await measure(tester, '${t.id} @80ms');
        expect(n, 0,
            reason: '«${t.id}» mavzusida (${t.bgKind.name}) o`tish paytida eski '
                'sahifa yangisining ichidan ko`rinadi — $n piksel');
        await tester.pumpAndSettle();
      }, variant: iOS);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 5. TUZILISH — tuzatish MEXANIZMI o'z joyida
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('yangi sahifaning IKKI `ThemedBackground` ajdodi bor (ildiz + route)',
      (t) async {
    await pumpApp(t);
    await t.tap(find.text('OCHISH'));
    await t.pumpAndSettle();

    // ⚠️  Tuzatishdan OLDIN bu BITTA edi — faqat `main.dart` dagi ildiz foni.
    //     Ikkinchisi `_OpaquePageTransitionsTheme` qo'shgan route foni.
    //     Bu tasdiq mexanizmni qadab qo'yadi: kimdir `pageTransitionsTheme` ni
    //     olib tashlasa, piksel testlari sekin, bu esa darhol yiqiladi.
    expect(
      find.ancestor(
          of: find.byKey(kNewPageKey), matching: find.byType(ThemedBackground)),
      findsNWidgets(2),
      reason: 'route darajasidagi opaque yuza yo`q — `pageTransitionsTheme` '
          'olib tashlangan yoki almashtirilgan',
    );
  }, variant: iOS);

  // ═══════════════════════════════════════════════════════════════════════════
  // 6. ANDROID — platforma xulqi o'zgarmaganini tekshirish
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  Android'da o'tish `ZoomPageTransitionsBuilder` (predictive back
  //     mavjud bo'lmaganda) — yangi sahifa ATAYLAB yarim shaffof holda
  //     kirib keladi. Shu bois o'rtada eski sahifaning ko'rinishi NUQSON EMAS.
  //     O'lchanadigan narsa boshqa: (a) o'tish TUGAGANDA toza, (b) mexanizm
  //     Android'da ham o'rnatilgan.

  testWidgets('Android: o`tish tugagach toza va mexanizm o`rnatilgan', (t) async {
    await pumpApp(t);
    await t.tap(find.text('OCHISH'));
    await t.pumpAndSettle();

    expect(await measure(t, 'android settle'), 0);
    expect(
      find.ancestor(
          of: find.byKey(kNewPageKey), matching: find.byType(ThemedBackground)),
      findsNWidgets(2),
    );
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  // ═══════════════════════════════════════════════════════════════════════════
  // 7. SHAFFOF OYNALAR BUZILMAGAN — tuzatishning chegarasi
  // ═══════════════════════════════════════════════════════════════════════════
  //
  // ⚠️  Bu guruh ATAYLAB teskari tomonga qaraydi. Agar tuzatish «hamma narsani
  //     opaque qil» bo'lsa, dialog va bottom sheet ortidagi ekran ham
  //     yo'qolardi — bu Material dizayni va ilovaning o'z ko'rinishini buzardi.
  //     Spetsifikatsiya: «Real transparent dialoglar, bottom sheet'lar yoki
  //     dekorativ mavzular buzilmasin».

  group('shaffof oynalar SAQLANADI', () {
    testWidgets('showDialog: ortidagi ekran KO`RINADI', (t) async {
      await pumpApp(t);
      final ctx = rootNavKey.currentContext!;
      showDialog<void>(
          context: ctx,
          builder: (_) => const AlertDialog(content: Text('oyna')));
      await t.pumpAndSettle();
      expect(find.text('oyna'), findsOneWidget, reason: 'dialog ochilmadi');

      final shot = await _shoot(t);
      final hammasi = Rect.fromLTWH(0, 0, kPhoneSize.width, kPhoneSize.height);
      expect(shot.sentinelsIn(hammasi), greaterThan(0),
          reason: 'DIALOG ORTIDAGI EKRAN YO`QOLDI — tuzatish shaffof oynalarni '
              'ham opaque qilib qo`ygan');
    }, variant: iOS);

    testWidgets('showModalBottomSheet: ortidagi ekran KO`RINADI', (t) async {
      await pumpApp(t);
      final ctx = rootNavKey.currentContext!;
      showModalBottomSheet<void>(
          context: ctx,
          builder: (_) => const SizedBox(height: 120, child: Text('varaq')));
      await t.pumpAndSettle();
      expect(find.text('varaq'), findsOneWidget, reason: 'varaq ochilmadi');

      final shot = await _shoot(t);
      final hammasi = Rect.fromLTWH(0, 0, kPhoneSize.width, kPhoneSize.height);
      expect(shot.sentinelsIn(hammasi), greaterThan(0),
          reason: 'VARAQ ORTIDAGI EKRAN YO`QOLDI');
    }, variant: iOS);
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 8. MAVZU ALMASHUVI SAHIFA OCHIQ PAYTDA
  // ═══════════════════════════════════════════════════════════════════════════

  testWidgets('sahifa ochiq paytda mavzu almashsa, route foni HAM yangilanadi',
      (t) async {
    // ⚠️  BU TEST `testApp()` NI ISHLATMAYDI. Sabab: `test/support/pump.dart`
    //     dagi `testApp` oddiy `MaterialApp` quradi va `AppTheme.version` ni
    //     KUZATMAYDI, ishlab chiqarishdagi `SavdoApp` esa butun `MaterialApp`
    //     ni `AnimatedBuilder(animation: Listenable.merge([L.version,
    //     AppTheme.version]))` ichiga oladi (`main.dart:107-109`). Harness
    //     bilan o'lchasak, javob «mavzu yangilanmadi» bo'lib chiqardi — lekin
    //     bu harness cheklovi, ilovaning xulqi emas.
    //
    //     Shu bois bu yerda ishlab chiqarish TUZILISHI takrorlanadi va
    //     o'lchanadigan savol aniq bo'ladi: ilova qayta qurilganda ROUTE
    //     darajasidagi fon ham yangi mavzuni oladimi? (`ThemedBackground`
    //     `AppTheme.current` ni GLOBAL o'qiydi, InheritedWidget emas.)
    await AppTheme.set('tungi');
    setPhoneViewport(t);
    rootNavKey = GlobalKey<NavigatorState>();
    installLockGuards();
    await t.pumpWidget(RepaintBoundary(
      key: _shotKey,
      child: AnimatedBuilder(
        animation: AppTheme.version,
        builder: (context, _) => MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: buildTheme(),
          navigatorKey: rootNavKey,
          builder: (context, child) => ThemedBackground(
            child: AppLockBarrier(child: child ?? const SizedBox.shrink()),
          ),
          home: _host(),
        ),
      ),
    ));
    await t.pumpAndSettle();

    await t.tap(find.text('OCHISH'));
    await t.pumpAndSettle();

    Color? routeFoni() {
      // Route darajasidagi fon — yangi sahifaning ENG YAQIN `ThemedBackground`
      // ajdodi. Ildizdagisi ham mos keladi, shuning uchun ro'yxatdan
      // OXIRGISINI (daraxt bo'yicha eng chuquri) olamiz.
      final fonlar = find.ancestor(
          of: find.byKey(kNewPageKey), matching: find.byType(ThemedBackground));
      final eng = t.elementList(fonlar).last;
      final box = find.descendant(
          of: find.byElementPredicate((e) => e == eng),
          matching: find.byType(ColoredBox));
      return t.widgetList<ColoredBox>(box).first.color;
    }

    expect(routeFoni(), kThemes.firstWhere((x) => x.id == 'tungi').bg,
        reason: 'nazorat: route foni boshlang`ich mavzuda emas');

    await AppTheme.set('oq'); // to'q -> och
    await t.pumpAndSettle();

    expect(routeFoni(), kThemes.firstWhere((x) => x.id == 'oq').bg,
        reason: 'mavzu almashgach ROUTE foni eski rangda qoldi — sahifa '
            'ilovaning qolgan qismi bilan MOS KELMAYDI');
  }, variant: iOS);
}
