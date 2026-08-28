import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'sales_detail_screen.dart';

// tr() bilan — ru/ky tillarida ham to'g'ri chiqadi (ilgari doim o'zbekcha edi)
Map<String, String> get payLabels =>
    {'cash': tr('Naqd'), 'card': tr('Karta'), 'qr': 'QR', 'credit': tr('Qarz')};
// Yorug' mavzularda to'qroq, tungilarida ochroq tuslar — matn/ikonka o'qilsin.
Map<String, Color> get payColors => AppTheme.current.dark
    ? const {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn}
    : const {'cash': Color(0xFF12915A), 'card': Color(0xFF6D5DD3), 'qr': Color(0xFF0E8F8F), 'credit': Color(0xFFB8730C)};

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
          // Xato/bo'sh holat ham RefreshIndicator ICHIDA — pastga tortib yangilab bo'ladi
          // (ilgari xato chiqsa yangilashning iloji yo'q edi)
          final rows = snap.data ?? [];
          Widget child;
          if (snap.hasError) {
            child = ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
              SizedBox(height: 200, child: Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)))),
            ]);
          } else if (rows.isEmpty) {
            child = ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
              SizedBox(height: 200, child: Center(child: Text(tr('Sotuvlar yo‘q'), style: TextStyle(color: AppColors.muted)))),
            ]);
          } else {
            child = ListView.builder(
              padding: const EdgeInsets.all(14),
              itemCount: rows.length,
              itemBuilder: (context, i) => GestureDetector(
                onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SalesDetailScreen(sale: rows[i]))),
                child: saleTile(rows[i]),
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => setState(() { _future = Api.sales(limit: 100); }),
            child: child,
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
