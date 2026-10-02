# OPERATOR RUNBOOK — 1C razvedka yurishi (§9)

Manba: `integrations/1c/extractor/BinOSDiscovery.bsl`
Validator: `apps/server/app/services/discovery_1c/cli.py`
Paket shartnomasi: `apps/server/app/services/discovery_1c/runtime_bundle.py`
Darvoza testi: `apps/server/tests/test_discovery_1c_runbook.py`

> Bu hujjat **operator** uchun. Operator 1C mutaxassisi bo'lishi SHART EMAS. Har qadam —
> bitta amal. Har qadamda uch narsa yozilgan: **nima qilish**, **nima ko'rinishi kerak**,
> **boshqacha bo'lsa nima qilish**.

---

## 0. BOSHLASHDAN OLDIN — TO'RT SHART

Bu to'rt shartning birortasi qondirilmasa, **birinchi qadam ham boshlanmaydi**.

| # | shart | nega |
|---|---|---|
| 0.1 | Baza — **AJRATILGAN NUSXA**. Jonli bazada bu yurish BAJARILMAYDI. | Do'kon kassasi shu bazada savdo qilyapti. Nusxa tiklash tartibi: `integrations/1c/SANDBOX_RESTORE_RUNBOOK.md`. |
| 0.2 | **Egasining YOZMA roziligi** olingan (xat, xabar — og'zaki EMAS). | Bu birovning buxgalteriya bazasi. |
| 0.3 | **1C mutaxassisi** Konfiguratorda modulni ochib **sintaksis tekshiruvidan** o'tkazgan (`Ctrl+F7`) va xato chiqmagan. | 3-qadamga qarang. |
| 0.4 | Operator biladi: **bu modul birorta 1C bazasida hech qachon bajarilmagan.** | Ya'ni **birinchi yurishning O'ZI — sinov**. Natija «kutilgan» emas, **kuzatiladigan** narsa. |

**RUNTIME HOLATI: `RUNTIME-UNKNOWN`.** Bu modul 1C:Enterprise o'rnatilmagan mashinada
yozilgan: Konfiguratorda ochilmagan, sintaksis tekshiruvidan o'tmagan, hech qanday bazada
bajarilmagan. Shu bois bu runbookda natija haqida hech qanday runtime da'vosi berilmaydi —
faqat **nimani kuzatish** va **qachon to'xtash** yozilgan. Batafsil:
`integrations/1c/RUNTIME_READINESS.md`.

---

## ⚠️ BU TUGMALAR KERAK EMAS

Bu bo'lim **birinchi o'qiladi**. Quyidagi tugmalarning birortasi bu runbookda **umuman
kerak emas**. Ular razvedkaga hech narsa qo'shmaydi — razvedka faqat **o'qiydi**.

| tugma / buyruq | nima qiladi | nega bu runbookda KERAK EMAS |
|---|---|---|
| **Выгрузить в весы** | katalogni tarozi qurilmasiga yuboradi | Razvedka tarozi bilan almashmaydi. Bu tugma do'kon tarozilarining ishchi holatini o'zgartiradi. **KERAK EMAS.** |
| **Передать в весы** | yuqoridagining boshqa konfiguratsiyadagi nomi | Ayni narsa. **KERAK EMAS.** |
| **Загрузить** | tashqi fayldan bazaga ma'lumot **kiritadi** | Razvedka bazaga hech narsa kiritmaydi. Bu tugma mijoz ma'lumotini o'zgartiradi. **KERAK EMAS.** |
| **Синхронизировать** | boshqa tizim bilan ikki tomonlama almashinuvni boshlaydi | Razvedka birorta tashqi tizimga ulanmaydi. Bu tugma boshqa integratsiyalarni ishga soladi. **KERAK EMAS.** |
| **Записать** | ochilgan obyektni bazaga **yozadi** | Razvedka birorta obyektni ochmaydi va yozmaydi. **KERAK EMAS.** |
| **Провести** | hujjatni **o'tkazadi** — registr harakatlarini yaratadi | Razvedka hujjat o'tkazmaydi. Bu tugma qoldiq va hisobotlarni o'zgartiradi. **KERAK EMAS.** |
| **Удалить** | obyektni o'chirishga belgilaydi yoki o'chiradi | Razvedka hech narsa o'chirmaydi. **KERAK EMAS.** |

**Qoida:** bu ro'yxatdagi tugmani bosish — **to'xtash sharti** (pastdagi `T7`). Bosilgan
bo'lsa, yurish davom etmaydi va hodisa BinOS tomoniga xabar qilinadi.

---

## O'N QADAM

### 1-qadam. Qaysi 1C oynasiga kirish

**Nima qilish.** Ajratilgan nusxa bazasini **1C:Enterprise** oynasida ochish (Konfigurator
EMAS, `1cv8.exe` odatdagi ishga tushirish). Ro'yxatdan AYNAN nusxa bazasi tanlanadi.

**Nima ko'rinishi kerak.** Oyna sarlavhasida nusxa bazasining nomi va yo'li. Baza ro'yxatida
nusxa bazasi jonli bazadan AJRATILGAN nom bilan turadi.

**Boshqacha bo'lsa.** Oyna sarlavhasida jonli bazaning nomi yoki yo'li ko'rinsa — **DARHOL
yopish** va hech narsa bosmaslik (`T1`). Ro'yxatda nusxa umuman bo'lmasa — 0.1 sharti
qondirilmagan, yurish boshlanmaydi.

### 2-qadam. Tashqi qayta ishlashni ochish

**Nima qilish.** `Файл → Открыть` → `BinOSDiscovery.epf` faylini tanlash.

**Nima ko'rinishi kerak.** Qayta ishlash ochiladi.

**Boshqacha bo'lsa.**
- `.epf` fayli **berilmagan bo'lsa** — bu normal holat, va yurish shu yerda to'xtaydi (`T2`):
  repoda faqat `.bsl` matni turadi, `.epf` konteynerini 1C mutaxassisi quradi
  (`integrations/1c/extractor/README.md`, «`.epf` ni qurish»).
- Xato oynasi chiqsa (litsenziya, xavfsiz rejim, huquq) — **TO'XTASH** (`T5`): matnni
  to'liq ko'chirib olib BinOS tomoniga yuborish.

### 3-qadam. Qaysi tugma

**Nima qilish.** Qayta ishlash oynasida **BinOS razvedkasini boshlaydigan YAGONA tugma**
bosiladi. Uni 2-qadamdagi `.epf` ni qurgan 1C mutaxassisi qo'yadi va u `ВыполнитьРазведку`
funksiyasini chaqiradi.

**Nima ko'rinishi kerak.** Oynada chiqish papkasini ko'rsatadigan maydon va bitta tugma.

**⚠️ Boshqacha bo'lsa — va bu KUTILGAN holat.** Manbada **forma YO'Q**: modul faqat ikki
eksport funksiyasidan iborat (`ВыполнитьРазведку`, `ВыполнитьЗонд`). Ya'ni **tugma ham,
oyna ham hozir mavjud emas** — ularni 1C mutaxassisi qo'shadi. Oynada tugma bo'lmasa:

- operator **hech qanday boshqa tugmani izlamaydi** va bosmaydi (yuqoridagi ro'yxatga
  qarang);
- 1C mutaxassisi razvedkani kod bilan boshlaydi, AYNAN shu ko'rinishda:

```bsl
Обработка = ВнешниеОбработки.Создать("C:\binos\BinOSDiscovery.epf");
Результат = Обработка.ВыполнитьРазведку("C:\binos\out");   // rejim berilmadi = METADATA_ONLY
```

Uchinchi yo'l YO'Q: o'zboshimcha boshqa funksiya chaqirilmaydi.

### 4-qadam. `METADATA_ONLY` rejimini tanlash

**Nima qilish.** **Hech narsa qilmaslik.** `METADATA_ONLY` — **DEFAULT** rejim: rejim
argumenti berilmasa, AYNAN shu rejim qo'llanadi.

**Nima ko'rinishi kerak.** Oynada rejim tanlagich bo'lsa — `METADATA_ONLY` turgan bo'ladi.
Yurishdan keyin `run_status.json` faylida `"mode": "METADATA_ONLY"`.

**Boshqacha bo'lsa.** Oynada `APPROVED_PROBES` tanlangan bo'lsa — **uni tanlamaslik**. Aktiv
zondlar alohida qadam va ular FAQAT BinOS tomoni ANIQ ro'yxat (`(tur, nishon, sabab)`
uchliklari) berganda, alohida ruxsat bilan bajariladi. Rejim nomi noto'g'ri yozilsa
(`metadata_only`, bo'sh joy bilan) — modul uni noma'lum deb hisoblaydi va **`METADATA_ONLY`
ga tushadi** (fail-safe), sababi `run_status.json` ning `mode_note` maydonida qoladi.

### 5-qadam. Chiqish papkasini tanlash

**Nima qilish.** Yangi, **BO'SH** papka yaratish va uni chiqish papkasi qilib ko'rsatish.
Masalan `C:\binos\out`.

**Nima ko'rinishi kerak.** Papka **mavjud** va ichida **birorta fayl yo'q**.

**Boshqacha bo'lsa.**
- Papka **mavjud emas** — modul papka YARATMAYDI (`СоздатьКаталог` statik audit bilan
  taqiqlangan). Papkani operator oldin yaratadi.
- Papka **bo'sh emas** — **TO'XTASH** (`T3`). Bo'sh bo'lmagan papka ikki zarar beradi:
  (a) 9-qadamdagi validator shartnomada yo'q faylni ko'rib paketni RAD etadi; (b) eski fayl
  yangi yurishning natijasiga o'xshab qolishi mumkin. Boshqa BO'SH papka olinadi.
- Papka yo'lini **oxirida `\` yoki `/` bilan** yozmaslik: modul yo'lni matn qo'shish bilan
  quradi, ya'ni ikki ajratuvchi qolib ketadi.
- Papka **tarmoq diskida yoki USB'da** bo'lmasin: mahalliy disk olinadi.

### 6-qadam. Ishga tushirish (Run)

**Nima qilish.** 3-qadamdagi tugmani **bir marta** bosish va kutish. Boshqa hech narsa
bosilmaydi, oyna yopilmaydi.

**Nima ko'rinishi kerak.** Kutish belgisi. Davomiylik **oldindan noma'lum**: metadata o'qish
tez, `КОЛИЧЕСТВО(*)` sanoqlari esa katalog hajmiga bog'liq. Fayzan o'lchamidagi baza uchun
**1–5 daqiqa** deb BAHOLANGAN — bu **o'lchov emas**, chunki hech qachon o'lchanmagan.

**Boshqacha bo'lsa.**
- Xato oynasi chiqsa — matnni **to'liq** ko'chirib olib **TO'XTASH** (`T5`).
- 1C **parol so'rasa** — **DARHOL TO'XTASH** (`T4`). Operator parol kiritmaydi.
- 30 daqiqadan oshsa yoki 1C javob bermay qolsa — **TO'XTASH** (`T8`): tugma QAYTA
  bosilmaydi, BinOS tomoniga xabar beriladi.
- Tugmani ikki marta bosib yuborilgan bo'lsa — papkada ikki yurishning fayllari aralashadi.
  Papka tozalanmaydi: hodisa xabar qilinadi va **yangi BO'SH papka** bilan boshidan
  boshlanadi.

### 7-qadam. Qaysi fayllar paydo bo'lishi kerak

**Nima qilish.** Chiqish papkasini ochib fayllarni **sanash**.

**Nima ko'rinishi kerak — YETTI ARTEFAKT:**

| # | fayl | shartnoma | majburiy | mazmuni |
|---|---|---|---|---|
| 1 | `export.json` | `binos-1c-export-v1` | HA | metadata razvedkasi va sanoqlar |
| 2 | `metadata.json` | `binos-1c-metadata-v1` | HA | konfiguratsiyada umuman nima bor |
| 3 | `run_status.json` | `binos-1c-run-v1` | HA | rejim, vaqtlar, bo'limlar, umumiy holat |
| 4 | `errors.json` | `binos-1c-errors-v1` | HA (bo'sh bo'lishi mumkin) | strukturali xatolar |
| 5 | `run_summary.md` | — | HA | operator uchun: nima bo'ldi |
| 6 | `manifest.json` | `binos-1c-manifest-v1` | HA | har fayl uchun bayt hajmi va SHA-256 |
| 7 | `probes/NN_<tur>.json` | `binos-1c-probe-v1` | YO'Q | FAQAT `APPROVED_PROBES` rejimida |

**⚠️ `status.json` va `summary.md` deb ATALGAN fayl bu papkada BO'LMAYDI.** Ular boshqa
hujjatning (`binos-1c-discovery-v1` to'plamining) a'zolari va ularni BinOS tomonidagi
adapter quradi. Shu nomli fayl papkada ko'rinsa — bu boshqa papka yoki eski fayl (`T3`).

**Nima qilish (birinchi o'qish).** `run_summary.md` ni ochib o'qish: u odam uchun yozilgan.
Undagi «Holat (oldindan)» — **oraliq** qiymat; **qat'iy holat** `run_status.json` ning
`overall` maydonida.

**Boshqacha bo'lsa.**
- Papka **bo'sh** — modul ichidan tutilmagan istisno chiqqan. **TO'XTASH** (`T5`): xato
  oynasining matni yuboriladi.
- 1–6 dan **birortasi yo'q** — paket to'liq emas. Qolgan fayllar **o'chirilmaydi**: ular
  BinOS tomonida nima bo'lganini aniqlaydigan yagona dalil. 8-qadamga o'tiladi va
  nimalar borligi xabar qilinadi.
- `METADATA_ONLY` rejimida `probes/` papkasi yoki zond fayli ko'rinsa — bu **ziddiyat**.
  Validator uni RAD etadi; hodisa xabar qilinadi.

### 8-qadam. Paketni papkaga / USB'ga olish

**Nima qilish.** Chiqish papkasini **butun holida** (ichidagi `probes/` bilan birga)
nusxalash. Nusxadan hech narsa **olib tashlanmaydi** va hech narsa **qo'shilmaydi**.

**Nima ko'rinishi kerak.** Nusxada AYNAN o'sha fayllar, AYNAN o'sha nomlar bilan.

**Boshqacha bo'lsa.**
- Faylni **ochib tahrirlash TAQIQLANGAN.** `manifest.json` da har faylning SHA-256 xeshi bor;
  bitta harf o'zgarsa validator mos kelmaslikni ko'rsatadi va paket RAD etiladi. Bu
  **himoya**, to'siq emas: tahrirlangan paket ustida chiqarilgan xulosa yolg'on bo'lardi.
- Fayllar **arxivga** olinsa — parolsiz oddiy `.zip`, papka tuzilmasi SAQLANGAN holda.
- Paketni yuborishdan oldin ma'lumot minimallashtirish bo'limi o'qiladi:
  `integrations/1c/extractor/README.md` → «Chiqishni yuborishdan oldin».

### 9-qadam. Validator bilan tekshirish

**Nima qilish.** BinOS tomonidagi (1C mashinasi EMAS) kompyuterda, `apps/server` papkasidan:

```
cd apps/server
python -m app.services.discovery_1c.cli validate-runtime-bundle C:\binos\out
```

Mashina o'qiydigan shakl kerak bo'lsa — oxiriga `--json` qo'shiladi.

**Nima ko'rinishi kerak.** Har tekshiruv uchun bitta qator (`[OK]` yoki `[NUQSON]`), oxirida
`XULOSA`. **Chiqish kodi — shartnoma va u UCH HOLATLI:**

| kod | ma'nosi | keyin nima |
|---|---|---|
| `0` | paket TO'G'RI **va** yurish TO'LIQ (`run_status.json`.`overall` = `SUCCESS`) | 10-qadamga o'tiladi — FAQAT shu kodda |
| `1` | paket NOTO'G'RI: sxema, sir, xesh yoki ziddiyat nuqsoni bor — fayllarga ISHONIB BO'LMAYDI | **TO'XTASH** (`T6`) — paket keyingi qadamga O'TMAYDI |
| `2` | paket to'g'ri, LEKIN yurish TO'LIQ EMAS (`overall` = `PARTIAL`/`FAILED`); **yoki** buyruqning O'ZI xato yozilgan | **TO'XTASH** (`T9`) — quyidagi «ikki ma'no» bandiga qarang |

Windows'da chiqish kodi: `echo %ERRORLEVEL%`; PowerShell'da: `$LASTEXITCODE`.

**⚠️ `2` NING IKKI MA'NOSI VA ULARNI AJRATISH.** Ikkisi ham «TO'XTA, keyingi bosqichga
o'tma» degani va ikkisi ham `1` EMAS («paket yaroqsiz» degan hukm emas). Farqi CHIQISHDA
ko'rinadi:
- ekranda tekshiruv qatorlari va `XULOSA` bor → bu **paket haqidagi** hukm: yurish to'liq
  tugamagan. `run_status.json` dagi `overall` o'qiladi, keyin `sections` ichidan `failed`
  qator va `families` ichidan `unreadable` qator TOPILADI — sabab aynan o'sha yerda. Matn
  to'liq ko'chirilib BinOS tomoniga yuboriladi. Paket o'chirilmaydi, tahrirlanmaydi,
  yig'uvchi QAYTA ishga tushirilmaydi.
- ekranda tekshiruv qatorlari YO'Q, faqat xato satri (`usage:` yoki noma'lum bayroq) → bu
  **buyruq** xatosi, paket haqidagi hukm EMAS: buyruq to'g'rilanadi va qayta bajariladi.

**⚠️ Kod `0` nimani ISBOTLAYDI:** papkadagi **baytlar** shartnomaga mos, ichida sir yo'q,
sanoqlar matn, xeshlar mos, yig'uvchining O'ZI e'lon qilgan `overall` `SUCCESS` va u
hisoblangani bilan ZIDDIYATSIZ, ya'ni keyingi qatlamlar shu paketdan qurila oladi.
**Nimani ISBOTLAMAYDI:** modulning 1C dagi xatti-harakatini va topilgan nomzodning
to'g'riligini. Runtime holati `0` dan keyin ham `RUNTIME-UNKNOWN` bo'lib qoladi.

**Boshqacha bo'lsa.**
- Kod `1` — **TO'XTASH** (`T6`). Paket «tuzatilmaydi»: validatorda ataylab tuzatish bayrog'i
  YO'Q. Chiqish matni to'liq ko'chirilib BinOS tomoniga yuboriladi. Paket o'chirilmaydi.
- Kod `2` — **TO'XTASH** (`T9`). Yuqoridagi «ikki ma'no» bandi bo'yicha qaysi holat ekani
  aniqlanadi va shu holat uchun yozilgani bajariladi.
- Kod `0` ham, `1` ham, `2` ham emas — kutilmagan holat, xabar qilinadi.

### 10-qadam. AI analitikka berish

**Nima qilish.** Kod `0` bo'lgan paketni BinOS tomoniga topshirish. Analitik yuki (`ai`
qatlami) **BinOS mashinasida** quriladi.

**⚠️ FAQAT KOD `0`.** Kod `1` ham, kod `2` ham bu qadamga o'tish HUQUQINI bermaydi: `1` —
fayllarga ishonib bo'lmaydi, `2` — yurishning O'ZI to'liq tugamagan (`overall` `SUCCESS`
emas). Ilgari bu darvoza YO'Q edi va YIQILGAN yurish AI qatlamiga o'tib ketardi, ya'ni
to'liqsiz razvedka ustida xulosa chiqarilardi — topilmagan oila «bu konfiguratsiyada yo'q»
bo'lib ko'rinardi.

