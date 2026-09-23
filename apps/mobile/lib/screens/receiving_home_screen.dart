import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api/receiving_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'manual_receiving_screen.dart';
import 'receiving_detail_screen.dart';
import 'receiving_review_screen.dart';
import 'receiving_widgets.dart';

/// Picks an invoice photo; tests replace it (`(source) async => (bytes, mime)`).
typedef RecvImagePicker = Future<(List<int>, String)?> Function(ImageSource source);

/// Tovar qabul: AI (nakladnoy surati), qo'lda kirim va so'nggi qabullar tarixi.
///
/// Ruxsatlar (server bilan AYNI): yangi kirim va AI skan `xaridlar.edit`,
/// tarix va hujjat `xaridlar.view`. Ruxsat bo'lmagan qism ko'rsatilmaydi.
class ReceivingHomeScreen extends StatefulWidget {
  /// Creates the screen.
  const ReceivingHomeScreen({super.key});

  /// Photo picker override (tests).
  @visibleForTesting
  static RecvImagePicker? debugPicker;

  @override
  State<ReceivingHomeScreen> createState() => _ReceivingHomeScreenState();
}

class _ReceivingHomeScreenState extends State<ReceivingHomeScreen> {
  final _picker = ImagePicker();
  List<ReceivingDoc>? _history;
  Object? _historyError;
  bool _historyLoading = false;
  int _seq = 0;

  bool get _canCommit => Perm.allows('receiving.commit');
  bool get _canScan => Perm.allows('receiving.scan');
  bool get _canHistory => Perm.allows('receiving.history');

  @override
  void initState() {
    super.initState();
    Session.instance.addListener(_onSession);
    if (_canHistory) _loadHistory();
  }

  @override
  void dispose() {
    Session.instance.removeListener(_onSession);
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    setState(() {});
    if (_canHistory && _history == null && !_historyLoading) _loadHistory();
  }

  Future<void> _loadHistory() async {
    final seq = ++_seq;
    setState(() {
      _historyLoading = true;
      _historyError = null;
    });
    try {
      final h = await ReceivingApi.history();
      if (!mounted || seq != _seq) return;
      setState(() {
        _history = h;
        _historyLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _historyError = e;
        _historyLoading = false;
      });
    }
  }

  Future<(List<int>, String)?> _takePhoto(ImageSource source) async {
    final dbg = ReceivingHomeScreen.debugPicker;
    if (dbg != null) return dbg(source);
    final XFile? f = await _picker.pickImage(source: source, imageQuality: 70, maxWidth: 1800);
    if (f == null) return null;
    final bytes = await f.readAsBytes();
    final media = (f.mimeType != null && f.mimeType!.startsWith('image/')) ? f.mimeType! : 'image/jpeg';
    return (bytes, media);
  }

  Future<void> _pick(ImageSource source) async {
    (List<int>, String)? photo;
    try {
      photo = await _takePhoto(source);
    } catch (e) {
      _snack(tr('Rasmni olib bo‘lmadi — kamera yoki galereyaga ruxsatni tekshiring.'));
      return;
    }
    if (photo == null || !mounted) return;
    await _scanAndReview(base64Encode(photo.$1), photo.$2);
  }

  Future<void> _scanAndReview(String b64, String media) async {
    final nav = Navigator.of(context);
    showDialog<void>(context: context, barrierDismissible: false, builder: (_) => const _ScanLoading());
    AiScan scan;
    try {
      scan = await ReceivingApi.scanInvoice(b64, media);
    } catch (e) {
      if (mounted) nav.pop();
      if (mounted) _snack(userMessage(e));
      return;
    }
    if (!mounted) return;
    nav.pop(); // loading
    if (scan.items.isEmpty) {
      _snack(tr('Hujjatdan mahsulot topilmadi. Aniqroq suratga oling.'));
      return;
    }
    final ok = await nav.push<bool>(MaterialPageRoute(
      builder: (_) => ReceivingReviewScreen(scan: scan, imageB64: b64),
    ));
    if (ok == true && _canHistory) _loadHistory();
  }

