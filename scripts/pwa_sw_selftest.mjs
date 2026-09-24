#!/usr/bin/env node
/*
 * Behavioural self-test for the SavdoOS PWA service worker
 * (Phase 5G.1, package C1).
 *
 *   node scripts/pwa_sw_selftest.mjs [path/to/sw.js]
 *
 * `apps/mobile/test/pwa_service_worker_test.dart` pins the POLICY — the values
 * the worker runs on and the shape of its guards — but Dart cannot execute
 * JavaScript. This runs the real `sw.js` inside a fake ServiceWorkerGlobalScope
 * and drives actual events, so the claim "the worker never caches a business
 * API response" is demonstrated rather than asserted.
 *
 * It is a checker, not a build step: nothing it does touches the build output.
 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const swPath = path.resolve(process.argv[2] ?? path.join(repoRoot, 'apps/mobile/web/sw.js'));
const ORIGIN = 'https://pwa.example.test';

let failures = 0;
let checks = 0;

function check(name, condition, detail = '') {
  checks++;
  if (condition) {
    console.log(`  ok    ${name}`);
  } else {
    failures++;
    console.log(`  FAIL  ${name}${detail ? '  — ' + detail : ''}`);
  }
}

/* ---------- a fake Cache Storage --------------------------------------- */

class FakeCache {
  constructor(name, log) {
    this.name = name;
    this.log = log;
    this.entries = new Map();
  }
  async put(request, response) {
    this.log.push({ cache: this.name, url: request.url, method: request.method });
    this.entries.set(request.url.split('#')[0], response);
  }
  async match(request) {
    return this.entries.get((request.url ?? request).split('#')[0]);
  }
}

function makeCaches(log) {
  const store = new Map();
  return {
    store,
    async open(name) {
      if (!store.has(name)) store.set(name, new FakeCache(name, log));
      return store.get(name);
    },
    async keys() {
      return [...store.keys()];
    },
    async delete(name) {
      return store.delete(name);
    },
    async match(request, options) {
      const cache = options?.cacheName ? store.get(options.cacheName) : null;
      if (!cache) return undefined;
      return cache.match(request);
    },
  };
}

/* ---------- a fake request/response ------------------------------------ */

class Headers {
  constructor(init = {}) {
    this.map = new Map(Object.entries(init).map(([k, v]) => [k.toLowerCase(), v]));
  }
  has(k) {
    return this.map.has(k.toLowerCase());
  }
  get(k) {
    return this.map.get(k.toLowerCase()) ?? null;
  }
}

class Req {
  constructor(url, init = {}) {
    // `new Request(otherRequest, { ... })` — the copy form the worker uses to
    // re-issue a request with a different cache mode. Without it the fake
    // would stringify the object and the test would pass on a URL that a
    // browser never sees.
    const src = url instanceof Req ? url : null;
    this.url = src ? src.url : typeof url === 'string' ? url : String(url);
    this.method = init.method ?? src?.method ?? 'GET';
    this.mode = init.mode ?? src?.mode ?? 'no-cors';
    this.headers = new Headers(init.headers ?? (src ? Object.fromEntries(src.headers.map) : {}));
    this.cache = init.cache ?? src?.cache;
    this.credentials = init.credentials ?? src?.credentials;
  }
}

class Res {
  constructor(body, init = {}) {
    this.body = body;
    this.status = init.status ?? 200;
    this.type = init.type ?? 'basic';
    this.headers = new Headers(init.headers ?? {});
  }
  clone() {
    const r = new Res(this.body, { status: this.status, type: this.type });
    r.headers = this.headers;
    return r;
  }
}

/* ---------- load the worker -------------------------------------------- */

