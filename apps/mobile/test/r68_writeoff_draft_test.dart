// R6.8 P0-1 — HISOBDAN CHIQARISH: KALIT SESSIYA TUGASHIDAN OMON QOLADI.
//
// NUQSON (R6.7): ikki marta yozishga qarshi yagona to'siq `_frozenUuid` edi va
// u FAQAT widget `State` ida yashardi. 401, qulfdan chiqish, qulf tiklash,
// crash yoki iOS'ning fonda ilovani o'ldirishi `State` ni yo'q qilardi;
// operator AYNI amalni qaytadan kiritardi; YANGI tasodifiy kalit serverda
// YANGI, qabul qilinadigan write-off bo'lardi va QOLDIQ + TANNARX IKKI MARTA
// hisobdan chiqardi. Ekran `DraftGuard` ro'yxatida YO'Q edi, `DraftVault` esa
// bo'sh bo'lgani uchun login ekrani «saqlanmagan ma'lumot» ham demasdi.
//
// Bu fayl KLIENT yarmini isbotlaydi (server yarmi:
// `apps/server/tests/test_r68_writeoff_double_post.py`):
//   1. 502 (natija NOMA'LUM) -> qoralama muzlaydi (mavjud xulq, regressiya himoyasi);
//   2. HAQIQIY 401 -> muzlagan tana va KALIT `DraftVault` ga tushadi;
//   3. AYNI xodim qaytgach TAKLIF ko'rinadi, tiklash AYNI `client_uuid` ni beradi;
//   4. tiklangan ekran MUZLAGAN qoladi (`_unknown`) — avtomatik yuborish YO'Q;
//   5. BOSHQA xodim taklifni KO'RMAYDI;
//   6. server 409 `WRITEOFF_DUPLICATE_SUSPECTED` -> ANIQ banner, kalit muzlaydi,
//      tasdiqlangan yuborish `confirm_duplicate: true` bilan ketadi;
//   7. server 409 `IDEMPOTENCY_KEY_REUSED` -> qulf QO'YILMAYDI, kalit AYLANADI
//      (aks holda ekran abadiy 409 olardi);
//   8. RECONCILIATION: `GET /inventory/writeoff/status` NOMA'LUMNI hal qiladi —
//      «yozilgan» bo'lsa qulf ochiladi, «yozilmagan» bo'lsa SAQLANADI;
//   9. tekshiruv YIQILSA qulf SAQLANADI (taxmin qilinmaydi).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/stock_api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/main.dart' show installSessionExpiryHandler;
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'stock_fixtures_test.dart';

String _scope() => Session.instance.cacheKey('draft');

FakeResponse _expired() => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring');
FakeResponse _gateway502(FakeRequest _) => FakeResponse.error(502, 'Bad Gateway');

FakeResponse _dupSuspected(FakeRequest _) => FakeResponse.error(
      409,
      'Bu hisobdan chiqarish shu filialda yaqinda allaqachon yozilgan. Agar bu HAQIQATAN '
      'ikkinchi, alohida amal bo\'lsa — tasdiqlang; aks holda qoldiq ikki marta kamayadi.',
      code: kWriteoffDuplicateSuspected,
    );

FakeResponse _keyReused(FakeRequest _) => FakeResponse.error(
      409,
      'Bu idempotentlik kaliti BOSHQA hisobdan chiqarish uchun ishlatilgan — amal YOZILMADI. '
      'Yangi kalit bilan qaytadan yuboring.',
      code: kIdempotencyKeyReused,
    );

