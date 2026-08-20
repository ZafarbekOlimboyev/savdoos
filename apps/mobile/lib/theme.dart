import 'package:flutter/material.dart';

/// SavdoOS dizayn tokenlari (dark tema + binafsha accent) — desktop ilova bilan bir xil.
class AppColors {
  static const bg = Color(0xFF0F1420);
  static const card = Color(0xFF151B28);
  static const cardAlt = Color(0xFF171D2B);
  static const surface = Color(0xFF1B2230);
  static const border = Color(0xFF232A3A);
  static const borderInput = Color(0xFF2A3242);
  static const accentBorder = Color(0xFF33306A);
  static const warnBorder = Color(0xFF3A3320);

  static const text = Color(0xFFE9EBF2);
  static const text2 = Color(0xFFD7DBE6);
  static const text3 = Color(0xFFAAB2C5);
  static const muted = Color(0xFF8B93A5);
  static const faint = Color(0xFF5E6675);

  static const accent = Color(0xFF6D5DD3);
  static const accentStrong = Color(0xFFA99CF0);
  static const accentSoft = Color(0x2E6D5DD3); // ~0.18 alpha

  static const ok = Color(0xFF35D08A);
  static const okSoft = Color(0x2935D08A);
  static const warn = Color(0xFFE0A53A);
  static const warnSoft = Color(0x29E0A53A);
  static const danger = Color(0xFFF2555A);
  static const dangerSoft = Color(0x29F2555A);
}

ThemeData buildTheme() {
  const accent = AppColors.accent;
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: const ColorScheme.dark(
      primary: accent,
      secondary: accent,
      surface: AppColors.card,
      onSurface: AppColors.text,
      error: AppColors.danger,
    ),
    canvasColor: AppColors.bg,
    cardColor: AppColors.card,
    dividerColor: AppColors.border,
    textTheme: base.textTheme.apply(
      bodyColor: AppColors.text,
      displayColor: AppColors.text,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      elevation: 0,
      foregroundColor: AppColors.text,
      centerTitle: false,
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: Colors.white,
        elevation: 0,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.borderInput),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.borderInput),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: accent, width: 1.5),
      ),
    ),
  );
}

/// Umumiy karta konteyneri.
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? color;
  const AppCard({super.key, required this.child, this.padding = const EdgeInsets.all(18), this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? AppColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: child,
    );
  }
}
