// M4 l10n: every `tr('…')` / `trArgs('…')` literal of the package files has a
// Russian and a Kyrgyz translation, the package map has ru/ky parity and
// keeps placeholders, and dynamic keys (expense categories) are covered.
import 'dart:io';

import 'package:flutter/foundation.dart' show setEquals;
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/l10n/money_strings.dart';

/// Files of package M4.
const List<String> kMoneyFiles = [
  'lib/api/money_api.dart',
  'lib/screens/money_payment_sheet.dart',
  'lib/screens/customers_screen.dart',
  'lib/screens/customer_profile_screen.dart',
  'lib/screens/customer_edit_screen.dart',
  'lib/screens/debtors_screen.dart',
  'lib/screens/suppliers_screen.dart',
  'lib/screens/supplier_detail_screen.dart',
  'lib/screens/cash_ops_screen.dart',
  'lib/screens/sales_list_screen.dart',
  'lib/screens/sales_detail_screen.dart',
  'lib/screens/receipt_screen.dart',
];

/// Keys passed to `tr()` through a variable (expense categories).
const List<String> kDynamicKeys = ['Ijara', 'Kommunal', 'Maosh', 'Boshqa'];

// Adjacent string literals inside tr('a' 'b') are joined by the extractor.
final _trCall = RegExp(r"\btr(?:Args)?\(\s*((?:'(?:[^'\\]|\\.)*'\s*)+)");
final _lit = RegExp(r"'((?:[^'\\]|\\.)*)'");
final _ph = RegExp(r'\{[a-zA-Z_]+\}');

Set<String> moneyKeys() => {
      for (final f in kMoneyFiles)
        for (final m in _trCall.allMatches(File(f).readAsStringSync()))
          [for (final l in _lit.allMatches(m[1]!)) l[1]!].join(),
      ...kDynamicKeys,
    };

void main() {
  tearDown(() => L.code = 'uz');

  test('every M4 tr() literal is translated to ru and ky', () {
    final keys = moneyKeys();
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

  test('money map: ru/ky parity and placeholders kept', () {
    final problems = <String>[
      for (final k in ruMoney.keys) if (!kyMoney.containsKey(k)) 'ky missing "$k"',
      for (final k in kyMoney.keys) if (!ruMoney.containsKey(k)) 'ru missing "$k"',
      for (final m in [ruMoney, kyMoney])
        for (final e in m.entries)
          if (!setEquals({for (final x in _ph.allMatches(e.key)) x[0]}, {for (final x in _ph.allMatches(e.value)) x[0]}))
            'placeholder "${e.key}" -> "${e.value}"',
    ];
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('money map adds no key that is not used (no dead strings)', () {
    final used = moneyKeys();
    final dead = [for (final k in ruMoney.keys) if (!used.contains(k)) k];
    expect(dead, isEmpty, reason: dead.join('\n'));
  });

  test('sample translations', () {
    L.code = 'ru';
    expect(tr('Qarzni so‘ndirish'), isNot('Qarzni so‘ndirish'));
    expect(trArgs('{n} ta chek', {'n': 3}), contains('3'));
    L.code = 'ky';
    expect(tr('Inkassatsiya'), isNot('Inkassatsiya'));
  });
}
