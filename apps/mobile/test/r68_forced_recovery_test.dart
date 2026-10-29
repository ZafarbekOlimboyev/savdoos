// R6.8 P1 — MAJBURIY TIKLASH × QORALAMA, va PRODUCTION LISTENER TARTIBI.
//
// ⚠️  BU FAYL `Session.instance.attach()` NI CHAQIRADI — `main.dart:84` kabi.
//     Mavjud qoralama testlari buni QILMAYDI (`signInAs` faqat `load(force:)`
//     chaqiradi), shu bois ular PRODUCTION TARTIBINI o'lchamaydi va R6.6 da
//     e'lon qilingan himoyaning ikki ekranda ishlamasligini SEZMAGAN:
//
//       main.dart:84      Session.attach()        -> authEpoch listener #1
//       runApp            ... ekran initState     -> authEpoch listener #2
//       401               authEpoch.value++
//         listener #1     Session._signOut()      -> ctx=null, notifyListeners()
//                           ekran._onSession()    -> «filial o'zgardi» -> _items.clear()
//         listener #2     DraftGuard              -> captureDraft() == null (!)
//
//     Ya'ni `inventarizatsiya` va `transfer` ekranlari HECH NARSA saqlamasdi.
//     Tuzatish: `_onSession` sessiya TUGAGANDA darhol qaytadi (`!Api.loggedIn`).
//
// Bu fayl isbotlaydi:
//   A. production tartibida 401 da qoralama HAQIQATAN saqlanadi (ikki ekran);
//   B. 12 noto'g'ri PIN (MAJBURIY tozalash) qoralamani SAQLAYDI;
//   C. qulf ekranidagi ANIQ «Chiqish» tasdiq so'raydi va qoralamani TASHLAYDI;
//   D. `lock_recovery` «Parol bilan kirish» qoralamani SAQLAYDI;
//   E. sozlamalardagi chiqish avvalgidek TASHLAYDI (regressiya himoyasi);
//   F. saqlangan qoralamani FAQAT ayni xodim oladi; begona urinish uni YO'Q qiladi;
//   G. tiklangan qoralama AYNI `client_uuid` ni qaytaradi (ikki marta yozishga
//      qarshi yagona to'siq) — bu P1 ning MOLIYAVIY yarmi.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_guard.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/main.dart' show installSessionExpiryHandler;
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/screens/money_payment_sheet.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

import 'stock_fixtures_test.dart';

String _scope() => Session.instance.cacheKey('draft');

FakeResponse _expired() => FakeResponse.error(401, 'Sessiya bekor qilingan — qayta kiring');

Map<String, dynamic> _ctxJson({String employeeId = 'eA', String companyId = 'c1'}) =>
    contextJson(
      employeeId: employeeId,
      companyId: companyId,
      role: 'ega',
      permissions: const ['ombor.edit', 'ombor.view'],
      branches: [branchJson('b1', 'Markaz'), branchJson('b2', 'Chilonzor')],
    );

/// `main()` kabi: `attach()` + 401 ishlovchisi.
Future<void> _bootLikeProduction(FakeBackend be,
    {String employeeId = 'eA', String companyId = 'c1'}) async {
  be.get('/auth/context', (_) => _ctxJson(employeeId: employeeId, companyId: companyId));
  signIn(id: employeeId, role: 'ega', permissions: const ['ombor.edit', 'ombor.view']);
  installSessionExpiryHandler();
  //  ⚠️  `attach()` FAKE KLIENT ICHIDA: u `Api.loggedIn` bo'lsa darhol
  //      `unawaited(load())` qiladi, va o'sha so'rov `be.run` dan TASHQARIDA
  //      ketsa haqiqiy tarmoqqa urinib yiqilardi — keyin `load` ning
  //      `_inflight` ulashishi tufayli bizning `force: true` chaqirig'imiz
  //      ham o'sha nosoz natijani olardi (o'lchangan: `currentBranchId` null).
  await be.run(() async {
    Session.instance.attach(); // ← AYNAN `main.dart:84`
    await Session.instance.load(force: true);
  });
}

