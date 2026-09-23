import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import 'app_sheet.dart';
import 'tokens.dart';

/// Class-style entry point: `ConfirmDestructive.show(context, ...)` ==
/// [confirmDestructive].
abstract final class ConfirmDestructive {
  /// See [confirmDestructive].
  static Future<bool> show(
    BuildContext context, {
    required String title,
    required String message,
    List<String> details = const [],
    String? confirmLabel,
    String? cancelLabel,
    bool requireAcknowledge = false,
    String? acknowledgeText,
    String? typedPhrase,
  }) =>
      confirmDestructive(context,
          title: title,
          message: message,
          details: details,
          confirmLabel: confirmLabel,
          cancelLabel: cancelLabel,
          requireAcknowledge: requireAcknowledge,
          acknowledgeText: acknowledgeText,
          typedPhrase: typedPhrase);
}

/// Asks for an explicit confirmation of an irreversible action (write-off,
/// cancelling a receiving, a correction that moves money).
///
/// * [details] — bullet lines stating exactly what will change;
/// * [requireAcknowledge] — a checkbox ([acknowledgeText]) must be ticked;
/// * [typedPhrase] — the operator must type this word (case-insensitive).
///
/// Resolves to `true` ONLY when the red confirm button was pressed.
Future<bool> confirmDestructive(
  BuildContext context, {
  required String title,
  required String message,
  List<String> details = const [],
  String? confirmLabel,
  String? cancelLabel,
  bool requireAcknowledge = false,
  String? acknowledgeText,
  String? typedPhrase,
}) async {
  final r = await showAppSheet<bool>(
    context,
    title: title,
    builder: (ctx) => _ConfirmBody(
      message: message,
      details: details,
      confirmLabel: confirmLabel ?? tr('Tasdiqlash'),
      cancelLabel: cancelLabel ?? tr('Bekor qilish'),
      requireAcknowledge: requireAcknowledge,
      acknowledgeText: acknowledgeText ?? tr('Tushundim, bu amalni qaytarib bo‘lmaydi'),
      typedPhrase: typedPhrase,
    ),
  );
  return r == true;
}

class _ConfirmBody extends StatefulWidget {
  const _ConfirmBody({
    required this.message,
    required this.details,
    required this.confirmLabel,
    required this.cancelLabel,
    required this.requireAcknowledge,
    required this.acknowledgeText,
    required this.typedPhrase,
  });

  final String message, confirmLabel, cancelLabel, acknowledgeText;
  final List<String> details;
  final bool requireAcknowledge;
  final String? typedPhrase;

  @override
  State<_ConfirmBody> createState() => _ConfirmBodyState();
}

class _ConfirmBodyState extends State<_ConfirmBody> {
  bool _ack = false;
  final _typed = TextEditingController();

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  bool get _ready {
    if (widget.requireAcknowledge && !_ack) return false;
    final p = widget.typedPhrase;
    if (p != null && _typed.text.trim().toLowerCase() != p.trim().toLowerCase()) return false;
    return true;
  }

  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Icon(Icons.warning_amber_rounded, color: AppColors.danger, size: 26),
        const SizedBox(width: 10),
        Expanded(child: Text(widget.message, style: TextStyle(fontSize: 15, height: 1.35, color: AppColors.text))),
      ]),
      if (widget.details.isNotEmpty) ...[
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final d in widget.details)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('•  ', style: TextStyle(color: AppColors.muted)),
                  Expanded(child: Text(d, style: TextStyle(fontSize: 14, color: AppColors.text2))),
                ]),
              ),
          ]),
        ),
      ],
      if (widget.requireAcknowledge) ...[
        const SizedBox(height: 8),
        InkWell(
          key: const Key('confirm-ack'),
          onTap: () => setState(() => _ack = !_ack),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: kMinTouch),
            child: Row(children: [
              Icon(_ack ? Icons.check_box : Icons.check_box_outline_blank,
                  color: _ack ? AppColors.danger : AppColors.muted),
              const SizedBox(width: 10),
              Expanded(child: Text(widget.acknowledgeText, style: const TextStyle(fontSize: 14))),
            ]),
          ),
        ),
      ],
      if (widget.typedPhrase != null) ...[
        const SizedBox(height: 12),
        TextField(
          key: const Key('confirm-typed'),
          controller: _typed,
          autocorrect: false,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(
            labelText: trArgs('Tasdiqlash uchun «{w}» deb yozing', {'w': widget.typedPhrase}),
          ),
        ),
      ],
      const SizedBox(height: 16),
      SizedBox(
        height: kPrimaryButtonHeight,
        child: ElevatedButton(
          key: const Key('confirm-yes'),
          onPressed: _ready ? () => Navigator.of(context).pop(true) : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.danger,
            disabledBackgroundColor: AppColors.surface,
            disabledForegroundColor: AppColors.muted,
          ),
          child: Text(widget.confirmLabel),
        ),
      ),
      const SizedBox(height: 8),
      SizedBox(
        height: kMinTouch,
        child: TextButton(
          key: const Key('confirm-no'),
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(widget.cancelLabel),
        ),
      ),
    ]);
  }
}
