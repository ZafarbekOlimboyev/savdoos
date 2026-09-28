# -*- coding: utf-8 -*-
"""`source_copy` — QAYSI nusxadan chiqarilgani (provenans).

NIMANI ISBOTLAYDI VA NIMANI YO'Q — bu farq butun blokning ma'nosi:

    `sha256` QAYSI nusxa artefakti ishlatilganini isbotlaydi.
    U o'sha nusxa QACHON olinganini ISBOTLAMAYDI.

Qachonligi operator boshqaradigan yozma qaydda qoladi (`SANDBOX_RESTORE_RUNBOOK.md`, 1-bo'lim).
Shu bois uchta himoya ALOHIDA: yangilik darvozasi (e'lon qilingan yosh) · provenans (qaysi nusxa) ·
yozma qayd (qachon olingan). Biri ikkinchisining o'rnini bosmaydi.

⚠️ BinOS `.dt` / `1Cv8.1CD` faylini hech qachon ko'rmaydi — `sha256` va `byte_size` ni server
TEKSHIRA OLMAYDI. Ular DA'VO; kod faqat shaklni va kesim bilan moslikni kafolatlaydi.
"""
import pytest

from app.services.migrator_1c import bundle as B
from tests.migrator_1c_helpers import (as_utc, bundle_dict, default_snapshot, g, load, prod,
                                       source_copy_for)

S0 = default_snapshot()
SHA = "a1b2c3d4" * 8          # 64 hex


def _b(**over):
    sc = source_copy_for(S0)
    sc.update(over)
    return bundle_dict([prod(g(1), "Tovar")], snapshot_at=S0, source_copy=sc)


def test_togri_blok_qabul_qilinadi():
    b = load(_b(sha256=SHA))
    assert b.data["source_copy"]["sha256"] == SHA
    assert b.data["source_copy"]["copy_method"] == "DT_EXPORT"


# ── Majburiylik ────────────────────────────────────────────────────────────────────────────
def test_blok_YOQ_bolsa_RAD():
    """Bu `binos-1c-v1` ning MAJBURIY maydoni — yo'qligi degradatsiya rejimi emas, xato."""
    d = bundle_dict([prod(g(1), "Tovar")], snapshot_at=S0)
    d.pop("source_copy")
    with pytest.raises(B.BundleError, match="source_copy YO'Q"):
        load(d)


@pytest.mark.parametrize("key", sorted(B.SOURCE_COPY_KEYS))
def test_ichki_kalit_YOQ_bolsa_RAD(key):
    sc = source_copy_for(S0)
    sc.pop(key)
    d = bundle_dict([prod(g(1), "Tovar")], snapshot_at=S0, source_copy=sc)
    with pytest.raises(B.BundleError, match="yetishmayapti"):
        load(d)


def test_notanish_ichki_kalit_RAD():
    with pytest.raises(B.BundleError, match="noma'lum kalit"):
        load(_b(qoshimcha="x"))


# ── sha256 ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "A1B2C3D4" * 8,                 # KATTA harf — `Get-FileHash` shunday chiqaradi
    "a1b2c3d4" * 7,                 # qisqa
    "a1b2c3d4" * 8 + "aa",          # uzun
    "z" * 64,                       # hex emas
    " " + "a" * 64,                 # chekka probel
    "",
])
def test_sha256_shakli_qatiy(bad):
    with pytest.raises(B.BundleError, match="sha256"):
        load(_b(sha256=bad))


def test_sha256_KATTA_harf_xatosi_sababni_AYTADI():
    """PowerShell `Get-FileHash` KATTA harfda chiqaradi — xato xabari buni ochiq aytishi kerak."""
    with pytest.raises(B.BundleError, match="Get-FileHash"):
        load(_b(sha256="A" * 64))


# ── byte_size ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["0", "007", "-1", "1.5", "1 000", "", "1e9"])
def test_byte_size_shakli_qatiy(bad):
    with pytest.raises(B.BundleError, match="byte_size"):
        load(_b(byte_size=bad))


