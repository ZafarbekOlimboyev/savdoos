import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Fon uslubi — ThemedBackground shu bo'yicha chizadi.
enum BgKind { flat, aurora, ocean, forest, stars }

/// Bitta mavzu (skin): fon + kartalar + matn + urg'u rangi birga.
class ThemePalette {
  final String id;
  final String name; // ko'rsatiladigan nom (o'zbekcha)
  final bool dark;
  final BgKind bgKind;
  final Color bg, card, cardAlt, surface, border, borderInput, accentBorder;
  final Color text, text2, text3, muted, faint;
  final Color accent, accentStrong;
  final int accentSoftAlpha; // accent ustiga alpha (0..255) — accentSoft
  final Color glowA, glowB; // aurora/stars uchun yog'du ranglari
  const ThemePalette({
    required this.id, required this.name, required this.dark, required this.bgKind,
    required this.bg, required this.card, required this.cardAlt, required this.surface,
    required this.border, required this.borderInput, required this.accentBorder,
    required this.text, required this.text2, required this.text3, required this.muted, required this.faint,
    required this.accent, required this.accentStrong, required this.accentSoftAlpha,
    this.glowA = const Color(0x006D5DD3), this.glowB = const Color(0x0014B8A6),
  });
}

// ── 9 mavzu ──────────────────────────────────────────────────────────────
const _dkText = Color(0xFFE9EBF2), _dkT2 = Color(0xFFD7DBE6), _dkT3 = Color(0xFFAAB2C5),
    _dkMuted = Color(0xFF8B93A5), _dkFaint = Color(0xFF5E6675);

