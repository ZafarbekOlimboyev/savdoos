# -*- coding: utf-8 -*-
"""OPERATOR RUNBOOK va PLATFORMA MOSLIK jadvalining DARVOZA testlari (§9, §11).

⚠️ NIMANI ISBOTLAYDI: ikki hujjatning KOD bilan mos ekanini — artefakt nomlari
   `runtime_bundle.REQUIRED_FILES` dan, validator buyrug'i `cli.py` dan, rejim
   `runtime_bundle.DEFAULT_MODE` dan, 2-jadvalning maydonlari `BinOSDiscovery.bsl`
   manbasidan olinganini. Riskli tugmalar ro'yxatining to'liqligini va hujjatlarda
   ISBOTLANMAGAN runtime da'vosi yo'qligini.
⚠️ NIMANI ISBOTLAMAYDI: modulning 1C dagi xatti-harakatini. Bu mashinada
   1C:Enterprise YO'Q. Hujjat to'g'ri yozilgani — natija to'g'ri bo'lishi EMAS.

⚠️ NEGA HUJJAT TESTLANADI: hujjat kod bilan bog'lanmasa, u jimgina eskiradi va
   «runbook bor» degan yolg'on xotirjamlik qoladi. Eskirgan runbook — operatorni
   mavjud bo'lmagan tugmaga yuboradigan hujjat, ya'ni yo'qligidan XAVFLIROQ.
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import re

import pytest

from app.services.discovery_1c import cli
from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_1c import REQUIRED_MEMBERS

# ── Hujjatlar va manbalar ──────────────────────────────────────────────────────────────────
_REPO = pathlib.Path(rb.__file__).resolve().parents[5]

RUNBOOK = _REPO / "integrations" / "1c" / "OPERATOR_RUNBOOK.md"
MOSLIK = _REPO / "integrations" / "1c" / "PLATFORM_COMPATIBILITY.md"
BSL = _REPO / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl"

#: `KNOWN` qatorning dalili shu manbalarda topilishi SHART. ⚠️ Ro'yxat ATAYLAB qisqa:
#: dalil bo'lib faqat MAJBURLAYDIGAN joy (validator, statik audit, yig'uvchi manbasi)
#: qabul qilinadi — testning o'zi yoki boshqa hujjat dalil bo'la olmaydi.
_DALIL_MANBALARI = (
    pathlib.Path(rb.__file__),
    pathlib.Path(rb.__file__).with_name("runtime_audit.py"),
    pathlib.Path(rb.__file__).with_name("epf_audit.py"),
    pathlib.Path(rb.__file__).with_name("export_adapter.py"),
    BSL,
)


def _matn(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def runbook() -> str:
    return _matn(RUNBOOK)


@pytest.fixture(scope="module")
def moslik() -> str:
    return _matn(MOSLIK)


@pytest.fixture(scope="module")
def dalil_matni() -> str:
    return "\n".join(_matn(p) for p in _DALIL_MANBALARI)


# ── Markdown jadval tahlilchisi ────────────────────────────────────────────────────────────
def _bolim(matn: str, sarlavha: str) -> str:
    """`## <sarlavha>` dan keyingi va keyingi `## ` gacha bo'lgan matn."""
    i = matn.index(sarlavha)
    keyingi = matn.find("\n## ", i + len(sarlavha))
    return matn[i:] if keyingi < 0 else matn[i:keyingi]


def _qatorlar(bolim: str, ustunlar: int) -> list[list[str]]:
    """Jadval qatorlari: birinchi katagi SON bo'lgan va ustun soni mos qatorlar.

    ⚠️ Sarlavha va `|---|` ajratuvchisi tushib qoladi, chunki ularning birinchi
       katagi son emas. Shu bois jadvalga izoh qatori qo'shilsa ham tahlil buzilmaydi."""
    natija = []
    for satr in bolim.splitlines():
        s = satr.strip()
        if not s.startswith("|"):
            continue
        kataklar = [k.strip() for k in s.strip("|").split("|")]
        if len(kataklar) == ustunlar and kataklar[0].isdigit():
            natija.append(kataklar)
    return natija


def _teskari_apostrofdagilar(katak: str) -> list[str]:
    return re.findall(r"`([^`]+)`", katak)


