import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../theme.dart';

/// Do'kon egasi uchun mobil analitika (BILLZ uslubida): savdo/foyda, dinamika,
/// to'lov usullari, top mahsulotlar. Sodda — keraksiz widget yo'q.
class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  String _period = 'week';
  Future<Overview>? _future;
  Future<List<CatRow>>? _cats;
  Future<DebtInfo>? _debt;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => setState(() {
        _future = Api.overview(_period);
        _cats = Api.categories(_period);
        _debt = Api.debt();
      });

  void _setPeriod(String p) {
    if (p == _period) return;
    setState(() {
      _period = p;
      _future = Api.overview(p);
      _cats = Api.categories(p);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            children: [
              Row(
                children: [
                  const Text('Analitika', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const Spacer(),
                  Text(Api.employee?['full_name']?.toString() ?? '',
                      style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
                ],
              ),
              const SizedBox(height: 14),
              _PeriodBar(period: _period, onChange: _setPeriod),
              const SizedBox(height: 16),
              FutureBuilder<Overview>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState == ConnectionState.waiting) {
                    return const Padding(
                      padding: EdgeInsets.only(top: 80),
                      child: Center(child: CircularProgressIndicator()),
                    );
                  }
                  if (snap.hasError) {
                    return _ErrorBox(msg: snap.error.toString(), onRetry: _reload);
                  }
                  final ov = snap.data!;
                  return Column(children: _content(ov));
                },
              ),
              FutureBuilder<DebtInfo>(
                future: _debt,
                builder: (context, snap) {
                  final d = snap.data;
                  if (d == null || (d.total == 0 && d.paidToday == 0)) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _DebtCard(d: d));
                },
              ),
              FutureBuilder<List<CatRow>>(
                future: _cats,
                builder: (context, snap) {
                  final rows = snap.data ?? [];
                  if (rows.isEmpty) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _CatCard(cats: rows));
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _content(Overview ov) {
    return [
      // KPI 2x2
      Row(children: [
        Expanded(child: _kpi('Savdo', money(ov.sales), ov.dSales, AppColors.accentStrong)),
        const SizedBox(width: 12),
        Expanded(child: _kpi('Yalpi foyda', money(ov.profit), ov.dProfit, AppColors.ok)),
      ]),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(child: _kpi('Cheklar', ov.tx.toString(), null, AppColors.text)),
        const SizedBox(width: 12),
        Expanded(child: _kpi('O‘rtacha chek', money(ov.avgCheck), null, AppColors.text)),
      ]),
      const SizedBox(height: 16),
      if (ov.series.isNotEmpty) _TrendCard(series: ov.series),
      if (ov.series.isNotEmpty) const SizedBox(height: 16),
      if (ov.payments.isNotEmpty || ov.creditTotal > 0) _PayCard(ov: ov),
      if (ov.payments.isNotEmpty || ov.creditTotal > 0) const SizedBox(height: 16),
      if (ov.top.isNotEmpty) _TopCard(top: ov.top),
      if (ov.top.isNotEmpty) const SizedBox(height: 16),
      if (ov.cashiers.isNotEmpty) _CashiersCard(cashiers: ov.cashiers),
    ];
  }

  Widget _kpi(String label, String value, double? delta, Color color) {
    return AppCard(
      padding: const EdgeInsets.all(15),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
          const SizedBox(height: 8),
          Text(value, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: color)),
          const SizedBox(height: 6),
          if (delta == null)
            const Text('yangi', style: TextStyle(color: AppColors.faint, fontSize: 11.5, fontWeight: FontWeight.w600))
          else
            Row(children: [
              Icon(delta >= 0 ? Icons.trending_up : Icons.trending_down,
                  size: 14, color: delta >= 0 ? AppColors.ok : AppColors.danger),
              const SizedBox(width: 3),
              Text('${delta.abs().toStringAsFixed(1)}%',
                  style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: delta >= 0 ? AppColors.ok : AppColors.danger)),
            ]),
        ],
      ),
    );
  }
}

class _PeriodBar extends StatelessWidget {
  final String period;
  final void Function(String) onChange;
  const _PeriodBar({required this.period, required this.onChange});

