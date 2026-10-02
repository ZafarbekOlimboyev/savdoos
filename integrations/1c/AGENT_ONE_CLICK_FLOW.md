# BinOS Discovery — BIR BOSISHLI OQIM (operator uchun)

Bu hujjat **operator** uchun: besh qadam, har qadamda ekranda nima turadi va nima qilish
kerak. Ichki atamalar bu qismda **yo'q** — ular oxirdagi «Batafsil diagnostika»
bo'limida (u faqat nosozlikni ishlab chiquvchiga uzatganda kerak).

> **Agent 1C da HECH NARSANI o'zgartirmaydi.** U faqat **o'qiydi**: na yozadi, na
> o'chiradi, na sozlamaga tegadi. Xavfsizlik rejimi, xavfsizlik profili va rollar
> **o'zgartirilmaydi**.
>
> **Kirish ma'lumotini (login/parol) agent so'ramaydi va ko'rmaydi.** Agar baza parol
> talab qilsa, uni **1C ning o'z oynasi** so'raydi.

---

## ⚠️ Yig'uvchi bazadan nimani oladi (buni bilib turing)

Yig'uvchi **ikki** xil ish qiladi va ikkinchisi haqida ochiq aytiladi:

1. **Tuzilmani o'qiydi** — bazada qanday ma'lumotnoma, hujjat va registr borligini,
   ularning nomi va maydonlarini. Bu **tuzilma**, mazmun emas.
2. **Jadvallardagi qatorlarni SANAYDI** — ya'ni bazaga **so'rov yuboradi** va har jadval
   uchun **nechta qator borligini** oladi.

**Nima farqi bor:** sanoq **faqat sonni** qaytaradi — «bu jadvalda 7137 qator». Narx,
mijoz nomi, barkod, hujjat qatori va boshqa **birorta ustun o'qilmaydi**.

> **Shu sababli yig'uvchini «faqat tuzilmani o'qiydi» deb atash to'g'ri bo'lmaydi.** U
> biznes jadvallari ustidan sanoq so'rovini bajaradi. Bazaga **yozmaydi**,
> **o'chirmaydi** va **o'zgartirmaydi** — lekin so'rov yuboradi.

**Nega bu sizga muhim:**

- **Katta bazada sanoq vaqt oladi.** Eng katta jadvallarda bu bir necha daqiqaga
  cho'zilishi mumkin — shu bois 4-qadamdagi kutish uzoq ko'rinadi.
- **Bazani band vaqtda tekshirmang.** Ish kuni o'rtasida emas, bo'sh vaqtda yoki
  bazaning **nusxasida** ishga tushirish tavsiya qilinadi.
- **Sanoq soni qulflangan:** yig'uvchida **aynan ikki** sanoq so'rovi bor va bu test
  bilan tekshirilgan. Uchinchi so'rov odam ko'rigidan o'tmasdan qo'shilmaydi.

Buning to'liq texnik tavsifi oxirdagi «Batafsil diagnostika» bo'limida.

---

## ⚠️ AVVAL O'QING: hozir nimaga tayyor, nimaga tayyor emas

**Yig'uvchi (1C ichida ishlaydigan qism) hozir MANBA ko'rinishida tayyor** — holati:
`EPF_SOURCE_READY`. Ya'ni 1C ga yuklanadigan **ikkilik fayl hali yig'ilmagan**, va uni 1C
konfiguratorida **siz** yig'asiz.

Shu sababli: **«bitta bosishda hammasi o'zi bo'ladi» deb aytilmaydi.** Hozirgi haqiqiy
yo'l:

| Kim | Nima qiladi |
|-----|-------------|
| **Siz** | 1C ni ochasiz va yig'uvchini **bir marta** o'z sessiyangizda bajarasiz |
| **Agent** | 1C ni aniqlaydi, bazani so'raydi, chiqish joyini tayyorlaydi, natijani **kutadi**, keyin tekshiradi va tahlil qiladi |

Agentning 1C ni **o'zi** ochishi — hali **tekshirilmagan yo'l** va u **o'z-o'zidan
ishlatilmaydi**.

**Fayllarni qo'lda ko'chirish KERAK EMAS.** Yig'uvchi natijani qayerga yozishi kerakligi
**avtomatik** belgilanadi: agent har yurish uchun **bo'sh papka** tayyorlaydi va o'sha
papkaning yo'lini yig'uvchiga **so'rov hujjatida** beradi. Siz yig'uvchini bajarasiz —
natija **o'sha joyga** tushadi, agent uni **o'zi** oladi. Papkadan papkaga nusxa
ko'chirish, fayl nomini o'zgartirish yoki natijani agentga «ko'rsatish» kerak emas.

