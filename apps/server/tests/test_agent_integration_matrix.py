# -*- coding: utf-8 -*-
"""AGENT INTEGRATSIYA MATRITSASINING DARVOZA testlari.

⚠️ NIMANI ISBOTLAYDI: `integrations/1c/AGENT_INTEGRATION_MATRIX.md` hujjatining
   SHAKLINI va KOD bilan bog'liqligini — beshta yo'l ham baholanganini, holat
   lug'ati buzilmaganini, `KNOWN` deb belgilangan qatorning dalili kodda ROSTDAN
   TA'RIFLANGANINI, `/P` kredensial taqiqi ochiq yozilganini, PRIMARY/FALLBACK
   qarori shartnoma nomlari bilan AYNAN bir xil yozilganini va hujjatda
   isbotlanmagan runtime da'vosi yo'qligini.
⚠️ NIMANI ISBOTLAMAYDI: birorta integratsiya yo'lining 1C da bajarilishini. Bu
   mashinada 1C:Enterprise YO'Q: `1cv8.exe` ham, COM klassi ham, `.epf` ham yo'q.
   Hujjat to'g'ri yozilgani — yo'l ishga tushishi EMAS.

⚠️ NEGA HUJJAT TESTLANADI: strategiya hujjati kod bilan bog'lanmasa, u jimgina
   eskiradi va «matritsa bor» degan yolg'on xotirjamlik qoladi. Phase 4 darsi
   AYNAN shu: jadval berilgan, lekin majburlanmagan kalit nomlari ikki agentda
   har xil to'ldirilgan va har bir real paket rad etilgan. Shu bois bu yerda
   hujjatning HAR BIR da'vosi tekshiriladi, ro'yxat emas.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.services.discovery_1c import runtime_bundle as rb

# ── Hujjat va dalil manbalari ──────────────────────────────────────────────────────────────
_REPO = pathlib.Path(rb.__file__).resolve().parents[5]
_SERVICE = pathlib.Path(rb.__file__).parent

MATRITSA = _REPO / "integrations" / "1c" / "AGENT_INTEGRATION_MATRIX.md"
BSL = _REPO / "integrations" / "1c" / "extractor" / "BinOSDiscovery.bsl"

#: `KNOWN` / `SOURCE-VALIDATED` qatorning dalili SHU manbalarda topilishi SHART.
#: ⚠️ Ro'yxat ATAYLAB qisqa: dalil bo'lib faqat MAJBURLAYDIGAN joy (validator, statik
#: audit, yig'uvchi manbasi) qabul qilinadi — testning o'zi yoki boshqa hujjat dalil
#: bo'la OLMAYDI.
_DALIL_MANBALARI = (
    _SERVICE / "runtime_bundle.py",
    _SERVICE / "runtime_audit.py",
    _SERVICE / "epf_audit.py",
    _SERVICE / "redact.py",
    _SERVICE / "probe.py",
    _SERVICE / "cli.py",
    BSL,
)

#: Dalil sifatida qabul qilinadigan fayl ildizlari (hujjatda yo'l qisqa yozilgan).
_FAYL_ILDIZLARI = (_REPO, _REPO / "apps" / "server", _SERVICE, _REPO / "integrations" / "1c")

#: Holat lug'ati — UCHTA, boshqa qiymat yo'q.
HOLATLAR = ("KNOWN", "SOURCE-VALIDATED", "RUNTIME-UNKNOWN")

#: MVP ustunining ruxsat etilgan qiymatlari. ⚠️ `HA — SHARTLI` ATAYLAB bor: «simlanadi,
#: lekin preflight darvozasi ortida» — `HA` ham, `YO'Q` ham bu holatni to'g'ri aytmaydi.
MVP_QIYMATLAR = ("HA", "YO'Q", "HA — SHARTLI")

#: Arxitektor belgilagan agent holatlari. ⚠️ Hujjat FAQAT shu nomlarni ishlatishi mumkin:
#: hujjat yangi holat O'YLAB CHIQARSA, `states.py` yozilganda nom talashuvi chiqardi — Phase 4
#: nuqsonining aynan o'zi.
SHARTNOMA_HOLATLARI = frozenset({
    "START", "ENVIRONMENT_SCAN", "TARGET_SELECTION", "SAFETY_CHECK", "METADATA_DISCOVERY",
    "VALIDATION", "GRAPH_BUILD", "ANALYSIS", "OPTIONAL_APPROVED_PROBES", "REVALIDATE",
    "REPORT", "COMPLETE",
    "FAILED_NO_1C", "FAILED_NO_TARGET", "FAILED_AUTH_REQUIRED",
    "FAILED_COLLECTOR_UNAVAILABLE", "FAILED_SAFETY", "FAILED_VALIDATION",
    "FAILED_ANALYSIS", "FAILED_REPORT", "FAILED_TIMEOUT", "FAILED_INTERNAL",
    "ABORTED_BY_OPERATOR",
})

#: Shartnoma bergan ikki marshrut nomi — hujjat ularni AYNAN shunday yozishi SHART.
MARSHRUTLAR = ("batch_execute", "watch_folder")


def _matn(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def matritsa() -> str:
    return _matn(MATRITSA)


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

    ⚠️ Sarlavha va `|---|` ajratuvchisi tushib qoladi, chunki ularning birinchi katagi
       son emas. Shu bois jadvalga izoh qatori qo'shilsa ham tahlil buzilmaydi."""
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


