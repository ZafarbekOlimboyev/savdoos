-- BinOS asosiy PRODUCTION — FAQAT O'QISH auditi (P0 cutover uchun).
-- Butun blok READ ONLY tranzaksiyada va ROLLBACK bilan tugaydi: YOZUV YO'Q.
-- Chiqishda parol, token yoki shaxsiy ma'lumot YO'Q — faqat sanoq, kod va o'lcham.
SELECT 'read_only', current_setting('transaction_read_only');

-- 1. SXEMA VA KATALOG MOSLIGI (klonda: 84 jadval, 21 ruxsat, 5 rol, 4 birlik)
SELECT 'tables', count(*) FROM information_schema.tables
 WHERE table_schema IN ('public','cash') AND table_type='BASE TABLE';
SELECT 'catalog', (SELECT count(*) FROM permissions), (SELECT count(*) FROM roles),
       (SELECT count(*) FROM units), (SELECT count(*) FROM plans);
SELECT 'perm_codes', string_agg(code, ',' ORDER BY code) FROM permissions;
SELECT 'role_codes', string_agg(code, ',' ORDER BY code) FROM roles;
SELECT 'unit_codes', string_agg(code, ',' ORDER BY code) FROM units;
SELECT 'has_kassa_ops', count(*) FROM permissions WHERE code = 'kassa.ops';

-- 2. TENANT KODI TO'QNASHUVI
SELECT 'company_codes', count(*), string_agg(code, ',' ORDER BY code) FROM companies;
SELECT 'demoprodsm_bormi', count(*) FROM companies WHERE code = 'demoprodsm';

-- 3. UUID VA NOYOB KALIT TO'QNASHUVI (demo qiymatlari)
SELECT 'uuid_hits', count(*) FROM (VALUES ('11a2b691-f003-458c-bc8c-d6a1bd35fb1a'::uuid),('521a6d0d-aab8-49e8-943c-7fa68a1532ae'::uuid),('4d3ab9e9-63e4-47dc-8bc5-cfa727a5bb50'::uuid),('24884ab6-7b9f-4e00-b4bb-eba9a0c4a6a8'::uuid),('dd162f38-e935-422b-a212-1b206183269d'::uuid)) v(id)
 WHERE EXISTS (SELECT 1 FROM companies WHERE id = v.id)
    OR EXISTS (SELECT 1 FROM branches  WHERE id = v.id)
    OR EXISTS (SELECT 1 FROM cash.cash_accounts WHERE id = v.id)
    OR EXISTS (SELECT 1 FROM cash_movements WHERE client_uuid = v.id);
SELECT 'phone_hits', count(*) FROM employees
 WHERE password_hash IS NOT NULL AND phone IN ('+996253838615','+996715644735','+996199577652','+996306867245','+996312245676','+996978666544','+996803774595','+996192639269','+996757106823');

-- 4. OBUNA TALABI
SELECT 'subs_rows', count(*) FROM subscriptions;
SELECT 'subs_cols', string_agg(column_name, ',') FROM information_schema.columns
 WHERE table_name = 'subscriptions';
SELECT 'plans', count(*), coalesce(string_agg(code, ',' ORDER BY code), '-') FROM plans;

-- 5. RATE LIMIT (DB tomoni)
SELECT 'auth_attempts_rows', count(*) FROM auth_attempts;
SELECT 'auth_attempts_cols', string_agg(column_name, ',') FROM information_schema.columns
 WHERE table_name = 'auth_attempts';

-- 6. O'LCHAM VA SIG'IM
SELECT 'db_size', pg_size_pretty(pg_database_size(current_database()));
SELECT 'pg_version', substring(version() from 'PostgreSQL [0-9.]+');
SELECT 'top_tables', relname, pg_size_pretty(pg_total_relation_size(c.oid))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname IN ('public','cash') AND c.relkind = 'r'
 ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 5;
SELECT 'row_counts', (SELECT count(*) FROM sales), (SELECT count(*) FROM employees),
       (SELECT count(*) FROM products);
