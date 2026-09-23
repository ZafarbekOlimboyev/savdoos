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

/// Filiallararo transfer from the session's CURRENT branch to another active
/// branch of the company.
///
/// ⚠️  Lot-tracked products are BLOCKED up front: the server has no lot-aware
///     transfer (`stock_gate`, 409 `TRANSFER_TRACKED_UNSUPPORTED`). They are
///     listed but cannot be chosen, and the reason is explained.
/// ⚠️  The destination is never pre-selected — the operator chooses it.
class TransferScreen extends StatefulWidget {
  /// Creates the screen.
  const TransferScreen({super.key, this.scannerBuilder});

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<TransferScreen> createState() => _TransferScreenState();
}

class _TItem {
  _TItem(this.product, this.milli);
  final StockProduct product;
  int milli;
}

/// Why [p] cannot be transferred (null = it can).
String? transferBlockedReason(StockProduct p) =>
    p.trackLots ? tr('Partiyali mahsulot — filiallararo ko‘chirib bo‘lmaydi') : null;

class _TransferScreenState extends State<TransferScreen> {
  List<CompanyBranch>? _branches;
  Object? _branchesError;
  CompanyBranch? _to;
  final List<_TItem> _items = [];
  String? _fromId;
  String? _notice;

  final _uuid = DraftUuid();
  bool _busy = false;
  Object? _submitError;

  Session get _s => Session.instance;

  @override
  void initState() {
    super.initState();
    _fromId = _s.currentBranchId;
    _s.addListener(_onSession);
    _loadBranches();
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    final now = _s.currentBranchId;
    setState(() {
      if (now != _fromId) {
        if (_items.isNotEmpty) {
          _items.clear();
          _notice = tr('Manba filial o‘zgardi — ro‘yxat tozalandi.');
        }
        _fromId = now;
        if (_to?.id == now) _to = null;
      }
    });
  }

  Future<void> _loadBranches() async {
    setState(() => _branchesError = null);
    try {
      final b = await StockApi.companyBranches();
      if (mounted) setState(() => _branches = b);
    } catch (e) {
      if (mounted) setState(() => _branchesError = e);
    }
  }

  List<CompanyBranch> get _destinations => [
        for (final b in _branches ?? const <CompanyBranch>[])
          if (b.isActive && b.id != _fromId) b
      ];

