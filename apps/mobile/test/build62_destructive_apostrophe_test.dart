import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/ui/confirm_destructive.dart';
import 'package:savdoos_mobile/ui/confirm_erase.dart';
import 'support/support.dart';

void main() {
  testWidgets('apostrophe variants preserve acknowledgement guard', (tester) async {
    await pumpAt390(tester, Scaffold(body: Builder(builder: (context) =>
      TextButton(onPressed: () => confirmDestructive(context,
        title: 'Test', message: 'No API call', typedPhrase: kEraseConfirmWord,
        requireAcknowledge: true), child: const Text('open')))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    final field = find.byKey(const Key('confirm-typed'));
    expect(tester.widget<TextField>(field).smartQuotesType, SmartQuotesType.disabled);
    final button = find.byKey(const Key('confirm-yes'));
    await tester.enterText(field, 'O’CHIRISH');
    await tester.pumpAndSettle();
    expect(tester.widget<ElevatedButton>(button).onPressed, isNull);
    await tester.tap(find.byKey(const Key('confirm-ack')));
    await tester.pumpAndSettle();
    for (final phrase in ["O'CHIRISH", 'O’CHIRISH', 'OʻCHIRISH']) {
      await tester.enterText(field, phrase);
      await tester.pumpAndSettle();
      expect(tester.widget<ElevatedButton>(button).onPressed, isNotNull);
    }
    await tester.enterText(field, 'OCHIRISH');
    await tester.pumpAndSettle();
    expect(tester.widget<ElevatedButton>(button).onPressed, isNull);
  });
  testWidgets('smart phrase requires password and returns exact server token', (tester) async {
    Future<EraseConfirmation?>? result;
    const serverToken = 'OʻCHIRISH';
    await pumpAt390(tester, Scaffold(body: Builder(builder: (context) =>
      TextButton(onPressed: () => result = confirmErase(context,
        title: 'Test', message: 'No API call', phrase: serverToken),
        child: const Text('open')))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('erase-phrase')), 'O’CHIRISH');
    await tester.pumpAndSettle();
    final button = find.byKey(const Key('erase-submit'));
    expect(tester.widget<FilledButton>(button).onPressed, isNull);
    await tester.enterText(find.byKey(const Key('erase-password')), 'synthetic-only');
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect((await result)!.phrase, serverToken);
  });
}
