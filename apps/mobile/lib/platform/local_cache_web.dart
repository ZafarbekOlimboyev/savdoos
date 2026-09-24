import 'local_cache.dart';

/// Web: a documented no-op.
///
/// INVARIANT: the web build writes NO catalog anywhere (no IndexedDB, no
/// localStorage catalog). If a future change caches products in the browser,
/// this method must delete that cache — the rule in `Api` ("another tenant's
/// stock list never survives logout / 401 / server change") does not stop at
/// the file system.
LocalCache createLocalCache() => const _WebLocalCache();

class _WebLocalCache implements LocalCache {
  const _WebLocalCache();

  @override
  Future<void> purgeCatalogFiles() async {}
}
