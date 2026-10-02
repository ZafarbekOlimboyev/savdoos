# -*- coding: utf-8 -*-
"""Yadro UMUMIY bo'lib qolishining statik qo'riqchisi.

Egasining talabi: «Do NOT hardcode Fayzan/Розница 2.3 into the core» va
«Fayzan-specific assumptions remaining: MUST be zero in core».

Bu — niyat emas, TEKSHIRUV. Yadro manbasida konfiguratsiyaga yoki ijarachiga oid biror nom
paydo bo'lsa, shu test yiqiladi. Bilim faqat uch joyda yashashi mumkin:
  · to'plam ICHIDA (ya'ni ma'lumot sifatida),
  · ixtiyoriy adapterda (`adapters/`, yadrodan TASHQARIDA), yoki
  · TALQIN qatlamida (`analyst/`, yadrodan TASHQARIDA) — u ko'p tilli ishoralarni saqlaydi.

⚠️ `analyst/` NEGA alohida ro'yxatda. Talqin qatlami ishoralarni LOTIN shaklida saqlaydi
   (`nomenklatur`, `shtrihkod`, `sklad`, `vesovoy` — `lexicon.py` ning shartnomasi shunday), va
   AYNAN shu lotin shakllari yadroda bo'lmasligi kerak. Shu farqni pastdagi
   `test_analyst_qatlami_mavjud_va_lugat_shu_yerda` o'lchaydi: namuna lotin shakllari LUG'ATDAN
   OLINADI va ular yadro matnida qidiriladi.

⚠️ AMMO `FORBIDDEN` NING O'ZI ZAIFLASHTIRILMAYDI. Ilgari bu yerda `analyst/` uchun QISQARTILGAN
   ro'yxat turardi va asoslanishi «lug'at aynan shu so'zlardan iborat» edi — FAKT SIFATIDA
   NOTO'G'RI: `FORBIDDEN` KIRILL shakllarini (`номенклатура`, `штрихкод`, `виды цен`, `весовой`
   …) sanaydi, lug'at esa ularni saqlamaydi. Ya'ni qisqartish HECH NIMA bermasdi, lekin JONLI
   TESHIK qoldirardi: `analyst/heuristics.py` ga `# Справочник.Номенклатура, виды цен, весовой`
   satrini qo'shsa hamma test yashil o'tardi. Shu bois hozir TO'LIQ ro'yxat `analyst/` ga HAM
   qo'llanadi, istisnolar esa `ANALYST_ISTISNO` da fayl-ba-fayl, token-ba-token va sababi bilan
   yoziladi (hozircha BO'SH).

⚠️ `analyst/` ning `core_files()` dan chiqarib tashlanishi CHEGARANI BO'SHATMAYDI, uni
   KO'CHIRADI: shu qatlam uchun alohida darvozalar pastda turadi —
     · yadro `analyst` ni import QILMAYDI (bog'liqlik bir tomonlama),
     · `analyst/` ham tarmoqqa chiqmaydi,
     · `analyst/` da TO'LIQ `FORBIDDEN` ro'yxati va versiya SHAKLI taqiqlanadi.
   Ya'ni talqin qatlamiga ruxsat berilgani faqat UMUMIY TIL ishoralari; muayyan mijozning
   konfiguratsiyasi bu yerda ham TAQIQLANGAN.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import app.services.discovery_1c as pkg

CORE_DIR = pathlib.Path(pkg.__file__).parent
ANALYST_DIR = CORE_DIR / "analyst"

#: Yadroda uchramasligi KERAK bo'lgan tokenlar.
#
#: CHEGARA QAYERDA: 1C PLATFORMASINING tushunchalari (Справочник, РегистрСведений,
#: ПланВидовХарактеристик, Измерение, Ресурс …) RUXSAT ETILADI — yadroning butun vazifasi
#: aynan shularni modellashtirish va ular har qanday konfiguratsiyada bir xil. Taqiqlanadigani —
#: AMALIY nomlar: muayyan konfiguratsiyada yaratilgan katalog/registr nomlari, mahsulot nomi,
#: ijarachi nomi, mamlakat/valyuta taxminlari.
FORBIDDEN = (
    # ijarachi / do'kon
    "fayzan", "файзан", "faizan",
    # konfiguratsiya oilalari va versiyalari
    "розница", "roznitsa", "управление торговлей", "1с:erp", "1c:erp", "унф", "2.3.5.38",
    # amaliy metadata nomlari — yadro bularni BILMASLIGI kerak
    "номенклатура", "штрихкод", "склад", "виды цен", "весовой", "серии",
    "подключаемого оборудования", "подключаемое оборудование",
    # mamlakat / valyuta taxminlari
    "кыргыз", "сом", "bishkek",
)


#: ⚠️ TALQIN QATLAMIGA HAM AYNAN SHU RO'YXAT qo'llanadi — `FORBIDDEN` ning QISQARTMASI EMAS.
#: Sabab: qisqartma o'z-o'zidan «ruxsat» yozardi, tekshirib esa bo'lmaydi — qatlamda bu
#: shakllar BUGUN yo'q, ya'ni to'liq ro'yxat hech kimga xalal bermaydi. Qisqartirilgan ro'yxat
#: esa `analyst/` ga muayyan konfiguratsiyaning KIRILL nomlarini (`Справочник.Номенклатура`,
#: `виды цен`, `весовой`) jimgina olib kirish yo'lini ochib qo'yardi va buni hech narsa
#: aytmasdi.
ANALYST_FORBIDDEN = FORBIDDEN

#: ⚠️ ISTISNOLAR: fayl nomi -> shu FAYLDA ruxsat etilgan tokenlar. Hozircha BO'SH va bo'sh
#: qolishi KUTILADI. Ro'yxatga yozuv qo'shilsa u TOR bo'lishi SHART: bitta fayl, sanab
#: o'tilgan tokenlar va IZOHDA sababi. «Hammasiga ruxsat» degan yozuv bu jadvalda bo'lishi
#: mumkin emas — u darvozani o'chirish bilan bir xil narsa bo'lardi.
ANALYST_ISTISNO: dict[str, tuple[str, ...]] = {}

#: Konfiguratsiya versiyasining SHAKLI (`2.3.5`, `11.4.13` …). ⚠️ Aniq raqamni ro'yxatga
#: yozish yetmaydi: keyingi versiya boshqa raqam bilan kelardi va ro'yxat ortda qolardi.
VERSION_SHAPE_RE = re.compile(r"\b\d+\.\d+\.\d+")

#: Yadroda ham, `analyst/` da ham bo'lmasligi kerak bo'lgan importlar.
#: ⚠️ BITTA ro'yxat ataylab: ikki joyda ikki ro'yxat bo'lsa, ular bir kun bir-biridan ajralib
#: ketardi va qatlamlardan biri jimgina tarmoqqa chiqish huquqini olib qolardi.
TARMOQ_TAQIQ = ("socket", "requests", "urllib", "http.client", "subprocess", "win32com",
                "pythoncom", "ctypes", "comtypes", "psycopg", "sqlalchemy")


def core_files() -> list[pathlib.Path]:
    """YADRO fayllari. ⚠️ `adapters` ham, `analyst` ham chiqarib tashlanadi: ikkisi ham
    yadrodan TASHQARIDA turadigan, talqin bilimini saqlaydigan qatlamlar. `FORBIDDEN` esa
    O'ZGARMAYDI va IKKI ro'yxatga ham TO'LIQ qo'llanadi (`ANALYST_FORBIDDEN is FORBIDDEN`)."""
    return sorted(p for p in CORE_DIR.rglob("*.py")
                  if "adapters" not in p.parts and "analyst" not in p.parts)


def taqiqlangan_tokenlar(text: str, tokenlar, *, istisno=()) -> list[str]:
    """Matnda uchragan taqiqlangan tokenlar (tartiblangan, takrorsiz).

    ⚠️ BITTA funksiya ataylab: yadro darvozasi ham, `analyst/` darvozasi ham, mutatsiya
       tekshiruvi ham AYNAN shu kodni chaqiradi. Ikki joyda ikki skaner bo'lsa, biri
       o'zgarganda ikkinchisi jimgina ortda qolardi — va darvozaning ortda qolgani
       «yashil test» bo'lib ko'rinardi."""
    past = text.lower()
    return sorted({tok for tok in tokenlar if tok not in istisno and tok in past})


def analyst_files() -> list[pathlib.Path]:
    """TALQIN qatlamining fayllari — ular uchun alohida, torroq darvozalar bor."""
    return sorted(ANALYST_DIR.rglob("*.py"))


def import_lines(path: pathlib.Path) -> list[str]:
    """Faqat IMPORT satrlari. ⚠️ Izoh va docstring qaralmaydi: qatlam haqida YOZISH mumkin,
    uni IMPORT QILISH mumkin emas — tekshiriladigan narsa bog'liqlik, matn emas."""
    return [l for l in path.read_text(encoding="utf-8").splitlines()
            if re.match(r"\s*(?:from|import)\s", l)]


