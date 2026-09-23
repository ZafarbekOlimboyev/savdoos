/// Package M4 — customers/debt, suppliers, cash operations, sales and the
/// server receipt (`binos.receipt.v1`).
///
/// Every call goes through the core JSON helpers ([Api.getJson] & co.), so a
/// failure is ALWAYS an [ApiException] (network, auth, permission, business…)
/// and a write is reported as done only after a 2xx.
///
/// Money is carried as integer CENTS and quantities as integer MILLI (see
/// `qty.dart`); binary doubles appear only when a request body is encoded
/// ([centsToJson]). Nothing here computes an accounting figure: balances,
/// totals and receipts are exactly what the server stored.
library;

import '../api.dart';
import '../l10n.dart';
import '../qty.dart';

// ─────────────────────────── helpers ───────────────────────────

String _s(Object? v) => v == null ? '' : '$v';
String? _ns(Object? v) {
  final s = v?.toString().trim();
  return (s == null || s.isEmpty) ? null : s;
}

int _int(Object? v) => v is num ? v.toInt() : int.tryParse('${v ?? ''}') ?? 0;

List<Map<String, dynamic>> _maps(Object? v) => [
      for (final e in (v is List ? v : const []))
        if (e is Map) e.cast<String, dynamic>()
    ];

/// Payment methods the debt / supplier payment endpoints accept.
const List<String> kPaymentMethods = ['cash', 'card', 'qr'];

/// Localized label of a payment method code (`cash`, `card`, `qr`, `credit`).
String paymentMethodLabel(String method) => switch (method) {
      'cash' => tr('Naqd'),
      'card' => tr('Karta'),
      'qr' => 'QR',
      'credit' => tr('Nasiya'),
      _ => method,
    };

// ─────────────────────────── customers ───────────────────────────

/// `CustomerOut` — one customer of the list.
class CustomerRow {
  /// Creates a row.
  const CustomerRow({required this.id, required this.code, required this.fullName, this.phone, required this.balanceCents});

  /// Parses `{id, code, full_name, phone, credit_balance}`.
  factory CustomerRow.fromJson(Map<String, dynamic> j) => CustomerRow(
        id: _s(j['id']),
        code: _s(j['code']),
        fullName: _s(j['full_name']),
        phone: _ns(j['phone']),
        balanceCents: centsFromNum(j['credit_balance']),
      );

  /// Customer id.
  final String id;

  /// Store code (`M-1001`).
  final String code;

  /// Full name.
  final String fullName;

  /// Canonical phone (`+996700111222`) or null.
  final String? phone;

  /// Credit balance in cents: > 0 the customer owes the store (debt),
  /// < 0 the store owes the customer (advance).
  final int balanceCents;

  /// True when the customer owes money.
  bool get hasDebt => balanceCents > 0;
}

/// One purchase of `GET /customers/{id}/detail.history`.
class CustomerPurchase {
  /// Creates an entry.
  const CustomerPurchase({
    required this.at,
    required this.items,
    required this.amountCents,
    required this.method,
    this.saleId,
    this.receiptNo,
    this.qtyMilli,
  });

  /// Parses `{date, items, amount, method, sale_id?, receipt_no?, items_qty?}`
  /// (the last three are absent on a server before Phase 5G).
  factory CustomerPurchase.fromJson(Map<String, dynamic> j) => CustomerPurchase(
        at: serverDt(j['date']),
        items: _int(j['items']),
        amountCents: centsFromNum(j['amount']),
        method: _s(j['method'] ?? 'cash'),
        saleId: _ns(j['sale_id']),
        receiptNo: _ns(j['receipt_no']),
        qtyMilli: j['items_qty'] == null ? null : scaledFromServer(j['items_qty'], 3),
      );

  /// Sale time (local).
  final DateTime? at;

  /// Item count as the server reports it (whole units, truncated).
  final int items;

  /// Sale total in cents.
  final int amountCents;

  /// First payment method of the sale.
  final String method;

  /// Sale id (opens the receipt), or null on an older server.
  final String? saleId;

  /// Receipt number, or null on an older server.
  final String? receiptNo;

  /// Exact quantity sum of the sale's lines in milli (weighed goods keep
  /// their fraction), or null on an older server.
  final int? qtyMilli;
}

/// Quantity text with exactly 3 decimals when fractional (`3500` ->
/// `"3,500"`, `3000` -> `"3"`, `1234500` -> `"1 234,500"`).
String formatQty3(int milli) {
  if (milli % kMilli == 0) return formatMilli(milli, group: true);
  final a = milli.abs();
  final whole = formatMilli((a ~/ kMilli) * kMilli, group: true);
  return '${milli < 0 ? '-' : ''}$whole,${(a % kMilli).toString().padLeft(3, '0')}';
}

