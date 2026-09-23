import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/stock_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../qty.dart';
import '../scan.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'barcode_scan_screen.dart';
import 'product_detail_screen.dart';

/// Ombor (stock) tab: server-side search over the catalog with infinite
/// scroll, scoped to the session's CURRENT branch.
///
/// ⚠️  The full catalog is NEVER loaded (Fayzan: 7137 products = 3.2 MB):
///     `GET /products?q=&limit=50&offset=&branch_id=` page by page. A branch
///     switch drops every row of the old branch before the new one loads.
class InventoryScreen extends StatefulWidget {
  /// Creates the tab. [scannerBuilder] replaces the camera (tests).
  const InventoryScreen({super.key, this.scannerBuilder});

  /// Camera override passed to the scanner (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

enum _Filter { all, tracked, archived }

class _InventoryScreenState extends State<InventoryScreen> {
  final _searchC = TextEditingController();
  final _sc = ScrollController();
  Timer? _debounce;
  _Filter _filter = _Filter.all;
  String _q = '';

  final List<StockProduct> _items = [];
  int? _total;
  bool _hasMore = false;
  bool _loading = false; // first page
  bool _loadingMore = false;
  Object? _error; // first page
  Object? _moreError;
  int _seq = 0;
  String? _loadedBranch;
  bool _started = false;
  bool _showTop = false;

  Session get _s => Session.instance;

  @override
  void initState() {
    super.initState();
    _s.addListener(_onSession);
    Api.stockRev.addListener(_onStock);
    _sc.addListener(() {
      final show = _sc.hasClients && _sc.offset > 600;
      if (show != _showTop) setState(() => _showTop = show);
    });
    _maybeStart();
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    Api.stockRev.removeListener(_onStock);
    _debounce?.cancel();
    _searchC.dispose();
    _sc.dispose();
    super.dispose();
  }

  bool get _sessionPending => _s.status == SessionStatus.loading;

  void _maybeStart() {
    if (_sessionPending) return; // branch unknown yet — wait for /auth/context
    _started = true;
    _reload();
  }

  void _onSession() {
    if (!mounted) return;
    if (!_started) {
      _maybeStart();
      if (!_started) setState(() {});
      return;
    }
    if (_s.currentBranchId != _loadedBranch) _reload();
  }

  void _onStock() {
    if (mounted && _started) _reload(keepRows: true);
  }

  /// Reloads from the first page. With [keepRows] (same branch refresh) the
  /// old rows stay visible until the new page arrives.
  Future<void> _reload({bool keepRows = false}) async {
    final branch = _s.currentBranchId;
    final seq = ++_seq;
    setState(() {
      if (!keepRows || branch != _loadedBranch) {
        _items.clear();
        _total = null;
        _hasMore = false;
      }
      _loadedBranch = branch;
      _loading = true;
      _loadingMore = false;
      _error = null;
      _moreError = null;
    });
    try {
      final page = await StockApi.products(
        q: _q,
        branchId: branch,
        offset: 0,
        tracked: _filter == _Filter.tracked ? true : null,
        archived: _filter == _Filter.archived,
      );
      if (!mounted || seq != _seq) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _hasMore = page.hasMore;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loading || _loadingMore || !_hasMore || _moreError != null) return;
    final seq = _seq;
    final branch = _loadedBranch;
    setState(() => _loadingMore = true);
    try {
      final page = await StockApi.products(
        q: _q,
        branchId: branch,
        offset: _items.length,
        tracked: _filter == _Filter.tracked ? true : null,
        archived: _filter == _Filter.archived,
      );
      if (!mounted || seq != _seq) return;
      setState(() {
        final known = {for (final p in _items) p.id};
        _items.addAll(page.items.where((p) => !known.contains(p.id)));
        _total = page.total ?? _total;
        _hasMore = page.hasMore && page.items.isNotEmpty;
        _loadingMore = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _moreError = e;
        _loadingMore = false;
      });
    }
  }

