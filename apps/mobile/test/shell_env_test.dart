// C2 item 2 — staging and production are told apart at a glance.
//
// Production is the OLDER server SHA carrying the live Fayzan tenant. Until
// now a "staging APK" and a "production APK" were byte-identical, both pointed
// at production, and nothing on screen said which server was in use: a pilot
// tester was one tap away from writing into live merchant data with no cue.
//
// The contract: a build is cut with `--dart-define=BINOS_ENV=…` /
// `BINOS_API_BASE=…` (B4's `Env`); a non-production build wears an unmissable
// marker in the shell and names its environment and API host in Settings; a
// production build shows NEITHER — the production widget tree must be exactly
// what it was before this phase.
//
// Two layers on purpose:
//   * the widget behaviour is driven through `EnvBadge.debugStagingOverride`,
//     so both branches are covered in an ordinary `flutter test` run;
//   * the last test takes the override away and asserts the marker follows the
//     COMPILE-TIME `Env` — it passes in the plain run (production, no marker)
//     and in the `--dart-define=BINOS_ENV=staging` run (marker), which is what
//     proves the build flag is really wired to the UI.
//
// Every "the marker is there" assertion below checks the PLATFORM SEMANTICS
// TREE, not only `find.byKey`. A widget finder walks the widget tree, and the
// widget tree was never what broke: when the marker moved to the app root it
// kept being built and painted, while the route's `ModalBarrier` (which is a
// `BlockSemantics`) deleted its accessibility node — so TalkBack, the web
// semantics DOM and every automated check of a real APK saw a build with no
// marker at all. A test that only asks `find.byKey` cannot tell those two
// worlds apart; `platformSemanticsLabels` can.
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/main.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/ui/ui.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get('/auth/context', (_) => contextJson(role: 'ega', permissions: const ['hisobot.view', 'ombor.view']))
      ..get('/inventory/overview', (_) => {'low_count': 0, 'out_count': 0});
    addTearDown(() {
      EnvBadge.debugStagingOverride = null;
      s.debugReset();
    });
  });

  Future<void> openShell(WidgetTester tester) async {
    signIn();
    await s.load(force: true);
    await pumpAt390(tester, Shell(tabBuilders: {ShellTab.home: (_) => const SizedBox.shrink()}));
    await tester.pumpAndSettle();
  }

  // The marker lives at the APP ROOT (`main.dart`), not in the shell: the
  // screen that asks for the password is exactly where a tester must see which
  // server is being addressed, and an upgraded phone can still carry a stored
  // server address from its previous install.
  group('root marker', () {
    testWidgets('the LOGIN screen of a staging build already names the server', (tester) async {
      final semantics = tester.ensureSemantics();
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      Api.token = null; // not signed in -> the app opens on the login screen
      setPhoneViewport(tester);
      await tester.pumpWidget(const SavdoApp());
      await tester.pump();

      final badge = find.byKey(const Key('env-badge'));
      expect(badge, findsOneWidget, reason: 'the marker must be there BEFORE the password is typed');
      expect(find.descendant(of: badge, matching: find.textContaining('STAGING')), findsOneWidget);
      expect(find.descendant(of: badge, matching: find.textContaining('staging.example.test')), findsOneWidget,
          reason: 'the marker must name the server, not just the word STAGING');

      // ...and the same thing in the tree the ENGINE is handed. This is the
      // assertion a real build can fail: the widget tree above stayed perfect
      // while the accessibility tree lost the marker completely.
      final marker = expectOneStagingNode(tester);
      expect(marker.label, contains('staging.example.test'),
          reason: 'the marker must name the server on the platform side too');
      // The node's OWN size — not its position, which `SemanticsData.rect`
      // expresses in the node's own coordinate space and would make an
      // assertion about the top of the screen very nearly a tautology. Size is
      // what pins `Semantics(container: true)`: without that boundary the
      // label is absorbed by the full-screen node above it, the marker's node
      // becomes the whole app, and a screen reader announces the entire
      // application as "STAGING · <host>".
      final screen = tester.view.physicalSize / tester.view.devicePixelRatio;
      expect(marker.rect.height, greaterThan(0), reason: 'a zero-height strip is an invisible strip');
      expect(marker.rect.height, lessThan(screen.height / 4),
          reason: 'the marker must be its OWN node, the size of the strip — not the whole screen');
      expect(marker.rect.size.height, closeTo(tester.getRect(badge).height, 1.0),
          reason: 'the accessibility node and the painted strip must be the same thing');

      // The strip must also TAKE its space: the login screen is pushed down by
      // it, not hidden under it.
      expect(tester.getRect(badge).top, 0);
      expect(tester.getRect(badge).height, greaterThanOrEqualTo(24));
      semantics.dispose();
    });

    testWidgets('a production build shows nothing and its layout is untouched', (tester) async {
      final semantics = tester.ensureSemantics();
      EnvBadge.debugStagingOverride = false;
      Api.token = null;
      setPhoneViewport(tester);
      await tester.pumpWidget(const SavdoApp());
      await tester.pump();

      expect(find.byKey(const Key('env-badge')), findsNothing);
      expect(find.textContaining('STAGING'), findsNothing);
      expect(find.byType(EnvBadge), findsNothing,
          reason: 'production must not even build the marker widget — no layout change at all');
      expect(platformSemanticsLabels(tester).where((l) => l.contains('STAGING')), isEmpty,
          reason: 'production must not announce an environment to the platform either');
      semantics.dispose();
    });

    testWidgets('the shell draws no second marker of its own', (tester) async {
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      await be.run(() => openShell(tester));
      expect(find.byType(EnvBadge), findsNothing,
          reason: 'the shell pumped alone must carry no marker — one is drawn at the root, '
              'and two would mean two strips on a real phone');
    });
  });

  group('settings', () {
    Future<void> openSettings(WidgetTester tester) async {
      signIn();
      await s.load(force: true);
      await pumpAt390(tester, const SettingsScreen());
      await tester.pumpAndSettle();
    }

    testWidgets('a staging build names the environment and the API host', (tester) async {
      EnvBadge.debugStagingOverride = true;
      Api.baseUrl = 'https://staging.example.test';
      await be.run(() => openSettings(tester));

      final row = find.byKey(const Key('settings-env'));
      expect(row, findsOneWidget);
      expect(find.descendant(of: row, matching: find.textContaining('STAGING')), findsOneWidget);
      expect(find.descendant(of: row, matching: find.textContaining('staging.example.test')), findsOneWidget);
      expectMinTouchTarget(tester, row);
    });

    testWidgets('a production build shows no environment row', (tester) async {
      EnvBadge.debugStagingOverride = false;
      await be.run(() => openSettings(tester));
      expect(find.byKey(const Key('settings-env')), findsNothing);
    });

    testWidgets('the version line carries the build number — the part that tells two builds apart', (tester) async {
      EnvBadge.debugStagingOverride = false;
      await be.run(() => openSettings(tester));
      // The fake package info reports 0.6.30 / build 55. The footer is the
      // last row of a lazy list, so scroll to it first.
      await tester.scrollUntilVisible(find.textContaining('0.6.30'), 300,
          scrollable: find.descendant(of: find.byType(SettingsScreen), matching: find.byType(Scrollable)).first);
      await tester.pumpAndSettle();
      expect(find.textContaining('0.6.30+55'), findsOneWidget,
          reason: 'versionName alone cannot distinguish two builds of the same version');
    });
  });

  // Pumps the REAL app root (`SavdoApp`), because that is where the marker is
  // wrapped. Pumping a screen on its own would prove nothing about the build
  // flag — it would pass in the production run for the wrong reason.
  testWidgets('the marker follows the COMPILE-TIME environment, not a runtime guess', (tester) async {
    final semantics = tester.ensureSemantics();
    EnvBadge.debugStagingOverride = null;
    expect(EnvBadge.visible, Env.isStaging);
    Api.token = null; // login screen: no backend needed
    setPhoneViewport(tester);
    await tester.pumpWidget(const SavdoApp());
    await tester.pump();
    expect(find.byKey(const Key('env-badge')), Env.isStaging ? findsOneWidget : findsNothing,
        reason: 'BINOS_ENV=staging bilan yig‘ilgan ilova ildizida nishon BO‘LISHI shart');
    // The line that stands between this file and a green run over a build that
    // silently wears no marker.
    final reached = platformSemanticsLabels(tester).where((l) => l.contains(EnvBadge.label));
    expect(reached, Env.isStaging ? hasLength(1) : isEmpty,
        reason: 'nishon platformaga (TalkBack / web semantics) YETIB BORISHI shart — '
            'faqat widget daraxtida bo‘lishi yetarli emas');
    semantics.dispose();
  });
}

