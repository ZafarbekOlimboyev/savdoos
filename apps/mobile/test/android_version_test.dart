// C2 item 1 — ONE version number, derived everywhere.
//
// Phase 5G (`1d16dd7`) shipped the entire mobile rewrite and left
// `version: 0.6.30+55` untouched. A pre-5G APK and a post-5G APK are therefore
// two materially different applications reporting the same `versionName` and
// the same `versionCode` 55 — during a pilot "which build is on that phone?"
// is unanswerable, and Android refuses the newer one as an upgrade because the
// versionCode is equal, not greater.
//
// The rules pinned here (all read out of the repo's own history):
//   * the pubspec version is the SINGLE source and has the shape `x.y.z+build`;
//   * the build number is strictly greater than the last released one (55) —
//     this repo has never reused or skipped a build number;
//   * Phase 5G is a feature jump, so the minor is bumped (precedent `c23f14d`,
//     `0.5.5+24` -> `0.6.0+25`, for PIN + biometrics);
//   * Android does NOT restate the number: `versionCode` / `versionName` come
//     from `flutter.versionCode` / `flutter.versionName`, which the flutter
//     tool writes into the (gitignored) `android/local.properties` straight
//     from the pubspec. A second copy anywhere is a second source of truth.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The last version released before the Phase 5G rewrite (`043341c`,
/// 2026-09-03). Its build number must never be reused.
const int kLastReleasedBuild = 55;

/// The minor of that release — Phase 5G must be above it.
const int kPreRewriteMinor = 6;

final RegExp _versionLine = RegExp(r'^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$', multiLine: true);

void main() {
  final pubspec = File('pubspec.yaml').readAsStringSync();
  final gradle = File('android/app/build.gradle.kts').readAsStringSync();

  test('the pubspec carries exactly one `x.y.z+build` version line', () {
    expect(_versionLine.allMatches(pubspec), hasLength(1),
        reason: 'pubspec.yaml must declare exactly one `version: x.y.z+build` line');
  });

  test('the Phase 5G rewrite bumped the version: the build number is never reused', () {
    final m = _versionLine.firstMatch(pubspec)!;
    final build = int.parse(m[4]!);
    expect(build, greaterThan(kLastReleasedBuild),
        reason: 'build $build was already released before the 5G rewrite; Android will not treat this APK as an '
            'upgrade and two different apps would report the same versionCode');
  });

  test('the Phase 5G rewrite bumped the minor, following the 0.5.5 -> 0.6.0 precedent', () {
    final m = _versionLine.firstMatch(pubspec)!;
    final major = int.parse(m[1]!), minor = int.parse(m[2]!);
    expect(major > 0 || minor > kPreRewriteMinor, isTrue,
        reason: 'the whole mobile rewrite is a feature jump, not a patch: expected >= 0.7.0, found $major.$minor.x');
  });

  test('Android derives versionName/versionCode from the pubspec and never duplicates the number', () {
    expect(gradle, contains('versionCode = flutter.versionCode'));
    expect(gradle, contains('versionName = flutter.versionName'));
    expect(RegExp(r'versionCode\s*=\s*\d').hasMatch(gradle), isFalse,
        reason: 'a literal versionCode in build.gradle.kts is a second source of truth');
    expect(RegExp('''versionName\\s*=\\s*["']''').hasMatch(gradle), isFalse,
        reason: 'a literal versionName in build.gradle.kts is a second source of truth');
  });

  test('the Android manifest does not restate the version either', () {
    final manifest = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    expect(manifest, isNot(contains('android:versionCode')));
    expect(manifest, isNot(contains('android:versionName')));
  });
}
