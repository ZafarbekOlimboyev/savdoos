/// Client-side permission gating, driven by `assets/permission_matrix.json`.
///
/// The matrix maps every mobile ACTION (write or gated read) to the server
/// route it calls and the permission codes that route requires. The UI asks
/// `Perm.allows('stock.writeoff')` instead of hard-coding permission codes, so
/// the gating can be cross-checked against the backend route dependencies
/// (`apps/server/tests/test_mobile_permission_matrix.py`).
///
/// The server stays authoritative: hiding a button is UX only.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'l10n.dart';
import 'session.dart';

/// Asset path of the matrix.
const String kPermissionMatrixAsset = 'assets/permission_matrix.json';

/// One matrix entry.
@immutable
class PermRule {
  /// Creates a rule.
  const PermRule({
    required this.action,
    required this.method,
    required this.path,
    required this.anyOf,
    this.query = const {},
    this.gate = 'route',
  });

  /// Action name (`stock.writeoff`).
  final String action;

  /// HTTP method of the route.
  final String method;

  /// Route template relative to `/api/v1` (`/inventory/writeoff`).
  final String path;

  /// Permission codes; any one is enough. Empty = any signed-in employee.
  final List<String> anyOf;

  /// Fixed query parameters distinguishing this action (custody preview).
  final Map<String, String> query;

  /// `route` (dependency on the route) or `handler` (checked in the handler).
  final String gate;
}

/// The permission matrix and the gate the UI uses.
class Perm {
  Perm._();

  static Map<String, PermRule> _rules = const {};

  /// True once the matrix is loaded.
  static bool get loaded => _rules.isNotEmpty;

  /// All rules (loaded order).
  static Iterable<PermRule> get all => _rules.values;

  /// Loads the matrix asset (call once at startup; tests may call it too).
  static Future<void> load({AssetBundle? bundle}) async {
    final text = await (bundle ?? rootBundle).loadString(kPermissionMatrixAsset);
    loadFromJson(text);
  }

  /// Parses a matrix document (throws [FormatException] on a malformed one).
  static void loadFromJson(String text) {
    final doc = jsonDecode(text);
    if (doc is! Map || doc['actions'] is! Map) throw const FormatException('permission matrix: no actions');
    final out = <String, PermRule>{};
    (doc['actions'] as Map).forEach((k, v) {
      if (v is! Map) throw FormatException('permission matrix: bad entry $k');
      final any = v['any_of'];
      if (any is! List || v['method'] is! String || v['path'] is! String) {
        throw FormatException('permission matrix: incomplete entry $k');
      }
      out['$k'] = PermRule(
        action: '$k',
        method: v['method'] as String,
        path: v['path'] as String,
        anyOf: [for (final c in any) '$c'],
        query: {for (final e in ((v['query'] as Map?) ?? const {}).entries) '${e.key}': '${e.value}'},
        gate: (v['gate'] as String?) ?? 'route',
      );
    });
    _rules = out;
  }

  /// True when [action] is declared in the matrix.
  static bool isKnown(String action) => _rules.containsKey(action);

  /// The rule for [action], or `null` if it is not declared.
  static PermRule? rule(String action) => _rules[action];

  /// Whether the current [Session] may perform [action].
  ///
  /// FAIL-CLOSED: an unknown action, a matrix that is not loaded or a
  /// signed-out session all answer `false`.
  static bool allows(String action, {Session? session}) {
    final r = _rules[action];
    if (r == null) {
      if (kDebugMode) debugPrint('Perm.allows: unknown action "$action"');
      return false;
    }
    return (session ?? Session.instance).canAny(r.anyOf);
  }

  /// Localized reason shown next to a disabled control:
  /// `"Ruxsat kerak: Ombor amallari"`; empty when allowed.
  static String reason(String action, {Session? session}) {
    if (allows(action, session: session)) return '';
    final r = _rules[action];
    if (r == null || r.anyOf.isEmpty) return tr('Bu amal uchun ruxsatingiz yo‘q.');
    return trArgs('Ruxsat kerak: {perms}', {'perms': r.anyOf.map(permissionLabel).join(' / ')});
  }
}

const Map<String, String> _labels = {
  'kassa.sell': 'Kassada sotish',
  'kassa.view': 'Kassani ko‘rish',
  'sotuvlar.view': 'Sotuvlarni ko‘rish',
  'qaytarishlar.create': 'Qaytarish qilish',
  'qaytarishlar.view': 'Qaytarishlarni ko‘rish',
  'mijozlar.view': 'Mijozlarni ko‘rish',
  'mijozlar.edit': 'Mijozlarni boshqarish',
  'mahsulotlar.view': 'Mahsulotlarni ko‘rish',
  'mahsulotlar.edit': 'Mahsulotlarni boshqarish',
  'ombor.view': 'Omborni ko‘rish',
  'ombor.edit': 'Ombor amallari',
  'xaridlar.view': 'Xaridlarni ko‘rish',
  'xaridlar.edit': 'Xarid va qabul',
  'hisobot.view': 'Hisobotlar',
  'xodimlar.view': 'Xodimlarni ko‘rish',
  'xodimlar.edit': 'Xodimlarni boshqarish',
  'xodimlar.make_admin': 'Administrator tayinlash',
  'sozlamalar.view': 'Sozlamalarni ko‘rish',
  'sozlamalar.edit': 'Sozlamalarni o‘zgartirish',
};

/// Localized human label of a permission [code] (the code itself if unknown).
String permissionLabel(String code) {
  final l = _labels[code.trim()];
  return l == null ? code : tr(l);
}

/// Every permission label (l10n parity test).
@visibleForTesting
Iterable<String> debugPermissionLabels() => _labels.values;
