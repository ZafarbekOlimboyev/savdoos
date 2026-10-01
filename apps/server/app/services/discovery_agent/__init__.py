# -*- coding: utf-8 -*-
"""BinOS 1C Discovery AGENTI — operator ishga tushiradigan FAQAT-O'QISH quvuri.

Bu paket Phase 3/4 yadrosini (`..discovery_1c`) CHAQIRADI. Yadro mantiqi (validator, graf,
analitik, zond allowlisti, redaksiya, hisobot) BU YERDA QAYTA YOZILMAYDI — qayta yozish
regressiya bo'ladi: ikki nusxa bir kun bir-biridan ajralib ketadi va qaysi biri haqiqat
ekani aniqlanmay qoladi. Agent qatlami faqat QADAMLAR TARTIBINI, MUHIT SKANERINI va
OPERATOR BILAN MULOQOTNI qo'shadi.

QAT'IY CHEGARALAR (buzilishi — nuqson, sozlama emas):
  · DEFAULT va YAGONA rejim — FAQAT O'QISH. Agent `Записать`/`Провести`/`Удалить` qilmaydi,
    biznes qatorini ham, metadatani ham o'zgartirmaydi, hujjat yaratmaydi, konstanta
    o'rnatmaydi, tarozi bilan almashmaydi, o'zboshimcha BSL yoki so'rov bajarmaydi.
  · Yashirin saqlash YO'Q · avtoyuklanish YO'Q · Windows xizmati YO'Q · yashirin xulq YO'Q.
    Faqat OPERATOR ishga tushirganda ishlaydi va ishini tugatib chiqadi.
  · OCHIQ MATNLI KREDENSIAL SAQLANMAYDI va parol BUYRUQ SATRIGA QO'YILMAYDI (u jarayon
    ro'yxatida ko'rinadi). Autentifikatsiya kerak bo'lsa — `FAILED_AUTH_REQUIRED` va
    `watch_folder` yo'li taklif qilinadi.
  · TARMOQ YO'Q: bu paketda `socket`/`requests`/`urllib`/`http.client` importi BO'LMAYDI.
    Analitik DETERMINISTIK va LOKAL; cloud AI YO'Q.
  · TASHQI KUTUBXONA YO'Q — faqat stdlib (reestr uchun `winreg`, UI uchun `tkinter`).
    Sabab: do'kon kompyuterida Python o'rnatish talab qilinmasligi kerak va `pywin32`
    o'rnatilmagan.
  · AI `VERIFIED` BERMAYDI; `HUMAN_CONFIRMED` faqat operator tasdig'idan tug'iladi.
  · Sanoqlar JSON'da MATN. Bir xil kirish — AYNAN bir xil bayt (determinizm).

⚠️⚠️ RUNTIME HOLATI: bu mashinada 1C UMUMAN O'RNATILMAGAN (`1cv8.exe` yo'q, COM klasslari
     ro'yxatda yo'q, `pywin32` yo'q). Shu bois: (1) COM yo'li MVP da QURILMAYDI — u
     «ishlamaydi» emas, «TEKSHIRIB BO'LMAYDI» va matritsada `RUNTIME-UNKNOWN`; (2) muhit
     aniqlash kodi HAQIQIY o'rnatmaga qarshi SINALMAGAN — faqat SINTETIK reestr va fayl
     tizimi fiksturalariga qarshi; (3) integratsiya yo'llari («ishlaydi» DEMAYMIZ)
     `RUNTIME-UNKNOWN` deb belgilanadi.

Natija papkasi (`binos-discovery-<timestamp>/`):

    agent_status.json              agent yurishi (`binos-agent-run-v1`)
    environment.json               muhit skaneri (`binos-agent-env-v1`)
    agent_manifest.json            BUTUN papkaning sha256 manifesti
    discovery_ai_candidates.json   analitik nomzodlari (`discovery_1c.review`)
    discovery_report.md            odam o'qiydigan hisobot
    bundle/                        Phase 4 runtime paketi — O'ZGARMAGAN holda

⚠️⚠️ NEGA `bundle/` OSTKI PAPKA: Phase 4 runtime paketining O'Z `manifest.json` i bor. Agar
     agent ham ildizda `manifest.json` yozsa — BIR XIL NOM, IKKI XIL SXEMA; Phase 4 da aynan
     shu nuqson butun paketni rad etgan edi. Shu bois Phase 4 paketi tegilmasdan `bundle/`
     ichida yashaydi, agentning manifesti esa `agent_manifest.json` deb ATALADI.
"""
from __future__ import annotations

