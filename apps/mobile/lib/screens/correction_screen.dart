/// Receiving correction / cancel with cash custody (Phase 5D + 5E) — the
/// mobile port of the desktop `KirimTuzatish` (`packages/shared/src/screens/
/// Purchases.tsx`). Contract: `apps/server/app/services/RECEIVING_CORRECTION.md`.
///
/// ⚠️  THIS IS NOT A LINE EDIT. Purchase lines are never rewritten: the
///     operator REVERSES a quantity out of a lot the receiving created and,
///     if needed, declares a NEW lot in its place (immutable events). A full
///     reversal without replacement that brings the total to zero cancels the
///     document — there is no separate cancel endpoint.
///
/// ⚠️  THE SERVER DECIDES. Which lot's identity may still be corrected
///     (`correctable`), which line is blocked (open shortfall), which cash
///     account is used (`cash_custody`) — this screen only renders those
///     decisions and pre-validates for UX; the writer validates everything
///     again.
///
/// Public entry point: [CorrectionScreen.open] (pops a [CorrectionResult] on a
/// 2xx, `null` when the operator leaves).
library;

import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api/correction_api.dart';
import '../errors.dart';
import '../format.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../qty.dart';
import '../session.dart';
import '../theme.dart';
import '../ui/ui.dart';
import '../widgets/custody_block.dart';
import '../widgets/lot_editor.dart';

/// Permission-matrix action of the correction writer.
const String kCorrectAction = 'receiving.correct';

/// Localized unit label (`dona` -> `шт.`).
String unitLabel(String code) => switch (code) {
      'dona' => tr('dona'),
      'kg' => tr('kg'),
      'litr' => tr('litr'),
      'upak' => tr('upak'),
      _ => code,
    };

/// The write may or may not have been applied: no HTTP answer, a timeout, or
/// a 5xx / non-JSON answer (a gateway 502/504 can hide a committed write).
/// Such a failure is retried with the SAME `client_uuid`.
///
/// It is ALSO every answer the core discarded because the session epoch moved
/// on ([Api.kStaleSession]) that was itself a 2xx or a 5xx: a concurrent 401
/// (the owner resets the employee's password) ends the session while a write
/// authenticated BEFORE the revocation is still in flight. Such a 2xx means
/// the correction IS written — calling it a refusal would send the manager
/// back with a fresh key and write a SECOND immutable correction. Only a stale
/// 4xx is a real decision.
///
/// Twin of `stockOutcomeUnknown` (M2) and `moneyOutcomeUnknown` (M4) — the
/// three must agree (`test/correction_logic_test.dart` pins that) until the
/// core grows `ApiException.isOutcomeUnknown`.
bool outcomeUnknown(Object? e) =>
    isConnectivityError(e) ||
    (e is ApiException &&
        (e.kind == ApiErrorKind.server ||
            (e.code == Api.kStaleSession && (e.status >= 500 || (e.status >= 200 && e.status < 300)))));

/// Signed money: `+12 000 so'm` / `−5 000 so'm` / `0 so'm`.
String signedCents(int cents) {
  if (cents > 0) return '+${formatCents(cents)}';
  if (cents < 0) return '−${formatCents(-cents)}';
  return formatCents(0);
}

// ════════════════════════════════════════════════════════════════════════════
//  DRAFT — pure logic (no widgets), unit-tested in test/correction_logic_test.dart
// ════════════════════════════════════════════════════════════════════════════

/// One correctable line: a purchase line and the lots shown under it.
class CorrLine {
  CorrLine._(this.item, this.lots, this.blocked);

  /// The document line (`purchase_item_id` = [PurchaseLine.id]).
  final PurchaseLine item;

  /// Lots shown (and reversible) under THIS line — see [buildCorrLines].
  final List<ReceivedLot> lots;

  /// Server block reason (raw) — the line may not be corrected; `null` = open.
  final String? blocked;

  /// A replacement is being declared.
  bool repOn = false;

  /// Replacement quantity text.
  String repQty = '';

  /// Replacement unit cost text (the LINE cost of the new lots).
  String repCost = '';

  /// Replacement lots (created on the first [CorrectionDraft.setRepOn]).
  LotEditorController? rep;

  /// `purchase_item_id`.
  String get itemId => item.id;

  /// Product name.
  String get name => item.name;

  /// Product tracks expiry.
  bool get trackExpiry => item.trackExpiry;
}

/// Correction lines of [d].
///
/// ⚠️  ONE LOT — ONCE. The server links lots to lines by PRODUCT (the
///     receiving does not store `purchase_item_id` on a lot), so a product on
///     two lines returns the SAME lots under both. Sending a quantity for the
///     same lot twice is rejected for the whole request — the lot is shown
///     only under the FIRST line (desktop `corrLines`). Lines without lots are
///     skipped.
List<CorrLine> buildCorrLines(PurchaseDoc d) {
  final seen = <String>{};
  final out = <CorrLine>[];
  for (final it in d.lines) {
    final lots = [for (final l in it.lots) if (seen.add(l.id)) l];
    if (lots.isEmpty) continue;
    out.add(CorrLine._(it, lots, it.correctable == false ? (it.blockedReason ?? '') : null));
  }
  return out;
}

/// What [CorrectionDraft.check] found first.
enum CorrIssueKind {
  /// Reason shorter than 3 or longer than 300 characters.
  reason,

  /// A reversal quantity is not a valid 3-decimal number.
  revInvalid,

  /// A reversal quantity is above the lot's remaining quantity.
  overRemaining,

  /// A quantity was entered on a line the server blocks.
  blockedLine,

  /// A replacement on a line whose reversed lot already moved.
  replaceLocked,

  /// Replacement quantity missing / invalid.
  repQty,

  /// Replacement lots invalid (Σ, expiry, decimals, count).
  repLots,

  /// Replacement unit cost missing or not above zero.
  repCost,

  /// Nothing would be sent.
  nothing,
}

/// A validation problem with the localized message and the field to focus.
@immutable
class CorrIssue {
  /// Creates an issue.
  const CorrIssue(this.kind, this.message, {this.itemId, this.lotId});

  /// Kind.
  final CorrIssueKind kind;

  /// Localized operator message.
  final String message;

  /// Line of the issue (`purchase_item_id`).
  final String? itemId;

  /// Lot of the issue.
  final String? lotId;

