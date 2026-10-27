// R5.2 — QULF CHETLAB O'TILMASIN (P0).
//
// ⚠️  NEGA BU TEST BOR. Fondan qaytgandagi qulf ODDIY Navigator route sifatida
//     push qilinadi (`shell.dart` `_showLock`). Ya'ni qulf ostidagi ekranlar
//     MOUNT bo'lib qolaveradi: ularning kamera oqimi, taymerlari va async
//     davomlari ishlashda davom etadi. `PopScope(canPop: false)` faqat tizim
//     "orqaga" ishorasini to'sadi — programmali `Navigator.pop()` ni EMAS, va
//     qulf ostidagi kod YANGI route'ni qulf USTIGA push qila oladi.
//
//     Aniq topilma: `barcode_scan_screen.dart` `_deliver` da `isCurrent`
//     qorovuli FAQAT bitta-martalik shoxda bor (`!widget.continuous`), uzluksiz
//     ("Ketma-ket sanash") shoxda esa YO'Q — u faqat `mounted` va `_done` ni
//     tekshiradi. Shu bois qulf ko'ringandan keyin ham kamera kodni yetkazadi,
//     `GET /products/scan` AUTHENTICATED so'rovi ketadi va natija varaqasi
//     qulf USTIGA chiqadi.
//
//     Egasining talabi: "Faqat vizual overlay qo'yib, fondagi biznes amallarini
//     ishlashda qoldirma." Shu bois bu test holat qiymatini emas, AMALLARNI
//     tekshiradi: so'rov ketdimi, route push bo'ldimi, natija yetkazildimi.
@TestOn('vm')
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/lock.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/screens/lock_recovery_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

/// Kamera OQIMI: kadr test tomonidan [emit] bilan yuboriladi, tegish ORQALI
/// emas. Qulf ostida tegish baribir yetib bormaydi — haqiqiy xavf esa aynan
/// oqimning o'zi ishlab turishi.
class _StreamCamera {
  void Function(String)? _sink;

  ScannerViewBuilder get build => (ctx, onCode, errorView) {
        _sink = onCode;
        return const SizedBox.expand();
      };

  bool get attached => _sink != null;

  void emit(String code) {
    final s = _sink;
    if (s == null) throw StateError('kamera hali ulanmagan');
    s(code);
  }
}

/// `/products/scan` javobi — bu testga yetarli minimal shakl (fixture fayliga
/// bog'lanmaslik uchun joyida qurilgan).
Map<String, dynamic> _scanReply({String code = '4780001'}) => {
      'code': code,
      'kind': 'barcode',
      'product': {
        'id': 'p1',
        'name': 'Sut',
        'unit_code': 'dona',
        'stock': 5,
        'min_stock': 0,
        'base_sell_price': 15000,
        'base_buy_price': 12000,
        'is_active': true,
        'tracked': false,
      },
      'candidates': <Map<String, dynamic>>[],
      'scale': null,
    };

/// PIN kalitlarini o'qiy olmaydigan xotira — holatni `unavailable` qiladi.
class _ReadDownStore implements SecretStore {
  final Map<String, String> map = {};

  @override
  bool get isHardwareBacked => true;

  @override
  Future<String?> read(String key) async {
    if (key == SecretKeys.pinHash || key == SecretKeys.pinSalt) {
      throw StateError('read down: $key');
    }
    return map[key];
  }

  @override
  Future<void> write(String key, String value) async => map[key] = value;

  @override
  Future<void> delete(String key) async => map.remove(key);
}

Map<ShellTab, WidgetBuilder> _tabs(Widget home) => {
      ShellTab.home: (_) => home,
      ShellTab.stock: (_) => const Center(child: Text('STOCK-TAB')),
      ShellTab.analytics: (_) => const Center(child: Text('ANALYTICS-TAB')),
    };

/// Fon -> oldinga: `shell.dart` shu yerda qulfni ko'rsatadi.
Future<void> backgroundAndResume(WidgetTester t) async {
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  await t.pumpAndSettle();
}

