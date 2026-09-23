/// Stock (Ombor) API of package M2: product list/search, lots, write-off,
/// lot-aware count, transfer, stock alerts.
///
/// Rules (SPEC §0/§4):
///  * quantities are integer thousandths ("milli", NUMERIC(14,3)), money is
///    integer cents — JSON numbers are produced only at the request edge;
///  * every branch-scoped read AND the matching write send the SAME
///    `branch_id` (the desktop lists lots across branches but writes to the
///    actor branch — that mismatch is deliberately NOT copied);
///  * the server decides: nothing here re-implements a lot rule, it only
///    shapes requests and parses responses;
///  * a write is "done" only after a 2xx; the caller owns the `client_uuid`
///    ([DraftUuid]) so a retry after a network failure reuses it.
library;

import '../api.dart';
import '../errors.dart' show isConnectivityError;
import '../format.dart' show parseIsoDate;
import '../qty.dart';

/// True when the server DECIDED NOTHING about a stock write, so it may already
/// be applied: every connectivity failure, every 5xx (the edge returns a
/// gateway 502/504 AFTER the backend committed — the deploy runbook records a
/// ~15 s window of dropped requests during a container swap) AND every answer
/// the core discarded because the session epoch moved on ([Api.kStaleSession])
/// that was itself a 2xx or a 5xx: a concurrent 401 (the owner reset the
/// password) ends the session while a write authenticated BEFORE the
/// revocation is still in flight, and such a 2xx means the stock IS written.
/// Only a stale 4xx is a real decision (the server refused it).
///
/// A screen that gets `true` freezes the draft and keeps the SAME
/// `client_uuid`; the flag is STICKY, because a later decided refusal does not
/// prove the earlier, still-running attempt was not written.
///
/// Twin of `moneyOutcomeUnknown` (M4) and `outcomeUnknown` (M3) — the three
/// must agree; `test/stock_write_safety_test.dart` pins that. They collapse
/// into one the day the core gains `ApiException.isOutcomeUnknown` (FX-D).
bool stockOutcomeUnknown(Object? e) =>
    isConnectivityError(e) ||
    (e is ApiException &&
        (e.kind == ApiErrorKind.server ||
            (e.code == Api.kStaleSession && (e.status >= 500 || (e.status >= 200 && e.status < 300)))));

/// Page size of the Ombor list (SPEC §4: `limit=50`).
const int kStockPageSize = 50;

/// Server limit of lot lines (counted + new) in ONE count request.
const int kMaxCountLotLines = 2000;

/// Server limit of counted lots per product in a count / lots per write-off.
const int kMaxLotsPerItem = 200;

/// Server limit of new lots per product in a count.
const int kMaxNewLotsPerItem = 50;

/// Write-off reason codes — the desktop `Hisobdan` set.
const List<String> kWriteoffReasons = ['expired', 'damaged', 'lost', 'other'];

/// Max length of the write-off `reason` text (server `max_length=200`).
const int kWriteoffReasonMax = 200;

String _s(Object? v) => v == null ? '' : '$v';
String? _sn(Object? v) {
  final s = v?.toString().trim();
  return s == null || s.isEmpty ? null : s;
}

int _int(Object? v) => v is num ? v.toInt() : int.tryParse('${v ?? ''}') ?? 0;

/// Stock state of a product in a branch.
enum StockLevel {
  /// Above the minimum.
  ok,

  /// At or below a positive minimum.
  low,

  /// Nothing (or negative) in stock.
  out,
}

/// A product as `GET /products` / `GET /products/scan` returns it (`ProductOut`).
///
/// ⚠️  [expiryDate] is the PRODUCT column: for lot-tracked products it is
///     frozen and meaningless — the lots carry the real dates. Use
///     [productExpiry], which is null for tracked products.
class StockProduct {
  /// Creates a product (tests build them directly).
  const StockProduct({
    required this.id,
    required this.name,
    this.unit = 'dona',
    this.stockMilli = 0,
    this.minMilli = 0,
    this.sellCents = 0,
    this.buyCents = 0,
    this.trackLots = false,
    this.trackExpiry = false,
    this.isActive = true,
    this.isWeighted = false,
    this.plu,
    this.expiryDate,
    this.barcodes = const [],
  });

