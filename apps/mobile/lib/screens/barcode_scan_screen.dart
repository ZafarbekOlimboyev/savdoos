import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../l10n.dart';
import '../qty.dart';
import '../scan.dart';
import '../theme.dart';
import '../ui/ui.dart';

/// Builds the camera area. Tests inject a fake: call `onCode` to simulate a
/// detection, or return `errorView(code)` to simulate a camera failure.
typedef ScannerViewBuilder = Widget Function(
  BuildContext context,
  ValueChanged<String> onCode,
  Widget Function(MobileScannerErrorCode code) errorView,
);

/// Camera barcode scanner.
///
/// * `BarcodeScanScreen()` — LEGACY raw mode: pops the scanned code (digits
///   only, as before). Existing callers keep working unchanged.
/// * `BarcodeScanScreen.lookup(...)` — resolves the code through the server
///   (`GET /products/scan`) and pops a [ScanResult] (product, scale quantity,
///   operator's choice among ambiguous candidates, or "not found"). With
///   [continuous] the screen stays open and reports each result to [onResult].
///
/// Detections are debounced (same code ignored for 1.5 s, one lookup in
/// flight). A denied camera permission shows an explanation and manual entry.
class BarcodeScanScreen extends StatefulWidget {
  /// Raw mode (legacy): pops `String` digits.
  const BarcodeScanScreen({super.key, this.title, this.scannerBuilder})
      : lookup = false,
        continuous = false,
        allowNotFound = false,
        branchId = null,
        onResult = null;

  /// Lookup mode: pops a [ScanResult] (or reports to [onResult] when [continuous]).
  const BarcodeScanScreen.lookup({
    super.key,
    this.branchId,
    this.continuous = false,
    this.onResult,
    this.allowNotFound = false,
    this.title,
    this.scannerBuilder,
  }) : lookup = true;

  /// Resolve codes on the server.
  final bool lookup;

  /// Keep scanning after each result.
  final bool continuous;

  /// Offer "continue with this code" when nothing matched (new product flow).
  final bool allowNotFound;

  /// Branch for the stock shown in results (default: session's current branch).
  final String? branchId;

  /// Continuous-mode callback (awaited before the next scan is accepted).
  final FutureOr<void> Function(ScanResult result)? onResult;

  /// App bar title.
  final String? title;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<BarcodeScanScreen> createState() => _BarcodeScanScreenState();
}

/// Opens the lookup scanner and returns the resolved [ScanResult] (null if
/// the operator closed it).
Future<ScanResult?> scanProduct(BuildContext context, {String? branchId, bool allowNotFound = false}) =>
    Navigator.of(context).push<ScanResult>(MaterialPageRoute(
      builder: (_) => BarcodeScanScreen.lookup(branchId: branchId, allowNotFound: allowNotFound),
    ));

class _BarcodeScanScreenState extends State<BarcodeScanScreen> with WidgetsBindingObserver {
  MobileScannerController? _ctrl;
  final _debouncer = ScanDebouncer();
  bool _done = false; // popped (single-shot)
  bool _paused = false; // a sheet is open
  bool _searching = false;
  Object? _error;
  String? _errorCode;
  ScanResult? _last;
  int _count = 0;

  @override
  void initState() {
    super.initState();
    if (widget.scannerBuilder == null) {
      _ctrl = MobileScannerController(detectionSpeed: DetectionSpeed.normal, facing: CameraFacing.back);
      WidgetsBinding.instance.addObserver(this);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final c = _ctrl;
    if (c == null) return;
    if (state == AppLifecycleState.resumed) {
      unawaited(c.start().catchError((_) {}));
    } else if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) {
      unawaited(c.stop().catchError((_) {}));
    }
  }

  @override
  void dispose() {
    if (_ctrl != null) WidgetsBinding.instance.removeObserver(this);
    _ctrl?.dispose();
    super.dispose();
  }

