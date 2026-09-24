import 'package:flutter/widgets.dart';

/// One normalisation of [AppLifecycleState] for every platform (pure Dart).
///
/// * Android synthesises `hidden` around `paused` (`inactive → hidden → paused`
///   and back), so a naive observer stops/starts a camera twice per cycle.
/// * Web NEVER enters `paused` ("only entered on iOS and Android" — SDK doc);
///   a hidden tab is `hidden`. A screen that only handles `paused` keeps its
///   camera streaming in a background tab.
///
/// [LifecycleGate] collapses both into ONE background and ONE foreground
/// event; [lifecyclePhase] is the three-way view for code that treats
/// `inactive` (a system dialog over the app) differently from `hidden`.
enum LifecyclePhase {
  /// `resumed`.
  active,

  /// `inactive` — still visible, not focused (permission dialog, share sheet).
  inactive,

  /// `hidden` / `paused` / `detached` — not visible.
  hidden,
}

/// Three-way phase of [state].
LifecyclePhase lifecyclePhase(AppLifecycleState state) => switch (state) {
      AppLifecycleState.resumed => LifecyclePhase.active,
      AppLifecycleState.inactive => LifecyclePhase.inactive,
      AppLifecycleState.hidden || AppLifecycleState.paused || AppLifecycleState.detached => LifecyclePhase.hidden,
    };

/// De-duplicating active/not-active gate. Starts ACTIVE (the app is in the
/// foreground when a screen is built).
class LifecycleGate {
  bool _active = true;

  /// Whether the app is currently `resumed`.
  bool get isActive => _active;

  /// Feeds one state; returns `true` when the app just became active, `false`
  /// when it just left the foreground, `null` when nothing changed.
  bool? feed(AppLifecycleState state) {
    final active = state == AppLifecycleState.resumed;
    if (active == _active) return null;
    _active = active;
    return active;
  }
}
