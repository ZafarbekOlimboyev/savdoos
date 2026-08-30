import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'employee_edit_screen.dart';

/// Xodimlar ro'yxati — ega/menejer uchun to'liq boshqaruv kirish nuqtasi.
class EmployeesScreen extends StatefulWidget {
  const EmployeesScreen({super.key});
  @override
  State<EmployeesScreen> createState() => _EmployeesScreenState();
}

class _EmployeesScreenState extends State<EmployeesScreen> {
  Future<List<EmployeeRow>>? _future;

  @override
  void initState() {
    super.initState();
    _future = Api.employees();
  }

  void _reload() => setState(() { _future = Api.employees(); });

  Future<void> _open([EmployeeRow? e]) async {
    final changed = await Navigator.of(context).push<bool>(
        MaterialPageRoute(builder: (_) => EmployeeEditScreen(employeeId: e?.id)));
    if (changed == true) _reload();
  }

  String _roleLabel(String code, String fallback) => switch (code) {
        'ega' => tr('Ega'),
        'administrator' => tr('Administrator'),
        'menejer' => tr('Menejer'),
        'omborchi' => tr('Omborchi'),
        'kassir' => tr('Kassir'),
        _ => fallback,
      };

  @override
  Widget build(BuildContext context) {
    final canEdit = Api.can('xodimlar.edit');
    return Scaffold(
      appBar: AppBar(title: Text(tr('Xodimlar'))),
      floatingActionButton: canEdit
          ? FloatingActionButton(
              backgroundColor: AppColors.accent,
              onPressed: () => _open(),
              child: const Icon(Icons.person_add_alt_1, color: Colors.white))
          : null,
      body: FutureBuilder<List<EmployeeRow>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          Widget child;
          if (snap.hasError) {
            child = ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
              SizedBox(height: 200, child: Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)))),
            ]);
          } else {
            final rows = snap.data ?? [];
            child = ListView.builder(
              padding: const EdgeInsets.all(14),
              itemCount: rows.length,
              itemBuilder: (context, i) {
                final e = rows[i];
                final active = e.status == 'active';
                return GestureDetector(
                  onTap: () => _open(e),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                        color: AppColors.card,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: AppColors.border)),
                    child: Row(children: [
                      Container(
                        width: 42, height: 42,
                        decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(12)),
                        child: Center(
                            child: Text(e.fullName.isEmpty ? '?' : e.fullName[0].toUpperCase(),
                                style: TextStyle(color: AppColors.accentStrong, fontSize: 17, fontWeight: FontWeight.w800))),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(e.fullName, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                          const SizedBox(height: 2),
                          Text(
                            [_roleLabel(e.role, e.roleName), if ((e.branch ?? '').isNotEmpty) e.branch!].join(' · '),
                            style: TextStyle(fontSize: 12, color: AppColors.muted)),
                        ]),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                        decoration: BoxDecoration(
                            color: active ? AppColors.okSoft : AppColors.dangerSoft,
                            borderRadius: BorderRadius.circular(8)),
                        child: Text(active ? tr('Faol') : tr("To'xtatilgan"),
                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700,
                                color: active ? AppColors.ok : AppColors.danger)),
                      ),
                    ]),
                  ),
                );
              },
            );
          }
          return RefreshIndicator(
            onRefresh: () async => _reload(),
            child: child,
          );
        },
      ),
    );
  }
}
