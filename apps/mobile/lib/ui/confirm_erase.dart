import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// The word the server demands before an irreversible erasure.
///
/// ⚠️  THE SERVER IS AUTHORITATIVE. It re-checks this value and answers 400 on
///     a mismatch (`services/account_deletion.CONFIRM_WORD`), so if the two
///     ever drift the request FAILS CLOSED rather than erasing anything. Where
///     the client already holds server state it should prefer the
///     `confirm_word` field from `GET /auth/account-deletion`.
const String kEraseConfirmWord = "O'CHIRISH";

/// Result of [confirmErase]: the password, the typed phrase and any opt-in.
class EraseConfirmation {
  /// Creates the result.
  const EraseConfirmation(this.password, this.phrase, {this.optedIn = false});

  /// The operator's CURRENT password, re-entered for this one action.
  final String password;

  /// The exact word the server demands as confirmation.
  final String phrase;

  /// Whether the operator ticked the dialog's extra, OFF-BY-DEFAULT election.
  ///
  /// ⚠️  OFF BY DEFAULT ON PURPOSE. The election carries a second irreversible
  ///     consequence (currently: erasing the owner's own personal data while
  ///     closing the shop). Defaulting it on would perform an irreversible act
  ///     nobody asked for; defaulting it off means the worst case is that the
  ///     operator keeps data they could have erased.
  final bool optedIn;
}

/// An extra, off-by-default election offered inside [confirmErase].
class EraseOptIn {
  /// Creates the election.
  const EraseOptIn({required this.label, required this.note});

  /// The checkbox label. ALREADY TRANSLATED by the caller.
  final String label;

  /// One line under the label explaining what ticking it does, and — when it
  /// applies — that this is the LAST moment the choice can be made.
  final String note;
}

/// Asks for a password AND a typed phrase before an irreversible erasure.
///
/// ⚠️  WHY BOTH. The typed phrase stops a mis-tap; the password proves the
///     person at the keyboard is the account holder. A stolen token alone must
///     never be enough to erase someone's personal data, so the password is
///     verified SERVER-side on every such call — this dialog only collects it.
///
/// ⚠️  THE PASSWORD ASKED FOR IS ALWAYS THE ACTOR'S OWN. When an owner erases
///     an employee's account, the employee's password is neither needed nor
///     requested; it stays known only to them.
Future<EraseConfirmation?> confirmErase(
  BuildContext context, {
  required String title,
  required String message,
  required String phrase,
  List<String> details = const [],
  String? confirmLabel,
  EraseOptIn? optIn,
}) =>
    showDialog<EraseConfirmation>(
      context: context,
      builder: (_) => _EraseDialog(
        title: title,
        message: message,
        phrase: phrase,
        details: details,
        confirmLabel: confirmLabel,
        optIn: optIn,
      ),
    );

class _EraseDialog extends StatefulWidget {
  const _EraseDialog({
    required this.title,
    required this.message,
    required this.phrase,
    required this.details,
    this.confirmLabel,
    this.optIn,
  });

  final String title;
  final String message;
  final String phrase;
  final List<String> details;
  final String? confirmLabel;
  final EraseOptIn? optIn;

  @override
  State<_EraseDialog> createState() => _EraseDialogState();
}

class _EraseDialogState extends State<_EraseDialog> {
  final _password = TextEditingController();
  final _typed = TextEditingController();
  bool _ready = false;
  bool _opted = false;

  @override
  void dispose() {
    _password.dispose();
    _typed.dispose();
    super.dispose();
  }

  void _recheck() {
    final ok = _password.text.isNotEmpty && _typed.text.trim() == widget.phrase;
    if (ok != _ready) setState(() => _ready = ok);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.title),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(widget.message),
            for (final d in widget.details) ...[
              const SizedBox(height: 8),
              Text(d, style: TextStyle(fontSize: 13, color: AppColors.muted)),
            ],
            const SizedBox(height: 14),
            TextField(
              controller: _password,
              key: const Key('erase-password'),
              obscureText: true,
              onChanged: (_) => _recheck(),
              decoration: InputDecoration(labelText: tr('Joriy parolingiz')),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _typed,
              key: const Key('erase-phrase'),
              onChanged: (_) => _recheck(),
              decoration: InputDecoration(
                labelText: trArgs('«{word}» so‘zini kiriting', {'word': widget.phrase}),
              ),
            ),
            if (widget.optIn != null) ...[
              const SizedBox(height: 6),
              CheckboxListTile(
                key: const Key('erase-optin'),
                value: _opted,
                onChanged: (v) => setState(() => _opted = v ?? false),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                title: Text(widget.optIn!.label, style: const TextStyle(fontSize: 14)),
                subtitle: Text(widget.optIn!.note,
                    style: TextStyle(fontSize: 12, color: AppColors.muted)),
              ),
            ],
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: Text(tr('Bekor'))),
          FilledButton(
            key: const Key('erase-submit'),
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            // Disabled until BOTH are right — the button itself is the last guard.
            //
            // ⚠️  The election travels with the result. Leaving it out here
            //     silently dropped the operator's tick: the dialog looked
            //     right and the caller got `optedIn: false`. The widget test
            //     `belgilansa optedIn true bo'lib qaytadi` exists for exactly
            //     that failure, which is how it was caught.
            onPressed: _ready
                ? () => Navigator.of(context).pop(EraseConfirmation(
                    _password.text, _typed.text.trim(), optedIn: _opted))
                : null,
            child: Text(widget.confirmLabel ?? tr('O‘chirish')),
          ),
        ],
      );
}
