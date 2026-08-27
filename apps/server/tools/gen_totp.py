"""Vendor portal 2FA (TOTP) uchun sir yaratish.

Ishlatish:
    python tools/gen_totp.py "SavdoOS Vendor"

Chiqadi:
  1) base32 sir  → Railway'да  VENDOR_TOTP_SECRET  env'iga qo'ying.
  2) otpauth:// URI → Google Authenticator / Authy'да QR sifatida qo'shing
     (yoki sirni qo'lda kiriting).

Sir o'rnatilgach portal (/api/v1/admin/portal) kirishда kalitdan tashqari 6 xonali
kod ham so'raydi. Sir bo'sh bo'lsa — 2FA o'chiq (faqat kalit).

Hech qanday tashqi kutubxona kerak emas (RFC 6238, standart kutubxona).
"""
import base64
import secrets
import sys
import urllib.parse


def main() -> int:
    try:  # Windows konsoli (cp1252) Unicode'ни buzmasin
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    issuer = sys.argv[1] if len(sys.argv) > 1 else "SavdoOS Vendor"
    # 20 bayt (160 bit) tasodifiy sir — RFC 6238 tavsiyasi
    raw = secrets.token_bytes(20)
    b32 = base64.b32encode(raw).decode().rstrip("=")
    label = urllib.parse.quote("SavdoOS:vendor")
    uri = (f"otpauth://totp/{label}?secret={b32}"
           f"&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits=6&period=30")
    print("VENDOR_TOTP_SECRET =", b32)
    print()
    print("otpauth URI (QR uchun):")
    print(" ", uri)
    print()
    print("Keyingi qadam: Railway -> savdoos -> Variables -> VENDOR_TOTP_SECRET = yuqoridagi sir.")
    print("Authenticator'да shu sirni qo'shing. Portal kirishда 6 xonali kod so'raydi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
