import 'package:flutter/material.dart';
import '../api.dart';
import '../l10n.dart';
import '../theme.dart';

/// Joriy tarif SERVERDAN olinadi (ilgari qattiq 'Start+' belgilangan edi).
class TariffScreen extends StatefulWidget {
  const TariffScreen({super.key});
  @override
  State<TariffScreen> createState() => _TariffScreenState();
}

class _TariffScreenState extends State<TariffScreen> {
  String? _plan; // start | start+ | business (null = yuklanmoqda)

  static const _plans = [
    ('start', 'Start', '1 filial · POS · asosiy hisobot'),
    ('start+', 'Start+', 'Ko\'p filial · analitika · nasiya · qo\'llab-quvvatlash'),
    ('business', 'Business', 'Cheksiz filial · to\'liq analitika · API · prioritet'),
  ];

  @override
  void initState() {
    super.initState();
    Api.plan().then((p) => mounted ? setState(() => _plan = p) : null);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Tarif'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.accentBorder)),
            child: Row(children: [
              Icon(Icons.verified, size: 20, color: AppColors.accentStrong),
              const SizedBox(width: 10),
              Expanded(child: Text(tr('Tarifni o‘zgartirish uchun SavdoOS bilan bog‘laning'), style: TextStyle(fontSize: 13, color: AppColors.text2, fontWeight: FontWeight.w500))),
            ]),
          ),
          const SizedBox(height: 16),
          ..._plans.map((p) => _card(p.$2, p.$3, _plan != null && _plan == p.$1)),
        ],
      ),
    );
  }

  Widget _card(String name, String desc, bool current) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: current ? AppColors.accent : AppColors.border, width: current ? 2 : 1),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            const SizedBox(width: 10),
            if (current)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
                decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(7)),
                child: Text(tr('Joriy'), style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white)),
              ),
          ]),
          const SizedBox(height: 8),
          Text(tr(desc), style: TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.5)),
        ]),
      );
}
