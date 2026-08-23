import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../report_export.dart';
import '../theme.dart';
import 'customers_screen.dart';
import 'detail_report_screen.dart';
import 'sales_list_screen.dart';
import 'suppliers_screen.dart';

/// Do'kon egasi uchun mobil analitika (BILLZ uslubida): savdo/foyda, dinamika,
/// to'lov usullari, top mahsulotlar. Sodda — keraksiz widget yo'q.
class AnalyticsScreen extends StatefulWidget {
  final void Function(int index)? onTab; // pastki nav'ga o'tish (banner uchun)
  const AnalyticsScreen({super.key, this.onTab});
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  String _period = 'week';      // day|week|month|range
  String _lastPreset = 'week';  // range paytida aux kartalar (kategoriya/naqd oqim) uchun
  String? _from, _to;           // custom oraliq (YYYY-MM-DD)
  Future<Overview>? _future;
  Future<List<CatRow>>? _cats;
  Future<DebtInfo>? _debt;
  Future<List<HourPoint>>? _hourly;
  Future<List<SaleRow>>? _recent;
  Future<(int, int)>? _alerts;
  Future<CashFlow>? _cash;

  // Keshlangan natijalar — refresh paytida eski ma'lumot ko'rinib turadi (scroll sakramaydi).
  Overview? _ov;
  List<CatRow> _catsData = [];
  DebtInfo? _debtData;
  List<HourPoint> _hourlyData = [];
  List<SaleRow> _recentData = [];
  (int, int)? _alertsData;
  CashFlow? _cashData;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => setState(() {
        _future = Api.overview(_period, from: _from, to: _to);
        _cats = Api.categories(_lastPreset);
        _debt = Api.debt();
        _hourly = Api.hourly();
        _recent = Api.sales(limit: 6);
        _alerts = Api.invAlerts();
        _cash = Api.cashflow(_lastPreset);
      });

  void _setPeriod(String p) {
    if (p == _period && _from == null) return;
    setState(() {
      _period = p;
      _lastPreset = p;
      _from = null;
      _to = null;
      _future = Api.overview(p);
      _cats = Api.categories(p);
      _cash = Api.cashflow(p);
    });
  }

