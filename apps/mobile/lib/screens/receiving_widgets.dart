import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/receiving_api.dart';
import '../l10n.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';

/// Small coloured label ("Partiya", "Yangi", "Arxivda").
class RecvBadge extends StatelessWidget {
  /// Creates a badge.
  const RecvBadge(this.text, {super.key, this.color});

  /// Label.
  final String text;

  /// Colour (default accent).
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.accentStrong;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: c.withAlpha(36), borderRadius: BorderRadius.circular(6)),
      child: Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
    );
  }
}

/// Badges describing a product's tracking / state.
List<Widget> productBadges(RecvProduct p) => [
      if (p.trackLots) RecvBadge(p.trackExpiry ? tr('Partiya · muddat') : tr('Partiya'), key: const Key('badge-tracked')),
      if (p.isWeighted) RecvBadge(tr('Tarozi'), color: AppColors.text3),
      if (!p.isActive) RecvBadge(tr('Arxivda'), color: AppColors.warn),
    ];

/// "Qabul filiali: X" — and, when the branch on screen is not the one the
/// server writes receivings to, an explicit notice with a switch button.
class ReceivingBranchBanner extends StatelessWidget {
  /// Creates the banner.
  const ReceivingBranchBanner({super.key, this.session});

  /// Session (default [Session.instance]).
  final Session? session;

  @override
  Widget build(BuildContext context) {
    final s = session ?? Session.instance;
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) {
        final st = RecvBranchState.of(s);
        switch (st.issue) {
          case RecvBranchIssue.none:
            return Semantics(
              label: trArgs('Qabul filiali: {name}', {'name': st.actor!.name}),
              child: Container(
                key: const Key('recv-branch'),
                constraints: const BoxConstraints(minHeight: 40),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
                child: Row(children: [
                  Icon(Icons.store_mall_directory_outlined, size: 18, color: AppColors.accentStrong),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(trArgs('Qabul filiali: {name}', {'name': st.actor!.name}),
                        style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text2)),
                  ),
                ]),
              ),
            );
          case RecvBranchIssue.loading:
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                const SizedBox(width: 10),
                Text(st.reason(), style: TextStyle(color: AppColors.muted)),
              ]),
            );
          case RecvBranchIssue.unknown:
            return ErrorBanner(
              key: const Key('recv-branch-unknown'),
              message: st.reason(),
              severity: BannerSeverity.warning,
              onRetry: () => s.load(force: true),
            );
          case RecvBranchIssue.mismatch:
            final actor = st.actor!;
            final canSwitch = s.selectableBranches.any((b) => b.id == actor.id);
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              ErrorBanner(key: const Key('recv-branch-mismatch'), message: st.reason(), severity: BannerSeverity.warning),
              if (canSwitch) ...[
                const SizedBox(height: 8),
                SizedBox(
                  height: kMinTouch,
                  child: OutlinedButton.icon(
                    key: const Key('recv-branch-switch'),
                    onPressed: () => s.selectBranch(actor.id),
                    icon: const Icon(Icons.swap_horiz),
                    label: Text(trArgs('«{name}» filialiga o‘tish', {'name': actor.name})),
                  ),
                ),
              ],
            ]);
        }
      },
    );
  }
}

// ── Product search sheet ───────────────────────────────────────────────────

/// Server-side product search (never the full catalog). Returns the chosen
/// product, or null. Tracking flags are OR-ed with [tracked].
Future<RecvProduct?> showRecvProductSearch(BuildContext context,
        {String initialQuery = '', TrackedCatalog? tracked}) =>
    showAppSheet<RecvProduct>(
      context,
      title: tr('Mahsulotni tanlang'),
      scrollable: false,
      maxHeightFactor: 0.92,
      builder: (ctx) => RecvProductSearch(initialQuery: initialQuery, tracked: tracked),
    );

/// Body of [showRecvProductSearch].
class RecvProductSearch extends StatefulWidget {
  /// Creates the search.
  const RecvProductSearch({super.key, this.initialQuery = '', this.tracked});

  /// Prefilled query (e.g. the name the AI read).
  final String initialQuery;

  /// Tracked products (flags).
  final TrackedCatalog? tracked;

  @override
  State<RecvProductSearch> createState() => _RecvProductSearchState();
}

class _RecvProductSearchState extends State<RecvProductSearch> {
  late final TextEditingController _q = TextEditingController(text: widget.initialQuery);
  Timer? _debounce;
  int _seq = 0;
  bool _loading = false;
  Object? _error;
  List<RecvProduct>? _rows;

  @override
  void initState() {
    super.initState();
    if (_q.text.trim().length >= 2) _search();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _q.dispose();
    super.dispose();
  }

