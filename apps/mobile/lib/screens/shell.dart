import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../permissions.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'analytics_screen.dart';
import 'cash_ops_screen.dart';
import 'home_screen.dart';
import 'inventarizatsiya_screen.dart';
import 'inventory_screen.dart';
import 'login_screen.dart';
import 'pin_screens.dart';
import 'receiving_home_screen.dart';
import 'settings_screen.dart';
import 'transfer_screen.dart';
import 'writeoff_screen.dart';

/// Bottom-navigation tabs. The ids are LOGICAL and stable: a hidden tab keeps
/// its id, so `HomeScreen(onTab: 2)` always means the stock tab.
enum ShellTab {
  /// Bosh — always visible.
  home,

  /// Analitika — only with `hisobot.view` (`reports.overview`).
  analytics,

  /// Ombor — stock / product list (desktop Sidebar: `ombor.view` or `mahsulotlar.view`).
  stock,

  /// Sozlama — always visible.
  settings,
}

/// Entries of the "+" (new operation) sheet.
enum ShellAction {
  /// Tovar qabul (receiving: new or history).
  receiving,

  /// Hisobdan chiqarish.
  writeoff,

  /// Inventarizatsiya.
  count,

  /// Kassa kirim / chiqim.
  cash,

  /// Filiallararo transfer.
  transfer,
}

/// Permissions that open the stock tab — mirrors the desktop Manager sidebar
/// (`qoldiq`: `ombor.view`, `mahsulotlar`: `mahsulotlar.view`).
const List<String> kStockTabPerms = ['ombor.view', 'mahsulotlar.view'];

/// What the signed-in employee SEES in the shell.
///
/// UX ONLY: hiding a tab or an action never grants or denies anything — every
/// screen's request is still checked by the server. The rules are:
/// * navigation (tabs, "+" entries, menu rows) is HIDDEN without the permission;
/// * a write button on a screen the employee can open is shown DISABLED with
///   the reason (`Perm.reason`).
class ShellGates {
  ShellGates._();

  /// Whether [tab] is shown.
  static bool tabVisible(ShellTab tab, {Session? session}) {
    final s = session ?? Session.instance;
    switch (tab) {
      case ShellTab.home:
      case ShellTab.settings:
        return true;
      case ShellTab.analytics:
        return Perm.allows('reports.overview', session: s);
      case ShellTab.stock:
        return s.canAny(kStockTabPerms);
    }
  }

  /// Visible tabs in bar order.
  static List<ShellTab> visibleTabs({Session? session}) => [
        for (final t in ShellTab.values)
          if (tabVisible(t, session: session)) t
      ];

  /// Whether the "+" sheet offers [a] (also used by Home's quick actions).
  ///
  /// Each entry is gated by the matrix action of the WRITE it leads to
  /// (receiving also opens its history, so either one is enough).
  static bool actionAllowed(ShellAction a, {Session? session}) {
    bool p(String action) => Perm.allows(action, session: session);
    return switch (a) {
      ShellAction.receiving => p('receiving.commit') || p('receiving.history'),
      ShellAction.writeoff => p('stock.writeoff'),
      ShellAction.count => p('stock.count'),
      ShellAction.cash => p('cash.ops.create'),
      ShellAction.transfer => p('stock.transfer'),
    };
  }

  /// Whether the notifications screen has anything this employee may read
  /// (stock summary / low list: `hisobot.view`; lot expiry: `ombor.view`).
  /// Without any of them the bell (Home) and the settings row are hidden.
  static bool notificationsVisible({Session? session}) =>
      Perm.allows('stock.overview', session: session) ||
      Perm.allows('stock.low', session: session) ||
      Perm.allows('lots.alerts', session: session);

  /// Whether the "Ombor" badge may be requested: stock tab shown AND the
  /// `/inventory/overview` gate (`stock.overview`) — no request that would 403.
  static bool stockBadgeAllowed({Session? session}) =>
      tabVisible(ShellTab.stock, session: session) && Perm.allows('stock.overview', session: session);

