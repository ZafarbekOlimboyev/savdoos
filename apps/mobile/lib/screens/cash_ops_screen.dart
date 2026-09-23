import 'package:flutter/material.dart';

import '../api.dart';
import '../api/money_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';
import 'money_payment_sheet.dart';

const _expenseCats = [
  ('Ijara', Icons.home_outlined),
  ('Kommunal', Icons.bolt_outlined),
  ('Maosh', Icons.badge_outlined),
  ('Boshqa', Icons.more_horiz),
];

/// Cash in / expense / collection on the OPEN SHIFT of the employee's branch
/// (`POST /cash/ops`, `hisobot.view`).
///
/// The screen first asks the server where the cash goes
/// (`GET /cash/custody-preview?operation=collection_destination`): it names
/// the shift's branch, says clearly when there is NO open shift, and — for a
/// collection — offers EXACTLY the active SAFEs the writer accepts
/// (`destination_safe_id`, never preselected).
class CashOpsScreen extends StatefulWidget {
  /// Creates the screen.
  const CashOpsScreen({super.key});

  @override
  State<CashOpsScreen> createState() => _CashOpsScreenState();
}

class _CashOpsScreenState extends State<CashOpsScreen> {
  String _type = CashOpType.expense;
  String _cat = 'Ijara';
  final _amount = TextEditingController();
  final _note = TextEditingController();
  final DraftUuid _key = DraftUuid();
  List<CashOpEntry>? _today;
  Object? _todayError;
  bool _todayLoading = false;
  int _todaySeq = 0;

  CustodyInfo? _custody;
  Object? _custodyError;
  bool _custodyLoading = false;
  int _custodySeq = 0;
  String? _safeId;

  bool _tried = false;
  bool _busy = false;
  bool _unknown = false;
  Object? _error;
  String? _notice;

  @override
  void initState() {
    super.initState();
    if (Perm.allows('cash.ops.create')) {
      _loadCustody();
      _loadToday();
    }
  }

