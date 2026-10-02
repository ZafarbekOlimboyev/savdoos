# -*- coding: utf-8 -*-
"""OPERATOR BUYRUQ QATORI — runtime paketini OFFLINE tekshirish.

    python -m app.services.discovery_1c.cli validate-runtime-bundle <papka>
    python -m app.services.discovery_1c.cli validate-runtime-bundle <papka> --json

⚠️ CHIQISH KODI SHARTNOMA, ya'ni testda QULFLANGAN. UCH HOLAT:
       0 — paket TO'G'RI **va** yurish TO'LIQ (`overall == SUCCESS`) — faqat shu holatda
           paket keyingi bosqichga (AI analitik) o'tadi;
       1 — paket NOTO'G'RI: sxema, sir, xesh yoki ziddiyat nuqsoni bor — FAYLLARGA ISHONIB
           BO'LMAYDI;
       2 — paket to'g'ri (fayllar butun, sxema mos, sir yo'q), LEKIN `overall != SUCCESS`
           — yurishning O'ZI to'liq tugamagan, ya'ni TO'XTASH sharti.
           ⚠️ AMALDA bu `PARTIAL` (va holat o'qilmagan) holat: `FAILED` majburiy
              artefaktning YO'QLIGINI bildiradi, ya'ni paket AYNI VAQTDA yaroqsiz
              bo'ladi va `1` qaytadi. Ya'ni `FAILED` uchun `2` shoxi ERISHIB
              BO'LMAYDIGAN — bu qat'iyroq, `0` qaytaradigan holat YO'Q.
   ⚠️ `1` NI `2` DAN AJRATISH SHARTNOMANING O'ZAGI: «fayllarga ishonib bo'lmaydi» va «fayllar
      butun, lekin yurish to'liq emas» ikki XIL vaziyat va operatorning harakati ham boshqa
      (birinchisida paketni QAYTA yig'adi, ikkinchisida yiqilgan bo'limning sababini o'qiydi).
   ⚠️ Ilgari `0` FAQAT tekshiruvlarga qarardi, ya'ni `overall=FAILED` bo'lgan paket ham `0`
      olardi va runbook bo'yicha keyingi bosqichga o'tib ketardi.
   Papka topilmasa — bu paket haqidagi hukm (majburiy fayllar yo'q), ya'ni `1`.

⚠️ `2` NI BUYRUQ XATOSI HAM QAYTARADI (noma'lum bayroq, argument yo'q) va bu raqamni ATAYLAB
   BO'LISHADI: ikkisi ham «TO'XTA, keyingi bosqichga o'tma» degani, ikkisi ham `1` EMAS
   («paket yaroqsiz» degan hukm emas). Ajratish CHIQISHDA ko'rinadi: paket hukmi `stdout` ga
   hisobot bo'lib tushadi, buyruq xatosi esa `stderr` ga chiqadi va hisobot umuman
   yozilmaydi. Yagona raqam ostida turishining sababi tashqi: runbookning 9-qadami va uning
   testi uch kodni (`0`/`1`/`2`) qulflab qo'ygan.

⚠️ SIR EKRANGA CHIQMAYDI. Nuqson matnida topilgan qiymatning O'ZI hech qachon ko'rsatilmaydi:
   sir skanlari faqat fayl nomi, satr raqami, naqsh nomi va tavsifini yozadi
   (`redact.Finding.__str__`, `runtime_bundle._raw_secret_findings`), QOLGAN tekshiruvlar esa
   nuqson matniga qo'shiladigan HAR QANDAY tashqi qiymatni (oila nomi, fayl nomi, obyekt
   manzili, rejim izohi, sxema xatosining matni) `runtime_bundle._xavfsiz` orqali
   `redact.redact` dan o'tkazadi. Sabab: bu matn operatorning ekranidan jurnalga, jurnaldan
   esa xabar almashinuviga ko'chadi.
   ⚠️ Ilgari bu da'vo YOLG'ON edi: `errors.json` dan kelgan `family` qiymati XOM holda nuqson
      matniga qo'shilardi, ya'ni 1C xatosi sifatida tushgan ulanish satri, server nomi va
      PAROL ekranda ham, `--json` chiqishida ham TO'LIQ ko'rinardi.

⚠️ TARMOQ YO'Q, 1C GA ULANISH YO'Q, AI PROVAYDERI KERAK EMAS. CLI faqat papkani O'QIYDI;
   hech narsa yozmaydi va hech narsani tuzatmaydi. «Tuzatib qo'yish» bayrog'i ATAYLAB yo'q:
   paketni jimgina o'zgartirish — nuqsonni yashirish va asl baytlarni yo'qotish bo'lardi.

⚠️ `--json` chiqishi DETERMINISTIK: bir xil paket — AYNAN bir xil baytlar. Shu sababli unda
   papka YO'LI ham, vaqt tamg'asi ham YO'Q (`Report.to_json` izohiga qarang). Yo'l faqat odam
   o'qiydigan hisobotda ko'rinadi.
"""
from __future__ import annotations

