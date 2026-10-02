# -*- coding: utf-8 -*-
"""AGENTNING KIRISH NUQTASI — oyna yoki UI'siz (`--headless`) yurish.

    python -m app.services.discovery_agent                        # operator oynasi
    python -m app.services.discovery_agent --headless <papka>      # UI'siz, kuzatilgan papka
    python -m app.services.discovery_agent --headless <papka> --result-dir <qayerga>
    python -m app.services.discovery_agent --version

⚠️ CHIQISH KODI SHARTNOMA (testda QULFLANGAN) va u `discovery_1c.cli` ning uch kodli
   naqshini TAKRORLAYDI — operator skripti ikki buyruqni bir xil o'qishi kerak:
       0 — yurish yakunlandi va natija paketi tekshiruvdan O'TDI (`COMPLETE`);
       1 — yurish YIQILDI (`FAILED_*` yoki `ABORTED_BY_OPERATOR`) — bu ham JAVOB: natija
           papkasi (bo'lsa) sabab bilan qoladi;
       2 — YURGIZIB BO'LMADI: buyruq xatosi, papka yo'q, `tkinter` yo'q yoki quvur moduli
           bu yig'mada ulanmagan. ⚠️ `1` dan ATAYLAB ajratilgan: «yurish yiqildi» va
           «yurish BOSHLANMADI» operator uchun ikki boshqa vaziyat.

⚠️ SOATNI FAQAT SHU QATLAM O'QIYDI (`ui.utc_now`). Qolgan modullar vaqtni KIRISHDAN oladi —
   shu tufayli ular deterministik. `--timestamp` bilan soat ham chetlab o'tiladi (testlar va
   takrorlanadigan yurish uchun).

⚠️ YASHIRIN XULQ YO'Q: avtoyuklanish yo'q, Windows xizmati yo'q, reestrga yozish yo'q,
   yashirin saqlash yo'q. Agent FAQAT operator ishga tushirganda ishlaydi va ishini tugatib
   CHIQADI. Natija faqat operator bergan papkaga yoziladi (`--result-dir`, standart holda
   joriy papka).

⚠️ KREDENSIAL BUYRUQ SATRIDA YO'Q: parol uchun bayroq ATAYLAB mavjud emas (buyruq satri
   jarayon ro'yxatida ko'rinadi). Baza autentifikatsiya talab qilsa quvur
   `FAILED_AUTH_REQUIRED` ga o'tadi va `watch_folder` yo'lini taklif qiladi.

⚠️ 1C BU MASHINADA YO'Q, shu bois `--headless` ning 1C bilan ishlaydigan qismi
   `RUNTIME-UNKNOWN`. Bu modulning O'ZI (argumentlar, chiqish kodlari, xabarlar) to'liq
   sinaladi.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import AGENT_NAME, AGENT_VERSION
from . import bridge_protocol as bpr
from . import collector_bridge as bridge
from . import one_click as oc
from . import result_package as rp
from . import states as st
from . import ui as agent_ui

#: Chiqish kodlari — nomlari `discovery_1c.cli` dagi bilan AYNI naqsh.
EXIT_OK = 0
EXIT_FAILED_RUN = 1
EXIT_CANNOT_RUN = 2

#: ⚠️ AGENTNING O'ZIDA nuqson (natija papkasi yozilmadi, ichki istisno) — «yurgizib
#: bo'lmadi» (2), «yurish yiqildi» (1) EMAS: `1` paket yoki muhit haqidagi HUKM, bu esa
#: hukm EMAS. Ikkisini bitta kodga qo'shib yuborish nuqsonni oddiy nosozlik qilib ko'rsatardi.
_CANNOT_RUN_CODES = frozenset({agent_ui.CODE_ICHKI_XATO, agent_ui.CODE_PAKET_YOZILMADI})

#: ⚠️ YORDAM MATNIDAGI NOM OPERATOR KO'RGAN NOMGA MOS BO'LISHI KERAK. Yig'ilgan ilovada
#: operator `BinOSDiscoveryAgent.exe` ni yurgizadi, manbadan esa `python -m ...` ishlatiladi —
#: bitta qattiq yozilgan nom ikkisidan BIRINI yolg'on ko'rsatardi. `sys.frozen` ni PyInstaller
#: qo'yadi, shu bois shart yig'mada ROST, manbada YOLG'ON bo'ladi.
#: ⚠️ Nom `argv[0]` dan OLINMAYDI: u to'liq yo'l bo'lishi mumkin va yordam matniga
#: ishlab chiquvchi yoki operator papkasining yo'li tushib qolardi.
PROG_SOURCE = "python -m app.services.discovery_agent"
PROG_FROZEN = "BinOSDiscoveryAgent.exe"
PROG = PROG_FROZEN if getattr(sys, "frozen", False) else PROG_SOURCE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG, add_help=True,
        description=f"{AGENT_NAME} {AGENT_VERSION} — 1C razvedkasi, FAQAT O'QISH.")
    p.add_argument("--headless", metavar="BUNDLE_DIR", default=None,
                   help="UI'siz yurish: kuzatiladigan Phase 4 chiqish papkasi")
    p.add_argument("--result-dir", metavar="PAPKA", default=None,
                   help="natija papkasi QAYERDA qurilsin (standart: joriy papka)")
    p.add_argument("--timestamp", metavar="YYYYMMDDTHHMMSSZ", default=None,
                   help="natija papkasining vaqt qismi (standart: hozirgi UTC)")
    # ⚠️ KUTISH CHEKLI va OPERATOR KO'RADI: `watch_folder` yo'lida agent yig'uvchining
    #    chiqishini kutadi. Cheksiz kutish YO'Q (brief §6C) — shu bois chegara BAYROQ bo'lib
    #    ko'rinadi va standart qiymati ko'prikdan keladi (ikki joyda yozilmaydi).
    p.add_argument("--wait-seconds", metavar="SONIYA", default=None,
                   help=(f"yig'uvchining chiqishini eng ko'p qancha kutish "
                         f"(standart: {int(bridge.DEFAULT_TIMEOUT_SECONDS)}); "
                         f"vaqt tugasa yurish {st.FAILED_TIMEOUT} bilan to'xtaydi"))
    # ── BIR BOSISHLI OQIM (`one_click`) ──────────────────────────────────────────────────
    # ⚠️⚠️ UCHTA BAYROQ QO'SHILDI va har biri ZARUR: `--one-click` — oqimning O'ZI;
    #      `--runs-dir` — QAROR 4 shartnomasi (standart joy aniqlanmasa agent TAXMIN
    #      QILMAYDI, demak operatorda ko'rsatish YO'LI bo'lishi SHART); `--target` — bir
    #      nechta baza bo'lgan mashinada oqimni DAVOM ETTIRISHNING yagona yo'li, chunki
    #      agent bazani O'ZI TANLAMAYDI (noto'g'ri baza butun hisobotni noto'g'ri qiladi).
    # ⚠️ PAROL BAYROG'I QO'SHILMAYDI va bo'lmaydi: buyruq satri jarayon ro'yxatida
    #    ko'rinadi. Parolni 1C ning O'Z oynasi oladi.
    # ⚠️ CHIQISH KODI SHARTNOMASI O'ZGARMAYDI: 0 — `COMPLETE`, 1 — yurish yiqildi,
    #    2 — yurish BOSHLANMADI (buyruq xatosi yoki qaror operatorda).
    p.add_argument("--one-click", action="store_true",
                   help=("operator oqimi: 1C ni aniqlash -> bazani tanlash -> yurish "
                         "papkasini tayyorlash -> yig'uvchining natijasini kutish -> "
                         "tahlil (oyna OCHILMAYDI)"))
    # ⚠️⚠️ YORDAM MATNIDA `%` BELGISI YO'Q (yig'ilgan EXE ni yurgizib topilgan tuzoq
    #      naqshi): argparse yordam matnini `% params` bilan formatlaydi, shu bois
    #      `%LOCALAPPDATA%` yozilsa `--help` ning O'ZI `ValueError` bilan yiqiladi. Muhit
    #      o'zgaruvchisining NOMI (foizsiz) ayni ma'noni beradi. Testda `--help` ning
    #      qurilishi qulflangan.
    p.add_argument("--runs-dir", metavar="PAPKA", default=None,
                   help=(f"yurishlar papkasining ildizi (standart: "
                         f"{bpr.LOCALAPPDATA_ENV} muhit o'zgaruvchisi ichidagi "
                         + "\\".join(bpr.RUNS_SUBPATH) + ")"))
    p.add_argument("--target", metavar="RAQAM", default=None,
                   help=("ma'lumot bazasining RO'YXATDAGI raqami (1 dan boshlab) — bir "
                         "nechta baza bo'lsa tanlovni SIZ qilasiz"))
    p.add_argument("--version", action="store_true", help="versiyani chiqarib chiqish")
    return p


# ── KONSOL KODLASHI ─────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ NEGA BU KERAK (yig'ilgan EXE ni HAQIQATAN yurgizib topilgan nuqson): operator
#      matnlarida `⚠`, `═`, `─` va bir nechta kirill harfi bor — 28 xil belgi `cp1252` ga
#      SIG'MAYDI. Windows'da chiqish qayta yo'naltirilganda (quvur, fayl, ba'zi konsollar)
#      `sys.stdout.encoding` AYNAN `cp1252` bo'ladi va chop etish `UnicodeEncodeError`
#      beradi. Natijada yurish CHOP ETISH paytida uzilib, NATIJA PAKETI UMUMAN
#      YOZILMASDI — ya'ni «operator hech qachon hech narsasiz qolmasin» kafolati
#      HAQIQIY konsolda buzilardi.
# ⚠️ To'plam buni TUTMAGAN: pytest chiqishni UTF-8 bilan ushlaydi. Shu bois bu yerda
#    tuzatish bor VA `tests/test_agent_packaging.py` da cp1252 oqimi bilan test bor.
# ⚠️ IKKI QATLAM, ikkisi ham kerak:
#    (1) `_utf8ga_otkaz` — iloji bo'lsa oqimni UTF-8 ga o'tkazadi, ya'ni belgilar
#        YO'QOLMAYDI (eng yaxshi holat);
#    (2) `_XavfsizOqim` — o'tkazib bo'lmasa (yoki boshqa kodlash bo'lsa) yozish
#        YIQILMAYDI: sig'maydigan belgi almashtiriladi. Chop etish HECH QACHON
#        yurishni to'xtatmaydi.
def _utf8ga_otkaz(oqim) -> None:
    """Oqimni UTF-8 ga o'tkazishga HARAKAT qiladi. Bo'lmasa — jim o'tadi."""
    try:
        oqim.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:          # noqa: BLE001 - oqim almashtirilgan bo'lishi mumkin (testlar)
        pass