def _holat(katak: str) -> str:
    """`` `RUNTIME-UNKNOWN` `` → `RUNTIME-UNKNOWN`. Bezakni olib tashlaydi."""
    return katak.strip().strip("*").strip("`").strip()


def _dalil_topildi(token: str, dalil_matni: str) -> bool:
    """Token kodda TA'RIFLANGANMI (eslanganmi EMAS).

    ⚠️ NEGA «ESLANGAN» YETARLI EMAS: `METADATA_ONLY` kabi shartnoma QIYMATI hamma joyda
       uchraydi, lekin u hech narsani MAJBURLAMAYDI. Dalil bo'lib faqat TA'RIF joyi qabul
       qilinadi: funksiya (`def` / `Функция` / `Процедура`), modul darajasidagi doimiy
       (`NOM = ...` yoki `NOM: ... = ...`), statik audit qoidasi (`Rule("NOM"`), validator
       tekshiruvi (`CHECK_NAMES`) yoki repoda ROSTDAN turgan fayl."""
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


@pytest.fixture(scope="module")
def jadval1(matritsa) -> list[list[str]]:
    qatorlar = _qatorlar(_bolim(matritsa, "## 1-JADVAL"), 9)
    assert qatorlar, "1-jadval topilmadi yoki bo'sh"
    return qatorlar


@pytest.fixture(scope="module")
def jadval2(matritsa) -> list[list[str]]:
    qatorlar = _qatorlar(_bolim(matritsa, "## 2-JADVAL"), 5)
    assert qatorlar, "2-jadval topilmadi yoki bo'sh"
    return qatorlar


# ── Ustun indekslari (1-jadval) ────────────────────────────────────────────────────────────
U_YOL, U_TALAB, U_XAVF, U_KRED, U_SINOV, U_HOLAT, U_MVP, U_SABAB = 1, 2, 3, 4, 5, 6, 7, 8


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1 · HUJJAT MAVJUD va SHAKLI BUTUN
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_REPODA_mavjud():
    assert MATRITSA.is_file(), f"matritsa hujjati yo'q: {MATRITSA}"
    assert _matn(MATRITSA).strip(), "matritsa hujjati bo'sh"


def test_matritsa_BESH_yolni_baholaydi(jadval1):
    """⚠️ Brief AYNAN beshta yo'lni so'raydi: biri tushib qolsa, u baholanmagan
    bo'ladi va keyin «hisobga olinmagan» deb qaytib keladi."""
    assert len(jadval1) == 5, f"1-jadvalda {len(jadval1)} qator, beshta bo'lishi SHART"
    assert [int(q[0]) for q in jadval1] == [1, 2, 3, 4, 5], "qatorlar uzluksiz raqamlanmagan"


