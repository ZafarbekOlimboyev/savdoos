/// Receiving ("tovar qabul qilish") — server contract, draft model and the
/// client-side PRE-validation of a receiving document.
///
/// The SERVER is the judge (`POST /receiving/commit`, `apps/server/app/api/v1/
/// receiving.py`): everything checked here is checked again there. The client
/// only tells the operator early, mirroring the desktop Manager
/// (`packages/shared/src/screens/Products.tsx` `FullReceiving`,
/// `components/LotReceivingEditor.tsx`):
///
///  * lot-tracked lines carry `lots[]` (`{qty, batch_number?, expiry_date?}`),
///    Σ lots == line qty in integer thousandths, expiry iff tracked, never
///    before the receiving branch's business date, tracked cost > 0;
///  * untracked lines send exactly the legacy payload (no `lots` key);
///  * a NEW product whose name equals a tracked product is refused (the server
///    would attach the line to that tracked product and reject the document);
///  * `cash_account_id` only when the custody preview says OPERATOR_MUST_CHOOSE;
///  * one stable `client_uuid` per document: a retry after a lost answer is a
///    replay, and the server answers `duplicate: true` WITHOUT applying edits.
library;

import 'package:flutter/foundation.dart';

import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../scan.dart';
import '../session.dart';
import '../widgets/custody_block.dart';
import '../widgets/lot_editor.dart';

// ── Units ──────────────────────────────────────────────────────────────────

/// Unit codes a NEW product can get (server `Unit.code`, desktop `UNITS`).
const List<String> kRecvUnits = ['dona', 'kg', 'litr', 'upak'];

/// Localized label of a unit code (the code itself when unknown).
String recvUnitLabel(String code) => switch (code) {
      'dona' => tr('Dona'),
      'kg' => tr('Kg (tarozi)'),
      'litr' => tr('Litr'),
      'upak' => tr('Upak'),
      _ => code,
    };

// ── Products ───────────────────────────────────────────────────────────────

/// A catalog product as receiving needs it (`ProductOut` subset + tracking flags).
@immutable
class RecvProduct {
  /// Creates a product.
  const RecvProduct({
    required this.id,
    required this.name,
    this.unitCode,
    this.isActive = true,
    this.isWeighted = false,
    this.trackLots = false,
    this.trackExpiry = false,
    this.pluCode,
    this.barcodes = const [],
    this.stockMilli,
    this.buyCents,
    this.sellCents,
    this.categoryId,
  });

  /// Parses `ProductOut` (`GET /products`, `GET /products/scan`).
  factory RecvProduct.fromJson(Map<String, dynamic> j) => RecvProduct(
        id: '${j['id']}',
        name: '${j['name'] ?? ''}',
        unitCode: j['unit_code']?.toString(),
        isActive: j['is_active'] != false,
        isWeighted: j['is_weighted'] == true,
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        pluCode: j['plu_code']?.toString(),
        barcodes: [for (final b in (j['barcodes'] as List? ?? const [])) '$b'],
        stockMilli: j['stock'] == null ? null : milliFromNum(j['stock']),
        buyCents: j['base_buy_price'] == null ? null : centsFromNum(j['base_buy_price']),
        sellCents: j['base_sell_price'] == null ? null : centsFromNum(j['base_sell_price']),
        categoryId: j['category_id']?.toString(),
      );

  /// From a server barcode lookup result.
  factory RecvProduct.fromScan(ScanProduct p) => RecvProduct.fromJson(p.raw.isNotEmpty
      ? p.raw
      : {
          'id': p.id,
          'name': p.name,
          'unit_code': p.unitCode,
          'is_active': p.isActive,
          'is_weighted': p.isWeighted,
          'track_lots': p.trackLots,
          'track_expiry': p.trackExpiry,
          'plu_code': p.pluCode,
          'barcodes': p.barcodes,
        });

  /// Product id.
  final String id;

  /// Name.
  final String name;

  /// Unit code (`dona`, `kg`, `litr`, `upak`); null when not known (AI match).
  final String? unitCode;

  /// False for an archived product (receiving re-activates it on the server).
  final bool isActive;

  /// Sold by weight.
  final bool isWeighted;

  /// Lot-tracked: every receiving line needs `lots[]`.
  final bool trackLots;

  /// Expiry-tracked: every lot needs an expiry date.
  final bool trackExpiry;

  /// Scale PLU.
  final String? pluCode;

  /// Barcodes.
  final List<String> barcodes;

  /// Stock (milli) as the server sent it.
  final int? stockMilli;

  /// Purchase / sell price (cents).
  final int? buyCents, sellCents;

  /// Category id.
  final String? categoryId;

  /// A copy with other tracking flags.
  RecvProduct withTracking({required bool trackLots, required bool trackExpiry}) => RecvProduct(
        id: id,
        name: name,
        unitCode: unitCode,
        isActive: isActive,
        isWeighted: isWeighted,
        trackLots: trackLots,
        trackExpiry: trackLots && trackExpiry,
        pluCode: pluCode,
        barcodes: barcodes,
        stockMilli: stockMilli,
        buyCents: buyCents,
        sellCents: sellCents,
        categoryId: categoryId,
      );
}

