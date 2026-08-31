import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Mijoz profili: qarz balansi + qarz so'ndirish, xaridlar tarixi, to'lovlar.
class CustomerProfileScreen extends StatefulWidget {
  final String customerId;
  final String name;
  const CustomerProfileScreen({super.key, required this.customerId, required this.name});
  @override
  State<CustomerProfileScreen> createState() => _CustomerProfileScreenState();
}

class _CustomerProfileScreenState extends State<CustomerProfileScreen> {
  Future<CustomerDetail>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.customerDetail(widget.customerId);
  }

  void _reload() => setState(() { _future = Api.customerDetail(widget.customerId); });

  Future<void> _pay(double balance) async {
    final ok = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PaySheet(customerId: widget.customerId, name: widget.name, balance: balance),
    );
    if (ok == true) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.name, maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: FutureBuilder<CustomerDetail>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final d = snap.data!;
          final debtor = d.creditBalance > 0;
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Profil boshi
                Row(children: [
                  CircleAvatar(radius: 28, backgroundColor: AppColors.accentSoft, child: Text(d.fullName.isEmpty ? '?' : d.fullName[0], style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: AppColors.accentStrong))),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(d.fullName, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                      if (d.phone != null && d.phone!.isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(d.phone!, style: TextStyle(fontSize: 13, color: AppColors.muted)),
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
                // Qarz kartasi
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: debtor ? AppColors.dangerSoft : AppColors.okSoft,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: debtor ? AppColors.danger : AppColors.ok.withValues(alpha: 0.3)),
                  ),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(tr('Qarz'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                        const SizedBox(height: 4),
                        Text(money(d.creditBalance), style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: debtor ? AppColors.danger : AppColors.ok, letterSpacing: -0.5)),
                      ]),
                    ),
                    if (debtor)
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: AppColors.ok, padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12)),
                        onPressed: () => _pay(d.creditBalance),
                        child: Text(tr('Qarzni so‘ndirish')),
                      ),
                  ]),
                ),
                const SizedBox(height: 12),
                // Statistika
                Row(children: [
                  Expanded(child: _stat(tr('Jami xarid'), money(d.totalSpent), Icons.shopping_bag_outlined)),
                  const SizedBox(width: 12),
                  Expanded(child: _stat(tr('Tashriflar'), '${d.visits}', Icons.event_repeat_outlined)),
                ]),
                const SizedBox(height: 20),
                // Xaridlar tarixi
                Text(tr('Xaridlar tarixi'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                if (d.history.isEmpty)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Text(tr('Xarid yo‘q'), style: TextStyle(color: AppColors.muted)))
                else
                  AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(children: [
                      for (int i = 0; i < d.history.length; i++) _histRow(d.history[i], i < d.history.length - 1),
                    ]),
                  ),
                if (d.payments.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  Text(tr('To‘lovlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 10),
                  AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(children: [
                      for (int i = 0; i < d.payments.length; i++) _payRow(d.payments[i], i < d.payments.length - 1),
                    ]),
                  ),
                ],
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _stat(String label, String value, IconData ic) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(ic, size: 18, color: AppColors.accentStrong),
          const SizedBox(height: 8),
          Text(value, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
        ]),
      );

  Widget _histRow(CustHistory h, bool border) {
    final label = switch (h.method) {
      'cash' => tr('Naqd'), 'card' => tr('Karta'), 'qr' => 'QR', 'credit' => tr('Qarz'), _ => h.method,
    };
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${qtyStr(h.items.toDouble())} ${tr('dona')} · $label', style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(hm(h.at), style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        Text(money(h.amount), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
      ]),
    );
  }

  Widget _payRow(CustPayment p, bool border) => Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
        child: Row(children: [
          const Icon(Icons.south_west, size: 16, color: AppColors.ok),
          const SizedBox(width: 10),
          Expanded(child: Text(hm(p.at), style: TextStyle(fontSize: 12.5, color: AppColors.text3))),
          Text('+${money(p.amount)}', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.ok)),
        ]),
      );
}

class _PaySheet extends StatefulWidget {
  final String customerId, name;
  final double balance;
  const _PaySheet({required this.customerId, required this.name, required this.balance});
  @override
  State<_PaySheet> createState() => _PaySheetState();
}

class _PaySheetState extends State<_PaySheet> {
  late final TextEditingController _amt;
  bool _busy = false;
  // Barqaror idempotentlik kaliti (bitta oyna = bitta to'lov) — qayta yuborishда ikki marta emas.
  final String _clientUuid = Api.newUuid();
  @override
  void initState() {
    super.initState();
    _amt = TextEditingController(text: widget.balance.toStringAsFixed(0));
  }

  @override
  void dispose() {
    _amt.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    // Vergul = kasr ajratkich ('500,50' -> 500.50); aks holda o'chirilib 50050 bo'lib ketardi (100x)
    final v = double.tryParse(_amt.text.replaceAll(',', '.').replaceAll(RegExp(r'[^0-9.]'), ''));
    if (v == null || v <= 0) return;
    setState(() => _busy = true);
    try {
      await Api.payCredit(widget.customerId, v, clientUuid: _clientUuid);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() => _busy = false);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${tr('Xato')}: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 12, 20, 24 + MediaQuery.of(context).viewInsets.bottom),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
        const SizedBox(height: 16),
        Text(tr('Qarzni so‘ndirish'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(13)),
          child: Column(children: [
            Text('${widget.name} · ${tr('joriy qarz')}', style: TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(money(widget.balance), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.danger)),
          ]),
        ),
        const SizedBox(height: 16),
        Text(tr('To‘lov summasi'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        TextField(controller: _amt, keyboardType: const TextInputType.numberWithOptions(decimal: true), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.ok),
            onPressed: _busy ? null : _submit,
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.check, size: 20),
            label: Text(tr('To‘lovni tasdiqlash')),
          ),
        ),
      ]),
    );
  }
}
