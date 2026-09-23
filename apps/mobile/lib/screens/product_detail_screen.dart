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
import 'barcode_scan_screen.dart';
import 'inventarizatsiya_screen.dart';
import 'inventory_screen.dart';
import 'writeoff_screen.dart';

/// Product card: prices, stock, sales statistics, and — for lot-tracked
/// products — the lots of the CURRENT branch (`GET /lots/products/{id}?branch_id=`)
/// with expired lots highlighted.
///
/// BRANCH SCOPE. Stock, minimum and this month's in / out come from
/// `GET /products/{id}?branch_id=<current branch>` and are labelled with that
/// branch. A user who sees several branches also gets the total of all his
/// branches (`GET /products/{id}` without `branch_id`), labelled as such.
/// Without a current branch (several branches, none chosen) the card shows
/// that total only — never a guessed branch. A branch switch reloads the card
/// from scratch (branch A numbers are never shown under branch B).
///
/// ⚠️  For a tracked product the product-level `expiry_date` is a frozen
///     column: it is NOT shown; the lots carry the real dates.
class ProductDetailScreen extends StatefulWidget {
  /// Creates the screen.
  const ProductDetailScreen({super.key, required this.productId, this.initialName, this.scannerBuilder});

  /// Product id.
  final String productId;

  /// Name shown in the app bar while loading.
  final String? initialName;

  /// Camera override for the write-off / count screens opened from here (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

/// What the card shows: the detail of the current branch (or of all visible
/// branches when there is none) plus, for a multi-branch user, the total stock
/// of all his branches.
class _CardData {
  const _CardData(this.detail, this.allStockMilli);
  final StockProductDetail detail;

  /// Stock summed over the caller's visible branches (null: not requested).
  final int? allStockMilli;
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  final Session _s = Session.instance;
  StockProductDetail? _detail;
  late String? _branchId = _s.currentBranchId;

  @override
  void initState() {
    super.initState();
    _s.addListener(_onSession);
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    super.dispose();
  }

  void _onSession() {
    final b = _s.currentBranchId;
    if (b == _branchId || !mounted) return;
    // Filial almashdi: eski filial raqamlari (va ular asosidagi amallar) darhol olib tashlanadi.
    setState(() {
      _branchId = b;
      _detail = null;
    });
  }

  Future<_CardData> _load() async {
    final branchId = _s.currentBranchId;
    final withTotal = branchId != null && _s.branches.length > 1;
    final r = await Future.wait([
      StockApi.productDetail(widget.productId, branchId: branchId),
      if (withTotal) StockApi.productDetail(widget.productId),
    ]);
    final d = _CardData(r.first, withTotal ? r.last.stockMilli : null);
    if (mounted && branchId == _s.currentBranchId) setState(() => _detail = d.detail);
    return d;
  }

