import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/receiving_api.dart';

import 'support/ai_contract.dart';
import 'support/support.dart';

void main() {
  setUp(() async {
    await resetCore();
    signIn();
  });

  for (final revision in [7, 103]) {
    test('AI contract: GET revision $revision is echoed in both POST DTOs', () async {
      final be = FakeBackend();
      var status = {...aiRequirement, 'revision': revision};
      be.get('/receiving/ai-consent', (_) => status);
      be.post('/receiving/ai-consent', (r) {
        final reply = consentResponse(r, status);
        if (reply.status == 200) status = {...status, 'granted': true};
        return reply;
      });
      be.post('/receiving/scan', (r) => scanResponse(r, status));
      await be.run(() async {
        final requirement = await ReceivingApi.aiConsentStatus();
        final granted = await ReceivingApi.grantAiConsent(requirement);
        expect(granted.granted, isTrue);
        expect(granted.sameRequirement(requirement), isTrue);
        await ReceivingApi.scanInvoice('c3ludGhldGlj', 'image/jpeg',
            revision: requirement.revision);
        expect((await ReceivingApi.aiConsentStatus()).mustAsk, isFalse);
      });
      expect(be.last('POST', '/receiving/ai-consent').body, {
        'revision': revision,
        'provider': status['provider'],
        'disclosure_id': status['disclosure_id'],
        'disclosure_version': status['disclosure_version'],
      });
      expect(be.last('POST', '/receiving/scan').body, {
        'revision': revision, 'image_b64': 'c3ludGhldGlj', 'media_type': 'image/jpeg',
      });
    });
  }

  test('AI contract: server DTO mock rejects the old incomplete POST bodies', () async {
    final be = FakeBackend();
    be.post('/receiving/ai-consent', (r) => consentResponse(r, aiRequirement));
    be.post('/receiving/scan', (r) => scanResponse(r, aiRequirement));
    await be.run(() async {
      await expectLater(Api.postJson('/receiving/ai-consent', {'disclosure_version': 1}),
          throwsA(isA<ApiException>().having((e) => e.status, 'status', 422)));
      await expectLater(Api.postJson('/receiving/scan',
          {'image_b64': 'c3ludGhldGlj', 'media_type': 'image/jpeg'}),
          throwsA(isA<ApiException>().having((e) => e.status, 'status', 422)));
    });
  });

  test('AI contract: stale scan revision returns 409 without a retry', () async {
    final be = FakeBackend();
    be.post('/receiving/scan', (r) => scanResponse(r,
        {...aiRequirement, 'revision': 104, 'granted': true}));
    await be.run(() async {
      await expectLater(ReceivingApi.scanInvoice('c3ludGhldGlj', 'image/jpeg', revision: 103),
          throwsA(isA<ApiException>().having((e) => e.status, 'status', 409)
              .having((e) => e.code, 'code', 'AI_REQUIREMENT_CHANGED')));
    });
    expect(be.calls('POST', '/receiving/scan'), hasLength(1));
  });
}
