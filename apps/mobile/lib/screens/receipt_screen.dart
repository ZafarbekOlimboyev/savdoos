/// Read-only view of the SERVER receipt (`binos.receipt.v1`), laid out like
/// the desktop renderer (`packages/shared/src/receipt/layout.ts`): header,
/// meta, lines, totals, payments / refund, footer. Every amount is the
/// server's stored value — nothing is recomputed. RETURN receipts show their
/// amounts with a minus sign. Sharing sends plain text; mobile never prints.
library;

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../api/money_api.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../theme.dart';
import '../ui/ui.dart';
import 'money_payment_sheet.dart';

/// Shares [text] (overridable in tests).
typedef ShareText = Future<void> Function(String text, {String? subject});

Future<void> _defaultShare(String text, {String? subject}) async {
  await Share.share(text, subject: subject);
}

/// The app-wide share hook used by receipt screens.
ShareText receiptShare = _defaultShare;

/// A 2-decimal server amount as whole som or 2 decimals (`"4224.00"` ->
/// `4 224`, `"12.50"` -> `12,50`); `?` for a malformed value.
String receiptMoney(String v) {
  final c = scaledFromServer(v, 2);
  return c == null ? '?' : formatCents(c, currency: false);
}

/// A 3-decimal server quantity: weighed products keep 3 decimals (`0,352`),
/// others drop trailing zeros (`2`, `1,5`).
String receiptQty(String v, {required bool weighted}) {
  final m = scaledFromServer(v, 3);
  if (m == null) return '?';
  if (!weighted) return formatMilli(m, group: true);
  final neg = m < 0;
  final a = m.abs();
  return '${neg ? '-' : ''}${a ~/ kMilli},${(a % kMilli).toString().padLeft(3, '0')}';
}

/// True when a server amount is > 0.
bool receiptAmountPositive(String v) => (scaledFromServer(v, 2) ?? 0) > 0;

/// True when a server amount is not zero.
bool receiptAmountNonZero(String v) => (scaledFromServer(v, 2) ?? 0) != 0;

bool _pos(String v) => receiptAmountPositive(v);
bool _nonZero(String v) => receiptAmountNonZero(v);
String _minus(String s) => (s == '0' || s == '?') ? s : '-$s';

/// Signed rounding (`+0,40` / `-0,40`), inverted for a return.
String receiptRoundingText(Receipt r) => _signedRounding(r);

String _signedRounding(Receipt r) {
  var c = scaledFromServer(r.rounding, 2);
  if (c == null) return '?';
  if (r.isReturn) c = -c;
  if (c == 0) return '0';
  return '${c > 0 ? '+' : '-'}${formatCents(c.abs(), currency: false)}';
}

/// Currency label of a receipt (`UZS` -> the app's localized "so'm").
String receiptCurrency(Receipt r) => (r.currency == 'UZS' || r.currency == 'KGS' || r.currency.isEmpty)
    ? tr('so‘m')
    : r.currency;

/// One logical receipt row (label/value pair or a single text).
class _Row {
  const _Row(this.left, [this.right, this.style = _RowStyle.normal, this.indent = false]);
  final String left;
  final String? right;
  final _RowStyle style;
  final bool indent;
}

enum _RowStyle { normal, bold, big, center, centerBold, muted, rule }

