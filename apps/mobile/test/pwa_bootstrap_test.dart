// C1 (Phase 5G.1) — the PWA boot path: who starts the engine, and who is
// allowed to register a service worker.
//
// Why this file exists — a measured hazard, not a style rule.
//
// `flutter build web` generates `flutter_bootstrap.js` from a template. The
// DEFAULT template (flutter_tools `lib/src/web/bootstrap.dart`,
// `generateDefaultFlutterBootstrapScript`) calls:
//
//     _flutter.loader.load({ serviceWorkerSettings: { serviceWorkerVersion: … } });
//
// and `flutter.js` then does (read from the built `flutter.js` of this very
// build, minified, reformatted here):
//
//     loadServiceWorker(e) {
//       if (!e || !("serviceWorker" in navigator)) return Promise.resolve();
//       let t = () => { ... navigator.serviceWorker.register(`flutter_service_worker.js?v=${r}`) ... };
//       return e.serviceWorkerUrl != null
//           ? (warn(), t())
//           : navigator.serviceWorker.getRegistration().then(r => r ? t() : Promise.resolve());
//     }
//
// Read the last line carefully. With only a `serviceWorkerVersion` (no
// `serviceWorkerUrl`), it registers Flutter's own worker **whenever a
// registration already exists**. Ours does exist from the second visit on —
// `web/pwa.js` registers `sw.js` at the same `/` scope — so Flutter's script
// would REPLACE our worker at that scope. And Flutter's 3.44 worker is the
// self-unregistering stub: it `skipWaiting()`s, then on activate unregisters
// itself and reloads every client. The PWA would therefore, on a return
// visit, throw away the offline shell and force a reload — possibly under an
// operator in the middle of a receiving document.
//
// So the repo owns `web/flutter_bootstrap.js` and never asks for that
// behaviour. `scripts/pwa_postbuild.mjs` re-checks it on the ARTEFACT, so a
// build made with the wrong flags fails instead of shipping.
//
// VM only: reads repo files.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String p) => File(p).readAsStringSync();

/// Repo root, from `apps/mobile` (where `flutter test` runs).
String _repo(String p) => '../../$p';

/// [source] with its comments removed, so "this file must not do X" can be
/// asserted on what the browser executes without forbidding the file from
/// EXPLAINING why it does not do X. (Every rule here is one a future reader
/// needs the reasoning for, and a test that punishes documentation would get
/// the documentation deleted.)
String _code(String source) {
  final withoutBlocks = source
      .replaceAll(RegExp(r'/\*.*?\*/', dotAll: true), '')
      .replaceAll(RegExp(r'<!--.*?-->', dotAll: true), '');
  return [
    for (final line in withoutBlocks.split('\n'))
      if (!line.trimLeft().startsWith('//')) line,
  ].join('\n');
}

void main() {
  group('the repo owns the loader call (web/flutter_bootstrap.js)', () {
    test('the template exists', () {
      expect(
        File('web/flutter_bootstrap.js').existsSync(),
        isTrue,
        reason: 'without it the tool generates the default bootstrap, which asks flutter.js '
            'to register flutter_service_worker.js over our own worker',
      );
    });

    test('it is a template over the toolchain, not a copy of the loader', () {
      final js = _read('web/flutter_bootstrap.js');
      expect(js, contains('{{flutter_js}}'), reason: 'flutter.js must come from the pinned SDK');
      expect(js, contains('{{flutter_build_config}}'),
          reason: 'the build config carries useLocalCanvasKit — dropping it sends CanvasKit back to gstatic');
      expect(js, contains('_flutter.loader.load'));
    });

    test('it never asks flutter.js to register a service worker', () {
      final js = _code(_read('web/flutter_bootstrap.js'));
      expect(js, isNot(contains('serviceWorkerSettings')),
          reason: 'that is what makes flutter.js replace our sw.js with its self-unregistering stub');
      expect(js, isNot(contains('{{flutter_service_worker_version}}')));
      expect(js, isNot(contains('flutter_service_worker.js')));
    });

    test('exactly one file registers a worker, and it registers ours', () {
      final registrars = <String>[
        for (final f in Directory('web').listSync(recursive: true).whereType<File>())
          if (f.path.endsWith('.js') || f.path.endsWith('.html'))
            if (_code(f.readAsStringSync()).contains('serviceWorker.register')) f.path.replaceAll(r'\', '/'),
      ];
      expect(registrars, ['web/pwa.js']);
      expect(_code(_read('web/pwa.js')), contains("register('sw.js')"));
    });

    test('index.html boots through that bootstrap', () {
      expect(_read('web/index.html'), contains('src="flutter_bootstrap.js"'));
    });
  });

  group('the PWA files point at build helpers that really exist', () {
    test('every scripts/… path named in web/ and in the README is a real file', () {
      final named = <String, Set<String>>{};
      final sources = <String>[
        'README.md',
        for (final f in Directory('web').listSync(recursive: true).whereType<File>())
          if (f.path.endsWith('.js') || f.path.endsWith('.html') || f.path.endsWith('.json')) f.path,
      ];
      for (final src in sources) {
        for (final m in RegExp(r'scripts/[A-Za-z0-9_.-]+').allMatches(_read(src))) {
          named.putIfAbsent(m[0]!, () => <String>{}).add(src.replaceAll(r'\', '/'));
        }
      }
      expect(named, isNotEmpty, reason: 'the build step must be documented somewhere');
      final missing = <String>[
        for (final e in named.entries)
          if (!File(_repo(e.key)).existsSync()) '${e.key} (named in ${e.value.join(", ")})',
      ];
      expect(missing, isEmpty,
          reason: 'a build step named in the docs but absent from the repo is a step nobody can run');
    });
  });
}
