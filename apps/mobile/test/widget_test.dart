// Minimal smoke-test. To'liq E2E test backend (Railway) talab qiladi, shuning uchun
// bu yerda faqat format yordamchilari tekshiriladi.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/format.dart';

void main() {
  test('qtyStr butun va kasr sonlarni to‘g‘ri formatlaydi', () {
    expect(qtyStr(24), '24');
    expect(qtyStr(1.5), '1.500');
  });

  test('short mln/ming qisqartmasi', () {
    expect(short(1500000), '1,5 mln');
    expect(short(34000), '34 ming');
  });

  test('dmy null uchun bo‘sh satr', () {
    expect(dmy(null), '');
  });
}
