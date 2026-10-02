# AGENT PORTABLE BUILD — `BinOSDiscoveryAgent` ni do'kon kompyuteriga yetkazish

Manba: `apps/server/app/services/discovery_agent/` (`__main__.py`, `ui.py`, `result_package.py`,
`detector.py`, `states.py`, `status.py`) + yadro `apps/server/app/services/discovery_1c/`.
Yig'ma manbasi: `apps/server/packaging/BinOSDiscoveryAgent.spec` + `packaging/binos_agent_entry.py`.
Darvoza testlari: `apps/server/tests/test_agent_result_package.py` (natija paketi),
`apps/server/tests/test_agent_packaging.py` (yig'ma TARKIBI),
`apps/server/tests/test_agent_portability.py` (yig'mani ROSTDAN yurgizish — §8/§9).

---

## 0 · HOLAT — BIR OG'IZ SO'Z BILAN

> **1-VARIANT (`.exe`) QURILDI va YURGIZILDI.** 2-variant (embeddable papka) QURILMAGAN va
> endi KERAK EMAS. 1C bilan ishlash HAMON `RUNTIME-UNKNOWN`.

| nima | holat |
|---|---|
| `BinOSDiscoveryAgent.exe` (PyInstaller **ONE-DIR**) | **QURILDI** — 2026-10-02 (qayta qurildi: bir bosishli oqim modullari qo'shildi), yig'ma repo TASHQARISIDA |
| yig'mani uch xil joydan yurgizish (§8) | **BAJARILDI** — uchovida bir xil natija (3-bo'lim pastda) |
| yig'mani ko'chirib (boshqa yo'lga, kirill nomli papkaga) yurgizish | **BAJARILDI** |
| ishlab chiquvchi yo'li yig'mada bormi (§8) | **YO'Q** — ikkilik qidiruv bilan tekshirildi (9-bo'lim) |
| toza mashinada ishlashi (§9) | **`APPROXIMATED`** — ikkinchi mashina YO'Q, faqat muhit o'zgaruvchilari KESILDI (10-bo'lim) |
| imzo (code signing) | **YO'Q — `unsigned` / IMZOLANMAGAN** (11-bo'lim) |
| portable papka (embeddable Python) | **QURILMAGAN** — kerak emas: `.exe` ishlagani o'lchandi |
| stdlib-only dizayn | **BAJARILGAN** — kod faqat standart kutubxona + `tkinter`, test bilan qulflangan |
| agentning 1C bilan ishlashi | **`RUNTIME-UNKNOWN`** — bu mashinada 1C:Enterprise umuman o'rnatilmagan |

⚠️ Tarqatish qarorini oqlaydigan jumla bu hujjatda YO'Q va bo'lmaydi: yig'ma YURADI,
lekin u HAQIQIY 1C ga qarshi hech qachon sinalmagan va imzolanmagan. Ikki narsa alohida
savol: «dastur ishga tushadimi» (o'lchandi) va «dastur ishini qiladimi» (o'lchanMAGAN).

---

## 1 · BU MASHINADA O'LCHANGAN HOLAT (taxmin EMAS)

| nima | o'lchov natijasi |
|---|---|
| Python (bo'lishilgan `.venv`, manba to'plami uchun) | **3.12.10** (`apps/server/.venv`) |
| Python (IZOLYATSIYALANGAN build muhiti) | **3.12.10, 64 bit** (`MSC v.1943 AMD64`) |
| `pyinstaller` (build muhitida) | **6.22.3** |
| `pyinstaller` (bo'lishilgan `.venv` da) | **YO'Q** — ataylab o'rnatilmagan, tekshirildi |
| `tkinter` | **BOR** — yig'maga ham tushgan (`_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`) |
| `pywin32` | **YO'Q** (o'rnatilmagan va kerak emas) |
| 1C:Enterprise | **YO'Q** — `1cv8.exe` / `1cestart.exe` / `ibcmd.exe` PATH da yo'q |
| COM klasslari | `V83.COMConnector`, `V82.COMConnector`, `V83.Application`, `V82.Application` — ro'yxatda YO'Q |

### ⚠️ BO'LISHILGAN `.venv` IFLOSLANMADI

`apps/server/.venv` boshqa sessiyalar bilan BO'LISHILADI, shu bois unga `pyinstaller`
O'RNATILMADI. Yig'ish uchun ALOHIDA, faqat shu ish uchun ochilgan muhit ishlatildi:

```
C:\Users\Developer\binos-agent-build\buildenv        <- izolyatsiyalangan build muhiti
    Python 3.12.10 64bit · PyInstaller 6.22.3
```

Tekshirish usuli (takrorlanadi): `apps/server/.venv/Scripts/python.exe -c "import PyInstaller"`
→ `ModuleNotFoundError`. Ya'ni bo'lishilgan muhitda yig'uvchi YO'Q.

### ⚠️ YIG'MA REPO TASHQARISIDA

```
C:\Users\Developer\binos-agent-build\
    buildenv\          <- izolyatsiyalangan build muhiti
    build-onedir\      <- PyInstaller ish papkasi (--workpath)
    dist-onedir\       <- TARQATILADIGAN yig'ma (--distpath)
    dist-onefile\      <- SOLISHTIRISH uchun onefile yig'masi (tarqatilMAYDI)
```

Sabab: repo daraxti TOZA qoladi, `.gitignore` o'zgartirilmaydi va yig'ma artefaktlari
hech qachon commit qilinmaydi. Repoda faqat MANBA turadi (`packaging/` ikki fayl).

⚠️ Amaliy natija: CI mashinasida yig'ma BO'LMAYDI, shu bois `test_agent_packaging.py` va
`test_agent_portability.py` dagi yig'maga bog'liq testlar ANIQ SABAB bilan `skip` bo'ladi
(yiqilmaydi). Hujjat halolligini tekshiradigan testlar CI da ham ISHLAYDI.

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
kengaytmalar, DLL va «kerakli paket topilmadi» xatolari YO'Q. Aynan shu sabab yig'ish
BIRINCHI urinishda o'tdi: `warn-BinOSDiscoveryAgent.txt` da majburiy modul yetishmasligi
YO'Q.

⚠️ Bu dalil statik test bilan qulflangan (`test_agent_paketida_TASHQI_kutubxona_YOQ`,
`test_agent_paketida_TARMOQ_importi_YOQ`): agentga tashqi kutubxona kirsa — to'plam qizil
bo'ladi, hujjat esa jimgina eskirib qolmaydi.

---

## 3 · DO'KON KOMPYUTERIDA PYTHON O'RNATISH TALAB QILINMASLIGI QANDAY TA'MINLANADI

Uchta mustaqil shart:

1. **Interpretator yig'ma ichida keladi.** `_internal/python312.dll` + `base_library.zip`
   yig'ma papkasining ichida. Do'kon kompyuterida o'rnatuvchi (`installer`) ishlatilmaydi,
   `PATH` o'zgartirilmaydi, reestrga yozilmaydi.
2. **Tashqi paket kerak emas** (2-bo'lim): `pip install` qadami YO'Q, demak do'konda
   internet ham, `pip` ham talab qilinmaydi.
3. **Yozish faqat operator bergan papkaga.** Agent natijani `--result-dir` (yoki oynada
   tanlangan) papkaga yozadi. `Program Files` ga, `AppData` ga, reestrga va avtoyuklanishga
   HECH NARSA yozilmaydi — shu bois administrator huquqi ham kerak emas.

⚠️ 1 va 3 shartlari O'LCHANDI (8-bo'lim). **2-shart o'lchanMADI**: «do'konda internet
kerak emas» mantiqiy xulosa, chunki yig'mada tarmoq kutubxonasi yo'q — lekin bu haqiqiy
do'kon kompyuterida tekshirilmagan.

---

## 4 · QURILGAN YIG'MA — ANIQ RAQAMLAR

### 4.1 Vosita va versiya

| nima | qiymat |
|---|---|
| yig'uvchi | **PyInstaller 6.22.3** |
| Python | **3.12.10, 64 bit** (`MSC v.1943 AMD64`) |
| build muhiti | `C:\Users\Developer\binos-agent-build\buildenv` (IZOLYATSIYALANGAN) |
| strategiya | **ONE-DIR** (`exclude_binaries=True` + `COLLECT`) |
| UPX | **YO'Q** (`upx=False`) |
| `console` | **`True`** |
| `runtime_hooks` | **BO'SH** |
| imzo | **YO'Q — `unsigned`** (11-bo'lim) |
| qurilgan sana (bu mashinada) | 2026-10-02 (qayta qurilgan) |

### 4.2 NEGA ONE-DIR, NEGA ONEFILE EMAS

ONE-FILE yig'masi ham qurildi (`dist-onefile\BinOSDiscoveryAgent-onefile.exe`,
**10 913 007 bayt**) — lekin TARQATILADIGANI **ONE-DIR**. Uchta sabab:

