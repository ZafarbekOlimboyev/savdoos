# -*- coding: utf-8 -*-
"""Portable yig'ma uchun KIRISH SKRIPTI — `BinOSDiscoveryAgent.exe` shu fayldan boshlanadi.

NEGA ALOHIDA FAYL: PyInstaller `python -m <paket>` ni emas, SKRIPTni yig'adi. Shu bois
kirish nuqtasi `app.services.discovery_agent.__main__.main` ga YUPQA o'ram bo'lib qoladi —
mantiq shu yerda TAKRORLANMAYDI, aks holda yig'ma va manba bir-biridan ajralib ketardi
(brief: source ↔ packaged parity).

⚠️ CHIQISH KODI SHARTNOMASI O'ZGARMAYDI va u `__main__` dan AYNAN ko'chadi:
       0 — yurish yakunlandi va natija paketi tekshiruvdan o'tdi (`COMPLETE`);
       1 — yurish YIQILDI (`FAILED_*`) — bu ham JAVOB, natija papkasi sabab bilan qoladi;
       2 — YURGIZIB BO'LMADI (buyruq xatosi, papka yo'q, `tkinter` yo'q).

⚠️ OPERATORGA PYTHON TRACEBACK CHIQMAYDI: yig'ilgan ilovada kutilmagan istisno ham qisqa,
   o'zbekcha xabarga aylanadi va chiqish kodi `2` bo'ladi. Sabab: operator uchun
   `Traceback (most recent call last)` hech qanday ma'no bermaydi va u qo'rqitadi.
   ⚠️ Xato MATNI YO'QOLMAYDI — u `stderr` ga bir qator bo'lib chiqadi va kutilmagan
   istisno turi ham ko'rsatiladi, aks holda nosozlikni topish imkonsiz bo'lardi.

⚠️ YO'LGA TAYANMAYDI: bu skript joriy papkaga (`cwd`), repo joylashuviga yoki
   `sys.path` ga QO'LDA hech narsa qo'shmaydi. Yig'mada hamma modul ichida bo'ladi.
"""
from __future__ import annotations

import sys

#: ⚠️ `__main__` nomi ataylab: yig'mada ham manbada ham AYNI modul ishlaydi.
from app.services.discovery_agent.__main__ import EXIT_CANNOT_RUN, main


def _run() -> int:
    try:
        return main()
    except SystemExit as e:                     # argparse / main o'zi chiqargan kod
        kod = e.code
        return 0 if kod in (0, None) else (kod if isinstance(kod, int) else EXIT_CANNOT_RUN)
    except KeyboardInterrupt:
        sys.stderr.write("\nOperator to'xtatdi.\n")
        return EXIT_CANNOT_RUN
    except BaseException as e:                  # noqa: BLE001 - oxirgi to'siq
        # ⚠️ Operator traceback KO'RMAYDI, lekin xato TURI va matni ko'rinadi.
        # ⚠️⚠️ OXIRGI TO'SIQNING O'ZI YIQILMASLIGI SHART: istisno matnida cp1252'ga
        #      sig'maydigan belgi bo'lishi mumkin (yo'l, 1C xatosi, kirill). Ilgari bu
        #      yerda XOM `sys.stderr.write` turardi, ya'ni `__main__` dagi kodlash
        #      himoyasidan TASHQARIDA edi va aynan oxirgi to'siq `UnicodeEncodeError`
        #      berib operatorni xabarsiz qoldirishi mumkin edi.
        xabar = ("Agent ishga tushmadi: kutilmagan ichki xato "
                 f"({type(e).__name__}: {e}).\n"
                 "Keyingi qadam: bu xabarni va natija papkasini (agar paydo bo'lgan "
                 "bo'lsa) ishlab chiquvchiga uzating.\n")
        try:
            sys.stderr.write(xabar)
        except UnicodeEncodeError:
            kod = getattr(sys.stderr, "encoding", None) or "ascii"
            sys.stderr.write(xabar.encode(kod, "replace").decode(kod, "replace"))
        except Exception:      # noqa: BLE001 - oqim yopilgan bo'lsa ham kod qaytadi
            pass
        return EXIT_CANNOT_RUN


if __name__ == "__main__":
    sys.exit(_run())
