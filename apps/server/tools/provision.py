"""Vendor CLI — mijozga akkaunt ochish / parol tiklash.

Ishlatish (apps/server da):
  .venv\\Scripts\\python tools\\provision.py new --name "Aziz Market" --code aziz \\
      --owner "Aziz Karimov" --phone "+996700111222" --password "maxfiy123" --plan start --pin 1234
  .venv\\Scripts\\python tools\\provision.py reset --phone "+996700111222" --password "yangi123"

Server: --server bilan (standart: Railway prod). Kalit: VENDOR_ADMIN_KEY env yoki --key.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "https://savdoos-production.up.railway.app"


def call(server: str, key: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        server.rstrip("/") + "/api/v1/admin" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Vendor-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", e.reason)
        except Exception:  # noqa: BLE001
            detail = e.reason
        print(f"[XATO {e.code}] {detail}")
        sys.exit(1)


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server", default=os.environ.get("SAVDOOS_SERVER", DEFAULT_SERVER))
    common.add_argument("--key", default=os.environ.get("VENDOR_ADMIN_KEY", ""))

    ap = argparse.ArgumentParser(description="SavdoOS vendor: mijoz akkauntlari", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="yangi mijoz (do'kon + ega akkaunti)", parents=[common])
    n.add_argument("--name", required=True, help="do'kon nomi")
    n.add_argument("--code", required=True, help="do'kon kodi (noyob, lotin kichik harf)")
    n.add_argument("--owner", required=True, help="ega F.I.Sh.")
    n.add_argument("--phone", required=True, help="ega telefoni (login)")
    n.add_argument("--password", required=True, help="boshlang'ich parol (>=6)")
    n.add_argument("--plan", default="start", choices=["start", "start+", "business"])
    n.add_argument("--pin", default=None, help="ega uchun kassa PIN (ixtiyoriy, >=4 raqam)")
    n.add_argument("--branch", default="Asosiy filial")
    n.add_argument("--currency", default="UZS")

    r = sub.add_parser("reset", help="ega parolini tiklash", parents=[common])
    r.add_argument("--phone", required=True)
    r.add_argument("--password", required=True, help="yangi parol (>=6)")

    a = ap.parse_args()
    if not a.key:
        print("[XATO] Vendor kaliti yo'q: VENDOR_ADMIN_KEY env yoki --key bering")
        sys.exit(1)

    if a.cmd == "new":
        out = call(a.server, a.key, "/companies", {
            "company_name": a.name, "company_code": a.code, "owner_name": a.owner,
            "owner_phone": a.phone, "owner_password": a.password, "plan": a.plan,
            "owner_pin": a.pin, "branch_name": a.branch, "currency": a.currency,
        })
        print("[OK] Mijoz ochildi:")
        print(f"  Do'kon kodi : {out['company_code']}")
        print(f"  Ega telefoni: {out['owner_phone']}")
        print(f"  Tarif       : {out['plan']}")
        print("Mijozga bering: telefon + parol (Manager), do'kon kodi + PIN (POS kassirlar).")
    else:
        out = call(a.server, a.key, "/reset-password", {"owner_phone": a.phone, "new_password": a.password})
        print(f"[OK] Parol tiklandi: {out['owner_phone']}")


if __name__ == "__main__":
    main()
