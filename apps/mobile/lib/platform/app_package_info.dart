import 'package:package_info_plus/package_info_plus.dart';

/// The app's own version as installed (Android: the APK; web: `version.json`
/// generated from the pubspec — only meaningful when both are cut from the
/// same `x.y.z+build`).
class AppVersion {
  /// Creates the value.
  const AppVersion(this.version, this.buildNumber);

  /// `x.y.z`.
  final String version;

  /// The build number after `+`.
  final String buildNumber;
}

/// `package_info_plus` is web-safe, so ONE adapter.
abstract class AppPackageInfo {
  /// The active adapter (tests inject a fake).
  static AppPackageInfo instance = const PluginAppPackageInfo();

  /// The installed version; null when the platform cannot tell. Never throws.
  Future<AppVersion?> read();
}

/// `package_info_plus`-backed default.
class PluginAppPackageInfo implements AppPackageInfo {
  /// Creates the default.
  const PluginAppPackageInfo();

  @override
  Future<AppVersion?> read() async {
    try {
      final p = await PackageInfo.fromPlatform();
      return AppVersion(p.version, p.buildNumber);
    } catch (_) {
      return null;
    }
  }
}
