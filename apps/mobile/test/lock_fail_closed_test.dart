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
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/lock_recovery_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/shell.dart';

import 'support/support.dart';

/// Kalit bo'yicha tanlab yiqiladigan xotira (qolgan kalitlar normal ishlaydi).
/// [failRead]/[failWrite] ni test o'rtasida o'zgartirish mumkin — "xotira
/// tuzaldi" holatini shu bilan modellaymiz.
class _FlakyStore implements SecretStore {
  _FlakyStore({Set<String>? failRead, Set<String>? failWrite})
      : failRead = {...?failRead},
        failWrite = {...?failWrite};

  final Map<String, String> map = {};
  final Set<String> failRead;
  final Set<String> failWrite;
  int reads = 0;

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
    if (failWrite.contains(key)) throw StateError('write down: $key');
    map[key] = value;
  }

  @override
  Future<void> delete(String key) async => map.remove(key);
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

    test('absent -> qobiq (qonuniy PIN onboarding buzilmaydi)', () async {
      await withState(LockStatus.absent);
      expect(lockGateHome(), isA<Shell>());
    });

    test('qulf o\'chirilgan + valid -> qobiq', () async {
      await withState(LockStatus.valid);
      await Lock.setLockEnabled(false);
      expect(lockGateHome(), isA<Shell>());
    });

    test('QULF O\'CHIRILGAN BO\'LSA HAM noma\'lum holat qobiqni ochmaydi', () async {
      // Operator "ochishda PIN so'ralsin" ni o'chirgan, keyin xotira yiqildi:
      // `lock_on` ni ham o'qib bo'lmaydi, ya'ni o'chirilganini BILMAYMIZ.
      SecretStore.instance = _FlakyStore(failRead: {SecretKeys.pinHash, SecretKeys.lockOn});
      await Lock.load();
      expect(lockGateHome(), isA<LockRecoveryScreen>());
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  group('Manba darvozasi (RATCHET)', () {
    test('main.dart uyni O\'ZI qulf shartidan tanlamaydi', () {
      // S3 aynan shu yerda tug'ilgan edi: `Lock.shouldLock ? LockScreen : Shell`.
      // Darvoza `lockGateHome()` da bo'lishi SHART — u `statusKnown` ni ham
      // hisobga oladi va shu bilan tiklash ekranini qo'shadi.
      final src = File('lib/main.dart').readAsStringSync();
      expect(src.contains('lockGateHome()'), isTrue,
          reason: 'darvoza funksiyasi ishlatilmagan');
      expect(src.contains('Lock.shouldLock ?'), isFalse,
          reason: 'uy to\'g\'ridan-to\'g\'ri `shouldLock` dan tanlanmasin — S3 qaytadi');
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
      await pumpBlocked(tester);
      final store = SecretStore.instance as _FlakyStore;
      expect(Api.token, isNotNull, reason: 'token o\'tkinchi xato sabab o\'chirilmaydi');
      expect(store.map.containsKey(SecretKeys.pinHash), isFalse,
          reason: 'bu testda xesh hech yozilmagan');
      // Ekran ochilishining O'ZI hech narsani o'chirmasligi kerak:
      await tester.pump(const Duration(seconds: 2));
      expect(Api.token, isNotNull);
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
        // Chiqish diskdagi eski katalog keshini ham tozalaydi — HAQIQIY IO.
        await flushIo(tester);
        await flushIo(tester);
      });
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.byType(Shell), findsNothing);
      expect(Api.token, isNull, reason: 'bu FOYDALANUVCHI tanlagan chiqish');
      expect(Lock.status, LockStatus.absent);
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
        await flushIo(tester);
        await flushIo(tester);
      });
      expect(find.byType(Shell), findsNothing);
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(Api.token, isNull, reason: 'oflayn bo\'lsa ham lokal chiqish bajariladi');
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
      expect(lockGateHome(), isA<Shell>(), reason: 'B parol bilan kirib, o\'z PIN\'ini qo\'yadi');
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
