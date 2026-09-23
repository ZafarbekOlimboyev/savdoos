/// Who is signed in, what they may do, and which branch they are working in.
///
/// Loaded from `GET /auth/context` at start, after every login and when the
/// app returns to the foreground. The SERVER decides permissions and branch
/// visibility; the client only mirrors them for UX (hiding buttons, choosing
/// the branch it sends as `branch_id`).
///
/// ```dart
/// final s = Session.instance;
/// if (s.can('ombor.edit')) ...;
/// Api.getJson('/products', query: {'q': q, ...s.branchQuery()});
/// ```
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

/// Roles that bypass per-permission checks on the server (`FULL_ACCESS_ROLES`).
const Set<String> kFullAccessRoles = {'ega', 'administrator'};

/// One branch the caller may see.
@immutable
class BranchInfo {
  /// Creates a branch.
  const BranchInfo({required this.id, required this.name, this.isActive = true, this.timezone, this.businessDate});

  /// Parses `{id,name,is_active,timezone,business_date}`.
  factory BranchInfo.fromJson(Map<String, dynamic> j) => BranchInfo(
        id: '${j['id']}',
        name: '${j['name'] ?? ''}',
        isActive: j['is_active'] != false,
        timezone: j['timezone']?.toString(),
        businessDate: j['business_date']?.toString(),
      );

  /// Branch id (uuid string).
  final String id;

  /// Display name.
  final String name;

  /// False for a deactivated branch (readable, not writable).
  final bool isActive;

  /// IANA timezone of the branch, if configured.
  final String? timezone;

  /// The branch's business date (`YYYY-MM-DD`) at load time.
  final String? businessDate;

  @override
  bool operator ==(Object other) => other is BranchInfo && other.id == id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => 'BranchInfo($id, $name)';
}

/// Parsed `GET /auth/context`.
@immutable
class AuthContext {
  /// Creates a context (tests may build one directly).
  const AuthContext({
    required this.employeeId,
    required this.fullName,
    required this.roleCode,
    this.roleName = '',
    this.companyId,
    this.companyName = '',
    this.companyCode,
    this.permissions = const {},
    this.fullAccess = false,
    this.actorBranch,
    this.branchScope = 'assigned',
    this.branches = const [],
  });

  /// Parses the server payload.
  factory AuthContext.fromJson(Map<String, dynamic> j) {
    final e = (j['employee'] as Map?)?.cast<String, dynamic>() ?? const {};
    final c = (j['company'] as Map?)?.cast<String, dynamic>() ?? const {};
    final ab = j['actor_branch'];
    return AuthContext(
      employeeId: '${e['id'] ?? ''}',
      fullName: '${e['full_name'] ?? ''}',
      roleCode: '${e['role_code'] ?? ''}',
      roleName: '${e['role_name'] ?? ''}',
      companyId: c['id']?.toString(),
      companyName: '${c['name'] ?? ''}',
      companyCode: c['code']?.toString(),
      permissions: {for (final p in (j['permissions'] as List? ?? const [])) '$p'},
      fullAccess: j['full_access'] == true,
      actorBranch: ab is Map ? BranchInfo.fromJson(ab.cast<String, dynamic>()) : null,
      branchScope: '${j['branch_scope'] ?? 'assigned'}',
      branches: [
        for (final b in (j['branches'] as List? ?? const []))
          if (b is Map) BranchInfo.fromJson(b.cast<String, dynamic>())
      ],
    );
  }

  /// Employee id.
  final String employeeId;

  /// Employee full name.
  final String fullName;

  /// Role code (`ega`, `administrator`, `menejer`, `omborchi`, `kassir`, ...).
  final String roleCode;

  /// Localized role name from the server.
  final String roleName;

  /// Company id / name / code.
  final String? companyId;

  /// Company display name.
  final String companyName;

  /// Company login code.
  final String? companyCode;

  /// Effective permission codes (role + overrides).
  final Set<String> permissions;

  /// True for `ega` / `administrator` (server bypass).
  final bool fullAccess;

  /// The branch the server WRITES to for branch-less writes (receiving, cash ops).
  final BranchInfo? actorBranch;

