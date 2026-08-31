import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

class SuppliersScreen extends StatefulWidget {
  const SuppliersScreen({super.key});
  @override
  State<SuppliersScreen> createState() => _SuppliersScreenState();
}

class _SuppliersScreenState extends State<SuppliersScreen> {
  Future<List<SupplierRow>>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.suppliers();
  }

  void _reload() => setState(() { _future = Api.suppliers(); });

  Future<void> _pay(SupplierRow s) async {
    final paid = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PaySheet(supplier: s),
    );
    if (paid == true) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Yetkazib beruvchilar'))),
      body: FutureBuilder<List<SupplierRow>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final all = snap.data ?? [];
          final owe = all.where((s) => s.balance > 0).toList()..sort((a, b) => b.balance.compareTo(a.balance));
          final total = owe.fold<double>(0, (a, s) => a + s.balance);
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.danger)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('Biz qarzmiz'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                    const SizedBox(height: 4),
                    Text(money(total), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: AppColors.danger, letterSpacing: -0.5)),
                  ]),
                ),
                const SizedBox(height: 16),
                if (owe.isEmpty)
                  Padding(padding: const EdgeInsets.symmetric(vertical: 24), child: Center(child: Text(tr('Qarz yo‘q 👍'), style: TextStyle(color: AppColors.muted))))
                else
                  ...owe.map((s) => _row(s)),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _row(SupplierRow s) => GestureDetector(
        onTap: () => _pay(s),
        child: Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Container(
              width: 40, height: 40,
              decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(11)),
              child: Icon(Icons.local_shipping_outlined, color: AppColors.accentStrong, size: 20),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(s.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                if (s.phone != null && s.phone!.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(s.phone!, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                ],
              ]),
            ),
            Text(money(s.balance), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger)),
          ]),
        ),
      );
}

class _PaySheet extends StatefulWidget {
  final SupplierRow supplier;
  const _PaySheet({required this.supplier});
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
    _amt = TextEditingController(text: widget.supplier.balance.toStringAsFixed(0));
  }

  @override
  void dispose() {
    _amt.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final v = double.tryParse(_amt.text.replaceAll(RegExp(r'[^0-9.]'), ''));
    if (v == null || v <= 0) return;
    setState(() => _busy = true);
    try {
      await Api.paySupplier(widget.supplier.id, v, clientUuid: _clientUuid);
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
        Text(tr('Yetkazib beruvchiga to‘lash'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(13)),
          child: Column(children: [
            Text('${widget.supplier.name} · ${tr('Biz qarzmiz')}', style: TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(money(widget.supplier.balance), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.danger)),
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
