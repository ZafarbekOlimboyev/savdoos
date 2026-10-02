-- ============================================================================
-- SavdoOS · Cash · Phase 1 — SEYF ONBOARDING / OCHILISH QOLDIG'I (ADDITIV)
--
-- Shartnoma: docs/PURCHASE_SETTLEMENT_PHASE1.md §2 (jadval) va §5 (migratsiya).
--
-- ⚠️  NEGA ALOHIDA FAYL. `cash_ddl_v1.sql` VERSIYALANGAN va MAVJUD bazaga QAYTA
--     QO'LLANMAYDI: `deploy_cash_schema` `cash` sxemasi bor bo'lsa 'exists' qaytaradi
--     va butun faylni o'tkazib yuboradi. Ya'ni v1 ga qo'shilgan yangi obyekt ishlab
--     turgan do'konga HECH QACHON yetib bormasdi. Shu bois Phase 1 obyektlari SHU
--     faylda va ular HAR BOOTDA idempotent qo'llanadi — fresh baza ham AYNI shu
--     yerdan oladi (ikki manba bo'lsa ular ajralib ketardi).
--
-- ⚠️  JIMGINA ALMASHTIRISH YO'Q. Bu yerda DROP TABLE / DROP TYPE / ALTER … DROP /
--     REINDEX YO'Q. Nomi to'g'ri, shakli noto'g'ri obyekt TEGILMAYDI — uni
--     `services/cash/schema_readiness.py` topadi va tayyorlik QIZIL bo'ladi.
--
-- ⚠️  Enum labeli (`ACCOUNT_OPENING`) bu faylda EMAS: `ALTER TYPE … ADD VALUE`
--     alohida AUTOCOMMIT ulanishini talab qiladi (yangi label o'sha tranzaksiyada
--     ishlatilmaydi). Uni `deploy.ensure_phase1_objects` qo'shadi.
-- ============================================================================

-- ⚠️  BO'LIMLARGA AJRATILGAN (`-- @@SECTION: <nom>`). `deploy.ensure_phase1_objects`
--     AVVAL katalogni FAQAT O'QIB nima yo'qligini aniqlaydi va FAQAT yetishmagan
--     bo'limni yuboradi. BARQAROR bootda BIRORTA bayonot yuborilmaydi.
--     NEGA MUHIM: `ddl_command_start` hodisa trigger'i jadval QULFIDAN OLDIN ishlaydi,
--     ya'ni `IF NOT EXISTS` ham DDL sifatida KO'RINADI va jonli jadvalga ShareLock
--     so'raydi (`tests/test_boot_locks_pg.py`). Ishlab turgan do'konda bu yozuvchilarni
--     to'sardi.

-- @@SECTION: table
-- ── Ochilish attestatsiyasi: hisob uchun BITTA o'zgarmas yozuv ──────────────
CREATE TABLE IF NOT EXISTS cash.cash_account_openings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES public.companies(id),
    cash_account_id uuid NOT NULL,
    account_type    cash.cash_account_type NOT NULL,   -- hosila nusxa; SEYF bo'lishi SHART
    kind            text NOT NULL,                     -- 'KNOWN_ZERO' | 'COUNTED'
    counted_amount  numeric(14,2) NOT NULL,            -- KNOWN_ZERO -> 0 ; COUNTED -> > 0
    currency        char(3) NOT NULL,
    counted_at      timestamptz NOT NULL,              -- ATTESTATSIYA sanog'i vaqti (§8)
    attested_by     uuid NOT NULL REFERENCES public.employees(id),
    attestation_ref text NOT NULL,                     -- hujjat/dalolatnoma havolasi
    ledger_entry_id uuid,                              -- COUNTED -> NOT NULL; KNOWN_ZERO -> NULL
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_cao_kind          CHECK (kind IN ('KNOWN_ZERO','COUNTED')),
    CONSTRAINT ck_cao_amount_nonneg CHECK (counted_amount >= 0),
    -- KNOWN_ZERO aynan NOL, COUNTED aynan MUSBAT — «nol summali ochilish legi» bo'lmaydi
    CONSTRAINT ck_cao_kind_amount   CHECK ((kind = 'COUNTED') = (counted_amount > 0)),
    -- KNOWN_ZERO ledger legi YOZMAYDI, COUNTED esa AYNAN bittasini yozadi
    CONSTRAINT ck_cao_kind_ledger   CHECK ((kind = 'COUNTED') = (ledger_entry_id IS NOT NULL)),
    CONSTRAINT ck_cao_ref_nb        CHECK (attestation_ref <> ''),
    CONSTRAINT ck_cao_type_safe     CHECK (account_type = 'SAFE'),

    -- SEYF-only + ayni tenant — DEKLARATIV (mavjud `ca_uq_tenant_id_type` ga tayanadi;
    -- yangi ota-kalit qo'shilmaydi):
    CONSTRAINT cao_acct_type_fk FOREIGN KEY (tenant_id, cash_account_id, account_type)
        REFERENCES cash.cash_accounts (tenant_id, id, type),
    -- valyuta hisobniki bilan bir xil (`ca_uq_tenant_id_currency`):
    CONSTRAINT cao_acct_cur_fk FOREIGN KEY (tenant_id, cash_account_id, currency)
        REFERENCES cash.cash_accounts (tenant_id, id, currency),
    CONSTRAINT cao_entry_fk FOREIGN KEY (tenant_id, ledger_entry_id)
        REFERENCES cash.cash_ledger_entries (tenant_id, id),

    CONSTRAINT cao_uq_account   UNIQUE (tenant_id, cash_account_id),   -- BITTA hisob = BITTA ochilish
    CONSTRAINT cao_uq_tenant_id UNIQUE (tenant_id, id)
);
COMMENT ON TABLE cash.cash_account_openings IS
    'SEYF ochilish attestatsiyasi: hisob uchun BITTA o''zgarmas yozuv. COUNTED -> aynan bitta '
    'NORMAL·ACCOUNT_OPENING·IN·ADJUSTMENT legi; KNOWN_ZERO -> leg YO''Q. Ochilish yozuvi '
    'bo''lmagan SEYF OPERATSION EMAS (UNKNOWN != nol).';

-- @@SECTION: index
-- Bitta ledger legi — bitta ochilish (soxta/takroriy bog'lanish bo'lmasin).
CREATE UNIQUE INDEX IF NOT EXISTS cao_uq_entry
    ON cash.cash_account_openings (ledger_entry_id) WHERE ledger_entry_id IS NOT NULL;

-- @@SECTION: triggers
-- ── O'zgarmaslik (append-only) — mavjud qo'riqchi funksiyalar qayta ishlatiladi ──
-- Tuzatish/reversal yo'li Phase 1 da YO'Q (§9): zid qayta-attestatsiya 409 beradi.
--
-- ⚠️  FAQAT YO'Q BO'LSA YARATILADI — `DROP TRIGGER` ATAYLAB YO'Q. `DROP`+`CREATE`
--     juftligi MAVJUD triggerni JIMGINA almashtirardi, holbuki u ataylab boshqa
--     bo'lishi mumkin: `cash_ddl_v1.sql` §CF-D6 append-only jadvalga haqiqiy
--     tuzatishni «audit qilingan tranzaksiya ichida qo'riqchi triggerni VAQTINCHA
--     o'chirish» deb ta'riflaydi — boot o'sha protsedurani o'rtasidan buzib
--     qo'ymasligi kerak. YO'Q trigger esa TIKLANADI: bu himoyani qayta o'rnatish,
--     u hech narsa yo'qotmaydi (R-DDL dagi ayni naqsh: yo'q -> yarat, bor-u
--     noto'g'ri -> tegma, tayyorlik QIZIL).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger tg
                     JOIN pg_class t ON t.oid = tg.tgrelid
                     JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'cash' AND t.relname = 'cash_account_openings'
                      AND tg.tgname = 'trg_cao_immutable' AND NOT tg.tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_cao_immutable BEFORE UPDATE OR DELETE '
                'ON cash.cash_account_openings '
                'FOR EACH ROW EXECUTE FUNCTION cash.fn_block_mutation()';
        RAISE NOTICE 'cash: trg_cao_immutable TIKLANDI (yo''q edi)';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger tg
                     JOIN pg_class t ON t.oid = tg.tgrelid
                     JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'cash' AND t.relname = 'cash_account_openings'
                      AND tg.tgname = 'trg_cao_no_truncate' AND NOT tg.tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_cao_no_truncate BEFORE TRUNCATE '
                'ON cash.cash_account_openings '
                'FOR EACH STATEMENT EXECUTE FUNCTION cash.fn_block_truncate()';
        RAISE NOTICE 'cash: trg_cao_no_truncate TIKLANDI (yo''q edi)';
    END IF;
END $$;

-- @@SECTION: grants
-- ── Grantlar (rol MAVJUD bo'lsa) ────────────────────────────────────────────
-- `ALTER DEFAULT PRIVILEGES` faqat AYNI rol yaratgan jadvalga tegadi, shu bois aniq beramiz.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_readonly') THEN
        EXECUTE 'GRANT SELECT ON cash.cash_account_openings TO cash_readonly';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_app') THEN
        EXECUTE 'GRANT SELECT ON cash.cash_account_openings TO cash_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_posting') THEN
        EXECUTE 'GRANT SELECT, INSERT ON cash.cash_account_openings TO cash_posting';
        EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON cash.cash_account_openings FROM cash_posting';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_admin') THEN
        EXECUTE 'GRANT ALL ON cash.cash_account_openings TO cash_admin';
        -- GRANT ALL UPDATE/DELETE/TRUNCATE ham beradi — o'zgarmas jadvalda uchalasi ham qaytariladi
        -- (triggerlar bilan ikki qatlamli himoya, `cash_ddl_v1.sql` §P naqshi).
        EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON cash.cash_account_openings FROM cash_admin';
    END IF;
END $$;
