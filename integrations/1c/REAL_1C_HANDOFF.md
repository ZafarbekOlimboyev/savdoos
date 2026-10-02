# REAL 1C HANDOFF — haqiqiy 1C mashinasida nima qilinadi

> ## HOLAT: `EPF_SOURCE_READY`
>
> Repoda **manba matni** bor. `.epf` konteyneri **yig'ilmagan va repoda YO'Q** — bu mashinada
> 1C:Enterprise platformasi o'rnatilmagan, demak manba kompilyatsiya qilinmagan, sintaksis
> tekshiruvidan o'tmagan va hech qanday 1C bazasida ishlatilmagan.
>
> Bu hujjat **tayyor mahsulot topshirmaydi**. U keyingi odam — 1C mutaxassisi — uchun
> **aniq qadamlar, aniq xeshlar va aniq nazorat ro'yxati** beradi. Designer'dagi har bir
> mexanik qadam `UNVERIFIED_ON_REAL_1C`.
>
> ⚠️ Bu hujjatda **sir yo'q**: na parol, na ulanish satri, na mijoz yo'llari. Kod repo
> ommaviy bo'lishi mumkin.

---

## 1. Aniq manba: nima topshiriladi

| narsa | qiymat |
|---|---|
| Repo commit (manba holati) | `cea2133f1bc2bd6460d25bcdea16b54d1a433a13` (qisqa: `cea2133`) |
| Muzlatilgan yig'uvchi | `integrations/1c/extractor/BinOSDiscovery.bsl` |
| — satrlar | 2531 |
| — sha256 (satr oxiri normallashtirilgan UTF-8 matn) | `3e5f88508e25ae87516898b1f6a0c66e686c98be30a5b56ca111d19370904208` |
| Ko'prik qatlami (yangi) | `integrations/1c/collector/BinOSDiscoveryCollector.bsl` |
| Ko'prik kimligi | `integrations/1c/collector/VERSION.json` → `BinOSDiscoveryCollector` / `0.1.0-source` |
| Yig'ish ko'rsatmasi | `integrations/1c/collector/BUILD.md` |
| Kutilgan `.epf` nomi | `BinOSDiscoveryCollector.epf` |

⚠️ **Yig'uvchi manbasi Phase 4 da muzlatilgan.** Unga **bir belgi ham qo'shilmaydi**;
yuqoridagi xesh `apps/server/tests/test_agent_collector_source.py` da pin qilingan va
o'zgarsa to'plam qizil bo'ladi. Xesh **normallashtirilgan** matndan olinadi, chunki
Windows checkout faylga CRLF qo'shadi va bayt-bayt pin o'zgarishga aloqasi yo'q sabab bilan
buzilardi.

⚠️ **Ko'prik qatlami mustaqil modul EMAS, FRAGMENT.** U yig'uvchi bilan **bir** ObjectModule
da yashaydi. Sabab va tartib — `collector/BUILD.md`.

---

## 2. Designer'da qanday ochish va yig'ish

⚠️ **`UNVERIFIED_ON_REAL_1C`** — quyidagi mexanika bu mashinada sinab ko'rilmagan. Agar
Designer boshqa narsa so'rasa, **taxmin qilinmaydi**: qadam to'xtatiladi va farq qayd etiladi.

