/// Receiving correction / cancel (Phase 5D + 5E cash custody) — data layer.
///
/// * [CorrectionApi.purchase] — `GET /purchases/{id}` (`xaridlar.view`): the
///   document with its lines, the lots each line created (`lots[]` with
///   `remaining_qty`, `consumed_qty`, `correctable`, `doc_unit_cost`), the
///   document-level `correctable` / `correction_blocked_reason`, the history
///   (`corrections[]`), the cash custody block and the DOCUMENT branch with
///   its business date.
/// * [CorrectionApi.submit] — `POST /receiving/{receiving_id}/corrections`
///   (`xaridlar.edit`).
///
/// ⚠️  Every decision stays on the server: whether a lot's identity may still
///     be corrected (`correctable`), whether a line is blocked (open lot
///     shortfall), the custody mode. This file only parses what the server
///     said; it never recomputes those rules.
///
/// Quantities are integer thousandths ("milli") and money integer hundredths
/// ("cents") — see `lib/qty.dart`.
library;

import '../api.dart';
import '../l10n.dart';
import '../qty.dart';
import '../widgets/custody_block.dart';

String? _str(Object? v) {
  if (v == null) return null;
  final s = '$v'.trim();
  return s.isEmpty ? null : s;
}

/// A lot (cohort) the receiving created — read view of `items[].lots[]`.
class ReceivedLot {
  /// Creates a lot (tests may build one directly).
  const ReceivedLot({
    required this.id,
    this.batchNo,
    this.expiryDate,
    required this.receivedMilli,
    required this.remainingMilli,
    required this.consumedMilli,
    required this.unitCostCents,
    this.status = 'open',
    required this.correctable,
    this.docUnitCostCents,
    this.blockedReason,
  });

  /// Parses one `lots[]` entry of `GET /purchases/{id}`.
  factory ReceivedLot.fromJson(Map<String, dynamic> j) {
    final doc = j['doc_unit_cost'];
    return ReceivedLot(
      id: '${j['id']}',
      batchNo: _str(j['batch_no']),
      expiryDate: _str(j['expiry_date']),
      receivedMilli: milliFromNum(j['received_qty']),
      remainingMilli: milliFromNum(j['remaining_qty']),
      consumedMilli: milliFromNum(j['consumed_qty']),
      unitCostCents: centsFromNum(j['unit_cost']),
      status: '${j['status'] ?? 'open'}',
      // ⚠️  SERVER QARORI (`lot_correction.untouched`); kalit yo'q bo'lsa —
      //     «tuzatib bo'lmaydi» (fail-closed), taxmin qilinmaydi.
      correctable: j['correctable'] == true,
      // `0` ham javob (qator narxi rostdan nol); faqat kalit YO'Q bo'lsa null.
      docUnitCostCents: doc is num || (doc is String && doc.trim().isNotEmpty) ? centsFromNum(doc) : null,
      blockedReason: _str(j['blocked_reason']),
    );
  }

  /// Lot id (`stock_batch_id`).
  final String id;

  /// Batch number, if any.
  final String? batchNo;

  /// Expiry `YYYY-MM-DD`, if tracked.
  final String? expiryDate;

  /// Received quantity (milli).
  final int receivedMilli;

  /// Remaining quantity (milli) — the reversal limit.
  final int remainingMilli;

  /// GROSS quantity that already left the lot (milli).
  final int consumedMilli;

  /// The lot's own (COGS) unit cost in cents.
  final int unitCostCents;

  /// `open` / `depleted` / `void`.
  final String status;

  /// Server: the lot's identity may still be corrected (never moved).
  final bool correctable;

  /// Unit price on the DOCUMENT side (cents) — what reversing this lot takes
  /// off the document total. `null` from an older server.
  final int? docUnitCostCents;

  /// Line-level block reason copied onto the lot by the server.
  final String? blockedReason;

  /// Price used for the money preview: the document price, else (older
  /// server) the lot's own cost — desktop `docCost`.
  int get docCostCents => docUnitCostCents ?? unitCostCents;
}

/// One document line — `items[]` of `GET /purchases/{id}`.
class PurchaseLine {
  /// Creates a line.
  const PurchaseLine({
    required this.id,
    required this.productId,
    required this.name,
    required this.qtyMilli,
    required this.unitCostCents,
    required this.lineTotalCents,
    this.unit = 'dona',
    this.trackLots = false,
    this.trackExpiry = false,
    this.correctable,
    this.blockedReason,
    this.lots = const [],
  });

