import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/stock_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import '../widgets/lot_editor.dart';
import 'barcode_scan_screen.dart';
import 'inventory_screen.dart';
import 'product_detail_screen.dart' show LotCard;

/// Inventarizatsiya (stock count) of the session's CURRENT branch — Phase 4B
/// lot-aware contract:
///
/// * untracked product — the counted quantity is ABSOLUTE (the new stock);
/// * lot-tracked product — per-lot counted quantities (a BLANK lot is left
///   UNTOUCHED, never read as zero) plus lots found on the shelf that the
///   system does not know (`new_lots`, LotEditor: qty, unit cost ≥ 0, expiry
///   iff the product tracks expiry); the declared total is
///   `untouched + Σ counted + Σ new`;
/// * the lots are read from `GET /lots/products/{id}?branch_id=` and the count
///   is written with the SAME `branch_id`;
/// * items can be removed from the session; the server's per-lot result
///   (`results[].lots`: decrements / surpluses / created) is shown;
///   `duplicate` is shown explicitly.
class InventarizatsiyaScreen extends StatefulWidget {
  /// Creates the screen, optionally opening [initialProduct] right away.
  const InventarizatsiyaScreen({super.key, this.initialProduct, this.scannerBuilder});

  /// Product to count first (e.g. from the product card).
  final StockProduct? initialProduct;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<InventarizatsiyaScreen> createState() => _InventarizatsiyaScreenState();
}

const Set<String> _staleLotCodes = {'LOT_COUNT_SUM_MISMATCH', 'LOT_SELECTION_INVALID', 'LOT_INSUFFICIENT_REMAINING'};

class _InventarizatsiyaScreenState extends State<InventarizatsiyaScreen> {
  final List<CountEntry> _items = [];
  String? _branchId;
  String? _branchNotice;
  bool _opening = false;
  Object? _openError;
  PickedProduct? _openRetry;

  final _uuid = DraftUuid();
  bool _busy = false;
  Object? _submitError;
  String? _failedProductId;
  bool _failedStale = false;

  Session get _s => Session.instance;

