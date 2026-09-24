// Real-backend E2E harness (Phase 5G, M6).
//
// The app runs exactly as shipped (real screens, real `Api`, real `Session`);
// only the transport is swapped for a REAL HTTP client that talks to the
// backend started by `e2e/mobile/start_backend.py` (see `e2e/mobile/README.md`).
//
// Why a custom client: `flutter_test` runs widget tests in a fake-async zone
// and installs a mock `HttpOverrides` that answers 400 to everything. The
// client here (1) clears that override, (2) performs every request — socket,
// TLS, body — in the ROOT zone so no fake timer is ever left behind, and (3)
// counts requests in flight so the test can wait until the network is idle
// ([settle] / [waitFor]) instead of `pumpAndSettle`, which cannot see real I/O.
//
// Files in this folder are NOT `*_test.dart` on purpose: a plain
// `flutter test` never picks them up (no skip, no fake green). They run only
// through `e2e/mobile/run_e2e.py` or explicitly:
//
//   flutter test test/e2e/flows_e2e.dart \
//     --dart-define=E2E_BASE=http://127.0.0.1:8010 \
//     --dart-define=E2E_MANIFEST=<repo>/e2e/mobile/.run/manifest.json
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:mobile_scanner/mobile_scanner.dart' show MobileScannerErrorCode;
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/main.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/receiving_item_editor_screen.dart';
import 'package:savdoos_mobile/session.dart';

import '../support/platform_mocks.dart';
import '../support/pump.dart';

/// Backend base URL (`--dart-define=E2E_BASE=http://127.0.0.1:8010`).
const String kE2EBase = String.fromEnvironment('E2E_BASE');

/// Scenario manifest written by the backend (`--dart-define=E2E_MANIFEST=...`).
const String kE2EManifest = String.fromEnvironment('E2E_MANIFEST');

/// A port nothing listens on (connectivity tests): the TCP connect is refused.
const String kDeadBase = 'http://127.0.0.1:9';

// ══ Scenario manifest ═══════════════════════════════════════════════════════

/// The seeded tenant (`e2e/mobile/scenario.py`).
class Scenario {
  Scenario._(this.raw);

  /// Raw JSON.
  final Map<String, dynamic> raw;

  static Scenario? _instance;

  /// Loads (once) and validates the manifest; fails LOUDLY when the run is
  /// not configured — an E2E run without a backend must never look green.
  static Scenario get I {
    final s = _instance;
    if (s != null) return s;
    if (kE2EBase.isEmpty) {
      throw StateError('E2E_BASE is not set. Run through e2e/mobile/run_e2e.py, or pass '
          '--dart-define=E2E_BASE=http://127.0.0.1:8010 --dart-define=E2E_MANIFEST=<path>.');
    }
    final path = kE2EManifest.isNotEmpty ? kE2EManifest : '../../e2e/mobile/.run/manifest.json';
    final f = File(path);
    if (!f.existsSync()) throw StateError('E2E manifest not found: ${f.absolute.path}');
    final j = (jsonDecode(f.readAsStringSync()) as Map).cast<String, dynamic>();
    if (j['version'] != 1) throw StateError('Unknown manifest version ${j['version']}');
    return _instance = Scenario._(j);
  }

  Map<String, dynamic> _m(String k) => (raw[k] as Map).cast<String, dynamic>();

  /// Password of every scenario user.
  String get password => '${raw['password']}';

  /// User by key (`owner`, `omborchi`, `kassir`, `menejer`, `omborchi_b`).
  Map<String, dynamic> user(String k) => (_m('users')[k] as Map).cast<String, dynamic>();

  /// Branch id (`A` / `B`).
  String branchId(String k) => '${(_m('branches')[k] as Map)['id']}';

  /// Branch name (`A` / `B`).
  String branchName(String k) => '${(_m('branches')[k] as Map)['name']}';

  /// Product by key (see `scenario.PRODUCTS`).
  Map<String, dynamic> product(String k) => (_m('products')[k] as Map).cast<String, dynamic>();

  /// Product id by key.
  String pid(String k) => '${product(k)['id']}';

  /// Product name by key.
  String pname(String k) => '${product(k)['name']}';

