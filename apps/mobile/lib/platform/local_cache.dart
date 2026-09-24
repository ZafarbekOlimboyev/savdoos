import 'local_cache_stub.dart'
    if (dart.library.io) 'local_cache_io.dart'
    if (dart.library.js_interop) 'local_cache_web.dart';

export 'local_cache_stub.dart'
    if (dart.library.io) 'local_cache_io.dart'
    if (dart.library.js_interop) 'local_cache_web.dart' show createLocalCache;

/// On-device cache files of OLDER app versions.
///
/// The RULE lives in `Api` (another tenant's catalog must never survive a
/// logout / 401 / server change and is purged once at start-up); this adapter
/// only knows the medium. The app no longer writes a catalog to disk.
abstract class LocalCache {
  /// The active adapter (tests inject a fake).
  static LocalCache instance = createLocalCache();

  /// Deletes every `catalog_*.json` an older version left in the app support
  /// directory, whichever employee/company/server it belonged to. Never throws.
  Future<void> purgeCatalogFiles();
}
