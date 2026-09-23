import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import 'tokens.dart';

/// Shows a themed modal bottom sheet (drag handle, optional title with a
/// 48 dp close button, keyboard-aware, at most [maxHeightFactor] of the screen).
///
/// [builder] gets the SHEET's context — pop it with `Navigator.pop(ctx, value)`
/// to return a value. With [scrollable] the content scrolls when it is taller
/// than the sheet (forms with many fields); pass `false` when the content
/// scrolls by itself (a long `ListView`).
Future<T?> showAppSheet<T>(
  BuildContext context, {
  required WidgetBuilder builder,
  String? title,
  bool isDismissible = true,
  bool scrollable = true,
  double maxHeightFactor = 0.9,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    isDismissible: isDismissible,
    enableDrag: isDismissible,
    backgroundColor: AppColors.card,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
    builder: (ctx) {
      final mq = MediaQuery.of(ctx);
      final content = Builder(builder: builder);
      return Padding(
        padding: EdgeInsets.only(bottom: mq.viewInsets.bottom),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: mq.size.height * maxHeightFactor),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const SizedBox(height: 10),
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)),
              ),
            ),
            if (title != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(kGutter, 6, 4, 0),
                child: Row(children: [
                  Expanded(
                    child: Semantics(
                      header: true,
                      child: Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                    ),
                  ),
                  if (isDismissible)
                    IconButton(
                      tooltip: tr('Yopish'),
                      constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                      onPressed: () => Navigator.of(ctx).pop(),
                      icon: Icon(Icons.close, color: AppColors.muted),
                    ),
                ]),
              )
            else
              const SizedBox(height: 8),
            Flexible(
              child: scrollable
                  ? SingleChildScrollView(
                      padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, kGutter),
                      child: content,
                    )
                  : Padding(padding: const EdgeInsets.only(bottom: 8), child: content),
            ),
          ]),
        ),
      );
    },
  );
}
