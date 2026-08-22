import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

class WriteoffScreen extends StatefulWidget {
  const WriteoffScreen({super.key});
  @override
  State<WriteoffScreen> createState() => _WriteoffScreenState();
}

class _WriteoffScreenState extends State<WriteoffScreen> {
  List<InvItem>? _products;
  InvItem? _sel;
  final _qty = TextEditingController(text: '1');
  String _reason = 'brak';
  bool _busy = false;

  static const _reasons = [('brak', 'Brak (nuqsonli)', Icons.report_gmailerrorred), ('expired', 'Muddati o‘tgan', Icons.event_busy), ('inventory', 'Inventarizatsiya', Icons.fact_check)];

  @override
  void initState() {
    super.initState();
    Api.inventory().then((p) => mounted ? setState(() => _products = p) : null).catchError((_) {});
  }

  @override
  void dispose() {
    _qty.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final prods = _products;
    if (prods == null) return;
    final sel = await showModalBottomSheet<InvItem>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _Picker(products: prods),
    );
    if (sel != null) setState(() => _sel = sel);
  }

  Future<void> _submit() async {
    final v = double.tryParse(_qty.text.replaceAll(',', '.'));
    if (_sel == null || v == null || v <= 0) return;
    setState(() => _busy = true);
    try {
      await Api.writeoff(_sel!.id, v, _reason);
      if (!mounted) return;
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${_sel!.name} hisobdan chiqarildi')));
    } catch (e) {
      setState(() => _busy = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Hisobdan chiqarish'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(tr('Tovar'), style: const TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          GestureDetector(
            onTap: _products == null ? null : _pick,
            child: Container(
              height: 50,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.borderInput)),
              child: Row(children: [
                Expanded(child: Text(_sel?.name ?? tr('Mahsulot tanlang'), style: TextStyle(fontSize: 14, color: _sel == null ? AppColors.muted : AppColors.text))),
                const Icon(Icons.search, size: 18, color: AppColors.muted),
              ]),
            ),
          ),
          if (_sel != null) ...[
            const SizedBox(height: 6),
            Text('Qoldiq: ${qtyStr(_sel!.stock)} ${_sel!.unit}', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
          const SizedBox(height: 16),
          Text(tr('Miqdor'), style: const TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          TextField(controller: _qty, keyboardType: const TextInputType.numberWithOptions(decimal: true), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          Text(tr('Sababi'), style: const TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          ..._reasons.map((r) {
            final on = _reason == r.$1;
            return GestureDetector(
              onTap: () => setState(() => _reason = r.$1),
              child: Container(
                margin: const EdgeInsets.only(bottom: 9),
                padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 14),
                decoration: BoxDecoration(
                  color: on ? AppColors.dangerSoft : AppColors.card,
                  borderRadius: BorderRadius.circular(13),
                  border: Border.all(color: on ? AppColors.danger : AppColors.border, width: on ? 1.5 : 1),
                ),
                child: Row(children: [
                  Icon(r.$3, size: 19, color: on ? AppColors.danger : AppColors.muted),
                  const SizedBox(width: 11),
                  Expanded(child: Text(r.$2, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600, color: on ? AppColors.text : AppColors.text3))),
                  if (on) const Icon(Icons.check_circle, size: 19, color: AppColors.danger),
                ]),
              ),
            );
          }),
        ],
      ),
      bottomNavigationBar: Container(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
        color: AppColors.bg,
        child: SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: (_busy || _sel == null) ? null : _submit,
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.remove_circle_outline, size: 20),
            label: Text(tr('Hisobdan chiqarish')),
          ),
        ),
      ),
    );
  }
}

class _Picker extends StatefulWidget {
  final List<InvItem> products;
  const _Picker({required this.products});
  @override
  State<_Picker> createState() => _PickerState();
}

class _PickerState extends State<_Picker> {
  String _q = '';
  @override
  Widget build(BuildContext context) {
    final ql = _q.toLowerCase();
    final list = _q.isEmpty ? widget.products : widget.products.where((p) => p.name.toLowerCase().contains(ql)).toList();
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.7,
        child: Column(children: [
          const SizedBox(height: 12),
          Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2))),
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(autofocus: true, onChanged: (v) => setState(() => _q = v), decoration: InputDecoration(hintText: tr('Mahsulot qidirish...'), prefixIcon: const Icon(Icons.search, color: AppColors.muted))),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: list.length,
              itemBuilder: (context, i) => ListTile(
                title: Text(list[i].name),
                trailing: Text('${qtyStr(list[i].stock)} ${list[i].unit}', style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
                onTap: () => Navigator.pop(context, list[i]),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
