import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Qo'lda kirim: mavjud mahsulotni qidirib tanlash (narxlar bazadan avto-to'ladi,
/// o'zgartirilsa kartochkada ham yangilanadi) yoki YANGI mahsulot (nom + kategoriya +
/// kelish narxi + sotish narxi) kiritish. Tasdiqlansa omborga kirim bo'ladi.
class ManualReceivingScreen extends StatefulWidget {
  const ManualReceivingScreen({super.key});
  @override
  State<ManualReceivingScreen> createState() => _ManualReceivingScreenState();
}

class _Entry {
  String? productId;                      // tanlangan mavjud mahsulot
  String? categoryId;                     // yangi mahsulot kategoriyasi
  final nameC = TextEditingController();
  final qtyC = TextEditingController();
  final costC = TextEditingController();  // kelish narxi
  final sellC = TextEditingController();  // sotish narxi
  bool open = false;                      // takliflar ochiqmi
  void dispose() { nameC.dispose(); qtyC.dispose(); costC.dispose(); sellC.dispose(); }
}

class _ManualReceivingScreenState extends State<ManualReceivingScreen> {
  List<InvItem> _all = [];
  List<CategoryLite> _cats = [];
  final List<_Entry> _rows = [_Entry()];
  String _payment = 'cash';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    Api.inventoryAll().then((v) => mounted ? setState(() => _all = v) : null).catchError((_) {});
    Api.catList().then((v) => mounted ? setState(() => _cats = v) : null).catchError((_) {});
  }

  @override
  void dispose() {
    for (final r in _rows) { r.dispose(); }
    super.dispose();
  }

  double get _total => _rows.fold(0.0, (t, r) {
        final q = double.tryParse(r.qtyC.text.replaceAll(',', '.')) ?? 0;
        final c = double.tryParse(r.costC.text) ?? 0;
        return t + q * c;
      });

  void _pick(_Entry r, InvItem p) {
    setState(() {
      r.productId = p.id;
      r.nameC.text = p.name;
      r.costC.text = p.buyPrice > 0 ? p.buyPrice.round().toString() : '';
      r.sellC.text = p.sellPrice > 0 ? p.sellPrice.round().toString() : '';
      r.open = false;
    });
  }

  Future<void> _save() async {
    final items = <ReviewItem>[];
    for (final r in _rows) {
      final name = r.nameC.text.trim();
      final qty = double.tryParse(r.qtyC.text.replaceAll(',', '.')) ?? 0;
      if (name.isEmpty || qty <= 0) continue;
      final cost = double.tryParse(r.costC.text) ?? 0;
      final sell = double.tryParse(r.sellC.text);
      items.add(ReviewItem(
        productId: r.productId,
        newName: r.productId == null ? name : null,
        newSellPrice: sell,
        newCategoryId: r.productId == null ? r.categoryId : null,
        name: name, qty: qty, unitCost: cost, unit: 'dona',
      ));
    }
    if (items.isEmpty) {
      _snack(tr('Kamida bitta mahsulot va miqdor kiriting'));
      return;
    }
    setState(() => _busy = true);
    try {
      final res = await Api.commit(items, null, payment: _payment, source: 'manual');
      if (!mounted) return;
      final n = (res['total_types'] ?? items.length);
      _snack(tr('Qabul qilindi') + ': $n');
      Navigator.of(context).pop(true);
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _snack(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Qo‘lda kirim'))),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              children: [
                for (var i = 0; i < _rows.length; i++) _entryCard(i),
                const SizedBox(height: 6),
                OutlinedButton.icon(
                  onPressed: () => setState(() => _rows.add(_Entry())),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.accentStrong,
                    side: const BorderSide(color: AppColors.accentStrong, width: 1.2),
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  icon: const Icon(Icons.add, size: 19),
                  label: Text(tr('Mahsulot qo‘shish')),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            decoration: const BoxDecoration(
              color: AppColors.card,
              border: Border(top: BorderSide(color: AppColors.border)),
            ),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Expanded(child: _payBtn('cash', tr('To‘landi'))),
                const SizedBox(width: 8),
                Expanded(child: _payBtn('credit', tr('Qarzga'))),
                const SizedBox(width: 14),
                Text(money(_total), style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
              ]),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _busy ? null : _save,
                  child: Text(_busy ? '...' : tr('Kirimni saqlash')),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _payBtn(String v, String label) {
    final on = _payment == v;
    return GestureDetector(
      onTap: () => setState(() => _payment = v),
      child: Container(
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? AppColors.accentSoft : AppColors.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: on ? AppColors.accentStrong : AppColors.border, width: 1.2),
        ),
        child: Text(label, style: TextStyle(
          fontSize: 13, fontWeight: FontWeight.w700,
          color: on ? AppColors.accentStrong : AppColors.muted,
        )),
      ),
    );
  }

  Widget _entryCard(int i) {
    final r = _rows[i];
    final q = r.nameC.text.trim().toLowerCase();
    final sugg = (r.open && r.productId == null && q.length >= 2)
        ? _all.where((p) => p.name.toLowerCase().contains(q)).take(6).toList()
        : <InvItem>[];
    final isNew = r.productId == null && r.nameC.text.trim().isNotEmpty && !r.open;
    final picked = r.productId != null ? _all.where((p) => p.id == r.productId).toList() : <InvItem>[];

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: TextField(
              controller: r.nameC,
              decoration: InputDecoration(hintText: tr('Mahsulot qidiring yoki yangi nom yozing')),
              onChanged: (_) => setState(() { r.productId = null; r.open = true; }),
              onTap: () => setState(() => r.open = true),
            ),
          ),
          IconButton(
            onPressed: () => setState(() { _rows[i].dispose(); _rows.removeAt(i); if (_rows.isEmpty) _rows.add(_Entry()); }),
            icon: const Icon(Icons.close, size: 19, color: AppColors.faint),
          ),
        ]),
        if (sugg.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(top: 4),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: Column(children: [
              for (final p in sugg)
                InkWell(
                  onTap: () => _pick(r, p),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                    child: Row(children: [
                      Expanded(child: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
                      Text(money(p.sellPrice), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                    ]),
                  ),
                ),
            ]),
          ),
        if (picked.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              '${tr('Qoldiq')}: ${qtyStr(picked.first.stock)} → ${qtyStr(picked.first.stock + (double.tryParse(r.qtyC.text.replaceAll(',', '.')) ?? 0))}',
              style: const TextStyle(fontSize: 12, color: AppColors.ok, fontWeight: FontWeight.w600),
            ),
          ),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: _numField(r.qtyC, tr('Miqdor'), decimal: true)),
          const SizedBox(width: 8),
          Expanded(child: _numField(r.costC, tr('Kelish narxi'))),
          const SizedBox(width: 8),
          Expanded(child: _numField(r.sellC, tr('Sotish narxi'))),
        ]),
        if (isNew) ...[
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            value: r.categoryId,
            decoration: InputDecoration(labelText: tr('Kategoriya (yangi mahsulot)')),
            items: [
              DropdownMenuItem(value: null, child: Text(tr('Kategoriyasiz'))),
              for (final c in _cats) DropdownMenuItem(value: c.id, child: Text(c.name)),
            ],
            onChanged: (v) => setState(() => r.categoryId = v),
          ),
        ],
      ]),
    );
  }

  Widget _numField(TextEditingController c, String label, {bool decimal = false}) {
    return TextField(
      controller: c,
      keyboardType: TextInputType.numberWithOptions(decimal: decimal),
      decoration: InputDecoration(labelText: label),
      onChanged: (_) => setState(() {}),
    );
  }
}
