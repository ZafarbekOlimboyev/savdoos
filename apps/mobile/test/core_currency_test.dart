// VALYUTA KONTRAKTI (mobil) — TIL matnni tarjima qiladi, DO'KON valyutasi pul
// birligini belgilaydi.
//
// Bu fayl web tomondagi `tests/currency-contract.test.ts` ning EGIZAGI: ikkisi
// bir xil jadvalni (KGS → kanonik "сом", UZS → tilga bog'liq eski yozuv,
// noma'lum kod → kodning o'zi, kod yo'q → eski yorliq) sinaydi. Biri o'zgarsa
// ikkinchisi ham o'zgarishi kerak.
@TestOn('vm')
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/api/money_api.dart';
import 'package:savdoos_mobile/currency.dart';
import 'package:savdoos_mobile/format.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/qty.dart';
import 'package:savdoos_mobile/screens/receipt_screen.dart';
import 'package:savdoos_mobile/session.dart';
import 'package:savdoos_mobile/ui/ui.dart';
import 'package:savdoos_mobile/widgets/custody_block.dart';

import 'money_fixtures_test.dart';
import 'support/support.dart';

/// Mobil tillari: `uz | ru | ky`, `uzc` — lotin matnning transliteratsiyasi.
const _langs = ['uz', 'uzc', 'ru', 'ky'];

/// Eski (tilga bog'langan) yorliqlar — UZS do'konlarda AYNAN shular qoladi.
const _legacy = {'uz': 'so‘m', 'uzc': 'сўм', 'ru': 'сом', 'ky': 'сом'};

/// ⚠️  NUQSONLI ESKI ALGORITM — faqat negativ nazorat uchun qayta tiklangan:
///     yorliq valyutaga QARAMASDAN, faqat tildan chiqarilardi.
String _oldLabelFromLangOnly(String _) => tr('so‘m');

Receipt _receiptWith(String currency) {
  final j = saleReceiptJson();
  j['totals'] = {...(j['totals'] as Map).cast<String, dynamic>(), 'currency': currency};
  return Receipt.fromJson(j);
}

