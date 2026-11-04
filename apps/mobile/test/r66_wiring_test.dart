// R6.6 §3 — PRODUCTION wiring integration testlari.
//
// ⚠️  Bu fayl `main.dart` ning O'Z ishlovchisini (`installSessionExpiryHandler`)
//     chaqiradi va 401 ni HAQIQIY `FakeBackend` javobi orqali keltiradi —
//     ya'ni `Api.authEpoch.value++` ni qo'lda bosmaydi. Shu bois quyidagi
//     zanjirning HAMMASI birgalikda sinaladi:
//
//       api.dart:832-845   401 -> _clearLocal(beforeCachePurge: …)
//       api.dart:381-396   token=null; employee=null; authEpoch++ -> … -> callback
//       main.dart          Lock.clear(); SessionNotice.raise(); pushAndRemoveUntil
//       draft_guard.dart   authEpoch listener -> DraftVault.stash(scope)
//       login_screen.dart  initState -> SessionNotice.consumeText() -> banner
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_guard.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/main.dart' show installSessionExpiryHandler;
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'support/support.dart';

String _scope() => Session.instance.cacheKey('draft');

FakeResponse _expired() =>
    FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring');

/// `unawaited(Lock.clear())` va fayl I/O tugashini kutadi.
///
/// ⚠️  `flushIo` (test/support/pump.dart) ishlatiladi: u 16 qadam real-IO
///     navbatini fake-async pump bilan almashtiradi. Qisqaroq qo'lbola
///     variant `Api.logout()` ni kutib ulgurmaydi — u `/auth/logout` POST
///     dan keyin Keychain va fayl tizimini tozalaydi.
Future<void> _drain(WidgetTester t) => flushIo(t);

