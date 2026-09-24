import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import 'file_export.dart';
import 'platform_error.dart';

/// Android/iOS: a temp file + the native share sheet (as before 5G.1).
FileExport createFileExport() => const _IoFileExport();

class _IoFileExport implements FileExport {
  const _IoFileExport();

  @override
  bool get supported => true;

  @override
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text}) async {
    try {
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/$filename');
      await file.writeAsBytes(bytes, flush: true);
      await Share.shareXFiles([XFile(file.path, mimeType: mime)], text: text);
    } catch (e) {
      throw PlatformUnavailable(PlatformUnavailable.kShare, cause: e);
    }
  }
}
