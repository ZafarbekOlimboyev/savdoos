import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Kassa kirim / chiqim — ochiq smenaga yoziladi (Ijara, Kommunal, Inkassatsiya...).
class CashOpsScreen extends StatefulWidget {
  const CashOpsScreen({super.key});
  @override
  State<CashOpsScreen> createState() => _CashOpsScreenState();
}

const _catsOut = [
  ('Ijara', Icons.home_outlined),
  ('Kommunal', Icons.bolt_outlined),
  ('Inkassatsiya', Icons.account_balance_outlined),
  ('Boshqa', Icons.more_horiz),
];

class _CashOpsScreenState extends State<CashOpsScreen> {
  bool _isIn = false; // false = chiqim (standart)
  String _cat = 'Ijara';
  final _amt = TextEditingController();
  final _note = TextEditingController();
  bool _busy = false;
  Future<List<CashOpRow>>? _today;

  @override
  void initState() {
    super.initState();
    _today = Api.cashOps();
  }

  @override
  void dispose() {
    _amt.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    // Vergul = kasr ajratkich ('12,5' -> 12.5); aks holda u o'chirilib 125 bo'lib ketardi
    final v = double.tryParse(_amt.text.replaceAll(',', '.').replaceAll(RegExp(r'[^0-9.]'), ''));
    if (v == null || v <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Summani kiriting'))));
      return;
    }
    setState(() => _busy = true);
    try {
      final type = _isIn ? 'payin' : (_cat == 'Inkassatsiya' ? 'collection' : 'expense');
      final reason = _isIn ? (_note.text.trim().isEmpty ? null : _note.text.trim())
          : '${_cat}${_note.text.trim().isEmpty ? '' : ' · ${_note.text.trim()}'}';
      await Api.cashOp(type, v, reason);
      if (!mounted) return;
      _amt.clear();
      _note.clear();
      setState(() { _today = Api.cashOps(); });
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Saqlandi ✓'))));
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Kassa kirim / chiqim'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Kirim / Chiqim toggle
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              _toggle(tr('Kirim'), true, AppColors.ok),
              _toggle(tr('Chiqim'), false, AppColors.danger),
            ]),
          ),
          const SizedBox(height: 18),
          Text(tr('Summa'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          TextField(
            controller: _amt,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800),
            decoration: const InputDecoration(hintText: '0', suffixText: "so'm"),
          ),
          if (!_isIn) ...[
            const SizedBox(height: 16),
            Text(tr('Xarajat turi'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8, runSpacing: 8,
              children: _catsOut.map((c) {
                final on = _cat == c.$1;
                return GestureDetector(
                  onTap: () => setState(() => _cat = c.$1),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      color: on ? AppColors.accentSoft : AppColors.card,
                      borderRadius: BorderRadius.circular(11),
                      border: Border.all(color: on ? AppColors.accent : AppColors.border, width: on ? 1.5 : 1),
                    ),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(c.$2, size: 16, color: on ? AppColors.accentStrong : AppColors.muted),
                      const SizedBox(width: 7),
                      Text(c.$1, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: on ? AppColors.accentStrong : AppColors.text3)),
                    ]),
                  ),
                );
              }).toList(),
            ),
          ],
          const SizedBox(height: 16),
          TextField(controller: _note, decoration: InputDecoration(hintText: tr('Izoh (ixtiyoriy)'))),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: _busy ? null : _save,
              style: ElevatedButton.styleFrom(backgroundColor: _isIn ? AppColors.ok : AppColors.accent),
              icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.check, size: 20),
              label: Text(tr('Saqlash')),
            ),
          ),
          const SizedBox(height: 26),
          Text(tr('Bugungi harakatlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          FutureBuilder<List<CashOpRow>>(
            future: _today,
            builder: (context, snap) {
              final rows = snap.data ?? [];
              if (snap.connectionState == ConnectionState.waiting) {
                return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
              }
              if (rows.isEmpty) {
                return Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Text(tr('Bugun harakat yo‘q'), style: TextStyle(color: AppColors.muted)));
              }
              return AppCard(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(children: [
                  for (int i = 0; i < rows.length; i++) _opRow(rows[i], i < rows.length - 1),
                ]),
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _toggle(String label, bool isIn, Color c) => Expanded(
        child: GestureDetector(
          onTap: () => setState(() => _isIn = isIn),
          child: Container(
            height: 44,
            decoration: BoxDecoration(
              color: _isIn == isIn ? c.withValues(alpha: 0.16) : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Center(child: Text(label, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: _isIn == isIn ? c : AppColors.muted))),
          ),
        ),
      );

  Widget _opRow(CashOpRow r, bool border) {
    final isIn = r.type == 'payin';
    final label = switch (r.type) {
      'payin' => tr('Kirim'), 'expense' => tr('Xarajat'), 'collection' => tr('Inkassatsiya'),
      'payout' => tr('Naqd topshirish'), 'opening' => tr('Smena ochildi'), _ => r.type,
    };
    final c = isIn ? AppColors.ok : AppColors.danger;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(border: border ? Border(bottom: BorderSide(color: AppColors.border)) : null),
      child: Row(children: [
        Icon(isIn ? Icons.south_west : Icons.north_east, size: 16, color: c),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(r.reason.isEmpty ? label : r.reason, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text('$label · ${hm(r.at)} · ${r.employee}', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        Text('${isIn ? '+' : '−'}${money(r.amount)}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: c)),
      ]),
    );
  }
}
