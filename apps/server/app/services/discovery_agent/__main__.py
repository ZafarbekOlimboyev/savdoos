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

PROG = "python -m app.services.discovery_agent"


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
    p.add_argument("--version", action="store_true", help="versiyani chiqarib chiqish")
    return p


def main(argv: list[str] | None = None, *, out=None, err=None, scan=None, now=None,
         runner=None, clock=None, analyzer=None, launcher=None) -> int:
    """Kirish nuqtasi. ⚠️ Hamma tashqi bog'liqlik ALMASHTIRILADI (testlar oyna ochmaydi).

    `scan` — muhit skaneri, `now` — soat, `runner` — 1C ni ishga tushiruvchi
    (`collector_bridge.Runner`), `clock` — ko'prikning monoton soati, `analyzer` — analitik,
    `launcher` — oyna ochuvchi.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
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

    model = agent_ui.UiModel(parent_dir=parent, bundle_dir=bundle_dir)
    if scan is not None:
        model.scan = scan
    if runner is not None:
        model.runner = runner
    if clock is not None:
        model.clock = clock
    if analyzer is not None:
        model.analyzer = analyzer
    if now is not None:
        model.now = now
    elif iso_timestamp is not None:
        # ⚠️ `--timestamp` berilsa soat UMUMAN o'qilmaydi: takrorlanadigan yurish uchun shart.
        model.now = lambda: iso_timestamp
    model.on_progress = lambda holat: print(f"holat: {holat}", file=out)

    print(f"{AGENT_NAME} {AGENT_VERSION} · {agent_ui.READ_ONLY_LABEL}", file=out)
    model.refresh_environment()
    print(model.install_line(), file=out)
    print(model.target_line(), file=out)

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
        print(st.failure_meaning(natija.state), file=err)
    return EXIT_CANNOT_RUN if natija.code in _CANNOT_RUN_CODES else EXIT_FAILED_RUN


if __name__ == "__main__":  # pragma: no cover - qobiq kirish nuqtasi
    raise SystemExit(main())
