# -*- coding: utf-8 -*-
"""Sintetik `binos-1c-v1` bundle generatori — DETERMINISTIK (seed bilan).

Testlar va staging rehearsal uchun. Real 1C ma'lumoti emas; ataylab chegaraviy holatlar
qo'shiladi: bir nechta barkod, takror barkod/artikul/GUID, GUID'siz qator, oldingi nollar,
kirill/Unicode, narxsiz, nol/manfiy/o'nlik/juda katta qoldiq, noma'lum birlik, o'chirish belgisi,
papka, xizmat, xarakteristika, seriya, buzuq barkod, 12 xonali UPC, PLU oldingi nol bilan.
"""
from __future__ import annotations

import hashlib
import json
import random
import uuid

WH_MAIN = "0f1e2d3c-4b5a-4968-8776-655443322110"
WH_SECOND = "1a2b3c4d-5e6f-4a0b-9c1d-2e3f4a5b6c7d"
PT_RETAIL = "aa000000-0000-4000-8000-000000000001"
PT_PURCHASE = "aa000000-0000-4000-8000-000000000002"
PT_WHOLESALE = "aa000000-0000-4000-8000-000000000003"

NAMES = ["Молоко «Простоквашино» 3,2% 1л", "Сахар-песок 1кг", "Нон Тандыр", "Чай «Акбар» 100г", "Yog' Oltin 5L",
         "Шоколад Alpen Gold 90г", "Ün 1-sort 50kg", "Кефир 2,5%  0,5л", "Сок «Gracio» яблоко 1л", "Tuxum C1 (10 dona)",
         "Макароны «Шебекинские» 450г", "Рис девзира 1кг", "Вода «Ак-Суу» 1,5л", "Сыр «Российский» кг", "Сабун «Дуру»"]
UNITS = [("шт", "796"), ("кг", "166"), ("л", "112"), ("упак", "778")]


def _guid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _ean13(rng: random.Random, prefix: str = "470") -> str:
    body = prefix + "".join(str(rng.randint(0, 9)) for _ in range(12 - len(prefix)))
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - s % 10) % 10)


