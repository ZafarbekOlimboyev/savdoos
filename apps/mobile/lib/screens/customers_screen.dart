import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../theme.dart';

class CustomersScreen extends StatefulWidget {
  final bool onlyDebt;
  const CustomersScreen({super.key, this.onlyDebt = false});
  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  Future<List<Debtor>>? _future;
  late bool _debt;
  String _q = '';

  @override
  void initState() {
    super.initState();
    _debt = widget.onlyDebt;
    _reload();
  }

  void _reload() => setState(() => _future = Api.customers(onlyDebt: _debt));

  Future<void> _pay(Debtor c) async {
    final ok = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PayCreditSheet(customer: c),
    );
    if (ok == true) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mijozlar')),
      body: FutureBuilder<List<Debtor>>(
        future: _future,
        builder: (context, snap) {
          final loading = snap.connectionState == ConnectionState.waiting;
          final all = snap.data ?? [];
          final ql = _q.toLowerCase();
          final rows = all.where((c) => ql.isEmpty || c.name.toLowerCase().contains(ql) || (c.phone ?? '').contains(ql)).toList();
          return Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: Column(children: [
                TextField(
                  onChanged: (v) => setState(() => _q = v),
                  decoration: const InputDecoration(hintText: 'Ism yoki telefon qidirish...', prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 20), isDense: true),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  _chip('Barcha', false),
                  const SizedBox(width: 8),
                  _chip('Qarzdor', true),
                ]),
              ]),
            ),
            Expanded(
              child: loading
                  ? const Center(child: CircularProgressIndicator())
                  : rows.isEmpty
                      ? const Center(child: Text('Topilmadi', style: TextStyle(color: AppColors.muted)))
                      : RefreshIndicator(
                          onRefresh: () async => _reload(),
                          child: ListView.builder(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                            itemCount: rows.length,
                            itemBuilder: (context, i) => _row(rows[i]),
                          ),
                        ),
            ),
          ]);
        },
      ),
    );
  }

  Widget _chip(String label, bool debt) {
    final on = _debt == debt;
    return GestureDetector(
      onTap: () { setState(() => _debt = debt); _reload(); },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 8),
        decoration: BoxDecoration(
          color: on ? AppColors.accent : AppColors.card,
          borderRadius: BorderRadius.circular(9),
          border: Border.all(color: on ? AppColors.accent : AppColors.border),
        ),
        child: Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: on ? Colors.white : AppColors.text3)),
      ),
    );
  }

  Widget _row(Debtor c) {
    final debtor = c.balance > 0;
    return GestureDetector(
      onTap: debtor ? () => _pay(c) : null,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
        child: Row(children: [
          CircleAvatar(radius: 21, backgroundColor: AppColors.accentSoft, child: Text(c.name.isEmpty ? '?' : c.name[0], style: const TextStyle(color: AppColors.accentStrong, fontWeight: FontWeight.w700))),
          const SizedBox(width: 13),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(c.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
              if (c.phone != null && c.phone!.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(c.phone!, style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
              ],
            ]),
          ),
          if (debtor)
            Text(money(c.balance), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger)),
        ]),
      ),
    );
  }
}

class _PayCreditSheet extends StatefulWidget {
  final Debtor customer;
  const _PayCreditSheet({required this.customer});
  @override
  State<_PayCreditSheet> createState() => _PayCreditSheetState();
}

class _PayCreditSheetState extends State<_PayCreditSheet> {
  late final TextEditingController _amt;
  bool _busy = false;
  @override
  void initState() {
    super.initState();
    _amt = TextEditingController(text: widget.customer.balance.toStringAsFixed(0));
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
      await Api.payCredit(widget.customer.id, v);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() => _busy = false);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 12, 20, 24 + MediaQuery.of(context).viewInsets.bottom),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
        const SizedBox(height: 16),
        const Text('Qarzni so‘ndirish', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(13)),
          child: Column(children: [
            Text('${widget.customer.name} · joriy qarz', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(money(widget.customer.balance), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.danger)),
          ]),
        ),
        const SizedBox(height: 16),
        const Text('To‘lov summasi', style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        TextField(controller: _amt, keyboardType: const TextInputType.numberWithOptions(decimal: true), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.ok),
            onPressed: _busy ? null : _submit,
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.check, size: 20),
            label: const Text('To‘lovni tasdiqlash'),
          ),
        ),
      ]),
    );
  }
}
