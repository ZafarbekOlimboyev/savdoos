import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../api/money_api.dart';
import '../errors.dart';
import '../l10n.dart';
import '../permissions.dart';
import '../theme.dart';
import '../ui/ui.dart';

/// Phone pre-check for UX only (the server's `require_phone` decides):
/// digits after an optional `+`; `+996` / `+998` numbers have 12 digits,
/// others 10–15. Empty is allowed (the phone is optional).
bool phoneLooksValid(String raw) {
  final digits = raw.replaceAll(RegExp(r'\D'), '');
  if (digits.isEmpty) return raw.trim().isEmpty;
  if (digits.startsWith('996') || digits.startsWith('998')) return digits.length == 12;
  return digits.length >= 10 && digits.length <= 15;
}

/// Server texts that belong to the phone field (shown inline there).
bool _isPhoneError(ApiException e) {
  final t = ApiException.flatten(e.detail) ?? '';
  return t.startsWith("Telefon raqami noto'g'ri") || t == "Bu telefon do'konda allaqachon band";
}

String _phoneErrorText(ApiException e) {
  final t = ApiException.flatten(e.detail) ?? '';
  if (t.startsWith("Telefon raqami noto'g'ri")) return tr('Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456');
  return userMessage(e);
}

/// Create (no [customer]) or edit a customer.
///
/// * create — `POST /customers` with a `client_uuid` bound to the draft, so a
///   retry after a lost answer returns the SAME customer (never a duplicate);
/// * edit — `PATCH /customers/{id}` with the changed fields only.
///
/// Pops with the saved [CustomerRow] after a 2xx.
class CustomerEditScreen extends StatefulWidget {
  /// Creates the screen.
  const CustomerEditScreen({super.key, this.customer});

  /// The customer to edit; null creates a new one.
  final CustomerRow? customer;

  @override
  State<CustomerEditScreen> createState() => _CustomerEditScreenState();
}

class _CustomerEditScreenState extends State<CustomerEditScreen> {
  late final TextEditingController _name = TextEditingController(text: widget.customer?.fullName ?? '');
  late final TextEditingController _phone = TextEditingController(text: widget.customer?.phone ?? '');
  final _address = TextEditingController();
  final _nameFocus = FocusNode();
  final _phoneFocus = FocusNode();
  final DraftUuid _key = DraftUuid();
  bool _tried = false;
  bool _busy = false;
  bool _unknown = false;
  Object? _error;
  String? _phoneServerError;

  bool get _isEdit => widget.customer != null;