  /// Cash account by key (`till_a`, `safe_a`, `till_b`, `safe_b`, `till_a_archived`).
  Map<String, dynamic> account(String k) => (_m('accounts')[k] as Map).cast<String, dynamic>();

  /// Section by name.
  Map<String, dynamic> section(String k) => _m(k);
}

// ══ Real HTTP transport ═════════════════════════════════════════════════════

/// One request as the app sent it.
class E2ECall {
  E2ECall(this.method, this.url, this.body);

  final String method;
  final Uri url;
  final String? body;
  int? status;
  String? response;
  Object? error;

  /// The server answered, but the answer was withheld from the app
  /// ([E2EClient.loseNextAnswer]).
  bool answerLost = false;

  /// Path relative to `/api/v1`.
  String get path => url.path.startsWith('/api/v1') ? url.path.substring(7) : url.path;

  /// JSON request body.
  Map<String, dynamic> get json => (jsonDecode(body!) as Map).cast<String, dynamic>();

  @override
  String toString() => '$method $path ${url.query} -> ${status ?? error}';
}

/// Real client; see the file comment.
class E2EClient extends http.BaseClient {
  E2EClient() : _inner = Zone.root.run(() => IOClient(HttpClient()..connectionTimeout = const Duration(seconds: 10)));

  final http.Client _inner;

  /// Requests the app has in flight.
  static int inFlight = 0;

  /// Every request of the current test, in order.
  static final List<E2ECall> log = [];

  /// Calls of [method] to exactly [path] (relative to `/api/v1`).
  static List<E2ECall> calls(String method, String path) =>
      [for (final c in log) if (c.method == method && c.path == path) c];

  static String? _loseMethod, _losePath;

  /// The NEXT [method] [path] request really reaches the server (which
  /// writes and answers), but the app gets a transport error instead of the
  /// answer — the "lost reply" case that idempotency keys exist for.
  static void loseNextAnswer(String method, String path) {
    _loseMethod = method;
    _losePath = path;
  }

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    final call = E2ECall(request.method, request.url, request is http.Request ? request.body : null);
    log.add(call);
    inFlight++;
    final done = Completer<http.StreamedResponse>();
    Zone.root.run(() async {
      try {
        final r = await _inner.send(request);
        final bytes = await r.stream.toBytes();
        call
          ..status = r.statusCode
          ..response = utf8.decode(bytes, allowMalformed: true);
        if (call.method == _loseMethod && call.path == _losePath) {
          _loseMethod = _losePath = null;
          call.answerLost = true;
          throw http.ClientException('E2E: connection reset after the server answered', request.url);
        }
        done.complete(http.StreamedResponse(Stream<List<int>>.value(bytes), r.statusCode,
            contentLength: bytes.length,
            request: request,
            headers: r.headers,
            reasonPhrase: r.reasonPhrase,
            isRedirect: r.isRedirect,
            persistentConnection: false));
      } catch (e, st) {
        call.error = e;
        done.completeError(e, st);
      } finally {
        inFlight--;
      }
    });
    return done.future;
  }

  @override
  void close() => Zone.root.run(_inner.close);
}

// ══ Server truth (independent of the app) ═══════════════════════════════════

/// Direct API reads with a SEPARATE session: what the server really holds.
class Probe {
  Probe._();

  static final Map<String, String> _tokens = {};

  static Future<Object?> _req(String method, String path,
      {String? token, Object? body, Map<String, String>? query}) async {
    final c = HttpClient();
    try {
      final u = Uri.parse('$kE2EBase/api/v1$path').replace(queryParameters: query);
      final rq = await c.openUrl(method, u);
      rq.headers.set('Accept', 'application/json');
      if (token != null) rq.headers.set('Authorization', 'Bearer $token');
      if (body != null) {
        rq.headers.contentType = ContentType.json;
        rq.write(jsonEncode(body));
      }
      final rs = await rq.close();
      final text = await utf8.decodeStream(rs);
      final data = text.isEmpty ? null : jsonDecode(text);
      if (rs.statusCode >= 300) throw ProbeError(rs.statusCode, data, rs.headers.value('x-error-code'));
      return data;
    } finally {
      c.close(force: true);
    }
  }