  void _changed(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _search);
    setState(() {});
  }

  Future<void> _search() async {
    final q = _q.text.trim();
    final seq = ++_seq;
    if (q.length < 2) {
      setState(() {
        _rows = null;
        _loading = false;
        _error = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = await ReceivingApi.searchProducts(q);
      if (!mounted || seq != _seq) return;
      final t = widget.tracked;
      setState(() {
        _rows = [
          for (final p in rows)
            (t != null && t.isTracked(p.id) && !p.trackLots)
                ? p.withTracking(trackLots: true, trackExpiry: t.byId[p.id]!.trackExpiry)
                : p
        ];
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Widget _tile(RecvProduct p) {
    final stock = p.stockMilli;
    final sub = [
      if ((p.unitCode ?? '').isNotEmpty) p.unitCode!,
      if (stock != null) '${tr('Qoldiq')}: ${formatMilli(stock, group: true)}',
      if (p.buyCents != null && p.buyCents! > 0) '${tr('Kelish narxi')}: ${formatCents(p.buyCents!)}',
    ].join(' · ');
    return InkWell(
      key: Key('recv-search-${p.id}'),
      onTap: () => Navigator.of(context).pop(p),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 60),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: kGutter, vertical: 8),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(p.name, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                if (sub.isNotEmpty) Text(sub, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                if (productBadges(p).isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Wrap(spacing: 6, runSpacing: 4, children: productBadges(p)),
                ],
              ]),
            ),
            Icon(Icons.chevron_right, color: AppColors.faint),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final q = _q.text.trim();
    Widget body;
    if (_error != null) {
      body = Padding(padding: const EdgeInsets.all(kGutter), child: ErrorBanner(error: _error, onRetry: _search));
    } else if (q.length < 2) {
      body = EmptyState(text: tr('Kamida 2 ta harf yoki shtrix-kod raqamini yozing'), icon: Icons.search);
    } else if (_rows == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_rows!.isEmpty) {
      body = EmptyState(text: tr('Topilmadi'), icon: Icons.search_off);
    } else {
      body = ListView.separated(
        key: const Key('recv-search-list'),
        itemCount: _rows!.length,
        separatorBuilder: (_, __) => Divider(height: 1, color: AppColors.border),
        itemBuilder: (_, i) => _tile(_rows![i]),
      );
    }
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.7,
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 8),
          child: TextField(
            key: const Key('recv-search-field'),
            controller: _q,
            autofocus: true,
            textInputAction: TextInputAction.search,
            onChanged: _changed,
            onSubmitted: (_) {
              _debounce?.cancel();
              _search();
            },
            decoration: InputDecoration(
              hintText: tr('Mahsulot qidirish...'),
              prefixIcon: Icon(Icons.search, color: AppColors.muted),
              constraints: const BoxConstraints(minHeight: kMinTouch),
            ),
          ),
        ),
        if (_loading && _rows != null) const LinearProgressIndicator(minHeight: 2),
        Expanded(child: body),
      ]),
    );
  }
}

// ── Supplier picker ────────────────────────────────────────────────────────

/// The default supplier (the server's "Qabul (mobil)").
final SupplierRow kDefaultSupplier = SupplierRow(id: '', name: 'Qabul (mobil)', phone: null, balance: 0);

/// Supplier name to show ('' id -> localized default).
String supplierLabel(SupplierRow? s) => (s == null || s.id.isEmpty) ? tr('Qabul (mobil)') : s.name;

/// Bottom sheet with a filter; returns the chosen supplier ([kDefaultSupplier]
/// for the default), or null when closed.
Future<SupplierRow?> showRecvSupplierPicker(BuildContext context, List<SupplierRow> suppliers, {String? selectedId}) =>
    showAppSheet<SupplierRow>(
      context,
      title: tr('Yetkazib beruvchi'),
      scrollable: false,
      builder: (ctx) => _SupplierPicker(suppliers: suppliers, selectedId: selectedId),
    );

class _SupplierPicker extends StatefulWidget {
  const _SupplierPicker({required this.suppliers, this.selectedId});
  final List<SupplierRow> suppliers;
  final String? selectedId;

  @override
  State<_SupplierPicker> createState() => _SupplierPickerState();
}