  /// Parses `ProductOut`.
  factory StockProduct.fromJson(Map<String, dynamic> j) => StockProduct(
        id: _s(j['id']),
        name: _s(j['name']),
        unit: _sn(j['unit_code']) ?? 'dona',
        stockMilli: milliFromNum(j['stock']),
        minMilli: milliFromNum(j['min_stock']),
        sellCents: centsFromNum(j['base_sell_price']),
        buyCents: centsFromNum(j['base_buy_price']),
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        isActive: j['is_active'] != false,
        isWeighted: j['is_weighted'] == true,
        plu: _sn(j['plu_code']),
        expiryDate: _sn(j['expiry_date']),
        barcodes: [for (final b in (j['barcodes'] as List? ?? const [])) '$b'],
      );

  /// Product id.
  final String id;

  /// Name.
  final String name;

  /// Unit code (`dona`, `kg`, ...).
  final String unit;

  /// Stock in the requested branch (milli).
  final int stockMilli;

  /// Minimum stock (milli).
  final int minMilli;

  /// Sell / buy price (cents).
  final int sellCents, buyCents;

  /// Lot-tracked (write-off / count by lot, no transfer).
  final bool trackLots;

  /// Expiry-tracked (new lots need an expiry date).
  final bool trackExpiry;

  /// False for an archived product.
  final bool isActive;

  /// Sold by weight.
  final bool isWeighted;

  /// Scale PLU.
  final String? plu;

  /// Raw product-level expiry column (see the class note).
  final String? expiryDate;

  /// Barcodes.
  final List<String> barcodes;

  /// Product-level expiry that is meaningful (null for lot-tracked products).
  String? get productExpiry => trackLots ? null : expiryDate;

  /// Stock state.
  StockLevel get level {
    if (stockMilli <= 0) return StockLevel.out;
    if (minMilli > 0 && stockMilli <= minMilli) return StockLevel.low;
    return StockLevel.ok;
  }
}

/// One page of `GET /products?limit=&offset=`.
class ProductPage {
  /// Creates a page.
  const ProductPage({required this.items, required this.offset, required this.limit, this.total});

  /// Products of this page.
  final List<StockProduct> items;

  /// Offset the page was requested with.
  final int offset;

  /// Requested page size.
  final int limit;

  /// `X-Total-Count` (null on a server that does not page).
  final int? total;

  /// True when more rows exist after this page.
  bool get hasMore => total != null ? offset + items.length < total! : items.length >= limit;
}

/// Full product card (`GET /products/{id}`).
class StockProductDetail {
  /// Creates a detail.
  const StockProductDetail({
    required this.id,
    required this.name,
    this.unit = 'dona',
    this.buyCents = 0,
    this.sellCents = 0,
    this.profitCents = 0,
    this.marginPct = 0,
    this.stockMilli = 0,
    this.minMilli = 0,
    this.monthInMilli = 0,
    this.monthOutMilli = 0,
    this.sales7 = const SalesStats(),
    this.sales30 = const SalesStats(),
    this.lastSoldAt,
    this.expiryDate,
    this.trackLots = false,
    this.trackExpiry = false,
    this.isActive = true,
    this.isWeighted = false,
    this.plu,
    this.barcodes = const [],
    this.createdBy = '',
    this.branchId,
  });

  /// Parses the server dict; [branchId] is the `branch_id` the request sent
  /// (the server does not echo it).
  factory StockProductDetail.fromJson(Map<String, dynamic> j, {String? branchId}) => StockProductDetail(
        id: _s(j['id']),
        name: _s(j['name']),
        unit: _sn(j['unit_code']) ?? 'dona',
        buyCents: centsFromNum(j['base_buy_price']),
        sellCents: centsFromNum(j['base_sell_price']),
        profitCents: centsFromNum(j['profit_unit']),
        marginPct: (j['margin_pct'] as num?)?.toDouble() ?? double.tryParse('${j['margin_pct']}') ?? 0,
        stockMilli: milliFromNum(j['stock']),
        minMilli: milliFromNum(j['min_stock']),
        monthInMilli: milliFromNum(j['month_in']),
        monthOutMilli: milliFromNum(j['month_out']),
        sales7: SalesStats.fromJson(j['sales_7d']),
        sales30: SalesStats.fromJson(j['sales_30d']),
        lastSoldAt: _sn(j['last_sold_at']),
        expiryDate: _sn(j['expiry_date']),
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        isActive: j['is_active'] != false,
        isWeighted: j['is_weighted'] == true,
        plu: _sn(j['plu_code']),
        barcodes: [for (final b in (j['barcodes'] as List? ?? const [])) '$b'],
        createdBy: _sn(j['created_by_name']) ?? '—',
        branchId: branchId,
      );

