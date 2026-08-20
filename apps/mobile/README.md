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
