#!/usr/bin/env bash
# SavdoOS · PostgreSQL mijoz binarlarini ANIQ tanlash + versiya gardi.
#
# ═══ NEGA BU FAYL BOR ════════════════════════════════════════════════════════
# Birinchi HAQIQIY production backup'i AYNAN shu sababdan yiqildi:
#
#     pg_dump: error: aborting because of server version mismatch
#     server version: 18.6 ... pg_dump version: 16.15
#
# Holbuki workflow `postgresql-client-17` ni MUVAFFAQIYATLI o'rnatgan edi (17.11).
# Sabab: Debian/Ubuntu'da `/usr/bin/pg_dump` — bu haqiqiy binar EMAS, u
# `/usr/share/postgresql-common/pg_wrapper` ga symlink. Wrapper qaysi versiyani
# ishga tushirishni O'ZI hal qiladi (standart klaster bo'yicha), va GitHub runner
# obrazida PostgreSQL 16 oldindan o'rnatilgani uchun u DOIM 16 ni tanlardi.
# Ya'ni yangi mijozni o'rnatish YETARLI EMAS — binar ANIQ ko'rsatilishi kerak.
#
# Shu bois: hech qachon PATH'dagi `pg_dump` ga ishonmaymiz. Versiyali katalogdan
# (`/usr/lib/postgresql/<major>/bin`) ANIQ binar tanlanadi va ishlatishdan OLDIN
# server bilan solishtiriladi.
#
# Ishlatish:
#     . scripts/lib/pg_client.sh
#     pg_client_resolve            # PG_DUMP / PG_RESTORE / PSQL o'zgaruvchilarini to'ldiradi
#     pg_client_require_ge "$URL"  # mijoz major >= server major ekanini TASDIQLAYDI
#
# Bekor qilish: PG_BIN=/usr/lib/postgresql/18/bin (yoki pgserver bin katalogi).

# `fail` chaqiruvchi skriptda aniqlanadi; bo'lmasa oddiy variant.
if ! command -v fail >/dev/null 2>&1 && ! declare -F fail >/dev/null 2>&1; then
  fail() { echo "::error::$*" >&2; exit 1; }
fi

# Faqat SON qismi: "pg_dump (PostgreSQL) 18.1 (Ubuntu ...)" -> 18
_pg_major_from_version_output() {
  # BIRINCHI sonni oladi:
  #   "pg_dump (PostgreSQL) 18.1 (Ubuntu 18.1-1.pgdg24.04+1)" -> 18
  #   "18.6 (Debian 18.6-1.pgdg13+2)"                          -> 18
  #
  # DIQQAT: bu yerda ochko'z ".*(son).*" naqshini ISHLATIB BO'LMAYDI — u OXIRGI sonni
  # tutadi va "18.1-1" dan 1 chiqarardi (major 18 o'rniga 1). Regressiya testi aynan
  # shuni ushlagan; shu bois birinchi sonni grep bilan olamiz.
  #
  # `|| true` SHART: chaqiruvchi skript `set -Eeuo pipefail` bilan ishlaydi. Mos son
  # topilmasa `grep` 1 qaytaradi va pipefail tufayli skript JIMGINA to'xtardi — ya'ni
  # "server versiyasini aniqlab bo'lmadi" xabari HECH QACHON chiqmasdi (regressiya
  # testi shuni ushladi). Bo'sh natija qaytaramiz; qarorni pg_client_require_ge beradi.
  printf '%s\n' "$1" | head -1 | grep -oE '[0-9]+' | head -1 || true
}

pg_client_major() {   # pg_client_major <binar>
  _pg_major_from_version_output "$("$1" --version 2>/dev/null)"
}

pg_server_major() {   # pg_server_major <url>
  # `SHOW server_version` -> "18.6 (Debian 18.6-1.pgdg13+2)"
  _pg_major_from_version_output "$("$PSQL" -tAc 'SHOW server_version' "$1" 2>/dev/null)"
}

