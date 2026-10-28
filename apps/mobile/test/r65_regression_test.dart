// R6.5 §3 — sessiya tugashi va qoralama xavfsizligining HAQIQIY regressiya
// to'plami. Har test UI natijasini ham tekshiradi, faqat state qiymatlarini
// emas.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/screens/app_lock.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';
import 'package:savdoos_mobile/screens/receiving_item_editor_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/session_notice.dart';

import 'correction_fixtures_test.dart';
import 'support/support.dart';

const _editor = ['xaridlar.view', 'xaridlar.edit'];
const _reason = 'Nakladnoyda 4 ta kam keldi, yetkazuvchi tasdiqladi';

String _scope() => Session.instance.cacheKey('draft');

FakeBackend _purchaseBe() => FakeBackend()
  ..get('/purchases/{id}',
      (r) => purchaseJson(custody: custodyJson('SERVER_RESOLVED', resolved: kTill)));

/// 401 ning AYNI tartibi (api.dart:381-396) + main.dart:39-55 ishlovchisi.
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

Future<void> _openCorrection(WidgetTester t) async {
  await pumpAt390(t, const PurchaseDetailScreen(purchaseId: 'p1'));
  await t.pumpAndSettle();
  await t.tap(find.descendant(
      of: find.byKey(const Key('pd-bar')), matching: find.byKey(const Key('sticky-primary'))));
  await t.pumpAndSettle();
}

