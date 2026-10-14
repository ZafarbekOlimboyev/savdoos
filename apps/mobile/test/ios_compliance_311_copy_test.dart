// CH-02 / CH-03 — iOS tariff copy (App Store Review Guideline 3.1.1 / 3.1.3 risk).
//
// The owner chose option A: the native iOS app has no Tarif entry and states a
// plan limit as a plain fact; Android and the web build keep their tariff screen
// and wording unchanged. This file pins both sides:
//   * iOS: no Tarif row, no plan or subscription wording on Settings, no call to
//     buy, raise or change a plan; the employee-limit message keeps its number;
//   * Android (control): the Tarif row, the tariff screen and the old limit
//     message are exactly as before;
//   * web: covered by the AppPlatform truth table — `kIsWeb` is a compile-time
//     constant, so a VM test cannot render the web build.
// It is a regression net, not a final Apple verdict ("LEGAL/APPLE REVIEW
// REQUIRED" still stands). uz, ru and ky are checked; uzc is transliterated from
// uz at runtime and is not checked here.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/platform/platform.dart' show AppPlatform;
import 'package:savdoos_mobile/screens/employee_edit_screen.dart' show employeeErrorMessage;
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/tariff_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/store_policy.dart';

import 'support/support.dart';

const _langs = ['uz', 'ru', 'ky'];
final _ios = TargetPlatformVariant.only(TargetPlatform.iOS);
final _android = TargetPlatformVariant.only(TargetPlatform.android);

const _roles = [
  ('ega', <String>[]),
  ('kassir', ['kassa.sell', 'kassa.view', 'sotuvlar.view', 'qaytarishlar.create', 'mijozlar.view']),
];

/// The employee-limit sentences: Android/web keep the first, iOS shows the second.
const _limitWithUpsell = 'Tarif bo‘yicha xodimlar chegarasi: {n} ta. Ko‘proq xodim uchun tarifni oshiring.';
const _limitFact = 'Tarif bo‘yicha xodimlar chegarasi: {n} ta. Yangi xodim qo‘shib bo‘lmaydi.';

/// One "word" in any script: Dart's `\w` is ASCII-only and would stop at Cyrillic.
const _w = r'[^\s.,:;!?«»"]*';

/// Calls to buy / raise / change a plan. Applied to every string in every
/// language, whatever the UI language is, so an untranslated CTA is caught too.
final _ctaPatterns = <String, RegExp>{
  'uz: raise/change plan': RegExp("tarif$_w\\s+(oshir|o'zgartir|kengaytir|yangila|almashtir|tanla)"),
  'uz: higher plan': RegExp(r'(yuqori|katta)\s+tarif'),
  'uz: renew/buy subscription': RegExp("obuna$_w\\s+(yangila|uzaytir|sotib)"),
  'ru: change/raise plan': RegExp("(смен|повыс|перейд|обнов|измен|выбер|куп)$_w[^.!?]{0,40}тариф"
      "|тариф$_w[^.!?]{0,40}(смен|повыс|перейд|обнов|измен|выбер|куп)"),
  'ru: renew/buy subscription': RegExp("(обнов|продл|куп|оформ)$_w[^.!?]{0,40}подписк"
      "|подписк$_w[^.!?]{0,40}(обнов|продл|куп|оформ)"),
  'ky: raise/change plan': RegExp("тариф$_w\\s+(жогорула|өзгөрт|жаңыла|алмаштыр|танда)"),
  'ky: renew/buy subscription': RegExp("жазылуу$_w\\s+(жаңыла|сатып)"),
  'buy': RegExp(r'sotib\s+ol|купит|приобрест|сатып\s+ал'),
};

/// "Contact BinOS" in the same sentence — the shipped way of selling a plan change.
final _vendor = RegExp('binos');
final _contactVerb = RegExp(r"bog'lan|murojaat|свяж|обратит|байланыш");

/// Any mention of a plan or subscription.
final _tariffWord = RegExp(r'\btarif|тариф|\bobuna|подписк|жазылуу', caseSensitive: false);

/// Lower-cases and folds the Uzbek apostrophe variants (‘ ’ ʻ ʼ `) to `'`.
String _norm(String s) => s.toLowerCase().replaceAll(RegExp('[‘’ʻʼ`]'), '\'');

List<String> _ctaHits(Iterable<String> texts) => [
      for (final t in texts) ...[
        for (final p in _ctaPatterns.entries)
          if (p.value.hasMatch(_norm(t))) '"$t" ~ ${p.key}',
        if (_vendor.hasMatch(_norm(t)) && _contactVerb.hasMatch(_norm(t))) '"$t" ~ contact BinOS',
      ],
    ];

