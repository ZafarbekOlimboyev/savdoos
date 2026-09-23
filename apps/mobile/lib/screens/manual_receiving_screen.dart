import 'package:flutter/material.dart';

import '../l10n.dart';
import 'receiving_draft_screen.dart';

/// Qo'lda kirim (mobil): yetkazib beruvchi, qatorlar (skaner / server qidiruvi /
/// yangi mahsulot, partiyali mahsulotda partiyalar), to'lov turi va naqd pul
/// manbai — bitta hujjat, bitta `client_uuid`.
///
/// Hujjat mantiqi [ReceivingDraftScreen] da (AI tekshiruvi bilan umumiy).
class ManualReceivingScreen extends StatelessWidget {
  /// Creates the screen.
  const ManualReceivingScreen({super.key});

  @override
  Widget build(BuildContext context) => ReceivingDraftScreen(title: tr('Qo‘lda kirim'), source: 'manual');
}
