"""ESKI ZAXIRA YO'LLARI UCHUN DARVOZA — kuzatuvli mahsulotga tegmasin.

`Inventory.qty` ni yozadigan 20 ga yaqin joy bor. Ularning bir qismi partiya
tushunchasidan butunlay bexabar: inventarizatsiya qoldiqni MUTLAQ qilib qo'yadi,
1C cutover moslashtiruvi ham shunday, demo seed esa umuman o'z bilganicha yozadi.

Partiya kuzatuvi yoqilganда bunday yozuv
`Inventory.qty == SUM(remaining_qty)` invariantini JIMGINA buzardi: qoldiq
o'zgaradi, partiyalar esa o'z holicha qoladi.

Shu bois bu yo'llar kuzatuvli mahsulotда FAIL-CLOSED to'xtaydi. Ular keyingi
bosqichlarда partiyani biladigan qilib qayta yozilгунча — ruxsat yo'q.

⚠️  BUGUN BU DARVOZA UXLAB YOTADI: Phase 0 da `track_lots` ni yoqadigan yo'l
    umuman yo'q, ya'ni hech bir mahsulot kuzatuvli emas va hech qanday yo'l
    bloklanmaydi. U kuzatuv yoqilgan KUNI o'z-o'zidan ishlay boshlaydi.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Product


class TrackedProductNotSupported(ValueError):
    """Bu yo'l partiyani bilmaydi — kuzatuvli mahsulotда ishlata olmaydi.

    ⚠️  `ValueError` dan meros: mavjud API qatlamlari `ValueError` ni allaqachon
        toza `400` ga aylantiradi. `RuntimeError` bo'lsa u ushlanmagan `500`
        bo'lib chiqardi — operator uchun bu "server buzildi" degani bo'lardi,
        holbuki bu ANIQ va kutilgan rad etish.
    """


def tracked_ids(db: Session, product_ids) -> list:
    ids = [p for p in product_ids if p is not None]
    if not ids:
        return []
    q = select(Product.id).where(Product.id.in_(ids), Product.track_lots.is_(True))
    return [r[0] for r in db.execute(q).all()]


def assert_untracked(db: Session, product_ids, path: str) -> None:
    """Kuzatuvli mahsulot bo'lsa — amalni TO'XTATADI.

    `path` — xabarда ko'rinadigan yo'l nomi ("inventarizatsiya", "1C cutover"),
    operator qaysi oqim rad etilganini bilishi uchun.
    """
    bad = tracked_ids(db, product_ids)
    if bad:
        raise TrackedProductNotSupported(
            f"«{path}» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin "
            f"{len(bad)} ta kuzatuvli mahsulot so'ralди. Partiya-darajasidagi "
            f"amalni ishlating — qoldiqni partiyalardan ayirmasdan o'zgartirish "
            f"miqdor invariantini buzardi.")


# ── HTTP QATLAMIGA MOSLASHTIRUVCHI ───────────────────────────────────────────
# Har chaqiruv joyida `try/except` ni nusxalash XAVFLI: bitta joyda `except` yozish
# unutilса, rad etish toza 409 emas, ushlanmagan 500 bo'lиб chiqardi.
#
# ⚠️  MAQOM TASODIFIY EMAS. `/sync/push` (offline kassa) 409 ni TRANZIENT deb biladi
#     va chekni outbox'да SAQLAB qayta-qayta yuboradi (`api/v1/sync.py`). Menejer
#     yo'llari esa outbox'да YASHAMAYDI — ular uchun `409` (holat ziddiyati) to'g'ri
#     maqom va cheksiz retry tug'dirmaydi.
#
#     PHASE 2 IZOHI: sotuv yo'li endi bu darvozadan UMUMAN o'tmaydi. Kuzatuvli
#     mahsulot FEFO bilan sotiladi (`lot_fefo.py`), offline qayta yuborish esa
#     kamomad partiyasi tufayli HECH QACHON rad etilmaydi. Sotuvga atalgan eski
#     doimiy shu bois olib tashlandi: ishlatilmaydigan, lekin «sotuv mana shunday
#     rad etiladi» deb turgan qiymat keyinchalik yanglishtirardi.
MANAGER_STATUS = 409


def http_assert_untracked(db: Session, product_ids, path: str,
                          status: int = MANAGER_STATUS) -> None:
    """`assert_untracked` + HTTP maqomi. Yagona tarjima nuqtasi."""
    from fastapi import HTTPException
    try:
        assert_untracked(db, product_ids, path)
    except TrackedProductNotSupported as e:
        raise HTTPException(status, str(e)) from e
