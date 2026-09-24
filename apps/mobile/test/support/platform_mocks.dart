// Platform layer for tests: injects the in-memory fakes of `lib/platform`
// (`fake_platform.dart`) and mocks the two remaining method channels
// (`path_provider` for the io LocalCache adapter, the app's own
// `savdoos/secure` FLAG_SECURE channel). Platform-neutral: no `dart:io` here —
// a temp directory is created lazily, only when `path_provider` is really
// asked (VM), through a conditional import.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_platform.dart';
import 'temp_dir_stub.dart' if (dart.library.io) 'temp_dir_io.dart' as tmp;

class PlatformMocks {
  PlatformMocks._();

  /// In-memory secure storage contents (`SecretStore`).
  static final Map<String, String> secure = {};

  /// Calls made on `savdoos/secure` (`on` / `off`).
  static final List<String> secureScreenCalls = [];

  /// What `Biometrics.available()` reports.
  static bool biometricsAvailable = false;

  /// Whether a biometric prompt succeeds (`Biometrics.authenticate`).
  static bool biometricAccepts = false;

  /// Files handed to `FileExport` (CSV exports).
  static final List<ExportedFile> exports = [];

  /// Texts handed to `Sharing`.
  static final List<String> sharedTexts = [];

  /// What `ImageCapture.pick` returns (null = cancelled).
  static PickedImage? pickedImage;

  /// Installs every fake/mock; call from `setUp`.
  static void install({Map<String, Object> prefs = const {}, Map<String, String> secureValues = const {}}) {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues(prefs);
    secure
      ..clear()
      ..addAll(secureValues);
    secureScreenCalls.clear();
    exports.clear();
    sharedTexts.clear();
    biometricsAvailable = false;
    biometricAccepts = false;
    pickedImage = null;

    SecretStore.instance = FakeSecretStore(secure);
    Biometrics.instance = FakeBiometrics(isAvailable: () => biometricsAvailable, accepts: () => biometricAccepts);
    FileExport.instance = FakeFileExport(exports);
    Sharing.instance = FakeSharing(sharedTexts);
    AppPackageInfo.instance = const FakeAppPackageInfo(AppVersion('0.6.30', '55'));
    ImageCapture.instance = FakeImageCapture(() => pickedImage);
    // Real, platform-selected defaults — a test that injects its own fake must
    // not leak it into the next test.
    LocalCache.instance = createLocalCache();
    Scanner.instance = createScanner();

    final m = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    // The io LocalCache adapter asks path_provider for the support directory.
    m.setMockMethodCallHandler(const MethodChannel('plugins.flutter.io/path_provider'), (call) async => tmp.tempDirPath());

    m.setMockMethodCallHandler(const MethodChannel('savdoos/secure'), (call) async {
      secureScreenCalls.add(call.method);
      return null;
    });
  }

  /// Directory path `path_provider` answers with (VM only; throws on web).
  static String get tempDirPath => tmp.tempDirPath();
}
