import 'package:flutter/foundation.dart';

/// Which kind of build is running — a fact, never a policy (see platform.dart).
class AppPlatform {
  AppPlatform._();

  /// True only for the native iOS app — never for the PWA opened in Safari on
  /// an iPhone, and never on Android, macOS or desktop.
  ///
  /// Reads `defaultTargetPlatform`, which widget tests can override; dart:io's
  /// `Platform.isIOS` would always read "not iOS" under `flutter test`.
  static bool get isNativeIos => isNativeIosFor(isWeb: kIsWeb, platform: defaultTargetPlatform);

  /// [isNativeIos] for an explicit build: lets tests cover the web case, where
  /// `kIsWeb` is a compile-time constant.
  @visibleForTesting
  static bool isNativeIosFor({required bool isWeb, required TargetPlatform platform}) =>
      !isWeb && platform == TargetPlatform.iOS;
}
