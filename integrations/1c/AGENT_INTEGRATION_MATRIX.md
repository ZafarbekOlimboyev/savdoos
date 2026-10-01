# AGENT INTEGRATSIYA MATRITSASI — 1C ULANISH STRATEGIYASI

Manba dalillari: `integrations/1c/extractor/BinOSDiscovery.bsl`,
`apps/server/app/services/discovery_1c/epf_audit.py`,
`apps/server/app/services/discovery_1c/runtime_bundle.py`,
`apps/server/app/services/discovery_1c/redact.py`,
`integrations/1c/OPERATOR_RUNBOOK.md`.
Darvoza testi: `apps/server/tests/test_agent_integration_matrix.py`.

---

## BU HUJJAT NIMA BERADI va NIMA BERMAYDI

**BERADI.** Beshta mumkin bo'lgan 1C ulanish yo'lining bir xil o'lchov bo'yicha baholanishi,
agent uchun PRIMARY/FALLBACK qarori va shu qarorni bloklagan ANIQ bo'shliqning yozilishi.

**BERMAYDI.** Birorta yo'l uchun bajarilish dalilini. Bu mashinada **1C:Enterprise
UMUMAN YO'Q** (pastdagi «O'LCHANGAN HOLAT»), shu bois integratsiya yo'llarining
PLATFORMA tomoni deyarli butunlay `RUNTIME-UNKNOWN`. Bu kamchilik emas — bu holatning
to'g'ri yozilishi.

---

## BU MASHINADA O'LCHANGAN HOLAT (taxmin EMAS)

| nima | o'lchov natijasi |
|---|---|
| 1C o'rnatmasi | `C:\Program Files\1cv8` YO'Q · `HKLM\SOFTWARE\1C\1Cv8` YO'Q |
| 1C binarlari | `1cv8.exe` · `1cestart.exe` · `ibcmd.exe` — PATH da YO'Q |
| COM klasslari | `V83.COMConnector` · `V82.COMConnector` · `V83.Application` · `V82.Application` — ro'yxatda YO'Q |
| Python paketlari | `pywin32` YO'Q · `pyinstaller` YO'Q · `tkinter` BOR · Python 3.12.10 |
| `.epf` konteyneri | repoda YO'Q — faqat `BinOSDiscovery.bsl` matni turadi |

⚠️ **SHU BOIS:** birorta yo'l bu yerda bajarilmagan. Yig'uvchi moduli Konfiguratorda
ochilmagan, sintaksis tekshiruvidan o'tmagan, hech qanday bazada yurmagan.

---

## HOLAT LUG'ATI (uchta, aralashtirilmaydi)

| holat | ma'nosi |
|---|---|
| `KNOWN` | **KOD MAJBURLAYDI.** Oxirgi ustunda aynan shu narsani majburlaydigan joy ko'rsatilgan: fayl, funksiya yoki qoida nomi. Kod o'zgarmaguncha natija AYNAN shunday. |
| `SOURCE-VALIDATED` | Manba matni va statik audit bilan tekshirilgan, lekin BAJARILMAGAN. Shartnoma mavjud; platforma javobi hali yo'q. |
| `RUNTIME-UNKNOWN` | Javob faqat real 1C mashinasida olinadi. Taxmin YOZILMAYDI. |

⚠️ `RUNTIME-UNKNOWN` **inkor DA'VOSI EMAS.** «Tekshirib bo'lmaydi» va «rad etildi» —
ikki boshqa narsa, va bu hujjatda ular aralashmaydi. Ayni qoida agent qatlamida ham
amal qiladi: «1C topilmadi» (`FAILED_NO_1C`) va «1C bor, lekin o'qiy olmadim»
(`FAILED_COLLECTOR_UNAVAILABLE`) ALOHIDA holatlar.

---

## 1-JADVAL — BESH YO'L

