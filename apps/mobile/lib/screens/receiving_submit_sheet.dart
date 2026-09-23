import 'package:flutter/material.dart';

import '../api.dart';
import '../api/receiving_api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';

/// How the submit sheet ended.
@immutable
class RecvSubmitOutcome {
  /// The server saved (or had already saved) the document.
  const RecvSubmitOutcome.saved(CommitResult this.result) : error = null;

  /// The server REFUSED the document (business rule): the draft must be fixed.
  const RecvSubmitOutcome.rejected(Object this.error) : result = null;

  /// The 2xx answer.
  final CommitResult? result;

  /// The refusal.
  final Object? error;
}

/// Sends the document; the sheet calls it with the chosen payment and the
/// `cash_account_id` to send (only for OPERATOR_MUST_CHOOSE).
typedef RecvSubmit = Future<CommitResult> Function(String payment, String? cashAccountId);

/// Codes after which the custody block is re-read (the server's answer about
/// "which cash account" changed or the choice was refused).
bool _isCashCode(String? code) =>
    code != null &&
    (code.startsWith('CASH_') ||
        code.startsWith('TILL_') ||
        code.startsWith('LEGACY_SHIFT') ||
        code.startsWith('CLOSED_SHIFT') ||
        const {
          'INSUFFICIENT_CASH',
          'NEGATIVE_APPROVAL_REQUIRED',
          'ACCOUNT_ARCHIVED',
          'ACCOUNT_NOT_FOUND',
          'CURRENCY_MISMATCH',
          'SHIFT_NOT_OPEN',
          'OPEN_SHIFT_REQUIRED',
        }.contains(code));

/// The outcome of a failed request is unknown or transient: stay in the sheet
/// and let the operator retry with the SAME `client_uuid` (the server answers a
/// replay with `duplicate: true`, never a second document).
bool _retryable(Object e) {
  if (isConnectivityError(e)) return true;
  if (e is ApiException) {
    if (e.kind == ApiErrorKind.server) return true; // 5xx / unusable 2xx
    // Hujjat raqami to'qnashuvi (server o'zi 3 marta urinadi) — hech narsa yozilmagan.
    if (e.status == 409 && e.code == null && e.detail == "Qabul hujjati band — qayta urinib ko'ring") return true;
  }
  return false;
}

/// Payment choice ("Naqd" / "Qarzga") + cash custody + the commit itself.
///
/// * nothing is preselected: the operator says how the goods were paid;
/// * cash reads `GET /cash/custody-preview?operation=receiving_payment` and
///   renders it with [CustodyBlock] (OPERATOR_MUST_CHOOSE → exact options, no
///   default; BLOCKED → the save button is disabled with the reason);
/// * "saved" is reported ONLY after a 2xx; a lost answer / 5xx keeps the
///   sheet open with a retry (same `client_uuid`); a business refusal closes
///   the sheet with [RecvSubmitOutcome.rejected] so the draft can be fixed.
Future<RecvSubmitOutcome?> showReceivingSubmitSheet(
  BuildContext context, {
  required String supplierName,
  required int lines,
  required int totalCents,
  required RecvSubmit submit,
}) =>
    showAppSheet<RecvSubmitOutcome>(
      context,
      isDismissible: false,
      builder: (_) => ReceivingSubmitBody(supplierName: supplierName, lines: lines, totalCents: totalCents, submit: submit),
    );

/// Body of [showReceivingSubmitSheet] (public for tests).
class ReceivingSubmitBody extends StatefulWidget {
  /// Creates the body.
  const ReceivingSubmitBody({
    super.key,
    required this.supplierName,
    required this.lines,
    required this.totalCents,
    required this.submit,
  });

  /// Supplier shown in the summary.
  final String supplierName;

  /// Number of lines.
  final int lines;

  /// Document total (cents).
  final int totalCents;

  /// The commit.
  final RecvSubmit submit;

  @override
  State<ReceivingSubmitBody> createState() => _ReceivingSubmitBodyState();
}

class _ReceivingSubmitBodyState extends State<ReceivingSubmitBody> {
  String? _payment; // cash | credit
  CustodyInfo? _custody;
  Object? _custodyError;
  bool _custodyLoading = false;
  int _custodySeq = 0;
  String? _account;
  bool _showErrors = false;
  bool _busy = false;
  Object? _error;
  bool _attempted = false;

