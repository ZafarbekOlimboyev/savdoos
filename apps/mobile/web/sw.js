/*
 * SavdoOS PWA service worker (Phase 5G.1, package C1).
 *
 * Flutter 3.44 ships only a self-unregistering stub (measured: zero
 * registrations after load), so the caching policy is ours and every rule
 * below is a decision, not a default.
 *
 * THE RULE THAT MATTERS MOST: business API responses are never cached.
 * Cache Storage is per-origin, not per-employee. A shop iPhone is handed
 * around; if this worker ever stored an authenticated response, the next
 * person to open the icon could be shown the previous employee's branch,
 * revenue or receipt — before the request even acquired an Authorization
 * header — with nothing on screen saying it was stale. So the worker does not
 * merely "avoid" the API: it refuses to intercept anything cross-origin, any
 * non-GET, anything under an API path, and anything carrying an Authorization
 * header, and it re-checks all of that again at the single cache-write site.
 *
 * SECOND RULE: this is a bridge, not an emergency POS. Reads may come from the
 * cached shell; writes are NEVER queued, replayed or answered from here. There
 * is no database, no background sync and no synthesized Response in this file,
 * so a write that did not reach the server fails in the app exactly as it does
 * on Android.
 *
 * THIRD RULE: no stale bundle. The cache name carries a per-build id stamped
 * by `scripts/pwa_postbuild.mjs`; activate deletes every other build's cache; and
 * the entry points (navigations, index.html, flutter_bootstrap.js,
 * main.dart.js) are network-first, so a deploy is picked up on the next load
 * even before the worker itself updates.
 *
 * If the build id was never stamped, the worker runs INERT: it caches nothing
 * and passes every request through. A forgotten build step therefore costs the
 * offline shell — never a wrong or stale answer.
 */

const BINOS_SW_POLICY = {
  "buildId": "__BINOS_BUILD_ID__",
  "cachePrefix": "binos-shell-",
  "precache": [
    "./",
    "index.html",
    "pwa.js",
    "flutter_bootstrap.js",
    "manifest.json",
    "favicon.png",
    "icons/Icon-192.png",
    "icons/apple-touch-icon-180.png",
    "vendor/zxing/zxing-0.19.1.min.js"
  ],
  "networkFirst": [
    "/",
    "/index.html",
    "/flutter_bootstrap.js",
    "/flutter.js",
    "/main.dart.js",
    "/manifest.json",
    "/version.json"
  ],
  "neverCache": {
    "pathPrefixes": ["/api/"],
    "onlyMethod": "GET",
    "sameOriginOnly": true,
    "authenticatedRequests": true
  },
  "update": "prompt-then-reload",
  "offlineWrites": "never-queued"
};

// The stamper replaces the literal placeholder; this comparison is written in
// two pieces so the stamp cannot rewrite the check along with the value.
const INERT = !BINOS_SW_POLICY.buildId || BINOS_SW_POLICY.buildId === '__BINOS' + '_BUILD_ID__';

const CACHE_NAME = BINOS_SW_POLICY.cachePrefix + BINOS_SW_POLICY.buildId;

function isApiPath(pathname) {
  return BINOS_SW_POLICY.neverCache.pathPrefixes.some(function (prefix) {
    return pathname === prefix || pathname === prefix.replace(/\/$/, '') || pathname.indexOf(prefix) === 0;
  });
}

function isNetworkFirst(url, request) {
  // Every navigation goes to the network first: that is what stops a deploy
  // from being served out of an old shell.
  if (request.mode === 'navigate') return true;
  const name = '/' + url.pathname.split('/').pop();
  return BINOS_SW_POLICY.networkFirst.indexOf(name) !== -1;
}

/**
 * The ONLY predicate that may say "yes, store this". It repeats the fetch
 * guards on purpose: a future caller must not be able to reach the cache by
 * skipping them.
 */
function isCacheable(request, response) {
  if (INERT) return false;
  if (request.method !== BINOS_SW_POLICY.neverCache.onlyMethod) return false;
  if (request.headers.has('Authorization')) return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (isApiPath(url.pathname)) return false;
  if (!response || response.status !== 200 || response.type === 'opaque') return false;
  const control = response.headers.get('Cache-Control') || '';
  if (control.indexOf('no-store') !== -1 || control.indexOf('private') !== -1) return false;
  const vary = response.headers.get('Vary') || '';
  if (/authorization|cookie/i.test(vary)) return false;
  return true;
}

/**
 * The single cache-write site. It NEVER rejects.
 *
 * A cache write is an optimisation; the response is the product. Storage can
 * fail for reasons that have nothing to do with this request — a low-storage
 * iPhone hitting QuotaExceededError while two builds' caches coexist is the
 * ordinary one — and a rejection here used to be caught by the callers' `try`
 * as if the NETWORK had failed, so a 200 from the server turned into the
 * browser's offline page and the PWA could not be opened at all.
 */
