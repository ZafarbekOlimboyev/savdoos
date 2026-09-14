# -*- coding: utf-8 -*-
"""CHECK ta'rifini TUZILMA bo'yicha solishtirish — sof Python, bazasiz (Phase 4A.1).

⚠️  NEGA. Tayyorlik CHECK'ni ilgari faqat (jadval, nom) bo'yicha topardi: to'g'ri
    nomli `CHECK (true)` YASHIL o'tardi. Endi `app.core.check_canon` Postgres
    yozuvini Postgres ustuvorligi bilan daraxtga tahlil qiladi. Bu fayl mahkamlaydi:
      1) HAQIQIY PG16 va PG18 yozuvlari (katalogdan olingan) kutilgan ta'rifga TENG —
         aks holda production tayyorligi yolg'on QIZIL bo'lardi;
      2) ma'nosi boshqa HAR BIR buzilish TENG EMAS: qavs, NOT joyi, > / >=, raqamli
         ustunni `::text` qilish (satr taqqoslash), uzunlikli/"char" literal keltirish
         ('netting'::varchar(3) aslida 'net'), qo'shtirnoqli (foydalanuvchi) tip nomlari,
         int va numeric literal (`2` / `2.0`), 28 raqamdan uzun sonlar;
      3) tanilmagan sintaksis «noto'g'ri» EMAS, «tekshirib bo'lmadi» (avtomatik
         qayta yaratilmaydi, lekin tayyorlik baribir QIZIL); juda uzun/chuqur ifoda TEZ rad
         etiladi; `check_definition_state` HECH QACHON istisno ko'tarmaydi;
      4) yangi tayyorlik xabarlari SOFT sinfida.
Ikki adversarial review (2026-09-14) topgan har bir yolg'on-yashil holat shu yerda qayd etilgan.
"""
import time

import pytest

from app.core import required_schema as rs
from app.core.check_canon import CanonError, canonical, same_check
from tests.check_renderings_pg import RENDERINGS

_REQUIRED = dict(rs.REQUIRED_PG_CONSTRAINTS)          # nom -> jadval
# Model va haqiqiy baza bo'yicha matn tipidagi ustunlar: lot_shortfall_resolutions.kind (varchar).
_TEXT = {"ck_lsr_kind": {"kind"}, "ck_lsr_netting_zero": {"kind"}}


def _state(name, expr):
    return rs.check_definition_state(name, expr, frozenset(_TEXT.get(name, ())))


def test_HAR_BIR_kutilgan_tarif_TAHLIL_qilinadi_va_royxat_MOS():
    assert set(rs.CHECK_DEFINITIONS) == set(_REQUIRED)
    for name, src in rs.CHECK_DEFINITIONS.items():
        canonical(src, text_columns=_TEXT.get(name, ()))


def test_HAR_BIR_majburiy_CHECK_uchun_HAQIQIY_yozuv_BOR():
    """Yangi majburiy CHECK qo'shilsa — uning haqiqiy PG yozuvi ham shu yerda bo'lsin."""
    have = {(r[1], r[2]) for r in RENDERINGS if r[0] == "public"}
    missing = [(t, n) for n, t in _REQUIRED.items() if (t, n) not in have]
    assert not missing, f"haqiqiy PG yozuvi yo'q: {missing}"


@pytest.mark.parametrize("row", [r for r in RENDERINGS if r[0] == "public" and r[2] in _REQUIRED],
                         ids=lambda r: r[2])
def test_HAQIQIY_PG_yozuvi_KUTILGAN_tarifga_TENG(row):
    _schema, table, name, plain, pretty = row
    assert _REQUIRED[name] == table
    assert _state(name, plain) == rs.CHECK_DEF_OK, plain
    assert _state(name, pretty) == rs.CHECK_DEF_OK, pretty


def test_TEXT_keltirish_FAQAT_haqiqiy_matn_ustunida_KECHIRILADI():
    """`(kind)::text` — kind varchar bo'lgani uchungina ma'nosiz. Ustun tipi noma'lum
    (yoki raqamli) bo'lsa, AYNI yozuv «noto'g'ri» — kanonizator taxmin qilmaydi."""
    plain = [r[3] for r in RENDERINGS if r[2] == "ck_lsr_kind"][0]
    assert rs.check_definition_state("ck_lsr_kind", plain, frozenset({"kind"})) == rs.CHECK_DEF_OK
    assert rs.check_definition_state("ck_lsr_kind", plain, frozenset()) == rs.CHECK_DEF_WRONG


def test_HAMMA_haqiqiy_yozuvlar_TAHLIL_qilinadi_va_oddiy_pretty_TENG():
    """`cash` cheklovlari tayyorlikka KIRMAYDI, lekin grammatika ular ustida ham
    sinaladi — enum keltirish, IS NULL, mantiqiy tenglik: haqiqiy chiqishga chidamlilik."""
    assert len(RENDERINGS) == 25
    for _schema, _table, name, plain, pretty in RENDERINGS:
        assert canonical(plain) == canonical(pretty), name


