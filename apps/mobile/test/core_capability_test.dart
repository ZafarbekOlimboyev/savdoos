// PHASE 5G.1 / C3 — SERVER QOBILIYAT DARAJASI va MIJOZ MOSLIK DARVOZASI.
//
// Bu yerdagi soxta backend AYNAN production `99b1da7` kabi javob beradi
// (o'lchangan, `cors_probe_findings.md` + `audit_security_compat.md` §4):
//
//   * `GET /health`                       → 200, lekin `api` BLOKI YO'Q  → level 0
//   * `GET /auth/context`                 → 404
//   * `GET /products/scan`                → 422 (prod'da `/products/{uuid}` soyalaydi)
//   * `GET /products?limit&offset`        → butun katalog, `X-Total-Count` YO'Q
//   * `GET /sales/{id}/receipt`           → 404
//   * `POST /receiving/{id}/corrections`  → 404 … LEKIN bu sinovda ATAYLAB 200:
//     «yozuv serverga umuman YETIB BORMASIN» invariantini 404 yashirib qo'ymasin.
//
// ASOSIY INVARIANT (audit AU-6 §4.3): yetishmayotgan qobiliyat FAQAT tugmani
// olib tashlashi yoki tushuntirish ko'rsatishi mumkin. U hech qachon yozuvni
// «muvaffaqiyat» ga aylantirmaydi va hech qachon tugamaydigan tsikl qoldirmaydi.
@TestOn('vm')
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/errors.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/session.dart';

import 'support/support.dart';

// ── Soxta serverlar ─────────────────────────────────────────────────────────

/// Bugungi server: `/health` qobiliyat darajasini E'LON QILADI.
Map<String, dynamic> healthCurrent({int level = 1, List<String>? features}) => {
      'status': 'ok',
      'service': 'savdoos-server',
      'build': {'commit': null, 'environment': 'staging', 'platform_environment': null},
      'api': {
        'level': level,
        'features': features ??
            const [
              'auth_context',
              'cash_custody_preview',
              'error_codes',
              'products_paging',
              'products_scan',
              'receiving_corrections',
              'sale_receipt',
            ],
      },
    };

/// Production `99b1da7`: javob bor, `api` bloki YO'Q.
Map<String, dynamic> healthLegacy() => {
      'status': 'ok',
      'service': 'savdoos-server',
      'build': {
        'commit': '99b1da76cfa7d6fcd2144243a0f158e0edd5e265',
        'environment': 'production',
        'platform_environment': 'production',
      },
    };

/// 7 ta mahsulot — «katalog». Prod `limit`/`offset` ni E'TIBORSIZ qoldiradi va
/// `X-Total-Count` yubormaydi.
List<Map<String, dynamic>> _catalog() =>
    [for (var i = 0; i < 7; i++) {'id': 'p$i', 'name': 'Tovar $i'}];

/// Prod kabi javob beradigan backend.
FakeBackend legacyBackend() {
  final be = FakeBackend()
    ..get('/health', (_) => healthLegacy())
    ..get('/auth/context', (_) => FakeResponse.error(404, 'Not Found'))
    // Prod'da `/products/{product_id}` (uuid) «scan» segmentini ushlaydi → 422.
    ..get('/products/scan', (_) => FakeResponse.error(422, [
          {'msg': 'Input should be a valid UUID', 'loc': ['path', 'product_id']}
        ]))
    ..get('/products', (_) => _catalog())
    ..get('/cash/custody-preview', (_) => FakeResponse.error(404, 'Not Found'))
    ..get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Not Found'))
    // ⚠️  ATAYLAB 200: agar darvoza ishlamasa, yozuv serverga yetib borgani va
    //     ekranga «bajarildi» qaytgani KO'RINSIN (404 buni yashirardi).
    ..post('/receiving/{id}/corrections', (_) => {'id': 'c1', 'ok': true});
  return be;
}

