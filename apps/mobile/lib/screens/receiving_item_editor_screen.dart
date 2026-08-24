import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'barcode_scan_screen.dart';

/// Bitta mahsulotni kiritish oynasi (qo'lda kirim uchun).
/// Oqim: shtrix-kod skaner → bazada bor bo'lsa avto-to'ladi; yo'q bo'lsa kod
/// saqlanadi va yangi mahsulot sifatida (nom+kategoriya+narxlar) kiritiladi.
/// Yoki nom bo'yicha qidirib mavjud mahsulotni tanlash mumkin.
/// "Saqlash" — ReviewItem'ni Navigator.pop bilan qaytaradi.
class ReceivingItemEditorScreen extends StatefulWidget {
  final List<InvItem> catalog;      // qidiruv-avto to'ldirish uchun (arxiv ham)
  final List<CategoryLite> cats;
  const ReceivingItemEditorScreen({super.key, required this.catalog, required this.cats});
  @override
  State<ReceivingItemEditorScreen> createState() => _ReceivingItemEditorScreenState();
}

class _ReceivingItemEditorScreenState extends State<ReceivingItemEditorScreen> {
  final _nameC = TextEditingController();
  final _qtyC = TextEditingController();
  final _costC = TextEditingController();
  final _sellC = TextEditingController();
  String? _productId;      // mavjud mahsulot (tanlangan)
  String? _categoryId;     // yangi mahsulot kategoriyasi
  String? _barcode;        // skanerlangan yangi kod (bazada yo'q edi)
  bool _open = false;      // nom takliflari ochiqmi
  bool _scanning = false;

  @override
  void dispose() {
    _nameC.dispose(); _qtyC.dispose(); _costC.dispose(); _sellC.dispose();
    super.dispose();
  }

  void _fillFrom(InvItem p, {String? keepBarcode}) {
    setState(() {
      _productId = p.id;
      _barcode = keepBarcode;   // mavjud mahsulotga skaner kelmasa null
      _nameC.text = p.name;
      _costC.text = p.buyPrice > 0 ? p.buyPrice.round().toString() : '';
      _sellC.text = p.sellPrice > 0 ? p.sellPrice.round().toString() : '';
      _open = false;
    });
  }

