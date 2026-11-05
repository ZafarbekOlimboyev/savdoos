# EGASI UCHUN: PRODUCTION AI DIAGNOSTIKASI (5 DAQIQA, HECH NARSA YOZILMAYDI)

## Nega bu siz tomondan bajariladi

Bu mashinadagi Railway CLI `fanzeepubgm@gmail.com` hisobiga kirgan va o'sha
hisobda **11 loyiha** ko'rinadi — `trustworthy-enchantment` ular orasida
**yo'q** (bitta workspace: «Fanzee's Projects»). Loyiha ID bilan ulanishga
urinish ham rad etildi:

```
railway link -p 32171ad7-cd7a-4eb8-8080-4806250fd1b8
  -> Project "32171ad7-..." not found in workspace "Fanzee's Projects"
```

Ya'ni bazaga men ulana olmayman. Qayta-qayta urinmadim.

---

## A YO'LI — Railway Dashboard (tavsiya etiladi)

1. [railway.app](https://railway.app) ga **`trustworthy-enchantment` ga kirish
   huquqi bor hisob** bilan kiring.
2. Loyiha **`trustworthy-enchantment`** → muhit **`production`**.
3. **`Postgres-d29B`** servisini oching.
4. Ma'lumotlar/so'rov bo'limiga o'ting (Railway'da bu **`Data`** yorlig'i;
   ba'zi versiyalarda **`Query`** deb nomlanadi). U yerda SQL yozish oynasi bor.
5. Quyidagi **A blokini** nusxalab yurgizing, keyin **B blokini**.

> ⚠️ Ulanish satrini (`DATABASE_URL`), parolni yoki tokenni **hech qayerga
> ko'chirmang** va menga yubormang — ularning hojati yo'q.

### A BLOKI — nusxalang va yurgizing

```sql
SELECT 'database' AS band, current_database() AS qiymat
UNION ALL
SELECT 'server_version', current_setting('server_version')
UNION ALL
SELECT 'jadval', coalesce(to_regclass('public.ai_requirement')::text, 'YO''Q')
UNION ALL
SELECT 'check_cheklov_soni', (SELECT count(*)::text FROM pg_constraint
                               WHERE conrelid = to_regclass('public.ai_requirement')
                                 AND contype = 'c')
UNION ALL
SELECT 'TRIGGER', (SELECT count(*)::text FROM pg_trigger
                    WHERE tgrelid = to_regclass('public.ai_requirement')
                      AND NOT tgisinternal
                      AND tgname = 'ai_requirement_revision_guard')
UNION ALL
SELECT 'guard_funksiya', (SELECT count(*)::text FROM pg_proc
                           WHERE proname = 'ai_requirement_revision_guard')
ORDER BY band;
```

### B BLOKI — nusxalang va yurgizing

```sql
SELECT id, revision, mode, provider, model,
       disclosure_version, disclosure_id, protocol_version, dispatch_id,
       activated_by, activated_at,
       (protocol_version = 2
        AND dispatch_id = 'binos.receiving.dispatch.v2'
        AND disclosure_version = 1
        AND disclosure_id = 'binos.receiving.ai.v1') AS kanonik
  FROM public.ai_requirement
 ORDER BY id;
```

### Menga nimani qaytarish kerak

Ikki jadvalning chiqishini to'liq (skrinshot yoki matn). Ularda sir yo'q:
`ai_requirement` da kredensial saqlanmaydi (provayder kaliti muhit
o'zgaruvchisida) va mijoz ma'lumoti ham yo'q — bu global siyosat qatori.

Agar B bloki **«relation ... does not exist»** xatosi bersa — shuni aytsangiz
yetarli (A bloki buni allaqachon ko'rsatgan bo'ladi).
Agar B bloki **0 qator** qaytarsa — «0 qator» deb yozing.

---

## B YO'LI — men yurgizishim uchun

Agar menga ulanish qulay bo'lsa, **o'zingizning terminalingizda** CLI'ni
to'g'ri hisobga o'tkazing (men sizning autentifikatsiyangizga tegmayman):

```bash
railway logout && railway login
```

Keyin «tayyor» deb aytsangiz, men `railway link` + `railway connect` orqali
`ops/ai-requirement/prod_readonly_diagnose.sql` ni yurgizaman — u
`BEGIN READ ONLY` ichida ishlaydi va o'zi read-only ligini isbotlaydi
(negativ nazorat bilan tekshirilgan: `UPDATE` → `cannot execute UPDATE in a
read-only transaction`).

---

## NATIJA → QAROR

| A: `TRIGGER` | B: qator | Xulosa | `--provision` |
|---|---|---|---|
| 0 | 0 qator | Migratsiya bajarilmagan. AI o'chiq **va yoqib bo'lmaydi** | ✅ **KERAK** |
| 0 | 1 qator | Qator qo'lda qo'yilgan, **baza gardi yo'q** | ✅ **KERAK** (gardni o'rnatadi, qatorga tegmaydi) |
| 1 | 0 qator | Gard bor, qator yo'q | ✅ **KERAK** (faqat qatorni ekadi) |
| 1 | 1 qator, `mode=paused`, `kanonik=true` | Hammasi joyida, AI ataylab pauzada | ❌ **KERAK EMAS** |
| 1 | 1 qator, `kanonik=false` | `locked()` → 503 `AI_WORKER_FENCED` | ❌ provision emas — `activate` bilan CAS |
| — | `mode=active` | **AI allaqachon yoniq** — eski klientlar 422 oladi | ❌ provision emas; yangi klientlar tarqatilmagan bo'lsa `paused` ga qaytaring |

⚠️ `jadval = YO'Q` chiqishi **kutilmaydi**: boot har safar
`Base.metadata.create_all` yurgizadi va model ro'yxatdan o'tgan. Agar shunday
chiqsa, bu ayrim xulosani talab qiladi — menga aytib yuboring.
