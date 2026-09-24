# SavdoOS Mobil (Flutter)

Do'kon **egasi** uchun mobil ilova — Android (va iOS). Ikki asosiy vazifa:

1. **Analitika** — savdo, yalpi foyda, cheklar, dinamika, to'lov usullari, top mahsulotlar,
   kassirlar (BILLZ mobil uslubida, sodda). Ma'lumot backend `/reports/overview` dan.
2. **Tovar qabul qilish** — kuryer keltirgan nakladnoyni **kameraga olib** yoki **galereyadan**
   yuklab, AI mahsulot nomi + miqdorini avtomatik o'qiydi → do'konchi tekshiradi/tahrirlaydi →
   **tasdiqlagach** omborga kirim bo'ladi. AI hech qachon o'zi tasdiqlamaydi.

Desktop ilovalar (POS/Manager) bilan **bir xil backend** va bir xil dizayn tili (dark + binafsha #6D5DD3).

---

## Papka tuzilishi

```
apps/mobile/
  pubspec.yaml
  analysis_options.yaml
  lib/
    main.dart               # kirish nuqtasi (login yoki Shell)
    theme.dart              # dizayn tokenlari + AppCard
    api.dart                # backend klient (Railway) + modellar
    format.dart             # pul/son/sana formatlari
    screens/
      login_screen.dart     # PIN-kod
      shell.dart            # pastki navigatsiya (Analitika/Qabul/Sozlamalar)
      analytics_screen.dart # analitika dashboard
      receiving_home_screen.dart    # kamera/galereya + qabullar tarixi
      receiving_review_screen.dart  # AI natijasini tekshirish/tahrirlash
      receiving_success_screen.dart # muvaffaqiyat + eski→yangi qoldiq
      receiving_detail_screen.dart  # tarixdagi qabul tafsiloti (rasm bilan)
      settings_screen.dart  # server manzili + chiqish
```

> **DIQQAT:** Bu papkada hali `android/`, `ios/` platforma papkalari **yo'q** — ular
> `flutter create` bilan generatsiya qilinadi (pastga qarang). Faqat Dart kodi + pubspec bor.

---

## 1-qadam — Flutter o'rnatish (kompyuterda)

Bu loyihani yig'ish uchun kompyuterda **Flutter SDK** kerak (hozir bu mashinada yo'q):

- https://docs.flutter.dev/get-started/install → OS'ingizni tanlang.
- O'rnatgach tekshiring:
  ```bash
  flutter --version
  flutter doctor
  ```
- Android APK yig'ish uchun **Android Studio** (SDK + build-tools) ham kerak. `flutter doctor`
  qizil belgilarni ko'rsatadi — o'shalarni bartaraf qiling (odatda: Android SDK, litsenziya
  `flutter doctor --android-licenses`).

## 2-qadam — Platforma papkalarini generatsiya qilish

`apps/mobile` ichida (bizning `lib/` va `pubspec.yaml` allaqachon bor):

```bash
cd apps/mobile
flutter create --org com.savdoos --project-name savdoos_mobile --platforms=android,ios .
```

- Bu buyruq **mavjud fayllarni o'chirmaydi** — faqat yetishmayotgan `android/`, `ios/`
  papkalarini qo'shadi. Agar u xatosidan `pubspec.yaml` yoki `lib/` ni o'zgartirib yuborsa,
  git orqali qaytaring: `git checkout apps/mobile/pubspec.yaml apps/mobile/lib`.

Paketlarni yuklang:
```bash
flutter pub get
```

## 3-qadam — Ruxsatlar (image_picker uchun)

**Android:** odatda qo'shimcha ruxsat **shart emas** — galereya tizim Photo Picker orqali,
kamera esa tizim kamera ilovasi (intent) orqali ochiladi. Agar kamerada muammo bo'lsa,
`android/app/src/main/AndroidManifest.xml` ga `<application>` dan tashqarida qo'shing:
```xml
<uses-permission android:name="android.permission.CAMERA"/>
```

**iOS:** `ios/Runner/Info.plist` ga qo'shing (aks holda kamera/galereya ochilganda ilova yiqiladi):
```xml
<key>NSCameraUsageDescription</key>
<string>Nakladnoyni suratga olish uchun kamera kerak.</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Nakladnoy rasmini tanlash uchun galereya kerak.</string>
```

