import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:share_plus/share_plus.dart';

import 'api.dart';
import 'format.dart';
import 'l10n.dart';

/// Analitika hisobotini PDF / Excel(CSV) / matn sifatida chiqarish (mijoz o'zi tanlaydi).
class ReportExport {
  static const _purple = PdfColor.fromInt(0xFF6D5DD3);
  static const _soft = PdfColor.fromInt(0xFFF3F1FB);
  static const _hdr = PdfColor.fromInt(0xFFF0F0F5);

  static String _store() {
    final e = Api.employee ?? {};
    return (e['company_name'] ?? e['store'] ?? 'SavdoOS').toString();
  }

  // ── PDF ──
  static Future<void> pdf(Overview ov, CashFlow? cf, String periodLabel) async {
    final doc = pw.Document();
    final font = await PdfGoogleFonts.robotoRegular();
    final bold = await PdfGoogleFonts.robotoBold();
    final theme = pw.ThemeData.withFont(base: font, bold: bold);

    pw.Widget kpi(String l, String v) => pw.Expanded(
          child: pw.Container(
            padding: const pw.EdgeInsets.all(10),
            decoration: pw.BoxDecoration(color: _soft, borderRadius: pw.BorderRadius.circular(8)),
            child: pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
              pw.Text(l, style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
              pw.SizedBox(height: 3),
              pw.Text(v, style: pw.TextStyle(fontSize: 15, fontWeight: pw.FontWeight.bold)),
            ]),
          ),
        );

    pw.Widget section(String t) => pw.Padding(
          padding: const pw.EdgeInsets.only(top: 16, bottom: 6),
          child: pw.Text(t, style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)),
        );

    doc.addPage(pw.MultiPage(
      theme: theme,
      margin: const pw.EdgeInsets.all(28),
      build: (ctx) => [
        pw.Row(mainAxisAlignment: pw.MainAxisAlignment.spaceBetween, crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
          pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
            pw.Text(_store(), style: pw.TextStyle(fontSize: 20, fontWeight: pw.FontWeight.bold)),
            pw.Text('${tr('Savdo hisoboti')} · $periodLabel', style: const pw.TextStyle(fontSize: 11, color: PdfColors.grey700)),
          ]),
          pw.Text('SavdoOS', style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold, color: _purple)),
        ]),
        pw.SizedBox(height: 16),
        pw.Row(children: [kpi(tr('Savdo'), money(ov.sales)), pw.SizedBox(width: 8), kpi(tr('Yalpi foyda'), money(ov.profit))]),
        pw.SizedBox(height: 8),
        pw.Row(children: [kpi(tr('Cheklar'), '${ov.tx}'), pw.SizedBox(width: 8), kpi(tr('O‘rtacha chek'), money(ov.avgCheck))]),
        if (ov.top.isNotEmpty) ...[
          section(tr('Eng ko‘p sotilgan')),
          pw.TableHelper.fromTextArray(
            headers: [tr('Mahsulot'), tr('Savdo')],
            data: ov.top.map((t) => [t.name, money(t.revenue)]).toList(),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10),
            cellStyle: const pw.TextStyle(fontSize: 10),
            cellAlignments: {1: pw.Alignment.centerRight},
            headerDecoration: const pw.BoxDecoration(color: _hdr),
          ),
        ],
        if (ov.cashiers.isNotEmpty) ...[
          section(tr('Kassirlar')),
          pw.TableHelper.fromTextArray(
            headers: [tr('Kassir'), tr('Savdo'), tr('Cheklar')],
            data: ov.cashiers.map((c) => [c.name, money(c.sales), '${c.tx}']).toList(),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10),
            cellStyle: const pw.TextStyle(fontSize: 10),
            cellAlignments: {1: pw.Alignment.centerRight, 2: pw.Alignment.centerRight},
            headerDecoration: const pw.BoxDecoration(color: _hdr),
          ),
        ],
        if (cf != null) ...[
          section(tr('Naqd oqim')),
          pw.TableHelper.fromTextArray(
            headers: [tr('Ko‘rsatkich'), tr('Summa')],
            data: [
              [tr('Naqd savdo'), money(cf.inNaqd)],
              [tr('Qarz qaytdi'), money(cf.inQarz)],
              [tr('Xarajat'), '−${money(cf.outXarajat)}'],
              [tr('Inkassatsiya'), '−${money(cf.outInkassa)}'],
              [tr('Kassada naqd'), money(cf.kassada)],
            ],
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10),
            cellStyle: const pw.TextStyle(fontSize: 10),
            cellAlignments: {1: pw.Alignment.centerRight},
            headerDecoration: const pw.BoxDecoration(color: _hdr),
          ),
        ],
        pw.SizedBox(height: 20),
        pw.Text('${tr('Tayyorlandi')}: SavdoOS', style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey)),
      ],
    ));
    await Printing.sharePdf(bytes: await doc.save(), filename: 'SavdoOS-${tr('Savdo hisoboti')}.pdf');
  }

  // ── Excel (CSV, ; ajratgichli — Excel to'g'ri ochadi) ──
  static Future<void> csv(Overview ov, CashFlow? cf, String periodLabel) async {
    final b = StringBuffer('﻿'); // UTF-8 BOM — Excel kirill/uzbekni to'g'ri o'qishi uchun
    void row(List<Object> cells) => b.writeln(cells.map((e) => '"${e.toString().replaceAll('"', '""')}"').join(';'));
    row(['SavdoOS ${tr('Savdo hisoboti')}', periodLabel]);
    b.writeln();
    row([tr('Ko‘rsatkich'), tr('Summa')]);
    row([tr('Savdo'), ov.sales]);
    row([tr('Yalpi foyda'), ov.profit]);
    row([tr('Cheklar'), ov.tx]);
    row([tr('O‘rtacha chek'), ov.avgCheck]);
    if (cf != null) row([tr('Kassada naqd'), cf.kassada]);
    b.writeln();
    row([tr('Eng ko‘p sotilgan'), tr('Savdo')]);
    for (final t in ov.top) {
      row([t.name, t.revenue]);
    }
    b.writeln();
    row([tr('Kassir'), tr('Savdo'), tr('Cheklar')]);
    for (final c in ov.cashiers) {
      row([c.name, c.sales, c.tx]);
    }
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/SavdoOS-${tr('Savdo hisoboti')}.csv');
    await file.writeAsString(b.toString());
    await Share.shareXFiles([XFile(file.path, mimeType: 'text/csv')], text: 'SavdoOS ${tr('Savdo hisoboti')} · $periodLabel');
  }

  // ── Matn (Telegram/WhatsApp uchun) ──
  static Future<void> text(Overview ov, CashFlow? cf, String periodLabel) async {
    final b = StringBuffer();
    b.writeln('📊 ${_store()} · $periodLabel');
    b.writeln('');
    b.writeln('${tr('Savdo')}: ${money(ov.sales)}');
    b.writeln('${tr('Yalpi foyda')}: ${money(ov.profit)}');
    b.writeln('${tr('Cheklar')}: ${ov.tx}');
    b.writeln('${tr('O‘rtacha chek')}: ${money(ov.avgCheck)}');
    if (cf != null) b.writeln('${tr('Kassada naqd')}: ${money(cf.kassada)}');
    if (ov.top.isNotEmpty) {
      b.writeln('');
      b.writeln('${tr('Eng ko‘p sotilgan')}:');
      for (final t in ov.top.take(5)) {
        b.writeln('• ${t.name} — ${money(t.revenue)}');
      }
    }
    b.writeln('');
    b.writeln('SavdoOS');
    await Share.share(b.toString());
  }
}
