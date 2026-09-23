import 'package:flutter/material.dart';

import '../api/money_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'money_payment_sheet.dart';
import 'receipt_screen.dart';

/// One sale, read from the SERVER receipt (`GET /sales/{id}/receipt`, the same
/// document the POS prints): status, branch, cashier, till, lines, totals and
/// the real payment split. "Chekni ko‘rish" opens the paper view (share as
/// text). Returns are not done from mobile.
class SalesDetailScreen extends StatefulWidget {
  /// Creates the screen.
  const SalesDetailScreen({super.key, required this.saleId, this.receiptNo});

  /// Sale id.
  final String saleId;

  /// Receipt number shown until the document loads.
  final String? receiptNo;

  @override
  State<SalesDetailScreen> createState() => _SalesDetailScreenState();
}

class _SalesDetailScreenState extends State<SalesDetailScreen> {
  Receipt? _r;

  Future<Receipt> _load() async {
    final r = await MoneyApi.saleReceipt(widget.saleId);
    if (mounted) setState(() => _r = r);
    return r;
  }

  void _openReceipt(Receipt r) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReceiptScreen(receipt: r)));

  @override
  Widget build(BuildContext context) {
    final title = _r?.number ?? widget.receiptNo ?? tr('Sotuv');
    if (!Perm.allows('sales.receipt')) {
      return Scaffold(appBar: AppBar(title: Text(title)), body: const NoAccessView(action: 'sales.receipt'));
    }
    final r = _r;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          if (r?.issuedAtLocal != null)
            Text(r!.issuedAtLocal!, style: TextStyle(fontSize: 12, color: AppColors.muted, fontWeight: FontWeight.w400)),
        ]),
        actions: [
          if (r != null)
            IconButton(
              key: const Key('sale-share'),
              tooltip: tr('Ulashish'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              onPressed: () => receiptShare(receiptPlainText(r), subject: '${tr('Chek')} ${r.number}'),
              icon: const Icon(Icons.share_outlined),
            ),
        ],
      ),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: AsyncView<Receipt>(
            load: _load,
            refreshable: true,
            builder: (context, r) => _body(r),
          ),
        ),
      ]),
      bottomNavigationBar: r == null
          ? null
          : StickyActionBar(
              key: const Key('sale-receipt-bar'),
              label: tr('Chekni ko‘rish'),
              icon: Icons.receipt_long,
              onPressed: () => _openReceipt(r),
            ),
    );
  }

  Widget _body(Receipt r) {
    final lines = r.lines;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(kGutter),
      children: [
        if (r.status != 'completed') ...[
          ErrorBanner(
            key: const Key('sale-status'),
            severity: r.isVoided ? BannerSeverity.error : BannerSeverity.warning,
            message: trArgs('Holati: {status}', {'status': saleStatusLabel(r.status)}),
          ),
          const SizedBox(height: 12),
        ],
        AppCard(
          padding: const EdgeInsets.all(14),
          child: Column(children: [
            if (r.branchName != null) _info(Icons.store_mall_directory_outlined, tr('Filial'), r.branchName!),
            if (r.cashier != null) _info(Icons.person_outline, tr('Kassir'), r.cashier!),
            if (r.tillCode != null) _info(Icons.point_of_sale, tr('Kassa'), r.tillCode!),
            if (r.terminal != null) _info(Icons.devices_other, tr('Terminal'), r.terminal!),
            if (r.customerName != null) _info(Icons.badge_outlined, tr('Xaridor'), r.customerName!),
            _info(Icons.schedule, tr('Vaqt'), r.issuedAtLocal ?? '—'),
          ]),
        ),
        const SizedBox(height: 14),
        Text(trArgs('Tovarlar ({n})', {'n': lines.length}),
            style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (lines.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Text(tr('Qatorlar saqlanmagan (tarixiy sotuv)'), style: TextStyle(color: AppColors.muted)),
          )
        else
          AppCard(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: Column(children: [
              for (var i = 0; i < lines.length; i++) _line(r, lines[i], i < lines.length - 1),
            ]),
          ),
        const SizedBox(height: 14),
        AppCard(
          key: const Key('sale-totals'),
          padding: const EdgeInsets.all(14),
          child: Column(children: [
            if (_pos(r.lineDiscount) || _pos(r.docDiscount) || _nonZero(r.rounding))
              _sum(tr('Oraliq jami'), receiptMoney(r.subtotal)),
            if (_pos(r.lineDiscount)) _sum(tr('Chegirma'), '-${receiptMoney(r.lineDiscount)}'),
            if (_pos(r.docDiscount)) _sum(tr('Chek chegirmasi'), '-${receiptMoney(r.docDiscount)}'),
            if (_nonZero(r.rounding)) _sum(tr('Yaxlitlash'), receiptRoundingText(r)),
            Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Divider(height: 1, color: AppColors.border)),
            _sum(tr('Jami'), '${receiptMoney(r.total)} ${receiptCurrency(r)}', big: true),
          ]),
        ),
        const SizedBox(height: 14),
        if (r.payments.isNotEmpty)
          AppCard(
            key: const Key('sale-payments'),
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('To‘lov'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              for (final p in r.payments) ...[
                _sum(paymentMethodLabel(p.method), receiptMoney(p.amount)),
                if (p.given != null) _sum(tr('Berildi'), receiptMoney(p.given!), muted: true),
                if (p.change != null) _sum(tr('Qaytim'), receiptMoney(p.change!), muted: true),
              ],
            ]),
          ),
        const SizedBox(height: 24),
      ],
    );
  }

  static bool _pos(String v) => receiptAmountPositive(v);
  static bool _nonZero(String v) => receiptAmountNonZero(v);

  Widget _info(IconData icon, String label, String value) => ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 34),
        child: Row(children: [
          Icon(icon, size: 18, color: AppColors.muted),
          const SizedBox(width: 10),
          Text(label, style: TextStyle(fontSize: 13, color: AppColors.muted)),
          const SizedBox(width: 12),
          Expanded(
            child: Text(value,
                textAlign: TextAlign.right,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
          ),
        ]),
      );

  Widget _line(Receipt r, ReceiptLine l, bool border) => Container(
        constraints: const BoxConstraints(minHeight: 52),
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(l.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(
                  '${receiptQty(l.qty, weighted: l.weighted)}${l.unit == null ? '' : ' ${l.unit}'} × ${receiptMoney(l.unitPrice)}'
                  '${_pos(l.discount) ? ' · ${tr('Chegirma')} -${receiptMoney(l.discount)}' : ''}',
                  style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          Text(receiptMoney(l.total), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        ]),
      );

  Widget _sum(String l, String v, {bool big = false, bool muted = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(l,
              style: TextStyle(
                  fontSize: big ? 15 : 13.5,
                  fontWeight: big ? FontWeight.w700 : FontWeight.w400,
                  color: muted ? AppColors.muted : (big ? AppColors.text : AppColors.text2))),
          Text(v,
              style: TextStyle(
                  fontSize: big ? 20 : 13.5,
                  fontWeight: big ? FontWeight.w800 : FontWeight.w600,
                  color: muted ? AppColors.muted : AppColors.text)),
        ]),
      );
}
