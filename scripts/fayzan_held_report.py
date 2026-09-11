# -*- coding: utf-8 -*-
"""FAYZAN — USHLAB QOLINGAN 4 TO'PLAM hisoboti (LOKAL, tarmoqsiz).

    python scripts/fayzan_held_report.py <chiqish_papkasi>

⚠️  HECH NARSA IMPORT QILMAYDI, production'ga UMUMAN chiqmaydi. Faqat .xls
    manbalarni o'qib, do'kon egasi qaror qilishi kerak bo'lgan to'rt varaqni
    yozadi:
      A) sotish < kelish            — 9
      B) kelish narxi yo'q          — 20
      C) tarozi (кг) nomzodlari     — 454
      D) takror nomli guruhlar      — 214 guruh / 666 qator
    Har varaqda TO'LDIRISH ustuni bor; hech qanday qaror avtomatik qilinmaydi.
"""
import collections, importlib.util, json, re, sys
import pandas as pd
SP = sys.argv[1] if len(sys.argv) > 1 else "."; sys.stdout.reconfigure(encoding="utf-8", errors="replace")
spec = importlib.util.spec_from_file_location("ic", r"apps\server\tools\import_1c.py")
IC = importlib.util.module_from_spec(spec); spec.loader.exec_module(IC)
D = r"C:\Users\Developer\Downloads\Telegram Desktop"
sena = IC.load_file(D + r"\sena.xls")
ast  = IC.load_file(D + r"\astatka.xls")
s9   = IC.load_file(D + r"\Список9.xls")

sena_by = collections.defaultdict(list)
for r in sena: sena_by[IC.norm_key(r["name"])].append(r)
ast_rows = collections.defaultdict(list)
for r in ast: ast_rows[IC.norm_key(r["name"])].append(r)
def netstock(k):
    qs = [x["stock"] for x in ast_rows.get(k, []) if x.get("stock") is not None]
    return round(sum(qs), 3) if qs else None
unit_of = {k: v[0].get("unit") for k, v in ast_rows.items()}
bc = collections.defaultdict(list)
for r in s9:
    d = IC._digits(r.get("barcode"))
    if d:
        k = IC.norm_key(r["name"])
        if d not in bc[k]: bc[k].append(d)
for k in bc: bc[k].sort()

exc = json.load(open(SP + "/exclusions.json", encoding="utf-8"))
# Lotin/kirill egizak harflarni (a/o/c/e/p/x...) kirillga keltiramiz — 1С da aralash yozilgan
HOMO = str.maketrans("acepoxyABCEHKMOPTXY", "асероху"
                                           "АВСЕНКМ"
                                           "ОРТХУ")
def is_till_button(name: str) -> bool:
    """«Товар 5сом» / «Твоар 20сом» — kassaning OCHIQ NARX tugmasi."""
    t = name.translate(HOMO).casefold().split()
    return (len(t) >= 2 and t[0] in {"товар", "твоар"}
            and re.fullmatch(r"\d+\s*(сом|с)?", " ".join(t[1:])) is not None)

# ═══ A) 9 ta ZARAR narxli ═══════════════════════════════════════════════
A = []
for n in exc["loss"]:
    k = IC.norm_key(n); r = sena_by[k][0]
    A.append({"Наименование": r["name"], "Цена закупки": r["buy"], "Цена продажи": r["sell"],
              "Разница (убыток/шт)": round(r["buy"] - r["sell"], 2),
              "Остаток": netstock(k), "Ед. изм.": unit_of.get(k) or "",
              "Штрихкоды": ", ".join(bc.get(k, [])) or "НЕТ",
              "Штрихкодов": len(bc.get(k, [])),
              "Потенциальный убыток": round((r["buy"] - r["sell"]) * (netstock(k) or 0), 2),
              "РЕШЕНИЕ: новая цена продажи": ""})
A.sort(key=lambda x: -x["Разница (убыток/шт)"])
print("=== A) SOTISH < KELISH — 9 ta ===")
for x in A:
    print(f"  {x['Наименование'][:40]:40} kelish={x['Цена закупки']:>7g} sotish={x['Цена продажи']:>6g} "
          f"farq={x['Разница (убыток/шт)']:>6g} qoldiq={x['Остаток']} bc={x['Штрихкодов']}")
print(f"  jami potensial zarar: {sum(x['Потенциальный убыток'] for x in A):,.2f} som")

# ═══ B) 20 ta KELISH NARXSIZ ════════════════════════════════════════════
B = []
for n in exc["no_buy"]:
    k = IC.norm_key(n); r = sena_by[k][0]
    is_btn = is_till_button(r["name"])
    B.append({"Наименование": r["name"], "Цена продажи": r["sell"],
              "Остаток": netstock(k), "Ед. изм.": unit_of.get(k) or "",
              "Штрихкоды": ", ".join(bc.get(k, [])) or "НЕТ",
              "Штрихкодов": len(bc.get(k, [])),
              "КНОПКА КАССЫ (открытая цена)": "ДА" if is_btn else "нет",
              "РЕШЕНИЕ: цена закупки": ""})
