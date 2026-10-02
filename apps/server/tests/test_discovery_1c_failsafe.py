# -*- coding: utf-8 -*-
"""FAIL-SAFE TALQINI — sintetik runtime paketlari ustida (§6, §10).

⚠️⚠️ HAMMA FIKSTURA SINTETIK (`tests/discovery_1c_runtime_mock.py`). Bu fayl BinOS tomonidagi
     O'RASH MANTIG'INI isbotlaydi: validator qanday hukm chiqaradi va fail-safe qoidalar
     ROSTDAN majburlanadimi. U yig'uvchining haqiqiy 1C da ishlashini ISBOTLAMAYDI va bunday
     da'vo QILMAYDI — `.epf` hech qachon kompilyatsiya qilinmagan, yig'uvchining runtime
     holati `RUNTIME-UNKNOWN`.

ISBOTLANADIGAN INVARIANTLAR:
  · HALOL paket o'tadi — yiqilishi BOR paket ham, agar yiqilish sababi bilan qayd etilgan
    bo'lsa (`PARTIAL` NUQSON EMAS);
  · YOLG'ON `SUCCESS` (majburiy artefakt yo'q) ZIDDIYAT deb belgilanadi — §6;
  · yarim yozilgan hujjat JSON PARSE sababi bilan rad etiladi, xesh MOS bo'lsa ham;
  · manifest xeshi mos kelmasa — rad;
  · sir oqib ketsa — rad, va QIYMATNING O'ZI hisobotda ham, operator ekranida ham
    KO'RINMAYDI;
  · `absent` (JAVOB) QABUL qilinadi, `unreadable` (javob YO'QLIGI) esa `PARTIAL` bo'lib
    qoladi va `UNKNOWN` HECH QACHON `NOT_FOUND` deb talqin qilinmaydi;
  · obyekt darajasidagi xatolar YO'QOLMAYDI — hammasi `errors.json` da;
  · ULKAN paket o'tadi va hisobot DETERMINISTIK;
  · g'alati, lekin SHAKLAN QONUNIY nomlar bilan graf QURILADI; qonuniy BO'LMAGAN nom esa
    SABABI bilan RAD etiladi — JIMGINA TASHLANMAYDI.

ATAYLAB SINALMAYDI:
  · fikstura ichidagi 1C nomlarining MA'NOSI — validator talqin qilmaydi;
  · `.bsl` yig'uvchisining haqiqiy chiqishi — bu fayl uni BAJARMAYDI.
"""
from __future__ import annotations

import io
import json
import pathlib
import time

import pytest

from app.services.discovery_1c import cli
from app.services.discovery_1c import runtime_bundle as rb
from tests import discovery_1c_runtime_mock as mock
from tests.discovery_1c_runtime_mock import (HAMMA_GENERATORLAR, QABUL_GENERATORLAR,
                                             RAD_GENERATORLAR, SIR_QIYMATLAR)


# ── Yordamchilar ───────────────────────────────────────────────────────────────────────────
def hisobot(papka: str) -> rb.Report:
    """Paketni DISKDAN tekshiradi. ⚠️ Ataylab diskdan: generator fayl tizimiga yozadi va
       `_read_folder` ning O'ZI ham (BOM tozalash, `/` bilan nom) shartnomaning bir qismi."""
    return rb.validate_runtime_bundle(papka)


def yiqilgan(r: rb.Report) -> set[str]:
    return {c.name for c in r.checks if not c.ok}


def matn(r: rb.Report) -> str:
    return " || ".join(r.problems)


def oqi(papka: str, nom: str) -> dict:
    """Paketdagi JSON faylni o'qiydi — test paketning O'ZI nima yozganini ko'rishi uchun."""
    return json.loads((pathlib.Path(papka) / nom).read_text(encoding="utf-8"))


def oila(doc: dict, nom: str) -> dict:
    return next(f for f in doc["families"] if f["name"] == nom)


