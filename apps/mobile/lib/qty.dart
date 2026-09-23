/// Quantity and money helpers built on INTEGER arithmetic.
///
/// Quantities are NUMERIC(14,3) on the server, so every quantity in the app is
/// handled as an integer number of thousandths ("milli"): `1,5 kg` == `1500`.
/// Money is handled as an integer number of hundredths ("cents"): `12 345,50`
/// == `1234550`. Binary doubles are only produced at the very edge, when a
/// value is serialised into a JSON request body ([milliToJson], [centsToJson]).
///
/// Rules shared with the server (never re-implemented differently):
///  * user input may use a comma or a dot as the decimal separator;
///  * more than 3 quantity decimals (2 money decimals) is an ERROR, not
///    something to round silently — the server rejects it too;
///  * server values are rounded half-up (away from zero) exactly like Python's
///    `Decimal.quantize(ROUND_HALF_UP)`.
library;

import 'l10n.dart';

/// Thousandths per quantity unit.
const int kMilli = 1000;

/// Hundredths per money unit.
const int kCents = 100;

/// Largest quantity the server accepts (`qty <= 1e9`), in milli.
const int kMaxQtyMilli = 1000000000000;

/// Largest money amount the server accepts (`amount <= 1e9`), in cents.
const int kMaxCents = 100000000000;

/// Why a number typed by the user was rejected.
enum NumError {
  /// Nothing typed.
  empty,

  /// Not a non-negative decimal number (letters, several separators, sign).
  invalid,

  /// More decimals than the field allows (3 for qty, 2 for money, 0 for whole som).
  tooManyDecimals,

  /// Zero where a positive number is required.
  notPositive,

  /// Above the server limit.
  tooLarge,
}

/// Result of parsing user input into a scaled integer.
class NumParse {
  /// A successfully parsed value.
  const NumParse.ok(int this.value) : error = null;

  /// A rejected input.
  const NumParse.fail(NumError this.error) : value = null;

  /// The scaled integer (milli or cents); `null` when [error] is set.
  final int? value;

  /// Why the input was rejected; `null` on success.
  final NumError? error;

  /// True when the input was accepted.
  bool get ok => error == null;

  @override
  String toString() => ok ? 'NumParse($value)' : 'NumParse($error)';
}

final RegExp _spaces = RegExp(r'[\s   ]');
final RegExp _decimal = RegExp(r'^(\d+)(?:\.(\d*))?$');

int _pow10(int n) {
  var r = 1;
  for (var i = 0; i < n; i++) {
    r *= 10;
  }
  return r;
}

NumParse _parseScaled(String? raw, int scale, {required bool allowZero, required int max}) {
  var s = (raw ?? '').replaceAll(_spaces, '');
  if (s.isEmpty) return const NumParse.fail(NumError.empty);
  s = s.replaceAll(',', '.');
  if (s == '.') return const NumParse.fail(NumError.invalid);
  if (s.startsWith('.')) s = '0$s'; // ",5" -> 0.5
  final m = _decimal.firstMatch(s);
  if (m == null) return const NumParse.fail(NumError.invalid);
  final frac = m[2] ?? '';
  if (frac.length > scale) return const NumParse.fail(NumError.tooManyDecimals);
  final whole = m[1]!.replaceFirst(RegExp(r'^0+(?=\d)'), '');
  if (whole.length > 15) return const NumParse.fail(NumError.tooLarge);
  final fracPart = scale == 0 ? 0 : int.parse(frac.padRight(scale, '0'));
  final v = int.parse(whole) * _pow10(scale) + fracPart;
  if (v > max) return const NumParse.fail(NumError.tooLarge);
  if (v == 0 && !allowZero) return const NumParse.fail(NumError.notPositive);
  return NumParse.ok(v);
}