/// One debt payment of `GET /customers/{id}/detail.payments`.
class CustomerPaymentEntry {
  /// Creates an entry.
  const CustomerPaymentEntry({required this.at, required this.amountCents, this.method});

  /// Parses `{date, amount, method?}` (`method` is absent before Phase 5G).
  factory CustomerPaymentEntry.fromJson(Map<String, dynamic> j) => CustomerPaymentEntry(
      at: serverDt(j['date']), amountCents: centsFromNum(j['amount']), method: _ns(j['method']));

  /// Payment time (local).
  final DateTime? at;

  /// Amount in cents.
  final int amountCents;

  /// Stored payment method (`cash` / `card` / `qr`), or null on an older server.
  final String? method;
}

/// `GET /customers/{id}/detail`.
class CustomerProfile {
  /// Creates a profile.
  const CustomerProfile({
    required this.id,
    required this.code,
    required this.fullName,
    this.phone,
    required this.balanceCents,
    required this.totalSpentCents,
    required this.visits,
    this.history = const [],
    this.payments = const [],
  });

  /// Parses the detail payload.
  factory CustomerProfile.fromJson(Map<String, dynamic> j) => CustomerProfile(
        id: _s(j['id']),
        code: _s(j['code']),
        fullName: _s(j['full_name']),
        phone: _ns(j['phone']),
        balanceCents: centsFromNum(j['credit_balance']),
        totalSpentCents: centsFromNum(j['total_spent']),
        visits: _int(j['visits']),
        history: [for (final m in _maps(j['history'])) CustomerPurchase.fromJson(m)],
        payments: [for (final m in _maps(j['payments'])) CustomerPaymentEntry.fromJson(m)],
      );

  /// Customer id.
  final String id;

  /// Store code.
  final String code;

  /// Full name.
  final String fullName;

  /// Phone or null.
  final String? phone;

  /// Credit balance in cents (> 0 debt, < 0 advance).
  final int balanceCents;

  /// Total of non-voided sales in cents.
  final int totalSpentCents;

  /// Number of non-voided sales.
  final int visits;

  /// Last purchases (newest first, at most 10).
  final List<CustomerPurchase> history;

  /// Last debt payments (newest first, at most 10).
  final List<CustomerPaymentEntry> payments;

  /// The row shape (for editing).
  CustomerRow get row => CustomerRow(id: id, code: code, fullName: fullName, phone: phone, balanceCents: balanceCents);
}

/// Answer of a debt payment.
class DebtPaymentResult {
  /// Creates a result.
  const DebtPaymentResult({required this.customerId, required this.balanceCents});

  /// Parses `{customer_id, credit_balance}`.
  factory DebtPaymentResult.fromJson(Map<String, dynamic> j) =>
      DebtPaymentResult(customerId: _s(j['customer_id']), balanceCents: centsFromNum(j['credit_balance']));

  /// Customer id.
  final String customerId;

  /// Debt left after the payment (cents).
  final int balanceCents;
}

// ─────────────────────────── suppliers ───────────────────────────

/// `SupplierOut` — one supplier of the list.
class SupplierRowM {
  /// Creates a row.
  const SupplierRowM({required this.id, required this.name, this.phone, required this.balanceCents});

  /// Parses `{id, name, phone, balance}`.
  factory SupplierRowM.fromJson(Map<String, dynamic> j) => SupplierRowM(
        id: _s(j['id']),
        name: _s(j['name']),
        phone: _ns(j['phone']),
        balanceCents: centsFromNum(j['balance']),
      );

  /// Supplier id.
  final String id;

  /// Name.
  final String name;

  /// Phone or null.
  final String? phone;

  /// What the STORE owes the supplier, in cents (> 0 = our debt).
  final int balanceCents;

  /// True when the store owes this supplier.
  bool get weOwe => balanceCents > 0;
}

/// One product line of the supplier detail.
class SupplierProduct {
  /// Creates a line.
  const SupplierProduct({required this.name, required this.qtyMilli, required this.costCents, required this.profitCents});

  /// Parses `{name, qty, cost, profit}`.
  factory SupplierProduct.fromJson(Map<String, dynamic> j) => SupplierProduct(
        name: _s(j['name']),
        qtyMilli: milliFromNum(j['qty']),
        costCents: centsFromNum(j['cost']),
        profitCents: centsFromNum(j['profit']),
      );

  /// Product name.
  final String name;

