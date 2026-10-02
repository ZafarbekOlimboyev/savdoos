# Birinchi HAQIQIY nusxa testi — operator ro'yxati

> **Maqsad:** mijozning 1C bazasidan **ajratilgan nusxa** olish va unda **faqat o'qiydigan**
> discovery'ni bir marta ishga tushirish.
>
> **Bu QADAM MIGRATSIYA EMAS.** Hech narsa BinOS'ga ko'chirilmaydi. Cutover alohida, keyin.
>
> ⚠️ Ekstraktor **runtime'da sinalmagan** (`extractor/README.md`). Shu bois birinchi yurish —
> bu ham **ekstraktorning o'zini sinash**, ham ma'lumot yig'ish. Muvaffaqiyatsizlik **kutilgan
> natija** va u nuqson emas: shuning uchun ham nusxada bajarilmoqda.

---

## 0. Mendan (BinOS tomonidan) tayyor

| Narsa | Holat |
|---|---|
| Ekstraktor manbasi `BinOSDiscovery.bsl` | ✅ tayyor, statik audit yashil |
| Qurish yo'riqnomasi | ✅ `extractor/README.md` |
| To'plam sxemasi + validator + redaksiya | ✅ 1C'siz to'liq sinalgan |
| `.epf` **fayli** | ❌ **YO'Q** — 1C mutaxassisi quradi |
| Sintaksis tasdig'i | ❌ **YO'Q** — 1C mutaxassisi beradi |

## 1. MIJOZDAN NIMA KERAK (siz so'rashingiz kerak bo'lgan narsalar)

