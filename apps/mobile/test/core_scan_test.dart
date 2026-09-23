import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/scan.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

Map<String, dynamic> product(String id, String name, {bool weighted = false, bool active = true, String? plu}) => {
      'id': id,
      'name': name,
      'unit_code': weighted ? 'kg' : 'dona',
      'is_active': active,
      'is_weighted': weighted,
      'track_lots': false,
      'track_expiry': false,
      'plu_code': plu,
      'barcodes': ['04780001'],
      'stock': 12.5,
      'base_sell_price': 15000,
    };

void main() {
  group('ScanLookup parsing', () {
    test('barcode keeps the code as a string (leading zeros)', () {
      final l = ScanLookup.fromJson({'code': '04780001', 'kind': 'barcode', 'product': product('p1', 'Sut'), 'candidates': const []});
      expect(l.kind, ScanKind.barcode);
      expect(l.code, '04780001');
      expect(l.product!.barcodes, ['04780001']);
      expect(l.product!.stockMilli, 12500);
      expect(l.product!.sellPriceCents, 1500000);
    });

    test('scale: qty string -> milli', () {
      final l = ScanLookup.fromJson({
        'code': '2000123012345',
        'kind': 'scale',
        'product': product('p2', 'Go‘sht', weighted: true, plu: '123'),
        'candidates': const [],
        'scale': const {'plu': 123, 'grams': 1234, 'qty': '1.234'},
      });
      expect(l.kind, ScanKind.scale);
      expect(l.scale!.qtyMilli, 1234);
      expect(ScanResult(l, l.product).qtyMilli, 1234);
    });

    test('ambiguous / none / unknown kind', () {
      final a = ScanLookup.fromJson({
        'code': '2000123012345',
        'kind': 'ambiguous',
        'product': null,
        'candidates': [product('a', 'A', weighted: true), product('b', 'B', weighted: true)],
        'scale': const {'plu': 123, 'grams': 500, 'qty': '0.500'},
      });
      expect(a.candidates.map((p) => p.id), ['a', 'b']);
      expect(ScanLookup.fromJson(const {'code': '1', 'kind': 'none'}).kind, ScanKind.none);
      expect(ScanLookup.fromJson(const {'code': '1', 'kind': 'weird'}).kind, ScanKind.none);
    });

    test('normalize trims whitespace and GS1 control characters only', () {
      expect(ScanService.normalize(' \x1d0478000\n'), '0478000');
      expect(ScanService.normalize('ABC-12'), 'ABC-12', reason: 'digits are extracted by the server');
    });
  });

  group('ScanDebouncer', () {
    test('same code ignored within 1.5 s; one lookup in flight', () async {
      var now = DateTime(2026, 9, 19, 10);
      final d = ScanDebouncer(now: () => now);
      var runs = 0;
      Future<int> task() async {
        runs++;
        return runs;
      }

      expect((await d.run('111', task)).$1, isTrue);
      now = now.add(const Duration(milliseconds: 500));
      expect((await d.run('111', task)).$1, isFalse, reason: 'same code too soon');
      expect((await d.run('222', task)).$1, isTrue, reason: 'another code is fine');
      now = now.add(const Duration(milliseconds: 1600));
      expect((await d.run('222', task)).$1, isTrue);
      expect(runs, 3);

      // In flight: a second detection is dropped.
      final slow = d.run('333', () => Future<int>.delayed(const Duration(milliseconds: 20), () => 9));
      expect(d.busy, isTrue);
      expect((await d.run('444', task)).$1, isFalse);
      expect((await slow).$2, 9);
      d.reset();
      expect(d.shouldProcess('333'), isTrue);
    });
  });

  group('BarcodeScanScreen', () {
    late FakeBackend be;

    setUp(() async {
      await resetCore();
      be = FakeBackend();
      signIn();
    });

    tearDown(() => Session.instance.debugReset());

    ScannerViewBuilder fakeCamera(List<String> codes) => (ctx, onCode, errorView) => Center(
          child: ElevatedButton(
            key: const Key('fake-detect'),
            onPressed: () => onCode(codes.removeAt(0)),
            child: const Text('detect'),
          ),
        );

    testWidgets('legacy raw mode pops the digits of the code', (tester) async {
      Object? result;
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
        result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
            builder: (_) => BarcodeScanScreen(scannerBuilder: fakeCamera(['47-80 001']))));
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('fake-detect')));
      await tester.pumpAndSettle();
      expect(result, '4780001');
      expect(be.log, isEmpty, reason: 'raw mode never calls the server');
    });

    testWidgets('lookup mode: server resolves the barcode, screen pops a ScanResult', (tester) async {
      be.get('/products/scan', (r) => {'code': r.query['code'], 'kind': 'barcode', 'product': product('p1', 'Sut'), 'candidates': []});
      Object? result;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(branchId: 'b9', scannerBuilder: fakeCamera(['04780001']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pumpAndSettle();
      });
      final r = result as ScanResult;
      expect(r.product!.name, 'Sut');
      expect(r.kind, ScanKind.barcode);
      expect(be.last('GET', '/products/scan').query, {'code': '04780001', 'branch_id': 'b9'});
    });

    testWidgets('scale label returns the weighed quantity', (tester) async {
      be.get('/products/scan', (r) => {
            'code': '2001230012344',
            'kind': 'scale',
            'product': product('g', 'Go‘sht', weighted: true, plu: '123'),
            'candidates': [],
            'scale': {'plu': 123, 'grams': 1234, 'qty': '1.234'},
          });
      Object? result;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(scannerBuilder: fakeCamera(['2001230012344']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pumpAndSettle();
      });
      expect((result as ScanResult).qtyMilli, 1234);
    });

    testWidgets('ambiguous PLU -> operator chooses; archived is marked', (tester) async {
      be.get('/products/scan', (r) => {
            'code': '2001230005001',
            'kind': 'ambiguous',
            'product': null,
            'candidates': [product('a', 'Mol go‘shti', weighted: true, plu: '123'), product('b', 'Qo‘y go‘shti', weighted: true, plu: '123', active: false)],
            'scale': {'plu': 123, 'grams': 500, 'qty': '0.500'},
          });
      Object? result;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(scannerBuilder: fakeCamera(['2001230005001']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pumpAndSettle();
        expect(find.text('Qaysi mahsulot?'), findsOneWidget);
        expect(find.textContaining('Arxivda'), findsOneWidget);
        await tester.tap(find.byKey(const Key('scan-candidate-b')));
        await tester.pumpAndSettle();
      });
      final r = result as ScanResult;
      expect(r.product!.id, 'b');
      expect(r.product!.isActive, isFalse);
      expect(r.qtyMilli, 500);
    });

    testWidgets('not found: explicit sheet; "continue with this code" when allowed', (tester) async {
      be.get('/products/scan', (r) => {'code': '999', 'kind': 'none', 'product': null, 'candidates': []});
      Object? result;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(allowNotFound: true, scannerBuilder: fakeCamera(['999']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pumpAndSettle();
        expect(find.text('Mahsulot topilmadi'), findsOneWidget);
        expect(find.byKey(const Key('scan-notfound-code')), findsOneWidget);
        await tester.tap(find.byKey(const Key('scan-use-code')));
        await tester.pumpAndSettle();
      });
      final r = result as ScanResult;
      expect(r.notFound, isTrue);
      expect(r.code, '999');
    });

    testWidgets('network error: explicit banner, no result; retry works', (tester) async {
      be.offline = true;
      be.get('/products/scan', (r) => {'code': '1', 'kind': 'barcode', 'product': product('p', 'Non'), 'candidates': []});
      Object? result = 'untouched';
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(scannerBuilder: fakeCamera(['1']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pumpAndSettle();
        expect(find.textContaining('Server bilan aloqa yo‘q'), findsOneWidget);
        expect(result, 'untouched');
        be.offline = false;
        await tester.tap(find.byKey(const Key('banner-retry')));
        await tester.pumpAndSettle();
      });
      expect((result as ScanResult).product!.name, 'Non');
    });

    testWidgets('camera permission denied: explanation + manual entry works', (tester) async {
      L.code = 'ru';
      be.get('/products/scan', (r) => {'code': r.query['code'], 'kind': 'barcode', 'product': product('p', 'Kefir'), 'candidates': []});
      Object? result;
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(
                  scannerBuilder: (c, onCode, errorView) => errorView(MobileScannerErrorCode.permissionDenied))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        expect(find.text('Нет доступа к камере'), findsOneWidget);
        await tester.tap(find.byKey(const Key('scan-error-manual')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('scan-manual-field')), '123456');
        await tester.tap(find.byKey(const Key('scan-manual-ok')));
        await tester.pumpAndSettle();
      });
      expect((result as ScanResult).product!.name, 'Kefir');
      expect(be.last('GET', '/products/scan').query['code'], '123456');
    });

    testWidgets('continuous mode reports every result and stays open; same code debounced', (tester) async {
      be.get('/products/scan', (r) => {'code': r.query['code'], 'kind': 'barcode', 'product': product('p${r.query['code']}', 'P${r.query['code']}'), 'candidates': []});
      final got = <String>[];
      final codes = ['11', '11', '22'];
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(
                  continuous: true, onResult: (r) => got.add(r.product!.name), scannerBuilder: fakeCamera(codes))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        for (var i = 0; i < 3; i++) {
          await tester.tap(find.byKey(const Key('fake-detect')));
          await tester.pumpAndSettle();
        }
        expect(find.byKey(const Key('scan-last')), findsOneWidget);
        expect(find.text('Tayyor (2)'), findsOneWidget);
        await tester.tap(find.byKey(const Key('scan-done')));
        await tester.pumpAndSettle();
      });
      expect(got, ['P11', 'P22']);
      expect(be.calls('GET', '/products/scan'), hasLength(2));
    });

    test('scanProduct() is the one-line public entry point for feature packages', () {
      expect(scanProduct, isA<Future<ScanResult?> Function(BuildContext, {String? branchId, bool allowNotFound})>());
    });
  });
}
