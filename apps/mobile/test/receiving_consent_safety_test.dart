import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:savdoos_mobile/screens/receiving_home_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

const externalStatus = <String, Object?>{
  'protocol_version': 2, 'revision': 1, 'mode': 'active',
  'disclosure_id': 'binos.receiving.ai.v1',
  'required': true,
  'granted': true,
  'provider': 'gemini',
  'provider_name': 'Google Gemini (Google LLC)',
  'model': 'synthetic-model',
  'previous_provider': null,
  'disclosure_version': 1,
};
const demoStatus = <String, Object?>{
  'protocol_version': 2, 'revision': 1, 'mode': 'demo',
  'disclosure_id': 'binos.receiving.ai.v1',
  'required': false,
  'granted': false,
  'provider': null,
  'provider_name': null,
  'model': null,
  'previous_provider': null,
  'disclosure_version': 1,
};

void main() {
  late FakeBackend be;
  var picks = 0;
  setUp(() async {
    await resetCore();
    picks = 0;
    be = FakeBackend()
      ..get('/auth/context', (_) => contextJson())
      ..get('/receiving', (_) => [])
      ..get('/receiving/ai-consent', (_) => externalStatus)
      ..post('/receiving/scan', (_) => {'source': 'ai', 'items': []})
      ..post('/receiving/ai-consent', (_) => externalStatus);
    ReceivingHomeScreen.debugPicker = (_) async {
      picks++;
      return ([1, 2, 3], 'image/jpeg');
    };
  });
  tearDown(() {
    ReceivingHomeScreen.debugPicker = null;
    Session.instance.debugReset();
  });

  Future<void> open(WidgetTester t, {String role = 'ega'}) async {
    signIn(role: role, permissions: ['xaridlar.edit']);
    be.get('/auth/context',
        (_) => contextJson(role: role, permissions: ['xaridlar.edit']));
    await Session.instance.load();
    await pumpAt390(t, const ReceivingHomeScreen());
    await t.pumpAndSettle();
  }

  Future<void> pick(WidgetTester t) async {
    await t.tap(find.byKey(const Key('recv-home-gallery')));
    await t.pumpAndSettle();
  }

  bool enabled(WidgetTester t) =>
      t
          .widget<OutlinedButton>(find.byKey(const Key('recv-home-gallery')))
          .onPressed !=
      null;

  void noGrant() => expect(be.calls('POST', '/receiving/ai-consent'), isEmpty);

  test('conditional grant submits exact approved requirement', () async {
    await be.run(() async {
      await ReceivingApi.grantAiConsent(AiConsent.fromJson(externalStatus));
      expect(be.last('POST', '/receiving/ai-consent').body, {
        'revision': 1, 'provider': 'gemini', 'disclosure_version': 1,
        'disclosure_id': 'binos.receiving.ai.v1',
      });
    });
  });

  final invalid = <String, Map<String, Object?>>{
    'empty': {},
    'revision missing': {...externalStatus}..remove('revision'),
    'revision null': {...externalStatus, 'revision': null},
    'revision string': {...externalStatus, 'revision': '1'},
    'revision zero': {...externalStatus, 'revision': 0},
    'protocol missing': {...externalStatus}..remove('protocol_version'),
    'protocol stale': {...externalStatus, 'protocol_version': 1},
    'identity missing': {...externalStatus}..remove('disclosure_id'),
    'identity unknown': {...externalStatus, 'disclosure_id': 'unknown'},
    'paused': {...externalStatus, 'mode': 'paused'},
    'mode missing': {...externalStatus}..remove('mode'),
    'model missing': {...externalStatus}..remove('model'),
    'active model null': {...externalStatus, 'model': null},
    'required missing': {...externalStatus}..remove('required'),
    'required null': {...externalStatus, 'required': null},
    'required string': {...externalStatus, 'required': 'true'},
    'granted missing': {...externalStatus}..remove('granted'),
    'granted null': {...externalStatus, 'granted': null},
    'granted number': {...externalStatus, 'granted': 1},
    'provider missing': {...externalStatus}..remove('provider'),
    'provider null': {...externalStatus, 'provider': null},
    'provider unknown': {...externalStatus, 'provider': 'unknown'},
    'provider wrong type': {...externalStatus, 'provider': {}},
    'provider name missing': {...externalStatus}..remove('provider_name'),
    'provider name mismatch': {
      ...externalStatus,
      'provider_name': 'Anthropic Claude (Anthropic PBC)'
    },
    'provider name null': {...externalStatus, 'provider_name': null},
    'model wrong type': {...externalStatus, 'model': []},
    'previous provider invalid': {
      ...externalStatus,
      'previous_provider': 'unknown'
    },
    'version missing': {...externalStatus}..remove('disclosure_version'),
    'version null': {...externalStatus, 'disclosure_version': null},
    'version string': {...externalStatus, 'disclosure_version': '1'},
    'version fractional': {...externalStatus, 'disclosure_version': 1.5},
    'version unsupported': {...externalStatus, 'disclosure_version': 2},
    'demo granted': {...demoStatus, 'granted': true},
    'demo provider': {...demoStatus, 'provider': 'gemini'},
    'demo provider name': {
      ...demoStatus,
      'provider_name': 'Google Gemini (Google LLC)'
    },
    'demo model': {...demoStatus, 'model': 'synthetic-model'},
  };
  for (final entry in invalid.entries) {
    testWidgets('malformed status blocks photo: ${entry.key}', (t) async {
      expect(
          () => AiConsent.fromJson(entry.value), throwsA(isA<ApiException>()));
      be.get('/receiving/ai-consent', (_) => entry.value);
      await be.run(() async {
        await open(t);
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        noGrant();
        expect(enabled(t), isTrue,
            reason: 'error releases the operation ticket');
      });
    });
  }

  for (final value in [null, [], 'unknown']) {
    testWidgets('non-map status $value blocks photo', (t) async {
      be.get('/receiving/ai-consent', (_) => value);
      await be.run(() async {
        await open(t);
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        noGrant();
        expect(enabled(t), isTrue);
      });
    });
  }

  for (final status in [
    demoStatus,
    externalStatus,
    {
      ...externalStatus,
      'provider': 'anthropic',
      'provider_name': 'Anthropic Claude (Anthropic PBC)'
    }
  ]) {
    testWidgets(
        'recognized demo or existing grant permits subsequent legitimate scans: ${status['required']}',
        (t) async {
      be.get('/receiving/ai-consent', (_) => status);
      await be.run(() async {
        await open(t);
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
        expect(enabled(t), isTrue);
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), hasLength(2));
        noGrant();
      });
    });
  }

  testWidgets('rapid double tap is guarded before the picker first awaits',
      (t) async {
    final photo = Completer<(List<int>, String)?>();
    ReceivingHomeScreen.debugPicker = (_) {
      picks++;
      return photo.future;
    };
    await be.run(() async {
      await open(t);
      final button = find.byKey(const Key('recv-home-gallery'));
      await t.tap(button);
      await t.tap(button);
      await t.pump();
      expect(picks, 1);
      expect(enabled(t), isFalse);
      photo.complete(([1, 2, 3], 'image/jpeg'));
      await t.pumpAndSettle();
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(enabled(t), isTrue);
    });
  });

  testWidgets(
      'a second receiving screen cannot bypass the shared operation ticket',
      (t) async {
    final status = Completer<Object?>();
    be.get('/receiving/ai-consent', (_) => status.future);
    await be.run(() async {
      await open(t);
      final nav = Navigator.of(t.element(find.byType(ReceivingHomeScreen)));
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      unawaited(nav.push(MaterialPageRoute<void>(
          builder: (_) => const ReceivingHomeScreen(key: Key('other')))));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      expect(picks, 1);
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(1));
      nav.pop();
      await t.pumpAndSettle();
      status.complete(externalStatus);
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(enabled(t), isTrue);
    });
  });

  testWidgets(
      'disposal during a scan does not pop a later route or leave a permanent guard',
      (t) async {
    final reply = Completer<Object?>();
    be.post('/receiving/scan', (_) => reply.future);
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(
          testApp(const ReceivingHomeScreen(key: Key('replacement'))));
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      reply.complete({'source': 'ai', 'items': []});
      await t.pumpAndSettle();
      expect(find.byType(ReceivingHomeScreen), findsOneWidget);
      expect(enabled(t), isTrue);
      expect(t.takeException(), isNull);
    });
  });

  testWidgets(
      'closing the scan loader releases guard and discards a late scan error',
      (t) async {
    final oldReply = Completer<Object?>();
    be.post('/receiving/scan', (_) => oldReply.future);
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(enabled(t), isFalse);
      Navigator.of(t.element(find.byType(Dialog))).pop();
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      be.post('/receiving/scan', (_) => {'source': 'ai', 'items': []});
      await pick(t);
      expect(be.calls('POST', '/receiving/scan'), hasLength(2));
      oldReply.complete(FakeResponse.error(502, 'Synthetic late error'));
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      expect(find.byType(Dialog), findsNothing);
      expect(t.takeException(), isNull);
    });
  });

  testWidgets(
      'picker completion after disposal sends no GET and cannot lock a replacement screen',
      (t) async {
    final photo = Completer<(List<int>, String)?>();
    ReceivingHomeScreen.debugPicker = (_) => photo.future;
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      await t.pumpWidget(const SizedBox());
      photo.completeError(StateError('Synthetic late picker failure'));
      await t.pump();
      await t.pumpWidget(
          testApp(const ReceivingHomeScreen(key: Key('replacement'))));
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      expect(be.calls('GET', '/receiving/ai-consent'), isEmpty);
      expect(t.takeException(), isNull);
    });
  });

  testWidgets(
      'initial GET retry action reacquires the guard without parallel scans',
      (t) async {
    be.get('/receiving/ai-consent',
        (_) => FakeResponse.error(503, 'Synthetic outage'));
    await be.run(() async {
      await open(t);
      await pick(t);
      expect(enabled(t), isTrue);
      final status = Completer<Object?>();
      be.get('/receiving/ai-consent', (_) => status.future);
      await t.tap(find.text('Qayta urinish'));
      await t.pump();
      expect(enabled(t), isFalse);
      status.complete(externalStatus);
      await t.pumpAndSettle();
      await t.tap(find.text('Qo‘lda kiritaman'));
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      expect(be.calls('POST', '/receiving/scan'), isEmpty);
      noGrant();
    });
  });

  testWidgets('held consent GET and scan cannot start parallel work',
      (t) async {
    final status = Completer<Object?>();
    final scan = Completer<Object?>();
    be.get('/receiving/ai-consent', (_) => status.future);
    be.post('/receiving/scan', (_) => scan.future);
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      expect(enabled(t), isFalse);
      await t.tap(find.byKey(const Key('recv-home-camera')));
      await t.pump();
      expect(picks, 1);
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(1));
      status.complete(externalStatus);
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(enabled(t), isFalse);
      scan.complete({'source': 'ai', 'items': []});
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
    });
  });

  testWidgets(
      'recovery owns the same ticket through GET, user decision, conditional grant and retry',
      (t) async {
    var gets = 0;
    final recovery = Completer<Object?>();
    be.get('/receiving/ai-consent',
        (_) => ++gets == 1 ? externalStatus : recovery.future);
    be.post('/receiving/scan',
        (_) => FakeResponse.error(403, 'Consent', code: 'AI_CONSENT_REQUIRED'));
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(enabled(t), isFalse);
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(2));
      recovery.complete({...externalStatus, 'granted': false});
      await t.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      expect(enabled(t), isFalse);
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(2));
      expect(enabled(t), isTrue);
    });
  });

  for (final failure in [
    'cancel picker',
    'picker exception',
    'GET network',
    'scan failure'
  ]) {
    testWidgets('$failure releases guard for a later user scan', (t) async {
      var first = true;
      ReceivingHomeScreen.debugPicker = (_) async {
        picks++;
        if (first && failure == 'cancel picker') {
          first = false;
          return null;
        }
        if (first && failure == 'picker exception') {
          first = false;
          throw StateError('Synthetic picker failure');
        }
        return ([1, 2, 3], 'image/jpeg');
      };
      if (failure == 'GET network') {
        be.get('/receiving/ai-consent', (_) {
          if (first) {
            first = false;
            throw http.ClientException('Synthetic offline');
          }
          return externalStatus;
        });
      }
      if (failure == 'scan failure') {
        be.post('/receiving/scan', (_) {
          if (first) {
            first = false;
            return FakeResponse.error(502, 'Synthetic failure');
          }
          return {'source': 'ai', 'items': []};
        });
      }
      await be.run(() async {
        await open(t);
        await pick(t);
        expect(enabled(t), isTrue);
        await pick(t);
        expect(enabled(t), isTrue);
        expect(be.calls('POST', '/receiving/scan'),
            hasLength(failure == 'scan failure' ? 2 : 1));
        noGrant();
      });
    });
  }

  for (final dismiss in [false, true]) {
    testWidgets('consent cancellation/dismiss=$dismiss releases guard',
        (t) async {
      be.get('/receiving/ai-consent',
          (_) => {...externalStatus, 'granted': false});
      await be.run(() async {
        await open(t);
        await pick(t);
        if (dismiss) {
          Navigator.of(t.element(find.byType(AlertDialog))).pop();
        } else {
          await t.tap(find.text('Qo‘lda kiritaman'));
        }
        await t.pumpAndSettle();
        expect(enabled(t), isTrue);
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        noGrant();
        be.get('/receiving/ai-consent', (_) => externalStatus);
        await pick(t);
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      });
    });
  }

  for (final change in ['provider', 'disclosure', 'network', 'revision', 'identity', 'unchanged']) {
    testWidgets(
        'approval boundary recheck $change only grants unchanged requirement',
        (t) async {
      be.get('/receiving/ai-consent',
          (_) => {...externalStatus, 'granted': false});
      await be.run(() async {
        await open(t);
        await pick(t);
        be.get('/receiving/ai-consent', (_) {
          if (change == 'network') {
            throw http.ClientException('Synthetic offline');
          }
          if (change == 'provider') {
            return {
              ...externalStatus,
              'provider': 'anthropic',
              'provider_name': 'Anthropic Claude (Anthropic PBC)'
            };
          }
          if (change == 'revision') return {...externalStatus, 'revision': 2};
          if (change == 'identity') return {...externalStatus, 'disclosure_id': 'unknown'};
          if (change == 'disclosure') {
            return {...externalStatus, 'disclosure_version': 2};
          }
          return externalStatus;
        });
        await t.tap(find.text('Roziman, yuborilsin'));
        await t.pumpAndSettle();
        expect(be.calls('GET', '/receiving/ai-consent'), hasLength(2));
        expect(be.calls('POST', '/receiving/scan'), hasLength(change == 'unchanged' ? 1 : 0));
        expect(be.calls('POST', '/receiving/ai-consent'), hasLength(change == 'unchanged' ? 1 : 0));
        expect(enabled(t), isTrue);
      });
    });
  }

  testWidgets('standard warehouse operator never reaches grant', (t) async {
    be.get(
        '/receiving/ai-consent', (_) => {...externalStatus, 'granted': false});
    await be.run(() async {
      await open(t, role: 'omborchi');
      await pick(t);
      expect(find.text('Roziman, yuborilsin'), findsNothing);
      await t.tap(find.text('Tushunarli'));
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      expect(be.calls('POST', '/receiving/scan'), isEmpty);
      noGrant();
    });
  });

  testWidgets(
      'ticket stays held during the post-approval authoritative recheck',
      (t) async {
    be.get(
        '/receiving/ai-consent', (_) => {...externalStatus, 'granted': false});
    await be.run(() async {
      await open(t);
      final staleTap = t
          .widget<OutlinedButton>(find.byKey(const Key('recv-home-gallery')))
          .onPressed!;
      await pick(t);
      final recheck = Completer<Object?>();
      be.get('/receiving/ai-consent', (_) => recheck.future);
      await t.tap(find.text('Roziman, yuborilsin'));
      await t.pump();
      expect(enabled(t), isFalse);
      staleTap();
      await t.pump();
      expect(picks, 1);
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(2));
      recheck.complete(externalStatus);
      await t.pumpAndSettle();
      expect(enabled(t), isTrue);
      expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
    });
  });

  testWidgets('stale status across an auth change never submits a photo',
      (t) async {
    final status = Completer<Object?>();
    be.get('/receiving/ai-consent', (_) => status.future);
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      Api.authEpoch.value++;
      signIn(id: 'synthetic-next-user');
      status.complete(externalStatus);
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/scan'), isEmpty);
      noGrant();
      expect(enabled(t), isTrue);
    });
  });

  testWidgets(
      'disposal releases ownership; old completion cannot unlock a newer scan',
      (t) async {
    final oldStatus = Completer<Object?>();
    final newStatus = Completer<Object?>();
    var gets = 0;
    be.get('/receiving/ai-consent',
        (_) => ++gets == 1 ? oldStatus.future : newStatus.future);
    await be.run(() async {
      await open(t);
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(
          testApp(const ReceivingHomeScreen(key: Key('new-screen'))));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('recv-home-gallery')));
      await t.pump();
      expect(be.calls('GET', '/receiving/ai-consent'), hasLength(2));
      oldStatus.complete(externalStatus);
      await t.pump();
      expect(enabled(t), isFalse);
      expect(be.calls('POST', '/receiving/scan'), isEmpty);
      newStatus.complete(externalStatus);
      await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(enabled(t), isTrue);
      expect(t.takeException(), isNull);
    });
  });
  for (final accept in [false, true]) {
    testWidgets('revision change 409 requires fresh explicit approval accept=$accept', (t) async {
      var scans = 0;
      var gets = 0;
      be.get('/receiving/ai-consent', (_) => ++gets == 1 ? externalStatus :
        {...externalStatus, 'revision': 2, 'granted': false});
      be.post('/receiving/scan', (_) => ++scans == 1
        ? FakeResponse.error(409, 'Changed', code: 'AI_REQUIREMENT_CHANGED')
        : {'source': 'ai', 'items': []});
      be.post('/receiving/ai-consent', (_) => {...externalStatus, 'revision': 2});
      await be.run(() async {
        await open(t); await pick(t);
        noGrant();
        expect(be.calls('POST', '/receiving/scan'), hasLength(1));
        await t.tap(find.text(accept ? 'Roziman, yuborilsin' : 'Qo‘lda kiritaman'));
        await t.pumpAndSettle();
        expect(be.calls('POST', '/receiving/ai-consent'), hasLength(accept ? 1 : 0));
        expect(be.calls('POST', '/receiving/scan'), hasLength(accept ? 2 : 1));
        if (accept) {
          expect(be.last('POST', '/receiving/ai-consent').body['revision'], 2);
          expect(be.last('POST', '/receiving/scan').body['revision'], 2);
        }
      });
    });
  }

  for (final field in ['revision', 'disclosure_id', 'model']) {
    testWidgets('grant acknowledgement mismatch $field never scans', (t) async {
      be.get('/receiving/ai-consent', (_) => {...externalStatus, 'granted': false});
      be.post('/receiving/ai-consent', (_) => {...externalStatus,
        field: field == 'revision' ? 2 : 'other'});
      await be.run(() async {
        await open(t); await pick(t);
        await t.tap(find.text('Roziman, yuborilsin')); await t.pumpAndSettle();
        expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
        expect(be.calls('POST', '/receiving/scan'), isEmpty);
        expect(enabled(t), isTrue);
      });
    });
  }

  testWidgets('failed scan after confirmed grant has no extra recovery', (t) async {
    be.get('/receiving/ai-consent', (_) => {...externalStatus, 'granted': false});
    be.post('/receiving/scan', (_) => FakeResponse.error(502, 'Synthetic failed scan'));
    await be.run(() async {
      await open(t); await pick(t);
      await t.tap(find.text('Roziman, yuborilsin')); await t.pumpAndSettle();
      expect(be.calls('POST', '/receiving/ai-consent'), hasLength(1));
      expect(be.calls('POST', '/receiving/scan'), hasLength(1));
      expect(enabled(t), isTrue);
    });
  });

}