_BUZILISHLAR = [
    ("ck_track_expiry_implies_lots", "NOT (track_expiry OR track_lots)"),
    ("ck_track_expiry_implies_lots", "track_expiry OR track_lots"),
    ("ck_track_expiry_implies_lots", "NOT track_expiry AND track_lots"),
    ("ck_track_expiry_implies_lots", "NOT track_lots OR track_expiry"),
    ("ck_track_expiry_implies_lots", "true"),
    ("ck_lsr_qty_pos", "qty >= 0"),
    ("ck_lsr_qty_pos", "qty > 1"),
    ("ck_lsr_qty_pos", "qty > -1"),
    ("ck_lsr_qty_pos", "qty::integer > 0"),
    ("ck_lsr_qty_pos", "qty <> 0"),
    ("ck_lsr_qty_pos", "qty > 0 OR qty IS NULL"),
    ("ck_lsr_qty_pos", "qty > 0.5::integer"),                   # 0.5::integer = 1
    ("ck_lsr_qty_pos", "qty > 0.00000000000000000000000000001"),  # 29 raqam — yaxlitlanmaydi
    # re-review: int va numeric literal turli tip (fail-closed; Postgres `0` ni `0` yozadi)
    ("ck_lsr_qty_pos", "qty > 0.0"),
    ("ck_lsr_qty_pos", "qty > (0.0)::integer"),
    # re-review: qo'shtirnoqli tip nomi — shu nomli domen/foydalanuvchi tipi, o'rnatilgan EMAS
    ("ck_lsr_qty_pos", '(qty > (0)::"integer")'),
    ("ck_lsr_kind", "((kind)::text = ANY ((ARRAY[('real'::character varying)::\"character varying\", "
                    "('netting'::character varying)::\"character varying\"])::text[]))"),
    # review: raqamli ustun matnga keltirilsa taqqoslash SATR bo'yicha ('10.000' <= '9.000')
    ("ck_lsr_qty_pos", "((qty)::text > (0)::text)"),
    ("ck_risa_qty_pos", "(((qty)::character varying)::text > ((0)::character varying)::text)"),
    ("ck_lot_shortfall_resolved_le_qty", "((resolved_qty)::text <= (qty)::text)"),
    ("ck_lsr_variance_identity", "variance = actual_cost + provisional_cost"),
    ("ck_lsr_variance_identity", "variance = provisional_cost - actual_cost"),
    ("ck_lsr_variance_identity", "variance = actual_cost"),
    ("ck_lsr_variance_identity", "variance <= actual_cost - provisional_cost"),
    ("ck_lsr_variance_identity", "variance = (actual_cost - provisional_cost)::integer"),
    ("ck_lsr_kind", "kind IN ('real')"),
    ("ck_lsr_kind", "kind IN ('real', 'netting', 'x')"),
    ("ck_lsr_kind", "kind NOT IN ('real', 'netting')"),
    ("ck_lsr_kind", "kind::char(7) IN ('real', 'netting')"),
    ("ck_lsr_kind", "kind = ANY (ARRAY['real'])"),
    ("ck_lsr_kind", "kind IN ('real', 'netting') OR true"),
    # review: qiymatni KESADIGAN literal keltirish ('netting'::varchar(3) = 'net')
    ("ck_lsr_kind", "((kind)::text = ANY ((ARRAY['real'::character varying, "
                    "'netting'::character varying(3)])::text[]))"),
    ("ck_lsr_netting_zero", "kind <> 'netting' AND variance = 0"),
    ("ck_lsr_netting_zero", "kind = 'netting' OR variance = 0"),
    ("ck_lsr_netting_zero", "kind <> 'netting' OR variance <> 0"),
    ("ck_lsr_netting_zero", "kind <> 'netting' OR variance = 1"),
    ("ck_lsr_netting_zero", "(((kind)::text <> ('netting'::character varying(3))::text) "
                            "OR (variance = (0)::numeric))"),
    ("ck_lsr_netting_zero", "(((kind)::text <> ('netting'::text)::\"char\") OR (variance = (0)::numeric))"),
    ("ck_lsr_netting_zero", "kind <> 'netting'::bpchar OR variance = 0"),
    ("ck_lot_shortfall_resolved_le_qty", "resolved_qty < qty"),
    ("ck_lot_shortfall_resolved_le_qty", "resolved_qty <= qty + 1"),
    ("ck_lot_shortfall_resolved_le_qty", "qty <= resolved_qty"),
    ("ck_lot_shortfall_resolved_le_qty", "resolved_qty >= qty"),
]


@pytest.mark.parametrize("name,expr", _BUZILISHLAR)
def test_MANOSI_BOSHQA_tarif_TENG_EMAS(name, expr):
    assert _state(name, expr) == rs.CHECK_DEF_WRONG, expr