void main() {
  setUp(() async {
    await resetCore(); // L.code = 'uz', Api.employee = null -> Cur.code = null
  });

  tearDown(() => Session.instance.debugReset());

  group('currencyLabel — yagona jadval', () {
    test('KGS — bitta KANONIK yozuv, TIL AHAMIYATSIZ', () {
      for (final l in _langs) {
        L.code = l;
        expect(currencyLabel('KGS'), 'сом', reason: 'til=$l');
      }
    });

    test('UZS — tilga qarab yozuv (bugungi xulq AYNAN saqlanadi)', () {
      for (final l in _langs) {
        L.code = l;
        expect(currencyLabel('UZS'), _legacy[l], reason: 'til=$l');
      }
    });

    test('valyuta YOQ — eski tilga-asoslangan yorliqqa ATAYLAB qaytadi', () {
      for (final l in _langs) {
        L.code = l;
        for (final v in [null, '', '   ']) {
          expect(currencyLabel(v), _legacy[l], reason: 'til=$l, qiymat=${v ?? "null"}');
        }
      }
    });

    test('NOMALUM kod — kodning OZI qaytadi, yorliq oylab TOPILMAYDI', () {
      expect(currencyLabel('EUR'), 'EUR');
      expect(currencyLabel('eur'), 'EUR', reason: 'registr normallashadi');
      expect(currencyLabel(' usd '), 'USD', reason: 'boshliq kesiladi');
      L.code = 'ru';
      expect(currencyLabel('EUR'), 'EUR', reason: 'til yorliqni almashtirmaydi');
    });
  });

  group('Cur — dokon valyutasining YAGONA manbai', () {
    test('Api.employee surati yozilganda Cur.code yangilanadi (login yoli)', () {
      expect(Cur.code, isNull);
      Api.employee = {'id': 'e1', 'company_currency': 'KGS'};
      expect(Cur.code, 'KGS');
      expect(Cur.label, 'сом');
    });

    test('chiqishda tozalanadi; eski server (maydonsiz surat) → null', () {
      Api.employee = {'id': 'e1', 'company_currency': 'KGS'};
      Api.employee = null;
      expect(Cur.code, isNull, reason: 'chiqish valyutani ham tozalaydi');
      Api.employee = {'id': 'e1'}; // eski server company_currency bermaydi
      expect(Cur.code, isNull);
      expect(Cur.label, 'so‘m', reason: 'eski yorliqqa qaytadi — regressiya yoq');
    });

    test('offline ishga tushish: saqlangan suratdan tiklanadi', () {
      // Qurilma xavfsiz xotirasidagi surat AYNI setter orqali qaytadi.
      Api.employee = {'id': 'e1', 'full_name': 'Kassir', 'company_currency': 'KGS'};
      expect(Cur.label, 'сом', reason: 'serverga ulanmasdan ham valyuta malum');
    });
  });

  group('pul formatlovchilari dokon valyutasiga boysunadi', () {
    test('money() — KGS dokonda ozbekcha interfeys ham "сом"', () {
      Api.employee = {'company_currency': 'KGS'};
      expect(money(12345), '12 345 сом');
      L.code = 'ru';
      expect(money(12345), '12 345 сом');
    });

    test('money() — UZS dokonda bugungi yorliq saqlanadi', () {
      Api.employee = {'company_currency': 'UZS'};
      expect(money(12345), '12 345 so‘m');
      L.code = 'ru';
      expect(money(12345), '12 345 сом');
    });

    // DIQQAT: `formatCents` minglikni NBSP ( ) bilan ajratadi, `money()` esa
    // uni oddiy bo‘shliqqa almashtiradi — ajratgich bu tuzatishda TEGILMAGAN.
    test('formatCents()/moneyExact() — ayni manba', () {
      expect(formatCents(1234500), '12 345 so‘m', reason: 'valyuta yoq → eski yorliq');
      Api.employee = {'company_currency': 'KGS'};
      expect(formatCents(1234500), '12 345 сом');
      expect(formatCents(1234550), '12 345,50 сом');
      expect(moneyExact(12.5), '12,50 сом');
      expect(formatCents(1234500, currency: false), '12 345', reason: 'yorliqsiz rejim tegilmagan');
    });

    testWidgets('MoneyField suffiksi — YANGI summa dokon valyutasida', (tester) async {
      Api.employee = {'company_currency': 'KGS'};
      await pumpAt390(tester, Scaffold(body: MoneyField(controller: TextEditingController())));
      expect(find.text('сом'), findsOneWidget);
      expect(find.text('so‘m'), findsNothing);
    });
  });

  group('HUJJAT valyutasi dokon valyutasidan USTUN', () {
    test('chek oz valyutasida qoladi — dokon boshqasiga otsa ham', () {
      Api.employee = {'company_currency': 'UZS'};
      expect(receiptCurrency(_receiptWith('KGS')), 'сом',
          reason: 'KGS cheki UZS dokonda ham KGS');
      Api.employee = {'company_currency': 'KGS'};
      expect(receiptCurrency(_receiptWith('UZS')), 'so‘m',
          reason: 'tarixiy UZS chek jim qayta talqin QILINMAYDI');
    });

    test('chekda valyuta yoq → eski yorliq; nomalum kod → kodning ozi', () {
      Api.employee = {'company_currency': 'KGS'};
      expect(receiptCurrency(_receiptWith('')), 'so‘m');
      expect(receiptCurrency(_receiptWith('EUR')), 'EUR');
    });

    test('ReceiptDTO parse yoli: totals.currency oqiladi', () {
      expect(_receiptWith('KGS').currency, 'KGS');
      expect(Receipt.fromJson(saleReceiptJson()).currency, 'UZS', reason: 'fixture UZS');
    });
  });

  group('kassa/seyf nishoni dokon valyutasiga nisbatan', () {
    testWidgets('AYNI valyutadagi hisobda nishon YOQ, begonasida bor', (tester) async {
      Api.employee = {'company_currency': 'KGS'};
      final info = CustodyInfo.fromJson(const <String, dynamic>{
        'mode': 'OPERATOR_MUST_CHOOSE',
        'reason': 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER',
        'resolved': null,
        'options': [
          {'id': 't1', 'type': 'TILL', 'code': 'K-01', 'currency': 'KGS'},
          {'id': 's1', 'type': 'SAFE', 'code': 'S-01', 'currency': 'USD'},
        ],
        'branch': {'id': 'b1', 'name': 'Markaz'},
      });
      await pumpAt390(
        tester,
        Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: CustodyBlock(info: info, selectedId: null, onChanged: (_) {}),
          ),
        ),
      );
      expect(find.textContaining('K-01'), findsOneWidget);
      expect(find.textContaining('· KGS'), findsNothing,
          reason: 'dokon valyutasi har hisob yonida takrorlanmaydi');
      expect(find.textContaining('· USD'), findsOneWidget,
          reason: 'begona valyuta KORINADI');
    });
  });

  group('/auth/context → surat → yorliq (toliq zanjir)', () {
    test('company.currency KGS butun zanjir boylab yetib boradi', () async {
      signIn();
      final be = FakeBackend()
        ..get('/auth/context', (_) {
          final j = contextJson();
          j['company'] = {...(j['company'] as Map).cast<String, dynamic>(), 'currency': 'KGS'};
          return j;
        });
      await be.run(() => Session.instance.load(force: true));
      expect(Session.instance.context!.companyCurrency, 'KGS');
      expect(Api.employee!['company_currency'], 'KGS', reason: 'surat saqlanadi (offline uchun)');
      expect(Cur.code, 'KGS');
      expect(money(1000), '1 000 сом');
    });

    test('eski server (company.currency yoq) → eski yorliq, regressiya yoq', () async {
      signIn();
      final be = FakeBackend()..get('/auth/context', (_) => contextJson());
      await be.run(() => Session.instance.load(force: true));
      expect(Session.instance.context!.companyCurrency, isNull);
      expect(Api.employee!.containsKey('company_currency'), isFalse);
      expect(Cur.label, 'so‘m');
    });
  });

  group('NEGATIV NAZORAT — eski algoritm nuqsonni qaytaradi', () {
    test('tilga-asoslangan yorliq KGS + ozbekchada YIQILADI', () {
      L.code = 'uz';
      expect(_oldLabelFromLangOnly('KGS'), 'so‘m',
          reason: 'eski algoritm valyutani umuman kormaydi');
      expect(currencyLabel('KGS'), 'сом');
      expect(_oldLabelFromLangOnly('KGS'), isNot(currencyLabel('KGS')),
          reason: 'aynan shu katak nuqson edi');
    });

    test('ikki algoritm UZS kataklarida AYNI — tuzatish tor', () {
      for (final l in _langs) {
        L.code = l;
        expect(_oldLabelFromLangOnly('UZS'), currencyLabel('UZS'), reason: 'til=$l');
      }
    });
  });
}