# PG_DUMP / PG_RESTORE / PSQL ni to'ldiradi. Tanlov tartibi:
#   1) PG_BIN aniq berilgan bo'lsa — SHU
#   2) /usr/lib/postgresql/<major>/bin — ENG YUQORI major
#   3) PATH (oxirgi chora; pg_wrapper xavfi bor, shu bois ogohlantiramiz)
pg_client_resolve() {
  local dir=""

  if [ -n "${PG_BIN:-}" ]; then
    dir="$PG_BIN"
    [ -x "$dir/pg_dump" ] || [ -x "$dir/pg_dump.exe" ] \
      || fail "PG_BIN='$dir' — bu katalogda pg_dump topilmadi."
  else
    # Versiyali kataloglar orasidan ENG YUQORI major (18 > 17 > 16 ...).
    local best=0 cand
    for cand in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin /opt/homebrew/opt/postgresql@*/bin; do
      [ -x "$cand/pg_dump" ] || continue
      local m
      m="$(pg_client_major "$cand/pg_dump")"
      case "$m" in ''|*[!0-9]*) continue ;; esac
      if [ "$m" -gt "$best" ]; then best="$m"; dir="$cand"; fi
    done
    if [ -z "$dir" ]; then
      command -v pg_dump >/dev/null 2>&1 \
        || fail "pg_dump topilmadi. PostgreSQL client o'rnating (yoki PG_BIN bering)."
      echo "::warning::Versiyali PostgreSQL katalogi topilmadi — PATH'dagi binar ishlatiladi." \
           "Debian/Ubuntu'da bu pg_wrapper bo'lishi va ESKI versiyani tanlashi mumkin."
      PG_DUMP="$(command -v pg_dump)"
      PG_RESTORE="$(command -v pg_restore)"
      PSQL="$(command -v psql)"
      export PG_DUMP PG_RESTORE PSQL
      return 0
    fi
  fi

  # `.exe` — Windows (pgserver) uchun
  if [ -x "$dir/pg_dump" ]; then
    PG_DUMP="$dir/pg_dump"; PG_RESTORE="$dir/pg_restore"; PSQL="$dir/psql"
  else
    PG_DUMP="$dir/pg_dump.exe"; PG_RESTORE="$dir/pg_restore.exe"; PSQL="$dir/psql.exe"
  fi
  export PG_DUMP PG_RESTORE PSQL
}

# Mijoz serverdan ESKI bo'lmasligi SHART.
#
# pg_dump serverdan eski bo'lsa QAT'IY rad etadi (bizni yiqitgan holat). pg_dump YANGI
# bo'lishi esa qo'llab-quvvatlanadi va xavfsiz — shu bois shart `>=`, `==` EMAS
# (aks holda Railway serverni yangilagan kunning ertasiga backup to'xtardi).
pg_client_require_ge() {   # pg_client_require_ge <url>
  local srv cli
  srv="$(pg_server_major "$1")"
  cli="$(pg_client_major "$PG_DUMP")"

  case "$srv" in ''|*[!0-9]*) fail "server versiyasini aniqlab bo'lmadi (ulanish xatomi?)." ;; esac
  case "$cli" in ''|*[!0-9]*) fail "pg_dump versiyasini aniqlab bo'lmadi: $PG_DUMP" ;; esac

  echo "PostgreSQL · server_major=$srv · pg_dump_major=$cli · binar=$PG_DUMP"

  if [ "$cli" -lt "$srv" ]; then
    fail "MIJOZ ESKI: pg_dump major=$cli, server major=$srv. pg_dump bunday holatda \
ATAYLAB rad etadi va NUSXA OLINMAYDI. postgresql-client-$srv o'rnating va \
/usr/lib/postgresql/$srv/bin ni ishlating (PATH'dagi pg_dump pg_wrapper bo'lishi mumkin)."
  fi
}
