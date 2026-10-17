// CH-18D/A — yopish oynasidagi SAYLOV (ega o'z ma'lumotini ham o'chirishi).
//
// ⚠️  NEGA WIDGET TESTI KERAK. Saylov — yopilgandan keyin TAKRORLANMAYDIGAN
//     qaror: `Company.deleted_at` o'rnatilgach autentifikatsiya 401 beradi
//     (ega uchun ham), ya'ni «keyin qaytib o'chiraman» mumkin emas. Shu bois
//     oynaning ikki xususiyati MAJBURIY:
//       1. saylov STANDART BELGILANMAGAN — jim qaytarilmas amal bo'lmasin;
//       2. belgilansa, natijada AYNAN shu uzatiladi — aks holda ega so'ragan
//          narsa yo'lda yo'qolardi.
//     Serverdagi mos tomoni `tests/test_ch18d_yagona_ega_chiqishi.py` da.
@TestOn('vm')
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/ui/confirm_erase.dart';

import 'support/support.dart';

/// Oynani ochadi va uning natija Future'sini QAYTARADI (hali tugamagan).
///
/// ⚠️  `confirmErase` ni `await` qilmaymiz — oyna hali ochiq. Lekin
///     `pumpAt390` ni `await` qilish SHART: `flutter_test` ikki guarded
///     chaqiruvning ustma-ust tushishini «Guarded function conflict» bilan
///     rad etadi. Shu bois Future tashqi o'zgaruvchiga YOZILADI, pump esa
///     to'liq kutiladi.
Future<Future<EraseConfirmation?>> _ochamiz(WidgetTester tester,
    {EraseOptIn? optIn}) async {
  Future<EraseConfirmation?>? kutilayotgan;
  await pumpAt390(tester, Scaffold(
    body: Builder(
      builder: (ctx) => TextButton(
        onPressed: () => kutilayotgan = confirmErase(ctx,
            title: 'Do‘konni yopish',
            message: 'Do‘kon yopiladi.',
            phrase: kEraseConfirmWord,
            optIn: optIn),
        child: const Text('ochish'),
      ),
    ),
  ));
  await tester.tap(find.text('ochish'));
  await tester.pumpAndSettle();
  expect(kutilayotgan, isNotNull, reason: 'oyna ochilmadi');
  return kutilayotgan!;
}

/// Saylovni BELGILAYDI va chindan belgilanganini qadaydi.
///
/// ⚠️  Tilega emas, `Checkbox` ning O'ZIGA tegamiz: `CheckboxListTile`
///     subtitle bilan baland bo'lib, oyna ichidagi scroll'da teginish
///     nuqtasi kutilmagan joyga tushishi mumkin. Belgilanganini ALOHIDA
///     qadamaslik «tapdim, demak ishladi» degan soxta xulosaga olib borardi.
Future<void> _belgilaymiz(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('erase-optin')));
  await tester.pumpAndSettle();
  await tester.tap(find.descendant(
      of: find.byKey(const Key('erase-optin')), matching: find.byType(Checkbox)));
  await tester.pumpAndSettle();
  final cb = tester.widget<CheckboxListTile>(find.byKey(const Key('erase-optin')));
  expect(cb.value, isTrue, reason: 'checkbox belgilanmadi');
}

Future<void> _toldiramiz(WidgetTester tester) async {
  await tester.enterText(find.byKey(const Key('erase-password')), 'parol-123');
  await tester.enterText(
      find.byKey(const Key('erase-phrase')), kEraseConfirmWord);
  await tester.pumpAndSettle();
}

const _saylov = EraseOptIn(
    label: 'Mening ma’lumotlarim', note: 'oxirgi imkoniyat');

