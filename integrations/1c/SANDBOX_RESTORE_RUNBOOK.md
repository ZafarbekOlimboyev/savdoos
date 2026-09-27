# Nusxani SANDBOX ga tiklash — operator runbook

**Nima uchun bu hujjat bor.** Nusxani uyga olib ketib ocha olmaymiz: 1C ning rasmiy litsenziya
javoblari (**I.19-19**) bazani qabul qiluvchidan *o'sha baza qurilgan konfiguratsiyani o'z ichiga
olgan* «основная поставка» litsenziyasini talab qiladi, aks holda nusxani o'z kompyuterida ochish
«неправомерно». Bu **har qanday bepul litsenziyani** (Комьюнити, учебная) yopadi. Matn Qirg'izistondagi
rasmiy saytda (`1c.kg`) ham aynan shunday.

Shu bois nusxa **do'konning O'Z tarmog'idagi zaxira kompyuterda** ochiladi: baza uchinchi shaxsga
umuman o'tmaydi, va litsenziya hududi (**I.1-1**: «локальная сеть пользователя») buzilmaydi.

⚠️ **Copy-first siyosati kuchsizlantirilmaydi.** Jonli bazada hech qachon hech narsa ishlamaydi.
Bu hujjat faqat NUSXA haqida.

---

## 0. Sandbox shartlari — hammasi MAJBURIY

| # | Shart | Nega |
|---|---|---|
| 1 | **Jonli infobase ro'yxati/ulanishi QAYTA ISHLATILMAYDI** | Bitta noto'g'ri tanlov = jonli bazada ish |
| 2 | Ro'yxatda **aniq yorliq: `ФАЙЗАН КОПИЯ — НЕ РАБОЧАЯ`** | Kechasi, charchaganda, ro'yxatdagi ikki qator farqlanishi shart |
| 3 | **Kassirlar va xodimlar ulanmaydi** | Nusxada qilingan ish yo'qoladi va chalkashlik tug'diradi |
| 4 | **Jonli almashinuv / sinxronizatsiya vazifalari o'chirilgan** | Nusxa jonli bazaga yoki tashqi tizimga yozib yuborishi mumkin |
| 5 | **OneDrive / Google Drive / bulutga sinxronlanadigan papka ISHLATILMAYDI** | Do'konning butun bazasi bulutga ketadi |
| 6 | Tiklash va yig'uvchi ishlayotganda **LAN uzilgan bo'lsin** (tavsiya) | 4-shartning fizik kafolati |
| 7 | **Jonli bazaga `.epf` HECH QACHON** | Egaga berilgan yozma va'da |
| 8 | **Tiklangan baza QAYSI nusxadan kelgani isbotlansin** | Pastda, 2-bo'lim |

---

## 1. Tiklashdan OLDIN — nusxani qayd etish

Bu qadam o'tkazib yuborilmaydi: keyinchalik «bu qaysi nusxa edi?» degan savolga javob **faqat shu
yerdan** chiqadi.

```powershell
# 1. Nusxa faylining barmoq izi
Get-FileHash -Algorithm SHA256 <nusxa.dt yoki 1Cv8.1CD>
Get-Item <nusxa> | Select-Object Name, Length, LastWriteTime, CreationTime
```

Yozib olinadigan **oltita** qiymat:

| Qiymat | Manba |
|---|---|
| `copy_sha256` | yuqoridagi buyruq |
| `copy_size_bytes` | `Length` |
| `copy_file_mtime` | `LastWriteTime` (vaqt zonasi bilan) |
| **`source_snapshot_at`** | **nusxa OLINGAN lahza** — administratorning yozma qaydi, fayl vaqti EMAS |
| `taken_by` | nusxani olgan odamning ismi |
| `freeze_declared_at` | savdo to'xtatilgan lahza (cutover kunida) |

⚠️ **`source_snapshot_at` — eng muhim qiymat.** U *jonli 1C holati muzlatilgan/nusxa olingan*
lahzani bildiradi. U **yig'uvchi ishlagan vaqt ham, tiklash vaqti ham, bundle yaratilgan vaqt ham
EMAS**. Eski nusxaga yangi vaqt yozish — **qat'iyan taqiqlangan**.