  void _onQuery(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      if (!mounted) return;
      final q = v.trim();
      if (q == _q) return;
      _q = q;
      _reload();
    });
  }

  void _setFilter(_Filter f) {
    if (f == _filter) return;
    setState(() => _filter = f);
    _reload();
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: _s.currentBranchId, scannerBuilder: widget.scannerBuilder);
    if (hit == null || !mounted) return;
    _open(hit.product);
  }

  void _open(StockProduct p) {
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            ProductDetailScreen(productId: p.id, initialName: p.name, scannerBuilder: widget.scannerBuilder)));
  }

  @override
  Widget build(BuildContext context) {
    final bizDate = _s.businessDate();
    return Scaffold(
      floatingActionButton: _showTop
          ? FloatingActionButton.small(
              heroTag: 'invTop',
              tooltip: tr('Tepaga'),
              onPressed: () => _sc.animateTo(0, duration: const Duration(milliseconds: 350), curve: Curves.easeOut),
              backgroundColor: AppColors.accent,
              foregroundColor: Colors.white,
              child: const Icon(Icons.keyboard_arrow_up, size: 26),
            )
          : null,
      body: SafeArea(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 12, 8, 0),
            child: Row(children: [
              Expanded(child: Text(tr('Ombor'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800))),
              const Flexible(child: BranchChip()),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: Row(children: [
              Expanded(
                child: TextField(
                  key: const Key('stock-search'),
                  controller: _searchC,
                  onChanged: _onQuery,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (v) {
                    _debounce?.cancel();
                    _q = v.trim();
                    _reload();
                  },
                  decoration: InputDecoration(
                    hintText: tr('Nomi, artikul yoki shtrix-kod'),
                    prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 20),
                    constraints: const BoxConstraints(minHeight: kMinTouch),
                    suffixIcon: _searchC.text.isEmpty
                        ? null
                        : IconButton(
                            tooltip: tr('Tozalash'),
                            onPressed: () {
                              _searchC.clear();
                              _onQuery('');
                              setState(() {});
                            },
                            icon: const Icon(Icons.close),
                          ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: kPrimaryButtonHeight,
                height: kPrimaryButtonHeight,
                child: OutlinedButton(
                  key: const Key('stock-scan'),
                  onPressed: _scan,
                  style: OutlinedButton.styleFrom(padding: EdgeInsets.zero),
                  child: Semantics(
                    label: tr('Skanerlash'),
                    child: Icon(Icons.qr_code_scanner, color: AppColors.accentStrong),
                  ),
                ),
              ),
            ]),
          ),
          SizedBox(
            height: kMinTouch + 8,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
              children: [
                _chip(_Filter.all, tr('Hammasi')),
                _chip(_Filter.tracked, tr('Partiyali')),
                _chip(_Filter.archived, tr('Arxivdagi')),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 6, kGutter, 4),
            child: Text(
              _total == null ? (_loading ? tr('Yuklanmoqda…') : '') : trArgs('{n} ta mahsulot', {'n': _total}),
              key: const Key('stock-total'),
              style: TextStyle(fontSize: 12.5, color: AppColors.muted),
            ),
          ),
          Expanded(child: _list(bizDate)),
        ]),
      ),
    );
  }

  Widget _chip(_Filter f, String label) {
    final on = _filter == f;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        key: Key('stock-filter-${f.name}'),
        label: Text(label),
        selected: on,
        onSelected: (_) => _setFilter(f),
        materialTapTargetSize: MaterialTapTargetSize.padded,
        selectedColor: AppColors.accentSoft,
        backgroundColor: AppColors.card,
        side: BorderSide(color: on ? AppColors.accentBorder : AppColors.border),
        labelStyle: TextStyle(fontWeight: FontWeight.w600, color: on ? AppColors.accentStrong : AppColors.text3),
        showCheckmark: false,
      ),
    );
  }

  Widget _list(String? bizDate) {
    if (!_started || (_loading && _items.isEmpty)) return const SkeletonList();
    if (_error != null && _items.isEmpty) return ErrorState(error: _error!, onRetry: _reload);
    if (_items.isEmpty) {
      return RefreshIndicator(
        onRefresh: _reload,
        child: ListView(children: [
          const SizedBox(height: 60),
          EmptyState(
            text: _q.isEmpty ? tr('Bu bo‘limda mahsulot yo‘q') : trArgs('«{q}» bo‘yicha topilmadi', {'q': _q}),
            icon: Icons.search_off,
          ),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView.builder(
        key: const Key('stock-list'),
        controller: _sc,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 24),
        itemCount: _items.length + 1,
        itemBuilder: (context, i) {
          if (i < _items.length) {
            final p = _items[i];
            return StockProductTile(
                key: Key('stock-row-${p.id}'), product: p, businessDate: bizDate, onTap: () => _open(p));
          }
          return _footer();
        },
      ),
    );
  }

  Widget _footer() {
    if (_error != null) {
      return Padding(
          padding: const EdgeInsets.only(top: 8),
          child: ErrorBanner(error: _error, onRetry: () => _reload(keepRows: true)));
    }
    if (_moreError != null) {
      return Padding(
        padding: const EdgeInsets.only(top: 8),
        child: ErrorBanner(
          key: const Key('stock-more-error'),
          error: _moreError,
          onRetry: () {
            setState(() => _moreError = null);
            _loadMore();
          },
        ),
      );
    }
    if (_hasMore) {
      // Ro'yxat oxiri ko'rindi — keyingi sahifa (bitta so'rov bir vaqtda).
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadMore();
      });
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2.4))),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Center(
        child: Text(tr('Ro‘yxat oxiri'), style: TextStyle(fontSize: 12, color: AppColors.faint)),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  Shared stock widgets (write-off, count, transfer, product detail)
// ══════════════════════════════════════════════════════════════════════════

/// A small coloured pill.
class StockBadge extends StatelessWidget {
  /// Creates the badge.
  const StockBadge(this.text, this.color, {super.key, this.icon});

  /// Label.
  final String text;

  /// Colour.
  final Color color;

  /// Optional leading icon.
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 12, color: color), const SizedBox(width: 3)],
          Flexible(
            child: Text(text,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                softWrap: false,
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color)),
          ),
        ]),
      );
}

