import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'barcode_scan_screen.dart';
import 'receiving_success_screen.dart';

/// Qabulni tekshirish: AI natijasini tahrirlash, yetkazib beruvchi + naqd/qarz,
/// topilmagan tovarni tanlash yoki yangi mahsulot sifatida yaratish.
class ReceivingReviewScreen extends StatefulWidget {
  final List<ScanItem> items;
  final String imageB64;
  final String source;
  const ReceivingReviewScreen({super.key, required this.items, required this.imageB64, required this.source});

  @override
  State<ReceivingReviewScreen> createState() => _ReceivingReviewScreenState();
}

class _ReceivingReviewScreenState extends State<ReceivingReviewScreen> {
  // Bitta savat = bitta uuid: qayta urinishda server dublikat kirim yaratmaydi
  final String _clientUuid = Api.newUuid();
  late List<_Line> _lines;
  List<ProductLite>? _products;
  List<SupplierRow>? _suppliers;
  List<CategoryLite> _cats = const [];
  SupplierRow? _supplier;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _lines = widget.items.map((s) => _Line(s)).toList();
    Api.products().then((p) => mounted ? setState(() => _products = p) : null).catchError((_) {});
    Api.suppliers().then((s) => mounted ? setState(() => _suppliers = s) : null).catchError((_) {});
    Api.catList().then((c) => mounted ? setState(() => _cats = c) : null).catchError((_) {});
  }

  int get _ready => _lines.where((l) => l.ready).length;
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
    if (sel != null) setState(() { line.productId = sel.id; line.name = sel.name; line.newName = null; line.newSellPrice = null; });
  }

  Future<void> _newProduct(_Line line) async {
    final nameCtl = TextEditingController(text: line.newName ?? line.aiName);
    final sellCtl = TextEditingController(text: line.newSellPrice != null ? line.newSellPrice!.toStringAsFixed(0) : '');
    final costCtl = TextEditingController(text: line.unitCost > 0 ? line.unitCost.toStringAsFixed(0) : '');
    final codeCtl = TextEditingController(text: line.newBarcode ?? '');
    final pluCtl = TextEditingController(text: line.newPlu ?? '');
    String unit = line.unit;
    String? catId = line.newCategoryId;
    // Kategoriya avto-taxmini (nom bo'yicha, do'kon katalogidan) — dialog ochilishidan
    // OLDIN olamiz, dropdown'da tayyor tanlangan holda ko'rinadi
    catId ??= (await Api.guessCategory(nameCtl.text.trim())).$1;
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dctx) => StatefulBuilder(builder: (dctx, setD) {
        Future<void> scanToField() async {
          final code = await Navigator.of(dctx).push<String>(
              MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
          if (code != null && code.isNotEmpty) setD(() => codeCtl.text = code);
        }
        return AlertDialog(
          backgroundColor: AppColors.card,
          title: Text(tr('Yangi mahsulot'), style: const TextStyle(fontSize: 17)),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: nameCtl, decoration: InputDecoration(labelText: tr('Nomi'))),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: TextField(controller: costCtl, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: tr('Kelish narxi')))),
                const SizedBox(width: 10),
                Expanded(child: TextField(controller: sellCtl, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: tr('Sotish narxi')))),
              ]),
              const SizedBox(height: 12),
              // Birlik: dona | kg
              Row(children: [
                for (final u in const ['dona', 'kg']) ...[
                  Expanded(child: GestureDetector(
                    onTap: () => setD(() => unit = u),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 9),
                      decoration: BoxDecoration(
                        color: unit == u ? AppColors.accentSoft : AppColors.surface,
                        borderRadius: BorderRadius.circular(9),
                        border: Border.all(color: unit == u ? AppColors.accent : AppColors.border),
                      ),
                      child: Center(child: Text(u == 'dona' ? tr('Dona') : tr('Kg (tarozi)'),
                          style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700,
                              color: unit == u ? AppColors.accentStrong : AppColors.muted))),
                    ),
                  )),
                  if (u == 'dona') const SizedBox(width: 8),
                ],
              ]),
              const SizedBox(height: 10),
              if (unit == 'dona')
                TextField(
                  controller: codeCtl,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: tr('Shtrix-kod (majburiy)'),
                    suffixIcon: IconButton(icon: Icon(Icons.qr_code_scanner, color: AppColors.accentStrong), onPressed: scanToField),
                  ),
                )
              else
                TextField(
                  controller: pluCtl,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(labelText: tr('Tarozi PLU kodi (majburiy)')),
                ),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                value: catId,
                dropdownColor: AppColors.card,
                decoration: InputDecoration(labelText: tr('Kategoriya')),
                items: [
                  DropdownMenuItem(value: null, child: Text(tr('Kategoriyasiz'))),
                  for (final c in _cats) DropdownMenuItem(value: c.id, child: Text(c.name)),
                ],
                onChanged: (v) => setD(() => catId = v),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dctx, false), child: Text(tr('Bekor'))),
            ElevatedButton(onPressed: () {
              // Majburiy kod tekshiruvi — kiritilmasa dialog yopilmaydi
              final bc = codeCtl.text.replaceAll(RegExp(r'\D'), '');
              final plu = pluCtl.text.replaceAll(RegExp(r'\D'), '');
              if (unit == 'dona' && bc.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Shtrix-kodni kiriting yoki skanerlang'))));
                return;
              }
              if (unit == 'kg' && plu.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Tarozi PLU kodini kiriting'))));
                return;
              }
              Navigator.pop(dctx, true);
            }, child: Text(tr('Qo‘shish'))),
          ],
        );
      }),
    );
    if (ok == true && nameCtl.text.trim().isNotEmpty) {
      setState(() {
        line.newName = nameCtl.text.trim();
        line.newSellPrice = double.tryParse(sellCtl.text.replaceAll(',', '.'));
        line.unitCost = double.tryParse(costCtl.text.replaceAll(',', '.')) ?? line.unitCost;
        line.unit = unit;
        line.newBarcode = unit == 'dona' ? codeCtl.text.replaceAll(RegExp(r'\D'), '') : null;
        line.newPlu = unit == 'kg' ? pluCtl.text.replaceAll(RegExp(r'\D'), '') : null;
        line.newCategoryId = catId;
        line.productId = null;
        line.name = null;
      });
    }
  }

  Future<void> _pickSupplier() async {
    final sups = _suppliers;
    if (sups == null) return;
    final sel = await showModalBottomSheet<SupplierRow?>(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _SupplierPicker(suppliers: sups),
    );
    if (sel != null) setState(() => _supplier = sel.id.isEmpty ? null : sel);
  }

  Future<void> _confirm() async {
    final unready = _lines.where((l) => !l.ready).length;
    if (unready > 0) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$unready ${tr('ta mahsulot tanlanmagan')}')));
      return;
    }
    // YANGI mahsulotlarda kod majburiy: dona -> shtrix-kod, kg -> PLU.
    // Yetishmasa saqlanmaydi — birinchi muammoli qator dialogi ochiladi.
    final noCode = _lines.where((l) => l.codeMissing).toList();
    if (noCode.isNotEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('${noCode.length} ${tr('ta yangi mahsulotda shtrix-kod/PLU yo‘q — kiriting yoki skanerlang')}')));
      _newProduct(noCode.first);
      return;
    }
    // Ikki YANGI mahsulot bir xil yangi shtrix-kod/PLU bilan kelmasin — aks holda
    // serverda biri ikkinchisini ustidan yozib, bitta kod jimgina yo'qoladi.
    final newCodes = <String>[], newPlus = <String>[];
    for (final l in _lines.where((l) => l.isNewProduct)) {
      final bc = l.newBarcode;
      if (bc != null && bc.isNotEmpty) newCodes.add(bc);
      final plu = l.newPlu;
      if (plu != null && plu.isNotEmpty) newPlus.add(plu);
    }
    if (newCodes.toSet().length != newCodes.length) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(tr('Ikki yangi mahsulotda bir xil shtrix-kod — har biriga alohida kod bering'))));
      return;
    }
    if (newPlus.toSet().length != newPlus.length) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(tr('Ikki yangi mahsulotda bir xil PLU — har biriga alohida PLU bering'))));
      return;
    }
    final payment = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PaymentSheet(supplier: _supplier?.name ?? 'Qabul (mobil)', types: _lines.length, qty: _totalQty),
    );
    if (payment == null) return;
    setState(() => _busy = true);
    try {
      final items = _lines.map((l) => ReviewItem(
            productId: l.productId, newName: l.newName, newSellPrice: l.newSellPrice,
            newCategoryId: l.newCategoryId, newBarcode: l.newBarcode,
            newPlu: l.newPlu, newIsWeighted: l.isNewProduct ? l.unit == 'kg' : null,
            name: l.display, qty: l.qty, unitCost: l.unitCost, unit: l.unit, aiName: l.aiName)).toList();
      final res = await Api.commit(items, widget.imageB64,
          supplierId: _supplier?.id, payment: payment, clientUuid: _clientUuid);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ReceivingSuccessScreen(result: res)));
    } catch (e) {
      setState(() => _busy = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Xato: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final unmatched = _lines.where((l) => !l.ready).toList();
    final matched = _lines.where((l) => l.ready).toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Tekshirish')),
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
              _supplierRow(),
              const SizedBox(height: 12),
              _summaryBar(unmatched.length),
              if (unmatched.isNotEmpty) ...[
                const SizedBox(height: 20),
                _sectionHeader(Icons.warning_amber_rounded, AppColors.warn, tr('Diqqat talab qiladi'), unmatched.length),
                const SizedBox(height: 12),
                ...unmatched.map(_unmatchedCard),
              ],
              if (matched.isNotEmpty) ...[
                const SizedBox(height: 20),
                _sectionHeader(Icons.check_circle, AppColors.ok, tr('Tayyor'), matched.length),
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

  Widget _supplierRow() => GestureDetector(
        onTap: _suppliers == null ? null : _pickSupplier,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Icon(Icons.local_shipping_outlined, size: 19, color: AppColors.accentStrong),
            const SizedBox(width: 11),
            Text(tr('Yetkazib beruvchi'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
            const Spacer(),
            Text(_supplier?.name ?? 'Qabul (mobil)', style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(width: 6),
            Icon(Icons.expand_more, size: 18, color: AppColors.muted),
          ]),
        ),
      );

  Widget _summaryBar(int needCheck) {
    Widget cell(String v, String l, Color c) => Expanded(
          child: Column(children: [
            Text(v, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: c)),
            const SizedBox(height: 2),
            Text(l, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        );
    final div = SizedBox(height: 34, child: VerticalDivider(color: AppColors.border, width: 1));
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 16),
      decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.border)),
      child: Row(children: [
        cell('${_lines.length}', tr('mahsulot'), AppColors.text),
        div,
        cell('$needCheck', tr('tekshirish'), needCheck > 0 ? AppColors.warn : AppColors.text),
        div,
        cell(qtyStr(_totalQty), tr('birlik'), AppColors.text),
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
              Expanded(child: Text(tr('Mahsulot topilmadi'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
              IconButton(onPressed: () => setState(() => _lines.remove(l)), icon: Icon(Icons.close, size: 18, color: AppColors.faint), visualDensity: VisualDensity.compact),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
              decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(9)),
              child: Row(children: [
                Icon(Icons.document_scanner_outlined, size: 14, color: AppColors.muted),
                const SizedBox(width: 7),
                Text(tr('AI o‘qidi:'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                const SizedBox(width: 5),
                Expanded(child: Text(l.aiName, style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontStyle: FontStyle.italic))),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _products == null ? null : () => _pickProduct(l),
                style: OutlinedButton.styleFrom(foregroundColor: AppColors.accentStrong, side: BorderSide(color: AppColors.accentBorder), padding: const EdgeInsets.symmetric(vertical: 12), backgroundColor: AppColors.accentSoft),
                icon: const Icon(Icons.search, size: 18),
                label: Text(tr('Mahsulotni tanlang'), style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
            ),
          ),
          Center(
            child: TextButton.icon(
              onPressed: () => _newProduct(l),
              icon: Icon(Icons.add_circle_outline, size: 16, color: AppColors.muted),
              label: Text(tr('yoki yangi mahsulot yaratish'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
            child: Row(children: [
              Text(tr('Miqdor'), style: TextStyle(fontSize: 13, color: AppColors.text3)),
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
          Container(width: 30, height: 30, decoration: BoxDecoration(color: l.newName != null ? AppColors.accentSoft : AppColors.okSoft, borderRadius: BorderRadius.circular(9)), child: Icon(l.newName != null ? Icons.fiber_new : Icons.check, size: 16, color: l.newName != null ? AppColors.accentStrong : AppColors.ok)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              GestureDetector(onTap: l.newName != null ? () => _newProduct(l) : (_products == null ? null : () => _pickProduct(l)), child: Text(l.display, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600))),
              const SizedBox(height: 2),
              l.codeMissing
                  // Kod yetishmayapti — bosganda dialog ochilib kiritiladi/skanerlaydi
                  ? GestureDetector(
                      onTap: () => _newProduct(l),
                      child: Text(
                        l.unit == 'kg' ? '⚠ ${tr('PLU kiriting')}' : '⚠ ${tr('Shtrix-kod kiriting')}',
                        style: const TextStyle(fontSize: 11.5, color: AppColors.warn, fontWeight: FontWeight.w700),
                      ),
                    )
                  : Text(l.newName != null ? tr('yangi mahsulot') : 'AI: ${l.aiName}', style: TextStyle(fontSize: 11.5, color: AppColors.muted, fontStyle: FontStyle.italic)),
            ]),
          ),
          const SizedBox(width: 8),
          _QtyStepper(qty: l.qty, unit: l.unit, big: false, onChange: (v) => setState(() => l.qty = v)),
        ]),
      );

  Widget _bottomBar() => Container(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.of(context).padding.bottom),
        decoration: BoxDecoration(color: AppColors.card, border: Border(top: BorderSide(color: AppColors.border))),
        child: SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: (_busy || _lines.isEmpty) ? null : _confirm,
            icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.check_circle, size: 21),
            label: Text(_busy ? tr('Qo‘shilyapti...') : '${tr('Omborga qo‘shish')} · ${tr('tayyor')} $_ready/${_lines.length}'),
          ),
        ),
      );
}

class _Line {
  final String aiName;
  String unit;                 // dona | kg (yangi mahsulotda o'zgartirish mumkin)
  double qty, unitCost;
  String? productId, name, newName;
  double? newSellPrice;
  String? newBarcode;          // yangi DONA mahsulot uchun majburiy
  String? newPlu;              // yangi KG mahsulot uchun majburiy
  String? newCategoryId;       // avto-taxmin / tanlangan
  _Line(ScanItem s)
      : aiName = s.aiName,
        unit = s.unit == 'kg' ? 'kg' : 'dona',
        qty = s.qty,
        unitCost = s.unitCost,
        productId = s.productId,
        name = s.matchedName;
  bool get ready => productId != null || newName != null;
  bool get isNewProduct => productId == null && newName != null;
  // Yangi mahsulotda kod yetishmayaptimi: dona -> barcode, kg -> PLU
  bool get codeMissing => isNewProduct &&
      (unit == 'kg' ? (newPlu == null || newPlu!.isEmpty) : (newBarcode == null || newBarcode!.isEmpty));
  String get display => name ?? newName ?? '';
}

class _PaymentSheet extends StatelessWidget {
  final String supplier;
  final int types;
  final double qty;
  const _PaymentSheet({required this.supplier, required this.types, required this.qty});

  @override
  Widget build(BuildContext context) {
    Widget opt(String code, String label, IconData ic, Color c, String sub) => GestureDetector(
          onTap: () => Navigator.pop(context, code),
          child: Container(
            margin: const EdgeInsets.only(bottom: 10),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(width: 46, height: 46, decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)), child: Icon(ic, color: c, size: 24)),
              const SizedBox(width: 14),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700)),
                Text(sub, style: TextStyle(fontSize: 12, color: AppColors.muted)),
              ])),
              Icon(Icons.chevron_right, color: AppColors.faint),
            ]),
          ),
        );
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
          const SizedBox(height: 16),
          Text(tr('Tovar qanday olindi?'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text('$supplier · $types xil · ${qtyStr(qty)} birlik', style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          const SizedBox(height: 16),
          opt('cash', tr('Naqd'), Icons.payments, AppColors.ok, tr('Darrov to‘landi')),
          opt('credit', tr('Qarzga'), Icons.account_balance_wallet, AppColors.warn, tr('Yetkazib beruvchiga qarz bo‘ldi')),
        ]),
      ),
    );
  }
}

