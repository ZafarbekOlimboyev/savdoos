# -*- coding: utf-8 -*-
"""INVENTAR QO'RIQCHISI — yig'maga TAYANADIGAN test modullarining ro'yxati MUZLATILGAN.

⚠️⚠️ NEGA BU FAYL BOR: AYNI bitta teshik BESH marta takrorlandi va har biri QO'LDA
     ko'rib topildi. Teshikning shakli har galda bir xil edi:
       (a) yig'ma ildizi QO'LDA, mutlaq yo'l bilan yozilgan (`BINOS_AGENT_BUILD_ROOT`
           o'qilmaydi) — ya'ni modullar jimgina BOSHQA yig'mani tekshirishi mumkin;
       (b) `.exe` yo'q bo'lsa SHARTSIZ `skip` — platformaga bog'liq EMAS va yig'ma
           YANGILIGI tekshirilmaydi, demak ESKIRGAN artefakt «ishlaydi» deb tasdiqlanadi;
       (c) o'sha skip'lar `tests/ci_expected_skips.txt` da YO'Q — HAQIQIY Linux CI'da
           «KUTILMAGAN skip» bo'lib backend job'ni QIZIL qiladi.
     Beshtasi tuzatildi. Bu fayl ALTINCHISI JIMGINA paydo bo'lmasligi uchun STRUKTURAVIY
     qo'riqchi: yangi modul yig'maga tayansa, ro'yxat tengligi BUZILADI va test yiqilib
     NIMA QILISH kerakligini AYTADI.

⚠️ BU TEST `.exe` DAN MUSTAQIL va Linux'da BAJARILADI: u faqat (1) `tests/` ichidagi
   MATNNI, (2) modullarning e'lon qilgan konstantalarini va (3) kutilgan-skip ro'yxatini
   o'qiydi. Shu bois u `tests/ci_expected_skips.txt` ga KIRMAYDI — kirsa, qo'riqchining
   o'zi jim qolishi mumkin bo'lardi.

═══ ANIQLASH MEZONI (ikki shart BIRGA) ══════════════════════════════════════════════════
Modul «yig'maga TAYANADI» deb hisoblanadi, agar uning MATNIDA:
    1. yig'ma ildiziga yoki artefaktiga havola bor (`_YIGMA_IZLARI`), VA
    2. shartli o'tkazib yuborish / yiqitish mexanizmi bor (`_DARVOZA_IZLARI`).
Ikkinchi shart ATAYLAB: artefakt nomini FAQAT matn sifatida tasdiqlaydigan modul
yig'maga TAYANMAYDI — u yig'ma bo'lmasa ham AYNI natijani beradi, demak unga darvoza ham,
kutilgan-skip yozuvi ham KERAK EMAS. Mezonning o'tkirligi `_TAYANMAYDIGANLAR` bilan
IKKI TOMONLAMA qadalgan: u modullar ro'yxatga TUSHMASLIGI ham test bilan talab qilinadi.

⚠️ Mezon MATN ustida ishlaydi, import ustida EMAS: modulni import qilish uning
   bog'liqliklarini (va yig'ma yo'lini) ishga solardi, matn esa Linux'da ham, yig'masiz
   ham bir xil o'qiladi.
"""
from __future__ import annotations

import pathlib

#: `apps/server` — nisbiy yo'llarning ildizi.
_SERVER = pathlib.Path(__file__).resolve().parents[1]
_TESTS = _SERVER / "tests"
_ALLOWLIST = _TESTS / "ci_expected_skips.txt"

#: 1-SHART: yig'ma ildiziga/artefaktiga havola.
_YIGMA_IZLARI = ("BINOS_AGENT_BUILD_ROOT", "BINOS_AGENT_EXE", "binos-agent-build",
                 "dist-onedir", "build-onedir", "BinOSDiscoveryAgent.exe")

#: 2-SHART: shartli skip/fail mexanizmi (darvoza yoki eski shartsiz `skipif`).
_DARVOZA_IZLARI = ("pytest.mark.skipif", "pytest.skip(", "pytest.fail(",
                   "_dist_talab", "yigma_tayyorligi")

