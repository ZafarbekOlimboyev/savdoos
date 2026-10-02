# -*- coding: utf-8 -*-
"""Yig'uvchi KO'PRIK QATLAMI manbasining darvozasi — 1C runtime'isiz bajariladigan tekshiruv.

⚠️ NIMANI ISBOTLAYDI:
   · ko'prik fragmenti MAVJUD 38 qoidali statik auditdan 0 topilma bilan o'tadi;
   · fragmentda begona alifbo harfi, yopilmagan satr literali va buzilgan blok
     muvozanati YO'Q (`runtime_audit` ning uch tekshiruvi);
   · fragment nomlari muzlatilgan ekstraktor nomlari bilan TO'QNASHMAYDI — bir modulga
     qo'shilganda kompilyatsiyani yiqitadigan yagona narsa aynan shu;
   · protokol kalitlari (`request`/`response`/`done`) manbada AYNAN yozilgan;
   · mavjud yig'uvchining IKKI kardinallik so'rovi OSHKOR qilingan va ular biznes
     ustunini tanlamaydi.

⚠️ NIMANI ISBOTLAMAYDI: fragment kompilyatsiya bo'lishini, 1C'da yurishini yoki to'g'ri
   javob berishini. Bu mashinada 1C:Enterprise YO'Q va `.epf` YIG'ILMAGAN —
   holat `EPF_SOURCE_READY`. Kompilyatsiya mijozning 1C mutaxassisi zimmasida.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from app.services.discovery_1c import runtime_audit
from app.services.discovery_1c.epf_audit import QUERY_CONCAT_ALLOWED, RULES, audit_source

_1C = pathlib.Path(__file__).resolve().parents[3] / "integrations" / "1c"

#: Muzlatilgan Phase 4 yig'uvchisi — bu test unga TEGMAYDI, faqat o'qiydi.
EXTRACTOR_SRC = _1C / "extractor" / "BinOSDiscovery.bsl"

#: Yangi ko'prik qatlami.
COLLECTOR_DIR = _1C / "collector"
BRIDGE_SRC = COLLECTOR_DIR / "BinOSDiscoveryCollector.bsl"
BRIDGE_VERSION = COLLECTOR_DIR / "VERSION.json"
BRIDGE_BUILD = COLLECTOR_DIR / "BUILD.md"
HANDOFF = _1C / "REAL_1C_HANDOFF.md"

#: ⚠️ MUZLATISH PINI. Ekstraktor manbasi Phase 4 da muzlatilgan va bu bosqichda unga
#: BIR BELGI ham qo'shilmaydi. Pin SATR OXIRI NORMALLASHTIRILGAN matndan olinadi
#: (`read_text` universal newline bilan o'qiydi): aks holda Windows checkout'dagi CRLF
#: pinni buzardi va test o'zgarishga ALOQASI YO'Q sabab bilan qizil bo'lardi.
EXTRACTOR_LINES = 2531
EXTRACTOR_SHA256 = "3e5f88508e25ae87516898b1f6a0c66e686c98be30a5b56ca111d19370904208"


def _matn(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _kod_satrlari(text: str) -> list[str]:
    """Izoh va satr literali OLIB TASHLANGAN satrlar (`runtime_audit` qoidasi bilan)."""
    return runtime_audit.code_lines(text)


# ── 1. FAYLLAR MAVJUD ─────────────────────────────────────────────────────────────────────
def test_koprik_loyihasining_UCH_fayli_REPODA_mavjud():
    for yol in (BRIDGE_SRC, BRIDGE_VERSION, BRIDGE_BUILD):
        assert yol.is_file(), f"ko'prik loyihasining fayli topilmadi: {yol}"


def test_handoff_hujjati_REPODA_mavjud():
    assert HANDOFF.is_file(), f"handoff hujjati topilmadi: {HANDOFF}"


# ── 2. MUZLATILGAN EKSTRAKTOR TEGILMAGAN ──────────────────────────────────────────────────
def test_muzlatilgan_EKSTRAKTOR_manbasi_TEGILMAGAN():
    """⚠️ Phase 4 manbasi 0 diff bo'lib qolishi SHART.

    Ko'prik qatlami yig'uvchiga BIRORTA qobiliyat qo'shmaydi, demak uning manbasini
    o'zgartirishga sabab ham yo'q. Agar kimdir ko'prikni ishlatish uchun ekstraktorni
    «bir oz» tuzatsa, 38 qoidali audit bilan qulflangan kafolatlar qayta ko'rikdan
    o'tmasdan o'zgargan bo'lardi."""
    matn = _matn(EXTRACTOR_SRC)
    assert len(matn.splitlines()) == EXTRACTOR_LINES
    assert hashlib.sha256(matn.encode("utf-8")).hexdigest() == EXTRACTOR_SHA256, (
        "muzlatilgan yig'uvchi manbasi O'ZGARGAN — bu bosqichda unga tegilmaydi")


# ── 3. STATIK AUDIT (38 QOIDA) ────────────────────────────────────────────────────────────
def test_audit_qoidalari_soni_QULFLANGAN():
    """Hujjatlarda «38 qoida» deb yozilgan — son manbadan ajralib ketmasin."""
    assert len(RULES) == 38


def test_koprik_manbasi_STATIK_AUDITDAN_otadi():
    """⚠️ ENG MUHIM DARVOZA: yangi manbada taqiqlangan chaqiruv BO'LMASLIGI.

    Ko'prik 1C ICHIDA to'liq huquq bilan ishlaydi, demak «faqat o'qiydi» kafolatini
    tekshiradigan yagona joy — MANBA MATNI."""
    findings = audit_source(_matn(BRIDGE_SRC))
    assert not findings, "ko'prik manbasida taqiqlangan chaqiruv bor:\n" + "\n".join(
        f"  {f.code} satr {f.line_no}: {f.line}  ({f.why})" for f in findings)


def test_koprik_manbasi_OZINI_SINALMAGAN_deb_belgilaydi():
    """Audit majburlagan belgilardan tashqari holat nomi AYNAN yozilishi kerak."""
    matn = _matn(BRIDGE_SRC)
    assert "RUNTIME'DA SINALMAGAN" in matn
    assert "FAQAT AJRATILGAN NUSXADA" in matn
    assert "EPF_SOURCE_READY" in matn, "holat nomi AYNAN `EPF_SOURCE_READY` bo'lishi kerak"


