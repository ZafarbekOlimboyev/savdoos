// R6.5 — qoralama saqlagichi: FAQAT RAM, qat'iy egalik izolyatsiyasi.
//
// Nima uchun: 401 (12 soatlik token muddati, parol tiklanishi, boshqa
// qurilmada chiqish) `main.dart` da `pushAndRemoveUntil(..., (r) => false)`
// ni ishga soladi va ochiq shakllardagi SAQLANMAGAN qo'l kiritmasi
// ogohlantirishsiz yo'qoladi (Fayzan, 2026-09-17). R6.4 buni 8 test bilan
// isbotladi.
//
// Shartnoma: qoralama DISKKA YOZILMAYDI va faqat AYNI server + kompaniya +
// xodim + filial uchun qaytariladi.
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/draft_vault.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Joriy sessiyaning qoralama doirasi — `Session.cacheKey` bilan AYNI
/// nomlash (server|kompaniya|xodim|filial).
String _scope() => Session.instance.cacheKey('draft');

void main() {
  setUp(() async {
    await resetCore();
    DraftVault.debugClear();
  });

  group('R6.5-V. DraftVault — egalik izolyatsiyasi', () {
    test('AYNI xodim qoralamasini qaytaradi', () {
      signIn(id: 'eA', companyCode: 'fayzan1');
      final scope = _scope();
      DraftVault.stash('corr.r1', {'reason': 'Nakladnoyda 4 ta kam'}, scope: scope);

      final got = DraftVault.claim('corr.r1', scope: _scope());
      expect(got, isNotNull);
      expect((got! as Map)['reason'], 'Nakladnoyda 4 ta kam');
    });

    test('BOSHQA xodimga qaytarMAYDI va qoralamani O\'CHIRADI', () {
      signIn(id: 'eA', companyCode: 'fayzan1');
      DraftVault.stash('corr.r1', {'reason': 'A ning ishi'}, scope: _scope());

      // Sessiya tugadi, boshqa xodim kirdi.
      Api.token = null;
      Api.employee = null;
      Session.instance.debugReset();
      signIn(id: 'eB', companyCode: 'fayzan1');

      expect(DraftVault.claim('corr.r1', scope: _scope()), isNull,
          reason: 'B A ning kiritmasini KO\'RMAYDI');
      // A qaytib kelsa ham — yozuv o'chirilgan (bir martalik urinish).
      Api.employee = null;
      Session.instance.debugReset();
      signIn(id: 'eA', companyCode: 'fayzan1');
      expect(DraftVault.claim('corr.r1', scope: _scope()), isNull,
          reason: 'begona urinish yozuvni O\'CHIRDI — qayta ochilmaydi');
    });

    test('BOSHQA kompaniyaga qaytarMAYDI', () {
      signIn(id: 'eA', companyCode: 'fayzan1');
      DraftVault.stash('corr.r1', {'reason': 'fayzan1 ishi'}, scope: _scope());

      Session.instance.debugReset();
      signIn(id: 'eA', companyCode: 'boshqa-dokon');
      expect(DraftVault.claim('corr.r1', scope: _scope()), isNull,
          reason: 'bir xil xodim id, BOSHQA kompaniya — ko\'rinmaydi');
    });

    test('claim BIR MARTALIK — ikkinchi chaqiruv null', () {
      signIn(id: 'eA');
      DraftVault.stash('corr.r1', {'reason': 'x'}, scope: _scope());
      expect(DraftVault.claim('corr.r1', scope: _scope()), isNotNull);
      expect(DraftVault.claim('corr.r1', scope: _scope()), isNull);
    });

    test('bir vaqtda bir nechta ekran qoralamasi', () {
      signIn(id: 'eA');
      final s = _scope();
      DraftVault.stash('corr.r1', {'reason': 'tuzatish'}, scope: s);
      DraftVault.stash('recv.item.7', {'qty': '12'}, scope: s);
      DraftVault.stash('count.b1', {'items': 3}, scope: s);

      expect(DraftVault.has('corr.r1', scope: s), isTrue);
      expect(DraftVault.has('recv.item.7', scope: s), isTrue);
      expect(DraftVault.has('count.b1', scope: s), isTrue);
      expect((DraftVault.claim('recv.item.7', scope: s)! as Map)['qty'], '12');
      // claim faqat o'zini oladi
      expect(DraftVault.has('corr.r1', scope: s), isTrue);
    });

    test('has() qoralamani O\'CHIRMAYDI va begona doiraga false', () {
      signIn(id: 'eA');
      final s = _scope();
      DraftVault.stash('corr.r1', {'reason': 'x'}, scope: s);
      expect(DraftVault.has('corr.r1', scope: s), isTrue);
      expect(DraftVault.has('corr.r1', scope: s), isTrue, reason: 'has() o\'chirmaydi');
      expect(DraftVault.has('corr.r1', scope: 'boshqa|doira'), isFalse);
    });

    test('evictAll hammasini o\'chiradi (chiqish/hisob almashishi)', () {
      signIn(id: 'eA');
      final s = _scope();
      DraftVault.stash('corr.r1', {'reason': 'x'}, scope: s);
      DraftVault.stash('recv.item.7', {'qty': '1'}, scope: s);
      DraftVault.evictAll();
      expect(DraftVault.has('corr.r1', scope: s), isFalse);
      expect(DraftVault.has('recv.item.7', scope: s), isFalse);
    });

    test('bo\'sh yoki noma\'lum doira saqlaMAYDI (fail-closed)', () {
      // Chiqilgan holat: Api.employee == null -> doira '-' lardan iborat.
      expect(Api.employee, isNull);
      DraftVault.stash('corr.r1', {'reason': 'x'}, scope: _scope());
      expect(DraftVault.has('corr.r1', scope: _scope()), isFalse,
          reason: 'noma\'lum xodim uchun qoralama SAQLANMAYDI');
    });

    test('sig\'im cheklovi: eng eskisi tushib qoladi, xotira o\'smaydi', () {
      signIn(id: 'eA');
      final s = _scope();
      for (var i = 0; i < DraftVault.maxEntries + 3; i++) {
        DraftVault.stash('k$i', {'i': i}, scope: s);
      }
      expect(DraftVault.debugCount, DraftVault.maxEntries);
      expect(DraftVault.has('k0', scope: s), isFalse, reason: 'eng eskisi chiqdi');
      expect(DraftVault.has('k${DraftVault.maxEntries + 2}', scope: s), isTrue);
    });
  });
}