/// Every distinct string currently rendered. RichText is read too so text built
/// without a [Text] widget cannot slip past; a [Text] also builds a RichText, so
/// the result is de-duplicated.
List<String> _renderedTexts(WidgetTester tester) => {
      for (final w in tester.widgetList<Text>(find.byType(Text))) w.data ?? w.textSpan?.toPlainText() ?? '',
      for (final w in tester.widgetList<RichText>(find.byType(RichText))) w.text.toPlainText(),
    }.toList();

/// The tarif_limit error the server sends when the employee cap is reached.
ApiException _tarifLimit(Object? maxUsers) => ApiException(403, 'tarif_limit',
    detail: {'error': 'tarif_limit', 'plan': 'start', if (maxUsers != null) 'max_users': maxUsers});

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()..get('/settings', (_) => {'plan': {'plan': 'start'}});
  });

  tearDown(() => s.debugReset());

  Future<void> signInAs(String role, List<String> perms) async {
    signIn(role: role, permissions: perms);
    be.get('/auth/context', (_) => contextJson(role: role, permissions: perms));
    await s.load(force: true);
    expect(s.status, SessionStatus.ready, reason: 'session must load before Settings is judged');
    expect(s.roleCode, role, reason: 'the case must really run as $role');
  }

  /// Renders Settings scrolled to the card that holds the Tarif row, proving
  /// Settings actually rendered (so an absent row is a real absence).
  Future<void> pumpSettings(WidgetTester tester) async {
    await pumpAt390(tester, const SettingsScreen());
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('settings-language')), 300,
        scrollable: find.descendant(of: find.byType(SettingsScreen), matching: find.byType(Scrollable)).first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('settings-server')), findsOneWidget, reason: 'the general card rendered');
  }

  // Self-check of the oracle: the iOS cases are only meaningful if the detector
  // catches realistic rewordings and leaves neutral wording alone.
  group('call-to-action detector (self-check)', () {
    test('flags shipped and reworded calls to buy or change a plan', () {
      const upsell = [
        'Ko‘proq xodim uchun tarifni oshiring.',
        'Tarifni o‘zgartirish uchun BinOS bilan bog‘laning',
        'Tarifingizni oshiring',
        'Yuqori tarifga o‘ting',
        'Tarifni kengaytiring',
        'binos.uz saytida tarif tanlang',
        'Ko‘proq xodim uchun BinOS bilan bog‘laning',
        'Чтобы добавить больше, повысьте тариф.',
        'Для смены тарифа свяжитесь с BinOS',
        'Свяжитесь с BinOS, чтобы сменить тариф',
        'Перейдите на тариф Business',
        'Обновите тариф',
        'Көбүрөөк кызматкер үчүн тарифти жогорулатыңыз.',
        'Тарифти өзгөртүү үчүн BinOS менен байланышыңыз',
        'Тарифиңизди жогорулатыңыз',
        'BinOS менен байланышыңыз',
      ];
      for (final t in upsell) {
        expect(_ctaHits([t]), isNotEmpty, reason: 'missed: "$t"');
      }
    });

    test('leaves neutral limit and plan wording alone', () {
      const neutral = [
        'Tarif bo‘yicha xodimlar chegarasi: 10 ta.',
        'Tarif bo‘yicha xodimlar chegarasi: 10 ta. Yangi xodim qo‘shib bo‘lmaydi.',
        'Joriy tarif: Start',
        'Batafsil ma’lumot uchun administratoringizga murojaat qiling.',
        'Biznes sanasi',
        'BinOS mobil · v1.0.0',
        'Лимит сотрудников по тарифу: 10. Добавить нового сотрудника нельзя.',
        'Текущий тариф: Start',
        'Обновить данные',
        'Тариф боюнча кызматкерлердин чеги: 10. Жаңы кызматкер кошууга болбойт.',
        'Учурдагы тариф: Start',
        'Тариф',
      ];
      for (final t in neutral) {
        expect(_ctaHits([t]), isEmpty, reason: 'false positive: "$t"');
      }
    });
  });

  group('platform detection', () {
    test('only the native iOS build counts as iOS — never the web build on an iPhone', () {
      expect(AppPlatform.isNativeIosFor(isWeb: false, platform: TargetPlatform.iOS), isTrue);
      expect(AppPlatform.isNativeIosFor(isWeb: true, platform: TargetPlatform.iOS), isFalse, reason: 'PWA in Safari');
      expect(AppPlatform.isNativeIosFor(isWeb: false, platform: TargetPlatform.android), isFalse);
      expect(AppPlatform.isNativeIosFor(isWeb: true, platform: TargetPlatform.android), isFalse);
      expect(AppPlatform.isNativeIosFor(isWeb: false, platform: TargetPlatform.macOS), isFalse);
    });

    testWidgets('StorePolicy hides the upsell on iOS', (tester) async {
      expect(AppPlatform.isNativeIos, isTrue);
      expect(StorePolicy.showsPlanUpsell, isFalse);
    }, variant: _ios);

    testWidgets('StorePolicy keeps the upsell on Android', (tester) async {
      expect(AppPlatform.isNativeIos, isFalse);
      expect(StorePolicy.showsPlanUpsell, isTrue);
    }, variant: _android);
  });

  group('iOS: employee-limit message is a fact, not a call to upgrade', () {
    for (final lang in _langs) {
      testWidgets('[$lang] shows the neutral limit sentence with its number', (tester) async {
        L.code = lang;
        final msg = employeeErrorMessage(_tarifLimit(10));
        expect(msg, trArgs(_limitFact, {'n': 10}));
        expect(RegExp(r'\b10\b').hasMatch(msg), isTrue, reason: 'the limit is information and stays: "$msg"');
        if (lang != 'uz') expect(msg.contains('xodim'), isFalse, reason: '[$lang] must be translated: "$msg"');
      }, variant: _ios);

      testWidgets('[$lang] carries no call to raise or change the plan', (tester) async {
        L.code = lang;
        expect(_ctaHits([employeeErrorMessage(_tarifLimit(10))]), isEmpty,
            reason: 'tariff-limit text must not tell the user to upgrade');
      }, variant: _ios);
    }

    testWidgets('{n} survives translation: every language shows the number exactly once', (tester) async {
      for (final lang in _langs) {
        L.code = lang;
        final msg = employeeErrorMessage(_tarifLimit(7));
        expect(RegExp(r'\b7\b').allMatches(msg).length, 1, reason: '[$lang] "$msg"');
      }
    }, variant: _ios);

    testWidgets('a missing max_users still fills the number slot', (tester) async {
      for (final lang in _langs) {
        L.code = lang;
        final msg = employeeErrorMessage(_tarifLimit(null));
        expect(msg, isNot(contains('{n}')), reason: '[$lang] "$msg"');
        expect(RegExp(r':\s*(ta\b|\.)').hasMatch(msg), isFalse, reason: '[$lang] empty limit slot: "$msg"');
      }
    }, variant: _ios);
  });

  group('iOS: Settings has no tariff entry', () {
    for (final role in _roles) {
      for (final lang in _langs) {
        testWidgets('[${role.$1}/$lang] no Tarif row, no plan wording, no call to action', (tester) async {
          late List<String> texts;
          await be.run(() async {
            L.code = lang;
            await signInAs(role.$1, role.$2);
            await pumpSettings(tester);
            texts = _renderedTexts(tester);
          });
          expect(find.byKey(const Key('settings-tariff')), findsNothing);
          expect(find.byIcon(Icons.workspace_premium_outlined), findsNothing);
          expect(find.text(tr('Tarif')), findsNothing);
          expect([for (final t in texts) if (_tariffWord.hasMatch(_norm(t))) t], isEmpty,
              reason: 'Settings must not mention a plan on iOS');
          expect(_ctaHits(texts), isEmpty, reason: 'a ${role.$1} must not be told to buy or change a plan');
        }, variant: _ios);
      }
    }
  });

  group('Android control: tariff UI and wording unchanged', () {
    for (final role in _roles) {
      for (final lang in _langs) {
        testWidgets('[${role.$1}/$lang] the Tarif row still opens the tariff screen', (tester) async {
          await be.run(() async {
            L.code = lang;
            await signInAs(role.$1, role.$2);
            await pumpSettings(tester);
            final row = find.byKey(const Key('settings-tariff'));
            expect(row, findsOneWidget);
            expect(find.descendant(of: row, matching: find.text(tr('Tarif'))), findsOneWidget);
            await tester.ensureVisible(row);
            await tester.tap(row);
            await tester.pumpAndSettle();
          });
          expect(find.byType(TariffScreen), findsOneWidget);
          expect(find.text(tr('Tarifni o‘zgartirish uchun BinOS bilan bog‘laning')), findsOneWidget);
          for (final plan in ['Start', 'Start+', 'Business']) {
            expect(find.text(plan), findsOneWidget, reason: 'all plans still listed on Android');
          }
        }, variant: _android);
      }
    }

    for (final lang in _langs) {
      testWidgets('[$lang] the employee-limit message is the original sentence', (tester) async {
        L.code = lang;
        expect(employeeErrorMessage(_tarifLimit(10)), trArgs(_limitWithUpsell, {'n': 10}));
      }, variant: _android);
    }
  });
}
