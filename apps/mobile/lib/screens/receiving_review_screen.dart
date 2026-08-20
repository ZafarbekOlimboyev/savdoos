import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../theme.dart';
import 'receiving_success_screen.dart';

/// Qabul qilishni tekshirish: AI natijasi taklif sifatida, foydalanuvchi tasdiqlaydi/tahrirlaydi.
class ReceivingReviewScreen extends StatefulWidget {
  final List<ScanItem> items;
  final String imageB64;
  final String source;
  const ReceivingReviewScreen({super.key, required this.items, required this.imageB64, required this.source});

  @override
  State<ReceivingReviewScreen> createState() => _ReceivingReviewScreenState();
}

class _ReceivingReviewScreenState extends State<ReceivingReviewScreen> {
  late List<_Line> _lines;
  List<ProductLite>? _products;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _lines = widget.items.map((s) => _Line(s)).toList();
    Api.products().then((p) => mounted ? setState(() => _products = p) : null).catchError((_) {});
  }

  int get _readyCount => _lines.where((l) => l.productId != null).length;
  double get _totalQty => _lines.fold(0.0, (a, l) => a + l.qty);

  Future<void> _pickProduct(_Line line) async {
    final prods = _products;
    if (prods == null) return;
    final sel = await showModalBottomSheet<ProductLite>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _ProductPicker(products: prods, query: line.aiName),
    );
    if (sel != null) {
      setState(() { line.productId = sel.id; line.name = sel.name; });
    }
  }

  Future<void> _confirm() async {
    final unmatched = _lines.where((l) => l.productId == null).length;
    if (unmatched > 0) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$unmatched ta mahsulot tanlanmagan')));
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Omborga qo‘shilsinmi?'),
        content: Text('${_lines.length} xil mahsulot\nJami ${qtyStr(_totalQty)} birlik',
            style: const TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Bekor')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Omborga qo‘shish')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final items = _lines.map((l) => ReviewItem(
            productId: l.productId!, name: l.name!, qty: l.qty, unitCost: l.unitCost, unit: l.unit, aiName: l.aiName,
          )).toList();
      final res = await Api.commit(items, widget.imageB64);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ReceivingSuccessScreen(result: res)));
    } catch (e) {
      setState(() => _busy = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Qabul qilingan mahsulotlar')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Row(children: [
              const Expanded(child: Text('Omborga qo‘shishdan oldin tekshiring',
                  style: TextStyle(color: AppColors.muted, fontSize: 13))),
              if (widget.source == 'demo')
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(color: AppColors.warnSoft, borderRadius: BorderRadius.circular(8)),
                  child: const Text('DEMO', style: TextStyle(color: AppColors.warn, fontSize: 11, fontWeight: FontWeight.w700)),
                ),
            ]),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              itemCount: _lines.length,
              itemBuilder: (context, i) => _card(_lines[i]),
            ),
          ),
          _bottomBar(),
        ],
      ),
    );
  }

  Widget _card(_Line l) {
    final matched = l.productId != null;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: matched ? AppColors.border : AppColors.warnBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(matched ? Icons.check_circle : Icons.warning_amber_rounded,
                size: 18, color: matched ? AppColors.ok : AppColors.warn),
            const SizedBox(width: 8),
            Expanded(
              child: Text(matched ? l.name! : 'Mahsulot aniq topilmadi',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700,
                      color: matched ? AppColors.text : AppColors.warn)),
            ),
            IconButton(
              onPressed: () => setState(() => _lines.remove(l)),
              icon: const Icon(Icons.close, size: 18, color: AppColors.faint),
              visualDensity: VisualDensity.compact,
            ),
          ]),
          const SizedBox(height: 4),
          Text('AI o‘qidi: ${l.aiName}', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          const SizedBox(height: 12),
          Row(children: [
            // Miqdor
            _QtyStepper(qty: l.qty, unit: l.unit, onChange: (v) => setState(() => l.qty = v)),
            const Spacer(),
            OutlinedButton.icon(
              onPressed: _products == null ? null : () => _pickProduct(l),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.accentStrong,
                side: const BorderSide(color: AppColors.accentBorder),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              ),
              icon: const Icon(Icons.search, size: 16),
              label: Text(matched ? 'Almashtirish' : 'Tanlash', style: const TextStyle(fontSize: 13)),
            ),
          ]),
        ],
      ),
    );
  }

  Widget _bottomBar() {
    return Container(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
      decoration: const BoxDecoration(
        color: AppColors.card,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SizedBox(
        width: double.infinity,
        child: ElevatedButton.icon(
          onPressed: (_busy || _lines.isEmpty) ? null : _confirm,
          icon: _busy
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.check, size: 20),
          label: Text(_busy ? 'Qo‘shilyapti...' : 'Hammasi to‘g‘ri — Omborga qo‘shish ($_readyCount)'),
        ),
      ),
    );
  }
}

class _Line {
  final String aiName;
  final String unit;
  double qty;
  double unitCost;
  String? productId;
  String? name;
  _Line(ScanItem s)
      : aiName = s.aiName,
        unit = s.unit,
        qty = s.qty,
        unitCost = s.unitCost,
        productId = s.productId,
        name = s.matchedName;
}

class _QtyStepper extends StatelessWidget {
  final double qty;
  final String unit;
  final void Function(double) onChange;
  const _QtyStepper({required this.qty, required this.unit, required this.onChange});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        _btn(Icons.remove, () => onChange(qty > 1 ? qty - 1 : qty)),
        GestureDetector(
          onTap: () async {
            final v = await _editDialog(context, qty);
            if (v != null) onChange(v);
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text('${qtyStr(qty)} $unit',
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          ),
        ),
        _btn(Icons.add, () => onChange(qty + 1)),
      ]),
    );
  }

  Widget _btn(IconData ic, VoidCallback f) => InkWell(
        onTap: f,
        child: Padding(padding: const EdgeInsets.all(8), child: Icon(ic, size: 18, color: AppColors.text3)),
      );

  Future<double?> _editDialog(BuildContext context, double cur) {
    final ctl = TextEditingController(text: qtyStr(cur));
    return showDialog<double>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Miqdor'),
        content: TextField(
          controller: ctl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          autofocus: true,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Bekor')),
          ElevatedButton(
            onPressed: () {
              final v = double.tryParse(ctl.text.replaceAll(',', '.'));
              Navigator.pop(context, (v != null && v > 0) ? v : null);
            },
            child: const Text('Saqlash'),
          ),
        ],
      ),
    );
  }
}

class _ProductPicker extends StatefulWidget {
  final List<ProductLite> products;
  final String query;
  const _ProductPicker({required this.products, required this.query});
  @override
  State<_ProductPicker> createState() => _ProductPickerState();
}

class _ProductPickerState extends State<_ProductPicker> {
  String _q = '';
  @override
  void initState() {
    super.initState();
    _q = '';
  }

  @override
  Widget build(BuildContext context) {
    final ql = _q.toLowerCase();
    final list = _q.isEmpty
        ? widget.products
        : widget.products.where((p) => p.name.toLowerCase().contains(ql)).toList();
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.7,
        child: Column(children: [
          const SizedBox(height: 12),
          Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2))),
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              autofocus: true,
              onChanged: (v) => setState(() => _q = v),
              decoration: InputDecoration(
                hintText: 'Mahsulot qidirish...',
                prefixIcon: const Icon(Icons.search, color: AppColors.muted),
              ),
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: list.length,
              itemBuilder: (context, i) => ListTile(
                title: Text(list[i].name),
                onTap: () => Navigator.pop(context, list[i]),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