  /// Id.
  final String id;

  /// Name.
  final String name;

  /// Unit code.
  final String unit;

  /// Prices and unit profit (cents).
  final int buyCents, sellCents, profitCents;

  /// Margin in percent.
  final double marginPct;

  /// Stock and minimum of [branchId] — or, when no branch was sent, summed
  /// over the caller's VISIBLE branches (the server decides the scope).
  final int stockMilli, minMilli;

  /// This month's in / out (milli), same branch scope as [stockMilli].
  final int monthInMilli, monthOutMilli;

  /// Branch the stock numbers belong to; null = all of the caller's visible
  /// branches. (Sales statistics are company-wide on the server either way.)
  final String? branchId;

  /// Sales of the last 7 / 30 days.
  final SalesStats sales7, sales30;

  /// Last sale timestamp (server text).
  final String? lastSoldAt;

  /// Raw product-level expiry (frozen for tracked products).
  final String? expiryDate;

  /// Tracking flags.
  final bool trackLots, trackExpiry;

  /// Active / weighted flags.
  final bool isActive, isWeighted;

  /// Scale PLU.
  final String? plu;

  /// Barcodes.
  final List<String> barcodes;

  /// Who created the product.
  final String createdBy;

  /// Product-level expiry that is meaningful (null for lot-tracked products).
  String? get productExpiry => trackLots ? null : expiryDate;

  /// As a list product (for the write-off / count screens).
  StockProduct toProduct({int? stockMilli}) => StockProduct(
        id: id,
        name: name,
        unit: unit,
        stockMilli: stockMilli ?? this.stockMilli,
        minMilli: minMilli,
        sellCents: sellCents,
        buyCents: buyCents,
        trackLots: trackLots,
        trackExpiry: trackExpiry,
        isActive: isActive,
        isWeighted: isWeighted,
        plu: plu,
        expiryDate: expiryDate,
        barcodes: barcodes,
      );
}

/// `{qty, revenue, profit}` of a period.
class SalesStats {
  /// Creates stats.
  const SalesStats({this.qtyMilli = 0, this.revenueCents = 0, this.profitCents = 0});

  /// Parses `{qty, revenue, profit}` (null -> zeros).
  factory SalesStats.fromJson(Object? v) {
    final j = v is Map ? v : const {};
    return SalesStats(
      qtyMilli: milliFromNum(j['qty']),
      revenueCents: centsFromNum(j['revenue']),
      profitCents: centsFromNum(j['profit']),
    );
  }

  /// Quantity sold (milli).
  final int qtyMilli;

  /// Revenue / profit (cents).
  final int revenueCents, profitCents;
}

/// Lot statuses that carry quantity (`stock_invariant.QUANTITY_BEARING`).
const Set<String> kQuantityBearing = {'open', 'depleted'};

/// One lot of `GET /lots/products/{id}`.
class LotRow {
  /// Creates a lot.
  const LotRow({
    required this.id,
    this.batchNumber,
    this.expiryDate,
    this.expired = false,
    this.receivedMilli = 0,
    this.remainingMilli = 0,
    this.unitCostCents = 0,
    this.status = 'open',
    this.sourceType,
    this.receivedAt,
  });

  /// Parses a lot.
  factory LotRow.fromJson(Map<String, dynamic> j) => LotRow(
        id: _s(j['id']),
        batchNumber: _sn(j['batch_number']),
        expiryDate: _sn(j['expiry_date']),
        expired: j['expired'] == true,
        receivedMilli: milliFromNum(j['received_qty']),
        remainingMilli: milliFromNum(j['remaining_qty']),
        unitCostCents: centsFromNum(j['unit_cost']),
        status: _sn(j['status']) ?? 'open',
        sourceType: _sn(j['source_type']),
        receivedAt: _sn(j['received_at']),
      );

  /// Lot (stock batch) id.
  final String id;

  /// Batch number printed on the package.
  final String? batchNumber;

  /// Expiry `YYYY-MM-DD`.
  final String? expiryDate;

  /// Server-computed: expired against the branch business date.
  final bool expired;

  /// Received / remaining quantity (milli).
  final int receivedMilli, remainingMilli;

  /// Unit cost (cents).
  final int unitCostCents;

