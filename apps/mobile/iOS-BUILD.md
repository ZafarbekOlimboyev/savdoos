# SavdoOS Mobil — iPhone (iOS) uchun yig'ish va o'rnatish

> ⚠️ **Muhim — Android'dan farqi.** iOS'da APK kabi "faylni yuklab, bosib o'rnatish" ishlamaydi.
> Apple har bir ilovani **imzolashni** (code signing) talab qiladi — telefon faqat imzolangan
> ilovani ishga tushiradi. Shuning uchun tayyor `.ipa` faylni GitHub'ga qo'yib, uni istalgan
> iPhone'ga o'rnatib bo'lmaydi. iPhone'ga o'rnatishning ishlaydigan yo'llari quyida.
>
> Bu yerda **loyiha to'liq tayyor** (iOS papkasi + ruxsatlar generatsiya qilingan). Faqat
> **Mac'da** Xcode bilan yig'ish qoladi (Windows'da iOS yig'ib bo'lmaydi — Xcode faqat macOS'da).

---

## Kerak bo'ladigan narsalar (Mac'da)

1. **macOS** + **Xcode** (App Store'dan bepul, ~10 GB).
2. **Flutter SDK** — https://docs.flutter.dev/get-started/install/macos
3. **CocoaPods** — `sudo gem install cocoapods` (yoki `brew install cocoapods`).
4. **Apple ID** — oddiy bepul Apple ID yetadi (developer akkaunti shart emas, pastga qarang).

Tekshirish: `flutter doctor` — Xcode va CocoaPods yashil bo'lsin.

---

## 1-qadam — loyihani Mac'ga olish

Kod GitHub'da (yopiq repo). Mac'da:
```bash
git clone https://github.com/ZafarbekOlimboyev/savdoos.git
cd savdoos/apps/mobile
flutter pub get
cd ios && pod install && cd ..
```

---

## 2-qadam — o'z iPhone'ingizga o'rnatish

### Yo'l A — Xcode + kabel (BEPUL, eng oson) ✅ tavsiya

Faqat **o'zingizning telefoningizga** sinash uchun — Apple developer akkaunti ($99) shart emas,
oddiy Apple ID yetadi. Kamchiligi: ilova **7 kundan keyin** ishlamay qoladi, qayta yig'ish kerak.

1. iPhone'ni Mac'ga **kabel** bilan ulang, telefonda "Trust / Ishon" ni bosing.
2. **RELEASE rejimda** o'rnatish (ENG OSON — bitta buyruq, kabel ulangan holda):
   ```bash
   flutter run --release
   ```
   > ⚠️ **`--release` MUHIM.** Oddiy `flutter run` yoki Xcode'ning oddiy Run tugmasi **debug**
   > rejimda yig'adi — u holda ilova telefonga o'rnatiladi, lekin ikonkani bosganda OCHILMAYDI
   > ("In iOS 14+, debug mode Flutter apps can only be launched from Flutter tooling…" xabari).
   > Release rejimda esa bosh ekrandan normal ochiladi.
3. Signing (birinchi marta): agar `flutter run --release` "development team" xatosi bersa —
   `open ios/Runner.xcworkspace` (aynan `.xcworkspace`!) → **Runner → Signing & Capabilities**:
   - **Automatically manage signing** ✓
   - **Team** → **Add an Account…** → Apple ID bilan kiring → Personal Team'ni tanlang.
   - **Bundle Identifier** noyob bo'lsin (band bo'lsa masalan `com.savdoos.savdoosMobile2`).
   - So'ng yana Terminal'da `flutter run --release`.
   - (Xcode'dan Run qilsangiz: **Product → Scheme → Edit Scheme → Run → Build Configuration =
     Release** qo'ying, keyin ▶ Run — aks holda debug bo'ladi.)
4. Birinchi marta telefonda: **Sozlamalar → Umumiy → VPN va qurilma boshqaruvi →
   [Apple ID'ingiz] → Ishon**.
5. Tayyor — ilova bosh ekrandan ochiladi. Kirish: vendor bergan **telefon + parol**.

> Bepul Apple ID bilan release ham **7 kunda** muddati tugaydi — o'sha payt yana
> `flutter run --release` bosasiz (qaytadan 7 kun).

### Yo'l B — TestFlight (bir necha telefon, 90 kun) — $99/yil kerak

Ko'p qurilmага yoki uzoq muddatga (do'kon egаlariga tarqatish) — Apple Developer Program
($99/yil) kerak:
```bash
flutter build ipa
```
So'ng `build/ios/archive/Runner.xcarchive` ni Xcode → **Organizer** orqali **App Store Connect**'ga
yuklaysiz → **TestFlight**'да odamlarга havola yuborasiz. Ular TestFlight ilovаsидан o'rnatadi.

---

## Sozlangan narsalar (allaqачон tayyor)

- iOS papka (`ios/`) generatsiya qilingan, org: `com.savdoos`.
- **Kamera + Galereya ruxsatlari** (`Info.plist`: NSCameraUsageDescription, NSPhotoLibraryUsageDescription)
  — nakladnoy skani ishlashi uchun.
- Ilova nomi: **SavdoOS**.
- Server: standart Railway prod (Sozlamalarда o'zgartirса bo'ladi).

## Muammolar bo'lsa

- **"Signing requires a development team"** — 3-qadamдаги Team'ni tanlang.
- **`pod install` xato** — `cd ios && pod repo update && pod install`.
- **Ilova ochilганда yiqilса** — kamera ruxsatlari Info.plist'да borligini tekshiring (bor).
- **Bundle ID band** — boshqa noyob ID qo'ying.
