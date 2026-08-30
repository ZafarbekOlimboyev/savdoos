import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

/// Xodim kartasi: yaratish (employeeId == null) yoki tahrirlash.
/// Tahrirda: statistika (oylik savdo + 6 oy grafigi) va ruxsatlar (faqat admin o'zgartiradi).
class EmployeeEditScreen extends StatefulWidget {
  final String? employeeId;
  const EmployeeEditScreen({super.key, this.employeeId});
  @override
  State<EmployeeEditScreen> createState() => _EmployeeEditScreenState();
}

class _EmployeeEditScreenState extends State<EmployeeEditScreen> {
  final _nameC = TextEditingController();
  final _phoneC = TextEditingController();
  final _pwC = TextEditingController();
  final _pinC = TextEditingController();
  String _role = 'kassir';
  String _branchId = '';
  bool _active = true;
  bool _busy = false;
  bool _loading = true;
  String? _err;

  List<BranchRow> _branches = [];
  EmpStats? _stats;
  List<PermissionRow> _allPerms = [];
  Set<String> _perms = {};

  bool get _isNew => widget.employeeId == null;

  static const _roles = [
    ('kassir', 'Kassir'), ('omborchi', 'Omborchi'),
    ('menejer', 'Menejer'), ('administrator', 'Administrator'), ('ega', 'Ega'),
  ];

