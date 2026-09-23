import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'employee_edit_screen.dart';

/// Xodimlar ro'yxati (`xodimlar.view`). "Xodim qo'shish" — `xodimlar.edit`;
/// ruxsat bo'lmasa tugma sababi bilan o'chirilgan holda ko'rinadi.
class EmployeesScreen extends StatefulWidget {
  const EmployeesScreen({super.key, this.session});

  /// Session (default [Session.instance]).
  final Session? session;

  @override
  State<EmployeesScreen> createState() => _EmployeesScreenState();
}

class _EmployeesScreenState extends State<EmployeesScreen> {
  final _ctl = AsyncViewController();

  Session get _s => widget.session ?? Session.instance;

  Future<List<EmployeeRow>> _load() => Api.employees();

  Future<void> _open([EmployeeRow? e]) async {
    final changed = await Navigator.of(context)
        .push<bool>(MaterialPageRoute(builder: (_) => EmployeeEditScreen(employeeId: e?.id)));
    if (changed == true) await _ctl.reload();
  }

  @override
  Widget build(BuildContext context) {
    final canView = Perm.allows('employees.list', session: _s);
    final canCreate = Perm.allows('employees.create', session: _s);
    return Scaffold(
      appBar: AppBar(title: Text(tr('Xodimlar'))),
      body: !canView
          ? EmptyState(text: Perm.reason('employees.list', session: _s), icon: Icons.lock_outline)
          : AsyncView<List<EmployeeRow>>(
              controller: _ctl,
              load: _load,
              refreshable: true,
              emptyText: tr('Hozircha xodim yo‘q'),
              emptyIcon: Icons.people_outline,
              builder: (context, rows) => ListView.builder(
                padding: const EdgeInsets.all(14),
                physics: const AlwaysScrollableScrollPhysics(),
                itemCount: rows.length,
                itemBuilder: (context, i) => _EmployeeTile(e: rows[i], onTap: () => _open(rows[i])),
              ),
            ),
      bottomNavigationBar: canView
          ? StickyActionBar(
              key: const Key('employees-add'),
              label: tr('Xodim qo‘shish'),
              icon: Icons.person_add_alt_1,
              enabled: canCreate,
              disabledReason: Perm.reason('employees.create', session: _s),
              onPressed: () => _open(),
            )
          : null,
    );
  }
}

class _EmployeeTile extends StatelessWidget {
  const _EmployeeTile({required this.e, required this.onTap});
  final EmployeeRow e;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final active = e.status == 'active';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(kRadius),
        child: InkWell(
          key: Key('employee-${e.id}'),
          borderRadius: BorderRadius.circular(kRadius),
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 68),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(kRadius), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(12)),
                child: Center(
                    child: Text(e.fullName.isEmpty ? '?' : e.fullName.characters.first.toUpperCase(),
                        style: TextStyle(color: AppColors.accentStrong, fontSize: 17, fontWeight: FontWeight.w800))),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(e.fullName, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text([roleLabel(e.role, e.roleName), if ((e.branch ?? '').isNotEmpty) e.branch!].join(' · '),
                      style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                    color: active ? AppColors.okSoft : AppColors.dangerSoft, borderRadius: BorderRadius.circular(8)),
                child: Text(active ? tr('Faol') : tr("To'xtatilgan"),
                    style: TextStyle(
                        fontSize: 11, fontWeight: FontWeight.w700, color: active ? AppColors.ok : AppColors.danger)),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