void main() {
  group('confirmErase saylovi', () {
    testWidgets('saylov berilmasa checkbox UMUMAN ko‘rinmaydi', (tester) async {
      await _ochamiz(tester);

      expect(find.byKey(const Key('erase-optin')), findsNothing);
    });

    testWidgets('saylov berilsa checkbox ko‘rinadi va BELGILANMAGAN',
        (tester) async {
      await _ochamiz(tester, optIn: _saylov);

      final cb = tester.widget<CheckboxListTile>(
          find.byKey(const Key('erase-optin')));
      expect(cb.value, isFalse);
    });

    testWidgets('saylov STANDART belgilanmagan -> optedIn false', (tester) async {
      final f = await _ochamiz(tester, optIn: _saylov);
      // Teginmasdan tasdiqlaymiz
      await _toldiramiz(tester);
      await tester.tap(find.byKey(const Key('erase-submit')));
      await tester.pumpAndSettle();

      final r = await f;
      expect(r, isNotNull);
      expect(r!.optedIn, isFalse, reason: 'jim qaytarilmas amal bo‘lmasin');
      expect(r.phrase, kEraseConfirmWord);
    });

    testWidgets('belgilansa optedIn true bo‘lib qaytadi', (tester) async {
      final f = await _ochamiz(tester, optIn: _saylov);
      await _belgilaymiz(tester);
      await _toldiramiz(tester);
      await tester.tap(find.byKey(const Key('erase-submit')));
      await tester.pumpAndSettle();

      final r = await f;
      expect(r!.optedIn, isTrue);
    });

    testWidgets('saylov tugmani OCHMAYDI — parol va so‘z hamon shart',
        (tester) async {
      await _ochamiz(tester, optIn: _saylov);
      await _belgilaymiz(tester);

      final btn = tester.widget<FilledButton>(find.byKey(const Key('erase-submit')));
      expect(btn.onPressed, isNull, reason: 'saylov o‘zi tasdiq o‘rnini bosmaydi');
    });

    testWidgets('bekor qilinsa natija null — saylov ham ketmaydi', (tester) async {
      final f = await _ochamiz(tester, optIn: _saylov);
      await _belgilaymiz(tester);
      await _toldiramiz(tester);
      await tester.tap(find.text('Bekor'));
      await tester.pumpAndSettle();

      expect(await f, isNull);
    });

    testWidgets('eslatma matni oynada KO‘RINADI', (tester) async {
      await _ochamiz(tester,
          optIn: const EraseOptIn(
              label: 'Mening shaxsiy ma’lumotlarimni ham o‘chirish',
              note: 'Yopilgandan keyin tizimga kira olmaysiz.'));

      expect(find.text('Mening shaxsiy ma’lumotlarimni ham o‘chirish'), findsOneWidget);
      expect(find.text('Yopilgandan keyin tizimga kira olmaysiz.'), findsOneWidget);
    });
  });

  // ── CH-24 — iOS APOSTROF P0 ───────────────────────────────────────────────
  //
  // ⚠️  NIMA SINDI. Server `O'CHIRISH` ni ASCII apostrof (U+0027) bilan
  //     kutadi, iPhone klaviaturasi esa «smart punctuation» bilan uni U+2019
  //     (’) ga aylantiradi. Qat'iy taqqoslash (`==`) shu bois yiqilardi:
  //     operator TO'G'RI so'zni yozsa ham tasdiq tugmasi FAOLLASHMASDI, ya'ni
  //     Apple 5.1.1(v) o'chirish oqimi qurilmada BAJARILMAS edi. Tuzatish
  //     MIJOZDA: taqqoslash normalizatsiyalanadi, API'ga esa SERVER bergan
  //     asl token yuboriladi. Server kontrakti TEGILMAGAN.
  group('CH-24 apostrof', () {
    test('erasePhraseMatches apostrof ko‘rinishini E‘TIBORGA OLMAYDI', () {
      expect(erasePhraseMatches("O'CHIRISH", kEraseConfirmWord), isTrue);
      expect(erasePhraseMatches('O\u2019CHIRISH', kEraseConfirmWord), isTrue);
      expect(erasePhraseMatches('O\u02BBCHIRISH', kEraseConfirmWord), isTrue);
      expect(erasePhraseMatches('O\u02BCCHIRISH', kEraseConfirmWord), isTrue);
      expect(erasePhraseMatches('  O\u2019CHIRISH  ', kEraseConfirmWord), isTrue);
      //  ⚠️  DARVOZA YUMSHAMADI: boshqa so‘z hamon RAD etiladi.
      expect(erasePhraseMatches('OCHIRISH', kEraseConfirmWord), isFalse);
      expect(erasePhraseMatches('o\u2019chirish', kEraseConfirmWord), isFalse);
      expect(erasePhraseMatches('', kEraseConfirmWord), isFalse);
    });

    testWidgets('tasdiq maydonida smart quotes O‘CHIRILGAN', (tester) async {
      await _ochamiz(tester);

      final tf = tester.widget<TextField>(find.byKey(const Key('erase-phrase')));
      expect(tf.smartQuotesType, SmartQuotesType.disabled);
    });

    testWidgets('SMART apostrof bilan yozilsa tugma FAOLLASHADI', (tester) async {
      final f = await _ochamiz(tester);
      await tester.enterText(find.byKey(const Key('erase-password')), 'parol-123');
      await tester.enterText(
          find.byKey(const Key('erase-phrase')), 'O\u2019CHIRISH');
      await tester.pumpAndSettle();

      final btn = tester.widget<FilledButton>(find.byKey(const Key('erase-submit')));
      expect(btn.onPressed, isNotNull, reason: 'smart apostrof bilan tugma o‘chiq');

      await tester.tap(find.byKey(const Key('erase-submit')));
      await tester.pumpAndSettle();
      final r = await f;
      //  API'ga SERVER kutgan ASCII token ketadi, yozilgani EMAS.
      expect(r!.phrase, kEraseConfirmWord);
      expect(r.phrase.contains('\u2019'), isFalse);
    });

    testWidgets('ASCII apostrof bilan ham AVVALGIDEK ishlaydi', (tester) async {
      final f = await _ochamiz(tester);
      await _toldiramiz(tester);
      await tester.tap(find.byKey(const Key('erase-submit')));
      await tester.pumpAndSettle();

      expect((await f)!.phrase, kEraseConfirmWord);
    });

    testWidgets('NOTO‘G‘RI so‘zda tugma O‘CHIQ qoladi', (tester) async {
      await _ochamiz(tester);
      await tester.enterText(find.byKey(const Key('erase-password')), 'parol-123');
      await tester.enterText(find.byKey(const Key('erase-phrase')), 'OCHIRISH');
      await tester.pumpAndSettle();

      final btn = tester.widget<FilledButton>(find.byKey(const Key('erase-submit')));
      expect(btn.onPressed, isNull);
    });
  });
}
