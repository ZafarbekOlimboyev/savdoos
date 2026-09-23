import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/receiving_api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'receiving_item_editor_screen.dart';
import 'receiving_submit_sheet.dart';
import 'receiving_success_screen.dart';
import 'receiving_widgets.dart';

/// A receiving DOCUMENT being prepared — manual (`ManualReceivingScreen`) or
/// read by the AI from an invoice photo (`ReceivingReviewScreen`).
///
/// * one stable `client_uuid` for the whole screen: a retry after a lost
///   answer is a replay (`duplicate: true`), never a second receiving;
/// * the receiving branch is shown explicitly (the server writes to the
///   actor branch) and a mismatch with the branch on screen blocks saving;
/// * lot-tracked lines need valid lots; the tracked product list is loaded
///   BEFORE saving is allowed and reloaded after a server refusal;
/// * success is shown only after a 2xx.
class ReceivingDraftScreen extends StatefulWidget {
  /// Creates the screen.
  const ReceivingDraftScreen({
    super.key,
    required this.title,
    required this.source,
    this.aiScan,
    this.imageB64,
  });

  /// App bar title.
  final String title;

  /// `manual`, `ai` or `demo` (sent as `source`).
  final String source;

  /// The AI result (review mode).
  final AiScan? aiScan;

  /// Invoice photo (review mode).
  final String? imageB64;

  @override
  State<ReceivingDraftScreen> createState() => _ReceivingDraftScreenState();
}

class _ReceivingDraftScreenState extends State<ReceivingDraftScreen> {
  // Bitta hujjat = bitta uuid. Qayta urinishda AYLANMAYDI: server takrorni
  // `duplicate: true` bilan qaytaradi, ikkinchi kirim yaratmaydi.
  final String _uuid = Api.newUuid();
  final List<RecvLine> _lines = [];
  final _scroll = ScrollController();
  final Map<String, GlobalKey> _lineKeys = {};

  TrackedCatalog? _tracked;
  Object? _trackedError;
  bool _trackedLoading = false;

  List<SupplierRow>? _suppliers;
  Object? _suppliersError;
  SupplierRow? _supplier; // null = standart "Qabul (mobil)"

  Object? _docError;
  bool _attempted = false;
  // Natijasi NOMA'LUM urinishlar (aloqa uzildi / 5xx) — `duplicate` javobida
  // shulardan keyingi o'zgarishlar yo'qolganini aniq aytish uchun.
  final Set<String> _unknownPrints = {};
  String? _lastSentPrint;

  bool get _ai => widget.aiScan != null;

  @override
  void initState() {
    super.initState();
    final scan = widget.aiScan;
    if (scan != null) {
      for (final it in scan.items) {
        _lines.add(RecvLine.fromAi(it, TrackedCatalog.empty()));
      }
    }
    Session.instance.addListener(_onSession);
    _loadTracked();
    _loadSuppliers();
  }

  @override
  void dispose() {
    Session.instance.removeListener(_onSession);
    for (final l in _lines) {
      l.dispose();
    }
    _scroll.dispose();
    super.dispose();
  }

  void _onSession() {
    if (mounted) setState(() {});
  }

  // ── Loads ───────────────────────────────────────────────────────────────