  @override
  void initState() {
    super.initState();
    _branchId = _s.currentBranchId;
    _s.addListener(_onSession);
    final p = widget.initialProduct;
    if (p != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _add(PickedProduct(p));
      });
    }
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    final now = _s.currentBranchId;
    if (now != _branchId) {
      setState(() {
        if (_items.isNotEmpty) {
          _items.clear();
          _branchNotice = tr('Filial o‘zgardi — boshqa filial sanog‘i yuborilmaydi, ro‘yxat tozalandi.');
        }
        _branchId = now;
        _submitError = null;
        _failedProductId = null;
      });
      return;
    }
    setState(() {});
  }

  // ── Adding / editing an item ─────────────────────────────────────────────

  Future<void> _pick() async {
    final hit = await showStockProductPicker(context,
        branchId: _s.currentBranchId, title: tr('Qaysi mahsulotni sanaysiz?'), scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) await _add(hit);
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: _s.currentBranchId, scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) await _add(PickedProduct(hit.product));
  }

  Future<void> _scanContinuous() async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => BarcodeScanScreen.lookup(
        branchId: _s.currentBranchId,
        continuous: true,
        title: tr('Ketma-ket sanash'),
        scannerBuilder: widget.scannerBuilder,
        onResult: (r) async {
          final p = r.product;
          if (p != null && mounted) await _add(PickedProduct(StockProduct.fromJson(p.raw)));
        },
      ),
    ));
  }

  /// Resolves [hit] in the current branch (authoritative tracking flag, branch
  /// stock, lots) and opens the matching editor; an existing entry is edited.
  Future<void> _add(PickedProduct hit) async {
    final p = hit.product;
    final branch = _s.currentBranchId;
    final existing = _items.where((e) => e.product.id == p.id).firstOrNull;
    ProductLots? lots;
    if (Perm.allows('lots.product')) {
      setState(() {
        _opening = true;
        _openError = null;
        _openRetry = null;
      });
      try {
        lots = await StockApi.productLots(p.id, branchId: branch);
      } catch (e) {
        if (mounted) {
          setState(() {
            _opening = false;
            _openError = e;
            _openRetry = hit;
          });
        }
        return;
      }
      if (!mounted) return;
      setState(() => _opening = false);
      if (_s.currentBranchId != branch) return; // filial almashdi — eski javob ishlatilmaydi
    } else if (p.trackLots) {
      setState(() {
        _openError =
            '${tr('Partiyali mahsulotni sanash uchun partiyalarni ko‘rish ruxsati kerak.')} ${Perm.reason('lots.product')}';
        _openRetry = null;
      });
      return;
    }
    final tracked = lots?.trackLots ?? p.trackLots;
    CountEntry? entry;
    if (tracked) {
      entry = await Navigator.of(context).push<LotCountEntry>(MaterialPageRoute(
        builder: (_) => _LotCountPage(product: p, lots: lots!, initial: existing is LotCountEntry ? existing : null),
      ));
    } else {
      final system = lots?.inventoryMilli ?? p.stockMilli;
      final counted = await showAppSheet<int>(
        context,
        title: p.name,
        builder: (ctx) => _PlainCountSheet(
          product: p,
          systemMilli: system,
          initialMilli: existing is PlainCountEntry ? existing.countedMilli : null,
        ),
      );
      if (counted != null) entry = PlainCountEntry(p, systemMilli: system, countedMilli: counted);
    }
    if (entry == null || !mounted) return;
    final e = entry;
    setState(() {
      final i = _items.indexWhere((x) => x.product.id == p.id);
      if (i >= 0) {
        _items[i] = e;
      } else {
        _items.add(e);
      }
      if (_failedProductId == p.id) {
        _failedProductId = null;
        _failedStale = false;
      }
      _branchNotice = null;
      _branchId = branch;
    });
  }

  Future<void> _remove(CountEntry e) async {
    setState(() {
      _items.removeWhere((x) => x.product.id == e.product.id);
      if (_failedProductId == e.product.id) _failedProductId = null;
    });
  }

  Future<void> _clearAll() async {
    final ok = await confirmDestructive(context,
        title: tr('Sanoqni tozalash'),
        message: tr('Kiritilgan barcha sanoqlar o‘chiriladi (serverga hech narsa yuborilmagan).'),
        confirmLabel: tr('Tozalash'));
    if (ok && mounted) {
      setState(() {
        _items.clear();
        _submitError = null;
        _failedProductId = null;
      });
    }
  }

  // ── Submit ───────────────────────────────────────────────────────────────

  int get _lotLines => _items.fold(0, (a, e) => a + e.lotLines);

  String? _disabledReason() {
    if (!Perm.allows('stock.count')) return Perm.reason('stock.count');
    if (_items.isEmpty) return tr('Kamida bitta mahsulotni sanang');
    if (_lotLines > kMaxCountLotLines) {
      return trArgs('Bir sanoqda ko‘pi bilan {n} ta partiya qatori — sanoqni qismlarga bo‘lib yuboring.',
          {'n': kMaxCountLotLines});
    }
    if (_opening) return tr('Yuklanmoqda…');
    return null;
  }

  Future<void> _submit() async {
    if (_disabledReason() != null) return;
    final body = countBody(items: [for (final e in _items) e.toJson()], branchId: _branchId);
    final ok = await confirmDestructive(
      context,
      title: tr('Sanoqni yuborish'),
      message: tr('Qoldiq sanoq bo‘yicha o‘zgartiriladi. Bu amalni qaytarib bo‘lmaydi.'),
      confirmLabel: tr('Yuborish'),
      details: [
        trArgs('Filial: {name}', {'name': _s.currentBranch?.name ?? '—'}),
        for (final e in _items)
          '${e.product.name}: ${qtyUnit(e.systemMilli, e.product.unit)} → ${qtyUnit(e.totalMilli, e.product.unit)}',
      ],
    );
    if (!ok || !mounted) return;
    final uuid = _uuid.forDraft(body);
    setState(() {
      _busy = true;
      _submitError = null;
      _failedProductId = null;
      _failedStale = false;
    });
    try {
      final res = await StockApi.count(body, clientUuid: uuid);
      if (!mounted) return;
      final entries = List<CountEntry>.of(_items);
      _uuid.rotate();
      setState(() {
        _busy = false;
        _items.clear();
      });
      await Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => CountResultPage(result: res, entries: entries)));
    } catch (e) {
      if (!mounted) return;
      String? failed;
      if (e is ApiException && !e.isConnectivity) {
        for (final it in _items) {
          if (e.message.startsWith('${it.product.name}: ')) failed = it.product.id;
        }
      }
      setState(() {
        _busy = false;
        _submitError = e;
        _failedProductId = failed;
        _failedStale = e is ApiException && _staleLotCodes.contains(e.code);
      });
    }
  }

  Future<bool> _confirmLeave() async {
    if (_items.isEmpty) return true;
    return confirmDestructive(context,
        title: tr('Sanoq yuborilmagan'),
        message: tr('Kiritilgan sanoqlar serverga yuborilmagan. Chiqsangiz, ular o‘chadi.'),
        confirmLabel: tr('Chiqish'),
        cancelLabel: tr('Qolish'));
  }

  // ── UI ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final reason = _disabledReason();
    final allowed = Perm.allows('stock.count');
    return PopScope(
      canPop: _items.isEmpty,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final leave = await _confirmLeave();
        if (!leave || !mounted) return;
        // canPop yangilanishi uchun avval qayta quriladi, keyin chiqiladi.
        setState(() => _items.clear());
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) Navigator.of(context).pop();
        });
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(tr('Inventarizatsiya')),
          actions: [
            if (_items.isNotEmpty)
              IconButton(
                key: const Key('cnt-clear'),
                tooltip: tr('Sanoqni tozalash'),
                constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                onPressed: _busy ? null : _clearAll,
                icon: const Icon(Icons.delete_sweep_outlined),
              ),
          ],
        ),
        body: Column(children: [
          const ConnectivityBanner(),
          if (_opening) const LinearProgressIndicator(minHeight: 2),
          Expanded(
            child: ListView(
              key: const Key('cnt-list'),
              padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
              children: [
                Row(children: [
                  Text(tr('Filial'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
                  const SizedBox(width: 4),
                  Flexible(child: _items.isEmpty ? const BranchChip() : _lockedBranch()),
                ]),
                if (!allowed)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: ErrorBanner(
                        key: const Key('cnt-denied'),
                        message: Perm.reason('stock.count'),
                        severity: BannerSeverity.warning),
                  ),
                if (_branchNotice != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: ErrorBanner(
                      key: const Key('cnt-branch-notice'),
                      message: _branchNotice!,
                      severity: BannerSeverity.info,
                      onDismiss: () => setState(() => _branchNotice = null),
                    ),
                  ),
                const SizedBox(height: 8),
                Text(
                  tr('Mahsulotni qidiring yoki skanerlang va haqiqiy qoldiqni kiriting. Partiyali mahsulotda har partiya alohida sanaladi.'),
                  style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  Expanded(
                    child: SizedBox(
                      height: kMinTouch,
                      child: OutlinedButton.icon(
                        key: const Key('cnt-add'),
                        onPressed: _busy || _opening || !allowed ? null : _pick,
                        icon: const Icon(Icons.search),
                        label: Text(tr('Qidirish')),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: SizedBox(
                      height: kMinTouch,
                      child: OutlinedButton.icon(
                        key: const Key('cnt-scan'),
                        onPressed: _busy || _opening || !allowed ? null : _scan,
                        icon: const Icon(Icons.qr_code_scanner),
                        label: Text(tr('Skanerlash')),
                      ),
                    ),
                  ),
                ]),
                const SizedBox(height: 6),
                SizedBox(
                  height: kMinTouch,
                  child: TextButton.icon(
                    key: const Key('cnt-scan-continuous'),
                    onPressed: _busy || _opening || !allowed ? null : _scanContinuous,
                    icon: const Icon(Icons.repeat),
                    label: Text(tr('Ketma-ket skanerlab sanash')),
                  ),
                ),
                if (_openError != null) ...[
                  const SizedBox(height: 8),
                  ErrorBanner(
                    key: const Key('cnt-open-error'),
                    error: _openError is String ? null : _openError,
                    message: _openError is String ? _openError as String : null,
                    severity: _openError is String ? BannerSeverity.warning : BannerSeverity.error,
                    onRetry: _openRetry == null ? null : () => _add(_openRetry!),
                    onDismiss: () => setState(() => _openError = null),
                  ),
                ],
                StockSectionTitle(trArgs('Sanalgan mahsulotlar ({n})', {'n': _items.length})),
                if (_items.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    child: EmptyState(text: tr('Hali hech narsa sanalmadi'), icon: Icons.fact_check_outlined),
                  )
                else
                  for (final e in _items) _entryCard(e),
              ],
            ),
          ),
          if (_submitError != null)
            WriteErrorStrip(
              bannerKey: const Key('cnt-error'),
              error: _submitError!,
              onDismiss: () => setState(() => _submitError = null),
            ),
          StickyActionBar(
            label: _submitError != null && isConnectivityErrorForWrite(_submitError)
                ? tr('Qayta yuborish')
                : trArgs('Sanoqni yuborish · {n}', {'n': _items.length}),
            icon: Icons.check,
            busy: _busy,
            enabled: reason == null,
            disabledReason: reason,
            onPressed: _submit,
          ),
        ]),
      ),
    );
  }

  Widget _lockedBranch() => Tooltip(
        message: tr('Filialni almashtirish uchun avval sanoqni yuboring yoki tozalang'),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: kMinTouch),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.lock_outline, size: 16, color: AppColors.muted),
            const SizedBox(width: 6),
            Flexible(
              child: Text(_s.currentBranch?.name ?? '—',
                  key: const Key('cnt-branch-locked'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text2)),
            ),
          ]),
        ),
      );

  Widget _entryCard(CountEntry e) {
    final p = e.product;
    final diff = e.totalMilli - e.systemMilli;
    final failed = _failedProductId == p.id;
    final diffCol = diff == 0 ? AppColors.muted : (diff > 0 ? AppColors.ok : AppColors.danger);
    return Container(
      key: Key('cnt-item-${p.id}'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
      decoration: BoxDecoration(
        color: failed ? AppColors.dangerSoft : AppColors.card,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: failed ? AppColors.danger : AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p.name, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text(
                trArgs('Tizim: {a} → Sanoq: {b}',
                    {'a': qtyUnit(e.systemMilli, p.unit), 'b': qtyUnit(e.totalMilli, p.unit)}),
                style: TextStyle(fontSize: 13, color: AppColors.text2),
              ),
              Text(
                diff == 0
                    ? tr('Farq yo‘q')
                    : '${diff > 0 ? '+' : '−'}${formatMilli(diff.abs(), group: true)} ${p.unit}',
                key: Key('cnt-diff-${p.id}'),
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: diffCol),
              ),
              if (e is LotCountEntry)
                Text(
                  trArgs('{c} ta partiya sanaldi · {u} tegilmagan · {n} ta yangi partiya',
                      {'c': e.counted.length, 'u': formatMilli(e.untouchedMilli), 'n': e.newLotsPayload.length}),
                  style: TextStyle(fontSize: 12, color: AppColors.muted),
                ),
            ]),
          ),
          IconButton(
            key: Key('cnt-edit-${p.id}'),
            tooltip: tr('Tahrirlash'),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: _busy || _opening ? null : () => _add(PickedProduct(p)),
            icon: Icon(Icons.edit_outlined, color: AppColors.accentStrong),
          ),
          IconButton(
            key: Key('cnt-remove-${p.id}'),
            tooltip: tr('Ro‘yxatdan olib tashlash'),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: _busy ? null : () => _remove(e),
            icon: const Icon(Icons.close, color: AppColors.danger),
          ),
        ]),
        if (failed)
          Padding(
            padding: const EdgeInsets.only(top: 6, right: 8),
            child: Text(
              _failedStale
                  ? tr(
                      'Server bu mahsulotni rad etdi: partiyalar o‘zgargan bo‘lishi mumkin. «Tahrirlash» bilan qayta oching yoki ro‘yxatdan olib tashlang.')
                  : tr('Server bu mahsulotni rad etdi — tuzating yoki ro‘yxatdan olib tashlang.'),
              key: Key('cnt-failed-${p.id}'),
              style: const TextStyle(fontSize: 12.5, color: AppColors.danger),
            ),
          ),
      ]),
    );
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  Count entries (pure — the request shape is unit tested)
// ══════════════════════════════════════════════════════════════════════════

