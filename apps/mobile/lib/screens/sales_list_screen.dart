import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'sales_detail_screen.dart';

const payLabels = {'cash': 'Naqd', 'card': 'Karta', 'qr': 'QR', 'credit': 'Qarz'};
const payColors = {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn};

class SalesListScreen extends StatefulWidget {
  const SalesListScreen({super.key});
  @override
  State<SalesListScreen> createState() => _SalesListScreenState();
}

class _SalesListScreenState extends State<SalesListScreen> {
  Future<List<SaleRow>>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.sales(limit: 100);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('So‘nggi sotuvlar'))),
      body: FutureBuilder<List<SaleRow>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final rows = snap.data ?? [];
          if (rows.isEmpty) {
            return Center(child: Text(tr('Sotuvlar yo‘q'), style: TextStyle(color: AppColors.muted)));
          }
          return RefreshIndicator(
            onRefresh: () async => setState(() => _future = Api.sales(limit: 100)),
            child: ListView.builder(
              padding: const EdgeInsets.all(14),
              itemCount: rows.length,
              itemBuilder: (context, i) => GestureDetector(
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SalesDetailScreen(sale: rows[i]))),
                child: saleTile(rows[i]),
              ),
            ),
          );
        },
      ),
    );
  }
}

Widget saleTile(SaleRow s) {
  final col = payColors[s.method] ?? AppColors.muted;
  return Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.all(13),
    decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
    child: Row(children: [
      Container(
        width: 40, height: 40,
        decoration: BoxDecoration(color: col.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(11)),
        child: Icon(Icons.receipt_long, color: col, size: 20),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(s.firstItem.isEmpty ? s.receiptNo : s.firstItem,
              maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text('${hm(s.at)} · ${s.cashier} · ${qtyStr(s.itemCount)} dona',
              style: TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      ),
      const SizedBox(width: 8),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(money(s.total), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        Text(payLabels[s.method] ?? s.method, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: col)),
      ]),
    ]),
  );
}
