import 'package:flutter/material.dart';

import '../theme.dart';
import 'tokens.dart';

/// The screen's primary action pinned to the bottom (above the keyboard when
/// placed as the last child of the body `Column`, or as
/// `Scaffold.bottomNavigationBar`).
///
/// * [busy] shows a spinner and blocks double taps (writes are single-flight);
/// * when [enabled] is false and [disabledReason] is set, the reason is shown
///   ABOVE the button — a disabled button never appears without an explanation;
/// * [summary] (e.g. a document total) sits above the buttons.
class StickyActionBar extends StatelessWidget {
  /// Creates the bar.
  const StickyActionBar({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.busy = false,
    this.enabled = true,
    this.disabledReason,
    this.summary,
    this.secondaryLabel,
    this.onSecondary,
    this.danger = false,
  });

  /// Primary button label.
  final String label;

  /// Primary action.
  final VoidCallback? onPressed;

  /// Optional leading icon of the primary button.
  final IconData? icon;

  /// A write is in flight: spinner + disabled.
  final bool busy;

  /// False disables the primary button.
  final bool enabled;

  /// Why the primary action is not available (shown when disabled).
  final String? disabledReason;

  /// Optional content above the buttons (totals, hints).
  final Widget? summary;

  /// Optional secondary (outlined) action.
  final String? secondaryLabel;

  /// Secondary action.
  final VoidCallback? onSecondary;

  /// Red primary button (destructive action).
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final active = enabled && !busy && onPressed != null;
    final reason = (!enabled && (disabledReason ?? '').isNotEmpty) ? disabledReason : null;
    return Material(
      color: AppColors.card,
      child: DecoratedBox(
        decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
        child: SafeArea(
          top: false,
          minimum: const EdgeInsets.only(bottom: 8),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 10, kGutter, 4),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (summary != null) ...[summary!, const SizedBox(height: 10)],
              if (reason != null) ...[
                Semantics(
                  liveRegion: true,
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.info_outline, size: 18, color: AppColors.warn),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(reason, key: const Key('sticky-reason'), style: TextStyle(fontSize: 13, color: AppColors.text2)),
                    ),
                  ]),
                ),
                const SizedBox(height: 10),
              ],
              Row(children: [
                if (secondaryLabel != null) ...[
                  Expanded(
                    child: SizedBox(
                      height: kPrimaryButtonHeight,
                      child: OutlinedButton(
                        key: const Key('sticky-secondary'),
                        onPressed: busy ? null : onSecondary,
                        style: OutlinedButton.styleFrom(
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadius)),
                        ),
                        child: Text(secondaryLabel!, maxLines: 1, overflow: TextOverflow.ellipsis),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  flex: secondaryLabel != null ? 2 : 1,
                  child: SizedBox(
                    height: kPrimaryButtonHeight,
                    child: ElevatedButton(
                      key: const Key('sticky-primary'),
                      onPressed: active ? onPressed : null,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        backgroundColor: danger ? AppColors.danger : AppColors.accent,
                        disabledBackgroundColor: AppColors.surface,
                        disabledForegroundColor: AppColors.muted,
                      ),
                      child: busy
                          ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                          : Row(mainAxisSize: MainAxisSize.min, children: [
                              if (icon != null) ...[Icon(icon, size: 20), const SizedBox(width: 8)],
                              Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis)),
                            ]),
                    ),
                  ),
                ),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}
