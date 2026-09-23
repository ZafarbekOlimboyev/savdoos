import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'app_sheet.dart';
import 'tokens.dart';

/// A date input (`YYYY-MM-DD` value) that opens [showAppDatePicker].
///
/// Dates are calendar days, not instants: the business date of a branch and
/// an expiry date are compared as ISO strings, never through the device clock.
/// Days before [minDate] cannot be chosen.
class DateField extends StatelessWidget {
  /// Creates the field.
  const DateField({
    super.key,
    required this.value,
    required this.onChanged,
    this.minDate,
    this.maxDate,
    this.label,
    this.hint,
    this.errorText,
    this.helperText,
    this.enabled = true,
    this.clearable = false,
    this.focusNode,
    this.pickerTitle,
  });

  /// Current value (`YYYY-MM-DD`) or null.
  final String? value;

  /// Called with the picked date (or null when cleared).
  final ValueChanged<String?> onChanged;

  /// Earliest selectable date (inclusive).
  final String? minDate;

  /// Latest selectable date (inclusive).
  final String? maxDate;

  /// Floating label.
  final String? label;

  /// Placeholder.
  final String? hint;

  /// Inline error.
  final String? errorText;

  /// Helper text.
  final String? helperText;

  /// Tappable.
  final bool enabled;

  /// Shows a clear button when a value is set.
  final bool clearable;

  /// Focus node (first-error focus scrolls to this field).
  final FocusNode? focusNode;

  /// Title of the picker sheet (defaults to [label]).
  final String? pickerTitle;

  Future<void> _pick(BuildContext context) async {
    final v = await showAppDatePicker(context,
        initial: value, minDate: minDate, maxDate: maxDate, title: pickerTitle ?? label ?? tr('Sanani tanlang'));
    if (v != null) onChanged(v);
  }

  @override
  Widget build(BuildContext context) {
    final shown = dateDisplay(value);
    return Focus(
      focusNode: focusNode,
      child: Builder(builder: (ctx) {
        final focused = Focus.of(ctx).hasFocus;
        return Semantics(
          button: true,
          label: label,
          value: shown,
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: enabled ? () => _pick(ctx) : null,
            child: InputDecorator(
              isFocused: focused,
              isEmpty: shown.isEmpty,
              decoration: InputDecoration(
                labelText: label,
                hintText: hint ?? tr('KK.OO.YYYY'),
                helperText: helperText,
                errorText: errorText,
                errorMaxLines: 3,
                enabled: enabled,
                constraints: const BoxConstraints(minHeight: kMinTouch),
                suffixIcon: clearable && shown.isNotEmpty && enabled
                    ? IconButton(
                        tooltip: tr('Tozalash'),
                        onPressed: () => onChanged(null),
                        icon: const Icon(Icons.close),
                      )
                    : Icon(Icons.calendar_month, color: AppColors.muted),
              ),
              child: Text(shown, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            ),
          ),
        );
      }),
    );
  }
}

/// Opens a localized date picker sheet: a typed `KK.OO.YYYY` entry (fast for
/// dates printed on a package) plus a month calendar with 48 dp day cells.
/// Returns `YYYY-MM-DD`, or null when dismissed.
Future<String?> showAppDatePicker(
  BuildContext context, {
  String? initial,
  String? minDate,
  String? maxDate,
  String? title,
}) {
  return showAppSheet<String>(
    context,
    title: title ?? tr('Sanani tanlang'),
    builder: (ctx) => _DatePickerBody(initial: initial, minDate: minDate, maxDate: maxDate),
  );
}

/// Formats typed digits as `KK.OO.YYYY` (dots are inserted automatically).
class DateTypingFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    var d = newValue.text.replaceAll(RegExp(r'\D'), '');
    if (d.length > 8) d = d.substring(0, 8);
    final b = StringBuffer();
    for (var i = 0; i < d.length; i++) {
      if (i == 2 || i == 4) b.write('.');
      b.write(d[i]);
    }
    final t = b.toString();
    return TextEditingValue(text: t, selection: TextSelection.collapsed(offset: t.length));
  }
}

/// `31.12.2026` -> `2026-12-31` (null if incomplete or impossible).
String? parseTypedDate(String text) {
  final m = RegExp(r'^(\d{2})\.(\d{2})\.(\d{4})$').firstMatch(text.trim());
  if (m == null) return null;
  final iso = '${m[3]}-${m[2]}-${m[1]}';
  return parseIsoDate(iso) == null ? null : iso;
}

class _DatePickerBody extends StatefulWidget {
  const _DatePickerBody({this.initial, this.minDate, this.maxDate});
  final String? initial, minDate, maxDate;

  @override
  State<_DatePickerBody> createState() => _DatePickerBodyState();
}

class _DatePickerBodyState extends State<_DatePickerBody> {
  late DateTime _month; // first day, UTC
  final _typed = TextEditingController();
  String? _typedError;

