/// Platform adapter layer — the ONLY door from the app to a native plugin,
/// `dart:io` or a browser API.
///
/// Rules (Phase 5G.1 / B4, pinned by `test/platform_boundary_test.dart`):
///
///  * business code (`lib/api/**`, `session`, `permissions`, `errors`, screens)
///    never imports a plugin; it talks to an interface from this barrel;
///  * an adapter that needs different code per platform is selected by a
///    CONDITIONAL IMPORT in its interface file
///    (`x_stub.dart` / `if (dart.library.io) x_io.dart` /
///    `if (dart.library.js_interop) x_web.dart`), never by `kIsWeb` around an
///    import; `kIsWeb` is used only for pure-Dart flags inside this layer;
///  * every adapter exposes an honest capability flag (`isHardwareBacked`,
///    `supported`, `hasTorch`, …) so the UI can tell the truth instead of
///    failing silently;
///  * every adapter has a mutable `instance` for tests
///    (`test/support/fake_platform.dart`), which is how the same widget tests
///    run on the VM today and under `flutter test --platform chrome` later;
///  * the existing screen seams (`scannerBuilder`, `receiptShare`,
///    `debugPicker`) stay — the adapters supply their DEFAULTS.
///
/// Nothing in this layer decides policy: e.g. [SecretStore.isHardwareBacked]
/// is `false` on web, and what the app does about that (session-only token,
/// hidden PIN settings, …) is the PWA-security package's decision.
library;

export 'app_package_info.dart';
export 'biometrics.dart';
export 'env.dart';
export 'file_export.dart';
export 'image_capture.dart';
export 'lifecycle.dart';
export 'local_cache.dart';
export 'platform_error.dart';
export 'scanner.dart';
export 'secret_store.dart';
export 'sharing.dart';