| # | yo'l | nima talab qiladi | xavfsizlik | kredensial oqimi | bu yerda sinaldimi | holat | MVP | sabab |
|---|---|---|---|---|---|---|---|---|
| 1 | external processor route — `ВнешниеОбработки.Создать`, operator qo'lda | 1C:Enterprise oynasi · Konfiguratorda qurilgan `.epf` · operator · BO'SH chiqish papkasi | FAQAT O'QISH: yozuv chaqiruvlari statik audit bilan taqiqlangan (`WRITE_OBJECT`, `POST_DOCUMENT`, `DELETE`); COM ham taqiqlangan (`EXTERNAL_CONNECTION`) | parolni 1C ning O'Z login oynasi oladi; agent uni KO'RMAYDI va saqlamaydi | YO'Q — 1C yo'q; faqat MANBA auditi va `OPERATOR_RUNBOOK.md` qadamlari | `SOURCE-VALIDATED` | HA | kirish nuqtasi manbada ROSTDAN bor (`ВыполнитьРазведку`), taqiqlar `epf_audit.py` bilan majburlangan, operator qadamlari `OPERATOR_RUNBOOK.md` da qulflangan — lekin birorta yurish BAJARILMAGAN |
| 2 | COMConnector / automation — `V83.COMConnector` | ro'yxatga olingan COM klassi · bitness MOSLIGI (x86/x64 1C ↔ Python) · `pywin32` · `Автоматизация` huquqi · ulanish satri | ulanish ochilgandan keyin agent IXTIYORIY BSL bajarishi mumkin — brief taqiqlagan qobiliyat; taqiqni kodda majburlash qiyin | ulanish satri (`Usr`/`Pwd`) jarayon xotirasida quriladi; ochiq matnli kredensial taqig'iga ZID | YO'Q — klass ro'yxatda yo'q, `pywin32` yo'q, demak chaqiruv TEKSHIRIB BO'LMAYDI | `RUNTIME-UNKNOWN` | YO'Q | uch sabab bir vaqtda: (a) tekshirib bo'lmaydi, (b) tashqi kutubxona (`pywin32`) talab qiladi — brief TAQIQLAYDI, (c) kredensialni agent QO'LIGA oladi. MVP da QURILMAYDI |
| 3 | 1C buyruq satri — `1cv8.exe ENTERPRISE /Execute`, `1cestart`, `ibcmd` | `1cv8.exe` yo'li · qurilgan `.epf` · paketli rejimda PARAMETR qabul qiladigan BSL kirish nuqtasi (bugun YO'Q) · parolsiz yoki OS-autentifikatsiyali baza | COM YO'Q, o'zboshimcha kod YO'Q: faqat auditdan o'tgan AYNI `.epf` yuritiladi — shu bois xavfsizlik yuzasi 1-yo'l bilan AYNI | ⚠️ `/P<parol>` parolni buyruq satrida qoldiradi va u JARAYON RO'YXATIDA ko'rinadi → TAQIQLANGAN. Parol kerak bo'lsa agent `FAILED_AUTH_REQUIRED` ga o'tadi | YO'Q — binar yo'q, `.epf` yo'q; buyruq qurilishi faqat MATN sifatida tekshirilgan | `RUNTIME-UNKNOWN` | HA — SHARTLI | PRIMARY sifatida SIMLANADI, lekin preflight darvozasi ortida: bugun `.epf` ham, parametr qabul qiladigan kirish nuqtasi ham YO'Q (pastdagi «BSL BO'SHLIG'I»), shu bois darvoza deterministik yiqiladi va 5-yo'lga tushadi |
| 4 | operator-opened session integration — operator ochgan sessiyaga tashqaridan qo'shilish | ishlab turgan 1C sessiyasiga TASHQARIDAN kod kiritish mexanizmi | sessiyaga tashqaridan kod kiritish — agentga «faqat o'qish» chegarasidan KENG qobiliyat beradi | — (agent ulanmaydi) | YO'Q — bizga MA'LUM bo'lgan qo'llab-quvvatlanadigan mexanizm yo'q, shu bois sinash predmeti ham yo'q | `RUNTIME-UNKNOWN` | YO'Q | ochiq sessiyaga TO'G'RIDAN-TO'G'RI qo'shilish uchun qo'llab-quvvatlanadigan API bizga ma'lum emas; mavjud mexanizmlar aslida 1-yo'l (operator `.epf` ni O'Z sessiyasida ochadi) va 5-yo'l (papka ko'prigi) — ya'ni bu qator ULAR BILAN QOPLANADI, alohida qurilmaydi |
| 5 | file/output-directory bridge — chiqish papkasini kuzatish | mavjud BO'SH papka · operator bir marta razvedkani boshlaydi · fayl tizimi | eng tor yuza: agent 1C ga ULANMAYDI, jarayon ochmaydi, faqat fayl O'QIYDI; paket shartnomaga mos bo'lmasa RAD etiladi | KREDENSIAL UMUMAN YO'Q — agent baza bilan gaplashmaydi; `locator` chiqishga yozilishdan oldin tozalanadi | HA — agent tomoni TO'LIQ sinaladi (sintetik paket fiksturalari); 1C tomoni sinalmagan | `KNOWN` | HA | majburlagan joylar: `REQUIRED_FILES` (olti majburiy artefakt), `validate_runtime_bundle` (papka validatori), `validate_runtime_members` (bayt validatori), `redact` (sir tozalash), `CHECK_NAMES` (deterministik tekshiruv tartibi) |

