import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'password_change_screen.dart';

/// Localized label of a role code (`ega`, `administrator`, ...); unknown codes
/// fall back to the server's role name, then the code.
String roleLabel(String code, [String fallback = '']) {
  switch (code.toLowerCase()) {
    case 'ega':
    case 'owner':
      return tr('Ega');
    case 'admin':
    case 'administrator':
      return tr('Administrator');
    case 'menejer':
    case 'manager':
      return tr('Menejer');
    case 'omborchi':
      return tr('Omborchi');
    case 'kassir':
    case 'cashier':
      return tr('Kassir');
    default:
      return fallback.isNotEmpty ? fallback : code;
  }
}

/// Roles an employee can have, lowest first (server `_ROLE_RANK`).
const List<String> kRoleOrder = ['kassir', 'omborchi', 'menejer', 'administrator', 'ega'];

/// Minimum password length of the server policy (`app/core/password_policy.py`
/// `MIN_LEN`). UX hint only — the server decides.
const int kMinPasswordLength = 12;

/// Roles the signed-in employee may ASSIGN — a UX mirror of the server rules
/// (`employees.py`): `ega` only by an owner; `administrator` by an owner or
/// an admin with `xodimlar.make_admin`; others never above their own rank.
List<String> assignableRoles(Session s) {
  final me = s.roleCode;
  final owner = me == 'ega';
  final makeAdmin = owner || s.permissions.contains('xodimlar.make_admin');
  final myRank = kRoleOrder.indexOf(me);
  return [
    for (final r in kRoleOrder)
      if (r == 'ega'
          ? owner
          : r == 'administrator'
              ? makeAdmin
              : (s.fullAccess || (myRank >= 0 && kRoleOrder.indexOf(r) <= myRank)))
        r,
  ];
}

/// Xodim kartasi: yaratish (`employeeId == null`) yoki tahrirlash. Tahrirda:
/// statistika (oylik savdo + 6 oy grafigi) va ruxsatlar.
///
/// Hamma cheklov SERVERDA; bu yerda faqat UX: bajarib bo'lmaydigan amal
/// sababi bilan o'chirilgan holda ko'rsatiladi. O'zini tahrirlashda parol/PIN
/// maydonlari YO'Q (server joriy parolni talab qiladi) — «Xavfsizlik → Parol».
class EmployeeEditScreen extends StatefulWidget {
  final String? employeeId;
  final Session? session;
  const EmployeeEditScreen({super.key, this.employeeId, this.session});
  @override
  State<EmployeeEditScreen> createState() => _EmployeeEditScreenState();
}

class _Original {
  _Original({
    required this.fullName,
    required this.phone,
    required this.role,
    required this.branchId,
    required this.active,
  });
  final String fullName, phone, role, branchId;
  final bool active;
}

class _EmployeeEditScreenState extends State<EmployeeEditScreen> {
  final _nameC = TextEditingController();
  final _phoneC = TextEditingController();
  final _pwC = TextEditingController();
  final _pinC = TextEditingController();
  final _createKey = DraftUuid();
  String _role = 'kassir';
  String _branchId = '';
  bool _active = true;
  bool _busy = false;
  bool _loading = true;
  bool _showErrors = false;
  Object? _loadError;
  Object? _saveError;
  _Original? _orig;

  List<BranchRow> _branches = [];
  EmpStats? _stats;
  List<PermissionRow> _allPerms = [];
  Set<String> _perms = {};

  bool get _isNew => widget.employeeId == null;
  Session get _s => widget.session ?? Session.instance;
  String get _meId => _s.context?.employeeId ?? '${Api.employee?['id'] ?? ''}';
  bool get _isSelf => !_isNew && widget.employeeId == _meId;
  bool get _iAmOwner => _s.roleCode == 'ega';
  bool get _targetManaged => !_isNew && const {'ega', 'administrator'}.contains(_orig?.role);

