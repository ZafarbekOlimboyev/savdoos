// R7.1 — HAQIQIY BACKEND JAVOBI × HAQIQIY FLUTTER PARSER.
//
// NEGA BU FAYL BOR. `test/support/ai_contract.dart` javobni O'ZI yasaydi va
// uning sarlavhasi tashlab ketilgan `26332b0` server shartnomasini nomlaydi.
// Shu bois mobil testlar YASHIL bo'lsa ham, haqiqiy server bilan mos kelmasligi
// mumkin — R7.0 auditi aynan shuni topdi (Build 67 da AI-skan 100% ishlamasdi).
//
// Bu fayl soxta javob ISHLATMAYDI. U `contracts/ai_consent.samples.json` ni
// o'qiydi — bu fayl HAQIQIY FastAPI serveridan
// `apps/server/tests/test_r71_ai_consent_contract.py` tomonidan yozib olinadi va
// o'sha test uni serverga qarab QULFLAYDI. Ya'ni:
//   · server shartnomasi siljisa  -> server testi QIZIL;
//   · mijoz parseri siljisa       -> BU test QIZIL.
// Shartnoma faqat ikkala tomon bilan birga o'zgaradi.
import 'dart:convert';
import 'dart:io';

import 'package:savdoos_mobile/api/receiving_api.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/ai_contract.dart';

/// Etalonni topadi: paket ildizidan (apps/mobile) yuqoriga chiqib boradi.
/// `flutter test` ni qaysi katalogdan yurgizilganidan QAT'I NAZAR ishlaydi.
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
      'tests/test_r71_ai_consent_contract.py -k ETALON');
}

