// Lifecycle adapter (B4 item 1): one normalisation of AppLifecycleState for
// every platform. Android synthesises `hidden` around `paused`; web never
// enters `paused` at all (a hidden tab is `hidden`). Screens must see ONE
// background event and ONE foreground event per cycle, on both.
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';

List<bool?> feed(LifecycleGate g, List<AppLifecycleState> states) => [for (final s in states) g.feed(s)];

void main() {
  test('Android cycle: inactive/hidden/paused collapse into one background, resumed into one foreground', () {
    final g = LifecycleGate();
    expect(
      feed(g, [
        AppLifecycleState.resumed, // already active: no event
        AppLifecycleState.inactive,
        AppLifecycleState.hidden,
        AppLifecycleState.paused,
        AppLifecycleState.hidden, // Android synthesises hidden again on the way back
        AppLifecycleState.inactive,
        AppLifecycleState.resumed,
      ]),
      [null, false, null, null, null, null, true],
    );
  });

  test('web cycle: a hidden tab (never paused) stops the camera exactly once', () {
    final g = LifecycleGate();
    expect(feed(g, [AppLifecycleState.inactive, AppLifecycleState.hidden, AppLifecycleState.resumed]), [false, null, true]);
  });

  test('detached counts as background; a fresh gate is active (the camera auto-starts)', () {
    final g = LifecycleGate();
    expect(g.isActive, isTrue);
    expect(g.feed(AppLifecycleState.detached), isFalse);
    expect(g.isActive, isFalse);
  });

  test('lifecyclePhase: the three-way view used by screens that treat inactive differently', () {
    expect(lifecyclePhase(AppLifecycleState.resumed), LifecyclePhase.active);
    expect(lifecyclePhase(AppLifecycleState.inactive), LifecyclePhase.inactive);
    for (final s in [AppLifecycleState.hidden, AppLifecycleState.paused, AppLifecycleState.detached]) {
      expect(lifecyclePhase(s), LifecyclePhase.hidden, reason: '$s');
    }
  });
}
