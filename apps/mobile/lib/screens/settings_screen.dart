import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../lock.dart';
import '../permissions.dart';
import '../platform/platform.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'employee_edit_screen.dart' show roleLabel;
import 'employees_screen.dart';
import 'login_screen.dart';
import 'notifications_screen.dart';
import 'password_change_screen.dart';
import 'pin_screens.dart';
import 'shell.dart' show ShellGates;
import 'tariff_screen.dart';

/// Sozlamalar: who I am (role, company, branch), the branch switcher, my
/// permissions, a manual session refresh, app preferences and the app lock.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, this.session});

  /// Session (default [Session.instance]).
  final Session? session;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _bioAvail = false;
  String _version = '';
  bool _refreshing = false;

  Session get _s => widget.session ?? Session.instance;

  @override
  void initState() {
    super.initState();
    Lock.biometricAvailable().then((v) {
      if (mounted) setState(() => _bioAvail = v);
    });
    AppPackageInfo.instance.read().then((p) {
      // Build number included on purpose: `versionName` alone cannot tell two
      // pilot builds of the same version apart, which is exactly the question
      // a tester is asked ("which build is on that phone?").
      if (p != null && mounted) setState(() => _version = '${p.version}+${p.buildNumber}');
    });
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _changePin() async {
    await Navigator.of(context)
        .push(MaterialPageRoute(builder: (ctx) => PinSetupScreen(onDone: () => Navigator.of(ctx).pop())));
    if (mounted) setState(() {});
  }

  Future<void> _toggleBiometric(bool on) async {
    if (on && !Lock.hasPin) {
      await _changePin();
      if (!Lock.hasPin) return; // foydalanuvchi PIN qo'ymadi
    }
    await Lock.setBiometric(on);
    if (mounted) setState(() {});
  }

  Future<void> _toggleLock(bool on) async {
    if (on && !Lock.hasPin) {
      await _changePin();
      if (!Lock.hasPin) return;
    }
    await Lock.setLockEnabled(on);
    if (mounted) setState(() {});
  }

  Future<void> _refreshSession() async {
    if (_refreshing) return;
    setState(() => _refreshing = true);
    final before = _s.loadedAt;
    await _s.load(force: true);
    if (!mounted) return;
    setState(() => _refreshing = false);
    final ok = _s.loadedAt != null && _s.loadedAt != before;
    _snack(ok ? tr('Ma’lumotlar yangilandi') : userMessage(_s.lastError));
  }

  Future<void> _logout() async {
    final ok = await confirmDestructive(
      context,
      title: tr('Chiqish'),
      message: tr('Hisobdan chiqmoqchimisiz?'),
      details: [tr('Ilova qulfi (PIN) ham o‘chiriladi — keyingi kirishda yangidan o‘rnatiladi.')],
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Bekor'),
    );
    if (!ok) return;
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true)
        .pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  Future<void> _editServer() async {
    final saved = await showAppSheet<String>(
      context,
      title: tr('Server manzili'),
      builder: (ctx) => _ServerForm(initial: Api.baseUrl, warnLogout: Api.loggedIn),
    );
    if (saved == null) return;
    // Server almashsa Api o'zi tozalaydi va login ekraniga qaytaradi (onSessionExpired).
    await Api.setBaseUrl(saved);
    if (mounted) setState(() {});
  }

  Future<void> _pickLanguage() async {
    const langs = [
      ('uz', 'O‘zbekcha', "O'zbek tili"),
      ('uzc', 'Ўзбекча', 'Ўзбекча (кирилл)'),
      ('ru', 'Русский', 'Русский язык'),
      ('ky', 'Кыргызча', 'Кыргыз тили')
    ];
    await showAppSheet<void>(
      context,
      title: tr('Til tanlang'),
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, children: [
        for (final l in langs)
          ListTile(
            key: Key('lang-${l.$1}'),
            minTileHeight: 56,
            contentPadding: EdgeInsets.zero,
            leading: Icon(L.code == l.$1 ? Icons.radio_button_checked : Icons.radio_button_off,
                color: L.code == l.$1 ? AppColors.accentStrong : AppColors.muted),
            title: Text(l.$2, style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(l.$3, style: TextStyle(fontSize: 12, color: AppColors.muted)),
            onTap: () async {
              final nav = Navigator.of(ctx);
              await L.set(l.$1);
              nav.pop();
            },
          ),
      ]),
    );
    if (mounted) setState(() {});
  }

  Future<void> _pickTheme() async {
    await showAppSheet<void>(
      context,
      title: tr('Mavzu tanlang'),
      builder: (ctx) => Wrap(
        spacing: 12,
        runSpacing: 12,
        children: kThemes.map((t) {
          final on = AppTheme.current.id == t.id;
          return GestureDetector(
            onTap: () async {
              final nav = Navigator.of(ctx);
              await AppTheme.set(t.id);
              nav.pop();
            },
            child: SizedBox(
              width: 96,
              child: Column(children: [
                Container(
                  height: 62,
                  decoration: BoxDecoration(
                    color: t.bg,
                    borderRadius: BorderRadius.circular(13),
                    border: Border.all(color: on ? t.accentStrong : t.border, width: on ? 2.4 : 1),
                  ),
                  child: Stack(children: [
                    Positioned(
                        left: 10,
                        top: 12,
                        child: Container(
                            width: 40,
                            height: 8,
                            decoration: BoxDecoration(color: t.accentStrong, borderRadius: BorderRadius.circular(4)))),
                    Positioned(
                        left: 10,
                        top: 26,
                        child: Container(
                            width: 58,
                            height: 6,
                            decoration: BoxDecoration(
                                color: t.card,
                                borderRadius: BorderRadius.circular(3),
                                border: Border.all(color: t.border)))),
                    Positioned(
                        left: 10,
                        top: 38,
                        child: Container(
                            width: 30,
                            height: 6,
                            decoration: BoxDecoration(
                                color: t.card,
                                borderRadius: BorderRadius.circular(3),
                                border: Border.all(color: t.border)))),
                    if (on)
                      Positioned(right: 6, top: 6, child: Icon(Icons.check_circle, size: 17, color: t.accentStrong)),
                  ]),
                ),
                const SizedBox(height: 6),
                Text(tr(t.name),
                    style: TextStyle(
                        fontSize: 12,
                        fontWeight: on ? FontWeight.w800 : FontWeight.w600,
                        color: on ? AppColors.accentStrong : AppColors.text2)),
              ]),
            ),
          );
        }).toList(),
      ),
    );
    if (mounted) setState(() {});
  }

  void _showPermissions() {
    final s = _s;
    final perms = s.permissions.toList()..sort();
    showAppSheet<void>(
      context,
      title: tr('Mening ruxsatlarim'),
      builder: (ctx) =>
          Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        if (s.fullAccess)
          ErrorBanner(
            severity: BannerSeverity.info,
            message:
                trArgs('{role} — barcha ruxsatlarga ega.', {'role': roleLabel(s.roleCode, s.context?.roleName ?? '')}),
          )
        else if (perms.isEmpty)
          Text(tr('Sizga hech qanday ruxsat berilmagan.'), style: TextStyle(color: AppColors.muted))
        else
          for (final p in perms)
            ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 40),
              child: Row(children: [
                const Icon(Icons.check_circle_outline, size: 18, color: AppColors.ok),
                const SizedBox(width: 10),
                Expanded(child: Text(permissionLabel(p), style: const TextStyle(fontSize: 14.5))),
              ]),
            ),
        const SizedBox(height: 12),
        Text(
            tr('Ruxsatlarni ega yoki administrator o‘zgartiradi. O‘zgarish kuchga kirishi uchun «Ma’lumotlarni yangilash» ni bosing.'),
            style: TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.35)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _s,
      builder: (context, _) {
        final s = _s;
        final ctx = s.context;
        final emp = Api.employee ?? const {};
        final name = (ctx?.fullName.isNotEmpty ?? false) ? ctx!.fullName : '${emp['full_name'] ?? emp['name'] ?? ''}';
        final role = roleLabel(s.roleCode, ctx?.roleName ?? '${emp['role_name'] ?? ''}');
        final company = (ctx?.companyName.isNotEmpty ?? false) ? ctx!.companyName : '${emp['company_name'] ?? ''}';
        final branch = s.currentBranch;
        final actor = s.actorBranch;
        final notActor = branch != null && actor != null && !s.currentIsActor;
        final loadedAt = s.loadedAt;
        return Scaffold(
          body: SafeArea(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
              children: [
                Text(tr('Sozlamalar'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                const SizedBox(height: 18),
                // ── Profil ──
                AppCard(
                  key: const Key('settings-profile'),
                  child: Row(children: [
                    CircleAvatar(
                      radius: 26,
                      backgroundColor: AppColors.accentSoft,
                      child: Text(name.isEmpty ? '?' : name.characters.first.toUpperCase(),
                          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: AppColors.accentStrong)),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(name.isEmpty ? tr('Xodim') : name,
                            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                        if (role.isNotEmpty) ...[
                          const SizedBox(height: 2),
                          Text(role,
                              key: const Key('settings-role'),
                              style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                        ],
                        if (company.isNotEmpty) ...[
                          const SizedBox(height: 2),
                          Text(company,
                              key: const Key('settings-company'),
                              style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                        ],
                      ]),
                    ),
                  ]),
                ),
                const SizedBox(height: 16),
                // ── Ish joyi: filial, ruxsatlar, yangilash ──
                _section(tr('Ish joyi')),
                AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Column(children: [
                    _row(
                      Icons.store_mall_directory_outlined,
                      tr('Filial'),
                      branch?.name ?? tr('Filial tanlanmagan'),
                      s.canSwitchBranch,
                      s.canSwitchBranch ? () => showBranchSwitcher(context, session: s) : null,
                      key: const Key('settings-branch'),
                    ),
                    if (notActor)
                      _row(Icons.home_work_outlined, tr('Asosiy filial'), actor.name, false, null,
                          key: const Key('settings-actor-branch'),
                          hint: tr('Tovar qabul va kassa amallari shu filialga yoziladi')),
                    if (branch?.businessDate != null)
                      _row(Icons.event_outlined, tr('Biznes sanasi'), dateDisplay(branch!.businessDate), false, null,
                          key: const Key('settings-business-date')),
                    _row(Icons.verified_user_outlined, tr('Mening ruxsatlarim'),
                        s.fullAccess ? tr('Barchasi') : '${s.permissions.length}', true, _showPermissions,
                        key: const Key('settings-perms')),
                    _row(
                      Icons.sync,
                      tr('Ma’lumotlarni yangilash'),
                      _refreshing ? tr('Yangilanmoqda…') : (loadedAt == null ? '' : hm(loadedAt)),
                      false,
                      _refreshing ? null : _refreshSession,
                      key: const Key('settings-refresh'),
                      last: true,
                    ),
                  ]),
                ),
                if (s.status == SessionStatus.degraded) ...[
                  const SizedBox(height: 10),
                  ErrorBanner(
                    severity: BannerSeverity.warning,
                    message:
                        tr('Server eski versiyada — filial va ruxsatlar kirishdagi holat bo‘yicha ko‘rsatilmoqda.'),
                  ),
                ],
                const SizedBox(height: 16),
                // ── Umumiy ──
                _section(tr('Umumiy')),
                AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Column(children: [
                    if (Perm.allows('employees.list', session: s))
                      _row(Icons.people_outline, tr('Xodimlar'), '', true,
                          () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EmployeesScreen())),
                          key: const Key('settings-employees')),
                    _row(
                        Icons.lock_outline,
                        tr('Xavfsizlik'),
                        tr('Parol'),
                        true,
                        () => Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => const PasswordChangeScreen()))),
                    // Bildirishnomalar — faqat o'qiy oladigan manba bo'lsa (ombor xulosasi / partiya muddati).
                    if (ShellGates.notificationsVisible(session: s))
                      _row(
                          Icons.notifications_outlined,
                          tr('Bildirishnomalar'),
                          '',
                          true,
                          () => Navigator.of(context)
                              .push(MaterialPageRoute(builder: (_) => const NotificationsScreen())),
                          key: const Key('settings-notifications')),
                    _row(Icons.workspace_premium_outlined, tr('Tarif'), '', true,
                        () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const TariffScreen()))),
                    _row(Icons.palette_outlined, tr('Mavzu'), tr(AppTheme.current.name), true, _pickTheme),
                    _row(Icons.language, tr('Til'), L.native, true, _pickLanguage, key: const Key('settings-language')),
                    _row(Icons.dns_outlined, tr('Server manzili'), Uri.tryParse(Api.baseUrl)?.host ?? '', true,
                        _editServer,
                        key: const Key('settings-server'), last: !EnvBadge.visible),
                    // Build-time environment. Shown ONLY in a non-production
                    // build: a production app must say nothing about staging.
                    if (EnvBadge.visible)
                      _row(Icons.science_outlined, tr('Muhit'), EnvBadge.label, false, null,
                          key: const Key('settings-env'), hint: Api.baseUrl, last: true),
                  ]),
                ),
                const SizedBox(height: 16),
                // ── Ilova qulfi — PIN + biometrik ──
                _section(tr('Ilova qulfi')),
                AppCard(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Column(children: [
                    _row(Icons.pin_outlined, tr('PIN kod'), Lock.hasPin ? tr('O‘rnatilgan') : tr('O‘rnatilmagan'), true,
                        _changePin),
                    if (_bioAvail)
                      _switchRow(Icons.fingerprint, tr('Barmoq izi / Face ID'), Lock.biometricOn, _toggleBiometric),
                    _switchRow(Icons.lock_clock_outlined, tr('Ochishda PIN so‘ralsin'), Lock.lockOn, _toggleLock,
                        last: true),
                  ]),
                ),
                const SizedBox(height: 16),
                // ── Chiqish ──
                Material(
                  color: AppColors.card,
                  borderRadius: BorderRadius.circular(16),
                  child: InkWell(
                    key: const Key('settings-logout'),
                    borderRadius: BorderRadius.circular(16),
                    onTap: _logout,
                    child: Container(
                      constraints: const BoxConstraints(minHeight: 60),
                      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                      decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.border)),
                      child: Row(children: [
                        Container(
                            width: 36,
                            height: 36,
                            decoration:
                                BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(10)),
                            child: const Icon(Icons.logout, color: AppColors.danger, size: 18)),
                        const SizedBox(width: 13),
                        Expanded(
                            child: Text(tr('Hisobdan chiqish'),
                                style: const TextStyle(
                                    fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger))),
                      ]),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                Center(
                    child: Text('BinOS mobil${_version.isEmpty ? '' : ' · v$_version'}',
                        style: TextStyle(color: AppColors.faint, fontSize: 12))),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _section(String label) => Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 8),
        child: Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.muted)),
      );

  Widget _row(IconData ic, String label, String value, bool arrow, VoidCallback? onTap,
          {bool last = false, Key? key, String? hint}) =>
      // Shaffof Material: InkWell to'lqini kartaning rangi USTIDA chizilsin (bosilish seziladi).
      Material(
        type: MaterialType.transparency,
        child: InkWell(
          key: key,
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 60),
            padding: const EdgeInsets.symmetric(vertical: 12),
            decoration: BoxDecoration(border: last ? null : Border(bottom: BorderSide(color: AppColors.border))),
            child: Row(children: [
              Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)),
                  child: Icon(ic, color: AppColors.accentStrong, size: 18)),
              const SizedBox(width: 13),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                  if (hint != null) ...[
                    const SizedBox(height: 2),
                    Text(hint, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
                  ],
                ]),
              ),
              if (value.isNotEmpty)
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 170),
                  child: Text(value,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.end,
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                ),
              if (arrow)
                Padding(
                    padding: const EdgeInsets.only(left: 8),
                    child: Icon(Icons.chevron_right, size: 16, color: AppColors.faint)),
            ]),
          ),
        ),
      );

  Widget _switchRow(IconData ic, String label, bool value, ValueChanged<bool> onChanged, {bool last = false}) =>
      Container(
        constraints: const BoxConstraints(minHeight: 60),
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(border: last ? null : Border(bottom: BorderSide(color: AppColors.border))),
        child: Row(children: [
          Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)),
              child: Icon(ic, color: AppColors.accentStrong, size: 18)),
          const SizedBox(width: 13),
          Expanded(child: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
          Switch(value: value, onChanged: onChanged, activeThumbColor: AppColors.accentStrong),
        ]),
      );
}

/// Server address form of the settings sheet. Owns its controller: the sheet's
/// closing animation still rebuilds the field after the value is returned.
class _ServerForm extends StatefulWidget {
  const _ServerForm({required this.initial, required this.warnLogout});
  final String initial;
  final bool warnLogout;

  @override
  State<_ServerForm> createState() => _ServerFormState();
}

class _ServerFormState extends State<_ServerForm> {
  late final TextEditingController _ctl = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        TextField(
          key: const Key('server-url'),
          controller: _ctl,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(hintText: 'https://...'),
        ),
        if (widget.warnLogout) ...[
          const SizedBox(height: 12),
          ErrorBanner(
            severity: BannerSeverity.warning,
            message: tr('Server almashsa, hisobdan chiqasiz va qayta kirishingiz kerak bo‘ladi.'),
          ),
        ],
        const SizedBox(height: 16),
        SizedBox(
          height: kPrimaryButtonHeight,
          child: ElevatedButton(
            key: const Key('server-save'),
            onPressed: () => Navigator.of(context).pop(_ctl.text),
            child: Text(tr('Saqlash')),
          ),
        ),
      ]);
}