def test_yadroda_fayl_bor():
    names = {p.name for p in core_files()}
    assert {"__init__.py", "schema.py", "bundle.py", "redact.py"} <= names


@pytest.mark.parametrize("path", core_files(), ids=lambda p: p.name)
def test_yadroda_konfiguratsiyaga_oid_nom_yoq(path: pathlib.Path):
    hits = taqiqlangan_tokenlar(path.read_text(encoding="utf-8"), FORBIDDEN)
    assert not hits, (
        f"{path.name} da konfiguratsiyaga/ijarachiga oid token(lar): {hits}. "
        "Yadro umumiy bo'lib qolishi kerak — bu bilim to'plam ichida yoki adapterda yashaydi."
    )


def test_nishonlar_binos_tomonida_nomlangan():
    """Nishonlar BIZNING shartnomamiz nomlari bo'lishi kerak, 1C nomlari emas."""
    from app.services.discovery_1c.schema import TARGETS
    for t in TARGETS:
        assert t.isascii(), f"nishon nomi ASCII bo'lishi kerak: {t!r}"
        assert t.replace(".", "").replace("_", "").isalnum(), f"nishon nomi g'alati: {t!r}"


def test_sxema_mahsulot_maydonlarini_qamraydi():
    """`binos-1c-v1` ning 15 mahsulot maydoni + 4 tuzilma bloki qamralgan bo'lsin."""
    from app.services.discovery_1c.schema import BUNDLE_TARGETS
    from app.services.migrator_1c.bundle import PRODUCT_KEYS
    covered = {t.split(".", 1)[1] for t in BUNDLE_TARGETS if t.startswith("products.")}
    assert PRODUCT_KEYS == covered, (
        "discovery nishonlari `binos-1c-v1` mahsulot maydonlari bilan bir xil bo'lishi kerak; "
        f"faqat bundle'da: {sorted(PRODUCT_KEYS - covered)}; faqat discovery'da: {sorted(covered - PRODUCT_KEYS)}"
    )


