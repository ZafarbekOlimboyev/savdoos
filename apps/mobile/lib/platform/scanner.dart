import 'package:flutter/widgets.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'scanner_stub.dart'
    if (dart.library.io) 'scanner_io.dart'
    if (dart.library.js_interop) 'scanner_web.dart';

export 'scanner_stub.dart'
    if (dart.library.io) 'scanner_io.dart'
    if (dart.library.js_interop) 'scanner_web.dart' show createScanner;

/// Skaner diagnostikasi panelini yoqadi — FAQAT sinov/nomzod build'ida.
///
///     flutter build web ... --dart-define=BINOS_SCAN_DIAG=1
///
/// ⚠️  `bool.fromEnvironment` ATAYLAB ISHLATILMAYDI: u FAQAT literal `"true"`
///     ni tan oladi va `=1` bilan JIMGINA `false` qaytaradi — birinchi nomzod
///     build'ida panel aynan shu sabab bundle'dan tushib qolgan va qurilmada
///     ko'rinmagan. Endi qiymat satr sifatida o'qilib, odam yozadigan har
///     ko'rinish qabul qilinadi.
/// ⚠️  Oddiy production build'ida bu `false` va panel UMUMAN qurilmaydi.
///     Panelga kadr, rasm, barkod qiymati, token yoki sir CHIQMAYDI.
const String _kScanDiagRaw = String.fromEnvironment('BINOS_SCAN_DIAG');

/// Build diagnostikani UMUMAN ko‘rsata oladimi. Bu YETARLI shart EMAS —
/// [scanDiagnosticsOn] ga qarang.
const bool kScanDiagnostics =
    _kScanDiagRaw == '1' || _kScanDiagRaw == 'true' || _kScanDiagRaw == 'yes' || _kScanDiagRaw == 'on';

/// URL diagnostikani SO‘RAYAPTIMI: aynan `?diag=scan`.
///
/// ⚠️  Bu ikkinchi shart 2026-09-27 da qo‘shildi. Ilgari panel FAQAT
///     [kScanDiagnostics] ga bog‘langan edi, URL tekshiruvi esa faqat
///     login’siz marshrutda (`main.dart`) turardi — natijada nomzod build’ida
///     panel oddiy skaner ekranida, toza URL bilan ham chiqib turdi. Do‘kon
///     egasi buni real iPhone’da ko‘rdi.
///
/// Qoida ATAYLAB tor va holatsiz: hech qanday `localStorage`/`sessionStorage`,
/// oldingi holat, muhit qiymati yoki service worker YOQA OLMAYDI — yagona
/// manba joriy URL. Faqat `diag` kaliti va aynan `scan` qiymati qabul qilinadi:
/// `?diag=0`, `?diag=false`, `?diag=`, `?foo=scan` — hammasi O‘CHIQ.
///
/// Flutter web xesh-marshrutida so‘rov fragment ichida bo‘lishi mumkin
/// (`/#/?diag=scan`), shu bois fragment ham AYNI qoida bilan tekshiriladi.
bool diagnosticsRequestedIn(Uri url) {
  if (url.queryParameters['diag'] == 'scan') return true;
  final String f = url.fragment;
  if (f.isEmpty || !f.contains('diag=')) return false;
  final int q = f.indexOf('?');
  final String query = q >= 0 ? f.substring(q + 1) : f;
  return Uri.splitQueryString(query)['diag'] == 'scan';
}

/// Panel KO‘RSATILADIMI: build imkoniyati VA URL so‘rovi — ikkalasi ham.
/// Sof funksiya, shu bois hamma holat testda tekshiriladi.
bool scanDiagnosticsFor({required bool buildAllows, required Uri url}) =>
    buildAllows && diagnosticsRequestedIn(url);

/// Joriy URL manbai (test uchun almashtiriladi).
@visibleForTesting
Uri Function() scanDiagUrlSource = () => Uri.base;

/// Diagnostika shu daqiqada yoqilganmi. HAR build’da qayta hisoblanadi
/// (keshlanmaydi): URL o‘zgarsa javob ham o‘zgaradi.
bool scanDiagnosticsOn() =>
    scanDiagnosticsFor(buildAllows: kScanDiagnostics, url: scanDiagUrlSource());