  @override
  Widget build(BuildContext context) {
    final opts = {'day': 'Bugun', 'week': 'Hafta', 'month': 'Oy'};
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: opts.entries.map((e) {
          final on = period == e.key;
          return Expanded(
            child: GestureDetector(
              onTap: () => onChange(e.key),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: on ? AppColors.card : Colors.transparent,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Center(
                  child: Text(e.value,
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: on ? AppColors.accentStrong : AppColors.muted)),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _TrendCard extends StatelessWidget {
  final List<SeriesPoint> series;
  const _TrendCard({required this.series});

  @override
  Widget build(BuildContext context) {
    final maxV = series.map((e) => e.sales).fold<double>(1, (a, b) => b > a ? b : a);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Savdo dinamikasi', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          SizedBox(
            height: 120,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: series.map((p) {
                final h = maxV <= 0 ? 0.0 : (p.sales / maxV) * 88;
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text(short(p.sales), style: const TextStyle(fontSize: 9.5, color: AppColors.faint)),
                        const SizedBox(height: 4),
                        Container(
                          height: h < 3 ? 3 : h,
                          decoration: BoxDecoration(
                            color: p == series.last ? AppColors.accent : AppColors.accentSoft,
                            borderRadius: BorderRadius.circular(6),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(p.label.length > 5 ? p.label.substring(5) : p.label,
                            style: const TextStyle(fontSize: 9, color: AppColors.muted),
                            overflow: TextOverflow.clip, maxLines: 1),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class _PayCard extends StatelessWidget {
  final Overview ov;
  const _PayCard({required this.ov});

  @override
  Widget build(BuildContext context) {
    const labels = {'cash': 'Naqd', 'card': 'Karta', 'qr': 'QR', 'credit': 'Qarz'};
    const colors = {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn};
    final rows = [...ov.payments.map((p) => (p.method, p.amount))];
    if (ov.creditTotal > 0) rows.add(('credit', ov.creditTotal));
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('To‘lov usullari', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          ...rows.map((r) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(children: [
                  Container(width: 9, height: 9, decoration: BoxDecoration(shape: BoxShape.circle, color: colors[r.$1] ?? AppColors.muted)),
                  const SizedBox(width: 8),
                  Text(r.$1 == 'credit' ? 'Qarz (to‘lanmagan)' : (labels[r.$1] ?? r.$1),
                      style: const TextStyle(fontSize: 13, color: AppColors.text3)),
                  const Spacer(),
                  Text(money(r.$2), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                ]),
              )),
        ],
      ),
    );
  }
}

class _TopCard extends StatelessWidget {
  final List<TopProduct> top;
  const _TopCard({required this.top});

  @override
  Widget build(BuildContext context) {
    final maxV = top.map((e) => e.revenue).fold<double>(1, (a, b) => b > a ? b : a);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Eng ko‘p sotilgan', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          ...top.map((p) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Expanded(child: Text(p.name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                      Text(money(p.revenue), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                    ]),
                    const SizedBox(height: 5),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(3),
                      child: LinearProgressIndicator(
                        value: (p.revenue / maxV).clamp(0.0, 1.0),
                        minHeight: 6,
                        backgroundColor: AppColors.border,
                        valueColor: const AlwaysStoppedAnimation(Color(0xFF8B7FF0)),
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}

class _CashiersCard extends StatelessWidget {
  final List<Cashier> cashiers;
  const _CashiersCard({required this.cashiers});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Kassirlar', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          ...cashiers.take(5).map((c) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(children: [
                  CircleAvatar(radius: 15, backgroundColor: AppColors.accentSoft,
                      child: Text(c.name.isEmpty ? '?' : c.name[0], style: const TextStyle(fontSize: 12, color: AppColors.accentStrong, fontWeight: FontWeight.w700))),
                  const SizedBox(width: 10),
                  Expanded(child: Text(c.name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                  Text('${c.tx} chek', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
                  const SizedBox(width: 10),
                  Text(short(c.sales), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.text3)),
                ]),
              )),
        ],
      ),
    );
  }
}

class _DebtCard extends StatelessWidget {
  final DebtInfo d;
  const _DebtCard({required this.d});
  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Mijozlar qarzi', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const Spacer(),
          Text('${d.debtors} qarzdor', style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
        ]),
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: _mini('Umumiy qarz', money(d.total), AppColors.warn)),
          Expanded(child: _mini('Bugun to‘landi', money(d.paidToday), AppColors.ok)),
        ]),
      ]),
    );
  }

  Widget _mini(String l, String v, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        const SizedBox(height: 4),
        Text(v, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c)),
      ]);
}

class _CatCard extends StatelessWidget {
  final List<CatRow> cats;
  const _CatCard({required this.cats});
  @override
  Widget build(BuildContext context) {
    final show = cats.take(6).toList();
    final maxV = show.map((e) => e.sales).fold<double>(1, (a, b) => b > a ? b : a);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Kategoriyalar bo‘yicha savdo', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 14),
        ...show.map((c) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(c.name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                  Text('${c.margin}%', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
                  const SizedBox(width: 10),
                  Text(money(c.sales), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                ]),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: (c.sales / maxV).clamp(0.0, 1.0),
                    minHeight: 6,
                    backgroundColor: AppColors.border,
                    valueColor: const AlwaysStoppedAnimation(AppColors.accent),
                  ),
                ),
              ]),
            )),
      ]),
    );
  }
}

class _ErrorBox extends StatelessWidget {
  final String msg;
  final VoidCallback onRetry;
  const _ErrorBox({required this.msg, required this.onRetry});
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 60),
      child: Column(children: [
        const Icon(Icons.cloud_off, color: AppColors.muted, size: 40),
        const SizedBox(height: 12),
        Text(msg, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
        const SizedBox(height: 16),
        OutlinedButton(onPressed: onRetry, child: const Text('Qayta urinish')),
      ]),
    );
  }
}
