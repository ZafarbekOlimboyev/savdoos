# -*- coding: utf-8 -*-
"""S1-F9F — kalitlangan IP chelagi HAQIQIY PostgreSQL da.

NEGA PG KERAK (SQLite bu savollarga javob BERMAYDI):
  · `varchar(128)` CHEGARASI — SQLite uzunlikni UMUMAN majburlamaydi, ya'ni
    "chelak ustunga sig'adi" degan da'vo SQLite'da isbotlanmaydi.
  · INDEKS — `bucket` ustida indeks borligi va yangi qiymat shakli bilan ham
    ishlashini faqat `pg_indexes` ko'rsatadi.
  · PURGE PREDIKATI — `"company_id" = :cid` ning NULL ustidagi UCH QIYMATLI
    mantiqi (UNKNOWN) aynan PG semantikasi; S1-F9B/F9C shu ustiga qurilgan.
  · TTL OBYEKTI — jadvalda trigger/rule YO'Qligini faqat `pg_trigger` va
    `pg_rules` isbotlaydi.

⚠️  PRODUKSIYA MA'LUMOTI YO'Q: butun sxema shu testda ko'tariladi va har
    qator shu yerda yaratiladi. Manzillar SINTETIK.
"""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import ratelimit as RL

pgserver = pytest.importorskip("pgserver")

IP4 = "84.54.70.21"
IP4_B = "84.54.70.22"
IP6 = "2a00:1450:4001:80e::200e"


