import 'dart:async';
import 'dart:convert';
import 'dart:math' show Random;
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'errors.dart';
import 'l10n.dart';

/// Decoded JSON response of a successful (2xx) request plus its headers.
///
/// Header names are lower-case (`http` normalises them), e.g.
/// `res.header('X-Total-Count')` reads `x-total-count`.
class ApiResponse {
  /// Creates a response wrapper (tests may build one directly).
  const ApiResponse(this.status, this.data, this.headers);

  /// HTTP status (always 2xx for a returned response).
  final int status;

  /// Decoded JSON body (`Map`, `List`, `String`, `num`, `bool` or `null`).
  final Object? data;

  /// Response headers with lower-case names.
  final Map<String, String> headers;

  /// Header value by (case-insensitive) [name].
  String? header(String name) => headers[name.toLowerCase()];

  /// `X-Total-Count` as an int (paged `GET /products?limit=`), if present.
  int? get totalCount => int.tryParse(header('x-total-count') ?? '');

  /// Body as a JSON object; throws a `server` [ApiException] when it is not one.
  Map<String, dynamic> get map {
    final d = data;
    if (d is Map) return d.cast<String, dynamic>();
    throw ApiException(status, 'Unexpected response shape', kind: ApiErrorKind.server, code: 'BAD_RESPONSE');
  }

  /// Body as a JSON array; throws a `server` [ApiException] when it is not one.
  List<dynamic> get list {
    final d = data;
    if (d is List) return d;
    throw ApiException(status, 'Unexpected response shape', kind: ApiErrorKind.server, code: 'BAD_RESPONSE');
  }
}

/// SavdoOS backend (Railway) bilan ishlovchi klient. Server manzili Sozlamalarda o'zgaradi.
///
/// ## Feature paketlar uchun ommaviy API
/// * [getJson] / [postJson] / [patchJson] / [deleteJson] — `/api/v1` ga nisbiy
///   yo'l, ixtiyoriy `query`; muvaffaqiyatda [ApiResponse] (JSON + sarlavhalar),
///   aks holda HAR DOIM [ApiException] (tarmoq xatosi ham) otiladi.
/// * Yozuv FAQAT 2xx dan keyin "bajarildi" deb ko'rsatiladi; tarmoq xatosi
///   (`kind == network/timeout`) biznes rad etishi EMAS — qayta urinishda o'sha
///   `client_uuid` ([DraftUuid]) yuboriladi.
/// * [online] faqat TARMOQ xatosida `false` bo'ladi; istalgan HTTP javob uni `true` qiladi.
/// * [authEpoch] — login/chiqish/401/server almashishida oshadi (Session tinglaydi).
class Api {
  static const _defaultBase = 'https://savdoos-production.up.railway.app';
  static String baseUrl = _defaultBase;
  static String? token;
  static Map<String, dynamic>? employee;

  /// Default timeout of reads.
  static const Duration readTimeout = Duration(seconds: 30);

  /// Default timeout of writes (receiving with an image may be slow).
  static const Duration writeTimeout = Duration(seconds: 60);

  /// Bearer token — qurilmaning XAVFSIZ xotirasida (Android Keystore), ochiq matnda EMAS.
  /// SharedPreferences ochiq (root/backup orqali o'qilishi mumkin), shuning uchun sirli
  /// token faqat shu yerда saqlanadi. (Lock bilan bir xil konfiguratsiya.)
  static const _secure = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  /// Full URL of an API [path] (relative to `/api/v1`) with an optional query.
  ///
  /// `null` query values are skipped; `Iterable` values repeat the key; other
  /// values are stringified (`true` -> `"true"`). A query already present in
  /// [path] is kept.
  static Uri uri(String path, [Map<String, Object?>? query]) {
    final u = Uri.parse('$baseUrl/api/v1$path');
    if (query == null || query.isEmpty) return u;
    final qp = <String, dynamic>{...u.queryParametersAll};
    query.forEach((k, v) {
      if (v == null) return;
      if (v is Iterable) {
        qp[k] = v.where((e) => e != null).map((e) => '$e').toList();
      } else {
        qp[k] = '$v';
      }
    });
    return u.replace(queryParameters: qp.isEmpty ? null : qp);
  }

  /// Encodes one path segment (`Api.seg(code)` in `/products/by-barcode/${...}`).
  static String seg(Object value) => Uri.encodeComponent('$value');