  Future<void> _pickRange() async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(now.year - 2),
      lastDate: now,
      initialDateRange: DateTimeRange(start: now.subtract(const Duration(days: 7)), end: now),
      builder: (context, child) => Theme(data: Theme.of(context).copyWith(colorScheme: const ColorScheme.dark(primary: AppColors.accent, surface: AppColors.card)), child: child!),
    );
    if (picked == null) return;
    String f(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
    setState(() {
      _from = f(picked.start);
      _to = f(picked.end);
      _period = 'range';
      _future = Api.overview('range', from: _from, to: _to);
    });
  }

  String get _rangeLabel {
    if (_from == null || _to == null) return '';
    final f = _from!.split('-'), t = _to!.split('-');
    return '${f[2]}.${f[1]} – ${t[2]}.${t[1]}';
  }

  String get _periodLabel => _period == 'range'
      ? _rangeLabel
      : switch (_period) { 'day' => tr('Bugun'), 'week' => tr('Hafta'), 'month' => tr('Oy'), _ => _period };

  void _exportSheet() {
    final ov = _ov;
    if (ov == null) return;
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
            const SizedBox(height: 16),
            Text(tr('Hisobotni yuklab olish'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            const SizedBox(height: 14),
            _expOpt(Icons.picture_as_pdf_outlined, 'PDF', tr('Chiroyli hujjat'), AppColors.danger, () => _doExport(() => ReportExport.pdf(ov, _cashData, _periodLabel))),
            _expOpt(Icons.grid_on_outlined, 'Excel', tr('Jadval (CSV)'), AppColors.ok, () => _doExport(() => ReportExport.csv(ov, _cashData, _periodLabel))),
            _expOpt(Icons.share_outlined, tr('Ulashish'), tr('Matn — Telegram/WhatsApp'), AppColors.accentStrong, () => _doExport(() => ReportExport.text(ov, _cashData, _periodLabel))),
          ]),
        ),
      ),
    );
  }

  Future<void> _doExport(Future<void> Function() fn) async {
    Navigator.pop(context);
    try {
      await fn();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${tr('Xato')}: $e')));
    }
  }

  Widget _expOpt(IconData ic, String title, String sub, Color c, VoidCallback onTap) => GestureDetector(
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Container(width: 44, height: 44, decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)), child: Icon(ic, color: c, size: 22)),
            const SizedBox(width: 14),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              Text(sub, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            ])),
            const Icon(Icons.chevron_right, color: AppColors.faint),
          ]),
        ),
      );

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
                  Text(tr('Analitika'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const Spacer(),
                  GestureDetector(
                    onTap: _ov == null ? null : _exportSheet,
                    child: Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(10), border: Border.all(color: AppColors.border)),
                      child: const Icon(Icons.ios_share, size: 18, color: AppColors.accentStrong),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              _PeriodBar(period: _period, onChange: _setPeriod, onPickRange: _pickRange, rangeLabel: _rangeLabel),
              const SizedBox(height: 16),
              FutureBuilder<(int, int)>(
                future: _alerts,
                builder: (context, snap) {
                  if (snap.hasData) _alertsData = snap.data;
                  final a = _alertsData;
                  if (a == null || (a.$1 + a.$2) == 0) return const SizedBox.shrink();
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: _AlertBanner(low: a.$1, out: a.$2, onTap: () => widget.onTab?.call(2)),
                  );
                },
              ),
              FutureBuilder<Overview>(
                future: _future,
                builder: (context, snap) {
                  if (snap.hasData) _ov = snap.data;
                  final ov = _ov;
                  if (ov == null) {
                    if (snap.hasError) return _ErrorBox(msg: snap.error.toString(), onRetry: _reload);
                    return const _AnalyticsSkeleton();
                  }
                  return Column(children: _content(ov));
                },
              ),
              FutureBuilder<DebtInfo>(
                future: _debt,
                builder: (context, snap) {
                  if (snap.hasData) _debtData = snap.data;
                  final d = _debtData;
                  if (d == null || (d.total == 0 && d.paidToday == 0)) return const SizedBox.shrink();
                  return Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: GestureDetector(
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const CustomersScreen(onlyDebt: true))),
                      child: _DebtCard(d: d),
                    ),
                  );
                },
              ),
              FutureBuilder<CashFlow>(
                future: _cash,
                builder: (context, snap) {
                  if (snap.hasData) _cashData = snap.data;
                  final cf = _cashData;
                  if (cf == null || (cf.inJami == 0 && cf.outJami == 0 && cf.opening == 0)) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _CashFlowCard(cf: cf));
                },
              ),
              FutureBuilder<List<HourPoint>>(
                future: _hourly,
                builder: (context, snap) {
                  if (snap.hasData) _hourlyData = snap.data!;
                  final hrs = _hourlyData;
                  if (hrs.isEmpty || hrs.every((h) => h.sales == 0)) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _HourCard(hours: hrs));
                },
              ),
              FutureBuilder<List<CatRow>>(
                future: _cats,
                builder: (context, snap) {
                  if (snap.hasData) _catsData = snap.data!;
                  final rows = _catsData;
                  if (rows.isEmpty) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _CatCard(cats: rows));
                },
              ),
              FutureBuilder<List<SaleRow>>(
                future: _recent,
                builder: (context, snap) {
                  if (snap.hasData) _recentData = snap.data!;
                  final rows = _recentData;
                  if (rows.isEmpty) return const SizedBox.shrink();
                  return Padding(padding: const EdgeInsets.only(top: 16), child: _RecentCard(rows: rows));
                },
              ),
              const SizedBox(height: 16),
              Row(children: [
                _navCard(context, Icons.receipt_long, tr('Sotuvlar'), const SalesListScreen()),
                const SizedBox(width: 10),
                _navCard(context, Icons.people_alt_outlined, tr('Mijozlar'), const CustomersScreen()),
              ]),
              const SizedBox(height: 10),
              Row(children: [
                _navCard(context, Icons.local_shipping_outlined, tr('Yetkazib beruvchilar'), const SuppliersScreen()),
                const SizedBox(width: 10),
                _navCard(context, Icons.analytics_outlined, tr('Batafsil · ABC'), const DetailReportScreen()),
              ]),
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
        Expanded(child: _kpi(tr('Savdo'), money(ov.sales), ov.dSales, AppColors.accentStrong)),
        const SizedBox(width: 12),
        Expanded(child: _kpi(tr('Yalpi foyda'), money(ov.profit), ov.dProfit, AppColors.ok)),
      ]),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(child: _kpi(tr('Cheklar'), ov.tx.toString(), null, AppColors.text)),
        const SizedBox(width: 12),
        Expanded(child: _kpi(tr('O‘rtacha chek'), money(ov.avgCheck), null, AppColors.text)),
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
            Text(tr('yangi'), style: const TextStyle(color: AppColors.faint, fontSize: 11.5, fontWeight: FontWeight.w600))
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
  final VoidCallback onPickRange;
  final String rangeLabel;
  const _PeriodBar({required this.period, required this.onChange, required this.onPickRange, this.rangeLabel = ''});

  @override
  Widget build(BuildContext context) {
    final opts = {'day': tr('Bugun'), 'week': tr('Hafta'), 'month': tr('Oy')};
    final rangeOn = period == 'range';
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          ...opts.entries.map((e) {
            final on = period == e.key;
            return Expanded(
              child: GestureDetector(
                onTap: () => onChange(e.key),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(color: on ? AppColors.card : Colors.transparent, borderRadius: BorderRadius.circular(8)),
                  child: Center(
                    child: Text(e.value, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: on ? AppColors.accentStrong : AppColors.muted)),
                  ),
                ),
              ),
            );
          }),
          // Sana oralig'i (kalendar)
          Expanded(
            flex: rangeOn ? 2 : 1,
            child: GestureDetector(
              onTap: onPickRange,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
                decoration: BoxDecoration(color: rangeOn ? AppColors.card : Colors.transparent, borderRadius: BorderRadius.circular(8)),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Icon(Icons.calendar_today_outlined, size: 14, color: rangeOn ? AppColors.accentStrong : AppColors.muted),
                  if (rangeOn && rangeLabel.isNotEmpty) ...[
                    const SizedBox(width: 5),
                    Flexible(child: Text(rangeLabel, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.accentStrong))),
                  ],
                ]),
              ),
            ),
          ),
        ],
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
          Text(tr('Savdo dinamikasi'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
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
    final labels = {'cash': tr('Naqd'), 'card': tr('Karta'), 'qr': 'QR', 'credit': tr('Qarz')};
    const colors = {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn};
    final rows = [...ov.payments.map((p) => (p.method, p.amount))];
    if (ov.creditTotal > 0) rows.add(('credit', ov.creditTotal));
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(tr('To‘lov usullari'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          ...rows.map((r) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(children: [
                  Container(width: 9, height: 9, decoration: BoxDecoration(shape: BoxShape.circle, color: colors[r.$1] ?? AppColors.muted)),
                  const SizedBox(width: 8),
                  Text(r.$1 == 'credit' ? tr('Qarz (to‘lanmagan)') : (labels[r.$1] ?? r.$1),
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
          Text(tr('Eng ko‘p sotilgan'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
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
          Text(tr('Kassirlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
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
          Text(tr('Mijozlar qarzi'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const Spacer(),
          Text('${d.debtors} qarzdor', style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
        ]),
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: _mini(tr('Umumiy qarz'), money(d.total), AppColors.warn)),
          Expanded(child: _mini(tr('Bugun to‘landi'), money(d.paidToday), AppColors.ok)),
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
        Text(tr('Kategoriyalar bo‘yicha savdo'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
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

Widget _navCard(BuildContext context, IconData ic, String label, Widget screen) => Expanded(
      child: GestureDetector(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen)),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
          decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Icon(ic, size: 19, color: AppColors.accentStrong),
            const SizedBox(width: 10),
            Expanded(child: Text(label, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600))),
            const Icon(Icons.chevron_right, size: 16, color: AppColors.muted),
          ]),
        ),
      ),
    );

/// Yuklanish skeleti — spinner o'rniga (dizayn: "skeleton loading").
class _AnalyticsSkeleton extends StatefulWidget {
  const _AnalyticsSkeleton();
  @override
  State<_AnalyticsSkeleton> createState() => _AnalyticsSkeletonState();
}

class _AnalyticsSkeletonState extends State<_AnalyticsSkeleton> with SingleTickerProviderStateMixin {
  late final AnimationController _ctl;
  @override
  void initState() {
    super.initState();
    _ctl = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat(reverse: true);
  }

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  Widget _box(double h, {double? w, double r = 12}) => Container(
        height: h, width: w, decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(r)));

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween(begin: 0.45, end: 0.9).animate(_ctl),
      child: Column(children: [
        Row(children: [Expanded(child: _box(96)), const SizedBox(width: 12), Expanded(child: _box(96))]),
        const SizedBox(height: 12),
        Row(children: [Expanded(child: _box(96)), const SizedBox(width: 12), Expanded(child: _box(96))]),
        const SizedBox(height: 16),
        _box(180, r: 16),
        const SizedBox(height: 16),
        _box(120, r: 16),
      ]),
    );
  }
}

class _CashFlowCard extends StatelessWidget {
  final CashFlow cf;
  const _CashFlowCard({required this.cf});

  Widget _row(String label, double v, Color c) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(fontSize: 12.5, color: AppColors.text3))),
          Text(money(v), style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: c)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.account_balance_wallet_outlined, size: 18, color: AppColors.accentStrong),
          const SizedBox(width: 8),
          Text(tr('Naqd oqim'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 12),
        // Kassada qoldi
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(13)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('Kassada naqd'), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 3),
            Text(money(cf.kassada), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.accentStrong, letterSpacing: -0.5)),
          ]),
        ),
        const SizedBox(height: 14),
        Row(children: [
          // Kirim
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.south_west, size: 14, color: AppColors.ok),
                const SizedBox(width: 5),
                Text('${tr('Kirim')} · ${money(cf.inJami)}', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.ok)),
              ]),
              const SizedBox(height: 4),
              _row(tr('Naqd savdo'), cf.inNaqd, AppColors.text3),
              _row(tr('Qarz qaytdi'), cf.inQarz, AppColors.text3),
              _row(tr('Qo‘shimcha'), cf.inQosh, AppColors.text3),
            ]),
          ),
          const SizedBox(width: 14),
          // Chiqim
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.north_east, size: 14, color: AppColors.danger),
                const SizedBox(width: 5),
                Text('${tr('Chiqim')} · ${money(cf.outJami)}', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.danger)),
              ]),
              const SizedBox(height: 4),
              _row(tr('Xarajat'), cf.outXarajat, AppColors.text3),
              _row(tr('Inkassatsiya'), cf.outInkassa, AppColors.text3),
              _row(tr('Qaytarish'), cf.outQaytarish, AppColors.text3),
              if (cf.outBeruvchi > 0) _row(tr('Beruvchiga'), cf.outBeruvchi, AppColors.text3),
            ]),
          ),
        ]),
      ]),
    );
  }
}

