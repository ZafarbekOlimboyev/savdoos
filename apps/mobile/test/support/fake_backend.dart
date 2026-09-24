// In-memory HTTP backend for widget/unit tests.
//
// Routes are matched on METHOD + path template (relative to `/api/v1`,
// `{name}` matches one segment). Every request is recorded in [FakeBackend.log].
// Requests are intercepted through `http.runWithClient` (see [FakeBackend.run]),
// so production code keeps calling the top-level `http.get/post/...`.
//
// ```dart
// final be = FakeBackend()..get('/products', (r) => [{'id': 'p1'}]);
// await be.run(() async {
//   final res = await Api.getJson('/products', query: {'q': 'sut'});
// });
// expect(be.last('GET', '/products').query['q'], 'sut');
// ```
import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// A recorded request.
class FakeRequest {
  FakeRequest(this.raw, this.params);

  /// The raw `http` request.
  final http.Request raw;

  /// Path parameters captured from the route template.
  final Map<String, String> params;

  /// HTTP method.
  String get method => raw.method;

  /// Path relative to `/api/v1`.
  String get path {
    final p = raw.url.path;
    const prefix = '/api/v1';
    return p.startsWith(prefix) ? p.substring(prefix.length) : p;
  }

  /// Query parameters (last value wins).
  Map<String, String> get query => raw.url.queryParameters;

  /// Query parameters with repeated keys.
  Map<String, List<String>> get queryAll => raw.url.queryParametersAll;

  /// Request headers (lower-case keys as sent by `http`).
  Map<String, String> get headers => {for (final e in raw.headers.entries) e.key.toLowerCase(): e.value};

  /// Decoded JSON body (null when empty).
  Object? get json => raw.body.isEmpty ? null : jsonDecode(raw.body);

  /// JSON body as a map.
  Map<String, dynamic> get body => (json as Map).cast<String, dynamic>();

  @override
  String toString() => '$method $path ${raw.url.query}';
}

/// A scripted response.
class FakeResponse {
  FakeResponse(this.status, {this.body, this.headers = const {}, this.text});

  /// JSON response.
  factory FakeResponse.json(Object? body, {int status = 200, Map<String, String> headers = const {}}) =>
      FakeResponse(status, body: body, headers: headers);

  /// FastAPI-style error `{"detail": detail}` with an optional `X-Error-Code`.
  factory FakeResponse.error(int status, Object? detail, {String? code}) => FakeResponse(
        status,
        body: {'detail': detail},
        headers: {if (code != null) 'x-error-code': code},
      );

  /// A non-JSON body (e.g. a captive portal page).
  factory FakeResponse.raw(int status, String text) => FakeResponse(status, text: text);

  final int status;
  final Object? body;
  final String? text;
  final Map<String, String> headers;
}

/// Handler: return a [FakeResponse], any JSON value (-> 200), or throw to
/// simulate a transport failure.
typedef FakeHandler = FutureOr<Object?> Function(FakeRequest req);

class _Route {
  _Route(this.method, this.pattern, this.handler) : parts = pattern.split('/');
  final String method, pattern;
  final List<String> parts;
  final FakeHandler handler;

  Map<String, String>? match(String method, String path) {
    if (method != this.method) return null;
    final segs = path.split('/');
    if (segs.length != parts.length) return null;
    final out = <String, String>{};
    for (var i = 0; i < segs.length; i++) {
      final p = parts[i];
      if (p.startsWith('{') && p.endsWith('}')) {
        out[p.substring(1, p.length - 1)] = Uri.decodeComponent(segs[i]);
      } else if (p != segs[i]) {
        return null;
      }
    }
    return out;
  }
}

/// The fake server.
class FakeBackend {
  FakeBackend();

  /// Base URL tests point `Api.baseUrl` at.
  static const String baseUrl = 'http://fake.test';

  /// All requests, in order.
  final List<FakeRequest> log = [];

  final List<_Route> _routes = [];

  /// When true every request fails like an unreachable server.
  bool offline = false;

  /// Registers a route (later registrations win).
  void on(String method, String pattern, FakeHandler handler) =>
      _routes.insert(0, _Route(method.toUpperCase(), pattern, handler));

  /// GET route.
  void get(String pattern, FakeHandler h) => on('GET', pattern, h);

  /// POST route.
  void post(String pattern, FakeHandler h) => on('POST', pattern, h);

  /// PATCH route.
  void patch(String pattern, FakeHandler h) => on('PATCH', pattern, h);

  /// DELETE route.
  void delete(String pattern, FakeHandler h) => on('DELETE', pattern, h);

  /// Requests matching [method] and exact [path].
  List<FakeRequest> calls(String method, String path) =>
      [for (final r in log) if (r.method == method.toUpperCase() && r.path == path) r];

  /// The last request to [method] [path] (throws if none).
  FakeRequest last(String method, String path) => calls(method, path).last;

  /// The mock client.
  MockClient get client => MockClient(_handle);

  /// Runs [body] with every `http` call routed to this backend.
  Future<T> run<T>(Future<T> Function() body) => http.runWithClient(body, () => client);

  Future<http.Response> _handle(http.Request req) async {
    final path = req.url.path.startsWith('/api/v1') ? req.url.path.substring(7) : req.url.path;
    Map<String, String>? params;
    _Route? route;
    for (final r in _routes) {
      params = r.match(req.method, path);
      if (params != null) {
        route = r;
        break;
      }
    }
    final fr = FakeRequest(req, params ?? const {});
    log.add(fr);
    // What `package:http` really throws on BOTH platforms: `IOClient` wraps a
    // `SocketException` into a `ClientException`, `BrowserClient` throws one
    // directly. A raw `SocketException` here would model a branch web never takes.
    if (offline) throw http.ClientException('Connection refused (fake offline)', req.url);
    if (route == null) {
      return http.Response(jsonEncode({'detail': 'Not Found'}), 404,
          headers: {'content-type': 'application/json'}, request: req);
    }
    final out = await route.handler(fr);
    final resp = out is FakeResponse ? out : FakeResponse.json(out);
    final text = resp.text ?? (resp.body == null && resp.status == 204 ? '' : jsonEncode(resp.body));
    return http.Response.bytes(utf8.encode(text), resp.status,
        headers: {'content-type': resp.text != null ? 'text/html' : 'application/json', ...resp.headers},
        request: req);
  }
}

/// `/auth/context` payload builder.
Map<String, dynamic> contextJson({
  String employeeId = 'e1',
  String fullName = 'Test User',
  String role = 'ega',
  List<String> permissions = const [],
  bool? fullAccess,
  String companyId = 'c1',
  String companyName = 'Fayzan',
  String companyCode = 'fayzan1',
  Map<String, dynamic>? actorBranch,
  List<Map<String, dynamic>>? branches,
  String branchScope = 'assigned',
}) {
  final bs = branches ?? [branchJson('b1', 'Markaz')];
  return {
    'employee': {'id': employeeId, 'full_name': fullName, 'role_code': role, 'role_name': role},
    'company': {'id': companyId, 'name': companyName, 'code': companyCode},
    'permissions': permissions,
    'full_access': fullAccess ?? (role == 'ega' || role == 'administrator'),
    'actor_branch': actorBranch ?? (bs.isEmpty ? null : bs.first),
    'branch_scope': branchScope,
    'branches': bs,
  };
}

/// One branch entry.
Map<String, dynamic> branchJson(String id, String name,
        {bool active = true, String businessDate = '2026-09-19', String timezone = 'Asia/Bishkek'}) =>
    {'id': id, 'name': name, 'is_active': active, 'timezone': timezone, 'business_date': businessDate};