  /// Total quantity received (milli).
  final int qtyMilli;

  /// Total purchase cost (cents).
  final int costCents;

  /// Expected profit at the current sell price (cents).
  final int profitCents;
}

/// One purchase document of the supplier detail.
class SupplierPurchase {
  /// Creates an entry.
  const SupplierPurchase({required this.id, required this.docNo, this.date, required this.totalCents, required this.status});

  /// Parses `{id, doc_no, date, total, status}`.
  factory SupplierPurchase.fromJson(Map<String, dynamic> j) => SupplierPurchase(
        id: _s(j['id']),
        docNo: _s(j['doc_no']),
        date: _ns(j['date']),
        totalCents: centsFromNum(j['total']),
        status: _s(j['status']),
      );

  /// Purchase id.
  final String id;

  /// Document number.
  final String docNo;

  /// Purchase date (`YYYY-MM-DD`).
  final String? date;

  /// Document total (cents).
  final int totalCents;

  /// `received | paid | partial | debt | draft | cancelled`.
  final String status;
}

/// Localized purchase status.
String purchaseStatusLabel(String s) => switch (s) {
      'received' => tr('Qabul qilingan'),
      'paid' => tr('To‘langan'),
      'partial' => tr('Qisman to‘langan'),
      'debt' => tr('Qarzga'),
      'draft' => tr('Qoralama'),
      'cancelled' => tr('Bekor qilingan'),
      _ => s,
    };

/// `GET /suppliers/{id}`.
class SupplierProfile {
  /// Creates a profile.
  const SupplierProfile({
    required this.id,
    required this.name,
    this.phone,
    required this.balanceCents,
    this.purchaseCount = 0,
    this.totalPurchasedCents = 0,
    this.paidTotalCents = 0,
    this.productTypes = 0,
    this.totalQtyMilli = 0,
    this.avgPurchaseCents = 0,
    this.expectedProfitCents = 0,
    this.profitMarginPct = 0,
    this.lastPurchase,
    this.products = const [],
    this.recentPurchases = const [],
  });

  /// Parses the detail payload.
  factory SupplierProfile.fromJson(Map<String, dynamic> j) {
    final margin = j['profit_margin'];
    return SupplierProfile(
      id: _s(j['id']),
      name: _s(j['name']),
      phone: _ns(j['phone']),
      balanceCents: centsFromNum(j['balance']),
      purchaseCount: _int(j['purchase_count']),
      totalPurchasedCents: centsFromNum(j['total_purchased']),
      paidTotalCents: centsFromNum(j['paid_total']),
      productTypes: _int(j['product_types']),
      totalQtyMilli: milliFromNum(j['total_qty']),
      avgPurchaseCents: centsFromNum(j['avg_purchase']),
      expectedProfitCents: centsFromNum(j['expected_profit']),
      profitMarginPct: margin is num ? margin.toDouble() : double.tryParse('${margin ?? ''}') ?? 0,
      lastPurchase: _ns(j['last_purchase']),
      products: [for (final m in _maps(j['products'])) SupplierProduct.fromJson(m)],
      recentPurchases: [for (final m in _maps(j['recent_purchases'])) SupplierPurchase.fromJson(m)],
    );
  }

  /// Supplier id.
  final String id;

  /// Name.
  final String name;

  /// Phone or null.
  final String? phone;

  /// What the store owes (cents).
  final int balanceCents;

  /// Number of purchase documents.
  final int purchaseCount;

  /// Sum of purchase cost (cents).
  final int totalPurchasedCents;

  /// Paid so far (cents).
  final int paidTotalCents;

  /// Distinct products supplied.
  final int productTypes;

  /// Total quantity supplied (milli).
  final int totalQtyMilli;

  /// Average purchase (cents).
  final int avgPurchaseCents;

  /// Expected profit at current prices (cents).
  final int expectedProfitCents;

  /// Expected margin, percent (display only, from the server).
  final double profitMarginPct;

  /// Date of the last purchase (`YYYY-MM-DD`).
  final String? lastPurchase;

  /// Products supplied (by cost, desc).
  final List<SupplierProduct> products;

  /// Recent purchase documents (newest first, at most 40).
  final List<SupplierPurchase> recentPurchases;

  /// The row shape (for editing / paying).
  SupplierRowM get row => SupplierRowM(id: id, name: name, phone: phone, balanceCents: balanceCents);
}

/// One entry of `GET /suppliers/{id}/ledger`.
class SupplierLedgerEntry {
  /// Creates an entry.
  const SupplierLedgerEntry(
      {required this.type, required this.amountCents, required this.balanceAfterCents, this.refType, this.at});

