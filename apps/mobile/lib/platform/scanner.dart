import 'package:flutter/widgets.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'scanner_stub.dart'
    if (dart.library.io) 'scanner_io.dart'
    if (dart.library.js_interop) 'scanner_web.dart';

export 'scanner_stub.dart'
    if (dart.library.io) 'scanner_io.dart'
    if (dart.library.js_interop) 'scanner_web.dart' show createScanner;

/// Skaner diagnostikasi panelini yoqadi — FAQAT sinov/nomzod build'ida.
///
///     flutter build web ... --dart-define=BINOS_SCAN_DIAG=1
///
/// ⚠️  Oddiy production build'ida bu `false` va panel UMUMAN qurilmaydi.
///     Panelga kadr, rasm, barkod qiymati, token yoki sir CHIQMAYDI — faqat
///     sanoq va o'lchamlar.
const bool kScanDiagnostics = bool.fromEnvironment('BINOS_SCAN_DIAG');

/// Dekodlash oynasi (ROI) — kadrning markaziy ulushi.
///
/// ⚠️  `web/scanner.js` dagi `ROI_W`/`ROI_H` bilan AYNI bo'lishi SHART: skaner
///     ekranidagi nishon ramka SHU ulushlar bo'yicha chiziladi, ya'ni operator
///     ko'rayotgan ramka haqiqatan dekodlanadigan joyni ko'rsatadi (ilgari
///     ramka 260x160 qat'iy edi va web'da BEZAK bo'lib qolardi: `scanWindow`
///     web implementatsiyasida no-op). Moslikni `tests/scanner-loop.test.ts`
///     tekshiradi. To'liq kadr ham navbatma-navbat sinaladi — tolerantlik saqlanadi.
const double kScanRoiW = 0.86;
const double kScanRoiH = 0.46;

/// App-facing name of the camera error code.
///
/// It is an alias of the plugin enum (not a copy) so the existing seam
/// `ScannerViewBuilder` — used by widget tests AND `test/e2e/harness.dart`
/// (`E2ECamera.view`) — keeps its signature; screens and tests import THIS
/// name from the platform barrel, never the plugin.
typedef ScanErrorCode = MobileScannerErrorCode;

/// Camera barcode scanner. `mobile_scanner` declares a web implementation, so
/// ONE adapter; the capability flags carry the platform truth (`kIsWeb` is a
/// pure-Dart flag here, never around an import).
///
/// The screen's `scannerBuilder` seam is untouched: the adapter supplies the
/// DEFAULT camera when no builder is injected.
abstract class Scanner {
  /// The active adapter (tests inject a fake).
  static Scanner instance = createScanner();

  /// A torch can be toggled. FALSE on web: `mobile_scanner_web` reports
  /// `TorchState.unavailable` and `toggleTorch()` throws `UnsupportedError`,
  /// so a torch button there is dead UI.
  bool get hasTorch;

  /// Front/back camera switching is possible.
  bool get canSwitchCamera;

  /// Opens a camera session (one per screen instance).
  ScannerSession open();
}

/// One camera session: the preview widget plus best-effort controls. Every
/// control is safe to call in any state and never throws.
abstract class ScannerSession {
  /// The preview; [onCode] receives each raw detection, [errorView] renders
  /// a camera failure (permission, unsupported, busy).
  Widget view({required ValueChanged<String> onCode, required Widget Function(ScanErrorCode code) errorView});

  /// (Re)starts the camera.
  Future<void> start();

  /// Stops the camera (background, hidden tab).
  Future<void> stop();

  /// Toggles the torch when [Scanner.hasTorch].
  Future<void> toggleTorch();

  /// Switches front/back.
  Future<void> switchCamera();

  /// Releases the camera.
  Future<void> dispose();

  /// Kamera/dekoder holati — FAQAT sanoq va o'lchamlar.
  ///
  /// ⚠️  MAXFIYLIK: bu yerga kadr, rasm, barkod QIYMATI, token yoki sir
  ///     TUSHMAYDI. Panel faqat `--dart-define=BINOS_SCAN_DIAG=1` bilan
  ///     yig'ilgan build'da ko'rsatiladi; oddiy production UI'da yo'q.
  Map<String, Object?> diagnostics() => const <String, Object?>{};
}