/// One product in the count session.
abstract class CountEntry {
  /// Creates an entry.
  CountEntry(this.product);

  /// Product.
  final StockProduct product;

  /// System stock in the branch when it was counted (milli).
  int get systemMilli;

  /// Declared counted total (milli).
  int get totalMilli;

  /// Lot lines this entry adds to the request.
  int get lotLines => 0;

  /// `items[]` element of `POST /inventory/count`.
  Map<String, Object?> toJson();
}

/// Untracked product: the count is the absolute new stock.
class PlainCountEntry extends CountEntry {
  /// Creates the entry.
  PlainCountEntry(super.product, {required int systemMilli, required this.countedMilli}) : _system = systemMilli;

  final int _system;

  /// Counted quantity (milli).
  final int countedMilli;

  @override
  int get systemMilli => _system;

  @override
  int get totalMilli => countedMilli;

  @override
  Map<String, Object?> toJson() => {'product_id': product.id, 'counted': milliToJson(countedMilli)};
}

/// Lot-tracked product: counted lots + declared new lots.
class LotCountEntry extends CountEntry {
  /// Creates the entry.
  LotCountEntry(
    super.product, {
    required this.lots,
    required this.counted,
    this.newLots = const [],
    this.newLotsPayload = const [],
    this.newMilli = 0,
    this.newReason = '',
  });

