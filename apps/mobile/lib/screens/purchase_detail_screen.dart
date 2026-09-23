/// A receiving/purchase document (`GET /purchases/{id}`): lines, the lots the
/// receiving created, the correction history and — for `xaridlar.edit` — the
/// entry into the correction / cancel flow ([CorrectionScreen]).
///
/// PUBLIC ENTRY POINT (other packages link here, e.g. receiving detail via
/// `purchase_id`):
///
/// ```dart
/// final changed = await PurchaseDetailScreen.open(context, purchaseId);
/// // or: Navigator.push(context, MaterialPageRoute(
/// //       builder: (_) => PurchaseDetailScreen(purchaseId: purchaseId)));
/// if (changed) reloadList();   // a correction was written / doc cancelled
/// ```
///
/// The route pops `true` when a correction was written (or the document was
/// cancelled), `false` otherwise.
library;

import 'package:flutter/material.dart';

import '../api/correction_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'correction_screen.dart';

/// Permission-matrix action of `GET /purchases/{id}`.
const String kPurchaseDetailAction = 'purchases.detail';

/// Localized purchase status.
String purchaseStatusLabel(String s) => switch (s) {
      'received' => tr('Holat: qabul qilingan'),
      'debt' => tr('Holat: to‘lanmagan'),
      'partial' => tr('Holat: qisman to‘langan'),
      'cancelled' => tr('Holat: bekor qilingan'),
      _ => trArgs('Holat: {s}', {'s': s}),
    };

/// Document view + correction entry.
class PurchaseDetailScreen extends StatefulWidget {
  /// Creates the screen for purchase [purchaseId].
  const PurchaseDetailScreen({super.key, required this.purchaseId});

  /// `purchases.id` (e.g. `purchase_id` of `GET /receiving/{id}`).
  final String purchaseId;

  /// Pushes the screen; resolves to `true` when the document changed.
  static Future<bool> open(BuildContext context, String purchaseId) async {
    final r = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => PurchaseDetailScreen(purchaseId: purchaseId)),
    );
    return r ?? false;
  }

  @override
  State<PurchaseDetailScreen> createState() => _PurchaseDetailScreenState();
}

class _PurchaseDetailScreenState extends State<PurchaseDetailScreen> {
  final _ctl = AsyncViewController();
  PurchaseDoc? _doc;
  bool _changed = false;
  String? _notice;

  Future<PurchaseDoc> _load() async {
    final d = await CorrectionApi.purchase(widget.purchaseId);
    if (mounted) setState(() => _doc = d);
    return d;
  }

  void _leave() => Navigator.of(context).pop(_changed);

