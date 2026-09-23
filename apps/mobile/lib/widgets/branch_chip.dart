import 'package:flutter/material.dart';

import '../l10n.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';

/// Shows the branch a branch-scoped screen is working in ("Filial: Chilonzor").
/// When the operator may switch (more than one active visible branch) a tap
/// opens [showBranchSwitcher]. Rebuilds on every [Session] change.
class BranchChip extends StatelessWidget {
  /// Creates the chip.
  const BranchChip({super.key, this.session, this.onChanged});

  /// Session to show (default [Session.instance]).
  final Session? session;

  /// Called after the branch was switched.
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    final s = session ?? Session.instance;
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) {
        final b = s.currentBranch;
        final name = b?.name ?? tr('Filial tanlanmagan');
        final can = s.canSwitchBranch;
        return Semantics(
          button: can,
          label: trArgs('Filial: {name}', {'name': name}),
          child: InkWell(
            key: const Key('branch-chip'),
            borderRadius: BorderRadius.circular(20),
            onTap: can
                ? () async {
                    final changed = await showBranchSwitcher(context, session: s);
                    if (changed) onChanged?.call();
                  }
                : null,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: kMinTouch),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                alignment: Alignment.centerLeft,
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.store_mall_directory_outlined, size: 18, color: AppColors.accentStrong),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text2)),
                  ),
                  if (can) Icon(Icons.expand_more, size: 18, color: AppColors.muted),
                ]),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Bottom sheet listing the selectable branches; returns true when the
/// branch was changed. Switching clears every branch-scoped cache
/// ([Session.selectBranch]).
Future<bool> showBranchSwitcher(BuildContext context, {Session? session}) async {
  final s = session ?? Session.instance;
  final picked = await showAppSheet<String>(
    context,
    title: tr('Filialni tanlang'),
    builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
      for (final b in s.selectableBranches)
        Semantics(
          inMutuallyExclusiveGroup: true,
          checked: b.id == s.currentBranchId,
          button: true,
          child: InkWell(
            key: Key('branch-option-${b.id}'),
            onTap: () => Navigator.of(ctx).pop(b.id),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 56),
              child: Row(children: [
                Icon(b.id == s.currentBranchId ? Icons.radio_button_checked : Icons.radio_button_off,
                    color: b.id == s.currentBranchId ? AppColors.accentStrong : AppColors.muted),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text(b.name, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700)),
                    if (s.actorBranch?.id == b.id)
                      Text(tr('Sizning asosiy filialingiz'), style: TextStyle(fontSize: 12, color: AppColors.muted)),
                  ]),
                ),
              ]),
            ),
          ),
        ),
    ]),
  );
  if (picked == null || picked == s.currentBranchId) return false;
  await s.selectBranch(picked);
  return true;
}
