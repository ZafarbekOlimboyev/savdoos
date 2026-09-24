// Env — build-time environment (B4 item 4).
//
// The production URL must survive a forgotten `--dart-define` (every pilot
// phone would otherwise point at nothing), the stored-preference override must
// obey the same normalisation rules as the build-time value, and the URL
// constant must live in ONE place (`lib/platform/env.dart`), not in `Api`.
// VM only: scans lib/ sources for the production URL literal.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/platform/platform.dart';

import 'support/support.dart';

const kProd = 'https://savdoos-production.up.railway.app';

/// What THIS test run was compiled with (empty in the normal run; the proof
/// run passes `--dart-define=BINOS_API_BASE=… --dart-define=BINOS_ENV=staging`).
const _defBase = String.fromEnvironment('BINOS_API_BASE');
const _defEnv = String.fromEnvironment('BINOS_ENV');

void main() {
  setUp(() async => resetCore());

  _buildBaseTests();

  test('without a --dart-define the API base is the production server, verbatim', () {
    if (_defBase.isNotEmpty || _defEnv.isNotEmpty) {
      // Proof run with defines: the define wins, normalised, and the name is honoured.
      expect(Env.apiBaseUrl, Env.resolveApiBase(_defBase));
      expect(Env.envName, _defEnv.trim().toLowerCase());
      expect(Env.isStaging, _defEnv.trim().toLowerCase() == 'staging');
      return;
    }
    expect(Env.apiBaseUrl, kProd);
    expect(Env.apiBaseUrl, isNotEmpty);
    expect(Env.envName, 'production');
    expect(Env.isStaging, isFalse);
    expect(Env.isProduction, isTrue);
  });

  test('a build define is applied at compile time (both runs must agree with the define)', () {
    // `buildBase` — AYNI qoida: manzil yo'q va muhit production EMAS bo'lsa,
    // production serveriga TUSHMAYDI (5G.1 review, android-release).
    expect(Env.apiBaseUrl, Env.buildBase(_defBase, _defEnv));
    expect(Env.isProduction, _defEnv.trim().isEmpty || _defEnv.trim().toLowerCase() == 'production');
    expect(Env.apiBaseUrl, isNotEmpty, reason: 'an empty define can never leave the app without a server');
  });

  test('an empty or malformed value never yields an empty base; empty means "the build-time base"', () {
    // Empty operator input / stored pref = no override -> the BUILD-TIME base
    // (production without a define, the define otherwise). Caught red by the
    // define run: it used to fall back to the production constant.
    expect(Env.resolveApiBase(''), Env.apiBaseUrl);
    expect(Env.resolveApiBase('   '), Env.apiBaseUrl);
    expect(Env.resolveApiBase('/'), Env.apiBaseUrl);
    if (_defBase.isEmpty) expect(Env.resolveApiBase(''), kProd);
    expect(Env.resolveApiBase('staging.example.com/api/v1/'), 'https://staging.example.com');
    expect(Env.resolveApiBase('http://10.0.2.2:8000/'), 'http://10.0.2.2:8000');
  });

  test('Api.normalizeBaseUrl delegates to Env (one rule set)', () {
    expect(Api.normalizeBaseUrl(''), Env.apiBaseUrl);
    expect(Api.normalizeBaseUrl('shop.uz/'), Env.resolveApiBase('shop.uz/'));
  });

  test('the stored server preference is normalised on load like the build-time value', () async {
    await resetCore(prefs: {'base_url': 'http://10.0.2.2:8000/'});
    await Api.load();
    expect(Api.baseUrl, 'http://10.0.2.2:8000', reason: 'a trailing slash in an old pref must not double up in URLs');
    expect(Api.uri('/health').toString(), 'http://10.0.2.2:8000/api/v1/health');
  });

  test('an empty stored preference falls back to the build-time base', () async {
    await resetCore(prefs: {'base_url': ''});
    await Api.load();
    expect(Api.baseUrl, Env.apiBaseUrl);
  });

  test('the production URL literal lives only in lib/platform/env.dart', () {
    final offenders = <String>[];
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      final p = f.path.replaceAll('\\', '/');
      if (!p.endsWith('.dart') || p.endsWith('lib/platform/env.dart')) continue;
      if (f.readAsStringSync().contains('savdoos-production.up.railway.app')) offenders.add(p);
    }
    expect(offenders, isEmpty, reason: 'hard-coded server URL outside Env: $offenders');
  });
}

// ── Yiqilgan relizdan himoya (5G.1 review, android-release) ─────────────────
//
// Reliz uzun buyruqni nusxalash bilan chiqariladi. BITTA bayroq tushib qolsa
// (`--dart-define=BINOS_API_BAS=…`, yoki shell davom qatorini yeb qo'ysa)
// ilgari APK STAGING lentasini taqib, JONLI production serveriga yozardi.
// Muhit ham, manzil ham AYNI kompilyatsiya faktidan kelgani uchun — muhit
// fallback'ni ham hal qiladi.
void _buildBaseTests() {
  group('buildBase: muhit fallback\'ni hal qiladi', () {
    test('production build, manzilsiz -> production serveri (avvalgidek)', () {
      expect(Env.buildBase('', ''), Env.kProductionApiBase);
      expect(Env.buildBase('', 'production'), Env.kProductionApiBase);
      expect(Env.buildBase('  ', 'PRODUCTION'), Env.kProductionApiBase);
    });

    test('staging build, manzilsiz -> HECH QAYERGA bormaydigan manzil', () {
      expect(Env.buildBase('', 'staging'), Env.kUnsetNonProductionBase);
      expect(Env.buildBase('   ', 'Staging'), Env.kUnsetNonProductionBase);
      expect(Env.buildBase('', 'qa'), Env.kUnsetNonProductionBase,
          reason: 'production emas EKAN — production serveriga tushmaydi');
      expect(Env.buildBase('', 'staging'), isNot(Env.kProductionApiBase));
    });

    test('manzil berilgan bo\'lsa — muhitdan QAT\'I NAZAR o\'sha manzil', () {
      expect(Env.buildBase('https://savdoos-staging.up.railway.app', 'staging'),
          'https://savdoos-staging.up.railway.app');
      expect(Env.buildBase('savdoos-staging.up.railway.app/api/v1/', 'staging'),
          'https://savdoos-staging.up.railway.app');
      expect(Env.buildBase(Env.kProductionApiBase, 'production'), Env.kProductionApiBase);
    });
  });
}