function loadWorker({ stamped, fetchImpl }) {
  const source = fs.readFileSync(swPath, 'utf8');
  const code = stamped ? source.replace('__BINOS_BUILD_ID__', 'deadbeefcafe0001') : source;
  const cacheLog = [];
  const listeners = new Map();
  const claimed = { value: false };
  const skipped = { value: false };

  const self = {
    location: new URL('/sw.js', ORIGIN),
    addEventListener: (type, fn) => listeners.set(type, fn),
    skipWaiting: () => {
      skipped.value = true;
    },
    clients: {
      claim: async () => {
        claimed.value = true;
      },
    },
    registration: {},
  };

  const sandbox = {
    self,
    caches: makeCaches(cacheLog),
    fetch: fetchImpl,
    Request: Req,
    Response: Res,
    URL,
    console,
    setTimeout,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: swPath });

  async function dispatch(type, event) {
    const fn = listeners.get(type);
    if (!fn) throw new Error(`no ${type} listener`);
    const waits = [];
    const responses = [];
    const e = {
      ...event,
      waitUntil: (p) => waits.push(p),
      respondWith: (p) => responses.push(p),
    };
    fn(e);
    await Promise.all(waits.map((p) => p.catch(() => {})));
    await Promise.all(responses.map((p) => Promise.resolve(p).catch(() => {})));
    return { responses, handled: responses.length > 0 };
  }

  return { sandbox, dispatch, cacheLog, claimed, skipped, listeners };
}

const okResponse = (url) => new Res(`body of ${url}`, { status: 200 });

/* ---------- the scenarios ---------------------------------------------- */

console.log(`service worker: ${swPath}`);
console.log('');
console.log('A. a stamped worker, online');

