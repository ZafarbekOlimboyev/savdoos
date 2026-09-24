import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../report_export.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'customers_screen.dart';
import 'detail_report_screen.dart';
import 'sales_detail_screen.dart';
import 'sales_list_screen.dart';
import 'shell.dart';
import 'suppliers_screen.dart';

/// Do'kon egasi uchun mobil analitika (BILLZ uslubida): savdo/foyda, dinamika,
/// to'lov usullari, top mahsulotlar.
///
/// FILIAL DOIRASI (Phase 5G.1 / C4 da yangilandi). `GET /reports/overview`,
/// `/reports/cashflow`, `/reports/hourly`, `/reports/categories`, `GET /sales` va
/// `GET /inventory/overview` (ombor ogohlantirishi) filial bo'yicha filtrlanadi
/// (`branch_id` = joriy filial; "Barcha filiallar" doirasida `branch_id`
/// yuborilmaydi). Ilgari faqat overview/sales/inventory filtrlanardi — qolgan uchta
/// karta ko'rinadigan BARCHA filiallar yig'indisini ko'rsatib, "Barcha filiallar"
/// yozuvi bilan rostini aytardi; B1 serverda o'sha uchta marshrutga
/// `GET /products?branch_id=` bilan AYNI tekshiruvni qo'shgach, ular ham doirani
/// kuzatadi va yozuv OLIB TASHLANDI.
///
/// `GET /reports/dashboard` (mijozlar qarzi) — ATAYLAB doirasiz: mijoz krediti
/// KOMPANIYA fakti (`Customer` da filial ustuni yo'q, server ham `/reports/debtors`
/// uchun `branch_id` qabul qilmaydi), shuning uchun o'sha kartada yozuv QOLADI.
///
/// ⚠️  ESKI SERVER. `branch_id` noma'lum parametr sifatida jimgina e'tiborsiz
///     qoldiriladi (yozuvga ta'sir qilmaydi, 4xx bermaydi) — shuning uchun uni
///     yuborish xavfsiz. Lekin 5G.1 dan OLDINGI serverda uch karta yana barcha
///     filial yig'indisini beradi va endi yozuvsiz beradi. Server darajasini
///     e'lon qiluvchi qobiliyat darvozasi (C3) kelsa, yozuv o'shanga BOG'LANSIN.
///
/// Filial almashganda qobiq bu ekranni QAYTA quradi (yangi so'rovlar).
///
/// Tab `hisobot.view` bilan ochiladi (qobiq); ichidagi havolalar va bo'limlar ham
/// o'z matritsa amali bilan (`sales.list`, `suppliers.list`, `stock.overview`, ...).
class AnalyticsScreen extends StatefulWidget {
  final void Function(int index)? onTab; // pastki nav'ga o'tish (banner uchun)
  final Session? session;
  const AnalyticsScreen({super.key, this.onTab, this.session});
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  String _period = 'week'; // day|week|month|range
  String _lastPreset = 'week'; // range paytida aux kartalar (kategoriya/naqd oqim) uchun
  String? _from, _to; // custom oraliq (YYYY-MM-DD)
  bool _allBranches = false; // true: overview/sotuvlar barcha ko'rinadigan filiallar bo'yicha
  Future<Overview>? _future;
  Future<List<CatRow>>? _cats;
  Future<DebtInfo>? _debt;
  Future<List<HourPoint>>? _hourly;
  Future<List<SaleRow>>? _recent;
  Future<(int, int)>? _alerts;
  Future<CashFlow>? _cash;

  // Keshlangan natijalar — refresh paytida eski ma'lumot ko'rinib turadi (scroll sakramaydi).
  // Filial/doira almashganda TOZALANADI (A filial raqamlari B ostida qolmasin).
  Overview? _ov;
  List<CatRow> _catsData = [];
  DebtInfo? _debtData;
  List<HourPoint> _hourlyData = [];
  List<SaleRow> _recentData = [];
  (int, int)? _alertsData;
  CashFlow? _cashData;

  Session get _s => widget.session ?? Session.instance;