  /// `"all"` (owner) or `"assigned"`.
  final String branchScope;

  /// Branches the caller may see (ordered by the server).
  final List<BranchInfo> branches;
}

/// Load state of the [Session].
enum SessionStatus {
  /// Nobody is signed in.
  signedOut,

  /// A load is running and no context is known yet.
  loading,

  /// `/auth/context` loaded (possibly refreshed in the background).
  ready,

  /// The server has no `/auth/context` (older backend): permissions come from
  /// the login snapshot and no branch list is known.
  degraded,

  /// Loading failed and nothing is known yet (see [Session.lastError]).
  error,
}

/// The signed-in session: identity, permissions, visible branches and the
/// branch currently worked on. Listen to it to rebuild on changes.
class Session extends ChangeNotifier with WidgetsBindingObserver {
  Session._();

  /// The app-wide session.
  static final Session instance = Session._();

  AuthContext? _ctx;
  SessionStatus _status = SessionStatus.signedOut;
  Object? _lastError;
  DateTime? _loadedAt;
  String? _currentId;
  int _branchEpoch = 0;
  Future<void>? _inflight;
  int _inflightEpoch = -1;
  bool _attached = false;
  final List<VoidCallback> _branchCaches = [];

  /// Minimum age before a foreground resume reloads the context.
  static Duration resumeRefreshAfter = const Duration(seconds: 20);

  /// The loaded context, if any.
  AuthContext? get context => _ctx;

  /// Current load state.
  SessionStatus get status => _status;

  /// Error of the last failed load (null after a success).
  Object? get lastError => _lastError;

  /// When the context was last loaded successfully.
  DateTime? get loadedAt => _loadedAt;

  /// Increments whenever the current branch changes (use as a cache/rebuild key).
  int get branchEpoch => _branchEpoch;

  // ── Lifecycle ────────────────────────────────────────────────────────────

  /// Hooks the session to [Api.authEpoch] (login / logout / 401 / server
  /// change) and to app resume. Idempotent; called once from `main`.
  void attach() {
    if (_attached) return;
    _attached = true;
    Api.authEpoch.addListener(_onAuthChanged);
    WidgetsBinding.instance.addObserver(this);
    if (Api.loggedIn) unawaited(load());
  }

  /// Undoes [attach] (tests).
  @visibleForTesting
  void detach() {
    if (!_attached) return;
    _attached = false;
    Api.authEpoch.removeListener(_onAuthChanged);
    WidgetsBinding.instance.removeObserver(this);
  }

  /// Clears all state (tests).
  @visibleForTesting
  void debugReset() {
    detach();
    _ctx = null;
    _status = SessionStatus.signedOut;
    _lastError = null;
    _loadedAt = null;
    _currentId = null;
    _branchEpoch = 0;
    _inflight = null;
    _branchCaches.clear();
  }