Beshta yo'l — `RUNTIME-UNKNOWN` **3**, `SOURCE-VALIDATED` **1**, `KNOWN` **1**.

⚠️ 2-qator inkor DA'VOSI EMAS: COM klassi ro'yxatda yo'qligi «COM rad etildi» degani
EMAS, «bu mashinada tekshirib bo'lmaydi» degani. MVP dan chiqarilish sababi — tekshirib
bo'lmasligi, tashqi kutubxona talabi va kredensial oqimi, uchovi birgalikda.

---

## 2-JADVAL — 3-YO'L ICHIDAGI UCHTA BINAR

| # | binar | nima qiladi | agent uchun qiymati | holat |
|---|---|---|---|---|
| 1 | `1cv8.exe ENTERPRISE /Execute <epf> /C<params>` | bazani Enterprise rejimida ochib `.epf` ni yuritadi | YAGONA nomzod: COM'siz, o'zboshimcha kodsiz, auditdan o'tgan AYNI modul | `RUNTIME-UNKNOWN` |
| 2 | `1cestart.exe` | ishga tushirish dispetcheri — ishni `1cv8.exe` ga uzatadi | QOBILIYAT QO'SHMAYDI: qo'shimcha qatlam, lekin chiqish kodi va xato matni ustidan nazoratni YO'QOTADI | `RUNTIME-UNKNOWN` |
| 3 | `ibcmd.exe` | server'siz infobase administratsiyasi (konfiguratsiya, dump/restore) | bizga MA'LUM hujjatlashtirilgan `.epf` yuritish verbi YO'Q; administrativ verblar esa razvedka uchun KERAK EMAS va xavflidir | `RUNTIME-UNKNOWN` |

⚠️ Shu bois 3-yo'l AYNAN `1cv8.exe` ga bog'lanadi: dispetcher ham, administrativ CLI ham
qo'shimcha qobiliyat bermaydi, lekin qo'shimcha noaniqlik beradi.

---

## BSL BO'SHLIG'I — ANIQ va BUGUN OCHIQ

Manbadan O'LCHANGAN fakt (`integrations/1c/extractor/BinOSDiscovery.bsl`, 2531 satr):

| fakt | o'lchov |
|---|---|
| eksport funksiyalari | AYNAN IKKITA: `ВыполнитьРазведку(КаталогВыгрузки, Режим, РазрешенныеЗонды)` va `ВыполнитьЗонд(ТипЗонда, ЦелевойОбъект)` |
| argumentsiz kirish nuqtasi | YO'Q — ikkovi ham argument TALAB qiladi |
| `ПараметрЗапуска` ni o'qiydigan joy | NOLTA uchrash |
| forma moduli / klient direktivalari | YO'Q — modul faqat ObjectModule |
| ilova ishga tushish ishlovchisi | YO'Q |
| `.epf` konteyneri | repoda YO'Q |

