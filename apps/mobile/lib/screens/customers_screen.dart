import 'dart:async';

import 'package:flutter/material.dart';

import '../api/money_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'customer_edit_screen.dart';
import 'customer_profile_screen.dart';

/// Customers: server-side search (`GET /customers?q=`), "debtors only"
/// filter, create (`mijozlar.edit | kassa.sell`) and the profile.
class CustomersScreen extends StatefulWidget {
  /// Creates the screen; [onlyDebt] starts on the debtors filter.
  const CustomersScreen({super.key, this.onlyDebt = false});

  /// Start with debtors only.
  final bool onlyDebt;

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  final _search = TextEditingController();
  final _view = AsyncViewController();
  late bool _debt = widget.onlyDebt;
  String _q = '';
  Timer? _debounce;

  /// Search debounce (typing does not fire a request per key).
  static const Duration debounce = Duration(milliseconds: 350);

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onQuery(String v) {
    _debounce?.cancel();
    _debounce = Timer(debounce, () {
      if (!mounted || v.trim() == _q) return;
      setState(() => _q = v.trim());
      _view.reload();
    });
  }

  void _setDebt(bool v) {
    if (v == _debt) return;
    setState(() => _debt = v);
    _view.reload();
  }

  Future<void> _create() async {
    final created = await Navigator.of(context).push<CustomerRow>(
      MaterialPageRoute(builder: (_) => const CustomerEditScreen()),
    );
    if (!mounted || created == null) return;
    await _view.reload();
    if (!mounted) return;
    await _open(created);
  }

  Future<void> _open(CustomerRow c) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => CustomerProfileScreen(customerId: c.id, name: c.fullName),
    ));
    if (mounted) await _view.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canCreate = Perm.allows('customers.create');
    return Scaffold(
      appBar: AppBar(
        title: Text(_debt ? tr('Qarzdorlar') : tr('Mijozlar')),
        actions: [
          if (canCreate)
            IconButton(
              key: const Key('customer-create'),
              tooltip: tr('Yangi mijoz'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              onPressed: _create,
              icon: const Icon(Icons.person_add_alt_1),
            ),
        ],
      ),
      body: Column(children: [
        const ConnectivityBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 8),
          child: Column(children: [
            TextField(
              key: const Key('customer-search'),
              controller: _search,
              onChanged: _onQuery,
              textInputAction: TextInputAction.search,
              onSubmitted: (v) {
                _debounce?.cancel();
                setState(() => _q = v.trim());
                _view.reload();
              },
              decoration: InputDecoration(
                hintText: tr('Ism yoki telefon bo‘yicha qidirish'),
                prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 22),
              ),
            ),
            const SizedBox(height: 10),
            Row(children: [
              _chip(tr('Barchasi'), false),
              const SizedBox(width: 8),
              _chip(tr('Qarzdorlar'), true),
            ]),
          ]),
        ),
        Expanded(
          child: AsyncView<List<CustomerRow>>(
            controller: _view,
            load: () => MoneyApi.customers(q: _q, onlyDebt: _debt),
            refreshable: true,
            emptyIcon: _debt ? Icons.verified_outlined : Icons.people_outline,
            empty: EmptyState(
              icon: _debt ? Icons.verified_outlined : Icons.people_outline,
              text: _q.isNotEmpty
                  ? tr('Hech narsa topilmadi')
                  : (_debt ? tr('Qarzdor mijozlar yo‘q') : tr('Hozircha mijoz yo‘q')),
              action: (canCreate && !_debt && _q.isEmpty)
                  ? SizedBox(
                      height: kMinTouch,
                      child: OutlinedButton.icon(
                        onPressed: _create,
                        icon: const Icon(Icons.person_add_alt_1),
                        label: Text(tr('Yangi mijoz')),
                      ),
                    )
                  : null,
            ),
            builder: (context, rows) => _list(rows),
          ),
        ),
      ]),
    );
  }

  Widget _list(List<CustomerRow> rows) {
    // Ro'yxatdagi qarzlar yig'indisi (faqat ko'rsatish; server qiymatlari butun sonda qo'shiladi).
    final debtTotal = rows.fold<int>(0, (a, r) => r.hasDebt ? a + r.balanceCents : a);
    return ListView.builder(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(kGutter, 0, kGutter, 24),
      itemCount: rows.length + (_debt ? 1 : 0),
      itemBuilder: (context, i) {
        if (_debt && i == 0) {
          return Container(
            key: const Key('debt-summary'),
            margin: const EdgeInsets.only(bottom: 10),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: AppColors.warnSoft, borderRadius: BorderRadius.circular(kRadius)),
            child: Row(children: [
              Expanded(
                child: Text(trArgs('{n} ta qarzdor', {'n': rows.length}),
                    style: TextStyle(fontSize: 13.5, color: AppColors.text2)),
              ),
              Text(formatCents(debtTotal),
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: AppColors.warn)),
            ]),
          );
        }
        return _row(rows[i - (_debt ? 1 : 0)]);
      },
    );
  }

  Widget _chip(String label, bool debt) {
    final on = _debt == debt;
    return Semantics(
      selected: on,
      button: true,
      child: InkWell(
        key: Key(debt ? 'filter-debt' : 'filter-all'),
        borderRadius: BorderRadius.circular(10),
        onTap: () => _setDebt(debt),
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

  Widget _row(CustomerRow c) {
    final advance = c.balanceCents < 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(kRadius),
        child: InkWell(
          key: Key('customer-${c.id}'),
          borderRadius: BorderRadius.circular(kRadius),
          onTap: () => _open(c),
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(kRadius),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(children: [
              CircleAvatar(
                radius: 21,
                backgroundColor: AppColors.accentSoft,
                child: Text(c.fullName.isEmpty ? '?' : c.fullName.characters.first.toUpperCase(),
                    style: TextStyle(color: AppColors.accentStrong, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(c.fullName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text([c.code, if (c.phone != null) c.phone!].join(' · '),
                      style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              if (c.hasDebt || advance)
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text(formatCents(c.balanceCents.abs()),
                      style: TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w800,
                          color: advance ? AppColors.accentStrong : AppColors.danger)),
                  Text(advance ? tr('Avans') : tr('Qarz'), style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                ]),
              const SizedBox(width: 4),
              Icon(Icons.chevron_right, color: AppColors.faint),
            ]),
          ),
        ),
      ),
    );
  }
}
