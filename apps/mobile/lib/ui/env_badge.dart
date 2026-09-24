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
  ///
  /// PAINT ORDER IS LOAD-BEARING. The flex runs upwards and the strip is its
  /// LAST child, so the strip is laid out at the top of the screen but painted
  /// AFTER the app content. That is not a style choice:
  ///
  /// every `Navigator` route hangs a `ModalBarrier` underneath its page, and
  /// `ModalBarrier` is a `BlockSemantics` — it deletes the accessibility nodes
  /// of everything painted BEFORE it under the same semantics parent. With the
  /// strip painted first (a plain `Column`, as Phase 5G.1 first wrote it) the
  /// strip was still on screen, but the platform accessibility tree — what
  /// TalkBack reads, what the web semantics DOM contains, what every automated
  /// check of a real build can see — contained no trace of it. The app looked
  /// like a production build to everything except a human eye.
  ///
  /// Painting the strip last puts it outside the barrier's reach. Widget
  /// finders cannot notice the difference (they walk the widget tree, which
  /// was correct all along), so the contract is pinned by the SEMANTICS
  /// assertions in `test/shell_env_test.dart`.
  static Widget wrap(BuildContext context, Widget child) {
    if (!visible) return child;
    return Column(
      verticalDirection: VerticalDirection.up,
      children: [
        // The strip already consumed the status-bar inset, so whatever is
        // below must not pad for it a second time.
        Expanded(child: MediaQuery.removePadding(context: context, removeTop: true, child: child)),
        const EnvBadge(),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!visible) return const SizedBox.shrink();
    // `container: true` gives the strip an accessibility node of its OWN,
    // sized like the strip. Without it the label is absorbed by the
    // full-screen node above it, which reads as if the whole app were called
    // "STAGING · …".
    return Semantics(
      container: true,
      child: Material(
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
      ),
    );
  }
}