  /// The lots the counts refer to (same branch as the write).
  final ProductLots lots;

  /// Lot id -> counted quantity (milli). Lots not in the map are UNTOUCHED.
  final Map<String, int> counted;

  /// New-lot drafts (to re-open the editor).
  final List<LotDraft> newLots;

  /// `new_lots[]` payload.
  final List<Map<String, Object>> newLotsPayload;

  /// Σ new lots (milli).
  final int newMilli;

  /// Why the new lots were found (optional, sent as `reason`).
  final String newReason;

  /// Σ remaining of the lots that were NOT counted (the server leaves them as is).
  int get untouchedMilli => sumMilli([
        for (final l in lots.usableLots)
          if (!counted.containsKey(l.id)) l.remainingMilli
      ]);

  /// Σ counted lots (milli).
  int get countedMilli => sumMilli(counted.values);

  @override
  int get systemMilli => lots.inventoryMilli;

  @override
  int get totalMilli => untouchedMilli + countedMilli + newMilli;

  @override
  int get lotLines => counted.length + newLotsPayload.length;

  @override
  Map<String, Object?> toJson() => {
        'product_id': product.id,
        'counted': milliToJson(totalMilli),
        'lots': [
          for (final e in counted.entries) {'stock_batch_id': e.key, 'counted': milliToJson(e.value)}
        ],
        'new_lots': [
          for (final n in newLotsPayload) {...n, if (newReason.trim().isNotEmpty) 'reason': newReason.trim()}
        ],
      };
}

