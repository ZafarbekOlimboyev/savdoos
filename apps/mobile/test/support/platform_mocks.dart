// Platform-channel mocks for the plugins the app touches: shared_preferences,
// flutter_secure_storage, path_provider, local_auth, package_info_plus and the
// app's own `savdoos/secure` (FLAG_SECURE) channel.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class PlatformMocks {
  PlatformMocks._();

  /// In-memory secure storage contents.
  static final Map<String, String> secure = {};

  /// Calls made on `savdoos/secure` (`on` / `off`).
  static final List<String> secureScreenCalls = [];

  /// What `local_auth` reports.
  static bool biometricsAvailable = false;

  static Directory? _tmp;

  /// Installs every mock; call from `setUp`.
  static void install({Map<String, Object> prefs = const {}, Map<String, String> secureValues = const {}}) {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues(prefs);
    secure
      ..clear()
      ..addAll(secureValues);
    secureScreenCalls.clear();
    biometricsAvailable = false;
    _tmp ??= Directory.systemTemp.createTempSync('savdoos_test_');
    final m = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    m.setMockMethodCallHandler(const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'), (call) async {
      final a = (call.arguments as Map?)?.cast<String, dynamic>() ?? const {};
      switch (call.method) {
        case 'read':
          return secure[a['key']];
        case 'write':
          secure[a['key'] as String] = a['value'] as String;
          return null;
        case 'delete':
          secure.remove(a['key']);
          return null;
        case 'deleteAll':
          secure.clear();
          return null;
        case 'readAll':
          return Map<String, String>.from(secure);
        case 'containsKey':
          return secure.containsKey(a['key']);
      }
      return null;
    });

    m.setMockMethodCallHandler(const MethodChannel('plugins.flutter.io/path_provider'), (call) async => _tmp!.path);

    m.setMockMethodCallHandler(const MethodChannel('plugins.flutter.io/local_auth'), (call) async {
      switch (call.method) {
        case 'isDeviceSupported':
        case 'deviceSupportsBiometrics':
          return biometricsAvailable;
        case 'getAvailableBiometrics':
          return biometricsAvailable ? <String>['fingerprint'] : <String>[];
        case 'authenticate':
          return false;
        case 'stopAuthentication':
          return true;
      }
      return null;
    });

    m.setMockMethodCallHandler(const MethodChannel('savdoos/secure'), (call) async {
      secureScreenCalls.add(call.method);
      return null;
    });

    m.setMockMethodCallHandler(const MethodChannel('dev.fluttercommunity.plus/package_info'), (call) async => {
          'appName': 'SavdoOS',
          'packageName': 'com.savdoos.savdoos_mobile',
          'version': '0.6.30',
          'buildNumber': '55',
          'buildSignature': '',
        });
  }

  /// Directory `path_provider` returns.
  static Directory get tempDir => _tmp ??= Directory.systemTemp.createTempSync('savdoos_test_');
}