  @override
  String toString() => 'CorrIssue($kind, $itemId, $lotId)';
}

int _roundOnce(BigInt raw) {
  // raw = Σ milli × cents  ->  cents, ROUND_HALF_UP away from zero, ONCE.
  final neg = raw.isNegative;
  final r = (raw.abs() + BigInt.from(500)) ~/ BigInt.from(1000);
  return (neg ? -r : r).toInt();
}

/// The operator's correction draft for one document.
///
/// Mirrors the desktop `KirimTuzatish` state: reversal quantities by LOT id,
/// replacement drafts by LINE, reason, chosen cash account, the idempotency
/// key ([uuid]) and the fingerprint of the last SENT draft ([sentKey]).
class CorrectionDraft extends ChangeNotifier {
  /// Creates a draft for [doc]; [uuid] defaults to a fresh v4.
  CorrectionDraft(PurchaseDoc doc, {String? uuid})
      : _doc = doc,
        _lines = buildCorrLines(doc),
        uuid = uuid ?? Api.newUuid();

  PurchaseDoc _doc;
  List<CorrLine> _lines;

  /// Reversal quantity text by lot id.
  final Map<String, String> rev = {};

  /// Correction reason (3..300 after trimming).
  String reason = '';

  /// Chosen cash account (OPERATOR_MUST_CHOOSE only).
  String? cashAccountId;

  /// Idempotency key (`client_uuid`). STABLE for the whole screen: a retry of
  /// a request whose answer was lost MUST reuse it. Rotated only after
  /// `LOT_CORRECTION_REPLAY_CONFLICT` ([onReplayConflict]).
  String uuid;

  /// [draftKey] of the last request that was SENT (answer received or not).
  String? sentKey;

  /// The document currently shown.
  PurchaseDoc get doc => _doc;

  /// Correction lines.
  List<CorrLine> get lines => _lines;

  /// Business date of the DOCUMENT branch (`YYYY-MM-DD`) or null (the server
  /// then judges replacement expiry dates alone).
  String? get businessDate {
    final own = _doc.businessDate;
    if (own != null) return own;
    final b = _doc.branchId;
    return b == null ? null : Session.instance.businessDate(b);
  }

  /// Replaces the document after a reload, KEEPING what the operator typed:
  /// reversal quantities by lot id, replacement drafts by line. A line the
  /// server now blocks loses its entries (its inputs are locked).
  void setDoc(PurchaseDoc next) {
    final old = {for (final l in _lines) l.itemId: l};
    final fresh = buildCorrLines(next);
    _doc = next;
    for (final l in fresh) {
      final o = old.remove(l.itemId);
      if (o == null || l.blocked != null) {
        if (o != null) old[l.itemId] = o; // disposed below
        continue;
      }
      l
        ..repOn = o.repOn
        ..repQty = o.repQty
        ..repCost = o.repCost
        ..rep = o.rep;
      o.rep = null;
      l.rep
        ?..trackExpiry = l.trackExpiry
        ..businessDate = businessDate;
    }
    for (final o in old.values) {
      o.rep?.removeListener(notifyListeners);
      o.rep?.dispose();
      o.rep = null;
    }
    final live = {
      for (final l in fresh)
        if (l.blocked == null)
          for (final lt in l.lots) lt.id
    };
    rev.removeWhere((k, _) => !live.contains(k));
    _lines = fresh;
    notifyListeners();
  }

  // ── Edits ────────────────────────────────────────────────────────────────

  /// Sets the reason text.
  void setReason(String v) {
    if (v == reason) return;
    reason = v;
    notifyListeners();
  }

  /// Sets the reversal quantity text of lot [lotId].
  void setRev(String lotId, String text) {
    if ((rev[lotId] ?? '') == text) return;
    if (text.isEmpty) {
      rev.remove(lotId);
    } else {
      rev[lotId] = text;
    }
    notifyListeners();
  }

  /// Chooses the cash account (null clears).
  void setCash(String? id) {
    if (id == cashAccountId) return;
    cashAccountId = id;
    notifyListeners();
  }

  /// Turns the replacement of [l] on/off. Turning it on is refused on a
  /// blocked line or when a reversed lot already moved; turning it off always
  /// works (the operator must be able to leave that state). The first time,
  /// the replacement quantity starts at what is being reversed and one lot
  /// row follows it (desktop `toggleRep` / `lotsAuto`).
  void setRepOn(CorrLine l, bool on) {
    if (!on) {
      if (!l.repOn) return;
      l.repOn = false;
      notifyListeners();
      return;
    }
    if (l.repOn || l.blocked != null || touched(l)) return;
    l.repOn = true;
    if (l.rep == null) {
      final q = revSumMilli(l);
      l.repQty = q > 0 ? milliToInput(q) : '';
      l.rep = LotEditorController(
        trackExpiry: l.trackExpiry,
        businessDate: businessDate,
        targetMilli: q > 0 ? q : null,
      )..addListener(notifyListeners);
    }
    notifyListeners();
  }

  /// Sets the replacement quantity; a single untouched lot row follows it.
  void setRepQty(CorrLine l, String text) {
    if (l.repQty == text) return;
    l.repQty = text;
    l.rep?.targetMilli = parseQty(text).value;
    notifyListeners();
  }

  /// Sets the replacement unit cost text.
  void setRepCost(CorrLine l, String text) {
    if (l.repCost == text) return;
    l.repCost = text;
    notifyListeners();
  }

  /// Reverses the whole remaining quantity of every lot on every OPEN line and
  /// switches every replacement off (desktop `reverseAll`). Blocked lines are
  /// left alone: their inputs are locked and the server would reject them.
  void reverseAll() {
    rev.clear();
    for (final l in _lines) {
      l.repOn = false;
      if (l.blocked != null) continue;
      for (final lt in l.lots) {
        if (lt.remainingMilli > 0) rev[lt.id] = milliToInput(lt.remainingMilli);
      }
    }
    notifyListeners();
  }

  /// Reversal quantity of lot [lotId] in milli (0 for empty/invalid text).
  int revMilli(String lotId) => parseQty(rev[lotId], allowZero: true).value ?? 0;

  /// Σ reversal of a line (milli).
  int revSumMilli(CorrLine l) => sumMilli(l.lots.map((lt) => revMilli(lt.id)));

