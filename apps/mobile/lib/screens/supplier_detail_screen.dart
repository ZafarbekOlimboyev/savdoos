import 'package:flutter/material.dart';

import '../api/money_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';
import 'money_payment_sheet.dart';
import 'purchase_detail_screen.dart' show PurchaseDetailScreen;
import 'suppliers_screen.dart' show showSupplierForm;

/// Supplier detail (`GET /suppliers/{id}`): our debt + payment (cash with the
/// server's custody decision, card, QR), purchases, the balance ledger
/// (`GET /suppliers/{id}/ledger`) and the supplied products. Edit with
/// `xaridlar.edit`.
class SupplierDetailScreen extends StatefulWidget {
  /// Creates the screen.
  const SupplierDetailScreen({super.key, required this.supplierId, required this.name});

  /// Supplier id.
  final String supplierId;

  /// Name shown until the detail loads.
  final String name;

  @override
  State<SupplierDetailScreen> createState() => _SupplierDetailScreenState();
}

enum _Tab { purchases, ledger, products }

class _SupplierDetailScreenState extends State<SupplierDetailScreen> {
  final _view = AsyncViewController();
  SupplierProfile? _last;
  List<SupplierLedgerEntry>? _ledgerRows;
  Object? _ledgerError;
  bool _ledgerLoading = false;
  int _ledgerSeq = 0;
  _Tab _tab = _Tab.purchases;
  String? _notice;
  bool _noticeWarn = false;

  Future<SupplierProfile> _load() async {
    final p = await MoneyApi.supplierDetail(widget.supplierId);
    if (mounted) setState(() => _last = p);
    return p;
  }

  Future<void> _reloadAll() async {
    await _view.reload();
    if (_ledgerRows != null || _ledgerError != null) await _loadLedger();
  }

  void _selectTab(_Tab t) {
    setState(() => _tab = t);
    if (t == _Tab.ledger && _ledgerRows == null && !_ledgerLoading && Perm.allows('suppliers.ledger')) _loadLedger();
  }

  Future<void> _edit(SupplierProfile p) async {
    final saved = await showSupplierForm(context, supplier: p.row);
    if (saved != null && mounted) {
      setState(() {
        _noticeWarn = false;
        _notice = tr('Yetkazib beruvchi ma’lumotlari saqlandi');
      });
      await _view.reload();
    }
  }