Map<String, dynamic> _ctx({String employeeId = 'eA'}) => contextJson(
      employeeId: employeeId,
      companyId: 'c1',
      role: 'ega',
      permissions: const ['ombor.edit', 'ombor.view', 'lots.product'],
      branches: [branchJson('b1', 'Markaz')],
    );

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
    SessionNotice.debugClear();
    be = FakeBackend();
  });

  tearDown(() {
    Api.onSessionExpired = null;
    Session.instance.debugReset();
  });

  void untracked() => be.get(
      '/lots/products/{id}', (r) => lotsJson('p5', const [], tracked: false, inv: 20));

  /// `main()` kabi ulanish: `attach()` + 401 ishlovchisi.
  Future<void> boot({String employeeId = 'eA'}) async {
    be.get('/auth/context', (_) => _ctx(employeeId: employeeId));
    signIn(id: employeeId, role: 'ega',
        permissions: const ['ombor.edit', 'ombor.view', 'lots.product']);
    installSessionExpiryHandler();
    await be.run(() async {
      Session.instance.attach();
      await Session.instance.load(force: true);
    });
  }

  Future<void> openForm(WidgetTester tester) async {
    await pumpAt390(
        tester, const WriteoffScreen(initialProduct: StockProduct(id: 'p5', name: 'Sut 1L')));
    await tester.pumpAndSettle();
  }

  Future<void> fill(WidgetTester tester, {String qty = '5'}) async {
    await tester.enterText(find.byKey(const Key('wo-qty')), qty);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('wo-reason-damaged')));
    await tester.pumpAndSettle();
  }

  Future<void> send(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('sticky-primary')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-yes')));
    await tester.pumpAndSettle();
  }

  // ══ 1-2. 502 -> MUZLASH -> 401 -> SAQLANISH ════════════════════════════════

  group('R6.8-1. natija noma\'lum -> kalit SAQLANADI', () {
    testWidgets('502 dan keyin HAQIQIY 401: muzlagan tana va KALIT vault\'ga tushadi',
        (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/reports/overview', (_) => _expired());

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        // Natija NOMA'LUM: ekran muzlagan (mavjud xulq).
        expect(find.byKey(const Key('wo-unknown')), findsOneWidget);
        expect(find.textContaining('SOLISHTIRISH KERAK'), findsOneWidget,
            reason: 'R6.8: holat NOMA\'LUM ekani ANIQ aytiladi');
        expect(find.text('Qayta yuborish'), findsOneWidget);

        // HAQIQIY 401 — butun produksiya zanjiri.
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      // AYNI xodim qaytadi.
      signIn(id: 'eA', role: 'ega',
          permissions: const ['ombor.edit', 'ombor.view', 'lots.product']);
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctx());
      await be2.run(() => Session.instance.load(force: true));

      expect(DraftVault.has('writeoff.b1', scope: _scope()), isTrue,
          reason: 'MUZLAGAN write-off kaliti saqlanishi SHART — bu ikki marta '
              'yozishga qarshi yagona to\'siq. Doiralar: ${DraftVault.debugScopes}');
    });

    testWidgets('login ekrani SAQLANMAGAN ma\'lumot borligini AYTADI', (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/reports/overview', (_) => _expired());

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      expect(find.byKey(const Key('login-session-notice')), findsOneWidget);
      expect(find.textContaining('saqlanmagan'), findsOneWidget,
          reason: 'ilgari DraftVault bo\'sh bo\'lgani uchun bu xabar CHIQMASDI — '
              'operator muzlagan amal borligini BILMASDI');
    });
  });

  // ══ 3-5. TIKLASH ═══════════════════════════════════════════════════════════

  group('R6.8-3. tiklash AYNI kalitni beradi', () {
    testWidgets('AYNI xodim: taklif ko\'rinadi, tiklangan ekran MUZLAGAN qoladi',
        (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/reports/overview', (_) => _expired());

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      signIn(id: 'eA', role: 'ega',
          permissions: const ['ombor.edit', 'ombor.view', 'lots.product']);
      final be2 = FakeBackend()
        ..get('/auth/context', (_) => _ctx())
        ..get('/lots/products/{id}',
            (r) => lotsJson('p5', const [], tracked: false, inv: 20));
      await be2.run(() async {
        await Session.instance.load(force: true);
        await openForm(tester);
        expect(find.byKey(const Key('wo-draft-restore')), findsOneWidget,
            reason: 'taklif AVTOMATIK tiklamaydi — foydalanuvchi bosadi');
        await tester.tap(find.byKey(const Key('wo-draft-restore')));
        await tester.pumpAndSettle();
      });

      // Tiklangan ekran MUZLAGAN: avtomatik yuborish MUMKIN EMAS.
      expect(find.byKey(const Key('wo-unknown')), findsOneWidget,
          reason: '`_unknown` tiklanishi SHART, aks holda operator ikkinchi marta yuborardi');
      expect(find.text('Qayta yuborish'), findsOneWidget);
      expect(find.byKey(const Key('wo-draft-restore')), findsNothing,
          reason: 'bir martalik: taklif yo\'qoladi');
    });

    testWidgets('BOSHQA xodim taklifni KO\'RMAYDI', (tester) async {
      await boot(employeeId: 'eA');
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/reports/overview', (_) => _expired());

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      // BOSHQA xodim kiradi.
      Api.token = null;
      Api.employee = null;
      signIn(id: 'eB', role: 'ega',
          permissions: const ['ombor.edit', 'ombor.view', 'lots.product']);
      final be2 = FakeBackend()
        ..get('/auth/context', (_) => _ctx(employeeId: 'eB'))
        ..get('/lots/products/{id}',
            (r) => lotsJson('p5', const [], tracked: false, inv: 20));
      await be2.run(() async {
        await Session.instance.load(force: true);
        await openForm(tester);
      });

      expect(find.byKey(const Key('wo-draft-restore')), findsNothing,
          reason: 'doira `server|company|employee|branch` — begona xodim KO\'RMAYDI');
    });
  });

  // ══ 6-7. SERVER DARVOZALARI ════════════════════════════════════════════════

  group('R6.8-6. 409 WRITEOFF_DUPLICATE_SUSPECTED', () {
    testWidgets('ANIQ banner, kalit MUZLAYDI, tasdiq `confirm_duplicate` yuboradi',
        (tester) async {
      await boot();
      untracked();
      final sent = <Map<String, Object?>>[];
      be.post('/inventory/writeoff', (r) {
        sent.add(r.body.cast<String, Object?>());
        // Birinchi so'rov — 409; tasdiqlangan ikkinchisi — 200.
        if (sent.last['confirm_duplicate'] == true) {
          return FakeResponse.json({'ok': true, 'product': 'Sut 1L', 'new_qty': 15});
        }
        return _dupSuspected(r);
      });

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);

        expect(find.byKey(const Key('wo-dup-suspected')), findsOneWidget,
            reason: 'operator QAROR qabul qilishi kerak — bu dedup EMAS');
        expect(find.textContaining('HECH NARSA yozilmadi'), findsOneWidget,
            reason: 'hozir nima bo\'lgani ANIQ aytiladi');
        expect(find.text('Tasdiqlab yuborish'), findsOneWidget);
        expect(find.byKey(const Key('wo-unknown')), findsNothing,
            reason: 'natija ANIQ — bu `_unknown` EMAS');

        // Tasdiqlangan yuborish.
        await send(tester);
      });

      expect(sent.length, 2, reason: 'avtomatik qayta yuborish YO\'Q');
      expect(sent[0]['confirm_duplicate'], isNull, reason: 'birinchi so\'rov tasdiqsiz');
      expect(sent[1]['confirm_duplicate'], isTrue, reason: 'ikkinchisi TASDIQLANGAN');
      expect(sent[1]['client_uuid'], sent[0]['client_uuid'],
          reason: 'tana ham, KALIT ham MUZLAGAN: operator tasdiqlagan narsa '
              'yuborilgan narsa bilan AYNI bo\'lishi SHART');
      expect(sent[1]['qty'], sent[0]['qty']);
    });
  });

  group('R6.8-7. 409 IDEMPOTENCY_KEY_REUSED', () {
    testWidgets('qulf QO\'YILMAYDI va kalit AYLANADI', (tester) async {
      await boot();
      untracked();
      final sent = <Map<String, Object?>>[];
      be.post('/inventory/writeoff', (r) {
        sent.add(r.body.cast<String, Object?>());
        return _keyReused(r);
      });

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);

        expect(find.byKey(const Key('wo-unknown')), findsNothing,
            reason: 'server HECH NARSA yozilmaganini ANIQ aytdi');
        expect(find.byKey(const Key('wo-dup-suspected')), findsNothing);
        expect(find.byKey(const Key('wo-error')), findsOneWidget);
        // Ekran TAHRIRLANADIGAN qoladi — aks holda u abadiy 409 olardi.
        await tester.enterText(find.byKey(const Key('wo-qty')), '6');
        await tester.pumpAndSettle();
        await send(tester);
      });

      expect(sent.length, 2);
      expect(sent[1]['client_uuid'], isNot(sent[0]['client_uuid']),
          reason: 'kalit BAND -> yangi kalit kerak');
    });
  });

  // ══ 8-9. RECONCILIATION ════════════════════════════════════════════════════

  group('R6.8-8. serverda tekshirish NOMA\'LUMNI hal qiladi', () {
    testWidgets('«yozilgan» -> qulf OCHILADI, forma tozalanadi', (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      String? askedUuid;
      be.get('/inventory/writeoff/status', (r) {
        askedUuid = r.query['client_uuid'];
        return FakeResponse.json(
            {'recorded': true, 'qty': 5, 'reason': 'damaged', 'at': '2026-10-29T10:00:00Z'});
      });

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        expect(find.byKey(const Key('wo-unknown')), findsOneWidget);

        await tester.tap(find.byKey(const Key('banner-retry')));
        await tester.pumpAndSettle();
      });

      expect(askedUuid, isNotNull, reason: 'MUZLAGAN kalit bo\'yicha so\'raladi');
      expect(find.byKey(const Key('wo-unknown')), findsNothing,
          reason: 'holat ANIQLANDI — qulf kerak emas');
      expect(find.byKey(const Key('wo-check-notice')), findsOneWidget);
      expect(find.textContaining('YOZILGAN'), findsOneWidget);
    });

    testWidgets('«yozilmagan» -> qulf SAQLANADI', (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/inventory/writeoff/status', (_) => FakeResponse.json({'recorded': false}));

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        await tester.tap(find.byKey(const Key('banner-retry')));
        await tester.pumpAndSettle();
      });

      expect(find.byKey(const Key('wo-unknown')), findsOneWidget,
          reason: 'amal yozilmagan — AYNI kalit bilan qayta yuborish kerak');
      expect(find.textContaining('YOZILMAGAN'), findsOneWidget);
    });

    testWidgets('tekshiruv YIQILSA qulf SAQLANADI (taxmin YO\'Q)', (tester) async {
      await boot();
      untracked();
      be.post('/inventory/writeoff', _gateway502);
      be.get('/inventory/writeoff/status', (_) => FakeResponse.error(503, 'yo\'q'));

      await be.run(() async {
        await openForm(tester);
        await fill(tester);
        await send(tester);
        await tester.tap(find.byKey(const Key('banner-retry')));
        await tester.pumpAndSettle();
      });

      expect(find.byKey(const Key('wo-unknown')), findsOneWidget,
          reason: '«tekshirib bo\'lmadi» — «yozilmagan» DEGANI EMAS');
      expect(find.textContaining('hamon noma'), findsOneWidget);
    });
  });
}