  /// Parses `{type, amount, balance_after, ref_type, at}`.
  factory SupplierLedgerEntry.fromJson(Map<String, dynamic> j) => SupplierLedgerEntry(
        type: _s(j['type']),
        amountCents: centsFromNum(j['amount']),
        balanceAfterCents: centsFromNum(j['balance_after']),
        refType: _ns(j['ref_type']),
        at: serverDt(j['at']),
      );

  /// Ledger type (`purchase`, `payment`, `adjustment`, …).
  final String type;

  /// Signed amount (cents): + increases our debt, − decreases it.
  final int amountCents;

  /// Our debt after this entry (cents).
  final int balanceAfterCents;

  /// Source document kind (`purchase`, `payment`, `correction`, …).
  final String? refType;

  /// Entry time (local).
  final DateTime? at;

  /// Localized description.
  String get label {
    final r = refType ?? type;
    return switch (r) {
      'payment' => tr('To‘lov'),
      'purchase' => tr('Xarid'),
      'receiving' => tr('Tovar qabul'),
      'purchase_edit' => tr('Xarid tahriri'),
      'receiving_correction' => tr('Qabul tuzatildi'),
      'return' || 'purchase_return' => tr('Qaytarish'),
      _ => amountCents < 0 ? tr('Qarz kamaydi') : tr('Qarz oshdi'),
    };
  }
}

/// Answer of a supplier payment.
class SupplierPaymentResult {
  /// Creates a result.
  const SupplierPaymentResult(
      {required this.supplierId, required this.balanceCents, required this.paidCents, this.duplicate = false});

  /// Parses `{supplier_id, balance, paid, duplicate?}`.
  factory SupplierPaymentResult.fromJson(Map<String, dynamic> j) => SupplierPaymentResult(
        supplierId: _s(j['supplier_id']),
        balanceCents: centsFromNum(j['balance']),
        paidCents: centsFromNum(j['paid']),
        duplicate: j['duplicate'] == true,
      );

  /// Supplier id.
  final String supplierId;

  /// Our debt after the payment (cents).
  final int balanceCents;

  /// What the server actually recorded (clamped to the debt), cents.
  final int paidCents;

  /// The same `client_uuid` was already recorded earlier — nothing new was written.
  final bool duplicate;
}

// ─────────────────────────── cash operations ───────────────────────────

/// Cash operation types `POST /cash/ops` accepts.
abstract final class CashOpType {
  /// Cash put INTO the drawer.
  static const payin = 'payin';

  /// Cash spent from the drawer.
  static const expense = 'expense';

  /// Cash moved from the drawer to a SAFE (requires `destination_safe_id`).
  static const collection = 'collection';
}

/// Localized label of a cash movement type.
String cashOpLabel(String type) => switch (type) {
      'payin' => tr('Kirim'),
      'expense' => tr('Xarajat'),
      'collection' => tr('Inkassatsiya'),
      'payout' => tr('Naqd chiqim'),
      'opening' => tr('Smena ochildi'),
      _ => type,
    };

/// One entry of `GET /cash/ops` (today, visible branches).
class CashOpEntry {
  /// Creates an entry.
  const CashOpEntry({required this.type, required this.amountCents, this.reason, this.employee, this.at});

  /// Parses `{type, amount, reason, employee, at}`.
  factory CashOpEntry.fromJson(Map<String, dynamic> j) => CashOpEntry(
        type: _s(j['type']),
        amountCents: centsFromNum(j['amount']),
        reason: _ns(j['reason']),
        employee: _ns(j['employee']),
        at: serverDt(j['at']),
      );

  /// Movement type.
  final String type;

  /// Amount (cents, positive).
  final int amountCents;

  /// Operator note.
  final String? reason;

  /// Who recorded it.
  final String? employee;

  /// When (local).
  final DateTime? at;

  /// True for cash coming INTO the drawer.
  bool get isIn => type == CashOpType.payin || type == 'opening';
}

/// Answer of `POST /cash/ops`.
class CashOpResult {
  /// Creates a result.
  const CashOpResult({this.shiftId, this.duplicate = false});

  /// Parses `{ok, shift_id, duplicate?}`.
  factory CashOpResult.fromJson(Map<String, dynamic> j) =>
      CashOpResult(shiftId: _ns(j['shift_id']), duplicate: j['duplicate'] == true);

  /// Shift the movement was written to.
  final String? shiftId;

  /// The same `client_uuid` was already recorded — nothing new was written.
  final bool duplicate;
}

// ─────────────────────────── sales ───────────────────────────