// ══════════════════════════════════════════════════════════════════════════
//  Editors
// ══════════════════════════════════════════════════════════════════════════

class _PlainCountSheet extends StatefulWidget {
  const _PlainCountSheet({required this.product, required this.systemMilli, this.initialMilli});
  final StockProduct product;
  final int systemMilli;
  final int? initialMilli;

  @override
  State<_PlainCountSheet> createState() => _PlainCountSheetState();
}

class _PlainCountSheetState extends State<_PlainCountSheet> {
  late final TextEditingController _c =
      TextEditingController(text: widget.initialMilli == null ? '' : milliToInput(widget.initialMilli!));
  bool _tried = false;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  void _save() {
    final r = parseQty(_c.text, allowZero: true);
    if (!r.ok) {
      setState(() => _tried = true);
      return;
    }
    Navigator.of(context).pop(r.value);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final r = parseQty(_c.text, allowZero: true);
    final diff = r.ok ? r.value! - widget.systemMilli : null;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(trArgs('Tizimdagi qoldiq: {q}', {'q': qtyUnit(widget.systemMilli, p.unit)}),
          key: const Key('cnt-plain-system'), style: TextStyle(fontSize: 14, color: AppColors.text2)),
      const SizedBox(height: 12),
      QtyField(
        key: const Key('cnt-plain-qty'),
        controller: _c,
        autofocus: true,
        allowZero: true,
        label: tr('Haqiqiy qoldiq (sanoq)'),
        unit: p.unit,
        textInputAction: TextInputAction.done,
        onSubmitted: (_) => _save(),
        errorText: (_tried || _c.text.isNotEmpty) && !r.ok ? qtyErrorText(r.error!) : null,
        onChanged: (_) => setState(() {}),
      ),
      const SizedBox(height: 8),
      Text(
        diff == null
            ? ' '
            : diff == 0
                ? tr('Farq yo‘q')
                : trArgs('Farq: {d}', {'d': '${diff > 0 ? '+' : '−'}${qtyUnit(diff.abs(), p.unit)}'}),
        key: const Key('cnt-plain-diff'),
        style: TextStyle(
            fontWeight: FontWeight.w700,
            color: diff == null || diff == 0 ? AppColors.muted : (diff > 0 ? AppColors.ok : AppColors.danger)),
      ),
      const SizedBox(height: 16),
      SizedBox(
        height: kPrimaryButtonHeight,
        child: ElevatedButton(
          key: const Key('cnt-plain-save'),
          onPressed: _save,
          child: Text(tr('Sanoqqa qo‘shish')),
        ),
      ),
    ]);
  }
}

