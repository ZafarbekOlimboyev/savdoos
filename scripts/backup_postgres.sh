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

# PostgreSQL mijozini ANIQ tanlaymiz (PATH'dagi pg_dump Debian'da pg_wrapper bo'lishi va
# ESKI versiyani tanlashi mumkin — birinchi haqiqiy backup aynan shundan yiqilgan edi).
. "$(dirname "$0")/lib/pg_client.sh"
pg_client_resolve

# psql — PORTATIV chaqiruv. `psql "$URL" -tAc '...'` GNU getopt permutatsiyasiga tayanadi:
# Linux'da ishlaydi, Windows/macOS build'larida esa bayroq POZITSION argument deb qabul
# qilinadi va buyruq yiqiladi. Yiqilish JIM bo'lardi (`2>/dev/null || echo`), natijada
# metadata sxemalar ro'yxatini BO'SH yozardi va mashqning "baza bo'shmi" tekshiruvi
# HAR DOIM rad etardi. Shu bois bayroqlar DOIM satrdan oldin.
_psql() {   # _psql <SQL> <URL>
  "$PSQL" -tAc "$1" "$2"
}

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$OUT_DIR/savdoos-$STAMP"
DUMP="$BASE.dump"

# Baza nomi — SIRSIZ etiketka (host/user/parol chiqmaydi)
DBNAME="$(_psql 'SELECT current_database()' "$DATABASE_URL" 2>/dev/null || echo '<unknown>')"
PGVER="$(_psql 'SHOW server_version' "$DATABASE_URL" 2>/dev/null || echo '<unknown>')"
SCHEMAS="$(_psql "SELECT string_agg(schema_name,',' ORDER BY schema_name)    FROM information_schema.schemata WHERE schema_name IN ('public','cash')"    "$DATABASE_URL" 2>/dev/null || echo '<unknown>')"

echo "SavdoOS backup · target=$DBNAME · pg=$PGVER · schemas=$SCHEMAS"

# ── VERSIYA GARDI: mijoz serverdan ESKI bo'lsa DUMP UMUMAN BOSHLANMAYDI ────
# pg_dump eski bo'lsa yarim-yozilgan fayl qoldirmaydi, lekin xato JIM ketmasin:
# sabab aniq ko'rsatilsin, aks holda operator "nega artefakt yo'q?" deb qidiradi.
pg_client_require_ge "$DATABASE_URL"

# -Fc  custom format (pg_restore uchun, siqilgan, tanlab tiklash mumkin)
# --no-owner  tiklashda boshqa rol ostida ham ishlasin
# Sxema CHEKLANMAYDI: public VA cash (va kelajakdagilar) to'liq tushadi.
# DIQQAT — ARGUMENT TARTIBI: bayroqlar ulanish satridan OLDIN keladi.
# `pg_dump "$URL" -Fc ...` GNU getopt permutatsiyasiga tayanadi (Linux'da ishlaydi), lekin
# Windows/macOS build'larida bayroq ikkinchi POZITSION argument deb qabul qilinib
# "too many command-line arguments" xatosi chiqadi. Operator skriptni istalgan mashinada
# ishlatishi kerak, shu bois portativ tartib.
"$PG_DUMP" -Fc --no-owner -f "$DUMP" "$DATABASE_URL" \
  || fail "pg_dump yiqildi — backup OLINMADI."

[ -s "$DUMP" ] || fail "dump fayli bo'sh — backup YAROQSIZ."
SIZE="$(wc -c < "$DUMP" | tr -d ' ')"
[ "$SIZE" -ge "$MIN_BYTES" ] \
  || fail "dump juda kichik ($SIZE bayt < $MIN_BYTES) — baza bo'shmi yoki ulanish xatomi?"

# pg_restore -l dump'ni O'QIB ko'radi: sintaktik butunlikni TASDIQLAYDI (shunchaki hajm emas).
"$PG_RESTORE" -l "$DUMP" >/dev/null 2>&1 \
  || fail "dump o'qib bo'lmadi (pg_restore -l yiqildi) — fayl BUZUQ."
OBJECTS="$("$PG_RESTORE" -l "$DUMP" 2>/dev/null | grep -c '^[0-9]' || echo 0)"

# Nazorat summasi — tiklashdan oldin fayl butunligini isbotlaydi.
#
# DIQQAT: hisoblash KATALOG ICHIDA, faqat FAYL NOMI bilan bajariladi. Sababi — GNU
# coreutils fayl nomida teskari slash yoki yangi qator bo'lsa "escape" rejimiga o'tadi
# va SATR BOSHIGA teskari slash qo'yadi. Windows/Git Bash'da yo'l diskdan boshlanadi
# (C: ... ) va ajratuvchisi teskari slash, shu bois
#   sha256sum "$DUMP" | awk '{print $1}'
# qiymati boshida ortiqcha belgi bilan chiqardi. Natijada:
#   · metadata JSON'i BUZILARDI ("Invalid escape"),
#   · saqlangan checksum qiymati ham NOTO'G'RI bo'lardi.
# Fayl nomida ajratuvchi bo'lmasa escape rejimi umuman yoqilmaydi.
DUMP_NAME="$(basename "$DUMP")"
SHA="$(cd "$OUT_DIR" && {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$DUMP_NAME"
  else
    shasum -a 256 "$DUMP_NAME"
  fi
} | awk '{print $1}')"

# Kutilgan ko'rinish — sof o'n oltilik (64 belgi). Aks holda metadata yozilmaydi.
case "$SHA" in
  *[!0-9a-f]* | "") fail "checksum kutilmagan ko'rinishda — metadata yozilmadi." ;;
esac
echo "$SHA  $DUMP_NAME" > "$DUMP.sha256"

cat > "$BASE.meta.json" <<META
{
  "tool": "savdoos/scripts/backup_postgres.sh",
  "created_at_utc": "$STAMP",
  "database": "$DBNAME",
  "server_version": "$PGVER",
  "pg_dump_version": "$($PG_DUMP --version 2>/dev/null | head -1)",
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
