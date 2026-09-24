// Biometrics / AppPackageInfo / ImageCapture / LocalCache adapters (B4 item 1).
// VM only: exercises the io LocalCache adapter against real files.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/biometrics_io.dart' as bio_io;
import 'package:savdoos_mobile/platform/biometrics_web.dart' as bio_web;
import 'package:savdoos_mobile/platform/local_cache_web.dart' as cache_web;
import 'package:savdoos_mobile/platform/platform.dart';

import 'support/support.dart';

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend();
  });

  group('Biometrics', () {
    test('Lock.biometricAvailable follows the adapter; nothing else decides', () async {
      PlatformMocks.biometricsAvailable = false;
      expect(await Lock.biometricAvailable(), isFalse);
      PlatformMocks.biometricsAvailable = true;
      expect(await Lock.biometricAvailable(), isTrue);
      expect(Lock.biometricsSupported, isTrue, reason: 'the fake models an Android phone');
    });

    test('the web adapter is honest: unsupported, unavailable, never authenticates', () async {
      final b = bio_web.createBiometrics();
      expect(b.supported, isFalse);
      expect(await b.available(), isFalse);
      expect(await b.authenticate('x'), isFalse);
    });

    test('the io adapter is the native path (local_auth), supported on this platform', () {
      expect(bio_io.createBiometrics().supported, isTrue);
    });

    test('Lock.authenticate returns the adapter answer', () async {
      PlatformMocks.biometricsAvailable = true;
      PlatformMocks.biometricAccepts = true;
      expect(await Lock.authenticate('reason'), isTrue);
      PlatformMocks.biometricAccepts = false;
      expect(await Lock.authenticate('reason'), isFalse);
    });
  });

  group('AppPackageInfo', () {
    test('the fake reports the pubspec version the channel mock used to', () async {
      final v = await AppPackageInfo.instance.read();
      expect(v?.version, '0.6.30');
      expect(v?.buildNumber, '55');
    });
  });

  group('LocalCache', () {
    test('logout, 401 and a server change purge the catalog cache through the adapter', () async {
      final fake = FakeLocalCache();
      LocalCache.instance = fake;
      signIn();
      be.post('/auth/logout', (_) => {'ok': true});
      await be.run(Api.logout);
      expect(fake.purges, 1);

      signIn();
      be.get('/products', (_) => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring'));
      await expectLater(be.run(() => Api.getJson('/products')), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(fake.purges, 2);

      signIn();
      Api.baseUrl = 'https://a.example';
      await Api.setBaseUrl('https://b.example');
      expect(fake.purges, 3);
    });

    test('the web adapter is a documented no-op (nothing is written to disk on web)', () async {
      await cache_web.createLocalCache().purgeCatalogFiles(); // must not throw
    });

    test('the default (io) adapter deletes catalog_*.json in the support dir and keeps other files', () async {
      final dir = Directory(PlatformMocks.tempDirPath);
      final old = File('${dir.path}/catalog_x.json')..writeAsStringSync('[]');
      final keep = File('${dir.path}/notes.json')..writeAsStringSync('{}');
      await createLocalCache().purgeCatalogFiles();
      expect(old.existsSync(), isFalse);
      expect(keep.existsSync(), isTrue);
      keep.deleteSync();
    });
  });

  group('ImageCapture', () {
    test('the suite fake returns what tests hand it, or null when the operator cancels', () async {
      expect(await ImageCapture.instance.pick(ImageSource.camera), isNull);
      PlatformMocks.pickedImage = ([1, 2, 3], 'image/png');
      final r = await ImageCapture.instance.pick(ImageSource.gallery);
      expect(r?.$1, [1, 2, 3]);
      expect(r?.$2, 'image/png');
    });
  });
}
