# BinOS Discovery Extractor — qurish va ishlatish

> ## ⚠️ HOLAT: RUNTIME'DA SINALMAGAN
>
> `BinOSDiscovery.bsl` — **manba matni**. U:
> - **kompilyatsiya qilinmagan** (bu mashinada 1C:Enterprise platformasi yo'q),
> - **sintaksis tekshiruvidan o'tmagan**,
> - **hech qanday 1C bazasida ishlatilmagan**,
> - shuning uchun `.epf` **fayli repoda YO'Q va soxta ravishda yaratilmaydi**.
>
> Tekshirilgan yagona narsa — **manba matni** (pastga qarang). «Ishlaydi» degan da'vo yo'q.

## Nima tekshirilgan (va nima yo'q)

| Tekshiruv | Holat | Qayerda |
|---|---|---|
| Manbada yozuv/o'tkazish/o'chirish chaqiruvi yo'qligi | ✅ **avtomatik, CI'da** | `app/services/discovery_1c/epf_audit.py` |
| Auditning o'zi ishlashi (16 qoida × buzuvchi namuna) | ✅ **avtomatik** | `tests/test_discovery_1c_epf_source.py` |
| Qonuniy chaqiruvlar yolg'on signal bermasligi | ✅ **avtomatik** | o'sha test |
| Manba o'zini «sinalmagan» deb belgilashi | ✅ **avtomatik** | o'sha test |
| **1C sintaksisi** | ❌ **YO'Q** | 1C mutaxassisi, Konfigurator |
| **Kompilyatsiya** | ❌ **YO'Q** | 1C mutaxassisi |
| **Haqiqiy bazada ishlashi** | ❌ **YO'Q** | birinchi nusxa testi |
| **Natija to'plamining to'g'riligi** | ❌ **YO'Q** | birinchi nusxa testidan keyin |

Statik auditni mahalliy ishga tushirish:

```bash
cd apps/server && python -m pytest tests/test_discovery_1c_epf_source.py -q
```

## Runtime talablari

| Talab | Qiymat | Izoh |
|---|---|---|
| 1C:Enterprise platformasi | **8.3.x**, mijozdagi baza bilan bir xil yoki undan yangi | Aniq versiya discovery'da yoziladi |
| Rejim | **Qalin klient (толстый клиент)**, oddiy yoki boshqariladigan ilova | Fayl yozish kerak |
| **Xavfsiz rejim** | ❌ **O'CHIQ bo'lishi kerak** | Xavfsiz rejim (безопасный режим) fayl yozishni taqiqlaydi |
| Huquqlar | Metadata o'qish + `Справочник`/`Регистр` larga **o'qish** | Yozuv huquqi **KERAK EMAS** — bermang |
| Litsenziya | **ПРОФ** (Базовая emas) | Базовая tashqi qayta ishlashni ochmaydi |
| Baza | **Ajratilgan nusxa**, do'kon LAN'idagi zaxira kompyuterda | `SANDBOX_RESTORE_RUNBOOK.md` |
| Bo'sh joy | Chiqish uchun ~50 MB | Katalog hajmiga qarab |

> ⚠️ **Litsenziya chegarasi.** 1C FAQ **I.19-19**: bazani qabul qiluvchi tomonda *o'sha
> konfiguratsiyani o'z ichiga olgan* «основная поставка» litsenziyasi bo'lishi shart. Shu bois
> nusxa **do'kondan tashqariga chiqarilmaydi** — u do'konning O'Z LAN'idagi zaxira kompyuterda
> tiklanadi. Batafsil: `integrations/1c/1C_PRE_VISIT_CLEARANCE.md`.

## `.epf` ni qurish (1C mutaxassisi bajaradi)

1. **Konfigurator** ochiladi (ajratilgan nusxa bazasida).
2. `Файл → Новый → Внешняя обработка`.
3. Nom: `BinOSDiscovery`.
4. `Объект → Модуль объекта` ochiladi va `BinOSDiscovery.bsl` **to'liq** ko'chiriladi.
5. **Sintaksis tekshiruvi:** `Правка → Синтаксический контроль` (yoki `Ctrl+F7`).
   Xato chiqsa — **TO'XTANG** va xatoni bizga yuboring; o'zingiz «tuzatib» ishlatmang.
6. Forma **shart emas**: qayta ishlash `ВыполнитьРазведку()` funksiyasi orqali chaqiriladi.
   Qo'lda ishga tushirish uchun oddiy forma qo'shilsa ham bo'ladi (bitta tugma → `ВыполнитьРазведку`).
7. Saqlash: `BinOSDiscovery.epf`.

## Ishga tushirish

```
1C:Enterprise (ajratilgan NUSXA bazasi)
  → Файл → Открыть → BinOSDiscovery.epf
  → chiqish papkasini ko'rsating (BO'SH papka bo'lsin)
  → ishga tushiring
```

Yoki kod orqali:

```bsl
Обработка = ВнешниеОбработки.Создать("C:\binos\BinOSDiscovery.epf");
Результат = Обработка.ВыполнитьРазведку("C:\binos\out");
```

**Kutilayotgan davomiylik:** metadata sweep soniyalar; `КОЛИЧЕСТВО(*)` sanoqlari katalog
hajmiga bog'liq — Fayzan o'lchamidagi bazada (~7k mahsulot, ~59k barkod) taxminan **1–5 daqiqa**.
⚠️ Bu **baholash**, o'lchov emas — hech qachon ishlatilmagan.

**Kutilayotgan chiqish:** `out/export.json` (shartnoma `binos-1c-export-v1`).

⚠️ Bu **to'plamning o'zi EMAS**. BinOS tomonidagi adapter uni `binos-1c-discovery-v1`
to'plamiga aylantiradi (`app/services/discovery_1c/export_adapter.py`). Vazifa ataylab
bo'lingan: to'plam qoidalari murakkab (besh a'zo, kalit oq ro'yxati, holat hisoblanishi), va
ularni men sinay olmaydigan tilda qurish xatoni tekshirib bo'lmaydigan joyga qo'yish bo'lardi.

```bash
# BinOS tomonida (nusxa emas, ishchi mashinada):
cd apps/server && python -c "
import json, pathlib
from app.services.discovery_1c import export_adapter as A
from app.services.discovery_1c import bundle as B
exp = json.loads(pathlib.Path('export.json').read_text(encoding='utf-8'))
members = A.to_bundle_members(exp, source_kind='copy')   # 'copy' — OPERATOR e'loni
print(B.content_hash(B.load_members(members)))
"
```

⚠️ `source_kind='copy'` — buni **operator** aytadi, yig'uvchi emas: qayta ishlash o'zi nusxada
ishlayotganini bila olmaydi.

## Xavfsizlik shartnomasi

Yig'uvchi quyidagilarni **hech qachon** chaqirmaydi (statik audit majburlaydi):

`Записать()` · `ЗаписатьНаборЗаписей()` · `Провести()` · `ОтменитьПроведение()` · `Удалить()` ·
`УдалитьОбъекты()` · `УстановитьМонопольныйРежим()` · `УстановитьПривилегированныйРежим()` ·
`НачатьТранзакцию()` · `ЗафиксироватьТранзакцию()` · `ОтменитьТранзакцию()` ·
`ВыполнитьОбработкуЗаполнения()` · dinamik `Выполнить()` / `Вычислить()` ·
`ОбменСВесами` / `ВыгрузитьВВесы` / `ЗаписатьPLU` · `COMОбъект`.

> ⚠️ **«Выгрузить в весы» HECH QACHON bosilmaydi** — 1C birinchi yuklashda yangi PLU'larni o'z
> registriga **yozishi** mumkin. Bu o'qish emas, yozuv amali.

## Ma'lumotni minimallashtirish

Bu versiya **faqat metadata va sanoq** oladi:

| Olinadi | Olinmaydi |
|---|---|
| Obyekt/rekvizit **nomlari** va sinonimlari | Mahsulot nomlari |
| Tip tavsifi (razryadlik, uzunlik) | Narxlar, qoldiqlar |
| `КОЛИЧЕСТВО(*)` sanoqlari | Mijoz, ta'minotchi, xodim ma'lumotlari |
| Platforma/konfiguratsiya versiyasi | Hujjat qatorlari, summalar |
| Nishon nomzodlari (faqat nom mosligi) | Barkod va PLU **qiymatlari** |

Biznes ma'lumotini ko'chirish — **alohida, keyingi qadam**, alohida ruxsat bilan.

## Chiqishni yuborishdan oldin

`discovery.json` **konfiguratsiya tuzilmasini** ochib beradi. Yuborishdan oldin mijoz uni
ko'rib chiqsin. BinOS tomonida `redact.py` sirlarni (ulanish satri, parol, token, e-pochta,
telefon) qidiradi va **topilsa to'plamni RAD etadi** — lekin bu ikkinchi qator himoya, birinchisi
odam ko'rigi.