/// Today's calendar date (`YYYY-MM-DD`) of [businessDate], else the device's.
String effectiveBusinessDate(String? businessDate) => businessDate ?? isoDate(DateTime.now());

/// Days between [businessDate] and [expiry] (negative = expired), or null.
int? daysUntil(String? expiry, String? businessDate) {
  final e = parseIsoDate(expiry), b = parseIsoDate(effectiveBusinessDate(businessDate));
  if (e == null || b == null) return null;
  return e.difference(b).inDays;
}

/// Expiry badge: expired / today / N days (warn ≤ 7) / date.
Widget expiryBadge(String? expiry, String? businessDate, {bool? expiredFlag}) {
  final d = daysUntil(expiry, businessDate);
  if (expiry == null || d == null) return StockBadge(tr('Muddatsiz'), AppColors.muted);
  if ((expiredFlag ?? false) || d < 0) {
    return StockBadge(tr('Muddati o‘tgan'), AppColors.danger, icon: Icons.event_busy);
  }
  if (d == 0) return StockBadge(tr('Bugun tugaydi'), AppColors.danger, icon: Icons.schedule);
  if (d <= 7) return StockBadge(trArgs('{n} kun qoldi', {'n': d}), AppColors.warn, icon: Icons.schedule);
  return StockBadge(dateDisplay(expiry), AppColors.muted);
}

/// Badges of a product row: tracking, archive, stock level, product expiry.
List<Widget> productBadges(StockProduct p, {String? businessDate, bool level = true}) => [
      if (p.trackLots) StockBadge(tr('Partiyali'), AppColors.accentStrong, icon: Icons.inventory_2_outlined),
      if (p.trackExpiry) StockBadge(tr('Muddatli'), AppColors.accentStrong),
      if (p.isWeighted) StockBadge(tr('Tarozi'), AppColors.muted),
      if (!p.isActive) StockBadge(tr('Arxivda'), AppColors.muted),
      if (level && p.level == StockLevel.out) StockBadge(tr('Tugagan'), AppColors.danger),
      if (level && p.level == StockLevel.low) StockBadge(tr('Kam qoldi'), AppColors.warn),
      if (p.productExpiry != null && (daysUntil(p.productExpiry, businessDate) ?? 99) <= 7)
        expiryBadge(p.productExpiry, businessDate),
    ];