  /// Allowed "+" entries in sheet order (empty -> the "+" button is hidden).
  static List<ShellAction> actions({Session? session}) => [
        for (final a in ShellAction.values)
          if (actionAllowed(a, session: session)) a
      ];

  /// Tabs whose data depends on the current branch (header + rebuild on switch).
  static bool branchScoped(ShellTab tab) => tab != ShellTab.settings;
}

/// The signed-in app: branch header, tab bar, "+" sheet, connectivity banner,
/// re-lock after a long background stay.
///
/// * Tabs are built lazily (first visit) and kept alive afterwards.
/// * A branch switch REBUILDS every branch-scoped tab (new `State`, fresh
///   load with the new `branch_id`): data loaded for branch A can never stay on
///   screen under branch B, whatever the tab does internally.
/// * The shell waits for `/auth/context` before building any tab, so no
///   branch-scoped request is sent before the branch is known.
class Shell extends StatefulWidget {
  /// Creates the shell.
  const Shell({super.key, this.session, this.tabBuilders});

  /// Session (default [Session.instance]).
  final Session? session;

  /// Test hook: replaces the real screen of a tab.
  @visibleForTesting
  final Map<ShellTab, WidgetBuilder>? tabBuilders;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> with WidgetsBindingObserver {
  ShellTab _tab = ShellTab.home;
  final Set<ShellTab> _visited = {ShellTab.home};
  int _attention = 0;
  int _attentionSeq = 0;
  String? _attentionBranch;
  bool _lockShown = false;
  SessionStatus? _lastStatus;
  int _lastEpoch = -1;
  DateTime? _lastLoadedAt;

  Session get _s => widget.session ?? Session.instance;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _s.addListener(_onSession);
    Api.stockRev.addListener(_loadAttention);
    if (_s.status == SessionStatus.signedOut && Api.loggedIn) {
      unawaited(_s.load());
    }
    _lastStatus = _s.status;
    _lastEpoch = _s.branchEpoch;
    _lastLoadedAt = _s.loadedAt;
    if (_ready) _loadAttention();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _s.removeListener(_onSession);
    Api.stockRev.removeListener(_loadAttention);
    super.dispose();
  }

  bool get _ready => _s.status == SessionStatus.ready || _s.status == SessionStatus.degraded;

  void _onSession() {
    if (!mounted) return;
    final becameReady = _ready && _lastStatus != _s.status;
    final branchChanged = _lastEpoch != _s.branchEpoch;
    final reloaded = _lastLoadedAt != _s.loadedAt; // ruxsatlar yangilangan bo'lishi mumkin
    _lastStatus = _s.status;
    _lastEpoch = _s.branchEpoch;
    _lastLoadedAt = _s.loadedAt;
    setState(() {});
    if (becameReady || branchChanged || reloaded) _loadAttention();
  }