const List<ThemePalette> kThemes = [
  // Tungi (joriy)
  ThemePalette(
    id: 'tungi', name: 'Tungi', dark: true, bgKind: BgKind.flat,
    bg: Color(0xFF0F1420), card: Color(0xFF151B28), cardAlt: Color(0xFF171D2B), surface: Color(0xFF1B2230),
    border: Color(0xFF232A3A), borderInput: Color(0xFF2A3242), accentBorder: Color(0xFF33306A),
    text: _dkText, text2: _dkT2, text3: _dkT3, muted: _dkMuted, faint: _dkFaint,
    accent: Color(0xFF6D5DD3), accentStrong: Color(0xFFA99CF0), accentSoftAlpha: 46),
  // Aurora
  ThemePalette(
    id: 'aurora', name: 'Aurora', dark: true, bgKind: BgKind.aurora,
    bg: Color(0xFF0F1420), card: Color(0xFF151B28), cardAlt: Color(0xFF171D2B), surface: Color(0xFF1B2230),
    border: Color(0xFF232A3A), borderInput: Color(0xFF2A3242), accentBorder: Color(0xFF3A3770),
    text: _dkText, text2: _dkT2, text3: _dkT3, muted: _dkMuted, faint: _dkFaint,
    accent: Color(0xFF6D5DD3), accentStrong: Color(0xFFC5B9FF), accentSoftAlpha: 46,
    glowA: Color(0xFF6D5DD3), glowB: Color(0xFF14B8A6)),
  // Okean
  ThemePalette(
    id: 'okean', name: 'Okean', dark: true, bgKind: BgKind.ocean,
    bg: Color(0xFF0A1E33), card: Color(0xFF0E2A44), cardAlt: Color(0xFF103150), surface: Color(0xFF123A58),
    border: Color(0xFF1C4A6E), borderInput: Color(0xFF23557A), accentBorder: Color(0xFF1C5A80),
    text: Color(0xFFE7F2FA), text2: Color(0xFFCFE0EC), text3: Color(0xFF9FC0D6), muted: Color(0xFF7FA3BC), faint: Color(0xFF4E6E86),
    accent: Color(0xFF0EA5E9), accentStrong: Color(0xFF56C5F5), accentSoftAlpha: 41),
  // O'rmon
  ThemePalette(
    id: 'ormon', name: "O'rmon", dark: true, bgKind: BgKind.forest,
    bg: Color(0xFF0A1D16), card: Color(0xFF0E2A20), cardAlt: Color(0xFF103026), surface: Color(0xFF123A2C),
    border: Color(0xFF164A38), borderInput: Color(0xFF1C5A44), accentBorder: Color(0xFF1C6A4E),
    text: Color(0xFFE4F3EC), text2: Color(0xFFC9E4D6), text3: Color(0xFF9BC4B2), muted: Color(0xFF7CA894), faint: Color(0xFF4E7562),
    accent: Color(0xFF10B981), accentStrong: Color(0xFF4FE0A0), accentSoftAlpha: 41),
  // Grafit
  ThemePalette(
    id: 'grafit', name: 'Grafit', dark: true, bgKind: BgKind.flat,
    bg: Color(0xFF17181C), card: Color(0xFF202228), cardAlt: Color(0xFF24262E), surface: Color(0xFF26282F),
    border: Color(0xFF2E313A), borderInput: Color(0xFF363945), accentBorder: Color(0xFF2E313A),
    text: Color(0xFFEBEDF2), text2: Color(0xFFD4D7DE), text3: Color(0xFFA2A7B2), muted: Color(0xFF9096A2), faint: Color(0xFF62666F),
    accent: Color(0xFF3B82F6), accentStrong: Color(0xFF7FB0FF), accentSoftAlpha: 41),
  // Kosmos
  ThemePalette(
    id: 'kosmos', name: 'Kosmos', dark: true, bgKind: BgKind.stars,
    bg: Color(0xFF0B1030), card: Color(0xFF141636), cardAlt: Color(0xFF171A3E), surface: Color(0xFF1B1E48),
    border: Color(0xFF262A5A), borderInput: Color(0xFF2E3268), accentBorder: Color(0xFF2C2F66),
    text: Color(0xFFEAECFB), text2: Color(0xFFD3D6EE), text3: Color(0xFFAAB0D6), muted: Color(0xFF8B92BC), faint: Color(0xFF5B618C),
    accent: Color(0xFF6366F1), accentStrong: Color(0xFF8B9CFF), accentSoftAlpha: 51,
    glowA: Color(0xFF6366F1), glowB: Color(0xFF8B5CF6)),
  // Sof oq (kunduzgi)
  ThemePalette(
    id: 'oq', name: 'Sof oq', dark: false, bgKind: BgKind.flat,
    bg: Color(0xFFF4F6FB), card: Color(0xFFFFFFFF), cardAlt: Color(0xFFF7F8FC), surface: Color(0xFFEEF1F7),
    border: Color(0xFFE6E9F2), borderInput: Color(0xFFDBE0EA), accentBorder: Color(0xFFDAD3F7),
    text: Color(0xFF141A28), text2: Color(0xFF263042), text3: Color(0xFF4A5468), muted: Color(0xFF6B7385), faint: Color(0xFF9AA2B2),
    accent: Color(0xFF6D5DD3), accentStrong: Color(0xFF6D5DD3), accentSoftAlpha: 26),
  // Osmon (kunduzgi ko'k)
  ThemePalette(
    id: 'osmon', name: 'Osmon', dark: false, bgKind: BgKind.flat,
    bg: Color(0xFFEEF4FF), card: Color(0xFFFFFFFF), cardAlt: Color(0xFFF5F8FE), surface: Color(0xFFE7EEFB),
    border: Color(0xFFE1E9F5), borderInput: Color(0xFFD4E0F2), accentBorder: Color(0xFFCFE0FB),
    text: Color(0xFF12203A), text2: Color(0xFF22344F), text3: Color(0xFF47597A), muted: Color(0xFF5B6B85), faint: Color(0xFF93A2BA),
    accent: Color(0xFF2563EB), accentStrong: Color(0xFF2563EB), accentSoftAlpha: 26),
  // Yalpiz (kunduzgi yashil)
  ThemePalette(
    id: 'yalpiz', name: 'Yalpiz', dark: false, bgKind: BgKind.flat,
    bg: Color(0xFFEFF7F3), card: Color(0xFFFFFFFF), cardAlt: Color(0xFFF4FAF7), surface: Color(0xFFE4F1EB),
    border: Color(0xFFDCEDE4), borderInput: Color(0xFFCDE6DA), accentBorder: Color(0xFFC3E7D6),
    text: Color(0xFF0F2A22), text2: Color(0xFF1E3E33), text3: Color(0xFF47695B), muted: Color(0xFF5A7A6C), faint: Color(0xFF93B2A4),
    accent: Color(0xFF0E9F6E), accentStrong: Color(0xFF0E9F6E), accentSoftAlpha: 26),
];

