/// Package M4 shared UI: the debt / supplier payment sheet, the payment
/// method selector and the "no access" state.
///
/// The payment sheet never decides where cash comes from: for a CASH payment
/// it asks the server (`GET /cash/custody-preview?operation=...`, the same
/// resolver the writer runs) and renders the answer with [CustodyBlock].
/// Card/QR payments never touch a cash account.
library;

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/money_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';

/// Full-area state for a screen the signed-in employee may not open.
class NoAccessView extends StatelessWidget {
  /// Creates the view for the matrix [action].
  const NoAccessView({super.key, required this.action});

  /// Permission-matrix action (`sales.list`).
  final String action;

  @override
  Widget build(BuildContext context) => EmptyState(
        key: const Key('no-access'),
        icon: Icons.lock_outline,
        text: '${tr('Bu bo‘limni ko‘rish uchun ruxsatingiz yo‘q.')}\n${Perm.reason(action)}',
      );
}

/// Segmented cash / card / QR selector with 48 dp targets.
class PaymentMethodSelector extends StatelessWidget {
  /// Creates the selector.
  const PaymentMethodSelector({super.key, required this.value, required this.onChanged, this.enabled = true});

  /// Selected method.
  final String value;

  /// Selection change.
  final ValueChanged<String> onChanged;

