// R6.6 §2 — INVENTARIZATSIYA qoralamasi 401 dan omon qoladi.
//
// R6.5 da bu ssenariy ataylab SKIP qilingan edi ("ichki sheet'lar uchun uchta
// kalit kerak"). Audit bu bahoni TUZATDI: `_PlainCountSheet` va
// `_LotCountPage` o'z `CountEntry` ini ASOSIY ekranga qaytaradi
// (inventarizatsiya_screen.dart:244, :251), ya'ni butun sanoq asosiy
// ekrandagi `_items` da yashaydi. Shuni saqlash katta yo'qotishni yopadi.
//
// ⚠️  KRITIK: `client_uuid` ham tiklanishi SHART. `_submit` kalitni
//     `_uuid.forDraft(body)` bilan oladi (:338) — tiklangan sanoq YANGI kalit
//     olsa, ayni sanoq serverda IKKINCHI marta yozilardi.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'stock_fixtures_test.dart';

String _scope() => Session.instance.cacheKey('draft');

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
    SessionNotice.debugClear();
    be = FakeBackend();
  });
  tearDown(() => Session.instance.debugReset());

  void catalog() {
    be.get(
        '/products',
        (r) => FakeResponse.json([prodJson('p5', 'Non', stock: 10), prodJson('p6', 'Tuz', stock: 4)],
            headers: const {'x-total-count': '2'}));
    be.get('/lots/products/{id}', (r) => lotsJson(r.params['id']!, const [], tracked: false, inv: 10));
  }

  Future<void> addPlain(WidgetTester tester, String id, String qty) async {
    await tester.tap(find.byKey(const Key('cnt-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(Key('picker-row-$id')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('cnt-plain-qty')), qty);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cnt-plain-save')));
    await tester.pumpAndSettle();
  }

  /// 401 ning AYNI tartibi (api.dart:381-396) + main.dart ishlovchisi.
  Future<void> expire(WidgetTester t) async {
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

  testWidgets('401: sanoq ro\'yxati SAQLANADI va xabar ko\'rinadi', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await addPlain(tester, 'p6', '3');
      expect(find.text('Non'), findsOneWidget);
      expect(find.text('Tuz'), findsOneWidget);

      await expire(tester);
    });

    expect(find.byType(InventarizatsiyaScreen), findsNothing);
    expect(find.byKey(const Key('login-session-notice')), findsOneWidget);
    expect(find.textContaining('saqlanmagan'), findsOneWidget);

    await signInAs(be);
    expect(DraftVault.has('count.b1', scope: _scope()), isTrue,
        reason: 'sanoq DraftVault da, filial bilan bog\'langan');
  });

  testWidgets('AYNI xodim qayta kirgach sanoq TAKLIF qilinadi va tiklanadi', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await addPlain(tester, 'p6', '3');
      await expire(tester);

      await signInAs(be);
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('cnt-draft-restore')), findsOneWidget,
          reason: 'tiklash TAKLIF qilinadi');
      expect(find.text('Non'), findsNothing, reason: 'avtomatik tiklanMAYDI');

      await tester.tap(find.byKey(const Key('cnt-draft-restore')));
      await tester.pumpAndSettle();
      expect(find.text('Non'), findsOneWidget, reason: 'sanoq tiklandi');
      expect(find.text('Tuz'), findsOneWidget);
      expect(find.byKey(const Key('cnt-draft-restore')), findsNothing);
    });
  });

  testWidgets('tiklangan sanoq AYNI client_uuid bilan yuboriladi (ikki yozuv YO\'Q)',
      (tester) async {
    await signInAs(be);
    catalog();
    be.post('/inventory/count', (r) => {'ok': true, 'changed': 1, 'results': const []});

    String? uuidBefore;
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');

      // Qoralama saqlansin, keyin AYNI holatdagi kalitni o'lchaymiz.
      Api.authEpoch.value++;
      await tester.pump();
      final d = DraftVault.claim('count.b1', scope: _scope())! as Map;
      uuidBefore = d['uuid'] as String?;
      expect(uuidBefore, isNotNull, reason: 'kalit qoralama bilan saqlanadi');
      DraftVault.stash('count.b1', d, scope: _scope()); // qayta qo'yamiz

      await expire(tester);
      await signInAs(be);
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cnt-draft-restore')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('sticky-primary')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
    });

    final sent = be.last('POST', '/inventory/count');
    expect(sent.body['client_uuid'], uuidBefore,
        reason: 'tiklangan sanoq AYNI kalit bilan ketadi — server ikkinchi '
            'yozuvni idempotent rad etadi');
  });

  testWidgets('BOSHQA xodimga sanoq KO\'RINMAYDI', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await addPlain(tester, 'p5', '7');
      await expire(tester);

      Session.instance.debugReset();
      // BOSHQA xodim kirdi. Doira `Session._ctx.employeeId` dan quriladi
      // (session.dart:501) — ya'ni SERVER aytgan xodimdan, lokal snapshot'dan
      // emas. Shu bois `/auth/context` ham B ni qaytarishi SHART: production'da
      // aynan shunday bo'ladi.
      be.get('/auth/context',
          (_) => contextJson(employeeId: 'eB', role: 'ega',
              permissions: kRolePerms['ega'] ?? const [], branches: twoBranches()));
      signIn(id: 'eB', role: 'ega', permissions: kRolePerms['ega'] ?? const []);
      await Session.instance.load(force: true);
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cnt-draft-restore')), findsNothing,
          reason: 'B A ning sanog\'ini KO\'RMAYDI');
      expect(find.text('Non'), findsNothing);
    });
  });

  testWidgets('bo\'sh sanoq 401 da qoralama YARATMAYDI', (tester) async {
    await signInAs(be);
    catalog();
    await be.run(() async {
      await pumpAt390(tester, const InventarizatsiyaScreen());
      await tester.pumpAndSettle();
      await expire(tester);
    });
    await signInAs(be);
    expect(DraftVault.has('count.b1', scope: _scope()), isFalse);
    expect(find.textContaining('saqlanmagan'), findsNothing);
  });
}