  /// Token of the scenario user [who] (cached per run).
  static Future<String> token(String who) async {
    final t = _tokens[who];
    if (t != null) return t;
    final s = Scenario.I;
    final r = await _req('POST', '/auth/login/password',
        body: {'phone': s.user(who)['phone'], 'password': s.password}) as Map;
    return _tokens[who] = '${r['access_token']}';
  }

  /// GET as [who] (real zone: call through [WidgetTester.runAsync] or [probe]).
  static Future<Object?> get(String path, {String who = 'owner', Map<String, String>? query}) async =>
      _req('GET', path, token: await token(who), query: query);

  /// POST as [who].
  static Future<Object?> post(String path, Object body, {String who = 'owner'}) async =>
      _req('POST', path, token: await token(who), body: body);
}

/// A non-2xx answer seen by [Probe].
class ProbeError implements Exception {
  ProbeError(this.status, this.body, this.code);
  final int status;
  final Object? body;
  final String? code;
  @override
  String toString() => 'ProbeError($status, $code, $body)';
}

/// Runs a [Probe] read outside the fake-async zone.
Future<T> probe<T>(WidgetTester t, Future<T> Function() f) async {
  late T out;
  Object? err;
  await t.runAsync(() async {
    try {
      out = await f();
    } catch (e) {
      err = e;
    }
  });
  if (err != null) throw err!;
  return out;
}

/// Runs [f] (a [Probe] call expected to be REFUSED) and returns the refusal;
/// null when the server accepted it.
Future<ProbeError?> probeError(WidgetTester t, Future<Object?> Function() f) => probe(t, () async {
      try {
        await f();
        return null;
      } on ProbeError catch (e) {
        return e;
      }
    });

/// Lots of [productId] in [branchId] as the server holds them (`GET /lots/products/{id}`).
Future<Map<String, dynamic>> serverLots(WidgetTester t, String productId, String branchId) async =>
    ((await probe(t, () => Probe.get('/lots/products/$productId', query: {'branch_id': branchId}))) as Map)
        .cast<String, dynamic>();

/// Branch stock of the scenario product [key] as the server computes it
/// (`GET /products?q=&branch_id=&limit=`).
Future<double> serverStock(WidgetTester t, String key, String branch) async {
  final s = Scenario.I;
  final rows = await probe(t, () => Probe.get('/products',
      query: {'q': s.pname(key), 'branch_id': s.branchId(branch), 'limit': '20'})) as List;
  final row = rows.cast<Map>().firstWhere((r) => r['id'] == s.pid(key));
  return (row['stock'] as num).toDouble();
}

// ══ Test lifecycle ══════════════════════════════════════════════════════════

/// Fake camera for every scanner: a button that "detects" [E2ECamera.next].
class E2ECamera {
  E2ECamera._();

  /// The code the next tap on `e2e-detect` delivers.
  static String next = '';

  /// Scanner view used by the app's test hooks.
  static Widget view(BuildContext ctx, ValueChanged<String> onCode, Widget Function(MobileScannerErrorCode) _) =>
      Center(
        child: ElevatedButton(
          key: const Key('e2e-detect'),
          onPressed: () => onCode(next),
          child: const Text('detect'),
        ),
      );
}

/// Loads the fonts a phone really renders with (Roboto + Material Icons from
/// the Flutter SDK cache). `flutter_test` otherwise draws every glyph as a
/// 1 em square, which makes texts ~2x wider than on the device and turns the
/// 390 dp layout check into noise. Fails loudly when the fonts are missing —
/// the run must not silently fall back to the test font.
Future<void> loadPhoneFonts() async {
  final dir = _materialFontsDir();
  // Fayl nomlari REGISTRGA sezgir emas deb hisoblanmaydi: Windows'da `roboto-regular.ttf`,
  // boshqa SDK yig'malarida `Roboto-Regular.ttf` bo'lishi mumkin va Linux'da bu IKKI XIL fayl.
  final byName = <String, File>{
    for (final e in dir.listSync()) if (e is File) e.uri.pathSegments.last.toLowerCase(): e,
  };
  Future<ByteData> read(String f) async {
    final file = byName[f.toLowerCase()];
    if (file == null) {
      throw StateError('$f not in ${dir.path} (bor: ${byName.keys.take(12).join(", ")})');
    }
    return ByteData.view((await file.readAsBytes()).buffer);
  }

  final roboto = FontLoader('Roboto');
  for (final f in const [
    'roboto-light.ttf',
    'roboto-regular.ttf',
    'roboto-medium.ttf',
    'roboto-bold.ttf',
    'roboto-black.ttf',
    'roboto-italic.ttf',
  ]) {
    if (byName.containsKey(f)) roboto.addFont(read(f));
  }
  await roboto.load();
  await (FontLoader('MaterialIcons')..addFont(read('materialicons-regular.otf'))).load();
  // Proof the real font is active: 10 narrow glyphs are ~35 px in Roboto, 140 px in the test font.
  final probe = TextPainter(
    text: const TextSpan(text: 'iiiiiiiiii', style: TextStyle(fontFamily: 'Roboto', fontSize: 14)),
    textDirection: TextDirection.ltr,
  )..layout();
  final w = probe.width;
  probe.dispose();
  if (w > 80) throw StateError('Roboto did not load (10 x "i" = ${w.toStringAsFixed(1)} px)');
}