**Xulosa.** Paketli rejimda `/C<params>` 1C sessiyasiga `ПараметрЗапуска` satrini uzatadi,
va uni FAQAT kod o'qiy oladi. Mavjud modulda shu satrni o'qib `КаталогВыгрузки` ga
aylantiradigan kirish nuqtasi YO'Q. Demak `1cv8.exe ENTERPRISE /Execute` bugun
yig'uvchiga chiqish papkasini BERA OLMAYDI — bu ANIQ BO'SHLIQ, taxmin emas.

⚠️ **BU HUJJAT BSL NI O'ZGARTIRMAYDI.** Yig'uvchi manbasi boshqa agentning ishi. Bu yerda
faqat bo'shliq qayd etiladi va minimal talab yoziladi: paketli rejim uchun ARGUMENTSIZ
eksport kirish nuqtasi kerak, u `ПараметрЗапуска` dan chiqish papkasini (va faqat uni)
o'qib `ВыполнитьРазведку` ni chaqirsin; rejim DEFAULT `METADATA_ONLY` qolsin.

⚠️ **AGENT BU BO'SHLIQNI O'ZI ANIQLAY OLMAYDI.** `.epf` konteyneri ichidagi kirish
nuqtalarini agent o'qiy olmaydi. Shu bois bo'shliq agentga faqat NATIJASI bilan
ko'rinadi: chiqish papkasi bo'sh qoladi → kutish vaqti tugaydi →
`FAILED_COLLECTOR_UNAVAILABLE`. Bu QOBILIYAT CHEGARASI, yashirilmaydi.

---

## KREDENSIAL CHEKLOVI — `/P` TAQIQI

| qoida | matn |
|---|---|
| TAQIQ | Agent parolni buyruq satriga HECH QACHON qo'ymaydi. `/P<parol>` kaliti TAQIQLANGAN. |
| sabab | buyruq satri jarayon ro'yxatida ko'rinadi (Task Manager, WMI, audit jurnali) — ya'ni bu brief ning «ochiq matnli kredensial saqlash YO'Q» talabini buzadi. |
| oqibat | selected infobase `requires_auth` = `"true"` yoki `"unknown"` bo'lsa, agent 3-yo'lni BOSHLAMAYDI: `FAILED_AUTH_REQUIRED` ga o'tadi va `watch_folder` yo'lini TAKLIF qiladi. |
| nega `unknown` ham to'xtatadi | fail-closed: `UNKNOWN` ruxsatga aylanmaydi. Noma'lumlik «parol kerak emas» degani EMAS. |
| saqlash | agent kredensialni na faylga, na `environment.json` ga, na `agent_status.json` ga yozmaydi. `locator` chiqishga tushishdan OLDIN `redact` dan o'tadi. |
| 5-yo'lda | kredensial OQIMI UMUMAN YO'Q: parolni 1C ning O'Z oynasi oladi, agent uni ko'rmaydi. |

---

## PRIMARY va FALLBACK QARORI

