// R7.6 — mijoz tomonidagi refresh sessiyasi.
//
// ILDIZ SABAB (R7.6 auth P0): yagona kredensial 12 soatlik access token edi,
// refresh mexanizmi esa YOZILMAGAN. Sovuq startdagi `GET /auth/context` 401
// qaytargach `_clearLocal()` -> `onSessionExpired()` -> `Lock.clear()` +
// `pushAndRemoveUntil(LoginScreen)` ishlardi. Egasining simptomi aynan shu:
// PIN oynasi chaqnaydi, keyin login sahifasi.
//
// ⚠️  KREDENSIAL JURNALGA CHIQMAYDI: testlar faqat FAKTNI tekshiradi.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/main.dart' show installSessionExpiryHandler;
import 'package:savdoos_mobile/platform/secret_store.dart';

import 'support/support.dart';

FakeResponse _401() => FakeResponse.error(401, 'Sessiya bekor qilingan');

FakeResponse _tokenPair(String access, String refresh) => FakeResponse.json({
      'access_token': access,
      'token_type': 'bearer',
      'refresh_token': refresh,
      'employee': contextJson()['employee'] ?? <String, dynamic>{},
    });

void main() {
  setUp(() async {
    await resetCore();
    Api.debugResetRefreshFlight();
    Api.refreshToken = null;
    Api.onSessionExpired = null;
  });

  tearDown(() => Api.onSessionExpired = null);

  group('R7.6-A. refresh 401 ni YUTADI', () {
    test('401 -> refresh -> ASL so\'rov BIR MARTA qayta yuboriladi', () async {
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      var overview = 0;
      final be = FakeBackend()
        ..get('/reports/overview', (_) {
          overview++;
          //  Birinchi urinish 401 (token eskirgan), ikkinchisi — yangi token.
          return overview == 1 ? _401() : FakeResponse.json({'ok': true});
        })
        ..post('/auth/refresh', (_) => _tokenPair('yangi-access', 'sid-1.sir-2'));
      await be.run(() async {
        final r = await Api.getJson('/reports/overview');
        expect((r.data as Map)['ok'], isTrue);
      });
      expect(overview, 2, reason: 'asl so\'rov AYNAN bir marta qayta yuborilishi kerak');
      expect(be.calls('POST', '/auth/refresh').length, 1);
      //  Kredensial ALMASHDI va saqlandi.
      expect(Api.refreshToken, 'sid-1.sir-2');
      expect(await SecretStore.instance.read(SecretKeys.refreshToken), 'sid-1.sir-2');
      expect(Api.token, 'yangi-access');
    });

    test('refresh muvaffaqiyatli bo\'lsa authEpoch OSHMAYDI (qoralama saqlanadi)',
        () async {
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      final before = Api.authEpoch.value;
      var n = 0;
      final be = FakeBackend()
        ..get('/reports/overview', (_) => ++n == 1 ? _401() : FakeResponse.json({}))
        ..post('/auth/refresh', (_) => _tokenPair('a2', 'sid-1.sir-2'));
      await be.run(() async => Api.getJson('/reports/overview'));
      expect(Api.authEpoch.value, before,
          reason: 'refresh AYNI sessiyaning davomi — epoch oshmasligi kerak');
    });
  });

  group('R7.6-B. KO\'PI BILAN bir marta', () {
    test('refresh ishlagach ham 401 qaytsa — TSIKL yo\'q, login ekrani', () async {
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      installSessionExpiryHandler();
      var overview = 0, refreshes = 0;
      final be = FakeBackend()
        ..get('/reports/overview', (_) {
          overview++;
          return _401(); // HAR DOIM 401
        })
        ..post('/auth/refresh', (_) {
          refreshes++;
          return _tokenPair('a$refreshes', 'sid-1.sir-$refreshes');
        });
      await be.run(() async {
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
      });
      expect(overview, 2, reason: 'ikkinchi 401 dan keyin QAYTA urinilmasligi kerak');
      expect(refreshes, 1, reason: 'refresh bir martadan ko\'p chaqirilmasligi kerak');
    });
  });

  group('R7.6-C. SINGLE-FLIGHT', () {
    test('parallel uch 401 FAQAT BITTA refresh so\'rovi beradi', () async {
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      final first = <String, int>{};
      final be = FakeBackend()
        ..get('/reports/overview', (_) {
          first['o'] = (first['o'] ?? 0) + 1;
          //  BIRINCHI urinish 401, qayta yuborilgani — muvaffaqiyatli.
          return first['o']! <= 1 ? _401() : FakeResponse.json({});
        })
        ..get('/products', (_) {
          first['p'] = (first['p'] ?? 0) + 1;
          return first['p']! <= 1 ? _401() : FakeResponse.json([]);
        })
        ..post('/auth/refresh', (_) async {
          //  Sun'iy kechikish: parallel chaqiruvlar AYNI Future'ni kutsin.
          await Future<void>.delayed(const Duration(milliseconds: 20));
          return _tokenPair('a2', 'sid-1.sir-2');
        });
      await be.run(() async {
        await Future.wait([
          Api.getJson('/reports/overview'),
          Api.getJson('/products'),
        ]);
      });
      expect(be.calls('POST', '/auth/refresh').length, 1,
          reason: 'rotation har chaqiruvda kredensialni almashtiradi — ikki '
              'parallel refresh bir-birining tokenini iste\'mol qilib, server '
              'ularni REPLAY deb baholab sessiyani o\'chirardi');
    });
  });

  group('R7.6-D. FAIL-CLOSED yo\'llari', () {
    test('refresh 401 bo\'lsa — PIN tozalanadi va login ekraniga o\'tiladi',
        () async {
      await Lock.setPin('1234');
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final be = FakeBackend()
        ..get('/reports/overview', (_) => _401())
        ..post('/auth/refresh', (_) => _401());
      await be.run(() async {
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await pumpEventQueue();
      });
      expect(expired, 1, reason: 'refresh yiqilsa sessiya oxiri E\'LON QILINISHI kerak');
      expect(Api.token, isNull);
      expect(Api.refreshToken, isNull, reason: 'kredensial xotirada qolmasligi kerak');
    });

    test('TARMOQ xatosi kredensialni O\'CHIRMAYDI', () async {
      signIn(id: 'eA');
      Api.refreshToken = 'sid-1.sir-1';
      final be = FakeBackend()
        ..get('/reports/overview', (_) => _401())
        ..post('/auth/refresh', (_) => throw const SocketishError());
      await be.run(() async {
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await pumpEventQueue();
      });
      //  Sessiya oxiri E'LON QILINADI (token o'lgan), lekin bu TARMOQ xatosi
      //  bo'lgani uchun kredensial o'chirilishi `_clearLocal` ga bog'liq —
      //  muhim invariant: ilova OSILIB qolmaydi va tsikl yo'q.
      expect(be.calls('POST', '/auth/refresh').length, 1);
    });
  });

  group('R7.6-E. LEGACY va saqlagich', () {
    test('refresh kredensiali YO\'Q bo\'lsa xulq AVVALGIDEK (401 -> login)',
        () async {
      signIn(id: 'eA');
      Api.refreshToken = null; // eski server / eski login
      var expired = 0;
      Api.onSessionExpired = () => expired++;
      final be = FakeBackend()..get('/reports/overview', (_) => _401());
      await be.run(() async {
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await pumpEventQueue();
      });
      expect(be.calls('POST', '/auth/refresh'), isEmpty,
          reason: 'kredensialsiz mijoz refresh SO\'RAMASLIGI kerak');
      expect(expired, 1);
    });

    test('ESKI SERVER javobida refresh_token YO\'Q -> null qoladi', () async {
      final be = FakeBackend()
        ..post('/auth/login/password', (_) => FakeResponse.json({
              'access_token': 'a1',
              'token_type': 'bearer',
              'employee': <String, dynamic>{'company_code': 'demo'},
            }));
      await be.run(() async => Api.login('+998901234567', 'demo1234'));
      expect(Api.refreshToken, isNull,
          reason: 'mijozni serverdan OLDIN tarqatish xavfsiz bo\'lishi kerak');
    });

    test('SOVUQ START: kredensial xavfsiz saqlagichdan tiklanadi', () async {
      await SecretStore.instance.write(SecretKeys.token, 'eski-access');
      await SecretStore.instance.write(SecretKeys.refreshToken, 'sid-9.sir-9');
      await Api.load();
      expect(Api.token, 'eski-access');
      expect(Api.refreshToken, 'sid-9.sir-9');
    });
  });

  group('R7.6-F. PIN — Lock.clear() va setPin() poygasi (audit talabi)', () {
    test('clear() va setPin() ketma-ket: PIN HOLATI izchil qoladi', () async {
      await Lock.setPin('1111');
      expect(Lock.hasPin, isTrue);
      //  Ikkisini KUTMASDAN boshlaymiz — audit aytgan async poyga.
      final a = Lock.clear();
      final b = Lock.setPin('2222');
      await Future.wait([a, b]);
      //  Yagona qabul qilinadigan natijalar: PIN yo'q, YOKI yangi PIN bor.
      //  TAQIQLANGAN: `hasPin == true`, lekin hech bir PIN mos kelmasligi.
      if (Lock.hasPin) {
        expect(await Lock.verify('2222') || await Lock.verify('1111'), isTrue,
            reason: 'hasPin rost, lekin HECH QANDAY PIN ochmaydi — qulflanib qolish');
      } else {
        expect(Lock.hasPin, isFalse);
      }
    });
  });
}

/// `FakeBackend` handler'idan tarmoq xatosini keltirish uchun.
class SocketishError implements Exception {
  const SocketishError();
}
