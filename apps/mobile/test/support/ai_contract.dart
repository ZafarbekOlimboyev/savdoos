// Wire DTOs from backend 26332b0fef2da11972b740a984e9c993dca570fc:
// apps/server/app/api/v1/receiving.py (ConsentIn, ScanIn).
import 'fake_backend.dart';

const aiRequirement = <String, dynamic>{
  'revision': 37,
  'mode': 'active',
  'protocol_version': 2,
  'required': true,
  'granted': false,
  'provider': 'gemini',
  'provider_name': 'Google Gemini (Google LLC)',
  'model': 'gemini-2.5-flash',
  'disclosure_id': 'binos.receiving.ai.v1',
  'disclosure_version': 1,
};

bool positiveInt(Object? value) => value is int && value >= 1;

/// Missing/wrongly typed DTO fields return 422, exactly as production does.
/// A well-formed but outdated requirement returns 409, never implicit success.
FakeResponse consentResponse(FakeRequest request, Map<String, dynamic> status) {
  final b = request.body;
  if (!positiveInt(b['revision']) ||
      !const ['gemini', 'anthropic'].contains(b['provider']) ||
      b['disclosure_id'] is! String ||
      (b['disclosure_id'] as String).isEmpty ||
      (b['disclosure_id'] as String).length > 100 ||
      !positiveInt(b['disclosure_version']) ||
      (b['disclosure_version'] as int) > 1000) {
    return FakeResponse.error(422, 'Invalid ConsentIn DTO');
  }
  for (final key in ['revision', 'provider', 'disclosure_id', 'disclosure_version']) {
    if (b[key] != status[key]) {
      return FakeResponse.error(409, 'Requirement changed', code: 'AI_REQUIREMENT_CHANGED');
    }
  }
  return FakeResponse.json({...status, 'granted': true});
}

FakeResponse scanResponse(FakeRequest request, Map<String, dynamic> status,
    {Object? result}) {
  final b = request.body;
  if (!positiveInt(b['revision']) || b['image_b64'] is! String ||
      (b['image_b64'] as String).length > 15000000 ||
      (b.containsKey('media_type') &&
          (b['media_type'] is! String || (b['media_type'] as String).length > 60))) {
    return FakeResponse.error(422, 'Invalid ScanIn DTO');
  }
  if (b['revision'] != status['revision']) {
    return FakeResponse.error(409, 'Requirement changed', code: 'AI_REQUIREMENT_CHANGED');
  }
  if (status['required'] == true && status['granted'] != true) {
    return FakeResponse.error(403, 'Consent required', code: 'AI_CONSENT_REQUIRED');
  }
  return FakeResponse.json(result ?? {'source': 'ai', 'items': [], 'ai_raw': []});
}