## 4-qadam — Ishga tushirish / yig'ish

Telefonni ulab (USB debugging yoqilgan) yoki emulyatorda:
```bash
flutter run
```

Relase APK (odamларга tarqatish uchun) yig'ish:
```bash
flutter build apk --release
# natija: build/app/outputs/flutter-apk/app-release.apk
```
Bu `.apk` faylni telefonga tashlab o'rnatish mumkin (Google Play talab qilmaydi).

> **Play Store uchun** (ixtiyoriy): `flutter build appbundle --release` → `.aab`.

### Flutter kompyuterda yo'q bo'lsa — bulutda yig'ish

Agar Flutter o'rnatishni istamasangiz, APK'ni **bulutда** yig'ish mumkin:

- **Codemagic** (codemagic.io) — Flutter uchun eng oson. GitHub repo'ни ulaysiz, `apps/mobile`
  ni project root qilib ko'rsatasiz, "Build APK" bosasiz. Bepul limit bor.
- **GitHub Actions** — `.github/workflows/mobile.yml` da `subosito/flutter-action` bilan
  `flutter build apk`. APK'ni artifact sifatida yuklab olasiz.

---

## Kirish (login)

Ilova birinchi ochilganda PIN so'raydi. Demo: **Administrator — 1234**, **Kassir — 1111**.
Server manzili **Sozlamalar**da o'zgaradi (odatda Railway: `https://savdoos-production.up.railway.app`).

Tovar qabul qilish `xaridlar.edit` ruxsatini talab qiladi — shунинг uchun **Administrator**
(yoki shu ruxsatli rol) bilan kiring.

---

## 🤖 AI (nakladnoy o'qish) — sozlash yo'riqnomasi

Backend'da **Anthropic (Claude) API kaliti** bo'lmasa, `/receiving/scan` **demo rejimda**
ishlaydi: birinchi bir necha mahsulotni namuna sifatida qaytaradi (ilova to'liq test qilinadi,
lekin rasm haqiqatan o'qilmaydi — kartochkada **DEMO** yozuvi chiqadi). Haqiqiy o'qish uchun:

### 1) Anthropic API kalitini oling
1. https://console.anthropic.com → ro'yxatdan o'ting / kiring.
2. **Billing** (Plans & Billing) → karta qo'shib, biroz balans to'ldiring (masalan $5–10).
3. **API keys** → **Create Key** → nusxa oling (`sk-ant-...`). **Kalitni sir saqlang**,
   git'ga commit qilmang.

### 2) Railway'da o'rnating
1. Railway → loyiha **trustworthy-enchantment** → servis **savdoos** → **Variables**.
2. Yangi o'zgaruvchi qo'shing:
   ```
   ANTHROPIC_API_KEY = sk-ant-...
   ```
3. (ixtiyoriy) Arzonroq/tez model tanlash — standart `claude-opus-5`:
   ```
   AI_MODEL = claude-sonnet-5      # yoki claude-haiku-4-5 (eng arzon)
   ```
4. **Deploy** (Railway avtomatik qayta deploy qiladi). Tayyor — endi skan haqiqiy AI bilan
   o'qiydi, `source` "demo" emas "ai" bo'ladi.

### 3) Tekshirish
- Ilovada "Qabul qilish" → nakladnoyни suratга oling. Kartochkalarda **DEMO** yozuvi
  yo'qolsa — AI ishlayapti.
- Yoki mahalliy: `apps/server/.env` ga `ANTHROPIC_API_KEY=...` qo'shib `uvicorn` ishga tushiring.

### Xarajat haqida
Har skan ~1 ta rasm + qisqa javob. `claude-haiku-4-5` eng arzon, `claude-opus-5` eng aniq.
Do'kon kuniga bir necha marta qabul qilsa — xarajat juda kichik. Balansни Anthropic konsolида
kuzatib turing.

### Xavfsizlik prinsipi
AI natijasi **faqat taklif**. Ombor **hech qachon** avtomatik o'zgarmaydi — faqat do'konchi
"Omborga qo'shish" ni bosгандан keyin. Har qabul audit uchun saqlanadi: asl rasm + AI
dastlabki o'qishi + do'konchi tahrirlagan yakuniy ro'yxat (`receivings` jadvali).
AI **yangi mahsulot yaratmaydi** — faqat mavjudlari bilan moslashtiradi; topilmagani
"Mahsulot aniq topilmadi" bo'lib, do'konchi qo'lда tanlaydi.

---

## Backend endpoint'lari (mos)

| Metod | Yo'l | Vazifa |
|------|------|--------|
| POST | `/api/v1/auth/login` | PIN bilan kirish |
| GET  | `/api/v1/reports/overview?period=day\|week\|month` | analitika |
| GET  | `/api/v1/products` | mahsulotlar (moslash uchun) |
| POST | `/api/v1/receiving/scan` | rasm → AI o'qish (ombor o'zgarmaydi) |
| POST | `/api/v1/receiving/commit` | tasdiqlangan ro'yxatни omborга kirim |
| GET  | `/api/v1/receiving` | qabullar tarixi |
| GET  | `/api/v1/receiving/{id}` | qabul tafsiloti (rasm bilan) |