  /// More than one visible branch -> scope matters.
  bool get _multiBranch => _s.branches.length > 1;

  /// `branch_id` for the branch-filterable reports (empty = all visible branches).
  Map<String, Object?> get _branchQ => _allBranches ? const {} : _s.branchQuery();

  bool get _canSales => Perm.allows('sales.list', session: _s);

  /// `/inventory/overview` gate (hisobot.view) — no request that would 403.
  bool get _canStockAlerts => Perm.allows('stock.overview', session: _s);

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<Overview> _loadOverview(String period, {String? from, String? to}) async {
    final q = <String, Object?>{
      if (from != null && to != null) ...{'from_date': from, 'to_date': to} else 'period': period,
      ..._branchQ,
    };
    return Overview.fromJson((await Api.getJson('/reports/overview', query: q)).map);
  }

  /// Low / out-of-stock counts of the current branch (or of every visible
  /// branch in the "Barcha filiallar" scope).
  Future<(int, int)> _loadAlerts() async {
    final m = (await Api.getJson('/inventory/overview', query: _branchQ)).map;
    int n(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
    return (n(m['low_count']), n(m['out_count']));
  }

  Future<List<SaleRow>> _loadRecent() async {
    final rows = (await Api.getJson('/sales', query: {'limit': 6, ..._branchQ})).list;
    return [
      for (final e in rows)
        if (e is Map) SaleRow.fromJson(e.cast<String, dynamic>())
    ];
  }

  // ⚠️  `Api.categories/hourly/cashflow` (yadro paketi) doirasiz qoladi — ular
  //     boshqa chaqiruvchilarga tegishli. Bu ekran filialni o'zi qo'shib, AYNI
  //     `/reports/*` marshrutlariga `Api.getJson` bilan boradi.

  Future<List<CatRow>> _loadCats(String period) async {
    final rows = (await Api.getJson('/reports/categories', query: {'period': period, ..._branchQ})).list;
    return [
      for (final e in rows)
        if (e is Map) CatRow.fromJson(e.cast<String, dynamic>())
    ];
  }

  Future<List<HourPoint>> _loadHourly() async {
    final rows = (await Api.getJson('/reports/hourly', query: _branchQ)).list;
    return [
      for (final e in rows)
        if (e is Map) HourPoint.fromJson(e.cast<String, dynamic>())
    ];
  }

  Future<CashFlow> _loadCash(String period) async =>
      CashFlow.fromJson((await Api.getJson('/reports/cashflow', query: {'period': period, ..._branchQ})).map);

  void _reload() => setState(() {
        _future = _loadOverview(_period, from: _from, to: _to);
        _cats = _loadCats(_lastPreset);
        _debt = Api.debt(); // KOMPANIYA doirasi — mijoz krediti filialga bo'linmaydi
        _hourly = _loadHourly();
        _recent = _canSales ? _loadRecent() : Future.value(const <SaleRow>[]);
        _alerts = _canStockAlerts ? _loadAlerts() : null;
        _cash = _loadCash(_lastPreset);
      });

  void _setScope(bool all) {
    if (all == _allBranches) return;
    setState(() {
      _allBranches = all;
      // Doira o'zgardi — keshlangan raqamlarning HAMMASI (endi kategoriya/soat/naqd
      // oqim ham) boshqa doiraga tegishli: yangisi kelguncha ko'rsatilmaydi.
      _ov = null;
      _recentData = [];
      _alertsData = null;
      _catsData = [];
      _hourlyData = [];
      _cashData = null;
      _future = _loadOverview(_period, from: _from, to: _to);
      _recent = _canSales ? _loadRecent() : Future.value(const <SaleRow>[]);
      _alerts = _canStockAlerts ? _loadAlerts() : null;
      _cats = _loadCats(_lastPreset);
      _hourly = _loadHourly();
      _cash = _loadCash(_lastPreset);
    });
  }

  void _setPeriod(String p) {
    if (p == _period && _from == null) return;
    setState(() {
      _period = p;
      _lastPreset = p;
      _from = null;
      _to = null;
      _future = _loadOverview(p);
      _cats = _loadCats(p);
      _cash = _loadCash(p);
    });
  }

  Future<void> _pickRange() async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(now.year - 2),
      lastDate: now,
      initialDateRange: DateTimeRange(start: now.subtract(const Duration(days: 7)), end: now),
      builder: (context, child) => Theme(
          data: Theme.of(context).copyWith(
              colorScheme: (AppTheme.current.dark ? const ColorScheme.dark() : const ColorScheme.light())
                  .copyWith(primary: AppColors.accent, surface: AppColors.card, onSurface: AppColors.text)),
          child: child!),
    );
    if (picked == null) return;
    setState(() {
      _from = isoDate(picked.start);
      _to = isoDate(picked.end);
      _period = 'range';
      _future = _loadOverview('range', from: _from, to: _to);
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

  /// Caption for the card whose numbers are a COMPANY fact and therefore cover
  /// every branch no matter which scope is selected (customer debt: `Customer`
  /// has no branch column, so `/reports/dashboard` is asked without `branch_id`).
  ///
  /// The branch-filterable cards (cashflow, hourly, categories) lost this
  /// caption in Phase 5G.1 / C4 — they now follow the scope bar like the KPIs.
  String? get _companyNote => (_multiBranch && !_allBranches) ? tr('Barcha filiallar') : null;

  void _exportSheet() {
    final ov = _ov;
    if (ov == null) return;
    showAppSheet<void>(
      context,
      title: tr('Hisobotni yuklab olish'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        _expOpt(ctx, Icons.picture_as_pdf_outlined, 'PDF', tr('Chiroyli hujjat'), AppColors.danger,
            () => ReportExport.pdf(ov, _cashData, _periodLabel)),
        _expOpt(ctx, Icons.grid_on_outlined, 'Excel', tr('Jadval (CSV)'), AppColors.ok,
            () => ReportExport.csv(ov, _cashData, _periodLabel)),
        _expOpt(ctx, Icons.share_outlined, tr('Ulashish'), tr('Matn — Telegram/WhatsApp'), AppColors.accentStrong,
            () => ReportExport.text(ov, _cashData, _periodLabel)),
      ]),
    );
  }

  Future<void> _doExport(BuildContext sheetCtx, Future<void> Function() fn) async {
    Navigator.of(sheetCtx).pop();
    try {
      await fn();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(userMessage(e))));
      }
    }
  }

  Widget _expOpt(BuildContext sheetCtx, IconData ic, String title, String sub, Color c, Future<void> Function() fn) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Material(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(kRadius),
          child: InkWell(
            borderRadius: BorderRadius.circular(kRadius),
            onTap: () => _doExport(sheetCtx, fn),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
              child: Row(children: [
                Container(
                    width: 44,
                    height: 44,
                    decoration:
                        BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
                    child: Icon(ic, color: c, size: 22)),
                const SizedBox(width: 14),
                Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                  Text(sub, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ])),
                Icon(Icons.chevron_right, color: AppColors.faint),
              ]),
            ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final note = _companyNote;
    final branchName = _s.currentBranch?.name ?? tr('Filial');
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => _reload(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            children: [
              Row(
                children: [
                  Expanded(
                      child: Text(tr('Analitika'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800))),
                  IconButton(
                    key: const Key('analytics-export'),
                    tooltip: tr('Hisobotni yuklab olish'),
                    constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                    onPressed: _ov == null ? null : _exportSheet,
                    icon: Icon(Icons.ios_share, size: 20, color: AppColors.accentStrong),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              _PeriodBar(period: _period, onChange: _setPeriod, onPickRange: _pickRange, rangeLabel: _rangeLabel),
              if (_multiBranch) ...[
                const SizedBox(height: 10),
                _ScopeBar(all: _allBranches, branchName: branchName, onChange: _setScope),
              ],
              const SizedBox(height: 16),
              if (_canStockAlerts)
                FutureBuilder<(int, int)>(
                  key: ValueKey('alerts@${_allBranches ? '*' : _s.currentBranchId}'),
                  future: _alerts,
                  builder: (context, snap) {
                    if (snap.hasData) _alertsData = snap.data;
                    final a = _alertsData;
                    if (a == null || (a.$1 + a.$2) == 0) return const SizedBox.shrink();
                    // Ombor tabi ko'rinmasa banner bosilmaydi (jim "hech narsa" emas).
                    final canOpen = widget.onTab != null && ShellGates.tabVisible(ShellTab.stock, session: _s);
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: _AlertBanner(
                          low: a.$1, out: a.$2, onTap: canOpen ? () => widget.onTab?.call(ShellTab.stock.index) : null),
                    );
                  },
                ),
              FutureBuilder<Overview>(
                future: _future,
                builder: (context, snap) {
                  if (snap.hasData) _ov = snap.data;
                  final ov = _ov;
                  if (ov == null) {
                    if (snap.hasError) {
                      return Padding(
                        padding: const EdgeInsets.only(top: 24),
                        child: ErrorState(key: const Key('analytics-error'), error: snap.error!, onRetry: _reload),
                      );
                    }
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
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () => Navigator.of(context)
                          .push(MaterialPageRoute(builder: (_) => const CustomersScreen(onlyDebt: true))),
                      child: _DebtCard(key: const Key('card-debt'), d: d, note: note),
                    ),
                  );
                },
              ),
              FutureBuilder<CashFlow>(
                future: _cash,
                builder: (context, snap) {
                  if (snap.hasData) _cashData = snap.data;
                  final cf = _cashData;
                  if (cf == null) return const SizedBox.shrink();
                  if (cf.inJami == 0 && cf.outJami == 0 && cf.opening == 0) return const SizedBox.shrink();
                  return Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: _CashFlowCard(key: const Key('card-cashflow'), cf: cf));
                },
              ),
              FutureBuilder<List<HourPoint>>(
                future: _hourly,
                builder: (context, snap) {
                  if (snap.hasData) _hourlyData = snap.data!;
                  final hrs = _hourlyData;
                  if (hrs.length < 24 || hrs.every((h) => h.sales == 0)) return const SizedBox.shrink();
                  return Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: _HourCard(key: const Key('card-hourly'), hours: hrs));
                },
              ),
              FutureBuilder<List<CatRow>>(
                future: _cats,
                builder: (context, snap) {
                  if (snap.hasData) _catsData = snap.data!;
                  final rows = _catsData;
                  if (rows.isEmpty) return const SizedBox.shrink();
                  return Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: _CatCard(key: const Key('card-categories'), cats: rows));
                },
              ),
              if (_canSales)
                FutureBuilder<List<SaleRow>>(
                  future: _recent,
                  builder: (context, snap) {
                    if (snap.hasData) _recentData = snap.data!;
                    final rows = _recentData;
                    if (rows.isEmpty) return const SizedBox.shrink();
                    return Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: _RecentCard(rows: rows, canOpen: Perm.allows('sales.receipt', session: _s)));
                  },
                ),
              const SizedBox(height: 16),
              ..._navCards(context),
            ],
          ),
        ),
      ),
    );
  }

  /// Links to the report screens — each only with its own permission.
  List<Widget> _navCards(BuildContext context) {
    final cards = <Widget>[
      if (_canSales)
        _navCard(context, const Key('nav-sales'), Icons.receipt_long, tr('Sotuvlar'), const SalesListScreen()),
      if (Perm.allows('customers.list', session: _s))
        _navCard(
            context, const Key('nav-customers'), Icons.people_alt_outlined, tr('Mijozlar'), const CustomersScreen()),
      if (Perm.allows('suppliers.list', session: _s))
        _navCard(context, const Key('nav-suppliers'), Icons.local_shipping_outlined, tr('Yetkazib beruvchilar'),
            const SuppliersScreen()),
      if (Perm.allows('reports.detail', session: _s))
        _navCard(
            context, const Key('nav-abc'), Icons.analytics_outlined, tr('Batafsil · ABC'), const DetailReportScreen()),
    ];
    return [
      for (var i = 0; i < cards.length; i += 2) ...[
        if (i > 0) const SizedBox(height: 10),
        Row(children: [
          Expanded(child: cards[i]),
          const SizedBox(width: 10),
          Expanded(child: i + 1 < cards.length ? cards[i + 1] : const SizedBox.shrink()),
        ]),
      ],
    ];
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
          Text(label, style: TextStyle(color: AppColors.muted, fontSize: 12.5)),
          const SizedBox(height: 8),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(value, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: color)),
          ),
          const SizedBox(height: 6),
          if (delta == null)
            Text(tr('yangi'), style: TextStyle(color: AppColors.faint, fontSize: 11.5, fontWeight: FontWeight.w600))
          else
            Row(children: [
              Icon(delta >= 0 ? Icons.trending_up : Icons.trending_down,
                  size: 14, color: delta >= 0 ? AppColors.ok : AppColors.danger),
              const SizedBox(width: 3),
              Text('${delta.abs().toStringAsFixed(1)}%',
                  style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: delta >= 0 ? AppColors.ok : AppColors.danger)),
            ]),
        ],
      ),
    );
  }
}

