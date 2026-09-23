import 'package:flutter/material.dart';

import '../api/money_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';
import 'customer_edit_screen.dart';
import 'money_payment_sheet.dart';
import 'sales_detail_screen.dart';

/// Customer profile: debt / advance, debt payment (cash · card · QR with the
/// server's cash-custody decision), edit, purchase history and payments.
///
/// A purchase row opens its receipt ([SalesDetailScreen]) when the server
/// sent the `sale_id` and the user may read receipts (`sales.receipt`); the
/// quantity keeps 3 decimals when fractional (weighed goods); a debt payment
/// shows its stored method.
class CustomerProfileScreen extends StatefulWidget {
  /// Creates the screen.
  const CustomerProfileScreen({super.key, required this.customerId, required this.name});

  /// Customer id.
  final String customerId;

  /// Name shown until the profile loads.
  final String name;

  @override
  State<CustomerProfileScreen> createState() => _CustomerProfileScreenState();
}

class _CustomerProfileScreenState extends State<CustomerProfileScreen> {
  final _view = AsyncViewController();
  CustomerProfile? _last;
  String? _notice;
  bool _noticeWarn = false;

  Future<CustomerProfile> _load() async {
    final p = await MoneyApi.customerDetail(widget.customerId);
    if (mounted) setState(() => _last = p);
    return p;
  }

  Future<void> _edit(CustomerProfile p) async {
    final saved = await Navigator.of(context).push<CustomerRow>(
      MaterialPageRoute(builder: (_) => CustomerEditScreen(customer: p.row)),
    );
    if (saved != null && mounted) {
      setState(() {
        _noticeWarn = false;
        _notice = tr('Mijoz ma’lumotlari saqlandi');
      });
      await _view.reload();
    }
  }

  Future<void> _pay(CustomerProfile p) async {
    final out = await showMoneyPaymentSheet(
      context,
      title: tr('Qarzni so‘ndirish'),
      partyName: p.fullName,
      balanceLabel: tr('joriy qarz'),
      balanceCents: p.balanceCents,
      custodyOperation: CustodyOperation.debtPayment,
      submit: ({required amountCents, required method, cashAccountId, required clientUuid}) async {
        final r = await MoneyApi.payCustomerDebt(p.id,
            amountCents: amountCents, method: method, cashAccountId: cashAccountId, clientUuid: clientUuid);
        return PaymentOutcome(balanceCents: r.balanceCents, paidCents: r.paidCents, duplicate: r.duplicate);
      },
    );
    if (!mounted) return;
    // Natija noma'lum bo'lib yopilgan bo'lsa ham qayta yuklaymiz — ekranda serverning HAQIQIY balansi.
    if (out != null) {
      final n = _payNotice(out);
      setState(() {
        _notice = n.$1;
        _noticeWarn = n.$2;
      });
    }
    await _view.reload();
  }

  /// What to tell the operator after the sheet closed, and whether it is a
  /// WARNING. Nothing is computed here: only what the server reported (and,
  /// for a clamp, what the operator had typed) is shown.
  (String, bool) _payNotice(PaymentOutcome out) {
    final left = formatCents(out.balanceCents);
    // Javob kelmagan yozuv: eski balansni "to'lov bo'lmagan" kabi ko'rsatmaymiz.
    if (!out.resolved) {
      return (tr('Server javobi kelmadi — to‘lov yozilgan bo‘lishi mumkin. Quyidagi ro‘yxatni tekshiring.'), true);
    }
    if (out.duplicate) return (tr('Bu to‘lov avval saqlangan edi — qayta yozilmadi.'), false);
    final paid = out.paidCents;
    final asked = out.requestedCents;
    // Eski server to'langan summani aytmaydi — kiritilgan summa yozilgan deb
    // ko'rsatmaymiz, faqat serverning balansini aytamiz.
    if (paid == null) return (trArgs('To‘lov qabul qilindi. Qolgan qarz: {left}', {'left': left}), false);
    // Server kamroq yozgan (parallel to'lov summani qirqqan): kassaga olingan
    // pul bilan yozilgan pul farq qiladi — buni ochiq aytamiz.
    if (asked != null && paid < asked) {
      return (
        trArgs('Diqqat: siz {asked} kiritdingiz, lekin serverga {paid} yozildi. Qolgan qarz: {left}',
            {'asked': formatCents(asked), 'paid': formatCents(paid), 'left': left}),
        true,
      );
    }
    return (trArgs('To‘landi: {paid}. Qolgan qarz: {left}', {'paid': formatCents(paid), 'left': left}), false);
  }

