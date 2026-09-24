// C2 item 4 — camera permission UX.
//
// Today a permanently denied camera is a dead end: `_errorView` tells the
// operator to grant the permission "in phone settings" and gives them no way
// to get there (there is no deep link anywhere in the app — neither Dart nor
// Kotlin), while the one button that looks like it should help ("Qayta
// urinish") re-runs the same request, which Android answers `denied`
// immediately and without a dialog once the operator has denied twice.
//
// What this pins:
//   * where the platform HAS an app-settings screen, the error view offers it
//     and tapping it really leaves for it;
//   * where it has not (iOS, and Safari/PWA, where site permissions live only
//     in the browser's own UI), the button is absent — the app never promises
//     a control it cannot provide — and nothing throws;
//   * manual barcode entry is offered on EVERY camera failure, always;
//   * the camera is asked for at feature time only: opening the app opens no
//     camera session at all.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Installs a fake Android side for the app-settings channel.
/// Returns the list of methods it received.
List<String> mockAppSettings({bool supported = true, bool opens = true}) {
  final calls = <String>[];
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(const MethodChannel(AppSettingsLink.channelName), (call) async {
    calls.add(call.method);
    return switch (call.method) {
      'supported' => supported,
      'open' => opens,
      _ => null,
    };
  });
  addTearDown(() => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(const MethodChannel(AppSettingsLink.channelName), null));
  return calls;
}

