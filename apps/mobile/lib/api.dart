import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n.dart';

/// SavdoOS backend (Railway) bilan ishlovchi klient. Server manzili Sozlamalarda o'zgaradi.
class Api {
  static const _defaultBase = 'https://savdoos-production.up.railway.app';
  static String baseUrl = _defaultBase;
  static String? token;
  static Map<String, dynamic>? employee;

  /// Bearer token — qurilmaning XAVFSIZ xotirasida (Android Keystore), ochiq matnda EMAS.
  /// SharedPreferences ochiq (root/backup orqali o'qilishi mumkin), shuning uchun sirli
  /// token faqat shu yerда saqlanadi. (Lock bilan bir xil konfiguratsiya.)
  static const _secure = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  static Uri _u(String path) => Uri.parse('$baseUrl/api/v1$path');
  static Map<String, String> get _headers => {
        'Content-Type': 'application/json',
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

  static Future<void> setBaseUrl(String url) async {
    baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    await _save();
  }

  static Future<void> logout() async {
    // Server tomonda ham bekor qilamiz (sec_epoch oshadi) — token o'g'irlangan bo'lsa
    // ham amalda ishlamay qoladi. Best-effort: offline bo'lsa mahalliy chiqishga o'tamiz.
    try {
      if (token != null) await _post('/auth/logout', {});
    } catch (_) {}
    token = null;
    employee = null;
    // Katalog k[eshini tozalaymiz — aks holда shu qurilmага boshqa foydalanuvchi kirса, avvalgi
    // foydalanuvchining katalog/qoldiqлари (xotirадаги kesh) ko'rsатилиб qolарди.
    _catalogMem = null;
    _catalogMemRev = null;
    final p = await SharedPreferences.getInstance();
    await p.remove('token');   // eski o'rnatmalar uchun ham
    await p.remove('employee');
    try {
      await _secure.delete(key: 'token');
      await _secure.delete(key: 'employee');
    } catch (_) {}
  }

  static bool get loggedIn => token != null;

  /// Ulanish holati — server javob bermasa (tarmoq/timeout) false bo'ladi; UI banner ko'rsatadi.
  static final ValueNotifier<bool> online = ValueNotifier(true);

  // ── So'rovlar ──
  static Future<dynamic> _get(String path) async {
    try {
      final r = await http.get(_u(path), headers: _headers).timeout(const Duration(seconds: 30));
      online.value = true; // http javob keldi (istalgan status) -> onlayn
      return _decode(r);
    } catch (e) {
      if (e is! ApiException) online.value = false; // faqat tarmoq/timeout xatosi
      rethrow;
    }
  }

  static Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    try {
      final r = await http
          .post(_u(path), headers: _headers, body: jsonEncode(body))
          .timeout(const Duration(seconds: 60));
      online.value = true;
      return _decode(r);
    } catch (e) {
      if (e is! ApiException) online.value = false;
      rethrow;
    }
  }

