# -*- coding: utf-8 -*-
"""SXEMA-XABARDOR GARDNING KONTRAKTI — klaster KERAK EMAS (sof Python).

Bu fayl `test_multischema_guard_pg.py` ning arzon yarmi: u yerda haqiqiy katalog
o'lchanadi, bu yerda esa KELAJAKDAGI o'zgarishni to'sadigan INVARIANTLAR qadab
qo'yiladi. Ikkisi boshqa-boshqa savolga javob beradi.
"""
from __future__ import annotations

import inspect

from app.core import index_guard as ig
from app.core import required_schema as rs


# ══ 1. SXEMA API'DA VA KESH KALITIDA ═══════════════════════════════════════

def test_SXEMA_parametri_va_STANDART_qiymat():
    """Standart `public` — 12 ta mavjud `require_index` chaqiruvi sxema UZATMAYDI.

    ⚠️  STANDART QIYMAT O'ZGARSA butun jonli pul yo'li (sotuv, qaytarish, qabul,
        xarid, kassa amali, smena ochish) HAR so'rovda 409 olardi: ularning
        indekslari `public` da, so'rov esa boshqa sxemaga ketardi.
    """
    for fn in (ig.index_state, ig.index_healthy, ig.require_index):
        p = inspect.signature(fn).parameters.get("schema")
        assert p is not None, f"{fn.__name__} da `schema` yo'q"
        assert p.default == "public", (fn.__name__, p.default)
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{fn.__name__}: `schema` pozitsion bo'lsa mavjud chaqiruvchining "
            f"`operation=` argumenti bilan chalkashardi")
    for fn in (rs._unique_index_states, rs.index_definition_states):
        p = inspect.signature(fn).parameters.get("schema")
        assert p is not None and p.default == rs.PUBLIC_SCHEMA, fn.__name__


def test_KESH_KALITIDA_sxema_BOR():
    """⚠️  BU TESTNI O'CHIRMANG. Kesh kalitida sxema bo'lmasa bitta sxemaning
        hukmi TTL davomida boshqasiga qo'llanardi. `shifts` jadvali public'da HAM,
        cash'da HAM bor, ya'ni bu nazariy emas — haqiqiy PG'da o'lchangan
        (`test_multischema_guard_pg.test_PG_KESH_ayni_nomni_SXEMA_boyicha_AJRATADI`).
    """
    src = inspect.getsource(ig.index_state)
    assert "key = (id(bind), schema, index, table)" in src, (
        "kesh kaliti sxemani o'z ichiga olmaydi:\n" + src[:400])
    #  Tip e'loni ham to'rt a'zoli bo'lsin — kalit shakli hujjatlashtirilgan qoladi.
    mod = inspect.getsource(ig)
    assert "_cache: dict[tuple[int, str, str, str], tuple[float, str]]" in mod


# ══ 2. REGISTRLAR SXEMAGA BOG'LANGAN, LEKIN QAYTA LOYIHALANMAGAN ═══════════

def test_REGISTR_SHAKLI_ozgarmadi():
    """Yozuv shakli AYNI: {nom: (jadval, ustunlar, predikat)} — 3 a'zoli tuple.

    ⚠️  4-a'zo (sxema) qo'shish REGISTR QAYTA LOYIHALASH bo'lardi: `required_schema`
        va testlardagi har bir ochish joyi (`for nm, (tbl, cols, pred) in ...`)
        buzilardi. Sxema CHAQIRUV bilan keladi, registr qatori bilan EMAS.
    """
    for registr in (rs.REQUIRED_INDEX_DEFINITIONS, rs.CASH_INDEX_DEFINITIONS):
        for nm, qiymat in registr.items():
            assert isinstance(qiymat, tuple) and len(qiymat) == 3, (nm, qiymat)
            tbl, cols, pred = qiymat
            assert isinstance(tbl, str) and "." not in tbl, (
                f"{nm}: jadval nomi KVALIFIKATSIYALANMAGAN bo'lishi shart "
                f"(sxema alohida uzatiladi), topildi: {tbl!r}")
            assert isinstance(cols, tuple) and cols, (nm, cols)
            assert pred is None or isinstance(pred, str), (nm, pred)


def test_SXEMA_XARITASI_registrlarga_MOS():
    assert rs.definitions_for("public") is rs.REQUIRED_INDEX_DEFINITIONS
    assert rs.definitions_for("cash") is rs.CASH_INDEX_DEFINITIONS
    #  Noma'lum sxema -> BO'SH (shakl tekshirilmaydi; noyoblik baribir tekshiriladi).
    for yoq in ("", "zz_yoq", "PUBLIC", "Cash"):
        assert rs.definitions_for(yoq) == {}, yoq


