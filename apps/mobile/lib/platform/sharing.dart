import 'package:share_plus/share_plus.dart';

import 'platform_error.dart';

/// Plain-text sharing (reports, receipts). `share_plus` is web-safe (Web
/// Share API, `mailto:` fallback), so ONE implementation; its raw
/// `Exception('Navigator.canShare() is false')` is mapped to a localized
/// [PlatformUnavailable].
abstract class Sharing {
  /// The active adapter (tests inject a fake).
  static Sharing instance = const PluginSharing();

  /// Opens the share sheet with [body]. Throws [PlatformUnavailable] only.
  Future<void> text(String body, {String? subject});
}

/// `share_plus`-backed default.
class PluginSharing implements Sharing {
  /// Creates the default.
  const PluginSharing();

  @override
  Future<void> text(String body, {String? subject}) async {
    try {
      await Share.share(body, subject: subject);
    } catch (e) {
      throw PlatformUnavailable(PlatformUnavailable.kShare, cause: e);
    }
  }
}