  /// Parses one `items[]` entry.
  factory PurchaseLine.fromJson(Map<String, dynamic> j) => PurchaseLine(
        id: '${j['id']}',
        productId: '${j['product_id']}',
        name: '${j['name'] ?? ''}',
        qtyMilli: milliFromNum(j['qty']),
        unitCostCents: centsFromNum(j['unit_cost']),
        lineTotalCents: centsFromNum(j['line_total']),
        unit: _str(j['unit']) ?? 'dona',
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        correctable: j['correctable'] is bool ? j['correctable'] as bool : null,
        blockedReason: _str(j['correction_blocked_reason']),
        lots: [
          for (final l in (j['lots'] as List? ?? const []))
            if (l is Map) ReceivedLot.fromJson(l.cast<String, dynamic>())
        ],
      );

  /// `purchase_item_id`.
  final String id;

  /// Product id.
  final String productId;

  /// Product name.
  final String name;

  /// Line quantity as recorded (milli) — never rewritten by corrections.
  final int qtyMilli;

  /// Line unit cost (cents).
  final int unitCostCents;

  /// Line total (cents).
  final int lineTotalCents;

  /// Unit code (`dona`, `kg`, ...).
  final String unit;

  /// Product is tracked by lots.
  final bool trackLots;

  /// Product tracks expiry dates.
  final bool trackExpiry;

  /// Server: this line may be corrected (null from an older server).
  final bool? correctable;

  /// Why this line may not be corrected (raw server text).
  final String? blockedReason;

  /// Lots this receiving created for the line's product.
  final List<ReceivedLot> lots;
}

/// One entry of `corrections[]` (newest first).
class CorrectionRecord {
  /// Creates a record.
  const CorrectionRecord({required this.id, this.at, required this.reason, required this.deltaCents, this.employee = ''});

  /// Parses `{id, at, reason, delta_total, employee}`.
  factory CorrectionRecord.fromJson(Map<String, dynamic> j) => CorrectionRecord(
        id: '${j['id']}',
        at: serverDt(j['at']),
        reason: '${j['reason'] ?? ''}',
        deltaCents: centsFromNum(j['delta_total']),
        employee: '${j['employee'] ?? ''}',
      );

  /// Correction id.
  final String id;

  /// When it was written (local time).
  final DateTime? at;

  /// Operator's reason.
  final String reason;

  /// Change of the document total (cents, signed).
  final int deltaCents;

  /// Who wrote it.
  final String employee;
}

/// Parsed `GET /purchases/{id}`.
class PurchaseDoc {
  /// Creates a document (tests may build one directly).
  const PurchaseDoc({
    required this.id,
    required this.docNo,
    this.supplier = '',
    this.supplierId,
    this.date,
    this.status = 'received',
    this.payment = 'cash',
    required this.totalCents,
    required this.paidCents,
    this.subtotalCents = 0,
    this.lines = const [],
    this.receivingId,
    this.correctable,
    this.blockedReason,
    this.corrections = const [],
    this.cashCustody,
    this.branchId,
    this.branchName,
    this.businessDate,
  });

  /// Parses the server payload.
  ///
  /// Missing Phase 5D/5E keys (older server) stay `null`: no correction flow
  /// is offered and no custody block is shown or sent — never guessed.
  factory PurchaseDoc.fromJson(Map<String, dynamic> j) => PurchaseDoc(
        id: '${j['id']}',
        docNo: '${j['doc_no'] ?? ''}',
        supplier: '${j['supplier'] ?? ''}',
        supplierId: _str(j['supplier_id']),
        date: _str(j['date']),
        status: '${j['status'] ?? ''}',
        payment: '${j['payment'] ?? 'cash'}',
        subtotalCents: centsFromNum(j['subtotal']),
        totalCents: centsFromNum(j['total']),
        paidCents: centsFromNum(j['paid_amount']),
        lines: [
          for (final it in (j['items'] as List? ?? const []))
            if (it is Map) PurchaseLine.fromJson(it.cast<String, dynamic>())
        ],
        receivingId: _str(j['receiving_id']),
        correctable: j['correctable'] is bool ? j['correctable'] as bool : null,
        blockedReason: _str(j['correction_blocked_reason']),
        corrections: [
          for (final c in (j['corrections'] as List? ?? const []))
            if (c is Map) CorrectionRecord.fromJson(c.cast<String, dynamic>())
        ],
        // Kalit BOR, lekin shakli noma'lum -> CustodyInfo o'zi BLOCKED qiladi (fail-closed).
        cashCustody: j.containsKey('cash_custody')
            ? CustodyInfo.fromJson((j['cash_custody'] as Map?)?.cast<String, dynamic>())
            : null,
        branchId: _str(j['branch_id']),
        branchName: _str(j['branch_name']),
        businessDate: _str(j['business_date']),
      );

