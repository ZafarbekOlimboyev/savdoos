-- BinOS R7.4 — AI SIYOSATI: PRODUCTION DIAGNOSTIKASI (QAT'IY FAQAT-O'QISH)
--
-- Maqsad: `ai_requirement` ning HAQIQIY holatini aniqlash — jadval, cheklovlar,
-- TRIGGER, qator, rejim va reviziya. Bu savollarga tashqaridan (HTTP orqali)
-- javob BERILMAYDI: `require("xaridlar.edit")` handler'dan oldin ishlaydi, shu
-- bois auth'siz so'rov 401 oladi va 503 ning sababi ko'rinmaydi (R7.3).
--
-- ISHLATISH (Railway -> Postgres -> Query, yoki psql):
--     \i ops/ai-requirement/prod_readonly_diagnose.sql
--
-- ⚠️  BU FAYL HECH NARSA YOZMAYDI. `BEGIN READ ONLY` ichida ishlaydi va
--     birinchi so'rovning o'zi buni ISBOTLAYDI. Agar kimdir keyinroq bu faylga
--     yozuv qo'shsa, tranzaksiya 25006 bilan RAD etadi.
-- ⚠️  Chiqishda sir YO'Q: `ai_requirement` da kredensial saqlanmaydi (kalit
--     muhit o'zgaruvchisida). Mijoz ma'lumoti ham yo'q — bu global siyosat qatori.

BEGIN READ ONLY;

-- 0) Read-only ISBOTI + baza identiteti (qaysi klasterga ulandik).
SELECT 'read_only'        AS band, current_setting('transaction_read_only') AS qiymat
UNION ALL SELECT 'database',       current_database()
UNION ALL SELECT 'system_id',      (SELECT system_identifier::text FROM pg_control_system())
UNION ALL SELECT 'server_version', current_setting('server_version');

-- 1) Jadval BORMI. NULL -> jadval yo'q (kutilmaydi: boot `create_all` uni yaratadi).
SELECT 'jadval' AS band, to_regclass('public.ai_requirement')::text AS qiymat;

-- 2) CHEKLOVLAR — ma'lumot uchun, LEKIN «kim yaratdi» degan savolga JAVOB EMAS.
--
--    ⚠️  CHEKLOV NOMLARI AJRATMAYDI. Boot HAR safar `create_all` yurgizadi va u
--        jadvalni MODEL nomlari bilan yaratadi; keyin `.sql` qo'llansa, uning
--        `CREATE TABLE IF NOT EXISTS` i NO-OP bo'ladi va nomlar O'ZGARMAYDI.
--        Ya'ni ilova bir marta ko'tarilgan HAR qanday bazada nomlar modelning
--        nomlari bo'ladi — migratsiya bajarilgan yoki bajarilmaganidan QAT'I NAZAR.
--        (R7.4 da haqiqiy PG18 da o'lchandi; R7.3 ning bu haqdagi xulosasi XATO edi.)
--
--    Yagona ishonchli signallar — pastdagi (3) TRIGGER va (4) QATOR.
--    Bu so'rov esa boshqa narsani topadi: cheklov umuman YETISHMAYOTGAN bo'lsa
--    (masalan `db/schema.sql` dan qo'lda qurilgan baza) — to'rtta bo'lishi kerak.
SELECT 'cheklov' AS band, conname AS qiymat
  FROM pg_constraint
 WHERE conrelid = 'public.ai_requirement'::regclass AND contype = 'c'
 ORDER BY conname;

-- 3) BAZA DARAJASIDAGI GARD. Ikkisi ham 1 bo'lishi KERAK, aks holda reviziyaning
--    monotonligi faqat ilova kodidagi CAS bilan himoyalangan (baza darajasida EMAS).
SELECT 'trigger' AS band, count(*)::text AS qiymat
  FROM pg_trigger
 WHERE tgrelid = 'public.ai_requirement'::regclass
   AND NOT tgisinternal AND tgname = 'ai_requirement_revision_guard'
UNION ALL
SELECT 'guard_funksiya', count(*)::text
  FROM pg_proc WHERE proname = 'ai_requirement_revision_guard';

-- 4) QATOR. 0 -> AI NI YOQIB BO'LMAYDI (`activate()` 503 beradi) — provision kerak.
SELECT 'qator_soni' AS band, count(*)::text AS qiymat FROM ai_requirement;