  Future<void> _writeoff() async {
    final d = _detail;
    if (d == null) return;
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => WriteoffScreen(initialProduct: d.toProduct(), scannerBuilder: widget.scannerBuilder)));
  }

  Future<void> _count() async {
    final d = _detail;
    if (d == null) return;
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => InventarizatsiyaScreen(initialProduct: d.toProduct(), scannerBuilder: widget.scannerBuilder)));
  }

  @override
  Widget build(BuildContext context) {
    final canWo = Perm.allows('stock.writeoff');
    final canCount = Perm.allows('stock.count');
    return Scaffold(
      appBar: AppBar(
        title:
            Text(_detail?.name ?? widget.initialName ?? tr('Mahsulot'), maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
      body: Column(children: [
        Expanded(
          child: AsyncView<_CardData>(
            // Filial kaliti: almashganda holat NOLDAN (A filial raqamlari B ostida qolmaydi).
            key: ValueKey('pd-${_branchId ?? '-'}'),
            reloadOn: Api.stockRev,
            load: _load,
            refreshable: true,
            builder: (context, d) => _body(d.detail, d.allStockMilli),
          ),
        ),
        if (_detail != null && (canWo || canCount))
          StickyActionBar(
            key: const Key('pd-actions'),
            label: canCount ? tr('Sanash') : tr('Hisobdan chiqarish'),
            icon: canCount ? Icons.fact_check_outlined : Icons.remove_circle_outline,
            onPressed: canCount ? _count : _writeoff,
            secondaryLabel: canCount && canWo ? tr('Hisobdan chiqarish') : null,
            onSecondary: canCount && canWo ? _writeoff : null,
          ),
      ]),
    );
  }

  Widget _body(StockProductDetail d, int? allStockMilli) {
    final s = Session.instance;
    final biz = s.businessDate();
    final severalBranches = s.branches.length > 1;
    final cur = s.currentBranch;
    final branchName = d.branchId == null
        ? null
        : (cur != null && cur.id == d.branchId
            ? cur.name
            : [for (final b in s.branches) if (b.id == d.branchId) b.name].firstOrNull);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(kGutter, 12, kGutter, 28),
      children: [
        Text(d.name, key: const Key('pd-name'), style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          if (d.trackLots)
            StockBadge(tr('Partiya bo‘yicha kuzatiladi'), AppColors.accentStrong, icon: Icons.inventory_2_outlined),
          if (d.trackExpiry) StockBadge(tr('Muddat kuzatiladi'), AppColors.accentStrong, icon: Icons.event_available),
          if (d.isWeighted) StockBadge(tr('Tarozi'), AppColors.accentStrong),
          if (d.plu != null) StockBadge('PLU ${d.plu}', AppColors.muted),
          if (!d.isActive) StockBadge(tr('Arxivda'), AppColors.muted),
          for (final b in d.barcodes.take(3)) StockBadge(b, AppColors.muted),
        ]),
        StockSectionTitle(tr('Narxlar')),
        Row(children: [
          Expanded(child: _card(tr('Kelish narxi'), formatCents(d.buyCents), AppColors.text)),
          const SizedBox(width: 10),
          Expanded(child: _card(tr('Sotish narxi'), formatCents(d.sellCents), AppColors.accentStrong)),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(
            child: _card(
                tr('Birlik foyda'), formatCents(d.profitCents), d.profitCents >= 0 ? AppColors.ok : AppColors.danger),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: _card(
              tr('Margin'),
              '${d.marginPct.toStringAsFixed(1).replaceFirst(RegExp(r'\.0$'), '').replaceFirst(RegExp(r'^-0$'), '0').replaceAll('.', ',')}%',
              d.profitCents >= 0 ? AppColors.ok : AppColors.danger,
            ),
          ),
        ]),
        StockSectionTitle(tr('Qoldiq')),
        Column(key: const Key('pd-stock'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: _card(
                // Filial yuborilgan — raqam SHU filialniki; yuborilmagan (filial tanlanmagan) —
                // ko'rinadigan filiallar yig'indisi va shunday yoziladi.
                d.branchId != null
                    ? (severalBranches && branchName != null
                        ? trArgs('Qoldiq ({branch})', {'branch': branchName})
                        : tr('Qoldiq'))
                    : (severalBranches ? tr('Qoldiq (barcha filiallaringiz)') : tr('Qoldiq')),
                qtyUnit(d.stockMilli, d.unit),
                d.stockMilli <= 0
                    ? AppColors.danger
                    : (d.minMilli > 0 && d.stockMilli <= d.minMilli ? AppColors.warn : AppColors.text),
                key: const Key('pd-stock-branch'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(child: _card(tr('Min. qoldiq'), qtyUnit(d.minMilli, d.unit), AppColors.text)),
          ]),
          if (allStockMilli != null) ...[
            const SizedBox(height: 8),
            Text(
              '${tr('Qoldiq (barcha filiallaringiz)')}: ${qtyUnit(allStockMilli, d.unit)}',
              key: const Key('pd-stock-all'),
              style: TextStyle(fontSize: 13, color: AppColors.text2),
            ),
          ],
        ]),
        if (d.productExpiry != null) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text(trArgs('Yaroqlilik muddati: {d}', {'d': dateDisplay(d.productExpiry)}),
                key: const Key('pd-product-expiry'), style: TextStyle(fontSize: 13, color: AppColors.text2)),
            expiryBadge(d.productExpiry, biz),
          ]),
        ],
        if (d.trackLots) _LotsSection(productId: d.id, unit: d.unit),
        StockSectionTitle(tr('Sotuv statistikasi')),
        _statBlock(tr('So‘nggi 30 kun'), d.sales30, d.unit),
        const SizedBox(height: 10),
        _statBlock(tr('So‘nggi 7 kun'), d.sales7, d.unit),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: _card(tr('Bu oy kirim'), '+${formatMilli(d.monthInMilli, group: true)}', AppColors.ok)),
          const SizedBox(width: 10),
          Expanded(
            child: _card(tr('Bu oy chiqim'),
                '${d.monthOutMilli > 0 ? '−' : ''}${formatMilli(d.monthOutMilli, group: true)}', AppColors.danger),
          ),
        ]),
        if (d.lastSoldAt != null) ...[
          const SizedBox(height: 10),
          Text('${tr('Oxirgi sotilgan')}: ${dmy(serverDt(d.lastSoldAt))}',
              style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
        ],
        if (Perm.allows('stock.movements')) ...[
          StockSectionTitle(tr('So‘nggi harakatlar')),
          InlineAsync<List<MoveRow>>(
            key: const Key('pd-moves'),
            load: () => Api.movements(productId: d.id, limit: 30),
            builder: (context, rows, _) => rows.isEmpty
                ? Text(tr('Harakat yo‘q'), style: TextStyle(color: AppColors.muted))
                : Column(children: [for (final m in rows) _move(m)]),
          ),
        ],
        const SizedBox(height: 16),
        Text('${tr('Qo‘shgan')}: ${d.createdBy}', style: TextStyle(fontSize: 11.5, color: AppColors.faint)),
      ],
    );
  }

  Widget _statBlock(String title, SalesStats s, String unit) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(child: _mini(tr('Sotildi'), qtyUnit(s.qtyMilli, unit))),
            Expanded(child: _mini(tr('Tushum'), formatCents(s.revenueCents))),
            Expanded(
                child: _mini(tr('Foyda'), formatCents(s.profitCents),
                    color: s.profitCents >= 0 ? AppColors.ok : AppColors.danger)),
          ]),
        ]),
      );

  Widget _mini(String l, String v, {Color? color}) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: TextStyle(fontSize: 11, color: AppColors.muted)),
        const SizedBox(height: 3),
        Text(v, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: color ?? AppColors.text)),
      ]);

  Widget _card(String l, String v, Color c, {Key? key}) => Container(
        key: key,
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(l, style: TextStyle(fontSize: 12, color: AppColors.muted)),
          const SizedBox(height: 6),
          Text(v, style: TextStyle(fontSize: 16.5, fontWeight: FontWeight.w800, color: c)),
        ]),
      );

  Widget _move(MoveRow m) {
    final incoming = m.direction == 'in';
    final col = incoming ? AppColors.ok : AppColors.danger;
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 40),
      child: Row(children: [
        Icon(incoming ? Icons.south_west : Icons.north_east, size: 16, color: col),
        const SizedBox(width: 10),
        Expanded(child: Text(tr(m.type), style: const TextStyle(fontSize: 13.5))),
        Text('${incoming ? '+' : '−'}${formatMilli(milliFromNum(m.qty.abs()), group: true)}',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: col)),
        const SizedBox(width: 10),
        Text(dmy(m.at), style: TextStyle(fontSize: 11.5, color: AppColors.faint)),
      ]),
    );
  }
}

