import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/ui/ui.dart';

import 'support/support.dart';

void main() {
  setUp(() async => resetCore());

  group('AsyncView', () {
    testWidgets('skeleton -> data', (tester) async {
      final c = Completer<List<String>>();
      await pumpAt390(tester, Scaffold(
        body: AsyncView<List<String>>(
          load: () => c.future,
          builder: (_, d) => ListView(children: [for (final s in d) Text(s)]),
        ),
      ));
      expect(find.byType(SkeletonList), findsOneWidget);
      c.complete(['Sut', 'Non']);
      await tester.pumpAndSettle();
      expect(find.text('Sut'), findsOneWidget);
      expect(find.byType(SkeletonList), findsNothing);
    });

    testWidgets('error -> localized message + 48dp retry -> data', (tester) async {
      L.code = 'ru';
      var n = 0;
      await pumpAt390(tester, Scaffold(
        body: AsyncView<String>(
          load: () async {
            n++;
            if (n == 1) throw ApiException(0, 'x', kind: ApiErrorKind.network);
            return 'OK-DATA';
          },
          builder: (_, d) => Text(d),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('Нет связи с сервером'), findsOneWidget);
      final retry = find.widgetWithText(OutlinedButton, 'Повторить');
      expect(retry, findsOneWidget);
      expectMinTouchTarget(tester, retry);
      await tester.tap(retry);
      await tester.pumpAndSettle();
      expect(find.text('OK-DATA'), findsOneWidget);
    });

    testWidgets('empty state and reloadOn keeps old data while reloading', (tester) async {
      final trigger = ValueNotifier(0);
      var result = <int>[];
      final gate = <Completer<List<int>>>[];
      await pumpAt390(tester, Scaffold(
        body: AsyncView<List<int>>(
          load: () {
            final c = Completer<List<int>>();
            gate.add(c);
            return c.future;
          },
          reloadOn: trigger,
          emptyText: 'Bo‘sh',
          builder: (_, d) => Text('n=${d.length}'),
        ),
      ));
      gate.last.complete(result);
      await tester.pumpAndSettle();
      expect(find.text('Bo‘sh'), findsOneWidget);
      result = [1, 2];
      trigger.value++;
      await tester.pump();
      expect(find.text('Bo‘sh'), findsOneWidget, reason: 'old data stays during reload');
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      gate.last.complete(result);
      await tester.pumpAndSettle();
      expect(find.text('n=2'), findsOneWidget);
    });

    testWidgets('a stale response never overwrites a newer one', (tester) async {
      final ctl = AsyncViewController();
      final gate = <Completer<String>>[];
      await pumpAt390(tester, Scaffold(
        body: AsyncView<String>(
          controller: ctl,
          load: () {
            final c = Completer<String>();
            gate.add(c);
            return c.future;
          },
          builder: (_, d) => Text(d),
        ),
      ));
      unawaited(ctl.reload());
      await tester.pump();
      gate[1].complete('new');
      await tester.pump();
      gate[0].complete('old');
      await tester.pumpAndSettle();
      expect(find.text('new'), findsOneWidget);
      expect(find.text('old'), findsNothing);
    });
  });

  group('StickyActionBar', () {
    testWidgets('disabled shows the reason; enabled calls; 48dp+', (tester) async {
      var taps = 0;
      Widget bar({bool enabled = true, bool busy = false}) => Scaffold(
            body: const SizedBox.expand(),
            bottomNavigationBar: StickyActionBar(
              label: 'Saqlash',
              enabled: enabled,
              busy: busy,
              disabledReason: 'Pul manbaini tanlang',
              onPressed: () => taps++,
            ),
          );
      await pumpAt390(tester, bar(enabled: false));
      expect(find.byKey(const Key('sticky-reason')), findsOneWidget);
      await tester.tap(find.byKey(const Key('sticky-primary')));
      expect(taps, 0);
      await tester.pumpWidget(testApp(bar()));
      expect(find.byKey(const Key('sticky-reason')), findsNothing);
      expectMinTouchTarget(tester, find.byKey(const Key('sticky-primary')));
      await tester.tap(find.byKey(const Key('sticky-primary')));
      expect(taps, 1);
      await tester.pumpWidget(testApp(bar(busy: true)));
      await tester.tap(find.byKey(const Key('sticky-primary')));
      expect(taps, 1, reason: 'busy blocks double submit');
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });
  });

  group('showAppSheet', () {
    testWidgets('returns the popped value; close button is 48dp', (tester) async {
      String? got;
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
        got = await showAppSheet<String>(ctx,
            title: 'Tanlang',
            builder: (s) => ElevatedButton(onPressed: () => Navigator.pop(s, 'A'), child: const Text('A')));
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(find.text('Tanlang'), findsOneWidget);
      expectMinTouchTarget(tester, find.byTooltip('Yopish'));
      await tester.tap(find.text('A'));
      await tester.pumpAndSettle();
      expect(got, 'A');
    });
  });

  group('QtyField / MoneyField', () {
    testWidgets('qty: comma, 3 decimals max, numeric keyboard', (tester) async {
      final c = TextEditingController();
      NumParse? last;
      await pumpAt390(tester, Scaffold(body: QtyField(controller: c, unit: 'kg', onChanged: (p) => last = p)));
      await tester.enterText(find.byType(TextField), '1,25');
      expect(last!.value, 1250);
      await tester.enterText(find.byType(TextField), '1,2345');
      expect(c.text, '1,25', reason: 'a 4th decimal is refused, not rounded');
      await tester.enterText(find.byType(TextField), 'abc');
      expect(c.text, '1,25');
      final tf = tester.widget<TextField>(find.byType(TextField));
      expect(tf.keyboardType, const TextInputType.numberWithOptions(decimal: true));
      expect(find.text('kg'), findsOneWidget);
      expect(tester.getSize(find.byType(TextField)).height, greaterThanOrEqualTo(48));
    });

    testWidgets('money: groups thousands, whole som by default', (tester) async {
      final c = TextEditingController();
      NumParse? last;
      await pumpAt390(tester, Scaffold(body: MoneyField(controller: c, onChanged: (p) => last = p)));
      await tester.enterText(find.byType(TextField), '1234567');
      expect(c.text, '1 234 567');
      expect(last!.value, 123456700);
      await tester.enterText(find.byType(TextField), '1234567,5');
      expect(c.text, '1 234 567', reason: 'whole som only');
    });

    testWidgets('money with cents', (tester) async {
      final c = TextEditingController();
      await pumpAt390(tester, Scaffold(body: MoneyField(controller: c, wholeOnly: false)));
      await tester.enterText(find.byType(TextField), '12500,5');
      expect(c.text, '12 500,5');
      expect(parseMoney(c.text).value, 1250050);
    });
  });

  group('DateField', () {
    testWidgets('days before the min date are disabled; a valid day is returned', (tester) async {
      String? value;
      await pumpAt390(tester, StatefulBuilder(
        builder: (ctx, set) => Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: DateField(
              value: value,
              minDate: '2026-09-19',
              label: 'Muddat',
              onChanged: (v) => set(() => value = v),
            ),
          ),
        ),
      ));
      await tester.tap(find.byType(DateField));
      await tester.pumpAndSettle();
      expect(find.text('Sentabr 2026'), findsOneWidget);
      await tester.tap(find.byKey(const Key('date-day-2026-09-18')));
      await tester.pumpAndSettle();
      expect(value, isNull, reason: 'before the business date');
      final day = find.byKey(const Key('date-day-2026-09-25'));
      expect(tester.getSize(day).width, greaterThanOrEqualTo(48));
      await tester.tap(day);
      await tester.pumpAndSettle();
      expect(value, '2026-09-25');
      expect(find.text('25.09.2026'), findsOneWidget);
    });

    testWidgets('typed entry with automatic dots; past date refused', (tester) async {
      String? got;
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
        got = await showAppDatePicker(ctx, minDate: '2026-09-19');
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('date-typed')), '01092026');
      expect(find.text('01.09.2026'), findsOneWidget);
      await tester.tap(find.byKey(const Key('date-typed-ok')));
      await tester.pumpAndSettle();
      expect(find.textContaining('dan oldin bo‘lmasin'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('date-typed')), '31122027');
      await tester.tap(find.byKey(const Key('date-typed-ok')));
      await tester.pumpAndSettle();
      expect(got, '2027-12-31');
    });

    testWidgets('month navigation', (tester) async {
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) => showAppDatePicker(ctx, initial: '2026-12-10')));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(find.text('Dekabr 2026'), findsOneWidget);
      await tester.tap(find.byTooltip('Keyingi oy'));
      await tester.pumpAndSettle();
      expect(find.text('Yanvar 2027'), findsOneWidget);
      await tester.tap(find.byTooltip('Oldingi yil'));
      await tester.pumpAndSettle();
      expect(find.text('Yanvar 2026'), findsOneWidget);
    });
  });

  group('confirmDestructive', () {
    testWidgets('typed phrase + acknowledge gate the red button', (tester) async {
      bool? ok;
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
        ok = await confirmDestructive(ctx,
            title: 'Hisobdan chiqarish',
            message: '3 kg Sut hisobdan chiqariladi',
            details: const ['Partiya A: 2 kg', 'Partiya B: 1 kg'],
            requireAcknowledge: true,
            typedPhrase: 'CHIQAR');
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      final yes = find.byKey(const Key('confirm-yes'));
      expect(tester.widget<ElevatedButton>(yes).onPressed, isNull);
      await tester.tap(find.byKey(const Key('confirm-ack')));
      await tester.pump();
      expect(tester.widget<ElevatedButton>(yes).onPressed, isNull);
      await tester.enterText(find.byKey(const Key('confirm-typed')), 'chiqar');
      await tester.pump();
      expect(tester.widget<ElevatedButton>(yes).onPressed, isNotNull);
      await tester.tap(yes);
      await tester.pumpAndSettle();
      expect(ok, isTrue);
    });

    testWidgets('cancel / dismiss is false', (tester) async {
      bool? ok;
      await pumpAt390(tester, LaunchHost(onPressed: (ctx) async {
        ok = await confirmDestructive(ctx, title: 'T', message: 'M');
      }));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-no')));
      await tester.pumpAndSettle();
      expect(ok, isFalse);
    });
  });

  group('banners', () {
    testWidgets('ErrorBanner renders userMessage and a 48dp retry', (tester) async {
      L.code = 'ky';
      var retried = 0;
      await pumpAt390(tester, Scaffold(
        body: ErrorBanner(error: ApiException(409, 'x', code: 'LOT_INVARIANT_BROKEN'), onRetry: () => retried++),
      ));
      expect(find.textContaining('Партиялар жана калдык дал келген жок'), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('banner-retry')));
      await tester.tap(find.byKey(const Key('banner-retry')));
      expect(retried, 1);
    });

    testWidgets('ConnectivityBanner follows Api.online and retries with ping', (tester) async {
      final be = FakeBackend()..get('/health', (_) => {'ok': true});
      await pumpAt390(tester, const Scaffold(body: Column(children: [ConnectivityBanner(), Spacer()])));
      expect(find.byKey(const Key('offline-text')), findsNothing);
      Api.online.value = false;
      await tester.pump();
      expect(find.byKey(const Key('offline-text')), findsOneWidget);
      expectMinTouchTarget(tester, find.byKey(const Key('offline-retry')));
      await be.run(() async {
        await tester.tap(find.byKey(const Key('offline-retry')));
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/health'), hasLength(1));
      expect(find.byKey(const Key('offline-text')), findsNothing);
    });
  });
}