/// Lot-tracked products of the company (`GET /products?tracked=true&include_archived=1`,
/// small). Used to (1) learn the flags of AI-matched lines, which only carry a
/// `product_id`, and (2) refuse a new product named like a tracked one.
class TrackedCatalog {
  /// Builds the catalog from [products].
  TrackedCatalog(Iterable<RecvProduct> products) : byId = {for (final p in products) p.id: p};

  /// An empty catalog (tests, no tracked products).
  TrackedCatalog.empty() : byId = const {};

  /// Tracked products by id.
  final Map<String, RecvProduct> byId;

  /// Same normalisation as the server dedup (`lower(strip(name))`).
  static String normName(String s) => s.trim().toLowerCase();

  /// The tracked product named [name] (case-insensitive), if any.
  RecvProduct? byName(String name) {
    final n = normName(name);
    if (n.isEmpty) return null;
    for (final p in byId.values) {
      if (normName(p.name) == n) return p;
    }
    return null;
  }

  /// Whether [id] is tracked.
  bool isTracked(String id) => byId.containsKey(id);
}

// ── History / detail / commit result ──────────────────────────────────────

/// `payment` of a receiving document.
enum RecvPayment {
  /// Paid in cash at receiving.
  cash,

  /// Owed to the supplier.
  credit,

  /// Not known (older server).
  unknown,
}

RecvPayment _payment(Object? v) => switch ('$v') {
      'cash' => RecvPayment.cash,
      'credit' => RecvPayment.credit,
      _ => RecvPayment.unknown,
    };

/// Localized payment label.
String recvPaymentLabel(RecvPayment p) => switch (p) {
      RecvPayment.cash => tr('Naqd'),
      RecvPayment.credit => tr('Qarzga'),
      RecvPayment.unknown => '—',
    };

/// A row of `GET /receiving`.
@immutable
class ReceivingDoc {
  /// Creates a row.
  const ReceivingDoc({
    required this.id,
    this.at,
    this.source = '',
    this.employee = '',
    this.totalTypes = 0,
    this.totalQtyMilli = 0,
    this.purchaseId,
    this.docNo,
    this.payment = RecvPayment.unknown,
    this.supplier,
    this.purchaseStatus,
    this.branchId,
    this.branchName,
  });

  /// Parses a history row.
  factory ReceivingDoc.fromJson(Map<String, dynamic> j) => ReceivingDoc(
        id: '${j['id']}',
        at: serverDt(j['at']),
        source: '${j['source'] ?? ''}',
        employee: '${j['employee'] ?? ''}',
        totalTypes: (j['total_types'] as num?)?.toInt() ?? 0,
        totalQtyMilli: milliFromNum(j['total_qty']),
        purchaseId: j['purchase_id']?.toString(),
        docNo: j['doc_no']?.toString(),
        payment: _payment(j['payment']),
        supplier: j['supplier']?.toString(),
        purchaseStatus: j['purchase_status']?.toString(),
        branchId: j['branch_id']?.toString(),
        branchName: j['branch_name']?.toString(),
      );

  /// Receiving id.
  final String id;

  /// Commit time (local).
  final DateTime? at;

  /// `ai`, `demo`, `manual`.
  final String source;

  /// Who received.
  final String employee;

  /// Number of lines.
  final int totalTypes;

  /// Σ qty (milli).
  final int totalQtyMilli;

  /// The purchase document the receiving created.
  final String? purchaseId;

  /// Purchase document number (`KIR-…`).
  final String? docNo;

  /// Cash or credit.
  final RecvPayment payment;

  /// Supplier name.
  final String? supplier;

  /// Purchase status (`received`, `debt`, `partial`, `cancelled`).
  final String? purchaseStatus;

  /// Branch the goods were received into.
  final String? branchId, branchName;

  /// True when a correction reversed the whole document.
  bool get cancelled => purchaseStatus == 'cancelled';
}

/// One line of a receiving document (`final_items`).
@immutable
class ReceivingDetailItem {
  /// Creates a line.
  const ReceivingDetailItem({
    this.productId,
    required this.name,
    required this.qtyMilli,
    required this.unitCostCents,
    this.aiName,
    this.unit,
  });

  /// Parses a `final_items` entry.
  factory ReceivingDetailItem.fromJson(Map<String, dynamic> j) => ReceivingDetailItem(
        productId: j['product_id']?.toString(),
        name: '${j['name'] ?? ''}',
        qtyMilli: milliFromNum(j['qty']),
        unitCostCents: centsFromNum(j['unit_cost']),
        aiName: j['ai_name']?.toString(),
        unit: j['unit']?.toString(),
      );

  /// Product id.
  final String? productId;

  /// Product name.
  final String name;

  /// Quantity (milli).
  final int qtyMilli;

  /// Unit cost (cents).
  final int unitCostCents;

  /// Name the AI read, if any.
  final String? aiName;

  /// Unit code.
  final String? unit;

  /// Line total (cents).
  int get totalCents => lineCents(qtyMilli, unitCostCents);
}