/// `roboto-regular.ttf` shu papkadami (fayl nomi registridan QAT'I NAZAR)?
bool _hasRoboto(Directory d) {
  if (!d.existsSync()) return false;
  for (final e in d.listSync(followLinks: false)) {
    if (e is File && e.uri.pathSegments.last.toLowerCase() == 'roboto-regular.ttf') return true;
  }
  return false;
}

Directory _materialFontsDir() {
  // CI (Linux) SDK yig'masida material shriftlar `precache` bilan ham kelmasligi
  // mumkin — o'sha yerda ish oqimi shriftni O'ZI topadi va yo'lni shu
  // o'zgaruvchida beradi (`E2E_FONT_DIR`). U berilgan bo'lsa — YAGONA manba.
  final pinned = Platform.environment['E2E_FONT_DIR'] ?? '';
  if (pinned.isNotEmpty) {
    final d = Directory(pinned);
    if (_hasRoboto(d)) return d;
    throw StateError('E2E_FONT_DIR=$pinned: roboto-regular.ttf topilmadi');
  }
  final candidates = <String>[
    if ((Platform.environment['FLUTTER_ROOT'] ?? '').isNotEmpty)
      '${Platform.environment['FLUTTER_ROOT']}/bin/cache/artifacts/material_fonts',
  ];
  // .../bin/cache/artifacts/engine/<platform>/flutter_tester(.exe)
  var d = File(Platform.resolvedExecutable).parent;
  for (var i = 0; i < 6; i++) {
    candidates.add('${d.path}/material_fonts');
    candidates.add('${d.path}/artifacts/material_fonts');
    d = d.parent;
  }
  for (final c in candidates) {
    final dir = Directory(c);
    if (_hasRoboto(dir)) return dir;
  }
  // Oxirgi chora: SDK keshini REKURSIV qidiramiz. Linux CI'da (`subosito/
  // flutter-action`) artefaktlar boshqa joyda yotadi va yuqoridagi aniq
  // yo'llar tegmaydi — shunda ham HAQIQIY shrift bilan ishlash SHART, aks
  // holda 390 dp tekshiruvi ma'nosiz kvadrat glifларга aylanadi.
  final root = (Platform.environment['FLUTTER_ROOT'] ?? '').isNotEmpty
      ? Directory('${Platform.environment['FLUTTER_ROOT']}/bin/cache')
      : File(Platform.resolvedExecutable).parent.parent.parent.parent;
  if (root.existsSync()) {
    for (final e in root.listSync(recursive: true, followLinks: false)) {
      if (e is File && e.uri.pathSegments.last.toLowerCase() == 'roboto-regular.ttf') {
        return e.parent;
      }
    }
  }
  throw StateError('Roboto not found in the Flutter SDK cache (tried: ${candidates.join(', ')}; '
      'then a recursive search under ${root.path}). Run `flutter precache --universal` once.');
}

