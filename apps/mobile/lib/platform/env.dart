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

  // ══ MAXFIYLIK SIYOSATI MANZILI (CH-17B) ══════════════════════════════════

  static const String _definedPrivacyUrl = String.fromEnvironment('BINOS_PRIVACY_URL');

  /// The published privacy policy URL, or `''` when it is not configured.
  ///
  /// ⚠️  THERE IS NO DEFAULT, ON PURPOSE. [kProductionApiBase] can have one
  ///     because a wrong-but-reachable API only costs a failed request; a
  ///     GUESSED policy URL would ship a dead or wrong legal link to the App
  ///     Store, which is exactly the review failure we are trying to avoid.
  ///     The address is owner-supplied (`--dart-define=BINOS_PRIVACY_URL=…`);
  ///     until it exists, [releaseBlockers] refuses the release.
  static String get privacyPolicyUrl => normalizePrivacyUrl(_definedPrivacyUrl);

  /// True when a usable policy address is compiled into this build.
  static bool get isPrivacyPolicyConfigured => privacyPolicyUrl.isNotEmpty;

  /// Validates an owner-supplied policy address; returns `''` when unusable.
  ///
  /// Stricter than [resolveApiBase] on purpose — this link is shown to the
  /// public and to App Review, so a scheme is NEVER guessed:
  ///   * `https` only (Apple serves review over the public internet; `http`
  ///     would be downgraded or blocked by ATS);
  ///   * a real registrable host (must contain a dot) — `localhost`,
  ///     `127.0.0.1`, `*.local`, `*.invalid` and bare hostnames are refused,
  ///     so a developer machine address can never become the public link;
  ///   * no embedded credentials.
  @visibleForTesting
  static String normalizePrivacyUrl(String raw) {
    final s = raw.trim();
    if (s.isEmpty) return '';
    final u = Uri.tryParse(s);
    if (u == null || u.scheme.toLowerCase() != 'https') return '';
    final host = u.host.toLowerCase();
    if (host.isEmpty || !host.contains('.')) return '';
    if (host == '127.0.0.1' || host == '::1' || host.endsWith('.local') ||
        host.endsWith('.invalid') || host.endsWith('.localhost') ||
        host == 'localhost') {
      return '';
    }
    if (u.userInfo.isNotEmpty) return '';
    return s.replaceAll(RegExp(r'/+$'), '');
  }

  // ══ RELEASE DARVOZASI (CH-17B) ═══════════════════════════════════════════

  /// Reasons this build must NOT be archived for the App Store. Empty = clear.
  ///
  /// A pure function of the compile-time facts so an ordinary test can cover
  /// every combination, including the ones a release can only be cut with once
  /// ([buildBase] follows the same approach).
  @visibleForTesting
  static List<String> releaseBlockers({
    required String apiBase,
    required String envName,
    required String privacyUrl,
  }) {
    final out = <String>[];
    final env = envName.trim().toLowerCase();
    final isProd = env.isEmpty || env == 'production';

    if (normalizePrivacyUrl(privacyUrl).isEmpty) {
      out.add('BINOS_PRIVACY_URL is missing or not a valid public https URL '
          '(Apple requires a working privacy policy link)');
    }
    if (!isProd) {
      out.add('BINOS_ENV is "$env" — an App Store archive must be production');
    }
    final base = apiBase.trim().toLowerCase();
    final bu = Uri.tryParse(base);
    final bh = bu?.host.toLowerCase() ?? '';
    if (base.isEmpty) {
      out.add('BINOS_API_BASE resolved to an empty address');
    } else if (bh == 'localhost' || bh == '127.0.0.1' || bh == '::1' ||
        bh.endsWith('.local') || bh.endsWith('.localhost')) {
      out.add('BINOS_API_BASE points at a developer machine ($bh)');
    } else if (bh.endsWith('.invalid')) {
      out.add('BINOS_API_BASE is the unconfigured sentinel ($bh)');
    } else if (base.startsWith('http://')) {
      out.add('BINOS_API_BASE is plain http — release traffic must be https');
    }
    return out;
  }

  /// [releaseBlockers] for the defines this binary was compiled with.
  static List<String> get releaseBlockersForThisBuild => releaseBlockers(
        apiBase: apiBaseUrl,
        envName: envName,
        privacyUrl: _definedPrivacyUrl,
      );

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