#: Har qator AYNAN qaysi yo'l haqida ekanini ko'rsatadigan majburiy belgi.
YOL_BELGILARI = (
    (1, "external processor"),
    (2, "COMConnector"),
    (3, "1cv8.exe"),
    (4, "operator-opened session"),
    (5, "file/output-directory"),
)


@pytest.mark.parametrize("raqam,belgi", YOL_BELGILARI)
def test_matritsa_har_yol_ANIQ_nomlanadi(jadval1, raqam, belgi):
    katak = jadval1[raqam - 1][U_YOL]
    assert belgi.lower() in katak.lower(), \
        f"{raqam}-qator «{belgi}» yo'li haqida emas: {katak!r}"


@pytest.mark.parametrize("ustun,nom", [(U_TALAB, "nima talab qiladi"),
                                       (U_XAVF, "xavfsizlik"),
                                       (U_KRED, "kredensial oqimi"),
                                       (U_SINOV, "bu yerda sinaldimi"),
                                       (U_SABAB, "sabab")])
def test_matritsa_har_qatorda_har_ustun_TOLDIRILGAN(jadval1, ustun, nom):
    """⚠️ Bo'sh katak — baholanmagan o'lcham. `—` faqat kredensial ustunida ruxsat:
       ulanmaydigan yo'lda kredensial oqimi ROSTDAN yo'q."""
    for q in jadval1:
        katak = q[ustun]
        assert len(katak) >= 15 or (ustun == U_KRED and katak.startswith("—")), \
            f"{q[0]}-qator «{nom}» ustuni to'ldirilmagan: {katak!r}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2 · HOLAT LUG'ATI va `KNOWN` NING DALILI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_FAQAT_lugatdagi_holatni_ishlatadi(jadval1):
    for q in jadval1:
        assert _holat(q[U_HOLAT]) in HOLATLAR, f"{q[0]}-qator: noma'lum holat {q[U_HOLAT]!r}"


def test_matritsa_HOLAT_lugati_UCHOVINI_tariflaydi(matritsa):
    for h in HOLATLAR:
        assert f"`{h}`" in matritsa, f"holat lug'atida `{h}` ta'riflanmagan"


def test_matritsa_RUNTIME_UNKNOWN_KOPCHILIK(jadval1):
    """⚠️ Bu mashinada 1C YO'Q, shu bois yo'llarning KO'PCHILIGI `RUNTIME-UNKNOWN`
    bo'lishi kerak. `KNOWN` ko'payib ketsa — jadval taxmin bilan bo'shashgan."""
    holatlar = [_holat(q[U_HOLAT]) for q in jadval1]
    assert holatlar.count("RUNTIME-UNKNOWN") > holatlar.count("KNOWN"), \
        f"jadval bo'shashib ketgan: {holatlar}"


def test_matritsa_KNOWN_qatori_KODDA_MAJBURLAGAN_joyni_korsatadi(jadval1, dalil_matni):
    """⚠️ ASOSIY DARVOZA: `KNOWN` yoki `SOURCE-VALIDATED` deb belgilangan har qator
    kamida bitta HAQIQIY kod nomiga tayanadi va o'sha nom manbada ROSTDAN TA'RIFLANGAN.
    Aks holda holat — bezakli taxmin."""
    kuchli = [q for q in jadval1 if _holat(q[U_HOLAT]) in ("KNOWN", "SOURCE-VALIDATED")]
    assert kuchli, "birorta `KNOWN`/`SOURCE-VALIDATED` qator yo'q — kod majburlagani tushib qolgan"
    for q in kuchli:
        tokenlar = _teskari_apostrofdagilar(q[U_SABAB])
        topilgan = [t for t in tokenlar if _dalil_topildi(t, dalil_matni)]
        assert topilgan, (
            f"{q[0]}-qator `{_holat(q[U_HOLAT])}`, lekin dalili KODDA TA'RIFLANMAGAN: "
            f"{tokenlar}. Shartnoma QIYMATINI eslash dalil EMAS")