  /// Σ replacement lots of a line (milli) — from the rows that will be sent.
  int repSumMilli(CorrLine l) => l.repOn && l.rep != null ? l.rep!.state.sumMilli : 0;

  /// Replacement unit cost of a line (cents, 0 when empty/invalid).
  int repCostCents(CorrLine l) => parseMoney(l.repCost, allowZero: true).value ?? 0;

  /// A lot being reversed on [l] already moved (its identity is frozen).
  bool touched(CorrLine l) => l.lots.any((lt) => revMilli(lt.id) > 0 && !lt.correctable);

  // ── Money preview (DOCUMENT basis, rounded ONCE — `lot_correction`) ──────

  /// Σ reversed × document unit price, rounded once to cents.
  int get reversedCents {
    var raw = BigInt.zero;
    for (final l in _lines) {
      for (final lt in l.lots) {
        final m = revMilli(lt.id);
        if (m > 0) raw += BigInt.from(m) * BigInt.from(lt.docCostCents);
      }
    }
    return _roundOnce(raw);
  }

  /// Σ replacement × replacement line cost, rounded once to cents.
  int get replacedCents {
    var raw = BigInt.zero;
    for (final l in _lines) {
      final m = repSumMilli(l);
      if (m > 0) raw += BigInt.from(m) * BigInt.from(repCostCents(l));
    }
    return _roundOnce(raw);
  }

  /// Change of the document total.
  int get deltaCents => replacedCents - reversedCents;

  /// Document total after the correction.
  int get newTotalCents => _doc.totalCents + deltaCents;

  /// `paid − new total`: > 0 cash comes back, < 0 more cash goes out. The
  /// writer asks for custody exactly when this is non-zero (not on `delta`).
  int get retAmtCents => _doc.paidCents - newTotalCents;

  /// Money actually moves (|paid − new total| ≥ 0.01).
  bool get moneyMoves => retAmtCents != 0;

  /// Every lot's remaining quantity is reversed.
  bool get allReversed =>
      _lines.isNotEmpty && _lines.every((l) => l.lots.every((lt) => revMilli(lt.id) >= lt.remainingMilli));

  /// The correction cancels the whole document (same rule as the writer).
  bool get fullCancel => allReversed && !_lines.any((l) => l.repOn) && newTotalCents == 0;

  // ── Cash custody (server block, drawn only when money moves) ─────────────

  /// Custody block of the document (null = older server).
  CustodyInfo? get custody => _doc.cashCustody;

  /// The custody block is shown (money moves AND the mode needs a word).
  bool get cashShown {
    final c = custody;
    if (!moneyMoves || c == null) return false;
    return c.mode == CustodyMode.serverResolved ||
        c.mode == CustodyMode.operatorMustChoose ||
        c.mode == CustodyMode.blocked;
  }

  /// The operator must pick an account.
  bool get mustChoose => cashShown && custody!.mode == CustodyMode.operatorMustChoose;

  /// Must choose, but the branch has no active account.
  bool get cashEmpty => mustChoose && custody!.options.isEmpty;

  /// Money moves and the server says it cannot move now.
  bool get cashBlocked => (cashShown && custody!.mode == CustodyMode.blocked) || cashEmpty;

  /// A choice is still missing.
  bool get cashNeed => mustChoose && !cashEmpty && !custody!.isReady(cashAccountId);

  /// Why the cash gate is closed (empty when open).
  String cashGateReason() {
    if (cashEmpty) return custody!.blockedReason();
    if (cashBlocked) {
      return trArgs('Bu tuzatish pulni siljitadi, lekin uni hozir yozib bo‘lmaydi: {reason}',
          {'reason': custody!.blockedReason()});
    }
    if (cashNeed) return tr('Pul qaysi kassa yoki seyf orqali o‘tishini tanlang — server buni taxmin qilmaydi');
    return '';
  }

  /// `cash_account_id` to send (only for OPERATOR_MUST_CHOOSE with money moving).
  String? get accountToSend => mustChoose ? custody!.accountToSend(cashAccountId) : null;

  // ── Request ──────────────────────────────────────────────────────────────

  /// `lines[]` — a line with neither reversal nor replacement is not sent;
  /// `unit_cost` goes ONLY together with `replace` (the server rejects a cost
  /// change without new lots); `expiry_date` only for expiry-tracked products.
  List<Map<String, Object?>> payload() {
    final out = <Map<String, Object?>>[];
    for (final l in _lines) {
      final reverse = [
        for (final lt in l.lots)
          if (revMilli(lt.id) > 0) {'stock_batch_id': lt.id, 'qty': milliToJson(revMilli(lt.id))}
      ];
      final replace = l.repOn && l.rep != null ? l.rep!.lotsPayload() : const <Map<String, Object>>[];
      if (reverse.isEmpty && replace.isEmpty) continue;
      out.add(replace.isNotEmpty
          ? {
              'purchase_item_id': l.itemId,
              'reverse': reverse,
              'replace': replace,
              'unit_cost': centsToJson(repCostCents(l)),
            }
          : {'purchase_item_id': l.itemId, 'reverse': reverse});
    }
    return out;
  }

  /// The request body.
  Map<String, Object?> body() {
    final acc = accountToSend;
    return {
      'client_uuid': uuid,
      'reason': reason.trim(),
      'lines': payload(),
      if (acc != null) 'cash_account_id': acc,
    };
  }

  /// Fingerprint of what the operator TYPED (plus the key and the account) —
  /// deliberately NOT the reloaded remaining quantities, so re-sending the
  /// same draft after a lost answer is recognised as the same request.
  String draftKey() {
    final keys = rev.keys.toList()..sort();
    return jsonEncode({
      'u': uuid,
      'reason': reason.trim(),
      'rev': [
        for (final k in keys)
          if ((rev[k] ?? '').trim().isNotEmpty && parseQty(rev[k], allowZero: true).value != 0)
            [k, parseQty(rev[k], allowZero: true).value ?? rev[k]!.trim()]
      ],
      'rep': [
        for (final l in _lines)
          [
            l.itemId,
            l.repOn,
            l.repQty.trim(),
            l.repCost.trim(),
            if (l.rep != null)
              for (final r in l.rep!.rows) [r.qty.trim(), r.expiry, r.batch.trim()]
          ]
      ],
      'acc': mustChoose ? (cashAccountId ?? '') : '',
    });
  }

