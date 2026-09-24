// Scanner adapter (B4 item 1): the screen keeps its `scannerBuilder` test seam;
// the adapter supplies the default camera AND the capability flags, so a
// torch button is never drawn on a platform whose torch does nothing (web).
// The camera stops once per background cycle and restarts once on resume.
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';

import 'support/support.dart';

void main() {
  late FakeScanner scanner;

  setUp(() async {
    await resetCore();
    signIn();
    scanner = FakeScanner();
    Scanner.instance = scanner;
  });

  Future<void> pump(WidgetTester t) async {
    await pumpAt390(t, const BarcodeScanScreen.lookup());
    await t.pump();
  }

  testWidgets('torch and camera-switch buttons follow the adapter capabilities', (t) async {
    scanner.hasTorch = false;
    scanner.canSwitchCamera = true;
    await pump(t);
    expect(find.byKey(const Key('scan-torch')), findsNothing, reason: 'web: toggleTorch throws UnsupportedError');
    expect(find.byKey(const Key('scan-switch-camera')), findsOneWidget);
    expect(scanner.sessions, hasLength(1));
  });

  testWidgets('a torch-capable platform shows the torch and it reaches the session', (t) async {
    scanner.hasTorch = true;
    await pump(t);
    expect(find.byKey(const Key('scan-torch')), findsOneWidget);
    await t.tap(find.byKey(const Key('scan-torch')));
    await t.pump();
    expect(scanner.sessions.single.torchToggles, 1);
    await t.tap(find.byKey(const Key('scan-switch-camera')));
    await t.pump();
    expect(scanner.sessions.single.cameraSwitches, 1);
  });

  testWidgets('the camera stops ONCE for inactive+hidden+paused and starts ONCE on resume', (t) async {
    await pump(t);
    final s = scanner.sessions.single;
    for (final st in [AppLifecycleState.inactive, AppLifecycleState.hidden, AppLifecycleState.paused]) {
      t.binding.handleAppLifecycleStateChanged(st);
      await t.pump();
    }
    expect(s.stops, 1);
    expect(s.starts, 0);
    for (final st in [AppLifecycleState.hidden, AppLifecycleState.inactive, AppLifecycleState.resumed]) {
      t.binding.handleAppLifecycleStateChanged(st);
      await t.pump();
    }
    expect(s.stops, 1);
    expect(s.starts, 1);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await t.pump();
  });

  testWidgets('the session is disposed with the screen', (t) async {
    await pump(t);
    final s = scanner.sessions.single;
    expect(s.disposed, isFalse);
    await t.pumpWidget(const SizedBox.shrink());
    expect(s.disposed, isTrue);
  });

  testWidgets('a code from the adapter session reaches the screen (legacy raw mode pops the digits)', (t) async {
    Object? result;
    await pumpAt390(t, LaunchHost(onPressed: (ctx) async {
      result = await Navigator.of(ctx).push<Object?>(MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
    }));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
    scanner.sessions.single.detect('47-80 001');
    await t.pumpAndSettle();
    expect(result, '4780001');
  });

  testWidgets('a camera error from the adapter shows the app-owned error view with manual entry', (t) async {
    scanner.error = ScanErrorCode.permissionDenied;
    await pump(t);
    expect(find.byKey(const Key('scan-camera-error-permissionDenied')), findsOneWidget);
    expect(find.byKey(const Key('scan-error-manual')), findsOneWidget);
    expect(find.text('Qayta urinish'), findsOneWidget, reason: 'retry is offered for a denied permission');
  });

  testWidgets('with a scannerBuilder (tests, E2E) the adapter is not opened at all', (t) async {
    await pumpAt390(
        t,
        BarcodeScanScreen(
            scannerBuilder: (c, onCode, errorView) => const SizedBox(key: Key('fake-cam'))));
    expect(find.byKey(const Key('fake-cam')), findsOneWidget);
    expect(scanner.sessions, isEmpty);
    expect(find.byKey(const Key('scan-torch')), findsNothing);
  });

  test('the default adapter reports the torch only off web (same test, both platforms)', () {
    final real = createScanner();
    expect(real.hasTorch, !kIsWeb, reason: 'VM/Android: torch; web: mobile_scanner_web has no torch');
    expect(real.canSwitchCamera, isTrue);
  });
}
