# `BinOSDiscoveryAgent` — YIG'MA DARVOZASI (ikki ega)

Bu hujjat **bitta savolga** javob beradi: «yig'ilgan `.exe` manba Python bilan AYNI
qarorni chiqaradi» degan kafolatni **kim**, **qayerda** va **qanday** isbotlaydi.

> ⚠️⚠️ **DA'VO CHEGARASI (kengaytirilmaydi).** Bu yerdagi hech narsa real 1C isboti EMAS:
> `.epf` holati — `EPF_SOURCE_READY`, avtomatik ishga tushirish — `UNVERIFIED_ON_REAL_1C`,
> COM yo'li YO'Q. Darvozalar 1C ga ULANMAYDI, `1cv8.exe` ni ISHGA TUSHIRMAYDI, tarmoqdan
> foydalanmaydi. O'lchanadigan narsa — **ikki yig'maning bir xil sintetik kirishdagi
> semantikasi** va **yig'ma tarkibi**.

---

## 1. Nega kafolat IKKIGA bo'lingan

Haqiqiy `.exe` parity'si Windows yig'masini talab qiladi. Backend CI **Linux**'da yuradi va
PyInstaller **kross-kompilyatsiya qilmaydi** — Windows runner esa bu job'da yo'q. Ya'ni
kafolatning bir qismi Linux'da **fizik ravishda** o'lchanmaydi.

Ikki yomon yechim bor edi va ikkisi ham rad etildi:

| Rad etilgan yechim | Nega |
|---|---|
| `.exe` yo'q bo'lsa testlar **shartsiz `skip`** | Kafolat jimgina yo'qoladi: hisobotda «hammasi o'tdi» ko'rinadi, aslida parity TEKSHIRILMAGAN. |
| Linux'da **baland yiqilish** (hozirgi holat) | Backend job doimo qizil, demak signal ma'lumot bermaydi va keyin umuman o'qilmaydi (loyihada bu allaqachon bo'lgan: `ci-backend-no-tests`). |

Shu bois kafolat **ikki egaga** bo'lingan. Ikkisi **kesishmaydi** — biri ikkinchisining
o'rnini bosmaydi.

### OWNER A — yig'ma SHARTNOMASI (Linux CI, `.exe` KERAK EMAS)
`tests/test_agent_parity.py::test_A_*` + `packaging/parity_harness.py`

Hammasi **manbadan** hisoblanadi, demak har platformada AYNI javobni beradi:

- yig'maga kiradigan modullar yopig'i (kirish skriptidan import grafi) **spec'dagi
  `excludes` bilan ZIDLASHMAYDI** — ratifikatsiya qilingan yagona kechikkan import
  (`migrator_1c.normalize`) va uning sharti (import FUNKSIYA ICHIDA, AYNAN
  `bundle._canon_guid_text` da) alohida qulflangan;
