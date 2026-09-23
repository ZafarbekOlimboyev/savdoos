import 'package:flutter/material.dart';

import '../api/receiving_api.dart';
import '../l10n.dart';
import 'receiving_draft_screen.dart';

/// AI o'qigan nakladnoyni tekshirish: topilmagan tovarni tanlash yoki yangi
/// mahsulot yaratish, partiyali mahsulotga partiyalar, yetkazib beruvchi,
/// to'lov turi va naqd pul manbai.
///
/// ⚠️  AI natijasi FAQAT taklif: ombor faqat operator "Kirimni saqlash"ni
///     tasdiqlagach va server 2xx qaytargach o'zgaradi.
class ReceivingReviewScreen extends StatelessWidget {
  /// Creates the screen for an AI [scan] of the photo [imageB64].
  const ReceivingReviewScreen({super.key, required this.scan, required this.imageB64});

  /// The AI result.
  final AiScan scan;

  /// The invoice photo (stored with the receiving for audit).
  final String imageB64;

  @override
  Widget build(BuildContext context) => ReceivingDraftScreen(
        title: tr('Tekshirish'),
        source: scan.source,
        aiScan: scan,
        imageB64: imageB64,
      );
}
