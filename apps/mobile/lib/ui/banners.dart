import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../theme.dart';
import 'tokens.dart';

/// Visual weight of an [ErrorBanner].
enum BannerSeverity {
  /// A failed action (red).
  error,

  /// Something the operator must know before acting (amber).
  warning,

  /// Neutral information (accent).
  info,
}

/// Inline banner for a failed action or an important notice. Pass [error]
/// (any object, rendered through [userMessage]) or a ready [message].
class ErrorBanner extends StatelessWidget {
  /// Creates the banner.
  const ErrorBanner({
    super.key,
    this.error,
    this.message,
    this.onRetry,
    this.onDismiss,
    this.severity = BannerSeverity.error,
    this.retryLabel,
  }) : assert(error != null || message != null, 'error or message is required');

  /// The failure to describe.
  final Object? error;

  /// A ready text (used when [error] is null).
  final String? message;

  /// Retry action (shows a 48 dp button).
  final VoidCallback? onRetry;

  /// Dismiss action (shows a close button).
  final VoidCallback? onDismiss;

  /// Colour scheme.
  final BannerSeverity severity;

  /// Label of the retry button.
  final String? retryLabel;

  @override
  Widget build(BuildContext context) {
    final offline = error != null && isConnectivityError(error);
    final (Color fg, Color bg, IconData icon) = switch (severity) {
      BannerSeverity.error => offline
          ? (AppColors.warn, AppColors.warnSoft, Icons.cloud_off)
          : (AppColors.danger, AppColors.dangerSoft, Icons.error_outline),
      BannerSeverity.warning => (AppColors.warn, AppColors.warnSoft, Icons.warning_amber_rounded),
      BannerSeverity.info => (AppColors.accentStrong, AppColors.accentSoft, Icons.info_outline),
    };
    final text = message ?? userMessage(error);
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: fg.withAlpha(90)),
        ),
        // Matn va tugmalar alohida qatorda: uzun tarjima (ru/ky) tugmani siqib,
        // matnni bir harfli ustunga aylantirmasin.
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 8), child: Icon(icon, color: fg, size: 20)),
            const SizedBox(width: 10),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(text, key: const Key('banner-text'), style: TextStyle(fontSize: 13.5, height: 1.3, color: AppColors.text)),
              ),
            ),
            if (onDismiss != null)
              IconButton(
                tooltip: tr('Yopish'),
                constraints: const BoxConstraints(minWidth: kMinTouch, minHeight: kMinTouch),
                onPressed: onDismiss,
                icon: Icon(Icons.close, size: 18, color: AppColors.muted),
              )
            else
              const SizedBox(width: 8),
          ]),
          if (onRetry != null)
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton.icon(
                key: const Key('banner-retry'),
                onPressed: onRetry,
                style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
                icon: const Icon(Icons.refresh, size: 18),
                label: Text(retryLabel ?? tr('Qayta urinish')),
              ),
            ),
        ]),
      ),
    );
  }
}

/// Full-width strip shown while the server is unreachable ([Api.online] is
/// false). "Qayta tekshirish" probes the server ([Api.ping] by default).
class ConnectivityBanner extends StatefulWidget {
  /// Creates the banner.
  const ConnectivityBanner({super.key, this.onRetry});

  /// Custom retry (defaults to [Api.ping]).
  final Future<void> Function()? onRetry;

  @override
  State<ConnectivityBanner> createState() => _ConnectivityBannerState();
}

class _ConnectivityBannerState extends State<ConnectivityBanner> {
  bool _checking = false;

  Future<void> _retry() async {
    if (_checking) return;
    setState(() => _checking = true);
    try {
      if (widget.onRetry != null) {
        await widget.onRetry!();
      } else {
        await Api.ping();
      }
    } catch (_) {
      // online flag already reflects the result
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: Api.online,
      builder: (context, online, _) {
        if (online) return const SizedBox.shrink();
        return Material(
          color: AppColors.warn,
          child: SafeArea(
            top: false,
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.only(left: kGutter),
              child: Row(children: [
                const Icon(Icons.cloud_off, size: 18, color: Colors.white),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(tr('Server bilan aloqa yo‘q — amallar yuborilmaydi'),
                      key: const Key('offline-text'),
                      style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                ),
                TextButton(
                  key: const Key('offline-retry'),
                  onPressed: _checking ? null : _retry,
                  style: TextButton.styleFrom(
                    foregroundColor: Colors.white,
                    minimumSize: const Size(kMinTouch, kMinTouch),
                  ),
                  child: Text(_checking ? tr('Tekshirilmoqda…') : tr('Qayta tekshirish')),
                ),
              ]),
            ),
          ),
        );
      },
    );
  }
}