/// Builds the receipt as ordered rows — the SAME list feeds the on-screen
/// paper and the shared text, so both always say the same thing.
List<_Row> _rows(Receipt r) {
  final t = r.template;
  final out = <_Row>[];
  void center(String? s, {bool bold = false}) {
    if (s == null || s.trim().isEmpty) return;
    for (final l in s.split('\n')) {
      if (l.trim().isEmpty) continue;
      out.add(_Row(l.trimRight(), null, bold ? _RowStyle.centerBold : _RowStyle.center));
    }
  }

  void rule() => out.add(const _Row('', null, _RowStyle.rule));

  if (r.test) center('*** TEST ***', bold: true);
  if (r.isVoided) center(tr('BEKOR QILINGAN CHEK'), bold: true);
  center(t.header);
  center(t.storeDisplayName ?? r.storeName, bold: true);
  if (t.showBranch && r.branchName != null) center('${tr('Filial')}: ${r.branchName}');
  center(t.address ?? r.address);
  center(t.phone ?? r.phone);
  if (t.showStir && r.stir != null) center('${tr('STIR')}: ${r.stir}');
  rule();

  if (r.isReturn) {
    center(tr('QAYTARISH CHEKI'), bold: true);
    if (r.originalNumber != null) out.add(_Row('${tr('Asl chek')}: ${r.originalNumber}', r.originalIssuedAtLocal));
  }
  out.add(_Row('${tr('Chek')} ${r.number}'.trim(), r.issuedAtLocal, _RowStyle.bold));
  final cashier = t.showCashier && r.cashier != null ? '${tr('Kassir')}: ${r.cashier}' : null;
  final till = t.showTill && r.tillCode != null ? '${tr('Kassa')}: ${r.tillCode}' : null;
  if (cashier != null || till != null) out.add(_Row(cashier ?? till!, cashier != null ? till : null, _RowStyle.muted));
  if (t.showCustomer && r.customerName != null) {
    out.add(_Row('${tr('Xaridor')}: ${r.customerName}', null, _RowStyle.muted));
  }
  rule();

  for (final l in r.lines) {
    out.add(_Row(l.name));
    final showDisc = t.showDiscount && _pos(l.discount);
    final qty = receiptQty(l.qty, weighted: l.weighted) + (l.unit == null ? '' : ' ${l.unit}');
    var amount = receiptMoney(showDisc ? l.gross : l.total);
    if (r.isReturn) amount = _minus(amount);
    out.add(_Row('$qty × ${receiptMoney(l.unitPrice)}', amount, _RowStyle.normal, true));
    if (showDisc) out.add(_Row(tr('Chegirma'), '-${receiptMoney(l.discount)}', _RowStyle.muted, true));
  }
  rule();

  final showLineDisc = t.showDiscount && _pos(r.lineDiscount);
  final showDocDisc = _pos(r.docDiscount);
  final showRounding = _nonZero(r.rounding);
  if (showLineDisc || showDocDisc || showRounding) {
    // Qator chegirmalari yashirilgan bo'lsa qatorlar sof summada — oraliq ham sof (server qiymatlari farqi).
    var sub = receiptMoney(r.subtotal);
    if (!t.showDiscount) {
      final s = scaledFromServer(r.subtotal, 2), d = scaledFromServer(r.lineDiscount, 2);
      if (s != null && d != null) sub = formatCents(s - d, currency: false);
    }
    out.add(_Row(tr('Oraliq jami'), r.isReturn ? _minus(sub) : sub));
  }
  if (showLineDisc) out.add(_Row(tr('Chegirma'), '-${receiptMoney(r.lineDiscount)}'));
  if (showDocDisc) out.add(_Row(tr('Chek chegirmasi'), '-${receiptMoney(r.docDiscount)}'));
  if (showRounding) out.add(_Row(tr('Yaxlitlash'), _signedRounding(r)));
  final total = receiptMoney(r.total);
  out.add(_Row(r.isReturn ? tr('QAYTARISH JAMI') : tr('JAMI'),
      '${r.isReturn ? _minus(total) : total} ${receiptCurrency(r)}', _RowStyle.big));

  if (!r.isReturn) {
    if (r.payments.isNotEmpty && (t.showPaymentBreakdown || r.payments.length > 1)) {
      out.add(_Row('${tr('To‘lov')}:', null, _RowStyle.muted));
      for (final p in r.payments) {
        out.add(_Row(paymentMethodLabel(p.method), receiptMoney(p.amount), _RowStyle.normal, true));
        if (p.given != null) out.add(_Row(tr('Berildi'), receiptMoney(p.given!), _RowStyle.muted, true));
        if (p.change != null) out.add(_Row(tr('Qaytim'), receiptMoney(p.change!), _RowStyle.muted, true));
      }
    }
  } else if (r.refundAmount != null) {
    out.add(_Row('${tr('Qaytarildi')} (${paymentMethodLabel(r.refundMethod ?? '')})', receiptMoney(r.refundAmount!)));
  }
  rule();
  center(t.footer ?? tr('Xaridingiz uchun rahmat!'));
  if (r.uid != null) center(r.uid);
  return out;
}

/// The receipt as plain text (for sharing): the same rows as the paper view.
String receiptPlainText(Receipt r, {int width = 40}) {
  final b = StringBuffer();
  for (final row in _rows(r)) {
    switch (row.style) {
      case _RowStyle.rule:
        b.writeln('-' * width);
      case _RowStyle.center:
      case _RowStyle.centerBold:
        final s = row.left;
        final pad = s.length >= width ? 0 : (width - s.length) ~/ 2;
        b.writeln('${' ' * pad}$s');
      default:
        final left = '${row.indent ? '  ' : ''}${row.left}';
        final right = row.right ?? '';
        if (right.isEmpty) {
          b.writeln(left);
        } else if (left.length + 1 + right.length <= width) {
          b.writeln('$left${' ' * (width - left.length - right.length)}$right');
        } else {
          b.writeln(left);
          b.writeln('${' ' * (width - right.length).clamp(0, width)}$right');
        }
    }
  }
  return b.toString().trimRight();
}

