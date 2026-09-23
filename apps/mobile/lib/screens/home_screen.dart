import 'package:flutter/material.dart';
import '../api.dart';
import '../api/stock_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'customers_screen.dart';
import 'notifications_screen.dart';
import 'receiving_home_screen.dart';
import 'sales_detail_screen.dart';
import 'sales_list_screen.dart';
import 'shell.dart';

/// Bosh sahifa — bugun bir qarashda + tez amallar (BILLZ uslubida).
///
/// FILIAL DOIRASI: bugungi savdo (`/reports/overview`), so'nggi sotuvlar
/// (`/sales`) va ombor xulosasi (`/inventory/overview`) JORIY filial bo'yicha
/// (`branch_id`) so'raladi; partiya muddatlari — `/lots/alerts?branch_id=`.
/// Filial almashsa hammasi qayta so'raladi va eski filial raqamlari yangi filial
/// ostida ko'rinmaydi.
///
/// RUXSATLAR (faqat UX, server baribir tekshiradi): har bo'lim/tugma o'z
/// matritsa amali bilan — ruxsat yo'q bo'lim ko'rsatilmaydi va so'ralmaydi
/// (403 kutilmaydi).
class HomeScreen extends StatefulWidget {
  /// Pastki nav'ga o'tish: mantiqiy indeks (`ShellTab.index`).
  final void Function(int index)? onTab;

  /// Sessiya (standart: [Session.instance]).
  final Session? session;

  const HomeScreen({super.key, this.onTab, this.session});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Future<Overview>? _ov;
  Future<List<SaleRow>>? _recent;
  Future<_Attention>? _attn;

  /// Filial, ma'lumot oxirgi marta shu filial uchun so'ralgan.
  String? _loadedBranch;

  /// Ruxsatlar imzosi — sessiya qayta yuklanib ruxsat o'zgarsa qayta so'raladi.
  String _gateSig = '';
  bool _reloadPending = false;

  Session get _s => widget.session ?? Session.instance;

  bool get _canOverview => Perm.allows('reports.overview', session: _s);
  bool get _canSales => Perm.allows('sales.list', session: _s);
  bool get _canReceipt => Perm.allows('sales.receipt', session: _s);
  bool get _canStockOverview => Perm.allows('stock.overview', session: _s);
  bool get _canLotAlerts => Perm.allows('lots.alerts', session: _s);

  String _sig() => '$_canOverview|$_canSales|$_canStockOverview|$_canLotAlerts';

  @override
  void initState() {
    super.initState();
    _s.addListener(_onSession);
    Api.stockRev.addListener(_onStock);
    _load();
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    Api.stockRev.removeListener(_onStock);
    super.dispose();
  }

