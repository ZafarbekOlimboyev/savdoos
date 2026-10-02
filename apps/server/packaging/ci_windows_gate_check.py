# -*- coding: utf-8 -*-
"""Windows CI darvozasining O'LCHOV yordamchisi — `.github/workflows/windows-1c-gate.yml`.

NEGA ALOHIDA SKRIPT (va YAML ichida emas): YAML ichidagi ko'p qatorli PowerShell/bash
qismlari MAHALLIY sinalmaydi — ular faqat runner'da birinchi marta bajariladi. Bu fayl esa
mahalliy Windows'da AYNI holda yurgiziladi, ya'ni darvozaning mantig'i CI'ga chiqishdan
OLDIN o'lchanadi. ⚠️ Qoida: workflow faqat CHAQIRADI, QAROR shu yerda.

⚠️ BU SKRIPT HECH NARSA QURMAYDI, O'CHIRMAYDI va TARMOQQA CHIQMAYDI. U faqat:
   · `parity_harness.yigma_tayyorligi()` hukmini O'QIYDI (`verdict`),
   · yig'ilgan `.exe` ning SHA-256 ini va manba imzosini YOZADI (`record`),
   · pytest ning junit faylini TEKSHIRADI (`gate`).

⚠️ YANGI MEXANIZM O'YLAB CHIQARILMAYDI: eskirgan-yig'ma hukmi BIR joydan — OWNER B
   (`packaging/parity_harness.py`) dan — olinadi. Ikkinchi nusxa bir kun ajralib ketardi va
   CI bilan mahalliy reliz darvozasi JIMGINA boshqa javob berardi.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

# ⚠️ CHIQISH OQIMLARI UTF-8 GA O'TKAZILADI (o'lchangan nuqson): bu skriptning matnlari
#    o'zbekcha va ⚠️ belgili, Windows konsoli esa `cp1252` bo'lishi mumkin. U holda
#    `argparse` ning O'Z yordam matni ham `UnicodeEncodeError` berib skriptni YIQITARDI
#    va asl sabab YO'QOLARDI. `backslashreplace`: belgi sig'masa ham MATN chiqadi.
# ⚠️ Bu BOLA JARAYONLARGA TA'SIR QILMAYDI — skript jarayon ochmaydi, ya'ni
#    `test_agent_*` ning kodlash o'lchovlari bu yerdan BUZILMAYDI.
for _oqim in (sys.stdout, sys.stderr):
    try:
        _oqim.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
    except Exception:          # noqa: BLE001 - oqim almashtirilgan bo'lsa ham davom etadi
        pass

#: `apps/server` — bu fayl `apps/server/packaging/` da turadi.
SERVER_ROOT = pathlib.Path(__file__).resolve().parent.parent
#: Worktree ildizi (`integrations/1c/...` hujjati shu yerdan izlanadi).
WORKTREE = SERVER_ROOT.parents[1]

#: ⚠️ `from packaging.parity_harness import ...` ISHLAMAYDI: `packaging` nomi PyPI
#:    paketi bilan to'qnashadi. Shu bois harness YO'L bilan yuklanadi — `test_agent_*.py`
#:    modullari ham AYNI usulni ishlatadi (`_harness()`).
_HARNESS_MODUL_NOMI = "binos_parity_harness"


def _harness():
    """OWNER B darvozasi — yo'l bilan yuklanadi, mavjud nusxa QAYTA ISHLATILADI."""
    modul = sys.modules.get(_HARNESS_MODUL_NOMI)
    if modul is not None:
        return modul
    # ⚠️ `app.services.discovery_agent` harness ichida import qilinadi, demak `apps/server`
    #    `sys.path` da bo'lishi SHART. Buni `cwd` ga TAYANMASDAN qo'yamiz: workflow
    #    qadamining ishchi papkasi o'zgarsa ham skript ishlashi kerak.
    if str(SERVER_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_ROOT))
    yo_l = SERVER_ROOT / "packaging" / "parity_harness.py"
    spec = importlib.util.spec_from_file_location(_HARNESS_MODUL_NOMI, yo_l)
    if spec is None or spec.loader is None:
        raise SystemExit(f"parity harnessi yuklanmadi: {yo_l}")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


