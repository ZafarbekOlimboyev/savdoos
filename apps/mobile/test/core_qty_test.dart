import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/format.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';

void main() {
  setUp(() => L.code = 'uz');

  group('parseMilli / parseQty', () {
    test('comma and dot are both decimal separators', () {
      expect(parseMilli('1,5'), 1500);
      expect(parseMilli('1.5'), 1500);
      expect(parseMilli('1,235'), 1235);
      expect(parseMilli('12'), 12000);
      expect(parseMilli(' 2 '), 2000);
      expect(parseMilli(',5'), 500);
      expect(parseMilli('1,'), 1000); // still typing
      expect(parseMilli('0'), 0);
      expect(parseMilli('007,1'), 7100);
    });

    test('more than 3 decimals is rejected, never rounded', () {
      expect(parseMilli('0.0015'), isNull);
      expect(parseQty('1,2345').error, NumError.tooManyDecimals);
      expect(hasTooManyDecimals('1,2345'), isTrue);
      expect(hasTooManyDecimals('1,234'), isFalse);
    });

    test('garbage, signs and several separators are invalid', () {
      for (final s in ['abc', '-1', '1.2.3', '1,2,3', '.', '1e3', '+1', '1 000.5.1']) {
        expect(parseQty(s).error, NumError.invalid, reason: s);
      }
      expect(parseQty('').error, NumError.empty);
      expect(parseQty(null).error, NumError.empty);
    });

    test('zero only when allowed; server limit', () {
      expect(parseQty('0').error, NumError.notPositive);
      expect(parseQty('0', allowZero: true).value, 0);
      expect(parseQty('1000000000').value, kMaxQtyMilli);
      expect(parseQty('1000000000,001').error, NumError.tooLarge);
      expect(parseQty('99999999999999999').error, NumError.tooLarge);
    });
  });

  group('server values -> milli (ROUND_HALF_UP like Decimal)', () {
    test('ints, doubles and decimal strings', () {
      expect(milliFromNum(2), 2000);
      expect(milliFromNum(1.5), 1500);
      expect(milliFromNum('2.000'), 2000);
      expect(milliFromNum('0.125'), 125);
      expect(milliFromNum(null), 0);
      expect(scaledFromServer('x', 3), isNull);
    });

    test('binary noise does not leak', () {
      expect(milliFromNum(0.1 + 0.2), 300);
      expect(milliFromNum(1.1 + 2.2), 3300);
      // 0.5005 is 0.50049999... in binary; Python Decimal("0.5005") -> 0.501
      expect(milliFromNum(0.5005), 501);
      expect(milliFromNum('0.5005'), 501);
      expect(milliFromNum('-1.0005'), -1001);
      expect(milliFromNum(1e-7), 0);
    });

    test('money', () {
      expect(centsFromNum('12.50'), 1250);
      expect(centsFromNum(12.345), 1235);
      expect(centsFromNum(-3), -300);
    });

    test('exponent notation is parsed, never recursed into (no StackOverflow)', () {
      // A Python Decimal can reach the wire as "1E-6" / "1e-06" / "1E+3".
      expect(scaledFromServer('1e-06', 3), 0);
      expect(scaledFromServer('1E-6', 3), 0);
      expect(scaledFromServer('5e-4', 3), 1, reason: '0.0005 -> half-up -> 0.001');
      expect(scaledFromServer('1E+3', 2), 100000);
      expect(scaledFromServer('1.5e2', 3), 150000);
      expect(scaledFromServer('-2.5e1', 2), -2500);
      expect(milliFromNum('1e-06'), 0);
    });

    test('absurd magnitudes fail closed instead of crashing the screen', () {
      // >= 1e21 formats back as "1e+21": the old fallback recursed for ever.
      expect(scaledFromServer('1e21', 2), isNull);
      expect(scaledFromServer(-1e21, 2), isNull);
      expect(scaledFromServer(1e20, 2), isNull);
      expect(scaledFromServer('99999999999999999999', 2), isNull);
      expect(scaledFromServer('-99999999999999999999.5', 3), isNull);
      expect(scaledFromServer(double.nan, 3), isNull);
      expect(scaledFromServer(double.infinity, 3), isNull);
      expect(scaledFromServer('1e999', 3), isNull);
      expect(milliFromNum('1e21'), 0, reason: 'null -> 0, the screen still renders');
      expect(centsFromNum('1e21'), 0);
      // The largest magnitude the server can actually store still parses.
      expect(scaledFromServer('999999999999999', 3), 999999999999999000);
    });
  });

  group('JSON and sums', () {
    test('milliToJson keeps exact 3-decimal values', () {
      expect(milliToJson(1500), 1.5);
      expect(milliToJson(2000), 2);
      expect(milliToJson(2000), isA<int>());
      expect(milliToJson(1235).toString(), '1.235');
      expect(milliToJson(1).toString(), '0.001');
      expect(centsToJson(1250), 12.5);
      expect(centsToJson(1200), 12);
    });

    test('sum in milli is exact where doubles are not', () {
      final parts = ['0,1', '0,2', '0,3'].map((s) => parseMilli(s)!).toList();
      expect(sumMilli(parts), 600);
      expect(0.1 + 0.2 + 0.3 == 0.6, isFalse); // the reason milli exists
    });

    test('lineCents rounds half-up and survives huge products', () {
      expect(lineCents(1500, 1000), 1500); // 1.5 × 10.00 = 15.00
      expect(lineCents(333, 100), 33); // 0.333 × 1.00 = 0.333 -> 0.33
      expect(lineCents(335, 100), 34); // 0.335 -> 0.34 (half-up)
      expect(lineCents(-335, 100), -34);
      // 1e9 units × 100 000 som: the naive milli×cents product (1e19) overflows int64.
      expect(lineCents(kMaxQtyMilli, 10000000), 10000000000000000);
    });
  });

  group('formatting', () {
    test('formatMilli', () {
      expect(formatMilli(1500), '1,5');
      expect(formatMilli(2000), '2');
      expect(formatMilli(1234567, group: true), '1 234,567');
      expect(formatMilli(-500), '-0,5');
      expect(milliToInput(10), '0,01');
    });

    test('formatCents shows whole som unless fractional', () {
      expect(formatCents(1234500), '12 345 so‘m');
      expect(formatCents(1234550), '12 345,50 so‘m');
      expect(formatCents(-500, currency: false), '-5');
      expect(centsToInput(1234500), '12345');
      expect(centsToInput(1250), '12,50');
      expect(moneyExact(12.5), '12,50 so‘m');
    });

    test('currency label is localized', () {
      L.code = 'ru';
      expect(formatCents(100), '1 сом');
    });
  });

  group('money parsing', () {
    test('whole som only rejects fractions', () {
      expect(parseMoney('12 345', wholeOnly: true).value, 1234500);
      expect(parseMoney('12 345,5', wholeOnly: true).error, NumError.tooManyDecimals);
      expect(parseMoney('0', wholeOnly: true).error, NumError.notPositive);
    });

    test('two decimals allowed', () {
      expect(parseCents('12,5'), 1250);
      expect(parseCents('12.05'), 1205);
      expect(parseMoney('1,005').error, NumError.tooManyDecimals);
      expect(parseMoney('1000000001').error, NumError.tooLarge);
    });

    test('error texts are localized', () {
      expect(qtyErrorText(NumError.tooManyDecimals), contains('0,001'));
      expect(moneyErrorText(NumError.tooManyDecimals, wholeOnly: true), 'Summa butun so‘mda kiritiladi');
      L.code = 'ky';
      expect(qtyErrorText(NumError.notPositive), 'Саны нөлдөн чоң болсун');
    });
  });

  group('dates', () {
    test('iso parse/format', () {
      expect(parseIsoDate('2026-02-30'), isNull);
      expect(parseIsoDate('2026-12-31'), DateTime.utc(2026, 12, 31));
      expect(dateDisplay('2026-01-05'), '05.01.2026');
      expect(isoDate(DateTime(2026, 3, 7)), '2026-03-07');
      expect(dateDisplay('junk'), '');
    });
  });
}
