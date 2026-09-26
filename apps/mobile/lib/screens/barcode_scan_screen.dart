import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n.dart';
import '../platform/platform.dart';
import '../qty.dart';
import '../scan.dart';
import '../theme.dart';
import '../ui/ui.dart';

/// Builds the camera area. Tests inject a fake: call `onCode` to simulate a
/// detection, or return `errorView(code)` to simulate a camera failure.
/// The default camera comes from the [Scanner] platform adapter.
typedef ScannerViewBuilder = Widget Function(
  BuildContext context,
  ValueChanged<String> onCode,
  Widget Function(ScanErrorCode code) errorView,
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

/// The phone's own "this app's permissions" page.
///
/// Android denies a permission the operator has refused twice WITHOUT showing
/// a dialog, so asking again can never succeed and the only way back is the
/// system settings page. This is the door to it.
///
/// It is deliberately capability-checked rather than platform-checked: where
/// the channel is not implemented (iOS today, and the browser, where site
/// permissions live only in Safari's own UI) [available] answers `false` and
/// the UI offers no button — the app never shows a control it cannot honour.
///
/// NOTE (C2 → B4): this belongs in `lib/platform/` next to the other adapters.
/// It lives here because `lib/platform/**` is another package's file in this
/// phase; moving it is a mechanical follow-up.
class AppSettingsLink {
  /// Creates the default implementation.
  const AppSettingsLink();

  /// The active implementation (tests normally mock the channel instead).
  @visibleForTesting
  static AppSettingsLink instance = const AppSettingsLink();

  /// Name of the platform channel (`MainActivity.kt` answers it on Android).
  static const String channelName = 'savdoos/app_settings';

  static const MethodChannel _ch = MethodChannel(channelName);

  /// Whether this platform has an app-settings page we can open.
  /// Never throws: an unimplemented channel means "no".
  Future<bool> available() async {
    try {
      return await _ch.invokeMethod<bool>('supported') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// Opens the page. Returns whether it really opened.
  Future<bool> open() async {
    try {
      return await _ch.invokeMethod<bool>('open') ?? false;
    } catch (_) {
      return false;
    }
  }
}

/// Opens the lookup scanner and returns the resolved [ScanResult] (null if
/// the operator closed it).
Future<ScanResult?> scanProduct(BuildContext context, {String? branchId, bool allowNotFound = false}) =>
    Navigator.of(context).push<ScanResult>(MaterialPageRoute(
      builder: (_) => BarcodeScanScreen.lookup(branchId: branchId, allowNotFound: allowNotFound),
    ));

class _BarcodeScanScreenState extends State<BarcodeScanScreen> with WidgetsBindingObserver {
  // The real camera (null when a `scannerBuilder` is injected). The session's
  // controls are best-effort and never throw; `_lifecycle` collapses Android's
  // inactive→hidden→paused and web's inactive→hidden into ONE stop / ONE start.
  Scanner? _scanner;
  ScannerSession? _cam;
  final _lifecycle = LifecycleGate();
  final _debouncer = ScanDebouncer();
  bool _done = false; // popped (single-shot)
  bool _searching = false;
  Object? _error;
  String? _errorCode;
  ScanResult? _last;
  String? _refused; // the caller refused the last scan (continuous mode)
  int _count = 0;
  bool _canOpenSettings = false; // this phone has an app-permissions page
  ScanErrorCode? _camError; // the camera's LAST failure (null = the preview is live)
  bool _restarting = false; // a replacement session is being opened

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
      final s = Scanner.instance;
      _scanner = s;
      _cam = s.open();
      WidgetsBinding.instance.addObserver(this);
    }
    // Asked once, before any denial: the error view must be able to decide
    // synchronously whether it may offer the Settings button.
    unawaited(AppSettingsLink.instance.available().then((v) {
      if (mounted && v != _canOpenSettings) setState(() => _canOpenSettings = v);
    }));
  }

  /// Replaces a camera session that FAILED — it cannot be revived.
  ///
  /// Found on a real Android runtime: after the operator refuses the camera,
  /// opens the phone's app-permissions page (the button right above) and
  /// grants it, `start()` on the SAME controller leaves the plugin in its
  /// error state, so `errorView` went on saying "no permission" until the app
  /// was killed — defeating the whole point of the Settings button. Retry and
  /// a resume-after-failure therefore open a NEW session; the preview widget
  /// starts it. The old one is released first: two live controllers fight
  /// over the camera.
  Future<void> _restartCamera() async {
    final s = _scanner;
    if (s == null || _restarting || !mounted) return; // a test owns the seam
    _restarting = true;
    try {
      final old = _cam;
      setState(() {
        _cam = null; // the dying controller must not be built again
        _camError = null;
      });
      if (old != null) await old.dispose();
      if (!mounted) return;
      setState(() => _cam = s.open());
    } finally {
      _restarting = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final active = _lifecycle.feed(state);
    if (active == null) return; // same phase as before (Android's synthetic hidden, web's inactive+hidden)
    final c = _cam;
    if (c == null) return; // a replacement is in flight: the new preview starts itself
    // Coming back from the phone's permissions page: a FAILED camera is
    // replaced, never restarted (see [_restartCamera]).
    if (active && _camError != null) {
      unawaited(_restartCamera());
      return;
    }
    unawaited(active ? c.start() : c.stop());
  }

  @override
  void dispose() {
    final c = _cam;
    if (c != null) {
      WidgetsBinding.instance.removeObserver(this);
      unawaited(c.dispose());
    }
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

  /// Leaves for the phone's app-permissions page. If the jump fails the
  /// operator is told in words instead of being left with a dead button —
  /// manual entry is one tap away underneath either way.
  Future<void> _openAppSettings() async {
    final ok = await AppSettingsLink.instance.open();
    if (ok || !mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
          content: Text(tr(
              'Sozlamalarni ochib bo‘lmadi. Telefon sozlamalari → Ilovalar → BinOS → Ruxsatlar bo‘limidan kamerani yoqing.'))));
  }

  Widget _errorView(ScanErrorCode code) {
    // Remembered for the lifecycle path; assigning during build triggers no
    // rebuild, and the retry button below is already on screen.
    _camError = code;
    final (String title, String body) = switch (code) {
      ScanErrorCode.permissionDenied => (
          tr('Kameraga ruxsat berilmagan'),
          tr('Shtrix-kodni skanerlash uchun telefon sozlamalarida ilovaga kamera ruxsatini bering. Hozircha kodni qo‘lda kiritishingiz mumkin.'),
        ),
      ScanErrorCode.unsupported => (
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
            // The operator refused the camera: asking again may already be
            // impossible (Android answers a twice-denied permission instantly
            // and without a dialog), so give them the phone's own permissions
            // page — but only where one exists.
            if (code == ScanErrorCode.permissionDenied && _canOpenSettings) ...[
              const SizedBox(height: 8),
              SizedBox(
                height: kMinTouch,
                child: OutlinedButton.icon(
                  key: const Key('scan-open-settings'),
                  onPressed: _openAppSettings,
                  style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white, side: const BorderSide(color: Colors.white54)),
                  icon: const Icon(Icons.settings_outlined, size: 18),
                  label: Text(tr('Sozlamalarni ochish')),
                ),
              ),
            ],
            if (_cam != null && code != ScanErrorCode.unsupported) ...[
              const SizedBox(height: 8),
              SizedBox(
                height: kMinTouch,
                child: OutlinedButton(
                  key: const Key('scan-error-retry'),
                  onPressed: () => unawaited(_restartCamera()),
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
    final c = _cam;
    // Between two sessions ([_restartCamera]): the screen stays, manual entry
    // at the bottom stays, only the preview is momentarily absent.
    if (c == null) return const ColoredBox(key: Key('scan-camera-restarting'), color: Colors.black);
    // KEYED BY THE SESSION — do not remove. `mobile_scanner`'s widget has no
    // `didUpdateWidget`: it starts its controller in `initState` and never
    // looks at it again. Without a key that changes with the session, Flutter
    // reuses that State for the replacement, the NEW camera is never started,
    // and the operator keeps seeing the OLD error (proven on an Android
    // runtime: granting the permission then retrying changed nothing).
    return KeyedSubtree(key: ObjectKey(c), child: c.view(onCode: _onCode, errorView: _errorView));
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
          // Capability flags from the adapter: no torch button where the torch
          // does nothing (web), no switch button where there is one camera.
          if (_cam != null) ...[
            if (_scanner?.hasTorch ?? false)
              IconButton(
                key: const Key('scan-torch'),
                tooltip: tr('Chiroq'),
                constraints: iconBtn,
                onPressed: () => unawaited(_cam!.toggleTorch()),
                icon: const Icon(Icons.flash_on),
              ),
            if (_scanner?.canSwitchCamera ?? false)
              IconButton(
                key: const Key('scan-switch-camera'),
                tooltip: tr('Kamerani almashtirish'),
                constraints: iconBtn,
                onPressed: () => unawaited(_cam!.switchCamera()),
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
          // Nishon ramka — AYNAN dekodlanadigan oyna (`kScanRoiW` x `kScanRoiH`).
          //
          // ⚠️  Ilgari bu 260x160 QAT'IY quti edi. Web'da `scanWindow` no-op
          //     bo'lgani uchun dekoder BUTUN kadrni olardi — ya'ni ramka bezak
          //     edi va operatorni kodni kichik qutiga "sig'dirish" uchun
          //     telefonni UZOQLASHTIRISHGA o'rgatardi, bu esa barkodni yanada
          //     mayda qilardi. Endi ramka rostini ko'rsatadi.
          IgnorePointer(
            child: FractionallySizedBox(
              widthFactor: kScanRoiW,
              heightFactor: kScanRoiH,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.accentStrong, width: 3),
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
            ),
          ),
          if (kScanDiagnostics)
            Positioned(top: 8, left: 8, right: 8, child: _ScanDiagnosticsPanel(session: _cam)),
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


/// Skaner diagnostikasi — `--dart-define=BINOS_SCAN_DIAG=1` bilan yig'ilganda.
///
/// Real qurilmada (iPhone) nima ko'rinadi: ruxsat, kameralar soni, tanlangan
/// kamera, video o'lchami, dekoder tayyormi, urinish/muvaffaqiyat sanog'i,
/// oxirgi format, kutilmagan xato TOIFASI va halqa tirikmi.
/// Kadr/rasm/barkod qiymati/token — CHIQMAYDI.
class _ScanDiagnosticsPanel extends StatefulWidget {
  const _ScanDiagnosticsPanel({required this.session});

  final ScannerSession? session;

  @override
  State<_ScanDiagnosticsPanel> createState() => _ScanDiagnosticsPanelState();
}

class _ScanDiagnosticsPanelState extends State<_ScanDiagnosticsPanel> {
  Timer? _t;
  Map<String, Object?> _d = const <String, Object?>{};

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) => _poll());
    _poll();
  }

  void _poll() {
    final ScannerSession? s = widget.session;
    if (s == null) return;
    final Map<String, Object?> next = s.diagnostics();
    if (!mounted) return;
    setState(() => _d = next);
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  String _v(String k) => '${_d[k] ?? '—'}';

  @override
  Widget build(BuildContext context) {
    final List<List<String>> rows = <List<String>>[
      <String>['ruxsat', _v('permission')],
      <String>['kameralar', _v('cameras')],
      <String>['tanlangan', _v('selectedLabel')],
      <String>['video', '${_v('videoWidth')}x${_v('videoHeight')}  rs=${_v('readyState')}'],
      <String>['facingMode', _v('facingMode')],
      <String>['cheklov pog‘onasi', _v('constraintStep')],
      <String>['dekoder', _v('decoderReady')],
      <String>['urinish', '${_v('attempts')}  (${_v('attemptsPerSec')}/s)  roi=${_v('roiAttempts')} full=${_v('fullAttempts')}'],
      <String>['muvaffaqiyat', _v('successes')],
      <String>['oxirgi format', _v('lastFormat')],
      <String>['kutilmagan xato', 'loop=${_v('loopErrors')} grab=${_v('grabErrors')} · ${_v('lastErrorKind')}'],
      <String>['halqa', 'tirik=${_v('loopAlive')} start=${_v('starts')} roi=${_v('roi')}'],
      <String>['birinchi kadr', '${_v('firstFrameMs')} ms'],
    ];
    return Material(
      color: Colors.black.withValues(alpha: 0.72),
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          key: const Key('scan-diagnostics'),
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Text('SCAN DIAG', style: TextStyle(color: Colors.amber, fontSize: 10, fontWeight: FontWeight.w800)),
            for (final List<String> r in rows)
              Text('${r[0]}: ${r[1]}',
                  style: const TextStyle(color: Colors.white, fontSize: 10.5, height: 1.35)),
          ],
        ),
      ),
    );
  }
}
