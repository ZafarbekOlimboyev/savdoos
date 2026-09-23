import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/stock_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'barcode_scan_screen.dart';
import 'inventory_screen.dart';
import 'product_detail_screen.dart' show LotCard;

/// Hisobdan chiqarish (write-off) from the session's CURRENT branch.
///
/// * untracked product — one quantity (≤ branch stock, 3 decimals);
/// * lot-tracked product — quantity PER LOT from `GET /lots/products/{id}?branch_id=`
///   (open lots, FEFO order, expired lots visible and highlighted), each ≤ its
///   remaining; the write sends `qty = Σ lots` and the SAME `branch_id` the lots
///   were read from. The system never guesses the lot (desktop `Hisobdan`);
/// * reason `expired|damaged|lost|other[: note]` (desktop codes);
/// * success only after a 2xx; a network failure keeps the same `client_uuid`
///   for the retry; `duplicate` is shown as "already saved earlier".
///
/// ⚠️  No cash effect: a write-off is a stock loss, not a money operation.
class WriteoffScreen extends StatefulWidget {
  /// Creates the screen, optionally pre-selecting [initialProduct] (and
  /// highlighting [initialLotId]).
  const WriteoffScreen({super.key, this.initialProduct, this.initialLotId, this.scannerBuilder});

  /// Product to start with (e.g. from the product card).
  final StockProduct? initialProduct;

  /// Lot to highlight (e.g. from an expiry notification).
  final String? initialLotId;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<WriteoffScreen> createState() => _WriteoffScreenState();
}

const Set<String> _reloadCodes = {
  'LOT_LINES_REQUIRED',
  'LOT_LINES_FORBIDDEN',
  'LOT_SELECTION_INVALID',
  'LOT_INSUFFICIENT_REMAINING',
  'LOT_QTY_SUM_MISMATCH',
};

class _WriteoffScreenState extends State<WriteoffScreen> {
  StockProduct? _product;
  String? _branchId; // branch the product/lots were loaded for (sent with the write)
  bool _resolving = false;
  Object? _resolveError;
  ProductLots? _lots;
  bool _tracked = false;
  int _stockMilli = 0;
  int _resolveSeq = 0;
  String? _branchNotice;

  final _qty = TextEditingController();
  final Map<String, TextEditingController> _lotQty = {};
  String _reason = 'expired';
  final _note = TextEditingController();
  bool _showErrors = false;

  final _uuid = DraftUuid();
  bool _busy = false;
  Object? _submitError;

  Session get _s => Session.instance;

  @override
  void initState() {
    super.initState();
    _s.addListener(_onSession);
    final p = widget.initialProduct;
    if (p != null) _resolve(p);
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    _qty.dispose();
    _note.dispose();
    for (final c in _lotQty.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    if (_product != null && _s.currentBranchId != _branchId) {
      // Boshqa filial — eski filial qoldig'i/partiyalari bilan yozib bo'lmaydi.
      setState(() {
        _product = null;
        _lots = null;
        _clearInputs();
        _submitError = null;
        _branchNotice = tr('Filial almashtirildi — mahsulotni qayta tanlang.');
      });
      return;
    }
    setState(() {});
  }

  void _clearInputs() {
    _qty.clear();
    for (final c in _lotQty.values) {
      c.clear();
    }
    _note.clear();
    _showErrors = false;
  }

  /// Loads the AUTHORITATIVE tracking flag, branch stock and lots of [p] in
  /// the current branch. Keeps typed lot quantities of lots that still exist.
  Future<void> _resolve(StockProduct p, {int? scaleMilli, bool keepInputs = false}) async {
    final seq = ++_resolveSeq;
    final branch = _s.currentBranchId;
    final canLots = Perm.allows('lots.product');
    setState(() {
      if (!keepInputs || _product?.id != p.id) {
        _clearInputs();
        _lotQty.clear();
      }
      _product = p;
      _branchId = branch;
      _branchNotice = null;
      _lots = null;
      _tracked = p.trackLots;
      _stockMilli = p.stockMilli;
      _resolveError = null;
      _resolving = canLots;
      if (scaleMilli != null && scaleMilli > 0 && !p.trackLots) _qty.text = milliToInput(scaleMilli);
    });
    if (!canLots) return;
    try {
      final lots = await StockApi.productLots(p.id, branchId: branch);
      if (!mounted || seq != _resolveSeq) return;
      setState(() {
        _lots = lots;
        _tracked = lots.trackLots;
        _stockMilli = lots.inventoryMilli;
        _resolving = false;
        final live = {for (final l in lots.usableLots) l.id};
        _lotQty.removeWhere((k, c) {
          if (live.contains(k)) return false;
          c.dispose();
          return true;
        });
      });
    } catch (e) {
      if (!mounted || seq != _resolveSeq) return;
      setState(() {
        _resolveError = e;
        _resolving = false;
      });
    }
  }

  Future<void> _pick() async {
    final hit = await showStockProductPicker(context,
        branchId: _s.currentBranchId, title: tr('Qaysi mahsulot?'), scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) {
      _submitError = null;
      await _resolve(hit.product, scaleMilli: hit.scaleMilli);
    }
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: _s.currentBranchId, scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) {
      _submitError = null;
      await _resolve(hit.product, scaleMilli: hit.scaleMilli);
    }
  }