# ── 4. RUNTIME AUDIT: UCH MATN FAKTI ──────────────────────────────────────────────────────
def _known(topilmalar) -> list[runtime_audit.Finding]:
    return [f for f in topilmalar if f.status == runtime_audit.STATUS_KNOWN]


def test_koprik_manbasida_BEGONA_ALIFBO_HARFI_YOQ():
    """⚠️ Bu XAVFSIZLIK emas, ISHLAYDIGANLIK darvozasi.

    Ekstraktorda topilgan nuqson aynan shu edi: funksiya nomidagi qozoq/o'zbek kirill
    harfi (`Қ` U+049A) kompilyatsiyani yiqitadi, lekin ko'z bilan farq qilinmaydi."""
    topilmalar = _known(runtime_audit.check_identifier_charset(_matn(BRIDGE_SRC)))
    assert not topilmalar, "\n".join(f"  {f.code} satr {f.line_no}: {f.why}"
                                    for f in topilmalar)


def test_koprik_manbasida_YOPILMAGAN_LITERAL_YOQ():
    """⚠️ Yopilmagan literal IKKI zarar keltiradi: modul kompilyatsiya bo'lmaydi VA
    begona harf darvozasi KO'R bo'lib qoladi (qolgan satrlar «literal» deb belgilanadi).
    Shu bois yo'l ajratuvchisi `Символ(92)` bilan yoziladi, `"\\"` literali bilan emas."""
    topilmalar = _known(runtime_audit.literal_defects(_matn(BRIDGE_SRC)))
    assert not topilmalar, "\n".join(f"  {f.code} satr {f.line_no}: {f.why}"
                                    for f in topilmalar)


def test_koprik_manbasida_BLOK_MUVOZANATI_buzilmagan():
    """⚠️ Muvozanat sintaksisning ZARURIY sharti, YETARLI sharti EMAS."""
    topilmalar = _known(runtime_audit.check_balanced_blocks(_matn(BRIDGE_SRC)))
    assert not topilmalar, "\n".join(f"  {f.code} {f.line}: {f.why}" for f in topilmalar)


#: ⚠️ `runtime_audit` ning QOLGAN tekshiruvlari EKSTRAKTORGA moslangan: ular
#: `export.json`/`metadata.json` shartnomasini, ixtiyoriy metadata OILALARINI va sanoq
#: maydonlarini qidiradi. Ko'prik qatlami metadata KEZMAYDI, demak bu topilmalar
#: «nuqson» emas, QO'LLANMAYDIGAN tekshiruv. Ro'yxat ATAYLAB QULFLANGAN: yangi KNOWN
#: topilma paydo bo'lsa to'plam qizil bo'ladi va hech narsa jimgina o'tib ketmaydi.
KUTILGAN_QOLGAN_KNOWN: dict[str, int] = {
    # Ixtiyoriy metadata oilalari ko'prikda ESLANMAYDI, chunki ko'prik birorta
    # kolleksiyani kezmaydi — oilalarni ekstraktor o'qiydi va u O'Z testi bilan
    # qulflangan (`test_discovery_1c_runtime_audit.py`).
    "OPTIONAL_FAMILY_UNMENTIONED": 4,
}


def test_runtime_auditning_QOLGAN_KNOWN_topilmalari_QULFLANGAN():
    sanoq: dict[str, int] = {}
    for f in _known(runtime_audit.audit_source(_matn(BRIDGE_SRC))):
        sanoq[f.code] = sanoq.get(f.code, 0) + 1
    assert sanoq == KUTILGAN_QOLGAN_KNOWN, (
        "ko'prik manbasidagi KNOWN topilmalar ro'yxati o'zgardi — yangi topilma "
        f"ko'rikdan o'tishi kerak: {sanoq}")


# ── 5. FRAGMENT SHARTLARI: BIR MODULGA QO'SHILADI ─────────────────────────────────────────
_ELON = re.compile(r"^\s*(?:Процедура|Функция)\s+([А-Яа-яЁёA-Za-z0-9_]+)\s*\(")
_PEREM = re.compile(r"^\s*Перем(?![А-Яа-яЁёA-Za-z0-9_])")


def _elon_qilingan_nomlar(text: str) -> set[str]:
    nomlar: set[str] = set()
    for satr in _kod_satrlari(text):
        m = _ELON.match(satr)
        if m:
            nomlar.add(m.group(1))
    return nomlar


def test_fragment_MODUL_OZGARUVCHISI_elon_QILMAYDI():
    """⚠️ 1C `Перем` ni BIRINCHI protseduradan OLDIN talab qiladi.

    Ko'prik matni modulning OXIRIGA qo'shiladi (`BUILD.md`), demak u modul
    o'zgaruvchisi e'lon qilsa kompilyatsiya yiqilardi. Butun holat mahalliy
    o'zgaruvchilarda va parametrlarda yuradi."""
    buzuvchi = [satr for satr in _kod_satrlari(_matn(BRIDGE_SRC)) if _PEREM.match(satr)]
    assert not buzuvchi, f"fragmentda modul o'zgaruvchisi e'lon qilingan: {buzuvchi}"


def test_fragment_nomlari_EKSTRAKTOR_nomlari_bilan_TOQNASHMAYDI():
    """⚠️ IKKI MANBA BIR MODULDA YASHAYDI, ya'ni bir xil nom kompilyatsiyani yiqitadi.

    Bu testning butun ma'nosi shu: nom to'qnashuvi diffda zararsiz ko'rinadi va faqat
    Designer'da — ya'ni bizdan uzoqda — ko'rinardi."""
    ekstraktor = _elon_qilingan_nomlar(_matn(EXTRACTOR_SRC))
    koprik = _elon_qilingan_nomlar(_matn(BRIDGE_SRC))
    assert koprik, "ko'prik fragmentida birorta protsedura/funksiya topilmadi"
    assert not (ekstraktor & koprik), (
        f"bir modulda takrorlanadigan nom: {sorted(ekstraktor & koprik)}")


def test_fragment_nomlari_MOST_prefiksi_bilan_boshlanadi():
    """⚠️ Prefiks QOIDA, uslub emas: u to'qnashuvni oldini oladi.

    Yagona istisno — EKSPORT kirish nuqtasi: uning nomi operator va hujjat uchun
    o'qiladigan bo'lishi kerak."""
    kirish = "ВыполнитьМостРазведки"
    for nom in _elon_qilingan_nomlar(_matn(BRIDGE_SRC)):
        if nom == kirish:
            continue
        assert nom.startswith("Мост"), f"prefikssiz nom: {nom}"


