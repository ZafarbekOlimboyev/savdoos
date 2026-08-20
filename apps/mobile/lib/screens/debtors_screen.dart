import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../theme.dart';

class DebtorsScreen extends StatefulWidget {
  const DebtorsScreen({super.key});
  @override
  State<DebtorsScreen> createState() => _DebtorsScreenState();
}

class _DebtorsScreenState extends State<DebtorsScreen> {
  Future<List<Debtor>>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.debtors();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Qarzdorlar')),
      body: FutureBuilder<List<Debtor>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: const TextStyle(color: AppColors.muted)));
          }
          final rows = (snap.data ?? [])..sort((a, b) => b.balance.compareTo(a.balance));
          if (rows.isEmpty) {
            return const Center(child: Text('Qarzdor yo‘q 👍', style: TextStyle(color: AppColors.muted)));
          }
          final total = rows.fold<double>(0, (a, d) => a + d.balance);
          return Column(children: [
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(14, 14, 14, 4),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: AppColors.warnSoft, borderRadius: BorderRadius.circular(14)),
              child: Row(children: [
                const Text('Umumiy qarz', style: TextStyle(fontSize: 13.5, color: AppColors.text2)),
                const Spacer(),
                Text(money(total), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppColors.warn)),
              ]),
            ),
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.all(14),
                itemCount: rows.length,
                itemBuilder: (context, i) {
                  final d = rows[i];
                  return Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
                    child: Row(children: [
                      CircleAvatar(radius: 18, backgroundColor: AppColors.warnSoft,
                          child: Text(d.name.isEmpty ? '?' : d.name[0], style: const TextStyle(color: AppColors.warn, fontWeight: FontWeight.w700))),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(d.name, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
                          if (d.phone != null && d.phone!.isNotEmpty) ...[
                            const SizedBox(height: 2),
                            Text(d.phone!, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                          ],
                        ]),
                      ),
                      Text(money(d.balance), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: AppColors.warn)),
                    ]),
                  );
                },
              ),
            ),
          ]);
        },
      ),
    );
  }
}
