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
import unicodedata

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas kerak:  pip install pandas xlrd openpyxl")

# Sarlavha kalit so'zlari — SPESIFIKdan umumiyga (birinchi mos kelgani yutadi).
KEYS = {
    "barcode": ["штрихкод", "штрих-код", "штрих код", "штрих", "barcode", "ean", "shtrix", "штрихкоды"],
    "article": ["артикул", "код товара", "sku", "artikul", "код"],
    "stock":   ["конечный остаток", "остаток на складе", "остаток", "кол-во", "количество", "наличие", "qoldiq", "soni", "остатки"],
    # «Цена поставщика» — Fayzan 1С eksportida kelish narxi AYNAN shunday ataladi.
    # U yo'q edi, shu bois kelish narxi ustuni HECH QACHON topilmasdi: `sell` kaliti
    # «цена» ni ushlab, «Розничная цена» ni olardi, «Цена поставщика» esa egasiz qolardi
    # va butun import buy=0 bilan ketardi. Ro'yxat OXIRIGA qo'shildi — mavjud, aniqroq
    # kalitlarning ustuvorligi saqlanadi.
    "buy":     ["цена закупки", "закупочная цена", "закупочная", "себестоимость", "закупка", "приход", "kelish narxi", "оптовая", "оптовая цена", "цена поставщика", "поставщик"],
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


# ── 1С nom katakchasi: «Номенклатура, Ед. изм., Упаковка» ────────────────────
#
# 1С nom ustuniga bir nechta maydonni BITTA katakchaga «, » bilan qo'shib yozadi.
# Sarlavhaning o'zi qaysi maydonlar borligini aytadi:
#     sena.xls    -> «Номенклатура, Упаковка»              (birlik YO'Q)
#     astatka.xls -> «Номенклатура, Ед. изм., Упаковка»    (birlik BOR)
# Shu bois astatka qatorlari « 7Up 450ml, шт, », sena qatorlari esa « 7Up 450ml, »
# ko'rinishida keladi. Ilgari ulash kaliti faqat lower()+probel edi — natijada bu
# ikkalasi HECH QACHON ulanmasdi: 8285 + 6382 = 14667 qator, ya'ni har bir mahsulot
# IKKI MARTA, biri narxsiz, biri qoldiqsiz. Kesishma nolga teng edi.
#
# ⚠️  O'nlik vergul (0,125) dan keyin PROBEL yo'q — shu bois «, » bo'yicha bo'lish
#     xavfsiz. Nomning o'zida «, » uchraydigan 8 ta qator ham to'g'ri ishlaydi,
#     chunki faqat OXIRGI bo'lak birlik sifatida olib tashlanadi.
NAME_SEP = ", "
UNIT_TOKENS = {"шт", "кг", "л", "гр", "г", "мл", "уп", "упак", "пар", "компл", "м", "см"}


def name_fields(header_cell) -> list[str]:
    """Sarlavhadan nom katakchasining maydonlari: «Номенклатура, Ед. изм., Упаковка»."""
    return [p.strip() for p in str(header_cell or "").split(NAME_SEP) if p.strip()]


def header_has_unit(header_cell) -> bool:
    """Sarlavha «Ед. изм.» (o'lchov birligi) maydonini e'lon qilganmi?"""
    return any("изм" in p.lower() for p in name_fields(header_cell))


def split_1c_name(cell, has_unit: bool) -> tuple[str, str | None, int]:
    """Nom katakchasini (nom, birlik, XOM_bo'laklar_soni) ga ajratadi.

    XOM bo'laklar soni (hech narsa olib tashlanmasdan OLDINGI) qaytariladi, chunki
    1С guruh/jami qatorlari («Магазин Файзан», «Итого», «Десерты», «Быстрые Тавары»)
    nom maydonining qolgan qismini TO'LDIRMAYDI — ularda ajratgich umuman yo'q.
    Nom bo'yicha qora ro'yxat tuzish o'rniga TUZILISH bo'yicha ajratamiz: qora
    ro'yxat keyingi eksportда paydo bo'ladigan yangi guruh nomini o'tkazib yuborardi.
    """
    parts = str(cell).split(NAME_SEP)
    raw_parts = len(parts)
    while parts and not parts[-1].strip():
        parts.pop()                                  # bo'sh «Упаковка»
    unit = None
    if has_unit and len(parts) >= 2 and parts[-1].strip().lower() in UNIT_TOKENS:
        unit = parts.pop().strip().lower()           # «Ед. изм.»
    # ⚠️  ICHKI PROBELLAR HAM SIQILADI. 1С eksportida 532 ta nomda qo'sh probel bor
    #     («…Премиум №2␣␣600г»). Backend dublikatni nom SATRI bo'yicha aniqlaydi, ya'ni
    #     «№2␣600г» va «№2␣␣600г» IKKI BOSHQA mahsulot bo'lib kiradi — ko'zga bir xil
    #     ko'rinadigan, lekin qidiruvda topilmaydigan dublikat. Ulash kaliti (`norm_key`)
    #     baribir siqadi, shu bois KO'RINADIGAN nom ham u bilan IZCHIL bo'lishi shart.
    return re.sub(r"\s+", " ", NAME_SEP.join(parts)).strip(), unit, raw_parts


def norm_key(name) -> str:
    """Fayllar o'rtasidagi ULASH KALITI — registr va probeldan xoli."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name))).strip().casefold()


def _digits(v) -> str | None:
    """Backend qoidasi: faqat raqamlar, uzunlik 6-14. Aks holda barkod YO'Q."""
    d = re.sub(r"\D", "", str(v or ""))
    return d if 6 <= len(d) <= 14 else None


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

    # Nom katakchasining TUZILISHI sarlavhadan o'qiladi (yuqoridagi izohga qarang).
    name_hdr = raw.iloc[hr, mapping["name"]] if "name" in mapping else ""
    has_unit = header_has_unit(name_hdr)
    fields = name_fields(name_hdr)
    # Guruh/jami qatorlarida nom maydonining qolgan bo'laklari umuman yo'q.
    min_parts = max(1, len(fields) - 1)
    if preview and len(fields) > 1:
        print(f"  Nom katakchasi: {fields} | birlik maydoni: {'BOR' if has_unit else 'yo`q'}"
              f" | guruh qatori chegarasi: xom bo'laklar <{min_parts}")

    rows, skipped_group = [], 0
    for _, r in body.iterrows():
        rec = {}
        raw_name = None
        for tgt, ci in mapping.items():
            val = r.iloc[ci] if ci < len(r) else None
            if tgt in ("stock", "buy", "sell"):
                rec[tgt] = _to_num(val)
            else:
                if tgt == "name":
                    # ⚠️  XOM holda saqlaymiz: 1С «, » bilan ajratadi va OXIRGI maydon
                    #     («Упаковка») ko'pincha BO'SH — ya'ni katakcha «…, шт, » bo'lib
                    #     PROBEL bilan tugaydi. Avval strip() qilinsa o'sha probel yo'qoladi
                    #     va oxirgi ajratgich «, » topilmay qoladi.
                    raw_name = None if str(val) == "nan" else str(val)
                rec[tgt] = None if str(val) == "nan" else str(val).strip()
        if not raw_name or not rec.get("name"):
            continue
        nm, unit, nparts = split_1c_name(raw_name, has_unit)
        # Guruh/jami qatori: tuzilish yo'q, yoki birlik e'lon qilingan faylda birlik yo'q.
        if not nm or nparts < min_parts or (has_unit and unit is None):
            skipped_group += 1     # «Магазин Файзан», «Итого», «Десерты» — jami qatorlari
            if preview and skipped_group <= 8:
                print(f"    guruh qatori tashlandi: {raw_name.strip()[:48]!r}")
            continue
        rec["name"] = nm
        if unit:
            rec["unit"] = unit
        rows.append(rec)
    if skipped_group:
        print(f"  guruh/jami qatorlari tashlandi: {skipped_group}")
    if preview:
        print(f"  Jami satr: {len(rows)}. Birinchi 8:")
        for rr in rows[:8]:
            print("   ", {k: v for k, v in rr.items() if v not in (None, "")})
    return rows


def _key(rec, axis="auto"):
    """Ulash kaliti. `axis` — barcha fayllar uchun BITTA o'q (pastga qarang)."""
    if axis == "barcode":
        bc = _digits(rec.get("barcode"))
        return "bc:" + bc if bc else "nm:" + norm_key(rec.get("name") or "")
    if axis == "article":
        art = (rec.get("article") or "").strip().lower()
        return "art:" + art if art else "nm:" + norm_key(rec.get("name") or "")
    if axis == "name":
        return "nm:" + norm_key(rec.get("name") or "")
    # auto — bitta yozuv uchun: aniqroqdan umumiyga
    bc = _digits(rec.get("barcode"))
    if bc:
        return "bc:" + bc
    art = (rec.get("article") or "").strip().lower()
    if art:
        return "art:" + art
    return "nm:" + norm_key(rec.get("name") or "")


def _join_axis(files_rows) -> str:
    """Ulash o'qini TANLAYDI — BARCHA fayllarda mavjud bo'lgan eng aniq maydon.

    ⚠️  ILGARI O'Q HAR YOZUV UCHUN ALOHIDA TANLANARDI. Natija: barkodli fayl
        «bc:…», barkodsiz narx fayli esa «nm:…» kalitini berardi va ular HECH
        QACHON uchrashmasdi — ulash JIM ravishda nolga aylanardi. Endi o'q butun
        birlashtirish uchun BITTA: hamma fayl uni to'ldira olmasa, o'q pasayadi.
    """
    for axis, field in (("barcode", "barcode"), ("article", "article")):
        if files_rows and all(
            rows and any((_digits(r.get(field)) if field == "barcode" else (r.get(field) or "").strip())
                         for r in rows)
            for rows in files_rows
        ):
            return axis
    return "name"


def merge(files_rows, enrich_only=None):
    """Bir nechta fayldan kelgan yozuvlarni kalit bo'yicha birlashtiradi.

    `enrich_only` — indekslari shu to'plamda bo'lgan fayllar YANGI mahsulot
    YARATMAYDI, faqat mavjudlarini to'ldiradi. Bu barkod katalogi uchun zarur:
    Fayzan'ning Список9.xls'ida 44 mingdan ortiq nom bor, ularning ko'pi narxsiz
    va sotib bo'lmaydi — ular mahsulot sifatida kirsa katalog 5 barobar shishib
    ketardi. Barkod fayli mahsulot ro'yxatini BELGILAMAYDI, faqat boyitadi.

    Barkodlar RO'YXAT sifatida yig'iladi (`barcodes`): bitta mahsulotда bir nechta
    barkod bo'lishi odatiy va ularning hammasi kerak — import bittasini oladi,
    qolganlari keyin `/products/barcodes/import` orqali qo'shiladi.
    """
    enrich_only = enrich_only or set()
    axis = _join_axis(files_rows)
    if len(files_rows) > 1:
        print(f"\n  ulash o'qi: {axis}")
    merged, order = {}, []
    for idx, rows in enumerate(files_rows):
        for rec in rows:
            k = _key(rec, axis)
            if k not in merged:
                if idx in enrich_only:
                    continue                       # mavjud emas — boyitadigan fayl yaratmaydi
                merged[k] = dict(rec)
                order.append(k)
            else:
                for f, v in rec.items():
                    if f == "barcodes":
                        continue
                    if v not in (None, "") and merged[k].get(f) in (None, ""):
                        merged[k][f] = v
            bc = _digits(rec.get("barcode"))
            if bc:
                merged[k].setdefault("barcodes", [])
                if bc not in merged[k]["barcodes"]:
                    merged[k]["barcodes"].append(bc)
    return [merged[k] for k in order]


def to_import_rows(records):
    """SavdoOS /products/import/commit formati."""
    out = []
    for r in records:
        row = {"name": r["name"]}
        # Import BITTA barkod oladi. Tanlov DETERMINISTIK bo'lishi shart — aks holda
        # har safar boshqa barkod «asosiy» bo'lib, qayta yurgizish natijasi o'zgarardi.
        bcs = r.get("barcodes") or ([_digits(r.get("barcode"))] if _digits(r.get("barcode")) else [])
        if bcs:
            row["barcode"] = sorted(bcs)[0]
            if len(bcs) > 1:
                row["_extra_barcodes"] = sorted(bcs)[1:]
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
    ap.add_argument("--enrich", default="", metavar="1,2",
                    help="FAQAT boyitadigan fayllar (0-dan boshlab): yangi mahsulot yaratmaydi")
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

    enrich = {int(x) for x in a.enrich.split(",") if x.strip().isdigit()}
    files_rows = [load_file(f, manual, a.preview) for f in a.files]
    records = merge(files_rows, enrich) if len(files_rows) > 1 else merge(files_rows)
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
