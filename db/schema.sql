-- ============================================================================
--  SavdoOS — Ma'lumotlar bazasi sxemasi (PostgreSQL 16)
--  Markaziy OLTP baza. Kassa (SQLite) shu sxemaning kichraytirilgan nusxasi.
--
--  PRINSIPLAR
--   • Hech qanday ma'lumot yo'qolmaydi — fizik o'chirish YO'Q (deleted_at soft-delete).
--   • Savdo qatorida narx VA tannarx o'sha ondagi holida saqlanadi (snapshot) →
--     kelajakda narx o'zgarsa ham tarixiy marja/foyda to'g'ri hisoblanadi.
--   • Har mutable jadval: id(UUID) · created_at · updated_at · created_by ·
--     deleted_at · client_uuid(offline idempotentlik) · row_version(sync).
--   • Pul: numeric(14,2) · Miqdor: numeric(14,3) (kg/litr uchun kasr) · Vaqt: timestamptz.
--   • Barcha o'zgaruvchan jadvalga updated_at + row_version trigger avtomatik biriktiriladi.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- nom/telefon bo'yicha tez qidiruv (ILIKE)

-- ---------------------------------------------------------------------------
-- 0. YORDAMCHI: updated_at + row_version avtomatik yangilash
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_row_meta() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  NEW.row_version := COALESCE(OLD.row_version, 0) + 1;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ENUM turlari (barqaror, ichki holatlar)
CREATE TYPE employee_status   AS ENUM ('active','suspended','terminated');
CREATE TYPE shift_status       AS ENUM ('open','closed');
CREATE TYPE sale_status        AS ENUM ('completed','voided','refunded','partially_refunded');
CREATE TYPE purchase_status    AS ENUM ('draft','received','paid','partial','debt','cancelled');
CREATE TYPE return_reason      AS ENUM ('customer','defective','wrong_item','expired','other');
CREATE TYPE credit_txn_type    AS ENUM ('charge','payment','adjustment','writeoff');
CREATE TYPE movement_type      AS ENUM
  ('purchase_in','sale_out','return_in','writeoff','adjustment','transfer_in','transfer_out','count_adjust');
CREATE TYPE cash_movement_type AS ENUM ('opening','sale_cash','payin','payout','expense','collection','closing');
CREATE TYPE import_status      AS ENUM ('uploaded','validated','committing','committed','failed');
CREATE TYPE import_row_status  AS ENUM ('new','existing','error');
CREATE TYPE price_type         AS ENUM ('buy','sell');


-- ===========================================================================
-- 1. TASHKILOT (companies · branches · terminals)
-- ===========================================================================
CREATE TABLE companies (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  legal_name    text,
  tax_id        text,                       -- STIR / INN
  phone         text,
  currency      char(3) NOT NULL DEFAULT 'UZS',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);

CREATE TABLE branches (                      -- filial (Oltin Do'kon · Chilonzor)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  code          text NOT NULL,               -- qisqa kod (F01)
  name          text NOT NULL,
  address       text,
  phone         text,
  timezone      text NOT NULL DEFAULT 'Asia/Tashkent',
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, code)
);

CREATE TABLE terminals (                     -- kassa apparati / qurilma
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  name          text NOT NULL,               -- "Kassa #1"
  device_uuid   text UNIQUE,                 -- fizik qurilma identifikatori
  last_seen_at  timestamptz,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);


-- ===========================================================================
-- 2. AUTH / RBAC (roles · permissions · employees)
-- ===========================================================================
CREATE TABLE roles (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code          text UNIQUE NOT NULL,        -- administrator | menejer | omborchi | kassir
  name          text NOT NULL,
  is_system     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  row_version   bigint NOT NULL DEFAULT 1
);

CREATE TABLE permissions (                   -- modul.harakat: kassa.view, mahsulot.edit ...
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code          text UNIQUE NOT NULL,
  module        text NOT NULL,               -- kassa|sotuvlar|ombor|xaridlar|mijozlar|hisobot|xodimlar|sozlamalar
  description   text
);