/// "Joriy filial | Barcha filiallar" — only when more than one branch is visible.
class _ScopeBar extends StatelessWidget {
  final bool all;
  final String branchName;
  final ValueChanged<bool> onChange;
  const _ScopeBar({required this.all, required this.branchName, required this.onChange});

  @override
  Widget build(BuildContext context) {
    Widget opt(Key key, bool value, IconData icon, String label) {
      final on = all == value;
      return Expanded(
        child: Semantics(
          button: true,
          selected: on,
          child: InkWell(
            key: key,
            borderRadius: BorderRadius.circular(8),
            onTap: () => onChange(value),
            child: Container(
              constraints: const BoxConstraints(minHeight: kMinTouch - 6),
              padding: const EdgeInsets.symmetric(horizontal: 8),
              decoration: BoxDecoration(
                  color: on ? AppColors.card : Colors.transparent, borderRadius: BorderRadius.circular(8)),
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(icon, size: 16, color: on ? AppColors.accentStrong : AppColors.muted),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: on ? AppColors.accentStrong : AppColors.muted)),
                ),
              ]),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(11),
          border: Border.all(color: AppColors.border)),
      child: Row(children: [
        opt(const Key('scope-branch'), false, Icons.store_mall_directory_outlined, branchName),
        opt(const Key('scope-all'), true, Icons.apartment_outlined, tr('Barcha filiallar')),
      ]),
    );
  }
}

