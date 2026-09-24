import 'package:flutter/material.dart';

import '../api.dart';
import '../platform/platform.dart';
import '../theme.dart';
import 'tokens.dart';

/// A permanent, unmissable strip saying that this build does NOT talk to
/// production.
///
/// Production is the older server SHA carrying the live merchant tenant. Until
/// Phase 5G.1 a "staging" and a "production" APK were byte-identical, both
/// defaulted to production, and nothing on screen said which server was in
/// use — a pilot tester was one tap away from writing into live merchant data
/// with no cue at all.
///
/// The environment is a BUILD-TIME fact ([Env], from
/// `--dart-define=BINOS_ENV=…`), never a runtime guess, so the marker cannot
/// be switched on or off by anything the operator does.
///
/// In a production build [wrap] returns its child untouched: no strip, no
/// extra widget, no layout change — the production tree is exactly what it was
/// before this phase.
class EnvBadge extends StatelessWidget {
  /// Creates the strip (only rendered by [wrap]).
  const EnvBadge({super.key});

  /// Forces the marker on/off in widget tests. `null` (always, in a real
  /// build) means "ask the compile-time [Env]".
  @visibleForTesting
  static bool? debugStagingOverride;

  /// Whether this build must wear the marker.
  static bool get visible => debugStagingOverride ?? Env.isStaging;

  /// The environment name on the marker. A build cut with a non-production
  /// `BINOS_ENV` shows that name; a test-forced marker shows `STAGING`.
  static String get label => (Env.isProduction ? 'staging' : Env.envName).toUpperCase();

  /// The host this build is actually talking to right now — the build-time
  /// base, or the operator's stored override if one is in force.
  static String get host {
    final h = Uri.tryParse(Api.baseUrl)?.host ?? '';
    return h.isEmpty ? Api.baseUrl : h;
  }

  /// Puts the marker above [child] in a non-production build; returns [child]
  /// itself in production.
  static Widget wrap(BuildContext context, Widget child) {
    if (!visible) return child;
    return Column(children: [
      const EnvBadge(),
      // The strip already consumed the status-bar inset, so whatever is below
      // must not pad for it a second time.
      Expanded(child: MediaQuery.removePadding(context: context, removeTop: true, child: child)),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    if (!visible) return const SizedBox.shrink();
    return Material(
      key: const Key('env-badge'),
      color: AppColors.warnSoft,
      child: SafeArea(
        bottom: false,
        child: Container(
          width: double.infinity,
          constraints: const BoxConstraints(minHeight: 24),
          padding: const EdgeInsets.symmetric(horizontal: kGutter, vertical: 4),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.warn))),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            const Icon(Icons.science_outlined, size: 14, color: AppColors.warn),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                '$label · $host',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: AppColors.warn),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