def test_matritsa_RUNTIME_UNKNOWN_qatori_SABABSIZ_qolmaydi(jadval1):
    for q in jadval1:
        if _holat(q[U_HOLAT]) != "RUNTIME-UNKNOWN":
            continue
        assert len(q[U_SABAB]) >= 40, f"{q[0]}-qator: sabab juda qisqa: {q[U_SABAB]!r}"
        assert not re.search(r"(?<![A-Z-])KNOWN", q[U_SABAB]), \
            f"{q[0]}-qator: `RUNTIME-UNKNOWN` qatorida `KNOWN` da'vosi qolgan"


def test_matritsa_TAQSIMOTI_jadval_bilan_MOS(matritsa, jadval1):
    """⚠️ Matnda yozilgan taqsimot jadvaldan HISOBLANADI, qo'lda emas."""
    mos = re.search(
        r"`RUNTIME-UNKNOWN` \*\*(\d+)\*\*, `SOURCE-VALIDATED` \*\*(\d+)\*\*, "
        r"`KNOWN` \*\*(\d+)\*\*", matritsa)
    assert mos, "yo'llar taqsimoti yozilmagan"
    holatlar = [_holat(q[U_HOLAT]) for q in jadval1]
    kutilgan = (holatlar.count("RUNTIME-UNKNOWN"), holatlar.count("SOURCE-VALIDATED"),
                holatlar.count("KNOWN"))
    assert tuple(int(g) for g in mos.groups()) == kutilgan, \
        f"taqsimot jadvalga mos emas: yozilgan {mos.groups()}, hisoblangan {kutilgan}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3 · COM QATORI — `RUNTIME-UNKNOWN` va MVP DAN TASHQARIDA
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def com_qator(jadval1) -> list[str]:
    qator = [q for q in jadval1 if "COMConnector" in q[U_YOL]]
    assert len(qator) == 1, "COM yo'li aynan bitta qatorda bo'lishi kerak"
    return qator[0]


def test_matritsa_COM_qatori_RUNTIME_UNKNOWN(com_qator):
    """⚠️ Bu mashinada `V83.COMConnector` ro'yxatda YO'Q, demak chaqiruv TEKSHIRIB
    BO'LMAYDI. «Ishlamaydi» — boshqa da'vo va u isbotlanmagan."""
    assert _holat(com_qator[U_HOLAT]) == "RUNTIME-UNKNOWN", \
        f"COM qatori holati {com_qator[U_HOLAT]!r}, `RUNTIME-UNKNOWN` bo'lishi SHART"


def test_matritsa_COM_qatori_MVP_dan_TASHQARIDA(com_qator):
    assert _holat(com_qator[U_MVP]) == "YO'Q", \
        f"COM qatori MVP ustuni {com_qator[U_MVP]!r}, `YO'Q` bo'lishi SHART"


def test_matritsa_COM_qatori_INKOR_DAVOSI_qilmaydi(com_qator):
    """⚠️ `RUNTIME-UNKNOWN` ≠ rad etildi. COM qatorida «tekshirib bo'lmaydi» degan
    ANIQ ibora turishi kerak, inkor da'vosi EMAS."""
    katak = (com_qator[U_SINOV] + " " + com_qator[U_SABAB]).lower()
    assert "tekshirib bo'lmaydi" in katak, \
        "COM qatori «tekshirib bo'lmaydi» demagan — holat noto'g'ri aytilgan"


def test_matritsa_COM_qoshimcha_XAVFLARINI_sanaydi(com_qator):
    """Brief talab qilgan uchta qo'shimcha xavf: bitness, COM registratsiyasi, huquq."""
    qator = " ".join(com_qator).lower()
    for talab in ("bitness", "ro'yxatga olingan com", "автоматизация"):
        assert talab in qator, f"COM qatorida «{talab}» xavfi yozilmagan"


