// C2 item 3 — the Android permission surface is exactly what the app needs,
// every entry is documented, and this phase adds nothing.
//
// The audit resolved the real numbers off a genuine AGP-produced merged
// manifest: compileSdk 36 / minSdk 24 / targetSdk 36, with three permissions
// DECLARED by the app and three more merged in from transitive AARs that
// nobody declared and nobody had written down. Those three still show in the
// phone's permission list and in any Play data-safety review, so they belong
// in the manifest as a comment — otherwise the next person reads the app
// manifest, sees three, looks at the phone, sees six, and has no way to tell
// which are ours.
//
// This test is a ratchet: adding a permission fails it on purpose.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Every permission the app itself declares. Nothing else may be added
/// without a deliberate change here AND a comment in the manifest.
const Set<String> kDeclared = {
  'android.permission.INTERNET', // backend
  'android.permission.CAMERA', // mobile_scanner + image_picker (invoice photo)
  'android.permission.USE_BIOMETRIC', // local_auth app lock
};

/// Permissions merged into the final APK from transitive AARs
/// (`androidx.biometric`, Play services / ML Kit via `mobile_scanner`).
/// All benign; all must be named in a manifest comment.
const List<String> kMergedFromAars = [
  'android.permission.USE_FINGERPRINT',
  'android.permission.ACCESS_NETWORK_STATE',
  'DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION',
];

final RegExp _usesPermission = RegExp(r'<uses-permission[^>]*android:name="([^"]+)"');

String _read(String p) => File(p).readAsStringSync();

Set<String> _permissionsIn(String xml) => {for (final m in _usesPermission.allMatches(xml)) m[1]!};

void main() {
  const mainManifest = 'android/app/src/main/AndroidManifest.xml';
  final main = _read(mainManifest);

  test('the app declares exactly the permissions it needs — nothing new in this phase', () {
    expect(_permissionsIn(main), kDeclared);
  });

  test('every declared permission is documented with a comment right above it', () {
    final lines = main.split('\n');
    final undocumented = <String>[];
    for (var i = 0; i < lines.length; i++) {
      final m = _usesPermission.firstMatch(lines[i]);
      if (m == null) continue;
      var j = i - 1;
      while (j >= 0 && lines[j].trim().isEmpty) {
        j--;
      }
      if (j < 0 || !lines[j].trim().endsWith('-->')) undocumented.add(m[1]!);
    }
    expect(undocumented, isEmpty, reason: 'no comment explains: $undocumented');
  });

  test('the permissions merged in from plugin AARs are written down in the manifest', () {
    final missing = [for (final p in kMergedFromAars) if (!main.contains(p)) p];
    expect(missing, isEmpty,
        reason: 'these reach the phone through transitive AARs and appear in the app\'s permission list, '
            'but the manifest says nothing about them: $missing');
  });

  test('the debug and profile variants add only INTERNET (Flutter tooling)', () {
    for (final v in ['debug', 'profile']) {
      expect(_permissionsIn(_read('android/app/src/$v/AndroidManifest.xml')), {'android.permission.INTERNET'},
          reason: v);
    }
  });

  test('cleartext HTTP stays blocked: no opt-out and no network security config', () {
    expect(main, isNot(contains('usesCleartextTraffic')),
        reason: 'the platform default at targetSdk >= 28 is cleartext-blocked; do not widen it');
    expect(main, isNot(contains('android:networkSecurityConfig')));
    expect(File('android/app/src/main/res/xml/network_security_config.xml').existsSync(), isFalse);
  });

  test('backup and device transfer stay locked down (the token and prefs never leave the phone)', () {
    expect(main, contains('android:allowBackup="false"'));
    expect(main, contains('android:fullBackupContent="false"'));
    expect(main, contains('android:dataExtractionRules="@xml/data_extraction_rules"'));
  });
}