  TextEditingController _lotCtl(String id) => _lotQty.putIfAbsent(id, TextEditingController.new);

  // ── Validation (UX only — the server decides) ────────────────────────────

  _WoState _state() {
    final p = _product;
    if (p == null) return const _WoState(reason: 'pick');
    if (_resolving) return const _WoState(reason: 'loading');
    if (_resolveError != null) return const _WoState(reason: 'resolve');
    if (!_tracked) {
      final r = parseQty(_qty.text);
      String? err;
      if (!r.ok) {
        err = qtyErrorText(r.error!);
      } else if (r.value! > _stockMilli) {
        err = trArgs('Qoldiqdan ko‘p (qoldiq: {q})', {'q': qtyUnit(_stockMilli, p.unit)});
      }
      return _WoState(totalMilli: r.value ?? 0, qtyError: err, reason: err == null ? null : 'qty');
    }
    final lots = _lots;
    if (lots == null) return const _WoState(reason: 'nolots');
    final picks = <LotPick>[];
    final errs = <String, String>{};
    var costMilliCents = 0;
    for (final l in lots.usableLots) {
      final t = _lotQty[l.id]?.text ?? '';
      if (t.trim().isEmpty) continue;
      final r = parseQty(t, allowZero: true);
      if (!r.ok) {
        errs[l.id] = qtyErrorText(r.error!);
      } else if (r.value! > l.remainingMilli) {
        errs[l.id] = trArgs('Partiya qoldig‘idan ko‘p ({q})', {'q': qtyUnit(l.remainingMilli, p.unit)});
      } else if (r.value! > 0) {
        picks.add(LotPick(l.id, r.value!));
        costMilliCents += r.value! * l.unitCostCents;
      }
    }
    final total = sumMilli(picks.map((x) => x.milli));
    String? reason;
    if (errs.isNotEmpty) {
      reason = 'lots';
    } else if (picks.isEmpty) {
      reason = 'nopick';
    } else if (picks.length > kMaxLotsPerItem) {
      reason = 'toomany';
    }
    return _WoState(
      totalMilli: total,
      picks: picks,
      lotErrors: errs,
      costCents: (costMilliCents + 500) ~/ 1000,
      reason: reason,
    );
  }

  String? _disabledReason(_WoState st) {
    if (!Perm.allows('stock.writeoff')) return Perm.reason('stock.writeoff');
    switch (st.reason) {
      case null:
        return null;
      case 'pick':
        return tr('Mahsulotni tanlang');
      case 'loading':
        return tr('Yuklanmoqda…');
      case 'resolve':
        return tr('Mahsulot ma’lumotini yuklab bo‘lmadi — qayta urinib ko‘ring.');
      case 'nolots':
        return '${tr('Partiyali mahsulotni chiqarish uchun partiyalarni ko‘rish ruxsati kerak.')} ${Perm.reason('lots.product')}';
      case 'nopick':
        return tr('Qaysi partiyadan qancha chiqarilishini kiriting');
      case 'toomany':
        return trArgs('Bir amalda ko‘pi bilan {n} ta partiya', {'n': kMaxLotsPerItem});
      case 'qty':
        return st.qtyError;
      default:
        return tr('Partiya miqdorlaridagi xatolarni tuzating');
    }
  }

