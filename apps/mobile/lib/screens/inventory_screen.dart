import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'barcode_scan_screen.dart';
import 'product_detail_screen.dart';

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
  final _searchC = TextEditingController();

  @override
  void initState() {
    super.initState();
    _future = Api.inventory();
  }

  @override
  void dispose() {
    _searchC.dispose();
    super.dispose();
  }

  void _reload() => setState(() => _future = Api.inventory());

  // Shtrix-kodni skanerlab mahsulotni topish: topilsa batafsil oyna, topilmasa —
  // kodni qidiruvga yozib qo'yamiz (nom bilan izlash uchun).
  Future<void> _scanFind() async {
    final code = await Navigator.of(context).push<String>(
        MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
    if (code == null || code.isEmpty || !mounted) return;
    try {
      final hit = await Api.productByBarcode(code);
      if (!mounted) return;
      if (hit != null) {
        Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ProductDetailScreen(productId: hit.id, initialName: hit.name)));
      } else {
        setState(() { _q = code; _searchC.text = code; });
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${tr('Bu kod bo‘yicha topilmadi')}: $code')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

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
                    controller: _searchC,
                    onChanged: (v) => setState(() => _q = v),
                    decoration: InputDecoration(
                      hintText: tr('Mahsulot qidirish...'),
                      prefixIcon: const Icon(Icons.search, color: AppColors.muted, size: 20),
                      // Shtrix-kod skaneri — istalgan tovarni skanerlab topish
                      suffixIcon: IconButton(
                        icon: const Icon(Icons.qr_code_scanner, color: AppColors.accentStrong, size: 22),
                        tooltip: tr('Skanerlash'),
                        onPressed: _scanFind,
                      ),
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
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ProductDetailScreen(productId: it.id, initialName: it.name)));
  }
}

