/// Cash custody ("where does the cash physically come from / go to") block.
///
/// The server computes the block — `GET /purchases/{id}` (`cash_custody`) or
/// `GET /cash/custody-preview?operation=...` — with the SAME resolver its
/// writer uses; the client never re-implements it:
///
/// | mode                  | UI                                             | sends `cash_account_id` |
/// |-----------------------|------------------------------------------------|-------------------------|
/// | NOT_APPLICABLE        | nothing                                        | no                      |
/// | NOT_REQUIRED          | nothing                                        | no                      |
/// | SERVER_RESOLVED       | read-only "Pul manbai: <code>"                 | no                      |
/// | OPERATOR_MUST_CHOOSE  | required choice among EXACTLY `options`, none preselected (even with one option) | the chosen id |
/// | BLOCKED (or unknown)  | localized reason, submit must be disabled      | — (blocked)             |
library;

import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../theme.dart';
import '../ui/tokens.dart';

/// Custody modes (server `lot_correction.MODE_*`).
enum CustodyMode {
  /// Credit document / no cash involved.
  notApplicable,

  /// Pre-cutover: the server resolves the drawer by itself.
  notRequired,

  /// The actor's open shift till — nothing to send.
  serverResolved,

  /// The operator must pick one of the offered accounts.
  operatorMustChoose,

  /// This actor cannot move this cash now (reason code given).
  blocked,
}

/// A cash account offered by the server.
@immutable
class CustodyAccount {
  /// Creates an account.
  const CustodyAccount({required this.id, required this.type, required this.code, this.currency = 'UZS'});

  /// Parses `{id,type,code,currency}`.
  factory CustodyAccount.fromJson(Map<String, dynamic> j) => CustodyAccount(
        id: '${j['id']}',
        type: '${j['type'] ?? ''}'.toUpperCase(),
        code: '${j['code'] ?? ''}',
        currency: '${j['currency'] ?? 'UZS'}',
      );

  /// Account id.
  final String id;

  /// `TILL` or `SAFE`.
  final String type;

  /// Human code (`K-01`).
  final String code;

  /// Currency code.
  final String currency;

  /// Localized type name.
  String get typeLabel => type == 'SAFE' ? tr('Seyf') : (type == 'TILL' ? tr('Kassa') : type);
}

/// Parsed custody block `{mode, reason, resolved, options, branch}`.
@immutable
class CustodyInfo {
  /// Creates a block.
  const CustodyInfo({
    required this.mode,
    this.rawMode = '',
    this.reason,
    this.resolved,
    this.options = const [],
    this.branchId,
    this.branchName,
  });

  /// Parses the server block. An unknown/missing mode FAILS CLOSED as
  /// [CustodyMode.blocked].
  factory CustodyInfo.fromJson(Map<String, dynamic>? j) {
    final m = '${j?['mode'] ?? ''}';
    final mode = switch (m) {
      'NOT_APPLICABLE' => CustodyMode.notApplicable,
      'NOT_REQUIRED' => CustodyMode.notRequired,
      'SERVER_RESOLVED' => CustodyMode.serverResolved,
      'OPERATOR_MUST_CHOOSE' => CustodyMode.operatorMustChoose,
      _ => CustodyMode.blocked,
    };
    final res = j?['resolved'];
    final br = j?['branch'];
    return CustodyInfo(
      mode: mode,
      rawMode: m,
      reason: j?['reason']?.toString() ?? (mode == CustodyMode.blocked && m != 'BLOCKED' ? 'CUSTODY_UNKNOWN_MODE' : null),
      resolved: res is Map ? CustodyAccount.fromJson(res.cast<String, dynamic>()) : null,
      options: [
        for (final o in (j?['options'] as List? ?? const []))
          if (o is Map) CustodyAccount.fromJson(o.cast<String, dynamic>())
      ],
      branchId: br is Map ? br['id']?.toString() : null,
      branchName: br is Map ? br['name']?.toString() : null,
    );
  }

  /// Mode.
  final CustodyMode mode;

  /// Mode as the server sent it.
  final String rawMode;

  /// Reason code (BLOCKED / OPERATOR_MUST_CHOOSE).
  final String? reason;

