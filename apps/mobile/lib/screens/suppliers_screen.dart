import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../api/money_api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'customer_edit_screen.dart' show phoneLooksValid;
import 'money_payment_sheet.dart';
import 'supplier_detail_screen.dart';

/// Suppliers: list with our debt (`GET /suppliers`, `xaridlar.view`),
/// filter/search, create (`xaridlar.edit`) and the supplier detail.
class SuppliersScreen extends StatefulWidget {
  /// Creates the screen.
  const SuppliersScreen({super.key});

  @override
  State<SuppliersScreen> createState() => _SuppliersScreenState();
}

class _SuppliersScreenState extends State<SuppliersScreen> {
  final _view = AsyncViewController();
  final _search = TextEditingController();
  bool _onlyOwed = false;
  String _q = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final created = await showSupplierForm(context);
    if (!mounted || created == null) return;
    await _view.reload();
    if (!mounted) return;
    await _open(created);
  }

  Future<void> _open(SupplierRowM s) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => SupplierDetailScreen(supplierId: s.id, name: s.name),
    ));
    if (mounted) await _view.reload();
  }

  List<SupplierRowM> _filter(List<SupplierRowM> all) {
    final q = _q.toLowerCase();
    return [
      for (final s in all)
        if ((!_onlyOwed || s.weOwe) &&
            (q.isEmpty || s.name.toLowerCase().contains(q) || (s.phone ?? '').contains(q)))
          s
    ];
  }

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows('suppliers.list')) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Yetkazib beruvchilar'))),
        body: const NoAccessView(action: 'suppliers.list'),
      );
    }
    final canCreate = Perm.allows('suppliers.create');
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Yetkazib beruvchilar')),
        actions: [
          if (canCreate)
            IconButton(
              key: const Key('supplier-create'),
              tooltip: tr('Yangi yetkazib beruvchi'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              onPressed: _create,
              icon: const Icon(Icons.add_business_outlined),
            ),
        ],
      ),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: AsyncView<List<SupplierRowM>>(
            controller: _view,
            load: MoneyApi.suppliers,
            refreshable: true,
            empty: EmptyState(
              icon: Icons.local_shipping_outlined,
              text: tr('Hozircha yetkazib beruvchi yo‘q'),
              action: canCreate
                  ? SizedBox(
                      height: kMinTouch,
                      child: OutlinedButton.icon(
                        onPressed: _create,
                        icon: const Icon(Icons.add),
                        label: Text(tr('Yangi yetkazib beruvchi')),
                      ),
                    )
                  : null,
            ),
            builder: (context, all) => _body(all),
          ),
        ),
      ]),
    );
  }

  Widget _body(List<SupplierRowM> all) {
    final rows = _filter(all);
    // Umumiy qarzimiz — serverdagi balanslarning butun-son yig'indisi (faqat ko'rsatish).
    final owed = all.fold<int>(0, (a, s) => s.weOwe ? a + s.balanceCents : a);
    final owedCount = all.where((s) => s.weOwe).length;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
      children: [
        Container(
          key: const Key('suppliers-owed'),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: owed > 0 ? AppColors.dangerSoft : AppColors.okSoft,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('Biz qarzmiz'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
            const SizedBox(height: 4),
            Text(formatCents(owed),
                style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    color: owed > 0 ? AppColors.danger : AppColors.ok,
                    letterSpacing: -0.5)),
            const SizedBox(height: 2),
            Text(trArgs('{n} ta yetkazib beruvchiga', {'n': owedCount}),
                style: TextStyle(fontSize: 12.5, color: AppColors.text3)),
          ]),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('supplier-search'),
          controller: _search,
          onChanged: (v) => setState(() => _q = v.trim()),
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            hintText: tr('Nomi yoki telefon bo‘yicha qidirish'),
            prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 22),
          ),
        ),
        const SizedBox(height: 10),
        Row(children: [
          _chip(tr('Barchasi'), false),
          const SizedBox(width: 8),
          _chip(tr('Qarzimiz bor'), true),
        ]),
        const SizedBox(height: 12),
        if (rows.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 32),
            child: Center(
              child: Text(_onlyOwed && _q.isEmpty ? tr('Hech kimga qarzimiz yo‘q') : tr('Hech narsa topilmadi'),
                  style: TextStyle(color: AppColors.muted)),
            ),
          )
        else
          for (final s in rows) _row(s),
      ],
    );
  }

  Widget _chip(String label, bool owed) {
    final on = _onlyOwed == owed;
    return Semantics(
      selected: on,
      button: true,
      child: InkWell(
        key: Key(owed ? 'filter-owed' : 'filter-all'),
        borderRadius: BorderRadius.circular(10),
        onTap: () => setState(() => _onlyOwed = owed),
        child: Container(
          constraints: const BoxConstraints(minHeight: kMinTouch, minWidth: kMinTouch),
          padding: const EdgeInsets.symmetric(horizontal: 16),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: on ? AppColors.accent : AppColors.card,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: on ? AppColors.accent : AppColors.border),
          ),
          child: Text(label,
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: on ? Colors.white : AppColors.text3)),
        ),
      ),
    );
  }

  Widget _row(SupplierRowM s) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Material(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(kRadius),
          child: InkWell(
            key: Key('supplier-${s.id}'),
            borderRadius: BorderRadius.circular(kRadius),
            onTap: () => _open(s),
            child: Container(
              constraints: const BoxConstraints(minHeight: 64),
              padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
              decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
              child: Row(children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(11)),
                  child: Icon(Icons.local_shipping_outlined, color: AppColors.accentStrong, size: 20),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(s.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
                    if (s.phone != null) ...[
                      const SizedBox(height: 2),
                      Text(s.phone!, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                    ],
                  ]),
                ),
                if (s.balanceCents != 0)
                  Text(formatCents(s.balanceCents.abs()),
                      style: TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w800,
                          color: s.weOwe ? AppColors.danger : AppColors.accentStrong)),
                const SizedBox(width: 4),
                Icon(Icons.chevron_right, color: AppColors.faint),
              ]),
            ),
          ),
        ),
      );
}

