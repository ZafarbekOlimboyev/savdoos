// Test harness barrel + core reset. Feature-package tests:
//
// ```dart
// import '../support/support.dart';   // or 'support/support.dart'
//
// setUp(() async => resetCore());
// testWidgets('...', (tester) async {
//   final be = FakeBackend()..get('/auth/context', (_) => contextJson(role: 'omborchi', permissions: ['ombor.edit']));
//   signIn(role: 'omborchi');
//   await be.run(() async {
//     await Session.instance.load(force: true);
//     await pumpAt390(tester, const MyScreen());
//     await tester.pumpAndSettle();
//   });
// });
// ```
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/permissions.dart';
import 'package:savdoos_mobile/session.dart';

import 'fake_backend.dart';
import 'platform_mocks.dart';

export 'fake_backend.dart';
export 'fake_platform.dart';
export 'platform_mocks.dart';
export 'pump.dart';

/// Resets every core singleton to a signed-out state pointing at
/// [FakeBackend.baseUrl]; installs the platform fakes; loads the permission matrix.
Future<void> resetCore({
  String lang = 'uz',
  Map<String, Object> prefs = const {},
  Map<String, String> secureValues = const {},
}) async {
  PlatformMocks.install(prefs: prefs, secureValues: secureValues);
  L.code = lang;
  Api.baseUrl = FakeBackend.baseUrl;
  Api.token = null;
  Api.employee = null;
  Api.online.value = true;
  Api.onSessionExpired = null;
  Session.instance.debugReset();
  await Perm.load();
}

/// Marks the app signed in (token + employee snapshot) without any request.
void signIn({
  String id = 'e1',
  String role = 'ega',
  List<String> permissions = const [],
  String companyCode = 'fayzan1',
  String fullName = 'Test User',
}) {
  Api.token = 'test-token';
  Api.employee = {
    'id': id,
    'full_name': fullName,
    'role_code': role,
    'role_name': role,
    'company_code': companyCode,
    'permissions': permissions,
  };
}
