import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../qty.dart';
import '../theme.dart';

/// Accepts digits and ONE decimal separator (`,` or `.`) with at most
/// [maxDecimals] digits after it. An edit that would break the rule is
/// rejected (the previous text stays) — nothing is ever rounded.
class DecimalInputFormatter extends TextInputFormatter {
  /// Creates the formatter.
  DecimalInputFormatter({this.maxDecimals = 3})
      : _re = maxDecimals == 0 ? RegExp(r'^\d*$') : RegExp('^\\d*([.,]\\d{0,$maxDecimals})?\$');

  /// Allowed decimals (0 = whole numbers only).
  final int maxDecimals;
  final RegExp _re;

  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    final cleaned = newValue.text.replaceAll(RegExp(r'[\s ]'), '');
    if (!_re.hasMatch(cleaned)) return oldValue;
    if (cleaned == newValue.text) return newValue;
    return TextEditingValue(text: cleaned, selection: TextSelection.collapsed(offset: cleaned.length));
  }
}

/// Quantity input: numeric keyboard with a decimal key, comma or dot, at most
/// 3 decimals, optional unit suffix. Report validity through [onChanged]
/// (a [NumParse] in milli) and show errors with [errorText].
class QtyField extends StatelessWidget {
  /// Creates the field.
  const QtyField({
    super.key,
    required this.controller,
    this.label,
    this.hint,
    this.unit,
    this.errorText,
    this.helperText,
    this.onChanged,
    this.onSubmitted,
    this.focusNode,
    this.textInputAction,
    this.allowZero = false,
    this.enabled = true,
    this.autofocus = false,
  });

  /// Text controller (the raw typed text).
  final TextEditingController controller;

  /// Floating label.
  final String? label;

  /// Placeholder.
  final String? hint;

  /// Unit shown as a suffix (`kg`, `dona`).
  final String? unit;

  /// Inline error (null = none).
  final String? errorText;

  /// Helper line under the field.
  final String? helperText;

  /// Called with the parsed value after every edit.
  final ValueChanged<NumParse>? onChanged;

  /// Keyboard action.
  final ValueChanged<String>? onSubmitted;

  /// Focus node (first-error focus).
  final FocusNode? focusNode;

  /// Keyboard action button.
  final TextInputAction? textInputAction;

  /// Zero is a valid value (stock counts).
  final bool allowZero;

  /// Editable.
  final bool enabled;

  /// Focus on first build.
  final bool autofocus;

  /// Current parsed value of [controller].
  NumParse get parsed => parseQty(controller.text, allowZero: allowZero);

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      focusNode: focusNode,
      enabled: enabled,
      autofocus: autofocus,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      textInputAction: textInputAction ?? TextInputAction.next,
      inputFormatters: [DecimalInputFormatter(maxDecimals: 3)],
      onChanged: onChanged == null ? null : (t) => onChanged!(parseQty(t, allowZero: allowZero)),
      onSubmitted: onSubmitted,
      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        helperText: helperText,
        errorText: errorText,
        errorMaxLines: 3,
        suffixText: unit,
        suffixStyle: TextStyle(color: AppColors.muted),
        constraints: const BoxConstraints(minHeight: 48),
      ),
    );
  }
}