| sabab | ONE-DIR | ONE-FILE |
|---|---|---|
| **antivirus/SmartScreen shubhasi** | past: oddiy papka, oddiy DLL lar | yuqori: o'zini `%TEMP%` ga OCHADI — bu naqsh zararli dasturlarga xos |
| **har yurishda `%TEMP%` ga yozish** | YO'Q — papkasiga ham hech narsa yozmaydi (o'lchandi, 8.6) | HAR yurishda ~25 MB ochiladi; `%TEMP%` to'lsa yurish yiqiladi |
| **nosozlikni topish** | ichidagi DLL/`.pyd` ko'rinadi, yetishmagani darhol aniq | ichini ko'rib bo'lmaydi |

⚠️ ONE-FILE artefakti darvozalar bilan QOPLANMAGAN: `test_agent_packaging.py` va
`test_agent_portability.py` AYNAN `dist-onedir` ni o'qiydi. Ya'ni onefile fayli
SOLISHTIRISH uchun qoldirilgan o'lchov, tarqatiladigan artefakt EMAS.

### 4.3 QURISH BUYRUG'I (AYNAN)

```bat
rem 0) ALOHIDA muhit — `apps\server\.venv` GA TEGMANG (u bo'lishilgan)
rem    (bir marta bajarilgan; muhit allaqachon bor)
py -3.12 -m venv C:\Users\Developer\binos-agent-build\buildenv
C:\Users\Developer\binos-agent-build\buildenv\Scripts\python.exe -m pip install pyinstaller==6.22.3

rem 1) yig'ish — ILDIZ `apps\server`, natija REPO TASHQARISIGA
cd C:\Users\Developer\Desktop\savdoOS\.claude\worktrees\1c-autonomous-agent\apps\server
C:\Users\Developer\binos-agent-build\buildenv\Scripts\pyinstaller.exe ^
    --noconfirm --clean ^
    --distpath C:\Users\Developer\binos-agent-build\dist-onedir ^
    --workpath C:\Users\Developer\binos-agent-build\build-onedir ^
    packaging\BinOSDiscoveryAgent.spec
```