def test_matritsa_COM_ni_TASHQI_kutubxona_sababi_bilan_ham_chiqaradi(com_qator):
    """⚠️ COM ni chiqarishning IKKINCHI mustaqil sababi: `pywin32` bu yerda yo'q va
    brief tashqi kutubxonani TAQIQLAYDI. Bitta sabab yo'qolsa ikkinchisi qoladi."""
    qator = " ".join(com_qator).lower()
    assert "pywin32" in qator, "COM qatorida `pywin32` talabi yozilmagan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4 · MVP USTUNI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_MVP_ustuni_FAQAT_lugatdagi_qiymat(jadval1):
    for q in jadval1:
        assert _holat(q[U_MVP]) in MVP_QIYMATLAR, \
            f"{q[0]}-qator: MVP qiymati {q[U_MVP]!r}, ruxsat etilgani {MVP_QIYMATLAR}"


def test_matritsa_MVP_da_kamida_bitta_yol_ISHLATILADI(jadval1):
    """⚠️ Hammasi `YO'Q` bo'lsa — strategiya emas, rad etish ro'yxati."""
    ishlatiladi = [q for q in jadval1 if _holat(q[U_MVP]) != "YO'Q"]
    assert ishlatiladi, "MVP da birorta yo'l ishlatilmaydi — qaror qabul qilinmagan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5 · KREDENSIAL CHEKLOVI — `/P` TAQIQI
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_P_kalitining_TAQIQINI_ochiq_yozadi(matritsa):
    """⚠️ Bu hujjatning eng muhim bitta gapi: parol buyruq satrida qolmaydi."""
    bolim = _bolim(matritsa, "## KREDENSIAL CHEKLOVI")
    assert "`/P<parol>`" in bolim, "`/P<parol>` kaliti ANIQ nomlanmagan"
    assert "TAQIQ" in bolim, "taqiq ochiq yozilmagan"


def test_matritsa_P_taqiqining_SABABINI_yozadi(matritsa):
    """⚠️ Sabab yozilmasa, keyingi agent taqiqni «ortiqcha qattiqlik» deb olib tashlaydi."""
    bolim = _bolim(matritsa, "## KREDENSIAL CHEKLOVI").lower()
    assert "jarayon ro'yxatida" in bolim, "sabab (jarayon ro'yxatida ko'rinishi) yozilmagan"
    assert "ochiq matnli kredensial" in bolim, "brief taqig'iga bog'lanmagan"


def test_matritsa_AUTH_kerak_bolsa_FALLBACK_ga_otadi(matritsa):
    """Auth talab qilinsa `FAILED_AUTH_REQUIRED` + `watch_folder` taklifi."""
    bolim = _bolim(matritsa, "## KREDENSIAL CHEKLOVI")
    assert "FAILED_AUTH_REQUIRED" in bolim, "auth yiqilish holati yozilmagan"
    assert "watch_folder" in bolim, "auth yiqilganda FALLBACK taklifi yozilmagan"


def test_matritsa_UNKNOWN_auth_ni_ham_TOXTATADI(matritsa):
    """⚠️ Fail-closed: `requires_auth` = `unknown` ruxsatga AYLANMAYDI. Bu loyihaning
    `fail-open-defaults` qoidasi, va kredensial yo'lida u eng muhim."""
    bolim = _bolim(matritsa, "## KREDENSIAL CHEKLOVI")
    assert "fail-closed" in bolim.lower(), "fail-closed qoidasi yozilmagan"
    assert re.search(r"`\"?unknown\"?`", bolim), "`unknown` holati ko'rib chiqilmagan"


def test_matritsa_KREDENSIAL_SAQLANMASLIGINI_yozadi(matritsa):
    bolim = _bolim(matritsa, "## KREDENSIAL CHEKLOVI")
    assert "`redact`" in bolim, "`locator` ning `redact` dan o'tishi yozilmagan"
    assert "agent_status.json" in bolim and "environment.json" in bolim, \
        "qaysi chiqish fayllariga kredensial YOZILMASLIGI aytilmagan"


def test_matritsa_redact_ROSTDAN_mavjud():
    """⚠️ Hujjat chaqirgan tozalagich ROSTDAN bor: havola eskirmasin."""
    from app.services.discovery_1c import redact
    assert callable(redact.redact), "`redact.redact` chaqiriladigan emas"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6 · PRIMARY / FALLBACK QARORI
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def qaror(matritsa) -> str:
    return _bolim(matritsa, "## PRIMARY va FALLBACK QARORI")