  void _onAuthChanged() {
    if (Api.loggedIn) {
      unawaited(load(force: true));
    } else {
      _signOut();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(refreshIfStale(resumeRefreshAfter));
  }

  /// Reloads the context when it is older than [maxAge] (or missing).
  Future<void> refreshIfStale(Duration maxAge) async {
    if (!Api.loggedIn) return;
    final at = _loadedAt;
    if (at != null && DateTime.now().difference(at) < maxAge) return;
    await load(force: true);
  }

  void _signOut() {
    final hadBranch = currentBranchId != null;
    _ctx = null;
    _status = SessionStatus.signedOut;
    _lastError = null;
    _loadedAt = null;
    _currentId = null;
    _inflight = null;
    if (hadBranch) _bumpBranch();
    notifyListeners();
  }

  /// Loads `GET /auth/context`. Concurrent calls share one request. With
  /// [force] false an already loaded context is kept.
  ///
  /// Failures never sign the user out by themselves (a 401 does that through
  /// [Api]); a network error keeps the previous context.
  Future<void> load({bool force = false}) {
    if (!Api.loggedIn) {
      _signOut();
      return Future.value();
    }
    if (!force && _ctx != null) return Future.value();
    final epoch = Api.authEpoch.value;
    final running = _inflight;
    if (running != null && _inflightEpoch == epoch) return running;
    _inflightEpoch = epoch;
    late final Future<void> f;
    f = _load().whenComplete(() {
      if (identical(_inflight, f)) _inflight = null;
    });
    return _inflight = f;
  }

  Future<void> _load() async {
    final epoch = Api.authEpoch.value;
    if (_ctx == null) {
      _status = SessionStatus.loading;
      notifyListeners();
    }
    try {
      final res = await Api.getJson('/auth/context');
      if (epoch != Api.authEpoch.value) return; // user changed meanwhile
      final ctx = AuthContext.fromJson(res.map);
      final prevBranch = currentBranchId;
      _ctx = ctx;
      _status = SessionStatus.ready;
      _lastError = null;
      _loadedAt = DateTime.now();
      await _restoreBranch(prevBranch);
      await Api.updateEmployeeSnapshot({
        'permissions': ctx.permissions.toList()..sort(),
        'role_code': ctx.roleCode,
        if (ctx.roleName.isNotEmpty) 'role_name': ctx.roleName,
        if (ctx.fullName.isNotEmpty) 'full_name': ctx.fullName,
        if (ctx.companyName.isNotEmpty) 'company_name': ctx.companyName,
        if (ctx.companyCode != null) 'company_code': ctx.companyCode,
        if (ctx.actorBranch != null) 'branch_name': ctx.actorBranch!.name,
      });
    } on ApiException catch (e) {
      // ⚠️  401 ni [Api] O'ZI qayta ishlaydi: tokenni tozalab, `authEpoch` ni
      //     shu istisno bu yergacha yetib kelishidan OLDIN oshiradi. Shu bois
      //     "auth" holati epoch qorovulidan OLDIN tekshiriladi — aks holda
      //     sessiya (ilova `attach()` qilmagan paytda) `loading` da muzlab
      //     qolardi. `!Api.loggedIn` sharti muhim: epoch BOSHQA foydalanuvchi
      //     kirgani uchun o'zgargan bo'lsa, eski 401 uni chiqarib yubormaydi.
      if (e.kind == ApiErrorKind.auth && !Api.loggedIn) {
        _signOut();
        return;
      }
      if (epoch != Api.authEpoch.value) return;
      _lastError = e;
      if (e.kind == ApiErrorKind.auth) {
        _signOut();
        return;
      }
      if (_ctx == null) {
        // Eski server (`/auth/context` yo'q) — login suratidan cheklangan rejim.
        _status = (e.status == 404 || e.status == 405) ? SessionStatus.degraded : SessionStatus.error;
      }
    } catch (e) {
      // Kutilmagan javob shakli: oldingi kontekst saqlanadi, yangisi O'YLAB TOPILMAYDI.
      if (epoch != Api.authEpoch.value) return;
      _lastError = e;
      if (_ctx == null) _status = SessionStatus.error;
    } finally {
      if (epoch == Api.authEpoch.value) notifyListeners();
    }
  }

  // ── Permissions ──────────────────────────────────────────────────────────

  /// Role code (context, else the login snapshot).
  String get roleCode => _ctx?.roleCode ?? '${Api.employee?['role_code'] ?? ''}';

  /// True for full-access roles (`ega` / `administrator`).
  bool get fullAccess => _ctx?.fullAccess ?? kFullAccessRoles.contains(roleCode);

  /// Effective permissions (context, else the login snapshot).
  Set<String> get permissions {
    final c = _ctx;
    if (c != null) return c.permissions;
    final p = Api.employee?['permissions'];
    return p is List ? {for (final x in p) '$x'} : const {};
  }

  /// Mirrors the server's `require(code)`: full access OR the permission.
  bool can(String code) => Api.loggedIn && (fullAccess || permissions.contains(code));

  /// Mirrors `require_any(codes)`; an empty list means "any signed-in user".
  bool canAny(Iterable<String> codes) {
    if (!Api.loggedIn) return false;
    if (codes.isEmpty || fullAccess) return true;
    final p = permissions;
    return codes.any(p.contains);
  }

  // ── Branches ─────────────────────────────────────────────────────────────

  /// Visible branches (empty until loaded or on an older server).
  List<BranchInfo> get branches => _ctx?.branches ?? const [];

  /// Branches the operator may switch to (visible AND active).
  List<BranchInfo> get selectableBranches => [for (final b in branches) if (b.isActive) b];

  /// The branch the server writes branch-less documents to.
  BranchInfo? get actorBranch => _ctx?.actorBranch;

  /// The branch every branch-scoped read/write uses (`branch_id`).
  ///
  /// Default: the actor branch; else the only visible branch; else `null`
  /// (never a silent guess among several).
  BranchInfo? get currentBranch {
    final id = _currentId;
    if (id != null) {
      for (final b in branches) {
        if (b.id == id) return b;
      }
    }
    return _defaultBranch();
  }

  /// Shortcut for `currentBranch?.id`.
  String? get currentBranchId => currentBranch?.id;

  /// True when the current branch is the one receiving/cash writes go to.
  bool get currentIsActor {
    final a = actorBranch, c = currentBranch;
    return a != null && c != null && a.id == c.id;
  }

  /// True when there is more than one branch to choose from.
  bool get canSwitchBranch => selectableBranches.length > 1;

  BranchInfo? _defaultBranch() {
    final a = actorBranch;
    if (a != null) {
      for (final b in branches) {
        if (b.id == a.id) return b;
      }
      if (branches.isEmpty) return a;
    }
    final sel = selectableBranches;
    if (sel.length == 1) return sel.first;
    return null;
  }

  /// Switches the working branch. Only a visible, active branch is accepted.
  /// Clears every registered branch-scoped cache and notifies listeners.
  Future<void> selectBranch(String branchId) async {
    final ok = selectableBranches.any((b) => b.id == branchId);
    if (!ok) throw ArgumentError.value(branchId, 'branchId', 'not a visible active branch');
    if (currentBranchId == branchId) return;
    _currentId = branchId;
    _bumpBranch();
    notifyListeners();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString(_prefKey(), branchId);
    } catch (_) {}
  }