  Future<void> _scan() async {
    final code = await Navigator.of(context).push<String>(
        MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
    if (code == null || code.isEmpty || !mounted) return;
    setState(() => _scanning = true);
    try {
      // Avval mahalliy katalogdan (tez), keyin serverdan aniqlash
      InvItem? hit;
      for (final p in widget.catalog) {
        if (p.id == code) { hit = p; break; }
      }
      hit ??= await Api.productByBarcode(code);
      if (!mounted) return;
      if (hit != null) {
        _fillFrom(hit);
        _snack(tr('Topildi') + ': ' + hit.name);
      } else {
        // Bazada yo'q — yangi mahsulot; kodni saqlab qo'yamiz (saqlashda biriktiriladi)
        setState(() {
          _productId = null;
          _barcode = code;
          _open = false;
        });
        _snack(tr('Yangi kod — mahsulot nomini kiriting'));
      }
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  void _save() {
    final name = _nameC.text.trim();
    final qty = double.tryParse(_qtyC.text.replaceAll(',', '.')) ?? 0;
    if (name.isEmpty) { _snack(tr('Mahsulot nomini kiriting')); return; }
    if (qty <= 0) { _snack(tr('Miqdorni kiriting')); return; }
    final cost = double.tryParse(_costC.text) ?? 0;
    final sell = double.tryParse(_sellC.text);
    final item = ReviewItem(
      productId: _productId,
      newName: _productId == null ? name : null,
      newSellPrice: sell,
      newCategoryId: _productId == null ? _categoryId : null,
      newBarcode: _barcode,
      name: name, qty: qty, unitCost: cost, unit: 'dona',
    );
    Navigator.of(context).pop(item);
  }

  void _snack(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    final q = _nameC.text.trim().toLowerCase();
    final sugg = (_open && _productId == null && q.length >= 2)
        ? widget.catalog.where((p) => p.name.toLowerCase().contains(q)).take(8).toList()
        : <InvItem>[];
    final isNew = _productId == null && _nameC.text.trim().isNotEmpty;
    final picked = _productId != null
        ? widget.catalog.where((p) => p.id == _productId).toList()
        : <InvItem>[];

    return Scaffold(
      appBar: AppBar(title: Text(tr('Mahsulot qo‘shish'))),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              children: [
                // Skaner tugmasi (eng tepada)
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _scanning ? null : _scan,
                    style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
                    icon: const Icon(Icons.qr_code_scanner, size: 22),
                    label: Text(_scanning ? tr('Qidirilmoqda…') : tr('Shtrix-kodni skanerlash')),
                  ),
                ),
                if (_barcode != null) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                    decoration: BoxDecoration(
                      color: _productId == null ? AppColors.okSoft : AppColors.accentSoft,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(children: [
                      Icon(Icons.qr_code, size: 16,
                          color: _productId == null ? AppColors.ok : AppColors.accentStrong),
                      const SizedBox(width: 8),
                      Expanded(child: Text(
                        (_productId == null ? tr('Yangi kod biriktiriladi') : tr('Kod')) + ': $_barcode',
                        style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                      )),
                    ]),
                  ),
                ],
                const SizedBox(height: 16),

                // Nom (qidiruv/yangi)
                Text(tr('Mahsulot nomi'), style: _lbl),
                const SizedBox(height: 6),
                TextField(
                  controller: _nameC,
                  decoration: InputDecoration(hintText: tr('Qidiring yoki yangi nom yozing')),
                  onChanged: (_) => setState(() { _productId = null; _open = true; }),
                  onTap: () => setState(() => _open = true),
                ),
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
                          onTap: () => _fillFrom(p),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                            child: Row(children: [
                              Expanded(child: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13.5))),
                              Text(money(p.sellPrice), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                            ]),
                          ),
                        ),
                    ]),
                  ),
                if (picked.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${tr('Qoldiq')}: ${qtyStr(picked.first.stock)}',
                      style: const TextStyle(fontSize: 12.5, color: AppColors.ok, fontWeight: FontWeight.w600),
                    ),
                  ),
                const SizedBox(height: 16),

                // Miqdor
                Text(tr('Miqdor'), style: _lbl),
                const SizedBox(height: 6),
                TextField(
                  controller: _qtyC,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(hintText: tr('Nechta keldi')),
                ),
                const SizedBox(height: 16),

                // Narxlar
                Row(children: [
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('Kelish narxi'), style: _lbl),
                    const SizedBox(height: 6),
                    TextField(controller: _costC, keyboardType: TextInputType.number,
                        decoration: const InputDecoration(hintText: '0')),
                  ])),
                  const SizedBox(width: 12),
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('Sotish narxi'), style: _lbl),
                    const SizedBox(height: 6),
                    TextField(controller: _sellC, keyboardType: TextInputType.number,
                        decoration: const InputDecoration(hintText: '0')),
                  ])),
                ]),

                // Kategoriya (faqat yangi mahsulotda)
                if (isNew) ...[
                  const SizedBox(height: 16),
                  Text(tr('Kategoriya (yangi mahsulot)'), style: _lbl),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<String>(
                    value: _categoryId,
                    decoration: const InputDecoration(),
                    items: [
                      DropdownMenuItem(value: null, child: Text(tr('Kategoriyasiz'))),
                      for (final c in widget.cats) DropdownMenuItem(value: c.id, child: Text(c.name)),
                    ],
                    onChanged: (v) => setState(() => _categoryId = v),
                  ),
                ],
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
            decoration: const BoxDecoration(
              color: AppColors.card,
              border: Border(top: BorderSide(color: AppColors.border)),
            ),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _save,
                style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
                icon: const Icon(Icons.check, size: 20),
                label: Text(tr('Saqlash va ro‘yxatga qo‘shish')),
              ),
            ),
          ),
        ]),
      ),
    );
  }

  static const _lbl = TextStyle(fontSize: 12.5, color: AppColors.muted, fontWeight: FontWeight.w600);
}