  Future<void> _pickDest() async {
    final list = _destinations;
    final picked = await showAppSheet<CompanyBranch>(
      context,
      title: tr('Qaysi filialga?'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        for (final b in list)
          InkWell(
            key: Key('tr-dest-${b.id}'),
            onTap: () => Navigator.of(ctx).pop(b),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 56),
              child: Row(children: [
                Icon(b.id == _to?.id ? Icons.radio_button_checked : Icons.radio_button_off,
                    color: b.id == _to?.id ? AppColors.accentStrong : AppColors.muted),
                const SizedBox(width: 12),
                Expanded(child: Text(b.name, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700))),
              ]),
            ),
          ),
      ]),
    );
    if (picked != null && mounted) setState(() => _to = picked);
  }

  Future<void> _add() async {
    final hit = await showStockProductPicker(context,
        branchId: _fromId,
        title: tr('Qaysi mahsulot ko‘chiriladi?'),
        blockedReason: transferBlockedReason,
        scannerBuilder: widget.scannerBuilder);
    if (hit == null || !mounted) return;
    await _editQty(hit.product);
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: _fromId, scannerBuilder: widget.scannerBuilder);
    if (hit == null || !mounted) return;
    final why = transferBlockedReason(hit.product);
    if (why != null) {
      setState(() => _notice = '${hit.product.name}: $why');
      return;
    }
    await _editQty(hit.product, initial: hit.scaleMilli);
  }

  Future<void> _editQty(StockProduct p, {int? initial}) async {
    final existing = _items.where((x) => x.product.id == p.id).firstOrNull;
    final product = existing?.product ?? p;
    final milli = await showAppSheet<int>(
      context,
      title: product.name,
      builder: (ctx) => _QtySheet(product: product, initialMilli: existing?.milli ?? initial),
    );
    if (milli == null || !mounted) return;
    setState(() {
      _notice = null;
      if (existing != null) {
        existing.milli = milli;
      } else {
        _items.add(_TItem(product, milli));
      }
    });
  }

  String? _disabledReason() {
    if (!Perm.allows('stock.transfer')) return Perm.reason('stock.transfer');
    if (_fromId == null) return tr('Manba filial aniqlanmadi');
    if (_branches != null && _destinations.isEmpty) return tr('Ko‘chirish uchun boshqa faol filial yo‘q');
    if (_to == null) return tr('Qaysi filialga ko‘chirilishini tanlang');
    if (_items.isEmpty) return tr('Kamida bitta mahsulot qo‘shing');
    return null;
  }

  Future<void> _submit() async {
    if (_disabledReason() != null) return;
    final to = _to!;
    final body = transferBody(
      fromBranchId: _fromId!,
      toBranchId: to.id,
      items: [for (final i in _items) (i.product.id, i.milli)],
    );
    final ok = await confirmDestructive(
      context,
      title: tr('Ko‘chirishni tasdiqlang'),
      message: tr('Tovar manba filial qoldig‘idan ayrilib, qabul qiluvchi filialga qo‘shiladi.'),
      confirmLabel: tr('Ko‘chirish'),
      details: [
        '${_s.currentBranch?.name ?? '—'} → ${to.name}',
        for (final i in _items) '${i.product.name}: ${qtyUnit(i.milli, i.product.unit)}',
      ],
    );
    if (!ok || !mounted) return;
    final uuid = _uuid.forDraft(body);
    setState(() {
      _busy = true;
      _submitError = null;
    });
    try {
      final res = await StockApi.transfer(body, clientUuid: uuid);
      if (!mounted) return;
      _uuid.rotate();
      setState(() {
        _busy = false;
        _items.clear();
      });
      final again = await _showResult(res);
      if (again != true && mounted) Navigator.of(context).maybePop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _submitError = e;
      });
    }
  }

  Future<bool?> _showResult(TransferResult res) => showAppSheet<bool>(
        context,
        title: res.duplicate ? tr('Bu ko‘chirish avval saqlangan') : tr('Ko‘chirildi ✓'),
        builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (res.duplicate)
            ErrorBanner(
              key: const Key('tr-duplicate'),
              severity: BannerSeverity.warning,
              message: tr('Server bu so‘rovni avval qabul qilgan — tovar QAYTA ko‘chirilmadi. Qoldiqni tekshiring.'),
            )
          else ...[
            Text('${res.from ?? ''} → ${res.to ?? ''}',
                key: const Key('tr-done'), style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            for (final m in res.moved)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  [
                    '${m.product}: ${formatMilli(m.qtyMilli, group: true)}',
                    if (m.fromLeftMilli != null)
                      trArgs('manbada {q} qoldi', {'q': formatMilli(m.fromLeftMilli!, group: true)}),
                  ].join(' · '),
                  style: TextStyle(color: AppColors.text2),
                ),
              ),
          ],
          const SizedBox(height: 16),
          SizedBox(
            height: kPrimaryButtonHeight,
            child: ElevatedButton(
              key: const Key('tr-again'),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(tr('Yana ko‘chirish')),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: kMinTouch,
            child: TextButton(
              key: const Key('tr-close'),
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(tr('Tayyor')),
            ),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final reason = _disabledReason();
    final allowed = Perm.allows('stock.transfer');
    return Scaffold(
      appBar: AppBar(title: Text(tr('Filiallararo transfer'))),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: ListView(
            key: const Key('tr-list'),
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
            children: [
              if (!allowed)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: ErrorBanner(
                      key: const Key('tr-denied'),
                      message: Perm.reason('stock.transfer'),
                      severity: BannerSeverity.warning),
                ),
              ErrorBanner(
                key: const Key('tr-tracked-note'),
                severity: BannerSeverity.info,
                message: tr(
                    'Partiya bo‘yicha kuzatiladigan mahsulotni filiallararo ko‘chirib bo‘lmaydi: server partiyali ko‘chirishni hali qo‘llab-quvvatlamaydi. Bunday mahsulotlar ro‘yxatda belgilanadi va tanlanmaydi.'),
              ),
              if (_notice != null) ...[
                const SizedBox(height: 8),
                ErrorBanner(
                  key: const Key('tr-notice'),
                  message: _notice!,
                  severity: BannerSeverity.warning,
                  onDismiss: () => setState(() => _notice = null),
                ),
              ],
              StockSectionTitle(tr('Qayerdan')),
              _items.isEmpty
                  ? const Align(alignment: Alignment.centerLeft, child: BranchChip())
                  : Row(children: [
                      Icon(Icons.lock_outline, size: 16, color: AppColors.muted),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(_s.currentBranch?.name ?? '—',
                            key: const Key('tr-from-locked'),
                            style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                      ),
                    ]),
              StockSectionTitle(tr('Qayerga')),
              _destBox(),
              StockSectionTitle(trArgs('Mahsulotlar ({n})', {'n': _items.length})),
              Row(children: [
                Expanded(
                  child: SizedBox(
                    height: kMinTouch,
                    child: OutlinedButton.icon(
                      key: const Key('tr-add'),
                      onPressed: _busy || !allowed || _fromId == null ? null : _add,
                      icon: const Icon(Icons.add),
                      label: Text(tr('Qo‘shish')),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: SizedBox(
                    height: kMinTouch,
                    child: OutlinedButton.icon(
                      key: const Key('tr-scan'),
                      onPressed: _busy || !allowed || _fromId == null ? null : _scan,
                      icon: const Icon(Icons.qr_code_scanner),
                      label: Text(tr('Skanerlash')),
                    ),
                  ),
                ),
              ]),
              const SizedBox(height: 8),
              if (_items.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: Center(child: Text(tr('Mahsulot qo‘shilmagan'), style: TextStyle(color: AppColors.muted))),
                )
              else
                for (final i in _items) _itemCard(i),
            ],
          ),
        ),
        if (_submitError != null)
          WriteErrorStrip(
            bannerKey: const Key('tr-error'),
            error: _submitError!,
            onDismiss: () => setState(() => _submitError = null),
          ),
        StickyActionBar(
          label: _submitError != null && isConnectivityErrorForWrite(_submitError)
              ? tr('Qayta yuborish')
              : tr('Ko‘chirishni tasdiqlash'),
          icon: Icons.swap_horiz,
          busy: _busy,
          enabled: reason == null,
          disabledReason: reason,
          onPressed: _submit,
        ),
      ]),
    );
  }

  Widget _destBox() {
    if (_branchesError != null) return ErrorBanner(error: _branchesError, onRetry: _loadBranches);
    if (_branches == null) {
      return const SizedBox(height: kMinTouch, child: Center(child: CircularProgressIndicator(strokeWidth: 2.4)));
    }
    if (_destinations.isEmpty) {
      return Text(tr('Ko‘chirish uchun boshqa faol filial yo‘q'), style: TextStyle(color: AppColors.muted));
    }
    return Material(
      color: AppColors.card,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        key: const Key('tr-dest'),
        borderRadius: BorderRadius.circular(12),
        onTap: _busy ? null : _pickDest,
        child: Container(
          constraints: const BoxConstraints(minHeight: 52),
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _to == null ? AppColors.warnBorder : AppColors.accentBorder),
          ),
          child: Row(children: [
            Icon(Icons.store_mall_directory_outlined, size: 20, color: AppColors.accentStrong),
            const SizedBox(width: 10),
            Expanded(
              child: Text(_to?.name ?? tr('Filialni tanlang'),
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: _to == null ? AppColors.muted : AppColors.text)),
            ),
            Icon(Icons.expand_more, color: AppColors.muted),
          ]),
        ),
      ),
    );
  }

  Widget _itemCard(_TItem i) => Container(
        key: Key('tr-item-${i.product.id}'),
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.fromLTRB(14, 8, 4, 8),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(i.product.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
              Text(trArgs('Manbada: {q}', {'q': qtyUnit(i.product.stockMilli, i.product.unit)}),
                  style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          Text(qtyUnit(i.milli, i.product.unit), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
          IconButton(
            key: Key('tr-edit-${i.product.id}'),
            tooltip: tr('Tahrirlash'),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: _busy ? null : () => _editQty(i.product),
            icon: Icon(Icons.edit_outlined, color: AppColors.accentStrong),
          ),
          IconButton(
            key: Key('tr-remove-${i.product.id}'),
            tooltip: tr('Ro‘yxatdan olib tashlash'),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: _busy ? null : () => setState(() => _items.remove(i)),
            icon: const Icon(Icons.close, color: AppColors.danger),
          ),
        ]),
      );
}