  Future<void> _restoreBranch(String? before) async {
    String? saved;
    try {
      saved = (await SharedPreferences.getInstance()).getString(_prefKey());
    } catch (_) {}
    final valid = saved != null && selectableBranches.any((b) => b.id == saved);
    _currentId = valid ? saved : null;
    if (currentBranchId != before) _bumpBranch();
  }

  void _bumpBranch() {
    _branchEpoch++;
    for (final clear in List.of(_branchCaches)) {
      try {
        clear();
      } catch (_) {}
    }
  }

  /// Registers [clear] to run whenever the branch changes (or the user signs
  /// out). Returns a function that unregisters it.
  VoidCallback registerBranchCache(VoidCallback clear) {
    _branchCaches.add(clear);
    return () => _branchCaches.remove(clear);
  }

  /// `{'branch_id': id}` for branch-scoped requests, `{}` when unknown (the
  /// server then uses the actor branch).
  Map<String, String> branchQuery() {
    final id = currentBranchId;
    return id == null ? const {} : {'branch_id': id};
  }

  /// Business date (`YYYY-MM-DD`) of [branchId] (default: current branch).
  String? businessDate([String? branchId]) {
    final id = branchId ?? currentBranchId;
    if (id == null) return null;
    for (final b in branches) {
      if (b.id == id) return b.businessDate;
    }
    final a = actorBranch;
    return a != null && a.id == id ? a.businessDate : null;
  }

  // ── Namespacing ──────────────────────────────────────────────────────────

  String _scope() {
    final emp = _ctx?.employeeId ?? '${Api.employee?['id'] ?? '-'}';
    final co = _ctx?.companyId ?? '${Api.employee?['company_code'] ?? '-'}';
    return '${Api.serverKey()}|$co|$emp';
  }

  String _prefKey() => 'session.branch.${_scope()}';

  /// A cache key namespaced by server + company + employee + current branch,
  /// so data cached for branch A is never read under branch B or another user.
  String cacheKey(String name) => '$name@${_scope()}|${currentBranchId ?? '-'}';
}
