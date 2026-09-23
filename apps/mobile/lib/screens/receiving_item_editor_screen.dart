import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../api/receiving_api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../qty.dart';
import '../scan.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/lot_editor.dart';
import 'barcode_scan_screen.dart';
import 'receiving_widgets.dart';

/// One receiving line (manual receiving, or an AI line being fixed).
///
/// * product: server scan (barcode / scale label) or server search — never
///   the full catalog; a scale label also fills the weighed quantity;
/// * NEW product: unit (dona/kg/litr/upak), barcode 6–14 digits checked
///   against the catalog (non-kg) or PLU 1–5 digits (kg), category (auto
///   guess), min qty; a name equal to a TRACKED product is refused;
/// * lot-tracked product: [LotEditor] (one row follows the line quantity until
///   edited), cost > 0, expiry iff tracked and not before the receiving
///   branch's business date.
///
/// Pops the edited [RecvLine] (the caller owns it afterwards) or null.
class ReceivingItemEditorScreen extends StatefulWidget {
  /// Creates the editor; [line] null = a new empty line.
  const ReceivingItemEditorScreen({super.key, this.line, this.tracked});

  /// The line to edit (a COPY is edited; the original is untouched on cancel).
  final RecvLine? line;

  /// Tracked products (flags of AI matches, tracked-name check).
  final TrackedCatalog? tracked;

  /// Camera override for tests.
  @visibleForTesting
  static ScannerViewBuilder? debugScannerBuilder;

  @override
  State<ReceivingItemEditorScreen> createState() => _ReceivingItemEditorScreenState();
}

class _ReceivingItemEditorScreenState extends State<ReceivingItemEditorScreen> {
  late final RecvLine _line;
  late final TextEditingController _nameC, _qtyC, _costC, _sellC, _barcodeC, _pluC, _minC;
  final _nameF = FocusNode(), _qtyF = FocusNode(), _costF = FocusNode(), _sellF = FocusNode();
  final _barcodeF = FocusNode(), _pluF = FocusNode(), _minF = FocusNode();
  final _scroll = ScrollController();
  bool _saved = false;
  bool _showErrors = false;
  bool _saving = false;
  Object? _saveError;
  late final String _initialPrint;

  // Server search suggestions (new-product name field).
  Timer? _searchT;
  int _searchSeq = 0;
  List<RecvProduct> _sugg = const [];
  bool _searching = false;
  Object? _searchError;
  bool _suggOpen = false;

  // Category (new product).
  List<CategoryLite>? _cats;
  Object? _catsError;
  bool _catGuessed = false;
  Timer? _guessT;

  TrackedCatalog get _tracked => widget.tracked ?? TrackedCatalog.empty();