def test_matritsa_QAROR_bolimi_mavjud(qaror):
    assert len(qaror) > 400, "PRIMARY/FALLBACK qarori bo'limi juda qisqa"


@pytest.mark.parametrize("marshrut", MARSHRUTLAR)
def test_matritsa_QARORDA_marshrut_nomi_AYNAN_shartnomadek(qaror, marshrut):
    """⚠️ Phase 4 darsi: kalit nomi hujjatda boshqacha yozilsa, kod boshqa nom bilan
    yoziladi va paket rad etiladi. Shu bois `route` qiymatlari AYNAN tekshiriladi."""
    assert f"`{marshrut}`" in qaror, f"qarorda `{marshrut}` nomi aynan yozilmagan"


def test_matritsa_PRIMARY_va_FALLBACK_ni_AJRATADI(qaror):
    assert re.search(r"\*\*PRIMARY — `batch_execute`\*\*", qaror), \
        "PRIMARY marshruti aniq belgilanmagan"
    assert re.search(r"\*\*FALLBACK — `watch_folder`\*\*", qaror), \
        "FALLBACK marshruti aniq belgilanmagan"


def test_matritsa_QARORDA_PREFLIGHT_darvozasi_bor(qaror):
    """⚠️ «PRIMARY» qarori darvozasiz bo'lsa, agent yo'lni SINAB ko'radi va jimgina
    yiqiladi. Har bir shart uchun ANIQ yiqilish holati yozilishi kerak."""
    assert "preflight" in qaror.lower(), "preflight darvozasi yozilmagan"
    holatlar = set(re.findall(r"FAILED_[A-Z_]+", qaror))
    assert len(holatlar) >= 5, f"preflight juda yumshoq: faqat {sorted(holatlar)}"


def test_matritsa_FAQAT_shartnoma_holatlarini_ishlatadi(matritsa):
    """⚠️ Hujjat YANGI holat o'ylab chiqarmaydi: `states.py` ni boshqa agent yozadi va
    nom talashuvi Phase 4 nuqsonining aynan o'zi bo'lardi."""
    uchraganlar = set(re.findall(r"\b(?:FAILED|ABORTED)_[A-Z_]+\b", matritsa))
    begona = uchraganlar - SHARTNOMA_HOLATLARI
    assert not begona, f"shartnomada yo'q holat nomlari: {sorted(begona)}"


def test_matritsa_IKKI_yol_BITTA_workflow_ekanini_aytadi(qaror):
    """Operator uchun farq ko'rinmaydi: UI faqat «Start Discovery» ko'rsatadi."""
    assert "Start Discovery" in qaror, "bitta workflow talabi yozilmagan"
    assert "`route`" in qaror, "tanlangan yo'l `route` maydonida qayd etilishi yozilmagan"


def test_matritsa_ETIROZ_bolimi_mavjud_va_MANTIQI_bor(matritsa):
    """⚠️ Brief e'tirozni ATAYLAB so'radi. E'tiroz bo'lsa — u BSL bo'shlig'iga
    tayanishi kerak, «menga yoqmadi» ga emas."""
    bolim = _bolim(matritsa, "## E'TIROZ")
    assert len(bolim) > 300, "e'tiroz bo'limi juda qisqa"
    assert "BSL" in bolim, "e'tiroz BSL bo'shlig'iga bog'lanmagan"
    assert "watch_folder" in bolim, "e'tirozda MVP da haqiqatda bajariladigan yo'l yozilmagan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7 · BSL BO'SHLIG'I — MANBADAN O'LCHANADI
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def bsl_matni() -> str:
    return _matn(BSL)