# ── 6. KIRISH NUQTASI ARGUMENTSIZ ─────────────────────────────────────────────────────────
def test_kirish_nuqtasi_ARGUMENTSIZ_va_EKSPORT():
    """⚠️ CP1 DA ANIQLANGAN BO'SHLIQ AYNAN ARGUMENTLI KIRISH NUQTASI EDI.

    Agent buyruq satriga qiymat qo'shardi, modulda esa uni o'qiydigan joy yo'q edi va
    natija JIMGINA bo'sh papka bo'lardi. Endi so'rov FAYLDAN keladi."""
    kod = _kod_satrlari(_matn(BRIDGE_SRC))
    kirishlar = [satr.strip() for satr in kod
                 if re.match(r"^\s*Функция\s+ВыполнитьМостРазведки\s*\(", satr)]
    assert len(kirishlar) == 1, f"kirish nuqtasi AYNAN bitta bo'lishi kerak: {kirishlar}"
    assert re.match(r"^Функция\s+ВыполнитьМостРазведки\s*\(\s*\)\s*Экспорт\s*$",
                    kirishlar[0]), (
        f"kirish nuqtasi ARGUMENTSIZ va `Экспорт` bo'lishi kerak: {kirishlar[0]!r}")


def test_fragmentda_EKSPORT_yuzasi_FAQAT_bitta():
    """⚠️ Kichik yuza — kichik shartnoma. Ikkinchi eksport nuqtasi agent bilmagan
    yo'ldan chaqirilishi mumkin bo'lardi."""
    eksportlar = [satr.strip() for satr in _kod_satrlari(_matn(BRIDGE_SRC))
                  if re.search(r"(?<![А-Яа-яЁёA-Za-z0-9_])Экспорт\s*$", satr.rstrip())]
    assert len(eksportlar) == 1, f"eksport yuzasi bitta bo'lishi kerak: {eksportlar}"


def test_koprik_PARAMETRZAPUSKA_ni_OQIMAYDI():
    """⚠️ O'YLAB CHIQARILGAN BUYRUQ SATRI PARAMETRI QO'SHILMAYDI.

    Mavjud agent buyrug'idagi `/C<...>` bo'lagi ko'prik tomonidan e'tiborga olinmaydi;
    so'rov faqat `request.json` dan keladi."""
    matn = _matn(BRIDGE_SRC)
    assert "ПараметрЗапуска" not in "\n".join(_kod_satrlari(matn)), (
        "ko'prik ishga tushirish parametrini o'qiydi — kirish nuqtasi ARGUMENTSIZ "
        "bo'lishi kerak")
    assert "ПараметрЗапуска" in matn, (
        "nega o'qilmasligi manbada OCHIQ yozilishi kerak, aks holda keyingi odam uni "
        "«esdan chiqqan» deb qo'shib qo'yardi")


def test_koprik_SO_ROVNI_OZ_papkasidan_topadi():
    kod = "\n".join(_kod_satrlari(_matn(BRIDGE_SRC)))
    assert "ИспользуемоеИмяФайла" in kod, (
        "ko'prik o'z papkasini `.epf` faylining yo'lidan topishi kerak")
    assert "Новый Файл" in kod


# ── 7. PROTOKOL KALITLARI — PHASE 4 DARSI ─────────────────────────────────────────────────
#: ⚠️ KALIT NOMLARI KOD YOZILISHIDAN OLDIN BELGILANDI. Phase 4 da ikki tomon bo'shliqni
#: har xil to'ldirgan va to'plam yashil bo'lsa ham HAR BIR real paket rad etilgan. Shu
#: bois kalitlar bu yerda AYNAN qulflanadi — agent tomoni ham shu ro'yxatga qaraydi.
REQUEST_KEYS = ("request_version", "run_id", "nonce", "requested_at", "output_dir",
                "expected_collector", "target_fingerprint", "mode", "allowed_probes",
                "notes")
RESPONSE_KEYS = ("response_version", "run_id", "nonce", "collector", "target_fingerprint",
                 "status", "started_at", "finished_at", "notes")
# ⚠️⚠️ `done_version` ILGARI SHU YERDA TUSHIB QOLGANDI va konformans darvozasi
#      (`test_agent_bridge_conformance.test_TORTINCHI_NUSXA...`) shu driftni TUTDI:
#      `.bsl` va `bridge_protocol` to'rt kalitni biladi, bu NUSXA esa uchtasini —
#      ya'ni shartnomaning TO'RTINCHI nusxasi jimgina ajralib ketgandi.
# ⚠️ Nusxa ATAYLAB qoldirildi (bu test `bridge_protocol` dan MUSTAQIL bo'lishi kerak:
#    u `.bsl` manbasini tekshiradi, agent kodini emas), lekin u endi darvoza ostida —
#    ikki tomon ajralsa CI qizil bo'ladi.
DONE_KEYS = ("done_version", "run_id", "nonce", "written_at")

PROTOCOL_VERSIONS = ("binos-bridge-request-v1", "binos-bridge-response-v1",
                     "binos-bridge-done-v1")

FILE_NAMES = ("request.json", "response.json", "bridge_done.json")


def test_PROTOKOL_versiya_satrlari_AYNAN():
    matn = _matn(BRIDGE_SRC)
    for versiya in PROTOCOL_VERSIONS:
        assert f'"{versiya}"' in matn, f"shartnoma versiyasi manbada yo'q: {versiya}"


def test_PROTOKOL_fayl_nomlari_AYNAN():
    matn = _matn(BRIDGE_SRC)
    for nom in FILE_NAMES:
        assert f'"{nom}"' in matn, f"shartnoma fayl nomi manbada yo'q: {nom}"


def test_SOROVNING_har_maydoni_manbada_OQILADI():
    """⚠️ So'rovning HAMMA maydoni ishlatilishi shart: o'qilmaydigan maydon agentni
    «yubordim» deb, ko'prikni «olmadim» deb qoldirardi — Phase 4 ning aynan naqshi."""
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    for kalit in REQUEST_KEYS:
        assert f'"{kalit}"' in kod, f"so'rov maydoni manbada o'qilmaydi: {kalit}"


def test_JAVOBNING_har_maydoni_manbada_YOZILADI():
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    for kalit in RESPONSE_KEYS:
        assert re.search(rf'Ответ\.Вставить\(\s*"{kalit}"', kod), (
            f"javob maydoni yozilmaydi: {kalit}")


