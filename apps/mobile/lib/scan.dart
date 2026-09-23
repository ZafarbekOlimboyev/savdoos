/// Barcode lookup through the SERVER (`GET /products/scan`).
///
/// The client never parses barcodes: weighed (scale) labels, leading zeros and
/// archived products are resolved by the backend with the same parser the POS
/// uses (`packages/shared/src/lib/scaleBarcode.ts`). The client only
/// debounces camera detections ([ScanDebouncer]) and renders the outcome.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api.dart';
import 'qty.dart';
import 'session.dart';

/// Outcome kind of a lookup.
enum ScanKind {
  /// Exact barcode match.
  barcode,

  /// A weighed-label (scale) code matched ONE weighted product by PLU.
  scale,

  /// Nothing matched.
  none,

  /// Several products share the scale PLU — the operator must choose.
  ambiguous,
}

/// A product as returned by the lookup (`ProductOut`).
@immutable
class ScanProduct {
  /// Creates a product.
  const ScanProduct({
    required this.id,
    required this.name,
    this.unitCode = 'dona',
    this.isActive = true,
    this.isWeighted = false,
    this.trackLots = false,
    this.trackExpiry = false,
    this.pluCode,
    this.barcodes = const [],
    this.stockMilli,
    this.sellPriceCents,
    this.buyPriceCents,
    this.raw = const {},
  });

  /// Parses `ProductOut`.
  factory ScanProduct.fromJson(Map<String, dynamic> j) => ScanProduct(
        id: '${j['id']}',
        name: '${j['name'] ?? ''}',
        unitCode: '${j['unit_code'] ?? 'dona'}',
        isActive: j['is_active'] != false,
        isWeighted: j['is_weighted'] == true,
        trackLots: j['track_lots'] == true,
        trackExpiry: j['track_expiry'] == true,
        pluCode: j['plu_code']?.toString(),
        barcodes: [for (final b in (j['barcodes'] as List? ?? const [])) '$b'],
        stockMilli: j['stock'] == null ? null : milliFromNum(j['stock']),
        sellPriceCents: j['base_sell_price'] == null ? null : centsFromNum(j['base_sell_price']),
        buyPriceCents: j['base_buy_price'] == null ? null : centsFromNum(j['base_buy_price']),
        raw: j,
      );

  /// Product id.
  final String id;

  /// Name.
  final String name;

  /// Unit code (`dona`, `kg`, ...).
  final String unitCode;

  /// False for an archived product (still returned — the caller decides).
  final bool isActive;

  /// Sold by weight.
  final bool isWeighted;

  /// Lot-tracked.
  final bool trackLots;

  /// Expiry-tracked.
  final bool trackExpiry;

  /// Scale PLU.
  final String? pluCode;

  /// Barcodes (strings, leading zeros kept).
  final List<String> barcodes;

  /// Stock in the requested branch (milli), if sent.
  final int? stockMilli;

  /// Sell / buy price in cents, if sent.
  final int? sellPriceCents, buyPriceCents;

  /// The raw JSON (for fields not modelled here).
  final Map<String, dynamic> raw;
}

/// Scale label details: PLU, grams and the quantity (milli = grams).
@immutable
class ScaleInfo {
  /// Creates the info.
  const ScaleInfo({required this.plu, required this.grams, required this.qtyMilli});

  /// Parses `{plu, grams, qty}` (`qty` is a 3-decimal string).
  factory ScaleInfo.fromJson(Map<String, dynamic> j) => ScaleInfo(
        plu: (j['plu'] as num?)?.toInt() ?? int.tryParse('${j['plu']}') ?? 0,
        grams: (j['grams'] as num?)?.toInt() ?? int.tryParse('${j['grams']}') ?? 0,
        qtyMilli: milliFromNum(j['qty']),
      );

  /// Product PLU from the label.
  final int plu;

  /// Weight in grams from the label.
  final int grams;

  /// Quantity in milli (kg × 1000).
  final int qtyMilli;
}

/// `GET /products/scan` response.
@immutable
class ScanLookup {
  /// Creates a lookup.
  const ScanLookup({required this.code, required this.kind, this.product, this.candidates = const [], this.scale});

  /// Parses the server payload; an unknown kind is treated as [ScanKind.none].
  factory ScanLookup.fromJson(Map<String, dynamic> j) {
    final kind = switch ('${j['kind']}') {
      'barcode' => ScanKind.barcode,
      'scale' => ScanKind.scale,
      'ambiguous' => ScanKind.ambiguous,
      _ => ScanKind.none,
    };
    final p = j['product'];
    final s = j['scale'];
    return ScanLookup(
      code: '${j['code'] ?? ''}',
      kind: kind,
      product: p is Map ? ScanProduct.fromJson(p.cast<String, dynamic>()) : null,
      candidates: [
        for (final c in (j['candidates'] as List? ?? const []))
          if (c is Map) ScanProduct.fromJson(c.cast<String, dynamic>())
      ],
      scale: s is Map ? ScaleInfo.fromJson(s.cast<String, dynamic>()) : null,
    );
  }

