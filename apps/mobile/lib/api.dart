import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// SavdoOS backend (Railway) bilan ishlovchi klient. Server manzili Sozlamalarda o'zgaradi.
class Api {
  static const _defaultBase = 'https://savdoos-production.up.railway.app';
  static String baseUrl = _defaultBase;
  static String? token;
  static Map<String, dynamic>? employee;

  static Uri _u(String path) => Uri.parse('$baseUrl/api/v1$path');
  static Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  // ── Sessiya saqlash ──
  static Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    baseUrl = p.getString('base_url') ?? _defaultBase;
    token = p.getString('token');
    final e = p.getString('employee');
    if (e != null) employee = jsonDecode(e) as Map<String, dynamic>;
  }

  static Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('base_url', baseUrl);
    if (token != null) await p.setString('token', token!);
    if (employee != null) await p.setString('employee', jsonEncode(employee));
  }

  static Future<void> setBaseUrl(String url) async {
    baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    await _save();
  }

  static Future<void> logout() async {
    token = null;
    employee = null;
    final p = await SharedPreferences.getInstance();
    await p.remove('token');
    await p.remove('employee');
  }

  static bool get loggedIn => token != null;

  // ── So'rovlar ──
  static Future<dynamic> _get(String path) async {
    final r = await http.get(_u(path), headers: _headers).timeout(const Duration(seconds: 30));
    return _decode(r);
  }

  static Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final r = await http
        .post(_u(path), headers: _headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 60));
    return _decode(r);
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
        : 'Xatolik (${r.statusCode})';
    throw ApiException(r.statusCode, msg.toString());
  }

  static Future<void> login(String phone, String password) async {
    final data = await _post('/auth/login/password', {'phone': phone, 'password': password});
    token = data['access_token'] as String;
    employee = data['employee'] as Map<String, dynamic>?;
    await _save();
  }

  static Future<Overview> overview(String period) async {
    return Overview.fromJson(await _get('/reports/overview?period=$period') as Map<String, dynamic>);
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

  static Future<List<CatRow>> categories(String period) async {
    final data = await _get('/reports/categories?period=$period') as List;
    return data.map((e) => CatRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<DebtInfo> debt() async {
    final d = await _get('/reports/dashboard') as Map<String, dynamic>;
    return DebtInfo.fromJson((d['debt'] as Map?)?.cast<String, dynamic>() ?? {});
  }

  static Future<Map<String, dynamic>> commit(List<ReviewItem> items, String? imageB64) async {
    return await _post('/receiving/commit', {
      'items': items
          .map((i) => {
                'product_id': i.productId,
                'qty': i.qty,
                'unit_cost': i.unitCost,
                'ai_name': i.aiName,
                'unit': i.unit,
              })
          .toList(),
      'image_b64': imageB64,
      'source': _lastSource,
      'ai_raw': _lastAiRaw,
    }) as Map<String, dynamic>;
  }

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
  String productId;
  String name;
  double qty;
  double unitCost;
  String unit;
  String? aiName;
  ReviewItem({required this.productId, required this.name, required this.qty, required this.unitCost, required this.unit, this.aiName});
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
        at: j['at'] == null ? null : DateTime.tryParse(j['at'].toString())?.toLocal(),
        source: (j['source'] ?? '').toString(),
        employee: (j['employee'] ?? '').toString(),
        totalTypes: _i(j['total_types']),
        totalQty: _d(j['total_qty']),
      );
}