  Future<void> _pay(SupplierProfile p) async {
    final out = await showMoneyPaymentSheet(
      context,
      title: tr('Yetkazib beruvchiga to‘lash'),
      partyName: p.name,
      balanceLabel: tr('Biz qarzmiz'),
      balanceCents: p.balanceCents,
      custodyOperation: CustodyOperation.supplierPayment,
      submit: ({required amountCents, required method, cashAccountId, required clientUuid}) async {
        final r = await MoneyApi.paySupplier(p.id,
            amountCents: amountCents, method: method, cashAccountId: cashAccountId, clientUuid: clientUuid);
        return PaymentOutcome(balanceCents: r.balanceCents, paidCents: r.paidCents, duplicate: r.duplicate);
      },
    );
    if (!mounted) return;
    if (out != null) {
      setState(() {
        _noticeWarn = !out.resolved;
        _notice = !out.resolved
            // Javob kelmadi: to'lov yozilgan bo'lishi MUMKIN — eski balansni
            // "to'lov bo'lmagan" kabi ko'rsatmaymiz.
            ? tr('Server javobi kelmadi — to‘lov yozilgan bo‘lishi mumkin. Quyidagi ro‘yxatni tekshiring.')
            : out.duplicate
                ? tr('Bu to‘lov avval saqlangan edi — qayta yozilmadi.')
                : trArgs('To‘landi: {paid}. Qolgan qarzimiz: {left}',
                    {'paid': formatCents(out.paidCents ?? 0), 'left': formatCents(out.balanceCents)});
      });
    }
    await _reloadAll();
  }

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows('suppliers.detail')) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.name)),
        body: const NoAccessView(action: 'suppliers.detail'),
      );
    }
    final p = _last;
    final canEdit = Perm.allows('suppliers.edit');
    return Scaffold(
      appBar: AppBar(
        title: Text(p?.name ?? widget.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [
          if (canEdit && p != null)
            IconButton(
              key: const Key('supplier-edit'),
              tooltip: tr('Tahrirlash'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              onPressed: () => _edit(p),
              icon: const Icon(Icons.edit_outlined),
            ),
        ],
      ),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: AsyncView<SupplierProfile>(
            controller: _view,
            load: _load,
            refreshable: true,
            builder: (context, d) => _body(d),
          ),
        ),
      ]),
      bottomNavigationBar: (p != null && p.balanceCents > 0)
          ? StickyActionBar(
              key: const Key('supplier-pay-bar'),
              label: tr('To‘lash'),
              icon: Icons.payments_outlined,
              enabled: Perm.allows('suppliers.pay'),
              disabledReason: Perm.reason('suppliers.pay'),
              onPressed: () => _pay(p),
            )
          : null,
    );
  }

  Widget _body(SupplierProfile d) {
    final owe = d.balanceCents > 0;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(kGutter),
      children: [
        if (_notice != null) ...[
          ErrorBanner(
            key: const Key('supplier-notice'),
            severity: _noticeWarn ? BannerSeverity.warning : BannerSeverity.info,
            message: _notice!,
            onDismiss: () => setState(() => _notice = null),
          ),
          const SizedBox(height: 12),
        ],
        if (d.phone != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(children: [
              Icon(Icons.phone_outlined, size: 18, color: AppColors.muted),
              const SizedBox(width: 8),
              SelectableText(d.phone!, style: TextStyle(fontSize: 14, color: AppColors.text2)),
            ]),
          ),
        Container(
          key: const Key('supplier-balance'),
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: owe ? AppColors.dangerSoft : AppColors.okSoft,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(owe ? tr('Biz qarzmiz') : (d.balanceCents < 0 ? tr('Yetkazib beruvchi bizga qarzdor') : tr('Qarz yo‘q')),
                style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(formatCents(d.balanceCents.abs()),
                style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: owe ? AppColors.danger : AppColors.ok,
                    letterSpacing: -0.5)),
          ]),
        ),
        const SizedBox(height: 12),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 2.1,
          children: [
            _stat(tr('Xaridlar'), '${d.purchaseCount}'),
            _stat(tr('Jami xarid'), formatCents(d.totalPurchasedCents)),
            _stat(tr('To‘langan'), formatCents(d.paidTotalCents)),
            _stat(tr('Oxirgi xarid'), d.lastPurchase == null ? '—' : dateDisplay(d.lastPurchase)),
            _stat(tr('Mahsulot turlari'), '${d.productTypes}'),
            _stat(tr('Kutilayotgan foyda'), formatCents(d.expectedProfitCents)),
          ],
        ),
        const SizedBox(height: 16),
        _tabs(),
        const SizedBox(height: 12),
        switch (_tab) {
          _Tab.purchases => _purchases(d),
          _Tab.ledger => _ledger(),
          _Tab.products => _products(d),
        },
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _tabs() {
    Widget seg(_Tab t, String label) {
      final on = _tab == t;
      return Expanded(
        child: Semantics(
          selected: on,
          button: true,
          child: InkWell(
            key: Key('supplier-tab-${t.name}'),
            borderRadius: BorderRadius.circular(10),
            onTap: () => _selectTab(t),
            child: Container(
              constraints: const BoxConstraints(minHeight: kMinTouch),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: on ? AppColors.accent : Colors.transparent,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: on ? Colors.white : AppColors.text3)),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
          color: AppColors.surface, borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
      child: Row(children: [
        seg(_Tab.purchases, tr('Xaridlar')),
        seg(_Tab.ledger, tr('Hisob-kitob')),
        seg(_Tab.products, tr('Mahsulotlar')),
      ]),
    );
  }

  Widget _stat(String label, String value) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
            color: AppColors.card, borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
        ]),
      );

  Widget _empty(String t) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 20),
        child: Center(child: Text(t, style: TextStyle(color: AppColors.muted))),
      );

  Widget _purchases(SupplierProfile d) {
    if (d.recentPurchases.isEmpty) return _empty(tr('Xarid yo‘q'));
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Column(children: [
        for (var i = 0; i < d.recentPurchases.length; i++)
          _purchaseRow(d.recentPurchases[i], i < d.recentPurchases.length - 1),
      ]),
    );
  }

  Future<void> _openPurchase(SupplierPurchase p) async {
    final changed = await PurchaseDetailScreen.open(context, p.id);
    if (changed && mounted) await _reloadAll();
  }

  Widget _purchaseRow(SupplierPurchase p, bool border) {
    final debt = p.status == 'debt' || p.status == 'partial';
    final canOpen = Perm.allows('purchases.detail') && p.id.isNotEmpty;
    return InkWell(
      key: Key('purchase-${p.id}'),
      onTap: canOpen ? () => _openPurchase(p) : null,
      child: Container(
        constraints: const BoxConstraints(minHeight: 56),
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p.docNo.isEmpty ? '—' : p.docNo, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(dateDisplay(p.date), style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(formatCents(p.totalCents), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            const SizedBox(height: 2),
            Text(purchaseStatusLabel(p.status),
                style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: debt ? AppColors.warn : AppColors.muted)),
          ]),
          if (canOpen) ...[
            const SizedBox(width: 4),
            Icon(Icons.chevron_right, color: AppColors.faint),
          ],
        ]),
      ),
    );
  }

  Future<void> _loadLedger() async {
    final seq = ++_ledgerSeq;
    setState(() {
      _ledgerLoading = true;
      _ledgerError = null;
    });
    try {
      final rows = await MoneyApi.supplierLedger(widget.supplierId);
      if (!mounted || seq != _ledgerSeq) return;
      setState(() {
        _ledgerRows = rows;
        _ledgerLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _ledgerSeq) return;
      setState(() {
        _ledgerError = e;
        _ledgerLoading = false;
      });
    }
  }

  Widget _ledger() {
    if (!Perm.allows('suppliers.ledger')) return _empty(Perm.reason('suppliers.ledger'));
    final rows = _ledgerRows;
    if (_ledgerError != null) {
      return ErrorBanner(key: const Key('ledger-error'), error: _ledgerError, onRetry: _loadLedger);
    }
    if (rows == null) {
      return const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: Center(child: CircularProgressIndicator()));
    }
    if (rows.isEmpty) return _empty(tr('Hisob-kitob yozuvlari yo‘q'));
    return AppCard(
      key: const Key('supplier-ledger'),
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Column(children: [
        if (_ledgerLoading) const LinearProgressIndicator(minHeight: 2),
        for (var i = 0; i < rows.length; i++) _ledgerRow(rows[i], i < rows.length - 1),
      ]),
    );
  }

  Widget _ledgerRow(SupplierLedgerEntry r, bool border) {
    final down = r.amountCents < 0;
    return Container(
      constraints: const BoxConstraints(minHeight: 56),
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
      child: Row(children: [
        Icon(down ? Icons.south_west : Icons.north_east, size: 16, color: down ? AppColors.ok : AppColors.danger),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(r.label, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(dmy(r.at), style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${down ? '−' : '+'}${formatCents(r.amountCents.abs())}',
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: down ? AppColors.ok : AppColors.danger)),
          Text(trArgs('Qoldiq: {sum}', {'sum': formatCents(r.balanceAfterCents)}),
              style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
        ]),
      ]),
    );
  }

  Widget _products(SupplierProfile d) {
    if (d.products.isEmpty) return _empty(tr('Mahsulot yo‘q'));
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Column(children: [
        for (var i = 0; i < d.products.length; i++)
          Container(
            constraints: const BoxConstraints(minHeight: 52),
            padding: const EdgeInsets.symmetric(vertical: 9),
            decoration: BoxDecoration(
                border: i < d.products.length - 1 ? Border(bottom: BorderSide(color: AppColors.border)) : null),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(d.products[i].name,
                      maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(trArgs('Miqdor: {qty}', {'qty': formatMilli(d.products[i].qtyMilli, group: true)}),
                      style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                ]),
              ),
              Text(formatCents(d.products[i].costCents), style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700)),
            ]),
          ),
      ]),
    );
  }
}