⚠️ `--distpath`/`--workpath` MAJBURIY: ularsiz PyInstaller `apps\server\dist\` va
`apps\server\build\` papkalarini REPO ICHIDA yaratadi.

⚠️ Spec faylida ishlab chiquvchining MUTLAQ yo'li YO'Q: u `SPECPATH` dan hisoblanadi
(shu bois yig'ma boshqa mashinada ham qurilaveradi).

⚠️ Yig'ma QAYSI OS da qurilsa, SHU OS uchun chiqadi — kross-kompilyatsiya YO'Q.

### 4.4 YIG'MA TUZILMASI va O'LCHAMI (o'lchandi)

```
dist-onedir\BinOSDiscoveryAgent\
    BinOSDiscoveryAgent.exe          <- 2 251 783 bayt (yuklovchi + PYZ arxivi)
    _internal\
        python312.dll                 <- interpretator
        base_library.zip              <- stdlib yadrosi
        VCRUNTIME140.dll, VCRUNTIME140_1.dll
        _tkinter.pyd, tcl86t.dll, tk86t.dll
        _bz2.pyd, _decimal.pyd, _hashlib.pyd, _lzma.pyd, _socket.pyd,
        _wmi.pyd, select.pyd, unicodedata.pyd, libcrypto-3.dll, zlib1.dll
        _tcl_data\, _tk_data\, tcl8\  <- Tcl/Tk resurslari (oyna rejimi uchun)