import argparse
import sys

from .runtime_bundle import (CHECK_NAMES, MODES, OPTIONAL_FILES, OVERALL_SUCCESS,
                             REPORT_VERSION, REQUIRED_FILES, Report, report_to_json_text,
                             validate_runtime_bundle)

#: Buyruq nomi — operator skriptidagi yozilishi bilan AYNI.
VALIDATE_CMD = "validate-runtime-bundle"

#: Chiqish kodlari — SHARTNOMA (modul docstringiga qarang).
EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE = 2

#: Paket TO'G'RI, lekin yurish TO'LIQ EMAS (`overall != SUCCESS`) — TO'XTASH sharti.
#: ⚠️ RAQAM `EXIT_USAGE` BILAN BIR XIL va bu ochiq aytiladi (modul docstringiga qarang):
#: ikkisi ham «to'xta», ikkisi ham «paket yaroqsiz» EMAS; farqi chiqish oqimida ko'rinadi.
EXIT_INCOMPLETE = 2

#: Odam o'qiydigan hisobotdagi belgilar. ⚠️ ASCII ataylab: Windows konsoli cp1252 da ishlaydi
#: va bezak belgisi tufayli XULOSA yo'qolib qolishi mumkin emas.
MARK_OK = "[OK]"
MARK_BAD = "[NUQSON]"

PROG = "python -m app.services.discovery_1c.cli"


def build_parser() -> argparse.ArgumentParser:
    """Argument tahlilchisi. ⚠️ Alohida funksiya: testlar uni chaqiruvsiz ham tekshira oladi."""
    p = argparse.ArgumentParser(
        prog=PROG,
        description="1C runtime paketini OFFLINE tekshirish (tarmoq yo'q, 1C ga ulanish yo'q).")
    subs = p.add_subparsers(dest="command", required=True, metavar="buyruq")
    v = subs.add_parser(
        VALIDATE_CMD,
        help="runtime paketi papkasini shartnomaga solishtiradi",
        description=(
            "Papkani tekshiradi. Majburiy fayllar: " + ", ".join(REQUIRED_FILES)
            + ". Ixtiyoriy: " + ", ".join(OPTIONAL_FILES)
            + f". Rejimlar: {', '.join(MODES)}."
            + " Chiqish kodi: 0 = paket to'g'ri va yurish TO'LIQ, 1 = paket noto'g'ri, "
              "2 = paket to'g'ri lekin yurish to'liq emas (yoki buyruq xato)."))
    v.add_argument("folder", metavar="papka", help="runtime paketi papkasi")
    v.add_argument("--json", action="store_true", dest="as_json",
                   help="mashina o'qiydigan DETERMINISTIK chiqish (papka yo'li va vaqt YO'Q)")
    return p


def _write(stream, text: str) -> None:
    """Matnni yozadi; kodlash imkoni bo'lmasa belgini ALMASHTIRADI.

    ⚠️ NEGA KERAK: Windows konsoli cp1252 da ishlaydi va hisobot matnida ASCII bo'lmagan
       belgi bor (uzun tire, o'zbekcha harflar). Kodlash xatosi bu yerda ISTISNO bo'lib
       chiqsa, operator XULOSANI umuman ko'rmay qolardi va chiqish kodi 1 ham, 0 ham emas,
       kutilmagan qiymat bo'lardi — ya'ni skript uchun ZIDDIYAT. Belgini almashtirish
       hukmni SAQLAB qoladi."""
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(enc, "replace").decode(enc, "replace"))