  // modul.harakat -> tushunarli yorliq
  static const _moduleL = {
    'kassa': 'Kassa',
    'sotuvlar': 'Sotuvlar',
    'qaytarishlar': 'Qaytarishlar',
    'mijozlar': 'Mijozlar',
    'mahsulotlar': 'Mahsulotlar',
    'ombor': 'Ombor',
    'xaridlar': 'Xaridlar',
    'hisobot': 'Hisobot',
    'xodimlar': 'Xodimlar',
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
    _nameC.dispose();
    _phoneC.dispose();
    _pwC.dispose();
    _pinC.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
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
        _orig =
            _Original(fullName: d.fullName, phone: d.phone ?? '', role: d.role, branchId: _branchId, active: _active);
        try {
          allPerms = await Api.permissionsList();
        } catch (_) {}
        try {
          stats = await Api.employeeStats(widget.employeeId!);
        } catch (_) {}
      } else {
        _phoneC.text = '+996 '; // avto prefiks — foydalanuvchi davom ettiradi
        final roles = assignableRoles(_s);
        _role = roles.contains('kassir') ? 'kassir' : (roles.isNotEmpty ? roles.first : 'kassir');
        final cur = _s.currentBranchId;
        _branchId = (cur != null && branches.any((b) => b.id == cur)) ? cur : '';
      }
      if (!mounted) return;
      setState(() {
        _branches = branches;
        _allPerms = allPerms;
        _stats = stats;
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadError = e;
          _loading = false;
        });
      }
    }
  }

  /// Why the whole form is read-only, or `null` when it can be saved.
  String? get _readOnlyReason {
    if (_isNew) {
      return Perm.allows('employees.create', session: _s) ? null : Perm.reason('employees.create', session: _s);
    }
    if (!Perm.allows('employees.edit', session: _s)) return Perm.reason('employees.edit', session: _s);
    if (_targetManaged && !_iAmOwner && !_isSelf) return tr('Administrator/Ega akkauntini faqat Ega boshqaradi');
    return null;
  }

  bool get _roleLocked => _isSelf && !_iAmOwner;

  String _phoneValue() {
    final p = _phoneC.text.trim();
    // Prefiksni (+996) o'zgartirmasdan qoldirsa — telefonsiz.
    return p.replaceAll(RegExp(r'\D'), '') == '996' ? '' : p;
  }

  String? get _nameError => _nameC.text.trim().isEmpty ? tr('Ism kiriting') : null;

  String? get _pinError {
    final p = _pinC.text.trim();
    if (p.isEmpty) return null;
    return RegExp(r'^\d{4}$').hasMatch(p) ? null : tr('PIN aynan 4 raqam bo‘lsin');
  }

  String? get _pwError {
    final p = _pwC.text;
    if (p.isEmpty) return null;
    if (p.length < kMinPasswordLength) return trArgs('Parol kamida {n} belgi bo‘lsin', {'n': kMinPasswordLength});
    if (_phoneValue().isEmpty) return tr('Parolli xodim uchun telefon (login) kerak');
    return null;
  }

  Map<String, dynamic> _createBody() => {
        'full_name': _nameC.text.trim(),
        'phone': _phoneValue(),
        'role_code': _role,
        if (_pwC.text.isNotEmpty) 'password': _pwC.text,
        if (_pinC.text.trim().isNotEmpty) 'pin': _pinC.text.trim(),
        if (_branchId.isNotEmpty) 'branch_id': _branchId,
      };

  Map<String, dynamic> _patchBody() {
    final o = _orig!;
    final name = _nameC.text.trim();
    final phone = _phoneValue();
    return {
      if (name != o.fullName) 'full_name': name,
      if (phone != o.phone) 'phone': phone,
      if (_role != o.role && !_roleLocked) 'role_code': _role,
      if (_branchId != o.branchId) 'branch_id': _branchId,
      if (_active != o.active && !_roleLocked) 'status': _active ? 'active' : 'suspended',
      if (!_isSelf && _pwC.text.isNotEmpty) 'password': _pwC.text,
      if (!_isSelf && _pinC.text.trim().isNotEmpty) 'pin': _pinC.text.trim(),
    };
  }

  Future<void> _save() async {
    if (_busy || _readOnlyReason != null) return;
    setState(() => _showErrors = true);
    if (_nameError != null || _pinError != null || _pwError != null) return;
    setState(() {
      _busy = true;
      _saveError = null;
    });
    try {
      if (_isNew) {
        final body = _createBody();
        // Idempotentlik: bir xil forma — bir xil client_uuid (tarmoq uzilib qayta
        // bosilsa server ikkinchi xodim YARATMAYDI, mavjudini qaytaradi).
        await Api.postJson('/employees', {...body, 'client_uuid': _createKey.forDraft(body)});
        _createKey.rotate();
      } else {
        final patch = _patchBody();
        if (patch.isNotEmpty) await Api.patchJson('/employees/${Api.seg(widget.employeeId!)}', patch);
        if (_isSelf) unawaited(_s.load(force: true)); // ism/filial o'zgargan bo'lishi mumkin
      }
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _saveError = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? get _deleteReason {
    if (!Perm.allows('employees.delete', session: _s)) return Perm.reason('employees.delete', session: _s);
    if (_targetManaged && !_iAmOwner) return tr('Administrator/Ega akkauntini faqat Ega o‘chira oladi');
    return null;
  }

  Future<void> _delete() async {
    if (_busy || _deleteReason != null) return;
    final ok = await confirmDestructive(
      context,
      title: tr("O'chirish"),
      message: '${_nameC.text} — ${tr("xodimni o'chirasizmi?")}',
      details: [tr('Xodim tizimga kira olmaydi; tarixdagi savdo va amallari saqlanadi.')],
      confirmLabel: tr("O'chirish"),
      requireAcknowledge: true,
    );
    if (!ok || !mounted) return;
    setState(() {
      _busy = true;
      _saveError = null;
    });
    try {
      await Api.deleteJson('/employees/${Api.seg(widget.employeeId!)}');
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) setState(() => _saveError = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Why the permission toggles are locked, or `null` when they can be changed.
  String? _permsLockReason({bool makeAdmin = false}) {
    if (!Perm.allows('employees.permissions', session: _s)) return Perm.reason('employees.permissions', session: _s);
    if (makeAdmin && !_iAmOwner) return tr("Buni faqat Ega o'zgartiradi");
    if (!_s.fullAccess) return tr("Ruxsatlarni faqat Ega yoki administrator o'zgartiradi");
    if (_targetManaged && !_iAmOwner) return tr("Buni faqat Ega o'zgartiradi");
    return null;
  }

  Future<void> _togglePerm(String code, {bool makeAdmin = false}) async {
    final why = _permsLockReason(makeAdmin: makeAdmin);
    if (why != null) {
      _snack(why);
      return;
    }
    final want = !_perms.contains(code);
    setState(() => want ? _perms.add(code) : _perms.remove(code));
    try {
      final fresh = await Api.setPermission(widget.employeeId!, code, want);
      if (mounted) setState(() => _perms = fresh.toSet());
    } catch (e) {
      if (mounted) {
        setState(() => want ? _perms.remove(code) : _perms.add(code));
        _snack(employeeErrorMessage(e));
      }
    }
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _pickRole() async {
    final options = assignableRoles(_s);
    final picked = await showAppSheet<String>(
      context,
      title: tr('Rol'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        for (final r in kRoleOrder)
          _radioRow(
            key: Key('role-$r'),
            selected: r == _role,
            label: roleLabel(r),
            enabled: options.contains(r),
            hint: options.contains(r) ? null : tr('Bu rolni tayinlash huquqingiz yo‘q'),
            onTap: () => Navigator.of(ctx).pop(r),
          ),
      ]),
    );
    if (picked != null && mounted) setState(() => _role = picked);
  }

  Future<void> _pickBranch() async {
    final picked = await showAppSheet<String>(
      context,
      title: tr('Filial'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        _radioRow(
          key: const Key('branch-none'),
          selected: _branchId.isEmpty,
          label: tr('Filial biriktirilmagan'),
          onTap: () => Navigator.of(ctx).pop(''),
        ),
        for (final b in _branches)
          _radioRow(
            key: Key('branch-${b.id}'),
            selected: b.id == _branchId,
            label: b.name,
            enabled: b.isActive || b.id == _branchId,
            hint: b.isActive ? null : tr('Nofaol filial'),
            onTap: () => Navigator.of(ctx).pop(b.id),
          ),
      ]),
    );
    if (picked != null && mounted) setState(() => _branchId = picked);
  }

  Widget _radioRow({
    required Key key,
    required bool selected,
    required String label,
    required VoidCallback onTap,
    bool enabled = true,
    String? hint,
  }) =>
      InkWell(
        key: key,
        onTap: enabled ? onTap : null,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 56),
          child: Row(children: [
            Icon(selected ? Icons.radio_button_checked : Icons.radio_button_off,
                color: !enabled ? AppColors.faint : (selected ? AppColors.accentStrong : AppColors.muted)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(label,
                    style: TextStyle(
                        fontSize: 15, fontWeight: FontWeight.w600, color: enabled ? AppColors.text : AppColors.faint)),
                if (hint != null) Text(hint, style: TextStyle(fontSize: 12, color: AppColors.muted)),
              ]),
            ),
          ]),
        ),
      );

  String get _branchName {
    if (_branchId.isEmpty) return tr('Filial biriktirilmagan');
    for (final b in _branches) {
      if (b.id == _branchId) return b.name;
    }
    return tr('Filial');
  }

  InputDecoration _dec(String label, {String? error, String? helper}) => InputDecoration(
        labelText: label,
        errorText: error,
        helperText: helper,
        labelStyle: TextStyle(color: AppColors.muted, fontSize: 13.5),
      );

  Widget _pickerTile(
          {required Key key, required String label, required String value, VoidCallback? onTap, String? hint}) =>
      Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          key: key,
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 56),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12), border: Border.all(color: AppColors.borderInput)),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(label, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                  const SizedBox(height: 2),
                  Text(value, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                  if (hint != null) Text(hint, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                ]),
              ),
              if (onTap != null) Icon(Icons.expand_more, color: AppColors.muted),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final title = _isNew ? tr('Yangi xodim') : (_isSelf ? tr('Mening kartam') : tr('Xodim kartasi'));
    if (_loading) {
      return Scaffold(appBar: AppBar(title: Text(title)), body: const SkeletonList(rows: 5));
    }
    if (_loadError != null) {
      return Scaffold(appBar: AppBar(title: Text(title)), body: ErrorState(error: _loadError!, onRetry: _load));
    }
    final ro = _readOnlyReason;
    final editable = ro == null && !_busy;
    final err = _showErrors;
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          if (ro != null) ...[
            ErrorBanner(key: const Key('employee-readonly'), severity: BannerSeverity.info, message: ro),
            const SizedBox(height: 12),
          ],
          TextField(
            key: const Key('employee-name'),
            controller: _nameC,
            enabled: editable,
            textCapitalization: TextCapitalization.words,
            onChanged: (_) => setState(() {}),
            decoration: _dec(tr('Ism familiya'), error: err ? _nameError : null),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('employee-phone'),
            controller: _phoneC,
            enabled: editable,
            keyboardType: TextInputType.phone,
            onChanged: (_) => setState(() {}),
            decoration: _dec(tr('Telefon'), helper: tr('Parolli xodim shu raqam bilan kiradi')),
          ),
          const SizedBox(height: 12),
          _pickerTile(
            key: const Key('employee-role'),
            label: tr('Rol'),
            value: roleLabel(_role),
            hint: _roleLocked ? tr('O‘z rolingizni o‘zgartira olmaysiz') : null,
            onTap: (editable && !_roleLocked) ? _pickRole : null,
          ),
          const SizedBox(height: 12),
          _pickerTile(
            key: const Key('employee-branch'),
            label: tr('Filial'),
            value: _branchName,
            onTap: editable ? _pickBranch : null,
          ),
          const SizedBox(height: 12),
          if (_isSelf)
            _pickerTile(
              key: const Key('employee-own-password'),
              label: tr('Parol'),
              value: tr('Parolni o‘zgartirish'),
              hint: tr('O‘z parolingiz joriy parol bilan almashtiriladi'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PasswordChangeScreen())),
            )
          else ...[
            TextField(
              key: const Key('employee-password'),
              controller: _pwC,
              enabled: editable,
              obscureText: true,
              onChanged: (_) => setState(() {}),
              decoration: _dec(_isNew ? tr('Parol (ixtiyoriy)') : tr('Yangi parol'),
                  error: err ? _pwError : null, helper: trArgs('Kamida {n} belgi', {'n': kMinPasswordLength})),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('employee-pin'),
              controller: _pinC,
              enabled: editable,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
              obscureText: true,
              onChanged: (_) => setState(() {}),
              decoration: _dec(tr('PIN (kassa uchun)'), error: err ? _pinError : null, helper: tr('4 ta raqam')),
            ),
          ],
          if (!_isNew) ...[
            const SizedBox(height: 4),
            SwitchListTile(
              key: const Key('employee-active'),
              contentPadding: EdgeInsets.zero,
              title: Text(tr('Faol'), style: const TextStyle(fontSize: 14.5)),
              subtitle: Text(
                  _roleLocked
                      ? tr('O‘z holatingizni o‘zgartira olmaysiz')
                      : tr("O'chirilsa xodim tizimga kira olmaydi"),
                  style: TextStyle(fontSize: 12, color: AppColors.muted)),
              value: _active,
              activeThumbColor: AppColors.accent,
              onChanged: (editable && !_roleLocked) ? (v) => setState(() => _active = v) : null,
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
            if (_stats!.chart.isNotEmpty) _chart(),
          ],

          // ── Ruxsatlar (faqat mavjud xodim) ──
          if (!_isNew) ...[
            const SizedBox(height: 16),
            Text(tr('RUXSATLAR'),
                style:
                    TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: AppColors.muted)),
            const SizedBox(height: 8),
            if (_role == 'administrator' || _role == 'ega') ...[
              Container(
                padding: const EdgeInsets.all(13),
                decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(12)),
                child: Row(children: [
                  Icon(Icons.verified_user, size: 18, color: AppColors.accentStrong),
                  const SizedBox(width: 9),
                  Expanded(
                      child: Text(
                          tr(_role == 'ega' ? 'Ega — barcha huquqlar' : 'Administrator — barcha ruxsatlarga ega'),
                          style: TextStyle(fontSize: 13, color: AppColors.accentStrong, fontWeight: FontWeight.w600))),
                ]),
              ),
              // Ega adminga "boshqani admin qilish" (make_admin) huquqini beradi. Egada doim bor.
              if (_role == 'administrator' && _orig?.role == 'administrator')
                SwitchListTile(
                  key: const Key('perm-xodimlar.make_admin'),
                  contentPadding: EdgeInsets.zero,
                  title: Text(tr('Boshqani administrator qilish'),
                      style: TextStyle(
                          fontSize: 13.5,
                          color: _perms.contains('xodimlar.make_admin') ? AppColors.text : AppColors.muted)),
                  value: _perms.contains('xodimlar.make_admin'),
                  activeThumbColor: AppColors.accent,
                  onChanged: _permsLockReason(makeAdmin: true) == null && !_busy
                      ? (_) => _togglePerm('xodimlar.make_admin', makeAdmin: true)
                      : null,
                ),
            ] else
              ..._permGroups(),
          ],

          if (!_isNew && !_isSelf) ...[
            const SizedBox(height: 20),
            _dangerZone(),
          ],
        ],
      ),
      bottomNavigationBar: StickyActionBar(
        key: const Key('employee-save'),
        label: tr('Saqlash'),
        icon: Icons.check,
        busy: _busy,
        enabled: ro == null,
        disabledReason: ro,
        summary: _saveError == null
            ? null
            : ErrorBanner(
                key: const Key('employee-error'),
                message: employeeErrorMessage(_saveError!),
                error: _saveError,
                onDismiss: () => setState(() => _saveError = null),
              ),
        onPressed: _save,
      ),
    );
  }

  Widget _dangerZone() {
    final why = _deleteReason;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SizedBox(
        height: kMinTouch,
        child: OutlinedButton.icon(
          key: const Key('employee-delete'),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.danger,
            side: BorderSide(color: why == null ? AppColors.danger : AppColors.border),
          ),
          onPressed: (why == null && !_busy) ? _delete : null,
          icon: const Icon(Icons.delete_outline),
          label: Text(tr('Xodimni o‘chirish')),
        ),
      ),
      if (why != null)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(why,
              key: const Key('employee-delete-reason'), style: TextStyle(fontSize: 12, color: AppColors.muted)),
        ),
    ]);
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
                      height: 4 + 40 * (v <= 0 ? 0 : v / maxV),
                      margin: const EdgeInsets.symmetric(horizontal: 7),
                      decoration: BoxDecoration(
                          color: v > 0 ? AppColors.accent : AppColors.border, borderRadius: BorderRadius.circular(4)),
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
      if (p.code == 'xodimlar.make_admin') continue; // faqat admin kartasida (Ega beradi)
      groups.putIfAbsent(p.module, () => []).add(p);
    }
    if (groups.isEmpty) {
      return [Text(tr('Ruxsatlar yuklanmadi'), style: TextStyle(fontSize: 12.5, color: AppColors.muted))];
    }
    final why = _permsLockReason();
    final can = why == null && !_busy;
    return [
      for (final e in groups.entries)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          // Material (not a coloured Container): the switches paint their ink on it.
          child: Material(
            color: AppColors.card,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12), side: BorderSide(color: AppColors.border)),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr(_moduleL[e.key] ?? e.key), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                for (final p in e.value)
                  SwitchListTile(
                    key: Key('perm-${p.code}'),
                    contentPadding: EdgeInsets.zero,
                    title: Text(tr(_actionL[p.code.split('.').last] ?? p.code),
                        style: TextStyle(
                            fontSize: 13.5, color: _perms.contains(p.code) ? AppColors.text : AppColors.muted)),
                    value: _perms.contains(p.code),
                    activeThumbColor: AppColors.accent,
                    onChanged: can ? (_) => _togglePerm(p.code) : null,
                  ),
              ]),
            ),
          ),
        ),
      if (why != null)
        Text(why, key: const Key('perms-locked'), style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
    ];
  }
}