/// Caption under a card title whose numbers cover EVERY visible branch because
/// the fact itself is company-level (customer debt). Since Phase 5G.1 the
/// branch-filterable reports no longer need it — they ask for one branch.
Widget _noteLine(String? note) => note == null
    ? const SizedBox.shrink()
    : Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Row(children: [
          Icon(Icons.apartment_outlined, size: 13, color: AppColors.muted),
          const SizedBox(width: 4),
          Flexible(
            child: Text(note,
                key: const Key('agg-note'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: AppColors.muted)),
          ),
        ]),
      );

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
              child: InkWell(
                key: Key('period-${e.key}'),
                borderRadius: BorderRadius.circular(8),
                onTap: () => onChange(e.key),
                child: Container(
                  constraints: const BoxConstraints(minHeight: kMinTouch - 6),
                  alignment: Alignment.center,
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(
                      color: on ? AppColors.card : Colors.transparent, borderRadius: BorderRadius.circular(8)),
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
          }),
          // Sana oralig'i (kalendar)
          Expanded(
            flex: rangeOn ? 2 : 1,
            child: InkWell(
              key: const Key('period-range'),
              borderRadius: BorderRadius.circular(8),
              onTap: onPickRange,
              child: Container(
                constraints: const BoxConstraints(minHeight: kMinTouch - 6),
                padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
                decoration: BoxDecoration(
                    color: rangeOn ? AppColors.card : Colors.transparent, borderRadius: BorderRadius.circular(8)),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Icon(Icons.calendar_today_outlined,
                      size: 14, color: rangeOn ? AppColors.accentStrong : AppColors.muted),
                  if (rangeOn && rangeLabel.isNotEmpty) ...[
                    const SizedBox(width: 5),
                    Flexible(
                        child: Text(rangeLabel,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style:
                                TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.accentStrong))),
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
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: series.map((p) {
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    // Ustun balandligi — mavjud joydan ulush (matn o'lchami/til o'zgarsa ham toshmaydi).
                    child: Column(
                      children: [
                        _BarLabel(short(p.sales), size: 9.5, color: AppColors.faint),
                        const SizedBox(height: 4),
                        Expanded(
                          child: _Bar(
                            fraction: maxV <= 0 ? 0 : p.sales / maxV,
                            color: p == series.last ? AppColors.accent : AppColors.accentSoft,
                            radius: 6,
                          ),
                        ),
                        const SizedBox(height: 6),
                        _BarLabel(p.label.length > 5 ? p.label.substring(5) : p.label, size: 9, color: AppColors.muted),
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
    final colors = AppTheme.current.dark
        ? const {'cash': AppColors.ok, 'card': Color(0xFF8B7FF0), 'qr': Color(0xFF2BC4C4), 'credit': AppColors.warn}
        : const {
            'cash': Color(0xFF12915A),
            'card': Color(0xFF6D5DD3),
            'qr': Color(0xFF0E8F8F),
            'credit': Color(0xFFB8730C)
          };
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
                  Container(
                      width: 9,
                      height: 9,
                      decoration: BoxDecoration(shape: BoxShape.circle, color: colors[r.$1] ?? AppColors.muted)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(r.$1 == 'credit' ? tr('Qarz (to‘lanmagan)') : (labels[r.$1] ?? r.$1),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 13, color: AppColors.text3)),
                  ),
                  const SizedBox(width: 8),
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
                        valueColor: AlwaysStoppedAnimation(AppColors.accent),
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
                  CircleAvatar(
                      radius: 15,
                      backgroundColor: AppColors.accentSoft,
                      child: Text(c.name.isEmpty ? '?' : c.name[0],
                          style: TextStyle(fontSize: 12, color: AppColors.accentStrong, fontWeight: FontWeight.w700))),
                  const SizedBox(width: 10),
                  Expanded(child: Text(c.name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                  Text('${c.tx} ${tr('chek')}', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                  const SizedBox(width: 10),
                  Text(short(c.sales),
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.text3)),
                ]),
              )),
        ],
      ),
    );
  }
}

