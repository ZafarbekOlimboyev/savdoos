/// Lot (batch) editor for a line of a lot-tracked product.
///
/// Used by receiving (`lots[]`), receiving-correction replacements (`replace[]`)
/// and stock-count `new_lots[]`. Mirrors the desktop `LotReceivingEditor`
/// (`packages/shared/src/components/LotReceivingEditor.tsx`):
///
///  * quantities are integer thousandths (milli) — `0.1 + 0.2` never lies;
///  * more than 3 decimals is an ERROR, never rounded;
///  * Σ rows == target quantity (when there is a target);
///  * an expiry date is required iff the product tracks expiry, and must be
///    on/after the branch BUSINESS date (unknown date -> not checked, the
///    server decides);
///  * at most [kMaxLots] rows (server limit);
///  * [lotsPayload] has exactly the desktop `lotsPayload` shape.
///
/// ⚠️  NO BUSINESS DECISION IS MADE HERE — the server validates everything
///     again and is the judge. This only tells the operator early.
library;

import 'dart:math';

import 'package:flutter/material.dart';

import '../l10n.dart';
import '../qty.dart';
import '../theme.dart';
import '../format.dart';
import '../ui/ui.dart';

/// Rows allowed per line (server `LotItem` list limit).
const int kMaxLots = 50;

final Random _rnd = Random();
int _seq = 0;

/// One lot row as typed by the operator.
class LotDraft {
  /// Creates a row; [key] identifies it across rebuilds.
  LotDraft({String? key, this.qty = '', this.expiry, this.batch = '', this.unitCost = ''})
      : key = key ?? 'l${++_seq}-${_rnd.nextInt(1 << 30)}';

  /// Stable row identity.
  final String key;

  /// Quantity text (comma or dot).
  String qty;

  /// Expiry `YYYY-MM-DD` or null.
  String? expiry;

  /// Batch number text (≤ 64).
  String batch;

  /// Unit cost text (only when the editor collects costs).
  String unitCost;

  /// A copy with the same key.
  LotDraft copy() => LotDraft(key: key, qty: qty, expiry: expiry, batch: batch, unitCost: unitCost);
}

/// What is wrong with a line or a row.
enum LotIssueKind {
  /// The line (target) quantity itself is invalid.
  lineQty,

  /// A row quantity is empty, zero or not a number (or there are no rows).
  qty,

  /// A row quantity has more than 3 decimals.
  decimals,

  /// Σ rows ≠ target.
  mismatch,

  /// Expiry required but empty.
  expiryMissing,

  /// Expiry before the business date.
  expiryPast,

  /// More than [kMaxLots] rows.
  tooMany,

  /// Unit cost missing or invalid (editors that collect costs).
  cost,
}

/// Field of a row, for first-error focus.
enum LotField {
  /// The line quantity (outside the editor).
  line,

  /// Row quantity.
  qty,

  /// Row expiry.
  expiry,

  /// Row unit cost.
  cost,
}

/// One issue; [key] is the row, null for line-level issues.
@immutable
class LotIssue {
  /// Creates an issue.
  const LotIssue(this.kind, [this.key]);

  /// Kind.
  final LotIssueKind kind;

  /// Row key.
  final String? key;

  @override
  String toString() => 'LotIssue($kind, $key)';
}

/// Validation state of a line and its rows (mirror of desktop `lotLineState`).
@immutable
class LotLineState {
  /// Creates a state.
  const LotLineState({
    required this.lineMilli,
    required this.sumMilli,
    required this.diffMilli,
    required this.issues,
    required this.firstBadKey,
    required this.firstBadField,
  });

  /// Target in milli (null if invalid or there is no target).
  final int? lineMilli;

  /// Σ of the valid row quantities.
  final int sumMilli;

  /// `lineMilli - sumMilli`; null when a quantity is invalid or no target.
  final int? diffMilli;

  /// All issues, in row order.
  final List<LotIssue> issues;

  /// Row of the first issue (null for a line-level issue).
  final String? firstBadKey;

  /// Field of the first issue (null when valid).
  final LotField? firstBadField;

  /// True when there is nothing to fix.
  bool get ok => issues.isEmpty;

  /// Whether an issue of [kind] exists (for row [key] when given).
  bool has(LotIssueKind kind, [String? key]) => issues.any((i) => i.kind == kind && (key == null || i.key == key));
}

