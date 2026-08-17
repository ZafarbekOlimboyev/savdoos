"""Ikkala dialektga mos tiplar: PostgreSQL (production) va SQLite (demo/lokal kassa).

- UUID: PG'da native uuid, SQLite'da CHAR(32)
- JSONB: PG'da jsonb, SQLite'da json (TEXT)

Shu tufayli bitta model kodi ham serverda (Postgres), ham demo/kassada (SQLite) ishlaydi.
"""
from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB as _PGJSONB


class UUID(Uuid):
    """PG `UUID(as_uuid=...)` bilan bir xil imzo, lekin cross-dialect."""

    def __init__(self, as_uuid: bool = True, **kw):
        super().__init__(as_uuid=as_uuid, **kw)


# PG'da JSONB, SQLite'da oddiy JSON
JSONB = _PGJSONB().with_variant(JSON(), "sqlite")
