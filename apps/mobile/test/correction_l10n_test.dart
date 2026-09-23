// M3 — every `tr('…')` literal of the correction package has a Russian and a
// Kyrgyz translation (from the package map or a shared source), and the
// package map only holds keys the package really uses.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/l10n/correction_strings.dart';

const _files = [
  'lib/screens/purchase_detail_screen.dart',
  'lib/screens/correction_screen.dart',
  'lib/api/correction_api.dart',
];

final _trLiteral = RegExp(r"\btr(?:Args)?\(\s*'((?:[^'\\]|\\.)*)'");

Set<String> _keys() => {
      for (final f in _files)
        for (final m in _trLiteral.allMatches(File(f).readAsStringSync())) m[1]!,
    };

void main() {
  tearDown(() => L.code = 'uz');

  test('every correction tr() literal is translated to ru and ky', () {
    final keys = _keys();
    expect(keys.length, greaterThan(60));
    final missing = <String>[];
    for (final lang in ['ru', 'ky']) {
      L.code = lang;
      for (final k in keys) {
        if (tr(k) == k) missing.add('$lang: $k');
      }
    }
    expect(missing, isEmpty, reason: missing.join('\n'));
  });

  test('the package map has no unused keys and ru/ky parity', () {
    final used = _keys();
    expect(ruCorrection.keys.toSet(), kyCorrection.keys.toSet());
    final unused = ruCorrection.keys.where((k) => !used.contains(k)).toList();
    expect(unused, isEmpty, reason: unused.join('\n'));
  });

  test('uzc is transliterated automatically and keeps data', () {
    L.code = 'uzc';
    expect(tr('Qabulni tuzatish'), 'Қабулни тузатиш');
    expect(trArgs('Hujjat jami: {old} → {next}', {'old': '10', 'next': '5'}), 'Ҳужжат жами: 10 → 5');
  });
}