/// `GET /sales` row.
class SaleSummary {
  /// Creates a row.
  const SaleSummary({
    required this.id,
    required this.receiptNo,
    this.at,
    this.cashier = '',
    this.method = 'cash',
    this.itemCountMilli = 0,
    this.firstItem = '',
    required this.totalCents,
    this.branchName,
    this.tillCode,
  });

  /// Parses a list row.
  factory SaleSummary.fromJson(Map<String, dynamic> j) => SaleSummary(
        id: _s(j['id']),
        receiptNo: _s(j['receipt_no']),
        at: serverDt(j['sold_at']),
        cashier: _s(j['cashier_name'] ?? j['cashier']),
        method: _s(j['method'] ?? 'cash'),
        itemCountMilli: milliFromNum(j['item_count']),
        firstItem: _s(j['first_item']),
        totalCents: centsFromNum(j['total']),
        branchName: _ns(j['branch_name']),
        tillCode: _ns(j['till_code']),
      );

  /// Sale id.
  final String id;

  /// Receipt number (`#123`).
  final String receiptNo;

  /// Sale time (local).
  final DateTime? at;

  /// Cashier name (sale-time snapshot).
  final String cashier;

  /// FIRST payment method (split payments: see the receipt).
  final String method;

  /// Sum of line quantities (milli).
  final int itemCountMilli;

  /// Name of the first line.
  final String firstItem;

  /// Sale total (cents).
  final int totalCents;

  /// Branch name snapshot.
  final String? branchName;

  /// Till code snapshot.
  final String? tillCode;
}

/// Sales list period filter (`GET /sales?period=`).
enum SalesPeriod {
  /// Today (store local day).
  today,

  /// The last 7 local days.
  week,

  /// The current month.
  month,

  /// No period filter.
  all,
}

// ─────────────────────────── receipt (binos.receipt.v1) ───────────────────────────

/// One line of a receipt. Money/qty are the server's decimal strings.
class ReceiptLine {
  /// Creates a line.
  const ReceiptLine({
    required this.name,
    required this.qty,
    this.unit,
    this.weighted = false,
    required this.unitPrice,
    required this.gross,
    required this.discount,
    required this.total,
  });

  /// Parses `{name, qty, unit, weighted, unit_price, gross, discount, total}`.
  factory ReceiptLine.fromJson(Map<String, dynamic> j) => ReceiptLine(
        name: _s(j['name']),
        qty: _s(j['qty']),
        unit: _ns(j['unit']),
        weighted: j['weighted'] == true,
        unitPrice: _s(j['unit_price']),
        gross: _s(j['gross']),
        discount: _s(j['discount']),
        total: _s(j['total']),
      );

  /// Product name (sale-time snapshot).
  final String name;

  /// Quantity, 3 decimals (`"0.352"`).
  final String qty;

  /// Unit code or null.
  final String? unit;

  /// Weighed product (qty always shown with 3 decimals).
  final bool weighted;

  /// Unit price, 2 decimals.
  final String unitPrice;

  /// qty × price, 2 decimals.
  final String gross;

  /// Line discount, 2 decimals.
  final String discount;

  /// Line total, 2 decimals.
  final String total;
}

/// One payment of a sale receipt.
class ReceiptPayment {
  /// Creates a payment.
  const ReceiptPayment({required this.method, required this.amount, this.given, this.change});

  /// Parses `{method, amount, given, change}`.
  factory ReceiptPayment.fromJson(Map<String, dynamic> j) => ReceiptPayment(
        method: _s(j['method']),
        amount: _s(j['amount']),
        given: _ns(j['given']),
        change: _ns(j['change']),
      );

  /// `cash | card | qr | credit`.
  final String method;

  /// Amount, 2 decimals.
  final String amount;

  /// Cash handed over (cash only) or null.
  final String? given;

  /// Change returned or null.
  final String? change;
}

/// The subset of the effective receipt template that decides what is shown.
class ReceiptTemplateView {
  /// Creates a template (defaults = server BUILTIN).
  const ReceiptTemplateView({
    this.header,
    this.footer,
    this.storeDisplayName,
    this.address,
    this.phone,
    this.showBranch = true,
    this.showStir = true,
    this.showCashier = true,
    this.showTill = false,
    this.showPaymentBreakdown = true,
    this.showDiscount = true,
    this.showCustomer = false,
  });

