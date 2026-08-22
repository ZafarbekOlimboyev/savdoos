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

  static Future<void> cashOp(String type, double amount, String? reason) async {
    await _post('/cash/ops', {'type': type, 'amount': amount, 'reason': reason});
  }

  static Future<List<CashOpRow>> cashOps() async {
    final data = await _get('/cash/ops') as List;
    return data.map((e) => CashOpRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<List<BranchRow>> branches() async {
    final d = await _get('/branches') as Map<String, dynamic>;
    return ((d['branches'] as List?) ?? []).map((e) => BranchRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<Map<String, dynamic>> transfer(String fromId, String toId, List<(String, double)> items) async {
    return await _post('/inventory/transfer', {
      'from_branch_id': fromId,
      'to_branch_id': toId,
      'items': items.map((i) => {'product_id': i.$1, 'qty': i.$2}).toList(),
      'client_uuid': _uuid(),
    }) as Map<String, dynamic>;
  }

  static String _uuid() {
    final r = DateTime.now().microsecondsSinceEpoch;
    final rnd = (r ^ (r >> 13)).toRadixString(16).padLeft(12, '0');
    return '${rnd.substring(0, 8)}-${rnd.substring(8, 12)}-4000-8000-${r.toRadixString(16).padLeft(12, '0').substring(0, 12)}';
  }

  static Future<List<SupplierRow>> suppliers() async {
    final data = await _get('/suppliers') as List;
    return data.map((e) => SupplierRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> paySupplier(String id, double amount) async {
    await _post('/suppliers/$id/payments', {'amount': amount});
  }

  static Future<List<Debtor>> customers({bool onlyDebt = false}) async {
    final data = await _get('/customers${onlyDebt ? '?only_debt=true' : ''}') as List;
    return data.map((e) => Debtor.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> payCredit(String customerId, double amount) async {
    await _post('/customers/$customerId/payments', {'amount': amount});
  }

  static Future<CustomerDetail> customerDetail(String id) async {
    return CustomerDetail.fromJson(await _get('/customers/$id/detail') as Map<String, dynamic>);
  }

  static Future<void> changePassword(String? oldPw, String newPw) async {
    await _post('/auth/password', {'old_password': oldPw, 'new_password': newPw});
  }

  static Future<void> writeoff(String productId, double qty, String? reason) async {
    await _post('/inventory/writeoff', {'product_id': productId, 'qty': qty, 'reason': reason});
  }

  static Future<int> stockCount(List<Map<String, dynamic>> items) async {
    final d = await _post('/inventory/count', {'items': items}) as Map<String, dynamic>;
    return _i(d['changed']);
  }

  static Future<Map<String, dynamic>> commit(List<ReviewItem> items, String? imageB64,
      {String? supplierId, String payment = 'cash'}) async {
    return await _post('/receiving/commit', {
      'items': items
          .map((i) => {
                'product_id': i.productId,
                'new_name': i.newName,
                'new_sell_price': i.newSellPrice,
                'qty': i.qty,
                'unit_cost': i.unitCost,
                'ai_name': i.aiName,
                'unit': i.unit,
              })
          .toList(),
      'image_b64': imageB64,
      'source': _lastSource,
      'ai_raw': _lastAiRaw,
      'supplier_id': supplierId,
      'payment': payment,
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
        at: j['sold_at'] == null ? null : DateTime.tryParse(j['sold_at'].toString())?.toLocal(),
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
        at: j['at'] == null ? null : DateTime.tryParse(j['at'].toString())?.toLocal(),
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
        at: j['sold_at'] == null ? null : DateTime.tryParse(j['sold_at'].toString())?.toLocal(),
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
        at: j['at'] == null ? null : DateTime.tryParse(j['at'].toString())?.toLocal());
}

class BranchRow {
  final String id, name;
  BranchRow({required this.id, required this.name});
  factory BranchRow.fromJson(Map<String, dynamic> j) =>
      BranchRow(id: (j['id'] ?? '').toString(), name: (j['name'] ?? '').toString());
}

class CustHistory {
  final DateTime? at;
  final int items;
  final double amount;
  final String method;
  CustHistory({required this.at, required this.items, required this.amount, required this.method});
  factory CustHistory.fromJson(Map<String, dynamic> j) => CustHistory(
        at: j['date'] == null ? null : DateTime.tryParse(j['date'].toString())?.toLocal(),
        items: _i(j['items']), amount: _d(j['amount']), method: (j['method'] ?? 'cash').toString());
}

class CustPayment {
  final DateTime? at;
  final double amount;
  CustPayment({required this.at, required this.amount});
  factory CustPayment.fromJson(Map<String, dynamic> j) => CustPayment(
        at: j['date'] == null ? null : DateTime.tryParse(j['date'].toString())?.toLocal(), amount: _d(j['amount']));
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
  String name;
  double qty;
  double unitCost;
  String unit;
  String? aiName;
  ReviewItem({this.productId, this.newName, this.newSellPrice, required this.name, required this.qty, required this.unitCost, required this.unit, this.aiName});
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
