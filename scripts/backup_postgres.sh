#!/usr/bin/env bash
# SavdoOS · PostgreSQL backup (operator skripti)
#
# Ishlatish:
#     DATABASE_URL='postgresql://...' ./scripts/backup_postgres.sh [CHIQISH_KATALOGI]
#
# Chiqadi (CHIQISH_KATALOGI, standart: ./backups):
#     savdoos-<UTC-vaqt>.dump         pg_dump -Fc (custom format: schema + data, public + cash)
#     savdoos-<UTC-vaqt>.dump.sha256  nazorat summasi
#     savdoos-<UTC-vaqt>.meta.json    metadata (vaqt, hajm, checksum, pg versiyasi, sxemalar)
#
# XAVFSIZLIK:
#   - DATABASE_URL FAQAT muhit o'zgaruvchisidan olinadi; hech qachon repoga yozilmaydi.
#   - URL/parol NEChIQARILMAYDI: loglarda faqat host yashirilgan "<db-nomi>" ko'rinadi.
#   - metadata ichida ULANISH SATRI YO'Q (talab: backup artefakti sirni tashimasin).
#   - Har xatoda NOL BO'LMAGAN kod bilan yiqiladi (jim muvaffaqiyat YO'Q).
set -Eeuo pipefail

OUT_DIR="${1:-./backups}"
MIN_BYTES="${SAVDOOS_BACKUP_MIN_BYTES:-20000}"

fail() { echo "::error::$*" >&2; exit 1; }

[ -n "${DATABASE_URL:-}" ] || fail "DATABASE_URL o'rnatilmagan — backup OLINMADI. \
Bu JIM o'tkazib yuborilmaydi: backup yo'qligi backup bor deb ko'rsatilmasligi kerak."

command -v pg_dump >/dev/null 2>&1 || fail "pg_dump topilmadi. PostgreSQL client kerak \
(masalan: docker run --rm postgres:17 pg_dump ...)."

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$OUT_DIR/savdoos-$STAMP"
DUMP="$BASE.dump"

# Baza nomi — SIRSIZ etiketka (host/user/parol chiqmaydi)
DBNAME="$(psql "$DATABASE_URL" -tAc 'SELECT current_database()' 2>/dev/null || echo '<unknown>')"
PGVER="$(psql "$DATABASE_URL" -tAc 'SHOW server_version' 2>/dev/null || echo '<unknown>')"
SCHEMAS="$(psql "$DATABASE_URL" -tAc \
  "SELECT string_agg(schema_name,',' ORDER BY schema_name) FROM information_schema.schemata \
   WHERE schema_name IN ('public','cash')" 2>/dev/null || echo '<unknown>')"

echo "SavdoOS backup · target=$DBNAME · pg=$PGVER · schemas=$SCHEMAS"

# -Fc  custom format (pg_restore uchun, siqilgan, tanlab tiklash mumkin)
# --no-owner  tiklashda boshqa rol ostida ham ishlasin
# Sxema CHEKLANMAYDI: public VA cash (va kelajakdagilar) to'liq tushadi.
pg_dump "$DATABASE_URL" -Fc --no-owner -f "$DUMP" \
  || fail "pg_dump yiqildi — backup OLINMADI."

[ -s "$DUMP" ] || fail "dump fayli bo'sh — backup YAROQSIZ."
SIZE="$(wc -c < "$DUMP" | tr -d ' ')"
[ "$SIZE" -ge "$MIN_BYTES" ] \
  || fail "dump juda kichik ($SIZE bayt < $MIN_BYTES) — baza bo'shmi yoki ulanish xatomi?"

# pg_restore -l dump'ni O'QIB ko'radi: sintaktik butunlikni TASDIQLAYDI (shunchaki hajm emas).
pg_restore -l "$DUMP" >/dev/null 2>&1 \
  || fail "dump o'qib bo'lmadi (pg_restore -l yiqildi) — fayl BUZUQ."
OBJECTS="$(pg_restore -l "$DUMP" 2>/dev/null | grep -c '^[0-9]' || echo 0)"

# Nazorat summasi — tiklashdan oldin fayl butunligini isbotlaydi
if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$DUMP" | awk '{print $1}')"
else
  SHA="$(shasum -a 256 "$DUMP" | awk '{print $1}')"
fi
echo "$SHA  $(basename "$DUMP")" > "$DUMP.sha256"

cat > "$BASE.meta.json" <<META
{
  "tool": "savdoos/scripts/backup_postgres.sh",
  "created_at_utc": "$STAMP",
  "database": "$DBNAME",
  "server_version": "$PGVER",
  "schemas_present": "$SCHEMAS",
  "format": "pg_dump -Fc --no-owner",
  "file": "$(basename "$DUMP")",
  "size_bytes": $SIZE,
  "toc_objects": $OBJECTS,
  "sha256": "$SHA",
  "restore_command": "pg_restore --clean --if-exists --no-owner -d <TARGET_DATABASE_URL> $(basename "$DUMP")",
  "note": "Ulanish satri ATAYLAB bu yerda YO'Q. Tiklash uchun URL operator muhitidan beriladi."
}
META

echo "OK · $DUMP ($SIZE bayt, $OBJECTS obyekt)"
echo "OK · sha256=$SHA"
echo "OK · $BASE.meta.json"