def _xabar(matn: str) -> None:
    """⚠️ Chiqish DOIM UTF-8: runner konsolida `cp1252` bo'lsa ⚠️ belgisi `UnicodeEncodeError`
    berib skriptning O'ZINI yiqitardi va asl sabab YO'QOLARDI."""
    xom = matn + "\n"
    oqim = sys.stdout
    try:
        oqim.write(xom)
    except UnicodeEncodeError:
        kod = getattr(oqim, "encoding", None) or "ascii"
        oqim.write(xom.encode(kod, "replace").decode(kod, "replace"))
    oqim.flush()


def _summary_yoz(matn: str) -> None:
    """`$GITHUB_STEP_SUMMARY` ga qo'shadi. ⚠️ O'zgaruvchi yo'q bo'lsa JIM o'tadi —
    mahalliy yurishda summary fayli bo'lmaydi va bu XATO emas."""
    yo_l = os.environ.get("GITHUB_STEP_SUMMARY")
    if not yo_l:
        return
    with open(yo_l, "a", encoding="utf-8") as f:
        f.write(matn.rstrip("\n") + "\n")


# ══════════════════════════════════════════════════════════════════════════════════════════
# verdict — eskirgan-yig'ma hukmi (OWNER B dan)
# ══════════════════════════════════════════════════════════════════════════════════════════
def buyruq_verdict(args: argparse.Namespace) -> int:
    """`yigma_tayyorligi()` hukmi KUTILGAN holat bilan AYNAN mos kelsinmi.

    ⚠️ IKKI TOMONLAMA ISHLATILADI:
      · `--expect TOZA`    — toza yig'ma: darvoza o'tishi KERAK;
      · `--expect ESKIRGAN` — SALBIY NAZORAT: manba o'zgartirilgandan keyin AYNI artefakt
        «eskirgan» deb topilishi KERAK. Mos kelmasa job QIZIL — ya'ni «eskirgan artefakt
        yiqiladi» da'vosi HAR YURISHDA o'lchanadi, hujjatdagi gap bo'lib qolmaydi.
    """
    h = _harness()
    holat, sabab = h.yigma_tayyorligi()
    _xabar(f"[verdict] holat={holat} kutilgan={args.expect}")
    if sabab:
        _xabar(f"[verdict] sabab: {sabab}")
    _xabar(f"[verdict] exe={h.YIGMA_EXE}")
    _xabar(f"[verdict] build={h.YIGMA_BUILD}")
    if holat != args.expect:
        _xabar(f"[verdict] YIQILDI: hukm `{holat}`, kutilgani `{args.expect}`")
        return 1
    _xabar("[verdict] MOS")
    return 0


# ══════════════════════════════════════════════════════════════════════════════════════════
# record — EXE SHA-256 + manba imzosi
# ══════════════════════════════════════════════════════════════════════════════════════════
_DOC_NISBIY = pathlib.PurePosixPath("integrations/1c/AGENT_PORTABLE_BUILD.md")


