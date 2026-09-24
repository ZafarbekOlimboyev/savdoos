/*
 * SavdoOS PWA \u2014 page-side bootstrap (Phase 5G.1, package C1).
 *
 * Everything executable lives here rather than inline in index.html, so the
 * page can run under `script-src 'self'` with no hash and no nonce.
 *
 * Three jobs, and deliberately nothing else:
 *   1. drop the boot splash once Flutter paints its first frame;
 *   2. localise the one sentence the shell has to say before Dart is alive:
 *      on web the session ends when the app is closed;
 *   3. register the service worker and run the SAFE update flow \u2014 a new build
 *      never swaps itself in under a running session; the operator is offered
 *      a banner and the page reloads only after they accept.
 *
 * It never touches the token, never reads a business endpoint, and never logs
 * anything. Keep it that way: this file runs before the app's own auth code.
 */
(function () {
  'use strict';

  var UPDATE_CHECK_MS = 4 * 60 * 60 * 1000; // same cadence as the desktop apps

  /*
   * FONTS \u2014 a measured gap, deliberately left visible rather than papered over.
   *
   * `--no-web-resources-cdn` self-hosts the CanvasKit ENGINE (verified: the
   * build loads canvaskit/chromium/canvaskit.{js,wasm} from this origin) but it
   * does not cover FONTS. CanvasKit resolves its default and fallback fonts
   * against `fontFallbackBaseUrl`, which defaults to Google's font CDN. On this
   * build, at the login screen it fetched:
   *     uz  (Latin)          -> roboto/v32/KFOmCnqEu92Fr1Me4GZLCzYlKw.woff2
   *     uzc / ru / ky        -> + notosanssc/v37/k3kCo84MPv\u2026HbczS.woff2
   * Those two are the only third-party requests the PWA still makes. They are
   * font fetches (no script execution), so they are a privacy/offline problem,
   * not a supply-chain one.
   *
   * Setting `window.flutterConfiguration.fontFallbackBaseUrl` here does NOT
   * work \u2014 measured: with it set to "fonts/" the engine still fetched from the
   * CDN, because `flutter_bootstrap.js` initialises the engine through
   * `_flutter.loader.load({config})` and that config wins over the legacy
   * window global. The working levers are (a) a hand-written loader that
   * passes `config: { fontFallbackBaseUrl: \u2026 }` plus a vendored font tree, or
   * (b) better, bundling ONE font with the product's glyph coverage as a
   * Flutter asset and making it the default text theme. Both live in
   * pubspec.yaml / lib/theme.dart, outside this package. See
   * apps/mobile/README.md ("Known gap: fonts").
   */

  // The shell has no access to the Dart l10n tables, so it carries only these
  // four strings. `shared_preferences_web` stores the app's language under
  // `flutter.savdoos_lang` as a JSON string (measured in the B-phase audit).
  var STRINGS = {
    uz: {
      session: 'Brauzer/iPhone versiyasi: ilovani yopsangiz, qaytadan kirish so\u2018raladi.',
      update: 'Yangi versiya tayyor.',
      apply: 'Yangilash'
    },
    uzc: {
      session: '\u0411\u0440\u0430\u0443\u0437\u0435\u0440/iPhone \u0432\u0435\u0440\u0441\u0438\u044f\u0441\u0438: \u0438\u043b\u043e\u0432\u0430\u043d\u0438 \u0451\u043f\u0441\u0430\u043d\u0433\u0438\u0437, \u049b\u0430\u0439\u0442\u0430\u0434\u0430\u043d \u043a\u0438\u0440\u0438\u0448 \u0441\u045e\u0440\u0430\u043b\u0430\u0434\u0438.',
      update: '\u042f\u043d\u0433\u0438 \u0432\u0435\u0440\u0441\u0438\u044f \u0442\u0430\u0439\u0451\u0440.',
      apply: '\u042f\u043d\u0433\u0438\u043b\u0430\u0448'
    },
    ru: {
      session: '\u0412\u0435\u0440\u0441\u0438\u044f \u0434\u043b\u044f \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430/iPhone: \u043f\u043e\u0441\u043b\u0435 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f \u043d\u0443\u0436\u043d\u043e \u0431\u0443\u0434\u0435\u0442 \u0432\u043e\u0439\u0442\u0438 \u0437\u0430\u043d\u043e\u0432\u043e.',
      update: '\u0413\u043e\u0442\u043e\u0432\u0430 \u043d\u043e\u0432\u0430\u044f \u0432\u0435\u0440\u0441\u0438\u044f.',
      apply: '\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c'
    },
    ky: {
      session: '\u0411\u0440\u0430\u0443\u0437\u0435\u0440/iPhone \u043d\u0443\u0441\u043a\u0430\u0441\u044b: \u0442\u0438\u0440\u043a\u0435\u043c\u0435\u043d\u0438 \u0436\u0430\u043f\u043a\u0430\u043d\u0434\u0430 \u043a\u0430\u0439\u0440\u0430 \u043a\u0438\u0440\u04af\u04af \u0441\u0443\u0440\u0430\u043b\u0430\u0442.',
      update: '\u0416\u0430\u04a3\u044b \u043d\u0443\u0441\u043a\u0430 \u0434\u0430\u044f\u0440.',
      apply: '\u0416\u0430\u04a3\u044b\u0440\u0442\u0443\u0443'
    }
  };

  function strings() {
    var code = 'uz';
    try {
      var raw = window.localStorage.getItem('flutter.savdoos_lang');
      if (raw) {
        try { raw = JSON.parse(raw); } catch (e) { /* stored unquoted */ }
        if (STRINGS[raw]) code = raw;
      }
    } catch (e) {
      // Private mode / blocked storage: fall back to the default language.
    }
    return STRINGS[code];
  }

  function applyStrings() {
    var s = strings();
    var notice = document.getElementById('binos-session-notice');
    if (notice) notice.textContent = s.session;
    var text = document.getElementById('binos-update-text');
    if (text) text.textContent = s.update;
    var apply = document.getElementById('binos-update-apply');
    if (apply) apply.textContent = s.apply;
  }

  function removeSplash() {
    var splash = document.getElementById('binos-splash');
    if (splash && splash.parentNode) splash.parentNode.removeChild(splash);
  }

  applyStrings();
  window.addEventListener('flutter-first-frame', removeSplash);

  if (!('serviceWorker' in navigator)) return;

  // Only a page that was ALREADY controlled may reload on a controller swap.
  // On a first install `clients.claim()` also fires controllerchange, and
  // reloading there would restart a login the operator just started.
  var hadController = !!navigator.serviceWorker.controller;
  var reloading = false;

  navigator.serviceWorker.addEventListener('controllerchange', function () {
    if (!hadController || reloading) return;
    reloading = true;
    window.location.reload();
  });

  function offerUpdate(worker) {
    var banner = document.getElementById('binos-update-banner');
    var apply = document.getElementById('binos-update-apply');
    if (!banner || !apply || !worker) return;
    banner.hidden = false;
    apply.onclick = function () {
      banner.hidden = true;
      worker.postMessage('SKIP_WAITING');
    };
  }

  function watch(registration) {
    // A build that finished installing while the tab was closed waits here.
    if (registration.waiting && navigator.serviceWorker.controller) {
      offerUpdate(registration.waiting);
    }
    registration.addEventListener('updatefound', function () {
      var installing = registration.installing;
      if (!installing) return;
      installing.addEventListener('statechange', function () {
        if (installing.state === 'installed' && navigator.serviceWorker.controller) {
          offerUpdate(installing);
        }
      });
    });
  }

  window.addEventListener('load', function () {
    navigator.serviceWorker.register('sw.js').then(function (registration) {
      watch(registration);
      setInterval(function () { registration.update(); }, UPDATE_CHECK_MS);
      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') registration.update();
      });
    }).catch(function () {
      // No worker means no offline shell \u2014 the app still works online, which
      // is the honest degradation. Never block the boot on this.
    });
  });
})();
