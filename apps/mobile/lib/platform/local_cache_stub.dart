import 'local_cache.dart';

/// No file system on this target: nothing to purge.
LocalCache createLocalCache() => const _NoLocalCache();

class _NoLocalCache implements LocalCache {
  const _NoLocalCache();

  @override
  Future<void> purgeCatalogFiles() async {}
}