def buyruq_record(args: argparse.Namespace) -> int:
    """Yig'ilgan artefaktning IMZOSINI log'ga, summary'ga va fayllarga yozadi.

    ⚠️ `.exe` NING O'ZI yuklanmaydi — faqat uning XESHI. Sabab: artefakt IMZOLANMAGAN
       (`unsigned`) va uni CI artefakti bo'lib tarqatish «tarqatishga tayyor» degan
       da'voga o'xshab ketardi. Bu yerda faqat ISBOT yoziladi, MAHSULOT yozilmaydi.
    """
    h = _harness()
    exe = pathlib.Path(h.YIGMA_EXE)
    if not exe.is_file():
        _xabar(f"[record] YIQILDI: `.exe` yo'q — {exe}")
        return 1
    baytlar = exe.read_bytes()
    exe_sha = hashlib.sha256(baytlar).hexdigest()
    manba_sha = h.manba_xeshi()

    # ⚠️⚠️ LANGAR `.exe` EMAS, `PYZ-00.pyz`. O'LCHANGAN SABAB: AYNI manba + AYNI build
    #      muhiti bilan ikki yig'ma `.exe` uchun IKKI XIL sha256 beradi (PE sarlavhasidagi
    #      vaqt tamg'asi/manifest), `PYZ-00.pyz` uchun esa AYNI baytlarni beradi. Shu bois
    #      hujjat bilan TENGLIK talab qiladigan darvoza PYZ ga qo'yildi
    #      (`test_hujjatdagi_PYZ_XESHI_haqiqiy_yigmaga_MOS_va_EXE_TAKRORLANMASLIGI_OCHIQ`),
    #      `.exe` xeshi esa MOS YOZUVLAR bo'lib qoldi.
    # ⚠️ Bu yerda HECH NARSA YIQITILMAYDI: `record` faqat ISBOT yozadi. PYZ tengligining
    #    HUKMI testda, `verdict` esa yig'ma yangiligini alohida o'lchaydi.
    pyz = pathlib.Path(h.pyz_yoli())
    pyz_sha = hashlib.sha256(pyz.read_bytes()).hexdigest() if pyz.is_file() else ""
    pyz_bayt = pyz.stat().st_size if pyz.is_file() else 0

    # ⚠️ Hujjatdagi xesh — BOOKKEEPING fakti, product da'vosi emas. CI'da yangi qurilgan
    #    `.exe` ning xeshi hujjatdagidan FARQ QILADI va bu KUTILGAN. Shu bois u
    #    YIQITMAYDI, lekin summary'da KO'RINADI — aks holda drift jimgina yo'qolardi.
    doc = WORKTREE / _DOC_NISBIY
    doc_xeshlari: list[str] = []
    if doc.is_file():
        doc_xeshlari = sorted(set(re.findall(r"\b[0-9a-f]{64}\b",
                                            doc.read_text(encoding="utf-8").lower())))

    yozuv = {
        "commit": os.environ.get("GITHUB_SHA", ""),
        "ref": os.environ.get("GITHUB_REF", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "runner_os": os.environ.get("RUNNER_OS", sys.platform),
        "python": sys.version.split()[0],
        "pyinstaller_kutilgan": args.pyinstaller,
        "exe_yoli": str(exe),
        "exe_sha256": exe_sha,
        "exe_bayt": len(baytlar),
        "pyz_yoli": str(pyz),
        "pyz_sha256": pyz_sha,
        "pyz_bayt": pyz_bayt,
        "manba_imzosi_sha256": manba_sha,
        "hujjatdagi_sha256": doc_xeshlari,
        # ⚠️ `hujjat_exe_mos` CI'da `False` bo'lishi KUTILADI va bu nuqson EMAS —
        #    `.exe` bayt-darajasida takrorlanuvchan emas. Langarning mosligi
        #    `hujjat_pyz_mos` da.
        "hujjat_exe_mos": exe_sha in doc_xeshlari,
        "hujjat_pyz_mos": bool(pyz_sha) and pyz_sha in doc_xeshlari,
        "exe_bayt_darajasida_takrorlanuvchan": False,
        "imzolangan": False,            # ⚠️ code signing YO'Q va bu YERDA ham yozilgan
        "haqiqiy_1c": "UNVERIFIED_ON_REAL_1C",
    }
    _xabar(f"[record] EXE SHA-256     : {exe_sha}")
    _xabar(f"[record] EXE bayt        : {len(baytlar)}")
    _xabar(f"[record] PYZ SHA-256     : {pyz_sha or '(PYZ yo‘q)'}  <- LANGAR")
    _xabar(f"[record] PYZ bayt        : {pyz_bayt}")
    _xabar(f"[record] MANBA imzosi    : {manba_sha}")
    _xabar(f"[record] commit          : {yozuv['commit']}")
    _xabar(f"[record] hujjatdagi xesh : {doc_xeshlari or '(yo‘q)'}")
    _xabar(f"[record] hujjat EXE mos  : {yozuv['hujjat_exe_mos']} (CI'da False KUTILADI)")
    _xabar(f"[record] hujjat PYZ mos  : {yozuv['hujjat_pyz_mos']} <- LANGAR")

    satrlar = [
        "## Windows 1C darvozasi — yig'ma imzosi",
        "",
        "| Nima | Qiymat |",
        "|---|---|",
        f"| `PYZ-00.pyz` SHA-256 (**LANGAR**) | `{pyz_sha or '(PYZ yo‘q)'}` |",
        f"| `PYZ-00.pyz` o'lchami | {pyz_bayt} bayt |",
        f"| Hujjatdagi PYZ langari bilan MOS | **{yozuv['hujjat_pyz_mos']}** |",
        f"| `BinOSDiscoveryAgent.exe` SHA-256 (mos yozuvlar) | `{exe_sha}` |",
        f"| `.exe` o'lchami | {len(baytlar)} bayt |",
        f"| `.exe` bayt-darajasida takrorlanuvchan | **YO'Q** (o'lchangan) |",
        f"| Manba imzosi (`parity_harness.manba_xeshi()`) | `{manba_sha}` |",
        f"| Nomzod commit (`GITHUB_SHA`) | `{yozuv['commit'] or '(mahalliy)'}` |",
        f"| Python | {yozuv['python']} |",
        f"| PyInstaller (pinlangan) | {args.pyinstaller} |",
        f"| Imzolangan (code signing) | **YO'Q — `unsigned`** |",
        f"| Haqiqiy 1C da tekshirilgan | **`UNVERIFIED_ON_REAL_1C`** |",
        "",
        "⚠️ `.exe` ning O'ZI artefakt bo'lib yuklanmaydi — faqat imzosi. Artefakt "
        "IMZOLANMAGAN va bu yurish uni «tarqatishga tayyor» DEB TASDIQLAMAYDI.",
        "",
    ]
    if doc_xeshlari and not yozuv["hujjat_exe_mos"]:
        satrlar += [
            "### `.exe` xeshi DRIFT (CI'da KUTILGAN — nuqson EMAS)",
            "",
            f"`{_DOC_NISBIY}` da yozilgan xesh(lar): "
            + ", ".join(f"`{x}`" for x in doc_xeshlari),
            "",
            "Hujjatdagi `.exe` xeshi RELIZ qilinadigan (mahalliy) artefaktni nomlaydi — u "
            "MOS YOZUVLAR. CI esa manbadan YANGI artefakt quradi, va `.exe` xeshi AYNI "
            "manbadan ham HAR yig'mada boshqa chiqadi (PE sarlavhasidagi vaqt "
            "tamg'asi/manifest — ikki yig'ma bilan o'lchangan). Shu bois `.exe` xeshiga "
            "TENGLIK darvozasi QO'YILMAYDI.",
            "",
            "Hujjat bilan TENGLIK talab qiladigan LANGAR — `PYZ-00.pyz`, va u SHU "
            "job'da `tests/test_agent_portability.py::"
            "test_hujjatdagi_PYZ_XESHI_haqiqiy_yigmaga_MOS_va_EXE_TAKRORLANMASLIGI_OCHIQ` "
            f"testida ROSTDAN bajariladi (`--deselect` YO'Q). Yuqoridagi "
            f"«Hujjatdagi PYZ langari bilan MOS» qatori: **{yozuv['hujjat_pyz_mos']}**.",
            "",
        ]
    elif not doc_xeshlari:
        satrlar += [f"⚠️ `{_DOC_NISBIY}` da birorta SHA-256 topilmadi.", ""]
    _summary_yoz("\n".join(satrlar))

    if args.out_json:
        pathlib.Path(args.out_json).write_text(
            json.dumps(yozuv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out_md:
        pathlib.Path(args.out_md).write_text("\n".join(satrlar), encoding="utf-8")
    return 0


# ══════════════════════════════════════════════════════════════════════════════════════════
# gate — junit tekshiruvi: 0 SKIP, 0 FAIL, modul SONLARI
# ══════════════════════════════════════════════════════════════════════════════════════════
def _junit_holatlari(kok: ET.Element) -> list[tuple[str, str, str]]:
    """`(classname, name, holat)` — holat: `pass`/`skipped`/`failure`/`error`.

    ⚠️ ATRIBUT emas, BOLA ELEMENT o'qiladi (`<skipped/>`, `<failure/>`, `<error/>`):
       `testsuite` atributlari (`skipped="0"`) pytest versiyalari orasida farq qilgan va
       ularga ishonish «0 skip» da'vosini TEKSHIRILMAGAN holda qabul qilish bo'lardi.
    """
    chiqish: list[tuple[str, str, str]] = []
    for tc in kok.iter("testcase"):
        holat = "pass"
        for teg in ("error", "failure", "skipped"):
            if tc.find(teg) is not None:
                holat = "failure" if teg == "failure" else teg
                if teg == "error":
                    holat = "error"
                break
        chiqish.append((tc.get("classname", ""), tc.get("name", ""), holat))
    return chiqish


def _modul_talablari(xom: list[str]) -> dict[str, int]:
    """`tests.test_agent_parity:61` -> `{"tests.test_agent_parity": 61}`."""
    talab: dict[str, int] = {}
    for bolak in xom:
        nom, _, son = bolak.rpartition(":")
        if not nom or not son.isdigit():
            raise SystemExit(f"`--module` shakli `<modul>:<eng_kam_son>` bo'lsin: {bolak}")
        talab[nom] = int(son)
    return talab


def buyruq_gate(args: argparse.Namespace) -> int:
    """Junit faylini TEKSHIRADI va BITTA ham skip qoldirmaydi.

    ⚠️⚠️ NEGA BU ISHONCHLI (brief §8 — «nega ishonchli ekanini yozing»):
      1. **Fayl yo'qligi YIQILISH.** pytest yiqilib junit yozmasa (INTERNALERROR,
         to'xtab qolish, import xatosi) darvoza JIM o'tib ketmaydi — bu AYNAN
         `verify_pytest_run.py` paydo bo'lishiga sabab bo'lgan nuqson edi.
      2. **Skip BOLA ELEMENT bilan sanaladi**, `testsuite` atributi bilan EMAS.
      3. **Har modulning ENG KAM test soni TALAB qilinadi.** Bu `--deselect` yoki `-k`
         bilan jimgina «hammasi yashil» qilishning yo'lini yopadi: deselect qilingan test
         junit'da UMUMAN bo'lmaydi, ya'ni son KAMAYADI va job QIZIL bo'ladi.
      4. **Taqiqlangan node id (`--forbid`) — HOZIR ISHLATILMAYDI.** ⚠️ Workflow bu
         kalitni BERMAYDI: yig'ma o'zligining langari `.exe` xeshidan TAKRORLANUVCHAN
         `PYZ-00.pyz` xeshiga ko'chirilgandan keyin deselect qiladigan test QOLMADI va
         beshta modulning HAMMA testi bajariladi. Imkoniyat kodda QOLDIRILDI (kelajakda
         ROSTDAN bajarilmaydigan test paydo bo'lsa kerak bo'ladi), lekin u DARVOZA
         EMAS — berilmasa hech narsa tekshirilmaydi. ⚠️ Shu bois `--forbid` ni
         «himoya bor» deb hisoblamang: himoya 3-banddagi ENG KAM SONLAR.
      5. **`failure`/`error` ham shu yerda sanaladi**, ya'ni pytest ning chiqish kodiga
         YOLG'IZ ishonilmaydi (quvur, qobiq va `Tee-Object` kodni yo'qotishi mumkin).
    """
    junit = pathlib.Path(args.junit)
    if not junit.is_file():
        _xabar(f"[gate] YIQILDI: junit fayli YO'Q — {junit}. pytest yurmagan yoki "
               f"junit yozilmasdan yiqilgan; «yashil» deb hisoblash TAQIQLANGAN.")
        return 1
    try:
        kok = ET.parse(junit).getroot()
    except ET.ParseError as e:
        _xabar(f"[gate] YIQILDI: junit o'qilmadi ({e}) — {junit}")
        return 1

    holatlar = _junit_holatlari(kok)
    jami = len(holatlar)
    skipped = [(c, n) for c, n, h in holatlar if h == "skipped"]
    yiqilgan = [(c, n, h) for c, n, h in holatlar if h in ("failure", "error")]

    sonlar: dict[str, int] = {}
    for c, _n, _h in holatlar:
        sonlar[c] = sonlar.get(c, 0) + 1

    muammolar: list[str] = []
    if jami == 0:
        muammolar.append("junit BO'SH — birorta test bajarilmagan")
    if skipped:
        muammolar.append(
            f"{len(skipped)} SKIP bor, lekin Windows'da 0 bo'lishi SHART: "
            + ", ".join(f"{c}::{n}" for c, n in skipped[:20]))
    if yiqilgan:
        muammolar.append(
            f"{len(yiqilgan)} test yiqildi: "
            + ", ".join(f"{c}::{n}[{h}]" for c, n, h in yiqilgan[:20]))

    for modul, eng_kam in _modul_talablari(args.module).items():
        bor = sonlar.get(modul, 0)
        if bor < eng_kam:
            muammolar.append(
                f"`{modul}` dan {bor} test bajarildi, kamida {eng_kam} kutilgan — "
                f"testlar JIMGINA tanlanmagan (`-k`/`--deselect`) yoki modul yig'ilmagan")

    for taqiq in args.forbid:
        modul, _, nom = taqiq.partition("::")
        topildi = [n for c, n, _h in holatlar if c == modul and n == nom]
        if topildi:
            muammolar.append(
                f"ATAYLAB deselect qilingan test junit'da PAYDO BO'LDI: {taqiq} — "
                f"workflow dagi deselect ro'yxati eskirgan")

    _xabar(f"[gate] jami={jami} skip={len(skipped)} yiqilgan={len(yiqilgan)}")
    for modul in sorted(sonlar):
        _xabar(f"[gate]   {modul}: {sonlar[modul]}")

    if muammolar:
        _xabar("[gate] YIQILDI:")
        for m in muammolar:
            _xabar(f"[gate]   - {m}")
        _summary_yoz("### Windows 1C darvozasi — QIZIL\n\n"
                     + "\n".join(f"- {m}" for m in muammolar) + "\n")
        return 1

    _xabar("[gate] O'TDI: 0 skip, 0 yiqilish, har modul kutilgan sondan kam emas")
    _summary_yoz(
        "### Windows 1C darvozasi — BESH MODUL\n\n"
        "| Modul | Bajarildi |\n|---|---|\n"
        + "\n".join(f"| `{m}` | {sonlar[m]} |" for m in sorted(sonlar))
        + f"\n\n**Jami {jami} test · 0 skip · 0 yiqilish.** "
          "Skip soni junit ning `<skipped/>` bola elementlaridan sanaladi, "
          "`testsuite` atributidan EMAS.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    # ⚠️ `description=__doc__` EMAS: docstring uzun va ⚠️ belgili, yordam matni esa
    #    har qanday konsolda o'qilishi kerak. Tafsilot fayl boshida turadi.
    p = argparse.ArgumentParser(
        prog="ci_windows_gate_check.py",
        description="Windows 1C CI darvozasining o'lchov yordamchisi.")
    sub = p.add_subparsers(dest="buyruq", required=True)

    v = sub.add_parser("verdict", help="eskirgan-yig'ma hukmini KUTILGAN holat bilan solish")
    v.add_argument("--expect", required=True,
                   choices=["TOZA", "ESKIRGAN", "ISBOTSIZ", "YO_Q"])
    v.set_defaults(func=buyruq_verdict)

    r = sub.add_parser("record", help="EXE SHA-256 + manba imzosini yozish")
    r.add_argument("--pyinstaller", default="(berilmagan)")
    r.add_argument("--out-json")
    r.add_argument("--out-md")
    r.set_defaults(func=buyruq_record)

    g = sub.add_parser("gate", help="junit: 0 skip, 0 yiqilish, modul sonlari")
    g.add_argument("--junit", required=True)
    g.add_argument("--module", action="append", default=[],
                   metavar="MODUL:ENG_KAM", help="masalan tests.test_agent_parity:64")
    g.add_argument("--forbid", action="append", default=[], metavar="MODUL::TEST",
                   help="junit'da BO'LMASLIGI kerak bo'lgan test — HOZIR workflow "
                        "bu kalitni BERMAYDI (deselect qilinadigan test qolmadi)")
    g.set_defaults(func=buyruq_gate)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
