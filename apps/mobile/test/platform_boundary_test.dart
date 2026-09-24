// Architecture guard (B4 goal): platform plugins are reached ONLY through
// `lib/platform/**`. Business files and screens never import a plugin or
// `dart:io`, and platform selection happens by conditional import, never by
// scattered `kIsWeb` checks. The test support layer is platform-neutral so the
// same suite can run under `flutter test --platform chrome`.
// VM only: scans lib/ and test/support sources for imports.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

const _plugins = [
  'package:flutter_secure_storage/',
  'package:path_provider/',
  'package:local_auth/',
  'package:mobile_scanner/',
  'package:share_plus/',
  'package:image_picker/',
  'package:package_info_plus/',
];

/// Files whose platform touchpoints B4 moved behind adapters.
const _adapted = [
  'lib/api.dart',
  'lib/lock.dart',
  'lib/scan.dart',
  'lib/report_export.dart',
  'lib/screens/barcode_scan_screen.dart',
  'lib/screens/receiving_home_screen.dart',
  'lib/screens/settings_screen.dart',
];

List<String> _imports(String path) => [
      for (final m in RegExp(r"^\s*(?:import|export)\s+'([^']+)'", multiLine: true).allMatches(File(path).readAsStringSync()))
        m[1]!,
    ];

Iterable<File> _dart(String dir) =>
    Directory(dir).listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));

String _rel(File f) => f.path.replaceAll('\\', '/');

/// Touchpoints B4 could NOT move because the files belong to other packages.
/// This list only SHRINKS: the owners were asked to (a) point
/// `receiptShare`'s default at `Sharing.instance.text` and (b) drop the dead
/// `dart:io` type tests in `isConnectivityError` (web never throws them).
///
/// (a) is DONE — C4 (the owner of `lib/screens/receipt_screen.dart`) removed
/// that entry in Phase 5G.1, so the guard below now covers the receipt screen
/// like every other screen. Only (b) is left, for `lib/errors.dart`'s owner.
const _knownOutsideB4 = {
  'lib/errors.dart -> dart:io',
};

void main() {
  test('adapted business files import no plugin and no dart:io', () {
    final problems = <String>[];
    for (final f in _adapted) {
      for (final i in _imports(f)) {
        if (i == 'dart:io' || _plugins.any(i.startsWith)) problems.add('$f -> $i');
      }
    }
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('no file outside lib/platform imports a plugin (the platform layer is the only door)', () {
    final problems = <String>[];
    for (final f in _dart('lib')) {
      final p = _rel(f);
      if (p.contains('/lib/platform/') || p.startsWith('lib/platform/')) continue;
      // secure_screen.dart uses its own MethodChannel and is outside B4's ownership.
      for (final i in _imports(f.path)) {
        if (_plugins.any(i.startsWith) && !_knownOutsideB4.contains('$p -> $i')) problems.add('$p -> $i');
      }
    }
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('dart:io appears only in *_io.dart adapter files', () {
    final problems = <String>[];
    for (final f in _dart('lib')) {
      final p = _rel(f);
      if (_imports(f.path).contains('dart:io') && !p.endsWith('_io.dart') && !_knownOutsideB4.contains('$p -> dart:io')) {
        problems.add(p);
      }
    }
    expect(problems, isEmpty, reason: 'dart:io outside an io adapter: $problems');
  });

  test('the allowlist of touchpoints outside B4 only shrinks (every entry still exists)', () {
    for (final e in _knownOutsideB4) {
      final [file, imp] = e.split(' -> ');
      expect(_imports(file), contains(imp), reason: '$e was fixed by its owner — remove it from _knownOutsideB4');
    }
  });

  test('kIsWeb is not sprinkled over screens (only lib/platform and the pre-existing secure_screen)', () {
    final problems = <String>[];
    for (final f in _dart('lib')) {
      final p = _rel(f);
      if (p.contains('lib/platform/') || p.endsWith('lib/secure_screen.dart')) continue;
      if (f.readAsStringSync().contains('kIsWeb')) problems.add(p);
    }
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('every adapter with a platform fork selects by conditional import', () {
    for (final name in ['secret_store', 'local_cache', 'file_export', 'biometrics']) {
      final src = File('lib/platform/$name.dart').readAsStringSync();
      expect(src, contains("if (dart.library.io) '${name}_io.dart'"), reason: name);
      expect(src, contains("if (dart.library.js_interop) '${name}_web.dart'"), reason: name);
      expect(File('lib/platform/${name}_stub.dart').existsSync(), isTrue, reason: '$name stub');
      expect(File('lib/platform/${name}_io.dart').existsSync(), isTrue, reason: '$name io');
      expect(File('lib/platform/${name}_web.dart').existsSync(), isTrue, reason: '$name web');
    }
  });

  test('the test support layer is platform-neutral (no dart:io at setUp)', () {
    final problems = <String>[];
    for (final f in _dart('test/support')) {
      final p = _rel(f);
      if (p.endsWith('_io.dart')) continue; // the one io-only helper, reached by conditional import
      if (_imports(f.path).contains('dart:io')) problems.add(p);
    }
    expect(problems, isEmpty, reason: 'dart:io in test support: $problems');
    final mocks = File('test/support/platform_mocks.dart').readAsStringSync();
    expect(mocks, isNot(contains('Directory.systemTemp')), reason: 'a temp dir must be created lazily, never at install()');
  });
}