/// SavdoOS dizayn tokenlari. Struktura/matn/urg'u ranglari MUTABLE — mavzu almashsa
/// AppTheme.apply() ularni yangilaydi. Status ranglari (ok/warn/danger) const — o'zgarmaydi.
class AppColors {
  // Mavzuga qarab o'zgaradiganlar (dastlab Tungi):
  static Color bg = kThemes[0].bg;
  static Color card = kThemes[0].card;
  static Color cardAlt = kThemes[0].cardAlt;
  static Color surface = kThemes[0].surface;
  static Color border = kThemes[0].border;
  static Color borderInput = kThemes[0].borderInput;
  static Color accentBorder = kThemes[0].accentBorder;
  static Color text = kThemes[0].text;
  static Color text2 = kThemes[0].text2;
  static Color text3 = kThemes[0].text3;
  static Color muted = kThemes[0].muted;
  static Color faint = kThemes[0].faint;
  static Color accent = kThemes[0].accent;
  static Color accentStrong = kThemes[0].accentStrong;
  static Color accentSoft = kThemes[0].accent.withAlpha(kThemes[0].accentSoftAlpha);

  // O'zgarmaydigan (status) ranglar:
  // warnBorder: warn rangining shaffof varianti — yorug' mavzuda ham to'g'ri ko'rinadi
  // (ilgari qattiq to'q-qo'ng'ir 0xFF3A3320 edi — oq fonda deyarli qora ramka bo'lardi)
  static const warnBorder = Color(0x55E0A53A);
  static const ok = Color(0xFF35D08A);
  static const okSoft = Color(0x2935D08A);
  static const warn = Color(0xFFE0A53A);
  static const warnSoft = Color(0x29E0A53A);
  static const danger = Color(0xFFF2555A);
  static const dangerSoft = Color(0x29F2555A);
}

/// Joriy mavzuni boshqaradi (til tizimidagi L kabi). Almashganda butun app qayta quriladi.
class AppTheme {
  static ThemePalette current = kThemes[0];
  static final ValueNotifier<int> version = ValueNotifier(0);

  static Future<void> load() async {
    try {
      final p = await SharedPreferences.getInstance();
      final id = p.getString('savdoos_theme') ?? 'tungi';
      _apply(kThemes.firstWhere((t) => t.id == id, orElse: () => kThemes[0]));
    } catch (_) {
      _apply(kThemes[0]);
    }
  }

  static Future<void> set(String id) async {
    _apply(kThemes.firstWhere((t) => t.id == id, orElse: () => kThemes[0]));
    version.value++;
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString('savdoos_theme', id);
    } catch (_) {}
  }

  static void _apply(ThemePalette t) {
    current = t;
    AppColors.bg = t.bg;
    AppColors.card = t.card;
    AppColors.cardAlt = t.cardAlt;
    AppColors.surface = t.surface;
    AppColors.border = t.border;
    AppColors.borderInput = t.borderInput;
    AppColors.accentBorder = t.accentBorder;
    AppColors.text = t.text;
    AppColors.text2 = t.text2;
    AppColors.text3 = t.text3;
    AppColors.muted = t.muted;
    AppColors.faint = t.faint;
    AppColors.accent = t.accent;
    AppColors.accentStrong = t.accentStrong;
    AppColors.accentSoft = t.accent.withAlpha(t.accentSoftAlpha);
  }
}