class _XavfsizOqim:
    """Yozishda kodlash xatosi bo'lsa ham YIQILMAYDIGAN o'ram.

    ⚠️ Belgini JIMGINA tashlab yubormaydi — `replace` bilan almashtiradi, ya'ni operator
       matnning qolganini KO'RADI va nimadir almashtirilganini ham ko'radi.
    """

    __slots__ = ("_o",)

    def __init__(self, oqim) -> None:
        self._o = oqim

    def write(self, s):
        try:
            return self._o.write(s)
        except UnicodeEncodeError:
            kod = getattr(self._o, "encoding", None) or "ascii"
            return self._o.write(s.encode(kod, "replace").decode(kod, "replace"))

    def flush(self):
        try:
            return self._o.flush()
        except Exception:      # noqa: BLE001 - yopilgan oqim chop etishni to'xtatmasin
            return None

    def __getattr__(self, nom):
        return getattr(self._o, nom)


def _kutish_oqi(args, err):
    """`--wait-seconds` ni o'qiydi. Qaytaradi: soniya yoki `None` (buyruq xatosi).

    ⚠️ FAIL-CLOSED: noto'g'ri yoki nol/manfiy chegara «cheksiz kut» degani EMAS — yurish
       BOSHLANMAYDI. Cheksiz kutish bu agentda umuman mavjud emas.
    ⚠️ Chegara IKKI yo'lda ham (UI'siz va bir bosishli) AYNI qoida bilan o'qiladi: ikkinchi
       nusxa yozilsa, bir kun bir yo'lda cheksiz kutish paydo bo'lardi.
    """
    if args.wait_seconds is None:
        return bridge.DEFAULT_TIMEOUT_SECONDS
    try:
        kutish = float(args.wait_seconds)
    except ValueError:
        kutish = -1.0
    if not kutish > 0:
        print("`--wait-seconds` musbat son bo'lishi kerak — cheksiz kutish YO'Q", file=err)
        return None
    return kutish


