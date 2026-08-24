import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../api.dart';
import '../format.dart';
import '../l10n.dart';
import '../theme.dart';
import 'receiving_review_screen.dart';
import 'receiving_detail_screen.dart';
import 'manual_receiving_screen.dart';

class ReceivingHomeScreen extends StatefulWidget {
  const ReceivingHomeScreen({super.key});
  @override
  State<ReceivingHomeScreen> createState() => _ReceivingHomeScreenState();
}

class _ReceivingHomeScreenState extends State<ReceivingHomeScreen> {
  final _picker = ImagePicker();
  Future<List<ReceivingRow>>? _history;

  @override
  void initState() {
    super.initState();
    _history = Api.history();
  }

  void _reloadHistory() => setState(() => _history = Api.history());

  Future<void> _pick(ImageSource source) async {
    try {
      final XFile? f = await _picker.pickImage(source: source, imageQuality: 70, maxWidth: 1800);
      if (f == null) return;
      final bytes = await f.readAsBytes();
      final b64 = base64Encode(bytes);
      final media = (f.mimeType != null && f.mimeType!.startsWith('image/')) ? f.mimeType! : 'image/jpeg';
      if (!mounted) return;
      _scanAndReview(b64, media);
    } catch (e) {
      _snack('Rasm olishda xato: $e');
    }
  }

  Future<void> _scanAndReview(String b64, String media) async {
    showDialog(context: context, barrierDismissible: false, builder: (_) => const _ScanLoading());
    try {
      final items = await Api.scan(b64, media);
      if (!mounted) return;
      Navigator.of(context).pop(); // loading
      if (items.isEmpty) {
        _snack(tr('Hujjatdan mahsulot topilmadi. Aniqroq suratga oling.'));
        return;
      }
      final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(
        builder: (_) => ReceivingReviewScreen(items: items, imageB64: b64, source: Api.lastSource),
      ));
      if (ok == true) _reloadHistory();
    } catch (e) {
      if (mounted) Navigator.of(context).pop();
      _snack('AI o‘qishda xato: $e');
    }
  }

  void _snack(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => _reloadHistory(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            children: [
              Text(tr('Tovar qabul qilish'), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
              const SizedBox(height: 24),
              // Asosiy action
              Column(children: [
                Container(
                  width: 76, height: 76,
                  decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(20)),
                  child: const Icon(Icons.inventory_2, color: AppColors.accentStrong, size: 38),
                ),
                const SizedBox(height: 16),
                Text(tr('Nakladnoyni suratga oling'),
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700), textAlign: TextAlign.center),
                const SizedBox(height: 6),
                Text(tr('Mahsulot nomi va miqdorini avtomatik o‘qiymiz'),
                    style: const TextStyle(color: AppColors.muted, fontSize: 13), textAlign: TextAlign.center),
              ]),
              const SizedBox(height: 26),
              ElevatedButton.icon(
                onPressed: () => _pick(ImageSource.camera),
                icon: const Icon(Icons.photo_camera, size: 20),
                label: Text(tr('Suratga olish')),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => _pick(ImageSource.gallery),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.text2,
                  side: const BorderSide(color: AppColors.borderInput),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                icon: const Icon(Icons.image_outlined, size: 20),
                label: Text(tr('Galereyadan tanlash')),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () async {
                  final ok = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(builder: (_) => const ManualReceivingScreen()));
                  if (ok == true) _reloadHistory();
                },
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.text2,
                  side: const BorderSide(color: AppColors.borderInput),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                icon: const Icon(Icons.edit_note, size: 22),
                label: Text(tr('Qo‘lda kirim')),
              ),
              const SizedBox(height: 32),
              // Tarix
              Row(children: [
                Text(tr('So‘nggi qabullar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              ]),
              const SizedBox(height: 10),
              FutureBuilder<List<ReceivingRow>>(
                future: _history,
                builder: (context, snap) {
                  if (snap.connectionState == ConnectionState.waiting) {
                    return const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator()));
                  }
                  final rows = snap.data ?? [];
                  if (rows.isEmpty) {
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 20),
                      child: Text(tr('Hali qabul qilinmagan'), style: const TextStyle(color: AppColors.muted)),
                    );
                  }
                  return Column(children: rows.map((r) => _historyRow(r)).toList());
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _historyRow(ReceivingRow r) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReceivingDetailScreen(id: r.id))),
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(
                width: 38, height: 38,
                decoration: BoxDecoration(color: AppColors.okSoft, borderRadius: BorderRadius.circular(10)),
                child: const Icon(Icons.check, color: AppColors.ok, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${r.totalTypes} ta mahsulot · ${qtyStr(r.totalQty)} birlik',
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text('${hm(r.at)} · ${r.employee}', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              const Icon(Icons.chevron_right, color: AppColors.faint),
            ]),
          ),
        ),
      ),
    );
  }
}

class _ScanLoading extends StatelessWidget {
  const _ScanLoading();
  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AppColors.card,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.description_outlined, color: AppColors.accentStrong, size: 40),
          const SizedBox(height: 18),
          Text(tr('Hujjat o‘qilmoqda...'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text(tr('AI mahsulotlarni aniqlaydi'), style: const TextStyle(color: AppColors.muted, fontSize: 13)),
          const SizedBox(height: 20),
          const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2.5)),
        ]),
      ),
    );
  }
}
