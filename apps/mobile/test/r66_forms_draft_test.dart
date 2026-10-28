// R6.6 §4 — risk matritsasi bo'yicha ULASH deb tasniflangan ikki shakl:
// KASSA AMALLARI va FILIALLARARO TRANSFER.
//
// NEGA shu ikkisi (18 ekrandan):
//   cash_ops_screen — ikki marta yozilgan kassa chiqimi smena yopilishida
//     kassirning shaxsiy tafovutiga aylanadi; ekranning O'ZI bu narxni
//     `_confirmForget()` matnida tan oladi, lekin 401 o'sha dialogni
//     chetlab o'tadi.
//   transfer_screen — 10-20 ta qo'lda yig'ilgan element, serverda NUSXASI YO'Q.
//
// Qolgan ekranlar P1/P2/DEFERRED sifatida hujjatlashtirilgan (hisobotga qarang).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/cash_ops_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/transfer_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'money_fixtures_test.dart';
import 'stock_fixtures_test.dart' show prodJson, lotsJson;
import 'support/support.dart';

String _scope() => Session.instance.cacheKey('draft');

/// 401 ning AYNI tartibi + main.dart ishlovchisi.
Future<void> _expire(WidgetTester t) async {
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
    DraftVault.debugClear();
    SessionNotice.debugClear();
  });
  tearDown(() => Session.instance.debugReset());

  group('R6.6-F. kassa amallari', () {
    FakeBackend be() {
      final b = FakeBackend()
        ..get('/auth/context', (_) => contextJson(role: 'ega', permissions: const []))
        ..get('/cash/custody-preview', (_) => custodyJson('OPERATOR_MUST_CHOOSE',
            reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [kSafe, kSafe2]))
        ..get('/cash/ops', (_) => const [])
        ..post('/cash/ops', (_) => {'ok': true, 'shift_id': 'sh1'});
      signIn(role: 'ega');
      return b;
    }

    testWidgets('401: summa, izoh va IDEMPOTENTLIK KALITI saqlanadi', (tester) async {
      final b = be();
      await b.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const CashOpsScreen());
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('cash-amount')), '250000');
        await tester.enterText(find.byKey(const Key('cash-note')), 'Ijara · oktabr');
        await tester.pumpAndSettle();

        await _expire(tester);
      });

      expect(find.byKey(const Key('login-session-notice')), findsOneWidget);
      signIn(role: 'ega');
      final key = 'cashops.${Session.instance.currentBranchId ?? '-'}';
      expect(DraftVault.has(key, scope: _scope()), isTrue);
      final d = DraftVault.claim(key, scope: _scope())! as Map;
      // ⚠️  Maydon summani FORMATLAB ko'rsatadi (`250 000`) — qoralama
      //     aynan ko'rinib turgan matnni saqlaydi, shu bois tiklangan
      //     shakl bir xil ko'rinadi.
      expect((d['amount']! as String).replaceAll(RegExp(r'\s'), ''), '250000');
      expect(d['note'], 'Ijara · oktabr');
      expect(d['uuid'], isNotNull,
          reason: 'client_uuid saqlanadi — ayni xarajat IKKI MARTA yozilmaydi');
    });

    testWidgets('qayta kirgach TAKLIF qilinadi va tiklanadi', (tester) async {
      final b = be();
      await b.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const CashOpsScreen());
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('cash-amount')), '250000');
        await tester.enterText(find.byKey(const Key('cash-note')), 'Ijara · oktabr');
        await tester.pumpAndSettle();
        await _expire(tester);

        signIn(role: 'ega');
        await Session.instance.load(force: true);
        await pumpAt390(tester, const CashOpsScreen());
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('cash-draft-restore')), findsOneWidget);

        await tester.tap(find.byKey(const Key('cash-draft-restore')));
        await tester.pumpAndSettle();
        expect(find.text('250 000'), findsOneWidget,
            reason: 'summa FORMATLANGAN ko\'rinishda tiklandi');
        expect(find.text('Ijara · oktabr'), findsOneWidget, reason: 'izoh tiklandi');
        expect(find.byKey(const Key('cash-draft-restore')), findsNothing);
      });
    });

    testWidgets('bo\'sh shakl 401 da qoralama YARATMAYDI', (tester) async {
      final b = be();
      await b.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const CashOpsScreen());
        await tester.pumpAndSettle();
        await _expire(tester);
      });
      signIn(role: 'ega');
      expect(DraftVault.isNotEmpty, isFalse);
      expect(find.textContaining('saqlanmagan'), findsNothing);
    });
  });

  group('R6.6-F. filiallararo transfer', () {
    FakeBackend be() {
      final b = FakeBackend()
        ..get('/auth/context', (_) => contextJson(role: 'ega', permissions: const []))
        ..get('/products', (r) => FakeResponse.json([prodJson('u1', 'Non', stock: 10)],
            headers: const {'x-total-count': '1'}))
        ..get('/lots/products/{id}', (r) => lotsJson(r.params['id']!, const [], tracked: false, inv: 10))
        ..post('/stock/transfer', (_) => {'ok': true});
      signIn(role: 'ega');
      return b;
    }

    Future<void> addItem(WidgetTester t, String qty) async {
      await t.tap(find.byKey(const Key('tr-add')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('picker-row-u1')));
      await t.pumpAndSettle();
      await t.enterText(find.byKey(const Key('tr-qty')), qty);
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('tr-qty-save')));
      await t.pumpAndSettle();
    }

    testWidgets('401: element ro\'yxati SAQLANADI va tiklanadi', (tester) async {
      final b = be();
      await b.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await addItem(tester, '4');
        expect(find.text('Non'), findsOneWidget);

        await _expire(tester);
        expect(find.byKey(const Key('login-session-notice')), findsOneWidget);

        signIn(role: 'ega');
        await Session.instance.load(force: true);
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('tr-draft-restore')), findsOneWidget);
        expect(find.text('Non'), findsNothing, reason: 'avtomatik tiklanMAYDI');

        await tester.tap(find.byKey(const Key('tr-draft-restore')));
        await tester.pumpAndSettle();
        expect(find.text('Non'), findsOneWidget, reason: 'element tiklandi');
      });
    });

    testWidgets('BOSHQA xodimga transfer KO\'RINMAYDI', (tester) async {
      final b = be();
      await b.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        await addItem(tester, '4');
        await _expire(tester);

        Session.instance.debugReset();
        b.get('/auth/context', (_) => contextJson(employeeId: 'eB', role: 'ega', permissions: const []));
        signIn(id: 'eB', role: 'ega');
        await Session.instance.load(force: true);
        await pumpAt390(tester, const TransferScreen());
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('tr-draft-restore')), findsNothing);
        expect(find.text('Non'), findsNothing);
      });
    });
  });
}