_TENGLAR = [
    ("ck_lot_shortfall_resolved_le_qty", "qty >= resolved_qty"),
    ("ck_lot_shortfall_resolved_le_qty", "(((resolved_qty)) <= (qty))"),
    ("ck_lsr_variance_identity", "actual_cost - provisional_cost = variance"),
    ("ck_lsr_kind", "kind IN ('netting', 'real')"),
    ("ck_lsr_kind", "(kind)::text = ANY ((ARRAY['netting'::text, 'real'::text])::text[])"),
    ("ck_lsr_qty_pos", "0 < qty"),
    ("ck_lsr_qty_pos", "qty > 00"),
    ("ck_lsr_qty_pos", "qty > (0)::numeric"),
    ("ck_lsr_qty_pos", "qty > (0)::integer"),
    ("ck_lsr_netting_zero", "variance = 0 OR kind != 'netting'"),
]


@pytest.mark.parametrize("name,expr", _TENGLAR)
def test_MANOSI_BIR_XIL_yozuv_TENG(name, expr):
    assert _state(name, expr) == rs.CHECK_DEF_OK, expr


_TANILMAGAN = [
    "abs(qty) > 0",
    "CASE WHEN kind = 'real' THEN true ELSE false END",
    "qty BETWEEN 1 AND 2",
    "E'x' = kind",
    "kind IS DISTINCT FROM 'x'",
    "cash.shifts.status = 'x'",
    # review: tip nomi operator so'zlarini yutib yubormasin
    "'2020-01-01'::timestamp at time zone kind = kind",
    "qty > 0 AND",
    "(qty > 0",
    "qty > 0)",
    "qty > 0 %",
    "(" * 60 + "qty > 0" + ")" * 60,
    "NOT " * 60 + "true",
    # re-review: sikl bilan quriladigan uzun zanjirlar — rekursiya/kvadratik vaqt o'rniga rad
    "qty" + "::numeric(1)" * 400 + " > 0",
    "qty" + " - qty" * 800 + " > 0",
    "qty > " + " + ".join(f"a{i}" for i in range(2000)),
    "",
    "   ",
]


@pytest.mark.parametrize("expr", _TANILMAGAN, ids=lambda e: e[:40])
def test_TANILMAGAN_sintaksis_TEKSHIRIB_BOLMADI_noto_g_ri_EMAS(expr):
    with pytest.raises(CanonError):
        canonical(expr)
    assert rs.check_definition_state("ck_lsr_qty_pos", expr) == rs.CHECK_DEF_UNPARSED


def test_UZUN_ifoda_TEZ_rad_etiladi():
    """re-review: 3000 hadli `+` zanjiri 3.7 s, 20000 hadli — 120 s dan oshardi."""
    expr = "qty > " + " + ".join(f"a{i}" for i in range(20000))
    t0 = time.monotonic()
    with pytest.raises(CanonError):
        canonical(expr)
    assert time.monotonic() - t0 < 2.0


def test_holat_funksiyasi_HECH_QACHON_istisno_KOTARMAYDI(monkeypatch):
    """review: kanonizatordagi kutilmagan xato (RecursionError) `_fatal` orqali boot'ni
    crash-loop'ga tushirmasin — «tekshirib bo'lmadi» bo'lib qoladi."""
    import app.core.check_canon as cc

    def boom(*a, **k):
        raise RecursionError("chuqur")
    monkeypatch.setattr(cc, "same_check", boom)
    assert rs.check_definition_state("ck_lsr_qty_pos", "qty > 0") == rs.CHECK_DEF_UNPARSED


def test_USTUVORLIK_va_LITERAL_tipi_Postgres_bilan_MOS():
    assert canonical("NOT a = b") == canonical("NOT (a = b)")
    assert canonical("a = b IS NULL") == canonical("(a = b) IS NULL")
    assert canonical("a OR b AND c") == canonical("a OR (b AND c)")
    assert canonical("a OR b AND c") != canonical("(a OR b) AND c")
    assert canonical("a - b - c") == canonical("(a - b) - c")
    assert canonical("a - b - c") != canonical("a - (b - c)")
    assert canonical("-qty::numeric > 0") == canonical("-(qty::numeric) > 0")
    assert canonical("a IS NOT NULL") != canonical("a IS NULL")
    assert same_check("x > 0", "x > 0::double precision") is False
    # re-review: `x / 2` butun bo'linish, `(1.50)::text` = '1.50' satri
    assert canonical("x / 2 = y") != canonical("x / 2.0 = y")
    assert canonical("kind = (1.50)::text") != canonical("kind = (1.5)::text")
    assert canonical("x = 00.10") == canonical("x = 0.10")


def test_tayyorlik_XABARLARI_hammasi_SOFT_sinfida():
    wrong = rs.CheckState(validated=False, enforced=False, definition=rs.CHECK_DEF_WRONG)
    unparsed = rs.CheckState(validated=True, enforced=True, definition=rs.CHECK_DEF_UNPARSED)
    msgs = (rs.check_problems("ck_lsr_qty_pos", "lot_shortfall_resolutions", wrong)
            + rs.check_problems("ck_lsr_qty_pos", "lot_shortfall_resolutions", unparsed))
    assert len(msgs) == 4, msgs
    for m in msgs:
        assert rs.is_soft(m), f"soft sinfida EMAS — lot_schema_integrity yashil qolardi: {m}"
    assert rs.check_problems("x", "t", rs.CheckState(True, True, rs.CHECK_DEF_OK)) == []