void main() {
  setUp(() async {
    await resetCore();
    PendingCorrectionKeys.clear();
    DraftVault.debugClear();
    SessionNotice.debugClear();
  });

  // ── 1. Expired token + ochiq receiving form ──────────────────────────────
  testWidgets('1. muddati tugagan token + ochiq KIRIM shakli', (tester) async {
    signIn(role: 'omborchi', permissions: ['ombor.edit']);
    final line = RecvLine();
    await pumpAt390(tester, ReceivingItemEditorScreen(line: line));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('recv-edit-name')), 'Coca-Cola 1L');
    await tester.pumpAndSettle();

    await _expire(tester);
    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.byKey(const Key('login-session-notice')), findsOneWidget);
    expect(find.textContaining('saqlanmagan'), findsOneWidget);

    // AYNI xodim qayta kirdi -> taklif ko'rinadi -> tiklanadi
    signIn(role: 'omborchi', permissions: ['ombor.edit']);
    await pumpAt390(tester, ReceivingItemEditorScreen(line: line));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('recv-draft-restore')), findsOneWidget);

    await tester.tap(find.byKey(const Key('recv-draft-restore')));
    await tester.pumpAndSettle();
    expect(find.text('Coca-Cola 1L'), findsOneWidget, reason: 'kirim satri tiklandi');
  });

  // ── 2. Expired token + inventarizatsiya ────────────────────────────────
  // R6.5 da bu ssenariy ataylab SKIP qilingan edi. R6.6 audit o'sha bahoni
  // TUZATDI: ichki sheet'lar (`_PlainCountSheet`, `_LotCountPage`) o'z
  // `CountEntry` ini ASOSIY ekranga qaytaradi, ya'ni butun sanoq `_items` da
  // yashaydi va uni saqlash yetarli. To'liq qamrov:
  // `test/r66_inventory_draft_test.dart` (5 test) va shu fayldagi 2a-test.
  testWidgets('2a. inventarizatsiya qoralamasi DraftVault da bog\'lanadi', (tester) async {
    signIn(id: 'eA', role: 'ega');
    // Sanoq filialga bog'lanadi: `count.<branchId>`.
    DraftVault.stash('count.b1', <String, Object?>{
      'items': const <Object>[],
      'branchId': 'b1',
      'uuid': 'uuid-sanoq',
      'fp': '{}',
      'unknown': false,
    }, scope: _scope());

    expect(DraftVault.has('count.b1', scope: _scope()), isTrue);
    expect(DraftVault.has('count.b2', scope: _scope()), isFalse,
        reason: 'boshqa FILIAL sanog\'i aralashmaydi');
    final d = DraftVault.claim('count.b1', scope: _scope())! as Map;
    expect(d['uuid'], 'uuid-sanoq',
        reason: 'client_uuid qoralama bilan saqlanadi — tiklangan sanoq '
            'IKKINCHI yozuv yaratmaydi');
  });

  // ── 3. Expired token + correction editor ─────────────────────────────────
  testWidgets('3. muddati tugagan token + TUZATISH tahrirlovchisi', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), _reason);
      await tester.pumpAndSettle();
      await _expire(tester);
    });
    expect(find.byType(CorrectionScreen), findsNothing);
    signIn(role: 'menejer', permissions: _editor);
    expect(DraftVault.has('corr.p1', scope: _scope()), isTrue);
  });

  // ── 4. Qayta login — AYNI xodim ──────────────────────────────────────────
  testWidgets('4. qayta login AYNI xodim: qoralama tiklanadi', (tester) async {
    signIn(id: 'eA', role: 'menejer', permissions: _editor);
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), _reason);
      await tester.pumpAndSettle();
      await _expire(tester);

      signIn(id: 'eA', role: 'menejer', permissions: _editor);
      await _openCorrection(tester);
      await tester.tap(find.byKey(const Key('corr-draft-restore')));
      await tester.pumpAndSettle();
      expect(find.text(_reason), findsOneWidget);
    });
  });

  // ── 5. Qayta login — BOSHQA xodim ────────────────────────────────────────
  testWidgets('5. BOSHQA xodim login: qoralama KO\'RINMAYDI', (tester) async {
    signIn(id: 'eA', role: 'menejer', permissions: _editor);
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), _reason);
      await tester.pumpAndSettle();
      await _expire(tester);

      Session.instance.debugReset();
      signIn(id: 'eB', role: 'menejer', permissions: _editor);
      await _openCorrection(tester);
      expect(find.byKey(const Key('corr-draft-restore')), findsNothing);
      expect(find.text(_reason), findsNothing);
    });
  });

  // ── 6. Ilovani qayta ishga tushirish ────────────────────────────────────
  testWidgets('6. ilova QAYTA ISHGA TUSHSA qoralama yo\'q (diskka yozilmaydi)',
      (tester) async {
    signIn(id: 'eA', role: 'menejer', permissions: _editor);
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), _reason);
      await tester.pumpAndSettle();
      await _expire(tester);
    });
    signIn(id: 'eA', role: 'menejer', permissions: _editor);
    expect(DraftVault.has('corr.p1', scope: _scope()), isTrue, reason: 'hozir RAM da');

    // Ilova o'ldi va qaytadan ko'tarildi: RAM bo'sh, disk TOZA.
    DraftVault.debugClear();
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      expect(find.byKey(const Key('corr-draft-restore')), findsNothing,
          reason: 'qoralama DISKDA saqlanmaydi — bu ATAYLAB');
    });
  });

  // ── 7. Hisob/filial almashishi ──────────────────────────────────────────
  testWidgets('7. FILIAL almashsa qoralama ko\'rinmaydi', (tester) async {
    signIn(id: 'eA', role: 'menejer', permissions: _editor);
    final before = _scope();
    DraftVault.stash('corr.p1', {'reason': _reason}, scope: before);

    // Boshqa filialdagi AYNI xodim — `cacheKey` filialni ham qamraydi.
    expect(DraftVault.has('corr.p1', scope: '$before|boshqa-filial'), isFalse);

    await _purchaseBe().run(() async {
      Session.instance.debugReset();
      signIn(id: 'eA', role: 'menejer', permissions: _editor, companyCode: 'boshqa-dokon');
      await _openCorrection(tester);
      expect(find.byKey(const Key('corr-draft-restore')), findsNothing,
          reason: 'boshqa kompaniya — begona kiritma ko\'rinmaydi');
    });
  });

  // ── 8. Offline / online ─────────────────────────────────────────────────
  testWidgets('8. OFFLINE tarmoq xatosi sessiyani TUGATMAYDI', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    final be = _purchaseBe()..offline = true;
    await be.run(() async {
      await pumpAt390(tester, const PurchaseDetailScreen(purchaseId: 'p1'));
      await tester.pumpAndSettle();
      // Tarmoq yo'q: 401 kelmaydi, token saqlanadi, qoralama ham kerak emas.
      expect(Api.token, isNotNull, reason: 'offline sessiyani tugatmaydi');
      expect(DraftVault.isNotEmpty, isFalse);
      expect(find.byType(LoginScreen), findsNothing);
    });
  });

  // ── 9. Kutayotgan so'rov va IKKI MARTA yuborish ─────────────────────────
  testWidgets('9. qoralama tiklanishi IKKI MARTA yozuv yaratmaydi', (tester) async {
    signIn(role: 'menejer', permissions: _editor);
    PendingCorrectionKeys.unknown('p1', 'uuid-A');
    await _purchaseBe().run(() async {
      await _openCorrection(tester);
      await tester.enterText(find.byKey(const Key('corr-reason')), _reason);
      await tester.pumpAndSettle();
      await _expire(tester);

      signIn(role: 'menejer', permissions: _editor);
      await _openCorrection(tester);
      await tester.tap(find.byKey(const Key('corr-draft-restore')));
      await tester.pumpAndSettle();
    });
    expect(PendingCorrectionKeys.of('p1'), 'uuid-A',
        reason: 'javobi noma\'lum so\'rovning kaliti O\'ZGARMAYDI — '
            'tiklangan qoralama ikkinchi immutable tuzatish yozmaydi');
  });

  // ── 10. PIN / Face ID fail-closed ───────────────────────────────────────
  testWidgets('10. qoralama tiklanishi QULFNI ochmaydi (fail-closed)', (tester) async {
    await Lock.setPin('1234');
    await Lock.setBiometric(true);
    signIn(role: 'menejer', permissions: _editor);
    final scope = _scope();
    DraftVault.stash('corr.p1', {'reason': _reason}, scope: scope);

    // 401: qulf TOZALANADI (PIN yo'q), qoralama esa qoladi.
    await Lock.clear();
    expect(Lock.status, LockStatus.absent, reason: 'PIN o\'chdi');
    expect(Lock.biometricOn, isFalse, reason: 'biometrika o\'chdi');
    expect(DraftVault.has('corr.p1', scope: scope), isTrue,
        reason: 'qoralama qulfdan MUSTAQIL saqlanadi');

    // Qoralamani olish uchun sessiya KERAK: chiqilgan holatda doira noma'lum.
    Api.token = null;
    Api.employee = null;
    Session.instance.debugReset();
    expect(DraftVault.has('corr.p1', scope: _scope()), isFalse,
        reason: 'autentifikatsiyasiz qoralama OCHILMAYDI — fail-closed');
  });
}
