// CH-18A — hisobni o'chirish HOLATI: ekran shu obyekt bo'yicha shoxlanadi.
//
// ⚠️  NEGA SOF MANTIQ SINALADI. `Api` static metodlari to'g'ridan `http` ga
//     boradi va repoda uni almashtirish uchun seam YO'Q, shu bois ekranning
//     o'zini widget testida mock qilish uchun yangi seam qurish kerak bo'lardi
//     — bu CH-18A doirasidan tashqari va regressiya xavfi. Shu sababli bu yerda
//     ekran SHOXLANISH QARORLARI (holat parsing + hosila bayroqlar) o'lchanadi;
//     majburlashning o'zi esa SERVERDA va u yerda 21 test bilan qoplangan
//     (`tests/test_ch18a_hisob_ochirish.py`).
@TestOn('vm')
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';

void main() {
  group('AccountDeletionState.fromJson', () {
    test('ruxsat berilgan holat', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': true,
        'blockers': <String>[],
        'confirm_word': "O'CHIRISH",
        'role': 'menejer',
        'already_deleted': false,
        'transfer_candidates': <Map<String, String>>[],
        'store_closure_available': false,
      });
      expect(st.canDelete, isTrue);
      expect(st.blockers, isEmpty);
      expect(st.confirmWord, "O'CHIRISH");
      expect(st.isSoleManager, isFalse);
      expect(st.hasOpenShift, isFalse);
    });

    test('ochiq smena — o`chirish bloklangan', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['open_shift'],
        'confirm_word': "O'CHIRISH",
      });
      expect(st.canDelete, isFalse);
      expect(st.hasOpenShift, isTrue);
      expect(st.isSoleManager, isFalse);
    });

    test('yagona rahbar — nomzodlar RO`YXATI bilan keladi', () {
      // ⚠️  Bu holatda ekran «boshqa administrator tayinlang» deb aytadi;
      //     nomzodlar bo'sh bo'lsa esa do'konni yopish yo'lini ko'rsatadi.
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['sole_manager'],
        'confirm_word': "O'CHIRISH",
        'role': 'ega',
        'transfer_candidates': [
          {'id': 'a1', 'role': 'kassir'},
          {'id': 'b2', 'role': 'menejer'},
        ],
      });
      expect(st.isSoleManager, isTrue);
      expect(st.transferCandidates, ['a1', 'b2']);
      expect(st.role, 'ega');
    });

    test('`sole_owner` ham yagona rahbar sifatida ko`rinadi', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['sole_owner'],
        'confirm_word': "O'CHIRISH",
      });
      expect(st.isSoleManager, isTrue);
    });

    test('do`kon yopish HALI mavjud emas (server shunday aytadi)', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['sole_manager'],
        'confirm_word': "O'CHIRISH",
        'store_closure_available': false,
      });
      expect(st.storeClosureAvailable, isFalse);
    });

    test('yetishmayotgan/noto`g`ri maydonlar — YIQILMAYDI, FAIL-CLOSED', () {
      // Eski yoki buzuq javobda `can_delete` yo'q -> `false` bo'ladi, ya'ni
      // ekran o'chirish tugmasini KO'RSATMAYDI. Teskarisi xavfli bo'lardi.
      final st = AccountDeletionState.fromJson(const <String, dynamic>{});
      expect(st.canDelete, isFalse);
      expect(st.blockers, isEmpty);
      expect(st.confirmWord, '');
      expect(st.transferCandidates, isEmpty);
      expect(st.alreadyDeleted, isFalse);
    });

    test('nomzod ro`yxatida Map bo`lmagan element O`TKAZIB YUBORILADI', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['sole_manager'],
        'confirm_word': "O'CHIRISH",
        'transfer_candidates': ['axlat', 7, null, {'id': 'ok', 'role': 'kassir'}],
      });
      expect(st.transferCandidates, ['ok']);
    });

    test('PIN`li hisob: parol KERAK EMAS -> SO`ROV yo`li', () {
      // ⚠️  `needs_password:false` bo'lganda ekran o'chirish formasini EMAS,
      //     so'rov formasini ko'rsatadi: PIN o'zi qaytarilmas o'chirishga
      //     yetarli emas, bajarishni ega paroli bilan qiladi.
      final st = AccountDeletionState.fromJson(const {
        'can_delete': true,
        'blockers': <String>[],
        'confirm_word': "O'CHIRISH",
        'needs_password': false,
        'request': {'pending': false, 'requested_at': null},
      });
      expect(st.needsPassword, isFalse);
      expect(st.requestPending, isFalse);
      expect(st.requestedAt, isNull);
    });

    test('so`rov YUBORILGAN -> kutilmoqda holati', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': true,
        'blockers': <String>[],
        'confirm_word': "O'CHIRISH",
        'needs_password': false,
        'request': {'pending': true, 'requested_at': '2026-10-16T12:00:00+00:00'},
      });
      expect(st.requestPending, isTrue);
      expect(st.requestedAt, '2026-10-16T12:00:00+00:00');
    });

    test('`needs_password` yetishmasa — PAROL TALAB deb o`qiladi (fail-closed)', () {
      // Eski server bu maydonni yubormaydi; shunda parol so'raladi, ya'ni
      // KUCHLIROQ tasdiq. Teskarisi (parolsiz o'chirish) xavfli bo'lardi.
      final st = AccountDeletionState.fromJson(const {
        'can_delete': true, 'blockers': <String>[], 'confirm_word': "O'CHIRISH",
      });
      expect(st.needsPassword, isTrue);
      expect(st.requestPending, isFalse);
    });

    test('yagona ega: YOPISH yo`li ochiq deb aytiladi', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': ['sole_manager'],
        'confirm_word': "O'CHIRISH",
        'role': 'ega',
        'transfer_candidates': <Map<String, String>>[],
        'store_closure_available': true,
      });
      expect(st.isSoleManager, isTrue);
      expect(st.transferCandidates, isEmpty);
      expect(st.storeClosureAvailable, isTrue,
          reason: 'vorisi yo`q ega uchun chiqish yo`li ko`rsatilishi SHART');
    });

    test('allaqachon o`chirilgan hisob', () {
      final st = AccountDeletionState.fromJson(const {
        'can_delete': false,
        'blockers': <String>[],
        'confirm_word': "O'CHIRISH",
        'already_deleted': true,
      });
      expect(st.alreadyDeleted, isTrue);
    });
  });

  // ⚠️  CH-18C. Yopish tasdiqlash ekrani oqibatlarni TAXMIN QILMAYDI — ularni
  //     serverdan o'qiydi. Ilgari ekran «barcha xodimlarning ismi va telefoni
  //     o'chiriladi» deb yozardi; yopish faqat O'ZI so'raganlarni o'chiradigan
  //     bo'lgach bu YOLG'ONGA aylandi. Shu bois parsing qadalади: ekran
  //     ko'rsatadigan raqamlar aynan server aytgani bo'lishi kerak.
  group('StoreClosurePreview.fromJson', () {
    test('server raqamlari o`zgartirilmasdan o`qiladi', () {
      final pv = StoreClosurePreview.fromJson(const {
        'confirm_word': "O'CHIRISH",
        'employees_with_pii': 7,
        'pending_requests': 2,
        'pii_retained_after_closure': 5,
        'accounting_retained': true,
        'bulk_anonymization_available': false,
      });

      expect(pv.confirmWord, "O'CHIRISH");
      expect(pv.employeesWithPii, 7);
      expect(pv.pendingRequests, 2);
      expect(pv.piiRetainedAfterClosure, 5);
      expect(pv.accountingRetained, isTrue);
      // Ommaviy anonimlashtirish TAKLIF QILINMAYDI — hech kim tasdiqlamagan.
      expect(pv.bulkAnonymizationAvailable, isFalse);
    });

    test('maydon yo`q bo`lsa 0/false — soxta va`da berilmaydi', () {
      final pv = StoreClosurePreview.fromJson(const <String, dynamic>{});

      expect(pv.employeesWithPii, 0);
      expect(pv.pendingRequests, 0);
      expect(pv.piiRetainedAfterClosure, 0);
      expect(pv.accountingRetained, isFalse);
      expect(pv.bulkAnonymizationAvailable, isFalse);
      expect(pv.confirmWord, isEmpty);
    });

    test('son matn sifatida kelsa ham yiqilmaydi', () {
      final pv = StoreClosurePreview.fromJson(const {
        'employees_with_pii': 3.0,
        'pii_retained_after_closure': 3.0,
      });

      expect(pv.employeesWithPii, 3);
      expect(pv.piiRetainedAfterClosure, 3);
    });
  });
}
