// R7.2 — KANONIK BACKEND JAVOBI × HAQIQIY FLUTTER PARSER.
//
// NEGA BU FAYL BOR. `test/support/ai_contract.dart` javobni O'ZI yasaydi.
// Mobil testlar yashil bo'lsa ham haqiqiy server bilan mos kelmasligi mumkin —
// R7.0 auditi aynan shuni topdi. Bu fayl soxta javob ISHLATMAYDI: u
// `contracts/ai_consent.samples.json` ni o'qiydi, o'sha fayl HAQIQIY FastAPI
// serveridan `apps/server/tests/test_r72_ai_consent_contract.py` tomonidan
// yozib olinadi va o'sha test uni serverga qarab QULFLAYDI. Ya'ni:
//   · server shartnomasi siljisa  -> server testi QIZIL;
//   · mijoz parseri siljisa       -> BU test QIZIL;
//   · fikstura ajralsa            -> BU test QIZIL.
//
// ⚠️  R7.2 DA KANONIK HOLAT MASHINASIGA MOSLASHTIRILDI. R7.1 versiyasi shu
//     branch'ning statik reviziya jadvaliga tayanardi. Kanonik backend uch
//     rejimli (`paused`/`demo`/`active`), reviziyani BAZADA monoton saqlaydi
//     va `DELETE` javobida faqat `{"ok": true}` qaytaradi — uchalasi ham shu
//     yerda tekshiriladi.
import 'dart:convert';
import 'dart:io';

import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/ai_contract.dart';

/// Etalonni topadi: paket ildizidan (apps/mobile) yuqoriga chiqib boradi.
File _etalon() {
  var dir = Directory.current.absolute;
  for (var i = 0; i < 6; i++) {
    final f = File('${dir.path}/contracts/ai_consent.samples.json');
    if (f.existsSync()) return f;
    final ota = dir.parent;
    if (ota.path == dir.path) break;
    dir = ota;
  }
  throw StateError(
      'contracts/ai_consent.samples.json topilmadi (${Directory.current.path} dan '
      'yuqoriga qarab). Serverda yozing: BINOS_WRITE_AI_CONTRACT=1 pytest '
      'tests/test_r72_ai_consent_contract.py -k ETALON');
}

