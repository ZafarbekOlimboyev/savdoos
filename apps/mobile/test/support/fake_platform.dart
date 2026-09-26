// In-memory fakes of every `lib/platform` adapter. Pure Dart — no
// `dart:io`, no method channel — so the same widget tests run on the VM and
// under `flutter test --platform chrome`. Installed by `PlatformMocks.install()`.
import 'package:flutter/material.dart';
import 'package:savdoos_mobile/platform/platform.dart';

/// Secret store backed by a plain map (the map is shared with tests).
class FakeSecretStore implements SecretStore {
  FakeSecretStore(this.map, {this.hardwareBacked = true});

  /// The backing map.
  final Map<String, String> map;

  /// What the fake claims about its medium (Android phone by default).
  final bool hardwareBacked;

  @override
  bool get isHardwareBacked => hardwareBacked;

  @override
  Future<String?> read(String key) async => map[key];

  @override
  Future<void> write(String key, String value) async => map[key] = value;

  @override
  Future<void> delete(String key) async => map.remove(key);
}

/// Biometrics whose answers come from callbacks (so tests flip flags at will).
class FakeBiometrics implements Biometrics {
  FakeBiometrics({required this.isAvailable, required this.accepts, this.supported = true});

  /// Whether a biometric is enrolled.
  final bool Function() isAvailable;

  /// Whether the prompt succeeds.
  final bool Function() accepts;

  @override
  final bool supported;

  @override
  Future<bool> available() async => supported && isAvailable();

  @override
  Future<bool> authenticate(String reason) async => supported && isAvailable() && accepts();
}

/// One file handed to [FakeFileExport].
class ExportedFile {
  ExportedFile(this.filename, this.mime, this.bytes, this.text);

  final String filename, mime;
  final List<int> bytes;
  final String? text;
}

/// Records exports instead of touching a file system or share sheet.
class FakeFileExport implements FileExport {
  FakeFileExport(this.log);

  /// Every export, in order.
  final List<ExportedFile> log;

  @override
  bool get supported => true;

  @override
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text}) async =>
      log.add(ExportedFile(filename, mime, bytes, text));
}

/// Records shared texts.
class FakeSharing implements Sharing {
  FakeSharing(this.log);

  /// Every shared body, in order.
  final List<String> log;

  @override
  Future<void> text(String body, {String? subject}) async => log.add(body);
}

/// Counts purges instead of deleting files (asserts the RULE, not the medium).
class FakeLocalCache implements LocalCache {
  /// How many times the catalog cache was purged.
  int purges = 0;

  @override
  Future<void> purgeCatalogFiles() async => purges++;
}

/// A fixed version.
class FakeAppPackageInfo implements AppPackageInfo {
  const FakeAppPackageInfo(this.value);

  final AppVersion? value;

  @override
  Future<AppVersion?> read() async => value;
}

/// Returns whatever [next] yields (null = the operator cancelled).
class FakeImageCapture implements ImageCapture {
  FakeImageCapture(this.next);

  final PickedImage? Function() next;

  @override
  Future<PickedImage?> pick(ImageSource source) async => next();
}

/// A scanner whose sessions are plain widgets; tests drive detections and
/// inspect start/stop/torch calls.
class FakeScanner implements Scanner {
  @override
  bool hasTorch = true;

  @override
  bool canSwitchCamera = true;

  /// When set, every session renders the error view with this code.
  ScanErrorCode? error;

  /// Every session opened, in order.
  final List<FakeScannerSession> sessions = [];

  @override
  ScannerSession open() {
    final s = FakeScannerSession(error);
    sessions.add(s);
    return s;
  }
}

/// A recorded camera session.
class FakeScannerSession implements ScannerSession {
  FakeScannerSession(this.error);

  final ScanErrorCode? error;
  int starts = 0, stops = 0, torchToggles = 0, cameraSwitches = 0;
  bool disposed = false;
  ValueChanged<String>? _onCode;

  /// Simulates one camera detection.
  void detect(String code) => _onCode?.call(code);

  @override
  Widget view({required ValueChanged<String> onCode, required Widget Function(ScanErrorCode code) errorView}) {
    _onCode = onCode;
    final e = error;
    if (e != null) return errorView(e);
    return const ColoredBox(key: Key('fake-camera'), color: Colors.black);
  }

  @override
  Future<void> start() async => starts++;

  @override
  Future<void> stop() async => stops++;

  @override
  Future<void> toggleTorch() async => torchToggles++;

  @override
  Future<void> switchCamera() async => cameraSwitches++;

  @override
  Future<void> dispose() async => disposed = true;

  @override
  Map<String, Object?> diagnostics() => diag;

  /// Testlar diagnostikani xohlagancha to'ldiradi (panel sinovi uchun).
  Map<String, Object?> diag = const <String, Object?>{};
}
