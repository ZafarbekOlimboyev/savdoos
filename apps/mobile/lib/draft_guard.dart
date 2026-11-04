import 'package:flutter/material.dart';

import 'api.dart';
import 'draft_vault.dart';
import 'l10n.dart';
import 'session.dart';

/// Sessiya tugaganda ekrandagi SAQLANMAGAN kiritmani [DraftVault] ga
/// topshiradigan va qayta kirgach uni TAKLIF qiladigan mixin.
///
/// ⚠️  TARTIB. `api.dart:381-396` da o'lchangan: 401 ishlovchisi avval
///     `token`/`employee` ni null qiladi, SO'NG `authEpoch.value++` chaqiradi,
///     va faqat undan keyin `onSessionExpired` (→ `pushAndRemoveUntil`)
///     ishlaydi. Ya'ni `authEpoch` listener'i ekran YO'Q QILINISHIDAN oldin
///     ishlaydi — qoralamani ushlab qolish uchun aynan shu nuqta.
///
/// ⚠️  DOIRA `initState` DA OLINADI. Tozalash paytida `Api.employee`
///     allaqachon `null`, demak egalikni o'sha paytda aniqlab bo'lmaydi.
///     Doira ekran ochilganda — sessiya hali tirik bo'lganda — olinadi.
///
/// ⚠️  AVTOMATIK TIKLAMAYDI. Qoralama faqat foydalanuvchi so'raganda
///     qaytariladi ([hasStashedDraft] → taklif → [claimStashedDraft]).
///     Shu bois begona kiritma ekranga o'z-o'zidan chiqib qolmaydi.
mixin DraftGuard<T extends StatefulWidget> on State<T> {
  /// Qoralama kaliti — ekran va hujjatga xos, masalan `corr.r1`.
  String get draftKey;

  /// Hozirgi saqlanmagan kiritma, yoki `null` — saqlashga arzimaydi
  /// (bo'sh shakl uchun `null` qaytarish SHART, aks holda foydalanuvchiga
  /// bo'sh "tiklash" taklifi ko'rsatiladi).
  Object? captureDraft();

  /// [DraftVault] dan qaytgan qoralamani ekranga qo'yadi.
  void restoreDraft(Object draft);

  late final String _stashScope;
  late final VoidCallback _onAuthEpoch;

  @override
  void initState() {
    super.initState();
    _stashScope = _scope();
    _onAuthEpoch = () {
      final d = captureDraft();
      if (d != null) DraftVault.stash(draftKey, d, scope: _stashScope);
    };
    Api.authEpoch.addListener(_onAuthEpoch);
  }

  @override
  void dispose() {
    Api.authEpoch.removeListener(_onAuthEpoch);
    super.dispose();
  }

  /// Joriy sessiya uchun tiklanadigan qoralama bormi. O'chirmaydi.
  bool get hasStashedDraft => DraftVault.has(draftKey, scope: _scope());

  /// Qoralamani oladi — bir martalik. Doira mos kelmasa `null`.
  Object? claimStashedDraft() => DraftVault.claim(draftKey, scope: _scope());

  /// `Session.cacheKey` — server|kompaniya|xodim|filial.
  String _scope() => Session.instance.cacheKey('draft');
}

/// Sessiya tugashidan oldin saqlangan kiritmani TIKLASH taklifi.
///
/// ⚠️  Avtomatik tiklanmaydi — foydalanuvchi o'zi bosadi. [DraftVault.claim]
///     doirani (server|kompaniya|xodim|filial) ham tekshiradi, ya'ni boshqa
///     xodim bu kartani KO'RMAYDI.
class DraftRestoreCard extends StatelessWidget {
  const DraftRestoreCard({
    super.key,
    required this.restoreKey,
    required this.onRestore,
    this.enabled = true,
  });

  /// Tiklash tugmasining kaliti (ekranga xos, testlar uchun).
  final Key restoreKey;

  /// Tugma bosilganda — ekran `claimStashedDraft()` + `restoreDraft()` qiladi.
  final VoidCallback onRestore;

  /// `false` — ekran band (yuborish ketmoqda).
  final bool enabled;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 14),
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF4E5),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE8A33D)),
        ),
        child: Row(children: [
          const Icon(Icons.restore, size: 20, color: Color(0xFF8A5A00)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              tr('Sessiya tugaganda kiritganingiz saqlab qolindi'),
              style: const TextStyle(fontSize: 14, height: 1.3, color: Color(0xFF6B4500)),
            ),
          ),
          TextButton(
            key: restoreKey,
            onPressed: enabled ? onRestore : null,
            child: Text(tr('Tiklash')),
          ),
        ]),
      );
}