/// Server texts of `/employees*` (`apps/server/app/api/v1/employees.py`),
/// EXACTLY as sent. They are translated in `lib/l10n/shell_strings.dart` and
/// shown as-is (a 403 among them is a specific rule, not a missing permission).
const Set<String> kEmployeeServerTexts = {
  'Administrator/Ega akkauntini faqat Ega boshqaradi',
  'Ega rolini faqat Ega tayinlaydi',
  "Administrator tayinlash huquqi yo'q — Ega bilan bog'laning",
  "O'z rolingizni yoki holatingizni o'zgartira olmaysiz",
  "O'z darajangizdan yuqori rol tayinlay olmaysiz",
  "Oxirgi faol rahbarni (Ega/administrator) to'xtatib/o'zgartirib bo'lmaydi",
  "Oxirgi faol Egani pasaytirib/to'xtatib bo'lmaydi — avval boshqa Ega tayinlang",
  "O'zingizni o'chira olmaysiz",
  "Administrator/Ega akkauntini faqat Ega o'chira oladi",
  "Oxirgi faol rahbarni (Ega/administrator) o'chirib bo'lmaydi",
  "Oxirgi faol Egani o'chirib bo'lmaydi — avval boshqa Ega tayinlang",
  'Bu telefon allaqachon band',
  "Bu PIN do'konda allaqachon ishlatilgan",
  "PIN aynan 4 ta raqamdan iborat bo'lishi kerak",
  "Telefon raqami noto'g'ri. Masalan: +996 700 123 456",
  "Parolli akkauntdan telefonni olib tashlab bo'lmaydi (telefon — login)",
  'Parolli xodim uchun telefon (login) kerak',
  'Rol topilmadi',
  'Xodim topilmadi',
  'Xodimда ochiq smena bor — avval smenani yopish kerak',
  "Status noto'g'ri",
  "Ruxsatlarni faqat Ega yoki administrator o'zgartira oladi",
  "Administrator/Ega ruxsatlarини faqat Ega o'zgartiradi",
  '"Admin qilish" huquqini faqat Ega beradi',
  "Parol kamida 6 belgi bo'lishi kerak",
  "Filial ID noto'g'ri",
  'Filial nofaol — avval faollashtiring',
  'Ism kiritilishi kerak',
};