void main() {
  late FakeBackend be;
  final s = Session.instance;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get('/auth/context', (_) => contextJson(role: 'ega'))
      ..get('/inventory/overview', (_) => {'low_count': 0, 'out_count': 0});
    await Lock.clear();
    Lock.relockAfter = const Duration(minutes: 3);
    Lock.debugResetBackground();
  });

  tearDown(() async {
    s.debugReset();
    Lock.relockAfter = const Duration(minutes: 3);
    await Lock.clear();
  });

  group('Uzluksiz skaner qulf ostida', () {
    testWidgets('qulf ko\'ringach kod yetkazilmaydi va API chaqirilmaydi', (t) async {
      final cam = _StreamCamera();
      final delivered = <String>[];
      be.get('/products/scan', (_) => _scanReply());

      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero; // har qanday fonga chiqish qulflaydi
        signIn(role: 'ega');
        await s.load(force: true);

        await pumpAt390(
          t,
          Shell(
            tabBuilders: _tabs(BarcodeScanScreen.lookup(
              continuous: true,
              scannerBuilder: cam.build,
              onResult: (r) async {
                delivered.add(r.code);
                return null;
              },
            )),
          ),
        );
        await t.pumpAndSettle();
        expect(cam.attached, isTrue, reason: 'kamera ulanmadi — test o\'zini sozlay olmadi');

        // Qulf chiqadi.
        await backgroundAndResume(t);
        expect(find.byType(LockScreen), findsOneWidget, reason: 'qulf chiqmadi');

        // Kamera oqimi qulf ostida ishlashda davom etadi va kadr keladi.
        cam.emit('4780001');
        await t.pumpAndSettle();
      });

      // ⚠️  ASOSIY TASDIQLAR — amallar, holat emas.
      expect(be.calls('GET', '/products/scan'), isEmpty,
          reason: 'qulflangan ilovadan AUTHENTICATED so\'rov ketdi');
      expect(delivered, isEmpty, reason: 'natija qulf ostidagi ekranga yetkazildi');
      expect(find.byType(LockScreen), findsOneWidget, reason: 'qulf ustiga boshqa ekran chiqdi');
    });

    testWidgets('qulf ochilgach skaner normal ishlaydi (regressiya)', (t) async {
      final cam = _StreamCamera();
      final delivered = <String>[];
      be.get('/products/scan', (_) => _scanReply());

      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero;
        signIn(role: 'ega');
        await s.load(force: true);

        await pumpAt390(
          t,
          Shell(
            tabBuilders: _tabs(BarcodeScanScreen.lookup(
              continuous: true,
              scannerBuilder: cam.build,
              onResult: (r) async {
                delivered.add(r.code);
                return null;
              },
            )),
          ),
        );
        await t.pumpAndSettle();

        await backgroundAndResume(t);
        expect(find.byType(LockScreen), findsOneWidget);

        // To'g'ri PIN -> qulf yopiladi.
        for (final d in '2468'.split('')) {
          await t.tap(find.text(d).last);
          await t.pump();
        }
        await t.pumpAndSettle();
        expect(find.byType(LockScreen), findsNothing, reason: 'qulf ochilmadi');

        cam.emit('4780001');
        await t.pumpAndSettle();
      });

      expect(be.calls('GET', '/products/scan'), hasLength(1),
          reason: 'qulf ochilgandan keyin skaner ishlashi SHART');
      expect(delivered, ['4780001']);
    });
  });

