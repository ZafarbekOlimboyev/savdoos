// VM only: reads the repository's Dart sources to check every tr() literal.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter/foundation.dart' show setEquals;
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/errors.dart';
import 'package:savdoos_mobile/format.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/permissions.dart';

/// Files owned by the core package (MC): every `tr('…')` literal in them must
/// have a Russian and a Kyrgyz translation.
List<File> coreFiles() {
  final names = ['api', 'errors', 'session', 'qty', 'permissions', 'scan', 'format', 'main'];
  return [
    for (final n in names) File('lib/$n.dart'),
    File('lib/screens/barcode_scan_screen.dart'),
    File('lib/screens/password_change_screen.dart'),
    ...Directory('lib/ui').listSync().whereType<File>().where((f) => f.path.endsWith('.dart')),
    ...Directory('lib/widgets').listSync().whereType<File>().where((f) => f.path.endsWith('.dart')),
  ];
}

final _trLiteral = RegExp(r"\btr(?:Args)?\(\s*'((?:[^'\\]|\\.)*)'");
final _ph = RegExp(r'\{[a-zA-Z_]+\}');

Set<String> placeholders(String s) => {for (final m in _ph.allMatches(s)) m[0]!};

void main() {
  tearDown(() => L.code = 'uz');

  test('no key is translated differently by two sources', () {
    final seenRu = <String, (String, String)>{};
    final seenKy = <String, (String, String)>{};
    final problems = <String>[];
    debugL10nSources().forEach((src, maps) {
      maps.$1.forEach((k, v) {
        final prev = seenRu[k];
        if (prev != null && prev.$2 != v) problems.add('ru "$k": ${prev.$1}="${prev.$2}" vs $src="$v"');
        seenRu[k] = (src, v);
      });
      maps.$2.forEach((k, v) {
        final prev = seenKy[k];
        if (prev != null && prev.$2 != v) problems.add('ky "$k": ${prev.$1}="${prev.$2}" vs $src="$v"');
        seenKy[k] = (src, v);
      });
    });
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('every package map has ru/ky parity (same keys in both)', () {
    final problems = <String>[];
    debugL10nSources().forEach((src, maps) {
      if (src == 'base') return; // legacy map: parity checked for core keys below
      for (final k in maps.$1.keys) {
        if (!maps.$2.containsKey(k)) problems.add('$src: ky missing "$k"');
      }
      for (final k in maps.$2.keys) {
        if (!maps.$1.containsKey(k)) problems.add('$src: ru missing "$k"');
      }
    });
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('translations keep every {placeholder}', () {
    final problems = <String>[];
    debugL10nSources().forEach((src, maps) {
      for (final m in [maps.$1, maps.$2]) {
        m.forEach((k, v) {
          if (!setEquals(placeholders(k), placeholders(v))) problems.add('$src "$k" -> "$v"');
        });
      }
    });
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('every core tr() literal, error template, permission label and date key is translated', () {
    final keys = <String>{
      for (final f in coreFiles())
        for (final m in _trLiteral.allMatches(f.readAsStringSync())) m[1]!,
      ...debugErrorTemplates(),
      ...debugCapabilityTemplates(),
      ...debugPermissionLabels(),
      ...debugDateKeys(),
    };
    expect(keys.length, greaterThan(250));
    final missing = <String>[];
    for (final lang in ['ru', 'ky']) {
      L.code = lang;
      for (final k in keys) {
        final t = tr(k);
        final needsText = RegExp('[A-Za-z]{3,}').hasMatch(k.replaceAll(_ph, '')) && !const {'OK', 'KK.OO.YYYY'}.contains(k);
        if (t == k && needsText) missing.add('$lang: $k');
      }
    }
    expect(missing, isEmpty, reason: missing.join('\n'));
  });

  test('trArgs substitutes after translating; uzc transliterates but keeps data and placeholders', () {
    L.code = 'ru';
    expect(trArgs('Kod: {code}', {'code': 'ABC 123'}), 'Код: ABC 123');
    L.code = 'uzc';
    expect(tr('Partiya qo‘shish'), 'Партия қўшиш');
    expect(trArgs('Filial: {name}', {'name': 'Chilonzor'}), 'Филиал: Chilonzor');
    expect(tr('Yak'), 'Як');
    expect(weekdayShortNames(), ['Душ', 'Сеш', 'Чор', 'Пай', 'Жум', 'Шан', 'Як']);
    L.code = 'ky';
    expect(monthName(9), 'Сентябрь');
  });

  test('package string files exist with the agreed shape', () {
    for (final (file, cap) in [
      ('receiving', 'Receiving'),
      ('stock', 'Stock'),
      ('correction', 'Correction'),
      ('money', 'Money'),
      ('shell', 'Shell'),
    ]) {
      final src = File('lib/l10n/${file}_strings.dart').readAsStringSync();
      expect(src, contains('const Map<String, String> ru$cap'), reason: file);
      expect(src, contains('const Map<String, String> ky$cap'), reason: file);
      expect(debugL10nSources().containsKey(file), isTrue, reason: 'merged in l10n.dart: $file');
    }
  });
}