  /// Selectable.
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(children: [
        for (final m in kPaymentMethods)
          Expanded(
            child: Semantics(
              inMutuallyExclusiveGroup: true,
              checked: value == m,
              button: true,
              child: InkWell(
                key: Key('pay-method-$m'),
                borderRadius: BorderRadius.circular(10),
                onTap: enabled ? () => onChanged(m) : null,
                child: Container(
                  constraints: const BoxConstraints(minHeight: kMinTouch),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: value == m ? AppColors.accent : Colors.transparent,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(
                      switch (m) { 'cash' => Icons.payments_outlined, 'card' => Icons.credit_card, _ => Icons.qr_code_2 },
                      size: 18,
                      color: value == m ? Colors.white : AppColors.muted,
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(paymentMethodLabel(m),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: value == m ? Colors.white : AppColors.text3)),
                    ),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

/// Result of a payment write: a decided 2xx, or — via [PaymentOutcome.unresolved]
/// — a write whose answer never arrived and which may already be recorded.
class PaymentOutcome {
  /// Creates an outcome.
  const PaymentOutcome({required this.balanceCents, this.paidCents, this.duplicate = false, this.requestedCents})
      : resolved = true;

  /// The sheet was closed after a write the server never answered: the caller
  /// must say so and re-read the balance instead of showing the old one.
  const PaymentOutcome.unresolved({this.requestedCents})
      : balanceCents = 0,
        paidCents = null,
        duplicate = false,
        resolved = false;

  /// Balance after the payment, as the server reports it (cents).
  final int balanceCents;

  /// What the server recorded (supplier payments report it), cents.
  final int? paidCents;

  /// The request was a replay of an already recorded payment.
  final bool duplicate;

  /// What the operator asked for (cents) — the sheet fills it in, so a caller
  /// can see that the server clamped the payment.
  final int? requestedCents;

  /// False only for [PaymentOutcome.unresolved]: the server never decided.
  final bool resolved;

  /// Copy that remembers the amount the sheet actually sent.
  PaymentOutcome _withRequested(int cents) => resolved
      ? PaymentOutcome(
          balanceCents: balanceCents, paidCents: paidCents, duplicate: duplicate, requestedCents: cents)
      : PaymentOutcome.unresolved(requestedCents: cents);
}

/// Performs the payment write. MUST throw on failure (an [ApiException]).
typedef PaymentSubmit = Future<PaymentOutcome> Function(
    {required int amountCents, required String method, String? cashAccountId, required String clientUuid});

/// Opens the payment sheet; resolves to the outcome of a 2xx write, or null
/// when the sheet was closed without one.
///
/// * [custodyOperation] — `CustodyOperation.debtPayment` / `supplierPayment`;
/// * [balanceCents] — what is owed (the amount is capped at it, rounded up to
///   whole som — the server clamps an overpayment to the balance anyway).
Future<PaymentOutcome?> showMoneyPaymentSheet(
  BuildContext context, {
  required String title,
  required String partyName,
  required String balanceLabel,
  required int balanceCents,
  required String custodyOperation,
  required PaymentSubmit submit,
}) =>
    showAppSheet<PaymentOutcome>(
      context,
      title: title,
      scrollable: false,
      isDismissible: false,
      builder: (ctx) => MoneyPaymentSheet(
        partyName: partyName,
        balanceLabel: balanceLabel,
        balanceCents: balanceCents,
        custodyOperation: custodyOperation,
        submit: submit,
      ),
    );

/// The body of [showMoneyPaymentSheet] (public for tests).
class MoneyPaymentSheet extends StatefulWidget {
  /// Creates the sheet body.
  const MoneyPaymentSheet({
    super.key,
    required this.partyName,
    required this.balanceLabel,
    required this.balanceCents,
    required this.custodyOperation,
    required this.submit,
  });

  /// Customer / supplier name.
  final String partyName;

  /// "Joriy qarz" / "Biz qarzmiz".
  final String balanceLabel;

  /// What is owed (cents).
  final int balanceCents;

  /// Custody preview operation.
  final String custodyOperation;

  /// The write.
  final PaymentSubmit submit;

  @override
  State<MoneyPaymentSheet> createState() => _MoneyPaymentSheetState();
}

class _MoneyPaymentSheetState extends State<MoneyPaymentSheet> {
  late final TextEditingController _amount;
  final DraftUuid _key = DraftUuid();
  String _method = 'cash';
  bool _tried = false;
  bool _busy = false;

  /// The server never DECIDED an attempt (connectivity, 5xx, a discarded stale
  /// answer) — the payment may already be recorded. Sticky for the life of the
  /// sheet: a later refusal does not prove the earlier, still-running attempt
  /// was not written, so the `client_uuid` is kept until a 2xx.
  bool _unknown = false;

  /// The LAST attempt came back decided — its refusal is shown next to the
  /// unknown warning rather than replacing it.
  bool _decided = false;

  /// The operator pressed the system Back while the sheet was locked: the
  /// gesture is swallowed, so the sheet SAYS why instead of looking frozen.
  bool _backBlocked = false;
  int? _sentCents; // oxirgi yuborilgan summa (clamp'ni ko'rsatish uchun)
  Object? _error;

  CustodyInfo? _custody;
  Object? _custodyError;
  bool _custodyLoading = false;
  String? _accountId;
  int _custodySeq = 0;

  /// Whole-som ceiling of the debt: the most the operator may type.
  int get _maxCents => ((widget.balanceCents + kCents - 1) ~/ kCents) * kCents;

  @override
  void initState() {
    super.initState();
    _amount = TextEditingController(text: _maxCents > 0 ? _group(centsToInput(_maxCents)) : '');
    _loadCustody();
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  static String _group(String digits) {
    final b = StringBuffer();
    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) b.write(' ');
      b.write(digits[i]);
    }
    return b.toString();
  }

  Future<void> _loadCustody() async {
    // Muzlagan (yoki yo'ldagi) yozuvga custody javobi TEGMAYDI: yangi javob
    // tanlangan hisobni tushirib yuborishi va shu bilan tanani — demak
    // `client_uuid` ni ham — o'zgartirishi mumkin edi.
    if (_method != 'cash' || _unknown || _busy) return;
    final seq = ++_custodySeq;
    setState(() {
      _custodyLoading = true;
      _custodyError = null;
    });
    try {
      final info = await fetchCustodyPreview(widget.custodyOperation);
      if (!mounted || seq != _custodySeq || _unknown) return;
      setState(() {
        _custody = info;
        _custodyLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _custodySeq || _unknown) return;
      setState(() {
        _custodyError = e;
        _custodyLoading = false;
      });
    }
  }

  NumParse get _parsed => parseMoney(_amount.text, wholeOnly: true);

  String? get _amountError {
    final p = _parsed;
    if (!p.ok) return moneyErrorText(p.error!, wholeOnly: true);
    if (p.value! > _maxCents) {
      return trArgs('To‘lov qarzdan oshmasin (ko‘pi bilan {max})', {'max': formatCents(_maxCents)});
    }
    return null;
  }

  /// Why the submit button is disabled (null = enabled).
  String? get _blockReason {
    // MUZLAGAN QORALAMA: hisob ham, summa ham tanlangan va o'zgarmaydi —
    // «Qayta yuborish» yangi custody javobiga bog'liq emas. Aks holda custody
    // xatosi yagona xavfsiz yo'lni (ayni kalit bilan qayta yuborish) yopardi.
    if (_unknown) return null;
    if (_method != 'cash') return null;
    // Qayta o'qilayotganda eski blok bilan yuborilmaydi — yangi qaror kutiladi.
    if (_custodyLoading) return tr('Pul manbai tekshirilmoqda…');
    if (_custodyError != null) return tr('Pul manbaini aniqlab bo‘lmadi — qayta urinib ko‘ring.');
    final c = _custody;
    if (c == null) return tr('Pul manbai tekshirilmoqda…');
    if (c.blocksSubmit) return c.blockedReason();
    return null;
  }

  Future<void> _submit() async {
    setState(() => _tried = true);
    if (_amountError != null || _blockReason != null || _busy) return;
    final c = _custody;
    if (_method == 'cash' && c != null && !c.isReady(_accountId)) return; // tanlov shart
    final amount = _parsed.value!;
    final account = _method == 'cash' ? c?.accountToSend(_accountId) : null;
    final uuid = _key.forDraft(MoneyApi.paymentBody(amountCents: amount, method: _method, cashAccountId: account));
    setState(() {
      _busy = true;
      _error = null;
      _sentCents = amount;
    });
    try {
      final out = await widget.submit(amountCents: amount, method: _method, cashAccountId: account, clientUuid: uuid);
      if (!mounted) return;
      _key.rotate();
      Navigator.of(context).pop(out._withRequested(amount));
    } catch (e) {
      if (!mounted) return;
      // 5xx ham NOMA'LUM: shlyuz 502/504 ni server yozib bo'lgandan KEYIN
      // qaytarishi mumkin — shuning uchun qoralama muzlatiladi va qayta
      // yuborish AYNAN o'sha client_uuid bilan ketadi.
      final unknown = moneyOutcomeUnknown(e);
      setState(() {
        _busy = false;
        _error = e;
        _decided = !unknown;
        // YOPISHQOQ: keyingi aniq rad etish oldingi (hali yakunlanmagan)
        // urinish yozilmasligini ISBOTLAMAYDI — kalit saqlanib qoladi.
        _unknown = _unknown || unknown;
      });
      if (!_unknown && e is ApiException && _isCustodyCode(e.code)) _loadCustody();
    }
  }

  static bool _isCustodyCode(String? code) =>
      code != null &&
      (code.startsWith('CASH_') ||
          code.startsWith('TILL_') ||
          code == 'OPEN_SHIFT_REQUIRED' ||
          code == 'LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER' ||
          code == 'ACCOUNT_ARCHIVED' ||
          code == 'ACCOUNT_NOT_FOUND');

  @override
  Widget build(BuildContext context) {
    final locked = _busy || _unknown;
    final block = _blockReason;
    final amountErr = _tried ? _amountError : null;
    // Tizim «orqaga» tugmasi yozuvni JIMGINA bekor qilmasin: so'rov serverda
    // yozilib qolishi mumkin. Chiqish faqat «Yopish» orqali — u holda
    // chaqiruvchiga natija noma'lumligi aytiladi. Ammo JIMGINA yutib yuborish
    // ham yaramaydi: operator oyna qotib qolgan deb o'ylaydi, shuning uchun
    // nega chiqib bo'lmasligi AYTILADI.
    return PopScope(
      canPop: !locked,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop || !mounted) return;
        setState(() => _backBlocked = true);
      },
      child: _sheet(locked, block, amountErr),
    );
  }

  Widget _sheet(bool locked, String? block, String? amountErr) {
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Flexible(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(kRadius)),
              child: Column(children: [
                Text('${widget.partyName} · ${widget.balanceLabel}',
                    textAlign: TextAlign.center, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
                const SizedBox(height: 4),
                Text(formatCents(widget.balanceCents),
                    key: const Key('pay-balance'),
                    style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.danger)),
              ]),
            ),
            const SizedBox(height: 16),
            MoneyField(
              key: const Key('pay-amount'),
              controller: _amount,
              enabled: !locked,
              label: tr('To‘lov summasi'),
              helperText: tr('Butun so‘mda. Qarzdan ortig‘i qabul qilinmaydi.'),
              errorText: amountErr,
              onChanged: (_) => setState(() {}),
              textInputAction: TextInputAction.done,
            ),
            const SizedBox(height: 14),
            Text(tr('To‘lov usuli'),
                style: TextStyle(fontSize: 12.5, color: AppColors.text3, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            PaymentMethodSelector(
              value: _method,
              enabled: !locked,
              onChanged: (m) {
                if (m == _method) return;
                setState(() {
                  _method = m;
                  _accountId = null;
                  _error = null;
                });
                _loadCustody();
              },
            ),
            if (_method == 'cash') ...[
              const SizedBox(height: 14),
              _custodySection(locked),
            ],
            if (_busy) ...[
              const SizedBox(height: 14),
              ErrorBanner(
                key: const Key('pay-inflight'),
                severity: BannerSeverity.info,
                message: tr('So‘rov serverga yuborildi — javob kutilmoqda. Javob kelguncha bu oyna yopilmaydi.'),
              ),
            ],
            // Qulf tugagach eslatma ham yo'qoladi (chiqish endi ishlaydi).
            if (_backBlocked && locked) ...[
              const SizedBox(height: 14),
              ErrorBanner(
                key: const Key('pay-back-blocked'),
                severity: BannerSeverity.warning,
                message: _busy
                    ? tr('Javob kelmaguncha chiqib bo‘lmaydi: to‘lov serverda yozilayotgan bo‘lishi mumkin.')
                    : tr('Chiqish uchun «Yopish» tugmasini bosing — natija noma’lumligi aytiladi va qarz '
                        'qoldig‘i serverdan qayta o‘qiladi.'),
                onDismiss: () => setState(() => _backBlocked = false),
              ),
            ],
            if (_unknown) ...[
              const SizedBox(height: 14),
              ErrorBanner(
                key: const Key('pay-unknown'),
                severity: BannerSeverity.warning,
                message: _decided
                    ? tr('Oldingi urinish natijasi noma’lum — to‘lov yozilgan bo‘lishi mumkin. Shuning uchun '
                        'forma bloklangan: AYNAN shu to‘lovni qayta yuboring yoki «Yopish» bilan chiqing.')
                    : tr('Server javobi kelmadi — to‘lov yozilgan-yozilmagani noma’lum. '
                        '«Qayta yuborish» xavfsiz: to‘lov ikki marta yozilmaydi.'),
              ),
            ],
            // Aniq rad etish noma'lum ogohlantirishni YASHIRMAYDI — ikkalasi ham ko'rsatiladi.
            if (_error != null && _decided) ...[
              const SizedBox(height: 14),
              ErrorBanner(key: const Key('pay-error'), error: _error),
            ],
          ]),
        ),
      ),
      StickyActionBar(
        label: _unknown ? tr('Qayta yuborish') : tr('To‘lovni tasdiqlash'),
        icon: _unknown ? Icons.refresh : Icons.check,
        busy: _busy,
        enabled: block == null,
        disabledReason: block,
        onPressed: _submit,
        secondaryLabel: tr('Yopish'),
        onSecondary: () => Navigator.of(context)
            .pop(_unknown ? PaymentOutcome.unresolved(requestedCents: _sentCents) : null),
      ),
    ]);
  }

  Widget _custodySection(bool locked) {
    if (_custodyError != null) {
      return ErrorBanner(
        key: const Key('pay-custody-error'),
        error: _custodyError,
        onRetry: locked ? null : _loadCustody,
      );
    }
    final c = _custody;
    if (c == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: LinearProgressIndicator(minHeight: 2),
      );
    }
    return CustodyBlock(
      info: c,
      selectedId: _accountId,
      enabled: !locked,
      showErrors: _tried,
      onChanged: (id) => setState(() => _accountId = id),
    );
  }
}
