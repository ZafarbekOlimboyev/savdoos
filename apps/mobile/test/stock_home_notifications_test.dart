// M2 home "attention" + notifications: built from /inventory/overview,
// /inventory/low and /lots/alerts (per permission) — never the full
// /products catalog; lot alerts follow the current branch; expiring lots list
// with a write-off shortcut that keeps the branch.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/screens/home_screen.dart';
import 'package:savdoos_mobile/screens/notifications_screen.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';
import 'package:savdoos_mobile/session.dart';

import 'stock_fixtures_test.dart';

Map<String, dynamic> alertsJson({int expired = 2, int today = 1, int w7 = 4, int w30 = 9, int shortfalls = 0}) => {
      'expiry': {
        'expired': {'lots': expired, 'qty': 3, 'value_at_risk': 1000},
        'expires_today': {'lots': today, 'qty': 1, 'value_at_risk': 10},
        'within_7_days': {'lots': w7, 'qty': 1, 'value_at_risk': 10},
        'within_30_days': {'lots': w30, 'qty': 1, 'value_at_risk': 10},
      },
      'shortfalls': {'open_count': shortfalls, 'open_qty': shortfalls},
      'cost_quality': {'tracked_products': 5},
    };

void main() {
  late FakeBackend be;

  setUp(() async {
    await resetCore();
    be = FakeBackend()
      ..get(
          '/reports/overview',
          (r) => {
                'kpi': {'sales': 1000}
              })
      ..get('/sales', (r) => [])
      ..get('/inventory/overview', (r) => {'total_products': 100, 'low_count': 3, 'out_count': 2, 'moves_today': 0})
      ..get(
          '/inventory/low',
          (r) => [
                {'name': 'Tuz', 'qty': 1, 'min': 5},
              ])
      ..get('/lots/alerts', (r) => alertsJson())
      ..get(
          '/lots/batches',
          (r) => {
                'total': 1,
                'lots': [
                  {
                    'id': 'l1',
                    'product_id': 'p1',
                    'product': 'Qatiq',
                    'unit_code': 'dona',
                    'batch_number': 'A-1',
                    'expiry_date': '2026-09-10',
                    'bucket': 'expired',
                    'expired': true,
                    'remaining_qty': 2,
                    'unit_cost': 1000,
                  },
                ],
              })
      ..get('/lots/products/{id}', (r) => lotsJson('p1', [lotJson('l1', batch: 'A-1', expired: true, remaining: 2)]));
  });
  tearDown(() => Session.instance.debugReset());

  group('home attention', () {
    testWidgets('owner: overview + lot alerts of the current branch, never /products', (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const HomeScreen());
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/products'), isEmpty, reason: 'the full catalog is not loaded on the home screen');
      expect(be.calls('GET', '/inventory/overview'), hasLength(1));
      expect(be.last('GET', '/lots/alerts').query['branch_id'], 'b1');
      expect(find.byKey(const Key('home-attention')), findsOneWidget);
      expect(find.text('7'), findsOneWidget, reason: 'expired + today + within 7 days lots');
      expect(find.text('kam qolgan'), findsOneWidget);
    });

    testWidgets('branch switch reloads the lot alerts for the new branch', (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const HomeScreen());
        await tester.pumpAndSettle();
        await Session.instance.selectBranch('b2');
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/lots/alerts').map((c) => c.query['branch_id']), ['b1', 'b2']);
    });

    testWidgets('kassir: no stock / lot / report requests (no permission), no attention card', (tester) async {
      await signInAs(be, role: 'kassir');
      await be.run(() async {
        await pumpAt390(tester, const HomeScreen());
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/inventory/overview'), isEmpty);
      expect(be.calls('GET', '/lots/alerts'), isEmpty);
      expect(be.calls('GET', '/reports/overview'), isEmpty);
      expect(be.calls('GET', '/products'), isEmpty);
      expect(find.byKey(const Key('home-attention')), findsNothing);
    });

    testWidgets('omborchi: lot alerts only (no hisobot.view)', (tester) async {
      await signInAs(be, role: 'omborchi');
      await be.run(() async {
        await pumpAt390(tester, const HomeScreen());
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/inventory/overview'), isEmpty);
      expect(be.calls('GET', '/lots/alerts'), hasLength(1));
      expect(find.byKey(const Key('home-attention')), findsOneWidget);
      expect(find.text('kam qolgan'), findsNothing);
    });
  });

  group('notifications', () {
    testWidgets('owner: expiry buckets (branch) + stock summary; bucket -> lots -> write-off keeps the branch',
        (tester) async {
      await signInAs(be);
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('nt-bucket-expired')), findsOneWidget);
        expect(find.byKey(const Key('nt-out')), findsOneWidget);
        expect(find.byKey(const Key('nt-low-Tuz')), findsOneWidget);
        await tester.tap(find.byKey(const Key('nt-bucket-expired')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('nt-lot-l1')), findsOneWidget);
        await tester.tap(find.byKey(const Key('nt-wo-l1')));
        await tester.pumpAndSettle();
      });
      expect(be.last('GET', '/lots/alerts').query['branch_id'], 'b1');
      expect(be.last('GET', '/lots/batches').query,
          {'branch_id': 'b1', 'expiry': 'expired', 'status': 'open', 'sort': 'expiry', 'order': 'asc', 'limit': '50'});
      expect(find.byType(WriteoffScreen), findsOneWidget);
      expect(be.last('GET', '/lots/products/p1').query['branch_id'], 'b1');
      expect(be.calls('GET', '/products'), isEmpty);
    });

    testWidgets('omborchi: only the lot section (no /inventory/overview)', (tester) async {
      await signInAs(be, role: 'omborchi');
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
      });
      expect(be.calls('GET', '/inventory/overview'), isEmpty);
      expect(be.calls('GET', '/inventory/low'), isEmpty);
      expect(find.byKey(const Key('nt-bucket-expired')), findsOneWidget);
    });

    testWidgets('kassir: explicit "no permission", no requests', (tester) async {
      await signInAs(be, role: 'kassir');
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
      });
      expect(find.byKey(const Key('nt-denied')), findsOneWidget);
      expect(be.calls('GET', '/lots/alerts'), isEmpty);
      expect(be.calls('GET', '/inventory/overview'), isEmpty);
    });

    testWidgets('nothing expiring: calm message; shortfalls are surfaced', (tester) async {
      await signInAs(be, role: 'omborchi');
      be.get('/lots/alerts', (r) => alertsJson(expired: 0, today: 0, w7: 0, w30: 0, shortfalls: 2));
      await be.run(() async {
        await pumpAt390(tester, const NotificationsScreen());
        await tester.pumpAndSettle();
      });
      expect(find.byKey(const Key('nt-expiry-ok')), findsOneWidget);
      expect(find.byKey(const Key('nt-shortfall')), findsOneWidget);
    });
  });
}