---

## PWA (iPhone uchun ko'prik) — Phase 5G.1

iPhone uchun **native ilova emas**, balki Flutter Web'dan yig'ilgan **PWA**: Safari'da ochiladi,
"Add to Home Screen" bilan o'rnatiladi va alohida ilova sifatida ishga tushadi. Apple imzosi,
sertifikat yoki App Store hisobi **kerak emas**.

### Papka

```
apps/mobile/web/
  index.html              # brend + iOS meta teglari + CSP (inline script YO'Q)
  flutter_bootstrap.js    # engine yuklash shabloni (Flutter'ning SW'siz — pastga qarang)
  pwa.js                  # splash, til, service worker ro'yxatga olish + yangilanish banneri
  sw.js                   # keshlash siyosati (pastga qarang)
  manifest.json           # nomi SavdoOS, standalone, portrait, #5A4BC4
  favicon.png
  icons/                  # 192/512 (any) + 192/512 (maskable) + apple-touch-icon-180
  vendor/zxing/           # barkod kutubxonasi (o'zimizda, CDN'dan emas) + provenance.json
```

`web/` **qo'lda yozilgan**. `flutter create --platforms=web .` ishlatilmadi, chunki u
`.metadata` dan `ios` yozuvini o'chiradi va `pubspec.lock` ni qayta yozadi (20 ta transitiv
versiya + CRLF→LF), CI esa `pub get --enforce-lockfile` bilan ishlaydi. Ikkala fayl ham
**o'zgarmagan** (`test/pwa_manifest_test.dart` buni tekshiradi).

Ikonkalarni qayta yaratish: `apps/server/.venv/Scripts/python scripts/pwa_icons.py`
(manba — Android launcher ikonkasi bilan **bir xil**: `assets/icon/icon.png`, `icon_fg.png`).

### Yig'ish

```bash
cd apps/mobile
flutter build web --release --no-web-resources-cdn --pwa-strategy=none \
  --dart-define=BINOS_API_BASE=https://<server> --dart-define=BINOS_ENV=staging
cd ../.. && node scripts/pwa_postbuild.mjs        # MAJBURIY
```

`--pwa-strategy=none` — **majburiy** (sababi pastda, "Bitta service worker").
Unutilsa `pwa_postbuild.mjs` build'ni yiqitadi.

`scripts/pwa_postbuild.mjs`:
* `sw.js` dagi `__BINOS_BUILD_ID__` o'rniga **build hash** yozadi (har build uchun boshqa
  token, bir xil build uchun bir xil token);
* boot yo'lida (`index.html`, `flutter_bootstrap.js`, `flutter.js`, `pwa.js`, `sw.js`,
  `manifest.json`) CDN manzili yo'qligini, `useLocalCanvasKit: true` ekanini, `.map` fayl
  yo'qligini va ZXing joyida ekanini tekshiradi;
* **service worker bitta** ekanini tekshiradi: `flutter_bootstrap.js` da
  `serviceWorkerSettings` bo'lmasligi va build'da `flutter_service_worker.js`
  **chiqmasligi** kerak (sababi pastda);
* qaysi shrift manbasi ishlatilayotganini yozib beradi (`font fallback base`);
* hajmni (raw + gzip) o'lchaydi.