def test_TUGALLANISH_BELGISINING_har_maydoni_YOZILADI():
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    for kalit in DONE_KEYS:
        assert re.search(rf'Метка\.Вставить\(\s*"{kalit}"', kod), (
            f"tugallanish belgisining maydoni yozilmaydi: {kalit}")


def test_TUGALLANISH_BELGISI_JAVOBDAN_KEYIN_yoziladi():
    """⚠️ TARTIB SHARTNOMANING O'ZI: belgi «javob allaqachon diskda» degan MA'NONI
    bildiradi. Teskari tartib agentga to'liq bo'lmagan paketni to'liq deb ko'rsatardi."""
    kod = _kod_satrlari(_matn(BRIDGE_SRC))
    chaqiruvlar = [i for i, satr in enumerate(kod)
                   if "МостЗаписатьОтвет(" in satr or "МостЗаписатьМеткуЗавершения(" in satr]
    assert chaqiruvlar, "yozish chaqiruvlari topilmadi"
    # Har bir belgi chaqiruvidan OLDIN javob chaqiruvi turishi kerak.
    oxirgi_javob = -1
    for i in chaqiruvlar:
        if "МостЗаписатьОтвет(" in kod[i]:
            oxirgi_javob = i
        elif "МостЗаписатьМеткуЗавершения(" in kod[i]:
            assert 0 <= oxirgi_javob < i, (
                f"{i + 1}-satrda tugallanish belgisi javobdan OLDIN yoziladi")


def test_JAVOB_yozilmasa_BELGI_HAM_yozilmaydi():
    """⚠️ Yozish natijasi O'QILADI. Javob yozilmay, belgi yozilsa — agent javobsiz
    «tugadi» ni ko'rardi va bu JIMGINA noto'g'ri xulosa bo'lardi."""
    kod = _kod_satrlari(_matn(BRIDGE_SRC))
    for i, satr in enumerate(kod):
        if "МостЗаписатьМеткуЗавершения(" not in satr:
            continue
        if re.match(r"^\s*(?:Функция|Возврат)", satr):
            continue                      # e'lon yoki yordamchi qaytarishi
        atrof = "\n".join(kod[max(0, i - 4):i + 1])
        assert "Если МостЗаписатьОтвет(" in atrof, (
            f"{i + 1}-satrda belgi javob natijasini TEKSHIRMASDAN yoziladi")


def test_NOTES_MATNLAR_MASSIVI_bolib_yoziladi():
    """⚠️ Agent tomonidagi darvoza `notes` ni AYNAN ro'yxat deb kutadi.

    Bitta satrga qo'shish ikki zarar keltirardi: hujjat SHAKL bo'yicha rad etilardi va
    kodlarni qayta ajratib bo'lmas edi. Shu bois `СтрСоединить` bu manbada UMUMAN
    ishlatilmaydi — qo'shish yo'li yopiq."""
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    assert re.search(r'Ответ\.Вставить\(\s*"notes",\s*МостЗаметки\s*\)', kod), (
        "`notes` massiv o'zgaruvchisidan yozilishi kerak")
    assert "СтрСоединить" not in kod, (
        "`notes` qo'shilgan satrga aylantirilgan — agent uni ro'yxat deb kutadi")


def test_NOTES_ga_FAQAT_KOD_tushadi_XOM_XATO_MATNI_YOQ():
    """⚠️ XOM 1C XATO MATNI PROTOKOLGA YOZILMAYDI.

    `ОписаниеОшибки()` fayl yo'lini o'z ichiga olishi mumkin, agent tomonidagi `notes`
    darvozasi esa shubhali qiymat ko'rsa BUTUN hujjatni rad etadi — ya'ni xato matnini
    yozish nuqson sababini yo'qotib, ustiga yana bitta nuqson qo'shardi.
    Matn operatorga ko'rsatiladi (`Сообщить`), protokolga esa faqat KOD tushadi."""
    kod = runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False)
    chaqiruvlar = re.findall(r"МостЗаметка\(\s*МостЗаметки\s*,\s*([^)]*)\)", "\n".join(kod))
    assert chaqiruvlar, "`МостЗаметка` chaqiruvlari topilmadi"
    for arg in chaqiruvlar:
        arg = arg.strip()
        assert "+" not in arg, f"`notes` ga qo'shilgan matn uzatiladi: {arg!r}"
        assert "ОписаниеОшибки" not in arg, f"xom xato matni `notes` ga tushadi: {arg!r}"
        assert re.fullmatch(r'"[A-Z][A-Z0-9_]*"|[А-Яа-яЁёA-Za-z0-9_]+', arg), (
            f"`notes` ga faqat KOD yoki kod o'zgaruvchisi uzatilishi kerak: {arg!r}")
    # `ОписаниеОшибки()` FAQAT operatorga ko'rsatiladi.
    for satr in kod:
        if "ОписаниеОшибки" in satr:
            assert "Сообщить(" in satr, (
                f"xato matni operatorga ko'rsatishdan boshqa yo'lga ketadi: {satr.strip()!r}")


def test_KIMLIK_SHAKLI_HAMMA_YOZISHDAN_OLDIN_tekshiriladi():
    """⚠️ Buzuq kimlik bilan yozilgan javobni agent UMUMAN ajratib o'qiy olmaydi.

    Shunday holatda jimlik yaxshiroq: agent javob YO'Qligini aniq ko'radi. Shu bois
    tekshiruv BIRORTA yozishdan oldin turishi shart va bu test tartibni qulflaydi."""
    kod = runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False)
    tekshiruv = [i for i, s in enumerate(kod) if "МостПроверитьКимлик(МостЗапрос)" in s]
    yozishlar = [i for i, s in enumerate(kod)
                 if re.search(r"(?:Если\s+)?Мост(?:ЗаписатьОтвет|ЗаписатьМеткуЗавершения)\(", s)
                 and not re.match(r"^\s*(?:Функция|Процедура)", s)]
    assert len(tekshiruv) == 1, f"kimlik tekshiruvi AYNAN bir marta chaqirilsin: {tekshiruv}"
    assert yozishlar, "yozish chaqiruvlari topilmadi"
    assert tekshiruv[0] < min(yozishlar), (
        "kimlik shakli BIRINCHI yozishdan keyin tekshiriladi — tartib buzilgan")


