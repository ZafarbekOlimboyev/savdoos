#!/usr/bin/env bash
# SavdoOS · RESTORE REHEARSAL (tiklash mashqi)
#
# "Backup fayli bor" DEGANI "tiklanadi" DEGANI EMAS. Bu skript buni ISBOTLAYDI:
#     dump -> BIR MARTALIK baza -> tiklash -> butunlik -> barmoq izi solishtiruvi
#
# Ishlatish:
#     REHEARSAL_DATABASE_URL='postgresql://...bir_martalik_baza' \
#     BEFORE_FINGERPRINT=before.json \
#       ./scripts/restore_rehearsal.sh backups/savdoos-<vaqt>.dump
#
#   BEFORE_FINGERPRINT ixtiyoriy. Berilsa — tiklashdan keyingi barmoq izi bilan SOLISHTIRILADI
#   va farq bo'lsa RESTORE_REHEARSAL_FAILED. Berilmasa faqat tiklanish tekshiriladi.
#
# XAVFSIZLIK — eng muhimi:
#   * PRODUCTION USTIGA HECH QACHON TIKLAMAYDI. Maqsad baza `DATABASE_URL` bilan bir xil bo'lsa
#     yoki nomi production'ga o'xshasa — BOSH TORTADI.
#   * Maqsad baza BO'SH bo'lishi kerak (yoki --force bilan aniq tasdiqlansin).
set -Eeuo pipefail

DUMP="${1:-}"
fail() { echo "::error::$*" >&2; exit 1; }

# psql — PORTATIV chaqiruv. `psql "$URL" -tAc '...'` GNU getopt permutatsiyasiga tayanadi:
# Linux'da ishlaydi, Windows/macOS build'larida esa bayroq POZITSION argument deb qabul
# qilinadi va buyruq yiqiladi. Yiqilish JIM bo'lardi (`2>/dev/null || echo`), natijada
# metadata sxemalar ro'yxatini BO'SH yozardi va mashqning "baza bo'shmi" tekshiruvi
# HAR DOIM rad etardi. Shu bois bayroqlar DOIM satrdan oldin.
# PostgreSQL mijozini ANIQ tanlaymiz — backup bilan BIR XIL strategiya, aks holda
# nusxa PG18 bilan olinib, tiklash PG16 bilan urinilardi va zanjir yana uzilardi.
. "$(dirname "$0")/lib/pg_client.sh"
pg_client_resolve

_psql() {   # _psql <SQL> <URL>
  "$PSQL" -tAc "$1" "$2"
}

# Interpretator — CI'da oddiy `python`, mahalliy mashinada esa virtual muhitniki
# bo'lishi mumkin (tizim python'ida `psycopg` bo'lmasligi normal). PYTHON bilan bekor qilinadi.
PYTHON="${PYTHON:-python}"


[ -n "$DUMP" ] || fail "Foydalanish: restore_rehearsal.sh <dump-fayl>"
[ -f "$DUMP" ] || fail "dump topilmadi: $DUMP"
[ -n "${REHEARSAL_DATABASE_URL:-}" ] || fail "REHEARSAL_DATABASE_URL o'rnatilmagan."

# ── 1) PRODUCTION HIMOYASI ──────────────────────────────────────────────────
# Bu skript ma'lumot O'CHIRADI (pg_restore --clean). Noto'g'ri manzil = falokat.
if [ -n "${DATABASE_URL:-}" ] && [ "$REHEARSAL_DATABASE_URL" = "$DATABASE_URL" ]; then
  fail "RAD ETILDI: maqsad baza DATABASE_URL bilan BIR XIL. Mashq production ustiga tiklamaydi."
fi
case "$REHEARSAL_DATABASE_URL" in
  *prod*|*production*)
    [ "${ALLOW_PRODUCTION_TARGET:-}" = "yes-i-know" ] \
      || fail "RAD ETILDI: maqsad URL 'prod' so'zini o'z ichiga oladi. Bu mashq uchun BIR MARTALIK baza kerak." ;;
esac

# ── 2) Nazorat summasi (bor bo'lsa) ─────────────────────────────────────────
if [ -f "$DUMP.sha256" ]; then
  echo "== checksum tekshirilmoqda =="
  ( cd "$(dirname "$DUMP")" && \
    { command -v sha256sum >/dev/null 2>&1 && sha256sum -c "$(basename "$DUMP").sha256"; } || \
    { shasum -a 256 -c "$(basename "$DUMP").sha256"; } ) \
    || fail "checksum MOS EMAS — dump buzilgan, tiklash boshlanmadi."
else
  echo "::warning::checksum fayli yo'q ($DUMP.sha256) — butunlik isbotlanmadi."
fi

# ── 3) Maqsad baza bo'shmi ──────────────────────────────────────────────────
EXISTING="$(_psql   "SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','cash')"   "$REHEARSAL_DATABASE_URL" 2>/dev/null || echo 'ERR')"
[ "$EXISTING" != "ERR" ] || fail "maqsad bazaga ulanib bo'lmadi."
if [ "$EXISTING" != "0" ] && [ "${2:-}" != "--force" ]; then
  fail "maqsad baza BO'SH EMAS ($EXISTING jadval). Bir martalik bo'sh baza bering yoki --force."
fi