void main() {
  setUp(() async => resetCore());

  group('camera denied', () {
    testWidgets('a phone with an app-settings screen gets a working deep link', (tester) async {
      final calls = mockAppSettings();
      await pumpAt390(
          tester,
          const BarcodeScanScreen(
              scannerBuilder: _DeniedCamera.build));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('scan-camera-error-permissionDenied')), findsOneWidget);
      expect(find.byKey(const Key('scan-error-manual')), findsOneWidget, reason: 'manual entry is always offered');

      final settings = find.byKey(const Key('scan-open-settings'));
      expect(settings, findsOneWidget, reason: 'the copy tells the operator to open Settings — give them the door');
      expectMinTouchTarget(tester, settings);
      await tester.tap(settings);
      await tester.pumpAndSettle();
      expect(calls, contains('open'));
    });

    testWidgets('where no app-settings screen exists the button is absent and nothing throws', (tester) async {
      // No mock handler at all: the channel answers MissingPluginException,
      // which is exactly what iOS and the browser do.
      await pumpAt390(
          tester,
          const BarcodeScanScreen(
              scannerBuilder: _DeniedCamera.build));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('scan-open-settings')), findsNothing);
      expect(find.byKey(const Key('scan-error-manual')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a platform that reports no settings screen also gets no button', (tester) async {
      mockAppSettings(supported: false);
      await pumpAt390(
          tester,
          const BarcodeScanScreen(
              scannerBuilder: _DeniedCamera.build));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scan-open-settings')), findsNothing);
      expect(find.byKey(const Key('scan-error-manual')), findsOneWidget);
    });

    testWidgets('through the real scanner adapter: retry stays, Settings is added, manual comes first',
        (tester) async {
      mockAppSettings();
      Scanner.instance = FakeScanner()..error = ScanErrorCode.permissionDenied;
      await pumpAt390(tester, const BarcodeScanScreen());
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('scan-error-manual')), findsOneWidget);
      expect(find.byKey(const Key('scan-error-retry')), findsOneWidget);
      expect(find.byKey(const Key('scan-open-settings')), findsOneWidget);
      final manualY = tester.getTopLeft(find.byKey(const Key('scan-error-manual'))).dy;
      final settingsY = tester.getTopLeft(find.byKey(const Key('scan-open-settings'))).dy;
      expect(manualY, lessThan(settingsY), reason: 'manual entry is the action that always works');
    });

    // Found on an Android runtime (emulator, API 36): the operator denied the
    // camera, granted it on the phone's permissions page and came back — and
    // the screen still said "no permission". `start()` on a controller that
    // has already failed keeps the plugin's error state, so the failed session
    // must be REPLACED. Only killing the app used to help.
    testWidgets('after the permission is granted, retry opens a NEW session', (tester) async {
      mockAppSettings();
      final scanner = FakeScanner()..error = ScanErrorCode.permissionDenied;
      Scanner.instance = scanner;
      await pumpAt390(tester, const BarcodeScanScreen());
      await tester.pumpAndSettle();
      expect(scanner.sessions, hasLength(1));
      expect(find.byKey(const Key('scan-error-retry')), findsOneWidget);

      scanner.error = null; // the operator granted it in the phone's settings
      await tester.tap(find.byKey(const Key('scan-error-retry')));
      await tester.pumpAndSettle();

      expect(scanner.sessions, hasLength(2), reason: 'the dead session is replaced, not restarted');
      expect(scanner.sessions.first.disposed, isTrue, reason: 'two live controllers fight over the camera');
      // The preview must be KEYED by its session: `mobile_scanner`'s widget
      // starts the camera in `initState` only, so a reused State would leave
      // the replacement camera unstarted (the device bug this test pins).
      expect(find.byKey(ObjectKey(scanner.sessions.last)), findsOneWidget);
      expect(find.byKey(ObjectKey(scanner.sessions.first)), findsNothing);
      expect(find.byKey(const Key('fake-camera')), findsOneWidget, reason: 'the preview is back');
      expect(find.byKey(const Key('scan-error-retry')), findsNothing);
    });

    testWidgets('coming back from the settings page replaces a failed camera', (tester) async {
      mockAppSettings();
      final scanner = FakeScanner()..error = ScanErrorCode.permissionDenied;
      Scanner.instance = scanner;
      await pumpAt390(tester, const BarcodeScanScreen());
      await tester.pumpAndSettle();

      scanner.error = null;
      // Leaving for the permissions page and returning.
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(scanner.sessions, hasLength(2), reason: 'the resume after a failure opens a new camera');
      expect(find.byKey(const Key('fake-camera')), findsOneWidget);
    });

    testWidgets('a WORKING camera is only restarted, never replaced, on resume', (tester) async {
      mockAppSettings();
      final scanner = FakeScanner();
      Scanner.instance = scanner;
      await pumpAt390(tester, const BarcodeScanScreen());
      await tester.pumpAndSettle();

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();

      expect(scanner.sessions, hasLength(1), reason: 'a live camera keeps its session across a background trip');
      expect(scanner.sessions.single.stops, 1);
      expect(scanner.sessions.single.starts, 1);
      expect(scanner.sessions.single.disposed, isFalse);
    });

    testWidgets('an unsupported camera offers manual entry and no retry', (tester) async {
      mockAppSettings();
      Scanner.instance = FakeScanner()..error = ScanErrorCode.unsupported;
      await pumpAt390(tester, const BarcodeScanScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scan-error-manual')), findsOneWidget);
      expect(find.byKey(const Key('scan-error-retry')), findsNothing);
      expect(find.byKey(const Key('scan-open-settings')), findsNothing,
          reason: 'no camera at all is not a permission problem');
    });
  });

  testWidgets('the camera is opened only when the scanner screen is (feature time)', (tester) async {
    final scanner = FakeScanner();
    Scanner.instance = scanner;
    final be = FakeBackend();
    await be.run(() async {
      signIn(role: 'ega');
      be.get('/auth/context', (_) => contextJson(role: 'ega'));
      await Session.instance.load(force: true);
      await pumpAt390(tester, const SettingsScreen());
      await tester.pumpAndSettle();
      expect(scanner.sessions, isEmpty, reason: 'using the app must not ask for the camera');

      await tester.pumpWidget(testApp(const BarcodeScanScreen()));
      await tester.pumpAndSettle();
      expect(scanner.sessions, hasLength(1), reason: 'the camera starts with the scanner screen, not before');
    });
    Session.instance.debugReset();
  });

  group('the Android side of the deep link', () {
    final kotlin = File('android/app/src/main/kotlin/com/savdoos/savdoos_mobile/MainActivity.kt').readAsStringSync();

    test('MainActivity answers the same channel the Dart side calls', () {
      expect(kotlin, contains('"${AppSettingsLink.channelName}"'));
      expect(kotlin, contains('"supported"'));
      expect(kotlin, contains('"open"'));
    });

    test('it opens this app\'s own details page, not a global settings screen', () {
      expect(kotlin, contains('ACTION_APPLICATION_DETAILS_SETTINGS'));
      expect(kotlin, contains('"package"'));
      expect(kotlin, contains('packageName'));
    });

    test('opening Settings needs no new permission', () {
      final manifest = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
      expect(manifest, isNot(contains('ACTION_APPLICATION_DETAILS_SETTINGS')));
    });
  });
}

/// A camera that only ever reports "permission denied".
class _DeniedCamera {
  static Widget build(BuildContext context, ValueChanged<String> onCode, Widget Function(ScanErrorCode) errorView) =>
      errorView(ScanErrorCode.permissionDenied);
}
