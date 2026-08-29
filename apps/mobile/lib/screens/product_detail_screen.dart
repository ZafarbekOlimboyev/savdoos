import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Mahsulotning to'liq oynasi: narxlar (kelish/sotish/foyda), qoldiq,
/// sotuv statistikasi (7/30 kun) va so'nggi harakatlar.
class ProductDetailScreen extends StatefulWidget {
  final String productId;
  final String? initialName; // header darrov ko'rinishi uchun (ixtiyoriy)
  const ProductDetailScreen({super.key, required this.productId, this.initialName});
  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  Future<ProductDetail>? _future;

  @override
  void initState() {
    super.initState();
    _future = Api.productDetail(widget.productId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.initialName ?? tr('Mahsulot'), maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: FutureBuilder<ProductDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)),
            ));
          }
          final d = snap.data!;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            children: [
              // Nomi + belgilar
              Text(d.name, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                if (d.weighted) _tag(tr('Tarozi'), AppColors.accentStrong),
                if (d.pluCode != null && d.pluCode!.isNotEmpty) _tag('PLU ${d.pluCode}', AppColors.muted),
                for (final b in d.barcodes.take(3)) _tag(b, AppColors.muted),
              ]),
              const SizedBox(height: 18),

              // Narxlar
              Text(tr('Narxlar'), style: _section),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: _card(tr('Kelish narxi'), money(d.buyPrice), AppColors.text)),
                const SizedBox(width: 10),
                Expanded(child: _card(tr('Sotish narxi'), money(d.sellPrice), AppColors.accentStrong)),
              ]),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: _card(tr('Birlik foyda'), money(d.profitUnit),
                    d.profitUnit >= 0 ? AppColors.ok : AppColors.danger)),
                const SizedBox(width: 10),
                // Margin: ko'pi bilan 1 kasr, ".0" tashlanadi (31.2% / 25%)
                Expanded(child: _card(tr('Margin'), '${d.marginPct.toStringAsFixed(1).replaceFirst(RegExp(r'\.0$'), '').replaceFirst(RegExp(r'^-0$'), '0')}%',
                    d.profitUnit >= 0 ? AppColors.ok : AppColors.danger)),
              ]),
              const SizedBox(height: 18),

              // Qoldiq
              Text(tr('Ombor'), style: _section),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: _card(tr('Qoldiq'), '${qtyStr(d.stock)} ${d.unit}',
                    d.stock <= 0 ? AppColors.danger : (d.stock <= d.minStock && d.minStock > 0 ? AppColors.warn : AppColors.text))),
                const SizedBox(width: 10),
                Expanded(child: _card(tr('Ombor qiymati'), money(d.stockValue), AppColors.text)),
              ]),
              const SizedBox(height: 18),

              // Sotuv statistikasi
              Text(tr('Sotuv statistikasi'), style: _section),
              const SizedBox(height: 8),
              _statBlock(tr('So‘nggi 30 kun'), d.sales30d, d.unit),
              const SizedBox(height: 10),
              _statBlock(tr('So‘nggi 7 kun'), d.sales7d, d.unit),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: _card(tr('Bu oy kirim'), '+${qtyStr(d.monthIn)}', AppColors.ok)),
                const SizedBox(width: 10),
                Expanded(child: _card(tr('Bu oy chiqim'), '${d.monthOut > 0 ? '−' : ''}${qtyStr(d.monthOut)}', AppColors.danger)),
              ]),
              if (d.lastSoldAt != null) ...[
                const SizedBox(height: 10),
                Text('${tr('Oxirgi sotilgan')}: ${dmy(d.lastSoldAt)}',
                    style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
              ],
              const SizedBox(height: 20),

              // So'nggi harakatlar
              Text(tr('So‘nggi harakatlar'), style: _section),
              const SizedBox(height: 8),
              FutureBuilder<List<MoveRow>>(
                future: Api.movements(productId: widget.productId, limit: 30),
                builder: (context, ms) {
                  if (ms.connectionState == ConnectionState.waiting) {
                    return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
                  }
                  final rows = ms.data ?? [];
                  if (rows.isEmpty) return Text(tr('Harakat yo‘q'), style: TextStyle(color: AppColors.muted));
                  return Column(children: rows.map(_move).toList());
                },
              ),
              const SizedBox(height: 16),
              Text('${tr('Qo‘shgan')}: ${d.createdByName}', style: TextStyle(fontSize: 11.5, color: AppColors.faint)),
            ],
          );
        },
      ),
    );
  }

  Widget _statBlock(String title, SalesStat s, String unit) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: _mini(tr('Sotildi'), '${qtyStr(s.qty)} $unit')),
          Expanded(child: _mini(tr('Tushum'), money(s.revenue))),
          Expanded(child: _mini(tr('Foyda'), money(s.profit),
              color: s.profit >= 0 ? AppColors.ok : AppColors.danger)),
        ]),
      ]),
    );
  }

  Widget _mini(String l, String v, {Color? color}) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: TextStyle(fontSize: 11, color: AppColors.muted)),
        const SizedBox(height: 3),
        Text(v, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: color ?? AppColors.text)),
      ]);

  Widget _card(String l, String v, Color c) => Container(
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(l, style: TextStyle(fontSize: 12, color: AppColors.muted)),
          const SizedBox(height: 6),
          Text(v, style: TextStyle(fontSize: 16.5, fontWeight: FontWeight.w800, color: c)),
        ]),
      );

  Widget _tag(String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(6)),
        child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: c)),
      );

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
        Text(hm(m.at), style: TextStyle(fontSize: 11.5, color: AppColors.faint)),
      ]),
    );
  }

  static const _section = TextStyle(fontSize: 14, fontWeight: FontWeight.w700);
}
