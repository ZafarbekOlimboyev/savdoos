#!/usr/bin/env bash
# SavdoOS · Artefaktga chiqadigan fayllarni SHIFRLASH — va shifrni TEKSHIRISH.
#
# Ishlatish:
#     BACKUP_PASSPHRASE='...' ./scripts/encrypt_evidence.sh fayl1 [fayl2 ...]
#
# Har fayl uchun:  <fayl> -> <fayl>.gpg,  so'ng ochib sha256 bilan SOLISHTIRILADI,
# va faqat SHUNDAN KEYIN ochiq nusxa o'chiriladi.
#
# ═══ NEGA ALOHIDA SKRIPT ═════════════════════════════════════════════════════
# Shifrlash uch joyda kerak: `_db-backup-core.yml` (nusxa + barmoq izlari) va
# `restore-rehearsal.yml` ning IKKALA job'i (mashq dalillari). Uch nusxa = uch xil
# drift. Bu repo aynan shundan jabr ko'rgan: `pg_client.sh` da versiya parseri
# tuzatilgan, `action.yml` dagi NUSXASI esa yo'q — va birinchi haqiqiy production
# backup'i "major=2, expected=18" bilan yiqilgan.
#
# ═══ NEGA SHUNCHAKI `gpg` CHAQIRUVI YETARLI EMAS ════════════════════════════
# Talab: "Encryption must be verified before upload" va "Fail closed when encryption
# is unavailable". Ochiq faylni gpg chiqish kodiga ishonib o'chirish ikki xil jimgina
# nuqson beradi:
#   1. `gpg` UMUMAN o'rnatilmagan bo'lsa — buyruq topilmaydi, `|| true` yo'q bo'lsa
#      qadam yiqiladi, LEKIN `if: always()` li yuklash qadami baribir ishga tushadi va
#      hech narsa yuklamay "warn" bilan o'tib ketadi: mashq YASHIL, dalil YO'Q.
#   2. gpg chiqish kodi 0 bo'lsa ham fayl buzuq bo'lishi mumkin (disk to'lgan, oqim
#      uzilgan). Bunda ochiq nusxa o'chadi, shifrlangani esa OCHILMAYDI — ya'ni
#      falokat kunida nusxa bor ko'rinadi, lekin yo'q.
# Shu bois: mavjudlik + parol QAT'IY tekshiriladi, va har fayl ochib qaytarilib
# sha256 solishtiriladi. Solishtiruv o'tmasa — ochiq nusxa O'CHIRILMAYDI va skript
# NOL BO'LMAGAN kod bilan yiqiladi.
#
# XAVFSIZLIK:
#   · Parol buyruq satriga QO'YILMAYDI — `--passphrase-fd 0` orqali stdin bilan
#     beriladi, ya'ni runner'ning jarayonlar ro'yxatida ko'rinmaydi.
#   · Fayl TARKIBI hech qachon chop etilmaydi — faqat nom va hajm.
set -Eeuo pipefail

fail() { echo "::error::$*" >&2; exit 1; }

[ "$#" -gt 0 ] || fail "Foydalanish: encrypt_evidence.sh <fayl> [fayl ...]"

# ── FAIL CLOSED: shifrlash imkoni yo'q bo'lsa hech narsa qilinmaydi ──────────
command -v gpg >/dev/null 2>&1 \
  || fail "gpg TOPILMADI — shifrlash imkonsiz. Ochiq fayllar O'CHIRILMADI va \
artefaktga CHIQMAYDI (yuklash yo'llari faqat *.gpg ni oladi)."
[ -n "${BACKUP_PASSPHRASE:-}" ] \
  || fail "BACKUP_PASSPHRASE bo'sh — shifrlanmagan dalil YUKLANMAYDI."

_sha() {   # _sha <fayl> -> sof o'n oltilik
  # Katalog ichida, FAQAT fayl nomi bilan: GNU coreutils yo'lda teskari slash
  # ko'rsa "escape" rejimiga o'tadi va satr boshiga `\` qo'yadi (Windows/Git Bash).
  ( cd "$(dirname "$1")" && {
      if command -v sha256sum >/dev/null 2>&1; then sha256sum "$(basename "$1")"
      else shasum -a 256 "$(basename "$1")"; fi
    } | awk '{print $1}' )
}

encrypted=0
skipped=0
for f in "$@"; do
  if [ ! -f "$f" ]; then
    # Yo'q fayl xato EMAS: job'ga qarab ba'zi dalillar umuman yaratilmaydi.
    skipped=$((skipped + 1))
    continue
  fi

  before="$(_sha "$f")"
  # ⚠️  Shaklni tekshiramiz. Checksum vositasi 0 qaytarib BO'SH natija bersa
  #     (masalan buzilgan PATH), `before` va `after` ikkalasi ham bo'sh bo'lardi va
  #     "teng" chiqib, ochiq nusxa o'chib ketardi — ya'ni tekshiruv BEKORGA ishlardi.
  #     `backup_postgres.sh` da bu tekshiruv bor edi, bu skriptda esa yo'q edi.
  case "$before" in
    *[!0-9a-f]* | "") fail "checksum kutilmagan ko'rinishda: $f — shifrlash boshlanmadi." ;;
  esac

  printf '%s' "$BACKUP_PASSPHRASE" | gpg --batch --yes --quiet \
      --symmetric --cipher-algo AES256 --passphrase-fd 0 \
      -o "$f.gpg" "$f" \
    || fail "shifrlash yiqildi: $f (ochiq nusxa O'CHIRILMADI)"

  [ -s "$f.gpg" ] || fail "shifrlangan fayl BO'SH: $f.gpg"

  # ── TEKSHIRUV: ochib, asl bilan bit-ba-bit solishtiramiz ──────────────────
  check="$f.verify.tmp"
  printf '%s' "$BACKUP_PASSPHRASE" | gpg --batch --yes --quiet \
      --passphrase-fd 0 -o "$check" -d "$f.gpg" \
    || { rm -f "$check"; fail "shifrni OCHIB BO'LMADI: $f.gpg (ochiq nusxa saqlandi)"; }

  after="$(_sha "$check")"
  rm -f "$check"
  case "$after" in
    *[!0-9a-f]* | "") fail "ochilgan nusxaning checksum'i kutilmagan ko'rinishda: $f" ;;
  esac
  [ "$before" = "$after" ] \
    || fail "shifrlash/ochish MOS KELMADI: $f — nusxa YAROQSIZ (ochiq nusxa saqlandi)"

  # Faqat SHU YERDA ochiq nusxa o'chiriladi.
  rm -f "$f"
  encrypted=$((encrypted + 1))
  echo "shifrlandi va tekshirildi: $f.gpg ($(wc -c < "$f.gpg") bayt)"
done

echo "JAMI: $encrypted ta shifrlandi, $skipped ta fayl yo'q edi"
[ "$encrypted" -gt 0 ] || fail "birorta fayl ham shifrlanmadi — kutilgan dalillar YO'Q."