def test_matritsa_BSL_boshligini_ALOHIDA_bolimda_yozadi(matritsa):
    bolim = _bolim(matritsa, "## BSL BO'SHLIG'I")
    assert "ПараметрЗапуска" in bolim, "`ПараметрЗапуска` mexanizmi nomlanmagan"
    assert "/C" in bolim, "paketli rejimda parametr uzatish kaliti yozilmagan"
    assert "ВыполнитьРазведку" in bolim, "kirish nuqtasi nomlanmagan"


def test_BSL_da_ParametrZapuska_ROSTDAN_YOQ(bsl_matni):
    """⚠️ Hujjatning asosiy fakti MANBADAN o'lchanadi: agar kimdir BSL ga
    `ПараметрЗапуска` o'quvchisini qo'shsa, bu test qizil bo'ladi va hujjat
    (bo'shliq yopilgani) yangilanishi kerak bo'ladi."""
    assert "ПараметрЗапуска" not in bsl_matni, \
        "BSL da `ПараметрЗапуска` paydo bo'lgan — bo'shliq yopilgan, matritsa eskirdi"


def test_BSL_da_AYNAN_IKKI_eksport_kirish_nuqtasi_bor(bsl_matni):
    """⚠️ Ikkovi ham ARGUMENT talab qiladi — paketli rejimda chiqish papkasini
    beradigan argumentsiz kirish nuqtasi YO'Q."""
    eksportlar = re.findall(r"^Функция (\w+)\(([^)]*)\) Экспорт", bsl_matni, re.M)
    assert [n for n, _ in eksportlar] == ["ВыполнитьРазведку", "ВыполнитьЗонд"], \
        f"eksport kirish nuqtalari o'zgargan: {eksportlar}"
    for nom, argumentlar in eksportlar:
        assert argumentlar.strip(), f"{nom}: argumentsiz bo'lib qolgan — matritsa eskirdi"


def test_matritsa_BSL_ni_OZGARTIRMASLIGINI_ochiq_aytadi(matritsa):
    """⚠️ Yig'uvchi manbasi boshqa agentning ishi: bu hujjat faqat bo'shliqni QAYD etadi."""
    bolim = _bolim(matritsa, "## BSL BO'SHLIG'I")
    assert "BSL NI O'ZGARTIRMAYDI" in bolim, "BSL ga tegilmasligi ochiq yozilmagan"


def test_matritsa_epf_YOQLIGINI_qayd_etadi(matritsa):
    """⚠️ Ikkinchi mustaqil blokirovka: `.epf` konteyneri repoda YO'Q."""
    assert re.search(r"`\.epf`[^|\n]*YO'Q", matritsa), "`.epf` yo'qligi qayd etilmagan"


def test_epf_konteyneri_ROSTDAN_repoda_YOQ():
    """⚠️ Fakt o'lchanadi, ishonilmaydi: `.epf` paydo bo'lsa matritsa eskiradi."""
    topildi = [p for p in (_REPO / "integrations").rglob("*.epf")]
    assert not topildi, f"`.epf` paydo bo'lgan: {topildi} — matritsani yangilash kerak"


def test_matritsa_AGENT_boshligni_ANIQLAY_olmasligini_yozadi(matritsa):
    """⚠️ QOBILIYAT CHEGARASI: agent `.epf` ichini o'qiy olmaydi, bo'shliq faqat
    NATIJASI bilan ko'rinadi (bo'sh papka → `FAILED_COLLECTOR_UNAVAILABLE`)."""
    bolim = _bolim(matritsa, "## BSL BO'SHLIG'I")
    assert "FAILED_COLLECTOR_UNAVAILABLE" in bolim, \
        "bo'shliqning agentga qanday ko'rinishi yozilmagan"
    assert "QOBILIYAT CHEGARASI" in bolim, "qobiliyat chegarasi ochiq nomlanmagan"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8 · UCHTA BINAR (2-JADVAL)
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_matritsa_UCHTA_binarni_ajratib_baholaydi(jadval2):
    assert len(jadval2) == 3, f"2-jadvalda {len(jadval2)} qator, uchta bo'lishi SHART"
    nomlar = " ".join(q[1] for q in jadval2)
    for binar in ("1cv8.exe", "1cestart.exe", "ibcmd.exe"):
        assert binar in nomlar, f"2-jadvalda `{binar}` baholanmagan"


