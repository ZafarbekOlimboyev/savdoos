import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Bildirishnomalar — ombor holatidan hosil qilinadi (kam/tugagan/muddat).
/// Haqiqiy push (Firebase) alohida; bu — ilova ichidagi ro'yxat.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});
  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  Future<List<InvItem>>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.inventory();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Bildirishnomalar'))),
      body: FutureBuilder<List<InvItem>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          final items = snap.data ?? [];
          final today = DateTime.now();
          final t0 = DateTime(today.year, today.month, today.day);
          final alerts = items.where((it) => it.status(t0) != 0).toList()
            ..sort((a, b) => b.status(t0).compareTo(a.status(t0)));
          if (alerts.isEmpty) {
            return Center(child: Text(tr('Bildirishnoma yo‘q 👍'), style: const TextStyle(color: AppColors.muted)));
          }
          return RefreshIndicator(
            onRefresh: () async => setState(() => _future = Api.inventory()),
            child: ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: alerts.length,
              itemBuilder: (context, i) => _row(alerts[i], t0),
            ),
          );
        },
      ),
    );
  }

  Widget _row(InvItem it, DateTime t0) {
    final s = it.status(t0);
    final (ic, col, text) = switch (s) {
      3 => (Icons.remove_shopping_cart, AppColors.danger, '${it.name} — tugadi'),
      4 => (Icons.event_busy, AppColors.danger, '${it.name} — muddati o‘tgan'),
      2 => (Icons.warning_amber_rounded, AppColors.warn, '${it.name} — kam qoldi (${qtyStr(it.stock)} ${it.unit})'),
      _ => (Icons.schedule, AppColors.warn, '${it.name} — muddati yaqin'),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
      child: Row(children: [
        Container(
          width: 38, height: 38,
          decoration: BoxDecoration(color: col.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(11)),
          child: Icon(ic, color: col, size: 19),
        ),
        const SizedBox(width: 12),
        Expanded(child: Text(text, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w500, height: 1.3))),
      ]),
    );
  }
}
