import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../lock.dart';
import '../theme.dart';
import 'login_screen.dart';
import 'notifications_screen.dart';
import 'password_change_screen.dart';
import 'pin_screens.dart';
import 'tariff_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _bioAvail = false;

  @override
  void initState() {
    super.initState();
    Lock.biometricAvailable().then((v) {
      if (mounted) setState(() => _bioAvail = v);
    });
  }

  Future<void> _changePin() async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => PinSetupScreen(onDone: () => Navigator.of(context).pop())));
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

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr('Chiqish')),
        content: Text(tr('Hisobdan chiqmoqchimisiz?'), style: TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Bekor'))),
          ElevatedButton(style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger), onPressed: () => Navigator.pop(context, true), child: Text(tr('Chiqish'))),
        ],
      ),
    );
    if (ok != true) return;
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  Future<void> _editServer() async {
    final ctl = TextEditingController(text: Api.baseUrl);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr('Server manzili')),
        content: TextField(controller: ctl, keyboardType: TextInputType.url, autocorrect: false, decoration: const InputDecoration(hintText: 'https://...')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Bekor'))),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: Text(tr('Saqlash'))),
        ],
      ),
    );
    if (ok == true) {
      await Api.setBaseUrl(ctl.text);
      if (mounted) setState(() {});
    }
  }

  Future<void> _pickLanguage() async {
    const langs = [('uz', 'O‘zbekcha', "O'zbek tili"), ('uzc', 'Ўзбекча', 'Ўзбекча (кирилл)'), ('ru', 'Русский', 'Русский язык'), ('ky', 'Кыргызча', 'Кыргыз тили')];
    await showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(height: 12),
          Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2))),
          Padding(padding: const EdgeInsets.all(16), child: Align(alignment: Alignment.centerLeft, child: Text(tr('Til tanlang'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)))),
          ...langs.map((l) => ListTile(
                leading: Icon(L.code == l.$1 ? Icons.radio_button_checked : Icons.radio_button_off, color: L.code == l.$1 ? AppColors.accentStrong : AppColors.muted),
                title: Text(l.$2, style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text(l.$3, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                onTap: () async {
                  await L.set(l.$1);
                  if (context.mounted) Navigator.pop(context);
                },
              )),
          const SizedBox(height: 12),
        ]),
      ),
    );
    if (mounted) setState(() {});
  }

  Future<void> _pickTheme() async {
    await showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
            const SizedBox(height: 14),
            Text(tr('Mavzu tanlang'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
            const SizedBox(height: 14),
            Wrap(spacing: 12, runSpacing: 12, children: kThemes.map((t) {
              final on = AppTheme.current.id == t.id;
              return GestureDetector(
                onTap: () async {
                  await AppTheme.set(t.id);
                  if (context.mounted) Navigator.pop(context);
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
                        Positioned(left: 10, top: 12, child: Container(width: 40, height: 8, decoration: BoxDecoration(color: t.accentStrong, borderRadius: BorderRadius.circular(4)))),
                        Positioned(left: 10, top: 26, child: Container(width: 58, height: 6, decoration: BoxDecoration(color: t.card, borderRadius: BorderRadius.circular(3), border: Border.all(color: t.border)))),
                        Positioned(left: 10, top: 38, child: Container(width: 30, height: 6, decoration: BoxDecoration(color: t.card, borderRadius: BorderRadius.circular(3), border: Border.all(color: t.border)))),
                        if (on) Positioned(right: 6, top: 6, child: Icon(Icons.check_circle, size: 17, color: t.accentStrong)),
                      ]),
                    ),
                    const SizedBox(height: 6),
                    Text(t.name, style: TextStyle(fontSize: 12, fontWeight: on ? FontWeight.w800 : FontWeight.w600, color: on ? AppColors.accentStrong : AppColors.text2)),
                  ]),
                ),
              );
            }).toList()),
          ]),
        ),
      ),
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final emp = Api.employee ?? {};
    final name = (emp['name'] ?? emp['full_name'] ?? 'Xodim').toString();
    final role = _roleLabel((emp['role'] ?? emp['role_code'] ?? '').toString());
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          children: [
            Text(tr('Sozlamalar'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: 18),
            // Profil
            AppCard(
              child: Row(children: [
                CircleAvatar(radius: 26, backgroundColor: AppColors.accentSoft, child: Text(name.isEmpty ? '?' : name[0], style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: AppColors.accentStrong))),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    if (role.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(role, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                    ],
                  ]),
                ),
              ]),
            ),
            const SizedBox(height: 16),
            // Qatorlar
            AppCard(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(children: [
                _row(Icons.lock_outline, tr('Xavfsizlik'), tr('Parol'), true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PasswordChangeScreen()))),
                _row(Icons.notifications_outlined, tr('Bildirishnomalar'), '', true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const NotificationsScreen()))),
                _row(Icons.workspace_premium_outlined, tr('Tarif'), '', true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const TariffScreen()))),
                _row(Icons.palette_outlined, tr('Mavzu'), AppTheme.current.name, true, _pickTheme),
                _row(Icons.language, tr('Til'), L.native, true, _pickLanguage),
                _row(Icons.dns_outlined, tr('Server manzili'), '', true, _editServer, last: true),
              ]),
            ),
            const SizedBox(height: 16),
            // Ilova qulfi — PIN + biometrik
            Padding(padding: const EdgeInsets.only(left: 4, bottom: 8), child: Text(tr('Ilova qulfi'), style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.muted))),
            AppCard(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(children: [
                _row(Icons.pin_outlined, tr('PIN kod'), Lock.hasPin ? tr('O‘rnatilgan') : tr('O‘rnatilmagan'), true, _changePin),
                if (_bioAvail)
                  _switchRow(Icons.fingerprint, tr('Barmoq izi / Face ID'), Lock.biometricOn, _toggleBiometric),
                _switchRow(Icons.lock_clock_outlined, tr('Ochishda PIN so‘ralsin'), Lock.lockOn, _toggleLock, last: true),
              ]),
            ),
            const SizedBox(height: 16),
            // Chiqish
            GestureDetector(
              onTap: _logout,
              child: AppCard(
                child: Row(children: [
                  Container(width: 36, height: 36, decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(10)), child: const Icon(Icons.logout, color: AppColors.danger, size: 18)),
                  const SizedBox(width: 13),
                  Expanded(child: Text(tr('Hisobdan chiqish'), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger))),
                ]),
              ),
            ),
            const SizedBox(height: 20),
            Center(child: Text('SavdoOS mobil · v0.5.5', style: TextStyle(color: AppColors.faint, fontSize: 12))),
          ],
        ),
      ),
    );
  }

  Widget _row(IconData ic, String label, String value, bool arrow, VoidCallback onTap, {bool last = false}) => GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(border: last ? null : Border(bottom: BorderSide(color: AppColors.border))),
          child: Row(children: [
            Container(width: 36, height: 36, decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)), child: Icon(ic, color: AppColors.accentStrong, size: 18)),
            const SizedBox(width: 13),
            Expanded(child: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
            if (value.isNotEmpty) Text(value, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
            if (arrow) Padding(padding: EdgeInsets.only(left: 8), child: Icon(Icons.chevron_right, size: 16, color: AppColors.faint)),
          ]),
        ),
      );

  Widget _switchRow(IconData ic, String label, bool value, ValueChanged<bool> onChanged, {bool last = false}) => Container(
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(border: last ? null : Border(bottom: BorderSide(color: AppColors.border))),
        child: Row(children: [
          Container(width: 36, height: 36, decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)), child: Icon(ic, color: AppColors.accentStrong, size: 18)),
          const SizedBox(width: 13),
          Expanded(child: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
          Switch(value: value, onChanged: onChanged, activeColor: AppColors.accentStrong),
        ]),
      );

  String _roleLabel(String r) {
    switch (r.toLowerCase()) {
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
        return r;
    }
  }
}