Uchta nazorat hisoboti (`Остатки на складах`, `Цены по видам цен`, shtrix-kod ro'yxati) **jonli
bazadan**, aynan shu lahzada olinadi — ular nusxaning yagona mustaqil o'lchagichi.

## 2. Tiklash

1. Zaxira kompyuter: do'kon LAN'ida, **ishchi kassa EMAS**, bo'sh disk hajmi nusxadan kamida 3× ko'p.
2. Nusxa fayli **bulutga sinxronlanmaydigan** mahalliy papkaga ko'chiriladi (masalan `C:\1c_sandbox\`).
   **Рабочий стол va «Документы» ISHLATILMAYDI** — ular ko'pincha OneDrive'ga ulangan.
3. LAN kabeli uziladi (yoki Wi-Fi o'chiriladi).
4. 1C ishga tushirish oynasida **«Добавить» → «Создание новой информационной базы» → «Создание
   информационной базы без конфигурации»**, nomi: `ФАЙЗАН КОПИЯ — НЕ РАБОЧАЯ`, joyi `C:\1c_sandbox\base`.
   ⚠️ Jonli baza qatori **tanlanmaydi va tahrirlanmaydi**.
5. Yangi (bo'sh) bazaning **Конфигуратор**ida: «Администрирование» → «Загрузить информационную базу…»
   → nusxa fayli.
   ⚠️ Bu buyruq **faqat shu yangi bo'sh bazada** bosiladi. Jonli baza ro'yxatda tanlangan bo'lsa —
   to'xtang va qaytadan boshlang.
6. Birinchi kirishda 1C **«Это копия или перемещение?»** deb so'rashi mumkin — **«копия»** javobi
   beriladi: shunda almashinuv vazifalari avtomatik bloklanadi *(экранда tekshirilsin)*.
7. Kirgach darhol: reglament/fon vazifalari o'chirilganini tekshiring, almashinuv sozlamalarini
   **ochmasdan** qoldiring.

## 3. Tiklashdan KEYIN — nusxa aynan o'shami

Tiklangan bazada, **faqat o'qish** bilan:

- `infobase_id` (agar mavjud bo'lsa) va konfiguratsiya nomi/versiyasi yozib olinadi — ular
  `discovery.json` ning `source` blokiga tushadi;
- uchta nazorat hisoboti **qayta** shakllantiriladi va do'kondan kelgan asl nusxalari bilan
  solishtiriladi: `Итого` qiymatlari **aynan** teng bo'lishi kerak.

⚠️ Mos kelmasa — **to'xtang**. Nusxa boshqa bazadan olingan yoki tiklash to'liq emas. Bu yagona
tekshiruv bo'lib, u nusxa **qaysi** bazadan kelganini ko'rsata oladi.

## 4. Hech qachon bosilmaydi

Jonli bazada **va** sandboxda bir xil:

- **«Загрузить информационную базу…»** — jonli bazada hech qachon (ishchi bazani o'chiradi)
- **«Тестирование и исправление…»** — bu YOZUV amali
- **«Выгрузить в весы»** / tarozi dasturida **«Выгрузить» / «Загрузить» / «Отправить»** — 1C birinchi
  yuklashda yangi PLU'larni **yozishi** mumkin
- «Блокировка сеансов», «Региональные установки информационной базы», «Параметры информационной
  базы», «Настройка журнала регистрации» — hammasi ayni menyuda turadi
- Конфигуратор'da, **chiqarishning o'z tasdig'idan boshqa har qanday savolga** — «Нет» yoki «Отмена»

## 5. Ish tugagach

1. Sandbox bazasi va nusxa fayli **o'chiriladi** — jumladan ulardan kelib chiqqan hamma narsa:
   tiklangan baza, uning jurnali, `report.json` / `mapping.json` / `plan.json` va nazorat hisobotlari
   nusxalari.
2. Egaga **yozma tasdiq** beriladi: nima o'chirildi, qachon, kim.
3. Zaxira kompyuter o'z holiga qaytariladi, LAN ulanadi.

---

## Bog'liq hujjatlar

- Tashrifdan oldingi darvoza — [`docs/1C_PRE_VISIT_CLEARANCE.md`](../../docs/1C_PRE_VISIT_CLEARANCE.md)
- Nusxa olish tartibi (do'kon tomoni) — [`FAYZAN_1C_DISCOVERY_CHECKLIST.md`](FAYZAN_1C_DISCOVERY_CHECKLIST.md), **Вопрос 3**
- Discovery to'plami formati — [`DISCOVERY_BUNDLE_V1.md`](DISCOVERY_BUNDLE_V1.md)
- Migratsiya fayli shartnomasi — [`BINOS_1C_BUNDLE_V1.md`](BINOS_1C_BUNDLE_V1.md)
