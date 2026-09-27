/// Skaner diagnostikasi uchun kirish ekrani — FAQAT diagnostika build'ida.
///
/// NEGA BOR. Skaner nosozligini qidirganda kamera+dekodlashni qolgan hamma
/// narsadan AJRATISH kerak: aks holda sinovda login, sessiya, tarmoq, server
/// javobi va ruxsatlar bir vaqtda aralashadi va "skaner ishlamadi" degani
/// qaysi bo'g'in uzilganini AYTMAYDI. Bu ekran serverga UMUMAN murojaat
/// qilmaydi: `BarcodeScanScreen()` ning xom rejimi mahsulotni izlamaydi, faqat
/// o'qilgan raqamni qaytaradi.
///
/// ⚠️  Production build'da bu yo'l YO'Q: `main.dart` dagi shart `kScanDiagnostics`
///     (`--dart-define=BINOS_SCAN_DIAG`) const'iga bog'langan, ya'ni bayroq
///     o'chiq bo'lsa dart2js butun shoxni olib tashlaydi.
library;

import 'package:flutter/material.dart';

import '../theme.dart';
import 'barcode_scan_screen.dart';

class ScanDiagScreen extends StatefulWidget {
  const ScanDiagScreen({super.key});

  @override
  State<ScanDiagScreen> createState() => _ScanDiagScreenState();
}

class _ScanDiagScreenState extends State<ScanDiagScreen> {
  /// O'qilgan kodlar — eng yangisi yuqorida. Sanoq bilan: bir xil kod ketma-ket
  /// ikki marta kelsa, bu dubl bosish emas, ROSTDAN ikki marta o'qilgani.
  final List<String> _codes = <String>[];

  Future<void> _open() async {
    final String? code = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(builder: (_) => const BarcodeScanScreen(title: 'SCAN DIAG')),
    );
    if (!mounted || code == null || code.isEmpty) return;
    setState(() => _codes.insert(0, code));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(title: const Text('SCAN DIAG'), backgroundColor: AppColors.card),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              'Skaner diagnostikasi. Serverga murojaat YO‘Q: kod o‘qiladi va shu '
              'ro‘yxatga tushadi. Kamera ekranining yuqorisidagi SCAN DIAG paneli '
              'har bo‘g‘inni ko‘rsatadi.',
              style: TextStyle(color: AppColors.muted, fontSize: 13, height: 1.35),
            ),
            const SizedBox(height: 14),
            SizedBox(
              height: 52,
              child: ElevatedButton.icon(
                key: const Key('scan-diag-open'),
                onPressed: _open,
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('Kamerani ochish'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text('O‘qilgan: ${_codes.length}',
                style: TextStyle(color: AppColors.text, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.separated(
                key: const Key('scan-diag-codes'),
                itemCount: _codes.length,
                separatorBuilder: (_, __) => Divider(height: 1, color: AppColors.borderInput),
                itemBuilder: (BuildContext _, int i) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Text('${_codes.length - i}.  ${_codes[i]}',
                      style: TextStyle(color: AppColors.text, fontSize: 16)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