/// Localized message for an employee-management failure: the server's tariff
/// limit (`{"error":"tarif_limit","max_users":N}`), its employee rules
/// ([kEmployeeServerTexts]) and password-policy texts get their own sentence;
/// everything else goes through [userMessage].
String employeeErrorMessage(Object e) {
  if (e is ApiException) {
    final d = e.detail;
    if (d is Map && d['error'] == 'tarif_limit') {
      return trArgs('Tarif bo‘yicha xodimlar chegarasi: {n} ta. Ko‘proq xodim uchun tarifni oshiring.',
          {'n': d['max_users'] ?? '?'});
    }
    if (d is String && kEmployeeServerTexts.contains(d.trim())) return tr(d.trim());
    const prefix = 'Parol qabul qilinmadi: ';
    if (d is String && d.startsWith(prefix)) {
      final why = d.substring(prefix.length);
      if (why.startsWith('juda qisqa')) {
        return trArgs('Parol juda qisqa — kamida {n} belgi kerak.', {'n': kMinPasswordLength});
      }
      if (why.startsWith('juda uzun')) return tr('Parol juda uzun.');
      if (why.startsWith("juda ko'p uchraydigan") || why.startsWith("ma'lum arzon")) {
        return tr('Parol juda oddiy — boshqa parol tanlang.');
      }
      return tr('Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.');
    }
  }
  return userMessage(e);
}