  Future<void> _manual() async {
    final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const ManualReceivingScreen()));
    if (ok == true && _canHistory) _loadHistory();
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m)));
  }

  @override
  Widget build(BuildContext context) {
    final canCommit = _canCommit, canScan = _canScan, canHistory = _canHistory;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Tovar qabul qilish'))),
      body: SafeArea(
        child: Column(children: [
          const ConnectivityBanner(),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                if (canHistory) await _loadHistory();
              },
              child: ListView(
                padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
                children: [
                  if (canCommit || canScan) ...[
                    const ReceivingBranchBanner(),
                    const SizedBox(height: 18),
                  ],
                  if (canScan) ...[
                    Center(
                      child: Container(
                        width: 72,
                        height: 72,
                        decoration: BoxDecoration(color: AppColors.accentSoft, borderRadius: BorderRadius.circular(20)),
                        child: Icon(Icons.inventory_2, color: AppColors.accentStrong, size: 36),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(tr('Nakladnoyni suratga oling'),
                        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700), textAlign: TextAlign.center),
                    const SizedBox(height: 4),
                    Text(tr('Mahsulot nomi va miqdorini avtomatik o‘qiymiz'),
                        style: TextStyle(color: AppColors.muted, fontSize: 13), textAlign: TextAlign.center),
                    const SizedBox(height: 18),
                    SizedBox(
                      height: kPrimaryButtonHeight,
                      child: ElevatedButton.icon(
                        key: const Key('recv-home-camera'),
                        onPressed: () => _pick(ImageSource.camera),
                        icon: const Icon(Icons.photo_camera, size: 20),
                        label: Text(tr('Suratga olish')),
                      ),
                    ),
                    const SizedBox(height: 10),
                    SizedBox(
                      height: kPrimaryButtonHeight,
                      child: OutlinedButton.icon(
                        key: const Key('recv-home-gallery'),
                        onPressed: () => _pick(ImageSource.gallery),
                        icon: const Icon(Icons.image_outlined, size: 20),
                        label: Text(tr('Galereyadan tanlash')),
                      ),
                    ),
                    const SizedBox(height: 10),
                  ],
                  if (canCommit)
                    SizedBox(
                      height: kPrimaryButtonHeight,
                      child: OutlinedButton.icon(
                        key: const Key('recv-home-manual'),
                        onPressed: _manual,
                        icon: const Icon(Icons.edit_note, size: 22),
                        label: Text(tr('Qo‘lda kirim')),
                      ),
                    ),
                  if (!canCommit && !canScan)
                    ErrorBanner(
                      key: const Key('recv-home-no-edit'),
                      severity: BannerSeverity.info,
                      message: '${tr('Kirim qilish uchun ruxsatingiz yo‘q.')} ${Perm.reason('receiving.commit')}',
                    ),
                  const SizedBox(height: 26),
                  if (canHistory) ..._historySection() else if (canCommit || canScan)
                    Text(tr('Qabullar tarixini ko‘rish uchun ruxsat yo‘q.'),
                        key: const Key('recv-home-no-history'), style: TextStyle(color: AppColors.muted, fontSize: 13)),
                ],
              ),
            ),
          ),
        ]),
      ),
    );
  }

  List<Widget> _historySection() {
    final h = _history;
    final out = <Widget>[
      Row(children: [
        Expanded(child: Text(tr('So‘nggi qabullar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700))),
        if (_historyLoading && h != null)
          const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
      ]),
      const SizedBox(height: 10),
    ];
    if (_historyError != null) {
      out.add(ErrorBanner(key: const Key('recv-history-error'), error: _historyError, onRetry: _loadHistory));
      out.add(const SizedBox(height: 10));
    }
    if (h == null) {
      if (_historyError == null) {
        out.add(const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())));
      }
      return out;
    }
    if (h.isEmpty) {
      out.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 20),
        child: Text(tr('Hali qabul qilinmagan'), style: TextStyle(color: AppColors.muted)),
      ));
      return out;
    }
    out.addAll(h.map(_historyRow));
    return out;
  }

  Widget _historyRow(ReceivingDoc r) {
    final title = [
      if ((r.docNo ?? '').isNotEmpty) r.docNo!,
      if ((r.supplier ?? '').isNotEmpty) r.supplier!,
    ].join(' · ');
    final sub = [
      trArgs('{n} ta mahsulot', {'n': r.totalTypes}),
      formatMilli(r.totalQtyMilli, group: true),
      '${dmy(r.at)} · ${r.employee}',
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          key: Key('recv-history-${r.id}'),
          borderRadius: BorderRadius.circular(14),
          onTap: Perm.allows('receiving.detail')
              ? () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReceivingDetailScreen(id: r.id)))
              : null,
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: AppColors.border)),
            child: Row(children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                    color: r.cancelled ? AppColors.dangerSoft : AppColors.okSoft, borderRadius: BorderRadius.circular(10)),
                child: Icon(r.cancelled ? Icons.block : Icons.check,
                    color: r.cancelled ? AppColors.danger : AppColors.ok, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title.isEmpty ? tr('Kirim') : title,
                      maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              if (r.payment != RecvPayment.unknown) ...[
                const SizedBox(width: 6),
                RecvBadge(recvPaymentLabel(r.payment), color: r.payment == RecvPayment.credit ? AppColors.warn : AppColors.ok),
              ],
              if (r.cancelled) ...[
                const SizedBox(width: 6),
                RecvBadge(tr('Bekor qilingan'), color: AppColors.danger),
              ],
              Icon(Icons.chevron_right, color: AppColors.faint),
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
          Icon(Icons.description_outlined, color: AppColors.accentStrong, size: 40),
          const SizedBox(height: 18),
          Text(tr('Hujjat o‘qilmoqda...'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text(tr('AI mahsulotlarni aniqlaydi'), style: TextStyle(color: AppColors.muted, fontSize: 13)),
          const SizedBox(height: 20),
          const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2.5)),
        ]),
      ),
    );
  }
}