---

## Qadam 1 — «1C topildi»

Agentni ishga tushirasiz:

```
BinOSDiscoveryAgent.exe --one-click
```

Ekranda:

```
faza: DETECTING_1C — Kompyuterda 1C:Enterprise bor-yo'qligi tekshirilyapti.
                     Hech narsa o'zgartirilmaydi.
```

So'ng natija ko'rinadi: nechta 1C o'rnatmasi topilgani va eng yangisining versiyasi.

**Agar 1C topilmasa** oqim shu yerda **to'xtaydi** va ekranda ikki javobdan **biri**
chiqadi (ular bir xil emas):

- **«O'rnatilmagan»** — hamma manba o'qildi va bo'sh chiqdi. Bu **javob**: bu
  kompyuterda 1C yo'q. Keyingi qadam: agentni 1C o'rnatilgan kompyuterda ishga
  tushiring.
- **«Aniqlab bo'lmadi»** — manbalardan kamida bittasi **o'qilmadi** (huquq yetmadi).
  Bu javob **emas**: 1C bo'lishi ham mumkin. Keyingi qadam: agentni o'z hisobingiz
  huquqlari bilan qayta ishga tushiring.

⚠️ Agent bu ikkisini **hech qachon** aralashtirmaydi: «o'qiy olmadim» degani «yo'q»
degani emas.

---

## Qadam 2 — «Bazani tanlang»

```
faza: DISCOVERING_INFOBASES — 1C ro'yxatidagi ma'lumot bazalari o'qilyapti.
                             Bazalarning o'ziga TEGILMAYDI — faqat ro'yxat o'qiladi.
faza: SELECT_TARGET — Qaysi ma'lumot bazasi tekshirilishini TANLANG. Agent o'zi
                      tanlamaydi: bir nechta baza mos kelsa ham qarorni siz berasiz.
```