  /// Purchase id.
  final String id;

  /// Document number.
  final String docNo;

  /// Supplier name (`—` when none).
  final String supplier;

  /// Supplier id.
  final String? supplierId;

  /// Purchase date `YYYY-MM-DD`.
  final String? date;

  /// `received` / `debt` / `partial` / `cancelled`.
  final String status;

  /// `cash` / `credit` (as the server labels it).
  final String payment;

  /// Subtotal (cents).
  final int subtotalCents;

  /// Document total (cents).
  final int totalCents;

  /// Paid amount (cents).
  final int paidCents;

  /// Lines.
  final List<PurchaseLine> lines;

  /// The receiving the corrections endpoint is addressed by.
  final String? receivingId;

  /// Server: the document may be corrected (null = older server, no flow).
  final bool? correctable;

  /// Why the document may not be corrected (raw server text).
  final String? blockedReason;

  /// Corrections already written (newest first).
  final List<CorrectionRecord> corrections;

  /// Cash custody block (null = older server: nothing shown, nothing sent).
  final CustodyInfo? cashCustody;

  /// The DOCUMENT branch (corrections are written there).
  final String? branchId;

  /// Its name.
  final String? branchName;

  /// Its business date `YYYY-MM-DD` (replacement expiry must not be earlier).
  final String? businessDate;

  /// True when the server offers the correction flow for this document.
  bool get correctionOpen => receivingId != null && correctable == true;

  /// True when the document is a credit (supplier debt) document.
  bool get isCredit => payment == 'credit';
}

/// Reply of `POST /receiving/{id}/corrections`.
class CorrectionResult {
  /// Creates a result.
  const CorrectionResult({
    this.ok = true,
    this.correctionId,
    this.receivingId,
    this.purchaseId,
    this.reversedCents = 0,
    this.replacedCents = 0,
    this.deltaCents = 0,
    this.purchaseStatus,
    this.cancelled = false,
    this.duplicate = false,
  });

  /// Parses the server reply.
  factory CorrectionResult.fromJson(Map<String, dynamic> j) => CorrectionResult(
        ok: j['ok'] != false,
        correctionId: _str(j['correction_id']),
        receivingId: _str(j['receiving_id']),
        purchaseId: _str(j['purchase_id']),
        reversedCents: centsFromNum(j['reversed_total']),
        replacedCents: centsFromNum(j['replaced_total']),
        deltaCents: centsFromNum(j['delta_total']),
        purchaseStatus: _str(j['purchase_status']),
        cancelled: j['cancelled'] == true,
        duplicate: j['duplicate'] == true,
      );

  /// Server said ok.
  final bool ok;

  /// Correction id.
  final String? correctionId;

  /// Receiving id.
  final String? receivingId;

  /// Purchase id.
  final String? purchaseId;

  /// Reversed value on the document basis (cents).
  final int reversedCents;

  /// Replaced value (cents).
  final int replacedCents;

  /// Change of the document total (cents).
  final int deltaCents;

  /// Document status after the correction.
  final String? purchaseStatus;

  /// The whole document was reversed and cancelled (its GET is now 404).
  final bool cancelled;

  /// The same `client_uuid` was already applied: nothing new was written.
  final bool duplicate;
}

/// HTTP calls of the correction flow.
abstract final class CorrectionApi {
  /// `GET /purchases/{id}`.
  static Future<PurchaseDoc> purchase(String purchaseId) async {
    final r = await Api.getJson('/purchases/${Api.seg(purchaseId)}');
    return PurchaseDoc.fromJson(r.map);
  }

  /// `POST /receiving/{receivingId}/corrections` with a ready [body]
  /// (`client_uuid`, `reason`, `lines`, optional `cash_account_id`).
  ///
  /// Success ONLY on a 2xx; every failure throws an `ApiException` (a
  /// network/timeout failure means the outcome is unknown — resend the SAME
  /// body with the SAME `client_uuid`).
  static Future<CorrectionResult> submit({required String receivingId, required Map<String, Object?> body}) async {
    final r = await Api.postJson('/receiving/${Api.seg(receivingId)}/corrections', body);
    final res = CorrectionResult.fromJson(r.map);
    // Qoldiq va partiyalar o'zgardi — ombor ekranlari yangilansin.
    Api.invalidateCatalog();
    return res;
  }
}