/// The receipt drawn as a paper slip.
class ReceiptView extends StatelessWidget {
  /// Creates the view.
  const ReceiptView({super.key, required this.receipt});

  /// The server receipt.
  final Receipt receipt;

  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF1B1B1F);
    const faint = Color(0xFF6B6B75);
    const mono = TextStyle(fontFamily: 'monospace', fontFamilyFallback: ['Roboto Mono', 'Courier'], color: ink);
    final rows = _rows(receipt);
    return Container(
      key: const Key('receipt-paper'),
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 12, offset: Offset(0, 4))],
      ),
      child: DefaultTextStyle(
        style: mono.copyWith(fontSize: 13, height: 1.35),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (final row in rows)
            switch (row.style) {
              _RowStyle.rule => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: CustomPaint(size: const Size(double.infinity, 1), painter: _DashPainter()),
                ),
              _RowStyle.center || _RowStyle.centerBold => Text(
                  row.left,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontWeight: row.style == _RowStyle.centerBold ? FontWeight.w800 : FontWeight.w400),
                ),
              _ => Padding(
                  padding: EdgeInsets.only(left: row.indent ? 14 : 0, top: row.style == _RowStyle.big ? 4 : 0),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Expanded(
                      child: Text(row.left,
                          style: TextStyle(
                            fontWeight: row.style == _RowStyle.bold || row.style == _RowStyle.big ? FontWeight.w800 : FontWeight.w400,
                            fontSize: row.style == _RowStyle.big ? 16 : null,
                            color: row.style == _RowStyle.muted ? faint : null,
                          )),
                    ),
                    if (row.right != null) ...[
                      const SizedBox(width: 10),
                      Text(row.right!,
                          textAlign: TextAlign.right,
                          style: TextStyle(
                            fontWeight: row.style == _RowStyle.bold || row.style == _RowStyle.big ? FontWeight.w800 : FontWeight.w500,
                            fontSize: row.style == _RowStyle.big ? 16 : null,
                            color: row.style == _RowStyle.muted ? faint : null,
                          )),
                    ],
                  ]),
                ),
            },
        ]),
      ),
    );
  }
}

class _DashPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = const Color(0xFF9A9AA5)
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 7) {
      canvas.drawLine(Offset(x, 0), Offset((x + 4).clamp(0, size.width), 0), p);
    }
  }

  @override
  bool shouldRepaint(covariant _DashPainter oldDelegate) => false;
}

/// Receipt screen: shows [receipt] or loads `GET /sales/{saleId}/receipt`;
/// "Ulashish" shares it as text. No printing on mobile.
class ReceiptScreen extends StatefulWidget {
  /// Creates the screen (give [receipt] or [saleId]).
  const ReceiptScreen({super.key, this.saleId, this.receipt}) : assert(saleId != null || receipt != null);

  /// Sale id to load.
  final String? saleId;

  /// An already loaded receipt.
  final Receipt? receipt;

  @override
  State<ReceiptScreen> createState() => _ReceiptScreenState();
}

class _ReceiptScreenState extends State<ReceiptScreen> {
  Receipt? _loaded;

  Future<Receipt> _load() async {
    final given = widget.receipt;
    if (given != null) return given; // tayyor hujjat — build paytida setState chaqirilmasin
    final r = await MoneyApi.saleReceipt(widget.saleId!);
    if (mounted) setState(() => _loaded = r);
    return r;
  }

  Future<void> _share(Receipt r) async {
    try {
      await receiptShare(receiptPlainText(r), subject: '${tr('Chek')} ${r.number}');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Ulashib bo‘lmadi'))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.receipt == null && !Perm.allows('sales.receipt')) {
      return Scaffold(appBar: AppBar(title: Text(tr('Chek'))), body: const NoAccessView(action: 'sales.receipt'));
    }
    final r = _loaded ?? widget.receipt;
    return Scaffold(
      appBar: AppBar(
        title: Text(r == null ? tr('Chek') : '${tr('Chek')} ${r.number}'),
        actions: [
          if (r != null)
            IconButton(
              key: const Key('receipt-share'),
              tooltip: tr('Ulashish'),
              constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
              onPressed: () => _share(r),
              icon: const Icon(Icons.share_outlined),
            ),
        ],
      ),
      body: AsyncView<Receipt>(
        load: _load,
        builder: (context, r) => ListView(
          padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: ReceiptView(receipt: r),
            ),
            const SizedBox(height: 12),
            Text(tr('Bu — serverdagi chek nusxasi. Mobil ilovadan chop etilmaydi.'),
                textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ),
      ),
      bottomNavigationBar: r == null
          ? null
          : StickyActionBar(
              label: tr('Ulashish'),
              icon: Icons.share_outlined,
              onPressed: () => _share(r),
            ),
    );
  }
}