/// Quantity + unit (`1,5 kg`).
String qtyUnit(int milli, String unit) => '${formatMilli(milli, group: true)} $unit'.trim();

/// One product row (Ombor list, pickers).
class StockProductTile extends StatelessWidget {
  /// Creates the row.
  const StockProductTile({
    super.key,
    required this.product,
    this.onTap,
    this.businessDate,
    this.blockedReason,
    this.showPrice = true,
  });

  /// Product.
  final StockProduct product;

  /// Tap action (null = disabled).
  final VoidCallback? onTap;

  /// Business date for the product-expiry badge.
  final String? businessDate;

  /// Why the product cannot be chosen here (shown instead of acting).
  final String? blockedReason;

  /// Show the sell price.
  final bool showPrice;

  @override
  Widget build(BuildContext context) {
    final p = product;
    final col = switch (p.level) {
      StockLevel.out => AppColors.danger,
      StockLevel.low => AppColors.warn,
      StockLevel.ok => AppColors.text,
    };
    final blocked = blockedReason != null;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(13),
        child: InkWell(
          borderRadius: BorderRadius.circular(13),
          onTap: blocked ? null : onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(13),
              border: Border.all(color: blocked ? AppColors.warnBorder : AppColors.border),
            ),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w600,
                          color: blocked ? AppColors.muted : AppColors.text)),
                  const SizedBox(height: 4),
                  Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    if (showPrice)
                      Text('${formatCents(p.sellCents)} · ${p.unit}',
                          style: TextStyle(fontSize: 12, color: AppColors.muted)),
                    ...productBadges(p, businessDate: businessDate),
                  ]),
                  if (blocked) ...[
                    const SizedBox(height: 4),
                    Text(blockedReason!, style: const TextStyle(fontSize: 12, color: AppColors.warn)),
                  ],
                ]),
              ),
              const SizedBox(width: 10),
              // Katta qoldiq (1 234 567,891) nomni siqib chiqarmasin — ustun cheklangan.
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 110),
                child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerRight,
                    child: Text(formatMilli(p.stockMilli, group: true),
                        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: col)),
                  ),
                  Text(p.minMilli > 0 ? trArgs('min {n}', {'n': formatMilli(p.minMilli)}) : p.unit,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 11, color: AppColors.faint)),
                ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// A product chosen in a picker or by the scanner.
class PickedProduct {
  /// Creates the pick.
  const PickedProduct(this.product, {this.scaleMilli});

  /// Product (stock of the branch it was looked up in).
  final StockProduct product;

  /// Weight from a scale label (milli), if the code was one.
  final int? scaleMilli;
}

/// Opens the server-backed scanner (`GET /products/scan`) and returns the
/// product with its stock in [branchId]; null when closed.
Future<PickedProduct?> scanStockProduct(BuildContext context,
    {required String? branchId, ScannerViewBuilder? scannerBuilder}) async {
  final r = await Navigator.of(context).push<ScanResult>(MaterialPageRoute(
    builder: (_) => BarcodeScanScreen.lookup(branchId: branchId, scannerBuilder: scannerBuilder),
  ));
  final p = r?.product;
  if (r == null || p == null) return null;
  return PickedProduct(StockProduct.fromJson(p.raw), scaleMilli: r.kind == ScanKind.scale ? r.qtyMilli : null);
}

/// Bottom sheet with a server-side product search (paged) and a scan
/// button. Products for which [blockedReason] returns a text are listed but
/// cannot be chosen (the reason is shown).
Future<PickedProduct?> showStockProductPicker(
  BuildContext context, {
  required String? branchId,
  String? title,
  String? Function(StockProduct p)? blockedReason,
  ScannerViewBuilder? scannerBuilder,
}) =>
    showAppSheet<PickedProduct>(
      context,
      title: title ?? tr('Mahsulot tanlang'),
      scrollable: false,
      builder: (ctx) =>
          _ProductSearchSheet(branchId: branchId, blockedReason: blockedReason, scannerBuilder: scannerBuilder),
    );

