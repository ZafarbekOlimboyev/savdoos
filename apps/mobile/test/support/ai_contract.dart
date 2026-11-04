// ⚠️  BU FAYL SHARTNOMA MANBASI EMAS — U UNGA BO'YSUNADI.
//
//     Avvalgi sarlavha `26332b0fef2da11972b740a984e9c993dca570fc` serverini
//     nomlardi. BU FIKSTURA XAYOLIY EMAS EDI: o'sha shartnoma
//     `ci-proof/public-demo-cutover` da davom etgan va 2026-11-04T16:31Z da
//     PRODUCTION'ga chiqqan (`ai_requirement` jadvali, `revision`,
//     `disclosure_id`, `mode`, `protocol_version`).
//
//     MUAMMO BOSHQA EDI: fikstura MUAYYAN serverni nomlardi, BU BRANCH esa
//     (`release/1.0-rc1`) o'sha shartnomani OLIB YURMAYDI. Shu bois mobil
//     testlar yashil bo'lsa ham, Build 67 shu branch serveriga qarshi
//     `BAD_RESPONSE` berardi (R7.0 topdi). Fikstura endi SHU BRANCH serverini
//     aks ettiradi: `mode` va `protocol_version` bu yerda yo'q, chunki shu
//     branch ularni qaytarmaydi va mijoz parseri ularni O'QIMAYDI.
//
//     ⚠️  PRODUCTION'da AI hozir `mode='paused'` — `GET /receiving/ai-consent`
//         503 `AI_REQUIREMENT_PAUSED` qaytaradi, ya'ni AI ATAYLAB o'chirilgan.
//         Ikki branchni yarashtirish — EGANING qarori; batafsil:
//         ~/Documents/BinOS-iOS-Evidence/r71-fixes/.
//
//     HAQIQIY MANBA — `contracts/ai_consent.samples.json`, uni
//     `apps/server/tests/test_r71_ai_consent_contract.py` HAQIQIY FastAPI
//     serveridan yozib oladi. Quyidagi qiymatlar o'sha fayldagi
//     `gemini_rozilik_yoq` holatidan olingan va
//     `test/receiving_ai_backend_contract_test.dart` ikkisining MOSLIGINI
//     tekshiradi: fikstura siljisa test QIZIL bo'ladi.
//
//     Server DTO'lari: apps/server/app/api/v1/receiving.py (ConsentIn, ScanIn),
//     apps/server/app/services/ai_consent.py (status/grant).
import 'fake_backend.dart';

const aiRequirement = <String, dynamic>{
  'revision': 2,
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