/// Every label in the semantics tree the framework hands to the ENGINE — the
/// one Android turns into `content-desc` nodes and Flutter web turns into the
/// semantics DOM. Deliberately NOT a widget finder: the regression this file
/// guards against left the widget tree perfect and emptied this tree.
List<String> platformSemanticsLabels(WidgetTester tester) {
  final out = <String>[];
  void walk(SemanticsNode node) {
    final label = node.getSemanticsData().label;
    if (label.isNotEmpty) out.add(label);
    node.visitChildren((child) {
      walk(child);
      return true;
    });
  }

  for (final view in tester.binding.renderViews) {
    final root = view.debugSemantics;
    if (root != null) walk(root);
  }
  return out;
}

/// The one semantics node that carries the marker — or a failed expectation
/// naming exactly what a real build would be missing.
SemanticsData expectOneStagingNode(WidgetTester tester) {
  final hits = <SemanticsData>[];
  void walk(SemanticsNode node) {
    final data = node.getSemanticsData();
    if (data.label.contains('STAGING')) hits.add(data);
    node.visitChildren((child) {
      walk(child);
      return true;
    });
  }

  for (final view in tester.binding.renderViews) {
    final root = view.debugSemantics;
    if (root != null) walk(root);
  }
  expect(hits, hasLength(1),
      reason: 'the platform accessibility tree must carry the marker exactly once; found '
          '${hits.length}. A marker that is painted but has no semantics node is invisible to '
          'TalkBack and to every check that can be run against a real build.');
  return hits.single;
}
