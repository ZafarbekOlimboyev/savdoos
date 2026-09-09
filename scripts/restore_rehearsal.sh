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
EXISTING="$(psql "$REHEARSAL_DATABASE_URL" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','cash')" \
  2>/dev/null || echo 'ERR')"
[ "$EXISTING" != "ERR" ] || fail "maqsad bazaga ulanib bo'lmadi."
if [ "$EXISTING" != "0" ] && [ "${2:-}" != "--force" ]; then
  fail "maqsad baza BO'SH EMAS ($EXISTING jadval). Bir martalik bo'sh baza bering yoki --force."
fi

# ── 4) Tiklash ──────────────────────────────────────────────────────────────
echo "== pg_restore =="
# --clean --if-exists  qayta ishlatiladigan mashq bazasi uchun
# --no-owner           boshqa rol ostida ham tiklansin
# --exit-on-error      JIM qisman tiklash BO'LMASIN (asosiy talab)
pg_restore --clean --if-exists --no-owner --exit-on-error \
  -d "$REHEARSAL_DATABASE_URL" "$DUMP" \
  || fail "pg_restore yiqildi — RESTORE_REHEARSAL_FAILED."

# ── 5) Butunlik: sxema + FK ─────────────────────────────────────────────────
echo "== butunlik tekshiruvi =="
CASH_OK="$(psql "$REHEARSAL_DATABASE_URL" -tAc \
  "SELECT count(*) FROM information_schema.schemata WHERE schema_name='cash'")"
FKS="$(psql "$REHEARSAL_DATABASE_URL" -tAc \
  "SELECT count(*) FROM information_schema.table_constraints \
   WHERE constraint_type='FOREIGN KEY' AND constraint_schema IN ('public','cash')")"
echo "cash schema: $CASH_OK · foreign keys: $FKS"
[ "$FKS" -gt 0 ] || fail "tiklangan bazada FOREIGN KEY YO'Q — bog'lanishlar yo'qolgan (jim buzilish)."

# ── 6) Barmoq izi + solishtirish ────────────────────────────────────────────
echo "== barmoq izi =="
AFTER="${AFTER_FINGERPRINT:-after-fingerprint.json}"
( cd apps/server && DATABASE_URL="$REHEARSAL_DATABASE_URL" \
    python -m app.tools.db_fingerprint --json ) > "$AFTER" \
  || fail "barmoq izi olinmadi."
echo "yozildi: $AFTER"

if [ -n "${BEFORE_FINGERPRINT:-}" ]; then
  [ -f "$BEFORE_FINGERPRINT" ] || fail "BEFORE_FINGERPRINT topilmadi: $BEFORE_FINGERPRINT"
  echo "== solishtirish (before vs after) =="
  ( cd apps/server && python -m app.tools.db_fingerprint \
      --compare "../../$BEFORE_FINGERPRINT" "../../$AFTER" ) \
    || fail "RESTORE_REHEARSAL_FAILED — barmoq izi MOS EMAS (yuqoridagi farqlarga qarang)."
  echo "RESTORE_REHEARSAL_OK — sanoqlar va summalar MOS."
else
  echo "::warning::BEFORE_FINGERPRINT berilmadi — tiklanish tasdiqlandi, LEKIN to'liqlik solishtirilmadi."
fi

echo "TAYYOR."
