import 'package:intl/intl.dart';
import 'qty.dart';
import 'l10n.dart';

final _nf = NumberFormat('#,##0', 'ru_RU');

/// Pul formati: "12 345 so'm" (probel bilan). Valyuta — so'm (KG uchun keyin sozlanadi).
String money(num v) {
  final s = _nf.format(v.round()).replaceAll(',', ' ').replaceAll(' ', ' ');
  // Valyuta yorlig'i tilga qarab (ru/ky: "сом"; ilgari doim lotin "so'm" chiqardi)
  return '$s ${tr('so‘m')}';
}

/// Qisqa son: 1,2 mln / 34 ming.
String short(num v) {
  final a = v.abs();
  if (a >= 1e6) return '${(v / 1e6).toStringAsFixed(1).replaceAll('.', ',')} ${tr('mln')}';
  if (a >= 1e3) return '${(v / 1e3).round()} ${tr('ming')}';
  return v.round().toString();
}

String qtyStr(num v) => v == v.roundToDouble() ? v.round().toString() : v.toStringAsFixed(3);

String hm(DateTime? d) => d == null ? '' : DateFormat('HH:mm').format(d);

const _uzMonths = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'];
const _ruMonths = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const _kyMonths = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const _uzcMonths = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

List<String> _months() => switch (L.code) {
      'ru' => _ruMonths,
      'ky' => _kyMonths,
      'uzc' => _uzcMonths,
      _ => _uzMonths,
    };

/// To'liq sana-vaqt: "20 avg, 14:30" (locale-data'siz, tilga qarab oy nomi).
String dmy(DateTime? d) {
  if (d == null) return '';
  final mm = d.minute.toString().padLeft(2, '0');
  return '${d.day} ${_months()[d.month - 1]}, ${d.hour.toString().padLeft(2, '0')}:$mm';
}

// ── Sana (biznes sanasi, yaroqlilik muddati) ─────────────────────────────
// ⚠️  Biznes sanasi — FILIAL xossasi, qurilma soati emas: sanalar `YYYY-MM-DD`
//     satr sifatida yuradi va DateTime faqat kalendar hisobi uchun (UTC yarim tun).

/// `DateTime` -> `YYYY-MM-DD` (only the calendar date is used).
String isoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// Strict `YYYY-MM-DD` -> UTC midnight `DateTime`; `null` for anything else
/// (including impossible dates such as `2026-02-30`).
DateTime? parseIsoDate(String? s) {
  final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch((s ?? '').trim());
  if (m == null) return null;
  final y = int.parse(m[1]!), mo = int.parse(m[2]!), d = int.parse(m[3]!);
  if (mo < 1 || mo > 12 || d < 1) return null;
  final dt = DateTime.utc(y, mo, d);
  return (dt.year == y && dt.month == mo && dt.day == d) ? dt : null;
}

/// `2026-12-31` -> `31.12.2026` (empty for null/invalid input).
String dateDisplay(String? iso) {
  final d = parseIsoDate(iso);
  if (d == null) return '';
  return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
}

const _monthFull = [
  'Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
  'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr',
];
// 3 harfli kalit: 2 harfli 'Ch'/'Sh'/'Ya' kirillga bitta harf bo'lib o'girilardi.
const _weekdayShort = ['Dush', 'Sesh', 'Chor', 'Pay', 'Jum', 'Shan', 'Yak'];

/// Localized full month name (1..12).
String monthName(int month) => tr(_monthFull[month - 1]);

/// Localized short weekday names, Monday first.
List<String> weekdayShortNames() => [for (final w in _weekdayShort) tr(w)];

/// Month/weekday keys (l10n parity test).
List<String> debugDateKeys() => [..._monthFull, ..._weekdayShort];

/// Pul (hujjat summasi): butun so'm, kasr bo'lsa 2 xona — `12 345` / `12 345,50 so'm`.
/// `money()` dan farqi: yaxlitlamaydi (qarz, to'lov, chek summalari uchun).
String moneyExact(num v) => formatCents(centsFromNum(v));