**Bu qadam unutilsa** — service worker `INERT` rejimда ishlaydi: hech narsa keshlamaydi va
hech narsani ushlamaydi. Ya'ni offline shell yo'qoladi, lekin **eski build hech qachon
ko'rsatilmaydi**.

Service worker xatti-harakatini node'da haqiqiy `sw.js` ustida tekshirish:
`node scripts/pwa_sw_selftest.mjs` (27 ta tekshiruv).

### Keshlash siyosati (`web/sw.js`)

| Nima | Qanday |
|---|---|
| `/api/**`, boshqa origin, GET bo'lmagan so'rov, `Authorization` bor so'rov | **umuman ushlanmaydi** — brauzer o'zi bajaradi, keshга tushmaydi |
| navigatsiya, `index.html`, `flutter_bootstrap.js`, `flutter.js`, `main.dart.js` | network-first (offline'da keshdan) |
| qolgan statik fayllar | keshdan + fonda yangilanadi |
| kesh nomi | `binos-shell-<buildId>`; `activate` boshqa har qanday buildning keshini o'chiradi |
| yozuvlar (POST/PUT/…) | **hech qachon navbatga qo'yilmaydi**. Bu favqulodda POS emas |

Yangilanish: yangi versiya o'rnatilgach **banner** chiqadi ("Yangi versiya tayyor" →
"Yangilash"). Operator bosmaguncha bundle almashmaydi (hujjat to'ldirayotganda almashib
ketmasligi uchun).

### Bitta service worker (`web/flutter_bootstrap.js`)