void main() {
  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
    SessionNotice.debugClear();
  });

  tearDown(() {
    Api.onSessionExpired = null;
    Session.instance.debugReset(); // `detach()` ni ham qiladi
  });

  // ══ A. PRODUCTION TARTIBI ══════════════════════════════════════════════════

  group('R6.8-A. production listener tartibi', () {
    testWidgets('Session BIRINCHI xabardor bo‘ladi, lekin qoralama SAQLANADI', (tester) async {
      final be = FakeBackend()..get('/reports/overview', (_) => _expired());
      await _bootLikeProduction(be);
      expect(Session.instance.currentBranchId, 'b1', reason: 'kontekst yuklandi');

      await be.run(() async {
        await pumpAt390(tester, const _BranchForm(draftKey: 'count.b1'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('bf-text')), 'yarim kiritilgan sanoq');
        await tester.pumpAndSettle();

        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      // Ekran `_onSession` ni KO'RDI (filial null bo'ldi), lekin ro'yxatni
      // TOZALAMADI — chunki sessiya TUGAGAN, filial o'zgargani emas.
      expect(_BranchForm.lastOnSessionSawLoggedOut, isTrue,
          reason: 'Session listener ekran listener\'idan OLDIN ishladi');
      expect(_BranchForm.clearedOnSessionEnd, isFalse,
          reason: 'sessiya tugashi «filial o‘zgardi» deb talqin qilinmadi');

      // Qoralama SAQLANDI (401 `evictAll` chaqirmaydi).
      signIn(id: 'eA', role: 'ega');
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson());
      await be2.run(() => Session.instance.load(force: true));
      expect(DraftVault.has('count.b1', scope: _scope()), isTrue,
          reason: 'qayta kirgach AYNI doira — qoralama tiklanishi kerak');
    });

    testWidgets('XULQ: HAQIQIY inventarizatsiya ekrani 401 da sanoqni SAQLAYDI', (tester) async {
      // ⚠️  MANFIY NAZORAT SHU TESTDA. `_onSession` dagi `if (!Api.loggedIn)`
      //     darvozasi o'chirilsa bu test QIZIL bo'ladi: `Session._signOut()`
      //     filialni null qiladi, ekran «filial o'zgardi» deb `_items` ni
      //     tozalaydi, keyin `DraftGuard` bo'sh ro'yxatni ko'rib HECH NARSA
      //     saqlamaydi. Mavjud `r66_inventory_draft_test` buni SEZMAYDI,
      //     chunki u `authEpoch` ni QO'LDA bosadi va `Session` ULANMAGAN.
      final be = FakeBackend()
        ..get('/products',
            (_) => FakeResponse.json([prodJson('p5', 'Non', stock: 10)],
                headers: const {'x-total-count': '1'}))
        ..get('/lots/products/{id}',
            (r) => lotsJson(r.params['id']!, const [], tracked: false, inv: 10))
        ..get('/reports/overview', (_) => _expired());
      await _bootLikeProduction(be);

      await be.run(() async {
        await pumpAt390(tester, const InventarizatsiyaScreen());
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('cnt-add')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('picker-row-p5')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('cnt-plain-qty')), '7');
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('cnt-plain-save')));
        await tester.pumpAndSettle();
        expect(find.text('Non'), findsOneWidget, reason: 'sanoq ro‘yxatga tushdi');

        // HAQIQIY 401 — butun produksiya zanjiri.
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      // AYNI xodim qaytadi.
      signIn(id: 'eA', role: 'ega', permissions: const ['ombor.edit', 'ombor.view']);
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson());
      await be2.run(() => Session.instance.load(force: true));
      expect(DraftVault.has('count.b1', scope: _scope()), isTrue,
          reason: 'HAQIQIY ekran + ULANGAN Session: sanoq SAQLANISHI shart. '
              'Saqlangan doiralar: ${DraftVault.debugScopes}');
    });

    testWidgets('PRODUKSIYA EKRANI: inventarizatsiya `_onSession` sessiya tugashida TOZALAMAYDI',
        (tester) async {
      // Haqiqiy ekran manbasidagi darvozani o'lchaymiz: 401 dan keyin
      // `Api.loggedIn == false`, demak «filial o'zgardi» shoxiga KIRILMAYDI.
      final src = _read('lib/screens/inventarizatsiya_screen.dart');
      final i = src.indexOf('void _onSession()');
      expect(i, greaterThan(-1));
      final body = src.substring(i, i + 1400);
      expect(body, contains('if (!Api.loggedIn) return;'),
          reason: 'sessiya tugashi darvozasi `final now = ...` dan OLDIN bo‘lishi SHART');
      expect(body.indexOf('if (!Api.loggedIn) return;'),
          lessThan(body.indexOf('final now = _s.currentBranchId;')));
    });

    testWidgets('PRODUKSIYA EKRANI: transfer `_onSession` sessiya tugashida TOZALAMAYDI',
        (tester) async {
      final src = _read('lib/screens/transfer_screen.dart');
      final i = src.indexOf('void _onSession()');
      expect(i, greaterThan(-1));
      final body = src.substring(i, i + 1400);
      expect(body, contains('if (!Api.loggedIn) return;'));
      expect(body.indexOf('if (!Api.loggedIn) return;'),
          lessThan(body.indexOf('final now = _s.currentBranchId;')));
    });
  });

  // ══ B-E. NIYAT: MAJBURIY vs ANIQ ═══════════════════════════════════════════

  group('R6.8-B. majburiy tozalash qoralamani SAQLAYDI', () {
    testWidgets('12 noto‘g‘ri PIN: sessiya ketadi, QORALAMA QOLADI', (tester) async {
      await Lock.setPin('1234');
      final be = FakeBackend()..post('/auth/logout', (_) => FakeResponse.json({'ok': true}));
      await _bootLikeProduction(be);

      // Qoralamani joylaymiz (yozuv yo'lda bo'lgan ekranni modellaydi).
      DraftVault.stash('cashops.b1', const {'uuid': 'u-1', 'unknown': true}, scope: _scope());
      expect(DraftVault.has('cashops.b1', scope: _scope()), isTrue);

      // 12 marta noto'g'ri PIN — 12-chisida `registerFail` `true` qaytaradi.
      var wipe = false;
      for (var i = 0; i < 12; i++) {
        wipe = await Lock.registerFail();
      }
      expect(wipe, isTrue, reason: 'Lock._wipeAt = 12');

      // `pin_screens._logout(userChose: false)` AYNAN shu ikkitasini qiladi.
      await tester.runAsync(() async {
        await be.run(() async {
          await Api.logout();
          await Lock.clear();
        });
      });
      await tester.pump();

      expect(Api.token, isNull, reason: 'fail-closed: token ketdi');
      expect(Lock.hasPin, isFalse, reason: 'fail-closed: PIN ketdi');

      // AYNI xodim parol bilan qaytadi.
      signIn(id: 'eA', role: 'ega');
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson());
      await be2.run(() => Session.instance.load(force: true));
      expect(DraftVault.has('cashops.b1', scope: _scope()), isTrue,
          reason: 'MAJBURIY tozalash — foydalanuvchi tanlamagan, qoralama saqlanadi');
    });

    testWidgets('MANBA: `pin_screens` niyatni AJRATADI va majburiy yo‘lda evict QILMAYDI',
        (tester) async {
      final src = _read('lib/screens/pin_screens.dart');
      expect(src, contains('Future<void> _logout({required bool userChose})'),
          reason: 'niyat parametri SHART — bitta funksiya ikki oqimga xizmat qiladi');
      expect(src, contains('await _logout(userChose: false)'),
          reason: '12 urinish yo‘li MAJBURIY');
      expect(src, contains('await _logout(userChose: true)'),
          reason: 'ANIQ «Chiqish» yo‘li');
      // `evictAll` FAQAT `userChose` shoxida.
      final j = src.indexOf('DraftVault.evictAll()');
      expect(j, greaterThan(-1));
      expect(src.substring(0, j), contains('if (userChose) {'),
          reason: 'tozalash shartsiz qolmasligi SHART');
    });

    testWidgets('MANBA: `lock_recovery` endi evict QILMAYDI', (tester) async {
      final src = _read('lib/screens/lock_recovery_screen.dart');
      expect(src.contains('DraftVault.evictAll()'), isFalse,
          reason: 'bu ekranni foydalanuvchi TANLAMAYDI (qurilma nosozligi)');
      expect(src, contains('await Lock.clear()'), reason: 'fail-closed zaiflashmaydi');
      expect(src, contains('await Api.logout()'));
    });

    testWidgets('MANBA: ANIQ chiqish yo‘llari avvalgidek TASHLAYDI', (tester) async {
      for (final f in ['lib/screens/settings_screen.dart', 'lib/screens/shell.dart']) {
        final src = _read(f);
        expect(src, contains('DraftVault.evictAll()'), reason: '$f: aniq chiqish');
        expect(src.indexOf('DraftVault.evictAll()'), greaterThan(src.indexOf('await Api.logout()')),
            reason: '$f: tozalash logout\'dan KEYIN');
      }
    });

    testWidgets('MANBA: qulf ekranidagi «Chiqish» endi TASDIQ so‘raydi', (tester) async {
      final src = _read('lib/screens/pin_screens.dart');
      expect(src, contains('onPressed: _confirmLogout'),
          reason: 'bitta tasodifiy teginish qoralamani yo‘q qilmasligi kerak');
      expect(src, contains('Future<void> _confirmLogout()'));
      final i = src.indexOf('Future<void> _confirmLogout()');
      final body = src.substring(i, i + 900);
      expect(body, contains('confirmDestructive'));
      expect(body, contains('DraftVault.isNotEmpty'),
          reason: 'saqlanmagan ish borligi tasdiqda AYTILADI');
    });
  });

  // ══ F. IZOLYATSIYA ═════════════════════════════════════════════════════════

  group('R6.8-F. saqlangan qoralama FAQAT ayni xodimga', () {
    testWidgets('BOSHQA xodim ko‘rmaydi va urinishi qoralamani YO‘Q qiladi', (tester) async {
      final be = FakeBackend();
      await _bootLikeProduction(be, employeeId: 'eA');
      final scopeA = _scope();
      DraftVault.stash('cashops.b1', const {'uuid': 'u-1'}, scope: scopeA);

      // Boshqa xodim kiradi.
      Api.token = null;
      Api.employee = null;
      signIn(id: 'eB', role: 'ega');
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson(employeeId: 'eB'));
      await be2.run(() => Session.instance.load(force: true));
      expect(_scope(), isNot(scopeA));

      expect(DraftVault.has('cashops.b1', scope: _scope()), isFalse,
          reason: 'begona xodim qoralamani KO‘RMAYDI');
      expect(DraftVault.claim('cashops.b1', scope: _scope()), isNull);

      // Birinchi xodim qaytsa ham — begona urinish uni O'CHIRGAN (bir martalik).
      Api.token = null;
      Api.employee = null;
      signIn(id: 'eA', role: 'ega');
      final be3 = FakeBackend()..get('/auth/context', (_) => _ctxJson());
      await be3.run(() => Session.instance.load(force: true));
      expect(DraftVault.has('cashops.b1', scope: _scope()), isFalse,
          reason: 'begona teginish fail-closed: qoralama yo‘q qilinadi');
    });

    testWidgets('BOSHQA do‘kon (company) ham ko‘rmaydi', (tester) async {
      final be = FakeBackend();
      await _bootLikeProduction(be, companyId: 'c1');
      DraftVault.stash('cashops.b1', const {'uuid': 'u-1'}, scope: _scope());

      Api.token = null;
      Api.employee = null;
      signIn(id: 'eA', role: 'ega');
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson(companyId: 'co2'));
      await be2.run(() => Session.instance.load(force: true));

      expect(DraftVault.has('cashops.b1', scope: _scope()), isFalse,
          reason: 'doira `server|company|employee|branch` — kompaniya ham kiradi');
    });
  });

  // ══ H. TO'LOV VARAQASI: KALIT 401 DAN OMON QOLADI ══════════════════════════

  group('R6.8-H. to\'lov varaqasi (P1)', () {
    /// Natijasi NOMA'LUM to'lovni modellaydi: server javob bermaydi.
    testWidgets('401: muzlagan to\'lov kaliti SAQLANADI va tiklanadi', (tester) async {
      final be = FakeBackend()
        ..get('/cash/custody-preview', (_) => FakeResponse.json({
              'mode': 'NOT_REQUIRED',
              'reason': null,
              'resolved': null,
              'options': <Map<String, dynamic>>[],
              'branch': {'id': 'b1', 'name': 'Markaz'},
            }))
        ..get('/reports/overview', (_) => _expired());
      await _bootLikeProduction(be);

      String? kalit;
      await be.run(() async {
        await pumpAt390(
            tester,
            Scaffold(
              body: MoneyPaymentSheet(
                partyId: 'cust-1',
                partyName: 'Ali Valiyev',
                balanceLabel: 'Joriy qarz',
                balanceCents: 500000,
                custodyOperation: CustodyOperation.debtPayment,
                submit: ({required amountCents, required method, cashAccountId,
                    required clientUuid}) async {
                  kalit = clientUuid;
                  throw ApiException(502, 'Bad Gateway');
                },
              ),
            ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();

        // Natija NOMA'LUM -> varaqa muzlagan.
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget);
        expect(kalit, isNotNull);

        // HAQIQIY 401 — modal marshrut olib tashlanadi.
        await expectLater(Api.getJson('/reports/overview'), throwsA(isA<ApiException>()));
        await flushIo(tester);
        await tester.pumpAndSettle();
      });

      // AYNI xodim qaytadi va AYNI tomon uchun varaqani ochadi.
      signIn(id: 'eA', role: 'ega', permissions: const ['ombor.edit', 'ombor.view']);
      final be2 = FakeBackend()
        ..get('/auth/context', (_) => _ctxJson())
        ..get('/cash/custody-preview', (_) => FakeResponse.json({
              'mode': 'NOT_REQUIRED',
              'reason': null,
              'resolved': null,
              'options': <Map<String, dynamic>>[],
              'branch': {'id': 'b1', 'name': 'Markaz'},
            }));
      String? kalit2;
      await be2.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(
            tester,
            Scaffold(
              body: MoneyPaymentSheet(
                partyId: 'cust-1',
                partyName: 'Ali Valiyev',
                balanceLabel: 'Joriy qarz',
                balanceCents: 500000,
                custodyOperation: CustodyOperation.debtPayment,
                submit: ({required amountCents, required method, cashAccountId,
                    required clientUuid}) async {
                  kalit2 = clientUuid;
                  return const PaymentOutcome(balanceCents: 0);
                },
              ),
            ));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('pay-draft-restore')), findsOneWidget,
            reason: 'AYNI tomon uchun muzlagan to\'lov TAKLIF qilinadi');
        await tester.tap(find.byKey(const Key('pay-draft-restore')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('pay-unknown')), findsOneWidget,
            reason: 'tiklangan varaqa MUZLAGAN qoladi');
        await tester.tap(find.byKey(const Key('sticky-primary')));
        await tester.pumpAndSettle();
      });

      expect(kalit2, kalit,
          reason: 'AYNI kalit: server `(customer_id, client_uuid)` bo\'yicha dedup '
              'qiladi, ya\'ni to\'lov IKKI MARTA yozilmaydi. Ilgari kalit '
              'varaqa `State` ida yashardi va 401 uni yo\'q qilardi.');
    });

    testWidgets('BOSHQA tomon varaqasi taklifni KO\'RMAYDI', (tester) async {
      final be = FakeBackend()
        ..get('/cash/custody-preview', (_) => FakeResponse.json({
              'mode': 'NOT_REQUIRED',
              'reason': null,
              'resolved': null,
              'options': <Map<String, dynamic>>[],
              'branch': {'id': 'b1', 'name': 'Markaz'},
            }));
      await _bootLikeProduction(be);
      // `cust-1` uchun muzlagan to'lov.
      DraftVault.stash('pay.${CustodyOperation.debtPayment}.cust-1',
          const {'amount': '5 000', 'method': 'cash', 'unknown': true}, scope: _scope());

      await be.run(() async {
        await pumpAt390(
            tester,
            Scaffold(
              body: MoneyPaymentSheet(
                partyId: 'cust-2', // BOSHQA mijoz
                partyName: 'Boshqa Mijoz',
                balanceLabel: 'Joriy qarz',
                balanceCents: 500000,
                custodyOperation: CustodyOperation.debtPayment,
                submit: ({required amountCents, required method, cashAccountId,
                    required clientUuid}) async => const PaymentOutcome(balanceCents: 0),
              ),
            ));
        await tester.pumpAndSettle();
      });

      expect(find.byKey(const Key('pay-draft-restore')), findsNothing,
          reason: 'doira `pay.<amal>.<tomon>` — begona tomonga TAKLIF qilinmaydi, '
              'aks holda to\'lov NOTO\'G\'RI tomonga yozilardi');
    });
  });

  // ══ G. MOLIYAVIY YARMI: KALIT TIKLANADI ════════════════════════════════════

  group('R6.8-G. tiklangan qoralama AYNI kalitni beradi', () {
    testWidgets('majburiy tozalashdan keyin `DraftUuid` AYNI uuid’ni qaytaradi', (tester) async {
      final be = FakeBackend()..post('/auth/logout', (_) => FakeResponse.json({'ok': true}));
      await _bootLikeProduction(be);

      // Yozuv yo'lda: kalit barmoq bilan muzlatilgan.
      final body = {'amount': 250000, 'type': 'payin'};
      final key = DraftUuid();
      final uuid = key.forDraft(body);
      DraftVault.stash('cashops.b1', {'uuid': uuid, 'fp': _json(body), 'unknown': true},
          scope: _scope());

      await tester.runAsync(() async {
        await be.run(() async {
          await Api.logout();
          await Lock.clear();
        });
      });
      await tester.pump();

      signIn(id: 'eA', role: 'ega');
      final be2 = FakeBackend()..get('/auth/context', (_) => _ctxJson());
      await be2.run(() => Session.instance.load(force: true));

      final d = DraftVault.claim('cashops.b1', scope: _scope()) as Map<String, Object?>?;
      expect(d, isNotNull, reason: 'qoralama majburiy tozalashdan OMON QOLDI');
      final fresh = DraftUuid()..restore(d!['uuid'] as String, d['fp']);
      expect(fresh.forDraft(body), uuid,
          reason: 'AYNI tana -> AYNI kalit: server buni TAKROR deb taniydi, '
              'ya‘ni amal IKKI MARTA yozilmaydi');
    });
  });
}