def test_KIMLIK_tekshiruvi_UCHALA_maydonni_KORADI():
    """⚠️ Tekshiruvni `""` ga almashtirish (yoki maydonni tushirib qoldirish) darvozani
    JIMGINA o'chirardi: hamma narsa yashil, lekin har bir real javob agent tomonida
    `BRIDGE_SHAPE_INVALID` bo'lib qaytardi."""
    matn = _matn(BRIDGE_SRC)
    boshi = matn.find("Функция МостПроверитьКимлик(")
    assert boshi > 0, "kimlik tekshiruvi funksiyasi topilmadi"
    tana = matn[boshi:matn.find("КонецФункции", boshi)]
    for maydon, kod in (("run_id", "RUN_ID_MALFORMED"),
                        ("nonce", "NONCE_MALFORMED"),
                        ("target_fingerprint", "FINGERPRINT_MALFORMED")):
        assert f'"{maydon}"' in tana, f"kimlik maydoni tekshirilmaydi: {maydon}"
        assert f'"{kod}"' in tana, f"sabab kodi yo'q: {kod}"
    assert "МостМинимумNonce()" in tana and "МостМаксимумNonce()" in tana
    assert "МостДлинаОтпечатка()" in tana


def test_HEX_tekshiruvi_FAQAT_KICHIK_harfni_qabul_qiladi():
    """⚠️ Agent darvozasi aynan `[0-9a-f]` ni kutadi.

    Ko'prik bosh harfli hex'ni QABUL QILSA, nuqson yig'ish TUGAGANDAN keyin ko'rinardi:
    operator «yig'ish tugadi, lekin BinOS qabul qilmadi» degan tushunarsiz holatga
    tushardi. Shu bois chegaralar ikki tomonda AYNAN bir xil."""
    matn = _matn(BRIDGE_SRC)
    boshi = matn.find("Функция МостHexСтрока(")
    assert boshi > 0
    tana = matn[boshi:matn.find("КонецФункции", boshi)]
    ruxsat = re.search(r'Разрешенные\s*=\s*"([^"]*)"', tana)
    assert ruxsat, "ruxsat etilgan belgilar ro'yxati topilmadi"
    assert ruxsat.group(1) == "0123456789abcdef", (
        f"hex alifbosi agent darvozasidan farq qiladi: {ruxsat.group(1)!r}")


def test_VERSION_json_MANBA_bilan_AYNAN_MOS():
    """⚠️ IKKI JOYDA IKKI XIL QIYMAT — Phase 4 da har bir real paketni rad etgan naqsh.

    Agent `expected_collector` ni shu nom va versiya bilan solishtiradi."""
    yozilgan = json.loads(_matn(BRIDGE_VERSION))
    assert set(yozilgan) == {"collector"}
    sborshchik = yozilgan["collector"]
    assert set(sborshchik) == {"name", "version"}
    matn = _matn(BRIDGE_SRC)
    assert f'"{sborshchik["name"]}"' in matn
    assert f'"{sborshchik["version"]}"' in matn
    assert sborshchik["version"].endswith("-source"), (
        "`.epf` yig'ilmagan — versiya buni ko'rsatishi kerak")


def test_HOLAT_lugati_YIGUVCHINING_lugatidan_olinadi():
    """⚠️ YANGI LUG'AT YASALMAYDI. `SUCCESS`/`PARTIAL`/`FAILED` — yig'uvchining o'z
    `overall` qiymatlari; ko'prik ustiga faqat BITTA qiymat qo'shadi."""
    matn = _matn(BRIDGE_SRC)
    ekstraktor = _matn(EXTRACTOR_SRC)
    for holat in ("SUCCESS", "PARTIAL", "FAILED"):
        assert f'"{holat}"' in matn
        assert f'"{holat}"' in ekstraktor, (
            f"`{holat}` yig'uvchining lug'atida yo'q — ko'prik o'ylab chiqargan bo'lardi")
    assert '"BRIDGE_REJECTED"' in matn


def test_KOPRIKNING_RAD_ETISH_qiymati_YIGUVCHI_lugati_bilan_TOQNASHMAYDI():
    """⚠️ TOPILGAN TO'QNASHUV. `REJECTED` yig'uvchida ALLAQACHON bor, lekin BOSHQA
    ma'noda: u `bundle/errors.json` ning `code` lug'atidagi qiymat
    (`WRITE_FAILED | PROBE_FAILED | REJECTED | UNHASHABLE`) va REJIM rad etilganini
    bildiradi, YURISH rad etilganini emas.

    Bir xil so'z ikki shartnomada — aynan `status.json` va `run_status.json` ni ajratishga
    majbur qilgan naqsh. Shu bois ko'prik qiymati o'z prefiksini oladi va bu test
    prefikssiz qiymat qaytib kelishiga yo'l qo'ymaydi."""
    ekstraktor = _matn(EXTRACTOR_SRC)
    assert '"REJECTED"' in ekstraktor, (
        "to'qnashuvning sababi yo'qolgan — bu test o'z ma'nosini qayta ko'rishi kerak")
    assert '"BRIDGE_REJECTED"' not in ekstraktor
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    assert '"REJECTED"' not in kod, (
        "ko'prikda prefikssiz `REJECTED` qiymati — yig'uvchining xato kodi bilan "
        "chalkashadi")


# ── 8. IKKINCHI DVIGATEL QURILMAGAN ───────────────────────────────────────────────────────
def test_koprik_MAVJUD_yiguvchini_CHAQIRADI():
    kod = "\n".join(_kod_satrlari(_matn(BRIDGE_SRC)))
    assert "ВыполнитьРазведку(" in kod, (
        "ko'prik mavjud yig'uvchini chaqirishi kerak, o'zi yig'maydi")


def test_koprik_METADATA_KEZMAYDI_va_SOROV_YUBORMAYDI():
    """⚠️ «Do not build a second discovery engine» — bu test shuni MATNDA qulflaydi.

    Ko'prikda birorta `Новый Запрос` va birorta `Метаданные` murojaati bo'lmasligi
    kerak: ikkinchi, sinalmagan metadata o'quvchisi aynan semantik dublikat bo'lardi."""
    kod = "\n".join(_kod_satrlari(_matn(BRIDGE_SRC)))
    assert "Новый Запрос" not in kod, "ko'prik so'rov quradi — bu yig'uvchining ishi"
    assert not re.search(r"(?<![А-Яа-яЁёA-Za-z0-9_])Метаданные\s*\.", kod), (
        "ko'prik metadata kezadi — bu yig'uvchining ishi")


