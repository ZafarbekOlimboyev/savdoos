# BinOS Discovery Collector — ko'prik qatlami va uni yig'ish

> ## HOLAT: `EPF_SOURCE_READY`
>
> Bu papkada **manba matni** bor. `.epf` fayli **yig'ilmagan va repoda YO'Q**. Bu mashinada
> 1C:Enterprise platformasi o'rnatilmagan, demak manba:
> - **kompilyatsiya qilinmagan**,
> - **sintaksis tekshiruvidan o'tmagan**,
> - **hech qanday 1C bazasida ishlatilmagan**.
>
> Tekshirilgan yagona narsa — **manba matni** (`apps/server/tests/test_agent_collector_source.py`).
> Bu yerda «ishlaydi», «tayyor», «bir marta bosib o'rnatiladigan» degan da'vo **YO'Q**.
> Designer'dagi har bir mexanik qadam `UNVERIFIED_ON_REAL_1C`.

## Nima bu, nima emas

| | |
|---|---|
| **Nima** | Agent (BinOS tomonidagi Python jarayoni) bilan mavjud yig'uvchi orasidagi **faylga asoslangan ko'prik**: `request.json` → `ВыполнитьРазведку(...)` → `response.json` → `bridge_done.json`. |
| **Nima emas** | Ikkinchi discovery dvigateli. Metadata o'qish, kardinallik zondlari, hujjat shakllari, xato paketi va manifest — hammasi **o'zgarmagan** `../extractor/BinOSDiscovery.bsl` da. |

⚠️ `../extractor/BinOSDiscovery.bsl` **O'ZGARTIRILMAYDI**. U Phase 4 da muzlatilgan (38 qoidali
statik audit bilan qulflangan) va unga nisbatan diff **BO'SH** bo'lishi SHART. Ko'prik unga
faqat **havola qiladi**.

## Papkadagi fayllar

| fayl | nima |
|---|---|
| `BinOSDiscoveryCollector.bsl` | ObjectModule manbasining **FRAGMENTI** — ko'prik qatlami |
| `VERSION.json` | `{collector: {name, version}}` — protokolda **tekshiriladigan** kimlik |
| `BUILD.md` | shu hujjat |

## ⚠️ ENG MUHIM: bu MUSTAQIL MODUL EMAS, FRAGMENT

Tashqi qayta ishlashda (`ВнешняяОбработка`) **bitta** ObjectModule bor va unda umumiy modul
yo'q. Demak ko'prik va yig'uvchi **bir modulda** yashaydi. Yig'ish tartibi:

1. **Yangi tashqi qayta ishlash** yarating (Designer → Fayl → Yangi → Tashqi qayta ishlash).
2. Qayta ishlash **nomi**: `BinOSDiscoveryCollector`.
3. **ObjectModule** ni ochib, unga **AVVAL** `../extractor/BinOSDiscovery.bsl` ning to'liq
   matnini qo'ying — **o'zgartirmasdan, bir belgi ham qo'shmasdan**.
4. **SO'NG** shu modulning **OXIRIGA** `BinOSDiscoveryCollector.bsl` ning to'liq matnini
   qo'shing.
5. Faylni `BinOSDiscoveryCollector.epf` nomi bilan saqlang.

### Nega AYNAN shu tartib (va nega fragment o'zini modul deb atamaydi)

- ⚠️ **`Перем` birinchi protseduradan OLDIN bo'lishi shart.** 1C modul o'zgaruvchilarini
  modul boshida talab qiladi. Shu bois ko'prik fragmentida **birorta `Перем` YO'Q** — butun
  holat mahalliy o'zgaruvchilarda va parametrlarda yuradi. Agar fragment modul o'zgaruvchisi
  e'lon qilganida, oxiriga qo'shilgani kompilyatsiyani yiqitardi.
- ⚠️ **Nomlar to'qnashuvi kompilyatsiyani yiqitadi.** Bir modulda ikki bir xil nom bo'lmaydi,
  shu bois ko'prikdagi hamma protsedura, funksiya va doimiy `Мост` bilan boshlanadi. Buni
  qo'lda eslab qolish kerak emas: `test_agent_collector_source.py` ikki manbaning nomlari
  **kesishmasligini** tekshiradi va kesishsa to'plam qizil bo'ladi.