  /// Today's movements (`GET /cash/ops`) — rendered inline, no nested scroll.
  Future<void> _loadToday() async {
    final seq = ++_todaySeq;
    setState(() {
      _todayLoading = true;
      _todayError = null;
    });
    try {
      final rows = await MoneyApi.cashOpsToday();
      if (!mounted || seq != _todaySeq) return;
      setState(() {
        _today = rows;
        _todayLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _todaySeq) return;
      setState(() {
        _todayError = e;
        _todayLoading = false;
      });
    }
  }

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _loadCustody() async {
    final seq = ++_custodySeq;
    setState(() {
      _custodyLoading = true;
      _custodyError = null;
    });
    try {
      final info = await fetchCustodyPreview(CustodyOperation.collectionDestination);
      if (!mounted || seq != _custodySeq) return;
      setState(() {
        _custody = info;
        _custodyLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _custodySeq) return;
      setState(() {
        _custodyError = e;
        _custodyLoading = false;
      });
    }
  }

  bool get _noShift => _custody?.mode == CustodyMode.blocked && _custody?.reason == 'OPEN_SHIFT_REQUIRED';

  String? get _amountError {
    final p = parseMoney(_amount.text, wholeOnly: true);
    return p.ok ? null : moneyErrorText(p.error!, wholeOnly: true);
  }

  /// Why the submit button is disabled (null = enabled).
  String? get _blockReason {
    if (_custodyError != null) return tr('Kassa holatini aniqlab bo‘lmadi — qayta urinib ko‘ring.');
    final c = _custody;
    if (c == null || _custodyLoading) return tr('Kassa holati tekshirilmoqda…');
    if (_noShift) return tr('Ochiq smena yo‘q — kassa amallari faqat ochiq smenaga yoziladi.');
    // Inkassa manzili (seyf) blokini FAQAT inkassatsiya uchun qo'llaymiz: kirim/xarajatni
    // server o'zi tekshiradi (smena kassasining boshqa rad etishlari o'sha yerda xabar qilinadi).
    if (_type == CashOpType.collection && c.blocksSubmit) return c.blockedReason();
    return null;
  }

  /// Reason sent to the server. The expense category is stored as its Uzbek
  /// key (data, like the desktop and the previous mobile build); only the
  /// screen translates it.
  String? get _reason {
    final note = _note.text.trim();
    if (_type == CashOpType.expense) return note.isEmpty ? _cat : '$_cat · $note';
    return note.isEmpty ? null : note;
  }

  /// A stored reason for display: a leading expense category key is translated.
  static String displayReason(String reason) {
    for (final c in _expenseCats) {
      if (reason == c.$1) return tr(c.$1);
      if (reason.startsWith('${c.$1} · ')) return '${tr(c.$1)}${reason.substring(c.$1.length)}';
    }
    return reason;
  }

  Future<void> _save() async {
    setState(() => _tried = true);
    if (_amountError != null || _blockReason != null || _busy) return;
    final c = _custody!;
    if (_type == CashOpType.collection && !c.isReady(_safeId)) return; // seyf tanlanishi shart
    final amount = parseMoney(_amount.text, wholeOnly: true).value!;
    final dest = _type == CashOpType.collection ? c.accountToSend(_safeId) : null;
    if (_type != CashOpType.payin && !_unknown) {
      final safe = c.options.where((o) => o.id == dest).map((o) => o.code).firstOrNull;
      final ok = await confirmDestructive(
        context,
        title: _type == CashOpType.collection ? tr('Inkassatsiyani tasdiqlang') : tr('Xarajatni tasdiqlang'),
        message: trArgs('Kassadan {sum} chiqariladi.', {'sum': formatCents(amount)}),
        details: [
          if (c.branchName != null) trArgs('Smena filiali: {name}', {'name': c.branchName}),
          if (safe != null) trArgs('Qabul qiluvchi seyf: {code}', {'code': safe}),
          if ((_reason ?? '').isNotEmpty) trArgs('Izoh: {text}', {'text': displayReason(_reason!)}),
        ],
        confirmLabel: tr('Chiqarish'),
      );
      if (!ok || !mounted) return;
    }
    final body = MoneyApi.cashOpBody(type: _type, amountCents: amount, reason: _reason, destinationSafeId: dest);
    final uuid = _key.forDraft(body);
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final r = await MoneyApi.cashOp(
          type: _type, amountCents: amount, reason: _reason, destinationSafeId: dest, clientUuid: uuid);
      if (!mounted) return;
      _key.rotate();
      _amount.clear();
      _note.clear();
      setState(() {
        _busy = false;
        _unknown = false;
        _tried = false;
        _safeId = null;
        _notice = r.duplicate
            ? tr('Bu amal avval saqlangan edi — qayta yozilmadi.')
            : trArgs('Saqlandi: {type} {sum}', {'type': cashOpLabel(_type), 'sum': formatCents(amount)});
      });
      await _loadToday();
    } catch (e) {
      if (!mounted) return;
      final connectivity = isConnectivityError(e);
      setState(() {
        _busy = false;
        _error = e;
        _unknown = connectivity;
      });
      if (!connectivity && e is ApiException) {
        final code = e.code ?? '';
        if (code == 'OPEN_SHIFT_REQUIRED' || code.startsWith('CASH_') || code.startsWith('TILL_') ||
            code.startsWith('LEGACY_')) {
          _loadCustody();
        }
      }
    }
  }

  void _setType(String t) {
    if (t == _type || _unknown) return;
    setState(() {
      _type = t;
      _safeId = null;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows('cash.ops.create')) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Kassa kirim / chiqim'))),
        body: const NoAccessView(action: 'cash.ops.create'),
      );
    }
    final block = _blockReason;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Kassa kirim / chiqim'))),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async {
              await _loadCustody();
              await _loadToday();
            },
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(kGutter, 12, kGutter, 24),
              children: [
                _shiftCard(),
                const SizedBox(height: 14),
                _typeToggle(),
                const SizedBox(height: 16),
                MoneyField(
                  key: const Key('cash-amount'),
                  controller: _amount,
                  enabled: !_busy && !_unknown,
                  label: tr('Summa'),
                  errorText: _tried ? _amountError : null,
                  onChanged: (_) => setState(() {}),
                ),
                if (_type == CashOpType.expense) ...[
                  const SizedBox(height: 14),
                  Text(tr('Xarajat turi'),
                      style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 8, children: [for (final c in _expenseCats) _catChip(c.$1, c.$2)]),
                ],
                if (_type == CashOpType.collection && _custody != null && !_noShift) ...[
                  const SizedBox(height: 14),
                  CustodyBlock(
                    key: const Key('cash-safe-block'),
                    info: _custody!,
                    title: tr('Qabul qiluvchi seyf'),
                    selectedId: _safeId,
                    enabled: !_busy && !_unknown,
                    showErrors: _tried,
                    onChanged: (id) => setState(() => _safeId = id),
                  ),
                ],
                const SizedBox(height: 14),
                TextField(
                  key: const Key('cash-note'),
                  controller: _note,
                  enabled: !_busy && !_unknown,
                  maxLength: 150,
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(labelText: tr('Izoh (ixtiyoriy)'), counterText: ''),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  _unknown
                      ? ErrorBanner(
                          key: const Key('cash-unknown'),
                          severity: BannerSeverity.warning,
                          message: tr('Server javobi kelmadi — amal yozilgan-yozilmagani noma’lum. '
                              '«Qayta yuborish» xavfsiz: amal ikki marta yozilmaydi.'),
                        )
                      : ErrorBanner(key: const Key('cash-error'), error: _error),
                ],
                if (_notice != null) ...[
                  const SizedBox(height: 12),
                  ErrorBanner(
                    key: const Key('cash-notice'),
                    severity: BannerSeverity.info,
                    message: _notice!,
                    onDismiss: () => setState(() => _notice = null),
                  ),
                ],
                const SizedBox(height: 24),
                Text(tr('Bugungi harakatlar'), style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                _todayList(),
              ],
            ),
          ),
        ),
        StickyActionBar(
          label: _unknown ? tr('Qayta yuborish') : tr('Saqlash'),
          icon: _unknown ? Icons.refresh : Icons.check,
          busy: _busy,
          enabled: block == null,
          disabledReason: block,
          onPressed: _save,
          secondaryLabel: _unknown ? tr('Bekor qilish') : null,
          onSecondary: () {
            // Natija noma'lum: yangi amal — yangi kalit; ro'yxat serverdagi HAQIQATni ko'rsatadi.
            _key.rotate();
            setState(() {
              _unknown = false;
              _error = null;
            });
            _loadToday();
          },
        ),
      ]),
    );
  }

  Widget _shiftCard() {
    if (_custodyError != null) {
      return ErrorBanner(key: const Key('cash-custody-error'), error: _custodyError, onRetry: _loadCustody);
    }
    final c = _custody;
    if (c == null) {
      return const Padding(padding: EdgeInsets.symmetric(vertical: 10), child: LinearProgressIndicator(minHeight: 2));
    }
    if (_noShift) {
      return ErrorBanner(
        key: const Key('cash-no-shift'),
        severity: BannerSeverity.warning,
        message: tr('Ochiq smena yo‘q. Kassa kirim/chiqimi faqat filialning ochiq smenasiga yoziladi — '
            'avval POS’da smena oching, keyin qayta tekshiring.'),
        onRetry: _custodyLoading ? null : _loadCustody,
        retryLabel: tr('Qayta tekshirish'),
      );
    }
    final branch = c.branchName ?? Session.instance.actorBranch?.name;
    final current = Session.instance.currentBranch;
    final other = current != null && c.branchId != null && current.id != c.branchId;
    return Container(
      key: const Key('cash-shift'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: other ? AppColors.warn : AppColors.border),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.point_of_sale, color: AppColors.accentStrong),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(branch == null ? tr('Ochiq smenaga yoziladi') : trArgs('Ochiq smenaga yoziladi: {branch}', {'branch': branch}),
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            if (other) ...[
              const SizedBox(height: 4),
              Text(
                  trArgs('Diqqat: siz «{current}» filialini ko‘ryapsiz, lekin kassa amali sizning filialingiz smenasiga yoziladi.',
                      {'current': current.name}),
                  key: const Key('cash-branch-warning'),
                  style: const TextStyle(fontSize: 12.5, color: AppColors.warn)),
            ],
          ]),
        ),
      ]),
    );
  }

  Widget _typeToggle() {
    Widget seg(String t, String label, Color c) {
      final on = _type == t;
      return Expanded(
        child: Semantics(
          selected: on,
          button: true,
          child: InkWell(
            key: Key('cash-type-$t'),
            borderRadius: BorderRadius.circular(10),
            onTap: () => _setType(t),
            child: Container(
              constraints: const BoxConstraints(minHeight: kMinTouch),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: on ? c.withValues(alpha: 0.18) : Colors.transparent,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: on ? c : AppColors.muted)),
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
          color: AppColors.card, borderRadius: BorderRadius.circular(13), border: Border.all(color: AppColors.border)),
      child: Row(children: [
        seg(CashOpType.payin, tr('Kirim'), AppColors.ok),
        seg(CashOpType.expense, tr('Xarajat'), AppColors.danger),
        seg(CashOpType.collection, tr('Inkassatsiya'), AppColors.accentStrong),
      ]),
    );
  }

  Widget _catChip(String cat, IconData icon) {
    final on = _cat == cat;
    return Semantics(
      selected: on,
      button: true,
      child: InkWell(
        key: Key('cash-cat-$cat'),
        borderRadius: BorderRadius.circular(11),
        onTap: _unknown ? null : () => setState(() => _cat = cat),
        child: Container(
          constraints: const BoxConstraints(minHeight: kMinTouch),
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: on ? AppColors.accentSoft : AppColors.card,
            borderRadius: BorderRadius.circular(11),
            border: Border.all(color: on ? AppColors.accent : AppColors.border, width: on ? 1.5 : 1),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 16, color: on ? AppColors.accentStrong : AppColors.muted),
            const SizedBox(width: 7),
            Text(tr(cat),
                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: on ? AppColors.accentStrong : AppColors.text3)),
          ]),
        ),
      ),
    );
  }

  Widget _todayList() {
    final rows = _today;
    if (_todayError != null) {
      return ErrorBanner(key: const Key('cash-today-error'), error: _todayError, onRetry: _loadToday);
    }
    if (rows == null) {
      return const Padding(padding: EdgeInsets.symmetric(vertical: 16), child: Center(child: CircularProgressIndicator()));
    }
    if (rows.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Text(tr('Bugun harakat yo‘q'), style: TextStyle(color: AppColors.muted)),
      );
    }
    return AppCard(
      key: const Key('cash-today'),
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Column(children: [
        if (_todayLoading) const LinearProgressIndicator(minHeight: 2),
        for (var i = 0; i < rows.length; i++) ...[
          if (i > 0) Divider(height: 1, color: AppColors.border),
          _opRow(rows[i]),
        ],
      ]),
    );
  }

  Widget _opRow(CashOpEntry r) {
    final c = r.isIn ? AppColors.ok : AppColors.danger;
    final label = cashOpLabel(r.type);
    return Container(
      constraints: const BoxConstraints(minHeight: 56),
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(children: [
        Icon(r.isIn ? Icons.south_west : Icons.north_east, size: 16, color: c),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(r.reason == null ? label : displayReason(r.reason!),
                maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text('$label · ${hm(r.at)} · ${r.employee ?? '—'}', style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
          ]),
        ),
        Text('${r.isIn ? '+' : '−'}${formatCents(r.amountCents)}',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: c)),
      ]),
    );
  }
}