  // ── Submit ───────────────────────────────────────────────────────────────

  Future<void> _submit() async {
    final st = _state();
    if (st.reason != null || !Perm.allows('stock.writeoff')) {
      setState(() => _showErrors = true);
      return;
    }
    final p = _product!;
    final branchName = _s.currentBranch?.name ?? '—';
    final body = writeoffBody(
      productId: p.id,
      qtyMilli: st.totalMilli,
      reason: writeoffReasonText(_reason, _note.text),
      branchId: _branchId,
      lots: _tracked ? st.picks : const [],
    );
    final lotById = {for (final l in _lots?.lots ?? const <LotRow>[]) l.id: l};
    final ok = await confirmDestructive(
      context,
      title: tr('Hisobdan chiqarishni tasdiqlang'),
      message: tr('Tovar qoldiqdan chiqariladi. Bu amalni qaytarib bo‘lmaydi.'),
      confirmLabel: tr('Hisobdan chiqarish'),
      details: [
        '${p.name} — ${qtyUnit(st.totalMilli, p.unit)}',
        trArgs('Filial: {name}', {'name': branchName}),
        trArgs('Sabab: {r}', {'r': _reasonLabel(_reason)}),
        if (_tracked)
          for (final x in st.picks)
            '${lotById[x.lotId] == null ? x.lotId : lotLabel(lotById[x.lotId]!)}: ${formatMilli(x.milli)}',
        if (_tracked && st.costCents > 0) trArgs('Tannarx: {c}', {'c': formatCents(st.costCents)}),
      ],
    );
    if (!ok || !mounted) return;
    final uuid = _uuid.forDraft(body);
    setState(() {
      _busy = true;
      _submitError = null;
    });
    try {
      final res = await StockApi.writeoff(body, clientUuid: uuid);
      if (!mounted) return;
      _uuid.rotate();
      setState(() {
        _busy = false;
        _clearInputs();
        if (!_tracked && res.newQtyMilli != null) _stockMilli = res.newQtyMilli!;
      });
      if (_tracked || res.duplicate) unawaited(_resolve(p));
      final again = await _showResult(p, st, res);
      if (!mounted) return;
      if (again != true) Navigator.of(context).maybePop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _submitError = e;
      });
      if (e is ApiException && !e.isConnectivity) {
        final code = e.code ?? '';
        if (_reloadCodes.contains(code) || e.message.startsWith("Yetarli qoldiq yo'q")) {
          unawaited(_resolve(p, keepInputs: true));
        }
      }
    }
  }

  Future<bool?> _showResult(StockProduct p, _WoState st, WriteoffResult res) => showAppSheet<bool>(
        context,
        title: res.duplicate ? tr('Bu amal avval saqlangan') : tr('Hisobdan chiqarildi ✓'),
        builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (res.duplicate)
            ErrorBanner(
              key: const Key('wo-duplicate'),
              severity: BannerSeverity.warning,
              message: tr('Server bu so‘rovni avval qabul qilgan — qoldiq QAYTA kamaytirilmadi. Qoldiqni tekshiring.'),
            )
          else ...[
            Text('${res.product ?? p.name} — ${qtyUnit(st.totalMilli, p.unit)}',
                key: const Key('wo-done'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            if (res.newQtyMilli != null) ...[
              const SizedBox(height: 6),
              Text(trArgs('Yangi qoldiq: {q}', {'q': qtyUnit(res.newQtyMilli!, p.unit)}),
                  style: TextStyle(color: AppColors.text2)),
            ],
            if (res.costTotalCents != null) ...[
              const SizedBox(height: 6),
              Text(trArgs('Hisobdan chiqarilgan tannarx: {c}', {'c': formatCents(res.costTotalCents!)}),
                  key: const Key('wo-cost'), style: TextStyle(color: AppColors.text2)),
            ],
          ],
          const SizedBox(height: 16),
          SizedBox(
            height: kPrimaryButtonHeight,
            child: ElevatedButton(
              key: const Key('wo-again'),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(tr('Yana chiqarish')),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: kMinTouch,
            child: TextButton(
              key: const Key('wo-close'),
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(tr('Tayyor')),
            ),
          ),
        ]),
      );

  String _reasonLabel(String code) => switch (code) {
        'expired' => tr('Muddati o‘tgan'),
        'damaged' => tr('Shikastlangan'),
        'lost' => tr('Yo‘qolgan'),
        _ => tr('Boshqa sabab'),
      };

  // ── UI ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final allowed = Perm.allows('stock.writeoff');
    final st = _state();
    final p = _product;
    final reason = _disabledReason(st);
    return Scaffold(
      appBar: AppBar(title: Text(tr('Hisobdan chiqarish'))),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: ListView(
            key: const Key('wo-list'),
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
            children: [
              Row(children: [
                Text(tr('Filial'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
                const SizedBox(width: 4),
                const Flexible(child: BranchChip()),
              ]),
              if (!allowed)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: ErrorBanner(
                      key: const Key('wo-denied'),
                      message: Perm.reason('stock.writeoff'),
                      severity: BannerSeverity.warning),
                ),
              if (_branchNotice != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: ErrorBanner(message: _branchNotice!, severity: BannerSeverity.info),
                ),
              StockSectionTitle(tr('Mahsulot')),
              _productBox(p),
              if (p != null) ..._details(p, st),
            ],
          ),
        ),
        if (_submitError != null)
          WriteErrorStrip(
            bannerKey: const Key('wo-error'),
            error: _submitError!,
            onDismiss: () => setState(() => _submitError = null),
          ),
        StickyActionBar(
          label: _submitError != null && isConnectivityErrorForWrite(_submitError)
              ? tr('Qayta yuborish')
              : tr('Hisobdan chiqarish'),
          icon: Icons.remove_circle_outline,
          danger: true,
          busy: _busy,
          enabled: reason == null,
          disabledReason: reason,
          onPressed: _submit,
          summary: p == null
              ? null
              : Text(
                  _tracked && st.costCents > 0
                      ? trArgs('Jami: {q} · tannarx {c}',
                          {'q': qtyUnit(st.totalMilli, p.unit), 'c': formatCents(st.costCents)})
                      : trArgs('Jami: {q}', {'q': qtyUnit(st.totalMilli, p.unit)}),
                  key: const Key('wo-summary'),
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                ),
        ),
      ]),
    );
  }

  Widget _productBox(StockProduct? p) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (p != null)
        StockProductTile(
          key: const Key('wo-product'),
          product: StockProduct(
            id: p.id,
            name: p.name,
            unit: p.unit,
            stockMilli: _stockMilli,
            minMilli: p.minMilli,
            sellCents: p.sellCents,
            trackLots: _tracked,
            trackExpiry: _lots?.trackExpiry ?? p.trackExpiry,
            isActive: p.isActive,
            isWeighted: p.isWeighted,
          ),
          showPrice: false,
          onTap: _busy ? null : _pick,
        ),
      Row(children: [
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: OutlinedButton.icon(
              key: const Key('wo-pick'),
              onPressed: _busy ? null : _pick,
              icon: const Icon(Icons.search),
              label: Text(p == null ? tr('Mahsulot tanlash') : tr('Boshqa mahsulot')),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: OutlinedButton.icon(
              key: const Key('wo-scan'),
              onPressed: _busy ? null : _scan,
              icon: const Icon(Icons.qr_code_scanner),
              label: Text(tr('Skanerlash')),
            ),
          ),
        ),
      ]),
    ]);
  }

  List<Widget> _details(StockProduct p, _WoState st) {
    return [
      if (_resolving) const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
      if (_resolveError != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: ErrorBanner(error: _resolveError, onRetry: () => _resolve(p, keepInputs: true)),
        ),
      if (!_resolving && _resolveError == null) ...(_tracked ? _lotInputs(p, st) : _qtyInput(p, st)),
      if (!_resolving && _resolveError == null) ..._reasonInputs(),
    ];
  }

  List<Widget> _qtyInput(StockProduct p, _WoState st) => [
        StockSectionTitle(tr('Miqdor')),
        QtyField(
          key: const Key('wo-qty'),
          controller: _qty,
          label: tr('Chiqariladigan miqdor'),
          unit: p.unit,
          helperText: trArgs('Filial qoldig‘i: {q}', {'q': qtyUnit(_stockMilli, p.unit)}),
          errorText: (_showErrors || _qty.text.isNotEmpty) ? st.qtyError : null,
          onChanged: (_) => setState(() {}),
        ),
      ];

  List<Widget> _lotInputs(StockProduct p, _WoState st) {
    final lots = _lots;
    if (lots == null) {
      return [
        const SizedBox(height: 10),
        ErrorBanner(
          key: const Key('wo-lots-denied'),
          severity: BannerSeverity.warning,
          message: _disabledReason(const _WoState(reason: 'nolots')) ?? '',
        ),
      ];
    }
    final usable = lots.usableLots;
    return [
      StockSectionTitle(tr('Partiyalar')),
      Text(tr('Qaysi partiyadan qancha chiqarilayotganini kiriting. Tizim partiyani o‘zi tanlamaydi.'),
          style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
      const SizedBox(height: 8),
      if (usable.isEmpty)
        EmptyState(text: tr('Bu filialda ochiq partiya yo‘q'), icon: Icons.inventory_2_outlined)
      else
        for (final l in usable)
          LotCard(
            lot: l,
            unit: p.unit,
            businessDate: lots.businessDate,
            highlight: widget.initialLotId == l.id,
            child: QtyField(
              key: Key('wo-lot-qty-${l.id}'),
              controller: _lotCtl(l.id),
              allowZero: true,
              label: tr('Chiqariladi'),
              hint: '0',
              unit: p.unit,
              errorText: st.lotErrors[l.id],
              onChanged: (_) => setState(() {}),
            ),
          ),
      if (_showErrors && st.reason == 'nopick')
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(tr('Qaysi partiyadan qancha chiqarilishini kiriting'),
              style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
        ),
    ];
  }

  List<Widget> _reasonInputs() => [
        StockSectionTitle(tr('Sabab')),
        Wrap(spacing: 8, runSpacing: 4, children: [
          for (final r in kWriteoffReasons)
            ChoiceChip(
              key: Key('wo-reason-$r'),
              label: Text(_reasonLabel(r)),
              selected: _reason == r,
              onSelected: (_) => setState(() => _reason = r),
              materialTapTargetSize: MaterialTapTargetSize.padded,
              selectedColor: AppColors.dangerSoft,
              showCheckmark: false,
              side: BorderSide(color: _reason == r ? AppColors.danger : AppColors.border),
            ),
        ]),
        const SizedBox(height: 10),
        TextField(
          key: const Key('wo-note'),
          controller: _note,
          maxLength: 150,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(
            labelText: _reason == 'other' ? tr('Izoh (nima bo‘ldi?)') : tr('Izoh (ixtiyoriy)'),
            constraints: const BoxConstraints(minHeight: kMinTouch),
          ),
        ),
        Text(tr('Hisobdan chiqarish kassaga ta’sir qilmaydi — bu pul amali emas.'),
            style: TextStyle(fontSize: 12, color: AppColors.muted)),
      ];
}

class _WoState {
  const _WoState({
    this.totalMilli = 0,
    this.picks = const [],
    this.lotErrors = const {},
    this.qtyError,
    this.costCents = 0,
    this.reason,
  });

  final int totalMilli;
  final List<LotPick> picks;
  final Map<String, String> lotErrors;
  final String? qtyError;
  final int costCents;

  /// Why submitting is not possible (null = ready).
  final String? reason;
}