# ── 3b) YETISHMAYOTGAN ROLLARNI YARATISH (tiklashdan OLDIN) ────────────────
#
# NEGA BU SHART: rollar KLASTER darajasida yashaydi, BAZA ichida emas. `pg_dump` GRANT
# satrlarini oladi, LEKIN rollarning O'ZINI ololmaydi. Shu bois toza klasterga tiklashda
#     pg_restore: error: role "cash_posting" does not exist
# chiqadi va `--exit-on-error` butun tiklashni TO'XTATADI.
#
# Bu FALOKAT kunidagi eng yomon holat bo'lardi: nusxa bor, lekin u YANGI bazaga
# TUSHMAYDI. Aynan shu narsani mashq ushlab olishi kerak edi — va ushladi.
#
# Yechim: dump ichidagi GRANT/REVOKE qatorlaridan qabul qiluvchi rollarni ajratamiz va
# yo'qlarini NOLOGIN qilib yaratamiz (parolsiz, kirish huquqisiz — faqat GRANT nishoni).
# Ro'yxat dump'dan olinadi, ya'ni kelajakda yangi rol qo'shilsa ham o'zi topiladi.
echo "== yetishmayotgan rollar tekshirilmoqda =="
ROLE_LIST="$("$PG_RESTORE" -f - "$DUMP" 2>/dev/null \
  | grep -oE '(GRANT|REVOKE)[^;]* (TO|FROM) [A-Za-z_][A-Za-z0-9_]*' \
  | awk '{print $NF}' | sort -u \
  | grep -viE '^(public|current_user|session_user|current_role)$' || true)"

if [ -n "$ROLE_LIST" ]; then
  for role in $ROLE_LIST; do
    exists="$(_psql "SELECT count(*) FROM pg_roles WHERE rolname='$role'" \
      "$REHEARSAL_DATABASE_URL" 2>/dev/null || echo 0)"
    if [ "$exists" = "0" ]; then
      echo "  rol yaratilmoqda: $role (NOLOGIN)"
      _psql "CREATE ROLE \"$role\" NOLOGIN" "$REHEARSAL_DATABASE_URL" >/dev/null \
        || echo "::warning::rol yaratilmadi: $role"
    fi
  done
else
  echo "  dump'da rol grantlari topilmadi"
fi

# ── 3c) VERSIYA GARDI (maqsad server) ──────────────────────────────────────
# pg_restore ham serverdan eski bo'lmasligi kerak. Backup PG18 bilan olinib, tiklash
# PG16 bilan urinilsa zanjir aynan shu yerda uzilardi — buni OLDIN ushlaymiz.
pg_client_require_ge "$REHEARSAL_DATABASE_URL"

# ── 4) Tiklash ──────────────────────────────────────────────────────────────
echo "== pg_restore =="
# --clean --if-exists  qayta ishlatiladigan mashq bazasi uchun
# --no-owner           boshqa rol ostida ham tiklansin
# --exit-on-error      JIM qisman tiklash BO'LMASIN (asosiy talab)
"$PG_RESTORE" --clean --if-exists --no-owner --exit-on-error \
  -d "$REHEARSAL_DATABASE_URL" "$DUMP" \
  || fail "pg_restore yiqildi — RESTORE_REHEARSAL_FAILED."

# ── 5) Butunlik: sxema + FK ─────────────────────────────────────────────────
echo "== butunlik tekshiruvi =="
CASH_OK="$(_psql "SELECT count(*) FROM information_schema.schemata    WHERE schema_name='cash'" "$REHEARSAL_DATABASE_URL")"
FKS="$(_psql "SELECT count(*) FROM information_schema.table_constraints    WHERE constraint_type='FOREIGN KEY' AND constraint_schema IN ('public','cash')"    "$REHEARSAL_DATABASE_URL")"
echo "cash schema: $CASH_OK · foreign keys: $FKS"
[ "$FKS" -gt 0 ] || fail "tiklangan bazada FOREIGN KEY YO'Q — bog'lanishlar yo'qolgan (jim buzilish)."

# ── 6) Barmoq izi + solishtirish ────────────────────────────────────────────
echo "== barmoq izi =="
AFTER="${AFTER_FINGERPRINT:-after-fingerprint.json}"

# MUTLAQ yo'lga aylantiramiz: quyida `cd apps/server` qilinadi, shu bois nisbiy yo'l
# noto'g'ri katalogga ishora qilardi (operator mutlaq yo'l bergan bo'lsa ham buzilardi).
_abs() {
  case "$1" in
    /*|[A-Za-z]:*) printf '%s
' "$1" ;;
    *)             printf '%s/%s
' "$(pwd)" "$1" ;;
  esac
}
AFTER_ABS="$(_abs "$AFTER")"

( cd apps/server && DATABASE_URL="$REHEARSAL_DATABASE_URL"     "$PYTHON" -m app.tools.db_fingerprint --json ) > "$AFTER_ABS"   || fail "barmoq izi olinmadi."
echo "yozildi: $AFTER_ABS"

if [ -n "${BEFORE_FINGERPRINT:-}" ]; then
  BEFORE_ABS="$(_abs "$BEFORE_FINGERPRINT")"
  [ -f "$BEFORE_ABS" ] || fail "BEFORE_FINGERPRINT topilmadi: $BEFORE_ABS"
  echo "== solishtirish (before vs after) =="
  ( cd apps/server && "$PYTHON" -m app.tools.db_fingerprint       --compare "$BEFORE_ABS" "$AFTER_ABS" )     || fail "RESTORE_REHEARSAL_FAILED — barmoq izi MOS EMAS (yuqoridagi farqlarga qarang)."
  echo "RESTORE_REHEARSAL_OK — sanoqlar va summalar MOS."
else
  echo "::warning::BEFORE_FINGERPRINT berilmadi — tiklanish tasdiqlandi, LEKIN to'liqlik solishtirilmadi."
fi

echo "TAYYOR."