  // Filial yoki ruxsat o'zgarsa — eski ma'lumot DARHOL tozalanadi (A filial
  // raqami B ostida bir kadr ham turmaydi) va kadrdan keyin qayta so'raladi:
  // qobiq ichida filial almashsa bu State baribir yangisiga almashadi, shunda
  // eski State ortiqcha so'rov yubormaydi. Aks holda faqat qayta chiziladi
  // (tez amallar ruxsatga bog'liq).
  void _onSession() {
    if (!mounted) return;
    if (_s.currentBranchId == _loadedBranch && _sig() == _gateSig) {
      setState(() {});
      return;
    }
    setState(() {
      _loadedBranch = _s.currentBranchId;
      _gateSig = _sig();
      _ov = null;
      _recent = null;
      _attn = null;
    });
    if (_reloadPending) return;
    _reloadPending = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _reloadPending = false;
      if (mounted) _load();
    });
  }

  void _onStock() {
    if (!mounted) return;
    final f = _loadAttention();
    setState(() {
      _attn = f;
    });
  }

  Future<Overview> _loadOverview(Map<String, String> branch) async =>
      Overview.fromJson((await Api.getJson('/reports/overview', query: {'period': 'day', ...branch})).map);

  Future<List<SaleRow>> _loadRecent(Map<String, String> branch) async {
    final rows = (await Api.getJson('/sales', query: {'limit': 3, ...branch})).list;
    return [
      for (final e in rows)
        if (e is Map) SaleRow.fromJson(e.cast<String, dynamic>())
    ];
  }

  Future<StockOverview> _loadStockOverview(Map<String, String> branch) async =>
      StockOverview.fromJson((await Api.getJson('/inventory/overview', query: branch)).map);

  /// Diqqat kartasi — BUTUN katalog (/products) emas, server xulosalari:
  /// `/inventory/overview?branch_id=` (hisobot.view) va `/lots/alerts?branch_id=`
  /// (ombor.view). Ruxsat yo'q manba so'ralmaydi (403 kutilmaydi) — plitkasi
  /// ko'rsatilmaydi.
  Future<_Attention> _loadAttention() async {
    final branch = _s.currentBranchId;
    final q = _s.branchQuery();
    final stock = _canStockOverview ? _loadStockOverview(q) : null;
    final lots = _canLotAlerts ? StockApi.lotAlerts(branchId: branch) : null;
    StockOverview? o;
    LotAlerts? a;
    try {
      o = await stock;
    } catch (_) {}
    try {
      a = await lots;
    } catch (_) {}
    return _Attention(o, a);
  }

  Future<void> _load() {
    final q = _s.branchQuery();
    _loadedBranch = _s.currentBranchId;
    _gateSig = _sig();
    final ov = _canOverview ? _loadOverview(q) : null;
    final rec = _canSales ? _loadRecent(q) : null;
    final attn = _loadAttention();
    setState(() {
      _ov = ov;
      _recent = rec;
      _attn = attn;
    });
    // Pull-to-refresh indikatori ma'lumot KELGUNCHA aylansin (ilgari darhol yo'qolardi)
    return Future.wait<dynamic>([if (ov != null) ov, if (rec != null) rec, attn]).then((_) {}).catchError((_) {});
  }

  void _push(Widget screen) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));

  @override
  Widget build(BuildContext context) {
    final name = (Api.employee?['full_name'] ?? '').toString().split(' ').first;
    // Filial kaliti: yangi filialning FutureBuilder'lari eski filial ma'lumotini
    // (AsyncSnapshot.data) meros olmaydi.
    final bk = _loadedBranch ?? '-';
    final quick = <Widget>[
      if (ShellGates.actionAllowed(ShellAction.receiving, session: _s))
        _quick(const Key('home-quick-receiving'), Icons.add_box_rounded, tr('Yangi\nqabul'), AppColors.ok,
            () => _push(const ReceivingHomeScreen())),
      if (_canSales)
        _quick(const Key('home-quick-sales'), Icons.receipt_long, tr('Sotuvlar'), AppColors.accentStrong,
            () => _push(const SalesListScreen())),
      if (widget.onTab != null && ShellGates.tabVisible(ShellTab.stock, session: _s))
        _quick(const Key('home-quick-stock'), Icons.warehouse, tr('Ombor'), const Color(0xFF4EA8DE),
            () => widget.onTab?.call(ShellTab.stock.index)),
      if (Perm.allows('customers.list', session: _s))
        _quick(const Key('home-quick-debtors'), Icons.account_balance_wallet, tr('Qarzdorlar'), AppColors.warn,
            () => _push(const CustomersScreen(onlyDebt: true))),
    ];
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
                if (ShellGates.notificationsVisible(session: _s))
                  _iconBtn(const Key('home-bell'), Icons.notifications_outlined, tr('Bildirishnomalar'),
                      () => _push(const NotificationsScreen())),
              ]),
              const SizedBox(height: 18),

              // Bugungi savdo (hero) — faqat hisobot.view bilan
              if (_canOverview) ...[
                FutureBuilder<Overview>(
                  key: ValueKey('home-hero@$bk'),
                  future: _ov,
                  builder: (context, snap) {
                    final ov = snap.data;
                    return Container(
                      key: const Key('home-hero'),
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        // Mavzuga mos hero: accent gradient + doim OQ matn (har 9 mavzuda o'qiladi)
                        gradient: LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [AppColors.accent, Color.lerp(AppColors.accent, Colors.black, 0.35)!],
                        ),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(color: AppColors.accentBorder),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(tr('Bugungi savdo'), style: const TextStyle(fontSize: 13, color: Color(0xD9FFFFFF))),
                        const SizedBox(height: 6),
                        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                          Flexible(
                            child: FittedBox(
                              fit: BoxFit.scaleDown,
                              alignment: Alignment.centerLeft,
                              child: Text(ov == null ? '—' : money(ov.sales),
                                  key: const Key('home-hero-sales'),
                                  style: const TextStyle(
                                      fontSize: 30,
                                      fontWeight: FontWeight.w800,
                                      letterSpacing: -0.5,
                                      color: Colors.white)),
                            ),
                          ),
                          const SizedBox(width: 10),
                          if (ov?.dSales != null) _deltaChip(ov!.dSales!),
                        ]),
                      ]),
                    );
                  },
                ),
                const SizedBox(height: 18),
              ],

              // Tez amallar — har biri o'z ruxsati bilan
              if (quick.isNotEmpty) ...[
                Row(children: quick),
                const SizedBox(height: 22),
              ],

              // Diqqat
              FutureBuilder<_Attention>(
                key: ValueKey('home-attention@$bk'),
                future: _attn,
                builder: (context, snap) {
                  final d = snap.data;
                  final o = d?.stock, a = d?.lots;
                  if (o == null && a == null) return const SizedBox.shrink();
                  final tiles = <Widget>[
                    if (o != null) _attnTile(o.lowCount, tr('kam qolgan'), AppColors.warn),
                    if (o != null) _attnTile(o.outCount, tr('tugagan'), AppColors.danger),
                    // Partiyalar muddati — FILIAL biznes sanasi bo'yicha (o'tgan + bugun + 7 kun)
                    if (a != null) _attnTile(a.urgentLots, tr('muddati yaqin/o‘tgan'), AppColors.warn),
                  ];
                  return GestureDetector(
                    key: const Key('home-attention'),
                    onTap: () => _push(const NotificationsScreen()),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        const Icon(Icons.warning_amber_rounded, size: 16, color: AppColors.warn),
                        const SizedBox(width: 8),
                        Text(tr('Diqqat'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                      ]),
                      const SizedBox(height: 12),
                      Row(children: [
                        for (var i = 0; i < tiles.length; i++) ...[
                          if (i > 0) const SizedBox(width: 10),
                          tiles[i],
                        ],
                      ]),
                      const SizedBox(height: 22),
                    ]),
                  );
                },
              ),

              // So'nggi sotuvlar — faqat sotuvlar.view bilan
              if (_canSales) ...[
                Row(children: [
                  Expanded(
                    child:
                        Text(tr('So‘nggi sotuvlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                  ),
                  TextButton(
                    key: const Key('home-sales-all'),
                    style: TextButton.styleFrom(
                        minimumSize: const Size(kMinTouch, kMinTouch),
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        tapTargetSize: MaterialTapTargetSize.padded),
                    onPressed: () => _push(const SalesListScreen()),
                    child: Text(tr('Barchasi'),
                        style: TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600)),
                  ),
                ]),
                const SizedBox(height: 4),
                FutureBuilder<List<SaleRow>>(
                  key: ValueKey('home-recent@$bk'),
                  future: _recent,
                  builder: (context, snap) {
                    if (snap.hasError && snap.data == null) {
                      // Xato "bugun sotuv yo'q" deb ko'rsatilmaydi — aniq xabar + qayta urinish.
                      return ErrorBanner(key: const Key('home-sales-error'), error: snap.error!, onRetry: _load);
                    }
                    final rows = snap.data;
                    if (rows == null) {
                      return const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Center(
                            child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5))),
                      );
                    }
                    if (rows.isEmpty) {
                      return Padding(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          child: Text(tr('Bugun sotuv yo‘q'),
                              key: const Key('home-sales-empty'), style: TextStyle(color: AppColors.muted)));
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
            ],
          ),
        ),
      ),
    );
  }

  Widget _iconBtn(Key key, IconData ic, String label, VoidCallback onTap) => Semantics(
        button: true,
        label: label,
        child: GestureDetector(
          key: key,
          onTap: onTap,
          child: Container(
            width: kMinTouch,
            height: kMinTouch,
            decoration: BoxDecoration(
                color: AppColors.card,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.border)),
            child: Icon(ic, color: AppColors.accentStrong, size: 22),
          ),
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

  Widget _quick(Key key, IconData ic, String label, Color c, VoidCallback onTap) => Expanded(
        child: GestureDetector(
          key: key,
          onTap: onTap,
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 4),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
            decoration: BoxDecoration(
                color: AppColors.card,
                borderRadius: BorderRadius.circular(15),
                border: Border.all(color: AppColors.border)),
            child: Column(children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
                child: Icon(ic, color: c, size: 20),
              ),
              const SizedBox(height: 8),
              Text(label,
                  textAlign: TextAlign.center,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppColors.text3, height: 1.2)),
            ]),
          ),
        ),
      );

  Widget _attnTile(int n, String label, Color c) => Expanded(
        child: Container(
          padding: const EdgeInsets.all(13),
          decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: n > 0 ? c.withValues(alpha: 0.35) : AppColors.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('$n', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: n > 0 ? c : AppColors.text)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: 11, color: AppColors.muted)),
          ]),
        ),
      );

  /// One recent sale; with `sales.receipt` it opens the server receipt.
  Widget _saleRow(SaleRow s, bool border) {
    final row = Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(s.receiptNo, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text('${hm(s.at)} · ${s.cashier}',
                maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        const SizedBox(width: 8),
        Text(money(s.total), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
      ]),
    );
    if (!_canReceipt || s.id.isEmpty) return row;
    return InkWell(
      key: Key('home-sale-${s.id}'),
      onTap: () => _push(SalesDetailScreen(saleId: s.id, receiptNo: s.receiptNo.isEmpty ? null : s.receiptNo)),
      child: row,
    );
  }
}

/// Home "attention" data: stock counts (hisobot.view) and lot expiry (ombor.view);
/// a part the user may not read is null (its tile is hidden).
class _Attention {
  const _Attention(this.stock, this.lots);
  final StockOverview? stock;
  final LotAlerts? lots;
}