  /// Parses `template` — a missing/odd field keeps the BUILTIN default.
  factory ReceiptTemplateView.fromJson(Map<String, dynamic>? j) {
    bool b(String k, bool d) => j?[k] is bool ? j![k] as bool : d;
    return ReceiptTemplateView(
      header: _ns(j?['header']),
      footer: _ns(j?['footer']),
      storeDisplayName: _ns(j?['store_display_name']),
      address: _ns(j?['address']),
      phone: _ns(j?['phone']),
      showBranch: b('show_branch', true),
      showStir: b('show_stir', true),
      showCashier: b('show_cashier', true),
      showTill: b('show_till', false),
      showPaymentBreakdown: b('show_payment_breakdown', true),
      showDiscount: b('show_discount', true),
      showCustomer: b('show_customer', false),
    );
  }

  /// Header (slogan) text.
  final String? header;

  /// Footer text (null = the default thank-you line).
  final String? footer;

  /// Store name override.
  final String? storeDisplayName;

  /// Address override.
  final String? address;

  /// Phone override.
  final String? phone;

  /// Visibility switches (server template).
  final bool showBranch, showStir, showCashier, showTill, showPaymentBreakdown, showDiscount, showCustomer;
}

/// Server receipt DTO `binos.receipt.v1` (`GET /sales/{id}/receipt`,
/// `GET /returns/{id}/receipt`). Amounts are POSITIVE decimal strings; the
/// RETURN sign is added by the renderer.
class Receipt {
  /// Creates a receipt.
  const Receipt({
    required this.schema,
    required this.kind,
    this.test = false,
    this.provisional = false,
    this.docId,
    required this.number,
    this.uid,
    this.issuedAt,
    this.issuedAtLocal,
    this.status = 'completed',
    this.storeName = '',
    this.branchName,
    this.address,
    this.phone,
    this.stir,
    this.cashier,
    this.tillCode,
    this.terminal,
    this.customerName,
    this.lines = const [],
    this.currency = 'UZS',
    required this.subtotal,
    required this.lineDiscount,
    required this.docDiscount,
    required this.rounding,
    required this.total,
    this.payments = const [],
    this.refundMethod,
    this.refundAmount,
    this.originalNumber,
    this.originalIssuedAtLocal,
    this.template = const ReceiptTemplateView(),
  });

  /// Parses the DTO. A document of another schema still parses (the screen
  /// shows what it can); money fields default to `"0.00"`.
  factory Receipt.fromJson(Map<String, dynamic> j) {
    final doc = (j['doc'] as Map?)?.cast<String, dynamic>() ?? const {};
    final store = (j['store'] as Map?)?.cast<String, dynamic>() ?? const {};
    final actor = (j['actor'] as Map?)?.cast<String, dynamic>() ?? const {};
    final totals = (j['totals'] as Map?)?.cast<String, dynamic>() ?? const {};
    final cust = j['customer'];
    final refund = j['refund'];
    final orig = j['original'];
    String m(Object? v) => _ns(v) ?? '0.00';
    return Receipt(
      schema: _s(j['schema']),
      kind: _s(j['kind']).toUpperCase() == 'RETURN' ? 'RETURN' : 'SALE',
      test: j['test'] == true,
      provisional: j['provisional'] == true,
      docId: _ns(doc['id']),
      number: _s(doc['number']),
      uid: _ns(doc['uid']),
      issuedAt: _ns(doc['issued_at']),
      issuedAtLocal: _ns(doc['issued_at_local']),
      status: _s(doc['status'] ?? 'completed'),
      storeName: _s(store['name']),
      branchName: _ns(store['branch_name']),
      address: _ns(store['address']),
      phone: _ns(store['phone']),
      stir: _ns(store['stir']),
      cashier: _ns(actor['cashier']),
      tillCode: _ns(actor['till_code']),
      terminal: _ns(actor['terminal']),
      customerName: cust is Map ? _ns(cust['name']) : null,
      lines: [for (final l in _maps(j['lines'])) ReceiptLine.fromJson(l)],
      currency: _s(totals['currency'] ?? 'UZS'),
      subtotal: m(totals['subtotal']),
      lineDiscount: m(totals['line_discount']),
      docDiscount: m(totals['doc_discount']),
      rounding: m(totals['rounding']),
      total: m(totals['total']),
      payments: [for (final p in _maps(j['payments'])) ReceiptPayment.fromJson(p)],
      refundMethod: refund is Map ? _ns(refund['method']) : null,
      refundAmount: refund is Map ? _ns(refund['amount']) : null,
      originalNumber: orig is Map ? _ns(orig['number']) : null,
      originalIssuedAtLocal: orig is Map ? _ns(orig['issued_at_local']) : null,
      template: ReceiptTemplateView.fromJson((j['template'] as Map?)?.cast<String, dynamic>()),
    );
  }