  @override
  void initState() {
    super.initState();
    final base = parseIsoDate(widget.initial) ?? parseIsoDate(widget.minDate) ?? _todayUtc();
    _month = DateTime.utc(base.year, base.month);
    final init = parseIsoDate(widget.initial);
    if (init != null) _typed.text = dateDisplay(widget.initial);
  }

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  static DateTime _todayUtc() {
    final n = DateTime.now();
    return DateTime.utc(n.year, n.month, n.day);
  }

  bool _allowed(String iso) {
    if (widget.minDate != null && iso.compareTo(widget.minDate!) < 0) return false;
    if (widget.maxDate != null && iso.compareTo(widget.maxDate!) > 0) return false;
    return true;
  }

  void _shift(int months) => setState(() => _month = DateTime.utc(_month.year, _month.month + months));

  void _submitTyped() {
    final iso = parseTypedDate(_typed.text);
    if (iso == null) {
      setState(() => _typedError = tr('Sana noto‘g‘ri — KK.OO.YYYY'));
      return;
    }
    if (!_allowed(iso)) {
      setState(() => _typedError = widget.minDate != null && iso.compareTo(widget.minDate!) < 0
          ? trArgs('Sana {d} dan oldin bo‘lmasin', {'d': dateDisplay(widget.minDate)})
          : trArgs('Sana {d} dan keyin bo‘lmasin', {'d': dateDisplay(widget.maxDate)}));
      return;
    }
    Navigator.of(context).pop(iso);
  }

  @override
  Widget build(BuildContext context) {
    final sel = widget.initial;
    final daysInMonth = DateTime.utc(_month.year, _month.month + 1, 0).day;
    final lead = _month.weekday - 1; // Monday first
    final cells = <Widget>[
      for (final w in weekdayShortNames())
        Center(child: Text(w, style: TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w700))),
      for (var i = 0; i < lead; i++) const SizedBox.shrink(),
      for (var d = 1; d <= daysInMonth; d++) _day(isoDate(DateTime.utc(_month.year, _month.month, d)), d, sel),
    ];
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: TextField(
            key: const Key('date-typed'),
            controller: _typed,
            keyboardType: TextInputType.number,
            inputFormatters: [DateTypingFormatter()],
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submitTyped(),
            onChanged: (_) {
              if (_typedError != null) setState(() => _typedError = null);
            },
            decoration: InputDecoration(
              labelText: tr('Sanani yozing'),
              hintText: tr('KK.OO.YYYY'),
              errorText: _typedError,
              errorMaxLines: 2,
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          height: 52,
          child: ElevatedButton(
            key: const Key('date-typed-ok'),
            onPressed: _submitTyped,
            style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 18)),
            child: Text(tr('Tanlash')),
          ),
        ),
      ]),
      if (widget.minDate != null) ...[
        const SizedBox(height: 6),
        Text(trArgs('Eng erta sana: {d}', {'d': dateDisplay(widget.minDate)}),
            style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
      ],
      const SizedBox(height: 12),
      Row(children: [
        _nav(Icons.keyboard_double_arrow_left, tr('Oldingi yil'), () => _shift(-12)),
        _nav(Icons.chevron_left, tr('Oldingi oy'), () => _shift(-1)),
        Expanded(
          child: Text('${monthName(_month.month)} ${_month.year}',
              key: const Key('date-month-title'),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
        ),
        _nav(Icons.chevron_right, tr('Keyingi oy'), () => _shift(1)),
        _nav(Icons.keyboard_double_arrow_right, tr('Keyingi yil'), () => _shift(12)),
      ]),
      const SizedBox(height: 6),
      GridView.count(
        crossAxisCount: 7,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        childAspectRatio: 1.0,
        children: cells,
      ),
    ]);
  }

  Widget _nav(IconData icon, String tip, VoidCallback onTap) => IconButton(
        tooltip: tip,
        constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
        onPressed: onTap,
        icon: Icon(icon),
      );

  Widget _day(String iso, int d, String? selected) {
    final ok = _allowed(iso);
    final isSel = iso == selected;
    return Semantics(
      button: ok,
      selected: isSel,
      label: dateDisplay(iso),
      child: InkWell(
        key: Key('date-day-$iso'),
        customBorder: const CircleBorder(),
        onTap: ok ? () => Navigator.of(context).pop(iso) : null,
        child: Container(
          margin: const EdgeInsets.all(2),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isSel ? AppColors.accent : null,
          ),
          child: Text('$d',
              style: TextStyle(
                fontSize: 15,
                fontWeight: isSel ? FontWeight.w800 : FontWeight.w600,
                color: isSel ? Colors.white : (ok ? AppColors.text : AppColors.faint),
                decoration: ok ? null : TextDecoration.lineThrough,
              )),
        ),
      ),
    );
  }
}