{
  const requested = [];
  const w = loadWorker({
    stamped: true,
    fetchImpl: async (request) => {
      requested.push(request.url ?? String(request));
      return okResponse(request.url ?? String(request));
    },
  });

  await w.dispatch('install', {});
  check('install precaches the shell', w.cacheLog.length > 0, `${w.cacheLog.length} entries`);
  check(
    'every precached entry is same-origin and not an API path',
    w.cacheLog.every((e) => e.url.startsWith(ORIGIN) && !new URL(e.url).pathname.startsWith('/api/')),
    JSON.stringify(w.cacheLog.map((e) => e.url)),
  );
  check('the cache name carries the build id', [...w.sandbox.caches.store.keys()].every((k) => k.includes('deadbeefcafe0001')));

  const before = w.cacheLog.length;

  // --- the API must never be touched, in every shape it arrives in --------
  const apiCases = [
    ['cross-origin GET report', new Req('https://api.example.test/api/v1/reports/overview', { method: 'GET', headers: { Authorization: 'Bearer T' } })],
    ['cross-origin POST write', new Req('https://api.example.test/api/v1/receiving', { method: 'POST', headers: { Authorization: 'Bearer T' } })],
    ['same-origin proxied API GET', new Req(`${ORIGIN}/api/v1/auth/context`, { method: 'GET' })],
    ['same-origin proxied API POST', new Req(`${ORIGIN}/api/v1/cash/ops`, { method: 'POST' })],
    ['same-origin GET carrying a token', new Req(`${ORIGIN}/main.dart.js`, { method: 'GET', headers: { Authorization: 'Bearer T' } })],
    ['same-origin non-GET of a shell file', new Req(`${ORIGIN}/index.html`, { method: 'POST' })],
  ];
  for (const [name, request] of apiCases) {
    const r = await w.dispatch('fetch', { request });
    check(`${name}: the worker does not intercept it`, !r.handled);
  }
  check('nothing new was written to the cache by those', w.cacheLog.length === before, JSON.stringify(w.cacheLog.slice(before)));

  // --- the shell IS served and cached ------------------------------------
  const shell = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  check('a plain shell GET is intercepted', shell.handled);
  check('and it is cached', w.cacheLog.some((e) => e.url.endsWith('/main.dart.js')));

  const nav = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/`, { method: 'GET', mode: 'navigate' }) });
  check('a navigation is intercepted (network-first)', nav.handled);

  // --- a no-store response is not cached even when it is same-origin -----
  const w2 = loadWorker({
    stamped: true,
    fetchImpl: async (request) => new Res('private', { status: 200, headers: { 'Cache-Control': 'no-store' } }),
  });
  await w2.dispatch('install', {});
  const beforeNoStore = w2.cacheLog.length;
  await w2.dispatch('fetch', { request: new Req(`${ORIGIN}/assets/AssetManifest.json`, { method: 'GET' }) });
  check('a Cache-Control: no-store response is never stored', w2.cacheLog.length === beforeNoStore);

  // --- activate drops other builds ---------------------------------------
  await w.sandbox.caches.open('binos-shell-oldbuild00000000');
  await w.sandbox.caches.open('someone-elses-cache');
  await w.dispatch('activate', {});
  const names = await w.sandbox.caches.keys();
  check('activate deletes the previous build cache', !names.includes('binos-shell-oldbuild00000000'), JSON.stringify(names));
  check('activate keeps the current build cache', names.some((n) => n.includes('deadbeefcafe0001')));
  check('activate does not touch a cache it does not own', names.includes('someone-elses-cache'));
  check('activate claims the clients', w.claimed.value);

  // --- the update handshake ----------------------------------------------
  const msg = w.listeners.get('message');
  msg({ data: 'SOMETHING_ELSE' });
  check('an unknown message does nothing', !w.skipped.value);
  msg({ data: 'SKIP_WAITING' });
  check('SKIP_WAITING swaps the worker in', w.skipped.value);
}

console.log('');
console.log('B. a stamped worker, offline');

{
  let allowNetwork = true;
  const w = loadWorker({
    stamped: true,
    fetchImpl: async (request) => {
      if (!allowNetwork) throw new TypeError('Failed to fetch');
      return okResponse(request.url ?? String(request));
    },
  });
  await w.dispatch('install', {});
  allowNetwork = false;

  const nav = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/index.html`, { method: 'GET', mode: 'navigate' }) });
  const navBody = await nav.responses[0];
  check('offline, a navigation falls back to the cached shell', navBody instanceof Res && String(navBody.body).includes('index.html'));

  let threw = false;
  const miss = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/never-cached.js`, { method: 'GET' }) });
  await Promise.resolve(miss.responses[0]).catch(() => {
    threw = true;
  });
  check('offline, an uncached asset FAILS instead of being faked', threw);

  const before = w.cacheLog.length;
  const write = await w.dispatch('fetch', { request: new Req('https://api.example.test/api/v1/receiving', { method: 'POST' }) });
  check('offline, a write is not intercepted (never queued)', !write.handled);
  check('offline, a write leaves no trace in the cache', w.cacheLog.length === before);
}

console.log('');
console.log('C. an UNSTAMPED worker (the build step was forgotten)');

{
  const w = loadWorker({ stamped: false, fetchImpl: async (request) => okResponse(request.url ?? String(request)) });
  await w.dispatch('install', {});
  check('it caches nothing at install', w.cacheLog.length === 0);
  const r = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  check('it intercepts nothing', !r.handled);
  await w.sandbox.caches.open('binos-shell-someoldbuild');
  await w.dispatch('activate', {});
  check('it clears every cache of its own prefix', !(await w.sandbox.caches.keys()).includes('binos-shell-someoldbuild'));
}

console.log('E. a cache write can never decide the answer, and the network path is never the HTTP cache');

{
  // The operator's phone is out of storage: `caches.open` rejects. A 200 from
  // the server must still reach the page — the worker used to catch this in
  // the same `try` as the fetch and hand the browser its offline error page.
  const w = loadWorker({ stamped: true, fetchImpl: async (request) => okResponse(request.url) });
  w.sandbox.caches.open = async () => {
    throw new Error('QuotaExceededError');
  };
  const r = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  check('a subresource is served although the cache write failed', r.handled);
  if (r.handled) {
    const res = await r.responses[0].catch((e) => e);
    check('…and it is the real 200, not an error', res instanceof Res && res.status === 200,
      String(res && res.message ? res.message : res));
  }

  const nav = loadWorker({ stamped: true, fetchImpl: async (request) => okResponse(request.url) });
  nav.sandbox.caches.open = async () => {
    throw new Error('QuotaExceededError');
  };
  const rn = await nav.dispatch('fetch', {
    request: new Req(`${ORIGIN}/`, { method: 'GET', mode: 'navigate' }),
  });
  check('the NAVIGATION is served too (the app can still be opened)', rn.handled);
  if (rn.handled) {
    const res = await rn.responses[0].catch((e) => e);
    check('…and it is the real 200', res instanceof Res && res.status === 200,
      String(res && res.message ? res.message : res));
  }
}

{
  // `main.dart.js` carries no content hash: a host serving it with a long
  // max-age would answer the "network-first" path from the browser's HTTP
  // cache with the PREVIOUS build, and the worker would then store that stale
  // bundle. Every network read the worker performs bypasses that cache.
  const modes = [];
  const w = loadWorker({
    stamped: true,
    fetchImpl: async (request) => {
      modes.push({ url: request.url, cache: request.cache, mode: request.mode });
      return okResponse(request.url);
    },
  });
  await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  await w.dispatch('fetch', { request: new Req(`${ORIGIN}/`, { method: 'GET', mode: 'navigate' }) });
  check('every network read bypasses the browser HTTP cache',
    modes.length >= 2 && modes.every((m) => m.cache === 'reload'), JSON.stringify(modes));
  check('the navigation keeps its own URL when it is re-issued',
    modes.some((m) => m.url === `${ORIGIN}/`), JSON.stringify(modes));
}

console.log('');
console.log('F. while an update waits for the operator, the served bundle stays whole');

{
  // Build A is cached and controlling. Build B is installed and WAITING (the
  // operator has not tapped "Yangilash"). Network-first would hand the page
  // build B's main.dart.js next to build A's canvaskit — a bundle that never
  // existed. Everything must come from build A until the swap.
  const served = [];
  const w = loadWorker({
    stamped: true,
    fetchImpl: async (request) => {
      served.push(request.url);
      return new Res(`BUILD-B ${request.url}`, { status: 200 });
    },
  });
  await w.dispatch('install', {});                       // build A fills its cache
  const cache = await w.sandbox.caches.open([...w.sandbox.caches.store.keys()][0]);
  cache.entries.set(`${ORIGIN}/main.dart.js`, new Res('BUILD-A main', { status: 200 }));
  cache.entries.set(`${ORIGIN}/canvaskit/canvaskit.js`, new Res('BUILD-A canvaskit', { status: 200 }));
  served.length = 0;
  w.sandbox.self.registration.waiting = { state: 'installed' };

  const boot = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  const asset = await w.dispatch('fetch', {
    request: new Req(`${ORIGIN}/canvaskit/canvaskit.js`, { method: 'GET' }),
  });
  const bootBody = boot.handled ? (await boot.responses[0]).body : '(not handled)';
  const assetBody = asset.handled ? (await asset.responses[0]).body : '(not handled)';
  check('the boot file comes from the SAME build as the assets',
    bootBody === 'BUILD-A main' && assetBody === 'BUILD-A canvaskit', `${bootBody} | ${assetBody}`);
  check('and the next build is not fetched behind the operator’s back', served.length === 0,
    JSON.stringify(served));

  // No pending swap: the boot file is network-first again (the normal path).
  delete w.sandbox.self.registration.waiting;
  const after = await w.dispatch('fetch', { request: new Req(`${ORIGIN}/main.dart.js`, { method: 'GET' }) });
  const afterBody = after.handled ? (await after.responses[0]).body : '(not handled)';
  check('once nothing is waiting, the boot file is network-first again',
    afterBody === `BUILD-B ${ORIGIN}/main.dart.js`, String(afterBody));
}

console.log('');
console.log(`${checks - failures}/${checks} checks passed`);
process.exit(failures ? 1 : 0);
