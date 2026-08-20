import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'analytics_screen.dart';
import 'inventory_screen.dart';
import 'receiving_home_screen.dart';
import 'settings_screen.dart';

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _i = 0;
  int _attention = 0; // kam qolgan + tugagan — Ombor tab badge'i

  @override
  void initState() {
    super.initState();
    Api.invAlerts()
        .then((r) => mounted ? setState(() => _attention = r.$1 + r.$2) : null)
        .catchError((_) {});
  }

  Widget _omborIcon(bool selected) {
    final icon = Icon(selected ? Icons.warehouse : Icons.warehouse_outlined,
        color: selected ? AppColors.accentStrong : AppColors.muted);
    if (_attention <= 0) return icon;
    return Badge(
      label: Text('$_attention'),
      backgroundColor: AppColors.danger,
      child: icon,
    );
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      AnalyticsScreen(onTab: (i) => setState(() => _i = i)),
      const InventoryScreen(),
      const ReceivingHomeScreen(),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: _i, children: pages),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          color: AppColors.card,
          border: Border(top: BorderSide(color: AppColors.border)),
        ),
        child: NavigationBarTheme(
          data: NavigationBarThemeData(
            backgroundColor: AppColors.card,
            indicatorColor: AppColors.accentSoft,
            labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: s.contains(WidgetState.selected) ? AppColors.accentStrong : AppColors.muted,
                )),
          ),
          child: NavigationBar(
            height: 66,
            selectedIndex: _i,
            onDestinationSelected: (v) => setState(() => _i = v),
            destinations: [
              const NavigationDestination(
                icon: Icon(Icons.bar_chart_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.bar_chart, color: AppColors.accentStrong),
                label: 'Analitika',
              ),
              NavigationDestination(
                icon: _omborIcon(false),
                selectedIcon: _omborIcon(true),
                label: 'Ombor',
              ),
              const NavigationDestination(
                icon: Icon(Icons.add_box_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.add_box, color: AppColors.accentStrong),
                label: 'Qabul',
              ),
              const NavigationDestination(
                icon: Icon(Icons.settings_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.settings, color: AppColors.accentStrong),
                label: 'Sozlama',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
