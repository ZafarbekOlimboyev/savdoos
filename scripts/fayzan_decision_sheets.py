# -*- coding: utf-8 -*-
"""FAYZAN — do'kon egasi uchun TO'RT QAROR VARAG'I (LOKAL + faqat o'qish).

    python scripts/fayzan_decision_sheets.py --out <papka>

⚠️  PRODUCTION'GA YOZMAYDI. Baza `default_transaction_read_only=on` bilan
    ochiladi; .xls manbalar faqat o'qiladi. Hech qanday narx, nom yoki qoldiq
    O'ZGARTIRILMAYDI va TAXMIN QILINMAYDI.

Chiqadigan varaqlar:
  fayzan_missing_buy_16.xlsx  — kelish narxi yo'q 16 HAQIQIY mahsulot
                                (4 ta kassa tugmasi ALOHIDA varaqda)
  fayzan_loss_price_9.xlsx    — sotish < kelish bo'lgan 9 mahsulot
  fayzan_open_price_4.xlsx    — kassaning ochiq narx tugmalari
  fayzan_mixed_script_56.xlsx — nomida lotin/kirill aralashgan mahsulotlar
"""
import argparse
import collections
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SRC = pathlib.Path(__file__).resolve().parents[1] / "apps" / "server" / "tools" / "import_1c.py"
_spec = importlib.util.spec_from_file_location("import_1c", _SRC)
IC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IC)

RW = os.path.join("C:\\", "Users", "Developer", "nodejs", "node-v20.18.0-win-x64", "railway.cmd")
PROJECT = "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
PROD_ENV = "1d0edbf9-652e-44ae-b4ca-ca58d6c8106f"
PG_SVC = "ac01439d-cfed-47cc-b096-cdc6f8faa379"
COMPANY = "8933a0fb-a0b4-47b5-8bff-ecf5d90b6ef5"
SRC_DIR = r"C:\Users\Developer\Downloads\Telegram Desktop"

LAT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
CYR = set("абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
# Ko'rinishi AYNAN bir xil harflar. Ikki yo'nalish ham kerak: kirill so'zga lotin
# harf tushishi ham, lotin so'zga kirill harf tushishi ham uchraydi.
L2C = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
       "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
       "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"}
C2L = {v: k for k, v in L2C.items()}


def classify_word(w: str):
    """(toifa, tuzatilgan_so'z). Toifa: fold_cyr | fold_lat | bilingual | clean."""
    has_l = any(c in LAT for c in w)
    has_c = any(c in CYR for c in w)
    if not (has_l and has_c):
        return "clean", w
    nlat = sum(1 for c in w if c in LAT)
    ncyr = sum(1 for c in w if c in CYR)
    lat_homo = sum(1 for c in w if c in L2C)
    cyr_homo = sum(1 for c in w if c in C2L)
    # kirill ustun + undagi lotinlar egizak -> kirillga keltiramiz
    if ncyr > nlat and lat_homo == nlat:
        return "fold_cyr", "".join(L2C.get(c, c) for c in w)
    # lotin ustun + undagi kirillar egizak -> lotinga keltiramiz
    if nlat > ncyr and cyr_homo == ncyr:
        return "fold_lat", "".join(C2L.get(c, c) for c in w)
    return "bilingual", w          # haqiqiy ikki tilli nom — TEGILMAYDI


def analyse(name: str):
    kinds, out = set(), []
    for w in name.split():
        k, fixed = classify_word(w)
        kinds.add(k)
        out.append(fixed)
    prop = " ".join(out)
    if "bilingual" in kinds and prop == name:
        return "ARALASH BREND (решение владельца)", name
    if prop != name:
        return "ЛАТИНСКИЕ БУКВЫ В РУССКОМ СЛОВЕ" if "fold_cyr" in kinds \
            else "РУССКИЕ БУКВЫ В ЛАТИНСКОМ СЛОВЕ", prop
    return "", name