/// Resets every singleton to "fresh install pointed at the E2E backend".
Future<void> e2eReset({String lang = 'uz'}) async {
  Scenario.I; // fail loudly before anything else
  PlatformMocks.install();
  HttpOverrides.global = null; // flutter_test's mock answers 400 to every request
  L.code = lang;
  Api.baseUrl = kE2EBase;
  Api.token = null;
  Api.employee = null;
  Api.online.value = true;
  // As in main(): a 401 drops the session and the lock and shows the login screen.
  Api.onSessionExpired = () {
    unawaited(Lock.clear());
    rootNavKey.currentState
        ?.pushAndRemoveUntil(MaterialPageRoute<void>(builder: (_) => const LoginScreen()), (r) => false);
  };
  Session.instance.debugReset();
  await Perm.load();
  await Lock.load();
  ReceivingItemEditorScreen.debugScannerBuilder = E2ECamera.view;
  E2EClient.log.clear();
  E2EClient._loseMethod = E2EClient._losePath = null;
}

/// Registers a real-backend widget test: 390×844 phone, real HTTP, and a
/// teardown that waits for the network before disposing the tree.
void e2eTest(String name, Future<void> Function(WidgetTester t) body,
    {Duration timeout = const Duration(minutes: 4)}) {
  testWidgets(name, (t) async {
    setPhoneViewport(t);
    await http.runWithClient(() async {
      try {
        await body(t);
      } catch (e) {
        _dumpOnFailure(t);
        rethrow;
      } finally {
        await _drain(t);
      }
    }, E2EClient.new);
  }, timeout: Timeout(timeout));
}

void _dumpOnFailure(WidgetTester t) {
  final texts = <String>[];
  for (final e in find.byType(Text).evaluate()) {
    final w = e.widget as Text;
    final s = w.data ?? w.textSpan?.toPlainText();
    if (s != null && s.trim().isNotEmpty) texts.add(s.trim());
  }
  printOnFailure('── visible texts ──\n${texts.take(80).join(' | ')}');
  printOnFailure('── last requests ──\n${E2EClient.log.reversed.take(15).map((c) {
    final resp = (c.response ?? '').length > 300 ? '${c.response!.substring(0, 300)}…' : c.response;
    return '$c ${c.status != null && c.status! >= 300 ? resp : ''}';
  }).join('\n')}');
}

Future<void> _drain(WidgetTester t) async {
  try {
    await settle(t, timeout: const Duration(seconds: 30));
  } catch (_) {/* reported by the test itself */}
  Session.instance.debugReset();
  await t.pumpWidget(const SizedBox.shrink());
  for (var i = 0; i < 20; i++) {
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await t.pump(const Duration(seconds: 1));
    if (E2EClient.inFlight == 0) break;
  }
  Api.onSessionExpired = null;
}

// ══ Waiting ═════════════════════════════════════════════════════════════════

/// One step: let real I/O run, then pump. Fake time advances only while the
/// network is idle, so a slow real answer never trips the app's own timeouts.
Future<void> _step(WidgetTester t) async {
  await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 12)));
  await t.pump(E2EClient.inFlight > 0 ? Duration.zero : const Duration(milliseconds: 50));
}

/// Waits until no request is in flight and the UI stopped changing (debounce
/// timers included: 10 quiet steps = 500 ms of app time).
Future<void> settle(WidgetTester t, {Duration timeout = const Duration(seconds: 40)}) async {
  final sw = Stopwatch()..start();
  var quiet = 0;
  while (sw.elapsed < timeout) {
    await _step(t);
    if (E2EClient.inFlight == 0) {
      quiet++;
      if (quiet >= 10 && !t.binding.hasScheduledFrame) return;
      if (quiet >= 40) return; // network idle, only an endless animation left
    } else {
      quiet = 0;
    }
  }
  throw TimeoutException('network not idle after $timeout (in flight: ${E2EClient.inFlight})');
}

/// Pumps until [f] finds something, then settles. Fails with the screen's
/// texts and the last requests when it never appears.
Future<void> waitFor(WidgetTester t, Finder f,
    {Duration timeout = const Duration(seconds: 20), String? reason}) async {
  final sw = Stopwatch()..start();
  while (f.evaluate().isEmpty) {
    if (sw.elapsed > timeout) {
      throw TestFailure('Timed out after $timeout waiting for $f${reason == null ? '' : ' ($reason)'}');
    }
    await _step(t);
  }
  await settle(t);
}

/// Pumps until [f] finds nothing.
Future<void> waitGone(WidgetTester t, Finder f, {Duration timeout = const Duration(seconds: 40)}) async {
  final sw = Stopwatch()..start();
  while (f.evaluate().isNotEmpty) {
    if (sw.elapsed > timeout) throw TestFailure('Timed out after $timeout waiting for $f to disappear');
    await _step(t);
  }
  await settle(t);
}