void main() {
  final xom = jsonDecode(_etalon().readAsStringSync()) as List<dynamic>;
  final shartnoma = (xom.first as Map<String, dynamic>)['shartnoma'] as Map<String, dynamic>;
  final namunalar = xom.skip(1).map((e) => e as Map<String, dynamic>).toList();

  test('etalon serverning e\'lon qilgan shartnomasini olib yuradi', () {
    // Mijoz FAQAT v1 matnini biladi; server boshqa versiyani e'lon qilsa, bu
    // ilova uni tasdiqlay OLMAYDI va buni jim o'tkazib yubormasligi kerak.
    expect(shartnoma['disclosure_version'], 1,
        reason: 'server yangi oshkor etish versiyasiga o\'tgan — bu ilova '
            'uni tasdiqlay olmaydi, mobil tomonni ham yangilash kerak');
    expect(shartnoma['disclosure_id'], isA<String>());
    expect((shartnoma['disclosure_id'] as String).trim(), isNotEmpty);
    final revisions = (shartnoma['revisions'] as Map).values.toList();
    expect(revisions, isNotEmpty, reason: 'server reviziya e\'lon qilmagan');
    expect(revisions.toSet().length, revisions.length,
        reason: 'IKKI xil talab AYNI reviziyani ulashmoqda — `sameRequirement` '
            'provayder o\'zgarishini sezmay qolardi');
    for (final r in revisions) {
      expect(r, isA<int>());
      expect(r as int, greaterThanOrEqualTo(1));
    }
  });

  test('har bir namuna uchun sahna son-sanog\'i', () {
    expect(namunalar.length, greaterThanOrEqualTo(6),
        reason: 'etalon oltita holatni qamrashi kerak');
    expect(namunalar.map((n) => n['scenario']).toSet().length, namunalar.length);
  });

  for (final n in namunalar) {
    final scenario = n['scenario'] as String;
    final status = n['status'] as int;
    final body = (n['body'] as Map).cast<String, dynamic>();

    test('HAQIQIY server javobi "$scenario" ni HAQIQIY parser qabul qiladi', () {
      if (status != 200) {
        // 4xx — mijoz uchun normal yo'l (fail-closed), parse qilinmaydi.
        expect(body, isNotEmpty);
        return;
      }
      // ⚠️  SHU YER — R7.0 topgan P0 ning o'lchov nuqtasi. Server `revision`
      //     yoki `disclosure_id` ni qaytarmasa, bu chaqiruv `BAD_RESPONSE`
      //     bilan yiqiladi va AI-skan butunlay ishlamaydi.
      final st = AiConsent.fromJson(body);

      expect(st.disclosureId, shartnoma['disclosure_id'],
          reason: 'server namunada boshqa disclosure_id qaytardi');
      expect(st.revision, greaterThanOrEqualTo(1));
      expect(st.disclosureVersion, 1);

      switch (scenario) {
        case 'demo':
          // Provayder yo'q -> tashqariga hech narsa chiqmaydi -> dialog YO'Q.
          expect(st.required_, isFalse);
          expect(st.granted, isFalse);
          expect(st.provider, isNull);
          expect(st.mustAsk, isFalse);
          break;
        case 'gemini_rozilik_yoq':
          expect(st.required_, isTrue);
          expect(st.granted, isFalse);
          expect(st.mustAsk, isTrue, reason: 'dialog ko\'rsatilishi SHART');
          expect(st.provider, 'gemini');
          expect(st.providerName, contains('Google'));
          break;
        case 'gemini_grant_echo':
        case 'gemini_berilgan':
          expect(st.required_, isTrue);
          expect(st.granted, isTrue);
          expect(st.mustAsk, isFalse);
          expect(st.provider, 'gemini');
          break;
        case 'provayder_ozgardi':
          // Eski rozilik YANGI provayderga AVTOMATIK o'tmaydi.
          expect(st.required_, isTrue);
          expect(st.granted, isFalse, reason: 'eski rozilik yangi provayderga o\'tdi');
          expect(st.provider, 'anthropic');
          expect(st.previousProvider, 'gemini');
          expect(st.mustAsk, isTrue);
          break;
        case 'qaytarib_olindi':
          expect(st.granted, isFalse);
          expect(st.mustAsk, isTrue);
          break;
      }
    });
  }

  group('fikstura shartnomaga BO\'YSUNADI', () {
    // `support/ai_contract.dart` boshqa mobil testlarning soxta backendini
    // oziqlantiradi. U haqiqiy serverdan AJRALSA, o'sha testlar yashil bo'lib
    // turib mahsulotni buzishi mumkin — R7.0 topgan P0 aynan shunday yuzaga
    // kelgan. Shu bois fikstura shu yerda etalonga qarab tekshiriladi.
    late Map<String, dynamic> kanonik;

    setUpAll(() {
      kanonik = namunalar
          .firstWhere((n) => n['scenario'] == 'gemini_rozilik_yoq')['body']
          .cast<String, dynamic>() as Map<String, dynamic>;
    });

    test('fiksturada server QAYTARMAYDIGAN maydon YO\'Q', () {
      final ortiqcha = aiRequirement.keys.where((k) => !kanonik.containsKey(k));
      expect(ortiqcha, isEmpty,
          reason: 'fiksturada o\'ylab topilgan maydon(lar) bor — server ularni '
              'qaytarmaydi, ya\'ni ularga tayangan test MAHSULOTNI o\'lchamaydi');
    });

    test('shartnoma maydonlari AYNAN mos', () {
      // `model` — JOYLASHTIRISH konfiguratsiyasi (har serverda boshqa), shartnoma
      // qiymati emas; qolgani esa shartnomaning o'zi.
      for (final k in const ['revision', 'provider', 'provider_name',
        'disclosure_id', 'disclosure_version', 'required', 'granted']) {
        expect(aiRequirement[k], kanonik[k], reason: 'fikstura "$k" da siljidi');
      }
    });
  });

  test('provayder o\'zgarsa talab REVIZIYASI ham o\'zgaradi', () {
    // `sameRequirement` ayni shu farqqa tayanadi: u o'zgarmasa, mijoz
    // «rozilik o'sha talab uchun» deb yanglishardi.
    AiConsent? gemini;
    AiConsent? anthropic;
    for (final n in namunalar) {
      if (n['status'] != 200) continue;
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
}
