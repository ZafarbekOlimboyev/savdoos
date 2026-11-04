select 'read_only', current_setting('transaction_read_only');
select n.nspname||'.'||c.relname||' | '||i.relname||' | '||
       coalesce((select string_agg(a.attname, '+' order by k.ord)
                   from unnest(x.indkey) with ordinality k(attnum, ord)
                   join pg_attribute a on a.attrelid=c.oid and a.attnum=k.attnum), '(ifoda)')||
       ' | '||coalesce(pg_get_expr(x.indpred, x.indrelid), '-') as global_unique_key
  from pg_index x
  join pg_class c on c.oid=x.indrelid
  join pg_class i on i.oid=x.indexrelid
  join pg_namespace n on n.oid=c.relnamespace
 where x.indisunique and not x.indisprimary and c.relkind='r'
   and n.nspname in ('public','cash')
   and not exists (select 1 from unnest(x.indkey) k2
                     join pg_attribute a2 on a2.attrelid=c.oid and a2.attnum=k2
                    where a2.attname in ('company_id','tenant_id'))
 order by 1;
select 'barcode_idx', string_agg(i.relname, ',') from pg_index x
  join pg_class c on c.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
 where c.relname='product_barcodes' and x.indisunique;
select 'barkod_soni', count(*) from product_barcodes