def _injektsiya(model, *, scan, runner, clock, sleeper, analyzer, now, iso_timestamp):
    """Tashqi bog'liqliklarni modelga qo'yadi (testlar oyna ochmaydi, soatga qaramaydi).

    ⚠️ IKKI YO'L BIR XIL quriladi: UI'siz yurish ham, bir bosishli oqim ham AYNI
       almashtirishlarni oladi — aks holda bitta yo'l testda soxta soat bilan, ikkinchisi
       haqiqiy soat bilan yurib, to'plam mashinaning tezligiga bog'liq bo'lib qolardi.
    """
    if scan is not None:
        model.scan = scan
    if runner is not None:
        model.runner = runner
    if clock is not None:
        model.clock = clock
    if sleeper is not None:
        model.sleeper = sleeper
    if analyzer is not None:
        model.analyzer = analyzer
    if now is not None:
        model.now = now
    elif iso_timestamp is not None:
        # ⚠️ `--timestamp` berilsa soat UMUMAN o'qilmaydi: takrorlanadigan yurish uchun shart.
        model.now = lambda: iso_timestamp
    return model


def _bir_bosish(args, *, out, err, model) -> int:
    """`--one-click` yo'li: operator oqimini UI'siz yurgizadi.

    ⚠️⚠️ YANGI MANTIQ BU YERDA YO'Q: hamma qadam `one_click.run_one_click` da va u mavjud
         quvurni (`ui.UiModel.start` -> `pipeline` -> `result_package`) chaqiradi. Bu
         funksiya FAQAT bayroqlarni o'qiydi, fazalarni CHOP ETADI va chiqish kodini
         qaytaradi.
    ⚠️ CHIQISH KODI SHARTNOMASI O'ZGARMAYDI: `0` — `COMPLETE`, `1` — yurish yiqildi,
       `2` — yurish BOSHLANMADI (buyruq xatosi yoki QAROR OPERATORDA).
    """
    nishon_raqami = None
    if args.target is not None:
        # ⚠️ RO'YXATDAGI raqam 1 dan boshlanadi (operator ekranda shuni ko'radi), ichkarida
        #    esa indeks 0 dan. Noto'g'ri qiymat — «yurish boshlanmadi» (2), chunki boshqa
        #    bazani tanlab yurish OPERATOR so'ramagan narsa bo'lardi.
        try:
            nishon_raqami = int(args.target) - 1
        except ValueError:
            nishon_raqami = -1
        if nishon_raqami < 0:
            print("`--target` ro'yxatdagi raqam bo'lishi kerak (1 dan boshlab)", file=err)
            return EXIT_CANNOT_RUN

    print(f"{AGENT_NAME} {AGENT_VERSION} · {agent_ui.READ_ONLY_LABEL}", file=out)
    # ⚠️ Operator yurish BOSHLANISHIDAN OLDIN O'ZI nima qilishini ko'radi: «bitta bosishda
    #    avtomatik razvedka» degan taassurot ATAYLAB berilmaydi (`.epf` HALI yig'ilmagan —
    #    yig'uvchini operator O'Z 1C sessiyasida ochadi).
    print(model.route_line(), file=out)
    for qadam in model.operator_steps():
        print(f"  {qadam}", file=out)

    def _faza(h) -> None:
        print(f"faza: {h.phase} — {h.text}", file=out)
        if h.detail:
            print(f"  {h.detail}", file=out)

    try:
        natija = oc.run_one_click(model, runs_root=args.runs_dir,
                                 select_index=nishon_raqami, on_event=_faza,
                                 on_wait=lambda matn: print(matn, file=out))
    except agent_ui.UiError as e:
        # ⚠️ `--target` oraliqdan tashqarida: ro'yxat KO'RSATILADI, jim rad etilmaydi.
        print(agent_ui.xavfsiz_matn(e), file=err)
        for i, yorliq in enumerate(model.target_labels(), start=1):
            print(f"  {i}. {yorliq}", file=err)
        return EXIT_CANNOT_RUN

    if natija.run_id:
        print(f"yurish o'zligi: {natija.run_id}", file=out)
    if natija.run_dir:
        # ⚠️ Papka YO'LI faqat SHU YERDA, faqat operatorning O'Z ekraniga chiqadi: hisobotga
        #    va hujjatga yo'l YOZILMAYDI.
        print(f"yurish papkasi: {natija.run_dir}", file=out)
    if natija.result_dir:
        print(f"natija papkasi: {natija.result_dir}", file=out)
    print(f"xulosa: {natija.state} — {natija.detail}", file=out)
    for p in natija.problems[:20]:
        print(f"  - {p}", file=err)
    if natija.is_complete:
        return EXIT_OK
    # ⚠️ KEYINGI QADAM HAR DOIM CHIQADI: sababsiz (yoki keyingi qadamsiz) xato xabari har
    #    safar qo'ng'iroqqa aylanadi.
    print(f"keyingi qadam: {natija.next_action()}", file=err)
    if natija.waiting_for_operator:
        # ⚠️ Tanlov operatorda: ro'yxat raqamlari bilan ko'rsatiladi va u `--target` ga
        #    beriladi. Agent O'ZI tanlamaydi.
        for i, yorliq in enumerate(model.target_labels(), start=1):
            print(f"  {i}. {yorliq}", file=err)
        return EXIT_CANNOT_RUN
    if natija.run_code in _CANNOT_RUN_CODES:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED_RUN