void main() {
  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
    SessionNotice.debugClear();
    installSessionExpiryHandler(); // ← PRODUCTION wiring
  });

  tearDown(() => Api.onSessionExpired = null);

  group('R6.6-W. haqiqiy 401 zanjiri', () {
    testWidgets('HAQIQIY 401: qoralama saqlanadi, qulf tozalanadi, login ekrani + xabar',
        (tester) async {
      await Lock.setPin('1234');
      await Lock.setBiometric(true);
      signIn(id: 'eA');

      final be = FakeBackend()..get('/reports/overview', (_) => _expired());
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'Yarim kiritilgan ish');
        await tester.pumpAndSettle();

        // HAQIQIY so'rov -> HAQIQIY 401 -> butun zanjir.
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await _drain(tester);
        await tester.pumpAndSettle();
      });

      // 1) Navigator teardown: ish ekrani yo'q, login bor.
      expect(find.byType(_Form), findsNothing, reason: 'widget dispose bo\'ldi');
      expect(find.byType(LoginScreen), findsOneWidget, reason: 'navigator teardown');
      // 2) Login ekranida xabar KO'RINADI.
      expect(find.byKey(const Key('login-session-notice')), findsOneWidget);
      expect(find.textContaining('saqlanmagan'), findsOneWidget);
      // 3) Identity tozalandi.
      expect(Api.token, isNull);
      expect(Api.employee, isNull);
      // 4) Qulf fail-closed: PIN va biometrika ketdi.
      expect(Lock.status, LockStatus.absent);
      expect(Lock.biometricOn, isFalse);

      // 5) Qoralama saqlangan — AYNI xodim qaytganda.
      signIn(id: 'eA');
      expect(DraftVault.has('form.d1', scope: _scope()), isTrue,
          reason: 'scope stash\'dan OLDIN olingan (initState), 401 paytida '
              'Api.employee allaqachon null edi');
    });

    testWidgets('reauthentication: AYNI xodim tiklaydi, BOSHQA xodim ko\'rmaydi',
        (tester) async {
      signIn(id: 'eA');
      final be = FakeBackend()
        ..get('/reports/overview', (_) => _expired())
        // ⚠️  `company_code` SHART: doira (`Session.cacheKey`) kompaniyani ham
        //     qamraydi va production'da `/auth/login/password` uni
        //     `employee_out()` orqali qaytaradi. Uni tushirib qoldirish
        //     doirani o'zgartirib, qoralamani ko'rinmas qilib qo'yadi.
        ..post('/auth/login/password', (_) => {
              'access_token': 'yangi',
              'employee': {
                'id': 'eA',
                'role_code': 'ega',
                'company_code': 'fayzan1',
                'permissions': <String>[],
              },
            });
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'A ning ishi');
        await tester.pumpAndSettle();
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await _drain(tester);
        await tester.pumpAndSettle();

        // AYNI xodim parol bilan qayta kirdi.
        await Api.login('+998901234567', 'parol');
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('draft-restore')), findsOneWidget);
        await tester.tap(find.byKey(const Key('draft-restore')));
        await tester.pumpAndSettle();
        expect(find.text('A ning ishi'), findsOneWidget);
      });
    });

    testWidgets('BOSHQA xodim login: qoralama EVICT qilinadi', (tester) async {
      signIn(id: 'eA');
      final be = FakeBackend()
        ..get('/reports/overview', (_) => _expired())
        ..post('/auth/login/password', (_) => {
              'access_token': 'yangi',
              'employee': {
                'id': 'eB',
                'role_code': 'kassir',
                'company_code': 'fayzan1',
                'permissions': <String>[],
              },
            });
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'A ning ishi');
        await tester.pumpAndSettle();
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await _drain(tester);
        await tester.pumpAndSettle();

        await Api.login('+998900000000', 'parol-B');
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('draft-restore')), findsNothing,
            reason: 'B A ning kiritmasini KO\'RMAYDI');
        expect(find.text('A ning ishi'), findsNothing);
      });
    });

    testWidgets('OSHKORA chiqish: qoralama ATAYLAB tashlanadi, xabar YO\'Q',
        (tester) async {
      signIn(id: 'eA');
      final be = FakeBackend()..post('/auth/logout', (_) => {'ok': true});
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'ish'); 
        await tester.pumpAndSettle();

        // shell.dart:380-382 dagi AYNI uch qadam.
        //
        // ⚠️  `tester.runAsync` SHART. `Api.logout()` `/auth/logout` POST
        //     qiladi va keyin Keychain + fayl tizimini tozalaydi — bu HAQIQIY
        //     I/O. Fake-async zone'da u hech qachon tugamaydi (test osilib
        //     qoladi); `runAsync` o'sha zone'dan chiqaradi.
        await tester.runAsync(() async {
          await Api.logout();
          await Lock.clear();
          DraftVault.evictAll();
        });
        await _drain(tester);
      });

      signIn(id: 'eA');
      expect(DraftVault.has('form.d1', scope: _scope()), isFalse,
          reason: 'chiqish qoralamani ataylab tashlaydi');
      expect(SessionNotice.pending, isNull,
          reason: 'o\'z xohishi bilan chiqishda xabar KERAK EMAS');
    });

    testWidgets('KUTAYOTGAN so\'rov: javob 401 bo\'lsa ham qoralama saqlanadi',
        (tester) async {
      signIn(id: 'eA');
      final gate = Completer<Object?>();
      final be = FakeBackend()..get('/reports/overview', (_) => gate.future);
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'yo\'lda');
        await tester.pumpAndSettle();

        final pending = Api.getJson('/reports/overview');
        await tester.pump();
        expect(DraftVault.isNotEmpty, isFalse, reason: 'hali 401 kelmadi');

        gate.complete(_expired());
        await expectLater(pending, throwsA(isA<ApiException>()));
        await _drain(tester);
        await tester.pumpAndSettle();
      });

      signIn(id: 'eA');
      expect(DraftVault.has('form.d1', scope: _scope()), isTrue);
    });

    testWidgets('OFFLINE: tarmoq xatosi sessiyani tugatMAYDI', (tester) async {
      signIn(id: 'eA');
      final be = FakeBackend()..offline = true;
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'offline ish');
        await tester.pumpAndSettle();
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await _drain(tester);
        await tester.pumpAndSettle();
      });

      expect(Api.token, isNotNull, reason: 'offline sessiyani tugatmaydi');
      expect(find.byType(_Form), findsOneWidget, reason: 'ekran joyida qoladi');
      expect(find.byType(LoginScreen), findsNothing);
      expect(DraftVault.isNotEmpty, isFalse, reason: 'qoralama kerak emas');
      expect(SessionNotice.pending, isNull);
    });

    testWidgets('ILOVA O\'LIMI: RAM qoralama yo\'qoladi — hujjatlashtirilgan holat',
        (tester) async {
      signIn(id: 'eA');
      final be = FakeBackend()..get('/reports/overview', (_) => _expired());
      await be.run(() async {
        await pumpAt390(tester, const _Form(docId: 'd1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('f-reason')), 'ish');
        await tester.pumpAndSettle();
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await _drain(tester);
      });
      signIn(id: 'eA');
      expect(DraftVault.has('form.d1', scope: _scope()), isTrue, reason: 'RAM da');

      // Jarayon o'ldi va qaytadan ko'tarildi: RAM bo'sh.
      DraftVault.debugClear();
      await pumpAt390(tester, const _Form(docId: 'd1'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('draft-restore')), findsNothing,
          reason: 'qoralama DISKDA saqlanmaydi — ATAYLAB (maxfiy biznes '
              'ma\'lumoti sandbox\'da qolmasligi uchun)');
    });
  });
}

/// Qoralamasi bor shakl — `DraftGuard` ning production shartnomasi bilan.
class _Form extends StatefulWidget {
  const _Form({required this.docId});
  final String docId;
  @override
  State<_Form> createState() => _FormState();
}

class _FormState extends State<_Form> with DraftGuard<_Form> {
  final _reason = TextEditingController();
  bool _offered = false;

  @override
  String get draftKey => 'form.${widget.docId}';

  @override
  Object? captureDraft() =>
      _reason.text.trim().isEmpty ? null : {'reason': _reason.text};

  @override
  void restoreDraft(Object draft) =>
      _reason.text = ((draft as Map)['reason'] ?? '').toString();

  @override
  void initState() {
    super.initState();
    _offered = hasStashedDraft;
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(children: [
          if (_offered)
            DraftRestoreCard(
              restoreKey: const Key('draft-restore'),
              onRestore: () {
                final d = claimStashedDraft();
                if (d != null) restoreDraft(d);
                setState(() => _offered = false);
              },
            ),
          TextField(key: const Key('f-reason'), controller: _reason),
        ]),
      );
}
