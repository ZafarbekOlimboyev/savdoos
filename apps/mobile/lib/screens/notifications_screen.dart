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
import 'product_detail_screen.dart';
import 'writeoff_screen.dart';

/// In-app notifications built from cheap SERVER summaries — never from the
/// full `/products` catalog:
///
/// * expiry — `GET /lots/alerts?branch_id=` (ombor.view): expired / today /
///   7 / 30 days lot buckets of the CURRENT branch; a tap lists the lots
///   (`GET /lots/batches?expiry=`), with a write-off shortcut;
/// * stock — `GET /inventory/overview` + `GET /inventory/low` (hisobot.view)
///   of the CURRENT branch (`branch_id`); only when no branch is chosen (several
///   visible, none selected) the server sums the visible branches — labelled
///   so. A low-stock row opens the product card (`product_id`).
///
/// One [BranchChip] at the top: both sections follow the current branch.
///
/// ⚠️  The frozen product-level `expiry_date` of tracked products is not used.
class NotificationsScreen extends StatefulWidget {
  /// Creates the screen.
  const NotificationsScreen({super.key, this.scannerBuilder});

  /// Camera override for screens opened from here (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  int _tick = 0;

  Future<void> _refresh() async => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    final canLots = Perm.allows('lots.alerts');
    final canStock = Perm.allows('stock.overview');
    final s = Session.instance;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Bildirishnomalar'))),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListenableBuilder(
          listenable: Listenable.merge([s, Api.stockRev]),
          builder: (context, _) {
            final branchId = s.currentBranchId;
            final several = s.branches.length > 1;
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 24),
              children: [
                if (canLots || canStock)
                  const Padding(
                    padding: EdgeInsets.only(top: 4, bottom: 2),
                    child: Align(alignment: Alignment.centerLeft, child: BranchChip()),
                  ),
                if (!canLots && !canStock)
                  Padding(
                    padding: const EdgeInsets.only(top: 60),
                    child: EmptyState(
                      key: const Key('nt-denied'),
                      text: tr('Ombor bildirishnomalarini ko‘rish uchun ruxsat yo‘q.'),
                      icon: Icons.notifications_off_outlined,
                    ),
                  ),
                if (canLots) ...[
                  StockSectionTitle(tr('Yaroqlilik muddati')),
                  InlineAsync<LotAlerts>(
                    key: const Key('nt-lots'),
                    reloadKey: '$branchId|${Api.stockRev.value}|$_tick',
                    load: () => StockApi.lotAlerts(branchId: branchId),
                    builder: (context, a, _) => _expiry(a, branchId),
                  ),
                ],
                if (canStock) ...[
                  // Filial yuborilganda raqamlar SHU filialniki; «barcha filiallaringiz» faqat
                  // filial tanlanmagan (yig'indi) holatda.
                  StockSectionTitle(
                      branchId == null && several ? tr('Qoldiq (barcha filiallaringiz)') : tr('Qoldiq')),
                  InlineAsync<(StockOverview, List<LowStockRow>)>(
                    key: const Key('nt-stock'),
                    reloadKey: '$branchId|${Api.stockRev.value}|$_tick',
                    load: () async {
                      final r = await Future.wait<Object>(
                          [StockApi.overview(branchId: branchId), StockApi.low(branchId: branchId)]);
                      return (r[0] as StockOverview, r[1] as List<LowStockRow>);
                    },
                    builder: (context, d, _) => _stock(d.$1, d.$2),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _expiry(LotAlerts a, String? branchId) {
    final rows = [
      (ExpiryKind.expired, tr('Muddati o‘tgan'), AppColors.danger, Icons.event_busy),
      (ExpiryKind.today, tr('Bugun tugaydi'), AppColors.danger, Icons.schedule),
      (ExpiryKind.within7, tr('7 kun ichida'), AppColors.warn, Icons.schedule),
      (ExpiryKind.within30, tr('30 kun ichida'), AppColors.muted, Icons.date_range),
    ];
    final any = rows.any((r) => a.bucket(r.$1).lots > 0);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (!any)
        _tile(
          key: const Key('nt-expiry-ok'),
          icon: Icons.verified_outlined,
          color: AppColors.ok,
          title: a.trackedProducts == 0
              ? tr('Partiya bo‘yicha kuzatiladigan mahsulot yo‘q')
              : tr('Yaqin 30 kunda muddati tugaydigan partiya yo‘q'),
        ),
      for (final r in rows)
        if (a.bucket(r.$1).lots > 0)
          _tile(
            key: Key('nt-bucket-${r.$1}'),
            icon: r.$4,
            color: r.$3,
            title: r.$2,
            subtitle: trArgs('{n} ta partiya · miqdor {q} · tannarx {c}', {
              'n': a.bucket(r.$1).lots,
              'q': formatMilli(a.bucket(r.$1).qtyMilli, group: true),
              'c': formatCents(a.bucket(r.$1).valueCents),
            }),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => ExpiringLotsPage(kind: r.$1, title: r.$2, scannerBuilder: widget.scannerBuilder),
            )),
          ),
      if (a.shortfallCount > 0)
        _tile(
          key: const Key('nt-shortfall'),
          icon: Icons.link_off,
          color: AppColors.warn,
          title: trArgs('Partiyaga bog‘lanmagan sotuvlar: {n} ta', {'n': a.shortfallCount}),
          subtitle: tr('Manager ilovasida «Aniqlanmagan qoldiq» bo‘limida yoping.'),
        ),
    ]);
  }

  Widget _stock(StockOverview o, List<LowStockRow> low) {
    // Kalit noyob bo'lsin: filialsiz yig'indida bitta mahsulot har filial uchun alohida qator.
    final used = <String>{};
    String rowKey(LowStockRow r) {
      final base = 'nt-low-${r.productId ?? r.name}';
      var k = base;
      for (var i = 2; !used.add(k); i++) {
        k = '$base#$i';
      }
      return k;
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (o.outCount > 0)
        _tile(
          key: const Key('nt-out'),
          icon: Icons.remove_shopping_cart,
          color: AppColors.danger,
          title: trArgs('Tugagan: {n} ta', {'n': o.outCount}),
        ),
      if (o.lowCount > 0)
        _tile(
          key: const Key('nt-low'),
          icon: Icons.warning_amber_rounded,
          color: AppColors.warn,
          title: trArgs('Kam qolgan: {n} ta', {'n': o.lowCount}),
        ),
      if (o.outCount == 0 && o.lowCount == 0)
        _tile(icon: Icons.verified_outlined, color: AppColors.ok, title: tr('Qoldiq bo‘yicha ogohlantirish yo‘q')),
      for (final r in low.take(50))
        InkWell(
          key: Key(rowKey(r)),
          // `product_id` yo'q (eski server) — qator bosilmaydi, taxmin qilinmaydi.
          onTap: r.productId == null
              ? null
              : () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => ProductDetailScreen(
                      productId: r.productId!, initialName: r.name, scannerBuilder: widget.scannerBuilder))),
          child: Container(
            constraints: const BoxConstraints(minHeight: kMinTouch),
            padding: const EdgeInsets.symmetric(horizontal: 4),
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
            child: Row(children: [
              Expanded(child: Text(r.name, style: const TextStyle(fontSize: 13.5))),
              Text('${formatMilli(r.qtyMilli, group: true)} / ${formatMilli(r.minMilli, group: true)}',
                  style: TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: r.qtyMilli <= 0 ? AppColors.danger : AppColors.warn)),
              if (r.productId != null) Icon(Icons.chevron_right, size: 18, color: AppColors.muted),
            ]),
          ),
        ),
    ]);
  }

  Widget _tile(
      {Key? key,
      required IconData icon,
      required Color color,
      required String title,
      String? subtitle,
      VoidCallback? onTap}) {
    return Padding(
      key: key,
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.all(12),
            decoration:
                BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(
                width: 38,
                height: 38,
                decoration:
                    BoxDecoration(color: color.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(11)),
                child: Icon(icon, color: color, size: 19),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, height: 1.3)),
                  if (subtitle != null) Text(subtitle, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                ]),
              ),
              if (onTap != null) Icon(Icons.chevron_right, color: AppColors.muted),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Open lots of one expiry bucket in the current branch, most urgent first.