- **Bitta baza bo'lsa** — oqim o'zi davom etadi (tanlanadigan narsa yo'q).
- **Bir nechta baza bo'lsa** — agent **to'xtaydi** va ro'yxatni raqamlari bilan
  ko'rsatadi:

  ```
    1. Savdo bazasi · file · parol kerakmi: unknown
    2. Buxgalteriya · file · parol kerakmi: true
  ```

  Kerakli raqamni ko'rsatib qayta ishga tushirasiz:

  ```
  BinOSDiscoveryAgent.exe --one-click --target 2
  ```

⚠️ **Nega agent o'zi tanlamaydi:** noto'g'ri baza tanlansa, hisobot **o'zini to'liq deb
ko'rsatadi**, lekin butun mazmuni boshqa bazadan bo'ladi. Bunday xato jimgina o'tib
ketadi, shu bois qaror **sizda**.

⚠️ Ekranda ko'rinadigan narsa — faqat **baza nomi**, turi va parol talab qilishi. Bazaning
yo'li yoki server manzili ekranga **chiqarilmaydi**.

---

## Qadam 3 — «Discovery boshlash»

```
faza: PREPARING_COLLECTOR — Yig'uvchi va uning natijasi uchun bo'sh papka tayyorlanyapti.
                            Yig'uvchining o'zi faqat O'QIYDI: 1C da hech narsa
                            yozilmaydi, o'zgartirilmaydi va o'chirilmaydi.
faza: LAUNCHING_1C — 1C ochilyapti. Kirish ma'lumoti so'ralsa, uni 1C NING O'Z oynasi
                     so'raydi — agent uni ko'rmaydi va hech qayerga yozmaydi.
  Yig'uvchini O'Z 1C sessiyangizda bir marta ochib bajaring. Agent natija papkasini
  kuzatadi va o'zi davom etadi.
```

Shu qadamda:

1. Agent **bo'sh** papka tayyorlaydi va unga so'rov hujjatini yozadi. Papka
   `LOCALAPPDATA` ichida (`BinOS\Discovery\runs\<yurish>`), ya'ni **administrator huquqi
   kerak emas**. Boshqa joy kerak bo'lsa: `--runs-dir <papka>`.
2. **Siz** 1C ni ochib yig'uvchini bajarasiz. Yig'uvchi natijani **agent tayyorlagan
   papkaga** yozadi.
3. Agent kutadi.

⚠️ **Agent birorta faylni o'chirmaydi.** Ko'rsatilgan papka bo'sh bo'lmasa, agent unga
**yozmaydi** va to'xtaydi — ichidagi fayllarni «tozalab» tashlamaydi. Bunday holatda bo'sh
papka ko'rsating yoki ichidagini o'zingiz chetga suring.

⚠️ **Parol buyruq satriga yozilmaydi.** Agentda parol uchun bayroq **yo'q** va bo'lmaydi:
buyruq satri jarayonlar ro'yxatida ko'rinadi.

---

## Qadam 4 — Progress (nima bo'layotgani)

Har qadamda ekranda **matn** turadi (shunchaki aylanadigan belgi emas):

```
faza: WAITING_FOR_COLLECTOR — Yig'uvchi 1C ichida ishlayapti, natija kutilyapti. Katta
                              bazada bu bir necha daqiqa davom etadi. Bekor qilsangiz
                              agent kutishni to'xtatadi, 1C ni esa o'zingiz yopasiz —
                              agent birorta jarayonni majburan tugatmaydi.
kutilmoqda: yig'uvchi ishini tugatganini hali bildirmadi
            (1C oynasini yig'uvchi tugatguncha yopmang)
faza: COLLECTOR_COMPLETE — Yig'uvchi natijani qoldirdi. Natija HALI tekshirilmagan:
                           to'liqligi keyingi qadamda tekshiriladi.
faza: INGESTING — Natija o'qilyapti va to'liqligi tekshirilyapti. Tekshiruvdan o'tmagan
                  natija bo'yicha xulosa CHIQARILMAYDI.
faza: ANALYZING — Ma'lumotlar bog'lanyapti va taqqoslanyapti. Bu qadam 1C ga umuman
                  murojaat qilmaydi — faqat qo'lga olingan natija ustida ishlanadi.
```

Kutish haqida bilish kerak bo'lgan narsalar:

- **Kutish cheksiz emas.** Chegara bor va uni o'zgartirish mumkin:
  `--wait-seconds 1800`. Vaqt tugasa yurish **to'xtaydi** va sababini aytadi.
- **Bekor qilish — 1C ni yopish emas.** Agent hech qanday jarayonni majburan
  tugatmaydi: kutishni to'xtatadi, 1C oynasini esa **siz** yopasiz.
- Yig'uvchi tugatmasidan 1C oynasini yopsangiz, natija **yarim** qolishi mumkin — agent
  bunday natijani **qabul qilmaydi** (quyida).

---

## Qadam 5 — Muvaffaqiyat yoki nosozlik

### Muvaffaqiyat

```
faza: COMPLETE — Razvedka tugadi: natija papkasi va hisobot tayyor. 1C da hech narsa
                 o'zgartirilmadi.
natija papkasi: ...\binos-discovery-20261002T101500Z
xulosa: COMPLETE
```

Natija papkasida hisobot va artefaktlar bo'ladi. **Shu papkani butunligicha** saqlang —
savol tug'ilganda aynan u kerak bo'ladi.

### Nosozlik

Nosozlikda ekranda **har doim uchta** narsa bo'ladi:

1. **belgi** (masalan `DONE_MARKER_MISSING`) — ishlab chiquvchi uchun;
2. **nima bo'lgani** — oddiy til bilan;
3. **keyingi qadam** — nima qilish kerakligi.

Eng ko'p uchraydiganlari:

| Nima bo'ldi | Nima qilish kerak |
|-------------|-------------------|
| Yig'uvchi **javob qoldirmadi** (umuman boshlanmagan) | Yig'uvchini qaytadan bajaring va unga agent ko'rsatgan papkani bering |
| Yig'uvchi **ishini tugatganini bildirmadi** (natija yarim bo'lishi mumkin) | Yig'uvchi oxirigacha ishlab bo'lgunicha kuting; 1C oynasini undan oldin yopmang |
| Natija **to'liq emas** (fayllarning bir qismi yo'q) | Bo'sh papka bilan qaytadan urinib ko'ring; yarim natijani **o'chirmang** |
| Natija **boshqa yurishga** tegishli (eski) | Yangi yurish boshlang — har yurish o'z papkasini oladi |
| Natija **boshqa bazadan** yig'ilgan | 1C da so'rovdagi bazani tanlab, yig'uvchini qaytadan bajaring |
| Yig'uvchining **versiyasi** boshqa | Yig'uvchining yangi faylini 1C ga yuklab, yurishni qaytadan boshlang |
| Papka **bo'sh emas** | Bo'sh papka ko'rsating yoki ichidagini o'zingiz chetga suring |
| **Siz bekor qildingiz** | Bu nuqson emas. 1C oynasini o'zingiz yoping; xohlasangiz yangi yurish boshlang |

