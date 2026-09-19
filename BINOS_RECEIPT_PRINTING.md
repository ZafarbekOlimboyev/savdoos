# BinOS — chek va chop etish (Phase 5F)

> **Kim uchun:** do'kon egasi / administrator (Manager «Sozlamalar → Chek va printer»), kassa
> o'rnatuvchi (POS «Printer»), qo'llab-quvvatlash.
> **Asosiy qoida:** chek — sotuvdan KEYINGI yon ta'sir. Printer yo'qligi, qog'oz tugashi yoki
> uzilgan kabel sotuvni HECH QACHON bekor qilmaydi va to'xtatmaydi.

---

## 1. Arxitektura — summa qayerdan keladi

```
Sotuv/qaytarish (serverda saqlangan)
  → GET /sales/{id}/receipt | /returns/{id}/receipt   — kanonik ReceiptDTO (binos.receipt.v1)
  → layoutReceipt (58 mm = 32 ustun, 80 mm = 48 ustun)  — bitta qator modeli
  → renderHtml (Manager preview, tizim printer drayveri) | encodeEscPos (LAN / Windows RAW)
```

- **Buxgalteriya haqiqati — serverda.** Onlayn sotuv cheki HAR DOIM serverdagi yozuvdan chiziladi:
  qatorlar, chegirmalar, yaxlitlash, to'lovlar (naqd berilgan/qaytim, karta, QR, nasiya, aralash).
  Chekdagi qatorlar + chegirma + yaxlitlash = JAMI aniq qo'shiladi.
- **Oflayn sotuv** (internet yo'q) cheki POS'ning o'zi yuborgan ma'lumotdan chiziladi va ustida
  aniq yozuv bo'ladi: «OFLAYN — VAQTINCHALIK», raqami `OFFLINE-XXXXXXXX`. Sotuv serverga yetgach
  haqiqiy chekni «Sotuvlarim»dan qayta chop etish mumkin.
- Preview va qog'oz bir xil qator modelidan chiqadi: Manager'dagi ko'rinish = chop etiladigan chek.

## 2. Shablon sozlamalari va filial override

Saqlanadi: `settings` jadvali. Kompaniya standarti — `key='receipt'`, filial override —
`key='receipt_branch'` + `branch_id`. Rezolyutsiya: **filial override → kompaniya standarti →
o'rnatilgan standartlar.**

| Maydon | Standart | Izoh |
|---|---|---|
| Logo (`show_logo`, `logo_id`) | yoqilgan (logo bo'lsa) | §3 |
| Do'kon nomi / manzil / telefon | `store_info` → filial ma'lumoti | bo'sh qoldirilsa merosdan olinadi |
| Sarlavha, pastki matn (footer) | yo'q / «Xaridingiz uchun rahmat!» | faqat matn; ketma-ket bo'sh qatorlar bittaga yig'iladi; ko'pi bilan 30 YOZILGAN qator va 2000 belgi (chekka sig'maydigan uzun qator o'raladi, kesilmaydi) |
| Qog'oz kengligi | 80 mm | 58 yoki 80 |
| Chek tili | kassa interfeysi tili | uz / uzc / ru / ky |
| Ko'rinadigan maydonlar | filial, STIR, kassir, to'lov tafsiloti, chegirma — ha; kassa kodi, mijoz, shtrix-kod — yo'q | mijoz ismi faqat yoqilganda serverdan beriladi |
| QR | yo'q | «chek identifikatori» (sotuv `uid` — qaytarishda skanerlanadi) yoki «do'kon havolasi» (https URL). To'lov QR'i bilan ARALASHMAYDI; QR ichida token/maxfiy ma'lumot yo'q |
| Avto-kesish, nusxa soni (1–3), avto-chop | ha, 1, yo'q | avto-kesish faqat printer qo'llasa |

**Kim o'zgartiradi:** `sozlamalar.edit`. Kompaniya standartini faqat barcha filiallarni ko'radigan
xodim (ega yoki filialga biriktirilmagan xodim) o'zgartiradi; filialga biriktirilgan administrator —
faqat o'z filiali override'ini. Bir filial sozlamasi boshqa filialga sizmaydi.
`GET /settings` faqat kompaniya darajasidagi qatorlarni qaytaradi.

## 3. Logo

- PNG / JPEG / WebP, ko'pi bilan 2 MB, 16×16 … 2048×2048 piksel. Tur fayl nomidan emas, baytlardan
  aniqlanadi; animatsiya, buzilgan fayl, «dekompressiya bombasi», juda ko'p skanli JPEG rad etiladi.
- Asl fayl o'zgarmasdan saqlanadi va HECH QACHON qaytarilmaydi. Printer uchun serverda bir marta
  tayyorlanadi: kulrang → oq fonga → proporsiya saqlangan holda kichraytirish → Floyd–Steinberg
  bilan 1-bit. 58 mm (≤384 nuqta) va 80 mm (≤512 nuqta) variantlari keshlanadi — har chop etishda
  qayta ishlanmaydi.
- Bir xil fayl qayta yuklansa yangi yozuv yaratilmaydi (deterministik id).

## 4. Printerni ulash (har kompyuterda alohida)

Printer — QURILMA sozlamasi (serverda emas): POS'da «Printer» menyusi (yoki chop etish xatosidagi
«Printer sozlamasi» — sotuv ekranini tark etmasdan oynada ochiladi), Manager'da «Sozlamalar → Chek va
printer → Printer». Transportlar:

| Transport | Qachon | Eslatma |
|---|---|---|
| Tizim printeri (Windows drayveri) | printer Windows'da o'rnatilgan | HTML orqali; har qanday Unicode (kirill, qirg'iz, o'zbek) to'g'ri chiqadi. «Qog'oz uzunligi»: **aniq** (sahifa = chek uzunligi) yoki **printer drayveri** (5F dan oldingi xulq: o'lchamni drayver belgilaydi). 3276 mm dan uzun chek avtomatik drayver rejimida chiqadi |
| LAN ESC/POS | tarmoq printeri, port 9100–9109 | faqat lokal IPv4 (10.x, 172.16–31.x, 192.168.x, 169.254.x) |
| Windows RAW ESC/POS | USB printer, drayver RAW qabul qiladi | printer nomi Windows ro'yxatida bo'lishi shart |
| Brauzer | veb/dev rejimi | chop etish dialogi; natija tasdiqlanmaydi |

