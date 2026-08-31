import 'package:flutter/material.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

class ReceivingSuccessScreen extends StatelessWidget {
  final Map<String, dynamic> result;
  const ReceivingSuccessScreen({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final results = (result['results'] as List?) ?? [];
    final types = result['total_types'] ?? results.length;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 40, 20, 16),
                children: [
                  Center(
                    child: Container(
                      width: 76, height: 76,
                      decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(24)),
                      child: const Icon(Icons.check_circle, color: AppColors.ok, size: 44),
                    ),
                  ),
                  const SizedBox(height: 18),
                  Center(child: Text(tr('Mahsulotlar omborga qo‘shildi'),
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800), textAlign: TextAlign.center)),
                  const SizedBox(height: 6),
                  Center(child: Text(tr('{n} ta mahsulot muvaffaqiyatli qabul qilindi').replaceFirst('{n}', '$types'),
                      style: TextStyle(color: AppColors.muted, fontSize: 13))),
                  const SizedBox(height: 26),
                  AppCard(
                    padding: const EdgeInsets.all(6),
                    child: Column(
                      children: results.map<Widget>((r) {
                        final m = r as Map;
                        return Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                          child: Row(children: [
                            Expanded(
                              child: Text(m['product']?.toString() ?? '',
                                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                            ),
                            Text('${qtyStr(_n(m['old_qty']))}', style: TextStyle(color: AppColors.muted, fontSize: 13)),
                            Padding(
                              padding: EdgeInsets.symmetric(horizontal: 6),
                              child: Icon(Icons.arrow_forward, size: 14, color: AppColors.faint),
                            ),
                            Text('${qtyStr(_n(m['new_qty']))}',
                                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppColors.ok)),
                            const SizedBox(width: 6),
                            Text('(+${qtyStr(_n(m['added']))})', style: const TextStyle(color: AppColors.ok, fontSize: 12)),
                          ]),
                        );
                      }).toList(),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(20, 8, 20, 12 + MediaQuery.of(context).padding.bottom),
              child: Column(children: [
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: Text(tr('Yangi qabul qilish')),
                  ),
                ),
                const SizedBox(height: 10),
                TextButton(
                  // Bosh sahifagacha qaytamiz (ilgari "Yangi qabul" bilan bir xil ish qilardi)
                  onPressed: () => Navigator.of(context).popUntil((r) => r.isFirst),
                  child: Text(tr('Bosh sahifaga'), style: TextStyle(color: AppColors.text3)),
                ),
              ]),
            ),
          ],
        ),
      ),
    );
  }

  double _n(dynamic v) => v == null ? 0 : (v is num ? v.toDouble() : double.tryParse(v.toString()) ?? 0);
}