/// Lots of the product in the CURRENT branch (reloads on a branch switch and
/// after stock writes; the old branch's lots are dropped first).
class _LotsSection extends StatelessWidget {
  const _LotsSection({required this.productId, required this.unit});
  final String productId, unit;

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows('lots.product')) {
      return Padding(
        padding: const EdgeInsets.only(top: 18),
        child: ErrorBanner(
          key: const Key('pd-lots-denied'),
          message: '${tr('Partiyalarni ko‘rish uchun ruxsat kerak.')} ${Perm.reason('lots.product')}',
          severity: BannerSeverity.info,
        ),
      );
    }
    final s = Session.instance;
    return ListenableBuilder(
      listenable: Listenable.merge([s, Api.stockRev]),
      builder: (context, _) {
        final branchId = s.currentBranchId;
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          StockSectionTitle(tr('Partiyalar'), trailing: const BranchChip()),
          InlineAsync<ProductLots>(
            key: const Key('pd-lots'),
            reloadKey: '$branchId|${Api.stockRev.value}',
            load: () => StockApi.productLots(productId, branchId: branchId),
            builder: (context, lots, _) => LotListView(lots: lots, unit: unit),
          ),
        ]);
      },
    );
  }
}

/// Read-only list of a product's lots in one branch (FEFO order).
class LotListView extends StatelessWidget {
  /// Creates the list.
  const LotListView({super.key, required this.lots, required this.unit});