def test_koprik_REJIMNI_QAYTA_NORMALLASHTIRMAYDI():
    """⚠️ Rejim qarori BIR joyda qoladi: yig'uvchining o'z fail-safe darvozasida.

    Ikkinchi normallashtirish ikki tomonni zid qilib qo'yardi."""
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    assert '"METADATA_ONLY"' not in kod, (
        "ko'prik rejim qiymatini o'zi hal qiladi — u faqat uzatishi kerak")
    assert '"APPROVED_PROBES"' not in kod
    assert 'МостПоле(МостЗапрос, "mode"' in kod, "rejim so'rovdan uzatilishi kerak"
    assert "DEFAULT REJIM: METADATA_ONLY" in _matn(BRIDGE_SRC), (
        "default rejim manbada OCHIQ yozilishi shart (statik audit ham talab qiladi)")


# ── 9. KREDENSIAL VA FAYL TIZIMI ──────────────────────────────────────────────────────────
def test_koprik_KREDENSIALGA_umuman_TEGMAYDI():
    """⚠️ Parol `argv`, jurnal, natija fayli va konfiguratsiyaga HECH QACHON tushmaydi.

    Ko'prik parolni bilmaydi: `locator` ham protokolda YO'Q, faqat uning XESHI."""
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    for taqiq in ("Пароль", "password", "ИмяПользователя", "/N", "/P",
                  "СтрокаСоединенияИнформационнойБазы", "locator"):
        assert taqiq not in kod, f"ko'prik kodida kredensial yuzasi: {taqiq}"


def test_koprik_KATALOG_YARATMAYDI_va_WILDCARD_OCHIRISH_YOQ():
    """⚠️ QAROR 4: agent FAQAT o'z yurish papkasini yaratadi, ko'prik esa UMUMAN
    yaratmaydi. Hech qanday `rmtree` naqshi va umumiy global natija fayli yo'q."""
    matn = _matn(BRIDGE_SRC)
    for taqiq in ("СоздатьКаталог", "УдалитьФайлы", "НайтиФайлы", "*.json", "*.*"):
        assert taqiq not in matn, f"fayl tizimi yuzasi kengaygan: {taqiq}"


def test_koprik_CHIQISHNI_OZ_yurish_papkasi_ICHIDA_ushlab_turadi():
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    assert '"OUTPUT_DIR_OUTSIDE_RUN"' in kod, (
        "buzilgan so'rov ko'prikni begona papkaga yozishga yo'llardi")
    assert '"RUN_DIR_NOT_EMPTY"' in kod, (
        "tugagan yurishning javobi ustiga yozilmasligi kerak")


def test_koprik_CHIQISHI_UTF8():
    """⚠️ QAROR 4: chiqish UTF-8. BOM bilan fayl Python tomonida buziladi.

    ⚠️ KODLASH HAR `ОткрытьФайл` DA ANIQ beriladi — o'qishda ham. Platformaning
    standartiga tashlab qo'yish do'kon mashinasining mahalliy kod sahifasida o'qilish
    xavfini kiritardi va buzilgan kalit nomi JIMGINA «maydon yo'q» bo'lib ko'rinardi."""
    kod = runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False)
    ochishlar = sum(1 for satr in kod if re.search(r"\.\s*ОткрытьФайл\s*\(", satr))
    assert ochishlar >= 3, f"fayl ochish chaqiruvlari topilmadi: {ochishlar}"
    assert "\n".join(kod).count('"UTF-8"') == ochishlar, (
        f"{ochishlar} ta `ОткрытьФайл` bor, lekin kodlash boshqa sonda berilgan")
    assert not _known(runtime_audit.check_json_writer_usage(_matn(BRIDGE_SRC))), (
        "JSON oqimi kodlash/BOM/`Закрыть()` shartlarini buzadi")


def test_koprik_JARAYON_OLDIRMAYDI():
    """⚠️ Bekor qilish KOOPERATIV: keng jarayon o'ldirish YO'Q."""
    matn = _matn(BRIDGE_SRC)
    for taqiq in ("taskkill", "ЗавершитьРаботуСистемы", "ЗапуститьПриложение"):
        assert taqiq not in matn, f"jarayonni to'xtatish yuzasi: {taqiq}"


# ── 10. READ_ONLY_CARDINALITY_PROBE — OSHKORLIK ───────────────────────────────────────────
#: ⚠️ BRIEF TALAB QILADI. Mavjud yig'uvchi IKKI `ВЫБРАТЬ КОЛИЧЕСТВО(*)` so'rovini bazaga
#: YUBORADI. Bu metadata o'qish EMAS: so'rov biznes jadvalining USTIDAN o'tadi. Shu bois
#: ikkisi ham bu yerda SANALADI va SHAKLI qulflanadi — «faqat metadata» degan yumshoq
#: ta'rif aynan shu ikki so'rovni ko'rinmas qilardi.
_COUNT_QUERY = re.compile(r'"\s*ВЫБРАТЬ\s+(?P<select>.+?)\s+ИЗ\s*"\s*\+\s*'
                          r'(?P<operand>[А-Яа-яЁёA-Za-z0-9_]+)')


def _kardinallik_sorovlari() -> list[re.Match[str]]:
    return list(_COUNT_QUERY.finditer(_matn(EXTRACTOR_SRC)))


def test_KARDINALLIK_sorovlari_AYNAN_IKKITA():
    """(a) so'rov soni AYNAN 2 — uchinchi so'rov ko'rikdan o'tmasdan kirib kelmaydi."""
    assert len(_kardinallik_sorovlari()) == 2
    # Yig'uvchida UMUMAN boshqa so'rov yo'qligi: har so'rov `Новый Запрос` bilan ochiladi.
    kod = "\n".join(_kod_satrlari(_matn(EXTRACTOR_SRC)))
    assert kod.count("Новый Запрос") == 2, (
        "yig'uvchida ikkitadan ortiq so'rov bor — oshkorlik ro'yxati to'liq emas")


def test_KARDINALLIK_sorovida_BIZNES_USTUNI_TANLANMAYDI():
    """(b) `ВЫБРАТЬ` dan keyin FAQAT `КОЛИЧЕСТВО(*)`.

    ⚠️ Birorta ustun nomi tanlanmaydi, demak so'rov birorta QATOR QIYMATINI qaytarmaydi:
    natija bitta son. Agar bu yerga ustun nomi kirsa, yig'uvchi biznes ma'lumotini
    chiqaradigan vositaga aylanardi."""
    for m in _kardinallik_sorovlari():
        select = m.group("select").strip()
        assert re.fullmatch(r"КОЛИЧЕСТВО\(\*\)(?:\s+КАК\s+[А-Яа-яЁёA-Za-z0-9_]+)?",
                            select), f"tanlangan ifoda sanoq emas: {select!r}"