B.sort(key=lambda x: (x["КНОПКА КАССЫ (открытая цена)"] != "ДА", x["Наименование"]))
print("\n=== B) KELISH NARXI YO'Q — 20 ta ===")
for x in B:
    print(f"  {x['Наименование'][:34]:34} sotish={x['Цена продажи']:>6g} qoldiq={str(x['Остаток']):>7} "
          f"bc={x['Штрихкодов']} tugma={x['КНОПКА КАССЫ (открытая цена)']}")
print(f"  kassa tugmalari: {sum(1 for x in B if x['КНОПКА КАССЫ (открытая цена)']=='ДА')}")

# ═══ C) 454 TAROZI ══════════════════════════════════════════════════════
RE_PLU = re.compile(r"(?:(\d{3,4})\s*[Кк][Оо][РрOo]?[Дд]|[Кк][Оо][Дд]\s*(\d{3,4}))\s*$")
C, codes = [], collections.Counter()
for k, v in ast_rows.items():
    if v[0].get("unit") != "кг": continue
    pr = sena_by.get(k, [{}])[0]
    nm = pr.get("name") or v[0]["name"]
    mt = RE_PLU.search(nm)
    code = (mt.group(1) or mt.group(2)) if mt else ""
    if code: codes[code] += 1
    C.append({"_k": k, "Наименование": nm, "Ед. изм. (1С)": "кг",
              "Код из названия": code, "Остаток (кг)": netstock(k),
              "Цена продажи": pr.get("sell"), "Цена закупки": pr.get("buy"),
              "Штрихкоды": ", ".join(bc.get(k, [])) or "НЕТ",
              "Штрихкодов": len(bc.get(k, [])),
              "ПРОВЕРИТЬ НА ВЕСАХ: PLU": "", "ПРОВЕРИТЬ: цена за 1 кг": "",
              "Совпадает? (да/нет)": ""})
for x in C:
    c = x["Код из названия"]
    x["ПРОБЛЕМА"] = ("код повторяется" if c and codes[c] > 1 else "кода нет" if not c
                     else "нет цены" if not x["Цена продажи"] else "")
    x.pop("_k")
C.sort(key=lambda x: (x["ПРОБЛЕМА"] == "", x["Код из названия"] or "zzzz"))
print(f"\n=== C) TAROZI — {len(C)} ta ===")
print(f"  muammo: {dict(collections.Counter(x['ПРОБЛЕМА'] for x in C))}")
print(f"  kod diapazoni: {min(int(c) for c in codes)}..{max(int(c) for c in codes)} | noyob kod: {len(codes)}")
print(f"  barkodi bor: {sum(1 for x in C if x['Штрихкодов'])} | yo'q: {sum(1 for x in C if not x['Штрихкодов'])}")
print(f"  qoldig'i musbat: {sum(1 for x in C if (x['Остаток (кг)'] or 0) > 0)}")
print(f"  qoldig'i manfiy: {sum(1 for x in C if (x['Остаток (кг)'] or 0) < 0)}")
print(f"  qoldig'i yo'q  : {sum(1 for x in C if x['Остаток (кг)'] is None)}")

# ═══ D) 214 TAKROR NOM GURUHI ═══════════════════════════════════════════
Drows = []
for k in sorted(sena_by):
    v = sena_by[k]
    if len(v) < 2: continue
    bl, st = bc.get(k, []), ast_rows.get(k, [])
    for i, r in enumerate(v, 1):
        Drows.append({"Наименование (1С)": r["name"], "№ варианта": i, "Всего вариантов": len(v),
                      "Цена продажи": r.get("sell"), "Цена закупки": r.get("buy"),
                      "Штрихкодов у имени": len(bl),
                      "Штрихкоды": ", ".join(bl[:8]) or "НЕТ",
                      "Строк остатка": len(st),
                      "Остаток (суммарно)": netstock(k),
                      "ТОЧНОЕ УНИКАЛЬНОЕ НАЗВАНИЕ": ""})
groups = len({x["Наименование (1С)"].strip().lower() for x in Drows})
print(f"\n=== D) TAKROR NOM — {len(Drows)} qator ===")
print(f"  guruhlar: 214 | noyob yozilish: {groups}")
print(f"  barkodi guruh hajmiga TENG yoki ko'p: "
      f"{sum(1 for k in sena_by if len(sena_by[k])>1 and len(bc.get(k,[]))>=len(sena_by[k]))}")

for name, rows in (("fayzan_A_zarar_9", A), ("fayzan_B_kelishsiz_20", B),
                   ("fayzan_C_tarozi_454", C), ("fayzan_D_takror_666", Drows)):
    pd.DataFrame(rows).to_excel(f"{SP}/{name}.xlsx", index=False)
    print(f"  yozildi: {name}.xlsx ({len(rows)} qator)")