#: Dalil sifatida qabul qilinadigan fayl ildizlari (hujjatdagi yo'l qisqa yozilgan).
_FAYL_ILDIZLARI = (
    _REPO,
    _REPO / "apps" / "server",
    pathlib.Path(rb.__file__).parent,
)


def _dalil_topildi(token: str, dalil_matni: str) -> bool:
    """Token kodda TA'RIFLANGANMI (eslanganmi EMAS).

    ⚠️ NEGA «ESLANGAN» YETARLI EMAS: `METADATA_ONLY` kabi shartnoma QIYMATI hamma
       joyda uchraydi, lekin u hech narsani MAJBURLAMAYDI. Dalil bo'lib faqat
       TA'RIF joyi qabul qilinadi: funksiya (`def` / `Функция` / `Процедура`),
       modul darajasidagi doimiy (`NOM = ...`), statik audit qoidasi
       (`Rule("NOM"`), validator tekshiruvining nomi (`CHECK_NAMES`) yoki repoda
       ROSTDAN turgan fayl. Aks holda `KNOWN` qatori bezakli taxmin bo'lib qolardi."""
    for ildiz in _FAYL_ILDIZLARI:
        if (ildiz / token).is_file():
            return True
    sym = token.split(".")[-1].strip()
    if not sym or len(sym) < 4:
        return False
    if sym in rb.CHECK_NAMES:
        return True
    naqshlar = (
        rf"^def {re.escape(sym)}\s*\(",
        rf"^(?:Функция|Процедура) {re.escape(sym)}\s*\(",
        rf"^{re.escape(sym)}\s*[:=]",
        rf'Rule\("{re.escape(sym)}"',
    )
    return any(re.search(n, dalil_matni, re.M) for n in naqshlar)


def _holat(katak: str) -> str:
    """`` `UNKNOWN` `` → `UNKNOWN`. Bezakni olib tashlaydi."""
    return katak.strip().strip("*").strip("`").strip()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · HUJJATLAR MAVJUD
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_ikki_hujjat_REPODA_mavjud():
    assert RUNBOOK.is_file(), f"runbook topilmadi: {RUNBOOK}"
    assert MOSLIK.is_file(), f"moslik jadvali topilmadi: {MOSLIK}"
    assert BSL.is_file(), f"yig'uvchi manbasi topilmadi: {BSL}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · RUNBOOK — YETTI ARTEFAKT AYNAN KOD NOMI BILAN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_runbook_YETTI_artefaktni_AYNAN_kod_nomi_bilan_sanaydi(runbook):
    """⚠️ QULF: paket shartnomasi o'zgarsa runbook ham o'zgarishi SHART. Operator
    nomni AYNAN shu hujjatdan o'qiydi; bir harf farq — boshqa fayl izlash."""
    kutilgan = list(rb.REQUIRED_FILES) + list(rb.OPTIONAL_FILES)
    assert len(kutilgan) == 7, f"paket shartnomasi 7 artefakt emas: {kutilgan}"
    for nom in kutilgan:
        assert f"`{nom}`" in runbook, f"runbook `{nom}` artefaktini sanamaydi"


def test_runbook_MAJBURIY_va_IXTIYORIY_ni_ajratadi(runbook):
    """Majburiy fayl qatori `HA`, zond qatori `YO'Q` deb belgilangan bo'lishi kerak."""
    bolim = _bolim(runbook, "### 7-qadam.")
    qatorlar = _qatorlar(bolim, 5)
    assert len(qatorlar) == 7, f"7-qadam jadvalida 7 qator kutilgan, {len(qatorlar)} bor"
    xarita = {_teskari_apostrofdagilar(q[1])[0]: q[3] for q in qatorlar}
    for nom in rb.REQUIRED_FILES:
        assert xarita[nom].startswith("HA"), f"{nom} majburiy deb belgilanmagan"
    for nom in rb.OPTIONAL_FILES:
        assert xarita[nom].startswith("YO'Q"), f"{nom} ixtiyoriy deb belgilanmagan"