**Nima ko'rinishi kerak.** 9-qadam chiqishida `ai_kirishiga_tayyor` qatori `[OK]` va
detalida «YUBORILMADI, tarmoq YO'Q». Ya'ni yuk QURILDI, lekin hech qayerga yuborilmadi:
yuborish qarori alohida va u operatorning qadami EMAS.

**Boshqacha bo'lsa.**
- `ai_kirishiga_tayyor` `[NUQSON]` bo'lsa — kod `1` bo'ladi va `T6` amal qiladi.
- **1C mashinasidan hech narsa yuborilmaydi.** Razvedka paketi tarmoqqa chiqmaydi: uni
  operator qo'lda olib o'tadi.
- AI qaytargan har qanday taxmin **dalil emas**: u odam tasdig'isiz `CANDIDATE` darajasidan
  oshmaydi (`app/services/discovery_1c/confirmations.py`). Operator AI javobiga tayanib 1C da
  hech narsa qilmaydi.

---

## TO'XTASH SHARTLARI

Quyidagi holatlarda operator **DARHOL to'xtaydi** va **hech narsa qilmaydi**: tugma
bosmaydi, faylni tahrirlamaydi, papkani tozalamaydi, qayta ishga tushirmaydi. Faqat
ko'rganini yozib oladi (ekran surati + matn) va BinOS tomoniga yuboradi.

