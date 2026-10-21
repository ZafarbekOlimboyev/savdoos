// R4C — FAKE BACKEND ROUTE USTUVORLIGI.
//
// ⚠️  NEGA BU TEST BOR. `receiving_flow_test.dart` dagi «AI review: tracked
//     match» Build 59–62 da yiqilgan edi va sabab mahsulot kodida EMAS, shu
//     matcherda topildi: `on()` yangi route'ni ro'yxat BOSHIGA qo'yadi,
//     `_handle` esa BIRINCHI mos kelganini olardi — ya'ni natija faqat
//     RO'YXATDAN O'TISH TARTIBIGA bog'liq edi. Natijada keyinroq ro'yxatdan
//     o'tgan `/receiving/{id}` literal `/receiving/ai-consent` ni SOYA QILDI
//     va rozilik so'rovi qabul TAFSILOTI payload'ini oldi.
//
//     Matcherning o'zida birorta test yo'q edi — shuning uchun nuqson uch
//     build davomida (59, 60, 61, 62) sezilmay qoldi va Apple'ga yuborilgan
//     ikkilikda ham shu holat bilan chiqdi. Bu fayl aynan shu bo'shliqni
//     yopadi: ustuvorlik qoidasi endi QADALGAN.
@TestOn('vm')
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';

import 'support/support.dart';

/// Berilgan yo'lni so'raydi va javobdagi `who` maydonini qaytaradi —
/// ya'ni QAYSI handler javob berganini aytadi.
Future<String> who(FakeBackend be, String path, {String method = 'GET'}) =>
    be.run(() async {
      final r = method == 'GET'
          ? await Api.getJson(path)
          : await Api.postJson(path, const {});
      return '${r.map['who']}';
    });

void main() {
  setUp(() async {
    await resetCore();
    signIn();
  });

  group('route ustuvorligi', () {
    test('1. LITERAL marshrut PARAMETRLI marshrutdan ustun', () async {
      final be = FakeBackend();
      be.get('/receiving/ai-consent', (_) => {'who': 'literal'});
      be.get('/receiving/{id}', (_) => {'who': 'param'});

      expect(await who(be, '/receiving/ai-consent'), 'literal');
      //  Parametrli marshrut boshqa qiymatlar uchun AVVALGIDEK ishlaydi.
      expect(await who(be, '/receiving/r-42'), 'param');
    });

    test('2. RO\'YXATDAN O\'TISH TARTIBI natijani o\'zgartirmaydi', () async {
      //  Teskari tartib — nuqson aynan shu holatda yuzaga kelgan edi.
      final be = FakeBackend();
      be.get('/receiving/{id}', (_) => {'who': 'param'});
      be.get('/receiving/ai-consent', (_) => {'who': 'literal'});
      expect(await who(be, '/receiving/ai-consent'), 'literal');

      final be2 = FakeBackend();
      be2.get('/receiving/ai-consent', (_) => {'who': 'literal'});
      be2.get('/receiving/{id}', (_) => {'who': 'param'});
      expect(await who(be2, '/receiving/ai-consent'), 'literal');
    });

    test('3. HTTP metodlari ALOHIDA ajratiladi', () async {
      final be = FakeBackend();
      be.get('/receiving/ai-consent', (_) => {'who': 'get-literal'});
      be.post('/receiving/ai-consent', (_) => {'who': 'post-literal'});
      be.post('/receiving/{id}', (_) => {'who': 'post-param'});

      expect(await who(be, '/receiving/ai-consent'), 'get-literal');
      expect(await who(be, '/receiving/ai-consent', method: 'POST'), 'post-literal');
      expect(await who(be, '/receiving/r-7', method: 'POST'), 'post-param');
    });

    test('4. ODDIY parametrli marshrutlar va ko\'p parametr ishlashda davom etadi',
        () async {
      final be = FakeBackend();
      be.get('/lots/products/{id}', (r) => {'who': 'one:${r.params['id']}'});
      be.get('/a/{x}/b/{y}', (r) => {'who': 'two:${r.params['x']}-${r.params['y']}'});

      expect(await who(be, '/lots/products/p1'), 'one:p1');
      expect(await who(be, '/a/11/b/22'), 'two:11-22');
    });

    test('5. NOANIQ to\'qnashuv JIM noto\'g\'ri marshrutga ketmaydi', () async {
      //  `/a/b/{y}` va `/a/{x}/c` ikkisi ham `/a/b/c` ga mos keladi va
      //  ikkisida ham bitta parametr bor. Chapdan o'ngga qoida bilan natija
      //  DETERMINISTIK: 1-indeksda literal `b` parametrdan ustun.
      final be = FakeBackend();
      be.get('/a/b/{y}', (_) => {'who': 'left-literal'});
      be.get('/a/{x}/c', (_) => {'who': 'right-literal'});
      expect(await who(be, '/a/b/c'), 'left-literal');

      //  Teskari ro'yxatdan o'tish — natija O'ZGARMAYDI.
      final be2 = FakeBackend();
      be2.get('/a/{x}/c', (_) => {'who': 'right-literal'});
      be2.get('/a/b/{y}', (_) => {'who': 'left-literal'});
      expect(await who(be2, '/a/b/c'), 'left-literal');
    });

    test('TENG aniqlikdagi dublikatda OXIRGI ro\'yxatdan o\'tgani g\'olib '
        '(override semantikasi saqlanadi)', () async {
      //  ⚠️  Bu XUSUSIYAT, nuqson emas: testlar `boot()` dan keyin standart
      //      mock'ni aynan shu bilan almashtiradi.
      final be = FakeBackend();
      be.get('/receiving/ai-consent', (_) => {'who': 'default'});
      be.get('/receiving/ai-consent', (_) => {'who': 'override'});
      expect(await who(be, '/receiving/ai-consent'), 'override');

      final be2 = FakeBackend();
      be2.get('/x/{id}', (_) => {'who': 'param-default'});
      be2.get('/x/{id}', (_) => {'who': 'param-override'});
      expect(await who(be2, '/x/1'), 'param-override');
    });
  });
}
