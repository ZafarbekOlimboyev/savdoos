import 'package:intl/intl.dart';
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