  /// `open` / `depleted` / `void` / ...
  final String status;

  /// Source (`receiving`, `adjustment`, `return_unattributed`, ...).
  final String? sourceType;

  /// Received timestamp (server text).
  final String? receivedAt;

  /// The lot carries quantity (the server counts it as "untouched" in a count).
  bool get quantityBearing => kQuantityBearing.contains(status);

  /// Something can be written off / counted from this lot.
  bool get usable => quantityBearing && remainingMilli > 0;

  /// Days from [businessDate] to the expiry (negative = expired); null when
  /// either date is unknown. Calendar days, never the device clock.
  int? daysLeft(String? businessDate) {
    final e = parseIsoDate(expiryDate), b = parseIsoDate(businessDate);
    if (e == null || b == null) return null;
    return e.difference(b).inDays;
  }
}

/// `GET /lots/products/{id}?branch_id=` — lots of ONE branch, FEFO order.
class ProductLots {
  /// Creates the payload.
  const ProductLots({
    required this.productId,
    required this.branchId,
    this.trackLots = true,
    this.trackExpiry = false,
    this.businessDate,
    this.inventoryMilli = 0,
    this.shortfallMilli = 0,
    this.lots = const [],
  });

  /// Parses the payload; [branchId] is the branch that was REQUESTED.
  factory ProductLots.fromJson(Map<String, dynamic> j, {required String? branchId}) => ProductLots(
        productId: _s(j['product_id']),
        branchId: branchId,
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        businessDate: _sn(j['business_date']),
        inventoryMilli: milliFromNum(j['inventory_qty']),
        shortfallMilli: milliFromNum(j['unresolved_shortfall_qty']),
        lots: [
          for (final l in (j['lots'] as List? ?? const []))
            if (l is Map) LotRow.fromJson(l.cast<String, dynamic>())
        ],
      );

  /// Product id.
  final String productId;

  /// Branch the lots belong to (the same id must be sent with the write).
  final String? branchId;

  /// Tracking flags as the server sees them NOW.
  final bool trackLots, trackExpiry;

  /// Branch business date (`YYYY-MM-DD`).
  final String? businessDate;

  /// Product stock in this branch (milli).
  final int inventoryMilli;

  /// Unresolved lot shortfall (sold without a lot) in this branch (milli).
  final int shortfallMilli;

  /// Lots with remaining > 0, FEFO order (expiry asc, no-expiry last).
  final List<LotRow> lots;

  /// Lots something can be taken from / counted.
  List<LotRow> get usableLots => [
        for (final l in lots)
          if (l.usable) l
      ];
}

/// Result of `POST /inventory/writeoff`.
class WriteoffResult {
  /// Creates a result.
  const WriteoffResult({this.duplicate = false, this.product, this.newQtyMilli, this.costTotalCents});

  /// Parses the reply.
  factory WriteoffResult.fromJson(Map<String, dynamic> j) => WriteoffResult(
        duplicate: j['duplicate'] == true,
        product: _sn(j['product']),
        newQtyMilli: j['new_qty'] == null ? null : milliFromNum(j['new_qty']),
        costTotalCents: j['cost_total'] == null ? null : centsFromNum(j['cost_total']),
      );

  /// The same `client_uuid` was already applied — NOTHING was written now.
  final bool duplicate;

  /// Product name.
  final String? product;

  /// Branch stock after the write-off (milli).
  final int? newQtyMilli;

  /// Cost of the written-off lots (tracked products only).
  final int? costTotalCents;
}

/// One lot line of a count result.
class CountLotLine {
  /// Creates a line.
  const CountLotLine({required this.lotId, required this.qtyMilli, this.unitCostCents, this.batchNo, this.expiryDate});

  /// Parses `{stock_batch_id, qty, unit_cost?, batch_no?, expiry_date?}`.
  factory CountLotLine.fromJson(Map<String, dynamic> j) => CountLotLine(
        lotId: _s(j['stock_batch_id']),
        qtyMilli: milliFromNum(j['qty']),
        unitCostCents: j['unit_cost'] == null ? null : centsFromNum(j['unit_cost']),
        batchNo: _sn(j['batch_no']),
        expiryDate: _sn(j['expiry_date']),
      );

  /// Lot id (the counted lot, or the NEW lot for `created`).
  final String lotId;

  /// Quantity (milli).
  final int qtyMilli;

