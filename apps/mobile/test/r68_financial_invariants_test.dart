// R6.8 — MOLIYAVIY INVARIANTLAR (R6.7 xarakterizatsiya testlarining o'rni).
//
// ⚠️  BU FAYL `r67_financial_p0_test.dart` NI ALMASHTIRADI. U nuqsonni QOTIRIB
//     qo'ygan edi («writeoff DraftGuard ga ULANMAGAN», «filial darvozasi YO'Q»)
//     va tuzatish bilan birga 8 testdan 4-tasi YIQILDI — bu kutilgan edi va
//     har biriga «TUZATILGANDA YIQILADI» izohi qo'yilgan edi. Endi AYNI
//     invariantlar TESKARI tomondan qadab qo'yiladi: nuqson QAYTSA bu fayl
//     qizil bo'ladi.
//
// ⚠️  OLIB TASHLANMADI, AYLANTIRILDI. Hali ham to'g'ri bo'lgan to'rt dalil
//     (`PopScope` route o'chirilishini to'smaydi; server indeksi tana
//     barmog'ini qamramaydi; yozuv filiali `EmployeeBranch` dan olinadi;
//     mijoz `till_id` yubormaydi) o'z joyida qoldi.
//
// Manba matni bo'yicha tekshiriladigan dalillar ATAYLAB shunday: ular
// XULQ testlari bilan juftlashgan (`r68_writeoff_draft_test.dart`,
// `r68_forced_recovery_test.dart`, `apps/server/tests/test_r68_*.py`) va
// bu yerda faqat STRUKTURA qadab qo'yiladi — ya'ni tuzatish boshqa yo'l
// bilan «aylanib o'tilsa» ham sezilади.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String p) => File(p).readAsStringSync();

