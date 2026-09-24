import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/platform/platform.dart';
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

    test('a code the operator TYPED is never dropped: it waits for the lookup in flight', () async {
      var now = DateTime(2026, 9, 19, 10);
      final d = ScanDebouncer(now: () => now);
      final inFlight = Completer<int>();
      final order = <String>[];
      final camera = d.run('111', () async {
        final v = await inFlight.future;
        order.add('camera');
        return v;
      });
      expect(d.busy, isTrue);
      final manual = d.run('222', () async {
        order.add('manual');
        return 7;
      }, manual: true);
      inFlight.complete(1);
      expect((await camera).$2, 1);
      expect(await manual, (true, 7), reason: 'queued behind the camera lookup, never swallowed');
      expect(order, ['camera', 'manual']);

      // The same typed code twice in a row is looked up twice (no quiet period).
      expect((await d.run('222', () async => 8, manual: true)).$1, isTrue);
      expect((await d.run('222', () async => 9, manual: true)).$1, isTrue);
      // ... while the camera still honours the quiet period afterwards.
      expect((await d.run('222', () async => 10)).$1, isFalse);
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

    // The supplier's own scale label: 13 digits, prefix 2, weight encoded. The
    // server found no product but told us the code IS a weighed label.
    Map<String, Object?> unknownScaleLabel(FakeRequest r) => {
          'code': '2001234056780',
          'kind': 'none',
          'product': null,
          'candidates': [],
          'scale': {'plu': 1234, 'grams': 5678, 'qty': '5.678'},
        };

    for (final allowNotFound in [false, true]) {
      testWidgets('an unknown WEIGHED label is never offered as a product barcode (allowNotFound: $allowNotFound)',
          (tester) async {
        be.get('/products/scan', unknownScaleLabel);
        Object? result = 'untouched';
        await be.run(() async {
          await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
            result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
                builder: (_) => BarcodeScanScreen.lookup(
                    allowNotFound: allowNotFound, scannerBuilder: fakeCamera(['2001234056780']))));
          }));
          await tester.tap(find.text('open'));
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const Key('fake-detect')));
          await tester.pumpAndSettle();
          expect(find.text('Mahsulot topilmadi'), findsOneWidget);
          expect(find.byKey(const Key('scan-use-code')), findsNothing,
              reason: 'a weight-encoded label must never become a permanent product barcode');
          expect(find.byKey(const Key('scan-scale-label')), findsOneWidget,
              reason: 'the operator is told it is a weighed label (PLU 1234, 5,678 kg)');
          // The way out is a real barcode, not this label.
          await tester.tap(find.byKey(const Key('scan-again')));
          await tester.pumpAndSettle();
        });
        expect(result, 'untouched', reason: 'nothing is handed to the caller as a usable code');
      });
    }

    test('a weighed label is flagged on the result itself (second guard for callers)', () {
      final l = ScanLookup.fromJson(const {
        'code': '2001234056780',
        'kind': 'none',
        'product': null,
        'candidates': [],
        'scale': {'plu': 1234, 'grams': 5678, 'qty': '5.678'},
      });
      final r = ScanResult(l, null);
      expect(r.isWeighedLabel, isTrue);
      expect(r.notFound, isTrue);
      expect(r.qtyMilli, 5678);
      expect(ScanResult(ScanLookup.fromJson(const {'code': '999', 'kind': 'none'}), null).isWeighedLabel, isFalse);
    });

    testWidgets('code typed in the "not found" sheet is looked up, never silently dropped', (tester) async {
      be.get(
          '/products/scan',
          (r) => r.query['code'] == '999'
              ? {'code': '999', 'kind': 'none', 'product': null, 'candidates': []}
              : {'code': r.query['code'], 'kind': 'barcode', 'product': product('p1', 'Sut'), 'candidates': []});
      Object? result = 'untouched';
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
        await tester.tap(find.byKey(const Key('scan-manual-from-notfound')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('scan-manual-field')), '4780001');
        await tester.tap(find.byKey(const Key('scan-manual-ok')));
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products/scan'), hasLength(2), reason: 'the typed code reached the server');
      expect(be.last('GET', '/products/scan').query['code'], '4780001');
      expect((result as ScanResult).product!.name, 'Sut');
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
                  scannerBuilder: (c, onCode, errorView) => errorView(ScanErrorCode.permissionDenied))));
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
                  continuous: true,
                  onResult: (r) {
                    got.add(r.product!.name);
                    return null; // accepted
                  },
                  scannerBuilder: fakeCamera(codes))));
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

    // NOTE: while the "Qidirilmoqda…" spinner is up the screen animates every
    // frame, so `pumpAndSettle` would run the fake clock past the 30 s read
    // timeout and end the very lookup these tests keep in flight. Frames are
    // therefore pumped explicitly.
    Future<void> settle(WidgetTester tester) async {
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    /// `999` hangs on [gate]; anything else resolves to Sut.
    FakeHandler gatedScan(Completer<void> gate) => (r) async {
          final code = r.query['code'];
          if (code == '999') {
            await gate.future;
            return {'code': '999', 'kind': 'none', 'product': null, 'candidates': []};
          }
          return {'code': code, 'kind': 'barcode', 'product': product('p1', 'Sut'), 'candidates': []};
        };

    // A typed code is QUEUED behind the camera lookup in flight. When the
    // camera lookup then opens a sheet (not found / ambiguous), the queued
    // result must not pop that sheet: it would hand a ScanResult to a
    // Route<String>, lose the product and leave a dead scanner behind.
    testWidgets('a manual code queued behind a camera lookup delivers to the SCREEN, not to the sheet on top of it',
        (tester) async {
      final gate = Completer<void>();
      be.get('/products/scan', gatedScan(gate));
      Object? result = 'untouched';
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(allowNotFound: true, scannerBuilder: fakeCamera(['999']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pump();
        expect(find.byKey(const Key('scan-searching')), findsOneWidget, reason: 'the camera lookup is in flight');

        // The operator gets impatient and types a code.
        await tester.tap(find.byKey(const Key('scan-manual')));
        await settle(tester);
        await tester.enterText(find.byKey(const Key('scan-manual-field')), '4780001');
        await tester.tap(find.byKey(const Key('scan-manual-ok')));
        await settle(tester);
        expect(be.calls('GET', '/products/scan'), hasLength(1),
            reason: 'the typed code waits for the lookup in flight (ScanDebouncer)');

        // Only now does the camera lookup answer "not found" and open its sheet.
        gate.complete();
        for (var i = 0; i < 6; i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(find.text('Mahsulot topilmadi'), findsOneWidget,
            reason: 'the camera answer owns the screen — the queued result must WAIT, not pop this sheet');
        expect(result, 'untouched', reason: 'nothing is handed over while a sheet is open');

        // The operator deals with the sheet; only then is the typed code's
        // product delivered — to the SCREEN's route.
        await tester.tap(find.byKey(const Key('scan-again')));
        for (var i = 0; i < 8; i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
      });
      expect(result, isA<ScanResult>(), reason: 'the typed code must reach the caller');
      expect((result as ScanResult).product!.name, 'Sut');
      expect(find.byKey(const Key('scan-manual')), findsNothing, reason: 'the scanner screen itself was popped');
    });

    testWidgets('a queued manual lookup that resumes after the scanner is gone does nothing', (tester) async {
      final gate = Completer<void>();
      be.get('/products/scan', gatedScan(gate));
      Object? result = 'untouched';
      await be.run(() async {
        await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
          result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(
              builder: (_) => BarcodeScanScreen.lookup(scannerBuilder: fakeCamera(['999']))));
        }));
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('fake-detect')));
        await tester.pump();
        await tester.tap(find.byKey(const Key('scan-manual')));
        await settle(tester);
        await tester.enterText(find.byKey(const Key('scan-manual-field')), '4780001');
        await tester.tap(find.byKey(const Key('scan-manual-ok')));
        await settle(tester);
        expect(be.calls('GET', '/products/scan'), hasLength(1), reason: 'the typed code is still queued');

        // The operator gives up and leaves while both lookups are pending.
        await tester.binding.handlePopRoute();
        await settle(tester);
        gate.complete();
        for (var i = 0; i < 6; i++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
      });
      expect(result, isNull, reason: 'leaving the scanner returns nothing');
      expect(be.calls('GET', '/products/scan'), hasLength(1),
          reason: 'a screen nobody is looking at must not keep asking the server');
    });

    test('scanProduct() is the one-line public entry point for feature packages', () {
      expect(scanProduct, isA<Future<ScanResult?> Function(BuildContext, {String? branchId, bool allowNotFound})>());
    });
  });
}
