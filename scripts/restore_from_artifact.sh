#!/usr/bin/env bash
# SavdoOS · SAQLANGAN backup ARTEFAKTIDAN tiklash mashqi.
#
# ═══ NEGA ALOHIDA YO'L ══════════════════════════════════════════════════════
# `restore_rehearsal.sh` production'dan YANGI dump olib, uni tiklaydi. Bu tiklash
# MEXANIZMINI isbotlaydi, LEKIN falokat kunida ishlatiladigan narsani — GitHub'da
# SAQLANGAN artefaktni — isbotlamaydi. Haqiqiy savol boshqa:
#
#     "O'sha tundagi artefaktni yuklab olib, ochib, tiklab bo'ladimi?"
#
# Bu skript AYNAN shunga javob beradi: artefakt YAGONA haqiqat manbai.
# Yangi dump olishga QAYTMAYDI — aks holda mashq o'zini o'zi aldab, "artefakt
# yaroqli" degan yolg'on xulosa berardi.
#
# Ishlatish:
#     BACKUP_PASSPHRASE=... \
#     REHEARSAL_DATABASE_URL='postgresql://...localhost...' \
#       ./scripts/restore_from_artifact.sh <artefakt-katalogi>
#
# Ixtiyoriy: PYTHON, PG_BIN, KEEP_PLAINTEXT=1 (nosozlikni tekshirish uchun).
set -Eeuo pipefail

ART_DIR="${1:-}"
fail() { echo "::error::$*" >&2; exit 1; }

# ── Ochiq dump HAR QANDAY holatda o'chiriladi (xato/uzilishda ham) ──────────
# Ochiq nusxa — barcha do'konlarning mijozlari, qarzlari va naqd ledgeri. U runner
# fayl tizimida bir soniya ham keragidan ortiq turmasligi kerak.
PLAINTEXT=""
cleanup() {
  if [ -n "$PLAINTEXT" ] && [ -f "$PLAINTEXT" ] && [ "${KEEP_PLAINTEXT:-}" != "1" ]; then
    rm -f "$PLAINTEXT"
    echo "tozalandi: ochiq dump o'chirildi"
  fi
}
trap cleanup EXIT INT TERM

[ -n "$ART_DIR" ] || fail "Foydalanish: restore_from_artifact.sh <artefakt-katalogi>"
[ -d "$ART_DIR" ] || fail "artefakt katalogi topilmadi: $ART_DIR"
[ -n "${BACKUP_PASSPHRASE:-}" ] || fail "BACKUP_PASSPHRASE berilmagan — shifrni ochib bo'lmaydi."
[ -n "${REHEARSAL_DATABASE_URL:-}" ] || fail "REHEARSAL_DATABASE_URL berilmagan."

HERE="$(cd "$(dirname "$0")" && pwd)"

# ── 1) MAQSAD XAVFSIZ EKANINI TASDIQLASH — ENG BIRINCHI ────────────────────
# DIQQAT — TARTIB: bu tekshiruv PostgreSQL vositalarini topishdan ham OLDIN turadi.
# Ilgari `pg_client_resolve` birinchi edi va mijoz binari topilmagan mashinada skript
# gardlarga YETIB BORMASDAN to'xtardi. Ya'ni "noto'g'ri manzil rad etiladi" degan
# kafolat muhitga bog'liq bo'lib qolardi. Xavfsizlik hech qachon atrof-muhit
# sozlamasiga bog'liq bo'lmasligi kerak.
# Bu skript ma'lumot O'CHIRADI (pg_restore --clean). Noto'g'ri manzil = falokat.
# Tekshiruv shu yerda ham bor, `restore_rehearsal.sh` da ham — ATAYLAB ikki qatlam:
# bu skript kelajakda boshqa joydan chaqirilsa ham himoya yo'qolmasin.
if [ -n "${DATABASE_URL:-}" ] && [ "$REHEARSAL_DATABASE_URL" = "$DATABASE_URL" ]; then
  fail "RAD ETILDI: maqsad baza DATABASE_URL bilan BIR XIL. Artefakt production ustiga TIKLANMAYDI."