class ExpiringLotsPage extends StatelessWidget {
  /// Creates the page for [kind] (an [ExpiryKind]).
  const ExpiringLotsPage({super.key, required this.kind, required this.title, this.scannerBuilder});

  /// Expiry bucket.
  final String kind;

  /// Title.
  final String title;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  Widget build(BuildContext context) {
    final s = Session.instance;
    final canWo = Perm.allows('stock.writeoff');
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Column(children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(kGutter, 0, kGutter, 4),
          child: Align(alignment: Alignment.centerLeft, child: BranchChip()),
        ),
        Expanded(
          child: ListenableBuilder(
            listenable: s,
            builder: (context, _) => AsyncView<List<BatchRow>>(
              // Filial almashsa — yangi holat (A filial qatorlari B ostida ko'rinmaydi).
              key: ValueKey('exp-${s.currentBranchId}'),
              reloadOn: Api.stockRev,
              load: () => StockApi.expiringLots(branchId: s.currentBranchId, expiry: kind),
              emptyText: tr('Bu guruhda partiya yo‘q'),
              refreshable: true,
              builder: (context, rows) => ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 24),
                itemCount: rows.length,
                itemBuilder: (context, i) {
                  final r = rows[i];
                  return Container(
                    key: Key('nt-lot-${r.id}'),
                    margin: const EdgeInsets.only(bottom: 8),
                    decoration: BoxDecoration(
                      color: r.expired ? AppColors.dangerSoft : AppColors.card,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: r.expired ? AppColors.danger : AppColors.border),
                    ),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(12),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(
                          builder: (_) => ProductDetailScreen(
                              productId: r.productId, initialName: r.product, scannerBuilder: scannerBuilder))),
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
                        child: Row(children: [
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(r.product, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                              const SizedBox(height: 4),
                              Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                                expiryBadge(r.expiryDate, s.businessDate(), expiredFlag: r.expired),
                                Text(
                                  '${r.batchNumber ?? tr('Raqamsiz partiya')} · ${formatMilli(r.remainingMilli, group: true)} ${r.unit}',
                                  style: TextStyle(fontSize: 12.5, color: AppColors.text2),
                                ),
                              ]),
                            ]),
                          ),
                          if (canWo)
                            TextButton(
                              key: Key('nt-wo-${r.id}'),
                              style: TextButton.styleFrom(
                                  foregroundColor: AppColors.danger, minimumSize: const Size(kMinTouch, kMinTouch)),
                              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                                builder: (_) => WriteoffScreen(
                                  initialProduct: StockProduct(
                                      id: r.productId,
                                      name: r.product,
                                      unit: r.unit.isEmpty ? 'dona' : r.unit,
                                      trackLots: true),
                                  initialLotId: r.id,
                                  scannerBuilder: scannerBuilder,
                                ),
                              )),
                              child: Text(tr('Chiqarish')),
                            ),
                        ]),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
        ),
      ]),
    );
  }
}