CREATE TABLE role_permissions (              -- rol standart ruxsatlari
  role_id       uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE employees (                     -- xodimlar
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  full_name     text NOT NULL,
  phone         text,
  role_id       uuid NOT NULL REFERENCES roles(id),
  pin_hash      text,                        -- 4-6 xonali PIN (bcrypt) — tez kirish
  password_hash text,
  avatar_url    text,
  status        employee_status NOT NULL DEFAULT 'active',
  hired_at      date,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);
CREATE INDEX idx_employees_role ON employees(role_id) WHERE deleted_at IS NULL;

CREATE TABLE employee_permissions (          -- rol ustidan alohida override (Xodimlar sahifasidagi toggle'lar)
  employee_id   uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  allowed       boolean NOT NULL,            -- true=qo'shildi, false=olib tashlandi
  PRIMARY KEY (employee_id, permission_id)
);

CREATE TABLE employee_branches (             -- xodim qaysi filiallarda ishlaydi (ko'p-ko'p)
  employee_id   uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  branch_id     uuid NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
  PRIMARY KEY (employee_id, branch_id)
);

CREATE TABLE auth_sessions (                 -- refresh tokenlar / qurilmalar
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id   uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  terminal_id   uuid REFERENCES terminals(id),
  refresh_hash  text NOT NULL,
  issued_at     timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  ip            inet,
  user_agent    text
);
CREATE INDEX idx_sessions_emp ON auth_sessions(employee_id);


-- ===========================================================================
-- 3. KATALOG (units · brands · categories · products · barcodes · prices)
-- ===========================================================================
CREATE TABLE units (                         -- o'lchov birligi
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code          text UNIQUE NOT NULL,        -- dona | kg | litr | upak
  name          text NOT NULL,
  allow_fraction boolean NOT NULL DEFAULT false   -- kg/litr uchun kasr ruxsat
);

CREATE TABLE brands (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  deleted_at    timestamptz
);

CREATE TABLE categories (                    -- ierarxik (parent_id)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  parent_id     uuid REFERENCES categories(id),
  name          text NOT NULL,
  sort_order    int NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);
CREATE INDEX idx_categories_parent ON categories(parent_id);

CREATE TABLE products (                      -- mahsulot
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  article_code  text NOT NULL,               -- ARTIKUL (1C'dan ko'chganda o'zgarmaydi)
  name          text NOT NULL,
  category_id   uuid REFERENCES categories(id),
  brand_id      uuid REFERENCES brands(id),
  unit_id       uuid NOT NULL REFERENCES units(id),
  base_buy_price  numeric(14,2) NOT NULL DEFAULT 0,   -- joriy kelish narxi (cache)
  base_sell_price numeric(14,2) NOT NULL DEFAULT 0,   -- joriy sotish narxi (cache)
  tax_rate      numeric(5,2) NOT NULL DEFAULT 0,      -- QQS %
  is_weighted   boolean NOT NULL DEFAULT false,       -- tarozida sotiladimi
  is_active     boolean NOT NULL DEFAULT true,
  image_url     text,
  description   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  deleted_at    timestamptz,
  client_uuid   uuid,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, article_code)
);
CREATE INDEX idx_products_cat   ON products(category_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_products_name  ON products USING gin (name gin_trgm_ops);   -- tez qidiruv
CREATE INDEX idx_products_active ON products(is_active) WHERE deleted_at IS NULL;

CREATE TABLE product_barcodes (              -- bitta mahsulotda bir nechta barcode bo'lishi mumkin (upak/dona)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  barcode       text NOT NULL,
  pack_qty      numeric(14,3) NOT NULL DEFAULT 1,     -- bu barcode nechta birlikka teng
  is_primary    boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX uq_barcode ON product_barcodes(barcode);   -- barcode global unikal
CREATE INDEX idx_barcode_product ON product_barcodes(product_id);

CREATE TABLE product_prices (                -- NARX TARIXI (analitika uchun kritik)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  branch_id     uuid REFERENCES branches(id),          -- NULL = barcha filiallar
  kind          price_type NOT NULL,                    -- buy | sell
  price         numeric(14,2) NOT NULL,
  valid_from    timestamptz NOT NULL DEFAULT now(),
  valid_to      timestamptz,                            -- NULL = hozir amalda
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_prices_product ON product_prices(product_id, kind, valid_from DESC);

CREATE TABLE product_suppliers (             -- mahsulot ↔ yetkazib beruvchi (oxirgi narx)
  product_id    uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  supplier_id   uuid NOT NULL,               -- FK pastda (suppliers)
  supplier_sku  text,
  last_cost     numeric(14,2),
  PRIMARY KEY (product_id, supplier_id)
);


-- ===========================================================================
-- 4. OMBOR (inventory · movements · batches · counts · transfers)
-- ===========================================================================
CREATE TABLE inventory (                     -- joriy qoldiq (cache — movements yig'indisidan tiklanadi)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    uuid NOT NULL REFERENCES products(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  qty           numeric(14,3) NOT NULL DEFAULT 0,
  reserved_qty  numeric(14,3) NOT NULL DEFAULT 0,
  min_qty       numeric(14,3) NOT NULL DEFAULT 0,       -- kam qolgan chegarasi
  max_qty       numeric(14,3),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (product_id, branch_id)
);
CREATE INDEX idx_inventory_low ON inventory(branch_id) WHERE qty <= min_qty;

CREATE TABLE stock_batches (                 -- partiya (muddat/FEFO, tannarx)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    uuid NOT NULL REFERENCES products(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  batch_no      text,
  expiry_date   date,                        -- yaroqlilik muddati
  qty           numeric(14,3) NOT NULL DEFAULT 0,
  unit_cost     numeric(14,2) NOT NULL DEFAULT 0,
  received_at   timestamptz NOT NULL DEFAULT now(),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_batches_expiry ON stock_batches(expiry_date) WHERE qty > 0;
CREATE INDEX idx_batches_prod   ON stock_batches(product_id, branch_id);

CREATE TABLE stock_movements (               -- FAKT jadval: har harakat (immutable ledger)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    uuid NOT NULL REFERENCES products(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  batch_id      uuid REFERENCES stock_batches(id),
  type          movement_type NOT NULL,
  qty           numeric(14,3) NOT NULL,      -- kirim=+, chiqim=-
  unit_cost     numeric(14,2),              -- o'sha ondagi tannarx (analitika)
  balance_after numeric(14,3),              -- harakatdan keyingi qoldiq
  ref_type      text,                       -- 'sale'|'purchase'|'return'|'transfer'|'count'|'manual'
  ref_id        uuid,                       -- polimorf havola (FK yo'q)
  reason        text,
  employee_id   uuid REFERENCES employees(id),
  client_uuid   uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_moves_prod_time ON stock_movements(product_id, created_at DESC);
CREATE INDEX idx_moves_branch    ON stock_movements(branch_id, created_at DESC);
CREATE INDEX idx_moves_ref       ON stock_movements(ref_type, ref_id);

CREATE TABLE stock_counts (                  -- inventarizatsiya
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  status        text NOT NULL DEFAULT 'draft',   -- draft|completed|cancelled
  note          text,
  created_by    uuid REFERENCES employees(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);
CREATE TABLE stock_count_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  count_id      uuid NOT NULL REFERENCES stock_counts(id) ON DELETE CASCADE,
  product_id    uuid NOT NULL REFERENCES products(id),
  expected_qty  numeric(14,3) NOT NULL DEFAULT 0,
  counted_qty   numeric(14,3) NOT NULL DEFAULT 0,
  diff_qty      numeric(14,3) GENERATED ALWAYS AS (counted_qty - expected_qty) STORED
);

CREATE TABLE stock_transfers (               -- filiallararo ko'chirish
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_branch   uuid NOT NULL REFERENCES branches(id),
  to_branch     uuid NOT NULL REFERENCES branches(id),
  status        text NOT NULL DEFAULT 'draft',   -- draft|sent|received|cancelled
  created_by    uuid REFERENCES employees(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  received_at   timestamptz,
  row_version   bigint NOT NULL DEFAULT 1,
  CHECK (from_branch <> to_branch)
);
CREATE TABLE stock_transfer_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  transfer_id   uuid NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
  product_id    uuid NOT NULL REFERENCES products(id),
  qty           numeric(14,3) NOT NULL CHECK (qty > 0),
  unit_cost     numeric(14,2)
);


-- ===========================================================================
-- 5. XARIDLAR (suppliers · purchases · supplier payments/ledger)
-- ===========================================================================
CREATE TABLE suppliers (                     -- yetkazib beruvchi
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  name          text NOT NULL,
  phone         text,
  address       text,
  tax_id        text,
  balance       numeric(14,2) NOT NULL DEFAULT 0,   -- bizning qarz (cache, ledger'dan)
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  row_version   bigint NOT NULL DEFAULT 1
);

-- product_suppliers.supplier_id FK (endi suppliers mavjud)
ALTER TABLE product_suppliers
  ADD CONSTRAINT fk_prodsup_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE;

CREATE TABLE purchases (                     -- kirim hujjati (KIR-1042)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_no        text NOT NULL,
  company_id    uuid NOT NULL REFERENCES companies(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  supplier_id   uuid NOT NULL REFERENCES suppliers(id),
  employee_id   uuid REFERENCES employees(id),
  purchase_date date NOT NULL DEFAULT current_date,
  status        purchase_status NOT NULL DEFAULT 'received',
  currency      char(3) NOT NULL DEFAULT 'UZS',
  subtotal      numeric(14,2) NOT NULL DEFAULT 0,
  discount      numeric(14,2) NOT NULL DEFAULT 0,
  total         numeric(14,2) NOT NULL DEFAULT 0,
  paid_amount   numeric(14,2) NOT NULL DEFAULT 0,
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  deleted_at    timestamptz,
  client_uuid   uuid,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, doc_no)
);
CREATE INDEX idx_purchases_supplier ON purchases(supplier_id, purchase_date DESC);
CREATE INDEX idx_purchases_status   ON purchases(status);

CREATE TABLE purchase_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_id   uuid NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  product_id    uuid NOT NULL REFERENCES products(id),
  qty           numeric(14,3) NOT NULL CHECK (qty > 0),
  unit_cost     numeric(14,2) NOT NULL,
  line_total    numeric(14,2) NOT NULL,
  batch_id      uuid REFERENCES stock_batches(id),
  expiry_date   date
);
CREATE INDEX idx_purchase_items_prod ON purchase_items(product_id);

CREATE TABLE supplier_payments (             -- beruvchiga to'lov
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id   uuid NOT NULL REFERENCES suppliers(id),
  purchase_id   uuid REFERENCES purchases(id),
  amount        numeric(14,2) NOT NULL CHECK (amount > 0),
  method        text NOT NULL DEFAULT 'cash',
  paid_at       timestamptz NOT NULL DEFAULT now(),
  employee_id   uuid REFERENCES employees(id),
  note          text,
  client_uuid   uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_suppay_supplier ON supplier_payments(supplier_id, paid_at DESC);

CREATE TABLE supplier_ledger (               -- beruvchi qarz daftari
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id   uuid NOT NULL REFERENCES suppliers(id),
  type          credit_txn_type NOT NULL,    -- charge(xarid) | payment
  amount        numeric(14,2) NOT NULL,
  balance_after numeric(14,2) NOT NULL,
  ref_type      text, ref_id uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_supledger ON supplier_ledger(supplier_id, created_at);


-- ===========================================================================
-- 6. MIJOZLAR / QARZ (customers · credit · loyalty)
-- ===========================================================================
CREATE TABLE customer_groups (               -- segment / sadoqat darajasi
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  discount_pct  numeric(5,2) NOT NULL DEFAULT 0
);

CREATE TABLE customers (                     -- mijoz (M-1001)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  code          text NOT NULL,               -- M-1001
  full_name     text NOT NULL,
  phone         text,
  address       text,
  birth_date    date,
  group_id      uuid REFERENCES customer_groups(id),
  credit_balance numeric(14,2) NOT NULL DEFAULT 0,   -- joriy qarz (cache, ledger'dan)
  credit_limit  numeric(14,2),
  loyalty_points numeric(14,2) NOT NULL DEFAULT 0,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  deleted_at    timestamptz,
  client_uuid   uuid,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, code)
);
CREATE INDEX idx_customers_name  ON customers USING gin (full_name gin_trgm_ops);
CREATE INDEX idx_customers_phone ON customers(phone);
CREATE INDEX idx_customers_debt  ON customers(company_id) WHERE credit_balance > 0;

CREATE TABLE credit_transactions (           -- QARZ DAFTARI (source of truth)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   uuid NOT NULL REFERENCES customers(id),
  type          credit_txn_type NOT NULL,    -- charge(nasiya savdo) | payment | adjustment | writeoff
  amount        numeric(14,2) NOT NULL,      -- charge=+, payment=-
  balance_after numeric(14,2) NOT NULL,
  sale_id       uuid,                        -- charge manbai (FK pastda)
  payment_id    uuid,                        -- payment manbai
  employee_id   uuid REFERENCES employees(id),
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_credit_cust ON credit_transactions(customer_id, created_at);

CREATE TABLE customer_payments (             -- qarzni yopish (Qarzni yopish modali)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   uuid NOT NULL REFERENCES customers(id),
  amount        numeric(14,2) NOT NULL CHECK (amount > 0),
  method        text NOT NULL DEFAULT 'cash',
  paid_at       timestamptz NOT NULL DEFAULT now(),
  employee_id   uuid REFERENCES employees(id),
  branch_id     uuid REFERENCES branches(id),
  client_uuid   uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_custpay ON customer_payments(customer_id, paid_at DESC);

CREATE TABLE loyalty_transactions (          -- sadoqat ballari (kelajak)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   uuid NOT NULL REFERENCES customers(id),
  points        numeric(14,2) NOT NULL,      -- + to'plandi, - sarflandi
  sale_id       uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);


-- ===========================================================================
-- 7. SOZLAMALAR / TO'LOV (settings · payment_methods · tax · receipt)
-- ===========================================================================
CREATE TABLE payment_methods (               -- sozlanadigan to'lov usullari (Naqd/Karta/QR/Qarz)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  code          text NOT NULL,               -- cash|card|qr|credit
  name          text NOT NULL,
  is_enabled    boolean NOT NULL DEFAULT true,
  sort_order    int NOT NULL DEFAULT 0,
  config        jsonb NOT NULL DEFAULT '{}',
  UNIQUE (company_id, code)
);

CREATE TABLE tax_rates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  name          text NOT NULL,               -- QQS 12%
  rate          numeric(5,2) NOT NULL,
  is_default    boolean NOT NULL DEFAULT false
);

CREATE TABLE receipt_templates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  branch_id     uuid REFERENCES branches(id),
  header        text, footer text,
  show_barcode  boolean NOT NULL DEFAULT true,
  config        jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE settings (                      -- moslashuvchan scoped kalit-qiymat (JSONB)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  branch_id     uuid REFERENCES branches(id),   -- NULL = kompaniya darajasi
  key           text NOT NULL,                   -- 'features'|'payments'|'store_info'|'tax'|'receipt'
  value         jsonb NOT NULL DEFAULT '{}',
  updated_at    timestamptz NOT NULL DEFAULT now(),
  updated_by    uuid,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, branch_id, key)
);


-- ===========================================================================
-- 8. SMENA / KASSA (shifts · cash movements)
-- ===========================================================================
CREATE TABLE shifts (                        -- kassir smenasi
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  terminal_id   uuid REFERENCES terminals(id),
  cashier_id    uuid NOT NULL REFERENCES employees(id),
  opened_at     timestamptz NOT NULL DEFAULT now(),
  closed_at     timestamptz,
  opening_cash  numeric(14,2) NOT NULL DEFAULT 0,
  expected_cash numeric(14,2),               -- tizim hisobi
  counted_cash  numeric(14,2),               -- sanab chiqilgan
  difference    numeric(14,2),               -- counted - expected
  status        shift_status NOT NULL DEFAULT 'open',
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  client_uuid   uuid,
  row_version   bigint NOT NULL DEFAULT 1
);
CREATE INDEX idx_shifts_cashier ON shifts(cashier_id, opened_at DESC);
CREATE INDEX idx_shifts_open    ON shifts(branch_id) WHERE status = 'open';

CREATE TABLE cash_movements (                -- kassa kirim/chiqim (inkassatsiya, xarajat)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shift_id      uuid NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
  type          cash_movement_type NOT NULL,
  amount        numeric(14,2) NOT NULL,
  reason        text,
  employee_id   uuid REFERENCES employees(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_cashmov_shift ON cash_movements(shift_id);


-- ===========================================================================
-- 9. SOTUVLAR (sales · items · payments · discounts)
-- ===========================================================================
CREATE TABLE sales (                         -- chek (APPEND-ONLY — sync konflikti yo'q)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_no    text NOT NULL,               -- #1287
  uid           text,                        -- chek barcode uid (240816...)
  company_id    uuid NOT NULL REFERENCES companies(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  terminal_id   uuid REFERENCES terminals(id),
  cashier_id    uuid NOT NULL REFERENCES employees(id),
  shift_id      uuid REFERENCES shifts(id),
  customer_id   uuid REFERENCES customers(id),
  status        sale_status NOT NULL DEFAULT 'completed',
  currency      char(3) NOT NULL DEFAULT 'UZS',
  subtotal      numeric(14,2) NOT NULL,
  discount_total numeric(14,2) NOT NULL DEFAULT 0,
  tax_total     numeric(14,2) NOT NULL DEFAULT 0,
  total         numeric(14,2) NOT NULL,
  cost_total    numeric(14,2) NOT NULL DEFAULT 0,   -- tannarx yig'indisi (marja analitikasi)
  sold_at       timestamptz NOT NULL DEFAULT now(),
  is_offline    boolean NOT NULL DEFAULT false,     -- kassada offline yaratilganmi
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  client_uuid   uuid UNIQUE,                        -- offline idempotentlik (takror push himoyasi)
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, receipt_no)
);
CREATE INDEX idx_sales_time     ON sales(sold_at DESC);
CREATE INDEX idx_sales_branch   ON sales(branch_id, sold_at DESC);
CREATE INDEX idx_sales_cashier  ON sales(cashier_id, sold_at DESC);
CREATE INDEX idx_sales_customer ON sales(customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX idx_sales_shift    ON sales(shift_id);

CREATE TABLE sale_items (                    -- chek qatori (NARX/TANNARX SNAPSHOT)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_id       uuid NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  product_id    uuid NOT NULL REFERENCES products(id),
  name_snapshot text NOT NULL,               -- sotilgan ondagi nom
  article_snapshot text,
  qty           numeric(14,3) NOT NULL CHECK (qty > 0),
  unit_price    numeric(14,2) NOT NULL,      -- sotilgan ondagi narx (o'zgarmaydi)
  unit_cost     numeric(14,2) NOT NULL DEFAULT 0,   -- sotilgan ondagi tannarx (o'zgarmaydi)
  discount      numeric(14,2) NOT NULL DEFAULT 0,
  tax_rate      numeric(5,2) NOT NULL DEFAULT 0,
  line_total    numeric(14,2) NOT NULL,
  unit_id       uuid REFERENCES units(id)
);
CREATE INDEX idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX idx_sale_items_prod ON sale_items(product_id);

CREATE TABLE sale_payments (                 -- bir chekda bir nechta to'lov (split)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_id       uuid NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  method_code   text NOT NULL,               -- cash|card|qr|credit (payment_methods.code)
  amount        numeric(14,2) NOT NULL,
  given_amount  numeric(14,2),               -- berilgan (naqd)
  change_amount numeric(14,2),               -- qaytim
  txn_ref       text,                        -- karta/QR tranzaksiya ref
  paid_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_sale_pay_sale   ON sale_payments(sale_id);
CREATE INDEX idx_sale_pay_method ON sale_payments(method_code, paid_at);

CREATE TABLE sale_discounts (                -- chegirma detali (analitika)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_id       uuid NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  sale_item_id  uuid REFERENCES sale_items(id),   -- NULL = butun chekka
  kind          text NOT NULL,               -- percent|amount|promo
  value         numeric(14,2) NOT NULL,
  reason        text
);


-- ===========================================================================
-- 10. QAYTARISHLAR (returns · items)
-- ===========================================================================
CREATE TABLE returns (                       -- tovar qaytarish
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  return_no     text NOT NULL,
  original_sale_id uuid REFERENCES sales(id),
  company_id    uuid NOT NULL REFERENCES companies(id),
  branch_id     uuid NOT NULL REFERENCES branches(id),
  terminal_id   uuid REFERENCES terminals(id),
  cashier_id    uuid NOT NULL REFERENCES employees(id),
  customer_id   uuid REFERENCES customers(id),
  reason        return_reason NOT NULL DEFAULT 'customer',
  restock       boolean NOT NULL DEFAULT true,      -- true=omborga qaytdi, false=hisobdan chiqarildi
  refund_method text NOT NULL DEFAULT 'cash',       -- naqd|karta|qr|nasiya
  total         numeric(14,2) NOT NULL,
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  client_uuid   uuid UNIQUE,
  row_version   bigint NOT NULL DEFAULT 1,
  UNIQUE (company_id, return_no)
);
CREATE INDEX idx_returns_sale ON returns(original_sale_id);
CREATE INDEX idx_returns_time ON returns(created_at DESC);

CREATE TABLE return_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  return_id     uuid NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
  sale_item_id  uuid REFERENCES sale_items(id),
  product_id    uuid NOT NULL REFERENCES products(id),
  qty           numeric(14,3) NOT NULL CHECK (qty > 0),
  unit_price    numeric(14,2) NOT NULL,
  unit_cost     numeric(14,2) NOT NULL DEFAULT 0,
  line_total    numeric(14,2) NOT NULL
);
CREATE INDEX idx_return_items_ret ON return_items(return_id);

-- Kechiktirilgan FK'lar (sales endi mavjud)
ALTER TABLE credit_transactions ADD CONSTRAINT fk_credit_sale
  FOREIGN KEY (sale_id) REFERENCES sales(id);
ALTER TABLE credit_transactions ADD CONSTRAINT fk_credit_payment
  FOREIGN KEY (payment_id) REFERENCES customer_payments(id);
ALTER TABLE loyalty_transactions ADD CONSTRAINT fk_loyalty_sale
  FOREIGN KEY (sale_id) REFERENCES sales(id);


-- ===========================================================================
-- 11. IMPORT (1C / Excel / CSV — Mahsulotlar import ustasi)
-- ===========================================================================
CREATE TABLE import_jobs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id),
  source        text NOT NULL,               -- 1c|excel|csv
  file_name     text,
  status        import_status NOT NULL DEFAULT 'uploaded',
  column_mapping jsonb NOT NULL DEFAULT '{}', -- {"Artikul":"article_code", ...}
  total_rows    int NOT NULL DEFAULT 0,
  new_rows      int NOT NULL DEFAULT 0,
  existing_rows int NOT NULL DEFAULT 0,
  error_rows    int NOT NULL DEFAULT 0,
  created_by    uuid REFERENCES employees(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  committed_at  timestamptz
);
CREATE TABLE import_rows (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id        uuid NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
  row_no        int NOT NULL,
  raw           jsonb NOT NULL,              -- fayldagi asl qator
  parsed        jsonb,                       -- moslashtirilgan qiymatlar
  status        import_row_status NOT NULL DEFAULT 'new',
  error         text,
  product_id    uuid REFERENCES products(id)  -- commit'dan keyin
);
CREATE INDEX idx_import_rows_job ON import_rows(job_id, status);


-- ===========================================================================
-- 12. SYNC (devices · log · cursors) — offline-first
-- ===========================================================================
CREATE TABLE sync_devices (                  -- ro'yxatdan o'tgan kassa qurilmalari
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  terminal_id   uuid REFERENCES terminals(id),
  device_uuid   text UNIQUE NOT NULL,
  app_version   text,
  last_push_at  timestamptz,
  last_pull_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sync_log (                      -- har push/pull yozuvi (idempotentlik + audit)
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_uuid   text NOT NULL,
  direction     text NOT NULL,               -- push|pull
  entity        text NOT NULL,               -- 'sale'|'return'|'shift'|...
  entity_id     uuid,
  client_uuid   uuid,                        -- takror push aniqlash
  op            text,                        -- insert|update|delete
  status        text NOT NULL DEFAULT 'ok',  -- ok|duplicate|error
  message       text,
  received_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_sync_client ON sync_log(entity, client_uuid) WHERE client_uuid IS NOT NULL;
CREATE INDEX idx_sync_device ON sync_log(device_uuid, received_at DESC);

CREATE TABLE sync_cursors (                  -- qurilma qaysi vaqtgacha pull qilgan
  device_uuid   text NOT NULL,
  entity        text NOT NULL,
  last_pulled_at timestamptz NOT NULL DEFAULT 'epoch',
  PRIMARY KEY (device_uuid, entity)
);


-- ===========================================================================
-- 13. AUDIT (audit_log · activity_events)
-- ===========================================================================
CREATE TABLE audit_log (                     -- kim nimani o'zgartirdi (before/after)
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id      uuid REFERENCES employees(id),
  action        text NOT NULL,               -- create|update|delete|login|...
  entity        text NOT NULL,
  entity_id     uuid,
  before        jsonb,
  after         jsonb,
  ip            inet,
  terminal_id   uuid REFERENCES terminals(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log(entity, entity_id, created_at DESC);
CREATE INDEX idx_audit_actor  ON audit_log(actor_id, created_at DESC);

CREATE TABLE activity_events (               -- umumiy event-stream (analitika/ML uchun xom)
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type    text NOT NULL,
  branch_id     uuid,
  employee_id   uuid,
  payload       jsonb NOT NULL DEFAULT '{}',
  occurred_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_type ON activity_events(event_type, occurred_at DESC);


-- ===========================================================================
--  updated_at + row_version trigger'ni row_version ustuni bor jadvallarga ulash
-- ===========================================================================
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT table_name FROM information_schema.columns
    WHERE table_schema = 'public' AND column_name = 'row_version'
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_meta BEFORE UPDATE ON %1$I
       FOR EACH ROW EXECUTE FUNCTION set_row_meta();', t);
  END LOOP;
END $$;


-- ===========================================================================
--  HISOBOT KO'RINISHLARI (Dashboard / Hisobotlar sahifalarini quvvatlaydi)
--  Materialized — tez ochilishi uchun; CONCURRENTLY refresh (Celery/cron).
-- ===========================================================================

-- Kunlik savdo + foyda (Savdo dinamikasi grafigi, P&L)
CREATE MATERIALIZED VIEW mv_daily_sales AS
SELECT s.branch_id,
       date_trunc('day', s.sold_at)::date       AS day,
       count(*)                                  AS tx_count,
       sum(s.total)                              AS revenue,
       sum(s.cost_total)                         AS cost,
       sum(s.total - s.cost_total)               AS gross_profit,
       sum(s.discount_total)                     AS discount,
       sum(s.tax_total)                          AS tax
FROM sales s
WHERE s.status = 'completed'
GROUP BY s.branch_id, date_trunc('day', s.sold_at);
CREATE UNIQUE INDEX uq_mv_daily ON mv_daily_sales(branch_id, day);

-- Mahsulot bo'yicha foyda (Eng foydali mahsulotlar)
CREATE MATERIALIZED VIEW mv_product_profit AS
SELECT si.product_id,
       p.name,
       p.category_id,
       sum(si.qty)                               AS qty_sold,
       sum(si.line_total)                        AS revenue,
       sum(si.qty * si.unit_cost)                AS cost,
       sum(si.line_total - si.qty * si.unit_cost) AS profit
FROM sale_items si
JOIN sales s   ON s.id = si.sale_id AND s.status = 'completed'
JOIN products p ON p.id = si.product_id
GROUP BY si.product_id, p.name, p.category_id;
CREATE UNIQUE INDEX uq_mv_prodprofit ON mv_product_profit(product_id);

-- Kategoriya bo'yicha (Kategoriyalar bo'yicha panel)
CREATE MATERIALIZED VIEW mv_category_performance AS
SELECT c.id AS category_id, c.name,
       sum(si.line_total)                        AS sales,
       sum(si.line_total - si.qty * si.unit_cost) AS profit
FROM sale_items si
JOIN sales s     ON s.id = si.sale_id AND s.status = 'completed'
JOIN products p  ON p.id = si.product_id
JOIN categories c ON c.id = p.category_id
GROUP BY c.id, c.name;
CREATE UNIQUE INDEX uq_mv_catperf ON mv_category_performance(category_id);

-- To'lov usullari taqsimoti (Dashboard "To'lov usullari")
CREATE MATERIALIZED VIEW mv_payment_breakdown AS
SELECT sp.method_code,
       date_trunc('day', sp.paid_at)::date AS day,
       count(*) AS cnt,
       sum(sp.amount) AS amount
FROM sale_payments sp
GROUP BY sp.method_code, date_trunc('day', sp.paid_at);
CREATE UNIQUE INDEX uq_mv_paybreak ON mv_payment_breakdown(method_code, day);

-- Kam qolgan mahsulotlar (Dashboard / Ombor alertlari) — jonli view (yengil)
CREATE VIEW v_low_stock AS
SELECT i.branch_id, i.product_id, p.name, p.article_code,
       i.qty, i.min_qty
FROM inventory i
JOIN products p ON p.id = i.product_id
WHERE p.deleted_at IS NULL AND i.qty <= i.min_qty;

-- Muddati yaqin partiyalar (Dashboard "Muddati yaqin mahsulotlar")
CREATE VIEW v_expiring_soon AS
SELECT b.branch_id, b.product_id, p.name, b.expiry_date, b.qty,
       (b.expiry_date - current_date) AS days_left
FROM stock_batches b
JOIN products p ON p.id = b.product_id
WHERE b.qty > 0 AND b.expiry_date IS NOT NULL
  AND b.expiry_date <= current_date + INTERVAL '7 days'
ORDER BY b.expiry_date;

-- Qarzdor mijozlar (Dashboard qarz bloki / Mijozlar)
CREATE VIEW v_customer_debt AS
SELECT id AS customer_id, code, full_name, phone, credit_balance
FROM customers
WHERE deleted_at IS NULL AND credit_balance > 0;

-- ============================================================================
--  ESLATMA: OLAP yulduz-sxema (dim_* / fact_*) DuckDB/ClickHouse omborida —
--  ETL orqali shu OLTP jadvallaridan yig'iladi. Batafsil: db/README.md.
-- ============================================================================
