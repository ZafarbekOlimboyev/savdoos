// FileExport / Sharing adapters (B4 item 3): the CSV export must never surface
// a `MissingPluginException` or a raw share_plus `Exception`; the content is
// built once, platform-neutrally, and handed to the adapter.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/platform/platform.dart';
import 'package:savdoos_mobile/report_export.dart';

import 'support/support.dart';

Overview _ov() => Overview.fromJson({
      'kpi': {'sales': 125000, 'profit': 30000, 'avg_check': 2500, 'tx': 50},
      'delta': {},
      'series': [],
      'top_products': [
        {'name': 'Sut "Toza" 1L', 'revenue': 40000}
      ],
      'cashiers': [
        {'name': 'Aziz', 'sales': 125000, 'tx': 50}
      ],
      'payments': [],
      'credit_total': 0,
    });

class _Unavailable implements FileExport {
  @override
  bool get supported => false;

  @override
  Future<void> share({required String filename, required String mime, required List<int> bytes, String? text}) =>
      throw const PlatformUnavailable(PlatformUnavailable.kShare);
}

void main() {
  setUp(() async => resetCore());

  test('csv hands one text/csv file with a UTF-8 BOM to the adapter (no filesystem in the business code)', () async {
    signIn();
    await ReportExport.csv(_ov(), null, 'Bugun');
    expect(PlatformMocks.exports, hasLength(1));
    final e = PlatformMocks.exports.single;
    expect(e.filename, 'BinOS-Savdo hisoboti.csv');
    expect(e.mime, 'text/csv');
    expect(e.text, 'BinOS Savdo hisoboti · Bugun');
    expect(e.bytes.take(3).toList(), [0xEF, 0xBB, 0xBF], reason: 'Excel needs the BOM for Cyrillic');
    final body = utf8.decode(e.bytes);
    expect(body, contains('"Savdo";"125000.0"'));
    expect(body, contains('"Sut ""Toza"" 1L";"40000.0"'), reason: 'quotes are doubled');
    expect(body, contains('"Aziz";"125000.0";"50"'));
  });

  test('text goes through the Sharing adapter', () async {
    signIn();
    await ReportExport.text(_ov(), null, 'Bugun');
    expect(PlatformMocks.sharedTexts, hasLength(1));
    expect(PlatformMocks.sharedTexts.single, contains('Savdo: '));
  });

  test('an unavailable platform surfaces a typed, localized error — never a generic one', () async {
    FileExport.instance = _Unavailable();
    Object? err;
    try {
      await ReportExport.csv(_ov(), null, 'Bugun');
    } catch (e) {
      err = e;
    }
    expect(err, isA<PlatformUnavailable>());
    expect('$err', 'Ulashib bo‘lmadi');
    L.code = 'ru';
    expect('$err', 'Не удалось поделиться');
  });

  test('FakeFileExport records nothing when the adapter throws', () async {
    FileExport.instance = _Unavailable();
    await expectLater(ReportExport.csv(_ov(), null, 'Bugun'), throwsA(isA<PlatformUnavailable>()));
    expect(PlatformMocks.exports, isEmpty);
  });

  test('Sharing wraps a raw share_plus failure into PlatformUnavailable', () async {
    Sharing.instance = _ThrowingSharing();
    await expectLater(ReportExport.text(_ov(), null, 'Bugun'), throwsA(isA<PlatformUnavailable>()));
  });

  test('PlatformUnavailable.message is a translated key', () {
    L.code = 'ky';
    expect(const PlatformUnavailable(PlatformUnavailable.kShare).toString(), 'Бөлүшүү мүмкүн болбоду');
  });
}

class _ThrowingSharing implements Sharing {
  @override
  Future<void> text(String body, {String? subject}) => throw const PlatformUnavailable(PlatformUnavailable.kShare);
}