/// Mijozlar qarzi — KOMPANIYA doirasi (`/reports/dashboard`, `branch_id` siz).
/// Yagona karta: [note] hamon "Barcha filiallar" bo'lishi mumkin.
class _DebtCard extends StatelessWidget {
  final DebtInfo d;
  final String? note;
  const _DebtCard({super.key, required this.d, this.note});
  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text(tr('Mijozlar qarzi'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 8),
          Text('${d.debtors} ${tr('qarzdor')}', style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
        ]),
        _noteLine(note),
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: _mini(tr('Umumiy qarz'), money(d.total), AppColors.warn)),
          Expanded(child: _mini(tr('Bugun to‘landi'), money(d.paidToday), AppColors.ok)),
        ]),
      ]),
    );
  }

  Widget _mini(String l, String v, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l, style: TextStyle(fontSize: 12, color: AppColors.muted)),
        const SizedBox(height: 4),
        Text(v, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c)),
      ]);
}

/// Kategoriyalar — joriy doira (`/reports/categories?branch_id=`), yozuvsiz.
class _CatCard extends StatelessWidget {
  final List<CatRow> cats;
  const _CatCard({super.key, required this.cats});
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
                  Text('${c.margin}%', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
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
                    valueColor: AlwaysStoppedAnimation(AppColors.accent),
                  ),
                ),
              ]),
            )),
      ]),
    );
  }
}