def test_runbook_TOPLAM_azolari_bilan_NOM_TALASHMAYDI(runbook):
    """⚠️ `status.json` / `summary.md` — to'plamning a'zolari, paketning EMAS.
    Runbook operatorni bu tuzoqdan OCHIQ ogohlantirishi kerak."""
    talashadigan = [m for m in REQUIRED_MEMBERS if m in ("status.json", "summary.md")]
    assert talashadigan, "to'plam a'zolari ro'yxati o'zgargan — tuzoq izohi qayta yozilsin"
    for m in talashadigan:
        assert m not in rb.REQUIRED_FILES, f"{m} paket shartnomasiga kirib qolgan"
        assert f"`{m}`" in runbook, f"runbook `{m}` tuzog'ini eslatmaydi"
    assert "BO'LMAYDI" in runbook, "runbook bu fayllar papkada BO'LMAYDI deb aytmaydi"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · RUNBOOK — VALIDATOR BUYRUG'I HAQIQIY
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_runbook_VALIDATOR_buyrugi_KOD_bilan_AYNAN_bir_xil(runbook):
    buyruq = f"{cli.PROG} {cli.VALIDATE_CMD}"
    assert buyruq in runbook, f"runbookda validator buyrug'i mos emas; kutilgani: {buyruq}"


def test_runbook_VALIDATOR_moduli_YOLI_ROSTDAN_mavjud(runbook):
    """Runbookdagi `-m <modul>` yo'li importlanadigan modulga tushishi SHART."""
    mos = re.search(r"python -m ([\w.]+) " + re.escape(cli.VALIDATE_CMD), runbook)
    assert mos, "runbookda `python -m <modul> validate-runtime-bundle` satri yo'q"
    modul = mos.group(1)
    assert modul == cli.__name__, f"modul yo'li mos emas: {modul!r} != {cli.__name__!r}"
    assert importlib.util.find_spec(modul) is not None, f"{modul} importlanmadi"


def test_runbook_VALIDATOR_BOSH_papkada_kod_1_qaytaradi(tmp_path):
    """⚠️ Buyruq HAQIQATAN bajariladigan buyruq ekanining isboti: bo'sh papka —
    majburiy fayllar yo'q — chiqish kodi AYNAN `1` (paket haqidagi hukm), `2` EMAS.

    ⚠️ Subprocess ATAYLAB ishlatilmaydi: Windows konsolining cp1252 kodlashi
       hisobot matnini buzib, testni yolg'on yiqitardi. Bu yerda kirish nuqtasi
       AYNAN CLI ning o'zi."""
    out, err = io.StringIO(), io.StringIO()
    kod = cli.main([cli.VALIDATE_CMD, str(tmp_path)], out=out, err=err)
    assert kod == cli.EXIT_PROBLEM, f"bo'sh papka uchun {cli.EXIT_PROBLEM} kutilgan, {kod} keldi"
    assert cli.MARK_BAD in out.getvalue()


def test_runbook_CHIQISH_KODLARINI_kod_bilan_MOS_yozadi(runbook):
    """Runbookdagi uch kod `cli.py` dagi shartnoma bilan bir xil bo'lishi SHART."""
    bolim = _bolim(runbook, "### 9-qadam.")
    for kod in (cli.EXIT_OK, cli.EXIT_PROBLEM, cli.EXIT_USAGE):
        assert re.search(rf"^\| `{kod}` \|", bolim, re.M), f"9-qadamda `{kod}` kodi yozilmagan"
    assert (cli.EXIT_OK, cli.EXIT_PROBLEM, cli.EXIT_USAGE) == (0, 1, 2), \
        "chiqish kodlari shartnomasi o'zgargan — runbook 9-qadami qayta yozilsin"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · RUNBOOK — RISKLI TUGMALAR
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ Bu ro'yxat QO'LDA yozilgan va u TALAB: har biri runbookda bo'lishi SHART.
#: Tugmalar 1C konfiguratsiyalarining tipik nomlari bo'yicha rus tilida yoziladi —
#: operator ekranda AYNAN shu matnni ko'radi, tarjimasini emas.
RISKLI_TUGMALAR: tuple[str, ...] = (
    "Выгрузить в весы",
    "Загрузить",
    "Синхронизировать",
    "Передать в весы",
    "Записать",
    "Провести",
    "Удалить",
)


@pytest.mark.parametrize("tugma", RISKLI_TUGMALAR)
def test_runbook_RISKLI_TUGMANI_sanaydi(runbook, tugma):
    assert tugma in runbook, f"riskli tugma runbookda yo'q: {tugma}"