class _SupplierPicker extends StatelessWidget {
  final List<SupplierRow> suppliers;
  const _SupplierPicker({required this.suppliers});
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.6,
      child: Column(children: [
        const SizedBox(height: 12),
        Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2))),
        Padding(padding: const EdgeInsets.all(16), child: Align(alignment: Alignment.centerLeft, child: Text(tr('Yetkazib beruvchi'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)))),
        Expanded(
          child: ListView(children: [
            ListTile(leading: Icon(Icons.inventory_2, color: AppColors.muted), title: const Text('Qabul (mobil) — standart'), onTap: () => Navigator.pop(context, SupplierRow(id: '', name: 'Qabul (mobil)', phone: null, balance: 0))),
            ...suppliers.map((s) => ListTile(
                  leading: Icon(Icons.local_shipping_outlined, color: AppColors.accentStrong),
                  title: Text(s.name),
                  subtitle: s.balance > 0 ? Text('${tr('Qarz')}: ${money(s.balance)}', style: const TextStyle(color: AppColors.danger, fontSize: 12)) : null,
                  onTap: () => Navigator.pop(context, s),
                )),
          ]),
        ),
      ]),
    );
  }
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
        title: Text(tr('Miqdor')),
        content: TextField(controller: ctl, keyboardType: const TextInputType.numberWithOptions(decimal: true), autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Bekor'))),
          ElevatedButton(
            onPressed: () {
              final v = double.tryParse(ctl.text.replaceAll(',', '.'));
              Navigator.pop(context, (v != null && v > 0) ? v : null);
            },
            child: Text(tr('Saqlash')),
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
  late String _q = widget.query;              // AI nomi bilan boshlanadi (ilgari e'tiborsiz edi)
  late final _qC = TextEditingController(text: widget.query);
  @override
  void dispose() { _qC.dispose(); super.dispose(); }
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
            child: TextField(autofocus: true, controller: _qC, onChanged: (v) => setState(() => _q = v), decoration: InputDecoration(hintText: tr('Mahsulot qidirish...'), prefixIcon: Icon(Icons.search, color: AppColors.muted))),
          ),
          Expanded(child: ListView.builder(itemCount: list.length, itemBuilder: (context, i) => ListTile(title: Text(list[i].name), onTap: () => Navigator.pop(context, list[i])))),
        ]),
      ),
    );
  }
}
