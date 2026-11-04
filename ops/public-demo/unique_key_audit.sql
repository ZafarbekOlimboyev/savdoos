-- NOYOB KALIT AUDITI: tenant import'ida TO'QNASHUV EHTIMOLI BO'LGAN kalitlar.
-- Mantiq: noyob indeks ustunlari ichida tenant doirasi (company_id/tenant_id) BO'LSA
--         to'qnashuv MUMKIN EMAS (boshqa tenant qatori boshqa doirada).
--         Bo'lmasa -> GLOBAL kalit: demo qiymatlari production'da BO'LMASLIGI shart.
select n.nspname || '.' || c.relname as tbl,
       i.relname as idx,
       pg_get_indexdef(x.indexrelid) like '%WHERE%' as qismiy,
       (select string_agg(a.attname, ',' order by k.ord)
          from unnest(x.indkey) with ordinality k(attnum, ord)
          join pg_attribute a on a.attrelid = c.oid and a.attnum = k.attnum) as ustunlar
  from pg_index x
  join pg_class c on c.oid = x.indrelid
  join pg_class i on i.oid = x.indexrelid
  join pg_namespace n on n.oid = c.relnamespace
 where x.indisunique and c.relkind = 'r' and n.nspname in ('public','cash')
 order by 1, 2;
