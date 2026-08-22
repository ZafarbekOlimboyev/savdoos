import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'login_screen.dart';
import 'notifications_screen.dart';
import 'password_change_screen.dart';
import 'tariff_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr('Chiqish')),
        content: Text(tr('Hisobdan chiqmoqchimisiz?'), style: const TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(tr('Bekor'))),
          ElevatedButton(style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger), onPressed: () => Navigator.pop(context, true), child: Text(tr('Chiqish'))),
        ],
      ),
    );
    if (ok != true) return;
    await Api.logout();
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
    const langs = [('uz', 'O‘zbekcha', "O'zbek tili"), ('ru', 'Русский', 'Русский язык'), ('ky', 'Кыргызча', 'Кыргыз тили')];
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
                subtitle: Text(l.$3, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
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
                CircleAvatar(radius: 26, backgroundColor: AppColors.accentSoft, child: Text(name.isEmpty ? '?' : name[0], style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: AppColors.accentStrong))),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    if (role.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(role, style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
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
                _row(Icons.language, tr('Til'), L.native, true, _pickLanguage),
                _row(Icons.dns_outlined, tr('Server manzili'), '', true, _editServer, last: true),
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
            const Center(child: Text('SavdoOS mobil · v0.2.7', style: TextStyle(color: AppColors.faint, fontSize: 12))),
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
          decoration: BoxDecoration(border: last ? null : const Border(bottom: BorderSide(color: AppColors.border))),
          child: Row(children: [
            Container(width: 36, height: 36, decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(10)), child: Icon(ic, color: AppColors.accentStrong, size: 18)),
            const SizedBox(width: 13),
            Expanded(child: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
            if (value.isNotEmpty) Text(value, style: const TextStyle(fontSize: 12.5, color: AppColors.muted)),
            if (arrow) const Padding(padding: EdgeInsets.only(left: 8), child: Icon(Icons.chevron_right, size: 16, color: AppColors.faint)),
          ]),
        ),
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