/// Computes the [LotLineState].
///
/// * [targetMilli] — line quantity in milli; with [hasTarget] false (count
///   `new_lots`) there is no target and no Σ rule;
/// * [businessDate] — branch business date; null skips the past-date check;
/// * [withUnitCost] — rows carry a unit cost (≥ 0, required when
///   [unitCostRequired]);
/// * [allowEmpty] — zero rows is valid (count `new_lots`).
LotLineState lotLineState({
  required int? targetMilli,
  required List<LotDraft> lots,
  bool trackExpiry = false,
  String? businessDate,
  bool hasTarget = true,
  bool withUnitCost = false,
  bool unitCostRequired = true,
  bool allowEmpty = false,
}) {
  final issues = <LotIssue>[];
  final line = hasTarget ? targetMilli : null;
  if (hasTarget && (line == null || line <= 0)) issues.add(const LotIssue(LotIssueKind.lineQty));
  if (lots.length > kMaxLots) issues.add(const LotIssue(LotIssueKind.tooMany));
  var sum = 0;
  var bad = false;
  for (final l in lots) {
    final p = parseQty(l.qty);
    if (!p.ok) {
      bad = true;
      issues.add(LotIssue(p.error == NumError.tooManyDecimals ? LotIssueKind.decimals : LotIssueKind.qty, l.key));
    } else {
      sum += p.value!;
    }
    if (trackExpiry) {
      final e = l.expiry;
      if (e == null || e.isEmpty) {
        issues.add(LotIssue(LotIssueKind.expiryMissing, l.key));
      } else if (businessDate != null && e.compareTo(businessDate) < 0) {
        issues.add(LotIssue(LotIssueKind.expiryPast, l.key));
      }
    }
    if (withUnitCost) {
      final c = parseMoney(l.unitCost, allowZero: true);
      if (!c.ok && (unitCostRequired || c.error != NumError.empty)) issues.add(LotIssue(LotIssueKind.cost, l.key));
    }
  }
  if (lots.isEmpty && !allowEmpty) {
    bad = true;
    issues.add(const LotIssue(LotIssueKind.qty));
  }
  final diff = (!hasTarget || line == null || line <= 0 || bad) ? null : line - sum;
  if (diff != null && diff != 0) issues.add(const LotIssue(LotIssueKind.mismatch));
  final first = issues.isEmpty ? null : issues.first;
  final field = first == null
      ? null
      : switch (first.kind) {
          LotIssueKind.lineQty => LotField.line,
          LotIssueKind.expiryMissing || LotIssueKind.expiryPast => LotField.expiry,
          LotIssueKind.cost => LotField.cost,
          _ => LotField.qty,
        };
  String? firstKey = first?.key;
  if (first != null && first.kind == LotIssueKind.mismatch && lots.isNotEmpty) firstKey = lots.last.key;
  if (first != null && first.kind == LotIssueKind.qty && first.key == null && lots.isNotEmpty) firstKey = lots.first.key;
  return LotLineState(
    lineMilli: line,
    sumMilli: sum,
    diffMilli: diff,
    issues: issues,
    firstBadKey: firstKey,
    firstBadField: field,
  );
}

/// `lots[]` for `POST /receiving/commit` and correction `replace[]` — the
/// desktop `lotsPayload` shape: `{qty, batch_number?, expiry_date?}`.
///
/// `expiry_date` is sent ONLY for expiry-tracked products (the server rejects
/// it otherwise); no per-lot `unit_cost` (the line cost is the lot cost).
List<Map<String, Object>> lotsPayload(List<LotDraft> lots, {required bool trackExpiry}) =>
    _buildLots(lots, trackExpiry);

List<Map<String, Object>> _buildLots(List<LotDraft> lots, bool trackExpiry) => [
      for (final l in lots)
        {
          'qty': milliToJson(parseQty(l.qty).value ?? 0),
          if (l.batch.trim().isNotEmpty) 'batch_number': l.batch.trim(),
          if (trackExpiry && (l.expiry ?? '').isNotEmpty) 'expiry_date': l.expiry!,
        }
    ];

