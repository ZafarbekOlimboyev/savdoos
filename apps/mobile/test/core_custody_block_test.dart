import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

import 'support/support.dart';

Map<String, dynamic> block(String mode,
        {String? reason, Map<String, dynamic>? resolved, List<Map<String, dynamic>> options = const []}) =>
    {
      'mode': mode,
      'reason': reason,
      'resolved': resolved,
      'options': options,
      'branch': {'id': 'b1', 'name': 'Markaz'},
    };

const till = {'id': 't1', 'type': 'TILL', 'code': 'K-01', 'currency': 'UZS'};
const safe = {'id': 's1', 'type': 'SAFE', 'code': 'S-01', 'currency': 'UZS'};

void main() {
  setUp(() async => resetCore());

  group('CustodyInfo', () {
    test('parsing and what to send per mode', () {
      final na = CustodyInfo.fromJson(block('NOT_APPLICABLE'));
      expect(na.mode, CustodyMode.notApplicable);
      expect(na.isReady(null), isTrue);
      expect(na.accountToSend('t1'), isNull);

      final nr = CustodyInfo.fromJson(block('NOT_REQUIRED'));
      expect(nr.isReady(null), isTrue);
      expect(nr.accountToSend('t1'), isNull, reason: 'the server resolves the drawer');

      final sr = CustodyInfo.fromJson(block('SERVER_RESOLVED', resolved: till));
      expect(sr.resolved!.code, 'K-01');
      expect(sr.accountToSend('t1'), isNull, reason: 'client sends NOTHING for a resolved till');

      final ch = CustodyInfo.fromJson(block('OPERATOR_MUST_CHOOSE',
          reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [till, safe]));
      expect(ch.needsChoice, isTrue);
      expect(ch.isReady(null), isFalse);
      expect(ch.isReady('zzz'), isFalse, reason: 'only an EXACT offered option counts');
      expect(ch.accountToSend('s1'), 's1');
      expect(ch.accountToSend('zzz'), isNull);
      expect(ch.branchName, 'Markaz');

      final bl = CustodyInfo.fromJson(block('BLOCKED', reason: 'CASH_LEDGER_UNAVAILABLE'));
      expect(bl.blocksSubmit, isTrue);
      expect(bl.isReady('t1'), isFalse);
    });

    test('unknown / missing mode fails closed', () {
      final u = CustodyInfo.fromJson(const {'mode': 'SOMETHING_NEW'});
      expect(u.mode, CustodyMode.blocked);
      expect(u.blocksSubmit, isTrue);
      expect(CustodyInfo.fromJson(null).blocksSubmit, isTrue);
    });

    test('must-choose with no options blocks submit with its own message', () {
      L.code = 'ru';
      final e = CustodyInfo.fromJson(block('OPERATOR_MUST_CHOOSE', options: const []));
      expect(e.blocksSubmit, isTrue);
      expect(e.blockedReason(), startsWith('В этом филиале нет активной кассы или сейфа'));
    });

    test('BLOCKED never tells the operator to pick a source that is not on screen', () {
      L.code = 'ru';
      // Collection from a shift the POS opened WITHOUT a till: the server could
      // not resolve the SOURCE, so it blocks — there is no radio list at all.
      final b = CustodyInfo.fromJson(block('BLOCKED', reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER'));
      expect(b.blocksSubmit, isTrue);
      expect(b.options, isEmpty);
      expect(b.blockedReason(), isNot(contains('выберите')),
          reason: 'BLOCKED renders no picker — "choose a source" is impossible to obey');
      expect(b.blockedReason(), contains('смен'), reason: 'names the real cause: the shift has no till');

      // Where the operator really does choose, the server text is kept.
      final ch = CustodyInfo.fromJson(block('OPERATOR_MUST_CHOOSE',
          reason: 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER', options: [till, safe]));
      expect(ch.blockedReason(), isEmpty);
    });

    test('fetchCustodyPreview sends the operation', () async {
      final be = FakeBackend()..get('/cash/custody-preview', (r) => block('NOT_REQUIRED'));
      signIn();
      final info = await be.run(() => fetchCustodyPreview(CustodyOperation.debtPayment));
      expect(info.mode, CustodyMode.notRequired);
      expect(be.last('GET', '/cash/custody-preview').query, {'operation': 'debt_payment'});
    });
  });

  group('CustodyBlock widget', () {
    Widget host(CustodyInfo info, {String? selected, ValueChanged<String?>? onChanged, bool showErrors = false}) =>
        Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: CustodyBlock(info: info, selectedId: selected, onChanged: onChanged ?? (_) {}, showErrors: showErrors),
          ),
        );

    testWidgets('NOT_REQUIRED / NOT_APPLICABLE render nothing', (tester) async {
      await pumpAt390(tester, host(CustodyInfo.fromJson(block('NOT_REQUIRED'))));
      expect(find.byType(InkWell), findsNothing);
      expect(find.textContaining('Pul manbai'), findsNothing);
    });

    testWidgets('SERVER_RESOLVED is read-only "Pul manbai: <code>"', (tester) async {
      await pumpAt390(tester, host(CustodyInfo.fromJson(block('SERVER_RESOLVED', resolved: till))));
      expect(find.text('Pul manbai: K-01 (Kassa)'), findsOneWidget);
      expect(find.byType(InkWell), findsNothing);
    });

    testWidgets('OPERATOR_MUST_CHOOSE: no default even with ONE option; tap selects', (tester) async {
      String? sel;
      final info = CustodyInfo.fromJson(block('OPERATOR_MUST_CHOOSE', options: [safe]));
      await pumpAt390(
        tester,
        StatefulBuilder(builder: (ctx, set) => host(info, selected: sel, showErrors: true, onChanged: (v) => set(() => sel = v))),
      );
      await tester.pump();
      expect(sel, isNull, reason: 'never preselected');
      expect(find.byKey(const Key('custody-required')), findsOneWidget);
      final opt = find.byKey(const Key('custody-option-s1'));
      expect(tester.getSize(opt).height, greaterThanOrEqualTo(48));
      await tester.tap(opt);
      await tester.pump();
      expect(sel, 's1');
      expect(find.byKey(const Key('custody-required')), findsNothing);
      expect(info.accountToSend(sel), 's1');
    });

    testWidgets('a stale selection (not among options) is cleared', (tester) async {
      String? sel = 'old-account';
      final info = CustodyInfo.fromJson(block('OPERATOR_MUST_CHOOSE', options: [till]));
      await pumpAt390(tester, host(info, selected: sel, onChanged: (v) => sel = v));
      await tester.pump();
      expect(sel, isNull);
    });

    testWidgets('BLOCKED shows the localized reason (ky)', (tester) async {
      L.code = 'ky';
      await pumpAt390(
          tester, host(CustodyInfo.fromJson(block('BLOCKED', reason: 'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER'))));
      expect(find.text('Бул амал ачык сменанын кассасына туура келбейт. Сменанын ортосунда касса алмаштырылбайт.'),
          findsOneWidget);
    });
  });
}
