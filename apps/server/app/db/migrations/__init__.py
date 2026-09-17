# -*- coding: utf-8 -*-
"""ANIQ, VERSIYALANGAN SXEMA MIGRATSIYALARI — reyestr.

⚠️  BU BOOT YO'LI EMAS. `python -m app.initdb` bu paketni CHAQIRMAYDI: boot faqat yo'q
    obyektni qo'shadi va tip og'ishini TAYYORLIKDA ko'rsatadi (`required_schema.
    column_type_problems` -> `/health/ready` 503). Mavjud ustunning TIPINI o'zgartirish
    (jadvalni qayta yozish, har indeksni qayta qurish, ACCESS EXCLUSIVE) — OPERATOR qarori:

        python -m app.tools.schema_migrate list
        python -m app.tools.schema_migrate preflight --migration <id> --out report.json
        python -m app.tools.schema_migrate apply --migration <id> --report report.json \
            --expect-system-identifier <sysid> --rehearse
        python -m app.tools.schema_migrate apply ... --commit
        python -m app.tools.schema_migrate verify --migration <id>

⚠️  VERSIYA JADVALI YO'Q (`initdb.py:1` — «Alembic o'rniga tez yo'l»). Yagona haqiqat —
    KATALOG holati: `pg_attribute` dagi tip. Restore, qo'lda DDL yoki revert'dan keyin
    ham u yolg'on gapira olmaydi; hisobot jadvali esa gapirardi. Dalil operator saqlaydigan
    JSON hisobotlarda (`plan_sha256`, baza identiteti, digest'lar) qoladi.
"""
from __future__ import annotations

from . import m2026_09_17_uuid_client_columns as _uuid_client_columns

MIGRATIONS = {_uuid_client_columns.MIGRATION_ID: _uuid_client_columns}


def ids() -> list[str]:
    return sorted(MIGRATIONS)


def get(migration_id: str):
    """Ro'yxatdagi migratsiya moduli. Noma'lum id -> KeyError (CLI uni usage xatosi qiladi)."""
    try:
        return MIGRATIONS[str(migration_id).strip()]
    except KeyError:
        raise KeyError(f"noma'lum migratsiya: {migration_id!r} (mavjud: {', '.join(ids())})") from None