def _norm(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    from app.db.base import Base
    import app.models  # noqa: F401

    srv = pgserver.get_server(str(tmp_path_factory.mktemp("f9f_ip_pg")))
    eng = create_engine(_norm(srv.get_uri()), future=True)
    Base.metadata.create_all(eng)
    SessionLocal = sessionmaker(bind=eng, future=True)
    yield SessionLocal
    eng.dispose()


@pytest.fixture(autouse=True)
def _toza(pg):
    with pg() as s:
        s.execute(text("DELETE FROM auth_attempts"))
        s.execute(text("DELETE FROM vendor_auth_attempts"))
        s.commit()


# ══ PG1) Ustun chegarasi, indeks va round-trip ═════════════════════════════

def test_PG1_chelak_varchar128_ga_sigadi_INDEKS_bor_va_ROUND_TRIP(pg):
    """Har bir yo'l uchun yozib-o'qish; ustun uzunligi va indeks o'lchanadi."""
    with pg() as s:
        uzunlik = s.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='auth_attempts' "
            "  AND column_name='bucket'")).scalar()
        assert uzunlik == 128, uzunlik
        indekslar = [r[0] for r in s.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='auth_attempts'")).all()]
        assert any("(bucket)" in d for d in indekslar), indekslar

        chelaklar = {yol: RL.ip_bucket(yol, IP6) for yol in sorted(RL.IP_PATHS)}
        for yol, b in chelaklar.items():
            assert len(b) <= uzunlik, (yol, len(b))
        RL.record(s, [("ip", b, None) for b in chelaklar.values()])

        for yol, b in chelaklar.items():
            assert RL._count(s, "ip", b, 300) == 1, (yol, b)
        #  XOM manzil hech bir qatorda YO'Q (PG tomonda ham o'lchanadi).
        xom = s.execute(text(
            "SELECT count(*) FROM auth_attempts WHERE bucket LIKE :p"),
            {"p": "%" + IP6 + "%"}).scalar()
        assert xom == 0, "xom IPv6 PG qatorida topildi"


# ══ PG2) Tenglik semantikasi: sanoq va tozalash ════════════════════════════

def test_PG2_TENGLIK_semantikasi_PG_da_AYNAN_ishlaydi(pg):
    """`_count` faqat AYNI chelakni sanaydi, `clear` faqat uni o'chiradi."""
    a = RL.ip_bucket("pin", IP4)
    b = RL.ip_bucket("pin", IP4_B)
    with pg() as s:
        RL.record(s, [("ip", a, None)] * 3 + [("ip", b, None)] * 2)
        assert RL._count(s, "ip", a, 300) == 3
        assert RL._count(s, "ip", b, 300) == 2
        #  Boshqa o'lchovda AYNI qiymat — sanalmaydi (dimension ham kalit).
        assert RL._count(s, "acct", a, 900) == 0

        RL.clear(s, [("ip", a, None)])
        assert RL._count(s, "ip", a, 300) == 0
        assert RL._count(s, "ip", b, 300) == 2, (
            "`clear` begona chelakni ham o'chirdi")


# ══ PG3) Purge hikoyasi O'ZGARMADI ═════════════════════════════════════════

def test_PG3_ip_qatorlari_PURGE_predikatidan_OMON_QOLADI(pg):
    """F9F purge semantikasiga TEGMAYDI — bu ataylab va qayd etiladi.

    `ip` qatorlari `company_id=NULL` bilan yoziladi, `tenant_purge` predikati
    esa `"company_id" = :cid`. PG uch qiymatli mantiqida NULL = :cid ->
    UNKNOWN, ya'ni qator TANLANMAYDI va «nol qoldiq» tekshiruvi ham uni
    KO'RMAYDI (u AYNI predikatni qayta ishlatadi).

    Ya'ni: chelak endi kalitlangan, LEKIN qator do'kon o'chirilgandan keyin
    ham qoladi. Uni faqat SAQLASH MUDDATI (`_prune`) olib tashlaydi.
    """
    cid = uuid.uuid4()
    with pg() as s:
        RL.record(s, [("ip", RL.ip_bucket("pin", IP4), None)] * 2)
        mos = s.execute(text(
            'SELECT count(*) FROM auth_attempts WHERE "company_id" = :cid'),
            {"cid": str(cid)}).scalar()
        assert mos == 0, "purge predikati NULL qatorni TANLADI — semantika o'zgardi"
        jami = s.execute(text("SELECT count(*) FROM auth_attempts")).scalar()
        assert jami == 2, jami


# ══ PG4) Vendor jadvalida TTL OBYEKTI yo'q ═════════════════════════════════

def test_PG4_vendor_jadvalida_TRIGGER_ham_RULE_ham_YOQ(pg):
    """«TTL yo'q» da'vosi BAZA tomonidan ham tasdiqlanadi.

    Manba darajasidagi isbot `tests/test_retention_registry.py::test_F16c` da
    (butun `app/` da `VendorAuthAttempt` uchun o'chirish yo'q). Bu yerda
    BAZA tomonini o'lchaymiz: avtomatik tozalaydigan trigger yoki rule ham
    YO'Q, ya'ni qator haqiqatan MUDDATSIZ qoladi.
    """
    with pg() as s:
        trig = [r[0] for r in s.execute(text(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE NOT t.tgisinternal AND n.nspname='public' "
            "  AND c.relname='vendor_auth_attempts'")).all()]
        assert trig == [], trig
        rules = [r[0] for r in s.execute(text(
            "SELECT rulename FROM pg_rules "
            "WHERE schemaname='public' AND tablename='vendor_auth_attempts'")).all()]
        assert rules == [], rules
        #  ⚠️  POZITIV NAZORAT (mustaqil ko‘rik talab qildi): yuqoridagi ikki
        #      tasdiq fikstura `Base.metadata.create_all` bilan qurilgani uchun
        #      QURILISH BO‘YICHA yashil edi — SQLAlchemy trigger/rule DDL
        #      chiqarmaydi, ya’ni ular hech qachon yiqila olmasdi. Quyida
        #      so‘rovlarning O‘ZI haqiqatan obyekt KO‘RA olishi isbotlanadi.
        s.execute(text(
            "CREATE RULE f9f_sinov_rule AS ON DELETE TO vendor_auth_attempts "
            "DO INSTEAD NOTHING"))
        s.commit()
        try:
            qayta = [r[0] for r in s.execute(text(
                "SELECT rulename FROM pg_rules "
                "WHERE schemaname='public' AND tablename='vendor_auth_attempts'")).all()]
            assert "f9f_sinov_rule" in qayta, (
                "so‘rov RULE ni KO‘RMAYDI — yuqoridagi «rule yo‘q» tasdig‘i "
                "hech narsa o‘lchamasdi")
        finally:
            s.execute(text("DROP RULE f9f_sinov_rule ON vendor_auth_attempts"))
            s.commit()
        #  Vakuumga qarshi: jadval HAQIQATAN mavjud va yozuv qabul qiladi.
        s.execute(text(
            "INSERT INTO vendor_auth_attempts (bucket, reason, occurred_at) "
            "VALUES (:b, 'key', now())"), {"b": RL.ip_bucket("ip", IP4)})
        s.commit()
        assert s.execute(text(
            "SELECT count(*) FROM vendor_auth_attempts")).scalar() == 1