#: ⚠️⚠️ MUZLATILGAN RO'YXAT — AYNAN BESHTA modul. O'zgartirish ODAM qarori bilan va
#:      darvoza + kutilgan-skip yozuvi bilan BIRGA bo'ladi.
_MUZLATILGAN = frozenset({
    "tests/test_agent_parity.py",          # haqiqiy `.exe` ↔ manba parity'si (OWNER B)
    "tests/test_agent_packaging.py",       # yig'ma TARKIBI (`.exe` ichida nima bor)
    "tests/test_agent_portability.py",     # portativlik (`.exe` ROSTDAN yurgiziladi)
    "tests/test_agent_packaged_e2e.py",    # uchiga-uch ssenariy matritsasi
    "tests/test_agent_packaged_safety.py",  # tarqatiladigan BAYTLAR xavfsizligi
})

#: ⚠️ QO'RIQCHINING O'ZI: mezon tokenlari shu faylda RO'YXAT bo'lib yozilgan, shu bois
#:    mezon o'zini ham tutadi. Bu modul yig'maga TAYANMAYDI — u `.exe` ga ham, uning
#:    yo'liga ham MUROJAAT QILMAYDI va yig'masiz AYNI natijani beradi.
_OZI = "tests/test_agent_build_inventory.py"

#: ⚠️⚠️ MEZONNING O'TKIRLIGI SHU IKKI MODUL BILAN QADALGAN. Ular yig'ma izini O'Z ICHIGA
#:      OLADI, lekin yig'maga TAYANMAYDI — ro'yxatga tushsa, mezon KENG degani.
_TAYANMAYDIGANLAR = {
    "tests/test_agent_result_package.py":
        "faqat hisobot MATNIDA `BinOSDiscoveryAgent.exe` satri borligini tasdiqlaydi; "
        "yig'ma yo'q bo'lsa ham AYNI natija (skip/fail mexanizmi YO'Q).",
    "tests/test_discovery_1c_redact.py":
        "redaksiya FIKSTURASIDA yig'ma yo'li oddiy SATR sifatida turadi (niqoblanishi "
        "kerak bo'lgan kirish ma'lumoti); diskka murojaat ham, darvoza ham YO'Q.",
}