def dsn() -> str:
    q = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dsvars.gql")
    with open(q, "w", encoding="utf-8") as f:
        f.write("query($pid: String!, $eid: String!, $sid: String!) "
                "{ variables(projectId: $pid, environmentId: $eid, serviceId: $sid) }")
    try:
        raw = subprocess.run([RW, "api", "-f", q, "--var", f"pid={PROJECT}",
                              "--var", f"eid={PROD_ENV}", "--var", f"sid={PG_SVC}"],
                             capture_output=True, text=True, timeout=120).stdout
        V = json.loads(raw)["data"]["variables"]
        return (f"postgresql://{V['PGUSER']}:{V['PGPASSWORD']}@{V['RAILWAY_TCP_PROXY_DOMAIN']}:"
                f"{V['RAILWAY_TCP_PROXY_PORT']}/{V['PGDATABASE']}"
                "?sslmode=prefer&options=-c%20default_transaction_read_only%3Don")
    finally:
        try:
            os.remove(q)
        except OSError:
            pass


HOMO_ALL = str.maketrans({**L2C})


def is_till_button(name: str) -> bool:
    t = name.translate(HOMO_ALL).casefold().split()
    return (len(t) >= 2 and t[0] in {"товар", "твоар"}
            and re.fullmatch(r"\d+\s*(сом|с)?", " ".join(t[1:])) is not None)