def bolim(doc: dict, nom: str) -> dict:
    return next(s for s in doc["sections"] if s["name"] == nom)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 0 · MOCKNING O'ZI NIMA DA'VO QILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_MOCK_sarlavhasi_ISBOTLAMAYDI_deb_OGOHLANTIRADI():
    """⚠️ Bu ogohlantirish MAJBURIY va shu bois QULFLANGAN: mock o'tgani «yig'uvchi ishlaydi»
       degani EMAS, va bu da'voni hujjatdan olib tashlash — isbotlanmagan narsani isbotlangan
       deb ko'rsatish yo'li. Sarlavha sinalmasa, u bir kun jimgina yumshatilib qo'yilardi."""
    bosh = mock.__doc__ or ""
    assert "REAL 1C ISHLASHINI ISBOTLAMAYDI" in bosh
    assert "o'rash mantiqini" in bosh
    assert "RUNTIME-UNKNOWN" in bosh


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · HALOL PAKET O'TADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_SOGLOM_paket_validator_uchun_ok_TRUE(tmp_path):
    r = hisobot(mock.paket_sog_lom(tmp_path))
    assert r.ok, matn(r)
    assert r.problems == ()
    assert all(c.ok and c.detail.strip() for c in r.checks)


def test_SOGLOM_paket_YETTI_ARTEFAKT_shartnomasiga_mos(tmp_path):
    """Majburiy olti fayl bor, zond fayli YO'Q (METADATA_ONLY), `artifacts` papka bilan mos,
       manifest esa O'ZINI xeshlamaydi."""
    papka = mock.paket_sog_lom(tmp_path)
    bor = sorted(p.name for p in pathlib.Path(papka).iterdir())
    assert bor == sorted(rb.REQUIRED_FILES)
    assert not (pathlib.Path(papka) / rb.PROBE_DIR).exists()
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert run["artifacts"] == sorted(rb.REQUIRED_FILES)
    manifest = oqi(papka, rb.MANIFEST_FILE)
    nomlar = [f["name"] for f in manifest["files"]]
    assert rb.MANIFEST_FILE not in nomlar
    assert sorted(nomlar) == sorted(n for n in rb.REQUIRED_FILES if n != rb.MANIFEST_FILE)


@pytest.mark.parametrize("nom,gen", QABUL_GENERATORLAR, ids=[n for n, _ in QABUL_GENERATORLAR])
def test_HALOL_paketlar_hammasi_QABUL_qilinadi(nom, gen, tmp_path):
    """⚠️ `PARTIAL` NUQSON EMAS: validator paketning SHAKLINI tekshiradi, yurishning
       muvaffaqiyatini emas. Yiqilish sababi bilan qayd etilgan bo'lsa — paket HALOL."""
    r = hisobot(gen(tmp_path))
    assert r.ok, f"{nom}: {matn(r)}"


@pytest.mark.parametrize("nom,gen", RAD_GENERATORLAR, ids=[n for n, _ in RAD_GENERATORLAR])
def test_BUZUQ_paketlar_hammasi_RAD_etiladi(nom, gen, tmp_path):
    """⚠️ FAIL-CLOSED: rad etilgan paket keyingi qadamga O'TMAYDI, va har rad SABABI bilan
       keladi — bo'sh `problems` bilan `ok=False` bo'lishi mumkin emas."""
    r = hisobot(gen(tmp_path))
    assert not r.ok, nom
    assert r.problems, f"{nom}: rad etildi, lekin sabab aytilmadi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · YOLG'ON `SUCCESS` — §6 ning ziddiyati
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_YOLGON_SUCCESS_ziddiyat_deb_aniqlanadi_va_ok_FALSE(tmp_path):
    """⚠️ §6: chiqish BUZILGAN bo'lsa yurish `SUCCESS` deb belgilanMASIN. Ziddiyat oddiy
       nuqsondan qo'rqinchliroq: u paketning O'Z hisobotiga ishonib bo'lmasligini ko'rsatadi,
       shu bois hukm ALOHIDA tekshiruvda («overall_ziddiyatsiz») va ANIQ so'z bilan keladi."""
    papka = mock.paket_yolgon_success(tmp_path)
    assert oqi(papka, rb.RUN_STATUS_FILE)["overall"] == rb.OVERALL_SUCCESS, (
        "fikstura SUCCESS deb YOZILISHI kerak — aks holda test hech narsani o'lchamaydi")
    r = hisobot(papka)
    assert not r.ok
    assert "overall_ziddiyatsiz" in yiqilgan(r)
    ziddiyat = next(c for c in r.checks if c.name == "overall_ziddiyatsiz")
    assert "ZIDDIYAT" in ziddiyat.detail
    assert rb.RUN_SUMMARY_FILE in ziddiyat.detail


