# -*- coding: utf-8 -*-
"""
1С eksportlarini SavdoOS import formatiga aylantiruvchi konvertor.

Bir yoki bir nechta .xls/.xlsx faylni o'qiydi (nomenklatura + narx + qoldiq —
alohida bo'lsa ham), ustunlarni AVTOMATIK aniqlaydi (kirill/uzbek sarlavhalar),
fayllarni barkod yoki nom bo'yicha ulaydi va SavdoOS /products/import/commit
uchun tayyor rows JSON chiqaradi. Ixtiyoriy: to'g'ridan-to'g'ri serverga yuboradi.

Ishlatish:
  # faqat JSON chiqarish (bir yoki bir nechta fayl):
  python tools/import_1c.py "katalog.xls" "narxlar.xls" "qoldiq.xls" -o rows.json

  # ko'rib chiqish (birinchi 10 qator + ustun-xaritasi):
  python tools/import_1c.py "katalog.xls" --preview

  # serverga yuklash:
  python tools/import_1c.py rows_manbalari... --post \
     --url https://savdoos-production.up.railway.app/api/v1 \
     --phone +998901234567 --password savdo1234

Ustun-aniqlash sarlavha kalit so'zlariga tayanadi (pastdagi KEYS). Agar avtomatik
xato aniqlasa — --map bilan qo'lda ko'rsatish mumkin:  --map name=Владелец,barcode=Штрихкод
"""
import argparse
import json
import re
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas kerak:  pip install pandas xlrd openpyxl")

# Sarlavha kalit so'zlari — SPESIFIKdan umumiyga (birinchi mos kelgani yutadi).
KEYS = {
    "barcode": ["штрихкод", "штрих-код", "штрих код", "штрих", "barcode", "ean", "shtrix", "штрихкоды"],
    "article": ["артикул", "код товара", "sku", "artikul", "код"],
    "stock":   ["конечный остаток", "остаток на складе", "остаток", "кол-во", "количество", "наличие", "qoldiq", "soni", "остатки"],
    "buy":     ["цена закупки", "закупочная цена", "закупочная", "себестоимость", "закупка", "приход", "kelish narxi", "оптовая", "оптовая цена"],
    "sell":    ["розничная цена", "цена продажи", "цена розничная", "розничная", "цена реализации", "sotish narxi", "продажная", "продажа", "цена"],
    "name":    ["наименование товара", "наименование", "номенклатура", "название", "товар", "владелец", "mahsulot", "nomi", "tovar", "product", "name"],
    "category": ["категория товара", "категория", "группа товаров", "группа", "kategoriya", "guruh"],
}
TARGET_ORDER = ["barcode", "article", "stock", "buy", "sell", "category", "name"]


def _read_any(path):
    """Har qanday .xls/.xlsx (OLE yoki HTML-niqoblangan) ni DataFrame(header yo'q) qilib o'qiydi."""
    try:
        return pd.read_excel(path, sheet_name=0, header=None, dtype=object)
    except Exception:
        pass
    try:
        tabs = pd.read_html(path)
        if tabs:
            return tabs[0]
    except Exception as e:
        raise SystemExit(f"'{path}' o'qib bo'lmadi: {e}")
    raise SystemExit(f"'{path}' — formatni aniqlab bo'lmadi")


def _norm(s):
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _kw_in(kw, text):
    """Kalit so'z matnда BUTUN so'z sifatida bormi (штрихкода ichidagi 'код' mos kelmasin)."""
    return re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text) is not None


def _find_header_row(df, scan=25):
    """Sarlavha qatorini topadi — kalit so'zlar eng ko'p uchraydigan qator."""
    all_kw = [k for lst in KEYS.values() for k in lst]
    best, best_score = 0, 0
    for i in range(min(scan, len(df))):
        cells = [_norm(x) for x in df.iloc[i].tolist() if str(x) != "nan"]
        score = sum(1 for c in cells for kw in all_kw if _kw_in(kw, c))
        if score > best_score:
            best_score, best = score, i
    return best if best_score >= 1 else 0


def _map_columns(headers, manual):
    """headers: {col_index: normalized_header}. -> {target: col_index}"""
    mapping = {}
    used = set()
    # 1) qo'lda ko'rsatilgan
    for tgt, hdr in (manual or {}).items():
        for ci, h in headers.items():
            if _norm(hdr) == h and ci not in used:
                mapping[tgt] = ci
                used.add(ci)
                break
    # 2) avtomatik — spesifik kalitdan boshlab
    for tgt in TARGET_ORDER:
        if tgt in mapping:
            continue
        for kw in KEYS[tgt]:
            hit = None
            for ci, h in headers.items():
                if ci in used:
                    continue
                if _kw_in(kw, h):
                    hit = ci
                    break
            if hit is not None:
                mapping[tgt] = hit
                used.add(hit)
                break
    return mapping