/// Barmoq AYNI `jsonEncode` bilan hisoblanishi SHART (`DraftUuid.restore`).
String _json(Object o) => jsonEncode(o);

/// Repo manbasini o'qiydi (VM-only testlar bu naqshni ishlatadi:
/// `core_l10n_test`, `r67_financial_p0_test`).
String _read(String rel) => File(rel).readAsStringSync();

// ── Test ekranlari ──────────────────────────────────────────────────────────

/// `inventarizatsiya_screen` / `transfer_screen` ning `_onSession` naqshini
/// MODELLAYDI: filial o'zgarishini kuzatadi va ro'yxatni tozalaydi — lekin
/// SESSIYA TUGASHIDA tozalamaydi (tuzatishdan keyingi xulq).
class _BranchForm extends StatefulWidget {
  const _BranchForm({required this.draftKey});
  final String draftKey;

  /// Oxirgi `_onSession` chaqiruvida `Api.loggedIn == false` bo'lganmi.
  static bool lastOnSessionSawLoggedOut = false;

  /// `_onSession` sessiya tugashida ro'yxatni tozaladimi.
  static bool clearedOnSessionEnd = false;

  @override
  State<_BranchForm> createState() => _BranchFormState();
}

class _BranchFormState extends State<_BranchForm> with DraftGuard<_BranchForm> {
  final _text = TextEditingController();
  String? _branchId;
  late String _key;

  @override
  String get draftKey => _key;

  @override
  Object? captureDraft() => _text.text.trim().isEmpty ? null : {'text': _text.text};

  @override
  void restoreDraft(Object draft) =>
      setState(() => _text.text = (draft as Map)['text'] as String);

  @override
  void initState() {
    _key = widget.draftKey;
    super.initState();
    _BranchForm.lastOnSessionSawLoggedOut = false;
    _BranchForm.clearedOnSessionEnd = false;
    _branchId = Session.instance.currentBranchId;
    Session.instance.addListener(_onSession);
  }

  @override
  void dispose() {
    Session.instance.removeListener(_onSession);
    _text.dispose();
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    // ⚠️  AYNAN produksiya darvozasi: sessiya tugashi filial o'zgarishi EMAS.
    if (!Api.loggedIn) {
      _BranchForm.lastOnSessionSawLoggedOut = true;
      return;
    }
    final now = Session.instance.currentBranchId;
    if (now != _branchId) {
      setState(() {
        _text.clear();
        _BranchForm.clearedOnSessionEnd = true;
        _branchId = now;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: TextField(key: const Key('bf-text'), controller: _text),
      );
}