  /// Unit cost of a created lot (cents).
  final int? unitCostCents;

  /// Batch number / expiry of a created lot.
  final String? batchNo, expiryDate;
}

/// One product of a count result.
class CountResultRow {
  /// Creates a row.
  const CountResultRow({
    required this.productId,
    required this.product,
    required this.oldMilli,
    required this.countedMilli,
    required this.diffMilli,
    this.decrements = const [],
    this.surpluses = const [],
    this.created = const [],
    this.hasLots = false,
  });

  /// Parses `{product, product_id, old, counted, diff, lots?}`.
  factory CountResultRow.fromJson(Map<String, dynamic> j) {
    final lots = j['lots'];
    List<CountLotLine> list(String k) => [
          if (lots is Map)
            for (final l in (lots[k] as List? ?? const []))
              if (l is Map) CountLotLine.fromJson(l.cast<String, dynamic>())
        ];
    return CountResultRow(
      productId: _s(j['product_id']),
      product: _s(j['product']),
      oldMilli: milliFromNum(j['old']),
      countedMilli: milliFromNum(j['counted']),
      diffMilli: milliFromNum(j['diff']),
      decrements: list('decrements'),
      surpluses: list('surpluses'),
      created: list('created'),
      hasLots: lots is Map,
    );
  }

  /// Product id / name.
  final String productId, product;

  /// Stock before, counted, difference (milli).
  final int oldMilli, countedMilli, diffMilli;

  /// Lots reduced (lot id, reduced by).
  final List<CountLotLine> decrements;

  /// Lots found in surplus (SOURCE lot id, surplus qty) — a new lot is created for each.
  final List<CountLotLine> surpluses;

  /// Lots created (surplus copies and declared new lots).
  final List<CountLotLine> created;

  /// The product was counted by lot.
  final bool hasLots;
}

/// Result of `POST /inventory/count`.
class CountResult {
  /// Creates a result.
  const CountResult({this.duplicate = false, this.changed = 0, this.results = const []});

  /// Parses the reply.
  factory CountResult.fromJson(Map<String, dynamic> j) => CountResult(
        duplicate: j['duplicate'] == true,
        changed: _int(j['changed']),
        results: [
          for (final r in (j['results'] as List? ?? const []))
            if (r is Map) CountResultRow.fromJson(r.cast<String, dynamic>())
        ],
      );

  /// The same `client_uuid` was already applied — NOTHING was written now.
  final bool duplicate;

  /// Products whose stock/lots changed.
  final int changed;

  /// Per-product results.
  final List<CountResultRow> results;
}

/// One moved product of a transfer.
class TransferMoved {
  /// Creates a line.
  const TransferMoved({required this.product, required this.qtyMilli, this.fromLeftMilli, this.toNowMilli});

  /// Parses `{product, qty, from_left, to_now}`.
  factory TransferMoved.fromJson(Map<String, dynamic> j) => TransferMoved(
        product: _s(j['product']),
        qtyMilli: milliFromNum(j['qty']),
        fromLeftMilli: j['from_left'] == null ? null : milliFromNum(j['from_left']),
        toNowMilli: j['to_now'] == null ? null : milliFromNum(j['to_now']),
      );

  /// Product name.
  final String product;

  /// Moved quantity (milli).
  final int qtyMilli;

  /// Stock left in the source / now in the destination (milli).
  final int? fromLeftMilli, toNowMilli;
}

/// Result of `POST /inventory/transfer`.
class TransferResult {
  /// Creates a result.
  const TransferResult({this.duplicate = false, this.from, this.to, this.moved = const []});

  /// Parses the reply.
  factory TransferResult.fromJson(Map<String, dynamic> j) => TransferResult(
        duplicate: j['duplicate'] == true,
        from: _sn(j['from']),
        to: _sn(j['to']),
        moved: [
          for (final m in (j['moved'] as List? ?? const []))
            if (m is Map) TransferMoved.fromJson(m.cast<String, dynamic>())
        ],
      );

  /// The same `client_uuid` was already applied — NOTHING was moved now.
  final bool duplicate;

  /// Branch names.
  final String? from, to;

  /// Moved products.
  final List<TransferMoved> moved;
}

/// A company branch from `GET /branches` (transfer destination list).
class CompanyBranch {
  /// Creates a branch.
  const CompanyBranch({required this.id, required this.name, this.isActive = true});