/// `GET /receiving/{id}`.
@immutable
class ReceivingDetail {
  /// Creates a detail.
  const ReceivingDetail({required this.doc, this.items = const [], this.imageB64});

  /// Parses the server payload.
  factory ReceivingDetail.fromJson(Map<String, dynamic> j) => ReceivingDetail(
        doc: ReceivingDoc.fromJson(j),
        items: [
          for (final e in (j['items'] as List? ?? const []))
            if (e is Map) ReceivingDetailItem.fromJson(e.cast<String, dynamic>())
        ],
        imageB64: (j['image_b64'] is String && (j['image_b64'] as String).isNotEmpty) ? j['image_b64'] as String : null,
      );

  /// Header.
  final ReceivingDoc doc;

  /// Lines.
  final List<ReceivingDetailItem> items;

  /// Invoice photo (base64), if any.
  final String? imageB64;

  /// Σ line totals (cents).
  int get totalCents => items.fold(0, (a, i) => a + i.totalCents);
}

/// One `results[]` entry of a commit.
@immutable
class CommitLineResult {
  /// Creates an entry.
  const CommitLineResult({required this.product, required this.oldMilli, required this.addedMilli, required this.newMilli, this.unit});

  /// Parses an entry.
  factory CommitLineResult.fromJson(Map<String, dynamic> j) => CommitLineResult(
        product: '${j['product'] ?? ''}',
        oldMilli: milliFromNum(j['old_qty']),
        addedMilli: milliFromNum(j['added']),
        newMilli: milliFromNum(j['new_qty']),
        unit: j['unit']?.toString(),
      );

  /// Product name.
  final String product;

  /// Stock before / added / after (milli).
  final int oldMilli, addedMilli, newMilli;

  /// Unit code.
  final String? unit;
}

/// `POST /receiving/commit` answer.
@immutable
class CommitResult {
  /// Creates a result.
  const CommitResult({
    required this.receivingId,
    this.duplicate = false,
    this.purchaseId,
    this.docNo,
    this.results = const [],
    this.payment = RecvPayment.unknown,
    this.supplier,
    this.totalTypes = 0,
    this.totalQtyMilli = 0,
  });

  /// Parses the answer. A reply without `receiving_id` is not a receiving.
  factory CommitResult.fromJson(Map<String, dynamic> j) {
    final id = j['receiving_id']?.toString();
    if (j['ok'] != true || id == null || id.isEmpty) {
      throw ApiException(200, 'Unexpected response shape', kind: ApiErrorKind.server, code: 'BAD_RESPONSE');
    }
    return CommitResult(
      receivingId: id,
      duplicate: j['duplicate'] == true,
      purchaseId: j['purchase_id']?.toString(),
      docNo: j['doc_no']?.toString(),
      results: [
        for (final e in (j['results'] as List? ?? const []))
          if (e is Map) CommitLineResult.fromJson(e.cast<String, dynamic>())
      ],
      payment: _payment(j['payment']),
      supplier: j['supplier']?.toString(),
      totalTypes: (j['total_types'] as num?)?.toInt() ?? 0,
      totalQtyMilli: milliFromNum(j['total_qty']),
    );
  }

  /// Receiving id (of the FIRST document for a duplicate).
  final String receivingId;

  /// The server had already saved this `client_uuid`: NOTHING of this request
  /// was applied (later edits of the draft are lost).
  final bool duplicate;

  /// Purchase document id / number.
  final String? purchaseId, docNo;

  /// Stock changes per line.
  final List<CommitLineResult> results;

  /// Cash / credit.
  final RecvPayment payment;

  /// Supplier name.
  final String? supplier;

  /// Lines / Σ qty.
  final int totalTypes, totalQtyMilli;
}

// ── AI invoice scan ────────────────────────────────────────────────────────

/// One line the AI read (`POST /receiving/scan` → `items[]`).
@immutable
class AiItem {
  /// Creates a line.
  const AiItem({
    required this.aiName,
    this.qty,
    this.unit = 'dona',
    this.productId,
    this.matchedName,
    this.confidence = 0,
    this.unitCost,
  });

  /// Parses a line.
  factory AiItem.fromJson(Map<String, dynamic> j) => AiItem(
        aiName: '${j['ai_name'] ?? ''}',
        qty: j['qty'],
        unit: '${j['unit'] ?? 'dona'}',
        productId: j['product_id']?.toString(),
        matchedName: j['matched_name']?.toString(),
        confidence: (j['confidence'] as num?)?.toDouble() ?? 0,
        unitCost: j['unit_cost'],
      );

  /// Name as printed on the invoice.
  final String aiName;

  /// Quantity as read (number or string; NOT rounded here).
  final Object? qty;

  /// Unit as read.
  final String unit;

  /// Matched catalog product (null = not matched).
  final String? productId, matchedName;

  /// Match score 0..1.
  final double confidence;

  /// Price as read (or the product's purchase price).
  final Object? unitCost;
}

/// `POST /receiving/scan` answer.
@immutable
class AiScan {
  /// Creates a scan.
  const AiScan({required this.source, required this.items, this.aiRaw = const []});