  /// Lots payload.
  final ProductLots lots;

  /// Unit label.
  final String unit;

  @override
  Widget build(BuildContext context) {
    final rows = lots.lots;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: 12, runSpacing: 4, children: [
        Text(trArgs('Filial qoldig‘i: {q}', {'q': qtyUnit(lots.inventoryMilli, unit)}),
            key: const Key('pd-branch-stock'), style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700)),
        if (lots.businessDate != null)
          Text(trArgs('Ish kuni: {d}', {'d': dateDisplay(lots.businessDate)}),
              style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
      ]),
      if (lots.shortfallMilli > 0) ...[
        const SizedBox(height: 8),
        ErrorBanner(
          key: const Key('pd-shortfall'),
          severity: BannerSeverity.warning,
          message: trArgs(
              'Partiyasiz sotilgan {q} hali partiyaga bog‘lanmagan — Manager ilovasida «Aniqlanmagan qoldiq» bo‘limida yoping.',
              {'q': qtyUnit(lots.shortfallMilli, unit)}),
        ),
      ],
      const SizedBox(height: 8),
      if (rows.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(tr('Bu filialda ochiq partiya yo‘q'), style: TextStyle(color: AppColors.muted)),
        )
      else
        for (final l in rows) LotCard(lot: l, unit: unit, businessDate: lots.businessDate),
    ]);
  }
}

/// One lot (batch): number, expiry badge, remaining / received, unit cost.
/// Expired lots are highlighted in red.
class LotCard extends StatelessWidget {
  /// Creates the card; [child] (e.g. a quantity field) goes under the facts.
  const LotCard(
      {super.key, required this.lot, required this.unit, this.businessDate, this.child, this.highlight = false});

  /// Lot.
  final LotRow lot;

  /// Unit label.
  final String unit;

  /// Branch business date.
  final String? businessDate;

  /// Optional content below (inputs).
  final Widget? child;

  /// Accent border (the lot the operator came from).
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final d = lot.daysLeft(businessDate);
    final expired = lot.expired || (d != null && d < 0);
    final border = expired ? AppColors.danger : (highlight ? AppColors.accent : AppColors.border);
    return Container(
      key: Key('lot-card-${lot.id}'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: expired ? AppColors.dangerSoft : AppColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border, width: expired || highlight ? 1.5 : 1),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(lot.batchNumber ?? tr('Raqamsiz partiya'),
              style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
          expiryBadge(lot.expiryDate, businessDate, expiredFlag: lot.expired),
          if (lot.sourceType == 'adjustment') StockBadge(tr('Sanoqda topilgan'), AppColors.muted),
          if (lot.sourceType == 'return_unattributed') StockBadge(tr('Taxminiy tannarx'), AppColors.warn),
          if (!lot.quantityBearing) StockBadge(lot.status, AppColors.muted),
        ]),
        const SizedBox(height: 6),
        Text(
          [
            if (lot.expiryDate != null) '${tr('Muddat')}: ${dateDisplay(lot.expiryDate)}',
            '${tr('Qoldiq')}: ${formatMilli(lot.remainingMilli, group: true)} / ${formatMilli(lot.receivedMilli, group: true)} $unit',
            '${tr('Tannarx')}: ${formatCents(lot.unitCostCents)}',
          ].join(' · '),
          style: TextStyle(fontSize: 12.5, color: AppColors.text2, height: 1.35),
        ),
        if (child != null) ...[const SizedBox(height: 10), child!],
      ]),
    );
  }
}