  Future<void> _correct(PurchaseDoc d) async {
    final before = d.corrections.length;
    final res = await CorrectionScreen.open(context, d);
    if (!mounted) return;
    if (res == null) {
      // Chiqib ketildi — lekin javobi yo'qolgan urinish serverda yozilgan
      // bo'lishi mumkin: hujjat qayta o'qiladi va tarix solishtiriladi.
      await _ctl.reload();
      if (mounted && (_doc?.corrections.length ?? before) != before) setState(() => _changed = true);
      return;
    }
    _changed = true;
    if (res.cancelled) {
      // Bekor qilingan hujjat keyingi GET da 404 beradi — shu ekranda qolmaymiz.
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(res.duplicate
            ? tr('Bu tuzatish avval yozilgan — hujjat allaqachon bekor qilingan.')
            : tr('Hujjat bekor qilindi')),
      ));
      _leave();
      return;
    }
    setState(() {
      _notice = res.duplicate
          ? tr('Bu tuzatish avval yozilgan — qayta qo‘llanmadi.')
          : trArgs('Tuzatish yozildi: hujjat jami {delta} ga o‘zgardi', {'delta': signedCents(res.deltaCents)});
    });
    await _ctl.reload();
  }

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows(kPurchaseDetailAction)) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Kirim hujjati'))),
        body: EmptyState(text: Perm.reason(kPurchaseDetailAction), icon: Icons.lock_outline),
      );
    }
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leave();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(_doc?.docNo.isNotEmpty == true ? _doc!.docNo : tr('Kirim hujjati')),
        ),
        body: Column(children: [
          const ConnectivityBanner(),
          Expanded(
            child: AsyncView<PurchaseDoc>(
              controller: _ctl,
              load: _load,
              refreshable: true,
              builder: (context, d) {
                final bar = _bar(d);
                return Column(children: [
                  Expanded(child: _content(d)),
                  if (bar != null) bar,
                ]);
              },
            ),
          ),
        ]),
      ),
    );
  }

  /// The correction action (null = not offered: no permission / older server).
  Widget? _bar(PurchaseDoc d) {
    if (!Perm.allows(kCorrectAction)) return null;
    if (d.receivingId == null || d.correctable == null) {
      // Partiyasiz/qabulsiz hujjatda server sababni beradi — tugma o'chiq, sabab aytiladi.
      if (d.correctable == false && d.blockedReason != null) {
        return StickyActionBar(
          key: const Key('pd-bar'),
          label: tr('Tuzatish yoki bekor qilish'),
          onPressed: null,
          enabled: false,
          disabledReason: serverText(d.blockedReason),
        );
      }
      return null;
    }
    final open = d.correctionOpen;
    final reason = open ? null : serverText(d.blockedReason);
    return StickyActionBar(
      key: const Key('pd-bar'),
      label: tr('Tuzatish yoki bekor qilish'),
      icon: Icons.edit_note,
      onPressed: () => _correct(d),
      enabled: open,
      disabledReason: (reason == null || reason.isEmpty) && !open ? tr('Bu hujjatni tuzatib bo‘lmaydi') : reason,
    );
  }

  Widget _content(PurchaseDoc d) {
    final lines = _displayLines(d);
    return ListView(
      key: const Key('pd-list'),
      padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
      children: [
        if (_notice != null) ...[
          ErrorBanner(
            key: const Key('pd-notice'),
            message: _notice!,
            severity: BannerSeverity.info,
            onDismiss: () => setState(() => _notice = null),
          ),
          const SizedBox(height: 12),
        ],
        _header(d),
        const SizedBox(height: 16),
        _sectionTitle(tr('Hujjat qatorlari'), d.lines.length),
        for (final (item, lots) in lines) _itemCard(d, item, lots),
        if (d.corrections.isNotEmpty) ...[
          const SizedBox(height: 16),
          _sectionTitle(tr('Bu hujjatdagi tuzatishlar'), d.corrections.length),
          _history(d),
        ],
      ],
    );
  }

  /// Lines with their lots, each lot shown ONCE (under the first line of its
  /// product — the same rule as the correction editor).
  List<(PurchaseLine, List<ReceivedLot>)> _displayLines(PurchaseDoc d) {
    final seen = <String>{};
    return [
      for (final it in d.lines) (it, [for (final l in it.lots) if (seen.add(l.id)) l])
    ];
  }

  Widget _sectionTitle(String t, int n) => Padding(
        padding: const EdgeInsets.only(bottom: 8, left: 2),
        child: Semantics(
          header: true,
          child: Text('$t ($n)', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
        ),
      );

  Widget _chip(String text, Color fg, Color bg, {Key? key}) => Container(
        key: key,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(9)),
        child: Text(text, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: fg)),
      );

  Widget _kv(String k, String v, {Key? key, bool strong = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 128, child: Text(k, style: TextStyle(fontSize: 13, color: AppColors.muted))),
          Expanded(
            child: Text(v,
                key: key,
                style: TextStyle(fontSize: strong ? 16 : 14, fontWeight: strong ? FontWeight.w800 : FontWeight.w600)),
          ),
        ]),
      );

  Widget _header(PurchaseDoc d) {
    final credit = d.isCredit;
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          _chip(credit ? tr('Qarzga') : tr('Naqd'), credit ? AppColors.warn : AppColors.ok,
              credit ? AppColors.warnSoft : AppColors.okSoft,
              key: const Key('pd-payment')),
          _chip(purchaseStatusLabel(d.status), AppColors.text2, AppColors.surface, key: const Key('pd-status')),
        ]),
        const SizedBox(height: 10),
        _kv(tr('Yetkazib beruvchi'), d.supplier.isEmpty ? '—' : d.supplier, key: const Key('pd-supplier')),
        if (d.date != null) _kv(tr('Hujjat sanasi'), dateDisplay(d.date)),
        if (d.branchName != null) _kv(tr('Filial'), d.branchName!, key: const Key('pd-branch')),
        const SizedBox(height: 4),
        _kv(tr('Hujjat jami'), formatCents(d.totalCents), key: const Key('pd-total'), strong: true),
        _kv(tr('To‘langan summa'), formatCents(d.paidCents), key: const Key('pd-paid')),
      ]),
    );
  }

  Widget _itemCard(PurchaseDoc d, PurchaseLine it, List<ReceivedLot> lots) {
    final unit = unitLabel(it.unit);
    return Container(
      key: Key('pd-item-${it.id}'),
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(it.name, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text('${formatMilli(it.qtyMilli)} $unit × ${formatCents(it.unitCostCents)}',
                style: TextStyle(fontSize: 13, color: AppColors.text2)),
          ),
          Text(formatCents(it.lineTotalCents), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
        ]),
        if (it.trackLots || it.trackExpiry) ...[
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [
            if (it.trackLots) _chip(tr('Partiya hisobida'), AppColors.accentStrong, AppColors.accentSoft),
            if (it.trackExpiry) _chip(tr('Muddat hisobida'), AppColors.accentStrong, AppColors.accentSoft),
          ]),
        ],
        if (it.correctable == false && it.blockedReason != null && it.lots.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(serverText(it.blockedReason),
                key: Key('pd-item-${it.id}-blocked'), style: const TextStyle(fontSize: 12.5, color: AppColors.warn)),
          ),
        for (final lt in lots) _lotRow(d, lt, unit),
      ]),
    );
  }

  Widget _lotRow(PurchaseDoc d, ReceivedLot lt, String unit) {
    final biz = d.businessDate;
    final expired = lt.expiryDate != null && biz != null && lt.expiryDate!.compareTo(biz) < 0;
    final title = [
      lt.batchNo ?? tr('Raqamsiz partiya'),
      if (lt.expiryDate != null) dateDisplay(lt.expiryDate),
    ].join(' · ');
    return Container(
      key: Key('pd-lot-${lt.id}'),
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(Icons.inventory_2_outlined, size: 16, color: AppColors.text3),
          const SizedBox(width: 6),
          Expanded(child: Text(title, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700))),
          if (expired) Text(tr('Muddati o‘tgan'), style: const TextStyle(fontSize: 12, color: AppColors.danger)),
        ]),
        const SizedBox(height: 3),
        Text(
          trArgs('Qabul: {r} · Qoldiq: {q} · Ketgan: {c}', {
            'r': formatMilli(lt.receivedMilli),
            'q': formatMilli(lt.remainingMilli),
            'c': formatMilli(lt.consumedMilli),
          }),
          style: TextStyle(fontSize: 12.5, color: AppColors.muted),
        ),
        if (!lt.correctable && lt.blockedReason == null)
          Padding(
            padding: const EdgeInsets.only(top: 3),
            child: Text(
              tr('Bu partiyadan tovar ketgan — raqami, muddati va tannarxi tuzatilmaydi; faqat miqdorni teskari qilish mumkin'),
              style: const TextStyle(fontSize: 12, color: AppColors.warn),
            ),
          ),
      ]),
    );
  }

  Widget _history(PurchaseDoc d) => AppCard(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: Column(children: [
          for (final c in d.corrections)
            Padding(
              key: Key('pd-corr-${c.id}'),
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(c.reason, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text([c.employee, if (c.at != null) dmy(c.at)].where((s) => s.isNotEmpty).join(' · '),
                        style: TextStyle(fontSize: 12, color: AppColors.muted)),
                  ]),
                ),
                const SizedBox(width: 8),
                Text(signedCents(c.deltaCents),
                    style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w800,
                        color: c.deltaCents < 0 ? AppColors.danger : AppColors.ok)),
              ]),
            ),
        ]),
      );
}