  // ── Qulf: fonda uzoq qolgach qaytishda PIN ──
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      Lock.markBackground();
    } else if (state == AppLifecycleState.resumed) {
      if (Lock.consumeResume() && !_lockShown && mounted) _showLock();
    }
  }

  void _showLock() {
    _lockShown = true;
    final nav = Navigator.of(context, rootNavigator: true);
    nav
        .push(PageRouteBuilder<void>(
          opaque: true,
          transitionDuration: Duration.zero,
          reverseTransitionDuration: const Duration(milliseconds: 150),
          pageBuilder: (ctx, _, __) => LockScreen(onUnlocked: () => Navigator.of(ctx).pop()),
        ))
        .whenComplete(() => _lockShown = false);
  }

  // ── Ombor badge ──
  // `/inventory/overview?branch_id=<current>` — the count of the CURRENT branch
  // (Phase 5G server: optional branch_id). A branch switch re-requests it and
  // clears the old number first, so branch A's count never sits under B.
  // Gated by the matrix action `stock.overview` (hisobot.view): a role without
  // it sends no request at all.
  Future<void> _loadAttention() async {
    final seq = ++_attentionSeq;
    final allowed = _ready && ShellGates.stockBadgeAllowed(session: _s);
    if (!allowed) {
      if (_attention != 0 && mounted) setState(() => _attention = 0);
      return;
    }
    final q = _s.branchQuery();
    if (_attentionBranch != _s.currentBranchId) {
      _attentionBranch = _s.currentBranchId;
      if (_attention != 0 && mounted) setState(() => _attention = 0);
    }
    try {
      final m = (await Api.getJson('/inventory/overview', query: q)).map;
      if (!mounted || seq != _attentionSeq) return;
      int n(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
      setState(() => _attention = n(m['low_count']) + n(m['out_count']));
    } catch (_) {
      // Badge — ixtiyoriy: Ombor tabining o'zi haqiqiy holatni ko'rsatadi.
    }
  }

  void _select(ShellTab t) {
    if (!ShellGates.tabVisible(t, session: _s)) return;
    setState(() {
      _tab = t;
      _visited.add(t);
    });
  }

  /// `onTab(int)` of the tab screens: logical index 0=home 1=analytics 2=stock 3=settings.
  void _goIndex(int i) {
    if (i < 0 || i >= ShellTab.values.length) return;
    _select(ShellTab.values[i]);
  }

  Widget _screenFor(ShellTab t) {
    final custom = widget.tabBuilders?[t];
    if (custom != null) return Builder(builder: custom);
    // DIQQAT: const EMAS — mavzu almashganda IndexedStack ichidagi tirik ekranlar
    // yangi ranglar bilan qayta qurilishi shart.
    return switch (t) {
      ShellTab.home => HomeScreen(onTab: _goIndex, session: widget.session),
      ShellTab.analytics => AnalyticsScreen(onTab: _goIndex, session: widget.session),
      // ignore: prefer_const_constructors
      ShellTab.stock => InventoryScreen(),
      // ignore: prefer_const_constructors
      ShellTab.settings => SettingsScreen(),
    };
  }

  Widget _tabBody(ShellTab t) {
    if (!_visited.contains(t)) return SizedBox.shrink(key: ValueKey('${t.name}-unvisited'));
    final key = ShellGates.branchScoped(t) ? ValueKey('${t.name}@${_s.branchEpoch}') : ValueKey(t.name);
    return KeyedSubtree(key: key, child: _screenFor(t));
  }

  void _openAmal() {
    final actions = ShellGates.actions(session: _s);
    if (actions.isEmpty) return;
    showAppSheet<void>(
      context,
      title: tr('Yangi operatsiya'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        for (final a in actions)
          _AmalRow(
            action: a,
            onTap: () {
              Navigator.of(ctx).pop();
              Navigator.of(context).push(MaterialPageRoute(builder: (_) => _actionScreen(a)));
            },
          ),
      ]),
    );
  }

  Widget _actionScreen(ShellAction a) => switch (a) {
        ShellAction.receiving => const ReceivingHomeScreen(),
        ShellAction.writeoff => const WriteoffScreen(),
        ShellAction.count => const InventarizatsiyaScreen(),
        ShellAction.cash => const CashOpsScreen(),
        ShellAction.transfer => const TransferScreen(),
      };

  @override
  Widget build(BuildContext context) {
    // Mavzu, til YOKI sessiya (ruxsat/filial) o'zgarganda butun qobiq qayta quriladi.
    return AnimatedBuilder(
      animation: Listenable.merge([AppTheme.version, L.version]),
      builder: (context, _) {
        final st = _s.status;
        if (st == SessionStatus.error) return _SessionError(session: _s);
        if (!_ready) return const _SessionLoading();
        final tabs = ShellGates.visibleTabs(session: _s);
        final tab = tabs.contains(_tab) ? _tab : ShellTab.home;
        final scoped = ShellGates.branchScoped(tab);
        final actions = ShellGates.actions(session: _s);
        return Scaffold(
          body: Column(children: [
            if (scoped) _BranchHeader(session: _s),
            Expanded(
              child: MediaQuery.removePadding(
                context: context,
                removeTop: scoped,
                child: IndexedStack(
                  index: tabs.indexOf(tab),
                  children: [for (final t in tabs) _tabBody(t)],
                ),
              ),
            ),
            const ConnectivityBanner(),
          ]),
          bottomNavigationBar: _BottomBar(
            tabs: tabs,
            current: tab,
            attention: _attention,
            onTab: _select,
            onAmal: actions.isEmpty ? null : _openAmal,
          ),
        );
      },
    );
  }
}

