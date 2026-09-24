/// Build-time environment — the one place the server address and the
/// environment name are decided (`--dart-define=BINOS_API_BASE=…`,
/// `--dart-define=BINOS_ENV=staging|production`).
///
/// * A build cut WITHOUT a define is a production build pointed at the
///   production server, verbatim ([Env.kProductionApiBase]) — a forgotten
///   flag on an Android release can never point the pilot phones at nothing.
/// * An empty or blank define is treated as "not given" for the same reason.
/// * The operator's stored server preference (Settings) still overrides the
///   build-time base; both go through [Env.resolveApiBase], so one rule set.
///
/// Presentation of the environment (a staging banner) is NOT done here.
library;

import 'package:flutter/foundation.dart';

class Env {
  Env._();

  /// The live production API (Railway). Kept verbatim as the default.
  static const String kProductionApiBase = 'https://savdoos-production.up.railway.app';

  static const String _definedApiBase = String.fromEnvironment('BINOS_API_BASE');
  static const String _definedEnv = String.fromEnvironment('BINOS_ENV');

  /// The address a build that is NOT production falls back to when its
  /// `BINOS_API_BASE` define is missing or mistyped. It resolves nowhere on
  /// purpose: a "staging" APK must fail loudly rather than write receivings,
  /// cash and write-offs into the live merchant's tenant.
  static const String kUnsetNonProductionBase = 'https://server-not-configured.invalid';

  /// The API base of this build (normalised, never empty): the define, else —
  /// for a PRODUCTION build only — the production server.
  ///
  /// A release is cut by copying a long command; dropping or mistyping ONE
  /// flag (`--dart-define=BINOS_API_BAS=…`, a shell that ate the continuation
  /// line) used to produce an APK that wore the STAGING strip and talked to
  /// production. The environment is the same compile-time fact as the strip,
  /// so it decides the fallback too: no address, no production.
  static String get apiBaseUrl => buildBase(_definedApiBase, _definedEnv);

  /// [apiBaseUrl] as a pure function of the two defines, so every combination
  /// (including the ones a release build can never be cut with twice) is
  /// covered by an ordinary test.
  @visibleForTesting
  static String buildBase(String definedBase, String definedEnv) {
    final s = _normalize(definedBase);
    if (s.isNotEmpty) return s;
    final e = definedEnv.trim().toLowerCase();
    return (e.isEmpty || e == 'production') ? kProductionApiBase : kUnsetNonProductionBase;
  }

  /// `staging` or `production` (default). Lower-cased, trimmed.
  static String get envName {
    final e = _definedEnv.trim().toLowerCase();
    return e.isEmpty ? 'production' : e;
  }

  /// True for a staging build (`BINOS_ENV=staging`).
  static bool get isStaging => envName == 'staging';

  /// True for a production build (the default).
  static bool get isProduction => envName == 'production';

  /// Normalises an operator-entered / stored server address with the SAME
  /// rules as the build define: trims, drops trailing slashes and a pasted
  /// `/api/v1`, adds `https://` when no scheme is given. Empty input means
  /// "no override" -> the build-time base ([apiBaseUrl]) — NOT the production
  /// constant, or a staging build with a blank preference would silently talk
  /// to production.
  static String resolveApiBase(String raw) {
    final s = _normalize(raw);
    return s.isEmpty ? apiBaseUrl : s;
  }

  static String _normalize(String raw) {
    var s = raw.trim();
    if (s.isEmpty) return '';
    s = s.replaceAll(RegExp(r'/+$'), '');
    s = s.replaceFirst(RegExp(r'/api/v1$'), '');
    if (s.isEmpty) return '';
    if (!RegExp(r'^[a-zA-Z][a-zA-Z0-9+.-]*://').hasMatch(s)) s = 'https://$s';
    return s;
  }
}