/// `new_lots[]` for `POST /inventory/count`:
/// `{qty, unit_cost, batch_no?, expiry_date?}` (note: `batch_no`, not
/// `batch_number` — that is the count contract).
List<Map<String, Object>> newLotsPayload(List<LotDraft> lots, {required bool trackExpiry}) =>
    _buildNewLots(lots, trackExpiry);

List<Map<String, Object>> _buildNewLots(List<LotDraft> lots, bool trackExpiry) => [
      for (final l in lots)
        {
          'qty': milliToJson(parseQty(l.qty).value ?? 0),
          'unit_cost': centsToJson(parseMoney(l.unitCost, allowZero: true).value ?? 0),
          if (l.batch.trim().isNotEmpty) 'batch_no': l.batch.trim(),
          if (trackExpiry && (l.expiry ?? '').isNotEmpty) 'expiry_date': l.expiry!,
        }
    ];

/// Short one-line summary of rows (`"3 + 2 · 31.12.2026"`).
String lotSummary(List<LotDraft> lots) {
  final q = lots.map((l) => l.qty.isEmpty ? '0' : l.qty).join(' + ');
  final d = [for (final l in lots) if ((l.expiry ?? '').isNotEmpty) dateDisplay(l.expiry)];
  return d.isEmpty ? q : '$q · ${d.join(', ')}';
}

/// State holder of a [LotEditor]; the parent reads [state] / payloads and
/// calls [validate] before submitting.
class LotEditorController extends ChangeNotifier {
  /// Creates a controller. Without [rows] one empty row is created that
  /// FOLLOWS [targetMilli] until the operator edits the rows (desktop `lotsAuto`).
  LotEditorController({
    List<LotDraft>? rows,
    required bool trackExpiry,
    String? businessDate,
    int? targetMilli,
    this.hasTarget = true,
    this.withUnitCost = false,
    this.unitCostRequired = true,
    this.allowEmpty = false,
  })  : _trackExpiry = trackExpiry,
        _businessDate = businessDate,
        _target = targetMilli,
        _rows = rows == null ? [] : [for (final r in rows) r.copy()] {
    if (_rows.isEmpty && !allowEmpty) {
      _rows.add(LotDraft(qty: hasTarget && (targetMilli ?? 0) > 0 ? milliToInput(targetMilli!) : ''));
      _auto = hasTarget;
    }
  }

  final List<LotDraft> _rows;
  bool _trackExpiry;
  String? _businessDate;
  int? _target;
  bool _auto = false;
  bool _showAll = false;
  final Map<String, FocusNode> _focus = {};

  /// Whether a target quantity exists (false for count `new_lots`).
  final bool hasTarget;

  /// Rows carry a unit cost (count `new_lots`).
  final bool withUnitCost;

  /// Unit cost must be typed (0 allowed).
  final bool unitCostRequired;

  /// Zero rows is valid.
  final bool allowEmpty;

  /// Current rows (read-only view).
  List<LotDraft> get rows => List.unmodifiable(_rows);

  /// Product tracks expiry.
  bool get trackExpiry => _trackExpiry;
  set trackExpiry(bool v) {
    if (v == _trackExpiry) return;
    _trackExpiry = v;
    notifyListeners();
  }

  /// Branch business date (`YYYY-MM-DD`), null = unknown.
  String? get businessDate => _businessDate;
  set businessDate(String? v) {
    if (v == _businessDate) return;
    _businessDate = v;
    notifyListeners();
  }

  /// Target quantity in milli. While the single row is still automatic its
  /// quantity follows the target.
  int? get targetMilli => _target;
  set targetMilli(int? v) {
    if (v == _target) return;
    _target = v;
    if (_auto && _rows.length == 1) _rows.first.qty = (v == null || v <= 0) ? '' : milliToInput(v);
    notifyListeners();
  }

  /// True while the single row follows the target automatically.
  bool get autoFollowing => _auto && _rows.length == 1;

  /// True after [validate]: "missing" errors are shown too.
  bool get showAllErrors => _showAll;

  /// Current validation state.
  LotLineState get state => lotLineState(
        targetMilli: _target,
        lots: _rows,
        trackExpiry: _trackExpiry,
        businessDate: _businessDate,
        hasTarget: hasTarget,
        withUnitCost: withUnitCost,
        unitCostRequired: unitCostRequired,
        allowEmpty: allowEmpty,
      );