**ESC/POS profillari** (standart `generic` — kenglik chek shablonidan; aniq kenglikli `generic58`,
`generic80`, `epson80`, `xprinter58`, `xprinter80` — kenglikni model belgilaydi): kesish,
QR (printerning o'zida / rasm sifatida / yo'q), shtrix-kod, rastr va kodlash sahifasi (cp866)
bo'yicha imkoniyatlar. **Profillar ishlab chiqaruvchi hujjatlariga asoslangan, haqiqiy qurilmada
tekshirilmagan.** Printer qo'llamagan buyruq yuborilmaydi — chek baribir chiqadi, ogohlantirish
jurnalga yoziladi. ESC/POS matnida cp866 da yo'q harflar (ў қ ғ ҳ ң ө ү) yaqin harfga
almashtiriladi; aniq Unicode kerak bo'lsa tizim printeri transportini tanlang.

**Xavfsizlik:** ilova oynasi printerga xom bayt yubora olmaydi — faqat tuzilgan chek modeli
yuboriladi, baytlarni oq ro'yxatli kodlovchi yasaydi. Pul qutisini ochish buyrug'i hech qachon
yuborilmaydi; rasm ichidagi real-vaqt buyruq ketma-ketliklari neytrallanadi.

## 5. Chop etish holatlari, asl va nusxa

- Har chop etish — jurnal yozuvi: `PENDING` → `PRINTED` yoki `FAILED` (qurilmada saqlanadi, server
  `print_jobs` ga ham yoziladi).
- **Asl chek bitta.** Birinchi chop etish — ASL; keyingilari — «NUSXA #n» bannerli nusxa. Asl chek
  qog'ozga chiqishidan OLDIN serverda band qilinadi (qurilma tokeni bilan, 120 soniyalik «ijara»):
  boshqa qurilma ayni paytda band qilolmaydi (409) va nusxa chiqaradi; ikkinchi asl 409 bilan rad
  etiladi. Server javob bermasa: sotuvni yaratgan kassa aslni chiqaradi, boshqa har qanday qurilma — nusxa.
