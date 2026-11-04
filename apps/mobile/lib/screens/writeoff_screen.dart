import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/stock_api.dart';
import '../draft_guard.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/branch_chip.dart';
import 'barcode_scan_screen.dart';
import 'inventory_screen.dart';
import 'product_detail_screen.dart' show LotCard;

/// Hisobdan chiqarish (write-off) from the session's CURRENT branch.
///
/// * untracked product — one quantity (≤ branch stock, 3 decimals);
/// * lot-tracked product — quantity PER LOT from `GET /lots/products/{id}?branch_id=`
///   (open lots, FEFO order, expired lots visible and highlighted), each ≤ its
///   remaining; the write sends `qty = Σ lots` and the SAME `branch_id` the lots
///   were read from. The system never guesses the lot (desktop `Hisobdan`);
/// * reason `expired|damaged|lost|other[: note]` (desktop codes);
/// * success only after a 2xx; a network failure keeps the same `client_uuid`
///   for the retry; `duplicate` is shown as "already saved earlier".
///
/// ⚠️  No cash effect: a write-off is a stock loss, not a money operation.
class WriteoffScreen extends StatefulWidget {
  /// Creates the screen, optionally pre-selecting [initialProduct] (and
  /// highlighting [initialLotId]).
  const WriteoffScreen({super.key, this.initialProduct, this.initialLotId, this.scannerBuilder});

  /// Product to start with (e.g. from the product card).
  final StockProduct? initialProduct;

  /// Lot to highlight (e.g. from an expiry notification).
  final String? initialLotId;

  /// Camera override (tests).
  final ScannerViewBuilder? scannerBuilder;

  @override
  State<WriteoffScreen> createState() => _WriteoffScreenState();
}

const Set<String> _reloadCodes = {
  'LOT_LINES_REQUIRED',
  'LOT_LINES_FORBIDDEN',
  'LOT_SELECTION_INVALID',
  'LOT_INSUFFICIENT_REMAINING',
  'LOT_QTY_SUM_MISMATCH',
};

