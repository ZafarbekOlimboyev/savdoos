// R5.1 — S3: QULF XATOLARDA FAIL-CLOSED BO'LISHI.
//
// ⚠️  NEGA BU TEST BOR. `Lock.loadFailed` oshkor qilingan edi, ammo HECH KIM
//     uni tekshirmasdi. Xavfsiz xotira o'qishi yiqilganda (iOS Keychain
//     qurilma ilk yoqilgandan keyin qulflangan — `errSecInteractionNotAllowed`,
//     Keystore nosoz, iCloud tiklanishidan keyin access-group mos kelmaydi)
//     PIN xeshi o'qilmaydi:
//
//         _hash == null  ->  hasPin == false  ->  shouldLock == false
//         main.dart      ->  Shell()  (QULFSIZ!)
//
//     Ya'ni kirgan foydalanuvchining savdo, kassa, qarz va mijoz ma'lumotlari
//     PIN SO'RALMASDAN ochilardi. "PIN yo'q" va "PIN borligini bilib bo'lmadi"
//     bir xil muomala ko'rardi.
//
//     Bu test holat qiymatini EMAS, himoyalangan interfeysning haqiqatan
//     bloklanganini tekshiradi: daraxtda [Shell] YO'Q bo'lishi shart.
@TestOn('vm')
library;

import 'dart:io' show File, SocketException;

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/main.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/lock_recovery_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Kalit bo'yicha tanlab yiqiladigan xotira (qolgan kalitlar normal ishlaydi).
/// [failRead]/[failWrite] ni test o'rtasida o'zgartirish mumkin — "xotira
/// tuzaldi" holatini shu bilan modellaymiz.
class _FlakyStore implements SecretStore {
  _FlakyStore({Set<String>? failRead, Set<String>? failWrite, Set<String>? failDelete})
      : failRead = {...?failRead},
        failWrite = {...?failWrite},
        failDelete = {...?failDelete};

  final Map<String, String> map = {};
  final Set<String> failRead;
  final Set<String> failWrite;
  final Set<String> failDelete;
  int reads = 0;

  /// Shuncha yozuvdan KEYIN har qanday yozuv yiqiladi (`null` = cheksiz).
  /// «Xotira amal o'rtasida o'ldi» holatini modellaydi.
  int? writeBudget;
  int writes = 0;

  @override
  bool get isHardwareBacked => true;

  @override
  Future<String?> read(String key) async {
    reads++;
    if (failRead.contains(key)) throw StateError('read down: $key');
    return map[key];
  }