  /// Parses a `/branches` row.
  factory CompanyBranch.fromJson(Map<String, dynamic> j) =>
      CompanyBranch(id: _s(j['id']), name: _s(j['name']), isActive: j['is_active'] != false);

  /// Id / name.
  final String id, name;

  /// Active branches can receive a transfer.
  final bool isActive;
}

/// `GET /inventory/overview` (hisobot.view) — the counts of ONE branch when
/// `branch_id` is sent, otherwise summed over the caller's visible branches.
class StockOverview {
  /// Creates an overview.
  const StockOverview({this.totalProducts = 0, this.lowCount = 0, this.outCount = 0});

  /// Parses the reply.
  factory StockOverview.fromJson(Map<String, dynamic> j) => StockOverview(
        totalProducts: _int(j['total_products']),
        lowCount: _int(j['low_count']),
        outCount: _int(j['out_count']),
      );

  /// Counts.
  final int totalProducts, lowCount, outCount;
}

/// One row of `GET /inventory/low` (one product in one branch).
class LowStockRow {
  /// Creates a row.
  const LowStockRow({required this.name, required this.qtyMilli, required this.minMilli, this.productId});

  /// Parses `{name, qty, min, product_id}` (`product_id` is absent on an
  /// older server — then the row cannot open the product card).
  factory LowStockRow.fromJson(Map<String, dynamic> j) => LowStockRow(
        name: _s(j['name']),
        qtyMilli: milliFromNum(j['qty']),
        minMilli: milliFromNum(j['min']),
        productId: _sn(j['product_id']),
      );

  /// Product name.
  final String name;

  /// Product id (opens the product card), or null on an older server.
  final String? productId;

  /// Stock / minimum (milli).
  final int qtyMilli, minMilli;
}

/// One expiry bucket of `/lots/alerts`.
class ExpiryBucket {
  /// Creates a bucket.
  const ExpiryBucket({this.lots = 0, this.qtyMilli = 0, this.valueCents = 0});

  /// Parses `{lots, qty, value_at_risk}`.
  factory ExpiryBucket.fromJson(Object? v) {
    final j = v is Map ? v : const {};
    return ExpiryBucket(
      lots: _int(j['lots']),
      qtyMilli: milliFromNum(j['qty']),
      valueCents: centsFromNum(j['value_at_risk']),
    );
  }

  /// Number of lots.
  final int lots;

  /// Quantity (milli).
  final int qtyMilli;

  /// Cost value at risk (cents).
  final int valueCents;
}

/// Expiry bucket keys of `/lots/alerts` and `/lots/batches?expiry=`.
abstract final class ExpiryKind {
  /// Before the business date.
  static const String expired = 'expired';

  /// On the business date.
  static const String today = 'expires_today';

  /// Within 7 days.
  static const String within7 = 'within_7_days';

  /// Within 30 days.
  static const String within30 = 'within_30_days';

  /// All four, most urgent first.
  static const List<String> all = [expired, today, within7, within30];
}

/// `GET /lots/alerts?branch_id=` (ombor.view).
class LotAlerts {
  /// Creates alerts.
  const LotAlerts(
      {this.buckets = const {}, this.shortfallCount = 0, this.shortfallMilli = 0, this.trackedProducts = 0});

  /// Parses the reply.
  factory LotAlerts.fromJson(Map<String, dynamic> j) {
    final e = j['expiry'] is Map ? j['expiry'] as Map : const {};
    final s = j['shortfalls'] is Map ? j['shortfalls'] as Map : const {};
    final c = j['cost_quality'] is Map ? j['cost_quality'] as Map : const {};
    return LotAlerts(
      buckets: {for (final k in ExpiryKind.all) k: ExpiryBucket.fromJson(e[k])},
      shortfallCount: _int(s['open_count']),
      shortfallMilli: milliFromNum(s['open_qty']),
      trackedProducts: _int(c['tracked_products']),
    );
  }

  /// Expiry buckets by [ExpiryKind].
  final Map<String, ExpiryBucket> buckets;

  /// Open lot shortfalls.
  final int shortfallCount;

  /// Open shortfall quantity (milli).
  final int shortfallMilli;

  /// Lot-tracked products in the company.
  final int trackedProducts;

  /// Bucket by key (zeros when missing).
  ExpiryBucket bucket(String kind) => buckets[kind] ?? const ExpiryBucket();