  @override
  Widget build(BuildContext context) {
    final p = _last;
    final canPay = Perm.allows('customers.pay');
    final canEdit = Perm.allows('customers.edit');
    return Scaffold(
      appBar: AppBar(
        title: Text(p?.fullName ?? widget.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [
          if (canEdit && p != null)
            IconButton(
              key: const Key('customer-edit'),
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
          child: AsyncView<CustomerProfile>(
            controller: _view,
            load: _load,
            refreshable: true,
            builder: (context, d) => _body(d),
          ),
        ),
      ]),
      bottomNavigationBar: (p != null && p.hasDebtRow)
          ? StickyActionBar(
              key: const Key('customer-pay-bar'),
              label: tr('Qarzni so‘ndirish'),
              icon: Icons.payments_outlined,
              enabled: canPay,
              disabledReason: Perm.reason('customers.pay'),
              onPressed: () => _pay(p),
            )
          : null,
    );
  }

  Widget _body(CustomerProfile d) {
    final debt = d.balanceCents > 0;
    final advance = d.balanceCents < 0;
    final Color fg = debt ? AppColors.danger : (advance ? AppColors.accentStrong : AppColors.ok);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(kGutter),
      children: [
        if (_notice != null) ...[
          ErrorBanner(
            key: const Key('customer-notice'),
            severity: _noticeWarn ? BannerSeverity.warning : BannerSeverity.info,
            message: _notice!,
            onDismiss: () => setState(() => _notice = null),
          ),
          const SizedBox(height: 12),
        ],
        Row(children: [
          CircleAvatar(
            radius: 28,
            backgroundColor: AppColors.accentSoft,
            child: Text(d.fullName.isEmpty ? '?' : d.fullName.characters.first.toUpperCase(),
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: AppColors.accentStrong)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(d.fullName, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
              if (d.phone != null) ...[
                const SizedBox(height: 2),
                SelectableText(d.phone!, style: TextStyle(fontSize: 13.5, color: AppColors.muted)),
              ],
            ]),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
            decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(8)),
            child: Text(d.code, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.muted)),
          ),
        ]),
        const SizedBox(height: 18),
        Container(
          key: const Key('customer-balance'),
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: debt ? AppColors.dangerSoft : (advance ? AppColors.accentSoft : AppColors.okSoft),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: fg.withAlpha(110)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(debt ? tr('Qarz') : (advance ? tr('Avans (do‘kon mijozga qarzdor)') : tr('Qarz yo‘q')),
                style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(formatCents(d.balanceCents.abs()),
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: fg, letterSpacing: -0.5)),
          ]),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: _stat(tr('Jami xarid'), formatCents(d.totalSpentCents), Icons.shopping_bag_outlined)),
          const SizedBox(width: 12),
          Expanded(child: _stat(tr('Tashriflar'), '${d.visits}', Icons.event_repeat_outlined)),
        ]),
        const SizedBox(height: 20),
        _section(tr('So‘nggi xaridlar')),
        if (d.history.isEmpty)
          _muted(tr('Xarid yo‘q'))
        else
          AppCard(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(children: [
              for (var i = 0; i < d.history.length; i++) _histRow(d.history[i], i < d.history.length - 1),
            ]),
          ),
        const SizedBox(height: 20),
        _section(tr('Qarz to‘lovlari')),
        if (d.payments.isEmpty)
          _muted(tr('To‘lov yo‘q'))
        else
          AppCard(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(children: [
              for (var i = 0; i < d.payments.length; i++) _payRow(d.payments[i], i < d.payments.length - 1),
            ]),
          ),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _section(String t) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Text(t, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
      );

  Widget _muted(String t) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(t, style: TextStyle(color: AppColors.muted)),
      );

  Widget _stat(String label, String value, IconData ic) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
            color: AppColors.card, borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(ic, size: 18, color: AppColors.accentStrong),
          const SizedBox(height: 8),
          Text(value, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      );

  /// "3 ta tovar" for whole quantities; weighed (fractional) sums keep
  /// exactly 3 decimals ("Miqdor: 3,500"). An older server sends only the
  /// truncated whole count.
  String _qtyText(CustomerPurchase h) {
    final m = h.qtyMilli;
    if (m == null) return trArgs('{n} ta tovar', {'n': h.items});
    if (m % kMilli == 0) return trArgs('{n} ta tovar', {'n': formatQty3(m)});
    return trArgs('Miqdor: {q}', {'q': formatQty3(m)});
  }

  Widget _histRow(CustomerPurchase h, bool border) {
    final saleId = h.saleId;
    final open = saleId != null && Perm.allows('sales.receipt');
    final sub = [dmy(h.at), if (h.receiptNo != null) '№${h.receiptNo}'].join(' · ');
    return InkWell(
      key: saleId == null ? null : Key('customer-sale-$saleId'),
      onTap: open
          ? () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => SalesDetailScreen(saleId: saleId, receiptNo: h.receiptNo)))
          : null,
      child: Container(
        constraints: const BoxConstraints(minHeight: kMinTouch),
        padding: const EdgeInsets.symmetric(vertical: 11),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${_qtyText(h)} · ${paymentMethodLabel(h.method)}',
                  style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(sub, style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          Text(formatCents(h.amountCents), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          if (open) ...[
            const SizedBox(width: 4),
            Icon(Icons.chevron_right, size: 18, color: AppColors.muted),
          ],
        ]),
      ),
    );
  }

  Widget _payRow(CustomerPaymentEntry p, bool border) => Container(
        constraints: const BoxConstraints(minHeight: kMinTouch),
        padding: const EdgeInsets.symmetric(vertical: 11),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          const Icon(Icons.south_west, size: 16, color: AppColors.ok),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              [dmy(p.at), if (p.method != null) paymentMethodLabel(p.method!)].join(' · '),
              style: TextStyle(fontSize: 13, color: AppColors.text3),
            ),
          ),
          Text('+${formatCents(p.amountCents)}',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.ok)),
        ]),
      );
}

extension on CustomerProfile {
  /// The pay bar is shown only for a customer who owes money.
  bool get hasDebtRow => balanceCents > 0;
}