  Future<void> _loadCustody() async {
    final seq = ++_custodySeq;
    setState(() {
      _custodyLoading = true;
      _custodyError = null;
    });
    try {
      final c = await ReceivingApi.custodyPreview();
      if (!mounted || seq != _custodySeq) return;
      setState(() {
        _custody = c;
        _custodyLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _custodySeq) return;
      setState(() {
        _custody = null;
        _custodyError = e;
        _custodyLoading = false;
      });
    }
  }

  void _choose(String p) {
    if (_busy || _payment == p) return;
    setState(() {
      _payment = p;
      _error = null;
      _showErrors = false;
    });
    if (p == 'cash' && _custody == null && !_custodyLoading) _loadCustody();
  }

  /// Why the save button is disabled ('' = enabled).
  String _blockedReason() {
    final p = _payment;
    if (p == null) return tr('To‘lov turini tanlang');
    if (p == 'credit') return '';
    if (_custodyLoading) return tr('Pul manbai tekshirilmoqda…');
    if (_custodyError != null) return tr('Pul manbaini aniqlab bo‘lmadi — qayta urinib ko‘ring.');
    final c = _custody;
    if (c == null) return tr('Pul manbai tekshirilmoqda…');
    if (c.blocksSubmit) return c.blockedReason();
    return '';
  }

  Future<void> _save() async {
    if (_busy) return;
    final p = _payment;
    if (p == null || _blockedReason().isNotEmpty) return;
    String? account;
    if (p == 'cash') {
      final c = _custody!;
      if (!c.isReady(_account)) {
        setState(() => _showErrors = true);
        return;
      }
      account = c.accountToSend(_account);
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await widget.submit(p, account);
      if (!mounted) return;
      Navigator.of(context).pop(RecvSubmitOutcome.saved(r));
    } catch (e) {
      if (!mounted) return;
      _attempted = true;
      final code = e is ApiException ? e.code : null;
      if (_retryable(e)) {
        setState(() {
          _busy = false;
          _error = e;
        });
        return;
      }
      if (_isCashCode(code)) {
        // Kassa holati o'zgargan (smena ochildi/yopildi, T0 o'tdi, hisob arxivlandi) —
        // blokni serverdan QAYTA o'qiymiz; tanlov faqat yangi ro'yxatda qolsa saqlanadi.
        setState(() {
          _busy = false;
          _error = e;
        });
        if (p == 'cash') await _loadCustody();
        return;
      }
      Navigator.of(context).pop(RecvSubmitOutcome.rejected(e));
    }
  }

  Widget _payTile(String code, String label, String sub, IconData icon, Color color) {
    final on = _payment == code;
    return Semantics(
      inMutuallyExclusiveGroup: true,
      checked: on,
      button: true,
      child: InkWell(
        key: Key('recv-pay-$code'),
        borderRadius: BorderRadius.circular(kRadius),
        onTap: _busy ? null : () => _choose(code),
        child: Container(
          constraints: const BoxConstraints(minHeight: 64),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: on ? AppColors.accentSoft : AppColors.surface,
            borderRadius: BorderRadius.circular(kRadius),
            border: Border.all(color: on ? AppColors.accentStrong : AppColors.border, width: on ? 1.6 : 1),
          ),
          child: Row(children: [
            Icon(on ? Icons.radio_button_checked : Icons.radio_button_off, color: on ? AppColors.accentStrong : AppColors.muted),
            const SizedBox(width: 12),
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(color: color.withAlpha(40), borderRadius: BorderRadius.circular(10)),
              child: Icon(icon, color: color, size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(label, style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700)),
                Text(sub, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _custodyArea() {
    if (_payment != 'cash') return const SizedBox.shrink();
    if (_custodyLoading && _custody == null) {
      return Padding(
        key: const Key('recv-custody-loading'),
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(children: [
          const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 12),
          Flexible(child: Text(tr('Pul manbai tekshirilmoqda…'), style: TextStyle(color: AppColors.muted))),
        ]),
      );
    }
    if (_custodyError != null) {
      return ErrorBanner(key: const Key('recv-custody-error'), error: _custodyError, onRetry: _loadCustody);
    }
    final c = _custody;
    if (c == null) return const SizedBox.shrink();
    return CustodyBlock(
      info: c,
      selectedId: _account,
      showErrors: _showErrors,
      enabled: !_busy,
      onChanged: (v) => setState(() => _account = v),
    );
  }

  @override
  Widget build(BuildContext context) {
    final reason = _blockedReason();
    final err = _error;
    return PopScope(
      canPop: !_busy,
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
            child: Semantics(
              header: true,
              child: Text(tr('Tovar qanday olindi?'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            ),
          ),
          IconButton(
            key: const Key('recv-submit-close'),
            tooltip: tr('Yopish'),
            constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
            onPressed: _busy ? null : () => Navigator.of(context).pop(),
            icon: Icon(Icons.close, color: AppColors.muted),
          ),
        ]),
        Text(
          trArgs('{supplier} · {n} ta mahsulot', {'supplier': widget.supplierName, 'n': widget.lines}),
          style: TextStyle(fontSize: 13, color: AppColors.muted),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
          child: Row(children: [
            Expanded(
              child: Text(tr('Jami summa'),
                  style: TextStyle(fontSize: 13.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
            ),
            Text(formatCents(widget.totalCents),
                key: const Key('recv-submit-total'),
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppColors.accentStrong)),
          ]),
        ),
        const SizedBox(height: 14),
        _payTile('cash', tr('Naqd'), tr('Darrov to‘landi'), Icons.payments, AppColors.ok),
        const SizedBox(height: 10),
        _payTile('credit', tr('Qarzga'), tr('Yetkazib beruvchiga qarz bo‘ldi'), Icons.account_balance_wallet, AppColors.warn),
        const SizedBox(height: 12),
        _custodyArea(),
        if (err != null) ...[
          const SizedBox(height: 12),
          ErrorBanner(key: const Key('recv-submit-error'), error: err),
          if (_retryable(err)) ...[
            const SizedBox(height: 6),
            Text(tr('Qayta yuborish xavfsiz — bir kirim ikki marta yozilmaydi.'),
                key: const Key('recv-submit-safe-retry'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          ],
        ],
        const SizedBox(height: 14),
        if (reason.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.info_outline, size: 18, color: AppColors.warn),
              const SizedBox(width: 8),
              Expanded(
                child: Text(reason,
                    key: const Key('recv-submit-reason'), style: TextStyle(fontSize: 13, color: AppColors.text2)),
              ),
            ]),
          ),
        SizedBox(
          height: kPrimaryButtonHeight,
          child: ElevatedButton(
            key: const Key('recv-submit-save'),
            onPressed: (_busy || reason.isNotEmpty) ? null : _save,
            style: ElevatedButton.styleFrom(
              disabledBackgroundColor: AppColors.surface,
              disabledForegroundColor: AppColors.muted,
            ),
            child: _busy
                ? const SizedBox(
                    width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                : Text(_attempted && err != null && _retryable(err) ? tr('Qayta urinish') : tr('Kirimni saqlash')),
          ),
        ),
      ]),
    );
  }
}