def test_yadro_1c_ga_ulanmaydi():
    """Yadroda tarmoq/COM/jarayon chaqiruvi bo'lmasligi kerak — u faqat faylni o'qiydi."""
    banned = TARMOQ_TAQIQ
    for path in core_files():
        text = path.read_text(encoding="utf-8")
        for tok in banned:
            assert f"import {tok}" not in text and f"from {tok}" not in text, \
                f"{path.name}: yadro {tok!r} ni ishlatmasligi kerak"


# ══════════════════════════════════════════════════════════════════════════════════════════
# KOMPENSATSIYA — `analyst/` yadrodan chiqarilgani uchun QO'YILGAN DARVOZALAR
# ⚠️ Bular hujjat emas, DARVOZA. `core_files()` dan bir papkani chiqarib tashlash o'zi bilan
#    chegarani bo'shatardi; pastdagi testlar shu bo'shliqni yopadi.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_yadro_analyst_qatlamini_import_qilmaydi():
    """BOG'LIQLIK BIR TOMONLAMA: `analyst/` yadroni o'qiydi, yadro esa uni BILMAYDI.

    ⚠️ NEGA MUHIM: agar yadro talqin qatlamini import qilsa, ko'p tilli lug'at yadroning
       shartnomasiga qaytib kirardi — ya'ni `core_files()` dan papkani chiqarib tashlash
       chegarani bo'shatgan bo'lardi. Bog'liqlik bir tomonlama bo'lgani uchungina talqin
       bilimini o'zgartirish yadroga TEGMAYDI."""
    for path in core_files():
        for line in import_lines(path):
            assert "analyst" not in line, (
                f"{path.name}: yadro `analyst` qatlamini import qilmasligi kerak — {line.strip()!r}. "
                "Bog'liqlik BIR TOMONLAMA: talqin yadroni o'qiydi, yadro talqinni bilmaydi.")

    # ⚠️ Teskari yo'nalish ROSTDAN bor bo'lishi kerak: aks holda yuqoridagi tekshiruv
    #    «hech kim hech kimni import qilmaydi» degan bo'sh gapga aylanardi.
    assert any("from ..ai import" in l or "from ..probe import" in l
               for p in analyst_files() for l in import_lines(p)), \
        "talqin qatlami yadroni import qilishi kerak — aks holda chegara tekshiruvi bo'sh"


