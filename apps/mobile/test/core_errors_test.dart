import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:savdoos_mobile/api.dart';
import 'package:savdoos_mobile/errors.dart';
import 'package:savdoos_mobile/l10n.dart';
import 'package:savdoos_mobile/platform/platform.dart';

ApiException ex(int status, Object? detail, {String? code}) => ApiException(
      status,
      ApiException.flatten(detail) ?? '',
      detail: detail,
      code: code ?? ApiException.extractCode(const {}, detail),
    );

void main() {
  setUp(() => L.code = 'uz');

  group('transport and status classes', () {
    test('network / timeout / auth / 422 / 5xx get fixed messages', () {
      L.code = 'ru';
      expect(userMessage(ApiException(0, 'x', kind: ApiErrorKind.network)), startsWith('Нет связи с сервером'));
      expect(userMessage(ApiException(0, 'x', kind: ApiErrorKind.timeout)), startsWith('Сервер не ответил вовремя'));
      expect(userMessage(ex(401, 'Token yaroqsiz')), 'Сессия истекла — войдите снова');
      expect(userMessage(ex(422, [{'msg': 'Field required'}])), startsWith('Данные заполнены неверно'));
      expect(userMessage(ex(500, 'Traceback (most recent call last) ...')), startsWith('Временный сбой на сервере'));
      expect(userMessage(ex(502, "AI o'qishda xato: timeout")), startsWith('Временный сбой'));
    });

    test('raw dart transport exceptions are connectivity messages', () {
      expect(userMessage(const SocketException('refused')), startsWith('Server bilan aloqa yo‘q'));
      expect(userMessage(http.ClientException('x')), startsWith('Server bilan aloqa yo‘q'));
      expect(userMessage(TimeoutException('t')), startsWith('Server o‘z vaqtida'));
      expect(isConnectivityError(const SocketException('x')), isTrue);
      expect(isConnectivityError(ex(409, 'x')), isFalse);
      expect(userMessage(StateError('bug')), 'Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.');
    });

    // B4 asked for this: a platform capability the device/browser does not have
    // (no share sheet, no download, no biometric) is NOT "an unexpected error" —
    // it is a fact about the device, and the adapter already carries the l10n
    // key. Showing the generic message here hid a truth the operator can act on.
    test('PlatformUnavailable shows its OWN localized text, not the generic one', () {
      const e = PlatformUnavailable(PlatformUnavailable.kShare);
      expect(userMessage(e), 'Ulashib bo‘lmadi');
      expect(userMessage(e), isNot('Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.'));
      L.code = 'ru';
      expect(userMessage(e), 'Не удалось поделиться');
      L.code = 'ky';
      expect(userMessage(e), 'Бөлүшүү мүмкүн болбоду');
      L.code = 'uz';
      // The plugin's own words never reach the operator.
      expect(userMessage(const PlatformUnavailable(PlatformUnavailable.kShare,
          cause: 'MissingPluginException(No implementation found)')),
          'Ulashib bo‘lmadi');
    });
  });

  group('codes', () {
    test('every LOT_* shape code of the 5G contract has a message in ru and ky', () {
      const codes = [
        'LOT_LINES_REQUIRED', 'LOT_LINES_FORBIDDEN', 'LOT_QTY_SUM_MISMATCH', 'LOT_QTY_PRECISION',
        'LOT_EXPIRY_REQUIRED', 'LOT_EXPIRY_FORBIDDEN', 'LOT_EXPIRED', 'LOT_TZ_NOT_CONFIRMED',
        'LOT_SELECTION_INVALID', 'LOT_INSUFFICIENT_REMAINING', 'LOT_COUNT_SUM_MISMATCH',
        'TRANSFER_TRACKED_UNSUPPORTED', 'PERMISSION_DENIED', 'LOT_INVARIANT_BROKEN',
        'LOT_CORRECTION_NOT_TRACKED', 'LOT_CORRECTION_CONSUMED', 'LOT_CORRECTION_EXCEEDS_REMAINING',
        'LOT_CORRECTION_SHORTFALL_OPEN', 'LOT_CORRECTION_CASH_UNPOSTABLE', 'LOT_CORRECTION_REPLAY_CONFLICT',
        'LOT_CORRECTION_DOC_LOCKED', 'PRINT_ORIGINAL_EXISTS', 'PRINT_JOB_BUSY', 'RECEIPT_SCOPE_COMPANY_FORBIDDEN',
        'INSUFFICIENT_CASH', 'NEGATIVE_APPROVAL_REQUIRED', 'ACCOUNT_ARCHIVED',
        'CASH_OP_WRITE_FAILED', 'IDEMPOTENCY_KEY_REUSED', 'OPEN_SHIFT_REQUIRED',
      ];
      for (final lang in ['ru', 'ky']) {
        L.code = lang;
        for (final c in codes) {
          final m = codeMessage(c);
          expect(m, isNotNull, reason: c);
          expect(RegExp('[А-Яа-яЁёҢңӨөҮү]').hasMatch(m!), isTrue, reason: '$lang $c -> $m');
        }
      }
    });

    test('an unknown lot text with a stable header code shows the code message', () {
      L.code = 'ru';
      final e = ex(400, 'yangi server matni, lug‘atda yo‘q', code: 'LOT_QTY_SUM_MISMATCH');
      expect(userMessage(e), 'Сумма партий не равна количеству строки.');
    });

    test('cash prefix code wins over its technical text', () {
      L.code = 'ky';
      final e = ex(400, "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: 'debt_payment': T0'dan keyin naqd manbai SHART");
      expect(userMessage(e), startsWith('Накталай амал үчүн акча булагын'));
      L.code = 'uz';
      expect(userMessage(e), startsWith('Naqd amal uchun pul manbaini'));
    });

    test('cash posting dict detail', () {
      L.code = 'ru';
      final e = ex(409, {'error': 'NEGATIVE_APPROVAL_REQUIRED', 'message': 'manfiy'});
      expect(userMessage(e), 'Операция уводит кассу в минус — нужно подтверждение администратора.');
    });

    test('replay conflict code wins (client must rotate uuid)', () {
      final e = ex(409, "Bu client_uuid BOSHQA tuzatish so'rovida ishlatilgan — takror emas. Yangi so'rov uchun yangi client_uuid bering.",
          code: 'LOT_CORRECTION_REPLAY_CONFLICT');
      expect(userMessage(e), 'Bu so‘rov avval boshqa mazmun bilan yuborilgan. Hujjatni yangilab, tuzatishni qayta yuboring.');
    });
  });

  group('known server texts', () {
    test('static text', () {
      L.code = 'ru';
      expect(userMessage(ex(400, 'Ochiq smena yo\'q — avval kassada smena oching')),
          'Нет открытой смены — сначала откройте смену на кассе');
      expect(userMessage(ex(403, "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.")),
          startsWith('Магазин временно приостановлен'));
    });

    test('dynamic receiving text keeps the product name (with a quote and a colon)', () {
      L.code = 'ru';
      const t = "'Sut: olma' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY. Miqdor taxmin qilinmaydi.";
      expect(userMessage(ex(400, t)), '«Sut: olma» учитывается по партиям — укажите партии в каждой строке прихода.');
      L.code = 'ky';
      expect(userMessage(ex(400, t)), '«Sut: olma» партия боюнча эсептелет — ар бир кириш сабына партияларды киргизиңиз.');
    });

    test('count error prefixed with a product name (containing ": ") is split correctly', () {
      L.code = 'ru';
      const t = "Kefir: 1%: Partiyalar yig'indisi (3.000) e'lon qilingan umumiy sanoqqa (5.000) mos emas. "
          "Sanalmagan partiyalar TEGILMAYDI (1.000); farqni tizim TAQSIMLAMAYDI.";
      expect(userMessage(ex(400, t)),
          'Kefir: 1%: Сумма партий (3.000) не равна общему пересчёту (5.000). Непересчитанные партии не меняются (1.000).');
    });

    test('lot keys (UUIDs) are dropped from known texts', () {
      const t = 'Partiya topilmadi: 3f2a9c1e-8d7b-4c2a-9e1f-0a1b2c3d4e5f';
      expect(userMessage(ex(400, t)), 'Partiya topilmadi');
      expect(userMessage(ex(400, 'Sut: $t')), 'Sut: Partiya topilmadi');
    });

    test('403 permission text lists localized permission names', () {
      L.code = 'ru';
      expect(userMessage(ex(403, "Ruxsat yo'q: xaridlar.edit")), 'Нет прав на это действие: Закупки и приёмка');
      expect(userMessage(ex(403, "Ruxsat yo'q: sotuvlar.view / hisobot.view")),
          'Нет прав на это действие: Просмотр продаж / Отчёты');
      expect(userMessage(ex(403, "Ruxsat yo'q: bu filial sizga biriktirilmagan")), 'Этот филиал вам не назначен');
      expect(userMessage(ex(403, 'something else')), 'У вас нет прав на это действие.');
    });

    test('expired lot text with dates', () {
      L.code = 'ky';
      const t = "'Qatiq': 2026-09-01 muddati bugungi biznes sanasi (2026-09-19) dan OLDIN — muddati o'tgan tovar qabul qilinmaydi.";
      expect(userMessage(ex(400, t)),
          '«Qatiq»: 2026-09-01 мөөнөтү бүгүнкү иш күнүнөн (2026-09-19) мурун — мөөнөтү өткөн товар кабыл алынбайт.');
    });

    test('uzc transliterates the Uzbek message, keeps data raw', () {
      L.code = 'uzc';
      expect(userMessage(ex(400, "Qarz yo'q")), 'Қарз йўқ');
      expect(userMessage(ex(400, "Yetarli qoldiq yo'q: Sut (qoldiq: 2)")), 'Етарли қолдиқ йўқ: Sut (қолдиқ: 2)');
    });
  });

  group('unknown texts', () {
    test('shown after stripping UUIDs', () {
      final m = userMessage(ex(400, "Hujjat 9b1f2c3d-1111-4222-8333-444455556666 yopilgan: qayta oching"));
      expect(m, 'Hujjat yopilgan: qayta oching');
    });

    test('internal failures become a generic message', () {
      for (final t in [
        'Traceback (most recent call last): File x',
        '(psycopg.errors.UniqueViolation) duplicate key',
        '[SQL: INSERT INTO ...]',
        'sqlalchemy.exc.IntegrityError',
        'stock_invariant violated for 5',
      ]) {
        expect(userMessage(ex(400, t)), 'Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.', reason: t);
      }
    });

    test('dict detail without a known code never shows JSON', () {
      final m = userMessage(ex(400, {'foo': 'bar'}));
      expect(m, isNot(contains('{')));
      expect(m, 'Xatolik (400). Qayta urinib ko‘ring.');
    });

    test('missing route on an older server', () {
      L.code = 'ru';
      expect(userMessage(ex(404, 'Not Found')), 'Сервер не распознал запрос — возможно, сервер нужно обновить.');
    });
  });

  group('serverText (reasons sent as data)', () {
    test('bare code, prefixed code and known text', () {
      L.code = 'ru';
      expect(serverText('CASH_LEDGER_UNAVAILABLE'), startsWith('Учёт наличных временно недоступен'));
      expect(serverText('TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER: x'), startsWith('Операция не соответствует кассе'));
      expect(serverText("Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul uchun."),
          'Эта приёмка не создала партий — исправление только для приёмок с партиями.');
      expect(serverText(''), '');
    });
  });

  group('Phase 5G integration: server codes and texts', () {
    // Static copy of every stable code the server can send to the mobile app.
    // Dart tests cannot read the server tree reliably, so this list is kept by
    // hand; sources (update together):
    //   apps/server/app/core/error_codes.py                (X-Error-Code, all)
    //   apps/server/app/services/receipt/errors.py         (RECEIPT_*/PRINT_*)
    //   apps/server/app/services/cash/cutover_guard.py     ("CODE: text" prefix, custody reason)
    //   apps/server/app/services/cash/errors.py CashError  (dict detail {error, message})
    const serverCodes = [
      // error_codes.py
      'LOT_INVARIANT_BROKEN', 'LOT_RETURN_CAPS_VIOLATED', 'LOT_COST_BASIS_INCONSISTENT', 'LOT_RETURN_PRE_ACTIVATION',
      'LOT_RESOLVE_INVARIANT_BROKEN', 'LOT_SCHEMA_NOT_READY',
      'LOT_CORRECTION_NOT_TRACKED', 'LOT_CORRECTION_CONSUMED', 'LOT_CORRECTION_EXCEEDS_REMAINING',
      'LOT_CORRECTION_SHORTFALL_OPEN', 'LOT_CORRECTION_CASH_UNPOSTABLE', 'LOT_CORRECTION_REPLAY_CONFLICT',
      'LOT_CORRECTION_DOC_LOCKED',
      'LOT_LINES_REQUIRED', 'LOT_LINES_FORBIDDEN', 'LOT_QTY_SUM_MISMATCH', 'LOT_QTY_PRECISION',
      'LOT_EXPIRY_REQUIRED', 'LOT_EXPIRY_FORBIDDEN', 'LOT_EXPIRED', 'LOT_TZ_NOT_CONFIRMED',
      'LOT_SELECTION_INVALID', 'LOT_INSUFFICIENT_REMAINING', 'LOT_COUNT_SUM_MISMATCH',
      'TRANSFER_TRACKED_UNSUPPORTED', 'PERMISSION_DENIED', 'OPEN_SHIFT_REQUIRED',
      // receipt/errors.py
      'RECEIPT_SCOPE_COMPANY_FORBIDDEN', 'PRINT_ORIGINAL_EXISTS', 'PRINT_JOB_FINAL', 'PRINT_JOB_INVALID',
      'PRINT_JOB_BUSY',
      // cash/cutover_guard.py
      'LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER', 'TILL_REQUIRED_AFTER_CUTOVER', 'TILL_INVALID_AFTER_CUTOVER',
      'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER', 'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER',
      'CASH_CUSTODY_ACCOUNT_INVALID', 'CASH_LEDGER_UNAVAILABLE', 'CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY',
      // cash/errors.py CashError
      'ACCOUNT_NOT_FOUND', 'ACCOUNT_ARCHIVED', 'TENANT_MISMATCH', 'CURRENCY_MISMATCH', 'INVALID_TIMESTAMP',
      'SHIFT_NOT_FOUND', 'SHIFT_NOT_BELONG_TO_ACCOUNT', 'SHIFT_NOT_OPEN', 'INSUFFICIENT_CASH',
      'NEGATIVE_APPROVAL_REQUIRED', 'DUPLICATE_REQUEST', 'DUPLICATE_BUSINESS_LEG', 'ALREADY_REVERSED',
      'INVALID_REVERSAL', 'INVALID_TRANSFER', 'INVALID_ACCOUNT_TYPE', 'UNAUTHORIZED_OPERATION', 'INVALID_INPUT',
    ];

    test('every server code has its own message, translated to ru and ky', () {
      final missing = [for (final c in serverCodes) if (codeMessage(c) == null) c];
      expect(missing, isEmpty, reason: 'map in lib/errors.dart codeMessages');
      for (final lang in ['ru', 'ky']) {
        L.code = lang;
        for (final c in serverCodes) {
          expect(RegExp('[А-Яа-яЁёҢңӨөҮү]').hasMatch(codeMessage(c)!), isTrue, reason: '$lang $c -> ${codeMessage(c)}');
        }
      }
    });

    test('the MB header codes win over an unknown text on the 5G write paths', () {
      L.code = 'ru';
      const cases = {
        'LOT_LINES_REQUIRED': 400,
        'LOT_EXPIRED': 400,
        'LOT_TZ_NOT_CONFIRMED': 409,
        'TRANSFER_TRACKED_UNSUPPORTED': 409,
        'OPEN_SHIFT_REQUIRED': 400,
      };
      cases.forEach((code, status) {
        final e = ex(status, 'yangi server matni', code: code);
        expect(userMessage(e), codeMessage(code), reason: code);
      });
      final denied = ex(403, 'yangi matn', code: 'PERMISSION_DENIED');
      expect(userMessage(denied), 'У вас нет прав на это действие.');
    });

    test('cash posting codes with technical text show the code message', () {
      L.code = 'ky';
      expect(userMessage(ex(400, {'error': 'INVALID_TRANSFER', 'message': 'from == to'})),
          'Акча которуу туура эмес — булак жана алуучу эсепти текшериңиз.');
      L.code = 'uz';
      expect(userMessage(ex(400, {'error': 'TENANT_MISMATCH', 'message': 'Hisob boshqa tenantniki'})),
          'Naqd hisob bu do‘konga tegishli emas — ro‘yxatni yangilang.');
    });

    test('"<field> kiritilishi kerak": field label translated when known, kept otherwise', () {
      L.code = 'ru';
      expect(userMessage(ex(400, 'Mijoz nomi kiritilishi kerak')), 'Необходимо заполнить: Имя клиента');
      expect(userMessage(ex(400, 'Yetkazib beruvchi nomi kiritilishi kerak')),
          'Необходимо заполнить: Название поставщика');
      expect(userMessage(ex(400, 'Nomi kiritilishi kerak')), 'Необходимо заполнить: Название');
      expect(userMessage(ex(400, 'Yangi maydon kiritilishi kerak')), 'Необходимо заполнить: Yangi maydon');
      // A row prefix is kept as-is, the rest translated.
      expect(userMessage(ex(400, '3-qator: Mahsulot nomi kiritilishi kerak')),
          '3-qator: Необходимо заполнить: Название товара');
      L.code = 'ky';
      expect(userMessage(ex(400, 'Kategoriya nomi kiritilishi kerak')), 'Толтуруу керек: Категориянын аталышы');
      L.code = 'uz';
      expect(userMessage(ex(400, 'Mijoz nomi kiritilishi kerak')), 'Mijoz nomi kiritilishi kerak');
    });

    test('phone format and empty query texts', () {
      L.code = 'ru';
      expect(userMessage(ex(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")),
          'Неверный номер телефона. Например: +996 700 123 456');
      expect(userMessage(ex(400, "Bo'sh so'rov")), 'Пустой запрос — введите текст для поиска.');
      L.code = 'ky';
      expect(userMessage(ex(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")),
          'Телефон номери туура эмес. Мисалы: +996 700 123 456');
      expect(userMessage(ex(400, "Bo'sh so'rov")), 'Суроо бош — издөө текстин киргизиңиз.');
      L.code = 'uz';
      expect(userMessage(ex(400, "Telefon raqami noto'g'ri. Masalan: +996 700 123 456")),
          'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456');
    });

    test('password policy texts are localized, never raw; the minimum comes from the server text', () {
      L.code = 'ru';
      expect(userMessage(ex(400, 'Parol qabul qilinmadi: juda qisqa (7 belgi, kamida 12 kerak)')),
          'Пароль слишком короткий — нужно не менее 12 символов.');
      expect(userMessage(ex(400, 'Parol qabul qilinmadi: juda qisqa (9 belgi, kamida 14 kerak)')),
          'Пароль слишком короткий — нужно не менее 14 символов.');
      expect(
          userMessage(ex(400,
              "Parol qabul qilinmadi: juda uzun (80 bayt, ko'pi bilan 72) — bcrypt undan ortig'ini hisobga olmaydi")),
          'Пароль слишком длинный.');
      expect(userMessage(ex(400, "Parol qabul qilinmadi: juda ko'p uchraydigan qiymat")),
          'Пароль слишком простой — выберите другой.');
      expect(userMessage(ex(400, "Parol qabul qilinmadi: ma'lum arzon qiymatdan boshlanadi")),
          'Пароль слишком простой — выберите другой.');
      expect(userMessage(ex(400, 'Parol qabul qilinmadi: entropiyasi past (3 xil belgi) — takrorlanuvchi naqsh')),
          'В пароле слишком много повторяющихся символов — выберите другой.');
      expect(userMessage(ex(400, 'Parol qabul qilinmadi: bir xil belgi ketma-ket takrorlanadi')),
          'В пароле слишком много повторяющихся символов — выберите другой.');
      expect(userMessage(ex(400, "Parol qabul qilinmadi: bo'sh")), 'Введите новый пароль.');
      expect(userMessage(ex(400, 'Parol qabul qilinmadi: yangi sabab')), 'Пароль не принят — выберите другой.');
    });

    test('own-password endpoint: wrong current credential (401) is not "session expired"', () {
      L.code = 'ru';
      expect(userMessage(ex(401, "Joriy kredensial noto'g'ri")), 'Неверный текущий пароль (или PIN).');
      expect(userMessage(ex(401, 'Token yaroqsiz')), 'Сессия истекла — войдите снова');
      expect(userMessage(ex(403, "Parolni o'zingiz o'rnata olmaysiz — administratorga murojaat qiling")),
          'Вы не можете сами установить пароль — обратитесь к администратору.');
      expect(userMessage(ex(400, "Parol o'rnatish uchun avval telefon (login) qo'shilishi kerak")),
          'Чтобы установить пароль, сначала нужно добавить телефон (логин).');
      expect(userMessage(ex(409, 'Bu telefon boshqa akkauntda band')), 'Этот номер телефона занят другим аккаунтом.');
    });
  });
}