def test_REGISTR_NOMLARI_SXEMALAR_ORASIDA_KESISHMAYDI():
    """⚠️  BU ENG MUHIM KONTRAKT. `schema` standarti `public` bo'lgani uchun
        UNUTILGAN kalit xato EMAS — u jimgina `public` ni zondlaydi. Nom FAQAT
        bitta sxemada bo'lsa bu fail-closed (public'da obyekt yo'q -> BAD -> 409).
        Lekin AYNI nom IKKALA sxemada ham bo'lsa, unutilgan kalit FAIL-OPEN
        bo'lardi: public nusxasi sog'lom bo'lgani uchun cash'dagi YO'Q kafolat
        «bor» deb javob olardi.
        Shu bois nomlar KESISHMASLIGI — konvensiya emas, QADAB QO'YILGAN shart.
    """
    kesishma = set(rs.REQUIRED_INDEX_DEFINITIONS) & set(rs.CASH_INDEX_DEFINITIONS)
    assert not kesishma, (
        f"ayni indeks nomi ikki sxema registrida: {sorted(kesishma)} — "
        f"unutilgan `schema=` argumenti endi FAIL-OPEN bo'lardi")
    #  Noyoblik ro'yxatlari bilan ham kesishmasin (ular ham public zondlari).
    for nom, royxat in (("REQUIRED_INDEXES", rs.REQUIRED_INDEXES),
                        ("IDEMPOTENCY_INDEXES", rs.IDEMPOTENCY_INDEXES),
                        ("OPTIONAL_UNIQUE_INDEXES", rs.OPTIONAL_UNIQUE_INDEXES)):
        public_nomlar = {n for n, _ in royxat}
        k = public_nomlar & set(rs.CASH_INDEX_DEFINITIONS)
        assert not k, (nom, sorted(k))


# ══ 3. TAYYORLIK PUBLIC-ONLY — ATAYLAB, VA BU QOLDIQ ═══════════════════════

def test_TAYYORLIK_cash_shakllarini_CHIQARMAYDI():
    """⚠️  MA'LUM QOLDIQ, ATAYLAB: noto'g'ri shaklli CASH indeksi `/health/ready` ga
        CHIQMAYDI. Sabab — tayyorlik satrlari ishlab turgan do'konni QIZIL qiladi
        va cash sxemasi turli deployment'larda turli vaqtda qurilgan; bitta
        noto'g'ri ko'chirilgan registr yozuvi jonli do'konni soxta qizil qilardi.
        Cash tayyorligining O'Z moduli bor (`services/cash/schema_readiness.py`) —
        shakl tekshiruvini U YERGA qo'shish alohida qaror.
    ⚠️  Bu fail-open EMAS: gard sxema aytilganda yozuvni BARIBIR to'sadi
        (`test_multischema_guard_pg.test_PG_XATO_SXEMA_matritsasi`). Faqat
        operatorga tayyorlikda iz qolmaydi.
    """
    src = inspect.getsource(rs.index_definition_problems)
    assert "REQUIRED_INDEX_DEFINITIONS" in src, src[:300]
    assert "CASH_INDEX_DEFINITIONS" not in src and "definitions_for" not in src, (
        "tayyorlik cash registrini o'qiyapti — bu `/health/ready` xulqini "
        "o'zgartiradi va alohida qaror talab qiladi:\n" + src[:400])
    assert "schema=" not in src, src[:300]


def test_SIMLANGAN_yozuvchilar_hali_CASH_ni_SORAMAYDI():
    """Bu fazada HECH BIR yozuvchi cash gardiga simlanmadi — qaror dalil bilan.

    ⚠️  Freymvork TAYYOR, lekin simlash ALOHIDA: `cash` obyektlari bugun
        `DUAL_WRITE_SHADOW` da avtoritet EMAS, va cash sxemasining muammosi
        legacy pul yo'lini to'smasligi kerak (`services/cash/schema_readiness.py`
        ning e'lon qilingan qattiqlik siyosati). Simlash `LEDGER_PRIMARY`
        cutover'ining sharti sifatida qoldirildi.
    ⚠️  AGAR kelajakda simlansa: shu test YIQILADI va bu ATAYLAB — simlash
        qarori hujjat bilan birga o'zgartirilishi SHART.
    """
    import pathlib
    kok = pathlib.Path(inspect.getfile(rs)).parent.parent     # app/
    topildi = []
    for yol in kok.rglob("*.py"):
        if yol.name in ("index_guard.py",):
            continue
        matn = yol.read_text(encoding="utf-8", errors="replace")
        if "require_index(" in matn and 'schema="cash"' in matn:
            topildi.append(str(yol.relative_to(kok)))
    assert not topildi, f"cash gardi simlangan, lekin qaror hujjatlashtirilmagan: {topildi}"