/// Bugungi server kabi javob beradigan backend.
FakeBackend currentBackend() {
  final be = FakeBackend()
    ..get('/health', (_) => healthCurrent())
    ..get('/auth/context', (_) => contextJson())
    ..get('/products/scan', (_) => {'product': null, 'code': '123'})
    ..get(
        '/products',
        (r) => FakeResponse.json(_catalog().take(int.parse(r.query['limit'] ?? '50')).toList(),
            headers: {'x-total-count': '7'}))
    ..post('/receiving/{id}/corrections', (_) => {'id': 'c1', 'ok': true});
  return be;
}

/// Server bilan GAPIRMAYDIGAN manzil (`/health` ham yo'q) — «noma'lum» holat.
FakeBackend strangerBackend() => FakeBackend()
  ..get('/auth/context', (_) => FakeResponse.error(404, 'Not Found'));

/// Repo ildizi (sinov `apps/mobile` dan ishga tushadi).
Directory _repoRoot() {
  var d = Directory.current;
  for (var i = 0; i < 6; i++) {
    if (File('${d.path}/apps/server/app/core/api_capabilities.py').existsSync()) return d;
    d = d.parent;
  }
  fail('repo ildizi topilmadi (apps/server/app/core/api_capabilities.py)');
}

void main() {
  setUp(() async {
    await resetCore();
    // ⚠️  `resetCore` qobiliyat keshini bilmaydi (u `support/support.dart` —
    //     boshqa paket egasida). Shu bois shu yerda ochiq tozalanadi, aks holda
    //     bir sinovda probe qilingan daraja keyingisiga oqib o'tardi.
    Api.debugResetCapabilities();
  });

  tearDown(() {
    Session.instance.debugReset();
    Api.debugResetCapabilities();
  });

  // ══ 1. SKANER: eski serverda operator AYBLANMAYDI ════════════════════════
  //
  // Prod'da `/products/scan` 422 beradi va mijoz «Ma'lumotlar noto'g'ri
  // to'ldirilgan» deydi — ya'ni KASSIRNI aybdor qiladi, aslida SERVER eski.
  test('scan on an old server: the message blames the SERVER, and 422 never reaches the operator',
      () async {
    final be = legacyBackend();
    signIn();
    Object? err;
    await be.run(() async {
      try {
        await Api.getJson('/products/scan', query: {'code': '4780000000001'});
      } catch (e) {
        err = e;
      }
    });
    expect(err, isNotNull, reason: 'skaner eski serverda muvaffaqiyat qaytarmasin');
    final msg = userMessage(err);
    expect(msg, contains('Server eski'), reason: 'operator aybdor qilinmaydi — server eski');
    expect(msg, isNot(contains('Ma’lumotlar noto‘g‘ri')));
    expect(be.calls('GET', '/products/scan'), hasLength(1),
        reason: 'o‘qish YUBORILADI — aks holda shu marshrutga EGA, lekin darajasini '
            'e’lon qilmagan server (33ea7b1) da skaner bekordan ishlamay qolardi');
  });

  // ══ 2. YOZUV: yetishmayotgan qobiliyat yozuvni MUVAFFAQIYATGA aylantirmaydi ═
  test('a missing capability never turns a write into a success', () async {
    final be = legacyBackend();
    signIn();
    Object? ok;
    Object? err;
    await be.run(() async {
      try {
        ok = await Api.postJson('/receiving/r1/corrections', {'client_uuid': 'u1', 'lines': []});
      } catch (e) {
        err = e;
      }
    });
    expect(ok, isNull, reason: 'server 200 bersa ham mijoz yozuvni yubormasligi kerak edi');
    expect(err, isNotNull);
    expect(userMessage(err), contains('Server eski'));
    expect(be.calls('POST', '/receiving/r1/corrections'), isEmpty,
        reason: 'yozuv serverga YETIB BORMASIN');
  });

  // ══ 3. SAHIFALASH: tugamaydigan tsikl QOLMAYDI ═══════════════════════════
  //
  // Prod `limit` ni e'tiborsiz qoldiradi va `X-Total-Count` yubormaydi, ya'ni
  // «yana yuklash» har safar O'SHA qatorlarni qaytarib qo'shib boraveradi.
  test('paged /products on an old server terminates instead of appending duplicates forever',
      () async {
    final be = legacyBackend();
    signIn();
    final items = <String>[];
    var pages = 0;
    Object? err;
    // `stock_api.dart` dagi AYNAN shu qoida: `hasMore = items.length >= limit`
    // (jami son bo'lmasa). Katalog `limit` dan KATTA — eski serverda bu shart
    // hech qachon `false` bo'lmaydi.
    const limit = 5;
    await be.run(() async {
      var offset = 0;
      while (pages < 20) {
        pages++;
        try {
          final res = await Api.getJson('/products', query: {'limit': limit, 'offset': offset});
          final list = res.list;
          items.addAll([for (final e in list) '${(e as Map)['id']}']);
          final total = res.totalCount;
          final hasMore = total == null ? list.length >= limit : items.length < total;
          if (!hasMore) break;
          offset += limit;
        } catch (e) {
          err = e;
          break;
        }
      }
    });
    expect(err, isNotNull, reason: 'sahifalanmaydigan serverda sahifali so‘rov to‘silishi kerak');
    expect(userMessage(err), contains('Server eski'));
    expect(pages, 1, reason: 'birinchi urinishdayoq to‘xtaydi');
    expect(items, isEmpty, reason: 'takroriy qatorlar umuman qo‘shilmaydi');
    expect(items.length, items.toSet().length);
  });

  // ══ 4. SESSIYA: `/auth/context` yo'q → degraded, 404 SO'RALMAYDI ═════════
  test('no /auth/context: the session degrades on the ANSWER, not on a missing declaration',
      () async {
    final be = legacyBackend();
    signIn(role: 'omborchi', permissions: ['ombor.edit']);
    await be.run(() async {
      await Session.instance.load(force: true);   // 1-urinish: darvoza hali bilmaydi
      await Session.instance.load(force: true);   // 2-urinish: daraja ma'lum
    });
    expect(Session.instance.status, SessionStatus.degraded);
    // Login suratidan ruxsatlar ishlaydi (ilova ishga tushmay qolmaydi).
    expect(Session.instance.can('ombor.edit'), isTrue);
    expect(userMessage(Session.instance.lastError), contains('Server eski'));
    expect(be.calls('GET', '/auth/context'), isNotEmpty,
        reason: 'o‘qish yuboriladi; JAVOB (404) darajani ko‘rsatadi, e’lonning yo‘qligi emas');
  });

  // ══ 5. QOLGAN TO'SILGAN OQIMLAR ══════════════════════════════════════════
  test('custody preview and the receipt are blocked with the SAME localized reason', () async {
    final be = legacyBackend();
    signIn();
    final errors = <Object?>[];
    await be.run(() async {
      for (final p in ['/cash/custody-preview', '/sales/s1/receipt']) {
        try {
          await Api.getJson(p);
        } catch (e) {
          errors.add(e);
        }
      }
    });
    expect(errors.length, 2);
    for (final e in errors) {
      expect(userMessage(e), kServerOutdatedMessage);
      expect((e as ApiException).code, kServerCapabilityMissing);
    }
    expect(be.calls('GET', '/cash/custody-preview'), hasLength(1));
    expect(be.calls('GET', '/sales/s1/receipt'), hasLength(1));
  });

  // ══ 6. YANGI SERVER: hech narsa to'silmaydi ══════════════════════════════
  test('against a current server every gated flow runs unchanged', () async {
    final be = currentBackend();
    signIn();
    late ServerCapabilities caps;
    await be.run(() async {
      caps = await Api.ensureCapabilities();
      await Session.instance.load(force: true);
      await Api.getJson('/products/scan', query: {'code': '123'});
      await Api.getJson('/products', query: {'limit': 5, 'offset': 0});
      await Api.postJson('/receiving/r1/corrections', {'client_uuid': 'u1'});
    });
    expect(caps.known, isTrue);
    expect(caps.level, 1);
    for (final f in ServerFeature.all) {
      expect(caps.supports(f), isTrue, reason: f);
    }
    expect(Session.instance.status, SessionStatus.ready);
    expect(be.calls('GET', '/products/scan'), hasLength(1));
    expect(be.calls('POST', '/receiving/r1/corrections'), hasLength(1));
  });

  test('a NEWER server (higher level, unknown extra features) is not gated either', () async {
    final be = currentBackend()
      ..get('/health', (_) => healthCurrent(level: 9, features: [...ServerFeature.all, 'offline_queue_v3']));
    signIn();
    late ServerCapabilities caps;
    await be.run(() async {
      caps = await Api.ensureCapabilities();
      await Api.getJson('/products/scan', query: {'code': '123'});
    });
    expect(caps.level, 9);
    expect(caps.missing(ServerFeature.productsScan), isFalse);
    expect(be.calls('GET', '/products/scan'), hasLength(1));
  });

  // ══ 7. DARVOZA FAQAT OLIB TASHLAYDI — HECH QACHON O'YLAB TOPMAYDI ════════
  test('an unreadable /health gates NOTHING (the server still decides)', () async {
    final be = strangerBackend();   // `/health` marshruti umuman yo'q -> 404
    signIn();
    late ServerCapabilities caps;
    Object? err;
    await be.run(() async {
      caps = await Api.ensureCapabilities();
      try {
        await Api.getJson('/auth/context');
      } catch (e) {
        err = e;
      }
    });
    expect(caps.known, isFalse, reason: 'javobni o‘qiy olmadik — hech narsa bilmaymiz');
    expect(caps.missing(ServerFeature.authContext), isFalse);
    expect(be.calls('GET', '/auth/context'), hasLength(1), reason: 'so‘rov YUBORILADI');
    expect((err as ApiException).status, 404, reason: 'serverning O‘Z javobi keladi');
    expect(userMessage(err), isNot(contains('Server eski')));
  });

  test('offline never becomes "the server is old"', () async {
    final be = legacyBackend()..offline = true;
    signIn();
    Object? err;
    await be.run(() async {
      try {
        await Api.getJson('/products/scan', query: {'code': '1'});
      } catch (e) {
        err = e;
      }
    });
    expect(isConnectivityError(err), isTrue);
    expect(userMessage(err), startsWith('Server bilan aloqa yo‘q'));
    expect(Api.capabilities.value.known, isFalse);
  });

  test('a transport failure is not cached; an answer is', () async {
    final down = legacyBackend()..offline = true;
    signIn();
    await down.run(() async {
      await Api.ensureCapabilities();
      await Api.ensureCapabilities();
    });
    expect(down.calls('GET', '/health'), hasLength(2), reason: 'aloqa yo‘q — qayta so‘raladi');

    final be = legacyBackend();
    await be.run(() async {
      await Api.ensureCapabilities();
      await Api.ensureCapabilities();
      try {
        await Api.getJson('/products/scan', query: {'code': '1'});
      } catch (_) {}
    });
    expect(be.calls('GET', '/health'), hasLength(1), reason: 'javob keldi — bir marta so‘raladi');
  });

  // ══ 8. KESH KALITI: manzil + sessiya ═════════════════════════════════════
  test('the probe re-runs on a new session (authEpoch) and is dropped on a server change', () async {
    final be = legacyBackend()..post('/auth/logout', (_) => {'ok': true});
    signIn();
    await be.run(() async {
      await Api.ensureCapabilities();
      expect(Api.capabilities.value.level, 0);
      await Api.logout();                 // authEpoch++
      await Api.ensureCapabilities();
    });
    expect(be.calls('GET', '/health'), hasLength(2), reason: 'yangi sessiya — qayta probe');

    // Boshqa serverga o'tish: eski bilim DARHOL unutiladi (tarmoqqa chiqmasdan).
    await Api.setBaseUrl('https://boshqa.example');
    expect(Api.capabilities.value.known, isFalse);
    expect(Api.capabilities.value, same(ServerCapabilities.unknown));
    Api.baseUrl = FakeBackend.baseUrl;
  });

  test('capabilities is a notifier screens can listen to', () async {
    final seen = <ServerCapabilities>[];
    void listener() => seen.add(Api.capabilities.value);
    Api.capabilities.addListener(listener);
    addTearDown(() => Api.capabilities.removeListener(listener));
    final be = currentBackend();
    await be.run(() => Api.ensureCapabilities());
    expect(seen, hasLength(1));
    expect(seen.single.supports(ServerFeature.saleReceipt), isTrue);
  });

  // ══ 9. DARVOZA FAQAT SANAB O'TILGAN YO'LLARGA TEGADI ═════════════════════
  test('requiredFeature: only the six dependencies are gated, nothing else', () {
    expect(Api.requiredFeature('GET', '/auth/context'), ServerFeature.authContext);
    expect(Api.requiredFeature('GET', '/products/scan'), ServerFeature.productsScan);
    expect(Api.requiredFeature('GET', '/cash/custody-preview'), ServerFeature.cashCustodyPreview);
    expect(Api.requiredFeature('GET', '/sales/s1/receipt'), ServerFeature.saleReceipt);
    expect(Api.requiredFeature('GET', '/returns/r1/receipt'), ServerFeature.saleReceipt);
    expect(Api.requiredFeature('POST', '/receiving/r1/corrections'), ServerFeature.receivingCorrections);
    // `limit` YOLG'IZ — bu bitta martalik qidiruv, eski serverda ham ishlaydi.
    expect(Api.requiredFeature('GET', '/products', {'limit': 50}), isNull);
    expect(Api.requiredFeature('GET', '/products', {'offset': 50}), ServerFeature.productsPaging);
    expect(Api.requiredFeature('GET', '/products', {'limit': 50, 'offset': 0}), ServerFeature.productsPaging);

    // Har serverda ishlaydigan yo'llar — HECH QACHON to'silmaydi.
    for (final (m, p) in [
      ('GET', '/health'),
      ('GET', '/products'),
      ('GET', '/products/by-barcode/4780000000001'),
      ('GET', '/products/1a2b'),
      ('GET', '/receiving'),
      ('GET', '/receiving/r1'),
      ('GET', '/sales/s1'),
      ('POST', '/inventory/writeoff'),
      ('POST', '/inventory/count'),
      ('POST', '/receiving/commit'),
      ('POST', '/cash/ops'),
      ('GET', '/cash/ops'),
      ('POST', '/suppliers'),
      ('POST', '/auth/login'),
    ]) {
      expect(Api.requiredFeature(m, p), isNull, reason: '$m $p');
    }
    expect(Api.requiredFeature('GET', '/products', const {'q': 'sut'}), isNull);
    expect(Api.requiredFeature('GET', '/products', const {'limit': null}), isNull);
  });

  // ══ 9b. E'LON QILGAN SERVERNING O'Z 404'i TEGILMAYDI ════════════════════
  test('a declared capability keeps its own 404 (a missing sale is not an outdated server)', () async {
    final be = currentBackend()..get('/sales/{id}/receipt', (_) => FakeResponse.error(404, 'Sotuv topilmadi'));
    signIn();
    Object? err;
    await be.run(() async {
      await Api.ensureCapabilities();
      try {
        await Api.getJson('/sales/s9/receipt');
      } catch (e) {
        err = e;
      }
    });
    expect(err, isNotNull);
    expect(userMessage(err), contains('Sotuv topilmadi'));
    expect(userMessage(err), isNot(contains('Server eski')),
        reason: 'server bu qobiliyatni E’LON qilgan — 404 ma’lumot haqida, server haqida emas');
    expect((err as ApiException).code, isNot(kServerCapabilityMissing));
  });

  // ══ 9c. ESKI SERVERDA QIDIRUV ISHLAYDI (to'silmaydi) ════════════════════
  test('a one-shot product search still works on an old server', () async {
    final be = legacyBackend();
    signIn();
    late List<dynamic> rows;
    await be.run(() async {
      await Api.ensureCapabilities();
      rows = (await Api.getJson('/products', query: {'q': 'sut', 'limit': 30})).list;
    });
    expect(rows, isNotEmpty, reason: 'qidiruv eski serverda ham javob beradi');
    expect(be.calls('GET', '/products'), hasLength(1));
  });

  // ══ 10. XABAR: tarjima qilingan, xom emas ════════════════════════════════
  test('the block message is localized and never shows a status, route or raw detail', () async {
    for (final (lang, expected) in [
      ('uz', 'Server eski — bu amal uchun serverni yangilash kerak. Administratorga ayting.'),
      ('ru', 'Сервер устарел — для этой операции его нужно обновить. Сообщите администратору.'),
      ('ky', 'Сервер эскирген — бул операция үчүн аны жаңыртуу керек. Администраторго айтыңыз.'),
      ('uzc', 'Сервер эски — бу амал учун серверни янгилаш керак. Администраторга айтинг.'),
    ]) {
      await resetCore(lang: lang);
      Api.debugResetCapabilities();
      final be = legacyBackend();
      signIn();
      Object? err;
      await be.run(() async {
        try {
          await Api.getJson('/products/scan', query: {'code': '1'});
        } catch (e) {
          err = e;
        }
      });
      final msg = userMessage(err);
      expect(msg, expected, reason: lang);
      expect(msg, isNot(contains('422')));
      expect(msg, isNot(contains('404')));
      expect(msg, isNot(contains('/products')));
      expect(msg, isNot(contains('UUID')));
      expect(Api.capabilities.value.outdatedMessage, expected, reason: '$lang (ekranlar uchun)');
    }
    L.code = 'uz';
  });

  // ══ 11. SERVER BILAN NOM PARITETI ════════════════════════════════════════
  test('the feature names match the server declaration byte for byte', () {
    final src = File('${_repoRoot().path}/apps/server/app/core/api_capabilities.py')
        .readAsStringSync();
    final block = RegExp(r'LEVEL_FEATURES[^=]*=\s*\{(.*?)\n\}', dotAll: true).firstMatch(src);
    expect(block, isNotNull, reason: 'LEVEL_FEATURES topilmadi');
    final names = {
      for (final m in RegExp('"([a-z0-9_]+)"').allMatches(block!.group(1)!)) m.group(1)!,
    };
    expect(names, isNotEmpty);
    expect(names, ServerFeature.all,
        reason: 'server va mijoz qobiliyat nomlari ajralib ketdi');
  });

  test('a server declaration without an api block reads as level 0 — no special case', () {
    expect(ServerCapabilities.fromHealth(healthLegacy()).level, 0);
    expect(ServerCapabilities.fromHealth(healthLegacy()).known, isTrue);
    expect(ServerCapabilities.fromHealth(healthCurrent()).level, 1);
    // Buzuq e'lon ham «eski server» deb o'qiladi (javob KELDI).
    for (final bad in <Object?>[
      {'status': 'ok', 'api': 'yes'},
      {'status': 'ok', 'api': {'features': ['auth_context']}},
      {'status': 'ok', 'api': {'level': -3, 'features': ['auth_context']}},
      {'status': 'ok', 'api': {'level': '1'}},
      'not json object',
    ]) {
      final c = ServerCapabilities.fromHealth(bad);
      expect(c.known, isTrue, reason: '$bad');
      expect(c.level, 0, reason: '$bad');
      expect(c.features, isEmpty, reason: '$bad');
    }
  });
}