def test_matritsa_UCHTA_binar_ham_RUNTIME_UNKNOWN(jadval2):
    """⚠️ Birorta binar bu mashinada YO'Q, demak uchovi ham `RUNTIME-UNKNOWN`."""
    for q in jadval2:
        assert _holat(q[4]) == "RUNTIME-UNKNOWN", \
            f"{q[0]}-binar holati {q[4]!r}, `RUNTIME-UNKNOWN` bo'lishi SHART"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9 · ISBOTLANMAGAN DA'VO YO'Q
# ══════════════════════════════════════════════════════════════════════════════════════════
#: ⚠️ TAQIQLANGAN IBORALAR. Hech biri isbotlanmagan: bu mashinada 1C:Enterprise YO'Q.
#: Ro'yxat ANIQ iboralardan iborat, bitta so'zdan emas — halol texnik atama yolg'on
#: ijobiy bermasligi kerak.
TAQIQLANGAN_DAVOLAR: tuple[str, ...] = (
    "ishlaydi",
    "ishlab turadi",
    "ishlamaydi",
    "kompilyatsiya qilinadi",
    "kompilyatsiya qilingan",
    "runtime tasdiqlangan",
    "runtime tekshirilgan",
    "production tayyor",
    "ishlashi tasdiqlangan",
    "ishlashi kafolatlangan",
    "sinovdan o'tgan",
    "sinalgan va",
    "com ishlaydi",
)


@pytest.mark.parametrize("davo", TAQIQLANGAN_DAVOLAR)
def test_matritsada_ISBOTLANMAGAN_davo_YOQ(matritsa, davo):
    """⚠️ `ishlamaydi` ham TAQIQLANGAN: inkor da'vosi ham dalil talab qiladi. To'g'ri
    ibora — «tekshirib bo'lmaydi»."""
    assert davo not in matritsa.lower(), \
        f"isbotlanmagan da'vo — «{davo}». To'g'ri holat: `RUNTIME-UNKNOWN`"


def test_matritsa_1C_YOQLIGINI_ochiq_aytadi(matritsa):
    assert "1C:Enterprise" in matritsa and "YO'Q" in matritsa, \
        "bu mashinada 1C yo'qligi ochiq yozilmagan"


@pytest.mark.parametrize("olchov", ["1cv8.exe", "V83.COMConnector", "pywin32",
                                    "HKLM\\SOFTWARE\\1C\\1Cv8"])
def test_matritsa_OLCHANGAN_holatni_SANAYDI(matritsa, olchov):
    """⚠️ «1C yo'q» degan umumiy gap yetarli emas: NIMA o'lchangani sanalishi kerak,
    aks holda keyingi agent qaytib o'lchaydi yoki taxmin qiladi."""
    assert olchov in matritsa, f"o'lchangan holatda «{olchov}» qayd etilmagan"


def test_matritsa_NIMA_SINALMAGANINI_alohida_bolimda_sanaydi(matritsa):
    """⚠️ Brief talabi: nima SINALMAGANI ochiq yozilsin. Shu jumladan 1C aniqlash
    kodining FAQAT SINTETIK fikstura bilan sinalishi."""
    bolim = _bolim(matritsa, "## NIMA SINALMAGAN")
    assert "SINTETIK" in bolim.upper(), \
        "1C aniqlash kodining faqat sintetik fikstura bilan sinalishi yozilmagan"
    assert "Konfigurator" in bolim, "`.epf` sintaksisi sinalmaganligi yozilmagan"


def test_matritsa_HECH_QAYERDA_tarmoq_yoki_cloud_taklif_QILMAYDI(matritsa):
    """⚠️ Offline-first: matritsa birorta yo'lda tarmoq chaqiruvi yoki cloud AI
    taklif qilmasligi kerak."""
    past = matritsa.lower()
    for taqiq in ("requests.", "urllib", "http.client", "cloud ai", "openai"):
        assert taqiq not in past, f"matritsa tarmoq/cloud yo'lini eslatgan: «{taqiq}»"