group('Qulf ostidan navigatsiya (struktura zondlari)', () {
    /// Qulf ostidagi ekranga `BuildContext` beradi, keyin o'sha context bilan
    /// navigatsiya qilib ko'ramiz — aynan async davom/taymer qiladigan ish.
    testWidgets('ZOND: qulf ostidagi kod push qilgan route FOYDALANIB BO`LMAYDI', (t) async {
      // ⚠️  Qulf endi Navigator'dan YUQORIDA, shuning uchun push qilingan route
      //     daraxtda bo'lishi MUMKIN — lekin u qulf OSTIDA qoladi. Shu bois
      //     tekshiriladigan narsa daraxtda bor-yo'qligi emas, FOYDALANIB
      //     bo'ladimi-yo'qmi: tegish yetib boradimi va qulf hanuz talab
      //     qilmoqdami.
      BuildContext? under;
      var pushedTaps = 0;
      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero;
        signIn(role: 'ega');
        await s.load(force: true);
        await pumpAt390(
          t,
          Shell(tabBuilders: _tabs(Builder(builder: (ctx) {
            under = ctx;
            return const Center(child: Text('UNDER'));
          }))),
        );
        await t.pumpAndSettle();
        await backgroundAndResume(t);
        expect(find.byType(LockScreen), findsOneWidget);

        Navigator.of(under!, rootNavigator: true).push(MaterialPageRoute<void>(
          builder: (_) => Scaffold(
            body: Center(
              child: ElevatedButton(
                key: const Key('above-lock-action'),
                onPressed: () => pushedTaps++,
                child: const Text('QULF-USTIDA'),
              ),
            ),
          ),
        ));
        await t.pumpAndSettle();

        final btn = find.byKey(const Key('above-lock-action'));
        if (btn.evaluate().isNotEmpty) {
          await t.tap(btn, warnIfMissed: false);
          await t.pumpAndSettle();
        }
      });

      expect(pushedTaps, 0, reason: 'qulf ustiga chiqqan ekran ISHLATILDI');
      expect(Lock.engaged.value, isTrue, reason: 'qulf talab qilishni to`xtatdi');
      expect(find.byType(LockScreen), findsOneWidget, reason: 'qulf ekrani yo`qoldi');
    });

    testWidgets('ZOND: qulf ostidagi kod qulfni POP qila oladimi', (t) async {
      BuildContext? under;
      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero;
        signIn(role: 'ega');
        await s.load(force: true);
        await pumpAt390(
          t,
          Shell(tabBuilders: _tabs(Builder(builder: (ctx) {
            under = ctx;
            return const Center(child: Text('UNDER'));
          }))),
        );
        await t.pumpAndSettle();
        await backgroundAndResume(t);
        expect(find.byType(LockScreen), findsOneWidget);

        // `PopScope(canPop:false)` programmali pop'ni TO'SMAYDI.
        Navigator.of(under!, rootNavigator: true).pop();
        await t.pumpAndSettle();
      });
      expect(find.byType(LockScreen), findsOneWidget,
          reason: 'qulf ostidagi kod qulfni YO`Q QILDI');
      expect(Lock.engaged.value, isTrue, reason: 'qulf bayrog`i o`chirildi');
    });
  });

