#!/usr/bin/env node
/*
 * Post-build step for the SavdoOS PWA (Phase 5G.1, package C1).
 *
 *   node scripts/pwa_postbuild.mjs [--dir <build/web>] [--json]
 *
 * It does three things, and `flutter build web` does none of them:
 *
 *  1. STAMPS the service worker. `web/sw.js` ships with the placeholder
 *     `__BINOS_BUILD_ID__`; until it is replaced the worker runs INERT (caches
 *     nothing, passes everything through). This computes a content hash over
 *     the whole build and writes it in, so the shell cache name changes exactly
 *     when the build changes — identical inputs give an identical token, a
 *     changed bundle gives a new one, and `activate` drops every other build's
 *     cache. A forgotten stamp costs the offline shell, never a stale answer.
 *
 *  2. VERIFIES the "no third-party CDN at run time" rule on the ARTEFACT, not
 *     on the source: the boot path (index.html, flutter_bootstrap.js,
 *     flutter.js, pwa.js, sw.js, manifest.json) must contain no CDN URL, and
 *     `canvaskit/` must be present locally. It also reports CDN strings that
 *     survive inside `main.dart.js`, because those are real (see the note it
 *     prints) — they are reported rather than hidden.
 *
 *  3. MEASURES the payload, raw and gzip, so the number in the report is a
 *     number somebody took.
 *
 * Exit code 1 if a rule is broken.
 */

import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const asJson = args.includes('--json');
const dirArg = args.indexOf('--dir');
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const buildDir = path.resolve(dirArg === -1 ? path.join(repoRoot, 'apps/mobile/build/web') : args[dirArg + 1]);

const PLACEHOLDER = '__BINOS_BUILD_ID__';
const CDN_HOSTS = ['unpkg.com', 'gstatic.com', 'googleapis.com', 'jsdelivr.net', 'cdnjs.cloudflare.com'];
// The files a cold start actually executes before any Dart code runs.
const BOOT_PATH = ['index.html', 'flutter_bootstrap.js', 'flutter.js', 'pwa.js', 'sw.js', 'manifest.json'];
const TEXT = /\.(js|json|html|css|txt|map|wasm\.map)$/i;

const problems = [];
const out = { buildDir };

function walk(dir, base = dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(full, base));
    else files.push(path.relative(base, full).split(path.sep).join('/'));
  }
  return files.sort();
}

if (!fs.existsSync(buildDir)) {
  console.error(`no build at ${buildDir} — run: flutter build web --release --no-web-resources-cdn`);
  process.exit(1);
}

/* ---------- 0. the Flutter service worker, before anything else --------- */

// `--pwa-strategy=none` still WRITES `flutter_service_worker.js`, it just
// writes it empty (measured: 0 bytes). An empty worker is a valid worker: if
// anything ever registered it at `/`, it would replace ours and control the
// page with no fetch handler at all — the offline shell gone, and nothing on
// screen to say so. Nothing in this build registers it (our
// `web/flutter_bootstrap.js` never passes `serviceWorkerSettings`), but a file
// that exists only to be registered over our worker has no business shipping,
// so it is removed here — before the build is hashed, so the id stays
// deterministic. A NON-empty one means the strategy flag was forgotten: that
// is left in place and failed on, loudly.
const flutterStub = path.join(buildDir, 'flutter_service_worker.js');
out.flutterStub = 'absent';
if (fs.existsSync(flutterStub)) {
  if (fs.statSync(flutterStub).size === 0) {
    fs.unlinkSync(flutterStub);
    out.flutterStub = 'removed (was empty)';
  } else {
    out.flutterStub = `PRESENT (${fs.statSync(flutterStub).size} B)`;
  }
}

const files = walk(buildDir);

/* ---------- 1. stamp ---------------------------------------------------- */

// Hash every built file except the two this script writes, so re-running it on
// the same build yields the SAME id (determinism) while any change to the
// bundle yields a new one.
const OWN_OUTPUT = new Set(['sw.js', 'binos-build-id.txt']);
const manifest = createHash('sha256');
for (const rel of files) {
  if (OWN_OUTPUT.has(rel)) continue;
  manifest.update(rel);
  manifest.update('\0');
  manifest.update(createHash('sha256').update(fs.readFileSync(path.join(buildDir, rel))).digest());
}
const buildId = manifest.digest('hex').slice(0, 16);
out.buildId = buildId;