  /// `binos.receipt.v1`.
  final String schema;

  /// `SALE` or `RETURN`.
  final String kind;

  /// Sample receipt (never for a real sale).
  final bool test;

  /// Client-built offline receipt (never from the server read).
  final bool provisional;

  /// Document id.
  final String? docId;

  /// Receipt / return number.
  final String number;

  /// Receipt uid (barcode payload) or null.
  final String? uid;

  /// Issue time (UTC ISO) and the branch-local text (`dd.mm.yyyy HH:MM`).
  final String? issuedAt, issuedAtLocal;

  /// Sale status (`completed`, `voided`, `refunded`, `partially_refunded`).
  final String status;

  /// Store name.
  final String storeName;

  /// Branch / address / phone / tax id (STIR).
  final String? branchName, address, phone, stir;

  /// Cashier, till code, terminal (sale-time snapshots).
  final String? cashier, tillCode, terminal;

  /// Customer name (only when the template allows it).
  final String? customerName;

  /// Lines.
  final List<ReceiptLine> lines;

  /// Currency code.
  final String currency;

  /// Totals (2-decimal strings): subtotal − line_discount − doc_discount + rounding == total.
  final String subtotal, lineDiscount, docDiscount, rounding, total;

  /// Sale payments.
  final List<ReceiptPayment> payments;

  /// RETURN: refund method and amount.
  final String? refundMethod, refundAmount;

  /// RETURN: the original receipt number and its local time.
  final String? originalNumber, originalIssuedAtLocal;

  /// Effective template switches.
  final ReceiptTemplateView template;

  /// True for a return receipt (amounts shown with a minus sign).
  bool get isReturn => kind == 'RETURN';

  /// True when the sale was voided.
  bool get isVoided => status == 'voided';
}

/// Localized sale status (receipt `doc.status`).
String saleStatusLabel(String s) => switch (s) {
      'completed' => tr('Yakunlangan'),
      'voided' => tr('Bekor qilingan'),
      'refunded' => tr('Qaytarilgan'),
      'partially_refunded' => tr('Qisman qaytarilgan'),
      _ => s,
    };

// ─────────────────────────── the API ───────────────────────────

/// Calls of package M4. All of them throw [ApiException] on failure.
abstract final class MoneyApi {
  // ── customers ──

  /// `GET /customers?q=&only_debt=` (server-side search on name/phone).
  static Future<List<CustomerRow>> customers({String? q, bool onlyDebt = false}) async {
    final query = <String, Object?>{
      if ((q ?? '').trim().isNotEmpty) 'q': q!.trim(),
      if (onlyDebt) 'only_debt': 'true',
    };
    final r = await Api.getJson('/customers', query: query);
    return [for (final m in _maps(r.list)) CustomerRow.fromJson(m)];
  }

  /// `GET /customers/{id}/detail`.
  static Future<CustomerProfile> customerDetail(String id) async =>
      CustomerProfile.fromJson((await Api.getJson('/customers/${Api.seg(id)}/detail')).map);

  /// `POST /customers` — idempotent by [clientUuid] (a retry returns the same customer).
  static Future<CustomerRow> createCustomer(
      {required String fullName, String? phone, String? address, required String clientUuid}) async {
    final r = await Api.postJson('/customers', {
      'full_name': fullName,
      if ((phone ?? '').trim().isNotEmpty) 'phone': phone!.trim(),
      if ((address ?? '').trim().isNotEmpty) 'address': address!.trim(),
      'client_uuid': clientUuid,
    });
    return CustomerRow.fromJson(r.map);
  }

  /// `PATCH /customers/{id}` — only the given fields change; an empty [phone]
  /// clears the phone.
  static Future<CustomerRow> editCustomer(String id, {String? fullName, String? phone}) async {
    final r = await Api.patchJson('/customers/${Api.seg(id)}', {
      if (fullName != null) 'full_name': fullName,
      if (phone != null) 'phone': phone.trim(),
    });
    return CustomerRow.fromJson(r.map);
  }

  /// Body of a debt / supplier payment (without `client_uuid`): the draft the
  /// idempotency key is bound to.
  static Map<String, Object?> paymentBody({required int amountCents, required String method, String? cashAccountId}) => {
        'amount': centsToJson(amountCents),
        'method': method,
        if (cashAccountId != null) 'cash_account_id': cashAccountId,
      };