// ───────────────────────────────────────────────────────────────────────────
  // Qulf endi qatlam bo'lgani uchun eng xavfli joy — undan CHIQISH yo'llari.
  // Egasining talabi: "Login, majburiy PIN onboarding, recovery, logout va
  // account switching oqimlarini buzma."
  group('Qulf qatlamidan chiqish yo\'llari', () {
    Future<void> engageLock(WidgetTester t, {String pin = '2468'}) async {
      await Lock.setPin(pin);
      Lock.relockAfter = Duration.zero;
      signIn(role: 'ega');
      await s.load(force: true);
      await pumpAt390(t, Shell(tabBuilders: _tabs(const Center(child: Text('HOME-TAB')))));
      await t.pumpAndSettle();
      await backgroundAndResume(t);
      expect(find.byType(LockScreen), findsOneWidget, reason: 'qulf chiqmadi');
      expect(Lock.engaged.value, isTrue);
    }

    testWidgets('to\'g\'ri PIN qatlamni yopadi va qobiqqa qaytaradi', (t) async {
      await be.run(() async {
        await engageLock(t);
        for (final d in '2468'.split('')) {
          await t.tap(find.text(d).last);
          await t.pump();
        }
        await t.pumpAndSettle();
      });
      expect(Lock.engaged.value, isFalse, reason: 'qatlam yopilmadi');
      expect(find.byType(LockScreen), findsNothing);
      expect(find.text('HOME-TAB'), findsOneWidget, reason: 'operator qayerda qolgan bo`lsa — o`sha yerda');
    });

    testWidgets('noto\'g\'ri PIN qatlamni YOPMAYDI', (t) async {
      await be.run(() async {
        await engageLock(t);
        for (final d in '1111'.split('')) {
          await t.tap(find.text(d).last);
          await t.pump();
        }
        await t.pumpAndSettle();
      });
      expect(Lock.engaged.value, isTrue);
      expect(find.byType(LockScreen), findsOneWidget);
    });

    testWidgets('qulfdan "Chiqish" LOGIN ekraniga olib boradi (qatlam ICHIGA emas)', (t) async {
      // ⚠️  Qulf qatlamining O'Z navigatori bor (modal varaqlar uchun). Agar
      //     chiqish mahalliy navigatorga push qilsa, login ekrani qulf ICHIDA
      //     paydo bo'lardi va `engaged=false` bo'lgach butunlay yo'qolardi.
      be.post('/auth/logout', (_) => {'ok': true});
      await be.run(() async {
        await engageLock(t);
        await t.tap(find.text('Chiqish'));
        await flushIo(t);
        await flushIo(t);
      });
      expect(find.byType(LoginScreen), findsOneWidget, reason: 'login ekrani ko`rinmadi');
      expect(Lock.engaged.value, isFalse, reason: 'qatlam ochiq qoldi — login ekrani ostida');
      expect(Api.token, isNull);
      expect(Lock.hasPin, isFalse, reason: 'chiqishda PIN ham tozalanishi kerak');
    });

    testWidgets('account switch: A chiqadi, B majburiy PIN onboarding oladi', (t) async {
      be.post('/auth/logout', (_) => {'ok': true});
      await be.run(() async {
        await engageLock(t, pin: '1111'); // xodim A
        await t.tap(find.text('Chiqish'));
        await flushIo(t);
        await flushIo(t);
      });
      expect(find.byType(LoginScreen), findsOneWidget);

      // Xodim B kiradi (parol bilan) — A ning PIN'i o`tmasligi SHART.
      expect(Lock.verify('1111'), isFalse, reason: 'A ning PIN`i B ga o`tdi');
      signIn(role: 'ega', id: 'e2', fullName: 'Boshqa Xodim');
      expect(lockGateHome(), isA<MandatoryPinSetupScreen>(),
          reason: 'B o`z PIN`ini qo`yishi SHART');
    });

    testWidgets('401 qulf qatlamini YOPADI — login ekrani uning ostida qolmaydi', (t) async {
      await be.run(() async {
        await engageLock(t);
        // 401: `Api` tokenni tozalaydi va `onSessionExpired` ishga tushadi.
        // `Lock.clear()` qatlamni ham yopishi kerak.
        await Lock.clear();
        await t.pumpAndSettle();
      });
      expect(Lock.engaged.value, isFalse,
          reason: 'qatlam ochiq qolsa, login ekrani uning OSTIDA ko`rinmas bo`lardi');
    });

    testWidgets('tiklash ekranidagi TASDIQ varaqasi qatlam ichida ishlaydi', (t) async {
      // ⚠️  `confirmDestructive` -> `showModalBottomSheet` Navigator talab
      //     qiladi. Qatlam ilova Navigator'idan yuqorida, shuning uchun unga
      //     O'Z navigatori berilgan. Bu test aynan shuni tekshiradi.
      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero;
        signIn(role: 'ega');
        await s.load(force: true);
        await pumpAt390(t, Shell(tabBuilders: _tabs(const Center(child: Text('HOME-TAB')))));
        await t.pumpAndSettle();

        // Holatni NOMA'LUM qilamiz -> qatlamda tiklash ekrani chiqadi.
        SecretStore.instance = _ReadDownStore();
        await Lock.load();
        await backgroundAndResume(t);
        expect(find.byType(LockRecoveryScreen), findsOneWidget, reason: 'tiklash ekrani chiqmadi');

        await t.tap(find.text('Parol bilan kirish'));
        await t.pumpAndSettle();
      });
      // Tasdiq varaqasi ochilishi SHART (aks holda chiqish yo`li yo`q).
      expect(find.byKey(const Key('confirm-no')), findsOneWidget,
          reason: 'tasdiq varaqasi qatlam ichida ochilmadi');
    });
  });

  group('Qulf ostidagi interfeys FAOL emas', () {
    testWidgets('qulf ostidagi tugma tegishga javob bermaydi', (t) async {
      var taps = 0;
      await be.run(() async {
        await Lock.setPin('2468');
        Lock.relockAfter = Duration.zero;
        signIn(role: 'ega');
        await s.load(force: true);

        await pumpAt390(
          t,
          Shell(
            tabBuilders: _tabs(Center(
              child: ElevatedButton(
                key: const Key('protected-action'),
                onPressed: () => taps++,
                child: const Text('HIMOYALANGAN AMAL'),
              ),
            )),
          ),
        );
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key('protected-action')));
        await t.pumpAndSettle();
        expect(taps, 1, reason: 'qulfsiz holatda tugma ishlashi kerak');

        await backgroundAndResume(t);
        expect(find.byType(LockScreen), findsOneWidget);

        // Qulf ostidagi tugmani "bosishga" urinamiz.
        final btn = find.byKey(const Key('protected-action'));
        if (btn.evaluate().isNotEmpty) {
          await t.tap(btn, warnIfMissed: false);
          await t.pumpAndSettle();
        }
      });
      expect(taps, 1, reason: 'qulf ostidagi himoyalangan amal BAJARILDI');
    });
  });
}