def _modul_matnlari() -> dict[str, str]:
    """{"tests/<...>.py": matn} — `tests/` dagi HAMMA test moduli (rekursiv)."""
    out: dict[str, str] = {}
    for p in sorted(_TESTS.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if not (p.name.startswith("test_") or p.name.endswith("_test.py")):
            continue
        out[p.relative_to(_SERVER).as_posix()] = p.read_text(encoding="utf-8")
    assert out, f"test modullari topilmadi: {_TESTS}"
    return out


def _yigmaga_tayanadiganlar() -> set[str]:
    """Mezonni qo'llab topilgan modullar (qo'riqchining O'ZI chiqarib tashlanadi)."""
    topilgan = set()
    for rel, matn in _modul_matnlari().items():
        if rel == _OZI:
            continue
        if any(t in matn for t in _YIGMA_IZLARI) and any(t in matn
                                                         for t in _DARVOZA_IZLARI):
            topilgan.add(rel)
    return topilgan


def _allowlist_qoidalari() -> list[tuple[str, str]]:
    """[(id, sabab_bo'lagi)] — izoh va bo'sh qatorlar tashlanadi."""
    qoidalar = []
    for raw in _ALLOWLIST.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#") or not raw.strip():
            continue
        pat, sep, sabab = (x.strip() for x in raw.partition(" | "))
        assert sep and pat and sabab, f"kutilgan-skip qatori noto'g'ri: {raw!r}"
        qoidalar.append((pat, sabab))
    assert qoidalar, "kutilgan-skip ro'yxati BO'SH"
    return qoidalar


def _darvoza_jadvali() -> dict[str, tuple[pathlib.Path, str]]:
    """{"tests/<...>.py": (yig'ma ildizi, MUHIT skip sababi)} — BESH modul uchun.

    ⚠️ Import TEST ICHIDA: modullar og'ir bog'liqlik oladi va qo'riqchining YIG'ILISHI
       ularga bog'liq bo'lib qolmasligi kerak.
    ⚠️ `parity` ildizni O'ZIDA e'lon QILMAYDI — u harnessdan (OWNER B) oladi, shu bois
       uning qiymati `PH` orqali o'qiladi. Qolgan to'rttasi o'z konstantasini beradi.
    """
    from tests import test_agent_packaged_e2e as E2E
    from tests import test_agent_packaged_safety as SAFE
    from tests import test_agent_packaging as PKG
    from tests import test_agent_parity as PAR
    from tests import test_agent_portability as PORT

    jadval = {
        "tests/test_agent_parity.py": (PAR.PH.YIGMA_ILDIZ, PAR.PH.MUHIT_SABABI),
        "tests/test_agent_packaging.py": (PKG._YIGMA_ILDIZ, PKG._MUHIT_SABABI),
        "tests/test_agent_portability.py": (PORT._YIGMA_ILDIZ, PORT._MUHIT_SABABI),
        "tests/test_agent_packaged_e2e.py": (E2E._YIGMA_ILDIZ, E2E._MUHIT_SABABI),
        "tests/test_agent_packaged_safety.py": (SAFE._YIGMA_ILDIZ, SAFE._MUHIT_SABABI),
    }
    assert set(jadval) == set(_MUZLATILGAN), (
        f"darvoza jadvali muzlatilgan ro'yxatdan FARQ qiladi: "
        f"{sorted(set(jadval) ^ set(_MUZLATILGAN))}")
    return jadval


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. RO'YXAT TENGLIGI — ALTINCHI modul JIMGINA qo'shilmasin
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_yigmaga_TAYANADIGAN_modullar_royxati_MUZLATILGAN():
    """⚠️⚠️ ALTINCHI NUSXA QO'RIQCHISI. Ro'yxat AYNAN teng bo'lsin: yangi modul qo'shilsa
         ham, muzlatilgan modul darvozasini YO'QOTSA ham test yiqiladi.

    ⚠️ IKKI TOMONLAMA: «kamaygan» holat ham nuqson — muzlatilgan moduldan darvoza olib
       tashlangani (ya'ni `pytest.skip`/`fail` yo'qolgani) AYNAN shu yerda ko'rinadi.
    """
    topilgan = _yigmaga_tayanadiganlar()
    yangi = sorted(topilgan - _MUZLATILGAN)
    yoqolgan = sorted(_MUZLATILGAN - topilgan)
    assert not yangi, (
        f"YANGI MODUL TOPILDI: {yangi} — u yig'maga TAYANADI, lekin muzlatilgan "
        f"ro'yxatda YO'Q. AYNI teshik ilgari BESH marta takrorlangan, shu bois jimgina "
        f"qo'shib qo'yish TAQIQLANADI. Bajarilishi SHART bo'lgan uch qadam: "
        f"(1) DARVOZANI QO'LLANG — ildizni `BINOS_AGENT_BUILD_ROOT` dan oling va "
        f"`parity_harness.yigma_tayyorligi()` hukmini `_dist_talab()` orqali ishlating "
        f"(`tests/test_agent_portability.py` NAMUNA); (2) `tests/ci_expected_skips.txt` "
        f"GA YOZING — HAR skip uchun ANIQ id, sabab bo'lagi BOSHQA darvozalarning "
        f"BO'LAGI BO'LMAGAN yangi matn; (3) shu fayldagi `_MUZLATILGAN` ro'yxatiga "
        f"qo'shing.")
    assert not yoqolgan, (
        f"MUZLATILGAN MODUL MEZONGA TUSHMAY QOLDI: {yoqolgan} — yoki darvoza olib "
        f"tashlangan (`pytest.skip`/`pytest.fail`/`_dist_talab` yo'qolgan), yoki yig'ma "
        f"ildiziga havola yo'qolgan. Ikkisi ham eskirgan artefaktning jimgina "
        f"tasdiqlanishiga olib keladi.")
    assert topilgan == set(_MUZLATILGAN), sorted(topilgan ^ set(_MUZLATILGAN))


def test_mezon_yigmaga_TAYANMAYDIGAN_modullarni_TUTMAYDI():
    """⚠️ MEZONNING O'TKIRLIGI: yig'ma nomini FAQAT matnda eslatgan modul ro'yxatga
       TUSHMASLIGI kerak. Aks holda qo'riqchi ularga darvoza va kutilgan-skip yozuvi
       talab qilardi — ya'ni ROSTDAN kerak bo'lmagan `skip` yozuvi paydo bo'lardi
       (`ci_expected_skips.txt` konventsiyasi aynan buni TAQIQLAYDI).

    ⚠️ Bu test «ro'yxatda yo'q» bilan CHEKLANMAYDI: u SABABNI ham o'lchaydi — u modullar
       1-shartni (yig'ma izi) QONDIRADI, 2-shartni (darvoza izi) esa YO'Q. Shunda mezon
       keng tomonga siljisa, nima buzilgani ANIQ ko'rinadi.
    """
    topilgan = _yigmaga_tayanadiganlar()
    matnlar = _modul_matnlari()
    for rel, nega in _TAYANMAYDIGANLAR.items():
        assert rel in matnlar, f"istisno qilingan modul topilmadi: {rel}"
        assert rel not in topilgan, (
            f"mezon KENG: `{rel}` yig'maga tayanadigan deb topildi, lekin u tayanmaydi — "
            f"{nega}")
        matn = matnlar[rel]
        assert any(t in matn for t in _YIGMA_IZLARI), \
            f"`{rel}` da yig'ma izi YO'Q — istisno izohi eskirgan: {nega}"
        assert not any(t in matn for t in _DARVOZA_IZLARI), (
            f"`{rel}` ga shartli skip/fail mexanizmi QO'SHILGAN — endi u yig'maga "
            f"TAYANADI deb hisoblanishi mumkin: darvozani qo'llang va `_MUZLATILGAN` "
            f"ro'yxatiga qo'shing (yoki istisno izohini yangilang).")


def test_qoriqchining_OZI_YAGONA_istisno():
    """⚠️ Qo'riqchi faqat O'ZINI chiqarib tashlaydi — va shuni OCHIQ yozadi.

    ⚠️ NEGA MUHIM: «chiqarib tashlash» ro'yxati o'sib ketsa, qo'riqchi sekin-asta
       ko'rlanardi. Shu bois istisno AYNAN BITTA va u shu faylning O'ZI.
    """
    assert _OZI in _modul_matnlari(), f"qo'riqchi fayli topilmadi: {_OZI}"
    assert pathlib.Path(__file__).resolve().relative_to(_SERVER).as_posix() == _OZI, \
        "`_OZI` qiymati faylning haqiqiy yo'liga mos emas"
    assert _OZI not in _MUZLATILGAN, "qo'riqchi O'ZINI yig'maga tayanadigan deb yozdi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. BESH MODUL BITTA YIG'MANI KO'RSIN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_BESH_modulda_yigma_ILDIZI_AYNI():
    """⚠️⚠️ DRIFT QO'RIQCHISI, BESH MODUL uchun. `test_agent_parity.py` dagi
         `test_A_yigma_ILDIZI_UCH_modulda_AYNI` birinchi UCHTASINI qulflaydi; bu test
         to'rtinchi va beshinchisini ham qamraydi, ya'ni «ikki modulda AYNI» → «uchta» →
         «beshta» zanjirida yana bir modul nazardan chetda qolmaydi.
    """
    jadval = _darvoza_jadvali()
    ildizlar = {rel: ildiz for rel, (ildiz, _s) in jadval.items()}
    noyob = set(ildizlar.values())
    assert len(noyob) == 1, (
        f"BESH darvoza BOSHQA yig'ma ildizini ko'rsatadi — biri eskisini «toza» deb, "
        f"ikkinchisi yangisini o'lchashi mumkin: "
        f"{ {rel: str(i) for rel, i in ildizlar.items()} }")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. SKIP SABABLARI AJRALGAN BO'LSIN (`reason in msg` tufayli)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_BESH_darvozaning_skip_sababi_JUFTMA_JUFT_AJRALGAN():
    """⚠️⚠️ `verify_pytest_run._matches` sababni `reason in msg` bilan tekshiradi. Agar
         bir darvozaning sabab matni boshqasining BO'LAGI bo'lsa, ro'yxatdan bitta yozuv
         yo'qolganda uning skip'lari ikkinchisining qatoriga YASHIRINIB o'tib ketardi va
         KUTILMAGAN skip QIZIL BERMASDI. Shu bois beshta matn juftma-juft AJRALGAN
         bo'lishi SHART: teng ham emas, biri ikkinchisining bo'lagi ham emas.

    ⚠️ Har modul buni O'ZIDA ham tekshiradi (§0 darvoza testlari), lekin u yerda
       solishtirish «men ↔ qolganlar» ko'rinishida. Bu test BUTUN matritsani bitta
       joyda o'lchaydi, ya'ni oltinchi darvoza qo'shilganda ham qamrov to'liq qoladi.
    """
    jadval = _darvoza_jadvali()
    sabablar = {rel: sabab for rel, (_i, sabab) in jadval.items()}
    for rel_a, a in sabablar.items():
        assert a.strip() == a and a, f"`{rel_a}` sababi bo'sh yoki chetida bo'shliq bor"
        for rel_b, b in sabablar.items():
            if rel_a >= rel_b:
                continue
            assert a != b, f"`{rel_a}` va `{rel_b}` sababi AYNI: {a!r}"
            assert a not in b and b not in a, (
                f"`{rel_a}` va `{rel_b}` sabablari bir-birining BO'LAGI: {a!r} ↔ {b!r} — "
                f"ro'yxatdan bitta yozuv yo'qolsa skip ikkinchisiga yashirinib o'tardi")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. BESH MODULNING SKIP'LARI RATIFIKATSIYA QILINGAN BO'LSIN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_BESH_modulning_skiplari_ALLOWLISTDA_ratifikatsiya_qilingan():
    """⚠️⚠️ TESHIKNING (c) QISMI: darvoza to'g'ri bo'lib, skip'lar ro'yxatga YOZILMASA,
         HAQIQIY Linux CI'da ular «KUTILMAGAN skip» bo'lib backend job'ni QIZIL qiladi.
         Beshta teshikning har birida AYNAN shu bo'lak yetishmagan edi.

    O'lchanadigan uch narsa:
      1. HAR modulning kamida bitta yozuvi BOR;
      2. o'sha modulning HAMMA yozuvi AYNAN shu modulning sabab matnini ishlatadi
         (chalkash sabab = `_matches` mos kelmaydi = KUTILMAGAN skip);
      3. `glob:` ISHLATILMAYDI — ro'yxat konventsiyasi aniq id talab qiladi, aks holda
         yangi, ko'rilmagan skip jimgina o'tib ketardi.
    """
    jadval = _darvoza_jadvali()
    qoidalar = _allowlist_qoidalari()
    for rel, (_ildiz, sabab) in sorted(jadval.items()):
        prefiks = rel[len("tests/"):-len(".py")]
        prefiks = f"tests.{prefiks}::"
        tegishli = [(pat, s) for pat, s in qoidalar if pat.startswith(prefiks)]
        assert tegishli, (
            f"`{rel}` uchun `tests/ci_expected_skips.txt` da BIRORTA yozuv YO'Q — "
            f"Linux CI'da uning skip'lari KUTILMAGAN bo'lib job'ni QIZIL qiladi.")
        for pat, s in tegishli:
            assert not pat.startswith("glob:"), \
                f"`{pat}` `glob:` ishlatadi — ro'yxat ANIQ id talab qiladi"
            assert s == sabab, (
                f"`{pat}` yozuvi BOSHQA sabab matnini ishlatadi: {s!r}, kutilgani "
                f"{sabab!r} — `_matches` mos kelmaydi va skip KUTILMAGAN bo'ladi")
