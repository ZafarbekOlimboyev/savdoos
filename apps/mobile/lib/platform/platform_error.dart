import '../l10n.dart';

/// A platform capability the current device/browser cannot provide (no share
/// sheet, no file download, …). Carries an l10n KEY, translated at display
/// time, so a raw plugin `Exception('Navigator.canShare() is false')` or a
/// `MissingPluginException` never reaches the operator.
class PlatformUnavailable implements Exception {
  /// Creates the error; [message] is an Uzbek l10n key.
  const PlatformUnavailable(this.message, {this.cause});

  /// Sharing / exporting a file or text is not possible here (already
  /// translated in `money_strings.dart`).
  static const String kShare = 'Ulashib bo‘lmadi';

  /// The l10n key of the operator message.
  final String message;

  /// The underlying plugin failure, for logs only.
  final Object? cause;

  @override
  String toString() => tr(message);
}
