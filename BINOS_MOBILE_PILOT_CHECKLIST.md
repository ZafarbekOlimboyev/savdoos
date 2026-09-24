# BINOS mobil pilot — tekshiruv ro'yxati (Android real qurilma + iPhone PWA)

> ## ⛔ HECH BIR QATOR HALI BAJARILMAGAN
>
> **Bu hujjat — reja, natija emas.** Phase 5G.1 da **haqiqiy Android telefon ham, haqiqiy
> iPhone ham ishlatilmagan.** Quyidagi har bir «Dalil» katagi ataylab **bo'sh**.
> Katakni faqat o'sha qadamni **haqiqiy qurilmada** bajargan odam to'ldiradi
> (sana + qurilma modeli + OS versiyasi + skrinshot/log yo'li).
>
> Bo'sh dalil = bajarilmagan. «Ishlashi kerak» — dalil EMAS.
> Hech qachon «REAL ANDROID DEVICE VERIFIED» yoki «REAL IPHONE PWA VERIFIED» deb yozmang,
> agar shu ro'yxatning tegishli qismi to'ldirilmagan bo'lsa.

Baza: `main = 33ea7b1` ustiga Phase 5G.1. Production serveri `99b1da7` — **faqat o'qish**,
bu pilotda unga hech narsa yozilmaydi va deploy qilinmaydi.

---

## 0. Bu builddagi artefakt aniq nima (o'lchangan, taxmin emas)

| Nima | Qiymat | Qanday aniqlangan |
|---|---|---|
| Fayl (APK) | `apps/mobile/build/app/outputs/flutter-apk/app-release.apk` | `flutter build apk --release` |
| Hajmi | 78 927 704 bayt (≈75.3 MB, uchala ABI bitta APK ichida) | `ls -l` |
| Fayl (AAB) | `apps/mobile/build/app/outputs/bundle/release/app-release.aab` | `flutter build appbundle --release` |
| Hajmi (AAB) | 70 278 388 bayt (≈67.0 MB) — o'sha keystore bilan imzolangan (`keytool -printcert -jarfile`) | `ls -l` |
| `applicationId` | `com.savdoos.savdoos_mobile` | `aapt2 dump badging` |
| `versionName` / `versionCode` | **0.7.0 / 56** | `aapt2 dump badging` |
| min / target / compile SDK | 24 / 36 / 36 | `aapt2 dump badging` |
| ABI | `arm64-v8a`, `armeabi-v7a`, `x86_64` | `aapt2 dump badging` |
| **Imzo** | **Repodagi mavjud lokal release keystore bilan imzolangan** (v2 sxema; sertifikat DN `CN=SavdoOS, … C=KG` — ya'ni Android debug kaliti EMAS). Bu keystore'ning kelib chiqishi va zaxirasi bu ishda **noma'lum**. | `apksigner verify -v --print-certs` |
| **Bu nima EMAS** | **PRODUCTION SIGNED emas.** Play App Signing ishlatilmagan, yangi kalit yaratilmagan, hech qanday kalit materiali o'qilmagan/chop etilmagan/o'zgartirilmagan. | — |
| Server | `--dart-define=BINOS_ENV=staging`, `BINOS_API_BASE=https://savdoos-staging.up.railway.app` bilan yig'ilgan | build buyrug'i |

**Ogohlantirish (imzo).** `key.properties` va keystore faqat shu mashinada turibdi va ikkalasi ham
gitignore'da. Ularning boshqa joyda zaxirasi bor-yo'qligi noma'lum. **Kalit yo'qolsa** — pilot
telefonlariga o'rnatilgan APK boshqa hech qachon yangilanmaydi (qayta o'rnatish = butun lokal
holat yo'qoladi). Haqiqiy do'konga APK berishdan **oldin** keystore'ni ishonchli joyga zaxiralash
shart. Bu kod o'zgarishi emas — tashkiliy qadam.

**Ogohlantirish (debug imzo).** `-PallowDebugSigning` bilan yig'ilgan «release» APK tashqi
ko'rinishidan haqiqiysidan **farq qilmaydi**. Agar pilot telefoniga avval debug-imzoli build
tushsa, keyin to'g'ri imzolangani `INSTALL_FAILED_UPDATE_INCOMPATIBLE` bilan o'rnatilmaydi va
telefonni tozalashga to'g'ri keladi. Pilotga **hech qachon** `-PallowDebugSigning` bilan yig'ilgan
faylni bermang.

---

## 1. Aniq build va o'rnatish buyruqlari

Hammasi `apps/mobile/` dan bajariladi. `PATH` da Flutter bo'lsin (`export PATH="/c/flutter/bin:$PATH"`).

### 1.1 Qoidalar (buzilmaydi)

1. **Har doim `flutter` orqali yig'ing, hech qachon `./gradlew` bilan emas.**
   `versionName`/`versionCode` ni `flutter` tool `pubspec.yaml` dan olib `android/local.properties`
   ga yozadi (u fayl gitignore'da). Yalang'och Gradle eski yoki standart (`1.0`/`1`) raqamni oladi —
   ya'ni yolg'on versiya bilan APK chiqadi.
2. **`--build-name` / `--build-number` bermang.** Ular pubspec'ni bekor qiladi va yagona manba
   qoidasini buzadi.
3. **Har yangi pilot buildida `pubspec.yaml:4` dagi build raqami oshadi** (`0.7.0+56` → `0.7.0+57` → …).
   Build raqami hech qachon qayta ishlatilmaydi va o'tkazib yuborilmaydi.
4. **Sirlar `--dart-define` ga qo'yilmaydi.** U yerga faqat host nomi va muhit nomi boradi —
   Flutter bundle ichidagi hamma narsa o'qiladi.
5. **Staging va production APK bir xil `applicationId` ga ega** — ya'ni bitta telefonda birga
   tura olmaydi. Pilot telefonida ikkalasi kerak bo'lsa, `applicationIdSuffix` li alohida build
   type kerak (bu 5G.1 da **qilinmagan**, §4 ga qarang).

### 1.2 STAGING build (pilot uchun shu ishlatiladi)

```bash
cd apps/mobile
flutter build apk --release \
  --dart-define=BINOS_ENV=staging \
  --dart-define=BINOS_API_BASE=https://savdoos-staging.up.railway.app
# => build/app/outputs/flutter-apk/app-release.apk
```

App Bundle (Play uchun; pilotga kerak emas):

```bash
flutter build appbundle --release \
  --dart-define=BINOS_ENV=staging \
  --dart-define=BINOS_API_BASE=https://savdoos-staging.up.railway.app
# => build/app/outputs/bundle/release/app-release.aab
```

### 1.3 PRODUCTION build (pilot tugamaguncha **chiqarilmaydi**)

```bash
cd apps/mobile
flutter build apk --release \
  --dart-define=BINOS_ENV=production \
  --dart-define=BINOS_API_BASE=https://savdoos-production.up.railway.app
```

`BINOS_ENV` / `BINOS_API_BASE` umuman berilmasa ham build **production** bo'ladi va production
serveriga qaraydi (`Env` dagi xavfsiz standart — unutilgan bayroq pilot telefonini «hech qayerga»
qaratib qo'ymasin). Shuning uchun production buyrug'ida ham define'larni **ataylab yozing**:
buyruqqa qarab qaysi build ekani ko'rinib tursin.

Production buildda ekranda **hech qanday** muhit belgisi bo'lmaydi (badge ham, Sozlamalardagi
«Muhit» qatori ham). Staging buildda ikkalasi ham bo'ladi.

### 1.4 Telefonga o'rnatish

```bash
# USB orqali (USB debugging yoqilgan bo'lsin)
adb install -r apps/mobile/build/app/outputs/flutter-apk/app-release.apk

# yoki APK ni telefonga nusxalab, fayl menejeridan o'rnatish
# (Sozlamalar → Xavfsizlik → noma'lum manbalarga ruxsat)
```

Qaysi build o'rnatilganini telefonning o'zidan tekshirish:

```bash
adb shell dumpsys package com.savdoos.savdoos_mobile | grep -E "versionName|versionCode"
# kutilgan: versionCode=56  versionName=0.7.0
```

Ilova ichidan: **Sozlamalar → eng past qator** → `SavdoOS mobil · v0.7.0+56`
(build raqami ham ko'rsatiladi — ikki buildni faqat shu ajratadi).

---

## A. ANDROID — HAQIQIY QURILMADA

Kamida ikki telefon tavsiya etiladi: bittasi Android 15/16 (targetSdk 36 xatti-harakati uchun),
bittasi eski (minSdk 24 ga yaqin, API 24–27 — `USE_FINGERPRINT` yo'li).

### A.1 O'rnatish va identifikatsiya

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A1 | §1.4 dagi buyruq bilan STAGING APK ni o'rnatish | O'rnatiladi, xatosiz | |
| A2 | Launcher'da ilovani topish | Nomi `SavdoOS`, brend ikonkasi (ko'k-siyoh adaptive), oq kvadrat emas | |
| A3 | `adb shell dumpsys package … \| grep version` | `versionCode=56`, `versionName=0.7.0` | |
| A4 | Ilovani ochish → Sozlamalar → eng past qator | `SavdoOS mobil · v0.7.0+56` | |
| A5 | Android 13+ telefonda: launcher'ni «themed icons» rejimiga o'tkazish | Ikonka buzilmaydi (`<monochrome>` qatlami **yo'q** — kutilgani: oddiy rangli ikonka qolishi) | |

### A.2 Muhit ajratilishi (eng muhim qism — jonli do'kon ma'lumoti xavfi)

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A6 | Kirgandan keyin bosh ekran | Ekran tepasida doimiy sariq chiziq: `STAGING · savdoos-staging.up.railway.app` | |
| A7 | Qobiqning har tabiga o'tish; sessiya yuklanayotgan va sessiya xato holatlari | Chiziq **hamma** holatda ko'rinadi (yuklanish, xato, hamma tab) | |
| A7b | **Login ekrani va PIN qulfi ekrani** | ⚠️ **Hozir chiziq YO'Q** — ular qobiqdan tashqarida (`main.dart`). Ya'ni kirishdan oldin qaysi server ekani ko'rinmaydi. §4 dagi 10-xavfga qarang | |
| A8 | Sozlamalar → «Muhit» qatori | Qiymat `STAGING`, ostida to'liq API manzili | |
| A9 | Sozlamalar → «Server manzili» qatori | Host = staging hosti | |
| A10 | **PRODUCTION build** ni alohida telefonga o'rnatish (§1.3) | Sariq chiziq **yo'q**, «Muhit» qatori **yo'q**, «Server manzili» = production hosti | |
| A11 | Har yozuv amalidan oldin (qabul, kassa, hisobdan chiqarish) sariq chiziqqa qarash | Yozuv faqat STAGING chizig'i turganda qilinadi | |
| A12 | Sozlamalar → Server manzilini qo'lda o'zgartirish | Ogohlantiradi, so'ng hisobdan chiqaradi; token/PIN/kesh eski serverdan ketadi | |

> **Diqqat.** 5G.1 da server maydoni hali ham har qanday xodimga ochiq va saqlangan `base_url`
> build standartidan ustun turadi. Ya'ni production buildni ham qo'lda boshqa serverga qaratish
> mumkin. Pilotda bu ataylab qoldirilgan (staging'ga o'tish uchun kerak); production tarqatishdan
> oldin §4 dagi ochiq xavflarga qarang.

### A.3 Kamera ruxsati (yangi UX)

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A13 | Toza o'rnatishdan keyin ilovani ochib, Sozlamalar/Bosh/Analitika bo'ylab yurish | Kamera ruxsati **umuman so'ralmaydi** | |
| A14 | Birinchi marta skanerni ochish | Kamera ruxsati aynan shu payt so'raladi (feature-time) | |
| A15 | Ruxsatni **bir marta** rad etish | «Kameraga ruxsat berilmagan» ekrani; «Kodni qo'lda kiritish» (birinchi) va «Qayta urinish» tugmalari | |
| A16 | «Kodni qo'lda kiritish» → kod terish | Mahsulot topiladi — kamerasiz ish davom etadi | |
| A17 | «Qayta urinish» | Tizim dialogi yana chiqadi (hali butunlay rad etilmagan) | |
| A18 | Ruxsatni **ikki marta** / «boshqa so'rama» bilan rad etish, skanerni qayta ochish | Xato ekranida **«Sozlamalarni ochish»** tugmasi bor | |
| A19 | «Sozlamalarni ochish» ni bosish | Telefon aynan **shu ilovaning** ruxsatlar sahifasini ochadi (umumiy Sozlamalar emas) | |
| A20 | U yerda kamerani yoqib, ilovaga qaytish | Kamera o'zi ishga tushadi (lifecycle `resumed`), qayta ochish shart emas | |
| A21 | A18 holatida «Qayta urinish» ni bosish | Dialog chiqmaydi (Android shunday), lekin ekran boshqa yo'llarni ko'rsatib turibdi — boshi berk ko'cha emas | |
| A22 | Tovar qabul → nakladnoy rasmi → kamera | Rasm olinadi; ruxsat rad etilsa — tushunarli xabar, ish to'xtamaydi | |
| A23 | Kamerasi yo'q/ishlamaydigan qurilmada (yoki kamerani boshqa ilova band qilganda) skaner | «Kamera band yoki xato berdi» + qo'lda kiritish; «Sozlamalarni ochish» **chiqmaydi** (bu ruxsat muammosi emas) | |

### A.4 Ruxsatlar ro'yxati (telefonning o'zidan)

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A24 | Sozlamalar → Ilovalar → SavdoOS → Ruxsatlar | Faqat **Kamera** so'raladigan ruxsat sifatida ko'rinadi | |
| A25 | `adb shell dumpsys package com.savdoos.savdoos_mobile \| grep -A40 "requested permissions"` | Aynan 6 ta: `INTERNET`, `CAMERA`, `USE_BIOMETRIC` (ilova e'lon qilgan) + `USE_FINGERPRINT`, `ACCESS_NETWORK_STATE`, `…DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` (plagin AAR'laridan). Boshqasi bo'lsa — regressiya. | |
| A26 | `POST_NOTIFICATIONS` bormi? | **Yo'q.** Push ulanmagan. | |

### A.5 Qulf, xavfsizlik, ekran

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A27 | PIN o'rnatish, ilovani fonga olib uzoq qoldirib qaytish | PIN so'raladi | |
| A28 | Barmoq izi yoqilgan telefonda biometrik kirish | Ishlaydi; biometrik yo'q telefonda tugma umuman ko'rinmaydi | |
| A29 | Login / PIN ekranida skrinshot olishga urinish | Android bloklaydi (FLAG_SECURE); «so'nggi ilovalar» da ham ko'rinmaydi | |
| A30 | Hisobot/chek ekranida skrinshot | **Ishlaydi** (ataylab — foydalanuvchi ulashsin) | |
| A31 | Telefonni yangi telefonga «transfer» qilish / bulut zaxirasi | Ilova ma'lumoti ko'chmaydi (`allowBackup=false`) | |

### A.6 targetSdk 36 (Android 15/16) — hech kim tekshirmagan sinf

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A32 | Android 15/16 telefonda har ekranni ko'rib chiqish | Edge-to-edge majburiy: status bar / home indicator ostida matn yoki tugma **qolib ketmaydi** | |
| A33 | Har ekranda «predictive back» (orqaga surish) | Kutilgan ekranga qaytadi, ilova yopilib ketmaydi | |
| A34 | Sariq STAGING chizig'i status bar bilan to'qnashmaydi | Chiziq status bar ostida, matn kesilmaydi | |
| A35 | Klaviatura ochilganda forma maydonlari | `adjustResize` — maydon klaviatura ostida qolmaydi | |

### A.7 Biznes oqimlari (E2E ro'yxatining qurilmadagi takrori)

Avtomatik E2E (`e2e/mobile/run_e2e.py`) **fake backend/server bilan, kompyuterda** ishlaydi.
Quyidagilar o'sha oqimlarning **haqiqiy telefon + staging server** dagi takrori.

| # | Oqim | Kutilgan natija | Dalil |
|---|---|---|---|
| A36 | 0. Kirish (telefon + parol), `/auth/context` | Rol, kompaniya, filial to'g'ri | |
| A37 | 1. Shtrix-kod → mahsulot (`/products/scan`) | Mahsulot topiladi, qoldiq shu filialga tegishli | |
| A38 | 1b. **Tarozi yorlig'i (weighed EAN-13)** ni skanerlash | PLU va og'irlik to'g'ri o'qiladi, summa butun so'mga yaxlitlanadi | |
| A39 | 2/3/7. Tovar qabul: partiyali, muddatli, kassa hisobi bilan | Hujjat yaratiladi, ikki marta bosishda dublikat yaratilmaydi | |
| A40 | 4. Inventarizatsiya (partiya bo'yicha) | Sanash yopiladi, farq to'g'ri | |
| A41 | 5. Hisobdan chiqarish (partiya bo'yicha, FEFO) | To'g'ri partiyadan yechiladi | |
| A42 | 6. Qabulni tuzatish (kassa hujjati bilan) | Teskari + almashtiruvchi hujjat, pul ikki bazada to'g'ri | |
| A43 | 8. Mijoz qarzini to'lash | Qarz kamayadi, kassa yozuvi bor | |
| A44 | 9. Filial izolyatsiyasi: A filialga kirib B ni so'rash | 403 / ko'rinmaydi; hisobotlar ham boshqa filialni ko'rsatmaydi | |
| A45 | 10. Ruxsat manfiy: cheklangan rol bilan taqiqlangan amal | Tugma o'chiq + sabab; server ham rad etadi | |
| A46 | Aloqa uzilishi: Wi-Fi/mobil internetni o'chirib amal qilish | «Server bilan aloqa yo'q» banneri; **yozuv navbatga olinmaydi va «bajarildi» deyilmaydi** | |
| A47 | 5F chek: sotuvni ochib chekni ko'rish/chop etish/ulashish | Chek serverdan keladi, 58/80 mm formati to'g'ri | |
| A48 | Hisobot CSV eksporti va ulashish | Fayl yaratiladi, ulashish menyusi ochiladi | |
| A49 | Filialni almashtirish | Har filialga bog'liq tab qaytadan yuklanadi, eski filial raqamlari ekranda qolmaydi | |
| A50 | 4 til (uz / uzc / ru / ky) ni almashtirish | Butun UI tarjima bo'ladi, raqam/sana formati tilga mos | |

### A.8 Unumdorlik (haqiqiy katalog: 7137 mahsulot / 12603 shtrix-kod)

Har o'lchov **release** buildda, telefon sovuq holatda. Vaqtni sekundomer yoki
`adb shell am start -W` bilan yozing.

| # | O'lchov | Maqsad | Dalil (aniq ms) |
|---|---|---|---|
| A51 | Sovuq start (birinchi kadrgacha) | < 3 s | |
| A52 | Kirish → Bosh ekran to'liq | < 5 s | |
| A53 | Mahsulot qidiruvi (3 harf terilgach natija) | < 1.5 s | |
| A54 | Shtrix-kod: skanerdan natijagacha | < 2 s | |
| A55 | Filial almashtirish → tab qayta yuklandi | < 3 s | |
| A56 | Ombor ro'yxatini oxirigacha aylantirish (paging) | Dublikat qator yo'q, «yana yuklash» bir joyda to'xtaydi | |
| A57 | 30 daqiqalik uzluksiz ish | Ilova o'lmaydi, xotira o'smaydi (`adb shell dumpsys meminfo`) | |

### A.9 Yangilanish yo'li (pilotning eng og'riqli joyi)

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| A58 | `0.7.0+56` o'rnatilgan telefonga `0.7.0+57` ni `adb install -r` bilan tushirish | Yangilanadi, login va lokal holat saqlanadi | |
| A59 | Sozlamalardagi versiya qatori | `v0.7.0+57` | |
| A60 | Bir xil `versionCode` li ikkinchi APK ni o'rnatish | Android rad etadi — shuning uchun har build yangi raqam oladi | |
| A61 | Debug-imzoli build ustiga to'g'ri imzolangani | `INSTALL_FAILED_UPDATE_INCOMPATIBLE` — **shuning uchun pilotga debug-imzoli build berilmaydi** | |

---

## B. IPHONE — PWA (Safari + «Bosh ekranga qo'shish»)

> **Holat.** PWA target (`apps/mobile/web/`) Phase 5G.1 da alohida paket tomonidan yaratilmoqda —
> bu ro'yxatni yozgan paket (C2, Android) uning holatini tasdiqlamaydi. Quyidagi qismni faqat
> web build staging'da **HTTPS** orqali va **aniq SHA ga bog'langan** holda xizmat qilinganidan
> keyin bajarish mumkin. Native iOS ilova bu bosqichda **umuman yo'q**: Apple sertifikati,
> imzo, do'kon hisobi — hech biri qilinmagan va qilinmaydi.
>
> **Til qoidasi:** PWA da **Face ID yo'q** (`local_auth` ning web implementatsiyasi yo'q).
> Hech qanday PWA matnida, hujjatida yoki bu ro'yxatda «Face ID» deb yozilmaydi — faqat
> PIN + sessiya muddati qulfi.

| # | Qadam | Kutilgan natija | Dalil |
|---|---|---|---|
| B1 | Staging PWA ni **HTTPS** orqali ochish; `window.isSecureContext` | `true`. HTTPS majburiy: `getUserMedia`, service worker, `navigator.share`, `crypto.subtle` busiz ishlamaydi | |
| B2 | Safari → Ulashish → «Bosh ekranga qo'shish» | Ikonka BINOS brendi bilan, nomi to'g'ri (Flutter shabloni «A new Flutter project» emas) | |
| B3 | Bosh ekrandan ochish (standalone) | Brauzer paneli yo'q, ilovadek ochiladi | |
| B4 | **Standalone rejimda** shtrix-kod skaneri | iOS 16.4+ da kamera ishlaydi. Eski iOS da `NotAllowedError` — **shuning uchun pilot uchun eng past iOS versiyasini aniq yozing** | |
| B5 | Kamerani rad etib, keyin qayta urinish | Tushunarli xabar + «Kodni qo'lda kiritish». **«Sozlamalarni ochish» tugmasi BO'LMAYDI** — Safari'da bunday deep link yo'q; matn foydalanuvchiga qayerdan yoqishni **so'z bilan** aytadi | |
| B6 | Skaner ekranidagi chiroq (torch) tugmasi | **Ko'rinmaydi** (WebKit torch bermaydi) — o'lik tugma qoldirilmaydi | |
| B7 | Tarozi yorlig'i (weighed EAN-13) ni Safari'da skanerlash | Android bilan bir xil natija (bir xil `/products/scan` kontrakti) | |
| B8 | Skaner ochilganda tarmoq so'rovlari | zxing kutubxonasi `unpkg.com` dan tortiladimi? (hozir shunday — SRI yo'q, pin yo'q). Do'kon tarmog'ida bloklansa skaner ishlamaydi | |
| B9 | Sovuq yuklash paytida tarmoq | CanvasKit (`canvaskit.wasm`, ≈7.2 MB / 2.9 MB gz) va shriftlar `gstatic.com` dan keladimi — o'lchang | |
| B10 | Kirish → token qayerda saqlanadi (`localStorage` ni brauzer konsolidan ko'rish) | Token XSS uchun o'qilishi mumkinligini **tan oling**; PWA uchun sessiya-doirasidagi saqlash qarori bajarilgan bo'lsin | |
| B11 | Ilovani yopib, qayta ochish | Sessiya siyosati qanday belgilangan bo'lsa shunday (avtomatik chiqish yoki qayta kirish) — «esda qoldi» deb yolg'on ko'rsatilmaydi | |
| B12 | Chiqish (logout) | Token, keshlar va service worker keshi tozalanadi. **Bir telefonni ikki xodim ishlatsa** — A ning ma'lumoti B ga ko'rinmaydi | |
| B13 | Service worker: yangi SHA chiqarilgandan keyin PWA ni qayta ochish | Yangi bundle keladi, eski «qotib qolgan» ekran chiqmaydi; kesh SHA bo'yicha versiyalangan | |
| B14 | DevTools/Network: `/api/v1/**` so'rovlari | **Hech qachon keshlanmaydi** (network-first / no-store). Faqat statik assetlar keshlanadi | |
| B15 | Internetni o'chirib ilovani ishlatish | «Oflayn» aniq ko'rsatiladi. **Hech qanday yozuv navbatga olinmaydi va «bajarildi» deyilmaydi** — bu avariya-POS emas | |
| B16 | 7 kun ishlatmay qo'yib, qaytib ochish (tabda) | Safari script-storage ni o'chirishi mumkin → qayta kirish talab qilinadi, ma'lumot yo'qolmaydi (hammasi serverda). Bosh ekranga qo'shilgan ilova bu tozalashdan ozod | |
| B17 | Hisobot CSV eksporti | Fayl yuklab olinadi yoki ulashiladi; `navigator.canShare({files})` rad etsa — **yuklab olishga tushadi**, xom `Exception('Navigator.canShare() is false')` matni foydalanuvchiga **chiqmaydi** | |
| B18 | Chekni PDF qilib chop etish/ulashish (standalone rejimda) | Chop etish oynasi ochiladi yoki PDF yangi tabda; blob-download standalone'da ishlamasa — zaxira yo'l bor | |
| B19 | Nakladnoy rasmini yuklash (kamera / Photos) | Rasm HEIC bo'lsa ham qabul qilinadi; **to'liq o'lchamdagi rasm yuborilmaydi** (Dart tomonda kichraytirish) — 413 xatosi bo'lmaydi | |
| B20 | Notch'li telefonda safe area | Status bar va home indicator matnni bosmaydi (`viewport-fit=cover` + `SafeArea`) | |
| B21 | 390×844 va undan kichik/katta iPhone o'lchamlari | Gorizontal scroll yo'q, tugmalar 48 dp dan kichik emas | |
| B22 | Xato xabarlari (masalan taqiqlangan amal) | Android bilan **bir xil matn**. Eslatma: `X-Error-Code` sarlavhasi staging'da ochilgan, **production `99b1da7` da ochilmagan** — eski serverga qarshi PWA kodlarni o'qiy olmaydi, shuning uchun mos kelmaydigan server bloklanishi kerak | |
| B23 | `/products` ro'yxatini oxirigacha aylantirish | Dublikat qator yo'q, «yana yuklash» to'xtaydi. Eski serverda paging buziladi (`X-Total-Count` yo'q) — gate bu oqimni bloklasin | |
| B24 | Skrinshot olish | **Bloklanmaydi** — web'da FLAG_SECURE ekvivalenti yo'q. Buni pilot hujjatida ochiq yozing | |
| B25 | Ilova «his»i: scroll fizikasi, orqaga surish | `defaultTargetPlatform` Safari'da `iOS` bo'ladi — Android buildidan farq qiladi. Ataylab qabul qilingan qaror bo'lsin | |
| B26 | Unumdorlik (7137 mahsulot): sovuq start, kirish, qidiruv, skaner, filial almashtirish, keshlangan qayta yuklash | Aniq ms bilan yozing (A.8 bilan taqqoslash uchun) | |

---

## 2. Pilotni to'xtatuvchi (STOP) shartlar

Quyidagilardan bittasi ro'y bersa — pilot to'xtaydi, yangi build chiqmaydi:

1. STAGING chizig'i ko'rinmasa yoki production buildda ko'rinsa.
2. Ilova staging emas, **production** serveriga yozsa.
3. Kamera butunlay rad etilganda qo'lda kiritish ham ishlamasa.
4. Aloqa yo'qligida amal «bajarildi» deb ko'rsatilsa (yozuv aslida ketmagan bo'lsa).
5. Bir filialning ma'lumoti boshqa filial ostida ko'rinsa.
6. Yangilanish `INSTALL_FAILED_UPDATE_INCOMPATIBLE` bersa (imzo aralashgan).
7. PWA da chiqishdan keyin oldingi xodim ma'lumoti keshdan ko'rinsa.

---

## 3. Ro'yxatni to'ldirish qoidasi

Har «Dalil» katagiga: `YYYY-MM-DD · qurilma modeli · OS versiyasi · natija · skrinshot/log yo'li`.

Masalan:
`2026-10-02 · Redmi Note 12 · Android 14 · PASS · pilot/A19-settings-deeplink.png`

Bajarilmagan qadam **bo'sh** qoladi. «Tekshirilmadi» ham PASS emas.
Bo'lim to'liq to'ldirilmaguncha o'sha bo'lim uchun «VERIFIED» so'zi ishlatilmaydi.

---

## 4. Ochiq xavflar (5G.1 da yopilmagan — pilotdan oldin qaror kerak)

| # | Xavf | Ta'sir |
|---|---|---|
| 1 | **Keystore zaxirasi yo'q/noma'lum** | Kalit yo'qolsa — o'rnatilgan APK boshqa yangilanmaydi | 
| 2 | **Staging va production bitta `applicationId`** | Bitta telefonda ikkalasi tura olmaydi; almashtirish = qayta o'rnatish | 
| 3 | **Server maydoni rol bilan cheklanmagan** | Har qanday xodim ilovani boshqa serverga qaratishi mumkin; saqlangan `base_url` build standartidan ustun | 
| 4 | **Brend nomi hal qilinmagan** | Hujjatlarda BINOS, ilovada SavdoOS. `applicationId` birinchi o'rnatishdan keyin **o'zgarmaydi** — pilotdan **oldin** hal qiling | 
| 5 | **CI da Android release build yo'q** | `flutter build apk --release` hech qachon CI da yashil bo'lmagan; faqat qo'lda tekshirilgan | 
| 6 | **Dart obfuskatsiya / `--split-debug-info` yo'q** | Kelajakdagi crash-report'lar simvollanmaydi; Play uchun kerak bo'ladi | 
| 7 | **APK ≈75 MB (uchala ABI bitta faylda)** | `--split-per-abi` yoki App Bundle hajmni ≈3 barobar kamaytiradi | 
| 8 | **PWA hali staging'da HTTPS orqali xizmat qilinmagan** | B bo'limining birorta qatori hozir bajarib bo'lmaydi | 
| 9 | **Eski production server (`99b1da7`) mos emas** | Yangi klient eski serverga qarshi xavfli yozishi yoki xato matnini noto'g'ri ko'rsatishi mumkin — mos kelish darvozasi kerak | 
| 10 | **STAGING chizig'i login va PIN ekranlarida yo'q** | Ular `main.dart` da qobiqdan tashqarida. Tuzatish bir qator: `main.dart` dagi `builder:` ichida `EnvBadge.wrap(context, …)` (production'da u bolani o'zgarishsiz qaytaradi). `main.dart` C2 paketining egaligiga kirmaydi — yadro egasidan so'ralgan | 
