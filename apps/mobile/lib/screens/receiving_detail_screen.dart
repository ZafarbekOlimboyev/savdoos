import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../api/receiving_api.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'purchase_detail_screen.dart';
import 'receiving_widgets.dart';

/// Localized label of a receiving `source`.
String recvSourceLabel(String s) => switch (s) {
      'ai' => tr('AI (nakladnoy surati)'),
      'demo' => 'DEMO',
      'manual' => tr('Qo‘lda'),
      _ => s,
    };

/// Localized purchase status.
String recvStatusLabel(String? s) => switch (s) {
      'received' => tr('To‘langan'),
      'debt' => tr('Qarz'),
      'partial' => tr('Qisman to‘langan'),
      'cancelled' => tr('Bekor qilingan'),
      null => '',
      _ => s,
    };

/// A receiving document (`GET /receiving/{id}`, `xaridlar.view`): number,
/// supplier, payment, branch, lines with costs, the invoice photo and a link to
/// the purchase document (corrections live there).
class ReceivingDetailScreen extends StatefulWidget {
  /// Creates the screen for receiving [id].
  const ReceivingDetailScreen({super.key, required this.id});

  /// Receiving id.
  final String id;

  @override
  State<ReceivingDetailScreen> createState() => _ReceivingDetailScreenState();
}

class _ReceivingDetailScreenState extends State<ReceivingDetailScreen> {
  final _ctl = AsyncViewController();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Qabul tafsiloti'))),
      body: SafeArea(
        child: AsyncView<ReceivingDetail>(
          controller: _ctl,
          load: () => ReceivingApi.detail(widget.id),
          refreshable: true,
          builder: (context, d) => _Body(detail: d, onChanged: _ctl.reload),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.detail, required this.onChanged});
  final ReceivingDetail detail;
  final Future<void> Function() onChanged;

  Widget _kv(String k, String v, {Key? key, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 128, child: Text(k, style: TextStyle(fontSize: 13, color: AppColors.muted))),
          Expanded(
            child: Text(v,
                key: key, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: color ?? AppColors.text)),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final d = detail.doc;
    final pid = d.purchaseId;
    final canOpenPurchase = pid != null && !d.cancelled && Perm.allows('purchases.detail');
    Uint8List? img;
    final b64 = detail.imageB64;
    if (b64 != null) {
      try {
        img = base64Decode(b64);
      } catch (_) {
        img = null;
      }
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(kGutter, 12, kGutter, 24),
      children: [
        Row(children: [
          Expanded(
            child: Text((d.docNo ?? '').isNotEmpty ? d.docNo! : tr('Kirim'),
                key: const Key('recv-detail-docno'), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          ),
          if (d.payment != RecvPayment.unknown)
            RecvBadge(recvPaymentLabel(d.payment),
                key: const Key('recv-detail-payment'), color: d.payment == RecvPayment.credit ? AppColors.warn : AppColors.ok),
        ]),
        const SizedBox(height: 4),
        Text('${dmy(d.at)} · ${d.employee}', style: TextStyle(color: AppColors.muted, fontSize: 13)),
        const SizedBox(height: 12),
        AppCard(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Column(children: [
            _kv(tr('Yetkazib beruvchi'), (d.supplier ?? '').isNotEmpty ? d.supplier! : '—', key: const Key('recv-detail-supplier')),
            if ((d.branchName ?? '').isNotEmpty) _kv(tr('Filial'), d.branchName!),
            _kv(tr('Manba'), recvSourceLabel(d.source)),
            if ((d.purchaseStatus ?? '').isNotEmpty)
              _kv(tr('Holati'), recvStatusLabel(d.purchaseStatus),
                  key: const Key('recv-detail-status'), color: d.cancelled ? AppColors.danger : null),
          ]),
        ),
        if (d.cancelled) ...[
          const SizedBox(height: 10),
          ErrorBanner(
            severity: BannerSeverity.warning,
            message: tr('Bu kirim tuzatish orqali to‘liq bekor qilingan — xarid hujjati yopilgan.'),
          ),
        ],
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: Text(tr('Mahsulotlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
          Text('${detail.items.length}', style: TextStyle(color: AppColors.muted)),
        ]),
        const SizedBox(height: 8),
        AppCard(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(children: [
            for (var i = 0; i < detail.items.length; i++) ...[
              if (i > 0) Divider(height: 1, color: AppColors.border),
              _line(detail.items[i]),
            ],
            Divider(height: 1, color: AppColors.border),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              child: Row(children: [
                Expanded(child: Text(tr('Jami summa'), style: const TextStyle(fontWeight: FontWeight.w700))),
                Text(formatCents(detail.totalCents),
                    key: const Key('recv-detail-total'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
              ]),
            ),
          ]),
        ),
        if (canOpenPurchase) ...[
          const SizedBox(height: 14),
          SizedBox(
            height: kPrimaryButtonHeight,
            child: OutlinedButton.icon(
              key: const Key('recv-detail-open-purchase'),
              onPressed: () async {
                final changed = await PurchaseDetailScreen.open(context, pid);
                if (changed) await onChanged();
              },
              icon: const Icon(Icons.receipt_long_outlined),
              label: Text(tr('Xarid hujjati (partiyalar, tuzatish)')),
            ),
          ),
        ],
        if (img != null) ...[
          const SizedBox(height: 18),
          Text(tr('Nakladnoy rasmi'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.memory(img, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const SizedBox()),
          ),
        ],
      ],
    );
  }

  Widget _line(ReceivingDetailItem it) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(it.name, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(
                '${formatMilli(it.qtyMilli, group: true)}${(it.unit ?? '').isEmpty ? '' : ' ${it.unit}'} × ${formatCents(it.unitCostCents)}',
                style: TextStyle(fontSize: 12.5, color: AppColors.muted),
              ),
              if ((it.aiName ?? '').isNotEmpty && it.aiName != it.name)
                Text(trArgs('AI o‘qidi: {name}', {'name': it.aiName}),
                    style: TextStyle(fontSize: 12, color: AppColors.faint, fontStyle: FontStyle.italic)),
            ]),
          ),
          const SizedBox(width: 8),
          Text(formatCents(it.totalCents), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        ]),
      );
}
