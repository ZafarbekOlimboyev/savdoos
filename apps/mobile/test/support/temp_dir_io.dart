// VM only (reached by conditional import from platform_mocks.dart): the
// directory `path_provider` answers with, created LAZILY on first use so the
// support layer itself never touches `dart:io` at setUp.
import 'dart:io';

String? _path;

/// Path of a per-run temp directory.
String tempDirPath() => _path ??= Directory.systemTemp.createTempSync('savdoos_test_').path;
