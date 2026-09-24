// C1 (Phase 5G.1) — the PWA bridge for iPhone: the `web/` scaffold is
// production-grade, not the `flutter create` placeholder.
//
// What this pins:
//  * the installed app is branded exactly like the Android build (same label,
//    same brand colour) — no invented second brand;
//  * every manifest/meta tag iOS needs for a Home-Screen install is present;
//  * NOTHING under `web/` points at a third-party origin. The PWA must not
//    execute or fetch anything from unpkg / gstatic / any CDN at run time,
//    which is what makes a `script-src 'self'` posture possible at all;
//  * the ZXing barcode library `mobile_scanner` would otherwise pull from
//    `https://unpkg.com/@zxing/library@0.19.1` at run time is vendored,
//    version- and hash-pinned, and pre-loaded under the exact script id the
//    plugin looks for, so the plugin never injects the remote one.
//
// VM only: reads repo files.
@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

/// The version of `@zxing/library` `mobile_scanner` 5.2.3 hardcodes in
/// `lib/src/web/zxing/zxing_barcode_reader.dart` (`scriptUrl`). The vendored
/// copy must be that exact version, or scanning behaves differently on the
/// PWA than the plugin was tested against.
const zxingVersion = '0.19.1';

/// Origins the built PWA must never talk to.
const forbiddenHosts = ['unpkg.com', 'gstatic.com', 'googleapis.com', 'jsdelivr.net', 'cdnjs.cloudflare.com'];

File _f(String p) => File(p);

String _read(String p) => _f(p).readAsStringSync();

/// (width, height) of a PNG, from its IHDR header.
(int, int) _pngSize(String path) {
  final b = _f(path).readAsBytesSync();
  expect(b.length, greaterThan(24), reason: '$path is not a PNG');
  expect(b.sublist(1, 4), [0x50, 0x4E, 0x47], reason: '$path is not a PNG');
  int be32(int o) => (b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3];
  return (be32(16), be32(20));
}

/// Every `src="…"` / `href="…"` value in [html].
List<String> _urlAttrs(String html) => [
      for (final m in RegExp(r'(?:src|href)\s*=\s*"([^"]*)"').allMatches(html)) m[1]!,
    ];

