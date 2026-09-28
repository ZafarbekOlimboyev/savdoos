// Skaner diagnostika paneli QACHON ko'rinadi.
//
// ⚠️  NEGA BU TEST BOR. Panel ilgari FAQAT `kScanDiagnostics` (kompilyatsiya
//     bayrog'i) bilan gate qilingandi; URL tekshiruvi esa faqat login'siz
//     marshrutda turardi. Natijada nomzod build'ida panel oddiy skaner
//     ekranida, TOZA URL bilan ham chiqib turdi — do'kon egasi buni real
//     iPhone'da ko'rdi. Endi ikki shart ham kerak va quyidagi holatlar
//     mixlangan.
//
// Shartnoma: standart holat — O'CHIQ. Yoqadigan YAGONA narsa — joriy URL dagi
// `?diag=scan`. Hech qanday saqlangan holat, muhit qiymati yoki service worker
// uni yoqa olmaydi.
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';

import 'support/support.dart';

void main() {
  group('URL qoidasi — sof funksiya, hamma holat', () {
    // Foydalanuvchi bergan ro'yxat, so'zma-so'z.
    const yoqadi = <String>[
      'https://app.example/?diag=scan',
      'https://app.example/index.html?diag=scan',
      'https://app.example/?x=1&diag=scan',        // boshqa kalitlar xalaqit bermaydi
      'https://app.example/#/?diag=scan',          // Flutter web xesh-marshruti
    ];
    const ochiq = <String>[
      'https://app.example/',                      // TOZA URL
      'https://app.example/?diag=0',
      'https://app.example/?diag=false',
      'https://app.example/?diag=',
      'https://app.example/?foo=scan',
      'https://app.example/?diag=scanner',         // qiymat AYNAN `scan` bo'lsin
      'https://app.example/?diag=SCAN',            // katta harf — yo'q
      'https://app.example/scan',                  // yo'lda bo'lsa ham emas
      'https://app.example/?notdiag=scan',
    ];

    for (final u in yoqadi) {
      test('YOQADI: $u', () {
        expect(diagnosticsRequestedIn(Uri.parse(u)), isTrue);
        expect(scanDiagnosticsFor(buildAllows: true, url: Uri.parse(u)), isTrue);
      });
    }
    for (final u in ochiq) {
      test("O'CHIQ: $u", () {
        expect(diagnosticsRequestedIn(Uri.parse(u)), isFalse);
        expect(scanDiagnosticsFor(buildAllows: true, url: Uri.parse(u)), isFalse);
      });
    }

    test('build imkoniyati bo‘lmasa URL ham yoqa OLMAYDI', () {
      for (final u in yoqadi) {
        expect(scanDiagnosticsFor(buildAllows: false, url: Uri.parse(u)), isFalse,
            reason: 'production build’ida $u panelni yoqmasligi kerak');
      }
    });

    test('oddiy production build’ida panel har qanday URL’da o‘chiq', () {
      // `kScanDiagnostics` bu yerda (dart-define’siz) `false` — ya'ni
      // sinovdagi holat production build’i bilan bir xil.
      expect(kScanDiagnostics, isFalse);
      for (final u in [...yoqadi, ...ochiq]) {
        scanDiagUrlSource = () => Uri.parse(u);
        expect(scanDiagnosticsOn(), isFalse);
      }
      scanDiagUrlSource = () => Uri.base;
    });
  });

  group('skaner ekrani — panel va uning taymeri', () {
    late FakeScanner scanner;

    setUp(() async {
      await resetCore();
      signIn();
      scanner = FakeScanner();
      Scanner.instance = scanner;
    });
    tearDown(() => scanDiagUrlSource = () => Uri.base);

    // ⚠️  BU AYNAN XATOLIK HOLATI: nomzod build'i (build imkoniyati BOR) + TOZA
    //     URL. Ilgari panel shu holatda chiqib turardi. Build bayrog'i sinovda
    //     `false` bo'lgani uchun imkoniyat ATAYLAB majburlanadi — aks holda
    //     test hech narsani isbotlamasdi.
    testWidgets('nomzod build’i + TOZA URL: panel QURILMAYDI, joy ham egallamaydi', (t) async {
      await pumpAt390(t, BarcodeScanScreen.lookup(
        diagnosticsGate: () => scanDiagnosticsFor(
            buildAllows: true, url: Uri.parse('https://app.example/')),
      ));
      await t.pump();
      expect(find.byKey(const Key('scan-diagnostics')), findsNothing);
      expect(find.textContaining('SCAN DIAG'), findsNothing);
      // 700 ms li yangilash taymeri PANEL ichida yashaydi: panel yo'q bo'lsa
      // taymer ham yo'q. Vaqtni surib, hech narsa paydo bo'lmasligini ko'ramiz.
      await t.pump(const Duration(seconds: 3));
      expect(find.byKey(const Key('scan-diagnostics')), findsNothing);
      expect(scanner.sessions.single.diagnosticsReads, 0,
          reason: 'panel yo‘q bo‘lsa diagnostics() umuman o‘qilmasligi kerak');
    });

    testWidgets('?diag=scan: panel QURILADI va yangilanib turadi', (t) async {
      // Bu yerda build imkoniyatini ATAYLAB majburlaymiz: `kScanDiagnostics`
      // sinovda `false`, lekin biz tekshirayotgan narsa — ekranning gate’ga
      // bo‘ysunishi, bayroqning o‘zi emas.
      await pumpAt390(t, BarcodeScanScreen.lookup(
        diagnosticsGate: () => scanDiagnosticsFor(
            buildAllows: true, url: Uri.parse('https://app.example/?diag=scan')),
      ));
      await t.pump();
      expect(find.byKey(const Key('scan-diagnostics')), findsOneWidget);
      final int oldingi = scanner.sessions.single.diagnosticsReads;
      expect(oldingi, greaterThan(0));
      await t.pump(const Duration(milliseconds: 1500));
      expect(scanner.sessions.single.diagnosticsReads, greaterThan(oldingi),
          reason: 'panel davriy yangilanmayapti');
      // Taymerni sinov oxiriga qoldirmaymiz.
      await t.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('gate yolg‘on bo‘lsa — hech narsa, hatto bo‘sh joy ham yo‘q', (t) async {
      await pumpAt390(t, BarcodeScanScreen.lookup(diagnosticsGate: () => false));
      await t.pump();
      expect(find.byKey(const Key('scan-diagnostics')), findsNothing);
      unawaited(Future<void>.value());
    });
  });

  // Yuqoridagi vidjet testlari gate’ni TIKUV orqali beradi, chunki
  // `kScanDiagnostics` sinov yurishida (dart-define’siz) doim `false` — ya'ni
  // ekran yana faqat bayroqqa qaytarilsa, daraxtdan buni sezib bo‘lmaydi.
  // Shu bois ekranning O‘ZI manba darajasida qo‘riqlanadi.
  group('ekran gate’ni CHETLAB O‘TMAYDI (manba qo‘riqchisi)', () {
    final String src =
        File('lib/screens/barcode_scan_screen.dart').readAsStringSync();

    test('panel faqat bayroqqa qarab qurilmaydi', () {
      expect(src.contains('if (kScanDiagnostics)'), isFalse,
          reason: 'panel yana faqat kompilyatsiya bayrog‘iga bog‘lanib qolgan');
    });

    test('panel gate orqali quriladi', () {
      expect(src, contains('widget.diagnosticsGate ?? scanDiagnosticsOn'));
    });

    test('URL qoidasi bitta joyda — ekran o‘zi URL o‘qimaydi', () {
      expect(src.contains('Uri.base'), isFalse,
          reason: 'URL qoidasi `platform/scanner.dart` da, nusxa ko‘paytirilmasin');
    });

    test('diagnostika holati SAQLANMAYDI (localStorage/sessionStorage/prefs yo‘q)', () {
      // Izohlarda bu nomlar ATAYLAB tilga olinadi (nima TAQIQLANGANI yozilgan),
      // shu bois tekshiruvdan oldin izohlar olib tashlanadi — aks holda
      // hujjatning o‘zi testni yiqitardi.
      final String kod = File('lib/platform/scanner.dart')
          .readAsStringSync()
          .replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '')
          .split('\n')
          .map((String l) {
            final int i = l.indexOf('//');
            return i >= 0 ? l.substring(0, i) : l;
          })
          .join('\n');
      for (final String bad in <String>[
        'localStorage', 'sessionStorage', 'SharedPreferences', 'SecretStore', 'LocalCache',
      ]) {
        expect(kod.contains(bad), isFalse, reason: '$bad diagnostika gate’iga aralashmasin');
      }
    });
  });
}
