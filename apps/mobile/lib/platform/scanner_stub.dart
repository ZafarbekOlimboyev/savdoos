import 'package:flutter/widgets.dart';

import 'scanner.dart';

/// Noma'lum maqsad: kamera yo'q. Ekran qo'lda kiritish yo'lini ko'rsatadi.
Scanner createScanner() => const _NoScanner();

class _NoScanner implements Scanner {
  const _NoScanner();

  @override
  bool get hasTorch => false;

  @override
  bool get canSwitchCamera => false;

  @override
  ScannerSession open() => _NoSession();
}

class _NoSession implements ScannerSession {
  @override
  Widget view({
    required ValueChanged<String> onCode,
    required Widget Function(ScanErrorCode code) errorView,
  }) =>
      errorView(ScanErrorCode.unsupported);

  @override
  Future<void> start() async {}

  @override
  Future<void> stop() async {}

  @override
  Future<void> toggleTorch() async {}

  @override
  Future<void> switchCamera() async {}

  @override
  Future<void> dispose() async {}

  @override
  Map<String, Object?> diagnostics() => const <String, Object?>{};
}