class _QtySheet extends StatefulWidget {
  const _QtySheet({required this.product, this.initialMilli});
  final StockProduct product;
  final int? initialMilli;

  @override
  State<_QtySheet> createState() => _QtySheetState();
}

class _QtySheetState extends State<_QtySheet> {
  late final TextEditingController _c =
      TextEditingController(text: widget.initialMilli == null ? '' : milliToInput(widget.initialMilli!));
  bool _tried = false;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  String? _error() {
    final r = parseQty(_c.text);
    if (!r.ok) return qtyErrorText(r.error!);
    if (r.value! > widget.product.stockMilli) {
      return trArgs('Qoldiqdan ko‘p (qoldiq: {q})', {'q': qtyUnit(widget.product.stockMilli, widget.product.unit)});
    }
    return null;
  }

  void _save() {
    if (_error() != null) {
      setState(() => _tried = true);
      return;
    }
    Navigator.of(context).pop(parseQty(_c.text).value);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final err = _error();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(trArgs('Manba filialdagi qoldiq: {q}', {'q': qtyUnit(p.stockMilli, p.unit)}),
          style: TextStyle(fontSize: 14, color: AppColors.text2)),
      const SizedBox(height: 12),
      QtyField(
        key: const Key('tr-qty'),
        controller: _c,
        autofocus: true,
        label: tr('Ko‘chiriladigan miqdor'),
        unit: p.unit,
        textInputAction: TextInputAction.done,
        onSubmitted: (_) => _save(),
        errorText: (_tried || _c.text.isNotEmpty) ? err : null,
        onChanged: (_) => setState(() {}),
      ),
      const SizedBox(height: 16),
      SizedBox(
        height: kPrimaryButtonHeight,
        child: ElevatedButton(key: const Key('tr-qty-save'), onPressed: _save, child: Text(tr('Saqlash'))),
      ),
    ]);
  }
}
