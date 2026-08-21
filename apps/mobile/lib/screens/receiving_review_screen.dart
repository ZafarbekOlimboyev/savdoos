import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../theme.dart';
import 'receiving_success_screen.dart';

/// Qabulni tekshirish — AI natijasi taklif, egа tasdiqlaydi/tahrirlaydi.
/// Diqqat talab qiladigan (topilmagan) tepada, mos kelganlar pastda ixcham.
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

  int get _ready => _lines.where((l) => l.productId != null).length;
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
    if (sel != null) setState(() { line.productId = sel.id; line.name = sel.name; });
  }

  Future<void> _confirm() async {
    final unmatched = _lines.where((l) => l.productId == null).length;
    if (unmatched > 0) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$unmatched ta mahsulot tanlanmagan')));
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Omborga qo‘shilsinmi?'),
        content: Text('${_lines.length} xil mahsulot\nJami ${qtyStr(_totalQty)} birlik', style: const TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Bekor')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Qo‘shish')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final items = _lines.map((l) => ReviewItem(
            productId: l.productId!, name: l.name!, qty: l.qty, unitCost: l.unitCost, unit: l.unit, aiName: l.aiName)).toList();
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
    final unmatched = _lines.where((l) => l.productId == null).toList();
    final matched = _lines.where((l) => l.productId != null).toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Tekshirish'),
        actions: [
          if (widget.source == 'demo')
            Container(
              margin: const EdgeInsets.only(right: 12),
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(color: AppColors.warnSoft, borderRadius: BorderRadius.circular(8)),
              child: const Text('DEMO', style: TextStyle(color: AppColors.warn, fontSize: 11, fontWeight: FontWeight.w700)),
            ),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            children: [
              _summaryBar(unmatched.length),
              if (unmatched.isNotEmpty) ...[
                const SizedBox(height: 20),
                _sectionHeader(Icons.warning_amber_rounded, AppColors.warn, 'Diqqat talab qiladi', unmatched.length),
                const SizedBox(height: 12),
                ...unmatched.map(_unmatchedCard),
              ],
              if (matched.isNotEmpty) ...[
                const SizedBox(height: 20),
                _sectionHeader(Icons.check_circle, AppColors.ok, 'Mos keldi', matched.length),
                const SizedBox(height: 12),
                ...matched.map(_matchedRow),
              ],
            ],
          ),
        ),
        _bottomBar(),
      ]),
    );
  }

  Widget _summaryBar(int needCheck) {
    Widget cell(String v, String l, Color c) => Expanded(
          child: Column(children: [
            Text(v, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: c)),
            const SizedBox(height: 2),
            Text(l, style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        );
    const div = SizedBox(height: 34, child: VerticalDivider(color: AppColors.border, width: 1));
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 16),
      decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.border)),
      child: Row(children: [
        cell('${_lines.length}', 'mahsulot', AppColors.text),
        div,
        cell('$needCheck', 'tekshirish', needCheck > 0 ? AppColors.warn : AppColors.text),
        div,
        cell(qtyStr(_totalQty), 'birlik', AppColors.text),
      ]),
    );
  }

  Widget _sectionHeader(IconData ic, Color c, String title, int n) => Row(children: [
        Icon(ic, size: 17, color: c),
        const SizedBox(width: 8),
        Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(7)),
          child: Text('$n', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
        ),
      ]);

  Widget _unmatchedCard(_Line l) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.warnBorder, width: 1.5)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 15, 12, 0),
            child: Row(children: [
              const Icon(Icons.help_outline, size: 17, color: AppColors.warn),
              const SizedBox(width: 8),
              const Expanded(child: Text('Mahsulot topilmadi', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
              IconButton(
                onPressed: () => setState(() => _lines.remove(l)),
                icon: const Icon(Icons.close, size: 18, color: AppColors.faint),
                visualDensity: VisualDensity.compact,
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
              decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(9)),
              child: Row(children: [
                const Icon(Icons.document_scanner_outlined, size: 14, color: AppColors.muted),
                const SizedBox(width: 7),
                const Text('AI o‘qidi:', style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                const SizedBox(width: 5),
                Expanded(child: Text(l.aiName, style: const TextStyle(fontSize: 12.5, color: AppColors.text3, fontStyle: FontStyle.italic))),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _products == null ? null : () => _pickProduct(l),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.accentStrong,
                  side: const BorderSide(color: AppColors.accentBorder),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  backgroundColor: AppColors.accentSoft,
                ),
                icon: const Icon(Icons.search, size: 18),
                label: const Text('Mahsulotni tanlang', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: const BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
            child: Row(children: [
              const Text('Miqdor', style: TextStyle(fontSize: 13, color: AppColors.text3)),
              const Spacer(),
              _QtyStepper(qty: l.qty, unit: l.unit, big: true, onChange: (v) => setState(() => l.qty = v)),
            ]),
          ),
        ]),
      );

  Widget _matchedRow(_Line l) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
        child: Row(children: [
          Container(
            width: 30, height: 30,
            decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(9)),
            child: const Icon(Icons.check, size: 16, color: AppColors.ok),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              GestureDetector(
                onTap: _products == null ? null : () => _pickProduct(l),
                child: Text(l.name!, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
              ),
              const SizedBox(height: 2),
              Text('AI: ${l.aiName}', style: const TextStyle(fontSize: 11.5, color: AppColors.muted, fontStyle: FontStyle.italic)),
            ]),
          ),
          const SizedBox(width: 8),
          _QtyStepper(qty: l.qty, unit: l.unit, big: false, onChange: (v) => setState(() => l.qty = v)),
        ]),
      );

  Widget _bottomBar() => Container(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
        decoration: const BoxDecoration(color: AppColors.card, border: Border(top: BorderSide(color: AppColors.border))),
        child: SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: (_busy || _lines.isEmpty) ? null : _confirm,
            icon: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.check_circle, size: 21),
            label: Text(_busy ? 'Qo‘shilyapti...' : 'Omborga qo‘shish · tayyor $_ready/${_lines.length}'),
          ),
        ),
      );
}