  /// Parses the answer.
  factory AiScan.fromJson(Map<String, dynamic> j) => AiScan(
        source: '${j['source'] ?? 'ai'}',
        items: [
          for (final e in (j['items'] as List? ?? const []))
            if (e is Map) AiItem.fromJson(e.cast<String, dynamic>())
        ],
        aiRaw: (j['ai_raw'] as List?) ?? const [],
      );

  /// `ai` or `demo` (no AI key on the server: rows are NOT read from the photo).
  final String source;

  /// Lines.
  final List<AiItem> items;

  /// Raw AI rows (audit, sent back with the commit).
  final List<dynamic> aiRaw;

  /// True for demo output.
  bool get isDemo => source == 'demo';
}

/// Text for a quantity the AI/server sent, WITHOUT silent rounding: a value
/// with more than 3 decimals keeps its digits so the field shows an error.
String qtyTextFromServer(Object? v) {
  if (v == null) return '';
  if (v is int) return v > 0 ? '$v' : '';
  final s = v is double ? _shortDouble(v) : '$v'.trim();
  final p = parseQty(s, allowZero: true);
  if (p.ok) return p.value == 0 ? '' : milliToInput(p.value!);
  return s.replaceAll('.', ',');
}

/// Text for a money value the AI/server sent (2 decimals kept, more shown as is).
String moneyTextFromServer(Object? v) {
  if (v == null) return '';
  if (v is int) return v > 0 ? '$v' : '';
  final s = v is double ? _shortDouble(v) : '$v'.trim();
  final p = parseMoney(s, allowZero: true);
  if (p.ok) return p.value == 0 ? '' : centsToInput(p.value!);
  return s.replaceAll('.', ',');
}

String _shortDouble(double v) {
  if (v.isNaN || v.isInfinite) return '';
  if (v == v.roundToDouble() && v.abs() < 1e15) return v.toStringAsFixed(0);
  // Shortest representation that parses back to the same double
  // (0.1 + 0.2 -> "0.30000000000000004" is kept, so it shows as invalid).
  for (var d = 1; d <= 12; d++) {
    final s = v.toStringAsFixed(d);
    if (double.parse(s) == v) return s;
  }
  return '$v';
}

// ── Draft line ─────────────────────────────────────────────────────────────

int _lineSeq = 0;

/// One line of a receiving draft (manual or AI).
///
/// A tracked line owns a live [LotEditorController] ([lots]); the owner of the
/// line list disposes it ([dispose]).
class RecvLine {
  /// Creates a line.
  RecvLine({
    String? key,
    this.product,
    this.newName = '',
    this.unit = 'dona',
    this.barcode = '',
    this.barcodeVerified = false,
    this.plu = '',
    this.categoryId,
    this.categoryName,
    this.sellText = '',
    this.minText = '',
    this.qtyText = '',
    this.costText = '',
    this.aiName,
    this.aiConfidence,
  }) : key = key ?? 'r${++_lineSeq}';

  /// Line from an AI-read row; flags of a matched product come from [tracked].
  factory RecvLine.fromAi(AiItem a, TrackedCatalog tracked) {
    final l = RecvLine(
      aiName: a.aiName,
      aiConfidence: a.confidence,
      qtyText: qtyTextFromServer(a.qty),
      costText: moneyTextFromServer(a.unitCost),
      unit: kRecvUnits.contains(a.unit) ? a.unit : 'dona',
    );
    final id = a.productId;
    if (id != null && id.isNotEmpty) {
      final t = tracked.byId[id];
      l.setProduct(RecvProduct(
        id: id,
        name: a.matchedName ?? t?.name ?? a.aiName,
        trackLots: t != null,
        trackExpiry: t?.trackExpiry ?? false,
        unitCode: t?.unitCode,
      ));
    }
    return l;
  }

  /// Stable identity (list keys).
  final String key;

  /// The chosen existing product (null = new product or not chosen yet).
  RecvProduct? product;

  /// New product: name, unit, barcode (non-kg), PLU (kg), category, min qty.
  String newName, unit, barcode, plu;

  /// The barcode was checked against the catalog (scan lookup said "none").
  bool barcodeVerified;

  /// New product category (id + name for display).
  String? categoryId, categoryName;

  /// Sell price text (optional), min qty text (new product, optional).
  String sellText, minText;

  /// Quantity and unit cost texts as typed (comma or dot).
  String qtyText, costText;

  /// Name as read by the AI (audit `ai_name`), and the match score.
  String? aiName;

  /// AI match score (0..1), null for manual lines.
  double? aiConfidence;

  /// Lots of a tracked line (null for untracked lines).
  LotEditorController? lots;

  /// No existing product chosen.
  bool get isNew => product == null;

  /// Neither a product nor a new name — the AI line still needs attention.
  bool get unmatched => product == null && newName.trim().isEmpty;

  /// Lot-tracked (the chosen product).
  bool get tracked => product?.trackLots == true;

  /// Expiry-tracked.
  bool get trackExpiry => tracked && product!.trackExpiry;

  /// Name to show.
  String get displayName => product?.name ?? (newName.trim().isNotEmpty ? newName.trim() : (aiName ?? ''));

