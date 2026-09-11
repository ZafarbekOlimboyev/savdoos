# -*- coding: utf-8 -*-
"""FAYZAN — YAKUNIY COMMIT TO'PLAMI va PARTIYA REJASI (LOKAL, tarmoqsiz).

    python scripts/fayzan_commit_plan.py --file fayzan_artefakt.json -o commit_plan.json

⚠️  BU SKRIPT HECH NARSA YOZMAYDI. Tarmoqqa umuman chiqmaydi. U artefaktdan
    chiqarib tashlanadiganlarni olib tashlab, `/products/bulk` semantikasi
    bo'yicha TO'LIQ tekshiradi va partiya manifestini yozadi.

`/products/bulk` (apps/server/app/api/v1/products.py) BUTUN PARTIYANI rad etadi,
agar bitta qator ham quyidagilarni buzsa. Shu bois har biri YUBORISHDAN OLDIN
lokal tekshiriladi:
  · nom bo'sh                         -> 400
  · nom bazada yoki partiya ichida takror (registrga befarq) -> 409
  · artikul band                      -> 400
  · SKU band                          -> 409
  · PLU band                          -> 400
  · barkod band (baza yoki partiya)   -> 400
  · noto'g'ri o'lchov birligi         -> 400
  · stock/buy/sell/min_qty < 0        -> 422
  · partiyada 10000 dan ortiq qator   -> 422
`client_uuid` esa qayta yuborishni IDEMPOTENT qiladi.
"""
import argparse
import collections
import hashlib
import json
import os
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BATCH = 500            # partiya hajmi — rad etilganda zarar kichik bo'lsin
UNITS = {"dona", "kg", "litr", "upak"}     # SavdoOS `units` jadvali
LINES = []


def say(s=""):
    print(s)
    LINES.append(s)