/// Lot-level count of one tracked product.
class _LotCountPage extends StatefulWidget {
  const _LotCountPage({required this.product, required this.lots, this.initial});
  final StockProduct product;
  final ProductLots lots;
  final LotCountEntry? initial;

  @override
  State<_LotCountPage> createState() => _LotCountPageState();
}

class _LotCountPageState extends State<_LotCountPage> {
  final Map<String, TextEditingController> _c = {};
  late final LotEditorController _newCtl;
  late final TextEditingController _reason = TextEditingController(text: widget.initial?.newReason ?? '');
  String? _error;

  @override
  void initState() {
    super.initState();
    final init = widget.initial;
    for (final l in widget.lots.usableLots) {
      final v = init?.counted[l.id];
      _c[l.id] = TextEditingController(text: v == null ? '' : milliToInput(v));
    }
    _newCtl = LotEditorController(
      rows: init?.newLots,
      trackExpiry: widget.lots.trackExpiry,
      // Sanoqda topilgan qadoq muddati o'tgan bo'lishi MUMKIN (server rad etmaydi):
      // biznes sanasi bo'yicha "o'tgan sana" tekshiruvi bu yerda yo'q.
      businessDate: null,
      hasTarget: false,
      withUnitCost: true,
      unitCostRequired: true,
      allowEmpty: true,
    )..addListener(_changed);
  }