`flutter build web` `flutter_bootstrap.js` ni **shablon**dan yasaydi. Standart shablon
(flutter_tools `lib/src/web/bootstrap.dart`) `_flutter.loader.load({serviceWorkerSettings:
{serviceWorkerVersion: …}})` deb chaqiradi, `flutter.js` esa (shu build'dagi minified kod):

```js
return e.serviceWorkerUrl != null
    ? (warn(), t())                                   // t() = register('flutter_service_worker.js?v=…')
    : navigator.serviceWorker.getRegistration().then(r => r ? t() : Promise.resolve());
```

Ya'ni URL berilmasa ham, **registratsiya allaqachon bo'lsa** Flutter o'z worker'ini
ro'yxatga oladi. Bizda esa ikkinchi kirishdanoq `pwa.js` yozgan `sw.js` bor va scope bir xil
(`/`) — demak Flutter'ning script'i **bizникini almashtiradi**. Flutter 3.44 dagi worker esa
o'zini o'chiradigan stub (815 bayt: `skipWaiting`, keyin `unregister` + barcha client'ni
qayta yuklash). Natija: qaytib kirganда offline shell yo'qoladi va sahifa **majburan**
qayta yuklanadi — operator hujjat to'ldirayotgan bo'lsa ham.

Shuning uchun `web/flutter_bootstrap.js` **repoda** turadi va faqat
`_flutter.loader.load();` deydi (`{{flutter_js}}` va `{{flutter_build_config}}` token'lari
toolchain'dan keladi, `useLocalCanvasKit` ham shu yerda). Build esa `--pwa-strategy=none`
bilan qilinadi, shunda stub umuman chiqmaydi. Ikkalasini ham `pwa_postbuild.mjs`
**artefakt ustida** tekshiradi; Dart testi: `test/pwa_bootstrap_test.dart`.

### Token saqlash (web siyosati)

Web'da token **`sessionStorage`** da (`lib/platform/secret_store_web_policy.dart`).
Ilovani yopsangiz — sessiya tugaydi, qaytadan kirish kerak. Buni operator har ishga
tushganда splash'da o'qiydi.

Sabab: `flutter_secure_storage_web` AES kalitini `localStorage` ga **ochiq** yozadi
(shifrlangan qiymat yonida), ya'ni web'da u xavfsizlik chegarasi emas — audit tokenni
konsoldан 6 qatorда ochган. Undan ham muhimi: u tokenni **doimiy** qiladi, umumiy do'kon
telefonida esa bu "keyingi odam oldingi xodim sifatida kiradi" degani. Sessiya doirasi
shuni yo'q qiladi. XSS'ni esa hech bir brauzer saqlashi yo'q qilolmaydi — shuning uchun
`index.html` da qattiq CSP, inline script yo'q, uchinchi tomon script'i yo'q.

Eski siyosat qoldirган `FlutterSecureStorage*` va `flutter.token` / `flutter.employee`
kalitlari ishга tushishда `localStorage` dан **o'chiriladi**; sozlamalar (server manzili,
til, mavzu, filial) tegilmaydi.

### Barkod (ZXing)

`mobile_scanner 5.2.3` web'da birinchi skanда `https://unpkg.com/@zxing/library@0.19.1`
ni `<script>` sifatida yuklaydi (SRI yo'q, pin yo'q, offline'da ishlamaydi). Buning o'rniga
**xuddi shu artefakt** `web/vendor/zxing/` ga qo'yilgan va `index.html` uni plagin qidiradigan
`id="mobile-scanner-barcode-reader"` bilan oldindan yuklaydi — shuning uchun plagin o'z
script'ini **hech qachon** qo'shmaydi. Hash pin: `web/vendor/zxing/provenance.json`.

### Shriftlar — ochiq kamchilik (o'lchangan)

`--no-web-resources-cdn` **CanvasKit engine**'ni o'zimizda joylaydi (tekshirildi:
`canvaskit/chromium/canvaskit.{js,wasm}` o'z origin'imizdan), lekin **shriftlarni emas**.
CanvasKit hali ham Google CDN'dan yuklaydi:

```
uz (lotin)      https://fonts.gstatic.com/s/roboto/v32/KFOmCnqEu92Fr1Me4GZLCzYlKw.woff2
uzc/ru/ky       + https://fonts.gstatic.com/s/notosanssc/v37/k3kCo84MPvpLmixcA63oeAL7Iqp5IZJF9bmaG9_FrY9HbczS.woff2
belgilar        + https://fonts.gstatic.com/s/notosanssymbols/v43/rP2up3q65FkAtHfwd-eIS2brbDN6gxP34F9jRRCe4W3gfQ8gb_VFRkzrbQ.woff2
```

Bu **yagona** qolgan uchinchi tomon so'rovi. Bu script emas, shrift — kod bajarilmaydi,
ammo offline va maxfiylik nuqtai nazarida muammo.

**Richag bor, lekin shriftning o'zi yo'q.** `window.flutterConfiguration.fontFallbackBaseUrl`
ishlamaydi (o'lchangan) — chunki `_flutter.loader.load({config})` dagi config eski global'ni
bosib ketadi. Ammo o'sha config'ning O'ZI ishlaydi: engine uni shunday o'qiydi —
`engine/configuration.dart:358` (`_configuration?.fontFallbackBaseUrl ?? 'https://fonts.gstatic.com/s/'`),
standart Roboto manzili `engine/canvaskit/fonts.dart:14`, fallback'lar
`engine/font_fallbacks.dart:460`. Endi bizda o'z `web/flutter_bootstrap.js` bor, ya'ni
`_flutter.loader.load({config: {fontFallbackBaseUrl: "fonts/"}})` deb yozish bir qator ish.

**Shunga qaramay yoqilmadi** — qoplama yetmaydi. Pinlangan toolchain'da qayta tarqatsa
bo'ladigan yagona shrift — `bin/cache/artifacts/material_fonts/roboto-regular.ttf`
(Apache-2.0, 171 676 bayt, 896 kod nuqtasi: lotin + lotin-ext-A to'liq, **kirill 255/256**,
grek 75/144). Ilovaning `lib/` dagi matnlarida 200 xil kod nuqtasi bor, shundan **10 tasi**
bu shriftda yo'q. Oltitasi faqat **izoh yoki regexda** (`─ ═ ʻ` va tor probel) — ekranga
chiqmaydi. To'rttasi esa chiqadi:

| Belgi | Nechta | Qayerda |
|---|---|---|
| `→` | 47 | `l10n.dart` — `'Barchasi →'` va boshqalar |
| `✓` | 28 | `l10n.dart` — `'Saqlandi ✓'`, `'Chiqarildi ✓'` |
| `👍` | 8 | `l10n.dart` — `'Qarz yo‘q 👍'`, `'Bildirishnoma yo‘q 👍'` |
| `📊` | 1 | `report_export.dart` — eksport sarlavhasi |

Bugun ular Noto orqali CDN'dan keladi. Bazani o'z origin'imizga burasak va o'sha Noto'lar
bizda bo'lmasa — ular **kvadratchaga** aylanadi. Ya'ni "CDN yo'q" uchun ko'rinadigan UI
buziladi; bu savdo qilmaydigan savdo.

To'g'ri yechim o'zgarmaydi: `pubspec.yaml` ga **bitta** shriftni asset sifatida qo'shib
`lib/theme.dart` da standart qilish (lotin + kirill + `→ ✓` qoplamasi bilan). Bu C1
paketining egaligidan tashqarida. Shu bo'lguncha baza gstatic'da qoladi va
`pwa_postbuild.mjs` har buildda uni `font fallback base` qatorida **ochiq yozadi**.

### Brauzerda o'lchangan (2026-09-24, Chromium-asosli panel, 375×812)

`build/web` `python -m http.server 8899 --bind 127.0.0.1` bilan berildi
(`--dart-define=BINOS_API_BASE=https://api.invalid`, ya'ni server yo'q):

* **Ilova yuklanadi**: `document.title = "SavdoOS"`, splash `flutter-first-frame` da
  olib tashlandi, ekranda **login** (SavdoOS sarlavhasi, `+996` maydoni, "Parol", "Kirish").
* **Boot'da 11 ta so'rov**, shundan **o'z origin'imizdan 10 tasi**
  (`flutter_bootstrap.js`, `main.dart.js`, `canvaskit/chromium/canvaskit.{js,wasm}`,
  `pwa.js`, `vendor/zxing/…`, `assets/…`). CanvasKit CDN'dan **kelmadi**
  (`_flutter.buildConfig.useLocalCanvasKit = true`).
* **Begona so'rovlar — faqat shrift**: standart (uz) tilда **bitta**
  (`fonts.gstatic.com/s/roboto/v32/…woff2`); til `ru` ga qo'yilganda **ikkita**
  (kirill uchun yana `…/notosanssc/v37/…woff2`) — ya'ni kirill tenant (Fayzan) har
  sessiyada CDN'ga ko'proq murojaat qiladi. `unpkg.com` ga **bitta ham** so'rov yo'q.
* **Eski kalitlar tozalanishi** (haqiqiy brauzerda): `localStorage` ga
  `FlutterSecureStorage`, `FlutterSecureStorage.token`, `FlutterSecureStorage.pin_hash`,
  `flutter.token` qo'yib qayta yuklandi → to'rttasi ham **o'chdi**, sozlamalar
  (`flutter.base_url`, `flutter.savdoos_lang`) **qoldi**.
* **Sessiya chegarasi**: `sessionStorage` dagi token **yangi tab'da yo'q** (bo'sh) —
  ya'ni ilovani yopish sessiyani tugatadi.
* **Build tokeni**: ketma-ket ikki build `1beb6e5c80204ecc` va `d411bdbd8b1e3f0d`
  (har xil), bitta buildda skriptni ikki marta ishlatganда **bir xil** (deterministik).

### Nima tekshirilmagan

* **Haqiqiy iPhone yo'q.** Safari, "Add to Home Screen", standalone rejimда kamera,
  `navigator.share`, PDF chop etish va 7 kunlik storage eviction — **sinalmagan**.
* **Service worker brauzerda ro'yxatdan o'tkazilmagan**: mavjud test brauzeri SW
  registratsiyasiga ruxsat bermaydi. O'lchangan: `navigator.serviceWorker.register('sw.js')`
  → `TypeError: … An unknown error occurred when fetching the script`, va **ayni xato**
  boshqa har qanday skriptда ham (`register('pwa.js')`), holbuki `fetch('sw.js')` = 200.
  Ya'ni muammo bizning worker'da emas, muhitda. Ilova baribir yuklandi (registratsiya
  xatosi `pwa.js` da yutiladi). Siyosat node harness'da (`scripts/pwa_sw_selftest.mjs`,
  27 tekshiruv) va Dart testlarida tekshirilган, **brauzerda emas**: kesh, offline shell,
  yangilanish banneri va `activate` tozalashi haqiqiy brauzerда **sinalmagan**.
* Login'dan keyingi oqimlar (skan, qabul, kassa) web'da **sinalmagan** — faqat login ekrani
  yuklanishi tasdiqlangan.
