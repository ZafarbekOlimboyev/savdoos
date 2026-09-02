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
  // Bitta chiqarish = bitta uuid: qayta urinishda server qoldiqni ikki marta kamaytirmaydi.
  // QA WH-012: muvaffaqiyatdan keyin uuid YANGILANADI (dialog barrier bilan yopilib ekran
  // ochiq qolsa, keyingi BOSHQA chiqarish eski uuid bilan jim 'duplicate' bo'lardi).
  String _clientUuid = Api.newUuid();
  // QA WH-002: chiqarish ANIQ filialdan — yig'ma qoldiq ko'rsatib boshqa filialdan urish yopildi.
  List<BranchRow>? _branches;
  BranchRow? _branch;

  static const _reasons = [('brak', 'Brak (nuqsonli)', Icons.report_gmailerrorred), ('expired', 'Muddati o‘tgan', Icons.event_busy), ('inventory', 'Inventarizatsiya', Icons.fact_check)];

  @override
  void initState() {
    super.initState();
    Api.branches().then((b) {
      if (!mounted) return;
      final act = b.where((x) => x.visible && x.isActive).toList();
      setState(() {
        _branches = act;
        _branch = act.isNotEmpty ? act.first : null;
      });
      _loadProducts();
    }).catchError((_) { _loadProducts(); });
  }

  void _loadProducts() {
    Api.inventory(branchId: _branch?.id)
        .then((p) => mounted ? setState(() => _products = p) : null)
        .catchError((_) {});
  }

  Future<void> _pickBranch() async {
    final brs = _branches;
    if (brs == null || brs.length < 2) return;
    final sel = await showModalBottomSheet<BranchRow>(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(height: 12),
          Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2))),
          const SizedBox(height: 12),
          ...brs.map((b) => ListTile(
                leading: Icon(Icons.storefront, color: AppColors.accentStrong),
                title: Text(b.name),
                trailing: b.id == _branch?.id ? const Icon(Icons.check, size: 18) : null,
                onTap: () => Navigator.pop(context, b),
              )),
          const SizedBox(height: 12),
        ]),
      ),
    );
    if (sel != null && sel.id != _branch?.id) {
      setState(() { _branch = sel; _sel = null; _products = null; });
      _loadProducts();
    }
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
      await Api.writeoff(_sel!.id, v, _reason, clientUuid: _clientUuid, branchId: _branch?.id);
      if (!mounted) return;
      // QA WH-012: uuid yangilanadi — ekran ochiq qolsa keyingi chiqarish alohida amal bo'ladi
      setState(() { _busy = false; _clientUuid = Api.newUuid(); });
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (_) => AlertDialog(
          backgroundColor: AppColors.card,
          title: Text(tr('Chiqarildi ✓')),
          content: Text('${_sel!.name} ${tr('hisobdan chiqarildi')}', style: TextStyle(color: AppColors.text3)),
          actions: [ElevatedButton(onPressed: () { Navigator.pop(context); Navigator.pop(context); }, child: Text(tr('Yopish')))],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AppColors.card,
          title: Text(tr('Xato')),
          content: Text('$e', style: TextStyle(color: AppColors.text3)),
          actions: [ElevatedButton(onPressed: () => Navigator.pop(context), child: Text(tr('Yopish')))],
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Hisobdan chiqarish'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if ((_branches?.length ?? 0) > 1) ...[
            Text(tr('Filial'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            GestureDetector(
              onTap: _pickBranch,
              child: Container(
                height: 48,
                padding: const EdgeInsets.symmetric(horizontal: 14),
                decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.accentBorder)),
                child: Row(children: [
                  Icon(Icons.storefront, size: 17, color: AppColors.accentStrong),
                  const SizedBox(width: 9),
                  Expanded(child: Text(_branch?.name ?? tr('Filial'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700))),
                  Icon(Icons.expand_more, size: 17, color: AppColors.muted),
                ]),
              ),
            ),
            const SizedBox(height: 16),
          ],
          Text(tr('Tovar'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          GestureDetector(
            onTap: _products == null ? null : _pick,
            child: Container(
              height: 50,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.borderInput)),
              child: Row(children: [
                Expanded(child: Text(_sel?.name ?? tr('Mahsulot tanlang'), style: TextStyle(fontSize: 14, color: _sel == null ? AppColors.muted : AppColors.text))),
                Icon(Icons.search, size: 18, color: AppColors.muted),
              ]),
            ),
          ),
          if (_sel != null) ...[
            const SizedBox(height: 6),
            Text('${tr('Qoldiq')}: ${qtyStr(_sel!.stock)} ${_sel!.unit}', style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
          const SizedBox(height: 16),
          Text(tr('Miqdor'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          TextField(controller: _qty, keyboardType: const TextInputType.numberWithOptions(decimal: true), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          Text(tr('Sababi'), style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
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
                  Expanded(child: Text(tr(r.$2), style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600, color: on ? AppColors.text : AppColors.text3))),
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
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.remove_circle_outline, size: 20),
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
            child: TextField(autofocus: true, onChanged: (v) => setState(() => _q = v), decoration: InputDecoration(hintText: tr('Mahsulot qidirish...'), prefixIcon: Icon(Icons.search, color: AppColors.muted))),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: list.length,
              itemBuilder: (context, i) => ListTile(
                title: Text(list[i].name),
                trailing: Text('${qtyStr(list[i].stock)} ${list[i].unit}', style: TextStyle(color: AppColors.muted, fontSize: 12.5)),
                onTap: () => Navigator.pop(context, list[i]),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