def test_KARDINALLIK_jadval_nomi_METADATADAN_keladi():
    """(c) jadval nomi METADATA obyektidan keladi, kelgan matndan EMAS.

    ⚠️ IKKI SO'ROV IKKI XIL YO'L BILAN NOM OLADI va ikkisi ham qulflanadi:
       · `row_count` zondi — `ОбъектМД.ПолноеИмя()` ning qaytargani;
       · `counts` bo'limi — PLATFORMA prefiksi + kezilgan obyektning `.Имя` si.
    Ikkisi ham metadata kolleksiyasini kezishdan keladi; tashqaridan (model yoki
    operator bergan matndan) HECH BIRIGA qiymat tushmaydi."""
    matn = _matn(EXTRACTOR_SRC)
    operandlar = {m.group("operand") for m in _kardinallik_sorovlari()}
    # Audit oq ro'yxati bilan AYNAN bir xil bo'lishi shart.
    assert operandlar == set(QUERY_CONCAT_ALLOWED), (
        f"so'rovga qo'shilgan nom oq ro'yxatdan tashqarida: {operandlar}")
    # `row_count` zondi: nom `ПолноеИмя()` dan.
    assert "ПолноеИмяОбъекта = ПолноеИмяБезопасно(ОбъектМД, Ошибки);" in matn
    assert "Возврат ОбъектМД.ПолноеИмя();" in matn
    # `counts` bo'limi: nom PLATFORMA prefiksi va kezilgan obyekt nomidan.
    assert 'ПолноеИмя = Префикс + "." + ОбъектМД.Имя;' in matn


def test_KARDINALLIK_sorovi_TASHQI_ARGUMENTDAN_QURILMAYDI():
    """(d) so'rov matni tashqi argumentdan qurilmaydi.

    ⚠️ Haqiqiy himoya — statik audit darvozasi: `QUERY_TEXT_FROM_VARIABLE` so'rov
    matnini bo'sh bo'lmagan LITERAL bilan boshlanishini, `QUERY_TEXT_CONCAT_SOURCE`
    esa qo'shiladigan nomlarni OQ RO'YXAT bilan cheklashini majburlaydi. Bu test
    darvozaning YOQILGANIGA va yig'uvchining undan o'tishiga suyanadi."""
    qoidalar = {r.code for r in RULES}
    assert {"QUERY_TEXT_FROM_VARIABLE", "QUERY_TEXT_CONCAT_SOURCE"} <= qoidalar
    assert not audit_source(_matn(EXTRACTOR_SRC)), (
        "yig'uvchi o'z auditidan o'tmaydi — so'rov manbasi kafolati buzilgan")
    # Zondga kelgan NISHON matni so'rovga TUSHMAYDI: u metadata izlash uchun ishlatiladi.
    assert "ЦелевойОбъект" in _matn(EXTRACTOR_SRC)
    for m in _kardinallik_sorovlari():
        assert m.group("operand") != "ЦелевойОбъект"


def test_YIGUVCHI_ozini_FAQAT_METADATA_deb_ATAMAYDI():
    """⚠️ «faqat metadata» degan yumshoq ta'rif IKKI SANOQ SO'ROVINI ko'rinmas qilardi.

    Bu test MEN YOZGAN hujjat va manbalarda shunday da'vo YO'Qligini tekshiradi.
    Muzlatilgan yig'uvchi o'z matnini o'zi oshkor qiladi va u pastdagi testda
    qulflanadi — bu yerda unga tegilmaydi."""
    davolar = re.compile(r"faqat metadata|faqat-metadata|metadata-only|metadata only"
                         r"|only metadata", re.IGNORECASE)
    for yol in (BRIDGE_SRC, BRIDGE_BUILD, HANDOFF):
        topilgan = [satr.strip() for satr in _matn(yol).splitlines() if davolar.search(satr)]
        assert not topilgan, f"{yol.name} da asossiz «faqat metadata» da'vosi: {topilgan}"


def test_YIGUVCHINING_SANOQ_OSHKORLIGI_qulflangan():
    """⚠️ Muzlatilgan yig'uvchi sanoq so'rovini O'Z izohida oshkor qiladi. Bu test shu
    oshkorlikni QULFLAYDI: kimdir uni diffdan olib tashlasa, to'plam qizil bo'ladi."""
    matn = _matn(EXTRACTOR_SRC)
    assert ("Metadata-only: qiymatlar o'qilmadi, faqat metadata va КОЛИЧЕСТВО(*)."
            in matn), "eksport izohidagi sanoq oshkorligi yo'qolgan"
    assert "SANOQLAR — FAQAT КОЛИЧЕСТВО(*)" in matn
    assert ("`row_count` ATAYLAB bo'sh: inventarizatsiya so'rov yubormaydi." in matn), (
        "inventarizatsiyaning so'rov yubormasligi oshkorligi yo'qolgan")


def test_HUJJATLAR_IKKI_SANOQ_SOROVINI_OSHKOR_qiladi():
    """⚠️ Oshkorlik faqat kodda emas, OPERATOR o'qiydigan hujjatda ham bo'lishi kerak:
    haqiqiy mijoz bazasida nima ishlashini hal qiladigan odam shu hujjatni o'qiydi."""
    handoff = _matn(HANDOFF)
    assert "КОЛИЧЕСТВО(*)" in handoff, "handoff sanoq so'rovini eslamaydi"
    assert "READ_ONLY_CARDINALITY_PROBE" in handoff
    assert re.search(r"\bikki\b|\b2\b", handoff, re.IGNORECASE), (
        "so'rov SONI hujjatda yozilishi kerak")


# ── 11. HANDOFF HUJJATINING SHARTLARI ─────────────────────────────────────────────────────
def test_HANDOFF_holatni_EPF_SOURCE_READY_deb_belgilaydi():
    handoff = _matn(HANDOFF)
    assert "EPF_SOURCE_READY" in handoff
    assert "UNVERIFIED_ON_REAL_1C" in handoff


