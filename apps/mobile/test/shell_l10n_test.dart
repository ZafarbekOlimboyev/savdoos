// M5 l10n: every string the shell / settings / analytics / employees / login /
// PIN screens show has a Russian AND a Kyrgyz translation, and the server texts
// those screens can surface (employee management, login limits) are
// translated through `userMessage`.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/errors.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/l10n/shell_strings.dart';
import 'package:savdoos_mobile/screens/employee_edit_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';

/// Files owned by package M5.
const m5Files = [
  'lib/screens/shell.dart',
  'lib/screens/settings_screen.dart',
  'lib/screens/analytics_screen.dart',
  'lib/screens/employees_screen.dart',
  'lib/screens/employee_edit_screen.dart',
  'lib/screens/login_screen.dart',
  'lib/screens/pin_screens.dart',
  'lib/lock.dart',
];

/// Strings passed to `tr()` through a variable (tab labels, permission module
/// / action names, sale methods, conditional texts).
const indirectKeys = [
  'Bosh',
  'Analitika',
  'Ombor',
  'Sozlama',
  'Kassa',
  'Sotuvlar',
  'Qaytarishlar',
  'Mijozlar',
  'Mahsulotlar',
  'Xaridlar',
  'Hisobot',
  'Xodimlar',
  'Sozlamalar',
  "Ko'rish",
  "O'zgartirish",
  'Sotish',
  'Yaratish',
  'Naqd',
  'Karta',
  'Qarz',
  'Ega — barcha huquqlar',
  'Administrator — barcha ruxsatlarga ega',
];

final _trLiteral = RegExp(r"""\btr(?:Args)?\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""");

Set<String> literalsIn(String path) => {
      for (final m in _trLiteral.allMatches(File(path).readAsStringSync()))
        (m[1] ?? m[2]!).replaceAll(r"\'", "'").replaceAll(r'\"', '"'),
    };

void main() {
  tearDown(() => L.code = 'uz');

  test('every M5 tr() literal is translated to ru and ky', () {
    final keys = <String>{for (final f in m5Files) ...literalsIn(f), ...indirectKeys};
    expect(keys.length, greaterThan(150), reason: 'the scan must find the screens\' strings');
    final missing = <String>[];
    for (final lang in ['ru', 'ky']) {
      L.code = lang;
      for (final k in keys) {
        final letters = RegExp('[A-Za-z]{3,}').hasMatch(k.replaceAll(RegExp(r'\{[a-z_]+\}'), ''));
        if (letters && tr(k) == k && !const {'SavdoOS', 'PIN'}.contains(k)) missing.add('$lang: $k');
      }
    }
    expect(missing, isEmpty, reason: missing.join('\n'));
  });

  test('shell map: ru/ky key parity and placeholders kept', () {
    expect(ruShell.keys.toSet(), kyShell.keys.toSet());
    final ph = RegExp(r'\{[a-z_]+\}');
    for (final m in [ruShell, kyShell]) {
      m.forEach((k, v) {
        expect({for (final x in ph.allMatches(v)) x[0]}, {for (final x in ph.allMatches(k)) x[0]}, reason: k);
        expect(v.trim(), isNotEmpty, reason: k);
      });
    }
  });

  group('server texts on M5 screens are localized', () {
    ApiException err(int status, Object? detail) =>
        ApiException(status, ApiException.flatten(detail) ?? '', detail: detail);

    test('employee management refusals: every known server text, 403 included', () {
      expect(kEmployeeServerTexts.length, greaterThanOrEqualTo(25));
      for (final lang in ['ru', 'ky']) {
        L.code = lang;
        for (final t in kEmployeeServerTexts) {
          for (final status in [400, 403, 409]) {
            final m = employeeErrorMessage(err(status, t));
            expect(m, isNot(t), reason: '$lang $status: $t');
            expect(m, tr(t), reason: 'the specific rule, not a generic "no permission": $t');
            expect(m, isNot(contains("'")), reason: '$lang: $t -> $m');
          }
        }
      }
      L.code = 'uz';
      expect(employeeErrorMessage(err(403, "O'zingizni o'chira olmaysiz")), "O'zingizni o'chira olmaysiz");
      expect(employeeErrorMessage(err(403, "Ruxsat yo'q: xodimlar.edit")), isNot(contains('xodimlar.edit')));
    });

    test('tariff limit and password policy get their own sentence', () {
      L.code = 'ru';
      final limit = employeeErrorMessage(err(403, {'error': 'tarif_limit', 'plan': 'start', 'max_users': 3}));
      expect(limit, contains('3'));
      expect(limit, isNot(contains('tarif_limit')));
      expect(employeeErrorMessage(err(400, "Parol qabul qilinmadi: juda qisqa (7 belgi, kamida 12 kerak)")),
          contains('12'));
      expect(employeeErrorMessage(err(400, "Parol qabul qilinmadi: juda ko'p uchraydigan qiymat")),
          tr('Parol juda oddiy — boshqa parol tanlang.'));
      expect(tr('Parol juda oddiy — boshqa parol tanlang.'), isNot('Parol juda oddiy — boshqa parol tanlang.'));
    });

    test('login: wrong credentials vs no connection vs limits', () {
      L.code = 'ru';
      expect(loginErrorMessage(err(401, "Kirish ma'lumotlari noto'g'ri")), tr('Telefon yoki parol noto‘g‘ri'));
      final offline = loginErrorMessage(ApiException(0, 'x', kind: ApiErrorKind.network));
      expect(offline, isNot(tr('Telefon yoki parol noto‘g‘ri')), reason: 'no connection is NOT a wrong password');
      expect(offline, userMessage(ApiException(0, 'x', kind: ApiErrorKind.network)));
      for (final t in [
        "Juda ko'p urinish — 5 daqiqadan keyin qayta urining",
        "Hisob vaqtincha bloklandi — 15 daqiqadan keyin urinib ko'ring",
      ]) {
        final m = loginErrorMessage(err(429, t));
        expect(m, isNot(t));
        expect(m, contains(RegExp('[А-Яа-я]')));
      }
      expect(loginErrorMessage(err(403, "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.")),
          contains(RegExp('[А-Яа-я]')));
      expect(loginErrorMessage(err(503, 'x')), userMessage(err(503, 'x')));
    });
  });
}