  /// True when a row can be added.
  bool get canAdd => _rows.length < kMaxLots;

  /// Adds an empty row.
  void add() {
    if (!canAdd) return;
    _auto = false;
    _rows.add(LotDraft());
    notifyListeners();
  }

  /// Removes the row [key] (keeps at least one unless [allowEmpty]).
  void remove(String key) {
    if (_rows.length <= 1 && !allowEmpty) return;
    _auto = false;
    _rows.removeWhere((r) => r.key == key);
    _focus.remove(key)?.dispose();
    for (final f in LotField.values) {
      _focus.remove('$key/${f.name}')?.dispose();
    }
    notifyListeners();
  }

  /// Edits row [key]. Any manual edit stops the automatic target following.
  void update(String key, {String? qty, String? expiry, bool clearExpiry = false, String? batch, String? unitCost}) {
    final i = _rows.indexWhere((r) => r.key == key);
    if (i < 0) return;
    final r = _rows[i];
    if (qty != null && qty != r.qty) {
      r.qty = qty;
      _auto = false;
    }
    if (clearExpiry) r.expiry = null;
    if (expiry != null) r.expiry = expiry;
    if (batch != null) r.batch = batch;
    if (unitCost != null) r.unitCost = unitCost;
    notifyListeners();
  }

  /// Quantity still missing to reach the target, counting only the rows that
  /// already hold a valid quantity (empty rows are ignored); null when there
  /// is nothing to fill or a typed quantity is invalid.
  int? get fillableMilli {
    final t = _target;
    if (!hasTarget || t == null || t <= 0 || _rows.isEmpty) return null;
    var sum = 0;
    for (final r in _rows) {
      if (r.qty.trim().isEmpty) continue;
      final p = parseQty(r.qty);
      if (!p.ok) return null;
      sum += p.value!;
    }
    final d = t - sum;
    return d > 0 ? d : null;
  }

  /// Puts the missing quantity on the LAST row (an operator action, never automatic).
  void fillRemaining() {
    final d = fillableMilli;
    if (d == null) return;
    final last = _rows.last;
    final next = (parseQty(last.qty).value ?? 0) + d;
    if (next <= 0) return;
    _auto = false;
    last.qty = milliToInput(next);
    notifyListeners();
  }

  /// `lots[]` payload (receiving / correction replace).
  List<Map<String, Object>> lotsPayload() => _buildLots(_rows, _trackExpiry);

  /// `new_lots[]` payload (stock count).
  List<Map<String, Object>> newLotsPayload() => _buildNewLots(_rows, _trackExpiry);

  /// Focus node of a row field (created on demand, owned by the controller).
  FocusNode focusNode(String key, LotField field) =>
      _focus.putIfAbsent('$key/${field.name}', () => FocusNode(debugLabel: 'lot $key ${field.name}'));

  /// Reveals all errors, focuses the first bad field and returns `state.ok`.
  /// A line-level issue ([LotField.line]) is left to the parent to focus.
  bool validate() {
    _showAll = true;
    final st = state;
    notifyListeners();
    if (st.ok) return true;
    final key = st.firstBadKey;
    final field = st.firstBadField;
    if (key != null && field != null && field != LotField.line) {
      final node = focusNode(key, field);
      node.requestFocus();
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final ctx = node.context;
        if (ctx != null && ctx.mounted) {
          Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 200), alignment: 0.3);
        }
      });
    }
    return false;
  }

  @override
  void dispose() {
    for (final f in _focus.values) {
      f.dispose();
    }
    _focus.clear();
    super.dispose();
  }
}

/// The editor UI: one card per row (quantity, expiry, batch number, optional
/// unit cost), a running Σ with remaining/excess, "add row" and "fill the
/// remainder" buttons. Row errors are inline; missing-value errors appear
/// after [LotEditorController.validate].
class LotEditor extends StatefulWidget {
  /// Creates the editor.
  const LotEditor({super.key, required this.controller, this.unit, this.title, this.enabled = true});

  /// State holder.
  final LotEditorController controller;

  /// Unit label (`kg`, `dona`).
  final String? unit;

  /// Heading (default "Partiyalar").
  final String? title;

  /// Editable.
  final bool enabled;

  @override
  State<LotEditor> createState() => _LotEditorState();
}