/// Dekodlash oynasi (ROI) — kadrning markaziy ulushi.
///
/// ⚠️  `web/scanner.js` dagi `ROI_W`/`ROI_H` bilan AYNI bo'lishi SHART: skaner
///     ekranidagi nishon ramka SHU ulushlar bo'yicha chiziladi, ya'ni operator
///     ko'rayotgan ramka haqiqatan dekodlanadigan joyni ko'rsatadi (ilgari
///     ramka 260x160 qat'iy edi va web'da BEZAK bo'lib qolardi: `scanWindow`
///     web implementatsiyasida no-op). Moslikni `tests/scanner-loop.test.ts`
///     tekshiradi. Kengroq maydon har 4-urinishda sinaladi — tolerantlik saqlanadi.
/// ⚠️  Balandlik TASMA: 1D barkodga ko'p qator kerak emas, dekod narxi esa
///     piksel soniga proporsional (o'lchangan: 1280x720 muvaffaqiyatsiz kadr
///     ~850 ms, 960x140 ~355 ms).
const double kScanRoiW = 0.86;
const double kScanRoiH = 0.28;

/// App-facing name of the camera error code.
///
/// It is an alias of the plugin enum (not a copy) so the existing seam
/// `ScannerViewBuilder` — used by widget tests AND `test/e2e/harness.dart`
/// (`E2ECamera.view`) — keeps its signature; screens and tests import THIS
/// name from the platform barrel, never the plugin.
typedef ScanErrorCode = MobileScannerErrorCode;

/// Camera barcode scanner. `mobile_scanner` declares a web implementation, so
/// ONE adapter; the capability flags carry the platform truth (`kIsWeb` is a
/// pure-Dart flag here, never around an import).
///
/// The screen's `scannerBuilder` seam is untouched: the adapter supplies the
/// DEFAULT camera when no builder is injected.
abstract class Scanner {
  /// The active adapter (tests inject a fake).
  static Scanner instance = createScanner();

  /// A torch can be toggled. FALSE on web: `mobile_scanner_web` reports
  /// `TorchState.unavailable` and `toggleTorch()` throws `UnsupportedError`,
  /// so a torch button there is dead UI.
  bool get hasTorch;

  /// Front/back camera switching is possible.
  bool get canSwitchCamera;

  /// Opens a camera session (one per screen instance).
  ScannerSession open();
}

/// One camera session: the preview widget plus best-effort controls. Every
/// control is safe to call in any state and never throws.
abstract class ScannerSession {
  /// The preview; [onCode] receives each raw detection, [errorView] renders
  /// a camera failure (permission, unsupported, busy).
  Widget view({required ValueChanged<String> onCode, required Widget Function(ScanErrorCode code) errorView});

  /// (Re)starts the camera.
  Future<void> start();

  /// Stops the camera (background, hidden tab).
  Future<void> stop();

  /// Toggles the torch when [Scanner.hasTorch].
  Future<void> toggleTorch();

  /// Switches front/back.
  Future<void> switchCamera();

  /// Releases the camera.
  Future<void> dispose();

  /// Dekodlashni VAQTINCHA to‘xtatadi — kamera, oqim va dekoder TIRIK qoladi.
  ///
  /// Kod topilgach javob tayyorlanadi (server so‘rovi, varaq, animatsiya) va
  /// web’da bu ish dekodlash halqasi bilan BITTA ipni bo‘lishadi: o‘lchovda
  /// halqa ipning katta qismini egallaydi, ya’ni operator kutayotgan reaksiya
  /// sekinlashadi. To‘xtatish kamerani yopmaydi, shu bois davom etish darhol.
  /// Native yo‘lda plagin kadrlarni o‘zi chegaralaydi — u yerda bu no-op.
  void pauseDecoding() {}

  /// Dekodlashni davom ettiradi. Dublikat qulfi ham tozalanadi: operator AYNI
  /// mahsulotni qayta skanerlasa kutib qolmasin.
  void resumeDecoding() {}

  /// Kamera/dekoder holati — FAQAT sanoq va o'lchamlar.
  ///
  /// ⚠️  MAXFIYLIK: bu yerga kadr, rasm, barkod QIYMATI, token yoki sir
  ///     TUSHMAYDI. Panel faqat `--dart-define=BINOS_SCAN_DIAG=1` bilan
  ///     yig'ilgan build'da ko'rsatiladi; oddiy production UI'da yo'q.
  Map<String, Object?> diagnostics() => const <String, Object?>{};
}
