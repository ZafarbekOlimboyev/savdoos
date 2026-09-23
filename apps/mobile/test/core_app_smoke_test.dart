// Compile + boot smoke test: the whole app (every screen) compiles, and the
// signed-out app renders the login screen on a 390×844 phone without layout
// errors. HEAD before Phase 5G did not compile (receiving_review_screen.dart:539).
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/main.dart';
import 'package:savdoos_mobile/screens/analytics_screen.dart';
import 'package:savdoos_mobile/screens/barcode_scan_screen.dart';
import 'package:savdoos_mobile/screens/cash_ops_screen.dart';
import 'package:savdoos_mobile/screens/correction_screen.dart';
import 'package:savdoos_mobile/screens/customer_edit_screen.dart';
import 'package:savdoos_mobile/screens/customer_profile_screen.dart';
import 'package:savdoos_mobile/screens/customers_screen.dart';
import 'package:savdoos_mobile/screens/debtors_screen.dart';
import 'package:savdoos_mobile/screens/detail_report_screen.dart';
import 'package:savdoos_mobile/screens/employee_edit_screen.dart';
import 'package:savdoos_mobile/screens/employees_screen.dart';
import 'package:savdoos_mobile/screens/home_screen.dart';
import 'package:savdoos_mobile/screens/inventarizatsiya_screen.dart';
import 'package:savdoos_mobile/screens/inventory_screen.dart';
import 'package:savdoos_mobile/screens/login_screen.dart';
import 'package:savdoos_mobile/screens/manual_receiving_screen.dart';
import 'package:savdoos_mobile/screens/notifications_screen.dart';
import 'package:savdoos_mobile/screens/password_change_screen.dart';
import 'package:savdoos_mobile/screens/pin_screens.dart';
import 'package:savdoos_mobile/screens/product_detail_screen.dart';
import 'package:savdoos_mobile/screens/purchase_detail_screen.dart';
import 'package:savdoos_mobile/screens/receipt_screen.dart';
import 'package:savdoos_mobile/screens/receiving_detail_screen.dart';
import 'package:savdoos_mobile/screens/receiving_draft_screen.dart';
import 'package:savdoos_mobile/screens/receiving_home_screen.dart';
import 'package:savdoos_mobile/screens/receiving_item_editor_screen.dart';
import 'package:savdoos_mobile/screens/receiving_review_screen.dart';
import 'package:savdoos_mobile/screens/receiving_success_screen.dart';
import 'package:savdoos_mobile/screens/sales_detail_screen.dart';
import 'package:savdoos_mobile/screens/sales_list_screen.dart';
import 'package:savdoos_mobile/screens/settings_screen.dart';
import 'package:savdoos_mobile/screens/shell.dart';
import 'package:savdoos_mobile/screens/supplier_detail_screen.dart';
import 'package:savdoos_mobile/screens/suppliers_screen.dart';
import 'package:savdoos_mobile/screens/tariff_screen.dart';
import 'package:savdoos_mobile/screens/transfer_screen.dart';
import 'package:savdoos_mobile/screens/writeoff_screen.dart';

import 'support/support.dart';

void main() {
  setUp(() async => resetCore());

  test('every screen compiles', () {
    const screens = <Type>[
      AnalyticsScreen, BarcodeScanScreen, CashOpsScreen, CustomerProfileScreen, CustomersScreen, DebtorsScreen,
      DetailReportScreen, EmployeeEditScreen, EmployeesScreen, HomeScreen, InventarizatsiyaScreen, InventoryScreen,
      LoginScreen, ManualReceivingScreen, NotificationsScreen, PasswordChangeScreen, PinSetupScreen, LockScreen,
      ProductDetailScreen, ReceivingDetailScreen, ReceivingHomeScreen, ReceivingItemEditorScreen,
      ReceivingReviewScreen, ReceivingSuccessScreen, SalesDetailScreen, SalesListScreen, SettingsScreen, Shell,
      SuppliersScreen, TariffScreen, TransferScreen, WriteoffScreen, SavdoApp,
      // Phase 5G screens
      PurchaseDetailScreen, CorrectionScreen, ReceivingDraftScreen, SupplierDetailScreen, ReceiptScreen,
      CustomerEditScreen,
    ];
    expect(screens, hasLength(39));
  });

  testWidgets('signed-out app boots to the login screen at 390×844', (tester) async {
    await pumpAt390(tester, const SavdoApp(), wrap: false);
    await tester.pumpAndSettle();
    expect(find.byType(LoginScreen), findsOneWidget);
  });
}