  /// Unit to show (`''` when unknown).
  String get unitCode => product == null ? unit : (product!.unitCode ?? '');

  /// Parsed quantity (milli) or null.
  int? get qtyMilli => parseQty(qtyText).value;

  /// Parsed unit cost (cents, 0 allowed; empty = 0) or null when invalid.
  int? get costCents => costText.trim().isEmpty ? 0 : parseMoney(costText, allowZero: true).value;

  /// Line total (cents) when qty and cost are valid.
  int? get totalCents {
    final q = qtyMilli, c = costCents;
    return (q == null || c == null) ? null : lineCents(q, c);
  }

  /// Chooses [p] (or clears with null). Creates / drops / reconfigures the lot
  /// editor so it matches the product's tracking.
  void setProduct(RecvProduct? p) {
    product = p;
    syncLots();
  }

  /// Makes [lots] match [tracked] / [trackExpiry] and the line quantity.
  void syncLots({String? businessDate}) {
    if (!tracked) {
      lots?.dispose();
      lots = null;
      return;
    }
    final c = lots;
    if (c == null) {
      lots = LotEditorController(trackExpiry: trackExpiry, businessDate: businessDate, targetMilli: qtyMilli);
      return;
    }
    c.trackExpiry = trackExpiry;
    c.targetMilli = qtyMilli;
    if (businessDate != null) c.businessDate = businessDate;
  }

  /// Sets the quantity text; the automatic lot row follows it.
  void setQtyText(String t) {
    qtyText = t;
    lots?.targetMilli = qtyMilli;
  }

  /// A deep copy (the lot editor is rebuilt, keeping the "follows the line
  /// quantity" state of an untouched single row).
  RecvLine clone() {
    final c = RecvLine(
      key: key,
      product: product,
      newName: newName,
      unit: unit,
      barcode: barcode,
      barcodeVerified: barcodeVerified,
      plu: plu,
      categoryId: categoryId,
      categoryName: categoryName,
      sellText: sellText,
      minText: minText,
      qtyText: qtyText,
      costText: costText,
      aiName: aiName,
      aiConfidence: aiConfidence,
    );
    final src = lots;
    if (src != null) c.lots = cloneLotController(src);
    return c;
  }

  /// Releases the lot editor.
  void dispose() {
    lots?.dispose();
    lots = null;
  }
}

/// Copy of a lot editor state (same rows; an automatic single row stays automatic).
LotEditorController cloneLotController(LotEditorController c) {
  if (c.autoFollowing) {
    final n = LotEditorController(trackExpiry: c.trackExpiry, businessDate: c.businessDate, targetMilli: c.targetMilli);
    final src = c.rows.first;
    n.update(n.rows.first.key, expiry: src.expiry, batch: src.batch);
    return n;
  }
  return LotEditorController(
      rows: c.rows, trackExpiry: c.trackExpiry, businessDate: c.businessDate, targetMilli: c.targetMilli);
}

// ── Validation ─────────────────────────────────────────────────────────────

/// What is wrong with a line (client pre-check; the server decides).
enum RecvIssueKind {
  /// Neither a product nor a new name.
  unmatched,

  /// New product: name empty.
  name,

  /// New product named like a TRACKED product.
  trackedName,

  /// New non-kg product: barcode missing / not 6..14 digits.
  barcode,

  /// New kg product: PLU missing / not 1..5 digits.
  plu,

  /// Quantity invalid.
  qty,

  /// Unit cost invalid (or not > 0 on a tracked line).
  cost,

  /// Sell price invalid.
  sell,

  /// Min quantity invalid.
  min,

  /// Lots invalid (tracked line).
  lots,
}

/// One issue with its localized message.
@immutable
class RecvIssue {
  /// Creates an issue.
  const RecvIssue(this.kind, this.message);

  /// Kind.
  final RecvIssueKind kind;

  /// Localized text.
  final String message;

  @override
  String toString() => 'RecvIssue($kind)';
}

final RegExp _digits = RegExp(r'^\d+$');

/// Server `_norm_barcode`: 6..14 digits.
bool isValidBarcode(String s) => _digits.hasMatch(s) && s.length >= 6 && s.length <= 14;

/// Server `_valid_plu`: 1..5 digits.
bool isValidPlu(String s) => _digits.hasMatch(s) && s.isNotEmpty && s.length <= 5;

