// R6.5 §4 — sessiya tugashi XABARNOMASI auditi.
//
// R6.4 da taklif qilingan patch `pushAndRemoveUntil` dan KEYIN `nav.canPop()`
// ni o'qiydi. Bu XATO: `(route) => false` stack'ni bo'shatgach login YAKKA
// route bo'lib qoladi va `canPop()` doim `false` qaytaradi — ya'ni xabar
// HECH QACHON ko'rsatilmaydi. Shu fayl buni o'lchaydi va to'g'ri yechimni
// (login ekranining O'ZI xabarni ko'rsatishi) qotiradi.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'support/support.dart';

void main() {
  setUp(() async {
    await resetCore();
    SessionNotice.debugClear();
  });

  group('R6.5-N. sessiya tugashi xabarnomasi', () {
    testWidgets('canPop() AUDITI: pushAndRemoveUntil dan keyin har doim false',
        (tester) async {
      signIn();
      await pumpAt390(tester, const _Work());
      await tester.pumpAndSettle();
      final nav = rootNavKey.currentState!;

      // Ish ekrani ustida turganda stack'da ikki route bor.
      nav.push(MaterialPageRoute(builder: (_) => const _Work()));
      await tester.pumpAndSettle();
      expect(nav.canPop(), isTrue, reason: 'OLDIN: qaytish mumkin');

      nav.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
      await tester.pumpAndSettle();

      expect(nav.canPop(), isFalse,
          reason: 'KEYIN: login yakka route — `canPop()` shartiga qurilgan '
              'xabar HECH QACHON ko\'rsatilmaydi');
    });

    testWidgets('xabar YANGI login ekranida HAQIQATAN ko\'rinadi', (tester) async {
      signIn();
      await pumpAt390(tester, const _Work());
      await tester.pumpAndSettle();

      // main.dart dagi ishlovchi: xabar KO'TARILADI, keyin navigatsiya.
      SessionNotice.raise(SessionEndReason.expired, draftLost: true);
      rootNavKey.currentState!.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
      await tester.pumpAndSettle();

      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.textContaining('Sessiya'), findsOneWidget,
          reason: 'xabar login ekranida ko\'rinishi SHART');
      expect(find.textContaining('saqlanmagan'), findsOneWidget,
          reason: 'yo\'qolgan ish haqida aniq aytilishi SHART');
    });

    testWidgets('qoralama yo\'qolmagan bo\'lsa — yumshoq xabar', (tester) async {
      signIn();
      await pumpAt390(tester, const _Work());
      await tester.pumpAndSettle();

      SessionNotice.raise(SessionEndReason.expired, draftLost: false);
      rootNavKey.currentState!.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('Sessiya'), findsOneWidget);
      expect(find.textContaining('saqlanmagan'), findsNothing,
          reason: 'yo\'qolgan ish bo\'lmasa SOXTA ogohlantirish berilmaydi');
    });

    testWidgets('xabar BIR MARTALIK — qayta ochilganda takrorlanmaydi',
        (tester) async {
      signIn();
      SessionNotice.raise(SessionEndReason.expired, draftLost: true);
      await pumpAt390(tester, const LoginScreen());
      await tester.pumpAndSettle();
      expect(find.textContaining('Sessiya'), findsOneWidget);

      // Login ekrani qaytadan quriladi (masalan til almashdi).
      await pumpAt390(tester, const LoginScreen());
      await tester.pumpAndSettle();
      expect(find.textContaining('Sessiya'), findsNothing,
          reason: 'bir marta ko\'rsatilgan xabar qayta chiqmaydi');
    });

    testWidgets('xabarsiz login ekrani TOZA', (tester) async {
      await pumpAt390(tester, const LoginScreen());
      await tester.pumpAndSettle();
      expect(find.textContaining('Sessiya'), findsNothing);
    });

    test('chiqish sababi xabar matnini belgilaydi', () {
      SessionNotice.raise(SessionEndReason.loggedOut, draftLost: false);
      expect(SessionNotice.pending, isNull,
          reason: 'o\'z xohishi bilan chiqish — xabar KERAK EMAS');

      SessionNotice.raise(SessionEndReason.serverChanged, draftLost: true);
      expect(SessionNotice.pending, isNotNull);
    });
  });
}

/// Qoralamasi bor ish ekranining o'rnini bosuvchi.
class _Work extends StatelessWidget {
  const _Work();
  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: Text('ish ekrani')));
}
