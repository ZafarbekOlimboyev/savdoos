// C1 (Phase 5G.1) — the PWA caching policy.
//
// Flutter 3.44 ships only a self-unregistering service-worker stub (measured:
// 0 registrations after load), so `web/sw.js` is ours and so is every rule in
// it. This file pins the rules that decide whether the pilot is safe:
//
//  * business API responses are NEVER cached — not by path, not by accident,
//    not for an authenticated request. On a shared iPhone a cached
//    `/api/v1/auth/context` would show employee B the previous employee's
//    branch and revenue, because Cache Storage has no notion of who was
//    signed in;
//  * the app shell is cached under a name that changes per build, and every
//    other cache is deleted on activate — a deploy can never be served half
//    old, half new;
//  * `index.html`, `flutter_bootstrap.js` and `main.dart.js` are network-first,
//    so a new build is picked up on the next load instead of getting stuck;
//  * writes are NEVER queued offline. This is not an emergency POS: a write
//    that did not reach the server must fail, visibly.
//
// The policy lives in `sw.js` as one machine-readable object so these are
// assertions about the values the worker actually runs on, not about comments.
// VM only: reads repo files.
@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String get _src => File('web/sw.js').readAsStringSync();

/// The page-side shell: `index.html` plus `pwa.js`, which holds every line of
/// script the page runs (index.html carries no inline script, so the page can
/// run under `script-src 'self'` with no hash and no nonce).
String get _indexSrc => File('web/index.html').readAsStringSync() + File('web/pwa.js').readAsStringSync();

/// The `BINOS_SW_POLICY` object literal, parsed as JSON (it is written with
/// quoted keys precisely so it can be).
Map<String, dynamic> _policy(String src) {
  final start = src.indexOf('const BINOS_SW_POLICY = ');
  expect(start, isNot(-1), reason: 'sw.js must declare its policy as one readable object');
  final open = src.indexOf('{', start);
  var depth = 0;
  var end = -1;
  for (var i = open; i < src.length; i++) {
    if (src[i] == '{') depth++;
    if (src[i] == '}') {
      depth--;
      if (depth == 0) {
        end = i;
        break;
      }
    }
  }
  expect(end, isNot(-1));
  return (jsonDecode(src.substring(open, end + 1)) as Map).cast<String, dynamic>();
}

/// The body of a top-level `function <name>(…) { … }` (closing brace at column 0).
String _fn(String src, String name) {
  final i = src.indexOf(RegExp('^(?:async )?function $name\\(', multiLine: true));
  expect(i, isNot(-1), reason: 'sw.js must define $name() at top level');
  final end = src.indexOf(RegExp(r'^\}', multiLine: true), i);
  expect(end, isNot(-1), reason: '$name() must close at column 0');
  return src.substring(i, end);
}

List<String> _list(Map<String, dynamic> m, String k) => [for (final v in (m[k] as List)) '$v'];