def main() -> int:
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".")
    ap.add_argument("--exclusions", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)

    sena = IC.load_file(SRC_DIR + r"\sena.xls")
    ast = IC.load_file(SRC_DIR + r"\astatka.xls")
    s9 = IC.load_file(SRC_DIR + r"\Список9.xls")
    sena_by = collections.defaultdict(list)
    for r in sena:
        sena_by[IC.norm_key(r["name"])].append(r)
    ast_rows = collections.defaultdict(list)
    for r in ast:
        ast_rows[IC.norm_key(r["name"])].append(r)
    bc = collections.defaultdict(list)
    for r in s9:
        d = IC._digits(r.get("barcode"))
        if d:
            k = IC.norm_key(r["name"])
            if d not in bc[k]:
                bc[k].append(d)
    for k in bc:
        bc[k].sort()

    def net(k):
        qs = [x["stock"] for x in ast_rows.get(k, []) if x.get("stock") is not None]
        return round(sum(qs), 3) if qs else None

    exc = json.load(open(a.exclusions, encoding="utf-8"))

    # ── 1) KELISH NARXI YO'Q — 16 haqiqiy + 4 tugma ────────────────────
    real, btns = [], []
    for n in exc["no_buy"]:
        k = IC.norm_key(n)
        r = sena_by[k][0]
        st = ast_rows.get(k, [])
        q = net(k)
        ev = (f"sena.xls: цена продажи {r['sell']:g}, «Цена поставщика» ПУСТАЯ; "
              f"astatka.xls: {len(st)} строк, итог {q if q is not None else 'нет'}")
        row = {"Наименование": r["name"], "Цена продажи": r["sell"],
               "Остаток (1С, суммарно)": q, "Ед. изм.": (st[0].get("unit") if st else "") or "",
               "Штрихкоды": ", ".join(bc.get(k, [])) or "НЕТ",
               "Штрихкодов": len(bc.get(k, [])),
               "Источник (что известно)": ev,
               "ПОДТВЕРЖДЁННАЯ ЦЕНА ЗАКУПКИ": "",
               "КТО ПОДТВЕРДИЛ": "", "ПРИМЕЧАНИЯ": ""}
        (btns if is_till_button(r["name"]) else real).append(row)
    real.sort(key=lambda x: x["Наименование"])
    pd.DataFrame(real).to_excel(out / "fayzan_missing_buy_16.xlsx", index=False)

    # ── 2) ZARAR NARXLI — 9 ────────────────────────────────────────────
    loss = []
    for n in exc["loss"]:
        k = IC.norm_key(n)
        r = sena_by[k][0]
        q = net(k)
        loss.append({"Наименование": r["name"],
                     "Цена закупки (1С)": r["buy"], "Цена продажи (1С)": r["sell"],
                     "Разница (убыток/шт)": round(r["buy"] - r["sell"], 2),
                     "Остаток": q,
                     "Потенциальный убыток": round((r["buy"] - r["sell"]) * (q or 0), 2),
                     "Штрихкоды": ", ".join(bc.get(k, [])) or "НЕТ",
                     "Штрихкодов": len(bc.get(k, [])),
                     "ПРАВИЛЬНАЯ ЦЕНА ЗАКУПКИ": "", "ПРАВИЛЬНАЯ ЦЕНА ПРОДАЖИ": "",
                     "ПРИЧИНА (акция / старая себестоимость / ошибка розницы / другое)": ""})
    loss.sort(key=lambda x: -x["Разница (убыток/шт)"])
    pd.DataFrame(loss).to_excel(out / "fayzan_loss_price_9.xlsx", index=False)

    # ── 3) OCHIQ NARX TUGMALARI — 4 ────────────────────────────────────
    for b in btns:
        b["ЧТО ЭТО"] = "кнопка кассы с открытой ценой (не товар)"
        b["СКОЛЬКО РАЗ ИСПОЛЬЗОВАНА (1С)"] = abs(b["Остаток (1С, суммарно)"] or 0)
        b["РЕШЕНИЕ (оставить / убрать / заменить)"] = ""
    btns.sort(key=lambda x: -(x["СКОЛЬКО РАЗ ИСПОЛЬЗОВАНА (1С)"]))
    pd.DataFrame(btns).to_excel(out / "fayzan_open_price_4.xlsx", index=False)

    # ── 4) ARALASH YOZUV — production'dan ──────────────────────────────
    import psycopg
    with psycopg.connect(dsn(), connect_timeout=30) as con, con.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            sys.exit("XATO: read-only kafolatlanmadi")
        cur.execute("""SELECT p.id, p.name, p.article_code,
                              (SELECT count(*) FROM product_barcodes b WHERE b.product_id=p.id),
                              coalesce((SELECT sum(i.qty) FROM inventory i WHERE i.product_id=p.id),0),
                              p.base_sell_price
                       FROM products p WHERE p.company_id=%s AND p.deleted_at IS NULL
                       ORDER BY p.name""", (COMPANY,))
        prods = cur.fetchall()

    taken = {n.strip().lower(): str(i) for i, n, *_ in prods}
    mixed, seen_prop = [], {}
    for pid, nm, art, nbc, qty, sell in prods:
        kind, prop = analyse(nm)
        if not kind:
            continue
        low = prop.strip().lower()
        clash_db = low in taken and taken[low] != str(pid)
        clash_set = low in seen_prop
        seen_prop.setdefault(low, nm)
        mixed.append({"product_id": str(pid), "Текущее название": nm,
                      "Предлагаемое название": prop if prop != nm else "",
                      "Тип проблемы": kind, "Артикул": art,
                      "Штрихкодов": nbc, "Без штрихкода": "ДА" if nbc == 0 else "нет",
                      "Остаток": float(qty), "Цена продажи": float(sell),
                      "КОНФЛИКТ С СУЩЕСТВУЮЩИМ": "ДА" if clash_db else "нет",
                      "КОНФЛИКТ ВНУТРИ СПИСКА": "ДА" if clash_set else "нет",
                      "РЕШЕНИЕ (переименовать? да/нет)": ""})
    # eng xavflisi tepaga: barkodsiz + qoldiqli
    mixed.sort(key=lambda x: (not (x["Без штрихкода"] == "ДА" and x["Остаток"] > 0),
                              x["Тип проблемы"], x["Текущее название"]))
    pd.DataFrame(mixed).to_excel(out / "fayzan_mixed_script_56.xlsx", index=False)

    print(f"kelish narxi yo'q (haqiqiy)  : {len(real)}")
    print(f"kassa tugmalari              : {len(btns)}")
    print(f"zarar narxli                 : {len(loss)}")
    print(f"aralash yozuvli              : {len(mixed)}")
    k = collections.Counter(x["Тип проблемы"] for x in mixed)
    for t, c in k.most_common():
        print(f"    {t:36} : {c}")
    print(f"  to'qnashuv (bazada)        : {sum(1 for x in mixed if x['КОНФЛИКТ С СУЩЕСТВУЮЩИМ'] == 'ДА')}")
    print(f"  to'qnashuv (ro'yxat ichida): {sum(1 for x in mixed if x['КОНФЛИКТ ВНУТРИ СПИСКА'] == 'ДА')}")
    print(f"  barkodsiz VA qoldiqli      : {sum(1 for x in mixed if x['Без штрихкода'] == 'ДА' and x['Остаток'] > 0)}")
    print(f"\nyozildi: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