class _SupplierPickerState extends State<_SupplierPicker> {
  final _q = TextEditingController();

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Widget _tile(SupplierRow s, {required String title, String? subtitle}) {
    final on = (widget.selectedId ?? '') == s.id;
    return InkWell(
      key: Key('recv-supplier-${s.id.isEmpty ? 'default' : s.id}'),
      onTap: () => Navigator.of(context).pop(s),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: kGutter),
          child: Row(children: [
            Icon(on ? Icons.radio_button_checked : Icons.radio_button_off, color: on ? AppColors.accentStrong : AppColors.muted),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                if (subtitle != null) Text(subtitle, style: const TextStyle(fontSize: 12, color: AppColors.danger)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final q = _q.text.trim().toLowerCase();
    final list = q.isEmpty ? widget.suppliers : widget.suppliers.where((s) => s.name.toLowerCase().contains(q)).toList();
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.6,
      child: Column(children: [
        if (widget.suppliers.length > 6)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 4, kGutter, 8),
            child: TextField(
              controller: _q,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(hintText: tr('Qidirish...'), prefixIcon: Icon(Icons.search, color: AppColors.muted)),
            ),
          ),
        Expanded(
          child: ListView(children: [
            _tile(kDefaultSupplier, title: tr('Qabul (mobil) — standart')),
            for (final s in list)
              _tile(s,
                  title: s.name,
                  subtitle: s.balance > 0 ? '${tr('Qarz')}: ${formatCents(centsFromNum(s.balance))}' : null),
          ]),
        ),
      ]),
    );
  }
}

// ── Line card ──────────────────────────────────────────────────────────────

/// One draft line in a document list: name, qty × cost = total, badges and
/// the first problem. Tap edits the line; the trailing button removes it.
class RecvLineCard extends StatelessWidget {
  /// Creates the card.
  const RecvLineCard({
    super.key,
    required this.line,
    required this.issues,
    required this.onTap,
    required this.onRemove,
    this.showIssues = true,
    this.extra,
  });

  /// The line.
  final RecvLine line;

  /// Its issues (first one is shown).
  final List<RecvIssue> issues;

  /// Edit.
  final VoidCallback onTap;

  /// Remove.
  final VoidCallback onRemove;

  /// Show the first issue.
  final bool showIssues;

  /// Extra actions under the card content (AI line quick actions).
  final Widget? extra;

  @override
  Widget build(BuildContext context) {
    final l = line;
    final bad = issues.isNotEmpty;
    final q = l.qtyMilli;
    final c = l.costCents;
    final t = l.totalCents;
    final unit = l.unitCode;
    final amount = q == null
        ? '—'
        : '${formatMilli(q, group: true)}${unit.isEmpty ? '' : ' $unit'} × ${c == null ? '—' : formatCents(c)}'
            '${t == null ? '' : ' = ${formatCents(t)}'}';
    final lotsN = l.lots?.rows.length ?? 0;
    final p = l.product;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: bad && showIssues ? AppColors.warnBorder : AppColors.border, width: bad && showIssues ? 1.5 : 1),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          key: Key('recv-line-${l.key}'),
          borderRadius: BorderRadius.circular(kRadius),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 0, 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                width: 34,
                height: 34,
                margin: const EdgeInsets.only(top: 2),
                decoration: BoxDecoration(
                  color: bad ? AppColors.warnSoft : (l.isNew ? AppColors.accentSoft : AppColors.okSoft),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(bad ? Icons.priority_high : (l.isNew ? Icons.fiber_new : Icons.check),
                    size: 18, color: bad ? AppColors.warn : (l.isNew ? AppColors.accentStrong : AppColors.ok)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(l.displayName.isEmpty ? tr('Nomsiz') : l.displayName,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                  if (l.aiName != null && l.aiName!.isNotEmpty && l.aiName != l.displayName)
                    Text(trArgs('AI o‘qidi: {name}', {'name': l.aiName}),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, color: AppColors.muted, fontStyle: FontStyle.italic)),
                  const SizedBox(height: 3),
                  Text(amount, key: Key('recv-line-amount-${l.key}'), style: TextStyle(fontSize: 13, color: AppColors.text3)),
                  const SizedBox(height: 4),
                  Wrap(spacing: 6, runSpacing: 4, children: [
                    if (l.isNew && !l.unmatched) RecvBadge(tr('Yangi'), color: AppColors.ok),
                    if (p != null) ...productBadges(p),
                    if (l.tracked && lotsN > 0)
                      RecvBadge(trArgs('{n} ta partiya', {'n': lotsN}), color: AppColors.text3),
                    if (p != null && l.aiConfidence != null && l.aiConfidence! < 0.8)
                      RecvBadge(trArgs('AI moslik {p}%', {'p': (l.aiConfidence! * 100).round()}), color: AppColors.warn),
                  ]),
                  if (bad && showIssues) ...[
                    const SizedBox(height: 4),
                    Text(issues.first.message,
                        key: Key('recv-line-issue-${l.key}'),
                        style: const TextStyle(fontSize: 12.5, color: AppColors.danger, fontWeight: FontWeight.w600)),
                  ],
                ]),
              ),
              IconButton(
                key: Key('recv-line-remove-${l.key}'),
                tooltip: tr('O‘chirish'),
                constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                onPressed: onRemove,
                icon: Icon(Icons.close, size: 20, color: AppColors.muted),
              ),
            ]),
          ),
        ),
        if (extra != null) Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 10), child: extra),
      ]),
    );
  }
}