/// Parses a typed quantity into milli.
///
/// Accepts `"1,5"`, `"1.5"`, `",5"`, `"1."` (still typing) and surrounding
/// spaces. Rejects signs, several separators and more than 3 decimals.
/// Zero is rejected unless [allowZero] (stock counts may be zero).
NumParse parseQty(String? raw, {bool allowZero = false}) =>
    _parseScaled(raw, 3, allowZero: allowZero, max: kMaxQtyMilli);

/// Convenience: the milli value of [raw] (zero allowed), or `null` if invalid.
///
/// `parseMilli("1,5") == 1500`, `parseMilli("0.0015") == null`.
int? parseMilli(String? raw) => parseQty(raw, allowZero: true).value;

/// True when [raw] has more than [max] decimals (used to pick an error text).
bool hasTooManyDecimals(String? raw, {int max = 3}) {
  final s = (raw ?? '').replaceAll(_spaces, '').replaceAll(',', '.');
  final i = s.indexOf('.');
  return i >= 0 && s.length - i - 1 > max;
}

/// Parses typed money into cents (2 decimals) — or whole som when [wholeOnly].
///
/// Spaces are allowed as thousands separators (`"12 345,50"`).
NumParse parseMoney(String? raw, {bool wholeOnly = false, bool allowZero = false}) {
  if (!wholeOnly) return _parseScaled(raw, 2, allowZero: allowZero, max: kMaxCents);
  final r = _parseScaled(raw, 0, allowZero: allowZero, max: kMaxCents ~/ kCents);
  return r.ok ? NumParse.ok(r.value! * kCents) : r;
}

/// Convenience: cents of [raw] (zero allowed) or `null`.
int? parseCents(String? raw) => parseMoney(raw, allowZero: true).value;

/// Converts a server value (int, double or decimal string, possibly negative)
/// into a scaled integer, rounding half-up away from zero like Python's
/// `ROUND_HALF_UP`. Returns `null` for null/unparseable input.
int? scaledFromServer(Object? v, int scale) {
  if (v == null) return null;
  if (v is int) return v * _pow10(scale);
  String s;
  if (v is double) {
    if (v.isNaN || v.isInfinite) return null;
    // Six extra digits absorb binary noise (0.30000000000000004 -> "0.300000...").
    s = v.toStringAsFixed(scale + 6);
  } else {
    s = v.toString().trim().replaceAll(',', '.');
  }
  var neg = false;
  if (s.startsWith('-')) {
    neg = true;
    s = s.substring(1);
  } else if (s.startsWith('+')) {
    s = s.substring(1);
  }
  final m = _decimal.firstMatch(s);
  if (m == null) {
    final d = double.tryParse(s); // exponent form ("1e-7")
    if (d == null) return null;
    final r = scaledFromServer(d, scale);
    return r == null ? null : (neg ? -r : r);
  }
  final whole = m[1]!;
  final frac = m[2] ?? '';
  final kept = scale == 0 ? 0 : int.parse(frac.padRight(scale, '0').substring(0, scale));
  var mag = int.parse(whole) * _pow10(scale) + kept;
  if (frac.length > scale && frac.codeUnitAt(scale) >= 0x35 /* '5' */) mag += 1;
  return neg ? -mag : mag;
}

/// Server quantity -> milli (`1.5` -> 1500, `"2.000"` -> 2000); 0 for null.
int milliFromNum(Object? v) => scaledFromServer(v, 3) ?? 0;

/// Server money -> cents (`"12.50"` -> 1250); 0 for null.
int centsFromNum(Object? v) => scaledFromServer(v, 2) ?? 0;

/// Milli -> JSON number for a request body (`1500` -> `1.5`, `2000` -> `2`).
///
/// The shortest double representation of `m / 1000` prints back exactly the
/// same 3-decimal value, so the server receives what the operator saw.
num milliToJson(int milli) => milli % kMilli == 0 ? milli ~/ kMilli : milli / kMilli;