  /// Inputs are frozen while saving and after a lost CREATE answer: the retry
  /// must send the SAME draft (same `client_uuid`), never a changed one.
  bool get _locked => _busy || (_unknown && !_isEdit);

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _address.dispose();
    _nameFocus.dispose();
    _phoneFocus.dispose();
    super.dispose();
  }

  String? get _nameError => _name.text.trim().isEmpty ? tr('Ismni kiriting') : null;

  String? get _phoneError {
    if (_phoneServerError != null) return _phoneServerError;
    return phoneLooksValid(_phone.text) ? null : tr('Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456');
  }

  bool get _changed {
    final c = widget.customer;
    if (c == null) return true;
    return _name.text.trim() != c.fullName || _phone.text.trim() != (c.phone ?? '');
  }

  Future<void> _save() async {
    setState(() => _tried = true);
    if (_nameError != null) {
      _nameFocus.requestFocus();
      return;
    }
    if (_phoneError != null) {
      _phoneFocus.requestFocus();
      return;
    }
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final CustomerRow saved;
      final c = widget.customer;
      if (c == null) {
        final draft = {'n': _name.text.trim(), 'p': _phone.text.trim(), 'a': _address.text.trim()};
        saved = await MoneyApi.createCustomer(
          fullName: _name.text.trim(),
          phone: _phone.text,
          address: _address.text,
          clientUuid: _key.forDraft(draft),
        );
      } else {
        saved = await MoneyApi.editCustomer(
          c.id,
          fullName: _name.text.trim() != c.fullName ? _name.text.trim() : null,
          phone: _phone.text.trim() != (c.phone ?? '') ? _phone.text.trim() : null,
        );
      }
      if (!mounted) return;
      Navigator.of(context).pop(saved);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _unknown = isConnectivityError(e);
        if (e is ApiException && _isPhoneError(e)) {
          _phoneServerError = _phoneErrorText(e);
          _error = null;
          _phoneFocus.requestFocus();
        } else {
          _error = e;
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final allowed = Perm.allows(_isEdit ? 'customers.edit' : 'customers.create');
    return Scaffold(
      appBar: AppBar(title: Text(_isEdit ? tr('Mijozni tahrirlash') : tr('Yangi mijoz'))),
      body: !allowed
          ? EmptyState(
              key: const Key('no-access'),
              icon: Icons.lock_outline,
              text: Perm.reason(_isEdit ? 'customers.edit' : 'customers.create'),
            )
          : Column(children: [
              const ConnectivityBanner(),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(kGutter, 12, kGutter, 24),
                  children: [
                    TextField(
                      key: const Key('customer-name'),
                      controller: _name,
                      focusNode: _nameFocus,
                      enabled: !_locked,
                      autofocus: !_isEdit,
                      textCapitalization: TextCapitalization.words,
                      textInputAction: TextInputAction.next,
                      maxLength: 200,
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        labelText: '${tr('Ism familiya')} *',
                        errorText: _tried ? _nameError : null,
                        counterText: '',
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      key: const Key('customer-phone'),
                      controller: _phone,
                      focusNode: _phoneFocus,
                      enabled: !_locked,
                      keyboardType: TextInputType.phone,
                      textInputAction: _isEdit ? TextInputAction.done : TextInputAction.next,
                      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9+ ()-]'))],
                      onChanged: (_) => setState(() => _phoneServerError = null),
                      decoration: InputDecoration(
                        labelText: tr('Telefon (ixtiyoriy)'),
                        hintText: '+996 700 123 456',
                        errorText: (_tried || _phoneServerError != null) ? _phoneError : null,
                        errorMaxLines: 2,
                        prefixIcon: Icon(Icons.phone_outlined, color: AppColors.muted),
                      ),
                    ),
                    if (!_isEdit) ...[
                      const SizedBox(height: 14),
                      TextField(
                        key: const Key('customer-address'),
                        controller: _address,
                        enabled: !_locked,
                        textInputAction: TextInputAction.done,
                        maxLength: 300,
                        decoration: InputDecoration(
                          labelText: tr('Manzil (ixtiyoriy)'),
                          counterText: '',
                          prefixIcon: Icon(Icons.place_outlined, color: AppColors.muted),
                        ),
                      ),
                    ],
                    if (_error != null) ...[
                      const SizedBox(height: 14),
                      _unknown
                          ? ErrorBanner(
                              key: const Key('customer-unknown'),
                              severity: BannerSeverity.warning,
                              message: _isEdit
                                  ? tr('Server javobi kelmadi — o‘zgarish saqlangan-saqlanmagani noma’lum. Qayta saqlash xavfsiz.')
                                  : tr('Server javobi kelmadi — mijoz yaratilgan-yaratilmagani noma’lum. '
                                      'Qayta saqlash xavfsiz: mijoz ikki marta yaratilmaydi.'),
                            )
                          : ErrorBanner(key: const Key('customer-error'), error: _error),
                    ],
                  ],
                ),
              ),
              StickyActionBar(
                label: _unknown ? tr('Qayta saqlash') : tr('Saqlash'),
                icon: Icons.check,
                busy: _busy,
                enabled: _changed,
                disabledReason: tr('O‘zgarish yo‘q'),
                onPressed: _save,
              ),
            ]),
    );
  }
}