class _Line {
  final String aiName, unit;
  double qty, unitCost;
  String? productId, name;
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
  final bool big;
  final void Function(double) onChange;
  const _QtyStepper({required this.qty, required this.unit, required this.big, required this.onChange});

  @override
  Widget build(BuildContext context) {
    final s = big ? 44.0 : 34.0;
    final r = big ? 12.0 : 9.0;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      _btn(Icons.remove, s, r, AppColors.surface, AppColors.text3, () => onChange(qty > 1 ? qty - 1 : qty)),
      GestureDetector(
        onTap: () async {
          final v = await _editDialog(context, qty);
          if (v != null) onChange(v);
        },
        child: Container(
          constraints: BoxConstraints(minWidth: big ? 60 : 48),
          height: s,
          margin: const EdgeInsets.symmetric(horizontal: 8),
          alignment: Alignment.center,
          decoration: BoxDecoration(color: AppColors.bg, borderRadius: BorderRadius.circular(r), border: Border.all(color: AppColors.border)),
          child: Text(qtyStr(qty), style: TextStyle(fontSize: big ? 18 : 15, fontWeight: FontWeight.w800)),
        ),
      ),
      _btn(Icons.add, s, r, AppColors.accent, Colors.white, () => onChange(qty + 1)),
    ]);
  }

  Widget _btn(IconData ic, double s, double r, Color bg, Color fg, VoidCallback f) => GestureDetector(
        onTap: f,
        child: Container(width: s, height: s, decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(r)), child: Icon(ic, size: big ? 22 : 17, color: fg)),
      );

  Future<double?> _editDialog(BuildContext context, double cur) {
    final ctl = TextEditingController(text: qtyStr(cur));
    return showDialog<double>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Miqdor'),
        content: TextField(controller: ctl, keyboardType: const TextInputType.numberWithOptions(decimal: true), autofocus: true),
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
            child: TextField(
              autofocus: true,
              onChanged: (v) => setState(() => _q = v),
              decoration: const InputDecoration(hintText: 'Mahsulot qidirish...', prefixIcon: Icon(Icons.search, color: AppColors.muted)),
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: list.length,
              itemBuilder: (context, i) => ListTile(title: Text(list[i].name), onTap: () => Navigator.pop(context, list[i])),
            ),
          ),
        ]),
      ),
    );
  }
}
