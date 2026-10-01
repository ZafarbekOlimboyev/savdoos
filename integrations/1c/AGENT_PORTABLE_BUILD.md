# AGENT PORTABLE BUILD — `BinOSDiscoveryAgent` ni do'kon kompyuteriga yetkazish

Manba: `apps/server/app/services/discovery_agent/` (`__main__.py`, `ui.py`, `result_package.py`,
`detector.py`, `states.py`, `status.py`) + yadro `apps/server/app/services/discovery_1c/`.
Darvoza testi: `apps/server/tests/test_agent_result_package.py`.

---

## 0 · HOLAT — BIR OG'IZ SO'Z BILAN

> **Hech biri HOZIR QURILMAGAN.** Na `.exe`, na portable papka. Bu hujjat IKKI yo'lni
> tavsiflaydi va ularning TALABLARINI va XAVFLARINI yozadi.

| nima | holat |
|---|---|
| `BinOSDiscoveryAgent.exe` (PyInstaller onefile) | **QURILMAGAN** — `pyinstaller` bu mashinada O'RNATILMAGAN |
| portable papka (embeddable Python + agent kodi) | **QURILMAGAN** — embeddable arxiv yuklab olinmagan (tarmoq talab qiladi) |
| stdlib-only dizayn (qurilish uchun ASOS) | **BAJARILGAN** — kod faqat standart kutubxona + `tkinter` ishlatadi, test bilan qulflangan |
| agentning 1C bilan ishlashi | `RUNTIME-UNKNOWN` — bu mashinada 1C:Enterprise umuman o'rnatilmagan |

⚠️ «Qurildi», «sinaldi», «ishlaydi» degan jumla bu hujjatda YO'Q va bo'lmaydi: qurilmagan
narsani qurilgan deb aytish — keyingi bosqichdagi hamma qarorni buzadi.

---

## 1 · BU MASHINADA O'LCHANGAN HOLAT (taxmin EMAS)

| nima | o'lchov natijasi |
|---|---|
| Python (venv) | **3.12.10** (`apps/server/.venv`) |
| `tkinter` | **BOR** |
| `pyinstaller` | **YO'Q** (o'rnatilmagan) |
| `pywin32` | **YO'Q** (o'rnatilmagan) |
| 1C:Enterprise | **YO'Q** — `1cv8.exe` / `1cestart.exe` / `ibcmd.exe` PATH da yo'q |
| COM klasslari | `V83.COMConnector`, `V82.COMConnector`, `V83.Application`, `V82.Application` — ro'yxatda YO'Q |

⚠️ **`.venv` GA PAKET O'RNATILMAYDI.** Shu virtual muhit boshqa sessiyalar bilan
BO'LISHILADI: unga `pyinstaller` (yoki boshqa narsa) o'rnatish boshqa ishni buzishi mumkin.
Qurish kerak bo'lganda **ALOHIDA**, faqat shu ish uchun ochilgan muhitdan foydalaniladi
(2-variantning 2-qadamiga qarang).

---

## 2 · NEGA PORTABLE QILISH OSON — stdlib-only DIZAYN

Agent ATAYLAB faqat **standart kutubxona (stdlib) + `tkinter`** bilan yozilgan:

| ehtiyoj | nima ishlatiladi | nima ISHLATILMAYDI |
|---|---|---|
| reestrni o'qish | `winreg` (stdlib, Windows) | `pywin32` — **o'rnatilmagan va TAQIQ** |
| oyna | `tkinter` (stdlib) | Qt / wx / web view |
| xeshlar, JSON, yo'llar | `hashlib`, `json`, `os`, `re`, `dataclasses` | tashqi serializator |
| tarmoq | **HECH NARSA** — `socket`/`urllib`/`requests`/`http.client` importi YO'Q | cloud AI, telemetriya |

Bundan kelib chiqadigan amaliy natija: **yig'ma kichik va bir xil** — ortiqcha ikkilik
kengaytmalar, DLL va «kerakli paket topilmadi» xatolari YO'Q. Aynan shu sabab portable
papka varianti (2-variant) HAQIQATDA ishlaydigan yo'l bo'la oladi.