/// Issues of [l], in field order. [tracked] enables the tracked-name check.
List<RecvIssue> lineIssues(RecvLine l, {TrackedCatalog? tracked}) {
  final out = <RecvIssue>[];
  if (l.unmatched && l.aiName != null) {
    out.add(RecvIssue(RecvIssueKind.unmatched, tr('Mahsulotni tanlang yoki yangi mahsulot yarating')));
    return out;
  }
  if (l.isNew) {
    final name = l.newName.trim();
    if (name.isEmpty) {
      out.add(RecvIssue(RecvIssueKind.name, tr('Mahsulot nomini kiriting')));
    } else {
      final t = tracked?.byName(name);
      if (t != null) {
        out.add(RecvIssue(RecvIssueKind.trackedName,
            trArgs('«{name}» nomli mahsulot bor va u partiya bo‘yicha kuzatiladi — uni ro‘yxatdan tanlang', {'name': t.name})));
      }
    }
    if (l.unit == 'kg') {
      final plu = l.plu.trim();
      if (plu.isEmpty) {
        out.add(RecvIssue(RecvIssueKind.plu, tr('Tarozi PLU kodini kiriting')));
      } else if (!isValidPlu(plu)) {
        out.add(RecvIssue(RecvIssueKind.plu, tr('PLU kodi 1–5 raqamdan iborat bo‘lsin')));
      }
    } else {
      final bc = l.barcode.trim();
      if (bc.isEmpty) {
        out.add(RecvIssue(RecvIssueKind.barcode, tr('Shtrix-kodni kiriting yoki skanerlang')));
      } else if (!isValidBarcode(bc)) {
        out.add(RecvIssue(RecvIssueKind.barcode, tr('Shtrix-kod 6–14 raqamdan iborat bo‘lsin')));
      }
    }
  }
  final q = parseQty(l.qtyText);
  if (!q.ok) out.add(RecvIssue(RecvIssueKind.qty, qtyErrorText(q.error!)));
  final cost = l.costCents;
  if (cost == null) {
    final e = parseMoney(l.costText, allowZero: true).error ?? NumError.invalid;
    out.add(RecvIssue(RecvIssueKind.cost, moneyErrorText(e)));
  } else if (l.tracked && cost <= 0) {
    out.add(RecvIssue(RecvIssueKind.cost, tr('Partiyali mahsulot uchun kelish narxi noldan katta bo‘lsin')));
  }
  if (l.sellText.trim().isNotEmpty && !parseMoney(l.sellText, allowZero: true).ok) {
    out.add(RecvIssue(RecvIssueKind.sell, moneyErrorText(parseMoney(l.sellText, allowZero: true).error!)));
  }
  if (l.isNew && l.minText.trim().isNotEmpty && !parseQty(l.minText, allowZero: true).ok) {
    out.add(RecvIssue(RecvIssueKind.min, qtyErrorText(parseQty(l.minText, allowZero: true).error!)));
  }
  final c = l.lots;
  if (l.tracked) {
    if (c == null) {
      out.add(RecvIssue(RecvIssueKind.lots, tr('Partiyalarni kiriting')));
    } else if (q.ok) {
      final st = c.state;
      if (!st.ok) out.add(RecvIssue(RecvIssueKind.lots, lotIssueText(st, c.businessDate)));
    }
  }
  return out;
}

/// One-line localized explanation of the first lot issue (desktop `lotIssueText`).
String lotIssueText(LotLineState st, String? businessDate) {
  if (st.ok) return '';
  final first = st.issues.first.kind;
  return switch (first) {
    LotIssueKind.lineQty => tr('Avval qator miqdorini kiriting'),
    LotIssueKind.qty => tr('Har partiyaning miqdorini kiriting'),
    LotIssueKind.decimals => tr('Ko‘pi bilan 3 ta kasr xona (0,001)'),
    LotIssueKind.mismatch => (st.diffMilli ?? 0) > 0
        ? trArgs('Partiyalar yig‘indisi qator miqdoridan {n} kam', {'n': formatMilli(st.diffMilli!)})
        : trArgs('Partiyalar yig‘indisi qator miqdoridan {n} ortiq', {'n': formatMilli(-(st.diffMilli ?? 0))}),
    LotIssueKind.expiryMissing => tr('Har partiyaga yaroqlilik muddatini kiriting'),
    LotIssueKind.expiryPast => businessDate == null
        ? tr('Muddati o‘tgan partiya qabul qilinmaydi')
        : trArgs('Muddat {d} dan oldin bo‘lishi mumkin emas', {'d': dateDisplay(businessDate)}),
    LotIssueKind.tooMany => trArgs('Ko‘pi bilan {n} ta partiya', {'n': kMaxLots}),
    LotIssueKind.cost => tr('Tannarx noto‘g‘ri'),
  };
}

/// Document-level issues (two NEW lines with the same new barcode / PLU —
/// the server would silently keep only one of them).
List<String> documentIssues(List<RecvLine> lines) {
  final out = <String>[];
  final bcs = <String>[], plus = <String>[];
  for (final l in lines) {
    if (!l.isNew || l.unmatched) continue;
    if (l.unit == 'kg') {
      final p = l.plu.trim().replaceFirst(RegExp(r'^0+(?=\d)'), '');
      if (p.isNotEmpty) plus.add(p);
    } else if (l.barcode.trim().isNotEmpty) {
      bcs.add(l.barcode.trim());
    }
  }
  if (bcs.toSet().length != bcs.length) {
    out.add(tr('Ikki yangi mahsulotda bir xil shtrix-kod — har biriga alohida kod bering'));
  }
  if (plus.toSet().length != plus.length) {
    out.add(tr('Ikki yangi mahsulotda bir xil PLU — har biriga alohida PLU bering'));
  }
  return out;
}

// ── Payload ────────────────────────────────────────────────────────────────