```

| o'lchov | qiymat |
|---|---|
| jami fayl | **944** |
| jami papka | **37** |
| jami hajm | **25 842 293 bayt** (≈ 24,6 MB) |
| `BinOSDiscoveryAgent.exe` | **2 342 785 bayt** |
| `BinOSDiscoveryAgent.exe` SHA-256 | `e5d23664f9260f32c9ced9675a82e89182d5ecf1060f1bafbcb7f711a479ebba` |
| raqamli imzo | **YO'Q** — sertifikat olinmadi, imzolash siri yaratilmadi (§11) |

⚠️ XESH DARVOZA BILAN BOG'LANGAN: `test_hujjatdagi_EXE_XESHI_haqiqiy_yigmaga_MOS` shu
qiymatni HAQIQIY fayl bilan solishtiradi. Yig'ma qayta qurilsa xesh o'zgaradi va test
QIZIL bo'ladi — demak bu jadval hujjat bilan birga YANGILANISHI kerak, aks holda hujjat
mavjud bo'lmagan yig'ma haqida gapiradi.

⚠️ Jami hajm va fayl soni testda QULFLANMAGAN (ular PyInstaller/Python/Tcl versiyasiga
qarab o'zgaradi va darvoza har build'da yolg'on qizil bo'lardi).

### 4.5 YIG'MA ICHIDA NIMA BOR va NIMA YO'Q

Yig'ma TARKIBI alohida darvoza bilan tekshiriladi (`test_agent_packaging.py`): spec'dagi
`excludes` ro'yxati HAQIQIY yig'ma bilan solishtiriladi, ya'ni spec yolg'on kafolat bera
olmaydi. Qisqacha: migrator APPLY YO'Q, pytest YO'Q, FastAPI/SQLAlchemy/DB haydovchilari
YO'Q, tarmoq kutubxonalari YO'Q, mijoz ma'lumoti va ulanish satri YO'Q.

---

## 5 · ISHGA TUSHIRISH va CHIQISH KODLARI

```bat
BinOSDiscoveryAgent.exe --version
BinOSDiscoveryAgent.exe                                    rem operator oynasi (tkinter)
BinOSDiscoveryAgent.exe --headless <kuzatiladigan-papka> --result-dir <natija-papkasi>
```

| kod | ma'nosi |
|---|---|
| `0` | yurish yakunlandi va natija paketi tekshiruvdan O'TDI (`COMPLETE`) |
| `1` | yurish YIQILDI (`FAILED_*`) — bu ham JAVOB: natija papkasi SABAB bilan qoladi |
| `2` | YURGIZIB BO'LMADI (buyruq xatosi, papka yo'q, `tkinter` yo'q) |

⚠️ Operatorga PYTHON TRACEBACK CHIQMAYDI: kutilmagan istisno ham qisqa, o'zbekcha xabarga
aylanadi (`binos_agent_entry.py` dagi oxirgi to'siq) va kod `2` bo'ladi.

⚠️ **KONSOL KODLASHI — HAQIQIY NUQSON, TUZATILGAN.** Yig'ilgan `.exe` ni rostdan
yurgizganda topildi: operator matnlarida `cp1252` ga sig'maydigan 28 xil belgi bor
(`⚠`, `═`, `─`, kirill). Windows'da chiqish faylga/quvurga yo'naltirilganda
`sys.stdout.encoding` AYNAN `cp1252` bo'ladi va chop etish `UnicodeEncodeError` berardi —
natijada yurish chop etish paytida uzilib, **natija papkasi UMUMAN YOZILMASDI**. To'plam
buni TUTMAGAN, chunki pytest chiqishni UTF-8 bilan ushlaydi. Tuzatish `__main__.py` da
ikki qatlam (`_utf8ga_otkaz` + `_XavfsizOqim`) va u `test_agent_packaging.py` dagi
`cp1252` oqimi testi bilan QULFLANGAN.

---

## 6 · 1C YO'Q MASHINADA YURISH NATIJASI (o'lchandi)

Yig'ilgan `.exe` `--headless` rejimida bo'sh kuzatiladigan papka bilan yurgizildi:

| o'lchov | natija |
|---|---|
| chiqish kodi | **`1`** (`FAILED_TIMEOUT`) — «yurish yiqildi, lekin bu ham JAVOB» |
| Python traceback | **YO'Q** |
| natija papkasi | **YOZILDI** — `binos-discovery-<timestamp>/` |
| ildiz artefaktlari | **5 ta**: `agent_status.json`, `environment.json`, `errors.json`, `agent_manifest.json`, `discovery_report.md` |
| aniqlovchi hukmi | **`absent`** — ISBOTLANGAN yo'qlik: reestr, fayl tizimi, COM ro'yxati va `ibases.v8i` manbalari HAMMASI o'qildi va BO'SH chiqdi |
| `read_only` | **`true`** |

⚠️ `bundle/` ostki papkasi YO'Q va bu TO'G'RI: yig'uvchi (`.epf`) chiqishi kelmagan, chunki
1C yo'q. Ya'ni bu «1C bilan ishladi» EMAS, «1C YO'QLIGINI to'g'ri aniqladi va operatorga
keyingi qadamni yozdi».

---

## 7 · QAT'IY CHEGARALAR (yig'maga ham tegishli)

- **Agent FAQAT operator ishga tushirganda ishlaydi.** Avtoyuklanish YO'Q, Windows xizmati
  YO'Q, rejalashtirilgan topshiriq YO'Q, reestrga yozish YO'Q, YANGILOVCHI YO'Q. Spec'da
  `runtime_hooks` BO'SH va bu test bilan qulflangan
  (`test_yashirin_boshlangich_xulq_yoq`).
- **FAQAT O'QISH.** Agent 1C da hech narsa yozmaydi, hujjat yaratmaydi, o'tkazmaydi,
  o'chirmaydi va o'zboshimcha kod bajarmaydi.
- **Parol buyruq satriga QO'YILMAYDI** (u jarayon ro'yxatida ko'rinadi), parol bayrog'i
  UMUMAN mavjud emas. Baza autentifikatsiya talab qilsa — `FAILED_AUTH_REQUIRED` va
  `watch_folder` yo'li taklif qilinadi.
- **Tarmoq YO'Q.** Yig'ma internetga chiqmaydi; analitik deterministik va LOKAL.
- **Natija faqat operator bergan papkaga** yoziladi: `binos-discovery-<timestamp>/`, ichida
  `agent_status.json`, `environment.json`, `errors.json` (`binos-agent-errors-v1` — Phase 4
  ning `bundle/errors.json` i BILAN BIR XIL EMAS), `agent_manifest.json`,
  `discovery_ai_candidates.json`, `discovery_report.md` va O'ZGARMAGAN Phase 4 paketi
  `bundle/` ostki papkasida.

---

## 8 · §8 — FAYL TIZIMI PORTATIVLIGI (o'lchandi)

Darvoza: `apps/server/tests/test_agent_portability.py`. Testlar yig'ilgan `.exe` ni
`subprocess` bilan ROSTDAN yurgizadi (fayllarni o'qish emas).

### 8.1 UCH JOYDAN YURISH

| joy | joriy papka (`cwd`) | natija |
|---|---|---|
| 1 | BUTUNLAY BO'SH temp papkasi (`tmp_path`) | kod `1`, 5 artefakt, hukm `absent`, traceback YO'Q |
| 2 | REPO TASHQARISI — `C:\Users\Developer\binos-agent-build` | AYNI natija |
| 3 | `C:\Windows\System32` (repo bilan aloqasi yo'q, yozish huquqi kutilmaydi) | AYNI natija |

⚠️ «Ishladi» yetarli emas, shu bois alohida test uchovining NATIJASINI solishtiradi:
paket nomi, artefakt ro'yxati, holat, marshrut, xato kodlari, muhit hukmi, izohlar va
`discovery_report.md` ning SHA-256 i — uchovida AYNI. Ya'ni joriy papka natijaga
TA'SIR QILMAYDI.

### 8.2 `cwd` REPO BO'LISHIGA TAYANMAYDI — isbot

- uch joydan ikkitasi repo TASHQARISIDA, biri BUTUNLAY BO'SH papka;
- `--result-dir` berilmasa natija JORIY papkaga tushadi (yig'ma papkasiga ham, `%TEMP%` ga
  ham, `AppData` ga ham EMAS) — alohida test;
- yurishdan keyin repo ildizida va `apps/server` da `binos-discovery-*` papkasi PAYDO
  BO'LMAYDI — alohida test;
- joriy papkada SOXTA `app/services/discovery_agent/` paketi bo'lsa ham yig'ma uni IMPORT
  QILMAYDI (soxta modul import qilinsa chiqish kodi `77` bo'lardi — bo'lmadi). Bu ham
  portativlik, ham xavfsizlik invarianti.

### 8.3 YIG'MANI KO'CHIRIB YURGIZISH

Yig'ma papkasi butunlay BOSHQA yo'lga nusxalanadi — yo'lda ATAYLAB bo'sh joy va LOTIN
BO'LMAGAN (kirill) belgilar bor (`Разведка 1С (ko'chirilgan)\BinOSDiscoveryAgent\`) —
va shu nusxadan yuritiladi. **Natija: AYNI.** Ya'ni yig'ma qurilgan joyiga (`dist-onedir`)
BOG'LANMAGAN.

### 8.4 YIG'MA O'Z PAPKASIGA HECH NARSA YOZMAYDI

Yurishdan oldin va keyin yig'ma papkasining to'liq fayl ro'yxati + o'lchamlari
solishtiriladi: **O'ZGARISH YO'Q**. Shu bois operatorga beriladigan papkaning `sha256`
ro'yxati keyin ham to'g'ri qoladi va `Program Files` kabi yozib bo'lmaydigan joyga
qo'yilsa ham ishlaydi.

---

## 9 · §8 — ISHLAB CHIQUVCHI YO'LI YIG'MADA BORMI (ikkilik qidiruv)

Yig'madagi **944 fayl** uch kodlashda (UTF-8, UTF-16-LE, CP1251) qidirildi.

| naqsh | topildimi |
|---|---|
| `c:\users\developer`, `c:/users/developer`, `users\developer` | **YO'Q** |
| `binos-agent-build`, `buildenv`, `dist-onedir`, `build-onedir` | **YO'Q** |
| `worktrees`, `1c-autonomous-agent`, `savdoos` | **YO'Q** |
| `.venv`, `apps\server`, `apps/server` | **YO'Q** |

### 9.1 TOPILGAN, LEKIN NUQSON EMAS (ochiq yoziladi)

Teskari qidiruv ham o'tkazildi: yig'madagi HAR QANDAY disk harfi bilan boshlanadigan yo'l
yig'ildi (**103 xil satr**). Hammasi YUQORI OQIM yig'uvchilaridan kelgan va bizning
mashinamizga tegishli EMAS:

| satr | qaysi faylda | kimning yo'li |
|---|---|---|
| `D:\a\1\s\Objects\*.c`, `D:\a\1\b\bin\amd64\python312.pdb` | `python312.dll`, `*.pyd` | python.org ning CI mashinasi (Azure Pipelines) |
| `C:\A\_work\1\s\providers\...`, `C:\A\_work\1\b\libcrypto-3.pdb` | `libcrypto-3.dll` | OpenSSL ning CI mashinasi |
| `D:\a\1\a\amd64\lib\tcl8.6` | `tcl86t.dll` | Tcl/Tk yig'ma mashinasi |
| `C:\Program Files\Common Files\SSL\...` | `libcrypto-3.dll` | OpenSSL ning STANDART yo'li (qattiq yozilgan sozlama) |
| `C:\Users\Barney`, `C:///spam///ham` | `base_library.zip`, `python312.dll` | CPython hujjat/docstring MISOLLARI |

Shuningdek ikki satr topildi va ular ham YO'L EMAS:

- `PYINSTALLER_*` (`BinOSDiscoveryAgent.exe` da) — yuklovchining O'Z muhit
  o'zgaruvchilari nomi;
- `site-packages` (`python312.dll` da) — CPython `site` modulining YORDAM MATNI.

⚠️ Bu ikkisi ishlab chiquvchi haqida hech narsa oshkor qilmaydi, shu bois naqsh ro'yxatida
ATAYLAB YO'Q — aks holda darvoza har build'da yolg'on qizil bo'lardi.

### 9.2 Darvoza IKKI TOMONLAMA

Birinchi test NAQSH ro'yxatiga tayanadi (ro'yxat to'liq bo'lmasligi mumkin). Ikkinchi test
teskari yuradi: topilgan HAR BIR mutlaq yo'lni shu mashinaning `USERPROFILE`, `USERNAME`,
worktree ildizi va build ildizi bilan solishtiradi. Ya'ni kelajakda yangi naqsh
qo'shilmasa ham, BIZGA tegishli yo'l tutiladi.