⚠️ **Yarim natija bo'yicha xulosa chiqarilmaydi.** Agent «bir nimadir chiqdi» deb davom
etmaydi: natija tekshiruvdan o'tmasa, hisobot ham chiqmaydi. Bu ataylab shunday — noto'g'ri
hisobot hisobotsizlikdan yomonroq.

### Chiqish kodlari (skript yozsangiz)

| Kod | Ma'nosi |
|-----|---------|
| `0` | Yurish tugadi, natija tekshiruvdan o'tdi |
| `1` | Yurish **to'xtadi** va sababi aytildi (bu ham javob) |
| `2` | Yurish **boshlanmadi**: buyruq xatosi, yoki qaror sizda (masalan baza tanlanmagan) |

---

<details>
<summary><b>Batafsil diagnostika</b> (faqat nosozlikni ishlab chiquvchiga uzatganda)</summary>

Bu bo'lim **ichki atamalardan** iborat. Oddiy ishda u kerak emas.

**Yurish papkasi** (`%LOCALAPPDATA%\BinOS\Discovery\runs\<run_id>\`) tarkibi:

| Fayl | Kim yozadi | Nima |
|------|------------|------|
| `request.json` | agent | `binos-bridge-request-v1`: `run_id`, `nonce`, `requested_at`, `output_dir`, `expected_collector`, `target_fingerprint`, `mode`, `allowed_probes`, `notes` |
| `bundle/` | yig'uvchi | Phase 4 runtime paketi; uning `manifest.json` i **paket ichida oxirgi** yoziladi |
| `response.json` | yig'uvchi | `binos-bridge-response-v1`: `status` = `SUCCESS` / `PARTIAL` / `FAILED` / `CANCELLED` |
| `bridge_done.json` | yig'uvchi | `binos-bridge-done-v1`: **eng oxirgi** yoziladigan tugallanish belgisi |

**`status` lug'ati** (yopiq, noma'lum qiymat rad etiladi). `SUCCESS`, `PARTIAL` va
`FAILED` — Phase 4 yadrosining `run_status.json`.`overall` qiymatlarining **aynan o'zi**
(`runtime_bundle.OVERALL_*` dan import qilinadi, ikkinchi nusxa yozilmaydi). `CANCELLED` —
ko'prikka xos, ustiga qo'shiladigan yagona qiymat.

- `PARTIAL` **jimgina muvaffaqiyat emas**: faza `COLLECTOR_COMPLETE` ga o'tadi (javob bor,
  paket to'liq), lekin hukmni Phase 4 validatori beradi va u kodi `2` ni hurmat qilib
  **to'xtaydi**. Yarim natija «tugadi» deb **atalmaydi**.

> ⚠️ **OCHIQ NOMUVOFIQLIK (tuzatilmagan).** Ko'prik manbasi so'rovni rad etganda
> `response.json` ga `status = "BRIDGE_REJECTED"` yozadi, agentning lug'atida esa bu qiymat
> **yo'q** — natijada ko'prikning **aniq rad etishi** operatorga `BRIDGE_SHAPE_INVALID`
> («javob fayli o'qilmadi») bo'lib ko'rinadi, ya'ni **boshqa sabab** va **boshqa keyingi
> qadam**. Bu `tests/test_agent_bridge_conformance.py` da qulflangan va **arxitektor
> qarorini kutadi**: yoki lug'at bu qiymatni qabul qiladi (va uning ma'nosi belgilanadi),
> yoki manba uni yozmaydi.

**Yurishga bog'lanish (run-bound).** Har javob **aynan bitta** so'rovga tegishli:
`run_id` + `nonce` (`secrets.token_hex`, kamida 32 hex belgi) solishtiriladi. Shu sababli
papkada qolgan eski natijani «shu yurishning javobi» deb o'tkazib bo'lmaydi.

**Rad etish kodlari** (har sabab alohida):
`RESPONSE_MISSING` · `DONE_MARKER_MISSING` · `STALE_OUTPUT` · `NONCE_MISMATCH` ·
`WRONG_COLLECTOR_VERSION` · `TARGET_FINGERPRINT_MISMATCH` · `PARTIAL_PACKAGE` ·
`OUTPUT_PREDATES_REQUEST` · `BRIDGE_SHAPE_INVALID` · `OPERATOR_CANCELLED` ·
`RUN_DIR_NOT_EMPTY` · `RUNS_ROOT_UNKNOWN` · `TARGET_AMBIGUOUS` ·
`COLLECTOR_EXECUTION_NOT_ALLOWED`.

**Faza → holat.** Operator ko'radigan 12 faza mavjud holat mashinasining (12 normal + 11
yiqilish) holatlariga **1:1** bog'langan (`bridge_phase.PHASE_TO_STATE`); ikkinchi holat
mashinasi **qurilmagan**:

```
DETECTING_1C          -> ENVIRONMENT_SCAN
NO_1C                 -> FAILED_NO_1C
DISCOVERING_INFOBASES -> TARGET_SELECTION
SELECT_TARGET         -> TARGET_SELECTION
PREPARING_COLLECTOR   -> SAFETY_CHECK
LAUNCHING_1C          -> METADATA_DISCOVERY
WAITING_FOR_COLLECTOR -> METADATA_DISCOVERY
COLLECTOR_COMPLETE    -> METADATA_DISCOVERY
COLLECTOR_FAILED      -> FAILED_COLLECTOR_UNAVAILABLE
INGESTING             -> VALIDATION
ANALYZING             -> ANALYSIS
COMPLETE              -> COMPLETE
```

**Kardinallik zondi (`READ_ONLY_CARDINALITY_PROBE`).** Yig'uvchi bazaga **aynan ikki**
`ВЫБРАТЬ КОЛИЧЕСТВО(*)` so'rovini yuboradi: biri `counts` bo'limi uchun, ikkinchisi
`row_count` zondi uchun. `ВЫБРАТЬ` dan keyin **faqat** `КОЛИЧЕСТВО(*)` turadi, demak natija
bitta son va **birorta biznes ustuni tanlanmaydi**. Jadval nomi **metadatadan** keladi,
tashqi matndan emas; so'rov matni argumentdan qurilmaydi (statik audit
`QUERY_TEXT_FROM_VARIABLE` + `QUERY_TEXT_CONCAT_SOURCE` bilan majburlaydi) va so'rov soni
test bilan qulflangan. To'liq oshkorlik: `REAL_1C_HANDOFF.md`, 6-bo'lim.

**Maxfiylik chegaralari:**

- `nonce` **yurish papkasidan chiqmaydi**: na hisobotga, na natija paketiga yozilmaydi —
  u soxta javobni aniqlashning yagona vositasi.
- Bazaning **xom** manzili (`locator`) protokolga **yozilmaydi** — faqat
  `target_fingerprint` (sha256).
- `request.json` / `response.json` / `bridge_done.json` natija paketiga **ko'chirilmaydi**
  (ular `bundle/` dan tashqarida).
- Parol `argv` ga, jurnalga, natija fayliga, doimiy konfiguratsiyaga va buyruq tarixiga
  **hech qachon** tushmaydi. Ishga tushirishda faqat `/F<yo'l>` yoki `/S<server>`;
  `/N`/`/P` **taqiqlangan**.

**Tekshirilmagan yo'l:** agentning 1C ni **o'zi** ishga tushirishi
`UNVERIFIED_ON_REAL_1C` deb belgilangan va darvoza bilan **yopiq**
(`COLLECTOR_EXECUTION_NOT_ALLOWED`). COM avtomatizatsiyasi **yo'q**, o'ylab chiqarilgan
buyruq satri parametri **yo'q**.

**Bekor qilish kooperativ.** Agent tomonidagi bekor qilish **bor va ishlaydi**:
`launcher.CancelToken` qo'yiladi, `launcher.wait_for_collector` kutishni **to'xtatadi** va
natija `OPERATOR_CANCELLED` kodi bilan `ABORTED_BY_OPERATOR` holatiga tushadi
(`one_click.run_one_click(cancel=...)` uni oqimga uzatadi).

- ⚠️ **1C tomoni bunga xabardor emas.** Shartnomada `cancel_requested.json` nomi band
  qilingan, lekin uni **yozadigan kod yo'q** va ko'prik manbasi uni **o'qimaydi** — ya'ni
  «1C ichidagi yig'uvchi ham to'xtaydi» degan da'vo **berilmaydi**. Yig'uvchi o'z ishini
  oxirigacha davom ettiradi; **1C oynasini siz o'zingiz yopasiz**.
- ⚠️ Jarayonni majburan tugatish (`taskkill`, jarayon daraxtini o'ldirish) **hech qachon**
  qo'shilmaydi.

**Hozircha yozilmaydigan narsa:** `agent_status.json` ga ko'prik fazasi va `run_id`
yozilmaydi — yurish yozuvining sxemasida bu maydonlar hali yo'q. Ular ekranda va buyruq
chiqishida ko'rinadi.

</details>
