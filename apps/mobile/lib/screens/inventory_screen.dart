import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Ombor: mahsulotlar, qoldiq, ombor qiymati, diqqat talab qiladigan (kam/tugagan/muddat).
class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key});
  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen> {
  Future<List<InvItem>>? _future;
  int _filter = 0; // 0=hammasi 2=kam 3=tugagan 1=muddat-yaqin 4=muddat-o'tgan
  String _q = '';

  @override
  void initState() {
    super.initState();
    _future = Api.inventory();
  }

  void _reload() => setState(() => _future = Api.inventory());

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => _reload(),
          child: FutureBuilder<List<InvItem>>(
            future: _future,
            builder: (context, snap) {
              if (snap.connectionState == ConnectionState.waiting) {
                return ListView(children: const [SizedBox(height: 200), Center(child: CircularProgressIndicator())]);
              }
              if (snap.hasError) {
                return ListView(children: [
                  const SizedBox(height: 120),
                  Center(child: Text(snap.error.toString(), style: const TextStyle(color: AppColors.muted))),
                ]);
              }
              final items = snap.data ?? [];
              final today = DateTime.now();
              final today0 = DateTime(today.year, today.month, today.day);
              int low = 0, out = 0, expSoon = 0, expired = 0;
              double value = 0;
              for (final it in items) {
                value += it.stockValue;
                final s = it.status(today0);
                if (s == 2) low++;
                if (s == 3) out++;
                if (s == 1) expSoon++;
                if (s == 4) expired++;
              }
              final ql = _q.toLowerCase();
              final list = items.where((it) {
                if (ql.isNotEmpty && !it.name.toLowerCase().contains(ql)) return false;
                if (_filter == 0) return true;
                return it.status(today0) == _filter;
              }).toList()
                ..sort((a, b) => a.status(today0) == b.status(today0)
                    ? a.name.compareTo(b.name)
                    : b.status(today0).compareTo(a.status(today0)));

              return ListView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                children: [
                  Text(tr('Ombor'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 16),
                  Row(children: [
                    Expanded(child: _kpi(tr('Mahsulotlar'), items.length.toString(), AppColors.text)),
                    const SizedBox(width: 12),
                    Expanded(child: _kpi(tr('Ombor qiymati'), short(value), AppColors.accentStrong)),
                  ]),
                  const SizedBox(height: 12),
                  Row(children: [
                    Expanded(child: _kpi(tr('Kam qolgan'), low.toString(), low > 0 ? AppColors.warn : AppColors.text)),
                    const SizedBox(width: 12),
                    Expanded(child: _kpi(tr('Tugagan'), out.toString(), out > 0 ? AppColors.danger : AppColors.text)),
                  ]),
                  const SizedBox(height: 18),
                  // Filtrlar
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(children: [
                      _chip(tr('Hammasi'), 0, items.length),
                      _chip(tr('Kam qolgan'), 2, low),
                      _chip(tr('Tugagan'), 3, out),
                      _chip(tr('Muddati yaqin'), 1, expSoon),
                      _chip(tr('Muddati o‘tgan'), 4, expired),
                    ]),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    onChanged: (v) => setState(() => _q = v),
                    decoration: InputDecoration(
                      hintText: tr('Mahsulot qidirish...'),
                      prefixIcon: const Icon(Icons.search, color: AppColors.muted, size: 20),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  if (list.isEmpty)
                    Padding(padding: const EdgeInsets.symmetric(vertical: 28),
                        child: Center(child: Text(tr('Topilmadi'), style: const TextStyle(color: AppColors.muted))))
                  else
                    ...list.map((it) => _row(it, today0)),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _kpi(String label, String value, Color color) => AppCard(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
          const SizedBox(height: 7),
          Text(value, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: color)),
        ]),
      );

  Widget _chip(String label, int f, int count) {
    final on = _filter == f;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: GestureDetector(
        onTap: () => setState(() => _filter = f),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
          decoration: BoxDecoration(
            color: on ? AppColors.accentSoft : AppColors.card,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: on ? AppColors.accentBorder : AppColors.border),
          ),
          child: Text('$label${count > 0 ? '  $count' : ''}',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600,
                  color: on ? AppColors.accentStrong : AppColors.text3)),
        ),
      ),
    );
  }

  Widget _row(InvItem it, DateTime today0) {
    final s = it.status(today0);
    final (col, badge) = switch (s) {
      3 => (AppColors.danger, tr('Tugagan')),
      4 => (AppColors.danger, tr('Muddati o‘tgan')),
      2 => (AppColors.warn, tr('Kam qoldi')),
      1 => (AppColors.warn, tr('Muddati yaqin')),
      _ => (AppColors.ok, ''),
    };
    return GestureDetector(
      onTap: () => _showDetail(it),
      child: Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(it.name, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 3),
            Row(children: [
              Text('${money(it.sellPrice)} · ${it.unit}',
                  style: const TextStyle(fontSize: 12, color: AppColors.muted)),
              if (badge.isNotEmpty) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(color: col.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
                  child: Text(badge, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: col)),
                ),
              ],
            ]),
          ]),
        ),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(qtyStr(it.stock), style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: s == 0 ? AppColors.text : col)),
          Text('min ${qtyStr(it.minStock)}', style: const TextStyle(fontSize: 11, color: AppColors.faint)),
        ]),
      ]),
      ),
    );
  }

  void _showDetail(InvItem it) {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _ProductSheet(item: it),
    );
  }
}

class _ProductSheet extends StatelessWidget {
  final InvItem item;
  const _ProductSheet({required this.item});

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      maxChildSize: 0.9,
      minChildSize: 0.4,
      builder: (context, controller) => ListView(
        controller: controller,
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        children: [
          Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
          const SizedBox(height: 16),
          Text(item.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 14),
          Row(children: [
            Expanded(child: _stat(tr('Qoldiq'), '${qtyStr(item.stock)} ${item.unit}')),
            Expanded(child: _stat(tr('Ombor qiymati'), money(item.stockValue))),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(child: _stat(tr('Sotish narxi'), money(item.sellPrice))),
            Expanded(child: _stat(tr('Tannarx'), money(item.buyPrice))),
          ]),
          const SizedBox(height: 20),
          Text(tr('So‘nggi harakatlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          FutureBuilder<List<MoveRow>>(
            future: Api.movements(productId: item.id, limit: 30),
            builder: (context, snap) {
              if (snap.connectionState == ConnectionState.waiting) {
                return const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator()));
              }
              final rows = snap.data ?? [];
              if (rows.isEmpty) return Text(tr('Harakat yo‘q'), style: const TextStyle(color: AppColors.muted));
              return Column(children: rows.map(_move).toList());
            },
          ),
        ],
      ),
    );
  }

  Widget _stat(String l, String v) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        const SizedBox(height: 3),
        Text(v, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
      ]);

  Widget _move(MoveRow m) {
    final incoming = m.direction == 'in';
    final col = incoming ? AppColors.ok : AppColors.danger;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 9),
      child: Row(children: [
        Icon(incoming ? Icons.south_west : Icons.north_east, size: 16, color: col),
        const SizedBox(width: 10),
        Expanded(child: Text(m.type, style: const TextStyle(fontSize: 13.5))),
        Text('${incoming ? '+' : '−'}${qtyStr(m.qty)}',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: col)),
        const SizedBox(width: 10),
        Text(hm(m.at), style: const TextStyle(fontSize: 11.5, color: AppColors.faint)),
      ]),
    );
  }
}