  static Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  // ── Sessiya saqlash ──
  static Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    baseUrl = p.getString('base_url') ?? _defaultBase;
    // Token — xavfsiz xotiradan. Eski o'rnatmalarда SharedPreferences'да ochiq turgan bo'lsa,
    // uni bir marta xavfsiz xotiraga KO'CHIRAMIZ va ochiq nusxani o'chiramiz (migratsiya).
    String? tok;
    try {
      tok = await _secure.read(key: 'token');
    } catch (_) {}
    if (tok == null || tok.isEmpty) {
      final legacy = p.getString('token');
      if (legacy != null && legacy.isNotEmpty) {
        tok = legacy;
        try {
          await _secure.write(key: 'token', value: legacy);
          await p.remove('token'); // ochiq matndagi eskisini o'chiramiz
        } catch (_) {/* xavfsiz xotira ishlamasa — token xotirada qoladi (shu sessiya) */}
      }
    }
    token = tok;
    // Xodim ma'lumoti (rol, ruxsatlar, telefon) ham xavfsiz xotirada — ochiq
    // SharedPreferences'да EMAS (ruxsatlar xavfsizlik chegarasi emas, ammo PII sizib chiqmasin).
    String? es;
    try {
      es = await _secure.read(key: 'employee');
    } catch (_) {}
    if (es == null || es.isEmpty) {
      final legacyE = p.getString('employee');
      if (legacyE != null && legacyE.isNotEmpty) {
        es = legacyE;
        try {
          await _secure.write(key: 'employee', value: legacyE);
          await p.remove('employee'); // ochiq nusxani o'chiramiz (migratsiya)
        } catch (_) {}
      }
    }
    if (es != null && es.isNotEmpty) {
      try {
        employee = jsonDecode(es) as Map<String, dynamic>;
      } catch (_) {}
    }
    // Eski versiyalar katalogni (boshqa xodim/do'kon qoldig'i bilan) diskda qoldirgan
    // bo'lishi mumkin — BIR MARTA tozalaymiz. Ishga tushishni kutdirmaydi.
    if (p.getBool(_kCatalogPurgedPref) != true) {
      unawaited(_purgeCatalogCache().then((_) async {
        try {
          await p.setBool(_kCatalogPurgedPref, true);
        } catch (_) {}
      }));
    }
  }

  static Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('base_url', baseUrl);
    if (token != null) {
      try {
        await _secure.write(key: 'token', value: token!);
        await p.remove('token'); // ochiq matnda hech qачон qolmasin
      } catch (_) {/* xavfsiz xotira ishlamasa — token faqat xotirада (shu sessiya) */}
    }
    if (employee != null) {
      try {
        await _secure.write(key: 'employee', value: jsonEncode(employee));
        await p.remove('employee'); // ochiq matnda qolmasin
      } catch (_) {/* xavfsiz xotira ishlamasa — faqat xotirада (shu sessiya) */}
    }
  }

  /// Normalises a server address typed by the operator: trims, drops trailing
  /// slashes and a pasted `/api/v1`, adds `https://` when no scheme is given.
  /// Empty input means the default production server.
  static String normalizeBaseUrl(String url) {
    var s = url.trim();
    if (s.isEmpty) return _defaultBase;
    s = s.replaceAll(RegExp(r'/+$'), '');
    s = s.replaceFirst(RegExp(r'/api/v1$'), '');
    if (!RegExp(r'^[a-zA-Z][a-zA-Z0-9+.-]*://').hasMatch(s)) s = 'https://$s';
    return s;
  }

  /// Sets the server address. Returns true when the server CHANGED.
  ///
  /// ⚠️  Server almashsa eski token/xodim/kesh YANGI serverga yuborilmasligi
  ///     kerak: hammasi tozalanadi, [authEpoch] oshadi va kirgan foydalanuvchi
  ///     uchun [onSessionExpired] chaqiriladi (login ekrani).
  static Future<bool> setBaseUrl(String url) async {
    final next = normalizeBaseUrl(url);
    final changed = next != baseUrl;
    final wasLoggedIn = token != null;
    if (changed) {
      await _clearLocal(); // eski serverning token/xodim/katalogi — shu qurilmadan
    }
    baseUrl = next;
    await _save();
    if (changed && wasLoggedIn) onSessionExpired?.call();
    return changed;
  }

  static Future<void> logout() async {
    // Server tomonda ham bekor qilamiz (sec_epoch oshadi) — token o'g'irlangan bo'lsa
    // ham amalda ishlamay qoladi. Best-effort: offline bo'lsa mahalliy chiqishga o'tamiz.
    try {
      if (token != null) await _post('/auth/logout', {});
    } catch (_) {}
    await _clearLocal();
  }

  /// Lokal sessiyani tozalash (server chaqiruvisiz) — 401/sessiya-bekor holatida ham ishlatiladi.
  ///
  /// ⚠️  TARTIB MUHIM: token/xodim BIRINCHI (sinxron, birinchi `await` dan oldin)
  ///     tozalanadi va [authEpoch] oshadi — fayl/xotira o'chirilayotgan paytda
  ///     hech bir so'rov ESKI token bilan ketmasin. Keyin saqlangan nusxalar va
  ///     eski katalog keshi o'chiriladi.
  ///
  /// [beforeCachePurge] runs once the credentials are gone from memory AND
  /// storage, before the (file-system) cache purge — the 401 handler sends the
  /// UI to the login screen there, without waiting for disk I/O.
  static Future<void> _clearLocal({void Function()? beforeCachePurge}) async {
    token = null;
    employee = null;
    authEpoch.value++;
    try {
      final p = await SharedPreferences.getInstance();
      await p.remove('token'); // eski o'rnatmalar uchun ham
      await p.remove('employee');
    } catch (_) {}
    try {
      await _secure.delete(key: 'token');
      await _secure.delete(key: 'employee');
    } catch (_) {}
    beforeCachePurge?.call();
    await _purgeCatalogCache();
  }

  static const String _kCatalogPurgedPref = 'legacy_catalog_cache_purged';

  /// Deletes EVERY product-catalog cache older app versions kept on the phone
  /// (`catalog_*.json` in the app support directory and the `catalog_*_rev`
  /// prefs), whichever employee, company or server it belonged to. The app no
  /// longer stores a catalog on disk; this runs once at start-up and on every
  /// logout / 401 / server change, so no other tenant's stock list stays behind.
  static Future<void> _purgeCatalogCache() async {
    try {
      final p = await SharedPreferences.getInstance();
      final keys = p.getKeys().where((k) => k.startsWith('catalog_') && k.endsWith('_rev')).toList();
      for (final k in keys) {
        await p.remove(k);
      }
    } catch (_) {}
    try {
      final dir = await getApplicationSupportDirectory();
      await for (final f in dir.list(followLinks: false)) {
        if (f is! File) continue;
        final name = f.path.replaceAll('\\', '/').split('/').last;
        if (name.startsWith('catalog_') && name.endsWith('.json')) {
          try {
            await f.delete();
          } catch (_) {}
        }
      }
    } catch (_) {/* fayl tizimi yo'q (web) — o'chiradigan narsa yo'q */}
  }

  static bool get loggedIn => token != null;

  /// Ulanish holati — server javob bermasa (tarmoq xatosi) false bo'ladi; UI banner ko'rsatadi.
  /// Istalgan HTTP javob (hatto 4xx/5xx) uni true qiladi: server bilan ALOQA bor.
  static final ValueNotifier<bool> online = ValueNotifier(true);

  /// Login, chiqish, 401 va server almashishida oshadi — sessiyaga bog'liq
  /// holat (Session, keshlar) shu signal bo'yicha qayta yuklanadi/tozalanadi.
  static final ValueNotifier<int> authEpoch = ValueNotifier(0);

  /// Merges fresh identity fields (from `GET /auth/context`) into the stored
  /// employee snapshot so legacy `Api.can`/`isOwner` see current permissions.
  static Future<void> updateEmployeeSnapshot(Map<String, dynamic> patch) async {
    if (employee == null) return;
    employee = {...employee!, ...patch};
    try {
      await _secure.write(key: 'employee', value: jsonEncode(employee));
    } catch (_) {}
  }

  // ── So'rovlar ──

  /// GET a JSON resource. Throws [ApiException] for every failure.
  static Future<ApiResponse> getJson(String path, {Map<String, Object?>? query, Duration? timeout}) =>
      _send('GET', path, query: query, timeout: timeout ?? readTimeout);

  /// POST a JSON [body]. Throws [ApiException] for every failure.
  static Future<ApiResponse> postJson(String path, Object? body,
          {Map<String, Object?>? query, Duration? timeout}) =>
      _send('POST', path, query: query, body: body, timeout: timeout ?? writeTimeout);

  /// PATCH a JSON [body]. Throws [ApiException] for every failure.
  static Future<ApiResponse> patchJson(String path, Object? body,
          {Map<String, Object?>? query, Duration? timeout}) =>
      _send('PATCH', path, query: query, body: body, timeout: timeout ?? writeTimeout);

  /// DELETE a resource. Throws [ApiException] for every failure.
  static Future<ApiResponse> deleteJson(String path, {Map<String, Object?>? query, Duration? timeout}) =>
      _send('DELETE', path, query: query, timeout: timeout ?? writeTimeout);

  /// Cheap reachability probe (`GET /health`); true when the server answered.
  static Future<bool> ping() async {
    try {
      await _send('GET', '/health', timeout: const Duration(seconds: 10));
      return true;
    } on ApiException catch (e) {
      return !e.isConnectivity; // HTTP javob keldi -> server tirik
    }
  }

  static Future<ApiResponse> _send(String method, String path,
      {Map<String, Object?>? query, Object? body, required Duration timeout}) async {
    final Uri url;
    try {
      url = uri(path, query);
    } catch (e) {
      throw ApiException(0, 'Bad server address', kind: ApiErrorKind.network, path: path, method: method, cause: e);
    }
    if (!const {'GET', 'POST', 'PATCH', 'PUT', 'DELETE'}.contains(method)) {
      throw ArgumentError.value(method, 'method'); // dasturchi xatosi
    }
    final enc = body == null ? null : jsonEncode(body);
    final h = _headers;
    http.Response r;
    try {
      final Future<http.Response> f = switch (method) {
        'GET' => http.get(url, headers: h),
        'POST' => http.post(url, headers: h, body: enc),
        'PATCH' => http.patch(url, headers: h, body: enc),
        'PUT' => http.put(url, headers: h, body: enc),
        _ => http.delete(url, headers: h, body: enc),
      };
      r = await f.timeout(timeout);
    } on TimeoutException catch (e) {
      // Javob kelmadi — natija NOMA'LUM. Server bilan aloqa bor-yo'qligini bilmaymiz,
      // shu bois `online` o'zgartirilmaydi (faqat haqiqiy tarmoq xatosida false).
      throw ApiException(0, 'Timeout', kind: ApiErrorKind.timeout, path: path, method: method, cause: e);
    } catch (e) {
      // SocketException / ClientException / HandshakeException / noto'g'ri manzil.
      online.value = false;
      throw ApiException(0, 'Network error', kind: ApiErrorKind.network, path: path, method: method, cause: e);
    }
    online.value = true; // http javob keldi (istalgan status) -> onlayn
    return _decode(r, method, path);
  }

  static Future<dynamic> _get(String path) async => (await getJson(path)).data;

  static Future<dynamic> _post(String path, Map<String, dynamic> body) async =>
      (await postJson(path, body)).data;

  /// Sessiya bekor bo'lganda (401) UI login ekraniga qaytishi uchun callback (main.dart o'rnatadi).
  static void Function()? onSessionExpired;
  static bool _handling401 = false;

  static ApiResponse _decode(http.Response r, String method, String path) {
    final headers = {for (final e in r.headers.entries) e.key.toLowerCase(): e.value};
    Object? data;
    var jsonOk = true;
    final bytes = r.bodyBytes;
    if (bytes.isNotEmpty) {
      try {
        data = jsonDecode(utf8.decode(bytes));
      } catch (_) {
        jsonOk = false;
      }
    }
    // GLOBAL 401: token bilan yuborilgan so'rov 401 qaytarsa — sessiya bekor (parol tiklandi /
    // boshqa qurilmada logout / muddati tugadi). Token tozalanadi va UI login ekraniga qaytariladi.
    // /auth/login* (noto'g'ri PIN/parol) va /auth/password (joriy parol xato) bundan MUSTASNO —
    // foydalanuvchini chiqarib yubormaymiz. _handling401 — rekursiya/parallel takror himoyasi.
    if (r.statusCode == 401 && token != null && !_handling401) {
      final p = r.request?.url.path ?? path;
      final isAuthCall = p.contains('/auth/login') || p.endsWith('/auth/password');
      if (!isAuthCall) {
        _handling401 = true;
        () async {
          try {
            await _clearLocal(beforeCachePurge: () {
              _handling401 = false;
              onSessionExpired?.call();
            });
          } finally {
            _handling401 = false;
          }
        }();
      }
    }
    if (r.statusCode >= 200 && r.statusCode < 300) {
      // ⚠️  2xx, lekin JSON emas (Wi-Fi login sahifasi, proksi HTML) — bu BIZNING
      //     server javobi emas: yozuv "bajarildi" deb ko'rsatilmasin.
      if (!jsonOk) {
        throw ApiException(r.statusCode, 'Non-JSON response',
            kind: ApiErrorKind.server, code: 'BAD_RESPONSE', path: path, method: method, headers: headers);
      }
      return ApiResponse(r.statusCode, data, headers);
    }
    final detail = data is Map ? data['detail'] : null;
    throw ApiException(
      r.statusCode,
      ApiException.flatten(detail) ?? '${tr('Xatolik')} (${r.statusCode})',
      code: ApiException.extractCode(headers, detail),
      detail: detail,
      path: path,
      method: method,
      headers: headers,
    );
  }

  static Future<void> login(String phone, String password) async {
    final data = await _post('/auth/login/password', {'phone': phone, 'password': password});
    token = data['access_token'] as String;
    employee = data['employee'] as Map<String, dynamic>?;
    await _save();
    authEpoch.value++;
  }

  static Future<Overview> overview(String period, {String? from, String? to}) async {
    final q = (from != null && to != null) ? '?from_date=$from&to_date=$to' : '?period=$period';
    return Overview.fromJson(await _get('/reports/overview$q') as Map<String, dynamic>);
  }

  /// Katalog kategoriyalari (yangi mahsulot uchun)
  static Future<List<CategoryLite>> catList() async {
    final data = await _get('/categories') as List;
    return data.map((e) => CategoryLite.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Short stable fingerprint of [baseUrl] (FNV-1a 32) for cache/pref keys —
  /// keeps the URL itself out of file names.
  static String serverKey([String? url]) {
    var h = 0x811c9dc5;
    for (final c in utf8.encode(url ?? baseUrl)) {
      h ^= c;
      h = (h * 0x01000193) & 0xffffffff;
    }
    return h.toRadixString(16).padLeft(8, '0');
  }

  /// Ombor o'zgarganda (kirim/chiqarish/sanoq/transfer/tuzatish) ekranlar
  /// yangilanishi uchun signal.
  static final ValueNotifier<int> stockRev = ValueNotifier<int>(0);

  /// Qoldiq yoki mahsulotni o'zgartiruvchi yozuv 2xx bilan tugagach chaqiriladi —
  /// [stockRev] oshadi va ochiq ro'yxatlar serverdan qayta yuklanadi.
  static void invalidateCatalog() {
    stockRev.value++;
  }

  static Future<List<CatRow>> categories(String period) async {
    final data = await _get('/reports/categories?period=$period') as List;
    return data.map((e) => CatRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<DebtInfo> debt() async {
    final d = await _get('/reports/dashboard') as Map<String, dynamic>;
    return DebtInfo.fromJson((d['debt'] as Map?)?.cast<String, dynamic>() ?? {});
  }

  static Future<List<SaleRow>> sales({int limit = 30}) async {
    final data = await _get('/sales?limit=$limit') as List;
    return data.map((e) => SaleRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<MoveRow>> movements({String? productId, int limit = 20}) async {
    final p = productId != null ? '&product_id=$productId' : '';
    final data = await _get('/inventory/movements?limit=$limit$p') as List;
    return data.map((e) => MoveRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<HourPoint>> hourly() async {
    final data = await _get('/reports/hourly') as List;
    return data.map((e) => HourPoint.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Ombor ogohlantirishi (kam qolgan + tugagan soni) — bildirishnoma/badge uchun.
  static Future<(int low, int out)> invAlerts() async {
    final d = await _get('/inventory/overview') as Map<String, dynamic>;
    return (_i(d['low_count']), _i(d['out_count']));
  }

  static Future<ReportDetail> reportDetail(String period) async {
    return ReportDetail.fromJson(await _get('/reports/detail?period=$period') as Map<String, dynamic>);
  }

  static Future<CashFlow> cashflow(String period) async {
    return CashFlow.fromJson(await _get('/reports/cashflow?period=$period') as Map<String, dynamic>);
  }

  static Future<List<CashOpRow>> cashOps() async {
    final data = await _get('/cash/ops') as List;
    return data.map((e) => CashOpRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<BranchRow>> branches() async {
    final d = await _get('/branches') as Map<String, dynamic>;
    return ((d['branches'] as List?) ?? []).map((e) => BranchRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Tashqi ekranlar uchun (masalan kirim savati) — idempotentlik uuid'i.
  static String newUuid() => _uuid();

  static final Random _rng = Random.secure();

  static String _uuid() {
    // UUIDv4 — kriptografik tasodifiy. Ilgari faqat vaqtdan (mikrosekund) yasalardi: ikki qurilma
    // bir onda amal yuborsa kalit to'qnashib, halol operatsiya serverda "takror" deb yutilardi.
    final b = List<int>.generate(16, (_) => _rng.nextInt(256));
    b[6] = (b[6] & 0x0f) | 0x40; // versiya 4
    b[8] = (b[8] & 0x3f) | 0x80; // variant
    final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
    return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
  }

  static Future<List<SupplierRow>> suppliers() async {
    final data = await _get('/suppliers') as List;
    return data.map((e) => SupplierRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> changePassword(String? oldPw, String newPw) async {
    final r = await _post('/auth/password', {'old_password': oldPw, 'new_password': newPw});
    // Parol o'zgargach server ESKI tokenlarni bekor qiladi — joriy qurilma chiqib
    // qolmasligi uchun yangi tokenni qabul qilib, xavfsiz xotiraga saqlaymiz.
    if (r is Map && r['access_token'] is String) {
      token = r['access_token'] as String;
      await _save();
    }
  }

  /// Yangi mahsulot nomiga kategoriya TAXMINI (do'kon katalogidagi o'xshash nomdan).
  /// Topilmasa/xato bo'lsa (null, null).
  static Future<(String?, String?)> guessCategory(String name) async {
    try {
      final d = await _get('/products/guess-category?name=${Uri.encodeComponent(name)}')
          as Map<String, dynamic>;
      return (d['category_id'] as String?, d['category_name'] as String?);
    } catch (_) {
      return (null, null);
    }
  }

  /// Joriy tarif (Sozlamalar->Tarif uchun). Server settings'dan; xato bo'lsa 'start'.
  static Future<String> plan() async {
    try {
      final d = await _get('/settings') as Map<String, dynamic>;
      return ((d['plan'] as Map?)?['plan'] as String?) ?? 'start';
    } catch (_) {
      return 'start';
    }
  }

  // ── Xodimlar boshqaruvi ────────────────────────────────────────────────
  static Future<List<EmployeeRow>> employees() async {
    final data = await _get('/employees') as List;
    return data.map((e) => EmployeeRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<EmployeeDetail> employeeDetail(String id) async {
    return EmployeeDetail.fromJson(await _get('/employees/$id') as Map<String, dynamic>);
  }

  static Future<EmpStats> employeeStats(String id) async {
    return EmpStats.fromJson(await _get('/employees/$id/stats') as Map<String, dynamic>);
  }

  static Future<List<PermissionRow>> permissionsList() async {
    final data = await _get('/permissions') as List;
    return data.map((e) => PermissionRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<String>> setPermission(String id, String code, bool allowed) async {
    final d = (await patchJson('/employees/${seg(id)}/permissions', {
      'overrides': {code: allowed}
    }, timeout: readTimeout))
        .map;
    return ((d['permissions'] as List?) ?? []).map((e) => e.toString()).toList();
  }

  /// Joriy foydalanuvchida ruxsat bormi (login'dagi employee.permissions'dan)
  static bool can(String code) {
    final p = employee?['permissions'];
    if (p is List) return p.contains(code);
    return false;
  }
}

/// What kind of failure an [ApiException] is — screens branch on this, never
/// on the message text.
enum ApiErrorKind {
  /// No HTTP response at all (DNS, refused, TLS, offline). [Api.online] -> false.
  network,

  /// The request timed out: the outcome of a write is UNKNOWN — retry with the
  /// same `client_uuid`.
  timeout,

  /// 401 — session expired (the app is sent to the login screen).
  auth,

  /// 403 — the server refused for lack of permission / branch scope.
  permission,

  /// 422 — request shape rejected by the server's validator.
  validation,

  /// Other 4xx — a business rule refused the request (400, 404, 409, ...).
  business,

  /// 5xx or an unusable 2xx body.
  server,
}

/// Every failure of [Api] — HTTP errors AND transport errors.
///
/// * [status] — HTTP status, `0` for network/timeout;
/// * [code] — stable machine code: the `X-Error-Code` header, else a `CASH_*`
///   (cutover) prefix of the text, else `detail.error` of a dict detail;
/// * [detail] — the raw decoded `detail` (String, List for 422, Map for cash
///   posting errors, or null);
/// * [kind] — the category screens branch on.
///
/// `toString()` returns the localized operator message ([userMessage]), so a
/// legacy `Text('$e')` already shows a translated, sanitised text.
class ApiException implements Exception {
  /// Creates an exception; [kind] defaults to the category of [status].
  ApiException(this.status, this.message,
      {this.code, this.detail, ApiErrorKind? kind, this.path, this.method, this.headers = const {}, this.cause})
      : kind = kind ?? kindForStatus(status);

  /// HTTP status (0 when no response was received).
  final int status;

  /// Raw server text flattened to one line (back-compat; NOT for display —
  /// use [userMessage]).
  final String message;

  /// Stable error code, if the server sent one.
  final String? code;

  /// Raw decoded `detail` of the error body.
  final Object? detail;

  /// Failure category.
  final ApiErrorKind kind;

  /// Request path (relative to `/api/v1`) and method, for logs.
  final String? path, method;

  /// Response headers (lower-case names); empty for transport failures.
  final Map<String, String> headers;

  /// Underlying transport exception, if any.
  final Object? cause;

  /// True for network and timeout failures (nothing was decided by the server).
  bool get isConnectivity => kind == ApiErrorKind.network || kind == ApiErrorKind.timeout;

  /// True for 409 (state conflict: busy document, stale lot, replay conflict).
  bool get isConflict => status == 409;

  /// Category of an HTTP [status].
  static ApiErrorKind kindForStatus(int status) {
    if (status == 401) return ApiErrorKind.auth;
    if (status == 403) return ApiErrorKind.permission;
    if (status == 408) return ApiErrorKind.timeout;
    if (status == 422) return ApiErrorKind.validation;
    if (status >= 500) return ApiErrorKind.server;
    if (status == 0) return ApiErrorKind.network;
    return ApiErrorKind.business;
  }

  /// Codes the server sends as a `"<CODE>: text"` prefix (cash cutover guard).
  static const Set<String> prefixCodes = {
    'LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER',
    'TILL_REQUIRED_AFTER_CUTOVER',
    'TILL_INVALID_AFTER_CUTOVER',
    'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER',
    'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER',
    'CASH_CUSTODY_ACCOUNT_INVALID',
    'CASH_LEDGER_UNAVAILABLE',
    'CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY',
  };

  static final RegExp _prefix = RegExp(r'^([A-Z][A-Z0-9_]{2,}):');

  /// Stable code of an error response: header, else cash prefix, else dict `error`.
  static String? extractCode(Map<String, String> headers, Object? detail) {
    final h = headers['x-error-code']?.trim();
    if (h != null && h.isNotEmpty) return h;
    if (detail is Map && detail['error'] is String && (detail['error'] as String).isNotEmpty) {
      return detail['error'] as String;
    }
    if (detail is String) {
      final m = _prefix.firstMatch(detail.trim());
      final c = m?.group(1);
      if (c != null && (prefixCodes.contains(c) || c.startsWith('CASH_'))) return c;
    }
    return null;
  }

  /// One-line raw text of a `detail` value (`null` when there is none).
  static String? flatten(Object? detail) {
    if (detail == null) return null;
    if (detail is String) return detail;
    if (detail is Map) {
      final m = detail['message'];
      if (m is String && m.isNotEmpty) return m;
      return jsonEncode(detail);
    }
    if (detail is List) {
      final parts = detail.map((e) => e is Map && e['msg'] != null ? '${e['msg']}' : jsonEncode(e)).toList();
      return parts.join('; ');
    }
    return '$detail';
  }

  @override
  String toString() => userMessage(this);
}

/// Idempotency key (`client_uuid`) bound to a draft.
///
/// * the SAME draft (same fingerprint) always gets the SAME uuid — a retry
///   after a timeout/network error is recognised by the server as a replay;
/// * a CHANGED draft gets a NEW uuid (the server would otherwise report a
///   replay conflict or silently return the old result);
/// * [rotate] after a success (next document) or after a replay conflict.
///
/// ```dart
/// final key = DraftUuid();
/// final uuid = key.forDraft(body);   // body without client_uuid
/// await Api.postJson('/inventory/writeoff', {...body, 'client_uuid': uuid});
/// key.rotate();
/// ```
class DraftUuid {
  String? _fingerprint;
  String? _uuid;

  /// The uuid for [draft] (any JSON-encodable value or string).
  String forDraft(Object? draft) {
    final fp = draft is String ? draft : jsonEncode(draft);
    if (_uuid == null || fp != _fingerprint) {
      _fingerprint = fp;
      _uuid = Api.newUuid();
    }
    return _uuid!;
  }

  /// The current uuid (creates one for an unnamed draft).
  String get current => _uuid ??= Api.newUuid();

  /// Forgets the draft: the next call gets a new uuid.
  void rotate() {
    _fingerprint = null;
    _uuid = null;
  }
}

// ─────────────────────────── Modellar ───────────────────────────

double _d(dynamic v) => v == null ? 0.0 : (v is num ? v.toDouble() : double.tryParse(v.toString()) ?? 0.0);
int _i(dynamic v) => v == null ? 0 : (v is num ? v.toInt() : int.tryParse(v.toString()) ?? 0);

class Overview {
  final double sales, profit, avgCheck;
  final int tx;
  final double? dSales, dProfit;
  final List<SeriesPoint> series;
  final List<TopProduct> top;
  final List<Cashier> cashiers;
  final List<PayRow> payments;
  final double creditTotal;
  Overview({
    required this.sales, required this.profit, required this.avgCheck, required this.tx,
    required this.dSales, required this.dProfit, required this.series,
    required this.top, required this.cashiers, required this.payments, required this.creditTotal,
  });
  factory Overview.fromJson(Map<String, dynamic> j) {
    final k = (j['kpi'] as Map?) ?? {};
    final d = (j['delta'] as Map?) ?? {};
    return Overview(
      sales: _d(k['sales']), profit: _d(k['profit']), avgCheck: _d(k['avg_check']), tx: _i(k['tx']),
      dSales: d['sales'] == null ? null : _d(d['sales']),
      dProfit: d['profit'] == null ? null : _d(d['profit']),
      series: ((j['series'] as List?) ?? []).map((e) => SeriesPoint.fromJson(e)).toList(),
      top: ((j['top_products'] as List?) ?? []).map((e) => TopProduct.fromJson(e)).toList(),
      cashiers: ((j['cashiers'] as List?) ?? []).map((e) => Cashier.fromJson(e)).toList(),
      payments: ((j['payments'] as List?) ?? []).map((e) => PayRow.fromJson(e)).toList(),
      creditTotal: _d(j['credit_total']),
    );
  }
}

class SeriesPoint {
  final String label;
  final double sales, profit;
  SeriesPoint({required this.label, required this.sales, required this.profit});
  factory SeriesPoint.fromJson(Map j) => SeriesPoint(label: (j['label'] ?? '').toString(), sales: _d(j['sales']), profit: _d(j['profit']));
}

class TopProduct {
  final String name;
  final double revenue;
  TopProduct({required this.name, required this.revenue});
  factory TopProduct.fromJson(Map j) => TopProduct(name: (j['name'] ?? '').toString(), revenue: _d(j['revenue']));
}

class Cashier {
  final String name;
  final double sales;
  final int tx;
  Cashier({required this.name, required this.sales, required this.tx});
  factory Cashier.fromJson(Map j) => Cashier(name: (j['name'] ?? '').toString(), sales: _d(j['sales']), tx: _i(j['tx']));
}

class PayRow {
  final String method;
  final double amount;
  PayRow({required this.method, required this.amount});
  factory PayRow.fromJson(Map j) => PayRow(method: (j['method'] ?? '').toString(), amount: _d(j['amount']));
}

class CatRow {
  final String name;
  final double sales, profit;
  final int margin;
  CatRow({required this.name, required this.sales, required this.profit, required this.margin});
  factory CatRow.fromJson(Map<String, dynamic> j) => CatRow(
        name: (j['name'] ?? '—').toString(), sales: _d(j['sales']), profit: _d(j['profit']), margin: _i(j['margin']));
}

class DebtInfo {
  final double total, paidToday;
  final int debtors;
  DebtInfo({required this.total, required this.paidToday, required this.debtors});
  factory DebtInfo.fromJson(Map<String, dynamic> j) =>
      DebtInfo(total: _d(j['total']), paidToday: _d(j['paid_today']), debtors: _i(j['debtors']));
}

class SaleRow {
  final String id, receiptNo, cashier, method, firstItem;
  final DateTime? at;
  final double itemCount, total;
  SaleRow({
    required this.id, required this.receiptNo, required this.cashier, required this.method,
    required this.firstItem, required this.at, required this.itemCount, required this.total,
  });
  factory SaleRow.fromJson(Map<String, dynamic> j) => SaleRow(
        id: j['id'].toString(),
        receiptNo: (j['receipt_no'] ?? '').toString(),
        cashier: (j['cashier'] ?? '').toString(),
        method: (j['method'] ?? 'cash').toString(),
        firstItem: (j['first_item'] ?? '').toString(),
        at: serverDt(j['sold_at']),
        itemCount: _d(j['item_count']),
        total: _d(j['total']),
      );
}

class MoveRow {
  final String type, direction, name, employee;
  final double qty;
  final DateTime? at;
  MoveRow({required this.type, required this.direction, required this.name, required this.employee, required this.qty, required this.at});
  factory MoveRow.fromJson(Map<String, dynamic> j) => MoveRow(
        type: (j['type'] ?? '').toString(),
        direction: (j['direction'] ?? 'in').toString(),
        name: (j['name'] ?? '').toString(),
        employee: (j['employee'] ?? '—').toString(),
        qty: _d(j['qty']),
        at: serverDt(j['at']),
      );
}

class HourPoint {
  final int hour;
  final double sales;
  HourPoint({required this.hour, required this.sales});
  factory HourPoint.fromJson(Map<String, dynamic> j) => HourPoint(hour: _i(j['hour']), sales: _d(j['sales']));
}

class CashOpRow {
  final String type, reason, employee;
  final double amount;
  final DateTime? at;
  CashOpRow({required this.type, required this.reason, required this.employee, required this.amount, required this.at});
  factory CashOpRow.fromJson(Map<String, dynamic> j) => CashOpRow(
        type: (j['type'] ?? '').toString(),
        reason: (j['reason'] ?? '').toString(),
        employee: (j['employee'] ?? '—').toString(),
        amount: _d(j['amount']),
        at: serverDt(j['at']));
}

class BranchRow {
  final String id, name;
  final bool visible, isActive; // QA WH-002/WH-005: yashirin/nofaol filiallar tanlagichda ko'rinmasin
  BranchRow({required this.id, required this.name, this.visible = true, this.isActive = true});
  factory BranchRow.fromJson(Map<String, dynamic> j) =>
      BranchRow(id: (j['id'] ?? '').toString(), name: (j['name'] ?? '').toString(),
          visible: j['visible'] != false, isActive: j['is_active'] != false);
}

class CashFlow {
  final double inNaqd, inQarz, inQosh, inJami;
  final double outXarajat, outInkassa, outQaytarish, outBeruvchi, outJami;
  final double opening, kassada, karta, qr, nasiya;
  CashFlow({required this.inNaqd, required this.inQarz, required this.inQosh, required this.inJami,
      required this.outXarajat, required this.outInkassa, required this.outQaytarish, required this.outBeruvchi, required this.outJami,
      required this.opening, required this.kassada, required this.karta, required this.qr, required this.nasiya});
  factory CashFlow.fromJson(Map<String, dynamic> j) {
    final i = (j['in'] as Map?) ?? {}, o = (j['out'] as Map?) ?? {}, n = (j['noncash'] as Map?) ?? {};
    return CashFlow(
      inNaqd: _d(i['naqd_savdo']), inQarz: _d(i['qarz_qaytdi']), inQosh: _d(i['qoshimcha']), inJami: _d(i['jami']),
      outXarajat: _d(o['xarajat']), outInkassa: _d(o['inkassatsiya']), outQaytarish: _d(o['qaytarish']),
      outBeruvchi: _d(o['beruvchiga']), outJami: _d(o['jami']),
      opening: _d(j['opening']), kassada: _d(j['kassada']),
      karta: _d(n['karta']), qr: _d(n['qr']), nasiya: _d(n['nasiya']));
  }
}

class AbcRow {
  final String name, cls;
  final double units, revenue, profit, share;
  AbcRow({required this.name, required this.cls, required this.units, required this.revenue, required this.profit, required this.share});
  factory AbcRow.fromJson(Map<String, dynamic> j) => AbcRow(
        name: (j['name'] ?? '').toString(), cls: (j['cls'] ?? 'C').toString(),
        units: _d(j['units']), revenue: _d(j['revenue']), profit: _d(j['profit']), share: _d(j['share']));
}

class ReportDetail {
  final int retCount, voided;
  final double retSum, aShare;
  final List<AbcRow> abc;
  ReportDetail({required this.retCount, required this.voided, required this.retSum, required this.aShare, required this.abc});
  factory ReportDetail.fromJson(Map<String, dynamic> j) {
    final r = (j['returns'] as Map?) ?? {};
    return ReportDetail(
      retCount: _i(r['count']), voided: _i(r['voided']), retSum: _d(r['sum']),
      aShare: _d(j['a_share']),
      abc: ((j['abc'] as List?) ?? []).map((e) => AbcRow.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}

class SupplierRow {
  final String id, name;
  final String? phone;
  final double balance;
  SupplierRow({required this.id, required this.name, required this.phone, required this.balance});
  factory SupplierRow.fromJson(Map<String, dynamic> j) => SupplierRow(
        id: (j['id'] ?? '').toString(), name: (j['name'] ?? '').toString(), phone: j['phone']?.toString(), balance: _d(j['balance']));
}

class CategoryLite {
  final String id, name;
  CategoryLite({required this.id, required this.name});
  factory CategoryLite.fromJson(Map<String, dynamic> j) =>
      CategoryLite(id: j['id'].toString(), name: (j['name'] ?? '').toString());
}

class EmployeeRow {
  final String id, fullName, role, roleName, status;
  final String? phone, branch;
  EmployeeRow({required this.id, required this.fullName, required this.role,
      required this.roleName, required this.status, this.phone, this.branch});
  factory EmployeeRow.fromJson(Map<String, dynamic> j) => EmployeeRow(
        id: j['id'].toString(), fullName: (j['full_name'] ?? '').toString(),
        role: (j['role'] ?? '').toString(), roleName: (j['role_name'] ?? '').toString(),
        status: (j['status'] ?? 'active').toString(),
        phone: j['phone']?.toString(), branch: j['branch']?.toString());
}

class EmployeeDetail {
  final String id, fullName, role, status;
  final String? phone, branchId, branch;
  final List<String> permissions;
  EmployeeDetail({required this.id, required this.fullName, required this.role,
      required this.status, this.phone, this.branchId, this.branch, required this.permissions});
  factory EmployeeDetail.fromJson(Map<String, dynamic> j) => EmployeeDetail(
        id: j['id'].toString(), fullName: (j['full_name'] ?? '').toString(),
        role: (j['role'] ?? 'kassir').toString(), status: (j['status'] ?? 'active').toString(),
        phone: j['phone']?.toString(), branchId: j['branch_id']?.toString(),
        branch: j['branch']?.toString(),
        permissions: ((j['permissions'] as List?) ?? []).map((e) => e.toString()).toList());
}

class EmpStats {
  final double monthSales;
  final int tx;
  final List<(String, double)> chart; // (oy, savdo)
  EmpStats({required this.monthSales, required this.tx, required this.chart});
  factory EmpStats.fromJson(Map<String, dynamic> j) => EmpStats(
        monthSales: _d(j['month_sales']), tx: _i(j['tx']),
        chart: ((j['chart'] as List?) ?? [])
            .map((e) => ((e['label'] ?? '').toString(), _d(e['sales'])))
            .toList());
}

class PermissionRow {
  final String code, module;
  PermissionRow({required this.code, required this.module});
  factory PermissionRow.fromJson(Map<String, dynamic> j) =>
      PermissionRow(code: (j['code'] ?? '').toString(), module: (j['module'] ?? '').toString());
}