def test_YOLGON_SUCCESS_majburiy_faylning_YOQLIGI_ham_aytiladi(tmp_path):
    """⚠️ Ziddiyat SABABNI almashtirmaydi: fayl yo'qligining O'ZI ham alohida nuqson bo'lib
       qoladi. Operator ikkisini ko'rishi kerak — biri «nima yo'q», ikkinchisi «nega paket
       hisobotiga ishonib bo'lmaydi»."""
    r = hisobot(mock.paket_yolgon_success(tmp_path))
    assert {"majburiy_fayllar", "artefakt_dalvosi", "overall_ziddiyatsiz"} <= yiqilgan(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · YARIM YOZILGAN HUJJAT
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_YARIM_yozilgan_metadata_JSON_PARSE_sababi_bilan_rad(tmp_path):
    """⚠️ SABAB MUHIM, nafaqat hukm: manifest yarim baytlarni xeshlagani uchun xesh MOS
       keladi, ya'ni nuqsonni FAQAT qat'iy JSON o'qish tuta oladi. Agar xesh darvozasi buni
       «tutib» qolsa, test aslida boshqa himoyani o'lchagan bo'lardi."""
    papka = mock.paket_serializatsiya_yarim(tmp_path)
    r = hisobot(papka)
    assert not r.ok
    parse = next(c for c in r.checks if c.name == "json_parse")
    assert not parse.ok
    assert rb.METADATA_FILE in parse.detail
    # ⚠️ Xesh MOS: yarim yozilish xesh bilan tutilMAYDI va shuni ham qulflaymiz.
    assert "xesh_manifest_mosligi" not in yiqilgan(r), matn(r)


def test_YARIM_yozilgan_hujjat_keyingi_qatlamlarni_FAIL_CLOSED_qoldiradi(tmp_path):
    """⚠️ «Tekshirib ko'rmadim» «muammo yo'q» EMAS: buzuq hujjatga tayanadigan tekshiruvlar
       `ok=True` bo'lib qolmaydi, ular `NOT_RUN` bo'lib YIQILADI."""
    r = hisobot(mock.paket_serializatsiya_yarim(tmp_path))
    assert {"sxema_va_versiya", "graf_qurilishi", "ai_kirishiga_tayyor"} <= yiqilgan(r)
    ai = next(c for c in r.checks if c.name == "ai_kirishiga_tayyor")
    assert ai.detail == rb.NOT_RUN


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · MANIFEST XESHI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_MANIFEST_xeshi_mos_emas_ok_FALSE(tmp_path):
    papka = mock.paket_manifest_mos_emas(tmp_path)
    r = hisobot(papka)
    assert not r.ok
    xesh = next(c for c in r.checks if c.name == "xesh_manifest_mosligi")
    assert not xesh.ok
    assert rb.METADATA_FILE in xesh.detail and "sha256" in xesh.detail


def test_MANIFEST_xeshi_buzilsa_QOLGAN_tekshiruvlar_yashil_qoladi(tmp_path):
    """⚠️ NUQSON QAMROVI ANIQ BO'LISHI KERAK: xesh mos kelmasligi butun hisobotni qizil
       qilib qo'ymaydi, aks holda operator haqiqiy sababni topa olmasdi."""
    r = hisobot(mock.paket_manifest_mos_emas(tmp_path))
    assert yiqilgan(r) == {"xesh_manifest_mosligi"}, matn(r)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · SIR OQQAN PAKET
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_SIR_oqqan_paket_rad_etiladi(tmp_path):
    r = hisobot(mock.paket_sir_oqqan(tmp_path))
    assert not r.ok
    assert {"maxfiylik_skani", "taqiqlangan_sir_naqshlari"} <= yiqilgan(r)


@pytest.mark.parametrize("qiymat", SIR_QIYMATLAR)
def test_SIR_qiymati_HISOBOT_matnida_KORINMAYDI(qiymat, tmp_path):
    """⚠️ Bu matn operator ekranidan JURNALGA, jurnaldan esa xabar almashinuviga ko'chadi —
       ya'ni nuqson matnida qiymatni ko'rsatish sirni IKKINCHI marta tarqatish bo'lardi.
    ⚠️ Hamma chiqish yo'li tekshiriladi: `problems`, deterministik JSON va odam o'qiydigan
       hisobot. Bittasini qoldirib ketish — eng ko'p ishlatiladigan yo'lda teshik qoldirish."""
    papka = mock.paket_sir_oqqan(tmp_path)
    r = hisobot(papka)
    assert not r.ok
    assert qiymat in (pathlib.Path(papka) / rb.ERRORS_FILE).read_text(encoding="utf-8"), (
        "fikstura sirni ROSTDAN yozishi kerak — aks holda test hech narsani o'lchamaydi")
    assert qiymat not in matn(r)
    assert qiymat not in rb.report_to_json_text(r)
    assert qiymat not in cli.human_report(r, folder=papka)


def test_SIR_oqqan_paket_CLI_da_kod_1_beradi_va_sirni_EKRANGA_chiqarmaydi(tmp_path):
    """⚠️ Operator skripti CHIQISH KODINI o'qiydi: `1` = «paket yaroqsiz». Va sir ekranga
       chiqmasligi shu yerda, haqiqiy chiqish yo'lida tekshiriladi."""
    papka = mock.paket_sir_oqqan(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    kod = cli.main([cli.VALIDATE_CMD, papka], out=out, err=err)
    assert kod == cli.EXIT_PROBLEM
    ekran = out.getvalue() + err.getvalue()
    for qiymat in SIR_QIYMATLAR:
        assert qiymat not in ekran


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · `absent` va `unreadable` — RAZVEDKANING ENG MUHIM AJRIMI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ABSENT_oila_QABUL_qilinadi_bu_HAQIQIY_javob(tmp_path):
    """⚠️ `absent` = «o'qildi va BO'SH» = TO'LIQ JAVOB. Shu bois: paket o'tadi, `overall`
       `SUCCESS` bo'lib qoladi va `errors.json` BO'SH — yo'qlik XATO EMAS."""
    papka = mock.paket_oila_yoq(tmp_path)
    r = hisobot(papka)
    assert r.ok, matn(r)
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert oila(run, "ПланыСчетов")["state"] == "absent"
    assert run["overall"] == rb.OVERALL_SUCCESS
    assert oqi(papka, rb.ERRORS_FILE)["errors"] == []


def test_UNREADABLE_oila_PARTIAL_bolib_qoladi_va_XATOSI_qayd_etiladi(tmp_path):
    """⚠️ `unreadable` = «o'qiy olmadim» = JAVOB YO'QLIGI. U `SUCCESS` ni BUZADI va uch joyda
       iz qoldiradi: bo'lim `failed`, oila `unreadable`, `errors.json` da qatori."""
    papka = mock.paket_oila_oqilmadi(tmp_path)
    r = hisobot(papka)
    assert r.ok, matn(r)
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert oila(run, "ПланыСчетов")["state"] == "unreadable"
    assert run["overall"] == rb.OVERALL_PARTIAL
    assert bolim(run, "chart_of_accounts")["status"] == "failed"
    kodlar = [e["code"] for e in oqi(papka, rb.ERRORS_FILE)["errors"]]
    assert kodlar == [mock.CODE_FAMILY_UNREADABLE]


def test_UNREADABLE_hech_qachon_ABSENT_deb_TALQIN_QILINMAYDI(tmp_path):
    """⚠️ `UNKNOWN` ni `NOT_FOUND` deb talqin qilish razvedkaning eng katta yolg'oni bo'lardi:
       o'qilmagan oila «bu konfiguratsiyada yo'q» bo'lib ko'rinardi va keyingi qatlam uni
       yo'qlikning ISBOTIGA yaqin deb o'qishi mumkin edi.

    Ajrim UCH mustaqil o'lchov bilan qulflanadi:
      1. IKKI PAKET BIR XIL EMAS — `absent` paketi `SUCCESS`, `unreadable` paketi `PARTIAL`;
      2. HOLAT NOMI ALMASHTIRILMAYDI — o'qilmagan oila hujjatda `absent` deb yozilmaydi;
      3. `unreadable` bilan `SUCCESS` da'vo qilingan paket RAD etiladi, va sabab AYNAN shu
         ajrimni aytadi."""
    yoq = oqi(mock.paket_oila_yoq(tmp_path / "yoq"), rb.RUN_STATUS_FILE)
    oqilmadi = oqi(mock.paket_oila_oqilmadi(tmp_path / "oqilmadi"), rb.RUN_STATUS_FILE)

    # 1 · umumiy holat FARQ QILADI
    assert yoq["overall"] == rb.OVERALL_SUCCESS
    assert oqilmadi["overall"] == rb.OVERALL_PARTIAL

    # 2 · holat nomi almashtirilmaydi
    assert oila(oqilmadi, "ПланыСчетов")["state"] == "unreadable"
    assert [f["name"] for f in oqilmadi["families"] if f["state"] == "absent"] == []

    # 3 · `unreadable` + `SUCCESS` = ZIDDIYAT
    r = hisobot(mock.paket_oila_oqilmadi(tmp_path / "yolgon", yolgon_success=True))
    assert not r.ok
    ziddiyat = next(c for c in r.checks if c.name == "overall_ziddiyatsiz")
    assert not ziddiyat.ok
    assert "ПланыСчетов" in ziddiyat.detail
    assert "unreadable" in ziddiyat.detail and "absent" in ziddiyat.detail


def test_UNREADABLE_oila_YAGONA_iz_bolsa_ham_SUCCESS_ni_BUZADI(tmp_path):
    """⚠️ ENG NOZIK HOLAT VA AYNAN SHU HIMOYANI O'LCHAYDI: yurish o'qish xatosini `errors.json`
       ga ham, bo'lim jurnaliga ham yozmagan — `unreadable` oila holatidan BOSHQA hech qanday
       iz yo'q va `overall=SUCCESS`. Ya'ni paketni rad etadigan YAGONA qoida — «o'qilmagan
       oila bilan yurish muvaffaqiyatli deb e'lon qilinmaydi».
    ⚠️ NEGA ALOHIDA TEST: `yolgon_success` variantida paket AYNI VAQTDA `errors[]` bo'sh emas
       qoidasini ham buzadi, ya'ni `unreadable` qoidasini olib tashlasa ham paket rad etilib
       qolardi — mutatsiya to'plamni qizil qilmasdi va himoya O'LCHANMAY qolardi."""
    papka = mock.paket_oila_oqilmadi(tmp_path, xato_yashirilgan=True)
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert run["overall"] == rb.OVERALL_SUCCESS
    assert oqi(papka, rb.ERRORS_FILE)["errors"] == []
    assert {s["status"] for s in run["sections"]} == {"ok"}
    assert oila(run, "ПланыСчетов")["state"] == "unreadable"

    r = hisobot(papka)
    assert not r.ok, "o'qilmagan oila YAGONA iz bo'lsa ham SUCCESS ni buzishi SHART"
    assert yiqilgan(r) == {"overall_ziddiyatsiz"}, matn(r)
    ziddiyat = next(c for c in r.checks if c.name == "overall_ziddiyatsiz")
    assert "ПланыСчетов" in ziddiyat.detail
    assert "unreadable" in ziddiyat.detail and "absent" in ziddiyat.detail


def test_HUQUQ_YOQ_paketi_PARTIAL_va_har_oila_UCH_JOYDA_iz_qoldiradi(tmp_path):
    """⚠️ `PARTIAL`, `FAILED` EMAS: hech bo'lmasa bitta bo'lim tugadi. Va o'qilmagan oilaning
       izi UCHOVIDA ham bo'lishi kerak — birortasi tushib qolsa, «o'qiy olmadim» jimgina
       yo'qolardi va paket to'liqroq ko'rinardi."""
    papka = mock.paket_huquq_yoq(tmp_path)
    r = hisobot(papka)
    assert r.ok, matn(r)
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert run["overall"] == rb.OVERALL_PARTIAL
    oqilmagan = sorted(f["name"] for f in run["families"] if f["state"] == "unreadable")
    assert len(oqilmagan) >= 4
    xato_oilalar = sorted(e["family"] for e in oqi(papka, rb.ERRORS_FILE)["errors"])
    assert xato_oilalar == oqilmagan
    for nom in oqilmagan:
        assert bolim(run, mock.FAMILY_SECTION[nom])["status"] == "failed", nom


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · QISMLI INSPEKSIYA — XATOLAR YO'QOLMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_QISMLI_inspeksiya_xatolar_YOQOLMAYDI_hammasi_errors_json_da(tmp_path):
    """⚠️ Obyekt darajasidagi xato ikki joyda turadi: obyektning O'Z `errors` ida va
       `errors.json` da. Ikkinchisi bo'lmasa, hisobotni faqat `errors.json` dan o'qiydigan
       operator muammoni UMUMAN ko'rmasdi — bu esa jim tushib qolishning aynan o'zi."""
    papka = mock.paket_qismli_inspeksiya(tmp_path)
    r = hisobot(papka)
    assert r.ok, matn(r)

    metadata = oqi(papka, rb.METADATA_FILE)
    xatoli = {o["full_name"] for o in metadata["objects"] if o["errors"]}
    soglom = {o["full_name"] for o in metadata["objects"] if not o["errors"]}
    assert xatoli and soglom, "fikstura xatolini ham, sog'lomini ham o'z ichiga olishi kerak"

    qatorlar = oqi(papka, rb.ERRORS_FILE)["errors"]
    assert {e["object"] for e in qatorlar} == xatoli
    assert {e["scope"] for e in qatorlar} == {"object"}
    assert oqi(papka, rb.RUN_STATUS_FILE)["overall"] == rb.OVERALL_PARTIAL


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · ULKAN PAKET — ISHLASH VA DETERMINIZM
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ULKAN_paket_otadi_va_hisobot_DETERMINISTIK(tmp_path):
    """⚠️ DETERMINIZM SHARTNOMA: bir xil paket — AYNAN bir xil hisobot baytlari, aks holda
       ikki yurishni qatorga qator solishtirib bo'lmasdi. Papka YO'LI hisobotga chiqmaydi,
       shu bois ikki XIL papkadagi AYNI paket ayni javobni berishi kerak.
    ⚠️ Vaqt chegarasi KENG (30 s): bu ishlash o'lchovi emas, «validator ulkan hujjatda
       osilib qolmasligi» darvozasi. Aniq sekundni qulflash mashina tezligini shartnomaga
       aylantirardi."""
    t0 = time.monotonic()
    birinchi = hisobot(mock.paket_ulkan(tmp_path / "a"))
    ikkinchi = hisobot(mock.paket_ulkan(tmp_path / "b"))
    ketgan = time.monotonic() - t0

    assert birinchi.ok, matn(birinchi)
    assert rb.report_to_json_text(birinchi) == rb.report_to_json_text(ikkinchi)
    assert ketgan < 30.0, f"ikki yurish {ketgan:.1f}s oldi"


def test_ULKAN_paket_hamma_obyektni_SAQLAB_qoladi(tmp_path):
    """⚠️ Hajm tufayli obyekt TASHLANMAYDI: graf hujjatdagi HAMMA obyektni ko'rishi kerak.
       Kesib qo'yish «paket o'tdi» degan yolg'on xotirjamlik berardi."""
    papka = mock.paket_ulkan(tmp_path, obyektlar=2000)
    metadata = oqi(papka, rb.METADATA_FILE)
    assert len(metadata["objects"]) == 2000
    graf = next(c for c in hisobot(papka).checks if c.name == "graf_qurilishi")
    assert graf.ok and "2000 obyekt" in graf.detail


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · G'ALATI NOMLAR — QURILADI YOKI ANIQ RAD ETILADI, JIMGINA TASHLANMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_GALA_nomlar_SHAKLAN_QONUNIY_bolsa_graf_QURILADI(tmp_path):
    """⚠️ «G'alati» «yaroqsiz» degani EMAS: 1C identifikatorida alifbo AHAMIYATSIZ va uzunlik
       cheklanmagan, ya'ni 220 belgili kirill nom, aralash alifbo va `_` bilan boshlangan nom
       QONUNIY. Ularni rad etgan darvoza boshqa tildagi do'konda birinchi kunda yiqilardi.
    ⚠️ BO'SH SINONIM ham saqlanadi: «sinonim yo'q» (`null`) va «sinonim bo'sh» bir xil emas."""
    papka = mock.paket_gala_nomlar(tmp_path)
    r = hisobot(papka)
    assert r.ok, matn(r)
    graf = next(c for c in r.checks if c.name == "graf_qurilishi")
    assert graf.ok and "4 obyekt" in graf.detail

    nomlar = [o["name"] for o in oqi(papka, rb.METADATA_FILE)["objects"]]
    assert mock.UZUN_NOM in nomlar and len(mock.UZUN_NOM) == 220
    assert mock.ARALASH_NOM in nomlar and mock.CHIZIQ_NOM in nomlar
    assert "" in [o["synonym"] for o in oqi(papka, rb.METADATA_FILE)["objects"]]


def test_GALA_nomlar_QONUNIY_BOLMAGAN_nom_ANIQ_rad_etiladi(tmp_path):
    """⚠️ JIMGINA TASHLASH TAQIQLANGAN. Faqat raqamli nom (`12345`) 1C identifikatori emas,
       lekin uni «tushunmadim, o'tkazib yubordim» deb qoldirish razvedkada yo'qotishning eng
       jim turi bo'lardi. Shu bois: paket RAD etiladi, xato matnida NOMNING O'ZI turadi va
       sabab (identifikator qoidasi) aytiladi."""
    papka = mock.paket_gala_nomlar(tmp_path, raqamli_nom=True)
    r = hisobot(papka)
    assert not r.ok
    sxema = next(c for c in r.checks if c.name == "sxema_va_versiya")
    assert not sxema.ok
    assert repr(mock.RAQAMLI_NOM) in sxema.detail or mock.RAQAMLI_NOM in sxema.detail
    assert "IDENTIFIKATORI" in sxema.detail

    # ⚠️ Graf ham JIMGINA qurilmaydi: u SABABI bilan yiqiladi.
    graf = next(c for c in r.checks if c.name == "graf_qurilishi")
    assert not graf.ok and "graf qurilmadi" in graf.detail

    # ⚠️ Nom hujjatda ROSTDAN turgan bo'lishi kerak, aks holda test hech narsani o'lchamaydi.
    assert mock.RAQAMLI_NOM in [o["name"] for o in oqi(papka, rb.METADATA_FILE)["objects"]]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · REJIM — DEFAULT HAR DOIM `METADATA_ONLY`
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nom,gen", HAMMA_GENERATORLAR, ids=[n for n, _ in HAMMA_GENERATORLAR])
def test_HAMMA_paket_METADATA_ONLY_va_AKTIV_ZOND_YOQ(nom, gen, tmp_path):
    """⚠️ §5 fail-safe: rejim so'ralmagan bo'lsa natija ENG QAT'IY rejim bo'ladi. Shu bois
       birorta mock paketda aktiv zond IZI bo'lmasligi kerak — na `probes` qaydi, na
       `probes/` fayli. Bu generatorlarning O'ZIGA qo'yilgan darvoza: sinov fiksturasi
       jimgina aktiv zond rejimiga o'tib ketsa, u boshqa shartnomani sinayotgan bo'lardi."""
    papka = gen(tmp_path)
    run = oqi(papka, rb.RUN_STATUS_FILE)
    assert run["mode"] == rb.MODE_METADATA_ONLY == rb.DEFAULT_MODE
    assert run["probes"] == []
    assert not list(pathlib.Path(papka).glob(f"{rb.PROBE_DIR}/*"))
    assert not any(a.startswith(f"{rb.PROBE_DIR}/") for a in run["artifacts"])