- `migrator_1c` dan faqat `bundle` ga yetib boriladi (**APPLY** yig'maga kirmaydi);
- `excludes` HIMOYA oilalari (testlar · server freymvorki · DB · tarmoq · ishlab chiquvchi
  vositalari) butunlay yo'qolmaydi;
- `hiddenimports` `tkinter` oilasini qamraydi;
- **kirish nuqtasi shartnomasi**: `binos_agent_entry.py` `app.*` dan FAQAT
  `__main__.{main, EXIT_CANNOT_RUN}` ni oladi (mantiq takrorlanmaydi) va chiqish kodlari
  `0/1/2` bo'lib qoladi;
- **yig'ma imzosi** (`manba_xeshi()`): yig'maga kiradigan HAMMA manba faylining `sha256`
  jamlanmasi; jamlashning tishi (mazmun · qayta nomlash · yangi fayl) alohida o'lchangan.

Bundan tashqari **solishtiruvchining O'ZI** Linux'da ham o'lchanadi: `manba_yurishi`
fiksturasi agentni **jarayon ochmasdan** (`main()` ni shu jarayonda) uchta ssenariyda
yurgizadi, so'ng chuqur solishtiruvchi, allowlist va mutatsiya testlari shu natijaga
qo'llanadi. Ya'ni `.exe` yo'qligi «solishtirish ishlaydimi» savolini ochiq qoldirmaydi.

### OWNER B — HAQIQIY `.exe` parity'si (Windows, MAHALLIY reliz darvozasi)
`tests/test_agent_parity.py` (qolgan hammasi) + `tests/test_agent_packaging.py`
+ `tests/test_agent_portability.py`

Manba va `.exe` AYNI sintetik fikstura bilan yurgiziladi va natijalar JSON daraxti bo'ylab
bargma-barg solishtiriladi; `.exe` ichidagi modullar ro'yxati spec bilan solishtiriladi;
**portativlik** moduli esa `.exe` ni `subprocess` bilan ROSTDAN yurgizadi (uch joydan,
kesilgan muhitda, ko'chirilgan nusxadan). Buni **faqat Windows'da** bajarish mumkin.

---

## 2. ESKIRGAN YIG'MA DARVOZASI (brief talabi: «jimgina o'tmasligi SHART»)

### Muammo
«`.exe` bor» degani «`.exe` SHU manbadan qurilgan» degani EMAS. Eskirgan yig'ma parity'dan
**jimgina o'tib ketishi mumkin**: o'zgargan modul tanlangan fiksturada kuzatiladigan farq
bermasa, solishtirish YASHIL bo'ladi va «yig'ma manbaga teng» degan **yolg'on** xulosa
chiqadi.

> ⚠️ **Bu nazariy xavf emas.** Bu darvoza yozilgan kun shu worktree'da: manbada
> `discovery_1c/redact.py`, `discovery_agent/detector.py` va `discovery_agent/launcher.py`
> o'zgargan edi, mahalliy `.exe` esa ularning ESKI nusxasi bilan qurilgan — va parity
> to'plami **3067/3067 yashil** o'tdi. Kafolat o'sha yurishda **asossiz** edi.

### Yechim: artefaktning ICHIDAN o'qiladi, YONIDAN emas
PyInstaller `build-onedir/BinOSDiscoveryAgent/PYZ-00.pyz` ni alohida fayl bo'lib
qoldiradi: sarlavha `PYZ\0` + Python magic + TOC siljishi; TOC `marshal` bilan
o'qiladigan `{nom: (tur, siljish, uzunlik)}`; yozuvlar `zlib` bilan siqilgan kod
obyektlari. **Hammasi standart kutubxona bilan** o'qiladi — PyInstaller o'rnatilmaydi.

Darvoza har `app.*` moduli uchun yig'madagi kod obyektining **imzosini** joriy manbani
qayta kompilyatsiya qilib olingan imzo bilan solishtiradi
(`parity_harness.eskirgan_modullar()`).

**Nega shtamp fayli EMAS** (arxitektor taklif qilgan yo'l):

1. shtamp YANGI va MAJBURIY build qadamini talab qiladi — esdan chiqsa darvoza yo DOIM
   qizil, yo TESHIK bo'ladi;
2. shtamp artefaktning O'ZIDAN emas, uning YONIDAN keladi — ko'chirilgan yoki qo'lda
   yozilgan shtamp eskirgan `.exe` ni «toza» deb ko'rsatardi.

Bytecode **yolg'on bo'la olmaydi**. `manba_xeshi()` baribir saqlanadi, lekin darvoza sifatida
emas — reliz hisobotiga yoziladigan, inson o'qiy oladigan imzo sifatida.

**Nega `mtime` EMAS:** `git checkout` / worktree yaratish fayl vaqtlarini oldinga siljitadi,
ya'ni sog'lom yig'ma ham «eskirgan» bo'lib chiqardi (bu worktree'da aynan shunday bo'lardi).

### Darvoza holatlari (`parity_harness.yigma_tayyorligi()`)

| Holat | Qachon | Natija |
|---|---|---|
| `TOZA` | `.exe` bor · build papkasidagi `.exe` dist'dagisiga BAYT-BA-BAYT teng · PYZ dagi hamma `app.*` modul joriy manbaga mos | haqiqiy parity YURGIZILADI |
| `YO_Q` | `.exe` umuman yo'q | **Windows**: YIQILISH · **boshqa platforma**: ratifikatsiya qilingan MUHIT skip'i |
| `ISBOTSIZ` | `.exe` bor, lekin PYZ yo'q / build `.exe` farq qiladi / PYZ boshqa Python magic bilan / PYZ shakli buzuq / arxivda agent modullari yo'q | **YIQILISH** (har platformada) |
| `ESKIRGAN` | `.exe` bor va ≥1 modul joriy manbadan BOSHQA | **YIQILISH** (har platformada), nomos modullar ro'yxati bilan |

⚠️ **FAIL-CLOSED**: faqat `TOZA` da haqiqiy parity yuradi. «Isbotlab bo'lmadi» HECH QACHON
«toza» ga aylanmaydi.

### ⚠️ IKKI DARVOZANING IKKISI HAM shu jadvalga tayanadi (2026-10-02)

Jadval ilgari FAQAT `tests/test_agent_parity.py` ga qo'llanardi. **Yig'ma TARKIBI
darvozasi** (`tests/test_agent_packaging.py`) o'z o'lchovini qilardi — build papkasidagi
`.exe` ↔ dist papkasidagi `.exe` **BAYT tengligi** — va bu tenglik yangilik haqida HECH
NARSA demaydi: ikkisi ham AYNI, ESKI yig'madan bo'lsa tenglik SAQLANADI.

> ⚠️⚠️ **O'LCHANGAN TESHIK.** Shu worktree'da, mahalliy `.exe` uch moduldan eskirgan
> holatda: `test_agent_parity.py` BALAND yiqildi va uchta modulni NOMLADI,
> `test_agent_packaging.py` esa **`25 passed, 0 skipped`** berdi. Ya'ni yig'ma TARKIBI
> darvozasi ESKIRGAN artefaktni «toza» deb TASDIQLADI, va brif talab qilgan «eskirgan
> yig'ma jimgina o'tib ketolmasligi» kafolatining yagona himoyasi pastdagi cheklistning
> `0 skipped` sharti — ya'ni **HUJJAT** edi.

Endi himoya **KODDA**: `test_agent_packaging.py::_dist_talab()` hukmni
`parity_harness.yigma_tayyorligi()` dan OLADI (darvoza QAYTA YOZILMADI — ikkinchi nusxa
bir kun ajralib ketardi). Darvoza **(A) manifest** va **(B) artefakt** tekshiruvlarining
IKKISIDA ham turadi, chunki bu moduldagi har bir da'vo JORIY manba haqidagi da'vo bo'lib
o'qiladi («tarqatiladigan `.exe` da test kodi YO'Q», «ishlab chiquvchi yo'li YO'Q»,
«mijoz ulanish satri YO'Q») — eskirgan artefaktda manbaga BUGUN kiritilgan sir yoki
taqiqlangan import KO'RINMAYDI va da'vo YOLG'ON yashil bo'ladi.

Qaror jadvali `pytest` chaqiruvidan AJRATILGAN (`_yoqlik_qarori()`,
`_yangilik_qarori()`), shu bois u `.exe` BO'LMAGAN platformada ham test bilan o'lchanadi:
`test_darvoza_ESKIRGAN_yigmani_JIM_otkazib_yubormaydi` — `TOZA` dan boshqa HAR holat
yiqilish beradi, harness sababi (nomos modullar ro'yxati) SAQLANADI, `.exe` yo'qligi
Windows'da YIQILISH / boshqa platformada ratifikatsiya qilingan skip, va darvozaning
`_dist_talab()` ichida CHAQIRILGANI manbadan tekshiriladi (o'lik gard bo'lib qolmasin).
Bu test Linux CI'da ham BAJARILADI va `ci_expected_skips.txt` da YO'Q.

**O'lchangan (2026-10-02, shu worktree):**

| Holat | `test_agent_packaging.py` natijasi |
|---|---|
| `ESKIRGAN` (joriy daraxt, uch modul) | **21 failed, 5 passed** (ilgari: 25 passed, 0 skipped) |
| `ISBOTSIZ` (`BINOS_AGENT_BUILD` bo'sh papka) | **21 failed, 5 passed** |
| `YO_Q` + Windows | **21 failed, 5 passed** |
| `YO_Q` + boshqa platforma (taqlid) | **21 skipped** — ikki modulda JAMI `37 skipped`, `verify_pytest_run.py` → «BAJARILISH ISBOTLANDI», muammolar `[]` ⚠️ **BU O'LCHOV TO'LIQ EMAS EDI** — pastdagi «UCHINCHI DARVOZA» bo'limiga qarang: uchinchi modul `BINOS_AGENT_BUILD_ROOT` ni o'qimagani uchun taqlidga QO'SHILMAGAN; haqiqiy jami **55 skipped** |
| `TOZA` (as-built manba daraxti) | **26 passed, 0 skipped** — yolg'on qizil YO'Q |

⚠️ `ci_expected_skips.txt` O'ZGARTIRILMADI: skip sababi (`MUHIT: Windows yig'masi Linux
CI'da QURILMAYDI`) ham, 37 ta aniq id ham AYNAN avvalgidek. Ro'yxat sarlavhasidagi (b) va
(c) bandlari endi ikki modul uchun ham KODDA bajariladi. ⚠️ UCHINCHI modul uchun ro'yxat
O'ZGARDI — pastdagi bo'limga qarang (18 ta yangi aniq id).

### ⚠️ UCHINCHI DARVOZA: PORTATIVLIK (`tests/test_agent_portability.py`, 2026-10-02)

Yuqoridagi tuzatish IKKI modulni qamradi. **Uchinchisida AYNI teshik ochiq qolgan edi** va
unda yana UCHTA mustaqil nuqson bor edi:

| # | Nuqson | Oqibati |
|---|---|---|
| 1 | `_YIGMA_ILDIZ` **QOTIRILGAN**: `pathlib.Path("C:/Users/Developer/binos-agent-build")` — `BINOS_AGENT_BUILD_ROOT` ni UMUMAN o'qimasdi | Ildiz-drifti qo'riqchisi (`test_A_yigma_ILDIZI_ikki_modulda_AYNI`) bu modulni QAMRAMAGAN edi, ya'ni uchinchi darvoza jimgina BOSHQA yig'mani tekshirishi mumkin edi; yo'lning o'zi spec'ning «hardcoded developer path bo'lmasin» qoidasiga zid |
| 2 | `.exe` yo'q bo'lsa **SHARTSIZ `skip`** (o'zining `_dist_talab()` si): platformaga bog'liq EMAS, YANGILIK tekshiruvi YO'Q | ESKIRGAN `.exe` shu yerda ham «portativ» deb tasdiqlanardi — o'lchangan holat **`21 passed`** (yig'ma uch moduldan eskirgan). Windows reliz darvozasida yig'ma topilmasa ham skip bo'lib o'tardi |
| 3 | Uning skip'lari `ci_expected_skips.txt` da **UMUMAN YO'Q** edi | **HAQIQIY Linux CI'da 18 ta «KUTILMAGAN skip»** → `verify_pytest_run.py` backend job'ni QIZIL qilardi. Ya'ni yuqoridagi «37 skipped, yashil» Linux o'lchovi NOTO'G'RI edi: taqlid `BINOS_AGENT_BUILD_ROOT` ni o'zgartirardi, bu modul esa uni o'qimagani uchun Windows'dagi qotirilgan yo'l MAVJUD bo'lib testlar skip emas, BAJARILGAN |

**Tuzatish — AYNI harness, AYNI naqsh** (darvoza QAYTA YOZILMADI): ildiz
`BINOS_AGENT_BUILD_ROOT` dan (standart `~/binos-agent-build`), `_harness()` esa
`sys.modules["binos_parity_harness"]` dagi MAVJUD nusxani qayta ishlatadi (ikkinchi modul
nusxasi paydo bo'lmasin). Qaror funksiyalari `pytest` dan AJRATILGAN
(`_yoqlik_qarori()`, `_yangilik_qarori()`), darvoza `_dist_talab()` da SIMLANGAN, va
drift qo'riqchisi endi **UCH** modulni qamraydi:
`test_agent_parity.py::test_A_yigma_ILDIZI_UCH_modulda_AYNI`.

⚠️ **SKIP SABABI UCHINCHI, AJRALGAN MATN**: `MUHIT: Windows EXE'ni Linux CI YURGIZA
OLMAYDI`. `verify_pytest_run._matches` sababni `reason in msg` bilan tekshiradi — matnlar
bir-birining BO'LAGI bo'lsa, bir bo'lim ro'yxatdan yo'qolganda uning skip'lari
ikkinchisining qatoriga «yashirinib» o'tardi va KUTILMAGAN skip QIZIL bermasdi. Uch
matnning ajralganligi test bilan qulflangan
(`::test_darvoza_ESKIRGAN_yigmani_PORTATIV_deb_tasdiqlamaydi`). Matn semantik jihatdan ham
boshqa: bu modul `.exe` ni ROSTDAN yurgizadi, ya'ni Linux'dagi cheklov «qurilmaydi» emas —
yig'ma BO'LGANDA ham Linux Windows PE ikkiligini BAJARA OLMAYDI (Wine ishlatilmaydi).

**O'lchangan (2026-10-02, shu worktree):**

| Holat | `test_agent_portability.py` natijasi |
|---|---|
| `ESKIRGAN` (joriy daraxt, uch modul) | **18 failed, 4 passed** (ilgari: `21 passed`) — yiqilish matni uchta nomos modulni NOMLAYDI |
| `TOZA` (as-built manba daraxti, `git show HEAD:` dagi uch fayl bilan) | **22 passed, 0 skipped** — yolg'on qizil YO'Q |
| `YO_Q` + boshqa platforma (taqlid) | **18 skipped** — UCH modulda JAMI **55 skipped** (16 + 21 + 18), `verify_pytest_run.py` → «BAJARILISH ISBOTLANDI», muammolar `[]`, junit'da topilmagan statik funksiya `0` |
| NEGATIV NAZORAT: 18 yozuv ro'yxatdan OLIB TASHLANSA | «BAJARILISH ISBOTLANMADI», **18 ta KUTILMAGAN skip** — ya'ni yozuvlar HAQIQATAN ushlab turadi |

**Mutatsiya (darvoza o'lik qilinganda yangi test YIQILADI, so'ng fayl bayt-ba-bayt
tiklandi — `sha256` mos):**

| Mutatsiya | Natija |
|---|---|
| `_yangilik_qarori` HAMMA holatda `None` | `ESKIRGAN` holati JIMGINA o'tib ketdi — PORTATIVLIK darvozasi TESHIK |
| `_yoqlik_qarori` SHARTSIZ `SKIP` | yig'ma QURILADIGAN platformada `.exe` yo'qligi SKIP bo'lib qoldi |
| `_dist_talab()` harnessni CHAQIRMAYDI | `yigma_tayyorligi` ni CHAQIRMAYDI — darvoza SIMLANMAGAN |
| skip sababi parity'nikiga TENG / uning BO'LAGI | «sababi BOSHQASI bilan AYNI» / «sabablar bir-birining BO'LAGI» |

⚠️ Bu modulda `ci_expected_skips.txt` ga **18 ta ANIQ id** QO'SHILDI (ro'yxatda jami
59 qoida). `glob:` ISHLATILMADI, bu modulda parametrli test YO'Q. Ro'yxatda YO'Q va shu
bois Linux'da BAJARILADIGAN to'rtta test: darvozaning o'z o'lchovi va uchta hujjat testi.

### Solishtiruvchining tishi va YOLG'ON QIZILI
Ikkisi ham test bilan qulflangan (`test_B_*`):

- **tish**: bitta konstanta o'zgarsa (ichki funksiyada ham) imzo o'zgaradi;
- **yolg'on qizil**: imzo `repr()` ISHLATMAYDI. `co_consts` ichidagi `frozenset`
  (`in {...}` dan) `repr` TARTIBI satr xeshiga, ya'ni **jarayonga** bog'liq — birinchi
  nusxa aynan shu sababdan `redact.py` va `result_package.py` ni **o'zgarmagan holda**
  «eskirgan» deb ko'rsatdi. `nan`, `1` ↔ `True` holatlari ham qulflangan. Yolg'on qizil
  darvozani operator qo'li bilan o'chirishga olib keladi — ya'ni u ham kafolatni buzadi.
- **o'lchangan**: as-built manba daraxtida darvoza **34/34 modulni** `TOZA` deb berdi
  (0 yolg'on qizil), joriy daraxtda esa AYNAN uchta o'zgargan faylni nomlab `ESKIRGAN`.

### ⚠️ TO'RTINCHI va BESHINCHI DARVOZA (2026-10-02)

Yana IKKI modul AYNI yig'maga tayanardi va ularda AYNI UCHTA nuqson bor edi:

| # | `tests/test_agent_packaged_e2e.py` (15 test) | `tests/test_agent_packaged_safety.py` (3 bayt-testi) |
|---|---|---|
| 1 | `STANDART_EXE` **QOTIRILGAN** (`C:\Users\Developer\...`), `BINOS_AGENT_BUILD_ROOT` O'QILMASDI | `_DIST` **QOTIRILGAN**, AYNI sabab |
| 2 | **MODUL darajasidagi** `pytestmark = pytest.mark.skipif` — platformaga bog'liq EMAS, yig'ma YANGILIGI tekshirilmasdi | `_yigma_yoq` SHARTSIZ `skipif`, AYNI sabab |
| 3 | `ci_expected_skips.txt` da **0 yozuv** → Linux CI'da **15 «KUTILMAGAN skip»** | **0 yozuv** → **3 «KUTILMAGAN skip»** |

⚠️⚠️ **TO'RTINCHISINING OQIBATI ENG OG'IR**: u `.exe` ni `subprocess` bilan ROSTDAN
yurgizadi, ya'ni ESKIRGAN artefakt «uchiga-uch ishlaydi» deb TASDIQLANARDI (o'lchangan:
`15 passed`). **BESHINCHISI** tarqatiladigan `.exe` BAYTLARI ustida da'vo qiladi
(«qobiq/persistence izi YO'Q», «tarmoqqa qodir fayllar ro'yxati O'SMADI», «UPX YO'Q») —
eskirgan papkada bu da'volar YOLG'ON (o'lchangan: `22 passed`).

Ikkisi ham NAMUNA naqshiga keltirildi: ildiz `BINOS_AGENT_BUILD_ROOT` dan, hukm
`parity_harness.yigma_tayyorligi()` dan, `_harness()` esa `sys.modules`
(`binos_parity_harness`) dagi MAVJUD nusxani qayta ishlatadi — ikkinchi modul nusxasi
paydo bo'lmaydi.

⚠️ **SKIP SABABLARI TO'RTINCHI va BESHINCHI, AJRALGAN MATN**:
`MUHIT: Linux CI'da Windows yig'masi UCHIGA-UCH yurmaydi` ·
`MUHIT: tarqatiladigan Windows BAYTLARI Linux CI'da YO'Q`.
BESHTA matn juftma-juft AJRALGAN (teng emas, biri ikkinchisining BO'LAGI emas) va bu
`tests/test_agent_build_inventory.py::test_BESH_darvozaning_skip_sababi_JUFTMA_JUFT_AJRALGAN`
da QULFLANGAN. Sabab: `verify_pytest_run._matches` `reason in msg` ishlatadi.

**O'lchangan (`BINOS_AGENT_BUILD_ROOT` joyida, mahalliy `.exe` ESKIRGAN):**

| Holat | `packaged_e2e` | `packaged_safety` |
|---|---|---|
| `ESKIRGAN` (joriy daraxt) | **14 failed, 2 passed** (ilgari: 15 passed) | **3 failed, 20 passed** (ilgari: 22 passed) |
| `TOZA` (as-built, `git show HEAD:` dagi uch fayl) | **16 passed, 0 skipped** | **23 passed, 0 skipped** |
| `YO_Q` + boshqa platforma (taqlid) | **14 skipped** | **3 skipped** |

⚠️ BESH modul BIRGA (ildiz yo'q + `exe_qurish_mumkinmi()->False` + `BINOS_AGENT_EXE`
mavjud bo'lmagan yo'lda): **82 passed, 72 skipped** —
16 (parity) + 21 (packaging) + 18 (portability) + 14 (e2e) + 3 (safety).
HAQIQIY `scripts/ci/verify_pytest_run.py` → «BAJARILISH ISBOTLANDI», **muammolar `[]`**,
exit `0`, junit'da topilmagan statik funksiya `0`. Yangi 17 yozuv ro'yxat NUSXASIDAN
olib tashlanganda — AYNAN **17 «KUTILMAGAN skip»**, exit `1`.

⚠️ `test_I2_odam_tasdigi_AI_lugatida_UMUMAN_yoq` ro'yxatga **QO'SHILMADI** va bu ataylab:
u `.exe` ni YURGIZMAYDI (faqat `ai` lug'atini va `pipeline` manbasini o'qiydi), ilgari
esa MODUL darajasidagi `skipif` tufayli BEKORGA skip bo'lardi. Endi u Linux'da
BAJARILADI — ya'ni e2e modulidan 15 emas, **14** skip keladi va `ci_expected_skips.txt`
konventsiyasi («javob «dependency o'rnatilmagan» bo'lsa — qator QO'SHILMAYDI») buzilmaydi.

**Mutatsiya (har biri alohida, so'ng fayl BAYTMA-BAYT tiklandi — `sha256` mos):**

| Mutatsiya | Natija |
|---|---|
| `_yangilik_qarori` HAMMA holatda `None` (e2e / safety) | «`ESKIRGAN` holati JIMGINA o'tib ketdi» → YIQILDI |
| skip sababi boshqa darvozanikiga TENG (e2e / safety) | «sababi BOSHQASI bilan AYNI» → YIQILDI |
| bitta test darvozani CHAQIRMAYDI (e2e `test_J` / safety `ONE_DIR`) | AST QAMROV tekshiruvi → YIQILDI |
| SIM uzildi: `_darvoza_AYNI_EXE_ni_olchasin` / `yigma_tayyorligi` / `exe_qurish_mumkinmi` chaqiruvi yo'q | «darvoza SIMLANMAGAN» → YIQILDI |
| inventar MEZONI kengaytirildi (`assert ` qo'shildi) | «mezon KENG» + «YANGI MODUL TOPILDI» → YIQILDI |

⚠️⚠️ **SIMLASH QO'RIQCHISIDAGI O'LCHANGAN NUQSON**: dastlab simlash
`inspect.getsource(_dist_talab)` MATNIDA nom izlash bilan tekshirilardi. Chaqiruv OLIB
TASHLANGANDA ham test YASHIL qoldi, chunki `getsource()` DOCSTRINGNI ham qaytaradi va
docstring o'sha nomni ESLATADI — ya'ni qo'riqchining O'ZI o'lik edi. Endi
`_chaqirilgan_nomlar()` AST bilan faqat HAQIQIY `Call` tugunlarini o'qiydi.
⚠️ AYNI zaiflik `test_agent_packaging.py` va `test_agent_portability.py` dagi
`_dist_talab` simlash tekshiruvlarida ham QOLGAN (ularning docstringi ham o'sha nomlarni
eslatadi) — ular bu ishda TEGILMADI, qarang §4.

### ⚠️ INVENTAR QO'RIQCHISI (`tests/test_agent_build_inventory.py`)

AYNI teshik BESH marta takrorlandi va har biri QO'LDA ko'rib topildi, shu bois
**STRUKTURAVIY** qo'riqchi qo'shildi: `tests/` yurib chiqiladi va yig'maga TAYANADIGAN
modullar to'plami MUZLATILGAN beshlik bilan AYNAN teng bo'lishi talab qiladi.

**Mezon (ikki shart BIRGA, modul MATNI ustida — import QILINMAYDI):**

1. yig'ma ildiziga/artefaktiga havola: `BINOS_AGENT_BUILD_ROOT`, `BINOS_AGENT_EXE`,
   `binos-agent-build`, `dist-onedir`, `build-onedir`, `BinOSDiscoveryAgent.exe`;
2. shartli skip/fail mexanizmi: `pytest.mark.skipif`, `pytest.skip(`, `pytest.fail(`,
   `_dist_talab`, `yigma_tayyorligi`.

⚠️ 2-shart ATAYLAB: artefakt nomini FAQAT matn sifatida tasdiqlaydigan modul yig'maga
TAYANMAYDI. O'lchangan: 1-shart **7 modulni** tutadi, ikkisi BIRGA esa AYNAN **5 ta**.
`test_agent_result_package.py` (hisobot matnida `BinOSDiscoveryAgent.exe` satri) va
`test_discovery_1c_redact.py` (niqoblanadigan kirish SATRI) mezondan TUSHMAYDI va bu
`::test_mezon_yigmaga_TAYANMAYDIGAN_modullarni_TUTMAYDI` da IKKI TOMONLAMA qadalgan.
⚠️ YAGONA istisno — qo'riqchining O'ZI (mezon tokenlari unda RO'YXAT bo'lib yozilgan);
istisno bittaligi `::test_qoriqchining_OZI_YAGONA_istisno` da talab qilinadi.

Qo'riqchi yana uch narsani qulflaydi: BESH modulda yig'ma ildizi AYNI (parity'nikini
harnessdan oladi), skip sabablari juftma-juft AJRALGAN, va HAR modulning
`ci_expected_skips.txt` da kamida bitta — `glob:`siz, AYNI sabab matnli — yozuvi BOR.

⚠️ Qo'riqchi `.exe` DAN MUSTAQIL, Linux'da BAJARILADI va `ci_expected_skips.txt` da
YO'Q. O'lchangan: soxta oltinchi modul `tests/` ga qo'yilganda qo'riqchi QIZIL bo'ldi va
xabarda uch qadamni (darvozani qo'llang · ro'yxatga yozing · `_MUZLATILGAN` ga qo'shing)
KO'RSATDI; fayl o'chirilgandan keyin `6 passed`.

---

## 3. RELIZ CHEKLISTI (Windows, mahalliy)

PyInstaller **alohida** muhitda turadi (`%USERPROFILE%\binos-agent-build\buildenv`,
hozirda PyInstaller 6.22.3 / Python 3.12.10) — ⚠️ testlarning umumiy `.venv` iga u
O'RNATILMAYDI.

```bat
rem 1) yig'ish — build papkasi SAQLANADI (PYZ eskirgan-yig'ma darvozasiga kerak)
cd <repo>\apps\server
%USERPROFILE%\binos-agent-build\buildenv\Scripts\pyinstaller.exe --noconfirm ^
  --distpath %USERPROFILE%\binos-agent-build\dist-onedir ^
  --workpath %USERPROFILE%\binos-agent-build\build-onedir ^
  packaging\BinOSDiscoveryAgent.spec

rem 2) BESH darvoza + INVENTAR QO'RIQCHISI — SKIP BO'LMASLIGI SHART
<venv>\Scripts\python.exe -m pytest -q -p no:randomly ^
  tests\test_agent_parity.py tests\test_agent_packaging.py ^
  tests\test_agent_portability.py tests\test_agent_packaged_e2e.py ^
  tests\test_agent_packaged_safety.py tests\test_agent_build_inventory.py -rs
```

⚠️ **Yig'uvchi Python'i testlarni yurgizadigan Python bilan AYNI MINOR versiyada bo'lishi
SHART** (bytecode magic): aks holda eskirgan-yig'ma darvozasi `ISBOTSIZ` berib yiqiladi —
ataylab, chunki boshqa Python bilan qurilgan yig'mani solishtirish ma'nosiz.

**Qabul shartlari:**

1. `0 failed`, `0 error`;
2. ⚠️ **`0 skipped`**. Windows'da skip bo'lsa — yig'ma topilmagan yoki build papkasi
   tozalangan, ya'ni kafolat o'lchanmagan. `ci_expected_skips.txt` dagi yozuvlar FAQAT
   Linux CI uchun.
   ⚠️ Bu shart endi **ikkinchi** qatlam: BESH modulning HAMMASI Windows'da `.exe`
   yo'qligida YIQILADI va `ESKIRGAN`/`ISBOTSIZ` holatda HAR platformada YIQILADI, ya'ni
   shart bajarilmasa 1-band ham qizil bo'ladi. Shartning o'zi SAQLANADI: build papkasi
   qisman tozalangan bo'lsa (`Analysis-00.toc` o'chirilgan) o'lchov yo'qolganini
   ko'rsatadigan eng qisqa signal shu;
3. reliz yozuviga `parity_harness.manba_xeshi()` qiymati yoziladi (qaysi manba
   tarqatilgani keyin ham ma'lum bo'lsin).

**Yig'ma boshqa joyda bo'lsa** (ildiz bitta o'zgaruvchidan keladi, ikki test moduli AYNI
ildizni o'qiydi va tengligi test bilan qulflangan):

| O'zgaruvchi | Ma'nosi | Standart |
|---|---|---|
| `BINOS_AGENT_BUILD_ROOT` | yig'ma ildizi | `~/binos-agent-build` |
| `BINOS_AGENT_EXE` | `.exe` ning to'liq yo'li | `<ildiz>/dist-onedir/BinOSDiscoveryAgent/BinOSDiscoveryAgent.exe` |
| `BINOS_AGENT_BUILD` | build papkasi (PYZ) | `<ildiz>/build-onedir/BinOSDiscoveryAgent` |

---

## 3b. WINDOWS CI DARVOZASI (`.github/workflows/windows-1c-gate.yml`)

Kanonik CI (`.github/workflows/ci.yml`) ning **8 job'i HAMMASI `ubuntu-latest`** da, shu
bois 1C yig'ma testlarining **72 tasi** Linux'da MUHIT sababi bilan skip bo'ladi
(`tests/ci_expected_skips.txt`: packaging 21 · portability 18 · parity 16 ·
packaged_e2e 14 · packaged_safety 3). Bu job o'sha 72 qobiliyatni **ROSTDAN bajaradi**.

### Nega ALOHIDA fayl va nega nomi «CI» EMAS

| Sabab | Tafsilot |
|---|---|
| 8/8 hisobi | Kanonik CI ga 9-job qo'shish reliz qarorlarida ishlatiladigan «8/8 SUCCESS» hisobini buzardi. |
| Deploy xavfi | `staging-deploy.yml` `on: workflow_run` + `workflows: ["CI"]` + `branches: [main]` ni kuzatadi. Nomi `Windows 1C Gate` bo'lgan workflow bu triggerga **MOS KELMAYDI**, ya'ni deploy'ni QO'ZG'ATA OLMAYDI. Ruxsatlar ham `contents: read` — release/deploy uchun token yo'q. |

### Trigger

```yaml
push:    branches: ["ci-proof/**"]   +   paths: [discovery_1c/**, discovery_agent/**,
         packaging/**, tests/test_agent_*, integrations/1c/**, workflow faylining o'zi]
workflow_dispatch:
```

⚠️⚠️ `main` ATAYLAB YO'Q (hozircha). Sabab: staging'ni amalda Railway'ning O'Z
trigger'i deploy qiladi va u `checkSuites=true` bilan SHA'ga biriktirilgan HAR BIR
workflow run'ining XULOSASINI baholaydi. Ya'ni bu darvoza `main` da ishlasa, staging
deploy endi uni HAM kutadi va u QIZIL bo'lsa deploy BLOKLANADI. Yo'nalish fail-closed
(xavfsiz tomon), lekin bu RELIZ MEXANIKASINING o'zgarishi, va darvozaning O'ZI hali
bir marta ham haqiqiy runner'da yurmagan. TARTIB: avval `ci-proof/**` da yashil
bo'lsin, KEYIN ega qarori bilan `main` qo'shiladi (bir qatorli o'zgarish).
⚠️ «Deploy'ni QO'ZG'ATMAYDI» ≠ «deploy'ga TA'SIR QILMAYDI»: nomi «CI» emasligi
faqat `staging-deploy.yml` ning `workflow_run` yo'lini yopadi, Railway'ning O'Z
check-suite kutishini YOPMAYDI.

⚠️ GitHub'da `branches` va `paths` **VA (AND)** bilan birlashadi. Ya'ni `ci-proof/**`
shoxiga shu yo'llarga TEGMAYDIGAN push job'ni ishga TUSHIRMAYDI — o'shanda
`workflow_dispatch` ishlatiladi. Bu cheklov workflow ichida ham izoh bilan yozilgan.

### Qadamlar ketma-ketligi

| # | Qadam | Nima isbotlanadi |
|---|---|---|
| 1-2 | `checkout@v4`, `setup-python@v5` (`3.12.10`, x64) | Interpretator **ANIQ** pinlangan — «3.12» EMAS (pastdagi «Tcl/Tk pini» ga qarang). |
| 3 | Python pinlangan interpretatormi | Versiya/bit/`tkinter` — mos kelmasa DARHOL qizil, 40 daqiqadan keyin emas. |
| 4 | Yig'ma ildizi repo TASHQARISIDAmi | `test_repo_tashqarisidagi_papkadan_yuradi` shuni TALAB qiladi; ildiz `RUNNER_TEMP\binos-agent-build` (`D:\a\_temp\...`), workspace esa `D:\a\<repo>\<repo>`. |
| 5 | Izolyatsiyalangan **buildenv** | `pyinstaller==6.22.3`, `--only-binary=:all:`; versiya TEKSHIRILADI; fastapi/sqlalchemy/pydantic/psycopg/httpx/pytest/pandas BO'LMASLIGI tekshiriladi (spec'ning `excludes` ro'yxati «omad» emas, HIMOYA bo'lib qolsin). |
| 6 | Izolyatsiyalangan **testenv** | `pytest==9.1.1`. Ikki venv AYNI interpretatordan — bytecode magic bir xil, aks holda hukm `ISBOTSIZ` bo'lardi. |
| 7 | **Manbadan toza `.exe`** | `--distpath <ildiz>\dist-onedir --workpath <ildiz>\build-onedir`; **build papkasi SAQLANADI** (`PYZ-00.pyz` va `Analysis-00.toc` darvozaga kerak). Ishlab chiquvchining yig'masi ISHLATILMAYDI va runner'da MAVJUD ham emas. |
| 8 | Hukm **TOZA** bo'lishi SHART | `parity_harness.yigma_tayyorligi()` — YANGI mexanizm YO'Q. |
| 9 | `.exe` SHA-256 + manba imzosi | Log + `$GITHUB_STEP_SUMMARY` + artefakt (§ pastda). |
| 10 | Deselect ro'yxati ESKIRMAGANMI | `--collect-only <nodeid>`; test qayta nomlansa chiqish kodi `4` → qizil. |
| 11 | **BESH modul** AYNI artefaktga qarshi | `-p no:randomly`, `--junitxml`. |
| 12 | **0 SKIP majburlash** | `packaging/ci_windows_gate_check.py gate` (`if: always()`). |
| 13 | **SALBIY NAZORAT** | Eskirgan artefakt QIZIL bo'lishi o'lchanadi (pastda). |
| 14 | Daraxt tiklangan + artefakt yana TOZA | `git diff --exit-code` + hukm qaytadan `TOZA`. |
| 15 | Da'vo chegarasi | Summary'ga `unsigned`, `UNVERIFIED_ON_REAL_1C`, `EPF_SOURCE_READY`, «deploy yo'q» yoziladi. |
| 16 | Isbot artefakti | FAQAT matnli fayllar. |

### MINIMAL PAKET TO'PLAMI va uning ASOSI

Yig'ish uchun **faqat PyInstaller** kerak; `pip install -e ".[dev]"` **SHART EMAS**.
O'lchangan asos:

- `app/services/discovery_agent/**` va `app/services/discovery_1c/**` dagi HAR BIR
  `import` — standart kutubxona (`argparse`, `collections.abc`, `contextlib`, `copy`,
  `dataclasses`, `datetime`, `functools`, `hashlib`, `json`, `math`, `ntpath`, `os`,
  `pathlib`, `platform`, `re`, `secrets`, `shutil`, `subprocess`, `sys`, `time`,
  `typing`, `unicodedata`) **yoki** `app.services.discovery_1c`. Uchinchi tomon paketi
  **BITTA ham yo'q**.
- `app/__init__.py` va `app/services/__init__.py` **BO'SH** (0 import), ya'ni paket
  ildizi server stack'ini tranzitiv TORTMAYDI.
- Spec `fastapi`/`starlette`/`uvicorn`/`pydantic`/`sqlalchemy`/`alembic`/`psycopg`/
  `httpx`/`pandas`/... ni `excludes` ga **ANIQ** yozadi.
- `tkinter` paket bilan EMAS, **Python o'rnatmasi bilan** keladi (`setup-python`
  Windows'da Tcl/Tk bilan beradi — qadam 3 shuni tekshiradi).

Testlar uchun **faqat `pytest`**: beshta modul va `tests/conftest.py` boshqa uchinchi
tomon paketini import qilmaydi (`pgserver` HIMOYALANGAN `try/except ImportError` ichida).
`-p no:randomly` plagin O'RNATILMAGAN bo'lsa ham xato bermaydi (bloklash ro'yxatiga
qo'shiladi, mavjudligi talab qilinmaydi).

### NEGA Python PATCH versiyasi ham pinlangan

`test_yigmadagi_tarmoqqa_QODIR_fayllar_royxati_OSMAYDI` tarqatiladigan papkadagi
tarmoqqa qodir fayllarning **ANIQ** ro'yxatini qulflaydi — ichida `_tcl_data/http1.0/
http.tcl` va `tcl8/8.6/http-2.9.8.tm` bor. Bu fayllar `tkinter` bilan **Python
o'rnatmasidan** keladi. `python-version: "3.12"` deyilsa patch versiyasi vaqt bilan
siljiydi, Tcl/Tk ham siljishi mumkin va darvoza **YOLG'ON QIZIL** bo'lardi. Shu bois
pin `3.12.10` — mahalliy reliz muhitida o'lchangan versiya (`PyInstaller 6.22.3`).

### 0 SKIP qanday MAJBURLANADI (va nega ishonchli)

`packaging/ci_windows_gate_check.py gate` junit faylini o'qiydi. Besh qatlam:

1. **Junit fayli yo'q bo'lsa — YIQILISH.** pytest INTERNALERROR bilan yiqilsa yoki
   umuman yurmasa, darvoza JIM yashil bo'lmaydi.
2. **Skip `<skipped/>` BOLA ELEMENTI bilan sanaladi**, `testsuite` atributi bilan EMAS
   (atribut pytest versiyalari orasida farq qilgan).
3. **Har modulning ENG KAM test soni TALAB qilinadi** (`--module <modul>:<son>`):
   parity 64 · packaging 26 · portability 22 · packaged_e2e 16 · packaged_safety 23
   = **151**. `-k` yoki `--deselect` bilan jimgina «hammasi yashil» qilish mumkin emas:
   tanlanmagan test junit'da UMUMAN bo'lmaydi, son kamayadi, job qizil. `>=` ishlatiladi
   — test QO'SHILSA yashil qoladi.
4. **`failure`/`error` ham SHU YERDA sanaladi** — pytest ning chiqish kodiga YOLG'IZ
   ishonilmaydi (quvur/qobiq kodni yo'qotishi mumkin).

⚠️ Qaror jadvalining O'ZI mahalliy Windows'da **sintetik junit** bilan o'lchangan:
toza/skip/yiqilish/son-kam/taqiq-buzilgan/fayl-yo'q — **6 holatning hammasi** kutilgan
javobni berdi.

### DESELECT YO'Q — langar `.exe` dan `PYZ-00.pyz` ga KO'CHIRILDI

⚠️ Bu bo'lim ilgari bitta testni (`test_hujjatdagi_EXE_XESHI_haqiqiy_yigmaga_MOS`)
ATAYLAB `--deselect` qilishni asoslardi. **U asos ENDI YO'Q va deselect OLIB
TASHLANDI** — beshta modulning **HAMMA 151 testi** shu job'da bajariladi.

NEGA o'zgardi (o'lchangan fakt): `.exe` **bayt-darajasida TAKRORLANUVCHAN EMAS** —
AYNI manba + AYNI build muhiti bilan ketma-ket ikki yig'ma ikki xil SHA-256 beradi
(o'lcham AYNI; sabab — PE sarlavhasidagi qurish vaqti tamg'asi/manifest). Shu bois
hujjatga `.exe` xeshini LANGAR qilib qadash CI'da ta'rif bo'yicha bajarilmaydigan
shart edi. **`PYZ-00.pyz` esa ikki yig'mada BAYT-BA-BAYT AYNI** (uning ichidagi
`co_filename` NISBIY, vaqt tamg'asi yo'q).

Shu bois:

- **LANGAR** — `build-onedir\BinOSDiscoveryAgent\PYZ-00.pyz` ning SHA-256'si.
  Hujjatda yozilgan va `tests/test_agent_portability.py::test_hujjatdagi_PYZ_XESHI_haqiqiy_yigmaga_MOS_va_EXE_TAKRORLANMASLIGI_OCHIQ`
  uni diskdagi haqiqiy PYZ bilan SOLISHTIRADI. Manba o'zgarib qayta qurilsa — xesh
  o'zgaradi va test QIZIL bo'ladi.
- **MOS YOZUVLAR** — `.exe` ning SHA-256'si hujjatda QOLADI (tarqatiladigan ANIQ
  artefaktni identifikatsiya qiladi, imzo YO'Q bo'lgani uchun operator uchun muhim),
  lekin TENGLIK talab qilinmaydi va hujjat uning **takrorlanuvchan emasligini OCHIQ
  yozadi** — buni ayni test TALAB qiladi (halollik gardi).

⚠️ QOLGAN XAVF, OCHIQ YOZILADI: PYZ tengligi FAQAT bitta mashinada, ikki yig'mada
o'lchangan. GitHub runner'da AYNI PYZ chiqishi **ISBOTLANMAGAN**. Agar runner'da
boshqa chiqsa — test HALOL QIZIL bo'ladi va bu yangi fakt bo'ladi: o'shanda langarni
`parity_harness.manba_xeshi()` ga (modullarning bytecode imzosiga) ko'chirish ko'rib
chiqiladi. Birinchi Windows yurishida `ci_windows_gate_check.py record` summary'ga
yozadigan `hujjat_pyz_mos` qiymatini AYNAN shu savol uchun kuzatish kerak.

⚠️ OCHIQ QOLGAN KAMCHILIK: hujjatdagi `.exe` xeshini endi HECH QANDAY avtomatik
nazorat tekshirmaydi (test faqat uning MAVJUDLIGINI va langardan boshqa ekanini
talab qiladi). Ya'ni u jimgina drift qila oladi. Imzo YO'Q bo'lgani uchun bu xesh —
operatorning yagona tekshirish vositasi, shu bois buni yopish ro'yxatda turadi
(taklif: mahalliy reliz yurishida tenglikni ham talab qiladigan shart).

### SALBIY NAZORAT: eskirgan artefakt QIZIL bo'lishi SHART

13-qadam MAVJUD mexanizmni ishlatadi (yonma-yon shtamp fayli YO'Q):

1. `app/services/discovery_agent/states.py` ga **modul darajasidagi bitta nom**
   qo'shiladi (`_CI_STALE_PROBE_SENTINEL = 1`). ⚠️ IZOH EMAS: §4 bo'shliq 4 ga ko'ra
   imzoga `co_filename` va qator jadvali kirmaydi, ya'ni izoh darvozani QO'ZG'ATMASDI.
2. `.exe` **O'ZGARMAYDI** — ya'ni «AYNI artefakt, YANGI manba» holati.
3. `yigma_tayyorligi()` **`ESKIRGAN`** bermasa — job qizil.
4. `tests/test_agent_packaging.py` **YASHIL bo'lsa** — job qizil («darvoza TESHIK»).
5. Tahrir `git checkout --` bilan QAYTARILADI (hukmdan OLDIN, `throw` qaytarishni
   o'tkazib yubormasin), 14-qadam esa daraxt tozaligini `git diff --exit-code` bilan va
   hukmning yana `TOZA` bo'lishini ISBOTLAYDI.

⚠️ Mexanizm mahalliy Windows'da o'lchandi: qo'shishdan OLDIN `eskirgan_modullar()`
**3 modul** qaytardi, qo'shishdan KEYIN **4 modul** (`states.py` QO'SHILDI), qaytargandan
keyin fayl xeshi BITTA baytga ham o'zgarmagan holda tiklandi va `git diff --exit-code`
nol berdi. Qo'shimcha matn BOM'siz UTF-8 va LF bilan yoziladi
(`[System.IO.File]::AppendAllText` — `Add-Content -Encoding utf8` Windows PowerShell 5.1
da BOM'ni faylning O'RTASIGA tushirardi).

### EXE SHA-256 QAYERGA yoziladi

`packaging/ci_windows_gate_check.py record` uchta joyga yozadi:

1. **job LOG'i** — `[record] EXE SHA-256 : <64 hex>`;
2. **`$GITHUB_STEP_SUMMARY`** — jadval: `.exe` SHA-256, o'lcham, manba imzosi
   (`parity_harness.manba_xeshi()`), nomzod commit (`GITHUB_SHA`), Python/PyInstaller,
   `unsigned`, `UNVERIFIED_ON_REAL_1C`, va hujjat-xeshi drifti;
3. **artefakt** — `agent-build-record.json` + `agent-build-record.md`.

⚠️ `.exe` ning O'ZI yuklanmaydi: artefakt IMZOLANMAGAN va uni yuklab tarqatish
«tarqatishga tayyor» degan da'voga o'xshardi. Artefaktga faqat MATN tushadi: junit,
pytest log'i, PyInstaller log'i, yig'ma imzosi, ikki venv'ning `pip freeze` ro'yxati.
`dist-onedir/` va natija paketlari YUKLANMAYDI.

### Runner'da yiqilishi MUMKIN bo'lgan joylar (hali O'LCHANMAGAN)

Bu workflow HALI GitHub'da yurgizilmagan. Quyidagilar **taxmin emas, ro'yxatga olingan
xavf**:

| Xavf | Nega | Belgi |
|---|---|---|
| Tcl/Tk fayl ro'yxati | `setup-python` ning `3.12.10` yig'masi mahalliy python.org yig'masidan boshqa Tcl/Tk bersa, `_TARMOQQA_QODIR_FAYLLAR` va `_RUXSAT_KENGAYTMA` ro'yxatlari O'SADI. | `test_yigmadagi_tarmoqqa_QODIR_fayllar_royxati_OSMAYDI` / `test_yigmadagi_kengaytmalar_hammasi_kutilgan` qizil |
| Runner yo'li yig'ma baytlarida | `_BU_MASHINA_NAQSHI` da `savdoos`, `apps\server`, `.venv`, `dist-onedir` BOR. Mahalliy o'lchov PyInstaller bu yo'llarni dist'ga yozmasligini ko'rsatadi, lekin runner'da yo'l BOSHQA. | `test_yigmada_BU_MASHINA_yoli_YOQ` / `test_yigmadagi_mutlaq_yollar_BU_foydalanuvchiga_tegishli_EMAS` qizil |
| `pyinstaller==6.22.3` wheel'i | `--only-binary=:all:` bilan wheel yo'q bo'lsa pip YIQILADI (ataylab fail-closed). | 5-qadam qizil, aniq sabab bilan |
| Windows Defender | Yangi qurilgan imzolanmagan `.exe` ni skanerlash yig'ishni va 40 ta yurishni SEKINLASHTIRADI. | 75 daqiqa chegarasiga urilish |
| `.exe` yurishlarining soni | portability + packaged_e2e + parity birgalikda ~40 marta `.exe` ni yurgizadi, har biri `--wait-seconds 6`. | sekin, lekin yashil |
| `pwsh` kodlashi | Qadam skriptlari UTF-8; `pwsh` (PowerShell 7) ularni UTF-8 deb o'qiydi. `shell: powershell` (5.1) bo'lsa BOM'siz UTF-8 **ANSI** deb o'qilib em-tire `”` ga aylanardi va PowerShell AQLLI QO'SHTIRNOQNI satr chegarasi deb qabul qilardi. **Shu bois `shell: pwsh` ANIQ yozilgan** va qo'shtirnoqli satrlar ichidan em-tire/backtick OLIB TASHLANGAN (mahalliy 5.1 parseri bilan o'lchangan: 13/13 blok toza). | parse xatosi |
| `tests/` ga yozilgan isbot fayllari | `pytest-junit.xml`, `*.log`, `agent-build-record.*` `apps/server` ga yoziladi — ular **kuzatilmagan** fayllar, `git diff --exit-code` ni BUZMAYDI. | — |

---

## 4. QOLGAN BO'SHLIQLAR (yozilmagani — yashirilgani bo'lardi)

1. ~~**Windows CI job'i YO'Q.**~~ **YOZILDI** — §3b. Workflow:
   `.github/workflows/windows-1c-gate.yml` (`windows-latest`, manbadan toza `.exe`
   quradi, BESH modulni AYNI shu artefaktga qarshi 0 skip bilan yurgizadi).
   ⚠️ QOLGAN BO'SHLIQ: workflow ROSTDAN GitHub'da yurgizilgani hali **O'LCHANMAGAN**
   (§3b «Runner'da yiqilishi MUMKIN bo'lgan joylar»). Shu bois `ci_expected_skips.txt`
   dagi BESH bo'lim HALI OLIB TASHLANMAYDI: ular Linux job'ining ratifikatsiya qilingan
   skip'lari va Windows job'i yashil bo'lganini KO'RGANDAN KEYIN qayta ko'rib chiqiladi
   (olib tashlash Linux backend job'ini QIZIL qilardi — skip'lar hamon chiqadi).
2. **Haqiqiy parity hozir YURMAYDI** — mahalliy `.exe` eskirgan (yuqoridagi uch modul).
   Darvoza to'g'ri ishlab yiqilyapti; yashil holat uchun **yig'mani qayta qurish KERAK**.
   Bu agentning ishi emas (yig'ish bu topshiriq doirasidan tashqarida).
   ⚠️ 2026-10-02 dan beri shu sababdan BESH darvozaning hammasi qizil: yig'ma TARKIBI
   (`21 failed`), PORTATIVLIK (`18 failed, 4 passed`), UCHIGA-UCH (`14 failed,
   2 passed`), TARQATILADIGAN BAYTLAR (`3 failed, 20 passed`) — bu KUTILGAN holat,
   nuqson emas. Qayta yig'ilgach hammasi yashil bo'ladi (as-built daraxtda o'lchangan:
   packaging `26 passed`, portability `22 passed`, e2e `16 passed`, safety `23 passed`,
   inventar `6 passed`, 0 skipped).
3. ~~**Yig'ma tarkibi darvozasi (`test_agent_packaging.py`) `.exe` yo'qligida Windows'da
   ham `skip`** bo'ladi; himoya **hujjatda**, kodda emas.~~ **YOPILDI 2026-10-02**
   (§2 dagi «IKKI DARVOZANING IKKISI HAM shu jadvalga tayanadi» bo'limi). Endi bu modul
   ham `parity_harness.yigma_tayyorligi()` hukmini oladi: `.exe` yo'qligi Windows'da
   YIQILISH, `ESKIRGAN`/`ISBOTSIZ` esa HAR platformada YIQILISH. Qolgan (kichik)
   bo'shliq: `.exe` yangi, lekin build papkasidan FAQAT `Analysis-00.toc` o'chirilgan
   holat — u ham endi skip emas, YIQILISH, lekin uni avtomatik TIKLASH yo'li yo'q
   (operator qayta yig'adi).
3b. ~~**PORTATIVLIK darvozasi (`test_agent_portability.py`) ildizni QOTIRGAN, `.exe`
   yo'qligida SHARTSIZ `skip` beradi va skip'lari `ci_expected_skips.txt` da YO'Q.**~~
   **YOPILDI 2026-10-02** (§2 dagi «UCHINCHI DARVOZA» bo'limi). Qolgan bo'shliq: bu
   modul `.exe` ni ROSTDAN yurgizadi, lekin **TOZA MASHINA isboti EMAS** (§9
   `APPROXIMATED`) va 1C hamon `RUNTIME-UNKNOWN` — darvoza buni o'zgartirmaydi,
   faqat ESKIRGAN artefaktning «portativ» deb tasdiqlanishini to'sadi.
3c. ~~**UCHIGA-UCH (`test_agent_packaged_e2e.py`) va TARQATILADIGAN BAYTLAR
   (`test_agent_packaged_safety.py`) darvozalari ildizni QOTIRGAN, SHARTSIZ `skip`
   beradi va skip'lari `ci_expected_skips.txt` da YO'Q.**~~ **YOPILDI 2026-10-02**
   (§2 dagi «TO'RTINCHI va BESHINCHI DARVOZA» bo'limi) + ALTINCHI nusxaga qarshi
   **INVENTAR QO'RIQCHISI** qo'shildi.
3d. **`test_agent_packaging.py` va `test_agent_portability.py` dagi SIMLASH tekshiruvi
   DOCSTRING tufayli ZAIF.** Ikkisi ham `inspect.getsource(_dist_talab)` MATNIDA
   chaqiruv nomini izlaydi, ularning docstringi esa o'sha nomlarni ESLATADI — ya'ni
   chaqiruv OLIB TASHLANSA ham tekshiruv YASHIL qoladi (bu to'rtinchi darvozada
   ROSTDAN o'lchandi: mutatsiya TUTILMADI). Yangi ikki modulda bu AST bilan tuzatildi
   (`_chaqirilgan_nomlar()`), ESKI ikkisida esa QOLDI — ular bu ishning TAQIQ
   ro'yxatida edi. Tuzatish: o'sha ikki modulda ham `_chaqirilgan_nomlar()` naqshiga
   o'tish (xulq o'zgarmaydi, faqat qo'riqchi tiriladi).
4. **Imzoga `co_filename` va qator jadvali KIRMAYDI.** Ya'ni faqat izoh/bo'sh qator
   o'zgargan fayl darvozadan «mos» bo'lib o'tadi. Bu ataylab: aks holda darvoza mantiqqa
   tegmaydigan o'zgarish uchun relizni to'xtatardi (yolg'on qizil). Oqibat: **izoh
   darajasidagi** manba farqi eskirgan yig'mada sezilmaydi.
5. **Darvoza `app.*` dan boshqa modulni tekshirmaydi.** Yig'uvchi Python'i yoki `tkinter`
   versiyasi almashsa, bytecode solishtirish buni ko'rmaydi (Python **magic** o'zgarsa
   ko'radi, patch versiyasi o'zgarsa ko'rmaydi).
