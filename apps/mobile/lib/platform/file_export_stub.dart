import 'file_export.dart';
import 'platform_error.dart';

/// Unknown target: no way to hand a file over.
FileExport createFileExport() => const _NoFileExport();

class _NoFileExport implements FileExport {
  const _NoFileExport();

  @override
  bool get supported => false;

  @override
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text}) =>
      throw const PlatformUnavailable(PlatformUnavailable.kShare);
}