// ══ Gestures ════════════════════════════════════════════════════════════════

/// Finder by key string.
Finder k(String key) => find.byKey(Key(key));

/// Scrolls [f] into view, taps it and settles.
Future<void> tap(WidgetTester t, Finder f) async {
  await waitFor(t, f);
  await t.ensureVisible(f.first);
  await t.pump(const Duration(milliseconds: 300));
  await t.tap(f.first, warnIfMissed: false);
  await settle(t);
}

/// Types [text] into the field [f] (replacing its content).
Future<void> type(WidgetTester t, Finder f, String text) async {
  await waitFor(t, f);
  await t.ensureVisible(f.first);
  await t.pump(const Duration(milliseconds: 300));
  await t.enterText(f.first, text);
  await t.pump();
}

/// Scrolls the first [Scrollable] under [within] until [f] is built, then
/// into view (lazy lists build only what is on screen).
Future<void> scrollTo(WidgetTester t, Finder f, {required Finder within, double delta = 250}) async {
  await waitFor(t, within);
  final scrollable = find.descendant(of: within, matching: find.byType(Scrollable), matchRoot: true).first;
  final pos = t.state<ScrollableState>(scrollable).position;
  for (var i = 0; i < 80 && f.evaluate().isEmpty; i++) {
    if (pos.pixels >= pos.maxScrollExtent) break;
    pos.jumpTo((pos.pixels + delta).clamp(0, pos.maxScrollExtent).toDouble());
    await t.pump();
  }
  await waitFor(t, f);
  await t.ensureVisible(f.first);
  await settle(t);
}

/// Closes the soft keyboard / unfocuses (so sticky bars are not covered).
Future<void> unfocus(WidgetTester t) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await t.testTextInput.receiveAction(TextInputAction.done);
  await t.pump();
}

/// Types a date into the app's date picker opened by [field].
Future<void> pickDate(WidgetTester t, Finder field, DateTime d) async {
  await tap(t, field);
  String two(int v) => v.toString().padLeft(2, '0');
  await t.enterText(k('date-typed'), '${two(d.day)}${two(d.month)}${d.year}');
  await t.pump();
  await tap(t, k('date-typed-ok'));
}

/// The text of the first [Text] under [f].
String textOf(WidgetTester t, Finder f) {
  final txt = find.descendant(of: f, matching: find.byType(Text), matchRoot: true);
  final w = t.widget<Text>(txt.first);
  return w.data ?? w.textSpan!.toPlainText();
}

/// All texts under [f], joined.
String textsUnder(Finder f) => [
      for (final e in find.descendant(of: f, matching: find.byType(Text), matchRoot: true).evaluate())
        ((e.widget as Text).data ?? (e.widget as Text).textSpan?.toPlainText() ?? '')
    ].join(' | ');

// ══ Sign-in and app ═════════════════════════════════════════════════════════

/// Signs [who] in through the real API (no UI) and loads `/auth/context`.
Future<void> signInAs(WidgetTester t, String who) async {
  final s = Scenario.I;
  await t.runAsync(() => Api.login('${s.user(who)['phone']}', s.password));
  expect(Api.loggedIn, isTrue, reason: 'login of $who');
  await t.runAsync(() => Session.instance.load(force: true));
  expect(Session.instance.status, SessionStatus.ready, reason: '/auth/context of $who: ${Session.instance.lastError}');
}

/// Pumps the real app root ([SavdoApp]) and waits for the first screen.
Future<void> pumpApp(WidgetTester t) async {
  await t.pumpWidget(const SavdoApp());
  await settle(t);
}

/// Pumps [screen] as a pushed route over a host (so its back button works).
Future<void> pumpScreen(WidgetTester t, Widget screen) async {
  await t.pumpWidget(testApp(LaunchHost(
      onPressed: (ctx) => Navigator.of(ctx).push(MaterialPageRoute<void>(builder: (_) => screen)))));
  await t.tap(find.text('open'));
  await settle(t);
}

/// Unique tag for this run (batch numbers, notes) — reruns never collide.
final String runTag = 'R${DateTime.now().millisecondsSinceEpoch.toRadixString(36).toUpperCase()}';
