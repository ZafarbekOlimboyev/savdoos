// R6.5 — correction editor qoralamasi 401 dan OMON QOLADI.
//
// Fayzan, 2026-09-17: menejer tuzatish yozayotganda ega xodim parolini
// tikladi; 401 -> `pushAndRemoveUntil` -> kiritilgan hammasi yo'qoldi.
// R6.4 buni isbotladi, bu fayl TUZATILGANINI qotiradi.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

const _editor = ['xaridlar.view', 'xaridlar.edit'];
const _reasonText = 'Nakladnoyda 4 ta kam keldi, yetkazuvchi tasdiqladi';

FakeBackend _be() => FakeBackend()
  ..get('/purchases/{id}',
      (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)));

Future<void> _openEditor(WidgetTester t) async {
  await pumpAt390(t, const PurchaseDetailScreen(purchaseId: 'p1'));
  await t.pumpAndSettle();
  await t.tap(find.descendant(
      of: find.byKey(const Key('pd-bar')), matching: find.byKey(const Key('sticky-primary'))));
  await t.pumpAndSettle();
  expect(find.byType(CorrectionScreen), findsOneWidget);
}

/// 401 ning sinxron qismi: token/xodim ketadi, keyin `authEpoch` oshadi,
/// so'ng `onSessionExpired` navigatsiya qiladi (api.dart:381-396 tartibi).
Future<void> _expireSession(WidgetTester t) async {
  Api.token = null;
  Api.employee = null;
  Api.authEpoch.value++;
  await t.pump();
  SessionNotice.raise(SessionEndReason.expired, draftLost: DraftVault.isNotEmpty);
  rootNavKey.currentState!.pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const LoginScreen()),
    (route) => false,
  );
  await t.pumpAndSettle();
}

void main() {
  setUp(() async {
    await resetCore();
    PendingCorrectionKeys.clear();
    DraftVault.debugClear();
    SessionNotice.debugClear();
  });

  group('R6.5-C. correction editor qoralamasi', () {
    testWidgets('401 dan keyin qoralama SAQLANADI va xabar ko\'rinadi', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      await _be().run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), _reasonText);
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        expect(find.text(_reasonText), findsOneWidget);

        await _expireSession(tester);
      });

      // Ekran yo'q, lekin ish YO'QOLMAGAN.
      expect(find.byType(CorrectionScreen), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.byKey(const Key('login-session-notice')), findsOneWidget,
          reason: 'foydalanuvchi ogohlantiriladi');
      expect(find.textContaining('saqlanmagan'), findsOneWidget);

      signIn(role: 'menejer', permissions: _editor);
      expect(DraftVault.has('corr.p1', scope: Session.instance.cacheKey('draft')), isTrue,
          reason: 'qoralama DraftVault da');
    });

    testWidgets('AYNI xodim qayta kirgach qoralama TAKLIF qilinadi va tiklanadi',
        (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      await _be().run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), _reasonText);
        await tester.enterText(find.byKey(const Key('corr-rev-L1')), '2');
        await tester.pumpAndSettle();
        await _expireSession(tester);

        // Qayta kirish — AYNI xodim.
        signIn(role: 'menejer', permissions: _editor);
        await _openEditor(tester);

        expect(find.byKey(const Key('corr-draft-restore')), findsOneWidget,
            reason: 'tiklash TAKLIF qilinadi');
        expect(find.text(_reasonText), findsNothing,
            reason: 'avtomatik tiklanMAYDI');

        await tester.tap(find.byKey(const Key('corr-draft-restore')));
        await tester.pumpAndSettle();
        expect(find.text(_reasonText), findsOneWidget, reason: 'sabab tiklandi');
        expect(find.byKey(const Key('corr-draft-restore')), findsNothing);
      });
    });

    testWidgets('BOSHQA xodim kirsa taklif KO\'RINMAYDI', (tester) async {
      signIn(id: 'eA', role: 'menejer', permissions: _editor);
      await _be().run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), _reasonText);
        await tester.pumpAndSettle();
        await _expireSession(tester);

        // BOSHQA xodim kirdi.
        Session.instance.debugReset();
        signIn(id: 'eB', role: 'menejer', permissions: _editor);
        await _openEditor(tester);

        expect(find.byKey(const Key('corr-draft-restore')), findsNothing,
            reason: 'B A ning kiritmasini KO\'RMAYDI');
        expect(find.text(_reasonText), findsNothing);
      });
    });

    testWidgets('bo\'sh tahrirlovchi 401 da qoralama YARATMAYDI', (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      await _be().run(() async {
        await _openEditor(tester);
        await _expireSession(tester);
      });

      signIn(role: 'menejer', permissions: _editor);
      expect(DraftVault.has('corr.p1', scope: Session.instance.cacheKey('draft')), isFalse);
      expect(find.textContaining('saqlanmagan'), findsNothing,
          reason: 'yo\'qotish bo\'lmasa SOXTA ogohlantirish berilmaydi');
    });

    testWidgets('idempotentlik kaliti ham saqlanadi (ikki marta yozuv bo\'lmasin)',
        (tester) async {
      signIn(role: 'menejer', permissions: _editor);
      PendingCorrectionKeys.unknown('p1', 'uuid-A');
      await _be().run(() async {
        await _openEditor(tester);
        await tester.enterText(find.byKey(const Key('corr-reason')), _reasonText);
        await tester.pumpAndSettle();
        await _expireSession(tester);
      });
      expect(PendingCorrectionKeys.of('p1'), 'uuid-A',
          reason: 'qoralama tiklanishi idempotentlik kalitini BUZMAYDI');
    });
  });
}