  static dynamic _decode(http.Response r) {
    dynamic data;
    try {
      data = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (r.statusCode >= 200 && r.statusCode < 300) return data;
    final msg = (data is Map && data['detail'] != null)
        ? (data['detail'] is String ? data['detail'] : jsonEncode(data['detail']))
        : '${tr('Xatolik')} (${r.statusCode})';
    throw ApiException(r.statusCode, msg.toString());
  }

  static Future<void> login(String phone, String password) async {
    final data = await _post('/auth/login/password', {'phone': phone, 'password': password});
    token = data['access_token'] as String;
    employee = data['employee'] as Map<String, dynamic>?;
    await _save();
  }

  static Future<Overview> overview(String period, {String? from, String? to}) async {
    final q = (from != null && to != null) ? '?from_date=$from&to_date=$to' : '?period=$period';
    return Overview.fromJson(await _get('/reports/overview$q') as Map<String, dynamic>);
  }

  static Future<List<ScanItem>> scan(String imageB64, String mediaType) async {
    final data = await _post('/receiving/scan', {'image_b64': imageB64, 'media_type': mediaType});
    _lastSource = data['source'] as String? ?? 'ai';
    _lastAiRaw = (data['ai_raw'] as List?) ?? [];
    return ((data['items'] as List?) ?? []).map((e) => ScanItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  static String _lastSource = 'ai';
  static List _lastAiRaw = [];
  static String get lastSource => _lastSource;

  static Future<List<ProductLite>> products() async {
    final data = await _get('/products') as List;
    return data.map((e) => ProductLite.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<InvItem>> inventory() async {
    final data = await _get('/products') as List;
    return data.map((e) => InvItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Kirim uchun — arxivdagilar ham (kirim kelsa avto faollashadi)
  static Future<List<InvItem>> inventoryAll() async {
    final data = await _get('/products?include_archived=1') as List;
    return data.map((e) => InvItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Katalog kategoriyalari (yangi mahsulot uchun)
  static Future<List<CategoryLite>> catList() async {
    final data = await _get('/categories') as List;
    return data.map((e) => CategoryLite.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Shtrix-kod bo'yicha aniq mahsulot — topilmasa null (yangi mahsulot rejimi)
  static Future<InvItem?> productByBarcode(String code) async {
    final data = await _get('/products/by-barcode/$code');
    if (data == null) return null;
    return InvItem.fromJson(data as Map<String, dynamic>);
  }

  /// Mahsulot to'liq ma'lumoti (narxlar + sotuv statistikasi)
  static Future<ProductDetail> productDetail(String id) async {
    final data = await _get('/products/$id') as Map<String, dynamic>;
    return ProductDetail.fromJson(data);
  }

  // ── Katalog keshi (telefon xotirasida) ──────────────────────────────────
  // Butun katalogni (7000+ mahsulot) har safar yuklamaymiz — bir marta telefonga
  // saqlab qo'yamiz. Keyingi safar yengil "versiya" so'raymiz; o'zgarmagan bo'lsa
  // xotiradagi/fayldagi nusxadan ishlaymiz (bir zumda, internet shart emas).
  static List<InvItem>? _catalogMem;
  static String? _catalogMemRev;

  static String get _cacheKey {
    // Foydalanuvchи bo'yicha (xodим id) — bir do'konда turli FILIALга bog'langan xodимлар har
    // xil qoldiq ko'rади (server /products'ни visible_branches bilan cheklaydi); company bo'yicha
    // keshласак, bir qurilmада ikkinchи xodим avvalгисининг filial qoldig'ини ko'rарди.
    final c = employee?['id'] ?? employee?['company_id'] ?? 'def';
    return 'catalog_$c';
  }

  static Future<File> _catalogFile() async {
    final dir = await getApplicationSupportDirectory();
    return File('${dir.path}/${_cacheKey}.json');
  }

  static Future<String?> _catalogVersion() async {
    try {
      final d = await _get('/products/catalog-version') as Map<String, dynamic>;
      return d['rev']?.toString();
    } catch (_) {
      return null; // internet yo'q — keshdan ishlayveramiz
    }
  }

  /// Katalog (arxiv ham) — kesh bilan. forceRefresh=true bo'lsa majburan yuklaydi.
  /// onProgress: birinchi marta yuklanayotganda UI xabar ko'rsatishi uchun.
  static Future<List<InvItem>> cachedCatalog({bool forceRefresh = false, void Function(String)? onStatus}) async {
    final sp = await SharedPreferences.getInstance();
    final storedRev = sp.getString('${_cacheKey}_rev');
    final serverRev = await _catalogVersion();

    // OFLAYN (serverRev null): keshdan ishlaymiz — xotira, bo'lmasa fayl.
    // (Ilgari null'da to'g'ri serverdan yuklashga tushib, exception bilan bo'sh qolardi.)
    if (serverRev == null && !forceRefresh) {
      if (_catalogMem != null) return _catalogMem!;
      try {
        final f = await _catalogFile();
        if (await f.exists()) {
          final list = (jsonDecode(await f.readAsString()) as List)
              .map((e) => InvItem.fromJson(e as Map<String, dynamic>)).toList();
          _catalogMem = list;
          _catalogMemRev = storedRev;
          return list;
        }
      } catch (_) {/* buzilgan kesh — quyida serverga urinamiz (xato beradi, UI ko'rsatadi) */}
    }

    // 1) Xotirada bor va versiya mos — darrov qaytaramiz
    if (!forceRefresh && _catalogMem != null && serverRev != null && _catalogMemRev == serverRev) {
      return _catalogMem!;
    }
    // 2) Faylda bor va versiya mos — fayldan o'qiymiz (internet yuklamasdan)
    if (!forceRefresh && serverRev != null && storedRev == serverRev) {
      try {
        final f = await _catalogFile();
        if (await f.exists()) {
          final list = (jsonDecode(await f.readAsString()) as List)
              .map((e) => InvItem.fromJson(e as Map<String, dynamic>)).toList();
          _catalogMem = list; _catalogMemRev = serverRev;
          return list;
        }
      } catch (_) {/* buzilgan kesh — qayta yuklaymiz */}
    }
    // 3) Yangilash kerak — serverdan bir marta to'liq yuklab, saqlab qo'yamiz
    onStatus?.call(tr('Katalog yangilanmoqda…'));
    final raw = await _get('/products?include_archived=1') as List;
    final list = raw.map((e) => InvItem.fromJson(e as Map<String, dynamic>)).toList();
    _catalogMem = list;
    _catalogMemRev = serverRev;
    try {
      final f = await _catalogFile();
      await f.writeAsString(jsonEncode(raw));
      if (serverRev != null) await sp.setString('${_cacheKey}_rev', serverRev);
    } catch (_) {/* saqlashda xato bo'lsa ham ishlayveramiz */}
    return list;
  }

  /// Kirim saqlangach chaqiriladi — keshni eskiradi (yangi mahsulot/narx paydo bo'ldi).
  static void invalidateCatalog() {
    _bustCatalog();
  }

  /// Qoldiq o'zgartiruvchi amal muvaffaqiyatli bo'lgach — kesh eskiradi: xotira
  /// nusxasi tashlanadi va saqlangan rev o'chadi (rev qoldiqni SEZMAYDI), keyingi
  /// cachedCatalog() serverdan yangilaydi; fayl qoladi — oflayn zaxira.
  /// Ombor o'zgarganda (kirim/chiqarish/sanoq/transfer) ekranlar yangilanishi uchun signal.
  static final ValueNotifier<int> stockRev = ValueNotifier<int>(0);

  static Future<void> _bustCatalog() async {
    stockRev.value++;
    _catalogMem = null;
    _catalogMemRev = null;
    try {
      await (await SharedPreferences.getInstance()).remove('${_cacheKey}_rev');
    } catch (_) {}
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

  static Future<List<Debtor>> debtors() async {
    final data = await _get('/customers?only_debt=true') as List;
    return data.map((e) => Debtor.fromJson(e as Map<String, dynamic>)).toList();
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

  static Future<SaleDetail> saleDetail(String id) async {
    return SaleDetail.fromJson(await _get('/sales/$id') as Map<String, dynamic>);
  }

  static Future<ReportDetail> reportDetail(String period) async {
    return ReportDetail.fromJson(await _get('/reports/detail?period=$period') as Map<String, dynamic>);
  }

  static Future<CashFlow> cashflow(String period) async {
    return CashFlow.fromJson(await _get('/reports/cashflow?period=$period') as Map<String, dynamic>);
  }

  static Future<void> cashOp(String type, double amount, String? reason, {String? clientUuid}) async {
    // client_uuid — offline retry'да ikki marta kassaga yozilmasin (server dedup qiladi).
    await _post('/cash/ops', {'type': type, 'amount': amount, 'reason': reason, 'client_uuid': clientUuid});
  }

  static Future<List<CashOpRow>> cashOps() async {
    final data = await _get('/cash/ops') as List;
    return data.map((e) => CashOpRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<BranchRow>> branches() async {
    final d = await _get('/branches') as Map<String, dynamic>;
    return ((d['branches'] as List?) ?? []).map((e) => BranchRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<Map<String, dynamic>> transfer(String fromId, String toId, List<(String, double)> items,
      {required String clientUuid}) async {
    // Idempotentlik: bitta transfer uchun BITTA uuid (ekran beradi) — timeout'dan keyin
    // qayta bosilsa server o'sha ko'chirishni qaytaradi, dublikat yaratmaydi.
    final res = await _post('/inventory/transfer', {
      'from_branch_id': fromId,
      'to_branch_id': toId,
      'items': items.map((i) => {'product_id': i.$1, 'qty': i.$2}).toList(),
      'client_uuid': clientUuid,
    }) as Map<String, dynamic>;
    await _bustCatalog(); // filial qoldig'i ko'chdi — kesh eskirdi
    return res;
  }

  /// Tashqi ekranlar uchun (masalan kirim savati) — idempotentlik uuid'i.
  static String newUuid() => _uuid();

  static String _uuid() {
    final r = DateTime.now().microsecondsSinceEpoch;
    final rnd = (r ^ (r >> 13)).toRadixString(16).padLeft(12, '0');
    return '${rnd.substring(0, 8)}-${rnd.substring(8, 12)}-4000-8000-${r.toRadixString(16).padLeft(12, '0').substring(0, 12)}';
  }

  static Future<List<SupplierRow>> suppliers() async {
    final data = await _get('/suppliers') as List;
    return data.map((e) => SupplierRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> paySupplier(String id, double amount, {String? clientUuid}) async {
    // client_uuid — tarmoq uzilib qayta yuborilса server qisman to'lovни ikki marta yozмасин (dedup).
    await _post('/suppliers/$id/payments', {'amount': amount, 'client_uuid': clientUuid});
  }

  static Future<List<Debtor>> customers({bool onlyDebt = false}) async {
    final data = await _get('/customers${onlyDebt ? '?only_debt=true' : ''}') as List;
    return data.map((e) => Debtor.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> payCredit(String customerId, double amount, {String? clientUuid}) async {
    // client_uuid — tarmoq uzilib qayta yuborilса server qarзни ikki marta kamaytirмасин (dedup).
    await _post('/customers/$customerId/payments', {'amount': amount, 'client_uuid': clientUuid});
  }

  static Future<CustomerDetail> customerDetail(String id) async {
    return CustomerDetail.fromJson(await _get('/customers/$id/detail') as Map<String, dynamic>);
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

  static Future<void> writeoff(String productId, double qty, String? reason, {required String clientUuid}) async {
    // Idempotentlik: bitta chiqarish uchun BITTA uuid (ekran beradi) — timeout'dan keyin
    // qayta bosilsa server dublikat qoldiq kamaytmaydi.
    await _post('/inventory/writeoff',
        {'product_id': productId, 'qty': qty, 'reason': reason, 'client_uuid': clientUuid});
    await _bustCatalog(); // qoldiq kamaydi — kesh eskirdi
  }

  static Future<int> stockCount(List<Map<String, dynamic>> items) async {
    final d = await _post('/inventory/count', {'items': items}) as Map<String, dynamic>;
    await _bustCatalog(); // inventarizatsiya qoldiqni to'g'irladi — kesh eskirdi
    return _i(d['changed']);
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

  static Future<Map<String, dynamic>> commit(List<ReviewItem> items, String? imageB64,
      {String? supplierId, String payment = 'cash', String? source, String? clientUuid}) async {
    // Idempotentlik: bitta savat uchun BITTA uuid (ekran beradi) — timeout'dan keyin
    // qayta bosilsa server o'sha kirimni qaytaradi, dublikat yaratmaydi.
    final res = await _post('/receiving/commit', {
      'client_uuid': clientUuid ?? _uuid(),
      'items': items
          .map((i) => {
                'product_id': i.productId,
                'new_name': i.newName,
                'new_sell_price': i.newSellPrice,
                'new_category_id': i.newCategoryId,
                'new_barcode': i.newBarcode,
                'new_plu': i.newPlu,
                'new_is_weighted': i.newIsWeighted,
                'new_min_qty': i.newMinQty,
                'qty': i.qty,
                'unit_cost': i.unitCost,
                'ai_name': i.aiName,
                'unit': i.unit,
              })
          .toList(),
      'image_b64': imageB64,
      'source': source ?? _lastSource,
      'ai_raw': source == 'manual' ? [] : _lastAiRaw,
      'supplier_id': supplierId,
      'payment': payment,
    }) as Map<String, dynamic>;
    await _bustCatalog(); // kirim (qo'lda/AI) qoldiq va mahsulotni o'zgartirdi — kesh eskirdi
    return res;
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

  static Future<void> createEmployee({required String fullName, String? phone,
      required String roleCode, String? password, String? pin, String? branchId}) async {
    await _post('/employees', {
      'full_name': fullName, 'phone': phone, 'role_code': roleCode,
      if (password != null && password.isNotEmpty) 'password': password,
      if (pin != null && pin.isNotEmpty) 'pin': pin,
      'branch_id': branchId,
    });
  }

  static Future<void> editEmployee(String id, Map<String, dynamic> patch) async {
    final r = await http
        .patch(_u('/employees/$id'), headers: _headers, body: jsonEncode(patch))
        .timeout(const Duration(seconds: 30));
    _decode(r);
  }

  static Future<void> deleteEmployee(String id) async {
    final r = await http.delete(_u('/employees/$id'), headers: _headers)
        .timeout(const Duration(seconds: 30));
    _decode(r);
  }

  static Future<List<PermissionRow>> permissionsList() async {
    final data = await _get('/permissions') as List;
    return data.map((e) => PermissionRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<String>> setPermission(String id, String code, bool allowed) async {
    final r = await http
        .patch(_u('/employees/$id/permissions'), headers: _headers,
            body: jsonEncode({'overrides': {code: allowed}}))
        .timeout(const Duration(seconds: 30));
    final d = _decode(r) as Map<String, dynamic>;
    return ((d['permissions'] as List?) ?? []).map((e) => e.toString()).toList();
  }

  /// Joriy foydalanuvchida ruxsat bormi (login'dagi employee.permissions'dan)
  static bool can(String code) {
    final p = employee?['permissions'];
    if (p is List) return p.contains(code);
    return false;
  }

  static bool get isAdmin => (employee?['role_code'] ?? '') == 'administrator';
  static bool get isOwner => (employee?['role_code'] ?? '') == 'ega';  // do'kon egasi (eng yuqori)

  static Future<List<ReceivingRow>> history() async {
    final data = await _get('/receiving') as List;
    return data.map((e) => ReceivingRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<Map<String, dynamic>> receivingDetail(String id) async {
    return await _get('/receiving/$id') as Map<String, dynamic>;
  }
}

class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);
  @override
  String toString() => message;
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

class ProductLite {
  final String id, name;
  ProductLite({required this.id, required this.name});
  factory ProductLite.fromJson(Map<String, dynamic> j) => ProductLite(id: j['id'].toString(), name: (j['name'] ?? '').toString());
}

/// Ombor bandi — /products javobidan (qoldiq + narx + muddat).
class InvItem {
  final String id, name, unit;
  final double stock, minStock, buyPrice, sellPrice;
  final DateTime? expiry;
  final bool weighted;
  InvItem({
    required this.id, required this.name, required this.unit, required this.stock,
    required this.minStock, required this.buyPrice, required this.sellPrice, required this.expiry, required this.weighted,
  });
  factory InvItem.fromJson(Map<String, dynamic> j) => InvItem(
        id: j['id'].toString(),
        name: (j['name'] ?? '').toString(),
        unit: (j['unit_code'] ?? 'dona').toString(),
        stock: _d(j['stock']),
        minStock: _d(j['min_stock']),
        buyPrice: _d(j['base_buy_price']),
        sellPrice: _d(j['base_sell_price']),
        expiry: j['expiry_date'] == null ? null : DateTime.tryParse(j['expiry_date'].toString()),
        weighted: j['is_weighted'] == true,
      );
  double get stockValue => stock * buyPrice;

  /// 0=ok 1=muddati yaqin 2=kam qoldi 3=tugadi 4=muddati o'tgan
  int status(DateTime today) {
    if (stock <= 0) return 3;
    if (expiry != null && expiry!.isBefore(today)) return 4;
    if (stock <= minStock) return 2;
    if (expiry != null && expiry!.isBefore(today.add(const Duration(days: 7)))) return 1;
    return 0;
  }
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

class Debtor {
  final String id, name;
  final String? phone;
  final double balance;
  Debtor({required this.id, required this.name, required this.phone, required this.balance});
  factory Debtor.fromJson(Map<String, dynamic> j) => Debtor(
        id: (j['id'] ?? '').toString(),
        name: (j['full_name'] ?? '').toString(),
        phone: j['phone']?.toString(),
        balance: _d(j['credit_balance']));
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

class SaleLine {
  final String name;
  final double qty, unitPrice, lineTotal;
  SaleLine({required this.name, required this.qty, required this.unitPrice, required this.lineTotal});
  factory SaleLine.fromJson(Map<String, dynamic> j) => SaleLine(
        name: (j['name_snapshot'] ?? '').toString(),
        qty: _d(j['qty']), unitPrice: _d(j['unit_price']), lineTotal: _d(j['line_total']));
}

class SaleDetail {
  final String id, receiptNo;
  final DateTime? at;
  final double subtotal, discountTotal, total;
  final List<SaleLine> items;
  SaleDetail({required this.id, required this.receiptNo, required this.at, required this.subtotal, required this.discountTotal, required this.total, required this.items});
  factory SaleDetail.fromJson(Map<String, dynamic> j) => SaleDetail(
        id: (j['id'] ?? '').toString(),
        receiptNo: (j['receipt_no'] ?? '').toString(),
        at: serverDt(j['sold_at']),
        subtotal: _d(j['subtotal']), discountTotal: _d(j['discount_total']), total: _d(j['total']),
        items: ((j['items'] as List?) ?? []).map((e) => SaleLine.fromJson(e as Map<String, dynamic>)).toList());
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
  BranchRow({required this.id, required this.name});
  factory BranchRow.fromJson(Map<String, dynamic> j) =>
      BranchRow(id: (j['id'] ?? '').toString(), name: (j['name'] ?? '').toString());
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

class CustHistory {
  final DateTime? at;
  final int items;
  final double amount;
  final String method;
  CustHistory({required this.at, required this.items, required this.amount, required this.method});
  factory CustHistory.fromJson(Map<String, dynamic> j) => CustHistory(
        at: serverDt(j['date']),
        items: _i(j['items']), amount: _d(j['amount']), method: (j['method'] ?? 'cash').toString());
}

class CustPayment {
  final DateTime? at;
  final double amount;
  CustPayment({required this.at, required this.amount});
  factory CustPayment.fromJson(Map<String, dynamic> j) => CustPayment(
        at: serverDt(j['date']), amount: _d(j['amount']));
}

class CustomerDetail {
  final String id, code, fullName;
  final String? phone;
  final double creditBalance, totalSpent;
  final int visits;
  final List<CustHistory> history;
  final List<CustPayment> payments;
  CustomerDetail({required this.id, required this.code, required this.fullName, required this.phone,
      required this.creditBalance, required this.totalSpent, required this.visits, required this.history, required this.payments});
  factory CustomerDetail.fromJson(Map<String, dynamic> j) => CustomerDetail(
        id: (j['id'] ?? '').toString(), code: (j['code'] ?? '').toString(), fullName: (j['full_name'] ?? '').toString(),
        phone: j['phone']?.toString(), creditBalance: _d(j['credit_balance']), totalSpent: _d(j['total_spent']),
        visits: _i(j['visits']),
        history: ((j['history'] as List?) ?? []).map((e) => CustHistory.fromJson(e as Map<String, dynamic>)).toList(),
        payments: ((j['payments'] as List?) ?? []).map((e) => CustPayment.fromJson(e as Map<String, dynamic>)).toList());
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

/// AI skan natijasidagi bitta qator (mahsulot taklifi).
class ScanItem {
  final String aiName;
  double qty;
  final String unit;
  final double? price;
  String? productId;
  String? matchedName;
  final double confidence;
  double unitCost;
  ScanItem({
    required this.aiName, required this.qty, required this.unit, required this.price,
    required this.productId, required this.matchedName, required this.confidence, required this.unitCost,
  });
  factory ScanItem.fromJson(Map<String, dynamic> j) => ScanItem(
        aiName: (j['ai_name'] ?? '').toString(),
        qty: _d(j['qty']),
        unit: (j['unit'] ?? 'dona').toString(),
        price: j['price'] == null ? null : _d(j['price']),
        productId: j['product_id']?.toString(),
        matchedName: j['matched_name']?.toString(),
        confidence: _d(j['confidence']),
        unitCost: _d(j['unit_cost']),
      );
  bool get matched => productId != null;
}

/// Tasdiqlash uchun yakuniy qator.
class ReviewItem {
  String? productId;        // mavjud mahsulot
  String? newName;          // yoki yangi mahsulot nomi
  double? newSellPrice;
  String? newCategoryId;    // yangi mahsulot kategoriyasi (ixtiyoriy)
  String? newBarcode;       // skanerlangan shtrix-kod (bazada yo'q bo'lsa biriktiriladi)
  String? newPlu;           // tarozi PLU (kg mahsulot uchun majburiy)
  bool? newIsWeighted;      // kg/tarozi mahsulotimi
  double? newMinQty;        // min qoldiq (Manager formasi pariteti)
  String name;
  double qty;
  double unitCost;
  String unit;
  String? aiName;
  ReviewItem({this.productId, this.newName, this.newSellPrice, this.newCategoryId, this.newBarcode,
      this.newPlu, this.newIsWeighted, this.newMinQty,
      required this.name, required this.qty, required this.unitCost, required this.unit, this.aiName});
}

class CategoryLite {
  final String id, name;
  CategoryLite({required this.id, required this.name});
  factory CategoryLite.fromJson(Map<String, dynamic> j) =>
      CategoryLite(id: j['id'].toString(), name: (j['name'] ?? '').toString());
}

/// Sotuv statistikasi (davr bo'yicha): soni, tushum, foyda.
class SalesStat {
  final double qty, revenue, profit;
  SalesStat({required this.qty, required this.revenue, required this.profit});
  factory SalesStat.fromJson(Map<String, dynamic>? j) => SalesStat(
        qty: _d(j?['qty']), revenue: _d(j?['revenue']), profit: _d(j?['profit']));
}

/// Mahsulot to'liq ma'lumoti (batafsil oyna uchun).
class ProductDetail {
  final String id, name, unit;
  final double buyPrice, sellPrice, profitUnit, marginPct, stock, minStock, monthIn, monthOut;
  final SalesStat sales7d, sales30d;
  final DateTime? lastSoldAt, expiry;
  final List<String> barcodes;
  final String createdByName;
  final bool weighted;
  final String? pluCode;
  ProductDetail({
    required this.id, required this.name, required this.unit,
    required this.buyPrice, required this.sellPrice, required this.profitUnit, required this.marginPct,
    required this.stock, required this.minStock, required this.monthIn, required this.monthOut,
    required this.sales7d, required this.sales30d, required this.lastSoldAt, required this.expiry,
    required this.barcodes, required this.createdByName, required this.weighted, required this.pluCode,
  });
  double get stockValue => stock * buyPrice;
  factory ProductDetail.fromJson(Map<String, dynamic> j) => ProductDetail(
        id: j['id'].toString(),
        name: (j['name'] ?? '').toString(),
        unit: (j['unit_code'] ?? 'dona').toString(),
        buyPrice: _d(j['base_buy_price']),
        sellPrice: _d(j['base_sell_price']),
        profitUnit: _d(j['profit_unit']),
        marginPct: _d(j['margin_pct']),
        stock: _d(j['stock']),
        minStock: _d(j['min_stock']),
        monthIn: _d(j['month_in']),
        monthOut: _d(j['month_out']),
        sales7d: SalesStat.fromJson((j['sales_7d'] as Map?)?.cast<String, dynamic>()),
        sales30d: SalesStat.fromJson((j['sales_30d'] as Map?)?.cast<String, dynamic>()),
        lastSoldAt: serverDt(j['last_sold_at']),
        expiry: j['expiry_date'] == null ? null : DateTime.tryParse(j['expiry_date'].toString()),
        barcodes: ((j['barcodes'] as List?) ?? []).map((e) => e.toString()).toList(),
        createdByName: (j['created_by_name'] ?? '—').toString(),
        weighted: j['is_weighted'] == true,
        pluCode: j['plu_code']?.toString(),
      );
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

class ReceivingRow {
  final String id;
  final DateTime? at;
  final String source, employee;
  final int totalTypes;
  final double totalQty;
  ReceivingRow({required this.id, required this.at, required this.source, required this.employee, required this.totalTypes, required this.totalQty});
  factory ReceivingRow.fromJson(Map<String, dynamic> j) => ReceivingRow(
        id: j['id'].toString(),
        at: serverDt(j['at']),
        source: (j['source'] ?? '').toString(),
        employee: (j['employee'] ?? '').toString(),
        totalTypes: _i(j['total_types']),
        totalQty: _d(j['total_qty']),
      );
}