  /// This is exactly the draft that was already sent (its answer was lost or
  /// rejected): it is re-sent WITHOUT the client checks and the cash gate, so
  /// the server's dedup can answer `duplicate: true` (desktop `isReplay`).
  bool get isReplay => sentKey != null && sentKey == draftKey();

  /// Remembers the draft being sent (BEFORE the request leaves).
  void markSent() => sentKey = draftKey();

  /// `LOT_CORRECTION_REPLAY_CONFLICT`: the key was used with other content —
  /// a NEW key, and the next submit is a new request (full checks).
  void onReplayConflict() {
    uuid = Api.newUuid();
    sentKey = null;
    notifyListeners();
  }

  /// The server DECIDED to refuse (4xx): nothing was written, so the attempt
  /// is over. The next submit is a NEW request — the client checks and the
  /// cash custody gate run again (the document was reloaded and the custody
  /// mode may have changed under it). The key is KEPT: no write happened, so
  /// it is still free. Only an UNKNOWN outcome justifies the replay path.
  void onDecided() {
    if (sentKey == null) return;
    sentKey = null;
    notifyListeners();
  }

  /// Something was typed (leaving asks for confirmation).
  bool get dirty =>
      reason.trim().isNotEmpty ||
      rev.values.any((v) => v.trim().isNotEmpty) ||
      _lines.any((l) => l.repOn) ||
      cashAccountId != null;

  // ── Checks (a MIRROR of the server rules, never a replacement) ───────────

  /// The first problem, or null when the draft may be sent.
  CorrIssue? check() {
    final r = reason.trim();
    if (r.length < 3 || r.length > 300) {
      return CorrIssue(CorrIssueKind.reason, tr('Sababni yozing (3–300 belgi) — tuzatish izsiz qolmaydi'));
    }
    for (final l in _lines) {
      for (final lt in l.lots) {
        final t = (rev[lt.id] ?? '').trim();
        if (t.isEmpty) continue;
        final p = parseQty(t, allowZero: true);
        if (!p.ok) {
          return CorrIssue(CorrIssueKind.revInvalid,
              trArgs('«{name}»: teskari qilinadigan miqdor noto‘g‘ri', {'name': l.name}),
              itemId: l.itemId, lotId: lt.id);
        }
        if (p.value! > lt.remainingMilli) {
          return CorrIssue(CorrIssueKind.overRemaining,
              trArgs('«{name}»: miqdor partiya qoldig‘idan katta — partiya manfiyga tushmaydi', {'name': l.name}),
              itemId: l.itemId, lotId: lt.id);
        }
        if (p.value! > 0 && l.blocked != null) {
          return CorrIssue(CorrIssueKind.blockedLine, '«${l.name}»: ${blockedText(l)}', itemId: l.itemId, lotId: lt.id);
        }
      }
      if (!l.repOn) continue;
      if (l.blocked != null) {
        return CorrIssue(CorrIssueKind.blockedLine, '«${l.name}»: ${blockedText(l)}', itemId: l.itemId);
      }
      if (touched(l)) {
        return CorrIssue(CorrIssueKind.replaceLocked,
            trArgs('«{name}»: o‘rniga qo‘yish yopiq — teskari qilinayotgan partiyadan tovar allaqachon ketgan',
                {'name': l.name}),
            itemId: l.itemId);
      }
      if (!parseQty(l.repQty).ok) {
        return CorrIssue(CorrIssueKind.repQty,
            trArgs('«{name}»: o‘rniga qo‘yiladigan miqdorni kiriting', {'name': l.name}), itemId: l.itemId);
      }
      final st = l.rep!.state;
      if (!st.ok) return CorrIssue(CorrIssueKind.repLots, _lotIssueText(l, st), itemId: l.itemId);
      // Tannarx 0 bo'lsa partiya `cost_basis = unknown` bilan tug'iladi — kirim bilan AYNI qoida.
      if (!parseMoney(l.repCost).ok) {
        return CorrIssue(CorrIssueKind.repCost,
            trArgs('«{name}»: yangi partiya tannarxini kiriting — u taxmin qilinmaydi', {'name': l.name}),
            itemId: l.itemId);
      }
    }
    if (payload().isEmpty) {
      return CorrIssue(CorrIssueKind.nothing,
          tr('Hech narsa tanlanmagan — teskari qilinadigan miqdor kiriting yoki yangi partiya qo‘shing'));
    }
    return null;
  }

  String _lotIssueText(CorrLine l, LotLineState st) {
    final n = {'name': l.name};
    switch (st.issues.first.kind) {
      case LotIssueKind.mismatch:
        return trArgs('«{name}»: yangi partiyalar yig‘indisi o‘rniga qo‘yiladigan miqdorga teng emas', n);
      case LotIssueKind.expiryMissing:
        return trArgs('«{name}»: yangi partiyaga yaroqlilik muddatini kiriting', n);
      case LotIssueKind.expiryPast:
        return trArgs('«{name}»: muddat ish kunidan ({d}) oldin bo‘lmasin', {...n, 'd': dateDisplay(businessDate)});
      case LotIssueKind.tooMany:
        return trArgs('«{name}»: ko‘pi bilan {n} ta partiya', {'name': l.name, 'n': kMaxLots});
      case LotIssueKind.lineQty:
        return trArgs('«{name}»: o‘rniga qo‘yiladigan miqdorni kiriting', n);
      case LotIssueKind.qty:
      case LotIssueKind.decimals:
      case LotIssueKind.cost:
        return trArgs('«{name}»: yangi partiya miqdorini tekshiring', n);
    }
  }

  /// Localized block reason of a line.
  static String blockedText(CorrLine l) {
    final s = serverText(l.blocked);
    return s.isEmpty ? tr('Bu qatorni tuzatib bo‘lmaydi') : s;
  }

  @override
  void dispose() {
    for (final l in _lines) {
      l.rep?.removeListener(notifyListeners);
      l.rep?.dispose();
      l.rep = null;
    }
    super.dispose();
  }
}

/// `client_uuid`s whose request outcome is UNKNOWN (network failure/timeout),
/// by purchase id — kept in memory so an editor that is closed and reopened
/// after a lost answer sends the SAME key: re-entering the same correction
/// then comes back as `duplicate: true` instead of being written twice; a
/// different correction under that key comes back as
/// `LOT_CORRECTION_REPLAY_CONFLICT` (then a new key is used).
abstract final class PendingCorrectionKeys {
  static final Map<String, String> _byPurchase = {};