  /// The server-resolved account (SERVER_RESOLVED).
  final CustodyAccount? resolved;

  /// The accounts to choose from (OPERATOR_MUST_CHOOSE).
  final List<CustodyAccount> options;

  /// Branch the accounts belong to.
  final String? branchId, branchName;

  /// True when the operator has to pick an account.
  bool get needsChoice => mode == CustodyMode.operatorMustChoose;

  /// True when the action must not be submitted at all.
  bool get blocksSubmit => mode == CustodyMode.blocked || (needsChoice && options.isEmpty);

  /// Whether [selectedId] completes the block (always true when no choice is needed).
  bool isReady(String? selectedId) {
    if (mode == CustodyMode.blocked) return false;
    if (!needsChoice) return true;
    return selectedId != null && options.any((o) => o.id == selectedId);
  }

  /// `cash_account_id` to send: the chosen id ONLY for OPERATOR_MUST_CHOOSE,
  /// otherwise null (the server resolves / nothing moves).
  String? accountToSend(String? selectedId) => needsChoice && isReady(selectedId) ? selectedId : null;

  /// Localized explanation of why the action is blocked (empty if not blocked).
  String blockedReason() {
    if (mode == CustodyMode.blocked) {
      // ⚠️  BLOCKED da bu kod "hisobni TANLANG" degani EMAS: ro'yxat umuman
      //     ko'rsatilmaydi va tanlash bilan hech narsa hal bo'lmaydi — server
      //     MANBANI aniqlay olmadi (odatda smena kassasiz ochilgan). Operatorga
      //     ekranda yo'q narsani tanlashni aytmaymiz.
      if (reason == 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER') {
        return tr(
            'Naqd manbaini server aniqlay olmadi — ochiq smena kassasiz ochilgan bo‘lishi mumkin. Kassir smenani yopib, kassa tanlab yangi smena ochsin, so‘ng amalni takrorlang.');
      }
      return serverText(reason ?? 'CASH_LEDGER_UNAVAILABLE');
    }
    if (needsChoice && options.isEmpty) {
      return tr('Bu filialda faol kassa yoki seyf yo‘q — administrator naqd hisoblarni sozlashi kerak.');
    }
    return '';
  }
}

/// Server operations the preview endpoint answers for.
abstract final class CustodyOperation {
  /// Cash receiving payment.
  static const receivingPayment = 'receiving_payment';

  /// Customer debt payment in cash.
  static const debtPayment = 'debt_payment';

  /// Supplier payment in cash.
  static const supplierPayment = 'supplier_payment';

  /// Cash collection destination (SAFE).
  static const collectionDestination = 'collection_destination';
}

/// `GET /cash/custody-preview?operation=` -> [CustodyInfo]. Extra [query]
/// values (e.g. a document id) are passed through.
Future<CustodyInfo> fetchCustodyPreview(String operation, {Map<String, Object?> query = const {}}) async {
  final r = await Api.getJson('/cash/custody-preview', query: {'operation': operation, ...query});
  return CustodyInfo.fromJson(r.map);
}

/// Renders a [CustodyInfo] and, for OPERATOR_MUST_CHOOSE, a required choice.
///
/// The parent owns the selection ([selectedId] / [onChanged]) and sends
/// `info.accountToSend(selectedId)`. A selection that is no longer among the
/// options is cleared (reported through [onChanged]).
class CustodyBlock extends StatefulWidget {
  /// Creates the block.
  const CustodyBlock({
    super.key,
    required this.info,
    required this.selectedId,
    required this.onChanged,
    this.showErrors = false,
    this.title,
    this.enabled = true,
  });

  /// The server block.
  final CustodyInfo info;

  /// Chosen account id.
  final String? selectedId;

  /// Selection changes.
  final ValueChanged<String?> onChanged;

  /// Show "choose an account" as an error (after a submit attempt).
  final bool showErrors;

  /// Heading (default "Pul manbai").
  final String? title;

  /// Selectable.
  final bool enabled;

  @override
  State<CustodyBlock> createState() => _CustodyBlockState();
}

class _CustodyBlockState extends State<CustodyBlock> {
  @override
  void initState() {
    super.initState();
    _dropStale();
  }

