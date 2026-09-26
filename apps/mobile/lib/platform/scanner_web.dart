/// Web (Safari/iPhone) kamera skaneri — `web/scanner.js` ustidagi yupqa qatlam.
///
/// NEGA PLAGIN EMAS. `mobile_scanner` ning web yo'li kamerani o'lcham
/// cheklovisiz so'raydi va `cameraResolution` ni web'da UMUMAN o'qimaydi
/// (sabab va o'lchovlar: `web/scanner.js` sarlavhasi). Shu bois web'da
/// kamera+dekodlash qatlami O'ZIMIZNIKI; Android/iOS native yo'li
/// `scanner.dart` dagi plagin adapterida QOLADI.
///
/// ⚠️  Bu qatlam barkod MATNINI o'zgartirmaydi — u xuddi plagin kabi xom
///     qiymatni `onCode` ga uzatadi. Tarozi etiketkasi qoidasi va mahsulotga
///     moslashtirish serverda (`GET /products/scan`).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;

import 'scanner.dart';

// ── JS ko'prigi (`web/scanner.js` da `self.binosScanner`) ────────────────────
@JS('binosScanner')
external JSAny? get _binosScannerObj;

@JS('binosScanner.create')
external JSString _jsCreate(JSString containerId);

@JS('binosScanner.start')
external JSPromise<JSString> _jsStart(JSString id);

@JS('binosScanner.setCallback')
external void _jsSetCallback(JSString id, JSFunction cb);

@JS('binosScanner.stop')
external void _jsStop(JSString id);

@JS('binosScanner.dispose')
external void _jsDispose(JSString id);

@JS('binosScanner.diagnostics')
external JSString _jsDiagnostics(JSString id);

bool get _bridgeReady => _binosScannerObj != null;

/// Web maqsadi: o'z kamera/dekodlash quvurimiz (`web/scanner.js`).
Scanner createScanner() => const WebScanner();

/// Web adapteri: `Scanner` shartnomasini bajaradi.
class WebScanner implements Scanner {
  const WebScanner();

  /// Web'da chiroq YO'Q: `MediaStreamTrack` torch imkoniyati Safari'da
  /// e'lon qilinmaydi, shu bois tugma o'lik UI bo'lardi.
  @override
  bool get hasTorch => false;

  /// Old/orqa almashtirish web'da BERILMAYDI: `facingMode: {ideal:'environment'}`
  /// allaqachon orqa kamerani so'raydi va almashtirish oqimni qayta ochishni
  /// talab qilardi — iOS'da bu ruxsat oynasini qayta chiqarishi mumkin.
  @override
  bool get canSwitchCamera => false;

  @override
  ScannerSession open() => WebScannerSession();
}

/// Bitta kamera sessiyasi.
class WebScannerSession implements ScannerSession {
  WebScannerSession() : _n = ++_counter;

  static int _counter = 0;
  static final Set<String> _registered = <String>{};

  final int _n;
  String? _sid;
  bool _disposed = false;

  String get _containerId => 'binos-scan-host-$_n';
  String get _viewType => 'binos-scan-view-$_n';

  /// Oxirgi o'qilgan diagnostika (maxfiylikka xavfsiz: faqat sanoq va o'lcham).
  static Map<String, Object?> lastDiagnostics = const <String, Object?>{};