class _ProductSearchSheet extends StatefulWidget {
  const _ProductSearchSheet({required this.branchId, this.blockedReason, this.scannerBuilder});
  final String? branchId;
  final String? Function(StockProduct p)? blockedReason;
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<_ProductSearchSheet> createState() => _ProductSearchSheetState();
}

class _ProductSearchSheetState extends State<_ProductSearchSheet> {
  final _c = TextEditingController();
  Timer? _debounce;
  final List<StockProduct> _items = [];
  bool _loading = true, _more = false, _hasMore = false;
  Object? _error;
  String? _scanError;
  int _seq = 0;
  String _q = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _c.dispose();
    super.dispose();
  }

  Future<void> _load({bool more = false}) async {
    if (more && (_more || !_hasMore || _loading)) return;
    final seq = more ? _seq : ++_seq;
    setState(() {
      if (more) {
        _more = true;
      } else {
        _loading = true;
        _items.clear();
      }
      _error = null;
    });
    try {
      final page = await StockApi.products(q: _q, branchId: widget.branchId, offset: more ? _items.length : 0);
      if (!mounted || seq != _seq) return;
      setState(() {
        _items.addAll(page.items);
        _hasMore = page.hasMore && page.items.isNotEmpty;
        _loading = false;
        _more = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
        _more = false;
      });
    }
  }

  void _onQuery(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      if (!mounted || v.trim() == _q) return;
      _q = v.trim();
      _load();
    });
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: widget.branchId, scannerBuilder: widget.scannerBuilder);
    if (hit == null || !mounted) return;
    final why = widget.blockedReason?.call(hit.product);
    if (why != null) {
      setState(() => _scanError = '${hit.product.name}: $why');
      return;
    }
    Navigator.of(context).pop(hit);
  }

  @override
  Widget build(BuildContext context) {
    final h = MediaQuery.of(context).size.height * 0.72;
    return SizedBox(
      height: h,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 8),
          child: Row(children: [
            Expanded(
              child: TextField(
                key: const Key('picker-search'),
                controller: _c,
                autofocus: true,
                onChanged: _onQuery,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: tr('Nomi, artikul yoki shtrix-kod'),
                  prefixIcon: Icon(Icons.search, color: AppColors.muted),
                  constraints: const BoxConstraints(minHeight: kMinTouch),
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: kPrimaryButtonHeight,
              height: kPrimaryButtonHeight,
              child: OutlinedButton(
                key: const Key('picker-scan'),
                onPressed: _scan,
                style: OutlinedButton.styleFrom(padding: EdgeInsets.zero),
                child: Semantics(
                    label: tr('Skanerlash'), child: Icon(Icons.qr_code_scanner, color: AppColors.accentStrong)),
              ),
            ),
          ]),
        ),
        if (_scanError != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 0, kGutter, 8),
            child: ErrorBanner(
              key: const Key('picker-scan-blocked'),
              message: _scanError!,
              severity: BannerSeverity.warning,
              onDismiss: () => setState(() => _scanError = null),
            ),
          ),
        Expanded(child: _body()),
      ]),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null && _items.isEmpty) return ErrorState(error: _error!, onRetry: _load);
    if (_items.isEmpty) {
      return EmptyState(
          text: _q.isEmpty ? tr('Mahsulot yo‘q') : trArgs('«{q}» bo‘yicha topilmadi', {'q': _q}),
          icon: Icons.search_off);
    }
    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(kGutter, 0, kGutter, kGutter),
      itemCount: _items.length + 1,
      itemBuilder: (context, i) {
        if (i == _items.length) {
          if (_error != null) return ErrorBanner(error: _error, onRetry: () => _load(more: true));
          if (!_hasMore) return const SizedBox(height: 8);
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) _load(more: true);
          });
          return const Padding(
            padding: EdgeInsets.all(12),
            child: Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.2))),
          );
        }
        final p = _items[i];
        final why = widget.blockedReason?.call(p);
        return StockProductTile(
          key: Key('picker-row-${p.id}'),
          product: p,
          blockedReason: why,
          businessDate: Session.instance.businessDate(widget.branchId),
          onTap: () => Navigator.of(context).pop(PickedProduct(p)),
        );
      },
    );
  }
}