  @override
  Future<void> write(String key, String value) async {
    final budget = writeBudget;
    if (budget != null && writes >= budget) throw StateError('store died: $key');
    if (failWrite.contains(key)) throw StateError('write down: $key');
    writes++;
    map[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    if (failDelete.contains(key)) throw StateError('delete down: $key');
    map.remove(key);
  }
}

/// Haqiqiy `setPin` yozgan juftlik (shakl testlari uchun manba).
Future<Map<String, String>> _realPinPair(String pin) async {
  final s = _FlakyStore();
  SecretStore.instance = s;
  await Lock.clear();
  await Lock.setPin(pin);
  return {...s.map};
}

void main() {
  final original = SecretStore.instance;

  setUp(() async => resetCore());

  tearDown(() async {
    SecretStore.instance = original;
    await Lock.clear();
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('classifyLock — to\'rt holat ajratiladi', () {
    test('o\'qildi, hech narsa yo\'q -> absent', () {
      expect(classifyLock(readOk: true, hash: null, salt: null), LockStatus.absent);
      expect(classifyLock(readOk: true, hash: '', salt: ''), LockStatus.absent);
    });

    test('o\'qildi, juftlik to\'g\'ri -> valid', () {
      expect(classifyLock(readOk: true, hash: 'a' * 64, salt: 'b' * 32), LockStatus.valid);
    });

    test('o\'qish YIQILDI -> unavailable (qiymatlarga qaralmaydi)', () {
      expect(classifyLock(readOk: false, hash: null, salt: null), LockStatus.unavailable);
      expect(classifyLock(readOk: false, hash: 'a' * 64, salt: 'b' * 32), LockStatus.unavailable,
          reason: 'yarim o\'qishdan "PIN bor" degan xulosa chiqarilmaydi');
    });

    group('o\'qildi, lekin juftlik buzilgan -> corrupt', () {
      test('xesh bor, tuz yo\'q', () {
        expect(classifyLock(readOk: true, hash: 'a' * 64, salt: null), LockStatus.corrupt);
      });
      test('tuz bor, xesh yo\'q', () {
        expect(classifyLock(readOk: true, hash: null, salt: 'b' * 32), LockStatus.corrupt);
      });
      test('xesh uzunligi noto\'g\'ri', () {
        expect(classifyLock(readOk: true, hash: 'a' * 63, salt: 'b' * 32), LockStatus.corrupt);
        expect(classifyLock(readOk: true, hash: 'a' * 65, salt: 'b' * 32), LockStatus.corrupt);
      });
      test('tuz uzunligi noto\'g\'ri', () {
        expect(classifyLock(readOk: true, hash: 'a' * 64, salt: 'b' * 31), LockStatus.corrupt);
      });
      test('onaltilik emas (bo\'sh joy, katta harf, boshqa belgi)', () {
        expect(classifyLock(readOk: true, hash: 'g' * 64, salt: 'b' * 32), LockStatus.corrupt);
        expect(classifyLock(readOk: true, hash: 'A' * 64, salt: 'b' * 32), LockStatus.corrupt,
            reason: 'sha256 kichik harf chiqaradi — katta harf bu bizning yozuvimiz emas');
        expect(classifyLock(readOk: true, hash: '${'a' * 63} ', salt: 'b' * 32), LockStatus.corrupt);
      });
    });

    test('RATCHET: setPin yozgan HAQIQIY juftlik valid deb tanilishi shart', () async {
      // Shakl konstantalari (64/32 onaltilik) `_hashPin`/`_randSalt` dan kelib
      // chiqadi. Ulardan biri o'zgarsa — shu test yiqiladi, jim qolmaydi.
      final pair = await _realPinPair('7391');
      expect(
          classifyLock(
            readOk: true,
            hash: pair[SecretKeys.pinHash],
            salt: pair[SecretKeys.pinSalt],
          ),
          LockStatus.valid);
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Lock.load() — xato in\'ektsiyasi holatga aylanadi', () {
    test('bo\'sh xotira -> absent, holat ANIQ', () async {
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      expect(Lock.status, LockStatus.absent);
      expect(Lock.statusKnown, isTrue);
    });

    test('pin_hash o\'qishi yiqildi -> unavailable, holat NOMA\'LUM', () async {
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash});
      await Lock.load();
      expect(Lock.status, LockStatus.unavailable);
      expect(Lock.statusKnown, isFalse);
      expect(Lock.loadFailed, isTrue, reason: 'eski nom ham ishlashda davom etsin');
    });

    test('pin_salt o\'qishi yiqildi -> unavailable', () async {
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinSalt});
      await Lock.load();
      expect(Lock.status, LockStatus.unavailable);
      expect(Lock.statusKnown, isFalse);
    });

    test('diskda yarim juftlik (tuz bor, xesh yo\'q) -> corrupt, holat NOMA\'LUM', () async {
      SecretStore.instance = _FlakyStore()..map[SecretKeys.pinSalt] = 'b' * 32;
      await Lock.load();
      expect(Lock.status, LockStatus.corrupt);
      expect(Lock.statusKnown, isFalse);
      expect(Lock.loadFailed, isFalse, reason: 'o\'qish ISHLADI — bu boshqa nosozlik');
    });

    test('buzilgan juftlik xotirada SAQLANMAYDI (cheksiz "noto\'g\'ri PIN" bo\'lmasin)', () async {
      SecretStore.instance = _FlakyStore()
        ..map[SecretKeys.pinHash] = 'zz' * 32
        ..map[SecretKeys.pinSalt] = 'b' * 32;
      await Lock.load();
      expect(Lock.status, LockStatus.corrupt);
      expect(Lock.hasPin, isFalse);
      expect(Lock.verify('1234'), isFalse);
    });

    test('IKKINCHI DARAJALI kalit xatosi holatni buzmaydi -> valid', () async {
      final pair = await _realPinPair('1111');
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.biometricOn})..map.addAll(pair);
      await Lock.load();
      expect(Lock.status, LockStatus.valid);
      expect(Lock.statusKnown, isTrue);
      expect(Lock.verify('1111'), isTrue);
    });

    test('qayta ishga tushirish: yozilgan PIN valid bo\'lib qaytadi', () async {
      final pair = await _realPinPair('4321');
      SecretStore.instance = _FlakyStore()..map.addAll(pair);
      await Lock.load();
      expect(Lock.status, LockStatus.valid);
      expect(Lock.shouldLock, isTrue);
      expect(Lock.verify('4321'), isTrue);
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Darvoza: himoyalangan qobiq FAQAT holat aniq bo\'lganda', () {
    Future<void> withState(LockStatus want) async {
      // Darvoza endi login holatini ham tekshiradi: `Api.loggedIn` bo'lmasa
      // u (to'g'ri ravishda) login ekranini qaytaradi.
      signIn();
      switch (want) {
        case LockStatus.absent:
          SecretStore.instance = _FlakyStore();
        case LockStatus.valid:
          final pair = await _realPinPair('2468');
          SecretStore.instance = _FlakyStore()..map.addAll(pair);
        case LockStatus.corrupt:
          SecretStore.instance = _FlakyStore()..map[SecretKeys.pinHash] = 'a' * 64;
        case LockStatus.unavailable:
          SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash});
      }
      await Lock.load();
      expect(Lock.status, want, reason: 'test o\'zini sozlay olmadi');
    }

    test('unavailable -> tiklash ekrani (qobiq EMAS)', () async {
      await withState(LockStatus.unavailable);
      expect(lockGateHome(), isA<LockRecoveryScreen>());
    });

    test('NUQSON GUVOHI: eski darvoza (shouldLock) shu yerda qobiqni ochardi', () async {
      // Bu test tuzatishning MOHIYATINI qayd etadi. `unavailable` holatida
      // tekshiriladigan xesh yo'q, shuning uchun `shouldLock` YOLG'ON qaytadi
      // va `main.dart` dagi eski shart — `Lock.shouldLock ? LockScreen : Shell`
      // — himoyalangan qobiqni PIN SO'RAMASDAN ochardi. Darvoza endi
      // `statusKnown` ni ham hisobga oladi.
      await withState(LockStatus.unavailable);
      expect(Lock.shouldLock, isFalse, reason: 'eski darvoza "qulf shart emas" deb o\'qirdi');
      expect(Lock.statusKnown, isFalse, reason: 'yangi darvoza aynan shuni ko\'radi');
      expect(lockGateHome(), isNot(isA<Shell>()), reason: 'S3 qaytib keldi');
    });

    test('corrupt -> tiklash ekrani (qobiq EMAS)', () async {
      await withState(LockStatus.corrupt);
      expect(lockGateHome(), isA<LockRecoveryScreen>());
    });

    test('valid -> qulf ekrani', () async {
      await withState(LockStatus.valid);
      expect(lockGateHome(), isA<LockScreen>());
    });

    test('absent -> MAJBURIY PIN onboarding (qobiq EMAS)', () async {
      // Ilgari bu yerda `Shell` kutilardi. Lekin kirgan foydalanuvchida
      // `absent` holati FAQAT tugallanmagan onboarding'ni anglatadi — qobiqni
      // ochish sessiyani butunlay qulfsiz qoldirardi.
      await withState(LockStatus.absent);
      expect(lockGateHome(), isA<MandatoryPinSetupScreen>());
      expect(lockGateHome(), isNot(isA<Shell>()));
    });

    test('qulf o\'chirilgan + valid -> qobiq', () async {
      await withState(LockStatus.valid);
      await Lock.setLockEnabled(false);
      expect(lockGateHome(), isA<Shell>());
    });

    test('QULF O\'CHIRILGAN BO\'LSA HAM noma\'lum holat qobiqni ochmaydi', () async {
      // Operator "ochishda PIN so'ralsin" ni o'chirgan, keyin xotira yiqildi:
      // `lock_on` ni ham o'qib bo'lmaydi, ya'ni o'chirilganini BILMAYMIZ.
      signIn();
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash, SecretKeys.lockOn});
      await Lock.load();
      expect(lockGateHome(), isA<LockRecoveryScreen>());
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Manba darvozasi (RATCHET)', () {
    test('main.dart uyni O\'ZI tanlamaydi — qobiqni ham IMPORT qilmaydi', () {
      // S3 aynan shu yerda tug'ilgan edi: `Lock.shouldLock ? LockScreen : Shell`.
      // Darvoza `lockGateHome()` da bo'lishi SHART.
      //
      // Qorovul IMPORTLARGA qo'yilgan, matn qidirishga EMAS: izoh ichidagi
      // ko'chirma shartni ham «kod» deb hisoblab, yolg'on signal berardi.
      // Inline qarorni qaytarish uchun bu importlarni tiklash kerak bo'ladi.
      final src = File('lib/main.dart').readAsStringSync();
      final imports = [
        for (final l in src.split('\n'))
          if (l.trimLeft().startsWith('import ')) l.trim(),
      ];
      expect(src.contains('lockGateHome()'), isTrue,
          reason: 'darvoza funksiyasi ishlatilmagan');
      expect(imports.where((l) => l.contains('screens/shell.dart')), isEmpty,
          reason: 'main.dart qobiqni O\'ZI qurmasin — S3 qaytadi');
      expect(imports.where((l) => l.contains('screens/pin_screens.dart')), isEmpty,
          reason: 'main.dart qulf ekranini O\'ZI qurmasin — S3 qaytadi');
    });

    test('qobiqni ochadigan yagona darvoza — lockGateHome()', () {
      // `const Shell()` ni qulf qaroriga asoslab qaytaradigan boshqa joy
      // bo'lmasligi kerak (qulf ekranining o'z `_unlock()` i bundan mustasno).
      final gate = File('lib/screens/lock_recovery_screen.dart').readAsStringSync();
      expect(gate.contains('if (!Lock.statusKnown) return const LockRecoveryScreen();'), isTrue,
          reason: 'darvoza avval holat ANIQligini tekshirishi shart');
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Tiklash ekrani: haqiqiy UI bloklanishi', () {
    Future<void> pumpBlocked(WidgetTester tester, {Set<String>? failRead}) async {
      signIn();
      SecretStore.instance = _FlakyStore(failRead: failRead ?? {SecretKeys.pinHash});
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
    }

    testWidgets('daraxtda Shell YO\'Q va PIN klaviaturasi ham YO\'Q', (tester) async {
      await pumpBlocked(tester);
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing, reason: 'himoyalangan qobiq ochilib qoldi');
      expect(find.byType(LockScreen), findsNothing,
          reason: 'tekshirilmaydigan xesh bilan PIN so\'rash — boshi berk ko\'cha');
      // Faqat ikki chiqish yo'li bor.
      expect(find.text('Qayta urinish'), findsOneWidget);
      expect(find.text('Parol bilan kirish'), findsOneWidget);
    });

    testWidgets('corrupt holatda ham qobiq ochilmaydi', (tester) async {
      signIn();
      SecretStore.instance = _FlakyStore()..map[SecretKeys.pinSalt] = 'b' * 32;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    testWidgets('O\'TKINCHI xato PIN va tokenni O\'CHIRMAYDI', (tester) async {
      // ⚠️  Diskda HAQIQIY PIN juftligi turishi SHART, aks holda «o'chirilmadi»
      //     tasdig'i bo'm-bo'sh bo'ladi: o'chiradigan narsa yo'q edi.
      final pair = await _realPinPair('8642');
      signIn();
      final store = _FlakyStore(failRead: {SecretKeys.pinHash})..map.addAll(pair);
      SecretStore.instance = store;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(LockRecoveryScreen), findsOneWidget);

      // Ekran ochilishining O'ZI hech narsani o'chirmasligi kerak.
      await tester.pump(const Duration(seconds: 2));
      expect(store.map[SecretKeys.pinHash], pair[SecretKeys.pinHash],
          reason: 'PIN xeshi o\'tkinchi xato sabab O\'CHIRILDI');
      expect(store.map[SecretKeys.pinSalt], pair[SecretKeys.pinSalt],
          reason: 'PIN tuzi o\'tkinchi xato sabab O\'CHIRILDI');
      expect(Api.token, isNotNull, reason: 'token o\'tkinchi xato sabab o\'chirilmaydi');
    });

    testWidgets('Qayta urinish: xotira tuzaldi va PIN bor -> PIN so\'raladi', (tester) async {
      final pair = await _realPinPair('9753');
      signIn();
      final store = _FlakyStore(failRead: {SecretKeys.pinHash})..map.addAll(pair);
      SecretStore.instance = store;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(LockScreen), findsNothing);

      store.failRead.clear(); // Keychain ochildi
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();

      expect(find.byType(LockScreen), findsOneWidget, reason: 'endi PIN tekshirila oladi');
      expect(find.byType(Shell), findsNothing, reason: 'PIN kiritilmasdan qobiq ochilmaydi');
      expect(Api.token, isNotNull);
    });

    testWidgets('Qayta urinish: xotira hali yiqilgan -> BLOKLANGAN qoladi', (tester) async {
      await pumpBlocked(tester);
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
      expect(find.text('Qulf holati hali tasdiqlanmadi'), findsOneWidget,
          reason: 'jim turish — foydalanuvchi tiqilib qoladi');
    });

    testWidgets('Parol bilan kirish: sessiya tozalanadi va login ekrani chiqadi', (tester) async {
      final be = FakeBackend()..post('/auth/logout', (_) => {'ok': true});
      await pumpBlocked(tester);
      await be.run(() async {
        await tester.tap(find.text('Parol bilan kirish'));
        await tester.pumpAndSettle();
        // Bu amal tokenni ham, PIN'ni ham o'chiradi — tasdiq so'raladi.
        await tester.tap(find.byKey(const Key('confirm-yes')));
        // Chiqish diskdagi eski katalog keshini ham tozalaydi — HAQIQIY IO.
        await flushIo(tester);
        await flushIo(tester);
      });
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
      expect(Api.token, isNull, reason: 'bu FOYDALANUVCHI tanlagan chiqish');
      expect(Lock.status, LockStatus.absent);
    });

    testWidgets('tasdiqni BEKOR qilish sessiyani saqlaydi', (tester) async {
      final pair = await _realPinPair('7777');
      signIn();
      final store = _FlakyStore(failRead: {SecretKeys.pinHash})..map.addAll(pair);
      SecretStore.instance = store;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();

      await tester.tap(find.text('Parol bilan kirish'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-no')));
      await tester.pumpAndSettle();

      expect(Api.token, isNotNull, reason: 'bekor qilish sessiyani o\'chirmasin');
      expect(store.map[SecretKeys.pinHash], pair[SecretKeys.pinHash]);
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    testWidgets('orqaga qaytish tugmasi tiklash ekranidan QUTQARMAYDI', (tester) async {
      await pumpBlocked(tester);
      final popped = await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(popped, isTrue, reason: 'PopScope so\'rovni yutib yuboradi');
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    testWidgets('internet yo\'q: parol bilan kirish ham qobiqni ochmaydi', (tester) async {
      // Serverga ulanish yiqiladi — chiqish LOKAL bajarilishi va himoyalangan
      // interfeys emas, LOGIN ekrani chiqishi kerak.
      final be = FakeBackend()..post('/auth/logout', (_) => throw const SocketException('offline'));
      await pumpBlocked(tester);
      Api.online.value = false;
      await be.run(() async {
        await tester.tap(find.text('Parol bilan kirish'));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('confirm-yes')));
        await flushIo(tester);
        await flushIo(tester);
      });
      expect(find.byType(Shell), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(Api.token, isNull, reason: 'oflayn bo\'lsa ham lokal chiqish bajariladi');
    });
  });


  // ───────────────────────────────────────────────────────────────────────────
  // Xavfsizlik ko'rigi topgan qo'shimcha fail-open'lar (R5.1 ikkinchi to'lqin).
  group('Ishlayotgan PIN o\'tkinchi xato sabab YO\'QOLMAYDI', () {
    test('PIN almashtirish yiqilsa — ESKI PIN ishlashda davom etadi', () async {
      // ⚠️  Egasining talabi AYNAN shu: "PIN yoki tokenni transient storage
      //     xatosi sabab avtomatik o'chirma". Ilgari `setPin` ning `catch` i
      //     `_discardPin()` ni SHARTSIZ chaqirib, ishlayotgan PIN'ni diskdan
      //     ham o'chirardi -> keyingi ishga tushishda ilova QULFSIZ ochilardi.
      signIn();
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111');

      // Endi xesh yozuvi yiqiladi (Keychain to'lgan / nosoz).
      store.failWrite.add(SecretKeys.pinHash);
      await expectLater(Lock.setPin('2222'), throwsStateError);

      expect(Lock.status, LockStatus.valid, reason: 'eski PIN hanuz amalda');
      expect(Lock.verify('1111'), isTrue, reason: 'eski PIN O\'CHIRILDI');
      expect(Lock.verify('2222'), isFalse, reason: 'yangi PIN o\'rnatilmagan');
      expect(lockGateHome(), isA<LockScreen>(), reason: 'qulf saqlanishi shart');

      // Diskda ham eski juftlik turishi kerak — sovuq ishga tushish tekshiruvi.
      store.failWrite.clear();
      await Lock.load();
      expect(Lock.status, LockStatus.valid);
      expect(Lock.verify('1111'), isTrue);
      expect(lockGateHome(), isA<LockScreen>());
    });

    test('hech qanday yozuv o\'tmasa — eski PIN BUTUN qoladi', () async {
      // Diskda hech narsa o'zgarmagan, demak eski juftlik joyida: holatni
      // «yo'qoldi» deb e'lon qilish ishlayotgan qulfni bekorga buzardi.
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111');

      store.failWrite.addAll({SecretKeys.pinHash, SecretKeys.pinSalt, SecretKeys.lockOn});
      await expectLater(Lock.setPin('2222'), throwsStateError);

      expect(Lock.status, LockStatus.valid);
      expect(Lock.verify('1111'), isTrue);
      expect(Lock.verify('2222'), isFalse);
    });

    test('xotira amal O\'RTASIDA o\'lsa — holat YOPIQ, absent EMAS', () async {
      // Tuz YANGISIGA yozilib, xesh yozilmaydi va tiklash ham o'tmaydi:
      // diskda mos kelmaydigan juftlik qoladi, ya'ni eski PIN ham ishlamaydi.
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111');

      store.writeBudget = store.writes + 1; // yana BITTA yozuv o'tadi, keyin o'ladi
      await expectLater(Lock.setPin('2222'), throwsStateError);

      expect(Lock.statusKnown, isFalse,
          reason: 'absent desak keyingi ishga tushishda ilova qulfsiz ochilardi');
      expect(Lock.status, LockStatus.unavailable);
      signIn();
      expect(lockGateHome(), isA<LockRecoveryScreen>());
      expect(lockGateHome(), isNot(isA<Shell>()));

      // Sovuq ishga tushish: diskda SHAKLI to'g'ri, lekin MOS KELMAYDIGAN
      // juftlik qoladi (yangi tuz + eski xesh). Mos kelmasligini PIN'siz
      // aniqlash MUMKIN EMAS, shu bois holat `valid` ko'rinadi va qulf ekrani
      // chiqadi — lekin HECH QANDAY PIN o'tmaydi. Bu fail-CLOSED boshi berk
      // ko'cha: chiqish yo'li — qulf ekranidagi «Chiqish» va parol bilan
      // qayta kirish. Qobiq hech qachon ochilmaydi.
      store.writeBudget = null;
      await Lock.load();
      expect(lockGateHome(), isNot(isA<Shell>()), reason: 'qobiq ochilsa — fail-OPEN');
      expect(lockGateHome(), isA<LockScreen>());
      expect(Lock.verify('1111'), isFalse, reason: 'eski PIN tuzi almashgan');
      expect(Lock.verify('2222'), isFalse, reason: 'yangi PIN xeshi yozilmagan');
    });

    test('BIRINCHI marta o\'rnatish yiqilsa — absent (yo\'qotadigan narsa yo\'q)', () async {
      final store = _FlakyStore(failWrite: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.clear();
      await expectLater(Lock.setPin('1234'), throwsStateError);
      expect(Lock.status, LockStatus.absent);
      expect(store.map.containsKey(SecretKeys.pinSalt), isFalse,
          reason: 'yarim yozilgan tuz qolmasin');
    });
  });

  group('Token bor, PIN yo\'q — onboarding MAJBURIY', () {
    test('tashlab ketilgan PIN onboarding qobiqni ochmaydi', () async {
      // Token login'da saqlanadi, PIN esa keyin qo'yiladi. Foydalanuvchi PIN
      // ekranida ilovani yopsa, ilgari keyingi ishga tushishda `absent` ->
      // Shell bo'lib, sessiya BUTUNLAY qulfsiz qolardi.
      signIn();
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      expect(Lock.status, LockStatus.absent);
      expect(lockGateHome(), isA<MandatoryPinSetupScreen>());
      expect(lockGateHome(), isNot(isA<Shell>()));
    });

    testWidgets('majburiy ekran haqiqatan PIN o\'rnatishni ko\'rsatadi', (tester) async {
      signIn();
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(PinSetupScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    test('kirmagan foydalanuvchi uchun darvoza login ekranini beradi', () async {
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      expect(Api.loggedIn, isFalse);
      expect(lockGateHome(), isA<LoginScreen>(), reason: 'darvoza YAKUNIY qaror egasi');
    });

    test('PIN qo\'yilgach qobiq ochiladi (onboarding buzilmaydi)', () async {
      signIn();
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      await Lock.setPin('2468');
      expect(lockGateHome(), isA<LockScreen>(), reason: 'PIN bor — qulf so\'raladi');
      await Lock.setLockEnabled(false);
      expect(lockGateHome(), isA<Shell>(), reason: 'operator o\'zi o\'chirgan');
    });
  });

  group('Buzilgan ikkinchi darajali kalitlar', () {
    test('lock_on buzilgan qiymat bo\'lsa qulf YOQILGAN qoladi', () async {
      final pair = await _realPinPair('1357');
      signIn();
      for (final bad in ['', 'x', '2', 'true']) {
        SecretStore.instance = _FlakyStore()
          ..map.addAll(pair)
          ..map[SecretKeys.lockOn] = bad;
        await Lock.load();
        expect(Lock.lockOn, isTrue, reason: '«$bad» qulfni o\'chirmasligi kerak');
        expect(lockGateHome(), isA<LockScreen>(), reason: '«$bad» -> qulf');
      }
    });

    test('lock_on = "0" — operatorning ANIQ tanlovi hurmat qilinadi', () async {
      final pair = await _realPinPair('1357');
      signIn();
      SecretStore.instance = _FlakyStore()
        ..map.addAll(pair)
        ..map[SecretKeys.lockOn] = '0';
      await Lock.load();
      expect(Lock.lockOn, isFalse);
      expect(lockGateHome(), isA<Shell>());
    });

    test('clear(): bitta o\'chirish yiqilsa QOLGANLARI baribir o\'chiriladi', () async {
      final store = _FlakyStore(failDelete: {SecretKeys.pinHash});
      SecretStore.instance = store;
      store.map.addAll({
        SecretKeys.pinHash: 'a' * 64,
        SecretKeys.pinSalt: 'b' * 32,
        SecretKeys.biometricOn: '1',
        SecretKeys.lockOn: '1',
        SecretKeys.failCount: '3',
        SecretKeys.lockUntil: '999',
      });

      await Lock.clear();

      // Birinchi xato qolganlarini to'xtatmasligi kerak.
      for (final k in [
        SecretKeys.pinSalt,
        SecretKeys.biometricOn,
        SecretKeys.lockOn,
        SecretKeys.failCount,
        SecretKeys.lockUntil,
      ]) {
        expect(store.map.containsKey(k), isFalse, reason: '$k diskda qoldi');
      }
    });
  });


  // ───────────────────────────────────────────────────────────────────────────
  // Mutatsiya sinovi ochgan bo'shliqlar: shu tuzatishlarni ortga qaytarsak
  // HECH BIR test yiqilmasdi.
  group('Qulf sozlamasi: AVVAL disk, keyin xotira', () {
    test('setLockEnabled yozuvi yiqilsa — xotira «yoqilgan» deb YOLG\'ON gapirmaydi', () async {
      // ⚠️  Ilgari xotira birinchi yangilanardi: «Ochishda PIN so'ralsin» ni
      //     QAYTA YOQQANDA yozuv yiqilsa, tugmacha yoqilgan ko'rinardi-yu,
      //     keyingi ishga tushishda diskdagi `'0'` o'qilib ilova QULFSIZ
      //     ochilardi.
      final pair = await _realPinPair('1111');
      final store = _FlakyStore()..map.addAll(pair);
      store.map[SecretKeys.lockOn] = '0'; // operator oldin o'chirgan edi
      SecretStore.instance = store;
      await Lock.load();
      expect(Lock.lockOn, isFalse);

      store.failWrite.add(SecretKeys.lockOn);
      await expectLater(Lock.setLockEnabled(true), throwsStateError,
          reason: 'xato CHAQIRUVCHIGA yetib borishi shart');
      expect(Lock.lockOn, isFalse, reason: 'xotira diskdan FARQ qilmasin');

      await Lock.load(); // sovuq ishga tushish diskdagi haqiqatni aytadi
      expect(Lock.lockOn, isFalse);
      expect(store.map[SecretKeys.lockOn], '0');
    });

    test('setBiometric yozuvi yiqilsa — xotira diskdan farq qilmaydi', () async {
      final store = _FlakyStore(failWrite: {SecretKeys.biometricOn});
      SecretStore.instance = store;
      await Lock.clear();
      await expectLater(Lock.setBiometric(true), throwsStateError);
      expect(Lock.biometricOn, isFalse);
      expect(store.map.containsKey(SecretKeys.biometricOn), isFalse);
    });

    test('setPin muvaffaqiyatli bo\'lsa holat VALID bo\'ladi', () async {
      // ⚠️  Bu qator bo'lmasa: token ham, PIN ham o'qilmagan (`unavailable`)
      //     seansda foydalanuvchi parol bilan kirib PIN qo'yadi — holat
      //     `unavailable` qolib, darvoza uni tiklash ekraniga qamab qo'yardi.
      final store = _FlakyStore(failRead: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.load();
      expect(Lock.statusKnown, isFalse, reason: 'test o\'zini sozlay olmadi');

      store.failRead.clear();
      await Lock.setPin('5319');
      expect(Lock.status, LockStatus.valid);
      signIn();
      expect(lockGateHome(), isA<LockScreen>(), reason: 'tiklash ekranida qamalib qolmasin');
    });
  });

  group('Sozlamalar ekrani xatoni YASHIRMAYDI', () {
    testWidgets('qulf sozlamasi saqlanmasa — xabar ko\'rsatiladi', (tester) async {
      final be = FakeBackend()..get('/auth/context', (_) => contextJson());
      final pair = await _realPinPair('1111');
      final store = _FlakyStore()..map.addAll(pair);
      SecretStore.instance = store;
      await Lock.load();
      signIn();
      await be.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, const SettingsScreen());
        await tester.pumpAndSettle();

        store.failWrite.add(SecretKeys.lockOn);
        final label = find.text('Ochishda PIN so‘ralsin');
        await tester.scrollUntilVisible(label, 120);
        await tester.pumpAndSettle();
        final sw = find.descendant(
          of: find.ancestor(of: label, matching: find.byType(Row)).first,
          matching: find.byType(Switch),
        );
        expect(sw, findsOneWidget);
        await tester.tap(sw);
        await tester.pumpAndSettle();
      });
      expect(find.text('Sozlama saqlanmadi — qaytadan urinib ko‘ring'), findsOneWidget,
          reason: 'xato yutib yuborilsa operator himoyasini yo\'qotganini bilmaydi');
    });
  });

  group('Sessiya DAVOMIDA holat yo\'qolsa (qobiq ustida)', () {
    testWidgets('fondan qaytganda qulf emas, TIKLASH ekrani chiqadi', (tester) async {
      // Bu yo'l `_rollbackPin` paydo bo'lgach HAQIQATAN yetib boriladigan
      // bo'ldi: PIN almashtirish yiqilib, tiklash ham o'tmasa holat seans
      // o'rtasida `unavailable` ga o'tadi.
      final be = FakeBackend()
        ..get('/auth/context', (_) => contextJson())
        ..get('/inventory/overview', (_) => {'low_count': 0, 'out_count': 0});
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111');
      Lock.relockAfter = Duration.zero;
      signIn();
      await be.run(() async {
        await Session.instance.load(force: true);
        await pumpAt390(tester, Shell(tabBuilders: {
          ShellTab.home: (_) => const Center(child: Text('HOME-TAB')),
        }));
        await tester.pumpAndSettle();
        expect(find.text('HOME-TAB'), findsOneWidget);

        // Seans o'rtasida xotira o'ladi va PIN almashtirish buziladi.
        store.writeBudget = store.writes + 1;
        await expectLater(Lock.setPin('2222'), throwsStateError);
        expect(Lock.statusKnown, isFalse, reason: 'test o\'zini sozlay olmadi');

        tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
        tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
        await tester.pumpAndSettle();
      });
      expect(find.byType(LockRecoveryScreen), findsOneWidget,
          reason: 'tekshiriladigan xesh yo\'q — PIN so\'rash boshi berk ko\'cha');
      expect(find.byType(LockScreen), findsNothing);
      // ⚠️  R5.2 dan keyin qobiq daraxtda QOLADI: qulf endi route emas, butun
      //     ilova ustidagi qatlam (`AppLockBarrier`). Shu bois tekshiriladigan
      //     narsa "ko'rinmasligi" emas, FOYDALANIB bo'lmasligi — buni
      //     `Lock.engaged` boshqaradi (`IgnorePointer`/`ExcludeFocus`), va
      //     tegish yetib bormasligi `test/lock_bypass_test.dart` da alohida
      //     o'lchanadi.
      expect(Lock.engaged.value, isTrue, reason: 'qobiq ustidagi qatlam yoqilmadi');
    });
  });

  group('HAQIQIY ilova ildizi (SavdoApp) darvozani hurmat qiladi', () {
    Future<void> pumpRoot(WidgetTester tester) async {
      await pumpAt390(tester, const SavdoApp(), wrap: false);
      await tester.pump();
    }

    testWidgets('token bor + xotira yiqilgan -> daraxtda Shell YO\'Q', (tester) async {
      // ⚠️  Bu `main.dart` ning `home:` tanlovini HAQIQATAN tekshiradigan
      //     yagona test. Manba matnini grep qilish yetarli emas edi: izoh
      //     ichidagi ko'chirma shart ham «kod» deb hisoblanardi.
      signIn();
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash});
      await Lock.load();
      await pumpRoot(tester);
      expect(find.byType(LockRecoveryScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing, reason: 'S3 qaytib keldi');
    });

    testWidgets('token bor + PIN yo\'q -> daraxtda Shell YO\'Q', (tester) async {
      signIn();
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      await pumpRoot(tester);
      expect(find.byType(PinSetupScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    testWidgets('token bor + PIN bor -> qulf ekrani, Shell YO\'Q', (tester) async {
      final pair = await _realPinPair('2468');
      signIn();
      SecretStore.instance = _FlakyStore()..map.addAll(pair);
      await Lock.load();
      await pumpRoot(tester);
      expect(find.byType(LockScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });

    testWidgets('token YO\'Q -> login ekrani', (tester) async {
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      await pumpRoot(tester);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
    });
  });

  group('Tiklash ekrani kichik ekran va KATTA yozuvda ham ishlaydi', () {
    // ⚠️  Bu ekranning yagona ikki chiqish yo'li — pastdagi tugmalar, orqaga
    //     qaytish esa `PopScope` bilan to'silgan. Matn ularni ekrandan chiqarib
    //     yuborsa, foydalanuvchi BUTUNLAY tiqilib qolardi. iOS'da yozuv o'lchami
    //     3.1x gacha ko'tariladi, eng kichik iOS 15 qurilmasi — 320x568.
    for (final size in const [Size(320, 568), Size(375, 667), Size(390, 844)]) {
      for (final scale in const [1.0, 2.0, 3.0]) {
        for (final lang in const ['uz', 'ru', 'ky']) {
          testWidgets('${size.width.toInt()}x${size.height.toInt()} @${scale}x $lang', (tester) async {
            L.code = lang;
            signIn();
            SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash});
            await Lock.load();

            tester.view.physicalSize = Size(size.width * 3, size.height * 3);
            tester.view.devicePixelRatio = 3.0;
            tester.view.padding = const FakeViewPadding(top: 60, bottom: 102);
            tester.platformDispatcher.textScaleFactorTestValue = scale;
            addTearDown(tester.view.resetPhysicalSize);
            addTearDown(tester.view.resetDevicePixelRatio);
            addTearDown(tester.view.resetPadding);
            addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

            // Overflow bo'lsa `FlutterError` otiladi va test O'ZI yiqiladi.
            await tester.pumpWidget(testApp(lockGateHome()));
            await tester.pump();

            // Ikkala chiqish yo'li ham YETIB BORILADIGAN bo'lishi kerak
            // (`ensureVisible` scroll qiladi; scroll bo'lmasa otadi).
            for (final f in [find.byType(ElevatedButton), find.byType(TextButton)]) {
              expect(f, findsOneWidget);
              await tester.ensureVisible(f);
            }

            // ⚠️  Scroll BEKORGA qo'yilmagan: shu o'lchamlarda kontent
            //     ko'rinadigan maydondan OSHADI, ya'ni scroll bo'lmasa
            //     `RenderFlex overflow` bo'lib tugmalar ekrandan chiqib
            //     ketardi. `maxScrollExtent > 0` aynan shuni o'lchaydi.
            final pos = tester.state<ScrollableState>(find.byType(Scrollable)).position;
            if (scale >= 2.0) {
              expect(pos.maxScrollExtent, greaterThan(0),
                  reason: 'kontent sig\'ib ketdi — bu holat endi overflow sinovini '
                      'tekshirmaydi, matn yoki o\'lcham o\'zgargan bo\'lsa testni yangilang');
            }
          });
        }
      }
    }
  });


  // ───────────────────────────────────────────────────────────────────────────
  // Uchinchi to'lqin: O'Z tuzatishlarim ochgan teshiklar (adversarial audit).
  group('Tuzatishning O\'ZI yangi teshik ochmasin', () {
    test('chiqish paytida yiqilgan PIN almashtirish ESKI PIN\'ni TIRILTIRMAYDI', () async {
      // ⚠️  `_rollbackPin` ishlayotgan PIN'ni saqlash uchun qo'yilgan, lekin u
      //     o'tkinchi xatoni SESSIYA TUGASHIDAN ajrata olmasdi: 401 kelib
      //     `clear()` hamma kalitni o'chirgach, tiklash chiqqan xodimning
      //     juftligini diskka QAYTA yozardi. Natijada keyingi xodimning
      //     sessiyasini chiqib ketgan xodimning PIN'i qo'riqlardi.
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111'); // xodim A
      expect(Lock.verify('1111'), isTrue);

      store.failWrite.add(SecretKeys.pinHash);
      final setting = Lock.setPin('2222');
      final thrown = expectLater(setting, throwsStateError);
      await Lock.clear(); // 401 / chiqish yozuv ORASIDA
      await thrown;

      expect(Lock.verify('1111'), isFalse, reason: 'A ning PIN\'i TIRILDI');
      expect(Lock.status, LockStatus.absent);
      expect(store.map.containsKey(SecretKeys.pinHash), isFalse,
          reason: 'egasiz PIN xeshi diskda qoldi');
      expect(store.map.containsKey(SecretKeys.pinSalt), isFalse,
          reason: 'egasiz PIN tuzi diskda qoldi');

      // Xodim B ishga tushirdi: hech kimning PIN\'i qo\'riqlamasin.
      await Lock.load();
      expect(Lock.status, LockStatus.absent);
      expect(Lock.verify('1111'), isFalse);
      signIn();
      expect(lockGateHome(), isA<MandatoryPinSetupScreen>(),
          reason: 'B o\'z PIN\'ini qo\'yishi SHART');
    });

    testWidgets('Qayta urinish PIN YO\'Q deb chiqsa — qobiq EMAS, onboarding', (tester) async {
      // ⚠️  `_retry`/`_resolve` darvoza qarorini QAYTA chiqarardi va shu sababli
      //     darvozaning `absent -> MandatoryPinSetupScreen` qoidasini chetlab
      //     o'tardi: PIN o'rnatilmagan sessiya BITTA tugma bosishda qobiqni
      //     ochardi — ya'ni tuzatilgan (c) nuqsoni (a) ning tuzatishi orqali
      //     qaytib kelardi.
      signIn();
      final store = _FlakyStore(failRead: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(LockRecoveryScreen), findsOneWidget);

      // Xotira tuzaldi, lekin saqlangan PIN YO'Q (tashlab ketilgan onboarding).
      store.failRead.clear();
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();

      expect(Lock.status, LockStatus.absent, reason: 'test o\'zini sozlay olmadi');
      expect(find.byType(Shell), findsNothing, reason: 'bitta tugma qobiqni ochdi');
      expect(find.byType(PinSetupScreen), findsOneWidget);
    });

    testWidgets('Qayta urinish qulf O\'CHIRILGAN deb chiqsa — qobiq ochiladi', (tester) async {
      // `_resolve()` ning yagona qonuniy yo'li: holat `valid`, lekin operator
      // «ochishda PIN so'ralsin» ni o'zi o'chirgan. Ilgari bu shox umuman
      // testdan o'tmagan edi.
      final pair = await _realPinPair('3141');
      signIn();
      final store = _FlakyStore(failRead: {SecretKeys.pinHash})..map.addAll(pair);
      store.map[SecretKeys.lockOn] = '0';
      SecretStore.instance = store;
      await Lock.load();
      await pumpAt390(tester, lockGateHome());
      await tester.pump();
      expect(find.byType(LockRecoveryScreen), findsOneWidget);

      store.failRead.clear();
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();

      expect(Lock.status, LockStatus.valid);
      expect(Lock.lockOn, isFalse);
      expect(find.byType(Shell), findsOneWidget, reason: 'operator tanlovini hurmat qilamiz');
    });

    testWidgets('qobiq USTIDA: PIN yo\'q deb chiqsa, qobiqqa qaytarilmaydi', (tester) async {
      // Fondan qaytish yo'li: `onResolved` berilgan. Ilgari `done()` darhol
      // `pop` qilib, foydalanuvchini qulfsiz qobiqqa qaytarardi.
      var popped = false;
      final store = _FlakyStore(failRead: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.load();
      signIn();
      await pumpAt390(tester, LockRecoveryScreen(onResolved: () => popped = true));
      await tester.pump();

      store.failRead.clear();
      await tester.tap(find.text('Qayta urinish'));
      await tester.pumpAndSettle();

      expect(Lock.status, LockStatus.absent);
      expect(popped, isFalse, reason: 'qulfsiz qobiqqa qaytarildi');
      expect(find.byType(PinSetupScreen), findsOneWidget);
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Lifecycle: fondan qaytish ham fail-closed', () {
    test('holat noma\'lum bo\'lsa consumeResume QULFLAYDI', () async {
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash});
      await Lock.load();
      Lock.debugResetBackground();
      final t0 = DateTime(2026, 10, 27, 10);
      Lock.markBackground(t0);
      expect(Lock.consumeResume(t0.add(const Duration(seconds: 1))), isTrue,
          reason: 'qisqa chiqish ham — holatni bilmaymiz, demak yopiq');
    });

    test('holat aniq va PIN yo\'q bo\'lsa qulflamaydi', () async {
      SecretStore.instance = _FlakyStore();
      await Lock.load();
      Lock.debugResetBackground();
      final t0 = DateTime(2026, 10, 27, 10);
      Lock.markBackground(t0);
      expect(Lock.consumeResume(t0.add(const Duration(hours: 1))), isFalse);
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('PIN clear/set poygasi va boshqa xodim', () {
    test('PIN o\'rnatish paytidagi 401 (clear) yarim holat qoldirmaydi', () async {
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();

      // 401 ishlovchisi `Lock.clear()` ni PIN yozuvi ORASIDA chaqiradi.
      // `expectLater` xato ishlovchisini DARHOL biriktiradi — `clear()` ni
      // kutishdan oldin, aks holda xato "unhandled" deb hisoblanadi.
      final setting = Lock.setPin('1234');
      final thrown = expectLater(setting, throwsStateError,
          reason: 'chiqish bo\'ldi — bu PIN endi hech kimga tegishli emas');
      await Lock.clear();
      await thrown;

      // Xotira va disk KELISHGAN bo'lishi shart.
      final onDisk = classifyLock(
        readOk: true,
        hash: store.map[SecretKeys.pinHash],
        salt: store.map[SecretKeys.pinSalt],
      );
      expect(onDisk, LockStatus.absent, reason: 'diskda egasiz PIN qolmasin');
      expect(Lock.hasPin, isFalse, reason: 'xotirada "PIN bor" yolg\'oni qolmasin');
      expect(Lock.status, LockStatus.absent);

      // Qayta ishga tushirish ham xuddi shunday deydi.
      await Lock.load();
      expect(Lock.status, LockStatus.absent);
    });

    test('boshqa xodim: chiqishdan keyin oldingi PIN yangi sessiyaga o\'tmaydi', () async {
      final store = _FlakyStore();
      SecretStore.instance = store;
      await Lock.clear();

      await Lock.setPin('1111'); // xodim A
      expect(Lock.verify('1111'), isTrue);

      await Lock.clear(); // chiqish / 401
      expect(store.map.containsKey(SecretKeys.pinHash), isFalse);

      await Lock.load(); // xodim B ishga tushirdi
      expect(Lock.status, LockStatus.absent);
      expect(Lock.verify('1111'), isFalse, reason: 'A ning PIN\'i B ga o\'tdi');
      signIn();
      expect(lockGateHome(), isA<MandatoryPinSetupScreen>(),
          reason: 'B o\'z PIN\'ini qo\'yishi SHART');
    });

    test('fail_count yozilmasa ham PIN tekshiruvi ishdan chiqmaydi', () async {
      final pair = await _realPinPair('5555');
      SecretStore.instance = _FlakyStore(failWrite: {SecretKeys.failCount})..map.addAll(pair);
      await Lock.load();
      // Yozuv yiqilsa ham `registerFail` otmasligi kerak — aks holda qulf
      // ekrani javob bermay qotib qolardi.
      expect(await Lock.registerFail(), isFalse);
      expect(Lock.failCount, 1, reason: 'xotiradagi eskalatsiya ishlashda davom etadi');
      expect(Lock.verify('5555'), isTrue);
    });
  });
}