  /// The unresolved key of [purchaseId], if any.
  static String? of(String purchaseId) => _byPurchase[purchaseId];

  /// Remembers that [uuid]'s outcome is unknown.
  static void unknown(String purchaseId, String uuid) => _byPurchase[purchaseId] = uuid;

  /// The server answered (success or a decided rejection): forget it.
  static void resolved(String purchaseId) => _byPurchase.remove(purchaseId);

  /// Tests.
  @visibleForTesting
  static void clear() => _byPurchase.clear();
}

// ════════════════════════════════════════════════════════════════════════════
//  SCREEN
// ════════════════════════════════════════════════════════════════════════════

/// Correct or cancel a receiving (lot reversal + optional replacement).
class CorrectionScreen extends StatefulWidget {
  /// Creates the screen for a loaded [doc] (from `GET /purchases/{id}`).
  const CorrectionScreen({super.key, required this.doc});

  /// The document as last loaded.
  final PurchaseDoc doc;

  /// Pushes the screen; resolves to the server's [CorrectionResult] after a
  /// 2xx, or `null` when the operator leaves without writing.
  static Future<CorrectionResult?> open(BuildContext context, PurchaseDoc doc) =>
      Navigator.of(context).push<CorrectionResult>(
        MaterialPageRoute(builder: (_) => CorrectionScreen(doc: doc)),
      );

  @override
  State<CorrectionScreen> createState() => _CorrectionScreenState();
}

class _CorrectionScreenState extends State<CorrectionScreen> {
  late final CorrectionDraft _d =
      CorrectionDraft(widget.doc, uuid: PendingCorrectionKeys.of(widget.doc.id))..addListener(_changed);
  final _reason = TextEditingController();
  final _reasonFocus = FocusNode(debugLabel: 'corr reason');
  final Map<String, TextEditingController> _revCtl = {}, _repQtyCtl = {}, _repCostCtl = {};
  final Map<String, FocusNode> _focus = {};
  final Map<String, GlobalKey> _lineKeys = {};
  bool _busy = false;
  bool _tried = false;
  Object? _sendError;
  String? _checkError;

  @override
  void dispose() {
    _d.removeListener(_changed);
    _d.dispose();
    _reason.dispose();
    _reasonFocus.dispose();
    for (final m in [_revCtl, _repQtyCtl, _repCostCtl]) {
      for (final c in m.values) {
        c.dispose();
      }
    }
    for (final f in _focus.values) {
      f.dispose();
    }
    super.dispose();
  }

  void _changed() {
    if (!mounted) return;
    setState(() {
      // After a failed submit attempt the banner follows the CURRENT first
      // problem (and disappears once the draft is sendable).
      if (_checkError != null) _checkError = _preflight();
    });
  }

  /// Cash gate, then the client checks — the first problem's message or null.
  String? _preflight() {
    if (_d.cashBlocked || _d.cashNeed) return _d.cashGateReason();
    return _d.check()?.message;
  }

  TextEditingController _ctl(Map<String, TextEditingController> m, String key, String text) {
    final c = m.putIfAbsent(key, () => TextEditingController(text: text));
    if (c.text != text) c.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
    return c;
  }

  FocusNode _node(String key) => _focus.putIfAbsent(key, () => FocusNode(debugLabel: key));

  GlobalKey _lineKey(String itemId) => _lineKeys.putIfAbsent(itemId, GlobalKey.new);

  // ── Actions ──────────────────────────────────────────────────────────────

  Future<void> _submit() async {
    if (_busy) return;
    FocusScope.of(context).unfocus();
    // Ayni qoralamaning TAKRORI (javobi yo'qolgan urinish) — tekshiruv va kassa
    // to'sig'i o'tkazib yuboriladi: server dedup'i `duplicate: true` beradi.
    final replay = _d.isReplay;
    if (!replay) {
      if (_d.cashBlocked || _d.cashNeed) {
        setState(() {
          _tried = true;
          _checkError = _d.cashGateReason();
        });
        return;
      }
      final issue = _d.check();
      if (issue != null) {
        setState(() {
          _tried = true;
          _checkError = issue.message;
        });
        _focusIssue(issue);
        return;
      }
    }
    setState(() {
      _checkError = null;
    });
    final ok = await _confirm();
    if (!ok || !mounted) return;
    await _send();
  }

