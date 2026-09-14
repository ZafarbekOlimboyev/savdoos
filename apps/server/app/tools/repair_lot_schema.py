# -*- coding: utf-8 -*-
"""SavdoOS Operations CLI · PARTIYA SXEMASI YAXLITLIGINI TUZATISH (Phase 4A).

    python -m app.tools.repair_lot_schema

NEGA ALOHIDA VOSITA. `initdb` boot paytida majburiy FK va CHECK'larni tuzatadi,
lekin HECH QACHON yiqilmaydi: qulf band bo'lsa, 30 soniyalik byudjet tugasa yoki
yetim qatorlar bo'lsa u faqat JURNALGA yozadi va tayyorlik QIZIL qoladi. Vaqtinchalik
sabab (uzun backup, anti-wraparound vacuum) uchun butun servisni qayta deploy
qilish ortiqcha — shu vosita AYNI idempotent qadamlarni AYNI qulf siyosati bilan
qayta yurgizadi.

HECH NARSA O'CHIRMAYDI va noto'g'ri shakldagi FK'ni TEGMAYDI: faqat yo'q FK'ni
NOT VALID qo'shadi va tasdiqlanmaganini VALIDATE qiladi. CHECK ta'rifi noto'g'ri
yoki NOT ENFORCED bo'lsa (Phase 4A.1) — `initdb` qoidasi bilan AYNI ALTER ichida
almashtiradi.

⚠️  YAKUNIY HOLAT `rs.missing` (soft EMAS) bo'yicha (Phase 4A.1 review): halokatli
    sinfdagi CHECK (`ck_track_expiry_implies_lots`) YO'Q qolsa, vosita «joyida» deb
    0 qaytarmasin.

Exit: 0 = yaxlitlik to'liq, 2 = hali tayyor emas (sabablari chop etiladi), 1 = xato.
"""
from __future__ import annotations


def main(argv=None) -> int:
    from app import initdb
    from app.core import required_schema as rs
    if initdb.engine.dialect.name != "postgresql":
        print("REFUSED: bu vosita faqat PostgreSQL'da ma'noli (SQLite'da FK/CHECK tuzatilmaydi).")
        return 1
    initdb._ensure_lot_checks()
    initdb._ensure_foreign_keys()
    initdb._relax_ret_alloc_uniqueness()
    left = rs.missing(initdb.engine)
    for s in left:
        print(f"[lot-schema] TAYYOR EMAS — {s}")
    if left:
        return 2
    print("[lot-schema] majburiy FK va CHECK'lar joyida")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