/// `items[]` entry for [l] (desktop `FullReceiving.save` shape).
///
/// Untracked lines: exactly the legacy keys (no `lots`). Tracked lines: `qty`
/// rebuilt from milli and `lots` = [LotEditorController.lotsPayload].
Map<String, Object?> commitItem(RecvLine l) {
  final isNew = l.isNew;
  final kg = isNew && l.unit == 'kg';
  final sell = l.sellText.trim().isEmpty ? null : parseMoney(l.sellText, allowZero: true).value;
  final minQ = (isNew && l.minText.trim().isNotEmpty) ? parseQty(l.minText, allowZero: true).value : null;
  final item = <String, Object?>{
    'product_id': l.product?.id,
    'new_name': isNew ? l.newName.trim() : null,
    'new_sell_price': sell == null ? null : centsToJson(sell),
    'new_category_id': isNew ? l.categoryId : null,
    'new_barcode': (isNew && !kg && l.barcode.trim().isNotEmpty) ? l.barcode.trim() : null,
    'new_plu': (kg && l.plu.trim().isNotEmpty) ? l.plu.trim() : null,
    'new_is_weighted': isNew ? kg : null,
    'new_min_qty': minQ == null ? null : milliToJson(minQ),
    'qty': milliToJson(l.qtyMilli ?? 0),
    'unit_cost': centsToJson(l.costCents ?? 0),
    'ai_name': l.aiName,
    // Existing product: the SERVER records its own unit (an AI-read unit is not the product's).
    'unit': isNew ? l.unit : null,
  };
  if (l.tracked && l.lots != null) item['lots'] = l.lots!.lotsPayload();
  return item;
}

/// The full `POST /receiving/commit` body.
Map<String, Object?> commitBody({
  required List<RecvLine> lines,
  required String clientUuid,
  required String payment,
  required String source,
  String? supplierId,
  String? cashAccountId,
  String? imageB64,
  List<dynamic> aiRaw = const [],
}) =>
    {
      'client_uuid': clientUuid,
      'items': [for (final l in lines) commitItem(l)],
      'image_b64': imageB64,
      'source': source,
      'ai_raw': source == 'manual' ? const [] : aiRaw,
      'supplier_id': supplierId,
      'payment': payment,
      if (cashAccountId != null) 'cash_account_id': cashAccountId,
    };

/// Σ line totals (cents) of the lines whose qty and cost are valid.
int draftTotalCents(Iterable<RecvLine> lines) => lines.fold(0, (a, l) => a + (l.totalCents ?? 0));

/// Σ quantities (milli) of the lines with a valid qty.
int draftTotalMilli(Iterable<RecvLine> lines) => lines.fold(0, (a, l) => a + (l.qtyMilli ?? 0));

// ── Receiving branch ──────────────────────────────────────────────────────

/// Why receiving cannot be submitted for branch reasons.
enum RecvBranchIssue {
  /// The receiving branch is known and is the one on screen.
  none,

  /// `/auth/context` is still loading.
  loading,

  /// The receiving (actor) branch is not known — session not loaded / old server.
  unknown,

  /// The operator is looking at another branch than the one the server writes to.
  mismatch,
}

/// Where a receiving goes. The SERVER always writes to the employee's actor
/// branch (`receiving.py` → `custody_preview.receiving_branch`): the screen
/// shows it explicitly and refuses a silent mismatch with the branch on screen.
@immutable
class RecvBranchState {
  /// Creates a state.
  const RecvBranchState(this.issue, {this.actor, this.current});

  /// Computes the state of [s] (default [Session.instance]).
  factory RecvBranchState.of([Session? s]) {
    final ses = s ?? Session.instance;
    final a = ses.actorBranch;
    if (a == null) {
      final loading = ses.status == SessionStatus.loading;
      return RecvBranchState(loading ? RecvBranchIssue.loading : RecvBranchIssue.unknown);
    }
    final c = ses.currentBranch;
    if (c != null && c.id != a.id) return RecvBranchState(RecvBranchIssue.mismatch, actor: a, current: c);
    return RecvBranchState(RecvBranchIssue.none, actor: a, current: c);
  }

  /// Issue.
  final RecvBranchIssue issue;

  /// The branch the server writes to.
  final BranchInfo? actor;

  /// The branch on screen.
  final BranchInfo? current;

  /// Submitting is allowed.
  bool get ok => issue == RecvBranchIssue.none;

  /// Localized reason (empty when ok).
  String reason() => switch (issue) {
        RecvBranchIssue.none => '',
        RecvBranchIssue.loading => tr('Filial ma’lumoti yuklanmoqda…'),
        RecvBranchIssue.unknown => tr('Qabul filiali aniqlanmadi — aloqani tekshirib, qayta urinib ko‘ring.'),
        RecvBranchIssue.mismatch => trArgs(
            'Siz «{current}» filialini ko‘ryapsiz, lekin kirim faqat «{actor}» filialiga yoziladi. Kirim qilish uchun «{actor}» filialiga o‘ting.',
            {'current': current?.name ?? '', 'actor': actor?.name ?? ''}),
      };
}

// ── Server calls ───────────────────────────────────────────────────────────