Widget _navCard(BuildContext context, Key key, IconData ic, String label, Widget screen) => Material(
      color: AppColors.card,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        key: key,
        borderRadius: BorderRadius.circular(14),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen)),
        child: Container(
          constraints: const BoxConstraints(minHeight: 52),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
          decoration:
              BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Icon(ic, size: 19, color: AppColors.accentStrong),
            const SizedBox(width: 10),
            Expanded(child: Text(label, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600))),
            Icon(Icons.chevron_right, size: 16, color: AppColors.muted),
          ]),
        ),
      ),
    );

/// Yuklanish skeleti — spinner o'rniga (dizayn: "skeleton loading"). Statik:
/// cheksiz animatsiya yo'q (testlarda `pumpAndSettle` to'xtaydi, batareya tejaladi).
class _AnalyticsSkeleton extends StatelessWidget {
  const _AnalyticsSkeleton();

  Widget _box(double h, {double? w, double r = 12}) => Container(
      height: h, width: w, decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(r)));

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: tr('Yuklanmoqda…'),
      child: Column(key: const Key('analytics-skeleton'), children: [
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

/// Naqd oqim — joriy doira (`/reports/cashflow?branch_id=`), yozuvsiz.
class _CashFlowCard extends StatelessWidget {
  final CashFlow cf;
  const _CashFlowCard({super.key, required this.cf});

  Widget _row(String label, double v, Color c) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(child: Text(label, style: TextStyle(fontSize: 12.5, color: AppColors.text3))),
          Text(money(v), style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: c)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.account_balance_wallet_outlined, size: 18, color: AppColors.accentStrong),
          const SizedBox(width: 8),
          Expanded(child: Text(tr('Naqd oqim'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700))),
        ]),
        const SizedBox(height: 12),
        // Kassada qoldi
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(13)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('Kassada naqd'), style: TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 3),
            Text(money(cf.kassada),
                style: TextStyle(
                    fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.accentStrong, letterSpacing: -0.5)),
          ]),
        ),
        const SizedBox(height: 14),
        // Kirim (to'liq enlik — katta summalar sig'sin, ustma-ust chiqmasin)
        Row(children: [
          const Icon(Icons.south_west, size: 14, color: AppColors.ok),
          const SizedBox(width: 5),
          Expanded(
              child: Text('${tr('Kirim')} · ${money(cf.inJami)}',
                  style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.ok))),
        ]),
        const SizedBox(height: 4),
        _row(tr('Naqd savdo'), cf.inNaqd, AppColors.text3),
        _row(tr('Qarz qaytdi'), cf.inQarz, AppColors.text3),
        _row(tr('Qo‘shimcha'), cf.inQosh, AppColors.text3),
        Divider(height: 20, color: AppColors.border),
        // Chiqim (to'liq enlik)
        Row(children: [
          const Icon(Icons.north_east, size: 14, color: AppColors.danger),
          const SizedBox(width: 5),
          Expanded(
              child: Text('${tr('Chiqim')} · ${money(cf.outJami)}',
                  style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.danger))),
        ]),
        const SizedBox(height: 4),
        _row(tr('Xarajat'), cf.outXarajat, AppColors.text3),
        _row(tr('Inkassatsiya'), cf.outInkassa, AppColors.text3),
        _row(tr('Qaytarish'), cf.outQaytarish, AppColors.text3),
        if (cf.outBeruvchi > 0) _row(tr('Beruvchiga'), cf.outBeruvchi, AppColors.text3),
      ]),
    );
  }
}