def human_report(report: Report, *, folder: str) -> str:
    """Odam o'qiydigan hisobot: har tekshiruv uchun OK/NUQSON va SABAB.

    ⚠️ HAMMA tekshiruv ko'rsatiladi, faqat yiqilganlari EMAS: «nima tekshirilmagani» ham
       javobning bir qismi, va bajarilmagan tekshiruv `NUQSON` bo'lib turadi (fail-closed).
    ⚠️ Tartib `CHECK_NAMES` bilan qulflangan, ya'ni ikki yurishning chiqishini qatorga qator
       solishtirish mumkin."""
    satrlar = [
        f"Runtime paketi: {folder}",
        f"Hisobot sxemasi: {REPORT_VERSION}",
        # ⚠️ YURISH HOLATI SARLAVHADA: u tekshiruvlarning natijasi EMAS, paketning O'Z e'loni
        #    (tekshirilgan) va operator uni birinchi qarashda ko'rishi kerak. O'qilmasa —
        #    `NOMA'LUM`, «muvaffaqiyatli» EMAS.
        f"Yurish holati (overall): {report.overall or 'NOMA`LUM'}",
        "",
    ]
    kenglik = max(len(n) for n in CHECK_NAMES)
    for c in report.checks:
        belgi = MARK_OK if c.ok else MARK_BAD
        satrlar.append(f"  {belgi:<9} {c.name:<{kenglik}}  {c.detail}")
    satrlar.append("")
    yiqilgan = [c for c in report.checks if not c.ok]
    if report.ok and report.overall != OVERALL_SUCCESS:
        # ⚠️ UCHINCHI XULOSA: fayllar butun, lekin yurishning O'ZI to'liq tugamagan. Bu
        #    «hammasi o'tdi» EMAS: shu matn bilan operator paketni keyingi bosqichga
        #    olib bormaydi, sababini `errors.json` dan o'qiydi.
        satrlar.append(f"XULOSA: PAKET TO'G'RI ({len(report.checks)} tekshiruv o'tdi), LEKIN "
                       f"YURISH TO'LIQ EMAS: overall={report.overall or 'NOMA`LUM'}. "
                       "TO'XTASH sharti: yiqilgan bo'limlarning sababini `errors.json` dan "
                       "o'qing, paket keyingi qadamga O'TMAYDI.")
    elif report.ok:
        satrlar.append(f"XULOSA: HAMMASI O'TDI ({len(report.checks)} tekshiruv). "
                       "⚠️ Bu yig'uvchining 1C da ISHLAGANINI isbotlamaydi — paket BAYTLARI "
                       "shartnomaga mos, runtime holati esa RUNTIME-UNKNOWN.")
    else:
        satrlar.append(f"XULOSA: NUQSON BOR ({len(yiqilgan)} / {len(report.checks)} tekshiruv "
                       "yiqildi). FAIL-CLOSED: paket keyingi qadamga O'TMAYDI.")
    return "\n".join(satrlar) + "\n"


def main(argv: list[str] | None = None, *, out=None, err=None) -> int:
    """Kirish nuqtasi. `out`/`err` — testlar uchun; standarti `sys.stdout`/`sys.stderr`.

    ⚠️ ISTISNO TASHLAMAYDI: har qanday nuqson chiqish kodiga aylanadi, chunki operator
       skripti kodni o'qiydi. Argparse ning O'Z xatosi (`SystemExit(2)`) esa AYNAN 2 bo'lib
       qaytadi — buyruq xatosini paket hukmidan ajratish shartnomaning bir qismi."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    parser = build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as e:
        # ⚠️ `--help` ham `SystemExit(0)` beradi va u NUQSON emas: kod o'zgarishsiz qaytadi.
        kod = e.code
        return EXIT_USAGE if kod not in (EXIT_OK, None) else EXIT_OK

    if args.command != VALIDATE_CMD:                    # `required=True` buni imkonsiz qiladi
        _write(err, f"noma'lum buyruq: {args.command!r}\n")
        return EXIT_USAGE

    report = validate_runtime_bundle(args.folder)
    if args.as_json:
        _write(out, report_to_json_text(report))
    else:
        _write(out, human_report(report, folder=args.folder))
    # ⚠️ UCH HOLATLI HUKM (modul docstringiga qarang). Tartib MUHIM: paket noto'g'ri bo'lsa
    #    uning e'lon qilgan holati haqida gapirishdan foyda yo'q — `overall` ning O'ZI ham
    #    shu paketdan keladi.
    if not report.ok:
        return EXIT_PROBLEM
    # ⚠️ `!= SUCCESS` deb yozilgan, `in (PARTIAL, FAILED)` deb EMAS: holat NOMA'LUM (`None`)
    #    bo'lsa ham javob `0` bo'lmasligi kerak (fail-closed).
    if report.overall != OVERALL_SUCCESS:
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":            # pragma: no cover — modul import qilinganda ishlamaydi
    raise SystemExit(main())
