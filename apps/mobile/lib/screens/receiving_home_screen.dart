import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/receiving_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../platform/platform.dart';
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

  // One logical operation across receiving screens. An identity ticket keeps
  // an old disposed operation's finally from releasing a newer operation.
  static Object? _activeScan;

  @override
  State<ReceivingHomeScreen> createState() => _ReceivingHomeScreenState();
}

class _ReceivingHomeScreenState extends State<ReceivingHomeScreen> {
  List<ReceivingDoc>? _history;
  Object? _historyError;
  bool _historyLoading = false;
  int _seq = 0;
  Object? _scanTicket;
  AiConsent? _scanRequirement;

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
    final ticket = _scanTicket;
    if (ticket != null) _releaseScan(ticket, notify: false);
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
    return ImageCapture.instance.pick(source); // platforma adapteri (kamera/galereya)
  }

  Future<void> _pick(ImageSource source) async {
    await _runScan(() async {
      final epoch = Api.authEpoch.value;
      final base = Api.baseUrl;
      (List<int>, String)? photo;
      try {
        photo = await _takePhoto(source);
      } catch (e) {
        if (mounted && epoch == Api.authEpoch.value) {
          _snack(tr('Rasmni olib bo‘lmadi — kamera yoki galereyaga ruxsatni tekshiring.'));
        }
        return;
      }
      if (photo == null || !mounted || epoch != Api.authEpoch.value || base != Api.baseUrl) return;
      await _scanAndReview(base64Encode(photo.$1), photo.$2);
    });
  }

  Future<void> _runScan(Future<void> Function() action) async {
    if (!mounted || ReceivingHomeScreen._activeScan != null) return;
    final ticket = Object();
    ReceivingHomeScreen._activeScan = ticket;
    setState(() => _scanTicket = ticket);
    final epoch = Api.authEpoch.value;
    try {
      await action();
    } catch (e) {
      if (mounted && epoch == Api.authEpoch.value) _snack(userMessage(e));
    } finally {
      _releaseScan(ticket);
    }
  }

  void _releaseScan(Object ticket, {bool notify = true}) {
    if (identical(ReceivingHomeScreen._activeScan, ticket)) {
      ReceivingHomeScreen._activeScan = null;
    }
    if (!identical(_scanTicket, ticket)) return;
    if (notify && mounted) {
      setState(() => _scanTicket = null);
    } else {
      _scanTicket = null;
    }
  }

  /// Asks for consent before the photo leaves the shop, naming the real provider.
  ///
  /// Returns true when transmission may proceed. The backend enforces this
  /// independently (`POST /receiving/scan` answers 403 + `AI_CONSENT_REQUIRED`
  /// without consent), so this dialog is the DISCLOSURE, not the control — a
  /// patched client cannot bypass the gate, and Desktop is held to the same rule.
  static const _consentRequired = 'AI orqali o‘qish uchun do‘kon egasi yoki administratorining roziligi kerak. Qatorlarni qo‘lda kiritishingiz mumkin.';
  static const _consentMismatch = 'AI roziligi ma’lumotlari mos emas. Ilovani yangilang yoki qatorlarni qo‘lda kiriting.';

  Future<bool> _ensureAiConsent({bool forceConfirmation = false, VoidCallback? onStatusRetry}) async {
    _scanRequirement = null;
    final nav = Navigator.of(context);
    final epoch = Api.authEpoch.value;
    AiConsent st;
    try {
      st = await ReceivingApi.aiConsentStatus();
    } catch (e) {
      if (mounted && epoch == Api.authEpoch.value) {
        _snack(e is ApiException && e.code == 'BAD_RESPONSE'
            ? tr(_consentMismatch) : userMessage(e), onRetry: onStatusRetry);
      }
      return false;
    }
    if (!mounted || epoch != Api.authEpoch.value) return false;
    if (!st.required_ && !forceConfirmation) {
      _scanRequirement = st;
      return true; // explicit canonical demo
    }
    // This client displays disclosure v1. Never claim acceptance of wording
    // it cannot display, or infer a provider after the scan gate rejected us.
    if (!st.required_ || st.disclosureVersion != 1 ||
        (st.provider?.trim().isEmpty ?? true) ||
        (st.providerName?.trim().isEmpty ?? true)) {
      _snack(tr(_consentMismatch));
      return false;
    }
    if (!st.mustAsk && !forceConfirmation) {
      _scanRequirement = st;
      return true; // exact current revision is on record
    }

    final name = st.providerName ?? tr('tashqi AI xizmati');
    // ⚠️  SCANNING AND CONSENTING ARE DIFFERENT RIGHTS (CH-17A).
    //     Scanning needs `xaridlar.edit`, which `omborchi` has; recording the
    //     consent needs `sozlamalar.edit`, which it does NOT (`seed.py` ROLES —
    //     only `ega`/`administrator` hold it). Sending such an operator a
    //     "I agree" button would answer 403 and look like a bug, so we tell
    //     them who can enable it and keep the manual path in front of them.
    if (!Perm.allows('receiving.ai_consent_grant')) {
      await showDialog<void>(
        context: context,
        builder: (dctx) => AlertDialog(
          title: Text(tr('Rasm tashqi xizmatga yuboriladi')),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(trArgs('Nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.', {'name': name})),
            const SizedBox(height: 10),
            Text(tr('Buni do‘kon egasi yoki administratori bir marta ruxsat berishi kerak.')),
            const SizedBox(height: 10),
            Text(tr('Hozir qatorlarni qo‘lda kiritishingiz mumkin.'),
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          ]),
          actions: [
            FilledButton(
                onPressed: () => Navigator.of(dctx).pop(),
                child: Text(tr('Tushunarli'))),
          ],
        ),
      );
      return false;
    }
    final again = st.previousProvider != null;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dctx) => AlertDialog(
        title: Text(again ? tr('AI xizmati o‘zgardi') : tr('Rasm tashqi xizmatga yuboriladi')),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(again
                ? trArgs('Nakladnoy surati endi {name} ga yuboriladi.', {'name': name})
                : trArgs('Siz tanlagan nakladnoy surati matnini o‘qish uchun {name} ga yuboriladi.',
                    {'name': name})),
            const SizedBox(height: 10),
            Text(tr('Surat faqat o‘qish uchun yuboriladi va qabul tasdiqlangandan keyin saqlanmaydi. Joylashuv kabi qo‘shimcha ma’lumotlar yuborishdan oldin olib tashlanadi.'),
                style: const TextStyle(fontSize: 13)),
            const SizedBox(height: 10),
            Text(tr('Rozi bo‘lmasangiz, qatorlarni qo‘lda kiritish mumkin.'),
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(dctx).pop(false),
              child: Text(tr('Qo‘lda kiritaman'))),
          FilledButton(
              onPressed: () => Navigator.of(dctx).pop(true),
              child: Text(tr('Roziman, yuborilsin'))),
        ],
      ),
    );
    if (ok != true) {
      // Denial is a normal outcome, NOT an error: the manual path stays open.
      if (mounted) _snack(tr('Rasm yuborilmadi. Qatorlarni qo‘lda kiritishingiz mumkin.'));
      return false;
    }
    if (!mounted || epoch != Api.authEpoch.value ||
        !Perm.allows('receiving.ai_consent_grant')) return false;
    try {
      // Helpful early drift check. Atomic enforcement is the conditional POST
      // under the canonical requirement lock, not this extra GET.
      final current = await ReceivingApi.aiConsentStatus();
      if (!mounted || epoch != Api.authEpoch.value) return false;
      if (!current.required_ || !current.sameRequirement(st)) {
        _snack(tr(_consentMismatch));
        return false;
      }
      final granted = await ReceivingApi.grantAiConsent(st);
      if (!mounted || epoch != Api.authEpoch.value) return false;
      if (!granted.required_ || !granted.granted ||
          !granted.sameRequirement(st)) {
        _snack(tr(_consentMismatch));
        return false;
      }
      _scanRequirement = granted;
    } catch (e) {
      if (mounted && epoch == Api.authEpoch.value) {
        _snack(e is ApiException && (e.code == 'AI_CONSENT_REQUIRED' ||
                e.code == 'AI_REQUIREMENT_CHANGED' || e.code == 'BAD_RESPONSE')
                ? tr(_consentMismatch) : userMessage(e));
      }
      return false;
    }
    if (!nav.mounted) return false;
    return true;
  }

  Future<void> _scanAndReview(String b64, String media, {bool forceConsent = false}) async {
    final epoch = Api.authEpoch.value;
    final base = Api.baseUrl;
    // The photo is already chosen; nothing has left the device yet.
    if (!await _ensureAiConsent(
      forceConfirmation: forceConsent,
      onStatusRetry: () {
        if (mounted && epoch == Api.authEpoch.value && base == Api.baseUrl) {
          _runScan(() => _scanAndReview(b64, media, forceConsent: true));
        }
      },
    )) return;
    if (!mounted || epoch != Api.authEpoch.value || base != Api.baseUrl) return;
    final nav = Navigator.of(context, rootNavigator: true);
    AiScan? result;
    for (var attempt = 0; attempt < 2; attempt++) {
      if (!mounted || epoch != Api.authEpoch.value || base != Api.baseUrl) return;
      final loading = DialogRoute<void>(context: context, barrierDismissible: false,
          builder: (_) => const _ScanLoading());
      final loadingClosed = nav.push(loading);
      try {
        try {
          // Closing the loader cancels this logical operation. A request
          // already accepted by the server cannot be recalled; its late
          // result/error is observed by Future.any and cannot reopen review.
          result = await Future.any<AiScan?>([
            ReceivingApi.scanInvoice(b64, media, revision: _scanRequirement!.revision),
            loadingClosed.then<AiScan?>((_) => null),
          ]);
        } finally {
          // Remove only this operation's loader, never another route/dialog.
          if (loading.isActive) nav.removeRoute(loading);
        }
        if (!mounted || epoch != Api.authEpoch.value || result == null) return;
        break;
      } catch (e) {
        if (!mounted || epoch != Api.authEpoch.value) return;
        final needsConsent = e is ApiException &&
            ((e.status == 403 && e.code == 'AI_CONSENT_REQUIRED') ||
             (e.status == 409 && e.code == 'AI_REQUIREMENT_CHANGED'));
        _snack(needsConsent ? tr(_consentRequired) : userMessage(e));
        // A fresh status and an explicit grant are required even when GET
        // previously said granted. Never loop on a second rejection.
        if (!needsConsent || attempt != 0 ||
            !Perm.allows('receiving.ai_consent_grant') ||
            !await _ensureAiConsent(forceConfirmation: true)) return;
      }
    }
    if (!mounted || result == null) return;
    final scan = result;
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

  void _snack(String m, {VoidCallback? onRetry}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(m), action: onRetry == null ? null :
          SnackBarAction(label: tr('Qayta urinish'), onPressed: onRetry)));
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
                        onPressed: _scanTicket != null ? null : () => _pick(ImageSource.camera),
                        icon: const Icon(Icons.photo_camera, size: 20),
                        label: Text(tr('Suratga olish')),
                      ),
                    ),
                    const SizedBox(height: 10),
                    SizedBox(
                      height: kPrimaryButtonHeight,
                      child: OutlinedButton.icon(
                        key: const Key('recv-home-gallery'),
                        onPressed: _scanTicket != null ? null : () => _pick(ImageSource.gallery),
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
    final visible = Session.instance.branches;
    var name = r.branchName ?? '';
    if (name.isEmpty && r.branchId != null) {
      for (final b in visible) {
        if (b.id == r.branchId) name = b.name;
      }
    }
    final branchLabel = visible.length > 1 && name.isNotEmpty ? name : null;
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
                  // `GET /receiving` ko'rinadigan HAMMA filialni qaytaradi —
                  // tepadagi «Qabul filiali» banneri esa faqat AKTOR filialini
                  // ko'rsatadi. Bir nechta filial ko'rinsa, har qator o'z
                  // filialini aytadi (aks holda ro'yxat bitta filialdek o'qiladi).
                  if (branchLabel != null) ...[
                    const SizedBox(height: 2),
                    Text(trArgs('Filial: {name}', {'name': branchLabel}),
                        key: Key('recv-history-branch-${r.id}'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.text2)),
                  ],
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