-- 5) SIYOSATNING O'ZI va u kanonikmi. `kanonik=false` -> `locked()` AI_WORKER_FENCED
--    beradi; tuzatish faqat `activate()` (CAS) bilan, qo'lda UPDATE bilan EMAS.
SELECT id, revision, mode, provider, model,
       disclosure_version, disclosure_id, protocol_version, dispatch_id,
       activated_by, activated_at,
       (protocol_version = 2 AND dispatch_id = 'binos.receiving.dispatch.v2'
        AND disclosure_version = 1 AND disclosure_id = 'binos.receiving.ai.v1') AS kanonik,
       CASE
         WHEN mode = 'paused' THEN 'AI O''CHIQ -> 503 AI_REQUIREMENT_PAUSED'
         WHEN mode = 'demo'   THEN 'DEMO -> rozilik so''ralmaydi, tashqariga rasm CHIQMAYDI'
         WHEN mode = 'active' THEN 'AI YONIQ -> eski klientlar (iOS 62/65/66, eski desktop) 422 oladi'
       END AS izoh
  FROM ai_requirement
 ORDER BY id;

-- 6) Rozilik yozuvlari — QAYSI do'konlar rozilik bergan (SANOQ, qiymat emas).
SELECT 'rozilik_yozuvi' AS band, count(*)::text AS qiymat
  FROM settings WHERE key = 'ai_consent';

COMMIT;

-- ── NATIJANI QANDAY O'QISH ───────────────────────────────────────────────────
--
-- A) trigger=0 VA qator_soni=0
--    => Migratsiya BAJARILMAGAN. AI o'chiq (503 AI_REQUIREMENT_UNAVAILABLE) va
--       YOQIB BO'LMAYDI. Keyingi qadam — PROVISION (AI ni YOQMAYDI):
--
--         python -m app.tools.ai_requirement --provision --actor <kim> \
--             --expect-system-identifier <yuqoridagi system_id> \
--             --expect-database <yuqoridagi database>
--         # yuqorisi MASHQ qiladi; saqlash uchun oxiriga --commit qo'shing
--
-- B) trigger=1, qator_soni=1, mode='paused'
--    => Himoya TO'LIQ, AI ataylab pauzada. Yoqish uchun (FAQAT yangi desktop va
--       iOS Build 68 tarqatilgandan KEYIN):
--
--         python -m app.tools.ai_requirement --expected-revision <revision> \
--             --mode active --provider gemini --model <model> --actor <kim> \
--             --confirm-fenced-workers-only \
--             --expect-system-identifier <system_id> --expect-database <database>
--         # --commit siz MASHQ qiladi
--
-- C) qator_soni=1 lekin trigger=0
--    => Qator qo'lda qo'yilgan, gard yo'q. PROVISION gardni o'rnatadi va
--       QATORGA TEGMAYDI (`ON CONFLICT (id) DO NOTHING`).
--
-- D) kanonik=false
--    => `locked()` AI_WORKER_FENCED beradi. Qo'lda UPDATE QILMANG (trigger
--       reviziya +1 dan boshqasini rad etadi). `activate()` ni to'g'ri
--       `--expected-revision` bilan yurgizing.
--
-- E) mode='active'
--    => AI YONIQ. Eski klientlar grant/scan'da 422 oladi. Agar yangi klientlar
--       hali tarqatilmagan bo'lsa, `--mode paused` ga QAYTARING (bu ham reviziyani
--       oshiradi va mavjud roziliklarni bekor qiladi).