/// Create (no [supplier]) or edit a supplier in a bottom sheet; resolves to
/// the saved row after a 2xx, or null.
///
/// ⚠️  `POST /suppliers` has no idempotency key on the server: after a lost
///     answer the form does NOT retry by itself — it tells the operator to
///     check the list first (a blind retry could create a duplicate).
Future<SupplierRowM?> showSupplierForm(BuildContext context, {SupplierRowM? supplier}) => showAppSheet<SupplierRowM>(
      context,
      title: supplier == null ? tr('Yangi yetkazib beruvchi') : tr('Yetkazib beruvchini tahrirlash'),
      scrollable: false,
      builder: (_) => SupplierForm(supplier: supplier),
    );

/// Body of [showSupplierForm] (public for tests).
class SupplierForm extends StatefulWidget {
  /// Creates the form.
  const SupplierForm({super.key, this.supplier});

  /// The supplier to edit; null creates one.
  final SupplierRowM? supplier;

  @override
  State<SupplierForm> createState() => _SupplierFormState();
}

class _SupplierFormState extends State<SupplierForm> {
  late final _name = TextEditingController(text: widget.supplier?.name ?? '');
  late final _phone = TextEditingController(text: widget.supplier?.phone ?? '');
  final _nameFocus = FocusNode();
  final _phoneFocus = FocusNode();
  bool _tried = false;
  bool _busy = false;
  bool _unknown = false;
  Object? _error;
  String? _phoneServerError;