  void _ensureRegistered() {
    if (_registered.contains(_viewType)) return;
    _registered.add(_viewType);
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int _) {
      final web.HTMLDivElement host =
          web.document.createElement('div') as web.HTMLDivElement;
      host.id = _containerId;
      host.style
        ..width = '100%'
        ..height = '100%'
        ..backgroundColor = '#000'
        ..overflow = 'hidden';
      return host;
    });
  }

  @override
  Widget view({
    required ValueChanged<String> onCode,
    required Widget Function(ScanErrorCode code) errorView,
  }) {
    _ensureRegistered();
    return _WebScannerView(
      session: this,
      viewType: _viewType,
      onCode: onCode,
      errorView: errorView,
    );
  }

  /// `view()` DOM'ga joylashgach chaqiriladi. Natija: `ok` yoki xato kodi.
  Future<ScanErrorCode?> startAndReport(ValueChanged<String> onCode) async {
    if (_disposed) return null;
    if (!_bridgeReady) return ScanErrorCode.unsupported;

    // Host `div` platforma ko'rinishi qurilgach paydo bo'ladi — uni kutamiz.
    for (var i = 0; i < 40; i++) {
      if (web.document.getElementById(_containerId) != null) break;
      await Future<void>.delayed(const Duration(milliseconds: 25));
      if (_disposed) return null;
    }
    if (web.document.getElementById(_containerId) == null) {
      return ScanErrorCode.genericError;
    }

    _sid ??= _jsCreate(_containerId.toJS).toDart;
    final String sid = _sid!;
    _jsSetCallback(
      sid.toJS,
      ((JSString code) {
        if (_disposed) return;
        final String raw = code.toDart;
        if (raw.isNotEmpty) onCode(raw);
      }).toJS,
    );

    final String result = (await _jsStart(sid.toJS).toDart).toDart;
    _readDiagnostics();
    switch (result) {
      case 'ok':
        return null;
      case 'permission':
        return ScanErrorCode.permissionDenied;
      case 'unsupported':
        return ScanErrorCode.unsupported;
      default:
        return ScanErrorCode.genericError;
    }
  }

  void _readDiagnostics() {
    final String? sid = _sid;
    if (sid == null) return;
    try {
      final Object? decoded = jsonDecode(_jsDiagnostics(sid.toJS).toDart);
      if (decoded is Map) {
        lastDiagnostics = decoded.map((k, v) => MapEntry('$k', v));
      }
    } catch (_) {
      /* diagnostika hech qachon skanerni yiqitmaydi */
    }
  }

  /// Joriy diagnostika (ixtiyoriy panel uchun).
  @override
  Map<String, Object?> diagnostics() {
    _readDiagnostics();
    return lastDiagnostics;
  }

  @override
  Future<void> start() async {
    final String? sid = _sid;
    if (sid == null || _disposed || !_bridgeReady) return;
    try {
      await _jsStart(sid.toJS).toDart;
    } catch (_) {/* best-effort */}
  }

  @override
  Future<void> stop() async {
    final String? sid = _sid;
    if (sid == null || !_bridgeReady) return;
    try {
      _readDiagnostics();
      _jsStop(sid.toJS);
    } catch (_) {/* best-effort */}
  }

  @override
  Future<void> toggleTorch() async {/* web'da chiroq yo'q */}

  @override
  Future<void> switchCamera() async {/* web'da almashtirish yo'q */}

  @override
  Future<void> dispose() async {
    _disposed = true;
    final String? sid = _sid;
    if (sid == null || !_bridgeReady) return;
    try {
      _jsDispose(sid.toJS);
    } catch (_) {/* best-effort */}
    _sid = null;
  }
}

class _WebScannerView extends StatefulWidget {
  const _WebScannerView({
    required this.session,
    required this.viewType,
    required this.onCode,
    required this.errorView,
  });

  final WebScannerSession session;
  final String viewType;
  final ValueChanged<String> onCode;
  final Widget Function(ScanErrorCode code) errorView;

  @override
  State<_WebScannerView> createState() => _WebScannerViewState();
}

class _WebScannerViewState extends State<_WebScannerView> {
  ScanErrorCode? _error;
  bool _started = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(_boot()));
  }

  Future<void> _boot() async {
    if (_started) return;
    _started = true;
    final ScanErrorCode? err = await widget.session.startAndReport(widget.onCode);
    if (!mounted) return;
    if (err != null) setState(() => _error = err);
  }

  @override
  void dispose() {
    unawaited(widget.session.stop());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ScanErrorCode? err = _error;
    if (err != null) return widget.errorView(err);
    return HtmlElementView(viewType: widget.viewType);
  }
}