⚠️ Bu dalil statik test bilan qulflangan (`test_agent_paketida_TASHQI_kutubxona_YOQ`,
`test_agent_paketida_TARMOQ_importi_YOQ`): agentga tashqi kutubxona kirsa — to'plam qizil
bo'ladi, hujjat esa jimgina eskirib qolmaydi.

---

## 3 · DO'KON KOMPYUTERIDA PYTHON O'RNATISH TALAB QILINMASLIGI QANDAY TA'MINLANADI

Uchta mustaqil shart, uchovi ham BAJARILISHI kerak:

1. **Interpretator yig'ma ichida keladi.** 1-variantda u `.exe` ichiga qo'shiladi,
   2-variantda `python-3.12.x-embed-amd64` papkasi bilan yonma-yon turadi. Ikki holatda ham
   do'kon kompyuterida o'rnatuvchi (`installer`) ishlatilmaydi, `PATH` o'zgartirilmaydi,
   reestrga yozilmaydi.
2. **Tashqi paket kerak emas** (2-bo'lim): `pip install` qadami YO'Q, demak do'konda
   internet ham, `pip` ham talab qilinmaydi.
3. **Yozish faqat operator bergan papkaga.** Agent natijani `--result-dir` (yoki oynada
   tanlangan) papkaga yozadi. `Program Files` ga, `AppData` ga, reestrga va avtoyuklanishga
   HECH NARSA yozilmaydi — shu bois administrator huquqi ham kerak emas.

⚠️ Tekshirish usuli (qurilgandan keyin BAJARILADI, hozir BAJARILMAGAN): Python umuman
o'rnatilmagan toza Windows mashinasida yig'mani ishga tushirib ko'rish. Bu mashinada bunday
tekshiruv o'tkazilmagan.

---

## 4 · 1-VARIANT — `BinOSDiscoveryAgent.exe` (PyInstaller, onefile)

**Natija:** bitta fayl — `BinOSDiscoveryAgent.exe`.

### Talablar
- Windows (yig'ma QAYSI OS da qurilsa, SHU OS uchun chiqadi — kross-kompilyatsiya YO'Q);
- Python 3.12 (qurish mashinasida), **alohida** virtual muhit;
- `pyinstaller` (qurish mashinasida; do'kon kompyuterida KERAK EMAS);
- `tkinter` qurish mashinasidagi Python bilan birga kelishi SHART.

### Qadamlar
```bat
rem 1) ALOHIDA muhit — `apps\server\.venv` GA TEGMANG (u bo'lishilgan)
py -3.12 -m venv C:\tmp\agent-build
C:\tmp\agent-build\Scripts\python -m pip install pyinstaller

rem 2) agentni bitta faylga yig'ish (ildiz: apps\server)
cd apps\server
C:\tmp\agent-build\Scripts\pyinstaller ^
    --onefile --noconsole --name BinOSDiscoveryAgent ^
    --paths . ^
    --hidden-import app.services.discovery_agent.ui ^
    --hidden-import app.services.discovery_agent.result_package ^
    app\services\discovery_agent\__main__.py

rem 3) natija
dir dist\BinOSDiscoveryAgent.exe
```

### Tekshirish (qurilgandan keyin)
```bat
dist\BinOSDiscoveryAgent.exe --version
dist\BinOSDiscoveryAgent.exe --headless <kuzatiladigan-papka> --result-dir <natija-papkasi>
```
Chiqish kodi: `0` — yurish yakunlandi va paket tekshiruvdan o'tdi · `1` — yurish yiqildi
(sabab hisobotda) · `2` — yurish BOSHLANMADI (buyruq xatosi, papka yo'q, quvur ulanmagan).

### XAVFLAR
| xavf | nima bo'ladi | nima qilinadi |
|---|---|---|
| **Antivirus** `--onefile` yig'masini bloklaydi yoki karantinga oladi | do'konda `.exe` ishga tushmaydi, sabab ko'rinmaydi | 2-variantga o'tiladi; imzo (code signing) masalasi alohida hal qilinadi |
| **Imzo yo'q** — SmartScreen ogohlantiradi | operator «Windows protected your PC» oynasini ko'radi va qo'rqadi | operator hujjatida AVVALDAN yoziladi; uzoq muddatli yechim — sertifikat |
| `--onefile` har ishga tushishda vaqtinchalik papkaga ochiladi | sekin start; `%TEMP%` to'lishi | `--onedir` yoki 2-variant |
| Yashirin import topilmaydi (`ModuleNotFoundError`) | yig'ma ishga tushmaydi | `--hidden-import` ro'yxati yuqorida; har yangi modul qo'shilganda YANGILANADI |
| `tkinter` qurish muhitida yo'q | oyna rejimisiz `.exe` chiqadi | qurishdan oldin `python -c "import tkinter"` bilan tekshiriladi |
| Qurish mashinasiga `pyinstaller` o'rnatish | **bo'lishilgan `.venv` buzilishi** | ALOHIDA muhit (1-qadam) — `apps\server\.venv` ga TEGMAYDI |

⚠️ Bu varianti **BU MASHINADA SINALMAGAN**: `pyinstaller` o'rnatilmagan va o'rnatilmaydi.

---

## 5 · 2-VARIANT — PORTABLE PAPKA (embeddable Python + agent kodi) · **BRIEF QABUL QILADI**

**Natija:** bitta papka, ko'chirib qo'yiladi va shunchaki ishlaydi.

```
BinOSDiscoveryAgent\
    python\                     <- python-3.12.x-embed-amd64 (ochilgan arxiv)
        python.exe
        python312.zip
        python312._pth          <- `app` ildizi shu yerda ko'rsatiladi
        tcl\ ... tkinter DLL lari
    app\                        <- agent kodi (quyidagi ro'yxat)
    Agentni ishga tushirish.bat
    OQING.txt                   <- operator uchun qisqa yo'riqnoma
```

### Talablar
- `python-3.12.x-embed-amd64.zip` (python.org dan, bir marta, QURISH mashinasida yuklanadi);
- agent kodi: `app/services/discovery_agent/` + `app/services/discovery_1c/` +
  `app/services/migrator_1c/bundle.py` (yadro shu modullarni ishlatadi) + har bir papkadagi
  `__init__.py`;
- **tashqi paket YO'Q** — `pip` qadami UMUMAN yo'q.

### Qadamlar
```bat
rem 1) embeddable Python ni papkaga ochish
mkdir BinOSDiscoveryAgent\python
tar -xf python-3.12.10-embed-amd64.zip -C BinOSDiscoveryAgent\python

rem 2) agent kodini ko'chirish (faqat kerakli modullar)
robocopy apps\server\app\services\discovery_agent BinOSDiscoveryAgent\app\services\discovery_agent /E
robocopy apps\server\app\services\discovery_1c    BinOSDiscoveryAgent\app\services\discovery_1c /E
robocopy apps\server\app\services\migrator_1c     BinOSDiscoveryAgent\app\services\migrator_1c /E

rem 3) python312._pth ga ildizni qo'shish (satr: `..`), keyin ishga tushirgich:
rem    Agentni ishga tushirish.bat  ->
rem    %~dp0python\python.exe -m app.services.discovery_agent
```

### XAVFLAR
| xavf | nima bo'ladi | nima qilinadi |
|---|---|---|
| **embeddable yig'mada `tkinter` BO'LMAYDI** | oyna ochilmaydi | `tcl/`, `tkinter/` va `_tkinter.pyd` to'liq Python o'rnatmasidan QO'LDA ko'chiriladi; ko'chirilmasa agent `--headless` rejimida BARIBIR ishlaydi (`ui.py` import himoyalangan va ANIQ xato beradi) |
| `python312._pth` noto'g'ri | `ModuleNotFoundError: app` | `._pth` da ildiz (`..`) ko'rsatiladi; `sys.path` ni koddan o'zgartirish YO'Q |
| Papkani ko'chirishda fayl tushib qolishi | tushunarsiz import xatosi | papka bilan birga `sha256` ro'yxati tarqatiladi |
| Bitlik mos kelmasligi (x86 vs x64) | hozircha ahamiyatsiz: COM ishlatilmaydi | COM yo'li MVP da QURILMAYDI (`AGENT_INTEGRATION_MATRIX.md`, 2-qator) |
| Operator papka ichidagi faylni tahrirlashi | xulq o'zgaradi, iz qolmaydi | `OQING.txt` da ogohlantirish; natija paketi O'ZI xeshlangan (`agent_manifest.json`) |

⚠️ Bu varianti ham **BU MASHINADA SINALMAGAN**: embeddable arxiv yuklab olinmagan.

---

## 6 · IKKI VARIANT SOLISHTIRILGANDA

| o'lchov | 1-variant (`.exe`) | 2-variant (portable papka) |
|---|---|---|
| operator uchun qulaylik | bitta fayl | bitta papka |
| antivirus xavfi | **YUQORI** (onefile ochilishi) | past (oddiy `python.exe`) |
| qurish bog'liqligi | `pyinstaller` kerak | arxivni ochish yetarli |
| `tkinter` | odatda avtomat qo'shiladi | QO'LDA ko'chiriladi |
| nosozlikni topish | qiyin (ichini ko'rib bo'lmaydi) | oson (kod ko'rinadi) |
| brief qabul qiladimi | ha | **ha** — brief ikkinchisini ATAYLAB ruxsat etadi |

**Tavsiya:** birinchi do'kon uchun **2-variant**. Sababi uchta: antivirus xavfi past, qurish
uchun tashqi paket kerak emas (`.venv` ga tegilmaydi) va nosozlik bo'lganda sabab ko'rinadi.
`.exe` keyinroq, imzo masalasi hal bo'lganda qiziq bo'ladi.

---

## 7 · HAR IKKI VARIANTGA TEGISHLI QAT'IY CHEGARALAR

- **Agent FAQAT operator ishga tushirganda ishlaydi.** Avtoyuklanish YO'Q, Windows xizmati
  YO'Q, rejalashtirilgan topshiriq YO'Q, reestrga yozish YO'Q. Yig'ma skripti ham bularni
  QO'SHMAYDI — statik test (`test_agent_paketida_YASHIRIN_davomiylik_belgilari_YOQ`) kodda
  bunday belgilarni taqiqlaydi.
- **FAQAT O'QISH.** Agent 1C da hech narsa yozmaydi, hujjat yaratmaydi, o'tkazmaydi,
  o'chirmaydi va o'zboshimcha kod bajarmaydi.
- **Parol buyruq satriga QO'YILMAYDI** (u jarayon ro'yxatida ko'rinadi), parol bayrog'i
  UMUMAN mavjud emas. Baza autentifikatsiya talab qilsa — `FAILED_AUTH_REQUIRED` va
  `watch_folder` yo'li taklif qilinadi.
- **Tarmoq YO'Q.** Yig'ma internetga chiqmaydi; analitik deterministik va LOKAL.
- **Natija faqat operator bergan papkaga** yoziladi: `binos-discovery-<timestamp>/`, ichida
  `agent_status.json`, `environment.json`, `agent_manifest.json`,
  `discovery_ai_candidates.json`, `discovery_report.md` va O'ZGARMAGAN Phase 4 paketi
  `bundle/` ostki papkasida.

---

## 8 · NIMA BAJARILGAN va NIMA BAJARILMAGAN (ochiq ro'yxat)

**BAJARILGAN**
- stdlib-only (+`tkinter`) dizayn va uni qulflaydigan statik testlar — portable qilish uchun ASOS;
- `python -m app.services.discovery_agent` kirish nuqtasi, `--headless` rejimi va uch kodli
  chiqish shartnomasi;
- `tkinter` ning HIMOYALANGAN importi — oyna bo'lmasa ham agent `--headless` da ishlaydi;
- natija paketining shakli, manifesti va validatori.

**BAJARILMAGAN**
- `BinOSDiscoveryAgent.exe` QURILMAGAN (`pyinstaller` o'rnatilmagan, `.venv` ga o'rnatilmaydi);
- portable papka QURILMAGAN (embeddable arxiv yuklanmagan);
- Python o'rnatilmagan toza mashinada SINOV o'tkazilmagan;
- antivirus/SmartScreen xulqi TEKSHIRILMAGAN;
- imzo (code signing) YO'Q;
- 1C bilan ishlash har ikki variantda ham `RUNTIME-UNKNOWN`: bu mashinada 1C:Enterprise
  umuman o'rnatilmagan.