  /// `POST /customers/{id}/payments`. [cashAccountId] only when the custody
  /// preview said OPERATOR_MUST_CHOOSE.
  static Future<DebtPaymentResult> payCustomerDebt(String customerId,
      {required int amountCents, required String method, String? cashAccountId, required String clientUuid}) async {
    final r = await Api.postJson('/customers/${Api.seg(customerId)}/payments', {
      ...paymentBody(amountCents: amountCents, method: method, cashAccountId: cashAccountId),
      'client_uuid': clientUuid,
    });
    return DebtPaymentResult.fromJson(r.map);
  }

  // ── suppliers ──

  /// `GET /suppliers` (ordered by name).
  static Future<List<SupplierRowM>> suppliers() async {
    final r = await Api.getJson('/suppliers');
    return [for (final m in _maps(r.list)) SupplierRowM.fromJson(m)];
  }

  /// `GET /suppliers/{id}`.
  static Future<SupplierProfile> supplierDetail(String id) async =>
      SupplierProfile.fromJson((await Api.getJson('/suppliers/${Api.seg(id)}')).map);

  /// `GET /suppliers/{id}/ledger` (newest first).
  static Future<List<SupplierLedgerEntry>> supplierLedger(String id) async {
    final r = await Api.getJson('/suppliers/${Api.seg(id)}/ledger');
    return [for (final m in _maps(r.list)) SupplierLedgerEntry.fromJson(m)];
  }

  /// `POST /suppliers` (NOT idempotent on the server: never auto-retried).
  static Future<SupplierRowM> createSupplier({required String name, String? phone}) async {
    final r = await Api.postJson('/suppliers', {
      'name': name,
      if ((phone ?? '').trim().isNotEmpty) 'phone': phone!.trim(),
    });
    return SupplierRowM.fromJson(r.map);
  }

  /// `PATCH /suppliers/{id}`; an empty [phone] clears it.
  static Future<SupplierRowM> editSupplier(String id, {String? name, String? phone}) async {
    final r = await Api.patchJson('/suppliers/${Api.seg(id)}', {
      if (name != null) 'name': name,
      if (phone != null) 'phone': phone.trim(),
    });
    return SupplierRowM.fromJson(r.map);
  }

  /// `POST /suppliers/{id}/payments`.
  static Future<SupplierPaymentResult> paySupplier(String supplierId,
      {required int amountCents, required String method, String? cashAccountId, required String clientUuid}) async {
    final r = await Api.postJson('/suppliers/${Api.seg(supplierId)}/payments', {
      ...paymentBody(amountCents: amountCents, method: method, cashAccountId: cashAccountId),
      'client_uuid': clientUuid,
    });
    return SupplierPaymentResult.fromJson(r.map);
  }

  // ── cash operations ──

  /// `GET /cash/ops` — today's movements of the visible branches.
  static Future<List<CashOpEntry>> cashOpsToday() async {
    final r = await Api.getJson('/cash/ops');
    return [for (final m in _maps(r.list)) CashOpEntry.fromJson(m)];
  }

  /// Body of a cash operation (without `client_uuid`).
  static Map<String, Object?> cashOpBody(
          {required String type, required int amountCents, String? reason, String? destinationSafeId}) =>
      {
        'type': type,
        'amount': centsToJson(amountCents),
        if ((reason ?? '').trim().isNotEmpty) 'reason': reason!.trim(),
        if (type == CashOpType.collection && destinationSafeId != null) 'destination_safe_id': destinationSafeId,
      };

  /// `POST /cash/ops`.
  static Future<CashOpResult> cashOp(
      {required String type,
      required int amountCents,
      String? reason,
      String? destinationSafeId,
      required String clientUuid}) async {
    final r = await Api.postJson('/cash/ops', {
      ...cashOpBody(type: type, amountCents: amountCents, reason: reason, destinationSafeId: destinationSafeId),
      'client_uuid': clientUuid,
    });
    return CashOpResult.fromJson(r.map);
  }

  // ── sales ──

  /// `GET /sales?limit=&period=&q=&branch_id=`.
  static Future<List<SaleSummary>> sales(
      {SalesPeriod period = SalesPeriod.today, String? q, String? branchId, int limit = 100}) async {
    final r = await Api.getJson('/sales', query: {
      'limit': limit,
      if (period != SalesPeriod.all) 'period': period.name,
      if ((q ?? '').trim().isNotEmpty) 'q': q!.trim(),
      if (branchId != null) 'branch_id': branchId,
    });
    return [for (final m in _maps(r.list)) SaleSummary.fromJson(m)];
  }

  /// `GET /sales/{id}/receipt` — the server receipt DTO.
  static Future<Receipt> saleReceipt(String saleId) async =>
      Receipt.fromJson((await Api.getJson('/sales/${Api.seg(saleId)}/receipt')).map);
}