def test_runbook_RISKLI_TUGMALAR_bolimi_ALOHIDA_va_KORINADIGAN(runbook):
    """⚠️ Bo'lim alohida sarlavha bilan va qadamlardan OLDIN turishi kerak:
    operator uni qadamlarni bajarib bo'lgandan keyin emas, OLDIN o'qishi kerak."""
    assert "## ⚠️ BU TUGMALAR KERAK EMAS" in runbook, "riskli tugmalar bo'limi sarlavhasi yo'q"
    assert runbook.index("## ⚠️ BU TUGMALAR KERAK EMAS") < runbook.index("### 1-qadam."), \
        "riskli tugmalar bo'limi qadamlardan KEYIN qolgan"


def test_runbook_HAR_RISKLI_TUGMA_qatori_KERAK_EMAS_deb_yozadi(runbook):
    """⚠️ «Ehtiyot bo'ling» YEMAS: har qator AYNAN «KERAK EMAS» deb yozilishi SHART.
    Ikkilanish qoldiradigan ibora operatorni tanlov oldida qoldiradi."""
    bolim = _bolim(runbook, "## ⚠️ BU TUGMALAR KERAK EMAS")
    for tugma in RISKLI_TUGMALAR:
        satrlar = [s for s in bolim.splitlines() if tugma in s and s.strip().startswith("|")]
        assert satrlar, f"{tugma} uchun jadval qatori yo'q"
        assert any("KERAK EMAS" in s for s in satrlar), \
            f"{tugma} qatorida «KERAK EMAS» yozilmagan"
    assert "Ehtiyot bo'ling" not in bolim, "yumshoq ibora qaytib kelgan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · RUNBOOK — REJIM, QADAMLAR, TO'XTASH SHARTLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_runbook_DEFAULT_rejimni_KOD_bilan_MOS_yozadi(runbook):
    """`METADATA_ONLY` — DEFAULT. ⚠️ Bitta satrda ikkisi birga yozilishi SHART:
    alohida joylarda turgan «default» va «METADATA_ONLY» bog'lanmay qolardi."""
    assert rb.DEFAULT_MODE == "METADATA_ONLY", "default rejim o'zgargan — runbook qayta yozilsin"
    satrlar = [s for s in runbook.splitlines()
               if rb.DEFAULT_MODE in s and "DEFAULT" in s]
    assert satrlar, f"runbook `{rb.DEFAULT_MODE}` ni DEFAULT deb aytmaydi"


def test_runbook_AKTIV_zondni_operator_TANLAMAYDI(runbook):
    """`APPROVED_PROBES` eslanadi, lekin operatorga TANLAMASLIK deb aytiladi."""
    assert rb.MODE_APPROVED_PROBES in runbook
    bolim = _bolim(runbook, "### 4-qadam.")
    assert "uni tanlamaslik" in bolim, "4-qadam aktiv zond rejimini tanlamaslikni aytmaydi"


def test_runbook_ONTA_QADAMNI_qamraydi(runbook):
    raqamlar = [int(m) for m in re.findall(r"^### (\d+)-qadam\.", runbook, re.M)]
    assert raqamlar == list(range(1, 11)), f"§9 o'n qadam emas: {raqamlar}"


@pytest.mark.parametrize("qadam", range(1, 11))
def test_runbook_har_qadam_UCH_javobni_beradi(runbook, qadam):
    """⚠️ Har qadamda: nima qilish · nima ko'rinishi kerak · boshqacha bo'lsa nima
    qilish. Uchinchisi YO'Q bo'lsa operator xato holatda o'zi qaror qabul qilardi."""
    bolim = _bolim(runbook.replace("\n### ", "\n## "), f"## {qadam}-qadam.")
    for talab in ("Nima qilish", "Nima ko'rinishi kerak", "Boshqacha bo'lsa"):
        assert talab in bolim, f"{qadam}-qadamda «{talab}» yo'q"