---

## 10 · §9 — TOZA MASHINA: **`APPROXIMATED`** (isbot EMAS)

> ⚠️⚠️ **BU HAQIQIY TOZA MASHINA ISBOTI EMAS.** Ikkinchi Windows mashinasi ham, VM ham
> YO'Q. O'tkazilgan narsa — BIR XIL mashinada muhit o'zgaruvchilarini KESIB yurgizish.
> Python, `apps/server/.venv`, VC runtime, WinSxS va antivirus holati shu mashinada
> QANDAY BO'LSA SHUNDAYLIGIDA QOLDI. Toza mashinadagi xulq haqidagi XULOSA bu
> o'lchovlardan CHIQMAYDI.

Natija: **`APPROXIMATED` — kesilgan muhitda yig'ma ishladi.**

| yaqinlashuv | nima qilindi | natija |
|---|---|---|
| `python` PATH da YO'Q | `PATH` faqat `C:\Windows\System32` ga qisqartirildi; `shutil.which("python")` shu PATH da `None` ekani tekshirildi | kod `1`, 5 artefakt, hukm `absent` |
| bo'lishilgan `.venv` ko'rinmaydi | `VIRTUAL_ENV`, `PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONEXECUTABLE`, `CONDA_PREFIX`, `PYTHONUSERBASE` — BIRORTASI berilMADI (`.venv` ning O'ZIGA TEGILMADI) | AYNI natija |
| manba daraxti topilmaydi | `cwd` repo tashqarisida + `PYTHONPATH` BO'SH satr | AYNI natija |
| `PYTHONPATH` ZAHARLANGAN | `PYTHONPATH` darhol yiqiladigan soxta `app.services.discovery_agent` paketiga ko'rsatildi | soxta paket IMPORT QILINMADI (kod `77` CHIQMADI) |
| `PYTHONHOME` YOLG'ON | mavjud BO'LMAGAN papkaga ko'rsatildi | AYNI natija |
| `--version` kesilgan muhitda | — | kod `0`, matnda `RUNTIME-UNKNOWN` saqlanadi |

### 10.1 NIMA O'LCHANMAGAN (ochiq ro'yxat)

- Python umuman O'RNATILMAGAN mashinada yurish — **o'lchanMAGAN**;
- Visual C++ runtime o'rnatilmagan mashinada yurish — **o'lchanMAGAN** (yig'mada
  `VCRUNTIME140*.dll` bor, lekin bu tizim DLL lari bilan to'liq almashadimi — sinalmagan);
- boshqa Windows versiyasi / 32-bit Windows — **o'lchanMAGAN**;
- domenga kirgan, siyosat bilan cheklangan do'kon kompyuteri — **o'lchanMAGAN**;
- administrator huquqisiz foydalanuvchi profilida yurish — **o'lchanMAGAN**;
- `Program Files` kabi yozib bo'lmaydigan joydan yurish — **o'lchanMAGAN** (lekin yig'ma
  o'z papkasiga yozmagani o'lchandi, 8.4).

---

## 11 · §11 — IMZO: **YO'Q (`unsigned` / IMZOLANMAGAN)**

| savol | javob |
|---|---|
| `.exe` ga imzo qo'yilganmi | **YO'Q — `unsigned`.** Sertifikat yo'q, `codesign_identity=None` |
| Defender/SmartScreen ogohlantirishi KUZATILDIMI | **KUZATILMADI** — lekin bu «ogohlantirish bo'lmaydi» DEGANI EMAS (10.1 ga qarang) |
| nega kuzatilmadi | yig'ma shu mashinada qurildi va SHU MASHINADA yuritildi: fayl internetdan yuklanmagani uchun `Mark of the Web` (Zone.Identifier) YO'Q, SmartScreen esa aynan shu belgiga qaraydi |
| do'konda nima bo'lishi KUTILADI | fayl boshqa mashinaga ko'chirilganda (ayniqsa internet yoki messenjer orqali) SmartScreen «Windows protected your PC» oynasini ko'rsatishi EHTIMOL |

⚠️ Bu yerda «ishonchli» (`trusted`) yoki imzo qo'yilgan deb DA'VO QILINMAYDI. Tarqatishdan
oldin ikki yo'ldan biri kerak: (a) kod imzolash sertifikati, yoki (b) operator hujjatida
ogohlantirish va `sha256` ni qo'lda tekshirish tartibi.

⚠️ Antivirus xulqi ham **TEKSHIRILMAGAN**: bu mashinada karantin kuzatilmadi, lekin do'kon
kompyuteridagi boshqa antivirus boshqacha qaror qilishi mumkin. ONE-DIR tanlanganining bir
sababi aynan shu xavfni kamaytirish (4.2).

---

## 12 · NIMA BAJARILGAN va NIMA BAJARILMAGAN (ochiq ro'yxat)

**BAJARILGAN (o'lchangan)**
- stdlib-only (+`tkinter`) dizayn va uni qulflaydigan statik testlar;
- `BinOSDiscoveryAgent.exe` ONE-DIR yig'masi QURILDI (PyInstaller 6.22.3, Python 3.12.10);
- bo'lishilgan `.venv` IFLOSLANMADI (yig'uvchi alohida muhitda);
- yig'ma TARKIBI darvoza bilan tekshirildi (`test_agent_packaging.py`);
- yig'ma UCH xil joydan yurgizildi va natija uchovida AYNI (§8);
- yig'ma KO'CHIRILGANDA (bo'sh joy + kirill nomli yo'l) ham yurdi;
- yig'ma O'Z papkasiga va REPOGA hech narsa yozmagani o'lchandi;
- yig'mada SHU mashinaning yo'li YO'Q (944 fayl, 3 kodlash, ikki tomonlama darvoza);
- `cp1252` konsol nuqsoni TOPILDI (EXE ni rostdan yurgizib) va TUZATILDI, test bilan qulflandi;
- `APPROXIMATED` toza-mashina yaqinlashuvi: PATH kesilgan, `.venv` ko'rinmaydi, manba
  daraxti yo'q, `PYTHONPATH` zaharlangan — hammasida yurdi.

**BAJARILMAGAN**
- Python o'rnatilmagan HAQIQIY toza mashinada SINOV — **O'TKAZILMAGAN** (mashina yo'q);
- antivirus / SmartScreen xulqi boshqa mashinada — **TEKSHIRILMAGAN**;
- imzo (code signing) — **YO'Q**;
- portable papka (embeddable Python) varianti — **QURILMAGAN** (kerak emas: `.exe` yuradi);
- `tkinter` OYNA rejimi yig'mada — **YURGIZILMAGAN** (Tcl/Tk fayllari yig'mada BOR va
  `--headless` ishlaydi, lekin oyna ochilishi o'lchanmagan: avtomatik testda oyna yo'q);
- 1C bilan ishlash — **`RUNTIME-UNKNOWN`**: bu mashinada 1C:Enterprise umuman o'rnatilmagan,
  `.epf` yig'uvchisi qurilmagan, COM yo'li sinalmagan.