- ⚠️ **Teskari tartib ishlamaydi.** Yig'uvchini fragmentdan KEYIN qo'yish `Перем` qoidasini
  buzadi (yig'uvchining o'z modul o'zgaruvchilari bor).

## Qaysi mantiq qaysi joyda

| mantiq | qayerda | o'zgaradimi |
|---|---|---|
| Strukturaviy metadata, inventarizatsiya, zondlar, manifest, xatolar | `BinOSDiscovery.bsl` (modulning **birinchi** qismi) | **YO'Q** |
| `request.json` o'qish, versiya/nonce tekshirish, `response.json`, `bridge_done.json` | `BinOSDiscoveryCollector.bsl` (modulning **oxirgi** qismi) | ha |
| Rejim normallashtirish (`METADATA_ONLY` fail-safe) | **faqat** `BinOSDiscovery.bsl` da | **YO'Q** |
| Faza nomlari va operator matni | agent tomonida (`app/services/discovery_agent/bridge_phase.py`) | — |

⚠️ Rejim qarori ko'prikda **takrorlanmaydi**. `mode` so'rovdan olinadi va
`ВыполнитьРазведку` ga o'zgartirilmasdan uzatiladi; noma'lum rejimni yig'uvchining o'z
darvozasi `METADATA_ONLY` ga tushiradi va sababni `run_status.json`.`mode_note` ga yozadi.
Ikkinchi normallashtirish ikki tomonni zid qilib qo'yardi — bu Phase 4 ning aynan darsi.

## Kirish nuqtasi

```
ВыполнитьМостРазведки()      // ARGUMENTSIZ, Экспорт
```

⚠️ **ARGUMENTSIZ bo'lishi shartnomaning bir qismi.** CP1 da aniqlangan bo'shliq aynan
argumentli kirish nuqtasi edi: agent buyruq satriga qiymat qo'shardi, modulda esa uni
o'qiydigan joy yo'q edi va natija jimgina **bo'sh papka** bo'lardi. Endi so'rov **fayldan**
keladi.

⚠️ Ko'prik `ПараметрЗапуска` ni **O'QIMAYDI**. Mavjud agent buyruq satriga `/C<output_dir>`
qo'shadi — bu bo'lak ko'prik tomonidan **e'tiborga olinmaydi** va o'ylab chiqarilgan buyruq
satri parametri **qo'shilmaydi**.

### So'rovni qanday topadi

Ko'prik `request.json` ni **ishlayotgan `.epf` faylining o'z papkasidan** qidiradi
(`ЭтотОбъект.ИспользуемоеИмяФайла` → `Новый Файл(...)` → `.Путь`).

Demak agent `.epf` ni yurish papkasiga **nusxalaydi**, so'ng shu papkada `request.json`
qoldiradi:

```
%LOCALAPPDATA%\BinOS\Discovery\runs\<run_id>\
    BinOSDiscoveryCollector.epf     <- agent nusxalaydi
    request.json                    <- AGENT yozadi
    bundle\                          <- AGENT yaratadi, BO'SH
        probes\                      <- AGENT yaratadi (faqat zond ruxsat etilganda)
    response.json                   <- KO'PRIK yozadi
    bridge_done.json                <- KO'PRIK yozadi, ENG OXIRIDA
```

⚠️ `ИспользуемоеИмяФайла` ning **har senariyda** to'lishi bu yerda isbotlanmagan
(`UNVERIFIED_ON_REAL_1C`). Bo'sh bo'lsa ko'prik **to'xtaydi** va o'ylab chiqarilgan zaxira
papkaga **o'tmaydi**: taxmin qilingan papkaga yozish begona joyga yozish bo'lardi.

⚠️ **Papkalarni AGENT yaratadi.** Ko'prikda katalog yaratish statik audit bilan taqiqlangan,
shu bois `bundle\` (va zond ruxsat etilsa `bundle\probes\`) **oldin yaratilgan, mavjud va
bo'sh** bo'lishi shart. `bundle\` yo'q bo'lsa ko'prik `OUTPUT_DIR_MISSING` bilan rad etadi;
`probes\` yo'q bo'lsa zond fayllari yozilmaydi va sabab `bundle\errors.json` ga tushadi.
Bu **qobiliyat chegarasi**, yashirilmaydi.

### Ko'prikni qanday ishga tushirish

⚠️ **AVTOMATIK ISHGA TUSHIRISH — DEKLARATSIYA, `UNVERIFIED_ON_REAL_1C`.** COM avtomatizatsiya
**qo'shilmaydi**, o'ylab chiqarilgan buyruq satri parametri **qo'shilmaydi**, o'rnatuvchi,
xizmat, avtoyuklanish va yangilovchi **yo'q**. Ya'ni bugungi holatda ko'prikni **operator**
boshlaydi.

| yo'l | mexanika | holat |
|---|---|---|
| **A (tavsiya etiladi)** | Qayta ishlashga bitta tugmali **forma** qo'shiladi; tugma `ВыполнитьМостРазведки()` ni chaqiradi. Operator `.epf` ni yurish papkasidan ochib tugmani bosadi. | mexanika oddiy, lekin **sinalmagan** |
| **B** | Formasiz `.epf`: platformaning `/Execute` bilan modulni o'zi chaqirish qoidasiga suyaniladi. | **qoidaning o'zi bu yerda isbotlanmagan** — 1C mutaxassisi tekshirishi shart |

⚠️ B yo'li uchun kirish nuqtasining nomi va chaqirilish shartini **Designer'dagi sintaksis
yordamchisi** aytadi; bu yerda taxmin yozilmaydi. B ishlamasa A yo'li qoladi va u operator
ishini talab qiladi — bu **qobiliyat chegarasi**, yopib qo'yiladigan narsa emas.

## Kredensial

⚠️ Parol `argv`, jurnal, natija fayli, doimiy konfiguratsiya va buyruq tarixiga **hech qachon
tushmaydi**. Ishga tushirishda faqat `/F<yo'l>` yoki `/S<server>`; `/N` va `/P`
**taqiqlangan** va agent tomonida `collector_bridge._assert_no_credentials` darvozasi bilan
majburlanadi. Parolni **1C ning o'z oynasi** oladi.

⚠️ `request.json` da xom `locator` **yozilmaydi** — faqat nishon kimligining xeshi
(`target_fingerprint`). Ko'prik uni **qayta aytadi**, tekshirmaydi: xeshni qayta hisoblash
uchun kirish ma'lumoti unda yo'q. Shu bois javobdagi `target_fingerprint` **nishon
to'g'riligining dalili emas** — u faqat javobni so'rovga bog'laydi. Mustaqil dalil
`bundle/metadata.json` da.

## Xavfsizlik: nimaga TEGILMAYDI

⚠️ 1C xavfsizligi **zaiflashtirilmaydi**: xavfsiz rejimni chetlab o'tish, xavfsizlik profilini
o'zgartirish, rol tahrirlash — **taqiqlangan va qilinmagan**. Migrator APPLY yo'li ham
**yo'q**.

Ko'prik faqat o'qiydi: bazaga yozish, hujjat o'tkazish, tranzaksiya, monopol rejim, dinamik
kod bajarish, tashqi jarayon, uskuna buyrug'i, fayl nusxalash/ko'chirish/o'chirish, katalog
yaratish — **yo'q**. Taqiq `app/services/discovery_1c/epf_audit.py` ning **38 qoidasi** bilan
majburlanadi va ko'prik fragmenti shu auditdan **0 topilma** bilan o'tadi.

## Protokol qisqacha

| fayl | shartnoma | kim yozadi | qachon |
|---|---|---|---|
| `request.json` | `binos-bridge-request-v1` | AGENT | ko'prikdan oldin |
| `response.json` | `binos-bridge-response-v1` | KO'PRIK | yurishdan keyin |
| `bridge_done.json` | `binos-bridge-done-v1` | KO'PRIK | **eng oxirida** |

⚠️ Phase 4 paketining `manifest.json` i **o'zgarmaydi**: u `bundle/` ichida qoladi va o'z
navbatida oxirgi yoziladi. `bridge_done.json` — **qo'shimcha** qatlam, almashtiruvchi emas.

⚠️ Javob yozilmasa tugallanish belgisi **ham yozilmaydi**: belgi «javob diskda» degan ma'noni
bildiradi.

`status` lug'ati — yig'uvchining **o'z** lug'ati, ustiga bitta qiymat qo'shilgan:

| qiymat | ma'nosi |
|---|---|
| `SUCCESS` / `PARTIAL` / `FAILED` | `bundle/run_status.json`.`overall` dan **diskdan o'qilgan** |
| `BRIDGE_REJECTED` | ko'prik yurishni **boshlamadi** (so'rov tekshiruvdan o'tmadi) |

⚠️ **NEGA `REJECTED` EMAS (topilgan to'qnashuv).** `REJECTED` mavjud yig'uvchida
allaqachon bor, lekin **boshqa ma'noda**: u `bundle/errors.json` ning `code` lug'atidagi
qiymat (`WRITE_FAILED | PROBE_FAILED | REJECTED | UNHASHABLE`) va **rejim** rad
etilganini bildiradi, yurish rad etilganini emas. Bir xil so'z ikki shartnomada — bu
aynan `status.json` va `run_status.json` ni ajratishga majbur qilgan naqsh, shu bois
ko'prikning qiymati o'z prefiksini oladi.

⚠️ Holat **diskdagi** `run_status.json` dan o'qiladi, xotiradagi qaytarilgan qiymatdan emas:
agent faqat fayllarni ko'radi, ikki manba ajralib ketsa diskdagi fayl haqiqat bo'ladi.
O'qilmasa `FAILED` (fail-closed).

### `notes` — **kodlar massivi**, erkin matn emas

`notes` JSON'da **matnlar massivi** bo'lib yoziladi va unga **faqat kod** tushadi:

`SELF_PATH_UNAVAILABLE` · `SELF_PATH_EMPTY` · `SELF_PATH_UNREADABLE` ·
`RUN_DIR_NOT_EMPTY` · `REQUEST_NOT_FOUND` · `REQUEST_UNREADABLE` ·
`REQUEST_NOT_AN_OBJECT` · `RUN_ID_MALFORMED` · `NONCE_MALFORMED` ·
`FINGERPRINT_MALFORMED` · `REQUEST_VERSION_MISMATCH` · `REQUEST_FIELD_MISSING` ·
`WRONG_COLLECTOR_VERSION` · `OUTPUT_DIR_MISSING` · `OUTPUT_DIR_OUTSIDE_RUN` ·
`RUN_STATUS_MISSING` · `RUN_STATUS_UNREADABLE` · `RUN_STATUS_NOT_AN_OBJECT` ·
`RUN_STATUS_UNKNOWN_OVERALL` · `COLLECTOR_RAISED` · `BRIDGE_WRITE_FAILED`

⚠️ **XOM 1C XATO MATNI `notes` GA TUSHMAYDI.** `ОписаниеОшибки()` **fayl yo'lini** o'z
ichiga olishi mumkin, agent tomonidagi `notes` darvozasi esa shubhali qiymat ko'rsa **butun
hujjatni rad etadi**. Ya'ni xato matnini yozish nuqson sababini yo'qotib, ustiga yana bitta
nuqson qo'shardi. Matn **operatorga 1C oynasida** ko'rsatiladi.

⚠️ **CHEGARA:** paketli (fonda) ishga tushirishda operator xabari **ko'rinmaydi**, va
`ВыполнитьРазведку` birorta fayl yozishdan **oldin** yiqilsa, tafsilot faqat **kod** bo'lib qoladi.
Paket chiqqan holatda tafsilot baribir `bundle/errors.json` da.

### Kimlik shakli — **yozishdan oldin**

| maydon | shakl |
|---|---|
| `run_id` | bo'sh bo'lmagan matn |
| `nonce` | **32–128** ta **kichik** hex belgi (`0-9a-f`) |
| `target_fingerprint` | **aynan 64** ta **kichik** hex belgi (sha256) |

⚠️ Shakl buzuq bo'lsa ko'prik **hech narsa yozmaydi**. Sabab: javob so'rovning kimligini
**qayta aytadi**, demak buzuq kimlik bilan yozilgan javobni agent umuman ajratib o'qiy
olmaydi va u `BRIDGE_SHAPE_INVALID` bo'lib qaytadi — «rad etishni aniq aytish» maqsadi
bajarilmaydi. Shunday holatda **jimlik yaxshiroq**: agent javob yo'qligini aniq ko'radi,
operator xabarni 1C oynasida o'qiydi.

⚠️ Chegaralar **agent tomonidagi shakl darvozasi bilan aynan bir xil** qilib tanlangan.
Ko'prik agent rad etadigan qiymatni qabul qilsa, nuqson yig'ish **tugagandan keyin**
ko'rinardi va operator «yig'ish tugadi, lekin BinOS qabul qilmadi» degan tushunarsiz
holatga tushardi.

## Versiya

`VERSION.json` dagi qiymat `BinOSDiscoveryCollector.bsl` dagi `МостОписаниеСборщика()`
qiymati bilan **aynan bir xil** bo'lishi shart va buni test qulflaydi.

⚠️ Agent `expected_collector` ni shu nom va versiya bilan solishtiradi; farq bo'lsa paket
`WRONG_COLLECTOR_VERSION` bilan **rad etiladi**. Ikki joyda ikki xil qiymat — Phase 4 da har
bir real paketni rad etgan naqshning aynan o'zi, shu bois bu qiymat **qo'lda** ikki joyda
yangilanadi va test ularni taqqoslaydi.

⚠️ Versiya oxiridagi `-source` **ataylab**: qurilgan `.epf` yo'q. `.epf` yig'ilgach versiya
oshiriladi va `REAL_1C_HANDOFF.md` dagi xesh ish oqimi bajariladi.

## Yig'ishdan keyin nima qilish kerak

`../REAL_1C_HANDOFF.md` — haqiqiy 1C mashinasidagi nazorat ro'yxati: manba SHA, Designer
qadamlari, `.epf` xeshini qayd etish, real-pilot tekshiruvlari va nosozlik kodlari jadvali.
