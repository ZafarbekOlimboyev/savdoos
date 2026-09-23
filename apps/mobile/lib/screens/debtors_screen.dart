import 'package:flutter/material.dart';

import 'customers_screen.dart';

/// Debtors: the customers list on its "debtors only" filter (server-side
/// `only_debt=true`), with the total and the same profile / payment flow.
///
/// Kept as a named entry point for navigation; it no longer has its own
/// (untranslated, ungated) list.
class DebtorsScreen extends StatelessWidget {
  /// Creates the screen.
  const DebtorsScreen({super.key});

  @override
  Widget build(BuildContext context) => const CustomersScreen(onlyDebt: true);
}