def test_runbook_TOXTASH_shartlari_KODLANGAN_va_QADAMLARGA_bogliq(runbook):
    """To'xtash shartlari ALOHIDA bo'limda va har biri kodli (`T1`…): qadam matni
    shu kodga havola qiladi, ya'ni «to'xtash» aniq shartga bog'langan."""
    bolim = _bolim(runbook, "## TO'XTASH SHARTLARI")
    kodlar = re.findall(r"^\| `(T\d+)` \|", bolim, re.M)
    assert kodlar == [f"T{i}" for i in range(1, len(kodlar) + 1)], f"kodlar uzluksiz emas: {kodlar}"
    assert len(kodlar) >= 5, f"to'xtash shartlari juda kam: {kodlar}"
    for kod in kodlar:
        assert runbook.count(f"`{kod}`") >= 2, f"{kod} birorta qadamdan havola qilinmagan"


@pytest.mark.parametrize("shart", [
    "parol",              # 1C parol so'rasa
    "jonli",              # baza jonli ekani aniqlansa
    "bo'sh emas",         # papka bo'sh emas
    "Xato oynasi",        # xato oynasi chiqsa
])
def test_runbook_TOXTASH_shartlari_TALAB_qilinganlarni_qamraydi(runbook, shart):
    bolim = _bolim(runbook, "## TO'XTASH SHARTLARI")
    assert shart in bolim, f"to'xtash shartlarida «{shart}» holati yo'q"


def test_runbook_VALIDATOR_1_qaytarsa_TOXTASH_deb_yozadi(runbook):
    bolim = _bolim(runbook, "## TO'XTASH SHARTLARI")
    satrlar = [s for s in bolim.splitlines() if "Validator" in s]
    assert satrlar and any(f"`{cli.EXIT_PROBLEM}`" in s for s in satrlar), \
        "validatorning `1` kodi to'xtash sharti emas"


def test_runbook_BOSHIDA_tort_shartni_OCHIQ_yozadi(runbook):
    """⚠️ Boshida: ajratilgan NUSXA · jonli bazada EMAS · modul hech qachon
    bajarilmagan · egasining YOZMA roziligi · 1C mutaxassisining sintaksis tekshiruvi."""
    bosh = runbook[:runbook.index("## ⚠️ BU TUGMALAR KERAK EMAS")]
    for talab in ("AJRATILGAN NUSXA", "Jonli bazada", "YOZMA roziligi",
                  "sintaksis", "hech qachon bajarilmagan", "RUNTIME-UNKNOWN"):
        assert talab in bosh, f"runbook boshida «{talab}» yo'q"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · IKKI HUJJATDA ISBOTLANMAGAN DA'VO YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ TAQIQLANGAN IBORALAR. Hech biri isbotlanmagan: bu mashinada 1C:Enterprise YO'Q.
#: Ro'yxat ANIQ iboralardan iborat, bitta so'zdan emas — «kompilyatsiya direktivasi»
#: kabi halol texnik atama yolg'on ijobiy bermasligi kerak.
TAQIQLANGAN_DALVOLAR: tuple[str, ...] = (
    "ishlaydi",
    "ishlab turadi",
    "kompilyatsiya qilinadi",
    "kompilyatsiya qilingan",
    "runtime tasdiqlangan",
    "runtime tekshirilgan",
    "production tayyor",
    "ishlashi tasdiqlangan",
    "ishlashi kafolatlangan",
    "sinovdan o'tgan",
    "sinalgan va",
)


@pytest.mark.parametrize("hujjat", [RUNBOOK, MOSLIK], ids=lambda p: p.name)
@pytest.mark.parametrize("dalvo", TAQIQLANGAN_DALVOLAR)
def test_hujjatda_ISBOTLANMAGAN_dalvo_YOQ(hujjat, dalvo):
    matn = _matn(hujjat).lower()
    assert dalvo.lower() not in matn, \
        f"{hujjat.name}: isbotlanmagan da'vo — «{dalvo}». Runtime holati RUNTIME-UNKNOWN"


@pytest.mark.parametrize("hujjat", [RUNBOOK, MOSLIK], ids=lambda p: p.name)
def test_hujjat_RUNTIME_holatini_OCHIQ_aytadi(hujjat):
    matn = _matn(hujjat)
    assert "1C:Enterprise" in matn and "YO'Q" in matn, \
        f"{hujjat.name}: platforma yo'qligi ochiq yozilmagan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · MOSLIK 1-JADVAL — KNOWN / UNKNOWN
# ══════════════════════════════════════════════════════════════════════════════════════════
HOLATLAR = ("KNOWN", "UNKNOWN")