| # | So'raladigan narsa | Nega | Bloklaydimi |
|---|---|---|---|
| M1 | **1C:Enterprise ПРОФ litsenziyasi** zaxira kompyuterda | Базовая tashqi qayta ishlashni ochmaydi | ✅ HA |
| M2 | **Zaxira kompyuter** do'kon LAN'ida (nusxa tiklanadi) | Litsenziya I.19-19: nusxa do'kondan chiqmaydi | ✅ HA |
| M3 | **1C mutaxassisi** (yoki 1C'ni biladigan xodim) 30–60 daq | `.epf` qurish + sintaksis tekshiruvi | ✅ HA |
| M4 | **Egasining yozma roziligi** nusxa olishga | Ma'lumot egasi qarori | ✅ HA |
| M5 | 1C platformasining **aniq versiyasi** | Nusxa mos platformada tiklanadi | ✅ HA |
| M6 | Konfiguratsiya **o'zgartirilganmi** (ochiq/yopiq) | O'zgartirilgan bo'lsa nom mosligi hech narsani isbotlamaydi | ⚠️ qisman |
| M7 | Bazada **necha ta baza/tashkilot** bor | Ko'p tashkilotli bo'lsa doira aniqlanishi kerak | ⚠️ qisman |
| M8 | **Tarozi dasturi** nomi va versiyasi | PLU manbasi (D27) hamon ochiq | ❌ yo'q |

## 2. Zaxira va ajratilgan tiklash

1. Do'kon **yopiq** bo'lsin (savdo yo'q). Bu discovery uchun shart emas, lekin nusxa
   kuni cutover mashqi bilan birlashtirilsa — shart.
2. 1C'da: `Администрирование → Выгрузить информационную базу` → `.dt` fayl.
   *Yoki* fayl bazasi bo'lsa — 1C **yopiq** holatda `1Cv8.1CD` nusxasi.
3. `.dt` **zaxira kompyuterga** ko'chiriladi (tashqi diskda, internetsiz).
4. Zaxira kompyuterda **yangi bo'sh baza** yaratiladi → `Загрузить информационную базу`.
5. ⚠️ **Zaxira kompyuter tarmoqdan uziladi** — lekin **avval soati to'g'rilanadi**
   (o'lik CMOS `2000-01-01` beradi; `SANDBOX_RESTORE_RUNBOOK.md`).
6. ⚠️ **Nusxa olingan LAHZA yozib qo'yiladi** (sana + soat + kim). Bu keyin `snapshot_at`
   bo'ladi va uni server tekshira **olmaydi** — u sizning yozma qaydingizga tayanadi.
7. ⚠️ Nusxa fayli **sha256** va **bayt hajmi** yozib olinadi (`certutil -hashfile <fayl> SHA256`).
   Keyin `source_copy` bilan solishtiriladi.

## 3. Ekstraktorni qurish

`extractor/README.md` bo'yicha. **Sintaksis xatosi chiqsa — to'xtang va menga yuboring.**
O'zingiz tuzatmang: tuzatilgan manba auditdan o'tmagan bo'ladi.

## 4. Ishga tushirish

- Baza: **faqat tiklangan nusxa**. Jonli bazada **hech qachon**.
- Huquq: **o'qish yetarli**. Yozuv huquqi bermang.
- Chiqish: **bo'sh papka**.
- Kutilayotgan davomiylik: **1–5 daqiqa** (baholash, o'lchov emas).

⚠️ **«Выгрузить в весы» / «Обмен с весами» tugmalari HECH QACHON bosilmaydi.**

## 5. Natijani ko'rish (yuborishdan OLDIN)

`discovery.json` konfiguratsiya **tuzilmasini** ochib beradi. Mijoz ko'rib chiqsin:

- [ ] Mahsulot **nomlari** yo'q (faqat metadata nomlari bo'lishi kerak)
- [ ] Narx/qoldiq **qiymatlari** yo'q
- [ ] Mijoz/ta'minotchi/xodim ma'lumoti yo'q
- [ ] Parol, ulanish satri, token yo'q
- [ ] Faqat sanoqlar (`КОЛИЧЕСТВО(*)`) va tip tavsiflari

BinOS tomonida `redact.py` ham qidiradi va **sir topilsa to'plamni RAD etadi** — lekin
bu ikkinchi qator. Birinchisi — odam ko'rigi.

## 6. Tekshirish (BinOS tomonida)

Yig'uvchi `export.json` (`binos-1c-export-v1`) beradi. Uni avval **adapter** to'plamga
aylantiradi, keyin to'plam tekshiriladi:

```bash
cd apps/server && python -c "
import json, pathlib
from app.services.discovery_1c import export_adapter as A, bundle as B
exp = json.loads(pathlib.Path('export.json').read_text(encoding='utf-8'))
b = B.load_members(A.to_bundle_members(exp, source_kind='copy'))
print(b.status['status'], B.content_hash(b))
"
```

Kutilayotgan: holat `COMPLETE` yoki `PARTIAL`.

⚠️ **Hamma xarita `CANDIDATE` yoki `UNKNOWN` bo'ladi.** Adapter darajani KO'TARMAYDI —
`VERIFIED` faqat odam ko'rigi bilan, alohida qadamda beriladi.
⚠️ `PARTIAL` — **normal**: yiqilgan bo'lim jimgina tushirilmaydi, u xatosi bilan qoladi.

## 7. Konfiguratsiyaga bog'liq bloklar (kutilgan)

| Blok | Nima bo'ladi | Holat |
|---|---|---|
| **Xarakteristikalar** (`has_characteristics`) | V1 da HAR QATOR bloklanadi | ⛔ ochiq STOP |
| **PLU manbasi** (D27) | Nomdan PLU yozish TAQIQ (qamrov 0.9%) | ⛔ ochiq |
| Konfiguratsiya o'zgartirilgan | Nom mosligi isbot emas — hammasi CANDIDATE | ⚠️ kutilgan |
| Ko'p tashkilot | Doira aniqlanishi kerak | ⚠️ kutilgan |
| Tarozi dasturi 1C'dan tashqarida | PLU 1C'da umuman bo'lmasligi mumkin | ⚠️ kutilgan |

## 8. Keyingi qadamlar (discovery'dan KEYIN)

1. `discovery.json` ni ko'rib chiqish → qaysi nishon qaysi obyektga tushadi.
2. Har nishon uchun **VERIFIED** dalil yig'ish — nom mosligi **yetarli emas**.
   Kerak: odam tasdig'i, arifmetik isbot yoki mustaqil manbalar kelishuvi.
3. **Adapter** yozish (`discovery_1c/adapters/`) — konfiguratsiyaga xos bilim faqat shu yerda.
4. Adapter chiqishini `binos-1c-v1` bundle'ga aylantirish (bu **hali yozilmagan**).
5. Quruq yurish → conflict review → reja → rehearsal → cutover.

---

## Nima HAL QILINMAGAN (ochiq aytaman)

- `.epf` **hech qachon ishlatilmagan**. Birinchi yurish uni ham sinaydi.
- Discovery → migrator **konvertori yozilmagan**. Discovery hozir odam o'qishi uchun.
- Xarakteristikalar va D27 **ochiq STOP** bo'lib qolmoqda.
- Tarozi bilan sinxronizatsiya BinOS tomonida **stub** — cutover'dan keyingi egasiz qadam.
