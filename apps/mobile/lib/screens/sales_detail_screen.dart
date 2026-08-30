import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'sales_list_screen.dart' show payLabels, payColors;

class SalesDetailScreen extends StatefulWidget {
  final SaleRow sale;
  const SalesDetailScreen({super.key, required this.sale});
  @override
  State<SalesDetailScreen> createState() => _SalesDetailScreenState();
}

class _SalesDetailScreenState extends State<SalesDetailScreen> {
  Future<SaleDetail>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.saleDetail(widget.sale.id);
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.sale;
    final payCol = payColors[s.method] ?? AppColors.muted;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(s.receiptNo, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          Text('${hm(s.at)} · ${s.cashier}', style: TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w400)),
        ]),
      ),
      body: FutureBuilder<SaleDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final d = snap.data!;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              AppCard(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(children: [
                  for (int i = 0; i < d.items.length; i++) _item(d.items[i], i < d.items.length - 1),
                ]),
              ),
              const SizedBox(height: 14),
              AppCard(
                child: Column(children: [
                  _sumRow(tr('Oraliq'), money(d.subtotal), false),
                  if (d.discountTotal > 0) ...[
                    const SizedBox(height: 9),
                    _sumRow(tr('Chegirma'), '−${money(d.discountTotal)}', false),
                  ],
                  Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Divider(color: AppColors.border, height: 1)),
                  _sumRow(tr('Jami'), money(d.total), true),
                  const SizedBox(height: 12),
                  Row(children: [
                    Container(width: 9, height: 9, decoration: BoxDecoration(shape: BoxShape.circle, color: payCol)),
                    const SizedBox(width: 8),
                    Text('${payLabels[s.method] ?? s.method} ${tr('to‘lov')}', style: TextStyle(fontSize: 12.5, color: AppColors.text3)),
                  ]),
                ]),
              ),
            ],
          );
        },
      ),
      bottomNavigationBar: Container(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
        color: AppColors.bg,
        child: SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Qaytarish — tez orada')))),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.danger,
              side: const BorderSide(color: AppColors.danger, width: 1.5),
              backgroundColor: AppColors.dangerSoft,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            icon: const Icon(Icons.undo, size: 19),
            label: Text(tr('Qaytarish'), style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
        ),
      ),
    );
  }

  Widget _item(SaleLine i, bool border) => Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(i.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text('${qtyStr(i.qty)} × ${money(i.unitPrice)}', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
            ]),
          ),
          Text(money(i.lineTotal), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        ]),
      );

  Widget _sumRow(String l, String v, bool big) => Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(l, style: TextStyle(fontSize: big ? 15 : 13, fontWeight: big ? FontWeight.w700 : FontWeight.w400, color: big ? AppColors.text : AppColors.muted)),
          Text(v, style: TextStyle(fontSize: big ? 20 : 13, fontWeight: big ? FontWeight.w800 : FontWeight.w500, color: big ? AppColors.text : AppColors.text3)),
        ],
      );
}