| kod | shart | nega DARHOL |
|---|---|---|
| `T1` | Baza **jonli** ekani aniqlandi (oyna sarlavhasi, yo'l, kassaning ishlayotgani) | Har qanday keyingi amal mijozning savdo bazasiga tegadi. |
| `T2` | `.epf` fayli **berilmagan** yoki nomi boshqa | Boshqa faylni ochish — nima bajarilayotgani noma'lum bo'lishi. |
| `T3` | Chiqish papkasi **bo'sh emas**, yoki unda `status.json` / `summary.md` bor | Eski va yangi fayllar aralashsa, paket ustida chiqarilgan xulosa yolg'on bo'ladi. |
| `T4` | 1C **parol** yoki hisob ma'lumotini so'radi | Operator parol kiritmaydi. Parolni faqat egasi yoki uning 1C mutaxassisi biladi. |
| `T5` | **Xato oynasi** chiqdi (istalgan matn bilan) yoki papka bo'sh qoldi | Xato matni — bizdagi yagona dalil. «Yopib qayta urinish» uni yo'qotadi. |
| `T6` | Validator **`1`** qaytardi | Fail-closed: paket keyingi qadamga o'tmaydi. Paket o'chirilmaydi ham. |
| `T7` | «BU TUGMALAR KERAK EMAS» ro'yxatidagi tugma **bosildi** | Baza holati o'zgargan bo'lishi mumkin. Nusxa qayta tiklanadi. |
| `T8` | Yurish **30 daqiqadan** oshdi yoki 1C javob bermay qoldi | Qayta bosish ikkinchi yurishni boshlab, papkani aralashtirib yuboradi. |
| `T9` | Validator **`2`** qaytardi: paket to'g'ri, lekin `run_status.json`.`overall` `SUCCESS` EMAS (`PARTIAL`/`FAILED`) — yoki buyruqning o'zi xato yozilgan | Yurishning O'ZI to'liq tugamagan: bo'lim `failed` yoki oila `unreadable`. To'liqsiz razvedka ustida chiqarilgan xulosa yolg'on bo'ladi — topilmagan oila «yo'q» bo'lib ko'rinadi. Qayta ishga tushirish sababni yo'qotadi. |

**Umumiy qoida:** shubha bo'lsa — **to'xtash**. To'xtash arzon; jonli bazadagi o'zgarish
qaytarilmaydi.
