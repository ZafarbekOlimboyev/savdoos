import 'package:flutter/material.dart';

import '../api/receiving_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'receiving_detail_screen.dart';

/// Result of `POST /receiving/commit` — shown ONLY after a 2xx.
///
/// A `duplicate: true` answer is NOT a success of this request: the server had
/// already saved this document in an earlier attempt (whose answer was lost)
/// and applied NOTHING from this one. The screen says so explicitly, and, when
/// the draft was edited after that attempt, that those edits were not saved.
///
/// Pops `true` (the receiving home reloads its history).
class ReceivingSuccessScreen extends StatelessWidget {
  /// Creates the screen.
  const ReceivingSuccessScreen({super.key, required this.result, this.editsMayBeLost = false});

  /// The server answer.
  final CommitResult result;

  /// The draft changed after an attempt whose outcome was unknown.
  final bool editsMayBeLost;

  void _openDoc(BuildContext context) => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => ReceivingDetailScreen(id: result.receivingId)),
      );

  @override
  Widget build(BuildContext context) {
    final r = result;
    final canOpen = Perm.allows('receiving.detail');
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.of(context).pop(true);
      },
      child: Scaffold(
        body: SafeArea(
          child: Column(children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 32, 20, 16),
                children: r.duplicate ? _duplicate(context) : _saved(context),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(20, 8, 20, 12 + MediaQuery.of(context).padding.bottom),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (canOpen) ...[
                  SizedBox(
                    height: kPrimaryButtonHeight,
                    child: r.duplicate
                        ? ElevatedButton.icon(
                            key: const Key('recv-done-open'),
                            onPressed: () => _openDoc(context),
                            icon: const Icon(Icons.description_outlined),
                            label: Text(tr('Saqlangan hujjatni ochish')),
                          )
                        : OutlinedButton.icon(
                            key: const Key('recv-done-open'),
                            onPressed: () => _openDoc(context),
                            icon: const Icon(Icons.description_outlined),
                            label: Text(tr('Hujjatni ochish')),
                          ),
                  ),
                  const SizedBox(height: 10),
                ],
                SizedBox(
                  height: kPrimaryButtonHeight,
                  child: r.duplicate
                      ? OutlinedButton(
                          key: const Key('recv-done-close'),
                          onPressed: () => Navigator.pop(context, true),
                          child: Text(tr('Yopish')),
                        )
                      : ElevatedButton(
                          key: const Key('recv-done-new'),
                          onPressed: () => Navigator.pop(context, true),
                          child: Text(tr('Yangi qabul qilish')),
                        ),
                ),
                if (!r.duplicate) ...[
                  const SizedBox(height: 6),
                  SizedBox(
                    height: kMinTouch,
                    child: TextButton(
                      key: const Key('recv-done-home'),
                      onPressed: () => Navigator.of(context).popUntil((route) => route.isFirst),
                      child: Text(tr('Bosh sahifaga'), style: TextStyle(color: AppColors.text3)),
                    ),
                  ),
                ],
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _icon(IconData icon, Color fg, Color bg) => Center(
        child: Container(
          width: 76,
          height: 76,
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(24)),
          child: Icon(icon, color: fg, size: 44),
        ),
      );

  List<Widget> _duplicate(BuildContext context) => [
        _icon(Icons.info_outline, AppColors.warn, AppColors.warnSoft),
        const SizedBox(height: 18),
        Text(tr('Bu kirim avval saqlangan'),
            key: const Key('recv-duplicate-title'),
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
        const SizedBox(height: 10),
        Text(
          tr('Server bu hujjatni oldingi urinishda qabul qilgan (javobi sizga yetib kelmagan edi). Bu safargi yuborish qayta yozilmadi — ombor ikki marta o‘zgarmadi.'),
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 14.5, height: 1.4, color: AppColors.text2),
        ),
        const SizedBox(height: 14),
        Container(
          key: const Key('recv-duplicate-edits'),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: editsMayBeLost ? AppColors.dangerSoft : AppColors.surface,
            borderRadius: BorderRadius.circular(kRadius),
            border: Border.all(color: editsMayBeLost ? AppColors.danger.withAlpha(120) : AppColors.border),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.warning_amber_rounded, color: editsMayBeLost ? AppColors.danger : AppColors.warn),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                editsMayBeLost
                    ? tr('Oldingi urinishdan keyin kiritilgan o‘zgarishlar QO‘LLANMADI. Saqlangan hujjatni ochib tekshiring; farq bo‘lsa, hujjatni tuzating.')
                    : tr('Keyingi o‘zgarishlar qo‘llanmaydi — saqlangan hujjat oldingi urinishdagidek qoldi.'),
                style: TextStyle(fontSize: 14, height: 1.35, color: AppColors.text),
              ),
            ),
          ]),
        ),
      ];

  List<Widget> _saved(BuildContext context) {
    final r = result;
    final meta = [
      if ((r.docNo ?? '').isNotEmpty) r.docNo!,
      if ((r.supplier ?? '').isNotEmpty) r.supplier!,
      if (r.payment != RecvPayment.unknown) recvPaymentLabel(r.payment),
    ].join(' · ');
    return [
      _icon(Icons.check_circle, AppColors.ok, AppColors.okSoft),
      const SizedBox(height: 18),
      Text(tr('Mahsulotlar omborga qo‘shildi'),
          key: const Key('recv-saved-title'),
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
      const SizedBox(height: 6),
      Text(trArgs('{n} ta mahsulot muvaffaqiyatli qabul qilindi', {'n': r.totalTypes}),
          textAlign: TextAlign.center, style: TextStyle(color: AppColors.muted, fontSize: 13.5)),
      if (meta.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text(meta,
            key: const Key('recv-saved-meta'),
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.text3, fontSize: 13.5, fontWeight: FontWeight.w600)),
      ],
      const SizedBox(height: 22),
      if (r.results.isNotEmpty)
        AppCard(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(children: [
            for (final x in r.results)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                child: Row(children: [
                  Expanded(
                    child: Text(x.product, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                  ),
                  Text(formatMilli(x.oldMilli, group: true), style: TextStyle(color: AppColors.muted, fontSize: 13)),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Icon(Icons.arrow_forward, size: 14, color: AppColors.faint),
                  ),
                  Text(formatMilli(x.newMilli, group: true),
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AppColors.ok)),
                  const SizedBox(width: 6),
                  Text('(+${formatMilli(x.addedMilli, group: true)}${(x.unit ?? '').isEmpty ? '' : ' ${x.unit}'})',
                      style: const TextStyle(color: AppColors.ok, fontSize: 12)),
                ]),
              ),
          ]),
        ),
    ];
  }
}