class _AlertBanner extends StatelessWidget {
  final int low, out;
  final VoidCallback onTap;
  const _AlertBanner({required this.low, required this.out, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final parts = <String>[];
    if (out > 0) parts.add('$out tugagan');
    if (low > 0) parts.add('$low kam qolgan');
    return Material(
      color: AppColors.warnSoft,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            const Icon(Icons.warning_amber_rounded, color: AppColors.warn, size: 22),
            const SizedBox(width: 12),
            Expanded(child: Text('Diqqat: ${parts.join(' · ')} mahsulot',
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: AppColors.text2))),
            const Icon(Icons.chevron_right, color: AppColors.warn),
          ]),
        ),
      ),
    );
  }
}

class _HourCard extends StatelessWidget {
  final List<HourPoint> hours;
  const _HourCard({required this.hours});
  @override
  Widget build(BuildContext context) {
    // Faol oraliq: birinchi va oxirgi savdoli soat
    int lo = 0, hi = 23;
    while (lo < 23 && hours[lo].sales == 0) { lo++; }
    while (hi > lo && hours[hi].sales == 0) { hi--; }
    final slice = hours.sublist(lo, hi + 1);
    final maxV = slice.map((e) => e.sales).fold<double>(1, (a, b) => b > a ? b : a);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(tr('Bugun — soatlik savdo'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 16),
        SizedBox(
          height: 110,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: slice.map((p) {
              final h = maxV <= 0 ? 0.0 : (p.sales / maxV) * 80;
              return Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2.5),
                  child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                    Container(
                      height: p.sales > 0 && h < 3 ? 3 : h,
                      decoration: BoxDecoration(
                        color: p.sales > 0 ? AppColors.accent : AppColors.border,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text('${p.hour}', style: const TextStyle(fontSize: 9.5, color: AppColors.muted)),
                  ]),
                ),
              );
            }).toList(),
          ),
        ),
      ]),
    );
  }
}

class _RecentCard extends StatelessWidget {
  final List<SaleRow> rows;
  const _RecentCard({required this.rows});
  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(tr('So‘nggi sotuvlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const Spacer(),
          GestureDetector(
            onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SalesListScreen())),
            child: Text(tr('Barchasi →'), style: const TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600)),
          ),
        ]),
        const SizedBox(height: 12),
        ...rows.map(saleTile),
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
        OutlinedButton(onPressed: onRetry, child: Text(tr('Qayta urinish'))),
      ]),
    );
  }
}
