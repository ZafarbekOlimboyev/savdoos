/// Native (Android/iOS/desktop) skaner adapteri — `mobile_scanner` plagini.
///
/// ⚠️  WEB BU YO'LDAN KELMAYDI. Brauzerda `scanner_web.dart` ishlaydi: plaginning
///     web implementatsiyasi kamerani o'lcham cheklovisiz so'raydi va
///     `cameraResolution` ni o'qimaydi (sabab: `web/scanner.js` sarlavhasi).
library;

import 'package:flutter/widgets.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'scanner.dart';

/// Native maqsad (Android/iOS/desktop): `mobile_scanner` adapteri.
Scanner createScanner() => const _PluginScanner();

class _PluginScanner implements Scanner {
  const _PluginScanner();

  @override
  // Bu fayl FAQAT native maqsadda kompilyatsiya qilinadi (shartli import),
  // ya'ni `kIsWeb` bu yerda doim `false` — chiroq bor. Web'dagi javob
  // `scanner_web.dart` da: u yerda `false` (Safari torch imkoniyatini bermaydi).
  bool get hasTorch => true;

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

  @override
  Map<String, Object?> diagnostics() => const <String, Object?>{};
}
