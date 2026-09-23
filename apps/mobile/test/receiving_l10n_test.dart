import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/l10n/receiving_strings.dart';

/// Files owned by the receiving package (M1).
List<File> receivingFiles() => [
      File('lib/api/receiving_api.dart'),
      File('lib/screens/manual_receiving_screen.dart'),
      ...Directory('lib/screens')
          .listSync()
          .whereType<File>()
          .where((f) => f.uri.pathSegments.last.startsWith('receiving_') && f.path.endsWith('.dart')),
    ];

final _trLiteral = RegExp(r"\btr(?:Args)?\(\s*'((?:[^'\\]|\\.)*)'");
final _ph = RegExp(r'\{[a-zA-Z_]+\}');

void main() {
  tearDown(() => L.code = 'uz');

  test('every tr() literal of the receiving screens has a ru and ky translation', () {
    final keys = <String>{
      for (final f in receivingFiles())
        for (final m in _trLiteral.allMatches(f.readAsStringSync())) m[1]!.replaceAll(r"\'", "'"),
    };
    expect(keys.length, greaterThan(100));
    final missing = <String>[];
    for (final lang in ['ru', 'ky']) {
      L.code = lang;
      for (final k in keys) {
        final needsText = RegExp('[A-Za-z]{3,}').hasMatch(k.replaceAll(_ph, ''));
        if (needsText && tr(k) == k) missing.add('$lang: $k');
      }
    }
    expect(missing, isEmpty, reason: missing.join('\n'));
  });

  test('receiving maps: ru/ky parity, placeholders kept, Cyrillic output', () {
    expect(ruReceiving.keys.toSet(), kyReceiving.keys.toSet());
    for (final m in [ruReceiving, kyReceiving]) {
      m.forEach((k, v) {
        expect({for (final x in _ph.allMatches(v)) x[0]}, {for (final x in _ph.allMatches(k)) x[0]}, reason: k);
        expect(v.trim(), isNotEmpty, reason: k);
      });
    }
  });

  test('uzc is transliterated automatically', () {
    L.code = 'uzc';
    expect(tr('Qabul filiali: {name}'), 'Қабул филиали: {name}');
  });
}
