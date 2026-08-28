import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'customers_screen.dart';
import 'sales_list_screen.dart';
import 'receiving_home_screen.dart';
import 'notifications_screen.dart';

/// Bosh sahifa — bugun bir qarashda + tez amallar (BILLZ uslubida).
class HomeScreen extends StatefulWidget {
  final void Function(int index)? onTab;
  const HomeScreen({super.key, this.onTab});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Future<Overview>? _ov;
  Future<List<SaleRow>>? _recent;
  Future<List<InvItem>>? _inv;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() {
    final ov = Api.overview('day');
    final rec = Api.sales(limit: 3);
    final inv = Api.inventory();
    setState(() { _ov = ov; _recent = rec; _inv = inv; });
    // Pull-to-refresh indikatori ma'lumot KELGUNCHA aylansin (ilgari darhol yo'qolardi)
    return Future.wait<dynamic>([ov, rec, inv]).then((_) {}).catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final name = (Api.employee?['full_name'] ?? '').toString().split(' ').first;
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => _load(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            children: [
              // Salom + bildirishnoma
              Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('Assalomu alaykum,'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
                    Text(name.isEmpty ? tr('Ega') : name,
                        style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
                  ]),
                ),
                _iconBtn(Icons.notifications_outlined,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const NotificationsScreen()))),
              ]),
              const SizedBox(height: 18),

              // Bugungi savdo (hero)
              FutureBuilder<Overview>(
                future: _ov,
                builder: (context, snap) {
                  final ov = snap.data;
                  return Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      // Mavzuga mos hero: accent gradient + doim OQ matn (har 9 mavzuda o'qiladi)
                      gradient: LinearGradient(
                        begin: Alignment.topLeft, end: Alignment.bottomRight,
                        colors: [AppColors.accent, Color.lerp(AppColors.accent, Colors.black, 0.35)!],
                      ),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: AppColors.accentBorder),
                    ),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(tr('Bugungi savdo'), style: const TextStyle(fontSize: 13, color: Color(0xD9FFFFFF))),
                      const SizedBox(height: 6),
                      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                        Text(ov == null ? '—' : money(ov.sales),
                            style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800, letterSpacing: -0.5, color: Colors.white)),
                        const SizedBox(width: 10),
                        if (ov?.dSales != null) _deltaChip(ov!.dSales!),
                      ]),
                    ]),
                  );
                },
              ),
              const SizedBox(height: 18),

              // Tez amallar
              Row(children: [
                _quick(Icons.add_box_rounded, tr('Yangi\nqabul'), AppColors.ok,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ReceivingHomeScreen()))),
                _quick(Icons.receipt_long, tr('Sotuvlar'), AppColors.accentStrong,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SalesListScreen()))),
                _quick(Icons.warehouse, tr('Ombor'), const Color(0xFF4EA8DE), () => widget.onTab?.call(2)),
                _quick(Icons.account_balance_wallet, tr('Qarzdorlar'), AppColors.warn,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const CustomersScreen(onlyDebt: true)))),
              ]),
              const SizedBox(height: 22),

              // Diqqat
              FutureBuilder<List<InvItem>>(
                future: _inv,
                builder: (context, snap) {
                  final items = snap.data ?? [];
                  final today = DateTime.now();
                  final t0 = DateTime(today.year, today.month, today.day);
                  int low = 0, out = 0, exp = 0;
                  for (final it in items) {
                    final s = it.status(t0);
                    if (s == 2) low++;
                    if (s == 3) out++;
                    if (s == 1 || s == 4) exp++; // yaqin ham, O'TGAN (4) ham — ilgari 4 sanalmasdi
                  }
                  if (items.isEmpty) return const SizedBox.shrink();
                  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      const Icon(Icons.warning_amber_rounded, size: 16, color: AppColors.warn),
                      const SizedBox(width: 8),
                      Text(tr('Diqqat'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                    ]),
                    const SizedBox(height: 12),
                    Row(children: [
                      _attn(low, tr('kam qolgan'), AppColors.warn),
                      const SizedBox(width: 10),
                      _attn(out, tr('tugagan'), AppColors.danger),
                      const SizedBox(width: 10),
                      _attn(exp, tr('muddati yaqin/o‘tgan'), AppColors.warn),
                    ]),
                    const SizedBox(height: 22),
                  ]);
                },
              ),

              // So'nggi sotuvlar
              Row(children: [
                Text(tr('So‘nggi sotuvlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                const Spacer(),
                GestureDetector(
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SalesListScreen())),
                  child: Text(tr('Barchasi'), style: TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600)),
                ),
              ]),
              const SizedBox(height: 10),
              FutureBuilder<List<SaleRow>>(
                future: _recent,
                builder: (context, snap) {
                  final rows = snap.data ?? [];
                  if (rows.isEmpty) {
                    return Padding(padding: const EdgeInsets.symmetric(vertical: 16),
                        child: Text(tr('Bugun sotuv yo‘q'), style: TextStyle(color: AppColors.muted)));
                  }
                  return AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(children: [
                      for (int i = 0; i < rows.length; i++) _saleRow(rows[i], i < rows.length - 1),
                    ]),
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _iconBtn(IconData ic, VoidCallback onTap) => GestureDetector(
        onTap: onTap,
        child: Container(
          width: 44, height: 44,
          decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.border)),
          child: Icon(ic, color: AppColors.accentStrong, size: 22),
        ),
      );

  Widget _deltaChip(double d) {
    final up = d >= 0;
    final c = up ? AppColors.ok : AppColors.danger;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(8)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(up ? Icons.arrow_upward : Icons.arrow_downward, size: 12, color: c),
        const SizedBox(width: 3),
        Text('${d.abs().toStringAsFixed(1)}%', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: c)),
      ]),
    );
  }

  Widget _quick(IconData ic, String label, Color c, VoidCallback onTap) => Expanded(
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 4),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
            decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(15), border: Border.all(color: AppColors.border)),
            child: Column(children: [
              Container(
                width: 42, height: 42,
                decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
                child: Icon(ic, color: c, size: 20),
              ),
              const SizedBox(height: 8),
              Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppColors.text3, height: 1.2)),
            ]),
          ),
        ),
      );

  Widget _attn(int n, String label, Color c) => Expanded(
        child: Container(
          padding: const EdgeInsets.all(13),
          decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14),
              border: Border.all(color: n > 0 ? c.withValues(alpha: 0.35) : AppColors.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$n', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: n > 0 ? c : AppColors.text)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: 11, color: AppColors.muted)),
          ]),
        ),
      );

  Widget _saleRow(SaleRow s, bool border) => Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(s.receiptNo, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text('${hm(s.at)} · ${s.cashier}', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
            ]),
          ),
          Text(money(s.total), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        ]),
      );
}