/// Server calls of the receiving flows. Every call throws [ApiException] on
/// any failure (network included).
abstract final class ReceivingApi {
  /// Business-date cache lifetime (desktop `BIZ_TTL`).
  static const Duration businessDateTtl = Duration(minutes: 5);

  static String? _bizDate;
  static DateTime? _bizAt;
  static String? _bizScope;
  static List<CategoryLite>? _cats;
  static String? _catsScope;

  static String _scope() => '${Api.serverKey()}|${Api.employee?['id'] ?? '-'}|${Session.instance.actorBranch?.id ?? '-'}';

  /// Clears caches (tests, logout).
  @visibleForTesting
  static void debugReset() {
    _bizDate = null;
    _bizAt = null;
    _bizScope = null;
    _cats = null;
    _catsScope = null;
  }

  /// `POST /receiving/scan` — the AI reads the invoice photo. Changes NOTHING.
  static Future<AiScan> scanInvoice(String imageB64, String mediaType) async {
    final r = await Api.postJson('/receiving/scan', {'image_b64': imageB64, 'media_type': mediaType},
        timeout: const Duration(seconds: 90));
    return AiScan.fromJson(r.map);
  }

  /// Server-side product search for receiving (archived included: a receiving
  /// re-activates an archived product). At most [limit] rows.
  static Future<List<RecvProduct>> searchProducts(String q, {int limit = 30}) async {
    final r = await Api.getJson('/products', query: {
      'q': q.trim(),
      'limit': limit,
      'include_archived': 1,
    });
    return [for (final e in r.list) if (e is Map) RecvProduct.fromJson(e.cast<String, dynamic>())];
  }

  /// `GET /products?tracked=true&include_archived=1`.
  static Future<TrackedCatalog> trackedProducts() async {
    final r = await Api.getJson('/products', query: {'tracked': true, 'include_archived': 1});
    return TrackedCatalog([for (final e in r.list) if (e is Map) RecvProduct.fromJson(e.cast<String, dynamic>())]);
  }

  /// Business date (`YYYY-MM-DD`) of the RECEIVING branch, for the expiry hint.
  ///
  /// `GET /lots/products/{id}` (actor branch, needs `ombor.view`) first — it is
  /// computed now by the server; otherwise the actor branch's date from
  /// `/auth/context`. Null when neither is known: the client then skips the
  /// past-date check and the server decides. Cached for [businessDateTtl].
  static Future<String?> businessDate(String? probeProductId) async {
    final scope = _scope();
    final at = _bizAt;
    if (at != null && _bizScope == scope && DateTime.now().difference(at) < businessDateTtl) return _bizDate;
    String? d;
    if (probeProductId != null && Perm.allows('lots.product')) {
      try {
        final r = await Api.getJson('/lots/products/${Api.seg(probeProductId)}');
        d = r.map['business_date']?.toString();
      } catch (_) {
        d = null; // ruxsat yo'q / xato — sessiyadagi sanaga tushamiz, bo'lmasa server hal qiladi
      }
    }
    d = parseIsoDate(d) != null ? d : null;
    final fallback = Session.instance.actorBranch?.businessDate;
    d ??= parseIsoDate(fallback) != null ? fallback : null;
    _bizDate = d;
    _bizAt = DateTime.now();
    _bizScope = scope;
    return d;
  }

  /// Categories (cached per server + employee).
  static Future<List<CategoryLite>> categories() async {
    final scope = _scope();
    final c = _cats;
    if (c != null && _catsScope == scope) return c;
    final list = await Api.catList();
    _cats = list;
    _catsScope = scope;
    return list;
  }

  /// Category guess for a new product name (never throws).
  static Future<(String?, String?)> guessCategory(String name) => Api.guessCategory(name);

  /// Suppliers (`xaridlar.view`); empty when the operator may not list them.
  static Future<List<SupplierRow>> suppliers() async {
    if (!Perm.allows('suppliers.list')) return const [];
    return Api.suppliers();
  }

  /// `GET /cash/custody-preview?operation=receiving_payment`.
  static Future<CustodyInfo> custodyPreview() => fetchCustodyPreview(CustodyOperation.receivingPayment);

  /// `POST /receiving/commit` with a body built by [commitBody]. On success
  /// (duplicate included — an earlier attempt DID change stock) the catalog
  /// cache is invalidated.
  static Future<CommitResult> commit(Map<String, Object?> body) async {
    final r = await Api.postJson('/receiving/commit', body);
    final res = CommitResult.fromJson(r.map);
    Api.invalidateCatalog();
    return res;
  }

  /// `GET /receiving` (latest first).
  static Future<List<ReceivingDoc>> history({int limit = 50}) async {
    final r = await Api.getJson('/receiving', query: {'limit': limit});
    return [for (final e in r.list) if (e is Map) ReceivingDoc.fromJson(e.cast<String, dynamic>())];
  }

  /// `GET /receiving/{id}`.
  static Future<ReceivingDetail> detail(String id) async {
    final r = await Api.getJson('/receiving/${Api.seg(id)}');
    return ReceivingDetail.fromJson(r.map);
  }
}
