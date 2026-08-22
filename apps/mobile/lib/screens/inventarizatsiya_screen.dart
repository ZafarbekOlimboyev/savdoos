import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

class InventarizatsiyaScreen extends StatefulWidget {
  const InventarizatsiyaScreen({super.key});
  @override
  State<InventarizatsiyaScreen> createState() => _InventarizatsiyaScreenState();
}

class _InventarizatsiyaScreenState extends State<InventarizatsiyaScreen> {
  Future<List<InvItem>>? _future;
  final Map<String, double> _counted = {}; // product id -> sanoq
  String _q = '';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _future = Api.inventory();
  }

  int get _diffCount => _counted.length;

  Future<void> _enter(InvItem it) async {
    final ctl = TextEditingController(text: (_counted[it.id] ?? it.stock).toStringAsFixed(0));
    final v = await showDialog<double>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(it.name, style: const TextStyle(fontSize: 16)),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Tizim: ${qtyStr(it.stock)} ${it.unit}', style: const TextStyle(color: AppColors.muted, fontSize: 13)),
          const SizedBox(height: 10),
          TextField(controller: ctl, autofocus: true, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: InputDecoration(labelText: tr('Sanoq (haqiqiy qoldiq)'))),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Bekor'))),
          ElevatedButton(onPressed: () {
            final x = double.tryParse(ctl.text.replaceAll(',', '.'));
            Navigator.pop(context, x != null && x >= 0 ? x : null);
          }, child: Text(tr('Saqlash'))),
        ],
      ),
    );
    if (v != null) setState(() { _counted[it.id] = v; });
  }

  Future<void> _submit() async {
    if (_counted.isEmpty) return;
    setState(() => _busy = true);
    try {
      final items = _counted.entries.map((e) => {'product_id': e.key, 'counted': e.value}).toList();
      final changed = await Api.stockCount(items);
      if (!mounted) return;
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Inventarizatsiya: $changed ta farq saqlandi')));
    } catch (e) {
      setState(() => _busy = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Inventarizatsiya'))),
      body: FutureBuilder<List<InvItem>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          final items = snap.data ?? [];
          final ql = _q.toLowerCase();
          final list = items.where((it) => ql.isEmpty || it.name.toLowerCase().contains(ql)).toList();
          return Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: TextField(
                onChanged: (v) => setState(() => _q = v),
                decoration: InputDecoration(hintText: tr('Mahsulot qidirish...'), prefixIcon: const Icon(Icons.search, color: AppColors.muted, size: 20), isDense: true),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Row(children: [
                Expanded(child: Text(tr('Mahsulot'), style: const TextStyle(fontSize: 11, color: AppColors.muted, fontWeight: FontWeight.w600))),
                SizedBox(width: 50, child: Text(tr('Tizim'), textAlign: TextAlign.center, style: const TextStyle(fontSize: 11, color: AppColors.muted, fontWeight: FontWeight.w600))),
                SizedBox(width: 60, child: Text(tr('Sanoq'), textAlign: TextAlign.right, style: const TextStyle(fontSize: 11, color: AppColors.muted, fontWeight: FontWeight.w600))),
              ]),
            ),
            const SizedBox(height: 6),
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                itemCount: list.length,
                itemBuilder: (context, i) => _row(list[i]),
              ),
            ),
          ]);
        },
      ),
      bottomNavigationBar: Container(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
        color: AppColors.bg,
        child: SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: (_busy || _counted.isEmpty) ? null : _submit,
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.check, size: 20),
            label: Text(_busy ? tr('Saqlanyapti...') : 'Tasdiqlash · $_diffCount farq'),
          ),
        ),
      ),
    );
  }

  Widget _row(InvItem it) {
    final counted = _counted[it.id];
    final diff = counted == null ? null : counted - it.stock;
    final diffCol = diff == null ? AppColors.faint : (diff == 0 ? AppColors.ok : (diff > 0 ? AppColors.warn : AppColors.danger));
    return GestureDetector(
      onTap: () => _enter(it),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: counted != null ? diffCol.withValues(alpha: 0.4) : AppColors.border),
        ),
        child: Column(children: [
          Row(children: [
            Expanded(child: Text(it.name, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600))),
            SizedBox(width: 50, child: Text(qtyStr(it.stock), textAlign: TextAlign.center, style: const TextStyle(fontSize: 14, color: AppColors.muted))),
            SizedBox(
              width: 60,
              child: Container(
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: AppColors.bg, borderRadius: BorderRadius.circular(9), border: Border.all(color: AppColors.accentBorder)),
                child: Text(counted == null ? '—' : qtyStr(counted), style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: counted == null ? AppColors.faint : AppColors.text)),
              ),
            ),
          ]),
          if (diff != null && diff != 0) ...[
            const SizedBox(height: 6),
            Align(alignment: Alignment.centerRight, child: Text('${diff > 0 ? '+' : ''}${qtyStr(diff)}', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: diffCol))),
          ],
        ]),
      ),
    );
  }
}