  @override
  void didUpdateWidget(covariant CustodyBlock old) {
    super.didUpdateWidget(old);
    _dropStale();
  }

  void _dropStale() {
    final sel = widget.selectedId;
    if (sel == null) return;
    final stale = !widget.info.needsChoice || !widget.info.options.any((o) => o.id == sel);
    if (stale) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && widget.selectedId == sel) widget.onChanged(null);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final info = widget.info;
    final title = widget.title ?? tr('Pul manbai');
    switch (info.mode) {
      case CustodyMode.notApplicable:
      case CustodyMode.notRequired:
        return const SizedBox.shrink();
      case CustodyMode.serverResolved:
        final a = info.resolved;
        return _frame(
          child: Row(children: [
            Icon(Icons.point_of_sale, color: AppColors.accentStrong),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                trArgs('{title}: {code}', {'title': title, 'code': a == null ? '—' : '${a.code} (${a.typeLabel})'}),
                key: const Key('custody-resolved'),
                style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700),
              ),
            ),
          ]),
          footnote: tr('Ochiq smenangiz kassasi — server o‘zi aniqlaydi'),
        );
      case CustodyMode.blocked:
        return _frame(
          danger: true,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.block, color: AppColors.danger),
            const SizedBox(width: 10),
            Expanded(
              child: Text(info.blockedReason(),
                  key: const Key('custody-blocked'), style: TextStyle(fontSize: 14, color: AppColors.text, height: 1.35)),
            ),
          ]),
        );
      case CustodyMode.operatorMustChoose:
        return _choose(info, title);
    }
  }

  Widget _choose(CustodyInfo info, String title) {
    if (info.options.isEmpty) {
      return _frame(
        danger: true,
        child: Text(info.blockedReason(), key: const Key('custody-no-options'), style: const TextStyle(fontSize: 14)),
      );
    }
    final missing = widget.showErrors && !info.isReady(widget.selectedId);
    return _frame(
      danger: missing,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('$title *', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        Text(
          info.branchName == null
              ? tr('Naqd pul qaysi hisobdan o‘tishini tanlang')
              : trArgs('Naqd pul qaysi hisobdan o‘tishini tanlang ({branch} filiali)', {'branch': info.branchName}),
          style: TextStyle(fontSize: 12.5, color: AppColors.muted),
        ),
        const SizedBox(height: 6),
        for (final o in info.options) _option(o),
        if (missing)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(tr('Pul manbaini tanlang'),
                key: const Key('custody-required'), style: const TextStyle(color: AppColors.danger, fontSize: 13)),
          ),
      ]),
    );
  }

  Widget _option(CustodyAccount o) {
    final sel = widget.selectedId == o.id;
    return Semantics(
      inMutuallyExclusiveGroup: true,
      checked: sel,
      button: true,
      label: '${o.code} ${o.typeLabel}',
      child: InkWell(
        key: Key('custody-option-${o.id}'),
        borderRadius: BorderRadius.circular(10),
        onTap: widget.enabled ? () => widget.onChanged(o.id) : null,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: kMinTouch + 4),
          child: Row(children: [
            Icon(sel ? Icons.radio_button_checked : Icons.radio_button_off,
                color: sel ? AppColors.accentStrong : AppColors.muted),
            const SizedBox(width: 12),
            Icon(o.type == 'SAFE' ? Icons.lock_outline : Icons.point_of_sale, size: 20, color: AppColors.text3),
            const SizedBox(width: 8),
            Expanded(
              child: Text('${o.code} · ${o.typeLabel}${o.currency.isNotEmpty && o.currency != 'UZS' ? ' · ${o.currency}' : ''}',
                  style: TextStyle(fontSize: 15, fontWeight: sel ? FontWeight.w800 : FontWeight.w600)),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _frame({required Widget child, String? footnote, bool danger = false}) => Container(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: danger ? AppColors.dangerSoft : AppColors.surface,
          borderRadius: BorderRadius.circular(kRadius),
          border: Border.all(color: danger ? AppColors.danger.withAlpha(120) : AppColors.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          child,
          if (footnote != null) ...[
            const SizedBox(height: 6),
            Text(footnote, style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ]),
      );
}