**PRIMARY — `batch_execute`** (3-yo'l, `1cv8.exe ENTERPRISE /Execute`).
**FALLBACK — `watch_folder`** (5-yo'l, chiqish papkasini kuzatish; operator tomoni 1-yo'l).

Nega aynan shu ikkisi:

1. **2-yo'l (COM) chiqariladi** — tashqi kutubxona (`pywin32`) talab qiladi, brief TAQIQLAYDI;
   kredensialni agent qo'liga beradi; o'zboshimcha BSL bajarish qobiliyatini ochadi.
2. **4-yo'l chiqariladi** — to'g'ridan-to'g'ri qo'shilish uchun ma'lum mexanizm yo'q, va u
   aslida 1-yo'l + 5-yo'l kombinatsiyasi bilan qoplanadi.
3. **1-yo'l alohida yo'l EMAS** — u operatorning qadamlari, agentning ulanish usuli emas.
   Agent tomoni uchun u 5-yo'l ichida yashaydi.
4. Qolgan ikkisi: biri (`batch_execute`) bitta bosishda yakunlanadi va shu bois PRIMARY
   bo'lishga ARZIYDI; ikkinchisi (`watch_folder`) 1C ga umuman ulanmaydi va shu bois
   HAR DOIM mavjud zaxira bo'la oladi.

### PRIMARY preflight darvozasi (hammasi HA bo'lmasa — FALLBACK)

| # | shart | yiqilsa holat |
|---|---|---|
| 1 | muhit skanida kamida bitta o'rnatma va `1cv8.exe` yo'li topildi | `FAILED_NO_1C` |
| 2 | operator ko'rsatgan `.epf` fayli ROSTDAN mavjud | `FAILED_COLLECTOR_UNAVAILABLE` |
| 3 | nishon infobase tanlandi | `FAILED_NO_TARGET` |
| 4 | tanlangan baza `requires_auth` = `"false"` | `FAILED_AUTH_REQUIRED` → `watch_folder` taklifi |
| 5 | chiqish papkasi MAVJUD va BO'SH | `FAILED_SAFETY` |
| 6 | kutish vaqtida olti majburiy artefakt paydo bo'ldi | `FAILED_COLLECTOR_UNAVAILABLE` (3-shart bo'yicha bo'shliq ham shu yerda ko'rinadi) yoki `FAILED_TIMEOUT` |

⚠️ Ikki yo'l operator uchun BITTA workflow: UI faqat «Start Discovery» ko'rsatadi, yo'l
tanlash agent ichida bo'ladi va `agent_status.json` ning `route` maydonida qayd etiladi.

---

## E'TIROZ — ARXITEKTOR QARORIGA QISMAN

Arxitektorning TARTIBI qabul qilinadi (`batch_execute` PRIMARY), lekin bitta tuzatish bilan,
va men buni yolg'on kelishuvsiz yozaman:

**E'tiroz.** Bugungi repoda `batch_execute` **bajarilishi MUMKIN EMAS**: `.epf` konteyneri
yo'q va modulda paketli parametrni o'qiydigan kirish nuqtasi yo'q (yuqoridagi «BSL
BO'SHLIG'I»). Shu bois MVP da HAQIQATDA bajariladigan yo'l — `watch_folder`, va
`batch_execute` faqat preflight darvozasi ortidagi birinchi URINISH bo'lib qoladi.

**Amaliy talab (ikkisi ham):**
1. Kod `batch_execute` ni PRIMARY sifatida simlaydi, LEKIN darvoza yiqilganini
   `agent_status.json` ning `errors` va `notes` maydonlariga AYNAN sabab bilan yozadi va
   `route` ni `watch_folder` ga qo'yadi. Jimgina o'tish YO'Q.
2. Reliz yozuvlarida va operator hujjatida «bitta bosishda avtomatik» DEB TAKLIF
   QILINMAYDI: BSL bo'shlig'i yopilmaguncha operator baribir razvedkani O'ZI boshlaydi.

Agar BSL bo'shlig'i yopilsa va `.epf` qurilsa — e'tiroz tushadi, tartib o'zgarishsiz qoladi.

---

## NIMA SINALMAGAN (ochiq ro'yxat)

| nima | holat |
|---|---|
| birorta 1C yurishi | SINALMAGAN — bu mashinada 1C:Enterprise YO'Q |
| `1cv8.exe` buyruq satri | SINALMAGAN — binar yo'q |
| COM chaqiruvi | TEKSHIRIB BO'LMAYDI — klass ro'yxatda yo'q, `pywin32` yo'q |
| `.epf` kompilyatsiyasi va sintaksisi | SINALMAGAN — Konfigurator yo'q; faqat 1C mutaxassisi tekshira oladi |
| 1C aniqlash kodi (reestr va fayl tizimi skani) | FAQAT SINTETIK fikstura bilan sinaladi — HAQIQIY o'rnatmaga qarshi EMAS |
| paket validatori va fayl ko'prigi (agent tomoni) | sintetik paketlar bilan sinaladi; 1C tomoni baribir sinalmagan |