def test_analyst_qatlami_mavjud_va_lugat_shu_yerda():
    """KO'P TILLI LUG'AT AYNAN `analyst/lexicon.py` DA, yadroda EMAS."""
    lexicon = ANALYST_DIR / "lexicon.py"
    assert lexicon.is_file(), "`analyst/lexicon.py` yo'q — talqin bilimi qayerda yashaydi?"
    assert lexicon not in core_files(), "lug'at yadro ro'yxatiga qaytib tushgan"

    from app.services.discovery_1c.ai import CONCEPTS
    from app.services.discovery_1c.analyst.lexicon import CONCEPT_CLUES, MISLEADING_CLUES

    # Lug'at shartnomani TO'LIQ qamrasin: lug'atsiz konsept jimgina nomzodsiz qolardi.
    assert set(CONCEPT_CLUES) == set(CONCEPTS)

    # ⚠️ Ishoralar KO'P TILLI bo'lishi kerak: rus, o'zbek, qirg'iz va ingliz shakllari bitta
    #    lug'atda. Bitta tilga moslangan qatlam xato emas — u FAQAT BITTA do'konda ishlaydi.
    assert {"tovar", "mahsulot", "tauar", "product"} <= set(CONCEPT_CLUES["product"])

    # ⚠️ Bu shakllar yadroda BO'LMASLIGI kerak. Ular ro'yxatdan OLINADI, qo'lda yozilmaydi:
    #    lug'at o'zgarsa tekshiruv ham o'zgaradi.
    hamma_ishora = {c for clues in CONCEPT_CLUES.values() for c in clues}
    namuna = ("edinicy", "harakteristika", "mahsulotlar", "produkciya", "shtrihkod",
              "shtrixkod", "tarozilar", "tauarlar", "tovarlar", "vesovoy")
    yo_q = sorted(t for t in namuna if t not in hamma_ishora)
    assert not yo_q, f"namuna ishoralari lug'atdan yo'qolgan: {yo_q} — tekshiruv bo'sh qoldi"

    yadro_matni = "\n".join(p.read_text(encoding="utf-8") for p in core_files()).lower()
    sizib_chiqqan = sorted(t for t in namuna if t in yadro_matni)
    assert not sizib_chiqqan, (
        f"yadroda talqin lug'atining shakllari paydo bo'lgan: {sizib_chiqqan}. "
        "Ko'p tilli ishoralar faqat `analyst/lexicon.py` da yashaydi.")
    for nom in ("CONCEPT_CLUES", "MISLEADING_CLUES"):
        assert nom not in yadro_matni, f"yadroda talqin lug'ati e'lon qilingan: {nom}"
    assert MISLEADING_CLUES, "chalg'ituvchi shakllar ro'yxati bo'sh — qarshi dalil qayerdan keladi?"