  bool get _isEdit => widget.supplier != null;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _nameFocus.dispose();
    _phoneFocus.dispose();
    super.dispose();
  }

  String? get _nameError => _name.text.trim().isEmpty ? tr('Nomini kiriting') : null;

  String? get _phoneError =>
      _phoneServerError ?? (phoneLooksValid(_phone.text) ? null : tr('Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456'));

  bool get _changed {
    final s = widget.supplier;
    if (s == null) return true;
    return _name.text.trim() != s.name || _phone.text.trim() != (s.phone ?? '');
  }

  Future<void> _save() async {
    setState(() => _tried = true);
    if (_nameError != null) {
      _nameFocus.requestFocus();
      return;
    }
    if (_phoneError != null) {
      _phoneFocus.requestFocus();
      return;
    }
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final s = widget.supplier;
      final SupplierRowM saved = s == null
          ? await MoneyApi.createSupplier(name: _name.text.trim(), phone: _phone.text)
          : await MoneyApi.editSupplier(
              s.id,
              name: _name.text.trim() != s.name ? _name.text.trim() : null,
              phone: _phone.text.trim() != (s.phone ?? '') ? _phone.text.trim() : null,
            );
      if (!mounted) return;
      Navigator.of(context).pop(saved);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _unknown = isConnectivityError(e);
        final t = e is ApiException ? (ApiException.flatten(e.detail) ?? '') : '';
        if (t.startsWith("Telefon raqami noto'g'ri")) {
          _phoneServerError = tr('Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456');
          _error = null;
        } else if (t == "Bu telefon do'konda allaqachon band") {
          _phoneServerError = userMessage(e);
          _error = null;
        } else {
          _error = e;
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Flexible(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            TextField(
              key: const Key('supplier-name'),
              controller: _name,
              focusNode: _nameFocus,
              enabled: !_busy,
              autofocus: !_isEdit,
              maxLength: 200,
              textCapitalization: TextCapitalization.sentences,
              textInputAction: TextInputAction.next,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                labelText: '${tr('Nomi')} *',
                errorText: _tried ? _nameError : null,
                counterText: '',
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              key: const Key('supplier-phone'),
              controller: _phone,
              focusNode: _phoneFocus,
              enabled: !_busy,
              keyboardType: TextInputType.phone,
              textInputAction: TextInputAction.done,
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9+ ()-]'))],
              onChanged: (_) => setState(() => _phoneServerError = null),
              decoration: InputDecoration(
                labelText: tr('Telefon (ixtiyoriy)'),
                hintText: '+996 700 123 456',
                errorText: (_tried || _phoneServerError != null) ? _phoneError : null,
                errorMaxLines: 2,
                prefixIcon: Icon(Icons.phone_outlined, color: AppColors.muted),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 14),
              _unknown
                  ? ErrorBanner(
                      key: const Key('supplier-unknown'),
                      severity: BannerSeverity.warning,
                      message: _isEdit
                          ? tr('Server javobi kelmadi — o‘zgarish saqlangan-saqlanmagani noma’lum. Qayta saqlash xavfsiz.')
                          : tr('Server javobi kelmadi — yetkazib beruvchi yaratilgan bo‘lishi mumkin. '
                              'Takror yaratmaslik uchun avval ro‘yxatni yangilab tekshiring.'),
                    )
                  : ErrorBanner(key: const Key('supplier-error'), error: _error),
            ],
          ]),
        ),
      ),
      StickyActionBar(
        label: tr('Saqlash'),
        icon: Icons.check,
        busy: _busy,
        // Yaratishda javob yo'qolsa — ko'r-ko'rona qayta yuborish dublikat yaratishi mumkin.
        enabled: _changed && !(_unknown && !_isEdit),
        disabledReason: (_unknown && !_isEdit) ? tr('Avval ro‘yxatni tekshiring') : tr('O‘zgarish yo‘q'),
        onPressed: _save,
        secondaryLabel: (_unknown && !_isEdit) ? tr('Yopish') : null,
        onSecondary: () => Navigator.of(context).pop(),
      ),
    ]);
  }
}