  void _onCode(String raw, {bool manual = false}) {
    if (_done || !mounted) return;
    if (!widget.lookup) {
      final digits = raw.replaceAll(RegExp(r'\D'), '');
      if (digits.isEmpty) return;
      _done = true;
      Navigator.of(context).pop(digits);
      return;
    }
    if (_paused) return;
    final code = ScanService.normalize(raw);
    if (code.isEmpty) return;
    if (manual) _debouncer.reset();
    unawaited(_debouncer.run(code, () => _lookup(code)));
  }

  Future<void> _lookup(String code) async {
    setState(() {
      _searching = true;
      _error = null;
      _errorCode = null;
    });
    ScanLookup l;
    try {
      l = await ScanService.lookup(code, branchId: widget.branchId);
    } catch (e) {
      if (mounted) {
        setState(() {
          _searching = false;
          _error = e;
          _errorCode = code;
        });
      }
      return;
    }
    if (!mounted) return;
    setState(() => _searching = false);
    switch (l.kind) {
      case ScanKind.barcode:
      case ScanKind.scale:
        if (l.product != null) {
          await _deliver(ScanResult(l, l.product));
        } else {
          await _notFound(l);
        }
      case ScanKind.ambiguous:
        _paused = true;
        final chosen = await _choose(l);
        _paused = false;
        if (chosen != null) await _deliver(ScanResult(l, chosen));
      case ScanKind.none:
        await _notFound(l);
    }
  }

  Future<void> _deliver(ScanResult r) async {
    if (!mounted || _done) return;
    if (!widget.continuous) {
      _done = true;
      Navigator.of(context).pop(r);
      return;
    }
    _paused = true;
    try {
      await widget.onResult?.call(r);
    } finally {
      _paused = false;
    }
    if (mounted) {
      setState(() {
        _last = r;
        _count++;
      });
    }
  }

