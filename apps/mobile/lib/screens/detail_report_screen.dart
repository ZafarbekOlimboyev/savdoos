import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Batafsil: qaytarish/bekor xulosasi + tovarlar ABC analizi.
class DetailReportScreen extends StatefulWidget {
  const DetailReportScreen({super.key});
  @override
  State<DetailReportScreen> createState() => _DetailReportScreenState();
}

class _DetailReportScreenState extends State<DetailReportScreen> {
  Future<ReportDetail>? _future;
  String _cls = 'A';

  @override
  void initState() {
    super.initState();
    _future = Api.reportDetail('month');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Batafsil'))),
      body: FutureBuilder<ReportDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final d = snap.data!;
          final rows = d.abc.where((a) => a.cls == _cls).toList();
          return RefreshIndicator(
            onRefresh: () async => setState(() { _future = Api.reportDetail('month'); }),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Qaytarish / bekor
                AppCard(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Container(width: 38, height: 38, decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(11)), child: const Icon(Icons.undo, color: AppColors.danger, size: 19)),
                      const SizedBox(width: 10),
                      Text(tr('Qaytarish · bekor cheklar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                    ]),
                    const SizedBox(height: 14),
                    Row(children: [
                      _stat('${d.retCount}', tr('qaytarilgan'), AppColors.text),
                      _stat('−${money(d.retSum)}', tr('summa'), AppColors.danger),
                      _stat('${d.voided}', tr('bekor chek'), AppColors.warn),
                    ]),
                  ]),
                ),
                const SizedBox(height: 20),
                // ABC
                Text(tr('Tovarlar · ABC analiz'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                Row(children: ['A', 'B', 'C'].map((k) {
                  final on = _cls == k;
                  return Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => _cls = k),
                      child: Container(
                        margin: EdgeInsets.only(right: k != 'C' ? 8 : 0),
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        decoration: BoxDecoration(
                          color: on ? AppColors.accentSoft : AppColors.card,
                          borderRadius: BorderRadius.circular(11),
                          border: Border.all(color: on ? AppColors.accent : AppColors.border, width: on ? 1.5 : 1),
                        ),
                        child: Center(child: Text('$k-klass', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: on ? AppColors.accentStrong : AppColors.muted))),
                      ),
                    ),
                  );
                }).toList()),
                if (_cls == 'A') ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
                    decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(11), border: Border.all(color: AppColors.ok.withValues(alpha: 0.25))),
                    child: Row(children: [
                      const Icon(Icons.star, size: 15, color: AppColors.ok),
                      const SizedBox(width: 8),
                      Expanded(child: Text('A-klass: eng ko‘p foyda keltiruvchi · foydaning ${d.aShare.toStringAsFixed(0)}%', style: const TextStyle(fontSize: 12, color: AppColors.ok, fontWeight: FontWeight.w600))),
                    ]),
                  ),
                ],
                const SizedBox(height: 12),
                if (rows.isEmpty)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 24), child: Center(child: Text(tr('Bu klassda tovar yo‘q'), style: TextStyle(color: AppColors.muted))))
                else
                  AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(children: [
                      for (int i = 0; i < rows.length; i++) _abcRow(rows[i], i < rows.length - 1),
                    ]),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _stat(String v, String l, Color c) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(v, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: c)),
          const SizedBox(height: 2),
          Text(l, style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ]),
      );

  Widget _abcRow(AbcRow a, bool border) {
    final col = a.cls == 'A' ? AppColors.ok : (a.cls == 'B' ? AppColors.warn : AppColors.muted);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
      child: Row(children: [
        Container(width: 30, height: 30, decoration: BoxDecoration(color: col.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(8)), child: Center(child: Text(a.cls, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: col)))),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(a.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text('${qtyStr(a.units)} dona · ulush ${a.share.toStringAsFixed(1)}%', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        Text(money(a.profit), style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: col)),
      ]),
    );
  }
}