#: Agent o'zini shunday ataydi. ⚠️ `UNVERIFIED` ATAYLAB: agent birorta HAQIQIY 1C
#: o'rnatmasiga qarshi ishlatilmagan, demak versiya raqamining o'zi ham da'vo bo'lmasin.
AGENT_NAME = "BinOSDiscoveryAgent"
AGENT_VERSION = "0.1.0-UNVERIFIED"

#: Sxema nomlari — artefakt FAYLLARINING shartnomasi. Yangi maydon faqat versiya oshganda.
RUN_VERSION = "binos-agent-run-v1"
ENV_VERSION = "binos-agent-env-v1"
MANIFEST_VERSION = "binos-agent-manifest-v1"

#: Natija papkasi nomining boshlanishi: `binos-discovery-<timestamp>`.
RESULT_DIR_PREFIX = "binos-discovery-"

#: Artefakt nomlari. ⚠️ `AGENT_MANIFEST_FILE` ataylab `manifest.json` EMAS — modul
#: docstring'idagi «bir xil nom, ikki xil sxema» sababiga qarang.
AGENT_STATUS_FILE = "agent_status.json"
ENVIRONMENT_FILE = "environment.json"
AGENT_MANIFEST_FILE = "agent_manifest.json"
AI_CANDIDATES_FILE = "discovery_ai_candidates.json"
REPORT_FILE = "discovery_report.md"

#: Phase 4 paketi yashaydigan OSTKI papka (ichidagi fayllar O'ZGARTIRILMAYDI).
BUNDLE_SUBDIR = "bundle"

#: Agentning O'Z artefaktlari (Phase 4 paketidan TASHQARI).
AGENT_ARTIFACTS: tuple[str, ...] = (
    AGENT_STATUS_FILE, ENVIRONMENT_FILE, AGENT_MANIFEST_FILE, AI_CANDIDATES_FILE, REPORT_FILE,
)

#: Integratsiya yo'llari. ⚠️ Operator uchun bu BITTA workflow: UI faqat «Start Discovery»
#: ko'rsatadi, yo'l tanlash agent ICHIDA bo'ladi.
#:   `batch_execute` — PRIMARY: auditdan o'tgan AYNI `.epf` paketli rejimda
#:                     (`1cv8.exe ENTERPRISE /F<baza> /Execute <epf> /C<params>`),
#:                     COM YO'Q, o'zboshimcha kod YO'Q, PAROL BUYRUQ SATRIDA YO'Q.
#:   `watch_folder`  — FALLBACK: operator `.epf` ni O'Z 1C sessiyasida bir marta ochadi
#:                     (kirish oynasini 1C ning O'ZI ko'rsatadi — agent sirni KO'RMAYDI),
#:                     agent esa chiqish papkasini kuzatadi.
#: ⚠️ Ikkisi ham `RUNTIME-UNKNOWN`: bu mashinada 1C yo'q, demak hech biri sinalmagan.
ROUTE_BATCH_EXECUTE = "batch_execute"
ROUTE_WATCH_FOLDER = "watch_folder"
ROUTES: tuple[str, ...] = (ROUTE_BATCH_EXECUTE, ROUTE_WATCH_FOLDER)