  Future<void> _loadTracked({bool authoritative = false}) async {
    setState(() {
      _trackedLoading = true;
      _trackedError = null;
    });
    try {
      final t = await ReceivingApi.trackedProducts();
      if (!mounted) return;
      setState(() {
        _tracked = t;
        _trackedLoading = false;
        _applyTracking(t, authoritative: authoritative);
      });
      await _loadBiz();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _trackedError = e;
        _trackedLoading = false;
      });
    }
  }

  /// Makes every line's tracking match the catalog. [authoritative]: the
  /// catalog was just reloaded after a server refusal — its answer wins over
  /// older flags; otherwise flags are OR-ed (a fresher search may know more).
  void _applyTracking(TrackedCatalog t, {required bool authoritative}) {
    for (final l in _lines) {
      final p = l.product;
      if (p == null) continue;
      final hit = t.byId[p.id];
      final lots = authoritative ? hit != null : (p.trackLots || hit != null);
      final exp = lots && (hit?.trackExpiry ?? (authoritative ? false : p.trackExpiry));
      if (lots != p.trackLots || exp != p.trackExpiry) {
        l.setProduct(p.withTracking(trackLots: lots, trackExpiry: exp));
      }
    }
  }

  Future<void> _loadBiz() async {
    RecvLine? probe;
    for (final l in _lines) {
      if (l.trackExpiry) {
        probe = l;
        break;
      }
    }
    if (probe == null) return;
    final d = await ReceivingApi.businessDate(probe.product!.id);
    if (!mounted) return;
    setState(() {
      for (final l in _lines) {
        if (l.trackExpiry) l.lots?.businessDate = d;
      }
    });
  }

  Future<void> _loadSuppliers() async {
    setState(() => _suppliersError = null);
    try {
      final s = await ReceivingApi.suppliers();
      if (mounted) setState(() => _suppliers = s);
    } catch (e) {
      if (mounted) setState(() => _suppliersError = e);
    }
  }

  // ── Lines ───────────────────────────────────────────────────────────────

  Future<void> _editLine(RecvLine? line) async {
    final res = await Navigator.of(context).push<RecvLine>(MaterialPageRoute(
      builder: (_) => ReceivingItemEditorScreen(line: line, tracked: _tracked),
    ));
    if (res == null || !mounted) return;
    setState(() {
      final i = line == null ? -1 : _lines.indexOf(line);
      if (i >= 0) {
        _lines[i].dispose();
        _lines[i] = res;
      } else {
        _lines.add(res);
      }
      _docError = null;
    });
    if (res.trackExpiry) await _loadBiz();
  }

  Future<void> _pickForLine(RecvLine line) async {
    final p = await showRecvProductSearch(context, initialQuery: line.aiName ?? '', tracked: _tracked);
    if (p == null || !mounted) return;
    final t = _tracked?.byId[p.id];
    setState(() {
      line.setProduct((t != null && !p.trackLots) ? p.withTracking(trackLots: true, trackExpiry: t.trackExpiry) : p);
      if (line.costText.trim().isEmpty && (p.buyCents ?? 0) > 0) line.costText = centsToInput(p.buyCents!);
      _docError = null;
    });
    if (line.trackExpiry) await _loadBiz();
  }

  void _remove(RecvLine line) {
    final i = _lines.indexOf(line);
    if (i < 0) return;
    setState(() => _lines.removeAt(i));
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger
        .showSnackBar(SnackBar(
          content: Text(trArgs('«{name}» olib tashlandi', {'name': line.displayName})),
          action: SnackBarAction(
            label: tr('Qaytarish'),
            onPressed: () {
              if (!mounted) return;
              setState(() => _lines.insert(i.clamp(0, _lines.length), line));
            },
          ),
        ))
        .closed
        .then((reason) {
      if (reason != SnackBarClosedReason.action && !_lines.contains(line)) line.dispose();
    });
  }

  // ── Submit ──────────────────────────────────────────────────────────────

  String _blockedReason() {
    final br = RecvBranchState.of();
    if (!br.ok) return br.reason();
    if (!Perm.allows('receiving.commit')) return Perm.reason('receiving.commit');
    if (_lines.isEmpty) return tr('Avval mahsulot qo‘shing');
    if (_tracked == null) {
      return _trackedError != null
          ? tr('Partiyali mahsulotlar ro‘yxati yuklanmadi — qayta urinib ko‘ring.')
          : tr('Mahsulotlar tekshirilmoqda…');
    }
    return '';
  }

  List<RecvIssue> _issues(RecvLine l) => lineIssues(l, tracked: _tracked);

  String _print(Map<String, Object?> body) {
    final b = Map<String, Object?>.of(body)..remove('client_uuid');
    return jsonEncode(b);
  }

  bool _unknownOutcome(Object e) =>
      isConnectivityError(e) || (e is ApiException && e.kind == ApiErrorKind.server);

  Future<CommitResult> _send(String payment, String? account) async {
    final body = commitBody(
      lines: _lines,
      clientUuid: _uuid,
      payment: payment,
      source: widget.source,
      supplierId: (_supplier == null || _supplier!.id.isEmpty) ? null : _supplier!.id,
      cashAccountId: account,
      imageB64: widget.imageB64,
      aiRaw: widget.aiScan?.aiRaw ?? const [],
    );
    final print = _print(body);
    try {
      final r = await ReceivingApi.commit(body);
      _lastSentPrint = print;
      return r;
    } catch (e) {
      // ⚠️  Noma'lum natijali urinishlar HECH QACHON unutilmaydi: keyingi 4xx rad etish
      //     ham sekin (hali yakunlanmagan) oldingi urinish keyinroq yozilmasligini
      //     isbotlamaydi. Ortiqcha ogohlantirish xavfsiz, yo'qolgan ogohlantirish — yo'q.
      if (_unknownOutcome(e)) _unknownPrints.add(print);
      rethrow;
    }
  }

  Future<void> _submit() async {
    if (_blockedReason().isNotEmpty) return;
    final bad = <RecvLine>[for (final l in _lines) if (_issues(l).isNotEmpty) l];
    final doc = documentIssues(_lines);
    if (bad.isNotEmpty || doc.isNotEmpty) {
      setState(() {
        _attempted = true;
        _docError = doc.isNotEmpty ? doc.first : trArgs('{n} ta qatorda xato bor — tuzating', {'n': bad.length});
      });
      if (bad.isNotEmpty) _scrollTo(bad.first);
      return;
    }
    final total = draftTotalCents(_lines);
    final out = await showReceivingSubmitSheet(
      context,
      supplierName: supplierLabel(_supplier),
      lines: _lines.length,
      totalCents: total,
      submit: _send,
    );
    if (out == null || !mounted) return;
    final r = out.result;
    if (r != null) {
      final sent = _lastSentPrint;
      final editsLost =
          r.duplicate && sent != null && _unknownPrints.any((p) => _stripAccount(p) != _stripAccount(sent));
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => ReceivingSuccessScreen(result: r, editsMayBeLost: editsLost)),
        result: true,
      );
      return;
    }
    final e = out.error!;
    setState(() {
      _docError = e;
      _attempted = true;
    });
    // 400 — ehtimol mahsulotga partiya kuzatuvi ENDIGINA yoqilgan/o'chirilgan:
    // ro'yxatni yangilaymiz, qatorlar serverning hozirgi holatiga moslashadi.
    if (e is ApiException && e.status == 400) await _loadTracked(authoritative: true);
    _scroll.animateTo(0, duration: const Duration(milliseconds: 250), curve: Curves.easeOut).ignore();
  }

  String _stripAccount(String print) {
    final m = (jsonDecode(print) as Map).cast<String, Object?>()..remove('cash_account_id');
    return jsonEncode(m);
  }

  void _scrollTo(RecvLine l) {
    final ctx = _lineKeys[l.key]?.currentContext;
    if (ctx != null) {
      Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 250), alignment: 0.1);
    }
  }

  Future<bool> _confirmLeave() async {
    if (_lines.isEmpty) return true;
    return confirmDestructive(
      context,
      title: tr('Kirim saqlanmadi'),
      message: tr('Hujjat saqlanmagan. Chiqsangiz kiritilgan qatorlar yo‘qoladi.'),
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Qolish'),
    );
  }

  // ── Build ───────────────────────────────────────────────────────────────

  Widget _supplierRow() {
    final loading = _suppliers == null && _suppliersError == null;
    return InkWell(
      key: const Key('recv-supplier'),
      borderRadius: BorderRadius.circular(13),
      onTap: () async {
        if (_suppliersError != null) {
          await _loadSuppliers();
          return;
        }
        final list = _suppliers;
        if (list == null) return;
        final s = await showRecvSupplierPicker(context, list, selectedId: _supplier?.id);
        if (s != null && mounted) setState(() => _supplier = s.id.isEmpty ? null : s);
      },
      child: Container(
        constraints: const BoxConstraints(minHeight: 56),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(13),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(children: [
          Icon(Icons.local_shipping_outlined, size: 20, color: AppColors.accentStrong),
          const SizedBox(width: 11),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(tr('Yetkazib beruvchi'), style: TextStyle(fontSize: 12, color: AppColors.muted)),
              Text(
                _suppliersError != null ? tr('Ro‘yxat yuklanmadi — qayta urinish uchun bosing') : supplierLabel(_supplier),
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
              ),
            ]),
          ),
          if (loading)
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          else
            Icon(_suppliersError != null ? Icons.refresh : Icons.expand_more, color: AppColors.muted),
        ]),
      ),
    );
  }

  Widget _lineCard(RecvLine l) {
    final issues = _issues(l);
    final key = _lineKeys.putIfAbsent(l.key, GlobalKey.new);
    Widget? extra;
    if (l.unmatched) {
      extra = Row(children: [
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: OutlinedButton.icon(
              key: Key('recv-line-pick-${l.key}'),
              onPressed: () => _pickForLine(l),
              icon: const Icon(Icons.search, size: 18),
              label: Text(tr('Mahsulotni tanlang'), maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: TextButton.icon(
              key: Key('recv-line-new-${l.key}'),
              onPressed: () => _editLine(l),
              icon: const Icon(Icons.add_circle_outline, size: 18),
              label: Text(tr('Yangi mahsulot'), maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ),
        ),
      ]);
    }
    return KeyedSubtree(
      key: key,
      child: RecvLineCard(
        line: l,
        issues: issues,
        showIssues: _ai || _attempted,
        onTap: () => _editLine(l),
        onRemove: () => _remove(l),
        extra: extra,
      ),
    );
  }

  List<Widget> _lineList() {
    if (_lines.isEmpty) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 24),
          child: Center(
            child: Text(tr('Hali mahsulot qo‘shilmagan'), style: TextStyle(color: AppColors.muted)),
          ),
        ),
      ];
    }
    if (!_ai) return [for (final l in _lines) _lineCard(l)];
    final need = [for (final l in _lines) if (_issues(l).isNotEmpty) l];
    final ready = [for (final l in _lines) if (_issues(l).isEmpty) l];
    return [
      if (need.isNotEmpty) ...[
        _section(Icons.warning_amber_rounded, AppColors.warn, tr('Diqqat talab qiladi'), need.length),
        const SizedBox(height: 8),
        for (final l in need) _lineCard(l),
      ],
      if (ready.isNotEmpty) ...[
        const SizedBox(height: 8),
        _section(Icons.check_circle, AppColors.ok, tr('Tayyor'), ready.length),
        const SizedBox(height: 8),
        for (final l in ready) _lineCard(l),
      ],
    ];
  }

  Widget _section(IconData ic, Color c, String title, int n) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(children: [
          Icon(ic, size: 18, color: c),
          const SizedBox(width: 8),
          Text(title, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
          const SizedBox(width: 8),
          RecvBadge('$n', color: c),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final reason = _blockedReason();
    final total = draftTotalCents(_lines);
    final readyN = _lines.where((l) => _issues(l).isEmpty).length;
    final label = _ai
        ? trArgs('Omborga qo‘shish · tayyor {r}/{n}', {'r': readyN, 'n': _lines.length})
        : tr('Kirimni saqlash');
    final err = _docError;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final nav = Navigator.of(context);
        if (await _confirmLeave() && mounted) nav.pop();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: SafeArea(
          bottom: false,
          child: Column(children: [
            const ConnectivityBanner(),
            Expanded(
              child: ListView(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
                children: [
                  const ReceivingBranchBanner(),
                  const SizedBox(height: 10),
                  if (widget.aiScan?.isDemo == true) ...[
                    ErrorBanner(
                      key: const Key('recv-demo'),
                      severity: BannerSeverity.warning,
                      message: tr('DEMO rejim: server AI’siz ishlayapti — qatorlar rasmdan O‘QILMAGAN. Har qatorni nakladnoy bilan solishtiring.'),
                    ),
                    const SizedBox(height: 10),
                  ],
                  if (err != null) ...[
                    err is String
                        ? ErrorBanner(key: const Key('recv-doc-error'), message: err, onDismiss: () => setState(() => _docError = null))
                        : ErrorBanner(key: const Key('recv-doc-error'), error: err, onDismiss: () => setState(() => _docError = null)),
                    const SizedBox(height: 10),
                  ],
                  if (_trackedError != null) ...[
                    ErrorBanner(
                      key: const Key('recv-tracked-error'),
                      message: tr('Partiyali mahsulotlar ro‘yxati yuklanmadi — qayta urinib ko‘ring.'),
                      onRetry: () => _loadTracked(),
                    ),
                    const SizedBox(height: 10),
                  ] else if (_trackedLoading && _tracked == null) ...[
                    const LinearProgressIndicator(minHeight: 2),
                    const SizedBox(height: 10),
                  ],
                  _supplierRow(),
                  const SizedBox(height: 16),
                  Row(children: [
                    Expanded(
                      child: Text(tr('Mahsulotlar'), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                    ),
                    Text('${_lines.length}', style: TextStyle(fontSize: 14, color: AppColors.muted)),
                  ]),
                  const SizedBox(height: 8),
                  ..._lineList(),
                  const SizedBox(height: 6),
                  SizedBox(
                    height: kMinTouch,
                    child: OutlinedButton.icon(
                      key: const Key('recv-add-line'),
                      onPressed: () => _editLine(null),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.accentStrong,
                        side: BorderSide(color: AppColors.accentStrong, width: 1.3),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                      ),
                      icon: const Icon(Icons.add, size: 20),
                      label: Text(tr('Mahsulot qo‘shish')),
                    ),
                  ),
                ],
              ),
            ),
            StickyActionBar(
              label: label,
              icon: Icons.check_circle,
              enabled: reason.isEmpty,
              disabledReason: reason,
              onPressed: _submit,
              summary: Row(children: [
                Expanded(
                  child: Text(trArgs('{n} ta mahsulot · jami', {'n': _lines.length}),
                      style: TextStyle(color: AppColors.muted, fontSize: 13.5)),
                ),
                Text(formatCents(total),
                    key: const Key('recv-total'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