ThemeData buildTheme() {
  final t = AppTheme.current;
  final accent = AppColors.accent;
  final base = t.dark ? ThemeData.dark(useMaterial3: true) : ThemeData.light(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: Colors.transparent, // fon ThemedBackground orqali chiziladi
    colorScheme: (t.dark ? const ColorScheme.dark() : const ColorScheme.light()).copyWith(
      primary: accent,
      secondary: accent,
      surface: AppColors.card,
      onSurface: AppColors.text,
      error: AppColors.danger,
    ),
    canvasColor: Colors.transparent,
    cardColor: AppColors.card,
    dividerColor: AppColors.border,
    textTheme: base.textTheme.apply(bodyColor: AppColors.text, displayColor: AppColors.text),
    appBarTheme: AppBarTheme(
      backgroundColor: Colors.transparent,
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
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: AppColors.borderInput)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: AppColors.borderInput)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: accent, width: 1.5)),
    ),
  );
}

/// Butun ilova ortidagi fon — joriy mavzuga qarab (tekis/aurora/gradient/yulduzli).
/// MaterialApp.builder orqali barcha ekranlar ortida turadi.
class ThemedBackground extends StatelessWidget {
  final Widget child;
  const ThemedBackground({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    final t = AppTheme.current;
    switch (t.bgKind) {
      case BgKind.flat:
        return ColoredBox(color: t.bg, child: child);
      case BgKind.ocean:
        return _gradient(const [Color(0xFF0C2E4A), Color(0xFF0A1E33), Color(0xFF081726)]);
      case BgKind.forest:
        return _gradient(const [Color(0xFF0A2C20), Color(0xFF0A1D16), Color(0xFF08130F)]);
      case BgKind.aurora:
        return _glowBg(t);
      case BgKind.stars:
        return _starsBg(t);
    }
  }

  Widget _gradient(List<Color> colors) => DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: colors),
        ),
        child: child,
      );

  Widget _glowBg(ThemePalette t) => Stack(children: [
        Positioned.fill(child: ColoredBox(color: t.bg)),
        Positioned(top: -80, left: -60, child: _glow(t.glowA, 260)),
        Positioned(top: 90, right: -70, child: _glow(t.glowB, 240)),
        Positioned.fill(child: child),
      ]);

  Widget _starsBg(ThemePalette t) => Stack(children: [
        Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter, end: Alignment.bottomCenter,
                colors: [t.bg, const Color(0xFF070814)],
              ),
            ),
          ),
        ),
        Positioned.fill(child: CustomPaint(painter: _StarPainter())),
        Positioned(top: -70, right: -60, child: _glow(t.glowA, 240)),
        Positioned.fill(child: child),
      ]);

  Widget _glow(Color c, double size) => IgnorePointer(
        child: Container(
          width: size, height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(colors: [c.withAlpha(90), c.withAlpha(0)]),
          ),
        ),
      );
}

/// Yulduzlar — barqaror (seed bilan), rebuild'da joyi o'zgarmaydi.
class _StarPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final rnd = math.Random(42);
    final paint = Paint()..color = Colors.white;
    for (var i = 0; i < 70; i++) {
      final dx = rnd.nextDouble() * size.width;
      final dy = rnd.nextDouble() * size.height;
      final r = rnd.nextDouble() * 1.1 + 0.3;
      paint.color = Colors.white.withAlpha((rnd.nextDouble() * 120 + 40).round());
      canvas.drawCircle(Offset(dx, dy), r, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StarPainter oldDelegate) => false;
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
