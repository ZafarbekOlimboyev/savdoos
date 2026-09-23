// M2 (stock) l10n: every tr()/trArgs() literal of the stock files has a real
// Russian and Kyrgyz translation, and the stock map keeps ru/ky parity and
// {placeholders}. (Cross-source conflicts are checked by core_l10n_test.)
import 'dart:io';

import 'package:flutter/foundation.dart' show setEquals;
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/l10n/stock_strings.dart';

const stockFiles = [
  'lib/api/stock_api.dart',
  'lib/screens/inventory_screen.dart',
  'lib/screens/product_detail_screen.dart',
  'lib/screens/writeoff_screen.dart',
  'lib/screens/inventarizatsiya_screen.dart',
  'lib/screens/transfer_screen.dart',
  'lib/screens/notifications_screen.dart',
  'lib/screens/home_screen.dart',
];

final _lit = RegExp(r"\btr(?:Args)?\(\s*'((?:[^'\\]|\\.)*)'");
final _ph = RegExp(r'\{[a-zA-Z_]+\}');

String _unescape(String s) => s.replaceAll(r"\'", "'").replaceAll(r'\n', '\n');

Set<String> stockKeys() => {
      for (final f in stockFiles)
        for (final m in _lit.allMatches(File(f).readAsStringSync())) _unescape(m[1]!),
    };

void main() {
  tearDown(() => L.code = 'uz');

  test('every stock tr() literal is translated to ru and ky', () {
    final keys = stockKeys();
    expect(keys.length, greaterThan(150));
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

  test('stock map: ru/ky parity, placeholders kept, Cyrillic text', () {
    final problems = <String>[];
    for (final k in ruStock.keys) {
      if (!kyStock.containsKey(k)) problems.add('ky missing: $k');
    }
    for (final k in kyStock.keys) {
      if (!ruStock.containsKey(k)) problems.add('ru missing: $k');
    }
    for (final m in [ruStock, kyStock]) {
      m.forEach((k, v) {
        final a = {for (final x in _ph.allMatches(k)) x[0]};
        final b = {for (final x in _ph.allMatches(v)) x[0]};
        if (!setEquals(a, b)) problems.add('placeholders: "$k" -> "$v"');
        if (v.trim().isEmpty) problems.add('empty: $k');
        if (RegExp('[A-Za-z]{3,}').hasMatch(k.replaceAll(_ph, '')) && !RegExp('[А-Яа-яЁёҢңӨөҮү]').hasMatch(v)) {
          problems.add('not Cyrillic: "$k" -> "$v"');
        }
      });
    }
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('uzc transliterates stock strings, data stays', () {
    L.code = 'uzc';
    expect(trArgs('{n} ta mahsulot', {'n': 7}), '7 та маҳсулот');
    L.code = 'ru';
    expect(trArgs('Filial qoldig‘i: {q}', {'q': '5 kg'}), contains('5 kg'));
  });
}