class _AlertBanner extends StatelessWidget {
  final int low, out;
  final VoidCallback? onTap;
  const _AlertBanner({required this.low, required this.out, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final parts = <String>[];
    if (out > 0) parts.add('$out ${tr('tugagan')}');
    if (low > 0) parts.add('$low ${tr('kam qolgan')}');
    return Material(
      key: const Key('analytics-stock-alert'),
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
            Expanded(
                child: Text('${tr('Diqqat')}: ${parts.join(' · ')} ${tr('mahsulot')}',
                    style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: AppColors.text2))),
            if (onTap != null) const Icon(Icons.chevron_right, color: AppColors.warn),
          ]),
        ),
      ),
    );
  }
}

/// Soatlik savdo — joriy doira (`/reports/hourly?branch_id=`), yozuvsiz.
class _HourCard extends StatelessWidget {
  final List<HourPoint> hours;
  const _HourCard({super.key, required this.hours});
  @override
  Widget build(BuildContext context) {
    // Faol oraliq: birinchi va oxirgi savdoli soat
    int lo = 0, hi = 23;
    while (lo < 23 && hours[lo].sales == 0) {
      lo++;
    }
    while (hi > lo && hours[hi].sales == 0) {
      hi--;
    }
    final slice = hours.sublist(lo, hi + 1);
    final maxV = slice.map((e) => e.sales).fold<double>(1, (a, b) => b > a ? b : a);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(tr('Bugun — soatlik savdo'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 16),
        SizedBox(
          height: 110,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: slice.map((p) {
              return Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2.5),
                  child: Column(children: [
                    // Ulush klamp qilinadi (bir soatning sof savdosi manfiy bo'lishi mumkin:
                    // kechagi chekni ertalab qaytarish) — manfiy balandlik crash bermaydi.
                    Expanded(
                      child: _Bar(
                        fraction: maxV <= 0 ? 0 : p.sales / maxV,
                        color: p.sales > 0 ? AppColors.accent : AppColors.border,
                        radius: 4,
                      ),
                    ),
                    const SizedBox(height: 6),
                    _BarLabel('${p.hour}', size: 9.5, color: AppColors.muted),
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

  /// `sales.receipt`: a row opens the server receipt of that sale.
  final bool canOpen;
  const _RecentCard({required this.rows, required this.canOpen});

  static const Map<String, String> _methods = {'cash': 'Naqd', 'card': 'Karta', 'credit': 'Qarz'};

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
              child: Text(tr('So‘nggi sotuvlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
          TextButton(
            key: const Key('recent-all'),
            style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SalesListScreen())),
            child: Text(tr('Barchasi →'),
                style: TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600)),
          ),
        ]),
        const SizedBox(height: 4),
        for (final s in rows) _row(context, s),
      ]),
    );
  }

  /// One sale (≥ 48 dp tall); with `sales.receipt` it opens the server receipt.
  Widget _row(BuildContext context, SaleRow s) {
    final row = Padding(
      padding: const EdgeInsets.fromLTRB(0, 2, 8, 10),
      child: Row(children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(10)),
          child: Icon(Icons.receipt_long, color: AppColors.accentStrong, size: 18),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(s.firstItem.isEmpty ? s.receiptNo : s.firstItem,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            Text([hm(s.at), if (s.cashier.isNotEmpty) s.cashier].join(' · '),
                maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        const SizedBox(width: 8),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(money(s.total), style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800)),
          Text(_methods[s.method] == null ? s.method.toUpperCase() : tr(_methods[s.method]!),
              style: TextStyle(fontSize: 11, color: AppColors.muted)),
        ]),
      ]),
    );
    if (!canOpen || s.id.isEmpty) return row;
    return InkWell(
      key: Key('recent-sale-${s.id}'),
      borderRadius: BorderRadius.circular(10),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => SalesDetailScreen(saleId: s.id, receiptNo: s.receiptNo.isEmpty ? null : s.receiptNo))),
      child: row,
    );
  }
}

/// A bottom-aligned chart bar filling [fraction] of the available height
/// (clamped: never negative, never invisible).
class _Bar extends StatelessWidget {
  const _Bar({required this.fraction, required this.color, this.radius = 6});
  final double fraction;
  final Color color;
  final double radius;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.bottomCenter,
        child: FractionallySizedBox(
          widthFactor: 1,
          heightFactor: fraction.isNaN ? 0.03 : fraction.clamp(0.03, 1.0),
          child: DecoratedBox(decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(radius))),
        ),
      );
}

/// One-line chart label that shrinks instead of wrapping or overflowing.
class _BarLabel extends StatelessWidget {
  const _BarLabel(this.text, {required this.size, required this.color});
  final String text;
  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) => FittedBox(
        fit: BoxFit.scaleDown,
        child: Text(text, maxLines: 1, softWrap: false, style: TextStyle(fontSize: size, color: color)),
      );
}
