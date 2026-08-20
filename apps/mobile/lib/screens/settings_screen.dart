import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'login_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _urlCtl;

  @override
  void initState() {
    super.initState();
    _urlCtl = TextEditingController(text: Api.baseUrl);
  }

  @override
  void dispose() {
    _urlCtl.dispose();
    super.dispose();
  }

  Future<void> _saveUrl() async {
    await Api.setBaseUrl(_urlCtl.text);
    if (!mounted) return;
    setState(() => _urlCtl.text = Api.baseUrl);
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Server manzili saqlandi')));
  }

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Chiqish'),
        content: const Text('Hisobdan chiqmoqchimisiz?', style: TextStyle(color: AppColors.text3)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Bekor')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Chiqish'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await Api.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  @override
  Widget build(BuildContext context) {
    final emp = Api.employee ?? {};
    final name = (emp['name'] ?? emp['full_name'] ?? 'Xodim').toString();
    final role = (emp['role'] ?? emp['position'] ?? '').toString();
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          children: [
            const Text('Sozlamalar', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: 20),
            // Xodim
            AppCard(
              child: Row(children: [
                Container(
                  width: 48, height: 48,
                  decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(14)),
                  child: const Icon(Icons.person, color: AppColors.accentStrong),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    if (role.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(_roleLabel(role), style: const TextStyle(color: AppColors.muted, fontSize: 13)),
                    ],
                  ]),
                ),
              ]),
            ),
            const SizedBox(height: 22),
            const Text('SERVER MANZILI', style: TextStyle(color: AppColors.muted, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
            const SizedBox(height: 8),
            TextField(
              controller: _urlCtl,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(hintText: 'https://...'),
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _saveUrl,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.accentStrong,
                  side: const BorderSide(color: AppColors.accentBorder),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                icon: const Icon(Icons.save_outlined, size: 18),
                label: const Text('Saqlash'),
              ),
            ),
            const SizedBox(height: 6),
            const Text('Odatda o‘zgartirish shart emas. Faqat o‘z serveringiz bo‘lsa.',
                style: TextStyle(color: AppColors.faint, fontSize: 12)),
            const SizedBox(height: 28),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _logout,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.danger,
                  side: const BorderSide(color: AppColors.dangerSoft),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
                icon: const Icon(Icons.logout, size: 18),
                label: const Text('Hisobdan chiqish'),
              ),
            ),
            const SizedBox(height: 24),
            const Center(child: Text('SavdoOS mobil · v0.1.0', style: TextStyle(color: AppColors.faint, fontSize: 12))),
          ],
        ),
      ),
    );
  }

  String _roleLabel(String r) {
    switch (r.toLowerCase()) {
      case 'admin':
      case 'administrator':
        return 'Administrator';
      case 'owner':
        return 'Egasi';
      case 'manager':
        return 'Menejer';
      case 'cashier':
        return 'Kassir';
      default:
        return r;
    }
  }
}