@pytest.fixture(scope="module")
def jadval1(moslik) -> list[list[str]]:
    qatorlar = _qatorlar(_bolim(moslik, "## 1-JADVAL"), 5)
    assert qatorlar, "1-jadval topilmadi yoki bo'sh"
    return qatorlar


@pytest.fixture(scope="module")
def jadval2(moslik) -> list[list[str]]:
    qatorlar = _qatorlar(_bolim(moslik, "## 2-JADVAL"), 6)
    assert qatorlar, "2-jadval topilmadi yoki bo'sh"
    return qatorlar


def test_moslik_1_jadval_qatorlari_UZLUKSIZ_raqamlangan(jadval1):
    assert [int(q[0]) for q in jadval1] == list(range(1, len(jadval1) + 1))


def test_moslik_1_jadval_TALAB_qilingan_olchamlarni_qamraydi(jadval1):
    """§11: platforma versiyalari · managed/ordinary · klient turi · fayl/server
    infobase · DB turi · lokal — oltisi ham jadvalda bo'lishi SHART."""
    olchamlar = {q[1] for q in jadval1}
    for talab in ("platforma versiyasi", "ilova rejimi", "klient turi",
                  "infobase", "DB turi", "lokal"):
        assert talab in olchamlar, f"1-jadvalda «{talab}» o'lchami yo'q"


def test_moslik_1_jadval_FAQAT_lugatdagi_holatni_ishlatadi(jadval1):
    for q in jadval1:
        assert _holat(q[3]) in HOLATLAR, f"{q[0]}-qator: noma'lum holat {q[3]!r}"


def test_moslik_1_jadval_UNKNOWN_KOPCHILIK(jadval1):
    """⚠️ Taxmin bilan `KNOWN` yozilmasin: platforma o'lchanmagan, shu bois
    moslik qatorlarining KO'PCHILIGI `UNKNOWN` bo'lishi kerak."""
    holatlar = [_holat(q[3]) for q in jadval1]
    noma_lum = holatlar.count("KNOWN")
    assert holatlar.count("UNKNOWN") > noma_lum, \
        f"jadval bo'shashib ketgan: {noma_lum} `KNOWN` / {len(holatlar)} qator"


def test_moslik_1_jadval_KNOWN_qatori_KODDA_MAJBURLAGAN_joyni_korsatadi(jadval1, dalil_matni):
    """⚠️ ASOSIY DARVOZA: `KNOWN` deb belgilangan har qator kamida bitta HAQIQIY kod
    nomiga tayanadi va o'sha nom manbada ROSTDAN bor. Aks holda `KNOWN` — taxmin."""
    known = [q for q in jadval1 if _holat(q[3]) == "KNOWN"]
    assert known, "birorta `KNOWN` qator yo'q — kod majburlagan narsalar tushib qolgan"
    for q in known:
        tokenlar = _teskari_apostrofdagilar(q[4])
        topilgan = [t for t in tokenlar if _dalil_topildi(t, dalil_matni)]
        assert topilgan, (
            f"{q[0]}-qator `KNOWN`, lekin dalili KODDA TA'RIFLANMAGAN: {tokenlar}. "
            f"`KNOWN` faqat KOD MAJBURLAGAN narsa uchun yoziladi — shartnoma "
            f"QIYMATINI eslash dalil emas")


def test_moslik_1_jadval_UNKNOWN_qatori_SABABSIZ_qolmaydi(jadval1):
    """`UNKNOWN` ham izohsiz qolmaydi: nega kod bilan hal qilinmasligi yozilishi kerak."""
    for q in jadval1:
        if _holat(q[3]) != "UNKNOWN":
            continue
        assert len(q[4]) >= 30, f"{q[0]}-qator: `UNKNOWN` sababi juda qisqa: {q[4]!r}"
        assert not re.search(r"(?<![A-Z-])KNOWN", q[4]), \
            f"{q[0]}-qator: `UNKNOWN` qatorida `KNOWN` da'vosi qolgan"