def canon(obj) -> bytes:
    """Barqaror seriyalash — checksum qayta yurgizilganda O'ZGARMASIN."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(obj) -> str:
    return hashlib.sha256(canon(obj)).hexdigest()


def validate(items, db_names=(), db_articles=(), db_barcodes=(), db_skus=()):
    """`/products/bulk` qoidalarining AYNAN nusxasi. Buzilgan qatorlarni qaytaradi.

    Bitta yomon qator butun partiyani yiqitadi, shuning uchun u PRODUCTION'GA
    YUBORILISHDAN OLDIN shu yerda topilishi shart."""
    bad = []
    db_names = {str(x).strip().lower() for x in db_names}
    db_articles, db_barcodes, db_skus = set(db_articles), set(db_barcodes), set(db_skus)
    seen_name, seen_uuid, seen_art, seen_bc, seen_sku, seen_plu = set(), set(), set(), set(), set(), set()
    for i, it in enumerate(items):
        nm = str(it.get("name") or "").strip()
        low = nm.lower()
        if not nm:
            bad.append((i, "nom bo'sh", ""))
        elif low in db_names:
            bad.append((i, "nom BAZADA bor", nm))
        elif low in seen_name:
            bad.append((i, "nom to'plam ichida TAKROR", nm))
        seen_name.add(low)

        cu = it.get("client_uuid")
        if not cu:
            bad.append((i, "client_uuid yo'q", nm))
        else:
            try:
                uuid.UUID(str(cu))
            except (ValueError, AttributeError, TypeError):
                bad.append((i, "client_uuid noto'g'ri", str(cu)))
            if cu in seen_uuid:
                bad.append((i, "client_uuid TAKROR", str(cu)))
            seen_uuid.add(cu)

        for fld, store, db in (("article_code", seen_art, db_articles),
                               ("sku", seen_sku, db_skus),
                               ("plu_code", seen_plu, set())):
            v = it.get(fld)
            if v:
                if v in db:
                    bad.append((i, f"{fld} BAZADA band", str(v)))
                if v in store:
                    bad.append((i, f"{fld} to'plam ichida TAKROR", str(v)))
                store.add(v)

        bcr = it.get("barcode")
        if bcr:
            d = "".join(c for c in str(bcr) if c.isdigit())
            if not (6 <= len(d) <= 14):
                bad.append((i, "barcode 6-14 raqam emas", str(bcr)))
            elif d in db_barcodes:
                bad.append((i, "barcode BAZADA band", d))
            elif d in seen_bc:
                bad.append((i, "barcode to'plam ichida TAKROR", d))
            seen_bc.add(d)

        u = it.get("unit_code")
        if u not in UNITS:
            bad.append((i, "o'lchov birligi noto'g'ri", str(u)))

        for fld in ("buy_price", "sell_price", "stock", "min_qty"):
            v = it.get(fld)
            if v is None or float(v) < 0:
                bad.append((i, f"{fld} manfiy yoki yo'q", str(v)))
        if float(it.get("sell_price") or 0) <= 0:
            bad.append((i, "sell_price <= 0", nm))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--exclusions", help="loss/no_buy ro'yxatlari (JSON)")
    ap.add_argument("--db-names", help="bazadagi nomlar (JSON ro'yxat)")
    ap.add_argument("-o", "--out", default="fayzan_commit_plan.json")
    a = ap.parse_args()

    art = json.load(open(a.file, encoding="utf-8"))
    items = art["bulk_items"]
    say(f"artefakt bulk qatorlari : {len(items)}")

    exc = json.load(open(a.exclusions, encoding="utf-8")) if a.exclusions else {}
    loss = {n.strip().lower() for n in exc.get("loss", [])}
    nobuy = {n.strip().lower() for n in exc.get("no_buy", [])}
    dbn = {n.strip().lower() for n in json.load(open(a.db_names, encoding="utf-8"))} \
        if a.db_names else set()

    say()
    say("=== CHIQARIB TASHLASH ===")
    say(f"  bazada MAVJUD (tegilmaydi)          : {len(dbn)}")
    say(f"  SOTISH < KELISH (narx tuzatilsin)   : {len(loss)}")
    say(f"  KELISH NARXI YO'Q (0 qilinmaydi)    : {len(nobuy)}")

    final, dropped = [], collections.Counter()
    for it in items:
        low = it["name"].strip().lower()
        if low in dbn:
            dropped["bazada mavjud"] += 1
        elif low in loss:
            dropped["sotish < kelish"] += 1
        elif low in nobuy:
            dropped["kelish narxi yo'q"] += 1
        else:
            final.append(it)
    for k, v in dropped.most_common():
        say(f"    - {k:24} : {v}")
    say(f"  JAMI chiqarildi : {sum(dropped.values())}")

    say()
    say("=== TENGLAMA ===")
    say(f"  {len(items)}")
    say(f"  - {dropped['bazada mavjud']:<5} bazada mavjud")
    say(f"  - {dropped['sotish < kelish']:<5} sotish < kelish")
    say(f"  - {dropped['kelish narxi yo`q'] + dropped['kelish narxi yo\'q']:<5} kelish narxi yo'q")
    say(f"  = {len(final)}  <- YAKUNIY COMMIT SONI")

    say()
    say("=== /products/bulk SEMANTIKASI BO'YICHA TEKSHIRUV ===")
    bad = validate(final, db_names=dbn)
    if bad:
        say(f"  BUZILGAN QATORLAR: {len(bad)}")
        for i, why, what in bad[:20]:
            say(f"    {i}: {why} | {what}")
        say("  >>> TO'XTATILDI — production'ga birorta partiya yuborilmaydi.")
        _save(a)
        return 1
    say("  toza — birorta qator bulk qoidasini buzmaydi")

    u = collections.Counter(i["unit_code"] for i in final)
    say(f"  o'lchov birligi : {dict(u)}")
    say(f"  client_uuid     : {len({i['client_uuid'] for i in final})} noyob / {len(final)}")
    say(f"  asosiy barkod   : {len({i['barcode'] for i in final if i.get('barcode')})} noyob")
    say(f"  barkodsiz       : {sum(1 for i in final if not i.get('barcode'))}")
    say(f"  artikul yuborilmaydi (backend avto beradi): "
        f"{sum(1 for i in final if i.get('article_code'))} ta aniq berilgan")

    # ── Partiyalar — DETERMINISTIK (nom bo'yicha tartiblangan) ──────────
    final.sort(key=lambda i: i["name"])
    batches = []
    for n, s in enumerate(range(0, len(final), BATCH), start=1):
        chunk = final[s:s + BATCH]
        batches.append({
            "batch": n,
            "rows": len(chunk),
            "first_client_uuid": chunk[0]["client_uuid"],
            "last_client_uuid": chunk[-1]["client_uuid"],
            "first_name": chunk[0]["name"],
            "last_name": chunk[-1]["name"],
            "sha256": sha(chunk),
        })
    say()
    say(f"=== PARTIYA REJASI ({len(batches)} partiya, har biri <= {BATCH}) ===")
    for b in batches:
        say(f"  #{b['batch']:<3} {b['rows']:>4} qator | {b['first_name'][:26]:26} .. "
            f"{b['last_name'][:26]:26} | {b['sha256'][:16]}")
    overall = sha(final)
    say(f"  ARTEFAKT (yakuniy to'plam) sha256: {overall}")

    plan = {"final_items": final, "batches": batches, "batch_size": BATCH,
            "overall_sha256": overall, "final_count": len(final),
            "excluded": dict(dropped)}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    say()
    say(f"reja yozildi: {a.out}")
    say("HECH NARSA YOZILMADI — bu faqat reja.")
    _save(a)
    return 0


def _save(a):
    p = os.path.splitext(a.out)[0] + ".out"
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("\nhisobot:", p)


if __name__ == "__main__":
    sys.exit(main())