- **Avto-chop** yoqilgan bo'lsa sotuv yakunida bir marta chiqadi (ekran qayta chizilsa ham takrorlanmaydi).
- **Qayta urinish** — xato bo'lgan AYNI yozuvni qayta chop etadi (yangi asl emas).
- Test chop etish — namunaviy chek, «*** TEST PRINT ***» bilan; bazaga HECH NARSA yozmaydi
  (sotuv, kassa, qoldiq, smena, jurnal — hech biri).

## 6. Nosozliklar

| Holat | Kassir ko'radi | Sotuv | Nima qilish |
|---|---|---|---|
| Printer tanlanmagan / topilmadi | «Xato: printer topilmadi yoki tanlanmagan» + «Printer sozlamasi» havolasi | yakunlangan | Printer menyusida tanlash, «Qayta urinish» |
| Printer o'chiq / LAN javob bermaydi | «printer javob bermayapti — tarmoq va quvvatni tekshiring» | yakunlangan | Printerni yoqish, qayta urinish |
| Qog'oz tugagan (holat so'rovini qo'llaydigan printer) | «printerda qog'oz tugagan» | yakunlangan | Qog'oz qo'yish, qayta urinish |
| Tizim printeri chekni bo'lib/chiqarmay qo'ydi | — | — | Printer sozlamasida «Qog'oz uzunligi: Printer drayveri» |
| Kesish qo'llanmaydi | chek chiqadi, kesilmaydi | — | profilda kesishni o'chirish |
| Logo chizilmadi | chek logosiz chiqadi | — | logoni qayta yuklash |
| Internet yo'q | OFLAYN vaqtinchalik chek | navbatda | sinxronlangach «Sotuvlarim»dan haqiqiy chek |
| Chek ma'lumoti olinmadi (server javob bermadi) | «chek ma'lumoti olinmadi» | yakunlangan | tarmoq tiklangach «Qayta urinish» |
| Kassirda `sotuvlar.view` o'chirilgan | chek baribir chiqadi — faqat O'Z sotuvi | yakunlangan | — |

## 7. Ma'lum cheklovlar

- Haqiqiy printerda sinalmagan (§8 bajarilmaguncha).
- 5F klientlari 5F dan oldingi serverda faqat O'Z sotuvini eski usulda chop etadi; tartib — avval
  server, keyin klient (`CLAUDE.md`).
- ESC/POS kodlash sahifasi cp866/cp1251; qirg'iz va o'zbek kirilining maxsus harflari
  transliteratsiya qilinadi.
- Asl chekni band qilgan qurilmaning «chop etildi» hisoboti 120 soniyadan ko'proq yo'qolsa, ijara
  tugaydi va boshqa qurilma yana asl chiqarishi mumkin (vaqtga asoslangan ijara chegarasi).
- Tarmoq printerida «chop etildi» — printer baytlarni qabul qildi degani; qog'oz chiqqanini faqat
  holat so'rovini qo'llaydigan profil oldindan tekshiradi (qog'oz tugashi).

## 8. Haqiqiy printer pilot tekshiruvi (birinchi kun, har printer modeli uchun)

1. Test chop etish 58 va 80 mm da: qatorlar kesilmagan, o'ng ustun raqamlari tekis.
2. Kirill (rus), o'zbek lotin (oʻ gʻ), qirg'iz (ң ө ү) nomli mahsulot — tizim va ESC/POS transportlarida.
3. Logo: aniq, cho'zilmagan; 58 mm da qog'ozdan chiqmaydi.
4. Kesish: qisman/to'liq kesish ishlaydi yoki profilda o'chirilgan.
5. QR va shtrix-kod: telefon/skaner bilan o'qiladi; qaytarish ekranida `uid` bo'yicha chek topiladi.
6. 100+ qatorli chek: sahifalarga bo'linmaydi (tizim printeri «aniq» uzunlik bilan).
7. Printerni o'chirib sotuv: sotuv yakunlanadi, holat «Xato», yoqilgach «Qayta urinish» chiqaradi.
8. Qog'ozni olib qo'yib (LAN, holat so'rovi bor profil): «Qog'oz tugagan».
9. Pul qutisi ulangan bo'lsa: hech bir chek (logoli ham) qutini ochmaydi.
