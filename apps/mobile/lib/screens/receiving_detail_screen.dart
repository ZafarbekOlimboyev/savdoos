import 'dart:convert';
import 'package:flutter/material.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';

class ReceivingDetailScreen extends StatefulWidget {
  final String id;
  const ReceivingDetailScreen({super.key, required this.id});
  @override
  State<ReceivingDetailScreen> createState() => _ReceivingDetailScreenState();
}

class _ReceivingDetailScreenState extends State<ReceivingDetailScreen> {
  Future<Map<String, dynamic>>? _future;
  @override
  void initState() {
    super.initState();
    _future = Api.receivingDetail(widget.id);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Qabul tafsiloti'))),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text(snap.error.toString(), style: TextStyle(color: AppColors.muted)));
          }
          final d = snap.data!;
          final items = (d['items'] as List?) ?? [];
          final at = d['at'] == null ? null : DateTime.tryParse(d['at'].toString())?.toLocal();
          final img = d['image_b64']?.toString();
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('${items.length} ta mahsulot · ${qtyStr(_n(d['total_qty']))} birlik',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text('${dmy(at)} · ${d['employee'] ?? ''}${d['source'] == 'demo' ? ' · DEMO' : ''}',
                  style: TextStyle(color: AppColors.muted, fontSize: 12.5)),
              const SizedBox(height: 16),
              AppCard(
                padding: const EdgeInsets.all(6),
                child: Column(
                  children: items.map<Widget>((it) {
                    final m = it as Map;
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                      child: Row(children: [
                        Expanded(child: Text(m['name']?.toString() ?? '', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600))),
                        Text('${qtyStr(_n(m['qty']))} ${m['unit'] ?? ''}',
                            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.accentStrong)),
                      ]),
                    );
                  }).toList(),
                ),
              ),
              if (img != null && img.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(tr('Nakladnoy rasmi'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.memory(base64Decode(img), fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => const SizedBox()),
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  double _n(dynamic v) => v == null ? 0 : (v is num ? v.toDouble() : double.tryParse(v.toString()) ?? 0);
}
