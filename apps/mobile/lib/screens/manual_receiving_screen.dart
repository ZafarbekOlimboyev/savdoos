import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'receiving_item_editor_screen.dart';

/// Qo'lda kirim (mobil):
/// - Tepada yetkazib beruvchi tanlanadi.
/// - "Mahsulot qo'shish" bosilsa ALOHIDA oyna ochiladi (skaner/qidiruv/narxlar),
///   saqlangach orqaga qaytadi va ro'yxatda faqat NOM ko'rinadi.
/// - Pastda to'lov turi + jami + "Kirimni saqlash" (bir marta commit).
class ManualReceivingScreen extends StatefulWidget {
  const ManualReceivingScreen({super.key});
  @override
  State<ManualReceivingScreen> createState() => _ManualReceivingScreenState();
}

class _ManualReceivingScreenState extends State<ManualReceivingScreen> {
  // Bitta savat = bitta uuid: qayta urinishda server dublikat kirim yaratmaydi.
  // Ekran bir marta yaratilganda tayyorlanadi, qayta urinishda AYLANMAYDI.
  final String _clientUuid = Api.newUuid();
  List<InvItem> _catalog = [];
  List<CategoryLite> _cats = [];
  List<SupplierRow> _suppliers = [];
  String? _supplierId;
  final List<ReviewItem> _items = [];
  String _payment = 'cash';
  bool _busy = false;
  bool _loading = true;
  String _status = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      // Kichik ma'lumotlar (kategoriya + yetkazuvchi) — yengil, darrov
      final cats = await Api.catList();
      final sups = await Api.suppliers();
      if (mounted) setState(() { _cats = cats; _suppliers = sups; });
      // Katalog — keshdan (o'zgarmagan bo'lsa yuklamaydi). Birinchi marta biroz kutiladi.
      final cat = await Api.cachedCatalog(
        onStatus: (s) { if (mounted) setState(() => _status = s); });
      if (!mounted) return;
      setState(() { _catalog = cat; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  double get _total => _items.fold(0.0, (t, i) => t + i.qty * i.unitCost);

  Future<void> _addItem() async {
    final item = await Navigator.of(context).push<ReviewItem>(MaterialPageRoute(
      builder: (_) => ReceivingItemEditorScreen(catalog: _catalog, cats: _cats),
    ));
    if (item != null) setState(() => _items.add(item));
  }

  Future<void> _save() async {
    if (_items.isEmpty) { _snack(tr('Avval mahsulot qo‘shing')); return; }
    setState(() => _busy = true);
    try {
      final res = await Api.commit(_items, null,
          supplierId: _supplierId, payment: _payment, source: 'manual', clientUuid: _clientUuid);
      if (!mounted) return;
      Api.invalidateCatalog(); // yangi mahsulot/narx/qoldiq — kesh yangilanadi
      final n = res['total_types'] ?? _items.length;
      _snack('${tr('Qabul qilindi')}: $n');
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
    if (_loading) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Qo‘lda kirim'))),
        body: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
          const CircularProgressIndicator(),
          if (_status.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(_status, style: TextStyle(color: AppColors.muted, fontSize: 13)),
          ],
        ])),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(tr('Qo‘lda kirim'))),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              children: [
                // Yetkazib beruvchi (eng tepada)
                Text(tr('Yetkazib beruvchi'), style: _lbl),
                const SizedBox(height: 6),
                DropdownButtonFormField<String>(
                  value: _supplierId,
                  isExpanded: true,
                  dropdownColor: AppColors.card, // ochiq menyu shaffof bo'lmasin
                  decoration: const InputDecoration(),
                  items: [
                    DropdownMenuItem(value: null, child: Text(tr('Tanlanmagan'))),
                    for (final s in _suppliers) DropdownMenuItem(value: s.id, child: Text(s.name)),
                  ],
                  onChanged: (v) => setState(() => _supplierId = v),
                ),
                const SizedBox(height: 20),

                // Mahsulotlar ro'yxati (faqat nom)
                Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  Text(tr('Mahsulotlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                  Text('${_items.length}', style: TextStyle(fontSize: 14, color: AppColors.muted)),
                ]),
                const SizedBox(height: 8),
                if (_items.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    child: Center(child: Text(tr('Hali mahsulot qo‘shilmagan'),
                        style: TextStyle(color: AppColors.muted))),
                  ),
                for (var i = 0; i < _items.length; i++) _itemRow(i),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _addItem,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.accentStrong,
                    side: BorderSide(color: AppColors.accentStrong, width: 1.3),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                  ),
                  icon: const Icon(Icons.add, size: 20),
                  label: Text(tr('Mahsulot qo‘shish')),
                ),
              ],
            ),
          ),
          // Pastki panel: to'lov + jami + saqlash
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            decoration: BoxDecoration(
              color: AppColors.card,
              border: Border(top: BorderSide(color: AppColors.border)),
            ),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Expanded(child: _payBtn('cash', tr('To‘landi'))),
                const SizedBox(width: 8),
                Expanded(child: _payBtn('credit', tr('Qarzga'))),
                const SizedBox(width: 14),
                Text(money(_total), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              ]),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: (_busy || _items.isEmpty) ? null : _save,
                  style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
                  child: Text(_busy ? '...' : tr('Kirimni saqlash')),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _itemRow(int i) {
    final it = _items[i];
    final sub = money(it.qty * it.unitCost);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(children: [
        // Faqat nom (asosiy), ostida kichik miqdor/summa
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(it.name, maxLines: 2, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 3),
            Text('${qtyStr(it.qty)} × ${money(it.unitCost)} = $sub',
                style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ]),
        ),
        if (it.productId == null)
          Container(
            margin: const EdgeInsets.only(right: 6),
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
            decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(6)),
            child: Text(tr('Yangi'), style: const TextStyle(fontSize: 10.5, color: AppColors.ok, fontWeight: FontWeight.w700)),
          ),
        IconButton(
          onPressed: () => setState(() => _items.removeAt(i)),
          icon: Icon(Icons.close, size: 19, color: AppColors.faint),
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
        ),
      ]),
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

  TextStyle get _lbl => TextStyle(fontSize: 12.5, color: AppColors.muted, fontWeight: FontWeight.w600);
}