@pytest.mark.parametrize("path", analyst_files(), ids=lambda p: p.name)
def test_analyst_ham_tarmoqqa_ulanmaydi(path: pathlib.Path):
    """⚠️ Talqin qatlamiga LUG'AT ruxsat etildi, TARMOQ emas. U ham faqat kirishdagi lug'atni
    o'qiydi: model ulagichi ALOHIDA qadam bo'ladi va tarmoqqa chiqadigan yagona joy o'sha."""
    text = path.read_text(encoding="utf-8")
    for tok in TARMOQ_TAQIQ:
        assert f"import {tok}" not in text and f"from {tok}" not in text, \
            f"{path.name}: talqin qatlami {tok!r} ni ishlatmasligi kerak"


@pytest.mark.parametrize("path", analyst_files(), ids=lambda p: p.name)
def test_analyst_qatlamida_ijarachi_nomi_yoq(path: pathlib.Path):
    """⚠️ `analyst/` ga ruxsat berilgani faqat UMUMIY TIL ishoralari. Ijarachi nomi,
    konfiguratsiya oilasi va VERSIYASI, mamlakat/valyuta taxminlari bu yerda ham TAQIQ:
    ular tilning emas, muayyan MIJOZNING xossasi. Ular ko'rinsa, talqin qatlami bitta
    do'konga moslanib qolgan bo'ladi va buni keyin ajratib olish qiyin."""
    # ⚠️ Ro'yxat `FORBIDDEN` ning QISMI bo'lishi SHART: aks holda u yadro darvozasidan
    #    ajralib ketib, ijarachi nomiga jimgina ruxsat berardi.
    assert set(ANALYST_FORBIDDEN) <= set(FORBIDDEN)

    text = path.read_text(encoding="utf-8")
    hits = taqiqlangan_tokenlar(text, ANALYST_FORBIDDEN,
                                istisno=ANALYST_ISTISNO.get(path.name, ()))
    assert not hits, (
        f"{path.name} da ijarachiga/konfiguratsiyaga oid token(lar): {hits}. Talqin qatlami "
        "UMUMIY TIL bilimi bo'lib qolishi kerak, muayyan mijoz sozlamasi emas.")

    versiyalar = sorted(set(VERSION_SHAPE_RE.findall(text.lower())))
    assert not versiyalar, (
        f"{path.name} da konfiguratsiya versiyasiga o'xshash raqam(lar): {versiyalar}. "
        "Versiyaga bog'langan talqin keyingi versiyada jimgina xato javob berardi.")


def test_analyst_darvozasi_toliq_forbidden_royxatini_qollaydi():
    """⚠️ TALQIN DARVOZASI YADRO DARVOZASIDAN ZAIFROQ BO'LMAYDI.

    Ilgari `ANALYST_FORBIDDEN` `FORBIDDEN` dan SAKKIZ tokenni tushirib qoldirgan edi
    (`номенклатура`, `штрихкод`, `склад`, `виды цен`, `весовой`, `серии`, `подключаемое
    оборудование`, `подключаемого оборудования`) va asoslanishi «lug'at aynan shu so'zlardan
    iborat» edi. ASOSLANISH NOTO'G'RI: lug'at LOTIN shakllarini saqlaydi, ro'yxat esa KIRILL
    shakllarini sanaydi — ya'ni qisqartma hech narsa bermasdi, faqat teshik qoldirardi.

    ⚠️ Bu test FARQNI o'lchaydi, faylni emas: fayllarni skanerlash bugun ikki ro'yxatda ham
       bir xil natija beradi, ya'ni faqat fayl tekshiruvi teshikni KO'RSATMAYDI."""
    tushib_qolgan = sorted(set(FORBIDDEN) - set(ANALYST_FORBIDDEN))
    assert not tushib_qolgan, (
        f"talqin darvozasi yadro darvozasidan zaifroq: tushib qolgan token(lar) "
        f"{tushib_qolgan}. Qisqartma «ruxsat» yozadi, lekin uni tekshirib bo'lmaydi — to'liq "
        f"ro'yxat qo'llanilsin, istisno kerak bo'lsa `ANALYST_ISTISNO` da TOR yozilsin.")

    # ⚠️ Istisno jadvali BO'SH yoki TOR bo'lishi kerak: «hamma fayl» yoki «hamma token» degan
    #    yozuv darvozani o'chirish bilan bir xil.
    analyst_nomlari = {p.name for p in analyst_files()}
    for fayl, tokenlar in sorted(ANALYST_ISTISNO.items()):
        assert fayl in analyst_nomlari, f"istisno mavjud bo'lmagan faylga yozilgan: {fayl!r}"
        assert tokenlar, f"{fayl}: bo'sh istisno yozuvi — u hech narsani tushuntirmaydi"
        assert set(tokenlar) < set(FORBIDDEN), (
            f"{fayl}: istisno TO'LIQ ro'yxatni qamragan — bu darvozani o'chirish")