def test_HANDOFF_QURILGAN_EPF_DAVOSINI_qilmaydi():
    """⚠️ `.epf` BINARINI QURILGAN DEB AYTMASLIK — qat'iy talab.

    Shuningdek «bir marta bosib o'rnatiladigan» (install-ready one-click) degan da'vo
    ham yozilmaydi: o'rnatuvchi, xizmat, avtoyuklanish va yangilovchi YO'Q."""
    handoff = _matn(HANDOFF).lower()
    for davo in ("install-ready", "one-click", "one click", "bir bosishda",
                 "tayyor o'rnatuvchi", "ready to install"):
        assert davo not in handoff, f"handoff da asossiz da'vo: {davo}"


def test_HANDOFF_MANBA_SHA_sini_va_YIGUVCHI_manbasini_korsatadi():
    handoff = _matn(HANDOFF)
    assert "cea2133" in handoff, "aniq manba SHA si hujjatda bo'lishi kerak"
    assert EXTRACTOR_SHA256[:16] in handoff, "ekstraktor manbasining xeshi yozilmagan"
    assert "integrations/1c/collector/BinOSDiscoveryCollector.bsl" in handoff
    assert "BinOSDiscoveryCollector.epf" in handoff, "kutilgan `.epf` nomi yozilmagan"


def test_HANDOFF_PROTOKOLNI_va_NOSOZLIK_KODLARINI_sanab_beradi():
    handoff = _matn(HANDOFF)
    for nom in FILE_NAMES:
        assert nom in handoff, f"yurish protokolining fayli hujjatda yo'q: {nom}"
    #: ⚠️ QAROR 2 ning yangi kodlari: har biri uchun `code` + operator matni +
    #: `next_action` hujjatda bo'lishi kerak.
    yangi_kodlar = ("COLLECTOR_EXECUTION_NOT_ALLOWED", "STALE_OUTPUT", "NONCE_MISMATCH",
                    "WRONG_COLLECTOR_VERSION", "PARTIAL_PACKAGE",
                    "OUTPUT_PREDATES_REQUEST", "OPERATOR_CANCELLED", "RUN_DIR_NOT_EMPTY",
                    "TARGET_AMBIGUOUS")
    for kod in yangi_kodlar:
        assert kod in handoff, f"nosozlik kodi jadvalda yo'q: {kod}"
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", kod)


#: ⚠️ Ko'prik `notes` ga YOZADIGAN qiymatlar EMAS, balki holat qiymatlari — ular
#: nosozlik kodi jadvalida bo'lmaydi, chunki ular nosozlik emas.
_HOLAT_QIYMATLARI = frozenset({"SUCCESS", "PARTIAL", "FAILED", "BRIDGE_REJECTED"})


def _koprik_kodlari() -> set[str]:
    """Ko'prik manbasidagi HAMMA sabab kodi (satr literallaridan, izohlardan EMAS)."""
    kod = "\n".join(runtime_audit.code_lines(_matn(BRIDGE_SRC), strip_literals=False))
    return set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"', kod)) - _HOLAT_QIYMATLARI


def test_KOPRIK_KODLARINING_HAMMASI_HANDOFFDA_tushuntirilgan():
    """⚠️ KOD JADVALDA BO'LMASA, OPERATOR UNI HECH QAYERDAN O'QIY OLMAYDI.

    QAROR 2: har nosozlik uchun UCHTA narsa — `code`, operator matni va `next_action`.
    Bu test birinchisini qulflaydi: manbada paydo bo'lgan yangi kod hujjatga ham
    yozilmaguncha to'plam qizil bo'ladi. Aks holda kodlar jimgina ko'payib ketardi va
    operator tushunmaydigan qisqartma bilan qolardi."""
    handoff = _matn(HANDOFF)
    kodlar = _koprik_kodlari()
    assert kodlar, "ko'prik manbasida birorta sabab kodi topilmadi"
    yoq = sorted(k for k in kodlar if k not in handoff)
    assert not yoq, f"handoff jadvalida tushuntirilmagan kod: {yoq}"


def test_KOPRIK_KODLARI_SHAKL_qoidasiga_mos():
    """QAROR 2: `code` shakli `[A-Z][A-Z0-9_]*`."""
    for kod in _koprik_kodlari():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", kod), kod


def test_OPERATOR_matnida_ICHKI_ATAMA_YOQ():
    """⚠️ Operator `nonce`, `fingerprint`, `overall`, `JSON` so'zlarini KO'RMAYDI.

    Ichki atama operatorni yordam so'rashga majbur qiladi va u matn 1C oynasida —
    ya'ni bizdan uzoqda — turadi."""
    matn = _matn(BRIDGE_SRC)
    boshi = matn.find("Функция МостТекстОператору(")
    assert boshi > 0, "operator matni funksiyasi topilmadi"
    tana = matn[boshi:matn.find("КонецФункции", boshi)]
    operator_matnlari = re.findall(r'"([^"]{12,})"', tana)
    assert len(operator_matnlari) >= 4, f"operator matnlari topilmadi: {operator_matnlari}"
    for satr in operator_matnlari:
        for atama in ("nonce", "fingerprint", "overall", "JSON", "manifest", "bundle",
                      "run_id", "sha256"):
            assert atama.lower() not in satr.lower(), (
                f"operator matnida ichki atama `{atama}`: {satr!r}")


def test_HANDOFF_SIR_SAQLAMAYDI():
    """⚠️ SIR YO'Q: handoff ommaviy o'qiladigan hujjat (kod repo PUBLIC)."""
    handoff = _matn(HANDOFF)
    for naqsh in (r"\bUsr\s*=", r"\bPwd\s*=", r"/N[A-Za-z]", r"/P[A-Za-z]",
                  r"[A-Za-z]:\\\\Users\\\\[A-Za-z]"):
        assert not re.search(naqsh, handoff), f"handoff da sir ko'rinishi: {naqsh}"


def test_HANDOFF_1C_XAVFSIZLIGINI_zaiflashtirishni_TAKLIF_QILMAYDI():
    handoff = _matn(HANDOFF)
    for taqiq in ("БезопасныйРежим = Ложь", "xavfsiz rejimni o'chir",
                  "xavfsizlik profilini o'zgartir", "rolni tahrirlang"):
        assert taqiq not in handoff, f"xavfsizlikni zaiflashtirish ko'rsatmasi: {taqiq}"
    assert "zaiflashtir" in handoff.lower(), (
        "xavfsizlikka tegilmasligi hujjatda OCHIQ yozilishi kerak")
