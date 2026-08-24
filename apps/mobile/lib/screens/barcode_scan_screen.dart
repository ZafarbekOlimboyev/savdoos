import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../l10n.dart';
import '../theme.dart';

/// Kamera bilan shtrix-kod skaneri. Kod topilgach — Navigator.pop(code) qaytaradi.
/// Foydalanuvchi qo'lda ham kiritishi mumkin (skaner ishlamasa).
class BarcodeScanScreen extends StatefulWidget {
  const BarcodeScanScreen({super.key});
  @override
  State<BarcodeScanScreen> createState() => _BarcodeScanScreenState();
}

class _BarcodeScanScreenState extends State<BarcodeScanScreen> {
  final _ctrl = MobileScannerController(
    detectionSpeed: DetectionSpeed.normal,
    facing: CameraFacing.back,
  );
  bool _done = false;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  void _emit(String code) {
    if (_done) return;
    final digits = code.replaceAll(RegExp(r'\D'), '');
    if (digits.isEmpty) return;
    _done = true;
    Navigator.of(context).pop(digits);
  }

  Future<void> _manual() async {
    final c = TextEditingController();
    final v = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr('Kodni qo‘lda kiriting')),
        content: TextField(
          controller: c,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(hintText: '4780000000000'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Bekor'))),
          ElevatedButton(onPressed: () => Navigator.pop(context, c.text), child: Text(tr('OK'))),
        ],
      ),
    );
    if (v != null && v.trim().isNotEmpty) _emit(v.trim());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: Text(tr('Shtrix-kodni skanerlang')),
        actions: [
          IconButton(onPressed: () => _ctrl.toggleTorch(), icon: const Icon(Icons.flash_on)),
          IconButton(onPressed: () => _ctrl.switchCamera(), icon: const Icon(Icons.cameraswitch)),
        ],
      ),
      body: Stack(alignment: Alignment.center, children: [
        MobileScanner(
          controller: _ctrl,
          onDetect: (capture) {
            for (final b in capture.barcodes) {
              final raw = b.rawValue;
              if (raw != null && raw.isNotEmpty) { _emit(raw); break; }
            }
          },
        ),
        // Nishon ramka
        Container(
          width: 260, height: 160,
          decoration: BoxDecoration(
            border: Border.all(color: AppColors.accentStrong, width: 3),
            borderRadius: BorderRadius.circular(16),
          ),
        ),
        Positioned(
          bottom: 40, left: 20, right: 20,
          child: Column(children: [
            Text(tr('Kodni ramka ichiga tuting'),
                style: const TextStyle(color: Colors.white70, fontSize: 13),
                textAlign: TextAlign.center),
            const SizedBox(height: 14),
            OutlinedButton.icon(
              onPressed: _manual,
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: const BorderSide(color: Colors.white54),
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              ),
              icon: const Icon(Icons.keyboard, size: 18),
              label: Text(tr('Qo‘lda kiritish')),
            ),
          ]),
        ),
      ]),
    );
  }
}