void main() {
  group('R6.8-P0-1. hisobdan chiqarish kaliti HIMOYALANGAN', () {
    test('writeoff_screen DraftGuard ga ULANGAN — himoyalangan ekranlar ro\'yxatida', () {
      final guarded = Directory('lib/screens')
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.dart'))
          .where((f) => f.readAsStringSync().contains('with DraftGuard'))
          .map((f) => f.uri.pathSegments.last)
          .toSet();

      expect(
          guarded,
          containsAll(<String>[
            // R6.5–R6.6 da ulangan beshta ekran.
            'correction_screen.dart',
            'receiving_item_editor_screen.dart',
            'inventarizatsiya_screen.dart',
            'cash_ops_screen.dart',
            'transfer_screen.dart',
            // R6.8 P0-1: hisobdan chiqarish — moliyaviy P0 ning o'zagi.
            'writeoff_screen.dart',
            // R6.8 P1: to'lov varaqasi (barqaror `partyId` qo'shilgandan keyin).
            'money_payment_sheet.dart',
          ]),
          reason: 'bu ro\'yxatdan chiqib ketgan ekran kalitini SESSIYA TUGASHIDA '
              'yo\'qotadi va ayni amal IKKINCHI marta yozilishi mumkin');
    });

    test('muzlagan kalit DraftVault ga TOPSHIRILADI', () {
      final src = _read('lib/screens/writeoff_screen.dart');
      expect(src, contains('String? _frozenUuid'), reason: 'muzlagan kalit maydoni');
      expect(src, contains(r'final uuid = _frozenUuid ?? _uuid.forDraft(body)'),
          reason: 'yuborishda ishlatiladigan yagona kalit manbai');
      // R6.8: kalit endi `captureDraft` orqali vault'ga chiqadi va
      // `restoreDraft` da `DraftUuid.restore` bilan QAYTADI.
      expect(src, contains('Object? captureDraft()'));
      expect(src, contains("'uuid': _frozenUuid ?? _uuid.forDraft(body)"),
          reason: 'qoralamada AYNAN muzlagan kalit saqlanadi');
      expect(src, contains('_uuid.restore(uuid, d[\'fp\'])'),
          reason: 'barmoq ham tiklanadi — aks holda `forDraft` YANGI kalit yasardi');
      expect(src, contains("_unknown = d['unknown'] == true"),
          reason: 'muzlagan holat ham tiklanadi: tiklangan ekran qulflangan qoladi');
    });

    test('`PopScope` route O\'CHIRILISHINI to\'smaydi — faqat pop so\'rovini', () {
      final src = _read('lib/screens/writeoff_screen.dart');
      expect(src, contains('return PopScope('));
      expect(src, contains('canPop: !_busy && !_unknown && !_dupSuspected'),
          reason: 'R6.8: server «takror» deganda ham chiqish TASDIQLANADI');
      // 401 ishlovchisi pop SO'RAMAYDI, route'ni o'chiradi — shuning uchun
      // `PopScope` yolg'iz himoya BO'LA OLMAYDI va `DraftGuard` kerak.
      expect(_read('lib/main.dart'), contains('(route) => false'));
    });

    test('server indeksi tana barmog\'ini QAMRAMAYDI — shu bois TASDIQ darvozasi bor', () {
      final inv = _read('../server/app/api/v1/inventory.py');
      expect(inv, contains('(client_uuid + product_id + type)'),
          reason: 'dedup doirasi serverning o\'z izohida');
      final initdb = _read('../server/app/initdb.py');
      expect(initdb, contains('ux_stockmov_client_prod_type'), reason: 'yagona UNIQUE indeks');
      expect(initdb.contains('ux_stockmov_natural'), isFalse,
          reason: 'tabiiy kalit bo\'yicha dedup ATAYLAB YO\'Q: ikkita haqiqiy, '
              'alohida chiqarish qonuniy bo\'lishi mumkin');
      // R6.8 P0-1: shu bois indeks O'RNIGA emas, YONIGA tasdiq darvozasi.
      expect(inv, contains('def _assert_no_recent_twin'));
      expect(inv, contains('WRITEOFF_DUPLICATE_SUSPECTED'));
      expect(inv, contains('confirm_duplicate: bool = False'),
          reason: 'darvoza DEDUP emas: operator tasdiqlasa ikkinchi yozuv BAJARILADI');
      expect(inv, contains('def _same_writeoff'),
          reason: 'ayni kalit BOSHQA mazmun bilan kelsa `duplicate: true` DEYILMAYDI');
      expect(inv, contains('IDEMPOTENCY_KEY_REUSED'));
      // Konkurrent takror 500 bermasligi: kuzatuvli yo'ldagi `flush` o'ralgan.
      expect(inv, contains('''        try:
            db.flush()
        except _IE:'''),
          reason: 'kuzatuvli yo\'lda INSERT `flush` da bo\'ladi — u o\'ralmasa '
              'bir vaqtдаги AYNI kalit tutilmagan IntegrityError -> 500 berardi');
    });

    test('NOMA\'LUM holat serverdan SO\'RALADI — taxmin qilinmaydi', () {
      final src = _read('lib/screens/writeoff_screen.dart');
      expect(src, contains('Future<void> _reconcile()'));
      expect(src, contains('StockApi.writeoffStatus('));
      final inv = _read('../server/app/api/v1/inventory.py');
      expect(inv, contains('/inventory/writeoff/status'));
      expect(inv, contains('require("ombor.view")'),
          reason: 'sof o\'qish marshruti — yozuv ruxsati talab qilinmaydi');
      // Obuna darvozasi fail-closed: yangi marshrut tasniflangan bo'lishi SHART.
      expect(_read('../server/app/core/subscription_routes.py'),
          contains('("GET", "/inventory/writeoff/status"): ALLOW_READ'));
    });
  });

  group('R6.8-P0-2. ochiq smenada filial o\'zgarishi TO\'SILGAN', () {
    test('ASIMMETRIYA YO\'Q: status, delete VA filial — hammasi to\'silgan', () {
      final src = _read('../server/app/api/v1/employees.py');
      final lines = src.split('\n');
      int lineOf(String needle) => lines.indexWhere((l) => l.contains(needle)) + 1;

      final statusGate =
          lineOf('if _new_status != EmployeeStatus.active and _has_open_shift');
      expect(statusGate, greaterThan(0), reason: 'status darvozasi');
      expect(src, contains('if _has_open_shift(db, e.id):'), reason: 'o\'chirish darvozasi');

      final branchSet = lineOf('if data.branch_id is not None:');
      expect(branchSet, greaterThan(0));
      // FILIAL bloki endi darvoza bilan boshlanadi.
      final block = lines
          .sublist(branchSet - 1, (branchSet + 8).clamp(0, lines.length))
          .join('\n');
      expect(block, contains('_assert_branch_change_allowed(db, e.id, data.branch_id)'),
          reason: 'R6.8 P0-2: darvoza `_set_branch` dan OLDIN');
      expect(block.indexOf('_assert_branch_change_allowed'),
          lessThan(block.indexOf('_set_branch(db, e.id, data.branch_id')),
          reason: 'tartib muhim: rad etish YOZUVDAN oldin bo\'lishi SHART');
    });

    test('darvoza xodim qatorini QULFLAYDI va smena ochish AYNI qulfni oladi', () {
      final emp = _read('../server/app/api/v1/employees.py');
      expect(emp, contains('def _assert_branch_change_allowed'));
      expect(emp, contains('.with_for_update(of=Employee).first()'),
          reason: 'poyga oynasi qulf bilan yopiladi');
      final sh = _read('../server/app/services/shifts.py');
      expect(sh, contains('db.query(_Emp.id).filter(_Emp.id == emp.id).with_for_update(of=_Emp)'),
          reason: 'IKKI TOMON ham AYNI qatorni qulflashi SHART — bir tomon yetmaydi');
      final i = sh.indexOf('with_for_update(of=_Emp)');
      final j = sh.indexOf('branch = _ab(emp, db)');
      expect(i, greaterThan(-1));
      expect(j, greaterThan(i), reason: 'qulf `actor_branch` O\'QILISHIDAN oldin');
      // Ustun so'rovi SHART: `db.query(Employee)` `role` ni eager yuklaydi va
      // Postgres outer join'ning nullable tomoniga `FOR UPDATE` ni RAD etadi.
      expect(emp, contains('db.query(Employee.id).filter(Employee.id == employee_id)'),
          reason: 'obyekt so\'rovi haqiqiy Postgres\'da FeatureNotSupported berardi');
    });

    test('AYNI filial o\'zgarish EMAS — idempotentlik saqlanadi', () {
      final emp = _read('../server/app/api/v1/employees.py');
      expect(emp, contains('def _current_branch_id'),
          reason: 'eski qiymat YOZUVDAN OLDIN o\'qilishi kerak');
      expect(emp, contains('if eski == yangi:\n        return'),
          reason: 'takroriy PATCH va boshqa maydon tahriri BUZILMASLIGI shart');
    });

    test('AUDIT izi filial o\'zgarishini ANIQ yozadi', () {
      final emp = _read('../server/app/api/v1/employees.py');
      expect(emp, contains('"branch_changed": _branch_changed'));
      expect(emp, contains('"branch_detached":'),
          reason: 'biriktiruvni OLIB TASHLASH `None` bo\'lib «tegilmadi» bilan '
              'birlashib ketmasligi kerak');
      expect(emp, contains('before={"branch": _branch_before}'));
    });

    test('yozuv filiali `EmployeeBranch` dan olinadi — mijoz yubormaydi', () {
      expect(_read('../server/app/core/deps.py'), contains('def actor_branch'));
      expect(_read('../server/app/services/sales.py'), contains('_ab(emp, db)'));
      final mobileSrc = Directory('lib')
          .listSync(recursive: true)
          .whereType<File>()
          .where((f) => f.path.endsWith('.dart'))
          .map((f) => f.readAsStringSync())
          .join('\n');
      expect(mobileSrc.contains("'till_id'"), isFalse,
          reason: 'klient kassa/filialni tanlamaydi — server hisoblaydi');
    });

    test('UI OGOHLANTIRADI (lekin himoya serverda)', () {
      final src = _read('lib/screens/employee_edit_screen.dart');
      expect(src, contains("if (_branchId != o.branchId) 'branch_id': _branchId"),
          reason: 'PATCH tanasiga filial tushadi');
      final pick = src.substring(src.indexOf('Future<void> _pickBranch'));
      expect(pick, contains('confirmDestructive'),
          reason: 'R6.8 P0-2: haqiqiy o\'zgarishda tasdiq');
      expect(pick, contains('ochiq smena'),
          reason: 'oqibat YUBORISHDAN OLDIN aytiladi');
      // Serverning yangi matni mobil lug'atda BOR (kirill/rus egasi texnik
      // lotin matn ko'rmasligi uchun).
      expect(src, contains('filialni almashtirib bo\'lmaydi'),
          reason: 'kEmployeeServerTexts da bo\'lishi SHART');
    });
  });

  group('R6.8-P1. idempotentlik kafolatining DOIRASI aytiladi', () {
    test('to\'rtta joyda ham shartsiz «ikki marta yozilmaydi» YO\'Q', () {
      final joylar = {
        'lib/screens/inventory_screen.dart': 'SHU ekrandan',
        'lib/screens/cash_ops_screen.dart': 'SHU ekrandan',
        'lib/screens/money_payment_sheet.dart': 'SHU oynadan',
        'lib/screens/receiving_submit_sheet.dart': 'SHU oynadan',
      };
      // ⚠️  FAQAT `tr(...)` LITERALLARI tekshiriladi, butun fayl EMAS: izohlarda
      //     eski shartsiz matn ATAYLAB keltirilgan (nega o'zgartirilganini
      //     tushuntirish uchun) va u yolg'on qizil berardi.
      final trLit = RegExp(r"tr\(\s*((?:'(?:[^'\\]|\\.)*'\s*)+)");
      final lit = RegExp(r"'((?:[^'\\]|\\.)*)'");
      joylar.forEach((f, doira) {
        final src = _read(f);
        final kafolatlar = [
          for (final m in trLit.allMatches(src))
            [for (final l in lit.allMatches(m[1]!)) l[1]!].join()
        ].where((t) => t.contains('ikki marta yozilmaydi')).toList();
        expect(kafolatlar, isNotEmpty, reason: '\$f: kafolat matni topilmadi');
        for (final k in kafolatlar) {
          expect(k, contains(doira),
              reason: '$f: kafolat SHARTSIZ qolgan — operator yangi ekrandan/oynadan '
                  'qayta yuborish ham xavfsiz deb o\'ylaydi, holbuki kalit '
                  'yo\'qolgan va server ikkinchi yozuvni qabul qiladi:\n  $k');
        }
      });
    });

    test('to\'lov varaqasi barqaror `partyId` OLADI', () {
      final src = _read('lib/screens/money_payment_sheet.dart');
      expect(src, contains('required String partyId'));
      expect(src, contains("_draftKeyValue = 'pay.\${widget.custodyOperation}.\${widget.partyId}'"),
          reason: 'doira amal TURINI ham o\'z ichiga oladi: ayni id mijoz ham, '
              'ta\'minotchi ham bo\'lishi mumkin — bu boshqa-boshqa ledger');
      for (final f in [
        'lib/screens/customer_profile_screen.dart',
        'lib/screens/supplier_detail_screen.dart'
      ]) {
        expect(_read(f), contains('partyId: p.id'),
            reason: '$f: KO\'RSATISH NOMI emas, server id uzatilishi SHART');
      }
    });

    test('majburiy tiklash yo\'llari qoralamani TASHLAMAYDI', () {
      final pin = _read('lib/screens/pin_screens.dart');
      expect(pin, contains('Future<void> _logout({required bool userChose})'));
      expect(pin, contains('await _logout(userChose: false)'), reason: '12 urinish — MAJBURIY');
      expect(pin, contains('await _logout(userChose: true)'), reason: '«Chiqish» — ANIQ');
      expect(pin.substring(0, pin.indexOf('DraftVault.evictAll()')),
          contains('if (userChose) {'));
      expect(_read('lib/screens/lock_recovery_screen.dart').contains('DraftVault.evictAll()'),
          isFalse, reason: 'bu ekranni foydalanuvchi TANLAMAYDI');
      // ANIQ chiqish yo'llari AVVALGIDEK tashlaydi.
      for (final f in ['lib/screens/settings_screen.dart', 'lib/screens/shell.dart']) {
        final src = _read(f);
        expect(src, contains('DraftVault.evictAll()'), reason: f);
        expect(src.indexOf('DraftVault.evictAll()'),
            greaterThan(src.indexOf('await Api.logout()')), reason: f);
      }
    });

    test('sessiya tugashi FILIAL O\'ZGARISHI deb talqin qilinmaydi', () {
      for (final f in [
        'lib/screens/inventarizatsiya_screen.dart',
        'lib/screens/transfer_screen.dart'
      ]) {
        final src = _read(f);
        final i = src.indexOf('void _onSession()');
        expect(i, greaterThan(-1), reason: f);
        final body = src.substring(i, i + 1400);
        expect(body, contains('if (!Api.loggedIn) return;'), reason: f);
        expect(body.indexOf('if (!Api.loggedIn) return;'),
            lessThan(body.indexOf('final now = _s.currentBranchId;')),
            reason: '$f: darvoza filial solishtiruvidan OLDIN bo\'lishi SHART — '
                'aks holda `_items` tozalanadi va `captureDraft()` null qaytaradi');
      }
    });
  });
}