def test_moslik_1_jadval_TAQSIMOTI_jadval_bilan_MOS(moslik, jadval1):
    """⚠️ Matnda yozilgan taqsimot jadvaldan HISOBLANADI, qo'lda emas."""
    mos = re.search(r"(\d+) qator — `UNKNOWN` \*\*(\d+)\*\*, `KNOWN` \*\*(\d+)\*\*", moslik)
    assert mos, "1-jadval taqsimoti yozilmagan"
    jami, noaniq, aniq = (int(g) for g in mos.groups())
    holatlar = [_holat(q[3]) for q in jadval1]
    assert (jami, noaniq, aniq) == (len(holatlar), holatlar.count("UNKNOWN"),
                                    holatlar.count("KNOWN"))


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · MOSLIK 2-JADVAL — MAYDONLAR KOD BILAN MOS
# ══════════════════════════════════════════════════════════════════════════════════════════
#: §11 talab qilgan yetti maydon → 2-jadvaldagi JSON kaliti.
SS11_MAYDONLARI: dict[str, str] = {
    "platform version": "platform_version",
    "configuration name": "configuration_name",
    "configuration version": "configuration_version",
    "client type": "client_kind",
    "locale": "locale",
    "DB type": "db_type",
    "managed/ordinary": "application_mode",
}


def _maydon_xaritasi(jadval2: list[list[str]]) -> dict[str, str]:
    xarita = {}
    for q in jadval2:
        kalitlar = _teskari_apostrofdagilar(q[1])
        assert len(kalitlar) == 1, f"{q[0]}-qator: maydon kaliti noaniq: {q[1]!r}"
        xarita[kalitlar[0]] = _holat(q[3])
    return xarita


def test_moslik_2_jadval_SS11_maydonlarini_QAMRAYDI(jadval2):
    xarita = _maydon_xaritasi(jadval2)
    for nom, kalit in SS11_MAYDONLARI.items():
        assert kalit in xarita, f"§11 maydoni «{nom}» (`{kalit}`) 2-jadvalda yo'q"


def test_moslik_2_jadval_FAQAT_lugatdagi_holatni_ishlatadi(jadval2):
    ruxsat = ("BOR", "BOR (QISMAN)", "BOR (BO'SH)", "YO'Q")
    for q in jadval2:
        assert _holat(q[3]) in ruxsat, f"{q[0]}-qator: noma'lum holat {q[3]!r}"


def test_moslik_2_jadval_BOR_maydoni_BSL_da_ROSTDAN_bor(jadval2):
    """⚠️ DARVOZA: `BOR` deb yozilgan maydonning JSON kaliti yig'uvchi manbasida
    ROSTDAN yoziladi. Grep — `"kalit"` literalini qidirish, chunki yig'uvchi kalitni
    AYNAN shunday qo'yadi (`Вставить("kalit", ...)`)."""
    manba = _matn(BSL)
    xarita = _maydon_xaritasi(jadval2)
    borlar = [k for k, h in xarita.items() if h.startswith("BOR")]
    assert len(borlar) >= len(SS11_MAYDONLARI), "yig'uvchi chiqishi juda kambag'al ko'rsatilgan"
    for kalit in borlar:
        assert f'"{kalit}"' in manba, \
            f"`{kalit}` `BOR` deb yozilgan, lekin {BSL.name} da yozilmaydi"


def test_moslik_2_jadval_YOQ_maydoni_BSL_da_ROSTDAN_yoq(jadval2):
    """⚠️ Teskari tomon ham qulflanadi: `YO'Q` deb yozilgan maydon rostdan yo'q.
    Aks holda hujjat mavjud qobiliyatni yashirib turardi."""
    manba = _matn(BSL)
    xarita = _maydon_xaritasi(jadval2)
    yoqlar = [k for k, h in xarita.items() if h == "YO'Q"]
    assert yoqlar, "birorta `YO'Q` maydon yo'q — qobiliyat chegaralari yozilmagan"
    for kalit in yoqlar:
        assert f'"{kalit}"' not in manba, \
            f"`{kalit}` `YO'Q` deb yozilgan, lekin {BSL.name} da ROSTDAN bor"


