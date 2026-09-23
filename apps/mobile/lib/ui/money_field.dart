import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n.dart';
import '../qty.dart';
import '../theme.dart';

/// Groups the whole part in thousands with spaces while typing
/// (`1234567` -> `1 234 567`), allows 2 decimals (or none with [wholeOnly])
/// and keeps the cursor on the same digit.
class MoneyInputFormatter extends TextInputFormatter {
  /// Creates the formatter.
  MoneyInputFormatter({this.wholeOnly = false})
      : _re = wholeOnly ? RegExp(r'^\d*$') : RegExp(r'^\d*([.,]\d{0,2})?$');

  /// Whole som only (payments are whole som).
  final bool wholeOnly;
  final RegExp _re;
  static final RegExp _sp = RegExp(r'[\s ]');

  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    final raw = newValue.text.replaceAll(_sp, '');
    if (raw.isEmpty) return const TextEditingValue(text: '', selection: TextSelection.collapsed(offset: 0));
    if (!_re.hasMatch(raw)) return oldValue;
    final sep = raw.indexOf(RegExp('[.,]'));
    var whole = sep < 0 ? raw : raw.substring(0, sep);
    final rest = sep < 0 ? '' : raw.substring(sep);
    whole = whole.replaceFirst(RegExp(r'^0+(?=\d)'), '');
    final b = StringBuffer();
    for (var i = 0; i < whole.length; i++) {
      if (i > 0 && (whole.length - i) % 3 == 0) b.write(' ');
      b.write(whole[i]);
    }
    final text = '$b$rest';
    // Keep the cursor before the same number of non-space characters.
    final end = newValue.selection.end < 0 ? newValue.text.length : newValue.selection.end.clamp(0, newValue.text.length);
    final after = newValue.text.substring(end).replaceAll(_sp, '').length;
    var pos = text.length, seen = 0;
    while (pos > 0 && seen < after) {
      pos--;
      if (text[pos] != ' ') seen++;
    }
    return TextEditingValue(text: text, selection: TextSelection.collapsed(offset: pos));
  }
}

/// Money input with a numeric keyboard, thousands grouping and the currency
/// suffix. [wholeOnly] (default) accepts whole som only — debt and supplier
/// payments are whole som. [onChanged] reports a [NumParse] in CENTS.
class MoneyField extends StatelessWidget {
  /// Creates the field.
  const MoneyField({
    super.key,
    required this.controller,
    this.label,
    this.hint,
    this.errorText,
    this.helperText,
    this.onChanged,
    this.onSubmitted,
    this.focusNode,
    this.textInputAction,
    this.wholeOnly = true,
    this.allowZero = false,
    this.enabled = true,
    this.autofocus = false,
    this.currency = true,
  });

  /// Text controller.
  final TextEditingController controller;

  /// Floating label.
  final String? label;

  /// Placeholder.
  final String? hint;

  /// Inline error.
  final String? errorText;

  /// Helper line.
  final String? helperText;

  /// Parsed value (cents) after every edit.
  final ValueChanged<NumParse>? onChanged;

  /// Keyboard action.
  final ValueChanged<String>? onSubmitted;

  /// Focus node.
  final FocusNode? focusNode;

  /// Keyboard action button.
  final TextInputAction? textInputAction;

  /// Whole som only.
  final bool wholeOnly;

  /// Zero allowed.
  final bool allowZero;

  /// Editable.
  final bool enabled;

  /// Focus on first build.
  final bool autofocus;

  /// Show the currency suffix.
  final bool currency;

  /// Current parsed value (cents) of [controller].
  NumParse get parsed => parseMoney(controller.text, wholeOnly: wholeOnly, allowZero: allowZero);

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      focusNode: focusNode,
      enabled: enabled,
      autofocus: autofocus,
      keyboardType: TextInputType.numberWithOptions(decimal: !wholeOnly),
      textInputAction: textInputAction ?? TextInputAction.next,
      inputFormatters: [MoneyInputFormatter(wholeOnly: wholeOnly)],
      onChanged: onChanged == null
          ? null
          : (t) => onChanged!(parseMoney(t, wholeOnly: wholeOnly, allowZero: allowZero)),
      onSubmitted: onSubmitted,
      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        helperText: helperText,
        errorText: errorText,
        errorMaxLines: 3,
        suffixText: currency ? tr('so‘m') : null,
        suffixStyle: TextStyle(color: AppColors.muted),
        constraints: const BoxConstraints(minHeight: 48),
      ),
    );
  }
}