def _to_num(v):
    if v is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(v)).replace(",", ".")
    if s in ("", ".", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_file(path, manual=None, preview=False):
    raw = _read_any(path)
    hr = _find_header_row(raw)
    headers = {ci: _norm(raw.iloc[hr, ci]) for ci in range(raw.shape[1]) if str(raw.iloc[hr, ci]) != "nan"}
    mapping = _map_columns(headers, manual)
    body = raw.iloc[hr + 1:].reset_index(drop=True)

    print(f"\n[{path.split(chr(92))[-1].split('/')[-1]}]  sarlavha qatori: {hr}")
    print("  Ustun xaritasi:")
    for tgt in TARGET_ORDER:
        if tgt in mapping:
            print(f"    {tgt:9} <- ustun {mapping[tgt]}  «{raw.iloc[hr, mapping[tgt]]}»")
    miss = [t for t in ("name",) if t not in mapping]
    if miss:
        print(f"  ! DIQQAT: {miss} topilmadi — --map bilan ko'rsating")

    rows = []
    for _, r in body.iterrows():
        rec = {}
        for tgt, ci in mapping.items():
            val = r.iloc[ci] if ci < len(r) else None
            if tgt in ("stock", "buy", "sell"):
                rec[tgt] = _to_num(val)
            else:
                rec[tgt] = None if str(val) == "nan" else str(val).strip()
        if rec.get("name"):
            rows.append(rec)
    if preview:
        print(f"  Jami satr: {len(rows)}. Birinchi 8:")
        for rr in rows[:8]:
            print("   ", {k: v for k, v in rr.items() if v not in (None, "")})
    return rows


def _key(rec):
    """Ulash kaliti: barkod > artikul > normallashgan nom."""
    bc = re.sub(r"\D", "", rec.get("barcode") or "")
    if len(bc) >= 6:
        return "bc:" + bc
    art = (rec.get("article") or "").strip().lower()
    if art:
        return "art:" + art
    return "nm:" + _norm(rec.get("name") or "")


def merge(files_rows):
    """Bir nechta fayldan kelgan yozuvlarni kalit bo'yicha birlashtiradi."""
    merged = {}
    order = []
    for rows in files_rows:
        for rec in rows:
            k = _key(rec)
            if k not in merged:
                merged[k] = dict(rec)
                order.append(k)
            else:
                for f, v in rec.items():
                    if v not in (None, "") and merged[k].get(f) in (None, ""):
                        merged[k][f] = v
    return [merged[k] for k in order]


def to_import_rows(records):
    """SavdoOS /products/import/commit formati."""
    out = []
    for r in records:
        row = {"name": r["name"]}
        if r.get("barcode"):
            bc = re.sub(r"\D", "", r["barcode"])
            if bc:
                row["barcode"] = bc
        if r.get("article"):
            row["article"] = r["article"]
        if r.get("category"):
            row["category"] = r["category"]
        if r.get("buy") is not None:
            row["buy"] = round(r["buy"], 2)
        if r.get("sell") is not None:
            row["sell"] = round(r["sell"], 2)
        if r.get("stock") is not None:
            row["stock"] = round(r["stock"], 3)
        out.append(row)
    return out


def post_rows(rows, url, phone, password, batch=1000):
    import urllib.request
    def call(path, body, headers=None):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode() or "null")
    tok = call("/auth/login/password", {"phone": phone, "password": password})["access_token"]
    H = {"Authorization": "Bearer " + tok}
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        res = call("/products/import/commit", {"rows": chunk}, H)
        total += len(chunk)
        print(f"  yuklandi {total}/{len(rows)} ...  javob: {str(res)[:120]}")
    print(f"TUGADI: {total} mahsulot yuborildi.")


def main():
    ap = argparse.ArgumentParser(description="1С -> SavdoOS import konvertori")
    ap.add_argument("files", nargs="+", help=".xls/.xlsx fayllar (katalog/narx/qoldiq)")
    ap.add_argument("-o", "--out", help="natija JSON fayli")
    ap.add_argument("--preview", action="store_true", help="faqat ko'rib chiqish (yuklamaydi)")
    ap.add_argument("--map", help="qo'lda ustun: name=Владелец,barcode=Штрихкод,sell=Цена")
    ap.add_argument("--post", action="store_true", help="serverga yuklash")
    ap.add_argument("--url", default="https://savdoos-production.up.railway.app/api/v1")
    ap.add_argument("--phone")
    ap.add_argument("--password")
    a = ap.parse_args()

    manual = {}
    if a.map:
        for pair in a.map.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                manual[k.strip()] = v.strip()

    files_rows = [load_file(f, manual, a.preview) for f in a.files]
    records = merge(files_rows) if len(files_rows) > 1 else files_rows[0]
    rows = to_import_rows(records)

    # xulosa
    n = len(rows)
    with_bc = sum(1 for r in rows if r.get("barcode"))
    with_sell = sum(1 for r in rows if "sell" in r)
    with_stock = sum(1 for r in rows if "stock" in r)
    print(f"\n=== NATIJA ===")
    print(f"Mahsulot: {n}")
    print(f"  barkodli:  {with_bc}  ({with_bc*100//max(n,1)}%)")
    print(f"  sotish narxli: {with_sell}  ({with_sell*100//max(n,1)}%)")
    print(f"  qoldiqli:  {with_stock}  ({with_stock*100//max(n,1)}%)")
    if with_sell == 0:
        print("  ! Narx yo'q — sotish uchun narx fayli ham kerak (Прайс-лист)")
    if with_stock == 0:
        print("  ! Qoldiq yo'q — ombor uchun qoldiq fayli ham kerak (Остатки товаров)")

    if a.preview:
        return
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f, ensure_ascii=False, indent=1)
        print(f"Yozildi: {a.out}")
    if a.post:
        if not (a.phone and a.password):
            sys.exit("--post uchun --phone va --password kerak")
        post_rows(rows, a.url, a.phone, a.password)


if __name__ == "__main__":
    main()
