// R6.5 — `DraftGuard` mixin: ekran sessiya tugashini ko'rib qoralamani
// `DraftVault` ga topshiradi, qayta kirgach uni TAKLIF qiladi.
//
// Tartib (api.dart:381-396 da o'lchangan):
//   token = null; employee = null;  -> authEpoch.value++  -> ... -> onSessionExpired
// Ya'ni `authEpoch` listener'i `pushAndRemoveUntil` dan OLDIN ishlaydi, lekin
// o'sha paytda `Api.employee` ALLAQACHON null. Shu bois doira (scope) ekran
// `initState` ida olinishi SHART — mixin aynan shuni qiladi.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_guard.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

void main() {
  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
  });

  group('R6.5-G. DraftGuard mixin', () {
    testWidgets('sessiya tugashida qoralamani SAQLAYDI', (tester) async {
      signIn(id: 'eA');
      await pumpAt390(tester, const _Form(docId: 'r1'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('f-reason')), 'Nakladnoyda 4 ta kam');
      await tester.pumpAndSettle();

      // 401 ning sinxron qismi: token/xodim ketadi, keyin authEpoch oshadi.
      Api.token = null;
      Api.employee = null;
      Api.authEpoch.value++;
      await tester.pump();

      // Xodim qaytib keldi.
      signIn(id: 'eA');
      expect(DraftVault.has('form.r1', scope: Session.instance.cacheKey('draft')), isTrue,
          reason: 'qoralama saqlangan');
    });

    testWidgets('qayta kirgach qoralama TAKLIF qilinadi va tiklanadi', (tester) async {
      signIn(id: 'eA');
      DraftVault.stash('form.r1', {'reason': 'oldingi kiritma'},
          scope: Session.instance.cacheKey('draft'));

      await pumpAt390(tester, const _Form(docId: 'r1'));
      await tester.pumpAndSettle();

      // Taklif ko'rinadi, lekin matn HALI qo'yilmagan (avtomatik emas).
      expect(find.byKey(const Key('draft-restore')), findsOneWidget,
          reason: 'tiklash TAKLIF qilinadi');
      expect(find.text('oldingi kiritma'), findsNothing,
          reason: 'avtomatik tiklanMAYDI — foydalanuvchi tanlaydi');

      await tester.tap(find.byKey(const Key('draft-restore')));
      await tester.pumpAndSettle();
      expect(find.text('oldingi kiritma'), findsOneWidget, reason: 'tiklandi');
      expect(find.byKey(const Key('draft-restore')), findsNothing,
          reason: 'taklif bir martalik');
    });

    testWidgets('BOSHQA xodimga taklif KO\'RINMAYDI', (tester) async {
      signIn(id: 'eA');
      DraftVault.stash('form.r1', {'reason': 'A ning ishi'},
          scope: Session.instance.cacheKey('draft'));

      Session.instance.debugReset();
      signIn(id: 'eB');
      await pumpAt390(tester, const _Form(docId: 'r1'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('draft-restore')), findsNothing,
          reason: 'B A ning kiritmasini KO\'RMAYDI');
      expect(find.text('A ning ishi'), findsNothing);
    });

    testWidgets('bo\'sh shakl saqlanMAYDI', (tester) async {
      signIn(id: 'eA');
      await pumpAt390(tester, const _Form(docId: 'r1'));
      await tester.pumpAndSettle();
      // hech narsa kiritilmadi
      Api.token = null;
      Api.employee = null;
      Api.authEpoch.value++;
      await tester.pump();

      signIn(id: 'eA');
      expect(DraftVault.has('form.r1', scope: Session.instance.cacheKey('draft')), isFalse,
          reason: 'bo\'sh shakl uchun qoralama yaratilmaydi');
    });

    testWidgets('ekran yopilganda listener olib tashlanadi (leak yo\'q)',
        (tester) async {
      signIn(id: 'eA');
      await pumpAt390(tester, const _Form(docId: 'r1'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('f-reason')), 'x');
      await tester.pumpAndSettle();

      // Ekran yopiladi (oddiy orqaga qaytish — sessiya tugamagan).
      await pumpAt390(tester, const SizedBox.shrink());
      await tester.pumpAndSettle();

      Api.authEpoch.value++;
      await tester.pump();
      expect(DraftVault.has('form.r1', scope: Session.instance.cacheKey('draft')), isFalse,
          reason: 'yopilgan ekran endi qoralama saqlamaydi');
    });
  });
}

/// Qoralamasi bor shakl — `DraftGuard` ning test namunasi.
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
            TextButton(
              key: const Key('draft-restore'),
              onPressed: () {
                final d = claimStashedDraft();
                if (d != null) restoreDraft(d);
                setState(() => _offered = false);
              },
              child: const Text('Oldingi kiritmani tiklash'),
            ),
          TextField(key: const Key('f-reason'), controller: _reason),
        ]),
      );
}