def main(argv: list[str] | None = None, *, out=None, err=None, scan=None, now=None,
         runner=None, clock=None, sleeper=None, analyzer=None, launcher=None) -> int:
    """Kirish nuqtasi. ⚠️ Hamma tashqi bog'liqlik ALMASHTIRILADI (testlar oyna ochmaydi).

    `scan` — muhit skaneri, `now` — soat, `runner` — 1C ni ishga tushiruvchi
    (`collector_bridge.Runner`), `clock` — ko'prikning monoton soati, `sleeper` — kutish
    chaqiruvi, `analyzer` — analitik, `launcher` — oyna ochuvchi.

    ⚠️ `sleeper` NEGA ALMASHTIRILADI: `watch_folder` yo'lida agent yig'uvchining chiqishini
       KUTADI, test esa haqiqiy soniyalarni kutmasligi kerak. `clock` allaqachon shu sababdan
       kirishda turgan — ikkisini birga bermaslik to'plamni daqiqalarga cho'zardi.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    # ⚠️ Chop etish YURISHNI TO'XTATMASLIGI kerak: yuqoridagi izohga qarang.
    _utf8ga_otkaz(out)
    _utf8ga_otkaz(err)
    out = _XavfsizOqim(out)
    err = _XavfsizOqim(err)
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        # ⚠️ `--help` ham, noma'lum bayroq ham argparse'da `SystemExit` beradi. Ikkisi ham
        #    «yurish boshlanmadi», shu bois `0`/`2` ajratiladi: yordam — operator so'ragan
        #    narsa, noma'lum bayroq — xato.
        return EXIT_OK if e.code in (0, None) else EXIT_CANNOT_RUN

    if args.version:
        print(f"{AGENT_NAME} {AGENT_VERSION}", file=out)
        print("rejim: FAQAT O'QISH · tarmoq: YO'Q · tashqi kutubxona: YO'Q "
              "(stdlib + tkinter)", file=out)
        print("1C integratsiya yo'llari: RUNTIME-UNKNOWN (haqiqiy 1C ga qarshi SINALMAGAN)",
              file=out)
        return EXIT_OK

    parent = args.result_dir if args.result_dir else os.getcwd()
    if not os.path.isdir(parent):
        print("natija papkasi uchun ko'rsatilgan joy topilmadi yoki papka emas", file=err)
        return EXIT_CANNOT_RUN

    iso_timestamp = None
    if args.timestamp is not None:
        # ⚠️ Qisqa shakl QAT'IY talab qilinadi: `result_dir_name` undan ko'proq narsaga ruxsat
        #    beradi (har qanday ASCII nom), lekin kirish nuqtasi vaqtni ISO ga QAYTARISHI
        #    kerak — demak shakl aniq bo'lishi SHART. Noto'g'ri bayroq «yurish boshlanmadi» (2).
        try:
            iso_timestamp = rp.iso_from_compact(args.timestamp)
        except rp.ResultPackageError as e:
            print(str(e), file=err)
            return EXIT_CANNOT_RUN

    # ── BAYROQLARNING MOSLIGI ────────────────────────────────────────────────────────────
    # ⚠️⚠️ `--one-click` va `--headless` BIRGA ISHLAMAYDI va bu ATAYLAB: `--headless
    #      <papka>` «MEN ko'rsatgan papkani kuzat» degani, bir bosishli oqim esa
    #      kuzatiladigan papkani O'ZI egallaydi (yurishning O'Z papkasi, `request.json`
    #      dagi joy). Ikkisini birga qabul qilish «qaysi papka haqiqiy?» degan savolni
    #      tug'dirardi, bittasini jimgina afzal ko'rish esa aynan Phase 4 ni yiqitgan «ikki
    #      haqiqat» naqshi bo'lardi. Shu bois — ANIQ rad etish.
    if args.one_click and args.headless is not None:
        print("`--one-click` va `--headless` birga ishlatilmaydi: bir bosishli oqim "
              "kuzatiladigan papkani O'ZI tayyorlaydi", file=err)
        return EXIT_CANNOT_RUN
    # ⚠️ JIM E'TIBORSIZLIK YO'Q: `--runs-dir`/`--target` faqat bir bosishli oqimda ma'noga
    #    ega. Ularni jimgina tashlab yuborish operatorga «qabul qilindi» degan yolg'on
    #    taassurot berardi.
    for bayroq, qiymat in (("--runs-dir", args.runs_dir), ("--target", args.target)):
        if qiymat is not None and not args.one_click:
            print(f"`{bayroq}` faqat `--one-click` bilan ishlaydi", file=err)
            return EXIT_CANNOT_RUN

    # ── BIR BOSISHLI OQIM ────────────────────────────────────────────────────────────────
    if args.one_click:
        kutish = _kutish_oqi(args, err)
        if kutish is None:
            return EXIT_CANNOT_RUN
        # ⚠️ `bundle_dir` BERILMAYDI: uni `one_click` yurish papkasiga BOG'LAYDI.
        model = agent_ui.UiModel(parent_dir=parent, bundle_dir=None,
                                 watch_timeout_seconds=kutish)
        _injektsiya(model, scan=scan, runner=runner, clock=clock, sleeper=sleeper,
                    analyzer=analyzer, now=now, iso_timestamp=iso_timestamp)
        model.on_progress = lambda holat: print(f"holat: {holat}", file=out)
        model.on_wait = lambda tick: print(tick.human(), file=out)
        return _bir_bosish(args, out=out, err=err, model=model)

    # ── OYNA ─────────────────────────────────────────────────────────────────────────────
    if args.headless is None:
        if launcher is None and not agent_ui.TK_MAVJUD:
            print("tkinter bu muhitda yo'q — oyna ochilmaydi. UI'siz yurish uchun: "
                  f"{PROG} --headless <papka>", file=err)
            return EXIT_CANNOT_RUN
        ochuvchi = launcher if launcher is not None else agent_ui.launch
        try:
            ochuvchi(parent_dir=parent, bundle_dir=None)
        except agent_ui.UiError as e:
            print(agent_ui.xavfsiz_matn(e), file=err)
            return EXIT_CANNOT_RUN
        return EXIT_OK

    # ── UI'SIZ ───────────────────────────────────────────────────────────────────────────
    bundle_dir = args.headless
    if not os.path.isdir(bundle_dir):
        print("`--headless` papkasi topilmadi yoki papka emas", file=err)
        return EXIT_CANNOT_RUN

    # ⚠️ Chegara va almashtirishlar IKKI yo'lda AYNI qoida bilan (yordamchilar yuqorida).
    kutish = _kutish_oqi(args, err)
    if kutish is None:
        return EXIT_CANNOT_RUN

    model = agent_ui.UiModel(parent_dir=parent, bundle_dir=bundle_dir,
                             watch_timeout_seconds=kutish)
    _injektsiya(model, scan=scan, runner=runner, clock=clock, sleeper=sleeper,
                analyzer=analyzer, now=now, iso_timestamp=iso_timestamp)
    model.on_progress = lambda holat: print(f"holat: {holat}", file=out)
    # ⚠️ KUTISH KO'RINADI: bo'sh papkada agent jim turardi va operator «osilgan» deb
    #    o'qirdi. Bu qator kutishni ko'rsatadi va yangi HOLAT yaratmaydi.
    model.on_wait = lambda tick: print(tick.human(), file=out)

    print(f"{AGENT_NAME} {AGENT_VERSION} · {agent_ui.READ_ONLY_LABEL}", file=out)
    model.refresh_environment()
    print(model.install_line(), file=out)
    print(model.target_line(), file=out)
    # ⚠️⚠️ YO'L HAQQONIYLIGI (brief §7): operator yurish BOSHLANISHIDAN OLDIN qaysi yo'l
    #      ketayotganini va O'ZI nima qilishi kerakligini ko'radi. «Bitta bosishda avtomatik»
    #      degan taassurot ATAYLAB berilmaydi.
    print(model.route_line(), file=out)
    for qadam in model.operator_steps():
        print(f"  {qadam}", file=out)

    natija = model.start()
    if natija.result_dir:
        # ⚠️ Papka YO'LI chiqishga faqat SHU YERDA, faqat operatorning O'Z ekraniga chiqadi:
        #    uni bilish operatorga kerak. Hisobot va artefakt matnlarida esa yo'l YO'Q.
        print(f"natija papkasi: {natija.result_dir}", file=out)
    print(f"xulosa: {natija.state} — {natija.detail}", file=out)
    for p in natija.problems[:20]:
        print(f"  - {p}", file=err)
    if natija.state == st.COMPLETE:
        return EXIT_OK
    if st.is_known(natija.state) and st.is_failure(natija.state):
        # ⚠️ Yiqilish MA'NOSI ham chiqadi: «NIMA bo'ldi va NIMA QILISH kerak» (states.py).
        # ⚠️⚠️ HUKM UZATILADI: `FAILED_NO_1C` ning ma'nosi `presence_verdict` ga BOG'LIQ —
        #      `absent` «qaradim va yo'q» (JAVOB), `unknown` «qaray olmadim» (javob YO'Q).
        #      Hukmni uzatmaslik ekranda `environment.json` ga ZID xulosa chiqarardi.
        hukm = model.environment.presence_verdict if model.environment is not None else None
        print(st.failure_meaning(natija.state, presence_verdict=hukm), file=err)
    return EXIT_CANNOT_RUN if natija.code in _CANNOT_RUN_CODES else EXIT_FAILED_RUN


if __name__ == "__main__":  # pragma: no cover - qobiq kirish nuqtasi
    raise SystemExit(main())