class _LotEditorState extends State<LotEditor> {
  final Map<String, TextEditingController> _qty = {}, _batch = {}, _cost = {};

  LotEditorController get c => widget.controller;

  @override
  void initState() {
    super.initState();
    c.addListener(_changed);
  }

  @override
  void didUpdateWidget(covariant LotEditor old) {
    super.didUpdateWidget(old);
    if (old.controller != widget.controller) {
      old.controller.removeListener(_changed);
      widget.controller.addListener(_changed);
    }
  }

  @override
  void dispose() {
    c.removeListener(_changed);
    for (final m in [_qty, _batch, _cost]) {
      for (final t in m.values) {
        t.dispose();
      }
    }
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  TextEditingController _sync(Map<String, TextEditingController> m, String key, String text) {
    final t = m.putIfAbsent(key, () => TextEditingController(text: text));
    if (t.text != text) t.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
    return t;
  }

  @override
  Widget build(BuildContext context) {
    final st = c.state;
    final rows = c.rows;
    final live = {for (final r in rows) r.key};
    for (final m in [_qty, _batch, _cost]) {
      m.removeWhere((k, t) {
        if (live.contains(k)) return false;
        t.dispose();
        return true;
      });
    }
    final unit = widget.unit ?? '';
    final showAll = c.showAllErrors;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: AppColors.accentBorder),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(Icons.inventory_2_outlined, size: 18, color: AppColors.accentStrong),
          const SizedBox(width: 8),
          Expanded(
            child: Text(widget.title ?? tr('Partiyalar'),
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
          ),
        ]),
        const SizedBox(height: 6),
        _sumLine(st, unit, showAll),
        for (var i = 0; i < rows.length; i++) _row(i, rows[i], st, unit, showAll),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(
            child: SizedBox(
              height: kMinTouch,
              child: OutlinedButton.icon(
                key: const Key('lot-add'),
                onPressed: widget.enabled && c.canAdd ? c.add : null,
                icon: const Icon(Icons.add),
                label: Text(tr('Partiya qo‘shish')),
              ),
            ),
          ),
          if (c.fillableMilli != null && widget.enabled) ...[
            const SizedBox(width: 8),
            Expanded(
              child: SizedBox(
                height: kMinTouch,
                child: OutlinedButton(
                  key: const Key('lot-fill'),
                  onPressed: c.fillRemaining,
                  child: Text(tr('Qolganini qo‘shish'), maxLines: 1, overflow: TextOverflow.ellipsis),
                ),
              ),
            ),
          ],
        ]),
        if (!c.canAdd)
          _note(trArgs('Ko‘pi bilan {n} ta partiya', {'n': kMaxLots}), AppColors.muted),
        if (st.has(LotIssueKind.tooMany))
          _note(trArgs('Ko‘pi bilan {n} ta partiya', {'n': kMaxLots}), AppColors.danger),
        if (c.trackExpiry && c.businessDate != null)
          _note(trArgs('Muddat {d} yoki undan keyin bo‘lsin', {'d': dateDisplay(c.businessDate)}), AppColors.muted,
              key: const Key('lot-bizdate')),
        if (!c.trackExpiry) _note(tr('Bu mahsulotda yaroqlilik muddati kuzatilmaydi'), AppColors.muted),
      ]),
    );
  }

  Widget _note(String text, Color color, {Key? key}) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Text(text, key: key, style: TextStyle(fontSize: 12.5, color: color)),
      );

  Widget _sumLine(LotLineState st, String unit, bool showAll) {
    final String text;
    Color color = AppColors.muted;
    if (!c.hasTarget) {
      text = trArgs('Jami: {s} {u}', {'s': formatMilli(st.sumMilli), 'u': unit}).trim();
    } else {
      final target = st.lineMilli == null ? '—' : formatMilli(st.lineMilli!);
      var t = trArgs('Partiyalar: {s} / {q} {u}', {'s': formatMilli(st.sumMilli), 'q': target, 'u': unit}).trim();
      final d = st.diffMilli;
      if (d != null && d > 0) {
        t += ' · ${trArgs('yana {n} kerak', {'n': formatMilli(d)})}';
        color = AppColors.warn;
      } else if (d != null && d < 0) {
        t += ' · ${trArgs('{n} ortiqcha', {'n': formatMilli(-d)})}';
        color = AppColors.danger;
      } else if (d == 0) {
        color = AppColors.ok;
      }
      text = t;
    }
    return Semantics(
      liveRegion: true,
      child: Text(text, key: const Key('lot-sum'), style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
    );
  }

  Widget _row(int i, LotDraft r, LotLineState st, String unit, bool showAll) {
    final qp = parseQty(r.qty);
    String? qtyErr;
    if (st.has(LotIssueKind.decimals, r.key)) {
      qtyErr = qtyErrorText(NumError.tooManyDecimals);
    } else if (st.has(LotIssueKind.qty, r.key) && (showAll || r.qty.isNotEmpty)) {
      qtyErr = qtyErrorText(qp.error ?? NumError.invalid);
    }
    String? expErr;
    if (st.has(LotIssueKind.expiryPast, r.key)) {
      expErr = trArgs('Muddat {d} dan oldin bo‘lishi mumkin emas', {'d': dateDisplay(c.businessDate)});
    } else if (st.has(LotIssueKind.expiryMissing, r.key) && showAll) {
      expErr = tr('Yaroqlilik muddatini kiriting');
    }
    String? costErr;
    if (st.has(LotIssueKind.cost, r.key) && (showAll || r.unitCost.isNotEmpty)) {
      costErr = r.unitCost.isEmpty ? tr('Tannarxni kiriting (0 ham bo‘lishi mumkin)') : tr('Tannarx noto‘g‘ri');
    }
    final canRemove = widget.enabled && (c.rows.length > 1 || c.allowEmpty);
    return Container(
      key: Key('lot-row-$i'),
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.fromLTRB(10, 6, 4, 10),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
            child: Text(trArgs('{n}-partiya', {'n': i + 1}),
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.text3)),
          ),
          IconButton(
            key: Key('lot-remove-$i'),
            tooltip: trArgs('{n}-partiyani o‘chirish', {'n': i + 1}),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: canRemove ? () => c.remove(r.key) : null,
            icon: Icon(Icons.delete_outline, color: canRemove ? AppColors.danger : AppColors.faint),
          ),
        ]),
        Padding(
          padding: const EdgeInsets.only(right: 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            QtyField(
              key: Key('lot-qty-$i'),
              controller: _sync(_qty, r.key, r.qty),
              focusNode: c.focusNode(r.key, LotField.qty),
              label: tr('Miqdor'),
              unit: unit.isEmpty ? null : unit,
              enabled: widget.enabled,
              errorText: qtyErr,
              onChanged: (_) => c.update(r.key, qty: _qty[r.key]!.text),
            ),
            if (c.trackExpiry) ...[
              const SizedBox(height: 10),
              DateField(
                key: Key('lot-expiry-$i'),
                value: r.expiry,
                focusNode: c.focusNode(r.key, LotField.expiry),
                minDate: c.businessDate,
                label: '${tr('Yaroqlilik muddati')} *',
                pickerTitle: tr('Yaroqlilik muddati'),
                enabled: widget.enabled,
                errorText: expErr,
                onChanged: (v) => v == null ? c.update(r.key, clearExpiry: true) : c.update(r.key, expiry: v),
              ),
            ],
            const SizedBox(height: 10),
            TextField(
              key: Key('lot-batch-$i'),
              controller: _sync(_batch, r.key, r.batch),
              enabled: widget.enabled,
              maxLength: 64,
              textInputAction: TextInputAction.next,
              onChanged: (v) => c.update(r.key, batch: v),
              decoration: InputDecoration(
                labelText: tr('Partiya raqami (ixtiyoriy)'),
                counterText: '',
                constraints: const BoxConstraints(minHeight: kMinTouch),
              ),
            ),
            if (c.withUnitCost) ...[
              const SizedBox(height: 10),
              MoneyField(
                key: Key('lot-cost-$i'),
                controller: _sync(_cost, r.key, r.unitCost),
                focusNode: c.focusNode(r.key, LotField.cost),
                label: tr('Tannarx (birlik uchun)'),
                wholeOnly: false,
                allowZero: true,
                enabled: widget.enabled,
                errorText: costErr,
                onChanged: (_) => c.update(r.key, unitCost: _cost[r.key]!.text),
              ),
            ],
          ]),
        ),
      ]),
    );
  }
}
