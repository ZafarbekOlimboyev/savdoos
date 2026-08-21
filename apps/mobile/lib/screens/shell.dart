import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'analytics_screen.dart';
import 'cash_ops_screen.dart';
import 'home_screen.dart';
import 'inventory_screen.dart';
import 'inventarizatsiya_screen.dart';
import 'receiving_home_screen.dart';
import 'settings_screen.dart';
import 'transfer_screen.dart';
import 'writeoff_screen.dart';

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _i = 0; // 0=Bosh 1=Analitika 2=Ombor 3=Sozlama
  int _attention = 0;

  @override
  void initState() {
    super.initState();
    Api.invAlerts().then((r) => mounted ? setState(() => _attention = r.$1 + r.$2) : null).catchError((_) {});
  }

  void _go(int i) => setState(() => _i = i);

  @override
  Widget build(BuildContext context) {
    final pages = [
      HomeScreen(onTab: _go),
      AnalyticsScreen(onTab: _go),
      const InventoryScreen(),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: _i, children: pages),
      bottomNavigationBar: _BottomBar(current: _i, attention: _attention, onTab: _go, onAmal: _openAmal),
    );
  }

  void _openAmal() {
    void nav(Widget screen) {
      Navigator.pop(context);
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
    }

    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
      builder: (_) => _AmalSheet(
        onReceiving: () => nav(const ReceivingHomeScreen()),
        onWriteoff: () => nav(const WriteoffScreen()),
        onInventory: () => nav(const InventarizatsiyaScreen()),
        onCash: () => nav(const CashOpsScreen()),
        onTransfer: () => nav(const TransferScreen()),
      ),
    );
  }
}

class _BottomBar extends StatelessWidget {
  final int current, attention;
  final void Function(int) onTab;
  final VoidCallback onAmal;
  const _BottomBar({required this.current, required this.attention, required this.onTab, required this.onAmal});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 66 + MediaQuery.of(context).padding.bottom,
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).padding.bottom),
      decoration: const BoxDecoration(
        color: AppColors.card,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: Row(children: [
        _tab(0, Icons.home_outlined, Icons.home, 'Bosh'),
        _tab(1, Icons.bar_chart_outlined, Icons.bar_chart, 'Analitika'),
        Expanded(child: Center(child: _amalBtn())),
        _tab(2, Icons.warehouse_outlined, Icons.warehouse, 'Ombor', badge: attention),
        _tab(3, Icons.settings_outlined, Icons.settings, 'Sozlama'),
      ]),
    );
  }

  Widget _amalBtn() => GestureDetector(
        onTap: onAmal,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Transform.translate(
            offset: const Offset(0, -14),
            child: Container(
              width: 52, height: 52,
              decoration: BoxDecoration(
                color: AppColors.accent, borderRadius: BorderRadius.circular(16),
                boxShadow: [BoxShadow(color: AppColors.accent.withValues(alpha: 0.5), blurRadius: 18, offset: const Offset(0, 6))],
              ),
              child: const Icon(Icons.add, color: Colors.white, size: 28),
            ),
          ),
          Transform.translate(
            offset: const Offset(0, -18),
            child: const Text('Amal', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AppColors.accentStrong)),
          ),
        ]),
      );

  Widget _tab(int i, IconData off, IconData on, String label, {int badge = 0}) {
    final sel = current == i;
    final color = sel ? AppColors.accentStrong : AppColors.muted;
    Widget icon = Icon(sel ? on : off, color: color, size: 22);
    if (badge > 0) {
      icon = Badge(label: Text('$badge'), backgroundColor: AppColors.danger, child: icon);
    }
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onTab(i),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          icon,
          const SizedBox(height: 4),
          Text(label, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color)),
        ]),
      ),
    );
  }
}

class _AmalSheet extends StatelessWidget {
  final VoidCallback onReceiving, onWriteoff, onInventory, onCash, onTransfer;
  const _AmalSheet({required this.onReceiving, required this.onWriteoff, required this.onInventory,
      required this.onCash, required this.onTransfer});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)))),
          const SizedBox(height: 16),
          const Text('Yangi operatsiya', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 14),
          _row(Icons.document_scanner, 'Tovar qabul', 'Nakladnoyni skanerlash', AppColors.ok, onReceiving),
          _row(Icons.remove_circle_outline, 'Hisobdan chiqarish', 'Brak, muddati o‘tgan', AppColors.danger, onWriteoff),
          _row(Icons.fact_check_outlined, 'Inventarizatsiya', 'Qoldiqni sanash', AppColors.warn, onInventory),
          _row(Icons.account_balance_wallet_outlined, 'Kassa kirim / chiqim', 'Naqd pul harakati', AppColors.accentStrong, onCash),
          _row(Icons.swap_horiz, 'Filiallararo transfer', 'Do‘konlar orasida', AppColors.accentStrong, onTransfer),
        ]),
      ),
    );
  }

  Widget _row(IconData ic, String title, String sub, Color c, VoidCallback onTap) => GestureDetector(
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
          child: Row(children: [
            Container(
              width: 44, height: 44,
              decoration: BoxDecoration(color: c.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
              child: Icon(ic, color: c, size: 22),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                Text(sub, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
              ]),
            ),
            const Icon(Icons.chevron_right, color: AppColors.faint),
          ]),
        ),
      );
}
