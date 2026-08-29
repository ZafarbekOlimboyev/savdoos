import 'dart:async';

import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'barcode_scan_screen.dart';

/// Bitta mahsulotni kiritish oynasi (qo'lda kirim uchun).
/// Oqim: shtrix-kod skaner → bazada bor bo'lsa avto-to'ladi; yo'q bo'lsa kod
/// saqlanadi va yangi mahsulot sifatida kiritiladi.
///
/// YANGI mahsulot qoidalari (Manager formasi bilan paritet):
///  - Birlik: dona YOKI kg.
///  - dona  → shtrix-kod MAJBURIY (skaner yoki qo'lda) — kiritilmasa saqlanmaydi.
///  - kg    → tarozi PLU kodi MAJBURIY (mahsulot tarozida shu kod bilan sotiladi).
///  - Kategoriya nomga qarab AVTO taxmin qilinadi (o'zgartirish mumkin).
///  - Min qoldiq (ixtiyoriy) — kam-qoldiq ogohlantirishi uchun.
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
  final _barcodeC = TextEditingController();  // yangi mahsulot shtrix-kodi (dona)
  final _pluC = TextEditingController();      // yangi mahsulot PLU (kg)
  final _minC = TextEditingController();      // min qoldiq (ixtiyoriy)
  String? _productId;      // mavjud mahsulot (tanlangan)
  double? _liveStock;      // serverdan JONLI qoldiq
  String? _categoryId;     // yangi mahsulot kategoriyasi
  String _unit = 'dona';   // yangi mahsulot birligi: dona | kg
  bool _catFromGuess = false;   // kategoriya avto-taxmindan (foydalanuvchi tanlasa false)
  String? _guessName;           // taxmin qilingan kategoriya nomi (ko'rsatish uchun)
  Timer? _guessTimer;
  bool _open = false;      // nom takliflari ochiqmi
  bool _scanning = false;

  @override
  void dispose() {
    _guessTimer?.cancel();
    _nameC.dispose(); _qtyC.dispose(); _costC.dispose(); _sellC.dispose();
    _barcodeC.dispose(); _pluC.dispose(); _minC.dispose();
    super.dispose();
  }

  void _fillFrom(InvItem p, {String? keepBarcode}) {
    setState(() {
      _productId = p.id;
      _liveStock = null;        // yangisi kelguncha kesh ko'rsatiladi
      _barcodeC.text = keepBarcode ?? '';
      _nameC.text = p.name;
      _unit = p.weighted ? 'kg' : 'dona';
      _costC.text = p.buyPrice > 0 ? p.buyPrice.round().toString() : '';
      _sellC.text = p.sellPrice > 0 ? p.sellPrice.round().toString() : '';
      _open = false;
    });
    // Qoldiqni serverdan yangilaymiz — kesh eskirgan bo'lsa haqiqiy son ko'rinsin.
    Api.productDetail(p.id).then((d) {
      if (mounted && _productId == p.id) setState(() => _liveStock = d.stock);
    }).catchError((_) {});
  }

  /// Nom o'zgarganda (yangi mahsulot) — kategoriya avto-taxmini (debounce 600ms).
  void _scheduleGuess() {
    _guessTimer?.cancel();
    final name = _nameC.text.trim();
    if (_productId != null || name.length < 3) return;
    _guessTimer = Timer(const Duration(milliseconds: 600), () async {
      final (cid, cname) = await Api.guessCategory(name);
      if (!mounted || _productId != null) return;
      // Foydalanuvchi qo'lda tanlagan bo'lsa — tegmaymiz
      if (cid != null && (_categoryId == null || _catFromGuess)) {
        setState(() { _categoryId = cid; _catFromGuess = true; _guessName = cname; });
      }
    });
  }

  /// Tepadagi katta skaner: bazada bor kod -> mahsulot to'ladi; yo'q -> yangi kod maydonga.
  Future<void> _scan() async {
    final code = await Navigator.of(context).push<String>(
        MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
    if (code == null || code.isEmpty || !mounted) return;
    setState(() => _scanning = true);
    try {
      final hit = await Api.productByBarcode(code);
      if (!mounted) return;
      if (hit != null) {
        _fillFrom(hit);
        _snack(tr('Topildi') + ': ' + hit.name);
      } else {
        setState(() {
          _productId = null;
          _barcodeC.text = code;
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

  /// Barcode MAYDONI yonidagi skaner — faqat maydonni to'ldiradi
  /// (band kod bo'lsa ogohlantirib, mavjud mahsulotga o'tishni taklif qiladi).
  Future<void> _scanToBarcodeField() async {
    final code = await Navigator.of(context).push<String>(
        MaterialPageRoute(builder: (_) => const BarcodeScanScreen()));
    if (code == null || code.isEmpty || !mounted) return;
    try {
      final hit = await Api.productByBarcode(code);
      if (!mounted) return;
      if (hit != null) {
        _snack('${tr('Bu kod band')}: ${hit.name}');
        _fillFrom(hit, keepBarcode: null);
        return;
      }
    } catch (_) {/* offline — baribir to'ldiramiz, server commitда tekshiradi */}
    setState(() => _barcodeC.text = code);
  }

  void _save() {
    final name = _nameC.text.trim();
    final qty = double.tryParse(_qtyC.text.replaceAll(',', '.')) ?? 0;
    if (name.isEmpty) { _snack(tr('Mahsulot nomini kiriting')); return; }
    if (qty <= 0) { _snack(tr('Miqdorni kiriting')); return; }
    final isNew = _productId == null;
    final barcode = _barcodeC.text.replaceAll(RegExp(r'\D'), '');
    final plu = _pluC.text.replaceAll(RegExp(r'\D'), '');
    if (isNew && _unit == 'dona' && barcode.isEmpty) {
      _snack(tr('Shtrix-kodni kiriting yoki skanerlang')); return;
    }
    if (isNew && _unit == 'kg' && plu.isEmpty) {
      _snack(tr('Tarozi PLU kodini kiriting')); return;
    }
    // Narxlarda ham vergul kasr sifatida (miqdor bilan izchil)
    final cost = double.tryParse(_costC.text.replaceAll(',', '.')) ?? 0;
    final sell = double.tryParse(_sellC.text.replaceAll(',', '.'));
    final minQ = double.tryParse(_minC.text.replaceAll(',', '.'));
    final item = ReviewItem(
      productId: _productId,
      newName: isNew ? name : null,
      newSellPrice: sell,
      newCategoryId: isNew ? _categoryId : null,
      newBarcode: barcode.isEmpty ? null : barcode,
      newPlu: isNew && _unit == 'kg' && plu.isNotEmpty ? plu : null,
      newIsWeighted: isNew ? _unit == 'kg' : null,
      newMinQty: isNew ? minQ : null,
      name: name, qty: qty, unitCost: cost, unit: isNew ? _unit : _unit,
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
                const SizedBox(height: 16),

                // Nom (qidiruv/yangi)
                Text(tr('Mahsulot nomi'), style: _lbl),
                const SizedBox(height: 6),
                TextField(
                  controller: _nameC,
                  decoration: InputDecoration(hintText: tr('Qidiring yoki yangi nom yozing')),
                  onChanged: (_) { setState(() { _productId = null; _open = true; }); _scheduleGuess(); },
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
                              Text(money(p.sellPrice), style: TextStyle(fontSize: 12, color: AppColors.muted)),
                            ]),
                          ),
                        ),
                    ]),
                  ),
                if (picked.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${tr('Qoldiq')}: ${qtyStr(_liveStock ?? picked.first.stock)}',
                      style: const TextStyle(fontSize: 12.5, color: AppColors.ok, fontWeight: FontWeight.w600),
                    ),
                  ),
                const SizedBox(height: 16),

                // ── YANGI mahsulot: birlik + kod (Manager formasi pariteti) ──
                if (isNew) ...[
                  Text(tr('Birlik'), style: _lbl),
                  const SizedBox(height: 6),
                  Row(children: [
                    for (final u in const ['dona', 'kg']) ...[
                      Expanded(
                        child: GestureDetector(
                          onTap: () => setState(() => _unit = u),
                          child: Container(
                            padding: const EdgeInsets.symmetric(vertical: 11),
                            decoration: BoxDecoration(
                              color: _unit == u ? AppColors.accentSoft : AppColors.card,
                              borderRadius: BorderRadius.circular(11),
                              border: Border.all(color: _unit == u ? AppColors.accent : AppColors.border, width: 1.5),
                            ),
                            child: Center(child: Text(
                              u == 'dona' ? tr('Dona') : tr('Kg (tarozi)'),
                              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700,
                                  color: _unit == u ? AppColors.accentStrong : AppColors.muted),
                            )),
                          ),
                        ),
                      ),
                      if (u == 'dona') const SizedBox(width: 10),
                    ],
                  ]),
                  const SizedBox(height: 16),

                  if (_unit == 'dona') ...[
                    Text(tr('Shtrix-kod (majburiy)'), style: _lbl),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _barcodeC,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                        hintText: tr('Skanerlang yoki qo‘lda kiriting'),
                        suffixIcon: IconButton(
                          icon: Icon(Icons.qr_code_scanner, color: AppColors.accentStrong),
                          onPressed: _scanToBarcodeField,
                        ),
                      ),
                    ),
                  ] else ...[
                    Text(tr('Tarozi PLU kodi (majburiy)'), style: _lbl),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _pluC,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(hintText: tr('Masalan: 412 — tarozida shu kod bilan sotiladi')),
                    ),
                  ],
                  const SizedBox(height: 16),
                ] else if (_barcodeC.text.isNotEmpty) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                    decoration: BoxDecoration(
                      color: AppColors.accentSoft,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(children: [
                      Icon(Icons.qr_code, size: 16, color: AppColors.accentStrong),
                      const SizedBox(width: 8),
                      Expanded(child: Text(
                        '${tr('Kod')}: ${_barcodeC.text}',
                        style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                      )),
                    ]),
                  ),
                  const SizedBox(height: 16),
                ],

                // Miqdor
                Text(_unit == 'kg' ? tr('Miqdor (kg)') : tr('Miqdor'), style: _lbl),
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

                // Kategoriya + min qoldiq (faqat yangi mahsulotda)
                if (isNew) ...[
                  const SizedBox(height: 16),
                  Row(children: [
                    Text(tr('Kategoriya (yangi mahsulot)'), style: _lbl),
                    if (_catFromGuess && _guessName != null) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(7)),
                        child: Text(tr('avto'), style: const TextStyle(fontSize: 10.5, color: AppColors.ok, fontWeight: FontWeight.w700)),
                      ),
                    ],
                  ]),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<String>(
                    value: _categoryId,
                    dropdownColor: AppColors.card,
                    decoration: const InputDecoration(),
                    items: [
                      DropdownMenuItem(value: null, child: Text(tr('Kategoriyasiz'))),
                      for (final c in widget.cats) DropdownMenuItem(value: c.id, child: Text(c.name)),
                    ],
                    onChanged: (v) => setState(() { _categoryId = v; _catFromGuess = false; }),
                  ),
                  const SizedBox(height: 16),
                  Text(tr('Min qoldiq (ogohlantirish uchun, ixtiyoriy)'), style: _lbl),
                  const SizedBox(height: 6),
                  TextField(
                    controller: _minC,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(hintText: '0'),
                  ),
                ],
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
            decoration: BoxDecoration(
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

  TextStyle get _lbl => TextStyle(fontSize: 12.5, color: AppColors.muted, fontWeight: FontWeight.w600);
}
