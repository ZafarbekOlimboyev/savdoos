// R5 — ILOVA QULFI (PIN) XAVFSIZ XOTIRA XATOLARIDA.
//
// ⚠️  NEGA BU TEST BOR. Qulfning ikki jim nuqsoni topildi:
//       1) `setPin` tuzni yozib, xeshni yozmay qolsa (Keychain/Keystore
//          xatosi) keyingi ishga tushishda `hasPin` false bo'lib, ilova
//          QULFSIZ ochilardi — foydalanuvchi esa PIN qo'yganiga ishonardi;
//       2) `load()` dagi yagona `try` ikkinchi darajali kalit xatosida
//          (`biometric_on` va h.k.) MUVAFFAQIYATLI o'qilgan PIN xeshini ham
//          null qilib, qulfni jimgina o'chirardi.
//     Ikkisi ham "fail-open" edi: xato qulfni KUCHSIZLANTIRARDI.
@TestOn('vm')
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';

/// Kalit bo'yicha tanlab yiqiladigan xotira (qolgan kalitlar normal ishlaydi).
class _PartialStore implements SecretStore {
  _PartialStore({this.failWrite = const {}, this.failRead = const {}});

  final Map<String, String> map = {};
  final Set<String> failWrite;
  final Set<String> failRead;

  @override
  bool get isHardwareBacked => true;

  @override
  Future<String?> read(String key) async {
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

void main() {
  final original = SecretStore.instance;
  tearDown(() async {
    SecretStore.instance = original;
    await Lock.clear();
  });

  group('setPin qisman yozuvi', () {
    test('xesh yozilmasa — diskda TUZ ham qolmaydi va xato uzatiladi', () async {
      final store = _PartialStore(failWrite: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.clear();

      await expectLater(Lock.setPin('1234'), throwsStateError);

      expect(store.map.containsKey(SecretKeys.pinSalt), isFalse,
          reason: 'yarim yozilgan tuz qolsa, holat chalkash bo‘ladi');
      expect(store.map.containsKey(SecretKeys.pinHash), isFalse);
      expect(Lock.hasPin, isFalse,
          reason: 'xotirada "qulf bor" deb ko‘rsatish YOLG‘ON bo‘lardi');
      expect(Lock.shouldLock, isFalse);
    });

    test('xato o‘rnatishdan keyin qayta yuklash ham "PIN yo‘q" deydi', () async {
      final store = _PartialStore(failWrite: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.clear();
      await expectLater(Lock.setPin('1234'), throwsStateError);

      await Lock.load();
      expect(Lock.hasPin, isFalse);
      expect(Lock.loadFailed, isFalse,
          reason: 'o‘qish ISHLADI — holat haqiqatan "PIN yo‘q"');
    });

    test('muvaffaqiyatli o‘rnatish: PIN tekshiriladi va saqlanadi', () async {
      final store = _PartialStore();
      SecretStore.instance = store;
      await Lock.clear();

      await Lock.setPin('4321');
      expect(Lock.verify('4321'), isTrue);
      expect(Lock.verify('1234'), isFalse);

      await Lock.load(); // sovuq ishga tushish
      expect(Lock.hasPin, isTrue);
      expect(Lock.shouldLock, isTrue);
      expect(Lock.verify('4321'), isTrue);
      expect(Lock.loadFailed, isFalse);
    });
  });

  group('load() xatolarni ajratadi', () {
    test('IKKINCHI DARAJALI kalit xatosi PIN ni o‘chirmaydi', () async {
      final store = _PartialStore();
      SecretStore.instance = store;
      await Lock.clear();
      await Lock.setPin('1111');

      // Endi faqat `biometric_on` yiqiladi (Keystore'ning bitta yozuvi buzilgan).
      final broken = _PartialStore(failRead: {SecretKeys.biometricOn})
        ..map.addAll(store.map);
      SecretStore.instance = broken;
      await Lock.load();

      expect(Lock.hasPin, isTrue,
          reason: 'biometrika kaliti xatosi QULFNI o‘chirib yuborardi');
      expect(Lock.shouldLock, isTrue);
      expect(Lock.verify('1111'), isTrue);
      expect(Lock.biometricOn, isFalse, reason: 'o‘qilmagan — fail-closed');
      expect(Lock.loadFailed, isFalse, reason: 'PIN kalitlari o‘qildi');
    });

    test('PIN kaliti o‘qilmasa — loadFailed OSHKOR qilinadi', () async {
      final store = _PartialStore(failRead: {SecretKeys.pinHash});
      SecretStore.instance = store;
      await Lock.clear();

      await Lock.load();
      expect(Lock.loadFailed, isTrue,
          reason: '"PIN yo‘q" va "o‘qib bo‘lmadi" BIR XIL emas');
      expect(Lock.hasPin, isFalse);
    });

    test('hamma kalit yiqilsa ham load() otmaydi va qulf yoqilgan qoladi', () async {
      SecretStore.instance = _PartialStore(failRead: {
        SecretKeys.pinHash,
        SecretKeys.pinSalt,
        SecretKeys.biometricOn,
        SecretKeys.lockOn,
        SecretKeys.failCount,
        SecretKeys.lockUntil,
      });
      await Lock.load();
      expect(Lock.loadFailed, isTrue);
      expect(Lock.lockOn, isTrue, reason: 'lock_on o‘qilmasa standart = yoqilgan');
      expect(Lock.failCount, 0);
    });
  });
}
