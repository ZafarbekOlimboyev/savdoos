# SavdoOS — zaxira (backup) va tiklash runbook

Mijoz ma'lumoti (savdolar, mahsulotlar, qarzlar) — eng qimmatli narsa. Uni yo'qotmaslik
uchun **ikki qatlam** tavsiya etiladi.

## 1-qatlam (ASOSIY): Railway Postgres avtomatik zaxira

Eng ishonchli — Railway'ning o'zi. Bir marta yoqiladi, keyin avtomatik ishlaydi:

1. Railway → loyiha **trustworthy-enchantment** → **Postgres-d29B** servisi.
2. **Backups** bo'limi → **Enable automatic backups** (kunlik).
3. Kerak bo'lganда shu yerдан **Restore** qilinadi (snapshotdan).

> Bu — off-site, boshqarилadigan zaxira. Serverга hech narsa o'rnatish shart emas.

## 2-qatlam (QO'SHIMCHA): qo'lda / jadvalli dump — `tools/backup.py`

Muhim voqealardан oldin (katta import, migratsiya, versiya yangilash) qo'lда to'liq
nusxa oling. Fayl **boshqa joyга** (tashqi disk, Google Drive) ko'chirilsin.

```bash
# Railway CLI orqali (env avtomatik) — apps/server ичida:
railway run --service savdoos python tools/backup.py

# yoki to'g'ridan-to'g'ri (postgresql-client / pg_dump kerak):
DATABASE_URL="postgresql://user:pass@host:5432/db" python tools/backup.py
```

Natija: `backups/savdoos_YYYYMMDD_HHMMSS.sql` (Postgres) yoki `.db` nusxa (SQLite).

### Tiklash (restore)

```bash
# Postgres (dump'дан):
psql "$DATABASE_URL" < backups/savdoos_YYYYMMDD_HHMMSS.sql

# SQLite: nusxani joyiga qo'ying
cp backups/savdoos_YYYYMMDD_HHMMSS.db savdoos.db
```

## Nimani zaxira qilamiz / qilmaymiz

- **Zaxira:** butun Postgres bazasi (barcha do'konlar — multi-tenant bitta bazада).
- **Zaxira EMAS:** `.env` sirlari (ular Railway Variables'да), `node_modules`, `release/`.
  Sirlarni alohida, xavfsiz joyда saqlang (parol menejeri).

## Maslahatlar

- Dump fayllar **shaxsiy ma'lumot** — ochiq (GitHub artifact, umumiy disk) joyга qo'ymang.
- Kamida **oyда bir marta** tiklashни sinab ko'ring (zaxira ishlashiga ishonch).
- Katta o'zgarishdан oldin doim qo'лда bitta dump oling.