  @override
  void initState() {
    super.initState();
    final src = widget.line;
    _line = src?.clone() ?? RecvLine();
    if (_line.unmatched && (_line.aiName ?? '').isNotEmpty) _line.newName = _line.aiName!;
    _nameC = TextEditingController(text: _line.newName);
    _qtyC = TextEditingController(text: _line.qtyText);
    _costC = TextEditingController(text: _line.costText);
    _sellC = TextEditingController(text: _line.sellText);
    _barcodeC = TextEditingController(text: _line.barcode);
    _pluC = TextEditingController(text: _line.plu);
    _minC = TextEditingController(text: _line.minText);
    _initialPrint = _print();
    if (_line.trackExpiry) _loadBiz();
    if (_line.isNew) _ensureCats();
    // AI o'qigan, katalogga mos kelmagan nom: mavjud mahsulotlar darrov taklif qilinadi
    // (yangi mahsulot ochishdan oldin — dublikat yaratmaslik uchun).
    if (_line.isNew && (_line.aiName ?? '').isNotEmpty && _nameC.text.trim().length >= 2) {
      _suggOpen = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _search();
      });
    }
  }

  @override
  void dispose() {
    _searchT?.cancel();
    _guessT?.cancel();
    for (final c in [_nameC, _qtyC, _costC, _sellC, _barcodeC, _pluC, _minC]) {
      c.dispose();
    }
    for (final f in [_nameF, _qtyF, _costF, _sellF, _barcodeF, _pluF, _minF]) {
      f.dispose();
    }
    _scroll.dispose();
    if (!_saved) _line.dispose(); // bekor qilindi — nusxaning partiya muharriri bizniki
    super.dispose();
  }

  String _print() => [
        _line.product?.id,
        _line.newName,
        _line.unit,
        _line.barcode,
        _line.plu,
        _line.categoryId,
        _line.sellText,
        _line.minText,
        _line.qtyText,
        _line.costText,
        for (final r in _line.lots?.rows ?? const <LotDraft>[]) '${r.qty}|${r.expiry}|${r.batch}',
      ].join('§');

  bool get _dirty => _print() != _initialPrint;

  // ── Loading helpers ─────────────────────────────────────────────────────

  Future<void> _loadBiz() async {
    final p = _line.product;
    if (p == null) return;
    final d = await ReceivingApi.businessDate(p.id);
    if (!mounted || _line.product?.id != p.id) return;
    setState(() => _line.lots?.businessDate = d);
  }

  Future<void> _ensureCats() async {
    if (_cats != null) return;
    try {
      final c = await ReceivingApi.categories();
      if (mounted) setState(() => _cats = c);
    } catch (e) {
      if (mounted) setState(() => _catsError = e);
    }
  }

  void _scheduleGuess() {
    _guessT?.cancel();
    final name = _line.newName.trim();
    if (!_line.isNew || name.length < 3 || (_line.categoryId != null && !_catGuessed)) return;
    _guessT = Timer(const Duration(milliseconds: 600), () async {
      final (cid, cname) = await ReceivingApi.guessCategory(name);
      if (!mounted || !_line.isNew || cid == null) return;
      if (_line.categoryId == null || _catGuessed) {
        setState(() {
          _line.categoryId = cid;
          _line.categoryName = cname;
          _catGuessed = true;
        });
      }
    });
  }

  void _scheduleSearch() {
    _searchT?.cancel();
    final q = _nameC.text.trim();
    if (q.length < 2) {
      setState(() {
        _sugg = const [];
        _searching = false;
        _searchError = null;
      });
      return;
    }
    _searchT = Timer(const Duration(milliseconds: 350), _search);
  }

  Future<void> _search() async {
    final q = _nameC.text.trim();
    final seq = ++_searchSeq;
    setState(() {
      _searching = true;
      _searchError = null;
    });
    try {
      final rows = await ReceivingApi.searchProducts(q, limit: 8);
      if (!mounted || seq != _searchSeq) return;
      setState(() {
        _sugg = rows;
        _searching = false;
      });
    } catch (e) {
      if (!mounted || seq != _searchSeq) return;
      setState(() {
        _searchError = e;
        _searching = false;
      });
    }
  }

  // ── Product choice ──────────────────────────────────────────────────────

  RecvProduct _withCatalogFlags(RecvProduct p) {
    final t = _tracked.byId[p.id];
    if (t == null || p.trackLots) return p;
    return p.withTracking(trackLots: true, trackExpiry: t.trackExpiry);
  }

  void _pick(RecvProduct p, {int? qtyMilli}) {
    final prod = _withCatalogFlags(p);
    _searchT?.cancel();
    _guessT?.cancel();
    _searchSeq++; // kechikkan qidiruv javobi tanlovni bekor qilmasin
    setState(() {
      _searching = false;
      if (qtyMilli != null && qtyMilli > 0) {
        _qtyC.text = milliToInput(qtyMilli);
        _line.qtyText = _qtyC.text;
      }
      _line.setProduct(prod);
      if (_line.costText.trim().isEmpty && (prod.buyCents ?? 0) > 0) {
        _line.costText = centsToInput(prod.buyCents!);
        _costC.text = _line.costText;
      }
      if (_line.sellText.trim().isEmpty && (prod.sellCents ?? 0) > 0) {
        _line.sellText = centsToInput(prod.sellCents!);
        _sellC.text = _line.sellText;
      }
      _suggOpen = false;
      _sugg = const [];
      _saveError = null;
    });
    FocusScope.of(context).unfocus();
    // Tanlangan mahsulot kartasi (tepada) ko'rinsin — ro'yxat pastda qolib ketmasin.
    if (_scroll.hasClients) {
      _scroll.animateTo(0, duration: const Duration(milliseconds: 250), curve: Curves.easeOut).ignore();
    }
    if (_line.trackExpiry) _loadBiz();
  }

  void _clearProduct() {
    setState(() {
      _line.setProduct(null);
      _nameC.text = _line.newName;
      _suggOpen = true;
    });
    _ensureCats();
    _nameF.requestFocus();
  }

  Future<ScanResult?> _openScanner() => Navigator.of(context).push<ScanResult>(MaterialPageRoute(
        builder: (_) => BarcodeScanScreen.lookup(
          allowNotFound: true,
          scannerBuilder: ReceivingItemEditorScreen.debugScannerBuilder,
        ),
      ));

  /// Top scanner: a known code picks the product (a scale label also the
  /// weight); an unknown code starts a NEW product with that barcode.
  Future<void> _scan() async {
    final r = await _openScanner();
    if (r == null || !mounted) return;
    final p = r.product;
    if (p != null) {
      _pick(RecvProduct.fromScan(p), qtyMilli: r.qtyMilli);
      _snack(trArgs('Topildi: {name}', {'name': p.name}));
      return;
    }
    final code = r.code.replaceAll(RegExp(r'\D'), '');
    setState(() {
      _line.setProduct(null);
      if (_line.unit == 'kg') _line.unit = 'dona';
      _line.barcode = code;
      _barcodeC.text = code;
      _line.barcodeVerified = isValidBarcode(code); // server "none" dedi — kod bo'sh
    });
    _ensureCats();
    _snack(tr('Yangi kod — mahsulot nomini kiriting'));
    _nameF.requestFocus();
  }

  /// Barcode field scanner (new product): a code already used by another
  /// product is NOT silently attached — the operator decides.
  Future<void> _scanBarcodeField() async {
    final r = await _openScanner();
    if (r == null || !mounted) return;
    final p = r.product;
    if (p != null) {
      await _codeTaken(RecvProduct.fromScan(p));
      return;
    }
    final code = r.code.replaceAll(RegExp(r'\D'), '');
    setState(() {
      _line.barcode = code;
      _barcodeC.text = code;
      _line.barcodeVerified = isValidBarcode(code);
    });
  }

  Future<void> _codeTaken(RecvProduct p) async {
    final use = await showAppSheet<bool>(
      context,
      title: tr('Bu shtrix-kod band'),
      builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(trArgs('Bu kod «{name}» mahsulotiga tegishli. Yangi mahsulotga biriktirib bo‘lmaydi.', {'name': p.name}),
            key: const Key('recv-code-taken'), style: const TextStyle(fontSize: 15, height: 1.35)),
        const SizedBox(height: 16),
        SizedBox(
          height: kPrimaryButtonHeight,
          child: ElevatedButton(
            key: const Key('recv-code-taken-use'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(tr('Shu mahsulotni tanlash')),
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          height: kMinTouch,
          child: TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(tr('Bekor qilish'))),
        ),
      ]),
    );
    if (use == true && mounted) {
      _pick(p);
    }
  }

  // ── Save ────────────────────────────────────────────────────────────────

  FocusNode? _focusFor(RecvIssueKind k) => switch (k) {
        RecvIssueKind.unmatched || RecvIssueKind.name || RecvIssueKind.trackedName => _nameF,
        RecvIssueKind.barcode => _barcodeF,
        RecvIssueKind.plu => _pluF,
        RecvIssueKind.qty => _qtyF,
        RecvIssueKind.cost => _costF,
        RecvIssueKind.sell => _sellF,
        RecvIssueKind.min => _minF,
        RecvIssueKind.lots => null,
      };

  void _focus(FocusNode n) {
    n.requestFocus();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final ctx = n.context;
      if (ctx != null && ctx.mounted) {
        Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 200), alignment: 0.2);
      }
    });
  }

  Future<void> _save() async {
    if (_saving) return;
    setState(() {
      _showErrors = true;
      _saveError = null;
    });
    final issues = lineIssues(_line, tracked: _tracked);
    final lotsOk = _line.lots?.validate() ?? true;
    if (issues.isNotEmpty) {
      final first = issues.first;
      final f = _focusFor(first.kind);
      if (f != null) {
        _focus(f);
      } else if (lotsOk) {
        _snack(first.message);
      }
      return;
    }
    if (!lotsOk) return;
    // Yangi mahsulot shtrix-kodi katalogda band emasligini SERVER tasdiqlaydi —
    // aks holda server band kodni JIMGINA tashlab, mahsulotni kodsiz yaratardi.
    if (_line.isNew && _line.unit != 'kg' && !_line.barcodeVerified) {
      setState(() => _saving = true);
      try {
        final l = await ScanService.lookup(_line.barcode.trim());
        if (!mounted) return;
        setState(() => _saving = false);
        if (l.product != null) {
          await _codeTaken(RecvProduct.fromScan(l.product!));
          return;
        }
        if (l.kind == ScanKind.ambiguous) {
          setState(() => _saveError = tr('Bu kod tarozi yorlig‘i sifatida mavjud mahsulotlarga mos keladi — boshqa kod bering.'));
          return;
        }
        _line.barcodeVerified = true;
      } catch (e) {
        if (mounted) {
          setState(() {
            _saving = false;
            _saveError = e;
          });
        }
        return;
      }
    }
    _saved = true;
    if (mounted) Navigator.of(context).pop(_line);
  }

  Future<bool> _confirmDiscard() async {
    if (!_dirty) return true;
    final r = await confirmDestructive(
      context,
      title: tr('O‘zgarishlar saqlanmaydi'),
      message: tr('Kiritilgan ma’lumotlar saqlanmaydi. Chiqasizmi?'),
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Qolish'),
    );
    return r;
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m)));
  }

  // ── Build ───────────────────────────────────────────────────────────────

  String? _err(List<RecvIssue> issues, Set<RecvIssueKind> kinds) {
    if (!_showErrors) return null;
    for (final i in issues) {
      if (kinds.contains(i.kind)) return i.message;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final issues = lineIssues(_line, tracked: _tracked);
    final total = _line.totalCents;
    final title = widget.line == null ? tr('Mahsulot qo‘shish') : tr('Qatorni tahrirlash');
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (_saving) return;
        final nav = Navigator.of(context);
        if (await _confirmDiscard() && mounted) nav.pop();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(title)),
        body: SafeArea(
          bottom: false,
          child: Column(children: [
            Expanded(
              child: ListView(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
                children: [
                  if ((_line.aiName ?? '').isNotEmpty) ...[
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
                      child: Row(children: [
                        Icon(Icons.document_scanner_outlined, size: 18, color: AppColors.muted),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(trArgs('AI o‘qidi: {name}', {'name': _line.aiName}),
                              style: TextStyle(fontSize: 13, color: AppColors.text3, fontStyle: FontStyle.italic)),
                        ),
                      ]),
                    ),
                    const SizedBox(height: 12),
                  ],
                  SizedBox(
                    height: kPrimaryButtonHeight,
                    child: ElevatedButton.icon(
                      key: const Key('recv-edit-scan'),
                      onPressed: _saving ? null : _scan,
                      icon: const Icon(Icons.qr_code_scanner, size: 22),
                      label: Text(tr('Shtrix-kodni skanerlash')),
                    ),
                  ),
                  const SizedBox(height: 16),
                  ..._productSection(issues),
                  if (_line.isNew && _line.newName.trim().isNotEmpty) ..._newProductSection(issues),
                  const SizedBox(height: 16),
                  QtyField(
                    key: const Key('recv-edit-qty'),
                    controller: _qtyC,
                    focusNode: _qtyF,
                    label: tr('Miqdor'),
                    unit: _line.unitCode.isEmpty ? null : _line.unitCode,
                    errorText: _err(issues, {RecvIssueKind.qty}),
                    onChanged: (_) => setState(() => _line.setQtyText(_qtyC.text)),
                  ),
                  const SizedBox(height: 14),
                  MoneyField(
                    key: const Key('recv-edit-cost'),
                    controller: _costC,
                    focusNode: _costF,
                    wholeOnly: false,
                    allowZero: true,
                    label: tr('Kelish narxi (birlik uchun)'),
                    helperText: _line.tracked ? tr('Partiyali mahsulot uchun majburiy') : null,
                    errorText: _err(issues, {RecvIssueKind.cost}),
                    onChanged: (_) => setState(() => _line.costText = _costC.text),
                  ),
                  const SizedBox(height: 14),
                  MoneyField(
                    key: const Key('recv-edit-sell'),
                    controller: _sellC,
                    focusNode: _sellF,
                    wholeOnly: false,
                    allowZero: true,
                    label: tr('Sotish narxi (ixtiyoriy)'),
                    errorText: _err(issues, {RecvIssueKind.sell}),
                    onChanged: (_) => setState(() => _line.sellText = _sellC.text),
                  ),
                  if (_line.lots != null) ...[
                    const SizedBox(height: 16),
                    LotEditor(
                      key: const Key('recv-edit-lots'),
                      controller: _line.lots!,
                      unit: _line.unitCode,
                      enabled: !_saving,
                    ),
                  ],
                  if (_saveError != null) ...[
                    const SizedBox(height: 14),
                    _saveError is String
                        ? ErrorBanner(key: const Key('recv-edit-error'), message: _saveError as String)
                        : ErrorBanner(key: const Key('recv-edit-error'), error: _saveError, onRetry: _save),
                  ],
                ],
              ),
            ),
            StickyActionBar(
              label: tr('Saqlash'),
              icon: Icons.check,
              busy: _saving,
              onPressed: _save,
              summary: total == null
                  ? null
                  : Row(children: [
                      Expanded(child: Text(tr('Qator summasi'), style: TextStyle(color: AppColors.muted))),
                      Text(formatCents(total),
                          key: const Key('recv-edit-total'),
                          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                    ]),
            ),
          ]),
        ),
      ),
    );
  }

  List<Widget> _productSection(List<RecvIssue> issues) {
    final p = _line.product;
    if (p != null) {
      final stock = p.stockMilli;
      return [
        Container(
          key: const Key('recv-edit-product'),
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(kRadius),
            border: Border.all(color: AppColors.accentBorder),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Icon(Icons.inventory_2_outlined, color: AppColors.accentStrong),
              const SizedBox(width: 10),
              Expanded(child: Text(p.name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800))),
            ]),
            const SizedBox(height: 6),
            Wrap(spacing: 6, runSpacing: 4, children: [
              if ((p.unitCode ?? '').isNotEmpty) RecvBadge(p.unitCode!, color: AppColors.text3),
              ...productBadges(p),
            ]),
            if (stock != null) ...[
              const SizedBox(height: 6),
              Text('${tr('Qoldiq')}: ${formatMilli(stock, group: true)}',
                  style: const TextStyle(fontSize: 13, color: AppColors.ok, fontWeight: FontWeight.w600)),
            ],
            if (!p.isActive) ...[
              const SizedBox(height: 6),
              Text(tr('Mahsulot arxivda — kirimdan keyin avtomatik faollashadi'),
                  style: const TextStyle(fontSize: 12.5, color: AppColors.warn)),
            ],
            const SizedBox(height: 8),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton.icon(
                key: const Key('recv-edit-change-product'),
                onPressed: _saving ? null : _clearProduct,
                style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
                icon: const Icon(Icons.swap_horiz, size: 18),
                label: Text(tr('Boshqa mahsulot')),
              ),
            ),
          ]),
        ),
      ];
    }
    final collision = _tracked.byName(_line.newName);
    return [
      TextField(
        key: const Key('recv-edit-name'),
        controller: _nameC,
        focusNode: _nameF,
        textCapitalization: TextCapitalization.sentences,
        textInputAction: TextInputAction.next,
        onTap: () => setState(() => _suggOpen = true),
        onChanged: (v) {
          setState(() {
            _line.newName = v;
            _suggOpen = true;
          });
          _scheduleSearch();
          _scheduleGuess();
        },
        decoration: InputDecoration(
          labelText: tr('Mahsulot nomi'),
          hintText: tr('Qidiring yoki yangi nom yozing'),
          errorText: _err(issues, {RecvIssueKind.name, RecvIssueKind.unmatched}),
          errorMaxLines: 3,
          suffixIcon: _searching
              ? const Padding(
                  padding: EdgeInsets.all(14),
                  child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)))
              : null,
          constraints: const BoxConstraints(minHeight: kMinTouch),
        ),
      ),
      if (_suggOpen && _searchError != null) ...[
        const SizedBox(height: 6),
        ErrorBanner(error: _searchError, onRetry: _search),
      ],
      if (_suggOpen && _sugg.isNotEmpty)
        Container(
          key: const Key('recv-edit-suggestions'),
          margin: const EdgeInsets.only(top: 6),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.border),
          ),
          child: Column(children: [
            for (final s in _sugg)
              InkWell(
                key: Key('recv-sugg-${s.id}'),
                onTap: () => _pick(s),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 52),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    child: Row(children: [
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                          Text(s.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14.5)),
                          if (productBadges(_withCatalogFlags(s)).isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.only(top: 3),
                              child: Wrap(spacing: 6, children: productBadges(_withCatalogFlags(s))),
                            ),
                        ]),
                      ),
                      if (s.stockMilli != null)
                        Text(formatMilli(s.stockMilli!, group: true), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                    ]),
                  ),
                ),
              ),
          ]),
        ),
      if (collision != null) ...[
        const SizedBox(height: 8),
        Container(
          key: const Key('recv-edit-tracked-collision'),
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
          decoration: BoxDecoration(
            color: AppColors.warnSoft,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.warnBorder),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(
              trArgs('«{name}» nomli mahsulot bor va u partiya bo‘yicha kuzatiladi — uni ro‘yxatdan tanlang',
                  {'name': collision.name}),
              style: TextStyle(fontSize: 13.5, color: AppColors.text),
            ),
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton(
                key: const Key('recv-edit-use-tracked'),
                onPressed: () => _pick(collision),
                style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
                child: Text(tr('Shu mahsulotni tanlash')),
              ),
            ),
          ]),
        ),
      ],
    ];
  }

  List<Widget> _newProductSection(List<RecvIssue> issues) {
    final kg = _line.unit == 'kg';
    String? catName = _line.categoryName;
    if (catName == null && _line.categoryId != null) {
      for (final c in _cats ?? const <CategoryLite>[]) {
        if (c.id == _line.categoryId) catName = c.name;
      }
    }
    final catLabel = _line.categoryId == null ? tr('Kategoriyasiz') : (catName ?? '—');
    return [
      const SizedBox(height: 16),
      Row(children: [
        Text(tr('Yangi mahsulot'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
        const SizedBox(width: 8),
        RecvBadge(tr('Yangi'), color: AppColors.ok),
      ]),
      const SizedBox(height: 10),
      Text(tr('Birlik'), style: TextStyle(fontSize: 12.5, color: AppColors.muted, fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final u in kRecvUnits)
          Semantics(
            inMutuallyExclusiveGroup: true,
            checked: _line.unit == u,
            button: true,
            child: InkWell(
              key: Key('recv-edit-unit-$u'),
              borderRadius: BorderRadius.circular(11),
              onTap: () => setState(() {
                _line.unit = u;
              }),
              child: Container(
                constraints: const BoxConstraints(minHeight: kMinTouch, minWidth: 72),
                padding: const EdgeInsets.symmetric(horizontal: 14),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: _line.unit == u ? AppColors.accentSoft : AppColors.card,
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(color: _line.unit == u ? AppColors.accent : AppColors.border, width: 1.5),
                ),
                child: Text(recvUnitLabel(u),
                    style: TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w700,
                        color: _line.unit == u ? AppColors.accentStrong : AppColors.muted)),
              ),
            ),
          ),
      ]),
      const SizedBox(height: 14),
      if (!kg)
        TextField(
          key: const Key('recv-edit-barcode'),
          controller: _barcodeC,
          focusNode: _barcodeF,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(14)],
          onChanged: (v) => setState(() {
            _line.barcode = v;
            _line.barcodeVerified = false;
          }),
          decoration: InputDecoration(
            labelText: tr('Shtrix-kod (majburiy)'),
            helperText: tr('6–14 raqam; skanerlash tavsiya etiladi'),
            errorText: _err(issues, {RecvIssueKind.barcode}),
            errorMaxLines: 2,
            constraints: const BoxConstraints(minHeight: kMinTouch),
            suffixIcon: IconButton(
              key: const Key('recv-edit-barcode-scan'),
              tooltip: tr('Shtrix-kodni skanerlash'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              icon: Icon(Icons.qr_code_scanner, color: AppColors.accentStrong),
              onPressed: _scanBarcodeField,
            ),
          ),
        )
      else
        TextField(
          key: const Key('recv-edit-plu'),
          controller: _pluC,
          focusNode: _pluF,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(5)],
          onChanged: (v) => setState(() => _line.plu = v),
          decoration: InputDecoration(
            labelText: tr('Tarozi PLU kodi (majburiy)'),
            helperText: tr('1–5 raqam — tarozida shu kod bilan sotiladi'),
            errorText: _err(issues, {RecvIssueKind.plu}),
            constraints: const BoxConstraints(minHeight: kMinTouch),
          ),
        ),
      const SizedBox(height: 14),
      InkWell(
        key: const Key('recv-edit-category'),
        borderRadius: BorderRadius.circular(12),
        onTap: _pickCategory,
        child: Container(
          constraints: const BoxConstraints(minHeight: 56),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.borderInput),
          ),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(tr('Kategoriya'), style: TextStyle(fontSize: 12, color: AppColors.muted)),
                Text(catLabel, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
              ]),
            ),
            if (_catGuessed && _line.categoryId != null) ...[
              RecvBadge(tr('avto'), color: AppColors.ok),
              const SizedBox(width: 6),
            ],
            Icon(Icons.expand_more, color: AppColors.muted),
          ]),
        ),
      ),
      const SizedBox(height: 14),
      QtyField(
        key: const Key('recv-edit-min'),
        controller: _minC,
        focusNode: _minF,
        allowZero: true,
        label: tr('Min qoldiq (ogohlantirish uchun, ixtiyoriy)'),
        errorText: _err(issues, {RecvIssueKind.min}),
        onChanged: (_) => setState(() => _line.minText = _minC.text),
      ),
    ];
  }

  Future<void> _pickCategory() async {
    if (_cats == null) {
      _catsError = null;
      await _ensureCats();
      if (!mounted) return;
      if (_cats == null) {
        _snack(userMessage(_catsError));
        return;
      }
    }
    final cats = _cats!;
    final picked = await showAppSheet<CategoryLite>(
      context,
      title: tr('Kategoriya'),
      scrollable: false,
      builder: (ctx) => SizedBox(
        height: MediaQuery.of(ctx).size.height * 0.6,
        child: ListView(children: [
          ListTile(
            minTileHeight: kMinTouch + 8,
            title: Text(tr('Kategoriyasiz')),
            onTap: () => Navigator.of(ctx).pop(CategoryLite(id: '', name: '')),
          ),
          for (final c in cats)
            ListTile(
              key: Key('recv-cat-${c.id}'),
              minTileHeight: kMinTouch + 8,
              title: Text(c.name),
              trailing: c.id == _line.categoryId ? Icon(Icons.check, color: AppColors.accentStrong) : null,
              onTap: () => Navigator.of(ctx).pop(c),
            ),
        ]),
      ),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _line.categoryId = picked.id.isEmpty ? null : picked.id;
      _line.categoryName = picked.id.isEmpty ? null : picked.name;
      _catGuessed = false;
    });
  }
}
