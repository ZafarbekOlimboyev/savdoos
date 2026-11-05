# TestFlight — AI NAKLADNOY SKANERLASH: QABUL CHECKLISTI

iPhone'da Build 68 bilan bajariladi. Har band uchun **kutilgan natija** yozilgan;
mos kelmasa — NO-GO va sabab qayd etiladi.

---

## 0. Prekondisiyalar (bajarilmasa testning ma'nosi yo'q)

| # | Shart | Qanday tekshiriladi |
|---|---|---|
| P1 | Backend integratsiya kodida (`8b6f0aa` nasabi) | `GET /api/v1/health` → `build.commit` |
| P2 | `ai_requirement` provision qilingan (trigger + qator) | `ops/ai-requirement/prod_readonly_diagnose.sql` → `trigger=1`, `qator_soni=1` |
| P3 | Rejim `active`, provayder va model qo'yilgan | ayni SQL → `mode=active`, `kanonik=t` |
| P4 | Provayder kaliti muhitda bor | aks holda 503 `AI_CREDENTIAL_UNAVAILABLE` |
| P5 | **Yangi desktop reliz tarqatilgan** | aks holda desktop'da grant/scan **422** |
| P6 | Telefonda Build 68 (62 EMAS) | Sozlamalar → ilova versiyasi `1.0.0 (68)` |
| P7 | Test do'konida rozilik **hali berilmagan** | birinchi foydalanish yo'lini ko'rish uchun |

⚠️ P2/P3 ni **egasi** bajaradi. Men ularni bajarmadim: production DB, migratsiya
va AI aktivatsiyasi taqiqlangan.

---

## 1. Rozilik darvozasi — birinchi foydalanish

| # | Qadam | Kutilgan natija |
|---|---|---|
| 1.1 | Qabul → nakladnoyni rasmga olish | Rasm YUBORILMASDAN OLDIN rozilik oynasi chiqadi |
| 1.2 | Oynadagi matnni o'qish | Provayder **nomi** ko'rinadi (masalan «Google Gemini (Google LLC)»), modeli va nima yuborilishi aytiladi |
| 1.3 | **Rad etish** | Oyna yopiladi, **rasm yuborilmaydi**, qo'lda kiritish ishlaydi |
| 1.4 | Qayta urinib, **rozilik berish** | Rasm yuboriladi, qatorlar taklif qilinadi |
| 1.5 | Ikkinchi marta rasmga olish | Rozilik **qayta so'ralmaydi** (bir marta berilgan) |

**Nega muhim:** rozilik serverda, reviziyaga bog'langan holda saqlanadi; mijozning
`consent: true` bayrog'i dalil EMAS.

## 2. Natijani qabul qilish

| # | Qadam | Kutilgan natija |
|---|---|---|
| 2.1 | Taklif qilingan qatorlarni ko'rish | Mahsulot, miqdor, narx ko'rinadi; **avtomatik saqlanmaydi** |
| 2.2 | Bitta qatorni qo'lda tuzatish | Tuzatish saqlanadi |
| 2.3 | Qabulni tasdiqlash | Ombor va tannarx to'g'ri yangilanadi |
| 2.4 | Bir xil rasmni QAYTA yuborish | Takroriy qabul yaratilmaydi (yoki ogohlantiriladi) |

## 3. Rad etish yo'llari — ENG MUHIM QISM

| # | Holat (egasi o'zgartiradi) | Kutilgan natija telefonda |
|---|---|---|
| 3.1 | Rejim `paused` ga qaytariladi | O'zbekcha xabar: AI mavjud emas, **qatorlarni qo'lda kiriting**. Ilova yiqilmaydi, rasm yuborilmaydi |
| 3.2 | Provayder `gemini` → `anthropic` ga o'zgartiriladi | **Rozilik QAYTA so'raladi** (yangi provayder nomi bilan). Eski rozilik avtomatik o'tmaydi |
| 3.3 | Rozilik do'kon sozlamalaridan **bekor qilinadi** | Keyingi skan rozilik so'raydi; so'rovsiz rasm chiqmaydi |
| 3.4 | Provayder kaliti olib tashlanadi | 503 → o'zbekcha «mavjud emas» xabari, qo'lda kiritish ishlaydi |
| 3.5 | Skan o'rtasida **aviarejim** | Xato ko'rsatiladi, takroriy qabul YARATILMAYDI, jim muvaffaqiyat YO'Q |

⚠️ 3.1/3.4 da mijozda alohida tarjima YO'Q — server o'zbekcha matn yuboradi
(`"AI xizmati hozir mavjud emas. Qatorlarni qo'lda kiriting."`). Checklist aynan
shu matn ko'rinishini tekshiradi; inglizcha kod ko'rinsa — NO-GO.

## 4. Huquqlar

| # | Qadam | Kutilgan natija |
|---|---|---|
| 4.1 | **Kassir** hisobi bilan kirib, skanni sinash | Rozilik BERA OLMAYDI (403) — rozilik ega/administrator huquqi |
| 4.2 | Ega rozilik bergandan keyin kassir skan qiladi | Ishlaydi (rozilik do'kon darajasida) |
| 4.3 | Boshqa do'kon hisobiga kirish | Rozilik **o'tmaydi** — har kompaniya alohida |

## 5. Qo'lda kiritish buzilmaganini tasdiqlash

| # | Qadam | Kutilgan natija |
|---|---|---|
| 5.1 | AI'ni umuman ishlatmasdan nakladnoyni qo'lda kiritish | To'liq ishlaydi (AI yo'li ixtiyoriy qatlam) |
| 5.2 | Partiya kuzatuvli mahsulot bilan qo'lda qabul | Partiya maydonlari talab qilinadi, hisob to'g'ri |

---

## GO / NO-GO qoidasi

* **GO** — 1-bo'lim to'liq, 3-bo'limning HAMMA bandi kutilganidek, 5-bo'lim buzilmagan.
* **NO-GO** — 3-bo'limdan birortasi mos kelmasa (rasm roziliksiz chiqsa, provayder
  o'zgarganda rozilik qayta so'ralmasa, yoki xato matni o'zbekcha bo'lmasa).

Natijani shu faylga YOZMANG — alohida ijro jurnali yarating (sana, build, kim sinadi,
har band bo'yicha ✅/❌ va skrinshot).