/// Until `/auth/context` is known nothing branch-scoped is built.
class _SessionLoading extends StatelessWidget {
  const _SessionLoading();

  @override
  Widget build(BuildContext context) => Scaffold(
        key: const Key('shell-loading'),
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const SizedBox(width: 32, height: 32, child: CircularProgressIndicator(strokeWidth: 3)),
            const SizedBox(height: 14),
            Text(tr('Yuklanmoqda…'), style: TextStyle(color: AppColors.muted, fontSize: 14)),
          ]),
        ),
      );
}

/// `/auth/context` could not be loaded and nothing is known yet: explicit
/// error with retry (no guessed permissions, no guessed branch).
class _SessionError extends StatelessWidget {
  const _SessionError({required this.session});
  final Session session;

  Future<void> _logout(BuildContext context) async {
    await Api.logout();
    await Lock.clear();
    if (!context.mounted) return;
    Navigator.of(context, rootNavigator: true)
        .pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        key: const Key('shell-error'),
        body: SafeArea(
          child: Column(children: [
            Expanded(
              child: ErrorState(
                error: session.lastError ?? StateError('auth/context'),
                onRetry: () => unawaited(session.load(force: true)),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: TextButton.icon(
                key: const Key('shell-error-logout'),
                style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
                onPressed: () => _logout(context),
                icon: const Icon(Icons.logout, size: 18),
                label: Text(tr('Hisobdan chiqish')),
              ),
            ),
          ]),
        ),
      );
}

/// Current branch strip above branch-scoped tabs (tap to switch when the
/// employee sees more than one active branch).
class _BranchHeader extends StatelessWidget {
  const _BranchHeader({required this.session});
  final Session session;

  void _explain(BuildContext context) {
    final cur = session.currentBranch, actor = session.actorBranch;
    if (cur == null || actor == null) return;
    showAppSheet<void>(
      context,
      title: tr('Filial haqida'),
      builder: (ctx) =>
          Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Text(
          trArgs(
              'Siz «{current}» filiali ma’lumotlarini ko‘ryapsiz. Tovar qabul va kassa amallari asosiy filialingizga — «{actor}» — yoziladi.',
              {'current': cur.name, 'actor': actor.name}),
          style: TextStyle(fontSize: 14.5, height: 1.4, color: AppColors.text2),
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: kPrimaryButtonHeight,
          child: OutlinedButton.icon(
            key: const Key('branch-back-to-actor'),
            onPressed: () async {
              Navigator.of(ctx).pop();
              if (session.selectableBranches.any((b) => b.id == actor.id)) await session.selectBranch(actor.id);
            },
            icon: const Icon(Icons.home_work_outlined),
            label: Text(trArgs('«{actor}» filialiga qaytish', {'actor': actor.name})),
          ),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final degraded = session.status == SessionStatus.degraded;
    final legacyName = '${Api.employee?['branch_name'] ?? ''}';
    final showHint =
        !degraded && session.currentBranch != null && session.actorBranch != null && !session.currentIsActor;
    final noBranch = !degraded && session.currentBranch == null && session.branches.length > 1;
    return Material(
      color: Colors.transparent,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 2, 4, 0),
          child: Row(children: [
            Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: degraded
                    ? ConstrainedBox(
                        key: const Key('branch-legacy'),
                        constraints: const BoxConstraints(minHeight: kMinTouch),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          child: Row(mainAxisSize: MainAxisSize.min, children: [
                            Icon(Icons.store_mall_directory_outlined, size: 18, color: AppColors.accentStrong),
                            const SizedBox(width: 6),
                            Flexible(
                              child: Text(legacyName.isEmpty ? tr('Filial tanlanmagan') : legacyName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style:
                                      TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text2)),
                            ),
                          ]),
                        ),
                      )
                    : BranchChip(session: session),
              ),
            ),
            if (noBranch)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Text(tr('Filialni tanlang'),
                    key: const Key('branch-pick-hint'),
                    style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.warn)),
              ),
            if (showHint)
              IconButton(
                key: const Key('branch-actor-hint'),
                tooltip: tr('Filial haqida'),
                constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                onPressed: () => _explain(context),
                icon: const Icon(Icons.info_outline, color: AppColors.warn),
              ),
          ]),
        ),
      ),
    );
  }
}