  /// Lots that are expired or expire within 7 days (home "attention" tile).
  int get urgentLots =>
      bucket(ExpiryKind.expired).lots + bucket(ExpiryKind.today).lots + bucket(ExpiryKind.within7).lots;
}

/// One lot of `GET /lots/batches` (company lot list).
class BatchRow {
  /// Creates a row.
  const BatchRow({
    required this.id,
    required this.productId,
    required this.product,
    this.unit = '',
    this.batchNumber,
    this.expiryDate,
    this.bucket,
    this.daysLeft,
    this.expired = false,
    this.remainingMilli = 0,
    this.unitCostCents = 0,
    this.branch,
  });

  /// Parses a row.
  factory BatchRow.fromJson(Map<String, dynamic> j) => BatchRow(
        id: _s(j['id']),
        productId: _s(j['product_id']),
        product: _s(j['product']),
        unit: _s(j['unit_code']),
        batchNumber: _sn(j['batch_number']),
        expiryDate: _sn(j['expiry_date']),
        bucket: _sn(j['bucket']),
        daysLeft: j['days_left'] == null ? null : _int(j['days_left']),
        expired: j['expired'] == true,
        remainingMilli: milliFromNum(j['remaining_qty']),
        unitCostCents: centsFromNum(j['unit_cost']),
        branch: _sn(j['branch']),
      );

  /// Lot id / product id / product name / unit.
  final String id, productId, product, unit;

  /// Batch number, expiry date and expiry bucket.
  final String? batchNumber, expiryDate, bucket;

  /// Days to expiry (negative = expired).
  final int? daysLeft;

  /// Expired.
  final bool expired;

  /// Remaining (milli) / unit cost (cents).
  final int remainingMilli, unitCostCents;

  /// Branch name.
  final String? branch;
}

// ── Request bodies (pure — unit tested) ───────────────────────────────────

/// A lot quantity picked for a write-off.
class LotPick {
  /// Creates a pick.
  const LotPick(this.lotId, this.milli);

  /// Lot id.
  final String lotId;

  /// Quantity (milli).
  final int milli;
}

/// The write-off `reason` text: `"<code>"` or `"<code>: <note>"`, cut to 200
/// characters (desktop `Hisobdan` shape).
String writeoffReasonText(String code, String note) {
  final n = note.trim();
  final s = n.isEmpty ? code : '$code: $n';
  return s.length > kWriteoffReasonMax ? s.substring(0, kWriteoffReasonMax) : s;
}

/// `POST /inventory/writeoff` body WITHOUT `client_uuid` (the draft fingerprint).
///
/// Untracked products send only `qty`; tracked products send `lots[]` whose
/// sum is `qty` (the caller computes [qtyMilli] = Σ lots).
Map<String, Object?> writeoffBody({
  required String productId,
  required int qtyMilli,
  required String reason,
  required String? branchId,
  List<LotPick> lots = const [],
}) =>
    {
      'product_id': productId,
      'qty': milliToJson(qtyMilli),
      'reason': reason,
      'branch_id': branchId,
      if (lots.isNotEmpty)
        'lots': [
          for (final l in lots) {'stock_batch_id': l.lotId, 'qty': milliToJson(l.milli)}
        ],
    };

/// `POST /inventory/transfer` body WITHOUT `client_uuid`.
Map<String, Object?> transferBody({
  required String fromBranchId,
  required String toBranchId,
  required List<(String productId, int milli)> items,
}) =>
    {
      'from_branch_id': fromBranchId,
      'to_branch_id': toBranchId,
      'items': [
        for (final i in items) {'product_id': i.$1, 'qty': milliToJson(i.$2)}
      ],
    };

/// `POST /inventory/count` body WITHOUT `client_uuid`: [items] are already
/// shaped `{product_id, counted, lots?, new_lots?}` entries.
Map<String, Object?> countBody({required List<Map<String, Object?>> items, required String? branchId}) =>
    {'items': items, 'branch_id': branchId};

// ── Calls ─────────────────────────────────────────────────────────────────

