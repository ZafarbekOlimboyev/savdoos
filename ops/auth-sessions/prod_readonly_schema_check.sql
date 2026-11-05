-- BinOS R7.6 — `auth_sessions` SXEMASINI PRODUCTION'DA TEKSHIRISH (FAQAT O'QISH)
--
-- Audit talabi: «Production `auth_sessions` sxemasi read-only tekshiruvdan
-- o'tishi kerak». Men production'ga ulana olmayman (R7.5: Railway CLI bu
-- mashinada `trustworthy-enchantment` ni ko'rmaydi), shu bois buni EGASI
-- bajaradi — Railway Dashboard -> Postgres-d29B -> Data.
--
-- ⚠️  SOF `SELECT`. Hech narsa yozilmaydi. Chiqishda sir YO'Q: faqat ustun
--     nomlari va qator SONI (kredensial xeshlari ham CHIQMAYDI).

-- A) Jadval va USTUNLAR. Kutilgan: 7 ustun (model 6 ta e'lon qiladi + `PKMixin`
--    ning `id` i; `TimestampMixin` ISHLATILMAYDI, ya'ni `created_at` YO'Q).
--    `prev_refresh_hash` va `rotated_at` R7.6 da QO'SHILADI va ular hozir
--    BO'LMASLIGI NORMAL — `start.sh` -> `initdb._ensure_columns()` ularni
--    deploy'da avtomatik qo'shadi.
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'auth_sessions'
 ORDER BY ordinal_position;

-- B) Qator soni. Kutilgan: 0 — mexanizm hech qachon ishlatilmagan
--    (`account_deletion.py:28`: «`auth_sessions` jadvali ishlatilmaydi»).
--    0 BO'LMASA — to'xtang va menga xabar bering: kimdir qatorlarni qo'lda
--    kiritgan bo'lishi mumkin va rotation mantiqi ularga ishonmasligi kerak.
SELECT count(*) AS qator_soni FROM public.auth_sessions;

-- C) Indeks. `db/schema.sql:160` da `idx_sessions_emp` bor; `create_all`
--    yaratgan jadvalda u BO'LMASLIGI mumkin. Bu ishlashga ta'sir qiladi,
--    xavfsizlikka EMAS (`revoke_all` xodim bo'yicha qidiradi).
SELECT indexname FROM pg_indexes
 WHERE schemaname = 'public' AND tablename = 'auth_sessions'
 ORDER BY indexname;

-- ── NATIJANI O'QISH ────────────────────────────────────────────────────────
--  A da 7 ustun (prev_refresh_hash/rotated_at YO'Q) + B = 0
--     -> KUTILGAN holat. Deploy ustunlarni qo'shadi, migratsiya KERAK EMAS.
--  A da 9 ustun
--     -> ustunlar allaqachon bor (masalan boshqa muhitdan tiklangan baza).
--        Zararsiz, deploy ularni qayta qo'shmaydi (`_ensure_columns` mavjudini
--        tekshiradi).
--  A da jadval TOPILMADI
--     -> kutilmaydi (`create_all` uni yaratadi). To'xtang va xabar bering.
--  B > 0
--     -> TO'XTANG. Mexanizm ishlatilmagan bo'lishi kerak edi.