@pytest.mark.parametrize("path", analyst_files(), ids=lambda p: p.name)
def test_analyst_darvozasi_amaliy_metadata_nomini_tutadi(path: pathlib.Path):
    """MUTATSIYA: `analyst/` faylining matniga muayyan konfiguratsiyaning KIRILL nomlari
    qo'shilsa, darvoza uni USHLASHI kerak.

    ⚠️ NEGA SHU TEST KERAK: fayllarni «bor holicha» skanerlash HAR DOIM yashil bo'ladi —
       bugun bu shakllar qatlamda yo'q. Ya'ni oddiy skaner darvoza ROSTDAN ishlayotganini
       isbotlamaydi, u faqat «hozir toza» deydi. Qisqartirilgan ro'yxat bilan aynan shu
       satr — `# Справочник.Номенклатура, виды цен, весовой` — jimgina o'tib ketardi."""
    buzuq = path.read_text(encoding="utf-8") + (
        "\n# Справочник.Номенклатура, виды цен, весовой, штрихкод, склад, серии\n")
    hits = taqiqlangan_tokenlar(buzuq, ANALYST_FORBIDDEN,
                               istisno=ANALYST_ISTISNO.get(path.name, ()))
    kutilgan = {"номенклатура", "виды цен", "весовой", "штрихкод", "склад", "серии"}
    yo_q = sorted(kutilgan - set(hits))
    assert not yo_q, (
        f"{path.name}: darvoza muayyan konfiguratsiyaning nomlarini O'TKAZIB YUBORDI: {yo_q}. "
        f"Bu shakllar talqin qatlamida ham TAQIQ — ular umumiy til emas, bitta mijozning "
        f"konfiguratsiyasi.")


def test_yangi_yadro_fayllari_qamralgan():
    """⚠️ Qo'riqchi FAYL RO'YXATI bilan ishlaydi, shu bois yangi yadro fayli ham unga tushishi
    kerak. Aks holda kimdir yangi modul qo'shib, tekshiruvdan chetda qolib ketardi."""
    names = {p.name for p in core_files()}
    kutilgan = {"metadata.py", "graph.py", "ai.py", "probe.py", "confirmations.py", "review.py"}
    yo_q = sorted(kutilgan - names)
    assert not yo_q, f"yadro ro'yxatida yo'q fayl(lar): {yo_q} — qo'riqchidan chetda qolgan"

    # `analyst/` esa ATAYLAB tashqarida — lekin o'zining darvozalari bilan.
    assert "lexicon.py" not in names and "heuristics.py" not in names
    assert {p.name for p in analyst_files()} == {"__init__.py", "heuristics.py", "lexicon.py"}


def test_konsept_idlari_ascii():
    """⚠️ Konsept ID lari JSON kaliti bo'lib yuradi va kodda taqqoslanadi: ular ASCII
    snake_case bo'lishi SHART va tarjimaga bog'liq bo'lmasligi kerak."""
    from app.services.discovery_1c.ai import CONCEPTS
    snake = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
    for c in CONCEPTS:
        assert c.isascii(), f"konsept ID si ASCII bo'lishi kerak: {c!r}"
        assert snake.fullmatch(c), f"konsept ID si snake_case bo'lishi kerak: {c!r}"
    assert len(set(CONCEPTS)) == len(CONCEPTS), "konsept ID si takrorlangan"