class _AmalRow extends StatelessWidget {
  const _AmalRow({required this.action, required this.onTap});
  final ShellAction action;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (IconData ic, String title, String sub, Color c) = switch (action) {
      ShellAction.receiving => (Icons.document_scanner, tr('Tovar qabul'), tr('Nakladnoyni skanerlash'), AppColors.ok),
      ShellAction.writeoff => (
          Icons.remove_circle_outline,
          tr('Hisobdan chiqarish'),
          tr('Brak, muddati o‘tgan'),
          AppColors.danger
        ),
      ShellAction.count => (Icons.fact_check_outlined, tr('Inventarizatsiya'), tr('Qoldiqni sanash'), AppColors.warn),
      ShellAction.cash => (
          Icons.account_balance_wallet_outlined,
          tr('Kassa kirim / chiqim'),
          tr('Naqd pul harakati'),
          AppColors.accentStrong
        ),
      ShellAction.transfer => (
          Icons.swap_horiz,
          tr('Filiallararo transfer'),
          tr('Do‘konlar orasida'),
          AppColors.accentStrong
        ),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(kRadius),
        child: InkWell(
          key: Key('amal-${action.name}'),
          borderRadius: BorderRadius.circular(kRadius),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
                child: Icon(ic, color: c, size: 22),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                  Text(sub, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              Icon(Icons.chevron_right, color: AppColors.faint),
            ]),
          ),
        ),
      ),
    );
  }
}

// Telegram uslubidagi suzuvchi kapsula bar: faol tab orqasidagi tanlov pufagi
// BARMOQ bilan surilganda suzib ergashadi (drag), qo'yib yuborilganda eng yaqin
// tabga qo'nadi; oddiy bosishda ham suzib o'tadi. O'ngda alohida dumaloq "+" tugma
// (faqat kamida bitta amal ruxsat etilganda).
class _BottomBar extends StatefulWidget {
  const _BottomBar({
    required this.tabs,
    required this.current,
    required this.attention,
    required this.onTab,
    required this.onAmal,
  });
  final List<ShellTab> tabs;
  final ShellTab current;
  final int attention;
  final void Function(ShellTab) onTab;
  final VoidCallback? onAmal;

  @override
  State<_BottomBar> createState() => _BottomBarState();
}

class _BottomBarState extends State<_BottomBar> {
  static const Map<ShellTab, (IconData, IconData, String)> _spec = {
    ShellTab.home: (Icons.home_outlined, Icons.home, 'Bosh'),
    ShellTab.analytics: (Icons.bar_chart_outlined, Icons.bar_chart, 'Analitika'),
    ShellTab.stock: (Icons.warehouse_outlined, Icons.warehouse, 'Ombor'),
    ShellTab.settings: (Icons.settings_outlined, Icons.settings, 'Sozlama'),
  };

  double? _dragLeft; // sudralayotganda pufak chap chekkasi (px); null = normal
  double _cellW = 0;

  int get _n => widget.tabs.length;
  int get _currentIdx => widget.tabs.indexOf(widget.current).clamp(0, _n - 1);

  int _idxAt(double x) => _cellW <= 0 ? 0 : (x / _cellW).clamp(0, _n - 1).floor();

  void _panUpdate(double localX) {
    final left = (localX - _cellW / 2).clamp(0.0, _cellW * (_n - 1));
    setState(() => _dragLeft = left);
  }