/// Cents -> JSON number (`1250` -> `12.5`, `1200` -> `12`).
num centsToJson(int cents) => cents % kCents == 0 ? cents ~/ kCents : cents / kCents;

/// Sum of milli values.
int sumMilli(Iterable<int> values) => values.fold(0, (a, b) => a + b);

/// Line total in cents for [milli] quantity at [unitCents] per unit, rounded
/// half-up away from zero. Uses BigInt only when the product would overflow.
int lineCents(int milli, int unitCents) {
  final neg = (milli < 0) != (unitCents < 0);
  final a = milli.abs(), b = unitCents.abs();
  int mag;
  if (a != 0 && b > 9000000000000000000 ~/ a) {
    final p = BigInt.from(a) * BigInt.from(b);
    mag = ((p + BigInt.from(500)) ~/ BigInt.from(1000)).toInt();
  } else {
    mag = (a * b + 500) ~/ 1000;
  }
  return neg ? -mag : mag;
}

String _group(String digits, String sep) {
  final b = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) b.write(sep);
    b.write(digits[i]);
  }
  return b.toString();
}

String _formatScaled(int v, int scale, {required String decimalSep, required bool group, bool trim = true}) {
  final neg = v < 0;
  final a = v.abs();
  final p = _pow10(scale);
  final whole = (a ~/ p).toString();
  var frac = scale == 0 ? '' : (a % p).toString().padLeft(scale, '0');
  if (trim) frac = frac.replaceFirst(RegExp(r'0+$'), '');
  final w = group ? _group(whole, ' ') : whole;
  return '${neg ? '-' : ''}$w${frac.isEmpty ? '' : '$decimalSep$frac'}';
}

/// Milli -> display text: `1500` -> `"1,5"`, `2000` -> `"2"`, with optional
/// thousands grouping (`1 234,5`).
String formatMilli(int milli, {String decimalSep = ',', bool group = false}) =>
    _formatScaled(milli, 3, decimalSep: decimalSep, group: group);

/// Milli -> text suitable to prefill an input (no grouping).
String milliToInput(int milli) => formatMilli(milli);

/// Cents -> display text: whole som when there is no fraction
/// (`1234500` -> `"12 345"`), otherwise two decimals (`"12 345,50"`).
/// [currency] appends the localized currency label.
String formatCents(int cents, {bool currency = true}) {
  final frac = cents.abs() % kCents != 0;
  final s = _formatScaled(cents, 2, decimalSep: ',', group: true, trim: false);
  final out = frac ? s : s.substring(0, s.length - 3);
  return currency ? '$out ${tr('so‘m')}' : out;
}

/// Cents -> text to prefill a money input (no grouping, no currency).
String centsToInput(int cents) {
  final s = _formatScaled(cents, 2, decimalSep: ',', group: false, trim: false);
  return cents.abs() % kCents == 0 ? s.substring(0, s.length - 3) : s;
}

/// Localized message for a [NumError] on a quantity field.
String qtyErrorText(NumError e) => switch (e) {
      NumError.empty => tr('Miqdorni kiriting'),
      NumError.invalid => tr('Miqdor noto‘g‘ri'),
      NumError.tooManyDecimals => tr('Ko‘pi bilan 3 ta kasr xona (0,001)'),
      NumError.notPositive => tr('Miqdor noldan katta bo‘lsin'),
      NumError.tooLarge => tr('Miqdor juda katta'),
    };

/// Localized message for a [NumError] on a money field.
String moneyErrorText(NumError e, {bool wholeOnly = false}) => switch (e) {
      NumError.empty => tr('Summani kiriting'),
      NumError.invalid => tr('Summa noto‘g‘ri'),
      NumError.tooManyDecimals =>
        wholeOnly ? tr('Summa butun so‘mda kiritiladi') : tr('Ko‘pi bilan 2 ta kasr xona'),
      NumError.notPositive => tr('Summa noldan katta bo‘lsin'),
      NumError.tooLarge => tr('Summa juda katta'),
    };