/// An inline (non-expanding) async section: spinner, error + retry, data.
///
/// A new [reloadKey] (e.g. another branch) DROPS the old data before loading,
/// so data of branch A is never shown under branch B.
class InlineAsync<T> extends StatefulWidget {
  /// Creates the section.
  const InlineAsync({super.key, required this.load, required this.builder, this.reloadKey, this.minHeight = 96});

  /// Loader.
  final Future<T> Function() load;

  /// Data builder; `reload` re-runs [load] keeping the data on screen.
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;

  /// Changing it reloads from scratch.
  final Object? reloadKey;

  /// Height of the first-load placeholder.
  final double minHeight;

  @override
  State<InlineAsync<T>> createState() => _InlineAsyncState<T>();
}

class _InlineAsyncState<T> extends State<InlineAsync<T>> {
  int _seq = 0;
  bool _loading = true, _has = false;
  T? _data;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _run();
  }

  @override
  void didUpdateWidget(covariant InlineAsync<T> old) {
    super.didUpdateWidget(old);
    if (old.reloadKey != widget.reloadKey) {
      _has = false;
      _data = null;
      _run();
    }
  }

  Future<void> _run() async {
    final seq = ++_seq;
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final d = await widget.load();
      if (!mounted || seq != _seq) return;
      setState(() {
        _data = d;
        _has = true;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_has) {
      if (_error != null) return ErrorBanner(error: _error, onRetry: _run);
      return SizedBox(
        height: widget.minHeight,
        child: const Center(child: SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2.4))),
      );
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (_loading) const LinearProgressIndicator(minHeight: 2),
      if (_error != null) ...[ErrorBanner(error: _error, onRetry: _run), const SizedBox(height: 8)],
      widget.builder(context, _data as T, _run),
    ]);
  }
}

/// Section title used by the stock screens.
class StockSectionTitle extends StatelessWidget {
  /// Creates the title.
  const StockSectionTitle(this.text, {super.key, this.trailing});

  /// Title text.
  final String text;

  /// Optional trailing widget.
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 18, bottom: 8),
        child: Row(children: [
          Expanded(
            child: Semantics(
              header: true,
              child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
            ),
          ),
          if (trailing != null) trailing!,
        ]),
      );
}

/// Human label of a lot: batch number or "no number" + expiry.
String lotLabel(LotRow l) {
  final n = l.batchNumber ?? tr('Raqamsiz partiya');
  return l.expiryDate == null ? n : '$n · ${dateDisplay(l.expiryDate)}';
}

/// Extra line a connectivity failure of a WRITE needs: the outcome is unknown,
/// a retry is safe (same `client_uuid`).
String writeRetryHint(Object e) => isConnectivityErrorForWrite(e)
    ? tr('Natija noma’lum: amal saqlangan bo‘lishi mumkin. Qayta yuborsangiz, ikki marta yozilmaydi.')
    : '';

/// True for network / timeout failures (nothing decided by the server).
bool isConnectivityErrorForWrite(Object? e) => e is ApiException && e.isConnectivity;

/// A failed write, pinned right above the sticky action bar so it is always
/// visible (never scrolled away at the end of a long form). A connectivity
/// failure adds [writeRetryHint].
class WriteErrorStrip extends StatelessWidget {
  /// Creates the strip.
  const WriteErrorStrip({super.key, required this.error, this.onDismiss, this.bannerKey});

  /// The failure.
  final Object error;

  /// Dismiss action.
  final VoidCallback? onDismiss;

  /// Key of the inner [ErrorBanner] (tests).
  final Key? bannerKey;

  @override
  Widget build(BuildContext context) => ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 200),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
          child: ErrorBanner(
            key: bannerKey,
            error: error,
            message: [userMessage(error), writeRetryHint(error)].where((s) => s.isNotEmpty).join('\n'),
            onDismiss: onDismiss,
          ),
        ),
      );
}
