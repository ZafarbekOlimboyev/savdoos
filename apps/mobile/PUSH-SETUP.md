# Push bildirishnoma (Firebase / FCM) — sozlash

Telefon **yopiq turganda ham** keladigan bildirishnoma (kam qolgan/tugagan tovar) uchun Firebase kerak.
Backend allaqachon tayyor (`/devices/register`, kam-qoldiq trigger). Qoldi 2 narsa: **siz** Firebase
loyiha ochasiz, **men** Flutter tomonni ulayman.

## Siz qiladigan qism (Firebase — ~10 daqiqa)

1. **console.firebase.google.com** → **Add project** → nom: `SavdoOS` → yarating
   (Google Analytics'ni o'chirib qo'ysangiz ham bo'ladi).

2. Loyiha ichida **Android** ilova qo'shing (Android ikonkasi):
   - **Android package name:** `com.savdoos.savdoos_mobile`  ← aynan shu, o'zgartirmang
   - App nickname: `SavdoOS` (ixtiyoriy)
   - SHA-1: **shart emas** (push uchun kerak emas) → **Register app**

3. **`google-services.json`** faylini yuklab oling → **menga yuboring**
   (yoki o'zingiz `apps/mobile/android/app/google-services.json` ga qo'ying).

4. Server bildirishnoma yuborishi uchun kalit:
   Firebase konsol → **⚙ (Project settings)** → **Service accounts** →
   **Generate new private key** → JSON yuklanadi → **shu faylni menga bering**
   (yoki o'zingiz Railway'ga `FCM_CREDENTIALS_JSON` env sifatida to'liq JSON matnini qo'yasiz).

> Ikkala faylni ham sir saqlang — GitHub'ga qo'ymang (men `.gitignore`'ga qo'shaman).

## Men qiladigan qism (siz fayllarni bergач)

- Flutter'ga `firebase_core` + `firebase_messaging` qo'shaman, `google-services.json`'ni ulayman.
- Ilovaga kirganда FCM tokenni olib, `/devices/register` ga yuboraman + bildirishnoma ruxsatini so'rayman.
- Railway'ga `FCM_CREDENTIALS_JSON` o'rnataman.
- Push'li APK yig'ib yuboraman va sinab ko'ramiz (`/devices/test` bilan).

## Qanday ishlaydi (tayyor bo'lgач)

Kassir sotuv qilганда biror tovar **minimal qoldiq ostiga tushса** — egа telefoniga darrov
**"Kam qoldi: Coca-Cola — qoldiq 9"** degan push keladi (ilova yopiq bo'lса ham). Har tovar
uchun **1 marta** (qayta-qayta emas); qabul qilib to'ldirilса — keyingi tushишда yana ogohlantiradi.

## iOS haqida

iOS push qo'shимча **APNs** (Apple Push) sozlamasини talab qiladi — Apple Developer akkаунти
($99/yil) va sertifikat. Android'да esa yuqоридаги qadamlar yetарли. iOS'ни keyinroq qo'shамиз.
