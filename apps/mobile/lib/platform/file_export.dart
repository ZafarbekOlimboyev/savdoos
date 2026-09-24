import 'file_export_stub.dart'
    if (dart.library.io) 'file_export_io.dart'
    if (dart.library.js_interop) 'file_export_web.dart';

export 'file_export_stub.dart'
    if (dart.library.io) 'file_export_io.dart'
    if (dart.library.js_interop) 'file_export_web.dart' show createFileExport;

/// Hands a file the app BUILT IN MEMORY (CSV, …) to the operator: the share
/// sheet on Android/iOS, the Web Share sheet or a browser download on web.
/// The content is produced by platform-neutral code; only the hand-over
/// differs per platform.
abstract class FileExport {
  /// The active adapter (tests inject a fake).
  static FileExport instance = createFileExport();

  /// False when this target has no way to hand a file over at all.
  bool get supported;

  /// Shares/downloads [bytes] as [filename] (with [mime]); [text] is the
  /// accompanying message where the share sheet supports one.
  ///
  /// Throws `PlatformUnavailable` (localized) — never a raw plugin exception.
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text});
}
