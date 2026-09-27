/*
 * BinOS PWA — engine bootstrap (Phase 5G.1, package C1).
 *
 * `flutter build web` renders this file as a TEMPLATE: the `flutter_js` token
 * below is replaced by the pinned SDK's `flutter.js`, and the
 * `flutter_build_config` token by the generated build config (which carries
 * `"useLocalCanvasKit": true` when the build runs with
 * `--no-web-resources-cdn` — dropping that line is how a build silently goes
 * back to fetching CanvasKit from gstatic). Everything below the tokens is
 * ours.
 *
 * The substitution is a plain text replace over the WHOLE file, comments
 * included, so this comment must never spell a token out: writing one here
 * pastes a second copy of flutter.js into the artefact (measured: a build
 * whose comment named the token produced a 22,840 B flutter_bootstrap.js with
 * flutter.js in it twice; naming it in prose gives 13,365 B and one copy).
 *
 * The repo owns this file for ONE reason: the default template asks
 * `flutter.js` to manage a service worker, and that would take ours away.
 *
 *   default template (flutter_tools lib/src/web/bootstrap.dart):
 *       _flutter.loader.load({ serviceWorkerSettings: { serviceWorkerVersion: … } });
 *
 *   flutter.js, this build (minified; reformatted):
 *       loadServiceWorker(e) {
 *         if (!e || !("serviceWorker" in navigator)) return Promise.resolve();
 *         let t = () => navigator.serviceWorker.register(`flutter_service_worker.js?v=${r}`)…;
 *         return e.serviceWorkerUrl != null
 *             ? (warn(), t())
 *             : navigator.serviceWorker.getRegistration().then(r => r ? t() : Promise.resolve());
 *       }
 *
 * With a version but no URL it registers Flutter's worker **whenever any
 * registration already exists** — which ours does from the second visit on,
 * at the same `/` scope, so Flutter's script replaces it. And Flutter 3.44's
 * worker is the self-unregistering stub (815 bytes: skipWaiting, then
 * unregister + reload every client). The return visit would therefore drop
 * the offline shell and force a reload, possibly under an operator who is in
 * the middle of a receiving document.
 *
 * So: no `serviceWorkerSettings`. `web/pwa.js` registers `sw.js` itself, with
 * the update flow the operator controls. Build with `--pwa-strategy=none` as
 * well, so the stub is not even emitted; `scripts/pwa_postbuild.mjs` fails the
 * build if either guard is missing from the artefact.
 *
 * FONTS — deliberately NOT configured here, and this is the honest place to
 * say why. `_flutter.loader.load({config: {fontFallbackBaseUrl: "fonts/"}})`
 * does work (the engine reads it: `configuration.dart:358` falls back to
 * Google's font CDN only when the config leaves it unset, and
 * `canvaskit/fonts.dart:14` builds the default Roboto URL from it). What is
 * missing is not the lever but the font tree: pointing it at our origin makes
 * the engine fetch EVERY font from us, and the app renders four glyphs that
 * no font we may redistribute from this toolchain contains — `→` and `✓` in
 * the UI strings (`lib/l10n/l10n.dart`), `👍` in two "nothing to show" lines,
 * and `📊` in the export header. Today those come from Noto via the CDN; with
 * a local base URL that has no Noto they would become boxes. Roboto Regular
 * (the only redistributable font in the pinned SDK) covers Latin, Greek and
 * 255/256 Cyrillic, but none of those four. Closing this properly means
 * bundling ONE font with the product's glyph coverage as a Flutter asset in
 * `pubspec.yaml` + `lib/theme.dart` — outside this package's ownership. See
 * apps/mobile/README.md ("Shriftlar").
 */
{{flutter_js}}
{{flutter_build_config}}
_flutter.loader.load();