void main() {
  final xom = jsonDecode(_etalon().readAsStringSync()) as List<dynamic>;
  final shartnoma =
      (xom.first as Map<String, dynamic>)['shartnoma'] as Map<String, dynamic>;
  final namunalar = xom.skip(1).map((e) => e as Map<String, dynamic>).toList();

  /// Holat shaklidagi javoblar — `GET` va `POST` (grant). `DELETE` kanonik
  /// backendda faqat `{"ok": true}` qaytaradi, ya'ni u holat EMAS.
  bool holatShaklida(Map<String, dynamic> n) =>
      n['status'] == 200 && (n['body'] as Map).containsKey('mode');

  test('etalon serverning e\'lon qilgan shartnomasini olib yuradi', () {
    // Mijoz FAQAT v1 matnini va 2-protokolni biladi; server boshqasiga
    // o'tgan bo'lsa bu ilova uni tasdiqlay OLMAYDI.
    expect(shartnoma['disclosure_version'], 1,
        reason: 'server yangi oshkor etish versiyasiga o\'tgan — mobil tomonni '
            'ham yangilash kerak');
    expect(shartnoma['protocol_version'], 2,
        reason: 'mijoz parseri `protocol_version == 2` ni MAJBURIY talab qiladi');
    expect(shartnoma['disclosure_id'], isA<String>());
    expect((shartnoma['disclosure_id'] as String).trim(), isNotEmpty);
    expect(shartnoma['modes'], containsAll(<String>['active', 'paused', 'demo']));
    expect(shartnoma['providers'], isNotEmpty);
  });

  test('etalon kanonik holat mashinasining HAR rejimini qamraydi', () {
    final sahnalar = namunalar.map((n) => n['scenario'] as String).toSet();
    expect(sahnalar, containsAll(<String>[
      'paused', 'demo', 'active_rozilik_yoq', 'active_grant_echo',
      'active_berilgan', 'provayder_ozgardi', 'qaytarib_olindi',
    ]));
    expect(sahnalar.length, namunalar.length, reason: 'sahna nomi takrorlangan');
  });

  test('PAUSED holati mijozga 503 bo\'lib keladi — parse QILINMAYDI', () {
    // ⚠️  Kanonik siyosat `paused` bo'lsa AI ATAYLAB o'chirilgan. Mijoz buni
    //     xato sifatida ko'rsatadi va qo'lda kirim yo'lini ochiq qoldiradi;
    //     `mode: paused` HECH QACHON holat sifatida parse qilinmaydi
    //     (parser `mode in {active, demo}` ni talab qiladi).
    final n = namunalar.firstWhere((n) => n['scenario'] == 'paused');
    expect(n['status'], 503);
    expect((n['body'] as Map), isNotEmpty);
    expect(holatShaklida(n), isFalse);
  });

  test('DELETE javobi faqat `ok` qaytaradi — holat emas', () {
    final n = namunalar.firstWhere((n) => n['scenario'] == 'qaytarib_olindi');
    expect(n['status'], 200);
    expect((n['body'] as Map)['ok'], isTrue);
    expect(holatShaklida(n), isFalse,
        reason: 'kanonik `revoke` holat maydonlarini qaytarmaydi — mijoz '
            'bekor qilgandan keyin holatni QAYTA o\'qishi kerak');
  });

  for (final n in namunalar.where(holatShaklida)) {
    final scenario = n['scenario'] as String;
    final body = (n['body'] as Map).cast<String, dynamic>();

    test('KANONIK server javobi "$scenario" ni HAQIQIY parser qabul qiladi', () {
      // ⚠️  SHU YER — shartnoma buzilsa `BAD_RESPONSE` bilan yiqiladigan nuqta.
      final st = AiConsent.fromJson(body);

      expect(st.disclosureId, shartnoma['disclosure_id']);
      expect(st.revision, greaterThanOrEqualTo(1));
      expect(st.disclosureVersion, 1);
      expect(st.sameRequirement(st), isTrue,
          reason: 'talab o\'z-o\'ziga mos kelmadi');

      switch (scenario) {
        case 'demo':
          // Tashqariga hech narsa chiqmaydi -> dialog YO'Q.
          expect(st.mode, 'demo');
          expect(st.required_, isFalse);
          expect(st.granted, isFalse);
          expect(st.provider, isNull);
          expect(st.providerName, isNull);
          expect(st.model, isNull);
          expect(st.mustAsk, isFalse);
          break;
        case 'active_rozilik_yoq':
          expect(st.mode, 'active');
          expect(st.required_, isTrue);
          expect(st.granted, isFalse);
          expect(st.mustAsk, isTrue, reason: 'dialog ko\'rsatilishi SHART');
          expect(st.provider, 'gemini');
          expect(st.providerName, contains('Google'));
          expect(st.model, isNotNull);
          break;
        case 'active_grant_echo':
        case 'active_berilgan':
          expect(st.mode, 'active');
          expect(st.required_, isTrue);
          expect(st.granted, isTrue);
          expect(st.mustAsk, isFalse);
          expect(st.provider, 'gemini');
          break;
        case 'provayder_ozgardi':
          // Reviziya oshdi -> eski rozilik AVTOMATIK o'tmaydi.
          expect(st.mode, 'active');
          expect(st.required_, isTrue);
          expect(st.granted, isFalse,
              reason: 'eski rozilik yangi provayderga o\'tdi');
          expect(st.provider, 'anthropic');
          expect(st.previousProvider, 'gemini');
          expect(st.mustAsk, isTrue);
          break;
      }
    });
  }

  test('provayder o\'zgarsa talab REVIZIYASI ham o\'zgaradi', () {
    // `sameRequirement` ayni shu farqqa tayanadi: u o'zgarmasa, mijoz
    // «rozilik o'sha talab uchun» deb yanglishardi.
    AiConsent? gemini;
    AiConsent? anthropic;
    for (final n in namunalar.where(holatShaklida)) {
      final st = AiConsent.fromJson((n['body'] as Map).cast<String, dynamic>());
      if (st.provider == 'gemini') gemini ??= st;
      if (st.provider == 'anthropic') anthropic ??= st;
    }
    expect(gemini, isNotNull);
    expect(anthropic, isNotNull);
    expect(gemini!.sameRequirement(anthropic!), isFalse,
        reason: 'IKKI PROVAYDER AYNI talab deb hisoblandi');
    expect(gemini.revision == anthropic.revision, isFalse,
        reason: 'provayder o\'zgardi, reviziya esa o\'zgarmadi');
  });

  group('fikstura shartnomaga BO\'YSUNADI', () {
    // `support/ai_contract.dart` boshqa mobil testlarning soxta backendini
    // oziqlantiradi. U haqiqiy serverdan AJRALSA, o'sha testlar yashil bo'lib
    // turib mahsulotni buzishi mumkin — R7.0 topgan P0 shunday yuzaga kelgan.
    late Map<String, dynamic> kanonik;

    setUpAll(() {
      kanonik = (namunalar
              .firstWhere((n) => n['scenario'] == 'active_rozilik_yoq')['body']
          as Map).cast<String, dynamic>();
    });

    test('fiksturada server QAYTARMAYDIGAN maydon YO\'Q', () {
      final ortiqcha = aiRequirement.keys.where((k) => !kanonik.containsKey(k));
      expect(ortiqcha, isEmpty,
          reason: 'fiksturada o\'ylab topilgan maydon(lar) bor — server ularni '
              'qaytarmaydi, ya\'ni ularga tayangan test MAHSULOTNI o\'lchamaydi');
    });

    test('fikstura server QAYTARADIGAN majburiy maydonni TUSHIRIB qoldirmagan', () {
      // Parser talab qiladigan maydonlar fiksturada BO'LISHI shart, aks holda
      // soxta backend mijozga shartnomaga ZID javob berardi.
      for (final k in const ['mode', 'protocol_version', 'revision', 'provider',
        'provider_name', 'model', 'disclosure_id', 'disclosure_version',
        'required', 'granted']) {
        expect(aiRequirement.containsKey(k), isTrue,
            reason: 'fiksturada "$k" YO\'Q — kanonik parser uni talab qiladi');
      }
    });

    test('shartnoma maydonlari AYNAN mos', () {
      // `revision` va `model` — JOYLASHTIRISH/ketma-ketlik qiymatlari (har
      // serverda va har yurishda boshqa), shartnoma qiymati emas; qolgani esa
      // shartnomaning o'zi.
      for (final k in const ['mode', 'protocol_version', 'provider',
        'provider_name', 'disclosure_id', 'disclosure_version', 'required',
        'granted']) {
        expect(aiRequirement[k], kanonik[k], reason: 'fikstura "$k" da siljidi');
      }
    });

    test('fikstura HAQIQIY parser bilan parse bo\'ladi', () {
      final st = AiConsent.fromJson(Map<String, dynamic>.from(aiRequirement));
      expect(st.mode, 'active');
      expect(st.mustAsk, isTrue);
    });
  });
}