  void _focusIssue(CorrIssue issue) {
    FocusNode? node;
    switch (issue.kind) {
      case CorrIssueKind.reason:
        node = _reasonFocus;
      case CorrIssueKind.revInvalid:
      case CorrIssueKind.overRemaining:
        node = issue.lotId == null ? null : _node('rev/${issue.lotId}');
      case CorrIssueKind.repQty:
        node = _node('repqty/${issue.itemId}');
      case CorrIssueKind.repCost:
        node = _node('repcost/${issue.itemId}');
      case CorrIssueKind.repLots:
        for (final l in _d.lines) {
          if (l.itemId == issue.itemId) l.rep?.validate();
        }
        return;
      case CorrIssueKind.blockedLine:
      case CorrIssueKind.replaceLocked:
      case CorrIssueKind.nothing:
        node = null;
    }
    if (node != null) {
      node.requestFocus();
    }
    final itemId = issue.itemId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final ctx = node?.context ?? (itemId == null ? null : _lineKeys[itemId]?.currentContext);
      if (ctx != null && ctx.mounted) {
        Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 200), alignment: 0.2);
      }
    });
  }

  Future<bool> _confirm() {
    final cancel = _d.fullCancel;
    final label = cancel ? tr('Hujjatni bekor qilish') : tr('Tuzatishni yozish');
    final acc = _d.accountToSend;
    CustodyAccount? account;
    if (acc != null) {
      for (final o in _d.custody!.options) {
        if (o.id == acc) account = o;
      }
    }
    return confirmDestructive(
      context,
      title: cancel ? tr('Hujjat BEKOR qilinadi') : tr('Tuzatish yozilsinmi?'),
      message: tr('Tuzatish — o‘zgarmas hodisa: uni o‘chirib bo‘lmaydi, faqat yangi tuzatish bilan to‘g‘rilanadi.'),
      details: [
        if (cancel) tr('Butun qabul teskari qilinadi: qoldiq kamayadi va hujjat bekor bo‘ladi.'),
        trArgs('Hujjat jami: {old} → {next}',
            {'old': formatCents(_d.doc.totalCents), 'next': formatCents(_d.newTotalCents)}),
        if (_moneyLine() != null) _moneyLine()!,
        if (account != null) trArgs('Hisob: {code}', {'code': '${account.code} · ${account.typeLabel}'}),
        tr('Qoldiq va partiyalar darhol o‘zgaradi.'),
      ],
      confirmLabel: label,
      cancelLabel: tr('Tahrirga qaytish'),
      requireAcknowledge: true,
    );
  }

  /// Where the money difference goes, or null when nothing moves.
  String? _moneyLine() {
    final c = _d.custody;
    final credit = c == null ? _d.doc.isCredit : c.mode == CustodyMode.notApplicable;
    if (credit) {
      final delta = _d.deltaCents;
      if (delta == 0) return null;
      return trArgs('Yetkazib beruvchi qarzi o‘zgaradi: {s}', {'s': signedCents(delta)});
    }
    final ret = _d.retAmtCents;
    if (ret > 0) return trArgs('Kassaga qaytadi: {s}', {'s': formatCents(ret)});
    if (ret < 0) return trArgs('Kassadan chiqadi: {s}', {'s': formatCents(-ret)});
    return null;
  }

  Future<void> _send() async {
    if (_busy) return;
    final rid = _d.doc.receivingId;
    if (rid == null) return;
    setState(() {
      _busy = true;
      _sendError = null;
    });
    // Jo'natishdan OLDIN belgilanadi: javobi yo'qolgan urinish ham «yuborilgan».
    _d.markSent();
    final body = _d.body();
    final pid = _d.doc.id;
    // ⚠️  Kalit so'rov KETISHIDAN OLDIN eslab qolinadi. Ekran javobni kutib
    //     turganida butunlay yo'q qilinishi mumkin (401 -> `onSessionExpired`
    //     -> pushAndRemoveUntil(LoginScreen) — Fayzan, 2026-09-17: ega xodim
    //     parolini tikladi). Keyin bu `catch` hech qachon kalitni yozib
    //     ulgurmasdi va qayta kirgan menejer YANGI kalit bilan o'sha
    //     tuzatishni ikkinchi marta yozardi. Kalit faqat 2xx da yoki ANIQ rad
    //     etishda o'chadi.
    PendingCorrectionKeys.unknown(pid, body['client_uuid']! as String);
    try {
      final res = await CorrectionApi.submit(receivingId: rid, body: body);
      PendingCorrectionKeys.resolved(pid);
      if (!mounted) return;
      setState(() => _busy = false);
      Navigator.of(context).pop(res);
      return;
    } catch (e) {
      // Natija NOMA'LUM bo'lsa (javob yo'q / 5xx / eskirgan sessiyada rad
      // etilgan 2xx-5xx) kalit saqlanib qoladi — yagona xavfsiz qayta yuborish
      // shu kalit bilan bo'ladi.
      if (!outcomeUnknown(e)) PendingCorrectionKeys.resolved(pid);
      // Ekran allaqachon yo'q: qoralamaga TEGILMAYDI (dispose qilingan
      // ChangeNotifier ni xabardor qilish — xato).
      if (!mounted) return;
      if (!outcomeUnknown(e)) {
        // Ayni kalit boshqa mazmun bilan ishlatilgan — bu TAKROR emas: ayni kalit
        // bilan qayta urinish abadiy 409 berardi. Yangi kalit = yangi so'rov.
        if (e is ApiException && e.code == 'LOT_CORRECTION_REPLAY_CONFLICT') {
          _d.onReplayConflict();
        } else {
          // Server RAD ETDI (hech narsa yozilmadi) — keyingi yuborish YANGI
          // so'rov: tekshiruvlar va kassa to'sig'i qaytadan ishlaydi.
          _d.onDecided();
        }
      }
      setState(() => _sendError = e);
    }
    // Rad etishdan (yoki javobsiz urinishdan) keyin hujjat QAYTA o'qiladi:
    // qoldiqlar eskirgan bo'lishi mumkin; kiritilganlar saqlanadi.
    await _reload();
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _reload() async {
    try {
      final next = await CorrectionApi.purchase(_d.doc.id);
      if (!mounted) return;
      _d.setDoc(next);
    } catch (_) {
      // Hujjat ekranda qoladi; yuborish xatosi allaqachon ko'rsatilgan.
    }
  }

  Future<void> _onPopBlocked() async {
    if (_busy) return;
    final leave = await confirmDestructive(
      context,
      title: tr('Tuzatish yozilmadi'),
      message: tr('Kiritilgan ma’lumotlar yo‘qoladi. Chiqasizmi?'),
      confirmLabel: tr('Chiqish'),
      cancelLabel: tr('Tahrirga qaytish'),
    );
    if (leave && mounted) Navigator.of(context).pop();
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (!Perm.allows(kCorrectAction)) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Qabulni tuzatish'))),
        body: EmptyState(text: Perm.reason(kCorrectAction), icon: Icons.lock_outline),
      );
    }
    final doc = _d.doc;
    return PopScope(
      canPop: !_busy && !_d.dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _onPopBlocked();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('Qabulni tuzatish'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            Text(
              [doc.docNo, if (doc.supplier.isNotEmpty) doc.supplier].join(' · '),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12.5, color: AppColors.muted),
            ),
          ]),
        ),
        body: Column(children: [
          const ConnectivityBanner(),
          Expanded(
            child: ListView(
              key: const Key('corr-list'),
              padding: const EdgeInsets.fromLTRB(kGutter, 8, kGutter, 24),
              children: [
                _intro(doc),
                const SizedBox(height: 14),
                _reasonField(),
                if (_d.lines.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  SizedBox(
                    height: kMinTouch,
                    child: OutlinedButton.icon(
                      key: const Key('corr-reverse-all'),
                      onPressed: _busy ? null : _d.reverseAll,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.danger,
                        side: BorderSide(color: AppColors.danger.withAlpha(140)),
                      ),
                      icon: const Icon(Icons.undo),
                      label: Text(tr('Butun hujjatni teskari qilish')),
                    ),
                  ),
                ],
                for (var i = 0; i < _d.lines.length; i++) _lineCard(i, _d.lines[i]),
                if (_d.lines.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(tr('Bu hujjatda tuzatiladigan partiya yo‘q'),
                        key: const Key('corr-no-lots'), style: TextStyle(color: AppColors.muted, fontSize: 14)),
                  ),
                if (_d.cashShown) ...[
                  const SizedBox(height: 16),
                  KeyedSubtree(
                    key: const Key('corr-cash'),
                    child: CustodyBlock(
                      info: _d.custody!,
                      selectedId: _d.cashAccountId,
                      onChanged: _d.setCash,
                      showErrors: _tried,
                      enabled: !_busy,
                    ),
                  ),
                ],
                if (_moneyLine() != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Row(children: [
                      Icon(Icons.account_balance_wallet_outlined, size: 18, color: AppColors.text3),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(_moneyLine()!,
                            key: const Key('corr-money-line'), style: TextStyle(fontSize: 13.5, color: AppColors.text2)),
                      ),
                    ]),
                  ),
              ],
            ),
          ),
          _bar(doc),
        ]),
      ),
    );
  }

  Widget _intro(PurchaseDoc doc) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.accentSoft,
          borderRadius: BorderRadius.circular(kRadius),
          border: Border.all(color: AppColors.accentBorder),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            tr('Qator tahrirlanmaydi: ortiqcha yozilgan miqdor partiyadan teskari qilinadi, kerak bo‘lsa o‘rniga yangi partiya yoziladi.'),
            style: TextStyle(fontSize: 13, color: AppColors.text2, height: 1.35),
          ),
          if (doc.branchName != null) ...[
            const SizedBox(height: 6),
            Text(trArgs('Filial: {name}', {'name': doc.branchName}),
                key: const Key('corr-branch'), style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
          ],
        ]),
      );

  Widget _reasonField() {
    final r = _d.reason.trim();
    final bad = r.length < 3 || r.length > 300;
    return TextField(
      key: const Key('corr-reason'),
      controller: _reason,
      focusNode: _reasonFocus,
      enabled: !_busy,
      maxLength: 300,
      minLines: 1,
      maxLines: 3,
      textCapitalization: TextCapitalization.sentences,
      textInputAction: TextInputAction.done,
      onChanged: _d.setReason,
      decoration: InputDecoration(
        labelText: '${tr('Tuzatish sababi')} *',
        hintText: tr('Nima xato bo‘lgan?'),
        errorText: _tried && bad ? tr('Sababni yozing (3–300 belgi) — tuzatish izsiz qolmaydi') : null,
        errorMaxLines: 3,
        constraints: const BoxConstraints(minHeight: kMinTouch),
      ),
    );
  }

  Widget _lineCard(int i, CorrLine l) {
    final revSum = _d.revSumMilli(l);
    final touched = _d.touched(l);
    final unit = unitLabel(l.item.unit);
    final canToggle = !_busy && l.blocked == null && (l.repOn || !touched);
    return Container(
      key: _lineKey(l.itemId),
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(kRadius),
        border: Border.all(color: l.blocked != null ? AppColors.warnBorder : AppColors.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Text(l.name, key: Key('corr-line-$i-name'), style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(width: 8),
          Text(unit, style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
        ]),
        if (revSum > 0)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(trArgs('teskari qilinadi: {n}', {'n': '${formatMilli(revSum)} $unit'}),
                key: Key('corr-line-$i-rev'),
                style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.danger)),
          ),
        if (l.blocked != null)
          _note(CorrectionDraft.blockedText(l), AppColors.warn, key: Key('corr-line-$i-blocked')),
        for (final lt in l.lots) _lotRow(l, lt, unit),
        const SizedBox(height: 8),
        Divider(height: 1, color: AppColors.border),
        _toggleRow(i, l, canToggle),
        if (touched)
          _note(tr('O‘rniga qo‘yish yopiq: teskari qilinayotgan partiyadan tovar allaqachon ketgan'), AppColors.warn,
              key: Key('corr-line-$i-rep-locked')),
        if (l.repOn && l.rep != null) ..._replacement(i, l, unit),
      ]),
    );
  }

  Widget _lotRow(CorrLine l, ReceivedLot lt, String unit) {
    final text = _d.rev[lt.id] ?? '';
    final p = parseQty(text, allowZero: true);
    String? err;
    if (text.trim().isNotEmpty && !p.ok) {
      err = qtyErrorText(p.error!);
    } else if ((p.value ?? 0) > lt.remainingMilli) {
      err = trArgs('Qoldiqdan ko‘p — partiyada {q} qolgan', {'q': '${formatMilli(lt.remainingMilli)} $unit'});
    }
    final biz = _d.businessDate;
    final expired = lt.expiryDate != null && biz != null && lt.expiryDate!.compareTo(biz) < 0;
    // Qoldiq 0 bo'lsa kiritish yopiq — lekin avval yozilgan qiymat bo'lsa
    // operator uni o'chira olishi kerak (qayta o'qilgandan keyin).
    final enabled = !_busy && l.blocked == null && (lt.remainingMilli > 0 || text.isNotEmpty);
    final title = [
      lt.batchNo ?? tr('Raqamsiz partiya'),
      if (lt.expiryDate != null) dateDisplay(lt.expiryDate),
    ].join(' · ');
    return Container(
      key: Key('corr-lot-${lt.id}'),
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.only(top: 10),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700))),
          if (expired)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(color: AppColors.dangerSoft, borderRadius: BorderRadius.circular(8)),
              child: Text(tr('Muddati o‘tgan'), style: const TextStyle(fontSize: 11.5, color: AppColors.danger)),
            ),
        ]),
        const SizedBox(height: 3),
        Text(
          trArgs('Qabul: {r} · Qoldiq: {q} · Ketgan: {c}', {
            'r': formatMilli(lt.receivedMilli),
            'q': formatMilli(lt.remainingMilli),
            'c': formatMilli(lt.consumedMilli),
          }),
          style: TextStyle(fontSize: 12.5, color: AppColors.muted),
        ),
        Text(trArgs('Hujjat narxi: {s}', {'s': formatCents(lt.docCostCents)}),
            style: TextStyle(fontSize: 12.5, color: AppColors.muted)),
        if (!lt.correctable && l.blocked == null)
          _note(
              tr('Bu partiyadan tovar ketgan — raqami, muddati va tannarxi tuzatilmaydi; faqat miqdorni teskari qilish mumkin'),
              AppColors.warn,
              key: Key('corr-lot-${lt.id}-touched')),
        const SizedBox(height: 8),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: QtyField(
              key: Key('corr-rev-${lt.id}'),
              controller: _ctl(_revCtl, lt.id, text),
              focusNode: _node('rev/${lt.id}'),
              label: tr('Teskari qilinadigan miqdor'),
              unit: unit,
              allowZero: true,
              enabled: enabled,
              errorText: err,
              helperText: err == null ? trArgs('Partiya qoldig‘i: {q}', {'q': formatMilli(lt.remainingMilli)}) : null,
              onChanged: (_) => _d.setRev(lt.id, _revCtl[lt.id]!.text),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            height: 56,
            child: OutlinedButton(
              key: Key('corr-rev-all-${lt.id}'),
              onPressed: enabled && lt.remainingMilli > 0
                  ? () => _d.setRev(lt.id, milliToInput(lt.remainingMilli))
                  : null,
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(kMinTouch + 16, kMinTouch),
                padding: const EdgeInsets.symmetric(horizontal: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: Text(tr('Hammasi')),
            ),
          ),
        ]),
      ]),
    );
  }

  Widget _toggleRow(int i, CorrLine l, bool canToggle) => Semantics(
        toggled: l.repOn,
        child: InkWell(
          key: Key('corr-replace-$i'),
          onTap: canToggle ? () => _d.setRepOn(l, !l.repOn) : null,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: kMinTouch + 8),
            child: Row(children: [
              Expanded(
                child: Text(tr('O‘rniga yangi partiya yozish'),
                    style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w600,
                        color: canToggle ? AppColors.text : AppColors.faint)),
              ),
              Switch(
                value: l.repOn,
                onChanged: canToggle ? (v) => _d.setRepOn(l, v) : null,
              ),
            ]),
          ),
        ),
      );

  List<Widget> _replacement(int i, CorrLine l, String unit) {
    final qp = parseQty(l.repQty);
    final cp = parseMoney(l.repCost);
    return [
      const SizedBox(height: 6),
      QtyField(
        key: Key('corr-rep-qty-$i'),
        controller: _ctl(_repQtyCtl, l.itemId, l.repQty),
        focusNode: _node('repqty/${l.itemId}'),
        label: '${tr('O‘rniga qo‘yiladigan miqdor')} *',
        unit: unit,
        enabled: !_busy,
        errorText: (_tried || l.repQty.isNotEmpty) && !qp.ok ? qtyErrorText(qp.error!) : null,
        onChanged: (_) => _d.setRepQty(l, _repQtyCtl[l.itemId]!.text),
      ),
      const SizedBox(height: 10),
      MoneyField(
        key: Key('corr-rep-cost-$i'),
        controller: _ctl(_repCostCtl, l.itemId, l.repCost),
        focusNode: _node('repcost/${l.itemId}'),
        label: '${tr('Yangi tannarx (birlik uchun)')} *',
        wholeOnly: false,
        enabled: !_busy,
        errorText: _tried && !cp.ok ? tr('Yangi tannarxni kiriting (0 dan katta)') : null,
        onChanged: (_) => _d.setRepCost(l, _repCostCtl[l.itemId]!.text),
      ),
      const SizedBox(height: 10),
      LotEditor(
        key: Key('corr-lots-$i'),
        controller: l.rep!,
        unit: unit,
        title: tr('Yangi partiyalar'),
        enabled: !_busy,
      ),
      const SizedBox(height: 6),
    ];
  }

  Widget _note(String text, Color color, {Key? key}) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text(text, key: key, style: TextStyle(fontSize: 12.5, color: color, height: 1.3)),
      );

  Widget _bar(PurchaseDoc doc) {
    final replay = _d.isReplay;
    String? reason;
    if (!doc.correctionOpen) {
      final s = serverText(doc.blockedReason);
      reason = s.isEmpty ? tr('Bu hujjatni tuzatib bo‘lmaydi') : s;
    } else if (!replay && (_d.cashBlocked || _d.cashNeed)) {
      reason = _d.cashGateReason();
    }
    final cancel = _d.fullCancel;
    final err = _sendError;
    return StickyActionBar(
      key: const Key('corr-bar'),
      label: cancel ? tr('Hujjatni bekor qilish') : tr('Tuzatishni yozish'),
      icon: cancel ? Icons.delete_forever_outlined : Icons.edit_note,
      danger: true,
      busy: _busy,
      enabled: reason == null,
      disabledReason: reason,
      onPressed: _submit,
      summary: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (err != null) ...[
          ErrorBanner(
            key: const Key('corr-error'),
            error: err,
            message: outcomeUnknown(err)
                ? '${userMessage(err)} ${tr('Natija noma’lum: aynan shu tuzatishni qayta yuboring — server uni ikki marta yozmaydi.')}'
                : userMessage(err),
            onDismiss: () => setState(() => _sendError = null),
          ),
          const SizedBox(height: 8),
        ],
        if (_checkError != null) ...[
          ErrorBanner(
            key: const Key('corr-check'),
            message: _checkError!,
            severity: BannerSeverity.warning,
            onDismiss: () => setState(() => _checkError = null),
          ),
          const SizedBox(height: 8),
        ],
        _totals(),
        if (cancel)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(tr('Bu tuzatish hujjatni to‘liq bekor qiladi'),
                key: const Key('corr-full-cancel'),
                style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.danger)),
          ),
      ]),
    );
  }

  Widget _totals() {
    Widget cell(String label, String value, Color color, Key key) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: AppColors.muted)),
            const SizedBox(height: 2),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(value, key: key, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: color)),
            ),
          ]),
        );
    return Row(children: [
      cell(tr('Teskari'), _d.reversedCents == 0 ? formatCents(0) : '−${formatCents(_d.reversedCents)}', AppColors.danger,
          const Key('corr-sum-reversed')),
      const SizedBox(width: 8),
      cell(tr('O‘rniga'), _d.replacedCents == 0 ? formatCents(0) : '+${formatCents(_d.replacedCents)}', AppColors.ok,
          const Key('corr-sum-replaced')),
      const SizedBox(width: 8),
      cell(tr('Yangi jami'), formatCents(_d.newTotalCents), AppColors.text, const Key('corr-sum-total')),
    ]);
  }
}
