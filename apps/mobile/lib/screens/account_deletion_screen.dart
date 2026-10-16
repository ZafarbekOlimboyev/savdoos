import 'package:flutter/material.dart';

import '../api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../lock.dart';
import '../theme.dart';
import '../ui/confirm_erase.dart';
import '../ui/ui.dart';
import 'login_screen.dart';

/// Deletes the signed-in user's own account (Apple Guideline 5.1.1(v)).
///
/// ⚠️  THIS IS NOT A DEACTIVATION SCREEN. The server rewrites the name, phone,
///     password and PIN columns, so there is nothing left to restore. The text
///     says so plainly BEFORE the button, and says equally plainly what is
///     KEPT: sales, cash and inventory records stay for bookkeeping, because
///     they record a transaction rather than a person.
///
/// ⚠️  THE SOLE MANAGER IS NOT LEFT IN A DEAD END. When the server reports
///     `sole_manager`, the screen explains the way out (appoint another
///     manager) instead of showing a button that always fails.
class AccountDeletionScreen extends StatefulWidget {
  /// Creates the screen.
  const AccountDeletionScreen({super.key});

  @override
  State<AccountDeletionScreen> createState() => _AccountDeletionScreenState();
}

class _AccountDeletionScreenState extends State<AccountDeletionScreen> {
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  AccountDeletionState? _state;
  bool _loading = true;
  bool _busy = false;
  String? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final st = await Api.accountDeletionState();
      if (mounted) setState(() => (_state = st, _loading = false, _err = null));
    } catch (e) {
      if (mounted) setState(() => (_loading = false, _err = userMessage(e)));
    }
  }

  Future<void> _delete() async {
    final st = _state;
    if (_busy || st == null) return;
    if (_password.text.isEmpty) {
      return setState(() => _err = tr('Parolni kiriting'));
    }
    if (_confirm.text.trim() != st.confirmWord) {
      return setState(() => _err =
          trArgs('Tasdiqlash uchun «{word}» so‘zini kiriting', {'word': st.confirmWord}));
    }
    setState(() => (_busy = true, _err = null));
    try {
      await Api.deleteOwnAccount(_password.text, _confirm.text.trim());
    } catch (e) {
      if (mounted) setState(() => (_busy = false, _err = userMessage(e)));
      return;
    }
    if (!mounted) return;
    // The account is gone and every token for it is already void (`sec_epoch`
    // moved), so there is nothing left to show. Same teardown as the ordinary
    // sign-out in Settings: drop the token, clear the app lock, go to sign-in.
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  /// Asks for deletion when this account cannot confirm with a password.
  ///
  /// ⚠️  A PIN IS NOT AUTHORIZATION. PIN-only employees (cashiers) can still
  ///     START deletion from inside the app — which is what Apple requires —
  ///     but the erasure itself is performed by the owner with their password.
  Future<void> _request() async {
    if (_busy) return;
    setState(() => (_busy = true, _err = null));
    try {
      await Api.requestOwnDeletion();
    } catch (e) {
      if (mounted) setState(() => (_busy = false, _err = userMessage(e)));
      return;
    }
    if (mounted) setState(() => _busy = false);
    await _load();
  }

  /// The consequences, in the server's own numbers.
  ///
  /// ⚠️  Each line is a FACT the server reported, not a promise this screen
  ///     invented. The retained-name line is stated PLAINLY: the owner must
  ///     not learn afterwards that personal data they expected to disappear
  ///     is still in the database.
  List<String> _closureDetails(StoreClosurePreview pv) => [
        if (pv.pendingRequests > 0)
          tr('O‘chirishni so‘ragan {n} hisob o‘chiriladi.')
              .replaceFirst('{n}', '${pv.pendingRequests}'),
        if (pv.piiRetainedAfterClosure > 0)
          tr('Qolgan {n} xodimning ismi va telefoni bazada SAQLANIB QOLADI — ularni o‘chirishni hech kim so‘ramagan.')
              .replaceFirst('{n}', '${pv.piiRetainedAfterClosure}'),
        if (pv.accountingRetained)
          tr('Savdo, kassa va ombor yozuvlari buxgalteriya hisobi uchun saqlanadi.'),
        tr('Bu amalni ilova ichidan qaytarib bo‘lmaydi.'),
      ];

  /// Closes the shop — the exit for a sole owner with no successor.
  ///
  /// ⚠️  NOT A PURGE. Access stops; the sales, cash and inventory ledgers are
  ///     KEPT, because they are required bookkeeping records rather than
  ///     personal data.
  ///
  /// ⚠️  The consequences are READ FROM THE SERVER first, never guessed. This
  ///     screen used to promise that "every employee's name and phone is
  ///     erased" — that became FALSE once closing was narrowed to the accounts
  ///     whose holder actually asked for deletion, and a confirmation screen
  ///     that overstates an irreversible action is worse than none.
  Future<void> _closeStore() async {
    if (_busy) return;
    final st = _state;
    setState(() => (_busy = true, _err = null));
    final StoreClosurePreview pv;
    try {
      pv = await Api.storeClosurePreview();
    } catch (e) {
      if (mounted) setState(() => (_busy = false, _err = userMessage(e)));
      return;
    }
    if (!mounted) return;
    setState(() => _busy = false);

    final c = await confirmErase(
      context,
      title: tr('Do‘konni yopish'),
      message: tr('Do‘kon yopiladi va hech kim tizimga kira olmaydi.'),
      phrase: pv.confirmWord.isNotEmpty
          ? pv.confirmWord
          : (st?.confirmWord ?? kEraseConfirmWord),
      details: _closureDetails(pv),
      confirmLabel: tr('Do‘konni yopish'),
      //  ⚠️  OXIRGI IMKONIYAT. Yopilgandan keyin kirish 401 bo'ladi — EGA
      //      uchun ham — ya'ni keyin qaytib kelib o'z ma'lumotini o'chirish
      //      MUMKIN EMAS. Shu bois saylov AYNI SHU oynada beriladi va server
      //      ikkisini BITTA tranzaksiyada bajaradi. Standart — BELGILANMAGAN.
      optIn: EraseOptIn(
        label: tr('Mening shaxsiy ma’lumotlarimni ham o‘chirish'),
        note: tr('Yopilgandan keyin tizimga kira olmaysiz — bu shuni so‘rashning oxirgi imkoniyati.'),
      ),
    );
    if (c == null || !mounted) return;
    setState(() => (_busy = true, _err = null));
    try {
      await Api.closeOwnStore(c.password, c.phrase,
          deleteMyAccount: c.optedIn);
    } catch (e) {
      if (mounted) setState(() => (_busy = false, _err = userMessage(e)));
      return;
    }
    if (!mounted) return;
    await Api.logout();
    await Lock.clear();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false);
  }

  @override
  Widget build(BuildContext context) {
    final st = _state;
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(title: Text(tr('Hisobni o‘chirish'))),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.fromLTRB(kGutter, 16, kGutter, 24),
              children: [
                if (st != null && !st.needsPassword)
                  _requestForm(st)
                else if (st != null && !st.canDelete)
                  _blocked(st)
                else
                  _form(st),
                if (_err != null) ...[
                  const SizedBox(height: 12),
                  Text(_err!,
                      key: const Key('acct-del-error'),
                      style: const TextStyle(color: AppColors.danger, fontSize: 13)),
                ],
              ],
            ),
    );
  }

  Widget _blocked(AccountDeletionState st) => AppCard(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr('Hisobni hozir o‘chirib bo‘lmaydi'),
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 10),
          if (st.hasOpenShift)
            Text(tr('Sizda ochiq smena bor. Avval smenani yoping.'))
          else if (st.isSoleManager) ...[
            Text(tr('Siz do‘kondagi yagona rahbarsiz. Do‘kon boshqaruvsiz qolmasligi uchun hisob o‘chirilmaydi.')),
            const SizedBox(height: 10),
            Text(tr('Davom etish uchun avval boshqa xodimni administrator yoki Ega qilib tayinlang, so‘ng bu yerga qaytib keling.'),
                style: const TextStyle(fontWeight: FontWeight.w600)),
            if (st.transferCandidates.isEmpty) ...[
              const SizedBox(height: 10),
              Text(tr('Do‘konda boshqa faol xodim yo‘q. Do‘konni yopish uchun qo‘llab-quvvatlash xizmatiga murojaat qiling.'),
                  style: TextStyle(fontSize: 13, color: AppColors.muted)),
            ],
          ] else
            Text(tr('Hisobni o‘chirish uchun shart bajarilmagan.')),
          // ⚠️  VORISI YO'Q EGA UCHUN CHIQISH YO'LI. Busiz u abadiy
          //     qulflanib qolardi: o'chirish bloklangan, boshqa yo'l yo'q.
          if (st.storeClosureAvailable) ...[
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                key: const Key('acct-del-close-store'),
                style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                    side: const BorderSide(color: AppColors.danger)),
                onPressed: _busy ? null : _closeStore,
                icon: const Icon(Icons.storefront_outlined),
                label: Text(tr('Do‘konni yopish')),
              ),
            ),
          ],
        ]),
      );

  /// PIN-only account: ask, don't erase. Shows the pending state honestly.
  Widget _requestForm(AccountDeletionState st) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppCard(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Hisobni o‘chirish so‘rovi'),
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(tr('Sizda parol yo‘q, shuning uchun o‘chirishni do‘kon egasi bajaradi. So‘rovingiz unga ko‘rinadi.')),
              if (st.requestPending) ...[
                const SizedBox(height: 12),
                Text(tr('So‘rovingiz yuborilgan — kutilmoqda.'),
                    key: const Key('acct-del-pending'),
                    style: const TextStyle(fontWeight: FontWeight.w700)),
              ],
            ]),
          ),
          const SizedBox(height: 16),
          if (!st.requestPending)
            FilledButton.icon(
              key: const Key('acct-del-request'),
              onPressed: _busy ? null : _request,
              icon: _busy
                  ? const SizedBox(
                      width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.outgoing_mail),
              label: Text(tr('O‘chirish so‘rovini yuborish')),
            ),
        ],
      );

  Widget _form(AccountDeletionState? st) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppCard(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Nima o‘chadi'),
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(tr('Ismingiz, telefon raqamingiz, parolingiz va PIN kodingiz o‘chiriladi. Bu amalni qaytarib bo‘lmaydi.')),
              const SizedBox(height: 14),
              Text(tr('Nima qoladi'),
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(tr('Savdo, kassa va ombor yozuvlari buxgalteriya hisobi uchun saqlanadi. Ularda ismingiz ko‘rsatilmaydi.')),
            ]),
          ),
          const SizedBox(height: 14),
          AppCard(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Tasdiqlash'),
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
              const SizedBox(height: 10),
              TextField(
                controller: _password,
                key: const Key('acct-del-password'),
                obscureText: true,
                autofillHints: const [AutofillHints.password],
                decoration: InputDecoration(labelText: tr('Joriy parolingiz')),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _confirm,
                key: const Key('acct-del-confirm'),
                decoration: InputDecoration(
                  labelText: trArgs('«{word}» so‘zini kiriting',
                      {'word': st?.confirmWord ?? ''}),
                ),
              ),
            ]),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            key: const Key('acct-del-submit'),
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: _busy ? null : _delete,
            icon: _busy
                ? const SizedBox(
                    width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.delete_forever_outlined),
            label: Text(tr('Hisobni butunlay o‘chirish')),
          ),
        ],
      );
}
