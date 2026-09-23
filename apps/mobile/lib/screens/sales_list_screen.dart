import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/money_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'money_payment_sheet.dart';
import 'sales_detail_screen.dart';

/// Payment method labels (kept for other screens that show legacy [SaleRow]s).
Map<String, String> get payLabels => {for (final m in const ['cash', 'card', 'qr', 'credit']) m: paymentMethodLabel(m)};

/// Payment method colours, readable on light and dark palettes.
Map<String, Color> get payColors => AppTheme.current.dark
    ? const {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn}
    : const {'cash': Color(0xFF12915A), 'card': Color(0xFF6D5DD3), 'qr': Color(0xFF0E8F8F), 'credit': Color(0xFFB8730C)};

/// Sales of the CURRENT branch (`GET /sales?branch_id=&period=&q=`,
/// `sotuvlar.view`): period filter, receipt-number search, detail + receipt.
class SalesListScreen extends StatefulWidget {
  /// Creates the screen.
  const SalesListScreen({super.key});

  @override
  State<SalesListScreen> createState() => _SalesListScreenState();
}

class _SalesListScreenState extends State<SalesListScreen> {
  final _view = AsyncViewController();
  final _search = TextEditingController();
  SalesPeriod _period = SalesPeriod.today;
  String _q = '';
  int _limit = 100;
  Timer? _debounce;

  /// Server cap of `GET /sales?limit=`.
  static const int maxLimit = 300;

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _reload() {
    _limit = 100;
    _view.reload();
  }

  void _onQuery(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      if (!mounted || v.trim() == _q) return;
      setState(() => _q = v.trim());
      _reload();
    });
  }

  Future<List<SaleSummary>> _load() => MoneyApi.sales(
        period: _q.isNotEmpty ? SalesPeriod.all : _period,
        q: _q,
        branchId: Session.instance.currentBranchId,
        limit: _limit,
      );

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows('sales.list')) {
      return Scaffold(appBar: AppBar(title: Text(tr('Sotuvlar'))), body: const NoAccessView(action: 'sales.list'));
    }
    return Scaffold(
      appBar: AppBar(title: Text(tr('Sotuvlar'))),
      body: Column(children: [
        const ConnectivityBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Align(alignment: Alignment.centerLeft, child: BranchChip()),
            const SizedBox(height: 6),
            TextField(
              key: const Key('sales-search'),
              controller: _search,
              onChanged: _onQuery,
              keyboardType: TextInputType.text,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: tr('Chek raqami bo‘yicha qidirish'),
                prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 22),
              ),
            ),
            if (_q.isEmpty) ...[
              const SizedBox(height: 10),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(children: [
                  _chip(SalesPeriod.today, tr('Bugun')),
                  _chip(SalesPeriod.week, tr('7 kun')),
                  _chip(SalesPeriod.month, tr('Shu oy')),
                  _chip(SalesPeriod.all, tr('Barchasi')),
                ]),
              ),
            ],
          ]),
        ),
        Expanded(
          child: AsyncView<List<SaleSummary>>(
            controller: _view,
            load: _load,
            reloadOn: Session.instance,
            refreshable: true,
            empty: EmptyState(
              icon: Icons.receipt_long_outlined,
              text: _q.isNotEmpty
                  ? tr('Bu raqamli chek topilmadi')
                  : (_period == SalesPeriod.today ? tr('Bugun hali sotuv yo‘q') : tr('Bu davrda sotuv yo‘q')),
            ),
            builder: (context, rows) => ListView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(kGutter, 0, kGutter, 24),
              itemCount: rows.length + 1,
              itemBuilder: (context, i) {
                if (i == 0) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text(trArgs('{n} ta chek', {'n': rows.length}),
                        key: const Key('sales-count'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                  );
                }
                final s = rows[i - 1];
                final tile = Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      key: Key('sale-${s.id}'),
                      borderRadius: BorderRadius.circular(13),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => SalesDetailScreen(saleId: s.id, receiptNo: s.receiptNo),
                      )),
                      child: saleSummaryTile(s),
                    ),
                  ),
                );
                if (i == rows.length && rows.length >= _limit && _limit < maxLimit) {
                  return Column(children: [
                    tile,
                    SizedBox(
                      height: kMinTouch,
                      child: TextButton(
                        key: const Key('sales-more'),
                        onPressed: () {
                          _limit = maxLimit;
                          _view.reload();
                        },
                        child: Text(tr('Ko‘proq ko‘rsatish')),
                      ),
                    ),
                  ]);
                }
                return tile;
              },
            ),
          ),
        ),
      ]),
    );
  }

  Widget _chip(SalesPeriod p, String label) {
    final on = _period == p;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Semantics(
        selected: on,
        button: true,
        child: InkWell(
          key: Key('period-${p.name}'),
          borderRadius: BorderRadius.circular(10),
          onTap: () {
            if (on) return;
            setState(() => _period = p);
            _reload();
          },
          child: Container(
            constraints: const BoxConstraints(minHeight: kMinTouch, minWidth: kMinTouch),
            padding: const EdgeInsets.symmetric(horizontal: 16),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: on ? AppColors.accent : AppColors.card,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: on ? AppColors.accent : AppColors.border),
            ),
            child: Text(label,
                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: on ? Colors.white : AppColors.text3)),
          ),
        ),
      ),
    );
  }
}

/// One sale row.
Widget saleSummaryTile(SaleSummary s) {
  final col = payColors[s.method] ?? AppColors.muted;
  return Container(
    constraints: const BoxConstraints(minHeight: 64),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
        color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
    child: Row(children: [
      Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(color: col.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(11)),
        child: Icon(Icons.receipt_long, color: col, size: 20),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(s.firstItem.isEmpty ? s.receiptNo : s.firstItem,
              maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(
              [s.receiptNo, dmy(s.at), if (s.cashier.isNotEmpty) s.cashier]
                  .where((e) => e.isNotEmpty)
                  .join(' · '),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      ),
      const SizedBox(width: 8),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(formatCents(s.totalCents), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        Text(paymentMethodLabel(s.method), style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: col)),
      ]),
    ]),
  );
}

/// Legacy tile for a [SaleRow] (analytics "recent sales" card).
Widget saleTile(SaleRow s) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: saleSummaryTile(SaleSummary(
        id: s.id,
        receiptNo: s.receiptNo,
        at: s.at,
        cashier: s.cashier,
        method: s.method,
        itemCountMilli: milliFromNum(s.itemCount),
        firstItem: s.firstItem,
        totalCents: centsFromNum(s.total),
      )),
    );
