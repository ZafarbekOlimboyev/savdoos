import 'package:flutter/material.dart';
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
  final _pages = const [AnalyticsScreen(), InventoryScreen(), ReceivingHomeScreen(), SettingsScreen()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _i, children: _pages),
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
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.bar_chart_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.bar_chart, color: AppColors.accentStrong),
                label: 'Analitika',
              ),
              NavigationDestination(
                icon: Icon(Icons.warehouse_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.warehouse, color: AppColors.accentStrong),
                label: 'Ombor',
              ),
              NavigationDestination(
                icon: Icon(Icons.add_box_outlined, color: AppColors.muted),
                selectedIcon: Icon(Icons.add_box, color: AppColors.accentStrong),
                label: 'Qabul',
              ),
              NavigationDestination(
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