1. **Ajratilgan nusxa.** Jonli bazada **hech narsa ochilmaydi**. Zaxira alohida (do'kon
   LAN'idagi) kompyuterga tiklanadi va hamma ish **o'sha nusxada** bajariladi.
2. Designer → **Fayl → Yangi → Tashqi qayta ishlash**.
3. Qayta ishlash nomi: `BinOSDiscoveryCollector`.
4. **ObjectModule** ni ochib, unga **avval** `extractor/BinOSDiscovery.bsl` ning to'liq
   matnini qo'ying — **o'zgartirmasdan**.
5. **So'ng** shu modulning **oxiriga** `collector/BinOSDiscoveryCollector.bsl` ning to'liq
   matnini qo'shing.
6. **Sintaksisni tekshirish** (Designer → Matn → Modul sintaksisini tekshirish). ⚠️ Bu
   **birinchi haqiqiy tekshiruv**: bu yerga qadar modul hech qachon kompilyator ko'rmagan.
   Har bir xato **yozib olinadi** va repoga qaytariladi — tuzatish manbada bo'ladi, Designer
   ichida emas.
7. Ishga tushirish yo'li (`collector/BUILD.md` ning «Ko'prikni qanday ishga tushirish»
   bo'limi): **A yo'li** — bitta tugmali forma qo'shib, tugmani `ВыполнитьМостРазведки()` ga
   bog'lash; **B yo'li** — formasiz, platformaning `/Execute` qoidasiga suyanish.
   ⚠️ B yo'lining qoidasi bu yerda isbotlanmagan; A yo'li operator ishini talab qiladi.
8. **Saqlash**: `BinOSDiscoveryCollector.epf`.

### Nega tartib muhim

- ⚠️ `Перем` **birinchi protseduradan oldin** bo'lishi shart, shu bois ko'prik fragmentida
  modul o'zgaruvchisi **yo'q** va u faqat **oxiriga** qo'shiladi. Teskari tartib
  kompilyatsiyani yiqitadi.
- ⚠️ Bir modulda **bir xil nom** bo'lmaydi. Ko'prikning hamma nomi `Мост` bilan boshlanadi
  va nomlar kesishmasligi test bilan qulflangan — lekin bu faqat **manba** faktini
  isbotlaydi, kompilyatsiyani emas.

---

## 3. `.epf` xeshi: ish oqimi

`.epf` — ikkilik konteyner va u **repoda saqlanmaydi**. Uning o'rniga **provenansi** qayd
etiladi:

1. `.epf` saqlangach, uning **sha256** i va **bayt hajmi** olinadi:
   ```
   certutil -hashfile BinOSDiscoveryCollector.epf SHA256
   ```
2. Olingan qiymat **ikki manba faylining xeshi bilan birga** qayd etiladi:
   | maydon | qiymat |
   |---|---|
   | `extractor_sha256` | yuqoridagi jadvaldan |
   | `bridge_sha256` | `collector/BinOSDiscoveryCollector.bsl` ning sha256 i |
   | `epf_sha256` | 1-qadamdan |
   | `epf_bytes` | fayl hajmi |
   | `built_by` | yig'gan odam |
   | `built_on` | 1C platformasi versiyasi (aniq reliz raqami) |
3. Shu yozuv `.epf` bilan **birga** yuboriladi. Operator mashinasidagi `.epf` xeshini
   qayta o'lchab solishtirish — **yagona** yo'l: «men yig'gan fayl shu» deyish.

⚠️ **Xesh «ishlaydi» degani emas.** U faqat **aynan shu baytlar** ekanini isbotlaydi.
Modulning to'g'ri ishlashi 5-bo'limdagi pilot bilan aniqlanadi.

⚠️ **`.epf` ning takrorlanadigan (bit-for-bit) yig'ilishi KAFOLATLANMAYDI.** 1C konteyneri
vaqt belgisi va ichki tartibni saqlashi mumkin, ya'ni ikki marta yig'ilgan `.epf`
xeshlari farq qilishi **normal**. Shu bois xesh **qurilgan nusxani kuzatish** uchun,
takrorlanish dalili sifatida **emas**.

---

## 4. Kutilgan yurish protokoli

Ko'prik agent bilan **fayllar orqali** gaplashadi. Buyruq satri parametri, COM va
o'ylab chiqarilgan kalit **yo'q**.

### Yurish papkasi

```
%LOCALAPPDATA%\BinOS\Discovery\runs\<run_id>\
    BinOSDiscoveryCollector.epf      <- agent nusxalaydi
    request.json                     <- AGENT yozadi
    bundle\                          <- AGENT yaratadi, BO'SH bo'lishi SHART
        probes\                      <- AGENT yaratadi (faqat zond ruxsat etilganda)
    response.json                    <- KO'PRIK yozadi
    bridge_done.json                 <- KO'PRIK yozadi, ENG OXIRIDA
```

⚠️ Papka **manba daraxtidan tashqarida** va **admin huquqi kerak emas**. Agent **faqat o'z**
yurish papkasini yaratadi; papka **bo'sh** bo'lishi shart (`RUN_DIR_NOT_EMPTY`).
**Wildcard o'chirish yo'q**, umumiy global natija fayli yo'q. Chiqish **UTF-8**, BOM'siz.

⚠️ **Papkalarni ko'prik yaratmaydi** — katalog yaratish statik audit bilan taqiqlangan.
`bundle\` yo'q bo'lsa ko'prik `OUTPUT_DIR_MISSING` bilan rad etadi; `probes\` yo'q bo'lsa
zond fayllari yozilmaydi va sabab `bundle\errors.json` ga tushadi. Bu **qobiliyat chegarasi**.

### Uch fayl

| fayl | shartnoma | kim yozadi | qachon |
|---|---|---|---|
| `request.json` | `binos-bridge-request-v1` | AGENT | ko'prikdan oldin |
| `response.json` | `binos-bridge-response-v1` | KO'PRIK | yurishdan keyin |
| `bridge_done.json` | `binos-bridge-done-v1` | KO'PRIK | **eng oxirida** |

`request.json` maydonlari: `request_version` · `run_id` · `nonce` · `requested_at` ·
`output_dir` · `expected_collector{name,version}` · `target_fingerprint` · `mode` ·
`allowed_probes` · `notes`

`response.json` maydonlari: `response_version` · `run_id` · `nonce` ·
`collector{name,version}` · `target_fingerprint` · `status` · `started_at` · `finished_at` ·
`notes`

`bridge_done.json` maydonlari: `done_version` · `run_id` · `nonce` · `written_at`

⚠️ **Phase 4 paketining `manifest.json` i o'zgarmaydi.** U `bundle/` ichida qoladi va o'z
navbatida oxirgi yoziladi. `bridge_done.json` — **qo'shimcha** qatlam: avval
`bundle/manifest.json` (paket to'liq mi), keyin `bridge_done.json` (yurish tugadi mi).

⚠️ **Javob yozilmasa belgi ham yozilmaydi**: belgi «javob diskda» degan ma'noni bildiradi.

### `status`

| qiymat | manbasi |
|---|---|
| `SUCCESS` / `PARTIAL` / `FAILED` | `bundle/run_status.json`.`overall` dan **diskdan o'qilgan** |
| `BRIDGE_REJECTED` | ko'prik yurishni **boshlamadi** (so'rov tekshiruvdan o'tmadi) |

⚠️ Yangi lug'at yasalmagan: uchta qiymat yig'uvchining o'z lug'atidan olingan.

⚠️ **`BRIDGE_REJECTED`, `REJECTED` emas — topilgan to'qnashuv.** `REJECTED` yig'uvchida
allaqachon bor, lekin boshqa ma'noda: u `bundle/errors.json` ning `code` lug'atidagi
qiymat (`WRITE_FAILED | PROBE_FAILED | REJECTED | UNHASHABLE`) va **rejim** rad
etilganini bildiradi. Bir xil so'z ikki shartnomada aynan `status.json` /
`run_status.json` chalkashuvini keltirardi.

### Kimlik va kredensial

⚠️ **Parol hech qayerga tushmaydi** — `argv`, jurnal, natija fayli, doimiy konfiguratsiya,
buyruq tarixi. Ishga tushirishda faqat `/F<yo'l>` yoki `/S<server>`; foydalanuvchi va parol
kalitlari **taqiqlangan** va agent tomonida `collector_bridge._assert_no_credentials`
darvozasi bilan majburlanadi. Parolni **1C ning o'z oynasi** oladi.

⚠️ **Xom `locator` protokolga yozilmaydi** (u sir bo'lishi mumkin) — faqat
`target_fingerprint`: `kind` + `name` + `locator` ning sha256 i.

⚠️ **`target_fingerprint` nishon to'g'riligining dalili EMAS.** Ko'prik uni **qayta aytadi**,
tekshirmaydi: xeshni qayta hisoblash uchun unda kirish ma'lumoti yo'q. U faqat javobni
so'rovga **bog'laydi**. Nishon kimligining mustaqil dalili — `bundle/metadata.json`
(konfiguratsiya inventarizatsiyasi).

### `notes` va kimlik shakli

⚠️ **`notes` — matnlar MASSIVI va unga faqat KOD tushadi.** Xom 1C xato matni
protokolga **yozilmaydi**: `ОписаниеОшибки()` fayl yo'lini o'z ichiga olishi mumkin va
agent tomonidagi `notes` darvozasi shubhali qiymat ko'rsa **butun hujjatni rad etadi**.
Tafsilot **operatorga 1C oynasida** ko'rsatiladi; paketli ishga tushirishda u ko'rinmaydi va
bu **ochiq chegara**.

⚠️ **Kimlik shakli yozishdan OLDIN tekshiriladi:** `run_id` bo'sh emas, `nonce` — 32–128
ta **kichik** hex belgi, `target_fingerprint` — **aynan 64** ta kichik hex belgi. Shakl
buzuq bo'lsa ko'prik **hech narsa yozmaydi** (buzuq kimlikli javobni agent ajratib o'qiy
olmaydi, ya'ni «aniq rad etish» maqsadi bajarilmaydi). Chegaralar agent tomonidagi shakl
darvozasi bilan **aynan bir xil** qilib tanlangan.

### Vaqt

Protokoldagi hamma vaqt **ISO-8601, UTC, `+00:00` siljishi bilan**.

⚠️ **CHEGARA — soat siyrilishi (clock skew).** Agent `written_at` ni `requested_at` bilan
solishtiradi (`OUTPUT_PREDATES_REQUEST`). E'lon qilingan oqimda agent va 1C **bir** mashinada
ishlaydi, demak soat bitta. Yig'uvchi **boshqa** mashinada ishlatilsa (masalan `.epf`
tarmoq papkasiga qo'yilsa), bu tekshiruv **yolg'on** ishlashi mumkin. Shunda sabab
soatdan izlanadi, protokoldan emas.

---

## 4b. ⚠️ OCHIQ KELISHMOVCHILIK — `status` LUG'ATI (PILOTDAN OLDIN HAL QILINADI)

⚠️ **BU — PHASE 4 NAQSHI VA U REAL PAKET CHIQISHIDAN OLDIN TOPILDI.** Ko'prik tomoni va
agent tomoni `status` lug'atini **mustaqil** to'ldirdi, chunki arxitektor qarorlari maydon
NOMLARINI bergan, lekin `status` ning QIYMATLARINI bermagan. Natija:

| tomon | lug'at | manbasi |
|---|---|---|
| Yig'uvchi ko'prigi (shu hujjat) | `SUCCESS` · `PARTIAL` · `FAILED` · `BRIDGE_REJECTED` | `collector/BinOSDiscoveryCollector.bsl` |
| Agent darvozasi | `OK` · `FAILED` · `CANCELLED` | `app/services/discovery_agent/bridge_protocol.py` (`RESPONSE_STATUSES`) |

Kesishma — **faqat `FAILED`**. Demak bugun **har bir haqiqiy javob** agent tomonida
`BRIDGE_SHAPE_INVALID` bilan rad etilardi: to'plam ikki tomonda ham yashil, lekin tizim
ishlamaydi — Phase 4 da aynan shunday bo'lgan.

⚠️ **Bu FAIL-CLOSED, ya'ni yolg'on muvaffaqiyat BERMAYDI.** Agent noma'lum qiymatni rad
etadi, qabul qilmaydi. Shu bois bu **bloker**, lekin **xavfsiz** bloker.

### Tavsiya (ko'prik tomonining asoslari)

**Agent tomoni `RESPONSE_STATUSES` ni `("SUCCESS", "PARTIAL", "FAILED", "BRIDGE_REJECTED")`
qilsin**, ko'prik esa o'zgarmasin. Sabablar:

1. `SUCCESS`/`PARTIAL`/`FAILED` — **muzlatilgan yig'uvchining o'z** `run_status.json`.`overall`
   qiymatlari. Ko'prik ularni **diskdan o'qib qayta aytadi**. Ularni `OK`/`FAILED` ga
   aylantirish — ikkinchi, sinalmagan **tarjima qatlami** bo'lardi.
2. `PARTIAL` ni `OK` ga qo'shish **yarim natijani muvaffaqiyat** deb o'qishga olib keladi —
   agent tomonining o'z izohi aynan shundan ogohlantiradi. `FAILED` ga qo'shish esa
   ishlatishga yaroqli paketni tashlab yuborardi. ⚠️ Agentning `bundle/manifest.json` ni
   tekshirishi bu farqni **ko'rmaydi**: `overall = PARTIAL` majburiy fayllar **to'liq**
   bo'lgan holda ham, bitta BO'LIM yiqilgani uchun chiqadi.
3. `CANCELLED` qiymati yig'uvchi yozgan javobda **erishib bo'lmaydigan**: bekor qilish
   kooperativ va operator tomonida bo'ladi, ya'ni bekor qilinganda `response.json`
   **umuman yozilmaydi**. Uni yig'uvchi lug'atida saqlash «hech qachon kelmaydigan qiymat»
   bo'lib qolardi; bekor qilishni agent O'ZI (`OPERATOR_CANCELLED` kodi bilan) qayd etadi.
4. `OK` — ikki tomonning **birortasining** lug'atida yo'q: u shu yerda o'ylab chiqarilgan.

⚠️ Teskari qaror ham mumkin, lekin u ko'prikda tarjima qatlamini talab qiladi va
`PARTIAL` ni yo'qotadi — shu bois bu yerda **tavsiya etilmaydi**. Qaysi variant tanlansa
ham, qaror **bitta joyda** yozilishi va ikki tomon **shu joyga** qarashi kerak.

### Kelishilganlar (farq YO'Q)

Quyidagilar ikki tomonda **aynan bir xil** va tekshirilgan: uch shartnoma versiyasi
(`binos-bridge-*-v1`) · uch fayl nomi · `request.json` ning 10 kaliti · `response.json`
ning 9 kaliti · `bridge_done.json` ning 4 kaliti (`done_version` bilan) ·
`collector{name,version}` · `nonce` 32–128 kichik hex · `target_fingerprint` 64 kichik hex ·
`notes` matnlar massivi · JSON soni/booleani taqiqlangani (hamma qiymat MATN) ·
tugallanish belgisining ENG OXIRIDA yozilishi.

---

## 5. Real-pilot nazorat ro'yxati

⚠️ Tartib **majburiy**: har qadam oldingisining natijasiga suyanadi. Birorta qadam
yiqilsa — **keyingisiga o'tilmaydi**.

### 5.0 Oldin

- [ ] Nusxa **ajratilgan** mashinada tiklangan; jonli baza **ochilmagan**.
- [ ] Nusxa tiklangan **vaqt** yozib olingan (paket buni o'zi bila olmaydi).
- [ ] 1C platformasi **aniq reliz raqami** yozib olingan.
- [ ] `.epf` xeshi o'lchandi va 3-bo'limdagi yozuv bilan **mos**.

### 5.1 Kompilyatsiya

- [ ] Designer'da **modul sintaksisi tekshirildi** — xatolar ro'yxati yozib olindi.
- [ ] Xato bo'lsa: tuzatish **repo manbasida** bajariladi, Designer ichida emas; keyin
      `.epf` qayta yig'iladi va xesh yangilanadi.

### 5.2 Quruq yurish (so'rovsiz)

- [ ] `.epf` **bo'sh** papkadan ochildi (`request.json` yo'q).
- [ ] Kutilgan natija: ko'prik **to'xtadi**, `response.json` va `bridge_done.json`
      **yozilmadi**, operator «so'rov fayli topilmadi» xabarini ko'rdi.
- [ ] ⚠️ Agar fayllar **yozilgan** bo'lsa — bu **nuqson**: ko'prik so'rovsiz ishlagan.

### 5.3 Buzilgan so'rov (rad etish yo'li)

Har biri **alohida** yurish papkasida sinaladi:

- [ ] `request_version` boshqa qiymat → `REQUEST_VERSION_MISMATCH`, `status=BRIDGE_REJECTED`.
- [ ] `nonce` 32 belgidan qisqa, 128 dan uzun yoki kichik hex emas → `NONCE_MALFORMED`,
      va ⚠️ **birorta fayl yozilmagani** tekshiriladi (kimlik shakli buzuq).
- [ ] `target_fingerprint` 64 ta kichik hex belgi emas → `FINGERPRINT_MALFORMED`,
      **fayl yozilmaydi**.
- [ ] `expected_collector.version` boshqa qiymat → `WRONG_COLLECTOR_VERSION`.
- [ ] `output_dir` yurish papkasidan **tashqarida** → `OUTPUT_DIR_OUTSIDE_RUN`, va
      **o'sha papkaga hech narsa yozilmagani** tekshiriladi.
- [ ] `bundle\` yaratilmagan → `OUTPUT_DIR_MISSING`.
- [ ] Har holatda: `response.json` **bor**, `bridge_done.json` **bor**, `bundle\` **bo'sh**.
      ⚠️ Rad etishda ham javob yoziladi, aks holda «rad etdi» va «1C umuman ochilmadi»
      bir xil ko'rinardi.

### 5.4 `METADATA_ONLY` yurishi (asosiy yo'l)

- [ ] To'g'ri `request.json`, `mode = METADATA_ONLY`, `allowed_probes` **bo'sh**.
- [ ] `bundle\` ichida: `export.json` · `metadata.json` · `run_status.json` ·
      `errors.json` · `run_summary.md` · `manifest.json`.
- [ ] `bundle\manifest.json` **oxirgi** va ichida qolgan hamma fayl bor.
- [ ] `response.json`.`status` = `bundle\run_status.json`.`overall`.
- [ ] `response.json` dagi `run_id`/`nonce`/`target_fingerprint` so'rovdagi qiymat bilan
      **aynan** bir xil.
- [ ] `bridge_done.json`.`written_at` ≥ `request.json`.`requested_at`.
- [ ] `bundle\probes\` **bo'sh yoki yo'q** — zond bajarilmagani tasdiqlanadi.
- [ ] `run_status.json`.`mode_note` da rejim **qanday** tanlangani yozilgan.

### 5.5 Ikkinchi yurish himoyasi

- [ ] **Shu** papkada `.epf` qayta ochiladi.
- [ ] Kutilgan natija: `RUN_DIR_NOT_EMPTY`, **hech narsa yozilmaydi**, birinchi yurishning
      `response.json` va `bridge_done.json` i **o'zgarmagan** (xeshi bilan tekshiriladi).

### 5.6 Kardinallik zondi (oshkor qilingan so'rov)

⚠️ Bu qadam **bazaga so'rov yuboradi** — 6-bo'limni o'qing.

- [ ] Nusxa **band bo'lmagan** vaqtda sinaladi (jonli bazaga ta'sir qilmasligi uchun emas —
      u ajratilgan — balki vaqtni o'lchash uchun).
- [ ] Eng katta jadvalda sanoq **qancha vaqt** olgani yozib olinadi.
- [ ] ⚠️ Agar sanoq qabul qilinmas darajada uzoq cho'zilsa, bu **qobiliyat chegarasi** bo'lib
      qayd etiladi: yig'uvchi so'rovni bo'lmaydi va «tezlashtirish» uchun o'zgartirilmaydi.

### 5.7 Keyin

- [ ] Hamma artefakt BinOS tomoniga o'tkazildi va `export_adapter` ni o'tdi.
- [ ] Yiqilgan har qadam **yozilgan** holda qaytarildi; «ishladi» xulosasi faqat
      5.1–5.5 to'liq o'tgach yoziladi.

---

## 6. `READ_ONLY_CARDINALITY_PROBE` — oshkor qilish

⚠️ **BU BO'LIM YUMSHATILMAYDI.** Yig'uvchi **ikki** (2) ta `ВЫБРАТЬ КОЛИЧЕСТВО(*)` so'rovini
bazaga **yuboradi**. Bu metadata o'qish **emas**: so'rov biznes jadvalining ustidan o'tadi.

| # | qayerda | jadval nomi qayerdan keladi |
|---|---|---|
| 1 | `counts` bo'limi (`ДобавитьСчетчики`) | PLATFORMA prefiksi + kezilgan metadata obyektining `.Имя` si |
| 2 | `row_count` zondi (`ЗондКоличествоСтрок`) | metadata obyektining `ПолноеИмя()` i |

Nima kafolatlanadi (va qanday):

- ⚠️ **Birorta biznes ustuni tanlanmaydi.** `ВЫБРАТЬ` dan keyin faqat `КОЛИЧЕСТВО(*)` turadi,
  demak natija **bitta son**; narx, mijoz, barkod yoki hujjat qatori **chiqmaydi**.
- ⚠️ **Jadval nomi metadatadan keladi**, tashqi matndan emas. Model yoki operator bergan
  nishon matni (`ЦелевойОбъект`) so'rovga **tushmaydi** — u metadata obyektini
  **izlash** uchungina ishlatiladi.
- ⚠️ **So'rov matni tashqi argumentdan qurilmaydi.** Statik audit ikki qoida bilan
  majburlaydi: `QUERY_TEXT_FROM_VARIABLE` (so'rov matni bo'sh bo'lmagan **literal** bilan
  boshlanishi shart) va `QUERY_TEXT_CONCAT_SOURCE` (qo'shiladigan nom **oq ro'yxatda**
  bo'lishi shart).
- ⚠️ **So'rov soni qulflangan**: yig'uvchida **aynan ikki** `Новый Запрос` bor va test buni
  tekshiradi. Uchinchi so'rov odam ko'rigidan o'tmasdan kirib kelmaydi.

Nima kafolatlanmaydi:

- ❌ **Sanoq tez bajarilishi.** Katta jadvalda `КОЛИЧЕСТВО(*)` uzoq cho'zilishi mumkin; bu
  bazaga **yuk**. 5.6 qadami shuni o'lchaydi.
- ❌ **Sanoq qiymatining to'g'riligi** — u faqat haqiqiy bazada ko'rinadi.

---

## 7. Nosozlik kodlari

Har kod uchun **uchta** narsa: `code` · **operator matni** (ichki atama yo'q) ·
`next_action` (nima qilish). ⚠️ Kodlar `[A-Z][A-Z0-9_]*` shaklida.

### 7.1 Ko'prik va paket (yangi kodlar)

| `code` | operator matni | `next_action` |
|---|---|---|
| `COLLECTOR_EXECUTION_NOT_ALLOWED` | «1C ni avtomatik ishga tushirish bu yerda ruxsat etilmagan.» | Qayta ishlashni **o'zingiz** oching va tugmani bosing (`collector/BUILD.md`, A yo'li). |
| `STALE_OUTPUT` | «Papkadagi natija bu so'rovga tegishli emas.» | **Yangi** yurish boshlang; eski papka tegilmay qoladi. |
| `NONCE_MISMATCH` | «Natija boshqa so'rovdan.» | **Yangi** yurish boshlang. Eski papkani o'chirmang — u dalil. |
| `WRONG_COLLECTOR_VERSION` | «Qayta ishlash fayli boshqa versiyadan.» | `BinOSDiscoveryCollector.epf` ni BinOS bergan nusxa bilan almashtiring. |
| `PARTIAL_PACKAGE` | «Natija to'liq emas.» | `bundle` papkasidagi `run_summary.md` ni o'qing va yurishni qaytaring. |
| `OUTPUT_PREDATES_REQUEST` | «Natija so'rovdan oldin yozilgan.» | Papkani **bo'sh** qilib yangi yurish boshlang; mashinalar soatini tekshiring. |
| `OPERATOR_CANCELLED` | «Siz bekor qildingiz.» | Tayyor bo'lganda qaytadan boshlang. Yarim natija **saqlanmaydi**. |
| `RUN_DIR_NOT_EMPTY` | «Bu papkada tugagan yurish bor.» | BinOS dan **yangi** yurish boshlang. |
| `TARGET_AMBIGUOUS` | «Bir nechta baza topildi, qaysi biri kerakligi aniq emas.» | Ro'yxatdan **bittasini** tanlang. |

⚠️ `COLLECTOR_EXECUTION_NOT_ALLOWED` — **bugungi holat**, nuqson emas: COM yo'q, o'ylab
chiqarilgan buyruq satri parametri yo'q, o'rnatuvchi/xizmat/avtoyuklanish/yangilovchi yo'q.
Avtomatik ishga tushirish **deklaratsiya** sifatida qoldirilgan va `UNVERIFIED_ON_REAL_1C`
deb belgilangan.

⚠️ `OPERATOR_CANCELLED` — bekor qilish **kooperativ**. Jarayonni keng o'ldirish
(`taskkill /F`, process tree kill) **yo'q**: u 1C ni yarim yozilgan fayl va ochiq qulf bilan
qoldirishi mumkin.

### 7.2 Ko'prikning o'z rad etish sabablari (`notes` ga kod bo'lib tushadi)

| `code` | operator matni | `next_action` |
|---|---|---|
| `SELF_PATH_UNAVAILABLE` / `SELF_PATH_EMPTY` / `SELF_PATH_UNREADABLE` | «Qayta ishlash o'z papkasini aniqlay olmadi.» | `.epf` ni **BinOS yaratgan papkadan** oching (tarmoq papkasidan emas). |
| `REQUEST_NOT_FOUND` | «So'rov fayli topilmadi.» | Qayta ishlashni BinOS yaratgan papkadan oching. |
| `REQUEST_UNREADABLE` / `REQUEST_NOT_AN_OBJECT` | «So'rov fayli o'qilmadi.» | BinOS dan yangi yurish boshlang; faylni qo'lda tahrirlamang. |
| `REQUEST_VERSION_MISMATCH` | «BinOS va qayta ishlash versiyalari mos emas.» | Ikkisini bir xil relizdan oling. |
| `REQUEST_FIELD_MISSING` | «So'rov to'liq emas.» | BinOS dan yangi yurish boshlang. |
| `RUN_ID_MALFORMED` | «So'rov o'zligi buzilgan.» | BinOS dan yangi yurish boshlang; so'rovni qo'lda tahrirlamang. |
| `NONCE_MALFORMED` | «So'rov belgisi buzilgan.» | BinOS dan yangi yurish boshlang. |
| `FINGERPRINT_MALFORMED` | «Nishon belgisi buzilgan.» | BinOS dan yangi yurish boshlang. |
| `OUTPUT_DIR_MISSING` | «Natija papkasi yo'q.» | Yurishni BinOS dan qaytadan boshlang — papkani BinOS yaratadi. |
| `OUTPUT_DIR_OUTSIDE_RUN` | «So'rov natijani begona papkaga yo'llaydi.» | So'rovni qo'lda tahrirlamang; yangi yurish boshlang. |
| `RUN_STATUS_MISSING` / `RUN_STATUS_UNREADABLE` / `RUN_STATUS_NOT_AN_OBJECT` / `RUN_STATUS_UNKNOWN_OVERALL` | «Yurish holati o'qilmadi.» | `bundle` papkasidagi `errors.json` ni BinOS ga yuboring. |
| `COLLECTOR_RAISED` | «Yig'ish yarmida to'xtadi.» | `bundle` papkasini butunligicha BinOS ga yuboring. |
| `BRIDGE_WRITE_FAILED` | «Natija fayli yozilmadi.» | Papkaga yozish huquqini tekshirib, qaytadan urinib ko'ring. |

⚠️ Holat o'qilmasa `FAILED` qaytadi (**fail-closed**): «o'qiy olmadim» hech qachon
«muvaffaqiyat» degani emas.

---

## 8. Nimaga tegilmaydi

⚠️ **1C xavfsizligi zaiflashtirilmaydi.** Xavfsiz rejimni chetlab o'tish, xavfsizlik
profilini o'zgartirish, rol tahrirlash — **taqiqlangan va qilinmagan**. Agar yig'uvchi
ishlash uchun shunday o'zgarish talab qilsa, **javob «yo'q»**: bu holat qobiliyat chegarasi
bo'lib qayd etiladi.

Ko'prik va yig'uvchi **faqat o'qiydi**. Bazaga yozish, hujjat o'tkazish, o'chirish belgisi,
tranzaksiya, monopol rejim, imtiyozli rejim, dinamik kod bajarish, tashqi jarayon, uskuna
(tarozi/printer) buyrug'i, almashinuvni ro'yxatga olish, fayl nusxalash/ko'chirish/o'chirish,
katalog yaratish — **yo'q**. Taqiq `app/services/discovery_1c/epf_audit.py` ning **38
qoidasi** bilan majburlanadi; yig'uvchi ham, ko'prik fragmenti ham undan **0 topilma** bilan
o'tadi.

Bundan tashqari **yo'q**: COM avtomatizatsiya · o'ylab chiqarilgan buyruq satri kaliti ·
o'rnatuvchi · Windows xizmati · avtoyuklanish · yangilovchi · Migrator **APPLY** yo'li ·
jarayonni keng o'ldirish.

---

## 9. Nima isbotlangan va nima yo'q

| narsa | holat | qayerda |
|---|---|---|
| Ko'prik manbasida taqiqlangan chaqiruv yo'qligi | ✅ **avtomatik, CI** | `test_agent_collector_source.py` |
| Begona alifbo harfi / yopilmagan literal / blok muvozanati | ✅ **avtomatik (faqat MANBA MATNI)** | o'sha test |
| Fragment nomlari yig'uvchi nomlari bilan to'qnashmasligi | ✅ **avtomatik (faqat MANBA MATNI)** | o'sha test |
| Kirish nuqtasining **argumentsiz** ekani | ✅ **avtomatik (faqat MANBA MATNI)** | o'sha test |
| Protokol kalitlari ikki tomonda bir xil yozilgani | ✅ **avtomatik (faqat MANBA MATNI)** | o'sha test |
| `VERSION.json` manba bilan mosligi | ✅ **avtomatik** | o'sha test |
| Ikki kardinallik so'rovining shakli va soni | ✅ **avtomatik** | o'sha test |
| Muzlatilgan yig'uvchi tegilmagani | ✅ **avtomatik (xesh pini)** | o'sha test |
| **1C sintaksisi** | ❌ **YO'Q** | 1C mutaxassisi, Designer |
| **Kompilyatsiya** | ❌ **YO'Q** | 5.1 qadami |
| **`.epf` yig'ilishi** | ❌ **YO'Q — `.epf` repoda yo'q** | 2-bo'lim |
| **`ИспользуемоеИмяФайла` ning har senariyda to'lishi** | ❌ **`UNVERIFIED_ON_REAL_1C`** | 5.2 qadami |
| **`/Execute` bilan avtomatik chaqirilish qoidasi** | ❌ **`UNVERIFIED_ON_REAL_1C`** | `collector/BUILD.md`, B yo'li |
| **Haqiqiy bazada ishlashi** | ❌ **YO'Q** | 5.4 qadami |
| **Sanoq so'rovining tezligi** | ❌ **YO'Q** | 5.6 qadami |
| **Avtomatik ishga tushirish** | ❌ **DEKLARATSIYA, `UNVERIFIED_ON_REAL_1C`** | 7.1, `COLLECTOR_EXECUTION_NOT_ALLOWED` |

⚠️ Yuqoridagi «✅» lar **faqat manba matni** haqida. Ular modul kompilyatsiya bo'lishini,
1C'da yurishini yoki to'g'ri javob berishini **isbotlamaydi**.
