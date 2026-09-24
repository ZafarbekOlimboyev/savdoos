import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

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
}

/// The default (`mobile_scanner`) adapter.
Scanner createScanner() => const _PluginScanner();

class _PluginScanner implements Scanner {
  const _PluginScanner();

  @override
  bool get hasTorch => !kIsWeb;

  @override
  bool get canSwitchCamera => true;

  @override
  ScannerSession open() => _PluginSession(
        MobileScannerController(detectionSpeed: DetectionSpeed.normal, facing: CameraFacing.back),
      );
}

class _PluginSession implements ScannerSession {
  _PluginSession(this._ctrl);

  final MobileScannerController _ctrl;

  @override
  Widget view({required ValueChanged<String> onCode, required Widget Function(ScanErrorCode code) errorView}) =>
      MobileScanner(
        controller: _ctrl,
        errorBuilder: (ctx, e, _) => errorView(e.errorCode),
        onDetect: (capture) {
          for (final bc in capture.barcodes) {
            final raw = bc.rawValue;
            if (raw != null && raw.isNotEmpty) {
              onCode(raw);
              break;
            }
          }
        },
      );

  Future<void> _safe(Future<void> Function() f) async {
    try {
      await f();
    } catch (_) {/* best-effort camera control */}
  }

  @override
  Future<void> start() => _safe(_ctrl.start);

  @override
  Future<void> stop() => _safe(_ctrl.stop);

  @override
  Future<void> toggleTorch() => _safe(_ctrl.toggleTorch);

  @override
  Future<void> switchCamera() => _safe(_ctrl.switchCamera);

  @override
  Future<void> dispose() => _safe(_ctrl.dispose);
}