  // modul.harakat -> tushunarli yorliq
  static const _moduleL = {
    'kassa': 'Kassa', 'sotuvlar': 'Sotuvlar', 'qaytarishlar': 'Qaytarishlar',
    'mijozlar': 'Mijozlar', 'mahsulotlar': 'Mahsulotlar', 'ombor': 'Ombor',
    'xaridlar': 'Xaridlar', 'hisobot': 'Hisobot', 'xodimlar': 'Xodimlar',
    'sozlamalar': 'Sozlamalar',
  };
  static const _actionL = {'view': "Ko'rish", 'edit': "O'zgartirish", 'sell': 'Sotish', 'create': 'Yaratish'};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _nameC.dispose(); _phoneC.dispose(); _pwC.dispose(); _pinC.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final branches = await Api.branches();
      List<PermissionRow> allPerms = [];
      EmpStats? stats;
      if (!_isNew) {
        final d = await Api.employeeDetail(widget.employeeId!);
        _nameC.text = d.fullName;
        _phoneC.text = d.phone ?? '';
        _role = d.role;
        _branchId = d.branchId ?? '';
        _active = d.status == 'active';
        _perms = d.permissions.toSet();
        try { allPerms = await Api.permissionsList(); } catch (_) {}
        try { stats = await Api.employeeStats(widget.employeeId!); } catch (_) {}
      } else {
        _phoneC.text = '+998 ';  // avto prefiks — foydalanuvchi davom ettiradi (xohlasa o'chirib boshqa kod)
        if (branches.isNotEmpty) _branchId = branches.first.id;
      }
      if (!mounted) return;
      setState(() { _branches = branches; _allPerms = allPerms; _stats = stats; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _err = e.toString(); _loading = false; });
    }
  }

  Future<void> _save() async {
    final name = _nameC.text.trim();
    if (name.isEmpty) { _snack(tr('Ism kiriting')); return; }
    // Foydalanuvchi prefiksni (+998) o'zgartirmasdan qoldirsa — telefonsiz saqlaymiz.
    var phone = _phoneC.text.trim();
    if (phone.replaceAll(RegExp(r'\D'), '') == '998') phone = '';
    setState(() { _busy = true; _err = null; });
    try {
      if (_isNew) {
        await Api.createEmployee(
            fullName: name,
            phone: phone,
            roleCode: _role,
            password: _pwC.text,
            pin: _pinC.text,
            branchId: _branchId.isEmpty ? null : _branchId);
      } else {
        final patch = <String, dynamic>{
          'full_name': name,
          'phone': phone,
          'role_code': _role,
          'branch_id': _branchId,
          'status': _active ? 'active' : 'suspended',
        };
        if (_pwC.text.isNotEmpty) patch['password'] = _pwC.text;
        if (_pinC.text.isNotEmpty) patch['pin'] = _pinC.text;
        await Api.editEmployee(widget.employeeId!, patch);
      }
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _err = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr("O'chirish")),
        content: Text('${_nameC.text} — ${tr("xodimni o'chirasizmi?")}',
            style: TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Bekor'))),
          ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger),
              onPressed: () => Navigator.pop(context, true),
              child: Text(tr("O'chirish"), style: const TextStyle(color: Colors.white))),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      await Api.deleteEmployee(widget.employeeId!);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) { setState(() => _busy = false); _snack(e.toString()); }
    }
  }

  Future<void> _togglePerm(String code, {bool ownerOnly = false}) async {
    // ownerOnly (masalan make_admin yoki admin akkaunt ruxsati) — faqat Ega.
    // Boshqa (pastroq rol) ruxsatlari — Ega yoki administrator.
    final allowed = ownerOnly ? Api.isOwner : (Api.isOwner || Api.isAdmin);
    if (!allowed) {
      _snack(tr(ownerOnly ? "Buni faqat Ega o'zgartiradi" : "Ruxsatlarni faqat Ega yoki administrator o'zgartiradi"));
      return;
    }
    final want = !_perms.contains(code);
    setState(() { want ? _perms.add(code) : _perms.remove(code); });
    try {
      final fresh = await Api.setPermission(widget.employeeId!, code, want);
      if (mounted) setState(() => _perms = fresh.toSet());
    } catch (e) {
      if (mounted) {
        setState(() { want ? _perms.remove(code) : _perms.add(code); });
        _snack(e.toString());
      }
    }
  }

  void _snack(String m) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  InputDecoration _dec(String label) => InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: AppColors.muted, fontSize: 13.5),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_isNew ? tr('Yangi xodim') : tr('Xodim kartasi')),
        actions: [
          if (!_isNew && Api.can('xodimlar.edit'))
            IconButton(onPressed: _busy ? null : _delete,
                icon: Icon(Icons.delete_outline, color: AppColors.danger)),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                TextField(controller: _nameC, decoration: _dec(tr('Ism familiya'))),
                const SizedBox(height: 12),
                TextField(controller: _phoneC, keyboardType: TextInputType.phone,
                    decoration: _dec(tr('Telefon'))),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _role,
                  decoration: _dec(tr('Rol')),
                  dropdownColor: AppColors.card,
                  items: [for (final r in _roles)
                    DropdownMenuItem(value: r.$1, child: Text(tr(r.$2)))],
                  onChanged: (v) => setState(() => _role = v ?? 'kassir'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _branchId.isEmpty ? '' : _branchId,
                  decoration: _dec(tr('Filial')),
                  dropdownColor: AppColors.card,
                  items: [
                    DropdownMenuItem(value: '', child: Text(tr('Filial biriktirilmagan'))),
                    for (final b in _branches) DropdownMenuItem(value: b.id, child: Text(b.name)),
                  ],
                  onChanged: (v) => setState(() => _branchId = v ?? ''),
                ),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: TextField(controller: _pwC, obscureText: true,
                        decoration: _dec(_isNew ? tr('Parol (ixtiyoriy)') : tr('Yangi parol'))),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 130,
                    child: TextField(controller: _pinC, keyboardType: TextInputType.number,
                        obscureText: true, maxLength: 8,
                        decoration: _dec('PIN').copyWith(counterText: '')),
                  ),
                ]),
                if (!_isNew) ...[
                  const SizedBox(height: 4),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(tr('Faol'), style: const TextStyle(fontSize: 14.5)),
                    subtitle: Text(tr("O'chirilsa xodim tizimga kira olmaydi"),
                        style: TextStyle(fontSize: 12, color: AppColors.muted)),
                    value: _active,
                    activeThumbColor: AppColors.accent,
                    onChanged: (v) => setState(() => _active = v),
                  ),
                ],

                // ── Statistika (faqat mavjud xodim) ──
                if (_stats != null) ...[
                  const SizedBox(height: 8),
                  Row(children: [
                    Expanded(child: _statCard(tr('Oylik savdo'), money(_stats!.monthSales))),
                    const SizedBox(width: 10),
                    Expanded(child: _statCard(tr('Cheklar'), '${_stats!.tx}')),
                  ]),
                  const SizedBox(height: 10),
                  _chart(),
                ],

                // ── Ruxsatlar (faqat mavjud xodim) ──
                if (!_isNew) ...[
                  const SizedBox(height: 16),
                  Text(tr('RUXSATLAR'),
                      style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800,
                          letterSpacing: 0.8, color: AppColors.muted)),
                  const SizedBox(height: 8),
                  if (_role == 'administrator' || _role == 'ega') ...[
                    Container(
                      padding: const EdgeInsets.all(13),
                      decoration: BoxDecoration(color: AppColors.accentSoft,
                          borderRadius: BorderRadius.circular(12)),
                      child: Row(children: [
                        Icon(Icons.verified_user, size: 18, color: AppColors.accentStrong),
                        const SizedBox(width: 9),
                        Expanded(child: Text(tr(_role == 'ega' ? 'Ega — barcha huquqlar' : 'Administrator — barcha ruxsatlarga ega'),
                            style: TextStyle(fontSize: 13, color: AppColors.accentStrong,
                                fontWeight: FontWeight.w600))),
                      ]),
                    ),
                    // Ega adminга "boshqani admin qilish" (make_admin) huquqini beradi. Egada doim bor.
                    if (_role == 'administrator')
                      SwitchListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: Text(tr('Boshqani administrator qilish'),
                            style: TextStyle(fontSize: 13.5,
                                color: _perms.contains('xodimlar.make_admin') ? AppColors.text : AppColors.muted)),
                        value: _perms.contains('xodimlar.make_admin'),
                        activeThumbColor: AppColors.accent,
                        onChanged: Api.isOwner ? (_) => _togglePerm('xodimlar.make_admin', ownerOnly: true) : null,
                      ),
                  ]
                  else
                    ..._permGroups(),
                ],

                if (_err != null) ...[
                  const SizedBox(height: 12),
                  Text(_err!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
                ],
                const SizedBox(height: 16),
                SizedBox(
                  height: 52,
                  child: ElevatedButton(
                    onPressed: _busy ? null : _save,
                    style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.accent, foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(13))),
                    child: _busy
                        ? const SizedBox(width: 20, height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : Text(tr('Saqlash'), style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(height: 24),
              ],
            ),
    );
  }

  Widget _statCard(String label, String value) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          const SizedBox(height: 3),
          Text(value, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w800)),
        ]),
      );

  Widget _chart() {
    final ch = _stats!.chart;
    final maxV = ch.fold<double>(1, (m, e) => e.$2 > m ? e.$2 : m);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
      decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(tr("So'nggi 6 oy — savdo"), style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
        const SizedBox(height: 8),
        SizedBox(
          height: 64,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              for (final (label, v) in ch)
                Expanded(
                  child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                    Container(
                      height: 4 + 40 * (v / maxV),
                      margin: const EdgeInsets.symmetric(horizontal: 7),
                      decoration: BoxDecoration(
                          color: v > 0 ? AppColors.accent : AppColors.border,
                          borderRadius: BorderRadius.circular(4)),
                    ),
                    const SizedBox(height: 4),
                    Text(label, style: TextStyle(fontSize: 9.5, color: AppColors.muted)),
                  ]),
                ),
            ],
          ),
        ),
      ]),
    );
  }

  List<Widget> _permGroups() {
    final groups = <String, List<PermissionRow>>{};
    for (final p in _allPerms) {
      if (p.code == 'xodimlar.make_admin') continue;  // faqat admin kartasida (Ega beradi)
      groups.putIfAbsent(p.module, () => []).add(p);
    }
    if (groups.isEmpty) {
      return [Text(tr("Ruxsatlar yuklanmadi"), style: TextStyle(fontSize: 12.5, color: AppColors.muted))];
    }
    final admin = Api.isOwner || Api.isAdmin;  // pastroq rol ruxsatlarини Ega ham, admin ham beradi
    return [
      for (final e in groups.entries)
        Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 4),
          decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr(_moduleL[e.key] ?? e.key),
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
            for (final p in e.value)
              SwitchListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(tr(_actionL[p.code.split('.').last] ?? p.code),
                    style: TextStyle(fontSize: 13.5,
                        color: _perms.contains(p.code) ? AppColors.text : AppColors.muted)),
                value: _perms.contains(p.code),
                activeThumbColor: AppColors.accent,
                onChanged: admin ? (_) => _togglePerm(p.code) : null,
              ),
          ]),
        ),
      if (!admin)
        Text(tr("Ruxsatlarni faqat Ega yoki administrator o'zgartiradi"),
            style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
    ];
  }
}