class _WriteoffScreenState extends State<WriteoffScreen>
    with DraftGuard<WriteoffScreen> {
  StockProduct? _product;
  String? _branchId; // branch the product/lots were loaded for (sent with the write)
  bool _resolving = false;
  Object? _resolveError;
  ProductLots? _lots;
  bool _tracked = false;
  int _stockMilli = 0;
  int _resolveSeq = 0;
  String? _branchNotice;

  final _qty = TextEditingController();
  final Map<String, TextEditingController> _lotQty = {};
  String _reason = 'expired';
  final _note = TextEditingController();
  bool _showErrors = false;

  final _uuid = DraftUuid();
  bool _busy = false;
  Object? _submitError;

  /// The last attempt's OUTCOME IS UNKNOWN (no answer, timeout, 5xx, a stale
  /// 2xx): the write may already be committed. The draft is frozen — every
  /// input is disabled — so a retry re-sends the IDENTICAL body under the SAME
  /// `client_uuid` and the server's dedup can recognise it.
  ///
  /// STICKY: only a 2xx or an explicit, confirmed discard clears it. A later
  /// DECIDED refusal (e.g. a 400 «Yetarli qoldiq yo'q» produced by the first
  /// attempt's own commit) does NOT prove that first attempt was refused, so
  /// releasing the lock there would let the operator lower the quantity and
  /// write the same stock a second time under a fresh key.
  bool _unknown = false;

  /// The body and key of the attempt whose outcome is unknown. The retry
  /// re-sends EXACTLY this — never a body recomputed from a re-read stock
  /// level, which would silently change the request (and its fingerprint).
  Map<String, dynamic>? _frozenBody;
  String? _frozenUuid;

  /// Stash key — captured ONCE in [initState] (R6.8 P0-1).
  ///
  /// ⚠️  NEVER read the branch dynamically here. A 401 nulls
  ///     `Session.currentBranchId` BEFORE the `authEpoch` listener runs, so a
  ///     dynamic key would stash under `writeoff.-` and look for
  ///     `writeoff.b1` after the re-login — the draft, and with it the only
  ///     copy of the idempotency key, would be silently unreachable. The same
  ///     mistake was measured on `cash_ops_screen` in R6.6.
  late String _draftKeyValue;

  /// A restorable draft was waiting when the screen opened.
  bool _draftOffered = false;

  /// The server says this looks like a write-off recorded moments ago under a
  /// DIFFERENT key, and is asking the operator to decide. Set only by a
  /// [kWriteoffDuplicateSuspected] reply; cleared by a confirmed resend or an
  /// explicit discard.
  bool _dupSuspected = false;

  /// Reconciliation is running (`GET /inventory/writeoff/status`).
  bool _checking = false;

  /// What the status check found, as an operator sentence.
  String? _checkNotice;

  Session get _s => Session.instance;

  /// The submit body is PINNED (`_frozenBody`) — therefore every input MUST be
  /// locked.
  ///
  /// ⚠️  WHY ONE GETTER AND NOT TWO FLAGS (R6.8, adversarial review). The
  ///     original R6.8 change keyed every input lock on `_unknown` alone and
  ///     added `_dupSuspected` as a SECOND frozen state without extending
  ///     them. The result was the exact failure this phase exists to prevent:
  ///     the operator could change product, branch, quantity, lots and reason
  ///     while `_frozenBody`/`_frozenUuid` stayed pinned, the confirmation
  ///     dialog was rebuilt from the LIVE inputs, and `_submit` then sent the
  ///     OLD body — with `confirm_duplicate: true` explicitly waiving the
  ///     server's twin gate. The operator confirmed one write-off and a
  ///     different one was written.
  ///
  ///     The invariant is now stated once: FROZEN BODY ⇒ FROZEN FORM.
  bool get _frozen => _unknown || _dupSuspected;

  @override
  String get draftKey => _draftKeyValue;

  /// Everything needed to resume the SAME operation — above all the frozen
  /// `client_uuid`, which is the only barrier against writing the stock off
  /// twice.
  ///
  /// ⚠️  Returns `null` for an empty form, otherwise the operator would be
  ///     offered an empty "restore".
  @override
  Object? captureDraft() {
    final p = _product;
    if (p == null) return null;
    final st = _state();
    final hasInput = _unknown ||
        st.totalMilli > 0 ||
        _qty.text.trim().isNotEmpty ||
        _note.text.trim().isNotEmpty;
    if (!hasInput) return null;
    //  Barmoq AYNI shu tanadan hisoblanadi (`_submit` ham shunday qiladi,
    //  :338) — tiklangandan keyin `forDraft` AYNI kalitni qaytaradi.
    final body = _frozenBody ??
        writeoffBody(
          productId: p.id,
          qtyMilli: st.totalMilli,
          reason: writeoffReasonText(_reason, _note.text),
          branchId: _branchId,
          lots: _tracked ? st.picks : const [],
        );
    return <String, Object?>{
      'product': p,
      'branchId': _branchId,
      'tracked': _tracked,
      'stockMilli': _stockMilli,
      'qty': _qty.text,
      'lotQty': {for (final e in _lotQty.entries) e.key: e.value.text},
      'reason': _reason,
      'note': _note.text,
      'unknown': _unknown,
      'dupSuspected': _dupSuspected,
      'frozenBody': _frozenBody,
      'uuid': _frozenUuid ?? _uuid.forDraft(body),
      'fp': jsonEncode(body),
    };
  }

  @override
  void restoreDraft(Object draft) {
    final d = draft as Map<String, Object?>;
    final lotQty = (d['lotQty'] as Map?)?.cast<String, String>() ?? const {};
    setState(() {
      _product = d['product'] as StockProduct?;
      _branchId = d['branchId'] as String?;
      _tracked = d['tracked'] == true;
      _stockMilli = (d['stockMilli'] as int?) ?? 0;
      _qty.text = (d['qty'] as String?) ?? '';
      for (final e in lotQty.entries) {
        (_lotQty[e.key] ??= TextEditingController()).text = e.value;
      }
      _reason = (d['reason'] as String?) ?? 'expired';
      _note.text = (d['note'] as String?) ?? '';
      // ⚠️  `_unknown` ham tiklanadi: natija NOMA'LUM bo'lgan amal MUZLAGAN
      //     holatda qolishi kerak, aks holda operator uni ikkinchi marta
      //     yuborardi — aynan P0 ning o'zi.
      _unknown = d['unknown'] == true;
      _dupSuspected = d['dupSuspected'] == true;
      _frozenBody = (d['frozenBody'] as Map?)?.cast<String, dynamic>();
      _submitError = null;
      _checkNotice = null;
      _showErrors = false;
    });
    // ⚠️  KALIT TIKLANISHI SHART — aks holda ayni chiqarish serverda IKKINCHI
    //     yozuv bo'ladi (`DraftUuid.restore` barmoqni ham tiklaydi).
    final uuid = d['uuid'] as String?;
    if (uuid != null) {
      _uuid.restore(uuid, d['fp']);
      if (_frozen) _frozenUuid = uuid;
    }
    //  ⚠️  PARTIYALAR QAYTA O'QILADI (R6.8, raqib tekshiruvi topilmasi).
    //      Qoralama `_lots` ni SAQLAMAYDI (u serverning joriy holati, qoralama
    //      emas). Ekran menyudan `initialProduct` SIZ ochilsa `initState`
    //      `_resolve` ni umuman chaqirmaydi, va muzlagan holatda mahsulot
    //      tanlagich ham O'CHIRILGAN — ya'ni `_lots` abadiy `null` qolardi.
    //      Oqibati: kuzatuvli mahsulotda `_state()` «nolots» ga tushib
    //      «Jami: 0» ko'rsatardi, partiya qatorlari yo'qolardi va ekran
    //      operatorga «partiyalarni ko'rish ruxsati kerak» degan YOLG'ON
    //      banner berardi — holbuki `_frozenBody` haqiqiy miqdorni yozadi.
    //
    //      `_resolve` BU YERDA YARAMAYDI: u `_branchId` ni JORIY sessiya
    //      filialiga yozib qo'yadi va partiyalarni ham O'SHA filialdan
    //      o'qiydi. Muzlagan qoralama esa O'Z filialini yozadi — ikkisi
    //      farq qilsa ekran qaytarib bo'lmaydigan yozuvni NOTO'G'RI filial
    //      bilan belgilardi. Shu bois alohida, torroq yuklovchi.
    unawaited(_loadDraftLots());
  }

  /// Loads the lots of a RESTORED draft — for the DRAFT's branch, not the
  /// session's, and without touching any input or `_branchId`.
  ///
  /// ⚠️  Display only. The body that will be sent lives in `_frozenBody` and
  ///     is never recomputed from what this loads.
  Future<void> _loadDraftLots() async {
    final p = _product;
    final branch = _branchId;
    if (p == null || branch == null || !Perm.allows('lots.product')) return;
    final seq = ++_resolveSeq;
    setState(() => _resolving = true);
    try {
      final lots = await StockApi.productLots(p.id, branchId: branch);
      if (!mounted || seq != _resolveSeq) return;
      setState(() {
        _lots = lots;
        _tracked = lots.trackLots;
        _stockMilli = lots.inventoryMilli;
        _resolving = false;
      });
    } catch (e) {
      if (!mounted || seq != _resolveSeq) return;
      //  ⚠️  XATO QULFNI OCHMAYDI va tanani O'ZGARTIRMAYDI — bu faqat
      //      ko'rsatish uchun o'qish.
      setState(() {
        _resolveError = e;
        _resolving = false;
      });
    }
  }

  /// Name of the branch THIS draft writes off. While the outcome is unknown
  /// the draft keeps the branch it was loaded for, so the session's current
  /// branch may already be another one — showing that one would label an
  /// irreversible write with the wrong branch.
  String get _draftBranchName {
    final id = _branchId;
    if (id != null) {
      for (final b in _s.branches) {
        if (b.id == id) return b.name;
      }
    }
    return _s.currentBranch?.name ?? '—';
  }

  @override
  void initState() {
    //  ⚠️  KALIT `super.initState()` DAN OLDIN. `DraftGuard.initState`
    //      `authEpoch` listener'ini o'rnatadi va u `draftKey` ni o'qiydi;
    //      kalit hali yo'q bo'lsa `LateInitializationError` chiqardi.
    _draftKeyValue = 'writeoff.${Session.instance.currentBranchId ?? '-'}';
    super.initState();
    _draftOffered = hasStashedDraft;
    _s.addListener(_onSession);
    final p = widget.initialProduct;
    //  ⚠️  Qoralama taklif qilinayotganda ham mahsulot YUKLANADI, lekin
    //      `keepInputs: true` bilan: aks holda ekran bo'sh turardi (qoldiq va
    //      partiyalar o'qilmagan) va `_resolve` tiklangan kiritmani bosib
    //      ketardi. `keepInputs` ikkala muammoni ham yopadi — mahsulot,
    //      qoldiq va partiyalar yuklanadi, kiritma esa TEGILMAYDI.
    if (p != null) _resolve(p, keepInputs: _draftOffered);
  }

  @override
  void dispose() {
    _s.removeListener(_onSession);
    _qty.dispose();
    _note.dispose();
    for (final c in _lotQty.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _onSession() {
    if (!mounted) return;
    // Natija noma'lum ekan, filial chipi qulflangan — bu yerga kelinmaydi.
    if (_product != null && !_frozen && _s.currentBranchId != _branchId) {
      // Boshqa filial — eski filial qoldig'i/partiyalari bilan yozib bo'lmaydi.
      setState(() {
        _product = null;
        _lots = null;
        _clearInputs();
        _submitError = null;
        _branchNotice = tr('Filial almashtirildi — mahsulotni qayta tanlang.');
      });
      return;
    }
    setState(() {});
  }

  void _clearInputs() {
    _qty.clear();
    for (final c in _lotQty.values) {
      c.clear();
    }
    _note.clear();
    _showErrors = false;
  }

  /// Loads the AUTHORITATIVE tracking flag, branch stock and lots of [p] in
  /// the current branch. Keeps typed lot quantities of lots that still exist.
  Future<void> _resolve(StockProduct p, {int? scaleMilli, bool keepInputs = false}) async {
    final seq = ++_resolveSeq;
    final branch = _s.currentBranchId;
    final canLots = Perm.allows('lots.product');
    setState(() {
      if (!keepInputs || _product?.id != p.id) {
        _clearInputs();
        _lotQty.clear();
      }
      _product = p;
      _branchId = branch;
      _branchNotice = null;
      _lots = null;
      _tracked = p.trackLots;
      _stockMilli = p.stockMilli;
      _resolveError = null;
      _resolving = canLots;
      if (scaleMilli != null && scaleMilli > 0 && !p.trackLots) _qty.text = milliToInput(scaleMilli);
    });
    if (!canLots) return;
    try {
      final lots = await StockApi.productLots(p.id, branchId: branch);
      if (!mounted || seq != _resolveSeq) return;
      setState(() {
        _lots = lots;
        _tracked = lots.trackLots;
        _stockMilli = lots.inventoryMilli;
        _resolving = false;
        final live = {for (final l in lots.usableLots) l.id};
        _lotQty.removeWhere((k, c) {
          if (live.contains(k)) return false;
          c.dispose();
          return true;
        });
      });
    } catch (e) {
      if (!mounted || seq != _resolveSeq) return;
      setState(() {
        _resolveError = e;
        _resolving = false;
      });
    }
  }

  Future<void> _pick() async {
    final hit = await showStockProductPicker(context,
        branchId: _s.currentBranchId, title: tr('Qaysi mahsulot?'), scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) {
      _submitError = null;
      await _resolve(hit.product, scaleMilli: hit.scaleMilli);
    }
  }

  Future<void> _scan() async {
    final hit = await scanStockProduct(context, branchId: _s.currentBranchId, scannerBuilder: widget.scannerBuilder);
    if (hit != null && mounted) {
      _submitError = null;
      await _resolve(hit.product, scaleMilli: hit.scaleMilli);
    }
  }

  TextEditingController _lotCtl(String id) => _lotQty.putIfAbsent(id, TextEditingController.new);

  // ── Validation (UX only — the server decides) ────────────────────────────

  _WoState _state() {
    final p = _product;
    if (p == null) return const _WoState(reason: 'pick');
    if (_resolving) return const _WoState(reason: 'loading');
    if (_resolveError != null) return const _WoState(reason: 'resolve');
    if (!_tracked) {
      final r = parseQty(_qty.text);
      String? err;
      if (!r.ok) {
        err = qtyErrorText(r.error!);
      } else if (r.value! > _stockMilli) {
        err = trArgs('Qoldiqdan ko‘p (qoldiq: {q})', {'q': qtyUnit(_stockMilli, p.unit)});
      }
      return _WoState(totalMilli: r.value ?? 0, qtyError: err, reason: err == null ? null : 'qty');
    }
    final lots = _lots;
    if (lots == null) return const _WoState(reason: 'nolots');
    final picks = <LotPick>[];
    final errs = <String, String>{};
    var costMilliCents = 0;
    for (final l in lots.usableLots) {
      final t = _lotQty[l.id]?.text ?? '';
      if (t.trim().isEmpty) continue;
      final r = parseQty(t, allowZero: true);
      if (!r.ok) {
        errs[l.id] = qtyErrorText(r.error!);
      } else if (r.value! > l.remainingMilli) {
        errs[l.id] = trArgs('Partiya qoldig‘idan ko‘p ({q})', {'q': qtyUnit(l.remainingMilli, p.unit)});
      } else if (r.value! > 0) {
        picks.add(LotPick(l.id, r.value!));
        costMilliCents += r.value! * l.unitCostCents;
      }
    }
    final total = sumMilli(picks.map((x) => x.milli));
    String? reason;
    if (errs.isNotEmpty) {
      reason = 'lots';
    } else if (picks.isEmpty) {
      reason = 'nopick';
    } else if (picks.length > kMaxLotsPerItem) {
      reason = 'toomany';
    }
    return _WoState(
      totalMilli: total,
      picks: picks,
      lotErrors: errs,
      costCents: (costMilliCents + 500) ~/ 1000,
      reason: reason,
    );
  }

  String? _disabledReason(_WoState st) {
    if (!Perm.allows('stock.writeoff')) return Perm.reason('stock.writeoff');
    // MUZLAGAN QORALAMA: aynan o'sha tana o'sha kalit bilan qayta yuboriladi.
    // Serverdan qayta o'qilgan qoldiq (birinchi urinish o'tib ketgan bo'lsa u
    // kamaygan bo'ladi) «Qayta yuborish»ni to'smasin — aks holda operatorga
    // faqat «Bekor qilish» qolardi, ya'ni ikki marta yozish xavfi.
    if (_frozen) return null;
    switch (st.reason) {
      case null:
        return null;
      case 'pick':
        return tr('Mahsulotni tanlang');
      case 'loading':
        return tr('Yuklanmoqda…');
      case 'resolve':
        return tr('Mahsulot ma’lumotini yuklab bo‘lmadi — qayta urinib ko‘ring.');
      case 'nolots':
        return '${tr('Partiyali mahsulotni chiqarish uchun partiyalarni ko‘rish ruxsati kerak.')} ${Perm.reason('lots.product')}';
      case 'nopick':
        return tr('Qaysi partiyadan qancha chiqarilishini kiriting');
      case 'toomany':
        return trArgs('Bir amalda ko‘pi bilan {n} ta partiya', {'n': kMaxLotsPerItem});
      case 'qty':
        return st.qtyError;
      default:
        return tr('Partiya miqdorlaridagi xatolarni tuzating');
    }
  }

  // ── Submit ───────────────────────────────────────────────────────────────

  /// Sends the write-off.
  ///
  /// [confirmDuplicate] is passed ONLY when the operator answered the server's
  /// «so'nggi o'xshash chiqarish» question with «yes, this really is a second,
  /// separate operation». It is never set automatically: an automatic retry is
  /// exactly what writes the stock off twice.
  Future<void> _submit({bool confirmDuplicate = false}) async {
    final st = _state();
    if (!_frozen && (st.reason != null || !Perm.allows('stock.writeoff'))) {
      setState(() => _showErrors = true);
      return;
    }
    final p = _product!;
    final body = _frozenBody ??
        writeoffBody(
          productId: p.id,
          qtyMilli: st.totalMilli,
          reason: writeoffReasonText(_reason, _note.text),
          branchId: _branchId,
          lots: _tracked ? st.picks : const [],
        );
    final ok = await confirmDestructive(
      context,
      title: confirmDuplicate
          ? tr('Takroriy chiqarishni tasdiqlang')
          : tr('Hisobdan chiqarishni tasdiqlang'),
      message: confirmDuplicate
          ? tr('Shu filialda AYNI chiqarish yaqinda allaqachon yozilgan. Davom etsangiz IKKINCHI yozuv qilinadi va qoldiq yana kamayadi.')
          : tr('Tovar qoldiqdan chiqariladi. Bu amalni qaytarib bo‘lmaydi.'),
      confirmLabel: confirmDuplicate
          ? tr('Ha, ikkinchi marta chiqarish')
          : tr('Hisobdan chiqarish'),
        //  ⚠️  TAFSILOT AYNAN YUBORILADIGAN TANADAN OLINADI (R6.8, raqib
        //      tekshiruvi topilmasi). Ilgari u JONLI holatdan qurilardi, tana
        //      esa muzlagan bo'lishi mumkin edi — operator bir amalni
        //      tasdiqlab, serverga BOSHQASI ketardi. Endi `_frozenBody`
        //      bo'lsa dialog ham o'sha tanani ko'rsatadi: tasdiqlangan narsa
        //      yuborilgan narsaga TENG.
        details: _confirmDetails(body, p),
    );
    if (!ok || !mounted) return;
    final uuid = _frozenUuid ?? _uuid.forDraft(body);
    setState(() {
      _busy = true;
      _submitError = null;
    });
    try {
      final res =
          await StockApi.writeoff(body, clientUuid: uuid, confirmDuplicate: confirmDuplicate);
      if (!mounted) return;
      _uuid.rotate();
      setState(() {
        _busy = false;
        _unknown = false;
        _dupSuspected = false;
        _checkNotice = null;
        _frozenBody = null;
        _frozenUuid = null;
        _submitError = null;
        _clearInputs();
        if (!_tracked && res.newQtyMilli != null) _stockMilli = res.newQtyMilli!;
      });
      if (_tracked || res.duplicate) unawaited(_resolve(p));
      final again = await _showResult(p, st, res);
      if (!mounted) return;
      if (again != true) Navigator.of(context).maybePop();
    } catch (e) {
      if (!mounted) return;
      final unknown = stockOutcomeUnknown(e);
      final code = e is ApiException ? (e.code ?? '') : '';
      setState(() {
        _busy = false;
        _submitError = e;
        // Javob kelmadi / 5xx / eskirgan 2xx — amal yozilgan BO'LISHI MUMKIN:
        // qoralama muzlaydi. YOPISHQOQ: keyingi aniq rad etish oldingi
        // (hali yakunlanmagan) urinish yozilmasligini ISBOTLAMAYDI.
        _unknown = _unknown || unknown;
        if (_unknown) {
          _frozenBody ??= body;
          _frozenUuid ??= uuid;
        }
        // ⚠️  SERVER QAROR QILDI: hech narsa YOZILMADI, lekin shu filialda
        //     yaqinda AYNI chiqarish bor. Bu `_unknown` EMAS — natija ANIQ.
        //     Tana va kalit MUZLATILADI: tasdiqlangan qayta yuborish AYNAN
        //     shu amalni yuborishi kerak, aks holda operator tasdiqlagan
        //     narsa bilan yuborilgan narsa ajralib ketardi.
        if (code == kWriteoffDuplicateSuspected) {
          _dupSuspected = true;
          _frozenBody ??= body;
          _frozenUuid ??= uuid;
        }
        // ⚠️  KALIT BAND: hech narsa yozilmagan, lekin bu kalit BOSHQA amalga
        //     tegishli. Yangi kalit kerak — muzlatish YARAMAYDI, aks holda
        //     ekran abadiy 409 oladi.
        if (code == kIdempotencyKeyReused) {
          _dupSuspected = false;
          _unknown = false;
          _frozenBody = null;
          _frozenUuid = null;
          _uuid.rotate();
        }
      });
      // Qoldiq/partiyalar qayta o'qiladi (operator haqiqiy holatni ko'rsin);
      // muzlagan tana bunga BOG'LIQ emas — u `_frozenBody` da saqlanadi.
      if (!unknown && e is ApiException) {
        if (_reloadCodes.contains(code) || e.message.startsWith("Yetarli qoldiq yo'q")) {
          unawaited(_resolve(p, keepInputs: true));
        }
      }
    }
  }

  /// The confirmation dialog's lines, derived from the BODY THAT WILL BE SENT.
  ///
  /// ⚠️  Never from the live inputs. When the body is frozen
  ///     (`_frozenBody` — an unknown outcome, or the server's twin gate) the
  ///     form may still hold something else, and the whole point of this
  ///     dialog is that the operator sees the irreversible write they are
  ///     authorising.
  ///
  /// ⚠️  Lot labels fall back to the raw lot id when `_lots` has not been
  ///     loaded, and the cost line is omitted rather than guessed: a wrong
  ///     number here is worse than a missing one.
  List<String> _confirmDetails(Map<String, dynamic> body, StockProduct p) {
    final qtyMilli = milliFromNum(body['qty']);
    final reason = '${body['reason'] ?? ''}';
    final lots = (body['lots'] as List?) ?? const [];
    final lotById = {for (final l in _lots?.lots ?? const <LotRow>[]) l.id: l};
    final live = _frozenBody == null;
    return [
      '${p.name} — ${qtyUnit(qtyMilli, p.unit)}',
      trArgs('Filial: {name}', {'name': _draftBranchName}),
      //  Muzlagan tanada sabab ALLAQACHON matn (`<kod>: <izoh>`) — uni
      //  qayta talqin qilmasdan ko'rsatamiz.
      trArgs('Sabab: {r}', {'r': live ? _reasonLabel(_reason) : reason}),
      for (final l in lots)
        if (l is Map)
          '${lotById['${l['stock_batch_id']}'] == null ? '${l['stock_batch_id']}' : lotLabel(lotById['${l['stock_batch_id']}']!)}: '
              '${formatMilli(milliFromNum(l['qty']))}',
      if (live && _tracked && _state().costCents > 0)
        trArgs('Tannarx: {c}', {'c': formatCents(_state().costCents)}),
    ];
  }

  /// Asks the SERVER whether the frozen `client_uuid` was recorded, so an
  /// UNKNOWN outcome becomes a KNOWN one without writing anything (R6.8 P0-1).
  ///
  /// ⚠️  READ-ONLY. Guessing is forbidden: a wrong guess either writes the
  ///     stock off twice or drops the operation. If the server says the key is
  ///     there, the lock is released and the form cleared — the work is done.
  ///     If it is NOT there, the screen stays frozen and says so: the operator
  ///     resends the SAME body under the SAME key.
  Future<void> _reconcile() async {
    final p = _product;
    final uuid = _frozenUuid;
    if (p == null || uuid == null || _checking || _busy) return;
    setState(() {
      _checking = true;
      _checkNotice = null;
    });
    try {
      final st = await StockApi.writeoffStatus(clientUuid: uuid, productId: p.id);
      if (!mounted) return;
      if (st.recorded) {
        _uuid.rotate();
        setState(() {
          _checking = false;
          _unknown = false;
          _dupSuspected = false;
          _frozenBody = null;
          _frozenUuid = null;
          _submitError = null;
          _clearInputs();
          _checkNotice = tr('Tekshirildi: amal serverda YOZILGAN. Qayta yuborish kerak emas.');
        });
        unawaited(_resolve(p, keepInputs: true));
        return;
      }
      setState(() {
        _checking = false;
        _checkNotice =
            tr('Tekshirildi: amal serverda YOZILMAGAN — AYNAN shu amalni qayta yuboring.');
      });
    } catch (e) {
      if (!mounted) return;
      // ⚠️  TEKSHIRUV YIQILSA QULF SAQLANADI. «Tekshirib bo'lmadi» —
      //     «yozilmagan» DEGANI EMAS; qulfni bo'shatish operatorni ikkinchi
      //     yozuvga yo'llardi.
      setState(() {
        _checking = false;
        _checkNotice = tr('Tekshirib bo‘lmadi — holat hamon noma’lum. Qulf saqlanadi.');
      });
    }
  }

  /// Explicitly abandons an attempt whose outcome is unknown: only NOW may the
  /// idempotency key rotate. The form is emptied and the branch stock / lots
  /// are re-read, so the operator sees what the server really holds.
  Future<void> _discard() async {
    final ok = await confirmDestructive(
      context,
      title: tr('Urinishni bekor qilish'),
      message: tr(
          'Amal serverda yozilgan BO‘LISHI MUMKIN. Bekor qilsangiz, forma tozalanadi va qoldiq serverdan qayta o‘qiladi — natijani tekshiring.'),
      confirmLabel: tr('Bekor qilish'),
      cancelLabel: tr('Qolish'),
    );
    if (!ok || !mounted) return;
    _uuid.rotate();
    setState(() {
      _unknown = false;
      _dupSuspected = false;
      _checkNotice = null;
      _frozenBody = null;
      _frozenUuid = null;
      _submitError = null;
      _clearInputs();
    });
    final p = _product;
    if (p != null) unawaited(_resolve(p, keepInputs: true));
  }

  /// Leaving with an unknown outcome loses the «Qayta yuborish» button (a new
  /// screen would mint a new key), so it is confirmed.
  Future<void> _leaveUnknown() async {
    final leave = await confirmDestructive(
      context,
      title: tr('Natija noma’lum'),
      message: tr(
          'Amal serverda yozilgan bo‘lishi mumkin. Chiqsangiz, «Qayta yuborish» tugmasi yo‘qoladi — qoldiqni mahsulot kartasida tekshiring.'),
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Qolish'),
    );
    if (!leave || !mounted) return;
    _uuid.rotate();
    setState(() {
      _unknown = false;
      _dupSuspected = false;
      _frozenBody = null;
      _frozenUuid = null;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop();
    });
  }

  Future<bool?> _showResult(StockProduct p, _WoState st, WriteoffResult res) => showAppSheet<bool>(
        context,
        title: res.duplicate ? tr('Bu amal avval saqlangan') : tr('Hisobdan chiqarildi ✓'),
        builder: (ctx) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (res.duplicate)
            ErrorBanner(
              key: const Key('wo-duplicate'),
              severity: BannerSeverity.warning,
              message: tr('Server bu so‘rovni avval qabul qilgan — qoldiq QAYTA kamaytirilmadi. Qoldiqni tekshiring.'),
            )
          else ...[
            Text('${res.product ?? p.name} — ${qtyUnit(st.totalMilli, p.unit)}',
                key: const Key('wo-done'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            if (res.newQtyMilli != null) ...[
              const SizedBox(height: 6),
              Text(trArgs('Yangi qoldiq: {q}', {'q': qtyUnit(res.newQtyMilli!, p.unit)}),
                  style: TextStyle(color: AppColors.text2)),
            ],
            if (res.costTotalCents != null) ...[
              const SizedBox(height: 6),
              Text(trArgs('Hisobdan chiqarilgan tannarx: {c}', {'c': formatCents(res.costTotalCents!)}),
                  key: const Key('wo-cost'), style: TextStyle(color: AppColors.text2)),
            ],
          ],
          const SizedBox(height: 16),
          SizedBox(
            height: kPrimaryButtonHeight,
            child: ElevatedButton(
              key: const Key('wo-again'),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(tr('Yana chiqarish')),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: kMinTouch,
            child: TextButton(
              key: const Key('wo-close'),
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(tr('Tayyor')),
            ),
          ),
        ]),
      );

  String _reasonLabel(String code) => switch (code) {
        'expired' => tr('Muddati o‘tgan'),
        'damaged' => tr('Shikastlangan'),
        'lost' => tr('Yo‘qolgan'),
        _ => tr('Boshqa sabab'),
      };

  // ── UI ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final allowed = Perm.allows('stock.writeoff');
    final st = _state();
    final p = _product;
    final reason = _disabledReason(st);
    return PopScope(
      // `_busy` ham qulflaydi: so'rov yo'ldayligida chiqib ketilsa, javob
      // (va u bilan birga yagona `client_uuid`) jimgina yo'qoladi — amal
      // serverda yozilgan bo'lsa ham operator buni bilmaydi.
      canPop: !_busy && !_frozen,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop || _busy) return;
        await _leaveUnknown();
      },
      child: Scaffold(
      appBar: AppBar(title: Text(tr('Hisobdan chiqarish'))),
      body: Column(children: [
        const ConnectivityBanner(),
        Expanded(
          child: ListView(
            key: const Key('wo-list'),
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
            children: [
              if (_draftOffered)
                DraftRestoreCard(
                  restoreKey: const Key('wo-draft-restore'),
                  enabled: !_busy,
                  onRestore: () {
                    final d = claimStashedDraft();
                    if (d != null) restoreDraft(d);
                    setState(() => _draftOffered = false);
                  },
                ),
              Row(children: [
                Text(tr('Filial'), style: TextStyle(fontSize: 13, color: AppColors.muted)),
                const SizedBox(width: 4),
                Flexible(child: _frozen ? _lockedBranch() : const BranchChip()),
              ]),
              if (!allowed)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: ErrorBanner(
                      key: const Key('wo-denied'),
                      message: Perm.reason('stock.writeoff'),
                      severity: BannerSeverity.warning),
                ),
              if (_branchNotice != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: ErrorBanner(message: _branchNotice!, severity: BannerSeverity.info),
                ),
              StockSectionTitle(tr('Mahsulot')),
              _productBox(p),
              if (p != null) ..._details(p, st),
            ],
          ),
        ),
        if (_submitError != null)
          WriteErrorStrip(
            bannerKey: const Key('wo-error'),
            error: _submitError!,
            onDismiss: _frozen ? null : () => setState(() => _submitError = null),
          ),
        if (_busy)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: ErrorBanner(
              key: const Key('wo-inflight'),
              severity: BannerSeverity.info,
              message: tr('So‘rov yuborildi — javob kutilmoqda. Natija ma’lum bo‘lguncha bu ekrandan chiqmang.'),
            ),
          ),
        if (_unknown)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: ErrorBanner(
              key: const Key('wo-unknown'),
              severity: BannerSeverity.warning,
              message: [
                // ⚠️  R6.8: SARLAVHA ANIQ AYTADI — holat noma'lum va solishtirish
                //     KERAK. «Tahrirlash bloklandi» o'z-o'zidan sababni
                //     aytmasdi, operator esa qulfni nosozlik deb o'qishi mumkin.
                tr('SOLISHTIRISH KERAK: amal serverda yozilgan bo‘lishi MUMKIN, natija noma’lum.'),
                tr('Tahrirlash vaqtincha bloklandi: AYNAN shu amalni qayta yuboring yoki «Bekor qilish» bilan yangi amal boshlang.'),
                // Qulflangan qoralama O'Z filialini yozadi — joriy filial
                // o'zgargan bo'lsa, buni aytib qo'yamiz.
                if (_branchId != null && _branchId != _s.currentBranchId)
                  trArgs('Bu amal «{name}» filialidan chiqariladi (joriy filial boshqa).', {'name': _draftBranchName}),
              ].join(' '),
              // ⚠️  SERVERDAN SO'RASH — TAXMIN O'RNIGA. Faqat o'qish, hech
              //     narsa yozilmaydi.
              onRetry: _frozenUuid == null || _checking || _busy ? null : _reconcile,
              retryLabel: tr('Serverda tekshirish'),
            ),
          ),
        if (_dupSuspected)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: ErrorBanner(
              key: const Key('wo-dup-suspected'),
              severity: BannerSeverity.warning,
              // ⚠️  BITTA LITERAL (bo'linmagan). `stock_l10n_test` matnni regex
              //     bilan oladi va qo'shni literallarni BIRLASHTIRMAYDI: ikkiga
              //     bo'lingan matnda tekshirgich birinchi bo'lagini, ish vaqti
              //     esa TO'LIQ satrni ko'rardi — tarjima jimgina tushib qolardi.
              message: tr('Shu filialda AYNI chiqarish yaqinda allaqachon yozilgan va hozir HECH NARSA yozilmadi. Avval mahsulot kartasidagi harakatlarni tekshiring. Agar bu HAQIQATAN ikkinchi, alohida amal bo‘lsa — «Tasdiqlab yuborish» bilan davom eting.'),
            ),
          ),
        if (_checkNotice != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 0),
            child: ErrorBanner(
              key: const Key('wo-check-notice'),
              severity: BannerSeverity.info,
              message: _checkNotice!,
              onDismiss: () => setState(() => _checkNotice = null),
            ),
          ),
        StickyActionBar(
          label: _dupSuspected
              ? tr('Tasdiqlab yuborish')
              : (_unknown ? tr('Qayta yuborish') : tr('Hisobdan chiqarish')),
          icon: _unknown || _dupSuspected ? Icons.refresh : Icons.remove_circle_outline,
          danger: true,
          busy: _busy || _checking,
          enabled: reason == null,
          disabledReason: reason,
          // ⚠️  `confirm_duplicate` FAQAT shu yo'ldan — operator bannerni
          //     ko'rib, tasdiq dialogidan o'tgandan KEYIN. Avtomatik qayta
          //     yuborish YO'Q.
          onPressed: () => _submit(confirmDuplicate: _dupSuspected),
          secondaryLabel: _unknown || _dupSuspected ? tr('Bekor qilish') : null,
          onSecondary: _discard,
          summary: p == null
              ? null
              : Text(
                  _tracked && st.costCents > 0
                      ? trArgs('Jami: {q} · tannarx {c}',
                          {'q': qtyUnit(st.totalMilli, p.unit), 'c': formatCents(st.costCents)})
                      : trArgs('Jami: {q}', {'q': qtyUnit(st.totalMilli, p.unit)}),
                  key: const Key('wo-summary'),
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                ),
        ),
      ]),
      ),
    );
  }

  Widget _lockedBranch() => ConstrainedBox(
        constraints: const BoxConstraints(minHeight: kMinTouch),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.lock_outline, size: 16, color: AppColors.muted),
          const SizedBox(width: 6),
          Flexible(
            child: Text(_draftBranchName,
                key: const Key('wo-branch-locked'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppColors.text2)),
          ),
        ]),
      );

  Widget _productBox(StockProduct? p) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (p != null)
        StockProductTile(
          key: const Key('wo-product'),
          product: StockProduct(
            id: p.id,
            name: p.name,
            unit: p.unit,
            stockMilli: _stockMilli,
            minMilli: p.minMilli,
            sellCents: p.sellCents,
            trackLots: _tracked,
            trackExpiry: _lots?.trackExpiry ?? p.trackExpiry,
            isActive: p.isActive,
            isWeighted: p.isWeighted,
          ),
          showPrice: false,
          onTap: _busy || _frozen ? null : _pick,
        ),
      Row(children: [
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: OutlinedButton.icon(
              key: const Key('wo-pick'),
              onPressed: _busy || _frozen ? null : _pick,
              icon: const Icon(Icons.search),
              label: Text(p == null ? tr('Mahsulot tanlash') : tr('Boshqa mahsulot')),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: SizedBox(
            height: kMinTouch,
            child: OutlinedButton.icon(
              key: const Key('wo-scan'),
              onPressed: _busy || _frozen ? null : _scan,
              icon: const Icon(Icons.qr_code_scanner),
              label: Text(tr('Skanerlash')),
            ),
          ),
        ),
      ]),
    ]);
  }

  List<Widget> _details(StockProduct p, _WoState st) {
    return [
      if (_resolving) const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
      if (_resolveError != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: ErrorBanner(error: _resolveError, onRetry: () => _resolve(p, keepInputs: true)),
        ),
      if (!_resolving && _resolveError == null) ...(_tracked ? _lotInputs(p, st) : _qtyInput(p, st)),
      if (!_resolving && _resolveError == null) ..._reasonInputs(),
    ];
  }

  List<Widget> _qtyInput(StockProduct p, _WoState st) => [
        StockSectionTitle(tr('Miqdor')),
        QtyField(
          key: const Key('wo-qty'),
          controller: _qty,
          enabled: !_frozen,
          label: tr('Chiqariladigan miqdor'),
          unit: p.unit,
          helperText: trArgs('Filial qoldig‘i: {q}', {'q': qtyUnit(_stockMilli, p.unit)}),
          errorText: (_showErrors || _qty.text.isNotEmpty) ? st.qtyError : null,
          onChanged: (_) => setState(() {}),
        ),
      ];

  List<Widget> _lotInputs(StockProduct p, _WoState st) {
    final lots = _lots;
    if (lots == null) {
      return [
        const SizedBox(height: 10),
        ErrorBanner(
          key: const Key('wo-lots-denied'),
          severity: BannerSeverity.warning,
          message: _disabledReason(const _WoState(reason: 'nolots')) ?? '',
        ),
      ];
    }
    final usable = lots.usableLots;
    return [
      StockSectionTitle(tr('Partiyalar')),
      Text(tr('Qaysi partiyadan qancha chiqarilayotganini kiriting. Tizim partiyani o‘zi tanlamaydi.'),
          style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
      const SizedBox(height: 8),
      if (usable.isEmpty)
        EmptyState(text: tr('Bu filialda ochiq partiya yo‘q'), icon: Icons.inventory_2_outlined)
      else
        for (final l in usable)
          LotCard(
            lot: l,
            unit: p.unit,
            businessDate: lots.businessDate,
            highlight: widget.initialLotId == l.id,
            child: QtyField(
              key: Key('wo-lot-qty-${l.id}'),
              controller: _lotCtl(l.id),
              enabled: !_frozen,
              allowZero: true,
              label: tr('Chiqariladi'),
              hint: '0',
              unit: p.unit,
              errorText: st.lotErrors[l.id],
              onChanged: (_) => setState(() {}),
            ),
          ),
      if (_showErrors && st.reason == 'nopick')
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(tr('Qaysi partiyadan qancha chiqarilishini kiriting'),
              style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
        ),
    ];
  }

  List<Widget> _reasonInputs() => [
        StockSectionTitle(tr('Sabab')),
        Wrap(spacing: 8, runSpacing: 4, children: [
          for (final r in kWriteoffReasons)
            ChoiceChip(
              key: Key('wo-reason-$r'),
              label: Text(_reasonLabel(r)),
              selected: _reason == r,
              onSelected: _frozen ? null : (_) => setState(() => _reason = r),
              materialTapTargetSize: MaterialTapTargetSize.padded,
              selectedColor: AppColors.dangerSoft,
              showCheckmark: false,
              side: BorderSide(color: _reason == r ? AppColors.danger : AppColors.border),
            ),
        ]),
        const SizedBox(height: 10),
        TextField(
          key: const Key('wo-note'),
          controller: _note,
          enabled: !_frozen,
          maxLength: 150,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(
            labelText: _reason == 'other' ? tr('Izoh (nima bo‘ldi?)') : tr('Izoh (ixtiyoriy)'),
            constraints: const BoxConstraints(minHeight: kMinTouch),
          ),
        ),
        Text(tr('Hisobdan chiqarish kassaga ta’sir qilmaydi — bu pul amali emas.'),
            style: TextStyle(fontSize: 12, color: AppColors.muted)),
      ];
}

class _WoState {
  const _WoState({
    this.totalMilli = 0,
    this.picks = const [],
    this.lotErrors = const {},
    this.qtyError,
    this.costCents = 0,
    this.reason,
  });

  final int totalMilli;
  final List<LotPick> picks;
  final Map<String, String> lotErrors;
  final String? qtyError;
  final int costCents;

  /// Why submitting is not possible (null = ready).
  final String? reason;
}