void main() {
  group('the web scaffold exists and is ours, not the Flutter placeholder', () {
    test('web/ carries index.html, manifest.json and a service worker', () {
      expect(_f('web/index.html').existsSync(), isTrue, reason: 'flutter build web needs web/index.html');
      expect(_f('web/manifest.json').existsSync(), isTrue);
      expect(_f('web/sw.js').existsSync(), isTrue, reason: 'Flutter 3.44 ships only a self-unregistering stub');
    });

    test('nothing of "A new Flutter project" survives', () {
      for (final p in ['web/index.html', 'web/manifest.json']) {
        expect(_read(p), isNot(contains('A new Flutter project')), reason: p);
        expect(_read(p), isNot(contains('savdoos_mobile')), reason: '$p still uses the pub package name as a title');
      }
    });

    test('enabling web left .metadata and pubspec.lock alone (CI runs --enforce-lockfile)', () {
      // `flutter create --platforms=web .` drops the `ios` entry from .metadata
      // and rewrites pubspec.lock (20 transitive bumps + CRLF->LF). The web
      // scaffold here is hand-authored precisely so neither happens.
      final meta = _read('.metadata');
      expect(meta, contains('platform: ios'), reason: 'the iOS migration record must survive enabling web');
      expect(meta, isNot(contains('platform: web')), reason: '.metadata must stay byte-identical to 33ea7b1');
      expect(_read('pubspec.lock'), contains('flutter_secure_storage_web'), reason: 'lock untouched, web deps already resolved');
    });
  });

  group('brand: the PWA is the same app as the Android build', () {
    late Map<String, dynamic> manifest;
    late String androidLabel;
    late String brandColour;

    setUp(() {
      manifest = (jsonDecode(_read('web/manifest.json')) as Map).cast<String, dynamic>();
      final androidManifest = _read('android/app/src/main/AndroidManifest.xml');
      final labels = RegExp(r'android:label="([^"]+)"').allMatches(androidManifest).toList();
      expect(labels, hasLength(1), reason: 'the launcher label must stay the single label in the manifest');
      androidLabel = labels.single[1]!;
      brandColour = RegExp(r'adaptive_icon_background:\s*"([^"]+)"').firstMatch(_read('pubspec.yaml'))![1]!;
    });

    test('short_name is the Android launcher label, verbatim', () {
      expect(manifest['short_name'], androidLabel);
      expect('${manifest['name']}', startsWith(androidLabel));
    });

    test('theme and background colours are the Android adaptive-icon brand colour', () {
      expect('${manifest['theme_color']}'.toUpperCase(), brandColour.toUpperCase());
      expect('${manifest['background_color']}'.toUpperCase(), brandColour.toUpperCase());
      expect(brandColour.toUpperCase(), isNot('#0175C2'), reason: 'Flutter blue is not this product');
    });

    test('index.html carries the same title, theme colour and app title as the manifest', () {
      final html = _read('web/index.html');
      expect(RegExp(r'<title>([^<]+)</title>').firstMatch(html)![1], androidLabel);
      expect(html, contains('<meta name="apple-mobile-web-app-title" content="$androidLabel">'));
      expect(html.toUpperCase(), contains('<META NAME="THEME-COLOR" CONTENT="${brandColour.toUpperCase()}">'));
    });
  });

  group('manifest: installable as a standalone iPhone app', () {
    late Map<String, dynamic> m;

    setUp(() => m = (jsonDecode(_read('web/manifest.json')) as Map).cast<String, dynamic>());

    test('display, scope, start_url and orientation are set for a Home-Screen app', () {
      expect(m['display'], 'standalone');
      expect(m['start_url'], isNotNull);
      expect('${m['start_url']}', isNot(startsWith('http')), reason: 'start_url must be relative to the deploy path');
      expect(m['scope'], isNotNull);
      expect('${m['scope']}', isNot(startsWith('http')));
      expect(m['orientation'], 'portrait');
      expect('${m['description']}'.trim(), isNotEmpty);
      expect(m['lang'], isNotNull);
    });

    test('icons: 192 and 512, each in "any" and "maskable", and each file is really that size', () {
      final icons = [for (final i in (m['icons'] as List)) (i as Map).cast<String, dynamic>()];
      final got = {for (final i in icons) '${i['sizes']} ${i['purpose']}'};
      expect(got, containsAll(['192x192 any', '512x512 any', '192x192 maskable', '512x512 maskable']));
      for (final i in icons) {
        final src = 'web/${i['src']}';
        expect(_f(src).existsSync(), isTrue, reason: 'missing icon $src');
        final side = int.parse('${i['sizes']}'.split('x').first);
        expect(_pngSize(src), (side, side), reason: '$src is not ${i['sizes']}');
        expect(i['type'], 'image/png');
      }
    });
  });

  group('index.html: the iOS Home-Screen meta tags', () {
    late String html;

    setUp(() => html = _read('web/index.html'));

    test('viewport covers the notch so SafeArea gets real insets', () {
      final vp = RegExp(r'<meta name="viewport" content="([^"]+)"').firstMatch(html)?[1];
      expect(vp, isNotNull, reason: 'standalone mode has no browser chrome — the viewport must be explicit');
      expect(vp, contains('viewport-fit=cover'));
      expect(vp, contains('width=device-width'));
    });

    test('both the modern and the legacy Apple standalone flags are present', () {
      expect(html, contains('<meta name="mobile-web-app-capable" content="yes">'));
      expect(html, contains('<meta name="apple-mobile-web-app-capable" content="yes">'),
          reason: 'older iOS reads only the Apple-prefixed one');
      expect(html, contains('apple-mobile-web-app-status-bar-style'));
    });

    test('an Apple touch icon is linked and is a real 180px PNG', () {
      final href = RegExp(r'<link rel="apple-touch-icon"[^>]*href="([^"]+)"').firstMatch(html)?[1];
      expect(href, isNotNull, reason: 'iOS uses this for the Home-Screen tile');
      expect(_pngSize('web/$href'), (180, 180));
    });

    test('the manifest is linked', () => expect(html, contains('rel="manifest"')));

    test('the web build never claims Face ID or biometrics', () {
      expect(html.toLowerCase(), isNot(contains('face id')));
      expect(html.toLowerCase(), isNot(contains('touch id')));
    });
  });

  group('no third-party CDN at run time', () {
    test('no file the browser loads mentions a CDN host', () {
      // `provenance.json` is documentation: it records the unpkg URL this
      // vendoring REPLACES. Nothing loads it, and the next test proves it is
      // never referenced from the page or precached.
      const documentation = {'web/vendor/zxing/provenance.json'};
      final problems = <String>[];
      for (final f in Directory('web').listSync(recursive: true).whereType<File>()) {
        final p = f.path.replaceAll('\\', '/');
        if (p.endsWith('.png') || p.endsWith('.ico') || documentation.contains(p)) continue;
        final src = f.readAsStringSync();
        for (final h in forbiddenHosts) {
          if (src.contains(h)) problems.add('$p -> $h');
        }
      }
      expect(problems, isEmpty, reason: problems.join('\n'));
    });

    test('the documentation file is never loaded by the page or the worker', () {
      // It may be NAMED in a comment (that is the point of documentation);
      // it must never be fetched.
      expect(_urlAttrs(_read('web/index.html')).where((u) => u.contains('provenance')), isEmpty);
      final precache = RegExp(r'"precache":\s*\[([^\]]*)\]').firstMatch(_read('web/sw.js'))![1];
      expect(precache, isNot(contains('provenance')));
      expect(_read('web/pwa.js'), isNot(contains('provenance.json')));
    });

    test('every src/href in index.html is same-origin relative', () {
      final bad = _urlAttrs(_read('web/index.html'))
          .where((u) => u.startsWith('http://') || u.startsWith('https://') || u.startsWith('//'))
          .toList();
      expect(bad, isEmpty, reason: 'off-origin asset: $bad');
    });

    test('a Content-Security-Policy is declared and allows no foreign script origin', () {
      final html = _read('web/index.html');
      final csp = RegExp(r'http-equiv="Content-Security-Policy" content="([^"]+)"').firstMatch(html)?[1];
      expect(csp, isNotNull, reason: 'the CSP is what turns "we self-host" into an enforced rule');
      expect(csp, contains("default-src 'self'"));
      expect(csp, contains("object-src 'none'"));
      expect(csp, contains("base-uri 'none'"));
      final scriptSrc = RegExp(r"script-src ([^;]+)").firstMatch(csp!)?[1] ?? '';
      expect(scriptSrc, contains("'self'"));
      expect(scriptSrc, isNot(contains('http')), reason: 'no remote script origin may be allowlisted');
    });
  });

  group('ZXing is vendored, pinned and pre-loaded (mobile_scanner never reaches unpkg)', () {
    late Map<String, dynamic> prov;

    setUp(() => prov = (jsonDecode(_read('web/vendor/zxing/provenance.json')) as Map).cast<String, dynamic>());

    test('the vendored file is the exact npm artifact unpkg would have served', () {
      expect(prov['version'], zxingVersion);
      expect(prov['package'], '@zxing/library');
      expect(prov['npm_field'], 'unpkg', reason: 'https://unpkg.com/@zxing/library@x resolves to the "unpkg" field');
      final file = 'web/vendor/zxing/${prov['file']}';
      final bytes = _f(file).readAsBytesSync();
      expect(sha256.convert(bytes).toString(), prov['sha256'], reason: 'vendored $file does not match its pin');
      expect(bytes.length, prov['bytes']);
    });

    test('it defines the ZXing global the plugin binds to', () {
      final src = _read('web/vendor/zxing/${prov['file']}');
      expect(src, contains('ZXing'), reason: 'mobile_scanner binds @JS("ZXing.BrowserMultiFormatReader")');
    });

    test('index.html pre-loads it under the plugin script id, synchronously, before Flutter boots', () {
      final html = _read('web/index.html');
      // barcode_reader.dart: `if (document.querySelector('script#mobile-scanner-barcode-reader') != null) return;`
      final tag = RegExp(r'<script[^>]*id="mobile-scanner-barcode-reader"[^>]*>').firstMatch(html)?[0];
      expect(tag, isNotNull, reason: 'without this id the plugin injects the unpkg script itself');
      expect(tag, contains('vendor/zxing/'));
      expect(tag, isNot(contains('async')), reason: 'the plugin only checks the tag exists, not that it ran');
      expect(tag, isNot(contains('defer')), reason: 'ZXing must be defined before any Dart code can scan');
      expect(html.indexOf(tag!), lessThan(html.indexOf('<script src="flutter_bootstrap.js"')));
    });
  });

  group('the web token policy is visible to the operator', () {
    test('the boot screen says the browser build signs you out when it is closed', () {
      final html = _read('web/index.html');
      expect(html, contains('binos-session-notice'),
          reason: 'SecretStore on web is session-scoped; the operator must be told before they rely on it');
    });
  });
}