fi
if [ -n "${PROD_DATABASE_URL:-}" ] && [ "$REHEARSAL_DATABASE_URL" = "$PROD_DATABASE_URL" ]; then
  fail "RAD ETILDI: maqsad baza PROD_DATABASE_URL bilan BIR XIL."
fi
case "$REHEARSAL_DATABASE_URL" in
  *localhost*|*127.0.0.1*) : ;;   # bir martalik konteyner — YAGONA ruxsat etilgan shakl
  *) fail "RAD ETILDI: maqsad localhost/127.0.0.1 BO'LISHI SHART (bir martalik mashq bazasi). \
Berilgan manzil masofaviy ko'rinadi." ;;
esac
case "$REHEARSAL_DATABASE_URL" in
  *prod*|*production*|*rlwy.net*|*railway*)
    fail "RAD ETILDI: maqsad URL production belgilarini o'z ichiga oladi." ;;
esac

# Maqsad xavfsiz — endi vositalarni tanlaymiz (PG18 pinlangan binarlar).
. "$HERE/lib/pg_client.sh"
pg_client_resolve

# ── 2) ARTEFAKT TARKIBI — AYNAN BITTA to'plam bo'lishi shart ───────────────
shopt -s nullglob
ENC_FILES=("$ART_DIR"/*.dump.gpg)
SUM_FILES=("$ART_DIR"/*.dump.sha256)
META_FILES=("$ART_DIR"/*.meta.json)
shopt -u nullglob

[ "${#ENC_FILES[@]}" -ne 0 ] || fail "artefaktda shifrlangan nusxa (*.dump.gpg) YO'Q. \
Ochiq dump yuklanmaydi — demak bu artefakt yaroqsiz yoki noto'g'ri run tanlangan."
[ "${#ENC_FILES[@]}" -eq 1 ] || fail "artefaktda ${#ENC_FILES[@]} ta *.dump.gpg bor — QAYSI BIRI ekani NOANIQ. To'xtatildi."
[ "${#SUM_FILES[@]}" -eq 1 ] || fail "artefaktda checksum fayli (*.dump.sha256) aniq bitta emas (${#SUM_FILES[@]})."
[ "${#META_FILES[@]}" -eq 1 ] || fail "artefaktda metadata (*.meta.json) aniq bitta emas (${#META_FILES[@]})."

ENC="${ENC_FILES[0]}"
SUM="${SUM_FILES[0]}"
META="${META_FILES[0]}"
PLAINTEXT="${ENC%.gpg}"

# Ochiq dump artefaktda BO'LMASLIGI kerak — bo'lsa bu jiddiy xavfsizlik nuqsoni.
shopt -s nullglob
STRAY=("$ART_DIR"/*.dump)
shopt -u nullglob
[ "${#STRAY[@]}" -eq 0 ] || fail "XAVFSIZLIK: artefaktda OCHIQ dump bor (${STRAY[0]}). \
Shifrlanmagan nusxa saqlanmasligi kerak edi."

echo "artefakt: $(basename "$ENC") ($(wc -c < "$ENC") bayt)"
echo "metadata: $(basename "$META")"

# ── 3) METADATA — o'qiladigan JSON va kerakli maydonlar ────────────────────
PY="${PYTHON:-python}"
"$PY" - "$META" <<'PYEOF' || fail "metadata yaroqsiz — artefakt ishonchsiz."
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    m = json.load(f)
missing = [k for k in ("file", "sha256", "size_bytes", "created_at_utc") if k not in m]
if missing:
    print("metadata maydonlari yetishmayapti: %s" % missing, file=sys.stderr)
    raise SystemExit(1)
if len(str(m["sha256"])) != 64:
    print("sha256 uzunligi noto'g'ri", file=sys.stderr)
    raise SystemExit(1)
print("  created_at_utc = %s" % m["created_at_utc"])
print("  size_bytes     = %s" % m["size_bytes"])
print("  schemas        = %s" % m.get("schemas_present", "<yo'q>"))
print("  pg_dump        = %s" % m.get("pg_dump_version", "<yo'q>"))
PYEOF

# ── 3b) SHIFRLANGAN faylning checksum'i (bo'lsa) — OCHISHDAN OLDIN ─────────
# Kelajakdagi artefaktlarda `sha256_encrypted` bo'ladi va butunlikni shifrni
# ochmasdan tekshirish mumkin. Eski artefaktlarda u YO'Q — jimgina o'tkazmaymiz,
# aniq aytamiz (ochiq dump checksum'i baribir tiklashdan OLDIN tekshiriladi).
ENC_SHA_EXPECTED="$("$PY" -c "
import json,sys
m=json.load(open(sys.argv[1],encoding='utf-8'))
print(m.get('sha256_encrypted',''))" "$META")"
if [ -n "$ENC_SHA_EXPECTED" ]; then
  ENC_SHA_ACTUAL="$(cd "$ART_DIR" && sha256sum "$(basename "$ENC")" | awk '{print $1}')"
  [ "$ENC_SHA_ACTUAL" = "$ENC_SHA_EXPECTED" ] \
    || fail "SHIFRLANGAN fayl checksum'i MOS EMAS — artefakt buzilgan. Tiklash boshlanmadi."
  echo "shifrlangan checksum: MOS (ochishdan oldin tekshirildi)"
else
  echo "::warning::bu artefaktda 'sha256_encrypted' yo'q (eski format) — butunlik shifr ochilgach tekshiriladi."
fi

# ── 4) SHIFRNI OCHISH ──────────────────────────────────────────────────────
echo "== shifr ochilmoqda =="
gpg --batch --yes --quiet --passphrase "$BACKUP_PASSPHRASE" -o "$PLAINTEXT" -d "$ENC" 2>/dev/null \
  || fail "SHIFR OCHILMADI. Parol noto'g'ri yoki fayl buzilgan — bu nusxa TIKLANMAYDI. \
(BACKUP_PASSPHRASE almashtirilgan bo'lsa eski nusxalar ochilmaydi.)"
[ -s "$PLAINTEXT" ] || fail "shifr ochildi, lekin natija BO'SH."
echo "ochildi: $(wc -c < "$PLAINTEXT") bayt"

# ── 5) OCHIQ DUMP CHECKSUM'I — TIKLASHDAN OLDIN ───────────────────────────
# Bu artefakt yozilgandagi bilan BIR XIL bayt ekanini isbotlaydi.
EXPECTED="$(awk '{print $1}' < "$SUM")"
ACTUAL="$(cd "$(dirname "$PLAINTEXT")" && sha256sum "$(basename "$PLAINTEXT")" | awk '{print $1}')"
if [ "$ACTUAL" != "$EXPECTED" ]; then
  fail "CHECKSUM MOS EMAS — artefakt buzilgan. Kutilgan: $EXPECTED, olingan: $ACTUAL. TIKLASH BOSHLANMADI."
fi
echo "ochiq dump checksum: MOS ($EXPECTED)"

# ── 6) TIKLASH — mavjud mashq skripti (rollar, FK, barmoq izi) ────────────
# Yangi dump OLINMAYDI: `restore_rehearsal.sh` ga TAYYOR fayl beriladi.
echo "== tiklash (bir martalik bazaga) =="
CAPTURE_FP="$ART_DIR/fingerprint.json"
if [ -f "$CAPTURE_FP" ]; then
  echo "capture-time barmoq izi topildi — solishtiriladi"
  BEFORE_FINGERPRINT="$CAPTURE_FP" \
  AFTER_FINGERPRINT="${AFTER_FINGERPRINT:-$ART_DIR/after.json}" \
    "$HERE/restore_rehearsal.sh" "$PLAINTEXT"
else
  echo "::warning::artefaktda capture-time barmoq izi (fingerprint.json) YO'Q — \
tiklash tekshiriladi, LEKIN to'liqlik solishtirilmaydi."
  AFTER_FINGERPRINT="${AFTER_FINGERPRINT:-$ART_DIR/after.json}" \
    "$HERE/restore_rehearsal.sh" "$PLAINTEXT"
fi

echo "ARTIFACT_RESTORE_OK"