def test_moslik_2_jadval_TAQSIMOTI_jadval_bilan_MOS(moslik, jadval2):
    mos = re.search(
        r"(\d+) qator — `BOR` \*\*(\d+)\*\*, `BOR \(QISMAN\)` \*\*(\d+)\*\*, "
        r"`BOR \(BO'SH\)` \*\*(\d+)\*\*, `YO'Q` \*\*(\d+)\*\*", moslik)
    assert mos, "2-jadval taqsimoti yozilmagan"
    jami, bor, qisman, bosh, yoq = (int(g) for g in mos.groups())
    holatlar = [_holat(q[3]) for q in jadval2]
    assert (jami, bor, qisman, bosh, yoq) == (
        len(holatlar), holatlar.count("BOR"), holatlar.count("BOR (QISMAN)"),
        holatlar.count("BOR (BO'SH)"), holatlar.count("YO'Q"))


def test_moslik_2_jadval_ARTEFAKT_nomlari_SHARTNOMADAN(jadval2):
    """Maydon qaysi artefaktga tushishi ko'rsatilgan bo'lsa, u AYNAN paket fayli bo'lsin."""
    ruxsat = set(rb.REQUIRED_FILES)
    for q in jadval2:
        if _holat(q[3]) == "YO'Q":
            continue
        fayllar = {t for t in _teskari_apostrofdagilar(q[4]) if t.endswith(".json")}
        assert fayllar, f"{q[0]}-qator: artefakt ko'rsatilmagan"
        begona = fayllar - ruxsat
        assert not begona, f"{q[0]}-qator: paket shartnomasida yo'q artefakt {sorted(begona)}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · OCHIQ NUQSON: `run_status.json` SHAKLI IKKI TOMONDA MOS EMAS
# ══════════════════════════════════════════════════════════════════════════════════════════
def _bsl_run_status_kalitlari() -> set[str]:
    """`СобратьСостояниеЗапуска` tanasida `Документ.Вставить("...")` bilan qo'yilgan kalitlar."""
    manba = _matn(BSL)
    i = manba.index("Функция СобратьСостояниеЗапуска")
    j = manba.index("КонецФункции", i)
    return set(re.findall(r'Документ\.Вставить\("([a-z_]+)"', manba[i:j]))


def test_run_status_shakli_IKKI_TOMONDA_MOS(moslik):
    """⚠️ Ilgari bu yerda uch test NUQSONNI qulflagandi: `run_status.json` ning BSL va
    validator shakllari bir-biriga MOS KELMASDI va real paket 9-qadamda yiqilardi.
    Shakl yarashtirildi, shu bois testlar o'z shartiga ko'ra NAFAQAGA chiqdi va
    o'rniga TESKARI darvoza turadi: shakl mos bo'lsa, hujjat YO'Q nuqsonni da'vo
    qilmasligi kerak (eskirgan «OCHIQ NUQSON» bo'limi hujjatni ishonchsiz qiladi).

    ⚠️ Kalit tengligining O'ZI bu yerda emas — uni `test_discovery_1c_conformance.py`
    ancha qat'iyroq tekshiradi (RUN/ERROR/MANIFEST/zond kalitlari, oila holatlari,
    bo'lim holatlari, xato qamrovlari, provenans taqiqi va `overall` ta'riflari).
    Bu test faqat HUJJAT bilan KOD orasidagi eskirishni tutadi."""
    bsl = _bsl_run_status_kalitlari()
    assert bsl, "`СобратьСостояниеЗапуска` kalitlari o'qilmadi"
    notanish = sorted(bsl - rb.RUN_KEYS)
    tushib_qolgan = sorted(rb.RUN_KEYS - bsl)
    assert not notanish and not tushib_qolgan, (
        "ikki shakl YANA ajralib ketdi — validator bilmaydigan kalit(lar): "
        f"{notanish}; yig'uvchi yozmaydigan kalit(lar): {tushib_qolgan}")
    assert "OCHIQ NUQSON" not in moslik, (
        "shakl MOS, lekin moslik hujjatida hamon «OCHIQ NUQSON» bo'limi bor — "
        "hujjat mavjud bo'lmagan nuqsonni ko'rsatib turadi")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10 · IKKI HUJJAT BIR-BIRIGA HAVOLA QILADI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_hujjatlar_BIR_BIRIGA_havola_qiladi(runbook, moslik):
    """Operator runbookdan boshlaydi; moslik jadvali unga qaytarishi kerak."""
    assert "OPERATOR_RUNBOOK.md" in moslik, "moslik jadvali runbookka havola qilmaydi"
    assert "RUNTIME_READINESS.md" in runbook, "runbook inventarga havola qilmaydi"
