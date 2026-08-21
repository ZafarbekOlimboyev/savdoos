import 'package:flutter/material.dart';
import '../theme.dart';

class TariffScreen extends StatelessWidget {
  const TariffScreen({super.key});

  static const _plans = [
    ('Start', '1 filial · POS · asosiy hisobot', false),
    ('Start+', 'Ko\'p filial · analitika · nasiya · qo\'llab-quvvatlash', true),
    ('Business', 'Cheksiz filial · to\'liq analitika · API · prioritet', false),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Tarif')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.accentBorder)),
            child: Row(children: const [
              Icon(Icons.verified, size: 20, color: AppColors.accentStrong),
              SizedBox(width: 10),
              Expanded(child: Text('Tarifni o‘zgartirish uchun SavdoOS bilan bog‘laning', style: TextStyle(fontSize: 13, color: AppColors.text2, fontWeight: FontWeight.w500))),
            ]),
          ),
          const SizedBox(height: 16),
          ..._plans.map((p) => _card(p.$1, p.$2, p.$3)),
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
                child: const Text('Joriy', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white)),
              ),
          ]),
          const SizedBox(height: 8),
          Text(desc, style: const TextStyle(fontSize: 12.5, color: AppColors.muted, height: 1.5)),
        ]),
      );
}
