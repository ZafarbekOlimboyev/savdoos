import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/screens/receiving_home_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

const consent = {
  'protocol_version': 2,
  'revision': 1,
  'mode': 'active',
  'disclosure_id': 'binos.receiving.ai.v1',
  'model': 'synthetic-model',
  'required': true,
  'granted': false,
  'provider': 'gemini',
  'provider_name': 'Google Gemini (Google LLC)',
  'disclosure_version': 1,
};

void main() {
  late FakeBackend be;
  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get('/auth/context', (_) => contextJson())
      ..get('/receiving', (_) => [])
      ..get('/receiving/ai-consent', (_) => consent)
      ..post('/receiving/ai-consent', (_) => {...consent, 'granted': true})
      ..post('/receiving/scan', (_) => {'source': 'ai', 'items': []});
    ReceivingHomeScreen.debugPicker = (_) async => ([1, 2, 3], 'image/jpeg');
  });
  tearDown(() {
    ReceivingHomeScreen.debugPicker = null;
    Session.instance.debugReset();
  });

  Future<void> pick(WidgetTester t, {String role = 'ega'}) async {
    signIn(role: role, permissions: ['xaridlar.edit']);
    be.get('/auth/context',
        (_) => contextJson(role: role, permissions: ['xaridlar.edit']));
    await Session.instance.load();
    await pumpAt390(t, const ReceivingHomeScreen());
    await t.pumpAndSettle();
    await t.tap(find.byKey(const Key('recv-home-gallery')));
    await t.pumpAndSettle();
  }

  List<String> requests() => [
        for (final r in be.log)
          if (r.path == '/receiving/ai-consent' || r.path == '/receiving/scan')
            '${r.method} ${r.path}',
      ];

  void rejectFirstScan({bool rejectRetry = false}) {
    var gets = 0;
    var scans = 0;
    be.get(
        '/receiving/ai-consent',
        (_) => {
              ...consent,
              // Even a stale "granted" response must lead to explicit reconfirmation.
              'granted': ++gets == 1 || gets == 2,
            });
    be.post('/receiving/scan', (_) {
      if (++scans == 1 || rejectRetry) {
        return FakeResponse.error(403, 'Permission denied',
            code: 'AI_CONSENT_REQUIRED');
      }
      return {'source': 'ai', 'items': []};
    });
  }

  test(
      'real permission matrix maps grant to settings.edit and the three standard roles',
      () async {
    final rule = Perm.rule('receiving.ai_consent_grant');
    expect(Perm.isKnown('receiving.ai_consent_grant'), isTrue);
    expect(rule?.method, 'POST');
    expect(rule?.path, '/receiving/ai-consent');
    expect(rule?.anyOf, ['sozlamalar.edit']);
    for (final role in ['ega', 'administrator', 'omborchi']) {
      // Standard omborchi permissions from server seed.ROLES; owners/admins
      // use the same full_access mapping as backend FULL_ACCESS_ROLES.
      const permissions = [
        'mahsulotlar.view',
        'mahsulotlar.edit',
        'ombor.view',
        'ombor.edit',
        'xaridlar.view',
        'xaridlar.edit'
      ];
      Session.instance.debugReset();
      signIn(role: role, permissions: permissions);
      be.get('/auth/context',
          (_) => contextJson(role: role, permissions: permissions));
      await be.run(() => Session.instance.load());
      expect(Perm.allows('receiving.ai_consent_grant'), role != 'omborchi',
          reason: role);
      expect(Perm.allows('receiving.scan'), isTrue, reason: role);
    }
  });

  testWidgets('administrator can explicitly grant consent', (t) async {
    await be.run(() async {
      await pick(t, role: 'administrator');
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
    });
  });

  testWidgets('recovery displays the refreshed provider, not the old provider',
      (t) async {
    rejectFirstScan();
    var gets = 0;
    final current = {
      ...consent,
      'provider': 'anthropic',
      'provider_name': 'Anthropic Claude (Anthropic PBC)'
    };
    be.get('/receiving/ai-consent',
        (_) => ++gets == 1 ? {...consent, 'granted': true} : current);
    be.post('/receiving/ai-consent', (_) => {...current, 'granted': true});
    await be.run(() async {
      await pick(t);
      expect(find.textContaining('Anthropic Claude (Anthropic PBC)'),
          findsOneWidget);
      expect(find.textContaining('Google Gemini'), findsNothing);
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/scan'), hasLength(2));
    });
  });

  testWidgets('ordinary permission denial does not trigger consent recovery',
      (t) async {
    be.get('/receiving/ai-consent', (_) => {...consent, 'granted': true});
    be.post('/receiving/scan',
        (_) => FakeResponse.error(403, 'Denied', code: 'PERMISSION_DENIED'));
    await be.run(() async {
      await pick(t);
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
      expect(find.byType(AlertDialog), findsNothing);
    });
  });

  for (final version in [null, 2]) {
    testWidgets(
        'already granted with unsupported disclosure $version does not send an image',
        (t) async {
      be.get('/receiving/ai-consent',
          (_) => {...consent, 'granted': true, 'disclosure_version': version});
      await be.run(() async {
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
      });
    });
  }

  for (final accept in [false, true]) {
    testWidgets(
        'failed initial GET needs a user retry and new confirmation, accept=$accept',
        (t) async {
      be.get('/receiving/ai-consent',
          (_) => FakeResponse.error(503, 'Unavailable'));
      await be.run(() async {
        await pick(t);
        expect(requests(), ['GET /receiving/ai-consent']);
        be.get('/receiving/ai-consent', (_) => consent);
        await t.tap(find.text('Qayta urinish'));
        await t.pumpAndSettle();
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
        await t.tap(
            find.text(accept ? 'Roziman, yuborilsin' : 'Qo‘lda kiritaman'));
        await t.pumpAndSettle();
        expect(be.calls('GET', '/receiving/ai-consent'), hasLength(accept ? 3 : 2));
        expect(be.calls('POST', '/receiving/ai-consent'),
            hasLength(accept ? 1 : 0));
        expect(be.calls('POST', '/receiving/scan'), hasLength(accept ? 1 : 0));
      });
    });

    testWidgets(
        'scan consent rejection requires fresh disclosure and explicit confirmation, accept=$accept',
        (t) async {
      rejectFirstScan();
      final grant = Completer<Object?>();
      be.post('/receiving/ai-consent', (_) => grant.future);
      await be.run(() async {
        await pick(t);
        expect(be.calls('GET', '/receiving/ai-consent'), hasLength(2));
        expect(
            find.textContaining('Google Gemini (Google LLC)'), findsOneWidget);
        expect(find.textContaining('Joylashuv kabi'), findsOneWidget);
        expect(find.textContaining('AI orqali o‘qish uchun'), findsOneWidget);
        expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
        await t.tap(
            find.text(accept ? 'Roziman, yuborilsin' : 'Qo‘lda kiritaman'));
        await t.pump();
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
        if (accept) grant.complete({...consent, 'granted': true});
        await t.pumpAndSettle();
        expect(be.calls('POST', '/receiving/ai-consent'),
            hasLength(accept ? 1 : 0));
        expect(be.calls('POST', '/receiving/scan'), hasLength(accept ? 2 : 1));
        if (accept) {
          expect(be.calls('POST', '/receiving/scan')[0].body,
              be.calls('POST', '/receiving/scan')[1].body);
        }
      });
    });
  }

  testWidgets('a second consent rejection stops without another grant or scan',
      (t) async {
    rejectFirstScan(rejectRetry: true);
    await be.run(() async {
      await pick(t);
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pumpAndSettle();
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(3));
      expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(2));
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.textContaining('AI orqali o‘qish uchun'), findsOneWidget);
    });
  });

  for (final phase in ['GET', 'POST']) {
    testWidgets('recovery $phase network error sends no further image',
        (t) async {
      rejectFirstScan();
      if (phase == 'GET') {
        var gets = 0;
        be.get('/receiving/ai-consent', (_) {
          if (++gets == 1) return {...consent, 'granted': true};
          throw http.ClientException('Offline');
        });
      } else {
        be.post('/receiving/ai-consent',
            (_) => throw http.ClientException('Offline'));
      }
      await be.run(() async {
        await pick(t);
        if (phase == 'POST') {
          await t.tap(find.text('Roziman, yuborilsin'));
          await t.pumpAndSettle();
        }
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
        expect(be.calls('POST', '/receiving/ai-consent'),
            hasLength(phase == 'GET' ? 0 : 1));
        expect(find.byType(AlertDialog), findsNothing);
      });
    });
  }

  for (final version in [null, 2]) {
    testWidgets(
        'unsupported or missing disclosure $version prevents grant and retry',
        (t) async {
      rejectFirstScan();
      var gets = 0;
      be.get(
          '/receiving/ai-consent',
          (_) => ++gets == 1
              ? {...consent, 'granted': true}
              : {...consent, 'disclosure_version': version});
      await be.run(() async {
        await pick(t);
        expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
        expect(find.byType(AlertDialog), findsNothing);
        expect(find.textContaining('AI roziligi ma’lumotlari mos emas'),
            findsOneWidget);
      });
    });
  }

  for (final result in [
    FakeResponse.error(409, 'Disclosure changed', code: 'AI_CONSENT_REQUIRED'),
    {...consent, 'granted': true, 'provider': 'anthropic',
     'provider_name': 'Anthropic Claude (Anthropic PBC)'},
  ]) {
    testWidgets(
        'grant rejection or changed provider prevents scan retry: $result',
        (t) async {
      rejectFirstScan();
      be.post('/receiving/ai-consent', (_) => result);
      await be.run(() async {
        await pick(t);
        await t.tap(find.text('Roziman, yuborilsin'));
        await t.pumpAndSettle();
        expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      });
    });
  }

  testWidgets(
      'operator without grant rights sees consent explanation and no recovery grant',
      (t) async {
    rejectFirstScan();
    await be.run(() async {
      await pick(t, role: 'omborchi');
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
      expect(find.textContaining('AI orqali o‘qish uchun'), findsOneWidget);
      expect(find.text('Roziman, yuborilsin'), findsNothing);
    });
  });

  testWidgets(
      'owner: GET then explicit grant then photo; nothing sent before approval',
      (t) async {
    final grant = Completer<Object?>();
    be.post('/receiving/ai-consent', (_) => grant.future);
    await be.run(() async {
      await pick(t);
      expect(find.textContaining('Google Gemini (Google LLC)'), findsOneWidget);
      expect(requests(), ['GET /receiving/ai-consent']);
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pump();
      expect(be.last('POST', '/receiving/ai-consent').body,
          {'revision': 1, 'provider': 'gemini',
           'disclosure_id': 'binos.receiving.ai.v1', 'disclosure_version': 1});
      expect(be.calls('POST', '/receiving/scan'), isEmpty);
      grant.complete({...consent, 'granted': true});
      await t.pumpAndSettle();
      expect(requests(), [
        'GET /receiving/ai-consent',
        'GET /receiving/ai-consent',
        'POST /receiving/ai-consent',
        'POST /receiving/scan'
      ]);
      expect(be.last('POST', '/receiving/scan').body['image_b64'], 'AQID');
    });
  });

  for (final dismiss in [false, true]) {
    testWidgets(
        'declining or dismissing consent sends no photo (dismiss=$dismiss)',
        (t) async {
      await be.run(() async {
        await pick(t);
        if (dismiss) {
          Navigator.of(t.element(find.byType(AlertDialog))).pop();
        } else {
          await t.tap(find.text('Qo‘lda kiritaman'));
        }
        await t.pumpAndSettle();
        expect(requests(), ['GET /receiving/ai-consent']);
        expect(find.byKey(const Key('recv-home-manual')), findsOneWidget);
      });
    });
  }

  for (final failingMethod in ['GET', 'POST']) {
    testWidgets('$failingMethod consent error prevents scan', (t) async {
      be.on(failingMethod, '/receiving/ai-consent',
          (_) => FakeResponse.error(503, 'Consent unavailable'));
      await be.run(() async {
        await pick(t);
        if (failingMethod == 'POST') {
          await t.tap(find.text('Roziman, yuborilsin'));
          await t.pumpAndSettle();
        }
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        expect(find.byType(SnackBar), findsOneWidget);
      });
    });
  }

  testWidgets('already granted: GET precedes scan and never grants again',
      (t) async {
    be.get('/receiving/ai-consent', (_) => {...consent, 'granted': true});
    await be.run(() async {
      await pick(t);
      expect(requests(), ['GET /receiving/ai-consent', 'POST /receiving/scan']);
    });
  });

  testWidgets('warehouse operator cannot grant and sends no image', (t) async {
    await be.run(() async {
      await pick(t, role: 'omborchi');
      expect(find.text('Roziman, yuborilsin'), findsNothing);
      expect(requests(), ['GET /receiving/ai-consent']);
    });
  });

  testWidgets(
      'server consent rejection is surfaced, without automatic grant or retry',
      (t) async {
    be.get('/receiving/ai-consent', (_) => {...consent, 'granted': true});
    be.post(
        '/receiving/scan',
        (_) => FakeResponse.error(403, 'Rozilik kerak',
            code: 'AI_CONSENT_REQUIRED'));
    await be.run(() async {
      await pick(t);
      expect(requests(), [
        'GET /receiving/ai-consent',
        'POST /receiving/scan',
        'GET /receiving/ai-consent'
      ]);
      expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);
      expect(find.text('Roziman, yuborilsin'), findsOneWidget);
      expect(Api.loggedIn, isTrue);
    });
  });
}