  /// The normalised code the server looked up (digits, leading zeros kept).
  final String code;

  /// Outcome.
  final ScanKind kind;

  /// The matched product (barcode / scale).
  final ScanProduct? product;

  /// Candidates (ambiguous scale PLU).
  final List<ScanProduct> candidates;

  /// Scale label details (scale / ambiguous).
  final ScaleInfo? scale;
}

/// What the scan flow hands back to the caller.
@immutable
class ScanResult {
  /// Creates a result.
  const ScanResult(this.lookup, this.product);

  /// The server lookup.
  final ScanLookup lookup;

  /// The resolved product (chosen by the operator when ambiguous); null when
  /// nothing matched and the caller allowed "continue with this code".
  final ScanProduct? product;

  /// The looked-up code.
  String get code => lookup.code;

  /// Outcome kind.
  ScanKind get kind => lookup.kind;

  /// Weighed quantity from a scale label (milli), if any.
  int? get qtyMilli => lookup.scale?.qtyMilli;

  /// True when no product matched.
  bool get notFound => product == null;

  /// True when the SERVER recognised the code as a weighed (scale) label.
  ///
  /// Such a code carries the weight of one pack, so it differs on every pack:
  /// it may be used as a quantity ([qtyMilli]) but NEVER stored as a product's
  /// permanent barcode.
  bool get isWeighedLabel => lookup.scale != null;
}

/// Server lookup.
class ScanService {
  ScanService._();

  /// Trims whitespace and control characters (GS1 separators) — the SERVER
  /// extracts digits and decides everything else.
  static String normalize(String raw) => raw.replaceAll(RegExp(r'[\x00-\x1F\x7F]'), '').trim();

  /// `GET /products/scan?code=&branch_id=` (branch defaults to the session's
  /// current branch, so stock is that branch's).
  static Future<ScanLookup> lookup(String code, {String? branchId}) async {
    final r = await Api.getJson('/products/scan', query: {
      'code': normalize(code),
      'branch_id': branchId ?? Session.instance.currentBranchId,
    });
    return ScanLookup.fromJson(r.map);
  }
}

/// Camera detections arrive many times per second. The debouncer lets a code
/// through only when no lookup is in flight and the SAME code was not handled
/// within [window] (measured from the end of its last lookup).
///
/// A code the operator TYPED (`manual: true`) is never debounced and never
/// dropped: it waits for the lookup in flight instead of being swallowed by
/// the busy guard.
class ScanDebouncer {
  /// Creates a debouncer; [now] is injectable for tests.
  ScanDebouncer({this.window = const Duration(milliseconds: 1500), DateTime Function()? now})
      : _now = now ?? DateTime.now;

  /// Same-code quiet period.
  final Duration window;
  final DateTime Function() _now;
  String? _lastCode;
  DateTime? _lastAt;
  bool _busy = false;
  Completer<void>? _idle; // completes when the lookup in flight finishes

  /// A lookup is in flight.
  bool get busy => _busy;

  /// Whether a detection of [code] should start a lookup now.
  bool shouldProcess(String code) {
    if (_busy || code.isEmpty) return false;
    final at = _lastAt;
    return !(code == _lastCode && at != null && _now().difference(at) < window);
  }

  /// Runs [task] for [code] when allowed. Returns `(true, value)` when it ran,
  /// `(false, null)` when the detection was ignored.
  ///
  /// With [manual] the code came from the keyboard, not the camera: it is
  /// never ignored — neither by the quiet period nor by the in-flight guard —
  /// so a typed code can never disappear without a lookup.
  Future<(bool, T?)> run<T>(String code, Future<T> Function() task, {bool manual = false}) async {
    if (manual) {
      if (code.isEmpty) return (false, null);
      while (_busy) {
        final waiting = _idle;
        if (waiting == null) break;
        await waiting.future;
      }
      reset(); // a typed code is answered even if it was just scanned
    } else if (!shouldProcess(code)) {
      return (false, null);
    }
    _busy = true;
    _idle = Completer<void>();
    _lastCode = code;
    _lastAt = _now();
    try {
      return (true, await task());
    } finally {
      _busy = false;
      _lastAt = _now();
      final done = _idle;
      _idle = null;
      if (done != null && !done.isCompleted) done.complete();
    }
  }

  /// Forgets the last code (manual entry, "scan again").
  void reset() {
    _lastCode = null;
    _lastAt = null;
  }
}