// Stamp from the PRISTINE source worker, never from the built copy, so the
// script is idempotent and a second run cannot double-stamp or lose the
// placeholder.
const swSource = path.join(repoRoot, 'apps/mobile/web/sw.js');
const swPath = path.join(buildDir, 'sw.js');
if (!fs.existsSync(swSource)) {
  problems.push(`missing ${swSource}`);
} else if (!fs.existsSync(swPath)) {
  problems.push('sw.js is missing from the build — web/sw.js was not copied by flutter build web');
} else {
  const sw = fs.readFileSync(swSource, 'utf8');
  const occurrences = sw.split(PLACEHOLDER).length - 1;
  if (occurrences !== 1) {
    problems.push(`web/sw.js contains the build-id placeholder ${occurrences} times, expected exactly 1`);
  } else {
    fs.writeFileSync(swPath, sw.replace(PLACEHOLDER, buildId), 'utf8');
    fs.writeFileSync(path.join(buildDir, 'binos-build-id.txt'), buildId + '\n', 'utf8');
    const stamped = fs.readFileSync(swPath, 'utf8');
    if (!stamped.includes(`"buildId": "${buildId}"`)) problems.push('sw.js stamp did not take');
    // The INERT self-check is written in two pieces so the stamp cannot erase it.
    if (!stamped.includes("'__BINOS' + '_BUILD_ID__'")) problems.push('sw.js lost its INERT self-check');

    // Every precached path must be IN this build. A shell entry that 404s does
    // not fail the install (the worker swallows it on purpose, so one missing
    // asset never costs the app), which is exactly why nobody would notice the
    // offline shell quietly losing a file. Notice it here instead.
    const precache = /"precache"\s*:\s*\[([^\]]*)\]/.exec(sw);
    if (!precache) {
      problems.push('web/sw.js has no readable precache list');
    } else {
      const entries = [...precache[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
      out.precache = entries;
      const absent = entries.filter((e) => e !== './' && !files.includes(e));
      if (absent.length) {
        problems.push(`sw.js precaches paths that are not in the build: ${absent.join(', ')}`);
      }
    }
  }
}

/* ---------- 2. verify --------------------------------------------------- */

// `flutter.js` / `flutter_bootstrap.js` carry the gstatic CanvasKit URL inside
// the branch they take when `useLocalCanvasKit` is false:
//
//   ...e.engineRevision && !e.useLocalCanvasKit ? I("https://www.gstatic.com/flutter-canvaskit", ...) : "canvaskit"
//
// `--no-web-resources-cdn` sets `"useLocalCanvasKit":true` in the build config,
// so that branch is dead and the engine is loaded from `canvaskit/` on this
// origin. The check is therefore: the flag must be ON (a build without
// `--no-web-resources-cdn` FAILS here) — and the dead string is tolerated only
// in those two loader files, never in the files we author.
const bootstrap = fs.existsSync(path.join(buildDir, 'flutter_bootstrap.js'))
  ? fs.readFileSync(path.join(buildDir, 'flutter_bootstrap.js'), 'utf8')
  : '';
// Read the BUILD CONFIG, not the file. The built bootstrap is
// [our template's comment] + [flutter.js] + [build config] + [our loader call],
// and our own comment above explains the flag by quoting it verbatim — so a
// regex over the whole file matched the COMMENT and went green for a build cut
// WITHOUT `--no-web-resources-cdn` (flutter_tools omits the key entirely then,
// and `canvaskit/` is copied either way, so no other check caught it). That
// build boots CanvasKit from gstatic: dead on a locked-down network, and a
// third party in the boot path of a shop's app.
const cfgStart = bootstrap.lastIndexOf('_flutter.buildConfig');
const cfgEnd = cfgStart < 0 ? -1 : bootstrap.indexOf('_flutter.loader', cfgStart);
const buildConfig = cfgStart < 0 ? '' : bootstrap.slice(cfgStart, cfgEnd > cfgStart ? cfgEnd : undefined);
const localCanvasKit = /"useLocalCanvasKit"\s*:\s*true/.test(buildConfig);
out.useLocalCanvasKit = localCanvasKit;
if (!localCanvasKit) {
  problems.push('useLocalCanvasKit is not true — rebuild with --no-web-resources-cdn or CanvasKit loads from gstatic');
}
const loaderFiles = new Set(['flutter.js', 'flutter_bootstrap.js']);

for (const rel of BOOT_PATH) {
  const full = path.join(buildDir, rel);
  if (!fs.existsSync(full)) {
    problems.push(`boot file missing from the build: ${rel}`);
    continue;
  }
  const src = fs.readFileSync(full, 'utf8');
  for (const host of CDN_HOSTS) {
    if (!src.includes(host)) continue;
    if (loaderFiles.has(rel) && host === 'gstatic.com' && localCanvasKit) {
      out.deadCdnBranch = (out.deadCdnBranch ?? []).concat(`${rel} -> ${host} (unreachable: useLocalCanvasKit=true)`);
      continue;
    }
    problems.push(`${rel} references ${host} — the boot path must be self-hosted`);
  }
}

if (!files.some((f) => f.startsWith('canvaskit/'))) {
  problems.push('canvaskit/ is not in the build — CanvasKit would be fetched from a CDN at run time');
}

const maps = files.filter((f) => f.endsWith('.map'));
if (maps.length) problems.push(`source maps shipped: ${maps.join(', ')}`);

if (!files.includes('vendor/zxing/zxing-0.19.1.min.js')) {
  problems.push('the vendored ZXing bundle is not in the build — scanning would fall back to the CDN');
}

// ONE worker, and it is ours. With `serviceWorkerSettings` in the bootstrap,
// `flutter.js` registers `flutter_service_worker.js` at the same `/` scope on
// every visit where a registration already exists (i.e. every return visit
// once `pwa.js` has registered `sw.js`) — and Flutter 3.44's worker is the
// self-unregistering stub, so the PWA would drop its offline shell and force a
// reload under whoever is using it. `web/flutter_bootstrap.js` never asks for
// it and `--pwa-strategy=none` stops the stub being emitted at all; this is
// the check on the artefact, where a forgotten flag actually shows up.
// Read the LOADER CALL, not the file. The built bootstrap is
// [our template's comment] + [flutter.js] + [build config] + [our call], and
// both of the first two legitimately contain the words below — flutter.js
// because it implements `serviceWorkerSettings`, our comment because it
// explains why we do not pass it. The call is everything after the build
// config assignment, with line comments dropped (that tail is our own code).
const loaderCall = bootstrap
  .slice(bootstrap.lastIndexOf('_flutter.buildConfig'))
  .split('\n')
  .filter((line) => !line.trimStart().startsWith('//'))
  .join('\n');
out.loaderCall = (/_flutter\.loader\.load\s*\([^]*?\)\s*;/.exec(loaderCall) ?? ['(not found)'])[0].trim();

out.serviceWorker = { ownBootstrap: false, flutterStub: out.flutterStub };
if (loaderCall.includes('serviceWorkerSettings')) {
  problems.push(
    'flutter_bootstrap.js asks flutter.js to manage a service worker — it would replace web/sw.js ' +
      'with the self-unregistering stub; build with --pwa-strategy=none and keep web/flutter_bootstrap.js',
  );
} else {
  out.serviceWorker.ownBootstrap = true;
}
if (out.flutterStub.startsWith('PRESENT')) {
  problems.push(
    `flutter_service_worker.js is in the build (${out.flutterStub}) — rebuild with --pwa-strategy=none ` +
      'so the deprecated stub cannot be registered over web/sw.js',
  );
}
if (!files.includes('sw.js')) problems.push('sw.js is not in the build');

// FONTS — reported, never silently accepted. `--no-web-resources-cdn` covers
// the CanvasKit ENGINE, not the fonts it downloads for glyphs no bundled font
// has. The engine's base URL is `configuration.fontFallbackBaseUrl`, settable
// from the bootstrap's `_flutter.loader.load({config: {...}})`; while it is
// unset, the base stays `https://fonts.gstatic.com/s/` and a session fetches
// Roboto (and Noto for `→ ✓ 👍`) from Google. That is a privacy/offline gap,
// not a supply-chain one (fonts are data, not script), and it is stated in
// README.md ("Shriftlar") rather than hidden.
const fontBase = /fontFallbackBaseUrl\s*:\s*["']([^"']+)["']/.exec(loaderCall);
out.fontFallbackBaseUrl = fontBase ? fontBase[1] : 'https://fonts.gstatic.com/s/ (engine default)';
out.fontsSelfHosted = Boolean(fontBase) && !/^https?:/i.test(fontBase[1]);

// Honest reporting rather than a failure: Dart-level CDN strings.
out.cdnStringsInAppBundle = [];
for (const rel of files.filter((f) => TEXT.test(f) && !BOOT_PATH.includes(f) && f.endsWith('.js'))) {
  const src = fs.readFileSync(path.join(buildDir, rel), 'utf8');
  for (const host of CDN_HOSTS) {
    if (src.includes(host)) out.cdnStringsInAppBundle.push(`${rel} -> ${host}`);
  }
}

/* ---------- 3. measure -------------------------------------------------- */

function sizes(rel) {
  const full = path.join(buildDir, rel);
  if (!fs.existsSync(full)) return null;
  const raw = fs.readFileSync(full);
  return { file: rel, raw: raw.length, gzip: gzipSync(raw, { level: 9 }).length };
}

const interesting = [
  'main.dart.js',
  'flutter_bootstrap.js',
  'flutter.js',
  'pwa.js',
  'sw.js',
  'index.html',
  'vendor/zxing/zxing-0.19.1.min.js',
  'canvaskit/canvaskit.js',
  'canvaskit/canvaskit.wasm',
  'canvaskit/chromium/canvaskit.wasm',
  'assets/NOTICES',
];
out.artefacts = interesting.map(sizes).filter(Boolean);

let totalRaw = 0;
for (const rel of files) totalRaw += fs.statSync(path.join(buildDir, rel)).size;
out.totalFiles = files.length;
out.totalRaw = totalRaw;

// The iPhone cold start: Safari has neither Intl.v8BreakIterator nor
// ImageDecoder, so it takes the FULL canvaskit variant, not chromium/.
const pick = (rel) => out.artefacts.find((a) => a.file === rel);
const coldStart = ['index.html', 'flutter_bootstrap.js', 'main.dart.js', 'canvaskit/canvaskit.js', 'canvaskit/canvaskit.wasm', 'vendor/zxing/zxing-0.19.1.min.js', 'pwa.js'];
out.iosColdStartGzip = coldStart.reduce((sum, rel) => sum + (pick(rel)?.gzip ?? 0), 0);
out.iosColdStartParts = coldStart;

out.problems = problems;

/* ---------- report ------------------------------------------------------ */

if (asJson) {
  console.log(JSON.stringify(out, null, 2));
} else {
  const kb = (n) => (n / 1024).toFixed(1).padStart(9) + ' KiB';
  console.log(`build   ${buildDir}`);
  console.log(`buildId ${buildId}   (${files.length} files, ${(totalRaw / 1048576).toFixed(1)} MiB on disk)`);
  console.log('');
  console.log('artefact                                   raw          gzip');
  for (const a of out.artefacts) console.log(`${a.file.padEnd(38)}${kb(a.raw)}  ${kb(a.gzip)}`);
  console.log('');
  console.log(`iPhone/Safari cold start (gzip):      ${kb(out.iosColdStartGzip)}`);
  console.log(`useLocalCanvasKit:                    ${out.useLocalCanvasKit}`);
  console.log(
    `service worker:                       ${out.serviceWorker.ownBootstrap ? 'ours only (web/sw.js)' : 'FLUTTER-MANAGED — see below'}` +
      ` · flutter_service_worker.js: ${out.flutterStub}`,
  );
  console.log(`loader call:                          ${out.loaderCall}`);
  console.log(`font fallback base:                   ${out.fontFallbackBaseUrl}`);
  for (const d of out.deadCdnBranch ?? []) console.log(`dead CDN branch in the loader:        ${d}`);
  if (out.cdnStringsInAppBundle.length) {
    console.log('');
    console.log('CDN strings inside the compiled app (NOT the boot path):');
    for (const s of out.cdnStringsInAppBundle) console.log(`  ${s}`);
    console.log('  These are Dart string constants, not boot-time requests. The known one is');
    console.log('  printing/PdfGoogleFonts in lib/report_export.dart, which downloads a font when');
    console.log('  a PDF is exported — already true on Android today, not a web regression.');
  }
  console.log('');
  if (problems.length) {
    console.log('FAILED:');
    for (const p of problems) console.log(`  - ${p}`);
  } else {
    console.log('OK: stamped, self-hosted boot path, no source maps, ZXing vendored.');
  }
}

process.exit(problems.length ? 1 : 0);
