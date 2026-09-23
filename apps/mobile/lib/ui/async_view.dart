import 'package:flutter/material.dart';

import '../errors.dart';
import '../l10n.dart';
import '../theme.dart';
import 'tokens.dart';

/// Lets a parent trigger [AsyncView] reloads (pull-to-refresh, after a write).
class AsyncViewController {
  Future<void> Function()? _reload;

  /// Re-runs the load; resolves when it finishes (errors are shown, not thrown).
  Future<void> reload() => _reload?.call() ?? Future.value();
}

/// One async load rendered with explicit states:
///
/// * first load -> [skeleton] (default: static placeholder rows);
/// * error without data -> [ErrorState] with a 48 dp "Qayta urinish" button;
/// * data that [isEmpty] says is empty -> [empty] / [EmptyState];
/// * data -> [builder]. A reload keeps the old data on screen with a thin
///   progress bar; a failed reload shows an [ErrorBanner]-style strip above it.
///
/// [reloadOn] re-runs the load when it notifies (e.g. `Session.instance` for a
/// branch switch, `Api.stockRev` after stock writes). Stale responses of an
/// earlier load never overwrite a newer one.
class AsyncView<T> extends StatefulWidget {
  /// Creates the view.
  const AsyncView({
    super.key,
    required this.load,
    required this.builder,
    this.isEmpty,
    this.empty,
    this.emptyText,
    this.emptyIcon = Icons.inbox_outlined,
    this.skeleton,
    this.reloadOn,
    this.refreshable = false,
    this.controller,
  });

  /// Produces the data. Throwing shows the error state.
  final Future<T> Function() load;

  /// Builds the loaded data.
  final Widget Function(BuildContext context, T data) builder;

  /// Decides whether [data] is empty (default: empty Iterable/Map).
  final bool Function(T data)? isEmpty;

  /// Custom empty widget.
  final Widget? empty;

  /// Text of the default [EmptyState].
  final String? emptyText;

  /// Icon of the default [EmptyState].
  final IconData emptyIcon;

  /// Custom first-load placeholder.
  final Widget? skeleton;

  /// Reloads when this notifies.
  final Listenable? reloadOn;

  /// Wraps the data in a pull-to-refresh (the builder must be scrollable).
  final bool refreshable;

  /// Optional external reload handle.
  final AsyncViewController? controller;

  @override
  State<AsyncView<T>> createState() => _AsyncViewState<T>();
}

class _AsyncViewState<T> extends State<AsyncView<T>> {
  int _seq = 0;
  bool _loading = true;
  bool _hasData = false;
  T? _data;
  Object? _error;

  @override
  void initState() {
    super.initState();
    widget.controller?._reload = _run;
    widget.reloadOn?.addListener(_onReload);
    _run();
  }

  @override
  void didUpdateWidget(covariant AsyncView<T> old) {
    super.didUpdateWidget(old);
    if (old.reloadOn != widget.reloadOn) {
      old.reloadOn?.removeListener(_onReload);
      widget.reloadOn?.addListener(_onReload);
    }
    if (old.controller != widget.controller) {
      old.controller?._reload = null;
      widget.controller?._reload = _run;
    }
  }

  @override
  void dispose() {
    widget.reloadOn?.removeListener(_onReload);
    widget.controller?._reload = null;
    super.dispose();
  }

  void _onReload() => _run();

  Future<void> _run() async {
    final seq = ++_seq;
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final d = await widget.load();
      if (!mounted || seq != _seq) return;
      setState(() {
        _data = d;
        _hasData = true;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  bool _empty(T d) {
    final f = widget.isEmpty;
    if (f != null) return f(d);
    if (d is Iterable) return d.isEmpty;
    if (d is Map) return d.isEmpty;
    return false;
  }

  @override
  Widget build(BuildContext context) {
    if (!_hasData) {
      if (_error != null) return ErrorState(error: _error!, onRetry: _run);
      return widget.skeleton ?? const SkeletonList();
    }
    final d = _data as T;
    Widget body = _empty(d)
        ? (widget.empty ?? EmptyState(text: widget.emptyText ?? tr('Hozircha hech narsa yo‘q'), icon: widget.emptyIcon))
        : widget.builder(context, d);
    if (widget.refreshable) {
      body = RefreshIndicator(onRefresh: _run, color: AppColors.accent, child: body);
    }
    return Column(children: [
      if (_loading) const LinearProgressIndicator(minHeight: 2),
      if (_error != null)
        _InlineError(error: _error!, onRetry: _run),
      Expanded(child: body),
    ]);
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Container(
        color: AppColors.dangerSoft,
        padding: const EdgeInsets.only(left: kGutter),
        child: Row(children: [
          const Icon(Icons.error_outline, size: 18, color: AppColors.danger),
          const SizedBox(width: 8),
          Expanded(
            child: Text(userMessage(error),
                maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: AppColors.text)),
          ),
          TextButton(
            onPressed: onRetry,
            style: TextButton.styleFrom(minimumSize: const Size(kMinTouch, kMinTouch)),
            child: Text(tr('Qayta urinish')),
          ),
        ]),
      );
}

/// Static placeholder rows shown during a first load (no animation, so tests
/// can `pumpAndSettle` while it is visible).
class SkeletonList extends StatelessWidget {
  /// Creates [rows] placeholder rows.
  const SkeletonList({super.key, this.rows = 6});

  /// Number of rows.
  final int rows;

  @override
  Widget build(BuildContext context) {
    Widget bar(double w, double h) => Container(
          width: w,
          height: h,
          decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(6)),
        );
    return Semantics(
      label: tr('Yuklanmoqda…'),
      child: ListView.builder(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(kGutter),
        itemCount: rows,
        itemBuilder: (_, i) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Container(
            height: 64,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(kRadius),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(children: [
              bar(40, 40),
              const SizedBox(width: 12),
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  bar(i.isEven ? 180 : 140, 12),
                  const SizedBox(height: 8),
                  bar(90, 10),
                ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Full-area error with a localized message and a retry button.
class ErrorState extends StatelessWidget {
  /// Creates the error state for [error].
  const ErrorState({super.key, required this.error, this.onRetry});

  /// The failure (any object; rendered through [userMessage]).
  final Object error;

  /// Retry action; hidden when null.
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final offline = isConnectivityError(error);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(offline ? Icons.cloud_off : Icons.error_outline, size: 44, color: offline ? AppColors.warn : AppColors.danger),
          const SizedBox(height: 12),
          Text(userMessage(error), textAlign: TextAlign.center, style: TextStyle(fontSize: 15, color: AppColors.text2, height: 1.35)),
          if (onRetry != null) ...[
            const SizedBox(height: 16),
            SizedBox(
              height: kMinTouch,
              child: OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: Text(tr('Qayta urinish')),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Friendly "nothing here" state.
class EmptyState extends StatelessWidget {
  /// Creates the empty state.
  const EmptyState({super.key, required this.text, this.icon = Icons.inbox_outlined, this.action});

  /// Message.
  final String text;

  /// Illustration icon.
  final IconData icon;

  /// Optional call to action (e.g. "Qo‘shish").
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 44, color: AppColors.faint),
            const SizedBox(height: 12),
            Text(text, textAlign: TextAlign.center, style: TextStyle(fontSize: 15, color: AppColors.muted)),
            if (action != null) ...[const SizedBox(height: 16), action!],
          ]),
        ),
      );
}
