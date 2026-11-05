-- BinOS R7.5 — AI SIYOSATI DIAGNOSTIKASI: RAILWAY DASHBOARD VARIANTI
--
-- NEGA ALOHIDA FAYL: `prod_readonly_diagnose.sql` `psql` uchun yozilgan va
-- `BEGIN READ ONLY ... COMMIT` blokidan foydalanadi. Railway Dashboard'ning
-- so'rov oynasi har so'rovni ALOHIDA yurgizadi, shu bois tranzaksiya bloki
-- u yerda ishlamaydi. Bu yerdagi ikki blok — SOF `SELECT`, ya'ni tranzaksiya
-- blokisiz ham hech narsa YOZMAYDI.
--
-- ISHLATISH: A blokini nusxalab yurgizing, keyin B blokini. Natijani
-- hisobotga qaytaring.
--
-- ⚠️  CHIQISHDA SIR YO'Q: `ai_requirement` da kredensial saqlanmaydi (provayder
--     kaliti muhit o'zgaruvchisida), mijoz ma'lumoti ham yo'q — bu global
--     siyosat qatori. Ulanish satrini, parolni yoki tokenni HECH QAYERGA
--     ko'chirmang: ularning hojati yo'q.


-- ═════════════════════════════════════════════════════════════════════════
-- A BLOKI — KATALOG. Jadval bo'lmasa ham XATO BERMAYDI (`to_regclass` NULL
--           qaytaradi, `tgrelid = NULL` esa hech qanday qator bermaydi).
-- ═════════════════════════════════════════════════════════════════════════
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


-- ═════════════════════════════════════════════════════════════════════════
-- B BLOKI — SIYOSAT QATORINING O'ZI.
--
--   · 0 QATOR qaytsa  -> qator YO'Q  -> `--provision` KERAK
--   · 1 qator qaytsa  -> `mode`, `revision` va `kanonik` javobni beradi
--   · "relation does not exist" xatosi qaytsa -> jadval ham yo'q (A bloki
--     buni allaqachon ko'rsatgan bo'ladi)
-- ═════════════════════════════════════════════════════════════════════════
SELECT id,
       revision,
       mode,
       provider,
       model,
       disclosure_version,
       disclosure_id,
       protocol_version,
       dispatch_id,
       activated_by,
       activated_at,
       (protocol_version = 2
        AND dispatch_id = 'binos.receiving.dispatch.v2'
        AND disclosure_version = 1
        AND disclosure_id = 'binos.receiving.ai.v1') AS kanonik
  FROM public.ai_requirement
 ORDER BY id;


-- ═════════════════════════════════════════════════════════════════════════
-- NATIJANI O'QISH
-- ═════════════════════════════════════════════════════════════════════════
--
--  A: TRIGGER=0  va  B: 0 qator
--     -> Migratsiya BAJARILMAGAN. AI o'chiq (503 AI_REQUIREMENT_UNAVAILABLE)
--        va YOQIB BO'LMAYDI. `--provision` KERAK.
--
--  A: TRIGGER=1  va  B: 1 qator, mode='paused', kanonik=true
--     -> Hammasi joyida. `--provision` KERAK EMAS. AI ataylab pauzada;
--        yoqish uchun alohida `activate` amali (va avval yangi klientlar).
--
--  A: TRIGGER=0  va  B: 1 qator
--     -> Qator qo'lda qo'yilgan, BAZA GARDI YO'Q (reviziya monotonligi faqat
--        ilova kodida himoyalangan). `--provision` KERAK — u gardni o'rnatadi
--        va QATORGA TEGMAYDI.
--
--  A: TRIGGER=1  va  B: 0 qator
--     -> Gard bor, qator yo'q. `--provision` KERAK (faqat qatorni ekadi).
--
--  B: kanonik=false
--     -> `locked()` 503 AI_WORKER_FENCED beradi. Qo'lda UPDATE QILMANG —
--        trigger reviziya +1 dan boshqasini rad etadi. `activate` ni to'g'ri
--        `--expected-revision` bilan yurgizing.
--
--  B: mode='active'
--     -> AI ALLAQACHON YONIQ. Eski klientlar (iOS 62/65/66, eski desktop)
--        grant/scan'da 422 oladi. Yangi klientlar tarqatilmagan bo'lsa
--        `--mode paused` ga QAYTARING.
