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
  ///
  /// Returns `null` when the result was ACCEPTED, or a refusal text when the
  /// caller could not use it (no permission, a product the server would
  /// refuse …). A refused scan is shown IN the scanner and is NOT counted —
  /// the caller's own screen is buried under this route, so a message left
  /// there would never be read.
  final ScanResultSink? onResult;

  /// App bar title.
  final String? title;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<BarcodeScanScreen> createState() => _BarcodeScanScreenState();
}

/// Continuous-mode result handler: `null` = accepted, a text = refused (shown
/// inside the scanner, not counted). See [BarcodeScanScreen.onResult].
typedef ScanResultSink = FutureOr<String?> Function(ScanResult result);

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
  bool _searching = false;
  Object? _error;
  String? _errorCode;
  ScanResult? _last;
  String? _refused; // the caller refused the last scan (continuous mode)
  int _count = 0;

  // ── Who owns the screen ────────────────────────────────────────────────
  //
  // Exactly ONE outcome may own the screen at a time. A second outcome that
  // finished meanwhile (a code the operator typed waits for the lookup in
  // flight, so two answers CAN arrive close together) would otherwise pop the
  // sheet the first one opened — handing a [ScanResult] to a `Route<String>`
  // (TypeError), losing the product and leaving a scanner nobody can use.
  int _busyDepth = 0;
  Completer<void>? _idleScreen;

  /// True while a sheet or an outcome owns the screen.
  bool get _paused => _busyDepth > 0;

  void _enter() {
    _busyDepth++;
    _idleScreen ??= Completer<void>();
  }

  void _leave() {
    if (--_busyDepth > 0) return;
    _busyDepth = 0;
    final c = _idleScreen;
    _idleScreen = null;
    if (c != null && !c.isCompleted) c.complete();
  }

  /// Waits until nothing owns the screen.
  Future<void> _awaitScreen() async {
    while (_idleScreen != null) {
      await _idleScreen!.future;
    }
  }

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
    // A TYPED code is never dropped: it queues behind whatever owns the screen
    // (the debouncer holds it, and [_handle] waits for the screen). Only
    // camera detections are swallowed while a sheet is open.
    if (_paused && !manual) return;
    final code = ScanService.normalize(raw);
    if (code.isEmpty) return;
    unawaited(_handle(code, manual: manual));
  }

  /// One detection: the SERVER call runs inside the debouncer (one lookup at a
  /// time), the sheets it may open run OUTSIDE it — otherwise the code the
  /// operator types in the "not found" sheet would hit the in-flight guard and
  /// be dropped without a request. A typed code is never dropped at all: it
  /// waits for the lookup in flight (`manual`).
  Future<void> _handle(String code, {bool manual = false}) async {
    final (ran, lookup) = await _debouncer.run<ScanLookup?>(code, () => _lookup(code), manual: manual);
    if (!ran || lookup == null || !mounted || _done) return;
    // The screen may have been taken over while this lookup was running (the
    // other answer's sheet is open): wait for it instead of popping it.
    await _awaitScreen();
    if (!mounted || _done) return;
    _enter();
    try {
      await _outcome(lookup);
    } finally {
      _leave();
    }
  }

  /// The server call. Returns null when it failed (the banner is already shown)
  /// or when the screen is gone (a queued code that resumed after the operator
  /// left must not ask the server, nor touch a dead State).
  Future<ScanLookup?> _lookup(String code) async {
    if (!mounted || _done) return null;
    // The operator may have left while this code waited in the queue: the
    // route is already on its way out even though the State is not unmounted
    // yet. Nothing to ask the server for, and nothing to draw.
    if (ModalRoute.of(context)?.isActive == false) return null;
    setState(() {
      _searching = true;
      _error = null;
      _errorCode = null;
    });
    try {
      final l = await ScanService.lookup(code, branchId: widget.branchId);
      if (mounted) setState(() => _searching = false);
      return l;
    } catch (e) {
      if (mounted) {
        setState(() {
          _searching = false;
          _error = e;
          _errorCode = code;
        });
      }
      return null;
    }
  }

  Future<void> _outcome(ScanLookup l) async {
    switch (l.kind) {
      case ScanKind.barcode:
      case ScanKind.scale:
        if (l.product != null) {
          await _deliver(ScanResult(l, l.product));
        } else {
          await _notFound(l);
        }
      case ScanKind.ambiguous:
        _enter();
        final ScanProduct? chosen;
        try {
          chosen = await _choose(l);
        } finally {
          _leave();
        }
        if (chosen != null) await _deliver(ScanResult(l, chosen));
      case ScanKind.none:
        await _notFound(l);
    }
  }

  Future<void> _deliver(ScanResult r) async {
    if (!mounted || _done) return;
    if (!widget.continuous) {
      // Pop THIS screen's route. The outcome lock keeps it on top; if anything
      // still owns the navigator, the result is not delivered into a foreign
      // route (that would throw and kill the scanner) — the screen stays alive
      // so the operator can scan again.
      if (ModalRoute.of(context)?.isCurrent == false) return;
      _done = true;
      Navigator.of(context).pop(r);
      return;
    }
    _enter();
    String? refused;
    try {
      refused = await widget.onResult?.call(r);
    } finally {
      _leave();
    }
    if (mounted) {
      setState(() {
        _refused = refused;
        if (refused == null) {
          _last = r;
          _count++;
        } else {
          // Not counted: no green check and no tally for an item the caller
          // could not take.
          _last = null;
        }
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
    // ⚠️  Tarozi yorlig'i (server `scale` qaytargan): kodning ichida OG'IRLIK
    //     bor — har qadoqda boshqacha. Uni mahsulotga DOIMIY shtrix-kod qilib
    //     berib bo'lmaydi (aks holda har qadoq "topilmadi" bo'lib, yangi
    //     dublikat mahsulot tug'iladi va POS bilan o'qish farq qiladi), shu
    //     bois «Shu kod bilan davom etish» TAKLIF QILINMAYDI.
    //     Chaqiruvchi ekran (qabul muharriri) ham buni ikkinchi qavat himoya
    //     sifatida rad etadi ([ScanResult.isWeighedLabel]) — lekin birinchi
    //     to'siq shu yerda: operator yorliqni kod sifatida "davom ettira"
    //     olmaydi, qaytadan skanerlaydi yoki kodni qo'lda kiritadi.
    final scale = l.scale;
    _enter();
    final String? action;
    try {
      action = await showAppSheet<String>(
        context,
        title: tr('Mahsulot topilmadi'),
        builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(trArgs('Kod: {code}', {'code': l.code}),
              key: const Key('scan-notfound-code'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(tr('Bu kod bilan mahsulot yo‘q. Kodni tekshiring yoki qayta skanerlang.'),
              style: TextStyle(fontSize: 13.5, color: AppColors.text3)),
          if (scale != null) ...[
            const SizedBox(height: 8),
            Text(
              trArgs(
                  'Bu tarozi yorlig‘i: PLU {plu}, og‘irlik {q} kg. Yorliqdagi kod har qadoqda boshqacha, shuning uchun uni mahsulotga doimiy shtrix-kod qilib bo‘lmaydi. Qadoqning o‘z shtrix-kodini skanerlang yoki PLU {plu} bilan kilogrammli mahsulot oching.',
                  {'plu': scale.plu, 'q': formatMilli(scale.qtyMilli)}),
              key: const Key('scan-scale-label'),
              style: const TextStyle(fontSize: 13.5, color: AppColors.warn),
            ),
          ],
          const SizedBox(height: 16),
          if (widget.allowNotFound && scale == null) ...[
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
    } finally {
      _leave();
    }
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
    _enter();
    final String? v;
    try {
      v = await showAppSheet<String>(
        context,
        title: tr('Kodni qo‘lda kiriting'),
        builder: (ctx) => _ManualCodeSheet(okLabel: widget.lookup ? tr('Qidirish') : tr('OK')),
      );
    } finally {
      _leave();
    }
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
              if (_refused != null) ...[
                ErrorBanner(
                  key: const Key('scan-refused'),
                  severity: BannerSeverity.warning,
                  message: _refused!,
                  onDismiss: () => setState(() => _refused = null),
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