  Future<ScanProduct?> _choose(ScanLookup l) => showAppSheet<ScanProduct>(
        context,
        title: tr('Qaysi mahsulot?'),
        builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(
            trArgs('Tarozi kodi PLU {plu} bir nechta mahsulotga mos keladi — to‘g‘risini tanlang.',
                {'plu': l.scale?.plu ?? ''}),
            style: TextStyle(fontSize: 13.5, color: AppColors.text3),
          ),
          if (l.scale != null) ...[
            const SizedBox(height: 4),
            Text(trArgs('Og‘irlik: {q} kg', {'q': formatMilli(l.scale!.qtyMilli)}),
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
          ],
          const SizedBox(height: 8),
          for (final p in l.candidates)
            InkWell(
              key: Key('scan-candidate-${p.id}'),
              onTap: () => Navigator.of(ctx).pop(p),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 56),
                child: Row(children: [
                  Icon(Icons.scale, color: AppColors.accentStrong),
                  const SizedBox(width: 12),
                  Expanded(
                    child:
                        Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                      Text(p.name, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                      Text(
                        [
                          if (p.pluCode != null) 'PLU ${p.pluCode}',
                          p.unitCode,
                          if (!p.isActive) tr('Arxivda'),
                        ].join(' · '),
                        style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                      ),
                    ]),
                  ),
                  Icon(Icons.chevron_right, color: AppColors.muted),
                ]),
              ),
            ),
        ]),
      );

  Future<void> _notFound(ScanLookup l) async {
    _paused = true;
    final action = await showAppSheet<String>(
      context,
      title: tr('Mahsulot topilmadi'),
      builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(trArgs('Kod: {code}', {'code': l.code}),
            key: const Key('scan-notfound-code'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(tr('Bu kod bilan mahsulot yo‘q. Kodni tekshiring yoki qayta skanerlang.'),
            style: TextStyle(fontSize: 13.5, color: AppColors.text3)),
        const SizedBox(height: 16),
        if (widget.allowNotFound) ...[
          SizedBox(
            height: kPrimaryButtonHeight,
            child: ElevatedButton(
              key: const Key('scan-use-code'),
              onPressed: () => Navigator.of(ctx).pop('use'),
              child: Text(tr('Shu kod bilan davom etish')),
            ),
          ),
          const SizedBox(height: 8),
        ],
        SizedBox(
          height: kMinTouch,
          child: OutlinedButton(
            key: const Key('scan-again'),
            onPressed: () => Navigator.of(ctx).pop('again'),
            child: Text(tr('Qayta skanerlash')),
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          height: kMinTouch,
          child: TextButton(
            key: const Key('scan-manual-from-notfound'),
            onPressed: () => Navigator.of(ctx).pop('manual'),
            child: Text(tr('Kodni qo‘lda kiritish')),
          ),
        ),
      ]),
    );
    _paused = false;
    if (!mounted) return;
    if (action == 'use') {
      await _deliver(ScanResult(l, null));
    } else if (action == 'manual') {
      await _manual();
    } else {
      _debouncer.reset();
    }
  }

  Future<void> _manual() async {
    _paused = true;
    final v = await showAppSheet<String>(
      context,
      title: tr('Kodni qo‘lda kiriting'),
      builder: (ctx) => _ManualCodeSheet(okLabel: widget.lookup ? tr('Qidirish') : tr('OK')),
    );
    _paused = false;
    if (v != null && v.trim().isNotEmpty) _onCode(v.trim(), manual: true);
  }

  Widget _errorView(MobileScannerErrorCode code) {
    final (String title, String body) = switch (code) {
      MobileScannerErrorCode.permissionDenied => (
          tr('Kameraga ruxsat berilmagan'),
          tr('Shtrix-kodni skanerlash uchun telefon sozlamalarida ilovaga kamera ruxsatini bering. Hozircha kodni qo‘lda kiritishingiz mumkin.'),
        ),
      MobileScannerErrorCode.unsupported => (
          tr('Kamera skaneri ishlamaydi'),
          tr('Bu qurilmada kamera orqali skanerlab bo‘lmaydi — kodni qo‘lda kiriting.'),
        ),
      _ => (
          tr('Kamerani ishga tushirib bo‘lmadi'),
          tr('Kamera band yoki xato berdi. Qayta urinib ko‘ring yoki kodni qo‘lda kiriting.'),
        ),
    };
    return ColoredBox(
      key: Key('scan-camera-error-${code.name}'),
      color: Colors.black,
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Icon(Icons.no_photography_outlined, color: Colors.white70, size: 48),
            const SizedBox(height: 12),
            Text(title,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            Text(body,
                textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70, fontSize: 14, height: 1.4)),
            const SizedBox(height: 20),
            SizedBox(
              height: kPrimaryButtonHeight,
              child: ElevatedButton.icon(
                key: const Key('scan-error-manual'),
                onPressed: _manual,
                icon: const Icon(Icons.keyboard),
                label: Text(tr('Kodni qo‘lda kiritish')),
              ),
            ),
            if (_ctrl != null && code != MobileScannerErrorCode.unsupported) ...[
              const SizedBox(height: 8),
              SizedBox(
                height: kMinTouch,
                child: OutlinedButton(
                  onPressed: () => unawaited(_ctrl!.start().catchError((_) {})),
                  style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white, side: const BorderSide(color: Colors.white54)),
                  child: Text(tr('Qayta urinish')),
                ),
              ),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _camera(BuildContext context) {
    final b = widget.scannerBuilder;
    if (b != null) return b(context, _onCode, _errorView);
    return MobileScanner(
      controller: _ctrl,
      errorBuilder: (ctx, e, _) => _errorView(e.errorCode),
      onDetect: (capture) {
        for (final bc in capture.barcodes) {
          final raw = bc.rawValue;
          if (raw != null && raw.isNotEmpty) {
            _onCode(raw);
            break;
          }
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    const iconBtn = BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch);
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white, // ekran doim qora — yorug' mavzuda ham oq matn/ikonka
        title: Text(widget.title ?? tr('Shtrix-kodni skanerlang')),
        actions: [
          if (_ctrl != null) ...[
            IconButton(
              tooltip: tr('Chiroq'),
              constraints: iconBtn,
              onPressed: () => unawaited(_ctrl!.toggleTorch().catchError((_) {})),
              icon: const Icon(Icons.flash_on),
            ),
            IconButton(
              tooltip: tr('Kamerani almashtirish'),
              constraints: iconBtn,
              onPressed: () => unawaited(_ctrl!.switchCamera().catchError((_) {})),
              icon: const Icon(Icons.cameraswitch),
            ),
          ],
          if (widget.continuous)
            TextButton(
              key: const Key('scan-done'),
              onPressed: () => Navigator.of(context).pop(),
              style: TextButton.styleFrom(foregroundColor: Colors.white, minimumSize: const Size(kMinTouch, kMinTouch)),
              child: Text(trArgs('Tayyor ({n})', {'n': _count})),
            ),
        ],
      ),
      // SizedBox.expand: Stack TO'LIQ ekran bo'lsin — aks holda u eng katta
      // pozitsiyasiz bola (260×160 ramka) o'lchamiga qisqarib, kamera va tugmalarni kesardi.
      body: SizedBox.expand(
        child: Stack(alignment: Alignment.center, children: [
          Positioned.fill(child: _camera(context)),
          // Nishon ramka
          IgnorePointer(
            child: Container(
              width: 260,
              height: 160,
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.accentStrong, width: 3),
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),
          if (_searching)
            Container(
              key: const Key('scan-searching'),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(12)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                const SizedBox(
                    width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
                const SizedBox(width: 10),
                Text(tr('Qidirilmoqda…'), style: const TextStyle(color: Colors.white)),
              ]),
            ),
          Positioned(
            bottom: 24,
            left: kGutter,
            right: kGutter,
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (_error != null) ...[
                ErrorBanner(
                  error: _error,
                  onRetry: () {
                    final c = _errorCode;
                    if (c != null) _onCode(c, manual: true);
                  },
                ),
                const SizedBox(height: 10),
              ],
              if (_last != null) ...[
                _LastResultCard(result: _last!),
                const SizedBox(height: 10),
              ],
              Text(tr('Kodni ramka ichiga tuting'),
                  style: const TextStyle(color: Colors.white70, fontSize: 13), textAlign: TextAlign.center),
              const SizedBox(height: 12),
              SizedBox(
                height: kMinTouch,
                child: OutlinedButton.icon(
                  key: const Key('scan-manual'),
                  onPressed: _manual,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white54),
                  ),
                  icon: const Icon(Icons.keyboard, size: 18),
                  label: Text(tr('Qo‘lda kiritish')),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _LastResultCard extends StatelessWidget {
  const _LastResultCard({required this.result});
  final ScanResult result;

  @override
  Widget build(BuildContext context) {
    final p = result.product;
    final q = result.qtyMilli;
    return Container(
      key: const Key('scan-last'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(12)),
      child: Row(children: [
        const Icon(Icons.check_circle, color: AppColors.ok),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            p == null
                ? trArgs('Kod: {code}', {'code': result.code})
                : (q == null ? p.name : '${p.name} · ${formatMilli(q)} kg'),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
          ),
        ),
        if (p != null && !p.isActive) Text(tr('Arxivda'), style: const TextStyle(color: AppColors.warn, fontSize: 12)),
      ]),
    );
  }
}

/// Manual code entry; owns its controller so the closing sheet animation
/// never touches a disposed controller.
class _ManualCodeSheet extends StatefulWidget {
  const _ManualCodeSheet({required this.okLabel});
  final String okLabel;

  @override
  State<_ManualCodeSheet> createState() => _ManualCodeSheetState();
}

class _ManualCodeSheetState extends State<_ManualCodeSheet> {
  final _c = TextEditingController();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        TextField(
          key: const Key('scan-manual-field'),
          controller: _c,
          autofocus: true,
          keyboardType: TextInputType.number,
          textInputAction: TextInputAction.search,
          onSubmitted: (t) => Navigator.of(context).pop(t),
          decoration: const InputDecoration(hintText: '4780000000000'),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: kPrimaryButtonHeight,
          child: ElevatedButton(
            key: const Key('scan-manual-ok'),
            onPressed: () => Navigator.of(context).pop(_c.text),
            child: Text(widget.okLabel),
          ),
        ),
      ]);
}