def make_bundle(n: int = 10_000, seed: int = 42, edge_cases: bool = True, multi_warehouse: bool = True,
                export_id: str | None = None, snapshot_at: str = "2026-09-20T09:00:00+06:00") -> dict:
    rng = random.Random(seed)
    products = []
    used_bc: set[str] = set()
    for i in range(n):
        name = f"{rng.choice(NAMES)} #{i:05d}"
        unit = rng.choice(UNITS)
        code = f"{i + 1:011d}"                                  # 1C Код — oldingi nollar
        article = f"0{rng.randint(10000, 99999)}-{i}" if rng.random() < 0.6 else None
        bcs = []
        for _ in range(rng.choice([0, 1, 1, 1, 2, 3])):
            b = _ean13(rng)
            while b in used_bc:
                b = _ean13(rng)
            used_bc.add(b)
            bcs.append({"value": b, "type": "EAN13"})
        retail = f"{rng.randint(1, 250000)}.{rng.randint(0, 99):02d}" if rng.random() < 0.97 else None
        purchase = f"{rng.randint(1, 200000)}.{rng.randint(0, 99):02d}" if rng.random() < 0.9 else None
        prices = [{"price_type_guid": PT_RETAIL, "value": retail}]
        if purchase is not None:
            prices.append({"price_type_guid": PT_PURCHASE, "value": purchase})
        if rng.random() < 0.2:
            prices.append({"price_type_guid": PT_WHOLESALE, "value": f"{rng.randint(1, 250000)}.00"})
        stock = []
        r = rng.random()
        if r < 0.15:
            pass                                                # 1C registrida qoldiq yo'q -> 0
        elif r < 0.25:
            stock.append({"warehouse_guid": WH_MAIN, "qty": "0"})
        else:
            q = f"{rng.randint(0, 5000)}.{rng.randint(0, 999):03d}" if unit[0] == "кг" else str(rng.randint(1, 500))
            stock.append({"warehouse_guid": WH_MAIN, "qty": q})
        if multi_warehouse and rng.random() < 0.1:
            stock.append({"warehouse_guid": WH_SECOND, "qty": str(rng.randint(1, 50))})
        products.append({
            "guid": _guid(rng), "code": code, "article": article, "name": name, "kind": "goods",
            "is_folder": False, "deletion_mark": False, "has_characteristics": False, "has_series": False,
            "unit": {"name": unit[0], "code": unit[1]}, "is_weighted": unit[0] == "кг",
            "plu": (f"{rng.randint(1, 9999)}" if unit[0] == "кг" and rng.random() < 0.3 else None),
            "barcodes": bcs, "prices": prices, "stock": stock,
        })
    if edge_cases and n >= 40:
        p = products
        p[0]["guid"] = None                                               # GUID yo'q
        p[1]["guid"] = "not-a-guid"                                       # buzuq GUID
        p[3]["guid"] = p[2]["guid"]                                       # takror GUID
        p[4]["barcodes"] = [{"value": "4600000000017", "type": "EAN13"}]
        p[5]["barcodes"] = [{"value": "4600000000017", "type": "EAN13"}]  # takror barkod
        p[6]["article"] = "000777"
        p[7]["article"] = "000777"                                        # takror artikul
        p[8]["code"], p[8]["article"] = "0000123", "00000456"             # oldingi nollar
        p[9]["name"] = "Ўзбекча кирилл: «Қатиқ» ЁЎҚҒҲ — ёғли 3,5%"      # Unicode
        p[10]["prices"] = [{"price_type_guid": PT_RETAIL, "value": None}]  # narx yo'q
        p[11]["stock"] = [{"warehouse_guid": WH_MAIN, "qty": "0"}]        # nol qoldiq
        p[12]["stock"] = [{"warehouse_guid": WH_MAIN, "qty": "-25.500"}]  # manfiy
        p[13]["stock"] = [{"warehouse_guid": WH_MAIN, "qty": "12.345"}]   # o'nlik
        p[14]["stock"] = [{"warehouse_guid": WH_MAIN, "qty": "99999999999.999"}]  # juda katta
        p[15]["unit"] = {"name": "бухта", "code": "999"}                  # noma'lum birlik
        p[16]["deletion_mark"] = True
        p[17]["is_folder"] = True
        p[18]["kind"] = "service"
        p[19]["has_characteristics"] = True
        p[20]["has_series"] = True
        p[21]["barcodes"] = [{"value": "ABC-123456", "type": "CODE128"}]  # buzuq barkod
        p[22]["barcodes"] = [{"value": "012345678905", "type": "UPC"}]    # 12 xonali, oldingi nol
        p[23]["unit"], p[23]["plu"], p[23]["is_weighted"] = {"name": "кг", "code": "166"}, "00575", True
        p[24]["stock"] = [{"warehouse_guid": WH_MAIN, "qty": "1.2345"}]   # aniqlik yo'qolishi
        p[25]["prices"] = [{"price_type_guid": PT_RETAIL, "value": "0"}]  # nol narx
        p[26]["barcodes"] = [{"value": "  4780000000013  ", "type": "EAN13"}, {"value": "4780000000020", "type": "EAN13"},
                             {"value": "4780000000037", "type": "EAN13"}]
    return finalize({
        "schema_version": "binos-1c-v1", "source_system": "1c",
        "export_id": export_id or str(uuid.UUID(int=random.Random(seed * 7 + 1).getrandbits(128), version=4)),
        "exported_at": "2026-09-20T09:00:05+06:00", "snapshot_at": snapshot_at,
        "infobase": {"platform_version": "8.3.SYNTH", "configuration_name": "SYNTHETIC (test)",
                     "configuration_version": "0.0.0"},
        "extractor": {"name": "migrator_1c_synth", "version": "1"},
        "warehouses": [{"guid": WH_MAIN, "code": "000000001", "name": "Основной склад"},
                       {"guid": WH_SECOND, "code": "000000002", "name": "Склад 2"}],
        "price_types": [{"guid": PT_RETAIL, "code": "000000001", "name": "Розничная цена"},
                        {"guid": PT_PURCHASE, "code": "000000002", "name": "Цена поставщика"},
                        {"guid": PT_WHOLESALE, "code": "000000003", "name": "Оптовая"}],
        "selection": {"warehouse_guids": [WH_MAIN], "retail_price_type_guid": PT_RETAIL,
                      "purchase_price_type_guid": PT_PURCHASE},
        "products": products,
    })


def finalize(d: dict) -> dict:
    """Manifestni fayl mazmunidan hisoblaydi (extractor ham AYNAN shunday qilishi kerak)."""
    from decimal import Decimal, localcontext
    import re
    sel = set(d["selection"]["warehouse_guids"])
    tot = {w: Decimal("0") for w in sel}
    with localcontext() as ctx:                      # 1C ham yig'indini yuvarlamasdan hisoblaydi
        ctx.prec = 60
        for p in d["products"]:
            for st in p["stock"]:
                if st["warehouse_guid"] in sel and re.fullmatch(r"-?[0-9]{1,20}(\.[0-9]{1,12})?", st["qty"]):
                    tot[st["warehouse_guid"]] += Decimal(st["qty"])
    d["manifest"] = {
        "product_count": str(len(d["products"])),
        "barcode_count": str(sum(len(p["barcodes"]) for p in d["products"])),
        "price_count": str(sum(len(p["prices"]) for p in d["products"])),
        "stock_row_count": str(sum(len(p["stock"]) for p in d["products"])),
        "stock_qty_by_warehouse": {w: format(v, "f") for w, v in sorted(tot.items())},
    }
    return d


def to_bytes(d: dict, indent: int | None = None, bom: bool = False) -> bytes:
    raw = json.dumps(d, ensure_ascii=False, indent=indent).encode("utf-8")
    return (b"\xef\xbb\xbf" + raw) if bom else raw


def write(d: dict, path: str) -> str:
    raw = to_bytes(d)
    with open(path, "wb") as f:
        f.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with open(path + ".sha256", "w", encoding="utf-8") as f:
        f.write(f"{sha}  {path.replace(chr(92), '/').rsplit('/', 1)[-1]}\n")
    return sha


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(write(make_bundle(a.count, a.seed), a.out))