  void _panEnd() {
    if (_dragLeft == null) return;
    final idx = _idxAt(_dragLeft! + _cellW / 2);
    setState(() => _dragLeft = null);
    if (idx != _currentIdx) widget.onTab(widget.tabs[idx]);
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).padding.bottom;
    final hi = _dragLeft != null ? _idxAt(_dragLeft! + _cellW / 2) : _currentIdx;
    return Container(
      color: Colors.transparent,
      padding: EdgeInsets.fromLTRB(12, 8, 12, (bottom > 0 ? bottom : 10)),
      child: Row(children: [
        Expanded(
          child: Container(
            height: 62,
            decoration: BoxDecoration(
              color: AppColors.card.withValues(alpha: 0.96),
              borderRadius: BorderRadius.circular(31),
              border: Border.all(color: AppColors.border),
              boxShadow: [
                BoxShadow(color: Colors.black.withValues(alpha: 0.22), blurRadius: 18, offset: const Offset(0, 6))
              ],
            ),
            child: LayoutBuilder(builder: (context, cons) {
              _cellW = cons.maxWidth / _n;
              final left = (_dragLeft ?? (_currentIdx * _cellW)) + 5;
              return GestureDetector(
                behavior: HitTestBehavior.translucent,
                onHorizontalDragStart: (d) => _panUpdate(d.localPosition.dx),
                onHorizontalDragUpdate: (d) => _panUpdate(d.localPosition.dx),
                onHorizontalDragEnd: (_) => _panEnd(),
                onHorizontalDragCancel: _panEnd,
                child: Stack(children: [
                  AnimatedPositioned(
                    duration: _dragLeft != null ? Duration.zero : const Duration(milliseconds: 340),
                    curve: Curves.easeOutBack,
                    left: left,
                    top: 5,
                    width: _cellW - 10,
                    height: 52,
                    child: AnimatedScale(
                      scale: _dragLeft != null ? 1.18 : 1.0,
                      duration: const Duration(milliseconds: 160),
                      curve: Curves.easeOut,
                      child: Container(
                        decoration: BoxDecoration(
                          color: AppColors.accentSoft,
                          borderRadius: BorderRadius.circular(26),
                          boxShadow: _dragLeft != null
                              ? [
                                  BoxShadow(
                                      color: AppColors.accent.withValues(alpha: 0.4),
                                      blurRadius: 18,
                                      offset: const Offset(0, 5))
                                ]
                              : null,
                        ),
                      ),
                    ),
                  ),
                  Row(children: [for (var i = 0; i < _n; i++) _tab(i, hi, _dragLeft != null)]),
                ]),
              );
            }),
          ),
        ),
        if (widget.onAmal != null) ...[
          const SizedBox(width: 10),
          Semantics(
            button: true,
            label: tr('Yangi operatsiya'),
            child: GestureDetector(
              key: const Key('shell-amal'),
              onTap: widget.onAmal,
              child: Container(
                width: 62,
                height: 62,
                decoration: BoxDecoration(
                  color: AppColors.accent,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                        color: AppColors.accent.withValues(alpha: 0.45), blurRadius: 16, offset: const Offset(0, 5))
                  ],
                ),
                child: const Icon(Icons.add, color: Colors.white, size: 30),
              ),
            ),
          ),
        ],
      ]),
    );
  }

  Widget _tab(int i, int hi, bool dragging) {
    final t = widget.tabs[i];
    final (off, on, label) = _spec[t]!;
    final sel = hi == i;
    final color = sel ? AppColors.accentStrong : AppColors.muted;
    final badge = t == ShellTab.stock ? widget.attention : 0;
    Widget icon = Icon(sel ? on : off, color: color, size: 22);
    if (badge > 0) {
      icon =
          Badge(key: const Key('stock-badge'), label: Text('$badge'), backgroundColor: AppColors.danger, child: icon);
    }
    return Expanded(
      child: Semantics(
        button: true,
        selected: t == widget.current,
        label: tr(label),
        excludeSemantics: true,
        child: GestureDetector(
          key: Key('tab-${t.name}'),
          behavior: HitTestBehavior.opaque,
          onTap: () => widget.onTab(t),
          child: AnimatedScale(
            scale: sel ? (dragging ? 1.18 : 1.06) : 1.0,
            duration: const Duration(milliseconds: 160),
            curve: Curves.easeOut,
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              icon,
              const SizedBox(height: 3),
              Text(tr(label),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 10.5, fontWeight: sel ? FontWeight.w700 : FontWeight.w600, color: color)),
            ]),
          ),
        ),
      ),
    );
  }
}
