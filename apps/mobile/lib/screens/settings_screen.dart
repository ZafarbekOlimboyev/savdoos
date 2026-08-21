import 'package:flutter/material.dart';
import '../api.dart';
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
        title: const Text('Chiqish'),
        content: const Text('Hisobdan chiqmoqchimisiz?', style: TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Bekor')),
          ElevatedButton(style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger), onPressed: () => Navigator.pop(context, true), child: const Text('Chiqish')),
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
        title: const Text('Server manzili'),
        content: TextField(controller: ctl, keyboardType: TextInputType.url, autocorrect: false, decoration: const InputDecoration(hintText: 'https://...')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Bekor')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Saqlash')),
        ],
      ),
    );
    if (ok == true) {
      await Api.setBaseUrl(ctl.text);
      if (mounted) setState(() {});
    }
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
            const Text('Sozlamalar', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
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
                _row(Icons.lock_outline, 'Xavfsizlik', 'Parol', true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PasswordChangeScreen()))),
                _row(Icons.notifications_outlined, 'Bildirishnomalar', '', true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const NotificationsScreen()))),
                _row(Icons.workspace_premium_outlined, 'Tarif', '', true,
                    () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const TariffScreen()))),
                _row(Icons.language, 'Til', 'O‘zbekcha', false, () {}),
                _row(Icons.dns_outlined, 'Server manzili', '', true, _editServer, last: true),
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
                  const Expanded(child: Text('Hisobdan chiqish', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.danger))),
                ]),
              ),
            ),
            const SizedBox(height: 20),
            const Center(child: Text('SavdoOS mobil · v0.2.0', style: TextStyle(color: AppColors.faint, fontSize: 12))),
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
        return 'Administrator';
      case 'menejer':
      case 'manager':
        return 'Menejer';
      case 'omborchi':
        return 'Omborchi';
      case 'kassir':
      case 'cashier':
        return 'Kassir';
      default:
        return r;
    }
  }
}