void main() {
  group('the worker exists and is ours', () {
    test('web/sw.js is present and is not the Flutter stub', () {
      expect(File('web/sw.js').existsSync(), isTrue);
      expect(_src, isNot(contains('self.registration.unregister')),
          reason: 'the Flutter stub unregisters itself; ours must actually cache the shell');
      expect(_src.length, greaterThan(1500), reason: 'a real policy, not a placeholder');
    });

    test('index.html registers it (nothing registers a worker by default in 3.44)', () {
      expect(_indexSrc, contains("serviceWorker.register('sw.js'"));
    });
  });

  group('cache versioning — a deploy can never be served stale', () {
    late Map<String, dynamic> p;

    setUp(() => p = _policy(_src));

    test('the build id in the SOURCE is a placeholder, stamped per build', () {
      expect(p['buildId'], '__BINOS_BUILD_ID__',
          reason: 'a build id checked into the repo would freeze the cache across deploys');
      expect('${p['cachePrefix']}'.trim(), isNotEmpty);
    });

    test('an unstamped build is INERT rather than caching under a shared name', () {
      expect(_src, contains('INERT'));
      expect(_src, contains("'__BINOS' + '_BUILD_ID__'"),
          reason: 'the worker must detect its own unstamped placeholder without the stamper rewriting the check');
      final onFetch = _fn(_src, 'onFetch');
      expect(onFetch, contains('INERT'), reason: 'inert mode must pass every request straight through');
    });

    test('every cache opened is the per-build one', () {
      final opens = RegExp(r'caches\.open\(([^)]*)\)').allMatches(_src).map((m) => m[1]!.trim()).toList();
      expect(opens, isNotEmpty);
      expect(opens.toSet(), {'CACHE_NAME'}, reason: 'a second cache name would survive activate');
      expect(_src, contains("const CACHE_NAME = BINOS_SW_POLICY.cachePrefix + BINOS_SW_POLICY.buildId"));
    });

    test('activate deletes every cache that is not the current build', () {
      final onActivate = _fn(_src, 'onActivate');
      expect(onActivate, contains('caches.keys()'));
      expect(onActivate, contains('caches.delete('));
      expect(onActivate, contains('!== CACHE_NAME'));
    });

    test('the shell entry points are network-first, so a new build wins immediately', () {
      final nf = _list(p, 'networkFirst');
      expect(nf, containsAll(['/', '/index.html', '/flutter_bootstrap.js', '/flutter.js', '/main.dart.js']));
      expect(_fn(_src, 'onFetch'), contains('networkFirst'));
    });
  });

  group('business API responses are never cached', () {
    late Map<String, dynamic> p;

    setUp(() => p = _policy(_src));

    test('/api/ is an explicit never-cache prefix', () {
      final never = (p['neverCache'] as Map).cast<String, dynamic>();
      expect(_list(never, 'pathPrefixes'), contains('/api/'));
    });

    test('only same-origin GET is ever considered for the cache', () {
      final never = (p['neverCache'] as Map).cast<String, dynamic>();
      expect(never['onlyMethod'], 'GET', reason: 'a cached POST response would be a phantom write');
      expect(never['sameOriginOnly'], isTrue, reason: 'the API is a different origin than the PWA host');
      expect(never['authenticatedRequests'], isTrue);
    });

    test('the fetch handler bails out before respondWith for method, origin, api and Authorization', () {
      final onFetch = _fn(_src, 'onFetch');
      final guardEnd = onFetch.indexOf('respondWith');
      expect(guardEnd, isNot(-1));
      final guards = onFetch.substring(0, guardEnd);
      for (final needle in ["!== 'GET'", 'origin !== self.location.origin', 'isApiPath', "has('Authorization')"]) {
        expect(guards, contains(needle), reason: 'missing guard before respondWith: $needle');
      }
    });

    test('there is exactly one place that writes to the cache, and it re-checks the rules', () {
      expect(RegExp(r'\.put\(').allMatches(_src).length, 1, reason: 'one choke point only');
      final put = _fn(_src, 'cachePut');
      expect(put, contains('isCacheable('));
      final cacheable = _fn(_src, 'isCacheable');
      expect(cacheable, contains('isApiPath'));
      expect(cacheable, contains("has('Authorization')"));
      expect(cacheable, contains('no-store'));
      expect(cacheable, contains("status !== 200"));
    });

    test('nothing under /api is precached', () {
      for (final u in _list(p, 'precache')) {
        expect(u, isNot(contains('api')), reason: 'precache entry $u');
      }
      expect(_src, isNot(contains('/api/v1')), reason: 'the worker must not know a single business route');
    });
  });

  group('offline: a bridge, not an emergency POS', () {
    late Map<String, dynamic> p;

    setUp(() => p = _policy(_src));

    test('the policy states writes are never queued', () => expect(p['offlineWrites'], 'never-queued'));

    test('the worker has no queue, no background sync and no database', () {
      for (final banned in ['indexedDB', 'BackgroundSync', 'SyncManager', "addEventListener('sync'", 'replayQueue']) {
        expect(_src, isNot(contains(banned)), reason: 'a queued write would report success the server never gave: $banned');
      }
    });

    test('a failed navigation falls back to the cached shell, never to a fake response', () {
      final onFetch = _fn(_src, 'onFetch');
      expect(onFetch, isNot(contains('new Response(')), reason: 'the worker must never synthesize a body');
      expect(_src, isNot(contains('Response.json(')));
    });
  });

  group('the update flow is explicit and user-driven', () {
    late Map<String, dynamic> p;

    setUp(() => p = _policy(_src));

    test('the policy names a prompt-then-reload flow', () => expect(p['update'], 'prompt-then-reload'));

    test('install does not silently take over a running session', () {
      expect(_fn(_src, 'onInstall'), isNot(contains('skipWaiting')),
          reason: 'skipWaiting during install swaps the bundle under an operator mid-write');
      expect(_src, contains("data === 'SKIP_WAITING'"), reason: 'the page asks for the swap, the worker obeys');
    });

    test('index.html shows a banner on updatefound and reloads once on controllerchange', () {
      expect(_indexSrc, contains('updatefound'));
      expect(_indexSrc, contains('controllerchange'));
      expect(_indexSrc, contains('SKIP_WAITING'));
      expect(_indexSrc, contains('binos-update-banner'));
      expect(_indexSrc, contains('reloading'), reason: 'a controllerchange reload needs a once-only guard');
    });
  });
}