async function cachePut(request, response) {
  try {
    if (!isCacheable(request, response)) return;
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response);
  } catch (error) {
    // Storage is full / blocked / evicted mid-write. Nothing to do: the caller
    // already has its answer, and the next load will try again.
  }
}

/**
 * A fetch that does NOT go through the browser's HTTP cache.
 *
 * `main.dart.js` carries no content hash, so a host or CDN that serves it with
 * a long `max-age` would answer "network-first" from the HTTP cache with the
 * PREVIOUS build and we would then write that stale bundle into the shell
 * cache — the update would never arrive, whatever the operator does. A
 * navigation Request cannot be copied (`mode: 'navigate'`), so it is rebuilt
 * from its URL.
 */
function freshFetch(request) {
  if (request.mode === 'navigate') {
    return fetch(new Request(request.url, { cache: 'reload', credentials: 'same-origin' }));
  }
  return fetch(new Request(request, { cache: 'reload' }));
}

async function precacheShell() {
  for (const entry of BINOS_SW_POLICY.precache) {
    try {
      const request = new Request(new URL(entry, self.location.href), { cache: 'reload', credentials: 'same-origin' });
      const response = await fetch(request);
      await cachePut(request, response);
    } catch (error) {
      // A shell entry that is missing (or offline at install time) must never
      // fail the install — the app still runs, just without that asset cached.
    }
  }
}

async function networkFirst(request) {
  try {
    const response = await freshFetch(request);
    // Deliberately NOT awaited into the answer: see [cachePut].
    cachePut(request, response.clone());
    return response;
  } catch (error) {
    const cached = await caches.match(request, { cacheName: CACHE_NAME, ignoreSearch: true });
    if (cached) return cached;
    // Nothing cached and no network: let the browser report its own failure.
    // Synthesizing a body here is how a PWA ends up lying about being online.
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { cacheName: CACHE_NAME });
  const fromNetwork = freshFetch(request).then(function (response) {
    cachePut(request, response.clone());
    return response;
  });
  if (cached) {
    fromNetwork.catch(function () { /* revalidation is best-effort */ });
    return cached;
  }
  return fromNetwork;
}

function onInstall(event) {
  // This handler deliberately does NOT take over the page. A freshly installed
  // build must not replace the bundle under an operator who is in the middle of
  // a receiving document; `pwa.js` shows a banner and the message handler below
  // performs the swap only after the operator accepts.
  if (INERT) return;
  event.waitUntil(precacheShell());
}

function onActivate(event) {
  event.waitUntil((async function () {
    const names = await caches.keys();
    for (const name of names) {
      if (name.indexOf(BINOS_SW_POLICY.cachePrefix) !== 0) continue;
      // INERT builds own no cache at all, so they clear the prefix entirely.
      if (INERT || name !== CACHE_NAME) await caches.delete(name);
    }
    await self.clients.claim();
  })());
}

/**
 * A newer worker is installed and waiting for the operator to accept.
 *
 * Until they do, THIS worker keeps controlling the page — and it must keep
 * serving ONE build. Network-first would hand the page the NEW `main.dart.js`
 * while `assets/` and `canvaskit/` still came from this build's cache: a
 * bundle that never existed, whose symptoms (a blank canvas, a missing asset)
 * look like a broken app rather than a pending update.
 */
function swapPending() {
  try {
    return Boolean(self.registration && self.registration.waiting);
  } catch (error) {
    return false;
  }
}

/**
 * This build's copy, or the network when we never cached it — and the answer
 * is NOT written to the cache: a file from the next build must not land in
 * this build's cache and outlive the swap.
 */
async function frozenBundle(request) {
  const cached = await caches.match(request, { cacheName: CACHE_NAME, ignoreSearch: true });
  if (cached) return cached;
  return freshFetch(request);
}

function onFetch(event) {
  if (INERT) return;
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isApiPath(url.pathname)) return;
  if (request.headers.has('Authorization')) return;
  if (url.pathname.slice(-6) === '/sw.js') return;
  if (swapPending()) {
    // The operator has not accepted the new build yet: freeze the bundle.
    event.respondWith(frozenBundle(request));
    return;
  }
  if (isNetworkFirst(url, request)) {
    event.respondWith(networkFirst(request));
    return;
  }
  event.respondWith(cacheFirst(request));
}

self.addEventListener('install', onInstall);
self.addEventListener('activate', onActivate);
self.addEventListener('fetch', onFetch);
self.addEventListener('message', function (event) {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
