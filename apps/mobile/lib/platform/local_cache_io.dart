import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'local_cache.dart';

/// Android/iOS/desktop: the app support directory on disk.
LocalCache createLocalCache() => const _IoLocalCache();

class _IoLocalCache implements LocalCache {
  const _IoLocalCache();

  @override
  Future<void> purgeCatalogFiles() async {
    // Body moved verbatim from `Api._purgeCatalogCache` (pre-5G.1).
    try {
      final dir = await getApplicationSupportDirectory();
      await for (final f in dir.list(followLinks: false)) {
        if (f is! File) continue;
        final name = f.path.replaceAll('\\', '/').split('/').last;
        if (name.startsWith('catalog_') && name.endsWith('.json')) {
          try {
            await f.delete();
          } catch (_) {}
        }
      }
    } catch (_) {/* fayl tizimi yo'q / ruxsat yo'q — o'chiradigan narsa yo'q */}
  }
}