def test_byte_size_JSON_soni_bolsa_RAD():
    """Qoida 1: sanoq MATN. Son berilsa, uni maydon validatori emas — QAT'IY JSON o'quvchisi
    tutadi, ya'ni fayl hatto tuzilma tekshiruvigacha ham yetib bormaydi."""
    d = _b()
    d["source_copy"]["byte_size"] = 3221225472
    with pytest.raises(B.BundleError, match="JSON son"):
        load(d)


def test_nol_baytli_nusxa_RAD():
    """Nol baytli artefakt baza fayli emas — regexning o'zi buni tutadi."""
    with pytest.raises(B.BundleError, match="byte_size"):
        load(_b(byte_size="0"))


# ── copy_method / original_artifact_type ──────────────────────────────────────────────────
@pytest.mark.parametrize("method", list(B.COPY_METHODS))
def test_tanilgan_usullar_qabul(method):
    assert load(_b(copy_method=method)) is not None


@pytest.mark.parametrize("bad", ["dt_export", "BACKUP", "", "DT EXPORT", None])
def test_notanish_usul_RAD(bad):
    with pytest.raises(B.BundleError, match="copy_method"):
        load(_b(copy_method=bad))


@pytest.mark.parametrize("bad", ["DT", "", "d t", "x" * 40])
def test_artefakt_turi_shakli(bad):
    with pytest.raises(B.BundleError, match="original_artifact_type"):
        load(_b(original_artifact_type=bad))


def test_faylbaza_nusxasi_ham_BITTA_fayl_xeshi():
    """Papkada yagona xesh bo'lmaydi, shu bois fayl bazasida AYNAN `1Cv8.1CD` xeshlanadi."""
    b = load(_b(copy_method="FILEBASE_COPY", original_artifact_type="1cd"))
    assert b.data["source_copy"]["original_artifact_type"] == "1cd"


# ── Kesim bilan moslik ─────────────────────────────────────────────────────────────────────
def test_kesim_MOS_kelmasa_RAD():
    """Ekstraktor bog'liq bo'lmagan yangi kesim vaqtini o'ylab chiqara olmaydi."""
    from datetime import datetime, timedelta
    other = (datetime.fromisoformat(S0) + timedelta(seconds=1)).isoformat()
    with pytest.raises(B.BundleError, match="AYNI LAHZA"):
        load(_b(source_snapshot_at=other))


def test_bir_MIKROSEKUND_farq_ham_RAD():
    from datetime import datetime, timedelta
    other = (datetime.fromisoformat(S0) + timedelta(microseconds=1)).isoformat()
    with pytest.raises(B.BundleError, match="AYNI LAHZA"):
        load(_b(source_snapshot_at=other))


def test_BOSHQA_OFSET_ayni_lahza_bolsa_QABUL():
    """UTC ga keltirgan ekstraktor xato qilmagan — solishtirish LAHZA bo'yicha."""
    assert load(_b(source_snapshot_at=as_utc(S0))) is not None


def test_kesim_vaqti_shakli_buzuq_bolsa_RAD():
    with pytest.raises(B.BundleError, match="source_copy.source_snapshot_at"):
        load(_b(source_snapshot_at="20.09.2026 09:00"))


def test_kesim_vaqti_ZONASIZ_bolsa_RAD():
    with pytest.raises(B.BundleError, match="vaqt zonasi"):
        load(_b(source_snapshot_at=S0.split("+")[0]))


# ── Xesh siyosati ──────────────────────────────────────────────────────────────────────────
def test_provenans_MAZMUN_xeshiga_KIRMAYDI():
    """Bir xil 1C holatining ikki NUSXAsidan chiqarilgan bundle — AYNI mazmun.

    `source_copy` — artefakt haqidagi ma'lumot, HOLAT haqida emas; `infobase` va `extractor`
    kabi u ham mazmun xeshidan tashqarida. Shu tufayli takroriy apply darvozasi (`AlreadyApplied`)
    nusxa almashgani uchun ochilib ketmaydi."""
    a = load(_b(sha256="a" * 64))
    b = load(_b(sha256="b" * 64, byte_size="999999"))
    assert a.content_sha256 == b.content_sha256
    assert a.file_sha256 != b.file_sha256          # fayl esa boshqa — snapshot_id ham boshqa