/// Stock endpoints. Every method throws [ApiException] on failure.
abstract final class StockApi {
  /// One page of the product list — server-side search (name, article, SKU,
  /// barcode) scoped to [branchId]'s stock. Never loads the whole catalog.
  static Future<ProductPage> products({
    String q = '',
    String? branchId,
    int offset = 0,
    int limit = kStockPageSize,
    bool? tracked,
    bool archived = false,
  }) async {
    final query = q.trim();
    final r = await Api.getJson('/products', query: {
      if (query.isNotEmpty) 'q': query,
      'branch_id': branchId,
      'limit': limit,
      'offset': offset,
      'tracked': tracked,
      if (archived) 'archived': true,
    });
    return ProductPage(
      items: [
        for (final e in r.list)
          if (e is Map) StockProduct.fromJson(e.cast<String, dynamic>())
      ],
      offset: offset,
      limit: limit,
      total: r.totalCount,
    );
  }

  /// `GET /products/{id}?branch_id=` — stock / minimum / month in-out of
  /// [branchId]; without it the server sums the caller's visible branches.
  static Future<StockProductDetail> productDetail(String id, {String? branchId}) async =>
      StockProductDetail.fromJson(
          (await Api.getJson('/products/${Api.seg(id)}', query: {'branch_id': branchId})).map,
          branchId: branchId);

  /// `GET /lots/products/{id}?branch_id=` — lots of [branchId] (ombor.view).
  static Future<ProductLots> productLots(String productId, {required String? branchId}) async {
    final r = await Api.getJson('/lots/products/${Api.seg(productId)}', query: {'branch_id': branchId});
    return ProductLots.fromJson(r.map, branchId: branchId);
  }

  /// `POST /inventory/writeoff` — [body] from [writeoffBody].
  static Future<WriteoffResult> writeoff(Map<String, Object?> body, {required String clientUuid}) async {
    final r = await Api.postJson('/inventory/writeoff', {...body, 'client_uuid': clientUuid});
    final res = WriteoffResult.fromJson(r.map);
    Api.invalidateCatalog();
    return res;
  }

  /// `POST /inventory/count` — [body] from [countBody].
  static Future<CountResult> count(Map<String, Object?> body, {required String clientUuid}) async {
    final r = await Api.postJson('/inventory/count', {...body, 'client_uuid': clientUuid});
    final res = CountResult.fromJson(r.map);
    Api.invalidateCatalog();
    return res;
  }

  /// `POST /inventory/transfer` — [body] from [transferBody].
  static Future<TransferResult> transfer(Map<String, Object?> body, {required String clientUuid}) async {
    final r = await Api.postJson('/inventory/transfer', {...body, 'client_uuid': clientUuid});
    final res = TransferResult.fromJson(r.map);
    Api.invalidateCatalog();
    return res;
  }

  /// `GET /branches` — every company branch (transfer destinations).
  static Future<List<CompanyBranch>> companyBranches() async {
    final m = (await Api.getJson('/branches')).map;
    return [
      for (final b in (m['branches'] as List? ?? const []))
        if (b is Map) CompanyBranch.fromJson(b.cast<String, dynamic>())
    ];
  }

  /// `GET /inventory/overview?branch_id=` (hisobot.view) — counts of
  /// [branchId]; without it, of the caller's visible branches.
  static Future<StockOverview> overview({String? branchId}) async =>
      StockOverview.fromJson((await Api.getJson('/inventory/overview', query: {'branch_id': branchId})).map);

  /// `GET /inventory/low?branch_id=` (hisobot.view) — up to 200 rows of
  /// [branchId] (without it: every visible branch, one row per branch).
  static Future<List<LowStockRow>> low({String? branchId}) async => [
        for (final e in (await Api.getJson('/inventory/low', query: {'branch_id': branchId})).list)
          if (e is Map) LowStockRow.fromJson(e.cast<String, dynamic>())
      ];

  /// `GET /lots/alerts?branch_id=` (ombor.view).
  static Future<LotAlerts> lotAlerts({required String? branchId}) async =>
      LotAlerts.fromJson((await Api.getJson('/lots/alerts', query: {'branch_id': branchId})).map);

  /// `GET /lots/batches` — open lots of one expiry bucket in [branchId], most
  /// urgent first (ombor.view).
  static Future<List<BatchRow>> expiringLots(
      {required String? branchId, required String expiry, int limit = 50}) async {
    final m = (await Api.getJson('/lots/batches', query: {
      'branch_id': branchId,
      'expiry': expiry,
      'status': 'open',
      'sort': 'expiry',
      'order': 'asc',
      'limit': limit,
    }))
        .map;
    return [
      for (final e in (m['lots'] as List? ?? const []))
        if (e is Map) BatchRow.fromJson(e.cast<String, dynamic>())
    ];
  }
}
