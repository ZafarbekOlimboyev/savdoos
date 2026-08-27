import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'customer_profile_screen.dart';

class CustomersScreen extends StatefulWidget {
  final bool onlyDebt;
  const CustomersScreen({super.key, this.onlyDebt = false});
  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  Future<List<Debtor>>? _future;
  late bool _debt;
  String _q = '';

  @override
  void initState() {
    super.initState();
    _debt = widget.onlyDebt;
    _reload();
  }

  // DIQQAT: blok-tanа `{ }` — aks holda `=> _future = ...` yo'l qo'yilgan Future'ni QAYTARADI
  // va setState "callback Future qaytardi" deb debug'da qizil ekran beradi.
  void _reload() => setState(() {
        _future = Api.customers(onlyDebt: _debt);
      });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Mijozlar'))),
      body: FutureBuilder<List<Debtor>>(
        future: _future,
        builder: (context, snap) {
          final loading = snap.connectionState == ConnectionState.waiting;
          final all = snap.data ?? [];
          final ql = _q.toLowerCase();
          final rows = all.where((c) => ql.isEmpty || c.name.toLowerCase().contains(ql) || (c.phone ?? '').contains(ql)).toList();
          return Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: Column(children: [
                TextField(
                  onChanged: (v) => setState(() => _q = v),
                  decoration: InputDecoration(hintText: tr('Ism yoki telefon qidirish...'), prefixIcon: Icon(Icons.search, color: AppColors.muted, size: 20), isDense: true),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  _chip(tr('Barcha'), false),
                  const SizedBox(width: 8),
                  _chip(tr('Qarzdor'), true),
                ]),
              ]),
            ),
            Expanded(
              child: loading
                  ? const Center(child: CircularProgressIndicator())
                  : rows.isEmpty
                      ? Center(child: Text(tr('Topilmadi'), style: TextStyle(color: AppColors.muted)))
                      : RefreshIndicator(
                          onRefresh: () async => _reload(),
                          child: ListView.builder(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                            itemCount: rows.length,
                            itemBuilder: (context, i) => _row(rows[i]),
                          ),
                        ),
            ),
          ]);
        },
      ),
    );
  }

  Widget _chip(String label, bool debt) {
    final on = _debt == debt;
    return GestureDetector(
      onTap: () { setState(() => _debt = debt); _reload(); },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 8),
        decoration: BoxDecoration(
          color: on ? AppColors.accent : AppColors.card,
          borderRadius: BorderRadius.circular(9),
          border: Border.all(color: on ? AppColors.accent : AppColors.border),
        ),
        child: Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: on ? Colors.white : AppColors.text3)),
      ),
    );
  }

  Widget _row(Debtor c) {
    final debtor = c.balance > 0;
    return GestureDetector(
      onTap: () async {
        await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => CustomerProfileScreen(customerId: c.id, name: c.name)));
        _reload();
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
        child: Row(children: [
          CircleAvatar(radius: 21, backgroundColor: AppColors.accentSoft, child: Text(c.name.isEmpty ? '?' : c.name[0], style: TextStyle(color: AppColors.accentStrong, fontWeight: FontWeight.w700))),
          const SizedBox(width: 13),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(c.name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
              if (c.phone != null && c.phone!.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(c.phone!, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
              ],
            ]),
          ),
          if (debtor)
            Text(money(c.balance), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger)),
        ]),
      ),
    );
  }
}

// (Qarz to'lash endi CustomerProfileScreen ichida — bu yerdagi sheet olib tashlandi)
