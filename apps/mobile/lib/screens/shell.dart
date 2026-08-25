import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
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
      body: Column(children: [
        Expanded(child: IndexedStack(index: _i, children: pages)),
        // Offline banner — server javob bermasa ko'rinadi
        ValueListenableBuilder<bool>(
          valueListenable: Api.online,
          builder: (context, online, _) => online
              ? const SizedBox.shrink()
              : Container(
                  width: double.infinity,
                  color: AppColors.warn,
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    const Icon(Icons.cloud_off, size: 14, color: Colors.white),
                    const SizedBox(width: 7),
                    Text(tr('Oflayn — internet yo‘q'), style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                  ]),
                ),
        ),
      ]),
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

// Telegram uslubidagi suzuvchi kapsula bar: chetlardan ajralgan pill, faol tab
// orqasida SUZIB o'tadigan tanlov pufagi (easeOutBack — "suyuq" his), badge'lar,
// o'ngda alohida dumaloq "+" (Amal) tugmasi.
class _BottomBar extends StatelessWidget {
  final int current, attention;
  final void Function(int) onTab;
  final VoidCallback onAmal;
  const _BottomBar({required this.current, required this.attention, required this.onTab, required this.onAmal});

  static const _tabs = [
    (Icons.home_outlined, Icons.home, 'Bosh'),
    (Icons.bar_chart_outlined, Icons.bar_chart, 'Analitika'),
    (Icons.warehouse_outlined, Icons.warehouse, 'Ombor'),
    (Icons.settings_outlined, Icons.settings, 'Sozlama'),
  ];

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).padding.bottom;
    return Container(
      color: Colors.transparent,
      padding: EdgeInsets.fromLTRB(12, 8, 12, (bottom > 0 ? bottom : 10)),
      child: Row(children: [
        // ── Kapsula (4 tab + suzuvchi pufak) ──
        Expanded(
          child: Container(
            height: 62,
            decoration: BoxDecoration(
              color: AppColors.card.withValues(alpha: 0.96),
              borderRadius: BorderRadius.circular(31),
              border: Border.all(color: AppColors.border),
              boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.22), blurRadius: 18, offset: const Offset(0, 6))],
            ),
            child: LayoutBuilder(builder: (context, cons) {
              final cellW = cons.maxWidth / _tabs.length;
              return Stack(children: [
                // Tanlov pufagi — tab'lar orasida suzib o'tadi
                AnimatedPositioned(
                  duration: const Duration(milliseconds: 380),
                  curve: Curves.easeOutBack,
                  left: current * cellW + 5,
                  top: 5,
                  width: cellW - 10,
                  height: 52,
                  child: Container(
                    decoration: BoxDecoration(
                      color: AppColors.accentSoft,
                      borderRadius: BorderRadius.circular(26),
                    ),
                  ),
                ),
                Row(children: [for (var i = 0; i < _tabs.length; i++) _tab(i)]),
              ]);
            }),
          ),
        ),
        const SizedBox(width: 10),
        // ── Alohida dumaloq Amal (+) tugmasi ──
        GestureDetector(
          onTap: onAmal,
          child: Container(
            width: 62, height: 62,
            decoration: BoxDecoration(
              color: AppColors.accent,
              shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: AppColors.accent.withValues(alpha: 0.45), blurRadius: 16, offset: const Offset(0, 5))],
            ),
            child: const Icon(Icons.add, color: Colors.white, size: 30),
          ),
        ),
      ]),
    );
  }

  Widget _tab(int i) {
    final (off, on, label) = _tabs[i];
    final sel = current == i;
    final color = sel ? AppColors.accentStrong : AppColors.muted;
    final badge = i == 2 ? attention : 0;
    Widget icon = AnimatedScale(
      scale: sel ? 1.06 : 1.0,
      duration: const Duration(milliseconds: 250),
      child: Icon(sel ? on : off, color: color, size: 22),
    );
    if (badge > 0) {
      icon = Badge(label: Text('$badge'), backgroundColor: AppColors.danger, child: icon);
    }
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onTab(i),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          icon,
          const SizedBox(height: 3),
          Text(tr(label), style: TextStyle(fontSize: 10.5, fontWeight: sel ? FontWeight.w700 : FontWeight.w600, color: color)),
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
          Text(tr('Yangi operatsiya'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 14),
          _row(Icons.document_scanner, tr('Tovar qabul'), tr('Nakladnoyni skanerlash'), AppColors.ok, onReceiving),
          _row(Icons.remove_circle_outline, tr('Hisobdan chiqarish'), tr('Brak, muddati o‘tgan'), AppColors.danger, onWriteoff),
          _row(Icons.fact_check_outlined, tr('Inventarizatsiya'), tr('Qoldiqni sanash'), AppColors.warn, onInventory),
          _row(Icons.account_balance_wallet_outlined, tr('Kassa kirim / chiqim'), tr('Naqd pul harakati'), AppColors.accentStrong, onCash),
          _row(Icons.swap_horiz, tr('Filiallararo transfer'), tr('Do‘konlar orasida'), AppColors.accentStrong, onTransfer),
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
                Text(sub, style: TextStyle(fontSize: 12, color: AppColors.muted)),
              ]),
            ),
            Icon(Icons.chevron_right, color: AppColors.faint),
          ]),
        ),
      );
}
