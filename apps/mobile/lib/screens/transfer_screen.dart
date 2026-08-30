import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Filiallararo transfer: qayerdan -> qayerga, mahsulotlar + miqdor.
class TransferScreen extends StatefulWidget {
  const TransferScreen({super.key});
  @override
  State<TransferScreen> createState() => _TransferScreenState();
}

class _TransferScreenState extends State<TransferScreen> {
  List<BranchRow>? _branches;
  List<ProductLite>? _products;
  BranchRow? _from, _to;
  final List<(ProductLite, double)> _items = [];
  bool _busy = false;
  String? _err;
  // Bitta transfer = bitta uuid: qayta urinishda server dublikat ko'chirish yaratmaydi.
  // Muvaffaqiyatli tasdiqdan keyin ekran yopiladi — keyingi transfer yangi uuid oladi.
  final String _clientUuid = Api.newUuid();

  @override
  void initState() {
    super.initState();
    Api.branches().then((b) {
      if (!mounted) return;
      setState(() {
        _branches = b;
        if (b.length >= 2) { _from = b[0]; _to = b[1]; }
      });
    }).catchError((e) {
      if (mounted) setState(() => _err = e.toString());
    });
    Api.products().then((p) => mounted ? setState(() => _products = p) : null).catchError((_) {});
  }

  Future<void> _pickBranch(bool isFrom) async {
    final brs = _branches;
    if (brs == null) return;
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
                onTap: () => Navigator.pop(context, b),
              )),
          const SizedBox(height: 12),
        ]),
      ),
    );
    if (sel != null) setState(() => isFrom ? _from = sel : _to = sel);
  }

  Future<void> _addItem() async {
    final prods = _products;
    if (prods == null) return;
    final sel = await showModalBottomSheet<ProductLite>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _ProductSearch(products: prods),
    );
    if (sel == null || !mounted) return;
    final qty = await _askQty(sel.name);
    if (qty != null) setState(() => _items.add((sel, qty)));
  }

  Future<double?> _askQty(String name) {
    final ctl = TextEditingController(text: '1');
    return showDialog<double>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(name, style: const TextStyle(fontSize: 16)),
        content: TextField(controller: ctl, keyboardType: const TextInputType.numberWithOptions(decimal: true), autofocus: true, decoration: InputDecoration(labelText: tr('Miqdor'))),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Bekor'))),
          ElevatedButton(
            onPressed: () {
              final v = double.tryParse(ctl.text.replaceAll(',', '.'));
              Navigator.pop(context, (v != null && v > 0) ? v : null);
            },
            child: Text(tr('Qo‘shish')),
          ),
        ],
      ),
    );
  }

  Future<void> _confirm() async {
    if (_from == null || _to == null || _items.isEmpty) return;
    setState(() => _busy = true);
    try {
      final res = await Api.transfer(_from!.id, _to!.id, _items.map((i) => (i.$1.id, i.$2)).toList(),
          clientUuid: _clientUuid);
      if (!mounted) return;
      final moved = (res['moved'] as List?) ?? [];
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AppColors.card,
          title: Text(tr('Ko‘chirildi ✓')),
          content: Text('${_from!.name} → ${_to!.name}\n${moved.length} mahsulot ko‘chirildi',
              style: TextStyle(color: AppColors.text3)),
          actions: [ElevatedButton(onPressed: () { Navigator.pop(context); Navigator.pop(context); }, child: Text(tr('Yopish')))],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AppColors.card,
          title: Text(tr('Xato')),
          content: Text('$e', style: TextStyle(color: AppColors.text3)),
          actions: [ElevatedButton(onPressed: () => Navigator.pop(context), child: Text(tr('Yopish')))],
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final brs = _branches;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Filiallararo transfer'))),
      body: brs == null
          ? Center(child: _err != null ? Text(_err!, style: TextStyle(color: AppColors.muted)) : const CircularProgressIndicator())
          : brs.length < 2
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Text(tr('Transfer uchun kamida 2 ta filial kerak.\nFilial qo‘shish — Manager ilovasida.'),
                        textAlign: TextAlign.center, style: TextStyle(color: AppColors.muted, height: 1.5)),
                  ),
                )
              : Column(children: [
                  Expanded(
                    child: ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        Row(children: [
                          _branchBox(tr('Qayerdan'), _from, () => _pickBranch(true)),
                          Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: Icon(Icons.arrow_forward, color: AppColors.accentStrong, size: 20)),
                          _branchBox(tr('Qayerga'), _to, () => _pickBranch(false)),
                        ]),
                        const SizedBox(height: 20),
                        Row(children: [
                          Text(tr('Mahsulotlar'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                          const Spacer(),
                          GestureDetector(
                            onTap: _products == null ? null : _addItem,
                            child: Text(tr('+ Qo‘shish'), style: TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600)),
                          ),
                        ]),
                        const SizedBox(height: 10),
                        if (_items.isEmpty)
                          Padding(padding: const EdgeInsets.symmetric(vertical: 20), child: Center(child: Text(tr('Mahsulot qo‘shilmagan'), style: TextStyle(color: AppColors.muted))))
                        else
                          ..._items.asMap().entries.map((e) => Container(
                                margin: const EdgeInsets.only(bottom: 8),
                                padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 12),
                                decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
                                child: Row(children: [
                                  Expanded(child: Text(e.value.$1.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
                                  Text(qtyStr(e.value.$2), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
                                  IconButton(
                                    onPressed: () => setState(() => _items.removeAt(e.key)),
                                    icon: Icon(Icons.close, size: 17, color: AppColors.faint),
                                    visualDensity: VisualDensity.compact,
                                  ),
                                ]),
                              )),
                      ],
                    ),
                  ),
                  Container(
                    padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
                    decoration: BoxDecoration(color: AppColors.card, border: Border(top: BorderSide(color: AppColors.border))),
                    child: SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: (_busy || _from == null || _to == null || _from!.id == _to!.id || _items.isEmpty) ? null : _confirm,
                        icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.swap_horiz, size: 20),
                        label: Text(tr('Ko‘chirishni tasdiqlash')),
                      ),
                    ),
                  ),
                ]),
    );
  }

  Widget _branchBox(String label, BranchRow? b, VoidCallback onTap) => Expanded(
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: TextStyle(fontSize: 11, color: AppColors.muted)),
              const SizedBox(height: 3),
              Row(children: [
                Expanded(child: Text(b?.name ?? tr('Tanlang'), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700))),
                Icon(Icons.expand_more, size: 16, color: AppColors.muted),
              ]),
            ]),
          ),
        ),
      );
}

class _ProductSearch extends StatefulWidget {
  final List<ProductLite> products;
  const _ProductSearch({required this.products});
  @override
  State<_ProductSearch> createState() => _ProductSearchState();
}

class _ProductSearchState extends State<_ProductSearch> {
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
          Expanded(child: ListView.builder(itemCount: list.length, itemBuilder: (context, i) => ListTile(title: Text(list[i].name), onTap: () => Navigator.pop(context, list[i])))),
        ]),
      ),
    );
  }
}