  @override
  void dispose() {
    _newCtl
      ..removeListener(_changed)
      ..dispose();
    for (final c in _c.values) {
      c.dispose();
    }
    _reason.dispose();
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  ({Map<String, int> counted, Map<String, String> errors}) _counted() {
    final counted = <String, int>{};
    final errors = <String, String>{};
    for (final l in widget.lots.usableLots) {
      final t = _c[l.id]!.text;
      if (t.trim().isEmpty) continue; // bo'sh = TEGILMAYDI (nol emas)
      final r = parseQty(t, allowZero: true);
      if (r.ok) {
        counted[l.id] = r.value!;
      } else {
        errors[l.id] = qtyErrorText(r.error!);
      }
    }
    return (counted: counted, errors: errors);
  }

  void _save() {
    final c = _counted();
    final newOk = _newCtl.rows.isEmpty || _newCtl.validate();
    if (c.errors.isNotEmpty || !newOk) {
      setState(() => _error = tr('Xatolarni tuzating'));
      return;
    }
    if (c.counted.isEmpty && _newCtl.rows.isEmpty) {
      setState(() => _error = tr('Kamida bitta partiyani sanang yoki topilgan yangi partiyani qo‘shing.'));
      return;
    }
    if (c.counted.length > kMaxLotsPerItem || _newCtl.rows.length > kMaxNewLotsPerItem) {
      setState(() => _error = trArgs('Bir mahsulotda ko‘pi bilan {n} ta partiya', {'n': kMaxLotsPerItem}));
      return;
    }
    Navigator.of(context).pop(LotCountEntry(
      widget.product,
      lots: widget.lots,
      counted: c.counted,
      newLots: [for (final r in _newCtl.rows) r.copy()],
      newLotsPayload: _newCtl.newLotsPayload(),
      newMilli: _newCtl.state.sumMilli,
      newReason: _reason.text,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final lots = widget.lots;
    final c = _counted();
    final untouched = sumMilli([
      for (final l in lots.usableLots)
        if (!c.counted.containsKey(l.id)) l.remainingMilli
    ]);
    final countedSum = sumMilli(c.counted.values);
    final newSum = _newCtl.state.sumMilli;
    final total = untouched + countedSum + newSum;
    final usable = lots.usableLots;
    return Scaffold(
      appBar: AppBar(title: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: Column(children: [
        Expanded(
          child: ListView(
            key: const Key('lotcnt-list'),
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
            children: [
              Wrap(spacing: 12, runSpacing: 4, children: [
                Text(trArgs('Tizimdagi qoldiq: {q}', {'q': qtyUnit(lots.inventoryMilli, p.unit)}),
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                if (lots.businessDate != null)
                  Text(trArgs('Ish kuni: {d}', {'d': dateDisplay(lots.businessDate)}),
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
              ]),
              if (lots.shortfallMilli > 0) ...[
                const SizedBox(height: 8),
                ErrorBanner(
                  severity: BannerSeverity.warning,
                  message: trArgs('Partiyasiz sotilgan {q} hali partiyaga bog‘lanmagan — sanoq bu qarzni yopmaydi.',
                      {'q': qtyUnit(lots.shortfallMilli, p.unit)}),
                ),
              ],
              const SizedBox(height: 8),
              Text(
                tr('Har partiyada javonda nechta borligini kiriting. Bo‘sh qoldirilgan partiya O‘ZGARMAYDI (nol deb hisoblanmaydi). Partiyani nolga tushirish uchun 0 yozing.'),
                style: TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.35),
              ),
              StockSectionTitle(trArgs('Tizimdagi partiyalar ({n})', {'n': usable.length})),
              if (usable.isEmpty)
                Text(tr('Bu filialda ochiq partiya yo‘q'), style: TextStyle(color: AppColors.muted))
              else
                for (final l in usable) _lotRow(l, c),
              StockSectionTitle(tr('Javonda topilgan yangi partiyalar')),
              Text(
                tr('Tizimda yo‘q partiya topilsa (boshqa muddat yoki qadoq), uni shu yerda e’lon qiling — mavjud partiyaga qo‘shilmaydi. Tannarxni siz kiritasiz.'),
                style: TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.35),
              ),
              const SizedBox(height: 8),
              LotEditor(
                key: const Key('lotcnt-new'),
                controller: _newCtl,
                unit: p.unit,
                title: tr('Yangi partiyalar'),
              ),
              if (_newCtl.rows.isNotEmpty) ...[
                const SizedBox(height: 10),
                TextField(
                  key: const Key('lotcnt-reason'),
                  controller: _reason,
                  maxLength: 150,
                  decoration: InputDecoration(
                    labelText: tr('Qayerdan topildi? (ixtiyoriy)'),
                    constraints: const BoxConstraints(minHeight: kMinTouch),
                  ),
                ),
              ],
            ],
          ),
        ),
        // Xato doim ko'rinadigan joyda — uzun ro'yxat oxirida yashirinmaydi.
        if (_error != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: ErrorBanner(
                key: const Key('lotcnt-error'), message: _error!, onDismiss: () => setState(() => _error = null)),
          ),
        StickyActionBar(
          label: tr('Sanoqqa qo‘shish'),
          icon: Icons.check,
          onPressed: _save,
          summary: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(trArgs('Jami sanoq: {q}', {'q': qtyUnit(total, p.unit)}),
                key: const Key('lotcnt-total'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
            Text(
              trArgs('tegilmagan {u} + sanalgan {c} + yangi {n}',
                  {'u': formatMilli(untouched), 'c': formatMilli(countedSum), 'n': formatMilli(newSum)}),
              key: const Key('lotcnt-breakdown'),
              style: TextStyle(fontSize: 12.5, color: AppColors.muted),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _lotRow(LotRow l, ({Map<String, int> counted, Map<String, String> errors}) c) {
    final v = c.counted[l.id];
    final diff = v == null ? null : v - l.remainingMilli;
    return LotCard(
      lot: l,
      unit: widget.product.unit,
      businessDate: widget.lots.businessDate,
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: QtyField(
            key: Key('lotcnt-qty-${l.id}'),
            controller: _c[l.id]!,
            allowZero: true,
            label: tr('Sanoq'),
            hint: tr('Sanalmadi'),
            unit: widget.product.unit,
            errorText: c.errors[l.id],
            onChanged: (_) => setState(() => _error = null),
          ),
        ),
        const SizedBox(width: 10),
        SizedBox(
          width: 88,
          child: Padding(
            padding: const EdgeInsets.only(top: 14),
            child: Text(
              diff == null ? tr('tegilmaydi') : (diff == 0 ? '0' : '${diff > 0 ? '+' : '−'}${formatMilli(diff.abs())}'),
              key: Key('lotcnt-diff-${l.id}'),
              textAlign: TextAlign.right,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: diff == null
                    ? AppColors.faint
                    : (diff == 0 ? AppColors.muted : (diff > 0 ? AppColors.ok : AppColors.danger)),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  Result
// ══════════════════════════════════════════════════════════════════════════

/// What the server did: per product old → counted, and per lot what was
/// reduced, found in surplus and created. `duplicate` is explicit.
class CountResultPage extends StatelessWidget {
  /// Creates the page.
  const CountResultPage({super.key, required this.result, required this.entries});

  /// Server reply.
  final CountResult result;

  /// The entries that were sent (lot labels, units).
  final List<CountEntry> entries;

  @override
  Widget build(BuildContext context) {
    final byId = {for (final e in entries) e.product.id: e};
    return Scaffold(
      appBar: AppBar(title: Text(result.duplicate ? tr('Sanoq avval saqlangan') : tr('Sanoq saqlandi ✓'))),
      body: Column(children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
            children: [
              if (result.duplicate)
                ErrorBanner(
                  key: const Key('cnt-duplicate'),
                  severity: BannerSeverity.warning,
                  message: tr(
                      'Server bu sanoqni avval qabul qilgan — qoldiq QAYTA yozilmadi. Natijani mahsulot kartasida tekshiring.'),
                )
              else
                Text(trArgs('{n} ta mahsulotda o‘zgarish yozildi', {'n': result.changed}),
                    key: const Key('cnt-changed'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              for (final r in result.results) _row(r, byId[r.productId]),
            ],
          ),
        ),
        StickyActionBar(
          label: tr('Tayyor'),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ]),
    );
  }

  Widget _row(CountResultRow r, CountEntry? e) {
    final unit = e?.product.unit ?? '';
    final lotById = e is LotCountEntry ? {for (final l in e.lots.lots) l.id: l} : const <String, LotRow>{};
    String label(String id) => lotById[id] == null ? tr('Partiya') : lotLabel(lotById[id]!);
    final col = r.diffMilli == 0 ? AppColors.muted : (r.diffMilli > 0 ? AppColors.ok : AppColors.danger);
    return Container(
      key: Key('cnt-result-${r.productId}'),
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(r.product, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(
          '${qtyUnit(r.oldMilli, unit)} → ${qtyUnit(r.countedMilli, unit)}'
          '  (${r.diffMilli > 0 ? '+' : (r.diffMilli < 0 ? '−' : '')}${formatMilli(r.diffMilli.abs())})',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: col),
        ),
        if (r.decrements.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(tr('Kamaygan partiyalar'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          for (final d in r.decrements)
            Text('${label(d.lotId)}: −${formatMilli(d.qtyMilli)}',
                key: Key('cnt-dec-${d.lotId}'), style: const TextStyle(fontSize: 13, color: AppColors.danger)),
        ],
        if (r.surpluses.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(tr('Ortiqcha topilgan (alohida partiya bo‘lib yozildi)'),
              style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          for (final s in r.surpluses)
            Text('${label(s.lotId)}: +${formatMilli(s.qtyMilli)}',
                key: Key('cnt-sur-${s.lotId}'), style: const TextStyle(fontSize: 13, color: AppColors.ok)),
        ],
        if (r.created.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(tr('Yaratilgan partiyalar'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          for (final c in r.created)
            Text(
              [
                c.batchNo ?? tr('Raqamsiz partiya'),
                if (c.expiryDate != null) dateDisplay(c.expiryDate),
                '+${formatMilli(c.qtyMilli)} $unit'.trim(),
                if (c.unitCostCents != null) formatCents(c.unitCostCents!),
              ].join(' · '),
              key: Key('cnt-created-${c.lotId}'),
              style: TextStyle(fontSize: 13, color: AppColors.text2),
            ),
        ],
      ]),
    );
  }
}
