import 'dart:typed_data';

import 'package:share_plus/share_plus.dart';

import 'file_export.dart';
import 'platform_error.dart';

/// Web: no file system. The bytes go straight to the Web Share sheet
/// (`navigator.share` with a data-backed file — iOS Safari 15+, Android
/// Chrome); where the browser cannot share files, `share_plus` 10.x falls
/// back to a `<a download>` of the same bytes (`Share.downloadFallbackEnabled`,
/// true by default). Anything else becomes a localized [PlatformUnavailable].
///
/// Known UX difference to state in the pilot checklist: iOS Safari may open
/// a downloaded file in a viewer instead of saving it.
FileExport createFileExport() => const _WebFileExport();

class _WebFileExport implements FileExport {
  const _WebFileExport();

  @override
  bool get supported => true;

  @override
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text}) async {
    try {
      await Share.shareXFiles(
        [XFile.fromData(Uint8List.fromList(bytes), mimeType: mime, name: filename)],
        text: text,
        fileNameOverrides: [filename],
      );
    } catch (e) {
      throw PlatformUnavailable(PlatformUnavailable.kShare, cause: e);
    }
  }
}
